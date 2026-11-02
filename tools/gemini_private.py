"""Signed Gemini calls for Paul's own account.

Balance reads stay the default command. Prediction-market orders go through
private_call and are used only by tools/live_lock_orders.py. Spot order paths
stay refused. Secrets stay in secrets/ and are not printed.

Gemini soft-disable (quote-only / no-send): keep collecting Gemini books for
price discovery, but refuse new prediction-market POSTs until Paul flips the
flag. Same spirit as Novig NOVIG_ORDERS_ENABLED. Re-enable without a code hunt:
set GEMINI_ORDERS_ENABLED = True here, or set top-level "gemini_orders": true
in local systems.json (systems.json wins when present).
"""
from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BALANCES_PATH = "/v1/balances"
BALANCES_URL = "https://api.gemini.com/v1/balances"
PUBLIC_URL = "https://api.gemini.com/v1/symbols"
# Soft-disable send. False = quote-only (default). True only when Gemini again
# wins real after-fee opportunities. systems.json "gemini_orders" overrides.
GEMINI_ORDERS_ENABLED = False
ORDER_PLACE_PATH = "/v1/prediction-markets/order"
# Seconds added to local time so the nonce matches Gemini's Date header.
_CLOCK_OFFSET_SEC: float | None = None
ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / "secrets" / "gemini_api_key.txt"
SECRET_FILE = ROOT / "secrets" / "gemini_api_secret.txt"

_ORDER_MARKERS = (
    "/v1/order",
    "/v1/orders",
    "neworder",
    "cancelorder",
    "cancelall",
)


def _refuse_orders(path: str) -> None:
    lowered = path.lower().replace("_", "")
    if path != BALANCES_PATH or any(marker.replace("_", "") in lowered for marker in _ORDER_MARKERS):
        print("Refusing order path. This tool only reads balances.")
        raise SystemExit(2)


def _systems_json_orders_override() -> bool | None:
    """Optional top-level systems.json gemini_orders. None = use module flag."""
    try:
        from prediction_paths import RAW_DIR

        path = RAW_DIR / "systems.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or "gemini_orders" not in data:
        return None
    return bool(data.get("gemini_orders"))


def orders_live() -> bool:
    """True when Gemini may be selected as a send venue / POST new orders.

    Quote collection, compare, and price discovery ignore this. Cancel and
    history reads stay allowed so open leftovers can still be cleaned up.
    """
    override = _systems_json_orders_override()
    if override is not None:
        return override
    return bool(GEMINI_ORDERS_ENABLED)


def _load_secret(path: Path) -> str:
    if not path.is_file():
        print(f"Missing secret file: {path.name}")
        raise SystemExit(2)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        print(f"Secret file is empty: {path.name}")
        raise SystemExit(2)
    upper = text.upper()
    if "REPLACE" in upper or "YOUR_" in upper or "TODO" in upper or "CHANGEME" in upper or "PASTE" in upper:
        print(f"Secret file looks like a placeholder: {path.name}")
        raise SystemExit(2)
    return text


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    return out


