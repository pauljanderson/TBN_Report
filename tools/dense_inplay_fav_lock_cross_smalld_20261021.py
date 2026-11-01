"""Tennis A/B/C vs extra-Yes-on-dip on the frozen dense in-play book.

Research only. Reads price_memory (archive + dated shards) and official
settlements. Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Not gold. Not DailyRun.
Does not overwrite dense_inplay_yes_dip_20261021.html or
tennis_dual_yes_dip_no_20261021.html.
"""
from __future__ import annotations

import html as html_mod
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from dense_inplay_yes_dip_20261021 import (
    ABSORB,
    C_HI,
    C_LO,
    DIPS,
    TICK_BAR,
    assign_actual_t0,
    attach_pair_results,
    delta_money,
    esc,
    extra_fill_text,
    extras_payout,
    first_dip_yes,
    iso_now,
    mark_inplay,
    match_date,
    money_cell,
    na_book,
    pair_matches,
    signed_money,
    simulate_yes_dip,
    stream_tennis,
    summarize_hold,
    summarize_yes,
)
from inmatch_vol_hedge_20261021 import first_after
from odds_cross_no_roi_60_70_20261020 import copy_g, venue_fee
from odds_cross_winrate_20261020 import pct, table, tiny_note
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from prediction_paths import DRIVE_STAMP as STAMP
from tennis_decade_at_start_20261020 import start_lookup_from
from tennis_dual_yes_dip_no_20261021 import (
    et_iso,
    fmt_px,
    fmt_signed,
    last_name,
    mean,
    median,
    named_pairs,
    simulate_current_lock,
    summarize_lock,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "dense_inplay_fav_lock_cross_smalld_20261021.html"
ORIGINAL_PAGE = STAMP / "dense_inplay_yes_dip_20261021.html"
ORIGINAL_N = 182
ORIGINAL_SETTLED = 119
LOCK_DS = DIPS
SMALL_DIPS = (0.01, 0.02, 0.03, 0.04)
CROSS = 0.50

ASKED = (
    "Run the ABC HTML on the same dense in-play tennis universe as extra-Yes-on-dip. "
    "ORIGINAL control: at T0 buy BOTH Yes, then extra Yes on a player at the first T0−D print. "
    "D = 5/10/15/20/25. That D is a DIP from that player's T0 Yes, NOT a lock profit. "
    "A — favorite only then complementary lock. D lock profit in {0.05, 0.10, 0.15, 0.20, 0.25}. "
    "T0: buy ONLY the higher Yes (favorite). Hassan example: Hassan 0.65, do not buy Rodenas 0.36. "
    "Then first complementary ticket (underdog Yes OR favorite No — same 2-player moneyline lock) "
    "at cash ≤ 1 − favorite_fill − D. Use that match's actual T0 favorite fill, not a global 0.30. "
    "Do NOT buy a second favorite-Yes at the target (that is not a lock). If no hedge: hold the "
    "single favorite to settlement. Stop extras at first 5c/95c absorb, same as original. "
    "B — both at T0, underdog 50c cross, then lock original favorite. D lock profit 5/10/15/20/25. "
    "T0: buy BOTH Yes. If T0 underdog Yes prints strictly > 0.50 after T0 before absorb: buy 1 more "
    "of THAT player at the first such print (optimistic fill-at-print). Also compute a sensitivity "
    "using the next tick after the cross (Smith spiked 0.52 then 0.47). Primary = first print > 0.50. "
    "Show both on Smith; summary table uses first print > 0.50. Then buy 1 more original-favorite Yes "
    "the first time it prints at/below 1 − C − D after the cross, before absorb. No cross: stop at "
    "T0 both-Yes. Cross but no dip hedge: T0 both + extra new-favorite. "
    "C — original extra-Yes-on-dip at D in {0.01, 0.02, 0.03, 0.04}. Same first-dip primary (not ladder) "
    "as original. Also report on the same universe: current lock (first same-player Yes+No ≤ 0.95, "
    "sit-out 0), T0-only both-Yes, T0-favorite-only (buy only the higher Yes, no hedge). "
    "Worked examples, verify on tape, do not invent: Rodenas vs Hassan 2026-10-19 Polymarket; "
    "Smith vs Purcell Polymarket."
)

PLAIN = (
    "A Yes is a dollar from 0 to 1, also an implied chance: 0.65 means that named tennis player "
    "is listed at 65 percent to win (moneyline: who wins the match). T0 is the open used here — "
    "the last two-sided Yes at or before a trusted actual start, else the first time both Yes "
    "prices sit between 10 and 90 cents. At T0, buying Yes on both players always pays exactly $1 "
    "because only one can win. Cost C is those two T0 Yes prices added together. If C is $1.01 you "
    "are already down a penny if you never trade — that gap is the vig (the house overround), not "
    "a bug. A lock is a book that pays $1 against a known bill no matter who wins: either one Yes "
    "on each player, or Yes+No on the same player. Original extra-Yes-on-dip is NOT a lock. It "
    "buys another Yes on the name whose price is falling, usually the player who is losing. "
    "Strategy A starts with only the favorite (the higher T0 Yes), then tries to buy the cheapest "
    "complement that turns that ticket into a lock at a D-cent profit. Strategy B starts with both "
    "Yes, waits for the T0 underdog to print strictly above 50 cents, buys one more of that name, "
    "then tries to lock by buying one more of the original favorite cheap. Strategy C is the "
    "original extra-Yes-on-dip idea with tiny 1–4 cent dips. "
    "Primary P&L is without fees. Fills are optimistic at the printed Yes ask. Same-day tennis "
    "contracts, so annualized rate of return (Ann ROR) is omitted — we do not have days held. "
    "The whole October 2026 tape is out-of-sample (OOS): every T0 is on or after 2024-01-01. There "
    "is no in-sample (IS) row. Research only. Not gold. Not DailyRun."
)


def pair_key(pair: dict) -> tuple[str, str]:
    return (pair.get("game") or "", pair.get("venue") or "")


def freeze_keys_from_original_html() -> list[tuple[str, str]]:
    if not ORIGINAL_PAGE.is_file():
        raise FileNotFoundError(f"missing original dense HTML {ORIGINAL_PAGE}")
    text = ORIGINAL_PAGE.read_text(encoding="utf-8")
    start = text.find("<h2>7. Per-match dense tennis</h2>")
    end = text.find("<h2>8. Near-miss books", start)
    if start < 0 or end < 0:
        raise ValueError("could not find per-match dense table in original HTML")
    chunk = text[start:end]
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in re.finditer(r"<tr><td>(.*?)</td><td>.*?</td><td>(.*?)</td>", chunk):
        game = html_mod.unescape(match.group(1))
        venue = html_mod.unescape(match.group(2))
        key = (game, venue)
        if not game or not venue or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def fav_letter(pair: dict) -> str:
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    if t0a is None or t0b is None:
        return "a"
    if t0b > t0a + 1e-12:
        return "b"
    return "a"


def other_letter(letter: str) -> str:
    return "b" if letter == "a" else "a"


def side_name(pair: dict, letter: str) -> str:
    return pair.get("side_a") if letter == "a" else pair.get("side_b")


def ticks_of(pair: dict, letter: str, pay: str) -> list[tuple[int, float]]:
    key = f"{pay}_{letter}"
    return pair.get(key) or []


def fee_of(venue: str, price: float) -> float:
    got = venue_fee(venue, price)
    return float(got) if got is not None else 0.0


def fees_for(venue: str, prices: list[float]) -> float:
    return sum(fee_of(venue, px) for px in prices)


def first_complementary(
    pair: dict,
    fav: str,
    target: float,
    lo: int,
    hi: int,
) -> dict | None:
    if target is None or target < -1e-12:
        return None
    dog = other_letter(fav)
    events: list[tuple[int, float, str, str, str]] = []
    for ts, px in ticks_of(pair, dog, "yes"):
        if ts <= lo or ts > hi:
            continue
        if px <= ABSORB + 1e-12:
            continue
        if px <= target + 1e-12:
            events.append((ts, px, "underdog_yes", dog, "yes"))
    for ts, px in ticks_of(pair, fav, "no"):
        if ts <= lo or ts > hi:
            continue
        if px <= target + 1e-12:
            events.append((ts, px, "favorite_no", fav, "no"))
    if not events:
        return None
    events.sort(key=lambda row: (row[0], row[1], 0 if row[2] == "underdog_yes" else 1))
    ts, px, kind, side, pay = events[0]
    return {
        "ts": ts,
        "px": px,
        "kind": kind,
        "side": side,
        "pay": pay,
        "target": target,
    }


def first_yes_at_or_below(
    ticks: list[tuple[int, float]],
    after_ts: int,
    hi: int,
    target: float,
) -> dict | None:
    if target is None or target < -1e-12:
        return None
    for ts, px in ticks:
        if ts <= after_ts or ts > hi:
            continue
        if px <= ABSORB + 1e-12:
            continue
        if px <= target + 1e-12:
            return {"ts": ts, "px": px, "target": target}
    return None


def first_cross_yes(
    ticks: list[tuple[int, float]],
    lo: int,
    hi: int,
    bar: float = CROSS,
) -> dict | None:
    for ts, px in ticks:
        if ts <= lo or ts > hi:
            continue
        if px <= ABSORB + 1e-12 or px >= 0.95 - 1e-12:
            continue
        if px > bar + 1e-12:
            nxt = first_after(ticks, ts)
            return {
                "ts": ts,
                "px": px,
                "next_ts": nxt[0] if nxt else None,
                "next_px": nxt[1] if nxt else None,
            }
    return None


def assign_favorite(pair: dict) -> None:
    fav = fav_letter(pair)
    dog = other_letter(fav)
    pair["fav"] = fav
    pair["dog"] = dog
    pair["t0_fav"] = pair.get("t0_a") if fav == "a" else pair.get("t0_b")
    pair["t0_dog"] = pair.get("t0_a") if dog == "a" else pair.get("t0_b")
    pair["fav_name"] = side_name(pair, fav) or ""
    pair["dog_name"] = side_name(pair, dog) or ""


def simulate_t0_favorite_only(pair: dict) -> None:
    assign_favorite(pair)
    fav = pair["fav"]
    cost = pair.get("t0_fav")
    pair["fav_cost"] = cost
    pair["fav_pnl"] = None
    pair["fav_payout"] = None
    winner = pair.get("winner")
    if cost is None:
        return
    if pair.get("settled") and winner in ("a", "b"):
        paid = 1.0 if winner == fav else 0.0
        pair["fav_payout"] = paid
        pair["fav_pnl"] = paid - cost


def simulate_a(pair: dict) -> None:
    pair["a_locks"] = {}
    assign_favorite(pair)
    fav = pair.get("fav")
    t0_fav = pair.get("t0_fav")
    lo, hi = pair.get("lo"), pair.get("hi")
    if fav is None or t0_fav is None or lo is None or hi is None:
        return
    winner = pair.get("winner")
    settled = bool(pair.get("settled") and winner in ("a", "b"))
    venue = pair.get("venue") or ""
    for dip in LOCK_DS:
        target = 1.0 - float(t0_fav) - dip
        hedge = first_complementary(pair, fav, target, lo, hi)
        cost = float(t0_fav)
        fills = [float(t0_fav)]
        if hedge:
            cost += hedge["px"]
            fills.append(hedge["px"])
        rec = {
            "dip": dip,
            "target": target,
            "hedge": hedge,
            "hedged": hedge is not None,
            "cost": cost,
            "fees": fees_for(venue, fills),
            "pnl": None,
            "pnl_fee": None,
            "payout": None,
        }
        if settled:
            if hedge is not None:
                paid = 1.0
            else:
                paid = 1.0 if winner == fav else 0.0
            rec["payout"] = paid
            rec["pnl"] = paid - cost
            rec["pnl_fee"] = paid - cost - rec["fees"]
        pair["a_locks"][dip] = rec


def simulate_b_variant(
    pair: dict,
    dip: float,
    cross: dict | None,
    fill_px: float | None,
    fill_ts: int | None,
    label: str,
) -> dict:
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    c0 = pair.get("c0")
    lo, hi = pair.get("lo"), pair.get("hi")
    fav = pair.get("fav")
    dog = pair.get("dog")
    venue = pair.get("venue") or ""
    winner = pair.get("winner")
    settled = bool(pair.get("settled") and winner in ("a", "b"))
    rec = {
        "dip": dip,
        "label": label,
        "crossed": False,
        "cross": cross,
        "cross_px": None,
        "cross_ts": None,
        "target": None,
        "fav_extra": None,
        "lock_filled": False,
        "n_extra_dog": 0,
        "n_extra_fav": 0,
        "mix": "t0 both only",
        "cost": c0,
        "fees": fees_for(venue, [t0a, t0b] if t0a is not None and t0b is not None else []),
        "pnl": None,
        "pnl_fee": None,
        "payout": None,
    }
    if t0a is None or t0b is None or c0 is None or lo is None or hi is None:
        return rec
    n_a = n_b = 0
    fills = [float(t0a), float(t0b)]
    cost = float(c0)
    if cross is not None and fill_px is not None and fill_ts is not None:
        if ABSORB + 1e-12 < fill_px < 0.95 - 1e-12:
            rec["crossed"] = True
            rec["cross_px"] = fill_px
            rec["cross_ts"] = fill_ts
            rec["n_extra_dog"] = 1
            rec["mix"] = "cross, no fav hedge"
            cost += fill_px
            fills.append(fill_px)
            if dog == "a":
                n_a += 1
            else:
                n_b += 1
            target = 1.0 - float(fill_px) - dip
            rec["target"] = target
            fav_ticks = ticks_of(pair, fav, "yes")
            extra = first_yes_at_or_below(fav_ticks, fill_ts, hi, target)
            if extra:
                rec["fav_extra"] = extra
                rec["lock_filled"] = True
                rec["n_extra_fav"] = 1
                rec["mix"] = "cross + fav lock"
                cost += extra["px"]
                fills.append(extra["px"])
                if fav == "a":
                    n_a += 1
                else:
                    n_b += 1
    rec["cost"] = cost
    rec["fees"] = fees_for(venue, [px for px in fills if px is not None])
    if settled:
        paid = extras_payout(winner, n_a, n_b)
        rec["payout"] = paid
        rec["pnl"] = paid - cost
        rec["pnl_fee"] = paid - cost - rec["fees"]
    return rec


def simulate_b(pair: dict) -> None:
    pair["b_locks"] = {}
    pair["b_next"] = {}
    assign_favorite(pair)
    dog = pair.get("dog")
    lo, hi = pair.get("lo"), pair.get("hi")
    cross = None
    if dog and lo is not None and hi is not None:
        cross = first_cross_yes(ticks_of(pair, dog, "yes"), lo, hi)
    pair["b_cross"] = cross
    for dip in LOCK_DS:
        primary_px = cross["px"] if cross else None
        primary_ts = cross["ts"] if cross else None
        pair["b_locks"][dip] = simulate_b_variant(
            pair, dip, cross, primary_px, primary_ts, "first print > 0.50"
        )
        next_px = cross.get("next_px") if cross else None
        next_ts = cross.get("next_ts") if cross else None
        if next_px is None or next_ts is None:
            pair["b_next"][dip] = dict(pair["b_locks"][dip])
            pair["b_next"][dip]["label"] = "next tick after cross (same as primary)"
        else:
            pair["b_next"][dip] = simulate_b_variant(
                pair, dip, cross, next_px, next_ts, "next tick after cross"
            )


def simulate_c(pair: dict) -> None:
    pair["small_dips"] = {}
    t0a, t0b, t0_ts = pair.get("t0_a"), pair.get("t0_b"), pair.get("t0_ts")
    lo, hi = pair.get("lo"), pair.get("hi")
    if t0a is None or t0b is None or t0_ts is None or lo is None or hi is None:
        return
    c0 = t0a + t0b
    winner = pair.get("winner")
    settled = bool(pair.get("settled") and winner in ("a", "b"))
    venue = pair.get("venue") or ""
    for dip in SMALL_DIPS:
        ha = first_dip_yes(pair.get("yes_a") or [], t0a, lo, hi, dip)
        hb = first_dip_yes(pair.get("yes_b") or [], t0b, lo, hi, dip)
        n_extra = int(ha is not None) + int(hb is not None)
        cost = c0
        fills = [float(t0a), float(t0b)]
        if ha:
            cost += ha["yes_print"]
            fills.append(ha["yes_print"])
        if hb:
            cost += hb["yes_print"]
            fills.append(hb["yes_print"])
        rec = {
            "dip": dip,
            "extra_a": ha,
            "extra_b": hb,
            "n_extra": n_extra,
            "mix": {0: "none", 1: "one extra", 2: "both extra"}[n_extra],
            "cost": cost,
            "fees": fees_for(venue, fills),
            "pnl": None,
            "pnl_fee": None,
            "payout": None,
        }
        if settled:
            paid = extras_payout(winner, int(ha is not None), int(hb is not None))
            rec["payout"] = paid
            rec["pnl"] = paid - cost
            rec["pnl_fee"] = paid - cost - rec["fees"]
        pair["small_dips"][dip] = rec


def summarize_fav(pairs: list[dict]) -> dict:
    settled = [p for p in pairs if p.get("settled") and p.get("fav_pnl") is not None]
    pnls = [p["fav_pnl"] for p in settled]
    costs = [p["fav_cost"] for p in settled if p.get("fav_cost") is not None]
    wins = sum(1 for x in pnls if x > 1e-12)
    return {
        "kind": "t0_fav",
        "n": len(pairs),
        "n_settled": len(settled),
        "mean": mean(pnls),
        "median": median(pnls),
        "win_pct": pct(wins, len(pnls)),
        "mean_cost": mean(costs),
        "pct_hedged": "",
        "pct_crossed": "",
        "pct_lock": "",
        "note": tiny_note(len(settled)),
    }


def summarize_a(pairs: list[dict], dip: float) -> dict:
    rows = [p for p in pairs if dip in (p.get("a_locks") or {})]
    recs = [p["a_locks"][dip] for p in rows]
    settled = [p for p in rows if p.get("settled") and p["a_locks"][dip].get("pnl") is not None]
    pnls = [p["a_locks"][dip]["pnl"] for p in settled]
    costs = [p["a_locks"][dip]["cost"] for p in settled]
    fee_pnls = [p["a_locks"][dip]["pnl_fee"] for p in settled if p["a_locks"][dip].get("pnl_fee") is not None]
    n_hedge = sum(1 for r in recs if r.get("hedged"))
    wins = sum(1 for x in pnls if x > 1e-12)
    return {
        "kind": "A",
        "dip": dip,
        "dip_cents": int(round(dip * 100)),
        "n": len(rows),
        "n_settled": len(settled),
        "mean": mean(pnls),
        "median": median(pnls),
        "win_pct": pct(wins, len(pnls)),
        "mean_cost": mean(costs),
        "mean_fee": mean(fee_pnls),
        "pct_hedged": pct(n_hedge, len(rows)),
        "pct_crossed": "",
        "pct_lock": pct(n_hedge, len(rows)),
        "n_hedged": n_hedge,
        "note": tiny_note(len(settled)),
    }


def summarize_b(pairs: list[dict], dip: float, bag: str = "b_locks") -> dict:
    rows = [p for p in pairs if dip in (p.get(bag) or {})]
    recs = [p[bag][dip] for p in rows]
    settled = [p for p in rows if p.get("settled") and p[bag][dip].get("pnl") is not None]
    pnls = [p[bag][dip]["pnl"] for p in settled]
    costs = [p[bag][dip]["cost"] for p in settled]
    fee_pnls = [p[bag][dip]["pnl_fee"] for p in settled if p[bag][dip].get("pnl_fee") is not None]
    n_cross = sum(1 for r in recs if r.get("crossed"))
    n_lock = sum(1 for r in recs if r.get("lock_filled"))
    wins = sum(1 for x in pnls if x > 1e-12)
    return {
        "kind": "B" if bag == "b_locks" else "B_next",
        "dip": dip,
        "dip_cents": int(round(dip * 100)),
        "n": len(rows),
        "n_settled": len(settled),
        "mean": mean(pnls),
        "median": median(pnls),
        "win_pct": pct(wins, len(pnls)),
        "mean_cost": mean(costs),
        "mean_fee": mean(fee_pnls),
        "pct_hedged": "",
        "pct_crossed": pct(n_cross, len(rows)),
        "pct_lock": pct(n_lock, len(rows)),
        "n_crossed": n_cross,
        "n_lock": n_lock,
        "note": tiny_note(len(settled)),
    }


def summarize_c(pairs: list[dict], dip: float) -> dict:
    rows = [p for p in pairs if dip in (p.get("small_dips") or {})]
    recs = [p["small_dips"][dip] for p in rows]
    settled = [p for p in rows if p.get("settled") and p["small_dips"][dip].get("pnl") is not None]
    pnls = [p["small_dips"][dip]["pnl"] for p in settled]
    costs = [p["small_dips"][dip]["cost"] for p in settled]
    fee_pnls = [p["small_dips"][dip]["pnl_fee"] for p in settled if p["small_dips"][dip].get("pnl_fee") is not None]
    n_both = sum(1 for r in recs if r.get("mix") == "both extra")
    n_one = sum(1 for r in recs if r.get("mix") == "one extra")
    n_none = sum(1 for r in recs if r.get("mix") == "none")
    wins = sum(1 for x in pnls if x > 1e-12)
    return {
        "kind": "C",
        "dip": dip,
        "dip_cents": int(round(dip * 100)),
        "n": len(rows),
        "n_settled": len(settled),
        "mean": mean(pnls),
        "median": median(pnls),
        "win_pct": pct(wins, len(pnls)),
        "mean_cost": mean(costs),
        "mean_fee": mean(fee_pnls),
        "pct_hedged": "",
        "pct_crossed": "",
        "pct_lock": "",
        "pct_both": pct(n_both, len(rows)),
        "pct_one": pct(n_one, len(rows)),
        "pct_none": pct(n_none, len(rows)),
        "n_both": n_both,
        "n_one": n_one,
        "n_none": n_none,
        "note": tiny_note(len(settled)),
    }


def summarize_orig_fees(pairs: list[dict], dip: float) -> float | None:
    pnls = []
    for p in pairs:
        rec = (p.get("yes_dips") or {}).get(dip)
        if not rec or rec.get("pnl") is None or not p.get("settled"):
            continue
        t0a, t0b = p.get("t0_a"), p.get("t0_b")
        fills = []
        if t0a is not None:
            fills.append(t0a)
        if t0b is not None:
            fills.append(t0b)
        if rec.get("extra_a"):
            fills.append(rec["extra_a"]["yes_print"])
        if rec.get("extra_b"):
            fills.append(rec["extra_b"]["yes_print"])
        pnls.append(rec["pnl"] - fees_for(p.get("venue") or "", fills))
    return mean(pnls)


def a_fill_text(pair: dict, rec: dict | None) -> str:
    if not rec:
        return ""
    hedge = rec.get("hedge")
    if not hedge:
        return "no hedge"
    name = last_name(side_name(pair, hedge["side"]) or "") or hedge["side"]
    if hedge["kind"] == "underdog_yes":
        return f"Yes {name} {fmt_px(hedge['px'])} @ {et_iso(hedge['ts'])}"
    return f"No {name} {fmt_px(hedge['px'])} @ {et_iso(hedge['ts'])}"


def b_fill_text(pair: dict, rec: dict | None) -> str:
    if not rec:
        return ""
    bits = []
    if rec.get("crossed"):
        bits.append(
            f"cross {last_name(pair.get('dog_name') or '')} {fmt_px(rec.get('cross_px'))} "
            f"@ {et_iso(rec.get('cross_ts'))}"
        )
    extra = rec.get("fav_extra")
    if extra:
        bits.append(
            f"fav Yes {last_name(pair.get('fav_name') or '')} {fmt_px(extra.get('px'))} "
            f"@ {et_iso(extra.get('ts'))}"
        )
    if not bits:
        return rec.get("mix") or "t0 both only"
    return "; ".join(bits)


def lock_pnl_of(pair: dict) -> float | None:
    if not pair.get("settled"):
        return None
    lock = pair.get("cur_lock") or {}
    if lock.get("taken") and lock.get("pnl") is not None:
        return lock["pnl"]
    return 0.0


def pick_named(pairs: list[dict], *needles: str, venue: str = "polymarket") -> dict | None:
    found = named_pairs(pairs, *needles)
    if not found:
        return None
    want = venue.lower()
    for pair in found:
        if str(pair.get("venue") or "").lower() == want:
            return pair
    return found[0]


def close_enough(got, want, tol: float = 0.015) -> bool:
    if got is None or want is None:
        return False
    try:
        return abs(float(got) - float(want)) <= tol
    except (TypeError, ValueError):
        return False


def decide_verdict(
    a_rows: list[dict],
    b_rows: list[dict],
    c_rows: list[dict],
    orig_rows: list[dict],
    hold: dict,
    fav: dict,
    lock: dict,
) -> tuple[str, str]:
    def by_dip(rows, dip):
        return next((r for r in rows if abs(r.get("dip", -1) - dip) < 1e-12), None)

    a5 = by_dip(a_rows, 0.05)
    b5 = by_dip(b_rows, 0.05)
    c1 = by_dip(c_rows, 0.01)
    o5 = by_dip(orig_rows, 0.05)
    lock_mean = lock.get("mean_all_settled")
    fav_mean = fav.get("mean")
    hold_mean = hold.get("mean")
    a_mean = a5.get("mean") if a5 else None
    b_mean = b5.get("mean") if b5 else None
    c_mean = c1.get("mean") if c1 else None
    o_mean = o5.get("mean") if o5 else None
    scored = []
    for rec in a_rows:
        if rec.get("mean") is not None:
            scored.append((f"A D={rec['dip_cents']}¢ lock", rec["mean"]))
    for rec in b_rows:
        if rec.get("mean") is not None:
            scored.append((f"B D={rec['dip_cents']}¢ lock", rec["mean"]))
    for rec in c_rows:
        if rec.get("mean") is not None:
            scored.append((f"C D={rec['dip_cents']}¢ extra Yes", rec["mean"]))
    for rec in orig_rows:
        if rec.get("mean") is not None:
            scored.append((f"original D={rec['dip_cents']}¢ extra Yes", rec["mean"]))
    if not scored:
        return (
            "HOLD",
            "No settled dense books to score. HOLD. Research only. Not gold. Not DailyRun.",
        )
    best_name, best_mean = max(scored, key=lambda row: row[1])
    a_le0 = a_mean is not None and a_mean <= 1e-12
    a_worse_fav = fav_mean is not None and a_mean is not None and a_mean < fav_mean - 1e-12
    a_worse_lock = lock_mean is not None and a_mean is not None and a_mean < lock_mean - 1e-12
    if a_le0 and a_worse_fav and a_worse_lock:
        tag = "DISMISS"
    elif a_worse_fav and a_worse_lock:
        tag = "DISMISS"
    elif best_mean is not None and best_mean <= 1e-12:
        tag = "DISMISS"
    else:
        tag = "HOLD"
    why = (
        f"Best candidate on this frozen book is {best_name} mean {fmt_signed(best_mean)}. "
        f"A D=5 mean {fmt_signed(a_mean)}; B D=5 mean {fmt_signed(b_mean)}; "
        f"C D=1 mean {fmt_signed(c_mean)}; original D=5 mean {fmt_signed(o_mean)}. "
        f"T0-only both-Yes mean {fmt_signed(hold_mean)}. T0-favorite-only mean "
        f"{fmt_signed(fav_mean)}. Current Yes+No ≤ $0.95 lock all-settled mean "
        f"{fmt_signed(lock_mean)}. "
    )
    if tag == "DISMISS":
        why += (
            "DISMISS on quality, not trade count. A is at or below zero, or worse than both "
            "T0-favorite-only and the lock. Hassan and Smith are two worked paths, not KEEP. "
        )
    else:
        why += (
            "HOLD not KEEP. The best D on this table was read after seeing every arm on the same "
            "October 2026 universe (selection bias). Two named matches are not a send rule. "
            "Short tape, all out-of-sample. "
        )
        if a_mean is not None and lock_mean is not None and a_mean < lock_mean - 1e-12:
            why += "A D=5 does not beat the current lock on mean P&L. "
    why += "Research only. Not gold. Not DailyRun."
    return tag, why


def compare_rows(payload: dict) -> list[dict]:
    lock = payload["lock"]
    hold = payload["hold"]
    fav = payload["fav"]
    orig5 = next((r for r in payload["orig_rows"] if r["dip"] == 0.05), {})
    lock_mean = lock.get("mean_all_settled")
    hold_mean = hold.get("mean")
    fav_mean = fav.get("mean")
    o5_mean = orig5.get("mean")
    rows = []

    def add(arm, role, rec, extra_note=""):
        mean_v = rec.get("mean") if "mean" in rec else rec.get("mean_all_settled")
        med_v = rec.get("median") if "median" in rec else rec.get("median_all_settled")
        rows.append({
            "arm": arm,
            "role": role,
            "n": rec.get("n"),
            "n_settled": rec.get("n_settled"),
            "mean": signed_money(mean_v),
            "median": signed_money(med_v),
            "win_pct": rec.get("win_pct") or rec.get("win_pct_taken") or "",
            "mean_cost": money_cell(rec.get("mean_cost")),
            "pct_hedged": rec.get("pct_hedged") or rec.get("pct_taken") or rec.get("pct_both") or "",
            "pct_one": rec.get("pct_one") or "",
            "pct_crossed": rec.get("pct_crossed") or "",
            "pct_lock": rec.get("pct_lock") or rec.get("pct_none") or "",
            "d_orig5": delta_money(mean_v, o5_mean),
            "d_fav": delta_money(mean_v, fav_mean),
            "d_hold": delta_money(mean_v, hold_mean),
            "d_lock": delta_money(mean_v, lock_mean),
            "ann_ror": na_book(),
            "ann_ror_is": "n/a — no IS (all OOS)",
            "ann_ror_oos": na_book(),
            "max_dd": na_book(),
            "calmar": na_book(),
            "sharpe": na_book(),
            "note": extra_note or rec.get("note") or "",
        })

    add(
        "Current lock Yes+No ≤ $0.95 (sit out $0 if never)",
        "control",
        {
            **lock,
            "mean": lock_mean,
            "median": lock.get("median_all_settled"),
            "win_pct": lock.get("win_pct_taken") or "",
            "pct_taken": lock.get("pct_taken") or "",
            "pct_none": pct((lock.get("n") or 0) - (lock.get("n_taken") or 0), lock.get("n") or 0),
        },
        lock.get("note") or "",
    )
    add("T0-only both-Yes (no extra)", "control", hold)
    add("T0-favorite-only (higher Yes, no hedge)", "control", fav)
    for rec in payload["orig_rows"]:
        add(
            f"Original extra-Yes-on-dip D={rec['dip_cents']}¢ (dip, not lock)",
            "control",
            rec,
        )
    for rec in payload["a_rows"]:
        add(
            f"A favorite-only then complementary lock D={rec['dip_cents']}¢",
            "candidate",
            rec,
        )
    for rec in payload["b_rows"]:
        add(
            f"B both-Yes, 50¢ cross, then orig-fav lock D={rec['dip_cents']}¢",
            "candidate",
            rec,
        )
    for rec in payload["c_rows"]:
        add(
            f"C extra-Yes-on-dip D={rec['dip_cents']}¢ (first-dip primary)",
            "candidate",
            rec,
        )
    return rows


def optional_fee_rows(payload: dict) -> list[dict]:
    hold = payload["hold"]
    fav = payload["fav"]
    a5 = next((r for r in payload["a_rows"] if r["dip"] == 0.05), {})
    o5 = next((r for r in payload["orig_rows"] if r["dip"] == 0.05), {})
    b5 = next((r for r in payload["b_rows"] if r["dip"] == 0.05), {})
    c1 = next((r for r in payload["c_rows"] if r["dip"] == 0.01), {})
    hold_fee = payload.get("hold_fee_mean")
    fav_fee = payload.get("fav_fee_mean")
    return [
        {
            "arm": "T0-only both-Yes with venue fees (optional, not primary)",
            "mean_no_fee": signed_money(hold.get("mean")),
            "mean_fee": signed_money(hold_fee),
            "note": "Labeled optional. Primary P&L is without fees.",
        },
        {
            "arm": "T0-favorite-only with venue fees (optional, not primary)",
            "mean_no_fee": signed_money(fav.get("mean")),
            "mean_fee": signed_money(fav_fee),
            "note": "Labeled optional. Primary P&L is without fees.",
        },
        {
            "arm": "Original D=5¢ with venue fees (optional, not primary)",
            "mean_no_fee": signed_money(o5.get("mean")),
            "mean_fee": signed_money(payload.get("orig5_fee_mean")),
            "note": "Polymarket taker is NOT in the primary numbers.",
        },
        {
            "arm": "A D=5¢ with venue fees (optional, not primary)",
            "mean_no_fee": signed_money(a5.get("mean")),
            "mean_fee": signed_money(a5.get("mean_fee")),
            "note": "Labeled optional. Primary P&L is without fees.",
        },
        {
            "arm": "B D=5¢ with venue fees (optional, not primary)",
            "mean_no_fee": signed_money(b5.get("mean")),
            "mean_fee": signed_money(b5.get("mean_fee")),
            "note": "Labeled optional. Primary P&L is without fees.",
        },
        {
            "arm": "C D=1¢ with venue fees (optional, not primary)",
            "mean_no_fee": signed_money(c1.get("mean")),
            "mean_fee": signed_money(c1.get("mean_fee")),
            "note": "Labeled optional. Primary P&L is without fees.",
        },
    ]


def per_match_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        orig = p.get("yes_dips") or {}
        a_map = p.get("a_locks") or {}
        b_map = p.get("b_locks") or {}
        c_map = p.get("small_dips") or {}
        winner = p.get("winner")
        win_name = p.get("side_a") if winner == "a" else p.get("side_b") if winner == "b" else ""
        rec5 = orig.get(0.05) or {}
        a5 = a_map.get(0.05) or {}
        a10 = a_map.get(0.10) or {}
        b5 = b_map.get(0.05) or {}
        b10 = b_map.get(0.10) or {}
        c1 = c_map.get(0.01) or {}
        lock_pnl = lock_pnl_of(p)
        row = {
            "game": p.get("game") or "",
            "date": match_date(p),
            "venue": p.get("venue") or "",
            "side_a": p.get("side_a") or "",
            "t0_a": fmt_px(p.get("t0_a")),
            "side_b": p.get("side_b") or "",
            "t0_b": fmt_px(p.get("t0_b")),
            "c0": fmt_px(p.get("c0")),
            "fav": last_name(p.get("fav_name") or "") or "",
            "t0_fav": fmt_px(p.get("t0_fav")),
            "inplay_n": p.get("inplay_n") or 0,
            "winner": win_name,
            "live": "yes" if not p.get("settled") else "no",
            "t0_when": et_iso(p.get("t0_ts")),
            "hold_pnl": signed_money(p.get("hold_pnl")) if p.get("settled") else "",
            "fav_pnl": signed_money(p.get("fav_pnl")) if p.get("fav_pnl") is not None else "",
            "lock_pnl": signed_money(lock_pnl) if lock_pnl is not None else "",
            "orig5": extra_fill_text(p, rec5, "first"),
            "orig5_pnl": signed_money(rec5.get("pnl")) if rec5.get("pnl") is not None else "",
            "a5": a_fill_text(p, a5),
            "a5_pnl": signed_money(a5.get("pnl")) if a5.get("pnl") is not None else "",
            "a10": a_fill_text(p, a10),
            "a10_pnl": signed_money(a10.get("pnl")) if a10.get("pnl") is not None else "",
            "b5": b_fill_text(p, b5),
            "b5_pnl": signed_money(b5.get("pnl")) if b5.get("pnl") is not None else "",
            "b10": b_fill_text(p, b10),
            "b10_pnl": signed_money(b10.get("pnl")) if b10.get("pnl") is not None else "",
            "c1": extra_fill_text(p, c1, "first"),
            "c1_pnl": signed_money(c1.get("pnl")) if c1.get("pnl") is not None else "",
        }
        for dip in LOCK_DS:
            cents = int(round(dip * 100))
            rec = orig.get(dip) or {}
            row[f"orig{cents}_pnl"] = signed_money(rec.get("pnl")) if rec.get("pnl") is not None else ""
            ar = a_map.get(dip) or {}
            row[f"a{cents}_pnl"] = signed_money(ar.get("pnl")) if ar.get("pnl") is not None else ""
            br = b_map.get(dip) or {}
            row[f"b{cents}_pnl"] = signed_money(br.get("pnl")) if br.get("pnl") is not None else ""
        for dip in SMALL_DIPS:
            cents = int(round(dip * 100))
            rec = c_map.get(dip) or {}
            row[f"c{cents}_pnl"] = signed_money(rec.get("pnl")) if rec.get("pnl") is not None else ""
            row[f"c{cents}"] = extra_fill_text(p, rec, "first")
        rows.append(row)
    rows.sort(key=lambda r: (-(r.get("inplay_n") or 0), r.get("game") or "", r.get("venue") or ""))
    return rows


def example_pair_html(title: str, pair: dict | None, missing: str) -> str:
    if pair is None:
        return f"<p class='note'>{esc(missing)}</p>"
    orig = pair.get("yes_dips") or {}
    a_map = pair.get("a_locks") or {}
    b_map = pair.get("b_locks") or {}
    b_next = pair.get("b_next") or {}
    winner = ""
    if pair.get("winner") == "a":
        winner = pair.get("side_a") or ""
    elif pair.get("winner") == "b":
        winner = pair.get("side_b") or ""
    bits = [
        f"<p><strong>{esc(title)}</strong> {esc(pair.get('venue') or '')}. "
        f"T0 {esc(pair.get('t0_label') or '')} at {esc(et_iso(pair.get('t0_ts')))}: "
        f"{esc(pair.get('side_a'))} {fmt_px(pair.get('t0_a'))} / "
        f"{esc(pair.get('side_b'))} {fmt_px(pair.get('t0_b'))}, C = {fmt_px(pair.get('c0'))}. "
        f"Favorite {esc(pair.get('fav_name') or '')} {fmt_px(pair.get('t0_fav'))}. "
        f"Underdog {esc(pair.get('dog_name') or '')} {fmt_px(pair.get('t0_dog'))}. "
        f"Winner {esc(winner or 'unsettled')}. In-play ticks {pair.get('inplay_n') or 0}. "
        f"Clock hid match: {'yes' if pair.get('listed_stale') or pair.get('occ_stale') else 'no'}.</p>"
    ]
    o5 = orig.get(0.05) or {}
    bits.append(
        f"<p>Original D=5 extra-Yes-on-dip (dip, not lock): mix {esc(o5.get('mix') or '')}, "
        f"fills {esc(extra_fill_text(pair, o5, 'first'))}, cost {money_cell(o5.get('cost'))}, "
        f"P&amp;L {signed_money(o5.get('pnl')) if o5.get('pnl') is not None else 'unsettled'}.</p>"
    )
    a5, a10 = a_map.get(0.05) or {}, a_map.get(0.10) or {}
    bits.append(
        f"<p>A D=5 complementary target {fmt_px(a5.get('target'))}: "
        f"{esc(a_fill_text(pair, a5))}, cost {money_cell(a5.get('cost'))}, "
        f"P&amp;L {signed_money(a5.get('pnl')) if a5.get('pnl') is not None else 'unsettled'}. "
        f"A D=10 target {fmt_px(a10.get('target'))}: {esc(a_fill_text(pair, a10))}, "
        f"cost {money_cell(a10.get('cost'))}, "
        f"P&amp;L {signed_money(a10.get('pnl')) if a10.get('pnl') is not None else 'unsettled'}. "
        f"Unhedged T0-favorite-only P&amp;L "
        f"{signed_money(pair.get('fav_pnl')) if pair.get('fav_pnl') is not None else 'unsettled'}.</p>"
    )
    b5 = b_map.get(0.05) or {}
    b10 = b_map.get(0.10) or {}
    n5 = b_next.get(0.05) or {}
    cross = pair.get("b_cross") or {}
    bits.append(
        f"<p>B primary (first print &gt; 0.50): {esc(b_fill_text(pair, b5))}. "
        f"D=5 target {fmt_px(b5.get('target'))} P&amp;L "
        f"{signed_money(b5.get('pnl')) if b5.get('pnl') is not None else 'unsettled'}. "
        f"D=10 target {fmt_px(b10.get('target'))} P&amp;L "
        f"{signed_money(b10.get('pnl')) if b10.get('pnl') is not None else 'unsettled'}. "
        f"Cross print {fmt_px(cross.get('px'))} @ {esc(et_iso(cross.get('ts')))}; "
        f"next tick {fmt_px(cross.get('next_px'))} @ {esc(et_iso(cross.get('next_ts')))}. "
        f"B next-tick sensitivity D=5: {esc(b_fill_text(pair, n5))}, P&amp;L "
        f"{signed_money(n5.get('pnl')) if n5.get('pnl') is not None else 'unsettled'}.</p>"
    )
    return "\n".join(bits)


def hassan_check(pair: dict | None) -> str:
    if pair is None:
        return "Rodenas vs Hassan Polymarket is not on the frozen dense book."
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    rec = (pair.get("yes_dips") or {}).get(0.05) or {}
    a5 = (pair.get("a_locks") or {}).get(0.05) or {}
    a10 = (pair.get("a_locks") or {}).get(0.10) or {}
    b5 = (pair.get("b_locks") or {}).get(0.05) or {}
    extra = rec.get("extra_a") or rec.get("extra_b")
    extra_px = extra.get("yes_print") if extra else None
    extra_ts = extra.get("ts") if extra else None
    h5 = (a5.get("hedge") or {})
    h10 = (a10.get("hedge") or {})
    t0_ok = close_enough(t0a, 0.36) and close_enough(t0b, 0.65)
    if not t0_ok:
        t0_ok = close_enough(t0a, 0.65) and close_enough(t0b, 0.36)
    d5_ok = close_enough(extra_px, 0.29)
    a5_ok = close_enough(h5.get("px"), 0.29)
    a10_ok = close_enough(h10.get("px"), 0.25)
    b_ok = not b5.get("crossed")
    won = "hassan" in (pair.get("fav_name") or "").lower() and pair.get("winner") == pair.get("fav")
    if "hassan" not in (pair.get("fav_name") or "").lower():
        won = "hassan" in (
            (pair.get("side_a") if pair.get("winner") == "a" else pair.get("side_b")) or ""
        ).lower()
    bits = []
    bits.append("T0 0.36/0.65 C=1.01" if t0_ok else f"T0 now {fmt_px(t0a)}/{fmt_px(t0b)} C={fmt_px(pair.get('c0'))} (expected 0.36/0.65)")
    bits.append(f"T0 clock {et_iso(pair.get('t0_ts'))}")
    bits.append("Hassan won" if won else f"winner {(pair.get('side_a') if pair.get('winner')=='a' else pair.get('side_b')) or 'unsettled'}")
    bits.append(
        f"original D=5 extra {fmt_px(extra_px)} @ {et_iso(extra_ts)}"
        if d5_ok else
        f"original D=5 extra {fmt_px(extra_px)} @ {et_iso(extra_ts)} (expected Rodenas ~0.29 @ 05:14:27)"
    )
    bits.append(
        f"A D=5 complementary {fmt_px(h5.get('px'))}"
        if a5_ok else
        f"A D=5 {a_fill_text(pair, a5)} (expected ~0.29)"
    )
    bits.append(
        f"A D=10 {a_fill_text(pair, a10)}"
        + ("" if a10_ok else " (expected complementary ~0.25 @ 05:15:26)")
    )
    bits.append("B no 50¢ cross, stop at T0 both" if b_ok else f"B {b_fill_text(pair, b5)}")
    core = t0_ok and won and b_ok
    prefix = (
        "Tape matches Hassan T0 0.36/0.65, Hassan won, and B had no 50¢ cross. "
        if core else
        "Tape differs from the named Hassan path. "
    )
    if core and not (d5_ok and a5_ok and a10_ok):
        prefix += "First complementary prints on today's longer tape are earlier/cheaper than the named 05:14/05:15 walk. "
    return prefix + "; ".join(bits) + "."


def smith_check(pair: dict | None) -> str:
    if pair is None:
        return "Smith vs Purcell Polymarket is not on the frozen dense book."
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    t0_ok = (
        (close_enough(t0a, 0.34) and close_enough(t0b, 0.67))
        or (close_enough(t0a, 0.67) and close_enough(t0b, 0.34))
    )
    cross = pair.get("b_cross") or {}
    b5 = (pair.get("b_locks") or {}).get(0.05) or {}
    extra = (b5.get("fav_extra") or {})
    cross_ok = close_enough(cross.get("px"), 0.52)
    next_ok = close_enough(cross.get("next_px"), 0.47)
    fav_ok = close_enough(extra.get("px"), 0.38)
    a_fav = last_name(pair.get("fav_name") or "").lower()
    a_lost = pair.get("settled") and pair.get("winner") != pair.get("fav") and "purcell" in a_fav
    won = "smith" in (
        (pair.get("side_a") if pair.get("winner") == "a" else pair.get("side_b")) or ""
    ).lower()
    bits = []
    bits.append("T0 Smith 0.34 / Purcell 0.67 C=1.01" if t0_ok else f"T0 now {fmt_px(t0a)}/{fmt_px(t0b)}")
    bits.append("Smith won" if won else f"winner {pair.get('winner')}")
    bits.append(
        f"cross {fmt_px(cross.get('px'))} @ {et_iso(cross.get('ts'))} then {fmt_px(cross.get('next_px'))}"
        if cross_ok and next_ok else
        f"cross {fmt_px(cross.get('px'))} then {fmt_px(cross.get('next_px'))} (expected 0.52 then 0.47)"
    )
    bits.append(
        f"B D=5 original-favorite Yes {fmt_px(extra.get('px'))} @ {et_iso(extra.get('ts'))}"
        if fav_ok else
        f"B D=5 fav extra {fmt_px(extra.get('px'))} @ {et_iso(extra.get('ts'))} (expected Purcell ~0.38 @ 08:28:44)"
    )
    bits.append(
        "A bought T0 favorite Purcell who lost"
        if a_lost else
        f"A T0 favorite {pair.get('fav_name') or ''} winner-is-fav={pair.get('winner')==pair.get('fav')}"
    )
    core = t0_ok and won and cross_ok and next_ok
    prefix = (
        "Tape matches Smith T0 0.34/0.67, Smith won, and the 0.52 then 0.47 cross. "
        if core else
        "Tape differs from the named Smith path. "
    )
    if core and not fav_ok:
        prefix += (
            "B's first original-favorite Yes at/below 1 - C - D is earlier than the named 0.38 @ 08:28:44. "
        )
    return prefix + "; ".join(bits) + "."


def write_html(payload: dict) -> None:
    if PAGE.resolve() == ORIGINAL_PAGE.resolve():
        raise RuntimeError("refusing to overwrite the original extra-Yes-on-dip HTML")
    dual = STAMP / "tennis_dual_yes_dip_no_20261021.html"
    if PAGE.resolve() == dual.resolve():
        raise RuntimeError("refusing to overwrite tennis_dual_yes_dip_no_20261021.html")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis A/B/C vs extra-Yes-on-dip 2026-10-21</title>
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
<h1>Tennis A/B/C vs extra-Yes-on-dip — frozen dense book</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Entire October 2026 tape is out-of-sample (OOS): every T0 ≥ 2024-01-01. No in-sample (IS) row. Verdict: <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Frozen universe:</strong> {payload['n_dense']} tennis books keyed to the original 12:11 ET extra-Yes-on-dip HTML ({ORIGINAL_N} (game, venue) keys). Settled {payload['n_dense_settled']}; still live {payload['n_dense_live']}. {esc(payload.get('freeze_note') or '')}</p>
<p><strong>Hassan:</strong> {esc(payload.get('hassan_text') or '')}</p>
<p><strong>Smith:</strong> {esc(payload.get('smith_text') or '')}</p>
<p><strong>Verdict:</strong> {esc(payload.get('sweet_text') or '')}</p>
<p>Annualized rate of return (Ann ROR) is omitted. These are same-day tennis contracts. We do not have closed-trade days held, so the house Ann ROR formula is not computed. In-sample / out-of-sample Ann ROR, Max DD, Calmar, Sharpe, capital days, Paul Score, and FIT are n/a for the same reason. Total book PnL $ is omitted from the compare table (canonical HTML compare rule).</p>
</div>

<div class="warn">
<p>Primary P&amp;L is without fees. Fills are optimistic at the printed Yes ask. Do not buy after the first 5¢ / 95¢ absorbing print. Original extra-Yes-on-dip is not a lock. Two named matches are not KEEP. Arm ranking after seeing this table is selection bias. {esc(payload.get('note_n') or '')} Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Research only. Not gold. Not DailyRun.</p>
</div>

<h2>Freeze</h2>
<ul>
<li>Original 12:11 ET page: <code>dense_inplay_yes_dip_20261021.html</code> (not overwritten). Dense N {ORIGINAL_N}, settled {ORIGINAL_SETTLED}.</li>
<li>This page keeps those same {ORIGINAL_N} (game, venue) keys so later tape growth does not change N. Live dense now {payload.get('n_live_dense')}; extra live-dense keys excluded {payload.get('n_extra_live')}; freeze keys missing from tape {payload.get('n_missing')}.</li>
<li>Tape: price_memory iter (read-only archive <code>raw/price_memory.jsonl</code> plus dated sport shards under <code>raw/price_memory/</code>). Lines {(payload.get('stream') or {}).get('n_lines') or 0:,}. Tennis moneyline Yes/No change-ticks {(payload.get('stream') or {}).get('n_hits') or 0:,}. First quote {esc((payload.get('stream') or {}).get('seen_min') or '')}. Last quote {esc((payload.get('stream') or {}).get('seen_max') or '')}.</li>
<li>T0, in-play window, tick bar (≥{TICK_BAR}), C in [{C_LO}, {C_HI}], ABSORB=0.05: same helpers as the original generator (<code>assign_actual_t0</code>, <code>mark_inplay</code>, <code>first_dip_yes</code>).</li>
<li>Winners: <code>attach_pair_results</code> (odds_cross_settlements + Polymarket/Kalshi same-game).</li>
<li>Original D is a dip from that player's T0 Yes. A/B D is lock profit: complementary cash ≤ 1 − fill − D.</li>
<li>Primary P&amp;L has no Polymarket taker. Optional venue-fee rows are labeled below and are not the score.</li>
</ul>
<p>Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h2>1. Summary arms — same frozen universe</h2>
<p class="note">Mean / median / win rate are settled books. Fill-rate columns are all books. % hedged is A. % crossed / % lock filled are B. Original and C use % both extra in the hedged column when present. Deltas are candidate minus that control. Ann ROR / Max DD / Calmar / Sharpe are n/a — no days held. Click column headers to sort.</p>
{table(
    [("Arm", "text"), ("Role", "text"), ("N books", "num"), ("N settled", "num"),
     ("Mean $", "num"), ("Median $", "num"), ("Win rate %", "num"), ("Mean cost", "num"),
     ("% hedged / both extra / lock taken", "num"), ("% one extra", "num"),
     ("% crossed", "num"), ("% lock filled / none", "num"),
     ("Δ mean $ vs original D=5", "num"), ("Δ mean $ vs T0-favorite-only", "num"),
     ("Δ mean $ vs T0-both", "num"), ("Δ mean $ vs lock", "num"),
     ("Ann ROR full", "text"), ("Ann ROR IS", "text"), ("Ann ROR OOS", "text"),
     ("Max DD", "text"), ("Calmar", "text"), ("Sharpe", "text"),
     ("Note", "text")],
    payload["compare_rows"],
    ["arm", "role", "n", "n_settled", "mean", "median", "win_pct", "mean_cost",
     "pct_hedged", "pct_one", "pct_crossed", "pct_lock",
     "d_orig5", "d_fav", "d_hold", "d_lock",
     "ann_ror", "ann_ror_is", "ann_ror_oos", "max_dd", "calmar", "sharpe", "note"],
)}

<h2>2. Optional venue-fee row (not primary)</h2>
<p class="note">Primary score above is without fees. These rows apply documented venue fees after the fact, including Polymarket taker on Polymarket books. Do not read them as the result.</p>
{table(
    [("Arm", "text"), ("Mean $ without fees (primary)", "num"), ("Mean $ with venue fees", "num"), ("Note", "text")],
    payload["fee_rows"],
    ["arm", "mean_no_fee", "mean_fee", "note"],
)}

<h2>3. Rodenas vs Hassan 2026-10-19 Polymarket</h2>
{payload.get('hassan_html') or ''}
<p class="note">{esc(payload.get('hassan_text') or '')}</p>

<h2>4. Smith vs Purcell Polymarket</h2>
{payload.get('smith_html') or ''}
<p class="note">{esc(payload.get('smith_text') or '')}</p>

<h2>5. Per-match frozen dense tennis</h2>
<p class="note">One row per frozen (game, venue). A/B/C columns are the primary sims. Click column headers to sort.</p>
{table(
    [("Match", "text"), ("Date", "date"), ("Venue", "text"),
     ("Yes A", "text"), ("T0 A", "num"), ("Yes B", "text"), ("T0 B", "num"), ("C", "num"),
     ("T0 favorite", "text"), ("T0 fav px", "num"), ("in-play ticks", "num"),
     ("T0-both P&L", "num"), ("T0-fav P&L", "num"), ("Lock P&L", "num"),
     ("Original D=5 extras", "text"), ("Original D=5 P&L", "num"),
     ("A D=5 fill", "text"), ("A D=5 P&L", "num"), ("A D=10 fill", "text"), ("A D=10 P&L", "num"),
     ("B D=5 fills", "text"), ("B D=5 P&L", "num"), ("B D=10 fills", "text"), ("B D=10 P&L", "num"),
     ("C D=1 extras", "text"), ("C D=1 P&L", "num"),
     ("C D=2 P&L", "num"), ("C D=3 P&L", "num"), ("C D=4 P&L", "num"),
     ("Original D=10 P&L", "num"), ("Original D=15 P&L", "num"),
     ("Original D=20 P&L", "num"), ("Original D=25 P&L", "num"),
     ("A D=15 P&L", "num"), ("A D=20 P&L", "num"), ("A D=25 P&L", "num"),
     ("B D=15 P&L", "num"), ("B D=20 P&L", "num"), ("B D=25 P&L", "num"),
     ("Winner", "text"), ("Still live?", "text"), ("T0 when", "text")],
    payload["match_rows"],
    ["game", "date", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0",
     "fav", "t0_fav", "inplay_n", "hold_pnl", "fav_pnl", "lock_pnl",
     "orig5", "orig5_pnl", "a5", "a5_pnl", "a10", "a10_pnl",
     "b5", "b5_pnl", "b10", "b10_pnl", "c1", "c1_pnl", "c2_pnl", "c3_pnl", "c4_pnl",
     "orig10_pnl", "orig15_pnl", "orig20_pnl", "orig25_pnl",
     "a15_pnl", "a20_pnl", "a25_pnl", "b15_pnl", "b20_pnl", "b25_pnl",
     "winner", "live", "t0_when"],
)}

<h2>How to read this</h2>
<ul>
<li>KEEP / HOLD / DISMISS is quality versus T0-both, T0-favorite-only, the current lock, and original D=5, not trade count.</li>
<li>Hassan and Smith illustrate the paths. They are not KEEP.</li>
<li>If A’s mean is ≤ 0, or worse than both T0-favorite-only and the lock, A is DISMISS or HOLD.</li>
<li>Picking the best D after reading this table is in-sample selection on an all-OOS tape.</li>
</ul>
<p class="note">Acronyms: T0 is the open used here. C is the two T0 Yes prices added together. Vig is the overround when two Yes prices sum over $1. Ann ROR is annualized rate of return. IS is in-sample; OOS is out-of-sample. ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def hold_fee_mean(pairs: list[dict]) -> float | None:
    pnls = []
    for p in pairs:
        if not p.get("settled") or p.get("hold_pnl") is None:
            continue
        t0a, t0b = p.get("t0_a"), p.get("t0_b")
        if t0a is None or t0b is None:
            continue
        pnls.append(p["hold_pnl"] - fees_for(p.get("venue") or "", [t0a, t0b]))
    return mean(pnls)


def fav_fee_mean(pairs: list[dict]) -> float | None:
    pnls = []
    for p in pairs:
        if not p.get("settled") or p.get("fav_pnl") is None or p.get("t0_fav") is None:
            continue
        pnls.append(p["fav_pnl"] - fees_for(p.get("venue") or "", [p["t0_fav"]]))
    return mean(pnls)


def main() -> None:
    freeze_keys = freeze_keys_from_original_html()
    freeze_set = set(freeze_keys)
    print(f"freeze keys from original HTML {len(freeze_keys)} unique {len(freeze_set)}", flush=True)
    stream = stream_tennis()
    settlements = load_settlements()
    catalog = load_catalog()
    start_lookup = start_lookup_from(settlements, catalog)
    pairs = pair_matches(stream["series"], start_lookup)
    tennis = [p for p in pairs if (p.get("sport") or "").lower() == "tennis"]
    print(f"two-sided tennis {len(tennis)}", flush=True)
    for pair in tennis:
        assign_actual_t0(pair, start_lookup)
    attach_pair_results(tennis, settlements)
    for pair in tennis:
        mark_inplay(pair)
    live_dense = [p for p in tennis if p.get("dense")]
    by_key: dict[tuple[str, str], dict] = {}
    for pair in tennis:
        by_key[pair_key(pair)] = pair
    frozen = []
    missing = []
    for key in freeze_keys:
        pair = by_key.get(key)
        if pair is None:
            missing.append(key)
            continue
        frozen.append(pair)
    extra_live = [p for p in live_dense if pair_key(p) not in freeze_set]
    print(
        f"frozen {len(frozen)}; missing {len(missing)}; live dense {len(live_dense)}; "
        f"extra live dense excluded {len(extra_live)}",
        flush=True,
    )
    for pair in frozen:
        simulate_yes_dip(pair)
        simulate_t0_favorite_only(pair)
        simulate_a(pair)
        simulate_b(pair)
        simulate_c(pair)
    simulate_current_lock(frozen)
    settled = [p for p in frozen if p.get("settled")]
    live = [p for p in frozen if not p.get("settled")]
    orig_rows = [summarize_yes(frozen, dip, "first") for dip in DIPS]
    a_rows = [summarize_a(frozen, dip) for dip in LOCK_DS]
    b_rows = [summarize_b(frozen, dip, "b_locks") for dip in LOCK_DS]
    c_rows = [summarize_c(frozen, dip) for dip in SMALL_DIPS]
    hold = summarize_hold(frozen)
    fav = summarize_fav(frozen)
    lock = summarize_lock(frozen)
    for rec in orig_rows:
        print(
            f"ORIG D={rec['dip_cents']}c n={rec['n']} settled={rec['n_settled']} "
            f"mean={fmt_signed(rec['mean'])}",
            flush=True,
        )
    for rec in a_rows:
        print(
            f"A D={rec['dip_cents']}c n={rec['n']} settled={rec['n_settled']} "
            f"mean={fmt_signed(rec['mean'])} hedged={rec['pct_hedged']}",
            flush=True,
        )
    for rec in b_rows:
        print(
            f"B D={rec['dip_cents']}c n={rec['n']} settled={rec['n_settled']} "
            f"mean={fmt_signed(rec['mean'])} crossed={rec['pct_crossed']} lock={rec['pct_lock']}",
            flush=True,
        )
    for rec in c_rows:
        print(
            f"C D={rec['dip_cents']}c n={rec['n']} settled={rec['n_settled']} "
            f"mean={fmt_signed(rec['mean'])}",
            flush=True,
        )
    print(
        f"HOLD t0-both mean={fmt_signed(hold.get('mean'))} settled={hold.get('n_settled')}",
        flush=True,
    )
    print(
        f"FAV t0-fav mean={fmt_signed(fav.get('mean'))} settled={fav.get('n_settled')}",
        flush=True,
    )
    print(
        f"LOCK n={lock['n']} taken={lock['n_taken']} settled={lock['n_settled']} "
        f"mean_all={fmt_signed(lock.get('mean_all_settled'))}",
        flush=True,
    )
    verdict, sweet_text = decide_verdict(a_rows, b_rows, c_rows, orig_rows, hold, fav, lock)
    hassan = pick_named(frozen, "rodenas", "hassan", venue="polymarket")
    smith = pick_named(frozen, "smith", "purcell", venue="polymarket")
    hassan_text = hassan_check(hassan)
    smith_text = smith_check(smith)
    def _out(msg: str) -> None:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)

    _out(f"HASSAN {hassan_text}")
    _out(f"SMITH {smith_text}")
    _out(f"VERDICT {verdict}")
    freeze_bits = []
    if len(frozen) != ORIGINAL_N:
        freeze_bits.append(
            f"Frozen N is {len(frozen)}, not {ORIGINAL_N} "
            f"({len(missing)} keys missing from current tape)."
        )
    else:
        freeze_bits.append(f"Frozen N holds at {ORIGINAL_N}.")
    if len(settled) != ORIGINAL_SETTLED:
        freeze_bits.append(
            f"Settled N is {len(settled)}, not {ORIGINAL_SETTLED} from 12:11 ET. "
            "Freeze is on (game, venue) keys, not on settled flags; more (or fewer) official "
            "winners can attach after 12:11."
        )
    else:
        freeze_bits.append(f"Settled N holds at {ORIGINAL_SETTLED}.")
    if extra_live:
        freeze_bits.append(
            f"{len(extra_live)} books are dense on today's longer tape and were excluded so N stays frozen."
        )
    payload = {
        "written_at": iso_now(),
        "stream": stream,
        "orig_rows": orig_rows,
        "a_rows": a_rows,
        "b_rows": b_rows,
        "c_rows": c_rows,
        "hold": hold,
        "fav": fav,
        "lock": lock,
        "hold_fee_mean": hold_fee_mean(frozen),
        "fav_fee_mean": fav_fee_mean(frozen),
        "orig5_fee_mean": summarize_orig_fees(frozen, 0.05),
        "sweet_text": sweet_text,
        "verdict": verdict,
        "n_dense": len(frozen),
        "n_dense_settled": len(settled),
        "n_dense_live": len(live),
        "n_live_dense": len(live_dense),
        "n_extra_live": len(extra_live),
        "n_missing": len(missing),
        "freeze_note": " ".join(freeze_bits),
        "note_n": tiny_note(len(settled)),
        "hassan_text": hassan_text,
        "smith_text": smith_text,
        "hassan_html": example_pair_html(
            "Rodenas vs Hassan",
            hassan,
            "Rodenas vs Hassan Polymarket is not on this frozen book.",
        ),
        "smith_html": example_pair_html(
            "Smith vs Purcell",
            smith,
            "Smith vs Purcell Polymarket is not on this frozen book.",
        ),
        "match_rows": per_match_rows(frozen),
    }
    payload["compare_rows"] = compare_rows(payload)
    payload["fee_rows"] = optional_fee_rows(payload)
    write_html(payload)
    copy_g(PAGE)
    print("done", flush=True)


if __name__ == "__main__":
    main()
