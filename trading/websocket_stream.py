"""
Angel One WebSocket Streaming 2.0 — Real-time LTP for the 20 watchlist stocks.

Protocol:
  URL      : wss://smartapisocket.angelone.in/smart-stream
  Auth     : headers — Authorization (JWT), x-api-key, x-client-code, x-feed-token
  Mode     : 1 = LTP only  (51-byte binary response, prices in paise ÷ 100)
  Heartbeat: send the string "ping" every 30 s; server replies "pong"

Binary packet layout (Little Endian, mode 1 = 51 bytes):
  Offset  Size  Type    Field
  0       1     uint8   subscription_mode
  1       1     uint8   exchange_type
  2       25    bytes   token (null-padded ASCII)
  27      8     int64   sequence_number
  35      8     int64   exchange_timestamp (epoch ms)
  43      8     int64   last_traded_price (paise — divide by 100 for ₹)

Subscribe JSON payload:
  {
    "correlationID": "<any string>",
    "action": 1,                   # 1 = subscribe, 0 = unsubscribe
    "params": {
      "mode": 1,                   # LTP
      "tokenList": [{ "exchangeType": 1, "tokens": ["<token>", ...] }]
    }
  }
"""

import os
import json
import struct
import logging
import threading
import time
from typing import Callable

_WS_URL = "wss://smartapisocket.angelone.in/smart-stream"
_HEARTBEAT_INTERVAL = 30  # seconds
_RECONNECT_DELAY    = 5   # seconds between reconnect attempts

log = logging.getLogger("ws_stream")

# ── Module-level LTP cache (shared across all Streamlit reruns) ────────────────
# {symbol: {"ltp": float, "ts": epoch_ms, "token": str}}
ltp_cache: dict[str, dict] = {}

# Reverse map: token_id → symbol  (populated at subscribe time)
_token_to_symbol: dict[str, str] = {}

_stream_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ── Binary parser ──────────────────────────────────────────────────────────────

def _parse_ltp_packet(data: bytes) -> dict | None:
    """Parse a 51-byte mode-1 (LTP) binary packet from Angel One."""
    if len(data) < 51:
        return None
    try:
        mode          = data[0]
        exchange_type = data[1]
        token_raw     = data[2:27].rstrip(b"\x00").decode("ascii", errors="ignore")
        seq_no        = struct.unpack_from("<q", data, 27)[0]
        ts_ms         = struct.unpack_from("<q", data, 35)[0]
        ltp_paise     = struct.unpack_from("<q", data, 43)[0]

        return {
            "mode":          mode,
            "exchange_type": exchange_type,
            "token":         token_raw,
            "seq_no":        seq_no,
            "ts_ms":         ts_ms,
            "ltp":           ltp_paise / 100.0,
        }
    except Exception:
        return None


# ── Subscribe payload builder ──────────────────────────────────────────────────

def _build_subscribe(token_ids: list[str], correlation_id: str = "ws_20stocks") -> str:
    return json.dumps({
        "correlationID": correlation_id,
        "action": 1,
        "params": {
            "mode": 1,
            "tokenList": [{"exchangeType": 1, "tokens": token_ids}],
        },
    })


def _build_unsubscribe(token_ids: list[str]) -> str:
    return json.dumps({
        "correlationID": "ws_unsub",
        "action": 0,
        "params": {
            "mode": 1,
            "tokenList": [{"exchangeType": 1, "tokens": token_ids}],
        },
    })


# ── WebSocket runner (runs in background thread) ───────────────────────────────

