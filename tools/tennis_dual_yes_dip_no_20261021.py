"""Tennis dual-Yes at T0, then dip-No on each player independently.

Research only. Reads price_memory.jsonl and official settlements.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Not gold. Not DailyRun.
Does not take price_memory.lock (read-only scan of the jsonl).
"""
from __future__ import annotations

import json
import math
import re
import statistics
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
    mins_after,
    pair_matches,
    window_end,
)
from odds_cross_no_roi_60_70_20261020 import copy_g, venue_fee
from odds_cross_winrate_20261020 import (
    as_float,
    parse_dt,
    pct,
    table,
    tiny_note,
    uniclean,
)
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP, RAW_DIR as RAW
from price_memory import iter_tick_lines, to_et
from tennis_decade_at_start_20261020 import start_lookup_from

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "tennis_dual_yes_dip_no_20261021.html"
DIPS = (0.05, 0.10, 0.15, 0.20, 0.25)
C_LO, C_HI = 0.95, 1.20
LOCK_SUM = 0.95
TENNIS_MIN = 360  # OLD invalid cap (listed_start + 360 minutes). Kept for the clock-bug example only.

ASKED = (
    "He does NOT want to add only one hedge. THE IDEA IS TO BUY THE HEDGE FOR BOTH when the odds "
    "change. Example: Yes Prizmic 0.69 + Yes Dzumhur 0.33 = cost 1.02. When Prizmic Yes goes down, "
    "buy No (example 0.43). When Dzumhur Yes goes down, buy No (example 0.28). Total "
    "1.02+0.43+0.28=1.73, always win $2 (Yes+No on each player). If median 0.05 dip: he wrote "
    "1.02+0.64+0.28=1.94 still +6 cents. If a player never dips 5 cents, skip that No; he thinks "
    "they likely win so the initial Yes still pays. Test all tennis: buy both Yes at T0, then wait "
    "for a 5 cent dip to buy No for BOTH (each player independently). Repeat 10, 15, 20, 25. Find "
    "the sweet spot. Does this make sense vs current cross-venue lock?"
    " CLOCK-FIX RERUN: the first sim was INVALID. Hedge window was listed_start .. listed_start+360 "
    "minutes. For Stefanos Tsitsipas vs Aleksandar Kovacevic (Polymarket), listed start was stale "
    "Sunday 18 Oct 2026 05:00 ET so the window ended 11:00 ET, T0 was 16:12 ET that Sunday "
    "(hedge-lo after hedge-hi), and the real 5c loser dip printed Tuesday 20 Oct (Kovacevic Yes "
    "0.21 → 0.15 → 0.01). About 69% “never dipped 5c” was that clock. Fix the clock and rerun. "
    "Keep the Tsitsipas/Kovacevic clock-bug example on the page. Hedge from T0 through the last "
    "live quote before settlement (or until Yes hits ~0/1), not listed_start+360. Include Tuesday "
    "live tape for delayed matches."
    " FOLLOW-UP 2026-10-21: Show him a game where there was no hedge. Show the data we collected, "
    "and how we came up with the understanding there was no hedge. He is looking at a LIVE game "
    "(Wawrinka vs Landaluce) and both players started close to each other, but they BOTH experienced "
    "5c dips. In fact the maximum dip for each was 39c for one and 17c for the other. He asks: "
    "are you collecting enough data throughout the match?"
)

PLAIN = (
    "A Yes price is a dollar from 0 to 1, also an implied chance: 0.69 means that named tennis "
    "player is listed at 69 percent to win (moneyline: who wins the match). T0 is the last Yes we "
    "have at or before listed start; if we missed the pre-start book, T0 is the first time both "
    "sides have a live Yes, and we label that. We buy one Yes on each player at those T0 asks. "
    "Only one player can win, so those two Yes tickets always pay exactly $1. Cost C = Yes A + Yes B. "
    "Stand-pat P&L is always $1 − C (a loss when C is above $1 — that gap is the vig, the house "
    "overround, not a bug). Confirm: 0.69 + 0.33 = 1.02, so stand-pat is −$0.02. "
    "A dip of D means that player's Yes later prints at or below T0 minus D. Then we buy one No on "
    "that player (No pays $1 if that player loses). Each player is independent: one may dip, both, "
    "or neither. If a player never dips D, we skip that No. "
    "If BOTH Nos fill, Yes+No on each name pays $2 in either world. "
    "Identity you must not mix up: if both players dip exactly D and each No is the complement "
    "(No = 1 − dipped Yes, which ignores the extra vig on the No book): total cost = C + "
    "(1 − (a0 − D)) + (1 − (b0 − D)) = 2 + 2D. For a 5-cent dip that is $2.10 spent to win $2.00 "
    "→ −$0.10. His 1.02+0.64+0.28 mixed a dipped Yes (0.64 = 0.69 − 0.05) into a No slot. "
    "The No that matches that 5-cent Prizmic dip is about 1 − 0.64 = 0.36, not 0.64. Dzumhur's "
    "5-cent dipped Yes would be 0.28; the matching No is about 1 − 0.28 = 0.72, not 0.28. "
    "Correct complement total is 1.02 + 0.36 + 0.72 = 2.10, not 1.94. The tape can still win "
    "when only one player dips and that player loses (asymmetric), or when the real No ask is "
    "cheaper than 1 − Yes. That is why we simulate prints, not the identity alone. "
    "Fills at the printed ask are optimistic. Complement No is labeled and is optimistic (ignores "
    "No vig). Current desk does the opposite: do not buy both Yes at T0; wait until some Yes+No "
    "on the same player (same venue or the other venue) sums to $0.95 or less, which locks $1 "
    "payout for ≤ $0.95 spent. "
    "This page is a clock-fix rerun of that idea. The first sim only looked from listed start to "
    "listed start plus 360 minutes (six hours). When the listed start was stale, that window closed "
    "before T0, so delayed Tuesday prints never counted and “never dipped 5 cents” was mostly a "
    "clock bug, not a quiet match. The corrected clock looks from T0 through the last live quote "
    "before the match is decided (Yes at about 5 cents or 95 cents), with no six-hour cap, so "
    "Tuesday tape is included. Research only. Not gold. Not DailyRun. Short October 2026 tape. "
    "Follow-up: he is watching Wawrinka vs Landaluce live, both Yes near 50/50, both dipping "
    "several cents, and he wants to see one settled book the sim called “no hedge” tick by tick, "
    "plus whether our pollers actually write prices during a match or only before it starts."
)


