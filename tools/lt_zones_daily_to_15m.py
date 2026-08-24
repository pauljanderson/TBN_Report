#!/usr/bin/env python3
"""Long-term daily S/R zones overlaid on 15-minute charts (research / education).

Computes historically strong daily levels:
  - Yearly high / low (rolling 252 trading days)
  - Multi-touch swing S/R (pivot clusters)
  - Volume profile POC / HVN / LVN (reuses stock_analysis.vec_zones)

Carries them forward as horizontal bands on 15m OHLC (1m parquet resampled).

Examples:
  python tools/lt_zones_daily_to_15m.py -s AA --stamp
  python tools/lt_zones_daily_to_15m.py --scan --universe drive/universes/BRT_universe.csv \\
      --universe drive/universes/RL_universe.csv --top 8 --stamp
  python tools/lt_zones_daily_to_15m.py -s NVDA,AMD --out-dir drive/paul_experiments/lt_zones_15m_examples_20260823

Not a KEEP claim; not DailyRun-wired.
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SA = _REPO / "stock_analysis"
if str(_SA) not in sys.path:
    sys.path.insert(0, str(_SA))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from vec_zones import (  # noqa: E402
    VP_BIN_PCT,
    VP_HVN_FRAC,
    VP_LOOKBACK,
    VP_LVN_FRAC,
    compute_volume_profile,
)
from intraday_1m import DEFAULT_1M_DIR, resample_symbol_1m  # noqa: E402

DEFAULT_STAMP = _REPO / "drive" / "paul_experiments" / "lt_zones_15m_examples_20260823"
DEFAULT_DAILY = _REPO / "data" / "newdata" / "data"

# Soft pink S/R (StreetSmart-ish) + distinct accents
ZONE_COLORS = {
    "yearly_high": ("#e91e8c", 0.28),
    "yearly_low": ("#e91e8c", 0.28),
    "swing_sr": ("#f48fb1", 0.22),
    "poc": ("#1565c0", 0.30),
    "hvn": ("#42a5f5", 0.22),
    "lvn": ("#90a4ae", 0.15),
}


@dataclass
class Zone:
    symbol: str
    zone_type: str
    lo: float
    hi: float
    touches: int
    source: str
    mid: float = 0.0
    strength: float = 0.0
    confluence: str = ""

    def __post_init__(self) -> None:
        if not self.mid:
            self.mid = 0.5 * (float(self.lo) + float(self.hi))


def _load_daily(symbol: str, data_dir: Path) -> pd.DataFrame:
    path = data_dir / f"{symbol.upper()}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Missing daily CSV: {path}")
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for want in ("date", "open", "high", "low", "close", "volume"):
        if want not in cols:
            raise ValueError(f"{path}: missing column {want}")
        rename[cols[want]] = want.capitalize() if want != "date" else "Date"
    # normalize
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]]),
            "Open": pd.to_numeric(df[cols["open"]], errors="coerce"),
            "High": pd.to_numeric(df[cols["high"]], errors="coerce"),
            "Low": pd.to_numeric(df[cols["low"]], errors="coerce"),
            "Close": pd.to_numeric(df[cols["close"]], errors="coerce"),
            "Volume": pd.to_numeric(df[cols["volume"]], errors="coerce"),
        }
    ).dropna(subset=["High", "Low", "Close"])
    out = out.sort_values("Date").reset_index(drop=True)
    return out


def _atr14(df: pd.DataFrame) -> float:
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    if len(c) < 2:
        return float("nan")
    prev = np.roll(c, 1)
    prev[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    n = min(14, len(tr))
    return float(np.nanmean(tr[-n:]))


def _band_pad(level: float, atr: float, pct: float = 0.0025) -> tuple[float, float]:
    pad = max(abs(level) * pct, (atr * 0.15) if np.isfinite(atr) else 0.0)
    return float(level - pad), float(level + pad)


def yearly_hl_zones(df: pd.DataFrame, symbol: str, window: int = 252) -> list[Zone]:
    n = len(df)
    w = min(int(window), n)
    if w < 20:
        return []
    seg = df.iloc[-w:]
    yh = float(seg["High"].max())
    yl = float(seg["Low"].min())
    atr = _atr14(df)
    yhi_lo, yhi_hi = _band_pad(yh, atr)
    ylo_lo, ylo_hi = _band_pad(yl, atr)
    # touch counts: how many days high/low within 0.5% of extreme
    tol = 0.005
    touches_h = int(np.sum((seg["High"].to_numpy(float) >= yh * (1 - tol))))
    touches_l = int(np.sum((seg["Low"].to_numpy(float) <= yl * (1 + tol))))
    return [
        Zone(
            symbol,
            "yearly_high",
            yhi_lo,
            yhi_hi,
            max(1, touches_h),
            f"rolling_{w}d_max_high",
            mid=yh,
            strength=100.0,
        ),
        Zone(
            symbol,
            "yearly_low",
            ylo_lo,
            ylo_hi,
            max(1, touches_l),
            f"rolling_{w}d_min_low",
            mid=yl,
            strength=100.0,
        ),
    ]


def _fractal_pivots(high: np.ndarray, low: np.ndarray, k: int = 3) -> tuple[list[float], list[float]]:
    ph: list[float] = []
    pl: list[float] = []
    n = len(high)
    k = max(1, int(k))
    for i in range(k, n - k):
        window_h = high[i - k : i + k + 1]
        window_l = low[i - k : i + k + 1]
        if high[i] >= np.max(window_h) and np.isfinite(high[i]):
            ph.append(float(high[i]))
        if low[i] <= np.min(window_l) and np.isfinite(low[i]):
            pl.append(float(low[i]))
    return ph, pl


def _cluster_prices(prices: list[float], tol_pct: float, min_touches: int) -> list[tuple[float, float, int]]:
    if not prices:
        return []
    ordered = sorted(float(p) for p in prices if np.isfinite(p) and p > 0)
    clusters: list[list[float]] = []
    for p in ordered:
        if not clusters:
            clusters.append([p])
            continue
        mid = float(np.mean(clusters[-1]))
        if abs(p - mid) / mid <= tol_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    out: list[tuple[float, float, int]] = []
    for cl in clusters:
        if len(cl) < min_touches:
            continue
        out.append((float(min(cl)), float(max(cl)), len(cl)))
    out.sort(key=lambda t: (-t[2], -(t[1] - t[0])))
    return out


def swing_sr_zones(
    df: pd.DataFrame,
    symbol: str,
    *,
    pivot_k: int = 3,
    cluster_tol_pct: float = 0.0075,
    min_touches: int = 3,
    max_zones: int = 8,
    lookback: int = 504,
) -> list[Zone]:
    n = len(df)
    start = max(0, n - int(lookback))
    seg = df.iloc[start:]
    high = seg["High"].to_numpy(float)
    low = seg["Low"].to_numpy(float)
    ph, pl = _fractal_pivots(high, low, k=pivot_k)
    zones: list[Zone] = []
    for side, prices in (("high", ph), ("low", pl)):
        for lo, hi, touches in _cluster_prices(prices, cluster_tol_pct, min_touches)[: max_zones // 2 + 2]:
            mid = 0.5 * (lo + hi)
            # pad thin clusters a bit
            if hi - lo < mid * 0.002:
                pad = mid * 0.0025
                lo, hi = mid - pad, mid + pad
            zones.append(
                Zone(
                    symbol,
                    "swing_sr",
                    lo,
                    hi,
                    touches,
                    f"pivot_cluster_{side}_k{pivot_k}",
                    mid=mid,
                    strength=float(10 + touches * 5),
                )
            )
    zones.sort(key=lambda z: (-z.touches, -z.strength))
    return zones[:max_zones]


def vp_zones(df: pd.DataFrame, symbol: str, include_lvn: bool = True) -> list[Zone]:
    high = df["High"].to_numpy(float)
    low = df["Low"].to_numpy(float)
    close = df["Close"].to_numpy(float)
    vol = df["Volume"].to_numpy(float)
    end = len(df) - 1
    prof = compute_volume_profile(
        high,
        low,
        close,
        vol,
        end,
        lookback=VP_LOOKBACK,
        bin_pct=VP_BIN_PCT,
        hvn_frac=VP_HVN_FRAC,
        lvn_frac=VP_LVN_FRAC,
    )
    if prof is None:
        return []
    atr = _atr14(df)
    zones: list[Zone] = []
    plo, phi = _band_pad(prof.poc, atr, pct=0.003)
    zones.append(
        Zone(
            symbol,
            "poc",
            plo,
            phi,
            1,
            f"vp_lookback_{VP_LOOKBACK}_poc",
            mid=float(prof.poc),
            strength=80.0,
        )
    )
    # Merge contiguous HVN bins
    hvn = sorted(int(i) for i in prof.hvn_idx)
    if hvn:
        runs: list[list[int]] = [[hvn[0]]]
        for i in hvn[1:]:
            if i == runs[-1][-1] + 1:
                runs[-1].append(i)
            else:
                runs.append([i])
        for run in runs:
            blo, _ = prof.bin_range(run[0])
            _, bhi = prof.bin_range(run[-1])
            mid = 0.5 * (blo + bhi)
            # skip if essentially the POC band
            if abs(mid - prof.poc) / max(prof.poc, 1e-9) < 0.002:
                continue
            zones.append(
                Zone(
                    symbol,
                    "hvn",
                    float(blo),
                    float(bhi),
                    len(run),
                    f"vp_hvn_bins_{run[0]}-{run[-1]}",
                    mid=mid,
                    strength=60.0 + 2.0 * len(run),
                )
            )
    if include_lvn:
        for i in prof.lvn_idx:
            blo, bhi = prof.bin_range(int(i))
            mid = 0.5 * (blo + bhi)
            zones.append(
                Zone(
                    symbol,
                    "lvn",
                    float(blo),
                    float(bhi),
                    1,
                    f"vp_lvn_bin_{int(i)}",
                    mid=mid,
                    strength=20.0,
                )
            )
    return zones


def _mark_confluence(zones: list[Zone], overlap_pct: float = 0.01) -> None:
    strong = [z for z in zones if z.zone_type in {"yearly_high", "yearly_low", "poc", "hvn"}]
    for z in zones:
        hits: list[str] = []
        for s in strong:
            if s is z:
                continue
            # overlap or mid proximity
            if z.hi < s.lo or z.lo > s.hi:
                if abs(z.mid - s.mid) / max(s.mid, 1e-9) > overlap_pct:
                    continue
            hits.append(s.zone_type)
        if hits:
            z.confluence = "+".join(sorted(set(hits)))
            z.strength += 15.0 * len(set(hits))


def compute_lt_zones(
    df: pd.DataFrame,
    symbol: str,
    *,
    include_lvn: bool = False,
    max_swing: int = 6,
) -> list[Zone]:
    zones: list[Zone] = []
    zones.extend(yearly_hl_zones(df, symbol))
    zones.extend(swing_sr_zones(df, symbol, max_zones=max_swing))
    zones.extend(vp_zones(df, symbol, include_lvn=include_lvn))
    _mark_confluence(zones)
    zones.sort(key=lambda z: (-z.strength, -z.touches, z.zone_type))
    return zones


def zones_to_frame(zones: list[Zone]) -> pd.DataFrame:
    rows = [asdict(z) for z in zones]
    cols = ["symbol", "zone_type", "lo", "hi", "touches", "source", "mid", "strength", "confluence"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)[cols]


def load_15m(symbol: str, in_dir: Path = DEFAULT_1M_DIR) -> pd.DataFrame:
    df = resample_symbol_1m(symbol, "15m", out_dir=in_dir)
    return df


def near_score(price: float, zones: list[Zone]) -> tuple[float, Optional[Zone]]:
    """Return (distance_fraction, zone). Prefer stronger types on ties."""
    if not np.isfinite(price) or price <= 0 or not zones:
        return float("inf"), None
    best: Optional[Zone] = None
    best_score = float("inf")
    best_d = float("inf")
    for z in zones:
        # distance to band (0 if inside)
        if z.lo <= price <= z.hi:
            d = 0.0
        else:
            d = min(abs(price - z.lo), abs(price - z.hi)) / price
        type_boost = {
            "yearly_high": 0.0,
            "yearly_low": 0.0,
            "poc": 0.0005,
            "hvn": 0.001,
            "swing_sr": 0.002,
            "lvn": 0.005,
        }.get(z.zone_type, 0.003)
        score = d + type_boost
        if score < best_score:
            best_score = score
            best_d = d
            best = z
    return best_d, best


def plot_15m_with_zones(
    symbol: str,
    bars: pd.DataFrame,
    zones: list[Zone],
    out_png: Path,
    *,
    title_note: str = "",
    max_draw: int = 12,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    if bars is None or bars.empty:
        raise ValueError(f"{symbol}: no 15m bars to plot")

    df = bars.copy()
    if "ts" in df.columns:
        ts = pd.to_datetime(df["ts"])
    else:
        ts = pd.to_datetime(df.index)
    o = df["open"].to_numpy(float) if "open" in df.columns else df["Open"].to_numpy(float)
    h = df["high"].to_numpy(float) if "high" in df.columns else df["High"].to_numpy(float)
    l = df["low"].to_numpy(float) if "low" in df.columns else df["Low"].to_numpy(float)
    c = df["close"].to_numpy(float) if "close" in df.columns else df["Close"].to_numpy(float)

    # Prefer drawing strong zones; always keep yearly + poc
    priority = {"yearly_high": 0, "yearly_low": 0, "poc": 1, "hvn": 2, "swing_sr": 3, "lvn": 4}
    draw_list = sorted(zones, key=lambda z: (priority.get(z.zone_type, 9), -z.strength))[:max_draw]

    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=120)
    x = np.arange(len(c))
    # candlesticks
    for i in range(len(c)):
        color = "#2e7d32" if c[i] >= o[i] else "#c62828"
        ax.plot([x[i], x[i]], [l[i], h[i]], color=color, linewidth=0.8, solid_capstyle="round")
        body_lo, body_hi = min(o[i], c[i]), max(o[i], c[i])
        if body_hi - body_lo < 1e-9:
            body_hi = body_lo + max(abs(c[i]) * 1e-4, 1e-4)
        ax.add_patch(
            Rectangle(
                (x[i] - 0.35, body_lo),
                0.7,
                body_hi - body_lo,
                facecolor=color,
                edgecolor=color,
                linewidth=0.4,
                alpha=0.9,
            )
        )

    # Zoom to 15m OHLC, but expand so nearby drawn zones (POC/HVN etc.) are not
    # clipped just below/above the candle window (e.g. SPY POC ~744 vs 15m ~762+).
    bar_lo = float(np.nanmin(l))
    bar_hi = float(np.nanmax(h))
    mid_px = 0.5 * (bar_lo + bar_hi) if bar_hi > bar_lo else (abs(bar_hi) or 1.0)
    near_gap = 0.04  # fraction of mid price: include zones within 4% of bar window
    y_min, y_max = bar_lo, bar_hi
    for z in draw_list:
        if z.hi < bar_lo:
            gap = (bar_lo - float(z.hi)) / mid_px
        elif z.lo > bar_hi:
            gap = (float(z.lo) - bar_hi) / mid_px
        else:
            gap = 0.0
        if gap <= near_gap:
            y_min = min(y_min, float(z.lo))
            y_max = max(y_max, float(z.hi))
    pad = (y_max - y_min) * 0.08 if y_max > y_min else abs(y_max) * 0.02
    ax.set_ylim(y_min - pad, y_max + pad)

    for z in draw_list:
        color, alpha = ZONE_COLORS.get(z.zone_type, ("#ad1457", 0.2))
        ax.axhspan(z.lo, z.hi, facecolor=color, alpha=alpha, edgecolor=color, linewidth=0.6)
        label = f"{z.zone_type} {z.mid:.2f}"
        if z.touches > 1 and z.zone_type == "swing_sr":
            label += f" (n={z.touches})"
        if z.confluence:
            label += f" [{z.confluence}]"
        ax.text(
            x[max(0, len(x) - max(3, len(x) // 12))],
            z.mid,
            label,
            fontsize=7,
            color=color,
            va="bottom",
            ha="right",
            clip_on=True,
            alpha=0.95,
        )

    # x ticks: sparse timestamps
    n = len(x)
    step = max(1, n // 8)
    tick_idx = list(range(0, n, step))
    if tick_idx[-1] != n - 1:
        tick_idx.append(n - 1)
    labels = []
    for i in tick_idx:
        t = ts.iloc[i] if hasattr(ts, "iloc") else ts[i]
        try:
            labels.append(pd.Timestamp(t).strftime("%m/%d %H:%M"))
        except Exception:
            labels.append(str(t)[:16])
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)

    last = float(c[-1])
    ax.axhline(last, color="#455a64", linestyle="--", linewidth=0.7, alpha=0.7)
    note = title_note or ""
    ax.set_title(
        f"{symbol} — 15m with long-term daily zones  |  last={last:.2f}  {note}",
        fontsize=11,
    )
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.25)
    # legend proxy
    from matplotlib.lines import Line2D

    handles = [
        Line2D([0], [0], color="#e91e8c", lw=6, alpha=0.4, label="Yearly H/L"),
        Line2D([0], [0], color="#f48fb1", lw=6, alpha=0.4, label="Swing S/R"),
        Line2D([0], [0], color="#1565c0", lw=6, alpha=0.4, label="POC"),
        Line2D([0], [0], color="#42a5f5", lw=6, alpha=0.4, label="HVN"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.9)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.92, bottom=0.14)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def _load_universe(path: Path) -> list[str]:
    syms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip().upper()
        if not s or s.startswith("#"):
            continue
        # csv header skip
        if s in {"SYMBOL", "TICKER", "SYM"}:
            continue
        # first column if csv
        s = s.split(",")[0].strip().upper()
        if s and (s.replace(".", "").replace("-", "").isalnum()):
            syms.append(s)
    # dedupe preserve order
    seen = set()
    out = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def scan_near_zones(
    symbols: Iterable[str],
    *,
    data_dir: Path,
    near_pct: float = 0.015,
    include_lvn: bool = False,
) -> list[dict]:
    rows: list[dict] = []
    for sym in symbols:
        try:
            daily = _load_daily(sym, data_dir)
        except Exception:
            continue
        if len(daily) < 60:
            continue
        zones = compute_lt_zones(daily, sym, include_lvn=include_lvn)
        # focus scan on strong types
        strong = [z for z in zones if z.zone_type in {"yearly_high", "yearly_low", "poc", "hvn", "swing_sr"}]
        price = float(daily.iloc[-1]["Close"])
        d, z = near_score(price, strong)
        if z is None or not np.isfinite(d) or d > near_pct:
            continue
        rows.append(
            {
                "symbol": sym,
                "close": price,
                "near_type": z.zone_type,
                "near_mid": z.mid,
                "near_lo": z.lo,
                "near_hi": z.hi,
                "dist_pct": d * 100.0,
                "touches": z.touches,
                "confluence": z.confluence,
                "strength": z.strength,
                "yearly_high": next((x.mid for x in zones if x.zone_type == "yearly_high"), float("nan")),
                "yearly_low": next((x.mid for x in zones if x.zone_type == "yearly_low"), float("nan")),
            }
        )
    rows.sort(key=lambda r: (r["dist_pct"], -r["strength"]))
    return rows


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


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def write_gallery_html(
    out_path: Path,
    examples: list[dict],
    *,
    stamp_name: str,
) -> None:
    head = (
        _sortable_th("Symbol", "text")
        + _sortable_th("Close", "num")
        + _sortable_th("Near type", "text")
        + _sortable_th("Zone mid", "num")
        + _sortable_th("Dist %", "num")
        + _sortable_th("Touches", "num")
        + _sortable_th("Confluence", "text")
        + _sortable_th("Chart", "text")
        + _sortable_th("Zones CSV", "text")
    )
    body_rows = []
    for ex in examples:
        chart_rel = ex.get("chart_rel", "")
        csv_rel = ex.get("csv_rel", "")
        chart_cell = (
            f'<a href="{html_mod.escape(chart_rel)}">PNG</a>' if chart_rel else "—"
        )
        csv_cell = f'<a href="{html_mod.escape(csv_rel)}">CSV</a>' if csv_rel else "—"
        body_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(ex['symbol'])}</td>"
            f"<td>{ex['close']:.2f}</td>"
            f"<td>{html_mod.escape(str(ex.get('near_type', '')))}</td>"
            f"<td>{float(ex.get('near_mid', 0)):.2f}</td>"
            f"<td>{float(ex.get('dist_pct', 0)):.3f}</td>"
            f"<td>{int(ex.get('touches', 0))}</td>"
            f"<td>{html_mod.escape(str(ex.get('confluence') or '—'))}</td>"
            f"<td>{chart_cell}</td>"
            f"<td>{csv_cell}</td>"
            "</tr>"
        )
    # zone definition reference table
    def_head = (
        _sortable_th("Type", "text")
        + _sortable_th("How computed", "text")
        + _sortable_th("Heuristic rank", "num")
    )
    defs = [
        ("yearly_high / yearly_low", "Rolling 252 trading-day max High / min Low; thin band ±pad", "1"),
        ("poc", "vec_zones daily VP (60 bars, 0.5% bins); POC = max-volume bin center", "2"),
        ("hvn", "VP bins with vol ≥ 50% of POC bin; contiguous runs merged", "2"),
        ("swing_sr", "Fractal pivots (k=3) clustered within 0.75%; keep ≥3 touches", "3"),
        ("lvn", "Interior VP valleys (&lt;20% POC); optional / weaker magnet", "4"),
    ]
    def_rows = "".join(
        f"<tr><td>{html_mod.escape(a)}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in defs
    )
    cards = []
    for ex in examples:
        chart_rel = ex.get("chart_rel", "")
        if not chart_rel:
            continue
        cards.append(
            f'<figure class="card">'
            f'<figcaption><strong>{html_mod.escape(ex["symbol"])}</strong> — '
            f'{html_mod.escape(str(ex.get("near_type","")))} @ {float(ex.get("near_mid",0)):.2f} '
            f'(dist {float(ex.get("dist_pct",0)):.2f}%)</figcaption>'
            f'<a href="{html_mod.escape(chart_rel)}">'
            f'<img src="{html_mod.escape(chart_rel)}" alt="{html_mod.escape(ex["symbol"])} 15m LT zones" loading="lazy"/>'
            f"</a></figure>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LT zones on 15m — {html_mod.escape(stamp_name)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1rem; color: #1a2332; background: #f7f5f8; }}
h1 {{ font-size: 1.35rem; margin: 0 0 0.35rem; }}
.sub {{ color: #546e7a; font-size: 0.92rem; margin-bottom: 1rem; }}
.note {{ background: #fce4ec; border-left: 4px solid #e91e8c; padding: 0.65rem 0.85rem; margin: 1rem 0; font-size: 0.9rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.88rem; }}
th, td {{ border: 1px solid #e0e0e0; padding: 0.4rem 0.55rem; text-align: left; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; background: #f3e5f5; }}
th.sortable-th:hover {{ background: #e1bee7; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: 0.35; font-size: 0.75em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\25B2"; opacity: 0.8; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\25BC"; opacity: 0.8; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-top: 1.25rem; }}
.card {{ background: #fff; margin: 0; padding: 0.5rem; border: 1px solid #eee; }}
.card img {{ width: 100%; height: auto; display: block; }}
.card figcaption {{ font-size: 0.85rem; margin-bottom: 0.4rem; }}
@media (max-width: 640px) {{
  body {{ margin: 0.6rem; }}
  table.sortable {{ display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
}}
</style>
</head>
<body>
<h1>Long-term daily S/R on 15-minute charts</h1>
<p class="sub">Stamp <code>{html_mod.escape(stamp_name)}</code> · Research/education only · Click column headers to sort · Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
<div class="note">
<strong>Strongest zones (heuristic):</strong> yearly high/low (rolling 252d) and HVN/POC usually outrank one-touch swings.
Multi-touch swing clusters (≥3) sit in the middle. Not a trading KEEP claim; no DailyRun wire.
</div>
<h2>Examples near a major zone</h2>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
<h2>Zone definitions</h2>
<table class="sortable">
<thead><tr>{def_head}</tr></thead>
<tbody>
{def_rows}
</tbody>
</table>
<h2>Charts</h2>
<div class="gallery">
{''.join(cards)}
</div>
{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def process_symbol(
    symbol: str,
    *,
    data_dir: Path,
    in_dir: Path,
    out_dir: Path,
    include_lvn: bool = False,
    near_info: Optional[dict] = None,
) -> dict:
    sym = symbol.upper()
    daily = _load_daily(sym, data_dir)
    zones = compute_lt_zones(daily, sym, include_lvn=include_lvn)
    zdf = zones_to_frame(zones)
    zones_dir = out_dir / "zones"
    charts_dir = out_dir / "charts"
    zones_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)
    csv_path = zones_dir / f"{sym}_lt_zones.csv"
    zdf.to_csv(csv_path, index=False)

    bars = load_15m(sym, in_dir)
    png_path = charts_dir / f"{sym}_15m_lt_zones.png"
    note = ""
    if near_info:
        note = f"near {near_info.get('near_type')} @ {float(near_info.get('near_mid', 0)):.2f}"
    if bars.empty:
        print(f"[warn] {sym}: no 15m bars (missing/sparse 1m under {in_dir})", flush=True)
        return {
            "symbol": sym,
            "close": float(daily.iloc[-1]["Close"]),
            "zones_n": len(zones),
            "csv_path": csv_path,
            "chart_path": None,
            "bars_n": 0,
            "error": "no_15m",
            **(near_info or {}),
        }
    plot_15m_with_zones(sym, bars, zones, png_path, title_note=note)
    print(f"{sym}: {len(zones)} zones, {len(bars)} 15m bars -> {png_path.name}", flush=True)
    out = {
        "symbol": sym,
        "close": float(daily.iloc[-1]["Close"]),
        "zones_n": len(zones),
        "csv_path": csv_path,
        "chart_path": png_path,
        "bars_n": len(bars),
        "csv_rel": f"zones/{csv_path.name}",
        "chart_rel": f"charts/{png_path.name}",
    }
    if near_info:
        out.update({k: near_info[k] for k in near_info if k not in out})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily LT zones → 15m overlay (research)")
    ap.add_argument("-s", "--symbols", default="", help="Comma-separated symbols")
    ap.add_argument(
        "--scan",
        action="store_true",
        help="Scan universe(s) for names near yearly H/L, POC/HVN, or multi-touch S/R",
    )
    ap.add_argument(
        "--universe",
        action="append",
        default=[],
        help="Universe file (repeatable). Default: BRT+RL+VZ when --scan",
    )
    ap.add_argument("--top", type=int, default=8, help="Max examples from scan")
    ap.add_argument("--near-pct", type=float, default=0.015, help="Near-zone threshold (fraction)")
    ap.add_argument("--data-dir", default=str(DEFAULT_DAILY))
    ap.add_argument("--in-dir", default=str(DEFAULT_1M_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_STAMP))
    ap.add_argument("--include-lvn", action="store_true")
    ap.add_argument(
        "--stamp",
        action="store_true",
        help="Write gallery.html under out-dir (implied when --scan writes examples)",
    )
    ap.add_argument("--also", default="AA,SPY", help="Always include these symbols in stamp examples")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols: list[str] = []
    if args.symbols:
        symbols = [p.strip().upper() for p in args.symbols.replace(";", ",").split(",") if p.strip()]

    scan_rows: list[dict] = []
    if args.scan:
        univ_paths = [Path(p) for p in args.universe] if args.universe else [
            _REPO / "drive" / "universes" / "BRT_universe.csv",
            _REPO / "drive" / "universes" / "RL_universe.csv",
            _REPO / "drive" / "universes" / "VZ_universe.csv",
        ]
        pool: list[str] = []
        for up in univ_paths:
            if up.is_file():
                pool.extend(_load_universe(up))
            else:
                print(f"[warn] missing universe {up}", flush=True)
        # dedupe
        seen = set()
        pool_u = []
        for s in pool:
            if s not in seen:
                seen.add(s)
                pool_u.append(s)
        print(
            f"Scanning {len(pool_u)} symbols for near-zone (<= {args.near_pct*100:.2f}%)...",
            flush=True,
        )
        scan_rows = scan_near_zones(
            pool_u, data_dir=data_dir, near_pct=float(args.near_pct), include_lvn=bool(args.include_lvn)
        )
        scan_path = out_dir / "scan_near_zones.csv"
        pd.DataFrame(scan_rows).to_csv(scan_path, index=False)
        print(f"Scan hits: {len(scan_rows)} -> {scan_path}", flush=True)
        for r in scan_rows[: int(args.top)]:
            if r["symbol"] not in symbols:
                symbols.append(r["symbol"])

    # Always include educational anchors when stamping
    if args.stamp or args.scan:
        for s in [p.strip().upper() for p in args.also.replace(";", ",").split(",") if p.strip()]:
            if s not in symbols:
                symbols.append(s)

    if not symbols:
        print("No symbols. Pass -s or --scan.", file=sys.stderr)
        return 2

    near_by = {r["symbol"]: r for r in scan_rows}
    examples: list[dict] = []
    for sym in symbols:
        try:
            ex = process_symbol(
                sym,
                data_dir=data_dir,
                in_dir=in_dir,
                out_dir=out_dir,
                include_lvn=bool(args.include_lvn),
                near_info=near_by.get(sym),
            )
            examples.append(ex)
        except Exception as e:
            print(f"[error] {sym}: {e}", flush=True)
            examples.append({"symbol": sym, "error": str(e), "close": float("nan")})

    if args.stamp or args.scan:
        # Prefer a balanced gallery: yearly H/L first, then POC/HVN, then rest
        by_sym = {e["symbol"]: e for e in examples if e.get("chart_path")}
        # Enrich from scan
        for r in scan_rows:
            if r["symbol"] in by_sym:
                by_sym[r["symbol"]] = {**r, **by_sym[r["symbol"]]}

        def _enrich_near(e: dict) -> dict:
            if "near_type" in e:
                return e
            if not e.get("csv_path"):
                return e
            try:
                zdf = pd.read_csv(e["csv_path"])
                price = float(e["close"])
                zdf = zdf.copy()
                zdf["dist"] = zdf.apply(
                    lambda row: 0.0
                    if row["lo"] <= price <= row["hi"]
                    else min(abs(price - row["lo"]), abs(price - row["hi"])) / max(price, 1e-9),
                    axis=1,
                )
                strong = zdf[
                    zdf["zone_type"].isin(
                        ["yearly_high", "yearly_low", "poc", "hvn", "swing_sr"]
                    )
                ]
                if strong.empty:
                    return e
                best = strong.sort_values("dist").iloc[0]
                return {
                    **e,
                    "near_type": best["zone_type"],
                    "near_mid": float(best["mid"]),
                    "dist_pct": float(best["dist"]) * 100,
                    "touches": int(best["touches"]),
                    "confluence": best.get("confluence") or "",
                }
            except Exception:
                return e

        ranked = [_enrich_near(by_sym[s]) for s in by_sym]
        buckets = {
            "yearly_high": [],
            "yearly_low": [],
            "poc": [],
            "hvn": [],
            "swing_sr": [],
            "other": [],
        }
        for e in ranked:
            nt = str(e.get("near_type") or "other")
            buckets.get(nt, buckets["other"]).append(e)
        for b in buckets.values():
            b.sort(
                key=lambda x: float(x["dist_pct"])
                if x.get("dist_pct") is not None and str(x.get("dist_pct")) != ""
                else 99.0
            )

        gallery_examples: list[dict] = []
        # Cap: up to 4 yearly_high, 2 yearly_low, 3 poc, 2 hvn, 2 swing, then fill
        quotas = [
            ("yearly_high", 4),
            ("yearly_low", 2),
            ("poc", 3),
            ("hvn", 2),
            ("swing_sr", 2),
        ]
        used: set[str] = set()
        for key, n in quotas:
            for e in buckets.get(key, [])[:n]:
                if e["symbol"] not in used:
                    gallery_examples.append(e)
                    used.add(e["symbol"])
        # Always include AA / SPY / NVDA anchors if charts exist
        for anchor in ("AA", "SPY", "NVDA"):
            if anchor in by_sym and anchor not in used:
                gallery_examples.append(_enrich_near(by_sym[anchor]))
                used.add(anchor)
        # Fill to top+anchors from remaining scan order
        for e in ranked:
            if len(gallery_examples) >= max(int(args.top), 10) + 3:
                break
            if e["symbol"] not in used:
                gallery_examples.append(e)
                used.add(e["symbol"])

        write_gallery_html(out_dir / "gallery.html", gallery_examples, stamp_name=out_dir.name)
        print(f"Wrote {out_dir / 'gallery.html'} ({len(gallery_examples)} examples)", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
