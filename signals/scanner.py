import pandas as pd
from config.settings import (
    EMA_FAST, EMA_SLOW, EMA_TREND,
    RSI_LONG_MIN, RSI_LONG_MAX,
    RSI_SHORT_MIN, RSI_SHORT_MAX,
    ATR_MULTIPLIER_TARGET, ATR_MULTIPLIER_SL,
    VOLUME_MULTIPLIER, MIN_SCORE,
    USDT_INR_RATE, CANDLE_INTERVAL, CONFIRM_INTERVAL
)
from utils.logger import logger


def _to_inr(usdt_value: float) -> float:
    return round(usdt_value * USDT_INR_RATE, 2)


def _find_recent_crossover(df: pd.DataFrame, ema_fast: str, ema_slow: str,
                            lookback: int = 3) -> tuple[str, int]:
    """
    Check if a crossover happened within last `lookback` candles.
    Returns ('long', candles_ago) or ('short', candles_ago) or (None, 0)
    """
    for i in range(1, lookback + 1):
        if len(df) < i + 2:
            break
        prev = df.iloc[-(i + 1)]
        curr = df.iloc[-i]

        long_cross  = prev[ema_fast] <= prev[ema_slow] and curr[ema_fast] > curr[ema_slow]
        short_cross = prev[ema_fast] >= prev[ema_slow] and curr[ema_fast] < curr[ema_slow]

        if long_cross:
            return ('long', i)
        if short_cross:
            return ('short', i)

    return (None, 0)


def _score_long(prev, curr, ema_fast: str, ema_slow: str) -> tuple[int, list]:
    """Returns (score, reasons) for a potential LONG signal."""
    score   = 0
    reasons = []

    # 1. EMA crossover
    if prev[ema_fast] <= prev[ema_slow] and curr[ema_fast] > curr[ema_slow]:
        score += 1
        reasons.append("EMA crossover")

    # 2. Price above EMA 50 (major trend)
    ema_trend = curr.get(f'ema_{EMA_TREND}')
    if not pd.isna(ema_trend) and curr['close'] > ema_trend:
        score += 1
        reasons.append("Above EMA50")

    # 3. RSI in valid long zone
    rsi = curr['rsi']
    if not pd.isna(rsi) and RSI_LONG_MIN < rsi < RSI_LONG_MAX:
        score += 1
        reasons.append(f"RSI {round(float(rsi), 1)}")

    # 4. MACD bullish crossover
    macd       = curr.get('macd')
    macd_sig   = curr.get('macd_signal')
    prev_macd  = prev.get('macd')
    prev_msig  = prev.get('macd_signal')
    if all(not pd.isna(v) for v in [macd, macd_sig, prev_macd, prev_msig]):
        if prev_macd <= prev_msig and macd > macd_sig:
            score += 1
            reasons.append("MACD cross")

    # 5. Volume above average
    vol    = curr.get('volume')
    vol_ma = curr.get('volume_ma')
    if not pd.isna(vol) and not pd.isna(vol_ma) and vol_ma > 0:
        vol_ratio = vol / vol_ma
        if vol_ratio >= VOLUME_MULTIPLIER:
            score += 1
            reasons.append(f"Vol {round(vol_ratio, 1)}x avg")

    return score, reasons


def _score_short(prev, curr, ema_fast: str, ema_slow: str) -> tuple[int, list]:
    """Returns (score, reasons) for a potential SHORT signal."""
    score   = 0
    reasons = []

    # 1. EMA crossover
    if prev[ema_fast] >= prev[ema_slow] and curr[ema_fast] < curr[ema_slow]:
        score += 1
        reasons.append("EMA crossover")

    # 2. Price below EMA 50 (major trend)
    ema_trend = curr.get(f'ema_{EMA_TREND}')
    if not pd.isna(ema_trend) and curr['close'] < ema_trend:
        score += 1
        reasons.append("Below EMA50")

    # 3. RSI in valid short zone
    rsi = curr['rsi']
    if not pd.isna(rsi) and RSI_SHORT_MIN < rsi < RSI_SHORT_MAX:
        score += 1
        reasons.append(f"RSI {round(float(rsi), 1)}")

    # 4. MACD bearish crossover
    macd       = curr.get('macd')
    macd_sig   = curr.get('macd_signal')
    prev_macd  = prev.get('macd')
    prev_msig  = prev.get('macd_signal')
    if all(not pd.isna(v) for v in [macd, macd_sig, prev_macd, prev_msig]):
        if prev_macd >= prev_msig and macd < macd_sig:
            score += 1
            reasons.append("MACD cross")

    # 5. Volume above average
    vol    = curr.get('volume')
    vol_ma = curr.get('volume_ma')
    if not pd.isna(vol) and not pd.isna(vol_ma) and vol_ma > 0:
        vol_ratio = vol / vol_ma
        if vol_ratio >= VOLUME_MULTIPLIER:
            score += 1
            reasons.append(f"Vol {round(vol_ratio, 1)}x avg")

    return score, reasons


