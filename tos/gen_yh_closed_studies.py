#!/usr/bin/env python3
"""
Generate ThinkorSwim studies for Year-High (YH) Closed trades — single stamp.

Per symbol (MarkTen / run_yh.bat universe by default):
  - SMA20 (red), SMA50 (white), SMA100 (yellow), SMA200 (purple/violet)
    Same visual DNA as tos/gen_rl_closed_studies.py (no RL dip/expansion band).
  - YH zone clouds from Closed (+ Open) unique zones:
        lo/hi from ZONE_LOW/ZONE_HIGH when present, else center ± band_pct
        Cloud starts at MATURITY_DATE; colors cycle O-Y-B-C-V (ROYGBIV minus R/G)
  - BO bubbles at BREAKOUT_DATE (matching zone color)
  - CAD / retest bubbles at CLOSE_ABOVE_DATE (cyan "CAD >")
  - Green In/Out arrows+bubbles from Closed (open In from Open CSV)
  - Red stop-loss segments: STOP_PRICE from open..close (open → forward)
  - Cyan target segments: TARGET_PRICE from open..close (toggleable)

Output (system-owned folder; does not write into RL studies):
  drive/paul_studies/YH/closed_<stamp>/YH_<SYM>_closed_<stamp>.ts

Usage:
  python tos/gen_yh_closed_studies.py
  python tos/gen_yh_closed_studies.py --stamp 260731071559
  python tos/gen_yh_closed_studies.py -o drive/paul_studies/YH/closed_260731071559
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_TOS_DIR = Path(__file__).resolve().parent
_ROOT = _TOS_DIR.parent
if str(_TOS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOS_DIR))

from ts_common import color_name, event_hit_expr, zone_color  # noqa: E402

DRIVE = _ROOT / "drive"
STUDIES_ROOT = DRIVE / "paul_studies" / "YH"
# Same default universe as run_yh.bat / MarkTen-style Mag7+AU/AMD/NFLX.
DEFAULT_SYMBOLS = [
    "AAPL",
    "AMD",
    "AMZN",
    "AU",
    "GOOGL",
    "META",
    "MSFT",
    "NFLX",
    "NVDA",
    "TSLA",
]
DEFAULT_BAND_PCT = 0.015
_STAMP_RE = re.compile(r"YH_Closed_(\d{12})\.csv$", re.I)


@dataclass
class YhTrade:
    symbol: str
    open_ymd: int
    close_ymd: int  # 0 = still open
    entry: float
    exit: float
    stop: float
    target: float
    pnl: str
    exit_type: str
    zone_center: float
    zone_lo: float
    zone_hi: float
    maturity_ymd: int
    breakout_ymd: int
    cad_ymd: int  # CLOSE_ABOVE_DATE (CAD / retest trigger)
    is_open: bool = False


@dataclass
class Marker:
    ymd: int
    kind: str  # entry | exit | bo | cad
    color: str = "green"
    note: str = ""
    bubble: str = ""
    zone_index: int = 0  # 1-based for BO zone color


@dataclass
class LevelSeg:
    """Horizontal price segment (stop or target) over open..close."""

    open_ymd: int
    close_ymd: int
    price: float
    note: str = ""


@dataclass
class ZonePlot:
    maturity_ymd: int
    center: float
    lo: float
    hi: float
    breakout_ymd: int = 0
    cad_ymd: int = 0
    note: str = ""


@dataclass(frozen=True)
class BandParam:
    value: float
    source: str


def _ymd_int(value: object) -> int:
    if value is None:
        return 0
    text = str(value).strip()
    if not text or text.lower() in {"0", "na", "n/a", "none", "-", ""}:
        return 0
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return int(digits[:8])
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(text[:10], fmt).strftime("%Y%m%d"))
        except ValueError:
            continue
    return 0


def _f(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _fmt_px(px: float) -> str:
    text = f"{px:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def discover_latest_yh_closed_stamp(drive: Path = DRIVE) -> str:
    stamps: list[str] = []
    for path in drive.glob("YH_Closed_*.csv"):
        if "LatestRun" in path.name:
            continue
        m = _STAMP_RE.search(path.name)
        if m:
            stamps.append(m.group(1))
    if not stamps:
        raise FileNotFoundError(f"No YH_Closed_*.csv stamps under {drive}")
    return max(stamps)


def load_band_pct(
    drive: Path = DRIVE,
    *,
    stamp: str,
    default: float = DEFAULT_BAND_PCT,
) -> BandParam:
    candidates = [
        drive / f"YH_Report_{stamp}.csv",
        drive / f"YH_Audit_Report_{stamp}.csv",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "band_pct" not in reader.fieldnames:
                continue
            row = next(reader, None)
            if row is None:
                continue
            raw_text = (row.get("band_pct") or "").strip()
            if not raw_text:
                continue
            raw = _f(raw_text, default=0.0)
            if raw <= 0:
                continue
            # Accept percent form 1.5 → 0.015
            value = raw / 100.0 if raw >= 1.0 else raw
            return BandParam(
                value=value,
                source=f"{path.name}:band_pct (stamp {stamp}, stored={raw})",
            )
    return BandParam(
        value=default,
        source=f"run_yh.bat default band_pct={default}",
    )


def _zone_bounds(
    center: float,
    lo_raw: float,
    hi_raw: float,
    band_pct: float,
) -> tuple[float, float]:
    if lo_raw > 0 and hi_raw > 0 and hi_raw >= lo_raw:
        return lo_raw, hi_raw
    if center <= 0:
        return 0.0, 0.0
    return center * (1.0 - band_pct), center * (1.0 + band_pct)


def _parse_trade(raw: dict[str, str], *, band_pct: float, is_open: bool) -> YhTrade | None:
    sym = (raw.get("SYMBOL") or "").strip().upper()
    if not sym:
        return None
    open_ymd = _ymd_int(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
    if not open_ymd:
        return None
    close_ymd = 0 if is_open else _ymd_int(raw.get("DATE CLOSED") or raw.get("DATE_CLOSED"))
    center = _f(raw.get("ZONE_CENTER"))
    lo, hi = _zone_bounds(
        center,
        _f(raw.get("ZONE_LOW") or raw.get("ZONE_LOWER")),
        _f(raw.get("ZONE_HIGH") or raw.get("ZONE_UPPER")),
        band_pct,
    )
    pnl_raw = raw.get("PNL %") or raw.get("PNL%") or raw.get("PNL_PCT") or ""
    pnl = str(pnl_raw).strip()
    if pnl and not pnl.endswith("%"):
        try:
            pnl = f"{float(pnl):.2f}%"
        except ValueError:
            pass
    return YhTrade(
        symbol=sym,
        open_ymd=open_ymd,
        close_ymd=close_ymd,
        entry=_f(raw.get("ENTRY PRICE") or raw.get("ENTRY_PRICE")),
        exit=_f(raw.get("EXIT PRICE") or raw.get("EXIT_PRICE")),
        stop=_f(
            raw.get("STOP_PRICE")
            or raw.get("STOP LOSS")
            or raw.get("STOP_LOSS")
            or raw.get("STOP")
            or raw.get("ORIGINAL STOP")
            or raw.get("ORIGINAL_STOP")
        ),
        target=_f(raw.get("TARGET_PRICE") or raw.get("TARGET")),
        pnl=pnl or "?",
        exit_type=str(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip(),
        zone_center=center,
        zone_lo=lo,
        zone_hi=hi,
        maturity_ymd=_ymd_int(raw.get("MATURITY_DATE") or raw.get("MATURITY")),
        breakout_ymd=_ymd_int(raw.get("BREAKOUT_DATE") or raw.get("BREAKOUT")),
        cad_ymd=_ymd_int(
            raw.get("CLOSE_ABOVE_DATE")
            or raw.get("CAD_DATE")
            or raw.get("RETEST_DATE")
        ),
        is_open=is_open,
    )


def load_closed(path: Path, *, band_pct: float) -> list[YhTrade]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[YhTrade] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            t = _parse_trade(raw, band_pct=band_pct, is_open=False)
            if t is not None:
                rows.append(t)
    return rows


def load_open(path: Path, *, band_pct: float) -> list[YhTrade]:
    if not path.is_file():
        return []
    rows: list[YhTrade] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            t = _parse_trade(raw, band_pct=band_pct, is_open=True)
            if t is not None:
                rows.append(t)
    return rows


def unique_zones(trades: list[YhTrade]) -> list[ZonePlot]:
    """Dedup by (maturity, center rounded to 2dp); keep first BO/CAD seen."""
    order: list[tuple[int, float]] = []
    by_key: dict[tuple[int, float], ZonePlot] = {}
    for t in trades:
        if t.zone_center <= 0 or t.zone_lo <= 0 or t.zone_hi <= 0:
            continue
        mat = t.maturity_ymd or t.breakout_ymd or t.open_ymd
        if not mat:
            continue
        key = (mat, round(t.zone_center, 2))
        if key not in by_key:
            order.append(key)
            by_key[key] = ZonePlot(
                maturity_ymd=mat,
                center=t.zone_center,
                lo=t.zone_lo,
                hi=t.zone_hi,
                breakout_ymd=t.breakout_ymd,
                cad_ymd=t.cad_ymd,
                note=f"zc={t.zone_center:.2f}",
            )
        else:
            z = by_key[key]
            if not z.breakout_ymd and t.breakout_ymd:
                z.breakout_ymd = t.breakout_ymd
            if not z.cad_ymd and t.cad_ymd:
                z.cad_ymd = t.cad_ymd
    return [by_key[k] for k in order]


def markers_and_levels(
    symbol: str,
    closed: list[YhTrade],
    opens: list[YhTrade],
) -> tuple[list[ZonePlot], list[Marker], list[LevelSeg], list[LevelSeg]]:
    trades = [t for t in closed + opens if t.symbol == symbol]
    zones = unique_zones(trades)
    zone_index: dict[tuple[int, float], int] = {
        (z.maturity_ymd, round(z.center, 2)): i for i, z in enumerate(zones, 1)
    }

    markers: list[Marker] = []
    stops: list[LevelSeg] = []
    targets: list[LevelSeg] = []
    seen_marker: set[tuple[str, int]] = set()

    def add_marker(
        ymd: int,
        kind: str,
        *,
        color: str = "green",
        note: str = "",
        bubble: str = "",
        z_idx: int = 0,
    ) -> None:
        if not ymd:
            return
        key = (kind, ymd)
        if key in seen_marker:
            return
        seen_marker.add(key)
        markers.append(
            Marker(
                ymd=ymd,
                kind=kind,
                color=color,
                note=note,
                bubble=bubble,
                zone_index=z_idx,
            )
        )

    for i, z in enumerate(zones, 1):
        add_marker(
            z.breakout_ymd,
            "bo",
            color="zone",
            note=f"zone {i} {z.note}",
            bubble="BO >",
            z_idx=i,
        )
        add_marker(
            z.cad_ymd,
            "cad",
            color="cyan",
            note=f"zone {i} CAD/retest",
            bubble="CAD >",
            z_idx=i,
        )

    for t in trades:
        z_key = (t.maturity_ymd or t.breakout_ymd or t.open_ymd, round(t.zone_center, 2))
        z_idx = zone_index.get(z_key, 0)
        label = "open" if t.is_open else "closed"
        add_marker(
            t.open_ymd,
            "entry",
            note=label,
            bubble="IN > (open)" if t.is_open else "IN >",
            z_idx=z_idx,
        )
        if not t.is_open:
            xt = t.exit_type or "exit"
            add_marker(
                t.close_ymd,
                "exit",
                note=f"{label} {xt}",
                bubble=f"OUT > ({xt})" if xt else "OUT >",
                z_idx=z_idx,
            )
        close_bound = 99991231 if t.is_open or not t.close_ymd else t.close_ymd
        if t.open_ymd and t.stop > 0:
            stops.append(
                LevelSeg(
                    open_ymd=t.open_ymd,
                    close_ymd=close_bound,
                    price=t.stop,
                    note=f"{label} stop {t.open_ymd}->{close_bound}",
                )
            )
        if t.open_ymd and t.target > 0:
            targets.append(
                LevelSeg(
                    open_ymd=t.open_ymd,
                    close_ymd=close_bound,
                    price=t.target,
                    note=f"{label} target {t.open_ymd}->{close_bound}",
                )
            )

    markers.sort(
        key=lambda m: (
            m.ymd,
            {"bo": 0, "cad": 1, "entry": 2, "exit": 3}.get(m.kind, 9),
        )
    )
    stops.sort(key=lambda s: (s.open_ymd, s.close_ymd, s.price))
    targets.sort(key=lambda s: (s.open_ymd, s.close_ymd, s.price))
    return zones, markers, stops, targets


def build_study_lines(
    symbol: str,
    *,
    stamp: str,
    band: BandParam,
    zones: list[ZonePlot],
    markers: list[Marker],
    stops: list[LevelSeg],
    targets: list[LevelSeg],
) -> list[str]:
    entries = [m for m in markers if m.kind == "entry"]
    exits = [m for m in markers if m.kind == "exit"]
    bos = [m for m in markers if m.kind == "bo"]
    cads = [m for m in markers if m.kind == "cad"]
    band_lit = f"{band.value:.6g}"
    band_pct_label = f"{band.value * 100:.2g}%"

    lines: list[str] = [
        f"# YH closed {symbol} — stamp {stamp} (Year-High)",
        "# SMA20=red, SMA50=white, SMA100=yellow, SMA200=purple (Color.VIOLET)",
        "# Zones: traded YH bands from Closed/Open (O-Y-B-C-V); start at maturity",
        f"# Band: ±{band_pct_label} (band_pct={band_lit}) from {band.source}",
        "# BO = BREAKOUT_DATE (zone color); CAD = CLOSE_ABOVE_DATE (cyan)",
        "# Markers: GREEN In/Out from YH Closed (+ open In from Open ledger)",
        "# Stop lines: RED STOP_PRICE; Target lines: CYAN TARGET_PRICE",
        f"# Counts: zones={len(zones)} bo={len(bos)} cad={len(cads)} "
        f"in={len(entries)} out={len(exits)} stop_segs={len(stops)} "
        f"tgt_segs={len(targets)}",
        "",
        "declare upper;",
        "",
        "input showSMA = yes;",
        "input showZones = yes;",
        "input showBreakouts = yes;",
        "input showCad = yes;",
        "input showEntries = yes;",
        "input showExits = yes;",
        "input showStopLoss = yes;",
        "input showTargets = yes;",
        f"input bandPct = {band_lit};",
        "",
        "def isWeekly = GetAggregationPeriod() == AggregationPeriod.WEEK;",
        "",
        "# ---- SMAs (RL visual DNA; no RL dip band) ----",
        "def smaLen20 = Average(close, 20);",
        "def smaLen50 = Average(close, 50);",
        "def smaLen100 = Average(close, 100);",
        "def smaLen200 = Average(close, 200);",
        "",
        "plot SMA20 = smaLen20;",
        "SMA20.SetDefaultColor(Color.RED);",
        "SMA20.SetLineWeight(2);",
        "SMA20.SetHiding(!showSMA);",
        "",
        "plot SMA50 = smaLen50;",
        "SMA50.SetDefaultColor(Color.WHITE);",
        "SMA50.SetLineWeight(2);",
        "SMA50.SetHiding(!showSMA);",
        "",
        "plot SMA100 = smaLen100;",
        "SMA100.SetDefaultColor(Color.YELLOW);",
        "SMA100.SetLineWeight(2);",
        "SMA100.SetHiding(!showSMA);",
        "",
        "plot SMA200 = smaLen200;",
        "SMA200.SetDefaultColor(Color.VIOLET);",
        "SMA200.SetLineWeight(2);",
        "SMA200.SetHiding(!showSMA);",
        "",
    ]

    if not zones:
        lines.append("# (no YH zones from Closed/Open)")
        lines.append("")
    else:
        lines.append("# ===================== YH ZONES =====================")
        for i, z in enumerate(zones, 1):
            col = zone_color(i)
            cname = color_name(i)
            lines.append(
                f"# Zone {i} ({cname}): maturity {z.maturity_ymd} "
                f"lo={z.lo:.4f} hi={z.hi:.4f} center={z.center:.4f} "
                f"BO={z.breakout_ymd or '-'} CAD={z.cad_ymd or '-'}"
            )
            lines.append(
                f"def z{i}OnW = (IsNaN(GetYYYYMMDD()[1]) and GetYYYYMMDD() >= {z.maturity_ymd}) "
                f"or ({z.maturity_ymd} > GetYYYYMMDD()[1] and {z.maturity_ymd} <= GetYYYYMMDD());"
            )
            lines.append(
                f"def z{i}On = if !isWeekly then GetYYYYMMDD() >= {z.maturity_ymd} "
                f"else (z{i}On[1] or z{i}OnW);"
            )
            lines.append(
                f"def z{i}HiV = if showZones and z{i}On then {_fmt_px(z.hi)} else Double.NaN;"
            )
            lines.append(
                f"def z{i}LoV = if showZones and z{i}On then {_fmt_px(z.lo)} else Double.NaN;"
            )
            lines.append(
                f"def z{i}Hi = if showZones and z{i}On then HighestAll(z{i}HiV) else Double.NaN;"
            )
            lines.append(
                f"def z{i}Lo = if showZones and z{i}On then LowestAll(z{i}LoV) else Double.NaN;"
            )
            lines.append(f"AddCloud(z{i}Hi, z{i}Lo, {col}, {col});")
            lines.append("")

    lines.append("# ===================== BREAKOUTS =====================")
    if not bos:
        lines.append("# (no BO dates)")
        lines.append("")
    else:
        for i, m in enumerate(bos, 1):
            col = zone_color(m.zone_index) if m.zone_index else "Color.ORANGE"
            note = f"  # {m.note}" if m.note else ""
            lines.append(f"def bo{i}Hit = {event_hit_expr(m.ymd)};{note}")
            bubble = (m.bubble or "BO >").replace('"', "'")
            lines.append(
                f'AddChartBubble(showBreakouts and bo{i}Hit, high, "{bubble}", {col}, yes);'
            )
        lines.append("")

    lines.append("# ===================== CAD / RETEST (CLOSE_ABOVE) =====================")
    if not cads:
        lines.append("# (no CAD / CLOSE_ABOVE dates)")
        lines.append("")
    else:
        for i, m in enumerate(cads, 1):
            note = f"  # {m.note}" if m.note else ""
            lines.append(f"def cad{i}Hit = {event_hit_expr(m.ymd)};{note}")
            bubble = (m.bubble or "CAD >").replace('"', "'")
            lines.append(
                f'AddChartBubble(showCad and cad{i}Hit, low, "{bubble}", Color.CYAN, no);'
            )
        lines.append("")

    def emit_io(
        items: list[Marker],
        *,
        prefix: str,
        label: str,
        show_input: str,
        is_entry: bool,
    ) -> None:
        if not items:
            lines.append(f"# (no {label})")
            lines.append("")
            return
        lines.append(f"# ===================== {label.upper()} =====================")
        for i, m in enumerate(items, 1):
            note = f"  # {m.note}" if m.note else ""
            lines.append(f"def {prefix}{i}Hit = {event_hit_expr(m.ymd)};{note}")
        lines.append("")
        price = "low" if is_entry else "high"
        default_bubble = "IN >" if is_entry else "OUT >"
        above = "no" if is_entry else "yes"
        plot_prefix = prefix.upper()
        for i, m in enumerate(items, 1):
            hit = f"{prefix}{i}Hit"
            bubble = (m.bubble or default_bubble).replace('"', "'")
            lines.append(
                f'AddChartBubble({show_input} and {hit}, {price}, '
                f'"{bubble}", Color.GREEN, {above});'
            )
            lines.append(
                f"plot {plot_prefix}{i} = if {show_input} and {hit} "
                f"then {price} else Double.NaN;"
            )
        lines.append("")
        paint = "ARROW_UP" if is_entry else "ARROW_DOWN"
        for i in range(1, len(items) + 1):
            lines.append(
                f"{plot_prefix}{i}.SetPaintingStrategy(PaintingStrategy.{paint});"
            )
            lines.append(f"{plot_prefix}{i}.SetDefaultColor(Color.GREEN);")
            lines.append(f"{plot_prefix}{i}.SetLineWeight(4);")
        lines.append("")

    emit_io(
        entries,
        prefix="ne",
        label="entries (YH Closed/Open)",
        show_input="showEntries",
        is_entry=True,
    )
    emit_io(
        exits,
        prefix="nx",
        label="exits (YH Closed)",
        show_input="showExits",
        is_entry=False,
    )

    def emit_levels(
        segs: list[LevelSeg],
        *,
        prefix: str,
        label: str,
        show_input: str,
        color: str,
        style: str,
    ) -> None:
        if not segs:
            lines.append(f"# (no {label})")
            lines.append("")
            return
        lines.append(f"# ===================== {label.upper()} =====================")
        for i, seg in enumerate(segs, 1):
            note = f"  # {seg.note}" if seg.note else ""
            if seg.close_ymd >= 99990101:
                lines.append(
                    f"def {prefix}{i}Rng = GetYYYYMMDD() >= {seg.open_ymd};{note}"
                )
            else:
                lines.append(
                    f"def {prefix}{i}Rng = GetYYYYMMDD() >= {seg.open_ymd} "
                    f"and GetYYYYMMDD() <= {seg.close_ymd};{note}"
                )
        lines.append("")
        plot_prefix = prefix.upper()
        for i, seg in enumerate(segs, 1):
            px = _fmt_px(seg.price)
            lines.append(
                f"plot {plot_prefix}{i} = if {show_input} and {prefix}{i}Rng "
                f"then {px} else Double.NaN;"
            )
        lines.append("")
        for i in range(1, len(segs) + 1):
            lines.append(f"{plot_prefix}{i}.SetDefaultColor({color});")
            lines.append(f"{plot_prefix}{i}.SetLineWeight(2);")
            lines.append(f"{plot_prefix}{i}.SetStyle(Curve.{style});")
        lines.append("")

    emit_levels(
        stops,
        prefix="sl",
        label="stop loss (STOP_PRICE)",
        show_input="showStopLoss",
        color="Color.RED",
        style="FIRM",
    )
    emit_levels(
        targets,
        prefix="tg",
        label="targets (TARGET_PRICE)",
        show_input="showTargets",
        color="Color.CYAN",
        style="LONG_DASH",
    )

    # Quiet unused-input warning for bandPct (documented; bounds baked from CSV/Report).
    lines.append("# bandPct input documents run setting; zone lo/hi baked from Closed/Open.")
    lines.append("def _bandPctRef = bandPct;")
    lines.append("")
    return lines


def write_readme(
    output_dir: Path,
    *,
    stamp: str,
    symbols: list[str],
    per_sym: dict[str, dict[str, int]],
    band: BandParam,
    closed_path: Path,
    open_path: Path | None,
    failed: list[tuple[str, str]],
) -> Path:
    band_lit = f"{band.value:.6g}"
    ok = [s for s in symbols if s in per_sym]
    lines = [
        "# YH Closed ThinkorSwim studies (Year-High)",
        "",
        f"Single-stamp YH trade studies for MarkTen / `run_yh.bat` symbols, "
        f"stamp **`{stamp}`**.",
        "",
        f"- Symbols requested: **{len(symbols)}**",
        f"- Studies written: **{len(ok)}**",
        f"- Failed: **{len(failed)}**",
        "",
        "Output folder (YH-owned; not mixed with RL/BRT/WPBR):",
        "",
        f"`drive/paul_studies/YH/closed_{stamp}/`",
        "",
        "## What's drawn",
        "",
        "| Element | Meaning |",
        "|---------|---------|",
        "| Red/White/Yellow/Purple SMAs | SMA20 / SMA50 / SMA100 / SMA200 |",
        "| O-Y-B-C-V clouds | Traded YH zones (maturity → forward) |",
        "| Zone-colored BO bubbles | `BREAKOUT_DATE` |",
        "| Cyan CAD bubbles | `CLOSE_ABOVE_DATE` (CAD / retest trigger) |",
        "| Green In/Out arrows | YH Closed (+ Open → In only) |",
        "| Red stop segments | `STOP_PRICE` open→close |",
        "| Cyan dashed target segments | `TARGET_PRICE` open→close |",
        "",
        f"Zone width: `ZONE_LOW`/`ZONE_HIGH` when present, else "
        f"`center ± band_pct` (`band_pct={band_lit}` from `{band.source}`).",
        "",
        "## Files",
        "",
        "| Symbol | Zones | BO | CAD | IN | OUT | SL | TGT | File |",
        "|--------|------:|---:|----:|---:|----:|---:|----:|------|",
    ]
    for sym in symbols:
        c = per_sym.get(sym)
        if not c:
            continue
        lines.append(
            f"| {sym} | {c.get('zones', 0)} | {c.get('bo', 0)} | {c.get('cad', 0)} | "
            f"{c.get('in', 0)} | {c.get('out', 0)} | {c.get('stops', 0)} | "
            f"{c.get('targets', 0)} | `YH_{sym}_closed_{stamp}.ts` |"
        )
    if failed:
        lines.extend(["", "## Failed", ""])
        for sym, reason in failed:
            lines.append(f"- **{sym}**: {reason}")
    lines.extend(
        [
            "",
            "## How to import into ThinkorSwim",
            "",
            "1. Open a **daily** chart for the symbol (e.g. TSLA).",
            "2. Studies → Edit Studies → **Create…**",
            "3. Open the matching `.ts` file in a text editor, copy all, paste into the study editor.",
            f"4. Name it e.g. `YH TSLA closed {stamp}` and apply.",
            "5. Toggle inputs: `showSMA`, `showZones`, `showBreakouts`, `showCad`, "
            "`showEntries`, `showExits`, `showStopLoss`, `showTargets`.",
            "",
            "Regenerate:",
            "",
            "```",
            f"python tos/gen_yh_closed_studies.py --stamp {stamp}",
            "```",
            "",
            "## Sources",
            "",
            f"- `{closed_path.as_posix()}`",
        ]
    )
    if open_path is not None:
        lines.append(f"- `{open_path.as_posix()}` (open In + stop/target + zone)")
    lines.extend(
        [
            f"- `band_pct` from `{band.source}`",
            "- Default universe: AAPL,AMD,AMZN,AU,GOOGL,META,MSFT,NFLX,NVDA,TSLA "
            "(`run_yh.bat` / MarkTen)",
            "",
            "Sibling systems live under `drive/paul_studies/` "
            "(`RL/`, `BRT`→`brt/`, `WPBR`→`wpbr/`, `YH/`). "
            "See `drive/paul_studies/README.md`.",
            "",
        ]
    )
    path = output_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stamp",
        default=None,
        help="YH Closed stamp YYYYMMDDHHMMSS (default: newest under drive/)",
    )
    ap.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: drive/paul_studies/YH/closed_<stamp>)",
    )
    ap.add_argument(
        "--closed-csv",
        type=Path,
        default=None,
        help="Override Closed CSV path",
    )
    ap.add_argument(
        "--open-csv",
        type=Path,
        default=None,
        help="Override Open CSV path (default: YH_Open_<stamp>.csv if present)",
    )
    ap.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated subset (default: MarkTen / run_yh universe)",
    )
    ap.add_argument(
        "--band-pct",
        type=float,
        default=None,
        help=f"Override band_pct (default: from YH_Report or {DEFAULT_BAND_PCT})",
    )
    args = ap.parse_args(argv)

    stamp = args.stamp or discover_latest_yh_closed_stamp(DRIVE)
    closed_path = args.closed_csv or DRIVE / f"YH_Closed_{stamp}.csv"
    open_path = args.open_csv
    if open_path is None:
        cand = DRIVE / f"YH_Open_{stamp}.csv"
        if cand.is_file():
            open_path = cand
        elif (DRIVE / "YH_LatestRun_Open.csv").is_file():
            open_path = DRIVE / "YH_LatestRun_Open.csv"

    out_dir = args.output_dir or (STUDIES_ROOT / f"closed_{stamp}")

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = list(DEFAULT_SYMBOLS)

    if args.band_pct is not None:
        band = BandParam(value=args.band_pct, source=f"CLI --band-pct={args.band_pct}")
    else:
        band = load_band_pct(DRIVE, stamp=stamp)

    print(f"stamp={stamp}")
    print(f"band_pct={band.value} from {band.source}")
    print(f"closed={closed_path}")
    print(f"open={open_path}")
    print(f"symbols={len(symbols)} output={out_dir}")

    closed = load_closed(closed_path, band_pct=band.value)
    opens = load_open(open_path, band_pct=band.value) if open_path else []
    print(f"loaded closed={len(closed)} open={len(opens)}")

    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    per_sym: dict[str, dict[str, int]] = {}
    failed: list[tuple[str, str]] = []

    closed_by_sym = {s: 0 for s in symbols}
    for t in closed:
        if t.symbol in closed_by_sym:
            closed_by_sym[t.symbol] += 1

    for sym in symbols:
        try:
            zones, markers, stops, targets = markers_and_levels(sym, closed, opens)
            lines = build_study_lines(
                sym,
                stamp=stamp,
                band=band,
                zones=zones,
                markers=markers,
                stops=stops,
                targets=targets,
            )
            fname = f"YH_{sym}_closed_{stamp}.ts"
            path = out_dir / fname
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            written.append(fname)
            per_sym[sym] = {
                "zones": len(zones),
                "bo": sum(1 for m in markers if m.kind == "bo"),
                "cad": sum(1 for m in markers if m.kind == "cad"),
                "in": sum(1 for m in markers if m.kind == "entry"),
                "out": sum(1 for m in markers if m.kind == "exit"),
                "stops": len(stops),
                "targets": len(targets),
                "closed_trades": closed_by_sym.get(sym, 0),
            }
            c = per_sym[sym]
            print(
                f"  {sym}: zones={c['zones']} bo={c['bo']} cad={c['cad']} "
                f"in={c['in']} out={c['out']} stops={c['stops']} "
                f"tgts={c['targets']} closed_rows={c['closed_trades']} "
                f"-> {path.name}"
            )
        except Exception as exc:  # noqa: BLE001 — report per-symbol failures
            failed.append((sym, str(exc)))
            print(f"  FAIL {sym}: {exc}", file=sys.stderr)

    readme = write_readme(
        out_dir,
        stamp=stamp,
        symbols=symbols,
        per_sym=per_sym,
        band=band,
        closed_path=closed_path,
        open_path=open_path,
        failed=failed,
    )
    print(f"README: {readme}")
    print(f"Output dir: {out_dir.resolve()}")
    print(f"Wrote {len(written)} / {len(symbols)} studies; failed={len(failed)}")
    for sym, reason in failed:
        print(f"  FAIL {sym}: {reason}")
    return 1 if failed and not written else 0


if __name__ == "__main__":
    raise SystemExit(main())
