import os
import math
from utils.api_helper import APISession as requests
from dotenv import load_dotenv
from api.auth import get_futures_auth_headers, get_timestamp
from config.settings import DEFAULT_LEVERAGE, TRADE_AMOUNT_USDT, PAPER_TRADING
from utils.logger import trade_logger as logger
from trading.position import get_futures_balance
from api.fetcher import get_futures_specs, get_futures_instrument_details

load_dotenv()

BASE_URL = "https://api.coindcx.com"
DEFAULT_TIMEOUT = 10

# ── Metadata Cache ─────────────────────────────────────
_MARKETS_DETAILS_CACHE = {}
_FUTURES_SPECS_CACHE = {} # pair -> specs

def _get_specs(symbol: str):
    """
    Retrieves precision and step size for a symbol.
    Caches results to avoid redundant API calls.
    """
    global _MARKETS_DETAILS_CACHE, _FUTURES_SPECS_CACHE

    if symbol in _FUTURES_SPECS_CACHE:
        return _FUTURES_SPECS_CACHE[symbol]

    # 1. Load bulk metadata if not already loaded
    if not _MARKETS_DETAILS_CACHE:
        logger.info("📡 Loading bulk markets_details...")
        raw_specs = get_futures_specs()
        for s in raw_specs:
            name = s.get("coindcx_name")
            if name:
                _MARKETS_DETAILS_CACHE[name] = s

    # 2. Try fetching futures-specific instrument details (most accurate for B- pairs)
    # We only do this on-demand when a signal is found to keep startup fast.
    f_specs = get_futures_instrument_details(symbol)
    
    if f_specs:
        # Standardize field names
        quantity_increment = float(f_specs.get("quantity_increment", 0.0001))
        price_increment    = float(f_specs.get("price_increment", 0.0001))
        
        specs = {
            "step":          quantity_increment,
            "price_step":    price_increment,
            "qty_prec":      len(str(quantity_increment).split(".")[-1]) if "." in str(quantity_increment) else 0,
            "price_prec":    len(str(price_increment).split(".")[-1]) if "." in str(price_increment) else 0,
            "min_quantity":  float(f_specs.get("min_quantity") or f_specs.get("min_trade_size") or 0),
            "min_notional":  float(f_specs.get("min_notional", 0)),
        }
        _FUTURES_SPECS_CACHE[symbol] = specs
        return specs

    # 3. Fallback to markets_details
    clean_sym = symbol.replace("B-", "").replace("_", "")
    m_specs = _MARKETS_DETAILS_CACHE.get(clean_sym)
    if m_specs:
        q_prec = m_specs.get("target_currency_precision", 2)
        p_prec = m_specs.get("base_currency_precision", 2)
        specs = {
            "step":          1 / (10**q_prec),
            "price_step":    1 / (10**p_prec),
            "qty_prec":      q_prec,
            "price_prec":    p_prec,
            "min_quantity":  0.0, # Not reliably in markets_details
            "min_notional":  0.0,
        }
        _FUTURES_SPECS_CACHE[symbol] = specs
        return specs

    return None


def calculate_quantity(symbol: str, entry_price: float, trade_amount_usdt: float, leverage: int = DEFAULT_LEVERAGE) -> float:
    """Calculates quantity rounded down to the allowed step size."""
    specs = _get_specs(symbol)
    
    if not specs:
        # Blind fallback
        raw_qty = (trade_amount_usdt * leverage) / entry_price
        return float(round(math.floor(raw_qty * 100) / 100, 8))

    notional = trade_amount_usdt * leverage
    raw_qty  = notional / entry_price
    
    step = specs['step']
    
    # Round down to nearest multiple of step
    # Epsilon (1e-9) prevents float precision errors (e.g., 0.2999999 becoming 0.2)
    quantity = math.floor((raw_qty + 1e-9) / step) * step
    
    # Final safety check for min_quantity
    if quantity < specs['min_quantity']:
        logger.warning(f"⚠️ {symbol} quantity {quantity} below minimum {specs['min_quantity']}")
        return 0.0

    return float(round(quantity, 8))


