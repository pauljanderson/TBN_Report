#!/usr/bin/env python3
"""Compare RL backtest output to gold-standard RL_Closed CSV (AWK or Python engine).

Usage:
  python tools/run_rl_parity.py --gold Drive/RL_LatestRun_Closed.csv
  python tools/run_rl_parity.py --gold Drive/RL_LatestRun_Closed.csv --candidate Drive/RL_Closed_260629143410.csv
  python tools/run_rl_parity.py --run -s "TSLA,AMD,INTC"   # once rocket_brt rl_mode=true exists
  python tools/run_rl_parity.py --run --symbols-file data/rl_gold_universe.txt
  python tools/run_rl_parity.py --run-audit -s "TSLA,AMD"  # run legacy AWK + compare to prior gold

Exit 0 on full trade-key + price parity; 1 on mismatch.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TRADE_KEY_COLS_RL = ("SYMBOL", "DATE OPENED", "DATE CLOSED", "EXIT TYPE")
COMPARE_COLS_RL = (
    "SYMBOL",
    "DATE OPENED",
    "DATE CLOSED",
    "ENTRY PRICE",
    "EXIT PRICE",
    "PNL %",
    "DAYS HELD",
    "EXIT TYPE",
    "ORIGINAL STOP",
    "ORIGINAL TARGET",
)


@dataclass
class ParityResult:
    gold_rows: int
    cand_rows: int
    key_mismatches: list[str]
    field_mismatches: list[str]
    gold_only: list[tuple]
    cand_only: list[tuple]

    @property
    def ok(self) -> bool:
        return not self.key_mismatches and not self.field_mismatches and not self.gold_only and not self.cand_only


def _norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().upper())


def _load_rl_closed(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"No header in {path}")
        headers = [_norm_header(h) for h in reader.fieldnames]
        rows: list[dict[str, str]] = []
        for raw in reader:
            row = {_norm_header(k): (v or "").strip() for k, v in raw.items()}
            rows.append(row)
        return headers, rows


def _trade_key(row: dict[str, str]) -> tuple:
    return tuple(row.get(_norm_header(c), "") for c in TRADE_KEY_COLS_RL)


def _floatish(s: str) -> float | None:
    s = s.replace("%", "").replace(",", "").replace("$", "").strip()
    if not s:
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def compare_rl_closed(gold_path: Path, cand_path: Path, *, max_field_diffs: int = 20) -> ParityResult:
    _, gold_rows = _load_rl_closed(gold_path)
    _, cand_rows = _load_rl_closed(cand_path)

    gold_map = {_trade_key(r): r for r in gold_rows}
    cand_map = {_trade_key(r): r for r in cand_rows}

    gold_keys = set(gold_map)
    cand_keys = set(cand_map)
    gold_only = sorted(gold_keys - cand_keys)
    cand_only = sorted(cand_keys - gold_keys)

    field_mismatches: list[str] = []
    for key in sorted(gold_keys & cand_keys):
        g, c = gold_map[key], cand_map[key]
        for col in COMPARE_COLS_RL:
            nc = _norm_header(col)
            gv, cv = g.get(nc, ""), c.get(nc, "")
            if col in ("ENTRY PRICE", "EXIT PRICE", "ORIGINAL STOP", "ORIGINAL TARGET"):
                gf, cf = _floatish(gv), _floatish(cv)
                if gf is not None and cf is not None:
                    if abs(gf - cf) > 0.02:
                        field_mismatches.append(f"{key} {col}: gold={gv} cand={cv}")
                elif gv != cv:
                    field_mismatches.append(f"{key} {col}: gold={gv} cand={cv}")
            elif col == "PNL %":
                gf, cf = _floatish(gv), _floatish(cv)
                if gf is not None and cf is not None:
                    if abs(gf - cf) > 0.05:
                        field_mismatches.append(f"{key} {col}: gold={gv} cand={cv}")
                elif gv != cv:
                    field_mismatches.append(f"{key} {col}: gold={gv} cand={cv}")
            elif gv != cv:
                field_mismatches.append(f"{key} {col}: gold={gv} cand={cv}")
            if len(field_mismatches) >= max_field_diffs:
                break
        if len(field_mismatches) >= max_field_diffs:
            break

    return ParityResult(
        gold_rows=len(gold_rows),
        cand_rows=len(cand_rows),
        key_mismatches=[],
        field_mismatches=field_mismatches,
        gold_only=gold_only,
        cand_only=cand_only,
    )


def _print_result(res: ParityResult, gold: Path, cand: Path) -> None:
    print(f"Gold:      {gold} ({res.gold_rows} trades)")
    print(f"Candidate: {cand} ({res.cand_rows} trades)")
    if res.gold_only:
        print(f"\nMissing from candidate ({len(res.gold_only)}):")
        for k in res.gold_only[:10]:
            print(f"  {k}")
        if len(res.gold_only) > 10:
            print(f"  ... +{len(res.gold_only) - 10} more")
    if res.cand_only:
        print(f"\nExtra in candidate ({len(res.cand_only)}):")
        for k in res.cand_only[:10]:
            print(f"  {k}")
        if len(res.cand_only) > 10:
            print(f"  ... +{len(res.cand_only) - 10} more")
    if res.field_mismatches:
        print(f"\nField mismatches ({len(res.field_mismatches)}):")
        for line in res.field_mismatches:
            print(f"  {line}")
    if res.ok:
        print("\nPASS: trade keys and compared fields match.")
    else:
        print("\nFAIL: parity check failed.")


def _run_legacy_audit(symbols: str) -> None:
    ps1 = ROOT / "run_audit.ps1"
    if not ps1.is_file():
        raise FileNotFoundError(ps1)
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ps1),
        "-AllowRegression",
        "-s",
        symbols,
    ]
    print("[rl-parity] Running legacy AWK audit...")
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def _run_python_rl(symbols: str, workers: int) -> Path:
    """Run rocket_brt.py rl_mode=true once implemented; raises if not wired."""
    out_dir = ROOT / "drive"
    cmd = [
        sys.executable,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o",
        "drive",
        "-w",
        str(workers),
        "--no-regression",
        "-v",
        "rl_mode=true",
        "-v",
        "brt_zones=false",
        "-v",
        "yh_zones=false",
        "-v",
        "indicator_buy=off",
        "-s",
        symbols,
    ]
    print("[rl-parity] Running Python RL:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("rocket_brt rl_mode=true failed (engine not implemented yet?)")
    ts_path = out_dir / "last_run_ts.txt"
    if ts_path.is_file():
        ts = ts_path.read_text(encoding="utf-8").strip()
        closed = out_dir / f"RL_Closed_{ts}.csv"
        if closed.is_file():
            return closed
    # newest RL_Closed
    best: Path | None = None
    best_ts = ""
    for p in out_dir.glob("RL_Closed_*.csv"):
        m = re.search(r"RL_Closed_(\d+)\.csv$", p.name)
        if m and m.group(1) > best_ts:
            best_ts = m.group(1)
            best = p
    if best is None:
        raise FileNotFoundError("No RL_Closed_*.csv after Python run")
    return best


def _load_symbols_file(path: Path) -> str:
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        symbols.append(line.upper())
    if not symbols:
        raise ValueError(f"No symbols in {path}")
    return ",".join(symbols)


def main() -> int:
    ap = argparse.ArgumentParser(description="RL closed-trade parity vs gold standard")
    ap.add_argument("--gold", type=Path, default=ROOT / "Drive" / "RL_LatestRun_Closed.csv")
    ap.add_argument("--candidate", type=Path, default=None)
    ap.add_argument("--run", action="store_true", help="Run Python rl_mode=true then compare")
    ap.add_argument(
        "--symbols-file",
        type=Path,
        default=None,
        help="One symbol per line (e.g. data/rl_gold_universe.txt for 76-stock gold standard)",
    )
    ap.add_argument("--run-audit", action="store_true", help="Run legacy AWK audit then compare")
    ap.add_argument("-s", "--symbols", default="", help="Symbol list for --run / --run-audit")
    ap.add_argument("-w", type=int, default=4)
    args = ap.parse_args()

    symbols = args.symbols
    if args.symbols_file is not None:
        symbols = _load_symbols_file(args.symbols_file.resolve())

    gold = args.gold.resolve()
    if not gold.is_file():
        print(f"Gold file not found: {gold}", file=sys.stderr)
        return 1

    cand = args.candidate
    if args.run_audit:
        if not symbols:
            print("-s or --symbols-file required for --run-audit", file=sys.stderr)
            return 1
        _run_legacy_audit(symbols)
        ts = (ROOT / "drive" / "last_run_ts.txt").read_text(encoding="utf-8").strip()
        cand = ROOT / "drive" / f"RL_Closed_{ts}.csv"
    elif args.run:
        if not symbols:
            print("-s or --symbols-file required for --run", file=sys.stderr)
            return 1
        cand = _run_python_rl(symbols, args.w)

    if cand is None:
        print("Specify --candidate, --run, or --run-audit", file=sys.stderr)
        return 1

    cand = cand.resolve()
    if not cand.is_file():
        print(f"Candidate not found: {cand}", file=sys.stderr)
        return 1

    res = compare_rl_closed(gold, cand)
    _print_result(res, gold, cand)
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
