import json
import html
import os
import re
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st

from advisor import (
    AdvisorError,
    DEFAULT_MODEL,
    DEFAULT_REFRESH_SECONDS,
    ai_advisor_enabled,
    ai_brief_age_seconds,
    generate_ai_brief,
    read_ai_brief,
)


PROJECT_DIR = Path(__file__).parent
STATE_FILE = PROJECT_DIR / "trade_state.json"
TRANSACTION_FILE = PROJECT_DIR / "transactions.jsonl"
STATUS_FILE = PROJECT_DIR / "bot_status.json"
LIVE_PRICE_FILE = PROJECT_DIR / "live_prices.json"
CONFIG_FILE = PROJECT_DIR / "bot_config.json"
SELL_REQUEST_FILE = PROJECT_DIR / "sell_requests.jsonl"
INTERVAL_OPTIONS = [
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
    "12h", "1d", "3d", "1w", "1M",
]

st.set_page_config(page_title="Binance Bot Dashboard", page_icon="📈", layout="wide")
st.title("Binance Multi-Market Bot Dashboard - Version 2")
st.caption("Binance Spot · refreshes every 5 seconds")
st.markdown(
    """
    <style>
    .symbol-title {color:#38bdf8;font-size:1.18rem;font-weight:800;letter-spacing:.03em}
    .target-tag {display:inline-block;padding:.28rem .58rem;margin:.12rem;border-radius:999px;
      background:#172554;color:#bfdbfe;border:1px solid #2563eb;font-weight:700}
    .ai-brief-tag {display:inline-block;max-width:min(65vw,900px);padding:.28rem .58rem;
      margin:.12rem;border-radius:999px;background:#052e16;color:#bbf7d0;
      border:1px solid #16a34a;font-weight:750;white-space:nowrap;overflow:hidden;
      text-overflow:ellipsis;vertical-align:bottom}
    .ai-brief-waiting {background:#422006;color:#fde68a;border-color:#ca8a04}
    .suggestion-card {padding:1rem;border-radius:.7rem;background:#0f172a;
      border:1px solid #334155;min-height:12rem}
    .suggestion-symbol {color:#67e8f9;font-size:1.25rem;font-weight:800}
    .suggestion-stat {color:#e2e8f0;font-weight:650}
    .suggestion-note {color:#cbd5e1;font-size:.92rem;line-height:1.35}
    .result-card {padding:1rem;border-radius:.7rem;background:#0f172a;
      border:1px solid #334155;min-height:10rem;margin-bottom:.7rem}
    .result-symbol {color:#c4b5fd;font-size:1.25rem;font-weight:800}
    .result-stat {color:#e2e8f0;font-weight:650;margin-top:.18rem}
    .result-positive {color:#4ade80;font-size:1.1rem;font-weight:800}
    .result-negative {color:#f87171;font-size:1.1rem;font-weight:800}
    .position-symbol {color:#38bdf8;font-size:1.15rem;font-weight:900;letter-spacing:.03em}
    .position-symbol a {color:#38bdf8;text-decoration:none;border-bottom:1px dashed #38bdf8}
    .position-symbol a:hover {color:#7dd3fc;border-bottom-style:solid}
    .position-quantity {color:#94a3b8;font-size:.78rem}
    .position-pnl {font-size:1.05rem;font-weight:900;text-align:right}
    .position-stats {display:grid;grid-template-columns:repeat(2,1fr);gap:.3rem;
      margin-top:.15rem}
    .position-stat {padding:.3rem .4rem;border-radius:.35rem;background:#0f172a}
    .position-label {color:#94a3b8;font-size:.67rem;text-transform:uppercase;font-weight:700}
    .position-value {color:#e2e8f0;font-size:.83rem;font-weight:750}
    .sticky-summary {position:sticky;top:2.8rem;z-index:999;padding:.72rem;
      margin:.2rem 0 .7rem;border-radius:.75rem;background:rgba(2,6,23,.96);
      border:1px solid #334155;box-shadow:0 8px 24px rgba(0,0,0,.28)}
    .summary-grid {display:grid;grid-template-columns:repeat(9,minmax(100px,1fr));gap:.45rem}
    .summary-item {padding:.42rem .55rem;border-radius:.5rem;background:#0f172a}
    .summary-label {color:#cbd5e1;font-size:.9rem;text-transform:uppercase;font-weight:800}
    .summary-value {color:#f8fafc;font-size:1.5rem;font-weight:900;line-height:1.2}
    .summary-tags {margin-top:.45rem}.pnl-positive{color:#4ade80}.pnl-negative{color:#f87171}
    .hold-banner {padding:.55rem .75rem;margin-bottom:.5rem;border-radius:.5rem;
      background:#7c2d12;color:#ffedd5;border:1px solid #f97316;
      font-size:1.05rem;font-weight:900;text-align:center;letter-spacing:.04em}
    .market-check-row {display:flex;gap:.3rem;overflow-x:auto;padding-bottom:.18rem;
      scrollbar-width:thin}
    .market-check-card {flex:0 0 175px;padding:.34rem .42rem;margin-bottom:.2rem;
      border-radius:.5rem;background:#0f172a;border:1px solid #475569}
    .market-check-buy {border-color:#22c55e;background:linear-gradient(135deg,#052e16,#0f172a)}
    .market-check-sell,.market-check-error {border-color:#ef4444;background:linear-gradient(135deg,#450a0a,#0f172a)}
    .market-check-monitoring {border-color:#38bdf8;background:linear-gradient(135deg,#082f49,#0f172a)}
    .market-check-neutral {border-color:#eab308;background:linear-gradient(135deg,#422006,#0f172a)}
    .market-check-head {display:flex;justify-content:space-between;align-items:center;gap:.4rem}
    .market-check-symbol {color:#f8fafc;font-size:.96rem;font-weight:900;letter-spacing:.03em}
    .market-check-status {padding:.12rem .3rem;border-radius:999px;background:#020617;
      color:#e2e8f0;font-size:.62rem;font-weight:800;white-space:nowrap;
      max-width:56%;overflow:hidden;text-overflow:ellipsis}
    .market-check-signal {margin:.14rem 0;color:#fde68a;font-size:.7rem;font-weight:900}
    .market-check-grid {display:grid;grid-template-columns:repeat(2,1fr);gap:.22rem .65rem}
    .market-check-stat {color:#94a3b8;font-size:.62rem;text-transform:uppercase;font-weight:700}
    .market-check-stat span {display:block;color:#e2e8f0;font-size:.72rem;
      text-transform:none;font-weight:800}
    .market-check-levels {margin-top:.15rem;color:#cbd5e1;font-size:.65rem}
    .market-check-levels summary {cursor:pointer;font-weight:800;color:#94a3b8}
    .market-check-levels .market-check-grid {margin-top:.2rem}
    .live-up {color:#4ade80!important}.live-down {color:#f87171!important}
    .live-flat {color:#cbd5e1!important}
    @keyframes market-cycle-flash {0%{filter:brightness(2);transform:scale(1.015);
      box-shadow:0 0 22px currentColor}100%{filter:brightness(1);transform:scale(1);
      box-shadow:none}}
    .market-check-flash {animation:market-cycle-flash 1.15s ease-out}
    @media(max-width:900px){.summary-grid{grid-template-columns:repeat(2,1fr)}}
    </style>
    """,
    unsafe_allow_html=True,
)


