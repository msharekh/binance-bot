# Binance BTC/USDT Market Monitor

A small Python command-line application that monitors the Binance `BTCUSDT`
market and prints a new technical-analysis report every minute.

## What it does

- Downloads the latest 100 one-minute candles from Binance.
- Calculates 14-period RSI and ATR indicators.
- Estimates support and resistance from the latest 20 candles.
- Suggests a long-position entry, stop loss, and take-profit target.
- Uses a 1:2 risk/reward ratio and a stop distance of 1.5 ATR.
- Labels current conditions as buy, sell/no-long, or neutral.

The application is an informational monitor only. It does **not** submit orders
or manage a Binance account.

## Requirements

- Python 3.9 or newer
- `pandas`
- `python-binance`
- A Binance API key with read-only permissions

Install the dependencies:

```powershell
python -m pip install pandas python-binance
```

## Configuration

The current application reads `API_KEY` and `API_SECRET` from `app.py`.
Hard-coding credentials is unsafe. Revoke any credentials that have been
committed or shared, generate replacements, and restrict them to read-only
access. A future revision should load them from environment variables instead.

Other settings near the top of `app.py` control:

- Trading symbol (`BTCUSDT` by default)
- Candle interval (one minute by default)
- Risk/reward ratio
- ATR stop-loss multiplier

## Run

From this directory, execute:

```powershell
python app.py
```

The program prints a report immediately and refreshes it every 60 seconds.
Press `Ctrl+C` to stop it.

## Disclaimer

This project is for educational and informational purposes. Its signals are
based on simple technical rules and are not financial advice. Test and validate
any strategy independently before risking funds.
