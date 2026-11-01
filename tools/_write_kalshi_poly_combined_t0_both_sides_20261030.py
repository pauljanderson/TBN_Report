"""Combined Kalshi + Polymarket T0 both-named-Yes start→finish.

Research display only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not leftover-GTC A.
Does not DailyRun. Does not retune live B/C/D/E. Does not start System F.
Does not rewrite dashboard.html. Does not start a hist pull.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras  # noqa: E402
import t0_all_games_stats as t0  # noqa: E402
import _write_kalshi_poly_combined_t0_decile_20261030 as comb  # noqa: E402
import _write_sport_league_t0_decile_20261027 as decile_w  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
from t0_fav_lt90_baseline_20261024 import (  # noqa: E402
    COMPARE_HEADERS as QUALITY_HEADERS,
    fmt_pct,
    quality_row,
)

ET = ZoneInfo("America/New_York")
STAMP_SUB = STAMP / "kalshi_poly_combined_t0_both_sides_20261030"
PAGE = STAMP / "kalshi_poly_combined_t0_both_sides_20261030.html"
JSON_OUT = STAMP_SUB / "summary.json"
BASELINE = STAMP_SUB / "BASELINE.md"
PARENT_HTML = STAMP / "kalshi_poly_combined_t0_decile_20261030.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/kalshi_poly_combined_t0_both_sides_20261030.html"
)
DECADES = decile_w.DECADES
COMPLEMENT = {
    "0-9": "90-99",
    "10-19": "80-89",
    "20-29": "70-79",
    "30-39": "60-69",
    "40-49": "50-59",
    "50-59": "40-49",
    "60-69": "30-39",
    "70-79": "20-29",
    "80-89": "10-19",
    "90-99": "0-9",
}
LOW_DECADES = ("0-9", "10-19", "20-29", "30-39", "40-49")
FAV_DECADES = ("50-59", "60-69", "70-79", "80-89", "90-99")
C_LIKE = ("50-59", "60-69", "70-79", "80-89")  # live C is 51–89; 10¢ buckets
D_LIKE = ("50-59", "60-69", "70-79", "80-89")
TWO_WAY_ML_ORDER = (
    "college football",
    "pro football",
    "tennis",
    "hockey",
    "basketball",
    "baseball",
    "mma",
    "golf",
)
SPORT_LABEL = {
    "college football": "College football (CFB)",
    "pro football": "NFL",
    "tennis": "Tennis",
    "hockey": "NHL",
    "basketball": "NBA / basketball",
    "baseball": "MLB",
    "soccer": "Soccer",
    "mma": "MMA / UFC",
    "golf": "Golf / PGA",
    "wnba": "WNBA",
}
ASKED = (
    "Paul (Fri 30 Oct 2026): OK, but again can we focus on what we might have "
    "missed form the kalshi and polymarket start v finish data? this data count "
    "makes no sense to me. college football ALL Moneyline 10-19 347 / 0-9 1282 / "
    "20-29 280 / 30-39 241 / 40-49 198 / 50-59 15 / 60-69 2 / 70-79 1 if we had "
    "1,282 in the 0-9 range, wouldn't we also have that many in the 90-99 range "
    "for the other side of the bet?"
)
PLAIN = (
    "The earlier combined page kept only the cheaper named Yes per game — almost "
    "always the dog. That is why college football moneyline showed 1,282 tickets "
    "in the 0–9 opening-price bucket and almost none in 90–99: the expensive "
    "favorite Yes was dropped on purpose, not because Kalshi or Polymarket was "
    "missing games. This page buys both named Yes tickets. Same game, same bet, "
    "same named side: keep the cheaper shop after the take-a-trade fee; if only "
    "one shop listed that side, keep that one. Kalshi’s opening price is the Yes "
    "ask (the posted take-it price). Polymarket’s opening price on this tape is "
    "the last trade on the global Central Limit Order Book (CLOB) — not an ask, "
    "and not Polymarket US. Then we hold to the $1 / $0 result and ask whether "
    "that made money after the fee. Moneyline (ML) is who wins. Spread is whether "
    "a side covers a point line. Points Total is the over/under on combined score. "
    "On a two-way moneyline, N in 0–9 should sit near N in 90–99 if both sides stay. "
    "They will not match 1:1 when Yes+Yes is not $1 (cross-shop, Poly last-trade vs "
    "Kalshi ask), the other side is missing, soccer is three-way (Tie), or a spread "
    "/ total is not a clean p and 1−p pair. Live B/C/D/E knobs were not changed. "
    "System F was not started."
)

PAIR_HEADERS = [
    ("Sport", "text"),
    ("Bet type", "text"),
    ("N 0-9", "num"),
    ("N 90-99", "num"),
    ("Gap (0-9 minus 90-99)", "num"),
    ("2-side markets", "num"),
    ("1-side markets", "num"),
    ("3+ sides / 3-way", "num"),
    ("0-9 with 90-99 partner", "num"),
    ("0-9 partner in 80-89", "num"),
    ("0-9 unpaired", "num"),
    ("90-99 unpaired", "num"),
    ("Mean Yes+Yes (2-side)", "num"),
    ("Cross-venue 2-side", "num"),
    ("Why any gap", "text"),
]
COMP_HEADERS = [
    ("Low decile", "text"),
    ("N low", "num"),
    ("Complement", "text"),
    ("N complement", "num"),
    ("Gap (low minus complement)", "num"),
]
SIDE_HEADERS = [
    ("Sport", "text"),
    ("Bet type", "text"),
    ("Decile", "text"),
    ("Cheaper-Yes N", "num"),
    ("Both-sides N", "num"),
    ("Δ N (both minus cheaper)", "num"),
    ("Cheaper-Yes win%", "num"),
    ("Both-sides win%", "num"),
    ("Cheaper-Yes avg with-fee P&L", "num"),
    ("Both-sides avg with-fee P&L", "num"),
]
HIDDEN_HEADERS = [
    ("Slice", "text"),
    ("Cheaper-Yes N", "num"),
    ("Both-sides N", "num"),
    ("Both-sides wins", "num"),
    ("Both-sides win%", "num"),
    ("Both-sides with-fee avg P&L", "num"),
    ("Both-sides with-fee total P&L", "num"),
    ("What cheaper-Yes did", "text"),
]


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def esc(value) -> str:
    return comb.esc(value)


def sport_label(sport: str) -> str:
    raw = str(sport or "").strip()
    return SPORT_LABEL.get(raw.lower(), raw or "unknown")


def market_key(row: dict) -> str:
    key = str(row.get("_market") or "")
    if key:
        return key
    return (
        f"{str(row.get('sport') or '').lower()}|{row.get('kind') or 'moneyline'}|"
        f"{row.get('_date') or row.get('entry_date') or ''}|"
        f"{'|'.join(sorted(row.get('_game_ids') or []))}|{comb.line_key(row.get('number'))}"
    )


def pair_records(sides: list[dict]) -> list[dict]:
    bags: dict[str, list[dict]] = defaultdict(list)
    for row in sides:
        bags[market_key(row)].append(row)
    out = []
    for key, group in bags.items():
        ordered = sorted(group, key=lambda s: (float(s["t0_fav"]), str(s.get("fav_name") or "")))
        lo = ordered[0]
        hi = ordered[-1] if len(ordered) >= 2 else None
        lo_px = float(lo["t0_fav"])
        hi_px = float(hi["t0_fav"]) if hi is not None and hi is not lo else None
        lo_band = decile_w.decile_of(lo_px)
        hi_band = decile_w.decile_of(hi_px) if hi_px is not None else None
        venues = {str(s.get("venue") or s.get("_source_venue") or "") for s in group}
        three = any(bool(s.get("_three_way")) for s in group)
        rec = {
            "key": key,
            "sport": str(lo.get("sport") or ""),
            "kind": str(lo.get("kind") or "moneyline"),
            "n": len(group),
            "three_way": three,
            "lo": lo,
            "hi": hi,
            "lo_px": lo_px,
            "hi_px": hi_px,
            "lo_band": lo_band,
            "hi_band": hi_band,
            "px_sum": (lo_px + hi_px) if hi_px is not None else None,
            "complement_hit": bool(
                hi_band and lo_band and COMPLEMENT.get(lo_band) == hi_band
            ),
            "cross_venue": len(venues) > 1,
            "venues": sorted(venues),
        }
        out.append(rec)
    return out


def _filter_recs(records: list[dict], sport: str, kind: str) -> list[dict]:
    sport_l = str(sport or "").lower()
    kind_l = str(kind or "")
    out = []
    for rec in records:
        if sport_l and str(rec.get("sport") or "").lower() != sport_l:
            continue
        if kind_l and str(rec.get("kind") or "") != kind_l:
            continue
        out.append(rec)
    return out


def count_deciles(sides: list[dict], sport: str, kind: str) -> dict[str, int]:
    sport_l = str(sport or "").lower()
    kind_l = str(kind or "")
    out = {d: 0 for d in DECADES}
    for row in sides:
        if sport_l and str(row.get("sport") or "").lower() != sport_l:
            continue
        if kind_l and str(row.get("kind") or "") != kind_l:
            continue
        band = decile_w.decile_of(row.get("t0_fav"))
        if band in out:
            out[band] += 1
    return out


def pairing_summary(records: list[dict], sides: list[dict], sport: str, kind: str) -> dict:
    recs = _filter_recs(records, sport, kind)
    dec = count_deciles(sides, sport, kind)
    n_09 = int(dec.get("0-9") or 0)
    n_9099 = int(dec.get("90-99") or 0)
    n_one = n_two = n_gt2 = n_three = 0
    n_09_with_9099 = n_09_with_8089 = n_09_with_other = n_09_unpaired = 0
    n_9099_unpaired = n_9099_with_non09 = 0
    sums: list[float] = []
    n_cross = 0
    for rec in recs:
        if rec.get("three_way"):
            n_three += 1
        n = int(rec.get("n") or 0)
        lo_band = rec.get("lo_band")
        hi_band = rec.get("hi_band")
        if n <= 1:
            n_one += 1
            if lo_band == "0-9":
                n_09_unpaired += 1
            if lo_band == "90-99":
                n_9099_unpaired += 1
            continue
        if n == 2:
            n_two += 1
        else:
            n_gt2 += 1
        if rec.get("px_sum") is not None:
            sums.append(float(rec["px_sum"]))
        if rec.get("cross_venue"):
            n_cross += 1
        if lo_band == "0-9":
            if hi_band == "90-99":
                n_09_with_9099 += 1
            elif hi_band == "80-89":
                n_09_with_8089 += 1
            else:
                n_09_with_other += 1
        if hi_band == "90-99" and lo_band != "0-9":
            n_9099_with_non09 += 1
    mean_sum = (sum(sums) / len(sums)) if sums else None
    gap = n_09 - n_9099
    why = gap_reason(
        gap=gap,
        n_09=n_09,
        n_9099=n_9099,
        n_09_with_9099=n_09_with_9099,
        n_09_with_8089=n_09_with_8089,
        n_09_unpaired=n_09_unpaired,
        n_9099_unpaired=n_9099_unpaired,
        n_9099_with_non09=n_9099_with_non09,
        n_three=n_three,
        kind=kind,
        mean_sum=mean_sum,
        n_cross=n_cross,
        n_two=n_two,
    )
    return {
        "sport": sport,
        "kind": kind,
        "deciles": dec,
        "n_09": n_09,
        "n_9099": n_9099,
        "gap": gap,
        "n_one": n_one,
        "n_two": n_two,
        "n_gt2": n_gt2,
        "n_three": n_three,
        "n_09_with_9099": n_09_with_9099,
        "n_09_with_8089": n_09_with_8089,
        "n_09_with_other": n_09_with_other,
        "n_09_unpaired": n_09_unpaired,
        "n_9099_unpaired": n_9099_unpaired,
        "n_9099_with_non09": n_9099_with_non09,
        "mean_sum": mean_sum,
        "n_cross": n_cross,
        "n_two_with_sum": len(sums),
        "why": why,
    }


def gap_reason(
    *,
    gap: int,
    n_09: int,
    n_9099: int,
    n_09_with_9099: int,
    n_09_with_8089: int,
    n_09_unpaired: int,
    n_9099_unpaired: int,
    n_9099_with_non09: int,
    n_three: int,
    kind: str,
    mean_sum: float | None,
    n_cross: int,
    n_two: int,
) -> str:
    if n_09 == 0 and n_9099 == 0:
        return "No tickets in 0–9 or 90–99."
    if gap == 0 and n_09_with_9099 == n_09 == n_9099:
        return "Exact pair: every 0–9 has a 90–99 partner."
    bits = []
    if abs(gap) <= max(3, int(0.02 * max(n_09, n_9099, 1))) and n_09_with_9099:
        bits.append(
            f"Close pair ({n_09} vs {n_9099}); {n_09_with_9099} markets have the textbook 0–9 / 90–99 complement."
        )
    else:
        bits.append(f"N(0–9)={n_09}, N(90–99)={n_9099}, gap={gap:+d}.")
    if n_09_with_8089:
        bits.append(
            f"{n_09_with_8089} dogs in 0–9 have the favorite in 80–89 (Yes+Yes < $1, often Poly last-trade vs Kalshi ask)."
        )
    if n_09_unpaired:
        bits.append(
            f"{n_09_unpaired} one-sided markets sit in 0–9 with no other named Yes "
            "(often the favorite was a $1 T0 candle and was dropped; fee needs 0<p<1)."
        )
    if n_9099_unpaired:
        bits.append(f"{n_9099_unpaired} one-sided markets sit in 90–99 (favorite-only; cheaper-Yes dropped these).")
    if n_9099_with_non09:
        bits.append(
            f"{n_9099_with_non09} favorites in 90–99 pair with a dog outside 0–9 (Yes+Yes > $1 or dog in 10–19)."
        )
    if n_three:
        bits.append(f"{n_three} three-way events (Tie) — not a p and 1−p pair.")
    if kind in {"spread", "total"}:
        bits.append("Spread / Points Total sides are not a clean moneyline p and 1−p pair.")
    if mean_sum is not None and n_two:
        bits.append(
            f"Two-side mean Yes+Yes={mean_sum:.3f} ({n_cross} cross-venue of {n_two} two-side markets)."
        )
    return " ".join(bits)


def cell_rec(tables: dict, sport: str, kind: str, band: str) -> dict:
    cells = tables.get("cells") or {}
    rec = cells.get((sport, "ALL", kind, band)) or {}
    if rec:
        return rec
    if sport and sport != "ALL":
        alt = decile_w.SPORT_LEAGUE.get(str(sport).lower())
        if alt:
            rec = cells.get((sport, alt, kind, band)) or {}
    return rec or {}


def cell_n(tables: dict, sport: str, kind: str, band: str) -> int:
    return int(cell_rec(tables, sport, kind, band).get("n") or 0)


def complement_rows(sides: list[dict], sport: str, kind: str) -> list[list[str]]:
    dec = count_deciles(sides, sport, kind)
    rows = []
    for low in LOW_DECADES:
        high = COMPLEMENT[low]
        n_lo = int(dec.get(low) or 0)
        n_hi = int(dec.get(high) or 0)
        rows.append([low, str(n_lo), high, str(n_hi), str(n_lo - n_hi)])
    return rows


def pairing_rows(summaries: list[dict]) -> list[list[str]]:
    rows = []
    for rec in summaries:
        mean_sum = rec.get("mean_sum")
        rows.append([
            sport_label(rec.get("sport") or ""),
            decile_w.kind_label(rec.get("kind") or ""),
            str(rec.get("n_09") or 0),
            str(rec.get("n_9099") or 0),
            str(rec.get("gap") or 0),
            str(rec.get("n_two") or 0),
            str(rec.get("n_one") or 0),
            str(int(rec.get("n_gt2") or 0) + int(rec.get("n_three") or 0)),
            str(rec.get("n_09_with_9099") or 0),
            str(rec.get("n_09_with_8089") or 0),
            str(rec.get("n_09_unpaired") or 0),
            str(rec.get("n_9099_unpaired") or 0),
            f"{mean_sum:.3f}" if mean_sum is not None else "—",
            str(rec.get("n_cross") or 0),
            esc(rec.get("why") or ""),
        ])
    return rows


def _side_row(sport_txt: str, kind_txt: str, band: str, cheap: dict, both: dict) -> list[str]:
    cn = int(cheap.get("n") or 0)
    bn = int(both.get("n") or 0)
    return [
        sport_txt,
        kind_txt,
        band,
        str(cn),
        str(bn),
        str(bn - cn),
        fmt_pct(cheap.get("win_pct")) if cn else "—",
        fmt_pct(both.get("win_pct")) if bn else "—",
        decile_w.money_cell(cheap.get("avg_pnl"), n_fee=int(cheap.get("n_fee") or 0)),
        decile_w.money_cell(both.get("avg_pnl"), n_fee=int(both.get("n_fee") or 0)),
    ]


def side_by_side_rows(cheap_t: dict, both_t: dict, *, sport: str | None = None, rollup_only: bool = False) -> list[list[str]]:
    rows: list[list[str]] = []
    if rollup_only:
        for band in DECADES:
            c = cell_rec(cheap_t, "ALL", "ALL", band)
            b = cell_rec(both_t, "ALL", "ALL", band)
            if int(c.get("n") or 0) or int(b.get("n") or 0):
                rows.append(_side_row("ALL", "ALL bet types", band, c, b))
        for band in DECADES:
            c = decile_w.headline_spot(cheap_t.get("cells") or {}, "", "ALL", "moneyline", (band,))
            b = decile_w.headline_spot(both_t.get("cells") or {}, "", "ALL", "moneyline", (band,))
            if int(c.get("n") or 0) or int(b.get("n") or 0):
                rows.append(_side_row("ALL", "Moneyline", band, c, b))
        return rows
    kinds: set[str] = set()
    for tables in (cheap_t, both_t):
        for sp, lg, kd, _band in (tables.get("cells") or {}):
            if lg != "ALL" or kd in ("", "ALL") or sp in ("", "ALL"):
                continue
            if sport and sp != sport:
                continue
            kinds.add(kd)
    sp = sport or ""
    for kd in sorted(kinds, key=lambda k: {"moneyline": 0, "spread": 1, "total": 2}.get(k, 9)):
        for band in DECADES:
            c = cell_rec(cheap_t, sp, kd, band)
            b = cell_rec(both_t, sp, kd, band)
            if int(c.get("n") or 0) or int(b.get("n") or 0):
                rows.append(_side_row(sport_label(sp), decile_w.kind_label(kd), band, c, b))
    return rows


def hidden_rows(cheap_t: dict, both_t: dict) -> list[list[str]]:
    specs = [
        ("CFB ML 50–89 (C-like; live C is 51–89, 10¢ buckets)", "college football", "moneyline", C_LIKE),
        ("CFB ML 90–99", "college football", "moneyline", ("90-99",)),
        ("CFB ML 50–99 (all favorites)", "college football", "moneyline", FAV_DECADES),
        ("NFL ML 50–99", "pro football", "moneyline", FAV_DECADES),
        ("Tennis ML 50–99", "tennis", "moneyline", FAV_DECADES),
        ("NHL ML 50–99", "hockey", "moneyline", FAV_DECADES),
        ("NBA / basketball ML 50–99", "basketball", "moneyline", FAV_DECADES),
        ("MLB ML 50–99", "baseball", "moneyline", FAV_DECADES),
        ("ALL sports ML 50–99", "", "moneyline", FAV_DECADES),
        ("Spread 50–89 (D-like) all sports", "", "spread", D_LIKE),
        ("Spread 90–99 all sports", "", "spread", ("90-99",)),
        ("Points Total 50–99 all sports", "", "total", FAV_DECADES),
    ]
    rows = []
    for label, sport, kind, bands in specs:
        cheap_spot = decile_w.headline_spot(cheap_t.get("cells") or {}, sport, "ALL", kind, bands)
        both_spot = decile_w.headline_spot(both_t.get("cells") or {}, sport, "ALL", kind, bands)
        cn = int(cheap_spot.get("n") or 0)
        bn = int(both_spot.get("n") or 0)
        dropped = bn - cn
        if dropped > 0:
            what = f"Dropped {dropped} favorite-side tickets (kept {cn})."
        elif bn == 0 and cn == 0:
            what = "Neither book has this slice."
        else:
            what = f"Cheaper-Yes already kept {cn} of {bn}."
        n_fee = int(both_spot.get("n_fee") or 0)
        rows.append([
            label,
            str(cn),
            str(bn),
            str(int(both_spot.get("n_win") or 0)),
            fmt_pct(both_spot.get("win_pct")) if bn else "—",
            decile_w.money_cell(both_spot.get("avg_pnl"), n_fee=n_fee),
            decile_w.money_cell(both_spot.get("pnl_sum"), n_fee=n_fee),
            what,
        ])
    return rows


def hidden_paragraph(cheap_t: dict, both_t: dict, cfb: dict) -> str:
    c_spot = decile_w.headline_spot(
        both_t.get("cells") or {}, "college football", "ALL", "moneyline", C_LIKE
    )
    d_spot = decile_w.headline_spot(
        both_t.get("cells") or {}, "", "ALL", "spread", D_LIKE
    )
    fav_spot = decile_w.headline_spot(
        both_t.get("cells") or {}, "", "ALL", "moneyline", FAV_DECADES
    )
    cheap_fav = decile_w.headline_spot(
        cheap_t.get("cells") or {}, "", "ALL", "moneyline", FAV_DECADES
    )
    cheap_c = decile_w.headline_spot(
        cheap_t.get("cells") or {}, "college football", "ALL", "moneyline", C_LIKE
    )
    cheap_d = decile_w.headline_spot(
        cheap_t.get("cells") or {}, "", "ALL", "spread", D_LIKE
    )
    n_c = int(c_spot.get("n") or 0)
    n_d = int(d_spot.get("n") or 0)
    n_fav = int(fav_spot.get("n") or 0)
    return (
        f"Cheaper-Yes hid the favorite half of the ticket. Combined 5425-style "
        f"college football moneyline kept {cfb.get('cheap_n_09') or 0} in 0–9 and "
        f"{cfb.get('cheap_n_9099') or 0} in 90–99; both-sides restores "
        f"{cfb.get('n_09') or 0} in 0–9 and {cfb.get('n_9099') or 0} in 90–99. "
        f"All-sports moneyline 50–99: cheaper-Yes N={int(cheap_fav.get('n') or 0)}, "
        f"both-sides N={n_fav}, win% {fmt_pct(fav_spot.get('win_pct')) if n_fav else '—'}, "
        f"avg with-fee P&L {decile_w.money_cell(fav_spot.get('avg_pnl'), n_fee=int(fav_spot.get('n_fee') or 0))}. "
        f"C-like CFB ML 50–89 (live C is 51–89; 10¢ buckets): cheaper-Yes N="
        f"{int(cheap_c.get('n') or 0)}, both-sides N={n_c}, win% "
        f"{fmt_pct(c_spot.get('win_pct')) if n_c else '—'}, avg "
        f"{decile_w.money_cell(c_spot.get('avg_pnl'), n_fee=int(c_spot.get('n_fee') or 0))}. "
        f"D-like spread 50–89: cheaper-Yes N={int(cheap_d.get('n') or 0)}, both-sides N={n_d}, "
        f"win% {fmt_pct(d_spot.get('win_pct')) if n_d else '—'}, avg "
        f"{decile_w.money_cell(d_spot.get('avg_pnl'), n_fee=int(d_spot.get('n_fee') or 0))}. "
        "That is the start→finish book cheaper-Yes never showed. HOLD live knobs. "
        "Do not pick a band from a green cell."
    )


def freeze_rows() -> list[list[str]]:
    return [
        ["Kalshi hist", "books_kalshi.json — T0 Yes-ask (1-min yes_ask.close)"],
        ["Polymarket hist", "books_poly.json — T0 last-trade on global CLOB, not Yes-ask, not Polymarket US"],
        ["Sportsbooks", "Not mixed. Odds API closes are out."],
        ["Same settlement", "Same sport + bet type + named Yes + overlapping game tokens + date ±1 day + T0 clock ≤ 18h. Winner must agree."],
        ["Venue pick", "Same game + bet + named Yes: cheaper after-fee shop. Else the one shop. Kalshi 0.07×p×(1−p). Poly house theta."],
        ["Main book", "Both named Yes sides after the venue pick (dog and favorite)."],
        ["Cheaper-Yes book", "One named cheaper Yes per market (the previous combined page / 5425-style). Shown only as the control that starved 50–99."],
        ["Decile", "Selected T0 quote before fee (Kalshi ask, Poly last-trade). House 0–9 … 90–99."],
        ["Exit", "T0 buy, hold to settle. With-fee P&L = 1 − ask − fee on a win, else −ask − fee."],
        ["IS / OOS", "IS = entry_date &lt; 2024-01-01; OOS ≥ 2024-01-01. This tape starts Apr 2025 so IS is empty. Do not retune on OOS."],
        ["Ann ROR", "House compare_format.ann_ror_from_closed. Hist end_ts = T0 so average days held is ~0 — omitted (same-day overflow guard)."],
        ["Live knobs", "HOLD. Did not start a second B, leftover-GTC A, DailyRun, retune B/C/D/E, or start System F."],
        ["T0=1.00 rows", "Dropped. Fee formula needs 0&lt;p&lt;1."],
    ]


def arm_quality_rows(arms: dict[str, dict], control_id: str) -> list[list[str]]:
    control_q = (arms.get(control_id) or {}).get("quality") or {}
    rows = []
    for name, tables in arms.items():
        q = tables.get("quality") or {}
        if not q:
            continue
        row = quality_row(q, control_q if name != control_id else None)
        row[0] = esc(name)
        rows.append(row)
    return rows


def write_baseline(payload: dict, now: str) -> None:
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    cfb = payload.get("cfb") or {}
    text = f"""# Combined Kalshi + Polymarket T0 both named Yes sides — freeze

