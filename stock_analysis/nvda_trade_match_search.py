#!/usr/bin/env python3
"""
Search BRTConfig combinations for NVDA to maximize matches to reference entry (and exit) dates.

Usage (from repo root):
  python stock_analysis/nvda_trade_match_search.py --trials 400 --jobs 6
  python stock_analysis/nvda_trade_match_search.py --mode grid --jobs 4   # smaller exhaustive grid

Only the listed dimensions are varied; other fields use BRTConfig() defaults.
"""
from __future__ import annotations

import argparse
import itertools
import os
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rocket_brt_og import (  # noqa: E402
    BRTConfig,
    compute_market_structure,
    compute_pivots,
    compute_touch_stream,
    load_csv,
    run_brt_backtest,
)

# Reference trades (user-provided): match on entry date first, then exit date.
REF_TRADES: list[tuple[str, str]] = [
    ("2019-04-29", "2019-05-10"),
    ("2019-06-04", "2019-07-24"),
    ("2019-09-16", "2019-11-25"),
    ("2021-05-11", "2021-06-03"),
    ("2022-03-08", "2022-03-24"),
    ("2022-04-13", "2022-04-21"),
    ("2022-05-25", "2022-06-02"),
    ("2022-06-14", "2022-07-01"),
    ("2022-07-08", "2022-08-03"),
    ("2022-08-08", "2022-08-29"),
    ("2022-10-25", "2022-11-10"),
    ("2022-12-28", "2023-01-17"),
    ("2023-01-31", "2023-03-06"),
    ("2024-08-08", "2024-08-19"),
    ("2025-01-28", "2025-03-07"),
]


def _ymd(s: str) -> str:
    return s.strip().replace("-", "")[:8]


REF_ENTRIES: set[str] = {_ymd(a) for a, _ in REF_TRADES}
REF_BY_ENTRY: dict[str, str] = {_ymd(a): _ymd(b) for a, b in REF_TRADES}
N_REF = len(REF_TRADES)


def _cfg_from_overrides(overrides: dict) -> BRTConfig:
    d = asdict(BRTConfig())
    for k, v in overrides.items():
        if k in d:
            d[k] = v
    return BRTConfig(**d)


def _score_backtest(closed: list) -> tuple[int, int, int]:
    """Returns (entry_hits, exit_hits_among_those, n_sim_trades)."""
    by_open: dict[str, str] = {}
    for t in closed:
        if str(getattr(t, "symbol", "")).upper() != "NVDA":
            continue
        op = _ymd(str(t.date_opened))
        cl = _ymd(str(t.date_closed))
        by_open[op] = cl
    entry_hits = sum(1 for e in REF_ENTRIES if e in by_open)
    exit_hits = 0
    for e in REF_ENTRIES:
        if e not in by_open:
            continue
        want_x = REF_BY_ENTRY.get(e)
        if want_x and by_open[e] == want_x:
            exit_hits += 1
    return entry_hits, exit_hits, len(by_open)


