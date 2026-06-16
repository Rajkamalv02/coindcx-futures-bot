import schedule
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from config.settings import (
    WATCHLIST, SCAN_INTERVAL_MINUTES, ENABLE_AUTO_TRADING,
    TRADE_THRESHOLD_INR, USDT_INR_RATE
)
from api.fetcher import get_filtered_symbols, get_candles, get_confirm_candles
from signals.indicators import build_dataframe, calculate_indicators, get_confirm_trend
from signals.scanner import detect_signal
from alerts.telegram import send_signal
from trading.order import place_limit_order, get_order_status
from trading.position import get_futures_balance
from database.mongo import save_order, get_db, get_open_orders, update_order_status
from utils.logger import logger, scanner_logger, trade_logger

# ── Deduplication cache ────────────────────────────────
_cache_lock = threading.Lock()
_sent_lock = threading.Lock()
# Stores "SYMBOL_DIRECTION" → timestamp of last signal
_signal_cache: dict = {}
SIGNAL_COOLDOWN_MINUTES = 60  # don't repeat same signal within 60 min


def _is_duplicate(symbol: str, direction: str) -> bool:
    key      = f"{symbol}_{direction}"
    now      = time.time()
    with _cache_lock:
        last_ts  = _signal_cache.get(key, 0)
        if now - last_ts < SIGNAL_COOLDOWN_MINUTES * 60:
            return True
        _signal_cache[key] = now
    return False

def check_order_statuses():
    """Check and update status of all open orders in MongoDB."""
    open_orders = get_open_orders()
    if not open_orders:
        return

    trade_logger.info(f"Checking status of {len(open_orders)} open orders")
    for order in open_orders:
        order_id = order.get("order_id")
        if not order_id:
            continue
        result = get_order_status(order_id)
        status = result.get("status")
        if status and status != order.get("order_status"):
            update_order_status(order_id, status)
            if status == "filled":
                trade_logger.info(f"Order FILLED: {order.get('symbol')} {order.get('direction')} @ {order.get('entry_usdt')}")



def get_symbols() -> list:
    if WATCHLIST:
        return WATCHLIST
    return get_filtered_symbols(min_price=0.5, min_volume=500000)


def process_symbol(symbol: str, sent_this_run: set) -> dict | None:
    """
    Scans a single symbol and returns signal data if found.
    Trading logic removed from here to allow ranking after full scan.
    """
    try:
        candles = get_candles(symbol)
        df      = build_dataframe(candles)
        df      = calculate_indicators(df)

        confirm_candles = get_confirm_candles(symbol)
        df_confirm      = build_dataframe(confirm_candles)
        confirm_trend   = get_confirm_trend(df_confirm)

        signal = detect_signal(df, symbol, confirm_trend)

        if signal:
            key = f"{symbol}_{signal['direction']}"

            # Block if already sent this run OR within cooldown
            with _sent_lock:
                if key in sent_this_run or _is_duplicate(symbol, signal['direction']):
                    scanner_logger.info(f"Duplicate skipped: {symbol} {signal['direction']}")
                    return None
                sent_this_run.add(key)

            # Signal found! Log to scanner log
            scanner_logger.info(f"🔍 Signal Detected: {symbol} {signal['direction']} (Score: {signal['score']}/5)")
            return signal

        else:
            scanner_logger.info(f"No signal: {symbol} (confirm: {confirm_trend})")
            return None

    except Exception as e:
        logger.error(f"Error processing {symbol}: {e}")
        return None


def execute_trades(found_signals: list):
    """
    Ranks signals and executes them based on available balance and threshold.
    In PAPER_TRADING mode, we use a mock balance to allow trade simulation
    even if real funds are zero or auto-trading is disabled.
    """
    from config.settings import PAPER_TRADING
    
    # Only skip if BOTH are false
    if not found_signals:
        return
    if not ENABLE_AUTO_TRADING and not PAPER_TRADING:
        return

    # 1. Ranking/Sorting
    ranked_signals = sorted(found_signals, key=lambda x: x.get('score', 0), reverse=True)
    
    # 2. Fetch Balance and calculate limit
    balance_usdt = get_futures_balance()
    balance_inr  = balance_usdt * USDT_INR_RATE
    
    # MOCK balance for Paper Trading so we can see the orders execute
    if PAPER_TRADING and balance_inr < TRADE_THRESHOLD_INR:
        trade_logger.info("🧪 Paper Trading: Using MOCK balance (₹10,000.0) for simulation.")
        balance_inr = 10000.0

    per_trade_usdt = round(TRADE_THRESHOLD_INR / USDT_INR_RATE, 2)
    max_trades = int(balance_inr // TRADE_THRESHOLD_INR)
    trade_logger.info(f"💹 Ranking Results: {len(ranked_signals)} signals found.")
    trade_logger.info(f"💰 Balance: ₹{balance_inr:.2f} | Allowance: ₹{TRADE_THRESHOLD_INR} (~{per_trade_usdt} USDT) | Max Trades: {max_trades}")
    
    # 3. Process top signals
    executed_count = 0
    for signal in ranked_signals:
        if executed_count >= max_trades:
            trade_logger.info(f"⏹️ Trade limit reached ({max_trades}). Skipping {signal['symbol']} (Score: {signal['score']})")
            continue
            
        symbol = signal['symbol']
        trade_logger.info(f"🚀 Executing Top Signal: {symbol} (Score: {signal['score']})")
        
        order_result = place_limit_order(
            symbol      = symbol,
            direction   = signal['direction'],
            entry_price = signal['entry'],
            tp_price    = signal.get('target'),
            sl_price    = signal.get('stop_loss'),
            amount_usdt = per_trade_usdt,
        )
        
        signal.update(order_result)
        send_signal(signal) # Send telegram alert with order info

        if order_result.get("success"):
            save_order(signal)
            trade_logger.info(f"✅ Order successful for {symbol}")
            executed_count += 1
        else:
            trade_logger.warning(f"❌ Order failed for {symbol}")


def run_scanner():
    logger.info("=" * 50)
    logger.info("Scanner started...")
    
    symbols       = get_symbols()
    sent_this_run = set()
    found_signals = []
    
    scanner_logger.info(f"Scanning {len(symbols)} symbols")

    # Use ThreadPoolExecutor for parallel scanning
    MAX_WORKERS = 10
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all and gather results
        futures = {executor.submit(process_symbol, s, sent_this_run): s for s in symbols}
        for future in futures:
            res = future.result()
            if res:
                found_signals.append(res)

    logger.info(f"Scanner completed: {len(symbols)} symbols scanned.")
    
    if found_signals:
        tickers = ", ".join([s['symbol'] for s in found_signals])
        logger.info(f"🎯 SIGNALS FOUND: {len(found_signals)} ({tickers})")
        
        # Execute ranked signals
        execute_trades(found_signals)
    else:
        logger.info("💤 No signals detected.")
    
    logger.info("=" * 50)



if __name__ == "__main__":
    logger.info("CoinDCX Futures EMA Bot started")
    get_db()
    run_scanner()
    # Add in __main__ block:
    schedule.every(5).minutes.do(check_order_statuses)

    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scanner)
    while True:
        schedule.run_pending()
        time.sleep(1)