"""No-bet ROI after a moneyline 60→70 hysteresis cross, 15–60 minutes in.

Research only. Reuses the odds-cross event cache and official settlements.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not restart jobs.
"""
from __future__ import annotations

import csv
import html
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from odds_cross_winrate_20261020 import (
    PAGE as PARENT_PAGE,
    SETTLE_CACHE,
    STAMP,
    attach_results,
    build_index,
    drop_empty_book_crosses,
    game_norm,
    iso,
    load_stream_cache,
    parse_dt,
    timing_bucket,
)
from prediction_paths import RAW_DIR as RAW
from price_memory import to_et
PAGE = STAMP / "odds_cross_no_roi_60_70_20261020.html"
JSON_OUT = RAW / "odds_cross_no_roi_60_70_20261020.json"
CSV_OUT = RAW / "odds_cross_no_roi_60_70_20261020.csv"
ET = ZoneInfo("America/New_York")

ASKED = (
    "if we bet no on a side that goes from 60-70 during 15m - 60m after the start of a match, "
    "what would our average return on investment be? (given the results we've tracked thus far)"
)
PLAIN = (
    "A prediction-market Yes price is a dollar from 0 to 1, also read as an implied chance: "
    "0.70 means the venue is pricing that named side at 70 percent. This slice watches moneyline "
    "(who wins the game) only. We take the first hysteresis up-cross from under 60 cents to over "
    "70 cents — the Yes price was strictly below 0.60, then later strictly above 0.70 — one row "
    "per game, side, and venue. If that first jump happened between 15 and 60 minutes after the "
    "listed start, we buy No on that same side at the Yes price of that first print above 0.70. "
    "No costs one dollar minus that Yes price. If the side loses, No pays a dollar. If the side "
    "wins, No pays nothing and the stake is gone. Return on investment (ROI) is the mean of those "
    "trade-by-trade returns with an equal one-dollar stake on each No. Official win or loss comes "
    "from venue settlement (Kalshi result, Gemini resolution). Games still open are pending and "
    "are left out. Unknown start times are excluded, not dumped into this window. Research only. "
    "Not gold. Not DailyRun. Not a trading rule."
)

WINDOW_LO = 15.0
WINDOW_HI = 60.0


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value) -> str:
    return f"<td>{esc('' if value is None else value)}</td>"


def table(headers: list[tuple[str, str]], rows: list[dict], fields: list[str]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = [td(row.get(field, "")) for field in fields]
        body.append("<tr>" + "".join(cells) + "</tr>")
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def minutes_into(row: dict) -> float | None:
    cross_dt = parse_dt(row.get("cross_time"))
    start_dt = parse_dt(row.get("game_start"))
    if cross_dt is None or start_dt is None:
        return None
    return (to_et(cross_dt) - to_et(start_dt)).total_seconds() / 60.0


def tiny_note(n: int) -> str:
    if n <= 0:
        return "no settled rows"
    if n < 20:
        return "tiny sample"
    if n < 50:
        return "small sample"
    return ""


def kalshi_fee(no_cost: float) -> float:
    price = Decimal(str(no_cost))
    raw = Decimal("0.07") * price * (Decimal("1") - price)
    if raw < 0:
        raw = Decimal("0")
    return float(raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def gemini_fee(no_cost: float) -> float:
    price = Decimal(str(no_cost))
    raw = Decimal("0.07") * price * (Decimal("1") - price)
    if raw < 0:
        raw = Decimal("0")
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING))


def poly_fee(no_cost: float, theta: str = "0.0695") -> float:
    price = Decimal(str(no_cost))
    raw = Decimal(theta) * price * (Decimal("1") - price)
    if raw < 0:
        raw = Decimal("0")
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def venue_fee(venue: str, no_cost: float) -> float | None:
    name = (venue or "").strip().lower()
    if name == "kalshi":
        return kalshi_fee(no_cost)
    if name == "gemini":
        return gemini_fee(no_cost)
    if name == "polymarket":
        return poly_fee(no_cost)
    return None


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def pct(part: int, whole: int) -> str:
    if whole <= 0:
        return ""
    return f"{100.0 * part / whole:.1f}"


def fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return ""
    return f"{100.0 * value:.{digits}f}"


def fmt_px(value) -> str:
    number = as_float(value)
    if number is None:
        return ""
    return f"{number:.4f}"


def fmt_signed_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return ""
    return f"{100.0 * value:+.{digits}f}"


def roi_of(no_cost: float, no_wins: bool, fee: float = 0.0) -> float | None:
    cost = no_cost + fee
    if cost <= 0 or cost >= 1:
        return None
    if no_wins:
        return (1.0 / cost) - 1.0
    return -1.0


def backfill_starts(crosses: list[dict], settlements: list[dict]) -> None:
    occ = {}
    for row in settlements:
        if row.get("occurrence") and row.get("game_n"):
            occ.setdefault(row["game_n"], row["occurrence"])
    for cross in crosses:
        if cross.get("game_start"):
            continue
        occ_raw = occ.get(game_norm(cross.get("game") or ""))
        start = parse_dt(occ_raw)
        if start is None:
            continue
        cross["game_start"] = iso(start)
        timing, mins, bucket = timing_bucket(parse_dt(cross.get("cross_time")), start)
        cross["timing"] = timing
        cross["minutes_into_game"] = mins
        cross["during_bucket"] = bucket if timing == "during" else timing
        cross["start_source"] = "occurrence_backfill"


def annotate_crosses(crosses: list[dict]) -> None:
    for row in crosses:
        if not row.get("start_source"):
            row["start_source"] = "feed" if row.get("game_start") else ""
        minutes = minutes_into(row)
        row["minutes_num"] = minutes
        if minutes is None:
            row["timing"] = "unknown"
            row["during_bucket"] = "unknown"
            row["minutes_into_game"] = ""
            continue
        timing, mins, bucket = timing_bucket(parse_dt(row.get("cross_time")), parse_dt(row.get("game_start")))
        row["timing"] = timing
        row["minutes_into_game"] = mins
        row["during_bucket"] = bucket if timing == "during" else timing


def trade_from(row: dict) -> dict | None:
    yes_px = as_float(row.get("first_above"))
    if yes_px is None or yes_px <= 0 or yes_px >= 1:
        return None
    no_cost = 1.0 - yes_px
    if no_cost <= 0 or no_cost >= 1:
        return None
    official = row.get("official") or ""
    no_wins = official == "loss"
    yes_wins = official == "win"
    roi = roi_of(no_cost, no_wins) if official in ("win", "loss") else None
    fee = venue_fee(row.get("venue") or "", no_cost)
    fee_roi = roi_of(no_cost, no_wins, fee) if fee is not None and official in ("win", "loss") else None
    kalshi_all_roi = (
        roi_of(no_cost, no_wins, kalshi_fee(no_cost))
        if official in ("win", "loss")
        else None
    )
    return {
        "sport": row.get("sport") or "",
        "game": row.get("game") or "",
        "side": row.get("side") or "",
        "venue": row.get("venue") or "",
        "band": row.get("band") or "",
        "cross_time": row.get("cross_time") or "",
        "game_start": row.get("game_start") or "",
        "minutes_into_game": row.get("minutes_into_game") or "",
        "minutes_num": row.get("minutes_num"),
        "timing": row.get("timing") or "",
        "during_bucket": row.get("during_bucket") or "",
        "start_source": row.get("start_source") or "",
        "first_below": row.get("first_below"),
        "yes_price_at_cross": yes_px,
        "no_cost": no_cost,
        "official": official,
        "official_source": row.get("official_source") or "",
        "no_result": "win" if no_wins else ("loss" if yes_wins else official),
        "roi": roi,
        "fee": fee,
        "fee_roi": fee_roi,
        "kalshi_all_roi": kalshi_all_roi,
        "pnl_1_stake": roi if roi is not None else None,
        "pnl_1_contract": (1.0 - no_cost) if no_wins else (-no_cost if yes_wins else None),
    }


