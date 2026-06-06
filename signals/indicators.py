import pandas as pd
import pandas_ta as ta
from config.settings import (
    EMA_FAST, EMA_SLOW, EMA_TREND,
    RSI_PERIOD, ATR_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    VOLUME_MA_PERIOD
)
from utils.logger import logger


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


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
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
    macd = ta.macd(df['close'],
                   fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if macd is not None:
        df['macd']        = macd[f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}']
        df['macd_signal'] = macd[f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}']

    # Volume moving average
    df['volume_ma'] = df['volume'].rolling(window=VOLUME_MA_PERIOD).mean()

    return df


def get_confirm_trend(df_confirm: pd.DataFrame) -> str:
    """
    Returns 'bullish', 'bearish', or 'neutral' based on
    EMA alignment on the confirmation timeframe.
    """
    if df_confirm.empty or len(df_confirm) < EMA_TREND + 2:
        return 'neutral'

    df_confirm = calculate_indicators(df_confirm)
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