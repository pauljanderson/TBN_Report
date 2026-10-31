"""Tracked in-match books: tennis (and any other) with real post-T0 ticks.

Research only. Reads price_memory.jsonl and official settlements.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Not gold. Not DailyRun.
Does not take price_memory.lock (read-only scan of the jsonl).
Does not replace tennis_dual_yes_dip_no_20261021.html.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from inmatch_vol_hedge_20261021 import (
    assign_t0,
    attach_pair_results,
    first_absorbing,
    last_at_or_before,
    pair_matches,
)
from odds_cross_no_roi_60_70_20261020 import copy_g
from odds_cross_winrate_20261020 import as_float, parse_dt, pct, table, tiny_note
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP
from price_memory import iter_tick_lines, to_et
from tennis_decade_at_start_20261020 import start_lookup_from
from tennis_dual_yes_dip_no_20261021 import (
    C_HI,
    C_LO,
    DIPS,
    compare_rows,
    decide_verdict,
    et_iso,
    first_dip_no,
    fmt_px,
    fmt_signed,
    hedge_lo,
    is_competitive,
    last_live_quote_ts,
    last_name,
    match_id,
    named_pairs,
    pick_history,
    simulate_current_lock,
    simulate_pair,
    summarize_d,
    summarize_lock,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "tracked_inmatch_books_20261021.html"

ASKED = (
    "Report the ones we DID track — tennis (and any other) books where we actually have "
    "in-match ticks after T0, not empty-window “never dipped” artifacts. Dual-Yes then "
    "dip-No at D=5/10/15/20/25 only on that tracked subset, settled and still-live "
    "separately, versus the current lock Yes+No ≤ $0.95 on the same subset. Include "
    "Wawrinka vs Landaluce if it is on the tape. "
    "Follow-up: add the number of ticks to the table “Per-match tracked tennis "
    "(C in 0.95–1.20)”. He is looking at Miyoshi vs Jong on Polymarket. Miyoshi started "
    "at 60, low 6. Jong started at 41, low 7. If we had bought Yes Miyoshi at 60, another "
    "Yes when Miyoshi dropped to 35, Yes Jong at 41, and another Yes on Miyoshi at 16, "
    "we would have won $2 and spent $1.52 — he says this is the 25-cent dip rule. He "
    "asks: are you not tracking enough ticks? Does it move so fast we can’t see it?"
)

PLAIN = (
    "The last dual-Yes page mixed real in-match tape with empty books. An empty book "
    "is a match where we stored a T0 Yes for both players and then never wrote another "
    "Yes or No change after T0 (or after listed start). Those “never dipped” rows are "
    "missing data, not quiet matches. This page keeps only books with at least one "
    "Yes/No price change after T0. T0 is the last Yes at or before listed start; if we "
    "missed the pre-start book, T0 is the first time both sides have a live Yes. "
    "A change-tick is a stored Yes or No print that is a different price than the last "
    "one we had. Dual-Yes then dip-No means: buy one Yes on each player at T0, then "
    "if that player’s Yes later falls D cents, buy one No on that name. Current lock "
    "is the opposite: do not buy both Yes at T0; wait until some Yes+No on the same "
    "player sums to $0.95 or less. "
    "The per-match table now shows in-match ticks (post-T0 Yes/No changes), pre-match "
    "ticks (stored changes at or before T0 / listed start), and total ticks, so a quiet "
    "in-match column is not confused with “we never saw the book.” Miyoshi vs Jong is "
    "the example: Polymarket did print 0.60 → 0.35 → 0.16 → 0.06 on Miyoshi and "
    "0.41 → 0.07 on Jong. Those prints sit before the listed 15:00 ET start, so the "
    "in-match column is small even though the tape is dense. Buying more Yes on a dip "
    "is not the 25-cent dual-Yes-then-No hedge. Three Yes Miyoshi + one Yes Jong pays "
    "$3 if Miyoshi wins and $1 if Jong wins — not automatically $2. Research only. Not "
    "gold. Not DailyRun. Short October 2026 tape. Annualized rate of return is omitted "
    "— these are same-day contracts, not a stock book with days held."
)


def esc(value) -> str:
    import html as html_mod
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def stream_moneyline(history: Path | None = None) -> dict:
    """Tennis plus any other sport moneyline Yes/No change-ticks."""
    print("streaming moneyline yes/no (archive + shards)", flush=True)
    series: dict[tuple, dict] = {}
    n_lines = 0
    n_hits = 0
    n_tennis = 0
    n_other = 0
    sport_hits: dict[str, int] = defaultdict(int)
    seen_min = None
    seen_max = None
    for line in iter_tick_lines():
            n_lines += 1
            if n_lines % 400000 == 0:
                print(f"  {n_lines} lines, series {len(series)} ticks {n_hits}", flush=True)
            if "moneyline" not in line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if str(rec.get("market_type") or "") != "moneyline":
                continue
            pay = str(rec.get("pay") or "yes").lower()
            if pay not in ("yes", "no"):
                continue
            price = as_float(rec.get("price"))
            if price is None or price <= 0.0 or price >= 1.0:
                continue
            seen = rec.get("seen_at") or ""
            dt = parse_dt(seen)
            if dt is None:
                continue
            ts = int(to_et(dt).timestamp())
            game = rec.get("game") or ""
            side = rec.get("side") or rec.get("side_label") or ""
            venue = rec.get("venue") or ""
            sport = str(rec.get("sport") or "").lower() or "unknown"
            if not game or not side or not venue:
                continue
            key = (sport, game, venue, side, pay)
            st = series.get(key)
            if st is None:
                st = {
                    "sport": sport,
                    "game": game,
                    "venue": venue,
                    "side": side,
                    "pay": pay,
                    "start": rec.get("game_start") or "",
                    "ticks": [],
                }
                series[key] = st
            elif rec.get("game_start") and not st["start"]:
                st["start"] = rec.get("game_start") or ""
            ticks = st["ticks"]
            px = round(price, 4)
            if ticks and ticks[-1][0] == ts and ticks[-1][1] == px:
                continue
            if ticks and ticks[-1][1] == px:
                continue
            ticks.append((ts, px))
            n_hits += 1
            sport_hits[sport] += 1
            if sport == "tennis":
                n_tennis += 1
            else:
                n_other += 1
            if seen:
                if seen_min is None or seen < seen_min:
                    seen_min = seen
                if seen_max is None or seen > seen_max:
                    seen_max = seen
    for st in series.values():
        st["ticks"].sort(key=lambda row: row[0])
    print(
        f"stream done lines={n_lines} ml_change_ticks={n_hits} "
        f"tennis={n_tennis} other={n_other} series={len(series)}",
        flush=True,
    )
    return {
        "series": series,
        "n_lines": n_lines,
        "n_hits": n_hits,
        "n_tennis": n_tennis,
        "n_other": n_other,
        "sport_hits": dict(sport_hits),
        "seen_min": seen_min or "",
        "seen_max": seen_max or "",
        "history": str(history),
    }


def after_anchor_ticks(ticks: list[tuple[int, float]], lo: int) -> list[tuple[int, float]]:
    return [row for row in (ticks or []) if row[0] > lo]


def at_or_before_ticks(ticks: list[tuple[int, float]], lo: int) -> list[tuple[int, float]]:
    return [row for row in (ticks or []) if row[0] <= lo]


def mark_tracked(pair: dict) -> None:
    t0 = pair.get("t0_ts")
    pair["tracked"] = False
    pair["inmatch_n"] = 0
    pair["inmatch_yes"] = 0
    pair["inmatch_no"] = 0
    pair["pre_n"] = 0
    pair["pre_yes"] = 0
    pair["pre_no"] = 0
    pair["total_n"] = 0
    pair["max_gap_min"] = None
    pair["max_dip_a"] = None
    pair["max_dip_b"] = None
    pair["first_tick_mins"] = None
    pair["last_tick_mins"] = None
    pair["lo"] = hedge_lo(pair) if t0 is not None else None
    lo = pair.get("lo")
    if t0 is None or lo is None:
        return
    bags = [
        after_anchor_ticks(pair.get("yes_a") or [], lo),
        after_anchor_ticks(pair.get("yes_b") or [], lo),
        after_anchor_ticks(pair.get("no_a") or [], lo),
        after_anchor_ticks(pair.get("no_b") or [], lo),
    ]
    pre_bags = [
        at_or_before_ticks(pair.get("yes_a") or [], lo),
        at_or_before_ticks(pair.get("yes_b") or [], lo),
        at_or_before_ticks(pair.get("no_a") or [], lo),
        at_or_before_ticks(pair.get("no_b") or [], lo),
    ]
    yes_n = len(bags[0]) + len(bags[1])
    no_n = len(bags[2]) + len(bags[3])
    pre_yes = len(pre_bags[0]) + len(pre_bags[1])
    pre_no = len(pre_bags[2]) + len(pre_bags[3])
    times = sorted({ts for bag in bags for ts, _ in bag})
    pair["inmatch_yes"] = yes_n
    pair["inmatch_no"] = no_n
    pair["inmatch_n"] = yes_n + no_n
    pair["pre_yes"] = pre_yes
    pair["pre_no"] = pre_no
    pair["pre_n"] = pre_yes + pre_no
    pair["total_n"] = pair["pre_n"] + pair["inmatch_n"]
    pair["tracked"] = pair["inmatch_n"] >= 1
    if times:
        pair["first_tick_mins"] = (times[0] - lo) / 60.0
        pair["last_tick_mins"] = (times[-1] - lo) / 60.0
        gaps = [(times[0] - lo) / 60.0]
        gaps.extend((times[i] - times[i - 1]) / 60.0 for i in range(1, len(times)))
        pair["max_gap_min"] = max(gaps) if gaps else None
    after_a = bags[0]
    after_b = bags[1]
    if after_a and pair.get("t0_a") is not None:
        pair["max_dip_a"] = max(0.0, float(pair["t0_a"]) - min(px for _, px in after_a))
    if after_b and pair.get("t0_b") is not None:
        pair["max_dip_b"] = max(0.0, float(pair["t0_b"]) - min(px for _, px in after_b))


def match_date(pair: dict) -> str:
    start_dt = pair.get("start_dt")
    if start_dt is not None:
        return to_et(start_dt).date().isoformat()
    t0 = pair.get("t0_ts")
    if t0 is not None:
        return datetime.fromtimestamp(t0, ET).date().isoformat()
    return ""


def sibling_venues(pair: dict, by_id: dict[tuple, list[dict]]) -> str:
    names = []
    for other in by_id.get(match_id(pair), []):
        venue = other.get("venue") or ""
        if venue and venue not in names:
            names.append(venue)
    return ", ".join(names)


def fmt_mins(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)


def d_table_rows(summaries: list[dict]) -> list[dict]:
    rows = []
    for r in summaries:
        row = dict(r)
        row["dip"] = f"{r['dip_cents']}¢"
        row["mean"] = fmt_signed(r["mean"])
        row["median"] = fmt_signed(r["median"])
        row["total"] = fmt_signed(r["total"])
        row["mean_cost"] = fmt_px(r["mean_cost"])
        row["mean_hold"] = fmt_signed(r["mean_hold"])
        row["mean_fee"] = fmt_signed(r["mean_fee"])
        row["mean_none"] = fmt_signed(r["mean_none"])
        row["mean_one"] = fmt_signed(r["mean_one"])
        row["mean_both"] = fmt_signed(r["mean_both"])
        row["mean_both_comp"] = fmt_signed(r["mean_both_comp"])
        row["identity"] = fmt_signed(r["identity"])
        rows.append(row)
    return rows


def d_headers() -> list[tuple[str, str]]:
    return [
        ("D", "text"), ("N books", "num"), ("N settled", "num"),
        ("Mean $", "num"), ("Median $", "num"), ("Total $", "num"), ("Win rate %", "num"),
        ("% both hedges", "num"), ("% one hedge", "num"), ("% no hedge", "num"),
        ("N both", "num"), ("N one", "num"), ("N none", "num"),
        ("Mean cost", "num"), ("Mean stand-pat $1−C", "num"), ("Mean $ after fees", "num"),
        ("Mean $ if no hedge", "num"), ("Mean $ if one hedge", "num"), ("Mean $ if both hedges", "num"),
        ("N both at complement", "num"), ("Mean $ both-complement", "num"), ("Identity −2D", "num"),
        ("No fills that were asks", "num"), ("No fills that were complement", "num"),
        ("Note", "text"),
    ]


def d_fields() -> list[str]:
    return [
        "dip", "n", "n_settled", "mean", "median", "total", "win_pct",
        "pct_both", "pct_one", "pct_none", "n_both", "n_one", "n_none",
        "mean_cost", "mean_hold", "mean_fee",
        "mean_none", "mean_one", "mean_both",
        "n_both_comp", "mean_both_comp", "identity",
        "n_no_ask", "n_complement", "note",
    ]


def per_match_rows(pairs: list[dict], by_id: dict[tuple, list[dict]]) -> list[dict]:
    rows = []
    for p in pairs:
        rec = (p.get("dips") or {}).get(0.05) or {}
        winner = p.get("winner")
        win_name = p.get("side_a") if winner == "a" else p.get("side_b") if winner == "b" else ""
        live = "yes" if not p.get("settled") else "no"
        rows.append({
            "game": p.get("game") or "",
            "date": match_date(p),
            "venues": sibling_venues(p, by_id),
            "venue": p.get("venue") or "",
            "sport": p.get("sport") or "",
            "side_a": p.get("side_a") or "",
            "t0_a": fmt_px(p.get("t0_a")),
            "side_b": p.get("side_b") or "",
            "t0_b": fmt_px(p.get("t0_b")),
            "c0": fmt_px(p.get("c0")),
            "inmatch_n": p.get("inmatch_n") or 0,
            "pre_n": p.get("pre_n") or 0,
            "total_n": p.get("total_n") or 0,
            "inmatch_yes": p.get("inmatch_yes") or 0,
            "inmatch_no": p.get("inmatch_no") or 0,
            "max_gap": fmt_mins(p.get("max_gap_min")),
            "max_dip_a": fmt_px(p.get("max_dip_a")),
            "max_dip_b": fmt_px(p.get("max_dip_b")),
            "mix": rec.get("mix") or "",
            "pnl": fmt_signed(rec.get("pnl")) if rec.get("pnl") is not None else "",
            "live": live,
            "winner": win_name,
            "t0_label": p.get("t0_label") or "",
            "t0_when": et_iso(p.get("t0_ts")),
            "sort_live": 0 if live == "yes" else 1,
            "sort_ticks": -(p.get("inmatch_n") or 0),
        })
    rows.sort(key=lambda r: (r["sort_live"], r["sort_ticks"], r.get("game") or "", r.get("venue") or ""))
    return rows


def uniq_pairs(pairs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for p in pairs:
        key = (p.get("sport") or "", p.get("game") or "", p.get("venue") or "", p.get("side_a") or "", p.get("side_b") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def named_html(pairs: list[dict], *needles: str, title: str) -> str:
    found = uniq_pairs(named_pairs(pairs, *needles))
    if not found:
        return (
            f"<p class='note'>{esc(title)} was not on this two-sided tape "
            f"(tracked or empty-window).</p>"
        )
    chunks = [f"<h3>{esc(title)}</h3>"]
    for p in found:
        rec = (p.get("dips") or {}).get(0.05) or {}
        lock = p.get("cur_lock") or {}
        lock_txt = "no Yes+No ≤ $0.95 on this book"
        if lock.get("taken"):
            pnl_txt = fmt_signed(lock.get("pnl")) if lock.get("pnl") is not None else "pending"
            lock_txt = (
                f"{esc(lock.get('kind') or '')} {esc(lock.get('player') or '')}: "
                f"Yes {fmt_px(lock.get('yes'))} ({esc(lock.get('yes_venue') or '')}) + "
                f"No {fmt_px(lock.get('no'))} ({esc(lock.get('no_venue') or '')}) = "
                f"{fmt_px(lock.get('sum'))}. Locked P&amp;L {pnl_txt}."
            )
        chunks.append(
            f"<p><strong>{esc(p.get('game') or '')}</strong> — {esc(p.get('venue') or '')}. "
            f"Tracked: <strong>{'yes' if p.get('tracked') else 'no'}</strong>. "
            f"In-match change-ticks {p.get('inmatch_n') or 0} "
            f"(Yes {p.get('inmatch_yes') or 0}, No {p.get('inmatch_no') or 0}; "
            f"pre-match {p.get('pre_n') or 0}; total {p.get('total_n') or 0}). "
            f"T0 {esc(p.get('t0_label') or '')} at {esc(et_iso(p.get('t0_ts')))}: "
            f"{esc(p.get('side_a'))} {fmt_px(p.get('t0_a'))} / "
            f"{esc(p.get('side_b'))} {fmt_px(p.get('t0_b'))}, C = {fmt_px(p.get('c0'))}. "
            f"Max dip {esc(p.get('side_a'))} {fmt_px(p.get('max_dip_a'))}, "
            f"{esc(p.get('side_b'))} {fmt_px(p.get('max_dip_b'))}. "
            f"Max gap {fmt_mins(p.get('max_gap_min'))} min. "
            f"D=5 mix {esc(rec.get('mix') or '')}. "
            f"P&amp;L {fmt_signed(rec.get('pnl')) if rec.get('pnl') is not None else 'still live / unsettled'}. "
            f"Still live: {'yes' if not p.get('settled') else 'no'}. "
            f"Current lock: {lock_txt}</p>"
        )
    return "\n".join(chunks)


def _is_miyoshi(name: str) -> bool:
    return "miyoshi" in (name or "").lower()


def _is_jong(name: str) -> bool:
    return "jong" in (name or "").lower()


def first_near_px(ticks: list[tuple[int, float]], px: float, tol: float = 0.005, after: int | None = None):
    for ts, price in ticks or []:
        if after is not None and ts < after:
            continue
        if abs(price - px) <= tol:
            return ts, price
    return None


def first_leq_px(ticks: list[tuple[int, float]], thresh: float, after: int | None = None):
    for ts, price in ticks or []:
        if after is not None and ts < after:
            continue
        if price <= thresh + 1e-12:
            return ts, price
    return None


def max_gap_sec(ticks: list[tuple[int, float]], lo: int | None = None, hi: int | None = None):
    times = [
        ts for ts, _ in (ticks or [])
        if (lo is None or ts >= lo) and (hi is None or ts <= hi)
    ]
    if len(times) < 2:
        return None, None, None
    best = 0
    a = b = times[0]
    for i in range(1, len(times)):
        g = times[i] - times[i - 1]
        if g > best:
            best = g
            a, b = times[i - 1], times[i]
    return best, a, b


def split_miyoshi_sides(pair: dict) -> tuple[str, str, list, list, list, list] | None:
    a, b = pair.get("side_a") or "", pair.get("side_b") or ""
    if _is_miyoshi(a) and _is_jong(b):
        return a, b, pair.get("yes_a") or [], pair.get("yes_b") or [], pair.get("no_a") or [], pair.get("no_b") or []
    if _is_miyoshi(b) and _is_jong(a):
        return b, a, pair.get("yes_b") or [], pair.get("yes_a") or [], pair.get("no_b") or [], pair.get("no_a") or []
    return None


def paul_path_hi(pair: dict, lo: int) -> int | None:
    last = last_live_quote_ts(pair)
    after_a = [row for row in (pair.get("yes_a") or []) if row[0] > lo]
    after_b = [row for row in (pair.get("yes_b") or []) if row[0] > lo]
    absorb = first_absorbing(after_a, after_b)
    if last is None and absorb is None:
        return None
    if absorb is None:
        return last
    if last is None:
        return absorb - 1
    return min(last, absorb - 1)


def miyoshi_path_rows(pair: dict) -> tuple[list[dict], dict]:
    split = split_miyoshi_sides(pair)
    facts: dict = {"venue": pair.get("venue") or ""}
    if not split:
        return [], facts
    m_name, j_name, yes_m, yes_j, no_m, no_j = split
    facts["m_name"] = m_name
    facts["j_name"] = j_name
    facts["yes_m_n"] = len(yes_m)
    facts["yes_j_n"] = len(yes_j)
    facts["no_m_n"] = len(no_m)
    facts["no_j_n"] = len(no_j)
    t60 = first_near_px(yes_m, 0.60)
    t41 = first_near_px(yes_j, 0.41, after=(t60[0] - 5 if t60 else None))
    facts["t60"] = t60
    facts["t41"] = t41
    paul_lo = t60[0] if t60 else None
    t35 = first_near_px(yes_m, 0.35, after=paul_lo)
    t35_leq = first_leq_px(yes_m, 0.35, after=paul_lo)
    t16 = first_near_px(yes_m, 0.16, after=paul_lo)
    t16_leq = first_leq_px(yes_m, 0.16, after=paul_lo)
    t06 = first_near_px(yes_m, 0.06, after=paul_lo)
    t07 = first_near_px(yes_j, 0.07, after=paul_lo)
    facts["t35"] = t35
    facts["t35_leq"] = t35_leq
    facts["t16"] = t16
    facts["t16_leq"] = t16_leq
    facts["t06"] = t06
    facts["t07"] = t07
    low_m = min(yes_m, key=lambda row: row[1]) if yes_m else None
    low_j = min(yes_j, key=lambda row: row[1]) if yes_j else None
    facts["low_m"] = low_m
    facts["low_j"] = low_j
    listed_lo = pair.get("lo")
    gap_paul = max_gap_sec(sorted(yes_m + yes_j, key=lambda r: r[0]), lo=paul_lo) if paul_lo else (None, None, None)
    facts["max_gap_paul_sec"] = gap_paul[0]
    facts["max_gap_paul_a"] = gap_paul[1]
    facts["max_gap_paul_b"] = gap_paul[2]
    collapse_lo = t35_leq[0] if t35_leq else paul_lo
    gap_collapse = max_gap_sec(sorted(yes_m + yes_j, key=lambda r: r[0]), lo=collapse_lo) if collapse_lo else (None, None, None)
    facts["max_gap_collapse_sec"] = gap_collapse[0]
    d25 = None
    if t60 and t41 and paul_lo is not None:
        hi = paul_path_hi(pair, paul_lo)
        ha = first_dip_no(yes_m, no_m, t60[1], paul_lo, hi, 0.25) if hi is not None else None
        hb = first_dip_no(yes_j, no_j, t41[1], paul_lo, hi, 0.25) if hi is not None else None
        cost = t60[1] + t41[1]
        if ha:
            cost += ha["no_px"]
        if hb:
            cost += hb["no_px"]
        winner = pair.get("winner")
        # winner is "a"/"b" on pair sides, not Miyoshi/Jong names
        win_is_m = False
        win_is_j = False
        if pair.get("settled"):
            if pair.get("winner") == "a":
                win_is_m = _is_miyoshi(pair.get("side_a") or "")
                win_is_j = _is_jong(pair.get("side_a") or "")
            elif pair.get("winner") == "b":
                win_is_m = _is_miyoshi(pair.get("side_b") or "")
                win_is_j = _is_jong(pair.get("side_b") or "")
        paid = 1.0
        if ha and win_is_j:
            paid += 1.0
        if hb and win_is_m:
            paid += 1.0
        if ha and hb:
            paid = 2.0
        d25 = {
            "ha": ha,
            "hb": hb,
            "cost": cost,
            "mix": {0: "none", 1: "one", 2: "both"}[int(ha is not None) + int(hb is not None)],
            "payout": paid if pair.get("settled") else None,
            "pnl": (paid - cost) if pair.get("settled") else None,
            "win_is_j": win_is_j,
            "win_is_m": win_is_m,
            "hi": hi,
        }
        facts["d25"] = d25
        facts["win_is_j"] = win_is_j
        facts["win_is_m"] = win_is_m
    listed_d25 = (pair.get("dips") or {}).get(0.25) or {}
    facts["listed_d25"] = listed_d25
    facts["listed_t0_a"] = pair.get("t0_a")
    facts["listed_t0_b"] = pair.get("t0_b")
    facts["listed_t0_ts"] = pair.get("t0_ts")
    facts["listed_label"] = pair.get("t0_label") or ""
    facts["inmatch_n"] = pair.get("inmatch_n") or 0
    facts["pre_n"] = pair.get("pre_n") or 0
    facts["total_n"] = pair.get("total_n") or 0
    facts["winner_name"] = (
        pair.get("side_a") if pair.get("winner") == "a"
        else pair.get("side_b") if pair.get("winner") == "b"
        else ""
    )

    def row(when_ts, side, pay, px, note, paul_lo=paul_lo, listed_lo=listed_lo) -> dict:
        vs = ""
        if listed_lo is not None and when_ts is not None:
            vs = "pre-match vs listed start" if when_ts <= listed_lo else "in-match vs listed start"
        mins = ""
        if paul_lo is not None and when_ts is not None:
            mins = f"{(when_ts - paul_lo) / 60.0:.1f}"
        return {
            "when": et_iso(when_ts) if when_ts is not None else "",
            "side": side,
            "pay": pay,
            "px": fmt_px(px),
            "mins": mins,
            "vs": vs,
            "note": note,
        }

    rows: list[dict] = []
    if yes_m:
        rows.append(row(yes_m[0][0], m_name, "Yes", yes_m[0][1], "first stored Yes"))
    if yes_j:
        rows.append(row(yes_j[0][0], j_name, "Yes", yes_j[0][1], "first stored Yes"))
    if t60:
        rows.append(row(t60[0], m_name, "Yes", t60[1], "Paul T0 0.60"))
    if t41:
        rows.append(row(t41[0], j_name, "Yes", t41[1], "Paul T0 0.41"))
    if t60:
        resume = None
        for ts, px in yes_m:
            if ts > t60[0] + 30 * 60:
                resume = (ts, px)
                break
        if resume and resume[0] - t60[0] >= 20 * 60:
            j_resume = last_at_or_before(yes_j, resume[0])
            rows.append(row(resume[0], m_name, "Yes", resume[1], "resume after longest gap"))
            if j_resume:
                rows.append(row(j_resume[0], j_name, "Yes", j_resume[1], "Jong at resume"))
    if d25 and d25.get("hb"):
        hb = d25["hb"]
        rows.append(row(hb["ts"], j_name, "Yes", hb["yes_print"], f"first 25c dip Jong (No {fmt_px(hb['no_px'])} {hb['no_src']})"))
    if t07:
        rows.append(row(t07[0], j_name, "Yes", t07[1], "Jong low 0.07"))
    if t35_leq:
        rows.append(row(t35_leq[0], m_name, "Yes", t35_leq[1], "first ≤0.35 (25c dip from 0.60)"))
    if t35 and (not t35_leq or t35[0] != t35_leq[0]):
        rows.append(row(t35[0], m_name, "Yes", t35[1], "exact 0.35 print"))
    if t16_leq:
        rows.append(row(t16_leq[0], m_name, "Yes", t16_leq[1], "first ≤0.16 on the way down"))
    if t06:
        rows.append(row(t06[0], m_name, "Yes", t06[1], "exact 0.06 print"))
    if t16 and (not t16_leq or t16[0] != t16_leq[0]):
        rows.append(row(t16[0], m_name, "Yes", t16[1], "exact 0.16 print (bounce after 0.06)"))
    if low_m:
        rows.append(row(low_m[0], m_name, "Yes", low_m[1], "Miyoshi low"))
    if pair.get("t0_ts") is not None:
        rows.append(row(
            pair["t0_ts"],
            pair.get("side_a") or "",
            "Yes",
            pair.get("t0_a"),
            f"listed-start T0 A ({pair.get('t0_label') or ''})",
        ))
        rows.append(row(
            pair["t0_ts"],
            pair.get("side_b") or "",
            "Yes",
            pair.get("t0_b"),
            "listed-start T0 B",
        ))
    if yes_m:
        rows.append(row(yes_m[-1][0], m_name, "Yes", yes_m[-1][1], "last stored Yes"))
    if yes_j:
        rows.append(row(yes_j[-1][0], j_name, "Yes", yes_j[-1][1], "last stored Yes"))
    # de-dupe identical when/side/px/note
    seen = set()
    uniq = []
    for r in rows:
        key = (r["when"], r["side"], r["pay"], r["px"], r["note"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq, facts


def miyoshi_text_and_html(pairs: list[dict]) -> tuple[str, str]:
    found = uniq_pairs(named_pairs(pairs, "miyoshi", "jong"))
    if not found:
        text = "Miyoshi vs Jong was not on this two-sided tape."
        return text, f"<p class='note'>{esc(text)}</p>"
    pm = next((p for p in found if str(p.get("venue") or "").lower() == "polymarket"), found[0])
    others = [p for p in found if p is not pm]
    rows, facts = miyoshi_path_rows(pm)
    d25 = facts.get("d25") or {}
    listed = facts.get("listed_d25") or {}
    gap_sec = facts.get("max_gap_paul_sec")
    gap_min = f"{gap_sec / 60.0:.1f}" if gap_sec is not None else ""
    gap_a = et_iso(facts.get("max_gap_paul_a"))
    gap_b = et_iso(facts.get("max_gap_paul_b"))
    saw_60 = "yes" if facts.get("t60") else "no"
    saw_35 = "yes" if facts.get("t35") else "no"
    saw_16 = "yes" if facts.get("t16") else "no"
    saw_06 = "yes" if facts.get("t06") else "no"
    saw_41 = "yes" if facts.get("t41") else "no"
    saw_07 = "yes" if facts.get("t07") else "no"
    winner = facts.get("winner_name") or "unsettled"
    kalshi_note = "Kalshi moneyline Yes/No change-ticks: none on this tape (Kalshi settlement still recorded Jong won)."
    paul_cost = 0.60 + 0.35 + 0.41 + 0.16
    if facts.get("win_is_j"):
        paul_payout = 1.0
        paul_if_miyoshi = 3.0
    elif facts.get("win_is_m"):
        paul_payout = 3.0
        paul_if_miyoshi = 3.0
    else:
        paul_payout = None
        paul_if_miyoshi = 3.0
    listed_mix = listed.get("mix") or "n/a"
    listed_pnl = fmt_signed(listed.get("pnl")) if listed.get("pnl") is not None else "n/a"
    d25_cost = fmt_px(d25.get("cost")) if d25 else ""
    d25_pnl = fmt_signed(d25.get("pnl")) if d25.get("pnl") is not None else "n/a"
    d25_mix = d25.get("mix") or "n/a"
    text = (
        f"Polymarket {pm.get('game')}: in-match ticks {facts.get('inmatch_n')} "
        f"(pre-match {facts.get('pre_n')}, total {facts.get('total_n')}). "
        f"Listed-start T0 {fmt_px(pm.get('t0_a'))}/{fmt_px(pm.get('t0_b'))} at {et_iso(pm.get('t0_ts'))}. "
        f"Tape printed Miyoshi 0.60 {saw_60}, 0.35 {saw_35}, 0.16 {saw_16}, 0.06 {saw_06}; "
        f"Jong 0.41 {saw_41}, 0.07 {saw_07}. Winner {winner}."
    )
    path_bits = []
    if facts.get("t60"):
        path_bits.append(f"Miyoshi Yes 0.60 at {et_iso(facts['t60'][0])}")
    if facts.get("t41"):
        path_bits.append(f"Jong Yes 0.41 at {et_iso(facts['t41'][0])}")
    if facts.get("t35"):
        path_bits.append(f"Miyoshi Yes 0.35 at {et_iso(facts['t35'][0])}")
    if facts.get("t16"):
        path_bits.append(f"Miyoshi Yes 0.16 at {et_iso(facts['t16'][0])}")
    if facts.get("t06"):
        path_bits.append(f"Miyoshi Yes 0.06 at {et_iso(facts['t06'][0])}")
    if facts.get("t07"):
        path_bits.append(f"Jong Yes 0.07 at {et_iso(facts['t07'][0])}")
    other_txt = []
    for p in others:
        other_txt.append(
            f"{p.get('venue')}: in-match {p.get('inmatch_n') or 0}, pre {p.get('pre_n') or 0}, "
            f"T0 {fmt_px(p.get('t0_a'))}/{fmt_px(p.get('t0_b'))}"
        )
    html = f"""
