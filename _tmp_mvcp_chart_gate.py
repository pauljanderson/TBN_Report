"""Agent chart-gate proxy: Closed trades vs OHLC for minervini_vcp stamp 260801122831."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(r"C:\Users\songg\Downloads\stockresearch\data\newdata\data")
CLOSED = Path(r"C:\Users\songg\Downloads\stockresearch\drive\MVCP_Closed_260801122831.csv")


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{sym}.csv")
    cols = {c.lower(): c for c in df.columns}
    date_c = cols.get("date") or cols.get("datetime") or df.columns[0]
    df["Date"] = pd.to_datetime(df[date_c])
    for need in ["Open", "High", "Low", "Close", "Volume"]:
        for c in df.columns:
            if c.lower() == need.lower():
                df[need] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values("Date").reset_index(drop=True)
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA150"] = df["Close"].rolling(150).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["Vol50"] = df["Volume"].rolling(50).mean()
    return df


def idx_of(df: pd.DataFrame, d: pd.Timestamp) -> int:
    m = df.index[df["Date"] == d]
    if len(m):
        return int(m[0])
    return int((df["Date"] - d).abs().idxmin())


def analyze_trade(row: pd.Series) -> dict:
    sym = row["SYMBOL"]
    df = load(sym)
    trig = pd.Timestamp(str(row["TRIGGER_DATE"]))
    open_d = pd.Timestamp(str(row["DATE_OPENED"]))
    close_d = pd.Timestamp(str(row["DATE_CLOSED"]))
    ti, oi, ci = idx_of(df, trig), idx_of(df, open_d), idx_of(df, close_d)
    pivot = float(row["PIVOT"])
    final_low = float(row["FINAL_LOW"])
    trig_close = float(row["TRIGGER_CLOSE"])
    entry = float(row["ENTRY_PRICE"])
    stop = float(row["STOP_PRICE"])
    tbar = df.iloc[ti]
    template = {
        "c>sma150": bool(tbar["Close"] > tbar["SMA150"]) if pd.notna(tbar["SMA150"]) else None,
        "c>sma200": bool(tbar["Close"] > tbar["SMA200"]) if pd.notna(tbar["SMA200"]) else None,
        "sma150>sma200": (
            bool(tbar["SMA150"] > tbar["SMA200"])
            if pd.notna(tbar["SMA150"]) and pd.notna(tbar["SMA200"])
            else None
        ),
        "c>sma50": bool(tbar["Close"] > tbar["SMA50"]) if pd.notna(tbar["SMA50"]) else None,
        "sma200_up": (
            bool(tbar["SMA200"] > df.iloc[ti - 21]["SMA200"])
            if ti >= 21 and pd.notna(tbar["SMA200"])
            else None
        ),
    }
    win52 = df.iloc[max(0, ti - 252) : ti + 1]
    hi52 = win52["High"].max()
    lo52 = win52["Low"].min()
    hold = df.iloc[oi : ci + 1]
    mae = (hold["Low"].min() - entry) / entry
    mfe = (hold["High"].max() - entry) / entry
    recent_hi = df.iloc[max(0, ti - 40) : ti + 1]["High"].max()
    v_final = df.iloc[max(0, ti - 10) : ti]["Volume"].mean()
    v_prior = df.iloc[max(0, ti - 30) : max(0, ti - 10)]["Volume"].mean()
    # 15-bar context before trigger: highs/lows for visual coil
    ctx = df.iloc[max(0, ti - 45) : ti + 1]
    coil_hi = ctx["High"].max()
    coil_lo = ctx["Low"].min()
    # depth shrink check from CSV depths
    depths = [float(x) for x in str(row["DEPTHS"]).split(";") if x]
    shrink_ok = all(depths[i] <= 0.65 * depths[i - 1] + 1e-9 for i in range(1, len(depths)))
    return {
        "symbol": sym,
        "open": str(row["DATE_OPENED"]),
        "close": str(row["DATE_CLOSED"]),
        "exit": row["EXIT_TYPE"],
        "pnl": float(row["PNL_PCT"]),
        "days": int(row["DAYS_HELD"]),
        "n": int(row["CONTRACTIONS"]),
        "depths": str(row["DEPTHS"]),
        "shrink_ok": shrink_ok,
        "rs": float(row["RS_PERCENTILE"]),
        "volx": float(row["VOL_RATIO_TRIGGER"]),
        "pivot": pivot,
        "final_low": final_low,
        "final_depth_pct": round(100 * (pivot - final_low) / pivot, 2),
        "chase_trig_pct": round(100 * (trig_close - pivot) / pivot, 2),
        "fill_vs_pivot_pct": round(100 * (entry - pivot) / pivot, 2),
        "fill_vs_trig_pct": round(100 * (entry - trig_close) / trig_close, 2),
        "stop_risk_pct": round(100 * (entry - stop) / entry, 2),
        "pivot_vs_45d_hi_pct": round(100 * abs(pivot - coil_hi) / coil_hi, 2),
        "vol_dry_10_20": round(float(v_final / v_prior), 3) if v_prior else None,
        "near_high": bool(tbar["Close"] >= 0.75 * hi52),
        "above_low30": bool(tbar["Close"] >= 1.30 * lo52),
        "template": template,
        "mae_pct": round(100 * mae, 2),
        "mfe_pct": round(100 * mfe, 2),
        "trig_close": trig_close,
        "entry": entry,
        "stop": stop,
        "target": float(row["TARGET_PRICE"]),
        "exit_px": float(row["EXIT_PRICE"]),
        "coil_range_pct": round(100 * (coil_hi - coil_lo) / coil_hi, 2),
    }


def main() -> None:
    closed = pd.read_csv(CLOSED)
    results = [analyze_trade(r) for _, r in closed.iterrows()]
    priority = ["AXON", "CMG", "NVDA", "AVGO", "CRM", "DECK", "AMD", "TSLA", "ANET"]
    for sym in priority:
        for o in results:
            if o["symbol"] != sym:
                continue
            print("=" * 72)
            print(
                f"{o['symbol']} {o['open']}->{o['close']} {o['exit']} "
                f"PnL={o['pnl']:+.2f}% days={o['days']}"
            )
            print(
                f"  n={o['n']} depths={o['depths']} shrink_ok={o['shrink_ok']} "
                f"RS={o['rs']:.1f} volx={o['volx']:.2f}"
            )
            print(
                f"  pivot={o['pivot']:.4f} final_low={o['final_low']:.4f} "
                f"final_depth={o['final_depth_pct']}%"
            )
            print(
                f"  chase_trig={o['chase_trig_pct']}% fill_vs_pivot={o['fill_vs_pivot_pct']}% "
                f"fill_vs_trig={o['fill_vs_trig_pct']}% stop_risk={o['stop_risk_pct']}%"
            )
            print(
                f"  pivot_vs_45d_hi_err={o['pivot_vs_45d_hi_pct']}% "
                f"coil_range={o['coil_range_pct']}% vol_dry={o['vol_dry_10_20']}"
            )
            print(
                f"  near_high={o['near_high']} above_low30={o['above_low30']} "
                f"template={o['template']}"
            )
            print(f"  MAE={o['mae_pct']}% MFE={o['mfe_pct']}%")

    # Aggregate DNA health
    print("=" * 72)
    print("AGGREGATE")
    n = len(results)
    print(f"trades={n}")
    print(f"shrink_ok={sum(1 for r in results if r['shrink_ok'])}/{n}")
    print(f"template_all_true={sum(1 for r in results if all(r['template'].values()))}/{n}")
    print(f"near_high={sum(1 for r in results if r['near_high'])}/{n}")
    print(f"chase_trig>5%={sum(1 for r in results if r['chase_trig_pct'] > 5.01)}")
    print(f"fill_vs_pivot>10%={sum(1 for r in results if r['fill_vs_pivot_pct'] > 10)}")
    print(f"fill_vs_pivot>20%={sum(1 for r in results if r['fill_vs_pivot_pct'] > 20)}")
    print(f"stop_risk>8.1%={sum(1 for r in results if r['stop_risk_pct'] > 8.1)}")
    print(
        "avg chase_trig=",
        round(np.mean([r["chase_trig_pct"] for r in results]), 2),
        "avg fill_vs_pivot=",
        round(np.mean([r["fill_vs_pivot_pct"] for r in results]), 2),
    )

    # LULU idle
    print("=" * 72)
    print("LULU idle diagnostic")
    df = load("LULU").dropna(subset=["SMA200"]).copy()
    df["hi52"] = df["High"].rolling(252).max()
    df["lo52"] = df["Low"].rolling(252).min()
    cand = df[
        (df["Close"] > df["SMA50"])
        & (df["Close"] > df["SMA150"])
        & (df["Close"] > df["SMA200"])
        & (df["SMA150"] > df["SMA200"])
        & (df["Close"] >= 0.75 * df["hi52"])
        & (df["Close"] >= 1.3 * df["lo52"])
        & (df["Volume"] >= 1.5 * df["Vol50"])
    ]
    print(f"Template+vol1.5x bars (no VCP): {len(cand)}")
    print("last10:", list(cand["Date"].dt.strftime("%Y-%m-%d").tail(10)))


if __name__ == "__main__":
    main()
