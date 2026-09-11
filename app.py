import json
from collections import Counter
import math
import msvcrt
import os
import statistics
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path

import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from rich.console import Console
from entry_conditions import capture_entry_conditions
from watchlist_automation import apply_watchlist_automation


console = Console(highlight=False)


def print_status(message, style="cyan"):
    """Print a Windows Terminal-friendly status message."""
    console.print(message, style=style, markup=False)


# INTERVAL = Client.KLINE_INTERVAL_1MINUTE
INTERVAL = Client.KLINE_INTERVAL_15MINUTE
SUPPORTED_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
    "12h", "1d", "3d", "1w", "1M",
}
INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
    "12h": 720, "1d": 1440, "3d": 4320, "1w": 10080, "1M": 43200,
}
DEFAULT_RISK_REWARD_RATIO = Decimal("2")
DEFAULT_ATR_SL_MULTIPLIER = Decimal("1.5")
DEFAULT_BUY_RSI_RECOVERY = Decimal("35")
DEFAULT_MAX_SUPPORT_DISTANCE_PCT = Decimal("0.30")
DEFAULT_TREND_INTERVAL = Client.KLINE_INTERVAL_1HOUR
DEFAULT_TREND_EMA_PERIOD = 50
DEFAULT_MIN_NET_REWARD_PCT = Decimal("0.50")
DEFAULT_MIN_NET_PROFIT_USDT = Decimal("0.50")
DEFAULT_ESTIMATED_ROUND_TRIP_FEE_PCT = Decimal("0.20")
DEFAULT_SELL_RSI_THRESHOLD = Decimal("65")
DEFAULT_MAX_STOP_DISTANCE_PCT = Decimal("0.80")
TRADE_AMOUNT_USDT = Decimal(os.getenv("TRADE_AMOUNT_USDT", "25"))
DEFAULT_MAX_TOTAL_EXPOSURE_USDT = Decimal(
    os.getenv("MAX_TOTAL_EXPOSURE_USDT", "75")
)
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
# Keep the dashboard responsive while leaving a short pause between full
# Binance analysis cycles to avoid unnecessary API traffic.
POLL_SECONDS = 15
LIVE_PRICE_REFRESH_SECONDS = 2
BINANCE_REQUEST_TIMEOUT_SECONDS = 20
BINANCE_RECONNECT_SECONDS = 10
SUGGESTION_REFRESH_SECONDS = 15 * 60
WATCHLIST_MIN_QUOTE_VOLUME = 10_000_000
WATCHLIST_LIMIT = 30
MARKET_OVERVIEW_MIN_QUOTE_VOLUME = 10_000_000
WATCHLIST_MIN_RANGE_PCT = 1.5
MARKET_DIRECTION_THRESHOLD_PCT = 1.5
MARKET_MEDIAN_DIRECTION_THRESHOLD_PCT = 1.0
MARKET_ACTIVE_RANGE_PCT = 3.0
MARKET_QUIET_ACTIVE_BREADTH_PCT = 35.0
STABLE_BASE_ASSETS = {
    "AEUR", "BFUSD", "DAI", "EUR", "FDUSD", "PYUSD", "RLUSD", "TUSD",
    "TRY", "USDC", "USDE", "USDP", "USDS", "USD1",
}

# Comma-separated USDT markets, for example: BTCUSDT,ETHUSDT,TRXUSDT
DEFAULT_SYMBOLS = tuple(
    dict.fromkeys(
        symbol.strip().upper()
        for symbol in os.getenv(
            "TRADING_SYMBOLS", "BTCUSDT,ETHUSDT,TRXUSDT"
        ).split(",")
        if symbol.strip()
    )
)

# This remains production to preserve the environment selected by the user.
TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true" 
ENVIRONMENT = "testnet" if TESTNET else "production"
TRADING_ENABLED = os.getenv("ENABLE_TRADING", "false").lower() == "true"
STATE_FILE = Path(__file__).with_name("trade_state.json")
ENTRY_COOLDOWN_FILE = Path(__file__).with_name("entry_cooldowns.json")
TRANSACTION_FILE = Path(__file__).with_name("transactions.jsonl")
STATUS_FILE = Path(__file__).with_name("bot_status.json")
LIVE_PRICE_FILE = Path(__file__).with_name("live_prices.json")
CONFIG_FILE = Path(__file__).with_name("bot_config.json")
MARKET_OVERVIEW_HISTORY_FILE = Path(__file__).with_name(
    "market_overview_history.jsonl"
)
SELL_REQUEST_FILE = Path(__file__).with_name("sell_requests.jsonl")
SELL_PROCESSING_FILE = Path(__file__).with_name("sell_requests.processing.jsonl")
BUY_REQUEST_FILE = Path(__file__).with_name("buy_requests.jsonl")
BUY_PROCESSING_FILE = Path(__file__).with_name("buy_requests.processing.jsonl")
LOCK_FILE = Path(__file__).with_name("bot.lock")
INSTANCE_LOCK_HANDLE = None


def create_client():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("Set BINANCE_API_KEY and BINANCE_API_SECRET.")
    return Client(
        api_key.strip(),
        api_secret.strip(),
        testnet=TESTNET,
        requests_params={"timeout": BINANCE_REQUEST_TIMEOUT_SECONDS},
    )


def create_client_with_retry():
    while True:
        try:
            return create_client()
        except KeyboardInterrupt:
            raise
        except Exception as error:
            print_status(
                "Could not connect to Binance: "
                f"{type(error).__name__}: {error}. Retrying in "
                f"{BINANCE_RECONNECT_SECONDS} seconds.",
                "bold red",
            )
            time.sleep(BINANCE_RECONNECT_SECONDS)


def acquire_instance_lock():
    global INSTANCE_LOCK_HANDLE
    LOCK_FILE.touch(exist_ok=True)
    lock_handle = LOCK_FILE.open("r+")
    if LOCK_FILE.stat().st_size == 0:
        lock_handle.write("0")
        lock_handle.flush()
        lock_handle.seek(0)
    try:
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as error:
        lock_handle.close()
        raise RuntimeError(
            "Another bot instance is already running. Stop it before starting this one."
        ) from error
    INSTANCE_LOCK_HANDLE = lock_handle


