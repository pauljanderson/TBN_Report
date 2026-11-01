"""One-off page: why ~209 terminal tabs vs ~93 live pollers. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import prediction_job_control
from prediction_paths import DRIVE_STAMP as STAMP, ORDERS_STOP, RAW_DIR as RAW
from report_page_extras import (
    CACHE_META,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

PAGE = STAMP / "poller_windows_20261021.html"
ET = prediction_job_control.ET


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(_th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    return (
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def main() -> int:
    snap = prediction_job_control.snapshot()
    prediction_job_control.write_page(snap)
    compare = snap.get("poller_compare") or []
    mismatch = sum(1 for row in compare if row.get("status") != "match")
    consoles = snap.get("consoles") or {}
    latch_path = ORDERS_STOP
    latch_mtime = ""
    if latch_path.exists():
        latch_mtime = datetime.fromtimestamp(latch_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    checked = snap.get("checked") or datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    sup = snap.get("supervisor") or {}
    counts = [
        ["First count (this job, ~11:45 ET)", "227", "234", "96", "93", "1 supervisor pid 104512"],
        ["Second count (~11:48 ET, leftover 11:30 tabs already gone)", "113", "120", "83", "80", "supervisor still 104512"],
        ["Now (after safe cleanup pass)", str(consoles.get("OpenConsole", "")), str(consoles.get("conhost", "")), str(consoles.get("python", "")), str(len(snap.get("children") or [])), f"intended {len(snap.get('intended') or [])}, mismatches {mismatch}"],
    ]
    pid_rows = []
    for item in compare:
        pid_rows.append(
            [
                item.get("key") or "",
                item.get("sport") or "",
                item.get("game") or "",
                "" if item.get("intended_pid") is None else str(item.get("intended_pid")),
                "" if item.get("actual_pid") is None else str(item.get("actual_pid")),
                item.get("started") or "",
                item.get("status") or "",
            ]
        )
    counts_html = _table(
        [("When", "text"), ("OpenConsole (WT tabs)", "num"), ("conhost", "num"), ("python.exe", "num"), ("python --poll-one", "num"), ("Note", "text")],
        counts,
    )
    pid_html = _table(
        [("Key", "text"), ("Sport", "text"), ("Game", "text"), ("Intended PID", "num"), ("Actual python PID", "num"), ("Started", "date"), ("Status", "text")],
        pid_rows,
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
__CACHE_META__
<title>Poller windows 2026-10-21</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 0.4rem; font-size: 1.05rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
__SORTABLE_TH_CSS__
</style>
</head>
<body>
<h1>Why ~209 terminal tabs vs ~93 live pollers</h1>
<div class="callout">
<h2>What you asked</h2>
<p>Paul asked: “Why are there 209 Windows terminals open now? In the past maybe 40-50 (one per live game). job_status says 93 live pollers.”</p>
<h2>In plain English</h2>
<p>Each live game has its own small Python helper. Windows treats that helper like a Command Prompt app, so Windows Terminal opens a tab for it. Restarting the prediction jobs today stopped the old helpers but left the empty tabs. That is why the tab count was about double (and then some) the live-game count. We did not kill the current helpers, the supervisor, the catalog scan, or the leftover 20-second watch. The order-stop latch was left as it was. New helpers will start hidden, so they will not add more tabs.</p>
</div>
<h2>Verdict</h2>
<p><strong>209 vs 93 was leftover empty tabs from today’s restarts, plus one visible Windows Terminal tab and one hidden console host per live helper — not 209 extra Python pollers, and not two Python copies per game.</strong> At first count there were 93 <code>python --poll-one</code> processes (all children of supervisor 104512, 93 unique game keys, no duplicates) and 227 OpenConsole hosts. About 104 of those tabs were started at 11:30 ET when an earlier supervisor (pid 95700) spawned the all-sports helpers, then that Python was killed at the 11:36 restart and the empty tabs stayed. Two host processes per helper (visible tab + hidden conhost) is 93×2 ≈ 186, plus those leftovers, which lands on ~209–227. There was no extra <code>cmd.exe</code> wrapper per poller.</p>
<p>Safe cleanup killed <strong>0</strong> processes. The 11:30 leftover tabs were already gone by the second count (empty-tab close, not a poller kill). Remaining live helpers already matched one tab each, so closing more tabs would have risked killing current pollers. Latch file {html.escape(str(latch_path))} mtime {html.escape(latch_mtime)} was not written. Supervisor, catalog scan, leftover 20s watch thread, and current intended pollers were left running.</p>
<p>The spawn path now uses <code>CREATE_NO_WINDOW</code> so new helpers start hidden. The supervisor already running still has the old spawn code in memory, so a helper it starts before the next reload will still open a tab. I did not restart (that would kill the current live helpers). Double-click <code>run_prediction_restart.bat</code> when you want every helper to come back without a tab. The supervisor itself stays detached, as before. This page does not place an order. See also <a href="job_status.html">job_status.html</a>.</p>
<p class="note">Checked {html.escape(str(checked))}. Raw status file {html.escape(str(RAW / "live_pollers_status.json"))}. Click column headers to sort.</p>
<h2>Counts</h2>
__COUNTS_HTML__
<h2>Intended vs actual python poller PIDs</h2>
<p class="note">{len(compare)} game key(s). {mismatch} mismatch(es). Intended is the supervisor live set. Actual is a live <code>python -u ... --poll-one</code> PID.</p>
__PID_HTML__
<p class="note">Supervisor pid {html.escape(str((sup or {}).get("pid") or "—"))} started {html.escape(str((sup or {}).get("started") or "—"))}. Catalog scan pid {html.escape(str((snap.get("scan") or {}).get("pid") or "—"))}.</p>
__SORTABLE_TABLE_SCRIPT__
</body>
</html>
"""
    page = (
        page.replace("__CACHE_META__", CACHE_META)
        .replace("__SORTABLE_TH_CSS__", SORTABLE_TH_CSS)
        .replace("__COUNTS_HTML__", counts_html)
        .replace("__PID_HTML__", pid_html)
        .replace("__SORTABLE_TABLE_SCRIPT__", SORTABLE_TABLE_SCRIPT)
    )
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(f"wrote {PAGE}")
    print(f"actual_pollers={len(snap.get('children') or [])} intended={len(snap.get('intended') or [])} mismatches={mismatch}")
    print(f"consoles={consoles}")
    print(f"latch_mtime={latch_mtime}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
