"""Dense in-play tennis: both-Yes at T0, extra Yes on an n-cent dip.

Research only. Reads price_memory (archive + dated shards) and official
settlements. Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Not gold. Not DailyRun.
Does not overwrite tracked_inmatch_books_20261021.html.
"""
from __future__ import annotations

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
    attach_pair_results,
    first_absorbing,
    last_at_or_before,
    mins_after,
    pair_matches,
)
from odds_cross_no_roi_60_70_20261020 import copy_g
from odds_cross_winrate_20261020 import (
    as_float,
    game_norm,
    parse_dt,
    pct,
    table,
    tiny_note,
)
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from prediction_paths import DRIVE_STAMP as STAMP
from price_memory import to_et
from tennis_decade_at_start_20261020 import is_clocked_start, start_lookup_from
from tennis_dual_yes_dip_no_20261021 import (
    C_HI,
    C_LO,
    DIPS,
    et_iso,
    first_dip_no,
    fmt_px,
    fmt_signed,
    is_competitive,
    last_live_quote_ts,
    last_name,
    match_id,
    mean,
    median,
    named_pairs,
    simulate_current_lock,
    stream_tennis,
    summarize_lock,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "dense_inplay_yes_dip_20261021.html"
TICK_BAR = 200
NEAR_BAR = 50
ABSORB = 0.05
GAP_SEC = 60 * 60  # last quiet hour before a hidden-clock absorb → inferred actual start

ASKED = (
    "Find the matches where we were actually collecting a reasonable amount of ticks in match, "
    "then analyze: buy both at open and buy again when it drops n points. n = 5, 10, 15, 20, 25. "
    "Buy again means: at T0 buy Yes on BOTH players. Independently, the first time a player's Yes "
    "is ≥ n cents below that player's T0 Yes, buy ANOTHER Yes on THAT player at the live Yes "
    "(not No). Skip that extra if they never dip n. Miyoshi path: Yes M 0.60 + Yes M 0.35 + "
    "Yes J 0.41 + Yes M 0.16 = $1.52. That is extra Yes on the dumper, possibly more than one "
    "step. Primary sim = first dip only (one extra Yes per player at first T0−n print). Also "
    "report a ladder: extra Yes every additional n cents down (Miyoshi 60→35 is one 25c step; "
    "35→16 is not a full second 25c). Only books with a reasonable in-play tape. Do not use "
    "listed_start if it hides the match."
)

PLAIN = (
    "A Yes price is a dollar from 0 to 1, also an implied chance: 0.60 means that named tennis "
    "player is listed at 60 percent to win (moneyline: who wins the match). At the open (T0) we "
    "buy one Yes on each player. Only one can win, so those two tickets always pay exactly $1. "
    "Cost C is the two T0 Yes prices added together. If C is $1.01 you are already down a penny "
    "if you never trade — that gap is the vig (the house overround), not a bug. "
    "Then, separately for each player, the first time that player's Yes falls n cents below "
    "their own T0 Yes, we buy another Yes on that same name at the live price. We do not buy No. "
    "If they never fall n cents, we skip that extra. "
    "That extra ticket pays $1 only if that player still wins. The player whose price is falling "
    "is usually the one who is losing the match, so this adds more Yes on the dumper. "
    "Primary score: at most one extra Yes per player (first T0−n print). Ladder score: another "
    "extra Yes each time the same name falls another full n cents from T0 (T0 − 2n, T0 − 3n, …). "
    "Miyoshi 0.60 → 0.35 is one 25-cent step; 0.35 → 0.16 is only 19 cents more, so it is not a "
    "second 25-cent ladder step. "
    "T0 is the last two-sided Yes at or before the actual start when we trust that clock. We do "
    "not use a listed start that hides the match (Miyoshi vs Jong listed 15:00 Eastern Time, but "
    "the 0.60 → 0.06 path printed before that clock). If the clock is missing or stale, we infer "
    "actual start as the first tick after the last quiet hour (≥ 60 minutes with no Yes/No "
    "change) before the book hits 5 cents or 95 cents; T0 is the last two-sided Yes at or before "
    "that resume. If there is no such quiet hour, T0 is the first time both Yes prices on that "
    "venue sit between 10 and 90 cents. In-play ticks are "
    "Yes/No price changes after that T0 until the book hits about 5 cents or 95 cents, or the "
    "last quote. This page keeps only tennis books with at least 200 of those in-play change-ticks "
    "and C at T0 between 0.95 and 1.20. Research only. Not gold. Not DailyRun. Same-day contracts, "
    "so annualized rate of return is omitted — we do not have days held."
)


def esc(value) -> str:
    import html as html_mod
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def fmt_mins(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)


def na_book() -> str:
    return "n/a — no days held"


def attach_start_sources(pair: dict, start_lookup: dict) -> None:
    pair["listed_start"] = pair.get("start") or ""
    pair["listed_dt"] = pair.get("start_dt")
    gnorm = game_norm(pair.get("game") or "")
    extra = start_lookup.get(gnorm)
    pair["occ_start"] = ""
    pair["occ_dt"] = None
    pair["start_source"] = ""
    if extra:
        text, source = extra
        pair["lookup_start"] = text
        pair["lookup_source"] = source
        if source == "occurrence" and is_clocked_start(text):
            pair["occ_start"] = text
            pair["occ_dt"] = parse_dt(text)
    else:
        pair["lookup_start"] = ""
        pair["lookup_source"] = ""


def first_competitive_two_sided(yes_a, yes_b) -> tuple[float, float, int, str] | None:
    have_a = have_b = None
    merged = sorted([(t, "a", p) for t, p in yes_a] + [(t, "b", p) for t, p in yes_b])
    for t, who, p in merged:
        if who == "a":
            have_a = p
        else:
            have_b = p
        if have_a is None or have_b is None:
            continue
        if 0.10 < have_a < 0.90 and 0.10 < have_b < 0.90:
            return have_a, have_b, t, "first competitive two-sided Yes"
    return None


def clock_hides_match(pair: dict, start_ts: int) -> bool:
    """True when a start clock sits after the match already went 5c/95c."""
    yes_a = pair.get("yes_a") or []
    yes_b = pair.get("yes_b") or []
    comp = first_competitive_two_sided(yes_a, yes_b)
    if comp is None:
        return False
    _a, _b, comp_ts, _lab = comp
    if comp_ts >= start_ts:
        return False
    after_a = [row for row in yes_a if row[0] > comp_ts]
    after_b = [row for row in yes_b if row[0] > comp_ts]
    absorb = first_absorbing(after_a, after_b)
    return absorb is not None and absorb < start_ts


def last_gap_resume(pair: dict, end_ts: int | None) -> int | None:
    """First tick after the last >=60-minute quiet gap at or before end_ts."""
    if end_ts is None:
        return None
    times = sorted({
        ts
        for key in ("yes_a", "yes_b", "no_a", "no_b")
        for ts, _ in (pair.get(key) or [])
        if ts <= end_ts
    })
    if len(times) < 2:
        return None
    resume = None
    for i in range(1, len(times)):
        if times[i] - times[i - 1] >= GAP_SEC:
            resume = times[i]
    return resume


def tape_end_for_infer(pair: dict) -> int | None:
    yes_a = pair.get("yes_a") or []
    yes_b = pair.get("yes_b") or []
    comp = first_competitive_two_sided(yes_a, yes_b)
    if comp is None:
        return last_live_quote_ts(pair)
    _a, _b, comp_ts, _lab = comp
    after_a = [row for row in yes_a if row[0] > comp_ts]
    after_b = [row for row in yes_b if row[0] > comp_ts]
    absorb = first_absorbing(after_a, after_b)
    last = last_live_quote_ts(pair)
    if absorb is None:
        return last
    if last is None:
        return absorb
    return min(last, absorb)


def trusted_actual_start(pair: dict) -> tuple[datetime | None, str]:
    occ_dt = pair.get("occ_dt")
    listed_dt = pair.get("listed_dt")
    if occ_dt is not None:
        ts = int(to_et(occ_dt).timestamp())
        if not clock_hides_match(pair, ts):
            return occ_dt, "occurrence"
        pair["occ_stale"] = True
    if listed_dt is not None:
        ts = int(to_et(listed_dt).timestamp())
        if not clock_hides_match(pair, ts):
            return listed_dt, "listed/feed"
        pair["listed_stale"] = True
    end_ts = tape_end_for_infer(pair)
    resume = last_gap_resume(pair, end_ts)
    if resume is not None:
        return datetime.fromtimestamp(resume, ET), "tape resume after last >=60min gap"
    return None, ""


def assign_actual_t0(pair: dict, start_lookup: dict) -> None:
    attach_start_sources(pair, start_lookup)
    pair["t0_a"] = None
    pair["t0_b"] = None
    pair["t0_ts"] = None
    pair["t0_label"] = ""
    pair["listed_stale"] = bool(pair.get("listed_stale"))
    pair["occ_stale"] = bool(pair.get("occ_stale"))
    yes_a = pair.get("yes_a") or []
    yes_b = pair.get("yes_b") or []
    if not yes_a or not yes_b:
        return
    actual_dt, src = trusted_actual_start(pair)
    pair["actual_start"] = actual_dt.isoformat() if actual_dt is not None else ""
    pair["actual_source"] = src
    if actual_dt is not None:
        start_ts = int(to_et(actual_dt).timestamp())
        pre_a = last_at_or_before(yes_a, start_ts)
        pre_b = last_at_or_before(yes_b, start_ts)
        if pre_a and pre_b:
            pair["t0_a"] = pre_a[1]
            pair["t0_b"] = pre_b[1]
            pair["t0_ts"] = max(pre_a[0], pre_b[0])
            pair["t0_label"] = f"last two-sided Yes <= {src}"
            return
        have_a = pre_a[1] if pre_a else None
        have_b = pre_b[1] if pre_b else None
        merged = sorted(
            [(t, "a", p) for t, p in yes_a if t >= start_ts]
            + [(t, "b", p) for t, p in yes_b if t >= start_ts]
        )
        for t, who, p in merged:
            if who == "a":
                have_a = p
            else:
                have_b = p
            if have_a is not None and have_b is not None:
                pair["t0_a"] = have_a
                pair["t0_b"] = have_b
                pair["t0_ts"] = t
                pair["t0_label"] = f"mixed pre-start + first in-game ({src})"
                return
    hit = first_competitive_two_sided(yes_a, yes_b)
    if hit is None:
        return
    pair["t0_a"], pair["t0_b"], pair["t0_ts"], pair["t0_label"] = hit
    if pair.get("listed_stale") or pair.get("occ_stale"):
        pair["t0_label"] = "first competitive two-sided Yes (clock hid the match)"


def play_hi(pair: dict) -> int | None:
    t0 = pair.get("t0_ts")
    if t0 is None:
        return None
    last = last_live_quote_ts(pair)
    after_a = [row for row in (pair.get("yes_a") or []) if row[0] > t0]
    after_b = [row for row in (pair.get("yes_b") or []) if row[0] > t0]
    absorb = first_absorbing(after_a, after_b)
    if absorb is None:
        return last
    if last is None:
        return absorb - 1
    return min(last, absorb - 1)


def mark_inplay(pair: dict) -> None:
    t0 = pair.get("t0_ts")
    pair["lo"] = t0
    pair["hi"] = play_hi(pair) if t0 is not None else None
    pair["inplay_n"] = 0
    pair["inplay_yes"] = 0
    pair["inplay_no"] = 0
    pair["pre_n"] = 0
    pair["max_gap_min"] = None
    pair["max_dip_a"] = None
    pair["max_dip_b"] = None
    pair["dense"] = False
    pair["both_quoted"] = False
    lo = pair.get("lo")
    hi = pair.get("hi")
    if t0 is None or lo is None:
        return
    if pair.get("t0_a") is not None and pair.get("t0_b") is not None:
        pair["both_quoted"] = True
        pair["c0"] = pair["t0_a"] + pair["t0_b"]
        pair["hold_pnl"] = 1.0 - pair["c0"]
    hi_use = hi if hi is not None else 2**31
    bags = []
    pre_n = 0
    for key in ("yes_a", "yes_b", "no_a", "no_b"):
        ticks = pair.get(key) or []
        after = [row for row in ticks if lo < row[0] <= hi_use]
        bags.append(after)
        pre_n += sum(1 for ts, _ in ticks if ts <= lo)
    yes_n = len(bags[0]) + len(bags[1])
    no_n = len(bags[2]) + len(bags[3])
    pair["inplay_yes"] = yes_n
    pair["inplay_no"] = no_n
    pair["inplay_n"] = yes_n + no_n
    pair["pre_n"] = pre_n
    pair["both_inplay"] = bool(bags[0] and bags[1])
    times = sorted({ts for bag in bags for ts, _ in bag})
    if times:
        gaps = [(times[0] - lo) / 60.0]
        gaps.extend((times[i] - times[i - 1]) / 60.0 for i in range(1, len(times)))
        pair["max_gap_min"] = max(gaps) if gaps else None
    if bags[0] and pair.get("t0_a") is not None:
        pair["max_dip_a"] = max(0.0, float(pair["t0_a"]) - min(px for _, px in bags[0]))
    if bags[1] and pair.get("t0_b") is not None:
        pair["max_dip_b"] = max(0.0, float(pair["t0_b"]) - min(px for _, px in bags[1]))
    c0 = pair.get("c0")
    in_c = c0 is not None and (C_LO - 1e-12) <= c0 <= (C_HI + 1e-12)
    pair["dense"] = bool(
        pair["both_quoted"]
        and pair["both_inplay"]
        and in_c
        and is_competitive(pair)
        and pair["inplay_n"] >= TICK_BAR
    )


def first_dip_yes(yes_ticks, t0_px: float, lo: int, hi: int, dip: float) -> dict | None:
    thresh = t0_px - dip
    if thresh <= ABSORB + 1e-12:
        return None
    for ts, px in yes_ticks:
        if ts <= lo or ts > hi:
            continue
        if px <= thresh + 1e-12:
            if px <= ABSORB + 1e-12:
                return None
            return {
                "ts": ts,
                "yes_print": px,
                "thresh": thresh,
                "step": 1,
                "overshoot": max(0.0, thresh - px),
            }
    return None


def ladder_dip_yes(yes_ticks, t0_px: float, lo: int, hi: int, dip: float) -> list[dict]:
    fills = []
    last_ts = lo
    step = 1
    while True:
        thresh = t0_px - step * dip
        if thresh <= ABSORB + 1e-12:
            break
        hit = None
        for ts, px in yes_ticks:
            if ts <= last_ts or ts > hi:
                continue
            if px <= thresh + 1e-12:
                if px <= ABSORB + 1e-12:
                    return fills
                hit = {
                    "ts": ts,
                    "yes_print": px,
                    "thresh": thresh,
                    "step": step,
                    "overshoot": max(0.0, thresh - px),
                }
                break
        if hit is None:
            break
        fills.append(hit)
        last_ts = hit["ts"]
        step += 1
    return fills


def extras_payout(winner: str, n_a: int, n_b: int) -> float:
    # Always hold 1 Yes A and 1 Yes B (pays $1). Each extra Yes pays $1 if that name wins.
    if winner == "a":
        return 1.0 + float(n_a)
    if winner == "b":
        return 1.0 + float(n_b)
    return 0.0


def simulate_yes_dip(pair: dict) -> None:
    pair["yes_dips"] = {}
    pair["yes_ladders"] = {}
    pair["no_dips"] = {}
    t0a, t0b, t0_ts = pair.get("t0_a"), pair.get("t0_b"), pair.get("t0_ts")
    lo, hi = pair.get("lo"), pair.get("hi")
    if t0a is None or t0b is None or t0_ts is None or lo is None or hi is None:
        return
    c0 = t0a + t0b
    pair["c0"] = c0
    pair["hold_pnl"] = 1.0 - c0
    winner = pair.get("winner")
    settled = bool(pair.get("settled") and winner in ("a", "b"))
    for dip in DIPS:
        ha = first_dip_yes(pair["yes_a"], t0a, lo, hi, dip)
        hb = first_dip_yes(pair["yes_b"], t0b, lo, hi, dip)
        n_extra = int(ha is not None) + int(hb is not None)
        cost = c0
        if ha:
            cost += ha["yes_print"]
        if hb:
            cost += hb["yes_print"]
        rec = {
            "dip": dip,
            "extra_a": ha,
            "extra_b": hb,
            "n_extra": n_extra,
            "mix": {0: "none", 1: "one extra", 2: "both extra"}[n_extra],
            "cost": cost,
            "pnl": None,
            "payout": None,
        }
        if settled:
            paid = extras_payout(winner, int(ha is not None), int(hb is not None))
            rec["payout"] = paid
            rec["pnl"] = paid - cost
        pair["yes_dips"][dip] = rec

        la = ladder_dip_yes(pair["yes_a"], t0a, lo, hi, dip)
        lb = ladder_dip_yes(pair["yes_b"], t0b, lo, hi, dip)
        lcost = c0 + sum(x["yes_print"] for x in la) + sum(x["yes_print"] for x in lb)
        lrec = {
            "dip": dip,
            "fills_a": la,
            "fills_b": lb,
            "n_extra": len(la) + len(lb),
            "n_a": len(la),
            "n_b": len(lb),
            "mix": ladder_mix(len(la), len(lb)),
            "cost": lcost,
            "pnl": None,
            "payout": None,
        }
        if settled:
            paid = extras_payout(winner, len(la), len(lb))
            lrec["payout"] = paid
            lrec["pnl"] = paid - lcost
        pair["yes_ladders"][dip] = lrec

        na = first_dip_no(pair["yes_a"], pair.get("no_a") or [], t0a, lo, hi, dip)
        nb = first_dip_no(pair["yes_b"], pair.get("no_b") or [], t0b, lo, hi, dip)
        n_hedge = int(na is not None) + int(nb is not None)
        ncost = c0
        if na:
            ncost += na["no_px"]
        if nb:
            ncost += nb["no_px"]
        nrec = {
            "dip": dip,
            "hedge_a": na,
            "hedge_b": nb,
            "n_hedge": n_hedge,
            "mix": {0: "none", 1: "one", 2: "both"}[n_hedge],
            "cost": ncost,
            "pnl": None,
            "payout": None,
        }
        if settled:
            paid = 1.0
            if na and winner == "b":
                paid += 1.0
            if nb and winner == "a":
                paid += 1.0
            nrec["payout"] = paid
            nrec["pnl"] = paid - ncost
        pair["no_dips"][dip] = nrec


def ladder_mix(n_a: int, n_b: int) -> str:
    if n_a and n_b:
        return "both extra"
    if n_a or n_b:
        return "one extra"
    return "none"


def summarize_yes(pairs: list[dict], dip: float, kind: str) -> dict:
    bag = "yes_dips" if kind == "first" else "yes_ladders" if kind == "ladder" else "no_dips"
    rows = [p for p in pairs if dip in (p.get(bag) or {})]
    recs = [p[bag][dip] for p in rows]
    settled = [p for p in rows if p.get("settled") and p[bag][dip].get("pnl") is not None]
    pnls = [p[bag][dip]["pnl"] for p in settled]
    holds = [p["hold_pnl"] for p in settled if p.get("hold_pnl") is not None]
    costs = [p[bag][dip]["cost"] for p in settled]
    if kind == "no":
        n_both = sum(1 for r in recs if r.get("n_hedge") == 2)
        n_one = sum(1 for r in recs if r.get("n_hedge") == 1)
        n_none = sum(1 for r in recs if r.get("n_hedge") == 0)
    else:
        n_both = sum(1 for r in recs if r.get("mix") == "both extra")
        n_one = sum(1 for r in recs if r.get("mix") == "one extra")
        n_none = sum(1 for r in recs if r.get("mix") == "none")
    mix_pnls = defaultdict(list)
    for p in settled:
        mix_pnls[p[bag][dip].get("mix") or ""].append(p[bag][dip]["pnl"])
    wins = sum(1 for x in pnls if x > 1e-12)
    extra_counts = [r.get("n_extra") if kind != "no" else r.get("n_hedge") for r in recs]
    return {
        "kind": kind,
        "dip": dip,
        "dip_cents": int(round(dip * 100)),
        "n": len(rows),
        "n_settled": len(settled),
        "mean": mean(pnls),
        "median": median(pnls),
        "win_pct": pct(wins, len(pnls)),
        "n_win": wins,
        "pct_both": pct(n_both, len(rows)),
        "pct_one": pct(n_one, len(rows)),
        "pct_none": pct(n_none, len(rows)),
        "n_both": n_both,
        "n_one": n_one,
        "n_none": n_none,
        "mean_cost": mean(costs),
        "mean_hold": mean(holds),
        "median_hold": median(holds),
        "mean_none": mean(mix_pnls.get("none") or mix_pnls.get("") or []),
        "mean_one": mean(mix_pnls.get("one extra") or mix_pnls.get("one") or []),
        "mean_both": mean(mix_pnls.get("both extra") or mix_pnls.get("both") or []),
        "mean_extras": mean([float(x or 0) for x in extra_counts]),
        "note": tiny_note(len(settled)),
    }


def summarize_hold(pairs: list[dict]) -> dict:
    settled = [p for p in pairs if p.get("settled") and p.get("hold_pnl") is not None]
    pnls = [p["hold_pnl"] for p in settled]
    wins = sum(1 for x in pnls if x > 1e-12)
    costs = [p["c0"] for p in settled if p.get("c0") is not None]
    return {
        "kind": "t0_only",
        "n": len(pairs),
        "n_settled": len(settled),
        "mean": mean(pnls),
        "median": median(pnls),
        "win_pct": pct(wins, len(pnls)),
        "mean_cost": mean(costs),
        "pct_both": "",
        "pct_one": "",
        "pct_none": "100.0" if pairs else "",
        "n_both": 0,
        "n_one": 0,
        "n_none": len(pairs),
        "note": tiny_note(len(settled)),
    }


def money_cell(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):,.2f}"


