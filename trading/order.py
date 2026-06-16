import os
import math
from utils.api_helper import APISession as requests
from dotenv import load_dotenv
from api.auth import get_futures_auth_headers, get_timestamp
from config.settings import DEFAULT_LEVERAGE, TRADE_AMOUNT_USDT, PAPER_TRADING
from utils.logger import trade_logger as logger
from trading.position import get_futures_balance
from api.fetcher import get_futures_specs

load_dotenv()

BASE_URL = "https://api.coindcx.com"

# Cache for instrument specs
_INSTRUMENT_SPECS = {}

def _load_specs():
    """Fetches and caches instrument specifications from Markets Details."""
    global _INSTRUMENT_SPECS
    if not _INSTRUMENT_SPECS:
        specs = get_futures_specs()
        for s in specs:
            # CoinDCX Market Details uses 'coindcx_name' (e.g. BTCUSDT) or 'symbol'
            # We normalize to match B-BTC_USDT format
            name = s.get("coindcx_name")
            if name:
                _INSTRUMENT_SPECS[name] = s
    return _INSTRUMENT_SPECS


def _clean_symbol(symbol: str) -> str:
    """Normalizes B-BTC_USDT -> BTCUSDT for Market Details matching."""
    return symbol.replace("B-", "").replace("_", "")


def _round_to_step(value: float, precision: int) -> float:
    """Rounds a value to a fixed number of decimals."""
    if value is None: return None
    return round(float(value), int(precision))


def calculate_quantity(symbol: str, entry_price: float, trade_amount_usdt: float, leverage: int = DEFAULT_LEVERAGE) -> float:
    """Calculates quantity rounded down to the allowed precision."""
    specs = _load_specs()
    clean_sym = _clean_symbol(symbol)
    pair_specs = specs.get(clean_sym)
    
    precision = 2 # Default fallback
    if pair_specs:
        # Market Details provides 'target_currency_precision'
        precision = pair_specs.get("target_currency_precision", 2)

    notional = trade_amount_usdt * leverage
    raw_qty  = notional / entry_price
    
    factor = 10**int(precision)
    quantity = math.floor(raw_qty * factor) / factor
    return float(quantity)


def place_limit_order(symbol: str, direction: str,
                      entry_price: float,
                      tp_price: float = None,
                      sl_price: float = None,
                      amount_usdt: float = TRADE_AMOUNT_USDT,
                      leverage: int = DEFAULT_LEVERAGE) -> dict:
    """
    Place a limit order with correct quantity and price precision.
    """
    specs = _load_specs()
    clean_sym = _clean_symbol(symbol)
    pair_specs = specs.get(clean_sym)
    
    # 1. Get Precisions
    price_prec = 2
    qty_prec   = 2
    if pair_specs:
        price_prec = pair_specs.get("base_currency_precision", 2)
        qty_prec   = pair_specs.get("target_currency_precision", 2)
    
    final_entry = _round_to_step(entry_price, price_prec)
    final_tp    = _round_to_step(tp_price, price_prec)
    final_sl    = _round_to_step(sl_price, price_prec)
    
    # 2. Calculate Quantity
    quantity = calculate_quantity(symbol, final_entry, amount_usdt, leverage)
    side     = "buy" if direction == "LONG" else "sell"
    
    if quantity <= 0:
        logger.warning(f"Quantity 0 calculated for {symbol}")
        return {"success": False, "error": "Zero quantity"}

    trade_body = {
        "timestamp":  get_timestamp(),
        "order": {
            "pair":       symbol,
            "side":       side,
            "order_type": "limit_order",
            "price":      final_entry,
            "total_quantity": quantity,
            "leverage":   leverage,
            "take_profit_price": final_tp,
            "stop_loss_price":   final_sl,
            "margin_currency_short_name": "INR",
        }
    }

    if PAPER_TRADING:
        import json as _json
        logger.info(f"📝 PAPER TRADING: Simulated order for {symbol} {direction} @ {final_entry}")
        logger.info(f"📤 MOCK REQUEST BODY: {_json.dumps(trade_body, indent=2)}")
        return {
            "success":      True,
            "order_id":     "paper_trading_id",
            "order_status": "filled",
            "quantity":     quantity,
            "leverage":     leverage,
            "trade_amount": amount_usdt,
            "paper":        True
        }

    try:
        balance = get_futures_balance()
        if balance < (amount_usdt - 0.1):
            logger.warning(f"❌ Insufficient Funds for {symbol}")
            return {"success": False, "error": "Insufficient funds"}

        # Leverage update (optional, usually set once)
        # Note: can be noisy with 404s, skipping for now to focus on order success

        headers, json_body = get_futures_auth_headers(trade_body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create",
                               headers=headers, data=json_body)

        if resp.status_code == 200:
            order_data = resp.json()
            # COINDCX RETURNS A LIST [ {order...} ]
            if isinstance(order_data, list) and len(order_data) > 0:
                order = order_data[0]
            else:
                order = order_data
            
            order_id = order.get("id") or order.get("order_id")
            logger.info(f"Order placed: {symbol} {direction} qty:{quantity} @ {final_entry} id:{order_id}")
            return {
                "success":      True,
                "order_id":     order_id,
                "order_status": order.get("status", "open"),
                "quantity":     quantity,
                "leverage":     leverage,
                "trade_amount": amount_usdt,
            }

        logger.error(f"Order failed for {symbol}: {resp.status_code} | Details: {resp.text}")
        return {"success": False, "error": resp.text}

    except Exception as e:
        logger.error(f"Place order exception for {symbol}: {e}")
        return {"success": False, "error": str(e)}


def get_order_status(order_id: str) -> dict:
    try:
        body = {"timestamp": get_timestamp(), "id": order_id}
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders/status",
                               headers=headers, data=json_body)
        if resp.status_code == 200:
            order  = resp.json()
            return {"order_id": order_id, "status": order.get("status"), "data": order}
        return {"order_id": order_id, "status": "unknown"}
    except Exception as e:
        logger.error(f"Order status error: {e}")
        return {"order_id": order_id, "status": "error"}