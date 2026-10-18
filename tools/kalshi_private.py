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
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
KEY_PATH = SECRETS / "kalshi_private_key.pem"
KEY_ID_PATH = SECRETS / "kalshi_key_id.txt"
BASE = "https://api.elections.kalshi.com"


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


def signed_call(method: str, path: str, body: dict | None = None, query: dict | None = None) -> tuple[int, str]:
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
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail


def signed_get(path: str) -> tuple[int, str]:
    """GET a trade-api path. path starts with /trade-api/v2 and has no query string."""
    return signed_call("GET", path)


def balance() -> tuple[int, str]:
    return signed_get("/trade-api/v2/portfolio/balance")


def balance_usd() -> tuple[int, str | None]:
    """HTTP status and USD cash, if the balance body is the usual cent count."""
    status, body = balance()
    if status != 200:
        return status, None
    try:
        data = json.loads(body)
        cents = data.get("balance")
        if cents is None:
            return status, None
        return status, f"{int(cents) / 100:.2f}"
    except (TypeError, ValueError, json.JSONDecodeError):
        return status, None


if __name__ == "__main__":
    status, body = balance()
    print(status)
    print(body)
