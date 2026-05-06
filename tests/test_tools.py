from __future__ import annotations

import json

import httpx
import pytest

from akamai_edge_mcp import models as M
from akamai_edge_mcp.client import AkamaiEdgeDiagnosticsClient
from akamai_edge_mcp.server import _make_handler
from akamai_edge_mcp.tools import diagnostics, locations, logs, mdt, translate


async def test_run_dig_posts_correct_body(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answers": []})

    client = make_client(handler)
    try:
        result = await diagnostics.run_dig(
            client,
            M.DigInput(hostname="www.example.com", query_type="A", edge_location_id="loc1"),
        )
    finally:
        await client.aclose()

    assert seen["path"].endswith("/dig")
    assert seen["body"] == {
        "hostname": "www.example.com",
        "queryType": "A",
        "isGtmHostname": False,
        "edgeLocationId": "loc1",
    }
    assert result == {"answers": []}


async def test_run_dig_rejects_both_location_and_ip(make_client):
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError):
            await diagnostics.run_dig(
                client,
                M.DigInput(
                    hostname="x", query_type="A", edge_location_id="loc1", edge_ip="1.2.3.4"
                ),
            )
    finally:
        await client.aclose()


async def test_translate_error_string_kickoff_then_poll(make_client):
    """POST returns 202 + requestId; tool must poll the GET endpoint until done."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            assert json.loads(request.content) == {"errorCode": "9.abc.123.def"}
            return httpx.Response(202, json={"requestId": "req-7"})
        # GET poll
        assert request.url.path.endswith("/error-translator/requests/req-7")
        return httpx.Response(
            200,
            json={"status": "SUCCESS", "result": {"errorCode": "9.abc.123.def", "logs": []}},
        )

    client = make_client(handler)
    try:
        result = await translate.translate_error_string(
            client,
            M.TranslateErrorStringInput(error_code="9.abc.123.def", timeout_seconds=10),
        )
    finally:
        await client.aclose()

    assert result["polling"] is True
    assert result["request_id"] == "req-7"
    assert result["status"] == "SUCCESS"
    assert result["result"]["result"]["errorCode"] == "9.abc.123.def"
    assert calls[0][0] == "POST"
    assert any(method == "GET" for method, _ in calls[1:])


async def test_translate_error_string_passes_trace_forward_logs(make_client):
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted["body"] = json.loads(request.content)
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(200, json={"status": "SUCCESS", "result": {}})

    client = make_client(handler)
    try:
        await translate.translate_error_string(
            client,
            M.TranslateErrorStringInput(
                error_code="9.x.y.z", trace_forward_logs=True, timeout_seconds=10
            ),
        )
    finally:
        await client.aclose()

    assert posted["body"] == {"errorCode": "9.x.y.z", "traceForwardLogs": True}


async def test_grep_requires_edge_ip_and_cp_code_via_pydantic(make_client):
    """Akamai requires both — Pydantic validates this before we hit the API."""
    from pydantic import ValidationError

    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValidationError):
            await logs.get_grep_logs(client, M.GrepLogsInput())
        with pytest.raises(ValidationError):
            await logs.get_grep_logs(client, M.GrepLogsInput(edge_ip="1.2.3.4"))
    finally:
        await client.aclose()


async def test_grep_serializes_query_string(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"logs": []})

    client = make_client(handler)
    try:
        await logs.get_grep_logs(
            client,
            M.GrepLogsInput(
                edge_ip="23.45.67.89",
                cp_code=12345,
                arl="/L/123/path",
                http_status_code=502,
                start="2026-05-01T00:00:00Z",
                end="2026-05-01T01:00:00Z",
            ),
        )
    finally:
        await client.aclose()

    assert seen["params"]["edgeIp"] == "23.45.67.89"
    assert seen["params"]["cpCode"] == "12345"
    assert seen["params"]["arl"] == "/L/123/path"
    assert seen["params"]["httpStatusCode"] == "502"
    assert seen["params"]["start"] == "2026-05-01T00:00:00Z"
    assert seen["params"]["end"] == "2026-05-01T01:00:00Z"


async def test_estats_requires_url_or_cp_code(make_client):
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError):
            await logs.get_estats(client, M.EstatsInput())
    finally:
        await client.aclose()


async def test_list_edge_locations_uses_get(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"edgeLocations": []})

    client = make_client(handler)
    try:
        await locations.list_edge_locations(client, M.ListEdgeLocationsInput())
    finally:
        await client.aclose()

    assert seen["method"] == "GET"
    assert seen["path"].endswith("/edge-locations")


def test_handler_signature_exposes_model_fields_not_kwargs(credentials):
    """Regression: FastMCP must see real param names, not a single **kwargs."""
    import inspect

    async def fake_impl(client, params):
        return {}

    dummy_client = AkamaiEdgeDiagnosticsClient.__new__(AkamaiEdgeDiagnosticsClient)
    handler = _make_handler("verify_ip", M.VerifyIpInput, fake_impl, dummy_client)

    sig = inspect.signature(handler)
    assert list(sig.parameters) == ["ip_address"]
    assert sig.parameters["ip_address"].default is inspect.Parameter.empty


def test_handler_signature_handles_optional_fields(credentials):
    import inspect

    async def fake_impl(client, params):
        return {}

    dummy_client = AkamaiEdgeDiagnosticsClient.__new__(AkamaiEdgeDiagnosticsClient)
    handler = _make_handler("run_dig", M.DigInput, fake_impl, dummy_client)

    sig = inspect.signature(handler)
    assert list(sig.parameters) == [
        "hostname",
        "query_type",
        "is_gtm_hostname",
        "edge_location_id",
        "edge_ip",
    ]
    assert sig.parameters["hostname"].default is inspect.Parameter.empty
    assert sig.parameters["query_type"].default == "A"
    assert sig.parameters["is_gtm_hostname"].default is False
    assert sig.parameters["edge_location_id"].default is None


async def test_metadata_trace_kickoff_then_poll_uses_requests_segment(make_client):
    """MDT polls /metadata-tracer/requests/{requestId} — same /requests/
    convention as every other async endpoint in this API."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            assert request.url.path.endswith("/metadata-tracer")
            assert json.loads(request.content)["url"] == "https://www.example.com/"
            return httpx.Response(202, json={"requestId": "mdt-42"})
        assert request.url.path.endswith("/metadata-tracer/requests/mdt-42")
        return httpx.Response(200, json={"status": "SUCCESS", "result": {"behaviors": []}})

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(
                url="https://www.example.com/",
                mdt_location_id="frankfurt-1",
                timeout_seconds=10,
            ),
        )
    finally:
        await client.aclose()

    assert result["polling"] is True
    assert result["request_id"] == "mdt-42"
    assert calls[0][0] == "POST"


