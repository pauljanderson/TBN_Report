"""Unit test for dump_kalshi_recon packing. No live secrets. No orders."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import dump_kalshi_recon as dump  # noqa: E402


def test_build_pack_writes_core_keys():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        drive = tmp_path / "drive"
        raw = tmp_path / "raw"
        drive.mkdir()
        raw.mkdir()

        def fake_balance():
            return 200, json.dumps({"balance_dollars": "12.3400", "portfolio_value": 500})

        def fake_signed(method, path, body=None, query=None, timeout=30):
            assert method == "GET"
            if path.endswith("/positions"):
                return 200, json.dumps({"market_positions": [{"ticker": "KXTEST-YES", "position_fp": "1.00"}]})
            if path.endswith("/settlements"):
                return 200, json.dumps({"settlements": [{"ticker": "KXTEST-YES"}], "cursor": ""})
            raise AssertionError(path)

        def fake_fills(query=None, timeout=30):
            return 200, json.dumps({"fills": [{"order_id": "abc", "ticker": "KXTEST-YES"}], "cursor": ""})

        with patch.object(dump.kalshi_private, "balance", side_effect=fake_balance), patch.object(
            dump.kalshi_private, "signed_call", side_effect=fake_signed
        ), patch.object(dump.kalshi_private, "get_fills", side_effect=fake_fills), patch.object(
            dump, "DRIVE_STAMP", drive
        ), patch.object(dump, "RAW_DIR", raw), patch.object(
            dump.kalshi_private, "KEY_PATH", tmp_path / "kalshi_private_key.pem"
        ), patch.object(
            dump.kalshi_private, "KEY_ID_PATH", tmp_path / "kalshi_key_id.txt"
        ):
            (tmp_path / "kalshi_private_key.pem").write_text("dummy", encoding="utf-8")
            (tmp_path / "kalshi_key_id.txt").write_text("00000000-0000-0000-0000-000000000000\n", encoding="utf-8")
            pack = dump.build_pack(days=3)

        assert pack["days"] == 3
        assert pack["balance"]["balance_usd"] == "12.3400"
        assert pack["fills"]["n"] == 1
        assert pack["settlements"]["n"] == 1
        assert pack["positions"]["ok"] is True
        assert pack["ready_for_cloud_agent"] is True
        assert "same_direction_stacks" in pack
        assert "venue_settlement_pnl_usd" in pack


if __name__ == "__main__":
    test_build_pack_writes_core_keys()
    print("test_dump_kalshi_recon ok")
