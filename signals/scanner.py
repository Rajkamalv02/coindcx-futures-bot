import pandas as pd
import numpy as np
from config.settings import (
    ATR_MULTIPLIER_TARGET, ATR_MULTIPLIER_SL, TARGET_PROFIT_PERCENT,
    USDT_INR_RATE, CANDLE_INTERVAL, CONFIRM_INTERVAL,
    PIVOT_LOOKBACKS, REQUIRE_INDUCEMENT,
    RSI_LONG_MIN, RSI_LONG_MAX, RSI_SHORT_MIN, RSI_SHORT_MAX,
    VOLUME_MULTIPLIER, DEFAULT_LEVERAGE
)
from utils.logger import scanner_logger as logger

# Clean lookbacks — mirrors fix in indicators.py
CLEAN_PIVOT_LOOKBACKS = [lb for lb in PIVOT_LOOKBACKS if lb >= 5]

# Minimum bars that must be on the correct side before a BOS is valid
BOS_PREBREAK_BARS = 3


def _to_inr(usdt_value: float) -> float:
    return round(usdt_value * USDT_INR_RATE, 2)


def _detect_impulse_trigger(df: pd.DataFrame) -> dict | None:
    if len(df) < 2:
        return None
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    long_break  = prev['close'] <= prev['imp_upper'] and curr['close'] > curr['imp_upper']
    short_break = prev['close'] >= prev['imp_lower'] and curr['close'] < curr['imp_lower']
    if long_break:  return {"direction": "LONG",  "reason": "Impulse Breakout"}
    if short_break: return {"direction": "SHORT", "reason": "Impulse Breakout"}

    imp_dir       = curr['imp_dir']
    mad           = curr['imp_mad']
    band_thickness = mad * 0.5
    if imp_dir == 1  and curr['low']  < (curr['imp_lower'] + band_thickness):
        return {"direction": "LONG",  "reason": "Impulse Retest"}
    if imp_dir == -1 and curr['high'] > (curr['imp_upper'] - band_thickness):
        return {"direction": "SHORT", "reason": "Impulse Retest"}

    return None


def _check_recent_structure(df: pd.DataFrame, direction: str, lookback: int = 20) -> str | None:
    """
    FIX 3: BOS pre-break check deepened from 1 bar to BOS_PREBREAK_BARS (3).
    Previously: prev_bar['high'] < last_high  (only 1 bar checked)
    Now:        all bars in the window [idx-BOS_PREBREAK_BARS : idx] must be
                on the correct side of the level before calling it a valid break.
    """
    for i in range(1, lookback + 1):
        idx = -i
        if abs(idx) > len(df) - (BOS_PREBREAK_BARS + 2):
            break

        curr_bar = df.iloc[idx]
        close    = curr_bar['close']

        # Slice of bars that must have been on the correct side before the break
        pre_break_slice = df.iloc[idx - BOS_PREBREAK_BARS : idx]

        for lb in CLEAN_PIVOT_LOOKBACKS:
            ph_col, pl_col = f'ph_{lb}', f'pl_{lb}'
            sliced_df = df.iloc[:idx]

            valid_pivots_h = sliced_df[sliced_df[ph_col].notna()]
            valid_pivots_l = sliced_df[sliced_df[pl_col].notna()]
            if valid_pivots_h.empty or valid_pivots_l.empty:
                continue

            last_high = valid_pivots_h.iloc[-1][ph_col]
            last_low  = valid_pivots_l.iloc[-1][pl_col]

            if direction == "LONG":
                # All pre-break bars must have been below last_high
                pre_break_valid = all(pre_break_slice['high'] < last_high)
                if close > last_high and pre_break_valid:
                    struct_type = "BOS"
                    if len(valid_pivots_h) >= 2 and last_high < valid_pivots_h.iloc[-2][ph_col]:
                        struct_type = "CHOCH"
                    return f"{struct_type} (LB:{lb}, {i-1} bars ago)"
            else:
                # All pre-break bars must have been above last_low
                pre_break_valid = all(pre_break_slice['low'] > last_low)
                if close < last_low and pre_break_valid:
                    struct_type = "BOS"
                    if len(valid_pivots_l) >= 2 and last_low > valid_pivots_l.iloc[-2][pl_col]:
                        struct_type = "CHOCH"
                    return f"{struct_type} (LB:{lb}, {i-1} bars ago)"

    return None


def _passes_rsi_filter(rsi_val: float, direction: str) -> bool:
    """
    FIX 4: RSI filter was defined in settings but never enforced.
    Now gates every signal before it can be returned.
    """
    if direction == "LONG":
        return RSI_LONG_MIN <= rsi_val <= RSI_LONG_MAX
    else:
        return RSI_SHORT_MIN <= rsi_val <= RSI_SHORT_MAX


def _passes_volume_filter(curr: pd.Series) -> bool:
    """
    FIX 4: Volume multiplier was defined in settings but never enforced.
    Current volume must be >= volume_ma * VOLUME_MULTIPLIER.
    """
    volume    = float(curr.get('volume', 0))
    volume_ma = float(curr.get('volume_ma', 0))
    if volume_ma <= 0:
        return True  # can't judge — don't block
    return volume >= volume_ma * VOLUME_MULTIPLIER


