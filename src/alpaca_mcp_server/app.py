"""
ASGI entrypoint for the remote Alpaca MCP connector.

This module gives Railway, ChatGPT, and other remote MCP clients one clean HTTP
surface that owns health checks, discovery metadata, and the streamable MCP
transport. It intentionally does not validate Alpaca credentials at import time
so the service can boot and answer discovery/health requests before the first
real trading/data tool call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .server import AuthHeaderMiddleware, mcp

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / ".well-known" / "mcp" / "manifest.json"


def _load_manifest() -> dict[str, Any]:
    """Load the static MCP manifest shipped with the repository."""
    if not MANIFEST_PATH.exists():
        return {
            "name": "alpaca-mcp-server",
            "description": "Alpaca MCP Server",
            "error": f"Manifest file not found at {MANIFEST_PATH}",
        }

    with MANIFEST_PATH.open("r", encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def _build_mcp_asgi_app() -> Callable:
    """Return the FastMCP ASGI app for streamable HTTP transport.

    The MCP Python SDK has changed names across releases. Prefer the current
    streamable HTTP API, but keep a clear fallback for older builds.
    """
    if hasattr(mcp, "streamable_http_app"):
        return mcp.streamable_http_app()

    if hasattr(mcp, "sse_app"):
        return mcp.sse_app()

    raise RuntimeError(
        "This installed mcp package does not expose streamable_http_app() or sse_app(). "
        "Pin mcp>=1.21.0,<2.0.0 or update alpaca_mcp_server.app accordingly."
    )


app = FastAPI(
    title="Alpaca MCP Remote Connector",
    version="1.0.9",
    docs_url=None,
    redoc_url=None,
)


@app.get("/health")
@app.get("/health/")
async def health() -> dict[str, str]:
    """Railway-compatible health check."""
    return {"status": "ok", "service": "alpaca-mcp-connector"}


@app.get("/status")
@app.get("/status/")
async def status() -> dict[str, str]:
    """Alias health status for platforms that already probe /status."""
    return {"status": "ok", "service": "alpaca-mcp-connector"}


@app.get("/.well-known/mcp")
@app.get("/.well-known/mcp/")
@app.get("/.well-known/mcp/manifest.json")
@app.get("/.well-known/mcp/manifest.json/")
async def mcp_manifest() -> JSONResponse:
    """Expose MCP discovery metadata from the committed manifest."""
    return JSONResponse(_load_manifest())


# Mount the MCP app last so explicit health and discovery routes win first.
# Mounting at root preserves the SDK's own configured transport path, normally /mcp.
app.mount("/", AuthHeaderMiddleware(_build_mcp_asgi_app()))
