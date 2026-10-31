"""One-shot report: opportunities.html said both legs filled on SHSU 9.5; tape and accounts did not."""
from __future__ import annotations

import html as html_mod
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "shsu95_false_both_filled_20261021.html"


def th(kind: str, label: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def td(text: str) -> str:
    return f"<td>{html_mod.escape(text)}</td>"


def main() -> None:
    stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    restart_note = sys.argv[1] if len(sys.argv) > 1 else "restart not recorded"
    consider_rows = [
        ("2026-10-21T22:42:05-04:00", "0.4000", "0.50", "Neither leg filled."),
        (
            "2026-10-21T22:42:05-04:00",
            "0.4000",
            "0.50",
            "Sent. One leg filled and flatten missed. gemini flatten HTTP 201 flatten miss.",
        ),
        ("2026-10-21T22:42:05-04:00", "0.400", "0.50", "Both legs filled."),
        ("2026-10-21T22:42:05-04:00", "0.400", "0.53", "Both legs filled."),
        ("2026-10-21T22:42:05-04:00", "0.4000", "0.400", "Both legs filled."),
    ]
    consider_html = "".join(
        "<tr>"
        + td(at)
        + td("Yes kalshi " + yes_px)
        + td("No gemini " + no_px)
        + td("0.95")
        + td("sent")
        + td(reason)
        + "</tr>"
        for at, yes_px, no_px, reason in consider_rows
    )
    tape_rows = [
        ("orders.jsonl claim/sent/filled/one_leg/flatten/both_unfilled at 22:42", "none for this bet_key"),
        ("Last SHSU 9.5 kalshi/gemini tape", "claim+skip at 21:17 ET (over cap after book recheck); no send"),
        ("order_io.jsonl kind=order 22:40–22:46", "one Polymarket tennis leftover; zero Kalshi; zero Gemini"),
        ("order_io.jsonl KXNCAAFSPREAD-26OCT21NMSUSHSU-SHSU10", "20 book lookups only, last 22:10:43; never an order post"),
        ("live_supervisor.log at 22:42:05", "no “order simultaneous send”; nearby lines are send-gate skips"),
        ("Kalshi GET /trade-api/v2/portfolio/positions", "HTTP 200; 0 rows for this SHSU 9.5 ticker (position 0)"),
        ("Gemini positions helper", "none in gemini_private; not invented"),
        ("one_leg_watch.json / orders_stopped.json", "absent (no leftover watch; latch file not present, not created)"),
    ]
    tape_html = "".join(
        "<tr>" + td(item) + td(saw) + "</tr>" for item, saw in tape_rows
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SHSU 9.5 false both-filled — 21 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
ul {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>opportunities.html said both legs filled. Kalshi and Gemini did not.</h1>
<p class="note">America/New_York. Written {html_mod.escape(stamp)}. Research live. Not gold. Not DailyRun. This page does not place, cancel, flatten, or transfer. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul says his Kalshi and Gemini accounts disagree with opportunities.html. Four rows at 2026-10-21T22:42:05-04:00, NMSU vs Sam Houston spread Sam Houston 9.5, Yes kalshi / No gemini, net 0.95, all decision=sent: (1) 0.4000 / 0.400 both legs filled (2) 0.400 / 0.53 both legs filled (3) 0.400 / 0.50 both legs filled (4) 0.4000 / 0.50 Sent. One leg filled and flatten missed. gemini flatten HTTP 201 flatten miss. Investigate the tape. Do not shut down jobs except the requested poller restart if live_lock_orders.py changes. Do not start a second live_strategy_b.py. Do not commit. Do not print secrets. Do not sell/flatten. Do not transfer money. Do not invent API.</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>The opportunities page is a diary of quotes the bot looked at. “Sent / both legs filled” is supposed to mean we actually bought one Yes on Kalshi and one No on Gemini. For this Sam Houston 9.5 spread at 22:42 ET, the diary said that three times plus a “one leg filled, flatten missed” line. The order tape and the Kalshi positions read show no contracts. The three different Gemini No prices (0.400, 0.50, 0.53) at the same second are quote patches (websocket / book recheck / consider), not three true locks. We patched the bot so “both filled” only logs when both venues have quantity at least 1, and so one attempt cannot write three sent rows.</p>
</div>

<div class="callout warn">
<h2>Verdict</h2>
<ul>
<li><strong>Nothing filled on this SHSU 9.5 pair.</strong> Kalshi Yes 9.5 (<code>KXNCAAFSPREAD-26OCT21NMSUSHSU-SHSU10</code>) position 0. Gemini has no positions-list helper in the modules we already use; order_io has zero Gemini order posts at 22:42, so there is no fill to confirm there either.</li>
<li><strong>The page lied.</strong> Five <code>sent</code> rows share 22:42:05 (Paul quoted four; the log also has “Neither leg filled.”). Same timestamp, three No prices. That is websocket/recheck/consider patches plus a weak filled flag (HTTP 201 / cancelled / fill 0 treated as a fill), not three locks.</li>
<li><strong>Flatten-miss vs accounts:</strong> there is no flatten HTTP in order_io and no one-leg watch file. The flatten-miss sentence was logged without a filled contract to flatten. Accounts being flat matches the tape.</li>
<li><strong>Patched + restarted.</strong> {html_mod.escape(restart_note)} Latch file was not present and was not created. One Strategy B.</li>
</ul>
</div>

<h2>What opportunities.html logged</h2>
<p class="note">From local <code>considerations.json</code>. Click column headers to sort. Fingerprint includes Yes/No prices, so 0.400 vs 0.50 vs 0.53 each became a new row.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{th("date", "At")}{th("text", "Yes")}{th("text", "No")}{th("num", "Net")}{th("text", "Decision")}{th("text", "Reason")}
</tr></thead><tbody>
{consider_html}
</tbody></table></div>

<h2>What the tape and accounts actually show</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{th("text", "Source")}{th("text", "What we saw")}
</tr></thead><tbody>
{tape_html}
</tbody></table></div>

<h2>What we changed</h2>
<ul>
<li><code>filled_contracts</code>: if the venue sent <code>fill_count</code> / filled qty, that number wins. Kalshi IOC HTTP 201 with fill_count 0 is 0 even if a nested status says executed/complete.</li>
<li><code>leg_filled_at_least_one</code>: quantity &gt;= 1 only. A weak <code>filled=True</code> flag, HTTP 201, or status cancelled with fill 0 is not a fill.</li>
<li><code>_send_pair</code>: “Both legs filled” only when both legs have qty &gt;= 1. <code>posted</code> is false when no HTTP left the machine (status 0).</li>
<li><code>opportunity_considerations.record</code>: one <code>sent</code> row per bet per timestamp second, so quote patches cannot stack three “Both legs filled” lines for one attempt.</li>
</ul>
<p class="note">Tests: <code>test_kalshi_201_fill_count_zero_is_not_a_fill</code>, <code>test_weak_filled_flag_without_qty_is_not_a_fill</code>, <code>test_send_pair_does_not_log_both_filled_on_empty_201</code>, <code>test_record_sent_same_second_does_not_stack_quote_patches</code>. No secrets. No tickets sold.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
