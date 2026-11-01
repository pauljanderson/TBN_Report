#!/usr/bin/env python3
"""Generate Thinkorswim ThinkScript studies from LT zone CSVs (research/education).

Reads zone CSVs written by tools/lt_zones_daily_to_15m.py and emits one .ts study
per symbol: horizontal AddCloud bands (lo/hi) plus labeled plots for yearly H/L mid
and POC mid. Also plots **live** prior-session and prior-2 session High/Low via
ThinkScript daily aggregation (`high/low(period=DAY)[1]` / `[2]`) so those levels
do not go stale. Uses the same draw-priority / max_draw as the PNG charts.

Examples:
  python tools/gen_lt_zones_tos_studies.py
  python tools/gen_lt_zones_tos_studies.py --stamp-dir drive/paul_experiments/lt_zones_15m_examples_20260823
  python tools/gen_lt_zones_tos_studies.py --update-gallery

Not a KEEP claim; not DailyRun-wired.
"""
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DEFAULT_STAMP = (
    _REPO / "drive" / "paul_experiments" / "lt_zones_15m_examples_20260823"
)

# Match tools/lt_zones_daily_to_15m.py chart draw order
PRIORITY = {
    "yearly_high": 0,
    "yearly_low": 0,
    "poc": 1,
    "hvn": 2,
    "swing_sr": 3,
    "lvn": 4,
}
DEFAULT_MAX_DRAW = 12

# StreetSmart-ish RGB (same hex as chart ZONE_COLORS)
TYPE_RGB = {
    "yearly_high": (233, 30, 140),
    "yearly_low": (233, 30, 140),
    "swing_sr": (244, 143, 177),
    "poc": (21, 101, 192),
    "hvn": (66, 165, 245),
    "lvn": (144, 164, 174),
}
TYPE_GLOBAL = {
    "yearly_high": "Yearly",
    "yearly_low": "Yearly",
    "swing_sr": "SwingSR",
    "poc": "POC",
    "hvn": "HVN",
    "lvn": "LVN",
}
GLOBAL_RGB = {
    "Yearly": (233, 30, 140),
    "POC": (21, 101, 192),
    "HVN": (66, 165, 245),
    "SwingSR": (244, 143, 177),
    "LVN": (144, 164, 174),
    # Session H/L (live daily aggregation — not frozen from CSV)
    "PriorDay": (255, 152, 0),
    "Prior2Day": (255, 204, 128),
}


@dataclass
class Zone:
    zone_type: str
    lo: float
    hi: float
    mid: float
    touches: int
    source: str
    strength: float
    confluence: str


def _fmt_px(px: float) -> str:
    text = f"{float(px):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def load_zones(csv_path: Path) -> list[Zone]:
    rows: list[Zone] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                lo = float(r["lo"])
                hi = float(r["hi"])
                mid = float(r.get("mid") or 0) or 0.5 * (lo + hi)
                touches = int(float(r.get("touches") or 0))
                strength = float(r.get("strength") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                Zone(
                    zone_type=str(r.get("zone_type", "")).strip(),
                    lo=lo,
                    hi=hi,
                    mid=mid,
                    touches=touches,
                    source=str(r.get("source", "")).strip(),
                    strength=strength,
                    confluence=str(r.get("confluence") or "").strip(),
                )
            )
    return rows


def select_draw_list(zones: list[Zone], max_draw: int = DEFAULT_MAX_DRAW) -> list[Zone]:
    return sorted(
        zones, key=lambda z: (PRIORITY.get(z.zone_type, 9), -z.strength)
    )[:max_draw]


