#!/usr/bin/env python3
"""System G paper: tennis dual-dip gap grid (band × D × T0 all-in door).

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not retune live A–E. Not gold. Not DailyRun.

Rule: at T0 tennis moneyline, both Yes in [lo, hi]; optional T0 all-in ≤ C door.
Independently, each side fills on first print ≤ T0 − D (optimistic fill at
exactly T0 − D when max_dip ≥ D). If both fill, hold Yes+Yes to settlement.
If one fills, hold that one. If none, sit out (PnL 0).

Fees = documented taker on the fill price (Kalshi / Gemini / Polymarket).
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP  # noqa: E402
from write_t0_band_from_stay_above import all_in_c, documented_leg_fee  # noqa: E402

ET = ZoneInfo("America/New_York")
DENSE = ROOT / "docs" / "prediction_market" / "dense_inplay_yes_dip_20261021.html"
KALSHI_SIDES = (
    LOCAL_STAMP / "hist" / "drop_from_t0_20261102" / "kalshi_sides.jsonl"
)
OUT_DIR = ROOT / "docs" / "prediction_market"
PAGE = OUT_DIR / "system_g_dual_dip_paper_20261102.html"
DETAIL_PAGE = OUT_DIR / "system_g_dual_dip_runs_20261102.html"
JSON_OUT = OUT_DIR / "system_g_dual_dip_paper_20261102.json"
CSV_OUT = OUT_DIR / "system_g_dual_dip_runs_20261102.csv"
STAMP_PAGE = STAMP / "system_g_dual_dip_paper_20261102.html"
STAMP_DETAIL = STAMP / "system_g_dual_dip_runs_20261102.html"
STAMP_JSON = STAMP / "system_g_dual_dip_paper_20261102.json"
STAMP_CSV = STAMP / "system_g_dual_dip_runs_20261102.csv"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_g_dual_dip_paper_20261102.html"
)
DETAIL_FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_g_dual_dip_runs_20261102.html"
)

BANDS = (
    ("20-79", 0.20, 0.79),
    ("25-74", 0.25, 0.74),
    ("30-69", 0.30, 0.69),
    ("40-59", 0.40, 0.59),
)
DIPS = (0.05, 0.10, 0.15, 0.20)
DOORS = (1.05, 1.10, 1.15)

ASKED = (
    "Paper System G: both Yes in band at T0; buy each on first ≤ T0−D; when both "
    "filled hold Yes+Yes. Also: when only one side fills, is it usually the "
    "underdog who loses, the favorite who loses, or a one-leg winner? Grid "
    "bands 20–79 / 25–74 / 30–69 / 40–59 × dips 5/10/15/20¢ × T0 all-in doors "
    "1.05 / 1.10 / 1.15. Want entry+fees profitable."
)


def esc(v) -> str:
    return html_mod.escape("" if v is None else str(v))


def fnum(x):
    s = str(x).strip().replace("$", "").replace("+", "").replace(",", "")
    if s in ("", "—", "-", "n/a", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) > 2}


def side_won(side_name: str, winner: str) -> bool | None:
    st = tokens(side_name)
    wt = tokens(winner)
    if not st or not wt:
        return None
    if st & wt:
        return True
    # last-name heuristic: last token of side in winner
    side_last = (side_name or "").strip().split()
    if side_last and side_last[-1].lower() in (winner or "").lower():
        return True
    return False


def fee_f(venue: str, px: float) -> float:
    fee = documented_leg_fee(venue, px)
    if fee is None:
        # fallback ~1¢ per leg so we never pretend zero fee
        return 0.01
    return float(fee)


def load_dense_pairs() -> list[dict]:
    if not DENSE.is_file():
        return []
    raw = DENSE.read_text(errors="replace")
    tables = re.findall(r"<table[^>]*>(.*?)</table>", raw, flags=re.I | re.S)
    if len(tables) < 6:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tables[5], flags=re.I | re.S)
    hdr = [
        re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", c))).strip()
        for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], flags=re.I | re.S)
    ]
    out = []
    for tr in rows[1:]:
        cells = [
            re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.I | re.S)
        ]
        d = dict(zip(hdr, cells))
        if (d.get("Still live?") or "").lower() == "yes":
            continue
        winner = d.get("Winner") or ""
        if not winner:
            continue
        ta, tb = fnum(d.get("T0 A")), fnum(d.get("T0 B"))
        da, db = fnum(d.get("Max dip A")), fnum(d.get("Max dip B"))
        name_a, name_b = d.get("Yes A") or "A", d.get("Yes B") or "B"
        if None in (ta, tb, da, db):
            continue
        if not (0.05 < ta < 0.95 and 0.05 < tb < 0.95):
            continue
        wa = side_won(name_a, winner)
        wb = side_won(name_b, winner)
        if wa is True and wb is True:
            continue
        if wa is False and wb is False:
            continue
        if wa is None and wb is None:
            continue
        if wa is True:
            a_won, b_won = True, False
        elif wb is True:
            a_won, b_won = False, True
        elif wa is False:
            a_won, b_won = False, True
        else:
            a_won, b_won = True, False
        venue = d.get("Venue") or "Polymarket"
        wire_c = fnum(d.get("C"))
        if wire_c is None:
            wire_c = ta + tb
        ain = all_in_c(venue, ta, tb)
        all_in = float(ain) if ain is not None else wire_c + fee_f(venue, ta) + fee_f(venue, tb)
        if ta >= tb:
            fav = {"name": name_a, "t0": ta, "dip": da, "won": a_won}
            dog = {"name": name_b, "t0": tb, "dip": db, "won": b_won}
        else:
            fav = {"name": name_b, "t0": tb, "dip": db, "won": b_won}
            dog = {"name": name_a, "t0": ta, "dip": da, "won": a_won}
        out.append({
            "book": "dense_live_tape",
            "match": d.get("Match") or "",
            "venue": venue,
            "wire_c": round(wire_c, 4),
            "all_in": round(all_in, 4),
            "fav": fav,
            "dog": dog,
        })
    return out


def load_kalshi_pairs() -> list[dict]:
    if not KALSHI_SIDES.is_file():
        return []
    bags: dict[str, list] = defaultdict(list)
    with KALSHI_SIDES.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not row.get("usable"):
                continue
            if row.get("sport") != "tennis" or row.get("kind") != "moneyline":
                continue
            if row.get("result") not in ("yes", "no"):
                continue
            et = row.get("event_ticker") or ""
            if not et:
                continue
            bags[et].append(row)
    out = []
    for et, ms in bags.items():
        if len(ms) < 2:
            continue
        ms = sorted(ms, key=lambda r: float(r["t0_px"]), reverse=True)
        a, b = ms[0], ms[1]
        ta, tb = float(a["t0_px"]), float(b["t0_px"])
        if abs(ta - tb) < 1e-9:
            continue
        if not (0.05 < ta < 0.95 and 0.05 < tb < 0.95):
            continue
        wire_c = ta + tb
        ain = all_in_c("Kalshi", ta, tb)
        all_in = float(ain) if ain is not None else wire_c + fee_f("Kalshi", ta) + fee_f("Kalshi", tb)
        out.append({
            "book": "kalshi_yes_ask",
            "match": et,
            "venue": "Kalshi",
            "wire_c": round(wire_c, 4),
            "all_in": round(all_in, 4),
            "fav": {
                "name": a.get("title") or "fav",
                "t0": ta,
                "dip": float(a["max_dip"]),
                "won": a.get("result") == "yes",
            },
            "dog": {
                "name": b.get("title") or "dog",
                "t0": tb,
                "dip": float(b["max_dip"]),
                "won": b.get("result") == "yes",
            },
        })
    return out


def in_band(pair: dict, lo: float, hi: float) -> bool:
    return lo - 1e-12 <= pair["fav"]["t0"] <= hi + 1e-12 and lo - 1e-12 <= pair["dog"]["t0"] <= hi + 1e-12


def simulate(pair: dict, dip: float) -> dict:
    venue = pair["venue"]
    fav, dog = pair["fav"], pair["dog"]
    fav_hit = float(fav["dip"]) + 1e-12 >= dip
    dog_hit = float(dog["dip"]) + 1e-12 >= dip
    fav_fill = round(float(fav["t0"]) - dip, 4) if fav_hit else None
    dog_fill = round(float(dog["t0"]) - dip, 4) if dog_hit else None
    if fav_fill is not None and fav_fill <= 0.005:
        fav_hit, fav_fill = False, None
    if dog_fill is not None and dog_fill <= 0.005:
        dog_hit, dog_fill = False, None

    if fav_hit and dog_hit:
        fee_a = fee_f(venue, fav_fill)
        fee_b = fee_f(venue, dog_fill)
        cost = fav_fill + dog_fill + fee_a + fee_b
        pnl = 1.0 - cost
        path = "both"
        one_class = None
    elif fav_hit:
        fee = fee_f(venue, fav_fill)
        cost = fav_fill + fee
        won = bool(fav["won"])
        pnl = (1.0 - cost) if won else (-cost)
        path = "one_fav"
        one_class = "fav_won" if won else "fav_lost"
    elif dog_hit:
        fee = fee_f(venue, dog_fill)
        cost = dog_fill + fee
        won = bool(dog["won"])
        pnl = (1.0 - cost) if won else (-cost)
        path = "one_dog"
        one_class = "dog_won" if won else "dog_lost"
    else:
        cost = 0.0
        pnl = 0.0
        path = "none"
        one_class = None

    return {
        "path": path,
        "one_class": one_class,
        "fav_hit": fav_hit,
        "dog_hit": dog_hit,
        "fav_fill": fav_fill,
        "dog_fill": dog_fill,
        "cost": round(cost, 4),
        "pnl": round(pnl, 4),
        "lock_profit": bool(path == "both" and cost < 1.0 - 1e-12),
        "fav_won": bool(fav["won"]),
        "dog_won": bool(dog["won"]),
    }


def summarize(sims: list[dict]) -> dict:
    n = len(sims)
    if n <= 0:
        return {"n": 0}
    by_path = defaultdict(list)
    by_one = defaultdict(list)
    for s in sims:
        by_path[s["path"]].append(s)
        if s["one_class"]:
            by_one[s["one_class"]].append(s)

    def bag_stats(bag: list[dict]) -> dict:
        if not bag:
            return {"n": 0, "pct": 0.0, "total_pnl": 0.0, "avg_pnl": None, "win_pct": None}
        pnls = [s["pnl"] for s in bag]
        wins = sum(1 for p in pnls if p > 0)
        return {
            "n": len(bag),
            "pct": round(100.0 * len(bag) / n, 1),
            "total_pnl": round(sum(pnls), 4),
            "avg_pnl": round(sum(pnls) / len(pnls), 4),
            "win_pct": round(100.0 * wins / len(pnls), 1),
        }

    both = by_path["both"]
    lock_ok = [s for s in both if s.get("lock_profit")]
    lock_bad = [s for s in both if not s.get("lock_profit")]
    one = by_path["one_fav"] + by_path["one_dog"]
    all_pnls = [s["pnl"] for s in sims]
    traded = [s for s in sims if s["path"] != "none"]
    # Counterfactual: only take the trade when BOTH legs fill; one-leg = sit out.
    both_only_pnls = [s["pnl"] if s["path"] == "both" else 0.0 for s in sims]

    return {
        "n": n,
        "n_traded": len(traded),
        "total_pnl": round(sum(all_pnls), 4),
        "avg_pnl_all": round(sum(all_pnls) / n, 4),
        "avg_pnl_traded": (
            round(sum(s["pnl"] for s in traded) / len(traded), 4) if traded else None
        ),
        "both_only_total_pnl": round(sum(both_only_pnls), 4),
        "both_only_avg_pnl": round(sum(both_only_pnls) / n, 4),
        "paths": {
            "both": bag_stats(both),
            "one": bag_stats(one),
            "none": bag_stats(by_path["none"]),
            "one_fav": bag_stats(by_path["one_fav"]),
            "one_dog": bag_stats(by_path["one_dog"]),
        },
        "one_class": {
            "fav_won": bag_stats(by_one["fav_won"]),
            "fav_lost": bag_stats(by_one["fav_lost"]),
            "dog_won": bag_stats(by_one["dog_won"]),
            "dog_lost": bag_stats(by_one["dog_lost"]),
        },
        "both_lock_profit": bag_stats(lock_ok),
        "both_lock_unprofitable_fees": bag_stats(lock_bad),
        "mean_both_cost": (
            round(sum(s["cost"] for s in both) / len(both), 4) if both else None
        ),
    }


def detail_row(book_name: str, band_name: str, lo: float, hi: float, door: float, dip: float, pair: dict, sim: dict) -> dict:
    fav, dog = pair["fav"], pair["dog"]
    return {
        "book": book_name,
        "band": band_name,
        "lo": lo,
        "hi": hi,
        "door": door,
        "dip": dip,
        "match": pair.get("match") or "",
        "venue": pair.get("venue") or "",
        "wire_c": pair.get("wire_c"),
        "all_in": pair.get("all_in"),
        "fav": fav.get("name"),
        "dog": dog.get("name"),
        "t0_fav": fav.get("t0"),
        "t0_dog": dog.get("t0"),
        "dip_fav": fav.get("dip"),
        "dip_dog": dog.get("dip"),
        "fav_won": fav.get("won"),
        "dog_won": dog.get("won"),
        "fav_hit": sim.get("fav_hit"),
        "dog_hit": sim.get("dog_hit"),
        "fav_fill": sim.get("fav_fill"),
        "dog_fill": sim.get("dog_fill"),
        "path": sim.get("path"),
        "one_class": sim.get("one_class"),
        "cost": sim.get("cost"),
        "pnl": sim.get("pnl"),
        "both_only_pnl": sim.get("pnl") if sim.get("path") == "both" else 0.0,
        "lock_profit": sim.get("lock_profit"),
    }


def run_grid(pairs: list[dict], book_name: str) -> tuple[list[dict], list[dict]]:
    grid = []
    details: list[dict] = []
    for band_name, lo, hi in BANDS:
        banded = [p for p in pairs if in_band(p, lo, hi)]
        for door in DOORS:
            door_pairs = [p for p in banded if float(p["all_in"]) <= door + 1e-12]
            for dip in DIPS:
                sims = []
                for pair in door_pairs:
                    sim = simulate(pair, dip)
                    sims.append(sim)
                    details.append(
                        detail_row(book_name, band_name, lo, hi, door, dip, pair, sim)
                    )
                grid.append({
                    "band": band_name,
                    "lo": lo,
                    "hi": hi,
                    "door": door,
                    "dip": dip,
                    "n_band": len(banded),
                    "n_door": len(door_pairs),
                    **summarize(sims),
                })
    return grid, details


def fmt_money(x) -> str:
    if x is None:
        return "—"
    n = float(x)
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):.2f}"


def fmt_pct(x) -> str:
    if x is None:
        return "—"
    return f"{float(x):.1f}%"


def sketch_cell(grid: list[dict]) -> dict | None:
    return next(
        (
            r for r in grid
            if r["band"] == "25-74"
            and abs(r["dip"] - 0.10) < 1e-9
            and abs(r["door"] - 1.05) < 1e-9
        ),
        None,
    )


def html_report(payload: dict) -> str:
    books = payload.get("books") or {}
    dense_book = books.get("A_dense_live_tape") or {}
    sketch = sketch_cell(dense_book.get("grid") or []) or {}
    sk_paths = sketch.get("paths") or {}
    sk_one = sketch.get("one_class") or {}
    answer_html = ""
    if sketch.get("n"):
        answer_html = f"""