def read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


def read_state():
    state = read_json(STATE_FILE, {"environment": "unknown", "positions": {}})
    if "positions" not in state:
        return {"environment": "legacy", "positions": {}}
    return state


def read_transactions():
    if not TRANSACTION_FILE.exists():
        return []
    transactions = []
    try:
        for line in TRANSACTION_FILE.read_text(encoding="utf-8").splitlines():
            try:
                transactions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return transactions


def write_config(
    symbols, maximum_exposure, trade_amount, max_open_positions,
    trading_on_hold, interval,
):
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    config = {
        "target_symbols": symbols,
        "max_total_exposure_usdt": str(maximum_exposure),
        "trade_amount_usdt": str(trade_amount),
        "max_open_positions": max_open_positions,
        "trading_on_hold": trading_on_hold,
        "interval": interval,
        "updated_at": int(datetime.now().timestamp()),
    }
    temporary_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_file.replace(CONFIG_FILE)


def queue_sell_request(symbol, environment):
    request = {
        "command_id": uuid.uuid4().hex,
        "action": "SELL_MARKET",
        "symbol": symbol,
        "environment": environment,
        "created_at": int(datetime.now().timestamp()),
    }
    with SELL_REQUEST_FILE.open("a", encoding="utf-8") as request_file:
        request_file.write(json.dumps(request) + "\n")


