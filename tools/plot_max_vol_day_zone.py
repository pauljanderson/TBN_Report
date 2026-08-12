#!/usr/bin/env python3
"""Plot max-volume day Open/Close zone for a symbol (quick iterable prototype).

Modes:
  single (default): last N bars → one max-vol day → one O–C zone band
  rolling: from lookback onward, each day zones O–C of the trailing-window
           max-vol day; shade only while that day remains the rolling winner

Examples:
  python tools/plot_max_vol_day_zone.py --symbol NVDA
  python tools/plot_max_vol_day_zone.py --symbol NVDA --lookback-days 126
  python tools/plot_max_vol_day_zone.py --symbol NVDA --mode rolling --lookback-days 126
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO / "data" / "newdata" / "data"
DEFAULT_OUT_DIR = REPO / "drive" / "paul_experiments"

# Hybrid candle threshold: full daily if shorter; else weekly older + daily recent
_FULL_DAILY_MAX_BARS = 900
_RECENT_DAILY_BARS = 504  # ~2y trading days kept daily when hybrid


@dataclass(frozen=True)
class Regime:
    """Contiguous period where the same bar is the rolling max-vol winner."""

    max_vol_idx: int  # iloc in full df
    start_t: int  # first day (inclusive) this winner is active
    end_t: int  # last day (inclusive) this winner is active
    zone_low: float
    zone_high: float


def load_ohlcv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
    need = {"Date", "Open", "High", "Low", "Close", "Volume"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"CSV missing columns {sorted(missing)}: {csv_path}")
    return df


def find_max_vol_day(df: pd.DataFrame, lookback_days: int) -> tuple[pd.DataFrame, pd.Series]:
    """Return (window_df, max_vol_row) using last `lookback_days` bars."""
    if len(df) < 1:
        raise SystemExit("Empty OHLC data")
    window = df.tail(lookback_days).copy()
    idx = int(window["Volume"].values.argmax())
    row = window.iloc[idx]
    return window, row


def oc_zone(row: pd.Series) -> tuple[float, float]:
    o = float(row["Open"])
    c = float(row["Close"])
    return min(o, c), max(o, c)


def compute_rolling_regimes(df: pd.DataFrame, lookback_days: int) -> list[Regime]:
    """Walk day-by-day; new regime when identity of trailing max-vol day changes."""
    n = len(df)
    if n <= lookback_days:
        raise SystemExit(
            f"Need more than {lookback_days} bars for rolling mode; got {n}"
        )

    vol = df["Volume"].to_numpy(dtype=np.float64)
    opens = df["Open"].to_numpy(dtype=np.float64)
    closes = df["Close"].to_numpy(dtype=np.float64)

    regimes: list[Regime] = []
    prev_winner: int | None = None
    regime_start: int | None = None

    for t in range(lookback_days - 1, n):
        w0 = t - lookback_days + 1
        # argmax in [w0, t]; on ties take earliest (stable / left)
        winner = w0 + int(np.argmax(vol[w0 : t + 1]))
        if prev_winner is None:
            prev_winner = winner
            regime_start = t
            continue
        if winner != prev_winner:
            assert regime_start is not None
            zl = min(opens[prev_winner], closes[prev_winner])
            zh = max(opens[prev_winner], closes[prev_winner])
            regimes.append(
                Regime(
                    max_vol_idx=prev_winner,
                    start_t=regime_start,
                    end_t=t - 1,
                    zone_low=float(zl),
                    zone_high=float(zh),
                )
            )
            prev_winner = winner
            regime_start = t

    assert prev_winner is not None and regime_start is not None
    zl = min(opens[prev_winner], closes[prev_winner])
    zh = max(opens[prev_winner], closes[prev_winner])
    regimes.append(
        Regime(
            max_vol_idx=prev_winner,
            start_t=regime_start,
            end_t=n - 1,
            zone_low=float(zl),
            zone_high=float(zh),
        )
    )
    return regimes


def _draw_candles(ax, dates, o, h, l, c, lw_wick: float = 0.5, lw_body: float = 1.6) -> None:
    up = c >= o
    ax.vlines(dates, l, h, color="0.35", lw=lw_wick, zorder=2)
    body_lo = np.minimum(o, c)
    body_hi = np.maximum(o, c)
    if np.any(up):
        ax.vlines(dates[up], body_lo[up], body_hi[up], color="#2ca02c", lw=lw_body, zorder=3)
    if np.any(~up):
        ax.vlines(dates[~up], body_lo[~up], body_hi[~up], color="#d62728", lw=lw_body, zorder=3)


def _to_weekly_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.set_index("Date")
        .resample("W-FRI")
        .agg(
            Open=("Open", "first"),
            High=("High", "max"),
            Low=("Low", "min"),
            Close=("Close", "last"),
            Volume=("Volume", "sum"),
        )
        .dropna(subset=["Open", "Close"])
        .reset_index()
    )
    return g


def prepare_plot_bars(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Full daily if short enough; else weekly older + daily recent."""
    if len(df) <= _FULL_DAILY_MAX_BARS:
        return df.copy(), "daily"
    cut = max(0, len(df) - _RECENT_DAILY_BARS)
    older = df.iloc[:cut]
    recent = df.iloc[cut:]
    weekly = _to_weekly_ohlc(older)
    # Avoid duplicate dates at the join
    if len(weekly) and len(recent):
        weekly = weekly[weekly["Date"] < recent["Date"].iloc[0]]
    out = pd.concat([weekly, recent], ignore_index=True)
    return out, f"hybrid weekly(+{len(weekly)}) / daily(+{len(recent)})"