def summarize(trades: list[dict], label: str) -> dict:
    settled = [t for t in trades if t.get("official") in ("win", "loss") and t.get("roi") is not None]
    pending = [t for t in trades if t.get("official") == "pending"]
    no_wins = [t for t in settled if t["no_result"] == "win"]
    yes_wins = [t for t in settled if t["official"] == "win"]
    rois = [t["roi"] for t in settled]
    costs = [t["no_cost"] for t in settled]
    fee_rois = [t["fee_roi"] for t in settled if t.get("fee_roi") is not None]
    fee_n = len(fee_rois)
    kalshi_rois = [t["kalshi_all_roi"] for t in settled if t.get("kalshi_all_roi") is not None]
    n = len(settled)
    avg_roi = mean(rois)
    med_roi = median(rois)
    unique_games = len({t.get("game") or "" for t in settled})
    unique_gs = len({((t.get("game") or ""), (t.get("side") or "")) for t in settled})
    n_feed = sum(1 for t in settled if t.get("start_source") == "feed")
    n_backfill = sum(1 for t in settled if t.get("start_source") == "occurrence_backfill")
    return {
        "label": label,
        "n_rows": len(trades),
        "n": n,
        "pending": len(pending),
        "no_wins": len(no_wins),
        "yes_wins": len(yes_wins),
        "no_win_rate": (len(no_wins) / n) if n else None,
        "yes_win_rate": (len(yes_wins) / n) if n else None,
        "avg_roi": avg_roi,
        "avg_roi_pct": (100.0 * avg_roi) if avg_roi is not None else None,
        "median_roi": med_roi,
        "mean_no_cost": mean(costs),
        "total_pnl_1_stake": sum(rois) if rois else None,
        "total_pnl_1_contract": sum(t["pnl_1_contract"] for t in settled if t.get("pnl_1_contract") is not None) if settled else None,
        "unique_games": unique_games,
        "unique_game_side": unique_gs,
        "n_feed_start": n_feed,
        "n_occurrence_backfill": n_backfill,
        "fee_n": fee_n,
        "avg_roi_venue_fee": mean(fee_rois),
        "avg_roi_kalshi_fee_all": mean(kalshi_rois),
        "note": tiny_note(n),
        "by_sport": _group(settled, "sport"),
        "by_venue": _group(settled, "venue"),
    }


def _group(settled: list[dict], field: str) -> list[dict]:
    bags: dict[str, list[dict]] = defaultdict(list)
    for row in settled:
        bags[row.get(field) or ""].append(row)
    out = []
    for key, rows in bags.items():
        rois = [r["roi"] for r in rows if r.get("roi") is not None]
        no_wins = sum(1 for r in rows if r["no_result"] == "win")
        yes_wins = sum(1 for r in rows if r["official"] == "win")
        n = len(rows)
        avg = mean(rois)
        out.append({
            field: key,
            "n": n,
            "no_wins": no_wins,
            "yes_wins": yes_wins,
            "no_win_pct": pct(no_wins, n),
            "yes_win_pct": pct(yes_wins, n),
            "avg_roi_pct": fmt_signed_pct(avg),
            "mean_no_cost": f"{mean([r['no_cost'] for r in rows]):.4f}" if rows else "",
            "total_pnl_1_stake": f"{sum(rois):+.2f}" if rois else "",
            "note": tiny_note(n),
        })
    out.sort(key=lambda r: (-r["n"], r.get(field) or ""))
    return out


def summary_row(item: dict) -> dict:
    return {
        "label": item["label"],
        "n": item["n"],
        "unique_games": item.get("unique_games", ""),
        "pending": item["pending"],
        "no_wins": item["no_wins"],
        "yes_wins": item["yes_wins"],
        "no_win_pct": pct(item["no_wins"], item["n"]),
        "yes_win_pct": pct(item["yes_wins"], item["n"]),
        "avg_roi_pct": fmt_signed_pct(item["avg_roi"]),
        "median_roi_pct": fmt_signed_pct(item.get("median_roi")),
        "mean_no_cost": f"{item['mean_no_cost']:.4f}" if item["mean_no_cost"] is not None else "",
        "total_pnl_1_stake": f"{item['total_pnl_1_stake']:+.2f}" if item["total_pnl_1_stake"] is not None else "",
        "note": item["note"],
    }


