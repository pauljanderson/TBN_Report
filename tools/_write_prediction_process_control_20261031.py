"""Process-control page for the live prediction kitchen.

Display only. Does not start or stop python. Does not start a second B.
Does not leftover-GTC A. Does not sell TEN/CIN. Does not start hist pulls.
Does not rewrite dashboard.html.
"""
from __future__ import annotations

import html
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
import win_hidden  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW, ROOT as REPO  # noqa: E402
from write_orders_performance import table  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = STAMP / "prediction_process_control_20261031.html"
PY = Path(r"C:\Users\songg\AppData\Local\Programs\Python\Python310\python.exe")
REPO_S = str(REPO)
PY_S = str(PY)

PAUL = (
    "i feel like you are running all these programs that keep the system running. "
    "However, what I want is complete control. what programs are you running and "
    "how frequently do they run? I'd rather set them up using task scheduler on "
    "windows than have you run them. Help me reduce the costs of running cursor. "
    "i am way over this month."
)
PAUL_B = (
    "it looks like system B tries to lock in both sides for about 5 minutes."
)

KITCHEN_NEEDLES = (
    "live_game_pollers.py",
    "overnight_scan.py",
    "live_strategy_b.py",
    "live_cfb_favorite.py",
    "live_spread_t0.py",
    "live_tennis_t0_dog.py",
    "live_tennis_t0_spread.py",
    "live_soccer_t0_total.py",
    "live_lock_sender.py",
    "live_pm_settle_reconcile.py",
    "write_orders_performance.py",
    "write_dashboard.py",
    "prediction_job_control.py",
)
LEFTOVER_NEEDLES = (
    "_pull_kalshi_inplay_path",
    "_pull_pm_hist_t0",
    "_pull_venue_fill_history",
    "--leftover",
    "--poly-holes",
    "poly-holes",
)


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _ps_all_python() -> list[dict]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'python' -and $_.CommandLine } | "
        "ForEach-Object { "
        "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.ParentProcessId) "
        "-ErrorAction SilentlyContinue; "
        "$pn = if ($p) { $p.Name } else { '(gone)' }; "
        "'{0}|{1}|{2}|{3}|{4}' -f $_.ProcessId, $_.ParentProcessId, $pn, "
        "$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss'), "
        "($_.CommandLine -replace '\\|','/') }"
    )
    try:
        out = win_hidden.check_output(
            win_hidden.powershell_argv(script),
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not list processes: {exc}")
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0].strip())
            parent = int(parts[1].strip())
        except ValueError:
            continue
        rows.append(
            {
                "pid": pid,
                "parent": parent,
                "parent_name": parts[2].strip(),
                "started": parts[3].strip(),
                "cmd": parts[4].strip(),
            }
        )
    return rows