def gallery_symbols(stamp_dir: Path) -> list[str]:
    """Symbols that have both a chart PNG and a zone CSV (gallery examples)."""
    charts = stamp_dir / "charts"
    zones = stamp_dir / "zones"
    syms: list[str] = []
    if charts.is_dir():
        for p in sorted(charts.glob("*_15m_lt_zones.png")):
            sym = p.name.split("_")[0].upper()
            if (zones / f"{sym}_lt_zones.csv").is_file():
                syms.append(sym)
    if not syms and zones.is_dir():
        for p in sorted(zones.glob("*_lt_zones.csv")):
            syms.append(p.name.split("_")[0].upper())
    out: list[str] = []
    seen: set[str] = set()
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _gate_for(zone_type: str) -> str:
    if zone_type in ("yearly_high", "yearly_low", "poc"):
        return "showZones"
    if zone_type == "hvn":
        return "showZones and showHvn"
    if zone_type == "swing_sr":
        return "showZones and showSwing"
    if zone_type == "lvn":
        return "showZones and showLvn"
    return "showZones"


def build_thinkscript(
    symbol: str,
    zones: list[Zone],
    *,
    stamp: str,
    max_draw: int = DEFAULT_MAX_DRAW,
) -> str:
    draw = select_draw_list(zones, max_draw=max_draw)
    yh = next((z for z in zones if z.zone_type == "yearly_high"), None)
    yl = next((z for z in zones if z.zone_type == "yearly_low"), None)
    poc = next((z for z in zones if z.zone_type == "poc"), None)

    need_globals: set[str] = set()
    for z in draw:
        g = TYPE_GLOBAL.get(z.zone_type)
        if g:
            need_globals.add(g)
    if yh is not None or yl is not None:
        need_globals.add("Yearly")
    if poc is not None:
        need_globals.add("POC")

    order = ["Yearly", "POC", "HVN", "SwingSR", "LVN"]
    globals_sorted = [n for n in order if n in need_globals]

    lines: list[str] = [
        f"# LT {symbol} zones 15m — stamp {stamp}",
        "# Long-term daily S/R (yearly H/L, POC/HVN, swing clusters) as horizontal bands.",
        "# Zone bands frozen from zone CSV (research/education only — not DailyRun).",
        "# Prior / prior-2 session H/L are LIVE daily aggregation (high/low[1]/[2]) — not CSV.",
        "# Apply on a 15-minute chart for the matching symbol.",
        "",
        "declare upper;",
        "",
        "input showZones = yes;",
        "input showYearlyPlots = yes;",
        "input showPocPlot = yes;",
        "input showSwing = yes;",
        "input showHvn = yes;",
        "input showLvn = no;",
        "input showPriorSession = yes;",
        "input showPrior2Session = yes;",
        "",
    ]

    for gname in globals_sorted:
        r, g, b = GLOBAL_RGB[gname]
        lines.append(f'DefineGlobalColor("{gname}", CreateColor({r}, {g}, {b}));')
    # Always define session colors (independent of CSV zone mix)
    for gname in ("PriorDay", "Prior2Day"):
        r, g, b = GLOBAL_RGB[gname]
        lines.append(f'DefineGlobalColor("{gname}", CreateColor({r}, {g}, {b}));')
    lines.append("")

    lines.append("# ===================== ZONE CLOUDS (lo/hi from CSV) =====================")
    for i, z in enumerate(draw, 1):
        gname = TYPE_GLOBAL.get(z.zone_type, "SwingSR")
        conf = f" [{z.confluence}]" if z.confluence else ""
        lines.append(
            f"# {z.zone_type} mid={_fmt_px(z.mid)} lo={_fmt_px(z.lo)} hi={_fmt_px(z.hi)} "
            f"touches={z.touches} strength={z.strength}{conf}  src={z.source}"
        )
        gate = _gate_for(z.zone_type)
        lo_s = _fmt_px(z.lo)
        hi_s = _fmt_px(z.hi)
        lines.append(f"def z{i}HiV = if {gate} then {hi_s} else Double.NaN;")
        lines.append(f"def z{i}LoV = if {gate} then {lo_s} else Double.NaN;")
        lines.append(f"def z{i}Hi = if {gate} then HighestAll(z{i}HiV) else Double.NaN;")
        lines.append(f"def z{i}Lo = if {gate} then LowestAll(z{i}LoV) else Double.NaN;")
        lines.append(
            f'AddCloud(z{i}Hi, z{i}Lo, GlobalColor("{gname}"), GlobalColor("{gname}"));'
        )
        lines.append("")

    lines.append("# ===================== LABELED MID PLOTS =====================")
    if yh is not None:
        mid = _fmt_px(yh.mid)
        lines.append(f"# Yearly high mid (rolling 252d) = {mid}")
        lines.append(
            f"plot YearlyHigh = if showYearlyPlots then "
            f"HighestAll(if showYearlyPlots then {mid} else Double.NaN) else Double.NaN;"
        )
        lines.append('YearlyHigh.SetDefaultColor(GlobalColor("Yearly"));')
        lines.append("YearlyHigh.SetStyle(Curve.SHORT_DASH);")
        lines.append("YearlyHigh.SetLineWeight(2);")
        lines.append("")
    if yl is not None:
        mid = _fmt_px(yl.mid)
        lines.append(f"# Yearly low mid (rolling 252d) = {mid}")
        lines.append(
            f"plot YearlyLow = if showYearlyPlots then "
            f"HighestAll(if showYearlyPlots then {mid} else Double.NaN) else Double.NaN;"
        )
        lines.append('YearlyLow.SetDefaultColor(GlobalColor("Yearly"));')
        lines.append("YearlyLow.SetStyle(Curve.SHORT_DASH);")
        lines.append("YearlyLow.SetLineWeight(2);")
        lines.append("")
    if poc is not None:
        mid = _fmt_px(poc.mid)
        lines.append(f"# POC mid (vec_zones VP 60 / 0.5%) = {mid}")
        lines.append(
            f"plot POC = if showPocPlot then "
            f"HighestAll(if showPocPlot then {mid} else Double.NaN) else Double.NaN;"
        )
        lines.append('POC.SetDefaultColor(GlobalColor("POC"));')
        lines.append("POC.SetStyle(Curve.FIRM);")
        lines.append("POC.SetLineWeight(2);")
        lines.append("")

    lines.append("# ===================== PRIOR SESSION H/L (live daily) =====================")
    lines.append("# On a 15m chart: high/low(period=DAY)[1] = prior completed session;")
    lines.append("# [2] = prior-2 session. Updates live — not baked from CSV (avoids stale levels).")
    lines.append("def dayHigh = high(period = AggregationPeriod.DAY);")
    lines.append("def dayLow = low(period = AggregationPeriod.DAY);")
    lines.append("")
    lines.append("# Primary: prior session High & Low")
    lines.append(
        "plot PriorHigh = if showPriorSession then dayHigh[1] else Double.NaN;"
    )
    lines.append(
        "plot PriorLow = if showPriorSession then dayLow[1] else Double.NaN;"
    )
    lines.append('PriorHigh.SetDefaultColor(GlobalColor("PriorDay"));')
    lines.append('PriorLow.SetDefaultColor(GlobalColor("PriorDay"));')
    lines.append("PriorHigh.SetStyle(Curve.FIRM);")
    lines.append("PriorLow.SetStyle(Curve.FIRM);")
    lines.append("PriorHigh.SetLineWeight(2);")
    lines.append("PriorLow.SetLineWeight(2);")
    lines.append('PriorHigh.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);')
    lines.append('PriorLow.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);')
    lines.append("")
    lines.append("# Secondary: prior-2 session High & Low (lighter / dashed)")
    lines.append(
        "plot Prior2High = if showPrior2Session then dayHigh[2] else Double.NaN;"
    )
    lines.append(
        "plot Prior2Low = if showPrior2Session then dayLow[2] else Double.NaN;"
    )
    lines.append('Prior2High.SetDefaultColor(GlobalColor("Prior2Day"));')
    lines.append('Prior2Low.SetDefaultColor(GlobalColor("Prior2Day"));')
    lines.append("Prior2High.SetStyle(Curve.SHORT_DASH);")
    lines.append("Prior2Low.SetStyle(Curve.SHORT_DASH);")
    lines.append("Prior2High.SetLineWeight(1);")
    lines.append("Prior2Low.SetLineWeight(1);")
    lines.append('Prior2High.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);')
    lines.append('Prior2Low.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);')
    lines.append("")

    label_color = "Yearly" if "Yearly" in need_globals else (
        globals_sorted[0] if globals_sorted else "PriorDay"
    )
    lines.append(
        f'AddLabel(yes, "LT zones {symbol} ({stamp}) research", GlobalColor("{label_color}"));'
    )
    lines.append(
        'AddLabel(showPriorSession, "Prior session H/L", GlobalColor("PriorDay"));'
    )
    lines.append(
        'AddLabel(showPrior2Session, "Prior-2 session H/L", GlobalColor("Prior2Day"));'
    )
    lines.append("")
    return "\n".join(lines)


