#!/usr/bin/env python3
"""
Generate ThinkorSwim studies for Rocket Launcher (RL) Closed trades — single stamp.

Per symbol (full gold universe by default):
  - SMA20 (red), SMA50 (white), SMA100 (yellow), SMA200 (purple/violet)
    Plot names and AddLabels include the length so color alone is not required.
  - SMA50Up20 (cyan dashed) = SMA50 * 1.20
  - SMA50Exp (green solid) = SMA50 * rl_expansion  (from Report/Audit)
  - Disable any separate Thinkorswim DailySMA / MovingAvg studies when reading
    this RL study — a second “200” line in another color confuses the stack.
  - Dip band via RL formula at the run's rl_dip_pct (prior-bar SMA50 = y_sma):
        upper = y_sma * rl_dip_pct
        lower = y_sma * (1 - (rl_dip_pct - 1))
    When SMA20 > SMA50 AND SMA50 > SMA100 AND SMA100 > SMA200:
      green cloud = dip band
    Else: translucent red
  - SMAs/band always plot on chart close (`Average(close, N)`). Do NOT use
    secondary `close(period=DAY)` — ToS rejects secondary ≤ chart agg and
    blanks the whole study. AggregationPeriod gates were too brittle
    (markers OK / SMAs blank even on Day). Opt-in `requireDailyChart`
    (default **no**) can re-enable the old daily-like blank; otherwise
    weekly charts get a warning label (SMA50 = 50-week mean).
  - Stack gate (engine): SMA20 > SMA50 > SMA100 > SMA200 on the **signal**
    bar (day before entry). Closed CSV SMA* columns are **entry-bar EOD**
    simple means (same Average(close,N) definition). Dip band uses SMA50[1].
  - Cyan SMA50Up20 / green SMA50Exp are *multiples of SMA50*, not stack MAs —
    do not confuse them with purple SMA200.
  - Green In/Out arrows+bubbles from Closed (and open In from Open CSV)
  - Red stop-loss horizontal segment per closed trade (ORIGINAL STOP),
    open..close inclusive; open positions extend from open forward

Visual DNA matches tos/gen_rl_trade_diff_studies.py (single-stamp variant:
one dip band + one marker color instead of A/B grey/green dual bands).

Usage:
  python tos/gen_rl_closed_studies.py
  python tos/gen_rl_closed_studies.py --stamp 260728232254
  python tos/gen_rl_closed_studies.py -o drive/paul_studies/RL/closed_260728232254
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_TOS_DIR = Path(__file__).resolve().parent
_ROOT = _TOS_DIR.parent
if str(_TOS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOS_DIR))

from ts_common import event_hit_expr  # noqa: E402

# Reuse Closed loaders / types from the existing RL ToS generator.
from gen_rl_trade_diff_studies import (  # noqa: E402
    DEFAULT_RL_EXPANSION,
    ExpansionParam,
    Marker,
    StopSeg,
    Trade,
    _fmt_px,
    _f,
    _ymd_int,
    load_closed,
    load_rl_expansion,
)

DRIVE = _ROOT / "drive"
UNIVERSE_PATH = _ROOT / "data" / "rl_gold_universe.txt"


@dataclass(frozen=True)
class DipParam:
    value: float
    source: str


def discover_latest_rl_closed_stamp(drive: Path = DRIVE) -> str:
    """Pick newest RL_Closed_YYMMDDHHMMSS.csv stamp (exclude LatestRun)."""
    stamps: list[str] = []
    for path in drive.glob("RL_Closed_*.csv"):
        name = path.stem  # RL_Closed_260728232254
        if name.endswith("_LatestRun") or "LatestRun" in name:
            continue
        m = re.search(r"RL_Closed_(\d{12})$", name)
        if m:
            stamps.append(m.group(1))
    if not stamps:
        raise FileNotFoundError(f"No RL_Closed_*.csv stamps under {drive}")
    return max(stamps)


def load_universe(path: Path = UNIVERSE_PATH) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    syms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        syms.append(text.upper())
    if not syms:
        raise ValueError(f"Empty universe: {path}")
    return syms


def load_rl_dip_pct(
    drive: Path = DRIVE,
    *,
    stamp: str,
    default: float = 1.055,
) -> DipParam:
    candidates = [
        drive / f"RL_Report_{stamp}.csv",
        drive / f"RL_Audit_Report_{stamp}.csv",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "rl_dip_pct" not in reader.fieldnames:
                continue
            row = next(reader, None)
            if row is None:
                continue
            raw_text = (row.get("rl_dip_pct") or "").strip()
            if not raw_text:
                continue
            raw = _f(raw_text, default=0.0)
            if raw <= 0:
                continue
            # Accept fraction form 0.041 → 1.041
            value = raw if raw >= 1.0 else 1.0 + raw
            return DipParam(
                value=value,
                source=f"{path.name}:rl_dip_pct (stamp {stamp}, stored={raw})",
            )
    return DipParam(
        value=default,
        source=f"engine default rl_dip_pct={default}",
    )


def load_open(path: Path) -> list[Trade]:
    """Open ledger → Trade rows (close_ymd=0, exit=0)."""
    if not path.is_file():
        return []
    rows: list[Trade] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            sym = (raw.get("SYMBOL") or "").strip().upper()
            if not sym:
                continue
            open_ymd = _ymd_int(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
            if not open_ymd:
                continue
            stop = _f(
                raw.get("STOP LOSS")
                or raw.get("STOP_LOSS")
                or raw.get("ORIGINAL STOP")
                or raw.get("STOP")
            )
            rows.append(
                Trade(
                    symbol=sym,
                    open_ymd=open_ymd,
                    close_ymd=0,
                    entry=_f(raw.get("ENTRY PRICE") or raw.get("ENTRY_PRICE")),
                    exit=0.0,
                    pnl=str(raw.get("PNL %") or raw.get("PNL%") or "?").strip() or "?",
                    stop=stop,
                )
            )
    return rows


def markers_for_symbol(
    symbol: str,
    closed: list[Trade],
    opens: list[Trade],
) -> tuple[list[Marker], list[StopSeg]]:
    markers: list[Marker] = []
    stops: list[StopSeg] = []
    seen_marker: set[tuple[str, int]] = set()  # kind, ymd

    def add(ymd: int, kind: str, note: str = "", bubble: str = "") -> None:
        if not ymd:
            return
        key = (kind, ymd)
        if key in seen_marker:
            return
        seen_marker.add(key)
        markers.append(
            Marker(ymd=ymd, kind=kind, color="green", note=note, bubble=bubble)
        )

    for t in closed:
        if t.symbol != symbol:
            continue
        add(t.open_ymd, "entry", note="closed", bubble="IN >")
        add(t.close_ymd, "exit", note="closed", bubble="OUT >")
        if t.open_ymd and t.close_ymd and t.stop > 0:
            stops.append(
                StopSeg(
                    open_ymd=t.open_ymd,
                    close_ymd=t.close_ymd,
                    stop=t.stop,
                    note=f"closed {t.open_ymd}->{t.close_ymd}",
                )
            )

    for t in opens:
        if t.symbol != symbol:
            continue
        add(t.open_ymd, "entry", note="open", bubble="IN > (open)")
        if t.open_ymd and t.stop > 0:
            # Open stop: from entry forward (no close bound).
            stops.append(
                StopSeg(
                    open_ymd=t.open_ymd,
                    close_ymd=99991231,
                    stop=t.stop,
                    note=f"open from {t.open_ymd}",
                )
            )

    markers.sort(key=lambda m: (m.ymd, 0 if m.kind == "entry" else 1))
    stops.sort(key=lambda s: (s.open_ymd, s.close_ymd, s.stop))
    return markers, stops


def build_study_lines(
    symbol: str,
    *,
    stamp: str,
    markers: list[Marker],
    stops: list[StopSeg],
    expansion: ExpansionParam,
    dip: DipParam,
) -> list[str]:
    entries = [m for m in markers if m.kind == "entry"]
    exits = [m for m in markers if m.kind == "exit"]
    exp = expansion.value
    exp_lit = f"{exp:.6g}"
    dip_v = dip.value
    dip_lit = f"{dip_v:.6g}"
    dip_pct_label = f"{(dip_v - 1.0) * 100:.2g}%"

    lines: list[str] = [
        f"# RL closed {symbol} — stamp {stamp} (Rocket Launcher)",
        "# SMA20=red, SMA50=white, SMA100=yellow, SMA200=purple (Color.VIOLET)",
        "# SMA50Up20=cyan dashed = SMA50 * 1.20 (NOT a stack MA — ignore for 20>50>100>200)",
        f"# SMA50Exp=green = SMA50 * {exp_lit}  [rl_expansion from {expansion.source}] (also NOT stack)",
        "# SMA* = Average(close, N) on chart bars  [same simple mean as rocket_rl / Closed SMA cols]",
        "# Engine stack gate: signal bar (T) SMA20>50>100>200; fill next open (T+1).",
        "# Closed SMA20/50/100/200 = entry-bar (T+1) EOD means — not re-gated on fill.",
        "# SMAs/band ALWAYS plot (no AggregationPeriod NaN gate). Prefer Daily chart.",
        "# requireDailyChart=yes (opt-in) blanks SMAs/band unless DAY <= agg < WEEK.",
        "# No secondary close(period=DAY) — blanks whole study on daily charts.",
        "# Dip band (RL gate y_sma): upper = SMA50[1]*rl_dip_pct; lower = SMA50[1]*(2-rl_dip_pct)",
        f"# Band: rl_dip_pct={dip_lit} ({dip_pct_label}) from {dip.source}",
        "# Band colors: green when smaStackBull; else red cloud",
        "# Markers: GREEN In/Out from RL Closed (+ open In from Open ledger)",
        "# Stop lines: RED horizontal ORIGINAL STOP from open through close",
        f"# Counts: in={len(entries)} out={len(exits)} stop_segs={len(stops)}",
        "",
        "declare upper;",
        "",
        "input showSMA = yes;",
        "input showSMA50Up20 = yes;",
        "input showSMA50Exp = yes;",
        "input showBand = yes;",
        "input showEntries = yes;",
        "input showExits = yes;",
        "input showStopLoss = yes;",
        "input requireDailyChart = no;",
        "input showAggWarn = yes;",
        "input showStackLabel = yes;",
        "input showSmaValueLabels = yes;",
        "input showEntrySmaBubble = yes;",
        f"input dipPct = {dip_lit};",
        f"input rlExpansion = {exp_lit};",
        "",
        # isWeekly used by event_hit_expr for markers. Never secondary close(period=DAY).
        "def aggPeriod = GetAggregationPeriod();",
        "def isWeekly = aggPeriod == AggregationPeriod.WEEK;",
        "def isIntraday = aggPeriod < AggregationPeriod.DAY;",
        "def isDailyLike = aggPeriod >= AggregationPeriod.DAY and aggPeriod < AggregationPeriod.WEEK;",
        # Opt-in gate only: default requireDailyChart=no → always plot SMAs/band.
        "def allowSmaBand = !requireDailyChart or isDailyLike;",
        'AddLabel(showAggWarn and isDailyLike, "RL Daily", Color.GREEN);',
        'AddLabel(showAggWarn and isWeekly, "RL warn: WEEKLY (SMA50=50-week; use Day)", Color.ORANGE);',
        'AddLabel(showAggWarn and isIntraday, "RL warn: INTRADAY (use Day for RL SMA50)", Color.ORANGE);',
        'AddLabel(showAggWarn and requireDailyChart and !allowSmaBand, "RL SMAs OFF: requireDailyChart + not Day", Color.ORANGE);',
        'AddLabel(showAggWarn, "Disable extra DailySMA/MA studies — only this RL study", Color.GRAY);',
        "",
        "# ---- SMAs + RL dip band (chart close; no secondary aggregation) ----",
        "def smaLen20 = Average(close, 20);",
        "def smaLen50 = Average(close, 50);",
        "def smaLen100 = Average(close, 100);",
        "def smaLen200 = Average(close, 200);",
        "def ySma50 = smaLen50[1];",
        "def sma50Up20Val = smaLen50 * 1.20;",
        "def sma50ExpVal = smaLen50 * rlExpansion;",
        "def smaStackBull = smaLen20 > smaLen50 and smaLen50 > smaLen100 and smaLen100 > smaLen200;",
        'AddLabel(showStackLabel and allowSmaBand and smaStackBull, "Stack OK 20>50>100>200  " + Round(smaLen20, 2) + " > " + Round(smaLen50, 2) + " > " + Round(smaLen100, 2) + " > " + Round(smaLen200, 2), Color.GREEN);',
        'AddLabel(showStackLabel and allowSmaBand and !smaStackBull, "Stack BROKEN  " + Round(smaLen20, 2) + " / " + Round(smaLen50, 2) + " / " + Round(smaLen100, 2) + " / " + Round(smaLen200, 2), Color.RED);',
        # Per-length labels (last bar) — length in text so color alone cannot mislead.
        'AddLabel(showSmaValueLabels and allowSmaBand, "SMA20 red=" + Round(smaLen20, 2), Color.RED);',
        'AddLabel(showSmaValueLabels and allowSmaBand, "SMA50 white=" + Round(smaLen50, 2), Color.WHITE);',
        'AddLabel(showSmaValueLabels and allowSmaBand, "SMA100 yellow=" + Round(smaLen100, 2), Color.YELLOW);',
        'AddLabel(showSmaValueLabels and allowSmaBand, "SMA200 purple=" + Round(smaLen200, 2), Color.VIOLET);',
        "",
        "DefineGlobalColor(\"BandGreen\", CreateColor(34, 197, 94));",
        "DefineGlobalColor(\"BandRed\", CreateColor(239, 68, 68));",
        "",
        "# Visible band outlines + cloud edges; SMAs plotted after so white SMA50 stays on top.",
        "def rlBandHi = ySma50 * dipPct;",
        "def rlBandLo = ySma50 * (1 - (dipPct - 1));",
        "",
        "plot BandHi = if showBand and allowSmaBand then rlBandHi else Double.NaN;",
        "plot BandLo = if showBand and allowSmaBand then rlBandLo else Double.NaN;",
        "BandHi.SetDefaultColor(Color.DARK_GREEN);",
        "BandLo.SetDefaultColor(Color.DARK_GREEN);",
        "BandHi.SetStyle(Curve.SHORT_DASH);",
        "BandLo.SetStyle(Curve.SHORT_DASH);",
        "BandHi.SetLineWeight(2);",
        "BandLo.SetLineWeight(2);",
        "BandHi.SetHiding(!showBand);",
        "BandLo.SetHiding(!showBand);",
        "",
        "plot BandHiOk = if showBand and allowSmaBand and smaStackBull then rlBandHi else Double.NaN;",
        "plot BandLoOk = if showBand and allowSmaBand and smaStackBull then rlBandLo else Double.NaN;",
        "plot BandHiBad = if showBand and allowSmaBand and !smaStackBull then rlBandHi else Double.NaN;",
        "plot BandLoBad = if showBand and allowSmaBand and !smaStackBull then rlBandLo else Double.NaN;",
        "BandHiOk.SetDefaultColor(Color.GREEN);",
        "BandLoOk.SetDefaultColor(Color.GREEN);",
        "BandHiBad.SetDefaultColor(Color.RED);",
        "BandLoBad.SetDefaultColor(Color.RED);",
        "BandHiOk.SetHiding(yes);",
        "BandLoOk.SetHiding(yes);",
        "BandHiBad.SetHiding(yes);",
        "BandLoBad.SetHiding(yes);",
        "AddCloud(BandHiOk, BandLoOk, GlobalColor(\"BandGreen\"), GlobalColor(\"BandGreen\"));",
        "AddCloud(BandHiBad, BandLoBad, GlobalColor(\"BandRed\"), GlobalColor(\"BandRed\"));",
        "",
        # Always assign real SMA values; hide only via inputs (defaults yes).
        # Plot identifiers must be valid ThinkScript names (no spaces).
        # Color/length clarity lives in AddLabel + SetDefaultColor (SetName is not valid).
        "plot SMA20 = if showSMA and allowSmaBand then smaLen20 else Double.NaN;",
        "SMA20.SetDefaultColor(Color.RED);",
        "SMA20.SetLineWeight(2);",
        "SMA20.SetHiding(!showSMA);",
        "",
        "plot SMA50 = if showSMA and allowSmaBand then smaLen50 else Double.NaN;",
        "SMA50.SetDefaultColor(Color.WHITE);",
        "SMA50.SetLineWeight(3);",
        "SMA50.SetHiding(!showSMA);",
        "",
        "plot SMA50Up20 = if showSMA50Up20 and allowSmaBand then sma50Up20Val else Double.NaN;",
        "SMA50Up20.SetDefaultColor(Color.CYAN);",
        "SMA50Up20.SetLineWeight(2);",
        "SMA50Up20.SetStyle(Curve.LONG_DASH);",
        "SMA50Up20.SetHiding(!showSMA50Up20);",
        "",
        "plot SMA50Exp = if showSMA50Exp and allowSmaBand then sma50ExpVal else Double.NaN;",
        "SMA50Exp.SetDefaultColor(Color.GREEN);",
        "SMA50Exp.SetLineWeight(2);",
        "SMA50Exp.SetStyle(Curve.FIRM);",
        "SMA50Exp.SetHiding(!showSMA50Exp);",
        "",
        "plot SMA100 = if showSMA and allowSmaBand then smaLen100 else Double.NaN;",
        "SMA100.SetDefaultColor(Color.YELLOW);",
        "SMA100.SetLineWeight(2);",
        "SMA100.SetHiding(!showSMA);",
        "",
        "plot SMA200 = if showSMA and allowSmaBand then smaLen200 else Double.NaN;",
        "SMA200.SetDefaultColor(Color.VIOLET);",
        "SMA200.SetLineWeight(2);",
        "SMA200.SetHiding(!showSMA);",
        "",
    ]

    def emit_group(
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
            if is_entry:
                # Live bar SMA values on IN date — length in text (not color-only).
                lines.append(
                    f'AddChartBubble({show_input} and {hit}, {price}, '
                    f'if showEntrySmaBubble then "{bubble} 20/50/100/200=" '
                    f'+ Round(smaLen20, 2) + "/" + Round(smaLen50, 2) + "/" '
                    f'+ Round(smaLen100, 2) + "/" + Round(smaLen200, 2) '
                    f'else "{bubble}", Color.GREEN, {above});'
                )
            else:
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

    emit_group(
        entries,
        prefix="ne",
        label="entries (RL Closed/Open)",
        show_input="showEntries",
        is_entry=True,
    )
    emit_group(
        exits,
        prefix="nx",
        label="exits (RL Closed)",
        show_input="showExits",
        is_entry=False,
    )

    if not stops:
        lines.append("# (no stop-loss segments)")
        lines.append("")
    else:
        lines.append("# ===================== STOP LOSS (ORIGINAL STOP) =====================")
        for i, seg in enumerate(stops, 1):
            note = f"  # {seg.note}" if seg.note else ""
            if seg.close_ymd >= 99990101:
                lines.append(
                    f"def sl{i}Rng = GetYYYYMMDD() >= {seg.open_ymd};{note}"
                )
            else:
                lines.append(
                    f"def sl{i}Rng = GetYYYYMMDD() >= {seg.open_ymd} "
                    f"and GetYYYYMMDD() <= {seg.close_ymd};{note}"
                )
        lines.append("")
        for i, seg in enumerate(stops, 1):
            px = _fmt_px(seg.stop)
            lines.append(
                f"plot SL{i} = if showStopLoss and sl{i}Rng "
                f"then {px} else Double.NaN;"
            )
        lines.append("")
        for i in range(1, len(stops) + 1):
            lines.append(f"SL{i}.SetDefaultColor(Color.RED);")
            lines.append(f"SL{i}.SetLineWeight(2);")
            lines.append(f"SL{i}.SetStyle(Curve.FIRM);")
        lines.append("")

    return lines


def write_readme(
    output_dir: Path,
    *,
    stamp: str,
    symbols: list[str],
    per_sym: dict[str, dict[str, int]],
    expansion: ExpansionParam,
    dip: DipParam,
    closed_path: Path,
    open_path: Path | None,
    failed: list[tuple[str, str]],
) -> Path:
    exp_lit = f"{expansion.value:.6g}"
    dip_lit = f"{dip.value:.6g}"
    ok = [s for s in symbols if s in per_sym]
    lines = [
        "# RL Closed ThinkorSwim studies (Rocket Launcher)",
        "",
        f"Single-stamp RL trade/entry-exit studies for gold universe "
        f"(`data/rl_gold_universe.txt`), stamp **`{stamp}`**.",
        "",
        f"- Symbols requested: **{len(symbols)}**",
        f"- Studies written: **{len(ok)}**",
        f"- Failed: **{len(failed)}**",
        "",
        "## Colors / bands",
        "",
        "| Element | Meaning |",
        "|---------|---------|",
        "| Green arrows/bubbles | RL Closed In/Out (Open ledger → In only) |",
        "| Red SMA20 | chart `Average(close, 20)` |",
        "| White SMA50 | chart `Average(close, 50)` — same simple mean as rocket_rl / AWK |",
        "| Cyan SMA50Up20 (dashed) | `SMA50 × 1.20` — **not** part of the stack |",
        f"| Green SMA50Exp (solid) | `SMA50 × {exp_lit}` — `{expansion.source}` — **not** stack |",
        "| Yellow SMA100 | chart `Average(close, 100)` — plot `SMA100`, `Color.YELLOW` |",
        "| Purple SMA200 | chart `Average(close, 200)` — plot `SMA200`, `Color.VIOLET` |",
        f"| Green dip cloud | When SMA stack bull — prior-bar band `rl_dip_pct={dip_lit}` |",
        "| Red dip cloud | When SMA stack broken |",
        "| Stack OK / BROKEN label | Live `Round(SMA20/50/100/200)` vs 20>50>100>200 |",
        "| SMA value labels | `SMA20 red=…` / `SMA50 white=…` / `SMA100 yellow=…` / `SMA200 purple=…` |",
        "| IN bubble SMA values | Optional `20/50/100/200=` on entry bars (`showEntrySmaBubble`) |",
        "| Red stop-loss lines | `ORIGINAL STOP` (Closed) / `STOP LOSS` (Open) |",
        "",
        "Band formula (matches RL dip gate `y_sma` = prior-bar SMA50):",
        "",
        "```",
        "dip_hi = SMA50[1] * rl_dip_pct",
        "dip_lo = SMA50[1] * (1 - (rl_dip_pct - 1))",
        "```",
        "",
        "**Use a Daily chart** for RL-correct SMA50 / dip band. SMAs always plot "
        "(no AggregationPeriod NaN gate). On weekly/intraday you still see lines, but "
        "they are N-bar means of that aggregation (50-week on Week) — orange warn label. "
        "Opt-in `requireDailyChart=yes` restores blanking unless daily-like.",
        "",
        "**Disable extra platform SMA studies** (e.g. Thinkorswim `DailySMA(..., 200)` / "
        "Moving Average) while reading this RL study. A second “200” line in another color "
        "makes the stack look wrong even when our purple SMA200 is correct.",
        "",
        "## SMA stack vs Closed (AEHR 2013-07-29 check)",
        "",
        "Rocket Launcher requires **SMA20 > SMA50 > SMA100 > SMA200** on the **signal** bar "
        "(fill is next open). Closed `SMA20/50/100/200` are **entry-bar EOD** simple means — "
        "same definition as ThinkScript `Average(close, N)` on a Daily chart.",
        "",
        "Color map is fixed: **purple = SMA200** (Paul’s assumption is correct). "
        "For AEHR IN **2013-07-29**: Closed = 1.58 / 1.44 / 1.24 / 1.07 "
        "(stack OK; **SMA200 lowest**). Recomputed from `data/newdata/data/AEHR.csv` matches. "
        "If yellow appears *below* purple on the chart while labels show 100 > 200, that is not "
        "a color-map bug — disable extra SMA studies, confirm Day agg, and read the value labels "
        "(not color alone). Cyan SMA50Up20 / green SMA50Exp are **not** stack MAs.",
        "",
        "## Root cause (AEHR: markers OK, SMAs/band blank)",
        "",
        "1. **Wrong map (weekly):** Old studies used `Average(close, 50)` on chart bars, so a "
        "weekly chart plotted a **50-week** SMA and dip shading around it. Engine/Closed/PNG "
        "are **daily** SMA50 of close.",
        "2. **Blank everything (daily):** A follow-up tried `close(period = AggregationPeriod.DAY)` "
        "for intraday. ThinkScript rejects secondary ≤ chart aggregation → **no trades, no SMAs**. "
        "Removed secondary entirely.",
        "3. **Markers OK / SMAs blank:** Exact `GetAggregationPeriod() == AggregationPeriod.DAY` "
        "and later `DAY <= agg < WEEK` still NaN'd SMAs/band when ToS reported an agg Paul "
        "treated as Day (or sticky study settings). Markers were never gated. "
        "**Fix (2026-08-24):** always plot `Average(close, N)` + dip band; "
        "`requireDailyChart` default **no**; weekly → warn label only.",
        "",
        "Re-import after regen (paste into a **new** study or replace script; do not keep an old "
        "copy that still has the gate).",
        "",
        "## Files",
        "",
        "| Symbol | IN | OUT | SL segs | File |",
        "|--------|---:|----:|--------:|------|",
    ]
    for sym in symbols:
        c = per_sym.get(sym)
        if not c:
            continue
        lines.append(
            f"| {sym} | {c.get('in', 0)} | {c.get('out', 0)} | "
            f"{c.get('stops', 0)} | `RL_{sym}_closed_{stamp}.ts` |"
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
            "1. Open a **Day** (D) chart for the symbol (e.g. AEHR).",
            "2. Studies → Edit Studies → **Create…** (or edit existing and replace all script).",
            "3. Open the matching `.ts` file in a text editor, copy all, paste into the study editor.",
            f"4. Name it e.g. `RL AEHR closed {stamp}` and apply.",
            "5. Confirm plots `SMA20`/`SMA50`/`SMA100`/`SMA200` (red/white/yellow/purple) "
            "+ AddLabels `SMA20 red=…` etc. + dashed dip outlines + cloud + In/Out.",
            "6. Inputs default **yes** for `showSMA` / `showBand` / `showStackLabel` / "
            "`showSmaValueLabels` / `showEntrySmaBubble` / etc.; `requireDailyChart` default **no**.",
            "7. On Week/intraday: orange warn label (lines still draw; use Day for RL-correct SMA50).",
            "8. **Disable** other DailySMA / MA studies on the chart (second “200” line confuses).",
            "9. Toggle: `showSMA50Up20`, `showSMA50Exp`, `showBand`, `showAggWarn`, `showStackLabel`, "
            "`showSmaValueLabels`, `showEntrySmaBubble`, `showEntries`, `showExits`, `showStopLoss`, "
            "`requireDailyChart`.",
            "10. Optional: lower GlobalColor BandGreen/BandRed opacity in study settings.",
            "",
            "See also `HOW_TO.md` in this folder.",
            "",
            "Regenerate:",
            "",
            "```",
            f"python tos/gen_rl_closed_studies.py --stamp {stamp}",
            "```",
            "",
            "## Sources",
            "",
            f"- `{closed_path.as_posix()}`",
        ]
    )
    if open_path is not None:
        lines.append(f"- `{open_path.as_posix()}` (open In + stop)")
    lines.extend(
        [
            f"- `rl_expansion` from `{expansion.source}`",
            f"- `rl_dip_pct` from `{dip.source}`",
            f"- Universe: `{UNIVERSE_PATH.as_posix()}`",
            "",
            "Same visual family as `tos/gen_rl_trade_diff_studies.py` "
            "(single-stamp: one dip band + green markers).",
            "",
        ]
    )
    path = output_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_howto(output_dir: Path, *, stamp: str) -> Path:
    """Short import note — Daily chart + re-import after regen."""
    lines = [
        f"# HOW TO: Import RL Closed ThinkorSwim studies (stamp {stamp})",
        "",
        f"**Folder:** `drive/paul_studies/RL/closed_{stamp}/`",
        "**Format:** ThinkScript `.ts` (one study per symbol).",
        "",
        "## Critical",
        "",
        "1. Use a **Daily (Day / D)** chart so SMA50 matches RL (`Average(close, 50)` on daily bars).",
        "2. After regenerating `.ts` files, **re-import** (paste full script into Create… or replace "
        "the existing study script). Old copies still contain AggregationPeriod NaN gates that blank SMAs.",
        "3. Inputs: `showSMA` / `showBand` / `showSmaValueLabels` / `showEntrySmaBubble` / … default **yes**; "
        "`requireDailyChart` default **no** (SMAs always draw).",
        "4. Stack + per-SMA value labels (default on): **SMA20 red=…**, **SMA100 yellow=…**, "
        "**SMA200 purple=…**. Cyan SMA50Up20 / green SMA50Exp are **not** stack lines — purple is SMA200.",
        "5. **Turn off** any separate Thinkorswim `DailySMA` / Moving Average studies on the same chart "
        "(especially a second length-200). Only this RL study should draw the stack.",
        "",
        "## Import steps (AEHR example)",
        "",
        "1. Open **AEHR** on a **Day** chart; remove extra platform SMA studies first.",
        "2. Studies → Edit Studies → **Create…**",
        f"3. Open `RL_AEHR_closed_{stamp}.ts`, Select All → Copy → paste into the editor.",
        f"4. Name e.g. `RL AEHR closed {stamp}` → OK → apply.",
        "5. Confirm plots `SMA20`/`SMA50`/`SMA100`/`SMA200` (red/white/yellow/purple via "
        "`SetDefaultColor` + value AddLabels), white SMA50 thick line, dashed dip band, green In/Out.",
        "6. On **2013-07-29** IN: Closed SMA stack is 1.58 > 1.44 > 1.24 > 1.07 — Stack OK; "
        "**SMA200 purple is lowest** of the four stack MAs (yellow SMA100 sits above it).",
        "",
        "## Regenerate",
        "",
        "```",
        f"python tos/gen_rl_closed_studies.py --stamp {stamp}",
        "```",
        "",
        "Sibling systems: `drive/paul_studies/` (`RL/`, `YH/`, `SB/`, `MVCP/`, `brt/`).",
        "",
    ]
    path = output_dir / "HOW_TO.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stamp",
        default=None,
        help="RL Closed stamp YYYYMMDDHHMMSS (default: newest under drive/)",
    )
    ap.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: drive/paul_studies/RL/closed_<stamp>)",
    )
    ap.add_argument(
        "--universe",
        type=Path,
        default=UNIVERSE_PATH,
        help=f"Symbol list (default: {UNIVERSE_PATH})",
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
        help="Override Open CSV path (default: RL_Open_<stamp>.csv if present)",
    )
    ap.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated subset (default: full universe file)",
    )
    args = ap.parse_args(argv)

    stamp = args.stamp or discover_latest_rl_closed_stamp(DRIVE)
    closed_path = args.closed_csv or DRIVE / f"RL_Closed_{stamp}.csv"
    # Prefer stamped Open; fall back to LatestRun Open.
    open_path = args.open_csv
    if open_path is None:
        cand = DRIVE / f"RL_Open_{stamp}.csv"
        if cand.is_file():
            open_path = cand
        elif (DRIVE / "RL_LatestRun_Open.csv").is_file():
            open_path = DRIVE / "RL_LatestRun_Open.csv"

    out_dir = args.output_dir or (DRIVE / "paul_studies" / "RL" / f"closed_{stamp}")

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = load_universe(args.universe)

    expansion = load_rl_expansion(
        DRIVE,
        primary_stamp=stamp,
        fallback_stamp=stamp,
        default=DEFAULT_RL_EXPANSION,
    )
    dip = load_rl_dip_pct(DRIVE, stamp=stamp)
    print(f"stamp={stamp}")
    print(f"rl_expansion={expansion.value} from {expansion.source}")
    print(f"rl_dip_pct={dip.value} from {dip.source}")
    print(f"closed={closed_path}")
    print(f"open={open_path}")
    print(f"symbols={len(symbols)} output={out_dir}")

    closed = load_closed(closed_path)
    opens = load_open(open_path) if open_path else []
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
            markers, stops = markers_for_symbol(sym, closed, opens)
            lines = build_study_lines(
                sym,
                stamp=stamp,
                markers=markers,
                stops=stops,
                expansion=expansion,
                dip=dip,
            )
            fname = f"RL_{sym}_closed_{stamp}.ts"
            path = out_dir / fname
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            written.append(fname)
            per_sym[sym] = {
                "in": sum(1 for m in markers if m.kind == "entry"),
                "out": sum(1 for m in markers if m.kind == "exit"),
                "stops": len(stops),
                "closed_trades": closed_by_sym.get(sym, 0),
            }
            print(
                f"  {sym}: in={per_sym[sym]['in']} out={per_sym[sym]['out']} "
                f"stops={per_sym[sym]['stops']} closed_rows={per_sym[sym]['closed_trades']} "
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
        expansion=expansion,
        dip=dip,
        closed_path=closed_path,
        open_path=open_path,
        failed=failed,
    )
    howto = write_howto(out_dir, stamp=stamp)
    print(f"README: {readme}")
    print(f"HOW_TO: {howto}")
    print(f"Output dir: {out_dir.resolve()}")
    print(f"Wrote {len(written)} / {len(symbols)} studies; failed={len(failed)}")
    for sym, reason in failed:
        print(f"  FAIL {sym}: {reason}")
    return 1 if failed and not written else 0


if __name__ == "__main__":
    raise SystemExit(main())
