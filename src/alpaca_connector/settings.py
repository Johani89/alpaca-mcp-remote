"""Environment-backed configuration with secure trading defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _symbols(name: str) -> tuple[str, ...]:
    return tuple(
        symbol.strip().upper()
        for symbol in os.getenv(name, "").split(",")
        if symbol.strip()
    )


@dataclass(frozen=True)
class Settings:
    api_key: str | None = field(default_factory=lambda: os.getenv("ALPACA_API_KEY"))
    secret_key: str | None = field(default_factory=lambda: os.getenv("ALPACA_SECRET_KEY"))
    paper: bool = field(default_factory=lambda: _bool("ALPACA_PAPER_TRADE", True))
    trade_api_url: str | None = field(default_factory=lambda: os.getenv("TRADE_API_URL"))
    data_api_url: str | None = field(default_factory=lambda: os.getenv("DATA_API_URL"))
    mcp_auth_token: str | None = field(default_factory=lambda: os.getenv("MCP_AUTH_TOKEN"))
    require_mcp_auth: bool = field(default_factory=lambda: _bool("REQUIRE_MCP_AUTH", True))
    watchlist: tuple[str, ...] = field(default_factory=lambda: _symbols("WATCHLIST_SYMBOLS"))
    max_position_pct: float = field(
        default_factory=lambda: _float("MAX_POSITION_PCT", 0.05)
    )
    max_notional_trade: float = field(
        default_factory=lambda: _float("MAX_NOTIONAL_TRADE", 1000.0)
    )
    max_open_positions: int = field(
        default_factory=lambda: _int("MAX_OPEN_POSITIONS", 10)
    )
    max_daily_loss_pct: float = field(
        default_factory=lambda: _float("MAX_DAILY_LOSS_PCT", 0.02)
    )

    @property
    def credentials_configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def validate_startup(self) -> list[str]:
        errors: list[str] = []
        if self.require_mcp_auth and not self.mcp_auth_token:
            errors.append("MCP_AUTH_TOKEN is required when REQUIRE_MCP_AUTH=true")
        for name, value in (
            ("MAX_POSITION_PCT", self.max_position_pct),
            ("MAX_NOTIONAL_TRADE", self.max_notional_trade),
            ("MAX_DAILY_LOSS_PCT", self.max_daily_loss_pct),
        ):
            if value <= 0:
                errors.append(f"{name} must be greater than zero")
        if self.max_open_positions < 1:
            errors.append("MAX_OPEN_POSITIONS must be at least one")
        return errors