def load_runtime_config():
    config = {
        "target_symbols": list(DEFAULT_SYMBOLS),
        "max_total_exposure_usdt": DEFAULT_MAX_TOTAL_EXPOSURE_USDT,
        "trade_amount_usdt": TRADE_AMOUNT_USDT,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "trading_on_hold": False,
        "ignore_weak_market": False,
        "interval": INTERVAL,
        "buy_rsi_recovery": DEFAULT_BUY_RSI_RECOVERY,
        "rsi_recovery_window": 1,
        "max_support_distance_pct": DEFAULT_MAX_SUPPORT_DISTANCE_PCT,
        "trend_interval": DEFAULT_TREND_INTERVAL,
        "trend_ema_period": DEFAULT_TREND_EMA_PERIOD,
        "min_net_reward_pct": DEFAULT_MIN_NET_REWARD_PCT,
        "min_net_profit_usdt": DEFAULT_MIN_NET_PROFIT_USDT,
        "estimated_round_trip_fee_pct": DEFAULT_ESTIMATED_ROUND_TRIP_FEE_PCT,
        "atr_sl_multiplier": DEFAULT_ATR_SL_MULTIPLIER,
        "max_stop_distance_pct": DEFAULT_MAX_STOP_DISTANCE_PCT,
        "risk_reward_ratio": DEFAULT_RISK_REWARD_RATIO,
        "sell_rsi_threshold": DEFAULT_SELL_RSI_THRESHOLD,
        "poll_seconds": POLL_SECONDS,
        "live_price_refresh_seconds": LIVE_PRICE_REFRESH_SECONDS,
    }
    if not CONFIG_FILE.exists():
        return config
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
            saved = json.load(config_file)
        symbols = tuple(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in saved.get("target_symbols", [])
                if str(symbol).strip()
            )
        )
        maximum_exposure = Decimal(str(saved["max_total_exposure_usdt"]))
        trade_amount = Decimal(
            str(saved.get("trade_amount_usdt", TRADE_AMOUNT_USDT))
        )
        max_open_positions = int(
            saved.get("max_open_positions", MAX_OPEN_POSITIONS)
        )
        trading_on_hold = bool(saved.get("trading_on_hold", False))
        interval = str(saved.get("interval", INTERVAL))
        buy_rsi_recovery = Decimal(
            str(saved.get("buy_rsi_recovery", DEFAULT_BUY_RSI_RECOVERY))
        )
        max_support_distance_pct = Decimal(
            str(
                saved.get(
                    "max_support_distance_pct", DEFAULT_MAX_SUPPORT_DISTANCE_PCT
                )
            )
        )
        trend_interval = str(saved.get("trend_interval", DEFAULT_TREND_INTERVAL))
        trend_ema_period = int(
            saved.get("trend_ema_period", DEFAULT_TREND_EMA_PERIOD)
        )
        min_net_reward_pct = Decimal(
            str(saved.get("min_net_reward_pct", DEFAULT_MIN_NET_REWARD_PCT))
        )
        min_net_profit_usdt = Decimal(
            str(saved.get("min_net_profit_usdt", DEFAULT_MIN_NET_PROFIT_USDT))
        )
        estimated_round_trip_fee_pct = Decimal(
            str(
                saved.get(
                    "estimated_round_trip_fee_pct",
                    DEFAULT_ESTIMATED_ROUND_TRIP_FEE_PCT,
                )
            )
        )
        atr_sl_multiplier = Decimal(
            str(saved.get("atr_sl_multiplier", DEFAULT_ATR_SL_MULTIPLIER))
        )
        max_stop_distance_pct = Decimal(
            str(
                saved.get(
                    "max_stop_distance_pct", DEFAULT_MAX_STOP_DISTANCE_PCT
                )
            )
        )
        risk_reward_ratio = Decimal(
            str(saved.get("risk_reward_ratio", DEFAULT_RISK_REWARD_RATIO))
        )
        sell_rsi_threshold = Decimal(
            str(saved.get("sell_rsi_threshold", DEFAULT_SELL_RSI_THRESHOLD))
        )
        config["poll_seconds"] = max(10, int(saved.get("poll_seconds", POLL_SECONDS)))
        config["live_price_refresh_seconds"] = max(2, int(saved.get("live_price_refresh_seconds", LIVE_PRICE_REFRESH_SECONDS)))
        if maximum_exposure <= 0:
            raise ValueError("Maximum exposure must be greater than zero.")
        if trade_amount <= 0:
            raise ValueError("Per-trade amount must be greater than zero.")
        if trade_amount > maximum_exposure:
            raise ValueError("Per-trade amount cannot exceed maximum exposure.")
        if max_open_positions <= 0:
            raise ValueError("Maximum open positions must be greater than zero.")
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported candle interval: {interval}.")
        if not 1 <= buy_rsi_recovery <= 50:
            raise ValueError("Buy RSI recovery must be between 1 and 50.")
        if not 0 <= max_support_distance_pct <= 5:
            raise ValueError("Support distance must be between 0% and 5%.")
        if trend_interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported trend interval: {trend_interval}.")
        if INTERVAL_MINUTES[trend_interval] < INTERVAL_MINUTES[interval]:
            raise ValueError("Trend interval cannot be shorter than candle interval.")
        if not 10 <= trend_ema_period <= 500:
            raise ValueError("Trend EMA period must be between 10 and 500.")
        if not 0 <= min_net_reward_pct <= 20:
            raise ValueError("Minimum net reward must be between 0% and 20%.")
        if not 0 <= min_net_profit_usdt <= 1000:
            raise ValueError("Minimum net profit must be between 0 and 1000 USDT.")
        if not 0 <= estimated_round_trip_fee_pct <= 5:
            raise ValueError("Estimated round-trip fee must be between 0% and 5%.")
        if not 0.1 <= atr_sl_multiplier <= 10:
            raise ValueError("ATR stop multiplier must be between 0.1 and 10.")
        if not 0.1 <= max_stop_distance_pct <= 10:
            raise ValueError("Maximum stop distance must be between 0.1% and 10%.")
        if not 0.1 <= risk_reward_ratio <= 10:
            raise ValueError("Reward/risk ratio must be between 0.1 and 10.")
        if not 50 <= sell_rsi_threshold <= 99:
            raise ValueError("Sell RSI threshold must be between 50 and 99.")
        config["target_symbols"] = list(symbols)
        config["max_total_exposure_usdt"] = maximum_exposure
        config["trade_amount_usdt"] = trade_amount
        config["max_open_positions"] = max_open_positions
        config["trading_on_hold"] = trading_on_hold
        config["ignore_weak_market"] = bool(saved.get("ignore_weak_market", False))
        config["interval"] = interval
        config["buy_rsi_recovery"] = buy_rsi_recovery
        recovery_window = int(saved.get("rsi_recovery_window", 1))
        if not 1 <= recovery_window <= 10:
            raise ValueError("RSI recovery window must be between 1 and 10 candles.")
        config["rsi_recovery_window"] = recovery_window
        config["max_support_distance_pct"] = max_support_distance_pct
        config["trend_interval"] = trend_interval
        config["trend_ema_period"] = trend_ema_period
        config["min_net_reward_pct"] = min_net_reward_pct
        config["min_net_profit_usdt"] = min_net_profit_usdt
        config["estimated_round_trip_fee_pct"] = estimated_round_trip_fee_pct
        config["atr_sl_multiplier"] = atr_sl_multiplier
        config["max_stop_distance_pct"] = max_stop_distance_pct
        config["risk_reward_ratio"] = risk_reward_ratio
        config["sell_rsi_threshold"] = sell_rsi_threshold
        return config
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Ignoring invalid bot_config.json: {error}")
        return config


