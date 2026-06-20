import schedule
import time
import threading
import sys
import signal
from concurrent.futures import ThreadPoolExecutor
from config.settings import (
    WATCHLIST, SCAN_INTERVAL_MINUTES, ENABLE_AUTO_TRADING,
    TRADE_THRESHOLD_INR, USDT_INR_RATE, MIN_SCORE,
    BACKTEST_DAYS, BACKTEST_MIN_TRADES
)
from api.fetcher import get_filtered_symbols, get_candles, get_confirm_candles, get_historical_candles
from signals.indicators import build_dataframe, calculate_indicators, get_confirm_trend
from signals.scanner import detect_signal, run_quick_backtest
from trading.order import (
    place_limit_order, get_order_status, 
    get_symbol_trades, get_all_open_orders
)
from trading.position import get_futures_balance, get_open_positions
from utils.logger import logger, scanner_logger, trade_logger

# ── Global State ───────────────────────────────────────
_cache_lock = threading.Lock()
# Stores "SYMBOL_DIRECTION" → timestamp of last signal
_signal_cache: dict = {}
SIGNAL_COOLDOWN_MINUTES = 240  # 4 hours

def _norm_sym(symbol: str) -> str:
    if not symbol: return ""
    return symbol.replace("B-", "").replace("_", "").replace("-", "").upper()

def _is_duplicate(symbol: str, direction: str, live_positions: list = None, open_orders: list = None) -> bool:
    """
    Check if a signal is duplicate based on memory cache and live exchange state.
    """
    key = f"{symbol}_{direction}"
    now = time.time()

    # 1. Local Cache Check
    with _cache_lock:
        last_ts = _signal_cache.get(key, 0)
        if now - last_ts < SIGNAL_COOLDOWN_MINUTES * 60:
            return True

    # 2. Live Positions Check
    if live_positions is None:
        live_positions = get_open_positions() or []
    
    norm_target = _norm_sym(symbol)
    for pos in live_positions:
        raw = pos.get("pair") or pos.get("symbol") or ""
        size = abs(float(pos.get("active_pos", 0) or 0))
        if _norm_sym(raw) == norm_target and size > 0:
            return True

    # 3. Open Orders Check
    if open_orders is None:
        open_orders = get_all_open_orders()
    
    for order in open_orders:
        if _norm_sym(order.get("pair", "")) == norm_target:
            return True

    return False


def _mark_signal_sent(symbol: str, direction: str):
    with _cache_lock:
        _signal_cache[f"{symbol}_{direction}"] = time.time()


def _clean_signal_cache():
    now = time.time()
    with _cache_lock:
        to_delete = [
            k for k, ts in _signal_cache.items() 
            if now - ts > SIGNAL_COOLDOWN_MINUTES * 60
        ]
        for k in to_delete:
            del _signal_cache[k]