def signed_money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "+" if number >= 0 else "-"
    return f"{sign}${abs(number):,.2f}"


def delta_money(cand, ctrl) -> str:
    if cand is None or ctrl is None:
        return ""
    return signed_money(cand - ctrl)


def extra_fill_text(pair: dict, rec: dict | None, kind: str) -> str:
    if not rec:
        return ""
    a_name = last_name(pair.get("side_a") or "") or "A"
    b_name = last_name(pair.get("side_b") or "") or "B"
    if kind == "first":
        bits = []
        if rec.get("extra_a"):
            bits.append(f"{a_name} {fmt_px(rec['extra_a']['yes_print'])}")
        if rec.get("extra_b"):
            bits.append(f"{b_name} {fmt_px(rec['extra_b']['yes_print'])}")
        return ", ".join(bits) if bits else "none"
    bits = []
    fa = rec.get("fills_a") or []
    fb = rec.get("fills_b") or []
    if fa:
        bits.append(f"{a_name}: " + ",".join(fmt_px(x["yes_print"]) for x in fa))
    if fb:
        bits.append(f"{b_name}: " + ",".join(fmt_px(x["yes_print"]) for x in fb))
    return "; ".join(bits) if bits else "none"


def match_date(pair: dict) -> str:
    t0 = pair.get("t0_ts")
    if t0 is not None:
        return datetime.fromtimestamp(t0, ET).date().isoformat()
    start_dt = pair.get("listed_dt") or pair.get("start_dt")
    if start_dt is not None:
        return to_et(start_dt).date().isoformat()
    return ""


