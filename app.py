import time
import pandas as pd
from binance.client import Client

# 1. API Configuration (Read-only permissions are sufficient)
API_KEY = 'mSAUOghMbvTuUvnoegJImtchLlpVcFS2SnKlvwE08Oh7Bs3e87tK5UVY9P0dPtvu'
API_SECRET = 'zyPGddSLzM4wHZUoMFErLiC4ytBahmANCUBnWQtcTJhVkV7RytnkPVK07QfXh7fj'

client = Client(API_KEY, API_SECRET)

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_1MINUTE

# Risk Management Parameters (TradingView Style)
RISK_REWARD_RATIO = 2.0  # 1:2 Risk to Reward
ATR_SL_MULTIPLIER = 1.5  # Stop Loss = Entry - (1.5 * ATR)

# 2. Indicator Functions
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

# 3. Market Data & Setup Calculation
def analyze_market():
    klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
    df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    entry_price = df['close'].iloc[-1]
    rsi = calculate_rsi(df).iloc[-1]
    atr = calculate_atr(df).iloc[-1]
    
    support = df['low'].tail(20).min()
    resistance = df['high'].tail(20).max()
    
    # Calculate TradingView Long Position Parameters
    stop_loss_dist = atr * ATR_SL_MULTIPLIER
    stop_loss = entry_price - stop_loss_dist
    take_profit = entry_price + (stop_loss_dist * RISK_REWARD_RATIO)
    
    risk_amount = entry_price - stop_loss
    reward_amount = take_profit - entry_price
    risk_pct = (risk_amount / entry_price) * 100
    reward_pct = (reward_amount / entry_price) * 100
    
    return {
        'entry': entry_price,
        'sl': stop_loss,
        'tp': take_profit,
        'rsi': rsi,
        'atr': atr,
        'support': support,
        'resistance': resistance,
        'risk_pct': risk_pct,
        'reward_pct': reward_pct,
        'rr_ratio': RISK_REWARD_RATIO
    }

# 4. Structured Report Generator
def generate_structured_report(data):
    dist_to_support_pct = ((data['entry'] - data['support']) / data['entry']) * 100
    
    if data['rsi'] <= 35 or dist_to_support_pct <= 0.2:
        verdict = "🟢 HIGH CONVICTION BUY (LONG SETUP)"
        quality = "FAVORABLE (Valid Risk/Reward Setup)"
        summary = "Price is testing support with oversold momentum. Ideal long position entry."
    elif data['rsi'] >= 65:
        verdict = "🔴 HIGH CONVICTION SELL / NO LONG ENTRY"
        quality = "UNFAVORABLE (Overbought Conditions)"
        summary = "Price is overextended. Risk of immediate pullback makes long entry unfavorable."
    else:
        verdict = "⚪ NEUTRAL / NO TRADE ZONE"
        quality = "UNFAVORABLE (Mid-range Consolidation)"
        summary = "No clear edge detected. Wait for price to reach key boundary levels before taking a position."

    report = f"""
================================================================================
                    MARKET ANALYSIS REPORT | {SYMBOL}
================================================================================
[1] MARKET METRICS & INDICATORS
    • Current Price       : {data['entry']:.2f}
    • RSI (14 Period)     : {data['rsi']:.2f}
    • ATR Volatility (14) : {data['atr']:.2f}
    • Support / Resistance: {data['support']:.2f} / ${data['resistance']:.2f}

[2] SUGGESTED LONG POSITION TOOL (TRADINGVIEW INPUTS)
    • Entry Price         : {data['entry']:.2f}
    • Profit Target (TP)  : {data['tp']:.2f} (+{data['reward_pct']:.2f}%)
    • Stop Loss (SL)      : {data['sl']:.2f} (-{data['risk_pct']:.2f}%)
    • Risk / Reward Ratio : 1 : {data['rr_ratio']:.1f}

[3] OPPORTUNITY EVALUATION
    • Status / Verdict    : {verdict}
    • Quality             : {quality}
    • Analysis            : {summary}
================================================================================
"""
    return report

# 5. Execution Loop
print(f"Monitoring {SYMBOL} with TradingView Long Position Parameters...\n")

while True:
    try:
        data = analyze_market()
        report = generate_structured_report(data)
        
        print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(report)
        
        time.sleep(60)

    except Exception as e:
        print(f"Error fetching data: {e}")
        time.sleep(10)