<div class="note card">
<p><strong>Answer — one-leg side:</strong> When only one leg fills, it is almost
always the <em>eventual loser</em>. Sketch cell 25–74 / −10¢ / all-in≤1.05 on dense
tape (N={sketch.get('n')}): one-leg {sk_paths.get('one', {}).get('pct')}% of matches —
<strong>only-dog-lost {sk_one.get('dog_lost', {}).get('pct')}%</strong>
(P&amp;L {fmt_money(sk_one.get('dog_lost', {}).get('total_pnl'))}) and
<strong>only-fav-lost {sk_one.get('fav_lost', {}).get('pct')}%</strong>
(P&amp;L {fmt_money(sk_one.get('fav_lost', {}).get('total_pnl'))}).
Lone winners are rare: only-dog-won {sk_one.get('dog_won', {}).get('pct')}%,
only-fav-won {sk_one.get('fav_won', {}).get('pct')}%.</p>
<p><strong>Answer — P&amp;L:</strong> As-stated total {fmt_money(sketch.get('total_pnl'))}
(avg {fmt_money(sketch.get('avg_pnl_all'))}/match) — red. Both-fill avg
{fmt_money(sk_paths.get('both', {}).get('avg_pnl'))} on
{sk_paths.get('both', {}).get('pct')}% of matches, but one-leg avg
{fmt_money(sk_paths.get('one', {}).get('avg_pnl'))} wipes it.
<strong>Both-only</strong> counterfactual (sit out unless both legs fill):
total {fmt_money(sketch.get('both_only_total_pnl'))}, avg
{fmt_money(sketch.get('both_only_avg_pnl'))}/match. That is the sleeve to paper next.</p>
</div>
"""
    sections = []
    for book_name, book in books.items():
        grid = book.get("grid") or []
        # headline cells: door 1.05 × each band × dip
        focus = [r for r in grid if abs(float(r["door"]) - 1.05) < 1e-9]
        rows = []
        for r in focus:
            paths = r.get("paths") or {}
            one = r.get("one_class") or {}
            rows.append(
                "<tr>"
                f"<td>{esc(r['band'])}</td>"
                f"<td class='num'>{int(r['dip']*100)}¢</td>"
                f"<td class='num'>{r.get('n')}</td>"
                f"<td class='num'>{fmt_money(r.get('total_pnl'))}</td>"
                f"<td class='num'>{fmt_money(r.get('avg_pnl_all'))}</td>"
                f"<td class='num'>{fmt_money(r.get('both_only_total_pnl'))}</td>"
                f"<td class='num'>{fmt_money(r.get('both_only_avg_pnl'))}</td>"
                f"<td class='num'>{(paths.get('both') or {}).get('pct', 0)}</td>"
                f"<td class='num'>{fmt_money((paths.get('both') or {}).get('avg_pnl'))}</td>"
                f"<td class='num'>{(paths.get('one') or {}).get('pct', 0)}</td>"
                f"<td class='num'>{fmt_money((paths.get('one') or {}).get('avg_pnl'))}</td>"
                f"<td class='num'>{(paths.get('none') or {}).get('pct', 0)}</td>"
                f"<td class='num'>{(one.get('dog_lost') or {}).get('pct', 0)}</td>"
                f"<td class='num'>{(one.get('fav_lost') or {}).get('pct', 0)}</td>"
                f"<td class='num'>{(one.get('dog_won') or {}).get('pct', 0)}</td>"
                f"<td class='num'>{(one.get('fav_won') or {}).get('pct', 0)}</td>"
                f"<td class='num'>{(r.get('both_lock_profit') or {}).get('pct', 0)}</td>"
                "</tr>"
            )

        # full grid table
        full = []
        for r in grid:
            paths = r.get("paths") or {}
            one = r.get("one_class") or {}
            full.append(
                "<tr>"
                f"<td>{esc(r['band'])}</td>"
                f"<td class='num'>{r['door']:.2f}</td>"
                f"<td class='num'>{int(r['dip']*100)}¢</td>"
                f"<td class='num'>{r.get('n')}</td>"
                f"<td class='num'>{fmt_money(r.get('total_pnl'))}</td>"
                f"<td class='num'>{fmt_money(r.get('avg_pnl_all'))}</td>"
                f"<td class='num'>{fmt_money(r.get('avg_pnl_traded'))}</td>"
                f"<td class='num'>{(paths.get('both') or {}).get('n', 0)} ({(paths.get('both') or {}).get('pct', 0)}%)</td>"
                f"<td class='num'>{fmt_money((paths.get('both') or {}).get('total_pnl'))}</td>"
                f"<td class='num'>{fmt_money(r.get('mean_both_cost'))}</td>"
                f"<td class='num'>{(r.get('both_lock_profit') or {}).get('n', 0)}</td>"
                f"<td class='num'>{(paths.get('one') or {}).get('n', 0)} ({(paths.get('one') or {}).get('pct', 0)}%)</td>"
                f"<td class='num'>{fmt_money((paths.get('one') or {}).get('total_pnl'))}</td>"
                f"<td class='num'>{(one.get('dog_lost') or {}).get('n', 0)}</td>"
                f"<td class='num'>{fmt_money((one.get('dog_lost') or {}).get('total_pnl'))}</td>"
                f"<td class='num'>{(one.get('fav_lost') or {}).get('n', 0)}</td>"
                f"<td class='num'>{fmt_money((one.get('fav_lost') or {}).get('total_pnl'))}</td>"
                f"<td class='num'>{(one.get('dog_won') or {}).get('n', 0)}</td>"
                f"<td class='num'>{fmt_money((one.get('dog_won') or {}).get('total_pnl'))}</td>"
                f"<td class='num'>{(one.get('fav_won') or {}).get('n', 0)}</td>"
                f"<td class='num'>{fmt_money((one.get('fav_won') or {}).get('total_pnl'))}</td>"
                f"<td class='num'>{(paths.get('none') or {}).get('pct', 0)}</td>"
                "</tr>"
            )

        one_note = book.get("one_leg_note") or ""
        sections.append(f"""
