"""dashboard_stamp_gate: Size @ price on A today; no Gibson 0.84; no $2.40 today."""
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

# Drive failure mode: Size @ price header exists globally, but Trades today A rows
# show em-dash / blank, Gibson still 0.84, today A P&L +$2.40.
DRIVE_FAIL_HTML = """
<html><body>
<th>Size @ price</th>
<h2>Today</h2>
<div data-window="today">
<div class="kpi"><div class="kpi-label">With-fee P&amp;L</div><div class="kpi-value">+$2.40</div></div>
<table>
<tr><th>System</th><th>N sent</th><th>With-fee P&amp;L</th></tr>
<tr><td>A Lock gap</td><td>6</td><td>+$2.40</td></tr>
</table>
</div>
<div data-window="inception" hidden>
<div class="kpi"><div class="kpi-label">With-fee P&amp;L</div><div class="kpi-value">+$16.67</div></div>
</div>
<h2>Trades today</h2>
<table>
<tr>
<th>When ET</th><th>System</th><th>Type</th><th>Match</th><th>League</th>
<th>Venue</th><th>Side</th><th>Wire</th><th>Size @ price</th><th>Fee</th>
<th>After-fee</th><th>HTTP</th><th>Filled</th><th>Outcome</th>
<th>Failure kind</th><th>P&amp;L if settled</th>
</tr>
<tr>
<td>2026-11-03 01:32:15 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Gibson vs Oliynykova</td><td>WTA</td><td>polymarket</td>
<td>Yes Oleksandra Oliynykova</td><td class="num">0.8400</td><td>—</td>
<td>0.0000</td><td>0.8400</td><td>HTTP</td><td>yes</td><td>settled win</td>
<td>—</td><td>+$0.16</td></tr>
<tr>
<td>2026-11-03 01:32:15 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Gibson vs Oliynykova</td><td>WTA</td><td>kalshi</td>
<td>No Oleksandra Oliynykova</td><td class="num">0.8200</td><td>—</td>
<td>0.0104</td><td>0.8304</td><td>HTTP</td><td>yes</td><td>settled win</td>
<td>—</td><td>+$0.17</td></tr>
<tr>
<td>2026-11-03 01:28:18 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Imamura vs Leong</td><td>ATP</td><td>polymarket</td>
<td>Yes Leong</td><td>0.4800</td><td>—</td><td>0</td><td>0.4800</td>
<td>HTTP</td><td>yes</td><td>settled win</td><td>—</td><td>+$0.52</td></tr>
<tr>
<td>2026-11-03 01:28:17 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Imamura vs Leong</td><td>ATP</td><td>kalshi</td>
<td>No Leong</td><td>0.4500</td><td>—</td><td>0.0174</td><td>0.4674</td>
<td>HTTP</td><td>yes</td><td>settled win</td><td>—</td><td>+$0.53</td></tr>
<tr>
<td>2026-11-03 01:15:07 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Teichmann vs Garland</td><td>WTA</td><td>polymarket</td>
<td>Yes Garland</td><td>0.3300</td><td>—</td><td>0</td><td>0.3300</td>
<td>HTTP</td><td>yes</td><td>settled win</td><td>—</td><td>+$0.67</td></tr>
<tr>
<td>2026-11-03 01:15:06 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Teichmann vs Garland</td><td>WTA</td><td>kalshi</td>
<td>Yes Garland</td><td>0.6400</td><td>—</td><td>0.0162</td><td>0.6562</td>
<td>HTTP</td><td>yes</td><td>settled win</td><td>—</td><td>+$0.34</td></tr>
</table>
<h2>Full book (every posted send)</h2>
<table><tr><th>Size @ price</th></tr></table>
</body></html>
"""

