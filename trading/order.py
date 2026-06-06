import os
import requests
from dotenv import load_dotenv
from api.auth import get_futures_auth_headers, get_timestamp
from config.settings import DEFAULT_LEVERAGE, TRADE_AMOUNT_USDT
from utils.logger import logger

load_dotenv()

BASE_URL = "https://api.coindcx.com"


def set_leverage(symbol: str, leverage: int = DEFAULT_LEVERAGE) -> bool:
    try:
        body = {
            "timestamp": get_timestamp(),
            "pair":      symbol,
            "leverage":  leverage,
        }
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(
            f"{BASE_URL}/exchange/v1/derivatives/futures/leverage/update",
            headers=headers,
            data=json_body
        )
        if resp.status_code == 200:
            logger.info(f"Leverage set to {leverage}x for {symbol}")
            return True
        logger.warning(f"Leverage not set for {symbol}: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Set leverage error: {e}")
        return False


def calculate_quantity(entry_price: float,
                       trade_amount_usdt: float = TRADE_AMOUNT_USDT,
                       leverage: int = DEFAULT_LEVERAGE) -> float:
    notional = trade_amount_usdt * leverage
    quantity  = notional / entry_price
    return round(quantity, 4)


def place_limit_order(symbol: str, direction: str,
                      entry_price: float,
                      leverage: int = DEFAULT_LEVERAGE) -> dict:
    try:
        set_leverage(symbol, leverage)

        quantity = calculate_quantity(entry_price, TRADE_AMOUNT_USDT, leverage)
        side     = "buy" if direction == "LONG" else "sell"

        body = {
            "timestamp":  get_timestamp(),
            "pair":       symbol,
            "side":       side,
            "order_type": "limit_order",
            "price":      entry_price,
            "quantity":   quantity,
            "leverage":   leverage,
        }

        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(
            f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create",
            headers=headers,
            data=json_body
        )

        if resp.status_code == 200:
            order    = resp.json()
            order_id = order.get("id") or order.get("order_id")
            logger.info(f"Order placed: {symbol} {direction} qty:{quantity} @ {entry_price} id:{order_id}")
            return {
                "success":      True,
                "order_id":     order_id,
                "order_status": order.get("status", "open"),
                "quantity":     quantity,
                "leverage":     leverage,
                "trade_amount": TRADE_AMOUNT_USDT,
            }

        logger.error(f"Order failed for {symbol}: {resp.status_code} {resp.text}")
        return {
            "success":      False,
            "order_id":     None,
            "order_status": "failed",
            "error":        resp.text,
            "quantity":     quantity,
            "leverage":     leverage,
            "trade_amount": TRADE_AMOUNT_USDT,
        }

    except Exception as e:
        logger.error(f"Place order exception: {e}")
        return {"success": False, "order_id": None, "order_status": "error", "error": str(e)}


def get_order_status(order_id: str) -> dict:
    try:
        body = {
            "timestamp": get_timestamp(),
            "id":        order_id,
        }
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(
            f"{BASE_URL}/exchange/v1/derivatives/futures/orders/status",
            headers=headers,
            data=json_body
        )
        if resp.status_code == 200:
            order  = resp.json()
            status = order.get("status")
            logger.info(f"Order {order_id} status: {status}")
            return {"order_id": order_id, "status": status, "data": order}
        logger.error(f"Order status check failed: {resp.status_code} {resp.text}")
        return {"order_id": order_id, "status": "unknown"}
    except Exception as e:
        logger.error(f"Order status error: {e}")
        return {"order_id": order_id, "status": "error"}