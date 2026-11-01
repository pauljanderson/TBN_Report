"""Neighborhood grid around WPBR package 15/10/4.

Research only. 125 cells frozen before new P&L. Out of sample is report-only.
Not gold. Not DailyRun. Does not edit run_wpbr.bat.

Parallel supervisor: hard cap is 8 rocket_tbn.py engine processes TOTAL on the
machine (this grid plus any other WPBR runs). Do not start a new cell when
that count is 8 or more, or when CPU LoadPercentage is above 90. Extras
already running are left to finish. Eight workers inside each engine.
Checkpoints summary.csv as each cell finishes. Writes HTML and notifies only
when all 125 cells are scored.
"""
from __future__ import annotations

import csv
import html as html_mod
import importlib.util
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR = ROOT / "drive" / "paul_experiments" / "wpbr_15_10_4_neighborhood_20261002"
RUNS = ROOT / "tmp_wpbr_15_10_4_neighborhood_20261002"
PY = sys.executable
WORKERS = 8
IS_CUT = "20240101"
CENTER = (15, 10, 4)
REUSE_CENTER = ROOT / "tmp_wpbr_tighter_overhead_target_stop_ab_20261002" / "pkg_15_10_4"
CONTROL_DIR = ROOT / "tmp_wpbr_overhead20_vs22_t20s8_ab_20261002" / "control"
MAX_TRIES = 8

REQUEST_QUOTE = (
    "great - also. I'm curious if we can run some more tests around this adjusted run: "
    "Package 15/10/4 maybe 15/12/4, 15/12/5. can you try every iteration with +-2 to each #? "
    "(i.e. 13-17/8-12/2-6). "
    "run a couple more WPBR tests with overhead/target/stop: "
    "16/7/3, 16/7/4, 16/7/5, 17/7/2, 17/7/3, 17/7/4, 17/7/5. "
    "also add them to this summary wpbr_15_10_4_neighborhood_20261002. "
    "can you make sure the 22/20/8 with no overhead is written here as well. "
    "run a test using 17/8/6 taking NO trades unless there is an overhead zone. "
    "what if we build our dynamic target / stop on top of that the 70/40 for "
    "zones above >= 17%"
)

CTRL_NOH_ID = "control_no_overhead"
OH1786_OH_ID = "oh17_tg08_st06_overhead_only"
T70_G17_ID = "t70_s40_g17"
EXTRA_SLICE_IDS = {CTRL_NOH_ID, OH1786_OH_ID, T70_G17_ID}

# Frozen cartesian product. Inclusive. Do not add or drop the original 125.
CELLS: list[tuple[int, int, int]] = [
    (oh, tg, st)
    for oh in (13, 14, 15, 16, 17)
    for tg in (8, 9, 10, 11, 12)
    for st in (2, 3, 4, 5, 6)
]
assert len(CELLS) == 125

# Extra packages (target 7). Not part of the original 125. Do not recompute finished grid cells.
EXTRA_CELLS: list[tuple[int, int, int]] = [
    (16, 7, 3), (16, 7, 4), (16, 7, 5),
    (17, 7, 2), (17, 7, 3), (17, 7, 4), (17, 7, 5),
]
FRAC_TMP = ROOT / "tmp_wpbr_dynamic_overhead_frac_grid_20261002"

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
    "wpbr_overhead_band_pct": "0.22",
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


def cell_id(oh: int, tg: int, st: int) -> str:
    return f"oh{oh:02d}_tg{tg:02d}_st{st:02d}"


def knobs(oh: int, tg: int, st: int) -> dict[str, str]:
    return {
        "wpbr_overhead_band_pct": f"{oh / 100:.2f}",
        "target_pct": f"{1 + tg / 100:.2f}",
        "stop_pct": f"{1 - st / 100:.2f}",
    }


def log(msg: str) -> None:
    print(msg, flush=True)


def _load_prior():
    path = ROOT / "tools" / "wpbr_tighter_overhead_target_stop_ab_20261002.py"
    spec = importlib.util.spec_from_file_location("prior_wpbr_pkg", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    import ctypes
    # OpenProcess can still succeed briefly after exit. Require STILL_ACTIVE.
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    code = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return bool(ok) and code.value == 259


def engine_cmds() -> list[tuple[int, str]] | None:
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -match 'rocket_tbn\\.py' "
        "-and $_.CommandLine -notmatch 'spawn_main|multiprocessing' } | "
        "ForEach-Object { '{0}|{1}' -f $_.ProcessId, ($_.CommandLine -replace '\\r|\\n',' ') }"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True, encoding="utf-8", errors="replace",
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        log(f"[warn] engine list failed: {exc}")
        return None
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        pid_s, cmd = line.split("|", 1)
        try:
            rows.append((int(pid_s), cmd))
        except ValueError:
            continue
    return rows


# Hard cap: neighborhood engine processes at once (Paul 2026-10-02: 4 x -w 8).
HARD_CAP = 4
CPU_MAX = 90.0


def engine_count() -> int:
    """Count of WPBR engine processes, or -1 if the process list could not be read."""
    rows = engine_cmds()
    if rows is None:
        return -1
    return len(rows)


def neighborhood_engine_count() -> int:
    """Count only this stamp's cell engines (ignore unrelated rocket_tbn jobs)."""
    rows = engine_cmds()
    if rows is None:
        return -1
    marker = str(RUNS).lower().replace("/", "\\")
    n = 0
    for _pid, cmd in rows:
        low = cmd.lower().replace("/", "\\")
        if marker in low or "tmp_wpbr_15_10_4_neighborhood_20261002" in low:
            n += 1
    return n


def cpu_load() -> float:
    """Average Win32_Processor LoadPercentage. Fail closed (100) if unread."""
    script = "(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average"
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True, encoding="utf-8", errors="replace", timeout=90,
        )
        return float(out.strip())
    except (subprocess.CalledProcessError, OSError, ValueError):
        log("[warn] CPU sample failed; refusing to launch")
        return 100.0


def read_cap() -> int:
    path = RUNS / "concurrency_cap.txt"
    try:
        val = int(path.read_text(encoding="utf-8").strip().split()[0])
        if 1 <= val <= 32:
            return val
    except (OSError, ValueError, IndexError):
        pass
    return HARD_CAP


def read_cpu() -> str:
    path = RUNS / "cpu_check.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def pid_path(cid: str) -> Path:
    return RUNS / "pids" / f"{cid}.pid"


def tries_path(cid: str) -> Path:
    return RUNS / "pids" / f"{cid}.tries"