def render_settings_panel():
    status = read_json(STATUS_FILE, {})
    config = read_json(CONFIG_FILE, {})
    symbols = config.get("target_symbols") or status.get("target_symbols") or []
    maximum = config.get("max_total_exposure_usdt") or status.get(
        "max_total_exposure_usdt", "75"
    )
    trade_amount = config.get("trade_amount_usdt") or status.get(
        "trade_amount_usdt", "25"
    )
    max_open_positions = int(
        config.get("max_open_positions")
        or status.get("max_open_positions", 3)
    )
    trading_on_hold = bool(
        config.get("trading_on_hold", status.get("trading_on_hold", False))
    )
    interval = str(config.get("interval") or status.get("interval", "15m"))
    if interval not in INTERVAL_OPTIONS:
        interval = "15m"
    suggested_symbols = [
        str(suggestion.get("symbol", "")).strip().upper()
        for suggestion in status.get("suggestions", [])
        if suggestion.get("symbol")
    ]
    symbol_options = list(dict.fromkeys(list(symbols) + suggested_symbols))
    with st.expander("Trading targets and exposure", expanded=False):
        st.caption(
            f"Per trade: {float(trade_amount):,.2f} USDT | "
            f"Total exposure: {float(maximum):,.2f} USDT | "
            f"Max positions: {max_open_positions} | "
            f"Interval: {interval} | "
            f"Targets: {', '.join(symbols) if symbols else 'not reported yet'}"
        )
        with st.form("runtime_settings"):
            trade_column, exposure_column = st.columns(2)
            with trade_column:
                trade_amount_input = st.number_input(
                    "Per-trade amount (USDT)",
                    min_value=1.0,
                    value=float(trade_amount),
                    step=1.0,
                    help="Maximum USDT requested for one new buy.",
                )
            with exposure_column:
                maximum_input = st.number_input(
                    "Maximum total exposure (USDT)",
                    min_value=1.0,
                    value=float(maximum),
                    step=1.0,
                    help="Combined original entry value allowed across positions.",
                )
            positions_column, interval_column = st.columns(2)
            with positions_column:
                max_open_positions_input = st.number_input(
                    "Maximum open positions",
                    min_value=1,
                    value=max_open_positions,
                    step=1,
                    help="Maximum number of symbols held at the same time.",
                )
            with interval_column:
                interval_input = st.selectbox(
                    "Candle interval",
                    INTERVAL_OPTIONS,
                    index=INTERVAL_OPTIONS.index(interval),
                    help="Timeframe used to calculate indicators and buy signals.",
                )
            symbols_input = st.multiselect(
                "Targeted Spot symbols",
                options=symbol_options,
                default=symbols,
                accept_new_options=True,
                placeholder="Type BTCUSDT, then press Enter",
                help=(
                    "Type a complete USDT pair and press Enter to add it. "
                    "Select × on a tag to remove it."
                ),
            )
            hold_input = st.toggle(
                "Hold new buys",
                value=trading_on_hold,
                help="Existing positions remain monitored and can still be sold.",
            )
            confirmed = st.form_submit_button(
                "Save and confirm settings", type="primary", width="stretch"
            )

        if confirmed:
            parsed_symbols = list(
                dict.fromkeys(
                    symbol.strip().upper()
                    for symbol in symbols_input
                    if symbol.strip()
                )
            )
            invalid = [
                symbol
                for symbol in parsed_symbols
                if not re.fullmatch(r"[A-Z0-9]+USDT", symbol)
            ]
            if not parsed_symbols:
                st.error("Enter at least one targeted USDT symbol.")
            elif invalid:
                st.error("Invalid USDT symbols: " + ", ".join(invalid))
            elif trade_amount_input > maximum_input:
                st.error("Per-trade amount cannot exceed maximum total exposure.")
            else:
                write_config(
                    parsed_symbols, maximum_input, trade_amount_input,
                    max_open_positions_input, hold_input, interval_input,
                )
                st.success(
                    "Settings saved. The bot will load them at the next analysis cycle."
                )


def transaction_frame(transactions):
    if not transactions:
        return pd.DataFrame()
    history = pd.DataFrame(transactions)
    history["Time"] = pd.to_datetime(
        history["recorded_at"], unit="s", utc=True
    ).dt.tz_convert(datetime.now().astimezone().tzinfo)
    history = history.rename(
        columns={
            "side": "Side", "symbol": "Symbol", "order_id": "Order ID",
            "quantity": "Quantity", "price": "Price", "quote_amount": "Value",
            "quote_asset": "Quote asset", "reason": "Reason",
            "environment": "Environment",
            "estimated_pnl_usdt": "Est. P&L (USDT)",
        }
    )
    for column in [
        "Environment", "Side", "Symbol", "Reason", "Est. P&L (USDT)",
        "Quote asset",
    ]:
        if column not in history:
            history[column] = None
    history["Est. P&L (USDT)"] = pd.to_numeric(
        history["Est. P&L (USDT)"], errors="coerce"
    )
    return history