DRIVE_FIXED_HTML = """
<html><body>
<h2>Today</h2>
<div data-window="today">
<p class="window-banner" data-pnl-scope="today">Showing: <strong>Today with-fee P&amp;L</strong></p>
<div class="kpi"><div class="kpi-label">Today with-fee P&amp;L (since midnight ET only)</div>
<div class="kpi-value">+$0.07</div></div>
<table>
<tr><th>System</th><th>N sent</th><th>With-fee P&amp;L</th></tr>
<tr><td>A Lock gap</td><td>6</td><td>+$0.07</td></tr>
</table>
</div>
<div data-window="inception" hidden>
<p class="window-banner" data-pnl-scope="inception">Showing: <strong>Inception with-fee P&amp;L</strong></p>
<div class="kpi"><div class="kpi-label">Inception with-fee P&amp;L (all-time, NOT today)</div>
<div class="kpi-value">+$16.67</div></div>
</div>
<h2>Trades today</h2>
<table>
<tr>
<th>When ET</th><th>System</th><th>Type</th><th>Match</th><th>League</th>
<th>Venue</th><th>Side</th><th>Wire</th><th>Size @ price</th><th>Fee</th>
<th>After-fee</th><th>HTTP</th><th>Filled</th><th>Outcome</th>
<th>Failure kind</th><th>P&amp;L if settled</th>
</tr>
<tr>
<td>2026-11-03 01:32:15 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Gibson vs Oliynykova</td><td>WTA</td><td>polymarket</td>
<td>No Oleksandra Oliynykova</td><td class="num">0.1600</td><td>unknown</td>
<td>0.0000</td><td>0.1600</td><td>HTTP</td><td>yes</td><td>settled loss</td>
<td>—</td><td>−$0.16</td></tr>
<tr>
<td>2026-11-03 01:32:15 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Gibson vs Oliynykova</td><td>WTA</td><td>kalshi</td>
<td>No Oleksandra Oliynykova</td><td class="num">0.8200</td><td>8.0000</td>
<td>0.0104</td><td>0.8304</td><td>HTTP</td><td>yes</td><td>settled win</td>
<td>—</td><td>+$0.17</td></tr>
</table>
<p>Corrected Gibson/Oliynykova lock (+$0.01), not a 1.67 mistake.</p>
<h2>Full book (every posted send)</h2>
<table><tr><th>Size @ price</th></tr></table>
</body></html>
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
    # Note alone no longer clears a living 0.84 wire.
    assert gate.stamp_has_stale_gibson_poly_wire(
        STALE_GIBSON_SNIPPET + "<p>Corrected Gibson/Oliynykova lock</p>"
    ) is True
    assert gate.stamp_has_stale_gibson_poly_wire(FRESH_GIBSON_SNIPPET) is False


def test_drive_failure_mode_fails_gate():
    """The exact Drive stamp Paul saw must FAIL — prior gate wrongly passed Size @ price."""
    path = Path("/tmp/dashboard_stamp_gate_drive_fail.html")
    path.write_text(DRIVE_FAIL_HTML, encoding="utf-8")
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["ok"] is False
    assert report["stamp_size_at_price"] is True  # string present — old gate stopped here
    assert report["trades_today_size_at_price"] is True
    assert report["lock_gap_size_cells_ok"] is False
    assert report["stamp_stale_gibson_wire"] is True
    blob = " ".join(report["failures"])
    assert "Size @ price" in blob
    assert "Gibson" in blob or "0.84" in blob or "2.40" in blob or "2.4" in blob


def test_drive_fixed_stamp_passes_gate():
    from decimal import Decimal

    path = Path("/tmp/dashboard_stamp_gate_drive_fixed.html")
    path.write_text(DRIVE_FIXED_HTML, encoding="utf-8")
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["ok"] is True, report["failures"]
    assert report["lock_gap_size_cells_ok"] is True
    assert report["stamp_stale_gibson_wire"] is False
    assert report["gibson_pair_pnl"] is not None
    assert abs(report["gibson_pair_pnl"] - Decimal("0.01")) <= Decimal("0.02")


def test_drive_2_04_after_gibson_still_fails_gate():
    """Gibson repaired to +$0.01 but Imamura/Teichmann both-wins → today +$2.04."""
    from decimal import Decimal

    html = DRIVE_FAIL_HTML.replace("+$2.40", "+$2.04").replace("0.8400", "0.1600").replace("—", "unknown")
    # Drop stale Gibson 0.84 needle; keep three-lock both-wins leg dollars.
    html = html.replace("Yes Oleksandra Oliynykova", "Yes Oleksandra Oliynykova")
    path = Path("/tmp/dashboard_stamp_gate_drive_2_04.html")
    path.write_text(html, encoding="utf-8")
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["ok"] is False, report
    blob = " ".join(report["failures"])
    assert "2.04" in blob or "both-wins" in blob or "leg P&L" in blob
    assert report["today_a_pnl"] == Decimal("2.04") or report["three_lock_leg_pnl"] is not None


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
    path.write_text(DRIVE_FIXED_HTML, encoding="utf-8")
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["ok"] is True, report["failures"]
    assert report["stamp_size_at_price"] is True
    assert report["stamp_stale_gibson_wire"] is False


def test_three_lock_names_in_full_book_only_do_not_force_today_a():
    """Day rollover: names linger in Full book; Today A is other fills (−1.28).

    Paul 2026-11-04 gate dump: gibson_pair_pnl=None, today_a=-1.28, Size/wire OK.
    Must NOT fail the ~+$0.07 three-lock day expectation.
    """
    from decimal import Decimal

    html = """
