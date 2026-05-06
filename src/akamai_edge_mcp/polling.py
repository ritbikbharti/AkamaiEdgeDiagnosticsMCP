"""Shared polling helper for asynchronous Edge Diagnostics endpoints."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .client import AkamaiAPIError, AkamaiEdgeDiagnosticsClient

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 300
INITIAL_INTERVAL_SECONDS = 1.0
MAX_INTERVAL_SECONDS = 5.0
BACKOFF_FACTOR = 1.5

_DONE_STATES = {
    "SUCCESS",
    "SUCCEEDED",
    "FAILURE",
    "FAILED",
    "COMPLETED",
    "COMPLETE",
    "DONE",
    "FINISHED",
    "ERROR",
}
_IN_PROGRESS_STATES = {
    "IN_PROGRESS",
    "INPROGRESS",
    "PENDING",
    "QUEUED",
    "RUNNING",
    "STARTED",
    "PROCESSING",
    "WAITING",
    "ACCEPTED",
}


class PollingTimeoutError(RuntimeError):
    """Raised when an async Edge Diagnostics request does not finish in time."""

    def __init__(self, request_id: str, elapsed: float, last_status: str | None):
        self.request_id = request_id
        self.elapsed = elapsed
        self.last_status = last_status
        super().__init__(
            f"Request {request_id} did not complete within {elapsed:.1f}s "
            f"(last status: {last_status or 'unknown'})"
        )


def _extract_request_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("requestId", "request_id", "id"):
        if key in payload and payload[key]:
            return str(payload[key])
    nested = payload.get("request") if isinstance(payload.get("request"), dict) else None
    if nested:
        for key in ("requestId", "request_id", "id"):
            if nested.get(key):
                return str(nested[key])
    return None


def _extract_status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("executionStatus", "status", "state", "requestStatus"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.upper()
    return None


def _extract_retry_after(payload: Any) -> float | None:
    """Honor Akamai's ``retryAfter`` hint (seconds) when present."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("retryAfter")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _is_terminal(http_status: int, status: str | None, payload: Any) -> bool:
    """Decide whether a poll response is the final result.

    Priority of signals:
      1. HTTP 202 → always still running. Akamai's documented convention.
      2. Explicit ``status`` field in a known in-progress set → still running.
      3. Explicit ``status`` field in a known done set → done.
      4. Otherwise: 2xx with substantive payload → done.

    The earlier "no requestId in payload → done" heuristic is wrong: Akamai's
    GET poll responses echo the requestId back even after completion.
    """
    if http_status == 202:
        return False
    if status and status in _IN_PROGRESS_STATES:
        return False
    if status and status in _DONE_STATES:
        return True
    if isinstance(payload, dict) and any(
        k in payload for k in ("result", "results", "data", "error", "errors")
    ):
        return True
    if 200 <= http_status < 300 and payload not in (None, {}, []):
        return True
    return False


async def poll_until_complete(
    client: AkamaiEdgeDiagnosticsClient,
    initial_response: Any,
    *,
    poll_path_template: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Poll an async Edge Diagnostics endpoint until it returns a final result.

    ``initial_response`` is the JSON body of the kickoff POST. If it already
    contains the result inline (no ``requestId``), it is returned as-is.
    Otherwise we GET ``poll_path_template.format(request_id=...)`` on a
    bounded exponential backoff until the response indicates completion.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    timeout_seconds = min(timeout_seconds, MAX_TIMEOUT_SECONDS)

    request_id = _extract_request_id(initial_response)
    if request_id is None:
        return {
            "polling": False,
            "elapsed_seconds": 0.0,
            "result": initial_response,
        }

    start = time.monotonic()
    interval = INITIAL_INTERVAL_SECONDS
    last_status: str | None = None
    poll_count = 0

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= timeout_seconds:
            raise PollingTimeoutError(request_id, elapsed, last_status)

        await asyncio.sleep(min(interval, max(0.05, timeout_seconds - elapsed)))
        poll_count += 1
        try:
            http_status, payload = await client.get_with_status(
                poll_path_template.format(request_id=request_id)
            )
        except AkamaiAPIError as exc:
            if exc.status_code in (404, 425):
                interval = min(interval * BACKOFF_FACTOR, MAX_INTERVAL_SECONDS)
                continue
            raise

        last_status = _extract_status(payload)
        logger.debug(
            "Poll %d for %s: http=%d status=%s elapsed=%.2fs",
            poll_count,
            request_id,
            http_status,
            last_status,
            time.monotonic() - start,
        )
        if _is_terminal(http_status, last_status, payload):
            return {
                "polling": True,
                "request_id": request_id,
                "poll_count": poll_count,
                "elapsed_seconds": round(time.monotonic() - start, 2),
                "http_status": http_status,
                "status": last_status,
                "result": payload,
            }
        retry_after = _extract_retry_after(payload)
        backoff = min(interval * BACKOFF_FACTOR, MAX_INTERVAL_SECONDS)
        interval = max(retry_after, backoff) if retry_after else backoff
