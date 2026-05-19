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


def _ascii(value: str) -> str:
    """Strip whitespace and drop any non-ASCII characters (handles bad paste)."""
    return "".join(c for c in (value or "").strip() if ord(c) < 128)


_API_KEY     = _ascii(os.getenv("ANGELONE_API_KEY", ""))
_CLIENT_CODE = _ascii(os.getenv("ANGELONE_CLIENT_CODE", ""))
_PASSWORD    = _ascii(os.getenv("ANGELONE_PASSWORD", ""))
_TOTP_SECRET = _ascii(os.getenv("ANGELONE_TOTP_SECRET", "")).upper().replace(" ", "")


def _check_config() -> list[str]:
    """Returns a list of missing credential names."""
    missing = []
    if not _API_KEY     or _API_KEY     == "your_api_key_here":     missing.append("ANGELONE_API_KEY")
    if not _CLIENT_CODE or _CLIENT_CODE == "your_client_code_here": missing.append("ANGELONE_CLIENT_CODE")
    if not _PASSWORD    or _PASSWORD    == "your_password_here":    missing.append("ANGELONE_PASSWORD")
    if not _TOTP_SECRET or _TOTP_SECRET == "your_totp_secret_here": missing.append("ANGELONE_TOTP_SECRET")
    return missing


def _validate_totp_secret(secret: str) -> None:
    """Raise ValueError with a clear message if the TOTP secret is not valid base32."""
    valid = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    bad = [c for c in secret if c not in valid]
    if bad:
        raise ValueError(
            f"TOTP secret contains invalid base32 characters: {bad!r}. "
            "It must contain only A-Z and 2-7. "
            "Tip: in Google Authenticator tap the account → key icon → copy the secret. "
            "Do not include spaces or special characters."
        )
    if len(secret) < 8:
        raise ValueError(
            f"TOTP secret is too short ({len(secret)} chars). "
            "A valid base32 secret is usually 16–32 characters."
        )


def create_session():
    """
    Authenticate with Angel One SmartAPI and return a live SmartConnect session.

    Returns:
        (SmartConnect, login_data_dict) on success.

    Raises:
        ValueError  if credentials are missing/invalid
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
            "smartapi-python is not installed. "
            "Run: pip install smartapi-python pyotp websocket-client"
        )

    _validate_totp_secret(_TOTP_SECRET)

    try:
        totp = pyotp.TOTP(_TOTP_SECRET).now()
    except Exception as e:
        raise ValueError(f"Failed to generate TOTP from secret: {e}") from e

    api = SmartConnect(api_key=_API_KEY)

    try:
        data = api.generateSession(_CLIENT_CODE, _PASSWORD, totp)
    except Exception as e:
        raise Exception(f"Angel One API call failed: {e}") from e

    if not data:
        raise Exception("Angel One returned an empty response. Check your API key and network.")

    status = data.get("status")
    if status is False or str(status).lower() == "false":
        msg = data.get("message") or data.get("errorMessage") or "unknown error"
        code = data.get("errorCode") or data.get("errorcode") or ""
        raise Exception(f"Angel One login failed [{code}]: {msg}")

    return api, data


def fetch_all() -> dict:
    """
    Create a single session and fetch all data in one go.
    Returns a dict with keys: profile, funds, trades, orders, holdings, positions.
    Each value follows the {status, data, error} shape.
    """
    def _err(default):
        return lambda msg: {"status": False, "data": default, "error": msg}

    try:
        api, login_data = create_session()
    except Exception as e:
        err_str = str(e)
        return {
            "profile":   {"status": False, "data": {},  "error": err_str},
            "funds":     {"status": False, "data": {},  "error": err_str},
            "trades":    {"status": False, "data": [],  "error": err_str},
            "orders":    {"status": False, "data": [],  "error": err_str},
            "holdings":  {"status": False, "data": [],  "error": err_str},
            "positions": {"status": False, "data": [],  "error": err_str},
        }

    def _call(fn, default):
        try:
            resp = fn()
            return {"status": True, "data": resp.get("data") or default, "error": None}
        except Exception as e:
            return {"status": False, "data": default, "error": str(e)}

    return {
        "profile":   {"status": True, "data": login_data.get("data", {}), "error": None},
        "funds":     _call(api.rmsLimit,  {}),
        "trades":    _call(api.tradeBook, []),
        "orders":    _call(api.orderBook, []),
        "holdings":  _call(api.holding,   []),
        "positions": _call(api.position,  []),
    }


def is_configured() -> bool:
    """Returns True if all four Angel One credentials are set in .env."""
    return len(_check_config()) == 0
