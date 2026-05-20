"""
Phase 2 — Sell Signal Engine

Logic:
  For every stock you hold (qty > 0, avg_buy_price > 0):

    Tier-1 sell (half position):
      current_price >= avg_buy_price * (1 + sell_target_pct / 100)
      → Sell 50% of qty to lock in profit while keeping upside exposure

    Tier-2 sell (full position):
      current_price >= avg_buy_price * (1 + sell_target_pct * 1.5 / 100)
      → Sell remaining 50% at 1.5× the base target

    Example — CIPLA bought at ₹1400, sell_target_pct = 5%:
      Tier-1 trigger : ₹1400 × 1.05  = ₹1470  → sell half
      Tier-2 trigger : ₹1400 × 1.075 = ₹1505  → sell rest

  Why two tiers?
    Selling everything at once means missing further upside.
    Selling in halves locks in guaranteed profit while letting
    the remaining shares ride if the stock keeps rising.

  Override: if user sets partial_sell=False in config, full qty sold at Tier-1.
"""

import pandas as pd
from .stock_master import STOCK_LIST, STOCK_MAP
from .phase1 import load_holdings


def compute_sell_signals(
    ltp_map: dict[str, float],
    excel_path: str = "stock_config.xlsx",
    partial_sell: bool = True,
) -> pd.DataFrame:
    """
    Generate sell recommendations for all held stocks.

    Args:
        ltp_map      : {symbol: current_ltp}  — from Phase 1 fetch
        excel_path   : path to stock_config.xlsx (reads My Holdings)
        partial_sell : if True, sell in 2 tiers; if False, sell full qty at Tier-1

    Returns:
        DataFrame with columns:
          Stock, Symbol, Qty Held, Avg Buy ₹, LTP ₹,
          Gain %, Tier-1 Target ₹, Tier-2 Target ₹,
          Sell Qty, Sell Value ₹, Action
    """
    holdings = load_holdings(excel_path)
    rows = []

    for stock in STOCK_LIST:
        sym     = stock["symbol"]
        holding = holdings.get(sym)
        ltp     = ltp_map.get(sym)

        if not holding or not ltp:
            continue

        qty       = holding["qty"]
        avg_buy   = holding["avg_buy_price"]
        sell_pct  = stock["sell_target_pct"]

        if qty <= 0 or avg_buy <= 0:
            continue

        tier1_price = round(avg_buy * (1 + sell_pct / 100),         2)
        tier2_price = round(avg_buy * (1 + sell_pct * 1.5 / 100),   2)
        gain_pct    = round((ltp - avg_buy) / avg_buy * 100,         2)

        action    = "HOLD"
        sell_qty  = 0

        # Hard rule: NEVER sell at a loss. If LTP <= avg_buy, always HOLD
        # regardless of any other condition. Profit is measured from avg buy price.
        if ltp <= avg_buy:
            rows.append({
                "Stock": stock["name"], "Symbol": sym, "Category": stock["category"],
                "Qty Held": qty, "Avg Buy ₹": avg_buy, "LTP ₹": ltp,
                "Gain %": gain_pct, "Tier-1 Target ₹": tier1_price,
                "Tier-2 Target ₹": tier2_price, "Sell Qty": 0,
                "Sell Value ₹": 0, "Action": "HOLD (at loss — waiting for recovery)",
            })
            continue

        if ltp >= tier2_price and partial_sell:
            action   = f"SELL FULL (Tier-2: +{sell_pct * 1.5:.1f}%)"
            sell_qty = qty
        elif ltp >= tier1_price:
            if partial_sell:
                action   = f"SELL HALF (Tier-1: +{sell_pct:.1f}%)"
                sell_qty = max(1, qty // 2)
            else:
                action   = f"SELL ALL (Target: +{sell_pct:.1f}%)"
                sell_qty = qty

        sell_value = round(sell_qty * ltp, 2) if sell_qty > 0 else 0

        rows.append({
            "Stock":          stock["name"],
            "Symbol":         sym,
            "Category":       stock["category"],
            "Qty Held":       qty,
            "Avg Buy ₹":      avg_buy,
            "LTP ₹":          ltp,
            "Gain %":         gain_pct,
            "Tier-1 Target ₹": tier1_price,
            "Tier-2 Target ₹": tier2_price,
            "Sell Qty":       sell_qty,
            "Sell Value ₹":   sell_value,
            "Action":         action,
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not df.empty:
        # Sort: active sell actions first, then by gain descending
        df["_priority"] = df["Action"].apply(lambda x: 0 if "SELL" in x else 1)
        df = df.sort_values(["_priority", "Gain %"], ascending=[True, False])
        df = df.drop(columns=["_priority"])

    return df


def sell_summary(df: pd.DataFrame) -> dict:
    """Return aggregate stats from the sell signal DataFrame."""
    if df.empty:
        return {"total_sell_value": 0, "sell_count": 0, "hold_count": 0}

    sell_df = df[df["Action"].str.contains("SELL", na=False)]
    return {
        "total_sell_value": sell_df["Sell Value ₹"].sum(),
        "sell_count":       len(sell_df),
        "hold_count":       len(df) - len(sell_df),
    }
