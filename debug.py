from api.fetcher import get_candles, get_confirm_candles
from signals.indicators import build_dataframe, calculate_indicators, get_confirm_trend
from signals.scanner import detect_signal
from config.settings import EMA_FAST, EMA_SLOW, EMA_TREND

SYMBOLS = ["B-DEXE_USDT", "B-EPIC_USDT", "B-LIT_USDT"]

for SYMBOL in SYMBOLS:
    candles = get_candles(SYMBOL)
    df      = build_dataframe(candles)
    df      = calculate_indicators(df, symbol=SYMBOL)

    confirm_candles = get_confirm_candles(SYMBOL)
    df_confirm      = build_dataframe(confirm_candles)
    confirm_trend   = get_confirm_trend(df_confirm, symbol=SYMBOL)

    if df.empty or len(df) < 2:
        print(f"\n{SYMBOL}: not enough candle data")
        continue

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    ema_f = curr[f'ema_{EMA_FAST}']
    ema_s = curr[f'ema_{EMA_SLOW}']
    ema_t = curr[f'ema_{EMA_TREND}']
    rsi   = curr['rsi']
    atr   = curr['atr']
    macd  = curr.get('macd')
    msig  = curr.get('macd_signal')
    vol   = curr['volume']
    volma = curr['volume_ma']

    long_cross  = prev[f'ema_{EMA_FAST}'] <= prev[f'ema_{EMA_SLOW}'] and ema_f > ema_s
    short_cross = prev[f'ema_{EMA_FAST}'] >= prev[f'ema_{EMA_SLOW}'] and ema_f < ema_s

    print(f"\n{'='*55}")
    print(f"Symbol        : {SYMBOL}")
    print(f"Confirm Trend : {confirm_trend}")
    print(f"Close         : {curr['close']}")
    print(f"EMA{EMA_FAST} > EMA{EMA_SLOW}  : {ema_f > ema_s} | EMA{EMA_SLOW} > EMA{EMA_TREND}: {ema_s > ema_t}")
    print(f"RSI           : {round(float(rsi), 2)}")
    print(f"MACD > Signal : {macd > msig if macd and msig else 'N/A'}")
    print(f"Vol/VolMA     : {round(vol/volma, 2) if volma else 'N/A'}x")
    print(f"Long Cross    : {long_cross}")
    print(f"Short Cross   : {short_cross}")

    # Run the real signal detector so this matches what main.py would do
    signal = detect_signal(df, SYMBOL, confirm_trend)
    if signal:
        print(f"SIGNAL        : {signal['direction']} | score={signal['score']} | {signal['reasons']}")
    else:
        print("SIGNAL        : None (rejected by filters or no crossover)")