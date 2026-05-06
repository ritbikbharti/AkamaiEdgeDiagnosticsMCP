"""Akamai error reference / URL translation tools."""

from __future__ import annotations

from typing import Any

from ..client import AkamaiEdgeDiagnosticsClient
from ..models import TranslatedUrlInput, TranslateErrorStringInput
from ..polling import poll_until_complete


async def translate_error_string(
    client: AkamaiEdgeDiagnosticsClient, params: TranslateErrorStringInput
) -> dict[str, Any]:
    """Decode an Akamai reference error code shown on edge error pages.

    The codes look like ``9.abc12345.1234567890.abcdef`` and contain the
    edge server, request time, and a pointer to detailed logs. Async on
    the Akamai side: this kicks off POST /error-translator (which returns
    a 202 + requestId), then polls
    GET /error-translator/requests/{requestId} until the translated result
    is ready. Set ``trace_forward_logs`` to also fetch origin-side logs.
    """
    body: dict[str, Any] = {"errorCode": params.error_code}
    if params.trace_forward_logs:
        body["traceForwardLogs"] = True

    initial = await client.post("/error-translator", json=body)
    return await poll_until_complete(
        client,
        initial,
        poll_path_template="/error-translator/requests/{request_id}",
        timeout_seconds=params.timeout_seconds,
    )


async def launch_translated_url(
    client: AkamaiEdgeDiagnosticsClient, params: TranslatedUrlInput
) -> dict[str, Any]:
    """Translate an Akamai staging/production ARL into routing details.

    Returns origin, type code, CP code, network, and other metadata
    encoded in an ``aXX.akamai.net``-style URL.
    """
    return await client.post("/translated-url", json={"url": str(params.url)})
