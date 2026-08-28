import json
import os
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException


INTERVAL = Client.KLINE_INTERVAL_1MINUTE
RISK_REWARD_RATIO = Decimal("2")
ATR_SL_MULTIPLIER = Decimal("1.5")
TRADE_AMOUNT_USDT = Decimal(os.getenv("TRADE_AMOUNT_USDT", "25"))
MAX_TOTAL_EXPOSURE_USDT = Decimal(os.getenv("MAX_TOTAL_EXPOSURE_USDT", "75"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
POLL_SECONDS = 60

# Comma-separated USDT markets, for example: BTCUSDT,ETHUSDT,TRXUSDT
SYMBOLS = tuple(
    dict.fromkeys(
        symbol.strip().upper()
        for symbol in os.getenv(
            "TRADING_SYMBOLS", "BTCUSDT,ETHUSDT,TRXUSDT"
        ).split(",")
        if symbol.strip()
    )
)

# This remains production to preserve the environment selected by the user.
TESTNET = False
ENVIRONMENT = "testnet" if TESTNET else "production"
TRADING_ENABLED = os.getenv("ENABLE_TRADING", "false").lower() == "true"
STATE_FILE = Path(__file__).with_name("trade_state.json")
TRANSACTION_FILE = Path(__file__).with_name("transactions.jsonl")
STATUS_FILE = Path(__file__).with_name("bot_status.json")


def create_client():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("Set BINANCE_API_KEY and BINANCE_API_SECRET.")
    return Client(api_key.strip(), api_secret.strip(), testnet=TESTNET)


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


def analyze_market(client, symbol):
    klines = client.get_klines(symbol=symbol, interval=INTERVAL, limit=100)
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


def save_status(available_usdt, analyses, market_statuses):
    temporary_file = STATUS_FILE.with_suffix(".tmp")
    status = {
        "environment": ENVIRONMENT,
        "updated_at": int(time.time()),
        "available_usdt": str(available_usdt),
        "target_symbols": list(SYMBOLS),
        "market_statuses": market_statuses,
        "markets": {
            symbol: {
                "price": analysis["entry"],
                "rsi": analysis["rsi"],
                "status": market_statuses.get(symbol, "UNKNOWN"),
            }
            for symbol, analysis in analyses.items()
        },
    }
    with temporary_file.open("w", encoding="utf-8") as status_file:
        json.dump(status, status_file, indent=2)
    temporary_file.replace(STATUS_FILE)


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
    return {
        "base_asset": symbol_info["baseAsset"],
        "quote_asset": symbol_info["quoteAsset"],
        "step_size": Decimal(lot_size["stepSize"]),
        "min_quantity": Decimal(lot_size["minQty"]),
        "min_notional": Decimal(notional.get("minNotional", "0")),
    }


def round_to_step(quantity, step_size):
    return (quantity / step_size).to_integral_value(rounding=ROUND_DOWN) * step_size


def current_exposure(positions):
    return sum(
        (Decimal(position["entry"]) * Decimal(position["quantity"]) for position in positions.values()),
        Decimal("0"),
    )


def buy(client, symbol, rules, analysis, positions):
    if symbol in positions:
        return None
    if len(positions) >= MAX_OPEN_POSITIONS:
        print(f"{symbol} BUY skipped: maximum open positions reached.")
        return None

    remaining_exposure = MAX_TOTAL_EXPOSURE_USDT - current_exposure(positions)
    available_usdt = get_free_balance(client, rules["quote_asset"])
    amount = min(TRADE_AMOUNT_USDT, remaining_exposure, available_usdt)
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


def decide_and_trade(client, symbol, rules, analysis, positions):
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

    buy_signal = analysis["rsi"] <= 35 or analysis["distance_to_support_pct"] <= 0.2
    if buy_signal:
        position = buy(client, symbol, rules, analysis, positions)
        return "BUY FILLED" if position else "BUY SKIPPED"
    else:
        print(f"{symbol} NO TRADE: waiting for a buy signal.")
        return "WAITING TO BUY"


def print_report(symbol, analysis):
    if analysis["rsi"] <= 35 or analysis["distance_to_support_pct"] <= 0.2:
        verdict = "BUY SIGNAL"
    elif analysis["rsi"] >= 65:
        verdict = "SELL SIGNAL / NO LONG ENTRY"
    else:
        verdict = "NEUTRAL"
    print("=" * 72)
    print(f"{symbol} | Price: {analysis['entry']:.8f} | RSI: {analysis['rsi']:.2f}")
    print(f"ATR: {analysis['atr']:.8f} | Support: {analysis['support']:.8f}")
    print(f"Resistance: {analysis['resistance']:.8f} | Signal: {verdict}")
    print(f"Suggested SL: {analysis['sl']:.8f} | Suggested TP: {analysis['tp']:.8f}")
    print("=" * 72)


def main():
    if not SYMBOLS:
        raise RuntimeError("TRADING_SYMBOLS must contain at least one symbol.")
    client = create_client()
    positions = load_positions()
    rules_by_symbol = {symbol: get_market_rules(client, symbol) for symbol in SYMBOLS}
    unknown_positions = set(positions) - set(SYMBOLS)
    if unknown_positions:
        raise RuntimeError(
            "Open state exists for symbols missing from TRADING_SYMBOLS: "
            + ", ".join(sorted(unknown_positions))
        )

    mode = f"{ENVIRONMENT.upper()} TRADING" if TRADING_ENABLED else "ANALYSIS ONLY"
    print(f"Monitoring {', '.join(SYMBOLS)} | {mode} | Press Ctrl+C to stop")
    while True:
        try:
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            analyses = {}
            market_statuses = {}
            for symbol in SYMBOLS:
                try:
                    analysis = analyze_market(client, symbol)
                    analyses[symbol] = analysis
                    print_report(symbol, analysis)
                    if TRADING_ENABLED:
                        market_statuses[symbol] = decide_and_trade(
                            client, symbol, rules_by_symbol[symbol], analysis, positions
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
                    get_free_balance(client, "USDT"), analyses, market_statuses
                )
            except (BinanceAPIException, BinanceOrderException) as error:
                print(f"Could not update account status: {error}")
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


if __name__ == "__main__":
    main()
