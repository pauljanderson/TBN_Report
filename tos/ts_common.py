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

# Untraded BRT zones (no Closed/Open match)
UNTRADED_COLOR = "Color.GRAY"
UNTRADED_COLOR_NAME = "Gray"


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
    traded: list[bool] | None = None,
    study_label: str | None = None,
) -> list[str]:
    """
    zones: list of (pivot_yyyymmdd, zone_lo, zone_hi, breakout_yyyymmdd).
    breakout_yyyymmdd=0 means cloud only (no BO marker).
    traded: optional per-zone flags; False -> Color.GRAY cloud (no BO).
            None -> all zones colored (legacy gen_* behavior).
    study_label: header name (default: symbol). Use e.g. "BRT NVDA".
    """
    label = study_label or symbol
    if traded is not None and len(traded) != len(zones):
        raise ValueError(f"traded length {len(traded)} != zones length {len(zones)}")

    if traded is None:
        color_note = "Zone colors cycle O-Y-B-C-V (ROYGBIV minus R/G)."
    else:
        color_note = (
            "Traded zones cycle O-Y-B-C-V (ROYGBIV minus R/G); "
            "untraded zones are Gray."
        )

    lines: list[str] = [
        f"# {label} - zones (maturity/pivot date) + matching-color BO + entries/exits",
        f"# Daily AND Weekly. {color_note}",
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

    traded_color_i = 0
    zone_meta: list[tuple[str, str, bool]] = []  # col, cname, is_traded

    for i, (pivot, lo, hi, bo) in enumerate(zones, 1):
        is_traded = True if traded is None else bool(traded[i - 1])
        if is_traded:
            traded_color_i += 1
            col = zone_color(traded_color_i if traded is not None else i)
            cname = color_name(traded_color_i if traded is not None else i)
        else:
            col = UNTRADED_COLOR
            cname = UNTRADED_COLOR_NAME
        zone_meta.append((col, cname, is_traded))

        status = "traded" if is_traded else "untraded/grey"
        bo_note = f"  BO={bo}" if bo > 0 else "  (no BO date)"
        lines.append(
            f"# Zone {i} ({cname}, {status}): start {pivot}  lo={lo} hi={hi}{bo_note}"
        )
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

    lines.append("# ===================== BREAKOUTS (same color as zone; traded only) =====================")
    for i, ((_, _, _, bo), (col, cname, is_traded)) in enumerate(zip(zones, zone_meta), 1):
        if bo <= 0 or not is_traded:
            continue
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
    traded: list[bool] | None = None,
    study_label: str | None = None,
    filename: str | None = None,
) -> Path:
    text = (
        "\n".join(
            build_lines(
                symbol,
                zones,
                entries,
                exits,
                extra_header=extra_header,
                traded=traded,
                study_label=study_label,
            )
        )
        + "\n"
    )
    fname = filename or f"{symbol.upper()}_zones_trades.ts"
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
    n_traded = sum(1 for t in traded if t) if traded is not None else len(zones)
    n_grey = (len(zones) - n_traded) if traded is not None else 0
    print(
        f"{symbol}: {len(zones)} zones ({n_traded} traded/colored, {n_grey} grey), "
        f"{bo_count} BO markers, {len(entries)} entries, colors cycle {', '.join(COLOR_NAMES)}"
    )
    return paths[0]
