# Binance Multi-Market Spot Bot

A Python command-line application that monitors multiple USDT markets and can
place market orders on Binance Spot.

## What it does

- Downloads the latest 100 one-minute candles from Binance.
- Calculates 14-period RSI and ATR indicators.
- Estimates support and resistance from the latest 20 candles.
- Buys a fixed USDT amount when RSI is oversold or price is near support.
- Sells the tracked position at its stop loss, take profit, or RSI sell signal.
- Uses a 1:2 risk/reward ratio and a stop distance of 1.5 ATR.
- Monitors `BTCUSDT`, `ETHUSDT`, and `TRXUSDT` by default.
- Tracks one independent open position per symbol in `trade_state.json`.
- Limits the number of open positions and total USDT entry exposure.
- Records filled orders in `transactions.jsonl` and displays them in a local
  Streamlit dashboard.

The current `TESTNET = False` setting uses **Binance Spot production**. Orders
are real whenever `ENABLE_TRADING=true`. Keep trading disabled while changing
or validating configuration.

## Requirements

- Python 3.9 or newer
- `pandas`
- `python-binance`
- `streamlit` for the local transaction dashboard
- Binance Spot production API credentials with Spot trading permission

## Create the virtual environment

Open PowerShell in the project directory and create a virtual environment named
`.venv`:

```powershell
py -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, allow local scripts for your user
account and then try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

When activation succeeds, the terminal prompt normally starts with `(.venv)`.

## Install the dependencies

With `.venv` activated, upgrade `pip` and install the libraries used by the
application:

```powershell
python -m pip install --upgrade pip
python -m pip install pandas python-binance streamlit
```

Confirm that the packages were installed into the active environment:

```powershell
python -m pip show pandas python-binance streamlit
```

Do not install the package named only `binance`; it is a different library and
does not provide the `binance.client` module required by this application.

If you do not want to activate the environment, you can install the packages
through its Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install pandas python-binance streamlit
```

## Configure markets and risk limits

Never put API credentials directly in `app.py`. Set production credentials in
the PowerShell session used to run the bot:

Set the credentials in the PowerShell session used to run the bot:

```powershell
$env:BINANCE_API_KEY = "your-production-api-key"
$env:BINANCE_API_SECRET = "your-production-secret"
```

Trading is disabled by default. The default mode downloads data and prints
signals without submitting orders. Configure the comma-separated USDT markets:

```powershell
$env:TRADING_SYMBOLS = "BTCUSDT,ETHUSDT,TRXUSDT"
```

Each symbol can have at most one tracked position. Configure entry and portfolio
limits before enabling orders:

```powershell
$env:TRADE_AMOUNT_USDT = "10"
$env:MAX_OPEN_POSITIONS = "2"
$env:MAX_TOTAL_EXPOSURE_USDT = "20"
```

- `TRADE_AMOUNT_USDT` is the maximum amount spent by one buy.
- `MAX_OPEN_POSITIONS` is the maximum number of symbols held simultaneously.
- `MAX_TOTAL_EXPOSURE_USDT` caps the combined original entry values.

The bot currently supports USDT-quoted Spot pairs only. To explicitly enable
real production orders:

```powershell
$env:ENABLE_TRADING = "true"
```

These environment variables last for the current PowerShell session. Avoid
storing secrets in scripts or committing them to source control.

Other settings near the top of `app.py` control:

- Trading symbols (`BTCUSDT`, `ETHUSDT`, and `TRXUSDT` by default)
- Candle interval (one minute by default)
- Risk/reward ratio
- ATR stop-loss multiplier

## Run

With `.venv` activated, execute:

```powershell
python app.py
```

Alternatively, run it without activation:

```powershell
.\.venv\Scripts\python.exe -u app.py
```

The program analyzes every configured market sequentially, prints the reports,
and starts another cycle every 60 seconds.
Press `Ctrl+C` to stop it.

The stop loss and take profit are evaluated by this running Python process;
they are not protective orders stored at Binance. If the program or computer
stops, those exits cannot execute. Validate changes with trading disabled before
allowing production orders.

## Transaction dashboard