async def test_metadata_trace_rejects_both_source_kinds(make_client):
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError):
            await mdt.run_metadata_trace(
                client,
                M.MetadataTraceInput(
                    url="https://x.example/",
                    edge_ip="1.2.3.4",
                    mdt_location_id="loc1",
                ),
            )
    finally:
        await client.aclose()


async def test_metadata_trace_rejects_body_without_post(make_client):
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError, match="http_body"):
            await mdt.run_metadata_trace(
                client,
                M.MetadataTraceInput(
                    url="https://x.example/", http_method="GET", http_body="payload=1"
                ),
            )
    finally:
        await client.aclose()


async def test_metadata_trace_injects_default_headers_when_none_supplied(make_client):
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted["body"] = json.loads(request.content)
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 0,
                "traceInformation": [],
                "responseHeaderList": [],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(url="https://x.example/", timeout_seconds=10),
        )
    finally:
        await client.aclose()

    headers = posted["body"]["requestHeaders"]
    assert any(h.startswith("User-Agent: akamai-edge-mcp/") for h in headers)
    assert "Accept: */*" in headers
    assert "note" in result
    assert "Default request_headers injected" in result["note"]


async def test_metadata_trace_disable_default_headers_sends_bare_request(make_client):
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted["body"] = json.loads(request.content)
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(200, json={"executionStatus": "SUCCESS", "exitCode": 0})

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(
                url="https://x.example/",
                disable_default_headers=True,
                timeout_seconds=10,
            ),
        )
    finally:
        await client.aclose()

    assert "requestHeaders" not in posted["body"]
    assert "note" not in result