<h2>Book: {esc(book_name)} (N pairs={book.get('n_pairs')})</h2>
<p class="note">{esc(one_note)}</p>
<h3>Focus — T0 all-in door ≤ 1.05</h3>
<p class="muted">% columns are share of door-qualified matches. One-leg class % also of door-qualified matches.</p>
<div class="swipe"><table class="sortable">
<thead><tr>
<th>Band</th><th class="num">Dip</th><th class="num">N</th>
<th class="num">As-stated total</th><th class="num">As-stated avg</th>
<th class="num">Both-only total</th><th class="num">Both-only avg</th>
<th class="num">Both%</th><th class="num">Both avg $</th>
<th class="num">One%</th><th class="num">One avg $</th>
<th class="num">None%</th>
<th class="num">Only dog lost%</th><th class="num">Only fav lost%</th>
<th class="num">Only dog won%</th><th class="num">Only fav won%</th>
<th class="num">Both lock&lt;$1%</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody></table></div>

<h3>Full grid — every door × dip</h3>
<div class="swipe"><table class="sortable">
<thead><tr>
<th>Band</th><th class="num">Door</th><th class="num">Dip</th><th class="num">N</th>
<th class="num">Total P&amp;L</th><th class="num">Avg all</th><th class="num">Avg traded</th>
<th class="num">Both N (%)</th><th class="num">Both $</th><th class="num">Mean both cost</th>
<th class="num">Both cost&lt;$1</th>
<th class="num">One N (%)</th><th class="num">One $</th>
<th class="num">Dog lost N</th><th class="num">Dog lost $</th>
<th class="num">Fav lost N</th><th class="num">Fav lost $</th>
<th class="num">Dog won N</th><th class="num">Dog won $</th>
<th class="num">Fav won N</th><th class="num">Fav won $</th>
<th class="num">None%</th>
</tr></thead>
<tbody>
{''.join(full)}
</tbody></table></div>
""")

    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>System G paper — tennis dual-dip gap (2 Nov 2026)</title>
<style>
body {{ font-family: Georgia, 'Times New Roman', serif; margin: 1.5rem; color: #1a1a1a; background: #f7f4ef; }}
h1,h2,h3 {{ font-family: 'Segoe UI', system-ui, sans-serif; }}
.muted {{ color: #555; }}
.note {{ max-width: 56rem; line-height: 1.45; }}
.card {{ background:#fff; border:1px solid #d8d0c2; border-radius:6px; padding:0.9rem 1.1rem; max-width:56rem; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.82rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.3rem 0.4rem; }}
th {{ background: #ebe4d8; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.swipe {{ overflow-x: auto; margin-bottom: 1.2rem; }}
</style>
{report_page_extras.SORTABLE_TH_CSS}
</head>
<body>
<h1>System G paper — tennis dual-dip gap</h1>
<p class="muted">Written {esc(now)}. Research only. Not gold. Not DailyRun. Did not place orders. Did not retune live A–E.</p>
<div class="note card">
<p><strong>Asked:</strong> {esc(ASKED)}</p>
<p><strong>Mechanics:</strong> Optimistic fill at exactly T0−D when that side’s max dip
≥ D. Documented taker fee on each fill. Both-fill payout is always $1 (one side
wins). One-fill is directional. None = sit out at $0. T0 door uses all-in
(asks + documented fees). Band = both Yes T0 inside the cent range.</p>
</div>
{answer_html}
<div class="note card">
<p><strong>One-leg reading key:</strong> “Only dog lost” = bought only the
underdog and that underdog lost. “Only fav lost” = bought only the favorite and
the favorite lost. “Only dog/fav won” = left with a single winning ticket.
Percents are of door-qualified matches. <em>Both-only</em> = pretend one-leg
never entered (upper bound if you can require both fills).</p>
</div>
{''.join(sections)}
<p class="note">Per-match runs (every band × door × dip):
<a href="system_g_dual_dip_runs_20261102.html">system_g_dual_dip_runs_20261102.html</a>
· <a href="system_g_dual_dip_runs_20261102.csv">CSV</a>
· <a href="https://docs.google.com/spreadsheets/d/12MM3mix29etK2i2E3NEHn8LAWKXPs9iEr0O_cL2DqVA/edit">Sheet — sketch 25–74 / 10¢ / C1.05</a>
· <a href="https://docs.google.com/spreadsheets/d/165vZ-6EjkVbeb0beqlPF0nAk0VV7d9hXOamGT5-YfZg/edit">Sheet — dense door 1.05 all bands×dips</a>
· <a href="{esc(DETAIL_FILE_URL)}">{esc(DETAIL_FILE_URL)}</a></p>
<p class="muted">Summary file: <a href="{esc(FILE_URL)}">{esc(FILE_URL)}</a></p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def write_csv(details: list[dict], path: Path) -> None:
    if not details:
        return
    fields = list(details[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in details:
            w.writerow(row)


def detail_html(details: list[dict], written_at: str) -> str:
    """Browsable per-match runs. Default filter = sketch cell on dense tape."""
    # Keep page usable: embed all rows as JSON, render filtered table in JS.
    slim = []
    for d in details:
        slim.append({
            "book": d["book"],
            "band": d["band"],
            "door": d["door"],
            "dip": d["dip"],
            "match": d["match"],
            "venue": d["venue"],
            "all_in": d["all_in"],
            "fav": d["fav"],
            "dog": d["dog"],
            "t0_fav": d["t0_fav"],
            "t0_dog": d["t0_dog"],
            "dip_fav": d["dip_fav"],
            "dip_dog": d["dip_dog"],
            "fav_won": d["fav_won"],
            "dog_won": d["dog_won"],
            "fav_hit": d["fav_hit"],
            "dog_hit": d["dog_hit"],
            "fav_fill": d["fav_fill"],
            "dog_fill": d["dog_fill"],
            "path": d["path"],
            "one_class": d["one_class"],
            "cost": d["cost"],
            "pnl": d["pnl"],
            "both_only_pnl": d["both_only_pnl"],
        })
    payload = json.dumps(slim, separators=(",", ":"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>System G — per-match runs (2 Nov 2026)</title>
<style>
body {{ font-family: Georgia, 'Times New Roman', serif; margin: 1.25rem; color: #1a1a1a; background: #f7f4ef; }}
h1,h2 {{ font-family: 'Segoe UI', system-ui, sans-serif; }}
.muted {{ color: #555; }}
.controls {{ display:flex; flex-wrap:wrap; gap:0.6rem; align-items:end; margin:0.8rem 0 1rem; }}
.controls label {{ font-size:0.85rem; display:flex; flex-direction:column; gap:0.2rem; }}
.controls select, .controls button {{ font-size:0.95rem; padding:0.35rem 0.5rem; }}
.card {{ background:#fff; border:1px solid #d8d0c2; border-radius:6px; padding:0.75rem 1rem; max-width:56rem; }}
table {{ border-collapse:collapse; width:100%; background:#fff; font-size:0.8rem; }}
th, td {{ border:1px solid #ccc; padding:0.28rem 0.4rem; }}
th {{ background:#ebe4d8; position:sticky; top:0; }}
td.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
.swipe {{ overflow:auto; max-height:calc(100vh - 14rem); }}
.pos {{ color:#1b5e20; }}
.neg {{ color:#8a1f1f; }}
.stats {{ margin:0.5rem 0 0.8rem; }}
</style>
</head>
<body>
<h1>System G — every match run</h1>
<p class="muted">Written {esc(written_at)}. One row = one match under one band × door × dip.
Optimistic fill at T0−D + documented taker fee. Research only.</p>
<div class="card">
<p>Default view is the sketch cell: dense tape, band 25–74, door 1.05, dip 10¢.
Change filters to inspect any other combo. Full dump also in
<a href="system_g_dual_dip_runs_20261102.csv">system_g_dual_dip_runs_20261102.csv</a>.
Sheets:
<a href="https://docs.google.com/spreadsheets/d/12MM3mix29etK2i2E3NEHn8LAWKXPs9iEr0O_cL2DqVA/edit">sketch cell (80 matches)</a>
·
<a href="https://docs.google.com/spreadsheets/d/165vZ-6EjkVbeb0beqlPF0nAk0VV7d9hXOamGT5-YfZg/edit">dense door 1.05 (1080 rows)</a>.</p>
</div>
<div class="controls">
  <label>Book
    <select id="book">
      <option value="A_dense_live_tape">A_dense_live_tape</option>
      <option value="B_kalshi_yes_ask">B_kalshi_yes_ask</option>
      <option value="ALL">ALL</option>
    </select>
  </label>
  <label>Band
    <select id="band">
      <option>20-79</option>
      <option selected>25-74</option>
      <option>30-69</option>
      <option>40-59</option>
      <option>ALL</option>
    </select>
  </label>
  <label>Door
    <select id="door">
      <option selected>1.05</option>
      <option>1.1</option>
      <option>1.15</option>
      <option>ALL</option>
    </select>
  </label>
  <label>Dip
    <select id="dip">
      <option value="0.05">5¢</option>
      <option value="0.1" selected>10¢</option>
      <option value="0.15">15¢</option>
      <option value="0.2">20¢</option>
      <option value="ALL">ALL</option>
    </select>
  </label>
  <label>Path
    <select id="path">
      <option value="ALL" selected>ALL</option>
      <option value="both">both</option>
      <option value="one_fav">one_fav</option>
      <option value="one_dog">one_dog</option>
      <option value="none">none</option>
    </select>
  </label>
  <button type="button" id="apply">Show runs</button>
</div>
<div class="stats muted" id="stats"></div>
<div class="swipe">
<table>
<thead><tr>
<th>Match</th><th>Venue</th><th>All-in</th>
<th>Fav</th><th>T0 fav</th><th>Dip fav</th><th>Fill fav</th><th>Fav won?</th>
<th>Dog</th><th>T0 dog</th><th>Dip dog</th><th>Fill dog</th><th>Dog won?</th>
<th>Path</th><th>One class</th><th>Cost</th><th>P&amp;L</th><th>Both-only P&amp;L</th>
</tr></thead>
<tbody id="tbody"></tbody>
</table>
</div>
<script>
const ROWS = {payload};
function money(x) {{
  if (x === null || x === undefined) return "—";
  const n = Number(x);
  const s = (n < 0 ? "-" : "") + "$" + Math.abs(n).toFixed(4);
  return s;
}}
function px(x) {{
  if (x === null || x === undefined) return "—";
  return (100 * Number(x)).toFixed(1) + "¢";
}}
function yn(x) {{
  if (x === true) return "yes";
  if (x === false) return "no";
  return "—";
}}
function apply() {{
  const book = document.getElementById("book").value;
  const band = document.getElementById("band").value;
  const door = document.getElementById("door").value;
  const dip = document.getElementById("dip").value;
  const path = document.getElementById("path").value;
  const out = ROWS.filter(r => {{
    if (book !== "ALL" && r.book !== book) return false;
    if (band !== "ALL" && r.band !== band) return false;
    if (door !== "ALL" && Math.abs(Number(r.door) - Number(door)) > 1e-9) return false;
    if (dip !== "ALL" && Math.abs(Number(r.dip) - Number(dip)) > 1e-9) return false;
    if (path !== "ALL" && r.path !== path) return false;
    return true;
  }});
  const tb = document.getElementById("tbody");
  tb.innerHTML = "";
  let sum = 0, bothOnly = 0;
  for (const r of out) {{
    sum += Number(r.pnl || 0);
    bothOnly += Number(r.both_only_pnl || 0);
    const tr = document.createElement("tr");
    const pnlCls = Number(r.pnl) > 0 ? "pos" : (Number(r.pnl) < 0 ? "neg" : "");
    const boCls = Number(r.both_only_pnl) > 0 ? "pos" : (Number(r.both_only_pnl) < 0 ? "neg" : "");
    tr.innerHTML = `
      <td>${{r.match}}</td><td>${{r.venue}}</td><td class="num">${{Number(r.all_in).toFixed(3)}}</td>
      <td>${{r.fav}}</td><td class="num">${{px(r.t0_fav)}}</td><td class="num">${{px(r.dip_fav)}}</td>
      <td class="num">${{r.fav_fill == null ? "—" : px(r.fav_fill)}}</td><td>${{yn(r.fav_won)}}</td>
      <td>${{r.dog}}</td><td class="num">${{px(r.t0_dog)}}</td><td class="num">${{px(r.dip_dog)}}</td>
      <td class="num">${{r.dog_fill == null ? "—" : px(r.dog_fill)}}</td><td>${{yn(r.dog_won)}}</td>
      <td>${{r.path}}</td><td>${{r.one_class || "—"}}</td>
      <td class="num">${{money(r.cost)}}</td>
      <td class="num ${{pnlCls}}">${{money(r.pnl)}}</td>
      <td class="num ${{boCls}}">${{money(r.both_only_pnl)}}</td>`;
    tb.appendChild(tr);
  }}
  document.getElementById("stats").textContent =
    `Showing ${{out.length}} runs · as-stated total ${{money(sum)}} · both-only total ${{money(bothOnly)}}`;
}}
document.getElementById("apply").addEventListener("click", apply);
apply();
</script>
</body>
</html>
"""


