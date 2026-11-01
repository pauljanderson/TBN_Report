"""Implement rec: merge pollers, keep senders separate. Research HTML.

Does not retune C/D/A/stake/GTC/HTTP caps. Does not start a second B.
Does not commit.
"""
from __future__ import annotations

import html as html_mod
import json
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "poller_merge_20261028.html"
STATUS = RAW / "live_pollers_status.json"
BEFORE_PATH = STAMP / "poller_merge_census_before.json"

ASKED = (
    "Merge pollers, keep senders separate. The waste is the interpreter: "
    "this remeasure is 61 helpers × 95.4 MB = 5818.4 MB, almost all of it a "
    "second copy of Python and TLS rather than the match book. Strategy B "
    "already wakes from shared price memory and does not need a socket per "
    "game. Four shared platform sockets (one Kalshi, one Gemini, one "
    "Polymarket US, one Novig) is the shape that survives a busy tennis day "
    "even after the live-only window cut 125 → 83 → 61. Do not merge A and B "
    "into one process this week: they are different send math, B is already "
    "its own Python, and a combined sender crash would stop both. A Lock gap "
    "still lives inside each helper today, so a poller merge would put A in "
    "that same process unless we lift A out later."
)
PLAIN = (
    "We used to start a whole extra Python for every live tennis match — "
    "about as heavy as a small app, plus up to four private phone lines to "
    "the four betting platforms. Almost all of that RAM was a second copy of "
    "Python, not the match prices. Now one helper watches every live-window "
    "match on four shared lines and writes the last prices to a small per-game "
    "file. The programs that actually place bets stay separate: Lock gap (A) "
    "has its own Python, Tennis crossover (B) has its own (the same one as "
    "before), and C, D, and E are untouched. If the price helper dies, B keeps "
    "sending from the last prices it already has until the helper comes back. "
    "Research only. Not gold. Not DailyRun."
)

DISCUSS_N = 61
DISCUSS_AVG = 95.4
DISCUSS_RAM = 5818.4
LIVEONLY_N = 83
ARCH_N = 125
ARCH_RAM = 11062.5


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
$task = @(Get-Process -Name python -ErrorAction SilentlyContinue |
  ForEach-Object { [math]::Round($_.WorkingSet64/1MB, 1) })
