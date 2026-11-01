"""Write the 1pm ET NFL T0-miss autopsy for D. Does not trade."""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "d_missed_nfl_t0_1300_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/d_missed_nfl_t0_1300_20261025.html"
)

ONEPM = [
    ("Cincinnati vs Baltimore", "CIN", "BAL", "55760", "13:17:38"),
    ("Cleveland vs Tennessee", "CLE", "TEN", "51396", "13:13:05"),
    ("Indianapolis vs Minnesota", "IND", "MIN", "54800", "13:19:01"),
    ("Miami vs New York J", "MIA", "NYJ", "54992", "13:16:59"),
    ("New York G vs Houston", "NYG", "HOU", "63480", "13:17:40"),
    ("San Francisco vs Atlanta", "SF", "ATL", "39200", "13:17:19"),
    ("Tampa Bay vs Carolina", "TB", "CAR", "56352", "13:17:15"),
]
LATER = [
    ("Denver vs Arizona", "DEN", "ARI", "43492", "16:05", "13:16:45"),
    ("Green Bay vs Detroit", "GB", "DET", "24328", "16:25", "13:16:53"),
    ("Los Angeles R vs Las Vegas", "LAR", "LV", "47056", "16:25", "13:17:26"),
    ("Kansas City vs Seattle", "KC", "SEA", "52660", "20:20", "13:09:42"),
]


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def td(text: str, numeric: bool = False) -> str:
    return f"<td>{html.escape(text)}</td>"


def pid_alive(pid_text: str) -> bool:
    try:
        return live_game_pollers.pid_alive(int(pid_text))
    except Exception:
        return False


