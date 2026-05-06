# Contributing

Thanks for considering a contribution. This is an unofficial, community-maintained
MCP server (see the disclaimer in [README.md](README.md)) — anyone is welcome
to file issues or open PRs.

📖 **End-user docs:** <https://bit.ly/AkamaiEdgeDiagnosticsMCPDocs> — read these
first if you're new; they cover the LLM-facing behavior and the configuration
surface in more depth than this contributor guide.

## Quick start

```bash
git clone https://github.com/ritbikbharti/AkamaiEdgeDiagnosticsMCP.git akamai-edge-diagnostics-mcp
cd akamai-edge-diagnostics-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/pytest -q     # expect: all tests pass
.venv/bin/ruff check .  # expect: no errors
```

CI runs both on every push / PR (Python 3.10–3.13 + ruff). PRs that don't
pass CI won't be merged.

## What makes a good PR

- **Small and focused.** One logical change per PR. A new tool + matching
  tests + a one-line README update is great. A 600-line refactor that also
  adds two unrelated features is hard to review.
- **Tests included.** Every new tool needs at least one test in
  `tests/test_tools.py` covering the request body shape. Tests must use
  `httpx.MockTransport` (see `tests/conftest.py`) — never hit the real
  Akamai API in CI.
- **Schema descriptions written for an LLM.** The `description=...` on
  every Pydantic field is what an LLM client sees as the tool's parameter
  doc. Write it as if you're explaining the parameter to someone who has
  no Akamai context. Mention units, valid ranges, mutually-exclusive
  partners, and what to leave blank for sensible defaults.
- **Match the OpenAPI.** Akamai publishes the canonical contract at
  <https://github.com/akamai/akamai-apis/blob/main/apis/edge-diagnostics/v1/openapi.json>.
  Verify endpoint paths, request body field names, enum values, and
  required-vs-optional against that file before guessing from prose docs —
  most of the historical bugs in this repo came from inferring shapes from
  the human-readable docs.
- **Comments only when the *why* is non-obvious.** Don't restate what the
  code does; explain why it has to be this way (e.g. workarounds for an
  Akamai-specific quirk).

## Adding a new tool

The wiring is consistent across all 19 existing tools — copy the pattern:

1. **Pydantic input model** in `src/akamai_edge_mcp/models.py`. Inherit
   from `_Base` (gives you `extra="forbid"`). Every field needs a
   `description`. Required fields use `...`; optionals get a default.
2. **Tool function** in the appropriate `src/akamai_edge_mcp/tools/*.py`
   module (or a new module if it doesn't fit). Signature is
   `async def my_tool(client: AkamaiEdgeDiagnosticsClient, params: MyInput) -> dict[str, Any]`.
   Build the request body explicitly — don't auto-serialize the Pydantic
   model, because field names usually need camelCasing for Akamai.
3. **Async endpoints** (those that return `202 + requestId`): use
   `poll_until_complete()` from `src/akamai_edge_mcp/polling.py` and
   expose a `timeout_seconds` parameter (10–300, default 60–120).
4. **Register** in `src/akamai_edge_mcp/server.py` inside `_register_tools`.
5. **Test** the body shape, the polling path (if async), and any client-side
   validation. Use the live Akamai response shape if you can — saved
   `httpx.Response(200, json={...})` fixtures are gold.
6. **README** features table row.

## Security

If you discover a security issue, **do not file a public issue**. Open a
private security advisory on the repo
([Security tab → Advisories → Report a vulnerability](https://github.com/ritbikbharti/AkamaiEdgeDiagnosticsMCP/security/advisories/new))
or DM the maintainer. See the Security section in [README.md](README.md) for
the threat model this codebase is designed against (credential leakage,
header injection, XML attacks).

For Akamai-side issues (the underlying API), report through
[Akamai's vulnerability disclosure program](https://www.akamai.com/site/en/documents/akamai/2023/akamai-vulnerability-disclosure-policy.pdf).

## Code style

- `ruff` is the lint authority (config in `pyproject.toml`); CI rejects
  unfixed warnings.
- Line length: 100.
- Type hints encouraged but not required everywhere. Pydantic models
  enforce types at runtime regardless.
- Logging goes to **stderr** only — `stdout` is reserved for the MCP
  stdio transport and any stray write corrupts the protocol.

## Releases

Maintainer responsibility. Tag on `main`, push the tag, run `gh release
create vX.Y.Z` with release notes summarizing user-visible changes.
