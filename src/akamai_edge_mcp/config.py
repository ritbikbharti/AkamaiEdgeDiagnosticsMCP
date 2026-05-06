"""Load Akamai EdgeGrid credentials from a .edgerc file."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when EdgeGrid credentials cannot be loaded."""


@dataclass(frozen=True)
class EdgeGridCredentials:
    host: str
    client_token: str
    client_secret: str
    access_token: str
    max_body: int = 131072
    account_switch_key: str | None = None

    @property
    def base_url(self) -> str:
        host = self.host.rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return host


_REQUIRED_KEYS = ("host", "client_token", "client_secret", "access_token")
_ACCOUNT_KEY_ALIASES = ("account_key", "account-key", "account_switch_key", "account-switch-key")


def _resolve_edgerc_path(explicit: str | None) -> Path:
    raw = explicit or os.environ.get("EDGERC_PATH") or "~/.edgerc"
    return Path(raw).expanduser()


def load_credentials(
    section: str | None = None,
    edgerc_path: str | None = None,
) -> EdgeGridCredentials:
    """Load credentials from the named section of a .edgerc file.

    Resolution order:
      1. ``edgerc_path`` argument
      2. ``EDGERC_PATH`` env var
      3. ``~/.edgerc``

    Section resolution:
      1. ``section`` argument
      2. ``AKAMAI_EDGERC_SECTION`` env var
      3. ``"default"``
    """
    path = _resolve_edgerc_path(edgerc_path)
    if not path.is_file():
        raise ConfigError(
            f"EdgeGrid credentials file not found at {path}. "
            "Create one (see https://techdocs.akamai.com/developer/docs/set-up-authentication-credentials) "
            "or set EDGERC_PATH to point at it."
        )

    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    chosen = section or os.environ.get("AKAMAI_EDGERC_SECTION") or "default"
    if chosen not in parser:
        available = ", ".join(parser.sections()) or "(none)"
        raise ConfigError(
            f"Section '{chosen}' not found in {path}. Available sections: {available}"
        )

    cfg = parser[chosen]
    missing = [key for key in _REQUIRED_KEYS if not cfg.get(key)]
    if missing:
        raise ConfigError(
            f"Section '{chosen}' in {path} is missing required keys: {', '.join(missing)}"
        )

    max_body_raw = cfg.get("max-body") or cfg.get("max_body") or "131072"
    try:
        max_body = int(max_body_raw)
    except ValueError as exc:
        raise ConfigError(f"max-body in section '{chosen}' must be an integer") from exc

    account_switch_key = os.environ.get("AKAMAI_ACCOUNT_SWITCH_KEY")
    if not account_switch_key:
        for alias in _ACCOUNT_KEY_ALIASES:
            value = cfg.get(alias)
            if value:
                account_switch_key = value.strip()
                break

    return EdgeGridCredentials(
        host=cfg["host"].strip(),
        client_token=cfg["client_token"].strip(),
        client_secret=cfg["client_secret"].strip(),
        access_token=cfg["access_token"].strip(),
        max_body=max_body,
        account_switch_key=account_switch_key or None,
    )
