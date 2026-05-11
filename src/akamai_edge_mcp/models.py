"""Pydantic v2 input schemas for every MCP tool exposed by this server.

Each model becomes the JSON schema the LLM client sees. Field descriptions
are surfaced verbatim, so they should be useful to a non-Akamai expert.

Every string and list field has an explicit ``max_length`` cap. These are
sized far above realistic Akamai inputs but bounded enough to defend
against the "oversized payload" DoS class described in
<https://www.akamai.com/blog/security/other-side-mcp-threat-conversation>.
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

# Response shape selector for case-mgmt / user-diagnostic read tools.
# "full" preserves v0.2.0 behavior (raw Akamai response); "summary" strips
# known-sensitive fields (case bodies, contact info, end-user IPs, ...).
# Default is "full" in v0.2.1 to avoid breaking existing callers; v0.3.0
# may flip the default to "summary" per Akamai MCP threat-model guidance.
ReadFormat = Literal["full", "summary"]

# --- size caps (defense against oversized-payload DoS) -----------------
# Strings
_MAX_HOSTNAME = 253          # RFC 1035 dotted-name limit
_MAX_IP = 45                 # max IPv6 string length
_MAX_ID = 128                # case/group/location IDs
_MAX_NAME = 256              # human-readable names, severity labels
_MAX_HEADER_LINE = 1024      # one "Name: value" entry
_MAX_QUERY = 512             # short query strings (object status, user-agent filter)
_MAX_TIMESTAMP = 64          # ISO 8601
_MAX_TEXT = 8192             # comments, notes, free-form text
_MAX_LARGE_TEXT = 32768      # case description body
_MAX_ARL = 4096              # ARL paths can be long
_MAX_ACCOUNT_IDS = 4096      # comma-separated id list query param
_MAX_CURSOR = 2048           # opaque pagination cursor
# Lists
_MAX_HEADER_LIST = 50        # request_headers / sensitive_request_header_keys
_MAX_EMAIL_LIST = 50         # also_notify recipients
# Dicts (curl request_headers as name->value mapping)
_MAX_HEADER_DICT = 50


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- diagnostics ----------


class UrlHealthCheckInput(_Base):
    url: HttpUrl = Field(
        ...,
        description="The full URL to health-check, e.g. https://www.example.com/path.",
    )
    ip_version: IPVersion = Field(
        "IPV4", description="IP family to test against. IPV4 or IPV6."
    )
    spoof_edge_ip: str | None = Field(
        None,
        max_length=_MAX_IP,
        description=(
            "Optional Akamai edge IP address to spoof for the request. Use list_edge_locations "
            "or verify_ip to find a valid edge IP."
        ),
    )
    timeout_seconds: int = Field(
        90, ge=10, le=300, description="Maximum seconds to wait for the async result."
    )


class DigInput(_Base):
    hostname: str = Field(
        ...,
        max_length=_MAX_HOSTNAME,
        description="The hostname to look up, e.g. www.example.com.",
    )
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
        max_length=_MAX_ID,
        description=(
            "ID of the Akamai edge location to dig from (see list_edge_locations). "
            "If omitted, Akamai picks a default."
        ),
    )
    edge_ip: str | None = Field(
        None,
        max_length=_MAX_IP,
        description=(
            "Specific edge server IP to dig from. Mutually exclusive with edge_location_id; "
            "use one or the other."
        ),
    )


class MtrInput(_Base):
    destination: str = Field(
        ...,
        max_length=_MAX_HOSTNAME,
        description="The destination hostname or IP address to MTR towards.",
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
        max_length=_MAX_HOSTNAME,
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
        max_length=_MAX_HOSTNAME,
        description="Optional Site Shield hostname to MTR from instead of a regular edge.",
    )


class CurlInput(_Base):
    url: HttpUrl = Field(..., description="URL to fetch from the edge server.")
    edge_ip: str | None = Field(
        None,
        max_length=_MAX_IP,
        description="Edge server IP to issue the request from. If omitted Akamai chooses one.",
    )
    edge_location_id: str | None = Field(
        None,
        max_length=_MAX_ID,
        description="Edge location ID to source from. Mutually exclusive with edge_ip.",
    )
    spoof_edge_ip: str | None = Field(
        None,
        max_length=_MAX_IP,
        description="Edge IP to spoof for the test (different from the source edge_ip).",
    )
    request_headers: dict[str, str] | None = Field(
        None,
        max_length=_MAX_HEADER_DICT,
        description=(
            "Additional request headers to send, as a name->value mapping. To override "
            "User-Agent, set it here. (The previous separate user_agent param is gone.)"
        ),
    )
    sensitive_request_header_keys: list[str] | None = Field(
        None,
        max_length=_MAX_HEADER_LIST,
        description=(
            "Header names whose values Akamai should redact from long-term storage "
            "(e.g. ['Authorization', 'Cookie'])."
        ),
    )
    run_from_site_shield: bool = Field(
        False,
        description="Issue the request from a Site Shield region instead of a regular edge.",
    )
    ip_version: IPVersion = Field("IPV4", description="IP family to use.")


# ---------- translate ----------


class TranslateErrorStringInput(_Base):
    error_code: str = Field(
        ...,
        max_length=_MAX_ID,
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
        max_length=_MAX_IP,
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
        max_length=_MAX_ARL,
        description="ARL (Akamai Resource Locator) to filter on, e.g. /L/123/456/.../path.",
    )
    client_ip: str | None = Field(
        None, max_length=_MAX_IP, description="Client IP address to filter on."
    )
    object_status: str | None = Field(
        None,
        max_length=_MAX_QUERY,
        description="Object status code to filter on (Akamai-specific status codes).",
    )
    http_status_code: int | None = Field(
        None, description="HTTP status code to filter on, e.g. 502."
    )
    user_agent: str | None = Field(
        None, max_length=_MAX_QUERY, description="User-Agent substring to filter on."
    )
    start: str | None = Field(
        None,
        max_length=_MAX_TIMESTAMP,
        description="ISO 8601 start timestamp, e.g. 2026-05-02T15:00:00Z. Defaults to recent.",
    )
    end: str | None = Field(
        None,
        max_length=_MAX_TIMESTAMP,
        description="ISO 8601 end timestamp. Defaults to now.",
    )
    log_type: str | None = Field(
        None,
        max_length=_MAX_QUERY,
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
    ip_address: str = Field(
        ..., max_length=_MAX_IP, description="The IPv4 or IPv6 address to check."
    )


class LocateIpInput(_Base):
    ip_address: str = Field(
        ..., max_length=_MAX_IP, description="The IPv4 or IPv6 address to geolocate."
    )


class VerifyAndLocateIpInput(_Base):
    ip_address: str = Field(
        ...,
        max_length=_MAX_IP,
        description="IP address to both verify as Akamai-owned and geolocate.",
    )


class ListEdgeLocationsInput(_Base):
    pass


# ---------- problems ----------


class ConnectivityProblemsInput(_Base):
    url: HttpUrl = Field(..., description="The URL exhibiting connectivity / latency problems.")
    ip_version: IPVersion = Field("IPV4", description="IP family to test against.")
    spoof_edge_ip: str | None = Field(
        None, max_length=_MAX_IP, description="Edge IP to spoof during diagnosis."
    )
    timeout_seconds: int = Field(
        120, ge=10, le=300, description="Maximum seconds to wait for the async result."
    )


class ContentProblemsInput(_Base):
    url: HttpUrl = Field(..., description="The URL exhibiting incorrect or stale content.")
    ip_version: IPVersion = Field("IPV4", description="IP family to test against.")
    spoof_edge_ip: str | None = Field(
        None, max_length=_MAX_IP, description="Edge IP to spoof during diagnosis."
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
        None,
        max_length=_MAX_TEXT,
        description="Free-form note shown alongside the diagnostic group.",
    )
    ipa_hostname: str | None = Field(
        None,
        max_length=_MAX_HOSTNAME,
        description="IP Acceleration hostname, if collecting through an IPA-enabled property.",
    )


class ListUserDiagnosticGroupsInput(_Base):
    pass


class GetUserDiagnosticDataInput(_Base):
    group_id: str = Field(
        ...,
        max_length=_MAX_ID,
        description="The diagnostic data group ID to fetch collected records for.",
    )
    format: ReadFormat = Field(
        "full",
        description=(
            "Response shape. 'full' (default) returns every collected record verbatim "
            "— including end-user IP, city-level geolocation, and ASN, all of which "
            "are PII under most jurisdictions. 'summary' strips the IP and city, "
            "keeping only counts, timestamps, country, and ASN. Pass 'summary' "
            "unless you actually need per-record PII for the diagnostic. v0.3.0 "
            "may flip this default to 'summary'."
        ),
    )


# ---------- case management ----------

CaseListType = Literal[
    "MY_ACTIVE_CASES", "MY_CLOSED_CASES", "ALL_ACTIVE_CASES", "ALL_CLOSED_CASES"
]
CaseCategoryId = Literal[
    "SECURITY",
    "MANAGED_CLOUD",
    "BUSINESS_SUPPORT",
    "PROFESSIONAL_SERVICES",
    "BILLING",
    "TECHNICAL",
]


class AlternateContact(_Base):
    name: str | None = Field(
        None, max_length=_MAX_NAME, description="Full name of the alternate contact."
    )
    email: str | None = Field(None, max_length=_MAX_NAME, description="Email address.")
    phone: str | None = Field(None, max_length=64, description="Phone number.")
    company: str | None = Field(
        None, max_length=_MAX_NAME, description="Company the contact works for."
    )


class ListAccountCategoriesInput(_Base):
    pass


class GetCaseCategoryInput(_Base):
    category_id: CaseCategoryId = Field(
        ...,
        description=(
            "Case category to fetch the schema for. Call this BEFORE create_case "
            "to discover the per-category required fields (severity values, "
            "valid productName / serviceName / problemName combinations, etc.)."
        ),
    )


class ListCasesInput(_Base):
    type: CaseListType = Field(
        ...,
        description=(
            "Which cases to list. MY_* = cases you opened; ALL_* = all cases on "
            "the account. ACTIVE = open; CLOSED = resolved."
        ),
    )
    duration: int | None = Field(
        None,
        description=(
            "Look-back window in days (omit to use the API default). Useful with "
            "*_CLOSED_CASES to limit history."
        ),
    )
    account_ids: str | None = Field(
        None,
        max_length=_MAX_ACCOUNT_IDS,
        description="Comma-separated account IDs to filter by. Omit for all accessible accounts.",
    )
    limit: int | None = Field(
        None, ge=1, description="Max cases to return per page."
    )
    cursor: str | None = Field(
        None,
        max_length=_MAX_CURSOR,
        description="Pagination cursor from a previous response.",
    )
    format: ReadFormat = Field(
        "full",
        description=(
            "Response shape. 'full' (default) returns each case object verbatim. "
            "'summary' returns just {caseId, status, severity, category, subject, "
            "createdTime, lastUpdatedTime} per case — strips description, "
            "alternateContact, alsoNotify, and other potentially-PII fields. "
            "v0.3.0 may flip this default to 'summary'."
        ),
    )


class CreateCaseInput(_Base):
    subject: str = Field(
        ...,
        max_length=255,
        description="Title of the case (≤255 chars). Make it short and specific.",
    )
    description: str = Field(
        ...,
        max_length=_MAX_LARGE_TEXT,
        description="Detailed description of the issue.",
    )
    account_id: str = Field(
        ...,
        max_length=_MAX_ID,
        description="Account to create the case under. Get from list_account_categories.",
    )
    category_id: CaseCategoryId = Field(
        ...,
        description=(
            "Top-level category. Use TECHNICAL for most edge / configuration / "
            "performance issues; SECURITY for WAF / bot / DDoS; BILLING for "
            "invoicing; MANAGED_CLOUD for cloud-services; PROFESSIONAL_SERVICES "
            "for engagement-related; BUSINESS_SUPPORT for everything else."
        ),
    )
    severity: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description=(
            "Severity level. Valid values come from get_case_category for the "
            "chosen category_id — call that first if unsure."
        ),
    )
    product_name: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Product the case is about. Valid values come from get_case_category.",
    )
    service_name: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Service the case is about. Valid values come from get_case_category.",
    )
    problem_name: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Problem name. Valid values come from get_case_category.",
    )
    area_name: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Area name. Required for some categories (see get_case_category).",
    )
    policy_domain_name: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Policy domain. Required for some categories (see get_case_category).",
    )
    product_solution_name: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Product solution name. Required for some categories.",
    )
    ps_package_name: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Professional services package name. Required for PROFESSIONAL_SERVICES.",
    )
    also_notify: list[str] | None = Field(
        None,
        max_length=_MAX_EMAIL_LIST,
        description="Additional email addresses to send case notifications to.",
    )
    alternate_contact: AlternateContact | None = Field(
        None,
        description="Alternate person for the support team to contact (name/email/phone/company).",
    )
    customer_tracking_number: str | None = Field(
        None,
        max_length=_MAX_NAME,
        description="Your internal ticket / tracking number for cross-reference.",
    )
    partner_ticket_number: str | None = Field(
        None,
        max_length=30,
        description="Reseller's support ticket number (≤30 chars), if applicable.",
    )
    parent_account_id: str | None = Field(
        None,
        max_length=_MAX_ID,
        description="Parent account to associate the case with, if relevant.",
    )


class GetCaseInput(_Base):
    case_id: str = Field(..., max_length=_MAX_ID, description="The case ID to fetch.")
    format: ReadFormat = Field(
        "full",
        description=(
            "Response shape. 'full' (default) returns the entire case object "
            "verbatim, including description, contact emails / phone, and "
            "customer-tracking numbers. 'summary' returns just {caseId, status, "
            "severity, category, subject, createdTime, lastUpdatedTime, "
            "commentCount}. Pass 'summary' for privacy-sensitive contexts."
        ),
    )


class UpdateCaseInput(_Base):
    case_id: str = Field(..., max_length=_MAX_ID, description="The case ID to update.")
    also_notify: list[str] | None = Field(
        None,
        max_length=_MAX_EMAIL_LIST,
        description="Updated list of email addresses for case notifications.",
    )
    alternate_contact: AlternateContact | None = Field(
        None, description="Updated alternate contact details."
    )


class ListCaseCommentsInput(_Base):
    case_id: str = Field(
        ..., max_length=_MAX_ID, description="The case ID to list comments for."
    )
    format: ReadFormat = Field(
        "full",
        description=(
            "Response shape. 'full' (default) returns every comment with its full "
            "body. 'summary' returns just {commentId, createdTime, author} per "
            "comment — useful when you only need a count and recency, not the "
            "discussion content."
        ),
    )


class AddCaseCommentInput(_Base):
    case_id: str = Field(..., max_length=_MAX_ID, description="The case ID to comment on.")
    comment: str = Field(
        ..., max_length=_MAX_TEXT, description="Comment text to add."
    )


class RequestCaseClosureInput(_Base):
    case_id: str = Field(
        ..., max_length=_MAX_ID, description="The case ID to request closure for."
    )
    comment: str | None = Field(
        None,
        max_length=_MAX_TEXT,
        description="Optional context for closing (e.g. resolution summary).",
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
        max_length=_MAX_IP,
        description=(
            "Edge server IP to source the trace from. Mutually exclusive with "
            "mdt_location_id; provide one or the other."
        ),
    )
    mdt_location_id: str | None = Field(
        None,
        max_length=_MAX_ID,
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
        max_length=_MAX_HEADER_LIST,
        description=(
            "Custom request headers as a list of 'Header-Name: value' strings, "
            "e.g. ['X-Foo: bar', 'Accept-Language: en']."
        ),
    )
    sensitive_request_header_keys: list[str] | None = Field(
        None,
        max_length=_MAX_HEADER_LIST,
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
