"""Dedicated ASGI entrypoint for the remote Alpaca MCP server deployment.

Railway should import this module with:
    uvicorn alpaca_mcp_server.app:app --host 0.0.0.0 --port ${PORT:-8080}

The rule engine has its own ASGI app at alpaca_rule_engine.control:app and is
intentionally not imported here. This module serves only the MCP deployment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import __version__
from .server import AuthHeaderMiddleware, mcp


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / ".well-known" / "mcp" / "manifest.json"
MCP_PATH = "/mcp"


def _load_manifest() -> dict[str, Any]:
    """Load the MCP manifest shipped with the repository."""
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> Response:
    """Railway health check for the MCP service, not the rule engine."""
    return JSONResponse(
        {
            "status": "ok",
            "service": "alpaca-mcp-server",
            "version": __version__,
            "transport": MCP_PATH,
        }
    )


@mcp.custom_route("/health/", methods=["GET"], include_in_schema=False)
async def health_slash(_: Request) -> Response:
    """Slash-compatible Railway health check."""
    return await health(_)


@mcp.custom_route("/.well-known/mcp/manifest.json", methods=["GET"], include_in_schema=False)
async def manifest(_: Request) -> Response:
    """Return the MCP manifest JSON for discovery."""
    return JSONResponse(_load_manifest())


@mcp.custom_route("/.well-known/mcp", methods=["GET"], include_in_schema=False)
async def manifest_alias(_: Request) -> Response:
    """Compatibility alias for clients that probe /.well-known/mcp."""
    return JSONResponse(_load_manifest())


# Build the official FastMCP Streamable HTTP ASGI app. The SDK exposes /mcp
# through streamable_http_app(), so Railway receives health/discovery endpoints
# and ChatGPT receives the real MCP transport from the same process.
app = AuthHeaderMiddleware(
    mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        host="0.0.0.0",
    )
)
