"""
Phase 1 — Price fetch and signal generation.

For each of the 20 stocks:
  - Fetches live LTP + previous day's close via Angel One ltpData()
  - Calculates % change from previous close
  - Generates BUY signal if dip exceeds the configured threshold
  - Generates SELL signal if current price >= avg_buy_price * (1 + sell_target_pct/100)

Holdings (avg buy price + qty) are read from stock_config.xlsx → "My Holdings" sheet.
If the Excel isn't filled in yet, sell signals are skipped gracefully.
"""

import os
import pandas as pd
from datetime import datetime

from .stock_master import STOCK_LIST, lookup_tokens


# ── Holdings loader ────────────────────────────────────────────────────────────

def load_holdings(excel_path: str = "stock_config.xlsx") -> dict[str, dict]:
    """
    Read 'My Holdings' sheet from stock_config.xlsx.
    Returns {symbol: {qty, avg_buy_price}} for rows where qty > 0.
    """
    holdings = {}
    if not os.path.exists(excel_path):
        return holdings
    try:
        df = pd.read_excel(excel_path, sheet_name="My Holdings", header=0)
        # Columns: Stock Name, NSE Symbol, Qty Held, Avg Buy Price ₹, ...
        df.columns = [str(c).strip() for c in df.columns]
        sym_col = next((c for c in df.columns if "symbol" in c.lower()), None)
        qty_col = next((c for c in df.columns if "qty" in c.lower()), None)
        avg_col = next((c for c in df.columns if "avg" in c.lower() or "buy price" in c.lower()), None)
        if sym_col and qty_col and avg_col:
            for _, row in df.iterrows():
                sym = str(row[sym_col]).strip().upper()
                try:
                    qty = float(row[qty_col])
                    avg = float(row[avg_col])
                    if qty > 0 and avg > 0:
                        holdings[sym] = {"qty": int(qty), "avg_buy_price": avg}
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return holdings


# ── Capital allocator ──────────────────────────────────────────────────────────

def allocate_capital(buy_signals: list[dict], total_budget: float = 120000) -> list[dict]:
    """
    Given a list of BUY signal rows (sorted by dip%), allocate capital.

    Rules:
      - Max 4 stocks per day
      - Equal split across triggered stocks
      - Each allocation capped at stock's max_capital config
      - Reserve ₹30,000 always (not passed in here — caller controls budget)
    """
    if not buy_signals:
        return []

    top      = buy_signals[:4]           # pick top 4 by dip magnitude
    per_stock = round(total_budget / len(top), -2)  # round to nearest ₹100

    allocated = []
    for sig in top:
        alloc = min(per_stock, sig.get("max_capital", 15000))
        qty   = int(alloc // sig["ltp"]) if sig["ltp"] > 0 else 0
        allocated.append({**sig, "allocated_capital": alloc, "suggested_qty": qty})

    return allocated


# ── Main fetch function ────────────────────────────────────────────────────────

def fetch_signals(api, excel_path: str = "stock_config.xlsx") -> dict:
    """
    Fetch live prices for all 20 stocks and return buy/sell/hold signals.

    Returns:
        {
          "signals":      DataFrame — one row per stock with price + signal
          "buy_signals":  list of dicts for stocks in buy zone
          "sell_signals": list of dicts for stocks hitting sell target
          "errors":       list of (symbol, error_message)
          "fetched_at":   datetime string
        }
    """
    tokens   = lookup_tokens(api)
    holdings = load_holdings(excel_path)
    rows     = []
    errors   = []

    for stock in STOCK_LIST:
        sym       = stock["symbol"]
        tok_info  = tokens.get(sym, {})
        trading_sym = tok_info.get("trading_symbol", f"{sym}-EQ")
        token     = tok_info.get("token")
        holding   = holdings.get(sym, {})

        ltp = prev_close = None
        try:
            resp = api.ltpData("NSE", trading_sym, token or "")
            if resp and resp.get("status") and resp.get("data"):
                d         = resp["data"]
                ltp       = float(d.get("ltp")   or 0)
                prev_close = float(d.get("close") or 0)
        except Exception as e:
            errors.append((sym, str(e)))

        if not ltp or not prev_close:
            rows.append({
                "Stock":          stock["name"],
                "Symbol":         sym,
                "Category":       stock["category"],
                "LTP ₹":          None,
                "Prev Close ₹":   None,
                "Change %":       None,
                "Buy Trigger %":  -stock["buy_dip_pct"],
                "Avg Buy ₹":      holding.get("avg_buy_price"),
                "Qty Held":       holding.get("qty"),
                "Sell Target ₹":  None,
                "Signal":         "NO DATA",
                "max_capital":    stock["max_capital"],
            })
            continue

        change_pct    = (ltp - prev_close) / prev_close * 100
        avg_buy       = holding.get("avg_buy_price")
        qty_held      = holding.get("qty")
        sell_target_price = (avg_buy * (1 + stock["sell_target_pct"] / 100)) if avg_buy else None

        # ── Signal logic ───────────────────────────────────────────────────────
        signal = "HOLD"
        if change_pct <= -stock["buy_dip_pct"]:
            signal = "BUY"
        if avg_buy and ltp >= sell_target_price:
            signal = "SELL"
        # SELL takes priority over BUY if both conditions somehow met
        if avg_buy and ltp >= sell_target_price and change_pct <= -stock["buy_dip_pct"]:
            signal = "SELL"

        rows.append({
            "Stock":          stock["name"],
            "Symbol":         sym,
            "Category":       stock["category"],
            "LTP ₹":          round(ltp, 2),
            "Prev Close ₹":   round(prev_close, 2),
            "Change %":       round(change_pct, 2),
            "Buy Trigger %":  -stock["buy_dip_pct"],
            "Avg Buy ₹":      round(avg_buy, 2) if avg_buy else None,
            "Qty Held":       qty_held,
            "Sell Target ₹":  round(sell_target_price, 2) if sell_target_price else None,
            "Signal":         signal,
            "max_capital":    stock["max_capital"],
            "ltp":            ltp,
        })

    df = pd.DataFrame(rows)

    buy_rows  = df[df["Signal"] == "BUY"].copy()
    if not buy_rows.empty:
        buy_rows["dip_abs"] = buy_rows["Change %"].abs()
        buy_rows = buy_rows.sort_values("dip_abs", ascending=False)

    sell_rows = df[df["Signal"] == "SELL"].copy()

    buy_list  = buy_rows.to_dict("records")  if not buy_rows.empty  else []
    sell_list = sell_rows.to_dict("records") if not sell_rows.empty else []

    return {
        "signals":     df,
        "buy_signals": allocate_capital(buy_list),
        "sell_signals": sell_list,
        "errors":      errors,
        "fetched_at":  datetime.now().strftime("%d %b %Y  %H:%M:%S"),
    }
