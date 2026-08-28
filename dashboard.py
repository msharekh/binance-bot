import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_DIR = Path(__file__).parent
STATE_FILE = PROJECT_DIR / "trade_state.json"
TRANSACTION_FILE = PROJECT_DIR / "transactions.jsonl"

st.set_page_config(page_title="Binance Bot Dashboard", page_icon="📈", layout="wide")
st.title("Binance Multi-Market Bot Dashboard")
st.caption("Binance Spot · refreshes every 5 seconds")


def read_state():
    if not STATE_FILE.exists():
        return {"environment": "unknown", "positions": {}}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if "positions" not in state:
            return {"environment": "legacy", "positions": {}}
        return state
    except (json.JSONDecodeError, OSError):
        return {"environment": "unavailable", "positions": {}}


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


def position_rows(positions):
    rows = []
    for symbol, position in positions.items():
        opened_at = datetime.fromtimestamp(position["opened_at"]).astimezone()
        rows.append(
            {
                "Symbol": symbol,
                "Opened": opened_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "Quantity": float(position["quantity"]),
                "Entry": float(position["entry"]),
                "Stop loss": float(position["stop_loss"]),
                "Take profit": float(position["take_profit"]),
                "Entry value (USDT)": float(position["quantity"])
                * float(position["entry"]),
                "Order ID": position["order_id"],
            }
        )
    return rows


@st.fragment(run_every=5)
def render_dashboard():
    state = read_state()
    positions = state["positions"]
    transactions = read_transactions()
    buys = sum(item.get("side") == "BUY" for item in transactions)
    sells = sum(item.get("side") == "SELL" for item in transactions)
    realized_pnl = sum(
        float(item.get("estimated_pnl_usdt", 0) or 0)
        for item in transactions
        if item.get("side") == "SELL"
    )
    exposure = sum(
        float(position["quantity"]) * float(position["entry"])
        for position in positions.values()
    )

    environment, open_count, exposure_metric, pnl = st.columns(4)
    environment.metric("Environment", state["environment"].upper())
    open_count.metric("Open positions", len(positions))
    exposure_metric.metric("Entry exposure", f"{exposure:,.2f} USDT")
    pnl.metric("Estimated realized P&L", f"{realized_pnl:,.2f} USDT")

    st.subheader("Open positions")
    rows = position_rows(positions)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("No positions are currently tracked.")

    st.subheader("Transaction history")
    if not transactions:
        st.info("No filled transactions have been recorded yet.")
        return

    history = pd.DataFrame(transactions)
    history["Time"] = pd.to_datetime(
        history["recorded_at"], unit="s", utc=True
    ).dt.tz_convert(datetime.now().astimezone().tzinfo)
    history = history.rename(
        columns={
            "side": "Side", "symbol": "Symbol", "order_id": "Order ID",
            "quantity": "Quantity", "price": "Price",
            "quote_amount": "Value", "quote_asset": "Quote asset",
            "reason": "Reason", "environment": "Environment",
            "estimated_pnl_usdt": "Est. P&L (USDT)",
        }
    )
    display_columns = [
        "Time", "Environment", "Side", "Symbol", "Quantity", "Price",
        "Value", "Quote asset", "Est. P&L (USDT)", "Reason", "Order ID",
    ]
    for column in display_columns:
        if column not in history:
            history[column] = None
    history = history.sort_values("Time", ascending=False)
    st.dataframe(history[display_columns], hide_index=True, use_container_width=True)
    st.download_button(
        "Download transaction CSV",
        history[display_columns].to_csv(index=False),
        file_name="binance_transactions.csv",
        mime="text/csv",
    )
    st.caption(f"Recorded orders: {buys} buys · {sells} sells")


render_dashboard()
