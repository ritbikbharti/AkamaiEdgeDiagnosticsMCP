"""Async HTTP client for the Akamai Edge Diagnostics API with EdgeGrid signing."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import requests
from akamai.edgegrid import EdgeGridAuth as RequestsEdgeGridAuth

from .config import EdgeGridCredentials

logger = logging.getLogger(__name__)

_REDACTED_QUERY_KEYS = {"accountSwitchKey"}
# Same keys, but as they might appear inside Akamai error response bodies.
_REDACTED_BODY_KEYS = {"accountSwitchKey", "account_switch_key"}


def _redact(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Redact account-identifying query params before logging."""
    if not params:
        return params
    return {k: ("***" if k in _REDACTED_QUERY_KEYS else v) for k, v in params.items()}


def _redact_body(value: Any) -> Any:
    """Defense-in-depth: walk a response body and redact any field whose
    key matches a known credential / account-identifier name. Akamai's
    problem+json normally doesn't echo request creds back, but if it ever
    does we don't want it flowing to the LLM.
    """
    if isinstance(value, dict):
        return {
            k: ("***" if k in _REDACTED_BODY_KEYS else _redact_body(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_body(item) for item in value]
    return value


class AkamaiAPIError(RuntimeError):
    """Raised when the Akamai API returns a non-2xx response."""

    def __init__(self, status_code: int, body: Any, *, method: str, url: str):
        self.status_code = status_code
        self.body = body
        self.method = method
        self.url = url
        super().__init__(f"Akamai API {method} {url} returned {status_code}: {body!r}")


class _EdgeGridHttpxAuth(httpx.Auth):
    """Bridge ``edgegrid-python``'s requests-based signer into ``httpx``.

    EdgeGrid signs the canonical request including the body, so the httpx
    auth flow needs the full body before signing.
    """

    requires_request_body = True

    def __init__(self, credentials: EdgeGridCredentials):
        self._signer = RequestsEdgeGridAuth(
            client_token=credentials.client_token,
            client_secret=credentials.client_secret,
            access_token=credentials.access_token,
            max_body=credentials.max_body,
        )

    def auth_flow(self, request: httpx.Request):
        prepared = requests.Request(
            method=request.method,
            url=str(request.url),
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            data=request.content or b"",
        ).prepare()
        signed = self._signer(prepared)
        request.headers["Authorization"] = signed.headers["Authorization"]
        yield request


class AkamaiEdgeDiagnosticsClient:
    """Thin async wrapper around the Edge Diagnostics REST surface.

    All Edge Diagnostics paths live under ``/edge-diagnostics/v1``. Methods
    accept the path *suffix* (e.g. ``"/dig"``) and prepend the prefix.
    """

    API_PREFIX = "/edge-diagnostics/v1"

    def __init__(
        self,
        credentials: EdgeGridCredentials,
        *,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._credentials = credentials
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=credentials.base_url,
            auth=_EdgeGridHttpxAuth(credentials),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> AkamaiEdgeDiagnosticsClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _full_path(self, path: str) -> str:
        if path.startswith(self.API_PREFIX):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.API_PREFIX}{path}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        _, body = await self.request_with_status(method, path, params=params, json=json)
        return body

    async def request_with_status(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> tuple[int, Any]:
        """Same as :meth:`request` but also returns the HTTP status code.

        The polling helper uses this to distinguish 202 (still running) from
        200 (completed) — the most reliable signal Akamai gives us.
        """
        full_path = self._full_path(path)
        merged = self._merge_params(params)
        logger.debug("Akamai %s %s params=%s", method, full_path, _redact(merged))
        response = await self._client.request(method, full_path, params=merged, json=json)
        body = self._handle_response(response, method=method, url=full_path)
        return response.status_code, body

    def _merge_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        ask = self._credentials.account_switch_key
        if not ask:
            return params
        merged = dict(params or {})
        merged.setdefault("accountSwitchKey", ask)
        return merged

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def get_with_status(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        return await self.request_with_status("GET", path, params=params)

    async def post(self, path: str, *, json: Any | None = None) -> Any:
        return await self.request("POST", path, json=json)

    @staticmethod
    def _handle_response(response: httpx.Response, *, method: str, url: str) -> Any:
        if response.status_code >= 400:
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
            raise AkamaiAPIError(
                response.status_code, _redact_body(body), method=method, url=url
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text, "content_type": response.headers.get("content-type")}