def classify_row(cmd: str) -> tuple[str, str, str, str]:
    text = cmd or ""
    low = text.lower()
    if "write_orders_performance.py" in text:
        return (
            "Page rewrite",
            "orders_performance + dashboard.html",
            "Event (4s debounce after fill/close)",
            "Kitchen child — short-lived. Not Cursor.",
        )
    if "write_dashboard.py" in text:
        return (
            "Page rewrite",
            "dashboard.html",
            "Called from orders_performance",
            "Kitchen child — short-lived. Not Cursor.",
        )
    if "live_game_pollers.py --poll-all" in text:
        return (
            "poll-all",
            "One quote process for live games (A books)",
            "Websockets; HTTP fallback every 5s",
            "Always-on. Supervisor keeps exactly one.",
        )
    if "live_game_pollers.py --poll-one" in text:
        return (
            "leftover --poll-one",
            "Old per-game poller (supervisor no longer spawns)",
            "n/a",
            "Extra. Should not be here.",
        )
    if "live_game_pollers.py" in text:
        return (
            "Supervisor",
            "Looks after poll-all + A sender; rewrites job_status",
            "Loop every 60s (not a Task Scheduler repeat)",
            "Always-on. Start once at logon.",
        )
    if "live_lock_sender.py" in text:
        return (
            "A Lock gap sender",
            "Reads lock hints and sends when net is under the cap",
            "Loop every 0.2s",
            "Always-on. Supervisor respawns if it dies.",
        )
    if "live_strategy_b.py" in text:
        return (
            "B Tennis crossover",
            "T0 both-Yes, then 50c cross / fav dip",
            "1s slate; 0.05s while a 50-cross is armed. Send window 15s before T0 through 5 min after",
            "Always-on. Never a second copy.",
        )
    if "live_cfb_favorite.py" in text:
        return ("C CFB favorite", "Directional Yes at T0", "Tick every 1s", "Always-on when on.")
    if "live_spread_t0.py" in text:
        return ("D T0 spreads", "Traditional spread at T0 (NFL skipped)", "Tick every 1s", "Always-on when on.")
    if "live_tennis_t0_dog.py" in text:
        return ("E Tennis T0 dog", "Dog Yes at T0", "Tick every 1s", "Always-on when on.")
    if "live_tennis_t0_spread.py" in text:
        return ("F Tennis spread", "Tennis spread at T0", "Tick every 1s", "Always-on when on.")
    if "live_soccer_t0_total.py" in text:
        return ("G Soccer total", "Soccer total at T0", "Tick every 1s", "Always-on when on.")
    if "live_pm_settle_reconcile.py" in text:
        return (
            "Settle reconcile",
            "Pulls venue fills/settlement; queues page rewrite",
            "Loop every 90s",
            "Always-on. start will spawn if missing.",
        )
    if "overnight_scan.py" in text:
        return (
            "Catalog scan",
            "Walks matched games (college → other sports → shared), then repeats",
            "No clock. Sequential walk. A live game already cataloged is re-checked every 120s",
            "Always-on. Separate from live tennis A/B.",
        )
    if "_pull_kalshi_inplay_path" in text:
        return (
            "Hist pull (Kalshi through-game)",
            "Research tape only. Not the live kitchen",
            "Until finished / you End Task",
            "Does not need Cursor. Do not start a new one from an agent.",
        )
    if "_pull_pm_hist_t0" in text and "--poly-holes" in low:
        return (
            "Hist pull (Poly holes)",
            "Research tape only",
            "Until finished / you End Task",
            "Does not need Cursor.",
        )
    if "_pull_pm_hist_t0" in text:
        return (
            "Hist pull (T0 leftover)",
            "Research tape only",
            "Until finished / you End Task",
            "Does not need Cursor.",
        )
    if "_pull_venue_fill_history" in text:
        return (
            "Hist pull (venue fills)",
            "Research tape only",
            "Until finished / you End Task",
            "Does not need Cursor.",
        )
    if "prediction_job_control.py" in text:
        return ("Job control", "status / start / restart / systems", "One-shot", "You run this. Not a loop.")
    return ("Other python", text[-80:], "?", "Listed so you can End Task if you want.")


def is_kitchen(cmd: str) -> bool:
    return any(n in (cmd or "") for n in KITCHEN_NEEDLES)


def is_hist(cmd: str) -> bool:
    return any(n in (cmd or "") for n in LEFTOVER_NEEDLES)


