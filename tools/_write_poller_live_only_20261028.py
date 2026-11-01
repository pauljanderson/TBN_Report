"""Tennis pollers live-only. Research note. Not gold. Not DailyRun.

Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not retune C/D/A/stake.
"""
from __future__ import annotations

import html as html_mod
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers as lgp  # noqa: E402
import prediction_job_control as jc  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "poller_live_only_20261028.html"
HEALTH = RAW / "live_health"
STATUS = RAW / "live_pollers_status.json"

ASKED = (
    "Do now — kill unused pollers / stop twin-forever. The cheapest win. "
    "Tomorrow's listed tennis should not hold an 80 MB Python and four sockets today. "
    "we only need tennis matches being polled during a live match so we can collect data."
)
PLAIN = (
    "We were running a full Python helper (about 80 MB, up to four price sockets) "
    "for every tennis match Kalshi and Polymarket both list — including matches that "
    "do not start until tomorrow. That is why the count sat near 125 helpers and "
    "11 GB of RAM in the afternoon. Now a tennis helper starts 5 minutes before the "
    "trusted start, stays while the match is on, and dies when the match is over, "
    "not today, or never went live (30 minutes after listed start). One helper watches "
    "both books. Research only. Not gold. Not DailyRun."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value), quote=True)


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(_th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    if total:
        tds = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{tds}</tr>')
    return (
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _census() -> dict:
    script = r"""
$ErrorActionPreference = 'Continue'
$openConsole = @(Get-Process -Name OpenConsole -ErrorAction SilentlyContinue).Count
$conhost = @(Get-Process -Name conhost -ErrorAction SilentlyContinue).Count
$python = @(Get-Process -Name python,pythonw -ErrorAction SilentlyContinue)
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Select-Object ProcessId, ParentProcessId, Name, CommandLine, WorkingSetSize
$out = [ordered]@{
  checked = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  OpenConsole = $openConsole
  conhost = $conhost
  python_n = $python.Count
  rows = @()
}
foreach ($p in $procs) {
  $cl = if ($p.CommandLine) { $p.CommandLine } else { '' }
  $out.rows += [ordered]@{
    pid = [int]$p.ProcessId
    ppid = [int]$p.ParentProcessId
    ram_mb = [math]::Round($p.WorkingSetSize/1MB, 1)
    cmd = $cl
  }
}
$tcp = @(Get-NetTCPConnection -ErrorAction SilentlyContinue)
$out.tcp_all = $tcp.Count
$out | ConvertTo-Json -Depth 5 -Compress
"""
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            errors="replace",
            timeout=45,
            cwd=str(ROOT),
        )
        data = json.loads(raw)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"error": type(exc).__name__, "rows": [], "poller_n": None}
    rows = data.get("rows") or []
    pollers = []
    named = []
    for row in rows:
        cmd = str(row.get("cmd") or "")
        low = cmd.lower()
        if "--poll-one" in cmd:
            pollers.append(row)
        elif "live_game_pollers.py" in low:
            named.append({**row, "role": "supervisor"})
        elif "overnight_scan.py" in low:
            named.append({**row, "role": "catalog scan"})
        elif "live_strategy_b.py" in low:
            named.append({**row, "role": "B"})
        elif "live_cfb_favorite.py" in low:
            named.append({**row, "role": "C"})
        elif "live_spread_t0.py" in low:
            named.append({**row, "role": "D"})
        elif "live_tennis_t0_dog.py" in low:
            named.append({**row, "role": "E"})
    ram = [float(r.get("ram_mb") or 0) for r in pollers]
    parents = Counter(int(r.get("ppid") or 0) for r in pollers)
    poller_pids = {int(r.get("pid") or 0) for r in pollers}
    tcp_n = data.get("tcp_all")
    return {
        "checked": data.get("checked") or datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "OpenConsole": data.get("OpenConsole"),
        "conhost": data.get("conhost"),
        "python_n": data.get("python_n"),
        "pollers": pollers,
        "named": named,
        "poller_n": len(pollers),
        "poller_ram_sum": round(sum(ram), 1),
        "poller_ram_avg": round(sum(ram) / len(ram), 1) if ram else 0,
        "parents": dict(parents),
        "tcp_all": tcp_n,
        "poller_pids": sorted(p for p in poller_pids if p),
    }


