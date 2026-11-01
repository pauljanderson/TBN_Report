"""WPBR incremental + no-indicators parity/timing on a small universe."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
OUT = REPO / "drive" / "paul_experiments" / "wpbr_incremental_no_ind_20261002"
RUNS = OUT / "runs"
UNIV = REPO / "drive" / "universes" / "PaulTwenty_universe.csv"

# Live freeze knobs (match run_wpbr.bat) minus workers/universe
BASE_V = [
    "wpbr_zones=true",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "band_pct=0.015",
    "strong_pre_pivot_bars=3",
    "strong_pre_pivot_pct=0.10",
    "strong_post_pivot_bars=3",
    "strong_post_pivot_pct=0.10",
    "strong_pivot_mode=either",
    "wpbr_breakout_confirmation=0.03",
    "wpbr_max_days_after_retest=2",
    "wpbr_second_chance_after_win=true",
    "growth_filter_enabled=false",
    "growth_bars=756",
    "growth_history_slack_bars=0",
    "min_history_bars=0",
    "growth_filter_strict_gt=false",
    "growth_min_pct=0",
    "wpbr_overhead_band_pct=0.22",
    "min_spy_compare_1y_at_trigger=-1000",
    "ind_score_weights_path=",
    "too_high_multiplier=0",
    "target_pct=1.20",
    "stop_pct=0.92",
    "sheet_no_entry_same_bar_after_exit=false",
    "use_indicators=false",
    "max_market_cap=0",
    "min_market_cap=0",
]

# Truncate history for a fast parity test (still multi-year for zones).
END_A = "2024-06-28"  # Friday
END_B = "2024-07-05"  # +5 calendar days (~3-4 sessions)


def load_symbols(n: int = 20) -> list[str]:
    syms = []
    for line in UNIV.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        syms.append(s.upper())
        if len(syms) >= n:
            break
    return syms


def run_arm(name: str, extra_v: list[str], symbols: list[str]) -> dict:
    dest = RUNS / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        PY,
        str(REPO / "stock_analysis" / "rocket_tbn.py"),
        str(REPO / "data" / "newdata" / "data"),
        "-o",
        str(dest),
        "-w",
        "4",
        "--use-duckdb",
        "--no-regression",
        "--no-checkpoint",
        "-s",
        ",".join(symbols),
    ]
    for v in BASE_V + extra_v:
        cmd.extend(["-v", v])
    t0 = time.perf_counter()
    print(f"\n=== RUN {name} ===", flush=True)
    print(" ".join(cmd[-20:]), flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    (dest / "stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (dest / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    (dest / "timing.json").write_text(
        json.dumps({"elapsed_s": elapsed, "returncode": proc.returncode}, indent=2),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        print(proc.stderr[-2000:] if proc.stderr else proc.stdout[-2000:])
        raise RuntimeError(f"{name} failed rc={proc.returncode}")
    print(f"[{name}] {elapsed:.1f}s", flush=True)
    return {"name": name, "elapsed_s": elapsed, "dir": str(dest)}


def latest_closed(d: Path) -> Path | None:
    hits = sorted(d.glob("WPBR_Closed_*.csv"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def latest_open(d: Path) -> Path | None:
    hits = sorted(d.glob("WPBR_Open_*.csv"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def _pf(x) -> float:
    s = str(x or "").strip().replace("%", "").replace(",", "")
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return 0.0
    try:
        return round(float(s), 4)
    except ValueError:
        return 0.0


def trade_keys(path: Path | None) -> set[tuple]:
    if path is None or not path.is_file():
        return set()
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    keys = set()
    for r in rows:
        keys.add(
            (
                (r.get("SYMBOL") or r.get("Symbol") or "").upper(),
                (r.get("DATE_OPENED") or r.get("DATE") or r.get("Entry_Date") or r.get("ENTRY_DATE") or "")[:10],
                (r.get("DATE_CLOSED") or r.get("Exit_Date") or r.get("EXIT_DATE") or "")[:10],
                _pf(r.get("PNL_PCT") or r.get("Pct_PnL")),
            )
        )
    return keys


def open_keys(path: Path | None) -> set[tuple]:
    if path is None or not path.is_file():
        return set()
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    keys = set()
    for r in rows:
        keys.add(
            (
                (r.get("SYMBOL") or r.get("Symbol") or "").upper(),
                (r.get("DATE_OPENED") or r.get("DATE") or r.get("Entry_Date") or r.get("ENTRY_DATE") or "")[:10],
                _pf(r.get("ENTRY_PRICE") or r.get("ENTRY") or r.get("Entry_Price")),
            )
        )
    return keys


def has_ind_cols(path: Path | None) -> bool:
    """True when IND report columns are present with any populated IND_DIFF."""
    if path is None or not path.is_file():
        return False
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    if not rows:
        # header-only: treat IND_* header presence as on
        with path.open(encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
        return any(h.startswith("IND_") for h in header)
    if "IND_DIFF" not in rows[0]:
        return False
    return any(str(r.get("IND_DIFF") or "").strip() not in ("", "nan", "None") for r in rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = load_symbols(20)
    print("symbols", symbols)

    # 1) Full to END_A with incremental ON (builds state) + indicators off
    state_a = OUT / "incr_state_a"
    if state_a.exists():
        shutil.rmtree(state_a)
    r_full_a = run_arm(
        "full_end_a_incr_seed",
        [
            f"backtest_end_date={END_A}",
            "wpbr_incremental=true",
            f"wpbr_incremental_state_dir={state_a}",
            "wpbr_incremental_force_full=true",
        ],
        symbols,
    )

    # 2) Full control to END_B (no incremental)
    r_full_b = run_arm(
        "full_end_b_control",
        [
            f"backtest_end_date={END_B}",
            "wpbr_incremental=false",
        ],
        symbols,
    )

    # 3) Warm incremental from A state to END_B
    # Copy state from A run's state dir (also written under arm out if redirected)
    # The seed run wrote to state_a explicitly.
    r_warm_b = run_arm(
        "warm_end_b_from_a",
        [
            f"backtest_end_date={END_B}",
            "wpbr_incremental=true",
            f"wpbr_incremental_state_dir={state_a}",
        ],
        symbols,
    )

    # 4) Full END_B with indicators ON (timing contrast only; small N)
    r_ind_on = run_arm(
        "full_end_b_indicators_on",
        [
            f"backtest_end_date={END_B}",
            "use_indicators=true",
            "wpbr_incremental=false",
        ],
        symbols,
    )

    ctrl_dir = Path(r_full_b["dir"])
    warm_dir = Path(r_warm_b["dir"])
    ck = trade_keys(latest_closed(ctrl_dir))
    wk = trade_keys(latest_closed(warm_dir))
    co = open_keys(latest_open(ctrl_dir))
    wo = open_keys(latest_open(warm_dir))

    closed_only_ctrl = sorted(ck - wk)
    closed_only_warm = sorted(wk - ck)
    open_only_ctrl = sorted(co - wo)
    open_only_warm = sorted(wo - co)

    parity = {
        "n_closed_ctrl": len(ck),
        "n_closed_warm": len(wk),
        "n_open_ctrl": len(co),
        "n_open_warm": len(wo),
        "closed_match": ck == wk,
        "open_match": co == wo,
        "closed_only_ctrl": closed_only_ctrl[:20],
        "closed_only_warm": closed_only_warm[:20],
        "open_only_ctrl": open_only_ctrl[:20],
        "open_only_warm": open_only_warm[:20],
        "ind_cols_control": has_ind_cols(latest_closed(ctrl_dir)),
        "ind_cols_warm": has_ind_cols(latest_closed(warm_dir)),
        "ind_cols_ind_on": has_ind_cols(latest_closed(Path(r_ind_on["dir"]))),
    }

    timings = {
        "full_end_a_seed_s": r_full_a["elapsed_s"],
        "full_end_b_control_s": r_full_b["elapsed_s"],
        "warm_end_b_from_a_s": r_warm_b["elapsed_s"],
        "full_end_b_indicators_on_s": r_ind_on["elapsed_s"],
        "speedup_warm_vs_full": (
            r_full_b["elapsed_s"] / r_warm_b["elapsed_s"] if r_warm_b["elapsed_s"] > 0 else None
        ),
        "speedup_ind_off_vs_on": (
            r_ind_on["elapsed_s"] / r_full_b["elapsed_s"] if r_full_b["elapsed_s"] > 0 else None
        ),
        "end_a": END_A,
        "end_b": END_B,
        "symbols": symbols,
    }

    summary = {"parity": parity, "timings": timings, "can_work": "yes" if parity["closed_match"] and parity["open_match"] else "partial"}
    (OUT / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["can_work"] == "yes" else 2


if __name__ == "__main__":
    raise SystemExit(main())
