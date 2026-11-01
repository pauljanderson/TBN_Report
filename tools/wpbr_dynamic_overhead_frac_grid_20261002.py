"""WPBR dynamic overhead fraction grid: 90/40 vs 80/40 vs 70/40 vs live control + fixed packages.

Research only. Fractions apply for every constraining overhead G (including G>=22%).
Clear sky (no older zone) keeps fixed 20% target / 8% stop. No hard skip at 22%.
Also reports fixed packages: 16/8/3, 16/8/4, 16/8/5 (neighborhood cells), 16/7/3–5,
17/7/2–5, and 17/7/6 (extra fixed cells — target 7% is outside the neighborhood tg 8–12 grid).
OOS report-only. Not gold. Not DailyRun. Does not change run_wpbr.bat.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import pickle
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    calmar_ratio,
    sharpe_from_equity_curve_csv,
)
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

STAMP = "20261002"
IS_CUT = "20240101"
IS_DATE = date(2024, 1, 1)
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_dynamic_overhead_frac_grid_{STAMP}"
RUNS_DIR = ROOT / "tmp_wpbr_dynamic_overhead_frac_grid_20261002"
PRIOR_90_DIR = ROOT / "tmp_wpbr_dynamic_overhead_sizing_20261002" / "dynamic"
CONTROL_DIR = ROOT / "tmp_wpbr_overhead20_vs22_t20s8_ab_20261002" / "control"
NEIGH_TMP = ROOT / "tmp_wpbr_15_10_4_neighborhood_20261002"
PY = sys.executable
WORKERS = 8
# Paul cap: do not stack more than 4 extra rocket_tbn engines on top of neighborhood.
# Neighborhood at 4 → wait / one-at-a-time. Neighborhood done → up to 4 of these at -w 8.
NEIGH_PARENT_CAP = 2
CPU_CAP = 90.0
MAX_EXTRA_ENGINES = 4

COMMON: dict[str, str] = {
    "wpbr_zones": "true",
    "brt_zones": "false",
    "yh_zones": "false",
    "vec_zones": "false",
    "band_pct": "0.015",
    "strong_pre_pivot_bars": "3",
    "strong_pre_pivot_pct": "0.10",
    "strong_post_pivot_bars": "3",
    "strong_post_pivot_pct": "0.10",
    "strong_pivot_mode": "either",
    "wpbr_breakout_confirmation": "0.03",
    "wpbr_max_days_after_retest": "2",
    "wpbr_second_chance_after_win": "true",
    "growth_filter_enabled": "false",
    "growth_bars": "756",
    "growth_history_slack_bars": "0",
    "min_history_bars": "0",
    "growth_filter_strict_gt": "false",
    "growth_min_pct": "0",
    "wpbr_overhead_band_pct": "0",
    "wpbr_dynamic_overhead": "true",
    "min_spy_compare_1y_at_trigger": "-1000",
    "ind_score_weights_path": "",
    "too_high_multiplier": "0",
    "target_pct": "1.20",
    "stop_pct": "0.92",
    "sheet_no_entry_same_bar_after_exit": "false",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
}

ARMS: list[dict[str, Any]] = [
    {
        "id": "t90_s40",
        "short": "90/40",
        "role": "research A (reuse prior if valid)",
        "t_frac": 0.90,
        "s_frac": 0.40,
        "folder_name": "t90_s40",
        "reuse_prior": True,
        "kind": "dynamic",
    },
    {
        "id": "t80_s40",
        "short": "80/40",
        "role": "research B",
        "t_frac": 0.80,
        "s_frac": 0.40,
        "folder_name": "t80_s40",
        "reuse_prior": False,
        "kind": "dynamic",
    },
    {
        "id": "t70_s40",
        "short": "70/40",
        "role": "research C",
        "t_frac": 0.70,
        "s_frac": 0.40,
        "folder_name": "t70_s40",
        "reuse_prior": False,
        "kind": "dynamic",
    },
]

# Fixed packages (NOT dynamic fractions). Reuse Closed if present; run only missing.
FIXED_ARMS: list[dict[str, Any]] = [
    {
        "id": "oh16_tg08_st03",
        "short": "16/8/3",
        "role": "fixed package (neighborhood cell)",
        "folder": NEIGH_TMP / "oh16_tg08_st03",
        "kind": "fixed",
        "overhead_band_pct": 0.16,
        "target_pct": 1.08,
        "stop_pct": 0.97,
        "stop_under_pct": 3,
        "target_gain_pct": 8,
        # fixed books use static target — G cannot be recovered from target identity
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh16_tg08_st04",
        "short": "16/8/4",
        "role": "fixed package (neighborhood cell)",
        "folder": NEIGH_TMP / "oh16_tg08_st04",
        "kind": "fixed",
        "overhead_band_pct": 0.16,
        "target_pct": 1.08,
        "stop_pct": 0.96,
        "stop_under_pct": 4,
        "target_gain_pct": 8,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh16_tg08_st05",
        "short": "16/8/5",
        "role": "fixed package (neighborhood cell)",
        "folder": NEIGH_TMP / "oh16_tg08_st05",
        "kind": "fixed",
        "overhead_band_pct": 0.16,
        "target_pct": 1.08,
        "stop_pct": 0.95,
        "stop_under_pct": 5,
        "target_gain_pct": 8,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh16_tg07_st03",
        "short": "16/7/3",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        "folder": RUNS_DIR / "oh16_tg07_st03",
        "kind": "fixed",
        "overhead_band_pct": 0.16,
        "target_pct": 1.07,
        "stop_pct": 0.97,
        "stop_under_pct": 3,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh16_tg07_st04",
        "short": "16/7/4",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        "folder": RUNS_DIR / "oh16_tg07_st04",
        "kind": "fixed",
        "overhead_band_pct": 0.16,
        "target_pct": 1.07,
        "stop_pct": 0.96,
        "stop_under_pct": 4,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh16_tg07_st05",
        "short": "16/7/5",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        "folder": RUNS_DIR / "oh16_tg07_st05",
        "kind": "fixed",
        "overhead_band_pct": 0.16,
        "target_pct": 1.07,
        "stop_pct": 0.95,
        "stop_under_pct": 5,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh17_tg07_st02",
        "short": "17/7/2",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        "folder": RUNS_DIR / "oh17_tg07_st02",
        "kind": "fixed",
        "overhead_band_pct": 0.17,
        "target_pct": 1.07,
        "stop_pct": 0.98,
        "stop_under_pct": 2,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh17_tg07_st03",
        "short": "17/7/3",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        "folder": RUNS_DIR / "oh17_tg07_st03",
        "kind": "fixed",
        "overhead_band_pct": 0.17,
        "target_pct": 1.07,
        "stop_pct": 0.97,
        "stop_under_pct": 3,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh17_tg07_st04",
        "short": "17/7/4",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        "folder": RUNS_DIR / "oh17_tg07_st04",
        "kind": "fixed",
        "overhead_band_pct": 0.17,
        "target_pct": 1.07,
        "stop_pct": 0.96,
        "stop_under_pct": 4,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh17_tg07_st05",
        "short": "17/7/5",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        "folder": RUNS_DIR / "oh17_tg07_st05",
        "kind": "fixed",
        "overhead_band_pct": 0.17,
        "target_pct": 1.07,
        "stop_pct": 0.95,
        "stop_under_pct": 5,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh17_tg07_st06",
        "short": "17/7/6",
        "role": "fixed package (extra cell; tg07 outside neigh grid)",
        # Outside neighborhood tg 8–12 grid — score under frac-grid tmp (not neigh path)
        # so this engine does not count against neighborhood process caps.
        "folder": RUNS_DIR / "oh17_tg07_st06",
        "kind": "fixed",
        "overhead_band_pct": 0.17,
        "target_pct": 1.07,
        "stop_pct": 0.94,
        "stop_under_pct": 6,
        "target_gain_pct": 7,
        "t_frac": 0.90,
        "recover_g": True,
    },
    {
        "id": "oh17_tg08_st06",
        "short": "17/8/6",
        "role": "fixed package (neighborhood cell)",
        "folder": NEIGH_TMP / "oh17_tg08_st06",
        "kind": "fixed",
        "overhead_band_pct": 0.17,
        "target_pct": 1.08,
        "stop_pct": 0.94,
        "stop_under_pct": 6,
        "target_gain_pct": 8,
        "t_frac": 0.90,
        "recover_g": True,
    },
]

REQUEST_QUOTE = (
    "yes, but i would also like to know what the results are if there is an overhead "
    "zone >=22% if we use the fractions for those too. can you run that for 90/40 and "
    "then try B and C. also, let's add this to the mix oh16_tg08_st03. i'd like to see "
    "the bins and results alongside the dynamic ones and the control please. "
    "add 17/7/6 and 16/8/4 and 16/8/5 to the mix too. "
    "for each of the bin reports i would also like to know the aggregate of all bins, "
    "so if we don't care about what bin they live in we just trade them all - what do "
    "those numbers look like for each of them? "
    "run a couple more WPBR tests with overhead/target/stop: "
    "16/7/3, 16/7/4, 16/7/5, 17/7/2, 17/7/3, 17/7/4, 17/7/5. "
    "what are the results if we run control, but ONLY take trades where there IS "
    "overhead, but it is 22% or greater away? (i.e. we don't take the trades "
    "where there is NO overhead bin) "
    "run a test using 17/8/6 taking NO trades unless there is an overhead zone. "
    "what if we build our dynamic target / stop on top of that the 70/40 for "
    "zones above >= 17%"
)

LAYMAN = (
    "Pivot Break and Retest (WPBR) live skip buys when an older zone sits within 22% "
    "above the buy zone. This follow-up still takes those buys, and also takes buys "
    "where the older zone is farther than 22%, and in every case shrinks the profit "
    "target and stop to a fraction of the gap to that older zone. Clear sky (truly no "
    "older zone above) keeps the live 20% target and 8% stop. Arms: A = target 90% of "
    "gap / stop 40% of that target; B = 80/40; C = 70/40. Also included: fixed packages "
    "16/8/3, 16/8/4, 16/8/5 (skip when older-zone gap G ≤ 16%, 8% profit target, stop "
    "3%/4%/5% under trigger-day low), 16/7/3–5 (same 16% skip, 7% target, stop 3%/4%/5%), "
    "and 17/7/2–6 (skip when G ≤ 17%, 7% target, stop 2–6% under trigger-day low) "
    "— neighborhood-style fixed packages, not fraction sizing. Target 7 sits outside the "
    "15/10/4 neighborhood grid (that grid is target 8–12). We break results out by "
    "how far the older zone was — including the far band G≥22% — and each bin table ends "
    "with an All bins (trade all) total that is the whole closed book if you ignore which "
    "gap band a trade sits in. Separate named slice: live control but only buys that have "
    "an older overhead zone AND gap G ≥ 22% (drop clear-sky / no-overhead). Same 20% target "
    "and 8% stop — a filter of the live book, not a new engine freeze. Also: fixed package "
    "17/8/6 (skip when G ≤ 17%, 8% target, 6% stop under trigger-day low; Closed reused from "
    "the 15/10/4 neighborhood cell, not recomputed) and the same 17/8/6 book with clear-sky "
    "dropped — keep only buys that still have a constraining older zone (any recovered G that "
    "entered; this freeze already skips G ≤ 17%; do not require G ≥ 22%). All bins on that "
    "filtered table is the overhead-only set. Also: take the existing 70/40 dynamic book "
    "(target = 70% of gap G, stop under trigger-day low = 40% of that target) and keep only "
    "trades with a recovered overhead gap G ≥ 17%. Drop clear-sky and drop G < 17% (too close). "
    "17% is the skip/floor, not a fixed 17/8/6 exit. Example: G=17 → target 11.9% / stop 4.76%; "
    "G=22 → 15.4% / 6.16%. Slot cash is the 70/40 engine slot (about $2,449, not $47,500 and "
    "not the 90/40 $2,362 slot). Post-process of the existing Closed — not a new engine. "
    "G bins on that slice are 17–22, 22–30, and G>30; All bins is this filtered set. "
    "Research only; DailyRun unchanged."
)

ALL_BINS_LABEL = "All bins (trade all)"

# Display bins (mutually exclusive for the per-bin table).
G_BINS: list[tuple[str, float | None, float | None]] = [
    ("no overhead", None, None),
    ("G < 8%", 0.0, 8.0),
    ("8–12%", 8.0, 12.0),
    ("12–16%", 12.0, 16.0),
    ("16–22%", 16.0, 22.0),
    ("22–30%", 22.0, 30.0),
    ("G > 30%", 30.0, None),
]

ANN_FLAT = 0.25
ANN_WORSE = 0.15
PF_WORSE = 0.05
DD_WORSE = 1.0
N_FLOOR = 0.85


def _f(raw: Any, default: float = float("nan")) -> float:
    if raw is None:
        return default
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _ymd(raw: str) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _fmt(v: float, nd: int = 2, suf: str = "") -> str:
    if not math.isfinite(v):
        return "—"
    if nd == 0:
        return f"{v:.0f}{suf}"
    return f"{v:.{nd}f}{suf}"


def _delta(a: float, b: float, nd: int = 2, suf: str = "") -> str:
    if not math.isfinite(a) or not math.isfinite(b):
        return "—"
    d = a - b
    sign = "+" if d > 0 else ""
    return f"{sign}{_fmt(d, nd, suf)}"


def _latest(folder: Path, needle: str) -> Path | None:
    hits = sorted(folder.glob(f"WPBR_{needle}_*.csv"), key=lambda p: p.stat().st_mtime)
    if needle == "EquityCurve":
        primary = [p for p in hits if "_Aggressive_" not in p.name and "_Regular_" not in p.name]
        if primary:
            return primary[-1]
    return hits[-1] if hits else None


def _read_report(folder: Path) -> dict[str, str]:
    path = _latest(folder, "Report")
    if path is None:
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def _ps(cmd: str) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        cwd=str(ROOT), capture_output=True, text=True, check=False,
    )
    return (r.stdout or "").strip()


def _neighborhood_parent_count() -> int:
    ps = (
        "@(Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -match 'rocket_tbn\\.py' "
        "-and $_.CommandLine -match 'tmp_wpbr_15_10_4_neighborhood' "
        "-and $_.CommandLine -notmatch 'spawn_main' "
        "}).Count"
    )
    try:
        return int(_ps(ps).splitlines()[-1])
    except (ValueError, IndexError):
        return 99


def _dynamic_parent_count() -> int:
    ps = (
        "@(Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -match 'rocket_tbn\\.py' "
        "-and $_.CommandLine -match 'tmp_wpbr_dynamic_overhead_frac_grid' "
        "-and $_.CommandLine -notmatch 'spawn_main' "
        "}).Count"
    )
    try:
        return int(_ps(ps).splitlines()[-1])
    except (ValueError, IndexError):
        return 99


def _cpu_load() -> float:
    ps = (
        "Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage "
        "-Average | Select-Object -ExpandProperty Average"
    )
    try:
        return float(_ps(ps).splitlines()[-1])
    except (ValueError, IndexError):
        return 100.0


def _rocket_parent_count() -> int:
    ps = (
        "@(Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -match 'rocket_tbn\\.py' "
        "-and $_.CommandLine -notmatch 'spawn_main' "
        "-and $_.CommandLine -notmatch 'http\\.server' "
        "-and $_.CommandLine -notmatch 'hv15m' "
        "}).Count"
    )
    try:
        return int(_ps(ps).splitlines()[-1])
    except (ValueError, IndexError):
        return 99


def _extra_engine_count() -> int:
    """rocket_tbn parents that are not neighborhood cell engines."""
    total = _rocket_parent_count()
    neigh = _neighborhood_parent_count()
    if total >= 90:
        return 99
    return max(0, total - neigh)


def _launch_room() -> int:
    """How many extra engines we may start now. Neighborhood at 4 → wait."""
    neigh = _neighborhood_parent_count()
    extra = _extra_engine_count()
    if neigh >= 4:
        return 0
    room = MAX_EXTRA_ENGINES - extra
    if neigh > 0:
        room = min(room, 1)
    return max(0, room)


def _wait_for_slot(arm_id: str) -> bool:
    """Wait until there is room for one extra engine.

    Returns True if DuckDB is free (caller may use --use-duckdb); False → CSV path.
    """
    while True:
        neigh = _neighborhood_parent_count()
        extra = _extra_engine_count()
        room = _launch_room()
        duck_locked = _duckdb_locked()
        print(
            f"[cap] arm={arm_id} neigh_parents={neigh} extra_engines={extra} "
            f"room={room} duck_locked={duck_locked} "
            f"(max extra={MAX_EXTRA_ENGINES}; neigh>=4 waits)",
            flush=True,
        )
        if room >= 1:
            return not duck_locked
        time.sleep(60)


def _duckdb_locked() -> bool:
    """True if another process holds data/ohlcv.duckdb (Windows exclusive)."""
    db = ROOT / "data" / "ohlcv.duckdb"
    if not db.is_file():
        return False
    ps = (
        f"$p='{db}'; "
        "try { $f=[System.IO.File]::Open($p,'Open','ReadWrite','None'); $f.Close(); $false } "
        "catch { $true }"
    )
    try:
        return _ps(ps).splitlines()[-1].strip().lower() in {"true", "1"}
    except (ValueError, IndexError):
        return True


def _cmd(out: Path, t_frac: float, s_frac: float, *, use_duckdb: bool) -> list[str]:
    cmd = [
        PY, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(WORKERS),
        "--aggressive", "--no-regression",
    ]
    # Prefer DuckDB when free; otherwise CSV so we do not collide with another --use-duckdb job.
    if use_duckdb:
        cmd.append("--use-duckdb")
    knobs = dict(COMMON)
    knobs["wpbr_dyn_oh_target_frac"] = f"{t_frac:.2f}"
    knobs["wpbr_dyn_oh_stop_frac"] = f"{s_frac:.2f}"
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    return cmd


def _fixed_cmd(farm: dict[str, Any], *, use_duckdb: bool) -> list[str]:
    """Engine cmd for a fixed overhead/target/stop package (not dynamic fractions)."""
    out: Path = farm["folder"]
    cmd = [
        PY, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(WORKERS),
        "--aggressive", "--no-regression",
    ]
    if use_duckdb:
        cmd.append("--use-duckdb")
    knobs = dict(COMMON)
    knobs["wpbr_dynamic_overhead"] = "false"
    knobs["wpbr_overhead_band_pct"] = f"{float(farm['overhead_band_pct']):.2f}"
    knobs["target_pct"] = f"{float(farm['target_pct']):.2f}"
    knobs["stop_pct"] = f"{float(farm['stop_pct']):.2f}"
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    return cmd


def _ensure_all_fixed_arms(*, report_only: bool) -> None:
    """Reuse Closed if scored; run missing cells in waves of up to MAX_EXTRA_ENGINES."""
    missing: list[dict[str, Any]] = []
    for farm in FIXED_ARMS:
        out: Path = farm["folder"]
        if _closed_ready(out):
            farm["_reused_closed"] = True
            print(f"[reuse] {farm['id']} -> {out}", flush=True)
            continue
        farm["_reused_closed"] = False
        farm["_tries"] = 0
        if report_only:
            raise SystemExit(
                f"--report-only missing fixed arm {farm['id']} Closed at {out} "
                "(wait for neighborhood cell or run without --report-only)"
            )
        missing.append(farm)

    while missing:
        room = _launch_room()
        if room < 1:
            _wait_for_slot(missing[0]["id"])
            continue
        wave = missing[:room]
        missing = missing[room:]
        duck_ok = (not _duckdb_locked()) and _neighborhood_parent_count() == 0
        alive: list[tuple[dict[str, Any], subprocess.Popen, Path]] = []
        for i, farm in enumerate(wave):
            out = farm["folder"]
            out.mkdir(parents=True, exist_ok=True)
            farm["_tries"] = int(farm.get("_tries") or 0) + 1
            use_duck = duck_ok and i == 0
            log_path = RUNS_DIR / f"{farm['id']}.log"
            cmd = _fixed_cmd(farm, use_duckdb=use_duck)
            (out / "run_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
            mode = "duckdb" if use_duck else "csv"
            print(
                f"[start] fixed {farm['id']} attempt={farm['_tries']} mode={mode} "
                f"workers={WORKERS} log={log_path}",
                flush=True,
            )
            log_f = log_path.open("w", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_f, stderr=subprocess.STDOUT)
            alive.append((farm, proc, log_path, log_f))
        still = list(alive)
        while still:
            time.sleep(45)
            nxt = []
            for farm, proc, log_path, log_f in still:
                rc = proc.poll()
                if rc is None:
                    print(f"[wait] fixed {farm['id']} pid={proc.pid} running…", flush=True)
                    nxt.append((farm, proc, log_path, log_f))
                    continue
                try:
                    log_f.close()
                except OSError:
                    pass
                if rc == 0 and _closed_ready(farm["folder"]):
                    print(f"[fixed] {farm['id']} ready -> {farm['folder']}", flush=True)
                    continue
                print(
                    f"[retry] fixed {farm['id']} rc={rc} "
                    f"closed_ready={_closed_ready(farm['folder'])}; see {log_path}",
                    flush=True,
                )
                if int(farm.get("_tries") or 0) >= 3:
                    raise SystemExit(
                        f"fixed {farm['id']} engine failed after retries; see {log_path}"
                    )
                missing.append(farm)
            still = nxt
        if missing:
            time.sleep(30)


def _closed_ready(folder: Path) -> bool:
    return folder.is_dir() and _latest(folder, "Closed") is not None


def _prior_90_applies_fractions_for_far_g() -> bool:
    """Verify prior 90/40 book sized G>=22% with fractions (not fixed 20/8 clear-sky)."""
    if not _closed_ready(PRIOR_90_DIR):
        return False
    report = _read_report(PRIOR_90_DIR)
    dyn = str(report.get("wpbr_dynamic_overhead") or "").strip().lower()
    if dyn not in {"true", "1", "yes", "on"}:
        return False
    closed = _latest(PRIOR_90_DIR, "Closed")
    assert closed is not None
    far = 0
    clearish = 0
    with closed.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            entry = _f(raw.get("ENTRY_PRICE"))
            target = _f(raw.get("TARGET_PRICE"))
            if not (math.isfinite(entry) and entry > 0 and math.isfinite(target) and target > 0):
                continue
            gain = target / entry - 1.0
            if abs(gain - 0.20) < 0.002:
                clearish += 1
                continue
            if gain <= 0:
                continue
            g = (gain / 0.90) * 100.0
            if g >= 22.0:
                far += 1
    print(f"[verify] prior 90/40: clearish≈20% targets={clearish}, recovered G>=22%={far}", flush=True)
    return far > 0


def _recover_g_pct(raw: dict[str, Any], t_frac: float) -> float | None:
    g = _f(raw.get("OVERHEAD_GAP_PCT"))
    if math.isfinite(g):
        return g
    entry = _f(raw.get("ENTRY_PRICE"))
    target = _f(raw.get("TARGET_PRICE"))
    if not (math.isfinite(entry) and entry > 0 and math.isfinite(target) and target > 0):
        return None
    gain = target / entry - 1.0
    if abs(gain - 0.20) < 0.002:
        return None
    if gain <= 0 or t_frac <= 0:
        return None
    return (gain / t_frac) * 100.0


def _fixed_g_lookup(folder: Path, label: str = "fixed") -> dict[tuple[str, str, str], float | None]:
    """Map (symbol, opened, zone_id) -> overhead G% for closed books lacking OVERHEAD_GAP_PCT.

    Recover by:
    1) exact join to candidate 80/40 closed OVERHEAD_GAP_PCT (same zone + entry date),
    2) same-symbol+zone fallback,
    3) recompute via prior_overhead_nearest_gap on this folder's checkpoint breakout/retest zones.
    Blank / None = clear sky (no older overhead zone).
    """
    import numpy as np

    from stock_analysis.rocket_tbn import BRTTrade, prior_overhead_nearest_gap
    import __main__

    __main__.BRTTrade = BRTTrade

    cand_closed = _latest(RUNS_DIR / "t80_s40", "Closed")
    if cand_closed is None:
        cand_closed = _latest(RUNS_DIR / "t70_s40", "Closed")
    if cand_closed is None:
        raise FileNotFoundError("no candidate closed book for fixed-arm G join")

    exact: dict[tuple[str, str, str], float | None] = {}
    by_zone: dict[tuple[str, str], list[float | None]] = defaultdict(list)
    with cand_closed.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            opened = _ymd(str(raw.get("DATE_OPENED") or ""))
            zid = str(raw.get("WPBR_ZONE_ID") or "").strip()
            if not sym or not opened:
                continue
            raw_g = str(raw.get("OVERHEAD_GAP_PCT") or "").strip()
            if raw_g:
                g = _f(raw_g)
                g_val: float | None = g if math.isfinite(g) else None
            else:
                g_val = None  # blank OVERHEAD_GAP_PCT = clear sky on B/C books
            exact[(sym, opened, zid)] = g_val
            by_zone[(sym, zid)].append(g_val)

    ckpts = sorted(folder.glob("WPBR_Checkpoint_*.pkl"), key=lambda p: p.stat().st_mtime)
    ckpt = ckpts[-1] if ckpts else None
    inv: dict[str, dict[str, Any]] = {}
    br_by_zone: dict[tuple[str, float, float], list[dict[str, Any]]] = defaultdict(list)
    if ckpt is not None and ckpt.is_file():
        with ckpt.open("rb") as f:
            obj = pickle.load(f)
        for r in obj.get("all_breakout_retest") or []:
            sym = str(r.get("SYMBOL") or "").strip().upper()
            try:
                lo = float(r["zone_lower"])
                hi = float(r["zone_upper"])
            except (KeyError, TypeError, ValueError):
                continue
            born = int(r["zone_band_bar"]) if r.get("zone_band_bar") is not None else -1
            mat = str(r.get("maturity_source_iso") or "")
            mat_fmt = f"{mat[:4]}-{mat[4:6]}-{mat[6:8]}" if len(mat) == 8 else mat
            zid = f"{mat_fmt}|{lo:.4f}|{hi:.4f}"
            slot = inv.setdefault(sym, {"born": [], "lo": [], "ids": []})
            slot["born"].append(born)
            slot["lo"].append(lo)
            slot["ids"].append(zid)
            br_by_zone[(sym, round(lo, 4), round(hi, 4))].append(r)
        for slot in inv.values():
            slot["born_arr"] = np.asarray(slot["born"], dtype=np.int32)
            slot["lo_arr"] = np.asarray(slot["lo"], dtype=np.float64)

    out: dict[tuple[str, str, str], float | None] = {}
    src = Counter()
    closed = _latest(folder, "Closed")
    assert closed is not None
    with closed.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            opened = _ymd(str(raw.get("DATE_OPENED") or ""))
            zid = str(raw.get("WPBR_ZONE_ID") or "").strip()
            if not sym or not opened:
                continue
            key = (sym, opened, zid)
            if key in exact:
                out[key] = exact[key]
                src["exact"] += 1
                continue
            zs = by_zone.get((sym, zid))
            if zs:
                finite = [g for g in zs if g is not None and math.isfinite(g)]
                out[key] = finite[0] if finite else None
                src["zone_fb"] += 1
                continue
            top = _f(raw.get("ZONE_TOP"))
            bot = _f(raw.get("ZONE_BOTTOM"))
            slot = inv.get(sym)
            if slot is None or not math.isfinite(top) or top <= 0:
                out[key] = None
                src["recon_miss"] += 1
                continue
            trigger_bar = None
            if math.isfinite(bot):
                for br in br_by_zone.get((sym, round(float(bot), 4), round(float(top), 4)), []):
                    if br.get("retest_bar") is not None:
                        trigger_bar = int(br["retest_bar"])
                        break
            if trigger_bar is None:
                out[key] = None
                src["recon_nobar"] += 1
                continue
            g_frac = prior_overhead_nearest_gap(
                slot["born_arr"],
                slot["lo_arr"],
                slot["ids"],
                active_id=zid,
                active_upper=float(top),
                trigger_bar=int(trigger_bar),
            )
            if g_frac is None:
                out[key] = None
                src["recon_clear"] += 1
            else:
                out[key] = float(g_frac) * 100.0
                src["recon_g"] += 1
    print(f"[g] {label} recovery src={dict(src)} from {cand_closed.name}", flush=True)
    return out


def _control_g_lookup() -> dict[tuple[str, str, str], float | None]:
    return _fixed_g_lookup(CONTROL_DIR, label="control")


def _load_trades(
    path: Path,
    t_frac: float,
    *,
    g_lookup: dict[tuple[str, str, str], float | None] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    nonempty_g = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _ymd(str(raw.get("DATE_OPENED") or ""))
            if not opened:
                continue
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            zid = str(raw.get("WPBR_ZONE_ID") or "").strip()
            raw_g = str(raw.get("OVERHEAD_GAP_PCT") or "").strip()
            if raw_g:
                nonempty_g += 1
            if g_lookup is not None:
                g = g_lookup.get((sym, opened, zid))
            else:
                g = _recover_g_pct(raw, t_frac)
            rows.append({
                "symbol": sym,
                "opened": opened,
                "closed": _ymd(str(raw.get("DATE_CLOSED") or "")),
                "pnl": _f(raw.get("PNL_PCT")),
                "pnl_d": _f(raw.get("PNL_DOLLARS")),
                "days": _f(raw.get("DAYS_HELD")),
                "exit": str(raw.get("EXIT_TYPE") or "").strip() or "?",
                "entry": _f(raw.get("ENTRY_PRICE")),
                "target": _f(raw.get("TARGET_PRICE")),
                "stop": _f(raw.get("STOP_PRICE")),
                "g_pct": g,
            })
    print(f"[g] {path.name}: OVERHEAD_GAP_PCT nonempty={nonempty_g}/{len(rows)}", flush=True)
    return rows


def _slot_cash(folder: Path, trades: list[dict[str, Any]]) -> tuple[float, str]:
    report = _read_report(folder)
    cap = _f(report.get("capacity_brt_cash"))
    if math.isfinite(cap) and cap > 0:
        return cap, "report capacity_brt_cash (engine slot after host dollar scale)"
    notions: list[float] = []
    for t in trades:
        if math.isfinite(t["pnl_d"]) and math.isfinite(t["pnl"]) and abs(t["pnl"]) > 0.05:
            notions.append(abs(t["pnl_d"]) / (abs(t["pnl"]) / 100.0))
    if not notions:
        raise RuntimeError(f"no slot cash in {folder}")
    notions.sort()
    return notions[len(notions) // 2], "median |PNL_DOLLARS| / |PNL_PCT|"


def _slice_rows(trades: list[dict[str, Any]], window: str) -> list[dict[str, Any]]:
    if window == "FULL":
        return trades
    if window == "IS":
        return [t for t in trades if t["opened"] < IS_CUT]
    return [t for t in trades if t["opened"] >= IS_CUT]


def _profit_factor(pnls: list[float]) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    if gl > 0:
        return gp / gl
    return float("inf") if gp > 0 else float("nan")


def _equity_max_dd(path: Path | None, start: date | None, end_excl: date | None) -> float:
    if path is None or not path.is_file():
        return float("nan")
    peak = None
    worst = 0.0
    seen = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw_d = str(row.get("Date") or "")[:10]
            try:
                d = datetime.strptime(raw_d, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start is not None and d < start:
                continue
            if end_excl is not None and d >= end_excl:
                continue
            v = _f(row.get("Equity_Regular"))
            if not math.isfinite(v) or v <= 0:
                continue
            seen += 1
            if peak is None or v > peak:
                peak = v
            if peak and peak > 0:
                worst = max(worst, (peak - v) / peak)
    if seen < 2:
        return float("nan")
    return worst * 100.0


def _metrics(trades: list[dict[str, Any]], cash: float, curve: Path | None, window: str) -> dict[str, Any]:
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    empty: dict[str, Any] = {
        "n": 0, "wins": 0, "wr": float("nan"), "avg": float("nan"), "median": float("nan"),
        "pf": float("nan"), "max_dd": float("nan"), "ann_ror": float("nan"),
        "avg_days": float("nan"), "med_days": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "expect": float("nan"), "wo_max": float("nan"), "tpy": float("nan"),
        "total_pnl": float("nan"),
    }
    if n == 0:
        return empty
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    avg_days = (sum(days) / len(days)) if days else 0.0
    dols = [t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"])]
    total = sum(dols) if len(dols) == n else sum(p / 100.0 * cash for p in pnls)
    ann = ann_ror_from_closed(
        total_pnl=total, n_trades=n, avg_days_held=avg_days, brt_cash=cash,
    )
    if window == "IS":
        start, end = None, IS_DATE
    elif window == "OOS":
        start, end = IS_DATE, None
    else:
        start, end = None, None
    max_dd = _equity_max_dd(curve, start, end)
    ann_v = float(ann) if ann is not None else float("nan")
    calmar = calmar_ratio(ann_v, max_dd)
    sharpe = sharpe_from_equity_curve_csv(curve, start_date=start, end_date_exclusive=end)
    opens = []
    closes = []
    for t in trades:
        try:
            opens.append(datetime.strptime(t["opened"], "%Y%m%d").date())
            closes.append(datetime.strptime(t["closed"] or t["opened"], "%Y%m%d").date())
        except ValueError:
            continue
    span = ((max(closes) - min(opens)).days / 365.25) if opens and closes else 0.0
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else float("nan")
    return {
        "n": n,
        "wins": len(wins),
        "wr": 100.0 * len(wins) / n,
        "avg": sum(pnls) / n,
        "median": float(statistics.median(pnls)),
        "pf": _profit_factor(pnls),
        "max_dd": max_dd,
        "ann_ror": ann_v,
        "avg_days": avg_days,
        "med_days": float(statistics.median(days)) if days else float("nan"),
        "calmar": float(calmar) if calmar is not None else float("nan"),
        "sharpe": float(sharpe) if sharpe is not None else float("nan"),
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "expect": sum(pnls) / n,
        "wo_max": wo,
        "tpy": (n / span) if span > 0.25 else float("nan"),
        "total_pnl": total,
    }


def _g_bin(g: float | None) -> str:
    if g is None or not math.isfinite(g):
        return "no overhead"
    if g < 8.0:
        return "G < 8%"
    if g < 12.0:
        return "8–12%"
    if g < 16.0:
        return "12–16%"
    if g < 22.0:
        return "16–22%"
    if g <= 30.0:
        return "22–30%"
    return "G > 30%"


CONTROL_G22_SHORT = "Control, overhead G>=22% only"


def _control_oh_g22_book(ctrl: dict[str, Any]) -> dict[str, Any]:
    """Filter live control to overhead-present G>=22% (drop clear-sky). Same freeze."""
    trades = [
        t for t in ctrl["trades"]
        if t.get("g_pct") is not None and math.isfinite(t["g_pct"]) and t["g_pct"] >= 22.0
    ]
    cash = ctrl["cash"]
    curve = ctrl["curve"]
    slices = {w: _metrics(_slice_rows(trades, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    is_c, is_0 = slices["IS"], ctrl["slices"]["IS"]
    d_ann = (is_c["ann_ror"] - is_0["ann_ror"]) if math.isfinite(is_c["ann_ror"]) and math.isfinite(is_0["ann_ror"]) else float("nan")
    d_pf = (is_c["pf"] - is_0["pf"]) if math.isfinite(is_c["pf"]) and math.isfinite(is_0["pf"]) else float("nan")
    d_avg = (is_c["avg"] - is_0["avg"]) if math.isfinite(is_c["avg"]) and math.isfinite(is_0["avg"]) else float("nan")
    word = "HOLD"
    text = (
        f"{CONTROL_G22_SHORT}: HOLD — subset of the same freeze (research only, not a new "
        f"DailyRun freeze). In-sample Ann ROR {_fmt(is_c['ann_ror'], 2, '%')} vs full control "
        f"{_fmt(is_0['ann_ror'], 2, '%')} (Δ {_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')}) "
        f"but N collapsed by design ({is_c['n']} vs {is_0['n']}); win rate / avg % / profit factor "
        f"softer (WR {_fmt(is_c['wr'], 1, '%')} vs {_fmt(is_0['wr'], 1, '%')}; avg "
        f"{_fmt(is_c['avg'], 2, '%')} vs {_fmt(is_0['avg'], 2, '%')}; PF {_fmt(is_c['pf'], 2)} vs "
        f"{_fmt(is_0['pf'], 2)}). OOS report-only. Do not adopt from this filter."
    )
    if math.isfinite(d_ann) and d_ann < -ANN_WORSE:
        word = "DISMISS"
        text = (
            f"{CONTROL_G22_SHORT}: DISMISS — in-sample Ann ROR {_fmt(is_c['ann_ror'], 2, '%')} vs "
            f"full control {_fmt(is_0['ann_ror'], 2, '%')}."
        )
    _ = (d_pf, d_avg)
    g2230 = [t for t in trades if t["g_pct"] <= 30.0]
    g30 = [t for t in trades if t["g_pct"] > 30.0]
    return {
        "id": "control_oh_g22",
        "short": CONTROL_G22_SHORT,
        "role": "subset of live control (overhead present, G>=22%; drop clear-sky)",
        "folder": ctrl["folder"],
        "kind": "subset",
        "closed": ctrl["closed"],
        "cash": cash,
        "cash_src": ctrl["cash_src"],
        "symbols": len({t["symbol"] for t in trades}),
        "slices": slices,
        "g22_slices": slices,
        "trades": trades,
        "report": ctrl["report"],
        "curve": curve,
        "verdict_word": word,
        "verdict": text,
        "split_2230": {w: _metrics(_slice_rows(g2230, w), cash, curve, w) for w in ("FULL", "IS", "OOS")},
        "split_gt30": {w: _metrics(_slice_rows(g30, w), cash, curve, w) for w in ("FULL", "IS", "OOS")},
        "t_frac": 0.90,
    }


OH1786_OHONLY_SHORT = "17/8/6 overhead-only"
T70_G17_SHORT = "70/40, overhead G>=17% only"
T70_G17_BINS: list[tuple[str, float, float | None]] = [
    ("17–22%", 17.0, 22.0),
    ("22–30%", 22.0, 30.0),
    ("G > 30%", 30.0, None),
]


def _t70_g17_bin(g: float) -> str:
    if g < 22.0:
        return "17–22%"
    if g <= 30.0:
        return "22–30%"
    return "G > 30%"


def _overhead_present_book(src: dict[str, Any], ctrl: dict[str, Any]) -> dict[str, Any]:
    """Drop clear-sky from a fixed book. Keep any finite recovered G (this freeze already skips G<=17%)."""
    trades = [
        t for t in src["trades"]
        if t.get("g_pct") is not None and math.isfinite(t["g_pct"])
    ]
    cash = src["cash"]
    curve = src["curve"]
    slices = {w: _metrics(_slice_rows(trades, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    g22 = [t for t in trades if t["g_pct"] >= 22.0]
    g22_slices = {w: _metrics(_slice_rows(g22, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    cand = {
        "id": "oh17_tg08_st06_overhead_only",
        "short": OH1786_OHONLY_SHORT,
        "role": "subset of 17/8/6 (overhead present; drop clear-sky; G>17% typical)",
        "folder": src["folder"],
        "kind": "subset_oh_any",
        "closed": src["closed"],
        "cash": cash,
        "cash_src": src["cash_src"],
        "symbols": len({t["symbol"] for t in trades}),
        "slices": slices,
        "g22_slices": g22_slices,
        "trades": trades,
        "report": src.get("report", {}),
        "curve": curve,
        "overhead_band_pct": src.get("overhead_band_pct", 0.17),
        "target_pct": src.get("target_pct", 1.08),
        "stop_pct": src.get("stop_pct", 0.94),
        "stop_under_pct": src.get("stop_under_pct", 6),
        "target_gain_pct": src.get("target_gain_pct", 8),
        "t_frac": 0.90,
    }
    word, text = _verdict(cand, ctrl)
    extra = (
        " Filter of neighborhood cell oh17_tg08_st06 Closed (not recomputed). "
        "Drop no-overhead / clear-sky. Keep any constraining older zone that still entered "
        "(do not require G≥22%). Same 17/8/6 slot cash, 8% target, 6% stop. "
        "All bins = this overhead-only set. Research only. Selection bias: post-hoc filter. "
        "Not gold. Not DailyRun."
    )
    cand["verdict_word"] = word
    cand["verdict"] = text.rstrip(".") + "." + extra
    return cand


def _t70_overhead_g17_book(src: dict[str, Any], ctrl: dict[str, Any]) -> dict[str, Any]:
    """70/40 Closed, keep finite G >= 17%. Drop clear-sky and too-close overhead.

    Exits stay the 70/40 dynamic sizer already on the Closed (not fixed 17/8/6).
    """
    trades = [
        t for t in src["trades"]
        if t.get("g_pct") is not None and math.isfinite(t["g_pct"]) and t["g_pct"] >= 17.0
    ]
    cash = src["cash"]
    curve = src["curve"]
    slices = {w: _metrics(_slice_rows(trades, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    g22 = [t for t in trades if t["g_pct"] >= 22.0]
    g22_slices = {w: _metrics(_slice_rows(g22, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    cand = {
        "id": "t70_s40_g17",
        "short": T70_G17_SHORT,
        "role": "subset of 70/40 (G>=17%; drop clear-sky and G<17%; 70/40 sizer)",
        "folder": src["folder"],
        "kind": "subset_t70_g17",
        "closed": src["closed"],
        "cash": cash,
        "cash_src": src["cash_src"],
        "symbols": len({t["symbol"] for t in trades}),
        "slices": slices,
        "g22_slices": g22_slices,
        "trades": trades,
        "report": src.get("report", {}),
        "curve": curve,
        "t_frac": 0.70,
        "s_frac": 0.40,
        "g_bins": T70_G17_BINS,
    }
    word, text = _verdict(cand, ctrl)
    extra = (
        " Filter of 70/40 Closed (not recomputed). Drop no-overhead / clear-sky and G < 17%. "
        "Keep G ≥ 17%. Target and stop stay the 70/40 dynamic rule already on those fills "
        "(target = 0.70×G%; stop under trigger-day low = 0.40×target). 17% is the skip/floor, "
        "not a fixed 17/8/6 exit. Same 70/40 slot cash (not $47,500; not the 90/40 $2,362 slot). "
        "All bins = this G≥17% set. Research only. Selection bias: post-hoc filter. "
        "Not gold. Not DailyRun."
    )
    cand["verdict_word"] = word
    cand["verdict"] = text.rstrip(".") + "." + extra
    return cand


def _score_book(spec: dict[str, Any]) -> dict[str, Any]:
    folder: Path = spec["folder"]
    t_frac = float(spec.get("t_frac") or 0.90)
    closed = _latest(folder, "Closed")
    if closed is None:
        raise FileNotFoundError(f"no closed file in {folder}")
    g_lookup = None
    if spec.get("id") == "control" or spec.get("recover_g"):
        g_lookup = _fixed_g_lookup(folder, label=str(spec.get("id") or "fixed"))
    trades = _load_trades(closed, t_frac, g_lookup=g_lookup)
    cash, cash_src = _slot_cash(folder, trades)
    curve = _latest(folder, "EquityCurve")
    report = _read_report(folder)
    slices = {w: _metrics(_slice_rows(trades, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    g22 = [t for t in trades if t.get("g_pct") is not None and math.isfinite(t["g_pct"]) and t["g_pct"] >= 22.0]
    g22_slices = {w: _metrics(_slice_rows(g22, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    symbols = len({t["symbol"] for t in trades})
    return {
        **spec,
        "closed": closed,
        "cash": cash,
        "cash_src": cash_src,
        "symbols": symbols,
        "slices": slices,
        "g22_slices": g22_slices,
        "trades": trades,
        "report": report,
        "curve": curve,
    }


def _verdict(cand: dict[str, Any], ctrl: dict[str, Any]) -> tuple[str, str]:
    is_c = cand["slices"]["IS"]
    is_0 = ctrl["slices"]["IS"]
    oos_c = cand["slices"]["OOS"]
    oos_0 = ctrl["slices"]["OOS"]
    label = cand["short"]
    if not math.isfinite(is_c["ann_ror"]) or not math.isfinite(is_0["ann_ror"]):
        return "HOLD", f"{label}: HOLD — in-sample Ann ROR missing."
    d_ann = is_c["ann_ror"] - is_0["ann_ror"]
    d_pf = (is_c["pf"] - is_0["pf"]) if math.isfinite(is_c["pf"]) and math.isfinite(is_0["pf"]) else 0.0
    d_dd = (is_c["max_dd"] - is_0["max_dd"]) if math.isfinite(is_c["max_dd"]) and math.isfinite(is_0["max_dd"]) else 0.0
    n_ok = is_c["n"] >= N_FLOOR * max(1, is_0["n"])
    oos_soft = (
        math.isfinite(oos_c["ann_ror"]) and math.isfinite(oos_0["ann_ror"])
        and (oos_c["ann_ror"] + ANN_FLAT) < oos_0["ann_ror"]
    )
    if d_ann < -ANN_WORSE:
        return "DISMISS", (
            f"{label}: DISMISS — in-sample Ann ROR {_fmt(is_c['ann_ror'], 2, '%')} vs control "
            f"{_fmt(is_0['ann_ror'], 2, '%')} (Δ {_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')})."
        )
    if d_ann <= ANN_FLAT:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lift is flat "
            f"({_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')}; need > {ANN_FLAT:.2f} pts)."
        )
    if not n_ok:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted but trade count fell below "
            f"{N_FLOOR:.0%} of control ({is_c['n']} vs {is_0['n']})."
        )
    d_avg = (
        (is_c["avg"] - is_0["avg"])
        if math.isfinite(is_c["avg"]) and math.isfinite(is_0["avg"])
        else 0.0
    )
    if d_pf < -PF_WORSE or d_avg < -0.05:
        bits = []
        if d_pf < -PF_WORSE:
            bits.append(f"profit factor softened ({_delta(is_c['pf'], is_0['pf'], 2)})")
        if d_avg < -0.05:
            bits.append(f"avg % softened ({_delta(is_c['avg'], is_0['avg'], 2, '%')})")
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted but " + " and ".join(bits) + "."
        )
    if d_dd > DD_WORSE:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted but Max DD worsened "
            f"({_delta(is_c['max_dd'], is_0['max_dd'], 2, '%')})."
        )
    if oos_soft:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted "
            f"({_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')}) but out-of-sample Ann ROR "
            f"softened vs control ({_delta(oos_c['ann_ror'], oos_0['ann_ror'], 2, '%')}; report-only)."
        )
    return "KEEP", (
        f"{label}: KEEP (research only) — in-sample Ann ROR {_fmt(is_c['ann_ror'], 2, '%')} vs "
        f"{_fmt(is_0['ann_ror'], 2, '%')} (Δ {_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')}); "
        f"PF/DD/N ok; OOS not softer. Not gold. Not DailyRun."
    )


METRIC_ROWS: list[tuple[str, str, int, str]] = [
    ("n", "Trades", 0, ""),
    ("wr", "Win rate", 1, "%"),
    ("avg", "Avg %", 2, "%"),
    ("median", "Median %", 2, "%"),
    ("pf", "Profit factor", 2, ""),
    ("max_dd", "Max DD %", 2, "%"),
    ("ann_ror", "Ann ROR %", 2, "%"),
    ("avg_days", "Avg days held", 1, ""),
    ("med_days", "Median days held", 1, ""),
    ("avg_win", "Avg winner %", 2, "%"),
    ("avg_loss", "Avg loser %", 2, "%"),
    ("expect", "Expectancy %", 2, "%"),
    ("wo_max", "Avg % without max winner", 2, "%"),
    ("calmar", "Calmar", 2, ""),
    ("sharpe", "Sharpe", 2, ""),
    ("tpy", "Trades / year", 2, ""),
]


def _metric_table(books: list[dict[str, Any]], window: str) -> str:
    ctrl = books[0]["slices"][window]
    head = "".join([
        sortable_th("Metric", "text"),
        *[
            sortable_th(b["short"], "num") + sortable_th(f"{b['short']} vs control", "num")
            for b in books
        ],
    ])
    body = []
    for key, label, nd, suf in METRIC_ROWS:
        cells = [f"<td>{html_mod.escape(label)}</td>"]
        for b in books:
            v = b["slices"][window][key]
            cells.append(f"<td>{_fmt(v, nd, suf)}</td>")
            if b["id"] == "control":
                cells.append("<td>—</td>")
            else:
                cells.append(f"<td>{_delta(v, ctrl[key], nd, suf)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _headline_table(books: list[dict[str, Any]]) -> str:
    head = "".join([
        sortable_th("Arm", "text"),
        sortable_th("Role", "text"),
        sortable_th("N full", "num"),
        sortable_th("WR full", "num"),
        sortable_th("Avg % full", "num"),
        sortable_th("PF full", "num"),
        sortable_th("Max DD full", "num"),
        sortable_th("Ann ROR full", "num"),
        sortable_th("Ann ROR IS", "num"),
        sortable_th("Ann ROR OOS", "num"),
        sortable_th("G≥22% N", "num"),
        sortable_th("G≥22% Ann ROR", "num"),
        sortable_th("Verdict", "text"),
    ])
    rows = []
    for b in books:
        full, is_m, oos = b["slices"]["FULL"], b["slices"]["IS"], b["slices"]["OOS"]
        g22 = b.get("g22_slices", {}).get("FULL", {})
        verdict = "control" if b["id"] == "control" else b.get("verdict_word", "")
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(b['short'])}</td>"
            f"<td>{html_mod.escape(b['role'])}</td>"
            f"<td>{full['n']}</td>"
            f"<td>{_fmt(full['wr'], 1, '%')}</td>"
            f"<td>{_fmt(full['avg'], 2, '%')}</td>"
            f"<td>{_fmt(full['pf'], 2)}</td>"
            f"<td>{_fmt(full['max_dd'], 2, '%')}</td>"
            f"<td>{_fmt(full['ann_ror'], 2, '%')}</td>"
            f"<td>{_fmt(is_m['ann_ror'], 2, '%')}</td>"
            f"<td>{_fmt(oos['ann_ror'], 2, '%')}</td>"
            f"<td>{g22.get('n', '—')}</td>"
            f"<td>{_fmt(g22.get('ann_ror', float('nan')), 2, '%')}</td>"
            f"<td>{html_mod.escape(str(verdict))}</td>"
            "</tr>"
        )
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


FOCUS_IDS = (
    "control",
    "control_oh_g22",
    "oh17_tg08_st06_overhead_only",
    "t70_s40",
    "t70_s40_g17",
)


def _focus_slice_table(books: list[dict[str, Any]]) -> str:
    by_id = {b["id"]: b for b in books}
    focus = [by_id[i] for i in FOCUS_IDS if i in by_id]
    if len(focus) < 2:
        return ""
    return (
        "<h2>Focus slice — 70/40 G≥17% vs live, G≥22% control, 17/8/6 overhead-only, full 70/40</h2>"
        "<p class=\"muted\">Same Closed books as the headline. 70/40 G≥17% is a post-process "
        "filter (drop clear-sky and G&lt;17%; keep 70/40 dynamic target/stop). Deltas in the "
        "metric tables below are still vs full live control. OOS is report-only.</p>"
        + _headline_table(focus)
        + "<h3>Focus — full book</h3>"
        + _metric_table(focus, "FULL")
        + "<h3>Focus — in-sample</h3>"
        + _metric_table(focus, "IS")
        + "<h3>Focus — out-of-sample (report only)</h3>"
        + _metric_table(focus, "OOS")
    )


def _exit_table(trades: list[dict[str, Any]]) -> str:
    exits = Counter(t["exit"] for t in trades)
    n = len(trades) or 1
    head = (
        sortable_th("Exit", "text")
        + sortable_th("Trades", "num")
        + sortable_th("Share", "num")
    )
    rows = []
    for name, count in exits.most_common():
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{count}</td>"
            f"<td>{100.0 * count / n:.1f}%</td>"
            "</tr>"
        )
    return (
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _g_bin_metric_row(
    name: str,
    group: list[dict[str, Any]],
    cash: float,
    curve: Path | None,
    *,
    total: bool = False,
) -> str:
    m = {w: _metrics(_slice_rows(group, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    tr_cls = ' class="total-row"' if total else ""
    return (
        f"<tr{tr_cls}>"
        f"<td>{html_mod.escape(name)}</td>"
        f"<td>{m['FULL']['n']}</td>"
        f"<td>{_fmt(m['FULL']['wr'], 1, '%')}</td>"
        f"<td>{_fmt(m['FULL']['avg'], 2, '%')}</td>"
        f"<td>{_fmt(m['FULL']['ann_ror'], 2, '%')}</td>"
        f"<td>{_fmt(m['FULL']['avg_days'], 1)}</td>"
        f"<td>{m['IS']['n']}</td>"
        f"<td>{_fmt(m['IS']['wr'], 1, '%')}</td>"
        f"<td>{_fmt(m['IS']['avg'], 2, '%')}</td>"
        f"<td>{_fmt(m['IS']['ann_ror'], 2, '%')}</td>"
        f"<td>{_fmt(m['IS']['avg_days'], 1)}</td>"
        f"<td>{m['OOS']['n']}</td>"
        f"<td>{_fmt(m['OOS']['wr'], 1, '%')}</td>"
        f"<td>{_fmt(m['OOS']['avg'], 2, '%')}</td>"
        f"<td>{_fmt(m['OOS']['ann_ror'], 2, '%')}</td>"
        f"<td>{_fmt(m['OOS']['avg_days'], 1)}</td>"
        "</tr>"
    )


def _g_bin_groups(cand: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    if cand.get("kind") == "subset_t70_g17":
        by_bin: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in T70_G17_BINS}
        for t in cand["trades"]:
            by_bin[_t70_g17_bin(float(t["g_pct"]))].append(t)
        return [(name, by_bin[name]) for name, _, _ in T70_G17_BINS] + [
            (ALL_BINS_LABEL, list(cand["trades"])),
        ]
    by_bin = {name: [] for name, _, _ in G_BINS}
    for t in cand["trades"]:
        by_bin[_g_bin(t.get("g_pct"))].append(t)
    g22 = [
        t for t in cand["trades"]
        if t.get("g_pct") is not None and math.isfinite(t["g_pct"]) and t["g_pct"] >= 22.0
    ]
    return (
        [(name, by_bin[name]) for name, _, _ in G_BINS]
        + [("G >= 22%", g22), (ALL_BINS_LABEL, list(cand["trades"]))]
    )


def _g_bucket_table(cand: dict[str, Any]) -> str:
    cash = cand["cash"]
    curve = cand["curve"]
    groups = _g_bin_groups(cand)
    display = []
    for name, group in groups:
        label = "G ≥ 22% (all far)" if name == "G >= 22%" else name
        display.append((label, group, name == ALL_BINS_LABEL))
    head = "".join([
        sortable_th("Overhead G bin", "text"),
        sortable_th("N full", "num"),
        sortable_th("WR full", "num"),
        sortable_th("Avg % full", "num"),
        sortable_th("Ann ROR full", "num"),
        sortable_th("Avg days full", "num"),
        sortable_th("N IS", "num"),
        sortable_th("WR IS", "num"),
        sortable_th("Avg % IS", "num"),
        sortable_th("Ann ROR IS", "num"),
        sortable_th("Avg days IS", "num"),
        sortable_th("N OOS", "num"),
        sortable_th("WR OOS", "num"),
        sortable_th("Avg % OOS", "num"),
        sortable_th("Ann ROR OOS", "num"),
        sortable_th("Avg days OOS", "num"),
    ])
    rows = [
        _g_bin_metric_row(name, group, cash, curve, total=total)
        for name, group, total in display
    ]
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _write_baseline(books: list[dict[str, Any]], reuse_note: str) -> None:
    path = OUT_DIR / "BASELINE.md"
    ctrl = books[0]
    cands = books[1:]
    lines = [
        "# WPBR dynamic overhead fraction grid",
        "",
        "Pivot Break and Retest (WPBR). Research only. Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Verdict",
        "",
    ]
    for c in cands:
        lines.append(f"- {c['verdict']}")
    lines += [
        "",
        "Selection bias label: this is a **research candidate grid**. Knobs and fraction arms "
        "were frozen before reading OOS. KEEP/HOLD/DISMISS is on in-sample quality vs control only. "
        "Out of sample is report-only — do not retune on OOS. Do not adopt into DailyRun from this stamp alone.",
        "",
        "## Freeze",
        "",
        "- Control (live 2026-10-02 freeze, stamp 261002051403): `wpbr_overhead_band_pct=0.22`, "
        "`target_pct=1.20`, `stop_pct=0.92`, `wpbr_dynamic_overhead=false`, growth filter off, "
        "`min_history_bars=0`, full warehouse.",
        f"- Control closed file reused (not recomputed): `{ctrl['closed'].relative_to(ROOT).as_posix()}`. "
        f"N={ctrl['slices']['FULL']['n']}, symbols={ctrl['symbols']}.",
        "- Dynamic candidates: `wpbr_dynamic_overhead=true`, `wpbr_overhead_band_pct=0` (hard ≤22% skip off). "
        "Clear sky only when there is truly no older overhead zone → fixed 20% target / 8% stop. "
        "When overhead exists at any gap G% (including G≥22%): target = T_frac×G, "
        "stop_under = S_frac×target (engine `stop_pct` path uses trigger-day low × (1 − stop_under)). "
        "Arms: A 90/40, B 80/40, C 70/40.",
        f"- 90/40 reuse: {reuse_note}",
    ]
    for b in books:
        if b.get("kind") != "fixed":
            continue
        band = float(b.get("overhead_band_pct") or 0) * 100.0
        tg = int(b.get("target_gain_pct") or round((float(b.get("target_pct") or 1.0) - 1.0) * 100))
        st = int(b.get("stop_under_pct") or round((1.0 - float(b.get("stop_pct") or 1.0)) * 100))
        closed_rel = b["closed"].relative_to(ROOT).as_posix()
        lines.append(
            f"- Fixed package `{b['id']}` ({b['short']}): NOT dynamic. "
            f"`wpbr_dynamic_overhead=false`, `wpbr_overhead_band_pct={float(b['overhead_band_pct']):.2f}` "
            f"(skip when G ≤ {band:.0f}%), `target_pct={float(b['target_pct']):.2f}` ({tg}% gain), "
            f"`stop_pct={float(b['stop_pct']):.2f}` ({st}% under trigger-day low), growth off, "
            f"`min_history_bars=0`, full warehouse. Closed from `{closed_rel}`."
        )
    lines += [
        "- Exit identity: whole position at target or stop (no partial exit strategy). "
        "`stop_loss_based=trigger_low`, `stop_pct_is_multiplier=true`.",
        "- Slot cash: each arm’s own `capacity_brt_cash` (trade dollars), not $47,500.",
        "- Ann ROR: house formula `compare_format.ann_ror_from_closed` with that slot cash. "
        "Reported for FULL, IS (`DATE_OPENED` < 2024-01-01), and OOS (`DATE_OPENED` ≥ 2024-01-01).",
        "- Shared unchanged: weekly WPBR zones, band 1.5%, strong pivot either 3/10%, breakout confirm 3%, "
        "retest window 2 days, second chance after win on, indicators recorded not a buy gate, mcap off, "
        "SPY 1y gate off, `sheet_no_entry_same_bar_after_exit=false`.",
        "- Universe: every CSV under `data/newdata/data`.",
        "- Engine flag default remains off so DailyRun / `run_wpbr.bat` are untouched.",
        "- OVERHEAD_GAP_PCT: engine `_brt_closed_from_open` now copies `wpbr_overhead_gap_pct` "
        "(fixed for B/C runs). Reused 90/40 may still recover G from target identity when blank.",
        "- Control / fixed-package G bins: those closed books lacked OVERHEAD_GAP_PCT. Recovered via "
        "join to 80/40 `OVERHEAD_GAP_PCT` on (symbol, entry date, WPBR_ZONE_ID), zone-id fallback, then "
        "`prior_overhead_nearest_gap` on each arm’s checkpoint breakout/retest inventory. "
        "Each arm’s Ann ROR uses that arm’s slot cash. Bin tables include avg days held "
        "(FULL / IS / OOS) for control, fixed packages, and all fraction arms. Each G-bin table "
        f"ends with a pinned `{ALL_BINS_LABEL}` total-row = the arm’s full closed book "
        "(union of mutually exclusive bins; ignore which G band).",
        "- Control overhead G≥22% only: filter of stamp 261002051403 closed book — KEEP when "
        "recovered G is finite and G ≥ 22% (older zone present); DROP no-overhead / clear-sky "
        "and leftover G < 22% noise. Same slot cash, target, and stop as live control. Not a "
        "new engine run. Research subset; not DailyRun.",
        "- 17/8/6 overhead-only: filter of neighborhood `oh17_tg08_st06` Closed — KEEP when "
        "recovered G is finite (older zone present); DROP no-overhead / clear-sky. Same "
        "17/8/6 slot cash (`capacity_brt_cash`), 8% target, 6% stop. Not a new engine run. "
        "Research subset; not DailyRun.",
        "- 70/40 overhead G≥17% only: filter of 70/40 Closed — KEEP when recovered G is finite "
        "and G ≥ 17%; DROP clear-sky and G < 17%. Exits stay 70/40 dynamic (target 0.70×G, "
        "stop_under 0.40×target). 17% is skip/floor, not fixed 17/8/6. Same 70/40 slot cash. "
        "G bins on that slice: 17–22, 22–30, G>30; All bins = this filtered set. Not a new "
        "engine run. Research subset; not DailyRun.",
        "- Selection bias: fixed packages 16/8/3, 16/8/4, 16/8/5, 17/7/6, then 16/7/3–5 and "
        "17/7/2–5 were added to this stamp after the dynamic grid was scored (Paul ask). "
        "Target 7 is outside the neighborhood tg 8–12 grid and was scored here as extra fixed "
        "cells. Fixed 17/8/6 Closed is the neighborhood cell (in the original 125). "
        "The G≥22% overhead-only slice is a post-hoc filter of control. "
        "The 17/8/6 overhead-only slice is a post-hoc filter of that neighborhood Closed "
        "(drop clear-sky; keep finite G; not G≥22% required). "
        "The 70/40 G≥17% slice is a post-hoc filter of the 70/40 Closed (drop clear-sky and "
        "G<17%; keep 70/40 sizer). "
        "KEEP/HOLD/DISMISS still on IS quality vs full control only; OOS report-only. "
        "HOLD if Ann ROR is up but avg or profit factor is worse.",
        "",
        "## Slot cash",
        "",
        "| Arm | Slot cash | Source |",
        "| --- | --- | --- |",
    ]
    for b in books:
        lines.append(f"| {b['short']} | ${b['cash']:,.2f} | {b['cash_src']} |")
    lines += [
        "",
        "## Headline (FULL / IS Ann ROR / OOS Ann ROR)",
        "",
        "| Arm | N | WR | Avg % | PF | Max DD | Ann ROR full | Ann ROR IS | Ann ROR OOS | G≥22% N | G≥22% Ann ROR | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in books:
        f, i, o = b["slices"]["FULL"], b["slices"]["IS"], b["slices"]["OOS"]
        g22 = b.get("g22_slices", {}).get("FULL", {})
        verdict = "control" if b["id"] == "control" else b.get("verdict_word", "")
        g22_n = str(g22.get("n", "—"))
        g22_ann = _fmt(g22.get("ann_ror", float("nan")), 2, "%")
        lines.append(
            f"| {b['short']} | {f['n']} | {_fmt(f['wr'], 1, '%')} | {_fmt(f['avg'], 2, '%')} | "
            f"{_fmt(f['pf'], 2)} | {_fmt(f['max_dd'], 2, '%')} | {_fmt(f['ann_ror'], 2, '%')} | "
            f"{_fmt(i['ann_ror'], 2, '%')} | {_fmt(o['ann_ror'], 2, '%')} | {g22_n} | {g22_ann} | {verdict} |"
        )
    for c in cands:
        lines += [
            "",
            f"## Closed — {c['short']}",
            "",
            f"`{c['closed'].relative_to(ROOT).as_posix()}`",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_html(books: list[dict[str, Any]], reuse_note: str) -> Path:
    path = OUT_DIR / "compare.html"
    ctrl = books[0]
    cands = books[1:]
    css = SORTABLE_TH_CSS + RESPONSIVE_TABLE_CSS + """
    body{font-family:Segoe UI,system-ui,sans-serif;margin:1.2rem;max-width:1200px;line-height:1.45;color:#1a1a1a}
    h1{font-size:1.45rem;margin:0 0 .4rem} h2{font-size:1.15rem;margin:1.4rem 0 .5rem}
    .callout{background:#f4f7fb;border-left:4px solid #3b6ea5;padding:.75rem 1rem;margin:1rem 0}
    .verdict{background:#fff8e8;border-left:4px solid #c48a00;padding:.75rem 1rem;margin:1rem 0}
    .muted{color:#555;font-size:.92rem} code{font-size:.9em}
    """
    verdict_html = "<br/>".join(html_mod.escape(c["verdict"]) for c in cands)
    g_sections = []
    # Control first so Paul can compare side-by-side with candidates.
    g_sections.append(
        f"<h2>Overhead G bins — {html_mod.escape(ctrl['short'])}</h2>"
        f"<p class=\"muted\">Slot cash ${ctrl['cash']:,.2f} (control). Live skip when G ≤ 22%, so "
        f"mass should sit in <strong>no overhead</strong> / <strong>G ≥ 22%</strong>. "
        f"G recovered from candidate OVERHEAD_GAP_PCT join + checkpoint zone inventory "
        f"(control closed lacked OVERHEAD_GAP_PCT). Includes avg days held, aggregate "
        f"<strong>G ≥ 22%</strong>, and pinned <strong>{html_mod.escape(ALL_BINS_LABEL)}</strong> "
        f"(full closed book if you trade every bin).</p>"
        f"{_g_bucket_table(ctrl)}"
    )
    for c in cands:
        if c.get("kind") == "subset":
            g_note = (
                f"Slot cash ${c['cash']:,.2f}. Filter of live control: keep only trades with a "
                f"constraining older overhead zone and G ≥ 22%. Drop clear-sky. Same 20% target / "
                f"8% stop. Split 22–30% vs G&gt;30% below. Research subset, not a new freeze."
            )
        elif c.get("kind") == "subset_oh_any":
            g_note = (
                f"Slot cash ${c['cash']:,.2f} (17/8/6 engine slot, not $47,500). Filter of fixed "
                f"17/8/6: keep only trades with a constraining older overhead zone (finite recovered "
                f"G). Drop clear-sky. Do not require G≥22%; 17/8/6 already skips G≤17%. "
                f"Pinned <strong>{html_mod.escape(ALL_BINS_LABEL)}</strong> is this overhead-only "
                f"set. Research subset, not DailyRun."
            )
        elif c.get("kind") == "subset_t70_g17":
            g_note = (
                f"Slot cash ${c['cash']:,.2f} (70/40 engine slot, not $47,500 and not the 90/40 "
                f"$2,362 slot). Filter of 70/40 Closed: keep G ≥ 17% (older zone present). Drop "
                f"clear-sky and G &lt; 17%. Target/stop stay 70/40 dynamic (0.70×G / 0.40×target). "
                f"Bins are 17–22, 22–30, and G&gt;30. Pinned <strong>"
                f"{html_mod.escape(ALL_BINS_LABEL)}</strong> is this G≥17% set. Research subset, "
                f"not DailyRun."
            )
        elif c.get("kind") == "fixed":
            band = float(c.get("overhead_band_pct") or 0.16) * 100.0
            tg = int(c.get("target_gain_pct") or 8)
            st = int(c.get("stop_under_pct") or 3)
            g_note = (
                f"Slot cash ${c['cash']:,.2f}. Fixed package (not dynamic fractions): skip when G ≤ "
                f"{band:.0f}%, target {tg}%, stop {st}% under trigger-day low. G recovered like control "
                f"(80/40 join + checkpoint). Includes avg days held, aggregate "
                f"<strong>G ≥ 22%</strong>, and pinned <strong>{html_mod.escape(ALL_BINS_LABEL)}</strong>."
            )
        else:
            g_note = (
                f"Slot cash ${c['cash']:,.2f}. Includes avg days held, aggregate "
                f"<strong>G ≥ 22%</strong>, and pinned <strong>{html_mod.escape(ALL_BINS_LABEL)}</strong>. "
                f"Fractions applied for every overhead G (not only G&lt;22%)."
            )
        g_sections.append(
            f"<h2>Overhead G bins — {html_mod.escape(c['short'])}</h2>"
            f"<p class=\"muted\">{g_note}</p>"
            f"{_g_bucket_table(c)}"
        )
    exit_sections = [
        f"<h2>Exit mix — control</h2>{_exit_table(ctrl['trades'])}",
    ]
    for c in cands:
        exit_sections.append(f"<h2>Exit mix — {html_mod.escape(c['short'])}</h2>{_exit_table(c['trades'])}")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR dynamic overhead frac grid</title>
<style>{css}</style>
</head><body>
<h1>WPBR dynamic overhead fraction grid (research)</h1>
<p class="muted">Stamp {STAMP}. Control reused from live freeze 261002051403.
Arms A/B/C: 90/40, 80/40, 70/40 with fractions on every overhead G including ≥22%.
Plus fixed packages 16/8/3, 16/8/4, 16/8/5, 16/7/3–5, 17/7/2–6, and 17/8/6
(neighborhood-style; not fraction sizing; target 7 is outside the original 125-cell grid).
17/8/6 also appears as an overhead-only filter (drop clear-sky). 70/40 also appears as a
G≥17% overhead-only filter (drop clear-sky and G&lt;17%; keep 70/40 sizer). Not gold. Not DailyRun.</p>

<div class="callout">
<strong>What you asked</strong>
<blockquote>{html_mod.escape(REQUEST_QUOTE)}</blockquote>
<strong>In plain English</strong>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="verdict">
<strong>Verdicts (IS quality vs control; OOS report-only):</strong><br/>
{verdict_html}<br/><br/>
<span class="muted">{html_mod.escape(reuse_note)}</span>
</div>

<p>{SWIPE_NOTE_HTML} Click column headers to sort.</p>

<h2>Headline</h2>
{_headline_table(books)}

{_focus_slice_table(books)}

<h2>Full book</h2>
{_metric_table(books, "FULL")}

<h2>In-sample (entry before 2024-01-01)</h2>
{_metric_table(books, "IS")}

<h2>Out-of-sample (entry on/after 2024-01-01) — report only</h2>
{_metric_table(books, "OOS")}

{''.join(g_sections)}

{''.join(exit_sections)}

<p class="muted">Annualized rate of return (Ann ROR) uses house formula with each arm’s own slot cash.
Control closed: <code>{html_mod.escape(ctrl['closed'].relative_to(ROOT).as_posix())}</code>
(N={ctrl['slices']['FULL']['n']}, slot ${ctrl['cash']:,.2f}).</p>

{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")
    return path


def _write_summary_csv(books: list[dict[str, Any]]) -> Path:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm_id", "label", "slice", "n", "win_rate", "avg_pct", "median_pct", "profit_factor",
        "max_dd_pct", "ann_ror_pct", "avg_days", "calmar", "sharpe", "slot_cash", "verdict",
        "source_closed", "g_bin",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b in books:
            for sl in ("FULL", "IS", "OOS"):
                m = b["slices"][sl]
                w.writerow({
                    "arm_id": b["id"],
                    "label": b["short"],
                    "slice": sl,
                    "n": m["n"],
                    "win_rate": f"{m['wr']:.4f}" if math.isfinite(m["wr"]) else "",
                    "avg_pct": f"{m['avg']:.4f}" if math.isfinite(m["avg"]) else "",
                    "median_pct": f"{m['median']:.4f}" if math.isfinite(m["median"]) else "",
                    "profit_factor": f"{m['pf']:.4f}" if math.isfinite(m["pf"]) else "",
                    "max_dd_pct": f"{m['max_dd']:.4f}" if math.isfinite(m["max_dd"]) else "",
                    "ann_ror_pct": f"{m['ann_ror']:.4f}" if math.isfinite(m["ann_ror"]) else "",
                    "avg_days": f"{m['avg_days']:.4f}" if math.isfinite(m["avg_days"]) else "",
                    "calmar": f"{m['calmar']:.4f}" if math.isfinite(m["calmar"]) else "",
                    "sharpe": f"{m['sharpe']:.4f}" if math.isfinite(m["sharpe"]) else "",
                    "slot_cash": f"{b['cash']:.6f}",
                    "verdict": "control" if b["id"] == "control" else b.get("verdict_word", ""),
                    "source_closed": str(b["closed"].relative_to(ROOT)).replace("\\", "/"),
                    "g_bin": "",
                })
            for name, group in _g_bin_groups(b):
                for sl in ("FULL", "IS", "OOS"):
                    m = _metrics(_slice_rows(group, sl), b["cash"], b["curve"], sl)
                    w.writerow({
                        "arm_id": f"{b['id']}_gbin",
                        "label": b["short"],
                        "slice": sl,
                        "n": m["n"],
                        "win_rate": f"{m['wr']:.4f}" if math.isfinite(m["wr"]) else "",
                        "avg_pct": f"{m['avg']:.4f}" if math.isfinite(m["avg"]) else "",
                        "median_pct": f"{m['median']:.4f}" if math.isfinite(m["median"]) else "",
                        "profit_factor": f"{m['pf']:.4f}" if math.isfinite(m["pf"]) else "",
                        "max_dd_pct": f"{m['max_dd']:.4f}" if math.isfinite(m["max_dd"]) else "",
                        "ann_ror_pct": f"{m['ann_ror']:.4f}" if math.isfinite(m["ann_ror"]) else "",
                        "avg_days": f"{m['avg_days']:.4f}" if math.isfinite(m["avg_days"]) else "",
                        "calmar": f"{m['calmar']:.4f}" if math.isfinite(m["calmar"]) else "",
                        "sharpe": f"{m['sharpe']:.4f}" if math.isfinite(m["sharpe"]) else "",
                        "slot_cash": f"{b['cash']:.6f}",
                        "verdict": "control" if b["id"] == "control" else b.get("verdict_word", ""),
                        "source_closed": str(b["closed"].relative_to(ROOT)).replace("\\", "/"),
                        "g_bin": name,
                    })
    return path


def _run_arm(arm: dict[str, Any], reuse_90: bool) -> Path:
    out = RUNS_DIR / arm["folder_name"]
    out.mkdir(parents=True, exist_ok=True)

    if arm["reuse_prior"] and reuse_90 and _closed_ready(PRIOR_90_DIR):
        # Symlink/copy pointer: score from prior folder directly
        print(f"[reuse] {arm['id']} -> {PRIOR_90_DIR}", flush=True)
        return PRIOR_90_DIR

    if _closed_ready(out):
        report = _read_report(out)
        dyn = str(report.get("wpbr_dynamic_overhead") or "").strip().lower()
        tf = _f(report.get("wpbr_dyn_oh_target_frac"))
        want = float(arm["t_frac"])
        if dyn in {"true", "1", "yes", "on"} and (not math.isfinite(tf) or abs(tf - want) < 1e-6):
            print(f"[reuse] {arm['id']} closed already ready in {out}", flush=True)
            return out

    # Retry a few times if DuckDB lock or transient engine failure.
    last_log = RUNS_DIR / f"{arm['folder_name']}.log"
    for attempt in range(1, 4):
        use_duck = _wait_for_slot(arm["id"])
        # Always prefer CSV while neighborhood is still active — safer on this box.
        # Use DuckDB only when neighborhood is idle (0 parents) and DB unlocked.
        if _neighborhood_parent_count() > 0:
            use_duck = False
        log_path = RUNS_DIR / f"{arm['folder_name']}.log"
        last_log = log_path
        cmd = _cmd(out, float(arm["t_frac"]), float(arm["s_frac"]), use_duckdb=use_duck)
        (out / "run_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
        mode = "duckdb" if use_duck else "csv"
        print(
            f"[start] {arm['id']} attempt={attempt} mode={mode} workers={WORKERS} log={log_path}",
            flush=True,
        )
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            time.sleep(45)
            print(f"[wait] {arm['id']} pid={proc.pid} running…", flush=True)
        if proc.returncode == 0 and _closed_ready(out):
            return out
        print(
            f"[retry] {arm['id']} rc={proc.returncode} closed_ready={_closed_ready(out)}; "
            f"see {log_path}",
            flush=True,
        )
        time.sleep(90)
    raise SystemExit(f"{arm['id']} engine failed after retries; see {last_log}")


def _headline_row(b: dict[str, Any]) -> str:
    full, is_m, oos = b["slices"]["FULL"], b["slices"]["IS"], b["slices"]["OOS"]
    g22 = b.get("g22_slices", {}).get("FULL", {})
    verdict = "control" if b["id"] == "control" else b.get("verdict_word", "")
    return (
        "<tr>"
        f"<td>{html_mod.escape(b['short'])}</td>"
        f"<td>{html_mod.escape(b['role'])}</td>"
        f"<td>{full['n']}</td>"
        f"<td>{_fmt(full['wr'], 1, '%')}</td>"
        f"<td>{_fmt(full['avg'], 2, '%')}</td>"
        f"<td>{_fmt(full['pf'], 2)}</td>"
        f"<td>{_fmt(full['max_dd'], 2, '%')}</td>"
        f"<td>{_fmt(full['ann_ror'], 2, '%')}</td>"
        f"<td>{_fmt(is_m['ann_ror'], 2, '%')}</td>"
        f"<td>{_fmt(oos['ann_ror'], 2, '%')}</td>"
        f"<td>{g22.get('n', '—')}</td>"
        f"<td>{_fmt(g22.get('ann_ror', float('nan')), 2, '%')}</td>"
        f"<td>{html_mod.escape(str(verdict))}</td>"
        "</tr>"
    )


def _metric_pair_tds(book: dict[str, Any], window: str, key: str, nd: int, suf: str, ctrl_m: dict[str, Any]) -> str:
    v = book["slices"][window][key]
    return f"<td>{_fmt(v, nd, suf)}</td><td>{_delta(v, ctrl_m[key], nd, suf)}</td>"


def _inject_metric_table_arm(table_html: str, book: dict[str, Any], window: str, ctrl: dict[str, Any]) -> str:
    if CONTROL_G22_SHORT in table_html:
        return table_html
    extra_th = (
        sortable_th(book["short"], "num")
        + sortable_th(f"{book['short']} vs control", "num")
    )
    needle = (
        'role="columnheader" aria-sort="none">Control 22/20/8 vs control'
        '<span class="sort-ind"></span></th>'
    )
    i = table_html.find(needle)
    if i < 0:
        return table_html
    j = i + len(needle)
    table_html = table_html[:j] + extra_th + table_html[j:]
    ctrl_m = ctrl["slices"][window]
    out = []
    last = 0
    for key, label, nd, suf in METRIC_ROWS:
        mark = f"<tr><td>{html_mod.escape(label)}</td>"
        k = table_html.find(mark, last)
        if k < 0:
            continue
        p = k + len(mark)
        for _ in range(2):
            p = table_html.find("</td>", p)
            if p < 0:
                break
            p += 5
        if p < 0:
            continue
        extra = _metric_pair_tds(book, window, key, nd, suf, ctrl_m)
        out.append(table_html[last:p] + extra)
        last = p
    out.append(table_html[last:])
    return "".join(out)


def _patch_compare_html(ctrl: dict[str, Any], g22_arm: dict[str, Any]) -> Path:
    path = OUT_DIR / "compare.html"
    html = path.read_text(encoding="utf-8")
    row = _headline_row(g22_arm)
    if CONTROL_G22_SHORT not in html:
        mark = "<tr><td>Control 22/20/8</td>"
        i = html.find(mark)
        if i >= 0:
            j = html.find("</tr>", i) + 5
            html = html[:j] + row + html[j:]
    else:
        mark = f"<tr><td>{html_mod.escape(CONTROL_G22_SHORT)}</td>"
        alt = f"<tr><td>{CONTROL_G22_SHORT}</td>"
        i = html.find(mark)
        if i < 0:
            i = html.find(alt)
        if i >= 0:
            j = html.find("</tr>", i) + 5
            html = html[:i] + row + html[j:]

    windows = [
        ("Full book", "FULL"),
        ("In-sample (entry before 2024-01-01)", "IS"),
        ("Out-of-sample (entry on/after 2024-01-01) — report only", "OOS"),
    ]
    for h2, window in windows:
        start = html.find(f"<h2>{h2}</h2>")
        if start < 0:
            continue
        wrap = html.find('<div class="table-wrap">', start)
        end = html.find("</table></div>", wrap)
        if wrap < 0 or end < 0:
            continue
        end += len("</table></div>")
        patched = _inject_metric_table_arm(html[wrap:end], g22_arm, window, ctrl)
        html = html[:wrap] + patched + html[end:]

    ask_extra = (
        " what are the results if we run control, but ONLY take trades where there IS "
        "overhead, but it is 22% or greater away? (i.e. we don&#x27;t take the trades "
        "where there is NO overhead bin)"
    )
    if "ONLY take trades where there IS" not in html:
        html = html.replace("</blockquote>", ask_extra + "</blockquote>", 1)
    layman_extra = (
        " Separate named slice: live control but only buys that have an older overhead "
        "zone AND gap G ≥ 22% (drop clear-sky / no-overhead). Same 20% target and 8% stop "
        "— a filter of the live book, not a new engine freeze."
    )
    if "Separate named slice" not in html:
        html = html.replace(
            "Research only; DailyRun unchanged.</p>",
            layman_extra + " Research only; DailyRun unchanged.</p>",
            1,
        )
    verd = html_mod.escape(g22_arm["verdict"]) + "<br/>"
    verd_block = html.split('<div class="verdict">', 1)[-1][:1200]
    if CONTROL_G22_SHORT not in verd_block:
        html = html.replace(
            "<strong>Verdicts (IS quality vs control; OOS report-only):</strong><br/>",
            "<strong>Verdicts (IS quality vs control; OOS report-only):</strong><br/>" + verd,
            1,
        )

    split_h2 = f"<h2>Overhead G bins — {html_mod.escape(CONTROL_G22_SHORT)}</h2>"
    split_body = (
        f"{split_h2}"
        f"<p class=\"muted\">Slot cash ${g22_arm['cash']:,.2f}. Filter of live control: "
        f"keep only trades with a constraining older overhead zone and G ≥ 22%. Drop "
        f"clear-sky. Same 20% target / 8% stop. 22–30% vs G&gt;30% split is in this table. "
        f"Research subset, not a new freeze.</p>"
        f"{_g_bucket_table(g22_arm)}"
        f"<h2>Exit mix — {html_mod.escape(CONTROL_G22_SHORT)}</h2>"
        f"{_exit_table(g22_arm['trades'])}"
    )
    if split_h2 not in html:
        anchor = "<h2>Overhead G bins — 16/8/3</h2>"
        if anchor in html:
            html = html.replace(anchor, split_body + anchor, 1)
        else:
            html = html.replace("<h2>Exit mix — control</h2>", split_body + "<h2>Exit mix — control</h2>", 1)

    path.write_text(html, encoding="utf-8")
    return path


def _csv_arm_rows(b: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    closed = str(b["closed"].relative_to(ROOT)).replace("\\", "/")
    for sl in ("FULL", "IS", "OOS"):
        m = b["slices"][sl]
        rows.append({
            "arm_id": b["id"],
            "label": b["short"],
            "slice": sl,
            "n": m["n"],
            "win_rate": f"{m['wr']:.4f}" if math.isfinite(m["wr"]) else "",
            "avg_pct": f"{m['avg']:.4f}" if math.isfinite(m["avg"]) else "",
            "median_pct": f"{m['median']:.4f}" if math.isfinite(m["median"]) else "",
            "profit_factor": f"{m['pf']:.4f}" if math.isfinite(m["pf"]) else "",
            "max_dd_pct": f"{m['max_dd']:.4f}" if math.isfinite(m["max_dd"]) else "",
            "ann_ror_pct": f"{m['ann_ror']:.4f}" if math.isfinite(m["ann_ror"]) else "",
            "avg_days": f"{m['avg_days']:.4f}" if math.isfinite(m["avg_days"]) else "",
            "calmar": f"{m['calmar']:.4f}" if math.isfinite(m["calmar"]) else "",
            "sharpe": f"{m['sharpe']:.4f}" if math.isfinite(m["sharpe"]) else "",
            "slot_cash": f"{b['cash']:.6f}",
            "verdict": b.get("verdict_word", "HOLD"),
            "source_closed": closed,
            "g_bin": "",
        })
    for name, group in _g_bin_groups(b):
        for sl in ("FULL", "IS", "OOS"):
            m = _metrics(_slice_rows(group, sl), b["cash"], b["curve"], sl)
            rows.append({
                "arm_id": f"{b['id']}_gbin",
                "label": b["short"],
                "slice": sl,
                "n": m["n"],
                "win_rate": f"{m['wr']:.4f}" if math.isfinite(m["wr"]) else "",
                "avg_pct": f"{m['avg']:.4f}" if math.isfinite(m["avg"]) else "",
                "median_pct": f"{m['median']:.4f}" if math.isfinite(m["median"]) else "",
                "profit_factor": f"{m['pf']:.4f}" if math.isfinite(m["pf"]) else "",
                "max_dd_pct": f"{m['max_dd']:.4f}" if math.isfinite(m["max_dd"]) else "",
                "ann_ror_pct": f"{m['ann_ror']:.4f}" if math.isfinite(m["ann_ror"]) else "",
                "avg_days": f"{m['avg_days']:.4f}" if math.isfinite(m["avg_days"]) else "",
                "calmar": f"{m['calmar']:.4f}" if math.isfinite(m["calmar"]) else "",
                "sharpe": f"{m['sharpe']:.4f}" if math.isfinite(m["sharpe"]) else "",
                "slot_cash": f"{b['cash']:.6f}",
                "verdict": b.get("verdict_word", "HOLD"),
                "source_closed": closed,
                "g_bin": name,
            })
    return rows


def _patch_summary_csv(g22_arm: dict[str, Any]) -> None:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm_id", "label", "slice", "n", "win_rate", "avg_pct", "median_pct", "profit_factor",
        "max_dd_pct", "ann_ror_pct", "avg_days", "calmar", "sharpe", "slot_cash", "verdict",
        "source_closed", "g_bin",
    ]
    existing = []
    if path.is_file():
        with path.open(newline="", encoding="utf-8") as f:
            existing = [
                r for r in csv.DictReader(f)
                if r.get("arm_id") not in {"control_oh_g22", "control_oh_g22_gbin"}
            ]
    new_rows = _csv_arm_rows(g22_arm)
    out: list[dict[str, Any]] = []
    inserted = False
    control_slice_count = 0
    for r in existing:
        out.append(r)
        if r.get("arm_id") == "control" and not r.get("g_bin"):
            control_slice_count += 1
            if control_slice_count == 3 and not inserted:
                out.extend(new_rows)
                inserted = True
    if not inserted:
        out = new_rows + existing
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in fields})


def _patch_baseline_md(ctrl: dict[str, Any], g22_arm: dict[str, Any]) -> None:
    path = OUT_DIR / "BASELINE.md"
    text = path.read_text(encoding="utf-8")
    ask = (
        "what are the results if we run control, but ONLY take trades where there IS "
        "overhead, but it is 22% or greater away? (i.e. we don't take the trades "
        "where there is NO overhead bin)"
    )
    if "ONLY take trades where there IS overhead" not in text:
        text = text.replace(
            "## In plain English",
            ask + "\n\n## In plain English",
            1,
        )
    layman = (
        "Separate named slice: live control but only buys that have an older overhead "
        "zone AND gap G ≥ 22% (drop clear-sky / no-overhead). Same 20% target and 8% stop "
        "— a filter of the live book, not a new engine freeze. "
    )
    if "Separate named slice" not in text:
        text = text.replace(
            "Research only; DailyRun unchanged.",
            layman + "Research only; DailyRun unchanged.",
            1,
        )
    verd_sec = text.split("## Verdict", 1)[-1][:1500]
    if CONTROL_G22_SHORT not in verd_sec:
        text = text.replace(
            "## Verdict\n\n",
            f"## Verdict\n\n- {g22_arm['verdict']}\n",
            1,
        )
    f, i, o = g22_arm["slices"]["FULL"], g22_arm["slices"]["IS"], g22_arm["slices"]["OOS"]
    md_row = (
        f"| {CONTROL_G22_SHORT} | {f['n']} | {_fmt(f['wr'], 1, '%')} | {_fmt(f['avg'], 2, '%')} | "
        f"{_fmt(f['pf'], 2)} | {_fmt(f['max_dd'], 2, '%')} | {_fmt(f['ann_ror'], 2, '%')} | "
        f"{_fmt(i['ann_ror'], 2, '%')} | {_fmt(o['ann_ror'], 2, '%')} | {f['n']} | "
        f"{_fmt(f['ann_ror'], 2, '%')} | {g22_arm['verdict_word']} |"
    )
    head = text.split("## Headline", 1)[-1][:2500]
    if CONTROL_G22_SHORT not in head:
        idx = text.find("| Control 22/20/8 |")
        if idx >= 0:
            nl = text.find("\n", idx)
            text = text[:nl + 1] + md_row + "\n" + text[nl + 1:]
    freeze = (
        "- Control overhead G≥22% only: filter of stamp 261002051403 closed book — KEEP when "
        "recovered G is finite and G ≥ 22% (older zone present); DROP no-overhead / clear-sky "
        "and leftover G < 22% noise. Same slot cash, target, and stop as live control. Not a "
        "new engine run. Research subset; not DailyRun.\n"
    )
    if "Control overhead G≥22% only" not in text:
        text = text.replace("## Slot cash", freeze + "\n## Slot cash", 1)
    cash_row = f"| {CONTROL_G22_SHORT} | ${g22_arm['cash']:,.2f} | {g22_arm['cash_src']} |"
    slot = text.split("## Slot cash", 1)[-1][:900]
    if CONTROL_G22_SHORT not in slot:
        old = f"| Control 22/20/8 | ${ctrl['cash']:,.2f} |"
        if old in text:
            text = text.replace(old, old + "\n" + cash_row, 1)
        else:
            needle = "| Control 22/20/8 |"
            idx = text.find(needle)
            if idx >= 0:
                nl = text.find("\n", idx)
                text = text[:nl + 1] + cash_row + "\n" + text[nl + 1:]
    path.write_text(text, encoding="utf-8")


def _merge_control_g22() -> Path:
    ctrl = _score_book({
        "id": "control",
        "short": "Control 22/20/8",
        "role": "live freeze (reused)",
        "folder": CONTROL_DIR,
        "t_frac": 0.90,
        "kind": "control",
    })
    g22_arm = _control_oh_g22_book(ctrl)
    bins = Counter(_g_bin(t.get("g_pct")) for t in ctrl["trades"])
    print(f"[verify] control N={ctrl['slices']['FULL']['n']} bins={dict(bins)}", flush=True)
    print(
        f"[verify] subset N={g22_arm['slices']['FULL']['n']} WR={_fmt(g22_arm['slices']['FULL']['wr'], 1, '%')} "
        f"avg={_fmt(g22_arm['slices']['FULL']['avg'], 2, '%')} "
        f"AnnROR full/IS/OOS={_fmt(g22_arm['slices']['FULL']['ann_ror'], 2, '%')}/"
        f"{_fmt(g22_arm['slices']['IS']['ann_ror'], 2, '%')}/"
        f"{_fmt(g22_arm['slices']['OOS']['ann_ror'], 2, '%')} "
        f"days={_fmt(g22_arm['slices']['FULL']['avg_days'], 1)} "
        f"PF={_fmt(g22_arm['slices']['FULL']['pf'], 2)}",
        flush=True,
    )
    s22 = g22_arm["split_2230"]["FULL"]
    s30 = g22_arm["split_gt30"]["FULL"]
    print(
        f"[verify] 22-30% N={s22['n']} AnnROR={_fmt(s22['ann_ror'], 2, '%')} days={_fmt(s22['avg_days'], 1)}; "
        f">30% N={s30['n']} AnnROR={_fmt(s30['ann_ror'], 2, '%')} days={_fmt(s30['avg_days'], 1)}",
        flush=True,
    )
    html = _patch_compare_html(ctrl, g22_arm)
    _patch_summary_csv(g22_arm)
    _patch_baseline_md(ctrl, g22_arm)
    print(f"[merge] {html}", flush=True)
    print(f"[verdict] {g22_arm['verdict']}", flush=True)
    return html


def main() -> None:
    report_only = "--report-only" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if not _closed_ready(CONTROL_DIR):
        raise SystemExit(f"control closed missing: {CONTROL_DIR}")
    if "--merge-control-g22" in sys.argv:
        html = _merge_control_g22()
        if "--skip-ntfy" not in sys.argv:
            subprocess.run(
                [
                    PY, str(ROOT / "tools" / "ntfy_job_done.py"),
                    "--path", str(html),
                    "-t", "WPBR control G>=22 only",
                    "-m", "Control subset overhead G>=22% (drop clear-sky). Research only.",
                ],
                cwd=str(ROOT),
                check=False,
            )
        print(f"[done] {html}", flush=True)
        return

    reuse_90 = _prior_90_applies_fractions_for_far_g()
    reuse_note = (
        "Reused prior 90/40 closed book from wpbr_dynamic_overhead_sizing_20261002 "
        "(verified recovered G≥22% trades with fraction sizing; engine applied fractions "
        "for all overhead G with no 22% clear-sky fallback)."
        if reuse_90
        else "Prior 90/40 not reusable — rerunning 90/40 with fractions for all G including ≥22%."
    )
    print(f"[plan] {reuse_note}", flush=True)

    arm_dirs: dict[str, Path] = {}
    for arm in ARMS:
        if report_only:
            if arm["reuse_prior"] and reuse_90:
                arm_dirs[arm["id"]] = PRIOR_90_DIR
            else:
                d = RUNS_DIR / arm["folder_name"]
                if not _closed_ready(d):
                    raise SystemExit(f"--report-only missing {d}")
                arm_dirs[arm["id"]] = d
        else:
            arm_dirs[arm["id"]] = _run_arm(arm, reuse_90=reuse_90)

    _ensure_all_fixed_arms(report_only=report_only)
    fixed_reuse_bits: list[str] = []
    for farm in FIXED_ARMS:
        folder = farm["folder"]
        closed = _latest(folder, "Closed")
        assert closed is not None
        rel = closed.relative_to(ROOT).as_posix()
        if "neighborhood" in rel or farm.get("_reused_closed"):
            bit = f"Fixed {farm['short']} Closed reused from {rel} (not recomputed)."
        else:
            bit = f"Fixed {farm['short']} Closed from {rel}."
        fixed_reuse_bits.append(bit)
        print(f"[fixed] {farm['id']} ready -> {folder}", flush=True)

    ctrl = _score_book({
        "id": "control",
        "short": "Control 22/20/8",
        "role": "live freeze (reused)",
        "folder": CONTROL_DIR,
        "t_frac": 0.90,
        "kind": "control",
    })
    # Log control G-bin mass (expect clear sky + G>22%).
    _ctrl_bins: dict[str, int] = {name: 0 for name, _, _ in G_BINS}
    for t in ctrl["trades"]:
        _ctrl_bins[_g_bin(t.get("g_pct"))] += 1
    print(f"[g_bins] control FULL counts: {_ctrl_bins}", flush=True)
    g22_arm = _control_oh_g22_book(ctrl)
    print(
        f"[subset] {g22_arm['short']} N={g22_arm['slices']['FULL']['n']} "
        f"AnnROR full/IS/OOS={_fmt(g22_arm['slices']['FULL']['ann_ror'], 2, '%')}/"
        f"{_fmt(g22_arm['slices']['IS']['ann_ror'], 2, '%')}/"
        f"{_fmt(g22_arm['slices']['OOS']['ann_ror'], 2, '%')} "
        f"verdict={g22_arm['verdict_word']}",
        flush=True,
    )
    books: list[dict[str, Any]] = [ctrl, g22_arm]
    # Fixed package first after control so Paul sees 16/8/3 next to live, then dynamics.
    for farm in FIXED_ARMS:
        cand = _score_book(dict(farm))
        word, text = _verdict(cand, ctrl)
        cand["verdict_word"] = word
        cand["verdict"] = text
        books.append(cand)
        if farm["id"] == "oh17_tg08_st06":
            oh_only = _overhead_present_book(cand, ctrl)
            books.append(oh_only)
            print(
                f"[subset] {oh_only['short']} N={oh_only['slices']['FULL']['n']} "
                f"WR={_fmt(oh_only['slices']['FULL']['wr'], 1, '%')} "
                f"avg={_fmt(oh_only['slices']['FULL']['avg'], 2, '%')} "
                f"PF={_fmt(oh_only['slices']['FULL']['pf'], 2)} "
                f"days={_fmt(oh_only['slices']['FULL']['avg_days'], 1)} "
                f"cash=${oh_only['cash']:,.2f} "
                f"AnnROR full/IS/OOS={_fmt(oh_only['slices']['FULL']['ann_ror'], 2, '%')}/"
                f"{_fmt(oh_only['slices']['IS']['ann_ror'], 2, '%')}/"
                f"{_fmt(oh_only['slices']['OOS']['ann_ror'], 2, '%')} "
                f"verdict={oh_only['verdict_word']}",
                flush=True,
            )
        g22 = cand["g22_slices"]["FULL"]
        _fbins: dict[str, int] = {name: 0 for name, _, _ in G_BINS}
        for t in cand["trades"]:
            _fbins[_g_bin(t.get("g_pct"))] += 1
        print(f"[g_bins] {farm['short']} FULL counts: {_fbins}", flush=True)
        print(
            f"[arm] {farm['short']} verdict={word} N={cand['slices']['FULL']['n']} "
            f"AnnROR full/IS/OOS={_fmt(cand['slices']['FULL']['ann_ror'], 2, '%')}/"
            f"{_fmt(cand['slices']['IS']['ann_ror'], 2, '%')}/"
            f"{_fmt(cand['slices']['OOS']['ann_ror'], 2, '%')} "
            f"G>=22% N={g22['n']} AnnROR={_fmt(g22['ann_ror'], 2, '%')}",
            flush=True,
        )
    for arm in ARMS:
        cand = _score_book({
            "id": arm["id"],
            "short": arm["short"],
            "role": arm["role"],
            "folder": arm_dirs[arm["id"]],
            "t_frac": arm["t_frac"],
            "s_frac": arm["s_frac"],
            "kind": "dynamic",
        })
        word, text = _verdict(cand, ctrl)
        cand["verdict_word"] = word
        cand["verdict"] = text
        books.append(cand)
        g22 = cand["g22_slices"]["FULL"]
        print(
            f"[arm] {arm['short']} verdict={word} N={cand['slices']['FULL']['n']} "
            f"AnnROR full/IS/OOS={_fmt(cand['slices']['FULL']['ann_ror'], 2, '%')}/"
            f"{_fmt(cand['slices']['IS']['ann_ror'], 2, '%')}/"
            f"{_fmt(cand['slices']['OOS']['ann_ror'], 2, '%')} "
            f"G>=22% N={g22['n']} AnnROR={_fmt(g22['ann_ror'], 2, '%')}",
            flush=True,
        )
        if arm["id"] == "t70_s40":
            g17 = _t70_overhead_g17_book(cand, ctrl)
            books.append(g17)
            print(
                f"[subset] {g17['short']} N={g17['slices']['FULL']['n']} "
                f"WR={_fmt(g17['slices']['FULL']['wr'], 1, '%')} "
                f"avg={_fmt(g17['slices']['FULL']['avg'], 2, '%')} "
                f"PF={_fmt(g17['slices']['FULL']['pf'], 2)} "
                f"days={_fmt(g17['slices']['FULL']['avg_days'], 1)} "
                f"cash=${g17['cash']:,.2f} "
                f"AnnROR full/IS/OOS={_fmt(g17['slices']['FULL']['ann_ror'], 2, '%')}/"
                f"{_fmt(g17['slices']['IS']['ann_ror'], 2, '%')}/"
                f"{_fmt(g17['slices']['OOS']['ann_ror'], 2, '%')} "
                f"verdict={g17['verdict_word']}",
                flush=True,
            )

    reuse_note = reuse_note + " " + " ".join(fixed_reuse_bits)
    _write_baseline(books, reuse_note)
    html = _write_html(books, reuse_note)
    _write_summary_csv(books)

    if "--skip-ntfy" not in sys.argv:
        words = "/".join(b.get("verdict_word", "") for b in books[1:])
        subprocess.run(
            [
                PY, str(ROOT / "tools" / "ntfy_job_done.py"),
                "--path", str(html),
                "-t", "WPBR 16/7 and 17/7",
                "-m", f"Verdicts {words}. Research only.",
            ],
            cwd=str(ROOT),
            check=False,
        )
    print(f"[done] {html}", flush=True)
    for b in books[1:]:
        print(f"[verdict] {b['verdict']}", flush=True)


if __name__ == "__main__":
    main()
