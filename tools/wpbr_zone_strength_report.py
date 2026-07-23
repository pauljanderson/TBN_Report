#!/usr/bin/env python3
"""WPBR zone strength report: zone metrics + trade outcome correlation."""
from __future__ import annotations

import argparse
import csv
import glob
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

from wpbr_compare_filter import SHEET_COMPARE_MIN_DATE, filter_wpbr_output_for_compare
from wpbr_zones import WPBR_STRENGTH_FIELDS, compute_wpbr_touch_stream

DEFAULT_SYMBOLS = "AMZN,AMD,AU,GOOGL,META,TSLA"
WPBR_PARAMS = dict(
    band_pct=0.015,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_pivot_mode="either",
    breakout_confirmation=0.03,
    max_days_after_retest=2,
)


def _load_symbol(sym: str, data_dir: Path) -> pd.DataFrame:
    path = data_dir / f"{sym}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, index_col=0, parse_dates=True)


def _collect_zone_rows(symbols: list[str], data_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for sym in symbols:
        df = _load_symbol(sym, data_dir)
        out = filter_wpbr_output_for_compare(
            compute_wpbr_touch_stream(df, **WPBR_PARAMS),
            df,
            min_date=SHEET_COMPARE_MIN_DATE,
        )
        for ev in out.get("wpbr_zone_events") or []:
            row = {
                "symbol": sym,
                "wpbr_zone_id": ev.get("wpbr_zone_id", ""),
                "pivot_monday": ev.get("pivot_monday", ""),
                "has_breakout": bool(ev.get("breakout_monday")),
                "has_confirm": bool(ev.get("conf_monday")),
                "has_trade_signal": int(ev.get("entry_signal_bar", -1)) >= 0,
            }
            for field in WPBR_STRENGTH_FIELDS:
                v = ev.get(field)
                try:
                    row[field] = float(v) if v is not None and np.isfinite(float(v)) else np.nan
                except (TypeError, ValueError):
                    row[field] = np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def _run_backtest(symbols: list[str], data_dir: Path, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sym_arg = ",".join(symbols)
    py = sys.executable
    cmd = [
        py,
        str(REPO / "stock_analysis" / "rocket_brt.py"),
        str(data_dir),
        "-o",
        str(out_dir),
        "-w",
        "1",
        "--no-regression",
        "-v",
        "wpbr_zones=true",
        "-v",
        "brt_zones=false",
        "-v",
        "yh_zones=false",
        "-v",
        "vec_zones=false",
        "-v",
        "band_pct=0.015",
        "-v",
        "strong_pre_pivot_bars=3",
        "-v",
        "strong_pre_pivot_pct=0.10",
        "-v",
        "strong_post_pivot_bars=3",
        "-v",
        "strong_post_pivot_pct=0.10",
        "-v",
        "strong_pivot_mode=either",
        "-v",
        "wpbr_breakout_confirmation=0.03",
        "-v",
        "wpbr_max_days_after_retest=2",
        "-v",
        "growth_filter_enabled=false",
        "-v",
        "min_spy_compare_1y_at_trigger=-1000",
        "-v",
        'ind_score_weights_path=""',
        "-v",
        "too_high_multiplier=0",
        "-v",
        "target_pct=1.24",
        "-v",
        "stop_pct=0.927",
        "-s",
        sym_arg,
    ]
    print(f"Running WPBR backtest for {len(symbols)} symbols -> {out_dir}")
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-4000:] if proc.stdout else "")
        print(proc.stderr[-4000:] if proc.stderr else "", file=sys.stderr)
        return None
    matches = sorted(glob.glob(str(out_dir / "WPBR_Closed_*.csv")))
    return Path(matches[-1]) if matches else None


def _load_closed_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "PNL_PCT" in df.columns:
        df["pnl_pct_num"] = (
            df["PNL_PCT"].astype(str).str.replace("%", "", regex=False).astype(float)
        )
    else:
        df["pnl_pct_num"] = np.nan
    for field in WPBR_STRENGTH_FIELDS:
        up = field.upper()
        if up in df.columns:
            df[field] = pd.to_numeric(df[up], errors="coerce")
        elif field not in df.columns:
            df[field] = np.nan
    return df


def _summary_stats(series: pd.Series) -> str:
    s = series.dropna()
    if s.empty:
        return "n=0"
    return f"n={len(s)} mean={s.mean():.4f} med={s.median():.4f} p25={s.quantile(0.25):.4f} p75={s.quantile(0.75):.4f}"


