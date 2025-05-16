from flask import Flask, render_template
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import pandas as pd
from datetime import datetime

app = Flask(__name__)
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "DOGEUSDT"]

data_cache = []
last_update = ""

def fetch_klines(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        
        if not data:
            return pd.DataFrame()
            
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "_", "_", "_", "_", "_", "_"
        ])
        df["open"] = df["open"].astype(float)
        df["close"] = df["close"].astype(float)
        return df
    except Exception as e:
        print(f"Fehler bei fetch_klines für {symbol}: {str(e)}")
        return pd.DataFrame()

def compute_rsi(df, period=14):
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_signal_strength(signal):
    if "Engulfing" in signal:
        return 3
    elif "2 grüne" in signal or "2 rote" in signal:
        return 2
    elif "Könnte bald" in signal:
        return 1
    return 0

def analyze_engulfing(symbol):
    try:
        df = fetch_klines(symbol)
        if df.empty:
            return error_response(symbol)
            
        df["rsi"] = compute_rsi(df)
        last_rsi = df["rsi"].iloc[-1]
        c1 = df.iloc[-1]
        c2 = df.iloc[-2]
        c3 = df.iloc[-3]

        signal, status, pattern = "Neutral", "Neutral", "neutral"
        proximity = 0

        # Engulfing Logik
        if c3["close"] > c3["open"] and c2["close"] > c2["open"] and c1["close"] < c1["open"]:
            if abs(c1.close - c1.open) > abs(c2.close - c2.open):
                pattern = "bearish"
                proximity = max(last_rsi - 60, 0)
                if last_rsi > 60:
                    signal = "❌ Bearish Engulfing ❌"
                    status = "Trade möglich (Short)"
                else:
                    signal = "⚠️ Potentieller Bearish"
                    status = f"{round(60 - last_rsi,1)} Punkte bis Signal"
        
        elif c3["close"] < c3["open"] and c2["close"] < c2["open"] and c1["close"] > c1["open"]:
            if abs(c1.close - c1.open) > abs(c2.close - c2.open):
                pattern = "bullish"
                proximity = max(40 - last_rsi, 0)
                if last_rsi < 40:
                    signal = "✅ Bullish Engulfing ✅"
                    status = "Trade möglich (Long)"
                else:
                    signal = "⚠️ Potentieller Bullish"
                    status = f"{round(last_rsi - 40,1)} Punkte bis Signal"
        
        elif c2["close"] > c2["open"] and c1["close"] > c1["open"]:
            signal = "2 grüne Kerzen"
            pattern = "bullish"
            status = "Könnte bald Bearish sein"
            proximity = max(40 - last_rsi, 0)
        
        elif c2["close"] < c2["open"] and c1["close"] < c1["open"]:
            signal = "2 rote Kerzen"
            pattern = "bearish"
            status = "Könnte bald Bullish sein"
            proximity = max(last_rsi - 60, 0)
        
        else:
            proximity_bull = 40 - last_rsi if last_rsi < 40 else 0
            proximity_bear = last_rsi - 60 if last_rsi > 60 else 0
            proximity = max(proximity_bull, proximity_bear)
            status = f"Überwachung ({'Bullish' if proximity_bull > proximity_bear else 'Bearish'})"

        return {
            "symbol": symbol,
            "signal": signal,
            "rsi": round(last_rsi, 2),
            "status": status,
            "color": get_rsi_color(last_rsi, pattern, proximity),
            "score": get_signal_strength(signal),
            "proximity": round(proximity, 2)
        }
    except Exception as e:
        print(f"Fehler bei analyze_engulfing für {symbol}: {str(e)}")
        return error_response(symbol)

def error_response(symbol):
    return {
        "symbol": symbol,
        "signal": "Fehler",
        "rsi": 0,
        "status": "Keine Daten",
        "color": "#ffffff",
        "score": -1,
        "proximity": 0
    }

def get_rsi_color(rsi, pattern, proximity):
    if pattern == "bullish":
        intensity = min(int(proximity * 10), 200)
        return f"rgb({50}, {200 - intensity}, {50})"
    elif pattern == "bearish":
        intensity = min(int(proximity * 10), 200)
        return f"rgb({200 - intensity}, {50}, {50})"
    return f"hsl(0, 0%, {30 + min(proximity*2, 40)}%)"

def update_data():
    global data_cache, last_update
    print("\nStarte Datenupdate...")
    data = []
    for symbol in symbols:
        entry = analyze_engulfing(symbol)
        data.append(entry)
    
    data = [d for d in data if d["score"] >= 0]
    data.sort(key=lambda x: (-x["score"], -x["proximity"]))
    
    data_cache = data
    last_update = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"Update abgeschlossen um {last_update}")

# Scheduler-Konfiguration
scheduler = BackgroundScheduler()
scheduler.add_job(update_data, "interval", minutes=15)
scheduler.start()
update_data()

@app.route("/")
def index():
    return render_template("index.html", 
                         data=data_cache, 
                         last_update=last_update)

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)