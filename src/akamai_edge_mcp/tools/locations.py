"""Edge location listing and IP verification tools."""

from __future__ import annotations

from typing import Any

from ..client import AkamaiEdgeDiagnosticsClient
from ..models import (
    CreateUserDiagnosticLinkInput,
    GetUserDiagnosticDataInput,
    ListEdgeLocationsInput,
    ListUserDiagnosticGroupsInput,
    LocateIpInput,
    VerifyAndLocateIpInput,
    VerifyIpInput,
)


async def list_edge_locations(
    client: AkamaiEdgeDiagnosticsClient, params: ListEdgeLocationsInput
) -> dict[str, Any]:
    """List Akamai edge locations available for diagnostic tools.

    Use the returned ``id`` values as ``edge_location_id`` for dig, mtr, and curl.
    """
    return await client.get("/edge-locations")


async def verify_ip(
    client: AkamaiEdgeDiagnosticsClient, params: VerifyIpInput
) -> dict[str, Any]:
    """Verify whether an IPv4 or IPv6 address belongs to Akamai's edge network."""
    return await client.post("/verify-edge-ip", json={"ipAddresses": [params.ip_address]})


async def locate_ip(
    client: AkamaiEdgeDiagnosticsClient, params: LocateIpInput
) -> dict[str, Any]:
    """Geolocate an IP address using Akamai's network data."""
    return await client.post("/locate-ip", json={"ipAddresses": [params.ip_address]})


async def verify_and_locate_ip(
    client: AkamaiEdgeDiagnosticsClient, params: VerifyAndLocateIpInput
) -> dict[str, Any]:
    """Combined: check whether an IP is Akamai-owned AND geolocate it in one call."""
    return await client.post(
        "/verify-locate-ip", json={"ipAddress": params.ip_address}
    )


async def create_user_diagnostic_link(
    client: AkamaiEdgeDiagnosticsClient, params: CreateUserDiagnosticLinkInput
) -> dict[str, Any]:
    """Create a diagnostic data collection group and get a shareable link.

    The returned link can be sent to an end user; visiting it captures
    their IP, geolocation, ASN, and connection diagnostics for later
    retrieval via get_user_diagnostic_data.
    """
    body: dict[str, Any] = {}
    if params.url:
        body["url"] = str(params.url)
    if params.note:
        body["note"] = params.note
    if params.ipa_hostname:
        body["ipaHostname"] = params.ipa_hostname
    return await client.post("/user-diagnostic-data/groups", json=body)


async def list_user_diagnostic_groups(
    client: AkamaiEdgeDiagnosticsClient, params: ListUserDiagnosticGroupsInput
) -> dict[str, Any]:
    """List existing user-diagnostic-data groups created on this account."""
    return await client.get("/user-diagnostic-data/groups")


async def get_user_diagnostic_data(
    client: AkamaiEdgeDiagnosticsClient, params: GetUserDiagnosticDataInput
) -> dict[str, Any]:
    """Fetch the records collected by a user-diagnostic-data group.

    Each record represents one end-user visit and includes their IP,
    geolocation, ASN, and connection details.
    """
    return await client.get(
        f"/user-diagnostic-data/groups/{params.group_id}/records"
    )
