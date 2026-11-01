"""Parity + warm/cold timing for WPBR weekly/zone DuckDB cache."""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "stock_analysis"))

from wpbr_weekly_zone_cache import (  # noqa: E402
    format_cache_stats,
    reset_cache_stats,
    resolve_cache_db_path,
)
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

DATA = ROOT / "data" / "newdata" / "data"
OUT = ROOT / "drive" / "paul_experiments" / "wpbr_weekly_zone_cache_20261002"
OUT.mkdir(parents=True, exist_ok=True)
CACHE_DB = OUT / "parity_cache.duckdb"

SYMS = ["AAPL", "MSFT", "NVDA", "META", "AMD", "COST", "CRWD", "PLTR"]


def load_csv(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{sym}.csv")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    return df[cols].astype(float)


def zone_ids(stream: dict) -> list[str]:
    return [str(e.get("wpbr_zone_id") or "") for e in (stream.get("wpbr_zone_events") or [])]


def compare(a: dict, b: dict) -> dict:
    za = a.get("wpbr_zone_events") or []
    zb = b.get("wpbr_zone_events") or []
    ok = len(za) == len(zb) and zone_ids(a) == zone_ids(b)
    ok = ok and list(a.get("wpbr_entry_signal_bars") or []) == list(b.get("wpbr_entry_signal_bars") or [])
    ok = ok and list(a.get("wpbr_entry_fill_bars") or []) == list(b.get("wpbr_entry_fill_bars") or [])
    # Array parity
    for key in ("touch_price", "zone_low", "zone_high", "zone_center"):
        aa = np.asarray(a[key].to_numpy(dtype=np.float64))
        bb = np.asarray(b[key].to_numpy(dtype=np.float64))
        if aa.shape != bb.shape:
            ok = False
            break
        both_nan = np.isnan(aa) & np.isnan(bb)
        if not np.all(both_nan | np.isclose(aa, bb, rtol=0, atol=1e-9, equal_nan=True)):
            ok = False
            break
    # Spot-check a few event numeric fields
    if ok:
        for ea, eb in zip(za, zb):
            for k in ("zone_lower", "zone_upper", "retest_bar", "entry_signal_bar", "entry_fill_bar"):
                if ea.get(k) != eb.get(k):
                    # floats
                    try:
                        if abs(float(ea.get(k)) - float(eb.get(k))) > 1e-9:
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
            if not ok:
                break
    return {
        "ok": ok,
        "n_zones_cold": len(za),
        "n_zones_warm": len(zb),
        "n_signals_cold": len(a.get("wpbr_entry_signal_bars") or []),
        "n_signals_warm": len(b.get("wpbr_entry_signal_bars") or []),
    }


def run_one(sym: str, *, use_cache: bool) -> tuple[dict, float]:
    df = load_csv(sym)
    t0 = time.perf_counter()
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
        use_weekly_zone_cache=use_cache,
        weekly_zone_cache_db=str(CACHE_DB),
        cache_symbol=sym,
        debug_symbol=sym,
    )
    return stream, time.perf_counter() - t0


def main() -> None:
    if CACHE_DB.exists():
        CACHE_DB.unlink()
    # also remove wal if any
    for extra in (str(CACHE_DB) + ".wal",):
        p = Path(extra)
        if p.exists():
            p.unlink()

    reset_cache_stats()
    rows = []
    cold_s = warm_s = 0.0
    all_ok = True

    # Cold with cache writes
    for sym in SYMS:
        if not (DATA / f"{sym}.csv").is_file():
            continue
        cold, tc = run_one(sym, use_cache=True)
        warm, tw = run_one(sym, use_cache=True)
        cmp = compare(cold, warm)
        # Also compare to pure cold (no cache)
        pure, tp = run_one(sym, use_cache=False)
        cmp_pure = compare(pure, warm)
        ok = bool(cmp["ok"] and cmp_pure["ok"])
        all_ok = all_ok and ok
        cold_s += tc
        warm_s += tw
        rows.append(
            {
                "symbol": sym,
                "parity_warm_vs_first_fill": cmp["ok"],
                "parity_warm_vs_no_cache": cmp_pure["ok"],
                "ok": ok,
                "n_zones": cmp["n_zones_cold"],
                "cold_fill_s": round(tc, 4),
                "warm_s": round(tw, 4),
                "no_cache_s": round(tp, 4),
                "speedup_vs_no_cache": round(tp / max(tw, 1e-9), 2),
            }
        )
        print(
            f"{sym}: ok={ok} zones={cmp['n_zones_cold']} "
            f"fill={tc*1000:.0f}ms warm={tw*1000:.0f}ms no_cache={tp*1000:.0f}ms "
            f"speedup={tp/max(tw,1e-9):.1f}x",
            flush=True,
        )

    summary = {
        "all_ok": all_ok,
        "n_symbols": len(rows),
        "cold_fill_s": round(cold_s, 4),
        "warm_s": round(warm_s, 4),
        "mean_speedup_warm_vs_fill": round(cold_s / max(warm_s, 1e-9), 2),
        "cache_stats": format_cache_stats(),
        "cache_db": str(CACHE_DB),
        "flag_default": "OFF (wpbr_weekly_zone_cache=false / WPBR_WEEKLY_ZONE_CACHE unset)",
        "recommendation_default_on": bool(all_ok),
        "rows": rows,
    }
    out = OUT / "parity_timing.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2), flush=True)
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
