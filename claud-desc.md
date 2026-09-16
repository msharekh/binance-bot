# Binance Bot — Application Overview

## What this is

A Python trading bot for Binance Spot, plus a Streamlit dashboard, running
against **live production** by default (`TESTNET=False`).

## Core loop (`app.py`, ~1650 lines)

- `main()` runs forever, once per ~60s cycle (with a faster 15s poll for live
  prices/take-profit checks in between).
- For each target symbol: `analyze_market()` pulls the last 100 candles at the
  configured interval, computes RSI(14) and ATR(14), support/resistance from
  the last 20 candles, EMA9/21 momentum, and a higher-timeframe trend EMA (1h
  EMA-50 by default).
- **Buy signal** requires ALL of: RSI just crossed up through the recovery
  threshold (35 default) and is still rising, price near support (≤0.30%
  away), higher-TF trend price above its EMA, EMA9>EMA21 momentum, expected
  net TP reward after fees ≥ minimum, and stop distance not too wide.
- **Sell** happens on stop-loss hit, take-profit hit, or RSI≥65 exit signal
  (with a minimum-net-profit guard on the RSI exit).
- Risk model: stop = 1.5×ATR below entry, target = 2:1 reward/risk,
  take-profit is re-checked continuously against live ticker prices, not just
  candles.
- Positions persist in `trade_state.json`, keyed per-symbol (one position per
  symbol), with cooldown tracking in `entry_cooldowns.json` so a symbol can't
  rebuy off the same candle signal it just exited on.
- All fills logged to `transactions.jsonl` via `commission_accounting.py`
  (tracks actual/estimated commissions and realized P&L, including partial
  fills/dust).
- `bot_config.json` (limits, targets, hold-toggle, strategy params) is
  hot-reloaded every cycle so the dashboard can steer the bot without
  restarting it.
- Dashboard-queued manual buy/sell requests (`buy_requests.jsonl` /
  `sell_requests.jsonl`) are drained each cycle — the dashboard itself never
  holds API credentials.
- A Windows file lock (`bot.lock` via `msvcrt`) prevents two bot instances
  from double-trading.
- `get_market_suggestions()` scans the whole Binance USDT universe every 15
  min for a watchlist and an overall market-regime classification
  (quiet/positive/weak/mixed) used to optionally pause new buys in weak
  markets.

## Dashboard (`dashboard.py`, huge — 165KB)

Streamlit UI reading the JSON/JSONL state files, showing market cards with
the 5-part buy checklist, open positions with live P&L, the watchlist,
transaction history, and an optional AI advisor (`advisor.py`, OpenAI-backed,
off by default, sanitized inputs only).

## Uncommitted state (as of writing)

`live_prices.json` is modified — expected, it's bot-written runtime state,
not source.
