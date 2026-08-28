import json
import msvcrt
import os
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException


# INTERVAL = Client.KLINE_INTERVAL_1MINUTE
INTERVAL = Client.KLINE_INTERVAL_15MINUTE
SUPPORTED_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
    "12h", "1d", "3d", "1w", "1M",
}
RISK_REWARD_RATIO = Decimal("2")
ATR_SL_MULTIPLIER = Decimal("1.5")
TRADE_AMOUNT_USDT = Decimal(os.getenv("TRADE_AMOUNT_USDT", "25"))
DEFAULT_MAX_TOTAL_EXPOSURE_USDT = Decimal(
    os.getenv("MAX_TOTAL_EXPOSURE_USDT", "75")
)
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
POLL_SECONDS = 60
LIVE_PRICE_REFRESH_SECONDS = 10
SUGGESTION_REFRESH_SECONDS = 15 * 60

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
TRANSACTION_FILE = Path(__file__).with_name("transactions.jsonl")
STATUS_FILE = Path(__file__).with_name("bot_status.json")
LIVE_PRICE_FILE = Path(__file__).with_name("live_prices.json")
CONFIG_FILE = Path(__file__).with_name("bot_config.json")
SELL_REQUEST_FILE = Path(__file__).with_name("sell_requests.jsonl")
SELL_PROCESSING_FILE = Path(__file__).with_name("sell_requests.processing.jsonl")
LOCK_FILE = Path(__file__).with_name("bot.lock")
INSTANCE_LOCK_HANDLE = None


def create_client():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("Set BINANCE_API_KEY and BINANCE_API_SECRET.")
    return Client(api_key.strip(), api_secret.strip(), testnet=TESTNET)


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
        "interval": INTERVAL,
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
        if not symbols:
            raise ValueError("At least one target symbol is required.")
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
        config["target_symbols"] = list(symbols)
        config["max_total_exposure_usdt"] = maximum_exposure
        config["trade_amount_usdt"] = trade_amount
        config["max_open_positions"] = max_open_positions
        config["trading_on_hold"] = trading_on_hold
        config["interval"] = interval
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


def analyze_market(client, symbol, interval):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=100)
    columns = [
        "time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
    ]
    data = pd.DataFrame(klines, columns=columns)
    for column in ["open", "high", "low", "close", "volume"]:
        data[column] = data[column].astype(float)

    completed = data.iloc[:-1]
    entry_price = completed["close"].iloc[-1]
    rsi = calculate_rsi(completed).iloc[-1]
    atr = calculate_atr(completed).iloc[-1]
    support = completed["low"].tail(20).min()
    resistance = completed["high"].tail(20).max()
    stop_distance = atr * float(ATR_SL_MULTIPLIER)
    return {
        "entry": entry_price,
        "sl": entry_price - stop_distance,
        "tp": entry_price + stop_distance * float(RISK_REWARD_RATIO),
        "rsi": rsi,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "distance_to_support_pct": ((entry_price - support) / entry_price) * 100,
    }


def market_signal(analysis):
    if analysis["rsi"] <= 35 or analysis["distance_to_support_pct"] <= 0.2:
        return "BUY SIGNAL"
    if analysis["rsi"] >= 65:
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


def save_status(
    available_usdt, analyses, market_statuses, target_symbols, maximum_exposure,
    trade_amount, max_open_positions, trading_on_hold, interval, suggestions,
):
    temporary_file = STATUS_FILE.with_suffix(".tmp")
    status = {
        "environment": ENVIRONMENT,
        "updated_at": int(time.time()),
        "available_usdt": str(available_usdt),
        "trade_amount_usdt": str(trade_amount),
        "max_open_positions": max_open_positions,
        "trading_on_hold": trading_on_hold,
        "interval": interval,
        "target_symbols": list(target_symbols),
        "max_total_exposure_usdt": str(maximum_exposure),
        "market_statuses": market_statuses,
        "trading_enabled": TRADING_ENABLED,
        "suggestions": suggestions,
        "markets": {
            symbol: {
                "price": analysis["entry"],
                "rsi": analysis["rsi"],
                "atr": analysis["atr"],
                "support": analysis["support"],
                "resistance": analysis["resistance"],
                "suggested_sl": analysis["sl"],
                "suggested_tp": analysis["tp"],
                "signal": market_signal(analysis),
                "status": market_statuses.get(symbol, "UNKNOWN"),
            }
            for symbol, analysis in analyses.items()
        },
    }
    with temporary_file.open("w", encoding="utf-8") as status_file:
        json.dump(status, status_file, indent=2)
    temporary_file.replace(STATUS_FILE)


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
        prices[symbol] = {
            "price": str(price),
            "previous_price": str(previous_price),
            "direction": direction,
            "change_pct": str(change_pct),
        }

    temporary_file = LIVE_PRICE_FILE.with_suffix(".tmp")
    payload = {
        "environment": ENVIRONMENT,
        "updated_at": int(time.time()),
        "prices": prices,
    }
    try:
        with temporary_file.open("w", encoding="utf-8") as live_file:
            json.dump(payload, live_file, indent=2)
    except OSError as error:
        print(f"Could not write live-price update: {error}")
        return

    for attempt in range(6):
        try:
            temporary_file.replace(LIVE_PRICE_FILE)
            return
        except PermissionError as error:
            if attempt == 5:
                print(
                    "Live-price file remained locked; skipping this refresh "
                    f"and trying again in {LIVE_PRICE_REFRESH_SECONDS} seconds: "
                    f"{error}"
                )
                return
            time.sleep(0.05 * (attempt + 1))
        except OSError as error:
            print(f"Could not publish live-price update: {error}")
            return


