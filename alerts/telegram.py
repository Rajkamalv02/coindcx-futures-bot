import os
import requests
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

def send_signal(signal: dict):
    """
    Send a formatted signal message to Telegram.
    """
    direction = signal['direction']
    emoji     = "🟢" if direction == "LONG" else "🔴"

    message = (
        f"{emoji} *{direction} Signal — {signal['symbol']}*\n\n"
        f"📌 Entry     : `${signal['entry']}`\n"
        f"🎯 Target    : `${signal['target']}`\n"
        f"🛑 Stop Loss : `${signal['stop_loss']}`\n"
        f"📊 RSI       : `{signal['rsi']}`\n"
        f"📉 ATR       : `${signal['atr']}`"
    )

    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id":    CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown"
    }

    resp = requests.post(url, data=data)

    if resp.status_code == 200:
        logger.info(f"Telegram alert sent for {signal['symbol']}")
    else:
        logger.error(f"Telegram failed: {resp.status_code} {resp.text}")