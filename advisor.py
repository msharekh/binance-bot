import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).parent
STATE_FILE = PROJECT_DIR / "trade_state.json"
TRANSACTION_FILE = PROJECT_DIR / "transactions.jsonl"
STATUS_FILE = PROJECT_DIR / "bot_status.json"
CONFIG_FILE = PROJECT_DIR / "bot_config.json"
LIVE_PRICE_FILE = PROJECT_DIR / "live_prices.json"
AI_BRIEF_FILE = PROJECT_DIR / "ai_brief.json"
AI_LOCK_FILE = PROJECT_DIR / "ai_advisor.lock"

DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_REFRESH_SECONDS = 15 * 60


class AdvisorError(RuntimeError):
    pass


def ai_advisor_enabled():
    return os.getenv("ENABLE_AI_ADVISOR", "false").strip().lower() == "true"


def _read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return fallback


def _read_transactions():
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


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _rounded(value, decimals=6):
    return round(_number(value), decimals)


def _optional_rounded(value, decimals=6):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(number, decimals) if math.isfinite(number) else None


def _average(values):
    return sum(values) / len(values) if values else 0.0


def _transaction_metrics(transactions):
    sells = []
    for transaction in transactions:
        if str(transaction.get("side", "")).upper() != "SELL":
            continue
        sells.append(
            {
                "symbol": str(transaction.get("symbol", "UNKNOWN")),
                "pnl": _number(transaction.get("estimated_pnl_usdt")),
                "reason": str(transaction.get("reason", "unknown")).lower(),
                "recorded_at": int(_number(transaction.get("recorded_at"))),
            }
        )

    today = datetime.now().astimezone().date()
    today_sells = [
        sale
        for sale in sells
        if sale["recorded_at"]
        and datetime.fromtimestamp(sale["recorded_at"]).astimezone().date() == today
    ]
    wins = [sale["pnl"] for sale in sells if sale["pnl"] > 0]
    losses = [sale["pnl"] for sale in sells if sale["pnl"] < 0]
    stop_losses = [sale for sale in sells if "stop loss" in sale["reason"]]
    take_profits = [sale for sale in sells if "take profit" in sale["reason"]]
    manual_exits = [sale for sale in sells if "manual" in sale["reason"]]
    rsi_exits = [sale for sale in sells if "rsi" in sale["reason"]]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    per_symbol = {}
    for sale in sells:
        item = per_symbol.setdefault(
            sale["symbol"],
            {"completed": 0, "wins": 0, "pnl_usdt": 0.0, "stop_losses": 0},
        )
        item["completed"] += 1
        item["wins"] += int(sale["pnl"] > 0)
        item["pnl_usdt"] += sale["pnl"]
        item["stop_losses"] += int("stop loss" in sale["reason"])

    per_symbol_rows = []
    for symbol, item in per_symbol.items():
        per_symbol_rows.append(
            {
                "symbol": symbol,
                "completed": item["completed"],
                "wins": item["wins"],
                "win_rate_pct": _rounded(
                    item["wins"] / item["completed"] * 100, 2
                ),
                "pnl_usdt": _rounded(item["pnl_usdt"]),
                "stop_losses": item["stop_losses"],
            }
        )
    per_symbol_rows.sort(key=lambda item: item["pnl_usdt"], reverse=True)

    completed = len(sells)
    if completed < 10:
        sample_confidence = "low"
    elif completed < 30:
        sample_confidence = "medium"
    else:
        sample_confidence = "high"

    return {
        "completed_trades": completed,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": completed - len(wins) - len(losses),
        "win_rate_pct": _rounded(len(wins) / completed * 100, 2) if completed else 0,
        "total_realized_pnl_usdt": _rounded(sum(sale["pnl"] for sale in sells)),
        "today_realized_pnl_usdt": _rounded(
            sum(sale["pnl"] for sale in today_sells)
        ),
        "average_win_usdt": _rounded(_average(wins)),
        "average_loss_usdt": _rounded(_average(losses)),
        "profit_factor": _rounded(gross_profit / gross_loss, 3) if gross_loss else None,
        "stop_loss_count": len(stop_losses),
        "stop_loss_rate_pct": _rounded(len(stop_losses) / completed * 100, 2)
        if completed
        else 0,
        "take_profit_count": len(take_profits),
        "manual_exit_count": len(manual_exits),
        "rsi_exit_count": len(rsi_exits),
        "sample_confidence": sample_confidence,
        "per_symbol": per_symbol_rows,
        "recent_completed_trades": sells[-20:],
    }