def esc(value) -> str:
    import html as html_mod
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def fmt_px(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_signed(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:+.3f}"


def mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(statistics.fmean(xs))


def median(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(statistics.median(xs))


def last_name(side: str) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", uniclean(side)) if t not in {"vs", "v"}]
    return toks[-1] if toks else ""


def pick_history() -> Path:
    local = LOCAL_STAMP / "raw" / "price_memory.jsonl"
    drive = STAMP / "raw" / "price_memory.jsonl"
    ranked = []
    for path in (local, drive):
        if path.is_file():
            ranked.append((path.stat().st_size, path))
    if not ranked:
        raise FileNotFoundError("no price_memory.jsonl under local or drive stamp raw")
    ranked.sort(reverse=True)
    chosen = ranked[0][1]
    print(
        "history candidates: "
        + ", ".join(f"{p} ({n:,} bytes)" for n, p in ranked)
        + f" -> {chosen}",
        flush=True,
    )
    return chosen


def stream_tennis(history: Path | None = None) -> dict:
    print("streaming tennis moneyline yes/no (archive + shards)", flush=True)
    series: dict[tuple, dict] = {}
    n_lines = 0
    n_hits = 0
    seen_min = None
    seen_max = None
    for line in iter_tick_lines(sport="tennis"):
            n_lines += 1
            if n_lines % 400000 == 0:
                print(f"  {n_lines} lines, series {len(series)} ticks {n_hits}", flush=True)
            if "tennis" not in line or "moneyline" not in line:
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
            if str(rec.get("sport") or "").lower() != "tennis":
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
            if not game or not side or not venue:
                continue
            key = ("tennis", game, venue, side, pay)
            st = series.get(key)
            if st is None:
                st = {
                    "sport": "tennis",
                    "game": game,
                    "venue": venue,
                    "side": side,
                    "pay": pay,
                    "start": rec.get("game_start") or "",
                    "ticks": [],
                }
                series[key] = st
            else:
                if rec.get("game_start") and not st["start"]:
                    st["start"] = rec.get("game_start") or ""
            ticks = st["ticks"]
            px = round(price, 4)
            if ticks and ticks[-1][0] == ts and ticks[-1][1] == px:
                continue
            if ticks and ticks[-1][1] == px:
                continue
            ticks.append((ts, px))
            n_hits += 1
            if seen:
                if seen_min is None or seen < seen_min:
                    seen_min = seen
                if seen_max is None or seen > seen_max:
                    seen_max = seen
    for st in series.values():
        st["ticks"].sort(key=lambda row: row[0])
    print(f"stream done lines={n_lines} ml_change_ticks={n_hits} series={len(series)}", flush=True)
    return {
        "series": series,
        "n_lines": n_lines,
        "n_hits": n_hits,
        "seen_min": seen_min or "",
        "seen_max": seen_max or "",
        "history": str(history),
    }


def hedge_lo(pair: dict) -> int | None:
    """Search starts at T0.

    If listed start is later than T0 (true pre-start last-Yes), skip remaining
    pre-start quotes. If listed start is stale and T0 is later, use T0 — do not
    wait for listed start, and do not invert the window against a 6-hour cap.
    """
    t0 = pair.get("t0_ts")
    if t0 is None:
        return None
    start_dt = pair.get("start_dt")
    if start_dt is None:
        return t0
    start_ts = int(to_et(start_dt).timestamp())
    if start_ts > t0:
        return start_ts
    return t0


def last_live_quote_ts(pair: dict) -> int | None:
    last = None
    for key in ("yes_a", "yes_b", "no_a", "no_b"):
        ticks = pair.get(key) or []
        if not ticks:
            continue
        ts = ticks[-1][0]
        if last is None or ts > last:
            last = ts
    return last


def live_hi(pair: dict) -> int | None:
    """T0 through last live quote before settlement. No listed_start+360 cap."""
    lo = hedge_lo(pair)
    if lo is None:
        return None
    last = last_live_quote_ts(pair)
    if last is None:
        return None
    after_a = [row for row in pair["yes_a"] if row[0] > lo]
    after_b = [row for row in pair["yes_b"] if row[0] > lo]
    absorb = first_absorbing(after_a, after_b)
    if absorb is not None:
        return min(last, absorb - 1)
    return last


def old_listed_hi(pair: dict) -> int | None:
    """Invalid cap used by the first sim: listed_start + 360 minutes."""
    return window_end(pair)


def inverted_old_clock(pair: dict) -> bool:
    t0 = pair.get("t0_ts")
    old_hi = old_listed_hi(pair)
    return t0 is not None and old_hi is not None and t0 > old_hi


def no_fill_at(no_ticks: list[tuple[int, float]], ts: int, yes_print: float) -> tuple[float, str]:
    hit = last_at_or_before(no_ticks, ts) if no_ticks else None
    if hit is not None:
        return hit[1], "no_ask"
    return round(1.0 - yes_print, 4), "complement"


def first_dip_no(yes_ticks: list[tuple[int, float]], no_ticks: list[tuple[int, float]], t0_px: float, lo: int, hi: int, dip: float) -> dict | None:
    thresh = t0_px - dip
    if thresh <= 0.05:
        return None
    for ts, px in yes_ticks:
        if ts <= lo or ts > hi:
            continue
        if px <= thresh + 1e-12:
            no_px, src = no_fill_at(no_ticks, ts, px)
            return {
                "ts": ts,
                "yes_print": px,
                "thresh": thresh,
                "no_px": no_px,
                "no_src": src,
                "overshoot": max(0.0, thresh - px),
            }
    return None


def payout_for(winner: str, hedge_a: bool, hedge_b: bool) -> float:
    # Always hold Yes A and Yes B: one of them pays $1.
    paid = 1.0
    if hedge_a and winner == "b":
        paid += 1.0
    if hedge_b and winner == "a":
        paid += 1.0
    return paid


def fee_of(venue: str, price: float) -> float:
    got = venue_fee(venue, price)
    return float(got) if got is not None else 0.0


def simulate_pair(pair: dict) -> None:
    pair["dips"] = {}
    t0a, t0b, t0_ts = pair.get("t0_a"), pair.get("t0_b"), pair.get("t0_ts")
    if t0a is None or t0b is None or t0_ts is None:
        return
    lo = hedge_lo(pair)
    hi = live_hi(pair)
    pair["lo"] = lo
    pair["hi"] = hi
    if hi is None or lo is None:
        return
    c0 = t0a + t0b
    pair["c0"] = c0
    pair["hold_pnl"] = 1.0 - c0
    winner = pair.get("winner")
    for dip in DIPS:
        ha = first_dip_no(pair["yes_a"], pair["no_a"], t0a, lo, hi, dip)
        hb = first_dip_no(pair["yes_b"], pair["no_b"], t0b, lo, hi, dip)
        n_hedge = int(ha is not None) + int(hb is not None)
        cost = c0
        fees = fee_of(pair["venue"], t0a) + fee_of(pair["venue"], t0b)
        if ha:
            cost += ha["no_px"]
            fees += fee_of(pair["venue"], ha["no_px"])
        if hb:
            cost += hb["no_px"]
            fees += fee_of(pair["venue"], hb["no_px"])
        rec = {
            "dip": dip,
            "hedge_a": ha,
            "hedge_b": hb,
            "n_hedge": n_hedge,
            "mix": {0: "none", 1: "one", 2: "both"}[n_hedge],
            "cost": cost,
            "fees": fees,
            "cost_fee": cost + fees,
            "pnl": None,
            "pnl_fee": None,
            "payout": None,
        }
        if pair.get("settled") and winner in ("a", "b"):
            paid = payout_for(winner, ha is not None, hb is not None)
            rec["payout"] = paid
            rec["pnl"] = paid - cost
            rec["pnl_fee"] = paid - (cost + fees)
        pair["dips"][dip] = rec


def forward_quotes(ticks: list[tuple[int, float]], times: list[int]) -> dict[int, float]:
    out: dict[int, float] = {}
    i = 0
    last = None
    n = len(ticks)
    for t in times:
        while i < n and ticks[i][0] <= t:
            last = ticks[i][1]
            i += 1
        if last is not None:
            out[t] = last
    return out


def first_sum_lock(yes_ticks, no_ticks, t0_ts: int, hi: int, cap: float = LOCK_SUM) -> dict | None:
    if not yes_ticks or not no_ticks or hi is None:
        return None
    times = sorted({ts for ts, _ in yes_ticks if t0_ts < ts <= hi} | {ts for ts, _ in no_ticks if t0_ts < ts <= hi})
    if not times:
        return None
    fy = forward_quotes(yes_ticks, times)
    fn = forward_quotes(no_ticks, times)
    for t in times:
        y, n = fy.get(t), fn.get(t)
        if y is None or n is None:
            continue
        s = y + n
        if s <= cap + 1e-12:
            return {"ts": t, "yes": y, "no": n, "sum": s}
    return None


def first_two_yes_lock(yes_a, yes_b, t0_ts: int, hi: int, cap: float = LOCK_SUM) -> dict | None:
    if not yes_a or not yes_b or hi is None:
        return None
    times = sorted({ts for ts, _ in yes_a if t0_ts < ts <= hi} | {ts for ts, _ in yes_b if t0_ts < ts <= hi})
    if not times:
        return None
    fa = forward_quotes(yes_a, times)
    fb = forward_quotes(yes_b, times)
    for t in times:
        ya, yb = fa.get(t), fb.get(t)
        if ya is None or yb is None:
            continue
        s = ya + yb
        if s <= cap + 1e-12:
            return {"ts": t, "yes_a": ya, "yes_b": yb, "sum": s}
    return None


def is_competitive(pair: dict) -> bool:
    a, b = pair.get("t0_a"), pair.get("t0_b")
    if a is None or b is None:
        return False
    return 0.10 < a < 0.90 and 0.10 < b < 0.90


def match_id(pair: dict) -> tuple:
    names = tuple(sorted(n for n in (last_name(pair["side_a"]), last_name(pair["side_b"])) if n))
    start_dt = pair.get("start_dt")
    day = start_dt.date().isoformat() if start_dt is not None else ""
    return (names, day)


def simulate_current_lock(pairs: list[dict]) -> None:
    by_id: dict[tuple, list[dict]] = defaultdict(list)
    for pair in pairs:
        by_id[match_id(pair)].append(pair)
    for pair in pairs:
        pair["cur_lock"] = None
        pair["two_yes_lock"] = None
        t0_ts = pair.get("t0_ts")
        lo = pair.get("lo") if pair.get("lo") is not None else hedge_lo(pair)
        hi = pair.get("hi")
        if t0_ts is None or hi is None or lo is None:
            continue
        pair["two_yes_lock"] = first_two_yes_lock(pair["yes_a"], pair["yes_b"], lo, hi)
        cands = []
        same_a = first_sum_lock(pair["yes_a"], pair["no_a"], lo, hi)
        same_b = first_sum_lock(pair["yes_b"], pair["no_b"], lo, hi)
        if same_a:
            cands.append({**same_a, "kind": "same_player_same_venue", "player": pair["side_a"], "yes_venue": pair["venue"], "no_venue": pair["venue"]})
        if same_b:
            cands.append({**same_b, "kind": "same_player_same_venue", "player": pair["side_b"], "yes_venue": pair["venue"], "no_venue": pair["venue"]})
        my_last = {last_name(pair["side_a"]): "a", last_name(pair["side_b"]): "b"}
        for other in by_id.get(match_id(pair), []):
            if other is pair:
                continue
            for side_name, letter in ((other["side_a"], "a"), (other["side_b"], "b")):
                ln = last_name(side_name)
                mine = my_last.get(ln)
                if not mine:
                    continue
                my_yes = pair["yes_a"] if mine == "a" else pair["yes_b"]
                my_no = pair["no_a"] if mine == "a" else pair["no_b"]
                o_yes = other["yes_a"] if letter == "a" else other["yes_b"]
                o_no = other["no_a"] if letter == "a" else other["no_b"]
                player = pair["side_a"] if mine == "a" else pair["side_b"]
                cross1 = first_sum_lock(my_yes, o_no, lo, hi)
                if cross1:
                    cands.append({**cross1, "kind": "same_player_cross_venue", "player": player, "yes_venue": pair["venue"], "no_venue": other["venue"]})
                cross2 = first_sum_lock(o_yes, my_no, lo, hi)
                if cross2:
                    cands.append({**cross2, "kind": "same_player_cross_venue", "player": player, "yes_venue": other["venue"], "no_venue": pair["venue"]})
        if not cands:
            pair["cur_lock"] = {"taken": False}
            continue
        best = min(cands, key=lambda r: (r["ts"], r["sum"]))
        fees = fee_of(best.get("yes_venue") or "", best["yes"]) + fee_of(best.get("no_venue") or "", best["no"])
        taken = {
            "taken": True,
            "kind": best["kind"],
            "player": best.get("player") or "",
            "yes": best["yes"],
            "no": best["no"],
            "sum": best["sum"],
            "ts": best["ts"],
            "mins": mins_after(best["ts"], t0_ts),
            "mins_after_start": mins_after(best["ts"], lo),
            "yes_venue": best.get("yes_venue") or "",
            "no_venue": best.get("no_venue") or "",
            "fees": fees,
            "pnl": 1.0 - best["sum"] if pair.get("settled") else None,
            "pnl_fee": 1.0 - best["sum"] - fees if pair.get("settled") else None,
        }
        pair["cur_lock"] = taken


def summarize_d(pairs: list[dict], dip: float) -> dict:
    rows = [p for p in pairs if dip in (p.get("dips") or {})]
    recs = [p["dips"][dip] for p in rows]
    settled = [p for p in rows if p.get("settled") and p["dips"][dip].get("pnl") is not None]
    pnls = [p["dips"][dip]["pnl"] for p in settled]
    pnls_fee = [p["dips"][dip]["pnl_fee"] for p in settled if p["dips"][dip].get("pnl_fee") is not None]
    holds = [p["hold_pnl"] for p in settled if p.get("hold_pnl") is not None]
    costs = [p["dips"][dip]["cost"] for p in settled]
    n = len(rows)
    n_both = sum(1 for r in recs if r["n_hedge"] == 2)
    n_one = sum(1 for r in recs if r["n_hedge"] == 1)
    n_none = sum(1 for r in recs if r["n_hedge"] == 0)
    n_comp = 0
    n_ask = 0
    for r in recs:
        for h in (r.get("hedge_a"), r.get("hedge_b")):
            if not h:
                continue
            if h["no_src"] == "complement":
                n_comp += 1
            else:
                n_ask += 1
    both_comp_pnls = []
    for p in settled:
        r = p["dips"][dip]
        ha, hb = r.get("hedge_a"), r.get("hedge_b")
        if ha and hb and ha["no_src"] == "complement" and hb["no_src"] == "complement":
            both_comp_pnls.append(r["pnl"])
    mix_pnls = {k: [] for k in ("none", "one", "both")}
    for p in settled:
        r = p["dips"][dip]
        mix_pnls[r["mix"]].append(r["pnl"])
    wins = sum(1 for x in pnls if x > 1e-12)
    return {
        "dip": dip,
        "dip_cents": int(round(dip * 100)),
        "n": n,
        "n_settled": len(settled),
        "mean": mean(pnls),
        "median": median(pnls),
        "total": sum(pnls) if pnls else None,
        "win_pct": pct(wins, len(pnls)),
        "n_win": wins,
        "pct_both": pct(n_both, n),
        "pct_one": pct(n_one, n),
        "pct_none": pct(n_none, n),
        "n_both": n_both,
        "n_one": n_one,
        "n_none": n_none,
        "mean_cost": mean(costs),
        "mean_hold": mean(holds),
        "median_hold": median(holds),
        "mean_fee": mean(pnls_fee),
        "n_no_ask": n_ask,
        "n_complement": n_comp,
        "mean_both_comp": mean(both_comp_pnls),
        "n_both_comp": len(both_comp_pnls),
        "identity": -(2.0 * dip),
        "mean_none": mean(mix_pnls["none"]),
        "mean_one": mean(mix_pnls["one"]),
        "mean_both": mean(mix_pnls["both"]),
        "n_settled_none": len(mix_pnls["none"]),
        "n_settled_one": len(mix_pnls["one"]),
        "n_settled_both": len(mix_pnls["both"]),
        "note": tiny_note(len(settled)),
    }


def summarize_lock(pairs: list[dict]) -> dict:
    n = len(pairs)
    taken = [p for p in pairs if (p.get("cur_lock") or {}).get("taken")]
    settled = [p for p in pairs if p.get("settled")]
    settled_taken = [p for p in settled if (p.get("cur_lock") or {}).get("taken")]
    settled_miss = [p for p in settled if not (p.get("cur_lock") or {}).get("taken")]
    pnls = []
    for p in settled:
        lock = p.get("cur_lock") or {}
        if lock.get("taken") and lock.get("pnl") is not None:
            pnls.append(lock["pnl"])
        else:
            pnls.append(0.0)
    taken_pnls = [p["cur_lock"]["pnl"] for p in settled_taken if p["cur_lock"].get("pnl") is not None]
    two_yes = [p for p in pairs if p.get("two_yes_lock")]
    kinds = defaultdict(int)
    for p in taken:
        kinds[(p["cur_lock"] or {}).get("kind") or ""] += 1
    return {
        "n": n,
        "n_taken": len(taken),
        "pct_taken": pct(len(taken), n),
        "n_settled": len(settled),
        "n_settled_taken": len(settled_taken),
        "n_settled_miss": len(settled_miss),
        "mean_all_settled": mean(pnls),
        "median_all_settled": median(pnls),
        "mean_when_taken": mean(taken_pnls),
        "median_when_taken": median(taken_pnls),
        "total_when_taken": sum(taken_pnls) if taken_pnls else None,
        "win_pct_taken": pct(sum(1 for x in taken_pnls if x > 1e-12), len(taken_pnls)),
        "mean_sit_out": 0.0,
        "n_two_yes": len(two_yes),
        "pct_two_yes": pct(len(two_yes), n),
        "n_same_venue": kinds.get("same_player_same_venue", 0),
        "n_cross_venue": kinds.get("same_player_cross_venue", 0),
        "note": tiny_note(len(settled)),
    }


def identity_ok() -> dict:
    a0, b0, d = 0.69, 0.33, 0.05
    c = a0 + b0
    na = 1.0 - (a0 - d)
    nb = 1.0 - (b0 - d)
    total = c + na + nb
    ident = 2.0 + 2.0 * d
    return {
        "c": c,
        "c_ok": abs(c - 1.02) < 1e-12,
        "na": na,
        "nb": nb,
        "total": total,
        "ident": ident,
        "ident_ok": abs(total - ident) < 1e-12 and abs(total - 2.10) < 1e-12,
        "his_194": 1.02 + 0.64 + 0.28,
        "pnl": 2.0 - total,
    }


def et_iso(ts: int | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, ET).isoformat()


def hedge_cell(h: dict | None, t0_ts: int | None) -> str:
    if not h:
        return "no dip"
    src = "ask" if h["no_src"] == "no_ask" else "complement"
    mins = fmt_px(mins_after(h["ts"], t0_ts)) if t0_ts else ""
    return f"Yes {h['yes_print']:.3f} → No {h['no_px']:.3f} ({src}) @ {mins}m"


def named_pairs(pairs: list[dict], *needles: str) -> list[dict]:
    need = [n.lower() for n in needles]
    out = []
    for p in pairs:
        blob = " ".join([p.get("game") or "", p.get("side_a") or "", p.get("side_b") or ""]).lower()
        if all(n in blob for n in need):
            out.append(p)
    return out


def prizmic_pairs(pairs: list[dict]) -> list[dict]:
    return named_pairs(pairs, "prizmic", "dzumhur")


def tsitsi_pairs(pairs: list[dict]) -> list[dict]:
    return named_pairs(pairs, "tsitsipas", "kovacevic")


def zero_hedge_example_html() -> str:
    """Walk one settled 0-hedge book. Facts from price_memory, not a defense of the 69%."""
    rows = [
        {
            "when": "2026-10-18 16:12:26 ET",
            "venue": "Polymarket",
            "player": "Stefanos Tsitsipas",
            "pay": "Yes",
            "px": "0.800",
            "vs": "T0",
            "note": "Sim buys this Yes. First two-sided print we have (collection start), not listed start.",
        },
        {
            "when": "2026-10-18 16:12:26 ET",
            "venue": "Polymarket",
            "player": "Aleksandar Kovacevic",
            "pay": "Yes",
            "px": "0.210",
            "vs": "T0",
            "note": "Sim buys this Yes. C = 0.80 + 0.21 = 1.01.",
        },
        {
            "when": "2026-10-20 04:22:54 ET",
            "venue": "Polymarket",
            "player": "Aleksandar Kovacevic",
            "pay": "Yes",
            "px": "0.220",
            "vs": "+0.010",
            "note": "First Oct 20 Yes change. Live match tape. Sim window already closed two days earlier.",
        },
        {
            "when": "2026-10-20 04:28:34 ET",
            "venue": "Polymarket",
            "player": "Stefanos Tsitsipas",
            "pay": "Yes",
            "px": "0.750",
            "vs": "-0.050",
            "note": "Winner Yes prints exactly 5c below T0. Looser rule would buy No here.",
        },
        {
            "when": "2026-10-20 04:28:33 ET",
            "venue": "Polymarket",
            "player": "Stefanos Tsitsipas",
            "pay": "No",
            "px": "0.260",
            "vs": "",
            "note": "No ask on the tape at that Tsitsipas dip (complement would be 0.25).",
        },
        {
            "when": "2026-10-20 05:18:31 ET",
            "venue": "Polymarket",
            "player": "Aleksandar Kovacevic",
            "pay": "Yes",
            "px": "0.150",
            "vs": "-0.060",
            "note": "Loser Yes is 6c below T0. Looser rule would buy No. This is the 5c hedge Paul expected.",
        },
        {
            "when": "2026-10-20 05:18:31 ET",
            "venue": "Polymarket",
            "player": "Aleksandar Kovacevic",
            "pay": "No",
            "px": "0.860",
            "vs": "",
            "note": "No ask on the tape at that Kovacevic dip (complement would be 0.85).",
        },
        {
            "when": "2026-10-20 05:21:31 ET",
            "venue": "Polymarket",
            "player": "Aleksandar Kovacevic",
            "pay": "Yes",
            "px": "0.100",
            "vs": "-0.110",
            "note": "Loser still stepping down on the tape, not a one-tick gap to zero.",
        },
        {
            "when": "2026-10-20 06:06:57 ET",
            "venue": "Polymarket",
            "player": "Aleksandar Kovacevic",
            "pay": "Yes",
            "px": "0.050",
            "vs": "-0.160",
            "note": "First 5c absorbing print. Sim treats this as settlement and would stop the window here if the window were still open.",
        },
        {
            "when": "2026-10-20 06:22:23 ET",
            "venue": "Polymarket",
            "player": "Stefanos Tsitsipas",
            "pay": "Yes",
            "px": "0.980",
            "vs": "+0.180",
            "note": "Last Yes. Winner settled near 1.",
        },
        {
            "when": "2026-10-20 06:22:24 ET",
            "venue": "Polymarket",
            "player": "Aleksandar Kovacevic",
            "pay": "Yes",
            "px": "0.010",
            "vs": "-0.200",
            "note": "Last Yes. Loser settled near 0. Official winner: Tsitsipas.",
        },
    ]
    tbl = table(
        [
            ("When (ET)", "text"),
            ("Venue", "text"),
            ("Player", "text"),
            ("Pay", "text"),
            ("Price", "num"),
            ("vs T0 Yes", "text"),
            ("What this print is", "text"),
        ],
        rows,
        ["when", "venue", "player", "pay", "px", "vs", "note"],
    )
    return f"""
<div class="warn">
<h2>Does a 0-hedge match make sense? (clock bug — kept on purpose)</h2>
<p>Paul is right to doubt a quiet tape. The 69% &ldquo;never dipped 5 cents&rdquo; figure is <strong>not</strong> mostly matches that stayed still until the last point. It is the sim&rsquo;s clock, plus a pile of already-decided 99&cent;/1&cent; books.</p>
<p><strong>Example:</strong> Stefanos Tsitsipas vs Aleksandar Kovacevic, Polymarket tennis moneyline. Listed start Sunday 18 Oct 2026 05:00 ET (stale). Winner: <strong>Tsitsipas</strong>. T0 Yes: Tsitsipas <strong>0.80</strong>, Kovacevic <strong>0.21</strong> (C = 1.01) at 16:12:26 ET that same Sunday &mdash; the first two-sided print after our tape started, labeled &ldquo;first two-sided in-game.&rdquo;</p>
<p><strong>Why the sim said 0 hedges:</strong> it only looks for a dip <em>after</em> listed start and <em>before</em> listed start + 360 minutes. That window ends 18 Oct 11:00 ET. T0 is 16:12 ET the same day, so the search window is already over before T0. Hedge-lo (16:12) is after hedge-hi (11:00). Zero ticks can qualify. The live match prints are Tuesday 20 Oct ~04:22&ndash;06:22 ET &mdash; two days later, 1,084 Polymarket Yes change-ticks, Kovacevic Yes from 0.21 down through 0.15, 0.10, 0.05, then 0.01. The loser did not gap from 0.40 to 0.00 without a 5c step. The 5c step printed and the sim was not looking.</p>
<p><strong>Looser rule on the old page</strong> (&ldquo;did Yes ever print at least 5c below T0, even after the 6-hour cap / absorbing 5c print?&rdquo;): both names trigger. Tsitsipas Yes 0.75 at 04:28 with No ask 0.26; Kovacevic Yes 0.15 at 05:18 with No ask 0.86. Dual-Yes then both Nos would cost about 1.01 + 0.26 + 0.86 = <strong>$2.13</strong> to collect $2.00 (complement would be ~$2.11). So the tape had the dips; the identity still loses a dime-plus if you complete both Nos. The 0-hedge label is a clock bug, not a quiet match. We keep this example so the mistake stays visible.</p>
<p>Of 168 settled in-range books, 109 had 0 hedges at D = 5c. 80 of those 109 were lopsided (T0 already ~99&cent;/1&cent; &mdash; a 5c dip is blocked because the trigger would sit at or under 5c, which the sim treats as settlement). 29 were still competitive (both T0 Yes between 10c and 90c); 26 of those 29 had an empty search window, and 18 had this same inverted clock (T0 after listed-start + 6 hours). On 17 of the 29, the loser&rsquo;s Yes still printed at least 5c below T0 on the raw tape.</p>
<p>Same 0-hedge bucket, not one-offs:</p>
<ul>
<li>Ugo Humbert vs Corentin Moutet, Polymarket, T0 0.71 / 0.30, winner Moutet &mdash; inverted 6-hour window; 3,358 Yes change-ticks; loser Humbert Yes later 0.01, with a 5c dip printed 20 Oct 08:34.</li>
<li>Mariano Navone vs Juan Manuel Cerundolo, Polymarket, T0 0.60 / 0.41, winner Navone &mdash; inverted window; loser Cerundolo Yes later 0.01, 5c dip printed 20 Oct 06:44.</li>
<li>Matteo Arnaldi vs Lorenzo Musetti, Polymarket, T0 0.34 / 0.67, winner Musetti &mdash; inverted window; loser Arnaldi Yes later 0.01, 5c dip printed 19 Oct 11:21.</li>
</ul>
<p>A different miss, not inverted: Pacheco Mendez vs Rodriguez Taverna (Polymarket T0 0.64 / 0.37, Novig 0.38 / 0.63), winner Rodriguez Taverna. Window was open 20 Oct 15:10&ndash;21:10 ET, but the last Yes we stored is 14:08 still at those T0 prices &mdash; in-match quotes never arrived, so this one really is a missing tape, not a quiet match.</p>
<p>Click column headers to sort.</p>
{tbl}
</div>
"""


def tape_followup_html() -> str:
    """Wawrinka live tape + one current-sim mix=none book. Facts from price_memory, 2026-10-21."""
    waw_rows = [
        {
            "when": "2026-10-21 07:55:31 ET",
            "venue": "Kalshi",
            "player": "Martin Landaluce",
            "yes": "0.630",
            "no": "0.380",
            "dip": "T0",
            "note": "Last Yes at or before listed start 08:00. Sim would buy this Yes.",
        },
        {
            "when": "2026-10-21 07:55:31 ET",
            "venue": "Kalshi",
            "player": "Stan Wawrinka",
            "yes": "0.390",
            "no": "0.620",
            "dip": "T0",
            "note": "Sim would buy this Yes. C = 0.63 + 0.39 = 1.02. Competitive T0, not 99/1.",
        },
        {
            "when": "2026-10-21 08:00:02 ET",
            "venue": "Kalshi",
            "player": "Martin Landaluce",
            "yes": "0.640",
            "no": "0.390",
            "dip": "+0.010",
            "note": "First in-match print. Gap from last pre-start tick: 5 seconds.",
        },
        {
            "when": "2026-10-21 08:11:44 ET",
            "venue": "Kalshi",
            "player": "Martin Landaluce",
            "yes": "0.580",
            "no": "0.430",
            "dip": "-0.050",
            "note": "First D=5 trigger. first_dip_no: Yes 0.58 ≤ T0 0.63 − 0.05. Would buy this No.",
        },
        {
            "when": "2026-10-21 08:58:43 ET",
            "venue": "Kalshi",
            "player": "Martin Landaluce",
            "yes": "0.200",
            "no": "0.820",
            "dip": "-0.430",
            "note": "Max Landaluce dip vs T0: 43 cents (to 20c). Paul said ~39c on one name — same story.",
        },
        {
            "when": "2026-10-21 09:22:43 → 09:30:38 ET",
            "venue": "Kalshi / Polymarket",
            "player": "(gap)",
            "yes": "",
            "no": "",
            "dip": "",
            "note": "Largest in-match hole: 475 seconds. Dedicated live poller spawned at 09:30:44.",
        },
        {
            "when": "2026-10-21 09:48:49 ET",
            "venue": "Kalshi",
            "player": "Stan Wawrinka",
            "yes": "0.340",
            "no": "0.670",
            "dip": "-0.050",
            "note": "First D=5 trigger on Wawrinka. Yes 0.34 ≤ T0 0.39 − 0.05. Would buy this No.",
        },
        {
            "when": "2026-10-21 09:50:28 ET",
            "venue": "Kalshi",
            "player": "Stan Wawrinka",
            "yes": "0.190",
            "no": "0.820",
            "dip": "-0.200",
            "note": "Max Wawrinka dip vs T0: 20 cents (to 19c). Paul said ~17c on the other name.",
        },
        {
            "when": "2026-10-21 10:27:09 ET",
            "venue": "Kalshi",
            "player": "Stan Wawrinka",
            "yes": "0.510",
            "no": "0.500",
            "dip": "+0.120",
            "note": "Still live on this dump. Both Yes back near 50c. Match not settled.",
        },
        {
            "when": "2026-10-21 10:27:09 ET",
            "venue": "Kalshi",
            "player": "Martin Landaluce",
            "yes": "0.500",
            "no": "0.510",
            "dip": "-0.130",
            "note": "Same snapshot. Gemini and Novig never quoted this book.",
        },
    ]
    none_rows = [
        {
            "when": "2026-10-20 00:44:54 ET",
            "venue": "Novig",
            "player": "R. Pacheco Mendez",
            "yes": "0.805",
            "no": "",
            "dip": "",
            "note": "First two-sided Novig Yes we have. Pre-start. Overnight-style scan is writing.",
        },
        {
            "when": "2026-10-20 00:44:54 ET",
            "venue": "Novig",
            "player": "S. Rodriguez Taverna",
            "yes": "0.270",
            "no": "",
            "dip": "",
            "note": "Same first two-sided print.",
        },
        {
            "when": "2026-10-20 14:07:43 ET",
            "venue": "Novig",
            "player": "R. Pacheco Mendez",
            "yes": "0.750",
            "no": "0.340",
            "dip": "",
            "note": "Still pre-start. Book is moving. We are collecting.",
        },
        {
            "when": "2026-10-20 14:07:43 ET",
            "venue": "Novig",
            "player": "S. Rodriguez Taverna",
            "yes": "0.340",
            "no": "0.750",
            "dip": "",
            "note": "Same timestamp.",
        },
        {
            "when": "2026-10-20 14:08:25 ET",
            "venue": "Novig",
            "player": "S. Rodriguez Taverna",
            "yes": "0.375",
            "no": "0.630",
            "dip": "T0",
            "note": "Last Yes at or before listed start 15:10. Sim buys this Yes. T0 label: last Yes ≤ start.",
        },
        {
            "when": "2026-10-20 14:08:25 ET",
            "venue": "Novig",
            "player": "R. Pacheco Mendez",
            "yes": "0.630",
            "no": "0.375",
            "dip": "T0",
            "note": "Sim buys this Yes. C = 0.375 + 0.630 = 1.005. Competitive T0 (both 10–90c).",
        },
        {
            "when": "2026-10-20 15:10:00 ET",
            "venue": "Novig",
            "player": "(listed start)",
            "yes": "",
            "no": "",
            "dip": "",
            "note": "Hedge-lo. Zero Yes prints at or after this time. Tape is already 62 minutes stale.",
        },
        {
            "when": "after 14:08:25 ET",
            "venue": "Novig",
            "player": "(silence)",
            "yes": "",
            "no": "",
            "dip": "",
            "note": "0 in-match ticks. Last stored Yes vs match end: we never saw the match. Mix = none.",
        },
    ]
    waw_tbl = table(
        [
            ("When (ET)", "text"),
            ("Venue", "text"),
            ("Player", "text"),
            ("Yes", "num"),
            ("No ask", "num"),
            ("vs T0 Yes", "text"),
            ("What this print is", "text"),
        ],
        waw_rows,
        ["when", "venue", "player", "yes", "no", "dip", "note"],
    )
    none_tbl = table(
        [
            ("When (ET)", "text"),
            ("Venue", "text"),
            ("Player", "text"),
            ("Yes", "num"),
            ("No ask", "num"),
            ("vs T0 Yes", "text"),
            ("What this print is", "text"),
        ],
        none_rows,
        ["when", "venue", "player", "yes", "no", "dip", "note"],
    )
    return f"""
<div class="hl">
<h2>Wawrinka vs Landaluce on our tape</h2>
<p>Live ATP moneyline, still open on this dump (21 Oct 2026 ~10:28 ET). Listed start <strong>08:00 ET</strong>. Kalshi ticker KXATPMATCH-26OCT18WAWLAN (stale Oct 18 date in the key; actual start today). Polymarket slug aec-atp-stawaw-marlan-2026-10-18. Gemini and Novig: not quoted. Dedicated poller <code>tennis_wawlan_2026_10_18</code> is on websocket Kalshi + Polymarket; it spawned at 09:30:44 ET, 90 minutes after listed start.</p>
<p><strong>T0 (last Yes ≤ start):</strong> Kalshi Landaluce <strong>0.63</strong> / Wawrinka <strong>0.39</strong> at 07:55:31 ET, C = 1.02. Polymarket 0.63 / 0.38 at 07:45:20, C = 1.01. Both books are competitive (10–90c), not a 99/1 blowout.</p>
<p><strong>Max dip vs T0 after listed start:</strong> Kalshi Landaluce <strong>43c</strong> (Yes 0.63 → 0.20 at 08:58:43) and Wawrinka <strong>20c</strong> (0.39 → 0.19 at 09:50:28). Polymarket 42c and 19c. Paul saw about 39c and 17c on the live screen — same match, a few cents off depending on T0 and ask vs midpoint. Both names printed a 5c dip. <strong>D = 5 would hedge both</strong> (mix = both). This live game is not in the settled none bucket.</p>
<p><strong>How often we sampled:</strong> Kalshi 5,922 moneyline prints (2,770 pre-start, 3,152 in-match), 586 + 590 Yes change-ticks. Polymarket 12,510 prints (8,964 pre, 3,546 in-match), 634 + 686 Yes change-ticks. Hand-off at listed start is 5 seconds on Kalshi, 31 seconds on Polymarket. Largest in-match gap is <strong>475 seconds</strong> (09:22:43–09:30:38), which is the hole before the dedicated poller started. After 09:30 the websocket is dense (Kalshi ~4,800 book updates in the first hour of that poller).</p>
<p><strong>Are we collecting enough on this match?</strong> Yes for a live Kalshi + Polymarket tennis book: hundreds of in-match Yes change-ticks, both 5c dips are on tape, D = 5 would fire. We are not missing a 39c/17c swing. The 61.9% none figure is not this match, and this match does not excuse that figure.</p>
<p>Click column headers to sort. Swipe sideways to see more columns. Table is a highlight tape (T0, first in-match, first D=5 each, max dip each, last), not every tick.</p>
{waw_tbl}
</div>
<div class="warn">
<h2>A no-hedge game, tick by tick</h2>
<p>The current clock-fixed sim (page freeze at 10:12 ET) labels D = 5 mix = none on 185 of 299 in-range books (61.9%). Of the 80 settled rows in the cap table, 60 are none and <strong>only one is competitive T0</strong> (both Yes between 10c and 90c). That book is <strong>Pacheco Mendez vs Rodriguez Taverna, Novig</strong>. The other 59 none rows in that cap are 99/1-style books. The none bucket is not “quiet matches.”</p>
<p><strong>T0:</strong> last Yes ≤ listed start 20 Oct 2026 15:10 ET. Novig Rodriguez Taverna Yes <strong>0.375</strong>, Pacheco Mendez Yes <strong>0.630</strong>, C = 1.005, at 14:08:25 ET. Winner: Rodriguez Taverna. Stand-pat P&amp;L −$0.005. Official settled. Same match on Polymarket T0 0.64 / 0.37, also empty after T0.</p>
<p><strong>Why the sim said no hedge:</strong> <code>first_dip_no</code> in <code>tools/tennis_dual_yes_dip_no_20261021.py</code> only counts a Yes print with <code>ts &gt; lo</code> and <code>ts ≤ hi</code> and <code>px ≤ T0 − 0.05</code> (and the trigger itself must sit above 5c). <code>hedge_lo</code> is listed start when listed start is later than T0, so lo = 15:10. Last Yes we stored is 14:08. After the clock fix, <code>live_hi</code> is that last quote (14:08), so hi &lt; lo. Every tick fails <code>if ts &lt;= lo or ts &gt; hi: continue</code>. Both <code>hedge_a</code> and <code>hedge_b</code> stay <code>None</code>, <code>n_hedge = 0</code>, <code>mix = &quot;none&quot;</code>. Not a missing No ask, not a 99/1 block (<code>thresh</code> would be 0.325 and 0.580, both above 5c). Empty window: 101 Novig Yes change-ticks, all before start, <strong>0 after T0</strong>. Max gap on the stored tape 6,563 seconds (12:00–13:49, still pre-start). Last tick vs match end: we never saw the match.</p>
<p><strong>Poller cadence:</strong> <code>price_memory.remember_books</code> writes every pay-price change, and the same price again only if it is more than 20 seconds old — not lock-only quotes. Live tennis pollers (<code>tools/live_game_pollers.py</code> <code>tennis_rows</code>) spawn only for a Kalshi ATP/Challenger moneyline that has a Polymarket US twin, then stay on websocket and compare on each book update (50 ms coalesce). HTTP fallback is every 20 seconds. Pre-match density on this Novig book is real; in-match density is zero because no Kalshi twin, so no live poller, and the daytime scan stopped at 14:08. That is the bug Paul is smelling: we collect throughout a match only when a live websocket poller is up. Otherwise the tape dies before T0 and the sim reports “never dipped.”</p>
<p>Click column headers to sort.</p>
{none_tbl}
</div>
"""


def write_html(payload: dict) -> None:
    now = payload["written_at"]
    stream = payload["stream"]
    ident = payload["identity"]
    drows = payload["d_rows"]
    lock = payload["lock"]
    sweet = payload["sweet"]
    priz = payload["priz_html"]
    note_n = payload["note_n"]
    def d_to_rows(src):
        out = []
        for r in src:
            out.append({
            "dip": f"{r['dip_cents']}¢",
            "n": r["n"],
            "n_settled": r["n_settled"],
            "mean": fmt_signed(r["mean"]),
            "median": fmt_signed(r["median"]),
            "total": fmt_signed(r["total"]),
            "win_pct": r["win_pct"],
            "pct_both": r["pct_both"],
            "pct_one": r["pct_one"],
            "pct_none": r["pct_none"],
            "n_both": r["n_both"],
            "n_one": r["n_one"],
            "n_none": r["n_none"],
            "mean_cost": fmt_px(r["mean_cost"]),
            "mean_hold": fmt_signed(r["mean_hold"]),
            "mean_fee": fmt_signed(r["mean_fee"]),
            "mean_none": fmt_signed(r["mean_none"]),
            "mean_one": fmt_signed(r["mean_one"]),
            "mean_both": fmt_signed(r["mean_both"]),
            "n_both_comp": r["n_both_comp"],
            "mean_both_comp": fmt_signed(r["mean_both_comp"]),
            "identity": fmt_signed(r["identity"]),
            "n_no_ask": r["n_no_ask"],
            "n_complement": r["n_complement"],
            "note": r["note"],
        })
        return out
    d_table_rows = d_to_rows(drows)
    d_comp_rows = d_to_rows(payload.get("d_comp_rows") or [])
    cmp_rows = payload.get("compare_rows") or compare_rows(drows, lock)
    lock_rows = [{
        "book": "Current Yes+No ≤ $0.95 (no T0 buy)",
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
    sweet_label = f"{sweet['dip_cents']}¢" if sweet else "n/a"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis dual-Yes then dip-No 2026-10-21</title>
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
<h1>Tennis: buy both Yes at T0, then No on each dip</h1>
<p class="note">Written {esc(now)}. Clock-fix rerun of the dual-Yes then dip-No tennis sim. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Short October 2026 live tape — no in-sample / out-of-sample split. Verdict on this tape: <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
<p>Worked identity, D = 5 cents, his 0.69 / 0.33 book: C = 0.69 + 0.33 = <strong>1.02</strong> (confirmed). Stand-pat always pays $1, so P&amp;L = 1 − 1.02 = −$0.02. If both Yes then print exactly 5 cents lower (0.64 and 0.28) and each No is the complement: No Prizmic = 1 − 0.64 = 0.36, No Dzumhur = 1 − 0.28 = 0.72. Total = 1.02 + 0.36 + 0.72 = <strong>$2.10</strong> = 2 + 2×0.05. You always collect $2. P&amp;L = −$0.10. His 1.02+0.64+0.28 = 1.94 mixed the dipped Yes (0.64) with a No example (0.28). That 1.94 is not a cost you can pay. The first example 1.02+0.43+0.28 = 1.73 would be a +$0.27 lock <em>if</em> those 0.43 and 0.28 prints were real No asks — cheaper than complement. We do not assume that; we take the tape's No ask, or label complement.</p>
</div>

{payload.get('tape_followup_html') or tape_followup_html()}
{payload['zero_hedge_html']}
{payload.get('tsitsi_fixed_html') or ''}

<div class="hl">
<p><strong>Does the idea make sense?</strong> The intent does: do not add only one hedge; try to complete Yes+No on <em>each</em> player after that player's Yes dips, and skip the No when that player never dips (betting the unhedged Yes is the winner). The 5-cent both-hedge arithmetic does not: if both Nos fill at 1 − dipped Yes, you pay $2.10 to win $2.00 and lose a dime. Path-dependent wins need a cheap actual No, or only one hedge that pays (the dipped player loses). That is an empirical question, not the identity.</p>
<p><strong>Clock fix:</strong> {esc(payload.get('clock_fix_text') or '')}</p>
<p><strong>Sweet spot on this tape:</strong> {esc(payload['sweet_text'])}</p>
<p><strong>Versus the current lock:</strong> {esc(payload['vs_lock_text'])}</p>
<p>ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. T0 is match start. Vig is the overround when two Yes prices sum over $1.</p>
</div>

<div class="warn">
<p>Primary P&amp;L is without fees. Optional fee line uses the house venue formulas (Kalshi 0.07×p×(1−p) to a ten-thousandth; Gemini same raw rounded up to a cent; Polymarket 0.0695×p×(1−p) banker-cent). Novig fills get $0 fee in this optional line because we do not invent one. Optimistic fills at print. Complement No ignores No vig. Do not buy after the first 5¢ / 95¢ absorbing print — that is settlement, not an in-match dip.</p>
<p>N settled {payload['n_settled']}. {esc(note_n)} Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Research only. Not gold. Not DailyRun. Do not send this plan.</p>
</div>

<h2>Freeze</h2>
<ul>
<li>Universe: tennis moneyline, exactly two named Yes sides on the same game and venue, T0 Yes A + Yes B in [{C_LO:.2f}, {C_HI:.2f}].</li>
<li>T0: last Yes at or before listed start for both sides; else first two-sided in-game print, labeled.</li>
<li>Buy 1 Yes each at T0 asks. Then independently, first time that player's Yes ≤ T0 − D after T0 (and after listed start only when listed start is later than T0, so remaining pre-start quotes are not hedges) and before the last live quote prior to settlement, buy 1 No. Window is T0 through last live Yes/No before the first 5¢ or 95¢ Yes print. <strong>Not</strong> listed start + {TENNIS_MIN} minutes — that old cap inverted the clock when listed start was stale (T0 after listed-start + 6 hours). Tuesday in-match tape is included on delayed matches. One No per player max. A second table keeps only books where both T0 Yes prices sit between 10¢ and 90¢, so 99¢/1¢ decided books are not mixed into that slice.</li>
<li>No fill = last No ask at or before that timestamp if the tape has one; else 1 − Yes print, labeled complement (optimistic).</li>
<li>P&amp;L from official Kalshi / Gemini / same-game settlement. Unsettled rows are out of P&amp;L means and still count in both/one/zero hedge mix.</li>
<li>Current desk compare: do not buy at T0. First time some Yes+No on the same player (this venue or another venue for the same last-name pair and start day) sums to $0.95 or less. If it never prints, P&amp;L = $0 (sit out). Two-Yes ≤ $0.95 is a sibling lock, counted separately, not the current Yes+No send rule.</li>
<li>Tape: <code>{esc(stream.get('history') or '')}</code>. Tennis moneyline change-ticks {stream.get('n_hits') or 0:,} of {stream.get('n_lines') or 0:,} lines. First quote {esc(stream.get('seen_min') or '')}. Last quote {esc(stream.get('seen_max') or '')}. Two-sided tennis books {payload['n_pairs']}. In range {payload['n_in']}. Unique last-name+day matches {payload['n_unique']}. Old inverted listed-start+360 clocks: {payload.get('n_inverted_old') or 0} of {payload['n_in']} in-range books ({esc(payload.get('pct_inverted_old') or '')}).</li>
</ul>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>

<h2>1. Identity check (not the tape)</h2>
<p class="note">These numbers are the worked example, not our prints. 0.69+0.33 = {fmt_px(ident['c'])} ({'confirmed' if ident['c_ok'] else 'MISMATCH'}). Complement both-hedge total {fmt_px(ident['total'])} vs 2+2D = {fmt_px(ident['ident'])} ({'match' if ident['ident_ok'] else 'MISMATCH'}). P&amp;L {fmt_signed(ident['pnl'])}. His mixed 1.02+0.64+0.28 = {fmt_px(ident['his_194'])}.</p>

<h2>2. Per dip D — dual-Yes then No on each independent dip</h2>
<p class="note">Mean / median / total / win rate (P&amp;L &gt; 0) are settled books only. Hedge mix (both / one / none) is every in-range book, including unsettled. Stand-pat is $1 − C on the same settled rows. Sweet spot is the D with the best mean dollar P&amp;L. HOLD if N is tiny. Identity column is −2D, the both-hedge complement loss if both dip exactly D.</p>
{table(
    [("D", "text"), ("N books", "num"), ("N settled", "num"), ("Mean $", "num"), ("Median $", "num"),
     ("Total $", "num"), ("Win rate %", "num"),
     ("% both hedges", "num"), ("% one hedge", "num"), ("% no hedge", "num"),
     ("N both", "num"), ("N one", "num"), ("N none", "num"),
     ("Mean cost", "num"), ("Mean stand-pat $1−C", "num"),
     ("Mean $ after fees", "num"),
     ("Mean $ if no hedge", "num"), ("Mean $ if one hedge", "num"), ("Mean $ if both hedges", "num"),
     ("N both at complement", "num"), ("Mean $ both-complement", "num"), ("Identity −2D", "num"),
     ("No fills that were asks", "num"), ("No fills that were complement", "num"),
     ("Note", "text")],
    d_table_rows,
    ["dip", "n", "n_settled", "mean", "median", "total", "win_pct",
     "pct_both", "pct_one", "pct_none", "n_both", "n_one", "n_none",
     "mean_cost", "mean_hold", "mean_fee",
     "mean_none", "mean_one", "mean_both",
     "n_both_comp", "mean_both_comp", "identity",
     "n_no_ask", "n_complement", "note"],
)}

<h3>Same Ds, competitive T0 only (both Yes between 10¢ and 90¢)</h3>
<p class="note">Drops 99¢/1¢ and other already-decided books that still sum to $0.95–$1.20. This is the slice that matches “both players still have a live price.” Sweet spot in the yellow box uses the full 0.95–1.20 universe; use this table if those blowouts are noise.</p>
{table(
    [("D", "text"), ("N books", "num"), ("N settled", "num"), ("Mean $", "num"), ("Median $", "num"),
     ("Total $", "num"), ("Win rate %", "num"),
     ("% both hedges", "num"), ("% one hedge", "num"), ("% no hedge", "num"),
     ("N both", "num"), ("N one", "num"), ("N none", "num"),
     ("Mean cost", "num"), ("Mean stand-pat $1−C", "num"),
     ("Mean $ after fees", "num"),
     ("Mean $ if no hedge", "num"), ("Mean $ if one hedge", "num"), ("Mean $ if both hedges", "num"),
     ("N both at complement", "num"), ("Mean $ both-complement", "num"), ("Identity −2D", "num"),
     ("No fills that were asks", "num"), ("No fills that were complement", "num"),
     ("Note", "text")],
    d_comp_rows,
    ["dip", "n", "n_settled", "mean", "median", "total", "win_pct",
     "pct_both", "pct_one", "pct_none", "n_both", "n_one", "n_none",
     "mean_cost", "mean_hold", "mean_fee",
     "mean_none", "mean_one", "mean_both",
     "n_both_comp", "mean_both_comp", "identity",
     "n_no_ask", "n_complement", "note"],
)}

<h2>2b. Control vs candidate — this plan vs current lock</h2>
<p class="note">Control is the current desk: do not buy both Yes at T0; wait for some Yes+No on the same player (same venue or the other venue) summing to $0.95 or less; sit out $0 if it never prints. Candidates are dual-Yes at T0 then independent dip-No at each D after the clock fix. Mean / median deltas are candidate minus control (all-settled dollars, lock zeros included). Annualized rate of return (Ann ROR), in-sample Ann ROR, out-of-sample Ann ROR, Max DD, Calmar, Sharpe, capital days, days held, Paul Score, and FIT are <strong>n/a</strong> — this is a same-day tennis-contract tape, not a stock book with hold days or an equity curve, and there is no 2024-01-01 IS/OOS split. Click column headers to sort.</p>
{table(
    [("Arm", "text"), ("Role", "text"), ("N books", "num"), ("N settled", "num"),
     ("Mean $", "num"), ("Median $", "num"), ("Total $", "num"), ("Win rate %", "num"),
     ("Mean cost", "num"), ("% both hedges / taken", "num"), ("% one hedge", "num"), ("% none / sit out", "num"),
     ("Δ mean $ vs lock", "num"), ("Δ median $ vs lock", "num"),
     ("Ann ROR full", "text"), ("Ann ROR IS", "text"), ("Ann ROR OOS", "text"),
     ("Max DD", "text"), ("Calmar", "text"), ("Sharpe", "text"),
     ("Note", "text")],
    cmp_rows,
    ["arm", "role", "n", "n_settled", "mean", "median", "total", "win_pct",
     "mean_cost", "pct_both", "pct_one", "pct_none", "d_mean", "d_med",
     "ann_ror", "ann_ror_is", "ann_ror_oos", "max_dd", "calmar", "sharpe", "note"],
)}

<h2>3. Current desk: wait for Yes+No ≤ $0.95, do not buy both at T0</h2>
<p class="note">Same tennis two-sided books. Sit-out P&amp;L is $0 when the lock never prints. Mean $ on all settled includes those zeros. Mean when taken should be about +$0.05 or more (locked $1 minus the pair). Same-venue is Yes+No on one player at this venue. Cross-venue is Yes at one venue + No at another for the same player. Two-Yes ≤ $0.95 is shown as a sibling count only — that is a lock too, but it is not the current Yes+No send rule.</p>
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

<h2>4. Prizmic vs Dzumhur — our prints, not the 0.69 / 0.33 story</h2>
<p class="note">His 0.69 + 0.33 = 1.02 example is confirmed as arithmetic. The walkthrough below uses this tape's T0 asks and later prints. If several venues listed the match, each two-sided book is a row.</p>
{priz}

<h2>5. Settled books at the 5-cent dip (cap 80)</h2>
<p class="note">One row per two-sided book. Mix is how many Nos we actually bought at D = 5 cents. Click headers to sort.</p>
{table(
    [("Match", "text"), ("Venue", "text"), ("T0 label", "text"),
     ("Yes A", "text"), ("T0 A", "num"), ("Yes B", "text"), ("T0 B", "num"), ("C", "num"),
     ("Stand-pat $1−C", "num"), ("A hedge", "text"), ("B hedge", "text"),
     ("Mix", "text"),      ("Cost", "num"), ("Payout", "num"), ("P&L", "num"),
     ("Winner", "text"), ("Official", "text")],
    payload["detail05"],
    ["game", "venue", "t0_label", "side_a", "t0_a", "side_b", "t0_b", "c0",
     "hold", "hedge_a", "hedge_b", "mix", "cost", "payout", "pnl", "winner", "official"],
)}

<h2>How to read this</h2>
<ul>
<li>Buying both Yes at T0 pays the vig up front. Completing both Nos at complement after a D dip pays another 2D on top of that vig. For 5 cents that extra is a dime, which is why 1.94 was never the cost.</li>
<li>The strategy can still print a positive mean if most matches hedge only the loser (asymmetric) or if No asks are inside the Yes complement. Look at mean $ if one hedge vs both. If both-hedge mean sits near −2D, the identity won.</li>
<li>Current lock sits out unless a real Yes+No (not a complement) sums to $0.95. That is rarer and locked. Dual-Yes is always in and usually long the vig.</li>
<li>Sweet spot among 5 / 10 / 15 / 20 / 25 is whichever D had the best mean dollar P&amp;L on settled books. KEEP / HOLD / DISMISS is on quality versus the current lock, not trade count. Research only. Not gold. Not DailyRun. Do not send this plan.</li>
</ul>
<p class="note">Acronyms: ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. T0 is match start. Vig is the overround in two Yes prices summing over $1. IOC is immediate-or-cancel (not used on this page).</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def clock_stats(pairs: list[dict]) -> dict:
    n = len(pairs)
    n_inv = sum(1 for p in pairs if inverted_old_clock(p))
    n_empty_new = 0
    for p in pairs:
        lo, hi = p.get("lo"), p.get("hi")
        if lo is None or hi is None or hi <= lo:
            n_empty_new += 1
    return {
        "n": n,
        "n_inverted_old": n_inv,
        "pct_inverted_old": pct(n_inv, n),
        "n_empty_new": n_empty_new,
        "pct_empty_new": pct(n_empty_new, n),
    }


def describe_fixed_tsitsi(pairs: list[dict]) -> str:
    found = tsitsi_pairs(pairs)
    if not found:
        return (
            "<p><strong>This rerun (clock fixed):</strong> Tsitsipas vs Kovacevic was not on the "
            "two-sided tennis tape after the clock fix. That is a missing book, not a quiet match.</p>"
        )
    chunks = [
        '<div class="hl">',
        "<h2>This rerun — same match, clock fixed</h2>",
        "<p>Hedge window is now T0 through the last live quote before a 5¢ / 95¢ Yes (no listed-start + 360 cap). "
        "Tuesday 20 Oct prints are in the window. Independent No on each player at the first D dip.</p>",
    ]
    for p in found:
        t0a, t0b = p.get("t0_a"), p.get("t0_b")
        tsitsi_is_a = "tsitsipas" in (p.get("side_a") or "").lower()
        if tsitsi_is_a:
            t_side, k_side = p.get("side_a"), p.get("side_b")
            t_t0, k_t0 = t0a, t0b
        else:
            t_side, k_side = p.get("side_b"), p.get("side_a")
            t_t0, k_t0 = t0b, t0a
        old_hi = old_listed_hi(p)
        rec05 = (p.get("dips") or {}).get(0.05) or {}
        ha, hb = rec05.get("hedge_a"), rec05.get("hedge_b")
        if tsitsi_is_a:
            ht, hk = ha, hb
        else:
            ht, hk = hb, ha
        both = ht is not None and hk is not None
        fill_txt = (
            f"both Nos filled at D = 5¢"
            if both
            else f"mix = {esc(rec05.get('mix') or 'none')} at D = 5¢ "
            f"(Tsitsipas {'filled' if ht else 'no dip'}, Kovacevic {'filled' if hk else 'no dip'})"
        )
        chunks.append(
            f"<p><strong>{esc(p.get('game') or '')}</strong> — {esc(p.get('venue') or '')}. "
            f"T0 {esc(p.get('t0_label') or '')} at {esc(et_iso(p.get('t0_ts')))}: "
            f"{esc(t_side)} Yes {fmt_px(t_t0)}, {esc(k_side)} Yes {fmt_px(k_t0)}, C = {fmt_px(p.get('c0'))}. "
            f"Old invalid hi (listed start + 360 min): {esc(et_iso(old_hi))}"
            f"{' — inverted vs T0' if inverted_old_clock(p) else ''}. "
            f"Fixed lo {esc(et_iso(p.get('lo')))}, fixed hi {esc(et_iso(p.get('hi')))} "
            f"(last live quote before 5¢/95¢). Winner {esc(p.get('side_a') if p.get('winner') == 'a' else p.get('side_b') if p.get('winner') == 'b' else '')}.</p>"
            f"<p>At D = 5¢: <strong>{esc(fill_txt)}</strong>. "
            f"Tsitsipas No: {esc(hedge_cell(ht, p.get('t0_ts')))}. "
            f"Kovacevic No: {esc(hedge_cell(hk, p.get('t0_ts')))}. "
            f"Cost {fmt_px(rec05.get('cost'))}, payout {fmt_px(rec05.get('payout'))}, "
            f"P&amp;L {fmt_signed(rec05.get('pnl'))}.</p>"
        )
        rows = []
        for dip in DIPS:
            rec = (p.get("dips") or {}).get(dip) or {}
            ha = rec.get("hedge_a")
            hb = rec.get("hedge_b")
            if tsitsi_is_a:
                ht, hk = ha, hb
            else:
                ht, hk = hb, ha
            rows.append({
                "dip": f"{int(round(dip * 100))}¢",
                "t_fill": hedge_cell(ht, p.get("t0_ts")),
                "k_fill": hedge_cell(hk, p.get("t0_ts")),
                "mix": rec.get("mix") or "",
                "cost": fmt_px(rec.get("cost")),
                "payout": fmt_px(rec.get("payout")),
                "pnl": fmt_signed(rec.get("pnl")),
            })
        chunks.append(table(
            [("D", "text"), ("Tsitsipas No fill", "text"), ("Kovacevic No fill", "text"),
             ("Mix", "text"), ("Cost", "num"), ("Payout", "num"), ("P&L", "num")],
            rows,
            ["dip", "t_fill", "k_fill", "mix", "cost", "payout", "pnl"],
        ))
    chunks.append("</div>")
    return "\n".join(chunks)


def compare_rows(d_rows: list[dict], lock: dict) -> list[dict]:
    out = []
    lock_mean = lock.get("mean_all_settled")
    lock_med = lock.get("median_all_settled")
    out.append({
        "arm": "Current Yes+No ≤ $0.95 (no T0 buy)",
        "role": "control",
        "n": lock["n"],
        "n_settled": lock["n_settled"],
        "mean": fmt_signed(lock_mean),
        "median": fmt_signed(lock_med),
        "total": fmt_signed(lock.get("total_when_taken")),
        "win_pct": lock.get("win_pct_taken"),
        "mean_cost": fmt_px(None) or "",
        "pct_both": lock.get("pct_taken"),
        "pct_one": "",
        "pct_none": pct(lock.get("n_settled_miss") or 0, lock.get("n_settled") or 0),
        "d_mean": "—",
        "d_med": "—",
        "ann_ror": "n/a",
        "ann_ror_is": "n/a",
        "ann_ror_oos": "n/a",
        "max_dd": "n/a",
        "calmar": "n/a",
        "sharpe": "n/a",
        "note": "Sit-out $0 when the lock never prints. Mean $ is all settled including those zeros. Win % is when taken.",
    })
    for r in d_rows:
        d_mean = ""
        d_med = ""
        if r["mean"] is not None and lock_mean is not None:
            d_mean = fmt_signed(r["mean"] - lock_mean)
        if r["median"] is not None and lock_med is not None:
            d_med = fmt_signed(r["median"] - lock_med)
        out.append({
            "arm": f"Dual-Yes then dip-No D={r['dip_cents']}¢",
            "role": "candidate",
            "n": r["n"],
            "n_settled": r["n_settled"],
            "mean": fmt_signed(r["mean"]),
            "median": fmt_signed(r["median"]),
            "total": fmt_signed(r["total"]),
            "win_pct": r["win_pct"],
            "mean_cost": fmt_px(r["mean_cost"]),
            "pct_both": r["pct_both"],
            "pct_one": r["pct_one"],
            "pct_none": r["pct_none"],
            "d_mean": d_mean,
            "d_med": d_med,
            "ann_ror": "n/a",
            "ann_ror_is": "n/a",
            "ann_ror_oos": "n/a",
            "max_dd": "n/a",
            "calmar": "n/a",
            "sharpe": "n/a",
            "note": r["note"],
        })
    return out


def decide_verdict(sweet: dict | None, lock: dict) -> tuple[str, str]:
    if sweet is None:
        return "HOLD", "No settled tennis books in range — no sweet spot. HOLD. Research only. Not gold. Not DailyRun."
    n = sweet["n_settled"]
    dual_mean = sweet["mean"]
    dual_med = sweet["median"]
    lock_mean = lock.get("mean_all_settled")
    label = f"{sweet['dip_cents']}¢"
    tiny = n < 20
    if tiny:
        return (
            "HOLD",
            f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
            f"median {fmt_signed(dual_med)}. HOLD — tiny N, not a send rule. Research only. Not gold. Not DailyRun.",
        )
    worse = dual_mean is not None and lock_mean is not None and dual_mean < lock_mean - 1e-12
    better = dual_mean is not None and lock_mean is not None and dual_mean > lock_mean + 1e-12
    if dual_mean is not None and dual_mean <= 0:
        tag = "DISMISS"
        why = (
            f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
            f"median {fmt_signed(dual_med)}. DISMISS on quality — best D is still at or below zero "
            f"versus a locked $1 payout. Current Yes+No lock all-settled mean {fmt_signed(lock_mean)} "
            f"(zeros when it never printed). Completing both Nos after a D dip pays about 2D extra "
            f"on top of the opening vig. Not gold. Not DailyRun. Do not send this plan."
        )
        if not worse and better:
            tag = "HOLD"
            why = (
                f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
                f"median {fmt_signed(dual_med)}. HOLD — mean is still ≤ 0 even if it beats the lock's "
                f"sit-out zeros. Research only. Not gold. Not DailyRun. Do not send this plan."
            )
        return tag, why
    if better:
        return (
            "HOLD",
            f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
            f"median {fmt_signed(dual_med)}, above the current lock all-settled mean "
            f"{fmt_signed(lock_mean)} (that lock mean includes $0 sit-outs; when taken, mean "
            f"{fmt_signed(lock.get('mean_when_taken'))} on {lock.get('n_settled_taken')} settled fills). "
            f"HOLD not KEEP: dual-Yes is always in and path-dependent; the lock cannot lose if it fills. "
            f"Research only. Not gold. Not DailyRun. Do not send this plan.",
        )
    if worse:
        return (
            "DISMISS",
            f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
            f"median {fmt_signed(dual_med)}, worse than the current lock all-settled mean "
            f"{fmt_signed(lock_mean)}. DISMISS versus the current Yes+No ≤ $0.95 sit-out. "
            f"Research only. Not gold. Not DailyRun. Do not send this plan.",
        )
    return (
        "HOLD",
        f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
        f"median {fmt_signed(dual_med)}, flat vs lock {fmt_signed(lock_mean)}. HOLD. "
        f"Research only. Not gold. Not DailyRun. Do not send this plan.",
    )


def priz_html(pairs: list[dict]) -> str:
    found = prizmic_pairs(pairs)
    if not found:
        return "<p class='note'>Prizmic vs Dzumhur was not on this tennis two-sided tape (in-range or not).</p>"
    chunks = []
    for p in found:
        t0a, t0b = p.get("t0_a"), p.get("t0_b")
        c0 = p.get("c0")
        if t0a is None or t0b is None:
            continue
        priz_is_a = "prizmic" in (p.get("side_a") or "").lower()
        if priz_is_a:
            priz_side, dz_side = p["side_a"], p["side_b"]
            priz_t0, dz_t0 = t0a, t0b
        else:
            priz_side, dz_side = p["side_b"], p["side_a"]
            priz_t0, dz_t0 = t0b, t0a
        rows = []
        for dip in DIPS:
            rec = (p.get("dips") or {}).get(dip) or {}
            ha = rec.get("hedge_a")
            hb = rec.get("hedge_b")
            if priz_is_a:
                hp, hd = ha, hb
            else:
                hp, hd = hb, ha
            rows.append({
                "dip": f"{int(round(dip * 100))}¢",
                "thresh_p": fmt_px(priz_t0 - dip),
                "thresh_d": fmt_px(dz_t0 - dip),
                "p_fill": hedge_cell(hp, p.get("t0_ts")),
                "d_fill": hedge_cell(hd, p.get("t0_ts")),
                "mix": rec.get("mix") or "",
                "cost": fmt_px(rec.get("cost")),
                "payout": fmt_px(rec.get("payout")),
                "pnl": fmt_signed(rec.get("pnl")),
                "hold": fmt_signed(p.get("hold_pnl")),
            })
        lock = p.get("cur_lock") or {}
        lock_txt = "no Yes+No ≤ $0.95 on this book"
        if lock.get("taken"):
            pnl_txt = fmt_signed(lock.get("pnl")) if lock.get("pnl") is not None else "pending"
            lock_txt = (
                f"{lock.get('kind')} {esc(lock.get('player') or '')}: "
                f"Yes {fmt_px(lock.get('yes'))} ({esc(lock.get('yes_venue') or '')}) + "
                f"No {fmt_px(lock.get('no'))} ({esc(lock.get('no_venue') or '')}) = {fmt_px(lock.get('sum'))} "
                f"at {fmt_px(lock.get('mins'))} min after T0. Locked P&amp;L {pnl_txt}."
            )
        off = f"{esc(p.get('side_a'))} {esc(p.get('off_a'))} / {esc(p.get('side_b'))} {esc(p.get('off_b'))} ({esc(p.get('off_src_a') or p.get('off_src_b') or 'pending')})"
        chunks.append(f"""
<div class="callout">
<p><strong>{esc(p.get('game') or '')}</strong> — {esc(p.get('venue') or '')}. T0 label: {esc(p.get('t0_label') or '')} at {esc(et_iso(p.get('t0_ts')))}.</p>
<p>Our T0: {esc(priz_side)} Yes {fmt_px(priz_t0)}, {esc(dz_side)} Yes {fmt_px(dz_t0)}, C = {fmt_px(c0)}. Stand-pat $1 − C = {fmt_signed(p.get('hold_pnl'))}. Official: {off}.</p>
<p>His example was 0.69 + 0.33 = 1.02. Ours is {fmt_px(priz_t0)} + {fmt_px(dz_t0)} = {fmt_px(c0)}{' — same 1.02 to the cent' if c0 is not None and abs(c0 - 1.02) < 0.005 else ''}.</p>
<p>Current desk on this book: {lock_txt}</p>
</div>
{table(
    [("D", "text"), ("Prizmic Yes trigger", "num"), ("Dzumhur Yes trigger", "num"),
     ("Prizmic No fill", "text"), ("Dzumhur No fill", "text"),
     ("Mix", "text"), ("Cost", "num"), ("Payout", "num"), ("P&L", "num"), ("Stand-pat", "num")],
    rows,
    ["dip", "thresh_p", "thresh_d", "p_fill", "d_fill", "mix", "cost", "payout", "pnl", "hold"],
)}
""")
    return "".join(chunks) if chunks else "<p class='note'>Prizmic vs Dzumhur had no usable T0 on this tape.</p>"


def detail_rows(pairs: list[dict], dip: float = 0.05, cap: int = 80) -> list[dict]:
    rows = []
    for p in pairs:
        rec = (p.get("dips") or {}).get(dip)
        if not rec or rec.get("pnl") is None:
            continue
        winner = p.get("winner")
        win_name = p.get("side_a") if winner == "a" else p.get("side_b") if winner == "b" else ""
        rows.append({
            "game": p.get("game") or "",
            "venue": p.get("venue") or "",
            "t0_label": p.get("t0_label") or "",
            "side_a": p.get("side_a") or "",
            "t0_a": fmt_px(p.get("t0_a")),
            "side_b": p.get("side_b") or "",
            "t0_b": fmt_px(p.get("t0_b")),
            "c0": fmt_px(p.get("c0")),
            "hold": fmt_signed(p.get("hold_pnl")),
            "hedge_a": hedge_cell(rec.get("hedge_a"), p.get("t0_ts")),
            "hedge_b": hedge_cell(rec.get("hedge_b"), p.get("t0_ts")),
            "mix": rec.get("mix") or "",
            "cost": fmt_px(rec.get("cost")),
            "payout": fmt_px(rec.get("payout")),
            "pnl": rec.get("pnl"),
            "pnl_fmt": fmt_signed(rec.get("pnl")),
            "winner": win_name,
            "official": f"{p.get('off_a')}/{p.get('off_b')}",
        })
    rows.sort(key=lambda r: (r.get("pnl") is None, -(r.get("pnl") or 0)))
    out = []
    for r in rows[:cap]:
        r = dict(r)
        r["pnl"] = fmt_signed(r.get("pnl"))
        out.append(r)
    return out


def main() -> None:
    ident = identity_ok()
    print(
        f"identity C={ident['c']:.4f} ok={ident['c_ok']} total={ident['total']:.4f} "
        f"2+2D={ident['ident']:.4f} ok={ident['ident_ok']}",
        flush=True,
    )
    if not ident["c_ok"] or not ident["ident_ok"]:
        raise SystemExit("identity check failed")
    history = pick_history()
    stream = stream_tennis(history)
    settlements = load_settlements()
    catalog = load_catalog()
    start_lookup = start_lookup_from(settlements, catalog)
    pairs = [p for p in pair_matches(stream["series"], start_lookup) if (p.get("sport") or "").lower() == "tennis"]
    print(f"tennis two-sided books {len(pairs)}", flush=True)
    for pair in pairs:
        assign_t0(pair)
    attach_pair_results(pairs, settlements)
    n_t0 = 0
    in_range = []
    for pair in pairs:
        if pair.get("t0_a") is None or pair.get("t0_b") is None or pair.get("t0_ts") is None:
            continue
        n_t0 += 1
        c0 = pair["t0_a"] + pair["t0_b"]
        pair["c0"] = c0
        if C_LO - 1e-12 <= c0 <= C_HI + 1e-12:
            in_range.append(pair)
    print(f"with T0 {n_t0}; C in [{C_LO},{C_HI}] {len(in_range)}", flush=True)
    for pair in in_range:
        simulate_pair(pair)
    simulate_current_lock(in_range)
    extra_named = []
    for p in prizmic_pairs(pairs) + tsitsi_pairs(pairs):
        if p not in in_range and p not in extra_named and p.get("t0_a") is not None:
            extra_named.append(p)
    for pair in extra_named:
        simulate_pair(pair)
    if extra_named:
        simulate_current_lock(in_range + extra_named)
        print(f"named walkthrough books outside C filter still walked: {len(extra_named)}", flush=True)
    clocks = clock_stats(in_range)
    print(
        f"old inverted listed_start+360: {clocks['n_inverted_old']}/{clocks['n']} "
        f"({clocks['pct_inverted_old']}); new empty window {clocks['n_empty_new']}",
        flush=True,
    )
    d_rows = [summarize_d(in_range, dip) for dip in DIPS]
    competitive = [p for p in in_range if is_competitive(p)]
    d_comp_rows = [summarize_d(competitive, dip) for dip in DIPS]
    lock = summarize_lock(in_range)
    print(f"competitive T0 (both 10-90c) {len(competitive)}", flush=True)
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
    settled_n = max((r["n_settled"] for r in d_rows), default=0)
    scored = [r for r in d_rows if r["mean"] is not None]
    sweet = max(scored, key=lambda r: r["mean"]) if scored else None
    verdict, sweet_text = decide_verdict(sweet, lock)
    dual_mean = sweet["mean"] if sweet else None
    lock_mean = lock.get("mean_all_settled")
    if dual_mean is None or lock_mean is None:
        vs_lock_text = "Not enough settled rows to compare."
    elif lock_mean > dual_mean + 1e-12:
        vs_lock_text = (
            f"Current Yes+No lock mean {fmt_signed(lock_mean)} on all settled (zeros when the lock never printed, "
            f"taken on {lock['n_taken']}/{lock['n']} books) beats dual-Yes best mean {fmt_signed(dual_mean)}. "
            f"The lock is the one that does not pay vig first. Verdict {verdict}."
        )
    elif dual_mean > lock_mean + 1e-12:
        vs_lock_text = (
            f"Dual-Yes best mean {fmt_signed(dual_mean)} is above the current lock's all-settled mean "
            f"{fmt_signed(lock_mean)} (that lock mean includes $0 sit-outs; when taken, mean "
            f"{fmt_signed(lock.get('mean_when_taken'))} on {lock['n_settled_taken']} settled fills). "
            f"Do not read that as KEEP: dual-Yes is always in and path-dependent; the lock is the one "
            f"that cannot lose if it fills. Verdict {verdict}."
        )
    else:
        vs_lock_text = (
            f"Means are flat ({fmt_signed(dual_mean)} vs lock {fmt_signed(lock_mean)}). Verdict {verdict}."
        )
    clock_fix_text = (
        f"Hedge window is T0 through the last live quote before a 5¢/95¢ Yes. "
        f"listed_start+{TENNIS_MIN} minutes is no longer a hard cap. "
        f"{clocks['n_inverted_old']} of {clocks['n']} in-range books had an inverted old clock "
        f"(T0 after listed start + 6 hours). Those Tuesday delayed tapes now count."
    )
    tsitsi_fixed_html = describe_fixed_tsitsi(in_range + extra_named)
    for p in tsitsi_pairs(in_range + extra_named):
        rec = (p.get("dips") or {}).get(0.05) or {}
        print(
            f"TSITSI {p.get('venue')} mix={rec.get('mix')} cost={fmt_px(rec.get('cost'))} "
            f"pnl={fmt_signed(rec.get('pnl'))} lo={et_iso(p.get('lo'))} hi={et_iso(p.get('hi'))} "
            f"inverted_old={inverted_old_clock(p)}",
            flush=True,
        )
    print(f"VERDICT {verdict}", flush=True)
    now = iso_now()
    payload = {
        "written_at": now,
        "stream": stream,
        "identity": ident,
        "d_rows": d_rows,
        "d_comp_rows": d_comp_rows,
        "compare_rows": compare_rows(d_rows, lock),
        "n_competitive": len(competitive),
        "lock": lock,
        "sweet": sweet,
        "sweet_text": sweet_text,
        "vs_lock_text": vs_lock_text,
        "clock_fix_text": clock_fix_text,
        "verdict": verdict,
        "n_pairs": len(pairs),
        "n_in": len(in_range),
        "n_unique": len({match_id(p) for p in in_range}),
        "n_settled": settled_n,
        "n_inverted_old": clocks["n_inverted_old"],
        "pct_inverted_old": clocks["pct_inverted_old"],
        "note_n": tiny_note(settled_n),
        "priz_html": priz_html(in_range + extra_named),
        "detail05": detail_rows(in_range, 0.05),
        "zero_hedge_html": zero_hedge_example_html(),
        "tape_followup_html": tape_followup_html(),
        "tsitsi_fixed_html": tsitsi_fixed_html,
    }
    write_html(payload)
    copy_g(PAGE)
    print("done", flush=True)


if __name__ == "__main__":
    main()