def one_leg_blurb(grid: list[dict]) -> str:
    """Summarize one-leg mix at the sketch cell: 25-74 / D=10 / door 1.05."""
    hit = sketch_cell(grid)
    if not hit or not hit.get("n"):
        return "Sketch cell 25–74 / 10¢ / C≤1.05 had no door-qualified pairs on this book."
    one = hit.get("one_class") or {}
    paths = hit.get("paths") or {}
    return (
        f"Sketch cell 25–74 / −10¢ / all-in≤1.05 (N={hit['n']}): "
        f"both {paths.get('both', {}).get('pct')}%, "
        f"one {paths.get('one', {}).get('pct')}%, "
        f"none {paths.get('none', {}).get('pct')}%. "
        f"Only-dog-lost {one.get('dog_lost', {}).get('pct')}% "
        f"({one.get('dog_lost', {}).get('total_pnl')}), "
        f"only-fav-lost {one.get('fav_lost', {}).get('pct')}%, "
        f"only-dog-won {one.get('dog_won', {}).get('pct')}%, "
        f"only-fav-won {one.get('fav_won', {}).get('pct')}%. "
        f"As-stated total {hit.get('total_pnl')} (avg {hit.get('avg_pnl_all')}). "
        f"Both-only total {hit.get('both_only_total_pnl')} "
        f"(avg {hit.get('both_only_avg_pnl')})."
    )