def _clock_offset_sec() -> float:
    """server_time - local_utc, from the public Date header. Cached for this process."""
    global _CLOCK_OFFSET_SEC
    if _CLOCK_OFFSET_SEC is not None:
        return _CLOCK_OFFSET_SEC
    request = urllib.request.Request(PUBLIC_URL, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        local_utc = time.time()
        date_header = response.headers.get("Date") or ""
    server = email.utils.parsedate_to_datetime(date_header)
    _CLOCK_OFFSET_SEC = server.timestamp() - local_utc
    return _CLOCK_OFFSET_SEC


def _nonce() -> str:
    # Gemini time-based nonce is Unix seconds as a string, within 30s of server time.
    return str(int(time.time() + _clock_offset_sec()))


def _sign(api_secret: str, nonce: str) -> tuple[str, str]:
    _refuse_orders(BALANCES_PATH)
    # Balances body: request, nonce (Unix seconds string), account (string).
    # https://developer.gemini.com/trading/rest-api/fund-management/get-available-balances
    payload = {
        "request": BALANCES_PATH,
        "nonce": nonce,
        "account": "primary",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    signature = hmac.new(
        api_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha384,
    ).hexdigest()
    return encoded, signature


def next_nonce() -> str:
    """Unix-second nonce that only increases, including across processes."""
    from prediction_paths import RAW_DIR

    nonce_path = RAW_DIR / "gemini_nonce.txt"
    lock_path = nonce_path.with_suffix(".lock")
    nonce_path.parent.mkdir(parents=True, exist_ok=True)
    from venue_pace import FileLock

    with FileLock(lock_path):
        last = 0
        if nonce_path.is_file():
            try:
                last = int(nonce_path.read_text(encoding="utf-8").strip() or "0")
            except ValueError:
                last = 0
        current = int(time.time() + _clock_offset_sec())
        if current <= last:
            current = last + 1
        nonce_path.write_text(str(current), encoding="utf-8")
        return str(current)


def private_call(
    path: str,
    extra: dict | None,
    http_method: str,
    record: dict | None = None,
    timeout: float = 30,
) -> tuple[int, str]:
    """Signed prediction-market or balance call. Empty HTTP body. Payload is in the header.

    Spot /v1/order paths are refused. `record`, when passed, receives the JSON
    object that is base64-encoded. That object has no API key and no signature.
    New prediction-market order POSTs refuse when orders_live() is False.
    """
    allowed = path == BALANCES_PATH or path.startswith("/v1/prediction-markets/")
    if not allowed or any(marker.replace("_", "") in path.lower().replace("_", "") for marker in _ORDER_MARKERS):
        raise ValueError("refusing a non prediction-market order path")
    if path.rstrip("/") == ORDER_PLACE_PATH and str(http_method or "").upper() == "POST":
        if not orders_live():
            if record is not None:
                record["request"] = {"request": path, "skipped": "gemini orders off (quote only)"}
            return 0, '{"result":"error","reason":"gemini orders off (quote only)"}'
    api_key = _load_secret(KEY_FILE)
    api_secret = _load_secret(SECRET_FILE)
    nonce = next_nonce()
    # Balance reads take a string nonce. Prediction-market routes take a JSON number.
    # Nonce is Unix seconds, never milliseconds. This key names the primary account.
    payload = {
        "request": path,
        "nonce": int(nonce) if path.startswith("/v1/prediction-markets/") else nonce,
        "account": "primary",
    }
    if extra:
        payload.update(extra)
    if record is not None:
        record["request"] = json.loads(json.dumps(payload))
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    signature = hmac.new(api_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha384).hexdigest()
    headers = {
        "Content-Type": "text/plain",
        "Content-Length": "0",
        "X-GEMINI-APIKEY": api_key,
        "X-GEMINI-PAYLOAD": encoded,
        "X-GEMINI-SIGNATURE": signature,
        "Cache-Control": "no-cache",
    }
    request = urllib.request.Request(
        "https://api.gemini.com" + path,
        data=None if http_method == "GET" else b"",
        headers=headers,
        method=http_method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail


HISTORY_PATH = "/v1/prediction-markets/orders/history"
# Docs: https://developer.gemini.com/rest-api/prediction-markets/order-management/get-order-history


def get_order_history(extra: dict | None = None, timeout: float = 30) -> tuple[int, str]:
    """POST /v1/prediction-markets/orders/history. Read-only. Does not place or cancel."""
    return private_call(HISTORY_PATH, extra, "POST", timeout=timeout)


def _post(api_key: str, encoded: str, signature: str) -> tuple[int, str]:
    # Payload lives in X-GEMINI-PAYLOAD. The HTTP body stays empty.
    # https://developer.gemini.com/authentication/api-key
    headers = {
        "Content-Type": "text/plain",
        "Content-Length": "0",
        "X-GEMINI-APIKEY": api_key,
        "X-GEMINI-PAYLOAD": encoded,
        "X-GEMINI-SIGNATURE": signature,
        "Cache-Control": "no-cache",
    }
    request = urllib.request.Request(
        BALANCES_URL,
        data=b"",
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail


def _plain_reason(reason: str, message: str) -> str | None:
    blob = f"{reason} {message}".lower()
    if "invalidnonce" in blob:
        return "Gemini rejected the nonce. It must be a timestamp string that only increases."
    if "invalidsignature" in blob:
        return "Gemini rejected the signature. The secret did not match this payload."
    if "invalidapikey" in blob:
        return "Gemini rejected the API key."
    if "missingaccounts" in blob:
        return "Gemini still wants an account name on this balances read."
    if "missingrole" in blob:
        return "This API key is missing the role required to read balances."
    if "whitelist" in blob or "ip address" in blob or "ip filter" in blob or "not allowed from" in blob:
        return "The trusted-IP list does not include this machine."
    return None


def _print_result(status: int, body: str, secrets: tuple[str, ...]) -> None:
    print(f"HTTP {status}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print("Gemini response was not JSON.")
        return
    if isinstance(data, dict) and (data.get("result") == "error" or "reason" in data or "message" in data):
        reason = _redact(str(data.get("reason") or ""), secrets)
        message = _redact(str(data.get("message") or ""), secrets)
        if reason:
            print(f"reason: {reason}")
        if message and message != reason:
            print(f"message: {message}")
        plain = _plain_reason(reason, message)
        if plain:
            print(plain)
        return
    if isinstance(data, list):
        print(f"currency rows: {len(data)}")
        for row in data:
            if not isinstance(row, dict):
                continue
            currency = str(row.get("currency") or "").upper()
            if currency in ("USD", "GUSD"):
                print(f"{currency} available: {row.get('available')}")
        return
    print("Unexpected Gemini response shape.")


def main() -> None:
    _refuse_orders(BALANCES_PATH)
    api_key = _load_secret(KEY_FILE)
    api_secret = _load_secret(SECRET_FILE)
    nonce = _nonce()
    encoded, signature = _sign(api_secret, nonce)
    status, body = _post(api_key, encoded, signature)
    if "invalidnonce" in body.lower():
        print(f"offset_server_minus_local_sec: {_clock_offset_sec():.3f}")
    _print_result(status, body, (api_key, api_secret, encoded, signature))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — never leak request material
        print(f"Request failed: {type(exc).__name__}")
        sys.exit(1)
