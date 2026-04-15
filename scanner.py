import requests
import pandas as pd
from datetime import datetime
import time
import os

# Только топ ликвидные монеты
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT",
    "APTUSDT", "OPUSDT", "ARBUSDT", "INJUSDT", "SUIUSDT",
    "SEIUSDT", "TIAUSDT", "WLDUSDT", "FETUSDT", "RENDERUSDT",
    "AAVEUSDT", "MKRUSDT", "RUNEUSDT", "FILUSDT", "ICPUSDT",
    "GALAUSDT", "SANDUSDT", "MANAUSDT", "APEUSDT", "GMXUSDT",
    "STXUSDT", "CFXUSDT", "BLURUSDT", "JASMYUSDT", "JTOUSDT",
    "PYTHUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "TONUSDT", "NOTUSDT",
    "EIGENUSDT", "REZUSDT", "BBUSDT", "TURBOUSDT", "MEMEUSDT"
]

def get_klines(symbol, interval="15m", limit=50):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = requests.get(url, timeout=5)
    data = r.json()
    if not isinstance(data, list) or len(data) < 20:
        return None
    df = pd.DataFrame(data, columns=["time","open","high","low","close","volume","ct","qav","nt","tbbav","tbqav","ignore"])
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    return df

def get_funding_rate(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
        r = requests.get(url, timeout=5)
        data = r.json()
        return float(data.get("lastFundingRate", 0)) * 100
    except:
        return 0

def get_open_interest(symbol):
    try:
        url = f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=15m&limit=3"
        r = requests.get(url, timeout=5)
        data = r.json()
        if isinstance(data, list) and len(data) >= 2:
            oi_now = float(data[-1]["sumOpenInterest"])
            oi_prev = float(data[-2]["sumOpenInterest"])
            change = ((oi_now - oi_prev) / oi_prev) * 100 if oi_prev > 0 else 0
            return oi_now, change
    except:
        pass
    return 0, 0

def get_ticker(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"
        r = requests.get(url, timeout=5)
        return r.json()
    except:
        return None

def calc_rsi(df, period=14):
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 1)

def calc_atr(df, period=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def score_signal(r):
    score = 0
    if abs(r["funding"]) > 0.05: score += 3
    if abs(r["funding"]) > 0.1:  score += 2
    if abs(r["oi_change"]) > 3:   score += 2
    if r["vol_spike"] > 2:        score += 2
    if r["vol_spike"] > 3:        score += 2
    if r["rsi"] < 25 or r["rsi"] > 75: score += 2
    if r["atr_pct"] > 1.5:        score += 1
    return score

def scan_once():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 65)
    print(f"  BINANCE FUTURES SCANNER    {datetime.now().strftime('%d.%m.%Y  %H:%M:%S')}")
    print("=" * 65)
    print(f"  Сканирую {len(WHITELIST)} монет...\n")

    results = []

    for symbol in WHITELIST:
        try:
            ticker = get_ticker(symbol)
            if not ticker:
                continue

            price = float(ticker["lastPrice"])
            change24 = float(ticker["priceChangePercent"])
            volume_m = float(ticker["quoteVolume"]) / 1_000_000

            if volume_m < 20:
                continue

            df = get_klines(symbol, "15m", 50)
            if df is None:
                continue

            rsi = calc_rsi(df)
            atr = calc_atr(df)
            atr_pct = (atr / price) * 100 if price > 0 else 0

            funding = get_funding_rate(symbol)
            oi, oi_change = get_open_interest(symbol)

            avg_vol = df["volume"].iloc[-10:-1].mean()
            last_vol = df["volume"].iloc[-1]
            vol_spike = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1

            signal = ""
            reason = []

            # RSI сигналы
            if rsi <= 28:
                signal = "LONG"
                reason.append(f"RSI перепродан ({rsi})")
            elif rsi >= 72:
                signal = "SHORT"
                reason.append(f"RSI перекуплен ({rsi})")

            # Funding сигналы
            if funding > 0.05:
                signal = "SHORT"
                reason.append(f"Funding +{funding:.3f}% (лонги переплачивают)")
            elif funding < -0.05:
                signal = "LONG"
                reason.append(f"Funding {funding:.3f}% (шорты переплачивают)")

            # OI
            if oi_change > 4:
                reason.append(f"OI растёт +{oi_change:.1f}%")
            elif oi_change < -4:
                reason.append(f"OI падает {oi_change:.1f}%")

            # Объём спайк
            if vol_spike >= 2:
                reason.append(f"Объём x{vol_spike} от среднего")

            if not signal or not reason:
                continue

            r = {
                "symbol": symbol,
                "price": price,
                "change24": change24,
                "rsi": rsi,
                "atr_pct": round(atr_pct, 2),
                "funding": funding,
                "oi_change": round(oi_change, 1),
                "vol_spike": vol_spike,
                "volume_m": round(volume_m, 0),
                "signal": signal,
                "reason": reason
            }
            r["score"] = score_signal(r)
            results.append(r)

        except Exception:
            continue

    if not results:
        print("  Нет чётких сигналов. Входить нельзя.")
        print("  Следующий скан через 15 минут...\n")
        return

    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"  Найдено сигналов: {len(results)}  |  Топ-3 лучших:\n")

    for i, r in enumerate(results[:3]):
        direction = r["signal"]
        price = r["price"]

        if direction == "LONG":
            tp1 = round(price * 1.03, 6)
            tp2 = round(price * 1.06, 6)
            sl  = round(price * 0.975, 6)
            liq_risk = "~20% при x10 (SL защищает)"
        else:
            tp1 = round(price * 0.97, 6)
            tp2 = round(price * 0.94, 6)
            sl  = round(price * 1.025, 6)
            liq_risk = "~20% при x10 (SL защищает)"

        stars = "★" * min(r["score"], 5)
        print(f"  {'─'*60}")
        print(f"  #{i+1}  {r['symbol']}   {direction}   {stars} (сила {r['score']}/10)")
        print(f"  {'─'*60}")
        print(f"  Причина:      {' | '.join(r['reason'])}")
        print(f"  Цена входа:   ${price}")
        print(f"  TP1:          ${tp1}   (+3%  → ~+30% при x10)")
        print(f"  TP2:          ${tp2}   (+6%  → ~+60% при x10)")
        print(f"  SL:           ${sl}    (-2.5% → -25% при x10)")
        print(f"  RSI:          {r['rsi']}   |  ATR: {r['atr_pct']}%")
        print(f"  Funding:      {r['funding']:.4f}%")
        print(f"  OI изм.:      {r['oi_change']}%")
        print(f"  Объём 24h:    ${r['volume_m']:.0f}M   |  Спайк: x{r['vol_spike']}")
        print(f"  Плечо:        x10  (риск 2.5% депозита на сделку)")
        print(f"  Риск ликв.:   {liq_risk}")
        print()

    print(f"  {'─'*60}")
    print(f"  Следующий скан через 15 минут...  (Ctrl+C для остановки)")
    print(f"  {'─'*60}\n")

if __name__ == "__main__":
    print("  Запуск автосканера... (каждые 15 минут)")
    while True:
        try:
            scan_once()
            time.sleep(15 * 60)
        except KeyboardInterrupt:
            print("\n  Сканер остановлен.")
            break
        except Exception as e:
            print(f"  Ошибка: {e}")
            time.sleep(60)
