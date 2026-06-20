from utils.api_helper import APISession as requests
from api.auth import get_auth_headers, get_futures_auth_headers, get_timestamp
from utils.logger import logger

BASE_URL = "https://api.coindcx.com"


def get_open_positions() -> list | None:
    """Returns None on failure so callers can tell that apart from a genuinely empty list."""
    try:
        # According to official API docs:
        # page, size are MANDATORY strings.
        # margin_currency_short_name is an OPTIONAL array of strings.
        body = {
            "timestamp": get_timestamp(),
            "page": "1",
            "size": "50",
            "margin_currency_short_name": ["USDT", "INR"]
        }
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(
            f"{BASE_URL}/exchange/v1/derivatives/futures/positions",
            headers=headers, data=json_body, timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            logger.debug(f"RAW POSITIONS RESPONSE: {data}")
            
            # Filter out "ghost" positions with 0.0 balance
            # CoinDCX API returns positions for all pairs ever touched; we want active only.
            active_only = [
                p for p in data 
                if abs(float(p.get("active_pos", 0) or 0)) > 1e-8
            ]
            return active_only
        else:
            # Fallback: some older API keys might not like the array or multiple currencies
            logger.warning(f"Combined positions fetch failed ({resp.status_code}). Trying individual calls...")
            combined = []
            for curr in ["USDT", "INR"]:
                body["margin_currency_short_name"] = [curr]
                headers, json_body = get_futures_auth_headers(body)
                r = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/positions",
                                   headers=headers, data=json_body, timeout=10)
                if r.status_code == 200:
                    combined.extend(r.json())
            
            if combined:
                return [p for p in combined if abs(float(p.get("active_pos", 0) or 0)) > 1e-8]
                
            logger.error(f"Failed to fetch positions: {resp.status_code} | {resp.text}")
            return None if resp.status_code != 200 else []

    except Exception as e:
        logger.error(f"get_open_positions error: {e}")
        return None

        
def get_futures_balance() -> float:
    """
    Fetch available balance in futures wallet.
    Uses the correct endpoint: GET /exchange/v1/derivatives/futures/wallets
    Handles both USDT and INR futures wallets.
    INR balance is converted to USDT equivalent using the configured rate.
    """
    import json as _json
    from utils.logger import api_logger
    from config.settings import USDT_INR_RATE
    from utils.api_helper import APISession as api_requests

    api_logger.info(">>> Fetching Futures Wallet Balance...")
    try:
        body = {"timestamp": get_timestamp()}
        headers, json_body = get_futures_auth_headers(body)

        # Correct endpoint — uses GET, not POST
        resp = api_requests.get(
            f"{BASE_URL}/exchange/v1/derivatives/futures/wallets",
            headers=headers,
            data=json_body
        )

        if resp.status_code == 200:
            wallets = resp.json()
            # Try USDT wallet first
            for wallet in wallets:
                name = wallet.get("currency_short_name", "").upper()
                if name == "USDT":
                    return float(wallet.get("balance", 0))

            # Fallback: INR wallet
            for wallet in wallets:
                name = wallet.get("currency_short_name", "").upper()
                if name == "INR":
                    inr_bal = float(wallet.get("balance", 0))
                    return round(inr_bal / USDT_INR_RATE, 4)

            return 0.0

        api_logger.error(f"Failed to fetch wallets: {resp.status_code} {resp.text}")
        return 0.0
    except Exception as e:
        logger.error(f"Get futures balance error: {e}")
        return 0.0