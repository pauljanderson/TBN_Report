"""Write the Strategy B D=25 freeze note. Research page. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "live_b_d25_20261021.html"


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def main() -> None:
    freeze_rows = [
        ("Arm", "Strategy B, D = 0.25 lock profit on the extra post-cross pair (not a 25¢ dip)"),
        ("Universe", "Tennis moneyline only. Both Yes in (0.10, 0.90). C = sum of the two Yes in [0.95, 1.20]."),
        ("T0", "Live both-Yes only inside 5 minutes of a trusted actual start (Kalshi/Gemini occurrence when clocked, else listed/feed). Reject stale listed that hides in-play (Miyoshi). Skip if already in-play: two-sided Yes moving before the clock, occurrence/listed more than ~5 minutes ago, or either Yes absorbing at 5c/95c. Mid-slate start skips games whose T0 already passed (skip_reason). Never a clockless first-competitive T0 for live sends."),
        ("T0 send", "Buy both Yes, 1 contract each, immediate-or-cancel (IOC). Recheck book before every send. Do not send a second T0 on a match that already filled."),
        ("Cross", "If T0 underdog Yes prints strictly > 0.50 before 5¢/95¢ absorb: buy 1 more of that player at the rechecked live ask. Do not backfill an old print from an abandoned period. IOC miss flattens that extra attempt and waits for the next up-cross (not a 3s leftover retry of the same ask). Never opponent No."),
        ("Favorite dip", "Then buy 1 more original-favorite Yes first time it prints at/below 1 − cross_fill − 0.25 (D=25 lock on that extra pair). Recheck. IOC. 1 contract. Dip IOC miss flattens the extra dog Yes."),
        ("Watch cadence", "Continuous / tick. Quote checks as fast as the live tape (sleep at most 1s). No 20s wait between looks. Not continuous IOC spam."),
        ("Send-once extras", "Do not leftover-retry the same extra ask every 3s (Santos partial bug). A cross/dip IOC miss flattens that extra attempt. A later new up-cross (ask went back to ≤0.50, then >0.50) may fire once. Partial fill is flattened, not treated as a miss that retries."),
        ("No extras", "No cross or absorb first: hold T0 both-Yes (locked ~vig loss). Do not keep buying extras."),
        ("One-leg miss", "Leftover-watch only the missed player's Yes. Do not buy opponent No. Do not call resume_orders_after_lock. Do not delete lock-bot latch."),
        ("max_open_b_matches", "1 (default). Open = reserved waiting T0 through absorb / B complete / abandoned."),
        ("Size", "1 contract. Balance check before send. Novig orders never sent."),
        ("State file", "local/.../raw/strategy_b_watch.json (not Drive, not orders_stopped.json)"),
        ("Lock bot", "Stays up. Independent ORDERS_ENABLED / orders_stopped.json. Skip new lock pairs on an open B match after pollers reload this code."),
        ("Promotion", "Research live, not gold, not DailyRun. HOLD from dense_inplay_fav_lock_cross_smalld_20261021.html (selection bias on B D=25)."),
    ]
    freeze_head = "".join(th(label, kind) for label, kind in (("Knob", "text"), ("Freeze", "text")))
    freeze_body = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in freeze_rows
    )
    asked = (
        "Paul: make sure we don't buy T0 mid-game again (like Bueno/Taverna). "
        "He assumes we are still looking for a crossover to buy and another buy below the 25-cent level: "
        "buy Taverna if he crosses over again, then try to get a bargain Bueno."
    )
    asked2 = (
        "odds move so quickly on the tape we shouldn't wait 20s; perhaps continuously check. Can we do that?"
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live Strategy B D=25 2026-10-21</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Live Strategy B D=25 (tennis)</h1>
<p class="note">Written {esc(datetime.now(ET).isoformat(timespec="seconds"))}. Research live. Not gold. Not DailyRun. Verdict from the dense in-play A/B/C page: <strong>HOLD</strong> (selection bias on B D=25).</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(asked)}</p>
<p>{esc(asked2)}</p>
<h2>In plain English</h2>
<p>No mid-game T0. T0 is the first-ball open: buy Yes on both players only if we are still inside about five minutes of a trusted actual start (Kalshi/Gemini occurrence clock when it is real, otherwise the listed/feed start). If the match is already being played — prices already moving, first ball more than about five minutes ago, or either Yes already near 5 cents or 95 cents — we do not buy that both-Yes open. We also do not invent a “first quote we happened to see” open after B starts in the middle of the slate.</p>
<p>Taverna extras are still on. We already hold Kalshi Yes Taverna 0.35 and Yes Bueno 0.66 (C=1.01). That T0 is sunk; we will not buy it again. If Taverna Yes prints strictly above 50 cents on a new live ask, we buy one more Taverna Yes. Then we try to get a bargain Bueno: one more Bueno Yes at or below 1 − cross fill − 0.25 (a 25-cent lock on that extra pair). Old prints from while this match sat abandoned do not count. If Taverna never crosses, or the book absorbs first, we hold the original both-Yes only (the −1¢ vig lock).</p>
<p>Odds on a live tennis tape jump in a second, so waiting 20 seconds between looks is too slow. We now look at quotes continuously (same cadence as live ticks, or a 1-second sleep at most). We do not leftover-retry the same extra ask every 3 seconds — that stacking was the Santos/Malla bug. If a Taverna cross IOC misses, we wait for him to cross over again. If a Bueno dip IOC misses, we flatten that extra Taverna Yes so we are not left holding a directional extra.</p>
</div>
<div class="warn">
<p><strong>HOLD, not KEEP.</strong> B D=25 was the best mean on <a href="dense_inplay_fav_lock_cross_smalld_20261021.html">dense_inplay_fav_lock_cross_smalld_20261021.html</a> after seeing every arm on the same October 2026 tape. That ranking is in-sample selection even though every T0 is out-of-sample (OOS, entry on or after 2024-01-01). There is no in-sample (IS) row. Live wiring is research, not gold, not DailyRun.</p>
<p>First live send (21 Oct 2026 ~16:35 ET): Kalshi both-Yes on Rodriguez Taverna 0.35 and Bueno 0.66 (C=1.01) filled HTTP 201. Occurrence was 15:10 ET — about 85 minutes late. Pid 62620 treated a live two-sided quote as T0 even though the trusted clock had already passed; the advertised five-minute window was not enforced on that process. Santos vs Malla stays abandoned/stopped (Paul called that stack a bug). Taverna extras re-armed at stage waiting_cross: buy Taverna if he crosses over again, then a bargain Bueno. T0 live now rejects mid-game both-Yes (trusted clock only; skip_reason when T0 already passed).</p>
</div>
<h2>Freeze</h2>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>{freeze_head}</tr></thead>
<tbody>{freeze_body}</tbody>
</table></div>
<h2>How to read job_status</h2>
<p>Open <a href="job_status.html">job_status.html</a>. The Strategy B D=25 block is a live ops panel, not this research page. It shows on/off, max_open, watch cadence (continuous / tick), currently open N, tennis starts in the next 15 and 60 minutes, and each open match: game, venue, stage (waiting T0 / T0 filled waiting 50-cross / waiting fav dip at target X / done / one-leg miss / absorbed), T0 Yes prices and fills, last order id/time/HTTP/fill_qty, and last quotes. job_status does not get a What you asked block for this work — that callout stays on this freeze page.</p>
<p>If many ATP or Women’s Tennis Association (WTA) matches share a listed or occurrence clock, the 15-minute and 60-minute counts rise. With max_open=1, extras queue. We do not unleash every 06:00 open at once.</p>
<h2>T0 live</h2>
<p>T0 is detected from live poller ticks (price_memory shards + price_last.json), not a once-a-day CSV. Live sends use only a trusted occurrence or listed/feed clock inside five minutes. A listed start that hides the match (competitive two-sided Yes already moving, or the first 5¢/95¢ absorb printed before that clock) is rejected. Tape-resume and first-competitive quotes are research labels only — they are not a live T0 clock.</p>
<h2>Process</h2>
<p>B runs as <code>tools/live_strategy_b.py</code>, hidden, with its own state file. It does not require killing the ~93 live pollers to start. The supervisor loop will adopt it on the next reload; until then this job starts B itself. A full <code>run_prediction_restart.bat</code> is only needed if you want every already-running poller to load the lock-bot skip for open B games (CREATE_NO_WINDOW). Do not restart unless you want that skip in the old poller processes.</p>
<p>Acronyms: T0 is the open used here. C is the two T0 Yes prices added together. Vig is the overround when two Yes prices sum over $1. IOC is immediate-or-cancel. ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. OOS is out-of-sample. IS is in-sample. HTTP is Hypertext Transfer Protocol.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)


if __name__ == "__main__":
    main()
