"""dashboard_stamp_gate: Size @ price on writer + living HTML; no stale Gibson 0.84."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import dashboard_stamp_gate as gate  # noqa: E402
import write_dashboard as d  # noqa: E402


STALE_GIBSON_SNIPPET = """
<table><tr>
<td>2026-11-03 01:32:15.686 ET</td><td>A Lock gap</td>
<td>Gibson vs Oliynykova</td><td>WTA</td><td>polymarket</td>
<td>Yes Oleksandra Oliynykova</td><td class="num">0.8400</td>
</tr></table>
"""

FRESH_GIBSON_SNIPPET = """
<p>Corrected Gibson/Oliynykova lock (+$0.01), not a 1.67 mistake.</p>
<table><tr>
<td>Gibson vs Oliynykova</td><td>polymarket</td><td class="num">0.1600</td>
<td>Size @ price</td>
</tr></table>
"""


def test_writer_trade_headers_include_size_at_price():
    assert any(h[0] == "Size @ price" for h in d.TRADE_HEADERS)
    assert gate.writer_has_size_at_price() is True


def test_stamp_missing_size_at_price_fails():
    html = "<html><body><h2>Trades today</h2><th>Wire</th><th>Fee</th></body></html>"
    assert gate.stamp_has_size_at_price(html) is False
    assert gate.stamp_has_stale_gibson_poly_wire(html) is False


def test_stamp_with_size_at_price_passes_marker():
    html = "<html><th>Size @ price</th><p>Size @ price is book depth</p></html>"
    assert gate.stamp_has_size_at_price(html) is True


def test_stale_gibson_poly_wire_detected():
    assert gate.stamp_has_stale_gibson_poly_wire(STALE_GIBSON_SNIPPET) is True
    assert gate.stamp_has_stale_gibson_poly_wire(FRESH_GIBSON_SNIPPET) is False


def test_check_writer_only_ok_when_no_stamp(tmp_path: Path | None = None):
    missing = Path("/tmp/dashboard_stamp_gate_missing_dashboard.html")
    if missing.exists():
        missing.unlink()
    report = gate.check(dashboard_html=missing, require_stamp=False)
    assert report["writer_size_at_price"] is True
    assert report["stamp_exists"] is False
    assert report["ok"] is True


def test_check_require_stamp_fails_when_missing():
    missing = Path("/tmp/dashboard_stamp_gate_missing_dashboard.html")
    if missing.exists():
        missing.unlink()
    report = gate.check(dashboard_html=missing, require_stamp=True)
    assert report["ok"] is False
    assert any("missing stamp" in f for f in report["failures"])


def test_check_stale_stamp_fails(tmp_path=None):
    path = Path("/tmp/dashboard_stamp_gate_stale.html")
    path.write_text(
        "<html><th>Wire</th>" + STALE_GIBSON_SNIPPET + "</html>",
        encoding="utf-8",
    )
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["ok"] is False
    assert report["stamp_size_at_price"] is False
    assert report["stamp_stale_gibson_wire"] is True
    blob = " ".join(report["failures"])
    assert "Size @ price" in blob
    assert "Gibson" in blob


def test_check_fresh_stamp_passes():
    path = Path("/tmp/dashboard_stamp_gate_fresh.html")
    path.write_text(
        "<html><th>Size @ price</th>" + FRESH_GIBSON_SNIPPET + "</html>",
        encoding="utf-8",
    )
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["ok"] is True
    assert report["stamp_size_at_price"] is True
    assert report["stamp_stale_gibson_wire"] is False


if __name__ == "__main__":
    test_writer_trade_headers_include_size_at_price()
    test_stamp_missing_size_at_price_fails()
    test_stamp_with_size_at_price_passes_marker()
    test_stale_gibson_poly_wire_detected()
    test_check_writer_only_ok_when_no_stamp()
    test_check_require_stamp_fails_when_missing()
    test_check_stale_stamp_fails()
    test_check_fresh_stamp_passes()
    print("test_dashboard_stamp_gate ok")
