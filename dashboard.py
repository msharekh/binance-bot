import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_DIR = Path(__file__).parent
STATE_FILE = PROJECT_DIR / "trade_state.json"
TRANSACTION_FILE = PROJECT_DIR / "transactions.jsonl"
STATUS_FILE = PROJECT_DIR / "bot_status.json"

st.set_page_config(page_title="Binance Bot Dashboard", page_icon="📈", layout="wide")
st.title("Binance Multi-Market Bot Dashboard")
st.caption("Binance Spot · refreshes every 5 seconds")


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


def render_position_progress(symbol, position, current_price):
    stop_loss = float(position["stop_loss"])
    entry = float(position["entry"])
    take_profit = float(position["take_profit"])
    current = float(current_price) if current_price is not None else entry
    span = take_profit - stop_loss
    progress = (current - stop_loss) / span if span > 0 else 0.5
    progress = max(0.0, min(1.0, progress))
    entry_progress = (entry - stop_loss) / span if span > 0 else 0.5

    st.markdown(f"**{symbol}**")
    st.progress(
        progress,
        text=f"SL {stop_loss:.8f}  ←  Entry {entry:.8f}  →  TP {take_profit:.8f}",
    )
    current_column, entry_column, distance_column = st.columns(3)
    current_column.metric("Current price", f"{current:.8f}")
    entry_column.metric("Entry marker", f"{entry_progress * 100:.1f}% of range")
    if current >= entry:
        distance = ((take_profit - current) / current) * 100
        distance_column.metric("Distance to TP", f"{max(distance, 0):.2f}%")
    else:
        distance = ((current - stop_loss) / current) * 100
        distance_column.metric("Distance to SL", f"{max(distance, 0):.2f}%")


def render_results_by_symbol(history):
    sells = history[history["Side"] == "SELL"].copy()
    if sells.empty:
        st.info("No completed trades are available for symbol results yet.")
        return
    sells["Win"] = sells["Est. P&L (USDT)"].fillna(0) > 0
    results = (
        sells.groupby("Symbol", dropna=False)
        .agg(
            Completed_trades=("Side", "size"),
            Wins=("Win", "sum"),
            Estimated_PnL_USDT=("Est. P&L (USDT)", "sum"),
            Average_PnL_USDT=("Est. P&L (USDT)", "mean"),
        )
        .reset_index()
    )
    results["Win rate"] = results["Wins"] / results["Completed_trades"] * 100
    results = results.rename(
        columns={
            "Completed_trades": "Completed trades",
            "Estimated_PnL_USDT": "Estimated P&L (USDT)",
            "Average_PnL_USDT": "Average P&L (USDT)",
        }
    )
    st.dataframe(results, hide_index=True, use_container_width=True)


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


@st.fragment(run_every=5)
def render_dashboard():
    state = read_state()
    status = read_json(
        STATUS_FILE,
        {"environment": state["environment"], "available_usdt": None, "markets": {}},
    )
    positions = state["positions"]
    history = transaction_frame(read_transactions())
    exposure = sum(
        float(position["quantity"]) * float(position["entry"])
        for position in positions.values()
    )
    realized_pnl = (
        history.loc[history["Side"] == "SELL", "Est. P&L (USDT)"].sum()
        if not history.empty
        else 0
    )

    environment, available, open_count, exposure_metric, pnl = st.columns(5)
    environment.metric("Environment", status["environment"].upper())
    available_value = status.get("available_usdt")
    available.metric(
        "Available USDT",
        f"{float(available_value):,.2f}" if available_value is not None else "Unavailable",
    )
    open_count.metric("Open positions", len(positions))
    exposure_metric.metric("Entry exposure", f"{exposure:,.2f} USDT")
    pnl.metric("Estimated realized P&L", f"{realized_pnl:,.2f} USDT")

    st.subheader("Position exit progress")
    if positions:
        for symbol, position in positions.items():
            market = status.get("markets", {}).get(symbol, {})
            render_position_progress(symbol, position, market.get("price"))
    else:
        st.info("No positions are currently tracked.")

    st.subheader("Results by symbol")
    if history.empty:
        st.info("No completed transaction history is available.")
    else:
        render_results_by_symbol(history)

    st.subheader("Transaction history")
    if history.empty:
        st.info("No filled transactions have been recorded yet.")
        return
    filtered = filter_history(history).sort_values("Time", ascending=False)
    display_columns = [
        "Time", "Environment", "Side", "Symbol", "Quantity", "Price", "Value",
        "Quote asset", "Est. P&L (USDT)", "Reason", "Order ID",
    ]
    for column in display_columns:
        if column not in filtered:
            filtered[column] = None
    st.dataframe(filtered[display_columns], hide_index=True, use_container_width=True)
    st.download_button(
        "Download filtered transaction CSV",
        filtered[display_columns].to_csv(index=False),
        file_name="binance_filtered_transactions.csv",
        mime="text/csv",
    )


render_dashboard()