def decide_verdict(first_rows: list[dict], hold: dict, lock: dict) -> tuple[str, str]:
    scored = [r for r in first_rows if r.get("mean") is not None]
    if not scored:
        return (
            "HOLD",
            "No settled dense books — no D to score. HOLD. Research only. Not gold. Not DailyRun.",
        )
    sweet = max(scored, key=lambda r: (r["mean"], r.get("median") or -99))
    n = sweet["n_settled"]
    label = f"D={sweet['dip_cents']}¢ first-dip extra Yes"
    dual_mean = sweet["mean"]
    dual_med = sweet["median"]
    hold_mean = hold.get("mean")
    lock_mean = lock.get("mean_all_settled")
    tiny = n < 20
    worse_hold = hold_mean is not None and dual_mean < hold_mean - 1e-12
    worse_lock = lock_mean is not None and dual_mean < lock_mean - 1e-12
    if tiny:
        tag = "HOLD"
        if dual_mean is not None and dual_mean <= 0 and (worse_hold or worse_lock):
            tag = "DISMISS"
        why = (
            f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
            f"median {fmt_signed(dual_med)}. T0-only both-Yes mean {fmt_signed(hold_mean)}. "
            f"Current Yes+No ≤ $0.95 lock all-settled mean {fmt_signed(lock_mean)} "
            f"(zeros when the lock never printed). "
        )
        if tag == "DISMISS":
            why += (
                "DISMISS — even on a dense in-play tape, extra Yes on the dip loses versus "
                "stand-pat both-Yes and versus the lock. You are adding Yes on the player "
                "whose price is falling (usually the one who is losing). "
            )
        else:
            why += "HOLD — tiny N, not a send rule. "
        why += "Research only. Not gold. Not DailyRun."
        return tag, why
    if dual_mean is not None and dual_mean <= 0:
        return (
            "DISMISS",
            f"{label} has the best mean P&L ({fmt_signed(dual_mean)}) on settled N {n}, "
            f"median {fmt_signed(dual_med)}. DISMISS on quality — best D is still at or below "
            f"zero. T0-only both-Yes mean {fmt_signed(hold_mean)}. Lock all-settled mean "
            f"{fmt_signed(lock_mean)}. Extra Yes-on-dip buys more of the dumper. "
            f"Research only. Not gold. Not DailyRun.",
        )
    if worse_lock or worse_hold:
        return (
            "DISMISS",
            f"{label} mean {fmt_signed(dual_mean)} is worse than T0-only "
            f"{fmt_signed(hold_mean)} or the lock {fmt_signed(lock_mean)}. DISMISS. "
            f"Research only. Not gold. Not DailyRun.",
        )
    return (
        "HOLD",
        f"{label} mean {fmt_signed(dual_mean)} on settled N {n} is the best first-dip D "
        f"and is above zero, but this is a short October 2026 tape and the trade is always "
        f"in (unlike the lock). HOLD not KEEP. Research only. Not gold. Not DailyRun.",
    )


