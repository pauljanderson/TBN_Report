"""One-shot report: lock-bot slot counter was counting dead claims. No orders."""
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
PAGE = STAMP / "lock_open_slots_nmsu_20261021.html"


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
    rows = [
        (
            "SHSU 2.5 Gemini/Kalshi",
            "claim 49, skip 48",
            "none",
            "none",
            "neither",
            "claim (pid 12616, dead)",
            "yes (ghost)",
            "no",
        ),
        (
            "SHSU 2.5 Kalshi/Novig",
            "claim 1",
            "none",
            "none",
            "neither",
            "claim (pid 40680, dead)",
            "yes (ghost)",
            "no",
        ),
        (
            "Over 33.5 Kalshi/Novig",
            "claim 9, skip 8",
            "none",
            "none",
            "neither",
            "claim (pid 32316, dead)",
            "yes (ghost)",
            "no",
        ),
        (
            "NMSU 5.5 Kalshi/Novig",
            "claim 5, skip 4",
            "none",
            "none",
            "neither",
            "claim (pid 29208 is tennis Medvedev poller, not this game)",
            "yes (ghost)",
            "no",
        ),
    ]
    body_rows = []
    for row in rows:
        body_rows.append("<tr>" + "".join(td(cell) for cell in row) + "</tr>")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lock-bot open slots — NMSU vs Sam Houston — 21 Oct 2026</title>
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
<h1>Lock-bot open-slot counter was counting dead claims</h1>
<p class="note">America/New_York. Written {html_mod.escape(stamp)}. Research live. Not gold. Not DailyRun. This page does not place, cancel, or flatten orders. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul says he has no open positions on Novig or Gemini. That contradicts the lock-bot <code>MAX_OPEN_LOCKS=3</code> cap reporting 4 open New Mexico State vs Sam Houston pairs (SHSU 2.5 Gemini/Kalshi, SHSU 2.5 Kalshi/Novig, Over 33.5 Kalshi/Novig, NMSU 5.5 Kalshi/Novig). Investigate and fix the open-slot counter if it is wrong. Do not shut down jobs except the requested restart to load the patch. Do not start a second Strategy B. Do not sell or flatten. Do not transfer money.</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>The bot is allowed three live lock trades at a time. It was telling itself it already had four, so every new lock was denied. Those four “opens” were leftover claim tickets on the tape — the bot said “I am about to send” and then never sent, never filled, and never wrote skip. Gemini and Novig were never filled on any of them. Kalshi was never filled on any of them either. Paul is flat on those two venues for this game; the cap was full of ghosts. We patched the counter so a slot is a real holding (both legs filled, or a leftover watch that actually has a filled contract), restarted the pollers so they load it, and left the latch file alone.</p>
</div>

<div class="callout warn">
<h2>Verdict</h2>
<ul>
<li><strong>None of the four filled on Gemini or Novig.</strong> None filled on Kalshi either. No <code>sent</code>, <code>filled</code>, <code>one_leg</code>, <code>both_unfilled</code>, or flatten rows. No leftover-watch file.</li>
<li><strong>order_io.jsonl:</strong> no order HTTP for these four keys. Tonight’s NMSU/SHSU lines there are Kalshi <em>book</em> lookups, not posts. Gemini and Novig were never posted.</li>
<li><strong>Kalshi positions</strong> (existing GET <code>/trade-api/v2/portfolio/positions</code>, HTTP 200, pulled this job): 0 New Mexico State / Sam Houston rows. Gemini and Novig have no positions-list helper in the modules we already use; we did not invent one. Paul said he is flat there — the tape agrees.</li>
<li><strong>The counter was wrong.</strong> A claim with no skip occupied a slot whenever the game poller was still running, even if the claiming process was dead. One claim pid (29208) was still “alive” only because a tennis poller (Medvedev vs Shimabukuro) now has that pid — not because this football pair was in flight.</li>
<li><strong>Patched.</strong> After the fix the live tape reads <strong>0 / 3</strong> open slots, so new pairs can send again (still under the usual send gate, latch, and cap). Pollers restarted to load <code>live_lock_orders.py</code>. Latch file stays. One Strategy B.</li>
</ul>
</div>

<h2>The four reported opens</h2>
<p class="note">Click column headers to sort. Last event on every row is a claim with no fill. Game poller was still live, which is why ghosts occupied slots.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{th("text", "Pair")}{th("text", "Tape events")}{th("text", "Sent")}{th("text", "Filled venues")}{th("text", "Gemini/Novig fill")}{th("text", "Last event")}{th("text", "Counted as open before")}{th("text", "Counted as open after")}
</tr></thead><tbody>
{''.join(body_rows)}
</tbody></table></div>

<h2>What a slot is now</h2>
<ul>
<li>Both legs filled on a game the pollers are still watching, and not flattened.</li>
<li>Or a leftover one-leg still on tape (flatten missed) while the game is live or a leftover watch is open.</li>
<li>Or an active leftover watch that names a filled contract.</li>
<li>An in-flight claim occupies a slot only while that <em>same game’s</em> current poller pid is still the claim pid.</li>
<li>Dead claims, both-unfilled, flatten-filled, a partner venue that never filled, and a pid reused by another game do not occupy a slot.</li>
</ul>
<p class="note">Tests: <code>tools/test_live_lock_orders.py</code> <code>test_open_lock_keys_counts_live_true_locks_not_flatten_or_history</code> and <code>test_open_lock_keys_ignores_dead_claims_and_unfilled_sends</code>. No secrets logged. No tickets sold.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
