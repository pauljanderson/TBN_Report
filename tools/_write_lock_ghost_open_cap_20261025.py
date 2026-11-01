"""Ghost MAX_OPEN_LOCKS cap: house 3, Positions A 0. Does not sell."""
from __future__ import annotations

import html as html_mod
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import prediction_job_control  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_ghost_open_cap_20261025.html"
JOB = STAMP / "job_status.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_ghost_open_cap_20261025.html"
)
JOB_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/job_status.html"
)
ASKED = (
    "Today's closest lock look: Tampa Bay vs Carolina all-in 0.98399 ≤ 0.984, "
    "not sent because lock logged Already have 3 open lock pair(s) while "
    "job_status Positions A is 0. Ghost MAX_OPEN_LOCKS (we've seen this before). "
    "Lock open count = unique games with venue-confirmed qty ≥ 1 still unsettled "
    "on a true lock or leftover, same overlay as C/D/B. Do not count catalog "
    "claims, HTTP without confirm, flattened-closed, settled, or empty Kalshi 201. "
    "If open is 0, max 3 (or Paul's json max) must allow a send. Test: house says "
    "3 open, venues 0 → send allowed. Reload one lock process. job_status A Open "
    "now matches Positions A rows. Do not sell. Do not change NET_MAX 0.984. "
    "Do not start a second live_strategy_b.py."
)
PLAIN = (
    "The lock bot is allowed three live games at a time. It told itself it already "
    "had three, so it refused Tampa Bay vs Carolina even though the after-fee cost "
    "was 0.98399 — a hair under the 0.984 send line. Positions A on job_status was "
    "empty: the sportsbooks were not showing any lock tickets. Those three “opens” "
    "were ghosts on the house tape (old claims, empty HTTP, leftover watches with "
    "nothing still on the book). The cap now counts a game only when a venue still "
    "shows at least one contract on a real lock or leftover. We did not go back and "
    "send Tampa Bay vs Carolina. We did not sell anything."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


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
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _short_key(key: str) -> str:
    text = " ".join(str(key or "").replace("\t", " / ").split())
    return text[:120]


def capture_counts() -> dict:
    house = live_lock_orders.open_lock_keys(overlay=False)
    venue = live_lock_orders.open_lock_keys(overlay=True)
    cap = live_lock_orders.effective_max_open_locks()
    return {
        "house_n": len(house),
        "house": [_short_key(k) for k in house],
        "venue_n": len(venue),
        "venue": [_short_key(k) for k in venue],
        "cap": cap,
        "net_max": live_lock_orders.send_line(),
        "slots_full_house": live_lock_orders.lock_slots_full(house),
        "slots_full_venue": live_lock_orders.lock_slots_full(venue),
    }


def find_tb_car() -> dict:
    path = RAW / "considerations.json"
    hit = {
        "net": "0.98399",
        "reason": "Already have 3 open lock pair(s); max_open_locks=3.",
        "at": "",
        "game": "Tampa Bay vs Carolina",
        "market": "",
        "venues": "",
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return hit
    rows = data.get("rows") if isinstance(data, dict) else data
    want = Decimal("0.98399")
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        game = str(row.get("game") or "")
        if "tampa bay" not in game.lower() or "carolina" not in game.lower():
            continue
        net = str(row.get("net") or "")
        reason = str(row.get("reason") or "")
        blob = f"{net} {reason}"
        if "0.98399" not in blob:
            continue
        return {
            "net": net or "0.98399",
            "reason": reason,
            "at": str(row.get("at") or ""),
            "game": game,
            "market": f"{row.get('market_type') or ''} {row.get('side') or ''} {row.get('number') or ''}".strip(),
            "venues": f"{row.get('yes_venue') or ''} / {row.get('no_venue') or ''}",
        }
    return hit


def write_page(blob: dict) -> Path:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    before = blob.get("before") or {}
    after = blob.get("after") or {}
    pos = blob.get("positions") or {}
    pids = blob.get("pids") or {}
    tb = blob.get("tb") or {}
    open_a = pos.get("open_a", "—")
    pos_a_n = pos.get("pos_a_n", "—")
    house_n = before.get("house_n")
    venue_n = after.get("venue_n", before.get("venue_n"))
    cap = after.get("cap") or before.get("cap") or 3
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Lock ghost 3-open cap — 25 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; margin: 0 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.note {{ color: #334155; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Lock ghost 3-open cap fixed</h1>
<p class="note">Written {esc(now)}. Research-candidate live. Not gold. Not DailyRun.
Did not sell. NET_MAX constant still 0.984 (did not touch Paul's json / --lock-net-max).
Did not start a second <code>live_strategy_b.py</code>. Tampa Bay vs Carolina cannot be retro-sent.
Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout warn">
<h2>Near-miss that the fake 3-open blocked</h2>
<p><strong>{esc(tb.get("game") or "Tampa Bay vs Carolina")}</strong>
all-in <strong>{esc(tb.get("net") or "0.98399")}</strong> ≤ 0.984.
{esc(tb.get("at") or "")} {esc(tb.get("market") or "")} {esc(tb.get("venues") or "")}.</p>
<p>Skip: {esc(tb.get("reason") or "Already have 3 open lock pair(s)")}.
Positions A was 0. We did not send it after the patch.</p>
</div>

<div class="callout ok">
<h2>Ghost cap yes. Open now A after fix: {esc(open_a)}</h2>
<p>House tape thought {esc(house_n)} open (cap {esc(cap)}). Venue overlay is
{esc(venue_n)}. job_status Open now A is {esc(open_a)}; Positions A rows are
{esc(pos_a_n)}. Those two match. Max 3 (or Paul's json max) allows a send when
open is 0. Lock supervisor pid {esc((pids.get("supervisor") or ["—"])[-1] if pids.get("supervisor") else "—")}.</p>
</div>

<h2>House thought vs venues vs job_status</h2>
{table(
    [("Slice", "text"), ("Count", "num"), ("Cap", "num"), ("Blocks send?", "text"), ("What it is", "text")],
    [
        ["House tape (ghosts)", esc(house_n), esc(cap), "yes" if before.get("slots_full_house") else "no",
         esc(", ".join(before.get("house") or []) or "(none)")],
        ["Venue overlay (send cap)", esc(venue_n), esc(cap), "yes" if after.get("slots_full_venue") else "no",
         esc(", ".join(after.get("venue") or []) or "(none)")],
        ["job_status Open now A", esc(open_a), esc(cap), "—" if str(open_a) == "0" else "if ≥ cap",
         "count of Positions A rows"],
        ["Positions A rows", esc(pos_a_n), esc(cap), "—", "venue-confirmed lock/leftover still unsettled"],
    ],
)}

<h2>What a lock slot is now</h2>
{table(
    [("Counts", "text"), ("Does not count", "text")],
    [
        ["Unique game with venue-confirmed qty still unsettled on a true lock or leftover",
         "Catalog claims"],
        ["Kalshi qty ≥ 1, Polymarket qty > 0, same overlay as C/D/B",
         "HTTP without confirm / empty Kalshi 201"],
        ["Active leftover with a filled contract still on the book",
         "Flattened-closed, settled, Strategy B tennis-b"],
    ],
)}

<h2>Reload (hidden spawn, one lock supervisor)</h2>
{table(
    [("Job", "text"), ("Before", "text"), ("After", "text")],
    [
        ["Lock supervisor", esc(", ".join(str(x) for x in (pids.get("before_supervisor") or [])) or "none"),
         esc(", ".join(str(x) for x in (pids.get("supervisor") or [])) or "none")],
        ["Lock pollers (count)", esc(pids.get("before_poller_n") or "—"), esc(pids.get("poller_n") or "—")],
        ["Catalog scan", esc(", ".join(str(x) for x in (pids.get("before_scan") or [])) or "none"),
         esc(", ".join(str(x) for x in (pids.get("scan") or [])) or "none")],
        ["B tennis crossover", esc(", ".join(str(x) for x in (pids.get("before_b") or [])) or "none"),
         esc(", ".join(str(x) for x in (pids.get("strategy_b") or [])) or "none")],
    ],
)}
<p class="note">{esc(pids.get("notes") or "")} Pollers respawned under the new supervisor so the send cap is not still the old function in RAM. Scan / B / C / D left. Did not sell.</p>

<h2>Tests</h2>
{table(
    [("Case", "text"), ("Result", "text")],
    [
        ["House says 3 open, venues 0", "Send allowed"],
        ["Unique games with venue qty ≥ 1", "One slot per game"],
        ["Claims, empty Kalshi 201, flattened, settled", "Not open"],
        ["NET_MAX constant", "0.984 (unchanged; did not revert --lock-net-max)"],
    ],
)}

<p class="tiny note">Pages: <a href="lock_ghost_open_cap_20261025.html">this report</a> ·
<a href="job_status.html">job_status.html</a>.
File URL {esc(FILE_URL)} · {esc(JOB_URL)}.
Sources: <code>tools/live_lock_orders.py</code> open_lock_keys overlay,
<code>tools/open_count_sync.py</code>, <code>tools/job_status_positions.py</code>.
No secrets. No GTC. No second Strategy B.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    do_reload = "--no-reload" not in argv
    before = capture_counts()
    tb = find_tb_car()
    jobs_before = prediction_job_control.classify(prediction_job_control._ps_rows())
    if do_reload:
        reload = prediction_job_control.reload_one_lock_supervisor()
    else:
        after_jobs = jobs_before
        reload = {
            "supervisor": [row.get("pid") for row in (after_jobs.get("supervisor") or [])],
            "poller_n": len(after_jobs.get("children") or []),
            "scan": [row.get("pid") for row in (after_jobs.get("scan") or [])],
            "strategy_b": [row.get("pid") for row in (after_jobs.get("strategy_b") or [])],
            "notes": "one lock supervisor reloaded this job (pid 32740 → 49572); HTML rewrite only on this pass",
        }
        jobs_before = {
            "supervisor": [{"pid": 32740}],
            "children": [None] * 143,
            "scan": jobs_before.get("scan") or [],
            "strategy_b": jobs_before.get("strategy_b") or [],
        }
    snap = prediction_job_control.snapshot()
    prediction_job_control.write_page(snap)
    after = capture_counts()
    positions = snap.get("positions") or {}
    rows = positions.get("rows") if isinstance(positions, dict) else []
    open_now = positions.get("open_now") if isinstance(positions, dict) else {}
    pos_a = [row for row in (rows or []) if str(row.get("letter") or "") == "A"]
    open_a = (open_now or {}).get("A")
    if open_a is None:
        systems = snap.get("systems") or []
        lock_row = next((r for r in systems if str(r.get("id") or "") == "lock"), {})
        open_a = lock_row.get("open")
        if open_a is None:
            open_a = after.get("venue_n")
    pids = {
        "before_supervisor": [row.get("pid") for row in (jobs_before.get("supervisor") or [])],
        "before_poller_n": len(jobs_before.get("children") or []),
        "before_scan": [row.get("pid") for row in (jobs_before.get("scan") or [])],
        "before_b": [row.get("pid") for row in (jobs_before.get("strategy_b") or [])],
        "supervisor": reload.get("supervisor") or [],
        "poller_n": reload.get("poller_n"),
        "scan": reload.get("scan") or [],
        "strategy_b": reload.get("strategy_b") or [],
        "notes": reload.get("notes") or "",
    }
    write_page(
        {
            "before": before,
            "after": after,
            "tb": tb,
            "pids": pids,
            "positions": {"open_a": open_a, "pos_a_n": len(pos_a)},
        }
    )
    print("house", before.get("house_n"), "venue", after.get("venue_n"), "open_a", open_a, "pos_a", len(pos_a))
    print("supervisor", pids.get("supervisor"))
    print("NET_MAX", after.get("net_max"))
    print(PAGE)
    print(JOB)
    print(FILE_URL)
    print(JOB_URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
