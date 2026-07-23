"""Thin, lazy Alpaca SDK adapter."""

from __future__ import annotations

from typing import Any

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)

from .serialize import jsonable
from .settings import Settings


class Broker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._trading: TradingClient | None = None
        self._stock_data: StockHistoricalDataClient | None = None

    def _require_credentials(self) -> tuple[str, str]:
        if not self.settings.credentials_configured:
            raise RuntimeError("Alpaca credentials are not configured")
        return self.settings.api_key or "", self.settings.secret_key or ""

    @property
    def trading(self) -> TradingClient:
        if self._trading is None:
            key, secret = self._require_credentials()
            self._trading = TradingClient(
                key,
                secret,
                paper=self.settings.paper,
                url_override=self.settings.trade_api_url,
            )
        return self._trading

    @property
    def stock_data(self) -> StockHistoricalDataClient:
        if self._stock_data is None:
            key, secret = self._require_credentials()
            self._stock_data = StockHistoricalDataClient(
                key,
                secret,
                url_override=self.settings.data_api_url,
            )
        return self._stock_data

    def get_clock(self) -> dict[str, Any]:
        return jsonable(self.trading.get_clock())

    def get_account(self) -> dict[str, Any]:
        return jsonable(self.trading.get_account())

    def list_positions(self) -> list[dict[str, Any]]:
        return jsonable(self.trading.get_all_positions())

    def list_orders(self, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        query_status = QueryOrderStatus(status.lower())
        request = GetOrdersRequest(status=query_status, limit=max(1, min(limit, 500)))
        return jsonable(self.trading.get_orders(filter=request))

    def latest_trade_price(self, symbol: str) -> float:
        request = StockLatestTradeRequest(symbol_or_symbols=symbol)
        trades = self.stock_data.get_stock_latest_trade(request)
        return float(trades[symbol].price)

    def submit_stock_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
        client_order_id: str,
    ) -> dict[str, Any]:
        common = {
            "symbol": symbol,
            "qty": quantity,
            "side": OrderSide(side),
            "time_in_force": TimeInForce.DAY,
            "client_order_id": client_order_id,
        }
        if order_type == "market":
            request = MarketOrderRequest(**common)
        elif order_type == "limit":
            if limit_price is None:
                raise ValueError("limit_price is required for a limit order")
            request = LimitOrderRequest(**common, limit_price=limit_price)
        else:
            raise ValueError("order_type must be market or limit")
        return jsonable(self.trading.submit_order(order_data=request))

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self.trading.cancel_order_by_id(order_id)
        return {"cancel_requested": True, "order_id": order_id}

    def close_position(self, symbol: str) -> dict[str, Any]:
        return jsonable(self.trading.close_position(symbol))
