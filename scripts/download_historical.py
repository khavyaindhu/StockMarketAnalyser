#!/usr/bin/env python3
"""
One-time (or on-demand) download of NSE daily OHLCV from Angel One SmartAPI.

Default: last 1 calendar year of ONE_DAY candles for all 20 stocks in STOCK_LIST.
Skips download if manifest + files already exist for the requested period
(use --force to re-download).

Usage (from project root):
    python scripts/download_historical.py
    python scripts/download_historical.py --force
    python scripts/download_historical.py --years 1
    python scripts/download_historical.py --years 10

Outputs under data/historical/daily/:
    manifest.json
    per_stock/<SYMBOL>.csv
    historical_daily_combined.csv
    historical_daily.xlsx  (Metadata + All_Stocks sheets)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Project root on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.angelone import get_api, is_configured
from trading.stock_master import STOCK_LIST, lookup_tokens

OUTPUT_DIR = ROOT / "data" / "historical" / "daily"
PER_STOCK_DIR = OUTPUT_DIR / "per_stock"
MANIFEST_FILE = OUTPUT_DIR / "manifest.json"
COMBINED_CSV = OUTPUT_DIR / "historical_daily_combined.csv"
COMBINED_XLSX = OUTPUT_DIR / "historical_daily.xlsx"

INTERVAL = "ONE_DAY"
REQUEST_DELAY_SEC = 0.4

# Column order for analysis (stable headings)
COLUMNS = [
    "Stock Name",
    "NSE Symbol",
    "Category",
    "Exchange",
    "Token ID",
    "Date",
    "Open (₹)",
    "High (₹)",
    "Low (₹)",
    "Close (₹)",
    "Volume",
    "Prev Close (₹)",
    "Change (₹)",
    "Change (%)",
]


def _market_date_range(years: float) -> tuple[str, str, str, str]:
    """Return (fromdate, todate) strings for Angel One API and ISO date labels."""
    end = datetime.now()
    start = end - timedelta(days=int(365.25 * years))
    from_api = start.strftime("%Y-%m-%d 09:15")
    to_api = end.strftime("%Y-%m-%d 15:30")
    from_label = start.strftime("%Y-%m-%d")
    to_label = end.strftime("%Y-%m-%d")
    return from_api, to_api, from_label, to_label


def _parse_candle_response(raw: list) -> pd.DataFrame:
    """Angel One returns list of [datetime, open, high, low, close, volume]."""
    if not raw:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(raw, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("datetime").reset_index(drop=True)


def _enrich_stock_df(
    candles: pd.DataFrame,
    stock: dict,
    token_id: str,
) -> pd.DataFrame:
    if candles.empty:
        return pd.DataFrame(columns=COLUMNS)

    df = candles.copy()
    df["Date"] = df["datetime"].dt.strftime("%Y-%m-%d")
    df["Close (₹)"] = df["close"]
    df["Prev Close (₹)"] = df["Close (₹)"].shift(1)
    df["Change (₹)"] = df["Close (₹)"] - df["Prev Close (₹)"]
    df["Change (%)"] = (df["Change (₹)"] / df["Prev Close (₹)"] * 100).round(4)

    out = pd.DataFrame({
        "Stock Name": stock["name"],
        "NSE Symbol": stock["symbol"],
        "Category": stock["category"],
        "Exchange": "NSE",
        "Token ID": token_id or "",
        "Date": df["Date"],
        "Open (₹)": df["open"].round(2),
        "High (₹)": df["high"].round(2),
        "Low (₹)": df["low"].round(2),
        "Close (₹)": df["Close (₹)"].round(2),
        "Volume": df["volume"].astype("Int64"),
        "Prev Close (₹)": df["Prev Close (₹)"].round(2),
        "Change (₹)": df["Change (₹)"].round(2),
        "Change (%)": df["Change (%)"],
    })
    return out[COLUMNS]


def _fetch_candles_once(api, token: str, fromdate: str, todate: str) -> list:
    params = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": INTERVAL,
        "fromdate": fromdate,
        "todate": todate,
    }
    resp = api.getCandleData(params)
    if not resp:
        raise RuntimeError("Empty response from getCandleData")
    status = resp.get("status")
    if status is False or str(status).lower() == "false":
        msg = resp.get("message") or resp.get("errorcode") or "unknown error"
        raise RuntimeError(msg)
    return resp.get("data") or []


def _fetch_candles(api, token: str, fromdate: str, todate: str) -> list:
    """Fetch candles; retry in ~6-month chunks if one large request fails."""
    try:
        return _fetch_candles_once(api, token, fromdate, todate)
    except RuntimeError:
        pass

    start = datetime.strptime(fromdate[:10], "%Y-%m-%d")
    end = datetime.strptime(todate[:10], "%Y-%m-%d")
    merged: list = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=182), end)
        fd = chunk_start.strftime("%Y-%m-%d 09:15")
        td = chunk_end.strftime("%Y-%m-%d 15:30")
        part = _fetch_candles_once(api, token, fd, td)
        merged.extend(part)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(REQUEST_DELAY_SEC)

    # Deduplicate by datetime string (first field)
    seen: set[str] = set()
    unique: list = []
    for row in merged:
        key = str(row[0]) if row else ""
        if key and key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _manifest_years(manifest: dict) -> float:
    try:
        return float(manifest.get("years_requested", 0))
    except (TypeError, ValueError):
        return 0.0


def _is_complete(manifest: dict, requested_years: float) -> bool:
    """True if saved files cover this request and the current stock list."""
    if manifest.get("source") != "angel_one_smartapi":
        return False
    if manifest.get("interval") != INTERVAL:
        return False
    if _manifest_years(manifest) < requested_years:
        return False
    expected = {s["symbol"] for s in STOCK_LIST}
    saved = set(manifest.get("symbols") or [])
    if saved != expected:
        return False
    for sym in expected:
        if not (PER_STOCK_DIR / f"{sym}.csv").is_file():
            return False
    if not COMBINED_CSV.is_file() or not COMBINED_XLSX.is_file():
        return False
    return True


def _load_manifest() -> dict | None:
    try:
        with open(MANIFEST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_manifest(meta: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def download(years: float = 1.0, force: bool = False) -> int:
    if years <= 0:
        print("ERROR: --years must be greater than 0")
        return 1

    if not is_configured():
        print("ERROR: Angel One credentials missing in .env")
        print("  Required: ANGELONE_API_KEY, ANGELONE_CLIENT_CODE,")
        print("            ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET")
        return 1

    manifest = _load_manifest()
    if manifest and _is_complete(manifest, float(years)) and not force:
        print("Historical data already downloaded (use --force to re-download).")
        print(f"  Downloaded at: {manifest.get('downloaded_at')}")
        print(f"  Years in file: {manifest.get('years_requested')}")
        print(f"  Range: {manifest.get('from_date')} → {manifest.get('to_date')}")
        print(f"  Folder: {OUTPUT_DIR}")
        return 0

    from_api, to_api, from_label, to_label = _market_date_range(years)
    print(f"Connecting to Angel One…")
    api = get_api()
    print(f"Resolving NSE tokens for {len(STOCK_LIST)} stocks…")
    tokens = lookup_tokens(api)

    PER_STOCK_DIR.mkdir(parents=True, exist_ok=True)
    all_frames: list[pd.DataFrame] = []
    errors: list[tuple[str, str]] = []

    for i, stock in enumerate(STOCK_LIST, 1):
        sym = stock["symbol"]
        tok_info = tokens.get(sym, {})
        token_id = tok_info.get("token")
        print(f"  [{i}/{len(STOCK_LIST)}] {sym} …", end=" ", flush=True)

        if not token_id:
            errors.append((sym, "No symbol token (searchScrip failed)"))
            print("SKIP (no token)")
            continue

        try:
            raw = _fetch_candles(api, token_id, from_api, to_api)
            df = _enrich_stock_df(_parse_candle_response(raw), stock, token_id)
            if df.empty:
                errors.append((sym, "No candle data returned"))
                print("EMPTY")
            else:
                path = PER_STOCK_DIR / f"{sym}.csv"
                df.to_csv(path, index=False)
                all_frames.append(df)
                print(f"OK ({len(df)} rows)")
        except Exception as e:
            errors.append((sym, str(e)))
            print(f"FAIL ({e})")

        time.sleep(REQUEST_DELAY_SEC)

    if not all_frames:
        print("\nNo data downloaded for any symbol.")
        for sym, err in errors:
            print(f"  {sym}: {err}")
        return 1

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.sort_values(["NSE Symbol", "Date"]).reset_index(drop=True)
    combined = combined.drop_duplicates(subset=["NSE Symbol", "Date"], keep="last")
    combined = combined.reset_index(drop=True)
    combined.to_csv(COMBINED_CSV, index=False)

    meta_rows = pd.DataFrame([
        {"Field": "Downloaded At (UTC)", "Value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")},
        {"Field": "Source", "Value": "Angel One SmartAPI getCandleData"},
        {"Field": "Interval", "Value": INTERVAL},
        {"Field": "From Date", "Value": from_label},
        {"Field": "To Date", "Value": to_label},
        {"Field": "Requested Years", "Value": years},
        {"Field": "Stocks Requested", "Value": len(STOCK_LIST)},
        {"Field": "Stocks Downloaded", "Value": len(all_frames)},
        {"Field": "Total Rows", "Value": len(combined)},
        {"Field": "Re-download Command", "Value": "python scripts/download_historical.py --force"},
    ])

    with pd.ExcelWriter(COMBINED_XLSX, engine="openpyxl") as writer:
        meta_rows.to_excel(writer, sheet_name="Metadata", index=False)
        combined.to_excel(writer, sheet_name="All_Stocks", index=False)
        for sym, grp in combined.groupby("NSE Symbol", sort=True):
            sheet = sym[:31]  # Excel sheet name limit
            grp.to_excel(writer, sheet_name=sheet, index=False)

    manifest_data = {
        "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "angel_one_smartapi",
        "interval": INTERVAL,
        "from_date": from_label,
        "to_date": to_label,
        "years_requested": years,
        "symbols": [s["symbol"] for s in STOCK_LIST],
        "symbols_ok": [s["symbol"] for s in STOCK_LIST if s["symbol"] not in {e[0] for e in errors}],
        "errors": [{"symbol": s, "error": e} for s, e in errors],
        "files": {
            "combined_csv": str(COMBINED_CSV.relative_to(ROOT)),
            "combined_xlsx": str(COMBINED_XLSX.relative_to(ROOT)),
            "per_stock_dir": str(PER_STOCK_DIR.relative_to(ROOT)),
        },
        "row_counts": {sym: int(len(combined[combined["NSE Symbol"] == sym])) for sym in combined["NSE Symbol"].unique()},
    }
    _save_manifest(manifest_data)

    print(f"\nDone.")
    print(f"  Combined CSV : {COMBINED_CSV}")
    print(f"  Combined XLSX: {COMBINED_XLSX}")
    print(f"  Per-stock CSV: {PER_STOCK_DIR}/")
    print(f"  Manifest     : {MANIFEST_FILE}")
    if errors:
        print(f"\n  {len(errors)} symbol(s) had issues:")
        for sym, err in errors:
            print(f"    {sym}: {err}")
    return 0 if len(errors) < len(STOCK_LIST) else 1


def main():
    parser = argparse.ArgumentParser(description="Download NSE daily history from Angel One.")
    parser.add_argument(
        "--years", type=float, default=1.0,
        help="Calendar years of history to fetch (default: 1)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download even if manifest and files already exist",
    )
    args = parser.parse_args()
    sys.exit(download(years=args.years, force=args.force))


if __name__ == "__main__":
    main()
