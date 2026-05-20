"""
Phase 5 — Paper Portfolio Tracker

Reads the Phase 4 paper_trade_log.csv and simulates a virtual portfolio:
  - BUY rows  → open a paper position at signal_price × qty
  - SELL rows → close the position, book profit/loss
  - HOLD rows → ignored for portfolio state

State is rebuilt fresh from the log on every call (no separate state file)
so it is always consistent with the log.

Portfolio metrics:
  - Starting cash    : configurable (default ₹1,50,000)
  - Current cash     : starting − total deployed + total sell proceeds
  - Open positions   : {symbol: {qty, entry_price, current_value, unrealised_pnl}}
  - Closed trades    : list of completed round-trips with realised P&L
  - Portfolio value  : cash + sum of current open position values
"""

import os
import pandas as pd
from datetime import date

LOG_FILE = os.path.join("logs", "paper_trade_log.csv")


def _load_log() -> pd.DataFrame:
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["signal_price"] = pd.to_numeric(df["signal_price"], errors="coerce")
    df["qty"]          = pd.to_numeric(df["qty"],          errors="coerce").fillna(0).astype(int)
    df["amount"]       = pd.to_numeric(df["amount"],       errors="coerce").fillna(0)
    return df.sort_values(["date", "time"]).reset_index(drop=True)


def build_portfolio(
    starting_cash: float = 150_000,
    ltp_map: dict[str, float] | None = None,
) -> dict:
    """
    Rebuild the paper portfolio from the full log.

    Args:
        starting_cash : virtual cash at start (default ₹1,50,000)
        ltp_map       : {symbol: current_ltp} for unrealised P&L calculation.
                        If None, unrealised P&L shows as None.

    Returns dict with keys:
        cash, open_positions, closed_trades, realised_pnl, unrealised_pnl,
        portfolio_value, trade_count, win_count, loss_count, log_df
    """
    df = _load_log()
    if df.empty:
        return _empty_portfolio(starting_cash)

    cash = starting_cash
    # {symbol: [{"qty": int, "entry_price": float, "date": str, "run_id": str}]}
    positions: dict[str, list[dict]] = {}
    closed_trades: list[dict] = []

    for _, row in df.iterrows():
        action = str(row.get("action", "")).upper()
        sym    = str(row.get("symbol", "")).upper()
        qty    = int(row.get("qty", 0))
        price  = row.get("signal_price")
        amount = row.get("amount", 0)
        dt     = str(row.get("date", ""))[:10]
        run_id = str(row.get("run_id", ""))

        if action == "BUY" and qty > 0 and price and price > 0:
            cash -= amount
            if sym not in positions:
                positions[sym] = []
            positions[sym].append({
                "qty":         qty,
                "entry_price": float(price),
                "entry_date":  dt,
                "run_id":      run_id,
                "stock":       str(row.get("stock", sym)),
                "category":    str(row.get("category", "")),
            })

        elif "SELL" in action and qty > 0 and price and price > 0:
            cash += amount
            remaining_qty = qty
            sym_lots = positions.get(sym, [])

            while remaining_qty > 0 and sym_lots:
                lot = sym_lots[0]
                close_qty = min(remaining_qty, lot["qty"])
                entry_px  = lot["entry_price"]
                realised  = round((float(price) - entry_px) * close_qty, 2)

                closed_trades.append({
                    "Stock":        lot["stock"],
                    "Symbol":       sym,
                    "Category":     lot["category"],
                    "Entry Date":   lot["entry_date"],
                    "Exit Date":    dt,
                    "Qty":          close_qty,
                    "Entry Price ₹": entry_px,
                    "Exit Price ₹": float(price),
                    "Realised P&L ₹": realised,
                    "Return %":     round((float(price) - entry_px) / entry_px * 100, 2),
                })

                lot["qty"] -= close_qty
                remaining_qty -= close_qty
                if lot["qty"] == 0:
                    sym_lots.pop(0)

            if sym_lots:
                positions[sym] = sym_lots
            else:
                positions.pop(sym, None)

    # ── Build open positions summary ───────────────────────────────────────────
    open_rows = []
    total_unrealised = 0.0

    for sym, lots in positions.items():
        for lot in lots:
            if lot["qty"] <= 0:
                continue
            ltp       = (ltp_map or {}).get(sym)
            cur_val   = round(ltp * lot["qty"], 2)        if ltp else None
            unreal    = round((ltp - lot["entry_price"]) * lot["qty"], 2) if ltp else None
            unreal_pct = round((ltp - lot["entry_price"]) / lot["entry_price"] * 100, 2) if ltp else None
            if unreal is not None:
                total_unrealised += unreal

            open_rows.append({
                "Stock":           lot["stock"],
                "Symbol":          sym,
                "Category":        lot["category"],
                "Qty":             lot["qty"],
                "Entry Price ₹":   lot["entry_price"],
                "Entry Date":      lot["entry_date"],
                "LTP ₹":           ltp,
                "Current Value ₹": cur_val,
                "Unrealised P&L ₹": unreal,
                "Return %":        unreal_pct,
            })

    realised_total = sum(t["Realised P&L ₹"] for t in closed_trades)
    deployed       = sum(r["Current Value ₹"] for r in open_rows if r["Current Value ₹"])
    portfolio_val  = round(cash + deployed, 2)

    win_count  = sum(1 for t in closed_trades if t["Realised P&L ₹"] > 0)
    loss_count = sum(1 for t in closed_trades if t["Realised P&L ₹"] < 0)

    return {
        "starting_cash":   starting_cash,
        "cash":            round(cash, 2),
        "open_positions":  pd.DataFrame(open_rows) if open_rows else pd.DataFrame(),
        "closed_trades":   pd.DataFrame(closed_trades) if closed_trades else pd.DataFrame(),
        "realised_pnl":    round(realised_total, 2),
        "unrealised_pnl":  round(total_unrealised, 2),
        "portfolio_value": portfolio_val,
        "trade_count":     len(closed_trades),
        "win_count":       win_count,
        "loss_count":      loss_count,
        "log_df":          df,
    }


def _empty_portfolio(starting_cash: float) -> dict:
    return {
        "starting_cash":   starting_cash,
        "cash":            starting_cash,
        "open_positions":  pd.DataFrame(),
        "closed_trades":   pd.DataFrame(),
        "realised_pnl":    0.0,
        "unrealised_pnl":  0.0,
        "portfolio_value": starting_cash,
        "trade_count":     0,
        "win_count":       0,
        "loss_count":      0,
        "log_df":          pd.DataFrame(),
    }


def daily_pnl_series(log_df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame with columns [date, daily_realised_pnl, cumulative_pnl]
    aggregated from closed-trade P&L grouped by exit date.
    Useful for plotting a P&L curve.
    """
    if log_df.empty:
        return pd.DataFrame()
    sells = log_df[log_df["action"].str.contains("SELL", na=False)].copy()
    if sells.empty:
        return pd.DataFrame()
    sells["gain_pct"] = pd.to_numeric(sells.get("gain_pct", pd.Series(dtype=float)), errors="coerce")
    sells["amount"]   = pd.to_numeric(sells["amount"], errors="coerce").fillna(0)
    daily = sells.groupby("date")["amount"].sum().reset_index()
    daily.columns = ["date", "sell_proceeds"]
    daily = daily.sort_values("date")
    daily["cumulative_proceeds"] = daily["sell_proceeds"].cumsum()
    return daily
