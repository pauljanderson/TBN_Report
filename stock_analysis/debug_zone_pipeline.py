#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from rocket_brt import (
    BRTConfig,
    _strong_pivot_bar_ok,
    compute_market_structure,
    compute_pivots,
    compute_touch_stream,
    load_csv,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="Dump per-bar zone pipeline debug for one symbol.")
    ap.add_argument("csv_path", help="Path to symbol CSV, e.g. data/newdata/data/MSFT.csv")
    ap.add_argument("--symbol", default="", help="Optional symbol label for output naming")
    ap.add_argument("--out-dir", default="", help="Output directory (default: CSV parent)")
    ap.add_argument("--set", action="append", default=[], help="Config overrides key=value")
    args = ap.parse_args()

    csv_path = Path(args.csv_path).resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else csv_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = BRTConfig()
    for kv in args.set:
        if "=" not in kv:
            raise SystemExit(f"Invalid --set value: {kv} (expected key=value)")
        k, v = kv.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not hasattr(cfg, k):
            raise SystemExit(f"Unknown config key: {k}")
        cur = getattr(cfg, k)
        if isinstance(cur, bool):
            nv = v.lower() in ("1", "true", "yes", "on")
        elif isinstance(cur, int):
            nv = int(float(v))
        elif isinstance(cur, float):
            nv = float(v)
        else:
            nv = v
        cfg = replace(cfg, **{k: nv})

    df = load_csv(str(csv_path))
    ph, pl, ph_price, pl_price = compute_pivots(df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m)
    struct = compute_market_structure(df, ph, pl, ph_price, pl_price)
    lvl3 = compute_touch_stream(
        df,
        ph,
        pl,
        ph_price,
        pl_price,
        cfg.band_pct,
        cfg.lookback_long,
        cfg.touch_threshold,
        lookback_short=cfg.lookback_short,
        strong_pivots_enabled=cfg.strong_pivots_enabled,
        strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
        strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
        strong_post_pivot_bars=cfg.strong_post_pivot_bars,
        strong_post_pivot_pct=cfg.strong_post_pivot_pct,
        strong_pivot_mode=cfg.strong_pivot_mode,
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )

    hi = np.asarray(df["High"].to_numpy(), dtype=np.float64)
    lo = np.asarray(df["Low"].to_numpy(), dtype=np.float64)
    _hl_dec = int(cfg.zone_price_round_decimals)
    if _hl_dec >= 0:
        hi = np.round(hi, _hl_dec)
        lo = np.round(lo, _hl_dec)
    n = len(df)
    rows: list[dict] = []
    for i in range(n):
        is_ph = int(ph.iloc[i] == 1)
        is_pl = int(pl.iloc[i] == 1)
        pre_ok_h = post_ok_h = pre_ok_l = post_ok_l = 0
        both_ok_h = both_ok_l = 0
        if is_ph:
            pre_ok_h = int(
                _strong_pivot_bar_ok(
                    i, "PH", hi, lo, n,
                    pre_bars=int(cfg.strong_pre_pivot_bars),
                    pre_pct=float(cfg.strong_pre_pivot_pct),
                    post_bars=int(cfg.strong_post_pivot_bars),
                    post_pct=float(cfg.strong_post_pivot_pct),
                    mode="pre",
                )
            )
            post_ok_h = int(
                _strong_pivot_bar_ok(
                    i, "PH", hi, lo, n,
                    pre_bars=int(cfg.strong_pre_pivot_bars),
                    pre_pct=float(cfg.strong_pre_pivot_pct),
                    post_bars=int(cfg.strong_post_pivot_bars),
                    post_pct=float(cfg.strong_post_pivot_pct),
                    mode="post",
                )
            )
            both_ok_h = int(
                _strong_pivot_bar_ok(
                    i, "PH", hi, lo, n,
                    pre_bars=int(cfg.strong_pre_pivot_bars),
                    pre_pct=float(cfg.strong_pre_pivot_pct),
                    post_bars=int(cfg.strong_post_pivot_bars),
                    post_pct=float(cfg.strong_post_pivot_pct),
                    mode="both",
                )
            )
        if is_pl:
            pre_ok_l = int(
                _strong_pivot_bar_ok(
                    i, "PL", hi, lo, n,
                    pre_bars=int(cfg.strong_pre_pivot_bars),
                    pre_pct=float(cfg.strong_pre_pivot_pct),
                    post_bars=int(cfg.strong_post_pivot_bars),
                    post_pct=float(cfg.strong_post_pivot_pct),
                    mode="pre",
                )
            )
            post_ok_l = int(
                _strong_pivot_bar_ok(
                    i, "PL", hi, lo, n,
                    pre_bars=int(cfg.strong_pre_pivot_bars),
                    pre_pct=float(cfg.strong_pre_pivot_pct),
                    post_bars=int(cfg.strong_post_pivot_bars),
                    post_pct=float(cfg.strong_post_pivot_pct),
                    mode="post",
                )
            )
            both_ok_l = int(
                _strong_pivot_bar_ok(
                    i, "PL", hi, lo, n,
                    pre_bars=int(cfg.strong_pre_pivot_bars),
                    pre_pct=float(cfg.strong_pre_pivot_pct),
                    post_bars=int(cfg.strong_post_pivot_bars),
                    post_pct=float(cfg.strong_post_pivot_pct),
                    mode="both",
                )
            )
        rows.append(
            {
                "DATE": df.index[i].strftime("%Y-%m-%d"),
                "OPEN": float(df["Open"].iloc[i]),
                "HIGH": float(df["High"].iloc[i]),
                "LOW": float(df["Low"].iloc[i]),
                "CLOSE": float(df["Close"].iloc[i]),
                "PIVOT_HIGH": is_ph,
                "PIVOT_LOW": is_pl,
                "PH_PRICE": float(ph_price.iloc[i]) if is_ph else "",
                "PL_PRICE": float(pl_price.iloc[i]) if is_pl else "",
                "PRE_OK_PH": pre_ok_h,
                "POST_OK_PH": post_ok_h,
                "BOTH_OK_PH": both_ok_h,
                "PRE_OK_PL": pre_ok_l,
                "POST_OK_PL": post_ok_l,
                "BOTH_OK_PL": both_ok_l,
                "TOUCH_PRICE": float(lvl3["touch_price"].iloc[i]) if pd.notna(lvl3["touch_price"].iloc[i]) else "",
                "ZONE_LOW": float(lvl3["zone_low"].iloc[i]) if pd.notna(lvl3["zone_low"].iloc[i]) else "",
                "ZONE_HIGH": float(lvl3["zone_high"].iloc[i]) if pd.notna(lvl3["zone_high"].iloc[i]) else "",
                "TOUCH_COUNT_LONG": int(lvl3["touch_count_long"].iloc[i]) if pd.notna(lvl3["touch_count_long"].iloc[i]) else 0,
                "MATURED_NOW": int(bool(lvl3["matured_now"].iloc[i])),
            }
        )

    out_sym = args.symbol.strip() or csv_path.stem
    out_path = out_dir / f"BRT_ZONE_PIPELINE_{out_sym}.csv"
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

