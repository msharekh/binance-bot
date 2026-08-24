import time
import pandas as pd
from binance.client import Client

# 1. API Configuration (Read-only permissions are sufficient)
API_KEY = 'mSAUOghMbvTuUvnoegJImtchLlpVcFS2SnKlvwE08Oh7Bs3e87tK5UVY9P0dPtvu'
API_SECRET = 'zyPGddSLzM4wHZUoMFErLiC4ytBahmANCUBnWQtcTJhVkV7RytnkPVK07QfXh7fj'

client = Client(API_KEY, API_SECRET)

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_1MINUTE

# 2. Technical Indicator Functions
def calculate_rsi(data, window=14):
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(data, window=14):
    high_low = data['high'] - data['low']
    high_close = (data['high'] - data['close'].shift()).abs()
    low_close = (data['low'] - data['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=window).mean()

# 3. Market Analysis Function
def analyze_market():
    klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
    df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    current_price = df['close'].iloc[-1]
    rsi = calculate_rsi(df).iloc[-1]
    atr = calculate_atr(df).iloc[-1]
    
    support = df['low'].tail(20).min()
    resistance = df['high'].tail(20).max()
    
    return current_price, rsi, atr, support, resistance

# 4. Assessment & Description Generator
def evaluate_opportunity(price, rsi, atr, support, resistance):
    dist_to_support = ((price - support) / price) * 100
    dist_to_resistance = ((resistance - price) / price) * 100
    
    # Buy Signal Logic
    if rsi <= 35 or dist_to_support <= 0.2:
        signal = "🟢 [BUY OPPORTUNITY]"
        reason = (
            f"Strong risk-to-reward ratio. RSI is at {rsi:.1f} (Oversold threshold <= 35), "
            f"and price is within {dist_to_support:.2f}% of support (${support:.2f}). "
            f"Volatility (ATR) is ${atr:.2f}, indicating a potential reversal bounce."
        )
    # Sell Signal Logic
    elif rsi >= 65 or dist_to_resistance <= 0.2:
        signal = "🔴 [SELL / TAKE-PROFIT OPPORTUNITY]"
        reason = (
            f"Overextended momentum. RSI is at {rsi:.1f} (Overbought threshold >= 65), "
            f"and price is within {dist_to_resistance:.2f}% of resistance (${resistance:.2f}). "
            f"High probability of upside exhaustion or pullbacks."
        )
    # Neutral Logic
    else:
        signal = "⚪ [POOR / NEUTRAL OPPORTUNITY]"
        reason = (
            f"No edge detected. RSI sits at a neutral {rsi:.1f} (Mid-range 36–64), "
            f"and price is floating between support (${support:.2f}) and resistance (${resistance:.2f}). "
            f"Risk of chop is high; wait for price to test key boundary zones."
        )
        
    return signal, reason

# 5. Continuous Loop
print(f"Monitoring {SYMBOL} with detailed setup descriptions...\n")

while True:
    try:
        price, rsi, atr, support, resistance = analyze_market()
        signal, description = evaluate_opportunity(price, rsi, atr, support, resistance)
        
        print(f"--- [ {time.strftime('%H:%M:%S')} ] ---")
        print(f"Price: ${price:.2f} | RSI (14): {rsi:.2f} | ATR (14): ${atr:.2f}")
        print(f"Key Zones: Support ${support:.2f} <----> Resistance ${resistance:.2f}")
        print(f"Signal: {signal}")
        print(f"Analysis: {description}")
        print("-" * 50 + "\n")
        
        time.sleep(60)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(10)