def _open_position_metrics(state, status, live_prices):
    positions = state.get("positions", {})
    status_markets = status.get("markets", {})
    live_markets = live_prices.get("prices", {})
    rows = []
    total_entry_value = 0.0
    total_current_value = 0.0
    total_unrealized = 0.0

    for symbol, position in positions.items():
        entry = _number(position.get("entry"))
        quantity = _number(position.get("quantity"))
        stop_loss = _number(position.get("stop_loss"))
        take_profit = _number(position.get("take_profit"))
        market = status_markets.get(symbol, {})
        live_market = live_markets.get(symbol, {})
        current = _number(live_market.get("price", market.get("price", entry)), entry)
        entry_value = entry * quantity
        current_value = current * quantity
        unrealized = current_value - entry_value
        span = take_profit - stop_loss
        progress = (current - stop_loss) / span * 100 if span > 0 else 50
        risk = entry - stop_loss
        reward = take_profit - entry
        rows.append(
            {
                "symbol": symbol,
                "entry_price": _rounded(entry, 10),
                "current_price": _rounded(current, 10),
                "stop_loss_price": _rounded(stop_loss, 10),
                "take_profit_price": _rounded(take_profit, 10),
                "entry_value_usdt": _rounded(entry_value),
                "current_value_usdt": _rounded(current_value),
                "unrealized_pnl_usdt": _rounded(unrealized),
                "unrealized_pct": _rounded(
                    ((current - entry) / entry) * 100 if entry else 0, 3
                ),
                "progress_sl_to_tp_pct": _rounded(max(0, min(100, progress)), 2),
                "distance_to_sl_pct": _rounded(
                    ((current - stop_loss) / current) * 100 if current else 0, 3
                ),
                "distance_to_tp_pct": _rounded(
                    ((take_profit - current) / current) * 100 if current else 0, 3
                ),
                "planned_risk_reward": _rounded(reward / risk, 2) if risk > 0 else None,
                "rsi": _optional_rounded(market.get("rsi"), 2),
                "previous_rsi": _optional_rounded(market.get("previous_rsi"), 2),
                "atr_pct": _rounded(
                    _number(market.get("atr")) / current * 100 if current else 0, 3
                ),
                "signal": str(market.get("signal", "unknown")),
                "status": str(market.get("status", "unknown")),
                "live_direction_10s": str(live_market.get("direction", "unknown")),
            }
        )
        total_entry_value += entry_value
        total_current_value += current_value
        total_unrealized += unrealized

    return {
        "count": len(rows),
        "entry_exposure_usdt": _rounded(total_entry_value),
        "current_value_usdt": _rounded(total_current_value),
        "unrealized_pnl_usdt": _rounded(total_unrealized),
        "positions": rows,
    }


def _market_metrics(status, live_prices):
    markets = status.get("markets", {})
    live_markets = live_prices.get("prices", {})
    rows = []
    for symbol in status.get("target_symbols", markets.keys()):
        market = markets.get(symbol, {})
        live_market = live_markets.get(symbol, {})
        price = _optional_rounded(
            live_market.get("price", market.get("price")), 10
        )
        atr = _optional_rounded(market.get("atr"), 10)
        rows.append(
            {
                "symbol": str(symbol),
                "price": price,
                "rsi": _optional_rounded(market.get("rsi"), 2),
                "atr": atr,
                "atr_pct": _rounded(
                    atr / price * 100,
                    3,
                ) if atr is not None and price else None,
                "support": _optional_rounded(market.get("support"), 10),
                "resistance": _optional_rounded(market.get("resistance"), 10),
                "distance_to_support_pct": _optional_rounded(
                    market.get("distance_to_support_pct"), 3
                ),
                "suggested_stop_loss": _optional_rounded(
                    market.get("suggested_sl"), 10
                ),
                "suggested_take_profit": _optional_rounded(
                    market.get("suggested_tp"), 10
                ),
                "trend_interval": str(market.get("trend_interval", "unknown")),
                "trend_ema_period": int(_number(market.get("trend_ema_period"))),
                "trend_price": _optional_rounded(market.get("trend_price"), 10),
                "trend_ema": _optional_rounded(market.get("trend_ema"), 10),
                "expected_net_reward_pct": _optional_rounded(
                    market.get("expected_net_reward_pct"), 3
                ),
                "buy_checks": {
                    "rsi_recovered": bool(market.get("rsi_recovered", False)),
                    "near_support": bool(market.get("near_support", False)),
                    "trend_ok": bool(market.get("trend_ok", False)),
                    "reward_ok": bool(market.get("reward_ok", False)),
                },
                "signal": str(market.get("signal", "unknown")),
                "status": str(market.get("status", "unknown")),
                "live_direction_10s": str(live_market.get("direction", "unknown")),
            }
        )
    return rows


