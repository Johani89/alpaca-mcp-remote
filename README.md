# Jarvis Alpaca Connector

A single-purpose remote MCP server for Alpaca. It is designed for ChatGPT custom
apps and exposes structured account, market, position, order-preview, and bounded
paper-order tools.

## Safety model

- Live order submission is not exposed.
- Paper mode is the default and every write tool refuses a live account.
- New paper orders pass server-side notional, position-size, open-position,
  duplicate-order, and daily-loss checks.
- MCP authentication is required by default.
- Health checks never disclose credentials or tokens.

## Railway variables

Required:

- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `MCP_AUTH_TOKEN` (generate at least 32 random bytes)

Recommended:

- `ALPACA_PAPER_TRADE=true`
- `REQUIRE_MCP_AUTH=true`
- `MAX_POSITION_PCT=0.05`
- `MAX_NOTIONAL_TRADE=1000`
- `MAX_OPEN_POSITIONS=10`
- `MAX_DAILY_LOSS_PCT=0.02`
- `WATCHLIST_SYMBOLS=AZZ,VRT,SLNO,MP,RARE`

## ChatGPT custom app

For the private, single-user deployment, create the app with:

- Endpoint: `https://YOUR-RAILWAY-DOMAIN/mcp?token=YOUR_MCP_AUTH_TOKEN`
- Authentication: `No authentication`

The query token is a transitional single-user authentication method because the
ChatGPT custom-app form does not accept a static bearer header. Uvicorn access
logging is disabled so the token is not written to normal request logs. Rotate the
token after accidental disclosure. Move to an OAuth provider before granting
multi-user access.

## Local verification

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```