def plot_zone(
    window: pd.DataFrame,
    row: pd.Series,
    symbol: str,
    zone_low: float,
    zone_high: float,
    out_path: Path,
) -> None:
    dates = window["Date"]
    o = window["Open"].to_numpy()
    h = window["High"].to_numpy()
    l = window["Low"].to_numpy()
    c = window["Close"].to_numpy()
    v = window["Volume"].to_numpy()
    up = c >= o

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(14, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.05},
    )

    _draw_candles(ax, dates, o, h, l, c, lw_wick=0.6, lw_body=2.2)

    ax.axhspan(zone_low, zone_high, color="#1f77b4", alpha=0.22, zorder=1, label="O–C zone")
    ax.axhline(zone_low, color="#1f77b4", lw=0.8, alpha=0.7)
    ax.axhline(zone_high, color="#1f77b4", lw=0.8, alpha=0.7)

    max_dt = pd.Timestamp(row["Date"])
    ax.axvline(max_dt, color="#ff7f0e", lw=1.4, ls="--", alpha=0.9, label="Max-vol day")

    vol = int(row["Volume"])
    label = (
        f"{max_dt.date()}  O={float(row['Open']):.2f}  C={float(row['Close']):.2f}\n"
        f"zone [{zone_low:.2f}, {zone_high:.2f}]  vol={vol:,}"
    )
    ax.annotate(
        label,
        xy=(max_dt, zone_high),
        xytext=(12, 24),
        textcoords="offset points",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#ff7f0e", alpha=0.92),
        arrowprops=dict(arrowstyle="->", color="#ff7f0e"),
    )

    ax.set_ylabel("Price")
    ax.set_title(f"{symbol} — max-volume day Open/Close zone (last {len(window)} bars)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.25)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.2f}"))

    colors = ["#2ca02c" if u else "#d62728" for u in up]
    axv.bar(dates, v, color=colors, width=1.0, alpha=0.55, align="center")
    axv.bar([max_dt], [vol], color="#ff7f0e", width=1.2, alpha=0.95, align="center", label="Max vol")
    axv.set_ylabel("Volume")
    axv.grid(True, alpha=0.25)
    axv.legend(loc="upper left", fontsize=8)
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    axv.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_rolling_zones(
    df: pd.DataFrame,
    regimes: list[Regime],
    symbol: str,
    lookback_days: int,
    out_path: Path,
) -> None:
    """Full-history chart; shade O–C zone only while each max-vol day is the rolling winner."""
    plot_df, candle_mode = prepare_plot_bars(df)
    dates = plot_df["Date"]
    o = plot_df["Open"].to_numpy()
    h = plot_df["High"].to_numpy()
    l = plot_df["Low"].to_numpy()
    c = plot_df["Close"].to_numpy()
    v = plot_df["Volume"].to_numpy()

    # Wide figure for long history
    fig_w = max(22.0, min(40.0, 10.0 + len(plot_df) / 80.0))
    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(fig_w, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.06},
    )

    lw_wick = 0.35 if candle_mode != "daily" else 0.55
    lw_body = 1.1 if candle_mode != "daily" else 1.8
    _draw_candles(ax, dates, o, h, l, c, lw_wick=lw_wick, lw_body=lw_body)

    # Active-period zone shading (step regimes)
    cmap = plt.cm.tab20  # type: ignore[attr-defined]
    unique_idxs = sorted({r.max_vol_idx for r in regimes})
    idx_color = {i: cmap(j % 20) for j, i in enumerate(unique_idxs)}

    first_shade = True
    for r in regimes:
        d0 = pd.Timestamp(df["Date"].iloc[r.start_t])
        d1 = pd.Timestamp(df["Date"].iloc[r.end_t])
        # Extend right edge slightly so single-day regimes remain visible
        if d0 == d1:
            d1 = d0 + pd.Timedelta(days=1)
        color = idx_color[r.max_vol_idx]
        # Light time-tint for the active regime span
        ax.axvspan(d0, d1, facecolor=color, alpha=0.05, zorder=0, lw=0)
        # Price-band shade only over dates when this max-vol day was the winner
        end_d = pd.Timestamp(df["Date"].iloc[r.end_t])
        xs = df.loc[(df["Date"] >= d0) & (df["Date"] <= end_d), "Date"]
        if len(xs) == 0:
            continue
        ax.fill_between(
            xs,
            r.zone_low,
            r.zone_high,
            color=color,
            alpha=0.35,
            zorder=1,
            label="Active O–C zone" if first_shade else None,
            linewidth=0,
        )
        first_shade = False

    # Mark each unique max-vol day once
    marked = set()
    first_mark = True
    for r in regimes:
        if r.max_vol_idx in marked:
            continue
        marked.add(r.max_vol_idx)
        max_dt = pd.Timestamp(df["Date"].iloc[r.max_vol_idx])
        ax.axvline(
            max_dt,
            color="#ff7f0e",
            lw=0.9,
            ls="--",
            alpha=0.75,
            zorder=4,
            label="Unique max-vol day" if first_mark else None,
        )
        ax.scatter(
            [max_dt],
            [(r.zone_low + r.zone_high) / 2.0],
            color="#ff7f0e",
            s=28,
            zorder=5,
            edgecolors="white",
            linewidths=0.4,
        )
        first_mark = False

    n_unique = len(unique_idxs)
    n_regimes = len(regimes)
    start_plot = pd.Timestamp(df["Date"].iloc[lookback_days - 1]).date()
    end_plot = pd.Timestamp(df["Date"].iloc[-1]).date()
    ax.set_ylabel("Price")
    ax.set_title(
        f"{symbol} — rolling max-vol day O–C zones "
        f"(lookback={lookback_days} bars; {n_unique} unique max-vol days, "
        f"{n_regimes} regime segments; candles={candle_mode})"
    )
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.25)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.2f}"))
    ax.text(
        0.99,
        0.02,
        f"zones active {start_plot} → {end_plot}",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color="0.35",
    )

    # Volume: use plot_df bars (weekly vol is sum — still informative)
    up = c >= o
    colors = ["#2ca02c" if u else "#d62728" for u in up]
    width = 3.0 if candle_mode != "daily" else 1.0
    axv.bar(dates, v, color=colors, width=width, alpha=0.5, align="center")
    for i in unique_idxs:
        max_dt = pd.Timestamp(df["Date"].iloc[i])
        # Only mark if date appears on volume axis scale (daily source date)
        axv.axvline(max_dt, color="#ff7f0e", lw=0.7, ls="--", alpha=0.7)
    axv.set_ylabel("Volume")
    axv.grid(True, alpha=0.25)
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axv.xaxis.set_major_locator(mdates.YearLocator(base=1))
    fig.autofmt_xdate()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _print_rolling_summary(df: pd.DataFrame, regimes: list[Regime], lookback_days: int) -> None:
    unique_idxs = []
    seen = set()
    for r in regimes:
        if r.max_vol_idx not in seen:
            seen.add(r.max_vol_idx)
            unique_idxs.append(r.max_vol_idx)

    print(
        "DECISION: earliest data -> skip first lookback window -> each subsequent day "
        "zone = O-C of max-vol day in trailing lookback; redraw shading when that winner changes "
        "(active-period only)."
    )
    print(f"bars:           {len(df)}  ({df['Date'].iloc[0].date()} -> {df['Date'].iloc[-1].date()})")
    print(f"lookback:       {lookback_days} trading days")
    print(f"first_zone_t:   {df['Date'].iloc[lookback_days - 1].date()} (index {lookback_days - 1})")
    print(f"unique_maxvol:  {len(unique_idxs)}")
    print(
        f"regime_changes: {len(regimes)} segments  "
        f"({max(0, len(regimes) - 1)} identity changes)"
    )

    def _fmt_regime(r: Regime, tag: str) -> None:
        row = df.iloc[r.max_vol_idx]
        print(
            f"  {tag}: winner={pd.Timestamp(row['Date']).date()} "
            f"vol={int(row['Volume']):,}  zone=[{r.zone_low:.4f},{r.zone_high:.4f}]  "
            f"active={df['Date'].iloc[r.start_t].date()}->{df['Date'].iloc[r.end_t].date()}  "
            f"({r.end_t - r.start_t + 1}d)"
        )

    show = min(5, len(regimes))
    print(f"first {show} regimes:")
    for i in range(show):
        _fmt_regime(regimes[i], f"#{i + 1}")
    if len(regimes) > show:
        print(f"last {show} regimes:")
        for i in range(len(regimes) - show, len(regimes)):
            _fmt_regime(regimes[i], f"#{i + 1}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot max-volume day O/C zone")
    ap.add_argument("--symbol", default="NVDA")
    ap.add_argument(
        "--mode",
        choices=("single", "rolling"),
        default="single",
        help="single=last-window zone (default); rolling=step zones over full history",
    )
    ap.add_argument(
        "--lookback-days",
        type=int,
        default=126,
        help="Trailing trading-day window for max-vol (default 126 ≈ 6 months)",
    )
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output PNG path",
    )
    args = ap.parse_args()

    sym = args.symbol.strip().upper()
    csv_path = args.data_dir / f"{sym}.csv"
    if not csv_path.is_file():
        raise SystemExit(f"Missing CSV: {csv_path}")

    df = load_ohlcv(csv_path)

    if args.mode == "rolling":
        regimes = compute_rolling_regimes(df, args.lookback_days)
        out_path = args.out or (DEFAULT_OUT_DIR / f"MaxVolDay_Zone_{sym}_rolling.png")
        plot_rolling_zones(df, regimes, sym, args.lookback_days, out_path)
        _print_rolling_summary(df, regimes, args.lookback_days)
        print(f"saved:          {out_path}")
        return

    window, row = find_max_vol_day(df, args.lookback_days)
    zone_low, zone_high = oc_zone(row)
    vol = int(row["Volume"])
    max_date = pd.Timestamp(row["Date"]).date()

    out_path = args.out or (DEFAULT_OUT_DIR / f"MaxVolDay_Zone_{sym}.png")
    plot_zone(window, row, sym, zone_low, zone_high, out_path)

    print(f"symbol:     {sym}")
    print(
        f"lookback:   {args.lookback_days} bars "
        f"(window {window['Date'].iloc[0].date()} -> {window['Date'].iloc[-1].date()})"
    )
    print(f"max_vol_dt: {max_date}")
    print(f"Open:       {float(row['Open']):.4f}")
    print(f"Close:      {float(row['Close']):.4f}")
    print(f"zone_low:   {zone_low:.4f}")
    print(f"zone_high:  {zone_high:.4f}")
    print(f"volume:     {vol:,}")
    print(f"saved:      {out_path}")


if __name__ == "__main__":
    main()