def main() -> int:
    now = datetime.now(ET)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S ET")
    census = _census()
    status = _json(STATUS)
    games = status.get("games") if isinstance(status.get("games"), list) else []
    future = 0
    tennis_n = 0
    for row in games:
        if not isinstance(row, dict):
            continue
        if str(row.get("sport") or "").lower() == "tennis":
            tennis_n += 1
        start = str(row.get("start") or "")
        if start[:10] > now.date().isoformat():
            future += 1
    fery = _json(HEALTH / "tennis_fermus_2026_10_29.json")
    jobs = jc.classify(jc._ps_rows())
    sup = (jobs.get("supervisor") or [{}])[0]
    scan = (jobs.get("scan") or [{}])[0]
    b = (jobs.get("strategy_b") or [{}])[0]
    named = {row.get("role"): row for row in census.get("named") or []}

    asked_html = esc(ASKED)
    plain_html = esc(PLAIN)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Tennis pollers live-only 2026-10-28</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 0.4rem; font-size: 1.05rem; }}
.tape {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Tennis pollers: live window only</h1>
<p class="note">Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now_s)}.
Research only. Not gold. Not DailyRun. This page does not place a bet.
Kitchen scoreboard stays <a href="dashboard.html">dashboard.html</a>.
Up/down: <a href="job_status.html">job_status.html</a>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul agrees and says implement: “{asked_html}”</p>
<h2>In plain English</h2>
<p>{plain_html}</p>
</div>

<div class="tape">
<h2>What changed</h2>
<ul>
<li>Kalshi+Polymarket twins are not forever-on. Same live window as unmatched books.</li>
<li>Spawn <strong>{esc(str(lgp.TENNIS_PRE_START_MIN))} minutes</strong> before trusted/listed start
(existing unmatched knob). Kill on settle, after a typical tennis length (5 hours),
or <strong>{esc(str(lgp.TENNIS_NEVER_LIVE_MIN))} minutes</strong> after listed start if the match never went live.</li>
<li>Tomorrow-or-later ET calendar date does not spawn. Supervisor reaps idle helpers, including adopted PIDs that used to survive <code>terminate()</code>.</li>
<li>Hidden consoles stay hidden (<code>CREATE_NO_WINDOW</code>). One supervisor reloaded. B/C/D/E/catalog scan left. No second B. C=1.05, D=0.25, leftover GTC on A, and stake were not retuned.</li>
</ul>
</div>

<h2>Live window (exact)</h2>
{_table(
    [("Knob", "text"), ("Value", "text"), ("What it is", "text"), ("Used for spawn?", "text")],
    [
        ["TENNIS_PRE_START_MIN", f"{lgp.TENNIS_PRE_START_MIN} minutes before listed/trusted start",
         "Existing unmatched-book lead in tennis_collect_now. Supervisor loop is 60s, so a 15s lead would miss T0.",
         "Yes — spawn lead"],
        ["T0 send window (live_t0_yes.t0_window)", "15 seconds before through T0_GRACE_SEC=300 after",
         "When B/E may send at game start. Pollers must already be up, which is why spawn is 5 minutes, not 15 seconds.",
         "No — send only"],
        ["T0_GRACE_SEC", "300 seconds after trusted start",
         "B/E grace after T0. Not a poller lifetime.",
         "No"],
        ["slate_near_t0", "15 minutes before listed start through typical length",
         "C/D/E walk this slate. Not a poller spawn clock.",
         "No"],
        ["WHEN_LIVE", "Novig fee flag (OPEN_INGAME)",
         "Fee charged in-game only. Not a spawn clock.",
         "No"],
        ["TENNIS_NEVER_LIVE_MIN", f"{lgp.TENNIS_NEVER_LIVE_MIN} minutes after listed start",
         "If the match never went in-play, drop the helper.",
         "Yes — kill"],
        ["LIVE_HOURS tennis", f"{lgp.LIVE_HOURS.get('tennis')} hours after listed start",
         "Typical length backstop. In-play (OPEN_INGAME / S1–S5) stays until settled.",
         "Yes — cap / in-play override"],
        ["Calendar", "America/New_York date after today",
         "Tomorrow-or-later listed/trusted start does not spawn.",
         "Yes — hard no"],
        ["Settle", "period POST / settled / ended",
         "Helper dies. Worker also exits if the job file already says POST or tomorrow.",
         "Yes — kill"],
        ["Twins", "one helper per match",
         "Kalshi+Poly listed together share one --poll-one. Two helpers only while both would be in the live window; they die when the match is over / not today.",
         "Yes"],
    ],
)}
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>

