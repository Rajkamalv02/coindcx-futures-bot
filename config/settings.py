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
CANDLE_INTERVAL = "15"      # '1', '5', '15', '60', '240', '1D'
CANDLE_LIMIT    = 200        # reduced from 500 as we don't need huge warmup for EMAs

# Confirmation timeframe (must be higher than CANDLE_INTERVAL)
CONFIRM_INTERVAL = "60"    # 1H confirmation for 15m signals

# ── EMA Settings ───────────────────────────────────────
EMA_FAST   = 9
EMA_SLOW   = 21
EMA_TREND  = 50              # major trend filter

# ── MACD Settings ──────────────────────────────────────
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# ── ADX Settings ───────────────────────────────────────
ADX_PERIOD = 14
ADX_MIN_THRESHOLD = 15

# RSI removed to keep system simple

# ── Volume Settings ────────────────────────────────────
VOLUME_MA_PERIOD = 20        # average volume lookback
VOLUME_MULTIPLIER = 1.2      # volume must be 1.2x above average

ATR_PERIOD            = 14
ATR_MULTIPLIER_TARGET = 3.0  # fallback
ATR_MULTIPLIER_SL     = 1.2
TARGET_PROFIT_PERCENT = 0.05 # 5% profit on investment (margin) excluding leverage

# ── Signal Scoring ─────────────────────────────────────
MIN_SCORE = 3                # minimum score out of 6 to send alert (3+ for quality signals)

# ── Dynamic Backtest Settings ──────────────────────────
BACKTEST_DAYS = 30           # Look back period for dynamic backtest
BACKTEST_MIN_WIN_RATE = 0.40 # Skip signal if historical win rate is below 40%
BACKTEST_MIN_TRADES = 5      # Need at least 5 historical trades to judge performance

# Impulse and BOS/CHOCH settings removed

# ── Symbol Filter ──────────────────────────────────────
WATCHLIST       = []
MIN_PRICE_USDT  = 0.5
MIN_VOLUME_USDT = 500000

# ── Scanner Loop ───────────────────────────────────────
SCAN_INTERVAL_MINUTES = 5   # Increased to 5 min to reduce duplicate candle analysis

# ── Trading ────────────────────────────────────────────
DEFAULT_LEVERAGE     = int(os.getenv("DEFAULT_LEVERAGE", 3))
TRADE_AMOUNT_USDT    = float(os.getenv("TRADE_AMOUNT_USDT", 10))
ENABLE_AUTO_TRADING  = True    # Set to True when real funds are in futures wallet
PAPER_TRADING        = False # Set to False when real funds are in futures wallet
