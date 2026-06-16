from pandas_ta.volatility import true_range
from pandas_ta.volatility import true_range
import os
from dotenv import load_dotenv
load_dotenv()

# ── Currency ───────────────────────────────────────────
USDT_INR_RATE = 102.0        # 1 USDT = ₹102 (update manually or via API)
TRADE_THRESHOLD_INR = 500.0  # Amount in INR to allocate per trade

# ── Timeframes ─────────────────────────────────────────
# Primary timeframe for signal detection
CANDLE_INTERVAL = "60"      # '1', '5', '15', '60', '240', '1D'
CANDLE_LIMIT    = 150        # increased for EMA 50 warmup

# Confirmation timeframe (must be higher than CANDLE_INTERVAL)
# 15m → 60, 60 → 240, 240 → 1D
CONFIRM_INTERVAL = "240"    # 4H confirmation for 1H signals

# ── EMA Settings ───────────────────────────────────────
EMA_FAST   = 9
EMA_SLOW   = 21
EMA_TREND  = 50              # major trend filter

# ── MACD Settings ──────────────────────────────────────
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# ── RSI Settings ───────────────────────────────────────
RSI_PERIOD     = 14
RSI_LONG_MIN   = 50
RSI_LONG_MAX   = 70          # avoid overbought longs
RSI_SHORT_MIN  = 30          # avoid oversold shorts
RSI_SHORT_MAX  = 50

# ── Volume Settings ────────────────────────────────────
VOLUME_MA_PERIOD = 20        # average volume lookback
VOLUME_MULTIPLIER = 1.2      # volume must be 1.2x above average

# ── ATR Settings ───────────────────────────────────────
ATR_PERIOD            = 14
ATR_MULTIPLIER_TARGET = 3.0  # 1:3 RR
ATR_MULTIPLIER_SL     = 1.0

# ── Signal Scoring ─────────────────────────────────────
MIN_SCORE = 3                # minimum score out of 5 to send alert (3+ for quality signals)

# ── Symbol Filter ──────────────────────────────────────
WATCHLIST       = []
MIN_PRICE_USDT  = 0.5
MIN_VOLUME_USDT = 500000

# ── Scanner Loop ───────────────────────────────────────
SCAN_INTERVAL_MINUTES = 60   # scan every 60 min to match 1H candle timeframe

# ── Trading ────────────────────────────────────────────
DEFAULT_LEVERAGE     = int(os.getenv("DEFAULT_LEVERAGE", 3))
TRADE_AMOUNT_USDT    = float(os.getenv("TRADE_AMOUNT_USDT", 10))
ENABLE_AUTO_TRADING  = True    # Set to True when real funds are in futures wallet
PAPER_TRADING        = False # Set to False when real funds are in futures wallet
