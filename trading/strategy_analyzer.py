"""
Historical strategy analyzer for the paper-trading rules.

The model is intentionally conservative:
  - one open position per stock at a time
  - buy on a daily dip from previous close
  - sell only when the configured profit target is reached
  - mark still-open positions as capital stuck, not as wins
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .stock_master import STOCK_LIST, STOCK_MAP


DEFAULT_HISTORY_CSV = Path("data") / "historical" / "daily" / "historical_daily_combined.csv"
DEFAULT_BUY_DIPS = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
DEFAULT_SELL_TARGETS = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0]
STUCK_DAYS = 180


@dataclass(frozen=True)
class BacktestConfig:
    buy_dip_pct: float
    sell_target_pct: float
    capital_per_trade: float
    stuck_days: int = STUCK_DAYS


def _pick_column(columns: Iterable[str], candidates: list[str], contains: str | None = None) -> str:
    cols = list(columns)
    normal = {str(c).strip().lower(): c for c in cols}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normal:
            return normal[key]
    if contains:
        needle = contains.lower()
        for col in cols:
            if needle in str(col).lower():
                return col
    raise KeyError(f"Could not find required column. Tried: {', '.join(candidates)}")


def load_history(path: str | Path = DEFAULT_HISTORY_CSV) -> pd.DataFrame:
    """Load combined Angel One daily history using flexible column matching."""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Historical CSV not found: {csv_path}")

    raw = pd.read_csv(csv_path)
    symbol_col = _pick_column(raw.columns, ["NSE Symbol", "Symbol"], contains="symbol")
    date_col = _pick_column(raw.columns, ["Date"], contains="date")
    close_col = _pick_column(raw.columns, ["Close", "Close (Rs)", "Close (₹)", "Close (â‚¹)"], contains="close")
    stock_col = None
    category_col = None
    try:
        stock_col = _pick_column(raw.columns, ["Stock Name", "Stock"], contains="stock")
    except KeyError:
        pass
    try:
        category_col = _pick_column(raw.columns, ["Category"], contains="category")
    except KeyError:
        pass

    df = pd.DataFrame({
        "Symbol": raw[symbol_col].astype(str).str.strip().str.upper(),
        "Date": pd.to_datetime(raw[date_col], errors="coerce"),
        "Close": pd.to_numeric(raw[close_col], errors="coerce"),
    })
    if stock_col:
        df["Stock"] = raw[stock_col].astype(str)
    else:
        df["Stock"] = df["Symbol"].map(lambda s: STOCK_MAP.get(s, {}).get("name", s))
    if category_col:
        df["Category"] = raw[category_col].astype(str)
    else:
        df["Category"] = df["Symbol"].map(lambda s: STOCK_MAP.get(s, {}).get("category", ""))

    df = df.dropna(subset=["Date", "Close"])
    df = df[df["Close"] > 0].copy()
    df = df.sort_values(["Symbol", "Date"]).reset_index(drop=True)
    return df


def _simulate_symbol(symbol_df: pd.DataFrame, cfg: BacktestConfig) -> tuple[list[dict], dict | None]:
    """Return closed trades and the final open trade, if any."""
    rows = symbol_df.sort_values("Date").reset_index(drop=True)
    if len(rows) < 2:
        return [], None

    closed: list[dict] = []
    open_trade: dict | None = None

    for i in range(1, len(rows)):
        prev_close = float(rows.loc[i - 1, "Close"])
        close = float(rows.loc[i, "Close"])
        date = rows.loc[i, "Date"]

        if open_trade is None:
            dip_pct = (close - prev_close) / prev_close * 100 if prev_close else 0
            if dip_pct <= -cfg.buy_dip_pct:
                qty = int(cfg.capital_per_trade // close)
                if qty <= 0:
                    continue
                open_trade = {
                    "Entry Date": date,
                    "Entry Price": close,
                    "Qty": qty,
                    "Invested": round(qty * close, 2),
                    "Buy Dip %": round(dip_pct, 4),
                    "Lowest Close": close,
                    "Lowest Date": date,
                }
            continue

        if close < open_trade["Lowest Close"]:
            open_trade["Lowest Close"] = close
            open_trade["Lowest Date"] = date

        target_price = open_trade["Entry Price"] * (1 + cfg.sell_target_pct / 100)
        if close >= target_price:
            holding_days = int((date - open_trade["Entry Date"]).days)
            pnl = (close - open_trade["Entry Price"]) * open_trade["Qty"]
            drawdown_pct = (
                (open_trade["Lowest Close"] - open_trade["Entry Price"])
                / open_trade["Entry Price"]
                * 100
            )
            closed.append({
                **open_trade,
                "Exit Date": date,
                "Exit Price": close,
                "Holding Days": holding_days,
                "P&L": round(pnl, 2),
                "Return %": round((close - open_trade["Entry Price"]) / open_trade["Entry Price"] * 100, 4),
                "Max Drawdown %": round(drawdown_pct, 4),
                "Status": "Closed",
            })
            open_trade = None

    if open_trade is not None:
        final_close = float(rows.iloc[-1]["Close"])
        final_date = rows.iloc[-1]["Date"]
        holding_days = int((final_date - open_trade["Entry Date"]).days)
        pnl = (final_close - open_trade["Entry Price"]) * open_trade["Qty"]
        drawdown_pct = (
            (open_trade["Lowest Close"] - open_trade["Entry Price"])
            / open_trade["Entry Price"]
            * 100
        )
        open_trade = {
            **open_trade,
            "Last Date": final_date,
            "Last Close": final_close,
            "Holding Days": holding_days,
            "Unrealised P&L": round(pnl, 2),
            "Unrealised Return %": round((final_close - open_trade["Entry Price"]) / open_trade["Entry Price"] * 100, 4),
            "Max Drawdown %": round(drawdown_pct, 4),
            "Status": "Open",
        }

    return closed, open_trade


def backtest_symbol(symbol_df: pd.DataFrame, cfg: BacktestConfig) -> dict:
    """Backtest one symbol and return aggregate metrics for one parameter pair."""
    symbol = str(symbol_df["Symbol"].iloc[0])
    stock = str(symbol_df["Stock"].iloc[0])
    category = str(symbol_df["Category"].iloc[0])
    start_date = symbol_df["Date"].min()
    end_date = symbol_df["Date"].max()
    years = max((end_date - start_date).days / 365.25, 0.01)

    closed, open_trade = _simulate_symbol(symbol_df, cfg)
    closed_df = pd.DataFrame(closed)
    total_trades = len(closed) + (1 if open_trade else 0)
    closed_pnl = float(closed_df["P&L"].sum()) if not closed_df.empty else 0.0
    open_pnl = float(open_trade["Unrealised P&L"]) if open_trade else 0.0
    total_pnl = closed_pnl + open_pnl
    closed_hold = closed_df["Holding Days"] if not closed_df.empty else pd.Series(dtype=float)
    all_hold = list(closed_hold.astype(float)) + ([float(open_trade["Holding Days"])] if open_trade else [])
    drawdowns = list(closed_df["Max Drawdown %"].astype(float)) if not closed_df.empty else []
    if open_trade:
        drawdowns.append(float(open_trade["Max Drawdown %"]))

    hit_rate = (len(closed) / total_trades * 100) if total_trades else 0.0
    avg_holding = float(closed_hold.mean()) if not closed_hold.empty else 0.0
    max_holding = max(all_hold) if all_hold else 0.0
    max_drawdown = min(drawdowns) if drawdowns else 0.0
    open_positions = 1 if open_trade else 0
    stuck_positions = 1 if open_trade and open_trade["Holding Days"] >= cfg.stuck_days else 0
    capital_stuck = float(open_trade["Invested"]) if open_trade else 0.0
    return_pct = total_pnl / cfg.capital_per_trade * 100 if cfg.capital_per_trade else 0.0
    annual_return_pct = return_pct / years

    score = (
        annual_return_pct
        - (100 - hit_rate) * 0.12
        - max(0.0, avg_holding - 90) * 0.03
        - max(0.0, max_holding - cfg.stuck_days) * 0.015
        - abs(min(0.0, max_drawdown)) * 0.08
        - stuck_positions * 8
    )

    return {
        "Stock": stock,
        "Symbol": symbol,
        "Category": category,
        "Buy Dip %": cfg.buy_dip_pct,
        "Sell Target %": cfg.sell_target_pct,
        "Closed Trades": len(closed),
        "Open Positions": open_positions,
        "Stuck Positions": stuck_positions,
        "Target Hit Rate %": round(hit_rate, 2),
        "Avg Holding Days": round(avg_holding, 1),
        "Max Holding Days": round(max_holding, 1),
        "Max Drawdown %": round(max_drawdown, 2),
        "Closed P&L Rs": round(closed_pnl, 2),
        "Open P&L Rs": round(open_pnl, 2),
        "Total P&L Rs": round(total_pnl, 2),
        "Total Return %": round(return_pct, 2),
        "Annual Return %": round(annual_return_pct, 2),
        "Capital Stuck Rs": round(capital_stuck, 2),
        "Score": round(score, 2),
        "Data Start": start_date.date().isoformat(),
        "Data End": end_date.date().isoformat(),
    }


def analyze_strategy(
    history: pd.DataFrame,
    total_budget: float = 500_000,
    buy_dips: Iterable[float] | None = None,
    sell_targets: Iterable[float] | None = None,
    stuck_days: int = STUCK_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (recommendations, all_backtests)."""
    if history.empty:
        return pd.DataFrame(), pd.DataFrame()

    buy_dips = list(buy_dips or DEFAULT_BUY_DIPS)
    sell_targets = list(sell_targets or DEFAULT_SELL_TARGETS)
    symbols = sorted(history["Symbol"].dropna().unique())
    capital_per_trade = float(total_budget) / max(len(symbols), 1)

    results: list[dict] = []
    for symbol, symbol_df in history.groupby("Symbol", sort=True):
        for buy_dip in buy_dips:
            for sell_target in sell_targets:
                cfg = BacktestConfig(
                    buy_dip_pct=float(buy_dip),
                    sell_target_pct=float(sell_target),
                    capital_per_trade=capital_per_trade,
                    stuck_days=int(stuck_days),
                )
                results.append(backtest_symbol(symbol_df, cfg))

    all_tests = pd.DataFrame(results)
    if all_tests.empty:
        return pd.DataFrame(), all_tests

    idx = all_tests.groupby("Symbol")["Score"].idxmax()
    recommendations = all_tests.loc[idx].copy().sort_values("Score", ascending=False)
    current_settings = {
        s["symbol"]: {
            "Current Buy Dip %": s["buy_dip_pct"],
            "Current Sell Target %": s["sell_target_pct"],
            "Max Capital Rs": s["max_capital"],
        }
        for s in STOCK_LIST
    }
    recommendations["Current Buy Dip %"] = recommendations["Symbol"].map(
        lambda s: current_settings.get(s, {}).get("Current Buy Dip %")
    )
    recommendations["Current Sell Target %"] = recommendations["Symbol"].map(
        lambda s: current_settings.get(s, {}).get("Current Sell Target %")
    )
    recommendations["Max Capital Rs"] = recommendations["Symbol"].map(
        lambda s: current_settings.get(s, {}).get("Max Capital Rs")
    )
    recommendations["Suggested Action"] = recommendations.apply(_suggest_action, axis=1)

    preferred_cols = [
        "Stock", "Symbol", "Category",
        "Current Buy Dip %", "Current Sell Target %",
        "Buy Dip %", "Sell Target %",
        "Score", "Annual Return %", "Total Return %",
        "Target Hit Rate %", "Closed Trades", "Open Positions", "Stuck Positions",
        "Avg Holding Days", "Max Holding Days", "Max Drawdown %",
        "Capital Stuck Rs", "Total P&L Rs", "Max Capital Rs", "Suggested Action",
    ]
    recommendations = recommendations[[c for c in preferred_cols if c in recommendations.columns]]
    return recommendations.reset_index(drop=True), all_tests.reset_index(drop=True)


