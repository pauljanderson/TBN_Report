#!/usr/bin/env python3
"""Trace why engine matures 20.87/20.55/21.19 on 2018-05-21 vs sheet 24.92 next."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_brt import compute_sheet_brt_touch_stream  # noqa: E402

DATA = ROOT / "data" / "newdata" / "data" / "TSLA.csv"


def main() -> int:
    df = pd.read_csv(DATA, parse_dates=["Date"], index_col="Date")
    r = compute_sheet_brt_touch_stream(
        df,
        band_pct=0.0154,
        touch_pullback_pct=0.108,
        maturity_lag=7,
        pre_pivot_pct=0.081,
        post_pivot_bars=7,
        pre_pivot_bars=7,
        pivot_future_move_pct=0.06,
        dedup_tol_pct=0.01,
    )
    tp = r["touch_price"]
    mat = r["matured_now"]
    hi = df["High"].values
    lo = df["Low"].values

    print("=== Touch prices (AB) 2017-08 .. 2018-08 ===")
    for d in df.loc["2017-08-01":"2018-08-31"].index:
        i = df.index.get_loc(d)
        if np.isfinite(tp.iloc[i]):
            zl = r["zone_low"].iloc[i]
            zh = r["zone_high"].iloc[i]
            print(
                f"  {d.date()} bar={i} TP={tp.iloc[i]:.2f} "
                f"Z={zl:.2f}/{zh:.2f} mat_now={bool(mat.iloc[i])}"
            )

    print("\n=== Maturity events in window ===")
    for ev in r["brt_matured_zone_events"]:
        mb = ev["maturity_bar"]
        pb = ev["pivot_bar"]
        md = df.index[mb].date()
        if md < pd.Timestamp("2017-08-01").date() or md > pd.Timestamp("2018-08-31").date():
            continue
        pd_ = df.index[pb].date()
        print(
            f"  mature {md} bar={mb}  pivot {pd_} bar={pb}  "
            f"{ev['zone_center']:.2f}/{ev['zone_lower']:.2f}/{ev['zone_upper']:.2f}"
        )

    print("\n=== Forensics: 2018-05-10 pivot (engine bar 594) ===")
    d0 = pd.Timestamp("2018-05-10")
    i = df.index.get_loc(d0)
    fut = lo[i + 1 : i + 8]
    pre = lo[max(0, i - 7) : i]
    print(f"  High={hi[i]:.4f}")
    print(f"  post7 min low={fut.min():.4f}  drop={(fut.min() / hi[i] - 1) * 100:.2f}%")
    print(f"  pre7 min low={pre.min():.4f}  rise={(hi[i] / pre.min() - 1) * 100:.2f}%")
    print(f"  pullback={(1 - fut.min() / hi[i]) * 100:.2f}%  (need >= 10.8%)")

    print("\n=== Forensics: candidate for sheet 24.92 zone ===")
    # Engine matures 24.92 on 2018-06-27 pivot bar 618
    for label in ("2018-06-20", "2018-06-18", "2018-06-15"):
        d1 = pd.Timestamp(label)
        if d1 not in df.index:
            print(f"  {label}: not in index")
            continue
        j = df.index.get_loc(d1)
        fut2 = lo[j + 1 : j + 8]
        pre2 = lo[max(0, j - 7) : j]
        tps = tp.iloc[j] if np.isfinite(tp.iloc[j]) else None
        print(
            f"  {label} bar={j} H={hi[j]:.4f} TP={tps}  "
            f"pre_rise={(hi[j] / pre2.min() - 1) * 100:.2f}%  "
            f"pullback={(1 - fut2.min() / hi[j]) * 100:.2f}%"
        )

    print("\n=== Local window highs Apr-Jun 2018 (who wins local hi test?) ===")
    pivot_local_window = 4
    for d in pd.date_range("2018-04-01", "2018-06-30", freq="B"):
        if d not in df.index:
            continue
        j = df.index.get_loc(d)
        w0 = max(0, j - pivot_local_window)
        w1 = min(len(df), j + pivot_local_window + 1)
        mx = float(np.max(hi[w0:w1]))
        is_local = bool(np.isclose(float(hi[j]), mx, rtol=0.0, atol=1e-6))
        if is_local or hi[j] >= 24.5:
            mark = "LOCAL" if is_local else ""
            tps = f"TP={tp.iloc[j]:.2f}" if np.isfinite(tp.iloc[j]) else ""
            print(f"  {d.date()} H={hi[j]:.4f} {mark} {tps}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
