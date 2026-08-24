import time
import pandas as pd
from binance.client import Client

# 1. API Configuration (Read-only permissions are sufficient)
API_KEY = 'mSAUOghMbvTuUvnoegJImtchLlpVcFS2SnKlvwE08Oh7Bs3e87tK5UVY9P0dPtvu'
API_SECRET = 'zyPGddSLzM4wHZUoMFErLiC4ytBahmANCUBnWQtcTJhVkV7RytnkPVK07QfXh7fj'

client = Client(API_KEY, API_SECRET)

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_1MINUTE  # Candlestick time frame

# 2. RSI Calculation Function
def calculate_rsi(data, window=14):
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# 3. Market Data Fetching & Analysis Function
def analyze_market():
    # Fetch the last 100 candlesticks
    klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
    df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    
    # Calculate indicators and current price
    current_price = df['close'].iloc[-1]
    rsi_series = calculate_rsi(df)
    latest_rsi = rsi_series.iloc[-1]
    
    # Determine basic support and resistance levels (Min/Max over the last 20 candles)
    support_level = df['low'].tail(20).min()
    resistance_level = df['high'].tail(20).max()
    
    return current_price, latest_rsi, support_level, resistance_level

# 4. Continuous Monitoring & Analysis Loop
print(f"Starting market analysis and zone identification for {SYMBOL}...\n")

while True:
    try:
        price, rsi, support, resistance = analyze_market()
        
        print(f"--- [ {time.strftime('%H:%M:%S')} ] ---")
        print(f"Current Price: ${price:.2f}")
        print(f"RSI Value: {rsi:.2f}")
        print(f"Support (Buy Zone): ${support:.2f} | Resistance (Sell Zone): ${resistance:.2f}")
        
        # Generate signals based on indicators
        if rsi <= 30 or price <= support * 1.001:
            print("🟢 [BUY SIGNAL]: Price near support zone or oversold condition.")
        elif rsi >= 70 or price >= resistance * 0.999:
            print("🔴 [SELL SIGNAL]: Price near resistance zone or overbought condition.")
        else:
            print("⚪ [NEUTRAL ZONE]: Waiting for a clear entry point.")
            
        print("-" * 40 + "\n")
        
        # Wait for 60 seconds before the next check
        time.sleep(60)

    except Exception as e:
        print(f"Error fetching data: {e}")
        time.sleep(10)