from statistics import mean
import math


# -----------------------------
# SETTINGS
# -----------------------------

ACCOUNT_SIZE = 20_000
RISK_PER_TRADE = 0.01
STOP_LOSS_PCT = 0.01
TAKE_PROFIT_PCT = 0.03

SHORT_MA = 5
LONG_MA = 20
RSI_PERIOD = 14


# -----------------------------
# DEMO MARKET DATA
# -----------------------------

prices = [
    98.20, 98.75, 99.10, 99.40, 99.85,
    100.10, 100.55, 100.30, 100.90, 101.25,
    101.60, 101.95, 102.10, 102.45, 102.80,
    103.10, 103.35, 103.70, 104.05, 104.30,
    104.55, 104.85, 105.10, 105.40, 105.75,
]


# -----------------------------
# INDICATORS
# -----------------------------

def moving_average(data, period):
    return mean(data[-period:])


def calculate_rsi(data, period=14):
    changes = [
        data[i] - data[i - 1]
        for i in range(len(data) - period, len(data))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [abs(min(change, 0)) for change in changes]

    avg_gain = mean(gains)
    avg_loss = mean(losses)

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# -----------------------------
# READ THE MARKET
# -----------------------------

price = prices[-1]

short_ma = moving_average(prices, SHORT_MA)
long_ma = moving_average(prices, LONG_MA)
rsi = calculate_rsi(prices, RSI_PERIOD)


# -----------------------------
# SCORE THE TRADE
# -----------------------------

score = 0

if short_ma > long_ma:
    score += 2
else:
    score -= 2

if 50 <= rsi <= 70:
    score += 1
elif rsi > 75:
    score -= 1

if price > short_ma:
    score += 1
else:
    score -= 1


# -----------------------------
# MAKE A DECISION
# -----------------------------

if score >= 3:
    signal = "BUY"

elif score <= -3:
    signal = "SELL"

else:
    signal = "HOLD"


# -----------------------------
# RISK MANAGEMENT
# -----------------------------

quantity = 0
stop_loss = None
take_profit = None

if signal == "BUY":

    allowed_risk = ACCOUNT_SIZE * RISK_PER_TRADE

    risk_per_share = price * STOP_LOSS_PCT

    quantity = math.floor(
        allowed_risk / risk_per_share
    )

    stop_loss = price * (1 - STOP_LOSS_PCT)

    take_profit = price * (1 + TAKE_PROFIT_PCT)


# -----------------------------
# OUTPUT
# -----------------------------

print("TRADING ALGORITHM DECISION")
print("--------------------------")

print("Signal:", signal)
print("Price:", round(price, 2))
print("Short MA:", round(short_ma, 2))
print("Long MA:", round(long_ma, 2))
print("RSI:", round(rsi, 2))
print("Score:", score)
print("Quantity:", quantity)

if stop_loss:
    print("Stop Loss:", round(stop_loss, 2))

if take_profit:
    print("Take Profit:", round(take_profit, 2))

print()
print("Simulation only - no real order was placed.")