def compare_rows(first_rows, ladder_rows, no_rows, hold, lock) -> list[dict]:
    rows = []
    lock_mean = lock.get("mean_all_settled")
    lock_med = lock.get("median_all_settled")
    rows.append({
        "arm": "Current lock Yes+No ≤ $0.95 (sit out $0 if never)",
        "role": "control",
        "n": lock.get("n"),
        "n_settled": lock.get("n_settled"),
        "mean": signed_money(lock_mean),
        "median": signed_money(lock_med),
        "win_pct": lock.get("win_pct_taken") or "",
        "mean_cost": money_cell(None),
        "pct_both": lock.get("pct_taken") or "",
        "pct_one": "",
        "pct_none": pct((lock.get("n") or 0) - (lock.get("n_taken") or 0), lock.get("n") or 0),
        "d_mean_lock": signed_money(0.0),
        "d_mean_hold": delta_money(lock_mean, hold.get("mean")),
        "ann_ror": na_book(),
        "ann_ror_is": na_book(),
        "ann_ror_oos": na_book(),
        "max_dd": na_book(),
        "calmar": na_book(),
        "sharpe": na_book(),
        "note": lock.get("note") or "",
    })
    rows.append({
        "arm": "T0-only both-Yes (no extra)",
        "role": "control",
        "n": hold.get("n"),
        "n_settled": hold.get("n_settled"),
        "mean": signed_money(hold.get("mean")),
        "median": signed_money(hold.get("median")),
        "win_pct": hold.get("win_pct") or "",
        "mean_cost": money_cell(hold.get("mean_cost")),
        "pct_both": "",
        "pct_one": "",
        "pct_none": "100.0",
        "d_mean_lock": delta_money(hold.get("mean"), lock_mean),
        "d_mean_hold": signed_money(0.0),
        "ann_ror": na_book(),
        "ann_ror_is": na_book(),
        "ann_ror_oos": na_book(),
        "max_dd": na_book(),
        "calmar": na_book(),
        "sharpe": na_book(),
        "note": hold.get("note") or "",
    })
    for r in first_rows:
        rows.append({
            "arm": f"First-dip extra Yes D={r['dip_cents']}¢ (primary)",
            "role": "candidate",
            "n": r["n"],
            "n_settled": r["n_settled"],
            "mean": signed_money(r["mean"]),
            "median": signed_money(r["median"]),
            "win_pct": r.get("win_pct") or "",
            "mean_cost": money_cell(r.get("mean_cost")),
            "pct_both": r.get("pct_both") or "",
            "pct_one": r.get("pct_one") or "",
            "pct_none": r.get("pct_none") or "",
            "d_mean_lock": delta_money(r.get("mean"), lock_mean),
            "d_mean_hold": delta_money(r.get("mean"), hold.get("mean")),
            "ann_ror": na_book(),
            "ann_ror_is": na_book(),
            "ann_ror_oos": na_book(),
            "max_dd": na_book(),
            "calmar": na_book(),
            "sharpe": na_book(),
            "note": r.get("note") or "",
        })
    for r in ladder_rows:
        rows.append({
            "arm": f"Ladder extra Yes every {r['dip_cents']}¢ (secondary)",
            "role": "candidate",
            "n": r["n"],
            "n_settled": r["n_settled"],
            "mean": signed_money(r["mean"]),
            "median": signed_money(r["median"]),
            "win_pct": r.get("win_pct") or "",
            "mean_cost": money_cell(r.get("mean_cost")),
            "pct_both": r.get("pct_both") or "",
            "pct_one": r.get("pct_one") or "",
            "pct_none": r.get("pct_none") or "",
            "d_mean_lock": delta_money(r.get("mean"), lock_mean),
            "d_mean_hold": delta_money(r.get("mean"), hold.get("mean")),
            "ann_ror": na_book(),
            "ann_ror_is": na_book(),
            "ann_ror_oos": na_book(),
            "max_dd": na_book(),
            "calmar": na_book(),
            "sharpe": na_book(),
            "note": r.get("note") or "",
        })
    for r in no_rows:
        rows.append({
            "arm": f"D={r['dip_cents']}¢ No-hedge (same universe; already DISMISS)",
            "role": "comparison",
            "n": r["n"],
            "n_settled": r["n_settled"],
            "mean": signed_money(r["mean"]),
            "median": signed_money(r["median"]),
            "win_pct": r.get("win_pct") or "",
            "mean_cost": money_cell(r.get("mean_cost")),
            "pct_both": r.get("pct_both") or "",
            "pct_one": r.get("pct_one") or "",
            "pct_none": r.get("pct_none") or "",
            "d_mean_lock": delta_money(r.get("mean"), lock_mean),
            "d_mean_hold": delta_money(r.get("mean"), hold.get("mean")),
            "ann_ror": na_book(),
            "ann_ror_is": na_book(),
            "ann_ror_oos": na_book(),
            "max_dd": na_book(),
            "calmar": na_book(),
            "sharpe": na_book(),
            "note": "DISMISS leftover — No-hedge, not the main trade on this page.",
        })
    return rows


