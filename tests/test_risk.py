from alpaca_connector.risk import evaluate_order
from alpaca_connector.settings import Settings


def configured_settings(**overrides):
    values = {
        "paper": True,
        "max_position_pct": 0.05,
        "max_notional_trade": 1000.0,
        "max_open_positions": 10,
        "max_daily_loss_pct": 0.02,
    }
    values.update(overrides)
    return Settings(**values)


def test_allows_bounded_paper_order():
    decision = evaluate_order(
        settings=configured_settings(),
        account={"equity": "20000", "last_equity": "20000"},
        positions=[],
        open_orders=[],
        symbol="AAPL",
        side="buy",
        quantity=2,
        reference_price=200,
    )
    assert decision.allowed is True


def test_blocks_live_and_notional_breach():
    decision = evaluate_order(
        settings=configured_settings(paper=False),
        account={"equity": "20000", "last_equity": "20000"},
        positions=[],
        open_orders=[],
        symbol="AAPL",
        side="buy",
        quantity=10,
        reference_price=200,
    )
    assert decision.allowed is False
    assert "Live trading is disabled by this connector" in decision.reasons
    assert "Order exceeds maximum trade notional" in decision.reasons


def test_blocks_daily_loss_and_duplicate_entry():
    decision = evaluate_order(
        settings=configured_settings(),
        account={"equity": "9700", "last_equity": "10000"},
        positions=[{"symbol": "AAPL"}],
        open_orders=[],
        symbol="AAPL",
        side="buy",
        quantity=1,
        reference_price=100,
    )
    assert decision.allowed is False
    assert "Daily loss kill switch is active" in decision.reasons
    assert "Duplicate entry blocked: position already exists" in decision.reasons
