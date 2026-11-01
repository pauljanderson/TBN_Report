"""Sport / league / T0 Yes decile win% and with-fee P&L.

Research only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not bump stake, wire D NFL,
leftover GTC, or retune C=1.05.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
import t0_all_games_stats as t0
from nfl_t0_type_a_collect import (
    explode_cover_yes_sides,
    line_won,
    score_t0_yes,
)
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP
from t0_fav_lt90_baseline_20261024 import (
    VENUE_RANK,
    fav_yes_pnl,
    fmt_ann,
    fmt_pct,
    quality,
)
from write_orders_performance import league_from_instrument
from write_t0_band_from_stay_above import documented_leg_fee

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "sport_league_t0_decile_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/sport_league_t0_decile_20261027.html"
)
IS_CUT = "2024-01-01"
DECADES = (
    "0-9", "10-19", "20-29", "30-39", "40-49",
    "50-59", "60-69", "70-79", "80-89", "90-99",
)
SPORT_LEAGUE = {
    "pro football": "NFL",
    "nfl": "NFL",
    "college football": "CFB",
    "cfb": "CFB",
    "ncaaf": "CFB",
    "baseball": "MLB",
    "mlb": "MLB",
    "hockey": "NHL",
    "nhl": "NHL",
    "basketball": "NBA",
    "nba": "NBA",
    "wnba": "WNBA",
}
ASKED = (
    "Paul: “can i see the latest decile results from kalshi?” "
    "Show the latest Kalshi Yes-ask history deciles from disk. Original: "
    "“get Kalshi and Polymarket historical numbers then regen deciles.” "
    "Three labeled unblended tapes: (1) live 11-day four-platform Yes-ask venue-true, "
    "(2) Kalshi yes_ask hist, (3) Polymarket last-trade hist. Do not blend. Keep display "
    "Points Total (not total, not Over/Under as the column name). Keep CFB 40-49 callout: "
    "Points Total vs spread vs moneyline are parallel; true grand is the sum. "
    "Do not mix sportsbook closes. Do not start a second leftover pull. Original: show me "
    "a report of each sport / league / decile win percent from 0-9 to 90-99 and the "
    "overall profitability for each."
)
PLAIN = (
    "Kalshi history is the Yes-ask tape you asked for — jump to it first. "
    "Three separate books sit on this page. They are never averaged together. "
    "Book 1 is the 11-day live tape from 17 Oct 2026: last Yes <em>ask</em> at a trusted "
    "kickoff on Kalshi, Gemini, Polymarket, or Novig, with venue-true Polymarket winners "
    "(closed 0/1 outcome prices — the same settlement the kitchen used after the tennis "
    "invert). Book 2 is Kalshi history: 1-minute Yes-ask candles at the venue kickoff clock, "
    "plus the market result. Book 3 is Polymarket Central Limit Order Book (CLOB) history: "
    "last trade (not ask) at game start on the global book, which is not the Polymarket US "
    "kitchen. If a history book is incomplete, it is labeled with N, span, sports, and holes; "
    "the live-tape deciles still publish. "
    "T0 is the start price, not a random first tick. Each row is one named Yes — favorite "
    "and dog — after one-venue pick. Bet type is Moneyline (who wins), Spread (cover a "
    "point line), or Points Total (the over/under on combined score). Points Total is a "
    "market, not a grand total of Spread plus Moneyline. A decile is a 10-cent band of "
    "that Yes price. Win percent is how often that named side actually won. Profitability "
    "is buy one Yes at T0, pay the documented taker fee, hold to settlement. A win pays $1. "
    "Same-day holds omit annualized rate of return so the house formula does not overflow. "
    "If a book starts in 2025 it is still all out-of-sample versus the 2024-01-01 split. "
    "This is not the live A–E kitchen. Did not rescore frozen compare.html (24 Oct backtest)."
)
TAPE_NOTE = (
    "This page is a research named-Yes T0 tape, not the live A–E order kitchen. "
    "Each cell buys one named Yes at the T0 ask plus the documented taker fee. "
    "It does not use Polymarket BUY_SHORT fill cash, so the Yes-wire debit bug never applied here. "
    "Winners come from the all-game settlement cache (Kalshi result, Gemini resolutionSide, "
    "Polymarket closed 0/1 outcomePrices), not ticker result=yes from a close_hook. "
    "Did not retune live D / C / stake / second B."
)
_PREV_JSON = None
_PREV_HTML_CELLS = None
_PREV_PAGE_MTIME = None
KALSHI_HEADLINES = (
    ("CFB ML 50-89", "college football", "ALL", "moneyline",
     ("50-59", "60-69", "70-79", "80-89")),
    ("CFB ML 70-89", "college football", "ALL", "moneyline",
     ("70-79", "80-89")),
    ("Tennis ML 10-49", "tennis", "ALL", "moneyline",
     ("10-19", "20-29", "30-39", "40-49")),
    ("Spreads 50-89 (all sports)", "", "ALL", "spread",
     ("50-59", "60-69", "70-79", "80-89")),
)
HEADLINE_HEADERS = [
    ("Slice", "text"),
    ("N settled", "num"),
    ("Wins", "num"),
    ("Win%", "num"),
    ("N with fee", "num"),
    ("With-fee P&L", "num"),
    ("Avg P&L", "num"),
]

FLIP_HEADERS = [
    ("Sport", "text"),
    ("League", "text"),
    ("Bet type", "text"),
    ("Decile", "text"),
    ("Prior N", "num"),
    ("Now N", "num"),
    ("Prior wins", "num"),
    ("Now wins", "num"),
    ("Prior with-fee P&L", "num"),
    ("Now with-fee P&L", "num"),
    ("What changed", "text"),
]

HEADERS = [
    ("Sport", "text"),
    ("League", "text"),
    ("Bet type", "text"),
    ("Decile", "text"),
    ("N settled", "num"),
    ("Wins", "num"),
    ("Win%", "num"),
    ("N with fee", "num"),
    ("With-fee P&L", "num"),
    ("Avg P&L", "num"),
    ("Ann ROR full", "num"),
    ("Ann ROR IS", "num"),
    ("Ann ROR OOS", "num"),
    ("Note", "text"),
]

# Tape `kind` values. "total" is Points Total (the over/under on combined score) —
# not a grand sum of spread + moneyline. Display the layman label on the page.
KIND_LABEL = {
    "moneyline": "Moneyline",
    "spread": "Spread",
    "total": "Points Total",
    "team_total": "Team total",
}
KIND_NOTE = (
    "Each row is one bet type, not a nested sum of the rows above it. "
    "Moneyline = who wins the game. Spread = whether a team covers a point line. "
    "Points Total (the over/under on combined score) = whether combined points go "
    "over or under a posted number (sportsbook 'total'). ALL bet types means those "
    "markets are pooled."
)


def kind_label(kind: str) -> str:
    raw = str(kind or "").strip()
    if raw == "ALL":
        return "ALL bet types"
    return KIND_LABEL.get(raw, raw or "unknown")


def compact_cell(sport: str, league: str, kind: str, band: str, rec: dict) -> dict:
    return {
        "sport": sport,
        "league": league,
        "kind": kind,
        "kind_label": kind_label(kind),
        "decile": band,
        "n": rec.get("n"),
        "n_win": rec.get("n_win"),
        "win_pct": rec.get("win_pct"),
        "n_fee": rec.get("n_fee"),
        "pnl_sum": rec.get("pnl_sum"),
        "avg_pnl": rec.get("avg_pnl"),
        "note": rec.get("note") or "",
    }


def prev_snapshot() -> dict:
    """Load the on-disk JSON once, before this job overwrites it."""
    global _PREV_JSON, _PREV_HTML_CELLS, _PREV_PAGE_MTIME
    if _PREV_JSON is not None:
        return _PREV_JSON
    path = STAMP / "sport_league_t0_decile_20261027.json"
    if not path.is_file():
        _PREV_JSON = {}
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        _PREV_JSON = data if isinstance(data, dict) else {}
    if PAGE.is_file():
        try:
            _PREV_PAGE_MTIME = PAGE.stat().st_mtime
            html = PAGE.read_text(encoding="utf-8")
            _PREV_HTML_CELLS = parse_html_live_cells(html)
        except OSError:
            _PREV_HTML_CELLS = _PREV_HTML_CELLS or {}
    else:
        _PREV_HTML_CELLS = {}
    return _PREV_JSON


def _empty_spot() -> dict:
    return {"n": 0, "n_win": 0, "n_fee": 0, "pnl_sum": None}


def _add_spot(dst: dict, rec: dict | None) -> None:
    if not rec:
        return
    dst["n"] += int(rec.get("n") or 0)
    dst["n_win"] += int(rec.get("n_win") or 0)
    dst["n_fee"] += int(rec.get("n_fee") or 0)
    if rec.get("pnl_sum") is not None:
        dst["pnl_sum"] = float(dst["pnl_sum"] or 0.0) + float(rec["pnl_sum"])


def _compact_spot(rec: dict | None) -> dict:
    rec = rec or {}
    pnl = rec.get("pnl_sum")
    return {
        "n": int(rec.get("n") or 0),
        "n_win": int(rec.get("n_win") or 0),
        "n_fee": int(rec.get("n_fee") or 0),
        "pnl_sum": None if pnl is None else float(pnl),
    }


def spotcheck_from_cells(cells: dict) -> dict:
    tennis = _empty_spot()
    for band in ("10-19", "20-29", "30-39", "40-49"):
        _add_spot(tennis, _lookup_cell(cells, "tennis", "ALL", "moneyline", band))
    soccer = _lookup_cell(cells, "soccer", "ALL", "ALL", "ALL")
    cfb_total = _lookup_cell(cells, "college football", "ALL", "total", "40-49")
    cfb_ml = _lookup_cell(cells, "college football", "ALL", "moneyline", "40-49")
    cfb_sp = _lookup_cell(cells, "college football", "ALL", "spread", "40-49")
    cfb_grand = _empty_spot()
    for rec in (cfb_ml, cfb_sp, cfb_total):
        _add_spot(cfb_grand, rec)
    grand = _lookup_cell(cells, "ALL", "ALL", "ALL", "ALL")
    return {
        "tennis_ml_10_49": _compact_spot(tennis),
        "soccer_all": _compact_spot(soccer),
        "cfb_40_49_points_total": _compact_spot(cfb_total),
        "cfb_40_49_spread": _compact_spot(cfb_sp),
        "cfb_40_49_moneyline": _compact_spot(cfb_ml),
        "cfb_40_49_grand": _compact_spot(cfb_grand),
        "grand": _compact_spot(grand),
    }


def _prev_cfb_kind(prev: dict, kind: str) -> dict:
    cfb = prev.get("cfb_40_49") or {}
    if isinstance(cfb.get(kind), dict):
        return cfb[kind]
    indep = (prev.get("independent") or {}).get("cfb_40_49") or {}
    return indep.get(kind) or {}


def _prev_spot(prev: dict) -> dict:
    indep = prev.get("independent") or {}
    return {
        "tennis_ml_10_49": _compact_spot(indep.get("tennis_ml_10_49")),
        "soccer_all": _compact_spot(indep.get("soccer_all")),
        "cfb_40_49_points_total": _compact_spot(_prev_cfb_kind(prev, "total")),
        "cfb_40_49_spread": _compact_spot(_prev_cfb_kind(prev, "spread")),
        "cfb_40_49_moneyline": _compact_spot(_prev_cfb_kind(prev, "moneyline")),
        "cfb_40_49_grand": _compact_spot(prev.get("cfb_40_49_grand") or indep.get("cfb_40_49_grand")),
        "grand": _compact_spot(prev.get("grand") or indep.get("overall")),
    }


def _spot_close(a: dict, b: dict, *, tol: float = 0.02) -> bool:
    if int(a.get("n") or 0) != int(b.get("n") or 0):
        return False
    if int(a.get("n_win") or 0) != int(b.get("n_win") or 0):
        return False
    if int(a.get("n_fee") or 0) != int(b.get("n_fee") or 0):
        return False
    pa, pb = a.get("pnl_sum"), b.get("pnl_sum")
    if pa is None and pb is None:
        return True
    if pa is None or pb is None:
        return False
    return abs(float(pa) - float(pb)) <= tol


def _fmt_spot(rec: dict) -> str:
    pnl = rec.get("pnl_sum")
    pnl_s = "—" if pnl is None else money_cell(pnl, n_fee=int(rec.get("n_fee") or 0) or 1)
    return (
        f"N={int(rec.get('n') or 0)} wins={int(rec.get('n_win') or 0)} "
        f"n_fee={int(rec.get('n_fee') or 0)} P&L {pnl_s}"
    )


def compare_to_prev(spot: dict, prev: dict) -> dict:
    if not prev:
        return {
            "had_prev": False,
            "changed": None,
            "n_moved": None,
            "verdict": "No prior JSON on disk; first write of this page.",
            "rows": [],
        }
    old = _prev_spot(prev)
    labels = (
        ("tennis_ml_10_49", "tennis moneyline 10–49"),
        ("soccer_all", "soccer all bet types"),
        ("cfb_40_49_points_total", "CFB 40–49 Points Total"),
        ("cfb_40_49_spread", "CFB 40–49 Spread"),
        ("cfb_40_49_moneyline", "CFB 40–49 Moneyline"),
        ("cfb_40_49_grand", "CFB 40–49 true grand"),
        ("grand", "whole settled book"),
    )
    rows = []
    any_change = False
    n_moved = False
    for key, label in labels:
        before = old.get(key) or _empty_spot()
        after = spot.get(key) or _empty_spot()
        same = _spot_close(before, after)
        if not same:
            any_change = True
        if int(before.get("n") or 0) != int(after.get("n") or 0):
            n_moved = True
        rows.append({
            "key": key,
            "label": label,
            "before": before,
            "after": after,
            "changed": not same,
        })
    if not any_change:
        verdict = (
            "Poly kitchen ticker result=yes / BUY_SHORT Yes-wire fixes did not change any "
            "spot-check cell. This tape never used those kitchen fields. Numbers below are "
            "from today’s named-Yes T0 tape; the timestamp moved."
        )
    elif n_moved:
        verdict = (
            "N moved vs the prior JSON (tape grew or more games have a venue result). "
            "That is not a pure winner invert from ticker result=yes. Kitchen BUY_SHORT "
            "cash does not apply on this named-Yes T0 tape."
        )
    else:
        verdict = (
            "Same N, different wins or with-fee P&L vs the prior JSON. Winner mapping or "
            "documented-fee P&L moved. Still a named-Yes T0 tape (not live A–E fill cash)."
        )
    return {
        "had_prev": True,
        "changed": any_change,
        "n_moved": n_moved,
        "verdict": verdict,
        "rows": rows,
    }


def _strip_td(text: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def parse_money_cell(text: str):
    raw = _strip_td(text).replace(",", "").replace("−", "-").replace("–", "-")
    if not raw or raw in ("—", "-", "n/a"):
        return None
    raw = raw.replace("$", "").replace("+", "")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_int_cell(text: str) -> int:
    raw = _strip_td(text).replace(",", "")
    if not raw or raw in ("—", "-"):
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return 0


def parse_html_live_cells(html: str) -> dict:
    """Book 1 cells from the prior page. Starts at Book 1; stops before hist blocks."""
    cut = html or ""
    for start_mark in ("Book 1 —", "Book 1 -", 'id="book1-live"'):
        start = cut.find(start_mark)
        if start >= 0:
            cut = cut[start:]
            break
    for marker in (
        "Kalshi history",
        "Kalshi historical T0",
        "Polymarket historical (CLOB",
        "Coverage — sport",
        "Book 2",
        'id="kalshi-history"',
        'id="poly-history"',
    ):
        i = cut.find(marker)
        if i > 0:
            cut = cut[:i]
            break
    out = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", cut, flags=re.I | re.S):
        tds = re.findall(r"<td>(.*?)</td>", tr, flags=re.I | re.S)
        if len(tds) < 9:
            continue
        sport = _strip_td(tds[0])
        league = _strip_td(tds[1])
        kind = _strip_td(tds[2])
        band = _strip_td(tds[3])
        if not sport or not band:
            continue
        key = f"{sport}|{league}|{kind}|{band}"
        rec = {
            "n": parse_int_cell(tds[4]),
            "n_win": parse_int_cell(tds[5]),
            "n_fee": parse_int_cell(tds[7]),
            "pnl_sum": parse_money_cell(tds[8]),
        }
        if key not in out:
            out[key] = rec
    return out


def cells_from_tables(tables: dict) -> dict:
    out = {}
    for key, rec in (tables.get("cells") or {}).items():
        sport, league, kind, band = key
        out[f"{sport}|{league}|{kind_label(kind)}|{band}"] = {
            "n": int(rec.get("n") or 0),
            "n_win": int(rec.get("n_win") or 0),
            "n_fee": int(rec.get("n_fee") or 0),
            "pnl_sum": None if rec.get("pnl_sum") is None else float(rec["pnl_sum"]),
        }
    return out


def split_cell_id(key: str) -> tuple[str, str, str, str]:
    parts = str(key).split("|")
    while len(parts) < 4:
        parts.append("")
    return parts[0], parts[1], parts[2], parts[3]


def compare_live_cells(now_cells: dict, prior_cells: dict) -> dict:
    if not prior_cells:
        return {
            "had_prev": False,
            "n_prior": 0,
            "n_now": len(now_cells),
            "n_flip_same_n": 0,
            "n_n_moved": 0,
            "n_new": len(now_cells),
            "n_dropped": 0,
            "n_tennis_flip": 0,
            "verdict": "No prior 20261027 HTML cells to compare.",
            "flips": [],
            "n_moved_rows": [],
        }
    flips = []
    moved = []
    keys = set(now_cells) | set(prior_cells)
    n_new = n_dropped = 0
    for key in sorted(keys):
        before = prior_cells.get(key)
        after = now_cells.get(key)
        if before is None:
            n_new += 1
            continue
        if after is None:
            n_dropped += 1
            continue
        n0, n1 = int(before.get("n") or 0), int(after.get("n") or 0)
        same_n = n0 == n1
        same_stats = _spot_close(before, after)
        sport, league, kind, band = split_cell_id(key)
        row = {
            "key": key,
            "sport": sport,
            "league": league,
            "kind": kind,
            "decile": band,
            "before": before,
            "after": after,
            "same_n": same_n,
            "changed": not same_stats,
        }
        if same_n and not same_stats:
            flips.append(row)
        elif not same_n:
            moved.append(row)
    tennis_flips = [
        r for r in flips if "tennis" in f"{r.get('sport')} {r.get('league')}".lower()
    ]
    if not flips and not moved:
        verdict = (
            "No live-tape cell flipped vs the prior 20261027 page: every shared "
            "sport/league/bet-type/decile cell kept the same N, wins, and with-fee P&L. "
            "Venue-true Polymarket winners (closed 0/1) did not invert a named-Yes T0 cell "
            "on this tape. This tape never used kitchen ticker result=yes."
        )
    elif flips:
        verdict = (
            f"{len(flips)} live-tape cell(s) kept the same N but changed wins or with-fee "
            f"P&L vs the prior 20261027 page"
            + (f", including {len(tennis_flips)} tennis cell(s)" if tennis_flips else ", none of them tennis")
            + ". That is a winner or fee-P&L remap at constant sample size, not tape growth."
        )
        if moved:
            verdict += f" Separately, {len(moved)} cell(s) changed N (tape grew or new settlements)."
    else:
        verdict = (
            f"No same-N winner invert vs the prior 20261027 page. {len(moved)} cell(s) "
            "changed N (tape grew or more games have a venue result). Kitchen BUY_SHORT "
            "cash does not apply on this named-Yes T0 tape."
        )
    return {
        "had_prev": True,
        "n_prior": len(prior_cells),
        "n_now": len(now_cells),
        "n_flip_same_n": len(flips),
        "n_n_moved": len(moved),
        "n_new": n_new,
        "n_dropped": n_dropped,
        "n_tennis_flip": len(tennis_flips),
        "verdict": verdict,
        "flips": flips,
        "n_moved_rows": moved,
    }


def live_vs_prior_html(all_cmp: dict) -> str:
    flips = all_cmp.get("flips") or []
    moved = all_cmp.get("n_moved_rows") or []
    rows = []
    show = list(flips) + [r for r in moved if "tennis" in f"{r.get('sport')} {r.get('league')}".lower()][:12]
    if not show and moved:
        show = moved[:12]
    for row in show[:40]:
        before = row.get("before") or {}
        after = row.get("after") or {}
        what = "same-N win/P&L flip" if row.get("same_n") else "N moved"
        rows.append([
            esc(row.get("sport")),
            esc(row.get("league")),
            esc(row.get("kind")),
            esc(row.get("decile")),
            str(int(before.get("n") or 0)),
            str(int(after.get("n") or 0)),
            str(int(before.get("n_win") or 0)),
            str(int(after.get("n_win") or 0)),
            money_cell(before.get("pnl_sum"), n_fee=int(before.get("n_fee") or 0) or 1),
            money_cell(after.get("pnl_sum"), n_fee=int(after.get("n_fee") or 0) or 1),
            esc(what),
        ])
    table_html = ""
    if rows:
        table_html = (
            f"{report_page_extras.SWIPE_NOTE_HTML}"
            f"{t0.table(FLIP_HEADERS, rows)}"
        )
    return (
        f"<p><strong>Live tape vs prior 20261027 page.</strong> {esc(all_cmp.get('verdict') or '')} "
        f"Prior cells={esc(all_cmp.get('n_prior'))}, now={esc(all_cmp.get('n_now'))}, "
        f"same-N flips={esc(all_cmp.get('n_flip_same_n'))}, N-moved={esc(all_cmp.get('n_n_moved'))}, "
        f"new={esc(all_cmp.get('n_new'))}, dropped={esc(all_cmp.get('n_dropped'))}, "
        f"tennis same-N flips={esc(all_cmp.get('n_tennis_flip'))}.</p>"
        + table_html
    )


def venue_truth_html(cmp: dict, all_cmp: dict | None = None) -> str:
    bits = [esc(TAPE_NOTE), esc(cmp.get("verdict") or "")]
    lines = []
    for row in cmp.get("rows") or []:
        before = _fmt_spot(row.get("before") or {})
        after = _fmt_spot(row.get("after") or {})
        mark = "changed" if row.get("changed") else "same"
        lines.append(
            f"<li><strong>{esc(row.get('label'))}</strong> — was {esc(before)}; now {esc(after)} ({esc(mark)}).</li>"
        )
    extra = ""
    if lines:
        extra = "<ul>" + "".join(lines) + "</ul>"
    all_html = ""
    if all_cmp:
        all_html = live_vs_prior_html(all_cmp)
    return f"<p>{' '.join(bits)}</p>{extra}{all_html}"


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def decile_of(px) -> str | None:
    """T0 Yes in [0.00, 0.10) = 0-9, …, [0.90, 1.00] = 90-99."""
    if px is None:
        return None
    try:
        p = float(px)
    except (TypeError, ValueError):
        return None
    if p < 0 or p > 1:
        return None
    if p >= 0.90 - 1e-12:
        return "90-99"
    band = int(p * 10.0 + 1e-12)
    lo = band * 10
    return f"{lo}-{lo + 9}"


def league_of_side(book: dict) -> str:
    sport = str(book.get("sport") or "").strip()
    low = sport.lower()
    if low in SPORT_LEAGUE:
        return SPORT_LEAGUE[low]
    blob = " ".join(
        str(book.get(key) or "")
        for key in (
            "game", "game_n", "off_src_a", "off_src_b",
            "fav_name", "side_a", "side_b", "ticker", "instrument",
        )
    )
    found = league_from_instrument(blob)
    if found:
        return found
    if "tennis" in low:
        return "tennis"
    if "soccer" in low:
        return "soccer"
    return sport or "unknown"


def pick_one_side(sides: list[dict]) -> list[dict]:
    """One venue per sport-game-market-number-side. Documented fee first, then cheaper Yes."""
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in sides:
        key = (
            str(book.get("sport") or "").lower(),
            str(book.get("game_n") or book.get("game") or ""),
            str(book.get("kind") or "moneyline"),
            str(book.get("number") or ""),
            str(book.get("_side_letter") or book.get("fav_name") or ""),
        )
        bags[key].append(book)
    out = []
    for group in bags.values():
        group = sorted(
            group,
            key=lambda b: (
                0 if documented_leg_fee(str(b.get("venue") or ""), score_t0_yes(b)) is not None else 1,
                float(score_t0_yes(b) if score_t0_yes(b) is not None else 9),
                VENUE_RANK.get(str(b.get("venue") or ""), 9),
                str(b.get("venue") or ""),
            ),
        )
        chosen = dict(group[0])
        px = score_t0_yes(chosen)
        if chosen.get("t0_fav") is None and px is not None:
            chosen["t0_fav"] = px
        chosen["_n_venues"] = len(group)
        out.append(chosen)
    return out


def yes_trade(book: dict) -> dict | None:
    px = book.get("t0_fav")
    if px is None:
        px = score_t0_yes(book)
    won = line_won(book)
    if px is None or won is None:
        return None
    venue = str(book.get("venue") or "")
    fee = documented_leg_fee(venue, px)
    if fee is None:
        return None
    pnl = fav_yes_pnl(px, fee, won=bool(won))
    cost = Decimal(str(px)) + Decimal(str(fee))
    pnl_pct = (float(pnl) / float(cost) * 100.0) if cost > 0 else None
    t0_ts = book.get("t0_ts")
    end_ts = book.get("end_ts") or t0_ts
    days = 0.0
    opened = closed = None
    if t0_ts is not None:
        opened = datetime.fromtimestamp(int(t0_ts), ET)
        if end_ts is not None:
            closed = datetime.fromtimestamp(int(end_ts), ET)
            days = max(0.0, (int(end_ts) - int(t0_ts)) / 86400.0)
        else:
            closed = opened
    return {
        "sport": book.get("sport") or "",
        "kind": book.get("kind") or "moneyline",
        "venue": venue,
        "game": book.get("game") or "",
        "t0_fav": float(px),
        "fee": float(fee),
        "cost": float(cost),
        "won": bool(won),
        "pnl_d": float(pnl),
        "pnl": pnl_pct,
        "days": days,
        "opened": opened,
        "closed": closed,
        "entry_date": opened.date().isoformat() if opened else "",
    }


def score_bag(settled: list[dict], *, arm: str) -> dict:
    n = len(settled)
    n_win = sum(1 for row in settled if line_won(row) is True)
    wr = (100.0 * n_win / n) if n else None
    trades = []
    for row in settled:
        trade = yes_trade(row)
        if trade is not None:
            trades.append(trade)
    q = quality(trades, arm_id=arm, label=arm, grain="unique-game-side") if trades else {}
    pnl = q.get("pnl_sum") if trades else None
    if pnl is None and trades:
        pnl = sum(float(t["pnl_d"]) for t in trades)
    avg = (pnl / len(trades)) if trades and pnl is not None else None
    note = ""
    if n == 0:
        note = "N=0 on this tape"
    elif n < 8:
        note = "tiny N"
    elif n < 20:
        note = "small sample"
    if n and len(trades) < n:
        extra = f"P&L on {len(trades)}/{n} with documented fee (Novig omitted)"
        note = f"{note}; {extra}".strip("; ")
    if q.get("ann_note"):
        note = f"{note}; {q.get('ann_note')}".strip("; ")
    return {
        "n": n,
        "n_win": n_win,
        "win_pct": wr,
        "n_fee": len(trades),
        "pnl_sum": pnl,
        "avg_pnl": avg,
        "ann_ror": q.get("ann_ror"),
        "ann_ror_is": q.get("ann_ror_is"),
        "ann_ror_oos": q.get("ann_ror_oos"),
        "is_note": q.get("is_note") or "n/a — no IS (all T0 ≥ 2024-01-01)",
        "ann_note": q.get("ann_note") or "",
        "note": note,
        "trades": trades,
    }


def money_cell(value, *, n_fee: int) -> str:
    if not n_fee or value is None:
        return "—"
    try:
        from compare_format import format_money
        return format_money(value)
    except Exception:
        return f"{float(value):+.4f}"


def row_cells(sport: str, league: str, kind: str, decile: str, rec: dict) -> list[str]:
    n = int(rec.get("n") or 0)
    n_fee = int(rec.get("n_fee") or 0)
    ann_full = rec.get("ann_note") or fmt_ann(rec.get("ann_ror"))
    if rec.get("ann_note") and rec.get("ann_ror") is None:
        ann_full = "omitted (same-day)"
    ann_is = rec.get("is_note") or fmt_ann(rec.get("ann_ror_is"))
    if not rec.get("ann_ror_is") and rec.get("is_note"):
        ann_is = "n/a (no IS)"
    ann_oos = rec.get("ann_note") or fmt_ann(rec.get("ann_ror_oos"))
    if rec.get("ann_ror_oos") is None and rec.get("ann_note"):
        ann_oos = "omitted (same-day)"
    elif rec.get("ann_ror_oos") is not None:
        ann_oos = fmt_ann(rec.get("ann_ror_oos"))
    return [
        esc(sport),
        esc(league),
        esc(kind_label(kind)),
        esc(decile),
        str(n),
        str(rec.get("n_win") or 0) if n else "0",
        fmt_pct(rec.get("win_pct")) if n else "—",
        str(n_fee),
        money_cell(rec.get("pnl_sum"), n_fee=n_fee),
        money_cell(rec.get("avg_pnl"), n_fee=n_fee),
        esc(ann_full) if n_fee else "—",
        esc(ann_is) if n_fee else "—",
        esc(ann_oos) if n_fee else "—",
        esc(rec.get("note") or ""),
    ]


def group_sides(sides: list[dict]) -> dict[tuple, list[dict]]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in sides:
        if book.get("void"):
            continue
        if line_won(book) is None:
            continue
        px = book.get("t0_fav")
        if px is None:
            px = score_t0_yes(book)
        band = decile_of(px)
        if not band:
            continue
        sport = str(book.get("sport") or "unknown")
        league = league_of_side(book)
        kind = str(book.get("kind") or "moneyline")
        bags[(sport, league, kind, band)].append(book)
    return bags


def build_tables(sides: list[dict]) -> dict:
    bags = group_sides(sides)
    cells: dict[tuple, dict] = {}
    for key, rows in bags.items():
        sport, league, kind, band = key
        cells[key] = score_bag(rows, arm=f"{sport}|{league}|{kind}|{band}")
    roll: dict[tuple, list[dict]] = defaultdict(list)
    for (sport, league, kind, band), rows in bags.items():
        roll[(sport, league, kind, "ALL")].extend(rows)
        roll[(sport, league, "ALL", "ALL")].extend(rows)
        roll[(sport, "ALL", kind, band)].extend(rows)
        roll[(sport, "ALL", "ALL", "ALL")].extend(rows)
        roll[("ALL", "ALL", "ALL", band)].extend(rows)
        roll[("ALL", "ALL", "ALL", "ALL")].extend(rows)
    for key, rows in roll.items():
        if key not in cells:
            sport, league, kind, band = key
            cells[key] = score_bag(rows, arm=f"{sport}|{league}|{kind}|{band}")
    detail = []
    for sport, league, kind, band in sorted(bags):
        detail.append(row_cells(sport, league, kind, band, cells[(sport, league, kind, band)]))
    overall = []
    for key in sorted(k for k in cells if k[3] == "ALL" or k[0] == "ALL"):
        sport, league, kind, band = key
        overall.append(row_cells(sport, league, kind, band, cells[key]))
    sport_decile = []
    for key in sorted(k for k in cells if k[1] == "ALL" and k[2] != "ALL" and k[3] != "ALL"):
        sport, league, kind, band = key
        sport_decile.append(row_cells(sport, league, kind, band, cells[key]))
    all_decile = []
    for band in DECADES:
        rec = cells.get(("ALL", "ALL", "ALL", band))
        if rec:
            all_decile.append(row_cells("ALL", "ALL", "ALL", band, rec))
    grand = cells.get(("ALL", "ALL", "ALL", "ALL")) or score_bag([], arm="empty")
    return {
        "n_sides": len(sides),
        "n_settled": sum(int(cells[k]["n"]) for k in bags),
        "detail": detail,
        "sport_decile": sport_decile,
        "all_decile": all_decile,
        "overall": overall,
        "grand": grand,
        "cells": cells,
    }


def _lookup_cell(cells: dict, sport: str, league: str, kind: str, band: str) -> dict:
    rec = cells.get((sport, league, kind, band))
    if rec:
        return rec
    if league == "ALL":
        alt = SPORT_LEAGUE.get(sport.lower())
        if alt:
            rec = cells.get((sport, alt, kind, band))
            if rec:
                return rec
    return {}


def headline_spot(cells: dict, sport: str, league: str, kind: str, bands: tuple[str, ...]) -> dict:
    bag = _empty_spot()
    if sport:
        for band in bands:
            _add_spot(bag, _lookup_cell(cells, sport, league, kind, band))
    else:
        want = set(bands)
        for (sp, lg, kd, band), rec in (cells or {}).items():
            if kd == kind and lg == "ALL" and sp not in ("", "ALL") and band in want:
                _add_spot(bag, rec)
    n_fee = int(bag.get("n_fee") or 0)
    pnl = bag.get("pnl_sum")
    n = int(bag.get("n") or 0)
    n_win = int(bag.get("n_win") or 0)
    bag["avg_pnl"] = (float(pnl) / n_fee) if n_fee and pnl is not None else None
    bag["win_pct"] = (100.0 * n_win / n) if n else None
    return bag


def kalshi_headlines(cells: dict) -> list[dict]:
    out = []
    for label, sport, league, kind, bands in KALSHI_HEADLINES:
        rec = headline_spot(cells, sport, league, kind, bands)
        rec["label"] = label
        rec["sport"] = sport or "ALL"
        rec["kind"] = kind
        rec["bands"] = ":".join(bands)
        out.append(rec)
    return out


def kalshi_headline_html(tables: dict | None) -> str:
    if not tables or not tables.get("n_settled"):
        return ""
    rows = []
    for rec in kalshi_headlines(tables.get("cells") or {}):
        n = int(rec.get("n") or 0)
        n_fee = int(rec.get("n_fee") or 0)
        wr = rec.get("win_pct")
        rows.append([
            esc(rec.get("label") or ""),
            str(n),
            str(int(rec.get("n_win") or 0)),
            esc(fmt_pct(wr) if n else "—"),
            str(n_fee),
            esc(money_cell(rec.get("pnl_sum"), n_fee=n_fee)),
            esc(money_cell(rec.get("avg_pnl"), n_fee=n_fee)),
        ])
    return (
        "<h3>Kalshi tape — headline slices</h3>"
        "<p class=\"note\">Kalshi Yes-ask only. Not blended with live or Polymarket. "
        "CFB ML 50–89 is 50–59 through 80–89 pooled. Tennis ML 10–49 is 10–19 through 40–49. "
        "Spreads 50–89 pools every sport’s spread in those four bands. "
        "Click column headers to sort.</p>"
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        f"{t0.table(HEADLINE_HEADERS, rows)}"
    )


def cfb_4049_blurb(cells: dict) -> str:
    bits = []
    n = n_win = n_fee = 0
    pnl = 0.0
    any_pnl = False
    for kind in ("moneyline", "spread", "total"):
        rec = _lookup_cell(cells, "college football", "ALL", kind, "40-49")
        nn = int(rec.get("n") or 0)
        nw = int(rec.get("n_win") or 0)
        nf = int(rec.get("n_fee") or 0)
        p = rec.get("pnl_sum")
        bits.append(
            f"{kind_label(kind)} N={nn} wins={nw} with-fee P&L {money_cell(p, n_fee=nf)}"
        )
        n += nn
        n_win += nw
        n_fee += nf
        if p is not None:
            pnl += float(p)
            any_pnl = True
    grand_pnl = money_cell(pnl if any_pnl else None, n_fee=n_fee)
    return (
        "Worked example — college football 40–49: "
        + "; ".join(bits)
        + ". Those three rows are three different markets. True college-football 40–49 grand total "
        f"(Moneyline + Spread + Points Total): N={n} wins={n_win} with-fee P&L {grand_pnl}."
    )


def json_dump(tables: dict) -> dict:
    cells = tables.get("cells") or {}
    grand = {k: v for k, v in (tables.get("grand") or {}).items() if k != "trades"}
    cfb = {}
    n = n_win = n_fee = 0
    pnl = 0.0
    any_pnl = False
    for kind in ("moneyline", "spread", "total"):
        rec = _lookup_cell(cells, "college football", "ALL", kind, "40-49")
        cfb[kind] = compact_cell("college football", "ALL", kind, "40-49", rec) if rec else None
        if rec:
            n += int(rec.get("n") or 0)
            n_win += int(rec.get("n_win") or 0)
            n_fee += int(rec.get("n_fee") or 0)
            if rec.get("pnl_sum") is not None:
                pnl += float(rec["pnl_sum"])
                any_pnl = True
    spot = spotcheck_from_cells(cells)
    prev = prev_snapshot()
    return {
        "kind_labels": {**KIND_LABEL, "ALL": "ALL bet types"},
        "kind_note": KIND_NOTE,
        "tape": "research_named_yes_t0",
        "n_sides": tables.get("n_sides"),
        "n_settled": tables.get("n_settled"),
        "grand": grand,
        "cfb_40_49": cfb,
        "cfb_40_49_grand": {
            "n": n,
            "n_win": n_win,
            "n_fee": n_fee,
            "pnl_sum": pnl if any_pnl else None,
            "note": "Sum of Moneyline + Spread + Points Total in college football 40-49. Not a tape kind.",
        },
        "spotcheck": spot,
        "prev_compare": compare_to_prev(spot, prev),
        "live_cells": cells_from_tables(tables),
    }


HIST_DIR = LOCAL_STAMP / "hist"
COV_HEADERS = [
    ("Sport", "text"),
    ("League", "text"),
    ("Bet type", "text"),
    ("Platform", "text"),
    ("Price kind", "text"),
    ("Span start", "date"),
    ("Span end", "date"),
    ("N events", "num"),
    ("N T0 sides", "num"),
    ("N missing", "num"),
    ("Fetched candles?", "text"),
    ("Note", "text"),
]


def load_json_list(path: Path, *, retries: int = 6, pause: float = 0.4) -> list:
    """Read a list JSON. Retry if a concurrent hist pull is mid-write. Never overwrite the file."""
    if not path.is_file():
        return []
    last_err = None
    for _ in range(max(1, retries)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(pause)
    print(f"hist read failed {path.name}: {type(last_err).__name__ if last_err else 'unknown'}", flush=True)
    return []


def load_hist_books() -> tuple[list[dict], list[dict], list[dict]]:
    kalshi = load_json_list(HIST_DIR / "books_kalshi.json")
    poly = load_json_list(HIST_DIR / "books_poly.json")
    cov = load_json_list(HIST_DIR / "coverage.json")
    return kalshi, poly, cov


def hist_holes_html(coverage: list[dict], hist_k, hist_p) -> str:
    cov = coverage or []
    k_cov = [r for r in cov if str(r.get("platform") or "").lower() == "kalshi"]
    p_cov = [r for r in cov if str(r.get("platform") or "").lower().startswith("poly")]
    k_sports = sorted({str(r.get("sport") or "") for r in k_cov if r.get("sport")})
    p_sports = sorted({str(r.get("sport") or r.get("league") or "") for r in p_cov if r.get("sport") or r.get("league")})
    k_n = int((hist_k or {}).get("n_settled") or 0)
    p_n = int((hist_p or {}).get("n_settled") or 0)
    k_span = ""
    if k_cov:
        los = [r.get("span_lo") for r in k_cov if r.get("span_lo")]
        his = [r.get("span_hi") for r in k_cov if r.get("span_hi")]
        if los and his:
            k_span = f"{min(str(x) for x in los)} .. {max(str(x) for x in his)}"
    p_span = ""
    if p_cov:
        los = [r.get("span_lo") for r in p_cov if r.get("span_lo")]
        his = [r.get("span_hi") for r in p_cov if r.get("span_hi")]
        if los and his:
            p_span = f"{min(str(x) for x in los)} .. {max(str(x) for x in his)}"
    holes = []
    if p_n == 0:
        holes.append(
            "Polymarket CLOB last-trade hist is empty on disk (books_poly.json N=0). "
            "Book 3 is labeled empty; live-tape and Kalshi books still publish."
        )
    missing_k = [r for r in k_cov if int(r.get("n_missing") or 0) > 0]
    missing_k.sort(key=lambda r: -int(r.get("n_missing") or 0))
    if missing_k:
        top = ", ".join(
            f"{r.get('series') or r.get('league')} {kind_label(r.get('kind') or '')} "
            f"missing {int(r.get('n_missing') or 0)}"
            for r in missing_k[:8]
        )
        holes.append(f"Kalshi candle holes (top): {top}.")
    expected = (
        "KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL",
        "KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL",
        "KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL",
        "KXNHLGAME", "KXNHLSPREAD", "KXNHLTOTAL",
        "KXMLBGAME", "KXMLBSPREAD", "KXMLBTOTAL",
        "KXWNBAGAME", "KXWNBASPREAD", "KXWNBATOTAL",
        "KXATPMATCH", "KXWTAMATCH",
        "KXEPLGAME", "KXEPLSPREAD", "KXEPLTOTAL",
        "KXMLSGAME", "KXMLSSPREAD", "KXMLSTOTAL",
        "KXUCLGAME", "KXUCLSPREAD", "KXUCLTOTAL",
        "KXBUNDESLIGAGAME", "KXBUNDESLIGASPREAD", "KXBUNDESLIGATOTAL",
        "KXSERIEAGAME", "KXSERIEASPREAD", "KXSERIEATOTAL",
        "KXLALIGAGAME", "KXLALIGASPREAD", "KXLALIGATOTAL",
        "KXLIGUE1GAME", "KXLIGUE1SPREAD", "KXLIGUE1TOTAL",
        "KXUFCFIGHT",
    )
    have = {str(r.get("series") or "") for r in k_cov if r.get("candles_fetched")}
    not_yet = [t for t in expected if t not in have]
    t0_dir = HIST_DIR / "kalshi" / "t0"
    have_t0_files = {p.stem for p in t0_dir.glob("*.jsonl")} if t0_dir.is_dir() else set()
    leftover_named = (
        "KXLIGUE1TOTAL", "KXUFCFIGHT", "KXMMAFIGHT",
        "KXCHALLENGERMATCH", "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH",
        "KXITFMATCH", "KXITFWMATCH",
        "KXPGA", "KXPGARYDERMATCH", "KXPRESCUPMATCH", "KXTGLMATCH", "KXPGAH2H",
    )
    named_missing = [t for t in leftover_named if t not in have and t not in have_t0_files]
    named_disk = [t for t in leftover_named if t in have_t0_files and t not in have]
    if named_missing:
        holes.append(
            "Kalshi leftovers still uncandled: " + ", ".join(named_missing) + "."
        )
    if named_disk:
        holes.append(
            "Kalshi t0 jsonl on disk but missing from coverage.json: "
            + ", ".join(named_disk) + "."
        )
    cov_path = HIST_DIR / "coverage.json"
    itf_t0 = t0_dir / "KXITFMATCH.jsonl"
    try:
        if itf_t0.is_file() and cov_path.is_file() and itf_t0.stat().st_mtime > cov_path.stat().st_mtime + 1:
            holes.append(
                "Leftover Kalshi candle job is still writing KXITFMATCH "
                "(t0 jsonl newer than coverage.json). Did not start a second pull. "
                "This page scored books_kalshi.json as of that coverage mtime — ITF not in the book yet."
            )
    except OSError:
        pass
    ryder = next((r for r in k_cov if str(r.get("series") or "") == "KXPGARYDERMATCH"), None)
    if ryder is not None and int(ryder.get("n_t0") or 0) == 0:
        holes.append(
            "Golf Ryder (KXPGARYDERMATCH) is in coverage.json but T0 N=0 "
            f"(missing {int(ryder.get('n_missing') or 0)})."
        )
    ufc = next((r for r in k_cov if str(r.get("series") or "") == "KXUFCFIGHT"), None)
    if ufc is None:
        holes.append("coverage.json still missing KXUFCFIGHT.")
    elif int(ufc.get("n_missing") or 0) > 0:
        holes.append(
            f"UFC is in coverage.json (T0 N={int(ufc.get('n_t0') or 0)}, "
            f"missing {int(ufc.get('n_missing') or 0)})."
        )
    if not_yet:
        holes.append(
            "Kalshi series not yet candled (or events-only): " + ", ".join(not_yet[:16])
            + ("…" if len(not_yet) > 16 else "") + "."
        )
    poly_expected = (
        "nfl", "cfb", "nba", "nhl", "mlb", "wnba", "atp", "wta",
        "ufc", "pga", "epl", "mls", "ucl", "ncaab",
    )
    have_p = {str(r.get("league") or r.get("sport") or "").lower() for r in p_cov if r.get("candles_fetched")}
    poly_missing = [s for s in poly_expected if s not in have_p]
    if poly_missing:
        holes.append(
            "Polymarket last-trade sports not on disk: " + ", ".join(poly_missing) + "."
        )
    hole_p = " ".join(esc(h) for h in holes) if holes else "No coverage holes listed."
    return (
        "<div class=\"callout\"><h2>History books on disk — incomplete is OK</h2>"
        f"<p>Kalshi Yes-ask hist: settled N={k_n}"
        f"{' spanning ' + esc(k_span) if k_span else ''}"
        f"{'; sports: ' + esc(', '.join(k_sports)) if k_sports else ''}.</p>"
        f"<p>Polymarket last-trade hist: settled N={p_n}"
        f"{' spanning ' + esc(p_span) if p_span else ''}"
        f"{'; sports: ' + esc(', '.join(p_sports)) if p_sports else ''}.</p>"
        f"<p>{hole_p} Did not mix Odds API / sportsbook closes. Did not wipe hist files. "
        "Kalshi history is the first book on this page. Live-tape deciles still publish.</p></div>"
    )


def coverage_rows(cov: list[dict]) -> list[list[str]]:
    rows = []
    for rec in cov:
        kind = rec.get("kind") or ""
        kind_disp = ", ".join(kind_label(k.strip()) for k in str(kind).split(",") if k.strip()) if kind else ""
        rows.append([
            esc(rec.get("sport") or ""),
            esc(rec.get("league") or rec.get("series") or ""),
            esc(kind_disp),
            esc(rec.get("platform") or ""),
            esc(rec.get("price_kind") or ""),
            esc(rec.get("span_lo") or ""),
            esc(rec.get("span_hi") or ""),
            str(int(rec.get("n_events") or 0)),
            str(int(rec.get("n_t0") or 0)),
            str(int(rec.get("n_missing") or 0)),
            esc("yes" if rec.get("candles_fetched") else "events only"),
            esc(rec.get("note") or ""),
        ])
    return rows


def book_blurb(tables: dict, *, label: str) -> str:
    grand = tables.get("grand") or {}
    n = int(grand.get("n") or 0)
    n_fee = int(grand.get("n_fee") or 0)
    return (
        f"{esc(label)}: settled N={n}, wins={int(grand.get('n_win') or 0)}, "
        f"win% {esc(fmt_pct(grand.get('win_pct')) if n else '—')}, "
        f"with-fee P&amp;L {esc(money_cell(grand.get('pnl_sum'), n_fee=n_fee))} "
        f"on N_fee={n_fee}, avg $ {esc(money_cell(grand.get('avg_pnl'), n_fee=n_fee))}. "
        "Ann ROR omitted on same-day holds."
    )


def hist_book_html(
    title: str,
    note: str,
    tables: dict | None,
    *,
    anchor: str = "",
    extra: str = "",
) -> str:
    id_attr = f' id="{esc(anchor)}"' if anchor else ""
    if not tables or not tables.get("n_settled"):
        return (
            f"<h2{id_attr}>{esc(title)}</h2>"
            f"<p class=\"note\">{esc(note)} No settled T0 sides on disk yet.</p>"
            f"{extra}"
        )
    return f"""<h2{id_attr}>{esc(title)}</h2>
