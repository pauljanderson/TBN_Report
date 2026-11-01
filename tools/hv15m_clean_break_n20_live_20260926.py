#!/usr/bin/env python3
"""Live watch: clean break of the highest zone, 20-day memory.

As of the last bar in the 1-minute store, list symbols whose latest
15-minute bar is a first clean break of the highest still-active zone.
The fill is the next 15-minute open, which is not in the tape yet.
Zone source matches the preferred look: skip the 15:45 close bar when
picking each day's busiest candle. Stop is that zone's low.

Research scan only. Not gold. Not DailyRun. Not the daily Volume Zone.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import hv15m_day_zone_forward_20260925 as base  # noqa: E402
from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_clean_break_n20_live_20260926"
CACHE = STAMP / "cache_15m.parquet"
CHARTS = STAMP / "charts"
ONE_MIN = ROOT / "data" / "intraday" / "1m"
N = 20
NEXT_OPEN = "Monday, September 28, 2026, 9:30am Eastern Time"

ORIGINAL_REQUEST = (
    "lets take this Clean break of the highest zone Nd use 20 day history. "
    "show a report of all the stocks that have a current trigger signaling a buy "
    "at next open. i want to see 20 day charts with 15 minute bars and the "
    "zones drawn with the stop loss called out of zone low."
)


def _bkt_label(bucket: int) -> str:
    return base._bkt_label(int(bucket))


def _px(x: float) -> str:
    if not np.isfinite(x):
        return "—"
    ax = abs(float(x))
    if ax >= 1000:
        return f"{x:,.2f}"
    if ax >= 1:
        return f"{x:.2f}"
    return f"{x:.4f}"


def build_15m(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Fresh 15-minute bars. The parent study cache stops before this evening's tape."""
    print("resampling 1-minute to 15-minute regular-hours bars...", flush=True)
    glob = (ONE_MIN / "*.parquet").as_posix()
    df = con.execute(
        f"""
        WITH src AS (
            SELECT
                upper(symbol) AS symbol,
                timezone('America/New_York', ts) AS ts_et,
                open, high, low, close, volume
            FROM read_parquet('{glob}')
            WHERE volume IS NOT NULL AND volume > 0
              AND open IS NOT NULL AND high IS NOT NULL
              AND low IS NOT NULL AND close IS NOT NULL
        ),
        f AS (
            SELECT
                symbol,
                CAST(ts_et AS DATE) AS day,
                (hour(ts_et) * 60 + minute(ts_et)) AS mins,
                ts_et, open, high, low, close, volume
            FROM src
        )
        SELECT
            symbol,
            day,
            ((mins - 570) // 15)::INTEGER AS bucket,
            arg_min(open, ts_et) AS open,
            max(high) AS high,
            min(low) AS low,
            arg_max(close, ts_et) AS close,
            sum(volume) AS volume,
            count(*)::INTEGER AS n_min
        FROM f
        WHERE mins >= 570 AND mins < 960
        GROUP BY symbol, day, bucket
        HAVING count(*) >= 10
           AND max(high) > min(low)
           AND sum(volume) > 0
        ORDER BY symbol, day, bucket
        """
    ).fetchdf()
    STAMP.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE, index=False)
    print(f"15m rows {len(df):,} symbols {df['symbol'].nunique():,}", flush=True)
    return df


def _elect_zones(day, bucket, low, high, vol, sess, good_days):
    s_count = len(good_days)
    z_lo = np.full(s_count, np.nan)
    z_hi = np.full(s_count, np.nan)
    z_bkt = np.full(s_count, -1, dtype=np.int16)
    z_bar = np.full(s_count, -1, dtype=np.int32)
    for s, d in enumerate(good_days):
        idx = np.flatnonzero((day == d) & (sess == s))
        idx = idx[bucket[idx] < 25]
        if len(idx) == 0:
            continue
        vols = vol[idx]
        bk = bucket[idx]
        best = idx[int(np.lexsort((bk, -vols))[0])]
        lo = float(low[best])
        hi = float(high[best])
        mid = 0.5 * (lo + hi)
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo or mid <= 0:
            continue
        if (hi - lo) / mid < 0.0005:
            continue
        z_lo[s] = lo
        z_hi[s] = hi
        z_bkt[s] = int(bucket[best])
        z_bar[s] = int(best)
    valid = np.isfinite(z_lo) & np.isfinite(z_hi) & (z_bkt >= 0)
    return z_lo, z_hi, z_bkt, z_bar, valid


