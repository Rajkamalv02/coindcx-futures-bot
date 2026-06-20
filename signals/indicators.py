import pandas as pd
import pandas_ta as ta
from config.settings import (
    EMA_FAST, EMA_SLOW, EMA_TREND,
    RSI_PERIOD, ATR_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    VOLUME_MA_PERIOD,
    IMPULSE_TREND_LEN, IMPULSE_LOOKBACK, IMPULSE_DECAY,
    IMPULSE_MAD_LEN, IMPULSE_BAND_MIN, IMPULSE_BAND_MAX,
    PIVOT_LOOKBACKS
)
from utils.logger import logger
import numpy as np

# ── FIX 1: Persistent impulse state per symbol ─────────────────────────────
# Previously curr_impulse/curr_dir reset to 0.0 on every call.
# Now seeded from last known state so the recursive decay is continuous.
_impulse_state: dict[str, dict] = {}

# ── FIX 2: Strip noisy pivot lookbacks at module level ──────────────────────
# LB=1,2,3 flags nearly every candle as a pivot → BOS fires on noise.
# Only keep lookbacks >= 5.
CLEAN_PIVOT_LOOKBACKS = [lb for lb in PIVOT_LOOKBACKS if lb >= 5]


def build_dataframe(candles: list) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df['open']   = df['open'].astype(float)
    df['high']   = df['high'].astype(float)
    df['low']    = df['low'].astype(float)
    df['close']  = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df.sort_values('time', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def calculate_indicators(df: pd.DataFrame, symbol: str = "default") -> pd.DataFrame:
    if df.empty:
        return df

    # EMA
    df[f'ema_{EMA_FAST}']  = ta.ema(df['close'], length=EMA_FAST)
    df[f'ema_{EMA_SLOW}']  = ta.ema(df['close'], length=EMA_SLOW)
    df[f'ema_{EMA_TREND}'] = ta.ema(df['close'], length=EMA_TREND)

    # RSI
    df['rsi'] = ta.rsi(df['close'], length=RSI_PERIOD)

    # ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)

    # MACD
    macd = ta.macd(df['close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if macd is not None:
        df['macd']        = macd[f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}']
        df['macd_signal'] = macd[f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}']

    # Volume MA
    df['volume_ma'] = df['volume'].rolling(window=VOLUME_MA_PERIOD).mean()

    # Impulse Engine — pass symbol so state persists between scans
    df = calculate_impulse_engine(df, symbol=symbol)

    # Market Structure — uses cleaned lookbacks only
    df = calculate_structure(df)

    return df


def get_confirm_trend(df_confirm: pd.DataFrame, symbol: str = "default") -> str:
    if df_confirm.empty or len(df_confirm) < EMA_TREND + 2:
        return 'neutral'

    df_confirm = calculate_indicators(df_confirm, symbol=f"{symbol}_confirm")
    last = df_confirm.iloc[-1]

    ema_fast  = last.get(f'ema_{EMA_FAST}')
    ema_slow  = last.get(f'ema_{EMA_SLOW}')
    ema_trend = last.get(f'ema_{EMA_TREND}')

    if any(pd.isna(v) for v in [ema_fast, ema_slow, ema_trend]):
        return 'neutral'

    if ema_fast > ema_slow > ema_trend:
        return 'bullish'
    elif ema_fast < ema_slow < ema_trend:
        return 'bearish'
    return 'neutral'


def calculate_impulse_engine(df: pd.DataFrame, symbol: str = "default") -> pd.DataFrame:
    """
    FIX 1: Impulse state (curr_impulse, curr_dir) now persists across scans
    per symbol. Previously reset to 0.0 on every call, breaking the recursive
    decay that the Pine Script 'var' keyword provided.
    """
    if df.empty or len(df) < max(IMPULSE_TREND_LEN, IMPULSE_MAD_LEN):
        return df

    # Basis (EMA)
    df['imp_basis'] = ta.ema(df['close'], length=IMPULSE_TREND_LEN)

    # MAD
    df['imp_mean'] = ta.sma(df['close'], length=IMPULSE_MAD_LEN)
    df['imp_mad']  = ta.sma((df['close'] - df['imp_mean']).abs(), length=IMPULSE_MAD_LEN)

    # Raw Impulse
    df['raw_impulse'] = (df['close'] - df['close'].shift(IMPULSE_LOOKBACK)) / df['imp_mad']
    df['raw_impulse'] = df['raw_impulse'].replace([np.inf, -np.inf], 0).fillna(0)

    # ── Seed from last known state instead of always starting at 0 ──────────
    state = _impulse_state.get(symbol, {"curr_impulse": 0.0, "curr_dir": 0})
    curr_impulse = state["curr_impulse"]
    curr_dir     = state["curr_dir"]

    impulses     = np.zeros(len(df))
    impulse_dirs = np.zeros(len(df))
    raw_vals     = df['raw_impulse'].values

    for i in range(len(df)):
        raw_val = raw_vals[i]
        abs_raw = abs(raw_val)

        if abs_raw > 1.0:
            curr_impulse = abs_raw
            curr_dir = 1 if raw_val > 0 else -1
        else:
            curr_impulse = curr_impulse * IMPULSE_DECAY

        impulses[i]     = curr_impulse
        impulse_dirs[i] = curr_dir

    # ── Persist final state for next scan ────────────────────────────────────
    _impulse_state[symbol] = {"curr_impulse": float(curr_impulse), "curr_dir": int(curr_dir)}

    df['imp_value'] = impulses
    df['imp_dir']   = impulse_dirs

    # Freshness & Bands
    df['freshness'] = (df['imp_value'] / 2.0).clip(upper=1.0)
    df['band_mult'] = IMPULSE_BAND_MAX - (IMPULSE_BAND_MAX - IMPULSE_BAND_MIN) * df['freshness']
    df['imp_upper'] = df['imp_basis'] + df['imp_mad'] * df['band_mult']
    df['imp_lower'] = df['imp_basis'] - df['imp_mad'] * df['band_mult']

    return df


def calculate_structure(df: pd.DataFrame) -> pd.DataFrame:
    """
    FIX 2: Uses CLEAN_PIVOT_LOOKBACKS (>= 5 only).
    LB=1,2,3 were generating pivot flags on nearly every candle,
    causing BOS/CHOCH to fire on noise constantly.
    """
    if df.empty or len(df) < max(CLEAN_PIVOT_LOOKBACKS) * 2:
        return df

    highs = df['high'].values
    lows  = df['low'].values

    for lb in CLEAN_PIVOT_LOOKBACKS:
        ph_flags = np.zeros(len(df), dtype=bool)
        pl_flags = np.zeros(len(df), dtype=bool)

        for i in range(lb, len(df) - lb):
            val_h = highs[i]
            if all(val_h >= highs[i-lb:i]) and all(val_h > highs[i+1:i+lb+1]):
                ph_flags[i] = True

            val_l = lows[i]
            if all(val_l <= lows[i-lb:i]) and all(val_l < lows[i+1:i+lb+1]):
                pl_flags[i] = True

        df[f'ph_{lb}'] = np.where(ph_flags, highs, np.nan)
        df[f'pl_{lb}'] = np.where(pl_flags, lows, np.nan)

    return df