def read_pid(cid: str) -> int:
    try:
        return int(pid_path(cid).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def read_tries(cid: str) -> int:
    try:
        return int(tries_path(cid).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def write_tries(cid: str, n: int) -> None:
    tries_path(cid).write_text(str(n), encoding="utf-8")


def cmd_for(out: Path, oh: int, tg: int, st: int) -> list[str]:
    cmd = [
        PY, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(WORKERS),
        "--aggressive", "--no-regression",
    ]
    merged = dict(COMMON)
    merged.update(knobs(oh, tg, st))
    for key, val in merged.items():
        cmd.extend(["-v", f"{key}={val}"])
    return cmd


def launch_cell(oh: int, tg: int, st: int) -> int:
    cid = cell_id(oh, tg, st)
    out = RUNS / cid
    out.mkdir(parents=True, exist_ok=True)
    # Do not relaunch over a finished book.
    if _done_folder(out, oh, tg, st):
        log(f"[skip-done] {cid}")
        return 0
    tries = read_tries(cid) + 1
    write_tries(cid, tries)
    cmd = cmd_for(out, oh, tg, st)
    (out / "run_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
    log_path = RUNS / f"{cid}.log"
    log_f = log_path.open("a", encoding="utf-8", errors="replace")
    log_f.write(f"\n[launch] try={tries} workers={WORKERS}\n")
    log_f.flush()
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_f, stderr=subprocess.STDOUT)
    pid_path(cid).write_text(str(proc.pid), encoding="utf-8")
    log(f"[launch] {cid} pid={proc.pid} try={tries} knobs={knobs(oh, tg, st)}")
    return proc.pid


def _done_folder(folder: Path, oh: int, tg: int, st: int, prior=None) -> bool:
    if prior is None:
        return False
    if not prior._closed_ready(folder):
        return False
    report = prior._read_report(folder)
    k = knobs(oh, tg, st)
    return prior._knobs_match(
        report, float(k["wpbr_overhead_band_pct"]), float(k["target_pct"]), float(k["stop_pct"]),
    )


def adopt_running() -> dict[str, int]:
    """cell id -> pid, from pid files plus live command lines."""
    found: dict[str, int] = {}
    for oh, tg, st in CELLS:
        cid = cell_id(oh, tg, st)
        pid = read_pid(cid)
        if pid and alive(pid):
            found[cid] = pid
    cmds = engine_cmds() or []
    for pid, cmd in cmds:
        marker = str(RUNS).lower()
        low = cmd.lower().replace("/", "\\")
        if marker.lower() not in low and "tmp_wpbr_15_10_4_neighborhood_20261002" not in low:
            continue
        for oh, tg, st in CELLS:
            cid = cell_id(oh, tg, st)
            if cid.lower() in low:
                found[cid] = pid
                pid_path(cid).write_text(str(pid), encoding="utf-8")
                if read_tries(cid) == 0:
                    write_tries(cid, 1)
    return found


def reset_incomplete_tries(prior) -> None:
    """DuckDB lock crashes must not burn the retry budget. Finished cells stay put."""
    for oh, tg, st in CELLS:
        cid = cell_id(oh, tg, st)
        folder = REUSE_CENTER if (oh, tg, st) == CENTER else RUNS / cid
        if (oh, tg, st) == CENTER and _done_folder(REUSE_CENTER, oh, tg, st, prior=prior):
            continue
        if _done_folder(RUNS / cid, oh, tg, st, prior=prior):
            continue
        pid = read_pid(cid)
        if pid and alive(pid):
            continue
        if read_tries(cid):
            write_tries(cid, 0)
            log(f"[reset-tries] {cid}")


def build_cmd_line_guard(cid: str) -> bool:
    cmds = engine_cmds()
    if cmds is None:
        return True
    for _pid, cmd in cmds:
        if cid.lower() in cmd.lower():
            return True
    return False


def checkpoint(prior, books: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm_id", "label", "role", "center", "overhead_pct", "target_above_buy_pct",
        "stop_under_trigger_low_pct", "target_pct", "stop_pct", "slot_cash", "symbols",
        "slice", "n", "win_rate", "avg_pct", "median_pct", "profit_factor", "max_dd_pct",
        "ann_ror_pct", "avg_days", "median_days", "calmar", "sharpe", "avg_win_pct",
        "avg_loss_pct", "expectancy_pct", "avg_without_max_pct", "trades_per_year",
        "verdict", "source_closed", "g_bin",
    ]
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b in books:
            if b["id"] == "oh17_tg08_st06_full_for_slice" or b["id"] == "t70_s40_full_for_slice":
                continue
            for sl in ("FULL", "IS", "OOS"):
                m = b["slices"][sl]
                def num(key: str, nd: int = 4) -> str:
                    v = m.get(key, float("nan"))
                    return f"{v:.{nd}f}" if isinstance(v, (int, float)) and math.isfinite(v) else ""
                w.writerow({
                    "arm_id": b["id"],
                    "label": b["short"],
                    "role": b["role"],
                    "center": "yes" if b.get("center") else "",
                    "overhead_pct": f"{b['overhead'] * 100:.0f}",
                    "target_above_buy_pct": f"{b['target_above'] * 100:.0f}",
                    "stop_under_trigger_low_pct": f"{b['stop_under'] * 100:.0f}",
                    "target_pct": f"{b['target_pct']:.2f}",
                    "stop_pct": f"{b['stop_pct']:.2f}",
                    "slot_cash": f"{b['cash']:.6f}",
                    "symbols": b["symbols"],
                    "slice": sl,
                    "n": m["n"],
                    "win_rate": num("wr"),
                    "avg_pct": num("avg"),
                    "median_pct": num("median"),
                    "profit_factor": num("pf"),
                    "max_dd_pct": num("max_dd"),
                    "ann_ror_pct": num("ann_ror"),
                    "avg_days": num("avg_days"),
                    "median_days": num("med_days"),
                    "calmar": num("calmar"),
                    "sharpe": num("sharpe"),
                    "avg_win_pct": num("avg_win"),
                    "avg_loss_pct": num("avg_loss"),
                    "expectancy_pct": num("expect"),
                    "avg_without_max_pct": num("wo_max"),
                    "trades_per_year": num("tpy"),
                    "verdict": b.get("verdict_word", ""),
                    "source_closed": str(b["closed"]).replace("\\", "/"),
                    "g_bin": "",
                })
            for row in b.get("g_bin_rows") or []:
                w.writerow({k: row.get(k, "") for k in fields})
    tmp.replace(path)
    (RUNS / "progress.txt").write_text(
        f"scored_cells={sum(1 for b in books if b['id'] != 'control')}\n"
        f"cap={read_cap()}\ncpu={read_cpu()}\n",
        encoding="utf-8",
    )
    log(f"[checkpoint] {path} books={len(books)}")


def spec_for(oh: int, tg: int, st: int, folder: Path, role: str, *, extra: bool = False) -> dict[str, Any]:
    k = knobs(oh, tg, st)
    cid = cell_id(oh, tg, st)
    return {
        "id": cid,
        "short": f"{oh}/{tg}/{st}",
        "role": role,
        "center": (oh, tg, st) == CENTER,
        "extra": extra,
        "overhead": oh / 100,
        "target_above": tg / 100,
        "stop_under": st / 100,
        "target_pct": float(k["target_pct"]),
        "stop_pct": float(k["stop_pct"]),
        "folder": folder,
    }


def extra_folder(oh: int, tg: int, st: int, prior) -> Path | None:
    """Reuse Closed from frac-grid tmp or neighborhood tmp. Do not steal unfinished files."""
    cid = cell_id(oh, tg, st)
    for folder in (FRAC_TMP / cid, RUNS / cid):
        if _done_folder(folder, oh, tg, st, prior=prior):
            return folder
    return None


def score_control_no_overhead(ctrl_book: dict[str, Any]) -> dict[str, Any]:
    """Live 22/20/8, clear-sky / no constraining older zone. Same G recovery as frac grid.

    Not the G>=22% subset. Not an engine rerun. Extra slice, not part of the 125.
    """
    spec = importlib.util.spec_from_file_location(
        "wpbr_frac_grid_g", ROOT / "tools" / "wpbr_dynamic_overhead_frac_grid_20261002.py"
    )
    frac = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(frac)
    closed = frac._latest(CONTROL_DIR, "Closed")
    if closed is None:
        raise FileNotFoundError(f"no control closed in {CONTROL_DIR}")
    curve = frac._latest(CONTROL_DIR, "EquityCurve")
    g_lookup = frac._control_g_lookup()
    trades = frac._load_trades(closed, 0.80, g_lookup=g_lookup)
    noh = [t for t in trades if frac._g_bin(t.get("g_pct")) == "no overhead"]
    cash = float(ctrl_book["cash"])
    slices = {
        w: frac._metrics(frac._slice_rows(noh, w), cash, curve, w)
        for w in ("FULL", "IS", "OOS")
    }
    n_full = slices["FULL"]["n"]
    if n_full != 2996:
        log(f"[warn] no-overhead N={n_full} expected 2996")
    return {
        "id": CTRL_NOH_ID,
        "short": "22/20/8 no overhead (clear sky)",
        "role": "extra (clear-sky slice of live control)",
        "center": False,
        "extra": True,
        "extra_kind": "control_no_overhead",
        "overhead": 0.22,
        "target_above": 0.20,
        "stop_under": 0.08,
        "target_pct": 1.20,
        "stop_pct": 0.92,
        "folder": CONTROL_DIR,
        "closed": closed,
        "cash": cash,
        "symbols": len({t["symbol"] for t in noh}),
        "slices": slices,
        "verdict": (
            "Extra slice of live 22/20/8: buys with no constraining older zone "
            "(clear sky). Not the G>=22% overhead-present subset. Not in the original 125. "
            "Research only. Not DailyRun."
        ),
        "verdict_word": "extra / control slice",
    }


def score_oh17_overhead_only(ctrl_book: dict[str, Any], prior) -> tuple[dict[str, Any], dict[str, Any]]:
    """17/8/6 neighborhood Closed, drop clear-sky. Same G recovery as frac grid.

    Extra slice, not one of the original 125. Does not recompute the cell.
    Returns (overhead-only book, full 17/8/6 book with trades for G bins / compare).
    """
    spec = importlib.util.spec_from_file_location(
        "wpbr_frac_grid_g_1786", ROOT / "tools" / "wpbr_dynamic_overhead_frac_grid_20261002.py"
    )
    frac = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(frac)
    folder = RUNS / "oh17_tg08_st06"
    if not _done_folder(folder, 17, 8, 6, prior=prior):
        raise FileNotFoundError(f"no 17/8/6 closed in {folder}")
    full = frac._score_book({
        "id": "oh17_tg08_st06",
        "short": "17/8/6",
        "role": "fixed package (neighborhood cell)",
        "folder": folder,
        "kind": "fixed",
        "overhead_band_pct": 0.17,
        "target_pct": 1.08,
        "stop_pct": 0.94,
        "stop_under_pct": 6,
        "target_gain_pct": 8,
        "t_frac": 0.90,
        "recover_g": True,
    })
    oh = frac._overhead_present_book(full, {
        "slices": ctrl_book["slices"],
        "id": "control",
        "short": ctrl_book.get("short", "22/20/8 live"),
    })
    n_full = full["slices"]["FULL"]["n"]
    n_oh = oh["slices"]["FULL"]["n"]
    log(f"[1786-oh] full N={n_full} overhead-only N={n_oh} cash={oh['cash']:.2f}")
    book = {
        "id": OH1786_OH_ID,
        "short": "17/8/6 overhead-only",
        "role": "extra (17/8/6, drop clear-sky; not original 125)",
        "center": False,
        "extra": True,
        "extra_kind": "oh17_overhead_only",
        "overhead": 0.17,
        "target_above": 0.08,
        "stop_under": 0.06,
        "target_pct": 1.08,
        "stop_pct": 0.94,
        "folder": folder,
        "closed": full["closed"],
        "cash": oh["cash"],
        "symbols": oh["symbols"],
        "slices": oh["slices"],
        "trades": oh["trades"],
        "curve": oh["curve"],
        "g_bin_html": frac._g_bucket_table(oh),
        "g_bin_rows": _neigh_g_bin_rows(oh, frac),
        "verdict": oh["verdict"],
        "verdict_word": oh["verdict_word"],
    }
    full_book = {
        "id": "oh17_tg08_st06_full_for_slice",
        "short": "17/8/6 full book",
        "role": "internal (full 17/8/6 for slice compare)",
        "center": False,
        "extra": False,
        "overhead": 0.17,
        "target_above": 0.08,
        "stop_under": 0.06,
        "target_pct": 1.08,
        "stop_pct": 0.94,
        "folder": folder,
        "closed": full["closed"],
        "cash": full["cash"],
        "symbols": full["symbols"],
        "slices": full["slices"],
        "trades": full["trades"],
    }
    return book, full_book


def _neigh_g_bin_rows(oh: dict[str, Any], frac) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_bin: dict[str, list] = {name: [] for name, _, _ in frac.G_BINS}
    for t in oh["trades"]:
        by_bin[frac._g_bin(t.get("g_pct"))].append(t)
    g22 = [
        t for t in oh["trades"]
        if t.get("g_pct") is not None and math.isfinite(t["g_pct"]) and t["g_pct"] >= 22.0
    ]
    groups = list(by_bin.items()) + [("G >= 22%", g22), (frac.ALL_BINS_LABEL, list(oh["trades"]))]
    closed = str(oh["closed"]).replace("\\", "/")
    for name, group in groups:
        for sl in ("FULL", "IS", "OOS"):
            m = frac._metrics(frac._slice_rows(group, sl), oh["cash"], oh.get("curve"), sl)
            def num(key: str, nd: int = 4) -> str:
                v = m.get(key, float("nan"))
                return f"{v:.{nd}f}" if isinstance(v, (int, float)) and math.isfinite(v) else ""
            rows.append({
                "arm_id": OH1786_OH_ID,
                "label": "17/8/6 overhead-only",
                "role": "extra (17/8/6, drop clear-sky; not original 125)",
                "center": "",
                "overhead_pct": "17",
                "target_above_buy_pct": "8",
                "stop_under_trigger_low_pct": "6",
                "target_pct": "1.08",
                "stop_pct": "0.94",
                "slot_cash": f"{oh['cash']:.6f}",
                "symbols": str(len({t['symbol'] for t in group})),
                "slice": sl,
                "n": m["n"],
                "win_rate": num("wr"),
                "avg_pct": num("avg"),
                "median_pct": num("median"),
                "profit_factor": num("pf"),
                "max_dd_pct": num("max_dd"),
                "ann_ror_pct": num("ann_ror"),
                "avg_days": num("avg_days"),
                "median_days": num("med_days"),
                "calmar": num("calmar"),
                "sharpe": num("sharpe"),
                "avg_win_pct": num("avg_win"),
                "avg_loss_pct": num("avg_loss"),
                "expectancy_pct": num("expect"),
                "avg_without_max_pct": num("wo_max"),
                "trades_per_year": num("tpy"),
                "verdict": oh.get("verdict_word", ""),
                "source_closed": closed,
                "g_bin": name,
            })
    return rows


def score_t70_g17(ctrl_book: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """70/40 Closed, keep G>=17%. Extra labeled slice. Does not touch the 125 cells."""
    spec = importlib.util.spec_from_file_location(
        "wpbr_frac_grid_g_t70", ROOT / "tools" / "wpbr_dynamic_overhead_frac_grid_20261002.py"
    )
    frac = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(frac)
    folder = FRAC_TMP / "t70_s40"
    full = frac._score_book({
        "id": "t70_s40",
        "short": "70/40",
        "role": "research C",
        "folder": folder,
        "t_frac": 0.70,
        "s_frac": 0.40,
        "kind": "dynamic",
    })
    g17 = frac._t70_overhead_g17_book(full, {
        "slices": ctrl_book["slices"],
        "id": "control",
        "short": ctrl_book.get("short", "22/20/8 live"),
    })
    log(
        f"[t70-g17] full70 N={full['slices']['FULL']['n']} "
        f"g17 N={g17['slices']['FULL']['n']} cash={g17['cash']:.2f}"
    )
    book = {
        "id": T70_G17_ID,
        "short": "70/40, overhead G>=17% only",
        "role": "extra (70/40 G>=17%; drop clear-sky and G<17%; not original 125)",
        "center": False,
        "extra": True,
        "extra_kind": "t70_g17",
        "overhead": 0.17,
        "target_above": 0.0,
        "stop_under": 0.0,
        "target_pct": 1.0,
        "stop_pct": 1.0,
        "folder": folder,
        "closed": full["closed"],
        "cash": g17["cash"],
        "symbols": g17["symbols"],
        "slices": g17["slices"],
        "trades": g17["trades"],
        "curve": g17["curve"],
        "g_bin_html": frac._g_bucket_table(g17),
        "g_bin_rows": _neigh_t70_g17_rows(g17, frac),
        "verdict": g17["verdict"],
        "verdict_word": g17["verdict_word"],
    }
    full_book = {
        "id": "t70_s40_full_for_slice",
        "short": "70/40 full book",
        "role": "internal (full 70/40 for slice compare)",
        "center": False,
        "extra": False,
        "overhead": 0.0,
        "target_above": 0.0,
        "stop_under": 0.0,
        "target_pct": 1.20,
        "stop_pct": 0.92,
        "folder": folder,
        "closed": full["closed"],
        "cash": full["cash"],
        "symbols": full["symbols"],
        "slices": full["slices"],
        "trades": full["trades"],
    }
    return book, full_book


def _neigh_t70_g17_rows(oh: dict[str, Any], frac) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    closed = str(oh["closed"]).replace("\\", "/")
    for name, group in frac._g_bin_groups(oh):
        for sl in ("FULL", "IS", "OOS"):
            m = frac._metrics(frac._slice_rows(group, sl), oh["cash"], oh.get("curve"), sl)
            def num(key: str, nd: int = 4) -> str:
                v = m.get(key, float("nan"))
                return f"{v:.{nd}f}" if isinstance(v, (int, float)) and math.isfinite(v) else ""
            rows.append({
                "arm_id": T70_G17_ID,
                "label": "70/40, overhead G>=17% only",
                "role": "extra (70/40 G>=17%; drop clear-sky and G<17%; not original 125)",
                "center": "",
                "overhead_pct": "17",
                "target_above_buy_pct": "",
                "stop_under_trigger_low_pct": "",
                "target_pct": "",
                "stop_pct": "",
                "slot_cash": f"{oh['cash']:.6f}",
                "symbols": str(len({t['symbol'] for t in group})),
                "slice": sl,
                "n": m["n"],
                "win_rate": num("wr"),
                "avg_pct": num("avg"),
                "median_pct": num("median"),
                "profit_factor": num("pf"),
                "max_dd_pct": num("max_dd"),
                "ann_ror_pct": num("ann_ror"),
                "avg_days": num("avg_days"),
                "median_days": num("med_days"),
                "calmar": num("calmar"),
                "sharpe": num("sharpe"),
                "avg_win_pct": num("avg_win"),
                "avg_loss_pct": num("avg_loss"),
                "expectancy_pct": num("expect"),
                "avg_without_max_pct": num("wo_max"),
                "trades_per_year": num("tpy"),
                "verdict": oh.get("verdict_word", ""),
                "source_closed": closed,
                "g_bin": name,
            })
    return rows


def apply_verdicts(prior, books: list[dict[str, Any]]) -> None:
    ctrl = next(b for b in books if b["id"] == "control")
    for b in books:
        if b["id"] == "control":
            b["verdict"] = "Control."
            b["verdict_word"] = "control"
            continue
        if b["id"] in EXTRA_SLICE_IDS or b.get("extra_kind") in (
            "control_no_overhead", "oh17_overhead_only", "t70_g17",
        ):
            continue
        text = prior._verdict(b["short"], b["slices"]["IS"], b["slices"]["OOS"], ctrl["slices"])
        b["verdict"] = text
        b["verdict_word"] = prior._verdict_word(text)


def score_one(prior, oh: int, tg: int, st: int, folder: Path, role: str, *, extra: bool = False) -> dict[str, Any]:
    book = prior._score_book(spec_for(oh, tg, st, folder, role, extra=extra))
    book["extra"] = extra
    book["role"] = role
    return book


def esc(s: str) -> str:
    return html_mod.escape(s, quote=True)


def _best(books: list[dict[str, Any]], window: str, *, extras: bool | None = False) -> list[dict[str, Any]]:
    cells = [
        b for b in books
        if b["id"] not in ("control", CTRL_NOH_ID, OH1786_OH_ID)
        and b.get("extra_kind") not in ("control_no_overhead", "oh17_overhead_only", "t70_g17")
        and math.isfinite(b["slices"][window]["ann_ror"])
        and (extras is None or bool(b.get("extra")) == extras)
    ]
    if not cells:
        return []
    top = max(b["slices"][window]["ann_ror"] for b in cells)
    return [b for b in cells if abs(b["slices"][window]["ann_ror"] - top) < 1e-9]


def write_html(prior, books: list[dict[str, Any]], cap: int, cpu_txt: str) -> Path:
    from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th
    from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML

    ctrl = next(b for b in books if b["id"] == "control")
    noh = next((b for b in books if b["id"] == CTRL_NOH_ID), None)
    oh1786 = next((b for b in books if b["id"] == OH1786_OH_ID), None)
    oh1786_full = next((b for b in books if b["id"] == "oh17_tg08_st06_full_for_slice"), None)
    t70g17 = next((b for b in books if b["id"] == T70_G17_ID), None)
    t70_full = next((b for b in books if b["id"] == "t70_s40_full_for_slice"), None)
    skip_ids = {
        "control", CTRL_NOH_ID, OH1786_OH_ID, "oh17_tg08_st06_full_for_slice",
        T70_G17_ID, "t70_s40_full_for_slice",
    }
    cells = [b for b in books if b["id"] not in skip_ids]
    grid_cells = [b for b in cells if not b.get("extra")]
    extra_cells = [b for b in cells if b.get("extra")]
    cells.sort(key=lambda b: (b.get("extra") or False, b["overhead"], b["target_above"], b["stop_under"]))
    extra_cells.sort(key=lambda b: (b["overhead"], b["target_above"], b["stop_under"]))
    by_key = {
        (round(b["overhead"] * 100), round(b["target_above"] * 100), round(b["stop_under"] * 100)): b
        for b in grid_cells
    }
    is_best = {b["id"] for b in _best(books, "IS", extras=False)}
    oos_best = {b["id"] for b in _best(books, "OOS", extras=False)}
    extra_is_best = {b["id"] for b in _best(books, "IS", extras=True)}
    extra_oos_best = {b["id"] for b in _best(books, "OOS", extras=True)}
    words = {"KEEP": 0, "HOLD": 0, "DISMISS": 0}
    extra_words = {"KEEP": 0, "HOLD": 0, "DISMISS": 0}
    for b in grid_cells:
        words[b.get("verdict_word", "HOLD")] = words.get(b.get("verdict_word", "HOLD"), 0) + 1
    for b in extra_cells:
        extra_words[b.get("verdict_word", "HOLD")] = extra_words.get(b.get("verdict_word", "HOLD"), 0) + 1

    def fmt(v: float, nd: int = 2, suf: str = "") -> str:
        return prior._fmt(v, nd, suf)

    head = "".join([
        sortable_th("Cell", "text"),
        sortable_th("Set", "text"),
        sortable_th("Overhead %", "num"),
        sortable_th("Target %", "num"),
        sortable_th("Stop %", "num"),
        sortable_th("Center", "text"),
        sortable_th("N", "num"),
        sortable_th("Win rate", "num"),
        sortable_th("Avg %", "num"),
        sortable_th("Profit factor", "num"),
        sortable_th("Max DD %", "num"),
        sortable_th("Ann ROR full", "num"),
        sortable_th("Ann ROR in-sample", "num"),
        sortable_th("Ann ROR out-of-sample", "num"),
        sortable_th("IS avg %", "num"),
        sortable_th("IS profit factor", "num"),
        sortable_th("IS max DD %", "num"),
        sortable_th("IS Ann ROR vs live", "num"),
        sortable_th("Slot cash", "num"),
        sortable_th("Verdict vs live", "text"),
    ])
    rows = []
    ordered = [ctrl] + ([noh] if noh else []) + ([oh1786] if oh1786 else []) + cells
    c_is = ctrl["slices"]["IS"]["ann_ror"]
    for b in ordered:
        full, is_m, oos = b["slices"]["FULL"], b["slices"]["IS"], b["slices"]["OOS"]
        marks = []
        if b.get("center"):
            marks.append("center")
        if b["id"] == CTRL_NOH_ID:
            marks.append("extra slice (not in original 125) — live 22/20/8, no constraining older zone")
        elif b["id"] == OH1786_OH_ID:
            marks.append("extra slice (not in original 125) — 17/8/6, overhead zone required")
        elif b.get("extra"):
            marks.append("extra package (not in original 125)")
        if b["id"] in is_best and b["id"] not in EXTRA_SLICE_IDS:
            marks.append("highest in-sample Ann ROR on original 125 (in-sample selection)")
        if b["id"] in oos_best and b["id"] not in EXTRA_SLICE_IDS:
            marks.append("highest out-of-sample Ann ROR on original 125 (report-only)")
        if b["id"] in extra_is_best and b.get("extra") and b["id"] not in EXTRA_SLICE_IDS:
            marks.append("highest in-sample Ann ROR among extra packages")
        if b["id"] in extra_oos_best and b.get("extra") and b["id"] not in EXTRA_SLICE_IDS:
            marks.append("highest out-of-sample Ann ROR among extra packages (report-only)")
        dlt = "" if b["id"] == "control" else prior._delta(is_m["ann_ror"], c_is, 2, "%")
        if b["id"] == "control":
            set_lab = "live"
        elif b["id"] in EXTRA_SLICE_IDS:
            set_lab = "extra slice"
        elif b.get("extra"):
            set_lab = "extra"
        else:
            set_lab = "original 125"
        rows.append(
            "<tr>"
            f"<td>{esc(b['short'])}</td>"
            f"<td>{esc(set_lab)}</td>"
            f"<td>{b['overhead'] * 100:.0f}</td>"
            f"<td>{b['target_above'] * 100:.0f}</td>"
            f"<td>{b['stop_under'] * 100:.0f}</td>"
            f"<td>{esc(', '.join(marks) if marks else '')}</td>"
            f"<td>{full['n']}</td>"
            f"<td>{fmt(full['wr'], 1, '%')}</td>"
            f"<td>{fmt(full['avg'], 2, '%')}</td>"
            f"<td>{fmt(full['pf'], 2)}</td>"
            f"<td>{fmt(full['max_dd'], 2, '%')}</td>"
            f"<td>{fmt(full['ann_ror'], 2, '%')}</td>"
            f"<td>{fmt(is_m['ann_ror'], 2, '%')}</td>"
            f"<td>{fmt(oos['ann_ror'], 2, '%')}</td>"
            f"<td>{fmt(is_m['avg'], 2, '%')}</td>"
            f"<td>{fmt(is_m['pf'], 2)}</td>"
            f"<td>{fmt(is_m['max_dd'], 2, '%')}</td>"
            f"<td>{dlt if b['id'] != 'control' else '—'}</td>"
            f"<td>${b['cash']:,.2f}</td>"
            f"<td>{esc(b.get('verdict_word', ''))}</td>"
            "</tr>"
        )

    # Heatmap: one table, rows overhead Ã— target, columns stop. In-sample Ann ROR.
    vals = [b["slices"]["IS"]["ann_ror"] for b in grid_cells if math.isfinite(b["slices"]["IS"]["ann_ror"])]
    lo = min(vals) if vals else 0.0
    hi = max(vals) if vals else 1.0
    span = max(hi - lo, 0.01)

    def heat(v: float) -> str:
        if not math.isfinite(v):
            return ""
        t = (v - lo) / span
        # light stone to green
        r = int(255 - 140 * t)
        g = int(245 - 40 * t)
        bch = int(230 - 150 * t)
        return f" style=\"background:rgb({r},{g},{bch})\""

    hhead = sortable_th("Overhead", "num") + sortable_th("Target", "num")
    for st in (2, 3, 4, 5, 6):
        hhead += sortable_th(f"Stop {st}%", "num")
    hrows = []
    for oh in (13, 14, 15, 16, 17):
        for tg in (8, 9, 10, 11, 12):
            tds = [f"<td>{oh}</td>", f"<td>{tg}</td>"]
            for st in (2, 3, 4, 5, 6):
                b = by_key.get((oh, tg, st))
                if not b:
                    tds.append("<td>â€”</td>")
                    continue
                v = b["slices"]["IS"]["ann_ror"]
                label = fmt(v, 2, "%")
                if (oh, tg, st) == CENTER:
                    label += " center"
                tds.append(f"<td{heat(v)}>{label}</td>")
            hrows.append("<tr>" + "".join(tds) + "</tr>")

    is_best_s = ", ".join(b["short"] for b in _best(books, "IS", extras=False)) or "—"
    oos_best_s = ", ".join(b["short"] for b in _best(books, "OOS", extras=False)) or "—"
    extra_is_s = ", ".join(b["short"] for b in _best(books, "IS", extras=True)) or "—"
    extra_oos_s = ", ".join(b["short"] for b in _best(books, "OOS", extras=True)) or "—"
    extra_html = ""
    if extra_cells:
        extra_rows = []
        for b in extra_cells:
            full, is_m, oos = b["slices"]["FULL"], b["slices"]["IS"], b["slices"]["OOS"]
            extra_rows.append(
                "<tr>"
                f"<td>{esc(b['short'])}</td>"
                f"<td>extra</td>"
                f"<td>{b['overhead'] * 100:.0f}</td>"
                f"<td>{b['target_above'] * 100:.0f}</td>"
                f"<td>{b['stop_under'] * 100:.0f}</td>"
                f"<td>extra package (not in original 125)</td>"
                f"<td>{full['n']}</td>"
                f"<td>{fmt(full['wr'], 1, '%')}</td>"
                f"<td>{fmt(full['avg'], 2, '%')}</td>"
                f"<td>{fmt(full['pf'], 2)}</td>"
                f"<td>{fmt(full['max_dd'], 2, '%')}</td>"
                f"<td>{fmt(full['ann_ror'], 2, '%')}</td>"
                f"<td>{fmt(is_m['ann_ror'], 2, '%')}</td>"
                f"<td>{fmt(oos['ann_ror'], 2, '%')}</td>"
                f"<td>{fmt(is_m['avg'], 2, '%')}</td>"
                f"<td>{fmt(is_m['pf'], 2)}</td>"
                f"<td>{fmt(is_m['max_dd'], 2, '%')}</td>"
                f"<td>{prior._delta(is_m['ann_ror'], c_is, 2, '%')}</td>"
                f"<td>${b['cash']:,.2f}</td>"
                f"<td>{esc(b.get('verdict_word', ''))}</td>"
                "</tr>"
            )
        extra_html = f"""
<h2>Extra packages (target 7 — not part of the original 125)</h2>
<p class="note">These are 16/7/3, 16/7/4, 16/7/5, 17/7/2, 17/7/3, 17/7/4, and 17/7/5.
Target 7 sits outside the frozen neighborhood (target 8–12). They are scored the same way
as the grid, then shown here so they sit next to it. They do not replace a grid cell.
Closed books are reused from the frac-grid tmp when already scored. Extra KEEP {extra_words.get("KEEP", 0)},
HOLD {extra_words.get("HOLD", 0)}, DISMISS {extra_words.get("DISMISS", 0)}.
Highest extra in-sample Ann ROR: {esc(extra_is_s)} (in-sample selection). Highest extra
out-of-sample Ann ROR: {esc(extra_oos_s)} (report-only).</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead><tbody>{''.join(extra_rows)}</tbody></table></div>
"""
    noh_html = ""
    if noh is not None:
        nf, ni, no = noh["slices"]["FULL"], noh["slices"]["IS"], noh["slices"]["OOS"]
        cf, ci, co = ctrl["slices"]["FULL"], ctrl["slices"]["IS"], ctrl["slices"]["OOS"]
        metric_specs = [
            ("n", "Trades", 0, ""),
            ("wr", "Win rate", 1, "%"),
            ("avg", "Avg %", 2, "%"),
            ("median", "Median %", 2, "%"),
            ("pf", "Profit factor", 2, ""),
            ("max_dd", "Max DD %", 2, "%"),
            ("ann_ror", "Annualized rate of return (Ann ROR) %", 2, "%"),
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
        mhead = (
            sortable_th("Metric", "text")
            + sortable_th("No overhead FULL", "num")
            + sortable_th("No overhead IS", "num")
            + sortable_th("No overhead OOS", "num")
            + sortable_th("Live full book FULL", "num")
            + sortable_th("Δ vs live FULL", "num")
            + sortable_th("Live full book IS", "num")
            + sortable_th("Live full book OOS", "num")
        )
        mrows = []
        for key, label, nd, suf in metric_specs:
            mrows.append(
                "<tr>"
                f"<td>{esc(label)}</td>"
                f"<td>{fmt(nf[key], nd, suf)}</td>"
                f"<td>{fmt(ni[key], nd, suf)}</td>"
                f"<td>{fmt(no[key], nd, suf)}</td>"
                f"<td>{fmt(cf[key], nd, suf)}</td>"
                f"<td>{prior._delta(nf[key], cf[key], nd, suf)}</td>"
                f"<td>{fmt(ci[key], nd, suf)}</td>"
                f"<td>{fmt(co[key], nd, suf)}</td>"
                "</tr>"
            )
        noh_html = f"""
<h2>Extra slice: live 22/20/8, no overhead (clear sky)</h2>
<p class="note">Paul asked to write the live 22/20/8 freeze here as well, but only the
<strong>no-overhead / clear sky</strong> bin: buys with no constraining older zone above.
This is <strong>not</strong> the G≥22% overhead-present subset. It is not one of the original
125 cells (13–17 / 8–12 / 2–6). Numbers reuse stamp 261002051403 Closed, with the same
overhead-gap recovery as the fraction-grid page (join to 80/40 OVERHEAD_GAP_PCT, then zone
and checkpoint fallback). Slot cash is the live engine slot, about $4,255.32. Max DD and
Sharpe still come from the host equity curve, same as the frac-grid bin table. Symbol Paul
Score / FIT aggregates are the host book, not a separate Summary for this slice. Research
only. Not gold. Not DailyRun.</p>
<p class="note">Clear-sky full book: N {nf['n']}, win rate {nf['wr']:.1f}%, average {nf['avg']:.2f}%,
annualized rate of return {nf['ann_ror']:.2f}%, average days held {nf['avg_days']:.1f}.
In-sample Ann ROR {ni['ann_ror']:.2f}% (N {ni['n']}). Out-of-sample Ann ROR {no['ann_ror']:.2f}%
(N {no['n']}, report-only). Full live 22/20/8 book remains on this page: N {cf['n']},
Ann ROR {cf['ann_ror']:.2f}%.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{mhead}</tr></thead><tbody>{''.join(mrows)}</tbody></table></div>
"""
    oh1786_html = ""
    if oh1786 is not None:
        of_, oi, oo = oh1786["slices"]["FULL"], oh1786["slices"]["IS"], oh1786["slices"]["OOS"]
        cf, ci, co = ctrl["slices"]["FULL"], ctrl["slices"]["IS"], ctrl["slices"]["OOS"]
        ff = oh1786_full["slices"]["FULL"] if oh1786_full else None
        fi = oh1786_full["slices"]["IS"] if oh1786_full else None
        fo = oh1786_full["slices"]["OOS"] if oh1786_full else None
        metric_specs = [
            ("n", "Trades", 0, ""),
            ("wr", "Win rate", 1, "%"),
            ("avg", "Avg %", 2, "%"),
            ("median", "Median %", 2, "%"),
            ("pf", "Profit factor", 2, ""),
            ("max_dd", "Max DD %", 2, "%"),
            ("ann_ror", "Annualized rate of return (Ann ROR) %", 2, "%"),
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
        mhead = (
            sortable_th("Metric", "text")
            + sortable_th("17/8/6 overhead-only FULL", "num")
            + sortable_th("17/8/6 overhead-only IS", "num")
            + sortable_th("17/8/6 overhead-only OOS", "num")
            + sortable_th("17/8/6 full book FULL", "num")
            + sortable_th("Δ vs full 17/8/6 FULL", "num")
            + sortable_th("Live 22/20/8 FULL", "num")
            + sortable_th("Δ vs live FULL", "num")
            + sortable_th("Live IS", "num")
            + sortable_th("Live OOS", "num")
        )
        mrows = []
        for key, label, nd, suf in metric_specs:
            full_v = ff[key] if ff else float("nan")
            mrows.append(
                "<tr>"
                f"<td>{esc(label)}</td>"
                f"<td>{fmt(of_[key], nd, suf)}</td>"
                f"<td>{fmt(oi[key], nd, suf)}</td>"
                f"<td>{fmt(oo[key], nd, suf)}</td>"
                f"<td>{fmt(full_v, nd, suf)}</td>"
                f"<td>{prior._delta(of_[key], full_v, nd, suf) if ff else '—'}</td>"
                f"<td>{fmt(cf[key], nd, suf)}</td>"
                f"<td>{prior._delta(of_[key], cf[key], nd, suf)}</td>"
                f"<td>{fmt(ci[key], nd, suf)}</td>"
                f"<td>{fmt(co[key], nd, suf)}</td>"
                "</tr>"
            )
        g_tbl = oh1786.get("g_bin_html") or ""
        full_line = ""
        if ff and fi and fo:
            full_line = (
                f"Full 17/8/6 (all bins, including clear-sky): N {ff['n']}, WR {ff['wr']:.1f}%, "
                f"avg {ff['avg']:.2f}%, PF {ff['pf']:.2f}, Ann ROR {ff['ann_ror']:.2f}% "
                f"(IS {fi['ann_ror']:.2f}%, OOS {fo['ann_ror']:.2f}%, report-only)."
            )
        oh1786_html = f"""
<h2>Extra slice: 17/8/6, overhead zone required (not original 125)</h2>
<p class="note">Paul asked to run 17/8/6 taking <strong>no trades unless there is an overhead
zone</strong>. This is a filter of neighborhood cell <code>oh17_tg08_st06</code> Closed
(reused, not recomputed). Drop clear-sky / no-overhead. Keep any constraining older zone
that still entered (recovered G finite). Do not require G≥22%; 17/8/6 already skips G≤17%.
G recovered the same way as the fraction-grid page (80/40 OVERHEAD_GAP_PCT join, then zone
and checkpoint fallback). Slot cash is the 17/8/6 engine slot, not $47,500. All bins on
the G table is this overhead-only set. Research only. Selection-bias label: post-hoc filter
after seeing the neighborhood. Not gold. Not DailyRun.</p>
<p class="note">Overhead-only: N {of_['n']}, win rate {of_['wr']:.1f}%, average {of_['avg']:.2f}%,
profit factor {of_['pf']:.2f}, annualized rate of return {of_['ann_ror']:.2f}%, average days
held {of_['avg_days']:.1f}. In-sample Ann ROR {oi['ann_ror']:.2f}% (N {oi['n']}). Out-of-sample
Ann ROR {oo['ann_ror']:.2f}% (N {oo['n']}, report-only). Verdict vs live 22/20/8:
{esc(oh1786.get('verdict', ''))} {full_line} Live full book: N {cf['n']}, Ann ROR {cf['ann_ror']:.2f}%.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{mhead}</tr></thead><tbody>{''.join(mrows)}</tbody></table></div>
<h3>Overhead G bins — 17/8/6 overhead-only</h3>
<p class="note">Swipe sideways to see more columns. Click column headers to sort. All bins
(trade all) is the overhead-only set, not the full 17/8/6 book.</p>
{g_tbl}
"""
    t70_html = ""
    if t70g17 is not None:
        of_, oi, oo = t70g17["slices"]["FULL"], t70g17["slices"]["IS"], t70g17["slices"]["OOS"]
        cf, ci, co = ctrl["slices"]["FULL"], ctrl["slices"]["IS"], ctrl["slices"]["OOS"]
        ff = t70_full["slices"]["FULL"] if t70_full else None
        fi = t70_full["slices"]["IS"] if t70_full else None
        fo = t70_full["slices"]["OOS"] if t70_full else None
        ohf = oh1786["slices"]["FULL"] if oh1786 else None
        ohi = oh1786["slices"]["IS"] if oh1786 else None
        oho = oh1786["slices"]["OOS"] if oh1786 else None
        metric_specs = [
            ("n", "Trades", 0, ""),
            ("wr", "Win rate", 1, "%"),
            ("avg", "Avg %", 2, "%"),
            ("median", "Median %", 2, "%"),
            ("pf", "Profit factor", 2, ""),
            ("max_dd", "Max DD %", 2, "%"),
            ("ann_ror", "Annualized rate of return (Ann ROR) %", 2, "%"),
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
        mhead = (
            sortable_th("Metric", "text")
            + sortable_th("70/40 G>=17% FULL", "num")
            + sortable_th("70/40 G>=17% IS", "num")
            + sortable_th("70/40 G>=17% OOS", "num")
            + sortable_th("70/40 full FULL", "num")
            + sortable_th("Δ vs full 70/40 FULL", "num")
            + sortable_th("17/8/6 overhead-only FULL", "num")
            + sortable_th("Live 22/20/8 FULL", "num")
            + sortable_th("Δ vs live FULL", "num")
            + sortable_th("Live IS", "num")
            + sortable_th("Live OOS", "num")
        )
        mrows = []
        for key, label, nd, suf in metric_specs:
            full_v = ff[key] if ff else float("nan")
            oh_v = ohf[key] if ohf else float("nan")
            mrows.append(
                "<tr>"
                f"<td>{esc(label)}</td>"
                f"<td>{fmt(of_[key], nd, suf)}</td>"
                f"<td>{fmt(oi[key], nd, suf)}</td>"
                f"<td>{fmt(oo[key], nd, suf)}</td>"
                f"<td>{fmt(full_v, nd, suf)}</td>"
                f"<td>{prior._delta(of_[key], full_v, nd, suf) if ff else '—'}</td>"
                f"<td>{fmt(oh_v, nd, suf)}</td>"
                f"<td>{fmt(cf[key], nd, suf)}</td>"
                f"<td>{prior._delta(of_[key], cf[key], nd, suf)}</td>"
                f"<td>{fmt(ci[key], nd, suf)}</td>"
                f"<td>{fmt(co[key], nd, suf)}</td>"
                "</tr>"
            )
        g_tbl = t70g17.get("g_bin_html") or ""
        full_line = ""
        if ff and fi and fo:
            full_line = (
                f"Full 70/40 (all G, including clear-sky): N {ff['n']}, WR {ff['wr']:.1f}%, "
                f"avg {ff['avg']:.2f}%, PF {ff['pf']:.2f}, Ann ROR {ff['ann_ror']:.2f}% "
                f"(IS {fi['ann_ror']:.2f}%, OOS {fo['ann_ror']:.2f}%, report-only)."
            )
        oh_line = ""
        if ohf and ohi and oho:
            oh_line = (
                f" 17/8/6 overhead-only: N {ohf['n']}, WR {ohf['wr']:.1f}%, avg {ohf['avg']:.2f}%, "
                f"PF {ohf['pf']:.2f}, Ann ROR {ohf['ann_ror']:.2f}% "
                f"(IS {ohi['ann_ror']:.2f}%, OOS {oho['ann_ror']:.2f}%, report-only)."
            )
        t70_html = f"""
<h2>Extra slice: 70/40 dynamic, overhead G≥17% only (not original 125)</h2>
<p class="note">Paul asked what happens if we build the 70/40 dynamic target/stop on top of
the G≥17% overhead idea. This extra slice filters the existing 70/40 Closed from the
fraction-grid stamp (reused, not recomputed). Drop clear-sky / no-overhead. Drop G&lt;17%.
Keep G≥17%. Target and stop stay the 70/40 sizer already on those fills
(target = 70% of gap G, stop under trigger-day low = 40% of that target). 17% is the
skip/floor, not a fixed 17/8/6 exit. Slot cash is the 70/40 engine slot, not $47,500 and
not the 90/40 $2,362 slot. All bins on the G table is this G≥17% set. Research only.
Selection-bias label: post-hoc filter. Not gold. Not DailyRun. This does not replace any
of the original 125 cells.</p>
<p class="note">70/40 G≥17%: N {of_['n']}, win rate {of_['wr']:.1f}%, average {of_['avg']:.2f}%,
profit factor {of_['pf']:.2f}, annualized rate of return {of_['ann_ror']:.2f}%, average days
held {of_['avg_days']:.1f}. In-sample Ann ROR {oi['ann_ror']:.2f}% (N {oi['n']}). Out-of-sample
Ann ROR {oo['ann_ror']:.2f}% (N {oo['n']}, report-only). Verdict vs live 22/20/8:
{esc(t70g17.get('verdict', ''))} {full_line}{oh_line} Live full book: N {cf['n']},
Ann ROR {cf['ann_ror']:.2f}%.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{mhead}</tr></thead><tbody>{''.join(mrows)}</tbody></table></div>
<h3>Overhead G bins — 70/40 G≥17% only</h3>
<p class="note">Swipe sideways to see more columns. Click column headers to sort. Bins are
17–22, 22–30, and G&gt;30. All bins (trade all) is this filtered set, not the full 70/40 book.</p>
{g_tbl}
"""
    center_b = by_key.get(CENTER)
    center_line = "Center 15/10/4 was not loaded."
    if center_b:
        cf, ci = center_b["slices"]["FULL"], center_b["slices"]["IS"]
        center_line = (
            f"Center 15/10/4: N {cf['n']}, win rate {cf['wr']:.1f}%, average {cf['avg']:.2f}%, "
            f"profit factor {cf['pf']:.2f}, full-book annualized rate of return {cf['ann_ror']:.2f}%, "
            f"in-sample {ci['ann_ror']:.2f}%. Verdict versus live: {center_b.get('verdict_word')}."
        )
    keep_any = "A cell cleared the KEEP bar." if words.get("KEEP") else "No original-grid cell is a KEEP versus the live 22/20/8 book on this bar. Calls are HOLD or DISMISS."

    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR 15/10/4 neighborhood</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1c1917; max-width: 1200px; }}
.callout {{ background: #f5f5f4; border-left: 4px solid #44403c; padding: 12px 16px; margin: 12px 0 20px; }}
blockquote {{ margin: 8px 0; }}
td, th {{ padding: 4px 8px; border-bottom: 1px solid #e7e5e4; white-space: nowrap; }}
td {{ text-align: right; }}
td:first-child, th:first-child {{ text-align: left; }}
.note {{ font-size: 0.95rem; color: #44403c; }}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style>
</head><body>
<h1>Pivot Break and Retest — neighborhood around 15 / 10 / 4</h1>
<p class="note">Research only. Not gold. Not DailyRun. Click column headers to sort.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{esc(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>Pivot Break and Retest (WPBR) is the weekly-zone retest the live book already trades. This page is the neighborhood around the package with 15% overhead, a 10% target above the buy, and a 4% stop. Every combination is here: overhead 13 to 17, target 8 to 12, and stop 2 to 6. That is 125 cells, including 15/12/4 and 15/12/5. The stop is still under the trigger-day low, not under the entry. The live rule stays 22% overhead, 20% target, and 8% stop.</p>
<p>Paul also asked to park seven extra packages on this same summary: 16/7/3, 16/7/4, 16/7/5, 17/7/2, 17/7/3, 17/7/4, and 17/7/5. Those use a 7% profit target, which is outside the original grid (that grid is target 8–12). They are labeled extra. They are not one of the 125 frozen cells and they do not change DailyRun.</p>
<p>He also asked to write the live 22/20/8 freeze here as the <strong>no-overhead (clear sky)</strong> slice only — trades with no constraining older zone. That is not the G≥22% subset, and it is not part of the 125-cell grid.</p>
<p>He also asked to run the existing 17/8/6 package taking no trades unless there is an overhead zone. That extra slice drops clear-sky buys from the 17/8/6 Closed book. It is not one of the original 125. The full 17/8/6 cell stays in the grid. DailyRun stays 22/20/8.</p>
<p>He also asked what happens if we put the 70/40 dynamic target and stop on top of the G≥17% overhead floor: drop clear-sky, drop G&lt;17%, keep 70/40 sizing on the rest. That is an extra labeled slice of the existing 70/40 Closed, not a new 125-cell. 17% is the skip/floor; 70/40 is the sizer, not a fixed 17/8/6 exit.</p>
<p>This whole grid is an in-sample search around one package that looked interesting. A cell that looks best on the table is in-sample selection. Nothing here is adopted. Out of sample (buys from 2024 onward) is report-only. The annualized rate of return is the compound pace of the book from the profit per trade, the cash set aside for each trade, and how many days the trade is held.</p>
</div>
<h2>How the numbers map</h2>
<p>Confirmed in <code>rocket_tbn.py</code>: <code>stop_loss_based=trigger_low</code> and <code>stop_pct_is_multiplier=true</code>, so the stop is the trigger-day low times <code>stop_pct</code>. A 4% stop is 0.96 and an 8% stop is 0.92. The target is the entry price times <code>target_pct</code> (10% above the buy is 1.10, 20% is 1.20). Overhead is <code>wpbr_overhead_band_pct</code> (15% is 0.15). Workers inside each engine process: {WORKERS}. Processes at once after the CPU check: {cap}. CPU note from the first wave: {esc(cpu_txt or "not recorded")}.</p>
<p class="note">{esc(center_line)} {esc(keep_any)} Original 125 counts: KEEP {words.get("KEEP", 0)}, HOLD {words.get("HOLD", 0)}, DISMISS {words.get("DISMISS", 0)}. Highest in-sample annualized rate of return on the original 125: {esc(is_best_s)} (in-sample selection, not adopted). Highest out-of-sample annualized rate of return on the original 125: {esc(oos_best_s)} (report-only). Extra packages loaded: {len(extra_cells)}/7.</p>
<h2>Verdict bar</h2>
<p class="note">Same bar as the tighter-package page, versus the live 22/20/8 book, judged on in-sample quality. In-sample annualized rate of return is the headline, because a lower target cuts the average win on purpose. Worse in-sample annualized rate of return is DISMISS. A lift of 0.25 percentage points or less is HOLD. A larger lift is HOLD if out-of-sample annualized rate of return is softer than the live book by more than 0.25 points, or if in-sample profit factor drops by more than 0.05, maximum drawdown worsens by more than 1 point, or in-sample trades fall below 85% of the live book. That is why a higher annualized rate of return with a worse average and a worse profit factor was HOLD on 15/10/4, not KEEP. Otherwise the call would be KEEP as research only. Not gold. Not a live change. Live slot cash on this page is about $4,255, the engine slot, not $47,500.</p>
{SWIPE_NOTE_HTML}
<h2>In-sample annualized rate of return</h2>
<p class="note">Each number is the in-sample annualized rate of return for that overhead, target, and stop on the original 125 only (target 8–12). Extra target-7 packages are in the table below, not in this heatmap. Greener is higher inside this grid only. The center cell is marked.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{hhead}</tr></thead><tbody>{''.join(hrows)}</tbody></table></div>
{noh_html}
{oh1786_html}
{t70_html}
{extra_html}
<h2>Every cell</h2>
<p class="note">Original 125 plus extra packages plus extra slices (live 22/20/8 no-overhead, 17/8/6 overhead-only, and 70/40 G≥17%). Full book, then in-sample (entry before 2024-01-01) and out-of-sample (entry on or after 2024-01-01). Out of sample does not pick a winner. The Set column marks extra packages and extra slices.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="note">Picking the best cell after this table is in-sample selection. Not gold. Not DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(page, encoding="utf-8")
    return path


def write_baseline(books: list[dict[str, Any]], cap: int, cpu_txt: str) -> None:
    ctrl = next(b for b in books if b["id"] == "control")
    noh = next((b for b in books if b["id"] == CTRL_NOH_ID), None)
    oh1786 = next((b for b in books if b["id"] == OH1786_OH_ID), None)
    t70g17 = next((b for b in books if b["id"] == T70_G17_ID), None)
    cells = [b for b in books if b["id"] not in ("control", CTRL_NOH_ID, OH1786_OH_ID, "oh17_tg08_st06_full_for_slice", T70_G17_ID, "t70_s40_full_for_slice")]
    is_best = _best(books, "IS", extras=False)
    oos_best = _best(books, "OOS", extras=False)
    extra_is = _best(books, "IS", extras=True)
    extra_oos = _best(books, "OOS", extras=True)
    grid_cells = [b for b in cells if not b.get("extra")]
    extra_cells = [b for b in cells if b.get("extra")]
    lines = [
        "# WPBR neighborhood around 15/10/4",
        "",
        "Pivot Break and Retest (WPBR). Research only. Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "Pivot Break and Retest (WPBR) is the weekly-zone retest the live book already trades. "
        "This test is the neighborhood around the 15% overhead, 10% target, 4% stop package. "
        "Every combination from 13 to 17 overhead, 8 to 12 target, and 2 to 6 stop is in the grid. "
        "The stop is still under the trigger-day low. The live rule stays 22 / 20 / 8.",
        "",
        "Seven extra packages with a 7% target sit on the same page: 16/7/3, 16/7/4, 16/7/5, "
        "17/7/2, 17/7/3, 17/7/4, and 17/7/5. They are not part of the original 125. "
        "Target 7 is outside the frozen neighborhood (target 8-12). DailyRun stays 22/20/8.",
        "",
        "Paul also asked for the live 22/20/8 freeze as the no-overhead (clear sky) slice only: "
        "trades with no constraining older zone. That is not the G>=22% subset and not part of "
        "the original 125. Same Closed stamp 261002051403 and the same G recovery as the "
        "fraction-grid page (80/40 OVERHEAD_GAP_PCT join). Research only.",
        "",
        "Paul also asked to run 17/8/6 taking no trades unless there is an overhead zone. "
        "That extra slice filters neighborhood cell oh17_tg08_st06 Closed (not recomputed): "
        "drop clear-sky, keep finite recovered G. Do not require G>=22%. It is not part of "
        "the original 125. Full 17/8/6 stays in the grid. Slot cash is the 17/8/6 engine "
        "slot, not $47,500. Research only. Post-hoc filter = selection bias. Not DailyRun.",
        "",
        "Paul also asked to put 70/40 dynamic target/stop on trades with overhead G>=17%: "
        "drop clear-sky, drop G<17%, keep the 70/40 sizer (not fixed 17/8/6). Extra labeled "
        "slice of the existing 70/40 Closed. Not part of the original 125. Slot cash is the "
        "70/40 engine slot. Research only. Post-hoc filter = selection bias. Not DailyRun.",
        "",
        "This whole grid is an in-sample search around one package. "
        "A cell that looks best on the table is in-sample selection. Do not adopt a winner. "
        "Out of sample is report-only. The annualized rate of return uses the house formula.",
        "",
        "## Freeze",
        "",
        "- Grid, frozen before new P&L: overhead 13â€“17, target 8â€“12, stop 2â€“6. 125 cells. No cells added or dropped.",
        "- Extra packages (not in the 125): 16/7/3, 16/7/4, 16/7/5, 17/7/2, 17/7/3, 17/7/4, 17/7/5. Closed reused from tmp_wpbr_dynamic_overhead_frac_grid_20261002 when present.",
        "- Engine mapping: wpbr_overhead_band_pct = overhead/100. target_pct = 1 + target/100 (entry times that). stop_pct = 1 - stop/100 because stop_loss_based=trigger_low and stop_pct_is_multiplier=true (trigger-day low times stop_pct). 4% -> 0.96, 2% -> 0.98. 7% target -> 1.07.",
        "- Other knobs match run_wpbr.bat: growth filter off, min_history_bars=0, full warehouse data/newdata/data, same zone, breakout, and retest knobs. Only overhead, target, and stop change.",
        "- Control is stamp 261002051403, not rerun: tmp_wpbr_overhead20_vs22_t20s8_ab_20261002/control. 22% overhead, 20% target, 8% stop.",
        f"- Control full N {ctrl['slices']['FULL']['n']}, Ann ROR {ctrl['slices']['FULL']['ann_ror']:.2f}%, in-sample {ctrl['slices']['IS']['ann_ror']:.2f}%, slot ${ctrl['cash']:,.2f}.",
        (
            "- Extra slice, live 22/20/8 no overhead (clear sky), not in the 125, not G>=22%: "
            + (
                f"FULL N {noh['slices']['FULL']['n']}, WR {noh['slices']['FULL']['wr']:.1f}%, "
                f"avg {noh['slices']['FULL']['avg']:.2f}%, Ann ROR {noh['slices']['FULL']['ann_ror']:.2f}%, "
                f"days {noh['slices']['FULL']['avg_days']:.1f}; "
                f"IS N {noh['slices']['IS']['n']} Ann ROR {noh['slices']['IS']['ann_ror']:.2f}%; "
                f"OOS N {noh['slices']['OOS']['n']} Ann ROR {noh['slices']['OOS']['ann_ror']:.2f}% (report-only). "
                "Same slot cash. Source Closed 261002051403 + frac-grid G recovery."
                if noh
                else "not loaded."
            )
        ),
        (
            "- Extra slice, 17/8/6 overhead-only (not in the 125): "
            + (
                f"FULL N {oh1786['slices']['FULL']['n']}, WR {oh1786['slices']['FULL']['wr']:.1f}%, "
                f"avg {oh1786['slices']['FULL']['avg']:.2f}%, PF {oh1786['slices']['FULL']['pf']:.2f}, "
                f"Ann ROR {oh1786['slices']['FULL']['ann_ror']:.2f}%, days {oh1786['slices']['FULL']['avg_days']:.1f}; "
                f"IS N {oh1786['slices']['IS']['n']} Ann ROR {oh1786['slices']['IS']['ann_ror']:.2f}%; "
                f"OOS N {oh1786['slices']['OOS']['n']} Ann ROR {oh1786['slices']['OOS']['ann_ror']:.2f}% (report-only). "
                f"Slot ${oh1786['cash']:,.2f}. Verdict {oh1786.get('verdict_word')}. "
                "Closed oh17_tg08_st06 + frac-grid G recovery. Not DailyRun."
                if oh1786
                else "not loaded."
            )
        ),
        (
            "- Extra slice, 70/40 overhead G>=17% only (not in the 125): "
            + (
                f"FULL N {t70g17['slices']['FULL']['n']}, WR {t70g17['slices']['FULL']['wr']:.1f}%, "
                f"avg {t70g17['slices']['FULL']['avg']:.2f}%, PF {t70g17['slices']['FULL']['pf']:.2f}, "
                f"Ann ROR {t70g17['slices']['FULL']['ann_ror']:.2f}%, days {t70g17['slices']['FULL']['avg_days']:.1f}; "
                f"IS N {t70g17['slices']['IS']['n']} Ann ROR {t70g17['slices']['IS']['ann_ror']:.2f}%; "
                f"OOS N {t70g17['slices']['OOS']['n']} Ann ROR {t70g17['slices']['OOS']['ann_ror']:.2f}% (report-only). "
                f"Slot ${t70g17['cash']:,.2f}. Verdict {t70g17.get('verdict_word')}. "
                "Filter of 70/40 Closed (drop clear-sky and G<17%; keep 70/40 sizer). Not DailyRun."
                if t70g17
                else "not loaded."
            )
        ),
        "- Center 15/10/4 reused from tmp_wpbr_tighter_overhead_target_stop_ab_20261002/pkg_15_10_4 when knobs matched. Not recomputed.",
        f"- Parallel: {WORKERS} workers inside each engine process. Cap {cap} engine processes after the CPU check. CPU record: {cpu_txt or 'n/a'}.",
        "- In-sample is DATE_OPENED before 2024-01-01. Out of sample is DATE_OPENED on or after 2024-01-01.",
        "- Verdict uses the prior page's bar (Ann ROR headline; profit-factor drop over 0.05, drawdown worse by more than 1 point, or trade count under 85% is HOLD). Higher Ann ROR with a worse profit factor is HOLD, as 15/10/4 was. Not adopted.",
        "",
        "## Read of the table (in-sample selection)",
        "",
        "- Highest in-sample annualized rate of return (original 125): " + ", ".join(b["short"] for b in is_best),
        "- Highest out-of-sample annualized rate of return on original 125 (report-only): " + ", ".join(b["short"] for b in oos_best),
        "- Original 125 KEEP count: " + str(sum(1 for b in grid_cells if b.get("verdict_word") == "KEEP")),
        "- Original 125 HOLD count: " + str(sum(1 for b in grid_cells if b.get("verdict_word") == "HOLD")),
        "- Original 125 DISMISS count: " + str(sum(1 for b in grid_cells if b.get("verdict_word") == "DISMISS")),
        "- Extra packages loaded: " + str(len(extra_cells)) + "/7",
        "- Highest extra in-sample Ann ROR: " + (", ".join(b["short"] for b in extra_is) or "-"),
        "- Highest extra out-of-sample Ann ROR (report-only): " + (", ".join(b["short"] for b in extra_oos) or "-"),
        "- Extra KEEP/HOLD/DISMISS: "
        + str(sum(1 for b in extra_cells if b.get("verdict_word") == "KEEP")) + "/"
        + str(sum(1 for b in extra_cells if b.get("verdict_word") == "HOLD")) + "/"
        + str(sum(1 for b in extra_cells if b.get("verdict_word") == "DISMISS")),
        "",
        "Not gold. Not DailyRun.",
        "",
    ]
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def notify(html_path: Path) -> None:
    subprocess.run(
        [PY, str(ROOT / "tools" / "ntfy_job_done.py"),
         "--path", str(html_path.relative_to(ROOT)).replace("\\", "/"),
         "-t", "WPBR 15/10/4 neighborhood"],
        cwd=str(ROOT), check=False,
    )


def main() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "pids").mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lock = RUNS / "supervisor.pid"
    if lock.exists():
        try:
            old = int(lock.read_text(encoding="utf-8").strip())
        except ValueError:
            old = 0
        if old and old != os.getpid() and alive(old):
            log(f"[exit] supervisor already running pid={old}")
            return
    lock.write_text(str(os.getpid()), encoding="utf-8")
    log(f"[supervisor] pid={os.getpid()} cells={len(CELLS)} workers={WORKERS}")
    prior = _load_prior()

    books: list[dict[str, Any]] = []
    scored: set[str] = set()

    ctrl_spec = {
        "id": "control", "short": "22/20/8 live", "role": "control", "center": False,
        "overhead": 0.22, "target_above": 0.20, "stop_under": 0.08,
        "target_pct": 1.20, "stop_pct": 0.92, "folder": CONTROL_DIR,
    }
    if not prior._knobs_match(prior._read_report(CONTROL_DIR), 0.22, 1.20, 0.92):
        raise SystemExit("control knobs do not match 22/20/8")
    books.append(prior._score_book(ctrl_spec))
    scored.add("control")
    log(
        f"[control] N={books[0]['slices']['FULL']['n']} "
        f"ann={books[0]['slices']['FULL']['ann_ror']:.2f} "
        f"is={books[0]['slices']['IS']['ann_ror']:.2f} cash={books[0]['cash']:.2f}"
    )

    center_folder = REUSE_CENTER
    if _done_folder(center_folder, *CENTER, prior=prior):
        book = score_one(prior, *CENTER, center_folder, "center-reused")
        books.append(book)
        scored.add(cell_id(*CENTER))
        log(
            f"[reuse center] N={book['slices']['FULL']['n']} "
            f"wr={book['slices']['FULL']['wr']:.1f} avg={book['slices']['FULL']['avg']:.2f} "
            f"ann={book['slices']['FULL']['ann_ror']:.2f} is={book['slices']['IS']['ann_ror']:.2f}"
        )
    else:
        log("[reuse center] knobs mismatch or missing; cell will be run")

    apply_verdicts(prior, books)
    checkpoint(prior, books)

    running = adopt_running()
    reset_incomplete_tries(prior)
    log(f"[adopt] {len(running)} live cells cap={read_cap()} engines={engine_count()}")

    # Ingest finished folders before launching so scored cells are never recomputed.
    for oh, tg, st in CELLS:
        cid = cell_id(oh, tg, st)
        if cid in scored:
            continue
        folder = RUNS / cid
        if _done_folder(folder, oh, tg, st, prior=prior):
            try:
                book = score_one(prior, oh, tg, st, folder, "grid")
                books.append(book)
                scored.add(cid)
                log(
                    f"[ingest] {cid} N={book['slices']['FULL']['n']} "
                    f"is_ann={book['slices']['IS']['ann_ror']:.2f} "
                    f"scored={len(scored)-1}/125"
                )
            except Exception as exc:
                log(f"[ingest-error] {cid} {exc}")
    apply_verdicts(prior, books)
    checkpoint(prior, books)
    log(f"[ingest] ready scored_cells={len(scored)-1}/125")

    pending = [c for c in CELLS if cell_id(*c) not in scored]
    fails: dict[str, str] = {}

    while pending or running:
        running = {cid: pid for cid, pid in list(running.items()) if alive(pid)}
        # also drop scored
        running = {cid: pid for cid, pid in running.items() if cid not in scored}

        finished_ids = []
        for oh, tg, st in CELLS:
            cid = cell_id(oh, tg, st)
            if cid in scored or cid in running:
                continue
            pid = read_pid(cid)
            if pid and not alive(pid) and read_tries(cid) > 0:
                folder = RUNS / cid
                if _done_folder(folder, oh, tg, st, prior=prior):
                    finished_ids.append((oh, tg, st, folder))
                elif read_tries(cid) < MAX_TRIES:
                    if (oh, tg, st) not in pending:
                        log(f"[retry] {cid} tries={read_tries(cid)} no closed file")
                        pending.append((oh, tg, st))
                else:
                    fails[cid] = "no complete closed file after retries"
                    scored.add(cid)
                    log(f"[fail] {cid}")

        for oh, tg, st, folder in finished_ids:
            cid = cell_id(oh, tg, st)
            try:
                book = score_one(prior, oh, tg, st, folder, "grid")
                books.append(book)
                scored.add(cid)
                pending = [c for c in pending if cell_id(*c) != cid]
                apply_verdicts(prior, books)
                checkpoint(prior, books)
                log(
                    f"[done] {cid} N={book['slices']['FULL']['n']} "
                    f"is_ann={book['slices']['IS']['ann_ror']:.2f} {book['verdict_word']} "
                    f"scored={len(scored)-1}/125"
                )
            except Exception as exc:
                log(f"[score-error] {cid} {exc}")
                if read_tries(cid) < MAX_TRIES and (oh, tg, st) not in pending:
                    pending.append((oh, tg, st))
                else:
                    fails[cid] = str(exc)
                    scored.add(cid)

        # Hard pause: Paul / parent can drop PAUSE_LAUNCHES.txt to stop all new cells.
        if (RUNS / "PAUSE_LAUNCHES.txt").exists():
            log(
                f"[paused] launches frozen; scored={len(scored) - 1} "
                f"running={len(running)} pending={len(pending)}"
            )
            time.sleep(45)
            continue

        cap = read_cap()
        # New cell only when neighborhood engines < cap.
        # Cap=2 Ã— -w8 is expected to peg CPU; do not CPU-gate under the cap.
        # Processes already above the cap are left running (drain, no kills).
        guard = 0
        while pending and guard < max(cap, 1):
            guard += 1
            n_eng = neighborhood_engine_count()
            cpu_now = cpu_load()
            (RUNS / "cpu_check.txt").write_text(
                f"LoadPercentage average {cpu_now:.1f}; hard cap {cap}; "
                f"neighborhood engines seen {n_eng}; launch only if count < {cap} "
                f"(CPU gate off under cap; -w8Ã—2 pegs cores by design)",
                encoding="utf-8",
            )
            log(
                f"[gate] neigh_engines={n_eng} cpu={cpu_now:.1f} cap={cap} "
                f"scored={len(scored) - 1} running={len(running)}"
            )
            if n_eng < 0 or n_eng >= cap or len(running) >= cap:
                break
            # skip cells already running
            nxt = None
            for item in list(pending):
                cid = cell_id(*item)
                if cid in scored or cid in running:
                    continue
                if alive(read_pid(cid)):
                    running[cid] = read_pid(cid)
                    continue
                if build_cmd_line_guard(cid):
                    continue
                if _done_folder(RUNS / cid, *item, prior=prior):
                    pending.remove(item)
                    finished_ids.append((*item, RUNS / cid))
                    continue
                nxt = item
                break
            if nxt is None:
                break
            if read_tries(cell_id(*nxt)) >= MAX_TRIES:
                pending.remove(nxt)
                fails[cell_id(*nxt)] = "max tries"
                continue
            pid = launch_cell(*nxt)
            if pid:
                running[cell_id(*nxt)] = pid
            pending.remove(nxt)

        if len(scored) - 1 >= 125 and not running:
            break
        time.sleep(45)

    apply_verdicts(prior, books)
    checkpoint(prior, books)
    n_cells = len([b for b in books if b["id"] != "control"])
    log(f"[grid] scored_cells={n_cells} fails={fails}")
    if n_cells < 125 or fails:
        log("[stop] grid incomplete; not writing final notify")
        (RUNS / "FAILED.txt").write_text(repr(fails), encoding="utf-8")
        return
    cap = read_cap()
    cpu_txt = read_cpu()
    html_path = write_html(prior, books, cap, cpu_txt)
    write_baseline(books, cap, cpu_txt)
    log(f"[wrote] {html_path}")
    notify(html_path)
    is_best = ", ".join(b["short"] for b in _best(books, "IS"))
    oos_best = ", ".join(b["short"] for b in _best(books, "OOS"))
    keep = [b["short"] for b in books if b.get("verdict_word") == "KEEP"]
    center = next(b for b in books if b.get("center"))
    log(
        f"[PARENT] cells={n_cells}/125 center_N={center['slices']['FULL']['n']} "
        f"center_wr={center['slices']['FULL']['wr']:.1f} center_avg={center['slices']['FULL']['avg']:.2f} "
        f"center_ann={center['slices']['FULL']['ann_ror']:.2f} center_is={center['slices']['IS']['ann_ror']:.2f} "
        f"is_best={is_best} oos_best={oos_best} keep={keep or 'none'} "
        f"cap={cap} cpu={cpu_txt} html={html_path}"
    )


def append_extras() -> None:
    """Rescore original 125 from existing Closed and append extra target-7 packages.

    Does not launch original grid cells. Does not kill a live supervisor.
    Extra Closed is reused from frac-grid tmp or neighborhood tmp.
    """
    lock = RUNS / "supervisor.pid"
    if lock.exists():
        try:
            old = int(lock.read_text(encoding="utf-8").strip())
        except ValueError:
            old = 0
        if old and old != os.getpid() and alive(old):
            log(f"[append-extras] supervisor live pid={old}; scoring extras only if Closed exists, no original launches")
    prior = _load_prior()
    books: list[dict[str, Any]] = []
    ctrl_spec = {
        "id": "control", "short": "22/20/8 live", "role": "control", "center": False,
        "extra": False,
        "overhead": 0.22, "target_above": 0.20, "stop_under": 0.08,
        "target_pct": 1.20, "stop_pct": 0.92, "folder": CONTROL_DIR,
    }
    if not prior._knobs_match(prior._read_report(CONTROL_DIR), 0.22, 1.20, 0.92):
        raise SystemExit("control knobs do not match 22/20/8")
    ctrl = prior._score_book(ctrl_spec)
    ctrl["extra"] = False
    books.append(ctrl)
    scored: set[str] = {"control"}
    if _done_folder(REUSE_CENTER, *CENTER, prior=prior):
        books.append(score_one(prior, *CENTER, REUSE_CENTER, "center-reused"))
        scored.add(cell_id(*CENTER))
    for oh, tg, st in CELLS:
        cid = cell_id(oh, tg, st)
        if cid in scored:
            continue
        folder = RUNS / cid
        if _done_folder(folder, oh, tg, st, prior=prior):
            books.append(score_one(prior, oh, tg, st, folder, "grid"))
            scored.add(cid)
            log(f"[ingest] {cid} scored_grid={len(scored)-1}/125")
    extras_ok = 0
    for oh, tg, st in EXTRA_CELLS:
        cid = cell_id(oh, tg, st)
        folder = extra_folder(oh, tg, st, prior)
        if folder is None:
            log(f"[extra-missing] {cid}")
            continue
        books.append(score_one(prior, oh, tg, st, folder, "extra (not in original 125)", extra=True))
        extras_ok += 1
        log(f"[extra] {cid} from {folder}")
    books.append(score_control_no_overhead(ctrl))
    log("[extra] control no-overhead (clear sky) from stamp 261002051403")
    oh1786, oh1786_full = score_oh17_overhead_only(ctrl, prior)
    books.append(oh1786)
    books.append(oh1786_full)
    log("[extra] 17/8/6 overhead-only from oh17_tg08_st06 Closed")
    apply_verdicts(prior, books)
    checkpoint(prior, books)
    html_path = write_html(prior, books, read_cap(), read_cpu())
    write_baseline(books, read_cap(), read_cpu())
    log(f"[append-extras] grid={len(scored)-1}/125 extras={extras_ok}/7 html={html_path}")
    if extras_ok < 7:
        raise SystemExit(f"append-extras missing {7 - extras_ok} extra Closed books")


def append_t70_g17() -> None:
    """Add 70/40 G>=17% extra slice without rescoring the original 125."""
    from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, sortable_th  # noqa: F401
    from report_page_extras import SWIPE_NOTE_HTML

    prior = _load_prior()
    ctrl_spec = {
        "id": "control", "short": "22/20/8 live", "role": "control", "center": False,
        "overhead": 0.22, "target_above": 0.20, "stop_under": 0.08,
        "target_pct": 1.20, "stop_pct": 0.92, "folder": CONTROL_DIR,
    }
    ctrl = prior._score_book(ctrl_spec)
    t70g17, t70_full = score_t70_g17(ctrl)
    oh1786 = None
    path_sum = OUT_DIR / "summary.csv"
    if path_sum.is_file():
        by = {}
        with path_sum.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("arm_id") == OH1786_OH_ID and not (r.get("g_bin") or "").strip():
                    sl = r.get("slice")
                    by[sl] = r
        if {"FULL", "IS", "OOS"} <= set(by):
            def _m(row: dict[str, str]) -> dict[str, Any]:
                def f(k: str, src: str) -> float:
                    try:
                        return float(row.get(src) or "nan")
                    except ValueError:
                        return float("nan")
                return {
                    "n": int(float(row["n"])) if row.get("n") else 0,
                    "wr": f("wr", "win_rate"),
                    "avg": f("avg", "avg_pct"),
                    "median": f("median", "median_pct"),
                    "pf": f("pf", "profit_factor"),
                    "max_dd": f("max_dd", "max_dd_pct"),
                    "ann_ror": f("ann_ror", "ann_ror_pct"),
                    "avg_days": f("avg_days", "avg_days"),
                    "med_days": f("med_days", "median_days"),
                    "avg_win": f("avg_win", "avg_win_pct"),
                    "avg_loss": f("avg_loss", "avg_loss_pct"),
                    "expect": f("expect", "expectancy_pct"),
                    "wo_max": f("wo_max", "avg_without_max_pct"),
                    "calmar": f("calmar", "calmar"),
                    "sharpe": f("sharpe", "sharpe"),
                    "tpy": f("tpy", "trades_per_year"),
                }
            oh1786 = {
                "id": OH1786_OH_ID,
                "short": "17/8/6 overhead-only",
                "slices": {k: _m(by[k]) for k in ("FULL", "IS", "OOS")},
                "cash": float(by["FULL"].get("slot_cash") or 0),
                "verdict": by["FULL"].get("verdict", ""),
                "verdict_word": by["FULL"].get("verdict", ""),
            }

    existing: list[dict[str, str]] = []
    fields: list[str] = []
    if path_sum.is_file():
        with path_sum.open(newline="", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            fields = list(rdr.fieldnames or [])
            existing = [r for r in rdr if r.get("arm_id") not in {T70_G17_ID, f"{T70_G17_ID}_gbin"}]
    dummy = [ctrl, t70g17]
    checkpoint(prior, dummy)
    # checkpoint just wrote control+t70 only — restore grid rows then add t70.
    if existing and fields:
        with path_sum.open(newline="", encoding="utf-8") as f:
            t70_rows = [r for r in csv.DictReader(f) if str(r.get("arm_id") or "").startswith(T70_G17_ID)]
        with path_sum.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in existing:
                w.writerow({k: r.get(k, "") for k in fields})
            for r in t70_rows:
                w.writerow({k: r.get(k, "") for k in fields})
    log(f"[append-t70-g17] summary rows restored; t70 N={t70g17['slices']['FULL']['n']}")

    html_path = OUT_DIR / "compare.html"
    html = html_path.read_text(encoding="utf-8")
    books = [ctrl, t70g17, t70_full]
    if oh1786:
        books.append(oh1786)
    # Rebuild only the extra-slice markup via write_html's helpers by calling write_html
    # would wipe the 125. Inject a compact section instead.
    of_, oi, oo = t70g17["slices"]["FULL"], t70g17["slices"]["IS"], t70g17["slices"]["OOS"]
    cf, ci, co = ctrl["slices"]["FULL"], ctrl["slices"]["IS"], ctrl["slices"]["OOS"]
    ff = t70_full["slices"]["FULL"]
    fi = t70_full["slices"]["IS"]
    fo = t70_full["slices"]["OOS"]
    ohf = oh1786["slices"]["FULL"] if oh1786 else None
    snippet = (
        "<h2>Extra slice: 70/40 dynamic, overhead G≥17% only (not original 125)</h2>\n"
        "<p class=\"note\">Paul asked what happens if we build the 70/40 dynamic target/stop on top of "
        "the G≥17% overhead idea. This extra slice filters the existing 70/40 Closed from the "
        "fraction-grid stamp (reused, not recomputed). Drop clear-sky / no-overhead. Drop G&lt;17%. "
        "Keep G≥17%. Target and stop stay the 70/40 sizer already on those fills "
        "(target = 70% of gap G, stop under trigger-day low = 40% of that target). 17% is the "
        "skip/floor, not a fixed 17/8/6 exit. Slot cash is the 70/40 engine slot, not $47,500 and "
        "not the 90/40 $2,362 slot. All bins on the G table is this G≥17% set. Research only. "
        "Selection-bias label: post-hoc filter. Not gold. Not DailyRun. This does not replace any "
        "of the original 125 cells.</p>\n"
        f"<p class=\"note\">70/40 G≥17%: N {of_['n']}, win rate {of_['wr']:.1f}%, average {of_['avg']:.2f}%, "
        f"profit factor {of_['pf']:.2f}, annualized rate of return {of_['ann_ror']:.2f}%, average days "
        f"held {of_['avg_days']:.1f}. In-sample Ann ROR {oi['ann_ror']:.2f}% (N {oi['n']}). Out-of-sample "
        f"Ann ROR {oo['ann_ror']:.2f}% (N {oo['n']}, report-only). Verdict vs live 22/20/8: "
        f"{esc(t70g17.get('verdict', ''))} Full 70/40 (all G, including clear-sky): N {ff['n']}, "
        f"WR {ff['wr']:.1f}%, avg {ff['avg']:.2f}%, PF {ff['pf']:.2f}, Ann ROR {ff['ann_ror']:.2f}% "
        f"(IS {fi['ann_ror']:.2f}%, OOS {fo['ann_ror']:.2f}%, report-only)."
        + (
            f" 17/8/6 overhead-only: N {ohf['n']}, WR {ohf['wr']:.1f}%, avg {ohf['avg']:.2f}%, "
            f"PF {ohf['pf']:.2f}, Ann ROR {ohf['ann_ror']:.2f}%."
            if ohf else ""
        )
        + f" Live full book: N {cf['n']}, Ann ROR {cf['ann_ror']:.2f}%.</p>\n"
        + SWIPE_NOTE_HTML
        + (t70g17.get("g_bin_html") or "")
    )
    marker = "<h2>Extra packages (target 7"
    start = "Extra slice: 70/40 dynamic"
    if start in html:
        # replace prior injected block between this h2 and Extra packages
        i = html.find("<h2>Extra slice: 70/40 dynamic")
        j = html.find(marker)
        if i >= 0 and j > i:
            html = html[:i] + snippet + "\n" + html[j:]
        log("[append-t70-g17] replaced existing 70/40 G>=17 section")
    elif marker in html:
        html = html.replace(marker, snippet + "\n" + marker, 1)
        log("[append-t70-g17] inserted 70/40 G>=17 section")
    else:
        html = html.replace("</body>", snippet + "\n</body>", 1)
    old_q = "run a test using 17/8/6 taking NO trades unless there is an overhead zone."
    new_q = (
        old_q
        + " what if we build our dynamic target / stop on top of that the 70/40 for "
        "zones above &gt;= 17%"
    )
    if "70/40 for zones above" not in html and old_q in html:
        html = html.replace(old_q, new_q, 1)
    layman_bit = (
        "<p>He also asked what happens if we put the 70/40 dynamic target and stop on top of "
        "the G≥17% overhead floor: drop clear-sky, drop G&lt;17%, keep 70/40 sizing on the rest. "
        "That is an extra labeled slice of the existing 70/40 Closed, not a new 125-cell. "
        "17% is the skip/floor; 70/40 is the sizer, not a fixed 17/8/6 exit.</p>"
    )
    if "put the 70/40 dynamic target" not in html:
        needle = "DailyRun stays 22/20/8.</p>"
        html = html.replace(needle, needle + "\n" + layman_bit, 1)
    html_path.write_text(html, encoding="utf-8")

    base = OUT_DIR / "BASELINE.md"
    text = base.read_text(encoding="utf-8")
    if "70/40 dynamic target/stop on trades with overhead G>=17%" not in text:
        text = text.replace(
            "Post-hoc filter = selection bias. Not DailyRun.\n\nThis whole grid",
            "Post-hoc filter = selection bias. Not DailyRun.\n\n"
            "Paul also asked to put 70/40 dynamic target/stop on trades with overhead G>=17%: "
            "drop clear-sky, drop G<17%, keep the 70/40 sizer (not fixed 17/8/6). Extra labeled "
            "slice of the existing 70/40 Closed. Not part of the original 125. Slot cash is the "
            "70/40 engine slot. Research only. Post-hoc filter = selection bias. Not DailyRun.\n\n"
            "This whole grid",
            1,
        )
    freeze = (
        f"- Extra slice, 70/40 overhead G>=17% only (not in the 125): "
        f"FULL N {of_['n']}, WR {of_['wr']:.1f}%, avg {of_['avg']:.2f}%, PF {of_['pf']:.2f}, "
        f"Ann ROR {of_['ann_ror']:.2f}%, days {of_['avg_days']:.1f}; "
        f"IS N {oi['n']} Ann ROR {oi['ann_ror']:.2f}%; "
        f"OOS N {oo['n']} Ann ROR {oo['ann_ror']:.2f}% (report-only). "
        f"Slot ${t70g17['cash']:,.2f}. Verdict {t70g17.get('verdict_word')}. "
        "Filter of 70/40 Closed (drop clear-sky and G<17%; keep 70/40 sizer). Not DailyRun.\n"
    )
    if "70/40 overhead G>=17% only (not in the 125)" not in text:
        text = text.replace(
            "- Center 15/10/4 reused",
            freeze + "- Center 15/10/4 reused",
            1,
        )
    if REQUEST_QUOTE.split("what if we build")[-1][:20] not in text:
        if old_q in text and "70/40 for zones above" not in text:
            text = text.replace(
                old_q,
                old_q + " what if we build our dynamic target / stop on top of that the 70/40 for "
                "zones above >= 17%",
                1,
            )
    base.write_text(text, encoding="utf-8")
    log(f"[append-t70-g17] html={html_path} verdict={t70g17['verdict_word']}")


if __name__ == "__main__":
    if "--append-extras" in sys.argv:
        append_extras()
    elif "--append-t70-g17" in sys.argv:
        append_t70_g17()
    else:
        main()
