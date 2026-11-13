#!/usr/bin/env python3
"""Run the production engines through the honest harness.

Each system runs with its frozen production profile (the run_*.bat itself,
nothing re-typed here), but:
  - universe = ALL symbols in the data dir (no curated list), filtered later
    by the point-in-time rule in pit_universe.py,
  - data dir = data/pit_daily (survivor-free) or the canonical warehouse,
  - output  = drive/honest_bt/<stamp>/<variant>/<SYS>/ (never drive/ root, so
    copy-latest / reconcile / Pages never see these runs),
  - no DuckDB, no yfinance enrichment.

Usage (Windows or WSL):
  python tools/honest_bt/run_honest.py --variant pit
  python tools/honest_bt/run_honest.py --variant canon --systems BRT,RSI
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SYSTEMS = {  # code -> launcher (the same bat DailyRun calls)
    "BRT": "run_brt.bat", "YH": "run_yh.bat", "MTS": "run_mts.bat", "WPBR": "run_wpbr.bat",
    "RS": "run_rs.bat", "SB": "run_stockbee_burst.bat", "VZ": "run_vz.bat", "RSI": "run_rsi.bat",
    "WRL": "run_wrl.bat", "RL": "run_rl.bat",
}
DATA = {"pit": r"data\pit_daily", "canon": r"data\newdata\data"}


def _cmd_exe() -> str:
    return "cmd" if os.name == "nt" else "cmd.exe"


def _win(p: Path) -> str:
    """Repo-relative Windows path (the bats cd to the repo root)."""
    return str(p.relative_to(REPO)).replace("/", "\\")


def _repo_win() -> str:
    r = str(REPO)
    if r.startswith("/mnt/") and len(r) > 6:  # WSL path -> C:\...
        r = r[5].upper() + ":" + r[6:]
    return r.replace("/", "\\")


def _write_wrapper(path: Path, sys_code: str, variant: str, out: Path, argstub: bool, symbols: str = "",
                   env: tuple[str, ...] = ()) -> None:
    """A real .bat: passing quoted `set` commands through `cmd /c` from WSL mangles them
    (2026-11-12: TBN_OUT_DIR silently fell back to drive and clobbered RSI_LatestRun_*)."""
    lines = ["@echo off", f"cd /d {_repo_win()}",
             f'set "TBN_DATA_DIR={DATA[variant]}"', f'set "TBN_OUT_DIR={_win(out)}"',
             'set "TBN_NO_DUCKDB=1"', f'set "{sys_code}_SYMBOLS={symbols}"',
             # No Yahoo: delisted names have no fundamentals, and lookups would write the
             # production drive/fundamentals_cache.duckdb. Market-cap filters are off in every profile.
             'set "NO_YFINANCE=1"']
    if sys_code == "WRL":
        lines.append('set "WRL_TARGET_MODE=swing"')  # DailyRun sets this before the wave
    for kv in env:  # research toggles, e.g. WPBR_PLACEBO=random_week:1
        lines.append(f'set "{kv}"')
    if argstub:
        lines.append(f'set "PYTHONPATH={_repo_win()}\\tools\\honest_bt\\argstub"')
    lines.append(f"call {SYSTEMS[sys_code]} {'' if symbols else 'ALL '}--no-yfinance")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def _drive_root_snapshot() -> dict[str, float]:
    """Names of everything in drive/ root, plus mtimes of the files production reads
    (LatestRun aliases and run-stamp pointers). drive/ holds ~100k files, so a full
    stat over the WSL mount is too slow; names catch new files, mtimes catch overwrites."""
    snap: dict[str, float] = {}
    for e in os.scandir(REPO / "drive"):
        n = e.name
        snap[n] = e.stat().st_mtime if ("_LatestRun_" in n or n.endswith("last_run_ts.txt")) else 0.0
    return snap


def preflight_args(sys_code: str, variant: str, out: Path, symbols: str = "", env: tuple[str, ...] = ()) -> str:
    """Dry-run the launcher with argstub; refuse unless the engine would get our -o and data dir."""
    wrap = out / "_preflight.bat"
    _write_wrapper(wrap, sys_code, variant, out, argstub=True, symbols=symbols, env=env)
    proc = subprocess.run([_cmd_exe(), "/c", _win_abs(wrap)], cwd=str(REPO), capture_output=True)
    text = proc.stdout.decode("utf-8", "replace")
    args = [ln for ln in text.splitlines() if ln.startswith("ARGS:")]
    want_o, want_d = f"-o {_win(out)}", f"ARGS: {DATA[variant]} "
    if len(args) != 1 or want_o not in args[0] or not args[0].startswith(want_d) or "--use-duckdb" in args[0]:
        raise SystemExit(f"[honest] PREFLIGHT FAILED for {sys_code}: engine args would be {args!r} "
                         f"(need '{want_d.strip()}' and '{want_o}', no --use-duckdb). Refusing to run.")
    return args[0]


def _win_abs(p: Path) -> str:
    return _repo_win() + "\\" + _win(p)


def run_one(sys_code: str, variant: str, out_root: Path, log, symbols: str = "", tag: str = "",
            env: tuple[str, ...] = ()) -> Path | None:
    out = out_root / (tag or variant) / sys_code
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    args = preflight_args(sys_code, variant, out, symbols, env)
    log.write(f"[honest] {variant}/{sys_code} preflight ok: {args[:200]}\n".encode())
    wrap = out / "_run.bat"
    _write_wrapper(wrap, sys_code, variant, out, argstub=False, symbols=symbols, env=env)
    before = _drive_root_snapshot()
    t0 = time.time()
    proc = subprocess.run([_cmd_exe(), "/c", _win_abs(wrap)], cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    after = _drive_root_snapshot()
    touched = sorted(n for n, m in after.items() if before.get(n) != m)
    if touched:
        raise SystemExit(f"[honest] ABORT: {sys_code} wrote to drive/ root (production): {touched[:20]} "
                         f"... restore them from the prior stamp before DailyRun.")
    closed = sorted(c for c in out.glob("*_Closed_*.csv") if c.stem.split("_Closed_")[1].isdigit())
    msg = f"[honest] {variant}/{sys_code} exit={proc.returncode} {time.time() - t0:.0f}s closed={[c.name for c in closed]}"
    print(msg, flush=True)
    log.write((msg + "\n").encode())
    log.flush()
    if proc.returncode != 0 or not closed:
        return None
    return closed[-1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", choices=sorted(DATA) + ["custom"], required=True)
    ap.add_argument("--data-dir", default="", help="variant custom: repo-relative data dir (e.g. data/trunc/cut_20220630)")
    ap.add_argument("--systems", default=",".join(SYSTEMS))
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--symbols", default="", help="comma list instead of ALL (refactor checks)")
    ap.add_argument("--tag", default="", help="output subfolder name (default: the variant)")
    ap.add_argument("--env", action="append", default=[], help="KEY=VAL set in the run wrapper (repeatable)")
    a = ap.parse_args(argv)
    if a.variant == "custom":
        if not a.data_dir or not (REPO / a.data_dir).is_dir():
            print(f"ERROR: --variant custom needs an existing --data-dir (got {a.data_dir!r})", file=sys.stderr)
            return 2
        DATA["custom"] = a.data_dir.replace("/", "\\").rstrip("\\")
    if a.variant == "pit" and not (REPO / "data" / "pit_daily" / "_manifest.csv").exists():
        print("ERROR: data/pit_daily missing - run tools/honest_bt/fetch_pit_daily.py first", file=sys.stderr)
        return 2
    out_root = REPO / "drive" / "honest_bt" / a.stamp
    out_root.mkdir(parents=True, exist_ok=True)
    failed = []
    with open(out_root / f"run_{(a.tag or a.variant).replace('/', '_')}.log", "ab") as log:
        for s in [x.strip().upper() for x in a.systems.split(",") if x.strip()]:
            if run_one(s, a.variant, out_root, log, a.symbols, a.tag, tuple(a.env)) is None:
                failed.append(s)
    if failed:
        print(f"[honest] FAILED: {failed} (see {out_root / f'run_{a.variant}.log'})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