<html><body>
<th>Size @ price</th>
<h2>Today</h2>
<div data-window="today">
<div class="kpi"><div class="kpi-label">With-fee P&amp;L</div><div class="kpi-value">-$1.28</div></div>
<table>
<tr><th>System</th><th>N sent</th><th>With-fee P&amp;L</th></tr>
<tr><td>A Lock gap</td><td>2</td><td>-$1.28</td></tr>
</table>
</div>
<h2>Trades today</h2>
<table>
<tr>
<th>When ET</th><th>System</th><th>Type</th><th>Match</th><th>League</th>
<th>Venue</th><th>Side</th><th>Wire</th><th>Size @ price</th><th>Fee</th>
<th>After-fee</th><th>HTTP</th><th>Filled</th><th>Outcome</th>
<th>Failure kind</th><th>P&amp;L if settled</th>
</tr>
<tr>
<td>2026-11-04 12:00:00 ET</td><td>A Lock gap</td><td>initial lock</td>
<td>Some Other Match</td><td>ATP</td><td>kalshi</td>
<td>Yes Other</td><td>0.5000</td><td>unknown</td>
<td>0.0100</td><td>0.5100</td><td>HTTP</td><td>yes</td><td>settled loss</td>
<td>—</td><td>-$0.51</td></tr>
</table>
<h2>Full book (every posted send)</h2>
<table>
<tr><th>Match</th><th>Size @ price</th></tr>
<tr><td>Gibson vs Oliynykova</td><td>unknown</td></tr>
<tr><td>Imamura vs Leong</td><td>unknown</td></tr>
<tr><td>Teichmann vs Garland</td><td>unknown</td></tr>
</table>
<p>Corrected Gibson/Oliynykova lock (+$0.01), not a 1.67 mistake.</p>
</body></html>
"""
    path = Path("/tmp/dashboard_stamp_gate_day_rollover.html")
    path.write_text(html, encoding="utf-8")
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["today_a_pnl"] == Decimal("-1.28")
    assert report["gibson_pair_pnl"] is None
    assert report["three_lock_in_trades_today"] is False
    assert report["ok"] is True, report["failures"]
    assert gate.three_lock_games_present(html) is True


def test_three_lock_in_trades_today_with_negative_a_still_fails():
    """If the three locks are still in Trades today, Today A −1.28 must fail."""
    from decimal import Decimal

    # DRIVE_FAIL has all three locks in Trades today; repair Size/wire so only
    # the Today A −1.28 three-lock expectation fires.
    html = (
        DRIVE_FAIL_HTML.replace("+$2.40", "-$1.28")
        .replace("0.8400", "0.1600")
        .replace("—", "unknown")
    )
    path = Path("/tmp/dashboard_stamp_gate_losing_legs.html")
    path.write_text(html, encoding="utf-8")
    report = gate.check(dashboard_html=path, require_stamp=True)
    assert report["today_a_pnl"] == Decimal("-1.28")
    assert report["three_lock_in_trades_today"] is True
    assert report["ok"] is False, report
    blob = " ".join(report["failures"])
    assert "Trades today" in blob and "-1.28" in blob


if __name__ == "__main__":
    test_writer_trade_headers_include_size_at_price()
    test_stamp_missing_size_at_price_fails()
    test_stamp_with_size_at_price_passes_marker()
    test_stale_gibson_poly_wire_detected()
    test_drive_failure_mode_fails_gate()
    test_drive_fixed_stamp_passes_gate()
    test_drive_2_04_after_gibson_still_fails_gate()
    test_check_writer_only_ok_when_no_stamp()
    test_check_require_stamp_fails_when_missing()
    test_check_stale_stamp_fails()
    test_check_fresh_stamp_passes()
    test_three_lock_names_in_full_book_only_do_not_force_today_a()
    test_three_lock_in_trades_today_with_negative_a_still_fails()
    print("test_dashboard_stamp_gate ok")
