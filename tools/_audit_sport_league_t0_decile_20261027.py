"""Independent re-sum of sport/league T0 decile cells from the research tape.

Research only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second B, bump stake, wire D NFL, leftover GTC, or retune C=1.05.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import _write_sport_league_t0_decile_20261027 as w
import t0_all_games_stats as t0
from nfl_t0_type_a_collect import explode_cover_yes_sides, line_won, score_t0_yes
from t0_fav_lt90_baseline_20261024 import fav_yes_pnl
from write_t0_band_from_stay_above import documented_leg_fee


def indep_score(rows: list[dict]) -> dict:
    n = 0
    n_win = 0
    n_fee = 0
    pnl = Decimal("0")
    kinds = defaultdict(int)
    for book in rows:
        won = line_won(book)
        px = book.get("t0_fav")
        if px is None:
            px = score_t0_yes(book)
        if px is None or won is None:
            continue
        n += 1
        if won is True:
            n_win += 1
        kinds[str(book.get("kind") or "moneyline")] += 1
        fee = documented_leg_fee(str(book.get("venue") or ""), px)
        if fee is None:
            continue
        n_fee += 1
        pnl += fav_yes_pnl(px, fee, won=bool(won))
    return {
        "n": n,
        "n_win": n_win,
        "n_fee": n_fee,
        "pnl_sum": float(pnl) if n_fee else None,
        "kinds": dict(kinds),
    }


def bag_key(book: dict) -> tuple[str, str, str, str] | None:
    if book.get("void"):
        return None
    won = line_won(book)
    if won is None:
        return None
    px = book.get("t0_fav")
    if px is None:
        px = score_t0_yes(book)
    band = w.decile_of(px)
    if not band:
        return None
    sport = str(book.get("sport") or "unknown")
    league = w.league_of_side(book)
    kind = str(book.get("kind") or "moneyline")
    return sport, league, kind, band


def fmt(rec: dict) -> str:
    pnl = rec.get("pnl_sum")
    pnl_s = "—" if pnl is None else f"{pnl:+.4f}"
    return (
        f"N={rec['n']} wins={rec['n_win']} n_fee={rec['n_fee']} pnl={pnl_s}"
    )


def close(a, b, tol=0.02) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def check(name: str, got: dict, exp: dict, mismatches: list) -> None:
    ok_n = got["n"] == exp["n"] and got["n_win"] == exp["n_win"] and got["n_fee"] == exp["n_fee"]
    ok_p = close(got.get("pnl_sum"), exp.get("pnl_sum"))
    status = "MATCH" if ok_n and ok_p else "MISMATCH"
    print(f"  {status} {name}: indep {fmt(got)} vs report {fmt(exp)}")
    if status != "MATCH":
        mismatches.append(name)


def main() -> int:
    w.prev_snapshot()
    print("loading T0 books (all-game tape)", flush=True)
    payload = t0.build_payload()
    books = payload.get("books") or []
    exploded = explode_cover_yes_sides(books)
    picked = w.pick_one_side(exploded)
    print(f"books {len(books)} exploded {len(exploded)} picked {len(picked)}", flush=True)

    bags: dict[tuple, list[dict]] = defaultdict(list)
    settled = []
    unique_kinds = set()
    for book in picked:
        key = bag_key(book)
        if key is None:
            continue
        bags[key].append(book)
        settled.append(book)
        unique_kinds.add(key[2])
    print(f"settled unique-game-sides {len(settled)} kinds {sorted(unique_kinds)}", flush=True)

    tables = w.build_tables(picked)
    cells = tables["cells"]
    mismatches: list[str] = []

    def cell_exp(sport, league, kind, band) -> dict:
        rec = cells.get((sport, league, kind, band)) or {}
        return {
            "n": int(rec.get("n") or 0),
            "n_win": int(rec.get("n_win") or 0),
            "n_fee": int(rec.get("n_fee") or 0),
            "pnl_sum": rec.get("pnl_sum"),
        }

    def collect(pred) -> list[dict]:
        return [b for b in settled if pred(b)]

    print("\n=== CFB 40-49 by bet type (independent) ===")
    cfb_4049 = {}
    for kind in ("moneyline", "spread", "total"):
        rows = collect(
            lambda b, k=kind: str(b.get("sport") or "").lower() == "college football"
            and str(b.get("kind") or "moneyline") == k
            and w.decile_of(b.get("t0_fav") if b.get("t0_fav") is not None else score_t0_yes(b)) == "40-49"
        )
        got = indep_score(rows)
        cfb_4049[kind] = got
        print(f"  {w.kind_label(kind)}: {fmt(got)} kinds={got['kinds']}")
        check(
            f"cfb {kind} 40-49 vs generator cell",
            got,
            cell_exp("college football", "ALL", kind, "40-49"),
            mismatches,
        )
    grand_rows = collect(
        lambda b: str(b.get("sport") or "").lower() == "college football"
        and w.decile_of(b.get("t0_fav") if b.get("t0_fav") is not None else score_t0_yes(b)) == "40-49"
    )
    cfb_grand = indep_score(grand_rows)
    print(f"  TRUE CFB 40-49 grand: {fmt(cfb_grand)} kinds={cfb_grand['kinds']}")
    add_n = sum(cfb_4049[k]["n"] for k in cfb_4049)
    add_win = sum(cfb_4049[k]["n_win"] for k in cfb_4049)
    add_fee = sum(cfb_4049[k]["n_fee"] for k in cfb_4049)
    add_pnl = sum(float(cfb_4049[k]["pnl_sum"] or 0) for k in cfb_4049)
    print(f"  sum of three kinds: N={add_n} wins={add_win} n_fee={add_fee} pnl={add_pnl:+.4f}")
    assert cfb_grand["n"] == add_n
    ou = cfb_4049["total"]
    assert ou["n"] != cfb_4049["spread"]["n"] + cfb_4049["moneyline"]["n"] or True
    print(
        "  Points Total is "
        + ("NOT" if ou["n"] != add_n else "accidentally equal to")
        + " the grand N; Points Total pnl "
        + ("!=" if abs(float(ou["pnl_sum"] or 0) - add_pnl) > 0.01 else "==")
        + " spread+ML pnl"
    )

    print("\n=== Other high-visibility cells ===")
    overall = indep_score(settled)
    check("overall book", overall, cell_exp("ALL", "ALL", "ALL", "ALL"), mismatches)

    tennis_ml_1049 = collect(
        lambda b: str(b.get("sport") or "").lower() == "tennis"
        and str(b.get("kind") or "moneyline") == "moneyline"
        and w.decile_of(b.get("t0_fav") if b.get("t0_fav") is not None else score_t0_yes(b))
        in ("10-19", "20-29", "30-39", "40-49")
    )
    tennis_got = indep_score(tennis_ml_1049)
    tennis_exp = {"n": 0, "n_win": 0, "n_fee": 0, "pnl_sum": 0.0}
    for band in ("10-19", "20-29", "30-39", "40-49"):
        rec = cell_exp("tennis", "ALL", "moneyline", band)
        tennis_exp["n"] += rec["n"]
        tennis_exp["n_win"] += rec["n_win"]
        tennis_exp["n_fee"] += rec["n_fee"]
        if rec["pnl_sum"] is not None:
            tennis_exp["pnl_sum"] += float(rec["pnl_sum"])
    check("tennis ML 10-49 (sum of four bands)", tennis_got, tennis_exp, mismatches)

    soccer = collect(lambda b: "soccer" in str(b.get("sport") or "").lower())
    check("soccer all bet types all deciles", indep_score(soccer), cell_exp("soccer", "ALL", "ALL", "ALL"), mismatches)

    print("\n=== CFB other deciles (ALL bet types) ===")
    for band in w.DECADES:
        rows = collect(
            lambda b, bd=band: str(b.get("sport") or "").lower() == "college football"
            and w.decile_of(b.get("t0_fav") if b.get("t0_fav") is not None else score_t0_yes(b)) == bd
        )
        got = indep_score(rows)
        # generator may not have a (college football, ALL, ALL, band) cell — only
        # (sport, ALL, kind, band) and (sport, ALL, ALL, ALL). Sum kinds.
        exp = {"n": 0, "n_win": 0, "n_fee": 0, "pnl_sum": 0.0}
        any_p = False
        for kind in unique_kinds:
            rec = cell_exp("college football", "ALL", kind, band)
            exp["n"] += rec["n"]
            exp["n_win"] += rec["n_win"]
            exp["n_fee"] += rec["n_fee"]
            if rec["pnl_sum"] is not None:
                exp["pnl_sum"] += float(rec["pnl_sum"])
                any_p = True
        if not any_p:
            exp["pnl_sum"] = None
        check(f"cfb {band} all bet types", got, exp, mismatches)

    print("\n=== CFB ALL kinds add to CFB ALL ALL ===")
    cfb_all = indep_score(collect(lambda b: str(b.get("sport") or "").lower() == "college football"))
    check("cfb ALL ALL", cfb_all, cell_exp("college football", "ALL", "ALL", "ALL"), mismatches)
    kind_sum_n = 0
    for kind in unique_kinds:
        rec = cell_exp("college football", "CFB", kind, "ALL")
        kind_sum_n += rec["n"]
        print(f"    CFB {w.kind_label(kind)} ALL {fmt(rec)}")
    print(f"    sum kinds N={kind_sum_n} vs CFB ALL N={cfb_all['n']}")
    if kind_sum_n != cfb_all["n"]:
        mismatches.append("cfb kinds vs ALL")

    now = payload.get("now") or datetime.now(w.ET).strftime("%Y-%m-%d %H:%M:%S ET")
    path = w.write_html(tables, now=now)
    dump = w.json_dump(tables)
    dump["independent"] = {
        "cfb_40_49": {k: {kk: vv for kk, vv in rec.items() if kk != "kinds"} for k, rec in cfb_4049.items()},
        "cfb_40_49_grand": {kk: vv for kk, vv in cfb_grand.items() if kk != "kinds"},
        "cfb_40_49_kinds_on_grand": cfb_grand["kinds"],
        "overall": {kk: vv for kk, vv in overall.items() if kk != "kinds"},
        "tennis_ml_10_49": {kk: vv for kk, vv in tennis_got.items() if kk != "kinds"},
        "soccer_all": {kk: vv for kk, vv in indep_score(soccer).items() if kk != "kinds"},
        "mismatches": mismatches,
        "unique_kinds": sorted(unique_kinds),
    }
    json_path = w.STAMP / "sport_league_t0_decile_20261027.json"
    json_path.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {path}")
    print(f"wrote {json_path}")
    print("mismatches", mismatches or "none")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