def _highest(z_hi, valid, s, b, z_bkt, n_carry: int):
    s0 = s - n_carry
    if s0 < 0:
        s0 = 0
    hi_z = -1
    best_hi = -1e300
    for zs in range(s0, s + 1):
        if not valid[zs]:
            continue
        if (s - zs) > n_carry:
            continue
        if zs == s and b <= int(z_bkt[zs]):
            continue
        zh = float(z_hi[zs])
        if zh > best_hi or (zh == best_hi and zs > hi_z):
            best_hi = zh
            hi_z = zs
    return hi_z


def scan_pending(sym: str, g: pd.DataFrame, asof_day, asof_bucket: int) -> dict | None:
    g = g.sort_values(["day", "bucket"])
    day = pd.to_datetime(g["day"]).to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    o = g["open"].to_numpy(dtype=np.float64)
    h = g["high"].to_numpy(dtype=np.float64)
    low = g["low"].to_numpy(dtype=np.float64)
    c = g["close"].to_numpy(dtype=np.float64)
    v = g["volume"].to_numpy(dtype=np.float64)
    n = len(c)
    if n < 30:
        return None
    last = n - 1
    last_day = pd.Timestamp(day[last]).date()
    if last_day != asof_day or int(bucket[last]) != asof_bucket:
        return None

    uniq = pd.unique(day)
    counts = pd.Series(day).value_counts()
    good_days = [d for d in uniq if int(counts.get(d, 0)) >= base.MIN_BARS_SESSION]
    if len(good_days) < base.MIN_SESSIONS:
        return None
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    z_lo, z_hi, z_bkt, z_bar, valid = _elect_zones(day, bucket, low, h, v, sess, good_days)
    if not np.any(valid):
        return None

    clean_done = np.zeros(len(good_days), dtype=np.int8)
    hit_z = -1
    for j in range(n):
        s = int(sess[j])
        if s < 0 or j == 0 or int(sess[j - 1]) < 0:
            continue
        b = int(bucket[j])
        hi_z = _highest(z_hi, valid, s, b, z_bkt, N)
        if hi_z < 0 or clean_done[hi_z] != 0:
            continue
        zh = float(z_hi[hi_z])
        if low[j] > zh and c[j] > zh and c[j - 1] <= zh:
            clean_done[hi_z] = 1
            if j == last:
                hit_z = hi_z
    if hit_z < 0:
        return None

    s_last = int(sess[last])
    zones = []
    s0 = max(0, s_last - N)
    for zs in range(s0, s_last + 1):
        if not valid[zs]:
            continue
        if (s_last - zs) > N:
            continue
        if zs == s_last and int(bucket[last]) <= int(z_bkt[zs]):
            continue
        birth = pd.Timestamp(good_days[zs]).date().isoformat()
        zones.append(
            {
                "session": zs,
                "day": birth,
                "bucket": int(z_bkt[zs]),
                "clock": _bkt_label(int(z_bkt[zs])),
                "lo": float(z_lo[zs]),
                "hi": float(z_hi[zs]),
                "bar": int(z_bar[zs]),
                "trigger": zs == hit_z,
            }
        )

    stop = float(z_lo[hit_z])
    zhigh = float(z_hi[hit_z])
    last_c = float(c[last])
    risk = (last_c - stop) / last_c if last_c > 0 else float("nan")
    mid = 0.5 * (stop + zhigh)
    width = (zhigh - stop) / mid if mid > 0 else float("nan")
    born = pd.Timestamp(good_days[hit_z]).date()
    age = s_last - hit_z
    window_days = [pd.Timestamp(d).date() for d in uniq if pd.Timestamp(d).date() <= last_day]
    window_days = window_days[-N:]
    bars = g[pd.to_datetime(g["day"]).dt.date.isin(set(window_days))].copy()
    return {
        "symbol": sym,
        "signal_day": last_day.isoformat(),
        "signal_clock": _bkt_label(int(bucket[last])),
        "signal_bucket": int(bucket[last]),
        "open": float(o[last]),
        "high": float(h[last]),
        "low": float(low[last]),
        "close": last_c,
        "prior_close": float(c[last - 1]),
        "stop": stop,
        "zone_hi": zhigh,
        "zone_day": born.isoformat(),
        "zone_clock": _bkt_label(int(z_bkt[hit_z])),
        "zone_age_sessions": int(age),
        "risk_vs_close": float(risk),
        "zone_width": float(width),
        "zones": zones,
        "bars": bars,
    }