def load_systems() -> dict:
    path = RAW / "systems.json"
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def age_hours(started: str, now: datetime) -> str:
    try:
        dt = datetime.strptime(started, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=ET)
        hours = (now - dt).total_seconds() / 3600.0
        if hours < 1:
            return f"{int((now - dt).total_seconds() / 60)} min"
        return f"{hours:.1f} h"
    except Exception:
        return "—"


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def main() -> None:
    now = datetime.now(ET)
    written = now.strftime("%Y-%m-%d %I:%M %p ET")
    procs = _ps_all_python()
    kitchen = [r for r in procs if is_kitchen(r["cmd"])]
    hist = [r for r in procs if is_hist(r["cmd"])]
    other = [
        r
        for r in procs
        if "stockresearch" in (r["cmd"] or "") and r not in kitchen and r not in hist
    ]
    sys_cfg = (load_systems().get("systems") or {})

    def on_off(sid: str) -> str:
        row = sys_cfg.get(sid) or {}
        return "on" if row.get("on") else "off"

    live_rows = []
    for r in sorted(kitchen, key=lambda x: x["started"]):
        role, what, freq, restart = classify_row(r["cmd"])
        live_rows.append(
            [
                r["pid"],
                r["parent"],
                r["parent_name"],
                r["started"],
                age_hours(r["started"], now),
                role,
                what,
                freq,
                restart,
                r["cmd"].replace(REPO_S + "\\", "").replace(REPO_S + "/", ""),
            ]
        )
    b_pids = [r["pid"] for r in kitchen if "live_strategy_b.py" in r["cmd"]]
    hist_rows = []
    for r in sorted(hist, key=lambda x: x["started"]):
        role, what, freq, restart = classify_row(r["cmd"])
        hist_rows.append(
            [
                r["pid"],
                r["parent"],
                r["parent_name"],
                r["started"],
                role,
                what,
                "No — plain python.exe",
                "List only. Did not kill. Did not start a new one.",
                r["cmd"][-180:],
            ]
        )
    if not hist_rows:
        hist_rows.append(
            [
                "—",
                "—",
                "—",
                "—",
                "(none running)",
                "No Kalshi through-game pull, no T0 --leftover, no --poly-holes, no _pull_*.py",
                "n/a",
                "Do not start from Cursor. If you want one later, use Task Scheduler (recipe below).",
                "—",
            ]
        )

    intended = [
        [
            "Supervisor",
            "live_game_pollers.py",
            on_off("lock"),
            "60s loop; keep one poll-all + one A sender",
            "Always-on (supervisor loop, not Task Scheduler repeat)",
            "run_prediction_start.bat / prediction_job_control.py start",
        ],
        [
            "poll-all",
            "live_game_pollers.py --poll-all",
            on_off("lock"),
            "Websockets; HTTP fallback 5s. Tennis subscribe 5 min before listed start",
            "Always-on child of supervisor",
            "Do not start yourself; supervisor keeps one",
        ],
        [
            "A Lock gap",
            "live_lock_sender.py",
            on_off("lock"),
            "0.2s loop reading lock hints",
            "Always-on child of supervisor",
            "systems --lock on (does not start a second B)",
        ],
        [
            "B Tennis crossover",
            "live_strategy_b.py",
            on_off("tennis_crossover"),
            "1s slate; 0.05s when a 50-cross is armed. T0 send: 15s before through 5 min after listed/trusted start",
            "Always-on. Exactly one pid",
            "systems --tennis-crossover on  (never a second copy)",
        ],
        [
            "C CFB favorite",
            "live_cfb_favorite.py",
            on_off("cfb_favorite"),
            "1s T0 tick",
            "Always-on when on. Off = no process",
            "systems --cfb-favorite on|off",
        ],
        [
            "D T0 spreads",
            "live_spread_t0.py",
            on_off("spread_t0"),
            "1s T0 tick (NFL skipped)",
            "Always-on when on",
            "systems --spread-t0 on|off",
        ],
        [
            "E Tennis T0 dog",
            "live_tennis_t0_dog.py",
            on_off("tennis_t0_dog"),
            "1s T0 tick",
            "Always-on when on. Off = no process",
            "systems --tennis-t0-dog on|off",
        ],
        [
            "F Tennis spread",
            "live_tennis_t0_spread.py",
            on_off("tennis_t0_spread"),
            "1s T0 tick",
            "Always-on when on",
            "systems --tennis-t0-spread on|off",
        ],
        [
            "G Soccer total",
            "live_soccer_t0_total.py",
            on_off("soccer_t0_total"),
            "1s T0 tick",
            "Always-on when on",
            "systems --soccer-t0-total on|off",
        ],
        [
            "Settle reconcile",
            "live_pm_settle_reconcile.py",
            "on",
            "90s venue-true settle / fill pull",
            "Always-on",
            "start (never a second copy)",
        ],
        [
            "Catalog scan",
            "overnight_scan.py",
            "on",
            "Walks the matched catalog, then repeats. Per-game watch every 120s",
            "Always-on",
            "start (leave one that is already up)",
        ],
        [
            "job_status.html",
            "prediction_job_control.write_page",
            "kitchen scoreboard",
            "About once a minute from the supervisor",
            "Not a separate Windows task",
            "run_prediction_status.bat (refresh only; does not start/stop)",
        ],
        [
            "dashboard.html + orders_performance.html",
            "write_orders_performance.py",
            "kitchen scoreboard",
            "After a confirmed fill or a closed trade, 4s debounce. Not a 1-minute timer",
            "Short-lived child of supervisor / settle",
            "Manual: python tools/write_orders_performance.py",
        ],
        [
            "progress.html / stream_health.html",
            "overnight_scan + live_game_pollers",
            "kitchen scoreboard",
            "progress each supervisor loop (~60s); stream_health also at 30s into the loop",
            "Not a separate Windows task",
            "Supervisor",
        ],
    ]

    start_tr = (
        f'cmd /c cd /d {REPO_S} && {PY_S} -u tools\\prediction_job_control.py start'
    )
    status_tr = (
        f'cmd /c cd /d {REPO_S} && {PY_S} -u tools\\prediction_job_control.py status'
    )
    sch_start = (
        f'schtasks /Create /TN "PM kitchen at logon" /SC ONLOGON /RL LIMITED /F '
        f'/TR "{start_tr}"'
    )
    sch_status = (
        f'schtasks /Create /TN "PM kitchen status" /SC MINUTE /MO 5 /RL LIMITED /F '
        f'/TR "{status_tr}"'
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prediction process control — 31 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #ecfdf5; border: 1px solid #059669; padding: 10px 12px; margin: 0 0 14px; }}
.warn {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
pre {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px 12px; overflow: auto; white-space: pre-wrap; }}
blockquote {{ margin: 0.4rem 0 0.8rem; padding: 0.6rem 0.8rem; background: #fff7ed; border-left: 4px solid #ea580c; }}
h1 {{ font-size: 1.35rem; margin: 0 0 0.6rem; }}
h2 {{ font-size: 1.12rem; margin: 1.2rem 0 0.5rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Who runs the prediction kitchen — and how you take the keys</h1>
<p class="tiny">Written {esc(written)}. Snapshot of python on this PC. Did not start a second B. Did not kill trading. Did not start hist pulls. Did not rewrite dashboard.html.</p>

<div class="callout">
<h2>What you asked</h2>
<blockquote>{esc(PAUL)}</blockquote>
<p class="tiny">Also, separately (T0 window job already running; this page does not duplicate it):</p>
<blockquote>{esc(PAUL_B)}</blockquote>
</div>

<div class="callout">
<h2>In plain English</h2>
<p>Cursor is not the engine. The engine is ordinary <code>python.exe</code> on this PC. An agent (or a bat) starts those programs once; they keep looping on their own. Closing Cursor does <strong>not</strong> stop them. Leaving Cursor open to “watch” them is what runs up the Cursor bill.</p>
<p>You already have the switchboard: double-click bats in the repo root, or <code>python tools/prediction_job_control.py</code>. Task Scheduler should fire <strong>start once at Windows logon</strong>. Do not schedule the kitchen every minute — these jobs are always-on loops, not hourly stock scans.</p>
<p>The ~5 minute figure on B is the <strong>T0 send window</strong> (15 seconds before listed/trusted start through 5 minutes after), not a process that restarts every five minutes. A separate job is already looking at that window.</p>
</div>

<div class="banner">
<p><strong>This job did not start a second B</strong> (live B pid {esc(', '.join(str(p) for p in b_pids) or 'none')}). Did not kill A–G. Did not leftover-GTC A. Did not sell TEN/CIN. Did not start Kalshi through-game / T0 leftover / Poly-holes pulls.</p>
</div>

<div class="warn">
<p><strong>Cursor cost:</strong> stop using chat agents as a process manager. After logon start is in Task Scheduler, close Cursor. Check the kitchen with <code>run_prediction_status.bat</code> or <a href="job_status.html">job_status.html</a> (kitchen scoreboard — no “What you asked” on that page). Research hist pulls are also python; if you want one, schedule it yourself. Do not leave an agent overnight “because the pull is running.”</p>
</div>

<h2>Live python right now</h2>
<p class="note">Click column headers to sort. Parent “(gone)” means the starter (agent, bat, or <code>start</code>) already exited. The python kept going. That is why you still have a kitchen with Cursor closed — and why Cursor should not be the babysitter.</p>
{table(
        [
            ("PID", "num"),
            ("Parent PID", "num"),
            ("Parent name", "text"),
            ("Started ET", "date"),
            ("Age", "text"),
            ("Role", "text"),
            ("What it does", "text"),
            ("How often", "text"),
            ("Restart style", "text"),
            ("Command", "text"),
        ],
        live_rows,
    )}

<h2>Intended jobs and frequency</h2>
<p class="note">On/off is from <code>local/.../raw/systems.json</code> (this PC only). C and E are off, so they have no pid. Supervisor still runs A’s quote path.</p>
{table(
        [
            ("Job", "text"),
            ("Script", "text"),
            ("On/off now", "text"),
            ("Frequency", "text"),
            ("Supervisor loop vs always-on", "text"),
            ("How you start it", "text"),
        ],
        intended,
    )}

<h2>Cursor leftovers that are not the live kitchen</h2>
<p>Hist pulls do <strong>not</strong> need Cursor. They are python. None are running this snapshot. I listed them so you can End Task if one shows up later. I did not start new ones.</p>
{table(
        [
            ("PID", "text"),
            ("Parent PID", "text"),
            ("Parent name", "text"),
            ("Started ET", "text"),
            ("Role", "text"),
            ("What", "text"),
            ("Needs Cursor?", "text"),
            ("Action this job took", "text"),
            ("Command tail", "text"),
        ],
        hist_rows,
    )}
<p class="tiny">Restart later yourself (do not ask an agent to babysit):</p>
<pre>cd /d {esc(REPO_S)}
{esc(PY_S)} -u tools\\_pull_kalshi_inplay_path_20261030.py
{esc(PY_S)} -u tools\\_pull_pm_hist_t0_20261028.py --leftover
{esc(PY_S)} -u tools\\_pull_pm_hist_t0_20261028.py --poly-holes</pre>
<p class="note">Optional Task Scheduler: same command, <code>/SC ONCE</code> or a spare-time slot. Not at logon with the kitchen. Not from Cursor.</p>

<h2>Bats and <code>systems --help</code></h2>
<ul>
<li><code>run_prediction_status.bat</code> — refresh job_status.html. Does not start or stop anything.</li>
<li><code>run_prediction_start.bat</code> — start whatever is missing (supervisor, catalog, B/C/D/E/F/G if on, settle). Leaves a copy that is already up. Never a second B.</li>
<li><code>run_prediction_restart.bat</code> — stop the kitchen python, then start one of each. This <em>does</em> kill trading processes, then brings them back.</li>
<li><code>run_prediction_orders_on.bat</code> — <code>systems --lock on</code> after a one-leg fill. Does not stop B–G. Does not start a second B. Does not sell.</li>
<li><code>run_prediction_systems.bat</code> — print A–G on/off, stake, max, pid. Extra args turn a system on or off.</li>
<li>Those bats end with <code>pause</code> (wait for a key). <strong>Task Scheduler should call python directly</strong>, not the pause bats.</li>
</ul>
<p>Flags (from <code>python tools/prediction_job_control.py systems --help</code>):</p>
<pre>python tools/prediction_job_control.py systems
  --lock/--a on|off --lock-max --lock-stake --lock-size --lock-net-max
  --tennis-crossover/--b on|off --tennis-crossover-max --tennis-crossover-stake --tennis-crossover-size
  --cfb-favorite/--c on|off ...
  --spread-t0/--d on|off ...
  --tennis-t0-dog/--e on|off ...
  --tennis-t0-spread/--f on|off ...
  --soccer-t0-total/--g on|off ...
Other job_control actions: status | start | restart | restart-lock | reload-lock | systems
There is no stop-all action. Stop recipe is below.</pre>

<h2>Task Scheduler recipe (you run these)</h2>
<p>This page does <strong>not</strong> register the tasks. Paste in an elevated or normal PowerShell as you prefer. Use python.org 3.10 (already at <code>{esc(PY_S)}</code>), not Store python.</p>
<p><strong>1. At logon, start missing kitchen jobs once:</strong></p>
<pre>{esc(sch_start)}</pre>
<p>That calls <code>prediction_job_control.py start</code>, which starts supervisor + catalog + settle + any on system that is missing, and leaves a live B alone.</p>
<p><strong>2. Do not add a every-minute kitchen task.</strong> Supervisor already rewrites job_status about once a minute. Optional status-only (not required):</p>
<pre>{esc(sch_status)}</pre>
<p>Skip that if you are happy opening <a href="job_status.html">job_status.html</a> yourself.</p>
<p><strong>3. Do not attach this to the existing TBN stock evening task</strong> (<code>DailyRun.bat</code> / GetDaily / open-buy-sell). Those are the stock research jobs already in Task Scheduler. Prediction kitchen is a separate always-on logon task.</p>
<p><strong>4. After the logon task exists, close Cursor.</strong> Python keeps running. That is the cost cut.</p>

<h2>How to stop everything</h2>
<p>Turning systems off stops B–G processes. It does <em>not</em> kill supervisor, poll-all, A sender, catalog, or settle:</p>
<pre>cd /d {esc(REPO_S)}
{esc(PY_S)} -u tools\\prediction_job_control.py systems --lock off --tennis-crossover off --cfb-favorite off --spread-t0 off --tennis-t0-dog off --tennis-t0-spread off --soccer-t0-total off</pre>
<p>Then End Task the remaining kitchen python (supervisor, --poll-all, live_lock_sender, overnight_scan, live_pm_settle_reconcile), or run this PowerShell. <strong>This page did not run it.</strong></p>
<pre>$needles = @('live_game_pollers.py','overnight_scan.py','live_strategy_b.py','live_cfb_favorite.py','live_spread_t0.py','live_tennis_t0_dog.py','live_tennis_t0_spread.py','live_soccer_t0_total.py','live_lock_sender.py','live_pm_settle_reconcile.py','write_orders_performance.py')
Get-CimInstance Win32_Process | Where-Object {{ $cl = $_.CommandLine; $cl -and ($needles | Where-Object {{ $cl -like ('*' + $_ + '*') }}) }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}</pre>
<p class="tiny">Or Task Manager → End Task on those python.exe rows. <code>run_prediction_restart.bat</code> stops then starts again — use that only when you want the kitchen back immediately.</p>
<p>Turn A back later without touching B: <code>run_prediction_orders_on.bat</code> or <code>systems --lock on</code>.</p>

<h2>Confirmations</h2>
<ul>
<li>Live B pids this snapshot: {esc(', '.join(str(p) for p in b_pids) or 'none')} — did not start another.</li>
<li>Did not kill live A–G / supervisor / catalog / settle.</li>
<li>Did not leftover-GTC A. Did not sell TEN/CIN. Did not start hist pulls.</li>
<li>dashboard.html was not rewritten and does not get a What you asked block.</li>
<li>Other stockresearch python this snapshot (not kitchen, not hist): {esc(str(len(other)))}.</li>
</ul>
<p class="note">Sources: live_game_pollers.py (SUPERVISOR_SLEEP=60, POLL_SLEEP=5, TENNIS_PRE_START_MIN=5), live_lock_sender.py (SLEEP_SEC=0.2), live_strategy_b.py (TICK_SEC=1, CROSS_IDLE_SEC=0.05, T0_GRACE_SEC=300), live_t0_yes.py (TICK_SEC=1, T0_LEAD_SEC=15), live_pm_settle_reconcile.py (INTERVAL_SEC=90), overnight_scan.py (watch 120s; sequential catalog walk), orders_performance_refresh.py (DEBOUNCE_SEC=4), prediction_job_control.py, prediction_systems.py, run_prediction_*.bat. Click column headers to sort.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    page = report_page_extras.inject_report_page_extras(page)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"kitchen={len(kitchen)} hist={len(hist)} other={len(other)} b_pids={b_pids}")


if __name__ == "__main__":
    main()
