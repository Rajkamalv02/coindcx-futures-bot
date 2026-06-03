# CoinDCX Futures EMA Bot 🤖

An automated cryptocurrency futures scanner for [CoinDCX](https://coindcx.com) that detects **EMA crossover signals** using technical analysis and instantly sends alerts to your **Telegram** channel.

---

## ⚙️ Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Rajkamalv02/coindcx-futures-bot.git
cd coindcx-futures-bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```env
COINDCX_API_KEY=your_coindcx_api_key
COINDCX_API_SECRET=your_coindcx_api_secret
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

| Variable | Where to get it |
|---|---|
| `COINDCX_API_KEY` | [CoinDCX API Manager](https://coindcx.com/user/api) |
| `COINDCX_API_SECRET` | Same as above |
| `TELEGRAM_BOT_TOKEN` | Create a bot via [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_CHAT_ID` | Your channel/chat ID (use [@userinfobot](https://t.me/userinfobot)) |

### 4. (Optional) Customize Settings

Edit `config/settings.py` to tune the strategy:

```python
CANDLE_INTERVAL = "1h"        # Timeframe: 1m, 5m, 15m, 1h, 4h, 1d
CANDLE_LIMIT    = 100         # Number of historical candles to fetch

EMA_FAST = 9                  # Fast EMA period
EMA_SLOW = 21                 # Slow EMA period

RSI_PERIOD    = 14
RSI_LONG_MIN  = 50            # Only go LONG if RSI > 50
RSI_SHORT_MAX = 50            # Only go SHORT if RSI < 50

ATR_PERIOD           = 14
ATR_MULTIPLIER_TARGET = 2.0   # Target = Entry ± (ATR × 2.0)
ATR_MULTIPLIER_SL     = 1.0   # Stop Loss = Entry ∓ (ATR × 1.0)

WATCHLIST = []                # Leave empty to auto-scan all symbols
                              # Or set e.g. ["B-BTC_USDT", "B-ETH_USDT"]

SCAN_INTERVAL_MINUTES = 60    # How often to re-scan (in minutes)
```

---

## ▶️ Run

```bash
python main.py
```

The bot runs immediately on start, then repeats every `SCAN_INTERVAL_MINUTES`.

---

## 🗂️ Project Structure

```
coindcx-futures-bot/
│
├── main.py                  # Entry point — orchestrates the scan loop
│
├── config/
│   └── settings.py          # All tunable parameters (EMA, RSI, ATR, intervals)
│
├── api/
│   ├── auth.py              # HMAC-SHA256 authentication for CoinDCX private API
│   └── fetcher.py           # Fetches instruments, candles, tickers from CoinDCX
│
├── signals/
│   ├── indicators.py        # Builds OHLCV DataFrame and computes EMA/RSI/ATR
│   └── scanner.py           # Detects LONG/SHORT signals from indicator data
│
├── alerts/
│   └── telegram.py          # Formats and sends signal messages to Telegram
│
├── utils/
│   └── logger.py            # Unified logger (console + file output)
│
├── data/
│   └── logs/
│       └── bot.log          # Rolling log file (auto-created)
│
├── requirements.txt
├── pyrightconfig.json        # VS Code / Pylance import resolution config
└── .env                     # 🔒 Your secrets (never commit this)
```

---

## 🔄 How It Works — Full Flow

```
main.py
  │
  ├─ 1. Get Symbols
  │      ├── If WATCHLIST is set → use that list directly
  │      └── Else → call get_filtered_symbols()
  │                   ├── Fetches all active futures instruments from CoinDCX
  │                   ├── Fetches live ticker data (price + volume)
  │                   └── Filters out:
  │                         • Penny coins (price < $0.50)
  │                         • Low liquidity (volume < $500K USDT/day)
  │
  ├─ 2. For Each Symbol → fetch_candles()
  │      └── Calls CoinDCX public candles API
  │            with configured interval (default: 1h) and limit (100 candles)
  │
  ├─ 3. Build DataFrame + Calculate Indicators
  │      ├── build_dataframe()   → clean OHLCV pandas DataFrame
  │      └── calculate_indicators()
  │              ├── EMA 9   (fast)
  │              ├── EMA 21  (slow)
  │              ├── RSI 14
  │              └── ATR 14
  │
  ├─ 4. Detect Signal
  │      ├── 🟢 LONG  (Golden Cross)
  │      │     • EMA 9 crosses ABOVE EMA 21 (previous candle below, current above)
  │      │     • RSI > 50 (bullish momentum confirmed)
  │      │     • Target    = Entry + (ATR × 2.0)
  │      │     • Stop Loss = Entry - (ATR × 1.0)
  │      │
  │      └── 🔴 SHORT (Death Cross)
  │            • EMA 9 crosses BELOW EMA 21 (previous candle above, current below)
  │            • RSI < 50 (bearish momentum confirmed)
  │            • Target    = Entry - (ATR × 2.0)
  │            • Stop Loss = Entry + (ATR × 1.0)
  │
  └─ 5. Send Telegram Alert (if signal found)
         └── Formatted message with symbol, direction, entry, target, stop loss, RSI, ATR
```

---

## 📲 Telegram Signal Format

```
🟢 LONG Signal — B-BTC_USDT

📌 Entry     : $67432.1
🎯 Target    : $68844.5
🛑 Stop Loss : $66998.3
📊 RSI       : 58.4
📉 ATR       : $706.2
```

---

## 📋 Features

| Feature | Details |
|---|---|
| **Auto Symbol Discovery** | Scans all CoinDCX futures, filters by price & volume |
| **Manual Watchlist** | Optionally pin specific symbols in `settings.py` |
| **EMA Crossover Strategy** | Golden Cross (LONG) and Death Cross (SHORT) |
| **RSI Confirmation** | Filters out weak crossovers using RSI momentum check |
| **ATR-Based Targets** | Dynamic target and stop-loss calculated per coin's volatility |
| **Telegram Alerts** | Instant signal messages sent to your Telegram bot/channel |
| **Scheduled Scanning** | Auto re-runs every N minutes (default: 60) |
| **File + Console Logging** | All activity logged to `data/logs/bot.log` |
| **Error Resilience** | Per-symbol try/except — one bad symbol won't stop the scan |

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP calls to CoinDCX & Telegram APIs |
| `pandas` | OHLCV data handling |
| `pandas-ta` | Technical indicators (EMA, RSI, ATR) |
| `python-dotenv` | Load `.env` secrets |
| `schedule` | Periodic scan scheduling |

---

## ⚠️ Disclaimer

This bot is for **educational and informational purposes only**. It does **not** place trades automatically. Always do your own research before making any trading decisions. Cryptocurrency trading carries significant risk.
