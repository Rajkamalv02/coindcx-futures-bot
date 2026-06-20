import schedule
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from config.settings import (
    WATCHLIST, SCAN_INTERVAL_MINUTES, ENABLE_AUTO_TRADING,
    TRADE_THRESHOLD_INR, USDT_INR_RATE, MIN_SCORE,
    BACKTEST_DAYS, BACKTEST_MIN_WIN_RATE, BACKTEST_MIN_TRADES
)
from api.fetcher import get_filtered_symbols, get_candles, get_confirm_candles, get_historical_candles
from signals.indicators import build_dataframe, calculate_indicators, get_confirm_trend
from signals.scanner import detect_signal, run_quick_backtest
from alerts.telegram import send_signal
from trading.order import place_limit_order, get_order_status, get_trade_details, get_symbol_trades
from trading.position import get_futures_balance, get_open_positions
from database.mongo import (
    save_order, get_db, get_open_orders, update_order_status,
    get_active_trades, mark_trade_closed
)
from utils.logger import logger, scanner_logger, trade_logger, write_to_ledger

# ── Deduplication cache ────────────────────────────────
_cache_lock = threading.Lock()
_sent_lock = threading.Lock()
# Stores "SYMBOL_DIRECTION" → timestamp of last signal
_signal_cache: dict = {}
SIGNAL_COOLDOWN_MINUTES = 60  # don't repeat same signal within 60 min


# def _is_duplicate(symbol: str, direction: str) -> bool:
#     """
#     Check if a signal is duplicate based on:
#     1. Local memory cache (cooldown)
#     2. Active trades in DB
#     3. Pending orders in DB
#     """
#     key      = f"{symbol}_{direction}"
#     now      = time.time()
    
#     # 1. Local Cache Check
#     with _cache_lock:
#         last_ts  = _signal_cache.get(key, 0)
#         if now - last_ts < SIGNAL_COOLDOWN_MINUTES * 60:
#             return True

#     # 2. Database Check (Active Trades)
#     active = get_active_trades()
#     if any(t['symbol'] == symbol for t in active):
#         return True

#     # 3. Database Check (Pending Orders)
#     pending = get_open_orders()
#     if any(o['symbol'] == symbol for o in pending):
#         return True

#     # Update cache if not duplicate
#     with _cache_lock:
#         _signal_cache[key] = now
#     return False

def _is_duplicate(symbol: str, direction: str) -> bool:
    """Read-only — does NOT mutate the cache."""
    key = f"{symbol}_{direction}"
    now = time.time()

    with _cache_lock:
        last_ts = _signal_cache.get(key, 0)
        if now - last_ts < SIGNAL_COOLDOWN_MINUTES * 60:
            return True

    active = get_active_trades()
    if any(t['symbol'] == symbol for t in active):
        return True

    pending = get_open_orders()
    if any(o['symbol'] == symbol for o in pending):
        return True

    return False


def _mark_signal_sent(symbol: str, direction: str):
    with _cache_lock:
        _signal_cache[f"{symbol}_{direction}"] = time.time()

def _norm_sym(symbol: str) -> str:
    if not symbol: return ""
    return symbol.replace("B-", "").replace("_", "").replace("-", "").upper()


