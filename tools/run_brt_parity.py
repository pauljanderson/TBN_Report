#!/usr/bin/env python3
"""BRT sheet-parity regression for MAG7 + NFLX (zones first, then BO/retest, trades).

Usage:
  python tools/run_brt_parity.py                    # backtest + zone compare
  python tools/run_brt_parity.py --compare-only RUN_ID
  python tools/run_brt_parity.py --no-run           # compare newest BRT_Closed_* in drive/
  python tools/run_brt_parity.py --zones-only       # zone gates only (still runs backtest unless --compare-only)

Exit 0 when zone gates pass; 1 on regression (when gates defined).
"""
from __future__ import annotations

import argparse
import io
import contextlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from compare_brt_zones import compare_symbol as compare_brt_zone_symbol  # noqa: E402
from compare_breakout_retest import _compare_symbol as compare_brt_bo_symbol  # noqa: E402
from brt_sheet_zone_ledgers import DEFAULT_SYMBOLS  # noqa: E402

MAG7 = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, NFLX"

# Same trading params as YH parity unless BRT-specific tuning is required.
BRT_FLAGS = [
    "stop_pct=0.934",
    "target_pct=1.21",
    "too_high_multiplier=0",
    "band_pct=0.0154",
    "strong_pre_pivot_pct=0.081",
    "strong_post_pivot_pct=0.108",
    "strong_pre_pivot_bars=7",
    "strong_post_pivot_bars=7",
    "breakout_bars=100",
    "tight_range_threshold_pct=0.35",
    "tight_range_lookback=105",
    "sheet_breakout_scan_start_row_delta=2",
    "sheet_touch_pullback_bars=10",
    "brt_sheet_touch=true",
    "max_positions=16",
    "min_spy_compare_1y_at_trigger=-1000",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=false",
    "brt_zones=true",
    "yh_zones=false",
]


@dataclass
class GateResult:
    name: str
    ok: bool
    detail: str


def _newest_closed_run() -> str:
    best: tuple[str, float] | None = None
    for sub in ("drive", "Drive"):
        d = ROOT / sub
        if not d.is_dir():
            continue
        for p in d.glob("BRT_Closed_*.csv"):
            m = re.search(r"BRT_Closed_(\d+)\.csv$", p.name)
            if not m:
                continue
            ts = m.group(1)
            mt = p.stat().st_mtime
            if best is None or mt > best[1]:
                best = (ts, mt)
    if best is None:
        raise FileNotFoundError("No BRT_Closed_*.csv in drive/")
    return best[0]


def _run_backtest(workers: int = 5) -> str:
    cmd = [
        sys.executable,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        "data/newdata/data",
        "-o",
        "drive",
        "-w",
        str(workers),
        "--no-regression",
        "--print-zones",
        "-s",
        MAG7,
    ]
    for kv in BRT_FLAGS:
        cmd.extend(["-v", kv])
    print("[BRT-PARITY] Running backtest...")
    print(" ", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"rocket_brt exited {proc.returncode}")
    m = re.findall(r"BRT_Closed_(\d+)\.csv", proc.stdout + proc.stderr)
    if m:
        return m[-1]
    return _newest_closed_run()


def _bo_stats(sym: str, run_id: str) -> dict[str, int]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        compare_brt_bo_symbol(sym, run_id, brt=True, show_mismatches=0)
    text = buf.getvalue()
    out = {
        "sheet_n": 0,
        "eng_n": 0,
        "dz_matched": 0,
        "dz_rt_date": 0,
        "dz_rt_denom": 0,
        "bo_matched": 0,
        "mr_match": 0,
        "rt_exact": 0,
    }
    for line in text.splitlines():
        if "sheet rows (active):" in line:
            m = re.search(r"sheet rows \(active\): (\d+)\s+engine rows: (\d+)", line)
            if m:
                out["sheet_n"] = int(m.group(1))
                out["eng_n"] = int(m.group(2))
        if "PARITY date+zone matched:" in line:
            m = re.search(r"PARITY date\+zone matched: (\d+)/(\d+)", line)
            if m:
                out["dz_matched"] = int(m.group(1))
        if "PARITY retest date on matched:" in line:
            m = re.search(r"PARITY retest date on matched: (\d+)/(\d+)", line)
            if m:
                out["dz_rt_date"] = int(m.group(1))
                out["dz_rt_denom"] = int(m.group(2))
        if "false-mismatch" in line:
            pass
        elif line.strip().startswith("Matched:") and "Sheet-only" in line and out["bo_matched"] == 0:
            m = re.search(r"Matched: (\d+)\s+Sheet-only: (\d+)\s+Engine-only: (\d+)", line)
            if m and "authoritative" not in line:
                # MR+zone section comes after authoritative section
                idx = text.find(line)
                if idx > 0 and "false-mismatch" in text[:idx]:
                    out["bo_matched"] = int(m.group(1))
        if "Breakouts matched on Main Row:" in line:
            out["mr_match"] = int(line.split(":")[-1].strip())
        if line.strip().startswith("Retest exact (date+row):") and "date+zone" not in line:
            out["rt_exact"] = int(line.split(":")[-1].strip())
    return out