def calculate_rsi(data, window=14):
    delta = data["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    relative_strength = gain / loss
    return 100 - (100 / (1 + relative_strength))


def calculate_atr(data, window=14):
    high_low = data["high"] - data["low"]
    high_close = (data["high"] - data["close"].shift()).abs()
    low_close = (data["low"] - data["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=window).mean()


def analyze_market(client, symbol, interval, strategy):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=100)
    columns = [
        "time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
    ]
    data = pd.DataFrame(klines, columns=columns)
    for column in ["open", "high", "low", "close", "volume"]:
        data[column] = data[column].astype(float)

    completed = data.iloc[:-1]
    recent_candles = [
        {
            "close_time": int(row["close_time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        for _, row in completed.tail(48).iterrows()
    ]
    signal_candle_close_time = int(completed["close_time"].iloc[-1])
    entry_price = completed["close"].iloc[-1]
    rsi_series = calculate_rsi(completed)
    previous_rsi = rsi_series.iloc[-2]
    rsi = rsi_series.iloc[-1]
    atr = calculate_atr(completed).iloc[-1]
    support = completed["low"].tail(20).min()
    resistance = completed["high"].tail(20).max()
    stop_distance = atr * float(strategy["atr_sl_multiplier"])
    stop_distance_pct = stop_distance / entry_price * 100
    reward_distance = stop_distance * float(strategy["risk_reward_ratio"])
    gross_reward_pct = reward_distance / entry_price * 100
    expected_net_reward_pct = gross_reward_pct - float(
        strategy["estimated_round_trip_fee_pct"]
    )

    trend_klines = client.get_klines(
        symbol=symbol,
        interval=strategy["trend_interval"],
        limit=strategy["trend_ema_period"] + 2,
    )
    trend_closes = pd.Series(
        [float(kline[4]) for kline in trend_klines[:-1]], dtype="float64"
    )
    if len(trend_closes) < strategy["trend_ema_period"]:
        raise ValueError(
            f"Not enough {strategy['trend_interval']} candles for "
            f"EMA {strategy['trend_ema_period']}."
        )
    trend_price = trend_closes.iloc[-1]
    trend_ema = trend_closes.ewm(
        span=strategy["trend_ema_period"], adjust=False
    ).mean().iloc[-1]
    ema_9 = completed["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema_21 = completed["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    momentum_ok = bool(ema_9 > ema_21)
    distance_to_support_pct = ((entry_price - support) / entry_price) * 100
    threshold = float(strategy["buy_rsi_recovery"])
    recovery_window = int(strategy.get("rsi_recovery_window", 1))
    upward_crosses = (rsi_series.shift(1) <= threshold) & (rsi_series > threshold)
    rsi_recovered = bool(
        upward_crosses.tail(recovery_window).any()
        and rsi > threshold
        and rsi > previous_rsi
    )
    near_support = bool(
        distance_to_support_pct <= float(strategy["max_support_distance_pct"])
    )
    trend_ok = bool(trend_price > trend_ema)
    reward_ok = bool(
        expected_net_reward_pct >= float(strategy["min_net_reward_pct"])
    )
    stop_risk_ok = bool(
        stop_distance_pct
        <= float(
            strategy.get(
                "max_stop_distance_pct", DEFAULT_MAX_STOP_DISTANCE_PCT
            )
        )
    )
    buy_signal = sum(bool(check) for check in (
        rsi_recovered, near_support, trend_ok, reward_ok,
        stop_risk_ok, momentum_ok,
    )) >= 5
    return {
        "entry": entry_price,
        "signal_candle_close_time": signal_candle_close_time,
        "sl": entry_price - stop_distance,
        "tp": entry_price + reward_distance,
        "rsi": rsi,
        "previous_rsi": previous_rsi,
        "rsi_history": [float(value) if pd.notna(value) else None
                        for value in rsi_series.tail(3)],
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "distance_to_support_pct": distance_to_support_pct,
        "trend_interval": strategy["trend_interval"],
        "trend_ema_period": strategy["trend_ema_period"],
        "trend_price": trend_price,
        "trend_ema": trend_ema,
        "ema_9": ema_9,
        "ema_21": ema_21,
        "gross_reward_pct": gross_reward_pct,
        "expected_net_reward_pct": expected_net_reward_pct,
        "min_net_profit_usdt": float(strategy["min_net_profit_usdt"]),
        "risk_reward_ratio": float(strategy["risk_reward_ratio"]),
        "estimated_round_trip_fee_pct": float(
            strategy["estimated_round_trip_fee_pct"]
        ),
        "stop_distance_pct": stop_distance_pct,
        "rsi_recovered": rsi_recovered,
        "near_support": near_support,
        "trend_ok": trend_ok,
        "reward_ok": reward_ok,
        "stop_risk_ok": stop_risk_ok,
        "momentum_ok": momentum_ok,
        "buy_signal": buy_signal,
        "sell_signal": bool(rsi >= float(strategy["sell_rsi_threshold"])),
        "stop_distance": stop_distance,
        "candles": recent_candles,
    }


def market_signal(analysis):
    if analysis["buy_signal"]:
        return "BUY SIGNAL"
    if analysis["sell_signal"]:
        return "SELL SIGNAL"
    return "NEUTRAL"


def load_positions():
    if not STATE_FILE.exists():
        return {}
    with STATE_FILE.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)

    if "positions" not in state:
        raise RuntimeError(
            "Legacy trade_state.json detected. Archive it or convert it before "
            "running the multi-market bot."
        )
    saved_environment = state.get("environment")
    if saved_environment != ENVIRONMENT:
        raise RuntimeError(
            f"State belongs to {saved_environment}, but the bot is using {ENVIRONMENT}."
        )
    return state["positions"]


def save_positions(positions):
    temporary_file = STATE_FILE.with_suffix(".tmp")
    state = {"environment": ENVIRONMENT, "positions": positions}
    with temporary_file.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2)
    temporary_file.replace(STATE_FILE)


def load_entry_cooldowns():
    if not ENTRY_COOLDOWN_FILE.exists():
        return {}
    try:
        with ENTRY_COOLDOWN_FILE.open("r", encoding="utf-8") as cooldown_file:
            state = json.load(cooldown_file)
        if state.get("environment") != ENVIRONMENT:
            return {}
        return {
            str(symbol): int(candle_time)
            for symbol, candle_time in state.get("last_entry_candle", {}).items()
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Ignoring invalid entry_cooldowns.json: {error}")
        return {}


def save_entry_cooldowns(last_entry_candle):
    temporary_file = ENTRY_COOLDOWN_FILE.with_suffix(".tmp")
    state = {
        "environment": ENVIRONMENT,
        "last_entry_candle": last_entry_candle,
    }
    with temporary_file.open("w", encoding="utf-8") as cooldown_file:
        json.dump(state, cooldown_file, indent=2)
    # Windows readers/antivirus can briefly prevent an atomic replacement.
    # Keep the old file intact and retry; never truncate it as a fallback.
    for attempt in range(10):
        try:
            temporary_file.replace(ENTRY_COOLDOWN_FILE)
            return
        except PermissionError as error:
            if attempt == 9:
                raise PermissionError(
                    f"Could not save {ENTRY_COOLDOWN_FILE} after retrying for "
                    "4.5 seconds. Check file permissions or a program holding "
                    "the file open. The previous cooldown file was preserved."
                ) from error
            time.sleep(0.5)


def save_status(
    available_usdt, total_portfolio_usdt, unpriced_assets, analyses,
    market_statuses, target_symbols, maximum_exposure, trade_amount,
    max_open_positions, trading_on_hold, interval, suggestions, market_overview,
    strategy,
):
    temporary_file = STATUS_FILE.with_suffix(".tmp")
    status = {
        "environment": ENVIRONMENT,
        "updated_at": int(time.time()),
        "available_usdt": str(available_usdt),
        "total_portfolio_usdt": str(total_portfolio_usdt),
        "portfolio_unpriced_assets": unpriced_assets,
        "trade_amount_usdt": str(trade_amount),
        "max_open_positions": max_open_positions,
        "trading_on_hold": trading_on_hold,
        "interval": interval,
        "target_symbols": list(target_symbols),
        "max_total_exposure_usdt": str(maximum_exposure),
        "market_statuses": market_statuses,
        "trading_enabled": TRADING_ENABLED,
        "suggestions": suggestions,
        "market_overview": market_overview,
        "strategy": {
            "buy_rsi_recovery": str(strategy["buy_rsi_recovery"]),
            "rsi_recovery_window": int(strategy.get("rsi_recovery_window", 1)),
            "max_support_distance_pct": str(
                strategy["max_support_distance_pct"]
            ),
            "trend_interval": strategy["trend_interval"],
            "trend_ema_period": strategy["trend_ema_period"],
            "min_net_reward_pct": str(strategy["min_net_reward_pct"]),
            "min_net_profit_usdt": str(strategy["min_net_profit_usdt"]),
            "estimated_round_trip_fee_pct": str(
                strategy["estimated_round_trip_fee_pct"]
            ),
            "atr_sl_multiplier": str(strategy["atr_sl_multiplier"]),
            "max_stop_distance_pct": str(strategy["max_stop_distance_pct"]),
            "risk_reward_ratio": str(strategy["risk_reward_ratio"]),
            "sell_rsi_threshold": str(strategy["sell_rsi_threshold"]),
        },
        "markets": {
            symbol: {
                "price": analysis["entry"],
                "signal_candle_close_time": analysis[
                    "signal_candle_close_time"
                ],
                "rsi": analysis["rsi"],
                "atr": analysis["atr"],
                "support": analysis["support"],
                "resistance": analysis["resistance"],
                "suggested_sl": analysis["sl"],
                "suggested_tp": analysis["tp"],
                "previous_rsi": analysis["previous_rsi"],
                "rsi_history": analysis.get("rsi_history", []),
                "distance_to_support_pct": analysis["distance_to_support_pct"],
                "trend_interval": analysis["trend_interval"],
                "trend_ema_period": analysis["trend_ema_period"],
                "trend_price": analysis["trend_price"],
                "trend_ema": analysis["trend_ema"],
                "expected_net_reward_pct": analysis["expected_net_reward_pct"],
                "stop_distance_pct": analysis["stop_distance_pct"],
                "rsi_recovered": analysis["rsi_recovered"],
                "near_support": analysis["near_support"],
                "trend_ok": analysis["trend_ok"],
                "reward_ok": analysis["reward_ok"],
                "stop_risk_ok": analysis["stop_risk_ok"],
                "momentum_ok": analysis["momentum_ok"],
                "ema_9": analysis["ema_9"],
                "ema_21": analysis["ema_21"],
                "candles": analysis["candles"],
                "signal": market_signal(analysis),
                "status": market_statuses.get(symbol, "UNKNOWN"),
            }
            for symbol, analysis in analyses.items()
        },
    }
    try:
        with temporary_file.open("w", encoding="utf-8") as status_file:
            json.dump(status, status_file, indent=2)
    except OSError as error:
        print(f"Could not write bot-status update: {error}")
        return

    for attempt in range(6):
        try:
            temporary_file.replace(STATUS_FILE)
            return
        except PermissionError as error:
            if attempt == 5:
                print(
                    "Bot-status file remained locked; skipping this update "
                    f"and trying again next cycle: {error}"
                )
                return
            time.sleep(0.05 * (attempt + 1))
        except OSError as error:
            print(f"Could not publish bot-status update: {error}")
            return


def refresh_live_prices(client, symbols):
    previous = {}
    if LIVE_PRICE_FILE.exists():
        try:
            with LIVE_PRICE_FILE.open("r", encoding="utf-8") as live_file:
                saved = json.load(live_file)
            if saved.get("environment") == ENVIRONMENT:
                previous = saved.get("prices", {})
        except (OSError, json.JSONDecodeError, TypeError):
            previous = {}

    try:
        requested_symbols = set(symbols)
        tickers = client.get_symbol_ticker()
        ticker_prices = {
            ticker["symbol"]: Decimal(str(ticker["price"]))
            for ticker in tickers
            if ticker.get("symbol") in requested_symbols
        }
    except Exception as error:
        print(f"Could not refresh live prices: {error}")
        return

    prices = {}
    refreshed_at = int(time.time())
    for symbol in symbols:
        price = ticker_prices.get(symbol)
        if price is None:
            continue
        previous_price = Decimal(
            str(previous.get(symbol, {}).get("price", price))
        )
        if price > previous_price:
            direction = "UP"
        elif price < previous_price:
            direction = "DOWN"
        else:
            direction = "FLAT"
        change_pct = (
            ((price - previous_price) / previous_price) * Decimal("100")
            if previous_price
            else Decimal("0")
        )
        previous_market = previous.get(symbol, {})
        progress_price = Decimal(
            str(previous_market.get("progress_price", price))
        )
        last_progress_at = int(
            previous_market.get("last_progress_at", refreshed_at)
        )
        # Only a 0.1% new high counts as meaningful upward progress.
        if price >= progress_price * Decimal("1.001"):
            progress_price = price
            last_progress_at = refreshed_at
        prices[symbol] = {
            "price": str(price),
            "previous_price": str(previous_price),
            "direction": direction,
            "change_pct": str(change_pct),
            "progress_price": str(progress_price),
            "last_progress_at": last_progress_at,
        }

    temporary_file = LIVE_PRICE_FILE.with_suffix(".tmp")
    payload = {
        "environment": ENVIRONMENT,
        "updated_at": refreshed_at,
        "prices": prices,
    }
    try:
        with temporary_file.open("w", encoding="utf-8") as live_file:
            json.dump(payload, live_file, indent=2)
    except OSError as error:
        print(f"Could not write live-price update: {error}")
        return ticker_prices

    for attempt in range(6):
        try:
            temporary_file.replace(LIVE_PRICE_FILE)
            return ticker_prices
        except PermissionError as error:
            if attempt == 5:
                print(
                    "Live-price file remained locked; skipping this refresh "
                    f"and trying again in {LIVE_PRICE_REFRESH_SECONDS} seconds: "
                    f"{error}"
                )
                return ticker_prices
            time.sleep(0.05 * (attempt + 1))
        except OSError as error:
            print(f"Could not publish live-price update: {error}")
            return ticker_prices


def record_transaction(transaction):
    transaction["environment"] = ENVIRONMENT
    transaction["recorded_at"] = int(time.time())
    with TRANSACTION_FILE.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(transaction) + "\n")


def get_free_balance(client, asset):
    balance = client.get_asset_balance(asset=asset)
    return Decimal(balance["free"]) if balance else Decimal("0")


def get_spot_portfolio_value(client):
    account = client.get_account()
    prices = {
        ticker["symbol"]: Decimal(str(ticker["price"]))
        for ticker in client.get_all_tickers()
        if Decimal(str(ticker["price"])) > 0
    }

    def usdt_rate(asset):
        if asset == "USDT":
            return Decimal("1")
        direct = prices.get(f"{asset}USDT")
        if direct is not None:
            return direct
        inverse = prices.get(f"USDT{asset}")
        if inverse is not None:
            return Decimal("1") / inverse
        for bridge in ("BTC", "ETH", "BNB"):
            bridge_usdt = prices.get(f"{bridge}USDT")
            if bridge_usdt is None:
                continue
            if asset == bridge:
                return bridge_usdt
            asset_bridge = prices.get(f"{asset}{bridge}")
            if asset_bridge is not None:
                return asset_bridge * bridge_usdt
            bridge_asset = prices.get(f"{bridge}{asset}")
            if bridge_asset is not None:
                return bridge_usdt / bridge_asset
        return None

    available_usdt = Decimal("0")
    total_usdt = Decimal("0")
    unpriced_assets = []
    for balance in account.get("balances", []):
        asset = str(balance["asset"])
        free = Decimal(str(balance["free"]))
        locked = Decimal(str(balance["locked"]))
        quantity = free + locked
        if asset == "USDT":
            available_usdt = free
        if quantity <= 0:
            continue
        rate = usdt_rate(asset)
        if rate is None:
            unpriced_assets.append(asset)
            continue
        total_usdt += quantity * rate
    return available_usdt, total_usdt, sorted(unpriced_assets)


def get_market_rules(client, symbol):
    symbol_info = client.get_symbol_info(symbol)
    if not symbol_info:
        raise RuntimeError(f"Could not load exchange rules for {symbol}.")
    if symbol_info["status"] != "TRADING":
        raise RuntimeError(f"{symbol} is not currently open for trading.")
    if symbol_info["quoteAsset"] != "USDT":
        raise RuntimeError(f"{symbol} must use USDT as its quote asset.")

    filters = {item["filterType"]: item for item in symbol_info["filters"]}
    lot_size = filters["LOT_SIZE"]
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
    quote_precision = int(
        symbol_info.get("quoteAssetPrecision", symbol_info.get("quotePrecision", 8))
    )
    quote_precision = max(0, min(20, quote_precision))
    return {
        "base_asset": symbol_info["baseAsset"],
        "quote_asset": symbol_info["quoteAsset"],
        "quote_precision": quote_precision,
        "step_size": Decimal(lot_size["stepSize"]),
        "min_quantity": Decimal(lot_size["minQty"]),
        "min_notional": Decimal(notional.get("minNotional", "0")),
    }


def classify_market_overview(markets):
    if not markets:
        return {
            "regime": "DATA UNAVAILABLE",
            "expectation": "No liquid-market sample is available.",
            "sample_size": 0,
        }

    sample_size = len(markets)
    up_pct = sum(
        item["change_pct"] >= MARKET_DIRECTION_THRESHOLD_PCT for item in markets
    ) / sample_size * 100
    down_pct = sum(
        item["change_pct"] <= -MARKET_DIRECTION_THRESHOLD_PCT for item in markets
    ) / sample_size * 100
    active_pct = sum(
        item["range_pct"] >= MARKET_ACTIVE_RANGE_PCT for item in markets
    ) / sample_size * 100
    median_change = statistics.median(item["change_pct"] for item in markets)
    median_range = statistics.median(item["range_pct"] for item in markets)
    is_quiet = (
        active_pct < MARKET_QUIET_ACTIVE_BREADTH_PCT
        or median_range < MARKET_ACTIVE_RANGE_PCT
    )

    if is_quiet:
        if (
            median_change <= -MARKET_MEDIAN_DIRECTION_THRESHOLD_PCT
            or down_pct >= up_pct + 15
        ):
            regime = "QUIET / WEAK"
            expectation = "Expect fewer quality buys; avoid forcing entries."
        elif (
            median_change >= MARKET_MEDIAN_DIRECTION_THRESHOLD_PCT
            or up_pct >= down_pct + 15
        ):
            regime = "QUIET / POSITIVE"
            expectation = "Momentum is positive but participation is limited."
        else:
            regime = "QUIET / MIXED"
            expectation = "Expect fewer signals and uneven price movement."
    elif median_change >= MARKET_MEDIAN_DIRECTION_THRESHOLD_PCT or up_pct >= 60:
        regime = "ACTIVE / POSITIVE"
        expectation = "Broad momentum is positive; still require entry confirmation."
    elif median_change <= -MARKET_MEDIAN_DIRECTION_THRESHOLD_PCT or down_pct >= 60:
        regime = "ACTIVE / WEAK"
        expectation = "Broad selling pressure is elevated; new longs need caution."
    else:
        regime = "ACTIVE / MIXED"
        expectation = "Movement is sufficient, but market direction is divided."

    return {
        "regime": regime,
        "expectation": expectation,
        "sample_size": sample_size,
        "up_pct": round(up_pct, 1),
        "down_pct": round(down_pct, 1),
        "active_pct": round(active_pct, 1),
        "median_change_pct": round(median_change, 2),
        "median_range_pct": round(median_range, 2),
        "formula": (
            "Liquid non-stable USDT pairs: volume >= 10M; up/down threshold "
            "+/-1.5%; active logarithmic range threshold 3.0%; quiet active "
            "breadth threshold 35%; median direction threshold +/-1.0%."
        ),
    }


def record_market_overview(overview):
    record = {
        "recorded_at": int(time.time()),
        "environment": ENVIRONMENT,
        **overview,
    }
    try:
        with MARKET_OVERVIEW_HISTORY_FILE.open("a", encoding="utf-8") as history:
            history.write(json.dumps(record) + "\n")
    except OSError as error:
        print(f"Could not record market overview history: {error}")


def get_market_suggestions(client, estimated_round_trip_fee_pct):
    candidates = []
    overview_markets = []
    for ticker in client.get_ticker():
        symbol = ticker["symbol"]
        base_asset = symbol[:-4] if symbol.endswith("USDT") else ""
        if (
            not symbol.endswith("USDT")
            or base_asset in STABLE_BASE_ASSETS
            or any(symbol.endswith(suffix) for suffix in (
                "UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"
            ))
        ):
            continue
        quote_volume = float(ticker["quoteVolume"])
        change_pct = float(ticker["priceChangePercent"])
        weighted_average = float(ticker["weightedAvgPrice"])
        if weighted_average <= 0:
            continue
        high_price = float(ticker["highPrice"])
        low_price = float(ticker["lowPrice"])
        if high_price <= 0 or low_price <= 0 or high_price < low_price:
            continue
        range_pct = math.log(high_price / low_price) * 100
        if quote_volume >= MARKET_OVERVIEW_MIN_QUOTE_VOLUME:
            overview_markets.append(
                {
                    "change_pct": change_pct,
                    "range_pct": range_pct,
                }
            )
        if quote_volume < WATCHLIST_MIN_QUOTE_VOLUME:
            continue
        if range_pct < WATCHLIST_MIN_RANGE_PCT:
            continue
        estimated_net_range = max(
            0, range_pct - float(estimated_round_trip_fee_pct)
        )
        if change_pct >= 10:
            momentum_note = "Strong positive momentum; pullback risk is elevated."
        elif change_pct > 0:
            momentum_note = "Positive momentum with comparatively lower extension."
        elif change_pct <= -10:
            momentum_note = "Strong negative momentum; downside risk is elevated."
        else:
            momentum_note = "Negative momentum; wait for recovery confirmation."
        candidates.append(
            {
                "symbol": symbol,
                "price": float(ticker["lastPrice"]),
                "change_pct": change_pct,
                "range_pct": range_pct,
                "quote_volume_usdt": quote_volume,
                "analysis": (
                    f"{change_pct:+.1f}% 24h change, {range_pct:.1f}% "
                    f"24h range, and {quote_volume / 1_000_000:.1f}M USDT volume. "
                    f"Range after estimated costs: {estimated_net_range:.1f}%. "
                    f"{momentum_note}"
                ),
            }
        )
    candidates.sort(key=lambda item: item["range_pct"], reverse=True)
    return candidates[:WATCHLIST_LIMIT], classify_market_overview(overview_markets)


def round_to_step(quantity, step_size):
    return (quantity / step_size).to_integral_value(rounding=ROUND_DOWN) * step_size


def current_exposure(positions):
    return sum(
        (Decimal(position["entry"]) * Decimal(position["quantity"]) for position in positions.values()),
        Decimal("0"),
    )


def minimum_net_exit_price(entry, quantity, minimum_net_profit, round_trip_fee_pct):
    one_way_fee_rate = Decimal(str(round_trip_fee_pct)) / Decimal("200")
    if quantity <= 0 or one_way_fee_rate >= 1:
        return entry
    return (
        entry * quantity * (Decimal("1") + one_way_fee_rate)
        + Decimal(str(minimum_net_profit))
    ) / (quantity * (Decimal("1") - one_way_fee_rate))


def buy(
    client, symbol, rules, analysis, positions, maximum_exposure, trade_amount,
    max_open_positions, reason="strategy buy signal", allow_existing=False,
):
    existing_position = positions.get(symbol)
    if existing_position and not allow_existing:
        return None
    if not existing_position and len(positions) >= max_open_positions:
        print_status(
            f"{symbol} BUY skipped: maximum open positions reached.", "yellow"
        )
        return None

    remaining_exposure = maximum_exposure - current_exposure(positions)
    available_usdt = get_free_balance(client, rules["quote_asset"])
    amount = min(trade_amount, remaining_exposure, available_usdt)
    quote_step = Decimal("1").scaleb(-rules["quote_precision"])
    amount = round_to_step(amount, quote_step)
    if amount < rules["min_notional"] or amount <= 0:
        print_status(
            f"{symbol} BUY skipped: insufficient balance or exposure allowance.",
            "yellow",
        )
        return None

    entry_conditions = capture_entry_conditions(analysis)
    order = client.create_order(
        symbol=symbol,
        side=Client.SIDE_BUY,
        type=Client.ORDER_TYPE_MARKET,
        quoteOrderQty=format(amount, "f"),
        newOrderRespType="FULL",
    )
    executed_quantity = Decimal(order["executedQty"])
    quote_spent = Decimal(order["cummulativeQuoteQty"])
    average_price = quote_spent / executed_quantity
    stop_distance = Decimal(str(analysis["stop_distance"]))
    reward_distance = Decimal(str(analysis["tp"] - analysis["entry"]))
    if existing_position:
        existing_quantity = Decimal(existing_position["quantity"])
        existing_entry = Decimal(existing_position["entry"])
        combined_quantity = existing_quantity + executed_quantity
        average_price = (
            existing_entry * existing_quantity + quote_spent
        ) / combined_quantity
        executed_quantity = combined_quantity

    minimum_profit_price = minimum_net_exit_price(
        average_price,
        executed_quantity,
        analysis.get("min_net_profit_usdt", DEFAULT_MIN_NET_PROFIT_USDT),
        analysis.get(
            "estimated_round_trip_fee_pct",
            DEFAULT_ESTIMATED_ROUND_TRIP_FEE_PCT,
        ),
    )
    take_profit = max(average_price + reward_distance, minimum_profit_price)

    position = {
        "symbol": symbol,
        "base_asset": rules["base_asset"],
        "quote_asset": rules["quote_asset"],
        "order_id": order["orderId"],
        "quantity": str(executed_quantity),
        "entry": str(average_price),
        "stop_loss": str(average_price - stop_distance),
        "take_profit": str(take_profit),
        "strategy_take_profit": str(average_price + reward_distance),
        "entry_conditions": (
            existing_position.get("entry_conditions")
            if existing_position else entry_conditions
        ),
        "signal_candle_close_time": int(
            analysis["signal_candle_close_time"]
        ),
        "opened_at": (
            existing_position.get("opened_at", int(time.time()))
            if existing_position else int(time.time())
        ),
    }
    positions[symbol] = position
    save_positions(positions)
    record_transaction(
        {
            "side": "BUY", "symbol": symbol, "order_id": order["orderId"],
            "quantity": str(Decimal(order["executedQty"])),
            "price": str(quote_spent / Decimal(order["executedQty"])),
            "quote_amount": str(quote_spent), "quote_asset": rules["quote_asset"],
            "signal_candle_close_time": int(
                analysis["signal_candle_close_time"]
            ),
            "reason": reason,
            "entry_conditions": entry_conditions,
        }
    )
    print_status(
        f"{symbol} {'BUY MORE' if existing_position else 'BUY'} filled: "
        f"position is now {executed_quantity} {rules['base_asset']} "
        f"at an average entry of {average_price:.8f}",
        "bold green",
    )
    return position


def sell(client, symbol, rules, position, analysis, positions, reason):
    tracked_quantity = Decimal(position["quantity"])
    available_quantity = get_free_balance(client, rules["base_asset"])
    quantity = round_to_step(
        min(tracked_quantity, available_quantity), rules["step_size"]
    )
    notional = quantity * Decimal(str(analysis["entry"]))
    if quantity < rules["min_quantity"] or notional < rules["min_notional"]:
        print_status(
            f"{symbol} SELL skipped: free {rules['base_asset']} is below "
            "the exchange minimum.",
            "yellow",
        )
        return None

    order = client.create_order(
        symbol=symbol,
        side=Client.SIDE_SELL,
        type=Client.ORDER_TYPE_MARKET,
        quantity=format(quantity, "f"),
        newOrderRespType="FULL",
    )
    executed_quantity = Decimal(order["executedQty"])
    quote_received = Decimal(order["cummulativeQuoteQty"])
    average_price = quote_received / executed_quantity
    entry_price = Decimal(position["entry"])
    estimated_pnl = (average_price - entry_price) * executed_quantity
    record_transaction(
        {
            "side": "SELL", "symbol": symbol, "order_id": order["orderId"],
            "quantity": str(executed_quantity), "price": str(average_price),
            "quote_amount": str(quote_received), "quote_asset": rules["quote_asset"],
            "reason": reason, "estimated_pnl_usdt": str(estimated_pnl),
        }
    )
    positions.pop(symbol, None)
    save_positions(positions)
    print_status(
        f"{symbol} SELL filled: {executed_quantity}. Reason: {reason}",
        "bold red",
    )
    return order


def load_claimed_sell_requests():
    if not SELL_PROCESSING_FILE.exists() and SELL_REQUEST_FILE.exists():
        try:
            SELL_REQUEST_FILE.replace(SELL_PROCESSING_FILE)
        except OSError:
            return []
    if not SELL_PROCESSING_FILE.exists():
        return []
    requests = []
    try:
        for line in SELL_PROCESSING_FILE.read_text(encoding="utf-8").splitlines():
            try:
                requests.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return requests


def save_remaining_sell_requests(requests):
    if not requests:
        if SELL_PROCESSING_FILE.exists():
            SELL_PROCESSING_FILE.unlink()
        return
    temporary_file = SELL_PROCESSING_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        "".join(json.dumps(request) + "\n" for request in requests),
        encoding="utf-8",
    )
    temporary_file.replace(SELL_PROCESSING_FILE)


def process_sell_requests(client, positions, rules_by_symbol):
    requests = load_claimed_sell_requests()
    while requests:
        request = requests.pop(0)
        # Remove the request before placing an order: a crash may lose a request,
        # but it cannot replay a real-money sell after restart.
        save_remaining_sell_requests(requests)
        symbol = str(request.get("symbol", "")).upper()
        action = request.get("action")
        if action not in {"SELL_MARKET", "SET_SELL_PRICE"}:
            print(f"{symbol} manual SELL rejected: unknown action.")
            continue
        if time.time() - int(request.get("created_at", 0)) > 30:
            print(f"{symbol} manual SELL rejected: request expired.")
            continue
        if request.get("environment") != ENVIRONMENT:
            print(f"{symbol} manual SELL rejected: environment mismatch.")
            continue
        position = positions.get(symbol)
        if not position:
            print(f"{symbol} manual SELL skipped: no tracked open position.")
            continue
        if action == "SET_SELL_PRICE":
            try:
                sell_price = Decimal(str(request.get("sell_price")))
            except InvalidOperation:
                print(f"{symbol} sell-price update rejected: invalid price.")
                continue
            if not sell_price.is_finite() or sell_price <= 0:
                print(f"{symbol} sell-price update rejected: price must be positive.")
                continue
            if sell_price <= Decimal(position["entry"]):
                print(
                    f"{symbol} sell-price update rejected: target must be "
                    "above the entry price. Use Sell now for an immediate exit."
                )
                continue
            position["take_profit"] = str(sell_price)
            position["manual_take_profit"] = True
            save_positions(positions)
            print(
                f"{symbol} bot-managed sell price updated to {sell_price}."
            )
            continue
        try:
            if symbol not in rules_by_symbol:
                rules_by_symbol[symbol] = get_market_rules(client, symbol)
            ticker = client.get_symbol_ticker(symbol=symbol)
            analysis = {"entry": float(ticker["price"])}
            sell(
                client, symbol, rules_by_symbol[symbol], position, analysis,
                positions, "dashboard manual sell",
            )
        except (BinanceAPIException, BinanceOrderException) as error:
            print(f"{symbol} manual SELL Binance error: {error}")
        except Exception as error:
            print(f"{symbol} manual SELL error: {error}")


def load_claimed_buy_requests():
    if not BUY_PROCESSING_FILE.exists() and BUY_REQUEST_FILE.exists():
        try:
            BUY_REQUEST_FILE.replace(BUY_PROCESSING_FILE)
        except OSError:
            return []
    if not BUY_PROCESSING_FILE.exists():
        return []
    requests = []
    try:
        for line in BUY_PROCESSING_FILE.read_text(encoding="utf-8").splitlines():
            try:
                requests.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return requests


def save_remaining_buy_requests(requests):
    if not requests:
        if BUY_PROCESSING_FILE.exists():
            BUY_PROCESSING_FILE.unlink()
        return
    temporary_file = BUY_PROCESSING_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        "".join(json.dumps(request) + "\n" for request in requests),
        encoding="utf-8",
    )
    temporary_file.replace(BUY_PROCESSING_FILE)


def process_buy_requests(client, positions, rules_by_symbol, runtime_config):
    requests = load_claimed_buy_requests()
    while requests:
        request = requests.pop(0)
        # Remove before placing an order so a crash cannot replay a real-money buy.
        save_remaining_buy_requests(requests)
        symbol = str(request.get("symbol", "")).upper()
        if request.get("action") != "BUY_MARKET":
            print(f"{symbol} manual BUY rejected: unknown action.")
            continue
        if time.time() - int(request.get("created_at", 0)) > 30:
            print(f"{symbol} manual BUY rejected: request expired.")
            continue
        if request.get("environment") != ENVIRONMENT:
            print(f"{symbol} manual BUY rejected: environment mismatch.")
            continue
        if runtime_config["trading_on_hold"]:
            print(f"{symbol} manual BUY rejected: new buys are on hold.")
            continue
        if symbol not in runtime_config["target_symbols"]:
            print(f"{symbol} manual BUY rejected: symbol is not a target.")
            continue
        try:
            requested_amount = Decimal(str(request.get("amount_usdt", "20")))
        except InvalidOperation:
            print(f"{symbol} manual BUY rejected: invalid USDT amount.")
            continue
        if not requested_amount.is_finite() or requested_amount <= 0:
            print(f"{symbol} manual BUY rejected: USDT amount must be positive.")
            continue
        try:
            if symbol not in rules_by_symbol:
                rules_by_symbol[symbol] = get_market_rules(client, symbol)
            analysis = analyze_market(
                client, symbol, runtime_config["interval"], runtime_config
            )
            buy(
                client, symbol, rules_by_symbol[symbol], analysis, positions,
                runtime_config["max_total_exposure_usdt"],
                requested_amount,
                runtime_config["max_open_positions"],
                (
                    "dashboard manual buy more"
                    if symbol in positions else "dashboard manual buy"
                ),
                allow_existing=True,
            )
        except (BinanceAPIException, BinanceOrderException) as error:
            print(f"{symbol} manual BUY Binance error: {error}")
        except Exception as error:
            print(f"{symbol} manual BUY error: {error}")


def check_live_take_profits(client, positions, rules_by_symbol, prices):
    """Use fresh ticker prices for TP only; SL remains candle-close based."""
    if not TRADING_ENABLED or not prices:
        return
    for symbol, position in list(positions.items()):
        try:
            if symbol not in prices:
                continue
            price = Decimal(str(prices[symbol]))
            target = Decimal(str(position["take_profit"]))
            if not price.is_finite() or not target.is_finite():
                continue
            if price <= 0 or target <= 0 or price < target:
                continue
            if symbol not in rules_by_symbol:
                rules_by_symbol[symbol] = get_market_rules(client, symbol)
            sell(
                client, symbol, rules_by_symbol[symbol], position,
                {"entry": price}, positions, "take profit",
            )
        except Exception as error:
            print(f"{symbol} live take-profit error: {error}")


def wait_for_next_cycle(
    client, positions, rules_by_symbol, active_symbols, runtime_config,
):
    poll_seconds = max(10, int(runtime_config.get("poll_seconds", POLL_SECONDS)))
    live_refresh = max(2, int(runtime_config.get("live_price_refresh_seconds", LIVE_PRICE_REFRESH_SECONDS)))
    deadline = time.monotonic() + poll_seconds
    next_refresh = time.monotonic() + live_refresh
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        time.sleep(min(2, deadline - now, max(0, next_refresh - now)))
        now = time.monotonic()
        if now >= deadline:
            break
        if now >= next_refresh:
            prices = refresh_live_prices(
                client, list(dict.fromkeys(active_symbols + list(positions)))
            )
            check_live_take_profits(client, positions, rules_by_symbol, prices)
            next_refresh = time.monotonic() + live_refresh
        if TRADING_ENABLED:
            process_sell_requests(client, positions, rules_by_symbol)
            process_buy_requests(
                client, positions, rules_by_symbol, runtime_config
            )


def automatic_buys_paused(market_overview, ignore_weak_market=False):
    regime = str((market_overview or {}).get("regime", "")).strip().upper()
    return regime == "ACTIVE / WEAK" and not ignore_weak_market


def decide_and_trade(
    client, symbol, rules, analysis, positions, maximum_exposure, trade_amount,
    max_open_positions, trading_on_hold, last_entry_candle,
    market_overview=None, ignore_weak_market=False,
):
    position = positions.get(symbol)
    price = Decimal(str(analysis["entry"]))
    if position:
        minimum_profit_price = minimum_net_exit_price(
            Decimal(position["entry"]),
            Decimal(position["quantity"]),
            analysis.get("min_net_profit_usdt", DEFAULT_MIN_NET_PROFIT_USDT),
            analysis.get(
                "estimated_round_trip_fee_pct",
                DEFAULT_ESTIMATED_ROUND_TRIP_FEE_PCT,
            ),
        )
        if not position.get("manual_take_profit"):
            # Older positions did not store the strategy target separately.
            # Reconstruct it once from their original stop distance and the
            # current reward/risk setting, then keep it fixed as prices move.
            changed = False
            if "strategy_take_profit" not in position:
                entry = Decimal(position["entry"])
                stop_distance = max(entry - Decimal(position["stop_loss"]), Decimal("0"))
                ratio = Decimal(str(analysis.get("risk_reward_ratio", DEFAULT_RISK_REWARD_RATIO)))
                position["strategy_take_profit"] = str(entry + stop_distance * ratio)
                changed = True
            target = max(Decimal(position["strategy_take_profit"]), minimum_profit_price)
            if target != Decimal(position["take_profit"]):
                position["take_profit"] = str(target)
                changed = True
            if changed:
                save_positions(positions)
        if price <= Decimal(position["stop_loss"]):
            order = sell(client, symbol, rules, position, analysis, positions, "stop loss")
            return "SELL FILLED" if order else "SELL SKIPPED"
        elif price >= Decimal(position["take_profit"]):
            order = sell(client, symbol, rules, position, analysis, positions, "take profit")
            return "SELL FILLED" if order else "SELL SKIPPED"
        elif analysis["sell_signal"]:
            one_way_fee_rate = Decimal(str(analysis.get(
                "estimated_round_trip_fee_pct",
                DEFAULT_ESTIMATED_ROUND_TRIP_FEE_PCT,
            ))) / Decimal("200")
            quantity = Decimal(position["quantity"])
            entry = Decimal(position["entry"])
            estimated_net_profit = (
                (price - entry) * quantity
                - (entry * quantity + price * quantity) * one_way_fee_rate
            )
            minimum_net_profit = Decimal(str(analysis.get(
                "min_net_profit_usdt", DEFAULT_MIN_NET_PROFIT_USDT
            )))
            if estimated_net_profit < minimum_net_profit:
                return "WAITING FOR MIN NET PROFIT"
            order = sell(
                client, symbol, rules, position, analysis, positions, "RSI sell signal"
            )
            return "SELL FILLED" if order else "SELL SKIPPED"
        else:
            return "MONITORING"

    if trading_on_hold:
        return "ON HOLD"

    if automatic_buys_paused(market_overview, ignore_weak_market):
        return "WEAK MARKET PAUSE"

    if analysis["buy_signal"]:
        signal_candle = int(analysis["signal_candle_close_time"])
        if last_entry_candle.get(symbol) == signal_candle:
            return "WAITING FOR NEW CANDLE"
        position = buy(
            client, symbol, rules, analysis, positions, maximum_exposure,
            trade_amount, max_open_positions,
        )
        if position:
            last_entry_candle[symbol] = signal_candle
            save_entry_cooldowns(last_entry_candle)
        return "BUY FILLED" if position else "BUY SKIPPED"
    else:
        return "WAITING TO BUY"


def print_report(symbol, analysis):
    verdict = market_signal(analysis)
    signal_style = {
        "BUY": "bold green",
        "SELL": "bold red",
        "HOLD": "bold yellow",
    }.get(verdict, "bold cyan")
    console.rule(f"[bold cyan]{symbol}[/bold cyan]")
    console.print(
        f"[bold]{symbol}[/bold] | Price: [cyan]{analysis['entry']:.8f}[/cyan] | "
        f"RSI: [magenta]{analysis['rsi']:.2f}[/magenta]"
    )
    console.print(
        f"ATR: [magenta]{analysis['atr']:.8f}[/magenta] | "
        f"Support: [green]{analysis['support']:.8f}[/green]"
    )
    console.print(
        f"Resistance: [red]{analysis['resistance']:.8f}[/red] | "
        f"Signal: [{signal_style}]{verdict}[/{signal_style}]"
    )
    console.print(
        f"Suggested SL: [red]{analysis['sl']:.8f}[/red] | "
        f"Suggested TP: [green]{analysis['tp']:.8f}[/green]"
    )
    print_status(
        "Buy checks | "
        f"RSI recovery: {'YES' if analysis['rsi_recovered'] else 'NO'} | "
        f"Near support: {'YES' if analysis['near_support'] else 'NO'} | "
        f"Trend: {'YES' if analysis['trend_ok'] else 'NO'} | "
        f"Net reward: {'YES' if analysis['reward_ok'] else 'NO'} | "
        f"Stop risk: {'YES' if analysis['stop_risk_ok'] else 'NO'}"
        f" | Momentum EMA 9>21: {'YES' if analysis['momentum_ok'] else 'NO'}"
    )
    print(
        f"Trend: {analysis['trend_interval']} EMA {analysis['trend_ema_period']} "
        f"= {analysis['trend_ema']:.8f} | "
        f"Expected net reward: {analysis['expected_net_reward_pct']:.3f}% | "
        f"Stop distance: {analysis['stop_distance_pct']:.3f}%"
    )
    console.rule(style="cyan")


def main():
    acquire_instance_lock()
    client = create_client_with_retry()
    positions = load_positions()
    last_entry_candle = load_entry_cooldowns()
    cooldowns_recovered = False
    for symbol, position in positions.items():
        signal_candle = position.get("signal_candle_close_time")
        if signal_candle is None:
            continue
        signal_candle = int(signal_candle)
        if last_entry_candle.get(symbol) != signal_candle:
            last_entry_candle[symbol] = signal_candle
            cooldowns_recovered = True
    if cooldowns_recovered:
        save_entry_cooldowns(last_entry_candle)
    rules_by_symbol = {}
    suggestions = []
    market_overview = {}
    suggestions_updated_at = 0
    previous_market_state = None
    mode = f"{ENVIRONMENT.upper()} TRADING" if TRADING_ENABLED else "ANALYSIS ONLY"
    mode_style = "bold green" if TRADING_ENABLED else "bold yellow"
    console.print(
        f"[bold cyan]Multi-market bot[/bold cyan] | "
        f"[{mode_style}]{mode}[/{mode_style}] | Press Ctrl+C to stop"
    )
    while True:
        try:
            if TRADING_ENABLED:
                process_sell_requests(client, positions, rules_by_symbol)
            runtime_config = load_runtime_config()
            target_symbols = runtime_config["target_symbols"]
            maximum_exposure = runtime_config["max_total_exposure_usdt"]
            trade_amount = runtime_config["trade_amount_usdt"]
            max_open_positions = runtime_config["max_open_positions"]
            trading_on_hold = runtime_config["trading_on_hold"]
            interval = runtime_config["interval"]
            if TRADING_ENABLED:
                process_buy_requests(
                    client, positions, rules_by_symbol, runtime_config
                )
            # An open position is always monitored even if removed from targets.
            active_symbols = list(
                dict.fromkeys(target_symbols + list(positions.keys()))
            )
            prices = refresh_live_prices(client, active_symbols)
            check_live_take_profits(client, positions, rules_by_symbol, prices)
            if time.time() - suggestions_updated_at >= SUGGESTION_REFRESH_SECONDS:
                try:
                    suggestions, market_overview = get_market_suggestions(
                        client,
                        runtime_config["estimated_round_trip_fee_pct"],
                    )
                    record_market_overview(market_overview)
                    suggestions_updated_at = time.time()
                except Exception as error:
                    print(f"Could not refresh market suggestions: {error}")
            if time.time() - suggestions_updated_at < SUGGESTION_REFRESH_SECONDS:
                if apply_watchlist_automation(CONFIG_FILE, suggestions):
                    runtime_config = load_runtime_config()
                    target_symbols = runtime_config["target_symbols"]
                    active_symbols = list(dict.fromkeys(
                        target_symbols + list(positions.keys())
                    ))
            market_state = (
                market_overview.get("regime", "UNKNOWN"), trading_on_hold,
                runtime_config["ignore_weak_market"],
            )
            if market_state != previous_market_state:
                print_status(
                    f"Market: {market_state[0]} | Hold: {trading_on_hold} | "
                    f"Ignore weak market: {market_state[2]}", "cyan"
                )
                previous_market_state = market_state
            analyses = {}
            market_statuses = {}
            for symbol in active_symbols:
                try:
                    if symbol not in rules_by_symbol:
                        rules_by_symbol[symbol] = get_market_rules(client, symbol)
                    analysis = analyze_market(
                        client, symbol, interval, runtime_config
                    )
                    analyses[symbol] = analysis
                    if TRADING_ENABLED:
                        market_statuses[symbol] = decide_and_trade(
                            client, symbol, rules_by_symbol[symbol], analysis, positions,
                            maximum_exposure, trade_amount, max_open_positions,
                            trading_on_hold, last_entry_candle, market_overview,
                            ignore_weak_market=runtime_config["ignore_weak_market"],
                        )
                    else:
                        market_statuses[symbol] = "ANALYSIS ONLY"
                except (BinanceAPIException, BinanceOrderException) as error:
                    print_status(f"{symbol} Binance error: {error}", "bold red")
                    market_statuses[symbol] = "BINANCE ERROR"
                except Exception as error:
                    print_status(f"{symbol} error: {error}", "bold red")
                    market_statuses[symbol] = "ERROR"
            try:
                available_usdt, total_portfolio_usdt, unpriced_assets = (
                    get_spot_portfolio_value(client)
                )
                save_status(
                    available_usdt, total_portfolio_usdt, unpriced_assets,
                    analyses, market_statuses, target_symbols,
                    maximum_exposure, trade_amount,
                    max_open_positions, trading_on_hold, interval, suggestions,
                    market_overview, runtime_config,
                )
            except Exception as error:
                print_status(f"Could not update account status: {error}", "bold red")
            counts = Counter(market_statuses.values())
            outcomes = ", ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
            print_status(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"Checked {len(analyses)}/{len(active_symbols)} | "
                f"Open {len(positions)}/{max_open_positions} | {outcomes}",
                "cyan",
            )
            wait_for_next_cycle(
                client, positions, rules_by_symbol, active_symbols,
                runtime_config,
            )
        except KeyboardInterrupt:
            print_status("\nStopped.", "bold yellow")
            break
        except Exception as error:
            print_status(
                "Bot cycle failed: "
                f"{type(error).__name__}: {error}. Retrying in "
                f"{BINANCE_RECONNECT_SECONDS} seconds.",
                "bold red",
            )
            time.sleep(BINANCE_RECONNECT_SECONDS)


if __name__ == "__main__":
    main()