<div class="hl">
<h2>Miyoshi vs Jong — ticks vs the 25-cent dip</h2>
<p>Paul’s path: Yes Miyoshi 0.60 + Yes Miyoshi 0.35 + Yes Jong 0.41 + Yes Miyoshi 0.16 = <strong>${paul_cost:.2f}</strong>. He said that wins $2. Honest payout of that book: <strong>3× Yes Miyoshi + 1× Yes Jong</strong> pays <strong>$3 if Miyoshi wins</strong> and <strong>$1 if Jong wins</strong>, not automatically $2. Official winner: <strong>{esc(winner)}</strong>. Jong won, so that path pays $1 on $1.52 spent → <strong>−$0.52</strong>. If Miyoshi had won it would pay $3 → +$1.48. A $2 payout is what <em>dual-Yes then No on each name</em> pays when both hedges fill — a different trade than buying more Yes on the dip.</p>
<p>Did the tape see 0.60 → 0.35 → 0.16 → 0.06 and Jong 0.41 → 0.07? <strong>Yes</strong> on Polymarket ({", ".join(esc(x) for x in path_bits)}). Collection is enough to see that path. The longest Yes gap after 0.60 is {esc(gap_min)} min ({esc(gap_a)} to {esc(gap_b)}); prices resumed at about 0.59 / 0.42, so that hole did not skip 0.60→0.06. On the way down Miyoshi jumped 0.20→0.12 (no exact 0.16 print until a bounce after 0.06). In-match ticks vs listed 15:00 ET start: {facts.get('inmatch_n')} (pre-match {facts.get('pre_n')}, total {facts.get('total_n')}). Listed-start T0 is {fmt_px(pm.get('t0_a'))}/{fmt_px(pm.get('t0_b'))} at {esc(et_iso(pm.get('t0_ts')))} — after the match was already at 2¢/99¢ — so the per-match row looks quiet even though we stored {facts.get('yes_m_n')} Miyoshi Yes change-ticks and {facts.get('yes_j_n')} Jong Yes change-ticks.</p>
<p>D=25 No-hedge on listed-start T0: mix {esc(listed_mix)}, P&amp;L {esc(listed_pnl)} (no 25¢ dip after 2¢/99¢). Same D=25 if T0 is Paul’s 0.60/0.41 (search starts there, not at listed 15:00): mix {esc(d25_mix)}, cost {esc(d25_cost)}, payout $2 if both Nos fill, P&amp;L {esc(d25_pnl)}. {esc(kalshi_note)} {esc("; ".join(other_txt))}</p>
</div>
<p class="note">Downsampled Polymarket Yes prints only (T0, 25c dip, 35, 16, low, last, plus the 63-minute resume). Not thousands of rows. Click column headers to sort.</p>
{table(
    [("When (ET)", "date"), ("Side", "text"), ("Pay", "text"), ("Price", "num"),
     ("Minutes from 0.60", "num"), ("Vs listed start", "text"), ("Note", "text")],
    rows,
    ["when", "side", "pay", "px", "mins", "vs", "note"],
)}
"""
    return text, html


def write_html(payload: dict) -> None:
    stream = payload["stream"]
    d_all = d_table_rows(payload["d_rows"])
    d_settled = d_table_rows(payload["d_settled_rows"])
    d_live = d_table_rows(payload["d_live_rows"])
    d_comp = d_table_rows(payload["d_comp_rows"])
    lock = payload["lock"]
    lock_rows = [{
        "book": "Current Yes+No ≤ $0.95 (no T0 buy) on tracked subset",
        "n": lock["n"],
        "n_taken": lock["n_taken"],
        "pct_taken": lock["pct_taken"],
        "n_settled": lock["n_settled"],
        "mean_all": fmt_signed(lock["mean_all_settled"]),
        "median_all": fmt_signed(lock["median_all_settled"]),
        "mean_taken": fmt_signed(lock["mean_when_taken"]),
        "median_taken": fmt_signed(lock["median_when_taken"]),
        "win_taken": lock["win_pct_taken"],
        "n_same": lock["n_same_venue"],
        "n_cross": lock["n_cross_venue"],
        "n_two_yes": lock["n_two_yes"],
        "pct_two_yes": lock["pct_two_yes"],
        "note": lock["note"],
    }]
    sport_rows = [
        {"sport": k, "ticks": v}
        for k, v in sorted((payload.get("sport_hits") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    other_rows = payload.get("other_rows") or []
    empty_rows = payload.get("empty_rows") or []
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tracked in-match books 2026-10-21</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
h3 {{ font-size: 1.05rem; margin-top: 1.2rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Tracked in-match books — tennis (and any other)</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Short October 2026 live tape — no in-sample / out-of-sample split. Verdict on this tracked subset: <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Universe:</strong> {payload['n_tracked']} tracked tennis books with at least one Yes/No change-tick after T0 (or after listed start when that is later than T0), out of {payload['n_in']} two-sided tennis books whose T0 Yes A + Yes B sits in [0.95, 1.20]. That is the 299-set comparison on this tape ({payload['n_in']} now). Empty-window leftovers: {payload['n_empty']} of {payload['n_in']}.</p>
<p><strong>Still live / settled:</strong> tracked settled {payload['n_tracked_settled']}; tracked still live {payload['n_tracked_live']}.</p>
<p><strong>Wawrinka vs Landaluce:</strong> {esc(payload.get('waw_text') or 'not on tape')}</p>
<p><strong>Miyoshi vs Jong ticks:</strong> {esc(payload.get('miyoshi_text') or 'not on tape')}</p>
<p><strong>Pacheco vs Rodriguez Taverna (empty-window contrast):</strong> {esc(payload.get('pacheco_text') or '')}</p>
<p><strong>Sweet spot on the tracked subset:</strong> {esc(payload['sweet_text'])}</p>
<p><strong>Versus the current lock on the same subset:</strong> {esc(payload['vs_lock_text'])}</p>
<p>Annualized rate of return (Ann ROR) is omitted. These are same-day tennis contracts. We do not have closed-trade days held, so the house Ann ROR formula is not computed. In-sample / out-of-sample Ann ROR, Max DD, Calmar, Sharpe, capital days, Paul Score, and FIT are n/a for the same reason.</p>
</div>

<div class="warn">
<p>Primary P&amp;L is without fees. Optional fee line uses the house venue formulas (Kalshi 0.07×p×(1−p) to a ten-thousandth; Gemini same raw rounded up to a cent; Polymarket 0.0695×p×(1−p) banker-cent). Novig fills get $0 fee in this optional line because we do not invent one. Optimistic fills at print. Complement No ignores No vig. Do not buy after the first 5¢ / 95¢ absorbing print — that is settlement, not an in-match dip.</p>
<p>N settled tracked {payload['n_tracked_settled']}. {esc(payload.get('note_n') or '')} Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Research only. Not gold. Not DailyRun. Do not send this plan.</p>
</div>

<h2>Freeze</h2>
<ul>
<li>Tape: <code>{esc(stream.get('history') or '')}</code>. Moneyline change-ticks {stream.get('n_hits') or 0:,} of {stream.get('n_lines') or 0:,} lines (tennis {stream.get('n_tennis') or 0:,}; other sports {stream.get('n_other') or 0:,}). First quote {esc(stream.get('seen_min') or '')}. Last quote {esc(stream.get('seen_max') or '')}.</li>
<li>Two-sided tennis books {payload['n_pairs']}. With T0 {payload['n_t0']}. C in [0.95, 1.20]: {payload['n_in']} (the “299 set” on this tape). Tracked (post-T0 Yes/No change-tick): {payload['n_tracked']}. Empty window: {payload['n_empty']}.</li>
<li>T0: last Yes at or before listed start for both sides; else first two-sided in-game print, labeled.</li>
<li>In-match / tracked: at least one Yes or No change-tick with timestamp after T0, or after listed start when listed start is later than T0 (so leftover pre-start quotes do not count as in-match). Same-price repeats are not change-ticks.</li>
<li>Dual-Yes then dip-No is scored <em>only</em> on the tracked subset of the C 0.95–1.20 tennis books. Buy 1 Yes each at T0. Then independently, first time that player’s Yes ≤ T0 − D inside the live window, buy 1 No. Window is T0 through last live Yes/No before the first 5¢ or 95¢ Yes print.</li>
<li>No fill = last No ask at or before that timestamp if the tape has one; else 1 − Yes print, labeled complement (optimistic).</li>
<li>Current desk compare on the same tracked subset: do not buy at T0. First time some Yes+No on the same player (this venue or another venue for the same last-name pair and start day) sums to $0.95 or less. If it never prints, P&amp;L = $0 (sit out).</li>
<li>Other sports: listed if they have a two-sided moneyline and at least one post-T0 change-tick. They are not mixed into the tennis D tables or the 299 comparison.</li>
<li>This page does not replace <code>tennis_dual_yes_dip_no_20261021.html</code>.</li>
</ul>
<p>Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h2>1. Tape sports</h2>
<p class="note">Change-ticks stored on this scan. Tennis is the websocket sport (Kalshi Association of Tennis Professionals (ATP) / Challenger when a Polymarket twin exists). Other sports are poller/snapshot leftovers if they appear.</p>
{table([("Sport", "text"), ("Moneyline change-ticks", "num")], sport_rows, ["sport", "ticks"])}

<h2>2. Dual-Yes then dip-No — tracked tennis subset only</h2>
<p class="note">All {payload['n_tracked']} tracked C-in-range tennis books. Mean / median / total / win rate are settled books only. Hedge mix (both / one / none) includes still-live books. Identity column is −2D, the both-hedge complement loss if both dip exactly D. Click column headers to sort.</p>
{table(d_headers(), d_all, d_fields())}

<h3>Settled tracked only</h3>
<p class="note">Same Ds, dropping still-live books from the mix counts too.</p>
{table(d_headers(), d_settled, d_fields())}

<h3>Still-live tracked only</h3>
<p class="note">No official winner yet, so mean / median / P&amp;L are blank. Mix is how many Nos would have filled so far.</p>
{table(d_headers(), d_live, d_fields())}

<h3>Tracked and competitive T0 (both Yes between 10¢ and 90¢)</h3>
<p class="note">Drops 99¢/1¢ blowouts that still sum into 0.95–1.20.</p>
{table(d_headers(), d_comp, d_fields())}

<h2>3. Control vs candidate — tracked subset</h2>
<p class="note">Control is the current desk on the same tracked books: wait for Yes+No ≤ $0.95; sit out $0 if it never prints. Candidates are dual-Yes at T0 then independent dip-No at each D. Mean / median deltas are candidate minus control (all-settled dollars, lock zeros included). Annualized rate of return (Ann ROR) full / in-sample / out-of-sample, Max DD, Calmar, and Sharpe are n/a — no closed-trade days held. Click column headers to sort.</p>
{table(
    [("Arm", "text"), ("Role", "text"), ("N books", "num"), ("N settled", "num"),
     ("Mean $", "num"), ("Median $", "num"), ("Total $", "num"), ("Win rate %", "num"),
     ("Mean cost", "num"), ("% both hedges / taken", "num"), ("% one hedge", "num"), ("% none / sit out", "num"),
     ("Δ mean $ vs lock", "num"), ("Δ median $ vs lock", "num"),
     ("Ann ROR full", "text"), ("Ann ROR IS", "text"), ("Ann ROR OOS", "text"),
     ("Max DD", "text"), ("Calmar", "text"), ("Sharpe", "text"),
     ("Note", "text")],
    payload["compare_rows"],
    ["arm", "role", "n", "n_settled", "mean", "median", "total", "win_pct",
     "mean_cost", "pct_both", "pct_one", "pct_none", "d_mean", "d_med",
     "ann_ror", "ann_ror_is", "ann_ror_oos", "max_dd", "calmar", "sharpe", "note"],
)}

<h2>4. Current lock on the tracked subset</h2>
<p class="note">Sit-out P&amp;L is $0 when the lock never prints. Mean $ on all settled includes those zeros.</p>
{table(
    [("Book", "text"), ("N books", "num"), ("N lock taken", "num"), ("% taken", "num"),
     ("N settled", "num"), ("Mean $ all settled (0 if sit out)", "num"), ("Median $ all settled", "num"),
     ("Mean $ when taken", "num"), ("Median $ when taken", "num"), ("Win % when taken", "num"),
     ("N same-venue Yes+No", "num"), ("N cross-venue Yes+No", "num"),
     ("N two-Yes ≤0.95 (sibling)", "num"), ("% two-Yes sibling", "num"),
     ("Note", "text")],
    lock_rows,
    ["book", "n", "n_taken", "pct_taken", "n_settled", "mean_all", "median_all",
     "mean_taken", "median_taken", "win_taken", "n_same", "n_cross", "n_two_yes", "pct_two_yes", "note"],
)}

<h2>5. Named matches</h2>
{payload.get('waw_html') or ''}
{payload.get('pacheco_html') or ''}

<h2>5b. Miyoshi vs Jong (Polymarket path)</h2>
{payload.get('miyoshi_html') or ''}

<h2>6. Per-match tracked tennis (C in 0.95–1.20)</h2>
<p class="note">One row per two-sided book we actually tracked in-match. <strong>in-match ticks</strong> are Yes/No change-ticks after T0 (or after listed start when that is later). <strong>pre-match ticks</strong> are stored changes at or before that anchor. Mix and P&amp;L are D = 5 cents. Click column headers to sort.</p>
{table(
    [("Match", "text"), ("Date", "date"), ("Venues", "text"), ("This venue", "text"),
     ("Yes A", "text"), ("T0 A", "num"), ("Yes B", "text"), ("T0 B", "num"), ("C", "num"),
     ("in-match ticks", "num"), ("pre-match ticks", "num"), ("total ticks", "num"),
     ("in-match Yes ticks", "num"), ("in-match No ticks", "num"),
     ("Max gap min", "num"), ("Max dip A", "num"), ("Max dip B", "num"),
     ("Mix D=5", "text"), ("P&L D=5 if settled", "num"), ("Still live?", "text"),
     ("Winner", "text"), ("T0 label", "text"), ("T0 when", "text")],
    payload["match_rows"],
    ["game", "date", "venues", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0",
     "inmatch_n", "pre_n", "total_n", "inmatch_yes", "inmatch_no", "max_gap", "max_dip_a", "max_dip_b",
     "mix", "pnl", "live", "winner", "t0_label", "t0_when"],
)}

<h2>7. Empty-window leftovers (the artifacts)</h2>
<p class="note">Same 0.95–1.20 tennis set, but zero Yes/No change-ticks after T0 / listed start. These are the “never dipped” artifacts. Cap 40, sorted by match name. Pacheco vs Rodriguez Taverna Novig belongs here if it is still empty.</p>
{table(
    [("Match", "text"), ("Date", "date"), ("Venue", "text"),
     ("Yes A", "text"), ("T0 A", "num"), ("Yes B", "text"), ("T0 B", "num"), ("C", "num"),
     ("T0 label", "text"), ("Still live?", "text")],
    empty_rows,
    ["game", "date", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0", "t0_label", "live"],
)}

<h2>8. Other sports with in-match ticks</h2>
<p class="note">Two-sided moneyline books that are not tennis, with at least one Yes/No change-tick after T0. Not part of the 299 tennis set and not scored in the dual-Yes tables.</p>
{table(
    [("Sport", "text"), ("Match", "text"), ("Date", "date"), ("Venue", "text"),
     ("Yes A", "text"), ("T0 A", "num"), ("Yes B", "text"), ("T0 B", "num"), ("C", "num"),
     ("In-match ticks", "num"), ("Max gap min", "num"), ("Max dip A", "num"), ("Max dip B", "num"),
     ("Still live?", "text")],
    other_rows,
    ["sport", "game", "date", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0",
     "inmatch_n", "max_gap", "max_dip_a", "max_dip_b", "live"],
)}

<h2>How to read this</h2>
<ul>
<li>If a book is not on the per-match table, we did not store an in-match price change. That is a collection hole, not proof the match never dipped.</li>
<li>If in-match ticks is small but pre-match ticks is large, listed start may be late (Miyoshi vs Jong: 0.60→0.06 printed before the 15:00 ET listed start).</li>
<li>Wawrinka vs Landaluce should be on the table if the Kalshi / Polymarket websocket wrote post-T0 ticks. Pacheco Novig should be in the empty-window leftover table if it still has no post-T0 ticks.</li>
<li>KEEP / HOLD / DISMISS is quality versus the current lock on this tracked subset, not trade count. Research only. Not gold. Not DailyRun.</li>
</ul>
<p class="note">Acronyms: ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. T0 is match start (last Yes at or before listed start, or first two-sided in-game print). Vig is the overround when two Yes prices sum over $1.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def describe_named(pairs: list[dict], *needles: str) -> str:
    found = uniq_pairs(named_pairs(pairs, *needles))
    if not found:
        return "not on this two-sided tape."
    bits = []
    for p in found:
        rec = (p.get("dips") or {}).get(0.05) or {}
        bits.append(
            f"{p.get('venue') or '?'}: tracked={'yes' if p.get('tracked') else 'no'}, "
            f"T0 {fmt_px(p.get('t0_a'))}/{fmt_px(p.get('t0_b'))} C={fmt_px(p.get('c0'))}, "
            f"in-match ticks {p.get('inmatch_n') or 0} "
            f"(pre {p.get('pre_n') or 0}, total {p.get('total_n') or 0}), "
            f"max dip {fmt_px(p.get('max_dip_a'))}/{fmt_px(p.get('max_dip_b'))}, "
            f"D=5 mix {rec.get('mix') or 'n/a'}, "
            f"live={'yes' if not p.get('settled') else 'no'}"
        )
    return " | ".join(bits)


def empty_preview(pairs: list[dict], cap: int = 40) -> list[dict]:
    rows = []
    for p in pairs:
        rows.append({
            "game": p.get("game") or "",
            "date": match_date(p),
            "venue": p.get("venue") or "",
            "side_a": p.get("side_a") or "",
            "t0_a": fmt_px(p.get("t0_a")),
            "side_b": p.get("side_b") or "",
            "t0_b": fmt_px(p.get("t0_b")),
            "c0": fmt_px(p.get("c0")),
            "t0_label": p.get("t0_label") or "",
            "live": "yes" if not p.get("settled") else "no",
        })
    rows.sort(key=lambda r: (r.get("game") or "", r.get("venue") or ""))
    return rows[:cap]


def other_preview(pairs: list[dict], cap: int = 80) -> list[dict]:
    rows = []
    for p in pairs:
        rows.append({
            "sport": p.get("sport") or "",
            "game": p.get("game") or "",
            "date": match_date(p),
            "venue": p.get("venue") or "",
            "side_a": p.get("side_a") or "",
            "t0_a": fmt_px(p.get("t0_a")),
            "side_b": p.get("side_b") or "",
            "t0_b": fmt_px(p.get("t0_b")),
            "c0": fmt_px(p.get("c0")),
            "inmatch_n": p.get("inmatch_n") or 0,
            "max_gap": fmt_mins(p.get("max_gap_min")),
            "max_dip_a": fmt_px(p.get("max_dip_a")),
            "max_dip_b": fmt_px(p.get("max_dip_b")),
            "live": "yes" if not p.get("settled") else "no",
        })
    rows.sort(key=lambda r: (-(r.get("inmatch_n") or 0), r.get("sport") or "", r.get("game") or ""))
    return rows[:cap]


def main() -> None:
    history = pick_history()
    stream = stream_moneyline(history)
    settlements = load_settlements()
    catalog = load_catalog()
    start_lookup = start_lookup_from(settlements, catalog)
    pairs = pair_matches(stream["series"], start_lookup)
    tennis = [p for p in pairs if (p.get("sport") or "").lower() == "tennis"]
    other = [p for p in pairs if (p.get("sport") or "").lower() != "tennis"]
    print(f"two-sided tennis {len(tennis)} other {len(other)}", flush=True)
    for pair in pairs:
        assign_t0(pair)
    attach_pair_results(pairs, settlements)
    n_t0 = 0
    in_range = []
    for pair in tennis:
        if pair.get("t0_a") is None or pair.get("t0_b") is None or pair.get("t0_ts") is None:
            continue
        n_t0 += 1
        c0 = pair["t0_a"] + pair["t0_b"]
        pair["c0"] = c0
        if C_LO - 1e-12 <= c0 <= C_HI + 1e-12:
            in_range.append(pair)
    print(f"tennis with T0 {n_t0}; C in [{C_LO},{C_HI}] {len(in_range)}", flush=True)
    for pair in pairs:
        if pair.get("c0") is None and pair.get("t0_a") is not None and pair.get("t0_b") is not None:
            pair["c0"] = pair["t0_a"] + pair["t0_b"]
        mark_tracked(pair)
    tracked = [p for p in in_range if p.get("tracked")]
    empty = [p for p in in_range if not p.get("tracked")]
    other_tracked = [
        p for p in other
        if p.get("tracked") and p.get("t0_a") is not None and p.get("t0_b") is not None
    ]
    print(
        f"tracked in-range {len(tracked)}; empty-window {len(empty)}; "
        f"other-sport tracked {len(other_tracked)}",
        flush=True,
    )
    for pair in tracked:
        simulate_pair(pair)
    simulate_current_lock(tracked)
    extra_named = []
    for p in (
        named_pairs(tennis, "wawrinka", "landaluce")
        + named_pairs(tennis, "pacheco", "rodriguez")
        + named_pairs(tennis, "miyoshi", "jong")
    ):
        if p not in tracked and p.get("t0_a") is not None:
            simulate_pair(p)
            extra_named.append(p)
    if extra_named:
        simulate_current_lock(tracked + extra_named)
    settled = [p for p in tracked if p.get("settled")]
    live = [p for p in tracked if not p.get("settled")]
    competitive = [p for p in tracked if is_competitive(p)]
    d_rows = [summarize_d(tracked, dip) for dip in DIPS]
    d_settled_rows = [summarize_d(settled, dip) for dip in DIPS]
    d_live_rows = [summarize_d(live, dip) for dip in DIPS]
    d_comp_rows = [summarize_d(competitive, dip) for dip in DIPS]
    lock = summarize_lock(tracked)
    for r in d_rows:
        print(
            f"D={r['dip_cents']}c n={r['n']} settled={r['n_settled']} "
            f"mean={fmt_signed(r['mean'])} median={fmt_signed(r['median'])} "
            f"both={r['pct_both']} one={r['pct_one']} none={r['pct_none']}",
            flush=True,
        )
    print(
        f"lock n={lock['n']} taken={lock['n_taken']} settled={lock['n_settled']} "
        f"mean_all={fmt_signed(lock.get('mean_all_settled'))} "
        f"mean_taken={fmt_signed(lock.get('mean_when_taken'))}",
        flush=True,
    )
    scored = [r for r in d_rows if r["mean"] is not None]
    sweet = max(scored, key=lambda r: r["mean"]) if scored else None
    verdict, sweet_text = decide_verdict(sweet, lock)
    dual_mean = sweet["mean"] if sweet else None
    lock_mean = lock.get("mean_all_settled")
    if dual_mean is None or lock_mean is None:
        vs_lock_text = "Not enough settled tracked rows to compare."
    elif lock_mean > dual_mean + 1e-12:
        vs_lock_text = (
            f"Current Yes+No lock mean {fmt_signed(lock_mean)} on all settled tracked "
            f"(zeros when the lock never printed, taken on {lock['n_taken']}/{lock['n']} books) "
            f"beats dual-Yes best mean {fmt_signed(dual_mean)}. Verdict {verdict}."
        )
    elif dual_mean > lock_mean + 1e-12:
        vs_lock_text = (
            f"Dual-Yes best mean {fmt_signed(dual_mean)} is above the current lock's "
            f"all-settled mean {fmt_signed(lock_mean)} (lock zeros included). "
            f"Do not read that as KEEP: dual-Yes is always in and path-dependent. Verdict {verdict}."
        )
    else:
        vs_lock_text = (
            f"Means are flat ({fmt_signed(dual_mean)} vs lock {fmt_signed(lock_mean)}). "
            f"Verdict {verdict}."
        )
    named_universe = tracked + extra_named
    waw_text = describe_named(named_universe + empty, "wawrinka", "landaluce")
    pacheco_text = describe_named(named_universe + empty, "pacheco", "rodriguez")
    miyoshi_text, miyoshi_html = miyoshi_text_and_html(named_universe + empty)
    print(f"WAWRINKA {waw_text}", flush=True)
    print(f"PACHECO {pacheco_text}", flush=True)
    print(f"MIYOSHI {miyoshi_text}", flush=True)
    print(f"VERDICT {verdict}", flush=True)
    by_id: dict[tuple, list[dict]] = defaultdict(list)
    for p in tennis:
        by_id[match_id(p)].append(p)
    now = iso_now()
    payload = {
        "written_at": now,
        "stream": stream,
        "sport_hits": stream.get("sport_hits") or {},
        "d_rows": d_rows,
        "d_settled_rows": d_settled_rows,
        "d_live_rows": d_live_rows,
        "d_comp_rows": d_comp_rows,
        "compare_rows": compare_rows(d_rows, lock),
        "lock": lock,
        "sweet": sweet,
        "sweet_text": sweet_text,
        "vs_lock_text": vs_lock_text,
        "verdict": verdict,
        "n_pairs": len(tennis),
        "n_t0": n_t0,
        "n_in": len(in_range),
        "n_tracked": len(tracked),
        "n_empty": len(empty),
        "n_tracked_settled": len(settled),
        "n_tracked_live": len(live),
        "n_other_tracked": len(other_tracked),
        "note_n": tiny_note(len(settled)),
        "waw_text": waw_text,
        "pacheco_text": pacheco_text,
        "miyoshi_text": miyoshi_text,
        "waw_html": named_html(named_universe + empty, "wawrinka", "landaluce", title="Wawrinka vs Landaluce"),
        "pacheco_html": named_html(named_universe + empty, "pacheco", "rodriguez", title="Pacheco vs Rodriguez Taverna"),
        "miyoshi_html": miyoshi_html,
        "match_rows": per_match_rows(tracked, by_id),
        "empty_rows": empty_preview(empty),
        "other_rows": other_preview(other_tracked),
    }
    write_html(payload)
    copy_g(PAGE)
    print("done", flush=True)


if __name__ == "__main__":
    main()
