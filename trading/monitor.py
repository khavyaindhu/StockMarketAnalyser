"""
Live Paper Trading Monitor

Runs in a background daemon thread during NSE market hours (9:15–3:30 IST).
Every 60 seconds it:
  1. Reads live LTPs from the WebSocket cache (trading/websocket_stream.py)
     — no extra API calls, uses the already-streaming prices.
     Falls back to ltpData() API if WebSocket is not running.
  2. Runs Phase 1 signal logic (dip-buy / rise-sell)
  3. Runs Phase 2 sell decisions for current holdings
  4. Runs Phase 3 capital allocation for any BUY signals
  5. Logs every decision to:
       logs/paper_trade_log.csv  (Phase 4 format, for analytics)
       logs/paper_trades.xlsx    (Excel daily sheet, one tab per day)
  6. Stores the last N decisions in MonitorState for live display in the UI

Usage (from app.py):
  from trading.monitor import start_monitor, stop_monitor, is_running, MonitorState
"""

import os
import time
import threading
import logging
import pytz
from datetime import datetime

log = logging.getLogger("monitor")

IST          = pytz.timezone("Asia/Kolkata")
MARKET_OPEN  = (9, 15)
MARKET_CLOSE = (15, 30)
INTERVAL_SEC = 60          # check every 60 seconds

# ── Shared state (read by Streamlit UI without locks for display only) ─────────
class MonitorState:
    running       = False
    last_run_time = None       # "HH:MM:SS" string
    last_run_id   = None
    recent_decisions: list[dict] = []   # last 50 BUY/SELL decisions
    cycle_count   = 0
    errors        : list[str]   = []    # last 10 errors

_thread: threading.Thread | None = None
_stop   = threading.Event()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ist_now() -> datetime:
    return datetime.now(IST)


def _is_market_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


def _get_ltp_map(api) -> dict[str, float]:
    """
    Get LTPs for all 20 stocks.
    Prefers the WebSocket cache (already streaming, no API cost).
    Falls back to ltpData() if WebSocket is not active or cache is stale.
    """
    from . import websocket_stream as _ws
    from .stock_master import STOCK_LIST

    ws_prices = _ws.get_all_ltp()

    # If WebSocket has prices for at least 10 of 20 stocks, use it
    if len(ws_prices) >= 10:
        return ws_prices

    # Fallback: fetch via API
    ltp_map = {}
    for stock in STOCK_LIST:
        sym = stock["symbol"]
        try:
            resp = api.ltpData("NSE", f"{sym}-EQ", "")
            data = (resp or {}).get("data") or {}
            ltp  = data.get("ltp")
            if ltp:
                ltp_map[sym] = float(ltp)
        except Exception:
            pass
    return ltp_map


# ── One monitoring cycle ────────────────────────────────────────────────────────

