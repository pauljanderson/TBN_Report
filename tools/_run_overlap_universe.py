#!/usr/bin/env python3
"""
Overlap-universe system runs + convergence re-analysis + LatestRun restore.

Forces OLD SB params for apples-to-apples with prior convergence reports:
  SB_TARGET=1.10, SB_MAX_RISK=0.08
(Do not rely on bat defaults — they may already be 1.097/0.078.)

Writes only *OverlapUniverse* reports; restores official LatestRun from restore_map.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVE = ROOT / "drive"
PE = DRIVE / "paul_experiments"
RUN_DIR = PE / "overlap_universe_run"
LOG_DIR = RUN_DIR / "logs"
MAP_PATH = RUN_DIR / "overlap_closed_map.json"
STATUS_PATH = RUN_DIR / "run_status.json"
RESTORE_MAP = RUN_DIR / "restore_map.json"
UNIV_TXT = PE / "OverlapUniverse_symbols.txt"

# Explicit OLD SB params (prior convergence / gold freeze parity)
SB_TARGET_OLD = "1.10"
SB_MAX_RISK_OLD = "0.08"

SYSTEM_ORDER = (
    "SB",
    "BRT",
    "YH",
    "RS",
    "WPBR",
    "RL",
    "MTS",
    "MVCP",
    "QULL",
    "KELL",
    "CS",
    "IND",
)

_STAMP_RE = re.compile(r"^([A-Za-z]+)_Closed_(\d{6}[A-Za-z0-9]{1,12})\.csv$", re.I)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_symbols() -> str:
    raw = UNIV_TXT.read_text(encoding="utf-8").strip()
    if not raw:
        raise SystemExit(f"Empty universe: {UNIV_TXT}")
    return raw


def newest_closed_before(system: str) -> set[str]:
    return {p.name for p in DRIVE.glob(f"{system}_Closed_*.csv")}


def detect_new_stamp(system: str, before: set[str]) -> dict:
    """Pick newest Closed stamp created/updated during the run."""
    candidates: list[tuple[bool, float, str, Path]] = []
    for p in DRIVE.glob(f"{system}_Closed_*.csv"):
        m = _STAMP_RE.match(p.name)
        if not m or m.group(1).upper() != system.upper():
            continue
        if "_RL_" in p.name.upper():
            continue
        stamp = m.group(2)
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        is_new = p.name not in before
        candidates.append((is_new, mt, stamp, p))

    if not candidates:
        return {"stamp": None, "path": None, "note": "no Closed found"}

    # Prefer newly appeared files, then newest mtime
    candidates.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    is_new, _mt, stamp, path = candidates[0]
    return {
        "stamp": stamp,
        "path": str(path),
        "size": path.stat().st_size,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "was_new_name": is_new,
    }


def resolve_py() -> str:
    env = os.environ.get("PY", "").strip()
    if env and Path(env).is_file():
        return env
    # resolve_python.bat sets PY; fall back to sys.executable
    return sys.executable


def run_cmd(
    system: str,
    argv: list[str],
    env: dict[str, str],
    log_path: Path,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n===== [{system}] START {datetime.now().isoformat(timespec='seconds')} =====")
    print(f"  cmd: {' '.join(argv[:8])} ...")
    print(f"  log: {log_path}")
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"CMD: {' '.join(argv)}\n")
        log.write(f"CWD: {ROOT}\n")
        for k in sorted(env):
            if k.endswith("_SYMBOLS") or k.startswith("SB_"):
                v = env[k]
                if len(v) > 120:
                    v = v[:120] + f"...({len(env[k])} chars)"
                log.write(f"ENV {k}={v}\n")
        log.write("\n--- stdout/stderr ---\n")
        log.flush()
        proc = subprocess.run(
            argv,
            cwd=str(ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            shell=False,
        )
        rc = int(proc.returncode)
        elapsed = time.time() - t0
        log.write(f"\n--- exit {rc} after {elapsed:.1f}s ---\n")
    print(f"===== [{system}] DONE rc={rc} in {time.time()-t0:.1f}s =====")
    return rc


def bat_env(base: dict[str, str], symbols: str, system: str) -> dict[str, str]:
    env = dict(base)
    env[f"{system}_SYMBOLS"] = symbols
    # Also set common aliases used by bats
    mapping = {
        "SB": "SB_SYMBOLS",
        "BRT": "BRT_SYMBOLS",
        "YH": "YH_SYMBOLS",
        "RS": "RS_SYMBOLS",
        "WPBR": "WPBR_SYMBOLS",
        "RL": "RL_SYMBOLS",
        "MTS": "MTS_SYMBOLS",
        "MVCP": "MVCP_SYMBOLS",
        "QULL": "QULL_SYMBOLS",
        "KELL": "KELL_SYMBOLS",
        "CS": "CS_SYMBOLS",
    }
    key = mapping.get(system)
    if key:
        env[key] = symbols
    if system == "SB":
        # Force OLD values — do not rely on bat defaults (now 1.097/0.078)
        env["SB_TARGET"] = SB_TARGET_OLD
        env["SB_MAX_RISK"] = SB_MAX_RISK_OLD
        env["SB_TIME_STOP"] = env.get("SB_TIME_STOP") or "5"
        env["SB_NO_FT"] = env.get("SB_NO_FT") or "3"
        print(f"  [SB] FORCED SB_TARGET={SB_TARGET_OLD} SB_MAX_RISK={SB_MAX_RISK_OLD}")
    return env


def cmd_for_system(system: str, py: str, symbols: str) -> tuple[list[str], str | None]:
    """
    Return (argv, skip_reason).
    IND has no -s in bat — invoke rocket_tbn directly with same knobs + -s.
    """
    if system == "SB":
        return [str(ROOT / "run_sb.bat")], None
    if system == "BRT":
        return [str(ROOT / "run_brt.bat")], None
    if system == "YH":
        return [str(ROOT / "run_yh.bat")], None
    if system == "RS":
        return [str(ROOT / "run_rs.bat")], None
    if system == "WPBR":
        return [str(ROOT / "run_wpbr.bat")], None
    if system == "RL":
        return [str(ROOT / "run_rl.bat")], None
    if system == "MTS":
        return [str(ROOT / "run_mts.bat")], None
    if system == "MVCP":
        return [str(ROOT / "run_mvcp.bat")], None
    if system == "QULL":
        return [str(ROOT / "run_qull.bat")], None
    if system == "KELL":
        return [str(ROOT / "run_kell.bat")], None
    if system == "CS":
        return [str(ROOT / "run_canslim.bat")], None
    if system == "IND":
        # Mirror run_ind.bat + -s overlap universe (bat has no symbol env)
        return [
            py,
            str(ROOT / "stock_analysis" / "rocket_tbn.py"),
            str(ROOT / "data" / "newdata" / "data"),
            "-o",
            "drive",
            "-w",
            "30",
            "--aggressive",
            "--use-duckdb",
            "--no-regression",
            "-v",
            "target_pct=1.24",
            "-v",
            "trailing_stop_increment=0",
            "-v",
            "strong_pre_pivot_pct=0.081",
            "-v",
            "strong_post_pivot_pct=0.109",
            "-v",
            "atr_progress=0",
            "-v",
            "atr_days=0",
            "-v",
            "compute_beta=true",
            "-v",
            "min_avg_volume_10d_at_entry=0",
            "-v",
            "min_atr_pct_at_trigger=8.1",
            "-v",
            "max_atr_pct_at_trigger=0",
            "-v",
            "use_indicators=true",
            "-v",
            "indicator_buy=only",
            "-v",
            "indicator_diff=7",
            "-v",
            "indicator_sides=long",
            "-v",
            "transaction_type=long",
            "-v",
            "atr_target=2.2",
            "-v",
            "atr_stop=1.4",
            "-v",
            "max_ind_entry_neutral_n=30",
            "-v",
            "min_ind_score=-2",
            "-v",
            "yh_zones=false",
            "-v",
            "aggressive_avg_positions=20",
            "-s",
            symbols,
        ], None
    return [], f"no runner for {system}"


def write_status(status: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")


def run_systems(symbols: str) -> dict:
    py = resolve_py()
    base_env = dict(os.environ)
    base_env["PY"] = py
    # Ensure cmd.exe finds bats; use cmd /c for .bat
    status: dict = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "universe_n": len(symbols.split(",")),
        "sb_forced": {"SB_TARGET": SB_TARGET_OLD, "SB_MAX_RISK": SB_MAX_RISK_OLD},
        "systems": {},
        "skips": [],
    }
    closed_map: dict[str, str] = {}

    for system in SYSTEM_ORDER:
        argv, skip = cmd_for_system(system, py, symbols)
        if skip:
            status["skips"].append({"system": system, "reason": skip})
            continue
        before = newest_closed_before(system)
        env = bat_env(base_env, symbols, system)
        log_path = LOG_DIR / f"{system}_overlap_run.log"

        # Windows .bat needs cmd /c
        if argv and argv[0].lower().endswith(".bat"):
            full_argv = ["cmd.exe", "/c", argv[0]]
        else:
            full_argv = argv

        rc = run_cmd(system, full_argv, env, log_path)
        info = detect_new_stamp(system, before)
        info["rc"] = rc
        info["log"] = str(log_path)
        if system == "SB":
            info["forced_params"] = {
                "SB_TARGET": SB_TARGET_OLD,
                "SB_MAX_RISK": SB_MAX_RISK_OLD,
            }
        status["systems"][system] = info
        if info.get("path"):
            closed_map[system] = info["path"]
        write_status(status)
        MAP_PATH.write_text(json.dumps(closed_map, indent=2), encoding="utf-8")
        if rc != 0:
            print(f"WARNING: {system} exited {rc} — continuing")

    status["finished_runs"] = datetime.now().isoformat(timespec="seconds")
    status["closed_map"] = closed_map
    write_status(status)
    MAP_PATH.write_text(json.dumps(closed_map, indent=2), encoding="utf-8")
    return status


def run_analysis(closed_map: dict[str, str]) -> dict:
    """Run both convergence tools against overlap stamps only."""
    if not closed_map:
        raise SystemExit("empty closed_map — cannot analyze")
    # Ensure map file is JSON SYS->path
    MAP_PATH.write_text(json.dumps(closed_map, indent=2), encoding="utf-8")

    results = {}
    cmds = [
        (
            "sb",
            [
                sys.executable,
                str(ROOT / "tools" / "sb_system_convergence.py"),
                "--out-prefix",
                "OverlapUniverse",
                "--closed-map",
                str(MAP_PATH),
            ],
        ),
        (
            "all",
            [
                sys.executable,
                str(ROOT / "tools" / "all_systems_convergence.py"),
                "--out-prefix",
                "OverlapUniverse",
                "--closed-map",
                str(MAP_PATH),
            ],
        ),
    ]
    for name, argv in cmds:
        log = LOG_DIR / f"analysis_{name}.log"
        print(f"\n===== analysis {name} =====")
        with log.open("w", encoding="utf-8", errors="replace") as f:
            f.write("CMD: " + " ".join(argv) + "\n\n")
            f.flush()
            proc = subprocess.run(
                argv, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT
            )
        results[name] = {"rc": proc.returncode, "log": str(log)}
        print(f"  rc={proc.returncode} log={log}")
        if proc.returncode != 0:
            print(log.read_text(encoding="utf-8", errors="replace")[-3000:])
    return results


def restore_latestrun() -> dict:
    """Restore LatestRun Closed/Summary from restore_map gold stamps."""
    mapping = json.loads(RESTORE_MAP.read_text(encoding="utf-8"))
    report: dict = {"restored": [], "missing": [], "ts": datetime.now().isoformat(timespec="seconds")}
    for sys, info in mapping.items():
        for kind, key in (("Closed", "closed"), ("Summary", "summary")):
            src_s = info.get(key)
            if not src_s:
                report["missing"].append(f"{sys}_{kind}")
                continue
            src = Path(src_s)
            if not src.is_file():
                report["missing"].append(f"{sys}_{kind}:{src_s}")
                continue
            dst = DRIVE / f"{sys}_LatestRun_{kind}.csv"
            shutil.copy2(src, dst)
            report["restored"].append(
                {
                    "dst": dst.name,
                    "from": src.name,
                    "size": dst.stat().st_size,
                }
            )
    # Also restore Open/Scanner/Watchlist from stamp if present
    for sys, info in mapping.items():
        stamp = info.get("stamp")
        if not stamp:
            continue
        for kind in ("Open", "Scanner", "Watchlist"):
            src = DRIVE / f"{sys}_{kind}_{stamp}.csv"
            dst = DRIVE / f"{sys}_LatestRun_{kind}.csv"
            if src.is_file() and dst.is_file():
                shutil.copy2(src, dst)
                report["restored"].append({"dst": dst.name, "from": src.name, "size": dst.stat().st_size})
    out = RUN_DIR / "restore_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Restored {len(report['restored'])} LatestRun files -> {out}")
    return report


def verify_latestrun_reports_unchanged() -> dict:
    """Confirm *LatestRun* convergence reports match snapshot hashes."""
    snap = PE / "overlap_universe_run" / "baseline_latestrun_snapshot" / "convergence_reports"
    out = {}
    for name in (
        "SB_System_Convergence_LatestRun.html",
        "SB_System_Convergence_LatestRun.csv",
        "SB_System_Convergence_LatestRun.md",
        "SB_System_Convergence_SecondSignal_Agg.csv",
        "All_Systems_Convergence_LatestRun.html",
        "All_Systems_Convergence_LatestRun.csv",
        "All_Systems_Convergence_LatestRun.md",
        "All_Systems_Convergence_SecondSignal_Agg.csv",
    ):
        cur = PE / name
        base = snap / name
        if not cur.is_file() or not base.is_file():
            out[name] = {"ok": False, "reason": "missing"}
            continue
        out[name] = {
            "ok": sha256(cur) == sha256(base),
            "cur_size": cur.stat().st_size,
            "base_size": base.stat().st_size,
        }
    return out


def extract_verdict_summary() -> str:
    md = PE / "All_Systems_Convergence_OverlapUniverse.md"
    if not md.is_file():
        return "(analysis md missing)"
    text = md.read_text(encoding="utf-8", errors="replace")
    # Grab Alone vs overlap section header + summary line + table rows briefly
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("## Alone vs overlap"):
            start = i
            break
    if start is None:
        return "(no verdict section)"
    chunk = []
    for ln in lines[start : start + 30]:
        if ln.startswith("## ") and not ln.startswith("## Alone"):
            break
        chunk.append(ln)
    return "\n".join(chunk)


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    symbols = load_symbols()
    print(f"Universe: {len(symbols.split(','))} symbols from {UNIV_TXT}")
    print(f"SB forced: TARGET={SB_TARGET_OLD} MAX_RISK={SB_MAX_RISK_OLD}")

    phase = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()

    status: dict = {}
    if phase in ("all", "run"):
        status = run_systems(symbols)
    else:
        if STATUS_PATH.is_file():
            status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        if MAP_PATH.is_file():
            status["closed_map"] = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    closed_map = status.get("closed_map") or {}
    if phase in ("all", "analyze"):
        if not closed_map and MAP_PATH.is_file():
            closed_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        analysis = run_analysis(closed_map)
        status["analysis"] = analysis
        write_status(status)

    if phase in ("all", "restore"):
        restore = restore_latestrun()
        status["restore"] = restore
        status["latest_reports_unchanged"] = verify_latestrun_reports_unchanged()
        write_status(status)
        print("\n=== LatestRun convergence reports unchanged? ===")
        for k, v in status["latest_reports_unchanged"].items():
            print(f"  {k}: {'OK' if v.get('ok') else 'CHANGED/MISSING'} {v}")

    if phase in ("all", "analyze"):
        print("\n=== Alone vs overlap (OverlapUniverse) ===")
        print(extract_verdict_summary())

    print(f"\nStatus: {STATUS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
