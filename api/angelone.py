"""
Angel One SmartAPI integration.

Token is persisted to api/.ao_token.json (gitignored, valid ~24 h)
so generateSession() is called at most once per day.
"""

import os
import json
import time
import logging
import pyotp
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger("angelone")

_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"

_API_KEY = ""
_CLIENT_CODE = ""
_PASSWORD = ""
_TOTP_SECRET = ""

_TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".ao_token.json")
_TOKEN_TTL  = 6 * 3600   # reuse for up to 6 h (Angel One sessions expire intraday)


def _ascii(value: str) -> str:
    return "".join(c for c in (value or "").strip() if ord(c) < 128)


def _refresh_config() -> None:
    """Reload project-root .env so Streamlit reruns see newly saved credentials."""
    global _API_KEY, _CLIENT_CODE, _PASSWORD, _TOTP_SECRET
    load_dotenv(dotenv_path=_ENV_FILE, override=True)
    _API_KEY = _ascii(os.getenv("ANGELONE_API_KEY", ""))
    _CLIENT_CODE = _ascii(os.getenv("ANGELONE_CLIENT_CODE", ""))
    _PASSWORD = _ascii(os.getenv("ANGELONE_PASSWORD", ""))
    _TOTP_SECRET = _ascii(os.getenv("ANGELONE_TOTP_SECRET", "")).upper().replace(" ", "")


def _check_config() -> list[str]:
    _refresh_config()
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
            "Must contain only A-Z and 2-7."
        )
    if len(secret) < 8:
        raise ValueError(f"TOTP secret too short ({len(secret)} chars).")


# ── Token file helpers ─────────────────────────────────────────────────────────

def _save_token(access_token, refresh_token, feed_token, profile):
    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump({
                "access_token":  access_token,
                "refresh_token": refresh_token,
                "feed_token":    feed_token,
                "profile":       profile,
                "saved_at":      time.time(),
            }, f)
    except Exception:
        pass


