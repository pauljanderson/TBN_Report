#!/usr/bin/env python3
"""TBN regression suite — run before commit / as DailyRun preflight.

Covers:
  - getTarget empty book (DailyRun must not die on a flat book)
  - Pages push survives origin/main moving mid-run
  - Data freshness refuses a fresh stamp over a stale warehouse
  - RL compare refuses stamps older than DailyRun start
  - Path audit: deny-by-default for .py/.bat/.ps1/.awk (no twin-tree hardcodes)

Fails if the whole suite (or --max-seconds wall) exceeds the time budget so a
path-audit hang cannot stall DailyRun for minutes.

Do not git commit while drive/DailyRun.in_progress exists (DailyRun mid-run).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
_DEFAULT_MAX_SECONDS = 60.0

_CRITICAL_EXTS = {".py", ".bat", ".ps1", ".awk"}

# Explicit leftovers that still mention the old twin-tree path, with a reason.
# Prefer fixing live defaults; allowlist only frozen one-offs / intentional docs.
_PATH_AUDIT_ALLOWLIST: dict[str, str] = {
    # Frozen dated AB / experiment scripts (not DailyRun; historical URLs/paths).
    "tools/hv15m_day_zone_forward_short_20260928.py": "frozen 2026-09-28 experiment; file:// report link only",
    "tools/meta_yh_probe.py": "one-off META OHLC probe; not wired to DailyRun",
    "tools/risk1pct_size_ab_20260915.py": "frozen AB HTML link to old tree; not live",
    "tools/rl_lookleft_resistance_20260930.py": "frozen 2026-09-30 research ROOT pin",
    "tools/shannon_mtf_lines_post_ab_20260930.py": "frozen AB prose with old file:// path",
    "tools/thorp_timestop_and_chain_scan_20261001.py": "frozen 2026-10-01 research path pin",
    "tools/vwr_system_20261001.py": "frozen 2026-10-01 experiment file:// link",
    "tools/wpbr_improve_priority_ab_20261002.py": "frozen 2026-10-02 AB path pin",
    # stock_analysis one-off debug / sheet dumps (underscore or dated; not engines).
    "stock_analysis/_compare_nvda_sheet.py": "one-off NVDA sheet compare; not DailyRun",
    "stock_analysis/compare_nvda_sheet_vs_python.py": "one-off sheet-vs-python dump",
    "stock_analysis/compute_asof_age_debug.py": "debug as-of age; not wired",
    "stock_analysis/debug_ak_reason_for_date.py": "debug AK reason; not wired",
    "stock_analysis/dump_ar_diff_dates.py": "one-off AR diff dump",
    "stock_analysis/dump_ar_diff_de_df_dg_latest.py": "one-off AR mismatch dump paths",
}


def _run_script(name: str) -> int:
    path = _TOOLS / name
    print(f"\n=== {name} ===")
    proc = subprocess.run([sys.executable, str(path)], cwd=str(_REPO))
    return int(proc.returncode)


def _is_exempt(rel_n: str) -> bool:
    """Non-critical: tools/_*, docs/, repo_split/, tmp_*, or non-script extensions."""
    name = Path(rel_n).name
    if name.startswith("tmp_"):
        return True
    if rel_n.startswith("docs/") or rel_n.startswith("repo_split/"):
        return True
    if rel_n.startswith("tools/") and name.startswith("_"):
        return True
    if Path(rel_n).suffix.lower() not in _CRITICAL_EXTS:
        return True
    return False


def _is_critical(rel: str) -> bool:
    """Deny-by-default: every .py/.bat/.ps1/.awk is critical unless exempt or allowlisted."""
    rel_n = rel.replace("\\", "/")
    if _is_exempt(rel_n):
        return False
    if rel_n in _PATH_AUDIT_ALLOWLIST:
        return False
    return True


def _path_audit_critical() -> int:
    print("\n=== path audit (deny-by-default critical surfaces) ===")
    rewrite_dir = _REPO / "repo_split" / "lib"
    if not (rewrite_dir / "rewrite_paths.py").is_file():
        print("SKIP rewrite_paths.py missing")
        return 0
    # Call audit() directly — --audit-only CLI only prints the top 80 by count
    # and previously hid critical singles (e.g. portfolio_audit.awk).
    if str(rewrite_dir) not in sys.path:
        sys.path.insert(0, str(rewrite_dir))
    from rewrite_paths import audit  # noqa: E402

    t0 = time.perf_counter()
    hits = audit(_REPO)
    elapsed = time.perf_counter() - t0
    print(f"[path audit] {elapsed:.1f}s ({len(hits)} files with hits)")
    critical_hits: list[str] = []
    allowlisted: list[str] = []
    other = 0
    for path, count in sorted(hits, key=lambda x: str(x[0])):
        rel = path.relative_to(_REPO).as_posix()
        line = f"{count:4d}  {rel}"
        if _is_critical(rel):
            critical_hits.append(line)
        elif rel in _PATH_AUDIT_ALLOWLIST:
            allowlisted.append(f"{rel} — {_PATH_AUDIT_ALLOWLIST[rel]}")
        else:
            other += 1
    if critical_hits:
        print("FAIL critical paths still hardcode the old Downloads twin-tree root:")
        for h in critical_hits:
            print(f"  {h}")
        return 1
    if allowlisted:
        print(f"OK  allowlisted leftovers ({len(allowlisted)}):")
        for a in sorted(set(allowlisted)):
            print(f"  {a}")
    print(f"OK  critical surfaces clean ({other} exempt leftovers under tools/_*/docs/repo_split/non-scripts)")
    return 0


_TESTS = (
    "test_gettarget_empty_book.py",
    "test_publish_pages_push.py",
    "test_data_update_freshness.py",
    "test_compare_rl_stale_input.py",
    "test_copy_latest_no_stale_alias.py",
    "test_portfolio_risk.py",
    "test_governance.py",
    "test_live_risk_mult.py",
    "test_truncation_compare.py",
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--skip-path-audit",
        action="store_true",
        help="Skip twin-tree critical-path audit.",
    )
    p.add_argument(
        "--max-seconds",
        type=float,
        default=_DEFAULT_MAX_SECONDS,
        help=f"Fail if the suite wall time exceeds this (default {_DEFAULT_MAX_SECONDS:.0f}s).",
    )
    ns = p.parse_args(argv)
    lock = _REPO / "drive" / "DailyRun.in_progress"
    if lock.is_file():
        stamp = lock.read_text(encoding="utf-8", errors="ignore").strip() or "?"
        print(
            f"NOTE: DailyRun.in_progress present (stamp={stamp}). "
            "Do not git commit until DailyRun finishes and clears the lock."
        )
    t0 = time.perf_counter()
    failed = 0
    for name in _TESTS:
        rc = _run_script(name)
        if rc != 0:
            failed += 1
            print(f"FAIL {name} exit={rc}")
        else:
            print(f"PASS {name}")
        if time.perf_counter() - t0 > ns.max_seconds:
            print(f"FAIL suite exceeded --max-seconds={ns.max_seconds:.0f} during {name}")
            return 1
    if not ns.skip_path_audit:
        if _path_audit_critical() != 0:
            failed += 1
    elapsed = time.perf_counter() - t0
    if elapsed > ns.max_seconds:
        print(f"FAIL suite wall {elapsed:.1f}s > --max-seconds={ns.max_seconds:.0f}")
        return 1
    total = len(_TESTS) + (0 if ns.skip_path_audit else 1)
    print(f"\n{total - failed}/{total} checks passed (failed={failed}, {elapsed:.1f}s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