def metric_table_rows(summaries: list[dict]) -> list[dict]:
    rows = []
    for r in summaries:
        rows.append({
            "dip": f"{r['dip_cents']}¢",
            "n": r["n"],
            "n_settled": r["n_settled"],
            "mean": signed_money(r["mean"]),
            "median": signed_money(r["median"]),
            "win_pct": r.get("win_pct") or "",
            "pct_both": r.get("pct_both") or "",
            "pct_one": r.get("pct_one") or "",
            "pct_none": r.get("pct_none") or "",
            "n_both": r.get("n_both"),
            "n_one": r.get("n_one"),
            "n_none": r.get("n_none"),
            "mean_cost": money_cell(r.get("mean_cost")),
            "mean_hold": signed_money(r.get("mean_hold")),
            "mean_none": signed_money(r.get("mean_none")),
            "mean_one": signed_money(r.get("mean_one")),
            "mean_both": signed_money(r.get("mean_both")),
            "mean_extras": fmt_px(r.get("mean_extras")),
            "note": r.get("note") or "",
        })
    return rows


def d_headers() -> list[tuple[str, str]]:
    return [
        ("D", "text"), ("N books", "num"), ("N settled", "num"),
        ("Mean $", "num"), ("Median $", "num"), ("Win rate %", "num"),
        ("% both extra", "num"), ("% one extra", "num"), ("% none", "num"),
        ("N both extra", "num"), ("N one extra", "num"), ("N none", "num"),
        ("Mean cost", "num"), ("Mean T0-only $1−C", "num"),
        ("Mean $ if none", "num"), ("Mean $ if one extra", "num"), ("Mean $ if both extra", "num"),
        ("Mean extras filled", "num"), ("Note", "text"),
    ]


def d_fields() -> list[str]:
    return [
        "dip", "n", "n_settled", "mean", "median", "win_pct",
        "pct_both", "pct_one", "pct_none", "n_both", "n_one", "n_none",
        "mean_cost", "mean_hold", "mean_none", "mean_one", "mean_both",
        "mean_extras", "note",
    ]


def per_match_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        first = p.get("yes_dips") or {}
        ladder = p.get("yes_ladders") or {}
        winner = p.get("winner")
        win_name = p.get("side_a") if winner == "a" else p.get("side_b") if winner == "b" else ""
        rec25 = first.get(0.25) or {}
        lad25 = ladder.get(0.25) or {}
        row = {
            "game": p.get("game") or "",
            "date": match_date(p),
            "venue": p.get("venue") or "",
            "side_a": p.get("side_a") or "",
            "t0_a": fmt_px(p.get("t0_a")),
            "side_b": p.get("side_b") or "",
            "t0_b": fmt_px(p.get("t0_b")),
            "c0": fmt_px(p.get("c0")),
            "inplay_n": p.get("inplay_n") or 0,
            "inplay_yes": p.get("inplay_yes") or 0,
            "inplay_no": p.get("inplay_no") or 0,
            "pre_n": p.get("pre_n") or 0,
            "max_gap": fmt_mins(p.get("max_gap_min")),
            "max_dip_a": fmt_px(p.get("max_dip_a")),
            "max_dip_b": fmt_px(p.get("max_dip_b")),
            "winner": win_name,
            "live": "yes" if not p.get("settled") else "no",
            "t0_label": p.get("t0_label") or "",
            "t0_when": et_iso(p.get("t0_ts")),
            "actual_source": p.get("actual_source") or "",
            "listed_stale": "yes" if p.get("listed_stale") or p.get("occ_stale") else "no",
            "hold_pnl": signed_money(p.get("hold_pnl")) if p.get("settled") else "",
            "ex25": extra_fill_text(p, rec25, "first"),
            "mix25": rec25.get("mix") or "",
            "pnl25": signed_money(rec25.get("pnl")) if rec25.get("pnl") is not None else "",
            "lad25": extra_fill_text(p, lad25, "ladder"),
            "lad_n": lad25.get("n_extra") if lad25 else 0,
            "lad_pnl": signed_money(lad25.get("pnl")) if lad25.get("pnl") is not None else "",
        }
        for dip in DIPS:
            cents = int(round(dip * 100))
            rec = first.get(dip) or {}
            row[f"mix{cents}"] = rec.get("mix") or ""
            row[f"ex{cents}"] = extra_fill_text(p, rec, "first")
            row[f"pnl{cents}"] = signed_money(rec.get("pnl")) if rec.get("pnl") is not None else ""
            row[f"n{cents}"] = rec.get("n_extra") if rec else 0
        rows.append(row)
    rows.sort(key=lambda r: (-(r.get("inplay_n") or 0), r.get("game") or "", r.get("venue") or ""))
    return rows