def _run_stream(
    jwt_token: str,
    api_key: str,
    client_code: str,
    feed_token: str,
    token_to_symbol: dict[str, str],
    on_update: Callable[[str, float], None] | None = None,
):
    """
    Blocking WebSocket loop. Call in a daemon thread.
    Reconnects automatically on disconnect until _stop_event is set.
    """
    try:
        import websocket
    except ImportError:
        log.error("websocket-client not installed. Run: pip install websocket-client")
        return

    headers = {
        "Authorization": jwt_token,
        "x-api-key":     api_key,
        "x-client-code": client_code,
        "x-feed-token":  feed_token,
    }
    token_ids = list(token_to_symbol.keys())
    subscribe_msg = _build_subscribe(token_ids)

    def on_open(ws):
        log.info(f"WebSocket connected. Subscribing to {len(token_ids)} tokens…")
        ws.send(subscribe_msg)

    def on_message(ws, message):
        if isinstance(message, str):
            if message == "pong":
                log.debug("pong received")
            else:
                log.debug(f"Text frame: {message[:120]}")
            return

        parsed = _parse_ltp_packet(message)
        if not parsed:
            return

        sym = token_to_symbol.get(parsed["token"])
        if not sym:
            return

        ltp_cache[sym] = {"ltp": parsed["ltp"], "ts": parsed["ts_ms"], "token": parsed["token"]}
        if on_update:
            on_update(sym, parsed["ltp"])

    def on_error(ws, error):
        log.error(f"WebSocket error: {error}")

    def on_close(ws, code, msg):
        log.info(f"WebSocket closed (code={code}): {msg}")

    while not _stop_event.is_set():
        ws = websocket.WebSocketApp(
            _WS_URL,
            header=headers,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        # Heartbeat thread
        def _heartbeat(ws_ref):
            while not _stop_event.is_set():
                time.sleep(_HEARTBEAT_INTERVAL)
                try:
                    if ws_ref.sock and ws_ref.sock.connected:
                        ws_ref.send("ping")
                        log.debug("ping sent")
                except Exception:
                    break

        hb = threading.Thread(target=_heartbeat, args=(ws,), daemon=True)
        hb.start()

        ws.run_forever(ping_interval=0)  # we handle heartbeat manually

        if _stop_event.is_set():
            break
        log.info(f"Reconnecting in {_RECONNECT_DELAY}s…")
        time.sleep(_RECONNECT_DELAY)


# ── Public API ─────────────────────────────────────────────────────────────────

def start_stream(
    jwt_token: str,
    api_key: str,
    client_code: str,
    feed_token: str,
    token_map: dict[str, dict],
    on_update: Callable[[str, float], None] | None = None,
) -> bool:
    """
    Start the WebSocket stream in a background daemon thread.

    Args:
        jwt_token   : JWT access token from Angel One
        api_key     : Angel One API key
        client_code : Angel One client code (e.g. R123456)
        feed_token  : feed_token from generateSession response
        token_map   : {symbol: {"token": "<numeric_token_id>", ...}}
                      as returned by stock_master.lookup_tokens()
        on_update   : optional callback(symbol, ltp) fired on each LTP tick

    Returns True if thread started, False if already running or tokens missing.
    """
    global _stream_thread, _token_to_symbol

    if is_running():
        log.info("Stream already running.")
        return False

    # Build reverse map token_id → symbol
    rev = {}
    for sym, info in token_map.items():
        tid = info.get("token")
        if tid:
            rev[str(tid)] = sym

    if not rev:
        log.error("No valid token IDs found — run lookup_tokens() first.")
        return False

    _token_to_symbol = rev
    _stop_event.clear()

    _stream_thread = threading.Thread(
        target=_run_stream,
        args=(jwt_token, api_key, client_code, feed_token, rev, on_update),
        daemon=True,
        name="ao_ws_stream",
    )
    _stream_thread.start()
    log.info(f"Stream thread started for {len(rev)} tokens.")
    return True


def stop_stream():
    """Signal the background WebSocket thread to exit and clear LTP cache."""
    global _stream_thread
    _stop_event.set()
    _stream_thread = None
    log.info("Stream stop requested.")


def is_running() -> bool:
    return _stream_thread is not None and _stream_thread.is_alive()


def get_ltp(symbol: str) -> float | None:
    """Return latest LTP for a symbol, or None if not yet received."""
    entry = ltp_cache.get(symbol)
    return entry["ltp"] if entry else None


def get_all_ltp() -> dict[str, float]:
    """Return {symbol: ltp} for all symbols that have received at least one tick."""
    return {sym: v["ltp"] for sym, v in ltp_cache.items()}


def get_ltp_snapshot() -> list[dict]:
    """
    Return a list of dicts sorted by symbol, suitable for a Streamlit dataframe:
      [{"Symbol": ..., "LTP ₹": ..., "Last Updated": ...}, ...]
    """
    from datetime import datetime
    rows = []
    for sym, v in sorted(ltp_cache.items()):
        ts = v.get("ts")
        try:
            updated = datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S") if ts else "—"
        except Exception:
            updated = "—"
        rows.append({"Symbol": sym, "LTP ₹": v["ltp"], "Last Updated": updated})
    return rows
