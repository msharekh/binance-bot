import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_DIR = Path(__file__).parent
STATE_FILE = PROJECT_DIR / "trade_state.json"
TRANSACTION_FILE = PROJECT_DIR / "transactions.jsonl"

st.set_page_config(page_title="Binance Bot Dashboard", page_icon="📈", layout="wide")
st.title("Binance Bot Dashboard")
st.caption("Binance Spot Testnet · refreshes every 5 seconds")


def read_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


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


@st.fragment(run_every=5)
def render_dashboard():
    position = read_json(STATE_FILE)
    transactions = read_transactions()
    buys = sum(item.get("side") == "BUY" for item in transactions)
    sells = sum(item.get("side") == "SELL" for item in transactions)
    realized_pnl = sum(
        float(item.get("estimated_pnl_usdt", 0))
        for item in transactions
        if item.get("side") == "SELL"
    )

    status, buy_count, sell_count, pnl = st.columns(4)
    status.metric("Position", "OPEN" if position else "NONE")
    buy_count.metric("Buys", buys)
    sell_count.metric("Sells", sells)
    pnl.metric("Estimated realized P&L", f"{realized_pnl:,.2f} USDT")

    st.subheader("Open position")
    if position:
        opened_at = datetime.fromtimestamp(position["opened_at"]).astimezone()
        position_table = pd.DataFrame(
            [
                {
                    "Opened": opened_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "Quantity": float(position["quantity"]),
                    "Entry": float(position["entry"]),
                    "Stop loss": float(position["stop_loss"]),
                    "Take profit": float(position["take_profit"]),
                    "Order ID": position["order_id"],
                }
            ]
        )
        st.dataframe(position_table, hide_index=True, use_container_width=True)
    else:
        st.info("No position is currently tracked.")

    st.subheader("Transaction history")
    if not transactions:
        st.info("No filled testnet transactions have been recorded yet.")
        return

    history = pd.DataFrame(transactions)
    history["Time"] = pd.to_datetime(history["recorded_at"], unit="s", utc=True).dt.tz_convert(
        datetime.now().astimezone().tzinfo
    )
    history = history.rename(
        columns={
            "side": "Side",
            "symbol": "Symbol",
            "order_id": "Order ID",
            "quantity": "Quantity",
            "price": "Price",
            "quote_amount": "Value (USDT)",
            "reason": "Reason",
            "estimated_pnl_usdt": "Est. P&L (USDT)",
        }
    )
    display_columns = [
        "Time", "Side", "Symbol", "Quantity", "Price", "Value (USDT)",
        "Est. P&L (USDT)", "Reason", "Order ID",
    ]
    for column in display_columns:
        if column not in history:
            history[column] = None
    history = history.sort_values("Time", ascending=False)
    st.dataframe(history[display_columns], hide_index=True, use_container_width=True)
    st.download_button(
        "Download transaction CSV",
        history[display_columns].to_csv(index=False),
        file_name="binance_testnet_transactions.csv",
        mime="text/csv",
    )


render_dashboard()
