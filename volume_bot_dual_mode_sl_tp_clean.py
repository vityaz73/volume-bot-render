
import time
import pandas as pd
from datetime import datetime
from binance.client import Client
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volume import VolumeWeightedAveragePrice
from ta.volatility import AverageTrueRange
from telegram import Bot
import sqlite3
import os

TELEGRAM_TOKEN = os.getenv ("8135395605:AAGh0bNJB2MznFzOt6ve_VlXlDqqGwvBcA8")
TELEGRAM_CHAT_ID = os.getenv ("904532322")
BINANCE_API_KEY = os.getenv ("4lT6ogpGqlKhrYMa10Bf7vNskdQqkSD9m0shbWAnqtHFAhQGgmhqV94hVMJXU842")
BINANCE_API_SECRET = os.getenv ("q4SQqEiiwje17wSOvO3OSJgw56grVNqPOWXfd60Q8QI1kwSQMcxRNdYaENy5Bjph")

DEBUG = False
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
bot = Bot(token=TELEGRAM_TOKEN)

EXCLUDED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "BCHUSDT"]
EXCLUDED_KEYWORDS = ["BULL", "BEAR", "1000", "DOWN", "UP", "2L", "2S"]
MIN_VOLUME = 500000
MIN_NATR = 2.0
sent_signals = {}

def get_klines(symbol, interval='5m', limit=100):
    try:
        data = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['open'] = df['open'].astype(float)
        return df
    except Exception as e:
        print(f"[ERROR] Ошибка при получении свечей {symbol}: {e}")
        return None

def analyze(symbol):
    for word in EXCLUDED_KEYWORDS:
        if word in symbol:
            return None

    df = get_klines(symbol)
    if df is None or df.empty:
        return None

    df['ema9'] = EMAIndicator(df['close'], window=9).ema_indicator()
    df['ema21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
    df['vwap'] = VolumeWeightedAveragePrice(
        high=df['high'], low=df['low'], close=df['close'], volume=df['volume']
    ).volume_weighted_average_price()

    atr = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    df['natr'] = 100 * atr / df['close']

    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last['natr'] < MIN_NATR:
        return None
    if last['volume'] * last['close'] < MIN_VOLUME:
        return None

    is_long = (
        last['close'] > last['ema9'] > last['ema21'] and
        last['close'] > last['vwap'] and
        50 < last['rsi'] < 70
    )
    is_short = (
        last['close'] < last['ema9'] < last['ema21'] and
        last['close'] < last['vwap'] and
        30 < last['rsi'] < 50
    )

    if not (is_long or is_short):
        return None

    direction = '🟢 ЛОНГ' if is_long else '🔴 ШОРТ'
    price = last['close']
    atr_value = atr.iloc[-1]

    if is_long:
        sl = round(price - atr_value, 4)
        tp = round(price + atr_value * 1.5, 4)
    else:
        sl = round(price + atr_value, 4)
        tp = round(price - atr_value * 1.5, 4)

    return {
        'symbol': symbol,
        'price': price,
        'ema9': round(last['ema9'], 4),
        'ema21': round(last['ema21'], 4),
        'vwap': round(last['vwap'], 4),
        'rsi': round(last['rsi'], 1),
        'rsi_prev': round(prev['rsi'], 1),
        'natr': round(last['natr'], 2),
        'direction': direction,
        'sl': sl,
        'tp': tp
    }

def send_message(msg):
    if not DEBUG:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")
    else:
        print("[TEST]", msg)

def save_to_db(data):
    conn = sqlite3.connect("signals.db")
    df = pd.DataFrame([data])
    df.to_sql("signals", conn, if_exists="append", index=False)
    conn.close()

def main():
    while True:
        tickers = [t for t in client.futures_ticker() if t["symbol"].endswith("USDT") and t["symbol"] not in EXCLUDED]
        symbols = [t["symbol"] for t in tickers]

        for symbol in symbols:
            try:
                result = analyze(symbol)
                if not result:
                    continue

                now = time.time()
                if symbol not in sent_signals or now - sent_signals[symbol] > 3600:
                    sent_signals[symbol] = now

                    msg = (
                        f"{result['direction']} <b>{result['symbol']}</b>\n"
                        f"Цена: {result['price']}\n"
                        f"EMA9: {result['ema9']} | EMA21: {result['ema21']}\n"
                        f"VWAP: {result['vwap']} | RSI: {result['rsi']} (до: {result['rsi_prev']})\n"
                        f"NATR: {result['natr']}%\n"
                        f"🎯 TP: {result['tp']} | 🛡 SL: {result['sl']}"
                    )

                    send_message(msg)
                    save_to_db(result)

            except Exception as e:
                print(f"[ERROR] {symbol}: {e}")

        sleep_time = max(0.1, min(0.5, len(symbols) / 100))
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
