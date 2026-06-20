from api.fetcher import get_candles, get_confirm_candles
from signals.indicators import build_dataframe, calculate_indicators, get_confirm_trend
from signals.scanner import _score_long, _score_short

SYMBOLS = ["B-DEXE_USDT", "B-EPIC_USDT", "B-LIT_USDT"]

for SYMBOL in SYMBOLS:
    candles = get_candles(SYMBOL)
    df      = build_dataframe(candles)
    df      = calculate_indicators(df)

    confirm_candles = get_confirm_candles(SYMBOL)
    df_confirm      = build_dataframe(confirm_candles)
    confirm_trend   = get_confirm_trend(df_confirm)

    prev  = df.iloc[-2]
    curr  = df.iloc[-1]

    ema9  = curr['ema_9']
    ema21 = curr['ema_21']
    ema50 = curr['ema_50']
    rsi   = curr['rsi']
    atr   = curr['atr']
    macd  = curr.get('macd')
    msig  = curr.get('macd_signal')
    vol   = curr['volume']
    volma = curr['volume_ma']

    long_cross  = prev['ema_9'] <= prev['ema_21'] and curr['ema_9'] > curr['ema_21']
    short_cross = prev['ema_9'] >= prev['ema_21'] and curr['ema_9'] < curr['ema_21']

    print(f"\n{'='*55}")
    print(f"Symbol        : {SYMBOL}")
    print(f"Confirm Trend : {confirm_trend}")
    print(f"Close         : {curr['close']}")
    print(f"EMA9 > EMA21  : {ema9 > ema21} | EMA21 > EMA50: {ema21 > ema50}")
    print(f"RSI           : {round(float(rsi),2)}")
    print(f"MACD > Signal : {macd > msig if macd and msig else 'N/A'}")
    print(f"Vol/VolMA     : {round(vol/volma,2) if volma else 'N/A'}x")
    print(f"Long Cross    : {long_cross}")
    print(f"Short Cross   : {short_cross}")

    if long_cross:
        score, reasons = _score_long(prev, curr, 'ema_9', 'ema_21')
        print(f"LONG Score    : {score}/5 | {reasons}")
    elif short_cross:
        score, reasons = _score_short(prev, curr, 'ema_9', 'ema_21')
        print(f"SHORT Score   : {score}/5 | {reasons}")
    else:
        print(f"No crossover on latest candle")
        print(f"EMA9 vs EMA21 gap: {round(float(ema9 - ema21), 4)}")