def write_how_to(
    out_dir: Path,
    stamp: str,
    results: list[tuple[str, str, int]],
    *,
    stamp_dir: Path | None = None,
) -> Path:
    path = out_dir / "HOW_TO_TOS_IMPORT.md"
    root = stamp_dir if stamp_dir is not None else out_dir.parent
    has_watch = (root / "watch.html").is_file()
    has_gallery = (root / "gallery.html").is_file()
    example_sym = results[0][0] if results else "NVDA"
    chart_hint = (
        "same TF as the watch charts"
        if has_watch and not has_gallery
        else "same TF as the gallery PNGs"
    )
    regen_flags = ""
    if has_gallery:
        regen_flags = " --update-gallery"
    elif has_watch and results:
        regen_flags = " -s " + ",".join(r[0] for r in results)

    lines = [
        f"# Thinkorswim import — LT zones 15m (`{stamp}`)",
        "",
        "Research / education overlays only — **not** a KEEP claim, **not** DailyRun-wired.",
        "",
        "Each `.ts` study overlays:",
        "",
        "1. **Frozen LT zones** from the matching zone CSV — yearly high/low, Point of Control "
        "(POC) / High-Volume Node (HVN), swing clusters — as horizontal clouds + labeled mid plots.",
        "2. **Prior session High & Low** — live ThinkScript daily bars "
        "(`high/low(period = AggregationPeriod.DAY)[1]`).",
        "3. **Prior-2 session High & Low** — secondary live layer "
        "(`high/low(period = AggregationPeriod.DAY)[2]`, lighter / dashed).",
        "",
        "Session H/L are **not** baked from CSV so they stay current on the chart. "
        "Apply on a **15-minute** chart.",
        "",
        "## How to import",
        "",
        f"1. In Thinkorswim, open a chart for the symbol (e.g. `{example_sym}`).",
        f"2. Set aggregation to **15 minutes** ({chart_hint}).",
        "3. **Studies → Edit Studies → Create…** (or Shared → Studies → Import if you use shared study packages).",
        "4. Open the matching `.ts` file in a text editor, **copy all**, paste into the study editor.",
        f"5. Name the study e.g. `LT {example_sym} zones 15m` and click **OK** / apply.",
        "6. Optional inputs: `showZones`, `showYearlyPlots`, `showPocPlot`, `showSwing`, "
        "`showHvn`, `showLvn`, `showPriorSession`, `showPrior2Session`.",
        "",
    ]
    if has_watch:
        lines.extend(
            [
                f"**Symbols:** watch set from `watch.html` ({len(results)} studies in this folder).",
                "",
            ]
        )
    lines.extend(
        [
            "### Shared study import (optional)",
            "",
            "If you package studies via Setup → Open Shared Item / Shared → Studies:",
            "",
            "- Prefer **copy-paste Create** (above) for these research files — they are plain ThinkScript text.",
            "- There is no encrypted Shared Item ID for this stamp; treat the `.ts` as source.",
            "",
            "## Prior session H/L (live)",
            "",
            "| Layer | ThinkScript | Style |",
            "|-------|-------------|-------|",
            "| Prior session H & L | `high/low(period = AggregationPeriod.DAY)[1]` | Orange, firm weight 2 |",
            "| Prior-2 session H & L | `high/low(period = AggregationPeriod.DAY)[2]` | Light orange, short-dash weight 1 |",
            "",
            "On an intraday chart, `[0]` is the developing session; `[1]` is the last completed "
            "session (prior day); `[2]` is the session before that. Toggle with "
            "`showPriorSession` / `showPrior2Session`.",
            "",
            "## Colors (LT zones match gallery PNGs)",
            "",
            "| Type | Cloud / plot |",
            "|------|----------------|",
            "| Yearly high / low | Magenta/pink band + dashed mid plot |",
            "| POC | Blue band + firm mid plot |",
            "| HVN | Light-blue band (`showHvn`) |",
            "| Swing S/R | Soft pink band (`showSwing`) |",
            "| LVN | Gray band (off by default) |",
            "| Prior session H/L | Orange firm horizontals (live) |",
            "| Prior-2 session H/L | Light-orange dashed horizontals (live) |",
            "",
            "Draw order for CSV clouds matches the PNG tool: yearly → POC → HVN → swing (max 12 clouds).",
            "",
            "## Files",
            "",
            "| Symbol | Zones drawn | File |",
            "|--------|------------:|------|",
        ]
    )
    for sym, fname, n in results:
        lines.append(f"| {sym} | {n} | `{fname}` |")
    lines.extend(
        [
            "",
            "## Regenerate",
            "",
            "```",
            f"python tools/gen_lt_zones_tos_studies.py --stamp-dir drive/paul_experiments/{stamp}{regen_flags}",
            "```",
            "",
            f"Source zones: `drive/paul_experiments/{stamp}/zones/*_lt_zones.csv`",
        ]
    )
    if has_gallery:
        lines.append(f"Gallery: `drive/paul_experiments/{stamp}/gallery.html`")
    if has_watch:
        lines.append(f"Watch: `drive/paul_experiments/{stamp}/watch.html`")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def note_prior_session_in_html(html_path: Path) -> bool:
    """If an HTML page mentions LT zones / ToS, note prior-session H/L once."""
    text = html_path.read_text(encoding="utf-8")
    if "prior-session H/L" in text or "prior session H/L" in text.lower():
        return False
    marker = "Thinkorswim studies:"
    if marker in text:
        text = text.replace(
            marker,
            "Thinkorswim studies (LT zones + live prior / prior-2 session H/L):",
            1,
        )
        html_path.write_text(text, encoding="utf-8")
        return True
    # watch.html-style disclaimer / sub line
    if "yearly H/L, POC, HVN, swings" in text:
        text = text.replace(
            "yearly H/L, POC, HVN, swings",
            "yearly H/L, POC, HVN, swings; ToS studies also plot live prior / prior-2 session H/L",
            1,
        )
        html_path.write_text(text, encoding="utf-8")
        return True
    if '<div class="disclaimer">' in text and "prior / prior-2 session H/L" not in text:
        text = text.replace(
            '<div class="disclaimer">',
            '<div class="disclaimer"><strong>Thinkorswim:</strong> '
            '<a href="tos/HOW_TO_TOS_IMPORT.md">tos/</a> studies include LT zones plus '
            "live prior-session and prior-2 session High/Low. ",
            1,
        )
        html_path.write_text(text, encoding="utf-8")
        return True
    return False


