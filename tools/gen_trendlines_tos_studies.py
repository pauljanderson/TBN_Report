#!/usr/bin/env python3
"""Generate Thinkorswim (ToS) studies with M/W/D swing trendlines + chart overlays.

Computes objective fractal-swing trendlines offline from OHLC (Python), then
emits frozen two-point plot segments in ThinkScript for overlay on a **Daily**
chart, plus the same house overlays used on HTML trendline charts:

- SMA20 / SMA50 / SMA100 (native ``Average(close, N)``)
- House Vol Zone (VZ) HL: current 126d rolling max-volume winner + nearest HL
  above/below last close (``tools/vol_zone_break_retest.build_zones``)
- Light VZ OC band for the current winner day (context only)
- HV6m volume-day High/Low box

Wired by DailyRun step 13d via ``run_trendlines_tos_daily.bat``.

Examples:
  python tools/gen_trendlines_tos_studies.py
  python tools/gen_trendlines_tos_studies.py --symbols NVDA,AU,BTC
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from vol_zone_break_retest import Zone, build_zones  # noqa: E402

DEFAULT_DATA = _REPO / "data" / "newdata" / "data"
DEFAULT_STAMP = "trendlines_mw_d_20260827"
DEFAULT_STAMP_DIR = _REPO / "drive" / "paul_studies" / DEFAULT_STAMP

# Fractal half-window (bars each side) by timeframe
PIVOT_K = {"daily": 5, "weekly": 3, "monthly": 2}

# Colors (RGB) — monthly / weekly / daily
TF_RGB = {
    "monthly": (186, 104, 200),  # violet
    "weekly": (255, 152, 0),  # orange
    "daily": (0, 188, 212),  # cyan
}
TF_LABEL = {"monthly": "M", "weekly": "W", "daily": "D"}

# Highest-volume day in last 6 calendar months (HV6m box) — muted gold/amber
HV6M_RGB = (212, 168, 75)
HV6M_MONTHS = 6

# House VZ HL lookback + chart-matched overlay colors (gen_trendlines_charts_html)
VZ_LOOKBACK_DAYS = 126
VZ_HL_RGB = (126, 87, 194)  # #7e57c2 purple — current winner HL
VZ_OC_RGB = (66, 165, 245)  # #42a5f5 light blue — same-day OC context
VZ_ABOVE_RGB = (198, 40, 40)  # #c62828 nearest HL above
VZ_BELOW_RGB = (46, 125, 50)  # #2e7d32 nearest HL below
SMA_RGB = {
    20: (236, 64, 122),  # #ec407a pink
    50: (239, 108, 0),  # #ef6c00 orange
    100: (109, 76, 65),  # #6d4c41 brown
}
SMA_PERIODS = (20, 50, 100)

# BTC: Yahoo for data; ToS chart naming is documented separately
BTC_YAHOO = "BTC-USD"
BTC_TOS_PREFERRED = "BTCUSD"
BTC_TOS_ALT = "/BTC"

_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


@dataclass(frozen=True)
class Pivot:
    kind: str  # "H" or "L"
    date: date
    price: float
    tf_bar_idx: int


@dataclass(frozen=True)
class TrendLineSeg:
    timeframe: str  # daily | weekly | monthly
    side: str  # support | resistance
    d1: date
    p1: float
    d2: date
    p2: float
    extend_right: bool = True


@dataclass(frozen=True)
class HV6mBox:
    """Highest-volume daily bar in the trailing 6 calendar months."""

    day: date
    high: float
    low: float
    volume: float
    window_start: date
    window_end: date


@dataclass(frozen=True)
class VzHlBand:
    """Frozen house VZ HL (or OC) band for ThinkScript AddCloud."""

    kind: str  # HL | OC
    role: str  # current | above | below
    day: date
    high: float
    low: float
    volume: float


@dataclass(frozen=True)
class VzOverlayPack:
    """Chart-matched VZ overlays: current winner + nearest above/below."""

    current_hl: VzHlBand | None = None
    current_oc: VzHlBand | None = None
    nearest_above: VzHlBand | None = None
    nearest_below: VzHlBand | None = None
    last_close: float | None = None
    n_hl_zones: int = 0


def _fmt_px(px: float) -> str:
    text = f"{float(px):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _ymd(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def load_equity_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").drop_duplicates("Date", keep="last")
    df = df.set_index("Date")
    for col in ("Open", "High", "Low", "Close"):
        if col not in df.columns:
            raise ValueError(f"{path}: missing {col}")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df


def find_hv6m_box(daily: pd.DataFrame, *, months: int = HV6M_MONTHS) -> HV6mBox | None:
    """Pick the single max-Volume day in the last `months` calendar months.

    Window ends at the last available OHLC bar date. Ties → most recent day.
    """
    if daily.empty or "Volume" not in daily.columns:
        return None
    end_ts = pd.Timestamp(daily.index[-1]).normalize()
    start_ts = (end_ts - pd.DateOffset(months=int(months))).normalize()
    # Inclusive of bars on/after start_ts through end_ts
    win = daily.loc[(daily.index >= start_ts) & (daily.index <= end_ts)].copy()
    win = win.dropna(subset=["Volume", "High", "Low"])
    if win.empty:
        return None
    # Max volume; on ties take the last (most recent) row
    vol = win["Volume"].to_numpy(dtype=float)
    max_vol = float(np.nanmax(vol))
    if not np.isfinite(max_vol) or max_vol <= 0:
        return None
    candidates = win[win["Volume"] >= max_vol - 1e-9]
    row = candidates.iloc[-1]
    day_ts = pd.Timestamp(candidates.index[-1])
    return HV6mBox(
        day=day_ts.date(),
        high=float(row["High"]),
        low=float(row["Low"]),
        volume=float(row["Volume"]),
        window_start=start_ts.date(),
        window_end=end_ts.date(),
    )


def _daily_to_zone_frame(daily: pd.DataFrame) -> pd.DataFrame:
    """Date-indexed OHLC → reset frame with Date column for build_zones."""
    df = daily.reset_index()
    if "Date" not in df.columns:
        raise ValueError("daily frame needs a Date index or column for VZ zones")
    return df


def _zone_to_band(z: Zone, role: str) -> VzHlBand:
    return VzHlBand(
        kind=str(z.kind),
        role=role,
        day=pd.Timestamp(z.max_vol_date).date(),
        high=float(z.hi),
        low=float(z.lo),
        volume=float(z.volume),
    )


def nearest_hl_zones(zones: list[Zone], price: float) -> tuple[Zone | None, Zone | None]:
    """Nearest mature VZ HL zone above/below *price* (same as chart generator)."""
    hl = [z for z in zones if z.kind == "HL"]
    above = [z for z in hl if z.lo > price]
    below = [z for z in hl if z.hi < price]
    nearest_above = min(above, key=lambda z: z.lo - price) if above else None
    nearest_below = max(below, key=lambda z: z.hi) if below else None
    return nearest_above, nearest_below


def current_vz_zones(df: pd.DataFrame, lookback: int = VZ_LOOKBACK_DAYS) -> dict[str, Zone | None]:
    """Return current rolling-winner HL (house) and matching OC if present."""
    out: dict[str, Zone | None] = {"HL": None, "OC": None}
    if len(df) <= lookback:
        return out
    zones = build_zones(df, lookback)
    last_i = len(df) - 1
    active = [z for z in zones if z.last_winner_idx == last_i]
    if not active:
        by_kind: dict[str, list[Zone]] = {"HL": [], "OC": []}
        for z in zones:
            by_kind.setdefault(z.kind, []).append(z)
        for k in ("HL", "OC"):
            if by_kind[k]:
                out[k] = by_kind[k][-1]
        return out
    for z in active:
        out[z.kind] = z
    return out


def find_vz_overlays(daily: pd.DataFrame, *, lookback: int = VZ_LOOKBACK_DAYS) -> VzOverlayPack:
    """Compute chart-matched VZ HL overlays from house build_zones."""
    if daily.empty or "Volume" not in daily.columns or len(daily) <= lookback:
        return VzOverlayPack()
    dfz = _daily_to_zone_frame(daily)
    try:
        zones = build_zones(dfz, lookback)
    except ValueError:
        return VzOverlayPack()
    last_close = float(daily["Close"].iloc[-1])
    cur = current_vz_zones(dfz, lookback)
    above, below = nearest_hl_zones(zones, last_close)
    return VzOverlayPack(
        current_hl=_zone_to_band(cur["HL"], "current") if cur.get("HL") else None,
        current_oc=_zone_to_band(cur["OC"], "current") if cur.get("OC") else None,
        nearest_above=_zone_to_band(above, "above") if above else None,
        nearest_below=_zone_to_band(below, "below") if below else None,
        last_close=last_close,
        n_hl_zones=sum(1 for z in zones if z.kind == "HL"),
    )


def _band_meta(b: VzHlBand | None) -> dict | None:
    if b is None:
        return None
    return {
        "kind": b.kind,
        "role": b.role,
        "day": b.day.isoformat(),
        "high": b.high,
        "low": b.low,
        "volume": b.volume,
    }


def _band_label(b: VzHlBand | None) -> str:
    if b is None:
        return "—"
    return f"{b.day.isoformat()} {_fmt_px(b.low)}–{_fmt_px(b.high)}"


def fetch_btc_usd(out_csv: Path) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        BTC_YAHOO,
        start="2015-01-01",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance returned no data for {BTC_YAHOO}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    df = raw.rename_axis("Date").reset_index()
    keep = [c for c in ("Date", "Open", "High", "Low", "Close", "Adj Close", "Volume") if c in df.columns]
    df = df[keep]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return load_equity_csv(out_csv)


def build_htf_frame(daily: pd.DataFrame, rule: str) -> tuple[pd.DataFrame, list[pd.DatetimeIndex]]:
    """Resample daily OHLC; return HTF bars + list of daily DateIndexes per HTF bar."""
    groups: list[tuple[pd.Timestamp, pd.DataFrame]] = []
    for key, g in daily.groupby(pd.Grouper(freq=rule)):
        if g is None or g.empty:
            continue
        groups.append((pd.Timestamp(key), g))
    if not groups:
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        return empty, []

    rows = []
    members: list[pd.DatetimeIndex] = []
    for _key, g in groups:
        rows.append(
            {
                "Open": float(g["Open"].iloc[0]),
                "High": float(g["High"].max()),
                "Low": float(g["Low"].min()),
                "Close": float(g["Close"].iloc[-1]),
            }
        )
        members.append(g.index)
    htf = pd.DataFrame(rows)
    # Label index as last trading day in the period (stable for mapping)
    htf.index = pd.DatetimeIndex([m[-1] for m in members], name="Date")
    return htf, members


def fractal_pivots(
    high: np.ndarray,
    low: np.ndarray,
    k: int,
) -> list[tuple[str, int]]:
    """Confirmed fractal pivots (need k bars on each side). Returns (kind, idx)."""
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


def pivots_for_frame(
    htf: pd.DataFrame,
    members: list[pd.DatetimeIndex] | None,
    *,
    timeframe: str,
    k: int,
) -> list[Pivot]:
    if htf.empty:
        return []
    high = htf["High"].to_numpy(dtype=float)
    low = htf["Low"].to_numpy(dtype=float)
    raw = fractal_pivots(high, low, k=k)
    pivots: list[Pivot] = []
    for kind, i in raw:
        if members is not None:
            gidx = members[i]
            if kind == "H":
                # Exact daily bar where the period high printed
                # Re-read from member highs via positional — members are DatetimeIndex only;
                # price comes from htf High, date from argmax within member window using daily later.
                # Here we only have DatetimeIndex; date refined by caller for daily TF.
                # For HTF we store period last day temporarily; refined below if daily OHLC passed.
                d = gidx[-1].date()
                px = float(high[i])
            else:
                d = gidx[-1].date()
                px = float(low[i])
        else:
            d = pd.Timestamp(htf.index[i]).date()
            px = float(high[i] if kind == "H" else low[i])
        pivots.append(Pivot(kind=kind, date=d, price=px, tf_bar_idx=i))
    return pivots


def refine_htf_pivot_dates(
    daily: pd.DataFrame,
    members: list[pd.DatetimeIndex],
    pivots: list[Pivot],
) -> list[Pivot]:
    """Map HTF fractal bar to the daily date that printed the period H/L."""
    refined: list[Pivot] = []
    for p in pivots:
        gidx = members[p.tf_bar_idx]
        sub = daily.loc[gidx]
        if p.kind == "H":
            day = sub["High"].idxmax()
            px = float(sub.loc[day, "High"])
        else:
            day = sub["Low"].idxmin()
            px = float(sub.loc[day, "Low"])
        refined.append(
            Pivot(
                kind=p.kind,
                date=pd.Timestamp(day).date(),
                price=px,
                tf_bar_idx=p.tf_bar_idx,
            )
        )
    return refined


def last_two_same_kind(pivots: list[Pivot], kind: str) -> tuple[Pivot, Pivot] | None:
    same = [p for p in pivots if p.kind == kind]
    if len(same) < 2:
        return None
    a, b = same[-2], same[-1]
    if a.date >= b.date:
        return None
    # Degenerate: identical price → flat horizontal (still useful)
    return a, b


def trendlines_for_symbol(daily: pd.DataFrame) -> list[TrendLineSeg]:
    segs: list[TrendLineSeg] = []

    # --- Daily ---
    k_d = PIVOT_K["daily"]
    piv_d = pivots_for_frame(daily, None, timeframe="daily", k=k_d)
    for kind, side in (("L", "support"), ("H", "resistance")):
        pair = last_two_same_kind(piv_d, kind)
        if pair:
            a, b = pair
            segs.append(
                TrendLineSeg(
                    timeframe="daily",
                    side=side,
                    d1=a.date,
                    p1=a.price,
                    d2=b.date,
                    p2=b.price,
                )
            )

    # --- Weekly (Fri-ended weeks) ---
    htf_w, mem_w = build_htf_frame(daily, "W-FRI")
    piv_w = refine_htf_pivot_dates(
        daily, mem_w, pivots_for_frame(htf_w, mem_w, timeframe="weekly", k=PIVOT_K["weekly"])
    )
    for kind, side in (("L", "support"), ("H", "resistance")):
        pair = last_two_same_kind(piv_w, kind)
        if pair:
            a, b = pair
            segs.append(
                TrendLineSeg(
                    timeframe="weekly",
                    side=side,
                    d1=a.date,
                    p1=a.price,
                    d2=b.date,
                    p2=b.price,
                )
            )

    # --- Monthly ---
    htf_m, mem_m = build_htf_frame(daily, "ME")
    piv_m = refine_htf_pivot_dates(
        daily, mem_m, pivots_for_frame(htf_m, mem_m, timeframe="monthly", k=PIVOT_K["monthly"])
    )
    for kind, side in (("L", "support"), ("H", "resistance")):
        pair = last_two_same_kind(piv_m, kind)
        if pair:
            a, b = pair
            segs.append(
                TrendLineSeg(
                    timeframe="monthly",
                    side=side,
                    d1=a.date,
                    p1=a.price,
                    d2=b.date,
                    p2=b.price,
                )
            )

    return segs


def _emit_frozen_cloud(
    lines: list[str],
    *,
    prefix: str,
    show_input: str,
    color_name: str,
    band: VzHlBand,
    bubble_label: str,
    guide_plots: bool = False,
) -> None:
    """Emit date-gated AddCloud for a frozen HL/OC band (HV6m / ts_common pattern)."""
    d = _ymd(band.day)
    hi_s, lo_s = _fmt_px(band.high), _fmt_px(band.low)
    lines.append(
        f"# {bubble_label}: {band.day.isoformat()} High={hi_s} Low={lo_s} "
        f"(vol={band.volume:,.0f})"
    )
    lines.append(f"# Horizontal: GetYYYYMMDD() >= {d} (max-vol day → extend right)")
    lines.append(f"def {prefix}On = {show_input} and GetYYYYMMDD() >= {d};")
    lines.append(f"def {prefix}HiV = if {prefix}On then {hi_s} else Double.NaN;")
    lines.append(f"def {prefix}LoV = if {prefix}On then {lo_s} else Double.NaN;")
    lines.append(
        f"def {prefix}Hi = if {prefix}On then HighestAll({prefix}HiV) else Double.NaN;"
    )
    lines.append(
        f"def {prefix}Lo = if {prefix}On then LowestAll({prefix}LoV) else Double.NaN;"
    )
    lines.append(
        f'AddCloud({prefix}Hi, {prefix}Lo, GlobalColor("{color_name}"), '
        f'GlobalColor("{color_name}"));'
    )
    if guide_plots:
        # Dashed edge guides (charts use axhline on nearest zone edges)
        lines.append(
            f"plot {prefix}EdgeHi = if {prefix}On then {prefix}Hi else Double.NaN;"
        )
        lines.append(f'{prefix}EdgeHi.SetDefaultColor(GlobalColor("{color_name}"));')
        lines.append(f"{prefix}EdgeHi.SetLineWeight(1);")
        lines.append(f"{prefix}EdgeHi.SetStyle(Curve.SHORT_DASH);")
        lines.append(
            f"plot {prefix}EdgeLo = if {prefix}On then {prefix}Lo else Double.NaN;"
        )
        lines.append(f'{prefix}EdgeLo.SetDefaultColor(GlobalColor("{color_name}"));')
        lines.append(f"{prefix}EdgeLo.SetLineWeight(1);")
        lines.append(f"{prefix}EdgeLo.SetStyle(Curve.SHORT_DASH);")
    lines.append(f"def {prefix}Hit = GetYYYYMMDD() == {d};")
    lines.append(
        f'AddChartBubble(showLabels and {show_input} and {prefix}Hit, {hi_s}, '
        f'"{bubble_label} {band.day.isoformat()}", GlobalColor("{color_name}"), yes);'
    )
    lines.append("")


def build_thinkscript(
    *,
    symbol: str,
    tos_symbol: str,
    stamp: str,
    segs: list[TrendLineSeg],
    data_note: str,
    hv6m: HV6mBox | None = None,
    vz: VzOverlayPack | None = None,
) -> str:
    """Emit upper study: trendlines + HV6m + VZ HL zones + SMA20/50/100."""
    vz = vz or VzOverlayPack()
    lines: list[str] = [
        f"# {tos_symbol} M/W/D swing trendlines — stamp {stamp}",
        "# Offline fractal-swing lines (Python) frozen as two-point plot segments.",
        "# Apply on a DAILY chart for this symbol.",
        f"# Data: {data_note}",
        "# Algorithm: last two confirmed fractal swing highs → resistance;",
        "#            last two confirmed fractal swing lows → support;",
        "#            per TF (daily k=5, weekly k=3, monthly k=2).",
        "# HTF pivots mapped to the daily date that printed the period H/L.",
        "# Drawing: BarNumber linear interp between d1/d2; extend right of d2.",
        "# HV6m: AddCloud = High/Low of max-Volume day in last 6 calendar months.",
        f"# VZ HL: house build_zones lookback={VZ_LOOKBACK_DAYS} — current winner HL",
        "#       + nearest HL above/below last close (frozen AddCloud); light OC context.",
        "# SMA20/50/100: native Average(close, N) — live on chart (not frozen).",
        "# Zone clouds: GetYYYYMMDD() >= max-vol day (same as tos/ts_common.py).",
        "",
        "declare upper;",
        "",
        "input showMonthly = yes;",
        "input showWeekly = yes;",
        "input showDaily = yes;",
        "input showSupport = yes;",
        "input showResistance = yes;",
        "input showLabels = yes;",
        "input extendRight = yes;",
        "input showHV6m = yes;",
        "input showVzCurrent = yes;",
        "input showVzNearest = yes;",
        "input showSMA = yes;",
        "",
    ]
    for tf, (r, g, b) in TF_RGB.items():
        gname = tf.capitalize()
        lines.append(f'DefineGlobalColor("{gname}", CreateColor({r}, {g}, {b}));')
    hr, hg, hb = HV6M_RGB
    lines.append(f'DefineGlobalColor("HV6m", CreateColor({hr}, {hg}, {hb}));')
    vr, vg, vb = VZ_HL_RGB
    lines.append(f'DefineGlobalColor("VzHL", CreateColor({vr}, {vg}, {vb}));')
    or_, og, ob = VZ_OC_RGB
    lines.append(f'DefineGlobalColor("VzOC", CreateColor({or_}, {og}, {ob}));')
    ar, ag, ab = VZ_ABOVE_RGB
    lines.append(f'DefineGlobalColor("VzAbove", CreateColor({ar}, {ag}, {ab}));')
    br, bg, bb = VZ_BELOW_RGB
    lines.append(f'DefineGlobalColor("VzBelow", CreateColor({br}, {bg}, {bb}));')
    for period, (sr, sg, sb) in SMA_RGB.items():
        lines.append(
            f'DefineGlobalColor("SMA{period}", CreateColor({sr}, {sg}, {sb}));'
        )
    lines.append("")

    # --- Native SMA overlays (live, match HTML chart periods/colors) ---
    lines.append("# ---- SMA20 / SMA50 / SMA100 (Average close; live) ----")
    for period in SMA_PERIODS:
        lines.append(f"def smaLen{period} = Average(close, {period});")
        lines.append(f"plot SMA{period} = smaLen{period};")
        lines.append(f'SMA{period}.SetDefaultColor(GlobalColor("SMA{period}"));')
        lines.append(f"SMA{period}.SetLineWeight(2);")
        lines.append(f"SMA{period}.SetHiding(!showSMA);")
        lines.append("")

    # One plot per trendline segment
    for i, seg in enumerate(segs, 1):
        tf = seg.timeframe
        gname = tf.capitalize()
        show_tf = f"show{gname}"
        show_side = "showSupport" if seg.side == "support" else "showResistance"
        d1, d2 = _ymd(seg.d1), _ymd(seg.d2)
        p1, p2 = _fmt_px(seg.p1), _fmt_px(seg.p2)
        label = f"{TF_LABEL[tf]} {'Sup' if seg.side == 'support' else 'Res'}"
        style = "Curve.FIRM" if seg.side == "support" else "Curve.SHORT_DASH"
        weight = 3 if tf == "monthly" else (2 if tf == "weekly" else 1)

        lines.append(
            f"# {label}: {seg.d1.isoformat()} @ {p1}  →  {seg.d2.isoformat()} @ {p2}"
        )
        lines.append(f"def b{i}Hit1 = GetYYYYMMDD() == {d1};")
        lines.append(f"def b{i}Hit2 = GetYYYYMMDD() == {d2};")
        lines.append(f"def b{i}N1 = if b{i}Hit1 then BarNumber() else Double.NaN;")
        lines.append(f"def b{i}N2 = if b{i}Hit2 then BarNumber() else Double.NaN;")
        lines.append(f"def b{i}B1 = HighestAll(b{i}N1);")
        lines.append(f"def b{i}B2 = HighestAll(b{i}N2);")
        lines.append(
            f"def b{i}On = {show_tf} and {show_side} and !IsNaN(b{i}B1) and !IsNaN(b{i}B2) "
            f"and b{i}B2 != b{i}B1 and GetYYYYMMDD() >= {d1} "
            f"and (extendRight or GetYYYYMMDD() <= {d2});"
        )
        lines.append(
            f"plot TL{i} = if b{i}On then {p1} + ({p2} - {p1}) * "
            f"(BarNumber() - b{i}B1) / (b{i}B2 - b{i}B1) else Double.NaN;"
        )
        lines.append(f'TL{i}.SetDefaultColor(GlobalColor("{gname}"));')
        lines.append(f"TL{i}.SetLineWeight({weight});")
        lines.append(f"TL{i}.SetStyle({style});")
        lines.append(
            f'AddChartBubble(showLabels and b{i}Hit2, {p2}, "{label}", '
            f'GlobalColor("{gname}"), {"yes" if seg.side == "resistance" else "no"});'
        )
        lines.append("")

    if not segs:
        lines.append("# (no trendline segments — insufficient swings; SMAs/zones still plot)")
        lines.append("")

    # HV6m volume-day box
    if hv6m is not None:
        d = _ymd(hv6m.day)
        hi_s, lo_s = _fmt_px(hv6m.high), _fmt_px(hv6m.low)
        vol_s = f"{hv6m.volume:,.0f}"
        lines.append(
            f"# HV6m box: max Volume day {hv6m.day.isoformat()} "
            f"(vol={vol_s}) High={hi_s} Low={lo_s}; "
            f"window {hv6m.window_start.isoformat()} → {hv6m.window_end.isoformat()}"
        )
        lines.append(
            f"# Horizontal: GetYYYYMMDD() >= {d} (from HV day through last bar / extend right)"
        )
        lines.append(f"def hvOn = showHV6m and GetYYYYMMDD() >= {d};")
        lines.append(f"def hvHiV = if hvOn then {hi_s} else Double.NaN;")
        lines.append(f"def hvLoV = if hvOn then {lo_s} else Double.NaN;")
        lines.append("def hvHi = if hvOn then HighestAll(hvHiV) else Double.NaN;")
        lines.append("def hvLo = if hvOn then LowestAll(hvLoV) else Double.NaN;")
        lines.append('AddCloud(hvHi, hvLo, GlobalColor("HV6m"), GlobalColor("HV6m"));')
        lines.append(f"def hvHit = GetYYYYMMDD() == {d};")
        lines.append(
            f'AddChartBubble(showLabels and showHV6m and hvHit, {hi_s}, '
            f'"HV6m {hv6m.day.isoformat()}", GlobalColor("HV6m"), yes);'
        )
        lines.append("")

    # House VZ overlays (frozen nearest + current — not full zone history)
    lines.append(
        f"# ---- House VZ HL overlays (lookback={VZ_LOOKBACK_DAYS}; "
        f"n_hl={vz.n_hl_zones}; last_close="
        f"{_fmt_px(vz.last_close) if vz.last_close is not None else 'n/a'}) ----"
    )
    if vz.current_hl is not None:
        _emit_frozen_cloud(
            lines,
            prefix="vzHl",
            show_input="showVzCurrent",
            color_name="VzHL",
            band=vz.current_hl,
            bubble_label="VZ HL",
        )
    if vz.current_oc is not None:
        _emit_frozen_cloud(
            lines,
            prefix="vzOc",
            show_input="showVzCurrent",
            color_name="VzOC",
            band=vz.current_oc,
            bubble_label="VZ OC",
        )
    if vz.nearest_above is not None:
        _emit_frozen_cloud(
            lines,
            prefix="vzAb",
            show_input="showVzNearest",
            color_name="VzAbove",
            band=vz.nearest_above,
            bubble_label="VZ Above",
            guide_plots=True,
        )
    if vz.nearest_below is not None:
        _emit_frozen_cloud(
            lines,
            prefix="vzBl",
            show_input="showVzNearest",
            color_name="VzBelow",
            band=vz.nearest_below,
            bubble_label="VZ Below",
            guide_plots=True,
        )
    if (
        vz.current_hl is None
        and vz.current_oc is None
        and vz.nearest_above is None
        and vz.nearest_below is None
    ):
        lines.append("# (no VZ HL overlays — insufficient bars or missing Volume)")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_readme(
    stamp_dir: Path,
    *,
    stamp: str,
    rows: list[dict],
    hv_rows: list[dict],
    vz_rows: list[dict] | None = None,
    intro: str = "",
) -> Path:
    path = stamp_dir / "README.md"
    vz_rows = vz_rows or []
    lines = [
        f"# M / W / D swing trendlines (Thinkorswim / ToS) — `{stamp}`",
        "",
    ]
    if intro.strip():
        lines.append(intro.strip())
        lines.append("")
    lines.extend(
        [
            "## Honest answer on accuracy",
            "",
            "Thinkorswim (ToS) **cannot** automate discretionary hand-drawn trendlines "
            "(analyst judgment on which touches matter). ThinkScript also has no "
            "reliable general-purpose `Drawing.CreateTrendLine` path that matches "
            "manual drawings across chart types in all ToS builds.",
            "",
            "What we **can** do accurately:",
            "",
            "1. Define an **objective** swing algorithm in Python on OHLC.",
            "2. Freeze the resulting two-point geometry into ThinkScript `plot` "
            "segments using **BarNumber** linear interpolation (same frozen-geometry "
            "pattern as RL stop segments / LT zone studies).",
            "3. Overlay those segments on a **Daily** chart so dates line up.",
            "4. Add an **HV6m** volume-day High/Low box (frozen `AddCloud`, same date-gate "
            "pattern as zone boxes in `tos/ts_common.py`).",
            "5. Add **house Vol Zone (VZ) HL** overlays matching HTML charts: current "
            f"{VZ_LOOKBACK_DAYS}d rolling max-volume winner + nearest HL above/below "
            "last close (`tools/vol_zone_break_retest.build_zones`), plus light OC context.",
            "6. Plot **SMA20 / SMA50 / SMA100** via native `Average(close, N)` (live).",
            "",
            "So: **accurate vs the stated algorithm**, not vs a human discretionary line.",
            "",
            "## Algorithm",
            "",
            "### Fractal swings",
            "",
            "On each timeframe bar series, bar `i` is a confirmed swing high if "
            "`High[i]` is the max of `High[i-k : i+k]` (inclusive). Swing low: "
            "`Low[i]` is the min of the same window. Confirmation needs `k` bars "
            "on **both** sides (right bars must exist).",
            "",
            "| Timeframe | Source bars | `k` |",
            "|---|---|---|",
            "| Daily | daily OHLC | 5 |",
            "| Weekly | daily → `W-FRI` OHLC | 3 |",
            "| Monthly | daily → month-end OHLC | 2 |",
            "",
            "### Line construction",
            "",
            "- **Resistance:** connect the **last two** confirmed swing highs.",
            "- **Support:** connect the **last two** confirmed swing lows.",
            "- **HTF date mapping:** for weekly/monthly pivots, use the **daily** "
            "date inside that period where the period High (or Low) actually printed "
            "(so the segment anchors on a real daily bar).",
            "- **Extension:** from the earlier pivot through the later pivot, then "
            "**extend right** along the same slope (`extendRight = yes`).",
            "",
            "### HV6m volume-day box",
            "",
            "- **Window:** last **6 calendar months** ending at the last available OHLC bar date.",
            "- **Pick:** the single day with **max Volume** in that window (ties → most recent).",
            "- **Vertical:** that day's **High** to **Low**.",
            "- **Horizontal:** from that day's date **through the last bar / extend right** "
            "(`GetYYYYMMDD() >= HV day`), matching zone-box gating in `tos/ts_common.py` "
            "(not a fixed end date).",
            "- **Color:** muted gold/amber (`HV6m`); toggle `showHV6m`.",
            "- **Label:** `HV6m YYYY-MM-DD` bubble on the HV day (when `showLabels`).",
            "",
            "### House VZ HL zones (match HTML charts)",
            "",
            f"- **Engine:** `build_zones(df, lookback={VZ_LOOKBACK_DAYS})` — every unique "
            "rolling max-volume winner becomes a persistent OC + HL band.",
            "- **Current VZ HL (purple):** winner as of the last bar; High–Low of that day.",
            "- **Current VZ OC (light blue):** Open–Close of the same winner day (context only; "
            "house rocket_vz entry filter is HL-only).",
            "- **Nearest above / below:** among all mature HL zones, nearest with zone low "
            "above last close (above) or zone high below last close (below) — same selection "
            "as `gen_trendlines_charts_html.nearest_hl_zones`.",
            "- **Drawing:** frozen `AddCloud` from max-vol day extend-right; nearest also get "
            "dashed edge guide plots. Toggles: `showVzCurrent`, `showVzNearest`.",
            "- **Not embedded:** full historical fan of every past VZ winner (ToS study size / "
            "readability) — only current + nearest above/below.",
            "",
            "### SMA20 / SMA50 / SMA100",
            "",
            "- Native ThinkScript `Average(close, N)` — **live** (updates with new bars).",
            "- Colors match HTML charts: pink / orange / brown. Toggle: `showSMA`.",
            "",
            "### ThinkScript drawing",
            "",
            "For each segment with dates `d1`/`d2` and prices `p1`/`p2`:",
            "",
            "```text",
            "B1 = BarNumber on d1;  B2 = BarNumber on d2",
            "price(bar) = p1 + (p2-p1) * (BarNumber - B1) / (B2 - B1)",
            "```",
            "",
            "Support = firm line; resistance = short dash. Colors: monthly violet, "
            "weekly orange, daily cyan. Labels at the second pivot.",
            "",
            "HV6m / VZ clouds:",
            "",
            "```text",
            "on = GetYYYYMMDD() >= zone_day",
            "AddCloud(HighestAll(High), LowestAll(Low)) while on",
            "```",
            "",
            "## Install (Thinkorswim)",
            "",
            "1. Open ToS → Charts → Studies → Edit Studies → **Create** (or Import).",
            "2. Paste the contents of the matching `.ts` file (or copy from shared drive).",
            "3. Name it e.g. `Paul TL NVDA MWD`.",
            "4. Apply on a **Daily** aggregation chart for that symbol.",
            "5. Toggles: `showMonthly` / `showWeekly` / `showDaily`, "
            "`showSupport` / `showResistance`, `showLabels`, `extendRight`, "
            "`showHV6m`, `showVzCurrent`, `showVzNearest`, `showSMA`.",
            "",
            "## Symbols / BTC naming",
            "",
            "| Study file | Equity data | Prefer ToS chart symbol |",
            "|---|---|---|",
        ]
    )
    # Unique symbols from segment / HV / VZ rows
    seen: set[str] = set()
    sym_order: list[tuple[str, str]] = []
    for r in rows + hv_rows + vz_rows:
        sym = r["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        study = r.get("study") or f"{sym}_trendlines_mwd.ts"
        sym_order.append((sym, study))
    for sym, study in sym_order:
        if sym == "BTC":
            lines.append(
                f"| `{study}` | Yahoo `{BTC_YAHOO}` (saved in stamp) | "
                f"**`{BTC_TOS_PREFERRED}`** (spot-like). "
                f"`{BTC_TOS_ALT}` is CME futures — prices will **not** match this study. |"
            )
        else:
            lines.append(
                f"| `{study}` | `data/newdata/data/{sym}.csv` | `{sym}` |"
            )
    if not sym_order:
        lines.append(
            f"| `NVDA_trendlines_mwd.ts` | `data/newdata/data/NVDA.csv` | `NVDA` |"
        )
    lines.extend(
        [
            "",
            "## Limitations / blockers",
            "",
            "- Trendline / HV6m / VZ clouds go stale until you **re-run** this generator "
            "(frozen geometry). SMAs are live.",
            "- Weekly/monthly AggregationPeriod live HTF inside ThinkScript is brittle "
            "across chart types (same lesson as RL closed studies); offline freeze is intentional.",
            "- If a pivot date is missing on the chart (holiday mapping edge case), that "
            "segment will not plot (`HighestAll` of BarNumber stays NaN).",
            "- Only the **latest** support + resistance per TF (two pivots each) — not a fan of all historical swings.",
            "- VZ embeds **current + nearest above/below only**, not the full zone history.",
            "- HV6m / VZ need a Volume column; missing/zero volume → no box/zones for that symbol.",
            "- Discretionary multi-touch / channel judgment is out of scope.",
            "",
            "## Regenerated",
            "",
            f"- Stamp: `{stamp}`",
            f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## HV6m boxes",
            "",
            "| Symbol | HV day | High | Low | Volume | Window start | Window end |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for r in hv_rows:
        lines.append(
            f"| {r['symbol']} | {r['day']} | {r['high']} | {r['low']} | "
            f"{r['volume']} | {r['window_start']} | {r['window_end']} |"
        )
    if not hv_rows:
        lines.append("| — | — | — | — | — | — | — |")
    lines.extend(
        [
            "",
            "## VZ HL overlays",
            "",
            "| Symbol | Last close | Current HL | Current OC | Nearest above | Nearest below | N HL |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for r in vz_rows:
        lines.append(
            f"| {r['symbol']} | {r['last_close']} | {r['current_hl']} | {r['current_oc']} | "
            f"{r['nearest_above']} | {r['nearest_below']} | {r['n_hl_zones']} |"
        )
    if not vz_rows:
        lines.append("| — | — | — | — | — | — | — |")
    lines.extend(
        [
            "",
            "## Segments",
            "",
            "| Symbol | TF | Side | D1 | P1 | D2 | P2 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for r in rows:
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['side']} | "
            f"{r['d1']} | {r['p1']} | {r['d2']} | {r['p2']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_html(
    stamp_dir: Path,
    *,
    stamp: str,
    rows: list[dict],
    hv_rows: list[dict],
    notes: list[str],
    vz_rows: list[dict] | None = None,
) -> Path:
    path = stamp_dir / "index.html"
    head = "".join(
        [
            _sortable_th("Symbol", "text"),
            _sortable_th("ToS chart", "text"),
            _sortable_th("TF", "text"),
            _sortable_th("Side", "text"),
            _sortable_th("D1", "date"),
            _sortable_th("P1", "num"),
            _sortable_th("D2", "date"),
            _sortable_th("P2", "num"),
            _sortable_th("Study file", "text"),
        ]
    )
    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{html_mod.escape(r['tos_symbol'])}</td>"
            f"<td>{html_mod.escape(r['timeframe'])}</td>"
            f"<td>{html_mod.escape(r['side'])}</td>"
            f"<td>{html_mod.escape(r['d1'])}</td>"
            f"<td>{html_mod.escape(str(r['p1']))}</td>"
            f"<td>{html_mod.escape(r['d2'])}</td>"
            f"<td>{html_mod.escape(str(r['p2']))}</td>"
            f"<td><code>{html_mod.escape(r['study'])}</code></td>"
            "</tr>"
        )
    hv_head = "".join(
        [
            _sortable_th("Symbol", "text"),
            _sortable_th("HV day", "date"),
            _sortable_th("High", "num"),
            _sortable_th("Low", "num"),
            _sortable_th("Volume", "num"),
            _sortable_th("Window start", "date"),
            _sortable_th("Window end", "date"),
            _sortable_th("Study file", "text"),
        ]
    )
    hv_body = []
    for r in hv_rows:
        hv_body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{html_mod.escape(r['day'])}</td>"
            f"<td>{html_mod.escape(str(r['high']))}</td>"
            f"<td>{html_mod.escape(str(r['low']))}</td>"
            f"<td>{html_mod.escape(str(r['volume']))}</td>"
            f"<td>{html_mod.escape(r['window_start'])}</td>"
            f"<td>{html_mod.escape(r['window_end'])}</td>"
            f"<td><code>{html_mod.escape(r['study'])}</code></td>"
            "</tr>"
        )
    notes_html = "".join(f"<li>{html_mod.escape(n)}</li>" for n in notes)
    vz_rows = vz_rows or []
    vz_head = "".join(
        [
            _sortable_th("Symbol", "text"),
            _sortable_th("Last close", "num"),
            _sortable_th("Current HL", "text"),
            _sortable_th("Current OC", "text"),
            _sortable_th("Nearest above", "text"),
            _sortable_th("Nearest below", "text"),
            _sortable_th("N HL", "num"),
            _sortable_th("Study file", "text"),
        ]
    )
    vz_body = []
    for r in vz_rows:
        vz_body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{html_mod.escape(str(r['last_close']))}</td>"
            f"<td>{html_mod.escape(r['current_hl'])}</td>"
            f"<td>{html_mod.escape(r['current_oc'])}</td>"
            f"<td>{html_mod.escape(r['nearest_above'])}</td>"
            f"<td>{html_mod.escape(r['nearest_below'])}</td>"
            f"<td>{html_mod.escape(str(r['n_hl_zones']))}</td>"
            f"<td><code>{html_mod.escape(r['study'])}</code></td>"
            "</tr>"
        )
    hr, hg, hb = HV6M_RGB
    vr, vg, vb = VZ_HL_RGB
    or_, og, ob = VZ_OC_RGB
    ar, ag, ab = VZ_ABOVE_RGB
    br, bg, bb = VZ_BELOW_RGB
    s20 = SMA_RGB[20]
    s50 = SMA_RGB[50]
    s100 = SMA_RGB[100]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Trendlines M/W/D (ToS) — {html_mod.escape(stamp)}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1100px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
main{{max-width:1100px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{border-collapse:collapse;width:100%;font-size:.85rem;min-width:720px}}
th,td{{border-bottom:1px solid var(--line);padding:.4rem .45rem;text-align:left}}
th.sortable-th{{cursor:pointer;user-select:none;white-space:nowrap}}
th.sortable-th .sort-ind{{opacity:.45;font-size:.85em;margin-left:.25em}}
th.sortable-th.sort-asc .sort-ind::after{{content:"▲"}}
th.sortable-th.sort-desc .sort-ind::after{{content:"▼"}}
th.sortable-th:not(.sort-asc):not(.sort-desc) .sort-ind::after{{content:"↕"}}
code{{font-size:.9em}}
ul{{margin:.4rem 0 .2rem 1.1rem}}
.swatch{{display:inline-block;width:.85em;height:.85em;border-radius:2px;margin-right:.35em;vertical-align:middle}}
</style>
</head>
<body>
<header>
<h1>Thinkorswim (ToS) M/W/D trendlines + HV6m + VZ HL + SMAs</h1>
<p class="muted">Stamp <code>{html_mod.escape(stamp)}</code>. Offline Python swings → frozen ThinkScript segments,
HV6m box, house Vol Zone (VZ) HL current + nearest above/below, and live SMA20/50/100.
Matches HTML chart overlays from <code>gen_trendlines_charts_html.py</code>.
Click column headers to sort.</p>
</header>
<main>
<section>
<h2>Accuracy (honest)</h2>
<ul>
<li>ToS/ThinkScript cannot reliably automate discretionary trendlines.</li>
<li>These studies freeze <strong>last-two fractal swing</strong> support/resistance per TF.</li>
<li>HV6m box = High/Low of the max-Volume daily bar in the trailing 6 months (ties → most recent).</li>
<li>VZ HL = house <code>build_zones</code> ({VZ_LOOKBACK_DAYS}d) — current winner + nearest above/below last close (not full zone history).</li>
<li>SMA20/50/100 = native <code>Average(close, N)</code> (live).</li>
<li>Use on a <strong>Daily</strong> chart; BarNumber interpolation matches trading bars.</li>
</ul>
</section>
<section>
<h2>Colors</h2>
<p>
<span class="swatch" style="background:rgb(186,104,200)"></span>Monthly ·
<span class="swatch" style="background:rgb(255,152,0)"></span>Weekly ·
<span class="swatch" style="background:rgb(0,188,212)"></span>Daily ·
<span class="swatch" style="background:rgb({hr},{hg},{hb})"></span>HV6m ·
<span class="swatch" style="background:rgb({vr},{vg},{vb})"></span>VZ HL current ·
<span class="swatch" style="background:rgb({or_},{og},{ob})"></span>VZ OC ·
<span class="swatch" style="background:rgb({ar},{ag},{ab})"></span>VZ nearest above ·
<span class="swatch" style="background:rgb({br},{bg},{bb})"></span>VZ nearest below ·
<span class="swatch" style="background:rgb({s20[0]},{s20[1]},{s20[2]})"></span>SMA20 ·
<span class="swatch" style="background:rgb({s50[0]},{s50[1]},{s50[2]})"></span>SMA50 ·
<span class="swatch" style="background:rgb({s100[0]},{s100[1]},{s100[2]})"></span>SMA100
</p>
<p class="muted">Support = firm; Resistance = short dash. Toggles: showHV6m / showVzCurrent / showVzNearest / showSMA.</p>
</section>
<section>
<h2>HV6m box</h2>
<ul>
<li>Window: last 6 calendar months ending at last OHLC bar.</li>
<li>Horizontal: from HV day through last bar (extend right) via <code>GetYYYYMMDD() &gt;= HV day</code> — same as zone boxes in <code>tos/ts_common.py</code>.</li>
<li>Toggle: <code>showHV6m</code>.</li>
</ul>
<p class="muted">Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{hv_head}</tr></thead><tbody>
{''.join(hv_body) if hv_body else '<tr><td colspan="8">—</td></tr>'}
</tbody></table></div>
</section>
<section>
<h2>House VZ HL overlays</h2>
<ul>
<li>Engine: <code>tools/vol_zone_break_retest.build_zones</code> lookback {VZ_LOOKBACK_DAYS}.</li>
<li>Current HL (purple) + light OC (blue); nearest HL above (red) / below (green) vs last close.</li>
<li>Frozen AddCloud from max-vol day extend-right — <strong>not</strong> the full historical zone fan.</li>
<li>Toggles: <code>showVzCurrent</code>, <code>showVzNearest</code>.</li>
</ul>
<p class="muted">Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{vz_head}</tr></thead><tbody>
{''.join(vz_body) if vz_body else '<tr><td colspan="8">—</td></tr>'}
</tbody></table></div>
</section>
<section>
<h2>Install</h2>
<ol>
<li>Studies → Edit Studies → Create / paste the <code>.ts</code> file for the symbol.</li>
<li>Apply on Daily aggregation for that symbol.</li>
<li>BTC: prefer <code>{html_mod.escape(BTC_TOS_PREFERRED)}</code>; avoid <code>{html_mod.escape(BTC_TOS_ALT)}</code> (futures scale mismatch).</li>
</ol>
</section>
<section>
<h2>Frozen segments</h2>
<p class="muted">Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead><tbody>
{''.join(body_rows)}
</tbody></table></div>
</section>
<section>
<h2>Notes</h2>
<ul>{notes_html}</ul>
</section>
</main>
{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path


def resolve_symbol(
    sym: str,
    data_dir: Path,
    stamp_dir: Path,
) -> tuple[str, str, pd.DataFrame, str]:
    """Return (symbol_key, tos_symbol, df, data_note)."""
    u = sym.strip().upper().replace("/", "")
    if u in ("BTC", "BTCUSD", "BTC-USD"):
        csv_path = stamp_dir / "data" / "BTCUSD.csv"
        df = fetch_btc_usd(csv_path)
        note = f"Yahoo {BTC_YAHOO} → {csv_path.as_posix()} (as-of fetch)"
        return "BTC", BTC_TOS_PREFERRED, df, note
    path = data_dir / f"{u}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Missing OHLC CSV: {path}")
    df = load_equity_csv(path)
    note = path.as_posix()
    return u, u, df, note


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="NVDA,AU,BTC")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("--stamp-dir", type=Path, default=None)
    ap.add_argument(
        "--intro",
        default="",
        help="Optional markdown blurb inserted under the README title (universe note, etc.).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    stamp_dir = Path(args.stamp_dir) if args.stamp_dir else (_REPO / "drive" / "paul_studies" / args.stamp)
    stamp_dir.mkdir(parents=True, exist_ok=True)
    studies_dir = stamp_dir / "studies"
    studies_dir.mkdir(parents=True, exist_ok=True)

    table_rows: list[dict] = []
    hv_rows: list[dict] = []
    vz_rows: list[dict] = []
    notes: list[str] = []
    meta: dict = {
        "stamp": args.stamp,
        "symbols": {},
        "pivot_k": PIVOT_K,
        "hv6m_months": HV6M_MONTHS,
        "vz_lookback_days": VZ_LOOKBACK_DAYS,
        "sma_periods": list(SMA_PERIODS),
        "overlays": [
            "mwd_fractal_trendlines",
            "hv6m",
            "vz_hl_current",
            "vz_oc_current",
            "vz_hl_nearest_above",
            "vz_hl_nearest_below",
            "sma20",
            "sma50",
            "sma100",
        ],
    }

    for raw in str(args.symbols).split(","):
        if not raw.strip():
            continue
        try:
            key, tos_sym, df, data_note = resolve_symbol(raw, Path(args.data_dir), stamp_dir)
        except FileNotFoundError as e:
            msg = f"SKIP missing OHLC for {raw.strip().upper()}: {e}"
            notes.append(msg)
            print(f"[skip] {msg}")
            continue
        segs = trendlines_for_symbol(df)
        hv6m = find_hv6m_box(df)
        vz = find_vz_overlays(df)
        ts_name = f"{key}_trendlines_mwd.ts"
        ts_path = studies_dir / ts_name
        text = build_thinkscript(
            symbol=key,
            tos_symbol=tos_sym,
            stamp=args.stamp,
            segs=segs,
            data_note=data_note,
            hv6m=hv6m,
            vz=vz,
        )
        ts_path.write_text(text, encoding="utf-8")
        hv_note = (
            f"HV6m {hv6m.day.isoformat()} H={_fmt_px(hv6m.high)} L={_fmt_px(hv6m.low)} "
            f"vol={hv6m.volume:,.0f}"
            if hv6m
            else "HV6m none"
        )
        vz_note = (
            f"VZ above={_band_label(vz.nearest_above)} below={_band_label(vz.nearest_below)} "
            f"curHL={_band_label(vz.current_hl)}"
        )
        notes.append(f"{key}: {len(segs)} segments; {hv_note}; {vz_note}; SMA20/50/100 from {data_note}")
        if key == "BTC":
            notes.append(
                f"BTC ToS caveat: study prices are {BTC_YAHOO}/spot-like; "
                f"chart {BTC_TOS_PREFERRED}. Do not expect {BTC_TOS_ALT} futures to overlay."
            )
        hv_meta = None
        if hv6m is not None:
            hv_meta = {
                "day": hv6m.day.isoformat(),
                "high": hv6m.high,
                "low": hv6m.low,
                "volume": hv6m.volume,
                "window_start": hv6m.window_start.isoformat(),
                "window_end": hv6m.window_end.isoformat(),
            }
            hv_rows.append(
                {
                    "symbol": key,
                    "tos_symbol": tos_sym,
                    "day": hv6m.day.isoformat(),
                    "high": _fmt_px(hv6m.high),
                    "low": _fmt_px(hv6m.low),
                    "volume": f"{hv6m.volume:,.0f}",
                    "window_start": hv6m.window_start.isoformat(),
                    "window_end": hv6m.window_end.isoformat(),
                    "study": ts_name,
                }
            )
        vz_meta = {
            "last_close": vz.last_close,
            "n_hl_zones": vz.n_hl_zones,
            "current_hl": _band_meta(vz.current_hl),
            "current_oc": _band_meta(vz.current_oc),
            "nearest_above": _band_meta(vz.nearest_above),
            "nearest_below": _band_meta(vz.nearest_below),
        }
        vz_rows.append(
            {
                "symbol": key,
                "tos_symbol": tos_sym,
                "last_close": _fmt_px(vz.last_close) if vz.last_close is not None else "—",
                "current_hl": _band_label(vz.current_hl),
                "current_oc": _band_label(vz.current_oc),
                "nearest_above": _band_label(vz.nearest_above),
                "nearest_below": _band_label(vz.nearest_below),
                "n_hl_zones": vz.n_hl_zones,
                "study": ts_name,
            }
        )
        meta["symbols"][key] = {
            "tos_symbol": tos_sym,
            "data_note": data_note,
            "n_bars": int(len(df)),
            "last_date": str(pd.Timestamp(df.index[-1]).date()),
            "study": ts_name,
            "hv6m": hv_meta,
            "vz": vz_meta,
            "segments": [
                {
                    "timeframe": s.timeframe,
                    "side": s.side,
                    "d1": s.d1.isoformat(),
                    "p1": s.p1,
                    "d2": s.d2.isoformat(),
                    "p2": s.p2,
                }
                for s in segs
            ],
        }
        for s in segs:
            table_rows.append(
                {
                    "symbol": key,
                    "tos_symbol": tos_sym,
                    "timeframe": s.timeframe,
                    "side": s.side,
                    "d1": s.d1.isoformat(),
                    "p1": _fmt_px(s.p1),
                    "d2": s.d2.isoformat(),
                    "p2": _fmt_px(s.p2),
                    "study": ts_name,
                }
            )
        print(f"[ok] {key}: {len(segs)} lines; {hv_note}; {vz_note} -> {ts_path}")

    write_readme(
        stamp_dir,
        stamp=args.stamp,
        rows=table_rows,
        hv_rows=hv_rows,
        vz_rows=vz_rows,
        intro=str(args.intro or ""),
    )
    html_path = write_html(
        stamp_dir,
        stamp=args.stamp,
        rows=table_rows,
        hv_rows=hv_rows,
        vz_rows=vz_rows,
        notes=notes,
    )
    (stamp_dir / "segments.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[ok] HTML {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