def place_limit_order(symbol: str, direction: str,
                      entry_price: float,
                      tp_price: float | None = None,
                      sl_price: float | None = None,
                      amount_usdt: float = TRADE_AMOUNT_USDT,
                      leverage: int = DEFAULT_LEVERAGE) -> dict:
    
    specs = _get_specs(symbol)
    
    # 1. Price Rounding
    p_prec = specs['price_prec'] if specs else 2
    
    final_entry = round(float(entry_price), p_prec)
    final_tp    = round(float(tp_price), p_prec) if tp_price else None
    final_sl    = round(float(sl_price), p_prec) if sl_price else None

    # 2. Quantity calculation
    quantity = calculate_quantity(symbol, final_entry, amount_usdt, leverage)
    
    if quantity <= 0:
        return {"success": False, "error": "Zero quantity after precision rounding"}

    side = "buy" if direction == "LONG" else "sell"

    order_params = {
        "pair":       symbol,
        "side":       side,
        "order_type": "limit_order",
        "price":      final_entry,
        "total_quantity": quantity,
        "leverage":   leverage,
        "margin_currency_short_name": "INR",
    }
    
    if final_tp: order_params["take_profit_price"] = final_tp
    if final_sl: order_params["stop_loss_price"] = final_sl

    trade_body = {
        "timestamp":  get_timestamp(),
        "order": order_params
    }

    if PAPER_TRADING:
        return {
            "success":      True,
            "order_id":     "paper_trading_id",
            "quantity":     quantity,
            "paper":        True
        }

    try:
        # Check balance before committing
        balance = get_futures_balance()
        if balance < (amount_usdt - 0.1):
            return {"success": False, "error": "Insufficient wallet balance"}

        headers, json_body = get_futures_auth_headers(trade_body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create",
                               headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 200:
            res_data = resp.json()
            # Handle list return vs dict return
            order_info = res_data[0] if isinstance(res_data, list) else res_data
            if order_info.get("status") in ("placed", "open", "filled"):
                return {
                    "success":      True,
                    "order_id":     order_info.get("id") or order_info.get("order_id"),
                    "order_status": order_info.get("status"),
                    "quantity":     quantity,
                    "leverage":     leverage,
                }
            return {"success": False, "error": order_info.get("message", "API accepted but no order ID returned")}
        
        err_msg = resp.text
        try:
            err_json = resp.json()
            if isinstance(err_json, list): err_json = err_json[0]
            err_msg = err_json.get("message") or err_json.get("error") or err_msg
        except: pass
        
        return {"success": False, "error": f"API Error {resp.status_code}: {err_msg}"}
        
    except Exception as e:
        logger.error(f"place_limit_order critical error for {symbol}: {e}")
        return {"success": False, "error": str(e)}


def get_all_open_orders() -> list:
    """
    Fetch all open orders for both BUY/SELL and USDT/INR markets.
    Official Docs specify:
    - page, size, status, side are MANDATORY strings.
    - margin_currency_short_name is an OPTIONAL array (defaults to ["USDT"]).
    """
    try:
        combined_orders = []
        # 'side' is mandatory ("buy" or "sell")
        for side in ["buy", "sell"]:
            body = {
                "timestamp": get_timestamp(),
                "status": "open",
                "side": side,
                "page": "1",
                "size": "50",
                "margin_currency_short_name": ["USDT", "INR"]
            }
            headers, json_body = get_futures_auth_headers(body)
            resp = requests.post(
                f"{BASE_URL}/exchange/v1/derivatives/futures/orders", 
                headers=headers, data=json_body, timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                logger.debug(f"RAW ORDERS RESPONSE ({side}): {data}")
                orders = data.get("orders", []) if isinstance(data, dict) else data
                if isinstance(orders, list):
                    combined_orders.extend(orders)
            else:
                logger.error(f"Failed to fetch {side} orders: {resp.status_code} | {resp.text}")
        
        return combined_orders
    except Exception as e:
        logger.error(f"get_all_open_orders error: {e}")
        return []


def get_order_status(order_id: str) -> dict:
    """Uses the List Orders endpoint to find a specific order by ID."""
    try:
        body = {
            "timestamp": get_timestamp(),
            "status": "open", # First check open orders
            "page": 1,
            "size": 20
        }
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders", 
                               headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)
        
        if resp.status_code == 200:
            orders = resp.json().get("orders", [])
            for o in orders:
                if o.get("id") == order_id:
                    return {"status": o.get("status"), "data": o}
            
            # If not in open, check filled/closed
            body["status"] = "filled"
            headers, json_body = get_futures_auth_headers(body)
            resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders", 
                                   headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                orders = resp.json().get("orders", [])
                for o in orders:
                    if o.get("id") == order_id:
                        return {"status": o.get("status"), "data": o}
        
        return {"status": "unknown", "message": "Order not found in recent lists"}
    except Exception as e:
        logger.error(f"get_order_status error for {order_id}: {e}")
        return {"status": "error", "error": str(e)}


def get_trade_details(symbol: str, order_id: str) -> dict:
    """Fetches specific execution details for an order."""
    try:
        body = {"timestamp": get_timestamp(), "order_id": order_id}
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders/trades/details",
                               headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            t = data[0] if isinstance(data, list) else data
            return {
                "success":    True,
                "fill_price": float(t.get("price", 0)),
                "fees":       float(t.get("fee_amount", 0)),
                "raw":        t
            }
        return {"success": False}
    except Exception as e:
        logger.error(f"get_trade_details error: {e}")
        return {"success": False}


def get_symbol_trades(symbol: str, limit: int = 5) -> list:
    """Fetches recent trade history for a specific symbol."""
    try:
        body = {"timestamp": get_timestamp(), "pair": symbol, "page": 1, "size": limit}
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders/trades",
                               headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception as e:
        logger.error(f"get_symbol_trades error: {e}")
        return []

def cancel_order(order_id: str) -> bool:
    """Cancels an open order."""
    try:
        body = {"timestamp": get_timestamp(), "id": order_id}
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders/cancel",
                               headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"cancel_order error for {order_id}: {e}")
        return False

def place_sl_order(symbol: str, pos_side: str, price: float, quantity: float):
    """Places a Stop Loss order for an existing position."""
    # Use local function directly
    specs = _get_specs(symbol)
    p_prec = specs['price_prec'] if specs else 2
    final_price = round(float(price), p_prec)
    
    # SL side is opposite of position side
    side = "sell" if pos_side == "LONG" else "buy"
    
    trade_body = {
        "timestamp": get_timestamp(),
        "order": {
            "pair": symbol,
            "side": side,
            "order_type": "stop_limit_order", # Or "stop_market_order" if supported
            "stop_price": final_price,
            "price": final_price,
            "total_quantity": quantity,
            "leverage": 1, # leverage doesn't matter for closing orders usually but required
            "margin_currency_short_name": "INR"
        }
    }
    try:
        headers, json_body = get_futures_auth_headers(trade_body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create",
                               headers=headers, data=json_body, timeout=DEFAULT_TIMEOUT)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"place_sl_order error for {symbol}: {e}")
        return False