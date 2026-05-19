"""
Phase 4 — Paper Trading Engine

Logic:
  Runs the full signal pipeline (Phase 1 → 2 → 3) every 15 minutes
  during NSE market hours (9:15 AM – 3:15 PM IST, Mon–Fri).

  For each run:
    1. Fetch live prices for all 20 stocks
    2. Compute buy/sell signals (Phase 1 + Phase 2)
    3. Build trade plan (Phase 3)
    4. Log EVERY decision to logs/paper_trade_log.csv
       — but place NO real orders

  Why paper trade first?
    You can see exactly what the algorithm would have done,
    compare it to actual market prices the next day, and
    validate that the logic makes money before risking real capital.

  What the log contains per row:
    date, time, symbol, stock name, action (BUY/SELL/HOLD),
    signal_price (price when signal fired), qty, amount,
    reason (which rule triggered it), run_id (which 15-min cycle)

  End-of-day summary (written at 3:20 PM):
    - How many BUY/SELL signals fired today
    - Total hypothetical capital deployed
    - Hypothetical P&L if those trades had been made (vs closing price)

Usage (run in Codespace terminal, keep it open during market hours):
    python -m trading.phase4

Or import and call run_once() from anywhere for a single cycle.
"""

import os
import csv
import time
import pytz
import logging
from datetime import datetime, date

from .phase1 import fetch_signals, load_holdings
from .phase2 import compute_sell_signals, sell_summary
from .phase3 import build_trade_plan

LOG_DIR  = "logs"
LOG_FILE = os.path.join(LOG_DIR, "paper_trade_log.csv")
IST      = pytz.timezone("Asia/Kolkata")

MARKET_OPEN  = (9,  15)   # 9:15 AM IST
MARKET_CLOSE = (15, 15)   # 3:15 PM IST (stop 15 min before session end)
INTERVAL_SEC = 15 * 60    # 15 minutes

LOG_FIELDS = [
    "date", "time", "run_id", "symbol", "stock", "category",
    "action", "signal_price", "qty", "amount", "gain_pct",
    "reason", "buy_trigger_pct", "sell_target_price",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("phase4")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ensure_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=LOG_FIELDS).writeheader()


def _append_rows(rows: list[dict]):
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        writer.writerows(rows)


def _ist_now() -> datetime:
    return datetime.now(IST)


def _is_market_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


# ── Single run ─────────────────────────────────────────────────────────────────

def run_once(api, excel_path: str = "stock_config.xlsx",
             total_budget: float = 120_000) -> dict:
    """
    Execute one full paper-trading cycle:
      Phase 1 → signals
      Phase 2 → sell decisions for holdings
      Phase 3 → buy allocation plan
      Log everything to CSV

    Returns a summary dict for display.
    """
    _ensure_log()

    now    = _ist_now()
    run_id = now.strftime("%Y%m%d_%H%M")
    today  = now.strftime("%Y-%m-%d")
    t_str  = now.strftime("%H:%M:%S")

    log.info(f"Run {run_id} — fetching signals for 20 stocks…")

    # ── Phase 1: fetch signals ─────────────────────────────────────────────────
    p1 = fetch_signals(api, excel_path)
    df_signals = p1["signals"]

    # Build ltp_map for Phase 2
    ltp_map = {
        row["Symbol"]: row["LTP ₹"]
        for _, row in df_signals.iterrows()
        if row["LTP ₹"] is not None
    }

    # ── Phase 2: sell decisions ────────────────────────────────────────────────
    df_sell = compute_sell_signals(ltp_map, excel_path)

    # ── Phase 3: buy allocation ────────────────────────────────────────────────
    trade_plan = build_trade_plan(p1["buy_signals"], total_budget=total_budget)

    # ── Build log rows ─────────────────────────────────────────────────────────
    log_rows = []

    # BUY rows from trade plan
    for item in trade_plan["plan"]:
        log_rows.append({
            "date":               today,
            "time":               t_str,
            "run_id":             run_id,
            "symbol":             item["Symbol"],
            "stock":              item["Stock"],
            "category":           item["Category"],
            "action":             "BUY",
            "signal_price":       item["LTP ₹"],
            "qty":                item["Buy Qty"],
            "amount":             item["Amount ₹"],
            "gain_pct":           "",
            "reason":             f"Dip {item['Dip %']:+.2f}% past buy trigger",
            "buy_trigger_pct":    "",
            "sell_target_price":  "",
        })

    # SELL rows from Phase 2
    if not df_sell.empty:
        for _, row in df_sell[df_sell["Action"].str.contains("SELL", na=False)].iterrows():
            log_rows.append({
                "date":               today,
                "time":               t_str,
                "run_id":             run_id,
                "symbol":             row["Symbol"],
                "stock":              row["Stock"],
                "category":           row["Category"],
                "action":             row["Action"],
                "signal_price":       row["LTP ₹"],
                "qty":                row["Sell Qty"],
                "amount":             row["Sell Value ₹"],
                "gain_pct":           row["Gain %"],
                "reason":             f"Price ₹{row['LTP ₹']} hit target ₹{row['Tier-1 Target ₹']}",
                "buy_trigger_pct":    "",
                "sell_target_price":  row["Tier-1 Target ₹"],
            })

    # HOLD rows (one per stock with no action — for full audit trail)
    actioned = {r["symbol"] for r in log_rows}
    for _, row in df_signals.iterrows():
        if row["Symbol"] not in actioned:
            log_rows.append({
                "date":               today,
                "time":               t_str,
                "run_id":             run_id,
                "symbol":             row["Symbol"],
                "stock":              row["Stock"],
                "category":           row["Category"],
                "action":             "HOLD",
                "signal_price":       row["LTP ₹"] or "",
                "qty":                0,
                "amount":             0,
                "gain_pct":           row.get("Change %", ""),
                "reason":             "No trigger",
                "buy_trigger_pct":    row.get("Buy Trigger %", ""),
                "sell_target_price":  row.get("Sell Target ₹", ""),
            })

    _append_rows(log_rows)
    log.info(f"Run {run_id} logged {len(log_rows)} rows — "
             f"{len(trade_plan['plan'])} BUY, "
             f"{len([r for r in log_rows if 'SELL' in r['action']])} SELL, "
             f"{len([r for r in log_rows if r['action'] == 'HOLD'])} HOLD")

    return {
        "run_id":      run_id,
        "buy_plan":    trade_plan,
        "sell_df":     df_sell,
        "signals_df":  df_signals,
        "log_rows":    len(log_rows),
        "errors":      p1["errors"],
    }


