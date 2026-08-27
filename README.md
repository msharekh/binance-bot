# Binance BTC/USDT Market Monitor

A small Python command-line application that monitors `BTCUSDT` and can place
market orders on Binance Spot Testnet.

## What it does

- Downloads the latest 100 one-minute candles from Binance.
- Calculates 14-period RSI and ATR indicators.
- Estimates support and resistance from the latest 20 candles.
- Buys a fixed USDT amount when RSI is oversold or price is near support.
- Sells the tracked position at its stop loss, take profit, or RSI sell signal.
- Uses a 1:2 risk/reward ratio and a stop distance of 1.5 ATR.
- Stores the open position in `trade_state.json` to prevent repeated buys.

The application is intentionally locked to **Binance Spot Testnet**. Testnet
orders use simulated funds and do not buy or sell real cryptocurrency.

## Requirements

- Python 3.9 or newer
- `pandas`
- `python-binance`
- `streamlit` for the local transaction dashboard
- Binance Spot Testnet API credentials

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

## Configure Spot Testnet

Create API credentials at the Binance Spot Test Network. Testnet credentials
are different from production Binance credentials. Never put either kind of
secret directly in `app.py`.

Set the credentials in the PowerShell session used to run the bot:

```powershell
$env:BINANCE_API_KEY = "your-testnet-api-key"
$env:BINANCE_API_SECRET = "your-testnet-secret"
```

Trading is disabled by default. The default mode downloads data and prints
signals without submitting orders. To explicitly enable testnet orders:

```powershell
$env:ENABLE_TRADING = "true"
```

Each buy spends 25 testnet USDT by default. To choose another amount:

```powershell
$env:TRADE_AMOUNT_USDT = "50"
```

These environment variables last for the current PowerShell session. Avoid
storing secrets in scripts or committing them to source control.

Other settings near the top of `app.py` control:

- Trading symbol (`BTCUSDT` by default)
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

The program prints a report immediately and refreshes it every 60 seconds.
Press `Ctrl+C` to stop it.

The stop loss and take profit are evaluated by this running Python process;
they are not protective orders stored at Binance. If the program or computer
stops, those exits cannot execute. Use the Testnet to validate behavior before
considering any production-trading design.

## Transaction dashboard

Keep the bot running in its PowerShell window. Open a second PowerShell window
in the project directory and start the dashboard:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

The browser dashboard refreshes every five seconds and displays:

- The currently tracked position and its stop-loss/take-profit levels
- Filled testnet buy and sell orders
- Estimated realized profit or loss before commissions
- A CSV download of the transaction history

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
