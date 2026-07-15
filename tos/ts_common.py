"""Shared thinkScript builder for zone/trade chart studies."""
from __future__ import annotations

from pathlib import Path

# ROYGBIV minus Red and Green (reserved for exits / old BO green)
ZONE_COLORS = [
    "Color.ORANGE",
    "Color.YELLOW",
    "Color.BLUE",
    "Color.CYAN",
    "Color.VIOLET",
]

COLOR_NAMES = ["Orange", "Yellow", "Blue", "Cyan", "Violet"]


def zone_color(index: int) -> str:
    """1-based zone index -> thinkScript Color constant."""
    return ZONE_COLORS[(index - 1) % len(ZONE_COLORS)]


def color_name(index: int) -> str:
    return COLOR_NAMES[(index - 1) % len(COLOR_NAMES)]


def event_hit_expr(date: int) -> str:
    return (
        f"if !isWeekly then GetYYYYMMDD() == {date} else "
        f"((IsNaN(GetYYYYMMDD()[1]) and GetYYYYMMDD() >= {date}) "
        f"or ({date} > GetYYYYMMDD()[1] and {date} <= GetYYYYMMDD()))"
    )


def build_lines(
    symbol: str,
    zones: list[tuple[int, float, float, int]],
    entries: list[int],
    exits: list[int],
    *,
    extra_header: str = "",
) -> list[str]:
    """
    zones: list of (pivot_yyyymmdd, zone_lo, zone_hi, breakout_yyyymmdd).
    breakout_yyyymmdd=0 means cloud only (no BO marker).
    """
    lines: list[str] = [
        f"# {symbol} — zones (pivot date) + matching-color BO + entries/exits",
        "# Daily AND Weekly. Zone colors cycle O-Y-B-C-V (ROYGBIV minus R/G).",
        "# Entries white, exits red.",
    ]
    if extra_header:
        lines.append(f"# {extra_header}")
    lines.extend(
        [
            "",
            "declare upper;",
            "",
            "input showZones = yes;",
            "input showBreakouts = yes;",
            "input showEntries = yes;",
            "input showExits = yes;",
            "",
            "def isWeekly = GetAggregationPeriod() == AggregationPeriod.WEEK;",
            "",
        ]
    )

    for i, (pivot, lo, hi, bo) in enumerate(zones, 1):
        col = zone_color(i)
        cname = color_name(i)
        bo_note = f"  BO={bo}" if bo > 0 else "  (no BO date)"
        lines.append(f"# Zone {i} ({cname}): pivot {pivot}  lo={lo} hi={hi}{bo_note}")
        lines.append(
            f"def z{i}OnW = (IsNaN(GetYYYYMMDD()[1]) and GetYYYYMMDD() >= {pivot}) "
            f"or ({pivot} > GetYYYYMMDD()[1] and {pivot} <= GetYYYYMMDD());"
        )
        lines.append(
            f"def z{i}On = if !isWeekly then GetYYYYMMDD() >= {pivot} else (z{i}On[1] or z{i}OnW);"
        )
        lines.append(f"def z{i}HiV = if showZones and z{i}On then {hi:.2f} else Double.NaN;")
        lines.append(f"def z{i}LoV = if showZones and z{i}On then {lo:.2f} else Double.NaN;")
        lines.append(f"def z{i}Hi = if showZones and z{i}On then HighestAll(z{i}HiV) else Double.NaN;")
        lines.append(f"def z{i}Lo = if showZones and z{i}On then LowestAll(z{i}LoV) else Double.NaN;")
        lines.append(f"AddCloud(z{i}Hi, z{i}Lo, {col}, {col});")
        lines.append("")

    lines.append("# ===================== BREAKOUTS (same color as zone) =====================")
    for i, (_, _, _, bo) in enumerate(zones, 1):
        if bo <= 0:
            continue
        col = zone_color(i)
        cname = color_name(i)
        lines.append(f"# BO zone {i} ({cname})")
        lines.append(f"def bo{i}Hit = {event_hit_expr(bo)};")
        lines.append(
            f'AddChartBubble(showBreakouts and bo{i}Hit, high, "BO >", {col}, yes);'
        )
    lines.append("")

    lines.append("# ===================== ENTRIES (white) =====================")
    for i, d in enumerate(entries, 1):
        lines.append(f"def e{i} = {event_hit_expr(d)};")
    lines.append("")
    for i in range(1, len(entries) + 1):
        lines.append(f'AddChartBubble(showEntries and e{i}, low, "IN >", Color.WHITE, no);')
        lines.append(f"plot Entry{i} = if showEntries and e{i} then low else Double.NaN;")
    lines.append("")
    for i in range(1, len(entries) + 1):
        lines.append(f"Entry{i}.SetPaintingStrategy(PaintingStrategy.ARROW_UP);")
        lines.append(f"Entry{i}.SetDefaultColor(Color.WHITE);")
        lines.append(f"Entry{i}.SetLineWeight(4);")

    lines.append("")
    lines.append("# ===================== EXITS (red) =====================")
    for i, d in enumerate(exits, 1):
        lines.append(f"def x{i} = {event_hit_expr(d)};")
    lines.append("")
    for i in range(1, len(exits) + 1):
        lines.append(f'AddChartBubble(showExits and x{i}, high, "OUT >", Color.RED, yes);')
        lines.append(f"plot Exit{i} = if showExits and x{i} then high else Double.NaN;")
    lines.append("")
    for i in range(1, len(exits) + 1):
        lines.append(f"Exit{i}.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);")
        lines.append(f"Exit{i}.SetDefaultColor(Color.RED);")
        lines.append(f"Exit{i}.SetLineWeight(4);")

    return lines


def write_ts_files(
    symbol: str,
    zones: list[tuple[int, float, float, int]],
    entries: list[int],
    exits: list[int],
    *,
    output_dir: Path | None = None,
    repo_root: Path | None = None,
    extra_header: str = "",
) -> Path:
    text = "\n".join(build_lines(symbol, zones, entries, exits, extra_header=extra_header)) + "\n"
    fname = f"{symbol.upper()}_zones_trades.ts"
    paths: list[Path] = []
    if output_dir is not None:
        dests = [Path(output_dir).resolve() / fname]
    else:
        root = repo_root or Path(__file__).resolve().parents[1]
        dests = [root / "tos" / fname, root / "drive" / "tos" / fname]
    for dest in dests:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        paths.append(dest)
        print(f"Wrote {dest}")
    bo_count = sum(1 for *_, bo in zones if bo > 0)
    print(
        f"{symbol}: {len(zones)} zones, {bo_count} BO markers, "
        f"{len(entries)} entries, colors cycle {', '.join(COLOR_NAMES)}"
    )
    return paths[0]
