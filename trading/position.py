import requests
from api.auth import get_auth_headers, get_timestamp
from utils.logger import logger

BASE_URL = "https://api.coindcx.com"


def get_open_positions() -> list:
    """
    Fetch all open futures positions.
    """
    try:
        body = {"timestamp": get_timestamp()}
        headers, json_body = get_auth_headers(body)
        resp = requests.post(
            f"{BASE_URL}/exchange/v1/derivatives/futures/positions",
            headers=headers,
            data=json_body
        )
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"Failed to fetch positions: {resp.status_code} {resp.text}")
        return []
    except Exception as e:
        logger.error(f"Get positions error: {e}")
        return []


def get_futures_balance() -> float:
    """
    Fetch available USDT balance in futures wallet.
    """
    try:
        body = {"timestamp": get_timestamp()}
        headers, json_body = get_auth_headers(body)
        resp = requests.post(
            f"{BASE_URL}/exchange/v1/users/balances",
            headers=headers,
            data=json_body
        )
        if resp.status_code == 200:
            balances = resp.json()
            for b in balances:
                if b.get("currency") == "USDT":
                    return float(b.get("balance", 0))
        return 0.0
    except Exception as e:
        logger.error(f"Get balance error: {e}")
        return 0.0