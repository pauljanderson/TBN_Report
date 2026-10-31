"""Discuss: one process, many games. Research note. Does not implement a merge.

Does not place, cancel, or sell. Does not start or stop B/C/D/E.
Does not revert HTTP budget, GTC, venue-truth, or live-only pollers.
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

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "one_process_many_games_20261028.html"
STATUS = RAW / "live_pollers_status.json"

ASKED = (
    "Discuss — One process, many games. Today: one Python per game "
    "(~measured MB each, own GIL, own 4 sockets). Crash isolation is the benefit. "
    "RAM and TLS sessions are the cost. One asyncio process with many games would "
    "cut working set and share four platform sockets. Harder blast radius."
)
PLAIN = (
    "Each live tennis match currently gets its own copy of Python, about "
    "the size of a small app, plus up to four private phone lines to the four "
    "betting platforms (Kalshi, Gemini, Polymarket US, Novig). If one match's "
    "helper dies, the others keep ticking — that is the benefit. The cost is "
    "gigabytes of RAM and hundreds of duplicate connections. This page compares "
    "that shape with one shared helper that watches many games on four shared "
    "lines. It does not merge anything. Research only. Not gold. Not DailyRun."
)

# Sibling pages (do not overwrite). Afternoon peak before live-only.
ARCH_N = 125
ARCH_RAM = 11062.5
ARCH_AVG = 88.5
ARCH_SOCKETS = 198
ARCH_SUP = 38656
ARCH_WHEN = "2026-10-28 15:04:08 ET"
LIVEONLY_N = 83
LIVEONLY_RAM = 4099.9
LIVEONLY_SUP = 71868
LIVEONLY_WHEN = "2026-10-28 15:31:21 ET"
LIVEONLY_FIRST = 74


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
    """Live Windows process census. Read-only. Does not start or stop anything."""
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
            named.append({**row, "role": "B Tennis crossover"})
        elif "live_cfb_favorite.py" in low:
            named.append({**row, "role": "C College football favorite"})
        elif "live_spread_t0.py" in low:
            named.append({**row, "role": "D Spreads at game start"})
        elif "live_tennis_t0_dog.py" in low:
            named.append({**row, "role": "E Tennis dog at game start"})
    ram = [float(r.get("ram_mb") or 0) for r in pollers]
    parents = Counter(int(r.get("ppid") or 0) for r in pollers)
    return {
        "checked": data.get("checked") or datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "OpenConsole": data.get("OpenConsole"),
        "conhost": data.get("conhost"),
        "python_n": data.get("python_n"),
        "tasklist_python_n": data.get("tasklist_python_n"),
        "tasklist_python_ram": data.get("tasklist_python_ram"),
        "pollers": pollers,
        "named": named,
        "poller_n": len(pollers),
        "poller_ram_sum": round(sum(ram), 1),
        "poller_ram_avg": round(sum(ram) / len(ram), 1) if ram else 0,
        "poller_ram_min": round(min(ram), 1) if ram else 0,
        "poller_ram_max": round(max(ram), 1) if ram else 0,
        "parents": dict(parents),
        "named_ram": round(sum(float(r.get("ram_mb") or 0) for r in named), 1),
    }


def _boxes_svg(n: int, avg: float) -> str:
    """Today (N Pythons, 4 sockets each) vs one process (4 shared sockets)."""
    return f"""<svg viewBox="0 0 1100 420" role="img" aria-label="Today one Python per game versus one process many games">
  <style>
    .box {{ fill:#f8fafc; stroke:#334155; stroke-width:1.3; }}
    .py {{ fill:#eef2ff; stroke:#3730a3; stroke-width:1.3; }}
    .send {{ fill:#fff7ed; stroke:#c2410c; stroke-width:1.3; }}
    .mem {{ fill:#ecfdf5; stroke:#047857; stroke-width:1.3; }}
    .h {{ font: 700 13px Segoe UI, system-ui, sans-serif; fill:#0f172a; }}
    .t {{ font: 12px Segoe UI, system-ui, sans-serif; fill:#0f172a; }}
    .s {{ font: 11px Segoe UI, system-ui, sans-serif; fill:#475569; }}
    .arr {{ stroke:#334155; stroke-width:1.5; fill:none; marker-end:url(#arr2); }}
  </style>
  <defs>
    <marker id="arr2" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#334155"/>
    </marker>
  </defs>
  <text class="h" x="8" y="22">Today — one Python per game</text>
  <rect class="box" x="8" y="36" width="118" height="40" rx="5"/><text class="t" x="16" y="60">Kalshi</text>
  <rect class="box" x="134" y="36" width="118" height="40" rx="5"/><text class="t" x="142" y="60">Gemini</text>
  <rect class="box" x="260" y="36" width="118" height="40" rx="5"/><text class="t" x="268" y="60">Polymarket</text>
  <rect class="box" x="386" y="36" width="118" height="40" rx="5"/><text class="t" x="394" y="60">Novig</text>
  <path class="arr" d="M67,76 L67,110"/><path class="arr" d="M193,76 L193,110"/>
  <path class="arr" d="M319,76 L319,110"/><path class="arr" d="M445,76 L445,110"/>
  <rect class="py" x="8" y="112" width="160" height="78" rx="5"/>
  <text class="h" x="16" y="132">Helper 1</text>
  <text class="s" x="16" y="150">own GIL, ~{esc(str(avg))} MB</text>
  <text class="s" x="16" y="166">up to 4 sockets</text>
  <text class="s" x="16" y="182">A lock-gap inside</text>
  <rect class="py" x="178" y="112" width="160" height="78" rx="5"/>
  <text class="h" x="186" y="132">Helper 2</text>
  <text class="s" x="186" y="150">own GIL, ~{esc(str(avg))} MB</text>
  <text class="s" x="186" y="166">up to 4 sockets</text>
  <text class="s" x="186" y="182">A lock-gap inside</text>
  <rect class="py" x="348" y="112" width="156" height="78" rx="5"/>
  <text class="h" x="356" y="132">… × {esc(str(n))}</text>
  <text class="s" x="356" y="150">supervisor --poll-one</text>
  <text class="s" x="356" y="166">crash dies alone</text>
  <text class="s" x="356" y="182">TLS × up to 4N</text>
  <path class="arr" d="M256,190 L256,220"/>
  <rect class="mem" x="130" y="222" width="250" height="52" rx="5"/>
  <text class="h" x="140" y="242">price memory (files)</text>
  <text class="s" x="140" y="260">B reads this, not sockets</text>
  <path class="arr" d="M255,274 L80,310"/><path class="arr" d="M255,274 L190,310"/>
  <path class="arr" d="M255,274 L300,310"/><path class="arr" d="M255,274 L410,310"/>
  <rect class="send" x="8" y="312" width="90" height="50" rx="5"/><text class="t" x="16" y="342">A in helper</text>
  <rect class="send" x="108" y="312" width="90" height="50" rx="5"/><text class="t" x="124" y="342">B own</text>
  <rect class="send" x="208" y="312" width="90" height="50" rx="5"/><text class="t" x="224" y="342">C own</text>
  <rect class="send" x="308" y="312" width="90" height="50" rx="5"/><text class="t" x="324" y="342">D own</text>
  <rect class="send" x="408" y="312" width="90" height="50" rx="5"/><text class="t" x="424" y="342">E own</text>
  <text class="s" x="8" y="386">One match helper dies → others keep ticking. Cost: RAM + TLS copies.</text>
  <text class="s" x="8" y="404">A Lock gap currently lives inside each helper, not a separate sender.</text>

  <line x1="540" y1="16" x2="540" y2="408" stroke="#cbd5e1" stroke-width="1.5"/>

  <text class="h" x="560" y="22">One process, many games (not built)</text>
  <rect class="box" x="560" y="36" width="118" height="40" rx="5"/><text class="t" x="568" y="60">Kalshi</text>
  <rect class="box" x="686" y="36" width="118" height="40" rx="5"/><text class="t" x="694" y="60">Gemini</text>
  <rect class="box" x="812" y="36" width="118" height="40" rx="5"/><text class="t" x="820" y="60">Polymarket</text>
  <rect class="box" x="938" y="36" width="118" height="40" rx="5"/><text class="t" x="946" y="60">Novig</text>
  <path class="arr" d="M619,76 L780,110"/><path class="arr" d="M745,76 L800,110"/>
  <path class="arr" d="M871,76 L820,110"/><path class="arr" d="M997,76 L840,110"/>
  <rect class="py" x="620" y="112" width="420" height="78" rx="5"/>
  <text class="h" x="632" y="132">One asyncio Python — many games</text>
  <text class="s" x="632" y="150">one GIL · four shared platform sockets</text>
  <text class="s" x="632" y="166">fan-in to price memory / B sender</text>
  <text class="s" x="632" y="182">bug / OOM / reconnect hits every game</text>
  <path class="arr" d="M830,190 L830,220"/>
  <rect class="mem" x="700" y="222" width="260" height="52" rx="5"/>
  <text class="h" x="712" y="242">same price memory</text>
  <text class="s" x="712" y="260">B already event-wakes from here</text>
  <path class="arr" d="M830,274 L650,310"/><path class="arr" d="M830,274 L760,310"/>
  <path class="arr" d="M830,274 L870,310"/><path class="arr" d="M830,274 L980,310"/>
  <rect class="send" x="560" y="312" width="100" height="50" rx="5"/><text class="t" x="572" y="342">A separate</text>
  <rect class="send" x="670" y="312" width="90" height="50" rx="5"/><text class="t" x="686" y="342">B own</text>
  <rect class="send" x="770" y="312" width="90" height="50" rx="5"/><text class="t" x="786" y="342">C own</text>
  <rect class="send" x="870" y="312" width="90" height="50" rx="5"/><text class="t" x="886" y="342">D own</text>
  <rect class="send" x="970" y="312" width="90" height="50" rx="5"/><text class="t" x="986" y="342">E own</text>
  <text class="s" x="560" y="386">Recommended shape: merge pollers only. Keep senders (B/C/D/E) as their own Python.</text>
  <text class="s" x="560" y="404">Lift A out of the helper if we want A crash-isolated after the merge.</text>
</svg>"""


def _ram_bar(n: int, avg: float, measured_sum: float) -> str:
    """Bars: sibling censuses + this remeasure + one-process schematic (1 × avg)."""
    one = avg
    n83_extrap = round(LIVEONLY_N * avg, 1)
    n125_extrap = round(ARCH_N * avg, 1)
    shard10 = round(max(1, (n + 9) // 10) * avg, 1)
    plat4 = round(4 * avg, 1)
    # scale against afternoon peak (~11 GB)
    scale = max(measured_sum, ARCH_RAM, n125_extrap, 1.0)

    def w(mb: float) -> int:
        return max(6, int(round(mb / scale * 520)))

    def gb(mb: float) -> str:
        return f"{mb / 1024.0:.2f} GB"

    y = 56
    bars = [
        (f"Afternoon peak {ARCH_N} helpers (measured)", ARCH_RAM, "#1d4ed8", "measured"),
        (f"After live-only {LIVEONLY_N} (measured, freshly spawned)", LIVEONLY_RAM, "#60a5fa", "measured"),
        (f"This remeasure {n} helpers (measured sum)", measured_sum, "#1e3a8a", "measured"),
        (f"{ARCH_N} × this avg {avg} MB (extrap.)", n125_extrap, "#93c5fd", "extrapolated"),
        (f"{LIVEONLY_N} × this avg {avg} MB (extrap.)", n83_extrap, "#93c5fd", "extrapolated"),
        (f"One process (schematic: 1 × {avg} MB)", one, "#047857", "schematic"),
        (f"Four platform processes (schematic: 4 × {avg} MB)", plat4, "#0f766e", "schematic"),
        (f"Shards of ~10 games (schematic: {max(1,(n+9)//10)} × {avg} MB)", shard10, "#115e59", "schematic"),
    ]
    parts = [
        '<svg viewBox="0 0 980 340" role="img" aria-label="Helper RAM today versus one-process schematic">',
        """<style>
    .h { font: 700 13px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .t { font: 12px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .s { font: 11px Segoe UI, system-ui, sans-serif; fill:#475569; }
  </style>""",
        '<text class="h" x="8" y="20">Working-set RAM for --poll-one helpers</text>',
        f'<text class="s" x="8" y="38">This page\'s average is {esc(str(avg))} MB per helper. '
        "One-process and shard bars are that average × process count (not a measured merge).</text>",
    ]
    for label, mb, color, kind in bars:
        parts.append(f'<rect x="430" y="{y}" width="{w(mb)}" height="26" fill="{color}"/>')
        parts.append(f'<text class="t" x="8" y="{y + 18}">{esc(label)}</text>')
        parts.append(f'<text class="t" x="{440 + w(mb)}" y="{y + 18}">{esc(gb(mb))} · {esc(kind)}</text>')
        y += 34
    parts.append(
        '<text class="s" x="8" y="328">Does not include supervisor, catalog scan, or B/C/D/E. '
        "Freshly spawned helpers are smaller; they grow toward ~90 MB.</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    now = datetime.now(ET)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S ET")
    census = _census()
    status = _json(STATUS)
    n = int(census.get("poller_n") or 0)
    avg = float(census.get("poller_ram_avg") or 0)
    ram_sum = float(census.get("poller_ram_sum") or 0)
    named = {str(row.get("role") or ""): row for row in (census.get("named") or [])}
    parents = census.get("parents") or {}
    parent_note = ", ".join(
        f"pid {k} × {v}" for k, v in sorted(parents.items(), key=lambda kv: -kv[1])
    ) or "—"
    sup = named.get("supervisor") or {}
    b = named.get("B Tennis crossover") or {}
    one_mb = avg
    waste_mb = round(max(0.0, ram_sum - one_mb), 1)
    sockets_max = 4 * n
    shard_n = max(1, (n + 9) // 10) if n else 1
    named_rows = []
    for row in census.get("named") or []:
        named_rows.append([
            esc(row.get("role")),
            esc(row.get("pid")),
            esc(row.get("ram_mb")),
            "left running — this page only read the PID",
        ])
    named_rows.append([
        f"--poll-one helpers ({n})",
        "many",
        esc(ram_sum),
        esc(parent_note),
    ])

    rec = (
        "Merge pollers, keep senders separate. The waste is the interpreter: "
        f"this remeasure is {n} helpers × {avg} MB = {ram_sum} MB, almost all of it a second copy "
        "of Python and TLS rather than the match book. Strategy B already wakes from shared price "
        "memory and does not need a socket per game. Four shared platform sockets (one Kalshi, one "
        "Gemini, one Polymarket US, one Novig) is the shape that survives a busy tennis day even "
        f"after the live-only window cut 125 → 83 → {n}. Do not merge A and B into one process this "
        "week: they are different send math, B is already its own Python, and a combined sender crash "
        "would stop both. A Lock gap still lives inside each helper today, so a poller merge would "
        "put A in that same process unless we lift A out later. Research candidate only. Not gold. "
        "Not DailyRun. This job does not implement the merge."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Discuss: one process, many games 2026-10-28</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
h3 {{ font-size: 1.02rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 0.4rem; font-size: 1.05rem; }}
.tape {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.fig {{ margin: 0.6rem 0 1.2rem; border: 1px solid #e2e8f0; padding: 0.6rem; background: #fff; }}
.fig svg {{ width: 100%; height: auto; display: block; }}
.cap {{ color: #475569; font-size: 0.88rem; margin: 0.35rem 0 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Discuss: one process, many games</h1>
<p class="note">Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now_s)}.
Research only. Not gold. Not DailyRun. This page does not place a bet and does not merge processes.
Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a>.
Map: <a href="live_architecture_20261028.html">live_architecture_20261028.html</a>.
Live-only pollers: <a href="poller_live_only_20261028.html">poller_live_only_20261028.html</a>.
Up/down: <a href="job_status.html">job_status.html</a>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: write-up of architecture rec <strong>Discuss — One process, many games.</strong>
Pros/cons + recommendation. He quoted: “{esc(ASKED)}”</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="tape">
<h2>Recommendation (one paragraph)</h2>
<p>{esc(rec)}</p>
</div>

<div class="warn">
<p><strong>This job did not implement a merge.</strong> It did not start or stop Tennis crossover (B),
college football favorite (C), spreads (D), or tennis dog (E). It did not revert the HTTP venue pace
budget, leftover Good-till-cancelled (GTC), platform-truth, or live-only poller siblings.
PIDs below were read, not recycled.</p>
</div>

<h2>1. Measured census (this PC, this hour)</h2>
<p>Command line via <code>Get-CimInstance Win32_Process</code> so we can tell a
<code>--poll-one</code> helper from B. Working set also cross-checked with
<code>Get-Process</code> (same family as <code>tasklist</code>) for all
<code>python.exe</code>, which cannot see the command line and therefore mixes helpers with senders.</p>
{_table(
    [("When", "text"), ("python --poll-one", "num"), ("Supervisor pid", "text"),
     ("Helper RAM MB (sum)", "num"), ("MB / helper", "num"), ("Sockets", "text"),
     ("B pid", "text"), ("Kind", "text")],
    [
        [ARCH_WHEN, str(ARCH_N), str(ARCH_SUP), str(ARCH_RAM), str(ARCH_AVG),
         f"{ARCH_SOCKETS} expected flags (health files); 4×{ARCH_N}={4*ARCH_N} max",
         "74812", "Measured. live_architecture_20261028.html"],
        ["~15:00 ET request quote", "125", "38656", "~11000", "~80–88",
         "~198", "—", "Quoted on the architecture rec. Same afternoon peak."],
        [LIVEONLY_WHEN, str(LIVEONLY_N), str(LIVEONLY_SUP), str(LIVEONLY_RAM),
         str(round(LIVEONLY_RAM / LIVEONLY_N, 1)),
         f"4×{LIVEONLY_N}={4*LIVEONLY_N} max; Get-NetTCPConnection not elevated",
         "50716", "Measured after live-only. Twins for tomorrow killed. First loop after reload was 74."],
        [f"{esc(census.get('checked'))} ET (this page)",
         str(n),
         str(sup.get("pid") or status.get("supervisor_pid") or "—"),
         str(ram_sum),
         str(avg),
         f"4×{n}={sockets_max} max (not a packet capture)",
         str(b.get("pid") or "—"),
         "Measured. Read-only. Helpers aged since 15:31 so MB/helper is back near the afternoon average."],
    ],
)}
<p class="note">Click column headers to sort. Swipe sideways to see more columns.
Min helper this hour: {esc(census.get('poller_ram_min'))} MB. Max: {esc(census.get('poller_ram_max'))} MB.
Windows: OpenConsole {esc(census.get('OpenConsole'))}, conhost {esc(census.get('conhost'))},
python processes {esc(census.get('python_n'))}.
<code>Get-Process python</code> (tasklist-style, no command line):
{esc(census.get('tasklist_python_n'))} processes, {esc(census.get('tasklist_python_ram'))} MB working set
(helpers + supervisor + scan + senders + this writer).
Supervisor children: {esc(parent_note)}.
Status file live set: {esc(status.get('live_count'))} (updated {esc(status.get('updated_at') or '—')}).</p>
{_table(
    [("Role", "text"), ("PID", "text"), ("RAM MB", "num"), ("Note", "text")],
    named_rows,
)}
<p class="note">The 15:31 live-only helpers were freshly spawned (~{esc(str(round(LIVEONLY_RAM / LIVEONLY_N, 1)))} MB each).
This hour they sit at {esc(str(avg))} MB, in line with the afternoon 88.5 MB average at 125 helpers.
Do not treat the fresh-spawn number as the steady cost. Named senders + supervisor + scan this hour:
{esc(census.get('named_ram'))} MB — small next to {esc(str(ram_sum))} MB of helpers.</p>

<h2>2. Today, exactly</h2>
<p>The supervisor (<code>tools/live_game_pollers.py</code>, no <code>--poll-one</code>) looks about
every 60 seconds and starts <code>python -u tools/live_game_pollers.py --poll-one &lt;game-key&gt;</code>
for each tennis match in the live window. Each child is its own Python:</p>
<ul>
<li><strong>Own Global Interpreter Lock (GIL)</strong> — the lock inside one Python that only lets
one bytecode thread run at a time. One hundred helpers can use one hundred cores if they wanted to.
They wait on the network, so the GIL is not the limiter. RAM, TLS, file locks, and platform rate
limits are.</li>
<li><strong>Up to four websockets</strong> — one each to Kalshi, Gemini, Polymarket US, and Novig
(<code>live_quote_stream.run_until_done</code> gathers six asyncio tasks: four sockets plus two HTTP
fallbacks that stay quiet while their socket is up). There is no shared socket across games.
Polymarket already chunks 100 slugs on one socket — but each helper opens its own.</li>
<li><strong>Crash isolation</strong> — if one match's helper dies (bad ticker, OOM, reconnect storm),
the others keep ticking. That is the benefit of today's shape.</li>
<li><strong>A Lock gap rides inside the helper</strong> — <code>_maybe_lock_orders</code> calls
<code>live_lock_orders.execute_locks</code> on each compare. B/C/D/E are separate Pythons. A is not.</li>
</ul>
<p>Live-only already landed this afternoon: 125 helpers (~11 GB, ~198 sockets, twins for tomorrow)
down to 83 at 15:31 (first loop 74, supervisor {esc(str(LIVEONLY_SUP))}), and {esc(str(n))} this hour.
The leftover waste is still {esc(str(avg))} MB × N and up to four TLS sessions per game.</p>

<h2>3. Pictures</h2>
<div class="fig">
{_boxes_svg(n, avg)}
<p class="cap">Figure 1. Today (left) vs one asyncio process with four shared platform sockets (right).
Boxes are the real modules. The right side is not built. Timing is not to scale.</p>
</div>
<div class="fig">
{_ram_bar(n, avg, ram_sum)}
<p class="cap">Figure 2. RAM vs helper count. Blue bars with “measured” are real working set.
Green bars are this page's measured MB/helper × process count — schematic, because we did not merge.
Afternoon 125 × 88.5 MB = 11.06 GB was measured, not guessed.</p>
</div>

<h2>4. Cost of today's shape</h2>
{_table(
    [("Cost", "text"), ("What it is", "text"), ("Today (measured / from siblings)", "text"),
     ("If pollers merged (schematic)", "text")],
    [
        ["RAM",
         "Each helper is a full CPython + OpenSSL + imported modules. The match book is a small dict.",
         f"{n} × {avg} MB = {ram_sum} MB this hour. Afternoon peak {ARCH_RAM} MB at {ARCH_N} helpers.",
         f"About one helper ({one_mb} MB) plus game state. Interpreter waste this hour ≈ {waste_mb} MB."],
        ["TLS sessions / sockets",
         "Each helper handshakes its own encrypted websocket(s) to the platforms.",
         f"Afternoon health flags {ARCH_SOCKETS} expected sockets at {ARCH_N} helpers. Max 4×N = {sockets_max} this hour.",
         "Four platform sockets total (one Kalshi, one Gemini, one Polymarket, one Novig), fan-out in process."],
        ["price_memory.lock convoy",
         "Every compare used to take a global file lock and rewrite a 15 MB latest-price file. Sibling work split that to per-game files. This page does not revert it.",
         "N writers still exist. Per-game last files removed the 15 MB rewrite. N processes still mean N file opens.",
         "One writer process can append in memory and flush. Fewer lock waiters."],
        ["HTTP venue_pace convoy",
         "Ordinary web reads share one slot file per platform (Kalshi ~2/s, Gemini ~1/s, Novig 0.50s, Polymarket 0.06s). Websocket apply does not wait. Sibling HTTP budget caps in-flight callers. This page does not revert it.",
         f"A fallen-back minute at N={n} still joins that queue for seed/fallback. Send path has a reserved seat.",
         "One process can pace itself without N lock waiters. Sockets still skip the queue."],
        ["GIL",
         "One per process. Helpers are IO-bound.",
         f"{n} GILs. Parallel CPU is available and unused.",
         "One GIL. Fine if we stay on sockets. A CPU-heavy compare in the merged process stalls every game."],
    ],
)}

<h2>5. Alternative: one (or few) asyncio process(es), many games</h2>
<p>One Python runs <code>asyncio</code> for every live match. Four shared platform sockets subscribe
to every ticker/slug we care about (Polymarket already chunks 100 slugs — that pattern becomes the
only socket, not one per helper). Price changes fan in to the same price-memory files B already
reads. B's event-wake (first memory tick of dog Yes above 50¢) does not need a private socket.</p>
<p><strong>Blast radius:</strong> a bug, out-of-memory, or reconnect in that process takes down
<strong>all</strong> games at once. Today's isolation is gone. A Kalshi handshake failure today
kills one helper; tomorrow it could mute every tennis book until the process restarts.</p>
<p>That is why the middle paths exist. They are not gold. They are blast-radius knobs.</p>

<h2>6. Options (sortable)</h2>
{_table(
    [("Option", "text"), ("What changes", "text"), ("RAM vs today", "text"),
     ("Sockets", "text"), ("Crash isolation", "text"), ("Blast radius", "text"),
     ("Senders A/B/C/D/E", "text"), ("Verdict", "text")],
    [
        ["Keep today: one Python per game",
         "Supervisor keeps spawning --poll-one. Live-only window already cut N. No merge.",
         f"Measured {ram_sum} MB this hour. Still ~{avg} MB × N on a busy day.",
         f"Up to 4 per game ({sockets_max} max this hour).",
         "Best. One match dies alone.",
         "One game.",
         "A stays inside each helper. B/C/D/E stay separate. Do not merge A/B this week.",
         "HOLD as the live shape this week. Isolation is real. RAM/TLS still waste."],
        ["One asyncio process, many games",
         "Replace N helpers with one poller. Four shared platform sockets. Fan-in to price memory.",
         f"Schematic ~{one_mb} MB vs {ram_sum} MB. Interpreter waste ≈ {waste_mb} MB recovered.",
         "Four total.",
         "None among games. One crash stops the tape.",
         "All games.",
         "Must not swallow B/C/D/E. A currently lives in the helper — would ride along unless lifted out.",
         "LEAN later, not this week. Biggest RAM/TLS win. Hardest blast radius."],
        ["One process per platform",
         "Four Pythons: Kalshi / Gemini / Polymarket / Novig, each holding all games for that book.",
         f"Schematic ~{round(4*avg,1)} MB vs {ram_sum} MB.",
         "Four total (one each).",
         "A Kalshi reconnect does not take down Polymarket. A game still dies on all four if we do not fan-in carefully.",
         "One platform's full slate.",
         "Still separate from senders. Fan-in to price memory is extra wiring.",
         "HOLD. Isolates platforms, not matches. Four interpreters is still cheap vs N."],
        [f"One process per ~10 games (shards)",
         f"About {shard_n} poller Pythons this hour instead of {n}. Supervisor assigns keys.",
         f"Schematic ~{round(shard_n*avg,1)} MB vs {ram_sum} MB.",
         f"Up to 4 per shard ({4*shard_n} max this hour) unless sockets are shared inside the shard.",
         "A bad shard kills ~10 games, not 1 and not all.",
         "~10 games.",
         "Keep senders out of the shard. A-in-helper problem remains inside the shard.",
         "Middle path if a full merge scares us. Still research. Adds assignment complexity."],
        ["Merge pollers only; keep senders separate",
         "One (or few) poller process(es). B/C/D/E stay their own Python. Lift A out of the helper when we can, or accept A rides with the poller for a while.",
         f"Poller schematic ~{one_mb} MB + senders/supervisor already {census.get('named_ram')} MB.",
         "Four shared platform sockets. Senders keep using REST / memory, not extra sockets per game.",
         "A poller crash stops the tape for every game until respawn. A B crash still leaves C/D/E and the tape up.",
         "All games' prices; not all sends.",
         "Do not merge A and B into one process this week. B event-wake already needs shared memory, not a shared process with A.",
         "KEEP as the research candidate. This is the pick. Not implemented. Not gold. Not DailyRun."],
    ],
)}
<p class="note">Click column headers to sort. Swipe sideways to see more columns.
After the live-only window, N is smaller ({esc(str(n))} vs 125) but still worth merging
<strong>if sockets stay per-game</strong> — they do, today. 4×{esc(str(n))} is still
{esc(str(sockets_max))} handshakes for four platforms.</p>

<h2>7. Why not merge A and B this week</h2>
<ul>
<li>B is already one process that event-wakes from price memory. It does not hold the sockets.
Putting it in the poller process would couple a send bug to the tape, and a tape bug to the send.</li>
<li>A Lock gap is 1-contract hard-first IOC inside the helper. Different math, different failure mode.</li>
<li>Sibling GTC / venue-truth / HTTP budget jobs already reload senders on their own clock.
This discuss page must not start a second B or combine A+B as a “cleanup.”</li>
</ul>

<h2>8. What we would still need if we merge pollers later</h2>
<p>Not this job. Listed so the recommendation is not a slogan.</p>
<ul>
<li>A multiplexer: one Kalshi socket, one Gemini, one Polymarket, one Novig, subscribe/unsubscribe as
games enter and leave the live window.</li>
<li>Supervisor becomes “ensure the poller process is alive and holding the live key set,” not
“spawn N children.”</li>
<li>Health: one file or one row per game still, so a quiet book is visible without 80 helpers.</li>
<li>A Lock gap: either keep execute_locks in the merged poller (A shares the blast radius) or lift A
into its own sender that reads memory the way B does.</li>
<li>Replay tests that a poller crash respawns without a second B.</li>
</ul>

<p class="note">Sources: this PC's process census {esc(census.get('checked'))} ET,
<a href="live_architecture_20261028.html">live_architecture_20261028.html</a> (125 helpers, 11062.5 MB, 198 sockets, supervisor 38656),
<a href="poller_live_only_20261028.html">poller_live_only_20261028.html</a> (125→83, twins killed, supervisor 71868),
<code>tools/live_game_pollers.py</code>, <code>tools/live_quote_stream.py</code>,
<code>tools/price_memory.py</code>, <code>tools/venue_pace.py</code>.
No keys printed. No merge shipped.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)
    print(f"poller_n={n} ram_sum={ram_sum} ram_avg={avg} supervisor={sup.get('pid')} b={b.get('pid')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
