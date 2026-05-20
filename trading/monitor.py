"""
Live Paper Trading Monitor

Runs in a background daemon thread during NSE market hours (9:15–3:30 IST).
Checks prices every 60 seconds and logs paper BUY/SELL decisions.

Core sell rule (hard-coded, never overridden):
  SELL only when current price > avg buy price (i.e. profit exists).
  If a stock is in loss, hold indefinitely until it recovers.
  Profit is always measured from the average acquisition price, not
  from today's open or any real-time reference.

This means:
  Bought CIPLA at ₹1400 → dips to ₹1200 → HOLD (loss, wait)
  Two months later → rises to ₹1500 → SELL HALF at +7.1% profit ✓

Pipeline used (same as Phase 4, just every 60s instead of 15 min):
  Phase 1 → fetch live LTPs + dip-buy signals
  Phase 2 → sell signals (profit-only, never-at-loss guardrail built in)
  Phase 3 → capital allocation for buy signals
  Phase 4 → log to CSV + Excel daily sheet
"""

import time
import threading
import logging
import pytz
from datetime import datetime

log = logging.getLogger("monitor")

IST          = pytz.timezone("Asia/Kolkata")
MARKET_OPEN  = (9, 15)
MARKET_CLOSE = (15, 30)
INTERVAL_SEC = 60


# ── Shared UI state ────────────────────────────────────────────────────────────
class MonitorState:
    running           = False
    last_run_time     = None
    last_run_id       = None
    cycle_count       = 0
    recent_decisions  : list[dict] = []   # last 50 BUY/SELL actions
    errors            : list[str]  = []   # last 10 errors


_thread : threading.Thread | None = None
_stop    = threading.Event()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ist_now() -> datetime:
    return datetime.now(IST)


def _is_market_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


# ── One 60-second cycle ────────────────────────────────────────────────────────

def _run_cycle(api, excel_path: str, total_budget: float) -> str:
    """
    Execute one full signal + log cycle using the Phase 1→2→3→4 pipeline.
    Returns the run_id string.
    """
    from .phase4 import run_once, _ensure_log
    from . import websocket_stream as _ws

    now    = _ist_now()
    run_id = now.strftime("%Y%m%d_%H%M%S")   # second-level ID for 60s cadence

    # If WebSocket is streaming we already have live LTPs; pass them to
    # fetch_signals via a thin wrapper so Phase 1 skips the API poll
    # and uses cached prices instead (saves 20 API calls/minute).
    ws_prices = _ws.get_all_ltp()

    if len(ws_prices) >= 15:
        # WebSocket has enough prices → build signals directly from cache
        result = _run_cycle_from_ws(api, excel_path, total_budget, ws_prices, run_id, now)
    else:
        # Fall back to full Phase 4 run_once() which calls ltpData() per stock
        result = run_once(api, excel_path=excel_path, total_budget=total_budget)

    # Extract actionable rows for UI display
    log_rows = result.get("_raw_log_rows", [])
    active   = [r for r in log_rows if r.get("action", "HOLD") != "HOLD"]
    for r in active:
        r["_run_time"] = now.strftime("%H:%M:%S")
    MonitorState.recent_decisions = (active + MonitorState.recent_decisions)[:50]

    buys  = sum(1 for r in log_rows if r.get("action") == "BUY")
    sells = sum(1 for r in log_rows if "SELL" in str(r.get("action", "")))
    log.info(f"[{now.strftime('%H:%M:%S')}] {run_id} — "
             f"{buys} BUY, {sells} SELL, {len(log_rows)-buys-sells} HOLD")
    return run_id


