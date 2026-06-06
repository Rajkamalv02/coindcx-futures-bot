import time
import requests
from api.auth import get_auth_headers, get_timestamp
from config.settings import CANDLE_INTERVAL, CANDLE_LIMIT, CONFIRM_INTERVAL
from utils.logger import logger

BASE_URL = "https://api.coindcx.com"

# ── Account ────────────────────────────────────────────
def get_user_info():
    body = {"timestamp": get_timestamp()}
    headers, json_body = get_auth_headers(body)
    resp = requests.post(f"{BASE_URL}/exchange/v1/users/info",
                         headers=headers, data=json_body)
    return resp.json()


# ── Active Futures Instruments ─────────────────────────
def get_active_instruments():
    resp = requests.get(
        f"{BASE_URL}/exchange/v1/derivatives/futures/data/active_instruments"
    )
    if resp.status_code == 200:
        return resp.json()
    logger.error(f"Failed to fetch instruments: {resp.status_code}")
    return []


# ── Candles (core) ─────────────────────────────────────
def _fetch_candles(symbol: str, interval: str, limit: int) -> list:
    to_ts = int(time.time())

    if interval == "1D":
        offset_seconds = 86400
    else:
        offset_seconds = int(interval) * 60

    from_ts = to_ts - (limit * offset_seconds)

    params = {
        "pair":       symbol,
        "from":       from_ts,
        "to":         to_ts,
        "resolution": interval,
        "pcode":      "f"
    }

    resp = requests.get(
        "https://public.coindcx.com/market_data/candlesticks",
        params=params
    )

    if resp.status_code == 200:
        data = resp.json()
        return data.get("data", [])

    logger.error(f"Failed to fetch candles for {symbol} [{interval}]: {resp.status_code} {resp.text}")
    return []


# ── Primary Timeframe Candles ──────────────────────────
def get_candles(symbol: str) -> list:
    return _fetch_candles(symbol, CANDLE_INTERVAL, CANDLE_LIMIT)


# ── Confirmation Timeframe Candles ─────────────────────
def get_confirm_candles(symbol: str) -> list:
    return _fetch_candles(symbol, CONFIRM_INTERVAL, CANDLE_LIMIT)


# ── Ticker ─────────────────────────────────────────────
def get_ticker(symbol: str) -> dict:
    resp = requests.get(
        f"{BASE_URL}/exchange/v1/derivatives/futures/data/ticker",
        params={"pair": symbol}
    )
    if resp.status_code == 200:
        data = resp.json()
        return data[0] if isinstance(data, list) else data
    logger.error(f"Failed to fetch ticker for {symbol}: {resp.status_code}")
    return {}


# ── Filtered Symbols ───────────────────────────────────
def get_filtered_symbols(min_price: float = 0.5, min_volume: float = 500000) -> list:
    instruments_resp = requests.get(
        f"{BASE_URL}/exchange/v1/derivatives/futures/data/active_instruments"
    )
    all_pairs = instruments_resp.json()

    ticker_resp = requests.get("https://api.coindcx.com/exchange/ticker")
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