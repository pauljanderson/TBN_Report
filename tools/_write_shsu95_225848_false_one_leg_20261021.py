"""One-shot report: 22:58:48 SHSU 9.5 said one-leg + Gemini flatten miss; tape did not."""
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
PAGE = STAMP / "shsu95_225848_false_one_leg_20261021.html"


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
        ("2026-10-21T22:57:40-04:00", "0.4000", "0.50", "sent", "Neither leg filled."),
        (
            "2026-10-21T22:58:48-04:00",
            "0.4000",
            "0.50",
            "sent",
            "Sent. One leg filled and flatten missed. gemini flatten HTTP 201 flatten miss.",
        ),
        (
            "2026-10-21T22:58:48-04:00",
            "0.40",
            "0.53",
            "denied",
            "This pair is not two live order venues, so it was not sent.",
        ),
        ("2026-10-21T22:59:47-04:00", "0.4000", "0.50", "sent", "Neither leg filled."),
    ]
    consider_html = "".join(
        "<tr>"
        + td(at)
        + td("Yes kalshi " + yes_px)
        + td("No gemini " + no_px)
        + td("0.95")
        + td(decision)
        + td(reason)
        + "</tr>"
        for at, yes_px, no_px, decision, reason in consider_rows
    )
    tape_rows = [
        ("opportunities.html 22:58:48", "sent; One leg filled and flatten missed; gemini flatten HTTP 201 flatten miss; Yes 0.4000 / No 0.50; sizes 2/2; net 0.95"),
        ("orders.jsonl SHSU 9.5 kalshi/gemini", "5 claim + 5 skip only; no sent, filled, one_leg, flatten_filled, flatten_miss, or both_unfilled"),
        ("orders.jsonl 22:57–22:59 this key", "no claim/sent/flatten at that minute; nearby NMSU/SHSU rows are send-gate skips on other lines"),
        ("order_io.jsonl kind=order 22:00–23:05", "7 Polymarket tennis leftovers; 0 Kalshi; 0 Gemini"),
        ("order_io.jsonl Kalshi/Gemini HTTP at 22:58:48", "none. No 201, no fill_count, no remaining, no cancelled body for this pair"),
        ("live_supervisor.log 22:58:40–22:58:52", "send-gate skips (over cap on other NMSU/SHSU lines). No order simultaneous send. No order sent. No flatten. No ONE LEG"),
        ("live_supervisor.log Sam Houston simultaneous send", "never logged for this game"),
        ("Kalshi ticker KXNCAAFSPREAD-26OCT21NMSUSHSU-SHSU10", "no order post in order_io at 22:58; Paul says no Kalshi order and no position"),
        ("Gemini SHSU 9.5 No", "no order post in order_io at 22:58; Paul says no Gemini order and no position. No Gemini positions-list helper; not invented"),
        ("one_leg_watch.json", "absent (no leftover watch)"),
        ("orders_stopped.json", "absent (latch off; not created; not removed)"),
    ]
    tape_html = "".join("<tr>" + td(item) + td(saw) + "</tr>" for item, saw in tape_rows)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SHSU 9.5 22:58 false one-leg — 21 Oct 2026</title>
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
<h1>22:58:48 said one-leg filled and Gemini flatten missed. Neither venue filled.</h1>
<p class="note">America/New_York. Written {html_mod.escape(stamp)}. Research live. Not gold. Not DailyRun. This page does not place, cancel, flatten, or transfer. Click column headers to sort. This stamp owns the 22:58:48 row only; the 22:42:05 cluster is a separate page.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul clarifies: Kalshi does NOT have an order, nor does Gemini. The row he meant is NOT the 22:42:05 cluster. It is 2026-10-21T22:58:48-04:00 college football New Mexico State vs Sam Houston spread Sam Houston 9.5 Yes kalshi / No gemini 0.4000 / 0.50 sizes 2/2 net 0.95 sent. Reason: Sent. One leg filled and flatten missed. gemini flatten HTTP 201 flatten miss. He has no Kalshi position and no Gemini position for this. So ‘one leg filled’ is also false. Do not shut down jobs. Do not start a second live_strategy_b.py. Do not commit. Do not print secrets. Do not sell. Do not transfer money. Do not invent API.</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>The opportunities page is a diary of quotes the bot looked at. “Sent. One leg filled and flatten missed” is supposed to mean we actually bought one side (here, the bot named Gemini), the other side missed, and then it tried to sell/unwind the filled side on Gemini and that unwind also missed. For this Sam Houston 9.5 spread at 22:58:48 ET, the diary said that. The order tape shows no Kalshi post and no Gemini post at that time. Paul has no order and no position on either venue. HTTP 201 with fill count 0 is an empty cancel, not a fill. The bot should have logged both unfilled / skip, not one-leg plus flatten.</p>
</div>

