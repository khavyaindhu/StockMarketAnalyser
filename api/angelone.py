"""
Angel One SmartAPI integration.

Handles authentication (API key + TOTP) and fetches live trade data.
Token is persisted to .ao_token.json (gitignored) to avoid re-login
across Streamlit restarts — Angel One JWTs are valid for ~24 hours.
"""

import os
import json
import time
import pyotp
from dotenv import load_dotenv

load_dotenv()

_TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".ao_token.json")
_TOKEN_TTL  = 23 * 3600  # reuse token for up to 23 h


def _ascii(value: str) -> str:
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
            "It must contain only A-Z and 2-7."
        )
    if len(secret) < 8:
        raise ValueError(f"TOTP secret is too short ({len(secret)} chars).")


# ── Token file helpers ─────────────────────────────────────────────────────────

def _save_token(access_token: str, refresh_token: str, feed_token: str, profile: dict):
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
        pass  # non-fatal if file write fails


def _load_token() -> dict | None:
    """Return cached token dict if still valid, else None."""
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


# ── SmartConnect factory ───────────────────────────────────────────────────────

def _get_api(access_token=None, refresh_token=None, feed_token=None):
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


# ── Login ──────────────────────────────────────────────────────────────────────

def _do_login() -> dict:
    """Perform a fresh generateSession() call and return token dict or error."""
    missing = _check_config()
    if missing:
        return {"status": False, "error": f"Credentials not configured: {', '.join(missing)}"}

    _validate_totp_secret(_TOTP_SECRET)

    try:
        totp = pyotp.TOTP(_TOTP_SECRET).now()
    except Exception as e:
        return {"status": False, "error": f"Failed to generate TOTP: {e}"}

    try:
        api  = _get_api()
        data = api.generateSession(_CLIENT_CODE, _PASSWORD, totp)
    except Exception as e:
        return {"status": False, "error": f"Angel One API call failed: {e}"}

    if not data:
        return {"status": False, "error": "Angel One returned an empty response."}

    status = data.get("status")
    if status is False or str(status).lower() == "false":
        msg  = data.get("message") or data.get("errorMessage") or "unknown error"
        code = data.get("errorCode") or data.get("errorcode") or ""
        return {"status": False, "error": f"Login failed [{code}]: {msg}"}

    inner = data.get("data") or {}
    tok = {
        "access_token":  inner.get("jwtToken"),
        "refresh_token": inner.get("refreshToken"),
        "feed_token":    inner.get("feedToken"),
        "profile":       inner,
        "saved_at":      time.time(),
    }
    _save_token(tok["access_token"], tok["refresh_token"], tok["feed_token"], tok["profile"])
    return {"status": True, "error": None, **tok}


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_all() -> dict:
    """
    Fetch all Angel One trading data.

    Uses a cached token file to skip re-login (valid for 23 h).
    Only calls generateSession() when the cache is missing or expired.

    Returns dict with keys: login, profile, funds, trades, orders, holdings, positions.
    Each value: {status, data, error}.
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

    # ── Try cached token first ─────────────────────────────────────────────────
    cached = _load_token()
    from_cache = False
    profile = {}

    if cached:
        try:
            api = _get_api(cached["access_token"], cached["refresh_token"], cached["feed_token"])
            from_cache = True
            profile    = cached.get("profile", {})
        except Exception as e:
            cached = None  # fall through to fresh login

    # ── Fresh login if no valid cache ──────────────────────────────────────────
    if not cached:
        login_result = _do_login()
        if not login_result["status"]:
            return _err_all(login_result["error"])
        try:
            api = _get_api(login_result["access_token"],
                           login_result["refresh_token"],
                           login_result["feed_token"])
            profile = login_result.get("profile", {})
        except Exception as e:
            return _err_all(str(e))

    def _call(fn, default):
        try:
            resp = fn()
            # If the API returns a rate-limit or auth error, clear the cache so
            # the next click does a fresh login instead of reusing a dead token.
            if isinstance(resp, dict):
                s = resp.get("status")
                if s is False or str(s).lower() == "false":
                    msg = resp.get("message") or "API error"
                    if "rate" in msg.lower() or "access" in msg.lower():
                        _clear_token()
                    return {"status": False, "data": default, "error": msg}
            return {"status": True, "data": resp.get("data") or default, "error": None}
        except Exception as e:
            err = str(e)
            if "rate" in err.lower() or "access" in err.lower():
                _clear_token()
            return {"status": False, "data": default, "error": err}

    return {
        "login":     {"status": True, "error": None, "from_cache": from_cache},
        "profile":   {"status": True, "data": profile, "error": None},
        "funds":     _call(api.rmsLimit,  {}),
        "trades":    _call(api.tradeBook, []),
        "orders":    _call(api.orderBook, []),
        "holdings":  _call(api.holding,   []),
        "positions": _call(api.position,  []),
    }


def is_configured() -> bool:
    return len(_check_config()) == 0
