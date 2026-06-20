import pandas as pd
import numpy as np
from config.settings import (
    EMA_FAST, EMA_SLOW, EMA_TREND,
    ADX_MIN_THRESHOLD, ATR_MULTIPLIER_SL, TARGET_PROFIT_PERCENT,
    USDT_INR_RATE, CANDLE_INTERVAL, CONFIRM_INTERVAL,
    VOLUME_MULTIPLIER, DEFAULT_LEVERAGE
)
from utils.logger import scanner_logger as logger


def _to_inr(usdt_value: float) -> float:
    return round(usdt_value * USDT_INR_RATE, 2)


def detect_signal(df: pd.DataFrame, symbol: str, confirm_trend: str = 'neutral') -> dict | None:
    if df.empty or len(df) < 50:
        return None

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    # Required Indicator Columns - using pd.isna for robust NaN checking
    ema_f_curr = curr.get(f'ema_{EMA_FAST}')
    ema_s_curr = curr.get(f'ema_{EMA_SLOW}')
    ema_f_prev = prev.get(f'ema_{EMA_FAST}')
    ema_s_prev = prev.get(f'ema_{EMA_SLOW}')
    ema_t_curr = curr.get(f'ema_{EMA_TREND}')
    
    close_curr = curr['close']
    adx_curr   = curr.get('adx', 0)
    
    cols = [f'ema_{EMA_FAST}', f'ema_{EMA_SLOW}', f'ema_{EMA_TREND}']
    if any(pd.isna(curr.get(c)) for c in cols) or any(pd.isna(prev.get(c)) for c in cols[:2]):
        return None

    # 1. Crossover Logic
    is_long_cross  = (ema_f_prev <= ema_s_prev) and (ema_f_curr > ema_s_curr)
    is_short_cross = (ema_f_prev >= ema_s_prev) and (ema_f_curr < ema_s_curr)
    
    direction = None
    if is_long_cross:
        direction = "LONG"
    elif is_short_cross:
        direction = "SHORT"
        
    if not direction:
        return None

    # 2. Hard Filters (EMA 50 and ADX)
    # Long: Price > EMA50, Short: Price < EMA50
    if direction == "LONG" and close_curr <= ema_t_curr:
        logger.debug(f"{symbol} LONG rejected: Price {close_curr} below EMA{EMA_TREND}")
        return None
    if direction == "SHORT" and close_curr >= ema_t_curr:
        logger.debug(f"{symbol} SHORT rejected: Price {close_curr} above EMA{EMA_TREND}")
        return None

    if adx_curr < ADX_MIN_THRESHOLD:
        logger.debug(f"{symbol} {direction} rejected: ADX {adx_curr:.2f} below {ADX_MIN_THRESHOLD}")
        return None

    # 3. HTF Confirmation Check (Hard filter for strict setup)
    if direction == "LONG" and confirm_trend != "bullish":
        logger.debug(f"{symbol} LONG rejected: HTF trend is {confirm_trend}")
        return None
    if direction == "SHORT" and confirm_trend != "bearish":
        logger.debug(f"{symbol} SHORT rejected: HTF trend is {confirm_trend}")
        return None

    # 4. Scoring System (Max 6)
    score = 2  # Base score (Cross + ADX Gate + Trend Gate + HTF Gate)
    reasons = [f"EMA Crossover ({EMA_FAST}/{EMA_SLOW})", f"Price > EMA{EMA_TREND}", "HTF Confirmed"]
    
    # ADX Strength bonus
    if adx_curr > 25:
        score += 1
        reasons.append(f"Strong ADX ({adx_curr:.1f})")
    
    # Volume bonus (Contributes to score, not a gate)
    vol = float(curr.get('volume', 0))
    vol_ma = float(curr.get('volume_ma', 0))
    if vol_ma > 0 and vol >= vol_ma * VOLUME_MULTIPLIER:
        score += 1
        reasons.append(f"High Volume ({vol/vol_ma:.1f}x)")

    # HTF Alignment points
    score += 2

    score = min(score, 6)

    # 5. Target and SL Calculation
    entry = round(close_curr, 4)
    atr_val = float(curr.get('atr', 0)) or (curr['high'] - curr['low'])

    # Stop Loss: 1.2 * ATR
    sl_dist = atr_val * ATR_MULTIPLIER_SL
    
    # Target: Scaled based on leverage
    target_move_pct = TARGET_PROFIT_PERCENT / DEFAULT_LEVERAGE
    target_dist = entry * target_move_pct

    if direction == "LONG":
        target    = round(entry + target_dist, 4)
        sl        = round(entry - sl_dist, 4)
    else:
        target    = round(entry - target_dist, 4)
        sl        = round(entry + sl_dist, 4)

    signal = {
        "symbol":        symbol,
        "direction":     direction,
        "type":          "EMA_CROSS",
        "score":         score,
        "strength":      "Strong" if score >= 5 else "Normal",
        "reasons":       reasons,
        "entry":         entry,
        "target":        target,
        "stop_loss":     sl,
        "rsi":           0.0,
        "atr":           round(atr_val, 4),
        "atr_inr":       _to_inr(atr_val),
        "inr_rate":      USDT_INR_RATE,
        "entry_inr":     _to_inr(entry),
        "target_inr":    _to_inr(target),
        "stop_loss_inr": _to_inr(sl),
        "timeframe":     CANDLE_INTERVAL,
        "confirm_tf":    CONFIRM_INTERVAL,
        "confirm_trend": confirm_trend,
        "candles_ago":   1,
    }

    logger.info(f"Signal: {symbol} {direction} score={score} | {reasons}")
    return signal