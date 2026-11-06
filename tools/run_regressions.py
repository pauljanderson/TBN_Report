#!/usr/bin/env python3
"""TBN regression suite — run before commit / as DailyRun preflight.

Covers:
  - getTarget empty book (DailyRun must not die on a flat book)
  - Pages push survives origin/main moving mid-run
  - Data freshness refuses a fresh stamp over a stale warehouse
  - No new Downloads\\stockresearch hardcodes in live/critical paths
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"

# Live / DailyRun surfaces that must stay free of Downloads\\stockresearch.
# (Exclude tools/test_*.py and repo_split/ — tests/docs may name the twin path.)
_CRITICAL_PATTERNS = (
    "DailyRun.bat",
    "GetDaily.bat",
    "run_*.bat",
    "publish_github_pages.bat",
    "resolve_python.bat",
    "getTarget.py",
    "generate_investment_report.py",
    "generate_monthly_system_report.py",
    "generate_system_performance_report.py",
    "generate_system_convergence_report.py",
    "generate_sell_report.py",
    "generate_scanner_open_report.py",
    "scripts/publish_github_pages.py",
    "scripts/build_ohlcv_duckdb.py",
    "scripts/analyze_audit_trailing.py",
    "stock_analysis/pygetallMore.py",
    "stock_analysis/RocketOptimizer.py",
    "stock_analysis/rocket_tbn.py",
    "stock_analysis/live_style_sizing.py",
    "stock_analysis/ohlcv_store.py",
    "tools/data_update_freshness.py",
    "tools/check_phantoms.py",
    "tools/zone_origins.py",
    "runmts.bat",
)

_TESTS = (
    "test_gettarget_empty_book.py",
    "test_publish_pages_push.py",
    "test_data_update_freshness.py",
)


def _run_script(name: str) -> int:
    path = _TOOLS / name
    print(f"\n=== {name} ===")
    proc = subprocess.run([sys.executable, str(path)], cwd=str(_REPO))
    return int(proc.returncode)


def _is_critical(rel: str) -> bool:
    rel_n = rel.replace("\\", "/")
    if rel_n.startswith("repo_split/") or "/repo_split/" in rel_n:
        return False
    if rel_n.startswith("tools/test_") or "/tools/test_" in rel_n:
        return False
    if "run_regressions.py" in rel_n:
        return False
    name = Path(rel_n).name
    for pat in _CRITICAL_PATTERNS:
        if "/" in pat:
            if fnmatch.fnmatch(rel_n, pat):
                return True
        elif fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_n, pat):
            return True
    return False


def _path_audit_critical() -> int:
    print("\n=== path audit (critical surfaces) ===")
    rewrite = _REPO / "repo_split" / "lib" / "rewrite_paths.py"
    if not rewrite.is_file():
        print("SKIP rewrite_paths.py missing")
        return 0
    proc = subprocess.run(
        [sys.executable, str(rewrite), "--audit-only", "--root", str(_REPO)],
        cwd=str(_REPO),
        text=True,
        capture_output=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    critical_hits: list[str] = []
    other = 0
    for line in out.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        # "  12  relative/path"
        parts = line.split()
        if len(parts) < 2:
            continue
        rel = parts[-1].replace("\\", "/")
        if _is_critical(rel):
            critical_hits.append(line)
        else:
            other += 1
    if critical_hits:
        print("FAIL critical paths still hardcode Downloads\\stockresearch:")
        for h in critical_hits:
            print(f"  {h}")
        return 1
    print(f"OK  critical surfaces clean ({other} non-critical leftovers under tools/_*/docs OK for now)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--skip-path-audit",
        action="store_true",
        help="Skip Downloads\\stockresearch critical-path audit.",
    )
    ns = p.parse_args(argv)
    failed = 0
    for name in _TESTS:
        rc = _run_script(name)
        if rc != 0:
            failed += 1
            print(f"FAIL {name} exit={rc}")
        else:
            print(f"PASS {name}")
    if not ns.skip_path_audit:
        if _path_audit_critical() != 0:
            failed += 1
    total = len(_TESTS) + (0 if ns.skip_path_audit else 1)
    print(f"\n{total - failed}/{total} checks passed (failed={failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