def render_position_progress(
    symbol, position, current_price, trading_enabled, environment
):
    tradingview_url = (
        "https://www.tradingview.com/chart/?symbol="
        + quote(f"BINANCE:{symbol}", safe="")
    )
    stop_loss = float(position["stop_loss"])
    entry = float(position["entry"])
    take_profit = float(position["take_profit"])
    current = float(current_price) if current_price is not None else entry
    span = take_profit - stop_loss
    progress = (current - stop_loss) / span if span > 0 else 0.5
    progress = max(0.0, min(1.0, progress))
    quantity = float(position["quantity"])
    entry_value = quantity * entry
    current_value = quantity * current
    take_profit_value = quantity * take_profit
    stop_loss_value = quantity * stop_loss
    unrealized_pnl = (current - entry) * quantity
    unrealized_pct = ((current - entry) / entry) * 100 if entry else 0
    pnl_style = "pnl-positive" if unrealized_pnl >= 0 else "pnl-negative"
    if current >= entry:
        distance_label = "To TP"
        distance = max(((take_profit - current) / current) * 100, 0)
    else:
        distance_label = "To SL"
        distance = max(((current - stop_loss) / current) * 100, 0)

    symbol_column, profit_column, action_column = st.columns([2, 2, 1])
    with symbol_column:
        st.markdown(
            f'<div class="position-symbol"><a href="{html.escape(tradingview_url)}" '
            f'target="_blank" rel="noopener noreferrer" '
            f'title="Open {html.escape(symbol)} on TradingView">'
            f'{html.escape(symbol)} &#8599;</a></div>'
            f'<div class="position-quantity">Quantity: {quantity:.8f}</div>',
            unsafe_allow_html=True,
        )
    with profit_column:
        st.markdown(
            f'<div class="position-pnl {pnl_style}">{unrealized_pnl:+,.4f} USDT'
            f'<br><small>{unrealized_pct:+.2f}%</small></div>',
            unsafe_allow_html=True,
        )
    with action_column:
        with st.popover("Sell now"):
            st.warning(
                f"This submits a real market sell for the tracked {symbol} position. "
                "The execution price may differ from the displayed price."
            )
            if not trading_enabled:
                st.caption("Trading is disabled, so manual selling is unavailable.")
            confirmed = st.button(
                "Confirm market sell",
                key=f"confirm_sell_{symbol}",
                type="primary",
                disabled=not trading_enabled,
                width="stretch",
            )
            if confirmed:
                queue_sell_request(symbol, environment)
                st.success("Sell request queued. It expires in 30 seconds.")
    st.progress(
        progress,
        text=f"SL {stop_loss:.8f}  ←  Entry {entry:.8f}  →  TP {take_profit:.8f}",
    )
    st.markdown(
        f"""
        <div class="position-stats">
          <div class="position-stat"><div class="position-label">Entry / Spent</div><div class="position-value">Price {entry:.8f}<br>{entry_value:,.4f} USDT</div></div>
          <div class="position-stat"><div class="position-label">Current / Value</div><div class="position-value">Price {current:.8f}<br>{current_value:,.4f} USDT</div></div>
          <div class="position-stat"><div class="position-label">Take Profit / Est. Value</div><div class="position-value">Price {take_profit:.8f}<br>{take_profit_value:,.4f} USDT</div></div>
          <div class="position-stat"><div class="position-label">Stop Loss / Est. Value</div><div class="position-value">Price {stop_loss:.8f}<br>{stop_loss_value:,.4f} USDT</div></div>
        </div>
        <div class="position-quantity">Gross estimates before fees &middot; {distance_label}: {distance:.2f}%</div>
        """,
        unsafe_allow_html=True,
    )


