"""
Angel One SmartAPI integration.

Handles authentication (API key + TOTP) and fetches live trade data:
  - Trade book  : executed trades for today
  - Order book  : all orders placed today (pending + executed + cancelled)
  - Holdings    : long-term holdings (demat positions)
  - Positions   : intraday / carry-forward open positions
  - Funds       : available cash and margin limits
"""

import os
import pyotp
from dotenv import load_dotenv

load_dotenv()

_API_KEY     = os.getenv("ANGELONE_API_KEY", "")
_CLIENT_CODE = os.getenv("ANGELONE_CLIENT_CODE", "")
_PASSWORD    = os.getenv("ANGELONE_PASSWORD", "")
_TOTP_SECRET = os.getenv("ANGELONE_TOTP_SECRET", "")


def _check_config() -> list[str]:
    """Returns a list of missing credential names."""
    missing = []
    if not _API_KEY     or _API_KEY     == "your_api_key_here":     missing.append("ANGELONE_API_KEY")
    if not _CLIENT_CODE or _CLIENT_CODE == "your_client_code_here": missing.append("ANGELONE_CLIENT_CODE")
    if not _PASSWORD    or _PASSWORD    == "your_password_here":    missing.append("ANGELONE_PASSWORD")
    if not _TOTP_SECRET or _TOTP_SECRET == "your_totp_secret_here": missing.append("ANGELONE_TOTP_SECRET")
    return missing


def create_session():
    """
    Authenticate with Angel One SmartAPI and return a live SmartConnect session.

    Returns:
        SmartConnect instance with an active session token, or None on failure.
        Also returns a dict with the raw login response (tokens, profile, etc.).

    Raises:
        ValueError  if any credentials are missing from .env
        Exception   if SmartAPI login fails
    """
    missing = _check_config()
    if missing:
        raise ValueError(
            f"Angel One credentials not configured in .env: {', '.join(missing)}"
        )

    try:
        from SmartApi import SmartConnect
    except ImportError:
        raise ImportError(
            "smartapi-python is not installed. Run: pip install smartapi-python pyotp websocket-client"
        )

    api = SmartConnect(api_key=_API_KEY)

    totp = pyotp.TOTP(_TOTP_SECRET).now()
    data = api.generateSession(_CLIENT_CODE, _PASSWORD, totp)

    if data.get("status") is False:
        raise Exception(f"Angel One login failed: {data.get('message', 'unknown error')}")

    return api, data


def get_trade_book() -> dict:
    """
    Fetch all executed trades for today's session.

    Returns a dict with keys:
        status  : bool
        data    : list of trade dicts, each containing:
                    symbol, tradingsymbol, exchange, transactiontype,
                    producttype, quantity, price, tradevalue, orderid,
                    tradetime, etc.
        error   : str or None
    """
    try:
        api, _ = create_session()
        resp = api.tradeBook()
        return {
            "status": True,
            "data": resp.get("data") or [],
            "error": None,
        }
    except Exception as e:
        return {"status": False, "data": [], "error": str(e)}


def get_order_book() -> dict:
    """
    Fetch all orders placed today (pending, executed, cancelled, rejected).

    Each order dict contains:
        orderid, tradingsymbol, exchange, transactiontype, producttype,
        quantity, price, status, orderstatus, text (rejection reason), etc.
    """
    try:
        api, _ = create_session()
        resp = api.orderBook()
        return {
            "status": True,
            "data": resp.get("data") or [],
            "error": None,
        }
    except Exception as e:
        return {"status": False, "data": [], "error": str(e)}


def get_holdings() -> dict:
    """
    Fetch long-term holdings (demat stock positions).

    Each holding dict contains:
        tradingsymbol, exchange, isin, t1quantity, realisedquantity,
        quantity, authorisedquantity, producttype, collateralquantity,
        collateraltype, haircut, averageprice, ltp, symboltoken,
        close, pnl, totalbuyvalue, totalsellingvalue, etc.
    """
    try:
        api, _ = create_session()
        resp = api.holding()
        return {
            "status": True,
            "data": resp.get("data") or [],
            "error": None,
        }
    except Exception as e:
        return {"status": False, "data": [], "error": str(e)}


def get_positions() -> dict:
    """
    Fetch current open positions (intraday and carry-forward).

    Each position dict contains:
        tradingsymbol, exchange, producttype, symboltoken, netqty,
        netprice, buyqty, buyprice, sellqty, sellprice,
        unrealised, realised, pnl, ltp, close, etc.
    """
    try:
        api, _ = create_session()
        resp = api.position()
        return {
            "status": True,
            "data": resp.get("data") or [],
            "error": None,
        }
    except Exception as e:
        return {"status": False, "data": [], "error": str(e)}


def get_funds() -> dict:
    """
    Fetch available cash and margin limits.

    Returns net, availablecash, utiliseddebits, availablecashmargain,
    collateral, m2mrealized, m2munrealized, etc.
    """
    try:
        api, _ = create_session()
        resp = api.rmsLimit()
        return {
            "status": True,
            "data": resp.get("data") or {},
            "error": None,
        }
    except Exception as e:
        return {"status": False, "data": {}, "error": str(e)}


def get_profile() -> dict:
    """
    Fetch account profile: name, email, mobile, exchanges, products, etc.
    """
    try:
        api, login_data = create_session()
        profile = login_data.get("data", {})
        return {
            "status": True,
            "data": profile,
            "error": None,
        }
    except Exception as e:
        return {"status": False, "data": {}, "error": str(e)}


def is_configured() -> bool:
    """Returns True if all four Angel One credentials are set in .env."""
    return len(_check_config()) == 0
