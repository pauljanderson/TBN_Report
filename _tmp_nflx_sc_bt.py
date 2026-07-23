#!/usr/bin/env python3
"""NFLX: prove orphans appear iff wpbr_second_chance_after_win=True."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
import rocket_brt as rb  # noqa: E402

ORPHANS = {"2022-05-13", "2023-10-16"}


def nd(d):
    if d is None:
        return None
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    s = str(d).strip()
    if s.replace(".0", "").isdigit() and len(s.replace(".0", "")) == 8:
        s = s.replace(".0", "")
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return s


def run(sc: bool):
    df = pd.read_csv(REPO / "data/newdata/data/NFLX.csv", index_col=0, parse_dates=True).sort_index()
    cfg = rb.BRTConfig(
        wpbr_zones=True,
        brt_zones=False,
        yh_zones=False,
        vec_zones=False,
        band_pct=0.015,
        strong_pre_pivot_bars=3,
        strong_pre_pivot_pct=0.10,
        strong_post_pivot_bars=3,
        strong_post_pivot_pct=0.10,
        strong_pivot_mode="either",
        wpbr_breakout_confirmation=0.03,
        wpbr_max_days_after_retest=2,
        wpbr_retest_mode="stop_looking",
        wpbr_second_chance_after_win=sc,
        growth_filter_enabled=False,
        min_spy_compare_1y_at_trigger=-1000.0,
        ind_score_weights_path="",
        too_high_multiplier=0.0,
        target_pct=1.22,
        stop_pct=0.89,
        stop_pct_is_multiplier=True,
        entry_start_date="2016-01-01",
        use_indicators=False,
        indicator_buy="off",
        zone_price_round_decimals=2,
        max_market_cap=0,
    )
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    closed, *_ = rb.run_brt_backtest("NFLX", df, cfg, php, plp, struct, l3)
    rows = []
    for t in closed:
        rows.append(
            {
                "entry": nd(getattr(t, "date_opened", None)),
                "ep": float(getattr(t, "entry_price", 0) or 0),
                "exit": nd(getattr(t, "date_closed", None)),
                "xp": float(getattr(t, "exit_price", 0) or 0),
                "pnl": float(getattr(t, "pnl_pct", 0) or 0),
                "zone": str(getattr(t, "wpbr_zone_id", "") or ""),
                "opp": getattr(t, "wpbr_opportunity_index", None),
            }
        )
    return rows


def main():
    for sc in (False, True):
        rows = run(sc)
        hits = [r for r in rows if r["entry"] in ORPHANS]
        print(f"\n=== second_chance={sc} closed={len(rows)} orphan_hits={len(hits)} ===")
        for r in rows:
            mark = " <== ORPHAN" if r["entry"] in ORPHANS else ""
            print(
                f"  {r['entry']} @ {r['ep']:.2f} -> {r['exit']} @ {r['xp']:.2f} "
                f"pnl={r['pnl']:.2f}% zone={r['zone']}{mark}"
            )
        for h in hits:
            print(f"HIT detail: {h}")


if __name__ == "__main__":
    main()
