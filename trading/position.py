from utils.api_helper import APISession as requests
from api.auth import get_auth_headers, get_futures_auth_headers, get_timestamp
from utils.logger import logger

BASE_URL = "https://api.coindcx.com"


# def get_open_positions() -> list:
#     """
#     Fetch all open futures positions.
#     """
#     try:
#         body = {"timestamp": get_timestamp()}
#         headers, json_body = get_futures_auth_headers(body)
#         resp = requests.post(
#             f"{BASE_URL}/exchange/v1/derivatives/futures/positions",
#             headers=headers,
#             data=json_body
#         )
#         if resp.status_code == 200:
#             data = resp.json()
#             # Log raw data for debugging symbol matching
#             logger.info(f"DEBUG: Raw positions from API: {data}")
#             return data
#         logger.error(f"Failed to fetch positions: {resp.status_code} {resp.text}")
#         return []
#     except Exception as e:
#         logger.error(f"Get positions error: {e}")
#         return []

def get_open_positions() -> list | None:
    """Returns None on failure so callers can tell that apart from a genuinely empty list."""
    try:
        body = {"timestamp": get_timestamp()}
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(
            f"{BASE_URL}/exchange/v1/derivatives/futures/positions",
            headers=headers, data=json_body
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"DEBUG: Raw positions from API: {data}")
            return data
        logger.error(f"Failed to fetch positions: {resp.status_code} {resp.text}")
        return None
    except Exception as e:
        logger.error(f"Get positions error: {e}")
        return None

        
def get_futures_balance() -> float:
    """
    Fetch available balance in futures wallet.
    Uses the correct endpoint: GET /exchange/v1/derivatives/futures/wallets
    Handles both USDT and INR futures wallets.
    INR balance is converted to USDT equivalent using the configured rate.
    """
    import requests as _requests
    import json as _json
    from utils.logger import api_logger
    from config.settings import USDT_INR_RATE

    api_logger.info(">>> Fetching Futures Wallet Balance...")
    try:
        body = {"timestamp": get_timestamp()}
        headers, json_body = get_futures_auth_headers(body)

        # Correct endpoint — uses GET, not POST
        resp = _requests.get(
            f"{BASE_URL}/exchange/v1/derivatives/futures/wallets",
            headers=headers,
            data=json_body
        )
        api_logger.info(f"Wallet balance status: {resp.status_code}")

        if resp.status_code == 200:
            wallets = resp.json()  # returns a list of wallet objects
            # Log full response so we can see what currencies are available
            api_logger.info(f"Wallets response: {_json.dumps(wallets, indent=2)}")

            # Try USDT wallet first
            for wallet in wallets:
                name = wallet.get("currency_short_name", "").upper()
                if name == "USDT":
                    bal = float(wallet.get("balance", 0))
                    api_logger.info(f"USDT Futures Wallet Balance: {bal}")
                    return bal

            # Fallback: INR wallet → convert to USDT equivalent
            for wallet in wallets:
                name = wallet.get("currency_short_name", "").upper()
                if name == "INR":
                    inr_bal = float(wallet.get("balance", 0))
                    usdt_equiv = round(inr_bal / USDT_INR_RATE, 4)
                    api_logger.info(
                        f"INR Futures Wallet Balance: {inr_bal} INR "
                        f"= {usdt_equiv} USDT (rate: {USDT_INR_RATE})"
                    )
                    return usdt_equiv

            # Last resort: log available wallet names for debugging
            names = [w.get("currency_short_name", "?") for w in wallets]
            api_logger.warning(
                f"No USDT/INR wallet found. Available wallets: {names}"
            )
            return 0.0

        api_logger.error(f"Failed to fetch wallets: {resp.status_code} {resp.text}")
        return 0.0
    except Exception as e:
        logger.error(f"Get futures balance error: {e}")
        return 0.0