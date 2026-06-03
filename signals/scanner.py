import pandas as pd
from config.settings import (
    EMA_FAST, EMA_SLOW,
    RSI_LONG_MIN, RSI_SHORT_MAX,
    ATR_MULTIPLIER_TARGET, ATR_MULTIPLIER_SL
)
from utils.logger import logger


def detect_signal(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    Detect EMA crossover signal on the latest two candles.
    Returns signal dict, or None if no signal.
    """
    if df.empty or len(df) < EMA_SLOW + 2:
        return None

    ema_fast = f'ema_{EMA_FAST}'
    ema_slow = f'ema_{EMA_SLOW}'

    # Last two candles
    prev = df.iloc[-2]
    curr = df.iloc[-1]

    close = curr['close']
    atr   = curr['atr']
    rsi   = curr['rsi']

    if pd.isna(atr) or pd.isna(rsi):
        return None

    signal = None

    # ── Golden Cross → LONG ────────────────────────────
    if (prev[ema_fast] <= prev[ema_slow] and
            curr[ema_fast] > curr[ema_slow] and
            rsi > RSI_LONG_MIN):

        signal = {
            "symbol":    symbol,
            "direction": "LONG",
            "entry":     round(float(close), 4),
            "target":    round(float(close + (atr * ATR_MULTIPLIER_TARGET)), 4),
            "stop_loss": round(float(close - (atr * ATR_MULTIPLIER_SL)), 4),
            "rsi":       round(float(rsi), 2),
            "atr":       round(float(atr), 4),
        }

    # ── Death Cross → SHORT ────────────────────────────
    elif (prev[ema_fast] >= prev[ema_slow] and
              curr[ema_fast] < curr[ema_slow] and
              rsi < RSI_SHORT_MAX):

        signal = {
            "symbol":    symbol,
            "direction": "SHORT",
            "entry":     round(float(close), 4),
            "target":    round(float(close - (atr * ATR_MULTIPLIER_TARGET)), 4),
            "stop_loss": round(float(close + (atr * ATR_MULTIPLIER_SL)), 4),
            "rsi":       round(float(rsi), 2),
            "atr":       round(float(atr), 4),
        }

    if signal:
        logger.info(f"Signal detected: {signal}")

    return signal