def _run_cycle_from_ws(api, excel_path, total_budget, ws_prices, run_id, now):
    """
    Build paper trade decisions from WebSocket LTP cache, log to CSV + Excel.
    Mirrors phase4.run_once() but skips the API price fetch step.
    """
    import os, csv
    from .phase1 import load_holdings
    from .phase2 import compute_sell_signals
    from .phase3 import build_trade_plan
    from .phase4 import _ensure_log, _append_rows, LOG_FIELDS
    from .excel_logger import write_day as _excel_write
    from .stock_master import STOCK_LIST, STOCK_MAP

    today = now.strftime("%Y-%m-%d")
    t_str = now.strftime("%H:%M:%S")

    holdings = load_holdings(excel_path)

    # ── Build buy signals from WebSocket LTPs ──────────────────────────────────
    # (We don't have prev_close from WS, so use avg_buy as dip reference.)
    buy_signals = []
    for stock in STOCK_LIST:
        sym    = stock["symbol"]
        ltp    = ws_prices.get(sym)
        if not ltp:
            continue
        holding  = holdings.get(sym, {})
        avg_buy  = holding.get("avg_buy_price", 0)
        buy_dip  = stock["buy_dip_pct"]
        max_cap  = stock["max_capital"]

        if avg_buy > 0 and ltp <= avg_buy * (1 - buy_dip / 100):
            buy_signals.append({
                "Symbol":    sym,
                "Stock":     stock["name"],
                "Category":  stock["category"],
                "ltp":       ltp,
                "LTP ₹":    ltp,
                "Change %":  round((ltp - avg_buy) / avg_buy * 100, 2),
                "max_capital": max_cap,
            })

    # ── Phase 2: sell decisions (profit-only guard is inside compute_sell_signals)
    df_sell = compute_sell_signals(ws_prices, excel_path)

    # ── Phase 3: allocate buys ─────────────────────────────────────────────────
    trade_plan = build_trade_plan(buy_signals, total_budget=total_budget)

    # ── Build log rows ─────────────────────────────────────────────────────────
    log_rows = []
    actioned = set()

    for item in trade_plan["plan"]:
        sym = item["Symbol"]
        actioned.add(sym)
        log_rows.append({
            "date": today, "time": t_str, "run_id": run_id,
            "symbol": sym, "stock": item["Stock"], "category": item["Category"],
            "action": "BUY", "signal_price": item["LTP ₹"],
            "qty": item["Buy Qty"], "amount": item["Amount ₹"],
            "gain_pct": "", "reason": f"WS dip {item['Dip %']:+.2f}% vs avg buy",
            "buy_trigger_pct": "", "sell_target_price": "",
        })

    if not df_sell.empty:
        for _, row in df_sell[df_sell["Action"].str.contains("SELL", na=False)].iterrows():
            sym = row["Symbol"]
            actioned.add(sym)
            log_rows.append({
                "date": today, "time": t_str, "run_id": run_id,
                "symbol": sym, "stock": row["Stock"], "category": row["Category"],
                "action": row["Action"], "signal_price": row["LTP ₹"],
                "qty": row["Sell Qty"], "amount": row["Sell Value ₹"],
                "gain_pct": row["Gain %"],
                "reason": f"Price ₹{row['LTP ₹']} hit target ₹{row['Tier-1 Target ₹']}",
                "buy_trigger_pct": "", "sell_target_price": row["Tier-1 Target ₹"],
            })

    for stock in STOCK_LIST:
        sym = stock["symbol"]
        ltp = ws_prices.get(sym)
        if sym not in actioned:
            log_rows.append({
                "date": today, "time": t_str, "run_id": run_id,
                "symbol": sym, "stock": stock["name"], "category": stock["category"],
                "action": "HOLD", "signal_price": round(ltp, 2) if ltp else "",
                "qty": 0, "amount": 0, "gain_pct": "",
                "reason": "No trigger", "buy_trigger_pct": stock["buy_dip_pct"],
                "sell_target_price": "",
            })

    _ensure_log()
    _append_rows(log_rows)

    avg_buy_map = {s: h["avg_buy_price"] for s, h in holdings.items() if h["avg_buy_price"] > 0}
    try:
        _excel_write(log_rows, avg_buy_map=avg_buy_map, for_date=now.date())
    except Exception as e:
        log.warning(f"Excel write failed: {e}")

    return {
        "run_id": run_id,
        "_raw_log_rows": log_rows,
        "errors": [],
    }


# ── Background thread loop ──────────────────────────────────────────────────────

def _monitor_loop(api, excel_path: str, total_budget: float):
    MonitorState.running     = True
    MonitorState.cycle_count = 0
    log.info("Live monitor started — checking every 60s during market hours.")
    log.info("SELL rule: only when price > avg buy price (profit-only, hold at loss).")

    while not _stop.is_set():
        now = _ist_now()

        if _is_market_open():
            try:
                run_id = _run_cycle(api, excel_path, total_budget)
                MonitorState.last_run_time = now.strftime("%H:%M:%S")
                MonitorState.last_run_id   = run_id
                MonitorState.cycle_count  += 1
            except Exception as e:
                err = f"[{now.strftime('%H:%M:%S')}] {e}"
                log.error(err)
                MonitorState.errors = ([err] + MonitorState.errors)[:10]
        else:
            if now.weekday() >= 5:
                _stop.wait(3600); continue
            elif (now.hour, now.minute) < MARKET_OPEN:
                mins = (MARKET_OPEN[0]*60 + MARKET_OPEN[1]) - (now.hour*60 + now.minute)
                log.info(f"Pre-market — {mins} min until open.")
            else:
                log.info("Market closed for today.")

        _stop.wait(INTERVAL_SEC)

    MonitorState.running = False
    log.info("Monitor stopped.")


# ── Public API ──────────────────────────────────────────────────────────────────

def start_monitor(api, excel_path: str = "stock_config.xlsx",
                  total_budget: float = 120_000) -> bool:
    global _thread
    if is_running():
        return False
    _stop.clear()
    MonitorState.recent_decisions = []
    MonitorState.errors           = []
    _thread = threading.Thread(
        target=_monitor_loop,
        args=(api, excel_path, total_budget),
        daemon=True,
        name="live_monitor",
    )
    _thread.start()
    return True


def stop_monitor():
    _stop.set()
    MonitorState.running = False


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
