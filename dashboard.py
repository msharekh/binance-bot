import json
import html
import os
import re
import time
import uuid
from bisect import bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
BUY_REQUEST_FILE = PROJECT_DIR / "buy_requests.jsonl"
MARKET_OVERVIEW_HISTORY_FILE = PROJECT_DIR / "market_overview_history.jsonl"
INTERVAL_OPTIONS = [
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
    "12h", "1d", "3d", "1w", "1M",
]
INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
    "12h": 720, "1d": 1440, "3d": 4320, "1w": 10080, "1M": 43200,
}

st.set_page_config(page_title="Binance Bot Dashboard", page_icon="📈", layout="wide")
st.markdown(
    '<h1 class="dashboard-title">Binance Market Bot Dashboard</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="dashboard-subtitle">Binance Spot · refreshes every 5 seconds</div>',
    unsafe_allow_html=True,
)
st.markdown(
    """
    <style>
    .dashboard-title {font-size:1.65rem!important;line-height:1.15!important;
      margin:.1rem 0 .05rem!important;padding:0!important}
    .dashboard-subtitle {color:#94a3b8;font-size:.88rem;margin-bottom:.45rem}
    .max-status-strip {position:fixed;top:.3rem;right:3.4rem;z-index:1002;
      display:flex;align-items:center;gap:.55rem;margin:0;padding:.25rem .45rem;
      border:1px solid #475569;border-radius:.35rem;background:#020617;
      box-shadow:0 2px 9px rgba(0,0,0,.55)}
    .max-status-item {color:#cbd5e1;font-size:.7rem;font-weight:800;
      letter-spacing:.01em;white-space:nowrap}
    .max-status-item strong {margin-left:.18rem;color:#f8fafc;font-size:.86rem;
      font-weight:950;text-shadow:0 0 8px currentColor}
    .max-status-win strong {color:#38bdf8}
    .max-status-market {padding:.22rem .45rem;border-radius:.32rem;color:#bfdbfe;
      background:#172554;border:1px solid #2563eb;font-size:.88rem;font-weight:950;
      white-space:nowrap}
    .max-status-market-weak {color:#fecaca;background:#450a0a;border-color:#ef4444}
    .max-status-market-positive {color:#bbf7d0;background:#052e16;border-color:#16a34a}
    .max-status-market-quiet {color:#fde68a;background:#422006;border-color:#ca8a04}
    .max-status-online {margin-left:auto;color:#4ade80;font-size:.72rem;
      font-weight:950;letter-spacing:.04em;white-space:nowrap;
      text-shadow:0 0 12px rgba(34,197,94,1)}
    .max-status-offline {margin-left:auto;color:#f87171;font-size:.72rem;
      font-weight:950;letter-spacing:.04em;white-space:nowrap;
      text-shadow:0 0 12px rgba(248,113,113,.8)}
    .symbol-title {color:#38bdf8;font-size:1.18rem;font-weight:800;letter-spacing:.03em}
    .target-tag {display:inline-block;padding:.28rem .58rem;margin:.12rem;border-radius:999px;
      background:#172554;color:#bfdbfe;border:1px solid #2563eb;font-weight:700}
    .market-regime-tag {display:inline-block;padding:.28rem .58rem;margin:.12rem;
      border-radius:999px;font-weight:800;background:#172554;color:#bfdbfe;
      border:1px solid #2563eb}
    .market-regime-positive {background:#052e16;color:#bbf7d0;border-color:#16a34a}
    .market-regime-weak {background:#450a0a;color:#fecaca;border-color:#ef4444}
    .market-regime-quiet {background:#422006;color:#fde68a;border-color:#ca8a04}
    .bot-health-online {background:#052e16;color:#bbf7d0;border-color:#16a34a}
    .bot-health-delayed {background:#422006;color:#fde68a;border-color:#ca8a04}
    .bot-health-offline {background:#450a0a;color:#fecaca;border-color:#ef4444}
    .ai-brief-tag {display:inline-block;max-width:min(65vw,900px);padding:.28rem .58rem;
      margin:.12rem;border-radius:999px;background:#052e16;color:#bbf7d0;
      border:1px solid #16a34a;font-weight:750;white-space:nowrap;overflow:hidden;
      text-overflow:ellipsis;vertical-align:bottom}
    .ai-brief-waiting {background:#422006;color:#fde68a;border-color:#ca8a04}
    .suggestion-card {padding:1rem;border-radius:.7rem;background:#0f172a;
      border:1px solid #334155;min-height:12rem}
    .suggestion-symbol {color:#67e8f9;font-size:1.25rem;font-weight:800}
    .suggestion-target-tag {display:inline-block;margin-left:.4rem;padding:.1rem .35rem;
      border-radius:999px;background:#052e16;color:#bbf7d0;border:1px solid #16a34a;
      font-size:.65rem;font-weight:900;vertical-align:middle}
    .target-review-card {padding:.75rem;border-radius:.65rem;background:#1c1917;
      border:1px solid #f59e0b;min-height:9.5rem;margin-bottom:.35rem}
    .target-review-symbol {color:#fde68a;font-size:1.05rem;font-weight:900}
    .target-review-reason {color:#d6d3d1;font-size:.8rem;line-height:1.35;
      margin:.2rem 0}
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
    .position-spent {display:inline-block;margin-left:.4rem;padding:.08rem .3rem;
      border-radius:.25rem;background:#1e293b;color:#e2e8f0;font-size:.68rem;
      font-weight:800;vertical-align:middle;white-space:nowrap}
    .position-stats {display:grid;grid-template-columns:repeat(2,1fr);gap:.3rem;
      margin-top:.15rem}
    .position-stat {padding:.3rem .4rem;border-radius:.35rem;background:#0f172a}
    .position-label {color:#94a3b8;font-size:.67rem;text-transform:uppercase;font-weight:700}
    .position-value {color:#e2e8f0;font-size:.83rem;font-weight:750}
    .position-progress-wrap {margin:1.85rem 0 .2rem}
    .position-progress-wrap-max {margin:.28rem 0 .2rem}
    .position-progress-wrap-max .position-current-label {top:.43rem}
    .position-progress-track {position:relative;height:2.3rem;border-radius:.3rem;
      border:1px solid #64748b;box-shadow:inset 0 1px 3px rgba(0,0,0,.45)}
    .position-progress-marker {position:absolute;top:-.28rem;width:.35rem;height:2.85rem;
      border-radius:999px;background:#f8fafc;border:1px solid #020617;
      box-shadow:0 0 7px rgba(255,255,255,.9);transform:translateX(-50%)}
    .position-current-label {position:absolute;top:-1.65rem;transform:translateX(-50%);
      padding:.15rem .38rem;border-radius:.25rem;color:#fff;border:1px solid #f8fafc;
      box-shadow:0 2px 6px rgba(0,0,0,.55);font-size:.7rem;font-weight:900;
      white-space:nowrap;z-index:2}
    .position-entry-marker {position:absolute;top:0;width:2px;height:100%;
      background:rgba(255,255,255,.55);transform:translateX(-50%)}
    .position-progress-unfilled {position:absolute;top:0;right:0;height:100%;
      background:#020617;border-radius:0 .25rem .25rem 0}
    .position-progress-labels {display:flex;justify-content:space-between;gap:.5rem;
      margin-top:.18rem;color:#cbd5e1;font-size:.68rem;font-weight:750}
    .position-progress-state {text-align:center;color:#e2e8f0;font-size:.72rem;
      font-weight:850;margin-top:.08rem}
    .position-candle-wrap {width:100%;margin:.18rem 0 .1rem}
    .position-candle-title {display:flex;justify-content:space-between;gap:.5rem;
      color:#94a3b8;font-size:.66rem;font-weight:700;margin-bottom:.14rem}
    .position-candle-chart {display:block;width:100%;height:auto;background:#0b1220;
      border:1px solid #1e293b;border-radius:.12rem}
    .position-candle-empty {padding:.55rem;color:#94a3b8;background:#020617;
      border:1px solid #334155;border-radius:.2rem;font-size:.72rem}
    .sticky-summary {position:sticky;top:2.8rem;z-index:999;padding:.72rem;
      margin:.2rem 0 .7rem;border-radius:.75rem;background:rgba(2,6,23,.96);
      border:1px solid #334155;box-shadow:0 8px 24px rgba(0,0,0,.28)}
    .summary-grid {display:grid;grid-template-columns:repeat(7,minmax(105px,1fr));gap:.45rem}
    .secondary-summary-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
      gap:.45rem}
    .summary-item {padding:.42rem .55rem;border-radius:.5rem;background:#0f172a}
    .summary-label {color:#cbd5e1;font-size:.9rem;text-transform:uppercase;font-weight:800}
    .summary-value {color:#f8fafc;font-size:1.5rem;font-weight:900;line-height:1.2}
    .bot-health-card-online {background:#052e16;border:2px solid #22c55e;
      box-shadow:0 0 12px rgba(34,197,94,.8),inset 0 0 14px rgba(34,197,94,.18);
      animation:bot-health-glow 1.8s ease-in-out infinite}
    .bot-health-card-online .summary-label {color:#86efac}
    .bot-health-card-online .summary-value {color:#4ade80;text-shadow:0 0 10px #22c55e}
    .bot-health-card-delayed {background:#422006;border:1px solid #ca8a04}
    .bot-health-card-delayed .summary-label,.bot-health-card-delayed .summary-value {color:#fde68a}
    .bot-health-card-offline {background:#020617;border:1px solid #1e293b;box-shadow:none}
    .bot-health-card-offline .summary-label {color:#475569}
    .bot-health-card-offline .summary-value {color:#64748b;text-shadow:none}
    .bot-health-last {margin-top:.14rem;color:#94a3b8;font-size:.68rem;
      font-weight:750;line-height:1.15;white-space:nowrap}
    @keyframes bot-health-glow {0%,100%{box-shadow:0 0 9px rgba(34,197,94,.55),
      inset 0 0 12px rgba(34,197,94,.12)}50%{box-shadow:0 0 20px rgba(34,197,94,.95),
      inset 0 0 18px rgba(34,197,94,.24)}}
    @media(prefers-reduced-motion:reduce){.bot-health-card-online{animation:none}}
    .summary-tags {margin-top:.45rem}.pnl-positive{color:#4ade80}.pnl-negative{color:#f87171}
    .hold-banner {padding:.55rem .75rem;margin-bottom:.5rem;border-radius:.5rem;
      background:#7c2d12;color:#ffedd5;border:1px solid #f97316;
      font-size:1.05rem;font-weight:900;text-align:center;letter-spacing:.04em}
    .market-check-row {display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));
      gap:.35rem;padding-bottom:.18rem}
    .market-check-card {padding:.34rem .42rem;margin-bottom:.2rem;
      border-radius:.5rem;background:#0f172a;border:1px solid #475569}
    .market-check-buy {border-color:#22c55e;background:linear-gradient(135deg,#052e16,#0f172a)}
    .market-check-sell,.market-check-error {border-color:#ef4444;background:linear-gradient(135deg,#450a0a,#0f172a)}
    .market-check-monitoring {border-color:#38bdf8;background:linear-gradient(135deg,#082f49,#0f172a)}
    .market-check-neutral {border-color:#eab308;background:linear-gradient(135deg,#422006,#0f172a)}
    .market-check-head {display:flex;justify-content:space-between;align-items:center;gap:.4rem}
    .market-check-symbol {color:#f8fafc;font-size:.96rem;font-weight:900;letter-spacing:.03em}
    .market-check-symbol a {color:#f8fafc;text-decoration:none;
      border-bottom:1px dashed #94a3b8}
    .market-check-symbol a:hover {color:#7dd3fc;border-bottom-color:#38bdf8;
      border-bottom-style:solid}
    .market-rank-tag {display:inline-block;margin-left:.3rem;padding:.05rem .3rem;
      border-radius:999px;background:#1e293b;color:#f8fafc;border:1px solid #64748b;
      font-size:.62rem;font-weight:900;vertical-align:middle}
    .market-win-tag {display:inline-block;margin:.05rem 0 .16rem;padding:.08rem .32rem;
      border-radius:.3rem;background:#172554;color:#bfdbfe;border:1px solid #2563eb;
      font-size:.62rem;font-weight:850}
    .market-buy-link {display:inline-block;margin-left:.25rem;padding:.04rem .28rem;
      border-radius:.3rem;background:#052e16;color:#bbf7d0!important;
      border:1px solid #16a34a!important;text-decoration:none!important;
      font-size:.7rem;vertical-align:middle}
    .market-check-status {padding:.12rem .3rem;border-radius:999px;background:#020617;
      color:#e2e8f0;font-size:.62rem;font-weight:800;white-space:nowrap;
      max-width:56%;overflow:hidden;text-overflow:ellipsis}
    .market-check-signal {margin:.14rem 0;color:#fde68a;font-size:.7rem;font-weight:900}
    .buy-check-list {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
      gap:.2rem;margin:.2rem 0 .3rem}
    .buy-check {padding:.2rem .28rem;border-radius:.3rem;font-size:.62rem;
      font-weight:850;line-height:1.15;border:1px solid;white-space:normal}
    .buy-check-pass {color:#bbf7d0;background:#052e16;border-color:#16a34a}
    .buy-check-wait {color:#fecaca;background:#450a0a;border-color:#ef4444}
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
    @media(max-width:1200px){.summary-grid{grid-template-columns:repeat(3,1fr)}}
    @media(max-width:700px){.summary-grid{grid-template-columns:repeat(2,1fr)}
      .market-check-row{grid-template-columns:1fr}}
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


def read_market_overview_history():
    if not MARKET_OVERVIEW_HISTORY_FILE.exists():
        return []
    records = []
    try:
        for line in MARKET_OVERVIEW_HISTORY_FILE.read_text(
            encoding="utf-8"
        ).splitlines():
            try:
                record = json.loads(line)
                records.append(
                    (int(record["recorded_at"]), str(record.get("regime", "UNKNOWN")))
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
    except OSError:
        return []
    return sorted(records)


def market_status_icon(regime):
    text = str(regime or "UNKNOWN").upper()
    if "WEAK" in text:
        return f"🔴 {text}"
    if "POSITIVE" in text:
        return f"🟢 {text}"
    if "QUIET" in text:
        return f"🟡 {text}"
    return f"🔵 {text}" if text != "UNKNOWN" else "⚪ UNKNOWN"


def play_action_sound(transaction, sound_kind=None):
    if not st.session_state.get("action_sounds_enabled", True):
        return
    if sound_kind is None:
        side = str(transaction.get("side", "")).upper()
        if side == "BUY":
            sound_kind = "buy"
        else:
            try:
                pnl = float(transaction.get("estimated_pnl_usdt", 0) or 0)
            except (TypeError, ValueError):
                pnl = 0
            sound_kind = "profit" if pnl > 0 else "loss" if pnl < 0 else "neutral"
    sequences = {
        "buy": [(523.25, 0.00, 0.13), (659.25, 0.14, 0.18)],
        "profit": [
            (659.25, 0.00, 0.11),
            (783.99, 0.11, 0.11),
            (1046.50, 0.22, 0.22),
        ],
        "loss": [(440.00, 0.00, 0.14), (329.63, 0.15, 0.22)],
        "neutral": [(587.33, 0.00, 0.18)],
    }
    tones = sequences.get(sound_kind, sequences["neutral"])
    components.html(
        """
        <script>
        (() => {
          const tones = %s;
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          if (!AudioCtx) return;
          const context = new AudioCtx();
          context.resume().then(() => {
            const start = context.currentTime + 0.03;
            tones.forEach(([frequency, delay, duration]) => {
              const oscillator = context.createOscillator();
              const gain = context.createGain();
              oscillator.type = "sine";
              oscillator.frequency.value = frequency;
              gain.gain.setValueAtTime(0.0001, start + delay);
              gain.gain.exponentialRampToValueAtTime(0.11, start + delay + 0.015);
              gain.gain.exponentialRampToValueAtTime(
                0.0001, start + delay + duration
              );
              oscillator.connect(gain);
              gain.connect(context.destination);
              oscillator.start(start + delay);
              oscillator.stop(start + delay + duration + 0.02);
            });
            const end = Math.max(...tones.map(tone => tone[1] + tone[2]));
            window.setTimeout(() => context.close(), (end + 0.15) * 1000);
          }).catch(() => {});
        })();
        </script>
        """ % json.dumps(tones),
        height=0,
        width=0,
    )


def notify_new_transaction(transactions):
    if not transactions:
        return
    latest = transactions[-1]
    transaction_key = "|".join(
        str(latest.get(name, ""))
        for name in ("recorded_at", "order_id", "side", "symbol")
    )
    previous_key = st.session_state.get("last_action_sound_transaction")
    st.session_state["last_action_sound_transaction"] = transaction_key
    if previous_key is None or previous_key == transaction_key:
        return
    play_action_sound(latest)


def write_config(
    symbols, maximum_exposure, trade_amount, max_open_positions,
    trading_on_hold, interval, strategy,
):
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    config = {
        "target_symbols": symbols,
        "max_total_exposure_usdt": str(maximum_exposure),
        "trade_amount_usdt": str(trade_amount),
        "max_open_positions": max_open_positions,
        "trading_on_hold": trading_on_hold,
        "interval": interval,
        **strategy,
        "updated_at": int(datetime.now().timestamp()),
    }
    temporary_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_file.replace(CONFIG_FILE)


def add_target_symbol(symbol, status):
    config = read_json(CONFIG_FILE, {})
    symbols = list(
        config.get("target_symbols") or status.get("target_symbols") or []
    )
    if symbol in symbols:
        return False
    config["target_symbols"] = [*symbols, symbol]
    config["updated_at"] = int(datetime.now().timestamp())
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_file.replace(CONFIG_FILE)
    return True


def remove_target_symbol(symbol, status):
    config = read_json(CONFIG_FILE, {})
    symbols = list(
        config.get("target_symbols") or status.get("target_symbols") or []
    )
    if symbol not in symbols:
        return False
    config["target_symbols"] = [item for item in symbols if item != symbol]
    config["updated_at"] = int(datetime.now().timestamp())
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_file.replace(CONFIG_FILE)
    return True


def add_target_symbols(new_symbols, status):
    config = read_json(CONFIG_FILE, {})
    symbols = list(
        config.get("target_symbols") or status.get("target_symbols") or []
    )
    symbols_to_add = [symbol for symbol in new_symbols if symbol not in symbols]
    if not symbols_to_add:
        return 0
    config["target_symbols"] = [*symbols, *symbols_to_add]
    config["updated_at"] = int(datetime.now().timestamp())
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_file.replace(CONFIG_FILE)
    return len(symbols_to_add)


def remove_target_symbols(symbols_to_remove, status):
    config = read_json(CONFIG_FILE, {})
    symbols = list(
        config.get("target_symbols") or status.get("target_symbols") or []
    )
    removal_set = set(symbols_to_remove)
    remaining_symbols = [symbol for symbol in symbols if symbol not in removal_set]
    removed_count = len(symbols) - len(remaining_symbols)
    if not removed_count:
        return 0
    config["target_symbols"] = remaining_symbols
    config["updated_at"] = int(datetime.now().timestamp())
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_file.replace(CONFIG_FILE)
    return removed_count


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


def queue_sell_price_request(symbol, environment, sell_price):
    request = {
        "command_id": uuid.uuid4().hex,
        "action": "SET_SELL_PRICE",
        "symbol": symbol,
        "sell_price": str(sell_price),
        "environment": environment,
        "created_at": int(datetime.now().timestamp()),
    }
    with SELL_REQUEST_FILE.open("a", encoding="utf-8") as request_file:
        request_file.write(json.dumps(request) + "\n")


def queue_buy_request(symbol, environment, amount_usdt):
    request = {
        "command_id": uuid.uuid4().hex,
        "action": "BUY_MARKET",
        "symbol": symbol,
        "amount_usdt": str(amount_usdt),
        "environment": environment,
        "created_at": int(datetime.now().timestamp()),
    }
    with BUY_REQUEST_FILE.open("a", encoding="utf-8") as request_file:
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
    poll_seconds = int(config.get("poll_seconds", 15))
    live_price_refresh_seconds = int(config.get("live_price_refresh_seconds", 2))
    status_strategy = status.get("strategy", {})

    def strategy_value(name, default):
        return config[name] if name in config else status_strategy.get(name, default)

    buy_rsi_recovery = float(strategy_value("buy_rsi_recovery", 35))
    max_support_distance_pct = float(
        strategy_value("max_support_distance_pct", 0.30)
    )
    trend_interval = str(strategy_value("trend_interval", "1h"))
    if trend_interval not in INTERVAL_OPTIONS:
        trend_interval = "1h"
    trend_ema_period = int(strategy_value("trend_ema_period", 50))
    min_net_reward_pct = float(strategy_value("min_net_reward_pct", 0.50))
    min_net_profit_usdt = float(strategy_value("min_net_profit_usdt", 0.50))
    estimated_round_trip_fee_pct = float(
        strategy_value("estimated_round_trip_fee_pct", 0.20)
    )
    atr_sl_multiplier = float(strategy_value("atr_sl_multiplier", 1.5))
    max_stop_distance_pct = float(
        strategy_value("max_stop_distance_pct", 0.80)
    )
    risk_reward_ratio = float(strategy_value("risk_reward_ratio", 2.0))
    sell_rsi_threshold = float(strategy_value("sell_rsi_threshold", 65))
    suggested_symbols = [
        str(suggestion.get("symbol", "")).strip().upper()
        for suggestion in status.get("suggestions", [])
        if suggestion.get("symbol")
    ]
    symbol_options = list(dict.fromkeys(list(symbols) + suggested_symbols))
    with st.expander("⚙️ Trading controls", expanded=False):
        saved_notice = st.session_state.pop("trading_controls_notice", None)
        if saved_notice:
            st.success(saved_notice)
        st.caption(
            f"{float(trade_amount):,.2f} USDT/trade · "
            f"{float(maximum):,.2f} exposure · "
            f"{max_open_positions} positions · {interval} · {len(symbols)} targets"
        )
        st.caption(
            f"Buy: RSI ↑ {buy_rsi_recovery:g} · support ≤ "
            f"{max_support_distance_pct:.2f}% · {trend_interval} EMA "
            f"{trend_ema_period} · net TP ≥ {min_net_reward_pct:.2f}% · "
            f"stop ≤ {max_stop_distance_pct:.2f}%"
        )
        st.caption(
            f"Sell: SL {atr_sl_multiplier:g} ATR · TP {risk_reward_ratio:g}R · "
            f"RSI ≥ {sell_rsi_threshold:g} · net profit ≥ "
            f"{min_net_profit_usdt:.2f} USDT"
        )
        with st.form("quick_add_target", clear_on_submit=True):
            add_symbol_column, add_button_column = st.columns([3, 1])
            with add_symbol_column:
                quick_symbol = st.text_input(
                    "Quick add target",
                    placeholder="DEXEUSDT",
                    help="Enter one complete USDT Spot symbol.",
                )
            with add_button_column:
                st.write("")
                quick_add_confirmed = st.form_submit_button(
                    "Add", width="stretch"
                )

        if quick_add_confirmed:
            normalized_symbol = quick_symbol.strip().upper()
            if not re.fullmatch(r"[A-Z0-9]+USDT", normalized_symbol):
                st.error("Enter a complete USDT symbol, for example DEXEUSDT.")
            elif normalized_symbol in symbols:
                st.info(f"{normalized_symbol} is already selected.")
            else:
                write_config(
                    list(symbols) + [normalized_symbol],
                    float(maximum),
                    float(trade_amount),
                    max_open_positions,
                    trading_on_hold,
                    interval,
                    {
                        "buy_rsi_recovery": str(buy_rsi_recovery),
                        "max_support_distance_pct": str(
                            max_support_distance_pct
                        ),
                        "trend_interval": trend_interval,
                        "trend_ema_period": trend_ema_period,
                        "min_net_reward_pct": str(min_net_reward_pct),
                        "min_net_profit_usdt": str(min_net_profit_usdt),
                        "estimated_round_trip_fee_pct": str(
                            estimated_round_trip_fee_pct
                        ),
                        "atr_sl_multiplier": str(atr_sl_multiplier),
                        "max_stop_distance_pct": str(max_stop_distance_pct),
                        "risk_reward_ratio": str(risk_reward_ratio),
                        "sell_rsi_threshold": str(sell_rsi_threshold),
                    },
                )
                st.session_state["trading_controls_notice"] = (
                    f"{normalized_symbol} added. The bot will load it next cycle."
                )
                st.rerun()

        with st.form("runtime_settings"):
            limits_tab, buy_tab, sell_tab, targets_tab = st.tabs(
                ["Limits", "Buy", "Sell", "Targets"]
            )
            with limits_tab:
                st.caption("Capital limits and the completed-candle interval.")
                trade_column, exposure_column = st.columns(2)
                with trade_column:
                    trade_amount_input = st.number_input(
                        "USDT per trade",
                        min_value=1.0,
                        value=float(trade_amount),
                        step=1.0,
                        help="Maximum USDT requested for one new buy.",
                    )
                with exposure_column:
                    maximum_input = st.number_input(
                        "Total exposure",
                        min_value=1.0,
                        value=float(maximum),
                        step=1.0,
                        help="Combined original entry value allowed across positions.",
                    )
                positions_column, interval_column = st.columns(2)
                with positions_column:
                    max_open_positions_input = st.number_input(
                        "Max positions",
                        min_value=1,
                        value=max_open_positions,
                        step=1,
                    )
                with interval_column:
                    interval_input = st.selectbox(
                        "Trade interval",
                        INTERVAL_OPTIONS,
                        index=INTERVAL_OPTIONS.index(interval),
                        help="Timeframe for RSI, ATR, and support.",
                    )
                speed_column, live_column = st.columns(2)
                with speed_column:
                    poll_seconds_input = st.number_input("Full check seconds", min_value=10, max_value=300, value=poll_seconds, step=5)
                with live_column:
                    live_price_refresh_seconds_input = st.number_input("Live price seconds", min_value=2, max_value=60, value=live_price_refresh_seconds, step=1)
            with buy_tab:
                st.caption("All five checks must pass before a new buy.")
                rsi_column, support_column = st.columns(2)
                with rsi_column:
                    buy_rsi_recovery_input = st.number_input(
                        "RSI recovery",
                        min_value=1.0,
                        max_value=50.0,
                        value=buy_rsi_recovery,
                        step=1.0,
                        help="RSI must cross upward through this level.",
                    )
                with support_column:
                    max_support_distance_input = st.number_input(
                        "Support distance %",
                        min_value=0.0,
                        max_value=5.0,
                        value=max_support_distance_pct,
                        step=0.05,
                        format="%.2f",
                    )
                trend_column, ema_column = st.columns(2)
                with trend_column:
                    trend_interval_input = st.selectbox(
                        "Trend interval",
                        INTERVAL_OPTIONS,
                        index=INTERVAL_OPTIONS.index(trend_interval),
                        help="Must be equal to or longer than the trade interval.",
                    )
                with ema_column:
                    trend_ema_period_input = st.number_input(
                        "EMA period",
                        min_value=10,
                        max_value=500,
                        value=trend_ema_period,
                        step=10,
                    )
                reward_column, fee_column = st.columns(2)
                with reward_column:
                    min_net_reward_input = st.number_input(
                        "Minimum net TP %",
                        min_value=0.0,
                        max_value=20.0,
                        value=min_net_reward_pct,
                        step=0.10,
                        format="%.2f",
                    )
                with fee_column:
                    estimated_fee_input = st.number_input(
                        "Fees + slippage %",
                        min_value=0.0,
                        max_value=5.0,
                        value=estimated_round_trip_fee_pct,
                        step=0.05,
                        format="%.2f",
                        help="Estimated combined buy and sell cost.",
                    )
                max_stop_distance_input = st.number_input(
                    "Maximum stop distance %",
                    min_value=0.1,
                    max_value=10.0,
                    value=max_stop_distance_pct,
                    step=0.05,
                    format="%.2f",
                    help=(
                        "Skip an automatic buy when its ATR-based stop is "
                        "farther than this percentage from entry."
                    ),
                )

            with sell_tab:
                st.caption("Protection settings and the indicator exit.")
                stop_column, ratio_column = st.columns(2)
                with stop_column:
                    atr_sl_multiplier_input = st.number_input(
                        "Stop distance (ATR)",
                        min_value=0.1,
                        max_value=10.0,
                        value=atr_sl_multiplier,
                        step=0.1,
                        format="%.2f",
                    )
                with ratio_column:
                    risk_reward_ratio_input = st.number_input(
                        "TP reward/risk",
                        min_value=0.1,
                        max_value=10.0,
                        value=risk_reward_ratio,
                        step=0.1,
                        format="%.2f",
                    )
                sell_rsi_threshold_input = st.number_input(
                    "RSI exit level",
                    min_value=50.0,
                    max_value=99.0,
                    value=sell_rsi_threshold,
                    step=1.0,
                )
                min_net_profit_input = st.number_input(
                    "Minimum net profit (USDT)",
                    min_value=0.0,
                    max_value=1000.0,
                    value=min_net_profit_usdt,
                    step=0.10,
                    format="%.2f",
                    help=(
                        "Minimum estimated profit after buy and sell fees. "
                        "Stop-loss and manual sells can exit below this amount."
                    ),
                )
                st.caption("SL = entry − ATR distance · TP = entry + stop × reward/risk")
            with targets_tab:
                st.caption("Add or remove USDT Spot markets.")
                symbols_input = st.multiselect(
                    "Target symbols",
                    options=symbol_options,
                    default=symbols,
                    placeholder="Selected markets",
                    help="Select the x on a tag to remove it, then save all controls.",
                )
                hold_input = st.toggle(
                    "Pause new buys",
                    value=trading_on_hold,
                    help="Existing positions remain monitored and can still be sold.",
                )
            confirmed = st.form_submit_button(
                "Save all controls", type="primary", width="stretch"
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
            elif (
                INTERVAL_MINUTES[trend_interval_input]
                < INTERVAL_MINUTES[interval_input]
            ):
                st.error("Larger-trend interval cannot be shorter than candle interval.")
            else:
                write_config(
                    parsed_symbols, maximum_input, trade_amount_input,
                    max_open_positions_input, hold_input, interval_input,
                    {
                        "buy_rsi_recovery": str(buy_rsi_recovery_input),
                        "max_support_distance_pct": str(
                            max_support_distance_input
                        ),
                        "trend_interval": trend_interval_input,
                        "trend_ema_period": int(trend_ema_period_input),
                        "min_net_reward_pct": str(min_net_reward_input),
                        "min_net_profit_usdt": str(min_net_profit_input),
                        "estimated_round_trip_fee_pct": str(
                            estimated_fee_input
                        ),
                        "atr_sl_multiplier": str(atr_sl_multiplier_input),
                        "max_stop_distance_pct": str(max_stop_distance_input),
                        "risk_reward_ratio": str(risk_reward_ratio_input),
                        "sell_rsi_threshold": str(sell_rsi_threshold_input),
                        "poll_seconds": int(poll_seconds_input),
                        "live_price_refresh_seconds": int(live_price_refresh_seconds_input),
                    },
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
    history["Value"] = pd.to_numeric(history["Value"], errors="coerce")
    overview_history = read_market_overview_history()
    overview_times = [item[0] for item in overview_history]

    def regime_at_transaction(recorded_at):
        try:
            index = bisect_right(overview_times, int(recorded_at)) - 1
        except (TypeError, ValueError):
            return "UNKNOWN"
        return overview_history[index][1] if index >= 0 else "UNKNOWN"

    history["Market status"] = history["recorded_at"].map(regime_at_transaction)
    config = read_json(CONFIG_FILE, {})
    one_way_fee_pct = float(
        config.get("estimated_round_trip_fee_pct", 0.2)
    ) / 2
    history["Est. Fee (USDT)"] = history["Value"] * one_way_fee_pct / 100
    history["Est. Net P&L (USDT)"] = float("nan")
    pending_buy_fees = {}
    for index, row in history.iterrows():
        symbol = str(row.get("Symbol", ""))
        if str(row.get("Side", "")).upper() == "BUY":
            pending_buy_fees.setdefault(symbol, []).append(
                float(row.get("Est. Fee (USDT)", 0) or 0)
            )
        elif str(row.get("Side", "")).upper() == "SELL":
            buy_fees = pending_buy_fees.get(symbol, [])
            buy_fee = buy_fees.pop(0) if buy_fees else 0
            gross_pnl = row.get("Est. P&L (USDT)")
            if not pd.isna(gross_pnl):
                history.at[index, "Est. Net P&L (USDT)"] = (
                    float(gross_pnl)
                    - buy_fee
                    - float(row.get("Est. Fee (USDT)", 0) or 0)
                )
    return history


def position_candlestick_chart(
    candles, current, entry, break_even, stop_loss, take_profit, interval,
    max_view=False,
):
    parsed = []
    for candle in (candles or [])[-48:]:
        try:
            parsed.append(
                {
                    "close_time": int(candle["close_time"]),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not parsed:
        return (
            '<div class="position-candle-empty">📊 Candles will appear after '
            'the bot completes its next market check.</div>'
        )

    # A taller aspect ratio and smaller plot margins use the full card space,
    # especially when three open-position cards share one row.
    # Keep six maximum-view cards visible as a 3 x 2 grid on laptop screens.
    # The max chart remains taller than the normal dashboard chart.
    width, height = 600, 235 if max_view else 220
    left, right, top, bottom = 6, 82, 7, 22
    plot_width = width - left - right
    plot_height = height - top - bottom
    levels = [stop_loss, entry, break_even, current, take_profit]
    chart_low = min([item["low"] for item in parsed] + levels)
    chart_high = max([item["high"] for item in parsed] + levels)
    price_span = chart_high - chart_low
    if price_span <= 0:
        price_span = abs(chart_high) * 0.01 or 1
    chart_low -= price_span * 0.05
    chart_high += price_span * 0.05

    def y_position(price):
        return top + (chart_high - price) / (chart_high - chart_low) * plot_height

    step = plot_width / len(parsed)
    candle_width = max(5, min(11, step * 0.44))
    chart_parts = [
        f'<svg class="position-candle-chart" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{html.escape(str(interval))} candlestick chart '
        f'with stop loss, entry, break-even, current price, and take profit">',
        f'<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" '
        'fill="#0b1220"/>',
    ]
    for grid_index in range(1, 4):
        grid_y = top + plot_height * grid_index / 4
        chart_parts.append(
            f'<line x1="{left}" x2="{left + plot_width}" y1="{grid_y:.2f}" '
            f'y2="{grid_y:.2f}" stroke="#334155" stroke-width="0.7" '
            'opacity="0.25"/>'
        )

    for index, candle in enumerate(parsed):
        candle_x = left + step * index + step / 2
        rising = candle["close"] >= candle["open"]
        color = "#34d399" if rising else "#fb7185"
        high_y = y_position(candle["high"])
        low_y = y_position(candle["low"])
        body_top = y_position(max(candle["open"], candle["close"]))
        body_bottom = y_position(min(candle["open"], candle["close"]))
        body_height = max(2, body_bottom - body_top)
        candle_tip = (
            f'O {smart_number(candle["open"])} · H {smart_number(candle["high"])} · '
            f'L {smart_number(candle["low"])} · C {smart_number(candle["close"])}'
        )
        chart_parts.extend(
            [
                f'<g><title>{html.escape(candle_tip)}</title>',
                f'<line x1="{candle_x:.2f}" x2="{candle_x:.2f}" '
                f'y1="{high_y:.2f}" y2="{low_y:.2f}" stroke="{color}" '
                'stroke-width="1.4" opacity="0.5"/>',
                f'<rect x="{candle_x - candle_width / 2:.2f}" '
                f'y="{body_top:.2f}" width="{candle_width:.2f}" '
                f'height="{body_height:.2f}" fill="{color}" '
                'opacity="0.5"/></g>',
            ]
        )

    level_specs = [
        ("TP", take_profit, "#6ee7b7", "4 4"),
        ("Now", current, "#f8fafc", ""),
        ("BE", break_even, "#cbd5e1", "5 5"),
        ("Entry", entry, "#94a3b8", "5 5"),
        ("SL", stop_loss, "#fda4af", "4 4"),
    ]
    label_positions = []
    for label, price, color, dash in sorted(
        level_specs, key=lambda item: y_position(item[1])
    ):
        true_y = y_position(price)
        label_y = true_y
        if label_positions and label_y - label_positions[-1] < 15:
            label_y = label_positions[-1] + 15
        label_positions.append(label_y)
        dash_attribute = f' stroke-dasharray="{dash}"' if dash else ""
        chart_parts.extend(
            [
                f'<line x1="{left}" x2="{left + plot_width}" y1="{true_y:.2f}" '
                f'y2="{true_y:.2f}" stroke="{color}" stroke-width="1" '
                f'opacity="0.5"{dash_attribute}/>',
                f'<line x1="{left + plot_width}" x2="{left + plot_width + 6}" '
                f'y1="{true_y:.2f}" y2="{label_y:.2f}" stroke="{color}" '
                'stroke-width="0.8" opacity="0.5"/>',
                f'<text x="{left + plot_width + 9}" y="{label_y + 4:.2f}" '
                f'fill="{color}" font-size="11" font-weight="600">'
                f'{html.escape(label)} {smart_number(price)}</text>',
            ]
        )

    first_time = datetime.fromtimestamp(
        parsed[0]["close_time"] / 1000
    ).astimezone().strftime("%H:%M")
    last_time = datetime.fromtimestamp(
        parsed[-1]["close_time"] / 1000
    ).astimezone().strftime("%H:%M")
    chart_parts.extend(
        [
            f'<text x="{left}" y="{height - 7}" fill="#94a3b8" '
            f'font-size="11">{html.escape(first_time)}</text>',
            f'<text x="{left + plot_width}" y="{height - 7}" '
            f'text-anchor="end" fill="#94a3b8" font-size="11">'
            f'{html.escape(last_time)}</text></svg>',
        ]
    )
    return (
        '<div class="position-candle-wrap">'
        f'<div class="position-candle-title"><span>📊 Price · '
        f'{html.escape(str(interval))}</span><span>{len(parsed)} candles</span></div>'
        f'{"".join(chart_parts)}</div>'
    )


def render_position_progress(
    symbol, position, current_price, trading_enabled, environment,
    live_market=None, max_view=False,
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
    runtime_config = read_json(CONFIG_FILE, {})
    one_way_fee_pct = float(
        runtime_config.get("estimated_round_trip_fee_pct", 0.2)
    ) / 2
    estimated_buy_fee = entry_value * one_way_fee_pct / 100
    estimated_sell_fee = current_value * one_way_fee_pct / 100
    estimated_net_pnl = (
        unrealized_pnl - estimated_buy_fee - estimated_sell_fee
    )
    estimated_net_pct = (
        estimated_net_pnl / entry_value * 100 if entry_value else 0
    )
    fee_rate = one_way_fee_pct / 100
    break_even_price = (
        entry * (1 + fee_rate) / (1 - fee_rate)
        if fee_rate < 1 else entry
    )
    live_market = live_market or {}
    last_progress_at = live_market.get("last_progress_at")
    interval_minutes = INTERVAL_MINUTES.get(
        runtime_config.get("interval", "5m"), 5
    )
    stall_text = "🟢 Watching price"
    if last_progress_at:
        stalled_minutes = max(
            0, int((datetime.now().timestamp() - float(last_progress_at)) / 60)
        )
        if stalled_minutes >= interval_minutes * 6:
            stall_text = f"🔴 No new high {stalled_minutes}m"
        elif stalled_minutes >= interval_minutes * 3:
            stall_text = f"🟡 Waiting {stalled_minutes}m"
        else:
            stall_text = f"🟢 New high {stalled_minutes}m ago"
    pnl_style = "pnl-positive" if estimated_net_pnl >= 0 else "pnl-negative"
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
            f'<div class="position-quantity">Quantity: {smart_number(quantity)}</div>',
            unsafe_allow_html=True,
        )
    with profit_column:
        st.markdown(
            f'<div class="position-pnl {pnl_style}">{estimated_net_pnl:+,.4f} USDT'
            f'<span class="position-spent">Spent {entry_value:,.2f} USDT</span>'
            f'<br><small>Est. net {estimated_net_pct:+.2f}%</small></div>',
            unsafe_allow_html=True,
        )
    with action_column:
        with st.popover("💸" if max_view else "Sell now"):
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
            st.divider()
            sell_price = st.number_input(
                "Sell at price",
                min_value=0.00000001,
                value=float(take_profit),
                format="%.8f",
                key=f"manual_sell_price_{symbol}",
                disabled=not trading_enabled,
                help=(
                    "Bot-managed trigger, not a Binance limit order. "
                    "The bot must remain running."
                ),
            )
            if st.button(
                "Set sell price",
                key=f"set_sell_price_{symbol}",
                disabled=not trading_enabled,
                width="stretch",
            ):
                queue_sell_price_request(symbol, environment, sell_price)
                st.success(
                    f"Sell price update to {sell_price:.8f} queued."
                )
    st.markdown(
        position_candlestick_chart(
            live_market.get("candles"),
            current,
            entry,
            break_even_price,
            stop_loss,
            take_profit,
            runtime_config.get("interval", "5m"),
            max_view,
        ),
        unsafe_allow_html=True,
    )
    progress_pct = progress * 100
    break_even_pct = (
        (break_even_price - stop_loss) / span * 100 if span > 0 else 50
    )
    break_even_pct = max(0, min(break_even_pct, 100))
    label_pct = max(8, min(progress_pct, 92))
    if progress_pct <= break_even_pct and break_even_pct > 0:
        current_hue = round(38 * progress_pct / break_even_pct)
    elif break_even_pct < 100:
        current_hue = round(
            38
            + 97
            * (progress_pct - break_even_pct)
            / (100 - break_even_pct)
        )
    else:
        current_hue = 38
    current_hue = max(0, min(current_hue, 135))
    st.markdown(
        f"""
        <div class="position-progress-wrap{' position-progress-wrap-max' if max_view else ''}">
          <div class="position-progress-track" style="background:linear-gradient(90deg,#b91c1c 0%,#f59e0b {break_even_pct:.2f}%,#16a34a 100%)">
            <span class="position-progress-unfilled" style="width:{100 - progress_pct:.2f}%"></span>
            <span class="position-entry-marker" style="left:{break_even_pct:.2f}%" title="Fee-adjusted break-even"></span>
            <span class="position-progress-marker" style="left:{progress_pct:.2f}%" title="Current price"></span>
            <span class="position-current-label" style="left:{label_pct:.2f}%;background:hsl({current_hue} 80% 32%)">{current:.2f}</span>
          </div>
          <div class="position-progress-labels"><span>SL {smart_number(stop_loss)}</span><span>BE {smart_number(break_even_price)}</span><span>TP {smart_number(take_profit)}</span></div>
          <div class="position-progress-state">{html.escape(stall_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if max_view:
        return
    with st.expander("Position details", expanded=False):
        st.markdown(
            f"""
            <div class="position-stats">
              <div class="position-stat"><div class="position-label">Entry / Spent</div><div class="position-value">Price {smart_number(entry)}<br>{entry_value:,.4f} USDT</div></div>
              <div class="position-stat"><div class="position-label">Current / Value</div><div class="position-value">Price {smart_number(current)}<br>{current_value:,.4f} USDT</div></div>
              <div class="position-stat"><div class="position-label">Take Profit / Est. Value</div><div class="position-value">Price {smart_number(take_profit)}<br>{take_profit_value:,.4f} USDT</div></div>
              <div class="position-stat"><div class="position-label">Stop Loss / Est. Value</div><div class="position-value">Price {smart_number(stop_loss)}<br>{stop_loss_value:,.4f} USDT</div></div>
              <div class="position-stat"><div class="position-label">Est. Buy Fee ({one_way_fee_pct:.3f}%)</div><div class="position-value">{estimated_buy_fee:,.4f} USDT</div></div>
              <div class="position-stat"><div class="position-label">Est. Sell Fee ({one_way_fee_pct:.3f}%)</div><div class="position-value">{estimated_sell_fee:,.4f} USDT</div></div>
              <div class="position-stat"><div class="position-label">Est. Net P&amp;L</div><div class="position-value">{estimated_net_pnl:+,.4f} USDT</div></div>
            </div>
            <div class="position-quantity">Gross estimates before fees &middot; {distance_label}: {distance:.2f}%</div>
            """,
            unsafe_allow_html=True,
        )


def render_market_suggestions(status):
    suggestions = status.get("suggestions", [])
    config = read_json(CONFIG_FILE, {})
    target_symbols = set(
        config.get("target_symbols") or status.get("target_symbols", [])
    )
    selected_count = sum(
        suggestion["symbol"] in target_symbols for suggestion in suggestions
    )
    with st.expander(
        f"🟢 Coins to buy ({len(suggestions)}) · Selected: {selected_count}",
        expanded=False,
    ):
        st.caption(
            "Read-only screen: stablecoins excluded; requires a 1.5% range "
            "and 10M USDT volume, then ranks by range. "
            "This is not a profit guarantee or a buy signal."
        )
        candidate_symbols = [
            suggestion["symbol"]
            for suggestion in suggestions
            if suggestion["symbol"] not in target_symbols
        ]
        if st.button(
            "Add all",
            key="watchlist_add_all",
            type="primary",
            disabled=not candidate_symbols,
        ):
            added_count = add_target_symbols(candidate_symbols, status)
            st.toast(
                f"{added_count} candidate{'s' if added_count != 1 else ''} added; "
                "the bot will check them on the next cycle."
            )
            st.rerun()
        if not suggestions:
            st.info("Suggestions will appear after the bot refreshes Binance market data.")
            return
        for start in range(0, len(suggestions), 3):
            columns = st.columns(3)
            for column, suggestion in zip(columns, suggestions[start : start + 3]):
                with column:
                    symbol = html.escape(suggestion["symbol"])
                    target_tag = (
                        '<span class="suggestion-target-tag">TARGET</span>'
                        if suggestion["symbol"] in target_symbols
                        else ""
                    )
                    analysis = html.escape(suggestion["analysis"])
                    st.markdown(
                        f"""
                        <div class="suggestion-card">
                          <div class="suggestion-symbol">{symbol}{target_tag}</div>
                          <div class="suggestion-stat">Price: {smart_number(suggestion['price'])}</div>
                          <div class="suggestion-stat">24h change: {suggestion['change_pct']:+.2f}%</div>
                          <div class="suggestion-stat">24h range: {suggestion['range_pct']:.2f}%</div>
                          <div class="suggestion-stat">Volume: {suggestion['quote_volume_usdt']/1_000_000:.1f}M USDT</div>
                          <p class="suggestion-note">{analysis}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if suggestion["symbol"] not in target_symbols:
                        if st.button(
                            "Add to targets",
                            key=f"watchlist_add_{suggestion['symbol']}",
                            width="stretch",
                        ):
                            if add_target_symbol(suggestion["symbol"], status):
                                st.toast(
                                    f"{suggestion['symbol']} added; the bot will "
                                    "check it on the next cycle."
                                )
                            st.rerun()


def render_targets_outside_watchlist(status, positions):
    suggestions = status.get("suggestions", [])
    if not suggestions:
        return
    config = read_json(CONFIG_FILE, {})
    target_symbols = list(
        config.get("target_symbols") or status.get("target_symbols") or []
    )
    suggestion_symbols = {
        str(suggestion.get("symbol", "")) for suggestion in suggestions
    }
    outside_symbols = [
        symbol for symbol in target_symbols if symbol not in suggestion_symbols
    ]
    with st.expander(
        f"🔴 Coins to avoid ({len(outside_symbols)})",
        expanded=False,
    ):
        st.caption(
            "Review only: these targets are absent from the current 24-hour "
            "liquidity/range screen. This is not automatically a sell signal. "
            "Removing a target prevents new entries after the bot's next cycle; "
            "an existing position remains monitored until it closes."
        )
        if st.button(
            "Remove all",
            key="watchlist_remove_all",
            type="secondary",
            disabled=not outside_symbols,
        ):
            removed_count = remove_target_symbols(outside_symbols, status)
            st.toast(
                f"{removed_count} target{'s' if removed_count != 1 else ''} removed; "
                "the bot will stop seeking new entries after its next configuration reload."
            )
            st.rerun()
        if not outside_symbols:
            st.success("Every configured target is in the current watchlist screen.")
            return
        markets = status.get("markets", {})
        for start in range(0, len(outside_symbols), 3):
            columns = st.columns(3)
            for column, symbol in zip(columns, outside_symbols[start : start + 3]):
                market = markets.get(symbol, {})
                reasons = ["Outside current 24h volume/range screen"]
                if market and not market.get("trend_ok", False):
                    reasons.append("Below trend EMA")
                if market and not market.get("reward_ok", False):
                    reasons.append("Reward target not met")
                if market and not market.get("stop_risk_ok", False):
                    reasons.append("Stop distance too wide")
                if "SELL" in str(market.get("signal", "")):
                    reasons.append("Currently overbought")
                checks = sum(
                    bool(market.get(name))
                    for name in (
                        "rsi_recovered", "near_support", "trend_ok", "reward_ok",
                        "stop_risk_ok",
                    )
                )
                position_note = (
                    "Open position will remain monitored."
                    if symbol in positions
                    else "No open tracked position."
                )
                with column:
                    st.markdown(
                        f"""
                        <div class="target-review-card">
                          <div class="target-review-symbol">{html.escape(symbol)}</div>
                          <div class="target-review-reason">Current buy checks: {checks}/5</div>
                          <div class="target-review-reason">{html.escape(' · '.join(reasons))}</div>
                          <div class="target-review-reason">{html.escape(position_note)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "Remove target",
                        key=f"watchlist_remove_{symbol}",
                        type="secondary",
                        width="stretch",
                    ):
                        if remove_target_symbol(symbol, status):
                            st.toast(
                                f"{symbol} removed; the bot will stop seeking new "
                                "entries after its next configuration reload."
                            )
                        st.rerun()


def render_results_by_symbol(history):
    with st.expander("📊 Results by symbol", expanded=False):
        if history.empty:
            st.info("No completed trades are available for symbol results yet.")
            return
        sells = history[history["Side"] == "SELL"].copy()
        if sells.empty:
            st.info("No completed trades are available for symbol results yet.")
            return
        sells["Win"] = sells["Est. Net P&L (USDT)"].fillna(0) > 0
        results = (
            sells.groupby("Symbol", dropna=False)
            .agg(
                completed=("Side", "size"),
                wins=("Win", "sum"),
                total_pnl=("Est. Net P&L (USDT)", "sum"),
                average_pnl=("Est. Net P&L (USDT)", "mean"),
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
                          <div class="{pnl_style}">Total net P&amp;L: {total_pnl:+.4f} USDT</div>
                          <div class="result-stat">Completed trades: {int(result['completed'])}</div>
                          <div class="result-stat">Wins: {int(result['wins'])}</div>
                          <div class="result-stat">Win rate: {float(result['win_rate']):.1f}%</div>
                          <div class="result-stat">Average net P&amp;L: {float(result['average_pnl']):+.4f} USDT</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


def filter_history(history):
    today = datetime.now().astimezone().date()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())

    period_masks = {
        "today": history["Time"].dt.date == today,
        "yesterday": history["Time"].dt.date == yesterday,
        "week": (
            (history["Time"].dt.date >= week_start)
            & (history["Time"].dt.date <= today)
        ),
        "all": pd.Series(True, index=history.index),
    }

    def period_win_count(period_name):
        period_history = history[period_masks[period_name]]
        completed = period_history[period_history["Side"] == "SELL"]
        wins = int(
            (completed["Est. Net P&L (USDT)"].fillna(0) > 0).sum()
        )
        return wins, len(completed)

    period_labels = {}
    for period_name, title in (
        ("today", "Today"),
        ("yesterday", "Yesterday"),
        ("week", "This week"),
        ("all", "All"),
    ):
        wins, completed = period_win_count(period_name)
        period_labels[period_name] = f"{title} · ✅ {wins}/{completed}"

    selected_period = st.radio(
        "Transaction period",
        ("today", "yesterday", "week", "all"),
        format_func=lambda option: period_labels[option],
        horizontal=True,
        label_visibility="collapsed",
        key="transaction_period_filter",
    )

    with st.popover("⚙️ Advanced filters"):
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

    filtered = history[period_masks[selected_period]].copy()
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
    pnl = row.get("Est. Net P&L (USDT)")
    if pd.isna(pnl) or float(pnl) == 0:
        return "BREAK EVEN"
    return "PROFIT" if float(pnl) > 0 else "LOSS"


def style_transaction_row(row):
    result = str(row.get("Result", row.get("Outcome", ""))).upper()
    if "PROFIT" in result:
        style = "background-color:rgba(34,197,94,.16);color:#bbf7d0;font-weight:650"
    elif "LOSS" in result:
        style = "background-color:rgba(239,68,68,.16);color:#fecaca;font-weight:650"
    elif "BREAK EVEN" in result:
        style = "background-color:rgba(148,163,184,.10);color:#e2e8f0"
    elif "ENTRY" in result:
        style = "background-color:rgba(59,130,246,.10);color:#dbeafe;font-weight:600"
    else:
        style = ""
    return [style] * len(row)


def format_transaction_time(value):
    if value is None or pd.isna(value):
        return "—"
    try:
        moment = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
        today = datetime.now().astimezone().date()
        day_gap = (today - moment.date()).days
        if day_gap == 0:
            day_label = "Today"
        elif day_gap == 1:
            day_label = "Yesterday"
        else:
            day_label = moment.strftime("%d %b %Y")
        return f"{day_label} · {moment.strftime('%H:%M:%S')}"
    except (AttributeError, TypeError, ValueError):
        return str(value)


def smart_number(value, signed=False):
    if value is None or pd.isna(value):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    magnitude = abs(number)
    if magnitude >= 1000:
        decimals = 2
    elif magnitude >= 1:
        decimals = 4
    elif magnitude >= 0.01:
        decimals = 5
    elif magnitude >= 0.0001:
        decimals = 7
    else:
        decimals = 9
    prefix = "+" if signed and number > 0 else ""
    text = f"{abs(number) if number < 0 else number:,.{decimals}f}"
    text = text.rstrip("0").rstrip(".")
    if number < 0:
        return f"-{text}"
    return f"{prefix}{text}"


def format_usdt(value, signed=False, approximate=False):
    number = smart_number(value, signed=signed)
    if number == "—":
        return number
    prefix = "≈" if approximate else ""
    return f"{prefix}{number} USDT"


def transaction_action(side):
    return "🟢 Buy" if str(side).upper() == "BUY" else "🔴 Sell"


def transaction_outcome(result):
    return {
        "ENTRY": "🔵 Entry",
        "PROFIT": "✅ Profit",
        "LOSS": "❌ Loss",
        "BREAK EVEN": "⚪ Break even",
    }.get(str(result).upper(), "⚪ Unknown")


def transaction_reason_icon(reason):
    reason_text = str(reason or "—")
    lowered = reason_text.lower()
    if "take profit" in lowered:
        icon = "🎯"
    elif "stop loss" in lowered:
        icon = "🛑"
    elif "rsi" in lowered:
        icon = "📈"
    elif "manual buy" in lowered:
        icon = "🛒"
    elif "manual sell" in lowered:
        icon = "✋"
    elif "strategy buy" in lowered:
        icon = "🤖"
    else:
        icon = "ℹ️"
    return f"{icon} {reason_text}"


def format_market_number(value, decimals=8):
    if value is None:
        return "N/A"
    try:
        # Market prices are display values; avoid showing meaningless trailing
        # zeros while retaining explicit precision for percentages/metrics.
        if decimals == 8:
            return smart_number(value)
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


@st.fragment(run_every=5)
def render_market_check_cards():
    state = read_state()
    status = read_json(STATUS_FILE, {})
    config = read_json(CONFIG_FILE, {})
    live_prices = read_json(LIVE_PRICE_FILE, {})
    if live_prices.get("environment") != status.get("environment"):
        live_prices = {}
    live_markets = live_prices.get("prices", {})
    markets = status.get("markets", {})
    target_symbols = status.get("target_symbols", [])
    open_symbols = set(state.get("positions", {}))
    symbol_results = {}
    result_history = transaction_frame(read_transactions())
    for transaction in result_history.to_dict("records"):
        if str(transaction.get("Side", "")).upper() != "SELL":
            continue
        symbol = str(transaction.get("Symbol", "")).upper()
        result = symbol_results.setdefault(symbol, {"wins": 0, "completed": 0})
        result["completed"] += 1
        try:
            if float(transaction.get("Est. Net P&L (USDT)", 0)) > 0:
                result["wins"] += 1
        except (TypeError, ValueError):
            pass
    allowed_support_distance = format_market_number(
        config.get("max_support_distance_pct", 0.5), 2
    )
    buy_rsi_threshold = float(config.get("buy_rsi_recovery", 40))
    min_reward_threshold = float(config.get("min_net_reward_pct", 0.6))
    max_stop_distance_threshold = float(
        config.get("max_stop_distance_pct", 0.8)
    )
    sell_rsi_threshold = float(config.get("sell_rsi_threshold", 65))
    buy_check_names = (
        "rsi_recovered", "near_support", "trend_ok", "reward_ok",
        "stop_risk_ok",
    )
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

    def readiness_score(symbol):
        market = markets.get(symbol, {})
        return sum(bool(market.get(name)) for name in buy_check_names)

    def buy_proximity_score(symbol):
        market = markets.get(symbol, {})
        scores = []
        for check_name in buy_check_names:
            if market.get(check_name):
                scores.append(1.0)
                continue
            try:
                if check_name == "rsi_recovered":
                    current_rsi = float(market["rsi"])
                    previous_rsi = float(market["previous_rsi"])
                    if current_rsi <= buy_rsi_threshold:
                        score = current_rsi / buy_rsi_threshold
                    elif previous_rsi > buy_rsi_threshold:
                        score = 1 - min(
                            (current_rsi - buy_rsi_threshold) / 20, 1
                        )
                    else:
                        score = 0
                elif check_name == "near_support":
                    score = float(allowed_support_distance) / float(
                        market["distance_to_support_pct"]
                    )
                elif check_name == "trend_ok":
                    trend_price = float(market["trend_price"])
                    trend_ema = float(market["trend_ema"])
                    gap = max(0, (trend_ema - trend_price) / trend_ema * 100)
                    score = 1 - min(gap / 2, 1)
                elif check_name == "reward_ok":
                    score = (
                        float(market["expected_net_reward_pct"])
                        / min_reward_threshold
                    )
                else:
                    score = max_stop_distance_threshold / float(
                        market["stop_distance_pct"]
                    )
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                score = 0
            scores.append(max(0.0, min(score, 0.99)))
        return sum(scores)

    ordered_symbols = sorted(
        target_symbols,
        key=lambda symbol: (
            symbol not in open_symbols,
            -readiness_score(symbol),
            symbol,
        ),
    )
    market_view = st.radio(
        "Market card view",
        (
            "All targets", "Closest to buy", "4–5 checks",
            "Open positions", "None",
        ),
        index=1,
        horizontal=True,
        label_visibility="collapsed",
        key="market_card_view",
    )
    if market_view == "Closest to buy":
        ordered_symbols = sorted(
            (
                symbol
                for symbol in ordered_symbols
                if symbol not in open_symbols
            ),
            key=lambda symbol: (
                -readiness_score(symbol),
                -buy_proximity_score(symbol),
                symbol,
            ),
        )[:4]
    elif market_view == "4–5 checks":
        ordered_symbols = [
            symbol
            for symbol in ordered_symbols
            if symbol not in open_symbols and readiness_score(symbol) >= 4
        ]
    elif market_view == "Open positions":
        ordered_symbols = [
            symbol for symbol in ordered_symbols if symbol in open_symbols
        ]
    elif market_view == "None":
        ordered_symbols = []
    if not ordered_symbols and market_view != "None":
        st.info(f"No markets match the {market_view.lower()} view.")
    rank_by_symbol = (
        {symbol: rank for rank, symbol in enumerate(ordered_symbols, 1)}
        if market_view == "Closest to buy"
        else {}
    )

    cards = []
    for symbol in ordered_symbols:
        market = markets.get(symbol, {})
        rank_tag = (
            f'<span class="market-rank-tag">#{rank_by_symbol[symbol]}</span>'
            if symbol in rank_by_symbol
            else ""
        )
        manual_buy_link = (
            f'<a class="market-buy-link" href="?manual_buy={quote(symbol)}#manual-buy" '
            f'target="_self" title="Select {html.escape(symbol)} for manual buy">'
            f'&#128722;</a>'
            if symbol not in open_symbols
            else ""
        )
        result = symbol_results.get(symbol, {})
        completed_trades = result.get("completed", 0)
        if market_view == "Closest to buy" and completed_trades:
            win_rate = result.get("wins", 0) / completed_trades * 100
            star_count = max(1, min(5, int((win_rate + 19.999) / 20)))
            stars = "★" * star_count
            win_rate_tag = (
                f'<div class="market-win-tag">Win rate {win_rate:.0f}% '
                f'({result.get("wins", 0)}/{completed_trades}) '
                f'<span style="color:#facc15">{stars}</span></div>'
            )
        elif market_view == "Closest to buy":
            win_rate_tag = '<div class="market-win-tag">No trade history</div>'
        else:
            win_rate_tag = ""
        tradingview_url = (
            "https://www.tradingview.com/chart/?symbol="
            + quote(f"BINANCE:{symbol}", safe="")
        )
        live_market = live_markets.get(symbol, {})
        display_price = live_market.get("price", market.get("price"))
        direction = str(live_market.get("direction", "FLAT"))
        direction_icon = {"UP": "&#9650;", "DOWN": "&#9660;"}.get(
            direction, "&#8226;"
        )
        direction_class = {
            "UP": "live-up", "DOWN": "live-down", "FLAT": "live-flat"
        }.get(direction, "live-flat")
        rsi_value = market.get("rsi")
        previous_rsi = market.get("previous_rsi")
        try:
            rsi_change = float(rsi_value) - float(previous_rsi)
        except (TypeError, ValueError):
            rsi_change = 0
        if rsi_change > 0:
            rsi_direction_icon = "&#9650;"
            rsi_direction_class = "live-up"
        elif rsi_change < 0:
            rsi_direction_icon = "&#9660;"
            rsi_direction_class = "live-down"
        else:
            rsi_direction_icon = "&#8226;"
            rsi_direction_class = "live-flat"
        previous_rsi_title = (
            f"Previous RSI: {format_market_number(previous_rsi, 2)}"
        )
        market_status = str(
            market.get("status")
            or status.get("market_statuses", {}).get(symbol, "CHECK PENDING")
        )
        signal = str(market.get("signal", "CHECK PENDING"))
        display_signal = signal
        if market_status == "WAITING FOR NEW CANDLE":
            display_signal = "SIGNAL USED · WAITING NEXT CANDLE"
        elif "SELL" in signal and symbol not in open_symbols:
            display_signal = "OVERBOUGHT · NO POSITION"
        is_open_position = symbol in open_symbols
        has_buy_checks = any(name in market for name in buy_check_names)
        buy_check_label = ""
        buy_check_html = ""
        if is_open_position:
            position = state.get("positions", {}).get(symbol, {})
            try:
                current_price = float(display_price)
                entry_price = float(position["entry"])
                stop_price = float(position["stop_loss"])
                take_profit_price = float(position["take_profit"])
                take_profit_progress = (
                    (current_price - entry_price) / (take_profit_price - entry_price)
                    if take_profit_price > entry_price else 0
                )
                stop_loss_progress = (
                    (entry_price - current_price) / (entry_price - stop_price)
                    if entry_price > stop_price else 0
                )
                rsi_exit_progress = float(rsi_value) / sell_rsi_threshold
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                take_profit_progress = stop_loss_progress = rsi_exit_progress = 0
            exit_items = []
            for label, progress, hue in (
                ("Take profit", take_profit_progress, 135),
                ("Stop loss", stop_loss_progress, 0),
                ("RSI exit", rsi_exit_progress, 30),
            ):
                progress = max(0.0, min(progress, 1.0))
                saturation = round(35 + 55 * progress)
                lightness = round(12 + 20 * progress)
                exit_items.append(
                    f'<div class="buy-check" title="{html.escape(label)}: '
                    f'{progress * 100:.0f}% close" '
                    f'style="color:#f8fafc;background:hsl({hue} {saturation}% '
                    f'{lightness}%);border-color:hsl({hue} 85% 50%)">'
                    f'&#9679; {html.escape(label)}</div>'
                )
            buy_check_html = (
                f'<div class="buy-check-list">{"".join(exit_items)}</div>'
            )
        elif has_buy_checks:
            check_labels = (
                ("rsi_recovered", "RSI recovery"),
                ("near_support", "Near support"),
                ("trend_ok", "Above trend EMA"),
                ("reward_ok", "Reward target"),
                ("stop_risk_ok", "Safe stop"),
            )
            check_items = []
            for check_name, check_label in check_labels:
                passed = bool(market.get(check_name))
                check_class = "buy-check-pass" if passed else "buy-check-wait"
                check_icon = "&#10003;" if passed else "&#10007;"
                check_state = "PASSED" if passed else "REMAINING"
                proximity = 0.0
                if not passed:
                    try:
                        if check_name == "rsi_recovered":
                            current_rsi = float(market.get("rsi"))
                            prior_rsi = float(market.get("previous_rsi"))
                            if current_rsi <= buy_rsi_threshold:
                                proximity = current_rsi / buy_rsi_threshold
                            elif prior_rsi > buy_rsi_threshold:
                                proximity = 1 - min(
                                    (current_rsi - buy_rsi_threshold) / 20, 1
                                )
                        elif check_name == "near_support":
                            distance = float(market.get("distance_to_support_pct"))
                            proximity = float(allowed_support_distance) / distance
                        elif check_name == "trend_ok":
                            trend_price = float(market.get("trend_price"))
                            trend_ema = float(market.get("trend_ema"))
                            gap = max(0, (trend_ema - trend_price) / trend_ema * 100)
                            proximity = 1 - min(gap / 2, 1)
                        elif check_name == "reward_ok":
                            reward = float(market.get("expected_net_reward_pct"))
                            proximity = reward / min_reward_threshold
                        elif check_name == "stop_risk_ok":
                            stop_distance = float(market.get("stop_distance_pct"))
                            proximity = max_stop_distance_threshold / stop_distance
                    except (TypeError, ValueError, ZeroDivisionError):
                        proximity = 0.0
                proximity = max(0.0, min(proximity, 0.95))
                wait_style = ""
                if not passed:
                    hue = round(45 * proximity)
                    lightness = round(20 + 12 * proximity)
                    wait_style = (
                        f' style="background:hsl({hue} 82% {lightness}%);'
                        f'border-color:hsl({hue} 90% 55%)"'
                    )
                check_items.append(
                    f'<div class="buy-check {check_class}"{wait_style} '
                    f'title="{html.escape(check_label)}: {check_state}">'
                    f'{check_icon} {html.escape(check_label)}</div>'
                )
            buy_check_html = (
                f'<div class="buy-check-list">{"".join(check_items)}</div>'
            )
        if "ERROR" in market_status:
            color_class = "market-check-error"
        elif market_status == "WAITING FOR NEW CANDLE":
            color_class = "market-check-monitoring"
        elif "BUY" in signal:
            color_class = "market-check-buy"
        elif "SELL" in signal and symbol in open_symbols:
            color_class = "market-check-sell"
        elif market_status == "MONITORING":
            color_class = "market-check-monitoring"
        else:
            color_class = "market-check-neutral"
        flash_class = "market-check-flash" if should_flash else ""
        if is_open_position:
            position = state.get("positions", {}).get(symbol, {})
            try:
                level_current_price = float(display_price)
                level_take_profit = float(position["take_profit"])
                level_stop_loss = float(position["stop_loss"])
                take_profit_remaining = max(
                    (level_take_profit - level_current_price)
                    / level_current_price * 100,
                    0,
                )
                stop_loss_remaining = max(
                    (level_current_price - level_stop_loss)
                    / level_current_price * 100,
                    0,
                )
                rsi_remaining = max(sell_rsi_threshold - float(rsi_value), 0)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                take_profit_remaining = stop_loss_remaining = rsi_remaining = None
            levels_html = (
                f'<details class="market-check-levels"><summary>🟢 Take profit</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Entry price<span>'
                f'{format_market_number(position.get("entry"))}</span></div>'
                f'<div class="market-check-stat">Current price<span>'
                f'{format_market_number(display_price)}</span></div>'
                f'<div class="market-check-stat">Sell at<span>'
                f'{format_market_number(position.get("take_profit"))}</span></div>'
                f'<div class="market-check-stat">Remaining<span>'
                f'{format_market_number(take_profit_remaining, 2)}%</span></div>'
                f'</div></details>'
                f'<details class="market-check-levels"><summary>🔴 Stop loss</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Entry price<span>'
                f'{format_market_number(position.get("entry"))}</span></div>'
                f'<div class="market-check-stat">Current price<span>'
                f'{format_market_number(display_price)}</span></div>'
                f'<div class="market-check-stat">Sell at<span>'
                f'{format_market_number(position.get("stop_loss"))}</span></div>'
                f'<div class="market-check-stat">Buffer remaining<span>'
                f'{format_market_number(stop_loss_remaining, 2)}%</span></div>'
                f'</div></details>'
                f'<details class="market-check-levels"><summary>🟠 RSI exit</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Current RSI<span>'
                f'{format_market_number(rsi_value, 2)}</span></div>'
                f'<div class="market-check-stat">Sell at<span>'
                f'&ge; {sell_rsi_threshold:g}</span></div>'
                f'<div class="market-check-stat">Remaining<span>'
                f'{format_market_number(rsi_remaining, 2)} points</span></div>'
                f'</div></details>'
            )
        else:
            levels_html = (
                f'<details class="market-check-levels"><summary>🟠 RSI recovery</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Previous RSI<span>'
                f'{format_market_number(market.get("previous_rsi"), 2)}</span></div>'
                f'<div class="market-check-stat">Current RSI<span>'
                f'{format_market_number(market.get("rsi"), 2)}</span></div>'
                f'<div class="market-check-stat">Recovery level<span>'
                f'Cross above {buy_rsi_threshold:g}</span></div>'
                f'</div></details>'
                f'<details class="market-check-levels"><summary>🟡 Near support</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Current price<span>'
                f'{format_market_number(display_price)}</span></div>'
                f'<div class="market-check-stat">Support<span>'
                f'{format_market_number(market.get("support"))}</span></div>'
                f'<div class="market-check-stat">Distance<span>'
                f'{format_market_number(market.get("distance_to_support_pct"), 2)}%'
                f'</span></div>'
                f'<div class="market-check-stat">Allowed<span>'
                f'&le; {allowed_support_distance}%</span></div>'
                f'</div></details>'
                f'<details class="market-check-levels"><summary>🔵 Trend</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Trend price<span>'
                f'{format_market_number(market.get("trend_price"))}</span></div>'
                f'<div class="market-check-stat">Trend EMA<span>'
                f'{format_market_number(market.get("trend_ema"))}</span></div>'
                f'<div class="market-check-stat">Timeframe<span>'
                f'{html.escape(str(market.get("trend_interval", "N/A")))}</span></div>'
                f'<div class="market-check-stat">Required<span>Price above EMA</span></div>'
                f'</div></details>'
                f'<details class="market-check-levels"><summary>🟣 Reward</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Suggested SL<span>'
                f'{format_market_number(market.get("suggested_sl"))}</span></div>'
                f'<div class="market-check-stat">Suggested TP<span>'
                f'{format_market_number(market.get("suggested_tp"))}</span></div>'
                f'<div class="market-check-stat">Net reward<span>'
                f'{format_market_number(market.get("expected_net_reward_pct"), 3)}%'
                f'</span></div>'
                f'<div class="market-check-stat">Required<span>'
                f'&ge; {min_reward_threshold:g}%</span></div>'
                f'</div></details>'
                f'<details class="market-check-levels"><summary>🛡️ Stop risk</summary>'
                f'<div class="market-check-grid">'
                f'<div class="market-check-stat">Suggested SL<span>'
                f'{format_market_number(market.get("suggested_sl"))}</span></div>'
                f'<div class="market-check-stat">Stop distance<span>'
                f'{format_market_number(market.get("stop_distance_pct"), 3)}%'
                f'</span></div>'
                f'<div class="market-check-stat">Maximum allowed<span>'
                f'&le; {max_stop_distance_threshold:g}%</span></div>'
                f'<div class="market-check-stat">Action<span>Skip if wider</span></div>'
                f'</div></details>'
            )
        cards.append(
            f'<div class="market-check-card {color_class} {flash_class}">'
            f'<div class="market-check-head">'
            f'<span class="market-check-symbol"><a '
            f'href="{html.escape(tradingview_url)}" target="_blank" '
            f'rel="noopener noreferrer" '
            f'title="Open {html.escape(symbol)} on TradingView">'
            f'{html.escape(symbol)} &#8599;</a>{rank_tag}{manual_buy_link}</span>'
            f'<span class="market-check-status" title="{html.escape(market_status)}">'
            f'{html.escape(market_status)}</span></div>'
            f'<div class="market-check-signal">'
            f'{html.escape(display_signal + buy_check_label)}</div>'
            f'{win_rate_tag}'
            f'{buy_check_html}'
            f'<div class="market-check-grid">'
            f'<div class="market-check-stat">Price'
            f'<span class="{direction_class}">{direction_icon} '
            f'{format_market_number(display_price)}</span></div>'
            f'<div class="market-check-stat">RSI<span '
            f'class="{rsi_direction_class}" '
            f'title="{html.escape(previous_rsi_title)}">{rsi_direction_icon} '
            f'{format_market_number(rsi_value, 2)}</span></div></div>'
            f'{levels_html}</div>'
        )
    st.markdown(
        f'<div class="market-check-row">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
    buyable_symbols = list(target_symbols)
    requested_buy_symbol = str(st.query_params.get("manual_buy", "")).upper()
    valid_buy_request = requested_buy_symbol in buyable_symbols
    if (
        valid_buy_request
        and st.session_state.get("manual_buy_query_symbol")
        != requested_buy_symbol
    ):
        st.session_state["manual_buy_symbol"] = requested_buy_symbol
        st.session_state["manual_buy_query_symbol"] = requested_buy_symbol
    st.markdown('<div id="manual-buy"></div>', unsafe_allow_html=True)
    with st.expander("🛒 Manual buy", expanded=valid_buy_request):
        st.warning(
            "Manual buy skips entry checks and places a real market order. "
            "Final price may vary."
        )
        selected_symbol = st.selectbox(
            "Coin",
            buyable_symbols,
            key="manual_buy_symbol",
            disabled=not buyable_symbols,
        )
        if selected_symbol in open_symbols:
            st.info(
                "Buy more: quantity will be added and entry, stop loss, and "
                "take profit will be recalculated."
            )
        try:
            available_usdt = float(status.get("available_usdt"))
            max_open_positions = int(
                config.get(
                    "max_open_positions",
                    status.get("max_open_positions", 1),
                )
            )
            suggested_buy_amount = max(
                1.0, round(available_usdt / max_open_positions, 2)
            )
        except (TypeError, ValueError, ZeroDivisionError):
            suggested_buy_amount = 20.0
        previous_suggestion = st.session_state.get(
            "manual_buy_suggested_amount"
        )
        if (
            "manual_buy_amount" not in st.session_state
            or st.session_state["manual_buy_amount"] == previous_suggestion
        ):
            st.session_state["manual_buy_amount"] = suggested_buy_amount
        st.session_state["manual_buy_suggested_amount"] = suggested_buy_amount
        manual_buy_amount = st.number_input(
            "Buy amount (USDT)",
            min_value=1.0,
            step=1.0,
            key="manual_buy_amount",
            disabled=not buyable_symbols,
            help="Default is available USDT divided by maximum open positions.",
        )
        trading_enabled = bool(status.get("trading_enabled", False))
        trading_on_hold = bool(
            config.get("trading_on_hold", status.get("trading_on_hold", False))
        )
        if not trading_enabled:
            st.caption("Trading is disabled, so manual buying is unavailable.")
        elif trading_on_hold:
            st.caption("New buys are on hold, so manual buying is unavailable.")
        if st.button(
            (
                "Confirm buy more"
                if selected_symbol in open_symbols else "Confirm market buy"
            ),
            key="confirm_manual_buy",
            type="primary",
            disabled=(
                not buyable_symbols or not trading_enabled or trading_on_hold
            ),
        ):
            queue_buy_request(
                selected_symbol, status.get("environment"), manual_buy_amount
            )
            st.success(
                f"{manual_buy_amount:.2f} USDT buy request queued. "
                "It expires in 30 seconds."
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
    with st.expander("🤖 Full AI analysis", expanded=False):
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
def render_max_status_strip():
    state = read_state()
    status = read_json(STATUS_FILE, {})
    config = read_json(CONFIG_FILE, {})
    live_prices = read_json(LIVE_PRICE_FILE, {})
    if live_prices.get("environment") != status.get("environment"):
        live_prices = {}
    live_markets = live_prices.get("prices", {})
    transactions = read_transactions()
    notify_new_transaction(transactions)
    history = transaction_frame(transactions)
    today = datetime.now().astimezone().date()
    today_realized = 0.0
    today_wins = 0
    today_completed = 0
    if not history.empty:
        sells = history[
            (history["Side"] == "SELL") & (history["Time"].dt.date == today)
        ]
        today_completed = len(sells)
        today_wins = int(
            (sells["Est. Net P&L (USDT)"].fillna(0) > 0).sum()
        )
        today_realized = float(sells["Est. Net P&L (USDT)"].sum())
    win_rate = (
        f"{today_wins / today_completed * 100:.1f}%"
        if today_completed else "N/A"
    )
    today_unrealized = 0.0
    status_markets = status.get("markets", {})
    fee_pct = float(config.get("estimated_round_trip_fee_pct", 0.2)) / 2
    for symbol, position in state.get("positions", {}).items():
        try:
            opened_at = position.get("opened_at")
            if not opened_at or datetime.fromtimestamp(
                float(opened_at)
            ).astimezone().date() != today:
                continue
            entry = float(position["entry"])
            quantity = float(position["quantity"])
            current = float(live_markets.get(symbol, {}).get(
                "price", status_markets.get(symbol, {}).get("price", entry)
            ))
            today_unrealized += (
                (current - entry) * quantity
                - (entry + current) * quantity * fee_pct / 100
            )
        except (KeyError, TypeError, ValueError):
            continue
    status_age = time.time() - float(status.get("updated_at", 0) or 0)
    online = 0 <= status_age <= 120
    online_class = "max-status-online" if online else "max-status-offline"
    online_text = "● ONLINE" if online else "● OFFLINE"
    market_regime = str(
        status.get("market_overview", {}).get("regime", "WAITING")
    ).upper()
    if "WEAK" in market_regime:
        market_class = "max-status-market-weak"
    elif "POSITIVE" in market_regime:
        market_class = "max-status-market-positive"
    elif "QUIET" in market_regime:
        market_class = "max-status-market-quiet"
    else:
        market_class = ""
    realized_class = "pnl-positive" if today_realized >= 0 else "pnl-negative"
    unrealized_class = "pnl-positive" if today_unrealized >= 0 else "pnl-negative"
    st.markdown(
        f"""
        <div class="max-status-strip">
          <span class="max-status-item max-status-win">Win rate <strong>{win_rate}</strong></span>
          <span class="max-status-item">Realized <strong class="{realized_class}">{today_realized:+.4f}</strong></span>
          <span class="max-status-item">Unrealized <strong class="{unrealized_class}">{today_unrealized:+.4f}</strong></span>
          <span class="max-status-market {market_class}">MARKET · {html.escape(market_regime)}</span>
          <span class="{online_class}">{online_text}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every=5)
def render_top_bar(show_more_metrics=True):
    state = read_state()
    status = read_json(STATUS_FILE, {})
    config = read_json(CONFIG_FILE, {})
    live_prices = read_json(LIVE_PRICE_FILE, {})
    if live_prices.get("environment") != status.get("environment"):
        live_prices = {}
    live_markets = live_prices.get("prices", {})
    transactions = read_transactions()
    notify_new_transaction(transactions)
    history = transaction_frame(transactions)
    positions = state.get("positions", {})
    available = status.get("available_usdt")
    binance_portfolio = status.get("total_portfolio_usdt")
    unpriced_assets = status.get("portfolio_unpriced_assets", [])
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
    open_unrealized_pnl = 0.0
    usdt_in_trades = 0.0
    entry_exposure = 0.0
    today_win_rate = None
    today_completed_trades = 0
    today_wins = 0
    all_win_rate = None
    if not history.empty:
        sells = history[history["Side"] == "SELL"]
        total_pnl = float(sells["Est. Net P&L (USDT)"].sum())
        today_sells = sells[
            sells["Time"].dt.date == datetime.now().astimezone().date()
        ]
        today_pnl = float(today_sells["Est. Net P&L (USDT)"].sum())
        if not today_sells.empty:
            today_completed_trades = len(today_sells)
            today_wins = int(
                (today_sells["Est. Net P&L (USDT)"].fillna(0) > 0).sum()
            )
            today_win_rate = float(
                (today_sells["Est. Net P&L (USDT)"].fillna(0) > 0).mean()
                * 100
            )
        if not sells.empty:
            all_win_rate = float(
                (sells["Est. Net P&L (USDT)"].fillna(0) > 0).mean() * 100
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
            entry_exposure += entry * quantity
            one_way_fee_pct = float(
                config.get("estimated_round_trip_fee_pct", 0.2)
            ) / 2
            position_net_pnl = (
                (current - entry) * quantity
                - entry * quantity * one_way_fee_pct / 100
                - current * quantity * one_way_fee_pct / 100
            )
            open_unrealized_pnl += position_net_pnl
            opened_at = position.get("opened_at")
            if (
                opened_at
                and datetime.fromtimestamp(float(opened_at)).astimezone().date()
                == datetime.now().astimezone().date()
            ):
                today_unrealized_pnl += position_net_pnl
        except (KeyError, TypeError, ValueError):
            continue
    active_interval = str(status.get("interval") or config.get("interval", "15m"))
    market_overview = status.get("market_overview", {})
    market_regime = str(market_overview.get("regime", "WAITING FOR DATA"))
    if "WEAK" in market_regime:
        market_regime_style = " market-regime-weak"
    elif "POSITIVE" in market_regime:
        market_regime_style = " market-regime-positive"
    elif "QUIET" in market_regime:
        market_regime_style = " market-regime-quiet"
    else:
        market_regime_style = ""
    market_regime_detail = (
        f"{market_overview.get('expectation', 'Waiting for Binance market breadth.')} "
        f"Sample: {market_overview.get('sample_size', 0)} | "
        f"Up: {market_overview.get('up_pct', 'N/A')}% | "
        f"Down: {market_overview.get('down_pct', 'N/A')}% | "
        f"Active: {market_overview.get('active_pct', 'N/A')}% | "
        f"Median change: {market_overview.get('median_change_pct', 'N/A')}% | "
        f"Median range: {market_overview.get('median_range_pct', 'N/A')}% | "
        f"{market_overview.get('formula', '')}"
    )
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
    status_updated_at = status.get("updated_at")
    bot_health_extra = ""
    if status_updated_at:
        status_age = max(0, int(time.time() - float(status_updated_at)))
        if status_age <= 120:
            bot_health = "ONLINE"
            bot_health_style = " bot-health-online"
            bot_health_card_style = "bot-health-card-online"
        elif status_age <= 300:
            bot_health = "DELAYED"
            bot_health_style = " bot-health-delayed"
            bot_health_card_style = "bot-health-card-delayed"
        else:
            bot_health = "OFFLINE"
            bot_health_style = " bot-health-offline"
            bot_health_card_style = "bot-health-card-offline"
            last_online = datetime.fromtimestamp(
                float(status_updated_at)
            ).astimezone().strftime("%d %b %H:%M")
            offline_since = datetime.fromtimestamp(
                float(status_updated_at) + 300
            ).astimezone().strftime("%d %b %H:%M")
            if status_age < 3600:
                offline_age = f"{max(1, status_age // 60)}m ago"
            elif status_age < 86400:
                offline_age = f"{status_age // 3600}h ago"
            else:
                offline_age = f"{status_age // 86400}d ago"
            bot_health_extra = (
                f'<div class="bot-health-last">Offline since ~'
                f'{html.escape(offline_since)}</div>'
                f'<div class="bot-health-last">Last seen '
                f'{html.escape(last_online)} · {html.escape(offline_age)}</div>'
            )
        bot_health_detail = f"Last completed market check {status_age} seconds ago."
    else:
        status_age = None
        bot_health = "WAITING"
        bot_health_style = " bot-health-offline"
        bot_health_card_style = "bot-health-card-offline"
        bot_health_extra = '<div class="bot-health-last">Last online unknown</div>'
        bot_health_detail = "No completed market check is available."
    tags = (
        f'<span class="target-tag">INTERVAL &middot; '
        f'{html.escape(active_interval)}</span>'
        f'<span class="market-regime-tag{market_regime_style}" '
        f'title="{html.escape(market_regime_detail)}">MARKET &middot; '
        f'{html.escape(market_regime)}</span>'
        f'<span class="ai-brief-tag{ai_style}" '
        f'title="Open AI Advisor in the sidebar">AI &middot; '
        f'{html.escape(ai_headline)}</span>'
        f'<span class="market-regime-tag{bot_health_style}" '
        f'title="{html.escape(bot_health_detail)}">BOT &middot; '
        f'{html.escape(bot_health)}</span>'
    )
    today_class = "pnl-positive" if today_pnl >= 0 else "pnl-negative"
    today_unrealized_class = (
        "pnl-positive" if today_unrealized_pnl >= 0 else "pnl-negative"
    )
    total_class = "pnl-positive" if total_pnl >= 0 else "pnl-negative"
    open_unrealized_class = (
        "pnl-positive" if open_unrealized_pnl >= 0 else "pnl-negative"
    )
    total_net_pnl = total_pnl + open_unrealized_pnl
    total_net_class = "pnl-positive" if total_net_pnl >= 0 else "pnl-negative"
    available_text = f"{float(available):,.2f}" if available is not None else "N/A"
    tracked_total_text = (
        f"{float(available) + usdt_in_trades:,.2f}"
        if available is not None
        else "N/A"
    )
    binance_portfolio_text = (
        f"{float(binance_portfolio):,.2f}"
        if binance_portfolio is not None
        else "N/A"
    )
    binance_portfolio_note = (
        "All nonzero Spot balances converted to USDT, including locked assets."
        + (
            " Unpriced assets excluded: " + ", ".join(map(str, unpriced_assets))
            if unpriced_assets
            else ""
        )
    )
    trade_amount_text = (
        f"{float(trade_amount):,.2f}" if trade_amount is not None else "N/A"
    )
    today_win_rate_text = (
        f"{today_win_rate:.1f}%" if today_win_rate is not None else "N/A"
    )
    today_win_rate_class = (
        "pnl-positive"
        if today_win_rate is not None and today_win_rate >= 50
        else "pnl-negative"
        if today_win_rate is not None
        else ""
    )
    all_win_rate_text = (
        f"{all_win_rate:.1f}%" if all_win_rate is not None else "N/A"
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
            <div class="summary-item"><div class="summary-label">Open / max positions</div><div class="summary-value">{len(positions)} / {max_open_positions}</div></div>
            <div class="summary-item"><div class="summary-label">Exposure / max</div><div class="summary-value">{entry_exposure:,.2f} / {float(maximum):,.2f}</div></div>
            <div class="summary-item"><div class="summary-label">Today net realized P&amp;L</div><div class="summary-value {today_class}">{today_pnl:+,.4f}</div></div>
            <div class="summary-item" title="Estimated net P&amp;L after both fees for positions opened today"><div class="summary-label">Today net unrealized P&amp;L</div><div class="summary-value {today_unrealized_class}">{today_unrealized_pnl:+,.4f}</div></div>
            <div class="summary-item" title="{today_wins} net wins from {today_completed_trades} completed trades today"><div class="summary-label">Today win rate</div><div class="summary-value {today_win_rate_class}">{today_win_rate_text}</div></div>
            <div class="summary-item {bot_health_card_style}" title="{html.escape(bot_health_detail)}"><div class="summary-label">Bot health</div><div class="summary-value">{html.escape(bot_health)}</div>{bot_health_extra}</div>
          </div>
          <div class="summary-tags">{tags}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not show_more_metrics:
        return
    with st.expander("📈 More account and performance metrics", expanded=False):
        st.markdown(
            f"""
            <div class="secondary-summary-grid">
              <div class="summary-item" title="Current market price multiplied by tracked quantity"><div class="summary-label">USDT in trades</div><div class="summary-value">{usdt_in_trades:,.2f}</div></div>
              <div class="summary-item" title="Available USDT plus tracked open positions"><div class="summary-label">Bot tracked total</div><div class="summary-value">{tracked_total_text}</div></div>
              <div class="summary-item" title="{html.escape(binance_portfolio_note)}"><div class="summary-label">Binance Spot total</div><div class="summary-value">{binance_portfolio_text}</div></div>
              <div class="summary-item"><div class="summary-label">Per-trade max</div><div class="summary-value">{trade_amount_text}</div></div>
              <div class="summary-item"><div class="summary-label">All win rate</div><div class="summary-value">{all_win_rate_text}</div></div>
              <div class="summary-item"><div class="summary-label">Open net unrealized P&amp;L</div><div class="summary-value {open_unrealized_class}">{open_unrealized_pnl:+,.4f}</div></div>
              <div class="summary-item"><div class="summary-label">Total net realized P&amp;L</div><div class="summary-value {total_class}">{total_pnl:+,.4f}</div></div>
              <div class="summary-item"><div class="summary-label">Combined net P&amp;L</div><div class="summary-value {total_net_class}">{total_net_pnl:+,.4f}</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


@st.fragment(run_every=5)
def render_dashboard(open_trades_only=False):
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

    if not open_trades_only:
        open_title_column, open_focus_column = st.columns([4, 1])
        with open_title_column:
            st.subheader("📈 Open trades")
        with open_focus_column:
            if st.button(
                "⛶ Open trades only",
                key="open_trades_section_focus_button",
                type="primary",
                width="stretch",
            ):
                st.session_state["open_trades_only"] = True
                st.rerun()

    if positions:
        position_items = list(positions.items())
        cards_per_row = 3 if open_trades_only else 2
        for start in range(0, len(position_items), cards_per_row):
            columns = st.columns(cards_per_row, gap="small")
            for column, (symbol, position) in zip(
                columns, position_items[start : start + cards_per_row]
            ):
                with column:
                    with st.container(border=True):
                        market = status.get("markets", {}).get(symbol, {})
                        live_market = live_markets.get(symbol, {})
                        position_market = {**market, **live_market}
                        render_position_progress(
                            symbol, position,
                            position_market.get("price"),
                            bool(status.get("trading_enabled", False)),
                            status.get("environment", state["environment"]),
                            position_market,
                            open_trades_only,
                        )
    elif open_trades_only:
        st.info("No open trades are currently being monitored.")
    if open_trades_only:
        return
    render_results_by_symbol(history)
    render_market_suggestions(status)
    render_targets_outside_watchlist(status, positions)

    if history.empty:
        st.info("No filled transactions have been recorded yet.")
        return
    st.subheader("🧾 Transactions")
    filtered = filter_history(history).sort_values("Time", ascending=False)
    detail_columns = [
        "Time", "Environment", "Market status", "Side", "Result", "Symbol", "Quantity", "Price",
        "Value", "Est. Fee (USDT)", "Quote asset", "Est. P&L (USDT)",
        "Est. Net P&L (USDT)", "Reason", "Order ID",
    ]
    filtered = filtered.copy()
    filtered["Result"] = filtered.apply(transaction_result, axis=1)
    for column in detail_columns:
        if column not in filtered:
            filtered[column] = None
    detail_frame = filtered[detail_columns].copy()
    download_frame = detail_frame.copy()
    compact_frame = pd.DataFrame(index=filtered.index)
    compact_frame["Local time"] = filtered["Time"].map(format_transaction_time)
    compact_frame["Coin"] = filtered["Symbol"].map(
        lambda value: f"🪙 {str(value).upper()}"
    )
    compact_frame["Action"] = filtered["Side"].map(transaction_action)
    compact_frame["Outcome"] = filtered["Result"].map(transaction_outcome)
    compact_frame["Market"] = filtered["Market status"].map(market_status_icon)
    compact_frame["Amount"] = filtered["Value"].map(format_usdt)
    compact_frame["Fee"] = filtered["Est. Fee (USDT)"].map(
        lambda value: format_usdt(value, approximate=True)
    )
    compact_frame["Net P&L"] = filtered["Est. Net P&L (USDT)"].map(
        lambda value: format_usdt(value, signed=True, approximate=True)
    )
    compact_frame["Reason"] = filtered["Reason"].map(transaction_reason_icon)
    styled_frame = compact_frame.style.apply(style_transaction_row, axis=1)
    st.caption(
        f"Showing {len(compact_frame):,} transaction"
        f"{'s' if len(compact_frame) != 1 else ''} · times use your local timezone · "
        "≈ values use estimated fees"
    )
    st.dataframe(
        styled_frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Local time": st.column_config.TextColumn("🕒 Local time", width="medium"),
            "Coin": st.column_config.TextColumn("🪙 Coin", width="small"),
            "Action": st.column_config.TextColumn("Action", width="small"),
            "Outcome": st.column_config.TextColumn("Result", width="small"),
            "Market": st.column_config.TextColumn("🌐 Market", width="medium"),
            "Amount": st.column_config.TextColumn("💵 Amount", width="small"),
            "Fee": st.column_config.TextColumn("🧾 Fee", width="small"),
            "Net P&L": st.column_config.TextColumn("📊 Net P&L", width="small"),
            "Reason": st.column_config.TextColumn("💡 Reason", width="medium"),
        },
    )
    with st.expander("🧾 Detailed transaction columns", expanded=False):
        detail_frame["Time"] = detail_frame["Time"].map(format_transaction_time)
        detail_frame["Symbol"] = detail_frame["Symbol"].map(
            lambda value: f"🪙 {str(value).upper()}"
        )
        detail_frame["Side"] = detail_frame["Side"].map(transaction_action)
        detail_frame["Result"] = detail_frame["Result"].map(transaction_outcome)
        detail_frame["Market status"] = detail_frame["Market status"].map(
            market_status_icon
        )
        detail_frame["Reason"] = detail_frame["Reason"].map(
            transaction_reason_icon
        )
        detailed_style = detail_frame.style.apply(
            style_transaction_row, axis=1
        ).format(
            {
                "Quantity": smart_number,
                "Price": smart_number,
                "Value": format_usdt,
                "Est. Fee (USDT)": lambda value: format_usdt(
                    value, approximate=True
                ),
                "Est. P&L (USDT)": lambda value: format_usdt(
                    value, signed=True, approximate=True
                ),
                "Est. Net P&L (USDT)": lambda value: format_usdt(
                    value, signed=True, approximate=True
                ),
            },
            na_rep="—",
        )
        st.dataframe(detailed_style, hide_index=True, width="stretch")
    st.download_button(
        "⬇️ Download filtered transactions",
        download_frame.to_csv(index=False),
        file_name="binance_filtered_transactions.csv",
        mime="text/csv",
    )


open_trades_only = bool(st.session_state.get("open_trades_only", False))
if open_trades_only:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"], header {display:none!important}
        [data-testid="stMainBlockContainer"] {max-width:100%!important;
          padding:2.7rem .6rem .2rem!important}
        .dashboard-title,.dashboard-subtitle {display:none!important}
        [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {
          gap:.35rem}
        [data-testid="stMainBlockContainer"] [data-testid="stColumn"] {
          padding:0!important}
        .position-candle-wrap {margin:.05rem 0!important}
        .position-candle-title {margin-bottom:.05rem!important}
        .position-progress-wrap-max {margin:.12rem 0 .05rem!important}
        .position-progress-wrap-max .position-progress-track {height:1.6rem!important}
        .position-progress-wrap-max .position-progress-marker {
          height:2.05rem!important;top:-.2rem!important}
        .position-progress-wrap-max .position-current-label {top:.25rem!important}
        .position-progress-labels,.position-progress-state {margin-top:.03rem!important}
        [data-testid="stMarkdownContainer"]:has(.max-status-strip) {
          position:fixed;top:.45rem;right:3.7rem;z-index:1002;width:auto}
        [data-testid="stMarkdownContainer"]:has(.max-status-strip) .max-status-strip {
          position:static}
        .st-key-max_view_exit {position:fixed;top:.45rem;right:.7rem;
          width:2.5rem;z-index:1002}
        .st-key-max_view_exit button {min-height:2.2rem!important;padding:.2rem!important}
        </style>
        """,
        unsafe_allow_html=True,
    )
 
if open_trades_only:
    render_max_status_strip()
    if st.button(
        "↙",
        key="max_view_exit",
        help="Return to full dashboard",
        type="primary",
    ):
        st.session_state["open_trades_only"] = False
        st.rerun()
    render_dashboard(open_trades_only=True)
else:
    render_top_bar()
    render_market_check_cards()
    render_dashboard()
with st.sidebar:
    st.header("Version 2 AI")
    render_ai_advisor()
    st.header("Bot controls")
    render_settings_panel()
    st.header("Alerts")
    action_sounds_enabled = st.toggle(
        "Action sounds", value=True, key="action_sounds_enabled"
    )
    demo_sound = st.selectbox(
        "Sound demo",
        ("Buy", "Profit", "Loss", "Break-even"),
        disabled=not action_sounds_enabled,
    )
    if st.button(
        "Play demo sound",
        disabled=not action_sounds_enabled,
        width="stretch",
    ):
        demo_sound_kinds = {
            "Buy": "buy",
            "Profit": "profit",
            "Loss": "loss",
            "Break-even": "neutral",
        }
        play_action_sound({}, sound_kind=demo_sound_kinds[demo_sound])
    st.caption(
        "Buy, profit, loss, and break-even actions use different tones. "
        "If sounds are blocked, select the test button once to allow audio."
    )
