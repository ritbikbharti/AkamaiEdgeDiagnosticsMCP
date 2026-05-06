from __future__ import annotations

import textwrap

import pytest

from akamai_edge_mcp.config import ConfigError, load_credentials

EDGERC_BODY = textwrap.dedent("""\
    [default]
    host = akab-test.luna.akamaiapis.net
    client_token = akab-client-token-xxxxxxxxxxxxxxxx
    client_secret = c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0
    access_token = akab-access-token-xxxxxxxxxxxxxxxx
""")


def _write_edgerc(tmp_path, body):
    p = tmp_path / ".edgerc"
    p.write_text(body)
    return p


def test_loads_basic_section(tmp_path, monkeypatch):
    monkeypatch.delenv("AKAMAI_ACCOUNT_SWITCH_KEY", raising=False)
    p = _write_edgerc(tmp_path, EDGERC_BODY)
    creds = load_credentials(edgerc_path=str(p))
    assert creds.host == "akab-test.luna.akamaiapis.net"
    assert creds.account_switch_key is None
    assert creds.base_url == "https://akab-test.luna.akamaiapis.net"


def test_account_key_loaded_from_edgerc(tmp_path, monkeypatch):
    monkeypatch.delenv("AKAMAI_ACCOUNT_SWITCH_KEY", raising=False)
    p = _write_edgerc(tmp_path, EDGERC_BODY + "account_key = B-X-1234:5-6789\n")
    creds = load_credentials(edgerc_path=str(p))
    assert creds.account_switch_key == "B-X-1234:5-6789"


def test_account_switch_key_alias_also_works(tmp_path, monkeypatch):
    monkeypatch.delenv("AKAMAI_ACCOUNT_SWITCH_KEY", raising=False)
    p = _write_edgerc(tmp_path, EDGERC_BODY + "account-switch-key = B-X-9999:1-1111\n")
    creds = load_credentials(edgerc_path=str(p))
    assert creds.account_switch_key == "B-X-9999:1-1111"


def test_env_var_overrides_edgerc(tmp_path, monkeypatch):
    monkeypatch.setenv("AKAMAI_ACCOUNT_SWITCH_KEY", "B-ENV:1-OVERRIDE")
    p = _write_edgerc(tmp_path, EDGERC_BODY + "account_key = B-X-1234:5-6789\n")
    creds = load_credentials(edgerc_path=str(p))
    assert creds.account_switch_key == "B-ENV:1-OVERRIDE"


def test_missing_section_raises(tmp_path):
    p = _write_edgerc(tmp_path, EDGERC_BODY)
    with pytest.raises(ConfigError):
        load_credentials(section="nope", edgerc_path=str(p))


def test_edgegrid_logger_pinned_to_warning_even_when_root_is_debug(monkeypatch):
    """SECURITY regression: setting LOG_LEVEL=DEBUG must NOT enable
    edgegrid-python's token-printing debug logger."""
    import logging

    from akamai_edge_mcp.server import _configure_logging

    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.delenv("EDGEGRID_LOG_LEVEL", raising=False)
    _configure_logging()

    eg_logger = logging.getLogger("akamai.edgegrid.edgegrid")
    assert eg_logger.getEffectiveLevel() >= logging.WARNING, (
        "edgegrid logger leaked DEBUG output that contains client_token, "
        "access_token, and HMAC signing key in cleartext"
    )


def test_missing_required_key_raises(tmp_path):
    body = textwrap.dedent("""\
        [default]
        host = akab.example.net
        client_token = abc
        client_secret = def
    """)
    p = _write_edgerc(tmp_path, body)
    with pytest.raises(ConfigError, match="access_token"):
        load_credentials(edgerc_path=str(p))