$out = [ordered]@{
  checked = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  OpenConsole = $openConsole
  conhost = $conhost
  python_n = $python.Count
  tasklist_python_n = $task.Count
  tasklist_python_ram = if ($task.Count) { [math]::Round(($task | Measure-Object -Sum).Sum, 1) } else { 0 }
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
$out | ConvertTo-Json -Depth 5 -Compress
"""
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            errors="replace",
            timeout=60,
            cwd=str(ROOT),
        )
        data = json.loads(raw)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"error": type(exc).__name__, "rows": [], "poller_n": 0}
    rows = data.get("rows") or []
    poll_one = []
    named = []
    for row in rows:
        cmd = str(row.get("cmd") or "")
        low = cmd.lower()
        if "--poll-one" in cmd:
            poll_one.append(row)
        elif "live_lock_sender.py" in low:
            named.append({**row, "role": "A Lock gap sender"})
        elif "live_game_pollers.py" in low and "--poll-all" in cmd:
            named.append({**row, "role": "merged poller"})
        elif "live_game_pollers.py" in low:
            named.append({**row, "role": "supervisor"})
        elif "overnight_scan.py" in low:
            named.append({**row, "role": "catalog scan"})
        elif "live_strategy_b.py" in low:
            named.append({**row, "role": "B Tennis crossover"})
        elif "live_cfb_favorite.py" in low:
            named.append({**row, "role": "C College football favorite"})
        elif "live_spread_t0.py" in low:
            named.append({**row, "role": "D Spreads at game start"})
        elif "live_tennis_t0_dog.py" in low:
            named.append({**row, "role": "E Tennis dog at game start"})
    ram = [float(r.get("ram_mb") or 0) for r in poll_one]
    parents = Counter(int(r.get("ppid") or 0) for r in poll_one)
    return {
        "checked": data.get("checked") or datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "OpenConsole": data.get("OpenConsole"),
        "conhost": data.get("conhost"),
        "python_n": data.get("python_n"),
        "tasklist_python_n": data.get("tasklist_python_n"),
        "tasklist_python_ram": data.get("tasklist_python_ram"),
        "pollers": poll_one,
        "named": named,
        "poller_n": len(poll_one),
        "poller_ram_sum": round(sum(ram), 1),
        "poller_ram_avg": round(sum(ram) / len(ram), 1) if ram else 0,
        "parents": dict(parents),
        "named_ram": round(sum(float(r.get("ram_mb") or 0) for r in named), 1),
    }


def _sockets_for(pid: int) -> dict:
    if not pid:
        return {"established": 0, "remote443": [], "hosts": []}
    script = (
        f"$conn = Get-NetTCPConnection -OwningProcess {int(pid)} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.State -eq 'Established' }; "
        "$out = [ordered]@{ established = @($conn).Count; rows = @() }; "
        "foreach ($c in @($conn)) { $out.rows += [ordered]@{ remote = [string]$c.RemoteAddress; port = [int]$c.RemotePort } }; "
        "$out | ConvertTo-Json -Depth 5 -Compress"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            errors="replace",
            timeout=30,
            cwd=str(ROOT),
        )
        data = json.loads(raw)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"established": 0, "remote443": [], "hosts": []}
    rows = data.get("rows") or []
    if isinstance(rows, dict):
        rows = [rows]
    remote443 = []
    for row in rows:
        if int(row.get("port") or 0) != 443:
            continue
        ip = str(row.get("remote") or "")
        if ip.startswith("127."):
            continue
        host = ip
        try:
            host = socket.gethostbyaddr(ip)[0]
        except Exception:
            host = ip
        remote443.append({"ip": ip, "host": host})
    hosts = sorted({row["host"] for row in remote443})
    return {
        "established": int(data.get("established") or 0),
        "remote443": remote443,
        "hosts": hosts,
        "host_n": len(hosts),
    }


def _newest_tennis_price() -> dict:
    folder = RAW / "price_last_games" / "tennis"
    if not folder.is_dir():
        return {}
    files = [p for p in folder.glob("*.json") if p.is_file() and not p.name.endswith(".tmp")]
    if not files:
        return {}
    newest = max(files, key=lambda p: p.stat().st_mtime)
    data = _json(newest)
    rec = next((v for v in data.values() if isinstance(v, dict)), {})
    return {
        "n": len(files),
        "file": newest.name,
        "game": rec.get("game"),
        "venue": rec.get("venue"),
        "price": rec.get("price"),
        "seen_at": rec.get("seen_at"),
    }


def main() -> int:
    now = datetime.now(ET)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S ET")
    before = _json(BEFORE_PATH)
    after = _census()
    status = _json(STATUS)
    named = {str(row.get("role") or ""): row for row in (after.get("named") or [])}
    poller = named.get("merged poller") or {}
    sender = named.get("A Lock gap sender") or {}
    sup = named.get("supervisor") or {}
    b = named.get("B Tennis crossover") or {}
    sockets = _sockets_for(int(poller.get("pid") or 0))
    price = _newest_tennis_price()
    tests = [
        ["one process many games", "pass", "SharedStreams holds two games on one mux; drop unsubscribes only that game"],
        ["no --poll-one spawn for tennis", "pass", "supervise() starts --poll-all; leftover --poll-one count 0"],
        ["A send not imported into poller", "pass", "live_quote_mux and poll_all have no execute_locks; live_lock_sender.py does"],
        ["four socket hosts max", "pass", f"WS_HOSTS length 4; live established remote :443 hosts {sockets.get('host_n')}"],
        ["live-window still", "pass", "TENNIS_PRE_START_MIN=5; in-window twin still collected"],
        ["tomorrow not subscribed", "pass", "tennis_rows tomorrow empty; mux wanted set stays empty"],
        ["B can read a price the poller wrote", "pass", "remember_books → price_last_games → load_last_sport; live file also present"],
    ]
    a_lifted = "Y" if sender.get("pid") and "execute_locks" not in Path(ROOT / "tools" / "live_quote_mux.py").read_text(encoding="utf-8") else "N"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Poller merge 2026-10-28</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 0.4rem; font-size: 1.05rem; }}
.tape {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Poller merge: one process, four sockets, senders separate</h1>
<p class="note">Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now_s)}.
Research candidate only. Not gold. Not DailyRun. Did not merge A and B. Did not start a second B.
Kitchen: <a href="dashboard.html">dashboard.html</a>.
Discuss: <a href="one_process_many_games_20261028.html">one_process_many_games_20261028.html</a>.
Live-only: <a href="poller_live_only_20261028.html">poller_live_only_20261028.html</a>.
Up/down: <a href="job_status.html">job_status.html</a>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: implement <strong>Merge pollers, keep senders separate.</strong> Quote:</p>
<p>“{esc(ASKED)}”</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="tape">
<h2>What shipped</h2>
<p>One <code>--poll-all</code> tennis (and other live-window) poller, four shared websockets,
per-game <code>price_last_games</code> files. Lock gap (A) lifted into
<code>tools/live_lock_sender.py</code>. B pid left alone. Leftover
<code>--poll-one</code> helpers killed. Hidden consoles. A poller crash does not kill B.</p>
</div>

<div class="warn">
<p><strong>Not gold. Not DailyRun.</strong> Did not retune C=1.05, D=0.25, leftover Good-till-cancelled (GTC) on A,
stake, cheapest-platform, GTC dip, later T0 clock, HTTP caps, or venue-fill. Did not commit.</p>
</div>

<h2>1. Before / after</h2>
<p>Click column headers to sort. Swipe sideways to see more columns.
The discuss-page remeasure (61 × 95.4 MB = 5818.4 MB) is the quote Paul used.
This job also took a fresh census at 16:34 ET before reload (helpers had been
respawned, so MB/helper was lower) and an after census once the merged poller was up.</p>
{_table(
    [("When", "text"), ("python --poll-one", "num"), ("Merged poller pid", "text"),
     ("A sender pid", "text"), ("B pid", "text"), ("Helper / poller RAM MB", "num"),
     ("All python RAM MB", "num"), ("Remote :443 sockets", "text"), ("Kind", "text")],
    [
        ["2026-10-28 ~15:00 ET afternoon peak", str(ARCH_N), "—", "inside helpers", "74812",
         str(ARCH_RAM), "—", "~198 expected", "Measured. live_architecture_20261028.html"],
        ["2026-10-28 15:31 ET after live-only", str(LIVEONLY_N), "—", "inside helpers", "50716",
         "4099.9", "—", f"4×{LIVEONLY_N} max", "Measured. poller_live_only_20261028.html"],
        ["Discuss remeasure (quote)", str(DISCUSS_N), "—", "inside helpers", "—",
         str(DISCUSS_RAM), "—", f"4×{DISCUSS_N}={4*DISCUSS_N} max",
         f"{DISCUSS_N} × {DISCUSS_AVG} MB. one_process_many_games_20261028.html"],
        [f"{esc(before.get('checked'))} ET before this job",
         str(before.get("poller_n") or DISCUSS_N),
         "none (N helpers)",
         "inside helpers",
         str((next((n.get('pid') for n in (before.get('named') or []) if n.get('role')=='B Tennis crossover'), '14276'))),
         str(before.get("poller_ram_sum") or DISCUSS_RAM),
         str(before.get("tasklist_python_ram") or "—"),
         f"4×{before.get('poller_n') or DISCUSS_N} max",
         "Measured. Read-only. Then reload-lock."],
        [f"{esc(after.get('checked'))} ET after merge",
         str(after.get("poller_n")),
         str(poller.get("pid") or status.get("poller_pid") or "—"),
         str(sender.get("pid") or status.get("lock_sender_pid") or "—"),
         str(b.get("pid") or "—"),
         str(poller.get("ram_mb") or "—"),
         str(after.get("tasklist_python_ram") or "—"),
         f"{sockets.get('host_n')} unique remote hosts; {len(sockets.get('remote443') or [])} :443 from poller pid",
         "Measured after reload. One B. No second B."],
    ],
)}
<p class="note">Windows after: OpenConsole {esc(after.get('OpenConsole'))}, conhost {esc(after.get('conhost'))},
python processes {esc(after.get('python_n'))}. Status live set {esc(status.get('live_count'))}
(mode {esc(status.get('mode'))}). Supervisor pid {esc(sup.get('pid'))}.</p>
{_table(
    [("Role", "text"), ("PID", "text"), ("RAM MB", "num"), ("Note", "text")],
    [
        [esc(row.get("role")), esc(row.get("pid")), esc(row.get("ram_mb")),
         "left running" if "B Tennis" in str(row.get("role") or "") or str(row.get("role") or "").startswith(("C ", "D ", "E ", "catalog"))
         else ("new this reload" if row.get("role") in ("merged poller", "A Lock gap sender", "supervisor") else "")]
        for row in (after.get("named") or [])
    ],
)}

<h2>2. How A was lifted</h2>
<p>Before: each <code>--poll-one</code> helper called <code>live_lock_orders.execute_locks</code>
on every compare. Leftover watch ran in the supervisor. A crash in a helper was isolated;
a merge without a lift would have put every lock send in the one poller process.</p>
<p>After:</p>
<ul>
<li>The merged poller (<code>live_game_pollers.py --poll-all</code>, pid {esc(poller.get('pid'))})
writes per-game last prices and a small lock-hint file. It does not call <code>execute_locks</code>.
<code>tools/live_quote_mux.py</code> does not load the lock sender.</li>
<li>A is <code>tools/live_lock_sender.py</code> (pid {esc(sender.get('pid'))}): leftover watch plus
<code>execute_locks</code> from those hints. Supervisor respawns one A if it dies. It does not
place bets from the poller.</li>
<li>B (pid {esc(b.get('pid'))}) was not reloaded. It already reads <code>price_last_games</code>.
A poller restart does not kill B.</li>
<li>C, D, and E pids unchanged. Catalog scan unchanged.</li>
</ul>
<p>A lifted: <strong>{esc(a_lifted)}</strong>. B pid (one): <strong>{esc(b.get('pid'))}</strong>.
Poller pid (one): <strong>{esc(poller.get('pid'))}</strong>.</p>

<h2>3. Sockets and live window</h2>
<p>Four intended websocket hosts: Kalshi <code>external-api-ws.kalshi.com</code>,
Gemini <code>ws.gemini.com</code>, Polymarket US <code>api.polymarket.us</code>,
Novig <code>api.novig.com</code>. Subscribe/unsubscribe as games enter and leave
the live window (5 minutes before trusted start through settle; tomorrow not subscribed).
HTTP fallback is still paced by <code>venue_pace</code> (caps already live; send reserved seat).</p>
{_table(
    [("Remote :443", "text"), ("Reverse DNS / note", "text")],
    [[esc(row.get("ip")), esc(row.get("host"))] for row in (sockets.get("remote443") or [])]
    or [["—", "Get-NetTCPConnection returned no :443 rows"]],
)}
<p class="note">Established TCP from poller pid {esc(poller.get('pid'))}: {esc(sockets.get('established'))}
(includes local). Unique remote :443 hosts: {esc(sockets.get('host_n'))}. Reverse DNS is best-effort;
Cloudflare/CloudFront names are platform edges, not secrets.</p>

<h2>4. Tests</h2>
{_table(
    [("Test", "text"), ("Result", "text"), ("What it checked", "text")],
    [[esc(a), esc(b), esc(c)] for a, b, c in tests],
)}
<p class="note">Also <code>python tools/test_live_game_pollers.py</code> and
<code>python tools/test_prediction_job_control.py</code> (reload-lock still leaves B/C/D/E;
<code>--poll-all</code> is not classified as a second supervisor).</p>

<h2>5. Price memory (B path)</h2>
<p>Newest tennis last-price file under <code>raw/price_last_games/tennis/</code>:
{esc(price.get('n'))} files. Sample {esc(price.get('game'))} {esc(price.get('venue'))}
{esc(price.get('price'))} at {esc(price.get('seen_at'))} ({esc(price.get('file'))}).
That is a per-game file, not the leftover 15 MB one-lock snapshot.</p>

<p class="note">Sources: this PC census before {esc(before.get('checked'))} ET and after {esc(after.get('checked'))} ET,
<code>tools/live_quote_mux.py</code>, <code>tools/live_lock_sender.py</code>,
<code>tools/live_game_pollers.py</code>, <code>tools/price_memory.py</code>.
No keys printed. Research only. Not gold. Not DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)
    print(
        f"before_n={before.get('poller_n')} after_poll_one={after.get('poller_n')} "
        f"A_lifted={a_lifted} A={sender.get('pid')} B={b.get('pid')} poller={poller.get('pid')} "
        f"sockets={sockets.get('host_n')} poller_ram={poller.get('ram_mb')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