def update_gallery_html(gallery: Path, tos_dir_rel: str, symbols: list[str]) -> None:
    text = gallery.read_text(encoding="utf-8")

    if "ToS study" not in text:
        text = text.replace(
            "Zones CSV<span class=\"sort-ind\"></span></th></tr></thead>",
            "Zones CSV<span class=\"sort-ind\"></span></th>"
            '<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" '
            'aria-sort="none">ToS study<span class="sort-ind"></span></th></tr></thead>',
        )

    for sym in symbols:
        fname = f"LT_{sym}_zones_15m.ts"
        link = f'<a href="{tos_dir_rel}/{fname}">.ts</a>'
        pat = (
            rf'(<tr><td>{re.escape(sym)}</td>.*?'
            rf'<a href="zones/{re.escape(sym)}_lt_zones\.csv">CSV</a></td>)'
            rf'(?:<td><a href="{re.escape(tos_dir_rel)}/{re.escape(fname)}">\.ts</a></td>)?'
            rf'(</tr>)'
        )

        def _repl(m: re.Match[str], link: str = link) -> str:
            return m.group(1) + f"<td>{link}</td>" + m.group(2)

        text = re.sub(pat, _repl, text, count=1, flags=re.DOTALL)

    if "Thinkorswim studies" not in text:
        text = text.replace(
            '<div class="note">',
            '<div class="note"><strong>Thinkorswim studies</strong> '
            f'(LT zones + live prior / prior-2 session H/L): '
            f'see <a href="{tos_dir_rel}/HOW_TO_TOS_IMPORT.md">tos/HOW_TO_TOS_IMPORT.md</a> '
            "and per-symbol <code>LT_&lt;SYM&gt;_zones_15m.ts</code>.</div>\n"
            '<div class="note">',
            1,
        )
    elif "prior / prior-2 session H/L" not in text and "Thinkorswim studies:" in text:
        text = text.replace(
            "Thinkorswim studies:",
            "Thinkorswim studies (LT zones + live prior / prior-2 session H/L):",
            1,
        )

    for sym in symbols:
        fname = f"LT_{sym}_zones_15m.ts"
        if f'href="{tos_dir_rel}/{fname}">ToS</a>' in text:
            continue
        cap_pat = rf'(<figcaption><strong>{re.escape(sym)}</strong> — [^<]+)</figcaption>'
        repl = rf'\1 · <a href="{tos_dir_rel}/{fname}">ToS</a></figcaption>'
        text = re.sub(cap_pat, repl, text, count=1)

    gallery.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stamp-dir",
        type=Path,
        default=DEFAULT_STAMP,
        help="Stamp folder with zones/ and charts/",
    )
    ap.add_argument(
        "-s",
        "--symbols",
        default=None,
        help="Comma-separated symbols (default: all with chart+CSV)",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output tos/ folder (default: <stamp-dir>/tos)",
    )
    ap.add_argument(
        "--update-gallery",
        action="store_true",
        help="Add ToS links into gallery.html",
    )
    ap.add_argument("--max-draw", type=int, default=DEFAULT_MAX_DRAW)
    args = ap.parse_args(argv)

    stamp_dir = Path(args.stamp_dir).resolve()
    if not stamp_dir.is_dir():
        raise SystemExit(f"stamp dir not found: {stamp_dir}")
    stamp = stamp_dir.name
    out_dir = Path(args.output).resolve() if args.output else stamp_dir / "tos"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = gallery_symbols(stamp_dir)
    if not symbols:
        raise SystemExit("no symbols found")

    results: list[tuple[str, str, int]] = []
    max_draw = int(args.max_draw)
    for sym in symbols:
        csv_path = stamp_dir / "zones" / f"{sym}_lt_zones.csv"
        if not csv_path.is_file():
            print(f"SKIP {sym}: missing {csv_path}")
            continue
        zones = load_zones(csv_path)
        draw = select_draw_list(zones, max_draw=max_draw)
        text = build_thinkscript(sym, zones, stamp=stamp, max_draw=max_draw)
        fname = f"LT_{sym}_zones_15m.ts"
        dest = out_dir / fname
        dest.write_text(text, encoding="utf-8")
        results.append((sym, fname, len(draw)))
        print(f"Wrote {dest} ({len(draw)} clouds from {len(zones)} CSV rows)")

    how = write_how_to(out_dir, stamp, results, stamp_dir=stamp_dir)
    print(f"Wrote {how}")

    if args.update_gallery:
        gallery = stamp_dir / "gallery.html"
        if gallery.is_file():
            update_gallery_html(gallery, "tos", [r[0] for r in results])
            print(f"Updated {gallery}")
        else:
            print(f"WARNING: no gallery at {gallery}")

    watch = stamp_dir / "watch.html"
    if watch.is_file():
        note_prior_session_in_html(watch)
        print(f"Noted prior-session H/L in {watch}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
