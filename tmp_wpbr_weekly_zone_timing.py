"""Timed slice: weekly agg vs WPBR zone compute vs load. Does not touch DuckDB write."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "stock_analysis"))

from wpbr_zones import aggregate_weekly, compute_wpbr_touch_stream  # noqa: E402

DATA = ROOT / "data" / "newdata" / "data"
OUT = ROOT / "drive" / "paul_experiments" / "wpbr_weekly_zone_cache_20261002"
OUT.mkdir(parents=True, exist_ok=True)

# Small mix of liquid names + a few midcaps; enough bars for meaningful weeklies.
SYMS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "NFLX",
    "COST", "JPM", "XOM", "UNH", "LLY", "CRM", "ORCL", "ADBE", "INTC", "QCOM",
    "BA", "CAT", "GE", "HON", "DE", "ANET", "PANW", "CRWD", "SNOW", "PLTR",
]


def load_csv(sym: str) -> pd.DataFrame:
    p = DATA / f"{sym}.csv"
    df = pd.read_csv(p)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    return df[cols].astype(float)


def main() -> None:
    rows = []
    t_load = t_weekly = t_zone = 0.0
    n_ok = 0
    n_weeks = 0
    n_zones = 0
    n_bars = 0

    # Warm import / JIT-ish
    _ = aggregate_weekly(load_csv("AAPL").tail(260))

    for sym in SYMS:
        p = DATA / f"{sym}.csv"
        if not p.is_file():
            continue
        t0 = time.perf_counter()
        df = load_csv(sym)
        t1 = time.perf_counter()
        w = aggregate_weekly(df)
        t2 = time.perf_counter()
        stream = compute_wpbr_touch_stream(
            df,
            band_pct=0.015,
            strong_pre_pivot_bars=3,
            strong_pre_pivot_pct=0.10,
            strong_post_pivot_bars=3,
            strong_post_pivot_pct=0.10,
            strong_pivot_mode="either",
            breakout_confirmation=0.03,
            max_days_after_retest=2,
            retest_mode="stop_looking",
            zone_price_round_decimals=2,
            merge_overlapping_zones=False,
        )
        t3 = time.perf_counter()
        z = list(stream.get("wpbr_zone_events") or [])
        dl = t1 - t0
        wl = t2 - t1
        zl = t3 - t2
        t_load += dl
        t_weekly += wl
        t_zone += zl
        n_ok += 1
        n_weeks += len(w)
        n_zones += len(z)
        n_bars += len(df)
        rows.append(
            {
                "symbol": sym,
                "bars": len(df),
                "weeks": len(w),
                "zones": len(z),
                "load_s": round(dl, 4),
                "weekly_s": round(wl, 4),
                "zone_s": round(zl, 4),
                "zone_plus_weekly_s": round(wl + zl, 4),
            }
        )
        print(
            f"{sym:6s} bars={len(df):5d} weeks={len(w):4d} zones={len(z):3d} "
            f"load={dl*1000:6.1f}ms weekly={wl*1000:6.1f}ms zone={zl*1000:6.1f}ms",
            flush=True,
        )

    summary = {
        "n_symbols": n_ok,
        "n_bars": n_bars,
        "n_weeks": n_weeks,
        "n_zones": n_zones,
        "load_s": round(t_load, 4),
        "weekly_s": round(t_weekly, 4),
        "zone_s": round(t_zone, 4),
        "weekly_plus_zone_s": round(t_weekly + t_zone, 4),
        "weekly_share_of_zone_pipeline_pct": round(
            100.0 * t_weekly / max(1e-12, t_weekly + t_zone), 2
        ),
        "zone_share_of_zone_pipeline_pct": round(
            100.0 * t_zone / max(1e-12, t_weekly + t_zone), 2
        ),
        "mean_weekly_ms": round(1000.0 * t_weekly / max(1, n_ok), 2),
        "mean_zone_ms": round(1000.0 * t_zone / max(1, n_ok), 2),
        "extrapolate_1100_symbols_weekly_s": round(t_weekly * (1100 / max(1, n_ok)), 1),
        "extrapolate_1100_symbols_zone_s": round(t_zone * (1100 / max(1, n_ok)), 1),
        "extrapolate_1100_symbols_pipeline_s": round(
            (t_weekly + t_zone) * (1100 / max(1, n_ok)), 1
        ),
        "note": (
            "Zone pipeline = aggregate_weekly + compute_wpbr_touch_stream. "
            "Does not include engine trade sim / equity / IO beyond CSV load. "
            "CPU may be contended by other jobs."
        ),
        "rows": rows,
    }
    out_json = OUT / "timing_slice.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2), flush=True)
    print(f"wrote {out_json}", flush=True)


if __name__ == "__main__":
    main()