def handle_exit(sig, frame):
    logger.info("🛑 Shutting down bot gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


def check_order_statuses():
    """
    Simple poller to log current exchange state.
    No local tracking or PnL calculation as requested.
    """
    trade_logger.info("=== check_order_statuses() START ===")

    live_positions = get_open_positions()
    if live_positions is None:
        trade_logger.warning("⚠️ Positions fetch failed.")
    else:
        active_count = 0
        for pos in live_positions:
            raw = pos.get("pair") or pos.get("symbol") or ""
            size = abs(float(pos.get("active_pos", 0) or 0))
            if raw and size > 0:
                trade_logger.info(f"📍 Active Position: {raw} | Qty: {size} | Entry: {pos.get('entry_price')}")
                active_count += 1
        trade_logger.info(f"Total Active Positions: {active_count}")

    open_orders = get_all_open_orders()
    if open_orders:
        trade_logger.info(f"📝 Open Orders on Exchange: {len(open_orders)}")
        for o in open_orders:
            trade_logger.info(f"  - {o.get('pair')} | {o.get('side')} | Qty: {o.get('total_quantity')} | Prc: {o.get('price')}")
    else:
        trade_logger.info("📝 No open orders on exchange.")

    trade_logger.info("=== check_order_statuses() END ===")


def get_symbols() -> list:
    if WATCHLIST: return WATCHLIST
    return get_filtered_symbols(min_price=0.5, min_volume=500000)


def process_symbol(symbol: str, sent_this_run: set) -> dict | None:
    try:
        candles = get_candles(symbol)
        df      = build_dataframe(candles)
        df      = calculate_indicators(df, symbol=symbol)
        confirm_candles = get_confirm_candles(symbol)
        df_confirm      = build_dataframe(confirm_candles)
        confirm_trend   = get_confirm_trend(df_confirm)

        signal = detect_signal(df, symbol, confirm_trend)
        if signal:
            # Backtest Rejection
            try:
                hist_candles = get_historical_candles(symbol, BACKTEST_DAYS)
                if hist_candles:
                    df_hist = build_dataframe(hist_candles)
                    df_hist = calculate_indicators(df_hist, symbol=symbol)
                    bt = run_quick_backtest(df_hist)
                    if bt['total_trades'] >= BACKTEST_MIN_TRADES and bt['net_pnl'] < 0:
                        return None
                    signal['backtest_pnl'] = bt['net_pnl']
                    signal['backtest_wr']  = bt['win_rate']
            except: pass

            # Deduplication
            key = f"{symbol}_{signal['direction']}"
            if key in sent_this_run: return None
            if _is_duplicate(symbol, signal['direction']): return None
                
            sent_this_run.add(key)
            return signal
        return None
    except Exception as e:
        logger.error(f"Error processing {symbol}: {e}")
        return None


def execute_trades(found_signals: list):
    from config.settings import PAPER_TRADING
    if not found_signals or (not ENABLE_AUTO_TRADING and not PAPER_TRADING):
        return

    ranked_signals = [s for s in found_signals if s.get('score', 0) >= MIN_SCORE]
    ranked_signals = sorted(ranked_signals, key=lambda x: x.get('score', 0), reverse=True)
    
    if not ranked_signals: return

    balance_usdt = get_futures_balance()
    balance_inr  = balance_usdt * USDT_INR_RATE
    
    if PAPER_TRADING and balance_inr < TRADE_THRESHOLD_INR:
        balance_inr = 10000.0
        balance_usdt = balance_inr / USDT_INR_RATE

    max_trades = int(balance_inr // TRADE_THRESHOLD_INR)
    if max_trades == 0 and balance_inr >= 100: max_trades = 1

    executed_count = 0
    remaining_balance_usdt = balance_usdt
    
    # Pre-fetch live state once for all execution checks
    live_positions = get_open_positions() or []
    open_orders    = get_all_open_orders()

    for signal in ranked_signals:
        if executed_count >= max_trades: break
        
        threshold_usdt = round(TRADE_THRESHOLD_INR / USDT_INR_RATE, 2)
        amount_to_use_usdt = min(threshold_usdt, remaining_balance_usdt)
        if amount_to_use_usdt < 1.0: continue

        symbol = signal['symbol']
        
        if _is_duplicate(symbol, signal['direction'], live_positions, open_orders):
            continue

        try:
            trade_logger.info(f"🚀 Executing Top Signal: {symbol} (Score: {signal['score']})")
            order_result = place_limit_order(
                symbol      = symbol,
                direction   = signal['direction'],
                entry_price = signal['entry'],
                tp_price    = signal.get('target'),
                sl_price    = signal.get('stop_loss'),
                amount_usdt = amount_to_use_usdt,
            )
            
            if order_result.get("success"):
                _mark_signal_sent(symbol, signal['direction'])
                trade_logger.info(f"✅ Order successful for {symbol} | Qty: {order_result.get('quantity')}")
                executed_count += 1
                remaining_balance_usdt -= amount_to_use_usdt
        except Exception as e:
            logger.error(f"Error executing trade for {symbol}: {e}")


def run_scanner():
    logger.info("=" * 50)
    logger.info("Scanner started...")
    _clean_signal_cache()
    
    symbols       = get_symbols()
    sent_this_run = set()
    found_signals = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_symbol, s, sent_this_run): s for s in symbols}
        for future in futures:
            res = future.result()
            if res: found_signals.append(res)

    if found_signals:
        execute_trades(found_signals)
    
    logger.info("=" * 50)


if __name__ == "__main__":
    logger.info("CoinDCX Futures Bot (Ultra-Minimal) started")
    check_order_statuses()
    run_scanner()
    
    schedule.every(5).minutes.do(check_order_statuses)
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scanner)
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(5)