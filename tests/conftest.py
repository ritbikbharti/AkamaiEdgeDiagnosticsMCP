from __future__ import annotations

import httpx
import pytest

from akamai_edge_mcp.client import AkamaiEdgeDiagnosticsClient, _EdgeGridHttpxAuth
from akamai_edge_mcp.config import EdgeGridCredentials


@pytest.fixture
def credentials() -> EdgeGridCredentials:
    return EdgeGridCredentials(
        host="akab-test.luna.akamaiapis.net",
        client_token="akab-client-token-xxxxxxxxxxxxxxxx",
        client_secret="c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0",
        access_token="akab-access-token-xxxxxxxxxxxxxxxx",
    )


@pytest.fixture
def make_client(credentials):
    """Build an AkamaiEdgeDiagnosticsClient backed by a custom MockTransport."""

    def _factory(handler):
        transport = httpx.MockTransport(handler)
        http = httpx.AsyncClient(
            base_url=credentials.base_url,
            transport=transport,
            auth=_EdgeGridHttpxAuth(credentials),
            headers={"Accept": "application/json"},
        )
        return AkamaiEdgeDiagnosticsClient(credentials, client=http)

    return _factory