def record_transaction(transaction):
    transaction["environment"] = ENVIRONMENT
    transaction["recorded_at"] = int(time.time())
    with TRANSACTION_FILE.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(transaction) + "\n")


def get_free_balance(client, asset):
    balance = client.get_asset_balance(asset=asset)
    return Decimal(balance["free"]) if balance else Decimal("0")


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


def get_market_suggestions(client):
    excluded_symbols = {
        "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "USDPUSDT", "DAIUSDT",
        "EURUSDT", "TRYUSDT", "AEURUSDT", "BFUSDUSDT", "USDEUSDT",
    }
    candidates = []
    for ticker in client.get_ticker():
        symbol = ticker["symbol"]
        if (
            not symbol.endswith("USDT")
            or symbol in excluded_symbols
            or any(symbol.endswith(suffix) for suffix in (
                "UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"
            ))
        ):
            continue
        quote_volume = float(ticker["quoteVolume"])
        change_pct = float(ticker["priceChangePercent"])
        weighted_average = float(ticker["weightedAvgPrice"])
        if quote_volume < 30_000_000 or change_pct <= 0 or weighted_average <= 0:
            continue
        range_pct = (
            (float(ticker["highPrice"]) - float(ticker["lowPrice"]))
            / weighted_average
            * 100
        )
        risk_note = (
            "Strong momentum; pullback risk is elevated."
            if change_pct >= 10
            else "Positive momentum with comparatively lower extension."
        )
        candidates.append(
            {
                "symbol": symbol,
                "price": float(ticker["lastPrice"]),
                "change_pct": change_pct,
                "range_pct": range_pct,
                "quote_volume_usdt": quote_volume,
                "analysis": (
                    f"Positive {change_pct:.1f}% momentum, {range_pct:.1f}% "
                    f"24h range, and {quote_volume / 1_000_000:.1f}M USDT volume. "
                    f"{risk_note}"
                ),
            }
        )
    candidates.sort(key=lambda item: item["range_pct"], reverse=True)
    return candidates[:6]


def round_to_step(quantity, step_size):
    return (quantity / step_size).to_integral_value(rounding=ROUND_DOWN) * step_size


def current_exposure(positions):
    return sum(
        (Decimal(position["entry"]) * Decimal(position["quantity"]) for position in positions.values()),
        Decimal("0"),
    )