def detect_signal(df: pd.DataFrame, symbol: str,
                  confirm_trend: str = 'neutral') -> dict | None:

    if df.empty or len(df) < EMA_TREND + 2:
        return None

    ema_fast = f'ema_{EMA_FAST}'
    ema_slow = f'ema_{EMA_SLOW}'

    curr  = df.iloc[-1]
    close = curr['close']
    atr   = curr['atr']
    rsi   = curr['rsi']

    if pd.isna(atr) or pd.isna(rsi):
        return None

    # Find crossover within last 3 candles
    cross_type, candles_ago = _find_recent_crossover(df, ema_fast, ema_slow, lookback=3)

    if not cross_type:
        return None

    # Use the candle right after crossover as prev/curr for scoring
    idx  = -(candles_ago)
    prev = df.iloc[idx - 1]
    curr_score = df.iloc[idx]

    # But use latest candle values for price levels
    close_val = float(curr['close'])
    atr_val   = float(curr['atr'])

    signal    = None

    # ── LONG ───────────────────────────────────────────
    if cross_type == 'long' and confirm_trend in ('bullish', 'neutral'):
        # Trend must still be holding on latest candle
        if curr[ema_fast] <= curr[ema_slow]:
            return None  # crossover reversed, skip

        score, reasons = _score_long(prev, curr_score, ema_fast, ema_slow)

        if score >= MIN_SCORE:
            strength    = "Strong" if score == 5 else "Good"
            entry_usdt  = round(close_val, 4)
            target_usdt = round(close_val + (atr_val * ATR_MULTIPLIER_TARGET), 4)
            sl_usdt     = round(close_val - (atr_val * ATR_MULTIPLIER_SL), 4)

            signal = {
                "symbol":        symbol,
                "direction":     "LONG",
                "score":         score,
                "strength":      strength,
                "reasons":       reasons,
                "candles_ago":   candles_ago,
                "confirm_trend": confirm_trend,
                "timeframe":     CANDLE_INTERVAL,
                "confirm_tf":    CONFIRM_INTERVAL,
                "entry":         entry_usdt,
                "target":        target_usdt,
                "stop_loss":     sl_usdt,
                "rsi":           round(float(rsi), 2),
                "atr":           round(atr_val, 4),
                "inr_rate":      USDT_INR_RATE,
                "entry_inr":     _to_inr(entry_usdt),
                "target_inr":    _to_inr(target_usdt),
                "stop_loss_inr": _to_inr(sl_usdt),
                "atr_inr":       _to_inr(atr_val),
            }

    # ── SHORT ──────────────────────────────────────────
    elif cross_type == 'short' and confirm_trend in ('bearish', 'neutral'):
        # Trend must still be holding on latest candle
        if curr[ema_fast] >= curr[ema_slow]:
            return None  # crossover reversed, skip

        score, reasons = _score_short(prev, curr_score, ema_fast, ema_slow)

        if score >= MIN_SCORE:
            strength    = "Strong" if score == 5 else "Good"
            entry_usdt  = round(close_val, 4)
            target_usdt = round(close_val - (atr_val * ATR_MULTIPLIER_TARGET), 4)
            sl_usdt     = round(close_val + (atr_val * ATR_MULTIPLIER_SL), 4)

            signal = {
                "symbol":        symbol,
                "direction":     "SHORT",
                "score":         score,
                "strength":      strength,
                "reasons":       reasons,
                "candles_ago":   candles_ago,
                "confirm_trend": confirm_trend,
                "timeframe":     CANDLE_INTERVAL,
                "confirm_tf":    CONFIRM_INTERVAL,
                "entry":         entry_usdt,
                "target":        target_usdt,
                "stop_loss":     sl_usdt,
                "rsi":           round(float(rsi), 2),
                "atr":           round(atr_val, 4),
                "inr_rate":      USDT_INR_RATE,
                "entry_inr":     _to_inr(entry_usdt),
                "target_inr":    _to_inr(target_usdt),
                "stop_loss_inr": _to_inr(sl_usdt),
                "atr_inr":       _to_inr(atr_val),
            }

    if signal:
        logger.info(f"Signal [{score}/5] {symbol} {signal['direction']} "
                    f"| crossover {candles_ago} candle(s) ago | {reasons}")

    return signal