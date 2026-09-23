#!/usr/bin/env python3
"""
DailyRun system run/skip status for the investment report.

Written by DailyRun.bat; read by generate_investment_report.py so Paul can see
RUN / SKIPPED / NOT WIRED / STALE / MISSING at a glance.

Keep DAILYRUN_REGISTRY in sync with DailyRun.bat.

This is the single add-place for a new live sleeve:
  1) add the run_*.bat step in DailyRun.bat
  2) add the prefix here (wired=True, REPORT_ORDER)
Convergence (generate_system_convergence_report) and daily trendline universe
read this registry — do not keep a second frozen system tuple in those tools.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STATUS_NAME = "DailyRun_systems_status.json"

# Mirror DailyRun.bat wiring. Update when adding/removing system steps.
DAILYRUN_REGISTRY: dict[str, dict[str, Any]] = {
    "BRT": {"wired": True, "skip_env": None, "bat": "run_brt.bat"},
    "RL": {"wired": True, "skip_env": None, "bat": "run_rl.bat"},
    "YH": {"wired": True, "skip_env": None, "bat": "run_yh.bat"},
    "MTS": {"wired": True, "skip_env": None, "bat": "run_mts.bat"},
    "WPBR": {"wired": True, "skip_env": None, "bat": "run_wpbr.bat"},
    "RS": {"wired": True, "skip_env": None, "bat": "run_rs.bat"},
    "SB": {"wired": True, "skip_env": "SKIP_SB", "bat": "run_sb.bat"},
    "VZ": {"wired": True, "skip_env": "SKIP_VZ", "bat": "run_vz.bat"},
    "RSI": {"wired": True, "skip_env": "SKIP_RSI", "bat": "run_rsi.bat"},
    "IND": {
        "wired": False,
        "skip_env": None,
        "bat": None,
        "note": "deprecated - DailyRun step [5] permanently skipped",
    },
    "WRL": {
        "wired": True,
        "skip_env": "SKIP_WRL",
        "bat": "run_wrl.bat",
        "note": "DailyRun wire / official 6-sys mix — not gold",
    },
    "MVCP": {
        "wired": False,
        "skip_env": None,
        "bat": "run_mvcp.bat",
        "note": "retired 2026-08-21 from DailyRun and active reporting",
    },
}

# Report systems that appear on the investment report (order matches report chips).
REPORT_ORDER = ("BRT", "IND", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL")


def live_wired_systems() -> tuple[str, ...]:
    """DailyRun-wired sleeves in report order (skips deprecated / not-wired, e.g. IND).

    Live reports (historical performance, and others that want the same set)
    should call this instead of a stale hardcoded tuple.

    To add a system to this list: wire it in DailyRun.bat and this
    DAILYRUN_REGISTRY (plus REPORT_ORDER for display order). Research-only
    stamps stay out until they are DailyRun-wired.
    """
    ordered = [s for s in REPORT_ORDER if DAILYRUN_REGISTRY.get(s, {}).get("wired")]
    extras = [
        s
        for s, meta in DAILYRUN_REGISTRY.items()
        if meta.get("wired") and s not in ordered
    ]
    return tuple(ordered + extras)

# Never treat these as live DailyRun / convergence / trendline list sleeves.
LIVE_EXCLUDE = frozenset({"RSIN", "QULL", "KELL", "CS", "MVCP", "DB", "PBR"})

_LATEST_RUN_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]+)_LatestRun_(?P<kind>Watchlist|Scanner|Open)\.csv$",
    re.I,
)

_TS_RE = re.compile(r"^\d{12}$")


def wired_system_ids() -> list[str]:
    """Prefixes with wired=True in DAILYRUN_REGISTRY (current DailyRun sleeves)."""
    return [k for k, v in DAILYRUN_REGISTRY.items() if v.get("wired")]


def live_trendline_systems(_drive: Path | None = None) -> list[str]:
    """Opens / helds / watch / scan sleeves for daily trendline charts + score.

    Wired DailyRun systems only. Deprecated IND and retired Minervini Volatility
    Contraction Pattern (MVCP) stay out. Weekly Range / Swing (WRL) is DailyRun
    wired on the 29-name house universe (not gold).
    """
    return list(wired_system_ids())


def discover_latest_run_systems(
    drive: Path,
    stems: tuple[str, ...] = ("Watchlist", "Scanner", "Open"),
) -> list[str]:
    """Prefixes that already publish LatestRun watch/scan/open files."""
    found: set[str] = set()
    wanted = {s.upper() for s in stems}
    for path in drive.glob("*_LatestRun_*.csv"):
        m = _LATEST_RUN_RE.match(path.name)
        if not m:
            continue
        kind = m.group("kind").title()
        if kind not in wanted and m.group("kind").upper() not in wanted:
            continue
        prefix = m.group("prefix").upper()
        if prefix in LIVE_EXCLUDE:
            continue
        found.add(prefix)
    return sorted(found)


def live_convergence_systems(drive: Path | None = None) -> list[str]:
    """All systems the live watchlist/scanner/open convergence report should use.

    Order: investment REPORT_ORDER, then other wired registry ids, then any
    extra LatestRun prefixes on disk. Adding a new sleeve to DAILYRUN_REGISTRY
    (and DailyRun.bat) is enough — no second frozen tuple in the report.
    Disk discovery covers a forgotten REPORT_ORDER edit.
    """
    drive = drive or DRIVE
    seen: list[str] = []
    extras = discover_latest_run_systems(drive) if drive.is_dir() else []
    for sys in (*REPORT_ORDER, *wired_system_ids(), *extras):
        key = str(sys or "").strip().upper()
        if not key or key in LIVE_EXCLUDE:
            continue
        if key == "PBR" and ("WPBR" in seen or "WPBR" in REPORT_ORDER):
            continue
        if key not in seen:
            seen.append(key)
    return seen


def status_path(drive: Path = DRIVE) -> Path:
    return drive / STATUS_NAME


def _read_ts_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        ts = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return None
    return ts if _TS_RE.fullmatch(ts) else None


def _stamp_has_closed(prefix: str, drive: Path, ts: str) -> bool:
    return (drive / f"{prefix}_Closed_{ts}.csv").is_file()


def _newest_closed_stamp(prefix: str, drive: Path) -> Optional[str]:
    stamps: list[str] = []
    for path in drive.glob(f"{prefix}_Closed_*.csv"):
        m = re.match(rf"^{re.escape(prefix)}_Closed_(\d{{12}})\.csv$", path.name, re.I)
        if m:
            stamps.append(m.group(1))
    return max(stamps) if stamps else None


def read_system_stamp(system: str, drive: Path = DRIVE) -> Optional[str]:
    """Best public/production stamp for status freshness (house pin for VZ/RSI)."""
    sys = system.upper()
    if sys == "VZ":
        house = _read_ts_file(drive / "VZ_house_last_run_ts.txt")
        if house and _stamp_has_closed("VZ", drive, house):
            return house
        last = _read_ts_file(drive / "VZ_last_run_ts.txt")
        if last and _stamp_has_closed("VZ", drive, last):
            # Prefer house-sized only when possible; last_run may be ALL research.
            return last
        return house or last or _newest_closed_stamp("VZ", drive)
    if sys == "RSI":
        house = _read_ts_file(drive / "RSI_house_last_run_ts.txt")
        if house and _stamp_has_closed("RSI", drive, house):
            return house
        last = _read_ts_file(drive / "RSI_last_run_ts.txt")
        if last and _stamp_has_closed("RSI", drive, last):
            return last
        return house or last or _newest_closed_stamp("RSI", drive)
    if sys == "RL":
        for candidate in (
            drive / "RL_last_run_ts.txt",
            drive / "last_run_ts.txt",
        ):
            ts = _read_ts_file(candidate)
            if ts and _stamp_has_closed("RL", drive, ts):
                return ts
        return (
            _read_ts_file(drive / "RL_last_run_ts.txt")
            or _read_ts_file(drive / "last_run_ts.txt")
            or _newest_closed_stamp("RL", drive)
        )
    if sys == "WPBR":
        ts = _read_ts_file(drive / "WPBR_last_run_ts.txt") or _read_ts_file(
            drive / "PBR_last_run_ts.txt"
        )
        if ts and (
            _stamp_has_closed("WPBR", drive, ts) or _stamp_has_closed("PBR", drive, ts)
        ):
            return ts
        return ts or _newest_closed_stamp("WPBR", drive) or _newest_closed_stamp(
            "PBR", drive
        )
    ts = _read_ts_file(drive / f"{sys}_last_run_ts.txt")
    if ts and _stamp_has_closed(sys, drive, ts):
        return ts
    return ts or _newest_closed_stamp(sys, drive)


def load_status(drive: Path = DRIVE) -> dict[str, Any]:
    path = status_path(drive)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_status(data: dict[str, Any], drive: Path = DRIVE) -> Path:
    drive.mkdir(parents=True, exist_ok=True)
    path = status_path(drive)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def begin_session(drive: Path = DRIVE, dailyrun_stamp: Optional[str] = None) -> Path:
    stamp = dailyrun_stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "dailyrun_stamp": stamp,
        "begun_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "systems": {},
    }
    return save_status(data, drive)


def set_system(
    system: str,
    status: str,
    *,
    reason: str = "",
    ts: Optional[str] = None,
    drive: Path = DRIVE,
) -> Path:
    sys = system.upper().strip()
    data = load_status(drive)
    if not data:
        data = {
            "dailyrun_stamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "begun_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "systems": {},
        }
    systems = data.setdefault("systems", {})
    entry: dict[str, Any] = {
        "status": status.upper().strip(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if reason:
        entry["reason"] = reason
    stamp = ts or read_system_stamp(sys, drive)
    if stamp:
        entry["ts"] = stamp
    systems[sys] = entry
    return save_status(data, drive)


def finalize_from_drive(drive: Path = DRIVE) -> Path:
    """
    Mark wired systems not already SKIPPED as RUN (with stamp), and stamp NOT WIRED rows.
    Call after backtests (+ optional skips) before or after copy_latest.
    """
    data = load_status(drive)
    if not data:
        data = {
            "dailyrun_stamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "begun_at": datetime.now().isoformat(timespec="seconds"),
            "systems": {},
        }
    systems = data.setdefault("systems", {})
    for sys, meta in DAILYRUN_REGISTRY.items():
        existing = systems.get(sys) or {}
        if str(existing.get("status", "")).upper() == "SKIPPED":
            continue
        if not meta.get("wired", False):
            systems[sys] = {
                "status": "NOT WIRED",
                "reason": meta.get("note") or "not in DailyRun",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            continue
        stamp = read_system_stamp(sys, drive)
        systems[sys] = {
            "status": "RUN",
            "ts": stamp,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    data["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return save_status(data, drive)


def _ymd(ts: Optional[str]) -> Optional[str]:
    if ts and len(ts) >= 6 and ts[:6].isdigit():
        return ts[:6]
    return None


def compute_report_statuses(
    drive: Path = DRIVE,
    *,
    report_systems: tuple[str, ...] = REPORT_ORDER,
) -> list[dict[str, Any]]:
    """
    Resolve display status for each report system.

    Priority: NOT WIRED → SKIPPED (persisted or live env) → MISSING → STALE → RUN.
    STALE = wired stamp calendar day behind the newest wired peer that is not SKIPPED.
    """
    persisted = load_status(drive)
    pers_systems = persisted.get("systems") or {}
    rows: list[dict[str, Any]] = []

    stamps: dict[str, Optional[str]] = {}
    for sys in report_systems:
        stamps[sys] = read_system_stamp(sys, drive)

    # Cohort: wired systems that are not recorded as SKIPPED and have a stamp.
    cohort_ymds: list[str] = []
    for sys in report_systems:
        meta = DAILYRUN_REGISTRY.get(sys, {"wired": False})
        if not meta.get("wired"):
            continue
        pers = pers_systems.get(sys) or {}
        if str(pers.get("status", "")).upper() == "SKIPPED":
            continue
        skip_env = meta.get("skip_env")
        if skip_env and os.environ.get(skip_env, "").strip() in ("1", "true", "yes"):
            # Live skip env without a RUN record — exclude from cohort
            if str(pers.get("status", "")).upper() != "RUN":
                continue
        ymd = _ymd(stamps.get(sys))
        if ymd:
            cohort_ymds.append(ymd)
    cohort_max = max(cohort_ymds) if cohort_ymds else None

    for sys in report_systems:
        meta = DAILYRUN_REGISTRY.get(
            sys, {"wired": False, "note": "unknown to DailyRun registry"}
        )
        pers = pers_systems.get(sys) or {}
        ts = stamps.get(sys)
        detail = ""
        status = "RUN"

        if not meta.get("wired", False):
            status = "NOT WIRED"
            detail = str(pers.get("reason") or meta.get("note") or "not in DailyRun")
        else:
            skip_env = meta.get("skip_env")
            env_skip = bool(
                skip_env
                and os.environ.get(str(skip_env), "").strip().lower()
                in ("1", "true", "yes", "y")
            )
            if str(pers.get("status", "")).upper() == "SKIPPED":
                status = "SKIPPED"
                detail = str(pers.get("reason") or (f"{skip_env}=1" if skip_env else "skipped"))
            elif env_skip and str(pers.get("status", "")).upper() != "RUN":
                status = "SKIPPED"
                detail = f"{skip_env}=1 (current env)"
            elif not ts:
                status = "MISSING"
                detail = "no last_run / Closed stamp"
            elif cohort_max and _ymd(ts) and _ymd(ts) < cohort_max:
                status = "STALE"
                detail = f"stamp {ts} behind cohort day {cohort_max}"
            else:
                status = "RUN"
                detail = f"stamp {ts}" if ts else "ok"

        rows.append(
            {
                "system": sys,
                "status": status,
                "ts": ts or "",
                "detail": detail,
                "wired": bool(meta.get("wired")),
                "skip_env": meta.get("skip_env"),
                "bat": meta.get("bat"),
            }
        )
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description="Record / inspect DailyRun system status")
    p.add_argument("--drive", type=Path, default=DRIVE)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("begin", help="Start a DailyRun status session")
    b.add_argument("--stamp", default="", help="DailyRun log stamp (yyyyMMdd_HHmmss)")

    s = sub.add_parser("set", help="Record one system status")
    s.add_argument("system")
    s.add_argument("status", choices=["RUN", "SKIPPED", "NOT_WIRED", "NOT WIRED", "MISSING", "STALE"])
    s.add_argument("--reason", default="")
    s.add_argument("--ts", default="")

    sub.add_parser("finalize", help="Fill RUN/NOT WIRED from drive stamps")

    sh = sub.add_parser("show", help="Print computed report statuses")
    sh.add_argument("--json", action="store_true")

    args = p.parse_args()
    drive = args.drive

    if args.cmd == "begin":
        path = begin_session(drive, args.stamp or None)
        print(f"Wrote {path}")
        return 0
    if args.cmd == "set":
        status = args.status.replace("_", " ")
        path = set_system(
            args.system,
            status,
            reason=args.reason,
            ts=args.ts or None,
            drive=drive,
        )
        print(f"Wrote {path} ({args.system}={status})")
        return 0
    if args.cmd == "finalize":
        path = finalize_from_drive(drive)
        print(f"Wrote {path}")
        return 0
    if args.cmd == "show":
        rows = compute_report_statuses(drive)
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['system']:5} {r['status']:10} {r['ts'] or '-':14} {r['detail']}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
