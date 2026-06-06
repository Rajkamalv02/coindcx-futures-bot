import schedule
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from config.settings import WATCHLIST, SCAN_INTERVAL_MINUTES, ENABLE_AUTO_TRADING
from api.fetcher import get_filtered_symbols, get_candles, get_confirm_candles
from signals.indicators import build_dataframe, calculate_indicators, get_confirm_trend
from signals.scanner import detect_signal
from alerts.telegram import send_signal
from trading.order import place_limit_order, get_order_status
from database.mongo import save_order, get_db, get_open_orders, update_order_status
from utils.logger import logger

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

    logger.info(f"Checking status of {len(open_orders)} open orders")
    for order in open_orders:
        order_id = order.get("order_id")
        if not order_id:
            continue
        result = get_order_status(order_id)
        status = result.get("status")
        if status and status != order.get("order_status"):
            update_order_status(order_id, status)
            if status == "filled":
                logger.info(f"Order FILLED: {order.get('symbol')} {order.get('direction')} @ {order.get('entry_usdt')}")



def get_symbols() -> list:
    if WATCHLIST:
        return WATCHLIST
    return get_filtered_symbols(min_price=0.5, min_volume=500000)


def process_symbol(symbol: str, sent_this_run: set):
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
                    logger.info(f"Duplicate skipped: {symbol} {signal['direction']}")
                    return
                sent_this_run.add(key)

            if ENABLE_AUTO_TRADING:
                order_result = place_limit_order(
                    symbol      = symbol,
                    direction   = signal['direction'],
                    entry_price = signal['entry'],
                )
                signal.update(order_result)

                if order_result.get("success"):
                    save_order(signal)
                else:
                    logger.warning(f"Order failed for {symbol} — not saved to MongoDB")

            send_signal(signal)

        else:
            logger.info(f"No signal: {symbol} (confirm: {confirm_trend})")

    except Exception as e:
        logger.error(f"Error processing {symbol}: {e}")


def run_scanner():
    logger.info("=" * 50)
    logger.info("Scanner started...")

    symbols      = get_symbols()
    sent_this_run = set()          # ← track within single scan run
    logger.info(f"Scanning {len(symbols)} symbols")

    # Use ThreadPoolExecutor for parallel scanning
    MAX_WORKERS = 10
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for symbol in symbols:
            executor.submit(process_symbol, symbol, sent_this_run)

    logger.info("Scanner completed.")
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