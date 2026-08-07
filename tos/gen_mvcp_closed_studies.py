#!/usr/bin/env python3
"""
Generate ThinkorSwim studies for Minervini VCP (MVCP) Closed trades.

Per seed symbol:
  - SMA20 (red), SMA50 (white), SMA100 (yellow), SMA200 (purple/violet)
  - Orange TRIGGER bubbles on TRIGGER_DATE (pivot break + vol gate bar)
  - Green In/Out arrows+bubbles from Closed (open In from Open CSV)
  - Yellow dashed pivot segments: PIVOT from open..close
  - Red stop-loss segments: STOP_PRICE from open..close
  - Cyan dashed target segments: TARGET_PRICE from open..close
  - OUT bubble includes EXIT_TYPE (STOP_LOSS / TARGET / TIME_STOP / TRAIL_SMA / …)

Output:
  drive/paul_studies/MVCP/closed_<stamp>/MVCP_<SYM>_closed_<stamp>.ts

Usage:
  python tos/gen_mvcp_closed_studies.py
  python tos/gen_mvcp_closed_studies.py --stamp 260801122831
  python tos/gen_mvcp_closed_studies.py -o drive/paul_studies/MVCP/closed_260801122831
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

from ts_common import event_hit_expr  # noqa: E402

DRIVE = _ROOT / "drive"
STUDIES_ROOT = DRIVE / "paul_studies" / "MVCP"
_STAMP_RE = re.compile(r"MVCP_Closed_(\d{12})\.csv$", re.I)

# Locked seed universe (Theory / run_minervini_vcp.bat).
DEFAULT_SYMBOLS = [
    "AXON",
    "LULU",
    "CMG",
    "NVDA",
    "TSLA",
    "AMZN",
    "META",
    "NFLX",
    "AMD",
    "AVGO",
    "ANET",
    "CRM",
    "CRWD",
    "NET",
    "SHOP",
    "SNOW",
    "CELH",
    "DECK",
]

# Teaching / chart-gate priority (called out in README + 60_seed_tos.md).
HIGHLIGHT_SYMBOLS = ("AXON", "LULU", "CMG", "NVDA")


@dataclass
class MvcpTrade:
    symbol: str
    open_ymd: int
    close_ymd: int  # 0 = still open
    entry: float
    exit: float
    stop: float
    target: float
    pivot: float
    pnl: str
    exit_type: str
    trigger_ymd: int
    trigger_close: float
    vol_ratio: float
    rs_percentile: float
    contractions: int
    is_open: bool = False


@dataclass
class Marker:
    ymd: int
    kind: str  # trigger | entry | exit
    color: str = "green"
    note: str = ""
    bubble: str = ""


@dataclass
class LevelSeg:
    open_ymd: int
    close_ymd: int
    price: float
    note: str = ""


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


def _i(value: object, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _fmt_px(px: float) -> str:
    text = f"{px:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def discover_latest_mvcp_closed_stamp(drive: Path = DRIVE) -> str:
    stamps: list[str] = []
    for path in drive.glob("MVCP_Closed_*.csv"):
        if "LatestRun" in path.name:
            continue
        m = _STAMP_RE.search(path.name)
        if m:
            stamps.append(m.group(1))
    if not stamps:
        raise FileNotFoundError(f"No MVCP_Closed_*.csv stamps under {drive}")
    return max(stamps)


def _parse_trade(raw: dict[str, str], *, is_open: bool) -> MvcpTrade | None:
    sym = (raw.get("SYMBOL") or "").strip().upper()
    if not sym:
        return None
    open_ymd = _ymd_int(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
    if not open_ymd:
        return None
    close_ymd = 0 if is_open else _ymd_int(raw.get("DATE CLOSED") or raw.get("DATE_CLOSED"))
    pnl_raw = raw.get("PNL %") or raw.get("PNL%") or raw.get("PNL_PCT") or ""
    pnl = str(pnl_raw).strip()
    if pnl and not pnl.endswith("%"):
        try:
            pnl = f"{float(pnl):.2f}%"
        except ValueError:
            pass
    return MvcpTrade(
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
        ),
        target=_f(raw.get("TARGET_PRICE") or raw.get("TARGET")),
        pivot=_f(raw.get("PIVOT")),
        pnl=pnl or "?",
        exit_type=str(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip(),
        trigger_ymd=_ymd_int(raw.get("TRIGGER_DATE") or raw.get("SIGNAL_DATE")),
        trigger_close=_f(raw.get("TRIGGER_CLOSE")),
        vol_ratio=_f(raw.get("VOL_RATIO_TRIGGER") or raw.get("VOL_RATIO")),
        rs_percentile=_f(raw.get("RS_PERCENTILE")),
        contractions=_i(raw.get("CONTRACTIONS")),
        is_open=is_open,
    )


def load_closed(path: Path) -> list[MvcpTrade]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[MvcpTrade] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            t = _parse_trade(raw, is_open=False)
            if t is not None:
                rows.append(t)
    return rows


def load_open(path: Path) -> list[MvcpTrade]:
    if not path.is_file():
        return []
    rows: list[MvcpTrade] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            t = _parse_trade(raw, is_open=True)
            if t is not None:
                rows.append(t)
    return rows


def markers_and_levels(
    symbol: str,
    closed: list[MvcpTrade],
    opens: list[MvcpTrade],
) -> tuple[list[Marker], list[LevelSeg], list[LevelSeg], list[LevelSeg]]:
    trades = [t for t in closed + opens if t.symbol == symbol]
    markers: list[Marker] = []
    stops: list[LevelSeg] = []
    targets: list[LevelSeg] = []
    pivots: list[LevelSeg] = []
    seen_marker: set[tuple[str, int, str]] = set()

    def add_marker(
        ymd: int,
        kind: str,
        *,
        color: str = "green",
        note: str = "",
        bubble: str = "",
    ) -> None:
        if not ymd:
            return
        key = (kind, ymd, bubble)
        if key in seen_marker:
            return
        seen_marker.add(key)
        markers.append(
            Marker(ymd=ymd, kind=kind, color=color, note=note, bubble=bubble)
        )

    for t in trades:
        label = "open" if t.is_open else "closed"
        audit_bits = []
        if t.rs_percentile:
            audit_bits.append(f"rs={t.rs_percentile:.1f}")
        if t.vol_ratio:
            audit_bits.append(f"vol={t.vol_ratio:.2f}x")
        if t.contractions:
            audit_bits.append(f"n={t.contractions}")
        if t.trigger_close:
            audit_bits.append(f"trg_c={t.trigger_close:.2f}")
        audit = " ".join(audit_bits) if audit_bits else label
        add_marker(
            t.trigger_ymd,
            "trigger",
            color="orange",
            note=f"{label} trigger {audit}",
            bubble="TRIG >",
        )
        add_marker(
            t.open_ymd,
            "entry",
            note=label,
            bubble="IN > (open)" if t.is_open else "IN >",
        )
        if not t.is_open:
            xt = t.exit_type or "exit"
            add_marker(
                t.close_ymd,
                "exit",
                note=f"{label} {xt} {t.pnl}",
                bubble=f"OUT > ({xt})",
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
        # Pivot from trigger (or open) through exit — visual VCP shelf.
        pivot_start = t.trigger_ymd or t.open_ymd
        if pivot_start and t.pivot > 0:
            pivots.append(
                LevelSeg(
                    open_ymd=pivot_start,
                    close_ymd=close_bound,
                    price=t.pivot,
                    note=f"{label} pivot {pivot_start}->{close_bound}",
                )
            )

    markers.sort(
        key=lambda m: (
            m.ymd,
            {"trigger": 0, "entry": 1, "exit": 2}.get(m.kind, 9),
        )
    )
    stops.sort(key=lambda s: (s.open_ymd, s.close_ymd, s.price))
    targets.sort(key=lambda s: (s.open_ymd, s.close_ymd, s.price))
    pivots.sort(key=lambda s: (s.open_ymd, s.close_ymd, s.price))
    return markers, stops, targets, pivots


def build_study_lines(
    symbol: str,
    *,
    stamp: str,
    markers: list[Marker],
    stops: list[LevelSeg],
    targets: list[LevelSeg],
    pivots: list[LevelSeg],
) -> list[str]:
    triggers = [m for m in markers if m.kind == "trigger"]
    entries = [m for m in markers if m.kind == "entry"]
    exits = [m for m in markers if m.kind == "exit"]

    lines: list[str] = [
        f"# MVCP closed {symbol} — stamp {stamp} (Minervini VCP Stage-2)",
        "# SMA20=red, SMA50=white, SMA100=yellow, SMA200=purple (Color.VIOLET)",
        "# Orange TRIG = TRIGGER_DATE (Close > pivot + vol breakout bar)",
        "# Green IN = next-open fill; Green OUT = exit (bubble shows EXIT_TYPE)",
        "# Yellow dashed = PIVOT shelf; Red stop; Cyan dashed = TARGET (+25%)",
        f"# Counts: trig={len(triggers)} in={len(entries)} out={len(exits)} "
        f"pivot_segs={len(pivots)} stop_segs={len(stops)} tgt_segs={len(targets)}",
        "",
        "declare upper;",
        "",
        "input showSMA = yes;",
        "input showTriggers = yes;",
        "input showEntries = yes;",
        "input showExits = yes;",
        "input showPivot = yes;",
        "input showStopLoss = yes;",
        "input showTargets = yes;",
        "",
        "def isWeekly = GetAggregationPeriod() == AggregationPeriod.WEEK;",
        "",
        "# ---- SMAs (shared visual DNA with SB/RL/YH closed studies) ----",
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

    # ---- TRIGGER markers (orange) ----
    if not triggers:
        lines.append("# (no TRIGGER_DATE markers)")
        lines.append("")
    else:
        lines.append("# ===================== TRIGGERS (TRIGGER_DATE) =====================")
        for i, m in enumerate(triggers, 1):
            note = f"  # {m.note}" if m.note else ""
            lines.append(f"def tg{i}Hit = {event_hit_expr(m.ymd)};{note}")
            bubble = (m.bubble or "TRIG >").replace('"', "'")
            lines.append(
                f'AddChartBubble(showTriggers and tg{i}Hit, high, "{bubble}", '
                f"Color.ORANGE, yes);"
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
        label="entries (MVCP Closed/Open)",
        show_input="showEntries",
        is_entry=True,
    )
    emit_io(
        exits,
        prefix="nx",
        label="exits (MVCP Closed)",
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
        pivots,
        prefix="pv",
        label="pivot (PIVOT shelf)",
        show_input="showPivot",
        color="Color.YELLOW",
        style="LONG_DASH",
    )
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

    return lines


def write_readme(
    output_dir: Path,
    *,
    stamp: str,
    symbols: list[str],
    per_sym: dict[str, dict[str, int]],
    closed_path: Path,
    open_path: Path | None,
    failed: list[tuple[str, str]],
    closed_count: int,
    closed_by_sym: dict[str, int],
) -> Path:
    ok = [s for s in symbols if s in per_sym]
    zero = [s for s in ok if per_sym[s].get("in", 0) == 0]
    highlight = [s for s in HIGHLIGHT_SYMBOLS if s in symbols]
    lines = [
        "# MVCP Closed ThinkorSwim studies (Minervini VCP)",
        "",
        f"Single-stamp MVCP trade studies for the locked 18-seed universe, "
        f"stamp **`{stamp}`** ({closed_count} closed trades).",
        "",
        f"- Symbols requested: **{len(symbols)}**",
        f"- Studies written: **{len(ok)}**",
        f"- Zero-fill studies: **{len(zero)}**"
        + (f" ({', '.join(zero)})" if zero else ""),
        f"- Failed: **{len(failed)}**",
        "",
        "Output folder:",
        "",
        f"`drive/paul_studies/MVCP/closed_{stamp}/`",
        "",
        "## Chart-gate priority (open these first)",
        "",
        "| Symbol | Closed fills | Why |",
        "|--------|-------------:|-----|",
    ]
    for sym in highlight:
        n = closed_by_sym.get(sym, 0)
        why = {
            "AXON": "Teaching seed (TASR successor) — 2 fills on this stamp",
            "LULU": "Teaching seed — **0 fills**; confirm idle vs bug",
            "CMG": "Teaching seed — stop + time-stop paths",
            "NVDA": "Modern leader — includes fill-gap chase example (2023-05)",
        }.get(sym, "Priority chart-gate name")
        if sym == "AXON" and n:
            why = f"Teaching seed (TASR successor) — {n} fills on this stamp"
        elif sym == "LULU":
            why = "Teaching seed — **0 fills**; confirm idle vs bug under RS≥80 + vol 1.5×"
        elif sym == "CMG" and n:
            why = f"Teaching seed — {n} fills (stop + time-stop paths)"
        elif sym == "NVDA" and n:
            why = f"Modern leader — {n} fills; check 2023-05 fill gap vs pivot"
        lines.append(f"| **{sym}** | {n} | {why} |")
    lines.extend(
        [
            "",
            "## What's drawn",
            "",
            "| Element | Meaning |",
            "|---------|---------|",
            "| Red/White/Yellow/Purple SMAs | SMA20 / SMA50 / SMA100 / SMA200 |",
            "| Orange TRIG bubbles | `TRIGGER_DATE` — Close > pivot + vol gate |",
            "| Green In/Out arrows | MVCP Closed (+ Open → In only) |",
            "| OUT bubble text | Includes `EXIT_TYPE` |",
            "| Yellow dashed pivot | `PIVOT` shelf trigger→close |",
            "| Red stop segments | `STOP_PRICE` open→close |",
            "| Cyan dashed targets | `TARGET_PRICE` (+25%) open→close |",
            "",
            "## Files",
            "",
            "| Symbol | TRIG | IN | OUT | PV | SL | TGT | File |",
            "|--------|-----:|---:|----:|---:|---:|----:|------|",
        ]
    )
    for sym in symbols:
        c = per_sym.get(sym)
        if not c:
            continue
        star = " **" if sym in HIGHLIGHT_SYMBOLS else ""
        star_end = "**" if sym in HIGHLIGHT_SYMBOLS else ""
        lines.append(
            f"| {star}{sym}{star_end} | {c.get('trig', 0)} | {c.get('in', 0)} | "
            f"{c.get('out', 0)} | {c.get('pivots', 0)} | {c.get('stops', 0)} | "
            f"{c.get('targets', 0)} | `MVCP_{sym}_closed_{stamp}.ts` |"
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
            "1. Open a **daily** chart for the symbol (e.g. AXON).",
            "2. Studies → Edit Studies → **Create…**",
            "3. Open the matching `.ts` file in a text editor, copy all, paste into the study editor.",
            f"4. Name it e.g. `MVCP AXON closed {stamp}` and apply.",
            "5. Toggle inputs: `showSMA`, `showTriggers`, `showEntries`, "
            "`showExits`, `showPivot`, `showStopLoss`, `showTargets`.",
            "",
            "Regenerate:",
            "",
            "```",
            f"python tos/gen_mvcp_closed_studies.py --stamp {stamp}",
            "```",
            "",
            "## Sources",
            "",
            f"- `{closed_path.as_posix()}`",
        ]
    )
    if open_path is not None:
        lines.append(f"- `{open_path.as_posix()}` (open In + stop/target/pivot)")
    lines.extend(
        [
            "- Seed universe: `run_minervini_vcp.bat` / Theory 18 seeds",
            "",
            "Sibling systems under `drive/paul_studies/` "
            "(`RL/`, `YH/`, `SB/`, `MVCP/`, …).",
            "",
            "Process notes: `drive/paul_experiments/tbn_new_systems/"
            "minervini_vcp/60_seed_tos.md`.",
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
        help="MVCP Closed stamp YYYYMMDDHHMMSS (default: newest under drive/)",
    )
    ap.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: drive/paul_studies/MVCP/closed_<stamp>)",
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
        help="Override Open CSV path (default: MVCP_Open_<stamp>.csv if present)",
    )
    ap.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated subset (default: locked 18-seed universe)",
    )
    args = ap.parse_args(argv)

    stamp = args.stamp or discover_latest_mvcp_closed_stamp(DRIVE)
    closed_path = args.closed_csv or DRIVE / f"MVCP_Closed_{stamp}.csv"
    open_path = args.open_csv
    if open_path is None:
        cand = DRIVE / f"MVCP_Open_{stamp}.csv"
        if cand.is_file():
            open_path = cand

    out_dir = args.output_dir or (STUDIES_ROOT / f"closed_{stamp}")

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = list(DEFAULT_SYMBOLS)

    print(f"stamp={stamp}")
    print(f"closed={closed_path}")
    print(f"open={open_path}")
    print(f"symbols={len(symbols)} output={out_dir}")

    closed = load_closed(closed_path)
    opens = load_open(open_path) if open_path else []
    print(f"loaded closed={len(closed)} open={len(opens)}")

    closed_by_sym: dict[str, int] = {}
    for t in closed:
        closed_by_sym[t.symbol] = closed_by_sym.get(t.symbol, 0) + 1

    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    per_sym: dict[str, dict[str, int]] = {}
    failed: list[tuple[str, str]] = []

    for sym in symbols:
        try:
            markers, stops, targets, pivots = markers_and_levels(sym, closed, opens)
            lines = build_study_lines(
                sym,
                stamp=stamp,
                markers=markers,
                stops=stops,
                targets=targets,
                pivots=pivots,
            )
            fname = f"MVCP_{sym}_closed_{stamp}.ts"
            path = out_dir / fname
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            written.append(sym)
            per_sym[sym] = {
                "trig": sum(1 for m in markers if m.kind == "trigger"),
                "in": sum(1 for m in markers if m.kind == "entry"),
                "out": sum(1 for m in markers if m.kind == "exit"),
                "pivots": len(pivots),
                "stops": len(stops),
                "targets": len(targets),
            }
            print(
                f"  {sym}: trig={per_sym[sym]['trig']} in={per_sym[sym]['in']} "
                f"out={per_sym[sym]['out']} -> {fname}"
            )
        except Exception as exc:  # noqa: BLE001 — per-symbol continue
            failed.append((sym, str(exc)))
            print(f"  FAIL {sym}: {exc}")

    readme = write_readme(
        out_dir,
        stamp=stamp,
        symbols=symbols,
        per_sym=per_sym,
        closed_path=closed_path,
        open_path=open_path,
        failed=failed,
        closed_count=len(closed),
        closed_by_sym=closed_by_sym,
    )
    print(f"wrote {len(written)} studies + {readme.name}")
    return 1 if failed and not written else 0


if __name__ == "__main__":
    raise SystemExit(main())
