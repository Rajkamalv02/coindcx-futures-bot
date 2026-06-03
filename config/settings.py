# ── Currency ───────────────────────────────────────────
USDT_INR_RATE = 102.0        # 1 USDT = ₹102 (update manually as needed)

# ── Timeframe ──────────────────────────────────────────
CANDLE_INTERVAL = "1h"       # 1m, 5m, 15m, 1h, 4h, 1d
CANDLE_LIMIT    = 100        # number of candles to fetch

# ── EMA Settings ───────────────────────────────────────
EMA_FAST = 9
EMA_SLOW = 21

# ── RSI Settings ───────────────────────────────────────
RSI_PERIOD     = 14
RSI_LONG_MIN   = 50          # only take longs if RSI > 50
RSI_SHORT_MAX  = 50          # only take shorts if RSI < 50

# ── ATR Settings ───────────────────────────────────────
ATR_PERIOD     = 14
ATR_MULTIPLIER_TARGET = 2.0
ATR_MULTIPLIER_SL     = 1.0

# ── Symbols to Scan ────────────────────────────────────
# Leave empty to auto-scan filtered symbols
WATCHLIST = []

# Symbol filter thresholds (used when WATCHLIST is empty)
MIN_PRICE_USDT  = 0.5       # exclude coins below $0.5
MIN_VOLUME_USDT = 500000    # exclude coins with <$500K daily volume

# ── Scanner Loop ───────────────────────────────────────
SCAN_INTERVAL_MINUTES = 60   # run scanner every 60 minutes