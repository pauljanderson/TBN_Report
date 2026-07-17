#!/usr/bin/env python3
"""
Estimate P(major pivot) from BRT_Closed features available at the touch.
Usage: python analyze_major_probability.py [BRT_Closed_<timestamp>.csv]
Default: Drive/BRT_Closed_260302152707.csv
"""
import sys
from pathlib import Path

import pandas as pd
import numpy as np

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_PATH = SCRIPT_DIR.parent / "Drive" / "BRT_Closed_260302152707.csv"


def load_brt(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Normalize column names
    df.columns = [c.strip() for c in df.columns]
    if "ENTRY_MAJOR_PIVOT" not in df.columns:
        print("[WARN] ENTRY_MAJOR_PIVOT not found; cannot compute major probability.")
        return df
    df["MAJOR"] = (df["ENTRY_MAJOR_PIVOT"] == 1).astype(int)
    return df


def analyze(df: pd.DataFrame) -> None:
    n = len(df)
    if n == 0:
        print("No rows.")
        return
    p_major = df["MAJOR"].mean()
    print("=" * 60)
    print("MAJOR PIVOT PROBABILITY ANALYSIS")
    print("=" * 60)
    print(f"Total trades: {n}")
    print(f"Overall P(major): {p_major:.1%} ({df['MAJOR'].sum():.0f} major)")
    print()

    # 1. By ENTRY_STRUCT_REGIME
    print("--- By ENTRY_STRUCT_REGIME ---")
    for name, g in df.groupby("ENTRY_STRUCT_REGIME", observed=True):
        name = name if pd.notna(name) and str(name).strip() else "(blank)"
        p = g["MAJOR"].mean()
        print(f"  {name:6}  n={len(g):5}  P(major)={p:.1%}")
    print()

    # 2. By TOUCH_COUNT bucket
    print("--- By TOUCH_COUNT bucket ---")
    df["TC_BUCKET"] = pd.cut(
        df["TOUCH_COUNT"],
        bins=[0, 3, 5, 7, 9, 999],
        labels=["3", "4-5", "6-7", "8-9", "10+"],
    )
    for name, g in df.groupby("TC_BUCKET", observed=True):
        if g["MAJOR"].sum() == 0 and len(g) < 10:
            continue
        p = g["MAJOR"].mean()
        print(f"  {name:6}  n={len(g):5}  P(major)={p:.1%}")
    print()

    # 3. By TOUCH_COUNT_SHORT
    print("--- By TOUCH_COUNT_SHORT ---")
    if "TOUCH_COUNT_SHORT" in df.columns:
        for name, g in df.groupby("TOUCH_COUNT_SHORT", observed=True):
            if len(g) < 20:
                continue
            p = g["MAJOR"].mean()
            print(f"  TC_short={name}  n={len(g):5}  P(major)={p:.1%}")
    print()

    # 4. By ZONE_CLUSTER_DENSITY bucket
    print("--- By ZONE_CLUSTER_DENSITY ---")
    if "ZONE_CLUSTER_DENSITY" in df.columns:
        df["CLUSTER_BUCKET"] = pd.cut(
            df["ZONE_CLUSTER_DENSITY"],
            bins=[-1, 0, 5, 10, 15, 999],
            labels=["0", "1-5", "6-10", "11-15", "16+"],
        )
        for name, g in df.groupby("CLUSTER_BUCKET", observed=True):
            if len(g) < 10:
                continue
            p = g["MAJOR"].mean()
            print(f"  {name:6}  n={len(g):5}  P(major)={p:.1%}")
    print()

    # 5. By ENTRY_PIVOT_TYPE
    print("--- By ENTRY_PIVOT_TYPE ---")
    if "ENTRY_PIVOT_TYPE" in df.columns:
        for name, g in df.groupby("ENTRY_PIVOT_TYPE", observed=True):
            name = name if pd.notna(name) and str(name).strip() else "(blank)"
            if len(g) < 10:
                continue
            p = g["MAJOR"].mean()
            print(f"  {name:8}  n={len(g):5}  P(major)={p:.1%}")
    print()

    # 6. Simple rule: combinations that maximize P(major)
    print("--- High P(major) combinations ---")
    # HL + TC>=6
    if "ENTRY_STRUCT_REGIME" in df.columns and "TOUCH_COUNT" in df.columns:
        m = (df["ENTRY_STRUCT_REGIME"] == "HL") & (df["TOUCH_COUNT"] >= 6)
        if m.sum() >= 30:
            p = df.loc[m, "MAJOR"].mean()
            print(f"  HL & TOUCH_COUNT>=6:     n={m.sum():5}  P(major)={p:.1%}")
        m = (df["ENTRY_STRUCT_REGIME"] == "HL") & (df["TOUCH_COUNT"] >= 4)
        if m.sum() >= 30:
            p = df.loc[m, "MAJOR"].mean()
            print(f"  HL & TOUCH_COUNT>=4:     n={m.sum():5}  P(major)={p:.1%}")
        m = (df["ENTRY_STRUCT_REGIME"] == "LL") & (df["TOUCH_COUNT"] >= 6)
        if m.sum() >= 30:
            p = df.loc[m, "MAJOR"].mean()
            print(f"  LL & TOUCH_COUNT>=6:     n={m.sum():5}  P(major)={p:.1%}")
    print()

    # 7. Simple predictive rule (from this run)
    print("--- Predictive Rule: P(major) by proxy ---")
    print("Best proxies (available at touch):")
    if "ENTRY_STRUCT_REGIME" in df.columns:
        rp = df.groupby("ENTRY_STRUCT_REGIME", observed=True)["MAJOR"].agg(["mean", "count"])
        for r, row in rp.iterrows():
            if pd.notna(r) and str(r).strip() and row["count"] >= 50:
                print(f"  - ENTRY_STRUCT_REGIME={r}: P(major)={row['mean']:.1%}")
    if "ENTRY_PIVOT_TYPE" in df.columns:
        pt = df.groupby("ENTRY_PIVOT_TYPE", observed=True)["MAJOR"].agg(["mean", "count"])
        for t, row in pt.iterrows():
            if pd.notna(t) and str(t).strip() and row["count"] >= 20:
                print(f"  - ENTRY_PIVOT_TYPE={t}: P(major)={row['mean']:.1%}")
    if "TOUCH_COUNT_SHORT" in df.columns:
        g1 = df[df["TOUCH_COUNT_SHORT"] == 1]
        if len(g1) >= 20:
            print(f"  - TOUCH_COUNT_SHORT=1: P(major)={g1['MAJOR'].mean():.1%} (avoid)")
    print()

    # 8. Recommended filter
    print("--- Suggested 'High Major Probability' Filter ---")
    # Use: ENTRY_STRUCT_REGIME in (HL, HH) and TOUCH_COUNT >= 4
    if "ENTRY_STRUCT_REGIME" in df.columns:
        m = df["ENTRY_STRUCT_REGIME"].isin(["HL", "HH"])
        if m.sum() >= 50:
            p = df.loc[m, "MAJOR"].mean()
            print(f"  ENTRY_STRUCT_REGIME in (HL, HH): n={m.sum()}  P(major)={p:.1%}")
        m2 = m & (df["TOUCH_COUNT"] >= 5)
        if m2.sum() >= 30:
            p = df.loc[m2, "MAJOR"].mean()
            print(f"  + TOUCH_COUNT>=5:                n={m2.sum()}  P(major)={p:.1%}")
    print("=" * 60)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    if not path.exists():
        print(f"File not found: {path}")
        return 1
    print(f"Loading: {path}")
    df = load_brt(path)
    analyze(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