def _run_cycle(api, excel_path: str, total_budget: float):
    from .phase1 import fetch_signals, load_holdings
    from .phase2 import compute_sell_signals
    from .phase3 import build_trade_plan
    from .phase4 import _ensure_log, _append_rows, LOG_FIELDS
    from .excel_logger import write_day as _excel_write, EXCEL_FILE
    from .stock_master import STOCK_LIST, STOCK_MAP

    now    = _ist_now()
    run_id = now.strftime("%Y%m%d_%H%M")
    today  = now.strftime("%Y-%m-%d")
    t_str  = now.strftime("%H:%M:%S")

    # ── Get live prices ────────────────────────────────────────────────────────
    ltp_map = _get_ltp_map(api)
    if not ltp_map:
        raise RuntimeError("Could not fetch any LTP data")

    # ── Load holdings for sell signal context ──────────────────────────────────
    holdings = load_holdings(excel_path)

    # ── Phase 1: build signal rows from ltp_map ────────────────────────────────
    buy_signals  = []
    sell_signals = []
    log_rows     = []

    for stock in STOCK_LIST:
        sym     = stock["symbol"]
        ltp     = ltp_map.get(sym)
        if not ltp:
            continue

        holding    = holdings.get(sym, {})
        avg_buy    = holding.get("avg_buy_price", 0)
        held_qty   = holding.get("qty", 0)
        buy_dip    = stock["buy_dip_pct"]
        sell_tgt   = stock["sell_target_pct"]

        # Approximate prev close = ltp / (1 + change%) — we don't have it here
        # so signal is based on intraday dip from open; use a simplified check:
        # BUY if ltp has dropped by buy_dip_pct from avg_buy (only when held)
        # or if ltp is a fresh dip buy opportunity (no prior context without prev close)
        # For paper trading, we flag BUY when price is below avg_buy by dip%
        signal = "HOLD"
        reason = "No trigger"

        if avg_buy > 0 and ltp <= avg_buy * (1 - buy_dip / 100):
            signal = "BUY"
            reason = f"Price ₹{ltp:.2f} dipped {buy_dip}% below avg buy ₹{avg_buy:.2f}"
            buy_signals.append({
                "Symbol":    sym, "Stock": stock["name"],
                "Category":  stock["category"],
                "ltp":       ltp, "LTP ₹": ltp,
                "Change %":  round((ltp - avg_buy) / avg_buy * 100, 2),
                "max_capital": stock["max_capital"],
            })

        if avg_buy > 0 and held_qty > 0:
            tier1 = avg_buy * (1 + sell_tgt / 100)
            tier2 = avg_buy * (1 + sell_tgt * 1.5 / 100)
            if ltp >= tier2:
                signal = "SELL"
                reason = f"Price ₹{ltp:.2f} hit Tier-2 target ₹{tier2:.2f}"
                sell_signals.append(sym)
            elif ltp >= tier1:
                signal = "SELL"
                reason = f"Price ₹{ltp:.2f} hit Tier-1 target ₹{tier1:.2f}"
                sell_signals.append(sym)

        log_rows.append({
            "date":            today,
            "time":            t_str,
            "run_id":          run_id,
            "symbol":          sym,
            "stock":           stock["name"],
            "category":        stock["category"],
            "action":          signal,
            "signal_price":    round(ltp, 2),
            "qty":             0,
            "amount":          0,
            "gain_pct":        "",
            "reason":          reason,
            "buy_trigger_pct": buy_dip,
            "sell_target_price": round(avg_buy * (1 + sell_tgt / 100), 2) if avg_buy else "",
        })

    # ── Phase 3: allocate capital to buy signals ───────────────────────────────
    trade_plan = build_trade_plan(buy_signals, total_budget=total_budget)
    for item in trade_plan["plan"]:
        sym = item["Symbol"]
        for r in log_rows:
            if r["symbol"] == sym and r["action"] == "BUY":
                r["qty"]    = item["Buy Qty"]
                r["amount"] = item["Amount ₹"]
                break

    # ── Phase 2: sell decisions ────────────────────────────────────────────────
    df_sell = compute_sell_signals(ltp_map, excel_path)
    if not df_sell.empty:
        for _, row in df_sell[df_sell["Action"].str.contains("SELL", na=False)].iterrows():
            sym = row["Symbol"]
            for r in log_rows:
                if r["symbol"] == sym:
                    r["action"] = row["Action"]
                    r["qty"]    = row["Sell Qty"]
                    r["amount"] = row["Sell Value ₹"]
                    r["gain_pct"] = row["Gain %"]
                    r["reason"] = f"Price ₹{row['LTP ₹']} hit target ₹{row['Tier-1 Target ₹']}"
                    break

    # ── Append to CSV ──────────────────────────────────────────────────────────
    _ensure_log()
    _append_rows(log_rows)

    # ── Write to Excel ─────────────────────────────────────────────────────────
    avg_buy_map = {s: h["avg_buy_price"] for s, h in holdings.items() if h["avg_buy_price"] > 0}
    try:
        _excel_write(log_rows, avg_buy_map=avg_buy_map, for_date=now.date())
    except Exception as e:
        log.warning(f"Excel write failed: {e}")

    # ── Store actionable decisions for UI ──────────────────────────────────────
    active = [r for r in log_rows if r["action"] != "HOLD"]
    for r in active:
        r["_run_time"] = t_str
    MonitorState.recent_decisions = (active + MonitorState.recent_decisions)[:50]

    buys  = sum(1 for r in log_rows if r["action"] == "BUY")
    sells = sum(1 for r in log_rows if "SELL" in r["action"])
    log.info(f"[{t_str}] Cycle {run_id} — {buys} BUY, {sells} SELL, "
             f"{len(log_rows)-buys-sells} HOLD")

    return run_id


# ── Background thread loop ──────────────────────────────────────────────────────

def _monitor_loop(api, excel_path: str, total_budget: float):
    MonitorState.running = True
    MonitorState.cycle_count = 0
    log.info("Monitor started. Checking every 60s during market hours.")

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
                log.info("Weekend — monitor idle.")
                _stop.wait(3600)
                continue
            elif (now.hour, now.minute) < MARKET_OPEN:
                mins = (MARKET_OPEN[0]*60 + MARKET_OPEN[1]) - (now.hour*60 + now.minute)
                log.info(f"Pre-market — {mins} min until open.")
            else:
                log.info("Market closed — monitor idle.")

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
    MonitorState.errors = []
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