Written {now}. Report only. Live B/C/D/E knobs were not patched. System F was not started.

## What you asked

{ASKED}

## In plain English

{PLAIN}

## Freeze

- **Main identity:** both named Yes sides after cheaper-venue pick.
- **Control (display only):** cheaper named Yes per market (previous combined page).
- **CFB ML both-sides N 0–9 / 90–99:** {cfb.get('n_09')} / {cfb.get('n_9099')} (gap {cfb.get('gap')}).
- **CFB ML cheaper-Yes N 0–9 / 90–99:** {cfb.get('cheap_n_09')} / {cfb.get('cheap_n_9099')}.
- **Why any gap:** {cfb.get('why')}
- **IS / OOS:** book starts Apr 2025 — IS N=0. Do not retune on OOS.
- **Ann ROR:** omitted (same-day holds).
- **Live knobs:** HOLD. Did not start a second B, leftover-GTC A, DailyRun, retune B/C/D/E, or start System F.
- **Selection:** Do not pick a live band from this table.

## What cheaper-Yes hid

{payload.get('hidden_blurb') or ''}
"""
    BASELINE.write_text(text, encoding="utf-8")


def write_html(payload: dict, *, now: str) -> str:
    cheap_t = payload.get("cheap_tables") or {}
    both_t = payload.get("both_tables") or {}
    arms = payload.get("arms") or {}
    cfb = payload.get("cfb") or {}
    pair_tbl = t0.table(PAIR_HEADERS, payload.get("pairing_rows") or [])
    cfb_comp = t0.table(COMP_HEADERS, payload.get("cfb_comp_rows") or [])
    ml_comp_blocks = payload.get("ml_comp_html") or ""
    side_all = t0.table(SIDE_HEADERS, payload.get("side_all_rows") or [])
    side_cfb = t0.table(SIDE_HEADERS, payload.get("side_cfb_rows") or [])
    hidden_tbl = t0.table(HIDDEN_HEADERS, payload.get("hidden_rows") or [])
    quality_tbl = t0.table(QUALITY_HEADERS, arm_quality_rows(arms, "Cheaper-Yes only (dogs)"))
    cfb_both_decile = t0.table(decile_w.HEADERS, payload.get("cfb_ml_both_rows") or [])
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Kalshi + Polymarket combined T0 both named Yes sides</title>
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
<h1>Kalshi + Polymarket combined T0 both named Yes sides</h1>
<p class="note">Written {esc(now)}. Did not retune live A–E. Did not start a second B. Did not leftover-GTC A. Did not DailyRun. Did not start System F. Did not rewrite dashboard.html. Parent cheaper-Yes page: <a href="kalshi_poly_combined_t0_decile_20261030.html">kalshi_poly_combined_t0_decile_20261030.html</a>.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout"><h2>Paul’s count — cheaper-Yes was dogs only</h2>
<p>The 30 Oct combined page quoted college football ALL Moneyline
<strong>0–9 = 1,282</strong> / 10–19 = 347 / 20–29 = 280 / 30–39 = 241 / 40–49 = 198 /
50–59 = 15 / 60–69 = 2 / 70–79 = 1, and starved 80–99. That book is
<strong>named cheaper Yes per market</strong>. The other named Yes (the favorite,
near 90–99) was dropped. 50–99 starvation is that identity, not missing Kalshi or
Polymarket games. Paul is right: for a two-way moneyline, N(0–9) should sit near
N(90–99) if both sides are kept.</p>
<p>This page’s college football moneyline both-sides count is
<strong>0–9 = {esc(cfb.get('n_09'))}</strong> vs
<strong>90–99 = {esc(cfb.get('n_9099'))}</strong>
(gap {esc(cfb.get('gap'))}). Cheaper-Yes on the same tape:
0–9 = {esc(cfb.get('cheap_n_09'))}, 90–99 = {esc(cfb.get('cheap_n_9099'))}.</p>
<p>{esc(cfb.get('why') or '')}</p>
</div>

<div class="callout"><h2>Quote type — Poly last-trade vs Kalshi Yes-ask</h2>
<p>Kalshi history is a T0 <strong>Yes ask</strong> (1-minute yes_ask.close).
Polymarket history is a T0 <strong>last trade</strong> on the global CLOB, not a Yes ask
and not Polymarket US. Same named Yes keeps the cheaper after-fee venue; otherwise
the one shop. Yes+Yes will not equal $1 when the two sides were picked from
different quote types or different shops.</p></div>

<div class="callout"><h2>Freeze</h2>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table([("Knob", "text"), ("Value", "text")], freeze_rows())}
<p class="note">IS is empty — the book starts April 2025, after 2024-01-01. Do not retune on OOS.
Annualized rate of return (Ann ROR) uses the house formula and is omitted because hist holds are same-day.
HOLD live knobs. Do not pick a band from a green cell. Click column headers to sort.</p>
</div>

<h2>1. College football moneyline — both sides, every decile</h2>
<p class="note">Both named Yes after the venue pick. Complement of 0–9 is 90–99.
{esc(decile_w.KIND_NOTE)} Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<h3>0–9 vs 90–99 pairing (and the other complementary buckets)</h3>
{cfb_comp}
<p class="note">{esc(cfb.get('why') or '')}</p>
<h3>Start → finish on both sides (CFB ML)</h3>
{cfb_both_decile}

<h2>2. Other two-way moneyline sports — 0–9 vs 90–99</h2>
<p class="note">NFL, tennis, NHL, NBA, MLB, and the other two-way moneyline books on tape.
Soccer three-way Tie is not a p and 1−p pair — flagged in the gap column.
They will not match 1:1 when Yes+Yes ≠ $1, the other side is missing, or the market is not two-way.
Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{pair_tbl}
{ml_comp_blocks}

<h2>3. Cheaper-Yes only vs both-sides — why 50–99 starved</h2>
<p class="note">Cheaper-Yes is the previous combined / 5425-style book (one named Yes, usually the dog).
Both-sides keeps the favorite. Δ N in 50–99 is what that page hid. Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<h3>All sports, each decile</h3>
{side_all}
<h3>College football, each bet type × decile</h3>
{side_cfb}
<h3>Favorite buckets cheaper-Yes hid</h3>
{hidden_tbl}
<p class="note">{esc(payload.get('hidden_blurb') or '')}</p>

<h2>4. Start vs finish — both named Yes, sport × bet type × decile</h2>
<p class="note">T0 buy, hold to settle, with-fee average P&amp;L and win rate.
This is what cheaper-Yes missed: favorites 50–99, C-like CFB ML 50–89, D-like spread favorites 50–89.
{decile_w.book_blurb(both_t, label="Both named Yes combined")}
Do not pick a live band from a green cell. HOLD C/D/E/B. Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<h3>All sports — each decile</h3>
{t0.table(decile_w.HEADERS, both_t.get("all_decile") or [])}
<h3>Sport × bet type × decile</h3>
{t0.table(decile_w.HEADERS, both_t.get("sport_decile") or [])}
<h3>Sport × league × bet type × decile</h3>
{t0.table(decile_w.HEADERS, both_t.get("detail") or [])}
<h3>Overall (rollups)</h3>
{t0.table(decile_w.HEADERS, both_t.get("overall") or [])}

<h2>5. Canonical compare — cheaper-Yes (control) vs both-sides (this page)</h2>
<p class="note">Canonical compare metrics. Grain is unique-game-side. Quality over N.
Do not judge on max single-trade P&amp;L. Ann ROR omitted on same-day holds.
IS N=0 because the tape starts April 2025. Do not retune on OOS. HOLD live knobs.
Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{quality_tbl}

<p class="tiny">Parent cheaper-Yes: <a href="kalshi_poly_combined_t0_decile_20261030.html">kalshi_poly_combined_t0_decile_20261030.html</a>.
Unblended sport / league / T0: <a href="sport_league_t0_decile_20261027.html">sport_league_t0_decile_20261027.html</a>.
Generator: <code>tools/_write_kalshi_poly_combined_t0_both_sides_20261030.py</code>.
File URL {esc(FILE_URL)}.
Did not sell, start a second B, leftover-GTC A, DailyRun, retune C/D/E, or start System F.
Did not mix Odds API / sportsbook closes. Did not rewrite dashboard.html.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return str(PAGE)


def compact_grand(tables: dict) -> dict:
    return comb.compact_grand(tables)


def cfb_ml_both_rows(both_t: dict) -> list[list[str]]:
    rows = []
    for band in DECADES:
        rec = cell_rec(both_t, "college football", "moneyline", band)
        if not rec and not cell_n(both_t, "college football", "moneyline", band):
            rec = {"n": 0, "n_win": 0, "win_pct": None, "n_fee": 0, "pnl_sum": None, "avg_pnl": None, "note": ""}
        rows.append(decile_w.row_cells("college football", "ALL", "moneyline", band, rec))
    rec_all = cell_rec(both_t, "college football", "moneyline", "ALL")
    if rec_all:
        rows.append(decile_w.row_cells("college football", "ALL", "moneyline", "ALL", rec_all))
    return rows


def ml_comp_html(sides: list[dict], sports: list[str]) -> str:
    blocks = []
    for sport in sports:
        if sport == "college football":
            continue
        dec = count_deciles(sides, sport, "moneyline")
        if not any(dec.values()):
            continue
        rows = complement_rows(sides, sport, "moneyline")
        blocks.append(
            f"<h3>{esc(sport_label(sport))} moneyline — complementary buckets</h3>\n"
            f"{t0.table(COMP_HEADERS, rows)}"
        )
    return "\n".join(blocks)


def link_parent_page() -> None:
    if not PARENT_HTML.is_file():
        return
    html = PARENT_HTML.read_text(encoding="utf-8")
    marker = "kalshi_poly_combined_t0_both_sides_20261030.html"
    if marker in html:
        return
    needle = (
        '<a href="combined_t0_decile_system_recs_20261030.html">'
        "A–E recommendations (30 Oct)</a>"
    )
    extra = (
        needle
        + ' · <a href="kalshi_poly_combined_t0_both_sides_20261030.html">'
        + "both named Yes sides (30 Oct)</a>"
    )
    if needle in html:
        html = html.replace(needle, extra, 1)
    old = "Not the main book."
    new = (
        'Dedicated both-sides page (main identity, 0–9 vs 90–99 pairing): '
        '<a href="kalshi_poly_combined_t0_both_sides_20261030.html">'
        "kalshi_poly_combined_t0_both_sides_20261030.html</a>. "
        "This cheaper-Yes section stays dogs only."
    )
    if old in html:
        html = html.replace(old, new, 1)
    PARENT_HTML.write_text(html, encoding="utf-8")


def dump_json(payload: dict, path: str) -> None:
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    out = {
        "cfb": payload.get("cfb"),
        "pairing": payload.get("pairing_compact"),
        "cheap_grand": compact_grand(payload.get("cheap_tables") or {}),
        "both_grand": compact_grand(payload.get("both_tables") or {}),
        "hidden_blurb": payload.get("hidden_blurb"),
        "html": path,
        "poly_price_kind": "CLOB last-trade (not Yes ask)",
        "kalshi_price_kind": "1-min yes_ask candle close",
        "main_identity": "both named Yes after cheaper-venue pick",
        "is_cut": comb.IS_CUT,
        "system_f_started": False,
    }
    JSON_OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")


def two_way_sports(sides: list[dict]) -> list[str]:
    seen = sorted({str(r.get("sport") or "") for r in sides if r.get("sport")})
    ordered = [s for s in TWO_WAY_ML_ORDER if s in seen]
    extra = [s for s in seen if s not in TWO_WAY_ML_ORDER]
    return ordered + extra


def build_pairing(sides: list[dict]) -> tuple[list[dict], list[dict], list[list[str]]]:
    records = pair_records(sides)
    sports = two_way_sports(sides)
    summaries = []
    for sport in sports:
        summaries.append(pairing_summary(records, sides, sport, "moneyline"))
    soccer = [s for s in sports if "soccer" in s.lower()]
    if not soccer and any(str(r.get("sport") or "").lower() == "soccer" for r in sides):
        summaries.append(pairing_summary(records, sides, "soccer", "moneyline"))
    rows = pairing_rows(summaries)
    return records, summaries, rows


def main() -> int:
    _out("loading hist books")
    k_raw = decile_w.load_json_list(comb.HIST_DIR / "books_kalshi.json")
    p_raw = decile_w.load_json_list(comb.HIST_DIR / "books_poly.json")
    _out(f"raw kalshi={len(k_raw)} poly={len(p_raw)}")
    k_sides, k_stats = comb.attach_event_keys(k_raw)
    p_sides, p_stats = comb.attach_event_keys(p_raw)
    _out(f"valid kalshi={k_stats['n_ok']} poly={p_stats['n_ok']}")
    matched, leftover_k, leftover_p, match = comb.match_dual(k_sides, p_sides)
    _out(
        f"dual={match['n_dual']} k_only={match['n_kalshi_only']} p_only={match['n_poly_only']}"
    )
    selected, counts = comb.select_combined(matched, leftover_k, leftover_p)
    cheap = comb.pick_cheaper_yes(selected)
    both = comb.pick_named_yes(selected)
    _out(f"scoring cheap={len(cheap)} both={len(both)}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        cheap_fut = pool.submit(comb.score_sides, cheap, arm="Cheaper-Yes only (dogs)")
        both_fut = pool.submit(comb.score_sides, both, arm="Both named Yes (main)")
        cheap_tables = cheap_fut.result()
        both_tables = both_fut.result()
    arms = {
        "Cheaper-Yes only (dogs)": cheap_tables,
        "Both named Yes (main)": both_tables,
    }
    _out("pairing both-sides markets")
    _records, summaries, pair_row = build_pairing(both)
    cfb_sum = next((s for s in summaries if s.get("sport") == "college football"), {})
    cfb = dict(cfb_sum)
    cfb["cheap_n_09"] = count_deciles(cheap, "college football", "moneyline").get("0-9", 0)
    cfb["cheap_n_9099"] = count_deciles(cheap, "college football", "moneyline").get("90-99", 0)
    hidden_blurb = hidden_paragraph(cheap_tables, both_tables, cfb)
    sports = two_way_sports(both)
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    payload = {
        "counts": counts,
        "match": match,
        "k_stats": k_stats,
        "p_stats": p_stats,
        "cheap_tables": cheap_tables,
        "both_tables": both_tables,
        "arms": arms,
        "cfb": cfb,
        "pairing_rows": pair_row,
        "pairing_compact": summaries,
        "cfb_comp_rows": complement_rows(both, "college football", "moneyline"),
        "cfb_ml_both_rows": cfb_ml_both_rows(both_tables),
        "ml_comp_html": ml_comp_html(both, sports),
        "side_all_rows": side_by_side_rows(cheap_tables, both_tables, rollup_only=True),
        "side_cfb_rows": side_by_side_rows(cheap_tables, both_tables, sport="college football"),
        "hidden_rows": hidden_rows(cheap_tables, both_tables),
        "hidden_blurb": hidden_blurb,
    }
    path = write_html(payload, now=now)
    write_baseline(payload, now)
    dump_json(payload, path)
    link_parent_page()
    _out(
        f"wrote {path} cfb_ml 0-9={cfb.get('n_09')} 90-99={cfb.get('n_9099')} "
        f"gap={cfb.get('gap')} cheap_0-9={cfb.get('cheap_n_09')} "
        f"cheap_90-99={cfb.get('cheap_n_9099')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
