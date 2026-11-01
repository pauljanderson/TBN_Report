#!/usr/bin/env python3
"""Full-universe day-by-day fractal trendline slopes → slope_sum + breadth.

Optimized vs PaulTwenty long CSV: does NOT emit every TF×side row (would be
~50× the 90MB PaulTwenty book). Instead streams per-symbol daily aggregates:

  daily_symbol_slope_sum.csv  (date, symbol, slope_sum, n_lines, n_up, n_down, n_flat)
  daily_breadth.csv           (date, line-level + symbol-level breadth)

Look-ahead-safe confirmation (match tools/trendline_slopes_paultwenty.py):
  daily k=5, weekly W-FRI k=3, monthly ME k=2.

Research only — not gold, not DailyRun.

Usage:
  python tools/trendline_slopes_alluniv.py
  python tools/trendline_slopes_alluniv.py --workers 16 --stamp trendline_slopes_alluniv_20260831
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "newdata" / "data"
DRIVE = ROOT / "drive"
ALL_UNIV = DRIVE / "universes" / "ALL_ohlc_universe.csv"
DEFAULT_STAMP = "trendline_slopes_alluniv_20260831"

PIVOT_K = {"daily": 5, "weekly": 3, "monthly": 2}
WEEK_FREQ = "W-FRI"
MONTH_FREQ = "ME"
FLAT_EPS = 1e-12
MIN_BARS = 50


@dataclass(frozen=True)
class Pivot:
    kind: str  # H | L
    date: date
    price: float
    tf_bar_idx: int
    confirmed_on: date


def load_universe(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.append(s.split(",")[0].strip())
    return out


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    need = ("date", "open", "high", "low", "close")
    if not all(k in cols for k in need):
        return None
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]]).dt.date,
            "Open": df[cols["open"]].astype(float),
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": df[cols["close"]].astype(float),
        }
    )
    return out.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)


def build_htf(daily: pd.DataFrame, rule: str) -> tuple[pd.DataFrame, list[pd.DatetimeIndex]]:
    tmp = daily.copy()
    tmp["_dt"] = pd.to_datetime(tmp["Date"])
    groups: list[tuple[pd.Timestamp, pd.DataFrame]] = []
    for key, g in tmp.set_index("_dt").groupby(pd.Grouper(freq=rule)):
        if g is None or g.empty:
            continue
        groups.append((pd.Timestamp(key), g))
    if not groups:
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "end_date"])
        return empty, []
    rows = []
    members: list[pd.DatetimeIndex] = []
    for _key, g in groups:
        members.append(g.index)
        rows.append(
            {
                "Open": float(g["Open"].iloc[0]),
                "High": float(g["High"].max()),
                "Low": float(g["Low"].min()),
                "Close": float(g["Close"].iloc[-1]),
                "end_date": pd.Timestamp(g.index[-1]).date(),
            }
        )
    return pd.DataFrame(rows), members


def fractal_pivots(high: np.ndarray, low: np.ndarray, k: int) -> list[tuple[str, int]]:
    n = len(high)
    k = max(1, int(k))
    out: list[tuple[str, int]] = []
    for i in range(k, n - k):
        wh = high[i - k : i + k + 1]
        wl = low[i - k : i + k + 1]
        if np.isfinite(high[i]) and high[i] >= float(np.max(wh)):
            out.append(("H", i))
        if np.isfinite(low[i]) and low[i] <= float(np.min(wl)):
            out.append(("L", i))
    return out


def refine_pivot_date(
    daily: pd.DataFrame,
    members: list[pd.DatetimeIndex],
    kind: str,
    i: int,
    high: float,
    low: float,
) -> tuple[date, float]:
    gidx = members[i]
    member_dates = {pd.Timestamp(ts).date() for ts in gidx}
    sub = daily[daily["Date"].isin(member_dates)]
    if sub.empty:
        return pd.Timestamp(gidx[-1]).date(), float(high if kind == "H" else low)
    if kind == "H":
        j = sub["High"].idxmax()
        return sub.loc[j, "Date"], float(sub.loc[j, "High"])
    j = sub["Low"].idxmin()
    return sub.loc[j, "Date"], float(sub.loc[j, "Low"])


def confirmed_pivots_daily(daily: pd.DataFrame, k: int) -> list[Pivot]:
    if len(daily) < 2 * k + 1:
        return []
    high = daily["High"].to_numpy(dtype=float)
    low = daily["Low"].to_numpy(dtype=float)
    dates = list(daily["Date"])
    raw = fractal_pivots(high, low, k=k)
    n = len(daily)
    pivots: list[Pivot] = []
    for kind, i in raw:
        conf_i = i + k
        if conf_i >= n:
            continue
        pivots.append(
            Pivot(
                kind=kind,
                date=dates[i],
                price=float(high[i] if kind == "H" else low[i]),
                tf_bar_idx=i,
                confirmed_on=dates[conf_i],
            )
        )
    return pivots


def confirmed_pivots_htf(daily: pd.DataFrame, rule: str, k: int) -> list[Pivot]:
    htf, members = build_htf(daily, rule)
    if htf.empty or len(htf) < 2 * k + 1:
        return []
    high = htf["High"].to_numpy(dtype=float)
    low = htf["Low"].to_numpy(dtype=float)
    ends = [htf.iloc[i]["end_date"] for i in range(len(htf))]
    raw = fractal_pivots(high, low, k=k)
    n = len(htf)
    pivots: list[Pivot] = []
    for kind, i in raw:
        conf_i = i + k
        if conf_i >= n:
            continue
        d, px = refine_pivot_date(daily, members, kind, i, float(high[i]), float(low[i]))
        pivots.append(
            Pivot(
                kind=kind,
                date=d,
                price=px,
                tf_bar_idx=i,
                confirmed_on=ends[conf_i],
            )
        )
    return pivots


def slope_pct_and_sign(d1: date, p1: float, d2: date, p2: float) -> tuple[float, int]:
    days = (d2 - d1).days
    if days <= 0 or not (math.isfinite(p1) and math.isfinite(p2)) or p1 == 0:
        return 0.0, 0
    slope_per_day = (p2 - p1) / float(days)
    slope_pct = ((p2 / p1) - 1.0) / float(days) * 100.0
    if abs(slope_per_day) < FLAT_EPS:
        return slope_pct, 0
    return slope_pct, (1 if slope_per_day > 0 else -1)


def daily_aggregates_for_symbol(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    """Event-driven: O(days + pivots). Emit one row per day with any active line."""
    piv_d = confirmed_pivots_daily(df, PIVOT_K["daily"])
    piv_w = confirmed_pivots_htf(df, WEEK_FREQ, PIVOT_K["weekly"])
    piv_m = confirmed_pivots_htf(df, MONTH_FREQ, PIVOT_K["monthly"])

    # Per (tf, kind): chronological confirmed pivots + cursor into that list
    series: list[tuple[str, str, list[Pivot]]] = [
        ("daily", "L", [p for p in piv_d if p.kind == "L"]),
        ("daily", "H", [p for p in piv_d if p.kind == "H"]),
        ("weekly", "L", [p for p in piv_w if p.kind == "L"]),
        ("weekly", "H", [p for p in piv_w if p.kind == "H"]),
        ("monthly", "L", [p for p in piv_m if p.kind == "L"]),
        ("monthly", "H", [p for p in piv_m if p.kind == "H"]),
    ]
    cursors = [0] * len(series)
    confirmed: list[list[Pivot]] = [[] for _ in series]
    # Active line state: (slope_pct, sign) or None
    active: list[Optional[tuple[float, int]]] = [None] * len(series)

    dates = list(df["Date"])
    out_dates: list[str] = []
    out_sum: list[float] = []
    out_n: list[int] = []
    out_up: list[int] = []
    out_dn: list[int] = []
    out_fl: list[int] = []

    for as_of in dates:
        for si, (_tf, _kind, pivs) in enumerate(series):
            cur = cursors[si]
            while cur < len(pivs) and pivs[cur].confirmed_on <= as_of:
                confirmed[si].append(pivs[cur])
                cur += 1
            cursors[si] = cur
            conf = confirmed[si]
            if len(conf) < 2:
                active[si] = None
                continue
            a, b = conf[-2], conf[-1]
            if a.date >= b.date:
                active[si] = None
                continue
            active_from = max(a.confirmed_on, b.confirmed_on)
            if active_from > as_of:
                active[si] = None
                continue
            active[si] = slope_pct_and_sign(a.date, a.price, b.date, b.price)

        slope_sum = 0.0
        n_lines = n_up = n_dn = n_fl = 0
        for st in active:
            if st is None:
                continue
            pct, sign = st
            slope_sum += pct
            n_lines += 1
            if sign > 0:
                n_up += 1
            elif sign < 0:
                n_dn += 1
            else:
                n_fl += 1
        if n_lines == 0:
            continue
        out_dates.append(as_of.isoformat())
        out_sum.append(slope_sum)
        out_n.append(n_lines)
        out_up.append(n_up)
        out_dn.append(n_dn)
        out_fl.append(n_fl)

    if not out_dates:
        return pd.DataFrame(
            columns=["date", "symbol", "slope_sum", "n_lines", "n_up", "n_down", "n_flat"]
        )
    return pd.DataFrame(
        {
            "date": out_dates,
            "symbol": sym,
            "slope_sum": out_sum,
            "n_lines": out_n,
            "n_up": out_up,
            "n_down": out_dn,
            "n_flat": out_fl,
        }
    )


def _worker(sym: str) -> tuple[str, Optional[pd.DataFrame], str]:
    try:
        df = load_ohlc(sym)
        if df is None or len(df) < MIN_BARS:
            return sym, None, "missing_or_short"
        agg = daily_aggregates_for_symbol(sym, df)
        if agg.empty:
            return sym, None, "no_lines"
        return sym, agg, "ok"
    except Exception as e:  # noqa: BLE001 — isolate worker failures
        return sym, None, f"error:{type(e).__name__}:{e}"


def build_breadth(sym_daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate line-level and symbol-level breadth by date."""
    g = (
        sym_daily.groupby("date", as_index=False)
        .agg(
            n_symbols=("symbol", "nunique"),
            n_lines=("n_lines", "sum"),
            n_up=("n_up", "sum"),
            n_down=("n_down", "sum"),
            n_flat=("n_flat", "sum"),
            mean_slope_sum=("slope_sum", "mean"),
            median_slope_sum=("slope_sum", "median"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    g["breadth_lines"] = g["n_up"] - g["n_down"]
    g["pct_up_lines"] = np.where(g["n_lines"] > 0, g["n_up"] / g["n_lines"] * 100.0, np.nan)
    g["more_up_lines"] = (g["n_up"] > g["n_down"]).astype(int)
    g["more_down_lines"] = (g["n_down"] > g["n_up"]).astype(int)

    # Symbol-level: sign of that day's slope_sum
    ss = sym_daily.copy()
    ss["sym_up"] = (ss["slope_sum"] > 0).astype(int)
    ss["sym_down"] = (ss["slope_sum"] < 0).astype(int)
    ss["sym_flat"] = (ss["slope_sum"] == 0).astype(int)
    sg = (
        ss.groupby("date", as_index=False)
        .agg(
            n_sym_up=("sym_up", "sum"),
            n_sym_down=("sym_down", "sum"),
            n_sym_flat=("sym_flat", "sum"),
        )
    )
    g = g.merge(sg, on="date", how="left")
    g["breadth_symbols"] = g["n_sym_up"] - g["n_sym_down"]
    g["pct_sym_up"] = np.where(
        g["n_symbols"] > 0, g["n_sym_up"] / g["n_symbols"] * 100.0, np.nan
    )
    g["more_up_symbols"] = (g["n_sym_up"] > g["n_sym_down"]).astype(int)
    g["more_down_symbols"] = (g["n_sym_down"] > g["n_sym_up"]).astype(int)
    return g


def write_baseline(path: Path, stamp: str, n_univ: int, n_used: int, n_missing: int) -> None:
    path.write_text(
        f"""# BASELINE — {stamp}

Research-only full-universe fractal trendline slope aggregates.

## Freeze

| Knob | Value |
|------|-------|
| Universe | `drive/universes/ALL_ohlc_universe.csv` ({n_univ} listed; {n_used} with usable OHLC; {n_missing} skipped) |
| OHLC | `data/newdata/data/{{SYM}}.csv` |
| Algorithm | Fractal last-two swings (match `trendline_slopes_paultwenty.py`) |
| Look-ahead | Confirmed pivots only (`confirmed_on` = end of TF bar i+k) |
| Timeframes (TF) | daily (k=5), weekly W-FRI (k=3), monthly ME (k=2) |
| Sides | support = last two Lows; resistance = last two Highs |

## Outputs (tradeoff)

Full long CSV (every symbol × day × TF × side) is **not** stored — PaulTwenty alone was ~90MB / ~478k rows; full univ would be multi-GB.

Emitted instead (enough for signal + breadth):

- `daily_symbol_slope_sum.csv` — per symbol×day: Σ `slope_pct_per_day` across active TF×side + line UP/DOWN/FLAT counts
- `daily_breadth.csv` — market-wide line and symbol breadth by date
- `symbols_used.csv` / `symbols_skipped.csv`

## Slope definitions

Same as PaulTwenty stamp: `slope_pct_per_day = ((p2/p1)-1)/days*100`; sign from `$/day`.

## Scope

- Not gold. Not DailyRun-wired.
- Research only.
""",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("--universe", type=Path, default=ALL_UNIV)
    ap.add_argument("--workers", type=int, default=max(1, min(24, (os_cpu() or 8))))
    ap.add_argument("--limit", type=int, default=0, help="Debug: first N symbols only")
    args = ap.parse_args()

    out_dir = DRIVE / "paul_experiments" / args.stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir = out_dir / "chunks"
    chunk_dir.mkdir(exist_ok=True)

    symbols = load_universe(args.universe)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]
    print(f"Universe listed: {len(symbols)}  workers={args.workers}", flush=True)

    t0 = time.time()
    used: list[str] = []
    skipped: list[tuple[str, str]] = []
    frames: list[pd.DataFrame] = []
    done = 0

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_worker, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            sym, agg, status = fut.result()
            done += 1
            if status == "ok" and agg is not None:
                used.append(sym)
                frames.append(agg)
                # Incremental chunk every 50 symbols to bound memory
                if len(frames) >= 50:
                    chunk_path = chunk_dir / f"chunk_{len(used):05d}.parquet"
                    pd.concat(frames, ignore_index=True).to_parquet(chunk_path, index=False)
                    frames.clear()
            else:
                skipped.append((sym, status))
            if done % 50 == 0 or done == len(symbols):
                print(
                    f"  progress {done}/{len(symbols)} used={len(used)} "
                    f"elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )

    if frames:
        chunk_path = chunk_dir / f"chunk_{len(used):05d}.parquet"
        pd.concat(frames, ignore_index=True).to_parquet(chunk_path, index=False)
        frames.clear()

    # Concatenate chunks
    chunk_files = sorted(chunk_dir.glob("chunk_*.parquet"))
    if not chunk_files:
        print("No symbol aggregates produced.", file=sys.stderr)
        return 1
    print(f"Concatenating {len(chunk_files)} chunks...", flush=True)
    parts = [pd.read_parquet(p) for p in chunk_files]
    sym_daily = pd.concat(parts, ignore_index=True)
    sym_daily = sym_daily.sort_values(["date", "symbol"]).reset_index(drop=True)

    sum_path = out_dir / "daily_symbol_slope_sum.csv"
    sym_daily.to_csv(sum_path, index=False)
    print(f"Wrote {sum_path} ({len(sym_daily):,} rows)", flush=True)

    # Also parquet for faster downstream reads
    sum_pq = out_dir / "daily_symbol_slope_sum.parquet"
    sym_daily.to_parquet(sum_pq, index=False)

    breadth = build_breadth(sym_daily)
    br_path = out_dir / "daily_breadth.csv"
    breadth.to_csv(br_path, index=False)
    print(f"Wrote {br_path} ({len(breadth):,} days)", flush=True)

    pd.DataFrame({"symbol": sorted(used)}).to_csv(out_dir / "symbols_used.csv", index=False)
    pd.DataFrame(skipped, columns=["symbol", "reason"]).to_csv(
        out_dir / "symbols_skipped.csv", index=False
    )

    write_baseline(
        out_dir / "BASELINE.md",
        args.stamp,
        n_univ=len(load_universe(args.universe)) if not args.limit else len(symbols),
        n_used=len(used),
        n_missing=len(skipped),
    )

    # Quick SUMMARY
    n_days = len(breadth)
    pct_more_up = float(breadth["more_up_lines"].mean() * 100.0) if n_days else float("nan")
    pct_more_dn = float(breadth["more_down_lines"].mean() * 100.0) if n_days else float("nan")
    pct_sym_up = float(breadth["more_up_symbols"].mean() * 100.0) if n_days else float("nan")
    (out_dir / "SUMMARY.md").write_text(
        f"""# SUMMARY — {args.stamp}

- Universe listed: {len(symbols)} (limit={args.limit or 'none'})
- Symbols used: **{len(used)}**
- Skipped: {len(skipped)}
- Symbol×day rows: {len(sym_daily):,}
- Trading days in breadth: {n_days:,}
- Share of days with more UP lines than DOWN: **{pct_more_up:.1f}%**
- Share of days with more DOWN lines than UP: **{pct_more_dn:.1f}%**
- Share of days with more symbols slope_sum>0 than <0: **{pct_sym_up:.1f}%**
- Elapsed: {time.time()-t0:.0f}s
- Tradeoff: full long TF×side CSV not stored (see BASELINE).

Research only.
""",
        encoding="utf-8",
    )

    print(f"Done in {time.time()-t0:.0f}s -> {out_dir}")
    return 0


def os_cpu() -> int:
    try:
        import os

        return int(os.cpu_count() or 8)
    except Exception:
        return 8


if __name__ == "__main__":
    raise SystemExit(main())
