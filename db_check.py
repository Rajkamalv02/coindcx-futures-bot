"""
db_check.py  –  Diagnostic for placed orders in MongoDB.
Run with:  python db_check.py

Checks every non-terminal order:
  - Still placed/open?  Polls CoinDCX for live status.
  - Filled/Active?      Checks CoinDCX positions to see if still live.
  - Already Closed?     Shows stored PnL.
"""

import json
from datetime import datetime, timezone
from database.mongo import get_db
from trading.order import get_order_status
from trading.position import get_open_positions


# ── helpers ───────────────────────────────────────────────────────────────

def _norm(symbol: str) -> str:
    return symbol.replace("B-", "").replace("_", "").upper()


def _fmt_dt(dt) -> str:
    if not dt:
        return "N/A"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return str(dt)


def _divider(char="─", width=65):
    print(char * width)


# ── main diagnostic ───────────────────────────────────────────────────────

def diagnose():
    print()
    _divider("═")
    print("  MongoDB Orders Diagnostic")
    _divider("═")

    db         = get_db()
    orders_col = db["orders"]

    total = orders_col.count_documents({})
    print(f"  Total documents in 'orders' collection : {total}")

    statuses = orders_col.distinct("order_status")
    print(f"  Distinct statuses found                : {statuses}")
    print()

    # ── Pending orders (placed / open) ─────────────────────────────────
    pending = list(orders_col.find(
        {"order_status": {"$in": ["placed", "open"]}},
        {"_id": 0}
    ).sort("created_at", -1))

    _divider()
    print(f"  PENDING ORDERS (placed/open): {len(pending)}")
    _divider()

    if not pending:
        print("  ✅ No pending orders.")
    else:
        for i, o in enumerate(pending, 1):
            oid     = o.get("order_id", "N/A")
            sym     = o.get("symbol", "?")
            side    = o.get("direction", "?")
            status  = o.get("order_status")
            created = _fmt_dt(o.get("created_at"))

            print(f"  [{i}] {sym:20s} | {side:5s} | DB status: {status:10s} | Created: {created}")
            print(f"       Order ID  : {oid}")

            # Poll CoinDCX live status
            if oid and oid != "paper_trading_id":
                result     = get_order_status(oid)
                live_status = result.get("status", "unknown")
                data        = result.get("data", {})
                avg_price   = data.get("avg_price") or data.get("price", "N/A")
                print(f"       CoinDCX   : status='{live_status}'  avg_price={avg_price}")
                if live_status != status:
                    print(f"       ⚠️  STATUS MISMATCH — DB has '{status}' but CoinDCX says '{live_status}'")
                    print(f"       → Run check_order_statuses() or restart the bot to sync.")
            else:
                print("       CoinDCX   : (paper trade — no live check)")
            print()

    # ── Active trades (filled / is_active=True) ────────────────────────
    active = list(orders_col.find(
        {"is_active": True, "order_status": "filled"},
        {"_id": 0}
    ).sort("created_at", -1))

    _divider()
    print(f"  ACTIVE TRADES (filled, is_active=True): {len(active)}")
    _divider()

    # Fetch live positions once
    live_positions = get_open_positions()
    live_norm_syms = set()
    for pos in live_positions:
        raw = pos.get("pair") or pos.get("symbol") or ""
        if raw:
            live_norm_syms.add(_norm(raw))

    print(f"  Live positions on CoinDCX: {live_norm_syms or 'NONE'}")
    print()

    if not active:
        print("  ✅ No active trades.")
    else:
        for i, t in enumerate(active, 1):
            sym       = t.get("symbol", "?")
            direction = t.get("direction", "?")
            entry     = t.get("entry_usdt", "?")
            qty       = t.get("quantity", "?")
            oid       = t.get("order_id", "N/A")
            created   = _fmt_dt(t.get("created_at"))
            norm      = _norm(sym)
            still_live = norm in live_norm_syms

            status_icon = "🟢 STILL OPEN" if still_live else "🔴 NOT IN POSITIONS (may be closed)"

            print(f"  [{i}] {sym:20s} | {direction:5s} @ {entry} USDT | qty={qty}")
            print(f"       Order ID  : {oid}")
            print(f"       Created   : {created}")
            print(f"       Position  : {status_icon}")
            if not still_live:
                print(f"       ⚠️  This trade likely CLOSED. Run bot or call check_order_statuses() to record PnL.")
            print()

    # ── Closed trades ─────────────────────────────────────────────────
    closed = list(orders_col.find(
        {"order_status": "closed"},
        {"_id": 0}
    ).sort("exit_time", -1).limit(10))

    _divider()
    print(f"  RECENTLY CLOSED TRADES (last {len(closed)})")
    _divider()

    if not closed:
        print("  ℹ️  No closed trades yet.")
    else:
        total_pnl = 0.0
        for i, c in enumerate(closed, 1):
            sym     = c.get("symbol", "?")
            side    = c.get("direction", "?")
            pnl     = c.get("realized_pnl_usdt", 0) or 0
            fees    = c.get("fees_usdt", 0) or 0
            entry   = c.get("entry_usdt", "?")
            exit_p  = c.get("exit_price", "?")
            reason  = c.get("exit_reason", "?")
            ex_time = _fmt_dt(c.get("exit_time"))
            emoji   = "🟢" if pnl >= 0 else "🔴"

            total_pnl += pnl
            print(
                f"  [{i}] {emoji} {sym:20s} | {side:5s} | "
                f"Entry: {entry} → Exit: {exit_p} | "
                f"PnL: {pnl:+.4f} USDT (fees: {fees:.6f})"
            )
            print(f"       Closed: {ex_time} | Reason: {reason}")
        print()
        _divider()
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        print(f"  {pnl_emoji} TOTAL REALIZED PnL (last {len(closed)} trades): {total_pnl:+.4f} USDT")

    _divider("═")
    print()


if __name__ == "__main__":
    diagnose()
