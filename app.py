import time
import pandas as pd
from binance.client import Client

# 1. إعداد مفاتيح API (صلاحية القراءة فقط تكفي)
API_KEY = 'mSAUOghMbvTuUvnoegJImtchLlpVcFS2SnKlvwE08Oh7Bs3e87tK5UVY9P0dPtvu'
API_SECRET = 'zyPGddSLzM4wHZUoMFErLiC4ytBahmANCUBnWQtcTJhVkV7RytnkPVK07QfXh7fj'

client = Client(API_KEY, API_SECRET)

SYMBOL = 'ACTUSDT'
INTERVAL = Client.KLINE_INTERVAL_1MINUTE  # الإطار الزمني للشموع

# 2. دالة حساب مؤشر RSI
def calculate_rsi(data, window=14):
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# 3. دالة جلب وتحليل بيانات السوق
def analyze_market():
    # جلب آخر 100 شمعة
    klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
    df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    
    # حساب المؤشرات والأسعار
    current_price = df['close'].iloc[-1]
    rsi_series = calculate_rsi(df)
    latest_rsi = rsi_series.iloc[-1]
    
    # تحديد مستويات الدعم والمقاومة البسيطة (أعلى وأقل سعر في آخر 20 شمعة)
    support_level = df['low'].tail(20).min()
    resistance_level = df['high'].tail(20).max()
    
    return current_price, latest_rsi, support_level, resistance_level

# 4. حلقة المراقبة والتحليل المستمر
print(f"بدء مراقبة وتحديد مناطق الشراء والبيع لزوج {SYMBOL}...\n")

while True:
    try:
        price, rsi, support, resistance = analyze_market()
        
        print(f"--- [ {time.strftime('%H:%M:%S')} ] ---")
        print(f"السعر الحالي: ${price:.2f}")
        print(f"قيمة RSI: {rsi:.2f}")
        print(f"منطقة الدعم (الشراء): ${support:.2f} | منطقة المقاومة (البيع): ${resistance:.2f}")
        
        # تحديد الإشارات بناءً على التحليل
        if rsi <= 30 or price <= support * 1.001:
            print("🟢 [إشارة شراء]: السعر يقترب من منطقة دعم أو تشبع بيعي.")
        elif rsi >= 70 or price >= resistance * 0.999:
            print("🔴 [إشارة بيع]: السعر يقترب من منطقة مقاومة أو تشبع شرائي.")
        else:
            print("⚪ [منطقة محايدة]: الانتظار لحين وصول السعر لنقطة دخول مناسبة.")
            
        print("-" * 40 + "\n")
        
        # الانتظار دقيقة قبل التحديث التالي
        time.sleep(60)

    except Exception as e:
        print(f"حدث خطأ أثناء جلب البيانات: {e}")
        time.sleep(10)