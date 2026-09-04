#!/usr/bin/env python3
"""HTML chart pack: M/W/D trendlines + HV6m + house VZ HL zone.

Reads a frozen trendline stamp (segments.json from gen_trendlines_tos_studies.py)
and writes per-symbol PNGs + an index HTML under stamp/charts/.

VZ zone drawn = house Vol Zone HL: rolling 126-bar max-volume day's High–Low
for the *current* winner (tools/vol_zone_break_retest.build_zones, HL-only as in
rocket_vz). OC of the same day drawn lightly for dual-zone context.
HV6m gold box comes from segments.json (calendar 6m max-vol High–Low).

Examples:
  python tools/gen_trendlines_charts_html.py
  python tools/gen_trendlines_charts_html.py --stamp-dir drive/paul_studies/trendlines_opens_spy_20260902
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "tools"))

from vol_zone_break_retest import Zone, build_zones, load_ohlcv  # noqa: E402

DEFAULT_STAMP = _REPO / "drive" / "paul_studies" / "trendlines_opens_latest"
LOOKBACK_DAYS = 126  # house VZ HL
CHART_MONTHS = 6

SMA_STYLE = {
    20: {"color": "#ec407a", "lw": 0.9, "label": "SMA20"},
    50: {"color": "#ef6c00", "lw": 0.9, "label": "SMA50"},
    100: {"color": "#6d4c41", "lw": 0.9, "label": "SMA100"},
}

TF_STYLE = {
    "monthly": {"color": "#ba68c8", "lw": 1.8, "label": "M"},
    "weekly": {"color": "#ff9800", "lw": 1.5, "label": "W"},
    "daily": {"color": "#00bcd4", "lw": 1.2, "label": "D"},
}
HV6M_FACE = "#d4a84b"
VZ_HL_FACE = "#7e57c2"
VZ_OC_FACE = "#42a5f5"

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
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _parse_ymd(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def nearest_hl_zones(zones: list[Zone], price: float) -> tuple[Zone | None, Zone | None]:
    """Nearest mature VZ HL zone above/below *price* (house build_zones HL bands)."""
    hl = [z for z in zones if z.kind == "HL"]
    above = [z for z in hl if z.lo > price]
    below = [z for z in hl if z.hi < price]
    nearest_above = min(above, key=lambda z: z.lo - price) if above else None
    nearest_below = max(below, key=lambda z: z.hi) if below else None
    return nearest_above, nearest_below


def _zone_band_label(z: Zone | None) -> str:
    if z is None:
        return "—"
    day = pd.Timestamp(z.max_vol_date).date()
    return f"{day} {z.lo:.2f}–{z.hi:.2f}"


def current_vz_zones(df: pd.DataFrame, lookback: int = LOOKBACK_DAYS) -> dict[str, Zone | None]:
    """Return current rolling-winner HL (house) and matching OC if present."""
    out: dict[str, Zone | None] = {"HL": None, "OC": None}
    if len(df) <= lookback:
        return out
    zones = build_zones(df, lookback)
    last_i = len(df) - 1
    # Prefer zones still the rolling winner as of last bar
    active = [z for z in zones if z.last_winner_idx == last_i]
    if not active:
        # fallback: most recent created HL/OC
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


def _line_y_at_x(d1: date, p1: float, d2: date, p2: float, x: date) -> float:
    t1 = mdates.date2num(d1)
    t2 = mdates.date2num(d2)
    tx = mdates.date2num(x)
    if abs(t2 - t1) < 1e-12:
        return p2
    return p1 + (p2 - p1) * (tx - t1) / (t2 - t1)


def _draw_candles(ax, dates, o, h, l, c) -> None:
    x = mdates.date2num(dates)
    up = c >= o
    # wicks
    ax.vlines(x, l, h, color="#78909c", lw=0.45, zorder=2)
    body_lo = np.minimum(o, c)
    body_hi = np.maximum(o, c)
    height = np.maximum(body_hi - body_lo, np.maximum(np.abs(c) * 1e-4, 1e-4))
    for i in range(len(x)):
        color = "#2e7d32" if up[i] else "#c62828"
        ax.add_patch(
            Rectangle(
                (x[i] - 0.32, body_lo[i]),
                0.64,
                height[i],
                facecolor=color,
                edgecolor=color,
                linewidth=0.3,
                alpha=0.9,
                zorder=3,
            )
        )


def _format_header_line(sym_info: dict[str, Any] | None) -> str:
    if not sym_info:
        return ""
    systems = sym_info.get("systems") or []
    sys_txt = ", ".join(systems) if systems else "—"
    scan = sym_info.get("scanner_systems") or []
    scan_txt = ", ".join(scan) if scan else ""
    pd_raw = sym_info.get("purchase_date") or ""
    ep = sym_info.get("entry_price")
    src = sym_info.get("price_source") or ""
    port = sym_info.get("in_portfolio")
    if ep is not None and pd_raw:
        buy = f"{pd_raw} @ {float(ep):.2f}"
        if port:
            buy += " (our book)"
        elif src:
            buy += f" ({src})"
    elif pd_raw:
        buy = pd_raw
    else:
        buy = "—"
    parts = [f"Open in: {sys_txt}"]
    if scan_txt:
        parts.append(f"Scanner: {scan_txt}")
    parts.append(f"Buy: {buy}")
    return "  ·  ".join(parts)


def plot_symbol_chart(
    symbol: str,
    df: pd.DataFrame,
    meta: dict[str, Any],
    vz: dict[str, Zone | None],
    all_zones: list[Zone],
    sym_info: dict[str, Any] | None,
    out_png: Path,
) -> dict[str, Any]:
    """Plot last ~6 calendar months; return summary fields for HTML."""
    end_ts = pd.Timestamp(df["Date"].iloc[-1]).normalize()
    start_ts = (end_ts - pd.DateOffset(months=CHART_MONTHS)).normalize()
    plot_df = df[(df["Date"] >= start_ts) & (df["Date"] <= end_ts)].copy()
    if plot_df.empty:
        raise ValueError(f"{symbol}: empty plot window")

    # SMA on full history, then slice to plot window
    close_full = df["Close"].astype(float)
    sma_lines: dict[int, pd.Series] = {}
    for period in (20, 50, 100):
        sma_lines[period] = close_full.rolling(period, min_periods=period).mean()

    plot_mask = (df["Date"] >= start_ts) & (df["Date"] <= end_ts)

    plot_df = plot_df.copy()
    plot_df["Date"] = pd.to_datetime(plot_df["Date"])
    dates = plot_df["Date"]
    o = plot_df["Open"].to_numpy(float)
    h = plot_df["High"].to_numpy(float)
    l = plot_df["Low"].to_numpy(float)
    c = plot_df["Close"].to_numpy(float)
    win_start = dates.iloc[0].date()
    win_end = dates.iloc[-1].date()

    fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=110)
    _draw_candles(ax, dates, o, h, l, c)

    y_extra: list[float] = []
    for period, style in SMA_STYLE.items():
        sma_slice = sma_lines[period][plot_mask]
        if sma_slice.notna().any():
            ax.plot(
                dates,
                sma_slice.to_numpy(float),
                color=style["color"],
                lw=style["lw"],
                alpha=0.85,
                zorder=4,
                label=style["label"],
            )
            y_extra.extend(float(x) for x in sma_slice.dropna().tolist())

    # --- VZ HL (house) + light OC ---
    vz_hl = vz.get("HL")
    vz_oc = vz.get("OC")

    def _span_zone(z: Zone, face: str, alpha: float, label: str) -> None:
        # Draw from max-vol day (or created_on if later) through last bar —
        # same horizontal gating idea as HV6m / ToS zone boxes.
        z_day = pd.Timestamp(z.max_vol_date).date()
        d0 = max(win_start, z_day)
        d1 = win_end
        if d0 > d1:
            return
        x0 = mdates.date2num(d0)
        x1 = mdates.date2num(d1) + 0.6
        ax.add_patch(
            Rectangle(
                (x0, z.lo),
                x1 - x0,
                z.hi - z.lo,
                facecolor=face,
                edgecolor=face,
                alpha=alpha,
                linewidth=0.8,
                zorder=1,
                label=label,
            )
        )
        if win_start <= z_day <= win_end:
            ax.axvline(z_day, color=face, ls=":", lw=1.0, alpha=0.7, zorder=4)
        y_extra.extend([z.lo, z.hi])

    if vz_hl is not None:
        _span_zone(vz_hl, VZ_HL_FACE, 0.16, f"VZ HL {pd.Timestamp(vz_hl.max_vol_date).date()}")
    if vz_oc is not None:
        _span_zone(vz_oc, VZ_OC_FACE, 0.10, f"VZ OC {pd.Timestamp(vz_oc.max_vol_date).date()}")

    # --- HV6m gold box (from segments freeze) ---
    hv = meta.get("hv6m") or {}
    if hv and hv.get("day"):
        hv_day = _parse_ymd(str(hv["day"]))
        hv_hi = float(hv["high"])
        hv_lo = float(hv["low"])
        # Match ToS: from HV day through last bar
        box_x0 = mdates.date2num(max(hv_day, win_start))
        box_x1 = mdates.date2num(win_end) + 0.6
        if box_x1 > box_x0:
            ax.add_patch(
                Rectangle(
                    (box_x0, hv_lo),
                    box_x1 - box_x0,
                    hv_hi - hv_lo,
                    facecolor=HV6M_FACE,
                    edgecolor=HV6M_FACE,
                    alpha=0.22,
                    linewidth=1.0,
                    zorder=1.5,
                    label=f"HV6m {hv_day}",
                )
            )
            y_extra.extend([hv_lo, hv_hi])
            if win_start <= hv_day <= win_end:
                ax.axvline(hv_day, color=HV6M_FACE, ls="--", lw=1.1, alpha=0.85, zorder=4)

    # --- Trendline segments (extend right to chart end) ---
    segs = meta.get("segments") or []
    for seg in segs:
        tf = str(seg.get("timeframe", "daily"))
        side = str(seg.get("side", "support"))
        d1 = _parse_ymd(str(seg["d1"]))
        d2 = _parse_ymd(str(seg["d2"]))
        p1 = float(seg["p1"])
        p2 = float(seg["p2"])
        style = TF_STYLE.get(tf, TF_STYLE["daily"])
        # Draw from max(d1, win_start) through win_end (extend right)
        x_left = max(d1, win_start)
        x_right = win_end
        if x_left >= x_right and d2 < win_start:
            # entire segment before window — still extend into window if slope continues
            x_left = win_start
        y_left = _line_y_at_x(d1, p1, d2, p2, x_left)
        y_right = _line_y_at_x(d1, p1, d2, p2, x_right)
        ls = "-" if side == "support" else "--"
        ax.plot(
            [x_left, x_right],
            [y_left, y_right],
            color=style["color"],
            lw=style["lw"],
            ls=ls,
            solid_capstyle="round",
            zorder=5,
            alpha=0.95,
        )
        # pivot markers if inside window
        for dd, pp in ((d1, p1), (d2, p2)):
            if win_start <= dd <= win_end:
                ax.scatter(
                    [dd],
                    [pp],
                    s=18,
                    color=style["color"],
                    zorder=6,
                    edgecolors="white",
                    linewidths=0.4,
                )
        y_extra.extend([y_left, y_right])

    # Y limits: price window + nearby overlays
    bar_lo, bar_hi = float(np.nanmin(l)), float(np.nanmax(h))
    mid = 0.5 * (bar_lo + bar_hi) if bar_hi > bar_lo else (abs(bar_hi) or 1.0)
    y_min, y_max = bar_lo, bar_hi
    for y in y_extra:
        if not np.isfinite(y):
            continue
        gap = 0.0
        if y < bar_lo:
            gap = (bar_lo - y) / mid
        elif y > bar_hi:
            gap = (y - bar_hi) / mid
        if gap <= 0.35:  # include overlays within 35% of mid
            y_min = min(y_min, y)
            y_max = max(y_max, y)
    pad = (y_max - y_min) * 0.08 if y_max > y_min else abs(y_max) * 0.02
    ax.set_ylim(y_min - pad, y_max + pad)

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_xlim(dates.iloc[0] - pd.Timedelta(days=2), dates.iloc[-1] + pd.Timedelta(days=3))
    ax.grid(True, alpha=0.25)
    ax.set_ylabel("Price")
    last = float(c[-1])
    ax.axhline(last, color="#546e7a", ls=":", lw=0.7, alpha=0.6)

    zone_above, zone_below = nearest_hl_zones(all_zones, last)
    if zone_above is not None:
        ax.axhspan(zone_above.lo, zone_above.hi, color="#c62828", alpha=0.08, zorder=0)
        ax.axhline(zone_above.lo, color="#c62828", ls="--", lw=0.8, alpha=0.55)
    if zone_below is not None:
        ax.axhspan(zone_below.lo, zone_below.hi, color="#2e7d32", alpha=0.08, zorder=0)
        ax.axhline(zone_below.hi, color="#2e7d32", ls="--", lw=0.8, alpha=0.55)

    vz_note = "—"
    if vz_hl is not None:
        vz_note = (
            f"HL {pd.Timestamp(vz_hl.max_vol_date).date()} "
            f"{vz_hl.lo:.2f}–{vz_hl.hi:.2f}"
        )
    hv_note = "—"
    if hv and hv.get("day"):
        hv_note = f"{hv['day']} {float(hv['low']):.2f}–{float(hv['high']):.2f}"

    header = _format_header_line(sym_info)
    near_note = (
        f"Nearest HL above: {_zone_band_label(zone_above)}   ·   "
        f"Nearest HL below: {_zone_band_label(zone_below)}"
    )
    title_lines = [
        f"{symbol}  |  last 6m through {win_end}  |  last={last:.2f}",
    ]
    if header:
        title_lines.append(header)
    title_lines.append(
        f"VZ HL (126d): {vz_note}   ·   HV6m: {hv_note}   ·   {near_note}"
    )
    ax.set_title("\n".join(title_lines), fontsize=9.5)

    handles = [
        Line2D([0], [0], color="#ba68c8", lw=2, label="M trendline"),
        Line2D([0], [0], color="#ff9800", lw=2, label="W trendline"),
        Line2D([0], [0], color="#00bcd4", lw=2, label="D trendline"),
        Line2D([0], [0], color="#d4a84b", lw=6, alpha=0.45, label="HV6m box"),
        Line2D([0], [0], color="#7e57c2", lw=6, alpha=0.45, label="VZ HL zone"),
        Line2D([0], [0], color="#42a5f5", lw=6, alpha=0.35, label="VZ OC (context)"),
        Line2D([0], [0], color="#ec407a", lw=1.2, label="SMA20"),
        Line2D([0], [0], color="#ef6c00", lw=1.2, label="SMA50"),
        Line2D([0], [0], color="#6d4c41", lw=1.2, label="SMA100"),
        Line2D([0], [0], color="#c62828", lw=1.2, ls="--", label="Nearest HL above"),
        Line2D([0], [0], color="#2e7d32", lw=1.2, ls="--", label="Nearest HL below"),
        Line2D([0], [0], color="#78909c", lw=1.5, ls="-", label="Support solid / Res dashed"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=6.5, framealpha=0.9, ncol=2)

    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)

    return {
        "symbol": symbol,
        "last": last,
        "win_start": str(win_start),
        "win_end": str(win_end),
        "n_bars": int(len(plot_df)),
        "n_segs": int(len(segs)),
        "hv6m_day": str(hv.get("day") or ""),
        "vz_hl_day": str(pd.Timestamp(vz_hl.max_vol_date).date()) if vz_hl else "",
        "vz_hl_lo": float(vz_hl.lo) if vz_hl else None,
        "vz_hl_hi": float(vz_hl.hi) if vz_hl else None,
        "vz_oc_day": str(pd.Timestamp(vz_oc.max_vol_date).date()) if vz_oc else "",
        "systems": ", ".join(sym_info.get("systems") or []) if sym_info else "",
        "scanner_systems": ", ".join(sym_info.get("scanner_systems") or []) if sym_info else "",
        "purchase_date": str(sym_info.get("purchase_date") or "") if sym_info else "",
        "entry_price": sym_info.get("entry_price") if sym_info else None,
        "price_source": str(sym_info.get("price_source") or "") if sym_info else "",
        "in_portfolio": bool(sym_info.get("in_portfolio")) if sym_info else False,
        "zone_above": _zone_band_label(zone_above),
        "zone_below": _zone_band_label(zone_below),
        "header_line": _format_header_line(sym_info),
        "png": out_png.name,
    }


def write_index_html(
    out_dir: Path,
    stamp: str,
    rows: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> Path:
    rows_sorted = sorted(rows, key=lambda r: r["symbol"])
    nav_links = " · ".join(
        f'<a href="#{html_mod.escape(r["symbol"])}">{html_mod.escape(r["symbol"])}</a>'
        for r in rows_sorted
    )
    table_rows = []
    for r in rows_sorted:
        vz = "—"
        if r.get("vz_hl_day"):
            vz = (
                f'{html_mod.escape(r["vz_hl_day"])} '
                f'{r["vz_hl_lo"]:.2f}–{r["vz_hl_hi"]:.2f}'
            )
        buy = "—"
        if r.get("purchase_date"):
            ep = r.get("entry_price")
            buy = f'{html_mod.escape(r["purchase_date"])}'
            if ep is not None:
                buy += f" @ {float(ep):.2f}"
            if r.get("in_portfolio"):
                buy += " (our book)"
            elif r.get("price_source"):
                buy += f' ({html_mod.escape(r["price_source"])})'
        table_rows.append(
            "<tr>"
            f'<td><a href="#{html_mod.escape(r["symbol"])}">{html_mod.escape(r["symbol"])}</a></td>'
            f'<td>{html_mod.escape(r.get("systems") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("scanner_systems") or "—")}</td>'
            f"<td>{buy}</td>"
            f'<td>{html_mod.escape(r["win_start"])}</td>'
            f'<td>{html_mod.escape(r["win_end"])}</td>'
            f'<td>{r["last"]:.2f}</td>'
            f'<td>{html_mod.escape(r.get("zone_above") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("zone_below") or "—")}</td>'
            f'<td>{r["n_segs"]}</td>'
            f'<td>{html_mod.escape(r.get("hv6m_day") or "—")}</td>'
            f"<td>{vz}</td>"
            f'<td><a href="{html_mod.escape(r["png"])}">PNG</a></td>'
            "</tr>"
        )

    chart_blocks = []
    for r in rows_sorted:
        hdr = html_mod.escape(r.get("header_line") or "")
        hdr_p = f'<p class="meta">{hdr}</p>' if hdr else ""
        chart_blocks.append(
            f'<section class="chart" id="{html_mod.escape(r["symbol"])}">'
            f'<h2>{html_mod.escape(r["symbol"])}</h2>'
            f"{hdr_p}"
            f'<p class="meta">Window {html_mod.escape(r["win_start"])} → '
            f'{html_mod.escape(r["win_end"])} · last={r["last"]:.2f} · '
            f'Nearest HL above={html_mod.escape(r.get("zone_above") or "—")} · '
            f'below={html_mod.escape(r.get("zone_below") or "—")} · '
            f'segs={r["n_segs"]} · HV6m={html_mod.escape(r.get("hv6m_day") or "—")} · '
            f'VZ HL={html_mod.escape(r.get("vz_hl_day") or "—")}</p>'
            f'<a href="{html_mod.escape(r["png"])}">'
            f'<img src="{html_mod.escape(r["png"])}" alt="{html_mod.escape(r["symbol"])} chart" loading="lazy"/>'
            f"</a></section>"
        )

    skip_html = ""
    if skipped:
        items = "".join(
            f"<li><code>{html_mod.escape(s['symbol'])}</code>: {html_mod.escape(s['reason'])}</li>"
            for s in skipped
        )
        skip_html = f"<h2>Skipped</h2><ul>{items}</ul>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Trendlines + VZ charts — {html_mod.escape(stamp)}</title>
<style>
:root {{
  --bg: #f6f4ef;
  --ink: #1c2430;
  --muted: #5c6b7a;
  --card: #fff;
  --line: #d5d0c6;
  --accent: #2f5d50;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 1.25rem 1.5rem 3rem;
  font-family: "Segoe UI", "Helvetica Neue", sans-serif;
  color: var(--ink); background: var(--bg); line-height: 1.45;
}}
h1 {{ font-size: 1.45rem; margin: 0 0 0.35rem; color: var(--accent); }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
.sub, .meta {{ color: var(--muted); font-size: 0.92rem; }}
.nav {{
  position: sticky; top: 0; z-index: 5;
  background: rgba(246,244,239,0.95); backdrop-filter: blur(6px);
  border-bottom: 1px solid var(--line);
  padding: 0.55rem 0; margin: 0.75rem 0 1rem;
  font-size: 0.82rem; line-height: 1.7; max-height: 7.5rem; overflow: auto;
}}
.nav a {{ color: var(--accent); text-decoration: none; margin-right: 0.15rem; }}
.nav a:hover {{ text-decoration: underline; }}
table.sortable {{
  width: 100%; border-collapse: collapse; background: var(--card);
  font-size: 0.88rem; margin: 0.5rem 0 1.25rem;
}}
th, td {{ border: 1px solid var(--line); padding: 0.35rem 0.5rem; text-align: left; }}
th.sortable-th {{ cursor: pointer; user-select: none; background: #ece8df; }}
th.sortable-th .sort-ind::after {{ content: " ↕"; opacity: 0.35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " ↑"; opacity: 0.9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " ↓"; opacity: 0.9; }}
section.chart {{
  margin: 1.25rem 0 2rem; padding: 0.75rem 0.85rem 1rem;
  background: var(--card); border: 1px solid var(--line);
}}
section.chart img {{
  width: 100%; max-width: 1100px; height: auto; display: block;
  border: 1px solid var(--line);
}}
.defs {{
  background: var(--card); border: 1px solid var(--line);
  padding: 0.75rem 1rem; margin: 0.75rem 0 1rem; font-size: 0.9rem;
}}
.defs code {{ font-size: 0.85em; }}
.top {{ font-size: 0.85rem; }}
.top a {{ color: var(--accent); }}
</style>
</head>
<body>
<h1>Trendlines + HV6m + VZ zone charts</h1>
<p class="sub">Stamp <code>{html_mod.escape(stamp)}</code> · {len(rows_sorted)} charts ·
generated {datetime.now().strftime("%Y-%m-%d %H:%M")} · offline PNGs ·
Click column headers to sort · <a class="top" href="#charts">Jump to charts</a></p>

<div class="defs">
<strong>Overlays</strong>
<ul>
<li><b>M / W / D trendlines</b> — frozen fractal support (solid) &amp; resistance (dashed) from
<code>segments.json</code> / <code>gen_trendlines_tos_studies.py</code> (same geometry as ToS studies).</li>
<li><b>HV6m</b> — gold box: max-Volume day High–Low in last 6 <em>calendar</em> months (from stamp),
drawn from HV day through last bar.</li>
<li><b>VZ zone (house)</b> — purple band: Vol Zone <b>HL</b> for the <em>current</em> rolling
<strong>126 trading-day</strong> max-volume winner (<code>build_zones</code> in
<code>tools/vol_zone_break_retest.py</code>; house <code>rocket_vz</code> is HL-only).
Light blue = same day's <b>OC</b> band for dual-zone context (not the house entry filter).</li>
<li><b>SMA20 / SMA50 / SMA100</b> — simple moving averages on daily close (pink / orange / brown).</li>
<li><b>Nearest HL above / below</b> — closest house Vol Zone <b>HL</b> band (126d history via
<code>build_zones</code>) with zone low above last close (above) or zone high below last close (below).
Dashed red/green guides on chart.</li>
<li>HV6m (calendar) and VZ HL (126 bars) often match but can differ on ties / window edges.</li>
</ul>
</div>

<nav class="nav" aria-label="Symbol navigation">{nav_links}</nav>

<table class="sortable">
<thead><tr>
{_sortable_th("Symbol", "text")}
{_sortable_th("Systems", "text")}
{_sortable_th("Scanner", "text")}
{_sortable_th("Buy", "text")}
{_sortable_th("Window start", "date")}
{_sortable_th("Window end", "date")}
{_sortable_th("Last", "num")}
{_sortable_th("HL above", "text")}
{_sortable_th("HL below", "text")}
{_sortable_th("Segs", "num")}
{_sortable_th("HV6m day", "date")}
{_sortable_th("VZ HL", "text")}
{_sortable_th("PNG", "text")}
</tr></thead>
<tbody>
{"".join(table_rows)}
</tbody>
</table>

{skip_html}

<h2 id="charts">Charts</h2>
{"".join(chart_blocks)}

{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stamp-dir",
        type=Path,
        default=DEFAULT_STAMP,
        help="Trendline stamp with segments.json",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output charts dir (default: stamp-dir/charts)",
    )
    ap.add_argument("--limit", type=int, default=0, help="Optional symbol cap for smoke")
    ap.add_argument(
        "--symbol-meta",
        type=Path,
        default=None,
        help="JSON from trendlines_opens_universe (systems, buy date/price)",
    )
    args = ap.parse_args()

    stamp_dir = args.stamp_dir if args.stamp_dir.is_absolute() else _REPO / args.stamp_dir
    seg_path = stamp_dir / "segments.json"
    if not seg_path.is_file():
        print(f"[error] missing {seg_path}", file=sys.stderr)
        return 1

    open_meta: dict[str, Any] = {}
    meta_path = args.symbol_meta or (stamp_dir / "symbol_meta.json")
    if meta_path.is_file():
        open_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    payload = json.loads(seg_path.read_text(encoding="utf-8"))
    symbols_meta: dict[str, Any] = payload.get("symbols") or {}
    stamp = str(payload.get("stamp") or stamp_dir.name)
    out_dir = args.out_dir or (stamp_dir / "charts")
    if not out_dir.is_absolute():
        out_dir = _REPO / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    syms = sorted(symbols_meta.keys())
    if args.limit and args.limit > 0:
        syms = syms[: args.limit]

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    t0 = time.time()
    for i, sym in enumerate(syms, 1):
        meta = symbols_meta[sym]
        data_note = meta.get("data_note") or ""
        csv_path = Path(data_note) if data_note else _REPO / "data" / "newdata" / "data" / f"{sym}.csv"
        if not csv_path.is_file():
            alt = _REPO / "data" / "newdata" / "data" / f"{sym}.csv"
            if alt.is_file():
                csv_path = alt
            else:
                skipped.append({"symbol": sym, "reason": f"missing OHLC {csv_path}"})
                print(f"[skip] {sym}: missing OHLC")
                continue
        try:
            df = load_ohlcv(csv_path)
            vz = current_vz_zones(df, LOOKBACK_DAYS)
            all_zones = build_zones(df, LOOKBACK_DAYS) if len(df) > LOOKBACK_DAYS else []
            sym_info = open_meta.get(sym)
            png = out_dir / f"{sym}_tl_vz_6m.png"
            info = plot_symbol_chart(sym, df, meta, vz, all_zones, sym_info, png)
            rows.append(info)
            print(
                f"[{i}/{len(syms)}] {sym}  bars={info['n_bars']}  "
                f"vz_hl={info.get('vz_hl_day') or '—'}  "
                f"above={info.get('zone_above') or '—'}  -> {png.name}"
            )
        except Exception as exc:  # noqa: BLE001 — batch resilience
            skipped.append({"symbol": sym, "reason": str(exc)})
            print(f"[skip] {sym}: {exc}")

    index = write_index_html(out_dir, stamp, rows, skipped)
    # Also drop a short README for the charts folder
    (out_dir / "README.md").write_text(
        f"""# Charts — {stamp}

- **Index:** `index.html`
- **N charts:** {len(rows)}
- **Skipped:** {len(skipped)}
- **VZ zone drawn:** house Vol Zone **HL** — High–Low of the current rolling **126 trading-day**
  max-volume winner (`tools/vol_zone_break_retest.build_zones`). Light OC band = same day for context.
- **HV6m:** calendar-6m max-vol High–Low box from parent `segments.json`.
- **Trendlines:** M/W/D fractal support/resistance from `segments.json`.

Generated {datetime.now().isoformat(timespec="seconds")}.
""",
        encoding="utf-8",
    )

    elapsed = time.time() - t0
    print(f"\nDone: {len(rows)} charts, {len(skipped)} skipped in {elapsed:.1f}s")
    print(f"HTML: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
