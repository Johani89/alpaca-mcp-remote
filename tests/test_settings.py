from alpaca_connector.settings import Settings


def test_auth_is_secure_by_default(monkeypatch):
    monkeypatch.delenv("REQUIRE_MCP_AUTH", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    settings = Settings()
    assert settings.require_mcp_auth is True
    assert settings.validate_startup() == [
        "MCP_AUTH_TOKEN is required when REQUIRE_MCP_AUTH=true"
    ]


def test_paper_is_default(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_TRADE", raising=False)
    assert Settings().paper is True