<h2>Before vs after</h2>
<p>Request census ~15:00 ET: 125 <code>python --poll-one</code> helpers, parent supervisor 38656,
~198 sockets, ~11 GB RAM, twins up for matches listed tomorrow.
Implementation-time census 15:24:24 ET (same PC, after that 15:00 snapshot): 116 helpers,
parent 60888, 501 TCP rows owned by those PIDs (all states), 6.4 GB working set.
Reload-lock 15:27:58 ET started supervisor <strong>71868</strong> and respawned only the live window.
First loop 74 helpers. ~15:29 as 15:30 starts entered the 5-minute lead: 83 helpers.</p>
{_table(
    [("When", "text"), ("python --poll-one", "num"), ("Supervisor pid", "text"), ("Helper RAM MB", "num"),
     ("Sockets (measured)", "text"), ("Expected sockets (4 × N)", "num"), ("B pid", "text"), ("OpenConsole", "num")],
    [
        ["~15:00 ET (request census)", "125", "38656", "11000", "~198", "500", "—", "—"],
        ["15:24:24 ET (before this change)", "116", "60888", "6408.8", "501 (poller-owned TCP, all states)", "464", "74812", "2"],
        ["15:28:06 ET (just after reload-lock)", "74", "71868", "—", "—", "296", "74812", "2"],
        [f"{esc(census.get('checked'))} ET (this page)",
         str(census.get("poller_n")),
         str((named.get("supervisor") or {}).get("pid") or sup.get("pid") or "—"),
         str(census.get("poller_ram_sum")),
         f"Get-NetTCPConnection on new PIDs returned 0 (not elevated); machine TCP {census.get('tcp_all')}",
         str(4 * int(census.get("poller_n") or 0)),
         str((named.get("B") or {}).get("pid") or b.get("pid") or "—"),
         str(census.get("OpenConsole")),
         ],
    ],
)}
<p class="note">Drop vs 125: {esc(str((census.get('poller_n') or 0) - 125))} helpers.
Drop vs 116: {esc(str((census.get('poller_n') or 0) - 116))} helpers.
RAM {esc(str(census.get('poller_ram_sum')))} MB vs 6409 MB before.
One supervisor. Catalog scan pid {esc(str(scan.get('pid') or (named.get('catalog scan') or {}).get('pid') or '—'))} left.
C/D/E left. OpenConsole stayed 2 — helpers did not steal focus.</p>

<h2>Proof tomorrow twins died</h2>
<p>Fery vs Musetti (<code>tennis_fermus_2026_10_29</code>) was a Kalshi+Poly+Novig helper
pid 26968 from 15:24:39 through 15:27:55 ET, transport
<code>{esc(fery.get('transport') or 'websocket: kalshi, novig, polymarket')}</code>.
Listed date in the key is 2026-10-29 (tomorrow). After reload it is not in
<code>live_pollers_status.json</code>. Current intended live set:
{esc(str(status.get('live_count')))} games, tennis {esc(str(tennis_n))},
listed start date after today: {esc(str(future))}.</p>
{_table(
    [("Field", "text"), ("Value", "text")],
    [
        ["Supervisor pid (one)", str(status.get("supervisor_pid") or sup.get("pid") or "—")],
        ["Intended live set", str(status.get("live_count"))],
        ["Actual python --poll-one", str(census.get("poller_n"))],
        ["Status updated", str(status.get("updated_at") or "—")],
        ["Tomorrow keys in live set", str(future)],
        ["B copies", str(len(jobs.get("strategy_b") or []))],
    ],
)}

<h2>Tests</h2>
{_table(
    [("Test", "text"), ("Result", "text")],
    [
        ["tomorrow-listed twin does not spawn", "pass"],
        ["in-window twin (3 min before start) does spawn", "pass"],
        ["too-early today (3 hours before start) does not spawn", "pass"],
        ["period=POST settled match does not spawn; worker exits", "pass"],
        ["never-live 45 min after listed does not spawn", "pass"],
        ["in-play (S2 / OPEN_INGAME) 45 min after listed still spawns", "pass"],
        ["adopted PID terminate() actually kills; supervisor calls reap_idle_pollers", "pass"],
        ["hidden CREATE_NO_WINDOW spawn flags unchanged", "pass"],
        ["python tools/test_live_game_pollers.py", "ok"],
    ],
)}
<p class="note">Code: <code>tools/live_game_pollers.py</code> (<code>tennis_collect_now</code>,
<code>reap_idle_pollers</code>, <code>Tracked.terminate</code>),
<code>tools/prediction_job_control.py</code> job_status copy,
<code>python tools/prediction_job_control.py reload-lock</code> (one supervisor, not a second B).</p>
</body>
{SORTABLE_TABLE_SCRIPT}
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    print(PAGE)
    print(f"poller_n={census.get('poller_n')} supervisor={status.get('supervisor_pid')} future={future}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
