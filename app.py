import json
import os
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException


SYMBOL = "BTCUSDT"
BASE_ASSET = "BTC"
QUOTE_ASSET = "USDT"
INTERVAL = Client.KLINE_INTERVAL_1MINUTE
RISK_REWARD_RATIO = 2.0
ATR_SL_MULTIPLIER = 1.5
TRADE_AMOUNT_USDT = Decimal(os.getenv("TRADE_AMOUNT_USDT", "25"))
POLL_SECONDS = 60

# Safety: this application only connects to Binance Spot Testnet.
TESTNET = True
TRADING_ENABLED = os.getenv("ENABLE_TRADING", "false").lower() == "true"
STATE_FILE = Path(__file__).with_name("trade_state.json")


def create_client():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(
            "Set BINANCE_API_KEY and BINANCE_API_SECRET to Spot Testnet credentials."
        )
    return Client(api_key, api_secret, testnet=TESTNET)


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


def analyze_market(client):
    klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
    columns = [
        "time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
    ]
    data = pd.DataFrame(klines, columns=columns)
    for column in ["open", "high", "low", "close", "volume"]:
        data[column] = data[column].astype(float)

    # A completed candle avoids placing orders from a still-changing signal.
    completed = data.iloc[:-1]
    entry_price = completed["close"].iloc[-1]
    rsi = calculate_rsi(completed).iloc[-1]
    atr = calculate_atr(completed).iloc[-1]
    support = completed["low"].tail(20).min()
    resistance = completed["high"].tail(20).max()
    stop_distance = atr * ATR_SL_MULTIPLIER
    return {
        "entry": entry_price,
        "sl": entry_price - stop_distance,
        "tp": entry_price + stop_distance * RISK_REWARD_RATIO,
        "rsi": rsi,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "distance_to_support_pct": ((entry_price - support) / entry_price) * 100,
    }


def load_position():
    if not STATE_FILE.exists():
        return None
    with STATE_FILE.open("r", encoding="utf-8") as state_file:
        return json.load(state_file)


def save_position(position):
    temporary_file = STATE_FILE.with_suffix(".tmp")
    with temporary_file.open("w", encoding="utf-8") as state_file:
        json.dump(position, state_file, indent=2)
    temporary_file.replace(STATE_FILE)


def clear_position():
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def get_free_balance(client, asset):
    balance = client.get_asset_balance(asset=asset)
    return Decimal(balance["free"]) if balance else Decimal("0")


def get_step_size(client):
    symbol_info = client.get_symbol_info(SYMBOL)
    if not symbol_info:
        raise RuntimeError(f"Could not load exchange rules for {SYMBOL}.")
    lot_size = next(
        item for item in symbol_info["filters"] if item["filterType"] == "LOT_SIZE"
    )
    return Decimal(lot_size["stepSize"]), Decimal(lot_size["minQty"])


def round_to_step(quantity, step_size):
    return (quantity / step_size).to_integral_value(rounding=ROUND_DOWN) * step_size


def buy(client, analysis):
    available_usdt = get_free_balance(client, QUOTE_ASSET)
    amount = min(TRADE_AMOUNT_USDT, available_usdt)
    if amount <= 0:
        print("BUY skipped: no free USDT balance.")
        return None

    order = client.create_order(
        symbol=SYMBOL,
        side=Client.SIDE_BUY,
        type=Client.ORDER_TYPE_MARKET,
        quoteOrderQty=str(amount),
        newOrderRespType="FULL",
    )
    executed_quantity = Decimal(order["executedQty"])
    quote_spent = Decimal(order["cummulativeQuoteQty"])
    average_price = quote_spent / executed_quantity
    stop_distance = Decimal(str(analysis["atr"] * ATR_SL_MULTIPLIER))
    position = {
        "order_id": order["orderId"],
        "quantity": str(executed_quantity),
        "entry": str(average_price),
        "stop_loss": str(average_price - stop_distance),
        "take_profit": str(
            average_price + stop_distance * Decimal(str(RISK_REWARD_RATIO))
        ),
        "opened_at": int(time.time()),
    }
    save_position(position)
    print(f"BUY filled: {executed_quantity} {BASE_ASSET} at about {average_price:.2f}")
    return position


def sell(client, position, reason):
    step_size, minimum_quantity = get_step_size(client)
    tracked_quantity = Decimal(position["quantity"])
    available_quantity = get_free_balance(client, BASE_ASSET)
    quantity = round_to_step(min(tracked_quantity, available_quantity), step_size)
    if quantity < minimum_quantity:
        print(f"SELL skipped: available {BASE_ASSET} is below the minimum quantity.")
        return None

    order = client.create_order(
        symbol=SYMBOL,
        side=Client.SIDE_SELL,
        type=Client.ORDER_TYPE_MARKET,
        quantity=format(quantity, "f"),
        newOrderRespType="FULL",
    )
    clear_position()
    print(f"SELL filled: {quantity} {BASE_ASSET}. Reason: {reason}")
    return order


def decide_and_trade(client, analysis):
    position = load_position()
    price = Decimal(str(analysis["entry"]))
    if position:
        if price <= Decimal(position["stop_loss"]):
            sell(client, position, "stop loss")
        elif price >= Decimal(position["take_profit"]):
            sell(client, position, "take profit")
        elif analysis["rsi"] >= 65:
            sell(client, position, "RSI sell signal")
        else:
            print("HOLD: an open position is being monitored.")
        return

    buy_signal = (
        analysis["rsi"] <= 35 or analysis["distance_to_support_pct"] <= 0.2
    )
    if buy_signal:
        buy(client, analysis)
    else:
        print("NO TRADE: waiting for a buy signal.")


def print_report(analysis):
    if analysis["rsi"] <= 35 or analysis["distance_to_support_pct"] <= 0.2:
        verdict = "BUY SIGNAL"
    elif analysis["rsi"] >= 65:
        verdict = "SELL SIGNAL / NO LONG ENTRY"
    else:
        verdict = "NEUTRAL"
    print("=" * 72)
    print(f"{SYMBOL} | Price: {analysis['entry']:.2f} | RSI: {analysis['rsi']:.2f}")
    print(f"ATR: {analysis['atr']:.2f} | Support: {analysis['support']:.2f}")
    print(f"Resistance: {analysis['resistance']:.2f} | Signal: {verdict}")
    print(f"Suggested SL: {analysis['sl']:.2f} | Suggested TP: {analysis['tp']:.2f}")
    print("=" * 72)


def main():
    client = create_client()
    mode = "TESTNET TRADING" if TRADING_ENABLED else "ANALYSIS ONLY"
    print(f"Monitoring {SYMBOL} | {mode} | Press Ctrl+C to stop")
    while True:
        try:
            analysis = analyze_market(client)
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            print_report(analysis)
            if TRADING_ENABLED:
                decide_and_trade(client, analysis)
            else:
                print("Trading disabled. Set ENABLE_TRADING=true to place testnet orders.")
            time.sleep(POLL_SECONDS)
        except (BinanceAPIException, BinanceOrderException) as error:
            print(f"Binance error: {error}")
            time.sleep(10)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as error:
            print(f"Error: {error}")
            time.sleep(10)


if __name__ == "__main__":
    main()
