import pandas as pd
import numpy as np
from config.settings import (
    EMA_FAST, EMA_SLOW, EMA_TREND,
    ADX_MIN_THRESHOLD, ATR_MULTIPLIER_SL, ATR_MULTIPLIER_TARGET,
    USDT_INR_RATE, CANDLE_INTERVAL, CONFIRM_INTERVAL,
    VOLUME_MULTIPLIER, DEFAULT_LEVERAGE, MIN_SCORE
)
from utils.logger import logger

# How many recent candles to look back for a crossover event.
# On 1H candles, 2 candles = 2 hours — a reasonable window.
CROSSOVER_LOOKBACK = 2


def _to_inr(usdt_value: float) -> float:
    return round(usdt_value * USDT_INR_RATE, 2)


def _detect_recent_crossover(df: pd.DataFrame, lookback: int = CROSSOVER_LOOKBACK) -> str | None:
    """
    Checks if an EMA9/21 crossover happened within the last `lookback` candles,
    not just the current one. Returns 'LONG', 'SHORT', or None.
    If multiple crosses happened in the window, the most recent one wins.
    """
    fast_col = f'ema_{EMA_FAST}'
    slow_col = f'ema_{EMA_SLOW}'

    if len(df) < lookback + 1:
        return None

    window = df.iloc[-(lookback + 1):]  # +1 so we have a "prev" for the earliest candle
    fast = window[fast_col]
    slow = window[slow_col]

    if fast.isna().any() or slow.isna().any():
        return None

    cross_up   = (fast.shift(1) <= slow.shift(1)) & (fast > slow)
    cross_down = (fast.shift(1) >= slow.shift(1)) & (fast < slow)

    # Drop the first row (no valid prev inside window)
    cross_up   = cross_up.iloc[1:]
    cross_down = cross_down.iloc[1:]

    if cross_up.any():
        last_up_idx = cross_up[cross_up].index[-1]
    else:
        last_up_idx = None

    if cross_down.any():
        last_down_idx = cross_down[cross_down].index[-1]
    else:
        last_down_idx = None

    if last_up_idx is None and last_down_idx is None:
        return None
    if last_up_idx is not None and last_down_idx is None:
        return "LONG"
    if last_down_idx is not None and last_up_idx is None:
        return "SHORT"

    # both happened in window — most recent one wins
    if last_up_idx is not None and last_down_idx is not None:
        return "LONG" if last_up_idx > last_down_idx else "SHORT"
    
    return None


def detect_signal(df: pd.DataFrame, symbol: str, confirm_trend: str = 'neutral') -> dict | None:
    if df.empty or len(df) < 50:
        return None

    curr = df.iloc[-1]

    ema_f_curr = curr.get(f'ema_{EMA_FAST}')
    ema_s_curr = curr.get(f'ema_{EMA_SLOW}')
    ema_t_curr = curr.get(f'ema_{EMA_TREND}')

    close_curr = curr['close']
    adx_curr   = curr.get('adx', 0)

    cols = [f'ema_{EMA_FAST}', f'ema_{EMA_SLOW}', f'ema_{EMA_TREND}']
    if any(pd.isna(curr.get(c)) for c in cols):
        logger.debug(f"{symbol}: SKIPPED — NaN in required indicator columns")
        return None

    # 1. Crossover Logic — checks last CROSSOVER_LOOKBACK candles
    direction = _detect_recent_crossover(df)

    logger.debug(
        f"{symbol}: ema9={ema_f_curr:.5f} ema21={ema_s_curr:.5f} "
        f"cross={direction} adx={adx_curr:.1f} close={close_curr:.5f} "
        f"ema50={ema_t_curr:.5f} confirm_trend={confirm_trend}"
    )

    if not direction:
        return None

    # 2. Hard Filters (EMA 50 and ADX) — checked on CURRENT candle,
    #    confirming the crossover is still valid now, not stale.
    if direction == "LONG" and close_curr <= ema_t_curr:
        logger.info(f"⏩ {symbol} LONG rejected: Price {close_curr:.5f} below EMA{EMA_TREND} {ema_t_curr:.5f}")
        return None
    if direction == "SHORT" and close_curr >= ema_t_curr:
        logger.info(f"⏩ {symbol} SHORT rejected: Price {close_curr:.5f} above EMA{EMA_TREND} {ema_t_curr:.5f}")
        return None

    if adx_curr < ADX_MIN_THRESHOLD:
        logger.info(f"⏩ {symbol} {direction} rejected: ADX {adx_curr:.2f} below {ADX_MIN_THRESHOLD}")
        return None

    # ── Overextension & RSI Safety Filters ────────────
    rsi_curr   = float(curr.get('rsi', 50))
    ema9_curr  = float(curr.get(f'ema_{EMA_FAST}', 0))
    dist_pct   = abs(close_curr - ema9_curr) / ema9_curr * 100 if ema9_curr > 0 else 0

    # Overextension threshold: 3% for 1H candles (wider than 15m's 2%)
    OVEREXTENSION_PCT = 3.0

    if direction == "LONG":
        if rsi_curr > 75:
            logger.info(f"⏩ {symbol} LONG rejected: Overbought (RSI {rsi_curr:.1f})")
            return None
        if dist_pct > OVEREXTENSION_PCT:
            logger.info(f"⏩ {symbol} LONG rejected: Overextended ({dist_pct:.1f}% from EMA9)")
            return None
    
    if direction == "SHORT":
        if rsi_curr < 25:
            logger.info(f"⏩ {symbol} SHORT rejected: Oversold (RSI {rsi_curr:.1f})")
            return None
        if dist_pct > OVEREXTENSION_PCT:
            logger.info(f"⏩ {symbol} SHORT rejected: Overextended ({dist_pct:.1f}% from EMA9)")
            return None

    # 3. HTF Confirmation Check (4H alignment)
    if direction == "LONG" and confirm_trend != "bullish":
        logger.info(f"⏩ {symbol} LONG rejected: HTF trend is '{confirm_trend}' (needs 'bullish')")
        return None
    if direction == "SHORT" and confirm_trend != "bearish":
        logger.info(f"⏩ {symbol} SHORT rejected: HTF trend is '{confirm_trend}' (needs 'bearish')")
        return None

    logger.debug(f"{symbol} {direction}: ALL GATES PASSED — building signal")

    # 4. Scoring System (Max 6)
    score = 3  # Base: Recent Cross + Price/EMA Trend + HTF Alignment
    reasons = [f"EMA Crossover ({EMA_FAST}/{EMA_SLOW})", f"Price/Trend Aligned", f"HTF Support"]

    if adx_curr > 25:
        score += 2
        reasons.append(f"Strong ADX ({adx_curr:.1f})")
    elif adx_curr > 18:
        score += 1
        reasons.append(f"Moderate ADX ({adx_curr:.1f})")

    vol = float(curr.get('volume', 0))
    vol_ma = float(curr.get('volume_ma', 0))
    if vol_ma > 0 and vol >= vol_ma * VOLUME_MULTIPLIER:
        score += 1
        reasons.append(f"High Volume ({vol/vol_ma:.1f}x)")

    score = min(score, 6)

    # 5. Target and SL Calculation (ATR-based)
    entry = round(close_curr, 4)
    atr_val = float(curr.get('atr', 0)) or (curr['high'] - curr['low'])

    sl_dist     = atr_val * ATR_MULTIPLIER_SL
    target_dist = atr_val * ATR_MULTIPLIER_TARGET

    if direction == "LONG":
        target = round(entry + target_dist, 4)
        sl     = round(entry - sl_dist, 4)
    else:
        target = round(entry - target_dist, 4)
        sl     = round(entry + sl_dist, 4)

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
        "rsi":           round(rsi_curr, 1),   # Q-3 FIX: actual RSI, was hardcoded 0.0
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
    
    # ── MIN_SCORE Enforcement ─────────────────────────────
    if score < MIN_SCORE:
        logger.info(f"{symbol} {direction} rejected: Score {score} < MIN_SCORE {MIN_SCORE}")
        return None

    return signal


