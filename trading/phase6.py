"""
Phase 6 — Strategy Performance Analytics

Analyses the paper trade log to answer:
  1. Signal accuracy  — for BUY signals, did the price actually rise?
  2. Win rate         — % of closed paper trades that made money
  3. Avg return       — mean return % across all closed trades
  4. Category edge    — which sectors produce the best signals
  5. Time-in-trade    — how long positions are held before exit
  6. Daily P&L curve  — cumulative realised P&L over calendar days

All functions work from the paper_trade_log.csv built by Phase 4.
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime


LOG_FILE = os.path.join("logs", "paper_trade_log.csv")


def _load_log() -> pd.DataFrame:
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        return df
    df["date"]         = pd.to_datetime(df["date"],         errors="coerce")
    df["signal_price"] = pd.to_numeric(df["signal_price"],  errors="coerce")
    df["qty"]          = pd.to_numeric(df["qty"],           errors="coerce").fillna(0)
    df["amount"]       = pd.to_numeric(df["amount"],        errors="coerce").fillna(0)
    df["gain_pct"]     = pd.to_numeric(df["gain_pct"],      errors="coerce")
    return df.sort_values(["date", "time"]).reset_index(drop=True)


# ── 1. Signal summary ──────────────────────────────────────────────────────────

def signal_summary(df: pd.DataFrame | None = None) -> dict:
    """
    Count BUY / SELL / HOLD signals, total runs, date range.
    """
    if df is None:
        df = _load_log()
    if df.empty:
        return {}

    buys  = df[df["action"] == "BUY"]
    sells = df[df["action"].str.contains("SELL", na=False)]
    holds = df[df["action"] == "HOLD"]

    return {
        "total_runs":      df["run_id"].nunique(),
        "date_range":      f"{df['date'].min().date()} → {df['date'].max().date()}",
        "buy_signals":     len(buys),
        "sell_signals":    len(sells),
        "hold_signals":    len(holds),
        "unique_buy_syms": buys["symbol"].nunique(),
        "total_deployed":  buys["amount"].sum(),
        "total_sold":      sells["amount"].sum(),
    }


# ── 2. Win / loss stats from closed paper trades ───────────────────────────────

def closed_trade_stats(closed_df: pd.DataFrame) -> dict:
    """
    Given the closed_trades DataFrame from phase5.build_portfolio(),
    compute win rate, avg return, best/worst trade.
    """
    if closed_df.empty:
        return {}

    pnl   = closed_df["Realised P&L ₹"]
    ret   = closed_df["Return %"]
    wins  = closed_df[pnl > 0]
    losses= closed_df[pnl < 0]

    return {
        "total_trades":  len(closed_df),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate_pct":  round(len(wins) / len(closed_df) * 100, 1) if len(closed_df) else 0,
        "avg_return_pct":round(ret.mean(), 2),
        "avg_win_pct":   round(wins["Return %"].mean(), 2)   if not wins.empty   else 0,
        "avg_loss_pct":  round(losses["Return %"].mean(), 2) if not losses.empty else 0,
        "total_realised":round(pnl.sum(), 2),
        "best_trade":    closed_df.loc[pnl.idxmax()].to_dict() if not closed_df.empty else {},
        "worst_trade":   closed_df.loc[pnl.idxmin()].to_dict() if not closed_df.empty else {},
        "profit_factor": round(wins[pnl > 0]["Realised P&L ₹"].sum() /
                               abs(losses["Realised P&L ₹"].sum()), 2)
                         if not losses.empty and losses["Realised P&L ₹"].sum() != 0 else None,
    }


# ── 3. Category (sector) breakdown ────────────────────────────────────────────

def category_breakdown(df: pd.DataFrame | None = None,
                       closed_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Per-category signal counts and average realised return.
    """
    if df is None:
        df = _load_log()

    rows = []
    if not df.empty:
        buy_df = df[df["action"] == "BUY"]
        for cat, grp in buy_df.groupby("category"):
            rows.append({
                "Category":       cat,
                "BUY signals":    len(grp),
                "Symbols traded": grp["symbol"].nunique(),
                "Total deployed ₹": round(grp["amount"].sum(), 0),
            })

    cat_df = pd.DataFrame(rows)

    if closed_df is not None and not closed_df.empty:
        cat_pnl = closed_df.groupby("Category").agg(
            Trades=("Realised P&L ₹", "count"),
            Win_Rate=("Return %",      lambda x: round((x > 0).mean() * 100, 1)),
            Avg_Return=("Return %",    lambda x: round(x.mean(), 2)),
            Total_PnL=("Realised P&L ₹", lambda x: round(x.sum(), 2)),
        ).reset_index()
        cat_pnl.columns = ["Category", "Closed Trades", "Win Rate %", "Avg Return %", "Total P&L ₹"]

        if not cat_df.empty:
            cat_df = cat_df.merge(cat_pnl, on="Category", how="left")
        else:
            cat_df = cat_pnl

    return cat_df


