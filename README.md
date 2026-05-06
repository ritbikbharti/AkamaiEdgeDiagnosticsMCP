# Akamai Edge Diagnostics MCP Server

[![tests](https://github.com/ritbikbharti/AkamaiEdgeDiagnosticsMCP/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/ritbikbharti/AkamaiEdgeDiagnosticsMCP/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes the
[Akamai Edge Diagnostics API v1](https://techdocs.akamai.com/edge-diagnostics/reference/edge-diagnostics-api-1)
as tools an LLM client (Claude Desktop, OpenAI Codex CLI, Cursor, Windsurf, etc.) can call.

> **Disclaimer.** This is an **unofficial, community-maintained** project.
> It is not produced, endorsed, supported, or affiliated with Akamai
> Technologies, Inc. in any way. It is an independent client of the public
> [Akamai Edge Diagnostics API v1](https://techdocs.akamai.com/edge-diagnostics/reference/edge-diagnostics-api-1).
> "Akamai" and related marks are trademarks of Akamai Technologies, Inc.,
> used here only for descriptive reference. Use of this software is subject
> to the terms of your own Akamai API client agreement; the authors take no
> responsibility for actions performed against your Akamai account.

## Features

| Tool | What it does |
|---|---|
| `run_url_health_check` | Comprehensive URL diagnostic (DNS + TCP + HTTP probes from edge). Async + polled. |
| `run_dig` | DNS lookup from an Akamai edge server. |
| `run_mtr` | MTR network trace from an edge server to a destination. ICMP by default; switch to TCP (port 80 or 443) when ICMP is blocked. Auto-detects whether destination is IP or hostname. |
| `run_curl` | cURL from an edge with custom headers / UA. |
| `translate_error_string` | Decode `9.abc12345.…` reference codes from edge error pages. Async + polled. Optional `trace_forward_logs` to also pull origin-side traces. |
| `get_grep_logs` | Search edge logs. Akamai requires `edge_ip` AND `cp_code`; optional filters by ARL, client IP, object/HTTP status, user-agent, time window. |
| `get_estats` | Edge error stats for a URL or CP code. |
| `get_connectivity_problems` | Diagnose latency / connectivity issues. Async + polled. |
| `get_content_problems` | Diagnose stale / incorrect / partial content. Async + polled. |
| `list_edge_locations` | Enumerate edge locations usable as `edge_location_id`. |
| `verify_ip` / `locate_ip` / `verify_and_locate_ip` | Check Akamai ownership and/or geolocate an IP. |
| `launch_translated_url` | Translate an Akamai staging/production ARL. |
| `run_metadata_trace` | Metadata Tracer (MDT): which Property Manager behaviors / criteria fire for a URL. Async + polled. Auto-injects sensible default request headers (override or disable). Defaults to a compact summary with `failureSummary` + `featuresFired`; pass `format="full"` for raw `arlDataXml` and per-line stages. |
| `list_mdt_locations` | Enumerate edge locations available specifically for MDT. |
| `create_user_diagnostic_link` / `list_user_diagnostic_groups` / `get_user_diagnostic_data` | End-user diagnostic data collection workflow. |

### Case Management (since v0.2.0)

For the diagnose→file workflow — once an LLM has identified a problem
with the diagnostic tools above, it can open and manage support cases
without leaving the conversation:

| Tool | What it does |
|---|---|
| `list_account_categories` | Discover which accounts you can open cases for, and the categories each supports. Call FIRST. |
| `get_case_category` | Get the per-category schema (severity values, required fields like productName / serviceName / problemName). Call BEFORE `create_case`. |
| `list_cases` | List cases by `MY_ACTIVE_CASES` / `MY_CLOSED_CASES` / `ALL_ACTIVE_CASES` / `ALL_CLOSED_CASES`. |
| `get_case` | Fetch a single case by ID. |
| `create_case` | Open a new support case. |
| `update_case` | Update notification list / alternate contact (subject and category are immutable post-create). |
| `list_case_comments` / `add_case_comment` | Read or append to the case discussion thread. |
| `request_case_closure` | Request closure with an optional resolution comment. |

*File attachments (`POST /cases/{id}/attachments` and friends) are not
yet exposed — multipart upload + status polling is meaningful work that
will land in a later release.*

Plus first-class support for **Akamai account-switch keys**, so partners and
managed-service providers can run diagnostics against any account they have
delegated access to.

## Prerequisites

- Python 3.10+
- An Akamai API client whose authorization grants:
  - **Edge Diagnostics** API (`/edge-diagnostics/v1/*`) at READ-WRITE
    — required for everything except the case-management tools.
  - **Case Management** API (`/case-management/v3/*`) at READ-WRITE
    — required only if you want to use `create_case` /  `list_cases` /
    `add_case_comment` etc. Skip this grant if you only need diagnostics.

  Create or edit your client in
  [Akamai Control Center → Identity & Access](https://control.akamai.com/apps/identity-management).
- For account switching: that same API client must have **delegated access**
  to the target account.

## Install

The recommended layout uses a project-local virtualenv so Claude Desktop
gets a stable, absolute path to the launcher:

```bash
git clone https://github.com/ritbikbharti/AkamaiEdgeDiagnosticsMCP.git akamai-edge-diagnostics-mcp
cd akamai-edge-diagnostics-mcp

python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

This produces a launcher at `.venv/bin/akamai-edge-mcp` — you'll point Claude
Desktop at this exact path below. (If `pip` isn't on your PATH, use
`python3 -m pip` as shown above.)

## Configure credentials

The server reads standard Akamai EdgeGrid credentials from a `.edgerc` file:

```ini
; ~/.edgerc
[default]
host          = akab-XXXXXXXXXXXXXXXX.luna.akamaiapis.net
client_token  = akab-client-token-XXXXXXXXXXXXXXXX
client_secret = your-client-secret
access_token  = akab-access-token-XXXXXXXXXXXXXXXX
max-body      = 131072
; account_key = B-X-XXXXXXX:1-XXXXX   ; optional — see Account switching below
```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `EDGERC_PATH` | Path to the `.edgerc` file. | `~/.edgerc` |
| `AKAMAI_EDGERC_SECTION` | Section inside `.edgerc` to use. | `default` |
| `AKAMAI_ACCOUNT_SWITCH_KEY` | Per-launch account switch key (overrides `account_key` in `.edgerc`). | unset |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. Goes to stderr. | `INFO` |

See [`.env.example`](.env.example).

### Account switching (partners / MSPs)

If your API client has delegated access to other Akamai accounts, set an
account switch key and every request will be issued against that account.
The server merges the key into the URL as `?accountSwitchKey=…`; EdgeGrid
signs the canonical URL including query params, so signing stays valid.

**Option A — pin to a `.edgerc` section** (best for single-account work):

```ini
[default]
host          = ...
client_token  = ...
client_secret = ...
access_token  = ...
account_key   = B-X-XXXXXXX:1-XXXXX
```

The keys `account_key`, `account-key`, `account_switch_key`, and
`account-switch-key` are all accepted.

**Option B — set per-launch via env var** (best when you switch accounts often):

```bash
AKAMAI_ACCOUNT_SWITCH_KEY=B-X-XXXXXXX:1-XXXXX akamai-edge-mcp
```

The env var wins over any `account_key` set in `.edgerc`.

**Option C — multiple accounts in one Claude session.** Register one MCP
server entry per account, each with a different name and switch key:

```json
{
  "mcpServers": {
    "akamai-edge-acct-A": {
      "command": "/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp",
      "env": { "AKAMAI_ACCOUNT_SWITCH_KEY": "B-X-AAAA:1-1111" }
    },
    "akamai-edge-acct-B": {
      "command": "/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp",
      "env": { "AKAMAI_ACCOUNT_SWITCH_KEY": "B-X-BBBB:1-2222" }
    }
  }
}
```

Note: a few endpoints (e.g. `verify_ip`) operate on global Akamai
infrastructure and ignore the switch key — that's the API's behavior, not
a client bug.

## Run

```bash
# stdio transport (default — used by Claude Desktop, Cursor, etc.)
.venv/bin/akamai-edge-mcp

# HTTP / SSE transport (for HTTP-capable clients)
.venv/bin/akamai-edge-mcp --transport sse --host 127.0.0.1 --port 8765
```

Logs go to **stderr**; stdout is reserved for the stdio transport.

## A note on paths in the examples below

Every `/Users/you/...` in the configs below is a **placeholder** — replace
it with the real path on your machine. None of these clients (Claude
Desktop, Codex CLI, Codex IDE extension, ChatGPT Codex desktop app)
expand `~`, `$HOME`, or `${HOME}` in the `command` field, because that
field is handed straight to the OS subprocess spawner before any shell
sees it. You must hard-code an absolute path.

Get the exact strings you need with:

```bash
realpath .venv/bin/akamai-edge-mcp   # → put this in `command`
realpath ~/.edgerc                    # → put this in EDGERC_PATH
```

**Caveat for `EDGERC_PATH` only:** that env var IS expanded by our Python
code (`Path(...).expanduser()`), so `~/.edgerc` works there. It's also
optional — if omitted, the server defaults to `~/.edgerc`.

## Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%/Claude/claude_desktop_config.json` (Windows). Always
use the **absolute path** to the venv launcher — Claude Desktop launches
MCP servers without your shell PATH, so a bare `akamai-edge-mcp` will fail
with `Failed to spawn process: No such file or directory` (visible in
`~/Library/Logs/Claude/mcp-server-akamai-edge-diagnostics.log`).

```json
{
  "mcpServers": {
    "akamai-edge-diagnostics": {
      "command": "/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp",
      "env": {
        "EDGERC_PATH": "/Users/you/.edgerc",
        "AKAMAI_EDGERC_SECTION": "default",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

To use account switching, add `AKAMAI_ACCOUNT_SWITCH_KEY` to `env`. After
editing, **fully quit Claude Desktop (Cmd+Q) and relaunch** — closing the
window doesn't reload the config.

## OpenAI Codex

OpenAI ships Codex as three separate surfaces. They are **not** all driven
by the same config file:

| Surface | Where MCP servers are configured |
|---|---|
| **ChatGPT Codex desktop app** ([chatgpt.com/codex](https://chatgpt.com/codex)) | GUI form: *Settings → MCP servers → Connect to a custom MCP* |
| **Codex CLI** ([github.com/openai/codex](https://github.com/openai/codex)) | TOML file: `~/.codex/config.toml` |
| **Codex IDE extension** ([developers.openai.com/codex/ide](https://developers.openai.com/codex/ide)) | Same TOML file: `~/.codex/config.toml` (shared with the CLI) |

You only need to configure the surface(s) you actually use.

### A. ChatGPT Codex desktop app (GUI)

Open Codex → **Settings** → **MCP servers** → **Connect to a custom MCP**,
choose the **STDIO** tab, and fill in:

| Field | Value |
|---|---|
| **Name** | `akamai-edge-diagnostics` |
| **Transport** | `STDIO` |
| **Command to launch** | `/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp` (full absolute path — the app spawns without your shell PATH) |
| **Arguments** | *(leave empty)* |
| **Environment variables** | `EDGERC_PATH` = `/Users/you/.edgerc` <br> `AKAMAI_EDGERC_SECTION` = `default` <br> `LOG_LEVEL` = `INFO` |
| **Environment variable passthrough** | `AKAMAI_ACCOUNT_SWITCH_KEY` *(see below)* |
| **Working directory** | *(blank or your home)* |

Click **Save**. Codex spawns the server lazily on first tool call.

**Forward secrets from your shell** instead of typing them into the GUI
(safer — they never get persisted in the app's settings storage). Export
the variable in your shell:

```bash
# ~/.zshrc or ~/.bashrc
export AKAMAI_ACCOUNT_SWITCH_KEY="B-X-XXXXXXX:1-XXXXX"
```

…then add `AKAMAI_ACCOUNT_SWITCH_KEY` to the **Environment variable
passthrough** list. Codex pulls the value from your shell environment at
launch time. Quit and reopen the app once after editing your shell rc so
the new env var is picked up.

**Multi-account.** Add one MCP server entry per account, each with a
different Name (e.g. `akamai-edge-acct-A`, `akamai-edge-acct-B`) and a
different `AKAMAI_ACCOUNT_SWITCH_KEY` in its env-var list.

### B. Codex CLI / IDE extension (shared TOML config)

Both share `~/.codex/config.toml` (or project-scoped
`<project>/.codex/config.toml` for trusted projects). Install whichever
surface you want first:

```bash
# CLI
brew install codex                  # macOS
# or: npm i -g @openai/codex

# IDE extension — install from your editor's marketplace
# (VS Code: search "OpenAI Codex" and click Install)
```

Then add a `[mcp_servers.…]` table:

```toml
[mcp_servers.akamai-edge-diagnostics]
command = "/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp"
args = []

[mcp_servers.akamai-edge-diagnostics.env]
EDGERC_PATH = "/Users/you/.edgerc"
AKAMAI_EDGERC_SECTION = "default"
LOG_LEVEL = "INFO"
# AKAMAI_ACCOUNT_SWITCH_KEY = "B-X-XXXXXXX:1-XXXXX"   # see env_vars below
```

**Forward secrets from your shell** with `env_vars` so they don't live in
the TOML file:

```bash
export AKAMAI_ACCOUNT_SWITCH_KEY="B-X-XXXXXXX:1-XXXXX"
```

```toml
[mcp_servers.akamai-edge-diagnostics]
command = "/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp"
env_vars = ["AKAMAI_ACCOUNT_SWITCH_KEY"]   # pulled from host env at launch

[mcp_servers.akamai-edge-diagnostics.env]
EDGERC_PATH = "/Users/you/.edgerc"
AKAMAI_EDGERC_SECTION = "default"
```

**Multi-account.** One table per account:

```toml
[mcp_servers.akamai-edge-acct-A]
command = "/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp"
[mcp_servers.akamai-edge-acct-A.env]
EDGERC_PATH = "/Users/you/.edgerc"
AKAMAI_ACCOUNT_SWITCH_KEY = "B-X-AAAA:1-1111"

[mcp_servers.akamai-edge-acct-B]
command = "/Users/you/akamai-edge-diagnostics-mcp/.venv/bin/akamai-edge-mcp"
[mcp_servers.akamai-edge-acct-B.env]
EDGERC_PATH = "/Users/you/.edgerc"
AKAMAI_ACCOUNT_SWITCH_KEY = "B-X-BBBB:1-2222"
```

**Verify and reload.** `codex mcp list` shows what was parsed. The CLI
picks up changes on the next session; for the IDE extension, reload the
editor window. Server stderr is surfaced inline when `LOG_LEVEL=DEBUG`.

## Example session

> **You:** Translate Akamai error reference `9.abc12345.1700000000.deadbeef`
> from `www.example.com`, summarize the root cause, and open a TECHNICAL
> severity-3 case under account `ACT-XXX` with the findings as the description.
>
> **Claude:**
> 1. calls `translate_error_string({error_code: "9.abc12345.1700000000.deadbeef"})`
>    → returns the decoded edge server, timestamp, and an inline log snippet
> 2. calls `get_grep_logs({edge_ip: "...", cp_code: 12345, start: "..."})`
>    → returns matching log lines around the failure
> 3. summarizes for you in chat: "Origin returned 502 from `origin.example.com`
>    on edge IP `23.x.x.x` at 17:33 UTC; TCP connect succeeded but TLS
>    handshake failed (`SSL_ERROR_SYSCALL`). Likely an origin-side cert
>    rotation or LB drop."
> 4. calls `get_case_category({category_id: "TECHNICAL"})`
>    → discovers the valid severity values and which of `productName` /
>    `serviceName` / `problemName` are required for this category
> 5. calls `create_case({account_id: "ACT-XXX", category_id: "TECHNICAL",
>    severity: "3-Limited Impact", subject: "502 from origin on www.example.com
>    – TLS handshake failures", description: "<the summary above + the decoded
>    error + the relevant grep lines>", product_name: "...", problem_name: "..."})`
>    → returns the new `caseId`, which Claude shows you with a link
>
> **You (later):** Add a comment to that case with the MTR I just ran.
>
> **Claude:** calls `add_case_comment({case_id: "...", comment: "<your MTR
> findings>"})` → comment posted.

## Security

This server handles Akamai EdgeGrid credentials capable of executing diagnostics
against your account. The codebase has been audited for credential leakage
(to logs, the LLM, or the network) and common web-attack vectors. Highlights:

**Credential handling**
- Credentials live only inside `EdgeGridCredentials` and the EdgeGrid signer.
  Tool implementations never see them.
- The bundled `akamai.edgegrid` logger (which prints `client_token`,
  `access_token`, and the HMAC signing key at DEBUG) is **pinned to WARNING**
  regardless of `LOG_LEVEL`. Override only via `EDGEGRID_LOG_LEVEL` if you
  really need it.
- `accountSwitchKey` is redacted as `***` in our DEBUG log lines and in any
  4xx/5xx error body that flows back to the LLM.
- `.gitignore` blocks `.edgerc`, `*.edgerc`, `secrets.toml`, `**/credentials*`.

**Network posture**
- TLS verification on (`CERT_REQUIRED` + hostname check, min TLS 1.2).
  No `verify=False` paths.
- `follow_redirects=False` — credentials never follow a redirect to an
  attacker-controlled host.
- All requests go to the single `host` from your `.edgerc`. No third-party
  endpoints are hardcoded.

**Input safety**
- All Pydantic models use `extra="forbid"`; unknown fields are rejected
  before any HTTP call.
- `arlDataXml` (Metadata Tracer response) is parsed with `defusedxml`,
  blocking XXE, external-entity, and billion-laughs / DTD-expansion DOS.
- User-supplied `request_headers` (in `run_curl` and `run_metadata_trace`)
  are validated to reject CR / LF / NUL — preventing header injection /
  request smuggling against the target Akamai forwards to.
- Polling loops have a hard 300 s cap.

**Test coverage**
The pytest suite includes regression tests for each item above
(`test_account_switch_key_is_redacted_in_debug_log`,
`test_edgegrid_logger_pinned_to_warning_even_when_root_is_debug`,
`test_error_body_redacts_account_switch_key`,
`test_metadata_trace_blocks_xxe_in_arl_xml`,
`test_metadata_trace_blocks_billion_laughs_in_arl_xml`,
`test_curl_rejects_crlf_in_request_headers`,
`test_mdt_rejects_crlf_in_request_headers`).

**Reporting issues**
This is an unofficial community project (see top-of-file disclaimer).
For suspected vulnerabilities, please open a private security advisory
on the project's source repository rather than a public issue.

## Tests

```bash
.venv/bin/pytest
```

Tests use `httpx.MockTransport` and never touch the real Akamai API.
Coverage includes EdgeGrid signing, polling backoff, FastMCP schema shape,
the account-switch-key plumbing, and `.edgerc` parsing edge cases.

## Troubleshooting

**`Server disconnected` in Claude Desktop.** Almost always the launcher path
is wrong or `.edgerc` is missing/malformed. Check
`~/Library/Logs/Claude/mcp-server-akamai-edge-diagnostics.log` — if you
see `Failed to spawn process: No such file or directory`, your `command:`
isn't pointing at a real binary. Use the absolute venv path shown above.

**Tools appear in Claude but every call fails with `kwargs is required`.**
You're on an older build — pull the latest. The server now synthesizes a
real signature from each Pydantic model, so FastMCP exposes the actual
field names (`ip_address`, `hostname`, etc.) instead of a single `kwargs`
blob.

**`403 Forbidden` from Akamai.** Either (a) your API client doesn't have
the Edge Diagnostics API authorized at the right level, or (b) you set an
account switch key for an account your client lacks delegated access to.

**`run_metadata_trace` returns `traceInformation: []` with status SUCCESS.**
This usually means the test request never reached the property's metadata
evaluation. Run `run_curl` against the same URL — if it returns 4xx (often
403 Access Denied with an Akamai reference like `18.abc12345.…`), an edge
WAF / access policy is blocking the request *before* property eval. Decode
the reference with `translate_error_string` to find the rule that fired.
Other causes the tool will flag in its `warning` field: Zone Apex Mapping
hostnames (try the `www.` CNAMEd subdomain instead) or properties without
metadata-trace exposure enabled in Property Manager. Note: `Pragma:
akamai-x-meta-trace` is **not** a valid Akamai pragma — Akamai 400s on it.
Valid pragmas include `akamai-x-cache-on`, `akamai-x-get-request-id`,
`akamai-x-check-cacheable`, `akamai-x-get-cache-key` — but in our testing
none of them caused MDT to emit trace data when the underlying request was
being blocked at the edge perimeter.

**Codex doesn't see the server.**
- *CLI / IDE extension:* run `codex mcp list` to confirm `~/.codex/config.toml`
  parsed. If listed but tool calls fail, set `LOG_LEVEL=DEBUG` in the
  server's `env` table — Codex forwards stderr inline. TOML is
  whitespace-sensitive: the `[mcp_servers.<name>.env]` table must come
  *after* its parent `[mcp_servers.<name>]` table, not interleaved with
  another server's table.
- *ChatGPT Codex desktop app:* the GUI form is independent of `~/.codex/config.toml`
  — entries you add in *Settings → MCP servers* don't appear in the TOML
  file. If the server saved but a call fails, double-check the **Command
  to launch** field is the absolute path to `.venv/bin/akamai-edge-mcp`
  and that **Environment variable passthrough** lists `AKAMAI_ACCOUNT_SWITCH_KEY`
  if you exported it in your shell rather than typing it under
  Environment variables.

**Run the binary by hand to see startup errors:**
```bash
.venv/bin/akamai-edge-mcp </dev/null
```
A successful start prints `Starting akamai-edge-mcp on transport=stdio`
and exits cleanly when stdin closes. Anything else is a real error.

## Known limitations

- Endpoints under `/gtm/*` (GTM properties), `/ipa/hostnames` (IP
  Acceleration), and `/esi-debugger-api/v1/debug` (ESI Debugger) are not
  yet exposed. Open an issue or PR if you need them.
- Case Management file attachment endpoints
  (`POST /cases/{id}/attachments`, `GET .../status/{uploadId}`,
  `GET .../{attachmentId}`) are skipped in v0.2.0 — multipart upload +
  status polling needs its own design pass. Comments
  (`add_case_comment`) are usually sufficient for LLM-driven workflows.
- All request/response shapes are validated against Akamai's official
  [OpenAPI spec](https://github.com/akamai/akamai-apis/blob/main/apis/edge-diagnostics/v1/openapi.json).
- Only the synchronous `GET /grep` is wired up; the async `POST /grep`
  variant is intentionally skipped for v1.
- Polling caps at 300 s. For very long traces, kick them off out-of-band
  and pull results later via `get_user_diagnostic_data`.
- `edgegrid-python` ships a `requests` adapter; this server bridges it to
  `httpx` via [`src/akamai_edge_mcp/client.py`](src/akamai_edge_mcp/client.py)
  (`_EdgeGridHttpxAuth`). If Akamai changes the canonicalization rules,
  that shim is the only place to update.
- One account switch key per server process. To work against multiple
  accounts simultaneously, register multiple MCP server entries (Option C
  above).

## License & attribution

MIT — see `LICENSE` (or assume the standard MIT terms if the file is absent).

This project is an independent, unofficial client for the Akamai Edge
Diagnostics API v1 documented at
<https://techdocs.akamai.com/edge-diagnostics/reference/edge-diagnostics-api-1>.
It is not affiliated with, endorsed by, or supported by Akamai Technologies,
Inc. All Akamai product names, logos, and brands are property of their
respective owners and are used here for descriptive purposes only. Akamai
may change the underlying API at any time; this project tracks it on a
best-effort basis.
