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
    Prices shown in INR (primary) with USDT in parentheses.
    """
    direction = signal['direction']
    emoji     = "🟢" if direction == "LONG" else "🔴"
    inr_rate  = signal.get("inr_rate", "N/A")

    message = (
        f"{emoji} *{direction} Signal — {signal['symbol']}*\n\n"
        f"💱 Rate      : `1 USDT = ₹{inr_rate}`\n\n"
        f"📌 Entry     : `₹{signal['entry_inr']:,.2f}` _(${ signal['entry'] })_\n"
        f"🎯 Target    : `₹{signal['target_inr']:,.2f}` _(${ signal['target'] })_\n"
        f"🛑 Stop Loss : `₹{signal['stop_loss_inr']:,.2f}` _(${ signal['stop_loss'] })_\n"
        f"📊 RSI       : `{signal['rsi']}`\n"
        f"📉 ATR       : `₹{signal['atr_inr']:,.2f}` _(${ signal['atr'] })_"
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