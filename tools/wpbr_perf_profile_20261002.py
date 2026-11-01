#!/usr/bin/env python3
"""WPBR performance profile harness (research only; does not touch DailyRun freeze).

Phases:
  1) Microbench: compute_wpbr_touch_stream + cProfile on heavy symbols (light CPU).
  2) Optional slice engine run with --profile -w N (full pipeline phases).

Outputs under drive/paul_experiments/wpbr_perf_profile_20261002/.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
sys.path.insert(0, str(SA))

OUT = REPO / "drive" / "paul_experiments" / "wpbr_perf_profile_20261002"
DATA = REPO / "data" / "newdata" / "data"

# Match run_wpbr.bat freeze knobs (do not change).
WPBR_KW = dict(
    band_pct=0.015,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_pivot_mode="either",
    breakout_confirmation=0.03,
    max_days_after_retest=2,
)


def _load_csv(sym: str):
    import pandas as pd

    p = DATA / f"{sym}.csv"
    df = pd.read_csv(p, parse_dates=True, index_col=0)
    df.index = pd.to_datetime(df.index)
    # Normalize columns like engine
    colmap = {c: c.strip().title() if c.lower() in {"open", "high", "low", "close", "volume"} else c for c in df.columns}
    df = df.rename(columns=colmap)
    return df


def microbench(symbols: list[str], *, dump_prof: Path | None = None) -> dict:
    from wpbr_zones import compute_wpbr_touch_stream

    rows = []
    pr = cProfile.Profile()
    t_all = time.perf_counter()
    pr.enable()
    for sym in symbols:
        df = _load_csv(sym)
        t0 = time.perf_counter()
        out = compute_wpbr_touch_stream(df, **WPBR_KW)
        dt = time.perf_counter() - t0
        rows.append(
            {
                "symbol": sym,
                "bars": int(len(df)),
                "zones": len(out.get("wpbr_zone_events") or []),
                "entries": len(out.get("wpbr_entry_opportunities") or []),
                "t_touch_s": round(dt, 4),
            }
        )
        print(f"[micro] {sym}: bars={len(df)} zones={rows[-1]['zones']} entries={rows[-1]['entries']} {dt:.3f}s", flush=True)
    pr.disable()
    wall = time.perf_counter() - t_all

    buf = io.StringIO()
    stats = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    stats.print_stats(40)
    txt = buf.getvalue()
    if dump_prof:
        dump_prof.parent.mkdir(parents=True, exist_ok=True)
        pr.dump_stats(str(dump_prof))
        (dump_prof.with_suffix(".txt")).write_text(txt, encoding="utf-8")

    # Parse top functions by tottime from pstats
    top = []
    stats2 = pstats.Stats(pr)
    stats2.sort_stats("tottime")
    for func, (cc, nc, tt, ct, callers) in list(stats2.stats.items()):
        top.append(
            {
                "file": func[0],
                "line": func[1],
                "func": func[2],
                "tottime": round(tt, 4),
                "cumtime": round(ct, 4),
                "ncalls": nc,
            }
        )
    top.sort(key=lambda r: -r["tottime"])
    return {
        "wall_s": round(wall, 3),
        "symbols": rows,
        "top_tottime": top[:25],
        "pstats_head": "\n".join(txt.splitlines()[:60]),
    }


def phase_instrument_one(sym: str) -> dict:
    """Fine-grained timing inside compute_wpbr_touch_stream via monkeypatch sections."""
    import numpy as np
    import pandas as pd
    import wpbr_zones as wz

    df = _load_csv(sym)
    n = len(df)
    times: dict[str, float] = {}

    t0 = time.perf_counter()
    daily_index = pd.DatetimeIndex(df.index)
    hi = np.asarray(df["High"].values, dtype=np.float64)
    lo = np.asarray(df["Low"].values, dtype=np.float64)
    op = np.asarray(df["Open"].values, dtype=np.float64)
    cl = np.asarray(df["Close"].values, dtype=np.float64)
    vol = np.asarray(df["Volume"].values, dtype=np.float64) if "Volume" in df.columns else np.zeros(n)
    times["arrays"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    weekly = wz.aggregate_weekly(df)
    times["aggregate_weekly"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    out = wz.compute_wpbr_touch_stream(df, **WPBR_KW)
    times["compute_wpbr_touch_stream"] = time.perf_counter() - t0
    times["zones"] = len(out.get("wpbr_zone_events") or [])
    times["bars"] = n
    times["symbol"] = sym

    # Re-run with internal probes by wrapping key helpers
    probes = {
        "aggregate_weekly": 0.0,
        "weekly_pivots": 0.0,
        "cloud_fill": 0.0,
        "breakout_confirm": 0.0,
        "retest_signal": 0.0,
        "strength_poc": 0.0,
        "strength_other": 0.0,
        "series_wrap": 0.0,
    }

    # Direct instrumented reimplementation of hot path accounting using timing hooks
    # Call compute again under cProfile already covered; here estimate cloud cost.
    wh = weekly["High"].to_numpy(dtype=np.float64)
    wl = weekly["Low"].to_numpy(dtype=np.float64)
    pivots = wz._weekly_pivot_indices(
        wh, wl, pre_bars=3, post_bars=3, pre_pct=0.10, post_pct=0.10, pivot_mode="either"
    )
    # Estimate cloud fill cost as currently written
    dates_norm = daily_index.normalize()
    candidates = []
    for wi in pivots:
        pivot_high = float(wh[wi])
        pivot_week_end_ts = weekly.index[wi]
        pivot_monday = wz._week_monday(pivot_week_end_ts)
        atr_bar = wz._last_daily_bar_on_or_before(pivot_week_end_ts, daily_index)
        if atr_bar is None:
            continue
        touch, zl, zh = wz._round_bounds(pivot_high, 0.015, 2)
        pivot_daily_start = int(np.searchsorted(dates_norm.to_numpy(), pivot_monday.to_numpy(), side="left"))
        if pivot_daily_start >= n:
            continue
        candidates.append(pivot_daily_start)

    tp = np.full(n, np.nan)
    t0 = time.perf_counter()
    for start in candidates:
        for di in range(start, n):
            tp[di] = 1.0
    probes["cloud_fill_naive"] = time.perf_counter() - t0

    # Optimized last-writer watermark (same result when starts nondecreasing)
    tp2 = np.full(n, np.nan)
    t0 = time.perf_counter()
    filled_from = n
    for start in reversed(candidates):
        end = filled_from
        if start < end:
            tp2[start:end] = 1.0
        filled_from = min(filled_from, start)
    probes["cloud_fill_watermark"] = time.perf_counter() - t0
    probes["cloud_parity_ok"] = bool(np.array_equal(np.isnan(tp), np.isnan(tp2)) and np.allclose(np.nan_to_num(tp), np.nan_to_num(tp2)))
    probes["n_candidates"] = len(candidates)
    probes["n_pivots"] = len(pivots)

    # POC cost
    t0 = time.perf_counter()
    for start in candidates[: min(50, len(candidates))]:
        wz._wpbr_poc_confluence(hi, lo, cl, vol, min(n - 1, start + 5), float(cl[min(n - 1, start)]))
    probes["poc_50"] = time.perf_counter() - t0

    times["probes"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in probes.items()}
    times.update({k: round(v, 4) if isinstance(v, float) else v for k, v in times.items() if k != "probes"})
    return times


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="AAPL,NVDA,AMZN,MSFT,META,TSLA,AMD,GOOGL,AVGO,JPM")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("[wpbr_perf] microbench + cProfile", flush=True)
    micro = microbench(syms, dump_prof=args.out / "wpbr_zones_cprofile.prof")
    (args.out / "microbench.json").write_text(json.dumps(micro, indent=2), encoding="utf-8")

    print("[wpbr_perf] phase instrument", flush=True)
    phases = [phase_instrument_one(s) for s in syms[:5]]
    (args.out / "phase_instrument.json").write_text(json.dumps(phases, indent=2), encoding="utf-8")
    print(json.dumps({"micro_wall_s": micro["wall_s"], "top5": micro["top_tottime"][:8], "phases": phases}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