async def test_metadata_trace_warns_on_empty_trace_with_success(make_client):
    """Bug: SUCCESS + exitCode=92 + empty trace must not look like a real result."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 92,
                "traceInformation": [],
                "responseHeaderList": [],
                "suggestedActions": "Try resubmitting the request with relevant request headers.",
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(
                url="https://x.example/",
                disable_default_headers=True,
                timeout_seconds=10,
            ),
        )
    finally:
        await client.aclose()

    summary = result["result"]
    assert summary["warning"] is not None
    # exitCode=92 → specific Akamai-documented "no useful trace data" message
    assert "exitCode=92" in summary["warning"]
    assert "realistic request_headers" in summary["warning"]
    assert summary["exitCode"] == 92
    assert summary["suggestedActions"] == (
        "Try resubmitting the request with relevant request headers."
    )


async def test_metadata_trace_warns_about_perimeter_block(make_client):
    """Real-world bug: SUCCESS + 0 trace lines + 0 response headers usually
    means the edge denied the request (WAF/geo/403) before property metadata
    ran. Our warning should point the LLM at run_curl + translate_error_string,
    not suggest more bare headers."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": None,
                "traceInformation": [],
                "responseHeaderList": [],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(
                url="https://www.rbhartitest.com",
                disable_default_headers=True,
                timeout_seconds=10,
            ),
        )
    finally:
        await client.aclose()

    warning = result["result"]["warning"]
    assert warning is not None
    assert "run_curl" in warning
    assert "translate_error_string" in warning
    assert "Zone Apex Mapping" in warning or "ZAM" in warning


async def test_metadata_trace_summary_default_format(make_client):
    arl_xml = """<?xml version="1.0"?>
    <rules>
      <behavior line="42" name="caching"/>
      <behavior line="43" name="origin"/>
      <criteria line="44" name="path-match"/>
    </rules>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 0,
                "arlDataXml": arl_xml,
                "traceInformation": [
                    {"line": 42, "stages": [{"name": "client-request"}]},
                    {"line": 43, "stages": [{"name": "origin-fetch"}]},
                ],
                "responseHeaderList": [{"name": "Server", "value": "AkamaiGHost"}],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(url="https://x.example/", timeout_seconds=10),
        )
    finally:
        await client.aclose()

    assert result["mode"] == "summary"
    summary = result["result"]
    assert summary["traceLineCount"] == 2
    assert summary["stageCounts"] == {"client-request": 1, "origin-fetch": 1}
    assert summary["responseHeaderCount"] == 1
    assert summary["warning"] is None
    # arlDataXml should NOT be in summary
    assert "arlDataXml" not in summary
    # featuresFired joins XML to lines
    features = {(f["feature"], f["ruleName"]) for f in summary["featuresFired"]}
    assert ("behavior", "caching") in features
    assert ("behavior", "origin") in features


async def test_metadata_trace_full_format_enriches_trace_information(make_client):
    arl_xml = '<?xml version="1.0"?><rules><behavior line="10" name="redirect"/></rules>'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 0,
                "arlDataXml": arl_xml,
                "traceInformation": [
                    {"line": 10, "stages": [{"name": "client-request", "failures": []}]}
                ],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(
                url="https://x.example/", format="full", timeout_seconds=10
            ),
        )
    finally:
        await client.aclose()

    assert result["mode"] == "full"
    api = result["result"]
    assert api["arlDataXml"] == arl_xml  # full keeps raw XML
    enriched = api["traceInformation"][0]
    assert enriched["feature"] == "behavior"
    assert enriched["ruleName"] == "redirect"
    assert "failureSummary" in api
    assert api["suggestedActions"] is None  # ensured present even when Akamai omits


async def test_metadata_trace_failure_summary_lifts_buried_failures(make_client):
    arl_xml = '<?xml version="1.0"?><rules><behavior line="7" name="origin-tls"/></rules>'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 0,
                "arlDataXml": arl_xml,
                "traceInformation": [
                    {
                        "line": 7,
                        "stages": [
                            {
                                "name": "origin-fetch",
                                "failures": ["TLS handshake failed: bad cert"],
                            }
                        ],
                    }
                ],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(url="https://x.example/", timeout_seconds=10),
        )
    finally:
        await client.aclose()

    failures = result["result"]["failureSummary"]
    assert len(failures) == 1
    assert failures[0]["line"] == 7
    assert failures[0]["feature"] == "behavior"
    assert failures[0]["ruleName"] == "origin-tls"
    assert failures[0]["stage"] == "origin-fetch"
    assert failures[0]["failures"] == ["TLS handshake failed: bad cert"]


async def test_metadata_trace_blocks_xxe_in_arl_xml(make_client):
    """SECURITY: arlDataXml with XXE / external-entity payloads must be
    rejected by defusedxml; the tool must degrade gracefully (no exception,
    no file read)."""
    xxe_xml = """<?xml version="1.0"?>
    <!DOCTYPE root [
      <!ENTITY xxe SYSTEM "file:///etc/passwd">
    ]>
    <root>&xxe;</root>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 0,
                "arlDataXml": xxe_xml,
                "traceInformation": [{"line": 1, "stages": []}],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(url="https://x.example/", timeout_seconds=10),
        )
    finally:
        await client.aclose()

    # Should not raise. featuresFired empty because the XML was rejected.
    assert result["result"]["traceLineCount"] == 1
    assert result["result"]["featuresFired"] == []