def check_order_statuses():
    """
    Phase 1 – Pending orders: poll CoinDCX to see if they got filled or cancelled.
    Phase 2 – Active trades:  detect exits via position list + direct order status.
    """
    trade_logger.info("=== check_order_statuses() START ===")

    # ──────────────────────────────────────────────────────
    # PHASE 1 – Pending Orders  (placed / open / initial)
    # ──────────────────────────────────────────────────────
    # Build normalised set of live position symbols from CoinDCX
    # live_positions  = get_open_positions()
    # live_norm_syms  = set()
    # for pos in live_positions:
    #     raw = pos.get("pair") or pos.get("symbol") or ""
    #     if raw:
    #         live_norm_syms.add(_norm_sym(raw))

    live_positions = get_open_positions()
    if live_positions is None:
        trade_logger.warning("⚠️ Positions fetch failed — skipping exit detection this cycle to avoid false closes.")
        trade_logger.info("=== check_order_statuses() END ===")
        return
    live_norm_syms = set()
    for pos in live_positions:
        raw = pos.get("pair") or pos.get("symbol") or ""
        size = abs(float(pos.get("active_pos", 0) or 0))
        if raw and size > 0:          # only count genuinely open positions
            live_norm_syms.add(_norm_sym(raw))

    open_orders = get_open_orders()
    trade_logger.info(f"[Phase 1] {len(open_orders)} pending order(s) in DB")

    for order in open_orders:
        order_id = order.get("order_id")
        symbol   = order.get("symbol", "?")

        if not order_id or order_id == "paper_trading_id":
            trade_logger.debug(f"  Skipping paper/no-id order for {symbol}")
            continue

        result     = get_order_status(order_id)
        new_status = result.get("status", "")
        old_status = order.get("order_status", "")

        trade_logger.info(
            f"  [{symbol}] order_id={order_id[:8]}… "
            f"DB='{old_status}' → API='{new_status}'"
        )

        if new_status and new_status not in ("unknown", "error") and new_status != old_status:
            # IMPORTANT: Use the actual fill price from the API as the entry price
            api_data = result.get("data", {})
            actual_fill = api_data.get("avg_price") or api_data.get("price")
            
            if actual_fill and float(actual_fill) > 0:
                trade_logger.info(f"  Updating entry price to actual fill: {actual_fill}")
                update_order_status(order_id, new_status, extra={"avg_fill_price": float(actual_fill)})
            else:
                update_order_status(order_id, new_status)
        
        elif new_status in ("unknown", "error", "not_found"):
            # If API fails or order is not in lists, check if the symbol is already in live positions
            if _norm_sym(symbol) in live_norm_syms:
                trade_logger.info(f"  🔍 Order status unknown but {symbol} found in live positions. Marking as FILLED.")
                update_order_status(order_id, "filled")
            else:
                trade_logger.debug(f"  System status unknown for {symbol}, but no position found. Keeping old status '{old_status}'.")

            if new_status == "filled":
                trade_logger.info(
                    f"  ✅ FILLED: {symbol} {order.get('direction')} "
                    f"@ {order.get('entry_usdt')} USDT"
                )
            elif new_status in ("cancelled", "rejected", "cancel"):
                trade_logger.info(
                    f"  ❌ {new_status.upper()}: {symbol} order cancelled/rejected"
                )

    # ──────────────────────────────────────────────────────
    # PHASE 2 – Active Trades  (filled / is_active=True)
    # ──────────────────────────────────────────────────────
    active_trades = get_active_trades()
    trade_logger.info(f"[Phase 2] {len(active_trades)} active trade(s) in DB")

    if not active_trades:
        trade_logger.info("=== check_order_statuses() END ===")
        return

    trade_logger.info(
        f"  Live positions on exchange: {live_norm_syms or 'NONE'}"
    )

    for trade in active_trades:
        symbol    = trade.get("symbol", "")
        order_id  = trade.get("order_id", "")
        direction = trade.get("direction", "")
        norm      = _norm_sym(symbol)

        # ── Strategy A: symbol absent from live positions ──
        still_live = (norm in live_norm_syms)

        # ── Strategy B: directly check order status on API ──
        if order_id and order_id != "paper_trading_id":
            status_result = get_order_status(order_id)
            api_status    = status_result.get("status", "")
        else:
            api_status = ""

        trade_logger.info(
            f"  [{symbol}] live={still_live} | "
            f"api_status='{api_status}'"
        )

        # Determine if exit has occurred
        CLOSED_STATUSES = {"filled", "cancelled", "rejected", "cancel", "closed"}
        exit_by_position = not still_live
        exit_by_status   = (api_status in CLOSED_STATUSES)

        if still_live and not exit_by_status:
            trade_logger.info(f"  ✅ {symbol} is STILL ACTIVE. Skipping.")
            continue

        # ── Exit Detected ──────────────────────────────────
        trade_logger.info(
            f"  🔔 EXIT detected: {symbol} | "
            f"position_gone={exit_by_position} status_closed={exit_by_status}"
        )

        # Determine exit price from multiple sources
        exit_price = 0.0
        fees       = 0.0

        # Source 1: avg_price in direct order status response
        if status_result := (get_order_status(order_id) if order_id and order_id != "paper_trading_id" else {}):
            api_data  = status_result.get("data", {})
            avg_p     = api_data.get("avg_price") or api_data.get("price", 0)
            fee_amt   = api_data.get("fee_amount", 0)
            if avg_p:
                exit_price = float(avg_p)
                fees       = float(fee_amt or 0)
                trade_logger.info(f"  Exit price from order API: {exit_price}")

        # Source 2: trade history for this order ID
        if exit_price == 0.0 and order_id and order_id != "paper_trading_id":
            details = get_trade_details(symbol, order_id)
            if details.get("success"):
                exit_price = float(details.get("fill_price", 0))
                fees       = float(details.get("fees", 0))
                trade_logger.info(f"  Exit price from trade details: {exit_price}")

        # Source 3: scan recent symbol history for opposite-side trades
        if exit_price == 0.0:
            history     = get_symbol_trades(symbol)
            close_side  = "sell" if direction == "LONG" else "buy"
            matching    = [t for t in history if t.get("side") == close_side]
            if matching:
                matching.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
                latest     = matching[0]
                exit_price = float(latest.get("price", 0))
                fees       = float(latest.get("fee_amount", 0))
                trade_logger.info(
                    f"  Exit price from trade history: {exit_price} (fees: {fees})"
                )

        if exit_price == 0.0:
            trade_logger.warning(
                f"  ⚠️ Cannot determine exit price for {symbol}. "
                f"Will retry next cycle."
            )
            continue

        # ── PnL Calculation ───────────────────────────────
        entry_price = float(trade.get("entry_usdt") or trade.get("avg_fill_price") or 0)
        quantity    = float(trade.get("quantity", 0))

        if direction == "LONG":
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity

        net_pnl = gross_pnl - fees
        emoji   = "🟢" if net_pnl >= 0 else "🔴"

        close_data = {
            "symbol":      symbol,
            "direction":   direction,
            "entry_price": entry_price,
            "exit_price":  exit_price,
            "quantity":    quantity,
            "fees_usdt":   round(fees, 6),
            "pnl_usdt":    round(net_pnl, 4),
            "reason":      "TP/SL/Manual (Auto-detected)",
        }

        mark_trade_closed(order_id, close_data)
        write_to_ledger(close_data)

        trade_logger.info(
            f"  {emoji} TRADE CLOSED: {symbol} {direction} | "
            f"Entry: {entry_price} → Exit: {exit_price} | "
            f"Gross: {gross_pnl:+.4f} | Fees: {fees:.6f} | "
            f"Net PnL: {net_pnl:+.4f} USDT"
        )

        # ── Telegram notification ─────────────────────────
        try:
            from alerts.telegram import send_message
            pnl_str = f"{net_pnl:+.4f} USDT"
            msg = (
                f"{emoji} *TRADE CLOSED*\n"
                f"Symbol: `{symbol}`  |  {direction}\n"
                f"Entry: `{entry_price}` → Exit: `{exit_price}`\n"
                f"Net PnL: *{pnl_str}*  (fees: {fees:.6f})"
            )
            send_message(msg)
        except Exception as tg_err:
            trade_logger.warning(f"  Telegram notify failed: {tg_err}")

    trade_logger.info("=== check_order_statuses() END ===")



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
        df      = calculate_indicators(df,symbol=symbol)

        confirm_candles = get_confirm_candles(symbol)
        df_confirm      = build_dataframe(confirm_candles)
        confirm_trend   = get_confirm_trend(df_confirm)

        signal = detect_signal(df, symbol, confirm_trend)

        if signal:
            # ── Dynamic Backtest (Expectancy Check) ────────
            try:
                scanner_logger.info(f"⏳ Running dynamic backtest for {symbol} ({BACKTEST_DAYS} days)...")
                hist_candles = get_historical_candles(symbol, BACKTEST_DAYS)
                if not hist_candles:
                    logger.warning(f"  ⚠️ Backtest skipped: No history for {symbol}")
                else:
                    df_hist = build_dataframe(hist_candles)
                    df_hist = calculate_indicators(df_hist, symbol=symbol)
                    bt = run_quick_backtest(df_hist)
                    
                    pnl = bt['net_pnl']
                    wr  = bt['win_rate']
                    tr  = bt['total_trades']
                    
                    # Log the metrics for transparency to both File & Console
                    msg = f"📊 Backtest {symbol}: WR={wr:.0%}, Net={pnl:+.2f}%, Count={tr}"
                    scanner_logger.info(msg)
                    
                    if tr >= BACKTEST_MIN_TRADES and pnl < 0:
                        logger.warning(f"  ❌ {symbol} rejected: Negative expectancy ({pnl:+.2f}%) over {tr} trades.")
                        return None
                    
                    if tr < BACKTEST_MIN_TRADES:
                        logger.info(f"  ⚠️ {symbol} backtest thin ({tr} trades), allowing for now.")
                    else:
                        logger.info(f"  ✅ {symbol} passed backtest! Expectancy: {pnl:+.2f}%")
                    
                    signal['backtest_pnl'] = pnl
                    signal['backtest_wr']  = wr
            except Exception as bt_err:
                logger.error(f"  ❌ Backtest engine failure for {symbol}: {bt_err}")
                return None

            key = f"{symbol}_{signal['direction']}"

            # Block if already sent this run OR within cooldown OR already in DB
            with _sent_lock:
                if key in sent_this_run:
                    return None
                
                if _is_duplicate(symbol, signal['direction']):
                    scanner_logger.info(f"Duplicate/Active skipped: {symbol} {signal['direction']}")
                    return None
                
                sent_this_run.add(key)

            # Signal found! Log to scanner log
            scanner_logger.info(f"🔍 Signal Detected: {symbol} {signal['direction']} (Score: {signal['score']}/6)")
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
    ranked_signals = [s for s in found_signals if s.get('score', 0) >= MIN_SCORE]
    ranked_signals = sorted(found_signals, key=lambda x: x.get('score', 0), reverse=True)
    
    # 2. Fetch Balance and calculate limit
    balance_usdt = get_futures_balance()
    balance_inr  = balance_usdt * USDT_INR_RATE
    
    # MOCK balance for Paper Trading so we can see the orders execute
    if PAPER_TRADING and balance_inr < TRADE_THRESHOLD_INR:
        trade_logger.info("🧪 Paper Trading: Using MOCK balance (₹10,000.0) for simulation.")
        balance_inr = 10000.0
        balance_usdt = balance_inr / USDT_INR_RATE

    # Calculate max trades: allow at least 1 if we have ₹100+
    max_trades = int(balance_inr // TRADE_THRESHOLD_INR)
    if max_trades == 0 and balance_inr >= 100:
        max_trades = 1
        trade_logger.info(f"ℹ️ Balance (₹{balance_inr:.2f}) is below threshold, allowing 1 trade with remainder.")

    trade_logger.info(f"💹 Ranking Results: {len(ranked_signals)} signals found.")
    trade_logger.info(f"💰 Balance: ₹{balance_inr:.2f} | Threshold: ₹{TRADE_THRESHOLD_INR} | Max Trades: {max_trades}")
    
    # 3. Process top signals
    executed_count = 0
    remaining_balance_usdt = balance_usdt
    
    for signal in ranked_signals:
        if executed_count >= max_trades:
            trade_logger.info(f"⏹️ Trade limit reached ({max_trades}). Skipping {signal['symbol']} (Score: {signal['score']})")
            continue
            
        # Amount for THIS trade: Use threshold OR all remaining balance
        threshold_usdt = round(TRADE_THRESHOLD_INR / USDT_INR_RATE, 2)
        amount_to_use_usdt = min(threshold_usdt, remaining_balance_usdt)
        
        if amount_to_use_usdt < 1.0: # Minimum 1 USDT for order
            trade_logger.warning(f"⚠️ Skipping {signal['symbol']}: Residual balance too low ({amount_to_use_usdt:.2f} USDT)")
            continue

        symbol = signal['symbol']
        
        # Final safety: check if we already have an active/pending trade for this symbol
        # (This handles the case if a signal was found but another thread already placed it)
        if _is_duplicate(symbol, signal['direction']):
            trade_logger.info(f"⏩ {symbol} skipped: Position/Order already exists in DB.")
            continue

        try:
            trade_logger.info(f"🚀 Executing Top Signal: {symbol} (Score: {signal['score']}) | Budget: {amount_to_use_usdt:.2f} USDT")
            
            order_result = place_limit_order(
                symbol      = symbol,
                direction   = signal['direction'],
                entry_price = signal['entry'],
                tp_price    = signal.get('target'),
                sl_price    = signal.get('stop_loss'),
                amount_usdt = amount_to_use_usdt,
            )
            
            signal.update(order_result)
            
            # Wrap telegram alert in its own try block to prevent crash on network issues
            try:
                send_signal(signal) # Send telegram alert with order info
            except Exception as e:
                logger.error(f"Failed to send Telegram alert for {symbol}: {e}")

            if order_result.get("success"):
                _mark_signal_sent(symbol, signal['direction'])
                save_order(signal)
                trade_logger.info(f"✅ Order successful for {symbol}")
                executed_count += 1
                remaining_balance_usdt -= amount_to_use_usdt
            else:
                trade_logger.warning(f"❌ Order failed for {symbol}. Moving to next ranked signal.")
                
        except Exception as e:
            logger.error(f"Critical error executing trade for {symbol}: {e}")
            continue


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
    check_order_statuses()
    run_scanner()
    # Add in __main__ block:
    schedule.every(5).minutes.do(check_order_statuses)

    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scanner)
    while True:
        schedule.run_pending()
        time.sleep(1)