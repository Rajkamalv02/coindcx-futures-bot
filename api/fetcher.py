import time
from api.auth import get_auth_headers, get_timestamp
from utils.api_helper import APISession as requests
from config.settings import CANDLE_INTERVAL, CANDLE_LIMIT, CONFIRM_INTERVAL
from utils.logger import logger

BASE_URL = "https://api.coindcx.com"
DEFAULT_TIMEOUT = 10 # 10 seconds timeout for all requests

# ── Backtest Cache ─────────────────────────────────────
# Keeps historical candles for 1 hour to avoid redundant fetching
_HIST_CACHE = {} 
CACHE_TTL = 3600 

def _get_from_cache(key: str):
    if key in _HIST_CACHE:
        entry = _HIST_CACHE[key]
        if time.time() - entry['ts'] < CACHE_TTL:
            return entry['data']
        del _HIST_CACHE[key]
    return None

def _save_to_cache(key: str, data: list):
    _HIST_CACHE[key] = {'ts': time.time(), 'data': data}


# ── Account ────────────────────────────────────────────
def get_user_info():
    body = {"timestamp": get_timestamp()}
    headers, json_body = get_auth_headers(body)
    try:
        resp = requests.post(f"{BASE_URL}/exchange/v1/users/info",
                            headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)
        return resp.json()
    except Exception as e:
        logger.error(f"get_user_info error: {e}")
        return {}


# ── Active Futures Instruments ─────────────────────────
def get_active_instruments():
    try:
        resp = requests.get(
            f"{BASE_URL}/exchange/v1/derivatives/futures/data/active_instruments",
            timeout=DEFAULT_TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"Failed to fetch instruments: {resp.status_code}")
        return []
    except Exception as e:
        logger.error(f"get_active_instruments error: {e}")
        return []


def get_futures_specs():
    """Fetches detailed specifications for all instruments."""
    try:
        resp = requests.get("https://api.coindcx.com/exchange/v1/markets_details", timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"Failed to fetch futures specs: {resp.status_code}")
        return []
    except Exception as e:
        logger.error(f"get_futures_specs error: {e}")
        return []


def get_futures_instrument_details(pair: str):
    """
    Fetches futures-specific details for a pair (like quantity_increment).
    This is more accurate for B- and KC- pairs than markets_details.
    """
    url = f"https://api.coindcx.com/exchange/v1/derivatives/futures/data/instrument?pair={pair}"
    try:
        resp = requests.get(url, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("instrument") if isinstance(data, dict) else None
        return None
    except Exception as e:
        logger.error(f"Error fetching instrument details for {pair}: {e}")
        return None


# ── Candles (core) ─────────────────────────────────────
def _fetch_candles(symbol: str, interval: str, limit: int) -> list:
    to_ts = int(time.time())

    if interval == "1D":
        offset_seconds = 86400
    else:
        try:
            offset_seconds = int(interval) * 60
        except ValueError:
            offset_seconds = 3600 # Fallback 1H

    from_ts = to_ts - (limit * offset_seconds)

    params = {
        "pair":       symbol,
        "from":       from_ts,
        "to":         to_ts,
        "resolution": interval,
        "pcode":      "f"
    }

    try:
        resp = requests.get(
            "https://public.coindcx.com/market_data/candlesticks",
            params=params,
            timeout=DEFAULT_TIMEOUT
        )

        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])

        logger.error(f"Failed to fetch candles for {symbol} [{interval}]: {resp.status_code}")
        return []
    except Exception as e:
        logger.error(f"fetch_candles error for {symbol}: {e}")
        return []


# ── Primary Timeframe Candles ──────────────────────────
def get_candles(symbol: str) -> list:
    return _fetch_candles(symbol, CANDLE_INTERVAL, CANDLE_LIMIT)


# ── Confirmation Timeframe Candles ─────────────────────
def get_confirm_candles(symbol: str) -> list:
    return _fetch_candles(symbol, CONFIRM_INTERVAL, CANDLE_LIMIT)


# ── Ticker ─────────────────────────────────────────────
def get_ticker(symbol: str) -> dict:
    try:
        resp = requests.get(
            f"{BASE_URL}/exchange/v1/derivatives/futures/data/ticker",
            params={"pair": symbol},
            timeout=DEFAULT_TIMEOUT
        )
        if resp.status_code == 200:
            data = resp.json()
            return data[0] if isinstance(data, list) else data
        return {}
    except Exception as e:
        logger.error(f"get_ticker error for {symbol}: {e}")
        return {}


# ── Historical Candles for Backtest (with Caching) ────
def get_historical_candles(symbol: str, days: int) -> list:
    cache_key = f"{symbol}_{days}_{CANDLE_INTERVAL}"
    cached_data = _get_from_cache(cache_key)
    if cached_data:
        return cached_data

    if CANDLE_INTERVAL == "1D":
        limit = days
    else:
        try:
            limit = (days * 24 * 60) // int(CANDLE_INTERVAL)
        except ValueError:
            limit = days * 24

    limit = min(limit, 5000)
    
    logger.info(f"Fetching {limit} historical candles for {symbol} ({days} days)")
    data = _fetch_candles(symbol, CANDLE_INTERVAL, limit)
    
    if data:
        _save_to_cache(cache_key, data)
    return data


# ── Filtered Symbols ───────────────────────────────────
def get_filtered_symbols(min_price: float = 0.5, min_volume: float = 500000) -> list:
    try:
        instruments_resp = requests.get(
            f"{BASE_URL}/exchange/v1/derivatives/futures/data/active_instruments",
            timeout=DEFAULT_TIMEOUT
        )
        all_pairs = instruments_resp.json()

        ticker_resp = requests.get("https://api.coindcx.com/exchange/ticker", timeout=DEFAULT_TIMEOUT)
        tickers = ticker_resp.json()

        ticker_map = {}
        for t in tickers:
            ticker_map[t['market']] = t

        filtered = []
        for pair in all_pairs:
            try:
                symbol = pair.replace("B-", "").replace("_", "")
                ticker = ticker_map.get(symbol)
                if not ticker:
                    continue
                last_price  = float(ticker.get('last_price', 0))
                volume      = float(ticker.get('volume', 0))
                volume_usdt = volume * last_price
                if last_price >= min_price and volume_usdt >= min_volume:
                    filtered.append(pair)
            except Exception:
                continue

        logger.info(f"Filtered symbols: {len(filtered)} out of {len(all_pairs)} total")
        return filtered
    except Exception as e:
        logger.error(f"get_filtered_symbols error: {e}")
        return []