def _plot(hit: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    bars = hit["bars"].sort_values(["day", "bucket"])
    o = bars["open"].to_numpy(dtype=float)
    h = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    c = bars["close"].to_numpy(dtype=float)
    days = pd.to_datetime(bars["day"]).dt.date.to_numpy()
    buckets = bars["bucket"].to_numpy(dtype=int)
    n = len(c)
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(22, 8), dpi=110)
    for i in range(n):
        up = c[i] >= o[i]
        color = "#1b7f4e" if up else "#c0392b"
        ax.plot([x[i], x[i]], [low[i], h[i]], color=color, linewidth=0.6, solid_capstyle="butt")
        body_lo = min(o[i], c[i])
        body_hi = max(o[i], c[i])
        if body_hi - body_lo < max(abs(c[i]) * 1e-5, 1e-4):
            body_hi = body_lo + max(abs(c[i]) * 1e-4, 1e-4)
        ax.add_patch(
            Rectangle(
                (x[i] - 0.32, body_lo),
                0.64,
                body_hi - body_lo,
                facecolor=color,
                edgecolor=color,
                linewidth=0.4,
                zorder=3,
            )
        )

    day_keys = [pd.Timestamp(d).date() for d in days]
    day_starts = [0]
    for i in range(1, n):
        if day_keys[i] != day_keys[i - 1]:
            day_starts.append(i)
            ax.axvline(i - 0.5, color="#d0d5dd", linewidth=0.6, zorder=0)
    ax.set_xticks(day_starts)
    ax.set_xticklabels([day_keys[i].isoformat()[5:] for i in day_starts], rotation=45, ha="right", fontsize=8)
    ax.set_xlim(-1, n + 8)

    pos = {(day_keys[i], int(buckets[i])): i for i in range(n)}
    for z in hit["zones"]:
        key_day = pd.Timestamp(z["day"]).date()
        born_i = pos.get((key_day, int(z["bucket"])))
        xi = 0 if born_i is None else born_i
        color = "#e67e22" if z["trigger"] else "#94a3b8"
        if z["trigger"]:
            ax.axhspan(z["lo"], z["hi"], facecolor=color, alpha=0.22, zorder=1)
        ax.plot([xi, n - 1], [z["hi"], z["hi"]], color=color, linewidth=1.3 if z["trigger"] else 0.7, alpha=0.95, zorder=2)
        ax.plot([xi, n - 1], [z["lo"], z["lo"]], color=color, linewidth=1.3 if z["trigger"] else 0.7, alpha=0.95, zorder=2)
        if born_i is not None:
            ax.scatter(
                [born_i],
                [(z["lo"] + z["hi"]) / 2.0],
                s=36 if z["trigger"] else 14,
                color=color,
                zorder=4,
                marker="s",
            )

    stop = float(hit["stop"])
    zhigh = float(hit["zone_hi"])
    ax.axhline(stop, color="#b00020", linestyle="--", linewidth=1.6, zorder=5)
    ax.axhline(zhigh, color="#1a5276", linestyle=":", linewidth=1.2, zorder=5)

    sig_i = n - 1
    ax.axvline(sig_i, color="#6c3483", linewidth=1.0, alpha=0.85, zorder=4)
    ax.annotate(
        "trigger\nbuy next open",
        xy=(sig_i, float(hit["high"])),
        xytext=(-36, 14),
        textcoords="offset points",
        ha="right",
        fontsize=8,
        color="#6c3483",
        fontweight="bold",
        arrowprops={"arrowstyle": "->", "color": "#6c3483", "lw": 0.8},
    )
    box = (
        f"STOP  zone low   {_px(stop)}\n"
        f"zone high        {_px(zhigh)}\n"
        f"last close       {_px(float(hit['close']))}\n"
        f"buy next open    Mon 9/28 9:30 ET"
    )
    ax.text(
        0.012,
        0.98,
        box,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=10,
        fontweight="medium",
        color="#7f1d1d",
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#fff5f5", "edgecolor": "#b00020", "linewidth": 1.2},
        zorder=6,
        family="monospace",
    )

    lows = [float(np.nanmin(low)), stop]
    highs = [float(np.nanmax(h)), zhigh]
    pad = (max(highs) - min(lows)) * 0.06
    if pad <= 0:
        pad = max(abs(stop) * 0.01, 0.05)
    ax.set_ylim(min(lows) - pad, max(highs) + pad)
    ax.set_ylabel("Price")
    ax.set_title(
        f"{hit['symbol']}   clean break of the highest zone   "
        f"stop = zone low {_px(stop)}   zone born {hit['zone_day']} {hit['zone_clock']}",
        loc="left",
        fontsize=12,
    )
    note = (
        f"15-minute bars, regular hours, last {N} sessions. Gaps between sessions removed. "
        f"Orange band is the zone that broke. Gray lines are the other zones still in the 20-day memory. "
        f"Squares mark the busy candle that set each zone."
    )
    fig.text(0.01, 0.01, note, fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.03, 0.90, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def _risk_note(risk: float) -> str:
    if not np.isfinite(risk):
        return ""
    if risk < base.ZONE_R_MIN:
        return "tighter than 0.10% of the last close"
    if risk > base.ZONE_R_MAX:
        return "wider than 8% of the last close"
    return ""


def write_report(hits: list[dict], info: dict, asof_day, asof_bucket: int, scanned: int) -> None:
    rows = []
    for h in sorted(hits, key=lambda r: r["symbol"]):
        rel = f"charts/{h['symbol']}.png"
        note = _risk_note(h["risk_vs_close"])
        risk_txt = f"{h['risk_vs_close'] * 100:.2f}%"
        rows.append(
            "<tr>"
            f"<td><a href='#{html.escape(h['symbol'])}'>{html.escape(h['symbol'])}</a></td>"
            f"<td>{html.escape(h['signal_day'])} {html.escape(h['signal_clock'])}</td>"
            f"<td>{_px(h['close'])}</td>"
            f"<td>{_px(h['zone_hi'])}</td>"
            f"<td>{_px(h['stop'])}</td>"
            f"<td>{risk_txt}</td>"
            f"<td>{html.escape(h['zone_day'])} {html.escape(h['zone_clock'])}</td>"
            f"<td>{h['zone_age_sessions']}</td>"
            f"<td>{h['zone_width'] * 100:.2f}%</td>"
            f"<td>{html.escape(note) if note else '—'}</td>"
            f"<td><a href='{rel}'>chart</a></td>"
            "</tr>"
        )
    body = "\n".join(rows) if rows else "<tr><td colspan='11'>No symbol is waiting on the next open.</td></tr>"
    charts = []
    for h in sorted(hits, key=lambda r: r["symbol"]):
        rel = f"charts/{h['symbol']}.png"
        charts.append(
            f"<h3 id='{html.escape(h['symbol'])}'>{html.escape(h['symbol'])}</h3>"
            f"<p>Last close {_px(h['close'])}. Zone high {_px(h['zone_hi'])}. "
            f"<strong>Stop (zone low) {_px(h['stop'])}</strong>. "
            f"Zone born {html.escape(h['zone_day'])} at {html.escape(h['zone_clock'])} Eastern Time, "
            f"{h['zone_age_sessions']} sessions earlier. "
            f"Distance from Friday’s close down to the stop is {h['risk_vs_close'] * 100:.2f}% of that close. "
            f"The buy price is Monday’s open, which is not in this tape.</p>"
            f"<img src='{rel}' alt='{html.escape(h['symbol'])} 20-day 15-minute chart' loading='lazy'/>"
        )
    chart_html = "\n".join(charts) if charts else "<p>No charts, because no name has this trigger on the last bar.</p>"
    n_hits = len(hits)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Clean break, 20-day — buy next open</title>
<style>
body {{ font-family: Segoe UI, Helvetica, Arial, sans-serif; margin: 24px; color: #1e293b; max-width: 1200px; }}
h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0 28px; font-size: 0.92rem; }}
th, td {{ border-bottom: 1px solid #e2e8f0; padding: 6px 8px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin-bottom: 6px; }}
img {{ max-width: 100%; height: auto; border: 1px solid #e2e8f0; margin-bottom: 28px; }}
.callout {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin: 14px 0; }}
.callout.plain {{ background: #f0fdf4; border-color: #bbf7d0; }}
.note {{ color: #475569; font-size: 0.92rem; }}
code {{ background: #f1f5f9; padding: 0 4px; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Clean break of the highest zone — names waiting to buy the next open</h1>
<p class="note">Research watch only. Not gold. Not wired into DailyRun. Not the daily Volume Zone system. As of the last bar in the 1-minute store: {html.escape(str(asof_day))} {_bkt_label(asof_bucket)} Eastern Time. Click a symbol to jump to its chart. Click column headers to sort.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ORIGINAL_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>Each day we draw a price band from the low to the high of that day’s busiest 15-minute candle, skipping the last candle of the day (the one that starts at 3:45pm), because the closing auction often makes that candle the busiest. We remember those bands for 20 trading days. A buy signal is the first later 15-minute candle that sits entirely above the highest of those bands, when the candle before it had not already closed above that band. The buy itself is the next 15-minute bar’s open. The stop is the low of the band that just broke.</p>
<p>This tape ends Friday, September 25, 2026, on the 3:45pm Eastern Time candle. The next open is not in the file. It would be {html.escape(NEXT_OPEN)}. A stock is on this page only when that Friday 3:45pm candle is the signal. If the break happened earlier on Friday, the next 15-minute open already came and went, so that name is not waiting.</p>
<p>The charts cover the last 20 trading sessions of 15-minute bars during regular hours (9:30am to 4:00pm Eastern Time). The orange band is the zone price just cleared. The red dashed line is the stop, at that zone’s low. Gray lines are the other zones still inside the 20-day memory. We do not have Monday’s open, so the “distance vs last close” column measures from Friday’s close down to the stop. That is a preview, not the filled trade.</p>
</div>

<h2>Who is on the list</h2>
<p>{n_hits} symbol{"s" if n_hits != 1 else ""} of {scanned:,} scanned. The scan used the same liquid list as the earlier study: at least {info["min_sessions"]} full sessions, median session dollar volume at least ${info["min_median_session_dollar_vol"]:,.0f}, and a median price of at least ${info["min_price"]:.0f}. Tape dates {html.escape(info["date_min"])} through {html.escape(info["date_max"])}, {info["symbols_liquid"]:,} symbols after that screen.</p>
<table class="sortable">
<caption>Pending buy at the next 15-minute open. Stop is the broken zone’s low. Click column headers to sort.</caption>
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Signal bar (ET)", "text")}
{sortable_th("Last close", "num")}
{sortable_th("Zone high", "num")}
{sortable_th("Stop (zone low)", "num")}
{sortable_th("Distance vs last close", "num")}
{sortable_th("Zone born (ET)", "text")}
{sortable_th("Sessions since zone", "num")}
{sortable_th("Zone width", "num")}
{sortable_th("Note", "text")}
{sortable_th("Chart", "text")}
</tr></thead>
<tbody>
{body}
</tbody>
</table>
<p class="note">A distance tighter than 0.10% or wider than 8% of price was left out of the risk score on the earlier study. Those names still appear here if the signal itself fired. The note column flags that case. Eastern Time is the clock on the bars.</p>

<h2>Charts</h2>
{chart_html}

<h2>Freeze for this page</h2>
<ul>
<li>Buy: first 15-minute bar whose low and close are both above the highest active zone high, and whose prior close was not above that high. Fill would be the next regular-hours 15-minute open ({html.escape(NEXT_OPEN)}).</li>
<li>Zone source: highest-volume 15-minute bar that starts before 3:45pm. Ties go to the earlier bar.</li>
<li>Memory: 20 trading sessions. The current day’s zone counts only after its own candle has closed.</li>
<li>Stop drawn: the low of the zone that the signal bar cleared.</li>
<li>This page does not score a result. The next open has not printed.</li>
</ul>
</body>
{SORTABLE_TABLE_SCRIPT}
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")
    baseline = f"""# Clean break, 20-day live watch

Study id: `hv15m_clean_break_n20_live_20260926`

Parent: `hv15m_clean_break_nmax_exit_20260926` and `hv15m_day_zone_forward_20260925`. Research only. Not gold. Not DailyRun. Not the daily Volume Zone (VZ) system.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

A buy signal is the first 15-minute candle that sits entirely above the highest high-volume zone from the last 20 trading days. The day’s busiest candle is chosen after skipping the 3:45pm bar. The fill is the next 15-minute open. The stop is that zone’s low.

The tape ends Friday, September 25, 2026, at the 3:45pm Eastern Time candle. The next open is {NEXT_OPEN}, and it is not in the file. This page lists only names whose Friday 3:45pm candle is that first clean break.

## Freeze

- Pattern: clean break of the highest zone. Zone source: exclude the 15:45 bar.
- Carry: 20 trading sessions.
- Entry: next regular-hours 15-minute open. Not filled on this page.
- Stop shown: zone low of the broken zone.
- Universe: same liquidity screen as the parent study ({info["symbols_liquid"]} symbols, {info["date_min"]} through {info["date_max"]}).
- Names waiting: {n_hits} of {scanned} scanned. As-of bar: {asof_day} {_bkt_label(asof_bucket)} Eastern Time.

## Result

See `compare.html`. No expectancy is claimed. The next open has not printed.
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    df = build_15m(con)
    liquid, info = base.select_universe(df)
    asof_day = pd.to_datetime(liquid["day"]).max().date()
    last_rows = liquid[pd.to_datetime(liquid["day"]).dt.date == asof_day]
    asof_bucket = int(last_rows["bucket"].max()) if len(last_rows) else -1
    print(f"as-of {asof_day} bucket {asof_bucket} ({_bkt_label(asof_bucket)})", flush=True)

    hits = []
    scanned = 0
    grouped = {sym: g for sym, g in liquid.groupby("symbol", sort=False)}
    symbols = list(grouped)
    for i, sym in enumerate(symbols, 1):
        g = grouped[sym]
        scanned += 1
        hit = scan_pending(sym, g, asof_day, asof_bucket)
        if hit is not None:
            hits.append(hit)
            print(
                f"  HIT {sym} close={hit['close']:.2f} stop={hit['stop']:.2f} zone={hit['zone_day']} {hit['zone_clock']}",
                flush=True,
            )
        if i % 100 == 0 or i == len(symbols):
            print(f"  scanned {i}/{len(symbols)} hits {len(hits)}", flush=True)

    CHARTS.mkdir(parents=True, exist_ok=True)
    for old in CHARTS.glob("*.png"):
        old.unlink()
    for hit in hits:
        _plot(hit, CHARTS / f"{hit['symbol']}.png")
        print(f"chart {hit['symbol']}", flush=True)

    table = [
        {
            "symbol": h["symbol"],
            "signal_day": h["signal_day"],
            "signal_clock": h["signal_clock"],
            "close": h["close"],
            "zone_hi": h["zone_hi"],
            "stop": h["stop"],
            "risk_vs_close": h["risk_vs_close"],
            "zone_day": h["zone_day"],
            "zone_clock": h["zone_clock"],
            "zone_age_sessions": h["zone_age_sessions"],
            "zone_width": h["zone_width"],
        }
        for h in hits
    ]
    pd.DataFrame(table).to_csv(STAMP / "signals.csv", index=False)
    write_report(hits, info, asof_day, asof_bucket, scanned)
    print(f"wrote {STAMP / 'compare.html'} hits={len(hits)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
