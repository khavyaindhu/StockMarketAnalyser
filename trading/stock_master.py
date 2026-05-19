"""
Stock master — 20-stock configuration and Angel One token lookup.

Token IDs are fetched once via searchScrip and cached in trading/.token_cache.json
so subsequent runs don't need an extra API call.
"""

import os
import json

_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".token_cache.json")

# ── 20-stock master list ───────────────────────────────────────────────────────
# Fields: name, symbol (NSE base), category, buy_dip_pct, sell_target_pct, max_capital
STOCK_LIST = [
    # Pharma
    dict(name="Cipla",              symbol="CIPLA",      category="Pharma",      buy_dip_pct=2.5, sell_target_pct=5.0, max_capital=15000),
    dict(name="Natco Pharma",       symbol="NATCOPHARM", category="Pharma",      buy_dip_pct=2.5, sell_target_pct=5.0, max_capital=15000),
    dict(name="Dr Reddys",          symbol="DRREDDY",    category="Pharma",      buy_dip_pct=2.5, sell_target_pct=5.0, max_capital=15000),
    dict(name="Zydus Lifesciences", symbol="ZYDUSLIFE",  category="Pharma",      buy_dip_pct=2.5, sell_target_pct=5.0, max_capital=15000),
    # Large Cap
    dict(name="HDFC Bank",          symbol="HDFCBANK",   category="Large Cap",   buy_dip_pct=2.0, sell_target_pct=4.0, max_capital=15000),
    dict(name="ITC",                symbol="ITC",        category="Large Cap",   buy_dip_pct=2.0, sell_target_pct=4.0, max_capital=15000),
    dict(name="Wipro",              symbol="WIPRO",      category="Large Cap",   buy_dip_pct=2.0, sell_target_pct=4.0, max_capital=15000),
    # Mid Banks
    dict(name="Federal Bank",       symbol="FEDERALBNK", category="Mid Bank",    buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="IDFC First Bank",    symbol="IDFCFIRSTB", category="Mid Bank",    buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="IndusInd Bank",      symbol="INDUSINDBK", category="Mid Bank",    buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="Karnataka Bank",     symbol="KTKBANK",    category="Mid Bank",    buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="South Indian Bank",  symbol="SOUTHBANK",  category="Mid Bank",    buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    # NBFC
    dict(name="Manappuram Finance", symbol="MANAPPURAM", category="NBFC",        buy_dip_pct=3.5, sell_target_pct=7.0, max_capital=12000),
    # Metals
    dict(name="Tata Steel",         symbol="TATASTEEL",  category="Metals",      buy_dip_pct=3.5, sell_target_pct=6.0, max_capital=12000),
    # Auto
    dict(name="Tata Motors CV",     symbol="TMCV",       category="Auto",        buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="Tata Motors PV",     symbol="TMPV",       category="Auto",        buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    # Consumer / Jewellery
    dict(name="ITC Hotels",         symbol="ITCHOTELS",  category="Consumer",    buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="Kalyan Jewellers",   symbol="KALYANKJIL", category="Jewellery",   buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="Thangamayil",        symbol="THANGAMAYL", category="Jewellery",   buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
    dict(name="Titan",              symbol="TITAN",      category="Jewellery",   buy_dip_pct=3.0, sell_target_pct=6.0, max_capital=12000),
]

# Quick lookup by symbol
STOCK_MAP = {s["symbol"]: s for s in STOCK_LIST}


# ── Token cache ────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def lookup_tokens(api) -> dict[str, dict]:
    """
    Return {symbol: {trading_symbol, token}} for all 20 stocks.
    Uses cache; fetches missing tokens via searchScrip.
    """
    cache   = _load_cache()
    missing = [s for s in STOCK_LIST if s["symbol"] not in cache]

    if missing:
        for stock in missing:
            sym = stock["symbol"]
            try:
                result = api.searchScrip("NSE", sym)
                hits   = (result or {}).get("data") or []
                # Prefer exact equity match (e.g. CIPLA-EQ)
                match  = next(
                    (h for h in hits
                     if h.get("tradingsymbol", "").upper() == f"{sym}-EQ"),
                    hits[0] if hits else None,
                )
                if match:
                    cache[sym] = {
                        "trading_symbol": match["tradingsymbol"],
                        "token":          match["symboltoken"],
                    }
                else:
                    cache[sym] = {"trading_symbol": f"{sym}-EQ", "token": None}
            except Exception:
                cache[sym] = {"trading_symbol": f"{sym}-EQ", "token": None}

        _save_cache(cache)

    return cache


def get_stock_config(symbol: str) -> dict:
    """Return master config for a given NSE symbol."""
    return STOCK_MAP.get(symbol, {})