<div class="callout warn">
<h2>Verdict</h2>
<ul>
<li><strong>22:58 HTTP:</strong> house tape has no Kalshi order post and no Gemini order post at 22:58:48. There is no fill_count, remaining, or cancelled body to quote for this pair at that second. Nearby supervisor lines are send-gate skips on other NMSU/SHSU markets, not a simultaneous send.</li>
<li><strong>Why the page said one-leg + flatten miss:</strong> that sentence is only composed when the sender thinks exactly one venue filled at least one contract, then runs flatten on the filled venue. “gemini flatten HTTP 201 flatten miss” means the code thought Gemini filled, then posted (or thought it posted) the opposite Gemini side, got HTTP 201, and counted zero contracts on the unwind. With both original legs at fill 0, that flatten should never have run.</li>
<li><strong>Which venue it thought filled:</strong> Gemini. Flatten always runs on the filled venue. Kalshi was treated as the miss. Paul is flat on both, so the Gemini “fill” was false.</li>
<li><strong>Latch:</strong> off. <code>orders_stopped.json</code> is absent. <code>one_leg_watch.json</code> is absent. No false leftover watch to clear. Orders were not turned back on because they were not latched off.</li>
<li><strong>Patched + restarted.</strong> {html_mod.escape(restart_note)} One Strategy B. Nothing sold. No money moved.</li>
</ul>
</div>

<h2>What opportunities.html logged around 22:58</h2>
<p class="note">From local <code>considerations.json</code>. Same bet: Sam Houston 9.5, Yes kalshi / No gemini. Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{th("date", "At")}{th("text", "Yes")}{th("text", "No")}{th("num", "Net")}{th("text", "Decision")}{th("text", "Reason")}
</tr></thead><tbody>
{consider_html}
</tbody></table></div>

<h2>What the tape actually shows</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{th("text", "Source")}{th("text", "What we saw")}
</tr></thead><tbody>
{tape_html}
</tbody></table></div>

<h2>What we changed</h2>
<ul>
<li><code>filled_contracts</code>: quantity fields only. Kalshi IOC HTTP 201 with fill_count 0 is 0. Gemini cancelled / filledQuantity 0 / “no part of the order would be filled” is 0. A status of filled/executed/complete with no qty is 0, not 1.</li>
<li><code>leg_filled_at_least_one</code> / <code>_send_pair</code>: one-leg and both-filled only when filled_contracts &gt;= 1. HTTP 201 + flatten miss with fill 0 is both_unfilled / “Neither leg filled,” not sent-one-leg. Flatten is not called.</li>
<li>No latch file was present, so none was removed.</li>
</ul>
<p class="note">Tests: <code>test_status_filled_without_qty_is_not_a_fill</code>, <code>test_send_pair_does_not_log_both_filled_on_empty_201</code>, <code>test_send_pair_status_filled_without_qty_is_both_unfilled</code>, <code>test_kalshi_201_fill_count_zero_is_not_a_fill</code>. No secrets. No tickets sold.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
