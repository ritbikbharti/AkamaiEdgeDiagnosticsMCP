from __future__ import annotations

import json

import httpx
import pytest

from akamai_edge_mcp.client import AkamaiAPIError


async def test_full_path_routes_bare_to_edge_diagnostics(make_client):
    """Bare path → /edge-diagnostics/v1/<path> (back-compat for existing tools)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await client.get("/dig")
    finally:
        await client.aclose()
    assert seen["path"] == "/edge-diagnostics/v1/dig"


async def test_full_path_passes_already_prefixed_paths_through(make_client):
    """Already-prefixed Akamai API paths (case-mgmt, papi, etc.) route as-is."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await client.get("/case-management/v3/cases")
        await client.get("/papi/v1/properties")
        await client.get("/edge-diagnostics/v1/edge-locations")
    finally:
        await client.aclose()

    assert seen[0] == "/case-management/v3/cases"
    assert seen[1] == "/papi/v1/properties"
    assert seen[2] == "/edge-diagnostics/v1/edge-locations"
    # Critical: case-management path was NOT mangled to
    # /edge-diagnostics/v1/case-management/v3/cases
    for p in seen:
        assert not p.startswith("/edge-diagnostics/v1/case-management")
        assert not p.startswith("/edge-diagnostics/v1/papi")


async def test_get_returns_parsed_json(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, json={"locations": [{"id": "loc1"}]})

    client = make_client(handler)
    try:
        result = await client.get("/edge-locations")
    finally:
        await client.aclose()

    assert seen["method"] == "GET"
    assert seen["path"] == "/edge-diagnostics/v1/edge-locations"
    assert result == {"locations": [{"id": "loc1"}]}


async def test_post_serializes_json_body(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answer": "ok"})

    client = make_client(handler)
    try:
        await client.post("/dig", json={"hostname": "example.com", "queryType": "A"})
    finally:
        await client.aclose()

    assert seen["body"] == {"hostname": "example.com", "queryType": "A"}


async def test_error_body_redacts_account_switch_key(make_client):
    """SECURITY: if Akamai ever echoes accountSwitchKey back in an error body,
    redact it before it reaches the LLM-facing error envelope."""
    from akamai_edge_mcp.client import AkamaiAPIError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "type": "bad-request",
                "request": {
                    "url": "/edge-diagnostics/v1/dig",
                    "accountSwitchKey": "B-X-LEAKED:1-9999",
                },
                "nested": {"account_switch_key": "B-X-ALSO-LEAKED:1-1111"},
            },
        )

    client = make_client(handler)
    try:
        with pytest.raises(AkamaiAPIError) as info:
            await client.get("/dig")
    finally:
        await client.aclose()

    body = info.value.body
    assert body["request"]["accountSwitchKey"] == "***"
    assert body["nested"]["account_switch_key"] == "***"
    # Other fields preserved
    assert body["request"]["url"] == "/edge-diagnostics/v1/dig"
    assert "LEAKED" not in repr(body)


async def test_4xx_raises_akamai_api_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    client = make_client(handler)
    try:
        with pytest.raises(AkamaiAPIError) as info:
            await client.get("/edge-locations")
    finally:
        await client.aclose()

    assert info.value.status_code == 403
    assert info.value.body == {"detail": "forbidden"}


async def test_204_returns_none(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = make_client(handler)
    try:
        result = await client.post("/dig", json={"hostname": "x"})
    finally:
        await client.aclose()

    assert result is None


async def test_account_switch_key_added_as_query_param(credentials):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={})

    creds_with_ask = type(credentials)(
        host=credentials.host,
        client_token=credentials.client_token,
        client_secret=credentials.client_secret,
        access_token=credentials.access_token,
        account_switch_key="B-X-1234:5-6789",
    )

    from akamai_edge_mcp.client import AkamaiEdgeDiagnosticsClient, _EdgeGridHttpxAuth

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url=creds_with_ask.base_url,
        transport=transport,
        auth=_EdgeGridHttpxAuth(creds_with_ask),
    )
    client = AkamaiEdgeDiagnosticsClient(creds_with_ask, client=http)
    try:
        await client.get("/edge-locations")
        await client.post("/dig", json={"hostname": "x"})
    finally:
        await client.aclose()

    assert seen["query"]["accountSwitchKey"] == "B-X-1234:5-6789"


async def test_account_switch_key_is_redacted_in_debug_log(caplog, credentials):
    """Regression: accountSwitchKey must NOT appear in DEBUG log output."""
    import logging

    from akamai_edge_mcp.client import AkamaiEdgeDiagnosticsClient, _EdgeGridHttpxAuth

    creds_with_ask = type(credentials)(
        host=credentials.host,
        client_token=credentials.client_token,
        client_secret=credentials.client_secret,
        access_token=credentials.access_token,
        account_switch_key="B-X-SHOULD-NOT-LEAK:1-NOPE",
    )

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    http = httpx.AsyncClient(
        base_url=creds_with_ask.base_url,
        transport=transport,
        auth=_EdgeGridHttpxAuth(creds_with_ask),
    )
    client = AkamaiEdgeDiagnosticsClient(creds_with_ask, client=http)

    with caplog.at_level(logging.DEBUG, logger="akamai_edge_mcp.client"):
        try:
            await client.get("/edge-locations")
        finally:
            await client.aclose()

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SHOULD-NOT-LEAK" not in log_text
    assert "B-X-" not in log_text
    assert "***" in log_text


async def test_no_account_switch_key_means_no_query_param(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await client.get("/edge-locations")
    finally:
        await client.aclose()

    assert "accountSwitchKey" not in seen["query"]


async def test_authorization_header_added(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await client.get("/edge-locations")
    finally:
        await client.aclose()

    assert seen["auth"] is not None
    assert seen["auth"].startswith("EG1-HMAC-SHA256 ")