async def test_metadata_trace_blocks_billion_laughs_in_arl_xml(make_client):
    """SECURITY: defusedxml must reject DTD entity expansion (DOS vector)."""
    bomb_xml = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
      <!ENTITY lol "lol">
      <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
      <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
    ]>
    <lolz>&lol3;</lolz>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 0,
                "arlDataXml": bomb_xml,
                "traceInformation": [],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(url="https://x.example/", timeout_seconds=10),
        )
    finally:
        await client.aclose()

    # No exception, no expansion, no DOS.
    assert result["result"]["featuresFired"] == []


async def test_curl_rejects_crlf_in_request_headers(make_client):
    """SECURITY: header injection must be blocked at the tool layer."""
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError, match="header injection"):
            await diagnostics.run_curl(
                client,
                M.CurlInput(
                    url="https://x.example/",
                    request_headers={"X-Foo": "bar\r\nX-Smuggled: yes"},
                ),
            )
        with pytest.raises(ValueError, match="header injection"):
            await diagnostics.run_curl(
                client,
                M.CurlInput(
                    url="https://x.example/",
                    request_headers={"X-Bad\nName": "value"},
                ),
            )
    finally:
        await client.aclose()


async def test_mdt_rejects_crlf_in_request_headers(make_client):
    """SECURITY: header injection must be blocked at the tool layer for MDT too."""
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError, match="header injection"):
            await mdt.run_metadata_trace(
                client,
                M.MetadataTraceInput(
                    url="https://x.example/",
                    request_headers=["X-Foo: bar\r\nX-Smuggled: yes"],
                ),
            )
    finally:
        await client.aclose()


async def test_mdt_rejects_pragma_header_with_clear_error(make_client):
    """Akamai rejects/ignores Pragma in MDT requestHeaders. Fail fast at the
    tool layer so the LLM gets a corrective error instead of a silent
    empty trace or an opaque HTTP 400."""
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        for entry in (
            "Pragma: akamai-x-cache-on",
            "pragma: akamai-x-meta-trace",
            "  Pragma  : akamai-x-get-request-id",
        ):
            with pytest.raises(ValueError, match="Pragma"):
                await mdt.run_metadata_trace(
                    client,
                    M.MetadataTraceInput(
                        url="https://x.example/",
                        request_headers=["User-Agent: x", entry],
                    ),
                )
    finally:
        await client.aclose()


async def test_mdt_allows_non_pragma_headers_starting_with_p(make_client):
    """Make sure the Pragma check is exact, not a prefix match."""
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted["body"] = json.loads(request.content)
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(200, json={"executionStatus": "SUCCESS", "exitCode": 0})

    client = make_client(handler)
    try:
        await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(
                url="https://x.example/",
                request_headers=[
                    "Pragmatic-Choice: ok",  # not Pragma
                    "X-Pragma-Like: ok",  # not Pragma
                    "Priority: u=1",
                ],
                timeout_seconds=10,
            ),
        )
    finally:
        await client.aclose()

    assert "Pragmatic-Choice: ok" in posted["body"]["requestHeaders"]


async def test_metadata_trace_handles_malformed_arl_xml_gracefully(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(
            200,
            json={
                "executionStatus": "SUCCESS",
                "exitCode": 0,
                "arlDataXml": "<<<not xml at all>>>",
                "traceInformation": [{"line": 1, "stages": []}],
            },
        )

    client = make_client(handler)
    try:
        result = await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(url="https://x.example/", timeout_seconds=10),
        )
    finally:
        await client.aclose()

    # Should not raise; featuresFired is just empty when XML can't be parsed
    assert result["result"]["traceLineCount"] == 1
    assert result["result"]["featuresFired"] == []


async def test_metadata_trace_serializes_optional_fields(make_client):
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted["body"] = json.loads(request.content)
            return httpx.Response(202, json={"requestId": "r1"})
        return httpx.Response(200, json={"status": "SUCCESS", "result": {}})

    client = make_client(handler)
    try:
        await mdt.run_metadata_trace(
            client,
            M.MetadataTraceInput(
                url="https://x.example/",
                edge_ip="1.2.3.4",
                http_method="POST",
                http_body="a=b",
                request_headers=["X-Foo: bar"],
                sensitive_request_header_keys=["Authorization"],
                use_staging=True,
                timeout_seconds=10,
            ),
        )
    finally:
        await client.aclose()

    assert posted["body"] == {
        "url": "https://x.example/",
        "httpMethod": "POST",
        "useStaging": True,
        "edgeIp": "1.2.3.4",
        "httpBody": "a=b",
        "requestHeaders": ["X-Foo: bar"],
        "sensitiveRequestHeaderKeys": ["Authorization"],
    }


