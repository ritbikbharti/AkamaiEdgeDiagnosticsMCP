"""Connectivity and content problem diagnosis tools (async + polling)."""

from __future__ import annotations

from typing import Any

from ..client import AkamaiEdgeDiagnosticsClient
from ..models import ConnectivityProblemsInput, ContentProblemsInput
from ..polling import poll_until_complete


async def get_connectivity_problems(
    client: AkamaiEdgeDiagnosticsClient, params: ConnectivityProblemsInput
) -> dict[str, Any]:
    """Diagnose connectivity / latency problems for a URL.

    Akamai runs a battery of edge-side probes (DNS, TCP, TLS, HTTP) and
    reports which stages are slow or failing. Async — this kicks off the
    request and polls until completion.
    """
    body: dict[str, Any] = {
        "url": str(params.url),
        "ipVersion": params.ip_version,
    }
    if params.spoof_edge_ip:
        body["spoofEdgeIp"] = params.spoof_edge_ip

    initial = await client.post("/connectivity-problems", json=body)
    return await poll_until_complete(
        client,
        initial,
        poll_path_template="/connectivity-problems/requests/{request_id}",
        timeout_seconds=params.timeout_seconds,
    )


async def get_content_problems(
    client: AkamaiEdgeDiagnosticsClient, params: ContentProblemsInput
) -> dict[str, Any]:
    """Diagnose incorrect, stale, or partially delivered content for a URL.

    Akamai compares cached vs. origin responses and reports cache state,
    response code mismatches, and partial-download symptoms. Async.
    """
    body: dict[str, Any] = {
        "url": str(params.url),
        "ipVersion": params.ip_version,
    }
    if params.spoof_edge_ip:
        body["spoofEdgeIp"] = params.spoof_edge_ip

    initial = await client.post("/content-problems", json=body)
    return await poll_until_complete(
        client,
        initial,
        poll_path_template="/content-problems/requests/{request_id}",
        timeout_seconds=params.timeout_seconds,
    )
