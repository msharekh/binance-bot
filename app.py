import time
import pandas as pd
from binance.client import Client

# 1. API Configuration (Read-only permissions are sufficient)
API_KEY = 'mSAUOghMbvTuUvnoegJImtchLlpVcFS2SnKlvwE08Oh7Bs3e87tK5UVY9P0dPtvu'
API_SECRET = 'zyPGddSLzM4wHZUoMFErLiC4ytBahmANCUBnWQtcTJhVkV7RytnkPVK07QfXh7fj'

client = Client(API_KEY, API_SECRET)

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_1MINUTE

# 2. Indicator Calculation Functions
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

# 3. Market Data Fetching & Analysis Function
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

# 4. Structured Report & Description Generator
def generate_structured_report(price, rsi, atr, support, resistance):
    dist_to_support_pct = ((price - support) / price) * 100
    dist_to_resistance_pct = ((resistance - price) / price) * 100
    
    # Buy Setup Evaluation
    if rsi <= 35 or dist_to_support_pct <= 0.2:
        verdict = "🟢 HIGH CONVICTION BUY"
        quality = "FAVORABLE (High Reward-to-Risk Ratio)"
        summary = (
            "Asset is approaching key demand levels with selling momentum exhausting. "
            "Entering near support reduces downside exposure while maximizing potential bounce margin."
        )
    # Sell Setup Evaluation
    elif rsi >= 65 or dist_to_resistance_pct <= 0.2:
        verdict = "🔴 HIGH CONVICTION SELL / TAKE-PROFIT"
        quality = "FAVORABLE (Overextended Bullish Momentum)"
        summary = (
            "Asset is testing key supply/overhead resistance levels with buying volume fading. "
            "High probability of price rejection or mean-reversion pullback."
        )
    # Neutral Setup Evaluation
    else:
        verdict = "⚪ NEUTRAL / NO TRADE ZONE"
        quality = "UNFAVORABLE (High Risk of Consolidation / Chop)"
        summary = (
            "Price is hovering mid-range between support and resistance boundaries without clear momentum. "
            "Lacks statistical edge; preserve capital and wait for boundary confirmation."
        )

    # Format the structured report output
    report = f"""
================================================================================
                    MARKET ANALYSIS REPORT | {SYMBOL}
================================================================================
[1] MARKET METRICS & INDICATORS
    • Current Price       : ${price:.2f}
    • RSI (14 Period)     : {rsi:.2f}  [Oversold: ≤35 | Overbought: ≥65]
    • ATR Volatility (14) : ${atr:.2f}
    • Support Level (20)  : ${support:.2f}  (Distance: {dist_to_support_pct:.2f}%)
    • Resistance Level(20): ${resistance:.2f}  (Distance: {dist_to_resistance_pct:.2f}%)

[2] OPPORTUNITY EVALUATION
    • Status / Verdict    : {verdict}
    • Opportunity Quality : {quality}

[3] TECHNICAL RATIONALE & ANALYSIS
    {summary}
================================================================================
"""
    return report

# 5. Continuous Loop
print(f"Monitoring {SYMBOL} with structured trade reports...\n")

while True:
    try:
        price, rsi, atr, support, resistance = analyze_market()
        report = generate_structured_report(price, rsi, atr, support, resistance)
        
        print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(report)
        
        time.sleep(60)

    except Exception as e:
        print(f"Error fetching data: {e}")
        time.sleep(10)