<p class="note">{note} {book_blurb(tables, label="This book")}</p>
{extra}
{report_page_extras.SWIPE_NOTE_HTML}
<h3>All sports — each decile</h3>
{t0.table(HEADERS, tables.get("all_decile") or [])}
<h3>Sport × bet type × decile</h3>
{t0.table(HEADERS, tables.get("sport_decile") or [])}
<h3>Sport × league × bet type × decile</h3>
{t0.table(HEADERS, tables.get("detail") or [])}
<h3>Overall profitability (rollups)</h3>
{t0.table(HEADERS, tables.get("overall") or [])}
"""


def choose_page_path() -> Path:
    """Canonical path unless another job rewrote the HTML while we were scoring."""
    global _PREV_PAGE_MTIME
    if PAGE.is_file() and _PREV_PAGE_MTIME:
        try:
            if PAGE.stat().st_mtime > float(_PREV_PAGE_MTIME) + 1.0:
                stamped = STAMP / (
                    "sport_league_t0_decile_20261027_regen_"
                    + datetime.now(ET).strftime("%Y%m%d_%H%M%S")
                    + ".html"
                )
                print(f"canonical HTML mtime moved; writing {stamped.name}", flush=True)
                return stamped
        except OSError:
            pass
    return PAGE


def write_html(payload: dict, *, now: str, hist_k=None, hist_p=None, coverage=None) -> str:
    prev_snapshot()
    grand = payload.get("grand") or {}
    cells = payload.get("cells") or {}
    cfb_note = cfb_4049_blurb(cells)
    cmp = compare_to_prev(spotcheck_from_cells(cells), prev_snapshot())
    all_cmp = compare_live_cells(cells_from_tables(payload), _PREV_HTML_CELLS or {})
    holes_html = hist_holes_html(coverage or [], hist_k, hist_p)
    cov_html = ""
    if coverage:
        cov_html = (
            "<h2>Coverage — sport × type × platform</h2>"
            "<p class=\"note\">What exists on the public APIs vs what we actually reconstructed. "
            "Events-only rows were counted but not candled (too many soccer minors). "
            "Spread/Points Total history uses one primary line per game (both Yes sides), "
            "not every alternate number. Click column headers to sort.</p>"
            f"{report_page_extras.SWIPE_NOTE_HTML}"
            f"{t0.table(COV_HEADERS, coverage_rows(coverage))}"
        )
    kalshi_html = hist_book_html(
        "Kalshi history — Yes-ask T0 candles (Book 2, not blended)",
        "Last 1-minute yes_ask.close at or just before occurrence_datetime "
        "(else expected_expiration_time). Same Kalshi result and 0.07×p×(1−p) taker fee "
        "as the live tape. Not blended with Book 1 or with Polymarket. "
        "Kalshi NFL from July 2025 is entirely after 2024-01-01, so there is no in-sample "
        "row versus that split — the whole Kalshi NFL hist book is out-of-sample.",
        hist_k,
        anchor="kalshi-history",
        extra=kalshi_headline_html(hist_k),
    )
    poly_html = hist_book_html(
        "Polymarket historical (CLOB last-trade) — separate book",
        "Last CLOB trade p at or just before gameStartTime, fidelity 1 minute then 60. "
        "This is last-trade, not Yes ask. Global clob.polymarket.com, not Polymarket US. "
        "Theta taker fee. Never average these bands with Kalshi Yes-ask bands.",
        hist_p,
        anchor="poly-history",
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Sport / league / T0 decile win% and P&amp;L</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Sport / league / T0 decile win% and profitability</h1>
<p class="note">Written {esc(now)}. Research only. Did not retune live A–E.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{PLAIN}</p></div>
<div class="callout"><h2>Named-Yes T0 tape, not the live kitchen</h2>
{venue_truth_html(cmp, all_cmp)}</div>
<div class="callout"><h2>Rows are by bet type, not nested sums</h2>
<p>{esc(KIND_NOTE)} {esc(cfb_note)}</p></div>
<div class="callout"><h2>Three books, never blended</h2>
<p>Kalshi history is first. Book 1 is the 11-day four-platform live tape. Book 2 is Kalshi historical Yes ask.
Book 3 is Polymarket CLOB last-trade. Quality metrics (win%, N, with-fee P&amp;L, avg $)
are printed on each book. Do not read a Kalshi 40–49 win% as a Polymarket 40–49 win%.
Did not rescore frozen <code>compare.html</code> (24 Oct backtest).</p>
<p><a href="#kalshi-history">Jump to Kalshi history</a>
 · <a href="#book1-live">Live four-platform tape</a>
 · <a href="#poly-history">Polymarket last-trade</a>
 · <a href="t0_buy_sell_gain_decile_sport_bet_20261030.html">T0 buy then sell at +G (30 Oct)</a> · <a href="kalshi_poly_combined_t0_decile_20261030.html">Kalshi+Poly combined cheapest T0 (30 Oct)</a></p></div>
{holes_html}

{kalshi_html}
{cov_html}

<h2 id="book1-live">Book 1 — 11-day four-platform live tape (not history)</h2>
<p class="note">Settled unique-game-side tickets: {esc(payload.get('n_settled'))} (from {esc(payload.get('n_sides'))} venue sides after one-venue pick).
Grand: win% {esc(fmt_pct(grand.get('win_pct')) if grand.get('n') else '—')} on N={esc(grand.get('n'))};
with-fee P&amp;L {esc(money_cell(grand.get('pnl_sum'), n_fee=int(grand.get('n_fee') or 0)))} on N_fee={esc(grand.get('n_fee'))}.
IS = entry before 2024-01-01 (none on this October 2026 tape). OOS = the whole book.
Annualized rate of return uses the house formula; same-day holds omit Ann ROR instead of overflowing.
Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h3>All sports — each decile 0-9 through 90-99</h3>
<p class="note">Every settled named Yes, all sports and leagues together. Bet type here is ALL bet types (pooled). Overall is the last rollup table.</p>
{t0.table(HEADERS, payload.get("all_decile") or [])}

<h3>Sport × bet type × decile</h3>
<p class="note">League column is ALL here so tennis ATP/ITF/WTA are pooled inside tennis. Use the next table to split leagues. Points Total is the points market, not a subtotal.</p>
{t0.table(HEADERS, payload.get("sport_decile") or [])}

<h3>Sport × league × bet type × decile</h3>
<p class="note">The full grain you asked for. Tennis league is ATP / WTA / Challenger / ITF when the ticker or slug says so; otherwise it stays tennis.</p>
{t0.table(HEADERS, payload.get("detail") or [])}

<h3>Overall profitability (rollups)</h3>
<p class="note">ALL in Sport or League means that slice is pooled. ALL bet types + decile ALL is every settled ticket in that sport. Sport ALL + ALL bet types + decile ALL is the whole settled book.</p>
{t0.table(HEADERS, payload.get("overall") or [])}

{poly_html}

<p class="tiny">Generator: <code>tools/_write_sport_league_t0_decile_20261027.py</code>. Hist pull: <code>tools/_pull_pm_hist_t0_20261028.py</code>. T0 / settlement: <code>tools/t0_all_games_stats.py</code>.
Fees: <code>write_t0_band_from_stay_above.documented_leg_fee</code>. File URL {esc(FILE_URL)}.
Did not sell, start a second B, bump stake, wire D NFL, leftover GTC, or retune C=1.05.
Did not mix Odds API / sportsbook closes.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path = choose_page_path()
    path.write_text(html, encoding="utf-8")
    return str(path)


def build_from_books(books: list[dict]) -> dict:
    exploded = explode_cover_yes_sides(books)
    picked = pick_one_side(exploded)
    return build_tables(picked)


def main() -> int:
    prev_snapshot()
    print("loading T0 books (all-game tape)", flush=True)
    payload = t0.build_payload()
    tables = build_from_books(payload.get("books") or [])
    k_sides, p_sides, coverage = load_hist_books()
    hist_k = build_from_books(k_sides) if k_sides else None
    hist_p = build_from_books(p_sides) if p_sides else None
    now = payload.get("now") or datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    path = write_html(
        tables, now=now, hist_k=hist_k, hist_p=hist_p, coverage=coverage,
    )
    dump = json_dump(tables)
    live_vs = compare_live_cells(dump.get("live_cells") or {}, _PREV_HTML_CELLS or {})
    dump["live_vs_prior"] = {
        k: live_vs.get(k)
        for k in (
            "had_prev", "n_prior", "n_now", "n_flip_same_n", "n_n_moved",
            "n_new", "n_dropped", "n_tennis_flip", "verdict",
        )
    }
    dump["live_vs_prior"]["flips"] = [
        {"key": r.get("key"), "before": r.get("before"), "after": r.get("after")}
        for r in (live_vs.get("flips") or [])
    ]
    k_grand = (hist_k or {}).get("grand") or {}
    dump["hist"] = {
        "kalshi_n": int((hist_k or {}).get("n_settled") or 0),
        "poly_n": int((hist_p or {}).get("n_settled") or 0),
        "kalshi_n_sides": len(k_sides),
        "poly_n_sides": len(p_sides),
        "poly_price_kind": "CLOB last-trade (not Yes ask)",
        "kalshi_price_kind": "1-min yes_ask candle close",
        "coverage_n": len(coverage),
        "note": "hist books are separate; not blended into live grand",
        "kalshi_grand": {
            "n": int(k_grand.get("n") or 0),
            "n_win": int(k_grand.get("n_win") or 0),
            "n_fee": int(k_grand.get("n_fee") or 0),
            "pnl_sum": k_grand.get("pnl_sum"),
            "avg_pnl": k_grand.get("avg_pnl"),
        },
        "kalshi_headlines": kalshi_headlines((hist_k or {}).get("cells") or {}),
    }
    json_path = Path(path).with_suffix(".json")
    json_path.write_text(
        json.dumps(dump, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        f"wrote {path} kalshi_hist={dump['hist']['kalshi_n']} poly_hist={dump['hist']['poly_n']} "
        f"same_n_flips={dump['live_vs_prior'].get('n_flip_same_n')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
