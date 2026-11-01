"""Replay gate for the long-loop 50-cross miss. Research only. Not gold. Not DailyRun."""
from __future__ import annotations

import html
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP, RAW_DIR as RAW, ensure_dirs  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = DRIVE_STAMP / "long_loop_replay_gate_20261028.html"
LAST = RAW / "price_last.json"


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers, rows) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = []
        for (_, kind), val in zip(headers, row):
            extra = ' class="num"' if kind == "num" else ""
            cells.append(f"<td{extra}>{esc(val)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _run(script: str) -> tuple[str, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    status = "PASS" if proc.returncode == 0 and out.endswith("ok") else "FAIL"
    return status, (err or out)[-400:]


def _last_info() -> tuple[str, str]:
    if not LAST.is_file():
        return "missing", "—"
    size = LAST.stat().st_size
    mb = f"{size / (1024 * 1024):.2f} MB"
    try:
        keys = len(json.loads(LAST.read_text(encoding="utf-8")))
        return mb, f"{keys:,}"
    except (OSError, json.JSONDecodeError, TypeError):
        return mb, "unreadable"


def main() -> Path:
    ensure_dirs()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    gate = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import tools.test_live_strategy_b as t; "
                "t.test_shimizu_memory_052_sends_immediately_not_180s(); "
                "t.test_shimizu_memory_049_does_not_send_or_rest(); "
                "t.test_shimizu_cross_does_not_double_send(); "
                "t.test_maybe_cross_is_not_only_once_per_long_tick(); "
                "t.test_t0_hunt_does_not_run_before_50_cross_watches(); "
                "t.test_tick_cross_only_does_not_walk_t0_slate(); "
                "t.test_t0_arm_budget_shrinks_when_waiting_cross(); "
                "print('ok')"
            ),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    gate_status = "PASS" if gate.returncode == 0 and (gate.stdout or "").strip().endswith("ok") else "FAIL"
    lock = _run("test_price_memory_lock.py")
    last_mb, last_keys = _last_info()
    import price_memory
    import live_strategy_b

    pid_row = {}
    pid_path = RAW / "strategy_b.pid"
    if pid_path.is_file():
        try:
            pid_row = json.loads(pid_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pid_row = {}

    tests = table(
        [("Test", "text"), ("Role", "text"), ("Result", "text")],
        [
            ["test_shimizu_memory_052_sends_immediately_not_180s", "Keep: 52¢ REST+send now, no 180s sleep", gate_status],
            ["test_shimizu_memory_049_does_not_send_or_rest", "Keep: 49¢ no REST, no send", gate_status],
            ["test_shimizu_cross_does_not_double_send", "Keep: second maybe_cross does not send again", gate_status],
            ["test_t0_arm_budget_shrinks_when_waiting_cross", "Keep: T0 hunt ≤0.2s while 50-cross armed", gate_status],
            ["test_maybe_cross_is_not_only_once_per_long_tick", "Add: fail if maybe_cross is once per long tick", gate_status],
            ["test_t0_hunt_does_not_run_before_50_cross_watches", "Add: process_open before tennis_slate / try_t0", gate_status],
            ["test_tick_cross_only_does_not_walk_t0_slate", "Add: cross pump never walks T0 slate", gate_status],
            ["test_remember_books_lock_hold_under_500ms_with_huge_legacy_last", "Add: lock hold <500ms, leftover LAST not rewritten", lock[0]],
            ["test_two_games_do_not_share_one_lock", "Add: per-game lock files", lock[0]],
            ["test_fake_slow_http_is_not_under_lock", "Add: no HTTP while lock held", lock[0]],
        ],
    )
    order = table(
        [("Step", "text"), ("Before this job", "text"), ("After", "text")],
        [
            [
                "Long tick() start",
                "pump memory → tennis_slate() → _process_hot_opens → T0 hunt",
                "pump memory → _process_hot_opens (50-cross) → tennis_slate → T0 hunt (0.2s budget if a cross is armed)",
            ],
            [
                "While 50-cross armed",
                "tick_cross_only every 50ms already existed; T0 slate still ran first inside tick()",
                "tick_cross_only still every 50ms and does not call try_t0 / tennis_slate. tick() no longer walks the slate before the cross.",
            ],
            [
                "T0 arm budget",
                "0.2s while waiting on a 50-cross, 1.0s otherwise",
                "Unchanged. Re-checks the cross after each T0 probe.",
            ],
        ],
    )
    lock_rows = table(
        [("Fact", "text"), ("Value", "text")],
        [
            ["Leftover price_last.json size (this PC, not rewritten by new writers)", last_mb],
            ["Keys in leftover snapshot", last_keys],
            ["Old writer", "Global price_memory.lock, then json.dumps(all keys, indent=2) + replace"],
            ["New writer", "Per-game file raw/price_last_games/{sport}/{game}.json under that game's lock"],
            ["Lock hold budget (unit test)", f"< {price_memory.LOCK_HOLD_BUDGET_MS:.0f} ms"],
            ["HTTP under lock", "Forbidden. Quotes are built first. urlopen during remember_books fails the new test."],
            ["jsonl tape", "Still dated sport shards. Short per-sport lock only around the append."],
            ["job_status.html", "Sibling HTTP-wait fields not present yet. Did not add compare_ms there (would race their rewrite)."],
        ],
    )

    asked = (
        "this also sounds reasonable. make it so — architecture rec: Do now — Replay tests "
        "for the long-loop miss. Already have a Shimizu replay: 52¢ sends without a 180s sleep; "
        "49¢ does not REST; no double-send. Keep that as a gate. Add: T0 hunt must not run before "
        "50-cross watches; lifetime compare_ms must not sit in tens of seconds because of "
        "price_memory.lock."
    )
    plain = (
        "Two holes. First: while Tennis crossover is hunting new matches, it must not ignore a "
        "game that is already waiting to buy the extra 50-cent ticket. The 52-cent Shimizu replay "
        "stays as a required test. We added a test that fails if that extra-ticket check only runs "
        "once per long lap. Second: every live-game helper was rewriting one 15-megabyte "
        "latest-price file under one lock, so a compare could sit in tens of seconds waiting its "
        "turn. Helpers now write a small file for that one game and do not hold the lock during a "
        "web read. This is not gold and not DailyRun. C=1.05, D, leftover GTC, and stake were not retuned."
    )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>Long-loop replay gate — 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; padding: 0 0 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
td.num {{ text-align: right; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Long-loop replay gate</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now)}. Research only. Not gold. Not DailyRun. Did not retune C=1.05, D, leftover GTC, or stake. Did not start a second Strategy B from this page.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(asked)}</p>
<h2>In plain English</h2>
<p>{esc(plain)}</p>
</div>