def _run_one(overrides: dict, df, sym: str) -> tuple[dict, int, int, int]:
    cfg = _cfg_from_overrides(overrides)
    pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
        df,
        cfg.pivot_k,
        cfg.pivot_d,
        cfg.pivot_disp,
        cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
    level3 = compute_touch_stream(
        df,
        pivot_high,
        pivot_low,
        ph_price,
        pl_price,
        cfg.band_pct,
        cfg.lookback_long,
        cfg.touch_threshold,
        cfg.lookback_short,
        strong_pivots_enabled=cfg.strong_pivots_enabled,
        strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
        strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
        strong_post_pivot_bars=cfg.strong_post_pivot_bars,
        strong_post_pivot_pct=cfg.strong_post_pivot_pct,
        strong_pivot_mode=cfg.strong_pivot_mode,
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        debug_symbol=sym,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    closed, *_ = run_brt_backtest(sym, df, cfg, ph_price, pl_price, struct, level3, benchmark_df=None)
    eh, xh, n = _score_backtest(closed)
    return overrides, eh, xh, n


def _worker_nvda(args: tuple[dict, str]) -> tuple[dict, int, int, int]:
    overrides, csv_path = args
    sym = "NVDA"
    df = load_csv(csv_path)
    return _run_one(overrides, df, sym)


def _random_overrides(rng: random.Random) -> dict:
    return {
        "touch_threshold": rng.choice([2, 3, 4, 5, 6]),
        "strong_pre_pivot_bars": rng.choice([4, 6, 7, 8, 10, 12]),
        "strong_pre_pivot_pct": rng.choice([0.06, 0.08, 0.10, 0.12, 0.15]),
        "strong_post_pivot_bars": rng.choice([4, 6, 7, 8, 10, 12]),
        "strong_post_pivot_pct": rng.choice([0.06, 0.08, 0.09, 0.10, 0.12]),
        "strong_pivot_mode": rng.choice(["pre", "post", "both"]),
        "support_test_enabled": rng.choice([True, False]),
        "tight_range_enabled": rng.choice([True, False]),
        "tradeable_key_level_enabled": rng.choice([True, False]),
        "growth_filter_enabled": rng.choice([True, False]),
        "consolidation_blocker_enabled": rng.choice([True, False]),
        "band_pct": rng.choice([0.015, 0.02, 0.025, 0.03, 0.035]),
    }


def _grid_small() -> list[dict]:
    """Exhaustive product of a reduced space (~a few thousand max)."""
    keys = {
        "touch_threshold": [2, 3, 4, 5],
        "strong_pre_pivot_bars": [6, 8, 10],
        "strong_pre_pivot_pct": [0.08, 0.10, 0.12],
        "strong_post_pivot_bars": [6, 8, 10],
        "strong_post_pivot_pct": [0.08, 0.10, 0.12],
        "strong_pivot_mode": ["pre", "both"],
        "support_test_enabled": [True, False],
        "tight_range_enabled": [True, False],
        "tradeable_key_level_enabled": [True, False],
        "growth_filter_enabled": [True, False],
        "consolidation_blocker_enabled": [True, False],
        "band_pct": [0.02, 0.025],
    }
    names = list(keys.keys())
    combos = []
    for vals in itertools.product(*[keys[k] for k in names]):
        combos.append(dict(zip(names, vals)))
    return combos


def main() -> int:
    ap = argparse.ArgumentParser(description="NVDA BRT parameter search vs reference trade dates.")
    ap.add_argument("--data-dir", type=str, default=str(REPO_ROOT / "data" / "newdata" / "data"))
    ap.add_argument("--trials", type=int, default=400, help="Random combinations (mode=random).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--mode", choices=("random", "grid"), default="random")
    ap.add_argument("--top", type=int, default=20, help="Print top N configs.")
    args = ap.parse_args()

    csv_path = Path(args.data_dir) / "NVDA.csv"
    if not csv_path.is_file():
        print(f"NVDA.csv not found: {csv_path}", file=sys.stderr)
        return 1

    if args.mode == "grid":
        overrides_list = _grid_small()
        print(f"[search] mode=grid combos={len(overrides_list)} jobs={args.jobs}")
    else:
        rng = random.Random(args.seed)
        seen: set[str] = set()
        overrides_list = []
        while len(overrides_list) < args.trials:
            o = _random_overrides(rng)
            key = repr(sorted(o.items()))
            if key in seen:
                continue
            seen.add(key)
            overrides_list.append(o)
        print(f"[search] mode=random trials={len(overrides_list)} seed={args.seed} jobs={args.jobs}")

    tasks = [(o, str(csv_path)) for o in overrides_list]

    results: list[tuple[dict, int, int, int]] = []
    if args.jobs <= 1:
        for t in tasks:
            results.append(_worker_nvda(t))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            futs = [ex.submit(_worker_nvda, t) for t in tasks]
            for fut in as_completed(futs):
                results.append(fut.result())

    # Sort: entry hits, exit hits, fewer spurious trades (prefer tighter match)
    results.sort(key=lambda r: (-r[1], -r[2], r[3]))

    print(f"\nReference trades: {N_REF} | Best entry matches: {results[0][1]} | exit matches (same open): {results[0][2]}")
    print(f"Top {args.top} configs (entry_hits, exit_hits, n_nvda_trades, overrides):\n")
    for i, (o, eh, xh, n) in enumerate(results[: args.top], 1):
        print(f"{i:2}. entry={eh}/{N_REF} exit={xh} n_trades={n} | {o}")

    best = results[0]
    print("\n--- Best as BRTConfig overrides (merge with your run_brt.ps1 -v) ---")
    for k, v in sorted(best[0].items()):
        if isinstance(v, bool):
            print(f"  {k}={'true' if v else 'false'}")
        elif isinstance(v, float):
            print(f"  {k}={v}")
        else:
            print(f"  {k}={v}")
    return 0


if __name__ == "__main__":
    # Windows multiprocessing needs this guard
    raise SystemExit(main())