def _suggest_action(row: pd.Series) -> str:
    open_positions = int(row.get("Open Positions", 0) or 0)
    stuck_positions = int(row.get("Stuck Positions", 0) or 0)
    hit_rate = float(row.get("Target Hit Rate %", 0) or 0)
    max_hold = float(row.get("Max Holding Days", 0) or 0)
    drawdown = float(row.get("Max Drawdown %", 0) or 0)

    if stuck_positions:
        return "Use cautiously: capital can stay stuck"
    if open_positions and max_hold > STUCK_DAYS:
        return "Review: open position held too long"
    if hit_rate >= 90 and max_hold <= 120 and drawdown >= -12:
        return "Strong candidate"
    if hit_rate >= 75 and max_hold <= STUCK_DAYS:
        return "Usable with monitoring"
    return "Conservative review needed"


def portfolio_summary(recommendations: pd.DataFrame, total_budget: float = 500_000) -> dict:
    if recommendations.empty:
        return {}
    return {
        "stocks": int(len(recommendations)),
        "budget": float(total_budget),
        "capital_per_stock": round(float(total_budget) / max(len(recommendations), 1), 2),
        "avg_annual_return_pct": round(float(recommendations["Annual Return %"].mean()), 2),
        "avg_hit_rate_pct": round(float(recommendations["Target Hit Rate %"].mean()), 2),
        "total_closed_trades": int(recommendations["Closed Trades"].sum()),
        "total_open_positions": int(recommendations["Open Positions"].sum()),
        "total_stuck_positions": int(recommendations["Stuck Positions"].sum()),
        "worst_drawdown_pct": round(float(recommendations["Max Drawdown %"].min()), 2),
        "capital_stuck": round(float(recommendations["Capital Stuck Rs"].sum()), 2),
    }
