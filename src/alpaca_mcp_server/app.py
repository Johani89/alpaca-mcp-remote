"""ASGI entrypoint for the remote Alpaca MCP server deployment.

Railway should import this module with:
    uvicorn alpaca_mcp_server.app:app --host 0.0.0.0 --port ${PORT:-8080}

The rule engine has its own ASGI app at alpaca_rule_engine.control:app and is
intentionally not imported here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from . import __version__
from .server import AuthHeaderMiddleware, mcp


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / ".well-known" / "mcp" / "manifest.json"


def _load_manifest() -> dict[str, Any]:
    """Load the MCP manifest shipped with the repository."""
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP manifest not found") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="MCP manifest is invalid JSON") from exc


def _configure_mcp_transport_path() -> None:
    """Pin the FastMCP streamable HTTP endpoint to /mcp when supported."""
    settings = getattr(mcp, "settings", None)
    if settings is not None and hasattr(settings, "streamable_http_path"):
        settings.streamable_http_path = "/mcp"


def _build_mcp_asgi_app():
    """Return the FastMCP ASGI app for the installed MCP SDK version."""
    _configure_mcp_transport_path()

    streamable_http_app = getattr(mcp, "streamable_http_app", None)
    if callable(streamable_http_app):
        return streamable_http_app()

    http_app = getattr(mcp, "http_app", None)
    if callable(http_app):
        return http_app(path="/mcp")

    app_attr = getattr(mcp, "app", None)
    if app_attr is not None:
        return app_attr() if callable(app_attr) else app_attr

    raise RuntimeError("Installed MCP SDK does not expose an ASGI HTTP transport app")


mcp_asgi_app = _build_mcp_asgi_app()
mcp_lifespan = getattr(mcp_asgi_app, "lifespan", None)
if not callable(mcp_lifespan):
    mcp_router = getattr(mcp_asgi_app, "router", None)
    mcp_lifespan = getattr(mcp_router, "lifespan_context", None)

app = FastAPI(
    title="Alpaca MCP Server",
    version=__version__,
    description="Remote MCP transport for Alpaca trading tools.",
    lifespan=mcp_lifespan if callable(mcp_lifespan) else None,
)


@app.get("/health")
@app.get("/health/")
async def health() -> dict[str, Any]:
    """Railway health check for the MCP service, not the rule engine."""
    return {
        "status": "ok",
        "service": "alpaca-mcp-server",
        "version": __version__,
        "transport": "/mcp",
    }


@app.get("/.well-known/mcp/manifest.json")
async def mcp_manifest() -> JSONResponse:
    """Return the MCP manifest JSON for discovery."""
    return JSONResponse(_load_manifest())


@app.get("/.well-known/mcp")
async def mcp_manifest_alias() -> JSONResponse:
    """Compatibility alias for clients that probe /.well-known/mcp."""
    return JSONResponse(_load_manifest())


# Mount the real MCP transport after concrete routes so /health and discovery stay
# owned by this dedicated ASGI entrypoint. AuthHeaderMiddleware preserves inbound
# Authorization headers for downstream Alpaca SDK calls.
app.mount("/", AuthHeaderMiddleware(mcp_asgi_app))
