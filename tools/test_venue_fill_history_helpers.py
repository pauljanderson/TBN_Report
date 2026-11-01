"""Mock-HTTP tests for documented fill-history helpers. No live secrets. No orders."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import gemini_private  # noqa: E402
import kalshi_private  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402


class FakeHTTP:
    def __init__(self, status=200, body="{}"):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _urlopen_capture(seen, status=200, body="{}"):
    def fake_urlopen(req, timeout=30):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        return FakeHTTP(status, body)

    return fake_urlopen


def test_kalshi_get_fills_documented_path():
    seen = {}
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    with patch.object(kalshi_private, "load_key_id", return_value="test-key-id"), patch.object(
        kalshi_private, "load_private_key", return_value=key
    ), patch.object(kalshi_private.urllib.request, "urlopen", _urlopen_capture(seen, 200, '{"fills":[],"cursor":""}')):
        status, body = kalshi_private.get_fills({"min_ts": 123, "limit": 10})
    assert status == 200
    assert json.loads(body)["fills"] == []
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://api.elections.kalshi.com/trade-api/v2/portfolio/fills?")
    assert "min_ts=123" in seen["url"]
    assert "limit=10" in seen["url"]
    assert "/portfolio/orders" not in seen["url"]


def test_gemini_get_order_history_documented_path():
    seen = {}
    payload = {"orders": [{"symbol": "GEMI-X", "filledQuantity": "1", "avgExecutionPrice": "0.44"}]}
    with patch.object(gemini_private, "_load_secret", return_value="test-secret"), patch.object(
        gemini_private, "next_nonce", return_value="1700000000"
    ), patch.object(gemini_private.urllib.request, "urlopen", _urlopen_capture(seen, 200, json.dumps(payload))):
        status, body = gemini_private.get_order_history(
            {"status": "filled", "from": 1, "to": 2, "limit": 1000}
        )
    assert status == 200
    assert json.loads(body)["orders"][0]["filledQuantity"] == "1"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.gemini.com/v1/prediction-markets/orders/history"
    assert "/v1/order/new" not in seen["url"]


def test_polymarket_us_get_activities_documented_path():
    seen = {}
    body = {"activities": [], "eof": True}
    headers = {"X-PM-Access-Key": "id", "X-PM-Timestamp": "1", "X-PM-Signature": "sig"}
    with patch.object(polymarket_us_live, "sign_request", return_value=headers), patch.object(
        polymarket_us_live.urllib.request, "urlopen", _urlopen_capture(seen, 200, json.dumps(body))
    ):
        status, text = polymarket_us_live.get_activities(
            {"limit": 50, "types": ["ACTIVITY_TYPE_TRADE"]}
        )
    assert status == 200
    assert json.loads(text)["eof"] is True
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://api.polymarket.us/v1/portfolio/activities?")
    assert "types=ACTIVITY_TYPE_TRADE" in seen["url"]
    assert "clob.polymarket.com" not in seen["url"]
    assert "polymarketexchange.com" not in seen["url"]


def test_novig_list_fills_documented_path():
    seen = {}
    headers = {"Novig-Key-Id": "id", "Novig-Timestamp": "1", "Novig-Signature": "sig"}
    with patch.object(novig_live, "signature_headers", return_value=headers), patch.object(
        novig_live.urllib.request, "urlopen", _urlopen_capture(seen, 200, '{"items":[]}')
    ), patch.object(novig_live.venue_pace, "wait_turn", return_value=None):
        status, text = novig_live.list_fills({"limit": 100, "startsAfter": 1})
    assert status == 200
    assert json.loads(text)["items"] == []
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://api.novig.com/v3/portfolio/fills?")
    assert "limit=100" in seen["url"]
    assert "/v3/orders" not in seen["url"] or seen["url"].startswith("https://api.novig.com/v3/portfolio/fills")


def test_helpers_are_read_only_paths():
    assert kalshi_private.FILLS_PATH == "/trade-api/v2/portfolio/fills"
    assert gemini_private.HISTORY_PATH == "/v1/prediction-markets/orders/history"
    assert polymarket_us_live.ACTIVITIES_PATH == "/v1/portfolio/activities"
    assert novig_live.FILLS_PATH == "/v3/portfolio/fills"


if __name__ == "__main__":
    test_kalshi_get_fills_documented_path()
    test_gemini_get_order_history_documented_path()
    test_polymarket_us_get_activities_documented_path()
    test_novig_list_fills_documented_path()
    test_helpers_are_read_only_paths()
    print("venue fill-history helper tests ok")
