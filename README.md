# Binance Multi-Market Spot Bot

A Python command-line application that monitors multiple USDT markets and can
place market orders on Binance Spot.

## What it does

- Downloads completed candles for the selected trading interval from Binance.
- Calculates 14-period RSI and ATR indicators.
- Estimates support and resistance from the latest 20 candles.
- Buys only after RSI recovers upward through its threshold while price is near
  support, the higher-timeframe price is above its EMA, and expected TP reward
  remains above the configured minimum after estimated fees.
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
- `openai` for the optional Version 2 AI advisor
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
python -m pip install -r requirements.txt
```

Confirm that the packages were installed into the active environment:

```powershell
python -m pip show pandas python-binance streamlit openai
```

Do not install the package named only `binance`; it is a different library and
does not provide the `binance.client` module required by this application.

If you do not want to activate the environment, you can install the packages
through its Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Version 2 AI advisor

Version 2 adds a short AI brief beside the interval badge in the dashboard. The
full analysis is available in the **Version 2 AI** section in the sidebar. It
summarizes progress and results, highlights what appears right or wrong, and
suggests small, testable improvements to settings or code.

The advisor is paused by default, guaranteeing that it makes no OpenAI API
requests. When API billing is ready, set the enable switch and an OpenAI API key
in the same PowerShell window used to start Streamlit:

```powershell
$env:ENABLE_AI_ADVISOR = "true"
$env:OPENAI_API_KEY = "your-openai-api-key"
streamlit run dashboard.py
```

To pause it again, stop Streamlit and run:

```powershell
$env:ENABLE_AI_ADVISOR = "false"
streamlit run dashboard.py
```

The default model is `gpt-5.4-mini`. You can optionally select another model
before starting the dashboard:

```powershell
$env:OPENAI_MODEL = "gpt-5.4-mini"
```

The advisor refreshes at most once every 15 minutes and also has a manual
**Refresh AI brief** button. Results are cached locally in `ai_brief.json`, so
normal dashboard refreshes do not repeatedly call the API.

Only summarized trading metrics, configured limits, indicators, and position
values are sent for analysis. Binance API keys, OpenAI API keys, and order IDs
are not included. OpenAI requests use `store=False`. The advisor cannot place
orders or change bot settings; its output is informational and is not a profit
guarantee. OpenAI API usage is billed separately by OpenAI.

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

Other defaults near the top of `app.py` control:

- Trading symbols (`BTCUSDT`, `ETHUSDT`, and `TRXUSDT` by default)
- Candle interval (15 minutes by default; it can also be changed from the dashboard)
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

- A sticky top summary bar with available USDT, current USDT market value across
  open trades, their combined bot-tracked value, the Binance-wide Spot portfolio
  estimate, open-position count, maximum per-trade amount, maximum total
  exposure, today's realized P&L, current
  unrealized P&L for open positions, today's and all-time completed-trade win
  rates, total realized P&L, and the active interval
- Color-coded market-check cards that flash after each new bot cycle and show
  price, RSI, ATR, support, resistance, signal, suggested SL/TP, and bot status
- Live card prices and open-position progress refreshed every 10 seconds, with
  up/down direction indicators; indicator calculations still use the selected
  completed-candle interval
- A cached Version 2 AI performance headline beside the interval badge, with a
  detailed read-only analysis in the sidebar
- Every currently tracked position and its stop-loss/take-profit levels
- Available free USDT reported by the running bot
- Current-price progress between stop loss, entry, and take profit
- Live unrealized USDT profit and percentage beside each open position
- A confirmed **Sell now** control beside each open-position progress bar
- Compact bordered open-position cards shown two per row, so each transaction is
  visually separated while current price, entry, exit distance, P&L, and actions
  remain easy to scan
- Every open-position card shows unit price and corresponding gross USDT position
  value at entry, current price, take profit, and stop loss
- Six read-only Binance Spot watchlist candidates with current price, 24-hour
  change, trading range, USDT volume, and a short justification
- Filled production buy and sell orders across all configured symbols
- Completed-trade results grouped by symbol, including win rate and estimated P&L
- Collapsible color-coded result cards per symbol, with green/red total P&L,
  completed trades, wins, win rate, and average P&L
- Transaction filters for symbol, side, reason, environment, and date range
- Color-coded transaction rows and a clear `PROFIT`, `LOSS`, `BREAK EVEN`, or
  `ENTRY` result label
- Estimated realized profit or loss before commissions
- A CSV download of the filtered transaction history

### Change targets and maximum exposure from the dashboard

Open **Trading controls** under **Bot controls** in the sidebar. The compact form
is organized into **Limits**, **Buy**, **Sell**, and **Targets** tabs, with one
shared save button. Configure:

- A per-trade maximum amount in USDT
- A maximum combined entry exposure in USDT
- A maximum number of simultaneously open positions
- A candle interval from the dropdown: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`,
  `2h`, `4h`, `6h`, `8h`, `12h`, `1d`, `3d`, `1w`, or `1M`
