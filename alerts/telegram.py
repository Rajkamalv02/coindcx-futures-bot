import os
import requests
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """
    Send a plain/markdown message to the configured Telegram chat.
    Returns True on success.
    """
    try:
        url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id":    CHAT_ID,
            "text":       text,
            "parse_mode": parse_mode,
        }
        resp = requests.post(url, data=data, timeout=5)
        if resp.status_code == 200:
            logger.info("Telegram message sent successfully")
            return True
        logger.error(f"Telegram send_message failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram send_message exception: {e}")
        return False



def send_signal(signal: dict):
    direction  = signal['direction']
    emoji      = "🟢" if direction == "LONG" else "🔴"
    score      = signal.get('score', '-')
    strength   = signal.get('strength', '')
    reasons    = " | ".join(signal.get('reasons', []))
    tf         = signal.get('timeframe', '-')
    confirm_tf = signal.get('confirm_tf', '-')
    confirm    = signal.get('confirm_trend', '-').capitalize()
    inr_rate   = signal.get('inr_rate', 'N/A')
    stars      = "⭐" * score

    # Candles ago
    candles_ago = signal.get('candles_ago', 1)
    ago_text    = "current candle" if candles_ago == 1 else f"{candles_ago} candles ago"

    # Order execution info
    order_id     = signal.get('order_id')
    order_status = signal.get('order_status', '')
    quantity     = signal.get('quantity', '')
    leverage     = signal.get('leverage', '')

    order_line = ""
    if order_id:
        order_line = (
            f"\n\n🤖 *Order Placed*\n"
            f"🆔 Order ID  : `{order_id}`\n"
            f"📦 Quantity  : `{quantity}`\n"
            f"⚡ Leverage  : `{leverage}x`\n"
            f"📋 Status    : `{order_status}`"
        )
    elif order_status == "failed":
        order_line = "\n\n⚠️ *Order placement failed — manual entry needed*"

    message = (
        f"{emoji} *{direction} Signal — {signal['symbol']}*\n\n"
        f"{stars} *Score: {score}/5 ({strength})*\n"
        f"✅ _{reasons}_\n\n"
        f"⏱ Timeframe : `{tf}m → {confirm_tf}m` ({confirm} trend)\n"
        f"🕯 Crossover : `{ago_text}`\n"          # ← added here
        f"💱 Rate      : `1 USDT = ₹{inr_rate}`\n\n"
        f"📌 Entry     : `₹{signal['entry_inr']:,.2f}` _(${ signal['entry'] })_\n"
        f"🎯 Target    : `₹{signal['target_inr']:,.2f}` _(${ signal['target'] })_\n"
        f"🛑 Stop Loss : `₹{signal.get('stop_loss_inr', 0):,.2f}` _(${ signal.get('stop_loss', 0) })_\n"
        f"📊 RSI       : `{signal.get('rsi', '-')}`\n"
        f"📉 ATR       : `₹{signal.get('atr_inr', 0):,.2f}` _(${ signal.get('atr', 0) })_"
        f"{order_line}"
    )

    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id":    CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown"
    }

    resp = requests.post(url, data=data, timeout=5)

    if resp.status_code == 200:
        logger.info(f"Telegram alert sent for {signal['symbol']}")
    else:
        logger.error(f"Telegram failed: {resp.status_code} {resp.text}")