Keep the bot running in its PowerShell window. Open a second PowerShell window
in the project directory and start the dashboard:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Streamlit normally opens the dashboard automatically. If it does not, open:

```text
http://localhost:8501
```

The browser dashboard refreshes every five seconds and displays:

- A sticky top summary bar with available USDT, open-position count, maximum
  allowed exposure, today's realized P&L, total realized P&L, and compact
  symbol/status tags
- Every currently tracked position and its stop-loss/take-profit levels
- Available free USDT reported by the running bot
- Current-price progress between stop loss, entry, and take profit
- Live unrealized USDT profit and percentage beside each open position
- A confirmed **Sell now** control beside each open-position progress bar
- Header tags for every targeted symbol and its latest short bot status, such as
  `WAITING TO BUY`, `MONITORING`, or `BUY FILLED`
- Six read-only Binance Spot watchlist candidates with current price, 24-hour
  change, trading range, USDT volume, and a short justification
- Filled production buy and sell orders across all configured symbols
- Completed-trade results grouped by symbol, including win rate and estimated P&L
- Collapsible color-coded result cards per symbol, with green/red total P&L,
  completed trades, wins, win rate, and average P&L
- Transaction filters for symbol, side, reason, environment, and date range
- Estimated realized profit or loss before commissions
- A CSV download of the filtered transaction history

### Change targets and maximum exposure from the dashboard

Open the compact **Trading targets and exposure** popover near the top. It shows
the current maximum total exposure and targeted symbols. Enter:

- A maximum combined entry exposure in USDT
- Comma-separated Binance USDT Spot symbols such as
  `BTCUSDT,ETHUSDT,SOLUSDT`

Select **Save and confirm settings**. The settings are written to
`bot_config.json`, and the running bot loads them at the start of its next
analysis cycle. The dashboard refuses to remove a symbol that has an open
position, so the bot can continue monitoring its exit.

The bot validates new symbols against Binance before analyzing or trading them.
An invalid or unavailable pair is reported as an error and does not prevent
other configured markets from being processed.

The six-currency Spot watchlist is collapsed by default. Expand it only when
you want to review the current candidates and analysis.

### Manually close a tracked position

Select **Sell now** beside an open-position progress bar, review the warning,
then select **Confirm market sell**. The dashboard queues a request; it does not
hold Binance credentials or submit the order itself. The running bot validates
the environment and tracked position, then submits a market sell within a few
seconds.

Manual sell requests expire after 30 seconds and are available only when
`ENABLE_TRADING=true`. Market execution can differ from the price displayed on
the dashboard. The bot also holds a local single-instance lock so a second copy
of `app.py` cannot process real-money commands concurrently.

The bot and dashboard have separate roles:

- `app.py` must remain running to analyze the market and execute testnet orders.
- `dashboard.py` reads local state and history and can queue a confirmed manual
  sell request; only `app.py` holds credentials and submits the market order.
- `trade_state.json` contains positions keyed by trading symbol and records the
  environment that created them.
- `transactions.jsonl` contains the persistent filled-order history.
- `bot_status.json` contains the latest available USDT and market prices used by
  the dashboard. It also contains the latest market watchlist. The watchlist is
  refreshed from Binance every 15 minutes and screens positively moving USDT
  pairs with at least 30 million USDT in rolling 24-hour volume, ranked by their
  24-hour price range.
- `bot_config.json` contains dashboard-confirmed target symbols and maximum total
  USDT exposure. It contains no API credentials.
- `sell_requests.jsonl` is a short-lived local queue for confirmed dashboard
  market-sell requests.

The bot begins recording transactions after this feature is installed. Orders
placed before then are not present in `transactions.jsonl` and cannot appear in
the dashboard. Stop the dashboard with `Ctrl+C` in its terminal.

When you are finished using an activated environment, leave it with:

```powershell
deactivate
```

## Disclaimer

This project is for educational and informational purposes. Its signals are
based on simple technical rules and are not financial advice. Test and validate
any strategy independently before risking funds.

Dashboard watchlist candidates are volatility observations, not buy signals or
profit forecasts. High volatility can produce rapid losses as well as gains.
