import pandas as pd
from config.settings import (
    EMA_FAST, EMA_SLOW,
    RSI_LONG_MIN, RSI_SHORT_MAX,
    ATR_MULTIPLIER_TARGET, ATR_MULTIPLIER_SL,
    USDT_INR_RATE
)
from utils.logger import logger


def _to_inr(usdt_value: float) -> float:
    return round(usdt_value * USDT_INR_RATE, 2)


def detect_signal(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    Detect EMA crossover signal on the latest two candles.
    Returns signal dict with USDT and INR values, or None if no signal.
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

        entry_usdt  = round(float(close), 4)
        target_usdt = round(float(close + (atr * ATR_MULTIPLIER_TARGET)), 4)
        sl_usdt     = round(float(close - (atr * ATR_MULTIPLIER_SL)), 4)
        atr_usdt    = round(float(atr), 4)

        signal = {
            "symbol":        symbol,
            "direction":     "LONG",
            "entry":         entry_usdt,
            "target":        target_usdt,
            "stop_loss":     sl_usdt,
            "rsi":           round(float(rsi), 2),
            "atr":           atr_usdt,
            "inr_rate":      USDT_INR_RATE,
            "entry_inr":     _to_inr(entry_usdt),
            "target_inr":    _to_inr(target_usdt),
            "stop_loss_inr": _to_inr(sl_usdt),
            "atr_inr":       _to_inr(atr_usdt),
        }

    # ── Death Cross → SHORT ────────────────────────────
    elif (prev[ema_fast] >= prev[ema_slow] and
              curr[ema_fast] < curr[ema_slow] and
              rsi < RSI_SHORT_MAX):

        entry_usdt  = round(float(close), 4)
        target_usdt = round(float(close - (atr * ATR_MULTIPLIER_TARGET)), 4)
        sl_usdt     = round(float(close + (atr * ATR_MULTIPLIER_SL)), 4)
        atr_usdt    = round(float(atr), 4)

        signal = {
            "symbol":        symbol,
            "direction":     "SHORT",
            "entry":         entry_usdt,
            "target":        target_usdt,
            "stop_loss":     sl_usdt,
            "rsi":           round(float(rsi), 2),
            "atr":           atr_usdt,
            "inr_rate":      USDT_INR_RATE,
            "entry_inr":     _to_inr(entry_usdt),
            "target_inr":    _to_inr(target_usdt),
            "stop_loss_inr": _to_inr(sl_usdt),
            "atr_inr":       _to_inr(atr_usdt),
        }

    if signal:
        logger.info(f"Signal detected: {signal}")

    return signal