def main() -> None:
    dense = load_dense_pairs()
    kalshi = load_kalshi_pairs()
    print(f"dense pairs {len(dense)}; kalshi pairs {len(kalshi)}", flush=True)

    books = {}
    all_details: list[dict] = []
    if dense:
        g, details = run_grid(dense, "A_dense_live_tape")
        all_details.extend(details)
        books["A_dense_live_tape"] = {
            "n_pairs": len(dense),
            "grid": g,
            "one_leg_note": one_leg_blurb(g),
            "n_detail_rows": len(details),
        }
    if kalshi:
        g, details = run_grid(kalshi, "B_kalshi_yes_ask")
        all_details.extend(details)
        books["B_kalshi_yes_ask"] = {
            "n_pairs": len(kalshi),
            "grid": g,
            "one_leg_note": one_leg_blurb(g),
            "n_detail_rows": len(details),
        }

    written_at = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")
    payload = {
        "written_at_et": written_at,
        "asked": ASKED,
        "assumption": (
            "Optimistic fill at T0−D; documented taker fee on fill; no queue; "
            "no partial size. Sit-out PnL=0. Both-fill always receives $1."
        ),
        "books": books,
        "detail_csv": str(CSV_OUT.name),
        "detail_html": str(DETAIL_PAGE.name),
        "n_detail_rows": len(all_details),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PAGE.write_text(html_report(payload), encoding="utf-8")
    write_csv(all_details, CSV_OUT)
    DETAIL_PAGE.write_text(detail_html(all_details, written_at), encoding="utf-8")
    try:
        STAMP.mkdir(parents=True, exist_ok=True)
        STAMP_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        STAMP_PAGE.write_text(html_report(payload), encoding="utf-8")
        write_csv(all_details, STAMP_CSV)
        STAMP_DETAIL.write_text(detail_html(all_details, written_at), encoding="utf-8")
    except OSError:
        pass
    print(f"wrote {PAGE}", flush=True)
    print(f"wrote {DETAIL_PAGE}", flush=True)
    print(f"wrote {CSV_OUT} rows={len(all_details)}", flush=True)
    print(f"wrote {JSON_OUT}", flush=True)
    for name, book in books.items():
        print(name, book.get("one_leg_note"), flush=True)


if __name__ == "__main__":
    main()
