#!/usr/bin/env python3
"""AU 2019-04-25 SC miss: DuckDB vs CSV + zone-state trace."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
import rocket_brt as rb  # noqa: E402
from wpbr_zones import find_wpbr_retest_and_signal  # noqa: E402

ZID = "2018-01-26|11.8200|12.1800"
ZL, ZH = 11.82, 12.18


def nd(d):
    s = str(d).strip()
    if s.replace(".0", "").isdigit() and len(s.replace(".0", "")) == 8:
        s = s.replace(".0", "")
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return s


def load_csv():
    return pd.read_csv(REPO / "data/newdata/data/AU.csv", index_col=0, parse_dates=True).sort_index()


def load_duck():
    con = duckdb.connect(str(REPO / "data" / "ohlcv.duckdb"), read_only=True)
    dd = con.execute(
        "SELECT date, open, high, low, close, volume FROM prices WHERE symbol='AU' ORDER BY date"
    ).fetchdf()
    dd["date"] = pd.to_datetime(dd["date"])
    dd = dd.set_index("date").sort_index()
    dd.columns = ["Open", "High", "Low", "Close", "Volume"]
    return dd


def cfg():
    return rb.BRTConfig(
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
        wpbr_second_chance_after_win=True,
        growth_filter_enabled=False,
        min_spy_compare_1y_at_trigger=-1000.0,
        ind_score_weights_path="",
        too_high_multiplier=0.0,
        target_pct=1.22,
        stop_pct=0.91,
        stop_pct_is_multiplier=True,
        entry_start_date="2016-01-01",
        use_indicators=False,
        indicator_buy="off",
        zone_price_round_decimals=2,
        max_market_cap=0,
    )


def probe_signal(df: pd.DataFrame, label: str):
    lo = df["Low"].to_numpy(float)
    cl = df["Close"].to_numpy(float)
    op = df["Open"].to_numpy(float)
    n = len(df)
    idx = {pd.Timestamp(d).strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
    resume = idx["2019-02-20"] + 1
    sig_i = idx["2019-04-24"]
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo,
        cl,
        op,
        scan_start=resume,
        zone_lower=ZL,
        zone_upper=ZH,
        max_days_after_retest=2,
        n=n,
        stop_at=sig_i,
        retest_mode="stop_looking",
    )

    def D(b):
        return None if b is None else str(df.index[b].date())

    window = df.iloc[resume : sig_i + 1]
    ab = window[window["Close"] < ZL - 1e-9]
    cand = window[(window["Low"] <= ZH + 1e-9) & (window["Close"] > ZH + 1e-9)]
    print(f"=== {label} find_signal ===")
    print(f"  rt={D(rt)} sig={D(sig)} fill={D(fill)}")
    print(f"  abandon={len(ab)} retest_cands={len(cand)} first_rt={None if cand.empty else cand.index[0].date()}")
    for d in ["2019-04-23", "2019-04-24", "2019-04-25", "2019-04-26", "2019-04-29", "2019-04-30"]:
        if d in df.index:
            r = df.loc[d]
            print(f"  {d} O={r.Open} H={r.High} L={r.Low} C={r.Close}")


def run_bt(df: pd.DataFrame, label: str):
    c = cfg()
    ph, pl, php, plp = rb.compute_pivots(
        df, c.pivot_k, c.pivot_d, c.pivot_disp, c.pivot_m, realtime_filter_enabled=c.realtime_filter_enabled
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, c, ph, pl, php, plp)
    closed, *_ = rb.run_brt_backtest("AU", df, c, php, plp, struct, l3)
    print(f"=== {label} BT closed={len(closed)} ===")
    focus = {
        "2018-12-28",
        "2019-04-25",
        "2020-05-04",
        "2020-10-28",
        "2023-02-27",
        "2023-09-07",
    }
    for t in closed:
        e = nd(t.date_opened)
        if e in focus or e.startswith("2019-"):
            print(
                f"  {e} @ {float(t.entry_price):.4f} -> {nd(t.date_closed)} "
                f"pnl={float(t.pnl_pct):.2f}% zone={t.wpbr_zone_id} exit={getattr(t,'exit_type',None)}"
            )
    print(f"  HAS 2019-04-25: {any(nd(t.date_opened)=='2019-04-25' for t in closed)}")
    return closed


def main():
    csv = load_csv()
    dd = load_duck()
    for df in (csv, dd):
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    print(f"csv bars={len(csv)} duck bars={len(dd)}")
    w = slice("2019-02-20", "2019-05-02")
    both = csv.loc[w].index.intersection(dd.loc[w].index)
    cols = ["Open", "High", "Low", "Close"]
    a = csv.loc[both, cols].astype(float).round(4)
    b = dd.loc[both, cols].astype(float).round(4)
    b = b.reindex(a.index)
    diff_mask = (a.to_numpy() != b.to_numpy()).any(axis=1)
    print(f"OHLC diffs in window: {int(diff_mask.sum())}")
    if diff_mask.any():
        out = a.loc[diff_mask].copy()
        out.columns = [c + "_csv" for c in cols]
        for c in cols:
            out[c + "_dd"] = b.loc[diff_mask, c].values
        print(out.head(30))

    probe_signal(csv, "CSV")
    probe_signal(dd, "DUCK")
    run_bt(csv, "CSV")
    run_bt(dd, "DUCK")


if __name__ == "__main__":
    main()