<div class="warn">
<p><strong>Verdict.</strong> Shimizu 52¢ / 49¢ / no-double-send stay as a required gate ({esc(gate_status)}).
T0 hunt no longer runs before a 50-cross watch. <code>tick_cross_only</code> still pumps every 50 ms and never walks the T0 slate.
<code>price_last.json</code> was {esc(last_mb)} / {esc(last_keys)} keys — that global rewrite under <code>price_memory.lock</code> is why lifetime compare_ms could sit in tens of seconds. New writers lock one game file. Unit-test lock hold is under 500 ms ({esc(lock[0])}). Pollers already running still have the old function in memory until they restart; this job did not recycle the 100+ helpers.</p>
</div>

<h2>Tests kept and added</h2>
<p>Click column headers to sort. Gate tests {esc(gate_status)}. Lock tests {esc(lock[0])}. Did not run the whole Strategy B file here — a Poly size stub elsewhere does not accept sibling <code>pace=</code>; that is not this job.</p>
{SWIPE_NOTE_HTML}
{tests}

<h2>T0 hunt vs 50-cross order</h2>
<p><code>CROSS_IDLE_SEC={esc(live_strategy_b.CROSS_IDLE_SEC)}</code>. <code>T0_ARM_BUDGET_WHEN_CROSS_SEC={esc(live_strategy_b.T0_ARM_BUDGET_WHEN_CROSS_SEC)}</code>. <code>TICK_SEC={esc(live_strategy_b.TICK_SEC)}</code>.</p>
{SWIPE_NOTE_HTML}
{order}

<h2>price_memory.lock</h2>
{SWIPE_NOTE_HTML}
{lock_rows}

<h2>Strategy B pid</h2>
<p>Reloaded one B (runtime tick order + tennis last-price merge). Stopped 72808. New pid {esc(pid_row.get("pid") or "—")}, started {esc(pid_row.get("started_at") or "—")}. Did not start a second copy. Pollers were not recycled.</p>

<p class="note">Sources: <code>tools/live_strategy_b.py</code>, <code>tools/test_live_strategy_b.py</code>, <code>tools/price_memory.py</code>, <code>tools/test_price_memory_lock.py</code>. Architecture rec #4 in <code>live_architecture_20261028.html</code>. Leftover watch still uses the same ask; it now reads the per-game last file instead of the 15 MB snapshot. Not a GTC retune.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html_out, encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = main()
    print(path)
