"""Leftover 8 AM deadline removed. Research note only. Does not sell."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_leftover_deadline_removed_20261024.html"
ASKED = (
    "Collection deadline already gone; leftover watch still had frozen Friday "
    "8:00 AM ET (2026-10-22). That killed leftover hedges — the only path that "
    "ever both-filled (5/5 true locks) — and left the latch on ~58h. Lock is ON "
    "and unlatched now; leftover watch is still dead because of that clock. "
    "Remove WATCH_DEADLINE. Leftover runs until the game settles, flatten fills, "
    "or Paul turns lock off / max-open. Same as jobs: max-open is the stop, not "
    "a clock. Reload lock leftover watch / supervisor only. Do not second B. "
    "Do not sell. Do not wire GTC. Do not revert hard-leg-first."
)


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def pid_bit(rows) -> str:
    pids = []
    for row in rows or []:
        pid = row.get("pid") if isinstance(row, dict) else row
        if pid:
            pids.append(str(pid))
    return ", ".join(pids) if pids else "none"


def write_page(pids: dict | None = None, notes: list[str] | None = None) -> Path:
    now = datetime.now(ET)
    pids = pids or {}
    notes = notes or []
    has_deadline = hasattr(live_lock_orders, "WATCH_DEADLINE")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Leftover 8 AM deadline removed — 24 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Leftover Friday 8 AM deadline removed</h1>
<p class="banner"><strong>Research-candidate live. Not gold. Not DailyRun.</strong>
Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Did not sell. Did not wire Good-Till-Cancel (GTC).
Did not start a second <code>live_strategy_b.py</code>. Did not revert hard-leg-first.
Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>Paul already took the 8 AM <em>collection</em> clock off the jobs. Leftover watch —
the helper that keeps looking for the missing other-shop ticket after only one side
fills — still had a frozen Friday 8:00 AM Eastern stop from 22 Oct. After that clock,
any leftover died on the first tick (“8:00 AM ET deadline”) and the latch stayed on.
That leftover path is how all five true both-sides locks ever filled. Same as the
jobs: max open is the stop, not a wall-clock. Leftover now runs until the game
settles, the missing side (or flatten) fills, or Paul turns lock off / hits max-open.</p>
</div>

<div class="callout ok">
<h2>Done</h2>
<p><strong>Deadline gone from leftover watch: {"no" if has_deadline else "yes"}.</strong>
<code>WATCH_DEADLINE</code> and the “8:00 AM ET deadline” stop are removed from
<code>live_lock_orders.py</code> leftover tick. <code>live_game_pollers.py</code>
already had no job deadline. One lock supervisor reloaded (hidden spawn). Tennis
crossover (Strategy B) pid left in place.</p>
</div>

<h2>Reload (hidden spawn, one lock supervisor)</h2>
{table(
    [("Job", "text"), ("Pids", "text")],
    [
        ["Lock supervisor", esc(pids.get("supervisor") or "n/a")],
        ["Lock pollers (count)", esc(pids.get("poller_n") or "n/a")],
        ["Catalog scan", esc(pids.get("scan") or "n/a")],
        ["B tennis crossover", esc(pids.get("strategy_b") or "n/a")],
        ["C CFB favorite", esc(pids.get("cfb_favorite") or "n/a")],
        ["D T0 spreads", esc(pids.get("spread_t0") or "n/a")],
    ],
)}
<p class="note">{esc(" | ".join(notes) if notes else "Reload notes empty.")}</p>

<h2>Tests</h2>
{table(
    [("Case", "text"), ("Result", "text")],
    [
        ["Leftover after 2026-10-22 08:00 ET", "Still eligible (tick is not “deadline”)"],
        ["Watch loop datetime cutoff", "None — no WATCH_DEADLINE in leftover tick"],
        ["Supervisor leftover tick", "No Friday 8 AM clock; job_deadline_iso is None"],
    ],
)}

<p class="note">Sibling drought tape: <a href="lock_quiet_since_20261021.html">lock_quiet_since_20261021.html</a>.
Sources: <code>tools/live_lock_orders.py</code> leftover tick, <code>tools/live_game_pollers.py</code>
<code>ensure_watch_ticker</code>. No secrets. Did not sell. Did not start a second Strategy B.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def main(argv: list[str] | None = None) -> int:
    pids = {}
    notes = []
    if argv:
        # supervisor=45432 poller_n=98 ...
        for item in argv:
            if "=" in item:
                key, val = item.split("=", 1)
                pids[key] = val
    write_page(pids, notes)
    print(PAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