def build_snapshot():
    state = _read_json(STATE_FILE, {"environment": "unknown", "positions": {}})
    status = _read_json(STATUS_FILE, {})
    config = _read_json(CONFIG_FILE, {})
    live_prices = _read_json(LIVE_PRICE_FILE, {})
    if live_prices.get("environment") != state.get("environment"):
        live_prices = {}
    environment = str(state.get("environment", status.get("environment", "unknown")))
    transactions = [
        transaction
        for transaction in _read_transactions()
        if str(transaction.get("environment") or environment) == environment
    ]
    performance = _transaction_metrics(transactions)
    open_positions = _open_position_metrics(state, status, live_prices)
    maximum_exposure = _number(
        config.get(
            "max_total_exposure_usdt",
            status.get("max_total_exposure_usdt", 0),
        )
    )
    maximum_positions = int(
        _number(config.get("max_open_positions", status.get("max_open_positions", 0)))
    )

    snapshot = {
        "generated_at": int(time.time()),
        "environment": environment,
        "settings": {
            "interval": str(config.get("interval", status.get("interval", "unknown"))),
            "target_symbols": list(config.get("target_symbols", status.get("target_symbols", []))),
            "trade_amount_usdt": _rounded(
                config.get("trade_amount_usdt", status.get("trade_amount_usdt", 0))
            ),
            "max_total_exposure_usdt": _rounded(maximum_exposure),
            "max_open_positions": maximum_positions,
            "trading_on_hold": bool(
                config.get("trading_on_hold", status.get("trading_on_hold", False))
            ),
            "trading_enabled": bool(status.get("trading_enabled", False)),
        },
        "strategy": {
            "buy_rsi_recovery": _rounded(
                config.get("buy_rsi_recovery", 35), 2
            ),
            "max_support_distance_pct": _rounded(
                config.get("max_support_distance_pct", 0.30), 3
            ),
            "trend_interval": str(config.get("trend_interval", "1h")),
            "trend_ema_period": int(_number(config.get("trend_ema_period", 50))),
            "min_net_reward_pct": _rounded(
                config.get("min_net_reward_pct", 0.50), 3
            ),
            "estimated_round_trip_fee_pct": _rounded(
                config.get("estimated_round_trip_fee_pct", 0.20), 3
            ),
            "sell_rsi_threshold": _rounded(
                config.get("sell_rsi_threshold", 65), 2
            ),
            "stop_loss_atr_multiple": _rounded(
                config.get("atr_sl_multiplier", 1.5), 2
            ),
            "take_profit_reward_to_risk": _rounded(
                config.get("risk_reward_ratio", 2.0), 2
            ),
        },
        "market_checks": _market_metrics(status, live_prices),
        "portfolio": {
            **open_positions,
            "exposure_utilization_pct": _rounded(
                open_positions["entry_exposure_usdt"] / maximum_exposure * 100,
                2,
            )
            if maximum_exposure
            else None,
            "position_capacity_used_pct": _rounded(
                open_positions["count"] / maximum_positions * 100, 2
            )
            if maximum_positions
            else None,
        },
        "performance": performance,
        "data_limitations": [
            "Realized P&L is estimated before commissions.",
            "Only transactions recorded by this bot are included.",
            "Unrealized P&L uses the latest locally cached Binance price.",
            "Technical indicators are descriptive and do not predict profit.",
        ],
    }
    return snapshot


BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "progress": {"type": "string"},
        "result": {"type": "string"},
        "what_is_right": {"type": "array", "items": {"type": "string"}},
        "what_is_wrong": {"type": "array", "items": {"type": "string"}},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "area": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "reason": {"type": "string"},
                    "current_value": {"type": "string"},
                    "proposed_value": {"type": "string"},
                    "change_type": {
                        "type": "string",
                        "enum": ["behavior", "setting", "price_limit", "code", "none"],
                    },
                },
                "required": [
                    "priority", "area", "suggestion", "reason", "current_value",
                    "proposed_value", "change_type",
                ],
            },
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "risk_note": {"type": "string"},
    },
    "required": [
        "headline", "progress", "result", "what_is_right", "what_is_wrong",
        "recommendations", "confidence", "risk_note",
    ],
}


