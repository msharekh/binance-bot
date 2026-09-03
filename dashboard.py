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
st.caption("Binance Spot · refreshes every 5 seconds")
st.markdown(
    """
    <style>
    .dashboard-title {font-size:1.65rem!important;line-height:1.15!important;
      margin:.1rem 0 .05rem!important;padding:0!important}
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
    .position-stats {display:grid;grid-template-columns:repeat(2,1fr);gap:.3rem;
      margin-top:.15rem}
    .position-stat {padding:.3rem .4rem;border-radius:.35rem;background:#0f172a}
    .position-label {color:#94a3b8;font-size:.67rem;text-transform:uppercase;font-weight:700}
    .position-value {color:#e2e8f0;font-size:.83rem;font-weight:750}
    .position-progress-wrap {margin:.55rem 0 .2rem}
    .position-progress-track {position:relative;height:1.15rem;border-radius:999px;
      border:1px solid #64748b;box-shadow:inset 0 1px 3px rgba(0,0,0,.45)}
    .position-progress-marker {position:absolute;top:-.28rem;width:.28rem;height:1.7rem;
      border-radius:999px;background:#f8fafc;border:1px solid #020617;
      box-shadow:0 0 7px rgba(255,255,255,.9);transform:translateX(-50%)}
    .position-entry-marker {position:absolute;top:0;width:2px;height:100%;
      background:rgba(255,255,255,.55);transform:translateX(-50%)}
    .position-progress-unfilled {position:absolute;top:0;right:0;height:100%;
      background:#020617;border-radius:0 999px 999px 0}
    .position-progress-labels {display:flex;justify-content:space-between;gap:.5rem;
      margin-top:.18rem;color:#cbd5e1;font-size:.68rem;font-weight:750}
    .position-progress-state {text-align:center;color:#e2e8f0;font-size:.72rem;
      font-weight:850;margin-top:.08rem}
    .sticky-summary {position:sticky;top:2.8rem;z-index:999;padding:.72rem;
      margin:.2rem 0 .7rem;border-radius:.75rem;background:rgba(2,6,23,.96);
      border:1px solid #334155;box-shadow:0 8px 24px rgba(0,0,0,.28)}
    .summary-grid {display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:.45rem}
    .secondary-summary-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
      gap:.45rem}
    .summary-item {padding:.42rem .55rem;border-radius:.5rem;background:#0f172a}
    .summary-label {color:#cbd5e1;font-size:.9rem;text-transform:uppercase;font-weight:800}
    .summary-value {color:#f8fafc;font-size:1.5rem;font-weight:900;line-height:1.2}
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
    estimated_round_trip_fee_pct = float(
        strategy_value("estimated_round_trip_fee_pct", 0.20)
    )
    atr_sl_multiplier = float(strategy_value("atr_sl_multiplier", 1.5))
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
            f"{trend_ema_period} · net TP ≥ {min_net_reward_pct:.2f}%"
        )
        st.caption(
            f"Sell: SL {atr_sl_multiplier:g} ATR · TP {risk_reward_ratio:g}R · "
            f"RSI ≥ {sell_rsi_threshold:g}"
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
                        "estimated_round_trip_fee_pct": str(
                            estimated_round_trip_fee_pct
                        ),
                        "atr_sl_multiplier": str(atr_sl_multiplier),
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
            with buy_tab:
                st.caption("All four checks must pass before a new buy.")
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
                        "estimated_round_trip_fee_pct": str(
                            estimated_fee_input
                        ),
                        "atr_sl_multiplier": str(atr_sl_multiplier_input),
                        "risk_reward_ratio": str(risk_reward_ratio_input),
                        "sell_rsi_threshold": str(sell_rsi_threshold_input),
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
    return history


def render_position_progress(
    symbol, position, current_price, trading_enabled, environment,
    live_market=None,
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
    live_market = live_market or {}
    last_progress_at = live_market.get("last_progress_at")
    interval_minutes = INTERVAL_MINUTES.get(
        read_json(CONFIG_FILE, {}).get("interval", "5m"), 5
    )
    stall_text = "🟢 Tracking progress"
    if last_progress_at:
        stalled_minutes = max(
            0, int((datetime.now().timestamp() - float(last_progress_at)) / 60)
        )
        if stalled_minutes >= interval_minutes * 6:
            stall_text = f"🔴 Stalled {stalled_minutes}m"
        elif stalled_minutes >= interval_minutes * 3:
            stall_text = f"🟡 Slow {stalled_minutes}m"
        else:
            stall_text = f"🟢 Progress {stalled_minutes}m ago"
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
    progress_pct = progress * 100
    entry_pct = ((entry - stop_loss) / span * 100) if span > 0 else 50
    st.markdown(
        f"""
        <div class="position-progress-wrap">
          <div class="position-progress-track" style="background:linear-gradient(90deg,#b91c1c 0%,#f59e0b {entry_pct:.2f}%,#16a34a 100%)">
            <span class="position-progress-unfilled" style="width:{100 - progress_pct:.2f}%"></span>
            <span class="position-entry-marker" style="left:{entry_pct:.2f}%" title="Entry"></span>
            <span class="position-progress-marker" style="left:{progress_pct:.2f}%" title="Current price"></span>
          </div>
          <div class="position-progress-labels"><span>SL {stop_loss:.8f}</span><span>Entry {entry:.8f}</span><span>TP {take_profit:.8f}</span></div>
          <div class="position-progress-state">{html.escape(stall_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Position details", expanded=False):
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
                          <div class="suggestion-stat">Price: {suggestion['price']:.8f}</div>
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
                if "SELL" in str(market.get("signal", "")):
                    reasons.append("Currently overbought")
                checks = sum(
                    bool(market.get(name))
                    for name in (
                        "rsi_recovered", "near_support", "trend_ok", "reward_ok"
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
                          <div class="target-review-reason">Current buy checks: {checks}/4</div>
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
    with st.popover("Filters"):
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
    allowed_support_distance = format_market_number(
        config.get("max_support_distance_pct", 0.5), 2
    )
    buy_rsi_threshold = float(config.get("buy_rsi_recovery", 40))
    min_reward_threshold = float(config.get("min_net_reward_pct", 0.6))
    sell_rsi_threshold = float(config.get("sell_rsi_threshold", 65))
    buy_check_names = ("rsi_recovered", "near_support", "trend_ok", "reward_ok")
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
            "All targets", "Closest to buy", "3–4 checks",
            "Open positions", "None",
        ),
        index=4,
        horizontal=True,
        label_visibility="collapsed",
        key="market_card_view",
    )
    if market_view == "Closest to buy":
        ordered_symbols = [
            symbol for symbol in ordered_symbols if symbol not in open_symbols
        ][:6]
    elif market_view == "3–4 checks":
        ordered_symbols = [
            symbol
            for symbol in ordered_symbols
            if symbol not in open_symbols and readiness_score(symbol) >= 3
        ]
    elif market_view == "Open positions":
        ordered_symbols = [
            symbol for symbol in ordered_symbols if symbol in open_symbols
        ]
    elif market_view == "None":
        ordered_symbols = []
    if not ordered_symbols and market_view != "None":
        st.info(f"No markets match the {market_view.lower()} view.")

    cards = []
    for symbol in ordered_symbols:
        market = markets.get(symbol, {})
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
        buy_check_label = (
            f" · {sum(bool(market.get(name)) for name in buy_check_names)}/4 CHECKS"
            if has_buy_checks and not is_open_position
            else ""
        )
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
            )
        cards.append(
            f'<div class="market-check-card {color_class} {flash_class}">'
            f'<div class="market-check-head">'
            f'<span class="market-check-symbol"><a '
            f'href="{html.escape(tradingview_url)}" target="_blank" '
            f'rel="noopener noreferrer" '
            f'title="Open {html.escape(symbol)} on TradingView">'
            f'{html.escape(symbol)} &#8599;</a></span>'
            f'<span class="market-check-status" title="{html.escape(market_status)}">'
            f'{html.escape(market_status)}</span></div>'
            f'<div class="market-check-signal">'
            f'{html.escape(display_signal + buy_check_label)}</div>'
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
    buyable_symbols = [
        symbol for symbol in target_symbols if symbol not in open_symbols
    ]
    with st.expander("🛒 Manual buy", expanded=False):
        st.warning(
            "A manual buy bypasses all four automatic entry checks and submits "
            "a real market order. The execution price may differ from the displayed price."
        )
        selected_symbol = st.selectbox(
            "Coin",
            buyable_symbols,
            key="manual_buy_symbol",
            disabled=not buyable_symbols,
        )
        manual_buy_amount = st.number_input(
            "Buy amount (USDT)",
            min_value=1.0,
            value=20.0,
            step=1.0,
            key="manual_buy_amount",
            disabled=not buyable_symbols,
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
            "Confirm market buy",
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
def render_top_bar():
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
    usdt_in_trades = 0.0
    entry_exposure = 0.0
    today_win_rate = None
    all_win_rate = None
    if not history.empty:
        sells = history[history["Side"] == "SELL"]
        total_pnl = float(sells["Est. P&L (USDT)"].sum())
        today_sells = sells[
            sells["Time"].dt.date == datetime.now().astimezone().date()
        ]
        today_pnl = float(today_sells["Est. P&L (USDT)"].sum())
        if not today_sells.empty:
            today_win_rate = float(
                (today_sells["Est. P&L (USDT)"].fillna(0) > 0).mean() * 100
            )
        if not sells.empty:
            all_win_rate = float(
                (sells["Est. P&L (USDT)"].fillna(0) > 0).mean() * 100
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
            today_unrealized_pnl += (current - entry) * quantity
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
    if status_updated_at:
        status_age = max(0, int(time.time() - float(status_updated_at)))
        if status_age <= 120:
            bot_health = "ONLINE"
            bot_health_style = " bot-health-online"
        elif status_age <= 300:
            bot_health = "DELAYED"
            bot_health_style = " bot-health-delayed"
        else:
            bot_health = "OFFLINE"
            bot_health_style = " bot-health-offline"
        bot_health_detail = f"Last completed market check {status_age} seconds ago."
    else:
        status_age = None
        bot_health = "WAITING"
        bot_health_style = " bot-health-offline"
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
            <div class="summary-item"><div class="summary-label">Today realized P&amp;L</div><div class="summary-value {today_class}">{today_pnl:+,.4f}</div></div>
            <div class="summary-item" title="Current mark-to-entry P&amp;L for all open positions"><div class="summary-label">Today unrealized P&amp;L</div><div class="summary-value {today_unrealized_class}">{today_unrealized_pnl:+,.4f}</div></div>
            <div class="summary-item" title="{html.escape(bot_health_detail)}"><div class="summary-label">Bot health</div><div class="summary-value">{html.escape(bot_health)}</div></div>
          </div>
          <div class="summary-tags">{tags}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("📈 More account and performance metrics", expanded=False):
        st.markdown(
            f"""
            <div class="secondary-summary-grid">
              <div class="summary-item" title="Current market price multiplied by tracked quantity"><div class="summary-label">USDT in trades</div><div class="summary-value">{usdt_in_trades:,.2f}</div></div>
              <div class="summary-item" title="Available USDT plus tracked open positions"><div class="summary-label">Bot tracked total</div><div class="summary-value">{tracked_total_text}</div></div>
              <div class="summary-item" title="{html.escape(binance_portfolio_note)}"><div class="summary-label">Binance Spot total</div><div class="summary-value">{binance_portfolio_text}</div></div>
              <div class="summary-item"><div class="summary-label">Per-trade max</div><div class="summary-value">{trade_amount_text}</div></div>
              <div class="summary-item"><div class="summary-label">Today win rate</div><div class="summary-value">{today_win_rate_text}</div></div>
              <div class="summary-item"><div class="summary-label">All win rate</div><div class="summary-value">{all_win_rate_text}</div></div>
              <div class="summary-item"><div class="summary-label">Total realized P&amp;L</div><div class="summary-value {total_class}">{total_pnl:+,.4f}</div></div>
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

    if positions:
        st.subheader("📈 Open trades")
        for symbol, position in positions.items():
            with st.container(border=True):
                market = status.get("markets", {}).get(symbol, {})
                live_market = live_markets.get(symbol, {})
                render_position_progress(
                    symbol, position,
                    live_market.get("price", market.get("price")),
                    bool(status.get("trading_enabled", False)),
                    status.get("environment", state["environment"]),
                    live_market,
                )
    render_results_by_symbol(history)
    render_market_suggestions(status)
    render_targets_outside_watchlist(status, positions)

    if history.empty:
        st.info("No filled transactions have been recorded yet.")
        return
    filtered = filter_history(history).sort_values("Time", ascending=False)
    detail_columns = [
        "Time", "Environment", "Side", "Result", "Symbol", "Quantity", "Price",
        "Value", "Quote asset", "Est. P&L (USDT)", "Reason", "Order ID",
    ]
    compact_columns = [
        "Time", "Symbol", "Side", "Result", "Value", "Est. P&L (USDT)", "Reason",
    ]
    filtered = filtered.copy()
    filtered["Result"] = filtered.apply(transaction_result, axis=1)
    for column in detail_columns:
        if column not in filtered:
            filtered[column] = None
    detail_frame = filtered[detail_columns]
    compact_frame = filtered[compact_columns]
    styled_frame = compact_frame.style.apply(style_transaction_row, axis=1).format(
        {"Est. P&L (USDT)": lambda value: f"{value:+,.4f}"},
        na_rep="—",
    )
    st.dataframe(styled_frame, hide_index=True, width="stretch")
    with st.expander("🧾 Detailed transaction columns", expanded=False):
        detailed_style = detail_frame.style.apply(
            style_transaction_row, axis=1
        ).format(
            {"Est. P&L (USDT)": lambda value: f"{value:+,.4f}"},
            na_rep="—",
        )
        st.dataframe(detailed_style, hide_index=True, width="stretch")
    st.download_button(
        "Download filtered transaction CSV",
        detail_frame.to_csv(index=False),
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
