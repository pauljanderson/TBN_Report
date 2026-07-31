#!/usr/bin/env python3
"""
Generate ThinkorSwim studies for RL Closed trade-diff (111201 vs MarkTen 144725).

Per symbol (AAPL, AMD, AU, META, NFLX, NVDA, TSLA):
  - SMA20 (red), SMA50 (white), SMA100 (yellow), SMA200 (purple/violet)
  - SMA50Up20 (white) = SMA50 * 1.20  (distinct from SMA50 plot)
  - SMA50Exp (green) = SMA50 * rl_expansion  (from Report/Audit; not hard-coded)
  - SMA50 = Average(close, 50) — same simple mean as rocket_rl / AWK
  - Dip bands via RL formula:
        upper = SMA * rl_dip_pct
        lower = SMA * (1 - (rl_dip_pct - 1))   # == SMA * (2 - rl_dip_pct)
    When SMA20 > SMA50 AND SMA50 > SMA100 AND SMA100 > SMA200:
      grey cloud  = 2.4% band (rl_dip_pct=1.024, stamp 111201)
      green cloud = 4.1% band (rl_dip_pct=1.041, stamp 144725)
    Else (stack broken): both bands translucent red
  - Entry/exit arrows+bubbles (one In + one Out per logical trade):
    grey  = exact match OR close-match (same/near trade in both stamps)
    green = MarkTen-only (new trades in 144725)
    Close-match uses MarkTen open date only (111201 open in bubble text).
  - Red stop-loss horizontal segment per plotted trade (ORIGINAL STOP from
    MarkTen/Closed), from open date through close date inclusive.

Usage:
  python tos/gen_rl_trade_diff_studies.py
  python tos/gen_rl_trade_diff_studies.py -o drive/paul_studies/RL/trade_diff_111201_vs_144725
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
OLD_STAMP = "260726111201"
NEW_STAMP = "260726144725"
DEFAULT_OUT = (
    DRIVE / "paul_studies" / "RL" / f"trade_diff_{OLD_STAMP[-6:]}_vs_{NEW_STAMP[-6:]}"
)

# Symbols that actually traded in this comparison (not GOOGL/AMZN/MSFT).
SYMBOLS = ["AAPL", "AMD", "AU", "META", "NFLX", "NVDA", "TSLA"]

# RL dip band multipliers (audit: rl_dip_pct; gate uses yesterday SMA).
DIP_PCT_24 = 1.024  # stamp 111201
DIP_PCT_41 = 1.041  # stamp 144725 MarkTen

# Engine default for rl_expansion / AWK RL_EXPANSION (multiplier form, not fraction).
DEFAULT_RL_EXPANSION = 1.163

# Hard-coded close-match pairs from canvas/HTML (111201 open → 144725 open).
# Same symbol, nearby entry under expanded 4.1% zone, typically same exit.
CLOSE_PAIRS: list[tuple[str, str, str]] = [
    ("AMD", "20200916", "20200915"),
    ("AMD", "20230628", "20230626"),
    ("AU", "20240425", "20240424"),
    ("AU", "20250701", "20250625"),
    ("AU", "20251031", "20251024"),
    ("NFLX", "20221221", "20221219"),
]


@dataclass
class Trade:
    symbol: str
    open_ymd: int
    close_ymd: int
    entry: float
    exit: float
    pnl: str
    stop: float = 0.0  # ORIGINAL STOP (entry stop) from Closed CSV


@dataclass
class Marker:
    ymd: int
    kind: str  # "entry" | "exit"
    color: str  # "grey" | "green"
    note: str = ""
    bubble: str = ""  # optional AddChartBubble text override


@dataclass
class StopSeg:
    """Horizontal stop-loss segment for one plotted trade (open..close)."""

    open_ymd: int
    close_ymd: int
    stop: float
    note: str = ""


@dataclass(frozen=True)
class ExpansionParam:
    """rl_expansion as stored in Report/Audit (multiplier, e.g. 1.163)."""

    value: float
    source: str  # human-readable: file + column + stamp


def _normalize_expansion(raw: float) -> float:
    """Report/Audit stores multiplier (1.163). Accept fraction 0.163 → 1.163."""
    if raw <= 0:
        raise ValueError(f"invalid rl_expansion: {raw}")
    if raw < 1.0:
        return 1.0 + raw
    return raw


def load_rl_expansion(
    drive: Path = DRIVE,
    *,
    primary_stamp: str = NEW_STAMP,
    fallback_stamp: str = OLD_STAMP,
    default: float = DEFAULT_RL_EXPANSION,
) -> ExpansionParam:
    """
    Load rl_expansion from Report then Audit for primary stamp, then fallback stamp,
    else engine default. Column is ``rl_expansion`` (AWK ``RL_EXPANSION``).
    """
    candidates: list[tuple[str, Path]] = []
    for stamp in (primary_stamp, fallback_stamp):
        candidates.append((stamp, drive / f"RL_Report_{stamp}.csv"))
        candidates.append((stamp, drive / f"RL_Audit_Report_{stamp}.csv"))

    for stamp, path in candidates:
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "rl_expansion" not in reader.fieldnames:
                continue
            row = next(reader, None)
            if row is None:
                continue
            raw_text = (row.get("rl_expansion") or "").strip()
            if not raw_text:
                continue
            raw = _f(raw_text, default=0.0)
            if raw <= 0:
                continue
            value = _normalize_expansion(raw)
            return ExpansionParam(
                value=value,
                source=f"{path.name}:rl_expansion (stamp {stamp}, stored={raw})",
            )

    return ExpansionParam(
        value=default,
        source=f"engine default DEFAULT_RL_EXPANSION={default}",
    )


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


def load_closed(path: Path) -> list[Trade]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[Trade] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            sym = (raw.get("SYMBOL") or "").strip().upper()
            if not sym:
                continue
            open_ymd = _ymd_int(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
            close_ymd = _ymd_int(raw.get("DATE CLOSED") or raw.get("DATE_CLOSED"))
            if not open_ymd:
                continue
            pnl_raw = raw.get("PNL %") or raw.get("PNL%") or raw.get("PNL_PCT") or ""
            pnl = str(pnl_raw).strip()
            if pnl and not pnl.endswith("%"):
                try:
                    pnl = f"{float(pnl):.2f}%"
                except ValueError:
                    pass
            # Prefer ORIGINAL STOP (entry stop); fall back to STOP / STOP LOSS AT CLOSE.
            stop = _f(
                raw.get("ORIGINAL STOP")
                or raw.get("ORIGINAL_STOP")
                or raw.get("STOP")
                or raw.get("STOP LOSS AT CLOSE")
                or raw.get("STOP_LOSS_AT_CLOSE")
            )
            rows.append(
                Trade(
                    symbol=sym,
                    open_ymd=open_ymd,
                    close_ymd=close_ymd,
                    entry=_f(raw.get("ENTRY PRICE") or raw.get("ENTRY_PRICE")),
                    exit=_f(raw.get("EXIT PRICE") or raw.get("EXIT_PRICE")),
                    pnl=pnl or "?",
                    stop=stop,
                )
            )
    return rows


def _key(t: Trade) -> tuple[str, int]:
    return (t.symbol, t.open_ymd)


def classify_trades(
    old: list[Trade], new: list[Trade]
) -> tuple[list[Trade], list[tuple[Trade, Trade]], list[Trade]]:
    """Return (exact_new_rows, close_pairs (old,new), new_only)."""
    old_by_key = {_key(t): t for t in old}
    new_by_key = {_key(t): t for t in new}

    exact: list[Trade] = []
    for k, nt in new_by_key.items():
        if k in old_by_key:
            exact.append(nt)

    close_old_opens = {(sym, int(oa)): int(ob) for sym, oa, ob in CLOSE_PAIRS}
    close_new_opens = {(sym, int(ob)): int(oa) for sym, oa, ob in CLOSE_PAIRS}

    close_pairs: list[tuple[Trade, Trade]] = []
    for sym, oa, ob in CLOSE_PAIRS:
        ot = old_by_key.get((sym, int(oa)))
        nt = new_by_key.get((sym, int(ob)))
        if ot is None or nt is None:
            raise RuntimeError(
                f"Close-match missing: {sym} old={oa} new={ob} "
                f"(old_found={ot is not None} new_found={nt is not None})"
            )
        close_pairs.append((ot, nt))

    new_only: list[Trade] = []
    for k, nt in new_by_key.items():
        if k in old_by_key:
            continue
        if k in close_new_opens:
            continue
        new_only.append(nt)

    # Sanity: old-only should be exactly the 6 close-match A sides.
    old_only_keys = [k for k in old_by_key if k not in new_by_key]
    expected_old_only = {(sym, int(oa)) for sym, oa, _ in CLOSE_PAIRS}
    if set(old_only_keys) != expected_old_only:
        raise RuntimeError(
            f"Unexpected old-only keys {sorted(old_only_keys)}; "
            f"expected {sorted(expected_old_only)}"
        )

    exact.sort(key=lambda t: (t.symbol, t.open_ymd))
    new_only.sort(key=lambda t: (t.symbol, t.open_ymd))
    return exact, close_pairs, new_only


def _fmt_ymd(ymd: int) -> str:
    s = f"{ymd:08d}"
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _fmt_px(px: float) -> str:
    """Compact price literal for ThinkScript (preserve meaningful decimals)."""
    text = f"{px:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def markers_for_symbol(
    symbol: str,
    exact: list[Trade],
    close_pairs: list[tuple[Trade, Trade]],
    new_only: list[Trade],
) -> tuple[list[Marker], list[StopSeg]]:
    """
    One entry + one exit marker per logical trade (no duplicate plots),
    plus one red stop-loss segment per plotted trade.

    Grey: exact (MarkTen/new dates) + close-match (prefer MarkTen open; both
    open dates may appear in bubble text only).
    Green: MarkTen-only new trades.
    Stop price: MarkTen/new Closed ``ORIGINAL STOP`` (canonical for shared).

    Dedup keys: marker (kind, ymd, color) and trade (color, close_ymd, exit_px).
    """
    markers: list[Marker] = []
    stops: list[StopSeg] = []
    seen_marker: set[tuple[str, int, str]] = set()  # kind, ymd, color
    seen_trade: set[tuple[str, int, float]] = set()  # color, close_ymd, exit_px

    def add(ymd: int, kind: str, color: str, note: str = "", bubble: str = "") -> None:
        if not ymd:
            return
        key = (kind, ymd, color)
        if key in seen_marker:
            return
        seen_marker.add(key)
        markers.append(
            Marker(ymd=ymd, kind=kind, color=color, note=note, bubble=bubble)
        )

    def add_trade(
        *,
        open_ymd: int,
        close_ymd: int,
        exit_px: float,
        stop_px: float,
        color: str,
        entry_note: str,
        exit_note: str,
        entry_bubble: str = "",
        exit_bubble: str = "",
    ) -> None:
        trade_key = (color, close_ymd, round(exit_px, 4) if exit_px else 0.0)
        if close_ymd and trade_key in seen_trade:
            return
        if close_ymd:
            seen_trade.add(trade_key)
        add(open_ymd, "entry", color, entry_note, entry_bubble)
        add(close_ymd, "exit", color, exit_note, exit_bubble)
        if open_ymd and close_ymd and stop_px > 0:
            stops.append(
                StopSeg(
                    open_ymd=open_ymd,
                    close_ymd=close_ymd,
                    stop=stop_px,
                    note=f"{color} {entry_note}".strip(),
                )
            )

    for t in exact:
        if t.symbol != symbol:
            continue
        # Prefer MarkTen/new row dates (exact list is already new-stamp rows).
        add_trade(
            open_ymd=t.open_ymd,
            close_ymd=t.close_ymd,
            exit_px=t.exit,
            stop_px=t.stop,
            color="grey",
            entry_note="exact",
            exit_note="exact",
        )

    for ot, nt in close_pairs:
        if nt.symbol != symbol:
            continue
        # Single In on MarkTen (canonical) open; both dates in bubble text only.
        entry_bubble = (
            f"IN > {_fmt_ymd(nt.open_ymd)}"
            f" (111201:{_fmt_ymd(ot.open_ymd)})"
        )
        add_trade(
            open_ymd=nt.open_ymd,
            close_ymd=nt.close_ymd or ot.close_ymd,
            exit_px=nt.exit or ot.exit,
            stop_px=nt.stop or ot.stop,
            color="grey",
            entry_note=(
                f"close-match MarkTen ({NEW_STAMP[-6:]}); "
                f"111201 open {_fmt_ymd(ot.open_ymd)}"
            ),
            exit_note="close-match",
            entry_bubble=entry_bubble,
        )

    for t in new_only:
        if t.symbol != symbol:
            continue
        add_trade(
            open_ymd=t.open_ymd,
            close_ymd=t.close_ymd,
            exit_px=t.exit,
            stop_px=t.stop,
            color="green",
            entry_note="MarkTen-only",
            exit_note="MarkTen-only",
        )

    markers.sort(key=lambda m: (m.ymd, 0 if m.kind == "entry" else 1, m.color))
    stops.sort(key=lambda s: (s.open_ymd, s.close_ymd, s.stop))
    return markers, stops


def build_study_lines(
    symbol: str,
    markers: list[Marker],
    expansion: ExpansionParam,
    stops: list[StopSeg] | None = None,
) -> list[str]:
    grey_e = [m for m in markers if m.color == "grey" and m.kind == "entry"]
    grey_x = [m for m in markers if m.color == "grey" and m.kind == "exit"]
    green_e = [m for m in markers if m.color == "green" and m.kind == "entry"]
    green_x = [m for m in markers if m.color == "green" and m.kind == "exit"]
    stop_segs = stops or []

    exp = expansion.value
    exp_lit = f"{exp:.6g}"  # compact but precise enough for ThinkScript

    lines: list[str] = [
        f"# RL trade-diff {symbol} — {OLD_STAMP} (2.4%) vs MarkTen {NEW_STAMP} (4.1%)",
        "# SMA20=red, SMA50=white, SMA100=yellow, SMA200=purple (Color.VIOLET)",
        "# SMA50Up20=white = SMA50 * 1.20 (distinct from SMA50)",
        f"# SMA50Exp=green = SMA50 * {exp_lit}  [rl_expansion from {expansion.source}]",
        "# SMA50 = Average(close, 50)  [same simple mean as rocket_rl / AWK]",
        "# Dip band (RL gate): upper = SMA * rl_dip_pct; lower = SMA * (1 - (rl_dip_pct - 1))",
        "# Band colors depend on SMA stack (smaStackBull = SMA20>SMA50 AND SMA50>SMA100 AND SMA100>SMA200):",
        f"#   stack bull: grey cloud = rl_dip_pct={DIP_PCT_24} ({OLD_STAMP}); "
        f"green cloud = rl_dip_pct={DIP_PCT_41} ({NEW_STAMP})",
        "#   else: BOTH 2.4% and 4.1% bands translucent red",
        "# Markers: GREY = exact or close-match (both systems); GREEN = MarkTen-only new trades",
        "# Stop lines: RED horizontal ORIGINAL STOP from open through close (MarkTen Closed)",
        "# Note: SMA50Exp line is Color.GREEN (solid) — distinct from green trade markers/clouds",
        f"# Counts: grey_in={len(grey_e)} grey_out={len(grey_x)} "
        f"green_in={len(green_e)} green_out={len(green_x)} stop_segs={len(stop_segs)}",
        "",
        "declare upper;",
        "",
        "input showSMA = yes;",
        "input showSMA50Up20 = yes;",
        "input showSMA50Exp = yes;",
        "input showBand24 = yes;",
        "input showBand41 = yes;",
        "input showGreyEntries = yes;",
        "input showGreyExits = yes;",
        "input showGreenEntries = yes;",
        "input showGreenExits = yes;",
        "input showStopLoss = yes;",
        "input dipPct24 = 1.024;",
        "input dipPct41 = 1.041;",
        f"input rlExpansion = {exp_lit};",
        "",
        "def isWeekly = GetAggregationPeriod() == AggregationPeriod.WEEK;",
        "",
        "# ---- SMAs + RL dip bands ----",
        # ThinkScript identifiers are case-insensitive: def names must not collide
        # with plot names (e.g. band41Hi vs Band41Hi, ge1 vs GE1).
        "def smaLen20 = Average(close, 20);",
        "def smaLen50 = Average(close, 50);",
        "def smaLen100 = Average(close, 100);",
        "def smaLen200 = Average(close, 200);",
        "def sma50Up20Val = smaLen50 * 1.20;",
        "def sma50ExpVal = smaLen50 * rlExpansion;",
        "def smaStackBull = smaLen20 > smaLen50 and smaLen50 > smaLen100 and smaLen100 > smaLen200;",
        "",
        "DefineGlobalColor(\"BandGrey\", Color.GRAY);",
        "DefineGlobalColor(\"BandGreen\", Color.GREEN);",
        "DefineGlobalColor(\"BandRed\", Color.RED);",
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
        "plot SMA50Up20 = sma50Up20Val;",
        "SMA50Up20.SetDefaultColor(Color.WHITE);",
        "SMA50Up20.SetLineWeight(2);",
        "SMA50Up20.SetStyle(Curve.LONG_DASH);",
        "SMA50Up20.SetHiding(!showSMA50Up20);",
        "",
        "plot SMA50Exp = sma50ExpVal;",
        "SMA50Exp.SetDefaultColor(Color.GREEN);",
        "SMA50Exp.SetLineWeight(2);",
        "SMA50Exp.SetStyle(Curve.FIRM);",
        "SMA50Exp.SetHiding(!showSMA50Exp);",
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
        "def rlBand24Hi = smaLen50 * dipPct24;",
        "def rlBand24Lo = smaLen50 * (1 - (dipPct24 - 1));",
        "def rlBand41Hi = smaLen50 * dipPct41;",
        "def rlBand41Lo = smaLen50 * (1 - (dipPct41 - 1));",
        "",
        "# Dual clouds: bull-stack keeps grey/green; broken stack paints both red.",
        "# NaN on the inactive set so only one cloud paints each bar.",
        "plot Band41HiOk = if showBand41 and smaStackBull then rlBand41Hi else Double.NaN;",
        "plot Band41LoOk = if showBand41 and smaStackBull then rlBand41Lo else Double.NaN;",
        "plot Band41HiBad = if showBand41 and !smaStackBull then rlBand41Hi else Double.NaN;",
        "plot Band41LoBad = if showBand41 and !smaStackBull then rlBand41Lo else Double.NaN;",
        "Band41HiOk.SetDefaultColor(Color.GREEN);",
        "Band41LoOk.SetDefaultColor(Color.GREEN);",
        "Band41HiBad.SetDefaultColor(Color.RED);",
        "Band41LoBad.SetDefaultColor(Color.RED);",
        "Band41HiOk.SetStyle(Curve.SHORT_DASH);",
        "Band41LoOk.SetStyle(Curve.SHORT_DASH);",
        "Band41HiBad.SetStyle(Curve.SHORT_DASH);",
        "Band41LoBad.SetStyle(Curve.SHORT_DASH);",
        "AddCloud(Band41HiOk, Band41LoOk, GlobalColor(\"BandGreen\"), GlobalColor(\"BandGreen\"));",
        "AddCloud(Band41HiBad, Band41LoBad, GlobalColor(\"BandRed\"), GlobalColor(\"BandRed\"));",
        "",
        "plot Band24HiOk = if showBand24 and smaStackBull then rlBand24Hi else Double.NaN;",
        "plot Band24LoOk = if showBand24 and smaStackBull then rlBand24Lo else Double.NaN;",
        "plot Band24HiBad = if showBand24 and !smaStackBull then rlBand24Hi else Double.NaN;",
        "plot Band24LoBad = if showBand24 and !smaStackBull then rlBand24Lo else Double.NaN;",
        "Band24HiOk.SetDefaultColor(Color.GRAY);",
        "Band24LoOk.SetDefaultColor(Color.GRAY);",
        "Band24HiBad.SetDefaultColor(Color.RED);",
        "Band24LoBad.SetDefaultColor(Color.RED);",
        "Band24HiOk.SetStyle(Curve.SHORT_DASH);",
        "Band24LoOk.SetStyle(Curve.SHORT_DASH);",
        "Band24HiBad.SetStyle(Curve.SHORT_DASH);",
        "Band24LoBad.SetStyle(Curve.SHORT_DASH);",
        "AddCloud(Band24HiOk, Band24LoOk, GlobalColor(\"BandGrey\"), GlobalColor(\"BandGrey\"));",
        "AddCloud(Band24HiBad, Band24LoBad, GlobalColor(\"BandRed\"), GlobalColor(\"BandRed\"));",
        "",
    ]

    def emit_group(
        items: list[Marker],
        *,
        prefix: str,
        label: str,
        color: str,
        show_input: str,
        is_entry: bool,
    ) -> None:
        if not items:
            lines.append(f"# (no {label})")
            lines.append("")
            return
        lines.append(f"# ===================== {label.upper()} =====================")
        # Hit defs use "{prefix}{i}Hit" so they never collide with plots GE1/GX1/...
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
                f'"{bubble}", {color}, {above});'
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
            lines.append(f"{plot_prefix}{i}.SetDefaultColor({color});")
            lines.append(f"{plot_prefix}{i}.SetLineWeight(4);")
        lines.append("")

    emit_group(
        grey_e,
        prefix="ge",
        label="grey entries (exact/close)",
        color="Color.GRAY",
        show_input="showGreyEntries",
        is_entry=True,
    )
    emit_group(
        grey_x,
        prefix="gx",
        label="grey exits (exact/close)",
        color="Color.GRAY",
        show_input="showGreyExits",
        is_entry=False,
    )
    emit_group(
        green_e,
        prefix="ne",
        label="green entries (MarkTen-only)",
        color="Color.GREEN",
        show_input="showGreenEntries",
        is_entry=True,
    )
    emit_group(
        green_x,
        prefix="nx",
        label="green exits (MarkTen-only)",
        color="Color.GREEN",
        show_input="showGreenExits",
        is_entry=False,
    )

    # Red stop-loss segments: one plot per trade, open..close inclusive.
    # Def names use slNRng (not slN) so they never collide with plot SLN (case-insensitive).
    if not stop_segs:
        lines.append("# (no stop-loss segments)")
        lines.append("")
    else:
        lines.append("# ===================== STOP LOSS (ORIGINAL STOP) =====================")
        for i, seg in enumerate(stop_segs, 1):
            note = f"  # {seg.note}" if seg.note else ""
            lines.append(
                f"def sl{i}Rng = GetYYYYMMDD() >= {seg.open_ymd} "
                f"and GetYYYYMMDD() <= {seg.close_ymd};{note}"
            )
        lines.append("")
        for i, seg in enumerate(stop_segs, 1):
            px = _fmt_px(seg.stop)
            lines.append(
                f"plot SL{i} = if showStopLoss and sl{i}Rng "
                f"then {px} else Double.NaN;"
            )
        lines.append("")
        for i in range(1, len(stop_segs) + 1):
            lines.append(f"SL{i}.SetDefaultColor(Color.RED);")
            lines.append(f"SL{i}.SetLineWeight(2);")
            lines.append(f"SL{i}.SetStyle(Curve.FIRM);")
        lines.append("")

    return lines

def write_readme(
    output_dir: Path,
    *,
    exact_n: int,
    close_n: int,
    new_n: int,
    per_sym: dict[str, dict[str, int]],
    expansion: ExpansionParam,
) -> Path:
    exp_lit = f"{expansion.value:.6g}"
    lines = [
        "# RL trade-diff ThinkorSwim studies",
        "",
        f"Compare Closed ledgers `{OLD_STAMP}` (rl_dip_pct=1.024) vs MarkTen "
        f"`{NEW_STAMP}` (rl_dip_pct=1.041).",
        "",
        f"- Same or close enough: **{exact_n + close_n}** "
        f"({exact_n} exact + {close_n} close-match) → **grey** markers",
        f"- New MarkTen-only: **{new_n}** → **green** markers",
        "",
        "## Colors / bands",
        "",
        "| Element | Meaning |",
        "|---------|---------|",
        "| Grey arrows/bubbles | Trade in both systems (exact date match, or one of the 6 close-matches) |",
        "| Green arrows/bubbles | Trade only in MarkTen 144725 (new) |",
        "| Red SMA20 | `Average(close, 20)` |",
        "| White SMA50 | `Average(close, 50)` — same simple 50-bar mean as rocket_rl / AWK |",
        "| White SMA50Up20 (dashed) | `SMA50 × 1.20` — named distinctly from SMA50 |",
        f"| Green SMA50Exp (solid) | `SMA50 × {exp_lit}` — `rl_expansion` from Report/Audit "
        f"({expansion.source}); distinct from green trade markers/clouds |",
        "| Yellow SMA100 | `Average(close, 100)` |",
        "| Purple SMA200 | `Average(close, 200)` — `Color.VIOLET` |",
        "| Grey / green clouds | Only when **SMA20 > SMA50 AND SMA50 > SMA100 AND SMA100 > SMA200** |",
        "| Red clouds (both bands) | When that SMA stack is broken — 2.4% and 4.1% both red |",
        "| Red stop-loss lines (`SL1`…) | `ORIGINAL STOP` from MarkTen Closed, horizontal from open through close (inclusive) |",
        "",
        "Band widths (always):",
        "",
        "- 2.4% band: `upper = SMA×1.024`, `lower = SMA×0.976`",
        "- 4.1% band: `upper = SMA×1.041`, `lower = SMA×0.959`",
        "",
        f"**Expansion line:** `SMA50Exp = SMA50 × rl_expansion` with "
        f"`rl_expansion={exp_lit}` (Report/Audit stores the **multiplier** form "
        f"`1.163`, not the fraction `0.163`). Loaded at generate-time from "
        f"`RL_Report_{NEW_STAMP}.csv` / `RL_Audit_Report_…` (fallback "
        f"`{OLD_STAMP}`, then engine default `{DEFAULT_RL_EXPANSION}`).",
        "",
        "**Color logic** (`smaStackBull = SMA20 > SMA50 and SMA50 > SMA100 and SMA100 > SMA200`):",
        "",
        "- If `smaStackBull`: 2.4% cloud grey, 4.1% cloud green (current look)",
        "- Else: **both** dip bands translucent red (dual `AddCloud` plots; inactive set is `NaN`)",
        "",
        "Band formula matches the RL dip gate (`rl_dip_pct` in rocket_rl / portfolio_audit.awk):",
        "",
        "```",
        "dip_hi = y_sma * rl_dip_pct",
        "dip_lo = y_sma * (1 - (rl_dip_pct - 1))",
        "```",
        "",
        "Note: the live gate uses **prior-bar** SMA50; the study shades the band around the "
        "current-bar SMA50 for chart readability (same width).",
        "",
        "Close-matches plot **one** grey In on the MarkTen open date (not the earlier "
        "111201 open). The bubble text notes both dates when they differ. "
        "Each logical trade is deduped by `(color, exit_date, exit_price)` so nothing "
        "double-fires.",
        "",
        "**Stop-loss lines:** one red horizontal segment per plotted trade (grey shared "
        "and green MarkTen-only). Price from Closed column `ORIGINAL STOP` on the "
        "MarkTen (`144725`) row; span is `GetYYYYMMDD() >= open and <= close`. Toggle "
        "with `showStopLoss`.",
        "",
        "## Files",
        "",
        "| Symbol | Grey IN | Grey OUT | Green IN | Green OUT | SL segs | File |",
        "|--------|--------:|---------:|---------:|----------:|--------:|------|",
    ]
    for sym in SYMBOLS:
        c = per_sym.get(sym, {})
        lines.append(
            f"| {sym} | {c.get('grey_in', 0)} | {c.get('grey_out', 0)} | "
            f"{c.get('green_in', 0)} | {c.get('green_out', 0)} | "
            f"{c.get('stops', 0)} | "
            f"`RL_{sym}_trade_diff_111201_vs_144725.ts` |"
        )
    lines.extend(
        [
            "",
            "## How to import into ThinkorSwim",
            "",
            "1. Open a **daily** chart for the symbol (e.g. AMD).",
            "2. Studies → Edit Studies → **Create…**",
            "3. Open the matching `.ts` file in a text editor, copy all, paste into the study editor.",
            "4. Name it e.g. `RL AMD trade diff 111201 vs 144725` and apply.",
            "5. Toggle inputs as needed: `showSMA50Up20`, `showSMA50Exp`, `showBand24`, "
            "`showBand41`, grey/green entry/exit flags, `showStopLoss`.",
            "",
            "Regenerate:",
            "",
            "```",
            "python tos/gen_rl_trade_diff_studies.py",
            "```",
            "",
            "## Sources",
            "",
            f"- `drive/RL_Closed_{OLD_STAMP}.csv`",
            f"- `drive/RL_Closed_{NEW_STAMP}.csv`",
            f"- `rl_expansion` from `drive/RL_Report_{NEW_STAMP}.csv` "
            f"(fallback Audit / `{OLD_STAMP}` / default {DEFAULT_RL_EXPANSION})",
            "- Close-match pairs: canvas/HTML rl-stamp-trade-diff (6 pairs)",
            "",
        ]
    )
    path = output_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output directory (default: {DEFAULT_OUT})",
    )
    ap.add_argument(
        "--old-csv",
        type=Path,
        default=DRIVE / f"RL_Closed_{OLD_STAMP}.csv",
    )
    ap.add_argument(
        "--new-csv",
        type=Path,
        default=DRIVE / f"RL_Closed_{NEW_STAMP}.csv",
    )
    args = ap.parse_args(argv)

    expansion = load_rl_expansion(DRIVE)
    print(f"rl_expansion={expansion.value} from {expansion.source}")

    old = load_closed(args.old_csv)
    new = load_closed(args.new_csv)
    exact, close_pairs, new_only = classify_trades(old, new)

    print(
        f"Classified: exact={len(exact)} close={len(close_pairs)} "
        f"new_only={len(new_only)} (old={len(old)} new={len(new)})"
    )
    if len(exact) != 22 or len(close_pairs) != 6 or len(new_only) != 23:
        print(
            f"WARNING: expected 22/6/23, got {len(exact)}/{len(close_pairs)}/{len(new_only)}",
            file=sys.stderr,
        )

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    per_sym: dict[str, dict[str, int]] = {}
    for sym in SYMBOLS:
        markers, stops = markers_for_symbol(sym, exact, close_pairs, new_only)
        lines = build_study_lines(sym, markers, expansion, stops)
        fname = f"RL_{sym}_trade_diff_111201_vs_144725.ts"
        path = out_dir / fname
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(fname)
        per_sym[sym] = {
            "grey_in": sum(1 for m in markers if m.color == "grey" and m.kind == "entry"),
            "grey_out": sum(1 for m in markers if m.color == "grey" and m.kind == "exit"),
            "green_in": sum(1 for m in markers if m.color == "green" and m.kind == "entry"),
            "green_out": sum(1 for m in markers if m.color == "green" and m.kind == "exit"),
            "stops": len(stops),
        }
        print(
            f"  {sym}: grey_in={per_sym[sym]['grey_in']} grey_out={per_sym[sym]['grey_out']} "
            f"green_in={per_sym[sym]['green_in']} green_out={per_sym[sym]['green_out']} "
            f"stops={per_sym[sym]['stops']} -> {path}"
        )

    readme = write_readme(
        out_dir,
        exact_n=len(exact),
        close_n=len(close_pairs),
        new_n=len(new_only),
        per_sym=per_sym,
        expansion=expansion,
    )
    print(f"README: {readme}")
    print(f"Output dir: {out_dir.resolve()}")
    for f in written:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
