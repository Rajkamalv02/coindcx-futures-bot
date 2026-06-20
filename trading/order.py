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

# Cache for instrument specs
_INSTRUMENT_SPECS = {}
_FUTURES_INSTRUMENT_CACHE = {}

def _load_specs():
    """Fetches and caches instrument specifications from Markets Details."""
    global _INSTRUMENT_SPECS
    if not _INSTRUMENT_SPECS:
        specs = get_futures_specs()
        for s in specs:
            name = s.get("coindcx_name")
            if name:
                _INSTRUMENT_SPECS[name] = s
    return _INSTRUMENT_SPECS

def _get_accurate_specs(symbol: str):
    """
    Returns the most accurate specs for a symbol, prioritizing the 
    futures-specific details from the exchange.
    """
    global _FUTURES_INSTRUMENT_CACHE
    
    # 1. Check if we already have it in futures cache
    if symbol in _FUTURES_INSTRUMENT_CACHE:
        return _FUTURES_INSTRUMENT_CACHE[symbol]
    
    # 2. Try fetching from futures instrument endpoint
    f_specs = get_futures_instrument_details(symbol)
    if f_specs:
        # Standardize field names to be consistent with markets_details
        processed = {
            "step": f_specs.get("quantity_increment"),
            "min_quantity": f_specs.get("min_quantity") or f_specs.get("min_trade_size"),
            "min_notional": f_specs.get("min_notional"),
            "target_currency_precision": len(str(f_specs.get("quantity_increment")).split(".")[-1]) if "." in str(f_specs.get("quantity_increment")) else 0,
            "base_currency_precision": len(str(f_specs.get("price_increment")).split(".")[-1]) if "." in str(f_specs.get("price_increment")) else 0,
            "lot_size": f_specs.get("quantity_increment"),
            "is_futures": True,
            "raw": f_specs
        }
        _FUTURES_INSTRUMENT_CACHE[symbol] = processed
        return processed
    
    # 3. Fallback to markets_details
    specs = _load_specs()
    clean_sym = symbol.replace("B-", "").replace("_", "")
    return specs.get(clean_sym)


def _clean_symbol(symbol: str) -> str:
    """Normalizes B-BTC_USDT -> BTCUSDT for Market Details matching."""
    return symbol.replace("B-", "").replace("_", "")


def _round_to_step(value: float | None, precision: int) -> float | None:
    """Rounds a value to a fixed number of decimals."""
    if value is None: return None
    return round(float(value), precision)


def calculate_quantity(symbol: str, entry_price: float, trade_amount_usdt: float, leverage: int = DEFAULT_LEVERAGE) -> float:
    """Calculates quantity rounded down to the allowed precision."""
    pair_specs = _get_accurate_specs(symbol)
    
    precision = 2 # Default fallback
    if pair_specs:
        precision = pair_specs.get("target_currency_precision", 2)

    notional = trade_amount_usdt * leverage
    raw_qty  = notional / entry_price
    
    # 3. Round down to nearest step or precision
    step = 0.0
    if pair_specs:
        # Check various common field names for step size
        step = float(
            pair_specs.get("step") or 
            pair_specs.get("min_quantity_step") or 
            pair_specs.get("lot_size") or 
            0
        )
        
        # If still no step, derive it from target_currency_precision
        if step == 0 and precision >= 0:
            step = 1 / (10**int(precision))

    # DEBUG: See what the bot is using
    logger.debug(f"Quantity Specs for {symbol}: Precision={precision}, Step={step}, RawQty={raw_qty}")

    if step > 0:
        # Round down to nearest multiple of step
        # Using a small epsilon to avoid floating point issues (e.g. 0.2999999999)
        quantity = math.floor((raw_qty + 1e-9) / step) * step
    else:
        # Final fallback
        factor = 10**int(precision)
        quantity = math.floor(raw_qty * factor) / factor
        
    # FINAL SAFETY: If the API says "should be divisible by 0.1", 
    # we ensure our final quantity is aligned to at least 1 decimal if step is missing or too small
    if step < 0.1 and "divisible by 0.1" in str(pair_specs): # Not likely to be in specs but as a placeholder
        quantity = math.floor(quantity * 10) / 10

    return float(round(quantity, 8))


