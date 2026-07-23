"""MCP tool registration grouped by authority level."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .broker import Broker
from .risk import evaluate_order
from .settings import Settings


READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
PREPARE = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
)


def register_tools(mcp: FastMCP[Any], settings: Settings, broker: Broker) -> None:
    @mcp.tool(
        name="connector_get_health",
        title="Get connector health",
        description="A0 Observe: report connector configuration without exposing secrets.",
        annotations=READ_ONLY,
    )
    def connector_get_health() -> dict[str, Any]:
        return {
            "status": "ok" if not settings.validate_startup() else "misconfigured",
            "version": "2.0.0",
            "paper": settings.paper,
            "credentials_configured": settings.credentials_configured,
            "auth_required": settings.require_mcp_auth,
            "watchlist": list(settings.watchlist),
            "configuration_errors": settings.validate_startup(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @mcp.tool(
        name="market_get_clock",
        title="Get market clock",
        description="A0 Observe: get the current Alpaca market clock.",
        annotations=READ_ONLY,
    )
    def market_get_clock() -> dict[str, Any]:
        return broker.get_clock()

    @mcp.tool(
        name="account_get_summary",
        title="Get Alpaca account",
        description="A0 Observe: get paper account balances, status, and buying power.",
        annotations=READ_ONLY,
    )
    def account_get_summary() -> dict[str, Any]:
        return broker.get_account()

    @mcp.tool(
        name="positions_list",
        title="List positions",
        description="A0 Observe: list current paper-account positions.",
        annotations=READ_ONLY,
    )
    def positions_list() -> list[dict[str, Any]]:
        return broker.list_positions()

    @mcp.tool(
        name="orders_list",
        title="List orders",
        description="A0 Observe: list Alpaca paper-account orders.",
        annotations=READ_ONLY,
    )
    def orders_list(status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        return broker.list_orders(status=status, limit=limit)

    def preflight(
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        side = side.strip().lower()
        order_type = order_type.strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        if order_type == "limit" and (limit_price is None or limit_price <= 0):
            raise ValueError("a positive limit_price is required for limit orders")
        reference_price = (
            float(limit_price)
            if order_type == "limit" and limit_price is not None
            else broker.latest_trade_price(symbol)
        )
        account = broker.get_account()
        positions = broker.list_positions()
        open_orders = broker.list_orders(status="open", limit=500)
        decision = evaluate_order(
            settings=settings,
            account=account,
            positions=positions,
            open_orders=open_orders,
            symbol=symbol,
            side=side,
            quantity=quantity,
            reference_price=reference_price,
        )
        return {
            "request": {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "limit_price": limit_price,
                "reference_price": reference_price,
            },
            "risk": decision.as_dict(),
        }

    @mcp.tool(
        name="orders_preview_stock",
        title="Preview stock order",
        description="A1 Prepare: validate and risk-check a stock order without submitting it.",
        annotations=PREPARE,
    )
    def orders_preview_stock(
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        return preflight(symbol, side, quantity, order_type, limit_price)

    @mcp.tool(
        name="orders_submit_paper_stock",
        title="Submit paper stock order",
        description=(
            "A2 Execute bounded: submit a stock order only to an Alpaca paper account "
            "after server-side risk checks. Live accounts are always rejected."
        ),
        annotations=WRITE,
    )
    def orders_submit_paper_stock(
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        preview = preflight(symbol, side, quantity, order_type, limit_price)
        if not preview["risk"]["allowed"]:
            return {"submitted": False, **preview}
        request = preview["request"]
        client_order_id = f"jarvis-{uuid4().hex[:24]}"
        order = broker.submit_stock_order(
            symbol=request["symbol"],
            side=request["side"],
            quantity=request["quantity"],
            order_type=request["order_type"],
            limit_price=request["limit_price"],
            client_order_id=client_order_id,
        )
        return {
            "submitted": True,
            "authority": "A2",
            "client_order_id": client_order_id,
            "risk": preview["risk"],
            "order": order,
        }

    @mcp.tool(
        name="orders_cancel_paper",
        title="Cancel paper order",
        description="A2 Execute bounded: cancel one paper-account order by ID.",
        annotations=DESTRUCTIVE,
    )
    def orders_cancel_paper(order_id: str) -> dict[str, Any]:
        if not settings.paper:
            raise PermissionError("Live-account actions are disabled")
        return broker.cancel_order(order_id)

    @mcp.tool(
        name="positions_close_paper",
        title="Close paper position",
        description="A2 Execute bounded: close one paper-account position by symbol.",
        annotations=DESTRUCTIVE,
    )
    def positions_close_paper(symbol: str) -> dict[str, Any]:
        if not settings.paper:
            raise PermissionError("Live-account actions are disabled")
        return broker.close_position(symbol.strip().upper())
