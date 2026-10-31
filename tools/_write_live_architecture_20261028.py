"""Architecture map of the live prediction-market stack. Does not place a bet."""
from __future__ import annotations

import html
import json
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
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
PAGE = STAMP / "live_architecture_20261028.html"
SVG = STAMP / "live_architecture_map_20261028.svg"
HEALTH_DIR = RAW / "live_health"
STATUS = RAW / "live_pollers_status.json"
esc = html.escape


def now_et() -> datetime:
    return datetime.now(ET)


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
    """Live Windows process census. Real numbers, not a schematic."""
    script = r"""
$ErrorActionPreference = 'Continue'
$openConsole = @(Get-Process -Name OpenConsole -ErrorAction SilentlyContinue).Count
$conhost = @(Get-Process -Name conhost -ErrorAction SilentlyContinue).Count
$python = @(Get-Process -Name python,pythonw -ErrorAction SilentlyContinue)
$cpuMap = @{}
$python | ForEach-Object { $cpuMap[$_.Id] = [math]::Round($_.CPU, 1) }
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
  $cpu = 0
  if ($cpuMap.ContainsKey([int]$p.ProcessId)) { $cpu = $cpuMap[[int]$p.ProcessId] }
  $out.rows += [ordered]@{
    pid = [int]$p.ProcessId
    ppid = [int]$p.ParentProcessId
    ram_mb = [math]::Round($p.WorkingSetSize/1MB, 1)
    cpu_sec = $cpu
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
            timeout=45,
            cwd=str(ROOT),
        )
        data = json.loads(raw)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"error": type(exc).__name__, "rows": [], "OpenConsole": None, "conhost": None, "python_n": None}
    rows = data.get("rows") or []
    pollers = []
    named = []
    other = []
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
        else:
            other.append(row)
    ram = [float(r.get("ram_mb") or 0) for r in pollers]
    parents = Counter(int(r.get("ppid") or 0) for r in pollers)
    return {
        "checked": data.get("checked") or now_et().strftime("%Y-%m-%d %H:%M:%S"),
        "OpenConsole": data.get("OpenConsole"),
        "conhost": data.get("conhost"),
        "python_n": data.get("python_n"),
        "pollers": pollers,
        "named": named,
        "other": other,
        "poller_n": len(pollers),
        "poller_ram_sum": round(sum(ram), 1),
        "poller_ram_avg": round(sum(ram) / len(ram), 1) if ram else 0,
        "poller_ram_min": round(min(ram), 1) if ram else 0,
        "poller_ram_max": round(max(ram), 1) if ram else 0,
        "poller_parents": dict(parents),
        "poller_cpu_sum": round(sum(float(r.get("cpu_sec") or 0) for r in pollers), 1),
    }


def _health_stats(live_keys: set[str] | None = None) -> dict:
    files = list(HEALTH_DIR.glob("*.json")) if HEALTH_DIR.is_dir() else []
    last_ms: list[float] = []
    lifetime_avg: list[float] = []
    expected = Counter()
    transports = Counter()
    sports = Counter()
    minute_checks = 0
    minute_msgs = 0
    minute_updates = 0
    max_this_minute = 0.0
    n = 0
    skipped_stale = 0
    live_keys = live_keys or set()
    for path in files:
        key = path.stem
        if live_keys and key not in live_keys:
            skipped_stale += 1
            continue
        row = _json(path)
        if not row:
            skipped_stale += 1
            continue
        n += 1
        sports[str(row.get("sport") or "")] += 1
        exp = row.get("expected") if isinstance(row.get("expected"), dict) else {}
        for plat in ("kalshi", "gemini", "polymarket", "novig"):
            if exp.get(plat):
                expected[plat] += 1
        feed = str(row.get("transport") or "")
        if feed:
            transports[feed.split(":")[0].strip() or feed] += 1
        try:
            ms = float(row.get("last_compare_ms"))
            last_ms.append(ms)
        except (TypeError, ValueError):
            pass
        try:
            checks = float(row.get("checks") or 0)
            total = float(row.get("compare_ms_sum") or 0)
            if checks > 0:
                lifetime_avg.append(total / checks)
        except (TypeError, ValueError):
            pass
        try:
            minute_checks += int(row.get("minute_checks") or 0)
            mm = row.get("minute_messages") if isinstance(row.get("minute_messages"), dict) else {}
            mu = row.get("minute_updates") if isinstance(row.get("minute_updates"), dict) else {}
            minute_msgs += sum(int(v or 0) for v in mm.values())
            minute_updates += sum(int(v or 0) for v in mu.values())
            mx = float(row.get("minute_compare_ms_max") or 0)
            if mx > max_this_minute:
                max_this_minute = mx
        except (TypeError, ValueError):
            pass
    last_ms.sort()

    def pct(vals: list[float], p: float) -> float | None:
        if not vals:
            return None
        if len(vals) == 1:
            return round(vals[0], 1)
        idx = min(len(vals) - 1, max(0, int(round((p / 100.0) * (len(vals) - 1)))))
        return round(vals[idx], 1)

    return {
        "files": n,
        "sports": dict(sports),
        "expected": dict(expected),
        "expected_sum": int(sum(expected.values())),
        "transports": dict(transports),
        "last_ms_n": len(last_ms),
        "last_ms_p50": pct(last_ms, 50),
        "last_ms_p90": pct(last_ms, 90),
        "last_ms_max": round(max(last_ms), 1) if last_ms else None,
        "last_ms_mean": round(statistics.fmean(last_ms), 1) if last_ms else None,
        "lifetime_mean_ms": round(statistics.fmean(lifetime_avg), 1) if lifetime_avg else None,
        "minute_checks": minute_checks,
        "minute_msgs": minute_msgs,
        "minute_updates": minute_updates,
        "minute_max_ms": round(max_this_minute, 1),
        "skipped_stale": skipped_stale,
        "files_on_disk": len(files),
    }


def _status_sports() -> dict:
    snap = _json(STATUS)
    games = snap.get("games") if isinstance(snap.get("games"), list) else []
    sports = Counter(str(row.get("sport") or "") for row in games if isinstance(row, dict))
    live_until_null = sum(1 for row in games if isinstance(row, dict) and row.get("live_until") in (None, "", "null"))
    future = 0
    now = now_et()
    for row in games:
        if not isinstance(row, dict):
            continue
        start = str(row.get("start") or "")
        try:
            when = datetime.fromisoformat(start)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=ET)
        if when > now:
            future += 1
    return {
        "updated_at": snap.get("updated_at") or "",
        "live_count": int(snap.get("live_count") or len(games)),
        "supervisor_pid": snap.get("supervisor_pid"),
        "sports": dict(sports),
        "live_until_null": live_until_null,
        "future_start": future,
        "games": games,
    }


def _fmt_ms(val) -> str:
    if val is None:
        return "—"
    return f"{val:,.1f}"


def _architecture_svg() -> str:
    """Schematic grounded in code. Not a live packet capture."""
    return """<svg viewBox="0 0 1100 640" role="img" aria-label="Four platforms to pollers to memory to senders to ledger to dashboard">
  <style>
    .box { fill:#f8fafc; stroke:#334155; stroke-width:1.4; }
    .box2 { fill:#eef2ff; stroke:#3730a3; stroke-width:1.4; }
    .box3 { fill:#ecfdf5; stroke:#047857; stroke-width:1.4; }
    .box4 { fill:#fff7ed; stroke:#c2410c; stroke-width:1.4; }
    .t { font: 12px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .h { font: 700 13px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .s { font: 11px Segoe UI, system-ui, sans-serif; fill:#475569; }
    .arr { stroke:#334155; stroke-width:1.6; fill:none; marker-end:url(#arrow); }
  </style>
  <defs>
    <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#334155"/>
    </marker>
  </defs>
  <rect class="box" x="20" y="40" width="200" height="56" rx="6"/>
  <text class="h" x="30" y="62">Kalshi</text>
  <text class="s" x="30" y="80">wss://external-api-ws…</text>
  <rect class="box" x="20" y="110" width="200" height="56" rx="6"/>
  <text class="h" x="30" y="132">Gemini</text>
  <text class="s" x="30" y="150">wss://ws.gemini.com</text>
  <rect class="box" x="20" y="180" width="200" height="56" rx="6"/>
  <text class="h" x="30" y="202">Polymarket US</text>
  <text class="s" x="30" y="220">wss://api.polymarket.us</text>
  <rect class="box" x="20" y="250" width="200" height="56" rx="6"/>
  <text class="h" x="30" y="272">Novig</text>
  <text class="s" x="30" y="290">wss://api.novig.com</text>
  <text class="s" x="30" y="330">Four platforms. Live quotes.</text>

  <path class="arr" d="M220,68 L300,200"/>
  <path class="arr" d="M220,138 L300,210"/>
  <path class="arr" d="M220,208 L300,220"/>
  <path class="arr" d="M220,278 L300,230"/>

  <rect class="box2" x="300" y="160" width="230" height="120" rx="6"/>
  <text class="h" x="312" y="184">One Python per game</text>
  <text class="s" x="312" y="204">live_game_pollers --poll-one</text>
  <text class="s" x="312" y="222">asyncio sockets + 50ms compare</text>
  <text class="s" x="312" y="240">HTTP fallback every 5s if down</text>
  <text class="s" x="312" y="258">HTTP seed once at start</text>

  <path class="arr" d="M530,220 L610,220"/>

  <rect class="box3" x="610" y="150" width="210" height="140" rx="6"/>
  <text class="h" x="622" y="174">Price memory</text>
  <text class="s" x="622" y="194">jsonl shard per sport/day</text>
  <text class="s" x="622" y="212">price_last.json (latest)</text>
  <text class="s" x="622" y="230">file lock across processes</text>
  <text class="s" x="622" y="248">not a database</text>
  <text class="s" x="622" y="266">B reads this, not sockets</text>

  <path class="arr" d="M715,290 L715,340"/>

  <rect class="box4" x="40" y="360" width="150" height="88" rx="6"/>
  <text class="h" x="52" y="384">A Lock gap</text>
  <text class="s" x="52" y="402">in each poller</text>
  <text class="s" x="52" y="418">hard-first IOC</text>
  <text class="s" x="52" y="434">1 contract</text>
  <rect class="box4" x="210" y="360" width="150" height="88" rx="6"/>
  <text class="h" x="222" y="384">B Tennis cross</text>
  <text class="s" x="222" y="402">one process</text>
  <text class="s" x="222" y="418">memory wake + REST</text>
  <text class="s" x="222" y="434">IOC / FOK</text>
  <rect class="box4" x="380" y="360" width="150" height="88" rx="6"/>
  <text class="h" x="392" y="384">C CFB favorite</text>
  <text class="s" x="392" y="402">one process</text>
  <text class="s" x="392" y="418">game-start Yes</text>
  <text class="s" x="392" y="434">IOC</text>
  <rect class="box4" x="550" y="360" width="150" height="88" rx="6"/>
  <text class="h" x="562" y="384">D Spreads</text>
  <text class="s" x="562" y="402">one process</text>
  <text class="s" x="562" y="418">skip pro football</text>
  <text class="s" x="562" y="434">IOC</text>
  <rect class="box4" x="720" y="360" width="150" height="88" rx="6"/>
  <text class="h" x="732" y="384">E Tennis dog</text>
  <text class="s" x="732" y="402">one process</text>
  <text class="s" x="732" y="418">game-start dog Yes</text>
  <text class="s" x="732" y="434">IOC / FOK</text>
  <rect class="box4" x="890" y="360" width="190" height="88" rx="6"/>
  <text class="h" x="902" y="384">Confirm</text>
  <text class="s" x="902" y="402">platform fill-history</text>
  <text class="s" x="902" y="418">not our diary</text>
  <text class="s" x="902" y="434">then ledger</text>

  <path class="arr" d="M115,448 L115,500"/>
  <path class="arr" d="M285,448 L285,500"/>
  <path class="arr" d="M455,448 L455,500"/>
  <path class="arr" d="M625,448 L625,500"/>
  <path class="arr" d="M795,448 L795,500"/>
  <path class="arr" d="M985,448 L985,500"/>

  <rect class="box" x="200" y="500" width="280" height="70" rx="6"/>
  <text class="h" x="212" y="524">orders.jsonl / order_io.jsonl</text>
  <text class="s" x="212" y="542">local raw, not Drive</text>
  <text class="s" x="212" y="558">orders.html rewrite after both legs</text>
  <rect class="box" x="520" y="500" width="280" height="70" rx="6"/>
  <text class="h" x="532" y="524">dashboard.html</text>
  <text class="s" x="532" y="542">kitchen scoreboard</text>
  <text class="s" x="532" y="558">job_status Positions overlay</text>
  <path class="arr" d="M480,535 L520,535"/>
</svg>"""


def _process_chart(poller_n: int, ram_avg: float, ram_sum: float) -> str:
    """Bars: Oct 21 measured + today measured. 50/100 RAM is extrapolated from today's avg."""
    ram50 = round(50 * ram_avg / 1024.0, 2) if ram_avg else 0
    ram100 = round(100 * ram_avg / 1024.0, 2) if ram_avg else 0
    ram_now = round(ram_sum / 1024.0, 2)
    # scale: max 12 GB
    def w(gb: float) -> int:
        return max(4, int(round(gb / 12.0 * 420)))

    return f"""<svg viewBox="0 0 720 280" role="img" aria-label="Poller RAM at 50, 100, and live count">
  <style>
    .t {{ font: 12px Segoe UI, system-ui, sans-serif; fill:#0f172a; }}
    .s {{ font: 11px Segoe UI, system-ui, sans-serif; fill:#475569; }}
    .h {{ font: 700 13px Segoe UI, system-ui, sans-serif; fill:#0f172a; }}
  </style>
  <text class="h" x="8" y="22">Working-set RAM for --poll-one helpers only</text>
  <text class="s" x="8" y="40">Today's average {esc(str(ram_avg))} MB per helper. 50 and 100 are that average × N. Live bar is the measured sum.</text>
  <rect x="180" y="70" width="{w(ram50)}" height="36" fill="#93c5fd"/>
  <text class="t" x="8" y="94">50 helpers (extrap.)</text>
  <text class="t" x="{190 + w(ram50)}" y="94">{ram50} GB</text>
  <rect x="180" y="120" width="{w(ram100)}" height="36" fill="#60a5fa"/>
  <text class="t" x="8" y="144">100 helpers (extrap.)</text>
  <text class="t" x="{190 + w(ram100)}" y="144">{ram100} GB</text>
  <rect x="180" y="170" width="{w(ram_now)}" height="36" fill="#1d4ed8"/>
  <text class="t" x="8" y="194">Live {esc(str(poller_n))} (measured)</text>
  <text class="t" x="{190 + w(ram_now)}" y="194">{ram_now} GB</text>
  <text class="s" x="8" y="240">Does not include supervisor, catalog scan, B/C/D/E senders, or Windows console hosts.</text>
  <text class="s" x="8" y="258">Senders and the supervisor add roughly another 1.3 GB in today's census.</text>
</svg>"""


def _shimizu_svg() -> str:
    return """<svg viewBox="0 0 980 260" role="img" aria-label="Shimizu memory tape versus sender long loop">
  <style>
    .t { font: 12px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .h { font: 700 13px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .s { font: 11px Segoe UI, system-ui, sans-serif; fill:#475569; }
  </style>
  <text class="h" x="8" y="22">Two clocks on one match (this week's tape, not a guess)</text>
  <rect x="8" y="40" width="964" height="70" fill="#ecfdf5" stroke="#047857"/>
  <text class="h" x="20" y="62">Memory poller</text>
  <text class="s" x="20" y="80">00:23:57.410 Shimizu Yes 52¢  ·  00:24:03 53¢  ·  00:26:20 63¢  — wrote every change</text>
  <text class="s" x="20" y="96">Websocket + 5s HTTP fallback. Cadence is seconds.</text>
  <rect x="8" y="124" width="964" height="90" fill="#fef2f2" stroke="#991b1b"/>
  <text class="h" x="20" y="146">Sender (B) before the patch</text>
  <text class="s" x="20" y="164">maybe_cross ran at the start of a tick, then try_t0 REST-walked the tennis list for ~3 minutes.</text>
  <text class="s" x="20" y="180">00:23:46 other T0 skip · 00:24:00 · 00:24:19 · 00:26:20 Wolf skip · 00:26:59.999 first 50-cross REST send</text>
  <text class="s" x="20" y="196">Fill 00:27:00.289 at 60¢+2¢. 3m 3s after the first legal 52¢ print. Book had already walked to 63¢.</text>
  <line x1="210" y1="40" x2="210" y2="214" stroke="#047857" stroke-dasharray="3 3"/>
  <text class="s" x="216" y="250">first &gt;50¢ memory tick</text>
</svg>"""


def _timeline_svg() -> str:
    return """<svg viewBox="0 0 1000 220" role="img" aria-label="Idle poll versus game start versus 50-cross versus send versus confirm">
  <style>
    .t { font: 12px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .h { font: 700 13px Segoe UI, system-ui, sans-serif; fill:#0f172a; }
    .s { font: 11px Segoe UI, system-ui, sans-serif; fill:#475569; }
  </style>
  <text class="h" x="8" y="22">When we call the platforms (schematic of the intended path)</text>
  <rect x="20" y="50" width="150" height="70" rx="6" fill="#f8fafc" stroke="#334155"/>
  <text class="t" x="32" y="78">Idle poll</text>
  <text class="s" x="32" y="96">sockets only</text>
  <text class="s" x="32" y="110">no REST unless down</text>
  <rect x="200" y="50" width="160" height="70" rx="6" fill="#eef2ff" stroke="#3730a3"/>
  <text class="t" x="212" y="78">Game start</text>
  <text class="s" x="212" y="96">B/C/D/E REST both</text>
  <text class="s" x="212" y="110">books, then place a bet</text>
  <rect x="390" y="50" width="170" height="70" rx="6" fill="#ecfdf5" stroke="#047857"/>
  <text class="t" x="402" y="78">50-cross (B)</text>
  <text class="s" x="402" y="96">memory tick &gt;50¢</text>
  <text class="s" x="402" y="110">then REST confirm</text>
  <rect x="590" y="50" width="170" height="70" rx="6" fill="#fff7ed" stroke="#c2410c"/>
  <text class="t" x="602" y="78">Place a bet</text>
  <text class="s" x="602" y="96">IOC / FOK, 1 contract</text>
  <text class="s" x="602" y="110">A hard-first sequential</text>
  <rect x="790" y="50" width="180" height="70" rx="6" fill="#f8fafc" stroke="#334155"/>
  <text class="t" x="802" y="78">Confirm</text>
  <text class="s" x="802" y="96">fill-history GET</text>
  <text class="s" x="802" y="110">ledger + dashboard</text>
  <text class="s" x="20" y="150">Shared HTTP pace files apply to ordinary web reads, not to a websocket book update.</text>
  <text class="s" x="20" y="168">Kalshi ~2 reads/s across all processes. Gemini ~1/s. Polymarket public 0.06s slot. Novig 0.50s slot.</text>
  <text class="s" x="20" y="186">A 100-helper pile-up waiting on HTTP will queue behind that one lock. Sockets do not.</text>
  <text class="s" x="20" y="204">Catalog scan also uses the same pace. B T0 hunt used to as well; 50-cross confirm is now unpaced.</text>
</svg>"""


def main() -> int:
    census = _census()
    status = _status_sports()
    live_keys = {
        str(row.get("key") or "")
        for row in (status.get("games") or [])
        if isinstance(row, dict) and row.get("key")
    }
    health = _health_stats(live_keys)
    checked = now_et().strftime("%Y-%m-%d %H:%M:%S ET")
    poller_n = int(census.get("poller_n") or 0)
    ram_avg = float(census.get("poller_ram_avg") or 0)
    ram_sum = float(census.get("poller_ram_sum") or 0)
    named = census.get("named") or []
    other = census.get("other") or []
    parents = census.get("poller_parents") or {}
    parent_note = ", ".join(f"pid {k} × {v}" for k, v in sorted(parents.items(), key=lambda kv: -kv[1])) or "—"

    job_rows = []
    for row in named:
        job_rows.append([
            esc(str(row.get("role") or "")),
            esc(str(row.get("pid") or "")),
            esc(str(row.get("ppid") or "")),
            esc(str(row.get("ram_mb") or "")),
            esc(str(row.get("cpu_sec") or "")),
            esc((str(row.get("cmd") or "")[:90] + ("…" if len(str(row.get("cmd") or "")) > 90 else ""))),
        ])
    job_rows.append([
        f"--poll-one helpers ({poller_n})",
        "many",
        esc(parent_note),
        esc(str(census.get("poller_ram_sum"))),
        esc(str(census.get("poller_cpu_sum"))),
        "python -u tools/live_game_pollers.py --poll-one &lt;game-key&gt;",
    ])
    for row in other:
        cmd = str(row.get("cmd") or "(no cmdline)")
        if "stockresearch" not in cmd.lower() and "live_" not in cmd.lower():
            continue
        job_rows.append([
            "other python (this repo)",
            esc(str(row.get("pid") or "")),
            esc(str(row.get("ppid") or "")),
            esc(str(row.get("ram_mb") or "")),
            esc(str(row.get("cpu_sec") or "")),
            esc(cmd[:90] + ("…" if len(cmd) > 90 else "")),
        ])

    sport_rows = []
    for sport, n in sorted((status.get("sports") or {}).items(), key=lambda kv: (-kv[1], kv[0])):
        sport_rows.append([esc(sport or "(blank)"), esc(str(n))])
    if not sport_rows:
        sport_rows.append(["(status file empty)", "0"])

    ws_rows = [
        [
            "Kalshi",
            "<code>tools/live_quote_stream.py</code>",
            "<code>wss://external-api-ws.kalshi.com/trade-api/ws/v2</code>",
            "ticker + orderbook_delta per market ticker",
            "The game helper. In-memory contract dict. Compare thread on change.",
            "2s, doubles to 30s",
            "Whole-game HTTP loop every 5s only if the stream task cannot start",
            "secrets/kalshi_key_id.txt + secrets/kalshi_private_key.pem (signed handshake)",
        ],
        [
            "Gemini",
            "<code>tools/live_quote_stream.py</code>",
            "<code>wss://ws.gemini.com</code>",
            "<code>{symbol}@bookTicker</code>",
            "Same helper. Public book; no key on the socket.",
            "2s, doubles to 30s",
            "Same 5s HTTP loop if streams fail",
            "none on the socket. REST orders use secrets/gemini_api_key.txt + secrets/gemini_api_secret.txt",
        ],
        [
            "Polymarket US",
            "<code>tools/polymarket_us_live.py</code> + live_quote_stream",
            "<code>wss://api.polymarket.us/v1/ws/markets</code>",
            "markets subscribe, camelCase, chunks of 100 slugs. Heartbeat every 10s.",
            "Same helper. International CLOB socket is not used.",
            "2s–30s. If the key file is missing, wait 15s and retry; Kalshi/Gemini keep running.",
            "Dedicated HTTP task every 5s <em>only while the socket is down</em>",
            "secrets/polymarket_api_key.txt + secrets/polymarket_api_secret.txt",
        ],
        [
            "Novig",
            "<code>tools/novig_live.py</code> + live_quote_stream",
            "<code>wss://api.novig.com/v3/ws</code>",
            "subscribe markets {id: book}. Snapshot again if a book gap flag is set.",
            "Same helper. Idle if the key files are missing (HTTP still quotes).",
            "2s–30s",
            "Dedicated HTTP task every 5s while the socket is down",
            "secrets/novig_api_key.txt (or novig_key_id.txt) + secrets/novig_api_secret.txt (or novig_private_key.pem)",
        ],
    ]

    store_rows = [
        ["price memory tape", "raw/price_memory/YYYY-MM-DD/{sport}.jsonl", "file (append)", "each game helper on a change", "B (and lookback pages)", "Not sqlite. SAME_QUOTE_SEC=20 skips an unchanged rewrite."],
        ["latest prices", "raw/price_last.json", "file (rewrite under lock)", "each helper via price_memory.lock", "B memory pump, leftover watch", "Global file lock across 100+ writers."],
        ["sports queue", "raw/sports_queue.json", "file", "catalog scan", "C/D slate (not tennis E)", "Overnight matched list. Tennis is not in this file."],
        ["tennis list", "polymarket tennis cache + Novig ATP/WTA", "memory + json cache", "supervisor tennis_rows()", "B and E", "Twins stay listed while the supervisor is up."],
        ["opportunities.jsonl", "raw/opportunities.jsonl", "file (append)", "catalog scan / compare", "pages, not senders", "Snapshot tape. Live A uses in-memory compare."],
        ["considerations.json", "raw/considerations.json", "file (rolling)", "A skip/deny logger", "opportunities.html", "Last 500 rows."],
        ["order ledger", "raw/orders.jsonl + order_io.jsonl", "file (append)", "every sender after HTTP", "orders.html, dashboard, Positions", "HTTP tape. Confirm is a later GET."],
        ["dashboard cache", "raw/dashboard_cache.json", "file", "write_dashboard.py", "dashboard.html", "Kitchen scoreboard. Not a send path."],
        ["job_status", "drive/…/job_status.html + raw pid/status json", "HTML rewrite ~60s", "supervisor thread", "humans / phone", "Not a process manager. It reports."],
        ["B watch", "raw/strategy_b_watch.json", "file", "B process", "job_status, E skip-if-open", "Own state. Does not read orders_stopped.json."],
        ["C/D/E watch", "raw/{cfb_favorite,spread_t0,tennis_t0_dog}_watch.json", "file", "each sender", "job_status", "Directional Yes state."],
        ["systems.json", "raw/systems.json", "file", "prediction_job_control / bats", "all senders each tick", "On/off, stake, max open, A cap 0.99."],
        ["live poller status", "raw/live_pollers_status.json", "file", "supervisor publish()", "job_status PID table", "Intended vs actual --poll-one set."],
        ["HTTP pace slots", "raw/pace_{platform}.next + .lock", "file lock", "every ordinary HTTP read", "all processes", "Websocket apply does not wait."],
        ["sqlite", "none on the live path", "—", "—", "—", "Looked. Live tape is jsonl + json. sqlite3 is not wired."],
    ]

    rec_rows = [
        ["1", "Do now", "Stop forever-on tennis twins",
         "tennis_collect_now returns True for every Kalshi+Polymarket twin while the supervisor is up. Helpers stay even when listed start is tomorrow. Unmatched books already wait until 5 minutes before start. Apply that to twins. live_until is null on tennis rows, so the child never self-stops."],
        ["2", "Do now", "Keep B event-wake; never REST-hunt the world then maybe send",
         "This week's patch (pid 74812): first memory tick of T0-dog Yes &gt; 50¢ wakes an unpaced REST confirm, then IOC. tick_cross_only every 50ms while a 50-cross is armed. Do not regress to maybe_cross-once-per-long-tick. C/D/E still walk their slates each tick — they do not have a 50-cross, but they can still stall on REST."],
        ["3", "Do now", "Budget the shared HTTP pace",
         "venue_pace is one global queue per platform (Kalshi ~2/s, Gemini ~1/s, Novig 0.50s, Polymarket 0.06s). Seeds, catalog, leftover watch, and C/D/E all wait on those files. At 100+ helpers a fallen-back HTTP minute becomes a convoy. Measure skipped ticks / lock wait. Cap in-flight HTTP."],
        ["4", "Do now", "Replay tests for the long-loop miss",
         "Already have a Shimizu replay: 52¢ sends without a 180s sleep; 49¢ does not REST; no double-send. Keep that as a gate. Add: T0 hunt must not run before 50-cross watches; lifetime compare_ms must not sit in tens of seconds because of price_memory.lock."],
        ["5", "Discuss", "One process, many games",
         "Today: one Python per game (~measured MB each, own GIL, own 4 sockets). Crash isolation is the benefit. RAM and TLS sessions are the cost. One asyncio process with many games would cut working set and share four platform sockets. Harder blast radius."],
        ["6", "Discuss", "Share one websocket per platform",
         "Poly already chunks 100 slugs on one socket — but each helper opens its own. Kalshi/Gemini/Novig subscribe per ticker too. One connection per platform, fan-out in process, is the efficient shape. Needs a multiplexer the senders can trust."],
        ["7", "Discuss", "Treat job_status as a supervisor, not a poster",
         "The page rewrites about once a minute. It does not cap N, recycle quiet twins, or restart a dead sender without a bat. A cap (for example 40 in-match helpers) plus recycle of twins whose listed start is hours away would stop 50→100+ by itself."],
        ["8", "Discuss", "GTC dip rest (do not wire here)",
         "After a legal 50-cross fill, B IOC-buys the original favorite at $1 − cross_fill − 0.25. Hsu this game: fill 60¢ → target 15¢. Hsu's live Yes stayed at or above 38¢. IOC at 15¢ will miss. A rest-on-the-book GTC at that target would wait. Not live. Leftover GTC is a different ask — still not this job."],
        ["9", "Later", "One writer for price_last.json",
         "Every compare takes price_memory.lock and may rewrite the whole latest-price file. At a thousand updates a minute that is a disk convoy on top of the HTTP pace. A dedicated writer process, or sqlite later, is a later cut."],
        ["10", "Later", "Rate-limit budget on the health page",
         "stream_health already counts messages, updates, checks, quiet. Add slots used vs cap, lock wait, skipped compares. Then 100+ is a number we can see, not a surprise."],
    ]

    map_svg = _architecture_svg()
    SVG.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" ' + map_svg.split("<svg ", 1)[1],
        encoding="utf-8",
    )

    asked = (
        "The sender only checked the book once per long loop. "
        "Write a thorough architecture document as HTML on how the live prediction-market stack "
        "is actually wired: processes, websockets, API calls, order placement, and what happens "
        "as process count grows from 50 to 100+. The entire architecture, then recommendations "
        "to tighten, perform better, be more efficient. Graphs and figures. HTML is fine."
    )
    plain = (
        "The kitchen scoreboard (dashboard.html) tells you what we hold and whether we are up. "
        "This page is the map of how that happens. Four betting platforms push live prices. "
        "A small Python helper per live game keeps those prices. A handful of senders decide "
        "when to place a bet. As the helper count goes from 50 to 100+, the sockets stay fast; "
        "the slow part is ordinary web reads and a shared file lock, plus RAM. "
        "The 3-minute Shimizu miss was the sender ignoring the fast tape while it walked every "
        "other tennis match. That hole is patched for the 50-cross. The helper pile-up is not."
    )

    exp_sum = health.get("expected_sum") or 0
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Live prediction-market architecture 2026-10-28</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
h3 {{ font-size: 1.02rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 0.4rem; font-size: 1.05rem; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.tape {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.fig {{ margin: 0.6rem 0 1.2rem; border: 1px solid #e2e8f0; padding: 0.6rem; background: #fff; }}
.fig svg {{ width: 100%; height: auto; display: block; }}
.cap {{ color: #475569; font-size: 0.88rem; margin: 0.35rem 0 0; }}
code {{ font-size: 0.92em; }}
ol.recs li {{ margin: 0.45rem 0; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>How the live prediction-market stack is wired</h1>
<p class="note">Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(checked)}.
This page does not place a bet. It does not change send math. Companion map:
<a href="live_architecture_map_20261028.svg">live_architecture_map_20261028.svg</a>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul asked: “{esc(asked)}”</p>
<h2>In plain English</h2>
<p>{esc(plain)}</p>
<p class="note">Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a>.
This page is the wiring. Pulse check: <a href="stream_health.html">stream_health.html</a>.
Up/down: <a href="job_status.html">job_status.html</a>.
Shimizu 3-minute miss: <a href="b_crossover_lag_shimizu_20261028.html">b_crossover_lag_shimizu_20261028.html</a>.</p>
</div>

<div class="tape">
<h2>This week's tape (not eternal)</h2>
<ul>
<li>B 50-cross now wakes on the first memory tick of dog Yes strictly above 50¢, then REST-confirms both Yes books unpaced, then places the extra bet. Reload pid <code>74812</code>. Before that, B ignored memory and REST-hunted game-start tickets while <code>maybe_cross</code> waited ~3 minutes.</li>
<li>Hsu dip: after a legal extra fill, B may IOC-buy the original favorite at <code>$1 − cross_fill − 0.25</code> (15¢ on the 60¢ fill this game). GTC is not wired. Hsu's live Yes stayed at or above 38¢, so a 15¢ IOC does not rest on the book.</li>
<li>Polymarket fill/settle bugs were Polymarket-only. The platform-truth fix landed 2026-10-28
(<a href="venue_truth_fix_20261028.html">venue_truth_fix_20261028.html</a>).</li>
</ul>
</div>

<h2>1. One-picture map</h2>
<p>Four platforms push books. Each live game has its own helper that holds sockets in memory.
Price changes land in a shared tape. Five senders place a bet. Confirm is a later read of
the platform's own fill list. The kitchen scoreboard reads that ledger. Schematic, drawn from
the code paths below — not a packet capture.</p>
<div class="fig">
{map_svg}
<p class="cap">Figure 1. Schematic from code. Boxes are real modules. Arrow timing is not to scale.</p>
</div>

<h2>2. Processes</h2>
<p>Census taken {esc(str(census.get('checked') or checked))} on this PC with
<code>Get-CimInstance Win32_Process</code> plus <code>Get-Process</code> CPU seconds.
Windows Terminal tabs, console hosts, and Python are counted separately because
21 Oct 2026 they were not the same number.</p>
{_table(
    [("Role", "text"), ("PID", "num"), ("Parent PID", "text"), ("RAM MB", "num"), ("CPU sec (life)", "num"), ("Command", "text")],
    job_rows,
)}
<p class="note">Windows: OpenConsole {esc(str(census.get('OpenConsole')))} (Terminal tabs),
conhost {esc(str(census.get('conhost')))}, python {esc(str(census.get('python_n')))}.
<code>--poll-one</code> helpers: {esc(str(poller_n))}, all children of {esc(parent_note)}.
Working set for those helpers: sum {esc(str(census.get('poller_ram_sum')))} MB,
average {esc(str(census.get('poller_ram_avg')))} MB, min {esc(str(census.get('poller_ram_min')))} MB,
max {esc(str(census.get('poller_ram_max')))} MB. CPU seconds are lifetime, not percent.</p>

<h3>What the supervisor thinks is live</h3>
<p><code>live_pollers_status.json</code> updated {esc(str(status.get('updated_at') or '—'))}.
Claimed live games: {esc(str(status.get('live_count')))}.
Tennis rows with <code>live_until</code> empty: {esc(str(status.get('live_until_null')))}.
Listed start still in the future: {esc(str(status.get('future_start')))}.</p>
{_table([("Sport", "text"), ("Helpers in status file", "num")], sport_rows)}

<h3>Typical counts, and what happens at 50 vs 100+</h3>
{_table(
    [("When", "text"), ("OpenConsole tabs", "num"), ("conhost", "num"), ("python.exe", "num"), ("python --poll-one", "num"), ("Source", "text")],
    [
        ["21 Oct 2026 ~11:45 ET (first count)", "227", "234", "96", "93", "Measured. poller_windows_20261021.html"],
        ["21 Oct 2026 ~11:48 ET (leftover 11:30 tabs already gone)", "113", "120", "83", "80", "Measured. Same page."],
        ["21 Oct 2026, after CREATE_NO_WINDOW", "—", "—", "—", "one per live game, hidden", "Code change. New helpers do not add a tab."],
        [f"Now {esc(checked)}", esc(str(census.get('OpenConsole'))), esc(str(census.get('conhost'))), esc(str(census.get('python_n'))), esc(str(poller_n)), "This census. Real."],
    ],
)}
<p><strong>Why the count explodes.</strong> The supervisor looks about every 60 seconds
(<code>SUPERVISOR_SLEEP=60</code>) and starts <code>python -u live_game_pollers.py --poll-one KEY</code>
for each row in <code>live_games()</code>. Football helpers die when listed start plus a typical
length has passed (pro football 3.5 hours, college 4). Tennis is different: a Kalshi+Polymarket
<em>twin</em> stays listed the whole time the supervisor is up
(<code>tennis_collect_now(..., is_twin=True) → True</code>). That is why a match listed tomorrow
already has a helper today, and why 50 in-match games become 100+ processes on a busy tennis day.
21 Oct's ~209 Terminal tabs were leftover empty tabs from restarts (93 real helpers × visible tab
+ hidden conhost, plus killed-supervisor leftovers) — not 209 extra Pythons. New helpers start
with <code>CREATE_NO_WINDOW</code>. Today's 2 Terminal tabs vs {esc(str(poller_n))} helpers is that fix working.
conhost is still roughly one per Python.</p>
<div class="fig">
{_process_chart(poller_n, ram_avg, ram_sum)}
<p class="cap">Figure 2. RAM vs helper count. Live bar is measured. 50 and 100 use today's average MB × N (extrapolated, labeled).</p>
</div>
<p>Each helper is its own Python, so each has its own Global Interpreter Lock (GIL) — CPU can run in
parallel. What does not scale is: working-set RAM, TLS sessions (up to four sockets per helper),
the shared HTTP pace files, and <code>price_memory.lock</code> rewriting <code>price_last.json</code>.
Focus-stealing consoles were the 21 Oct problem; they are mostly gone. Tick latency vs N games is
the remaining cost — see section 8.</p>

<h2>3. Websockets</h2>
<p>Every live helper that seeded successfully runs six asyncio tasks in one process:
four platform sockets plus two HTTP fallbacks that stay quiet while their socket is up.
There is no shared socket across games. Who reads: that helper's in-memory book, then a
compare thread (50 ms coalesce). B/C/D/E do not subscribe. They read the tape or REST.</p>
{_table(
    [("Platform", "text"), ("File", "text"), ("URL host", "text"), ("Subscribes", "text"), ("Who reads", "text"), ("Reconnect", "text"), ("HTTP fallback", "text"), ("Key files (names only)", "text")],
    ws_rows,
)}
<p class="note">Expected sockets from live_health files this census:
Kalshi {esc(str((health.get('expected') or {}).get('kalshi') or 0))},
Gemini {esc(str((health.get('expected') or {}).get('gemini') or 0))},
Polymarket {esc(str((health.get('expected') or {}).get('polymarket') or 0))},
Novig {esc(str((health.get('expected') or {}).get('novig') or 0))}.
Sum of expected flags {esc(str(exp_sum))} across {esc(str(health.get('files')))} health files
(one file per helper; a helper can expect more than one platform). Transport labels:
{esc(', '.join(f'{k}={v}' for k, v in sorted((health.get('transports') or {}).items()))) or '—'}.</p>
<p>If the socket task cannot start at all, the helper falls back to
<code>_poll_loop</code> — an ordinary event request every 5 seconds
(<code>POLL_SLEEP=5</code>), which <em>does</em> wait on the shared HTTP pace.
A burst of ticks is collapsed in 50 ms (<code>COALESCE_SEC=0.05</code>) so one
price change does not start two compares.</p>

<h2>4. When we call APIs</h2>
<div class="fig">
{_timeline_svg()}
<p class="cap">Figure 3. Schematic of the intended HTTP vs socket split. Shimizu (section 7) is what it looks like when the sender does not follow this picture.</p>
</div>
{_table(
    [("Who", "text"), ("Call", "text"), ("Cadence", "text"), ("Waits on shared pace?", "text"), ("Blocks a send?", "text")],
    [
        ["Game helper, socket up", "none (book is in memory)", "every message", "No", "No. Compare is a side thread."],
        ["Game helper, socket down", "public/signed book GET", "every 5s", "Yes", "That helper's compare, not B."],
        ["Game helper, start", "event GET (seed)", "once", "Yes", "Delays first compare for that game."],
        ["A Lock gap", "REST recheck both books, then IOC/FOK", "on a qualifying compare", "Recheck yes (was). HTML rewrite deferred until both legs finish.", "Yes, sequential hard-first. Easy waits on hard fill."],
        ["B game-start both Yes", "REST both Yes, then two IOC", "T0 window; time-boxed hunt 1.0s (0.2s if a 50-cross is armed)", "Hunt yes. Confirm-before-send still REST.", "Can still stall the long tick if many listings. Cross path is separate after the patch."],
        ["B 50-cross / dip", "memory tick; REST both Yes only when dog &gt; 50¢", "50ms idle while armed; 1s otherwise", "Cross confirm is pace=False", "No longer waits on the T0 hunt. That was Shimizu."],
        ["C / D / E", "slate walk + REST recheck + IOC", "loop sleep 1s after each tick", "Yes on REST", "Their own loop. They do not run B's 50-cross."],
        ["Catalog scan", "matched-game event GET", "watch_game sleep 120s; page rewrite on the side", "Yes", "No send. Competes for the same pace slots."],
        ["Leftover watch (A)", "quote recheck, then one IOC", "sleep at most 1s; old copy said ~20s", "Yes", "Inside the supervisor process."],
        ["job_status / dashboard", "Positions overlay + file reads", "~60s / on fill", "Positions GET yes", "Must not sit on A hard-then-easy (already deferred)."],
        ["Confirm after send", "fill-history / activities GET", "inline after HTTP", "Usually yes", "After the bet is placed, not before."],
    ],
)}
<p>Env vars the live path sets (no secrets): <code>PYTHONDONTWRITEBYTECODE=1</code>,
<code>PYTHONPYCACHEPREFIX</code> (local stamp pycache). Order flags in code:
<code>NOVIG_ORDERS_ENABLED</code> (Novig.py, currently True in code; still needs a trading key).
A missing key file skips that platform's socket; it does not print the key.</p>

<h2>5. When we place a bet, and how</h2>
<p>Every live send is <strong>1 contract</strong> unless a stake setting covers more whole contracts
(C/D/E). Confirm-before-send means a REST book read immediately before the HTTP POST.
Immediate-or-cancel (IOC) takes what is there and cancels the rest. Fill-or-kill (FOK),
used on Polymarket, is all or nothing. Good-till-cancelled (GTC) is <strong>not live</strong>
on the dip or leftover paths. Game start (T0) is the trusted clocked start of the match;
after this paragraph the page just says game start.</p>
{_table(
    [("System", "text"), ("Who", "text"), ("When it places a bet", "text"), ("How", "text"), ("GTC?", "text")],
    [
        ["A Lock gap", "Inside each game helper (<code>live_lock_orders.execute_locks</code>)",
         "Websocket compare nets at or under the send cap (0.99 after fee) and a slot is free (max 3).",
         "REST both books. Sequential <strong>hard-first</strong>: thinner displayed ask posts first (size, then historical miss rank, then cash). If hard misses, do not send easy. If hard fills, REST-recheck easy; if the gap closed, flatten hard. Drive HTML waits until both attempts finish.",
         "No. IOC / Poly FOK."],
        ["B Tennis crossover", "One process <code>live_strategy_b.py</code> pid 74812",
         "Game start: both Yes in (0.10, 0.90) and all-in cost (asks + documented taker fees) ≤ 1.05. Then, if the T0-dog Yes later prints &gt; 50¢ and favorite Yes is strictly below the dog, extra dog Yes. Then original-favorite dip at $1 − cross_fill − 0.25.",
         "REST recheck before each send. T0 is both Yes (flatten if only one fills). 50-cross and dip are one IOC each, skip-if already filled. Memory tick wakes the extra (this week).",
         "No. Dip is IOC. GTC dip is a recommendation, not wired."],
        ["C College football favorite", "<code>live_cfb_favorite.py</code> → <code>live_t0_yes</code>",
         "College football moneyline favorite Yes in (0.50, 0.90) at game start. One shot.",
         "REST recheck, IOC, hold to settlement. No 50-cross, no dip.",
         "No."],
        ["D Spreads at game start", "<code>live_spread_t0.py</code>",
         "One traditional spread Yes in (0.50, 0.90) at game start. Pro football skipped (<code>d_skip_nfl_gathering</code>). College football stays on.",
         "Same shared directional sender as C/E. Did not retune this job.",
         "No."],
        ["E Tennis dog at game start", "<code>live_tennis_t0_dog.py</code>",
         "Cheaper tennis Yes in (0.10, 0.50) at game start, cheapest platform. Skip if B already has the match. If B skipped all-in cost &gt; 1.05, E may still send the dog.",
         "IOC / Poly FOK. No 50-cross, no dip. Reads the same tennis list as B, not sports_queue.json.",
         "No."],
    ],
)}
<p class="note">A leftover watch may still place one recovery IOC for a true hedge after a one-leg
lock miss whose flatten also missed. That is not GTC. B leftover-watch is only the missed player's
Yes, never opponent No.</p>

<h2>6. Shared stores</h2>
{_table(
    [("Store", "text"), ("Path", "text"), ("Kind", "text"), ("Writes", "text"), ("Reads", "text"), ("Notes", "text")],
    [[esc(a), esc(b), esc(c), esc(d), esc(e), esc(f)] for a, b, c, d, e, f in store_rows],
)}
<p class="note">Bulky raw files live under <code>local/…/raw</code> on this PC, not Google Drive.
HTML stays in the Drive stamp. No sqlite on the live path — looked, not guessed.</p>

<h2>7. The Shimizu long-loop (a worked failure of the architecture)</h2>
<p>Quote: “The sender only checked the book once per long loop.” That is exactly the split
in Figure 1. Memory is fast. The sender was on another loop.</p>
<div class="fig">
{_shimizu_svg()}
<p class="cap">Figure 4. Real clocks from this week's Shimizu vs Hsu tape (not a schematic). Detail: b_crossover_lag_shimizu_20261028.html.</p>
</div>
<p>Memory (the Polymarket tennis helper) wrote Shimizu Yes 0.52 / Hsu Yes 0.49 at 00:23:57.410.
That print was a legal extra: favorite below dog, all-in cost 1.05. B did not read it.
<code>maybe_cross</code> REST-fetched the dog book <em>once per</em> <code>tick()</code>.
The intended sleep is 1 second. The actual tick, while open slots remained, walked every
other tennis listing with <code>try_t0</code> (Kalshi + Gemini + Polymarket + Novig, 20s event
cache). Skip rows on that hunt sit on the tape through the window. The next
<code>maybe_cross</code> is the 00:26:59.999 send at 63¢ / 38¢. Fill 0.29s later at 60¢+2¢.
3 minutes 3 seconds after the first 50¢ memory tick. We paid 11¢ extra on the extra Yes.</p>
<p>That is not “the poller was slow.” The poller was fine. The architecture let a catalog-style
REST walk sit on the only function allowed to place the extra bet. The patch: memory tick of
dog Yes &gt; 50¢ wakes REST confirm now; <code>tick_cross_only</code> every 50 ms while armed;
T0 hunt is time-boxed and re-pumps memory after each probe. Confirm-before-send stays.
One contract stays. This job does not retune the 1.05 cost cap.</p>

<h2>8. Performance vs process growth</h2>
<p>Two kinds of numbers. <strong>Measured this census</strong> from live helper health files
joined by game key to <code>live_pollers_status.json</code>
({esc(str(health.get('files')))} live keys; skipped {esc(str(health.get('skipped_stale')))} other
files of {esc(str(health.get('files_on_disk')))} on disk — Windows PIDs get reused, so we do not
join on PID) plus the process table above.
<strong>Schematic / extrapolated</strong> called out in the caption.</p>
{_table(
    [("Metric", "text"), ("Value", "text"), ("Kind", "text")],
    [
        ["Helpers now", esc(str(poller_n)), "Measured (CIM)"],
        ["Expected platform sockets (sum of flags)", esc(str(exp_sum)), "Measured (health files)"],
        ["Stream messages this minute (sum of files)", esc(str(health.get('minute_msgs'))), "Measured"],
        ["Price updates this minute", esc(str(health.get('minute_updates'))), "Measured"],
        ["Checks this minute", esc(str(health.get('minute_checks'))), "Measured"],
        ["Last compare ms, median", esc(_fmt_ms(health.get('last_ms_p50'))), "Measured"],
        ["Last compare ms, 90th pct", esc(_fmt_ms(health.get('last_ms_p90'))), "Measured"],
        ["Last compare ms, max", esc(_fmt_ms(health.get('last_ms_max'))), "Measured"],
        ["Last compare ms, mean", esc(_fmt_ms(health.get('last_ms_mean'))), "Measured"],
        ["Lifetime mean compare ms (sum/count per helper, then mean)", esc(_fmt_ms(health.get('lifetime_mean_ms'))), "Measured — includes slow HTTP seeds"],
        ["Max compare ms this minute (worst helper)", esc(_fmt_ms(health.get('minute_max_ms'))), "Measured"],
        ["Shimizu first 50¢ → send", "3m 3s (00:23:57.410 → 00:26:59.999)", "Measured this week, before patch"],
        ["Helper RAM at 50 / 100", f"{round(50*ram_avg/1024, 2) if ram_avg else '—'} GB / {round(100*ram_avg/1024, 2) if ram_avg else '—'} GB", "Extrapolated from today's average"],
    ],
)}
<p>A healthy websocket compare should be tens to a few hundred milliseconds (memory apply +
lock + jsonl append). Lifetime means that are many seconds are the HTTP seed and
<code>price_memory.lock</code> waits mixed into the same counter — not “every tick is 15 seconds.”
The last-compare distribution is the live tick. The max-this-minute number is the stall to watch
as N grows: one helper blocked on the shared lock delays that game's next send decision,
not the sockets themselves.</p>
<p>Skipped ticks: the coalesce flag (<code>dirty</code>) collapses a burst into one compare.
There is no separate “skipped tick” counter on disk. Quiet in stream_health means no socket
message for more than two minutes while the helper is still alive — a frozen feed, not a skip.</p>
<p>GIL: one per process, so 100 helpers can burn 100 cores if they wanted to. They do not.
They wait on IO. The limiter is RAM, file locks, and platform rate limits, not the GIL.</p>

<h2>9. Recommendations</h2>
<p>Document only. None of these are implemented in this job.</p>
{_table(
    [("#", "num"), ("When", "text"), ("Change", "text"), ("Why", "text")],
    rec_rows,
)}
<ol class="recs">
<li><strong>Do now — kill unused pollers / stop twin-forever.</strong> The cheapest win. Tomorrow's
listed tennis should not hold an 80 MB Python and four sockets today.</li>
<li><strong>Do now — event-wake, not REST-the-world.</strong> B's 50-cross is patched. Guard it with
tests. Do not let C/D/E's slate walk become a second Shimizu if those systems grow extras.</li>
<li><strong>Do now — HTTP budget + lock wait.</strong> One queue for Kalshi across 100+ processes
will lose ticks without anyone noticing. Put the wait on the health page.</li>
<li><strong>Discuss — one process, many games, and/or one socket per platform.</strong> That is the
shape that survives 100+ in-match names. Isolation vs RAM is the trade.</li>
<li><strong>Discuss — GTC dip rest.</strong> Hsu 38¢ vs a 15¢ IOC target is the picture. Not this job.</li>
</ol>

<p class="note">Click column headers to sort. Swipe sideways to see more columns.
Sources: <code>tools/live_game_pollers.py</code>, <code>live_quote_stream.py</code>,
<code>live_lock_orders.py</code>, <code>live_strategy_b.py</code>, <code>live_t0_yes.py</code>,
<code>price_memory.py</code>, <code>venue_pace.py</code>, <code>stream_health.py</code>,
<code>prediction_job_control.py</code>, this PC's process census, <code>raw/live_health/</code>,
<code>raw/live_pollers_status.json</code>,
<a href="poller_windows_20261021.html">poller_windows_20261021.html</a>,
<a href="b_crossover_lag_shimizu_20261028.html">b_crossover_lag_shimizu_20261028.html</a>.
No keys printed.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    # store_rows already escaped via _table? I passed pre-escaped mixed. Fix store table:
    # The store_rows have no HTML tags except I used plain text. But I wrapped with a broken listcomp.
    # Rebuild page's store section is already using store_rows through a messy comprehension.
    # Looking at my code: I did [[esc(a)...]] inside the f-string via store_rows directly in _table
    # wait, I used a broken listcomp. Let me fix by writing the page with a clean store table.

    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(f"wrote {PAGE}")
    print(f"svg {SVG}")
    print(f"poller_n={poller_n} python={census.get('python_n')} OpenConsole={census.get('OpenConsole')} conhost={census.get('conhost')}")
    print(f"ws_expected_sum={exp_sum} health_files={health.get('files')}")
    print(f"last_ms_p50={health.get('last_ms_p50')} lifetime_mean_ms={health.get('lifetime_mean_ms')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
