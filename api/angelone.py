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
    missing = []
    if not _API_KEY     or _API_KEY     == "your_api_key_here":     missing.append("ANGELONE_API_KEY")
    if not _CLIENT_CODE or _CLIENT_CODE == "your_client_code_here": missing.append("ANGELONE_CLIENT_CODE")
    if not _PASSWORD    or _PASSWORD    == "your_password_here":    missing.append("ANGELONE_PASSWORD")
    if not _TOTP_SECRET or _TOTP_SECRET == "your_totp_secret_here": missing.append("ANGELONE_TOTP_SECRET")
    return missing


def _validate_totp_secret(secret: str) -> None:
    valid = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    bad = [c for c in secret if c not in valid]
    if bad:
        raise ValueError(
            f"TOTP secret contains invalid base32 characters: {bad!r}. "
            "It must contain only A-Z and 2-7. "
            "Tip: in Google Authenticator tap the account → key icon → copy the secret."
        )
    if len(secret) < 8:
        raise ValueError(
            f"TOTP secret is too short ({len(secret)} chars). "
            "A valid base32 secret is usually 16–32 characters."
        )


def _get_api(access_token: str | None = None, refresh_token: str | None = None,
             feed_token: str | None = None):
    """Return a SmartConnect instance, restored from tokens if provided."""
    try:
        from SmartApi import SmartConnect
    except ImportError:
        raise ImportError(
            "smartapi-python is not installed. "
            "Run: pip install smartapi-python pyotp websocket-client"
        )
    return SmartConnect(
        api_key=_API_KEY,
        access_token=access_token,
        refresh_token=refresh_token,
        feed_token=feed_token,
    )


def login() -> dict:
    """
    Perform a fresh login to Angel One and return tokens + profile.

    Returns:
        {
          "status": bool,
          "access_token": str,
          "refresh_token": str,
          "feed_token": str,
          "profile": dict,
          "error": str | None,
        }
    """
    missing = _check_config()
    if missing:
        return {"status": False, "error": f"Credentials not configured: {', '.join(missing)}",
                "access_token": None, "refresh_token": None, "feed_token": None, "profile": {}}

    _validate_totp_secret(_TOTP_SECRET)

    try:
        totp = pyotp.TOTP(_TOTP_SECRET).now()
    except Exception as e:
        return {"status": False, "error": f"Failed to generate TOTP: {e}",
                "access_token": None, "refresh_token": None, "feed_token": None, "profile": {}}

    try:
        api = _get_api()
        data = api.generateSession(_CLIENT_CODE, _PASSWORD, totp)
    except Exception as e:
        return {"status": False, "error": f"Angel One API call failed: {e}",
                "access_token": None, "refresh_token": None, "feed_token": None, "profile": {}}

    if not data:
        return {"status": False, "error": "Angel One returned an empty response.",
                "access_token": None, "refresh_token": None, "feed_token": None, "profile": {}}

    status = data.get("status")
    if status is False or str(status).lower() == "false":
        msg  = data.get("message") or data.get("errorMessage") or "unknown error"
        code = data.get("errorCode") or data.get("errorcode") or ""
        return {"status": False, "error": f"Login failed [{code}]: {msg}",
                "access_token": None, "refresh_token": None, "feed_token": None, "profile": {}}

    inner = data.get("data") or {}
    return {
        "status":        True,
        "error":         None,
        "access_token":  inner.get("jwtToken"),
        "refresh_token": inner.get("refreshToken"),
        "feed_token":    inner.get("feedToken"),
        "profile":       inner,
    }


def fetch_all(access_token: str | None = None,
              refresh_token: str | None = None,
              feed_token: str | None = None) -> dict:
    """
    Fetch all trading data using a cached token (no re-login) when provided,
    or perform a fresh login if no token is available.

    Returns a dict with keys: login, profile, funds, trades, orders, holdings, positions.
    """
    _err_all = lambda msg: {
        "login":     {"status": False, "error": msg,
                      "access_token": None, "refresh_token": None, "feed_token": None, "profile": {}},
        "profile":   {"status": False, "data": {}, "error": msg},
        "funds":     {"status": False, "data": {}, "error": msg},
        "trades":    {"status": False, "data": [], "error": msg},
        "orders":    {"status": False, "data": [], "error": msg},
        "holdings":  {"status": False, "data": [], "error": msg},
        "positions": {"status": False, "data": [], "error": msg},
    }

    # ── If we have a cached token, skip re-login ───────────────────────────────
    if access_token:
        try:
            api = _get_api(access_token, refresh_token, feed_token)
            login_result = {"status": True, "error": None,
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "feed_token": feed_token,
                            "profile": {}}
        except Exception as e:
            return _err_all(str(e))
    else:
        # ── Fresh login ────────────────────────────────────────────────────────
        login_result = login()
        if not login_result["status"]:
            return _err_all(login_result["error"])
        try:
            api = _get_api(login_result["access_token"],
                           login_result["refresh_token"],
                           login_result["feed_token"])
        except Exception as e:
            return _err_all(str(e))

    def _call(fn, default):
        try:
            resp = fn()
            return {"status": True, "data": resp.get("data") or default, "error": None}
        except Exception as e:
            return {"status": False, "data": default, "error": str(e)}

    return {
        "login":     login_result,
        "profile":   {"status": True, "data": login_result["profile"], "error": None},
        "funds":     _call(api.rmsLimit,  {}),
        "trades":    _call(api.tradeBook, []),
        "orders":    _call(api.orderBook, []),
        "holdings":  _call(api.holding,   []),
        "positions": _call(api.position,  []),
    }


def is_configured() -> bool:
    return len(_check_config()) == 0