SLICE_HEADERS = [
    ("Slice", "text"), ("Settled N", "num"), ("Unique games", "num"), ("Pending", "num"),
    ("No wins", "num"), ("Yes-side wins", "num"),
    ("No win %", "num"), ("Yes-side win %", "num"),
    ("Avg ROI %", "num"), ("Median ROI %", "num"), ("Mean No cost", "num"),
    ("Total $ ($1 No each)", "num"), ("Note", "text"),
]
SLICE_FIELDS = [
    "label", "n", "unique_games", "pending", "no_wins", "yes_wins", "no_win_pct", "yes_win_pct",
    "avg_roi_pct", "median_roi_pct", "mean_no_cost", "total_pnl_1_stake", "note",
]
WINDOW_HEADERS = [("Window", "text")] + SLICE_HEADERS[1:]


def in_main_window(row: dict) -> bool:
    minutes = row.get("minutes_num")
    return minutes is not None and WINDOW_LO <= minutes <= WINDOW_HI


def load_attached() -> tuple[list[dict], dict]:
    stream = load_stream_cache()
    if stream is None:
        raise FileNotFoundError("odds_cross_full_20261020.json missing; parent study cache required")
    if not SETTLE_CACHE.is_file():
        raise FileNotFoundError(SETTLE_CACHE)
    crosses = drop_empty_book_crosses(list(stream["h_crosses"]))
    settlements = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
    index = build_index(settlements)
    attach_results(crosses, stream["last_map"], settlements, index)
    for row in crosses:
        row["start_source"] = "feed" if row.get("game_start") else ""
    backfill_starts(crosses, settlements)
    annotate_crosses(crosses)
    meta = {
        "seen_min": stream.get("seen_min") or "",
        "seen_max": stream.get("seen_max") or "",
        "n_yes": stream.get("n_yes"),
        "n_keys": stream.get("n_keys"),
        "n_lines": stream.get("n_lines"),
        "settle_total": len(settlements),
        "kalshi": sum(1 for r in settlements if r.get("venue") == "Kalshi"),
        "gemini": sum(1 for r in settlements if r.get("venue") == "Gemini"),
    }
    return crosses, meta


def copy_g(path: Path) -> None:
    dest_dir = Path(r"G:\My Drive\paul_experiments\prediction_market_arb_exhaustive_20261017")
    if dest_dir.parent.exists() or Path("G:/").exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / path.name
            shutil.copy2(path, dest)
            print(f"copied {dest}", flush=True)
        except OSError as exc:
            print(f"G: copy skipped: {exc}", flush=True)
    else:
        print("G: not present, skip copy", flush=True)


def patch_parent() -> None:
    text = PARENT_PAGE.read_text(encoding="utf-8")
    follow = (
        " Follow-up: if we bet no on a side that goes from 60-70 during 15m - 60m after the start "
        "of a match, what would our average return on investment be? (given the results we&#x27;ve "
        "tracked thus far) See "
        "<a href=\"odds_cross_no_roi_60_70_20261020.html\">No-bet ROI 60→70</a>."
    )
    old_asked_end = "that there is actually a 70% chance they win, etc.</p></div>"
    if follow.strip() not in text and old_asked_end in text:
        text = text.replace(
            old_asked_end,
            "that there is actually a 70% chance they win, etc." + follow + "</p></div>",
            1,
        )
    elif follow.strip() not in text:
        print("parent What-you-asked block not found; skip ask append", flush=True)
    link_block = (
        "\n<div class=\"callout\"><p><strong>Follow-up slice:</strong> buying No after a moneyline "
        "60→70 hysteresis cross, 15–60 minutes after listed start. "
        "<a href=\"odds_cross_no_roi_60_70_20261020.html\">No-bet return on investment (ROI) 60→70</a> "
        "(recomputed from event-level rows, not from the 69.8% headline).</p></div>\n"
    )
    if "Follow-up slice:" not in text:
        text = re.sub(
            r"</div>(\s*)<h2>Sample and honesty</h2>",
            "</div>" + link_block + r"<h2>Sample and honesty</h2>",
            text,
            count=1,
        )
    PARENT_PAGE.write_text(text, encoding="utf-8")
    print(f"patched {PARENT_PAGE}", flush=True)


