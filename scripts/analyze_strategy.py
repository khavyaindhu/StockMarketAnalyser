#!/usr/bin/env python3
"""
Run the historical strategy analyzer from the terminal.

Usage:
    python scripts/analyze_strategy.py
    python scripts/analyze_strategy.py --budget 500000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trading.strategy_analyzer import (
    DEFAULT_HISTORY_CSV,
    analyze_strategy,
    load_history,
    portfolio_summary,
)


OUT_DIR = ROOT / "data" / "historical" / "daily"
RECOMMENDATIONS_CSV = OUT_DIR / "strategy_recommendations.csv"
ALL_BACKTESTS_CSV = OUT_DIR / "strategy_backtest_grid.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze historical buy/sell strategy settings.")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY_CSV), help="Combined historical CSV path.")
    parser.add_argument("--budget", type=float, default=500_000, help="Total paper/deployable budget.")
    parser.add_argument("--stuck-days", type=int, default=180, help="Holding days after which capital is treated as stuck.")
    args = parser.parse_args()

    history = load_history(ROOT / args.history if not Path(args.history).is_absolute() else args.history)
    recommendations, all_tests = analyze_strategy(
        history,
        total_budget=args.budget,
        stuck_days=args.stuck_days,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recommendations.to_csv(RECOMMENDATIONS_CSV, index=False)
    all_tests.to_csv(ALL_BACKTESTS_CSV, index=False)

    summary = portfolio_summary(recommendations, total_budget=args.budget)
    print("Historical strategy analysis complete.")
    print(f"  Recommendations: {RECOMMENDATIONS_CSV}")
    print(f"  Full grid       : {ALL_BACKTESTS_CSV}")
    if summary:
        print(f"  Stocks analyzed : {summary['stocks']}")
        print(f"  Avg hit rate    : {summary['avg_hit_rate_pct']}%")
        print(f"  Avg annual return: {summary['avg_annual_return_pct']}%")
        print(f"  Stuck positions : {summary['total_stuck_positions']}")
        print(f"  Worst drawdown  : {summary['worst_drawdown_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