def _load_token() -> dict | None:
    try:
        with open(_TOKEN_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("saved_at", 0) < _TOKEN_TTL:
            return data
    except Exception:
        pass
    return None


def _clear_token():
    try:
        os.remove(_TOKEN_FILE)
    except Exception:
        pass


# ── SmartConnect import ────────────────────────────────────────────────────────

def _import_smart_connect():
    try:
        from SmartApi import SmartConnect
        return SmartConnect
    except ImportError:
        raise ImportError(
            "smartapi-python is not installed. "
            "Run: pip install smartapi-python pyotp websocket-client"
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_all() -> dict:
    """
    Fetch all Angel One trading data.

    - If a valid token file exists, creates SmartConnect with that token (no re-login).
    - Otherwise does a fresh generateSession() and saves the token for next time.

    Returns dict with keys: login, profile, funds, trades, orders, holdings, positions.
    """
    def _err_all(msg):
        return {
            "login":     {"status": False, "error": msg, "from_cache": False},
            "profile":   {"status": False, "data": {},  "error": msg},
            "funds":     {"status": False, "data": {},  "error": msg},
            "trades":    {"status": False, "data": [],  "error": msg},
            "orders":    {"status": False, "data": [],  "error": msg},
            "holdings":  {"status": False, "data": [],  "error": msg},
            "positions": {"status": False, "data": [],  "error": msg},
        }

    _refresh_config()
    SmartConnect = _import_smart_connect()

    # ── Try cached token (skip login) ──────────────────────────────────────────
    cached = _load_token()
    if cached:
        try:
            api = SmartConnect(
                api_key=_API_KEY,
                access_token=cached["access_token"],
                refresh_token=cached["refresh_token"],
                feed_token=cached["feed_token"],
            )
            profile    = cached.get("profile", {})
            from_cache = True
        except Exception as e:
            cached = None

    # ── Fresh login ────────────────────────────────────────────────────────────
    if not cached:
        missing = _check_config()
        if missing:
            return _err_all(f"Credentials not configured: {', '.join(missing)}")

        try:
            _validate_totp_secret(_TOTP_SECRET)
            totp = pyotp.TOTP(_TOTP_SECRET).now()
        except Exception as e:
            return _err_all(str(e))

        # Use this SAME api object for data calls — preserves internal state
        api = SmartConnect(api_key=_API_KEY)
        try:
            data = api.generateSession(_CLIENT_CODE, _PASSWORD, totp)
        except Exception as e:
            return _err_all(f"Angel One API call failed: {e}")

        if not data:
            return _err_all("Angel One returned an empty response.")

        status = data.get("status")
        if status is False or str(status).lower() == "false":
            msg  = data.get("message") or data.get("errorMessage") or "unknown error"
            code = data.get("errorCode") or data.get("errorcode") or ""
            return _err_all(f"Login failed [{code}]: {msg}")

        inner = data.get("data") or {}
        _save_token(
            inner.get("jwtToken"),
            inner.get("refreshToken"),
            inner.get("feedToken"),
            inner,
        )
        profile    = inner
        from_cache = False

    # ── Fetch data using the api object (same instance that logged in) ─────────
    _token_expired = False

    def _is_token_error(text: str) -> bool:
        t = text.lower()
        return any(k in t for k in ("invalid token", "ag8001", "token expired", "unauthorized"))

    def _call(fn, default):
        nonlocal _token_expired
        try:
            resp = fn()
            if isinstance(resp, dict):
                s = resp.get("status") if "status" in resp else resp.get("success")
                if s is False or str(s).lower() == "false":
                    msg = resp.get("message") or resp.get("errorMessage") or "API error"
                    if _is_token_error(msg) or any(k in msg.lower() for k in ("rate", "access denied")):
                        _clear_token()
                        _token_expired = True
                    return {"status": False, "data": default, "error": msg}
                inner = resp.get("data")
                return {"status": True, "data": inner if inner is not None else default, "error": None}
            return {"status": True, "data": default, "error": None}
        except Exception as e:
            err = str(e)
            if _is_token_error(err) or any(k in err.lower() for k in ("rate", "access denied")):
                _clear_token()
                _token_expired = True
            return {"status": False, "data": default, "error": err}

    data_results = {
        "funds":     _call(api.rmsLimit,  {}),
        "trades":    _call(api.tradeBook, []),
        "orders":    _call(api.orderBook, []),
        "holdings":  _call(api.holding,   []),
        "positions": _call(api.position,  []),
    }

    # ── Cached token was rejected — do a fresh login and retry once ────────────
    if _token_expired and from_cache:
        log.info("Cached token rejected by Angel One — doing fresh login…")
        _clear_token()
        missing = _check_config()
        if missing:
            return _err_all(f"Credentials not configured: {', '.join(missing)}")
        try:
            _validate_totp_secret(_TOTP_SECRET)
            totp = pyotp.TOTP(_TOTP_SECRET).now()
            api2 = SmartConnect(api_key=_API_KEY)
            data2 = api2.generateSession(_CLIENT_CODE, _PASSWORD, totp)
        except Exception as e:
            return _err_all(f"Re-login failed: {e}")

        if not data2:
            return _err_all("Re-login returned empty response.")
        status2 = data2.get("status")
        if status2 is False or str(status2).lower() == "false":
            msg2 = data2.get("message") or "unknown error"
            return _err_all(f"Re-login failed: {msg2}")

        inner2 = data2.get("data") or {}
        _save_token(inner2.get("jwtToken"), inner2.get("refreshToken"),
                    inner2.get("feedToken"), inner2)
        profile = inner2

        def _call2(fn, default):
            try:
                resp = fn()
                if isinstance(resp, dict):
                    s = resp.get("status") if "status" in resp else resp.get("success")
                    if s is False or str(s).lower() == "false":
                        msg = resp.get("message") or "API error"
                        return {"status": False, "data": default, "error": msg}
                    inner = resp.get("data")
                    return {"status": True, "data": inner if inner is not None else default, "error": None}
                return {"status": True, "data": default, "error": None}
            except Exception as e:
                return {"status": False, "data": default, "error": str(e)}

        return {
            "login":     {"status": True, "error": None, "from_cache": False},
            "profile":   {"status": True, "data": profile, "error": None},
            "funds":     _call2(api2.rmsLimit,  {}),
            "trades":    _call2(api2.tradeBook, []),
            "orders":    _call2(api2.orderBook, []),
            "holdings":  _call2(api2.holding,   []),
            "positions": _call2(api2.position,  []),
        }

    return {
        "login":     {"status": True, "error": None, "from_cache": from_cache},
        "profile":   {"status": True, "data": profile, "error": None},
        **data_results,
    }


def get_api(force_login: bool = False):
    """
    Return a SmartConnect object with a guaranteed-valid token.

    Uses the cached token if it is still fresh; otherwise does a full
    generateSession() login and saves the new token. Pass force_login=True
    for one-off jobs that should not risk a stale cached token.

    Use this in background threads (e.g. the live monitor) instead of
    holding on to an api object from startup — tokens expire intraday.
    """
    _refresh_config()
    SmartConnect = _import_smart_connect()

    if force_login:
        _clear_token()

    cached = None if force_login else _load_token()
    if cached:
        return SmartConnect(
            api_key=_API_KEY,
            access_token=cached["access_token"],
            refresh_token=cached.get("refresh_token"),
            feed_token=cached.get("feed_token"),
        )

    # No valid cache — do a fresh login
    missing = _check_config()
    if missing:
        raise RuntimeError(f"Angel One credentials not configured: {', '.join(missing)}")

    _validate_totp_secret(_TOTP_SECRET)
    totp = pyotp.TOTP(_TOTP_SECRET).now()
    api  = SmartConnect(api_key=_API_KEY)
    data = api.generateSession(_CLIENT_CODE, _PASSWORD, totp)

    if not data:
        raise RuntimeError("Angel One generateSession returned empty response.")

    status = data.get("status")
    if status is False or str(status).lower() == "false":
        msg  = data.get("message") or data.get("errorMessage") or "unknown"
        code = data.get("errorCode") or ""
        raise RuntimeError(f"Angel One login failed [{code}]: {msg}")

    inner = data.get("data") or {}
    _save_token(inner.get("jwtToken"), inner.get("refreshToken"),
                inner.get("feedToken"), inner)
    log.info("Angel One: fresh login successful, token cached.")
    return api


def is_configured() -> bool:
    return len(_check_config()) == 0