def _print_section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    ap = argparse.ArgumentParser(description="WPBR zone strength report")
    ap.add_argument("--data-dir", default=str(REPO / "data" / "newdata" / "data"))
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--skip-backtest", action="store_true", help="Zone metrics only")
    ap.add_argument("--out-dir", default=str(REPO / "output" / "wpbr_strength_report"))
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    zones = _collect_zone_rows(symbols, data_dir)

    _print_section("WPBR ZONE STRENGTH — ZONE UNIVERSE")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Zones (pivot >= {SHEET_COMPARE_MIN_DATE}): {len(zones)}")
    if zones.empty:
        print("No zones found.")
        return 1

    print(f"  With breakout: {int(zones['has_breakout'].sum())}")
    print(f"  With confirmation: {int(zones['has_confirm'].sum())}")
    print(f"  With trade signal: {int(zones['has_trade_signal'].sum())}")

    _print_section("STRENGTH BY ZONE STAGE")
    for label, mask in [
        ("All zones", zones.index == zones.index),
        ("Confirmed only", zones["has_confirm"]),
        ("Trade signal only", zones["has_trade_signal"]),
        ("Confirmed, no trade", zones["has_confirm"] & ~zones["has_trade_signal"]),
    ]:
        sub = zones.loc[mask]
        print(f"\n{label} ({len(sub)})")
        for field in ("wpbr_zone_strength", "wpbr_pre_rise_pct", "wpbr_poc_dist_pct", "wpbr_conf_overshoot_pct", "wpbr_retest_depth_pct"):
            print(f"  {field}: {_summary_stats(sub[field])}")

    _print_section("TRADED vs UNTRADED (signal bar present vs not)")
    traded = zones[zones["has_trade_signal"]]
    untraded = zones[~zones["has_trade_signal"]]
    for field in WPBR_STRENGTH_FIELDS:
        t_mean = traded[field].mean() if not traded.empty else np.nan
        u_mean = untraded[field].mean() if not untraded.empty else np.nan
        if np.isfinite(t_mean) or np.isfinite(u_mean):
            diff = (t_mean - u_mean) if np.isfinite(t_mean) and np.isfinite(u_mean) else np.nan
            print(f"  {field:32s} traded={t_mean:8.4f}  untraded={u_mean:8.4f}  diff={diff:+.4f}")

    if args.skip_backtest:
        out_csv = Path(args.out_dir) / "wpbr_zone_strength_zones.csv"
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        zones.to_csv(out_csv, index=False)
        print(f"\nWrote zone detail: {out_csv}")
        return 0

    closed_path = _run_backtest(symbols, data_dir, Path(args.out_dir))
    if closed_path is None or not closed_path.exists():
        print("Backtest failed or no WPBR_Closed CSV produced.", file=sys.stderr)
        return 2

    trades = _load_closed_trades(closed_path)
    _print_section(f"TRADE OUTCOMES ({closed_path.name})")
    print(f"Closed trades: {len(trades)}")
    if trades.empty:
        return 0

    wins = trades[trades["pnl_pct_num"] > 0]
    losses = trades[trades["pnl_pct_num"] <= 0]
    print(f"  Winners: {len(wins)}  Losers: {len(losses)}")
    print(f"  Avg PnL%: {trades['pnl_pct_num'].mean():.2f}%  Median: {trades['pnl_pct_num'].median():.2f}%")

    if "wpbr_zone_strength" in trades.columns and trades["wpbr_zone_strength"].notna().any():
        trades = trades.dropna(subset=["wpbr_zone_strength"])
        trades["strength_quartile"] = pd.qcut(trades["wpbr_zone_strength"], 4, duplicates="drop")
        _print_section("PNL BY ZONE STRENGTH QUARTILE")
        grp = trades.groupby("strength_quartile", observed=True)["pnl_pct_num"].agg(["count", "mean", "median"])
        print(grp.to_string())

        _print_section("CORRELATION WITH PNL_PCT (closed trades)")
        corrs = []
        for field in WPBR_STRENGTH_FIELDS:
            if field in trades.columns and trades[field].notna().sum() >= 3:
                c = trades[field].corr(trades["pnl_pct_num"])
                if np.isfinite(c):
                    corrs.append((field, c))
        corrs.sort(key=lambda x: abs(x[1]), reverse=True)
        for field, c in corrs[:12]:
            print(f"  {field:32s} r={c:+.3f}")

        _print_section("TOP / BOTTOM TRADES BY ZONE STRENGTH")
        show_cols = ["SYMBOL", "DATE_OPENED", "PNL_PCT", "wpbr_zone_strength", "wpbr_conf_overshoot_pct", "wpbr_retest_depth_pct"]
        show_cols = [c for c in show_cols if c in trades.columns]
        top = trades.nlargest(5, "wpbr_zone_strength")[show_cols]
        bot = trades.nsmallest(5, "wpbr_zone_strength")[show_cols]
        print("\nHighest strength:")
        print(top.to_string(index=False))
        print("\nLowest strength:")
        print(bot.to_string(index=False))

    out_zones = Path(args.out_dir) / "wpbr_zone_strength_zones.csv"
    out_trades = Path(args.out_dir) / "wpbr_zone_strength_trades.csv"
    zones.to_csv(out_zones, index=False)
    trades.to_csv(out_trades, index=False)
    print(f"\nWrote: {out_zones}")
    print(f"Wrote: {out_trades}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