def place_limit_order(symbol: str, direction: str,
                      entry_price: float,
                      tp_price: float | None = None,
                      sl_price: float | None = None,
                      amount_usdt: float = TRADE_AMOUNT_USDT,
                      leverage: int = DEFAULT_LEVERAGE) -> dict:
    """
    Place a limit order with correct quantity and price precision.
    """
    pair_specs = _get_accurate_specs(symbol)
    
    # 1. Get Precisions
    price_prec = 2
    qty_prec   = 2
    if pair_specs:
        price_prec = pair_specs.get("base_currency_precision", 2)
        qty_prec   = pair_specs.get("target_currency_precision", 2)
    
    final_entry = _round_to_step(entry_price, price_prec)
    final_tp    = _round_to_step(tp_price, price_prec)
    final_sl    = _round_to_step(sl_price, price_prec)
    
    if final_entry is None:
        return {"success": False, "error": "Invalid entry price"}

    # 2. Calculate Quantity
    quantity = calculate_quantity(symbol, final_entry, amount_usdt, leverage)
    side     = "buy" if direction == "LONG" else "sell"
    
    if quantity <= 0:
        logger.warning(f"Quantity 0 calculated for {symbol}")
        return {"success": False, "error": "Zero quantity"}

    order_params = {
        "pair":       symbol,
        "side":       side,
        "order_type": "limit_order",
        "price":      final_entry,
        "total_quantity": quantity,
        "leverage":   leverage,
        "margin_currency_short_name": "INR",
    }
    
    if final_tp is not None:
        order_params["take_profit_price"] = final_tp
    if final_sl is not None:
        order_params["stop_loss_price"] = final_sl

    trade_body = {
        "timestamp":  get_timestamp(),
        "order": order_params
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


def get_symbol_trades(symbol: str, days_back: int = 1) -> list:
    """
    Fetch all recent trades for a symbol to find exit events.
    """
    try:
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end_date   = datetime.now().strftime("%Y-%m-%d")
        
        body = {
            "timestamp": get_timestamp(),
            "pair":      symbol,
            "from_date": start_date,
            "to_date":   end_date
        }
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/trades",
                               headers=headers, data=json_body)
        
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception as e:
        logger.error(f"Error fetching symbol trades for {symbol}: {e}")
        return []


def get_order_status(order_id: str) -> dict:
    """
    Futures tracking: We must use the List Orders endpoint and filter by ID 
    because there's no reliable single-status endpoint for futures.
    """
    try:
        path = "/exchange/v1/derivatives/futures/orders"
        # We check both open and filled/cancelled to be sure
        statuses = ["open", "filled", "cancelled", "rejected"]
        
        for status_to_check in statuses:
            body = {
                "timestamp": get_timestamp(),
                "status": status_to_check,
                "page": 1,
                "size": 50,
                "margin_currency_short_name": ["INR", "USDT"]
            }
            headers, json_body = get_futures_auth_headers(body)
            resp = requests.post(f"{BASE_URL}{path}", headers=headers, data=json_body)
            
            if resp.status_code == 200:
                data = resp.json()
                orders = data.get("orders", []) if isinstance(data, dict) else data
                
                # Search for our order ID in the list
                for o in orders:
                    this_id = o.get("id") or o.get("order_id")
                    if str(this_id) == str(order_id):
                        return {"order_id": order_id, "status": o.get("status"), "data": o}
            else:
                logger.debug(f"List {status_to_check} failed: {resp.status_code}")

        return {"order_id": order_id, "status": "not_found"}
    except Exception as e:
        logger.error(f"Order status error: {e}")
        return {"order_id": order_id, "status": "error"}


def get_trade_details(symbol: str, order_id: str) -> dict:
    """
    Fetch execution details (fill price, fees) for a specific order.
    Uses POST /exchange/v1/derivatives/futures/trades
    """
    try:
        body = {
            "timestamp": get_timestamp(),
            "pair":      symbol,
            "order_id":  order_id
        }
        headers, json_body = get_futures_auth_headers(body)
        resp = requests.post(f"{BASE_URL}/exchange/v1/derivatives/futures/trades",
                               headers=headers, data=json_body)
        
        if resp.status_code == 200:
            trades = resp.json()
            if isinstance(trades, list) and len(trades) > 0:
                total_fees = sum(float(t.get("fee_amount", 0)) for t in trades)
                avg_price = trades[0].get("price")
                return {
                    "success":    True,
                    "fill_price": float(avg_price),
                    "fees":       total_fees,
                    "symbol":     trades[0].get("pair")
                }
        
        return {"success": False, "error": f"API Error: {resp.status_code}"}
    except Exception as e:
        logger.error(f"Get trade details error for {order_id}: {e}")
        return {"success": False, "error": str(e)}