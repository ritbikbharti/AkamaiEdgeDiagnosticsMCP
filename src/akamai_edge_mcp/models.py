"""Pydantic v2 input schemas for every MCP tool exposed by this server.

Each model becomes the JSON schema the LLM client sees. Field descriptions
are surfaced verbatim, so they should be useful to a non-Akamai expert.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

IPVersion = Literal["IPV4", "IPV6"]
DigQueryType = Literal[
    "A", "AAAA", "CNAME", "MX", "NS", "PTR", "SOA", "TXT", "SRV", "CAA", "ANY"
]
HttpMethod = Literal["GET", "HEAD", "POST"]
MdtFormat = Literal["summary", "full"]
PacketType = Literal["ICMP", "TCP"]
DestinationType = Literal["IP", "HOST"]
SourceType = Literal["EDGE_IP", "LOCATION"]
EstatsErrorType = Literal["EDGE_ERRORS", "ORIGIN_ERRORS"]
EstatsDelivery = Literal["STANDARD_TLS", "ENHANCED_TLS"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- diagnostics ----------


class UrlHealthCheckInput(_Base):
    url: HttpUrl = Field(..., description="The full URL to health-check, e.g. https://www.example.com/path.")
    ip_version: IPVersion = Field(
        "IPV4", description="IP family to test against. IPV4 or IPV6."
    )
    spoof_edge_ip: str | None = Field(
        None,
        description=(
            "Optional Akamai edge IP address to spoof for the request. Use list_edge_locations "
            "or verify_ip to find a valid edge IP."
        ),
    )
    timeout_seconds: int = Field(
        90, ge=10, le=300, description="Maximum seconds to wait for the async result."
    )


class DigInput(_Base):
    hostname: str = Field(..., description="The hostname to look up, e.g. www.example.com.")
    query_type: DigQueryType = Field("A", description="DNS record type to query.")
    is_gtm_hostname: bool = Field(
        False,
        description=(
            "Whether the hostname is an Akamai Global Traffic Management (GTM) "
            "hostname. Set true only if you know the property is GTM-managed; "
            "Akamai treats GTM lookups specially."
        ),
    )
    edge_location_id: str | None = Field(
        None,
        description=(
            "ID of the Akamai edge location to dig from (see list_edge_locations). "
            "If omitted, Akamai picks a default."
        ),
    )
    edge_ip: str | None = Field(
        None,
        description=(
            "Specific edge server IP to dig from. Mutually exclusive with edge_location_id; "
            "use one or the other."
        ),
    )


class MtrInput(_Base):
    destination: str = Field(
        ..., description="The destination hostname or IP address to MTR towards."
    )
    destination_type: DestinationType | None = Field(
        None,
        description=(
            "'IP' or 'HOST'. If omitted, auto-detected from destination "
            "(IP-shaped → IP, otherwise HOST)."
        ),
    )
    packet_type: PacketType = Field(
        "ICMP",
        description=(
            "Probe protocol. ICMP is more universal; TCP works through "
            "firewalls that drop ICMP."
        ),
    )
    port: int | None = Field(
        None,
        description="Destination port, only valid with packet_type=TCP. Allowed values: 80 or 443.",
    )
    resolve_dns: bool = Field(
        True, description="Whether to resolve DNS for intermediate hops (PTR lookups)."
    )
    show_ips: bool = Field(True, description="Include IP addresses for hops in the result.")
    show_locations: bool = Field(
        True, description="Include geolocation info for hops in the result."
    )
    source: str | None = Field(
        None,
        description=(
            "Edge IP address or location ID to run the MTR from. "
            "Pair with source_type to disambiguate."
        ),
    )
    source_type: SourceType | None = Field(
        None,
        description="'EDGE_IP' if source is an IP, 'LOCATION' if source is an edge location ID.",
    )
    site_shield_hostname: str | None = Field(
        None,
        description="Optional Site Shield hostname to MTR from instead of a regular edge.",
    )


class CurlInput(_Base):
    url: HttpUrl = Field(..., description="URL to fetch from the edge server.")
    edge_ip: str | None = Field(
        None,
        description="Edge server IP to issue the request from. If omitted Akamai chooses one.",
    )
    edge_location_id: str | None = Field(
        None, description="Edge location ID to source from. Mutually exclusive with edge_ip."
    )
    spoof_edge_ip: str | None = Field(
        None,
        description="Edge IP to spoof for the test (different from the source edge_ip).",
    )
    request_headers: dict[str, str] | None = Field(
        None,
        description=(
            "Additional request headers to send, as a name->value mapping. To override "
            "User-Agent, set it here. (The previous separate user_agent param is gone.)"
        ),
    )
    sensitive_request_header_keys: list[str] | None = Field(
        None,
        description=(
            "Header names whose values Akamai should redact from long-term storage "
            "(e.g. ['Authorization', 'Cookie'])."
        ),
    )
    run_from_site_shield: bool = Field(
        False, description="Issue the request from a Site Shield region instead of a regular edge."
    )
    ip_version: IPVersion = Field("IPV4", description="IP family to use.")


# ---------- translate ----------


class TranslateErrorStringInput(_Base):
    error_code: str = Field(
        ...,
        description=(
            "The Akamai reference error code shown on edge error pages, "
            "e.g. '9.abc12345.1234567890.abcdef'."
        ),
    )
    trace_forward_logs: bool = Field(
        False,
        description=(
            "If true, also retrieve forward (origin) trace logs in addition to the "
            "edge logs. Slower but useful when diagnosing origin-side problems."
        ),
    )
    timeout_seconds: int = Field(
        90,
        ge=10,
        le=300,
        description="Maximum seconds to wait while polling for the translated result.",
    )


# ---------- logs / estats ----------


class GrepLogsInput(_Base):
    edge_ip: str = Field(
        ...,
        description=(
            "Edge server IP to grep logs from. Required by Akamai. Use list_edge_locations "
            "or verify_ip to discover one."
        ),
    )
    cp_code: int = Field(
        ..., ge=1, description="Akamai CP code that owns the traffic. Required by Akamai."
    )
    arl: str | None = Field(
        None,
        description="ARL (Akamai Resource Locator) to filter on, e.g. /L/123/456/.../path.",
    )
    client_ip: str | None = Field(None, description="Client IP address to filter on.")
    object_status: str | None = Field(
        None, description="Object status code to filter on (Akamai-specific status codes)."
    )
    http_status_code: int | None = Field(
        None, description="HTTP status code to filter on, e.g. 502."
    )
    user_agent: str | None = Field(
        None, description="User-Agent substring to filter on."
    )
    start: str | None = Field(
        None,
        description="ISO 8601 start timestamp, e.g. 2026-05-02T15:00:00Z. Defaults to recent.",
    )
    end: str | None = Field(
        None, description="ISO 8601 end timestamp. Defaults to now."
    )
    log_type: str | None = Field(
        None,
        description="Type of log to grep (e.g. 'EDGE'). Akamai-specific; omit for the default.",
    )


class EstatsInput(_Base):
    url: HttpUrl | None = Field(
        None, description="URL to fetch error stats for. Either url or cp_code is required."
    )
    cp_code: int | None = Field(
        None, ge=1, description="Akamai CP code to fetch error stats for."
    )
    error_type: EstatsErrorType | None = Field(
        None,
        description="Filter to EDGE_ERRORS or ORIGIN_ERRORS only. Omit for both.",
    )
    delivery: EstatsDelivery | None = Field(
        None,
        description="Filter by delivery network: STANDARD_TLS or ENHANCED_TLS.",
    )


# ---------- locations / IP ----------


class VerifyIpInput(_Base):
    ip_address: str = Field(..., description="The IPv4 or IPv6 address to check.")


class LocateIpInput(_Base):
    ip_address: str = Field(..., description="The IPv4 or IPv6 address to geolocate.")


class VerifyAndLocateIpInput(_Base):
    ip_address: str = Field(
        ..., description="IP address to both verify as Akamai-owned and geolocate."
    )


class ListEdgeLocationsInput(_Base):
    pass


# ---------- problems ----------


class ConnectivityProblemsInput(_Base):
    url: HttpUrl = Field(..., description="The URL exhibiting connectivity / latency problems.")
    ip_version: IPVersion = Field("IPV4", description="IP family to test against.")
    spoof_edge_ip: str | None = Field(
        None, description="Edge IP to spoof during diagnosis."
    )
    timeout_seconds: int = Field(
        120, ge=10, le=300, description="Maximum seconds to wait for the async result."
    )


class ContentProblemsInput(_Base):
    url: HttpUrl = Field(..., description="The URL exhibiting incorrect or stale content.")
    ip_version: IPVersion = Field("IPV4", description="IP family to test against.")
    spoof_edge_ip: str | None = Field(
        None, description="Edge IP to spoof during diagnosis."
    )
    timeout_seconds: int = Field(
        120, ge=10, le=300, description="Maximum seconds to wait for the async result."
    )


# ---------- translated URL / user diagnostic data ----------


class TranslatedUrlInput(_Base):
    url: HttpUrl = Field(
        ...,
        description=(
            "An Akamai staging or production ARL/URL (e.g. "
            "https://aXX.akamai.net/...) to translate into its origin "
            "and routing details."
        ),
    )


class CreateUserDiagnosticLinkInput(_Base):
    url: HttpUrl | None = Field(
        None,
        description=(
            "URL the end user will be sent to. The diagnostic harness collects their "
            "IP/geo/connection data when they visit this URL."
        ),
    )
    note: str | None = Field(
        None, description="Free-form note shown alongside the diagnostic group."
    )
    ipa_hostname: str | None = Field(
        None,
        description="IP Acceleration hostname, if collecting through an IPA-enabled property.",
    )


class ListUserDiagnosticGroupsInput(_Base):
    pass


class GetUserDiagnosticDataInput(_Base):
    group_id: str = Field(
        ..., description="The diagnostic data group ID to fetch collected records for."
    )


# ---------- metadata tracer (MDT) ----------


class MetadataTraceInput(_Base):
    url: HttpUrl = Field(
        ...,
        description=(
            "URL configured in Property Manager you want to trace metadata behaviors / "
            "criteria for, e.g. https://www.example.com/some/path."
        ),
    )
    edge_ip: str | None = Field(
        None,
        description=(
            "Edge server IP to source the trace from. Mutually exclusive with "
            "mdt_location_id; provide one or the other."
        ),
    )
    mdt_location_id: str | None = Field(
        None,
        description=(
            "MDT-specific edge location ID (see list_mdt_locations). Mutually "
            "exclusive with edge_ip."
        ),
    )
    http_method: HttpMethod = Field(
        "GET", description="HTTP method to simulate. One of GET, HEAD, POST."
    )
    http_body: str | None = Field(
        None,
        max_length=4096,
        description="Request body for POST. 1-4096 chars. Ignored unless http_method is POST.",
    )
    request_headers: list[str] | None = Field(
        None,
        description=(
            "Custom request headers as a list of 'Header-Name: value' strings, "
            "e.g. ['X-Foo: bar', 'Accept-Language: en']."
        ),
    )
    sensitive_request_header_keys: list[str] | None = Field(
        None,
        description=(
            "Header names to mark sensitive so Akamai excludes their values from "
            "long-term storage."
        ),
    )
    use_staging: bool = Field(
        False,
        description="Route the trace through the Akamai staging network instead of production.",
    )
    disable_default_headers: bool = Field(
        False,
        description=(
            "By default, when no request_headers are supplied, this tool injects "
            "'User-Agent: akamai-edge-mcp/<version>' and 'Accept: */*' so the trace "
            "actually runs (a bare GET typically returns empty traceInformation with "
            "exitCode 92). Set true to send the bare request anyway."
        ),
    )
    format: MdtFormat = Field(
        "summary",
        description=(
            "Response shape. 'summary' (default) returns counts, features fired, "
            "failureSummary, and suggestedActions — small enough to inline. "
            "'full' returns everything Akamai returned plus enriched traceInformation "
            "(each line annotated with feature/ruleName from arlDataXml) and "
            "failureSummary. Use 'full' when you need the raw arlDataXml or per-line "
            "stage details."
        ),
    )
    timeout_seconds: int = Field(
        120,
        ge=10,
        le=300,
        description="Maximum seconds to wait while polling for the trace result.",
    )


class ListMdtLocationsInput(_Base):
    pass