def render_market_suggestions(status):
    suggestions = status.get("suggestions", [])
    with st.expander("Six Spot watchlist candidates", expanded=False):
        st.caption(
            "Read-only screen: positive 24h momentum, at least 30M USDT volume, "
            "then ranked by 24h range. This is not a profit guarantee or a buy signal."
        )
        if not suggestions:
            st.info("Suggestions will appear after the bot refreshes Binance market data.")
            return
        for start in range(0, len(suggestions), 3):
            columns = st.columns(3)
            for column, suggestion in zip(columns, suggestions[start : start + 3]):
                with column:
                    symbol = html.escape(suggestion["symbol"])
                    analysis = html.escape(suggestion["analysis"])
                    st.markdown(
                        f"""
                        <div class="suggestion-card">
                          <div class="suggestion-symbol">{symbol}</div>
                          <div class="suggestion-stat">Price: {suggestion['price']:.8f}</div>
                          <div class="suggestion-stat">24h change: {suggestion['change_pct']:+.2f}%</div>
                          <div class="suggestion-stat">24h range: {suggestion['range_pct']:.2f}%</div>
                          <div class="suggestion-stat">Volume: {suggestion['quote_volume_usdt']/1_000_000:.1f}M USDT</div>
                          <p class="suggestion-note">{analysis}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


def render_results_by_symbol(history):
    with st.expander("Results by symbol", expanded=False):
        if history.empty:
            st.info("No completed trades are available for symbol results yet.")
            return
        sells = history[history["Side"] == "SELL"].copy()
        if sells.empty:
            st.info("No completed trades are available for symbol results yet.")
            return
        sells["Win"] = sells["Est. P&L (USDT)"].fillna(0) > 0
        results = (
            sells.groupby("Symbol", dropna=False)
            .agg(
                completed=("Side", "size"),
                wins=("Win", "sum"),
                total_pnl=("Est. P&L (USDT)", "sum"),
                average_pnl=("Est. P&L (USDT)", "mean"),
            )
            .reset_index()
            .sort_values("total_pnl", ascending=False)
        )
        results["win_rate"] = results["wins"] / results["completed"] * 100
        records = results.to_dict("records")
        for start in range(0, len(records), 3):
            columns = st.columns(3)
            for column, result in zip(columns, records[start : start + 3]):
                total_pnl = float(result["total_pnl"])
                pnl_style = "result-positive" if total_pnl >= 0 else "result-negative"
                with column:
                    st.markdown(
                        f"""
                        <div class="result-card">
                          <div class="result-symbol">{html.escape(str(result['Symbol']))}</div>
                          <div class="{pnl_style}">Total P&amp;L: {total_pnl:+.4f} USDT</div>
                          <div class="result-stat">Completed trades: {int(result['completed'])}</div>
                          <div class="result-stat">Wins: {int(result['wins'])}</div>
                          <div class="result-stat">Win rate: {float(result['win_rate']):.1f}%</div>
                          <div class="result-stat">Average P&amp;L: {float(result['average_pnl']):+.4f} USDT</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


def filter_history(history):
    with st.expander("Transaction filters", expanded=True):
        symbols = sorted(history["Symbol"].dropna().unique().tolist())
        sides = sorted(history["Side"].dropna().unique().tolist())
        reasons = sorted(history["Reason"].dropna().unique().tolist())
        environments = sorted(history["Environment"].dropna().unique().tolist())

        symbol_filter, side_filter, reason_filter, environment_filter = st.columns(4)
        selected_symbols = symbol_filter.multiselect("Symbols", symbols)
        selected_sides = side_filter.multiselect("Side", sides)
        selected_reasons = reason_filter.multiselect("Exit/reason", reasons)
        selected_environments = environment_filter.multiselect(
            "Environment", environments
        )

        minimum_date = history["Time"].dt.date.min()
        maximum_date = history["Time"].dt.date.max()
        selected_dates = st.date_input(
            "Date range", value=(minimum_date, maximum_date),
            min_value=minimum_date, max_value=maximum_date,
        )

    filtered = history.copy()
    if selected_symbols:
        filtered = filtered[filtered["Symbol"].isin(selected_symbols)]
    if selected_sides:
        filtered = filtered[filtered["Side"].isin(selected_sides)]
    if selected_reasons:
        filtered = filtered[filtered["Reason"].isin(selected_reasons)]
    if selected_environments:
        filtered = filtered[filtered["Environment"].isin(selected_environments)]
    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
        filtered = filtered[
            (filtered["Time"].dt.date >= start_date)
            & (filtered["Time"].dt.date <= end_date)
        ]
    elif isinstance(selected_dates, date):
        filtered = filtered[filtered["Time"].dt.date == selected_dates]
    return filtered


def transaction_result(row):
    if str(row.get("Side", "")).upper() != "SELL":
        return "ENTRY"
    pnl = row.get("Est. P&L (USDT)")
    if pd.isna(pnl) or float(pnl) == 0:
        return "BREAK EVEN"
    return "PROFIT" if float(pnl) > 0 else "LOSS"


def style_transaction_row(row):
    result = row.get("Result")
    if result == "PROFIT":
        style = "background-color:rgba(34,197,94,.16);color:#bbf7d0;font-weight:650"
    elif result == "LOSS":
        style = "background-color:rgba(239,68,68,.16);color:#fecaca;font-weight:650"
    elif result == "BREAK EVEN":
        style = "background-color:rgba(148,163,184,.10);color:#e2e8f0"
    else:
        style = ""
    return [style] * len(row)


def format_market_number(value, decimals=8):
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


@st.fragment(run_every=5)
def render_market_check_cards():
    status = read_json(STATUS_FILE, {})
    live_prices = read_json(LIVE_PRICE_FILE, {})
    if live_prices.get("environment") != status.get("environment"):
        live_prices = {}
    live_markets = live_prices.get("prices", {})
    markets = status.get("markets", {})
    target_symbols = status.get("target_symbols", [])
    updated_at = status.get("updated_at")
    visual_updated_at = live_prices.get("updated_at") or updated_at
    previous_update = st.session_state.get("market_cards_updated_at")
    should_flash = (
        visual_updated_at is not None and visual_updated_at != previous_update
    )
    st.session_state["market_cards_updated_at"] = visual_updated_at

    if not target_symbols:
        return

    if updated_at:
        update_age = max(0, int(datetime.now().timestamp() - float(updated_at)))
        checked_at = datetime.fromtimestamp(updated_at).astimezone().strftime("%H:%M:%S")
        if update_age > 150:
            st.error(
                f"BOT STATUS STALE - no completed market check for "
                f"{update_age // 60} minute(s). Confirm that app.py is running."
            )
        trading_mode = (
            "TRADING ACTIVE" if status.get("trading_enabled") else "ANALYSIS ONLY"
        )
        live_updated_at = live_prices.get("updated_at")
        live_label = "waiting"
        if live_updated_at:
            live_label = datetime.fromtimestamp(live_updated_at).astimezone().strftime(
                "%H:%M:%S"
            )
        st.caption(
            f"Latest market check: {checked_at} | "
            f"{str(status.get('environment', 'unknown')).upper()} | "
            f"{trading_mode} | Candle interval: {status.get('interval', 'N/A')} | "
            f"Live price: {live_label}"
        )
    else:
        st.warning("WAITING FOR BOT STATUS - start app.py to receive market checks.")

    cards = []
    for symbol in target_symbols:
        market = markets.get(symbol, {})
        live_market = live_markets.get(symbol, {})
        display_price = live_market.get("price", market.get("price"))
        direction = str(live_market.get("direction", "FLAT"))
        direction_icon = {"UP": "&#9650;", "DOWN": "&#9660;"}.get(
            direction, "&#8226;"
        )
        direction_class = {
            "UP": "live-up", "DOWN": "live-down", "FLAT": "live-flat"
        }.get(direction, "live-flat")
        market_status = str(
            market.get("status")
            or status.get("market_statuses", {}).get(symbol, "CHECK PENDING")
        )
        signal = str(market.get("signal", "CHECK PENDING"))
        if "ERROR" in market_status:
            color_class = "market-check-error"
        elif "BUY" in signal:
            color_class = "market-check-buy"
        elif "SELL" in signal:
            color_class = "market-check-sell"
        elif market_status == "MONITORING":
            color_class = "market-check-monitoring"
        else:
            color_class = "market-check-neutral"
        flash_class = "market-check-flash" if should_flash else ""
        cards.append(
            f'<div class="market-check-card {color_class} {flash_class}">'
            f'<div class="market-check-head">'
            f'<span class="market-check-symbol">{html.escape(symbol)}</span>'
            f'<span class="market-check-status" title="{html.escape(market_status)}">'
            f'{html.escape(market_status)}</span></div>'
            f'<div class="market-check-signal">{html.escape(signal)}</div>'
            f'<div class="market-check-grid">'
            f'<div class="market-check-stat">Price'
            f'<span class="{direction_class}">{direction_icon} '
            f'{format_market_number(display_price)}</span></div>'
            f'<div class="market-check-stat">RSI<span>'
            f'{format_market_number(market.get("rsi"), 2)}</span></div></div>'
            f'<details class="market-check-levels"><summary>Levels</summary>'
            f'<div class="market-check-grid">'
            f'<div class="market-check-stat">ATR<span>'
            f'{format_market_number(market.get("atr"))}</span></div>'
            f'<div class="market-check-stat">Support<span>'
            f'{format_market_number(market.get("support"))}</span></div>'
            f'<div class="market-check-stat">Resistance<span>'
            f'{format_market_number(market.get("resistance"))}</span></div>'
            f'<div class="market-check-stat">Suggested SL<span>'
            f'{format_market_number(market.get("suggested_sl"))}</span></div>'
            f'<div class="market-check-stat">Suggested TP<span>'
            f'{format_market_number(market.get("suggested_tp"))}</span></div>'
            f'</div></details></div>'
        )
    st.markdown(
        f'<div class="market-check-row">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every=60)
def render_ai_advisor():
    if not ai_advisor_enabled():
        st.info("AI advisor paused — no OpenAI API requests will be made.")
        return

    configured = bool(os.getenv("OPENAI_API_KEY", "").strip())
    brief = read_ai_brief()
    age = ai_brief_age_seconds(brief)
    now = time.time()
    last_attempt = st.session_state.get("ai_advisor_last_attempt", 0.0)
    auto_due = (
        configured
        and (not brief or age is None or age >= DEFAULT_REFRESH_SECONDS)
        and now - last_attempt >= 300
    )
    refresh_requested = st.button(
        "Refresh AI brief",
        type="primary",
        width="stretch",
        disabled=not configured,
        key="refresh_ai_brief",
    )

    if refresh_requested or auto_due:
        st.session_state["ai_advisor_last_attempt"] = now
        try:
            with st.spinner("Reviewing sanitized trading metrics..."):
                brief = generate_ai_brief(force=refresh_requested)
            st.session_state.pop("ai_advisor_error", None)
            age = ai_brief_age_seconds(brief)
        except AdvisorError as error:
            st.session_state["ai_advisor_error"] = str(error)

    if not configured:
        st.warning("Set OPENAI_API_KEY and restart the dashboard to enable AI.")
    if st.session_state.get("ai_advisor_error"):
        st.error(st.session_state["ai_advisor_error"])

    if not brief:
        st.caption(
            f"No AI brief yet. Default model: {os.getenv('OPENAI_MODEL', DEFAULT_MODEL)}"
        )
        return

    generated_at = datetime.fromtimestamp(brief["generated_at"]).astimezone()
    age_text = f"{age // 60} min old" if age is not None else "age unknown"
    st.caption(
        f"{brief.get('model', 'unknown model')} | "
        f"{generated_at.strftime('%Y-%m-%d %H:%M:%S')} | {age_text} | read-only"
    )
    with st.expander("Full AI analysis", expanded=False):
        st.markdown(f"**{brief.get('headline', 'AI performance review')}**")
        st.markdown("**Progress**")
        st.write(brief.get("progress", "Not available."))
        st.markdown("**Result**")
        st.write(brief.get("result", "Not available."))
        st.markdown("**What is right**")
        for item in brief.get("what_is_right", []):
            st.write(f"- {item}")
        st.markdown("**What is wrong**")
        for item in brief.get("what_is_wrong", []):
            st.write(f"- {item}")
        st.markdown("**Recommendations**")
        recommendations = brief.get("recommendations", [])
        if not recommendations:
            st.write("No setting or code change is supported by the current sample.")
        for recommendation in recommendations:
            st.markdown(
                f"**{str(recommendation.get('priority', 'low')).upper()} | "
                f"{recommendation.get('area', 'Review')}**"
            )
            st.write(recommendation.get("suggestion", ""))
            st.caption(
                f"Current: {recommendation.get('current_value', 'N/A')} | "
                f"Proposed: {recommendation.get('proposed_value', 'N/A')} | "
                f"Type: {recommendation.get('change_type', 'none')}"
            )
            st.caption(f"Why: {recommendation.get('reason', 'Not provided.')}")
        st.markdown(f"**Confidence:** {brief.get('confidence', 'low').upper()}")
        st.warning(brief.get("risk_note", "AI analysis is not a profit guarantee."))


@st.fragment(run_every=5)
def render_top_bar():
    state = read_state()
    status = read_json(STATUS_FILE, {})
    config = read_json(CONFIG_FILE, {})
    live_prices = read_json(LIVE_PRICE_FILE, {})
    if live_prices.get("environment") != status.get("environment"):
        live_prices = {}
    live_markets = live_prices.get("prices", {})
    history = transaction_frame(read_transactions())
    positions = state.get("positions", {})
    available = status.get("available_usdt")
    maximum = config.get("max_total_exposure_usdt") or status.get(
        "max_total_exposure_usdt", "75"
    )
    trade_amount = config.get("trade_amount_usdt") or status.get(
        "trade_amount_usdt"
    )
    max_open_positions = int(
        config.get("max_open_positions")
        or status.get("max_open_positions", 3)
    )
    trading_on_hold = bool(
        config.get("trading_on_hold", status.get("trading_on_hold", False))
    )
    total_pnl = 0.0
    today_pnl = 0.0
    today_unrealized_pnl = 0.0
    usdt_in_trades = 0.0
    if not history.empty:
        sells = history[history["Side"] == "SELL"]
        total_pnl = float(sells["Est. P&L (USDT)"].sum())
        today_pnl = float(
            sells.loc[
                sells["Time"].dt.date == datetime.now().astimezone().date(),
                "Est. P&L (USDT)",
            ].sum()
        )
    status_markets = status.get("markets", {})
    for symbol, position in positions.items():
        try:
            entry = float(position["entry"])
            quantity = float(position["quantity"])
            current = float(
                live_markets.get(symbol, {}).get(
                    "price", status_markets.get(symbol, {}).get("price", entry)
                )
            )
            usdt_in_trades += current * quantity
            today_unrealized_pnl += (current - entry) * quantity
        except (KeyError, TypeError, ValueError):
            continue
    active_interval = str(status.get("interval") or config.get("interval", "15m"))
    advisor_enabled = ai_advisor_enabled()
    ai_brief = read_ai_brief() if advisor_enabled else {}
    if ai_brief.get("environment") not in (None, status.get("environment")):
        ai_brief = {}
    ai_headline = str(
        ai_brief.get(
            "headline",
            "WAITING FOR FIRST BRIEF" if advisor_enabled else "PAUSED",
        )
    )
    ai_style = "" if ai_brief else " ai-brief-waiting"
    tags = (
        f'<span class="target-tag">INTERVAL &middot; '
        f'{html.escape(active_interval)}</span>'
        f'<span class="ai-brief-tag{ai_style}" '
        f'title="Open AI Advisor in the sidebar">AI &middot; '
        f'{html.escape(ai_headline)}</span>'
    )
    today_class = "pnl-positive" if today_pnl >= 0 else "pnl-negative"
    today_unrealized_class = (
        "pnl-positive" if today_unrealized_pnl >= 0 else "pnl-negative"
    )
    total_class = "pnl-positive" if total_pnl >= 0 else "pnl-negative"
    available_text = f"{float(available):,.2f}" if available is not None else "N/A"
    total_portfolio_text = (
        f"{float(available) + usdt_in_trades:,.2f}"
        if available is not None
        else "N/A"
    )
    trade_amount_text = (
        f"{float(trade_amount):,.2f}" if trade_amount is not None else "N/A"
    )
    hold_banner = (
        '<div class="hold-banner">TRADING ON HOLD &mdash; NEW BUYS PAUSED; '
        'EXISTING POSITIONS STILL MONITORED</div>'
        if trading_on_hold
        else ""
    )
    st.markdown(
        f"""
        <div class="sticky-summary">
          {hold_banner}
          <div class="summary-grid">
            <div class="summary-item"><div class="summary-label">Available USDT</div><div class="summary-value">{available_text}</div></div>
            <div class="summary-item" title="Current market price multiplied by tracked quantity for all open positions"><div class="summary-label">USDT in trades</div><div class="summary-value">{usdt_in_trades:,.2f}</div></div>
            <div class="summary-item" title="Available USDT plus the current market value of all tracked open positions"><div class="summary-label">Total portfolio USDT</div><div class="summary-value">{total_portfolio_text}</div></div>
            <div class="summary-item"><div class="summary-label">Open / max positions</div><div class="summary-value">{len(positions)} / {max_open_positions}</div></div>
            <div class="summary-item"><div class="summary-label">Per-trade max</div><div class="summary-value">{trade_amount_text}</div></div>
            <div class="summary-item"><div class="summary-label">Max total exposure</div><div class="summary-value">{float(maximum):,.2f}</div></div>
            <div class="summary-item"><div class="summary-label">Today realized P&amp;L</div><div class="summary-value {today_class}">{today_pnl:+,.4f}</div></div>
            <div class="summary-item" title="Current mark-to-entry P&amp;L for all open positions"><div class="summary-label">Today unrealized P&amp;L</div><div class="summary-value {today_unrealized_class}">{today_unrealized_pnl:+,.4f}</div></div>
            <div class="summary-item"><div class="summary-label">Total realized P&amp;L</div><div class="summary-value {total_class}">{total_pnl:+,.4f}</div></div>
          </div>
          <div class="summary-tags">{tags}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every=5)
def render_dashboard():
    state = read_state()
    status = read_json(
        STATUS_FILE,
        {
            "environment": state["environment"], "available_usdt": None,
            "markets": {}, "target_symbols": [], "market_statuses": {},
            "trading_enabled": False,
        },
    )
    positions = state["positions"]
    live_prices = read_json(LIVE_PRICE_FILE, {})
    if live_prices.get("environment") != status.get("environment"):
        live_prices = {}
    live_markets = live_prices.get("prices", {})
    history = transaction_frame(read_transactions())

    st.subheader("Position exit progress")
    if positions:
        position_items = list(positions.items())
        for start in range(0, len(position_items), 2):
            columns = st.columns(2, gap="small")
            for column, (symbol, position) in zip(
                columns, position_items[start : start + 2]
            ):
                with column:
                    with st.container(border=True):
                        market = status.get("markets", {}).get(symbol, {})
                        live_market = live_markets.get(symbol, {})
                        render_position_progress(
                            symbol, position,
                            live_market.get("price", market.get("price")),
                            bool(status.get("trading_enabled", False)),
                            status.get("environment", state["environment"]),
                        )
    else:
        st.info("No positions are currently tracked.")

    render_results_by_symbol(history)
    render_market_suggestions(status)

    st.subheader("Transaction history")
    if history.empty:
        st.info("No filled transactions have been recorded yet.")
        return
    filtered = filter_history(history).sort_values("Time", ascending=False)
    display_columns = [
        "Time", "Environment", "Side", "Result", "Symbol", "Quantity", "Price",
        "Value", "Quote asset", "Est. P&L (USDT)", "Reason", "Order ID",
    ]
    filtered = filtered.copy()
    filtered["Result"] = filtered.apply(transaction_result, axis=1)
    for column in display_columns:
        if column not in filtered:
            filtered[column] = None
    display_frame = filtered[display_columns]
    styled_frame = display_frame.style.apply(style_transaction_row, axis=1).format(
        {"Est. P&L (USDT)": lambda value: f"{value:+,.4f}"},
        na_rep="—",
    )
    st.dataframe(styled_frame, hide_index=True, width="stretch")
    st.download_button(
        "Download filtered transaction CSV",
        display_frame.to_csv(index=False),
        file_name="binance_filtered_transactions.csv",
        mime="text/csv",
    )


render_top_bar()
render_market_check_cards()
render_dashboard()
with st.sidebar:
    st.header("Version 2 AI")
    render_ai_advisor()
    st.header("Bot controls")
    render_settings_panel()
