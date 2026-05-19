"""
Phase 3 — Smart Capital Allocator

Logic:
  Takes all BUY signals from Phase 1 and decides HOW MUCH to invest in each,
  respecting three rules:

  Rule 1 — Daily Budget Cap
    Total capital available today = total_budget (e.g. ₹1,20,000)
    Never deploy more than the budget in one day.

  Rule 2 — Sector Concentration Limit
    Max 2 stocks from the same sector per day.
    Example: if Federal Bank, IDFC First, IndusInd all dip together,
    only the top 2 (by dip %) get capital. The third is skipped.
    Why? Banking sector risk is correlated — if one bank falls hard,
    others usually fall too (same macro reason). Putting ₹36K into
    3 banks is really just 1 concentrated bet.

  Rule 3 — Per-Stock Cap
    Each stock has a max_capital limit (from stock_master.py).
    Even if budget allows more, never exceed the per-stock cap.

  Ranking (best opportunities first):
    1. Biggest dip % (more dip = better entry price)
    2. Sector not already filled (diversification)
    3. Within same dip %, prefer lower max_capital stocks (more budget left)

  Output:
    A "Day Trade Plan" — list of stocks to buy, qty, amount, and
    the remaining undeployed cash.
"""

import pandas as pd
from .stock_master import STOCK_MAP

# Max stocks from any single sector per day
SECTOR_LIMIT = 2


def build_trade_plan(
    buy_signals: list[dict],
    total_budget: float = 120_000,
    sector_limit: int = SECTOR_LIMIT,
) -> dict:
    """
    Given a list of BUY signal dicts (from Phase 1 fetch_signals),
    allocate capital following the three rules above.

    Args:
        buy_signals  : list of signal dicts with keys:
                       Symbol, Stock, Category, ltp, Change %, max_capital
        total_budget : deployable cash today (excluding ₹30K reserve)
        sector_limit : max stocks per sector

    Returns:
        {
          "plan":      list of trade dicts (what to buy, qty, amount)
          "skipped":   list of dicts skipped due to sector/budget limits
          "deployed":  total ₹ allocated
          "remaining": undeployed ₹
          "summary":   human-readable explanation string
        }
    """
    if not buy_signals:
        return {
            "plan": [], "skipped": [], "deployed": 0,
            "remaining": total_budget,
            "summary": "No BUY signals today.",
        }

    # Sort by absolute dip descending (biggest dip = best opportunity)
    sorted_signals = sorted(
        buy_signals,
        key=lambda x: abs(x.get("Change %") or 0),
        reverse=True,
    )

    sector_count: dict[str, int] = {}
    plan          = []
    skipped       = []
    remaining     = total_budget

    for sig in sorted_signals:
        sym      = sig["Symbol"]
        sector   = sig.get("Category", "Other")
        ltp      = sig.get("ltp") or sig.get("LTP ₹") or 0
        max_cap  = sig.get("max_capital", 12000)

        # Rule 2: sector limit
        if sector_count.get(sector, 0) >= sector_limit:
            skipped.append({**sig, "skip_reason": f"Sector limit ({sector_limit} {sector} stocks already chosen)"})
            continue

        # Rule 1: budget exhausted
        if remaining <= 0:
            skipped.append({**sig, "skip_reason": "Daily budget exhausted"})
            continue

        # Rule 3: per-stock cap + available budget
        alloc_amount = min(max_cap, remaining)
        if alloc_amount < ltp:          # can't even buy 1 share
            skipped.append({**sig, "skip_reason": f"Insufficient budget for 1 share (LTP ₹{ltp:.0f})"})
            continue

        qty        = int(alloc_amount // ltp)
        actual_amt = round(qty * ltp, 2)

        plan.append({
            "Stock":       sig["Stock"],
            "Symbol":      sym,
            "Category":    sector,
            "LTP ₹":       round(ltp, 2),
            "Dip %":       sig.get("Change %"),
            "Buy Qty":     qty,
            "Amount ₹":    actual_amt,
            "Max Cap ₹":   max_cap,
        })

        remaining           -= actual_amt
        sector_count[sector] = sector_count.get(sector, 0) + 1

    deployed = total_budget - remaining

    # Human-readable summary
    lines = [f"Deploying ₹{deployed:,.0f} across {len(plan)} stock(s)."]
    for p in plan:
        lines.append(f"  • {p['Stock']} ({p['Symbol']}): {p['Buy Qty']} shares @ ₹{p['LTP ₹']} = ₹{p['Amount ₹']:,.0f}  [{p['Dip %']:+.2f}%]")
    if skipped:
        lines.append(f"Skipped {len(skipped)} signal(s):")
        for s in skipped:
            lines.append(f"  ✗ {s['Stock']}: {s.get('skip_reason', '—')}")
    lines.append(f"Undeployed cash: ₹{remaining:,.0f}")

    return {
        "plan":      plan,
        "skipped":   skipped,
        "deployed":  deployed,
        "remaining": round(remaining, 2),
        "summary":   "\n".join(lines),
    }


def plan_as_dataframe(plan: list[dict]) -> pd.DataFrame:
    if not plan:
        return pd.DataFrame()
    df = pd.DataFrame(plan)
    cols = ["Stock", "Symbol", "Category", "LTP ₹", "Dip %", "Buy Qty", "Amount ₹"]
    return df[[c for c in cols if c in df.columns]]