def main() -> int:
    now = datetime.now(ET)
    watch = json.loads((RAW / "spread_t0_watch.json").read_text(encoding="utf-8"))
    systems = json.loads((RAW / "systems.json").read_text(encoding="utf-8"))
    pid_blob = json.loads((RAW / "spread_t0.pid").read_text(encoding="utf-8"))
    d_pid = str(pid_blob.get("pid") or watch.get("pid") or "")
    d_alive = pid_alive(d_pid)
    max_now = (systems.get("systems") or {}).get("spread_t0", {}).get("max_open")
    rows = []
    for title, a, b, pid, streams in ONEPM:
        alive = pid_alive(pid)
        skip = (
            "D never considered this game during the 13:00–13:05 ET window. "
            "Pid 59648's last successful tick finished 12:53:50.266 ET "
            "(300 ms before the new queue landed) and then blocked inside "
            "collect_quotes REST. Not logged as T0 window passed / no trusted "
            "clock / fav band / one-sided / size / max_open / B / REST fail "
            "at kickoff. After reload at 13:18:37 ET, D tagged it T0 window passed."
        )
        rows.append(
            "<tr>"
            + td(title)
            + td("13:00:00")
            + td("yes, from 12:53:50 ET")
            + td(f"yes pid {pid} spawned 12:53:51; adopted 13:00:00; quoting no")
            + td("no — D watch frozen 12:53:50")
            + td("listed 13:00:00 seconds=00 (would have been trusted)")
            + td(f"{streams} ET (16–19 min after kickoff)" if streams else "still seeding at autopsy")
            + td("alive" if alive else "dead")
            + td(skip)
            + "</tr>"
        )
    later_rows = []
    for title, a, b, pid, kick, streams in LATER:
        alive = pid_alive(pid)
        later_rows.append(
            "<tr>"
            + td(title)
            + td(kick)
            + td("yes, queue since 12:53:50")
            + td(f"pid {pid} spawned 12:53:51")
            + td("alive and streaming" if alive else "process not listed")
            + td(f"{streams} ET")
            + td("not open yet (15 min pre-window, then T0 + 5 min grace)")
            + td("yes, if D stays ticking")
            + "</tr>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Why D missed 1pm NFL T0 — 2026-10-25</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.verdict {{ background: #fff7ed; border: 1px solid #fdba74; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Why D missed 1pm NFL T0</h1>
<p class="note">Autopsy {html.escape(now.strftime("%Y-%m-%d %H:%M ET"))}. Did not sell. Did not flatten. Did not start a second live_strategy_b.py.</p>
<div class="callout">
<h2>What you asked</h2>
<p>At 1:00 he had T0 spreads (D) max 2. None opened even though a bunch of NFL games started. He thinks we missed T0 on a bunch of games. Why?</p>
<h2>In plain English</h2>
<p>The T0 spread bot buys one spread per game in the first few minutes after kickoff, only if the favorite is between 50 and 90 cents. Today the Sunday football list was injected at 12:53:50 ET and eleven NFL quote helpers started one second later. D itself (pid 59648) then froze while downloading those fat spread books over the shared Gemini/Kalshi/Novig HTTP pace, so it never woke up for the 1:00–1:05 window. Max 2 with 0 open was not the blocker. The favorite-price band was never even checked.</p>
</div>
<div class="verdict">
<p><strong>One-sentence why none opened:</strong> D pid 59648 last saved status at 12:53:50.266 ET, then hung inside REST <code>collect_quotes</code> on the seven 1pm games and never ran during kickoff + 5-minute grace (trusted T0 = 13:00:00–13:05:00 ET).</p>
<p class="note">Not: looping old CFB in RAM (queue reread each tick; C and E kept ticking). Not: missing catalog at 12:59 (all seven were in <code>sports_queue.json</code> from 12:53:50). Not: untrusted clock (listed kickoff seconds=00). Not: max 2 with 0 open. Not: fav ≥ 0.90 / one-sided / size &lt; 1 / B skip — those gates never ran. Pollers were alive at 13:00:00 but not quoting yet; first websockets 13:09–13:19, after the T0 window. D does its own REST anyway, and that REST is what stuck it.</p>
</div>
<h2>Clock</h2>
<ul>
<li>Queue frozen Oct 17 until refresh wrote <code>sports_queue.json</code> at <strong>12:53:50.584 ET</strong>.</li>
<li>D watch last save before the miss: <strong>12:53:50.266 ET</strong>, pid 59648, last skip still last night's TXST vs USU, open 0, last send Oct 24 19:32. Watch max_open printed 4; <code>systems.json</code> was set to max 2 at 12:58:43 ET.</li>
<li>Eleven NFL pollers spawned <strong>12:53:51 ET</strong> (CINBAL, CLETEN, DENARI, GBDET, INDMIN, KCSEA, LARLV, MIANYJ, NYGHOU, SFATL, TBCAR). Supervisor adopted the seven 1pm pids at <strong>13:00:00.59 ET</strong>.</li>
<li>Refresh <code>slate_near_t0</code> at 12:53 ET listed the seven 1pm games. That was the refresh script, not a D tick.</li>
<li><code>spread_t0.log</code> after 12:50 ET: nothing until reload <code>spread_t0 start pid 6244</code> at 13:18:37 ET. Earlier PermissionError lines were 01:45 and 09:12.</li>
<li><code>orders.jsonl</code> after 12:50: no D / <code>spread_t0</code> / KXNFLSPREAD send. First post-12:50 line is a tennis-crossover skip at 12:52:33. Lock skipped CLE-TEN moneyline at 13:10 (over cap) — not D.</li>
<li>C (cfb_favorite) and E (tennis T0 dog) watches kept updating through 13:17. D CPU sample at 13:13 was +0 over 2 seconds — blocked, not looping old CFB.</li>
</ul>
<h2>Sunday 1pm ET NFL games × why missed</h2>
{SWIPE_NOTE_HTML}
<p class="note">Click column headers to sort. Trusted T0 = listed kickoff 13:00:00 ET (seconds=00) through +5 minutes (13:05:00). Grace is 300 seconds.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>
{th("Game", "text")}
{th("Listed kickoff ET", "text")}
{th("In queue at 12:59?", "text")}
{th("Poller at kickoff?", "text")}
{th("D slate_near_t0 tick at T0?", "text")}
{th("Trusted clock", "text")}
{th("Poller first websocket ET", "text")}
{th("Poller now", "text")}
{th("Skip reason", "text")}
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table></div>
<h2>4:05 / 4:25 / SNF — will D see those T0s now?</h2>
<p><strong>Yes, if this D stays ticking.</strong> Reloaded one D at 13:18:37 ET (old pid 59648 dead; live pid <strong>{html.escape(d_pid)}</strong> {"alive" if d_alive else "NOT ALIVE"}). Listed clocks are seconds=00. 4pm pollers were spawned at 12:53:51 and were already on websockets by ~13:17, so the T0 window is not open yet (15-minute pre-window, then kickoff + 5 min grace). Did not change max_open (now {html.escape(str(max_now))} in systems.json). Did not start a second B.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>
{th("Game", "text")}
{th("Listed kickoff ET", "text")}
{th("In queue?", "text")}
{th("Poller spawn", "text")}
{th("Poller now", "text")}
{th("First websocket ET", "text")}
{th("T0 window", "text")}
{th("D will see it?", "text")}
</tr></thead>
<tbody>
{''.join(later_rows)}
</tbody>
</table></div>
<h2>What we did / did not do</h2>
<ul>
<li>Reloaded <strong>one</strong> D because pid 59648 was stuck (watch frozen 12:53:50–13:18, CPU idle). New pid {html.escape(d_pid)} started 13:18:37 ET and is ticking; it now tags the 1pm games T0 window passed without re-hydrating books.</li>
<li>Did not sell. Did not flatten. Did not start a second <code>live_strategy_b.py</code>. Did not revert the sibling one-per-game work on <code>live_spread_t0.py</code>.</li>
<li>Did not change max_open / on / stake.</li>
</ul>
<p class="note">Sources: <code>sports_queue.json</code> fetched_at 12:53:50.584 ET; <code>spread_t0_watch.json</code>; <code>spread_t0.log</code> / <code>spread_t0.pid</code>; <code>live_supervisor.log</code> spawn 12:53:51 and worker streams 13:09–13:19; <code>live_jobs</code> / <code>live_state</code>; <code>orders.jsonl</code>; <code>systems.json</code> 12:58:43 ET max 2; <code>live_t0_yes.slate_near_t0</code> / <code>t0_window</code> (T0_GRACE_SEC=300); <code>nfl_d_queue.html</code> pulled 12:53 ET. Code: live_t0_yes.py, live_spread_t0.py, live_game_pollers.py, overnight_scan.load_sports.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    page = inject_report_page_extras(page)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(str(PAGE))
    print(FILE_URL)
    print(f"d_pid {d_pid} alive {d_alive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