# ── 4. Daily P&L curve ─────────────────────────────────────────────────────────

def daily_pnl_curve(closed_df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns DataFrame [date, daily_pnl, cumulative_pnl] from closed trades.
    Use for a line chart of portfolio growth.
    """
    if closed_df.empty:
        return pd.DataFrame()

    closed_df = closed_df.copy()
    closed_df["Exit Date"] = pd.to_datetime(closed_df["Exit Date"], errors="coerce")
    daily = (
        closed_df.groupby("Exit Date")["Realised P&L ₹"]
        .sum()
        .reset_index()
        .rename(columns={"Exit Date": "Date", "Realised P&L ₹": "Daily P&L ₹"})
        .sort_values("Date")
    )
    daily["Cumulative P&L ₹"] = daily["Daily P&L ₹"].cumsum()
    return daily


# ── 5. Top / bottom performing signals ────────────────────────────────────────

def top_signals(closed_df: pd.DataFrame, n: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (top_n, bottom_n) closed trades by Return %."""
    if closed_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    sdf = closed_df.sort_values("Return %", ascending=False)
    return sdf.head(n), sdf.tail(n)


# ── 6. Signal accuracy (requires current LTP) ─────────────────────────────────

def signal_accuracy(df: pd.DataFrame | None = None,
                    ltp_map: dict[str, float] | None = None) -> pd.DataFrame:
    """
    For each BUY signal, compare signal_price vs current LTP.
    Returns per-symbol accuracy table.
    Only meaningful when ltp_map is provided (during market hours).
    """
    if df is None:
        df = _load_log()
    if df.empty or not ltp_map:
        return pd.DataFrame()

    buy_df = df[df["action"] == "BUY"].copy()
    if buy_df.empty:
        return pd.DataFrame()

    latest = buy_df.sort_values("date").groupby("symbol").last().reset_index()
    rows = []
    for _, row in latest.iterrows():
        sym      = row["symbol"]
        entry_px = row["signal_price"]
        ltp      = ltp_map.get(sym)
        if not ltp or not entry_px:
            continue
        gain = round((ltp - entry_px) / entry_px * 100, 2)
        rows.append({
            "Symbol":          sym,
            "Stock":           row.get("stock", sym),
            "Signal Price ₹":  entry_px,
            "Current LTP ₹":  ltp,
            "Gain Since Signal %": gain,
            "Signal Date":     str(row["date"])[:10],
            "Correct?":        "✅ Yes" if gain > 0 else "❌ No",
        })

    return pd.DataFrame(rows).sort_values("Gain Since Signal %", ascending=False)


# ── Full analytics report ──────────────────────────────────────────────────────

def full_report(ltp_map: dict[str, float] | None = None,
                starting_cash: float = 150_000) -> dict:
    """
    Convenience wrapper: loads log, builds portfolio, computes all analytics.
    Returns everything needed by the Streamlit dashboard.
    """
    from .phase5 import build_portfolio
    portfolio = build_portfolio(starting_cash=starting_cash, ltp_map=ltp_map)
    df        = portfolio["log_df"]
    closed_df = portfolio["closed_trades"]

    return {
        "portfolio":        portfolio,
        "signal_summary":   signal_summary(df),
        "trade_stats":      closed_trade_stats(closed_df),
        "category_df":      category_breakdown(df, closed_df),
        "pnl_curve":        daily_pnl_curve(closed_df),
        "top5":             top_signals(closed_df, 5)[0],
        "bottom5":          top_signals(closed_df, 5)[1],
        "accuracy_df":      signal_accuracy(df, ltp_map),
    }
