#!/usr/bin/env python3
"""YH sheet-parity regression for MAG7 + NFLX.

Runs rocket_brt (optional), then compares zones / breakout-retest / trades vs sheet ledgers.

Usage:
  python tools/run_yh_parity.py                    # backtest + compare
  python tools/run_yh_parity.py --compare-only 260621111231
  python tools/run_yh_parity.py --no-run           # compare newest YH_Closed_* in drive/

Exit 0 when all gates pass; 1 on regression.
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

import pandas as pd

from compare_breakout_retest import _compare_symbol as compare_brt_symbol, DEFAULT_SYMBOLS
from compare_sheet_trades import compare_symbol, _closed_path
from compare_zones import _compare_symbol as compare_zone_symbol
from sheet_breakout_ledgers import DEFAULT_SYMBOLS as BRT_SYMBOLS
from sheet_zone_ledgers import DEFAULT_SYMBOLS as ZONE_SYMBOLS

MAG7 = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, NFLX"

# Minimum acceptable scores (canonical run 260621111231). Tighten as parity improves.
GATES = {
    "trades_exact_min": 229,
    "trades_total": 238,
    "brt_rt_exact_min": {  # per-symbol retest exact (date+row) on Main Row match
        "AAPL": 310,
        "MSFT": 275,
        "GOOGL": 255,
        "AMZN": 320,
        "NVDA": 400,
        "META": 315,
        "TSLA": 375,
        "NFLX": 355,
    },
    "zones_exact_min": {  # known-good single-symbol zone runs
        "TSLA": 51,
        "META": 38,
    },
}

YH_FLAGS = [
    "stop_pct=0.934",
    "too_high_multiplier=0",
    "band_pct=0.015",
    "max_positions=16",
    "min_spy_compare_1y_at_trigger=-1000",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=false",
    "yh_zones=true",
    "brt_zones=false",
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
        for p in d.glob("YH_Closed_*.csv"):
            m = re.search(r"YH_Closed_(\d+)\.csv$", p.name)
            if not m:
                continue
            ts = m.group(1)
            mt = p.stat().st_mtime
            if best is None or mt > best[1]:
                best = (ts, mt)
    if best is None:
        raise FileNotFoundError("No YH_Closed_*.csv in drive/")
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
    for kv in YH_FLAGS:
        cmd.extend(["-v", kv])
    print("[YH-PARITY] Running backtest...")
    print(" ", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"rocket_brt exited {proc.returncode}")
    m = re.findall(r"YH_Closed_(\d+)\.csv", proc.stdout + proc.stderr)
    if m:
        return m[-1]
    return _newest_closed_run()


def _brt_stats(run_id: str, sym: str) -> dict[str, int]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        compare_brt_symbol(sym, run_id, show_mismatches=0)
    text = buf.getvalue()

    def grab(label: str) -> int:
        for line in text.splitlines():
            if label in line:
                val = line.split(":")[-1].strip().split()[0]
                try:
                    return int(val)
                except ValueError:
                    return -1
        return -1

    return {
        "mr_match": grab("Breakouts matched on Main Row"),
        "rt_exact": grab("Retest exact (date+row)"),
        "rt_wrong": grab("Retest date wrong"),
        "zone_bound_mism": grab("Zone bound mismatches on MR"),
    }


def _zone_exact(run_id: str, sym: str) -> int | None:
    zones_path = None
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_ZONES_{sym}_{run_id}.csv"
        if p.is_file():
            zones_path = p
            break
    if zones_path is None:
        return None
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        compare_zone_symbol(sym, run_id)
    for line in buf.getvalue().splitlines():
        if "Exact (ctr+lo+hi):" in line:
            return int(line.split(":")[-1].strip())
    return None


def evaluate(run_id: str, symbols: list[str]) -> list[GateResult]:
    results: list[GateResult] = []
    eng = pd.read_csv(_closed_path(run_id))

    tot_exact = tot_sheet = 0
    for sym in symbols:
        r = compare_symbol(sym, eng, verbose=False)
        tot_exact += r["exact"]
        tot_sheet += r["sheet_n"]
        if r["sheet_only"] or r["eng_only"]:
            results.append(
                GateResult(
                    f"trades/{sym}",
                    r["sheet_only"] == 0 and r["eng_only"] == 0,
                    f"exact={r['exact']}/{r['sheet_n']} sheet_only={r['sheet_only']} eng_only={r['eng_only']}",
                )
            )
    results.append(
        GateResult(
            "trades/TOTAL",
            tot_exact >= GATES["trades_exact_min"] and tot_sheet == GATES["trades_total"],
            f"exact={tot_exact}/{tot_sheet} (min {GATES['trades_exact_min']})",
        )
    )

    for sym in symbols:
        st = _brt_stats(run_id, sym)
        floor = GATES["brt_rt_exact_min"].get(sym, 0)
        ok = st["rt_exact"] >= floor
        results.append(
            GateResult(
                f"brt/{sym}",
                ok,
                f"MR={st['mr_match']} rt_exact={st['rt_exact']} rt_wrong={st['rt_wrong']} "
                f"zone_bound_mism={st['zone_bound_mism']} (min rt_exact {floor})",
            )
        )

    for sym, floor in GATES["zones_exact_min"].items():
        exact = _zone_exact(run_id, sym)
        if exact is None:
            results.append(GateResult(f"zones/{sym}", False, "no YH_ZONES export (need --print-zones run)"))
        else:
            results.append(GateResult(f"zones/{sym}", exact >= floor, f"exact={exact}/{floor}"))

    # Zone ladder for all symbols when exports exist
    for sym in ZONE_SYMBOLS:
        if sym in GATES["zones_exact_min"]:
            continue
        exact = _zone_exact(run_id, sym)
        if exact is None:
            continue
        sheet_n = len(open(ROOT / "tools" / f"{sym.lower()}_sheet_zones.txt").read().splitlines())
        results.append(
            GateResult(f"zones/{sym}", exact == sheet_n, f"exact={exact} sheet={sheet_n}")
        )

    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="YH MAG7+NFLX sheet parity regression")
    ap.add_argument("--compare-only", metavar="RUN_ID", help="Skip backtest; compare existing run")
    ap.add_argument("--no-run", action="store_true", help="Compare newest YH_Closed_* only")
    ap.add_argument("-w", "--workers", type=int, default=5)
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.compare_only:
        run_id = args.compare_only
    elif args.no_run:
        run_id = _newest_closed_run()
    else:
        run_id = _run_backtest(workers=args.workers)

    print(f"\n[YH-PARITY] Run ID: {run_id}\n")
    gates = evaluate(run_id, symbols)

    failed = 0
    print("=" * 72)
    print(f"{'GATE':<20} {'STATUS':<8} DETAIL")
    print("-" * 72)
    for g in gates:
        status = "PASS" if g.ok else "FAIL"
        if not g.ok:
            failed += 1
        print(f"{g.name:<20} {status:<8} {g.detail}")
    print("-" * 72)
    print(f"Summary: {len(gates) - failed}/{len(gates)} gates passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