def uniq_pairs(pairs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for p in pairs:
        key = (p.get("game") or "", p.get("venue") or "", p.get("side_a") or "", p.get("side_b") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def describe_named(pairs: list[dict], *needles: str) -> str:
    found = uniq_pairs(named_pairs(pairs, *needles))
    if not found:
        return "not on this two-sided tennis tape."
    bits = []
    for p in found:
        rec = (p.get("yes_dips") or {}).get(0.25) or {}
        bits.append(
            f"{p.get('venue') or '?'}: dense={'yes' if p.get('dense') else 'no'}, "
            f"T0 {fmt_px(p.get('t0_a'))}/{fmt_px(p.get('t0_b'))} C={fmt_px(p.get('c0'))}, "
            f"in-play ticks {p.get('inplay_n') or 0} (bar {TICK_BAR}), "
            f"max dip {fmt_px(p.get('max_dip_a'))}/{fmt_px(p.get('max_dip_b'))}, "
            f"T0 label {p.get('t0_label') or ''}, "
            f"listed_stale={'yes' if p.get('listed_stale') or p.get('occ_stale') else 'no'}, "
            f"D=25 first-dip mix {rec.get('mix') or 'n/a'}, "
            f"live={'yes' if not p.get('settled') else 'no'}"
        )
    return " | ".join(bits)


def miyoshi_section(pairs: list[dict]) -> tuple[str, str]:
    found = uniq_pairs(named_pairs(pairs, "miyoshi", "jong"))
    if not found:
        text = "Miyoshi vs Jong is not on this two-sided tennis tape."
        return text, f"<p class='note'>{esc(text)}</p>"
    pm = next((p for p in found if str(p.get("venue") or "").lower() == "polymarket"), found[0])
    rec = (pm.get("yes_dips") or {}).get(0.25) or {}
    lad = (pm.get("yes_ladders") or {}).get(0.25) or {}
    in_bar = "IN" if pm.get("dense") else "OUT"
    paul_cost = 0.60 + 0.35 + 0.41 + 0.16
    winner = ""
    if pm.get("winner") == "a":
        winner = pm.get("side_a") or ""
    elif pm.get("winner") == "b":
        winner = pm.get("side_b") or ""
    win_jong = "jong" in winner.lower()
    win_miyoshi = "miyoshi" in winner.lower()
    if win_jong:
        paul_pnl = 1.0 - paul_cost
        paul_pay = 1.0
    elif win_miyoshi:
        paul_pnl = 3.0 - paul_cost
        paul_pay = 3.0
    else:
        paul_pnl = None
        paul_pay = None
    text = (
        f"Polymarket {in_bar} the >={TICK_BAR} in-play bar "
        f"(in-play ticks {pm.get('inplay_n') or 0}; T0 {fmt_px(pm.get('t0_a'))}/"
        f"{fmt_px(pm.get('t0_b'))} C={fmt_px(pm.get('c0'))}; {pm.get('t0_label') or ''}; "
        f"listed stale={'yes' if pm.get('listed_stale') or pm.get('occ_stale') else 'no'})."
    )
    html = [
        f"<p><strong>Miyoshi vs Jong — {esc(in_bar)} the dense bar.</strong> "
        f"{esc(pm.get('venue') or '')}. T0 {esc(pm.get('t0_label') or '')} at "
        f"{esc(et_iso(pm.get('t0_ts')))}: {esc(pm.get('side_a'))} {fmt_px(pm.get('t0_a'))} / "
        f"{esc(pm.get('side_b'))} {fmt_px(pm.get('t0_b'))}, C = {fmt_px(pm.get('c0'))}. "
        f"In-play Yes/No change-ticks after that T0: <strong>{pm.get('inplay_n') or 0}</strong> "
        f"(Yes {pm.get('inplay_yes') or 0}, No {pm.get('inplay_no') or 0}; pre-T0 {pm.get('pre_n') or 0}). "
        f"Max dip {esc(last_name(pm.get('side_a') or ''))} {fmt_px(pm.get('max_dip_a'))}, "
        f"{esc(last_name(pm.get('side_b') or ''))} {fmt_px(pm.get('max_dip_b'))}. "
        f"Listed start {esc(pm.get('listed_start') or 'none')}; occurrence "
        f"{esc(pm.get('occ_start') or 'none')}; inferred actual start "
        f"{esc(pm.get('actual_start') or 'none')} ({esc(pm.get('actual_source') or '')}); "
        f"clock hid the match: "
        f"{'yes' if pm.get('listed_stale') or pm.get('occ_stale') else 'no'}. "
        f"Winner {esc(winner or 'unsettled')}. Paul named Yes Miyoshi 0.60 / Yes Jong 0.41; "
        f"those prints sit on this tape just before the last quiet hour. Our T0 is the last "
        f"two-sided Yes at or before the resume, which should be that same book within a couple of cents.</p>",
        "<p>Paul’s named path is extra Yes on the dumper, not a No-hedge: "
        f"Yes Miyoshi 0.60 + Yes Miyoshi 0.35 + Yes Jong 0.41 + Yes Miyoshi 0.16 = "
        f"<strong>${paul_cost:.2f}</strong>. That book pays <strong>$3 if Miyoshi wins</strong> "
        f"and <strong>$1 if Jong wins</strong>, not automatically $2. "
        f"{'Jong won, so that path pays $1 → ' + signed_money(paul_pnl) + '.' if win_jong else ''}"
        f"{'Miyoshi won, so that path pays $3 → ' + signed_money(paul_pnl) + '.' if win_miyoshi else ''}"
        " The 0.16 print is 44 cents below 0.60, so it is not a full second 25-cent ladder step "
        "(T0 − 50c = 0.10). Primary D=25 on this page buys at most one extra Yes per player at "
        "the first T0−25c print.</p>",
        f"<p>Primary D=25 first-dip on this T0: mix {esc(rec.get('mix') or 'n/a')}, "
        f"fills {esc(extra_fill_text(pm, rec, 'first'))}, cost {money_cell(rec.get('cost'))}, "
        f"payout {fmt_px(rec.get('payout')) if rec.get('payout') is not None else 'unsettled'}, "
        f"P&amp;L {signed_money(rec.get('pnl')) if rec.get('pnl') is not None else 'unsettled'}.</p>",
        f"<p>Ladder D=25 (extra Yes at T0−25c, T0−50c, …): {esc(extra_fill_text(pm, lad, 'ladder'))}, "
        f"{lad.get('n_extra') or 0} extras, cost {money_cell(lad.get('cost'))}, "
        f"P&amp;L {signed_money(lad.get('pnl')) if lad.get('pnl') is not None else 'unsettled'}. "
        "A later 0.06 print would be a second 25c step only if it is ≤ T0 − 50c and still above "
        "the 5c absorbing floor.</p>",
    ]
    others = [p for p in found if p is not pm]
    if others:
        html.append(
            "<p class='note'>Other venues: "
            + esc(describe_named(others, "miyoshi", "jong"))
            + "</p>"
        )
    return text, "\n".join(html)


def write_html(payload: dict) -> None:
    stream = payload["stream"]
    first_fmt = metric_table_rows(payload["first_rows"])
    ladder_fmt = metric_table_rows(payload["ladder_rows"])
    no_fmt = metric_table_rows(payload["no_rows"])
    near = payload.get("near_rows") or []
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dense in-play Yes-on-dip 2026-10-21</title>
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
<h1>Dense in-play Yes-on-dip — tennis moneyline</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Short October 2026 live tape — no in-sample / out-of-sample split. Verdict: <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Universe after the tick bar:</strong> {payload['n_dense']} tennis books with ≥{TICK_BAR} Yes/No change-ticks after actual-start T0, both players quoted, both T0 Yes between 10¢ and 90¢, and C in [0.95, 1.20]. Settled {payload['n_dense_settled']}; still live {payload['n_dense_live']}. Two-sided tennis books scanned {payload['n_pairs']}; with a T0 {payload['n_t0']}; competitive C-in-range {payload['n_in']}; in-play ticks ≥1 {payload['n_any']}; ≥{NEAR_BAR} {payload['n_near']}; ≥100 {payload['n_100']}; ≥{TICK_BAR} {payload['n_dense']}.</p>
<p><strong>Miyoshi vs Jong:</strong> {esc(payload.get('miyoshi_text') or '')}</p>
<p><strong>Primary first-dip extra Yes:</strong> {esc(payload.get('sweet_text') or '')}</p>
<p><strong>Versus T0-only both-Yes and versus the current lock on the same dense universe:</strong> {esc(payload.get('vs_text') or '')}</p>
<p>Annualized rate of return (Ann ROR) is omitted. These are same-day tennis contracts. We do not have closed-trade days held, so the house Ann ROR formula is not computed. In-sample / out-of-sample Ann ROR, Max DD, Calmar, Sharpe, capital days, Paul Score, and FIT are n/a for the same reason. Total book PnL $ is omitted from the compare table (canonical HTML compare rule).</p>
</div>

<div class="warn">
<p>Primary P&amp;L is without fees. Fills are optimistic at the printed Yes ask. Do not buy after the first 5¢ / 95¢ absorbing print — that is settlement, not an in-match dip. Extra Yes-on-dip adds a ticket on the player whose price is falling. If that player loses, those extras expire at $0 and the bill is larger than stand-pat both-Yes. {esc(payload.get('note_n') or '')} Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Research only. Not gold. Not DailyRun.</p>
</div>

<h2>Freeze</h2>
<ul>
<li>Tape: price_memory iter (read-only archive <code>raw/price_memory.jsonl</code> plus dated sport shards under <code>raw/price_memory/</code>). Lines {stream.get('n_lines') or 0:,}. Tennis moneyline Yes/No change-ticks {stream.get('n_hits') or 0:,}. First quote {esc(stream.get('seen_min') or '')}. Last quote {esc(stream.get('seen_max') or '')}.</li>
<li>Sport / market: tennis moneyline only. Same-price repeats are not change-ticks.</li>
<li><strong>T0:</strong> last two-sided Yes at or before a trusted actual start. Actual start is Kalshi/Gemini occurrence when clocked, else listed/feed start when clocked. A start clock is rejected when it hides the match: a competitive two-sided Yes already existed and the first 5¢ / 95¢ absorbing print is <em>before</em> that clock (Miyoshi listed 15:00 Eastern Time). If the clock is missing or rejected, actual start is the first Yes/No change-tick after the last quiet hour (no Yes/No change for ≥ 60 minutes) before absorb or the last quote. T0 is then the last two-sided Yes at or before that resume. If there is no such quiet hour, T0 is the first time both Yes prices on that venue sit between 10¢ and 90¢.</li>
<li><strong>In-play ticks:</strong> Yes and No change-ticks after T0 through the last live quote before the first 5¢ / 95¢ Yes, or the last quote if the book never absorbed.</li>
<li><strong>Tick bar:</strong> ≥{TICK_BAR} in-play Yes/No change-ticks, both players quoted at T0, both still printing Yes after T0, both T0 Yes in (10¢, 90¢), C = Yes A + Yes B in [0.95, 1.20]. Sensitivity counts are in the headline (N at ≥1 / ≥{NEAR_BAR} / ≥100 / ≥{TICK_BAR}).</li>
<li><strong>n values:</strong> 5, 10, 15, 20, 25 cents. Threshold is that player’s own T0 Yes minus n. Fill at the live Yes print, not No.</li>
<li><strong>Primary:</strong> one extra Yes per player at the first T0−n print. Skip if they never print ≤ T0−n, or if that print is already ≤5¢ (absorbing).</li>
<li><strong>Ladder (secondary, labeled):</strong> extra Yes at first print ≤ T0 − k·n for k = 1, 2, … while the threshold stays above 5¢. Miyoshi 60→35 is k=1 for n=25. 35→16 is not k=2 (T0−50c = 0.10).</li>
<li><strong>Payout:</strong> each Yes pays $1 if that player wins. T0 always holds one Yes on each name (floor payout $1). Extras pay only in that player’s world.</li>
<li><strong>Controls on the same dense universe:</strong> T0-only both-Yes (no extra) = $1 − C; current desk lock = first same-player Yes+No ≤ $0.95 (this venue or the other venue), sit out $0 if it never prints.</li>
<li><strong>No-hedge D=n</strong> is a comparison row only (already DISMISS). It is not the main trade on this page.</li>
<li>This page does not overwrite <code>tracked_inmatch_books_20261021.html</code>.</li>
</ul>
<p>Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h2>1. Primary — first-dip extra Yes (one extra per player)</h2>
<p class="note">Dense universe only. Mean / median / win rate are settled books. Mix includes still-live books. Click column headers to sort.</p>
{table(d_headers(), first_fmt, d_fields())}

<h2>2. Ladder — extra Yes every additional n cents down</h2>
<p class="note">Same books. A player can fill more than one extra if they keep falling full n-cent steps from T0. Label: this is not the primary sim.</p>
{table(d_headers(), ladder_fmt, d_fields())}

<h2>3. Control vs candidate — same dense universe</h2>
<p class="note">Control 1 is the current Yes+No ≤ $0.95 lock (sit-out $0). Control 2 is T0-only both-Yes. Candidates are first-dip extra Yes and the ladder. No-hedge D=n is a comparison row we already DISMISS. Deltas are candidate minus that control. Ann ROR / Max DD / Calmar / Sharpe are n/a — no days held. Click column headers to sort.</p>
{table(
    [("Arm", "text"), ("Role", "text"), ("N books", "num"), ("N settled", "num"),
     ("Mean $", "num"), ("Median $", "num"), ("Win rate %", "num"),
     ("Mean cost", "num"), ("% both extra / lock taken", "num"), ("% one extra", "num"), ("% none / sit out", "num"),
     ("Δ mean $ vs lock", "num"), ("Δ mean $ vs T0-only", "num"),
     ("Ann ROR full", "text"), ("Ann ROR IS", "text"), ("Ann ROR OOS", "text"),
     ("Max DD", "text"), ("Calmar", "text"), ("Sharpe", "text"),
     ("Note", "text")],
    payload["compare_rows"],
    ["arm", "role", "n", "n_settled", "mean", "median", "win_pct",
     "mean_cost", "pct_both", "pct_one", "pct_none", "d_mean_lock", "d_mean_hold",
     "ann_ror", "ann_ror_is", "ann_ror_oos", "max_dd", "calmar", "sharpe", "note"],
)}

<h2>4. Current lock on the same dense universe</h2>
<p class="note">Sit-out P&amp;L is $0 when the lock never prints. Mean $ on all settled includes those zeros.</p>
{table(
    [("Book", "text"), ("N books", "num"), ("N lock taken", "num"), ("% taken", "num"),
     ("N settled", "num"), ("Mean $ all settled (0 if sit out)", "num"), ("Median $ all settled", "num"),
     ("Mean $ when taken", "num"), ("Median $ when taken", "num"), ("Win % when taken", "num"),
     ("N same-venue Yes+No", "num"), ("N cross-venue Yes+No", "num"),
     ("Note", "text")],
    payload["lock_rows"],
    ["book", "n", "n_taken", "pct_taken", "n_settled", "mean_all", "median_all",
     "mean_taken", "median_taken", "win_taken", "n_same", "n_cross", "note"],
)}

<h2>5. No-hedge D=n on the same dense universe (comparison only)</h2>
<p class="note">Buy both Yes at T0, then one No on each name the first time that Yes falls D cents. Already DISMISS on the wider tracked page. Shown here so the same dense books can be compared. Not the main trade.</p>
{table(d_headers(), no_fmt, d_fields())}

<h2>6. Miyoshi vs Jong</h2>
{payload.get('miyoshi_html') or ''}

<h2>7. Per-match dense tennis</h2>
<p class="note">One row per book that meets the ≥{TICK_BAR} in-play bar. Extras and P&amp;L are the primary first-dip extra Yes. Ladder D=25 is labeled separately. Click column headers to sort.</p>
{table(
    [("Match", "text"), ("Date", "date"), ("Venue", "text"),
     ("Yes A", "text"), ("T0 A", "num"), ("Yes B", "text"), ("T0 B", "num"), ("C", "num"),
     ("in-play ticks", "num"), ("in-play Yes", "num"), ("in-play No", "num"), ("pre-T0 ticks", "num"),
     ("Max gap min", "num"), ("Max dip A", "num"), ("Max dip B", "num"),
     ("D=5 mix", "text"), ("D=5 extras", "text"), ("D=5 P&L", "num"),
     ("D=10 mix", "text"), ("D=10 extras", "text"), ("D=10 P&L", "num"),
     ("D=15 mix", "text"), ("D=15 extras", "text"), ("D=15 P&L", "num"),
     ("D=20 mix", "text"), ("D=20 extras", "text"), ("D=20 P&L", "num"),
     ("D=25 mix", "text"), ("D=25 extras", "text"), ("D=25 P&L", "num"),
     ("Ladder D=25 fills", "text"), ("Ladder D=25 extras N", "num"), ("Ladder D=25 P&L", "num"),
     ("T0-only P&L", "num"), ("Winner", "text"), ("Still live?", "text"),
     ("T0 label", "text"), ("T0 when", "text"), ("Actual start source", "text"), ("Clock hid match?", "text")],
    payload["match_rows"],
    ["game", "date", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0",
     "inplay_n", "inplay_yes", "inplay_no", "pre_n", "max_gap", "max_dip_a", "max_dip_b",
     "mix5", "ex5", "pnl5", "mix10", "ex10", "pnl10", "mix15", "ex15", "pnl15",
     "mix20", "ex20", "pnl20", "mix25", "ex25", "pnl25",
     "lad25", "lad_n", "lad_pnl", "hold_pnl", "winner", "live",
     "t0_label", "t0_when", "actual_source", "listed_stale"],
)}

<h2>8. Near-miss books (50–199 in-play ticks)</h2>
<p class="note">Same T0 / C / competitive freeze, but under the 200-tick bar. Not scored in the D tables. Shown so the bar is visible. Cap 40, densest first.</p>
{table(
    [("Match", "text"), ("Date", "date"), ("Venue", "text"),
     ("T0 A", "num"), ("T0 B", "num"), ("C", "num"),
     ("in-play ticks", "num"), ("Max dip A", "num"), ("Max dip B", "num"),
     ("T0 label", "text"), ("Clock hid match?", "text"), ("Still live?", "text")],
    near,
    ["game", "date", "venue", "t0_a", "t0_b", "c0", "inplay_n", "max_dip_a", "max_dip_b",
     "t0_label", "listed_stale", "live"],
)}

<h2>How to read this</h2>
<ul>
<li>If a book is not on the dense table, we did not store 200 in-play price changes after actual-start T0. That can still be a collection hole, but this page will not treat a quiet window as “never dipped.”</li>
<li>If listed start is late, the old in-match column hid the tape as pre-match. This page rejects that clock when the match already absorbed before it.</li>
<li>KEEP / HOLD / DISMISS is quality versus T0-only both-Yes and versus the current lock on this dense subset, not trade count. Extra Yes on a falling price is a bet that the dumper comes back.</li>
</ul>
<p class="note">Acronyms: ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. T0 is the open used here (last two-sided Yes at or before a trusted actual start, else first competitive two-sided Yes). Vig is the overround when two Yes prices sum over $1. C is the two T0 Yes prices added together.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def near_preview(pairs: list[dict], cap: int = 40) -> list[dict]:
    rows = []
    for p in pairs:
        rows.append({
            "game": p.get("game") or "",
            "date": match_date(p),
            "venue": p.get("venue") or "",
            "t0_a": fmt_px(p.get("t0_a")),
            "t0_b": fmt_px(p.get("t0_b")),
            "c0": fmt_px(p.get("c0")),
            "inplay_n": p.get("inplay_n") or 0,
            "max_dip_a": fmt_px(p.get("max_dip_a")),
            "max_dip_b": fmt_px(p.get("max_dip_b")),
            "t0_label": p.get("t0_label") or "",
            "listed_stale": "yes" if p.get("listed_stale") or p.get("occ_stale") else "no",
            "live": "yes" if not p.get("settled") else "no",
        })
    rows.sort(key=lambda r: (-(r.get("inplay_n") or 0), r.get("game") or ""))
    return rows[:cap]


def lock_table_rows(lock: dict) -> list[dict]:
    return [{
        "book": "Dense tennis, current Yes+No ≤ $0.95",
        "n": lock.get("n"),
        "n_taken": lock.get("n_taken"),
        "pct_taken": lock.get("pct_taken") or "",
        "n_settled": lock.get("n_settled"),
        "mean_all": signed_money(lock.get("mean_all_settled")),
        "median_all": signed_money(lock.get("median_all_settled")),
        "mean_taken": signed_money(lock.get("mean_when_taken")),
        "median_taken": signed_money(lock.get("median_when_taken")),
        "win_taken": lock.get("win_pct_taken") or "",
        "n_same": lock.get("n_same_venue"),
        "n_cross": lock.get("n_cross_venue"),
        "note": lock.get("note") or "",
    }]


def main() -> None:
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
    n_t0 = 0
    in_range = []
    for pair in tennis:
        mark_inplay(pair)
        if pair.get("t0_a") is None or pair.get("t0_b") is None or pair.get("t0_ts") is None:
            continue
        n_t0 += 1
        c0 = pair.get("c0")
        if c0 is None:
            continue
        if C_LO - 1e-12 <= c0 <= C_HI + 1e-12 and is_competitive(pair):
            in_range.append(pair)
    any_ticks = [p for p in in_range if (p.get("inplay_n") or 0) >= 1 and p.get("both_inplay")]
    n_near = sum(1 for p in in_range if (p.get("inplay_n") or 0) >= NEAR_BAR and p.get("both_inplay"))
    n_100 = sum(1 for p in in_range if (p.get("inplay_n") or 0) >= 100 and p.get("both_inplay"))
    dense = [p for p in in_range if p.get("dense")]
    near = [
        p for p in in_range
        if p.get("both_inplay") and NEAR_BAR <= (p.get("inplay_n") or 0) < TICK_BAR
    ]
    print(
        f"tennis T0 {n_t0}; competitive C-in-range {len(in_range)}; "
        f">=1 {len(any_ticks)}; >={NEAR_BAR} {n_near}; >=100 {n_100}; "
        f">={TICK_BAR} dense {len(dense)}",
        flush=True,
    )
    extra_named = []
    for p in named_pairs(tennis, "miyoshi", "jong"):
        if p not in dense:
            extra_named.append(p)
    scored = list(dense)
    for pair in scored + extra_named:
        simulate_yes_dip(pair)
    # Lock on the dense set only (same universe). start_dt kept for match_id day.
    simulate_current_lock(dense)
    settled = [p for p in dense if p.get("settled")]
    live = [p for p in dense if not p.get("settled")]
    first_rows = [summarize_yes(dense, dip, "first") for dip in DIPS]
    ladder_rows = [summarize_yes(dense, dip, "ladder") for dip in DIPS]
    no_rows = [summarize_yes(dense, dip, "no") for dip in DIPS]
    hold = summarize_hold(dense)
    lock = summarize_lock(dense)
    for r in first_rows:
        print(
            f"FIRST D={r['dip_cents']}c n={r['n']} settled={r['n_settled']} "
            f"mean={fmt_signed(r['mean'])} median={fmt_signed(r['median'])} "
            f"both={r['pct_both']} one={r['pct_one']} none={r['pct_none']}",
            flush=True,
        )
    for r in ladder_rows:
        print(
            f"LADDER D={r['dip_cents']}c n={r['n']} settled={r['n_settled']} "
            f"mean={fmt_signed(r['mean'])} median={fmt_signed(r['median'])} "
            f"both={r['pct_both']} one={r['pct_one']} none={r['pct_none']}",
            flush=True,
        )
    print(
        f"HOLD t0-only mean={fmt_signed(hold.get('mean'))} median={fmt_signed(hold.get('median'))} "
        f"settled={hold.get('n_settled')}",
        flush=True,
    )
    print(
        f"LOCK n={lock['n']} taken={lock['n_taken']} settled={lock['n_settled']} "
        f"mean_all={fmt_signed(lock.get('mean_all_settled'))}",
        flush=True,
    )
    verdict, sweet_text = decide_verdict(first_rows, hold, lock)
    lock_mean = lock.get("mean_all_settled")
    hold_mean = hold.get("mean")
    scored_first = [r for r in first_rows if r.get("mean") is not None]
    best = max(scored_first, key=lambda r: r["mean"]) if scored_first else None
    if best is None or hold_mean is None or lock_mean is None:
        vs_text = "Not enough settled dense rows to compare."
    else:
        vs_text = (
            f"Best first-dip mean {fmt_signed(best['mean'])} (D={best['dip_cents']}¢) vs "
            f"T0-only {fmt_signed(hold_mean)} vs lock {fmt_signed(lock_mean)}. "
            f"Verdict {verdict}."
        )
    miyoshi_text, miyoshi_html = miyoshi_section(dense + extra_named)
    print(f"MIYOSHI {miyoshi_text}", flush=True)
    print(f"VERDICT {verdict}", flush=True)
    payload = {
        "written_at": iso_now(),
        "stream": stream,
        "first_rows": first_rows,
        "ladder_rows": ladder_rows,
        "no_rows": no_rows,
        "compare_rows": compare_rows(first_rows, ladder_rows, no_rows, hold, lock),
        "lock_rows": lock_table_rows(lock),
        "sweet_text": sweet_text,
        "vs_text": vs_text,
        "verdict": verdict,
        "n_pairs": len(tennis),
        "n_t0": n_t0,
        "n_in": len(in_range),
        "n_any": len(any_ticks),
        "n_near": n_near,
        "n_100": n_100,
        "n_dense": len(dense),
        "n_dense_settled": len(settled),
        "n_dense_live": len(live),
        "note_n": tiny_note(len(settled)),
        "miyoshi_text": miyoshi_text,
        "miyoshi_html": miyoshi_html,
        "match_rows": per_match_rows(dense),
        "near_rows": near_preview(near),
    }
    write_html(payload)
    copy_g(PAGE)
    print("done", flush=True)


if __name__ == "__main__":
    main()