def read_log(n_days: int = 7) -> "pd.DataFrame":
    """Read the paper trade log and return as DataFrame (last n_days)."""
    import pandas as pd
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=n_days)
    return df[df["date"] >= cutoff].sort_values(["date", "time"], ascending=False)


def daily_summary(log_df: "pd.DataFrame") -> dict:
    """
    Given today's log rows, compute hypothetical P&L stats.
    (Actual P&L needs next-day closing price — this shows signal counts.)
    """
    import pandas as pd
    today_str = date.today().isoformat()
    today_df  = log_df[log_df["date"].astype(str).str.startswith(today_str)] if not log_df.empty else log_df

    if today_df.empty:
        return {}

    buy_df  = today_df[today_df["action"] == "BUY"]
    sell_df = today_df[today_df["action"].str.contains("SELL", na=False)]

    return {
        "buy_signals":          len(buy_df["symbol"].unique()),
        "sell_signals":         len(sell_df["symbol"].unique()),
        "hypothetical_deployed": buy_df["amount"].sum(),
        "hypothetical_sold":     sell_df["amount"].sum(),
        "runs_today":            today_df["run_id"].nunique(),
    }


# ── Scheduler (run as __main__) ────────────────────────────────────────────────

def run_scheduler(api, excel_path: str = "stock_config.xlsx",
                  total_budget: float = 120_000):
    """
    Blocking loop — runs run_once() every 15 min during market hours.
    Call this from the terminal:  python -m trading.phase4
    """
    log.info("Paper trading scheduler started. Watching 20 stocks every 15 min.")
    log.info(f"Market hours: {MARKET_OPEN[0]:02d}:{MARKET_OPEN[1]:02d} – "
             f"{MARKET_CLOSE[0]:02d}:{MARKET_CLOSE[1]:02d} IST")

    while True:
        now = _ist_now()

        if _is_market_open():
            try:
                result = run_once(api, excel_path, total_budget)
                buys  = len(result["buy_plan"]["plan"])
                sells = sum(1 for r in result["log_rows"] if isinstance(result.get("log_rows"), int))
                log.info(f"Cycle complete — next run in 15 min")
            except Exception as e:
                log.error(f"Cycle failed: {e}")
        else:
            if now.weekday() >= 5:
                log.info("Weekend — market closed. Sleeping 1 hour.")
                time.sleep(3600)
                continue
            elif (now.hour, now.minute) < MARKET_OPEN:
                wait_sec = (MARKET_OPEN[0] * 60 + MARKET_OPEN[1] - now.hour * 60 - now.minute) * 60
                log.info(f"Pre-market — waiting {wait_sec // 60} min until open.")
                time.sleep(min(wait_sec, 900))
                continue
            else:
                log.info("Market closed for today. Sleeping until tomorrow.")
                time.sleep(3600)
                continue

        time.sleep(INTERVAL_SEC)