- Buy confirmation controls: RSI recovery level, maximum distance from support,
  higher-trend candle interval and EMA period, minimum net TP reward, and an
  estimated round-trip fee/slippage percentage
- Sell controls: ATR stop-loss multiplier, take-profit reward/risk ratio, and
  RSI exit threshold. TP is always above entry:
  `entry + (ATR × stop multiplier × reward/risk)`
- Binance USDT Spot symbols such as `BTCUSDT`, `ETHUSDT`, and `SOLUSDT`; use
  **Quick add target** and **Add** for reliable one-click insertion. To remove a
  market, open **Targets**, select the x on its tag, and save all controls.
- Optionally enable **Hold new buys** to pause new entries

Select **Save and confirm settings**. The settings are written to
`bot_config.json`, and the running bot loads them at the start of its next
analysis cycle. If you remove a target that still has an open position, the bot
continues monitoring that position until it closes but does not seek a new entry.

After the dashboard saves `max_open_positions` in `bot_config.json`, that value
overrides the `$env:MAX_OPEN_POSITIONS` default. You can safely set it below the
current number of positions; the bot will keep monitoring existing positions but
will not open another one until the count is below the new limit.

Changing the candle interval affects the next market analysis and future entry
signals. It does not recalculate the entry, stop loss, or take profit already
stored for an open position.

Changing the ATR stop multiplier or reward/risk ratio also applies only to
future positions. The RSI sell threshold is evaluated for all monitored open
positions on the next completed-candle analysis. The fee percentage is an
entry-quality estimate; recorded P&L remains an estimate before actual Binance
commissions.

When **Hold new buys** is enabled, the dashboard shows a prominent orange hold
banner. Existing positions remain monitored: stop-loss, take-profit, RSI exits,
and confirmed manual sells continue to work. Disable the toggle and save again
to resume new entries.

The bot validates new symbols against Binance before analyzing or trading them.
An invalid or unavailable pair is reported as an error and does not prevent
other configured markets from being processed.

The six-currency Spot watchlist is collapsed by default. Expand it only when
you want to review the current candidates and analysis.

### Overall market status

The top bar shows a deterministic `MARKET` badge to set expectations. It scans
non-stablecoin, non-leveraged Binance USDT pairs with at least 10 million USDT
in rolling 24-hour volume and calculates:

- **Up breadth:** percentage changing at least +0.5%
- **Down breadth:** percentage changing at most -0.5%
- **Active breadth:** percentage with at least a 1.5% high-to-low range
- Median 24-hour change and median 24-hour range

A market is classified as quiet when active breadth is below 35% or median
range is below 1.5%. Direction is weak when median change is at most -0.5% or
down breadth leads up breadth by at least 15 percentage points; it is positive
when the inverse thresholds are met. A non-quiet market becomes broadly positive
or weak at a median change of +/-1% or directional breadth of at least 60%; all
other cases are mixed. This status describes current breadth and volatility—it
does not predict future prices or bypass the four entry confirmations.

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
  the dashboard. It also contains the Binance-wide Spot portfolio estimate and
  any nonzero assets that could not be converted to USDT, plus the latest market
  watchlist and overall market-breadth classification. The watchlist is
  refreshed from Binance every 15 minutes, excludes stablecoin and leveraged
  pairs, and requires at least +0.5% change, a 1.5% range, and 30 million USDT
  in rolling 24-hour volume. Qualifying pairs are ranked by 24-hour range.
- `bot_config.json` contains dashboard-confirmed target symbols and maximum total
  USDT exposure. It contains no API credentials.
- `sell_requests.jsonl` is a short-lived local queue for confirmed dashboard
  market-sell requests.
- `advisor.py` builds sanitized performance metrics and requests the structured
  Version 2 analysis without access to Binance credentials or order execution.
- `ai_brief.json` is the local cache for the latest AI analysis.

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
