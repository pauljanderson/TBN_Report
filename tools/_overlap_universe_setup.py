#!/usr/bin/env python3
"""Build OverlapUniverse symbol list + snapshot LatestRun for restore."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DRIVE = ROOT / "drive"
PE = DRIVE / "paul_experiments"
SNAP = PE / "overlap_universe_run" / "baseline_latestrun_snapshot"
RUN_DIR = PE / "overlap_universe_run"

# Official restore targets (DailyRun / reconcile gold freezes).
# SB: user-requested freeze 260803121109.
# Peers: stamp twins that matched LatestRun at convergence generation time.
RESTORE_CLOSED_STAMPS = {
    "SB": "260803121109",
    "BRT": "260803143542",
    "YH": "260803143615",
    "RS": "260803144028",
    "WPBR": "260803143854",
    "RL": "260803143536",
    "MTS": "260803143630",
    "MVCP": "260801215052",
    "QULL": "260803qep1",
    "KELL": "260802kell01",
    "CS": "260803fund1",
    "IND": "260719094713",
}

SYSTEMS = list(RESTORE_CLOSED_STAMPS.keys())


def extract_union() -> list[str]:
    sb = pd.read_csv(PE / "SB_System_Convergence_LatestRun.csv")
    allc = pd.read_csv(PE / "All_Systems_Convergence_LatestRun.csv")
    syms = set()
    for df in (sb, allc):
        if "symbol" in df.columns:
            syms |= set(df["symbol"].astype(str).str.upper().str.strip())
    syms.discard("")
    syms.discard("NAN")
    return sorted(syms)


def snapshot_latestrun() -> dict:
    SNAP.mkdir(parents=True, exist_ok=True)
    meta: dict = {"snap_ts": datetime.now().isoformat(timespec="seconds"), "files": []}
    for sys in SYSTEMS:
        for kind in ("Closed", "Summary", "Open", "Scanner", "Watchlist"):
            src = DRIVE / f"{sys}_LatestRun_{kind}.csv"
            if not src.is_file():
                continue
            dst = SNAP / src.name
            shutil.copy2(src, dst)
            meta["files"].append(
                {
                    "name": src.name,
                    "size": src.stat().st_size,
                    "mtime": datetime.fromtimestamp(src.stat().st_mtime).isoformat(
                        timespec="seconds"
                    ),
                }
            )
    # Also copy convergence reports for checksum proof later
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
        src = PE / name
        if src.is_file():
            dst = SNAP / "convergence_reports" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            meta["files"].append({"name": f"convergence_reports/{name}", "size": src.stat().st_size})
    (SNAP / "snapshot_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def write_restore_map() -> Path:
    """Map system -> stamped Closed path to restore LatestRun from after experiment."""
    mapping: dict[str, dict] = {}
    for sys, stamp in RESTORE_CLOSED_STAMPS.items():
        closed = DRIVE / f"{sys}_Closed_{stamp}.csv"
        summary = DRIVE / f"{sys}_Summary_{stamp}.csv"
        mapping[sys] = {
            "stamp": stamp,
            "closed": str(closed) if closed.is_file() else None,
            "summary": str(summary) if summary.is_file() else None,
            "closed_exists": closed.is_file(),
            "summary_exists": summary.is_file(),
            "closed_size": closed.stat().st_size if closed.is_file() else None,
        }
    out = RUN_DIR / "restore_map.json"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    return out


def write_universe(syms: list[str]) -> tuple[Path, Path]:
    PE.mkdir(parents=True, exist_ok=True)
    csv_path = PE / "OverlapUniverse_symbols.csv"
    txt_path = PE / "OverlapUniverse_symbols.txt"
    pd.DataFrame({"symbol": syms}).to_csv(csv_path, index=False)
    txt_path.write_text(",".join(syms), encoding="utf-8")
    (RUN_DIR / "OverlapUniverse_symbols.csv").parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(csv_path, RUN_DIR / "OverlapUniverse_symbols.csv")
    shutil.copy2(txt_path, RUN_DIR / "OverlapUniverse_symbols.txt")
    return csv_path, txt_path


def main() -> int:
    syms = extract_union()
    csv_path, txt_path = write_universe(syms)
    meta = snapshot_latestrun()
    restore = write_restore_map()
    print(f"Overlap universe: {len(syms)} symbols")
    print(f"  {csv_path}")
    print(f"  {txt_path}")
    print(f"Snapshot: {SNAP} ({len(meta['files'])} files)")
    print(f"Restore map: {restore}")
    missing = [
        s
        for s, info in json.loads(restore.read_text(encoding="utf-8")).items()
        if not info["closed_exists"]
    ]
    if missing:
        print(f"WARNING missing restore Closed stamps: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