def run_quick_backtest(df: pd.DataFrame, adx_threshold: int = ADX_MIN_THRESHOLD) -> dict:
    """
    Simulates trades based on EMA Crossover logic over the provided historical data.
    """
    if len(df) < 50:
        return {"win_rate": 0, "total_trades": 0, "net_pnl": 0}

    # IMP-12 FIX: Work on a copy to avoid mutating the caller's DataFrame
    df = df.copy()

    # Signal generation (Vectorized)
    ema_f = df[f'ema_{EMA_FAST}']
    ema_s = df[f'ema_{EMA_SLOW}']
    ema_t = df[f'ema_{EMA_TREND}']
    adx   = df.get('adx', pd.Series(0, index=df.index))
    
    # Crosses
    df['prev_ema_f'] = ema_f.shift(1)
    df['prev_ema_s'] = ema_s.shift(1)
    
    long_signals  = (df['prev_ema_f'] <= df['prev_ema_s']) & (ema_f > ema_s) & (df['close'] > ema_t) & (adx >= adx_threshold)
    short_signals = (df['prev_ema_f'] >= df['prev_ema_s']) & (ema_f < ema_s) & (df['close'] < ema_t) & (adx >= adx_threshold)
    
    signals = []
    for idx in df[long_signals | short_signals].index:
        if idx >= len(df) - 1: continue
        
        row = df.loc[idx]
        direction = "LONG" if long_signals.loc[idx] else "SHORT"
        entry = row['close']
        atr   = row['atr'] if 'atr' in row and not pd.isna(row['atr']) else (row['high'] - row['low'])
        
        # SL/TP (ATR-based)
        sl_dist = atr * ATR_MULTIPLIER_SL
        tp_dist = atr * ATR_MULTIPLIER_TARGET
        
        if direction == "LONG":
            sl, tp = entry - sl_dist, entry + tp_dist
        else:
            sl, tp = entry + sl_dist, entry - tp_dist
            
        signals.append({"idx": idx, "direction": direction, "entry": entry, "sl": sl, "tp": tp})

    # Trade simulation
    results = []
    pnls = []
    for s in signals:
        future_df = df.loc[s['idx']+1:]
        outcome = 0 # 1 for win, -1 for loss
        
        for _, f_row in future_df.iterrows():
            if s['direction'] == "LONG":
                if f_row['high'] >= s['tp']:
                    outcome = 1; break
                if f_row['low'] <= s['sl']:
                    outcome = -1; break
            else:
                if f_row['low'] <= s['tp']:
                    outcome = 1; break
                if f_row['high'] >= s['sl']:
                    outcome = -1; break
                    
        if outcome != 0:
            results.append(outcome)
            pnl = abs(s['tp'] - s['entry']) / s['entry'] if outcome == 1 else -abs(s['sl'] - s['entry']) / s['entry']
            pnls.append(pnl)

    if not results:
        return {"win_rate": 0, "total_trades": 0, "net_pnl": 0}

    wins = results.count(1)
    total = len(results)
    return {
        "win_rate": round(wins/total, 2),
        "total_trades": total,
        "net_pnl": round(sum(pnls) * 100, 2)
    }