def _find_recent_pivot(df: pd.DataFrame, direction: str, max_lookback: int = 40) -> float | None:
    """
    Finds the most recent pivot high/low within max_lookback candles.
    Prioritizes larger lookbacks for stronger structural significance.
    """
    prefix = 'pl_' if direction == "LONG" else 'ph_'
    available_lbs = sorted(CLEAN_PIVOT_LOOKBACKS, reverse=True) # [20, 15, 11, 5]

    for i in range(2, max_lookback + 2): # Start from 2 candles ago to avoid using current unconfirmed candle
        idx = -i
        if abs(idx) >= len(df): break

        row = df.iloc[idx]
        for lb in available_lbs:
            col = f"{prefix}{lb}"
            val = row.get(col)
            if pd.notna(val):
                return float(val)
    return None


def detect_signal(df: pd.DataFrame, symbol: str, confirm_trend: str = 'neutral') -> dict | None:
    if df.empty or len(df) < 50:
        return None

    curr = df.iloc[-1]

    # 1. Impulse trigger
    trigger = _detect_impulse_trigger(df)

    # 2. Structure proof
    structure_proof = None
    if trigger:
        structure_proof = _check_recent_structure(df, trigger['direction'], lookback=20)
    else:
        now_break_long  = _check_recent_structure(df, "LONG",  lookback=1)
        now_break_short = _check_recent_structure(df, "SHORT", lookback=1)
        if now_break_long:
            trigger         = {"direction": "LONG",  "reason": "Structure Break"}
            structure_proof = now_break_long
        elif now_break_short:
            trigger         = {"direction": "SHORT", "reason": "Structure Break"}
            structure_proof = now_break_short

    if not trigger:
        return None

    direction = trigger['direction']
    rsi_val   = round(float(curr.get('rsi', 0)), 2)

    # ── FIX 4a: RSI filter — hard gate ──────────────────────────────────────
    if not _passes_rsi_filter(rsi_val, direction):
        logger.debug(f"{symbol} {direction} rejected — RSI {rsi_val} out of range")
        return None

    # ── FIX 4b: Volume filter — hard gate ───────────────────────────────────
    if not _passes_volume_filter(curr):
        logger.debug(f"{symbol} {direction} rejected — volume below threshold")
        return None

    # Scoring
    reasons = [trigger['reason']]
    score   = 3

    if structure_proof:
        reasons.append(f"Confluence: {structure_proof}")
        score += 2

    # ── FIX 5: Trend alignment now adds +1 to score ──────────────────────────
    if confirm_trend != 'neutral':
        if (direction == "LONG"  and confirm_trend == "bullish") or \
           (direction == "SHORT" and confirm_trend == "bearish"):
            reasons.append(f"Trend aligned ({confirm_trend})")
            score += 1  # was appending reason but never adding to score

    close_val = float(curr['close'])
    atr_val   = float(curr.get('atr', 0)) or (curr['high'] - curr['low'])

    # ── HYBRID ENTRY LOGIC ──────────────────────────────────────────────────
    # Aggressive for Momentum (Breakouts/BOS/CHOCH), Conservative for Retests.
    if trigger.get('reason') == "Impulse Retest":
        entry = round(float(curr['imp_basis']), 4)
        logger.debug(f"{symbol} using CONSERVATIVE entry (EMA) for retest: {entry}")
    else:
        entry = round(close_val, 4)
        logger.debug(f"{symbol} using AGGRESSIVE entry (Market) for breakdown/breakout: {entry}")

    # Target calculation based on % profit of margin (investment)
    # Target Move % = TARGET_PROFIT_PERCENT / Leverage
    target_move_pct = TARGET_PROFIT_PERCENT / DEFAULT_LEVERAGE
    target_distance = entry * target_move_pct

    if direction == "LONG":
        target = round(entry + target_distance, 4)
        
        # Structural Stop Loss
        pivot = _find_recent_pivot(df, "LONG")
        if pivot:
            sl = round(pivot - (atr_val * 0.5), 4)
            # Safety: Ensure SL is actually below entry and not too crazy far
            if sl >= entry * 0.999: # Too tight
                sl = round(entry - (atr_val * 2.0), 4)
            elif sl < entry * 0.85: # Max 15% drop allowed for safety
                sl = round(entry * 0.85, 4)
        else:
            sl = round(entry - (atr_val * 2.0), 4) # Wide ATR fallback
    else:
        target = round(entry - target_distance, 4)

        # Structural Stop Loss
        pivot = _find_recent_pivot(df, "SHORT")
        if pivot:
            sl = round(pivot + (atr_val * 0.5), 4)
            # Safety: Ensure SL is actually above entry
            if sl <= entry * 1.001: # Too tight
                sl = round(entry + (atr_val * 2.0), 4)
            elif sl > entry * 1.15: # Max 15% pump allowed
                sl = round(entry * 1.15, 4)
        else:
            sl = round(entry + (atr_val * 2.0), 4) # Wide ATR fallback

    signal = {
        "symbol":        symbol,
        "direction":     direction,
        "type":          "COMBINED",
        "score":         min(score, 6),   # max is now 6 (3 base + 2 structure + 1 trend)
        "strength":      "Strong" if score >= 5 else "Normal",
        "reasons":       reasons,
        "entry":         entry,
        "target":        target,
        "stop_loss":     sl,
        "rsi":           rsi_val,
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