def evaluate_zones(run_id: str, symbols: list[str]) -> list[GateResult]:
    results: list[GateResult] = []
    tot_exact = tot_near = tot_ms = tot_near_ms = tot_sheet = 0
    for sym in symbols:
        stats = compare_brt_zone_symbol(sym, run_id)
        tot_exact += stats["exact"]
        tot_near += stats.get("near", 0)
        tot_ms += stats.get("multiset_match", 0)
        tot_near_ms += stats.get("multiset_near", 0)
        tot_sheet += stats["sheet_n"]
        ms = stats.get("multiset_match", 0)
        ms_near = stats.get("multiset_near", 0)
        sn = stats["sheet_n"]
        ok = sn > 0 and ms_near == sn
        results.append(
            GateResult(
                f"zones/{sym}",
                ok,
                (
                    f"exact={stats['exact']}/{sn} near={stats.get('near', 0)} "
                    f"multiset={ms}/{sn} multiset±0.01={ms_near}/{sn} "
                    f"eng_only_ms={stats.get('eng_only_ms', 0)}"
                ),
            )
        )
    results.append(
        GateResult(
            "zones/TOTAL_multiset±0.01",
            tot_sheet > 0 and tot_near_ms == tot_sheet,
            f"multiset±0.01={tot_near_ms}/{tot_sheet} exact={tot_exact} multiset={tot_ms}/{tot_sheet}",
        )
    )
    return results


def evaluate_bo(run_id: str, symbols: list[str]) -> list[GateResult]:
    results: list[GateResult] = []
    tot_dz = tot_dz_rt = tot_sheet = 0
    for sym in symbols:
        st = _bo_stats(sym, run_id)
        tot_dz += st["dz_matched"]
        tot_dz_rt += st["dz_rt_date"]
        tot_sheet += st["sheet_n"]
        dz_ok = st["sheet_n"] > 0 and st["dz_matched"] == st["sheet_n"]
        rt_ok = st["dz_rt_denom"] > 0 and st["dz_rt_date"] == st["dz_rt_denom"]
        ok = dz_ok and rt_ok
        results.append(
            GateResult(
                f"bo/{sym}",
                ok,
                f"sheet={st['sheet_n']} date+zone={st['dz_matched']}/{st['sheet_n']} "
                f"rt_date={st['dz_rt_date']}/{st['dz_rt_denom']} "
                f"(MR_key={st['bo_matched']} rt_row={st['rt_exact']})",
            )
        )
    results.append(
        GateResult(
            "bo/TOTAL_date+zone",
            tot_sheet > 0 and tot_dz == tot_sheet,
            f"date+zone={tot_dz}/{tot_sheet} retest_date={tot_dz_rt}",
        )
    )
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="BRT sheet parity (MAG7+NFLX)")
    ap.add_argument("--compare-only", metavar="RUN_ID", help="Skip backtest; compare this run id")
    ap.add_argument("--no-run", action="store_true", help="Compare newest BRT_Closed run")
    ap.add_argument("--zones-only", action="store_true", help="Only evaluate zone gates (skip BO)")
    ap.add_argument("-w", "--workers", type=int, default=5)
    ap.add_argument("symbols", nargs="*", help="Optional symbol subset")
    args = ap.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else DEFAULT_SYMBOLS

    if args.compare_only:
        run_id = args.compare_only
    elif args.no_run:
        run_id = _newest_closed_run()
        print(f"[BRT-PARITY] Using newest run: {run_id}")
    else:
        run_id = _run_backtest(workers=args.workers)

    print(f"\n[BRT-PARITY] Run ID: {run_id}\n")
    gate_results = evaluate_zones(run_id, symbols)

    print("\n" + "=" * 80)
    print("BRT ZONE GATES (multiset = authoritative for duplicate rungs)")
    print("=" * 80)
    failed = 0
    for g in gate_results:
        status = "PASS" if g.ok else "FAIL"
        print(f"  [{status}] {g.name}: {g.detail}")
        if not g.ok:
            failed += 1

    if not args.zones_only:
        bo_results = evaluate_bo(run_id, symbols)
        print("\n" + "=" * 80)
        print("BRT BO/RETEST GATES (informational; zone ladder drives BO)")
        print("=" * 80)
        for g in bo_results:
            status = "PASS" if g.ok else "FAIL"
            print(f"  [{status}] {g.name}: {g.detail}")
            if not g.ok:
                failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
