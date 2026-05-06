"""URL health check, dig, mtr, and curl tools."""

from __future__ import annotations

import ipaddress
from typing import Any

from ..client import AkamaiEdgeDiagnosticsClient
from ..models import CurlInput, DigInput, MtrInput, UrlHealthCheckInput
from ..polling import poll_until_complete


def _looks_like_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


_HEADER_FORBIDDEN = ("\r", "\n", "\x00")


def _check_header_safety(name: str, value: str) -> None:
    """Reject CR/LF/NUL in header names or values to prevent header
    injection / request smuggling when Akamai forwards these to the
    target server.
    """
    for ch in _HEADER_FORBIDDEN:
        if ch in name or ch in value:
            raise ValueError(
                f"Header {name!r} contains illegal character {ch!r}; "
                "CR, LF, and NUL are forbidden to prevent header injection."
            )


def _format_request_headers(headers: dict[str, str]) -> list[str]:
    """Akamai's array form is a list of 'Name: value' strings."""
    for name, value in headers.items():
        _check_header_safety(name, value)
    return [f"{name}: {value}" for name, value in headers.items()]


async def run_url_health_check(
    client: AkamaiEdgeDiagnosticsClient, params: UrlHealthCheckInput
) -> dict[str, Any]:
    """Run a comprehensive Akamai URL health check.

    Combines DNS, TCP, and HTTP probes from edge servers and reports any
    routing/cache/origin issues. Async on the Akamai side: this kicks off
    the request and polls until completion (or until ``timeout_seconds``).
    """
    body: dict[str, Any] = {
        "url": str(params.url),
        "ipVersion": params.ip_version,
    }
    if params.spoof_edge_ip:
        body["spoofEdgeIp"] = params.spoof_edge_ip

    initial = await client.post("/url-health-check", json=body)
    return await poll_until_complete(
        client,
        initial,
        poll_path_template="/url-health-check/requests/{request_id}",
        timeout_seconds=params.timeout_seconds,
    )


async def run_dig(
    client: AkamaiEdgeDiagnosticsClient, params: DigInput
) -> dict[str, Any]:
    """Run ``dig`` from an Akamai edge server.

    Returns DNS resolution details (records, authority, additional sections,
    timing) for the requested hostname and query type.
    """
    if params.edge_location_id and params.edge_ip:
        raise ValueError("Provide either edge_location_id or edge_ip, not both.")

    body: dict[str, Any] = {
        "hostname": params.hostname,
        "queryType": params.query_type,
        "isGtmHostname": params.is_gtm_hostname,
    }
    if params.edge_location_id:
        body["edgeLocationId"] = params.edge_location_id
    if params.edge_ip:
        body["edgeIp"] = params.edge_ip

    return await client.post("/dig", json=body)


async def run_mtr(
    client: AkamaiEdgeDiagnosticsClient, params: MtrInput
) -> dict[str, Any]:
    """Run an MTR network trace from an Akamai edge server.

    Reports per-hop loss%, latency, and path information from the chosen
    edge source toward ``destination``. ``packet_type=ICMP`` works most
    places; switch to ``TCP`` (port 80 or 443) when ICMP is blocked.
    """
    if params.source and params.source_type is None:
        raise ValueError("source_type is required when source is provided.")
    if params.port is not None and params.packet_type != "TCP":
        raise ValueError("port is only valid when packet_type='TCP'.")
    if params.port is not None and params.port not in (80, 443):
        raise ValueError("port must be 80 or 443 (Akamai restriction).")

    destination_type = params.destination_type or (
        "IP" if _looks_like_ip(params.destination) else "HOST"
    )

    body: dict[str, Any] = {
        "destination": params.destination,
        "destinationType": destination_type,
        "packetType": params.packet_type,
        "resolveDns": params.resolve_dns,
        "showIps": params.show_ips,
        "showLocations": params.show_locations,
    }
    if params.source:
        body["source"] = params.source
        body["sourceType"] = params.source_type
    if params.port is not None:
        body["port"] = params.port
    if params.site_shield_hostname:
        body["siteShieldHostname"] = params.site_shield_hostname

    return await client.post("/mtr", json=body)


async def run_curl(
    client: AkamaiEdgeDiagnosticsClient, params: CurlInput
) -> dict[str, Any]:
    """Issue a cURL request from an Akamai edge server.

    Returns the response status, headers, body, and timing as observed by
    the edge. Useful for confirming what an edge sees vs. what a client sees.
    """
    if params.edge_ip and params.edge_location_id:
        raise ValueError("Provide either edge_ip or edge_location_id, not both.")

    body: dict[str, Any] = {
        "url": str(params.url),
        "ipVersion": params.ip_version,
        "runFromSiteShield": params.run_from_site_shield,
    }
    if params.edge_ip:
        body["edgeIp"] = params.edge_ip
    if params.edge_location_id:
        body["edgeLocationId"] = params.edge_location_id
    if params.spoof_edge_ip:
        body["spoofEdgeIp"] = params.spoof_edge_ip
    if params.request_headers:
        body["requestHeaders"] = _format_request_headers(params.request_headers)
    if params.sensitive_request_header_keys:
        body["sensitiveRequestHeaderKeys"] = params.sensitive_request_header_keys

    return await client.post("/curl", json=body)
