"""Pure risk checks used before every paper order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .settings import Settings


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]
    estimated_notional: float
    daily_loss_pct: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "estimated_notional": round(self.estimated_notional, 2),
            "daily_loss_pct": round(self.daily_loss_pct, 6),
        }


def evaluate_order(
    *,
    settings: Settings,
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    symbol: str,
    side: str,
    quantity: float,
    reference_price: float,
) -> RiskDecision:
    reasons: list[str] = []
    equity = float(account.get("equity") or 0)
    last_equity = float(account.get("last_equity") or equity or 0)
    daily_loss_pct = max(0.0, (last_equity - equity) / last_equity) if last_equity else 0.0
    estimated_notional = quantity * reference_price

    if not settings.paper:
        reasons.append("Live trading is disabled by this connector")
    if quantity <= 0:
        reasons.append("Quantity must be greater than zero")
    if reference_price <= 0:
        reasons.append("Reference price must be greater than zero")
    if daily_loss_pct >= settings.max_daily_loss_pct:
        reasons.append("Daily loss kill switch is active")
    if estimated_notional > settings.max_notional_trade:
        reasons.append("Order exceeds maximum trade notional")
    if equity and estimated_notional > equity * settings.max_position_pct:
        reasons.append("Order exceeds maximum position percentage")

    symbols = {str(position.get("symbol", "")).upper() for position in positions}
    open_buy_symbols = {
        str(order.get("symbol", "")).upper()
        for order in open_orders
        if str(order.get("side", "")).lower() == "buy"
    }
    if side == "buy" and symbol in symbols:
        reasons.append("Duplicate entry blocked: position already exists")
    if side == "buy" and symbol in open_buy_symbols:
        reasons.append("Duplicate entry blocked: open buy order already exists")
    if side == "buy" and symbol not in symbols and len(symbols) >= settings.max_open_positions:
        reasons.append("Maximum open positions reached")

    return RiskDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        estimated_notional=estimated_notional,
        daily_loss_pct=daily_loss_pct,
    )
