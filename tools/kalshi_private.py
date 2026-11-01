"""Signed Kalshi calls for Paul's own account.

The private key and the key id stay in secrets/, which is gitignored.
Balance reads stay the default. Limit orders are used only by the live lock
path in tools/live_lock_orders.py.

Kalshi's download is only the private key. The key id is the UUID shown
next to that key in Account Settings. Put that UUID, alone, in
secrets/kalshi_key_id.txt.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
KEY_PATH = SECRETS / "kalshi_private_key.pem"
KEY_ID_PATH = SECRETS / "kalshi_key_id.txt"
BASE = "https://api.elections.kalshi.com"

try:
    from prediction_paths import RAW_DIR as RAW
except Exception:
    RAW = ROOT / "local" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017" / "raw"

BALANCE_CACHE = RAW / "kalshi_balance_cache.json"
BALANCE_FAIL_LOG = RAW / "kalshi_balance_fail.log"
# Short GET race guard only. Send-path cash is venue_cash_local (hourly confirm).
BALANCE_CACHE_TTL_SEC = 8.0
BALANCE_FAIL_LOG_SEC = 300.0
BACKOFF_SEC = {401: 300.0, 429: 60.0, 500: 30.0, 502: 30.0, 503: 30.0}
_last_fail_log_at = 0.0


def load_key_id() -> str:
    if not KEY_ID_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {KEY_ID_PATH}. Put the key id UUID on one line. Do not paste the private key."
        )
    key_id = KEY_ID_PATH.read_text(encoding="utf-8").strip()
    if not key_id or key_id.startswith("REPLACE"):
        raise FileNotFoundError(
            f"{KEY_ID_PATH} still needs the key id UUID from the Kalshi API keys page."
        )
    return key_id


def load_private_key() -> Ed25519PrivateKey:
    if not KEY_PATH.is_file():
        raise FileNotFoundError(f"Missing {KEY_PATH}")
    key = serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("Kalshi key file is not an Ed25519 private key")
    return key


def signed_call(
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
    timeout: float = 30,
) -> tuple[int, str]:
    """Signed trade-api call. The signature covers method and path, not the query or body."""
    if "?" in path:
        raise ValueError("sign the path only; pass query separately")
    if not path.startswith("/trade-api/v2/"):
        raise ValueError("path must start with /trade-api/v2/")
    key_id = load_key_id()
    private_key = load_private_key()
    timestamp = str(int(time.time() * 1000))
    signature = base64.b64encode(private_key.sign(f"{timestamp}{method}{path}".encode("utf-8"))).decode("ascii")
    url = BASE + path
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    data = None
    headers = {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail


def signed_get(path: str) -> tuple[int, str]:
    """GET a trade-api path. path starts with /trade-api/v2 and has no query string."""
    return signed_call("GET", path)


FILLS_PATH = "/trade-api/v2/portfolio/fills"
# Docs: https://docs.kalshi.com/api-reference/portfolio/get-fills


def get_fills(query: dict | None = None, timeout: float = 30) -> tuple[int, str]:
    """GET /trade-api/v2/portfolio/fills. Read-only. Does not place or cancel."""
    return signed_call("GET", FILLS_PATH, query=query, timeout=timeout)


def _as_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return None
    return number


def parse_balance_usd(payload) -> Decimal | None:
    """USD cash from GetBalance JSON. Prefer balance_dollars; never use portfolio_value.

    Live 2026-10-25 schema: balance (int cents), balance_dollars (fixed-point string),
    portfolio_value (int cents of positions), balance_breakdown, updated_ts.
    """
    data = payload
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    for key in ("balance_dollars", "available_balance", "available"):
        number = _as_decimal(data.get(key))
        if number is not None and number >= 0:
            return number
    raw = data.get("balance")
    if raw in (None, ""):
        return None
    if isinstance(raw, str) and "." in raw.strip():
        number = _as_decimal(raw)
        return number if number is not None and number >= 0 else None
    if isinstance(raw, float):
        number = _as_decimal(raw)
        return number if number is not None and number >= 0 else None
    try:
        cents = int(raw)
    except (TypeError, ValueError):
        number = _as_decimal(raw)
        if number is None or number < 0:
            return None
        return number / Decimal(100)
    if cents < 0:
        return None
    return Decimal(cents) / Decimal(100)


def _file_lock(path: Path):
    try:
        import venue_pace

        return venue_pace.FileLock(path)
    except Exception:
        return None


def _read_balance_cache() -> dict:
    try:
        data = json.loads(BALANCE_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_balance_cache(row: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    text = json.dumps(row, indent=2, default=str) + "\n"
    lock = _file_lock(BALANCE_CACHE.with_suffix(".lock"))
    if lock is None:
        BALANCE_CACHE.write_text(text, encoding="utf-8")
        return
    with lock:
        BALANCE_CACHE.write_text(text, encoding="utf-8")


def reset_balance_cache_for_tests() -> None:
    """Tests only. Clears the shared GET cache so mocked HTTP is used."""
    global _last_fail_log_at
    _last_fail_log_at = 0.0
    try:
        if BALANCE_CACHE.is_file():
            BALANCE_CACHE.unlink()
    except OSError:
        pass


def _note_balance_fail(status: int, parsed: bool, keys: list[str]) -> None:
    """First failure, then at most once per 5 minutes. No dollar amounts. No secrets."""
    global _last_fail_log_at
    now = time.time()
    if _last_fail_log_at and (now - _last_fail_log_at) < BALANCE_FAIL_LOG_SEC:
        return
    _last_fail_log_at = now
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        line = (
            f"{stamp} kalshi balance http={status} parsed={'yes' if parsed else 'no'} "
            f"keys={','.join(keys)}\n"
        )
        with BALANCE_FAIL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return


def _wait_kalshi_slot() -> bool:
    try:
        import venue_pace

        return bool(venue_pace.wait_turn("kalshi"))
    except Exception:
        return True


def balance() -> tuple[int, str]:
    return signed_get("/trade-api/v2/portfolio/balance")


def balance_usd() -> tuple[int, str | None]:
    """HTTP status and USD cash. Venue GET with 429/401/5xx backoff.

    Send path must use venue_cash_local (local slip + hourly confirm). This
    helper is the GET used by that hourly confirm. A few-second success cache
    only covers simultaneous children hitting the same confirm slot.
    """
    now = time.time()
    cached = _read_balance_cache()
    usd = cached.get("usd")
    cached_at = float(cached.get("at") or 0)
    cached_http = int(cached.get("http") or 0)
    backoff_until = float(cached.get("backoff_until") or 0)
    if cached_http == 200 and usd not in (None, "") and (now - cached_at) < BALANCE_CACHE_TTL_SEC:
        return 200, str(usd)
    if backoff_until > now:
        return cached_http or 429, None
    slotted = _wait_kalshi_slot()
    if slotted is False:
        if cached_http == 200 and usd not in (None, ""):
            return 200, str(usd)
        return cached_http or 0, None
    try:
        now = time.time()
        cached = _read_balance_cache()
        usd = cached.get("usd")
        cached_at = float(cached.get("at") or 0)
        cached_http = int(cached.get("http") or 0)
        backoff_until = float(cached.get("backoff_until") or 0)
        if cached_http == 200 and usd not in (None, "") and (now - cached_at) < BALANCE_CACHE_TTL_SEC:
            return 200, str(usd)
        if backoff_until > now:
            return cached_http or 429, None
        status, body = balance()
        keys: list[str] = []
        parsed = None
        if status == 200:
            parsed = parse_balance_usd(body)
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                keys = sorted(str(key) for key in data.keys())
            usd_text = None if parsed is None else format(parsed, "f")
            row = {
                "at": now,
                "http": status,
                "usd": usd_text,
                "keys": keys,
                "backoff_until": 0,
            }
            _write_balance_cache(row)
            if parsed is None:
                _note_balance_fail(status, False, keys)
                return status, None
            return status, usd_text
        wait = BACKOFF_SEC.get(status, 15.0)
        row = {
            "at": now,
            "http": status,
            "usd": cached.get("usd"),
            "keys": keys,
            "backoff_until": now + wait,
        }
        _write_balance_cache(row)
        _note_balance_fail(status, False, keys)
        return status, None
    finally:
        try:
            import venue_pace

            venue_pace.release_turn("kalshi")
        except Exception:
            pass


if __name__ == "__main__":
    status, body = balance()
    keys = []
    parsed = None
    try:
        data = json.loads(body) if body else {}
        if isinstance(data, dict):
            keys = sorted(data.keys())
            parsed = parse_balance_usd(data)
    except Exception:
        data = None
    print(status)
    print("keys", keys)
    print("parsed_ge0", parsed is not None and parsed >= 0)
