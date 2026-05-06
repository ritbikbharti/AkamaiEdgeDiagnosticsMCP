"""MCP server entry point and tool registration."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from pydantic.fields import PydanticUndefined

from . import models as M
from .client import AkamaiAPIError, AkamaiEdgeDiagnosticsClient
from .config import ConfigError, load_credentials
from .polling import PollingTimeoutError
from .tools import diagnostics, locations, logs, mdt, problems, translate

logger = logging.getLogger("akamai_edge_mcp")


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # SECURITY: edgegrid-python prints the client_token, access_token, signing
    # key, and signed Authorization header at DEBUG. Anyone who captures the
    # logs gets credentials capable of forging requests. Pin it to WARNING
    # regardless of our LOG_LEVEL so users can debug our code without leaking
    # auth material. Override by setting EDGEGRID_LOG_LEVEL explicitly.
    eg_level = os.environ.get("EDGEGRID_LOG_LEVEL", "WARNING").upper()
    logging.getLogger("akamai.edgegrid").setLevel(
        getattr(logging, eg_level, logging.WARNING)
    )


def _build_server() -> tuple[FastMCP, AkamaiEdgeDiagnosticsClient]:
    creds = load_credentials()
    client = AkamaiEdgeDiagnosticsClient(creds)
    mcp = FastMCP("akamai-edge-diagnostics")
    _register_tools(mcp, client)
    return mcp, client


ToolFn = Callable[[AkamaiEdgeDiagnosticsClient, BaseModel], Awaitable[dict[str, Any]]]


def _make_handler(
    name: str,
    model: type[BaseModel],
    impl: "ToolFn",
    client: AkamaiEdgeDiagnosticsClient,
):
    """Build an async handler whose signature mirrors the Pydantic model fields.

    FastMCP introspects ``inspect.signature`` and ``__annotations__`` to build
    the JSON schema exposed to the LLM. A bare ``**kwargs`` handler exposes a
    single useless ``kwargs`` field, so we synthesize one parameter per model
    field and re-attach the original ``FieldInfo`` via ``Annotated`` to
    preserve descriptions and constraints.
    """

    async def handler(**kwargs: Any) -> dict[str, Any]:
        try:
            params = model(**kwargs)
            return await impl(client, params)
        except AkamaiAPIError as exc:
            return {
                "error": "akamai_api_error",
                "status_code": exc.status_code,
                "method": exc.method,
                "url": exc.url,
                "body": exc.body,
            }
        except PollingTimeoutError as exc:
            return {
                "error": "polling_timeout",
                "request_id": exc.request_id,
                "elapsed_seconds": round(exc.elapsed, 2),
                "last_status": exc.last_status,
            }
        except ValueError as exc:
            return {"error": "invalid_input", "message": str(exc)}

    parameters: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    for field_name, field_info in model.model_fields.items():
        annotated = Annotated[field_info.annotation, field_info]
        annotations[field_name] = annotated
        if field_info.is_required():
            default: Any = inspect.Parameter.empty
        else:
            default = (
                field_info.default
                if field_info.default is not PydanticUndefined
                else None
            )
        parameters.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotated,
            )
        )
    annotations["return"] = dict[str, Any]

    handler.__name__ = name
    handler.__qualname__ = name
    handler.__doc__ = (impl.__doc__ or "").strip()
    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters, return_annotation=dict[str, Any]
    )
    handler.__annotations__ = annotations
    return handler


def _register_tools(mcp: FastMCP, client: AkamaiEdgeDiagnosticsClient) -> None:
    def register(name: str, model: type[BaseModel], impl: ToolFn) -> None:
        handler = _make_handler(name, model, impl, client)
        mcp.tool(name=name)(handler)

    register("run_url_health_check", M.UrlHealthCheckInput, diagnostics.run_url_health_check)
    register("run_dig", M.DigInput, diagnostics.run_dig)
    register("run_mtr", M.MtrInput, diagnostics.run_mtr)
    register("run_curl", M.CurlInput, diagnostics.run_curl)

    register("translate_error_string", M.TranslateErrorStringInput, translate.translate_error_string)
    register("launch_translated_url", M.TranslatedUrlInput, translate.launch_translated_url)

    register("get_grep_logs", M.GrepLogsInput, logs.get_grep_logs)
    register("get_estats", M.EstatsInput, logs.get_estats)

    register("list_edge_locations", M.ListEdgeLocationsInput, locations.list_edge_locations)
    register("verify_ip", M.VerifyIpInput, locations.verify_ip)
    register("locate_ip", M.LocateIpInput, locations.locate_ip)
    register("verify_and_locate_ip", M.VerifyAndLocateIpInput, locations.verify_and_locate_ip)
    register(
        "create_user_diagnostic_link",
        M.CreateUserDiagnosticLinkInput,
        locations.create_user_diagnostic_link,
    )
    register(
        "list_user_diagnostic_groups",
        M.ListUserDiagnosticGroupsInput,
        locations.list_user_diagnostic_groups,
    )
    register(
        "get_user_diagnostic_data",
        M.GetUserDiagnosticDataInput,
        locations.get_user_diagnostic_data,
    )

    register(
        "get_connectivity_problems",
        M.ConnectivityProblemsInput,
        problems.get_connectivity_problems,
    )
    register("get_content_problems", M.ContentProblemsInput, problems.get_content_problems)

    register("run_metadata_trace", M.MetadataTraceInput, mdt.run_metadata_trace)
    register("list_mdt_locations", M.ListMdtLocationsInput, mdt.list_mdt_locations)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="akamai-edge-mcp", description=__doc__)
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse"),
        default="stdio",
        help="MCP transport. stdio (default) for desktop clients; sse for HTTP/SSE.",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind address when --transport=sse."
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Port when --transport=sse."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    try:
        mcp, client = _build_server()
    except ConfigError as exc:
        print(f"[akamai-edge-mcp] config error: {exc}", file=sys.stderr)
        return 2

    logger.info("Starting akamai-edge-mcp on transport=%s", args.transport)

    try:
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            mcp.run(transport="sse")
    finally:
        asyncio.run(client.aclose())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