def buy(
    client, symbol, rules, analysis, positions, maximum_exposure, trade_amount,
    max_open_positions,
):
    if symbol in positions:
        return None
    if len(positions) >= max_open_positions:
        print(f"{symbol} BUY skipped: maximum open positions reached.")
        return None

    remaining_exposure = maximum_exposure - current_exposure(positions)
    available_usdt = get_free_balance(client, rules["quote_asset"])
    amount = min(trade_amount, remaining_exposure, available_usdt)
    quote_step = Decimal("1").scaleb(-rules["quote_precision"])
    amount = round_to_step(amount, quote_step)
    if amount < rules["min_notional"] or amount <= 0:
        print(f"{symbol} BUY skipped: insufficient balance or exposure allowance.")
        return None

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
    stop_distance = Decimal(str(analysis["atr"])) * ATR_SL_MULTIPLIER
    position = {
        "symbol": symbol,
        "base_asset": rules["base_asset"],
        "quote_asset": rules["quote_asset"],
        "order_id": order["orderId"],
        "quantity": str(executed_quantity),
        "entry": str(average_price),
        "stop_loss": str(average_price - stop_distance),
        "take_profit": str(average_price + stop_distance * RISK_REWARD_RATIO),
        "opened_at": int(time.time()),
    }
    positions[symbol] = position
    save_positions(positions)
    record_transaction(
        {
            "side": "BUY", "symbol": symbol, "order_id": order["orderId"],
            "quantity": str(executed_quantity), "price": str(average_price),
            "quote_amount": str(quote_spent), "quote_asset": rules["quote_asset"],
            "reason": "strategy buy signal",
        }
    )
    print(
        f"{symbol} BUY filled: {executed_quantity} {rules['base_asset']} "
        f"at about {average_price:.8f}"
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
        print(
            f"{symbol} SELL skipped: free {rules['base_asset']} is below "
            "the exchange minimum."
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
    print(f"{symbol} SELL filled: {executed_quantity}. Reason: {reason}")
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
        if request.get("action") != "SELL_MARKET":
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


def wait_for_next_cycle(client, positions, rules_by_symbol, active_symbols):
    elapsed = 0
    while elapsed < POLL_SECONDS:
        time.sleep(min(2, POLL_SECONDS - elapsed))
        elapsed += 2
        if elapsed < POLL_SECONDS and elapsed % LIVE_PRICE_REFRESH_SECONDS == 0:
            refresh_live_prices(client, active_symbols)
        if TRADING_ENABLED:
            process_sell_requests(client, positions, rules_by_symbol)


def decide_and_trade(
    client, symbol, rules, analysis, positions, maximum_exposure, trade_amount,
    max_open_positions, trading_on_hold,
):
    position = positions.get(symbol)
    price = Decimal(str(analysis["entry"]))
    if position:
        if price <= Decimal(position["stop_loss"]):
            order = sell(client, symbol, rules, position, analysis, positions, "stop loss")
            return "SELL FILLED" if order else "SELL SKIPPED"
        elif price >= Decimal(position["take_profit"]):
            order = sell(client, symbol, rules, position, analysis, positions, "take profit")
            return "SELL FILLED" if order else "SELL SKIPPED"
        elif analysis["rsi"] >= 65:
            order = sell(
                client, symbol, rules, position, analysis, positions, "RSI sell signal"
            )
            return "SELL FILLED" if order else "SELL SKIPPED"
        else:
            print(f"{symbol} HOLD: open position is being monitored.")
            return "MONITORING"

    if trading_on_hold:
        print(f"{symbol} ON HOLD: new buys are paused.")
        return "ON HOLD"

    buy_signal = analysis["rsi"] <= 35 or analysis["distance_to_support_pct"] <= 0.2
    if buy_signal:
        position = buy(
            client, symbol, rules, analysis, positions, maximum_exposure,
            trade_amount, max_open_positions,
        )
        return "BUY FILLED" if position else "BUY SKIPPED"
    else:
        print(f"{symbol} NO TRADE: waiting for a buy signal.")
        return "WAITING TO BUY"


def print_report(symbol, analysis):
    verdict = market_signal(analysis)
    print("=" * 72)
    print(f"{symbol} | Price: {analysis['entry']:.8f} | RSI: {analysis['rsi']:.2f}")
    print(f"ATR: {analysis['atr']:.8f} | Support: {analysis['support']:.8f}")
    print(f"Resistance: {analysis['resistance']:.8f} | Signal: {verdict}")
    print(f"Suggested SL: {analysis['sl']:.8f} | Suggested TP: {analysis['tp']:.8f}")
    print("=" * 72)


def main():
    acquire_instance_lock()
    client = create_client()
    positions = load_positions()
    rules_by_symbol = {}
    suggestions = []
    suggestions_updated_at = 0
    mode = f"{ENVIRONMENT.upper()} TRADING" if TRADING_ENABLED else "ANALYSIS ONLY"
    print(f"Multi-market bot | {mode} | Press Ctrl+C to stop")
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
            # An open position is always monitored even if removed from targets.
            active_symbols = list(
                dict.fromkeys(target_symbols + list(positions.keys()))
            )
            refresh_live_prices(client, active_symbols)
            if time.time() - suggestions_updated_at >= SUGGESTION_REFRESH_SECONDS:
                try:
                    suggestions = get_market_suggestions(client)
                    suggestions_updated_at = time.time()
                except BinanceAPIException as error:
                    print(f"Could not refresh market suggestions: {error}")
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            print(
                f"Targets: {', '.join(target_symbols)} | "
                f"Trade amount: {trade_amount} USDT | "
                f"Max exposure: {maximum_exposure} USDT | "
                f"Max positions: {max_open_positions} | "
                f"Interval: {interval} | "
                f"New buys: {'ON HOLD' if trading_on_hold else 'ACTIVE'}"
            )
            analyses = {}
            market_statuses = {}
            for symbol in active_symbols:
                try:
                    if symbol not in rules_by_symbol:
                        rules_by_symbol[symbol] = get_market_rules(client, symbol)
                    analysis = analyze_market(client, symbol, interval)
                    analyses[symbol] = analysis
                    print_report(symbol, analysis)
                    if TRADING_ENABLED:
                        market_statuses[symbol] = decide_and_trade(
                            client, symbol, rules_by_symbol[symbol], analysis, positions,
                            maximum_exposure, trade_amount, max_open_positions,
                            trading_on_hold,
                        )
                    else:
                        print(f"{symbol}: trading disabled.")
                        market_statuses[symbol] = "ANALYSIS ONLY"
                except (BinanceAPIException, BinanceOrderException) as error:
                    print(f"{symbol} Binance error: {error}")
                    market_statuses[symbol] = "BINANCE ERROR"
                except Exception as error:
                    print(f"{symbol} error: {error}")
                    market_statuses[symbol] = "ERROR"
            try:
                save_status(
                    get_free_balance(client, "USDT"), analyses, market_statuses,
                    target_symbols, maximum_exposure, trade_amount,
                    max_open_positions, trading_on_hold, interval, suggestions,
                )
            except (BinanceAPIException, BinanceOrderException) as error:
                print(f"Could not update account status: {error}")
            wait_for_next_cycle(client, positions, rules_by_symbol, active_symbols)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


if __name__ == "__main__":
    main()
