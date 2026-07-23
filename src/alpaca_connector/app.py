"""Single-process ASGI entrypoint for Railway and ChatGPT custom apps."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import __version__
from .broker import Broker
from .settings import Settings
from .tools import register_tools


settings = Settings()
broker = Broker(settings)
mcp = FastMCP(
    "Jarvis Alpaca",
    instructions=(
        "Alpaca paper-trading connector. Observe and prepare freely. Use write tools "
        "only for bounded paper-account actions. This connector exposes no live-order tool."
    ),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)
register_tools(mcp, settings, broker)


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> Response:
    errors = settings.validate_startup()
    return JSONResponse(
        {
            "status": "ok" if not errors else "misconfigured",
            "service": "jarvis-alpaca-connector",
            "version": __version__,
            "paper": settings.paper,
            "credentials_configured": settings.credentials_configured,
            "errors": errors,
        },
        status_code=200 if not errors else 503,
    )


class ConnectorAuthMiddleware:
    """Accept a bearer token or ChatGPT-compatible query token on MCP calls."""

    def __init__(self, wrapped: Any):
        self.wrapped = wrapped

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not settings.require_mcp_auth:
            await self.wrapped(scope, receive, send)
            return
        if scope.get("path") == "/health":
            await self.wrapped(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("utf-8")
        bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
        query_token = query.get("token", [""])[0]
        expected = settings.mcp_auth_token or ""
        supplied = bearer or query_token
        if expected and supplied and secrets.compare_digest(supplied, expected):
            await self.wrapped(scope, receive, send)
            return

        response = JSONResponse({"error": "unauthorized"}, status_code=401)
        await response(scope, receive, send)


app = ConnectorAuthMiddleware(mcp.streamable_http_app())