ADVISOR_INSTRUCTIONS = """
You are a cautious technical-analysis reviewer for a small Binance Spot trading bot.
Analyze only the supplied computed metrics. Do not invent prices, news, causes, or
performance data. Separate evidence from uncertainty. If fewer than 10 completed
trades exist, state clearly that the sample is too small for strong conclusions.
Review progress, results, stop-loss behavior, risk/reward, exposure, symbol-level
performance, RSI/ATR context, and configuration. Recommend only testable changes.
Never promise profit, never tell the user to deposit more money, and never claim a
setting is optimal. Do not issue buy/sell commands for a specific asset. Prefer one
change at a time followed by paper/testnet evaluation. Any code or setting suggestion
must explain the evidence, current value, proposed value or range, and downside.
The advisor is read-only: it cannot trade or change configuration.
""".strip()


def read_ai_brief():
    return _read_json(AI_BRIEF_FILE, {})


def ai_brief_age_seconds(brief=None):
    brief = brief or read_ai_brief()
    generated_at = _number(brief.get("generated_at"))
    return max(0, int(time.time() - generated_at)) if generated_at else None


def _atomic_write_json(path, payload):
    temporary_file = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    temporary_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for attempt in range(6):
        try:
            temporary_file.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def _acquire_lock():
    try:
        with AI_LOCK_FILE.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    except FileExistsError:
        try:
            if time.time() - AI_LOCK_FILE.stat().st_mtime > 300:
                AI_LOCK_FILE.unlink()
                handle = AI_LOCK_FILE.open("x")
                handle.write(str(os.getpid()))
                handle.close()
                return True
        except OSError:
            pass
        return False


def _release_lock():
    try:
        AI_LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def generate_ai_brief(force=False, refresh_seconds=DEFAULT_REFRESH_SECONDS):
    if not ai_advisor_enabled():
        raise AdvisorError(
            "AI advisor is paused. Set ENABLE_AI_ADVISOR=true and restart "
            "the dashboard when API billing is ready."
        )
    existing = read_ai_brief()
    age = ai_brief_age_seconds(existing)
    if not force and existing and age is not None and age < refresh_seconds:
        return existing

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AdvisorError("Set OPENAI_API_KEY before generating an AI brief.")
    if not _acquire_lock():
        if existing:
            return existing
        raise AdvisorError("Another AI brief is already being generated.")

    try:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise AdvisorError(
                "The openai package is not installed. Run: python -m pip install openai"
            ) from error

        snapshot = build_snapshot()
        snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        client = OpenAI(api_key=api_key, timeout=30.0, max_retries=1)
        try:
            response = client.responses.create(
                model=model,
                instructions=ADVISOR_INSTRUCTIONS,
                input=(
                    "Produce the Version 2 trading performance brief from this "
                    f"sanitized metrics snapshot:\n{snapshot_json}"
                ),
                reasoning={"effort": "low"},
                text={
                    "verbosity": "low",
                    "format": {
                        "type": "json_schema",
                        "name": "trading_advisor_brief",
                        "strict": True,
                        "schema": BRIEF_SCHEMA,
                    },
                },
                max_output_tokens=2500,
                store=False,
            )
            report = json.loads(response.output_text)
        except Exception as error:
            raise AdvisorError(f"OpenAI brief generation failed: {error}") from error

        payload = {
            "version": 2,
            "generated_at": int(time.time()),
            "model": model,
            "environment": snapshot["environment"],
            "snapshot_hash": snapshot_hash,
            "metrics": {
                "completed_trades": snapshot["performance"]["completed_trades"],
                "total_realized_pnl_usdt": snapshot["performance"][
                    "total_realized_pnl_usdt"
                ],
                "unrealized_pnl_usdt": snapshot["portfolio"]["unrealized_pnl_usdt"],
                "open_positions": snapshot["portfolio"]["count"],
            },
            **report,
        }
        _atomic_write_json(AI_BRIEF_FILE, payload)
        return payload
    finally:
        _release_lock()
