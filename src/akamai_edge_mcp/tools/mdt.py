"""Metadata Tracer (MDT) tools.

MDT shows which Property Manager behaviors and criteria fired for a given
URL on the Akamai edge — invaluable for debugging "why is this rule (not)
applying?" questions.

The kickoff endpoint is asynchronous: ``POST /metadata-tracer`` returns a
202 + ``requestId``. Results are fetched from
``GET /metadata-tracer/requests/{requestId}`` — same ``/requests/``
convention as every other async endpoint in this API.

This module also adds three convenience layers on top of the raw API:

1. **Default request headers.** A bare GET without User-Agent or Accept
   often returns ``traceInformation: []`` with ``exitCode: 92``. We inject
   sensible defaults when the caller passes no headers, so the trace
   actually runs. Disable with ``disable_default_headers=True``.

2. **Server-side line→feature mapping.** ``traceInformation`` only has
   ``{line, stages}``; the line numbers reference rules in ``arlDataXml``.
   We parse the XML once and annotate each trace entry with ``feature``
   and ``ruleName`` so callers don't reimplement the XML walk.

3. **Top-level ``failureSummary``.** Any line whose ``stages.failures``
   array is non-empty is hoisted to a top-level list with the resolved
   feature name, since failures are the most important field for
   debugging and they're otherwise buried.

Output size is controlled by ``format``: ``summary`` (default) returns
counts and key findings; ``full`` returns everything Akamai sent plus the
enrichments above.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any
from xml.etree.ElementTree import Element  # type-only; safe

# SECURITY: arlDataXml comes from a remote (semi-trusted) Akamai response.
# defusedxml is API-compatible with stdlib ElementTree but rejects XXE,
# DTD/entity expansion (billion laughs), external entities, and other
# XML attacks. The stdlib parser does NOT block billion-laughs reliably.
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from .. import __version__
from ..client import AkamaiEdgeDiagnosticsClient
from ..models import ListMdtLocationsInput, MetadataTraceInput
from ..polling import poll_until_complete

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_HEADERS: list[str] = [
    f"User-Agent: akamai-edge-mcp/{__version__}",
    "Accept: */*",
]

# Akamai's documented "trace returned no data; resubmit with headers" code.
_EMPTY_TRACE_EXIT_CODE = 92

_HEADER_FORBIDDEN_CHARS = ("\r", "\n", "\x00")


def _header_name(entry: str) -> str:
    """Extract the (lowercased) header name from a 'Name: value' string."""
    name, _, _ = entry.partition(":")
    return name.strip().lower()


def _validate_header_strings(headers: list[str]) -> None:
    """Validate MDT request_headers entries before submission.

    Two checks:

    1. **CRLF / NUL injection** — embedded CR/LF/NUL would let a single
       entry split into multiple headers when Akamai forwards it (classic
       header-injection / request-smuggling vector).

    2. **No ``Pragma`` header** — Akamai manages MDT trace pragmas
       internally. Caller-supplied ``Pragma`` values are either rejected
       outright with HTTP 400 (for ``akamai-x-meta-trace`` and friends) or
       silently no-op (for normal debug pragmas like ``akamai-x-cache-on``).
       Either way, sending one wastes a round-trip. Fail fast here so the
       LLM gets a clear correction signal.
    """
    for entry in headers:
        for ch in _HEADER_FORBIDDEN_CHARS:
            if ch in entry:
                raise ValueError(
                    f"request_headers entry contains illegal character {ch!r}; "
                    "CR, LF, and NUL are forbidden to prevent header injection."
                )
        if _header_name(entry) == "pragma":
            raise ValueError(
                "Akamai does not allow Pragma headers in MDT request_headers — "
                "trace pragmas are injected server-side by the Metadata Tracer. "
                "Standard debug pragmas (akamai-x-cache-on, akamai-x-get-request-id, "
                "etc.) are silently ignored; trace-internal pragmas like "
                "akamai-x-meta-trace are rejected with HTTP 400. "
                "Drop the Pragma entry and resubmit. For interactive Pragma-based "
                "debugging, use run_curl instead."
            )


async def run_metadata_trace(
    client: AkamaiEdgeDiagnosticsClient, params: MetadataTraceInput
) -> dict[str, Any]:
    """Trace which Property Manager behaviors and criteria apply to a URL.

    Use this to debug "why did (or didn't) this rule fire?" questions on
    a configured property. Async — kicks off the trace and polls until
    Akamai returns the final result (or until ``timeout_seconds``).

    By default, returns a compact summary (executionStatus, exitCode,
    featuresFired, failureSummary, suggestedActions, counts). Pass
    ``format="full"`` for the complete Akamai response with per-line
    traceInformation annotated with feature/ruleName from arlDataXml.
    """
    if params.edge_ip and params.mdt_location_id:
        raise ValueError("Provide either edge_ip or mdt_location_id, not both.")
    if params.http_method != "POST" and params.http_body:
        raise ValueError("http_body is only valid when http_method is POST.")

    request_headers = list(params.request_headers or [])
    headers_were_defaulted = False
    if not request_headers and not params.disable_default_headers:
        request_headers = list(DEFAULT_REQUEST_HEADERS)
        headers_were_defaulted = True

    body: dict[str, Any] = {
        "url": str(params.url),
        "httpMethod": params.http_method,
        "useStaging": params.use_staging,
    }
    if params.edge_ip:
        body["edgeIp"] = params.edge_ip
    if params.mdt_location_id:
        body["mdtLocationId"] = params.mdt_location_id
    if params.http_body:
        body["httpBody"] = params.http_body
    if request_headers:
        _validate_header_strings(request_headers)
        body["requestHeaders"] = request_headers
    if params.sensitive_request_header_keys:
        body["sensitiveRequestHeaderKeys"] = params.sensitive_request_header_keys

    initial = await client.post("/metadata-tracer", json=body)
    polling_result = await poll_until_complete(
        client,
        initial,
        poll_path_template="/metadata-tracer/requests/{request_id}",
        timeout_seconds=params.timeout_seconds,
    )

    return _post_process(polling_result, params.format, headers_were_defaulted)


async def list_mdt_locations(
    client: AkamaiEdgeDiagnosticsClient, params: ListMdtLocationsInput
) -> dict[str, Any]:
    """List edge locations available specifically for Metadata Tracer.

    These are distinct from ``list_edge_locations`` — MDT runs on a
    smaller subset. Use the returned IDs as ``mdt_location_id`` when
    calling ``run_metadata_trace``.
    """
    return await client.get("/metadata-tracer/locations")


# ---------- post-processing ----------


def _post_process(
    polling_result: dict[str, Any], fmt: str, headers_were_defaulted: bool
) -> dict[str, Any]:
    api_result = polling_result.get("result") if isinstance(polling_result, dict) else None
    if not isinstance(api_result, dict):
        return polling_result

    line_map = _parse_arl_data_xml(api_result.get("arlDataXml") or "")
    enriched_trace = _enrich_trace_information(
        api_result.get("traceInformation") or [], line_map
    )
    failure_summary = _build_failure_summary(enriched_trace)
    warning = _build_warning(api_result, len(enriched_trace))

    polling_result["mode"] = fmt
    if headers_were_defaulted:
        polling_result["note"] = (
            "Default request_headers injected (User-Agent + Accept). "
            "Pass disable_default_headers=true for a bare request, or supply "
            "request_headers explicitly."
        )

    if fmt == "summary":
        polling_result["result"] = _build_summary(
            api_result, enriched_trace, failure_summary, warning
        )
    else:
        # full: keep everything Akamai sent, but enrich + add summaries
        api_result["traceInformation"] = enriched_trace
        api_result["failureSummary"] = failure_summary
        api_result.setdefault("suggestedActions", None)
        if warning:
            api_result["warning"] = warning

    return polling_result


def _build_summary(
    api_result: dict[str, Any],
    enriched_trace: list[dict[str, Any]],
    failure_summary: list[dict[str, Any]],
    warning: str | None,
) -> dict[str, Any]:
    stage_counts: Counter[str] = Counter()
    features_fired: list[dict[str, Any]] = []
    seen_features: set[tuple[str | None, str | None]] = set()
    for entry in enriched_trace:
        for stage in entry.get("stages") or []:
            name = stage.get("name") if isinstance(stage, dict) else None
            if name:
                stage_counts[name] += 1
        feat = entry.get("feature")
        rule = entry.get("ruleName")
        key = (feat, rule)
        if feat and key not in seen_features:
            seen_features.add(key)
            features_fired.append(
                {"feature": feat, "ruleName": rule, "firstLine": entry.get("line")}
            )

    return {
        "executionStatus": api_result.get("executionStatus"),
        "exitCode": api_result.get("exitCode"),
        "suggestedActions": api_result.get("suggestedActions"),
        "warning": warning,
        "traceLineCount": len(enriched_trace),
        "stageCounts": dict(stage_counts),
        "featuresFired": features_fired,
        "failureSummary": failure_summary,
        "responseHeaderCount": len(api_result.get("responseHeaderList") or []),
        "request": api_result.get("request"),
        "createdTime": api_result.get("createdTime"),
        "createdBy": api_result.get("createdBy"),
    }


def _build_warning(api_result: dict[str, Any], line_count: int) -> str | None:
    status = (api_result.get("executionStatus") or "").upper()
    exit_code = api_result.get("exitCode")
    if status != "SUCCESS":
        return None
    response_header_count = len(api_result.get("responseHeaderList") or [])
    if exit_code == _EMPTY_TRACE_EXIT_CODE:
        # Documented Akamai code: trace ran but the bare HTTP request had
        # no useful headers — caller should retry with realistic headers.
        return (
            "executionStatus=SUCCESS, exitCode=92 — Akamai's documented "
            "'no useful trace data' code. The test request was too bare. "
            "Retry with realistic request_headers (User-Agent, Accept, "
            "and any Host-specific headers your property expects). "
            "The default headers this tool injects sometimes aren't enough."
        )
    if line_count == 0:
        # Trace returned no metadata lines despite SUCCESS. Three common causes,
        # in rough order of likelihood:
        #   1. Edge denied the request before property eval (WAF, geo-block,
        #      403/451 from a security policy). Run run_curl on the same URL
        #      to see the actual HTTP status; if 4xx, the response body usually
        #      includes an Akamai reference like '18.abc12345.…' that
        #      translate_error_string can decode.
        #   2. Hostname is a Zone Apex Mapping (apex domain, no CNAME). MDT
        #      can't trace ZAM hosts on staging and is unreliable on prod.
        #      Try the www. or other CNAME-mapped subdomain.
        #   3. The property doesn't have metadata-trace exposure enabled in
        #      Property Manager.
        return (
            "executionStatus=SUCCESS but traceInformation is empty "
            f"(responseHeaderList={response_header_count}). Common causes: "
            "(a) the edge denied the test request before property metadata "
            "ran (WAF / access rule / geo-block). Run run_curl on the same "
            "URL to see the real HTTP status — if it's 4xx with an Akamai "
            "reference code in the body, decode it with translate_error_string. "
            "(b) the hostname uses Zone Apex Mapping (apex domain, no CNAME) "
            "— try a CNAME-mapped subdomain like www.<host>. "
            "(c) the property isn't configured to expose metadata-trace data."
        )
    if exit_code not in (0, None):
        return (
            f"executionStatus=SUCCESS but exitCode={exit_code} "
            "(non-zero). Check Akamai docs for the specific exit code meaning."
        )
    return None


# ---------- arlDataXml parsing ----------


def _parse_arl_data_xml(xml_text: str) -> dict[int, dict[str, Any]]:
    """Best-effort line→{feature,ruleName} mapping from arlDataXml.

    The XML's exact schema isn't fully documented, so this walker is
    permissive: any element with an attribute matching ``line`` (case
    insensitive, also tries ``lineNumber``, ``ln``) gets recorded with
    its tag name as the feature and its ``name`` / ``ruleName`` /
    ``description`` attribute as the ruleName. Returns an empty map on
    parse failure (callers degrade gracefully).
    """
    if not xml_text:
        return {}
    try:
        root = ET.fromstring(xml_text)
    except (DefusedXmlException, Exception) as exc:
        # DefusedXmlException = malicious XML (XXE/entity/etc.); other
        # exceptions = malformed XML. Both degrade gracefully to "no map".
        logger.debug("arlDataXml parse rejected: %s: %s", type(exc).__name__, exc)
        return {}

    line_map: dict[int, dict[str, Any]] = {}
    path: list[str] = []

    def _local(tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    def _line_attr(attrs: dict[str, str]) -> int | None:
        for key in ("line", "lineNumber", "lineNo", "ln"):
            v = attrs.get(key)
            if v is None:
                # case-insensitive fallback
                for ak, av in attrs.items():
                    if ak.lower() == key.lower():
                        v = av
                        break
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return None
        return None

    def visit(elem: Element) -> None:
        tag = _local(elem.tag)
        path.append(tag)
        line_no = _line_attr(elem.attrib)
        if line_no is not None and line_no not in line_map:
            line_map[line_no] = {
                "feature": tag,
                "ruleName": (
                    elem.attrib.get("name")
                    or elem.attrib.get("ruleName")
                    or elem.attrib.get("description")
                ),
                "path": "/".join(path),
            }
        for child in elem:
            visit(child)
        path.pop()

    visit(root)
    return line_map


def _enrich_trace_information(
    trace_lines: list[Any], line_map: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for entry in trace_lines:
        if not isinstance(entry, dict):
            enriched.append({"raw": entry})
            continue
        line = entry.get("line")
        info = line_map.get(line) if isinstance(line, int) else None
        merged = dict(entry)
        if info:
            merged.setdefault("feature", info.get("feature"))
            merged.setdefault("ruleName", info.get("ruleName"))
            merged.setdefault("path", info.get("path"))
        enriched.append(merged)
    return enriched


def _build_failure_summary(enriched_trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for entry in enriched_trace:
        stages = entry.get("stages") or []
        if not isinstance(stages, list):
            continue
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            failures = stage.get("failures") or []
            if failures:
                summary.append(
                    {
                        "line": entry.get("line"),
                        "feature": entry.get("feature"),
                        "ruleName": entry.get("ruleName"),
                        "stage": stage.get("name"),
                        "failures": failures,
                    }
                )
    return summary