def write_html(main: dict, companions: list[dict], windows: list[dict], trades: list[dict],
               counts: dict, meta: dict, now: str) -> None:
    settled = [t for t in trades if t.get("official") in ("win", "loss") and t.get("roi") is not None]
    detail = []
    for row in sorted(settled, key=lambda r: r.get("cross_time") or "", reverse=True):
        detail.append({
            "sport": row["sport"],
            "game": row["game"],
            "side": row["side"],
            "venue": row["venue"],
            "cross_time": row["cross_time"],
            "game_start": row["game_start"],
            "minutes": row["minutes_into_game"],
            "first_below": fmt_px(row["first_below"]),
            "yes_px": fmt_px(row["yes_price_at_cross"]),
            "no_cost": fmt_px(row["no_cost"]),
            "official": row["official"],
            "no_result": row["no_result"],
            "roi_pct": fmt_signed_pct(row["roi"]),
            "pnl": f"{row['pnl_1_stake']:+.4f}" if row.get("pnl_1_stake") is not None else "",
            "source": row["official_source"],
            "start_source": row["start_source"],
        })
    sport_rows = main["by_sport"]
    venue_rows = main["by_venue"]
    n = main["n"]
    headline_roi = fmt_signed_pct(main["avg_roi"])
    headline_med = fmt_signed_pct(main.get("median_roi"))
    no_wr = pct(main["no_wins"], n)
    yes_wr = pct(main["yes_wins"], n)
    mean_cost = f"{main['mean_no_cost']:.4f}" if main["mean_no_cost"] is not None else "n/a"
    total_pnl = f"{main['total_pnl_1_stake']:+.2f}" if main["total_pnl_1_stake"] is not None else "n/a"
    unique_games = main.get("unique_games") or 0
    n_backfill = main.get("n_occurrence_backfill") or 0
    n_feed = main.get("n_feed_start") or 0
    fee_line = "Fees are not subtracted in the primary table. "
    if main["avg_roi_kalshi_fee_all"] is not None and n:
        fee_line += (
            f"Sensitivity: if every No paid the Kalshi sports formula "
            f"0.07 × price × (1 − price) rounded to $0.0001, average ROI would be "
            f"{fmt_signed_pct(main['avg_roi_kalshi_fee_all'])}% on the same {n} trades. "
        )
    if main["avg_roi_venue_fee"] is not None and main["fee_n"]:
        fee_line += (
            f"Venue-specific fees (Kalshi formula on Kalshi, Gemini 0.07 × p × (1 − p) rounded up "
            f"to the next cent on Gemini, Polymarket typical coefficient 0.0695 banker's-cent on "
            f"Polymarket; Novig skipped) cover {main['fee_n']} of {n} settled rows and average "
            f"ROI {fmt_signed_pct(main['avg_roi_venue_fee'])}%. "
        )
    fee_line += "Polymarket’s real coefficient is per-market; 0.0695 is a typical US-sports default, not a lookup."

    arith = (
        "No cost = 1 − yes_price_at_cross, where yes_price_at_cross is the first Yes print strictly "
        "above 0.70 (the hysteresis HI cross). Equal stake $1 on each No: if the named side loses, "
        "No pays $1 and ROI = (1 / no_cost) − 1; if the named side wins, No pays $0 and ROI = −1. "
        "Average ROI is the mean of those per-trade ROIs. Total dollars with $1 No each is the sum "
        "of those ROIs (same as N × average ROI)."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>No-bet ROI after 60→70, 15–60 minutes in</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Buying No after a 60→70 moneyline cross, 15–60 minutes into the game</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Slice of <a href="odds_cross_winrate_20261020.html">odds-cross win rates</a>.</p>
<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<p>Parent ask (odds-cross win rates): when a game is on and implied odds go from under 55% to over 60%, how often is that a winner — and the same for other bands, by sport, venue, and before vs during.</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Definition</h2>
<ul>
<li><strong>Event:</strong> moneyline (who wins). First hysteresis up-cross 60→70: the named side’s Yes price was strictly below 0.60, later strictly above 0.70. One row per (game, side, venue) at the first HI cross. Later ticks on the same contract are ignored.</li>
<li><strong>Time filter:</strong> listed <code>game_start</code> known, and (cross time − start) is in [15 minutes, 60 minutes] inclusive. Unknown start is excluded (tennis often has no commence time in this feed). Do not dump those rows into this window.</li>
<li><strong>Bet:</strong> buy No on that same side at the Yes price of the first print strictly above 0.70. No cost = 1 − that Yes price.</li>
<li><strong>Payoff and ROI:</strong> {esc(arith)}</li>
<li><strong>Settlements:</strong> official Kalshi <code>result</code> / Gemini <code>resolutionSide</code> only, same matcher as the parent study. Pending markets are labeled and excluded from ROI. A last print at 99 cents is not used here.</li>
<li><strong>Fees:</strong> primary table without fees.</li>
</ul>
<p class="note">Acronyms: ROI is return on investment. ATP is Association of Tennis Professionals. NHL is National Hockey League. NFL is National Football League. MLB is Major League Baseball. NBA is National Basketball Association. WTA is Women’s Tennis Association.</p>

<div class="hl">
<p><strong>Headline, moneyline 60→70, 15–60 minutes after start, official settlements, No bet, no fees:</strong>
N = {n} settled rows ({unique_games} unique games), No win rate {esc(no_wr)}% ({main['no_wins']} No wins / {n} settled), Yes-side win rate {esc(yes_wr)}%,
average ROI {esc(headline_roi)}%, median ROI {esc(headline_med)}%, mean No cost {esc(mean_cost)},
total $ if $1 No each {esc(total_pnl)}. {esc(main['note'] or '')}</p>
<p>Average ROI is the equal-stake mean. Payoffs are skewed: a cheap No that hits can return several times the stake, so the mean can be positive while the median is still a full loss. This is <em>not</em> the parent headline 69.8% Yes win rate on all moneyline 60→70 crosses. That row mixes before, during, and unknown start. This page recomputes from event-level rows under the time filter above.</p>
</div>

<h2>Sample and honesty</h2>
<p>Live tape is about 17–20 Oct 2026 (first Yes quote {esc(meta.get('seen_min') or '')}, last {esc(meta.get('seen_max') or '')}). There is no in-sample / out-of-sample split to report: almost every first-cross is after 2024-01-01, and the tape does not go back years. If N is tiny, do not read this as a trading rule. Nothing here is KEEP, gold, or DailyRun.</p>
<p>Moneyline 60→70 hysteresis crosses after dropping $1 empty-book prints: {counts['ml6070_total']}. Still missing start after the parent study’s occurrence-datetime backfill (excluded; not dumped into this window): {counts['ml6070_unknown_start']}. Known start but outside [15, 60] minutes: {counts['ml6070_known_outside']}. Inside [15, 60] minutes: {counts['ml6070_in_window']} ({counts['ml6070_in_window_settled']} settled, {counts['ml6070_in_window_pending']} pending). Of the {n} settled primary rows, {n_feed} used a feed <code>game_start</code> and {n_backfill} used occurrence backfill (almost all tennis). The parent study uses that same backfill; a feed-start-only row is in the companion table so tennis-unknown is not silently mixed into the tighter read. Same game can appear once per venue, so N is not unique matches.</p>
<p>Official settlements in the parent cache: Kalshi {meta.get('kalshi', 0):,}; Gemini {meta.get('gemini', 0):,}; unique after merge {meta.get('settle_total', 0):,}.</p>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>

<h2>Arithmetic (quoted)</h2>
<p>{esc(arith)} Example: Yes first prints 0.72, so No costs 0.28. If that side loses, ROI = (1 / 0.28) − 1 = +257.1%. If that side wins, ROI = −100%. Average ROI is the equal-weight mean of those percents, not a dollar-weighted pool.</p>

<h2>Primary slice: 60→70 moneyline No, 15–60 minutes</h2>
{table(SLICE_HEADERS, [summary_row(main)], SLICE_FIELDS)}

<h2>Companion: same No bet on 55→60, same 15–60 minute window</h2>
<p class="note">First hysteresis up-cross 55→60 (Yes strictly below 0.55, later strictly above 0.60). Buy No at 1 − first Yes print above 0.60. Same start-time window and official settlements. The feed-start-only 60→70 row drops occurrence backfill.</p>
{table(SLICE_HEADERS, [summary_row(s) for s in companions], SLICE_FIELDS)}

<h2>Companion: 60→70 moneyline No by time into the game</h2>
<p class="note">All rows still require a known start. During-game (0m+) is any cross at or after start. 15–60m is the closed interval [15, 60] minutes. 60m+ is strictly after 60 minutes. Before-start crosses are not a No-bet target on this page; they are omitted here. Mean ROI in the 0m+ and 60m+ rows is dominated by a few very cheap No winners; read the median too.</p>
{table(WINDOW_HEADERS, [summary_row(s) for s in windows], SLICE_FIELDS)}

<h2>Primary slice by sport</h2>
{table(
    [
        ("Sport", "text"), ("Settled N", "num"), ("No wins", "num"), ("Yes-side wins", "num"),
        ("No win %", "num"), ("Yes-side win %", "num"), ("Avg ROI %", "num"),
        ("Mean No cost", "num"), ("Total $ ($1 No each)", "num"), ("Note", "text"),
    ],
    sport_rows,
    ["sport", "n", "no_wins", "yes_wins", "no_win_pct", "yes_win_pct",
     "avg_roi_pct", "mean_no_cost", "total_pnl_1_stake", "note"],
)}

<h2>Primary slice by venue</h2>
<p class="note">Novig is a quote venue. Official result is the same game/side on Kalshi or Gemini when that match exists.</p>
{table(
    [
        ("Venue", "text"), ("Settled N", "num"), ("No wins", "num"), ("Yes-side wins", "num"),
        ("No win %", "num"), ("Yes-side win %", "num"), ("Avg ROI %", "num"),
        ("Mean No cost", "num"), ("Total $ ($1 No each)", "num"), ("Note", "text"),
    ],
    venue_rows,
    ["venue", "n", "no_wins", "yes_wins", "no_win_pct", "yes_win_pct",
     "avg_roi_pct", "mean_no_cost", "total_pnl_1_stake", "note"],
)}

<h2>Fees</h2>
<p>{esc(fee_line)}</p>

<h2>Event rows (primary slice, settled only)</h2>
<p class="note">One row per (game, side, venue) at the first 60→70 HI cross inside [15, 60] minutes. Official win means the named side won (No lost). Official loss means the named side lost (No won).</p>
{table(
    [
        ("Sport", "text"), ("Game", "text"), ("Side", "text"), ("Venue", "text"),
        ("Cross time", "date"), ("Game start", "date"), ("Minutes in", "num"),
        ("First Yes below 0.60", "num"), ("Yes at HI cross", "num"), ("No cost", "num"),
        ("Official (Yes side)", "text"), ("No result", "text"), ("ROI %", "num"),
        ("$ PnL ($1 No)", "num"), ("Official source", "text"), ("Start source", "text"),
    ],
    detail,
    [
        "sport", "game", "side", "venue", "cross_time", "game_start", "minutes",
        "first_below", "yes_px", "no_cost", "official", "no_result", "roi_pct",
        "pnl", "source", "start_source",
    ],
)}

<p class="note">Rows saved as <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/odds_cross_no_roi_60_70_20261020.csv</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def main() -> None:
    now = datetime.now(ET).isoformat()
    crosses, meta = load_attached()
    ml = [r for r in crosses if r.get("market_type") == "moneyline"]
    ml6070 = [r for r in ml if r.get("band") == "60→70"]
    ml5560 = [r for r in ml if r.get("band") == "55→60"]

    unknown = [r for r in ml6070 if r.get("minutes_num") is None]
    known = [r for r in ml6070 if r.get("minutes_num") is not None]
    in_window = [r for r in known if in_main_window(r)]
    outside = [r for r in known if not in_main_window(r)]
    backfill_n = sum(1 for r in ml6070 if r.get("start_source") == "occurrence_backfill")

    def trades_of(rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            trade = trade_from(row)
            if trade:
                out.append(trade)
        return out

    primary_rows = in_window
    primary_trades = trades_of(primary_rows)
    main_sum = summarize(primary_trades, "60→70 moneyline No, 15–60m")

    companion_5560 = [r for r in ml5560 if in_main_window(r)]
    companion_sum = summarize(trades_of(companion_5560), "55→60 moneyline No, 15–60m")
    feed_only_rows = [r for r in in_window if r.get("start_source") == "feed"]
    feed_only_sum = summarize(trades_of(feed_only_rows), "60→70 moneyline No, 15–60m, feed start only")

    during = [r for r in known if r.get("minutes_num") is not None and r["minutes_num"] >= 0]
    after_60 = [r for r in known if r.get("minutes_num") is not None and r["minutes_num"] > WINDOW_HI]
    windows = [
        summarize(trades_of(during), "60→70 moneyline No, during-game 0m+"),
        main_sum,
        summarize(trades_of(after_60), "60→70 moneyline No, 60m+"),
    ]

    counts = {
        "ml6070_total": len(ml6070),
        "ml6070_unknown_start": len(unknown),
        "ml6070_known_outside": len(outside),
        "ml6070_in_window": len(in_window),
        "ml6070_in_window_settled": sum(1 for r in in_window if r.get("official") in ("win", "loss")),
        "ml6070_in_window_pending": sum(1 for r in in_window if r.get("official") == "pending"),
        "ml6070_backfill": backfill_n,
    }

    payload = {
        "written_at": now,
        "asked": ASKED,
        "window_minutes": [WINDOW_LO, WINDOW_HI],
        "arithmetic": (
            "no_cost = 1 - yes_price_at_cross; "
            "if side loses (No wins): ROI = (1 / no_cost) - 1; "
            "if side wins (No loses): ROI = -1; "
            "average ROI = mean of per-trade ROIs with $1 No stake"
        ),
        "counts": counts,
        "meta": meta,
        "primary": {k: v for k, v in main_sum.items() if k not in ("by_sport", "by_venue")},
        "companion_55_60": {k: v for k, v in companion_sum.items() if k not in ("by_sport", "by_venue")},
        "feed_start_only": {k: v for k, v in feed_only_sum.items() if k not in ("by_sport", "by_venue")},
        "windows": [{k: v for k, v in w.items() if k not in ("by_sport", "by_venue")} for w in windows],
        "by_sport": main_sum["by_sport"],
        "by_venue": main_sum["by_venue"],
        "trades": primary_trades,
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {JSON_OUT}", flush=True)

    if primary_trades:
        fieldnames = list(primary_trades[0].keys())
        with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(primary_trades)
        print(f"wrote {CSV_OUT}", flush=True)

    write_html(main_sum, [companion_sum, feed_only_sum], windows, primary_trades, counts, meta, now)
    patch_parent()
    copy_g(PAGE)
    copy_g(PARENT_PAGE)

    print(
        f"PRIMARY N={main_sum['n']} no_wr={main_sum['no_win_rate']} "
        f"avg_roi={main_sum['avg_roi']} mean_no_cost={main_sum['mean_no_cost']} "
        f"unknown_start={counts['ml6070_unknown_start']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
