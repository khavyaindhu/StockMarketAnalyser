# Daily historical OHLCV (Angel One)

NSE **daily** candles for the 20-stock watchlist in `trading/stock_master.py`.
The default is one year; use `--years 10` when you are ready to build the
10-year dataset in the same CSV/XLSX outputs.

## Download (once)

From the project root (Codespace or local), with Angel One credentials in `.env`:

```bash
python scripts/download_historical.py
```

- One-year bootstrap: `python scripts/download_historical.py --years 1`
- Ten-year build: `python scripts/download_historical.py --years 10`
- **Skips** if `manifest.json` and all files already exist for the requested period.
- **Re-download** only when you need fresh data: `python scripts/download_historical.py --force`

Works on **market holidays** and weekends — historical API is not tied to live session hours.

## Files

| File | Purpose |
|------|---------|
| `manifest.json` | Download date, date range, row counts, errors |
| `historical_daily_combined.csv` | All 20 stocks in one table (best for pandas/analysis) |
| `historical_daily.xlsx` | Metadata sheet + All_Stocks + one sheet per symbol |
| `per_stock/<SYMBOL>.csv` | Single-symbol CSV with same column headings |

## Column headings

`Stock Name`, `NSE Symbol`, `Category`, `Exchange`, `Token ID`, `Date`,  
`Open (₹)`, `High (₹)`, `Low (₹)`, `Close (₹)`, `Volume`,  
`Prev Close (₹)`, `Change (₹)`, `Change (%)`

## Sync to local / GitHub

Commit the CSV/XLSX/manifest after a successful run, then `git pull` on your machine:

```bash
git add data/historical/daily/
git commit -m "Add 1y daily historical OHLCV for 20 stocks"
git push
```

Do **not** run the downloader on every app start — only manually or when you want to refresh (e.g. once a month with `--force`).
If a one-year manifest exists and you request ten years, the script will download
again and replace the same CSV/XLSX outputs; after that, repeated ten-year runs
skip unless `--force` is used. Rows are de-duplicated by `NSE Symbol` + `Date`.
