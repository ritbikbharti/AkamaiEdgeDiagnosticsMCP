"""Edge server log search (grep) and error stats (estats) tools."""

from __future__ import annotations

from typing import Any

from ..client import AkamaiEdgeDiagnosticsClient
from ..models import EstatsInput, GrepLogsInput


async def get_grep_logs(
    client: AkamaiEdgeDiagnosticsClient, params: GrepLogsInput
) -> dict[str, Any]:
    """Search Akamai edge server logs (grep).

    Akamai requires both ``edge_ip`` and ``cp_code``. Optional filters
    narrow the result by ARL, client IP, object/HTTP status, user-agent,
    and time window. Results include matching log lines from the named
    edge server.
    """
    query: dict[str, Any] = {
        "edgeIp": params.edge_ip,
        "cpCode": params.cp_code,
    }
    if params.arl:
        query["arl"] = params.arl
    if params.client_ip:
        query["clientIp"] = params.client_ip
    if params.object_status:
        query["objectStatus"] = params.object_status
    if params.http_status_code is not None:
        query["httpStatusCode"] = params.http_status_code
    if params.user_agent:
        query["userAgent"] = params.user_agent
    if params.start:
        query["start"] = params.start
    if params.end:
        query["end"] = params.end
    if params.log_type:
        query["logType"] = params.log_type

    return await client.get("/grep", params=query)


async def get_estats(
    client: AkamaiEdgeDiagnosticsClient, params: EstatsInput
) -> dict[str, Any]:
    """Fetch Akamai edge server error statistics for a URL or CP code.

    Either ``url`` or ``cp_code`` must be supplied. Optionally filter to
    EDGE_ERRORS / ORIGIN_ERRORS only via ``error_type``, or to a single
    delivery network (STANDARD_TLS / ENHANCED_TLS) via ``delivery``.
    """
    if not params.url and not params.cp_code:
        raise ValueError("Either url or cp_code is required for estats.")

    body: dict[str, Any] = {}
    if params.url:
        body["url"] = str(params.url)
    if params.cp_code:
        body["cpCode"] = params.cp_code
    if params.error_type:
        body["errorType"] = params.error_type
    if params.delivery:
        body["delivery"] = params.delivery

    return await client.post("/estats", json=body)