async def test_list_mdt_locations(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"locations": []})

    client = make_client(handler)
    try:
        await mdt.list_mdt_locations(client, M.ListMdtLocationsInput())
    finally:
        await client.aclose()

    assert seen["method"] == "GET"
    assert seen["path"].endswith("/metadata-tracer/locations")


async def test_curl_with_headers_serializes_to_array_of_strings(make_client):
    """Akamai's requestHeaders is an array of 'Name: value' strings, not a dict."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": 200})

    client = make_client(handler)
    try:
        await diagnostics.run_curl(
            client,
            M.CurlInput(
                url="https://www.example.com/",
                request_headers={
                    "User-Agent": "custom-agent/1.0",
                    "X-Foo": "bar",
                    "Accept-Language": "en",
                },
                sensitive_request_header_keys=["Authorization"],
            ),
        )
    finally:
        await client.aclose()

    assert seen["body"]["url"] == "https://www.example.com/"
    assert seen["body"]["runFromSiteShield"] is False
    assert set(seen["body"]["requestHeaders"]) == {
        "User-Agent: custom-agent/1.0",
        "X-Foo: bar",
        "Accept-Language: en",
    }
    assert seen["body"]["sensitiveRequestHeaderKeys"] == ["Authorization"]
    assert "userAgent" not in seen["body"]


async def test_run_mtr_correct_body_shape(make_client):
    """Body must use spec field names: destination, destinationType, packetType,
    resolveDns, showIps, showLocations — not destinationDomain/sourceIp."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"hops": []})

    client = make_client(handler)
    try:
        await diagnostics.run_mtr(
            client,
            M.MtrInput(
                destination="origin.example.com",
                source="loc-frankfurt-1",
                source_type="LOCATION",
            ),
        )
    finally:
        await client.aclose()

    assert seen["body"]["destination"] == "origin.example.com"
    assert seen["body"]["destinationType"] == "HOST"  # auto-detected
    assert seen["body"]["packetType"] == "ICMP"
    assert seen["body"]["resolveDns"] is True
    assert seen["body"]["showIps"] is True
    assert seen["body"]["showLocations"] is True
    assert seen["body"]["source"] == "loc-frankfurt-1"
    assert seen["body"]["sourceType"] == "LOCATION"
    assert "destinationDomain" not in seen["body"]
    assert "sourceIp" not in seen["body"]


async def test_run_mtr_auto_detects_destination_type_for_ip(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await diagnostics.run_mtr(client, M.MtrInput(destination="93.184.216.34"))
    finally:
        await client.aclose()

    assert seen["body"]["destinationType"] == "IP"


async def test_run_mtr_rejects_port_without_tcp(make_client):
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError, match="packet_type='TCP'"):
            await diagnostics.run_mtr(
                client, M.MtrInput(destination="x.example", port=443)
            )
    finally:
        await client.aclose()


async def test_run_mtr_rejects_invalid_port(make_client):
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError, match="80 or 443"):
            await diagnostics.run_mtr(
                client,
                M.MtrInput(destination="x.example", packet_type="TCP", port=8080),
            )
    finally:
        await client.aclose()


async def test_verify_and_locate_ip_uses_singular_field(make_client):
    """Spec: ipAddress (string), not ipAddresses (array)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await locations.verify_and_locate_ip(
            client, M.VerifyAndLocateIpInput(ip_address="23.45.67.89")
        )
    finally:
        await client.aclose()

    assert seen["body"] == {"ipAddress": "23.45.67.89"}
    assert "ipAddresses" not in seen["body"]


async def test_user_diagnostic_paths_use_correct_segment(make_client):
    """Spec: /user-diagnostic-data/groups, not /user-diagnostic-data-groups."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await locations.list_user_diagnostic_groups(
            client, M.ListUserDiagnosticGroupsInput()
        )
        await locations.create_user_diagnostic_link(
            client,
            M.CreateUserDiagnosticLinkInput(url="https://shop.example/", note="test"),
        )
        await locations.get_user_diagnostic_data(
            client, M.GetUserDiagnosticDataInput(group_id="abc-123")
        )
    finally:
        await client.aclose()

    assert seen[0][1].endswith("/user-diagnostic-data/groups")
    assert seen[1][1].endswith("/user-diagnostic-data/groups")
    assert seen[2][1].endswith("/user-diagnostic-data/groups/abc-123/records")
    for _, path in seen:
        assert "/user-diagnostic-data-groups" not in path
