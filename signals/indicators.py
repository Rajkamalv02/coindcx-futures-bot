import pandas as pd
import pandas_ta as ta
from config.settings import EMA_FAST, EMA_SLOW, RSI_PERIOD, ATR_PERIOD
from utils.logger import logger


def build_dataframe(candles: list) -> pd.DataFrame:
    """
    Convert raw candle list from CoinDCX into a clean OHLCV DataFrame.
    """
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)

    # CoinDCX candle keys: open, high, low, close, volume, time
    df.rename(columns={
        'open':   'open',
        'high':   'high',
        'low':    'low',
        'close':  'close',
        'volume': 'volume',
        'time':   'time'
    }, inplace=True)

    df['open']   = df['open'].astype(float)
    df['high']   = df['high'].astype(float)
    df['low']    = df['low'].astype(float)
    df['close']  = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)

    df.sort_values('time', inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add EMA fast, EMA slow, RSI, ATR columns to dataframe.
    """
    if df.empty:
        return df

    df[f'ema_{EMA_FAST}'] = ta.ema(df['close'], length=EMA_FAST)
    df[f'ema_{EMA_SLOW}'] = ta.ema(df['close'], length=EMA_SLOW)
    df['rsi']             = ta.rsi(df['close'], length=RSI_PERIOD)
    df['atr']             = ta.atr(df['high'], df['low'], df['close'],
                                   length=ATR_PERIOD)

    return df