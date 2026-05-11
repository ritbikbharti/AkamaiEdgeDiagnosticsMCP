from __future__ import annotations

import httpx
import pytest

from akamai_edge_mcp.polling import PollingTimeoutError, poll_until_complete


async def test_returns_inline_when_no_request_id(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called")

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"result": {"answer": 42}},
            poll_path_template="/x/requests/{request_id}",
        )
    finally:
        await client.aclose()

    assert result["polling"] is False
    assert result["result"] == {"result": {"answer": 42}}


async def test_polls_until_terminal_status(make_client):
    states = ["IN_PROGRESS", "IN_PROGRESS", "SUCCESS"]
    payloads = [{"status": s} for s in states]
    payloads[-1]["result"] = {"foo": "bar"}
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/url-health-check/requests/req-123")
        body = payloads[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=body)

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"requestId": "req-123", "status": "PENDING"},
            poll_path_template="/url-health-check/requests/{request_id}",
            timeout_seconds=10,
        )
    finally:
        await client.aclose()

    assert result["polling"] is True
    assert result["status"] == "SUCCESS"
    assert result["request_id"] == "req-123"
    assert result["poll_count"] == 3
    assert result["result"]["result"] == {"foo": "bar"}


async def test_timeout_raises(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "IN_PROGRESS"})

    client = make_client(handler)
    try:
        with pytest.raises(PollingTimeoutError):
            await poll_until_complete(
                client,
                initial_response={"requestId": "req-x"},
                poll_path_template="/url-health-check/requests/{request_id}",
                timeout_seconds=2,
            )
    finally:
        await client.aclose()


async def test_poll_terminates_when_response_echoes_request_id(make_client):
    """Regression: Akamai's GET poll responses include requestId alongside the
    result. Earlier code mistook that for 'still in progress' and polled until
    timeout. This is the bug seen with translate_error_string."""
    payload = {
        "requestId": "0.b60ec417.1777962898.597deb",
        "errorReference": "0.b60ec417.1777962898.597deb",
        "edgeServerIp": "23.45.67.89",
        "edgeServerLogs": [{"line": "..."}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"requestId": "0.b60ec417.1777962898.597deb"},
            poll_path_template="/error-translator/requests/{request_id}",
            timeout_seconds=10,
        )
    finally:
        await client.aclose()

    assert result["polling"] is True
    assert result["http_status"] == 200
    assert result["poll_count"] == 1
    assert result["result"]["edgeServerIp"] == "23.45.67.89"


async def test_http_202_keeps_polling_even_with_result_field(make_client):
    """Regression: HTTP 202 must override payload heuristics — Akamai uses 202
    while still computing, then 200 when done."""
    responses = [
        httpx.Response(202, json={"requestId": "r1", "result": None}),
        httpx.Response(202, json={"requestId": "r1", "result": None}),
        httpx.Response(200, json={"requestId": "r1", "result": {"x": 1}}),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"requestId": "r1"},
            poll_path_template="/x/requests/{request_id}",
            timeout_seconds=10,
        )
    finally:
        await client.aclose()

    assert result["poll_count"] == 3
    assert result["http_status"] == 200


async def test_explicit_in_progress_status_keeps_polling(make_client):
    """Even on HTTP 200, an explicit IN_PROGRESS status should keep polling."""
    responses = [
        httpx.Response(200, json={"requestId": "r1", "status": "IN_PROGRESS"}),
        httpx.Response(200, json={"requestId": "r1", "status": "PROCESSING"}),
        httpx.Response(200, json={"requestId": "r1", "status": "SUCCESS", "result": "ok"}),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"requestId": "r1"},
            poll_path_template="/x/requests/{request_id}",
            timeout_seconds=10,
        )
    finally:
        await client.aclose()

    assert result["poll_count"] == 3
    assert result["status"] == "SUCCESS"


async def test_akamai_executionStatus_in_progress_keeps_polling(make_client):
    """Real bug seen against live Akamai: error-translator returns HTTP 200
    with executionStatus=IN_PROGRESS while still computing, not HTTP 202."""
    responses = [
        httpx.Response(
            200,
            json={
                "requestId": 1061219,
                "request": {"errorCode": "0.b60ec417.1777962898.597deb"},
                "executionStatus": "IN_PROGRESS",
                "retryAfter": 3,
                "link": "/edge-diagnostics/v1/error-translator/requests/1061219",
            },
        ),
        httpx.Response(
            200,
            json={
                "requestId": 1061219,
                "executionStatus": "SUCCESS",
                "errorReference": "0.b60ec417.1777962898.597deb",
                "edgeServerLogs": [{"line": "..."}],
            },
        ),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"requestId": "1061219"},
            poll_path_template="/error-translator/requests/{request_id}",
            timeout_seconds=20,
        )
    finally:
        await client.aclose()

    assert result["poll_count"] == 2
    assert result["status"] == "SUCCESS"
    assert result["result"]["edgeServerLogs"] == [{"line": "..."}]


async def test_429_during_poll_is_retried_with_retry_after(make_client):
    """SECURITY (denial-of-wallet defense): the polling helper must back off
    on 429, honoring Akamai's Retry-After hint, not let it bubble as a fatal
    error. Otherwise a transient rate limit aborts long-running diagnostics."""
    responses = [
        httpx.Response(429, json={}, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"executionStatus": "SUCCESS", "result": "ok"}),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"requestId": "r1"},
            poll_path_template="/x/requests/{request_id}",
            timeout_seconds=20,
        )
    finally:
        await client.aclose()

    assert result["status"] == "SUCCESS"
    assert calls["n"] == 2  # initial 429 retried


async def test_404_during_poll_is_retried(make_client):
    responses = [
        httpx.Response(404, json={"detail": "not ready"}),
        httpx.Response(200, json={"status": "SUCCESS", "result": "ok"}),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    client = make_client(handler)
    try:
        result = await poll_until_complete(
            client,
            initial_response={"requestId": "r"},
            poll_path_template="/url-health-check/requests/{request_id}",
            timeout_seconds=10,
        )
    finally:
        await client.aclose()

    assert result["status"] == "SUCCESS"
