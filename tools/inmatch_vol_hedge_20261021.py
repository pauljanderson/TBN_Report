"""In-match moneyline volatility and both-Yes-then-hedge study.

Research only. Reads price_memory.jsonl, odds_snapshots.jsonl, catalogs, and
official settlements. Does not place, cancel, or amend orders. Does not print
secrets. Does not touch orders_stopped.json. Not gold. Not DailyRun.
"""
from __future__ import annotations

import json
import math
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
from odds_cross_no_roi_60_70_20261020 import copy_g
from odds_cross_winrate_20261020 import (
    as_float,
    attach_results,
    build_index,
    game_norm,
    parse_dt,
    pct,
    table,
    tiny_note,
)
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from tennis_decade_at_start_20261020 import start_lookup_from
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import HISTORY, iter_tick_lines, to_et
PAGE = STAMP / "inmatch_vol_hedge_20261021.html"
JSON_OUT = RAW / "inmatch_vol_hedge_20261021.json"
SNAPSHOTS = RAW / "odds_snapshots.jsonl"
ET = ZoneInfo("America/New_York")
LOCK_SUM = 0.95
TARGETS = (0.05, 0.10, 0.25)
DURING_MINUTES = {
    "tennis": 360,
    "college football": 240,
    "pro football": 210,
    "soccer": 150,
    "pro hockey": 200,
    "pro baseball": 240,
    "mma": 180,
    "golf": 360,
    "motorsports": 180,
    "chess": 180,
    "basketball": 180,
    "wnba": 180,
    "nba": 180,
    "college basketball": 180,
}
ASKED = (
    "what sports tend to have the most volatility during a match? I am asking because I am curious "
    "if we can take advantage of some of the volatility? for example, in a specific tennis match "
    "Prizmic vs Dzumhur the game started with prizmic to win at 68.5% his chances of winning moved "
    "between that beginning point to 57.9 at the low to 74.1% at the high before he lost the first "
    "match, then he was under 50%, then they both swapped places until it was clear that Dzumhur was "
    "going to win about 2 hours and 42 minutes into the game. I'm sure there are some games that never "
    "cross over, but it would surprise me if the initial price doesn't move a bit lower at some point. "
    "How much do the prices move and can we put together a strategy that would win us money? example. "
    "buy 1 contract to win for each player/team. then, when the inevitable happens and the odds change, "
    "we bet again, taking the hedge on each player so we make money. can you run a report on this idea "
    "to see what the optimal amount would be to cash in on? i.e. do we buy the hedge bets to make 0.05? "
    "0.10? 0.25? (in this case we would need to also cover the amount we are set to lose by buying both "
    "opposite bets at the outset, because it will cost 1.15 or whatever) and please propose some other "
    "ideas once you comb through the data. perhaps it's a universal system, or perhaps it's one per sport."
)
PLAIN = (
    "A Yes price is a dollar from 0 to 1, also an implied chance: 0.685 means that named player is "
    "listed at 68.5 percent to win (moneyline: who wins the match). T0 is the last Yes we have at or "
    "before listed start; if we missed the pre-start book, T0 is the first time both sides have a live "
    "Yes, and we label that. In-match means after that T0 print, inside a typical game length. "
    "Vig is the house's built-in fee in the prices: if Prizmic Yes costs $0.685 and Dzumhur Yes costs "
    "$0.465, buying one of each costs $1.15. Only one player can win, so those two tickets always pay "
    "exactly $1 at settlement. You are already down $0.15 if you never trade. That gap is the vig, not "
    "a bug. Holding 1+1 Yes cannot lock a $0.05 / $0.10 / $0.25 profit, because the floor payout stays "
    "$1 while extra buys raise the bill. A single extra Yes or No pays in only one world, so the worst "
    "world gets worse. Buying No on the risen player pairs with the Yes you already hold (a same-player "
    "lock that pays $1 on that name) but you still hold the other Yes: one world pays $1 (a bigger loss) "
    "and the other pays $2 (maybe a win). That is not a two-outcome lock unless you also sell or offset "
    "the leftover Yes. We do not assume a sell unless the tape already has a No ask we can buy. Fills are "
    "at the printed ask (optimistic). Short October 2026 tape. Research only. Not gold. Not DailyRun. No KEEP."
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


def fmt_n(value, digits: int = 1) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def median(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(statistics.median(xs))


def mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(statistics.fmean(xs))


def duration_min(sport: str) -> int:
    return DURING_MINUTES.get((sport or "").lower(), 240)


def last_at_or_before(ticks: list[tuple[int, float]], t: int) -> tuple[int, float] | None:
    hit = None
    for ts, px in ticks:
        if ts <= t:
            hit = (ts, px)
        else:
            break
    return hit


def first_after(ticks: list[tuple[int, float]], t: int) -> tuple[int, float] | None:
    for ts, px in ticks:
        if ts > t:
            return ts, px
    return None


def ticks_between(ticks: list[tuple[int, float]], lo: int, hi: int) -> list[tuple[int, float]]:
    return [(ts, px) for ts, px in ticks if lo < ts <= hi]


def first_absorbing(ticks_a: list[tuple[int, float]], ticks_b: list[tuple[int, float]]) -> int | None:
    """First time either Yes prints at 5¢ or 95¢ — match is effectively over."""
    hit = None
    for ts, px in ticks_a + ticks_b:
        if px <= 0.05 or px >= 0.95:
            if hit is None or ts < hit:
                hit = ts
    return hit


def thin_ticks(ticks: list[tuple[int, float]], n: int = 220) -> list[tuple[int, float]]:
    if len(ticks) <= n:
        return ticks
    step = len(ticks) / n
    out = [ticks[min(len(ticks) - 1, int(i * step))] for i in range(n)]
    if out[-1] != ticks[-1]:
        out.append(ticks[-1])
    return out


def forward_fill(ticks: list[tuple[int, float]], times: list[int]) -> dict[int, float]:
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


def load_snapshot_t0() -> dict[tuple[str, str, str], dict]:
    out: dict[tuple[str, str, str], dict] = {}
    if not SNAPSHOTS.is_file():
        return out
    with SNAPSHOTS.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict) or rec.get("snapshot") != "t0":
                continue
            key = (
                game_norm(rec.get("game") or ""),
                game_norm(rec.get("player") or ""),
                str(rec.get("venue") or ""),
            )
            out[key] = rec
    return out


def stream_moneylines() -> dict:
    print("streaming moneyline yes/no (archive + shards)", flush=True)
    series: dict[tuple, dict] = {}
    n_lines = 0
    n_hits = 0
    seen_min = None
    seen_max = None
    for line in iter_tick_lines():
            n_lines += 1
            if n_lines % 400000 == 0:
                print(f"  {n_lines} lines, series {len(series)}", flush=True)
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
            sport = str(rec.get("sport") or "unknown")
            game = rec.get("game") or ""
            side = rec.get("side") or rec.get("side_label") or ""
            venue = rec.get("venue") or ""
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
            else:
                if rec.get("game_start") and not st["start"]:
                    st["start"] = rec.get("game_start") or ""
                if rec.get("sport") and st["sport"] in ("", "unknown"):
                    st["sport"] = rec["sport"]
            ticks = st["ticks"]
            px = round(price, 4)
            if ticks and ticks[-1][1] == px:
                continue
            ticks.append((ts, px))
            n_hits += 1
            if seen:
                if seen_min is None or seen < seen_min:
                    seen_min = seen
                if seen_max is None or seen > seen_max:
                    seen_max = seen
    print(f"stream done lines={n_lines} ml_change_ticks={n_hits} series={len(series)}", flush=True)
    return {
        "series": series,
        "n_lines": n_lines,
        "n_hits": n_hits,
        "seen_min": seen_min or "",
        "seen_max": seen_max or "",
    }


def pair_matches(series: dict[tuple, dict], start_lookup: dict) -> list[dict]:
    bags: dict[tuple, dict] = {}
    for (sport, game, venue, side, pay), st in series.items():
        gkey = (game, venue)
        bag = bags.get(gkey)
        if bag is None:
            bag = {"game": game, "venue": venue, "sport": sport, "yes": {}, "no": {}, "starts": []}
            bags[gkey] = bag
        if sport and sport not in ("", "unknown"):
            bag["sport"] = sport
        if st.get("start"):
            bag["starts"].append(st["start"])
        if pay == "yes":
            bag["yes"][side] = st
        else:
            bag["no"][side] = st
    pairs = []
    for bag in bags.values():
        sides = list(bag["yes"])
        if len(sides) != 2:
            continue
        a, b = sides[0], sides[1]
        sport = bag["sport"] or "unknown"
        start_text = ""
        for raw in bag["starts"]:
            if parse_dt(raw):
                start_text = raw
                break
        gnorm = game_norm(bag["game"])
        extra = start_lookup.get(gnorm)
        if extra:
            cand, _src = extra
            if parse_dt(cand) and not start_text:
                start_text = cand
        start_dt = parse_dt(start_text)
        pairs.append({
            "sport": sport,
            "game": bag["game"],
            "venue": bag["venue"],
            "side_a": a,
            "side_b": b,
            "yes_a": bag["yes"][a]["ticks"],
            "yes_b": bag["yes"][b]["ticks"],
            "no_a": (bag["no"].get(a) or {}).get("ticks") or [],
            "no_b": (bag["no"].get(b) or {}).get("ticks") or [],
            "start": start_text,
            "start_dt": start_dt,
        })
    print(f"two-sided moneyline pairs {len(pairs)}", flush=True)
    return pairs


def assign_t0(pair: dict) -> None:
    start_dt = pair.get("start_dt")
    yes_a = pair["yes_a"]
    yes_b = pair["yes_b"]
    pair["t0_label"] = ""
    pair["t0_a"] = None
    pair["t0_b"] = None
    pair["t0_ts"] = None
    if not yes_a or not yes_b:
        return
    if start_dt is not None:
        start_ts = int(to_et(start_dt).timestamp())
        pre_a = last_at_or_before(yes_a, start_ts)
        pre_b = last_at_or_before(yes_b, start_ts)
        if pre_a and pre_b:
            pair["t0_a"] = pre_a[1]
            pair["t0_b"] = pre_b[1]
            pair["t0_ts"] = max(pre_a[0], pre_b[0])
            pair["t0_label"] = "last Yes ≤ start"
            return
        # first two-sided in-game (or mixed pre-start + first other print)
        have_a = pre_a[1] if pre_a else None
        have_b = pre_b[1] if pre_b else None
        merged = sorted([(t, "a", p) for t, p in yes_a if t >= start_ts] + [(t, "b", p) for t, p in yes_b if t >= start_ts])
        for t, who, p in merged:
            if who == "a":
                have_a = p
            else:
                have_b = p
            if have_a is not None and have_b is not None:
                pair["t0_a"] = have_a
                pair["t0_b"] = have_b
                pair["t0_ts"] = t
                pair["t0_label"] = "first two-sided in-game" if not (pre_a and pre_b) else "last Yes ≤ start"
                if (pre_a is None) != (pre_b is None):
                    pair["t0_label"] = "mixed pre-start + first in-game"
                return
        return
    # no start: first two-sided print labeled
    have_a = have_b = None
    merged = sorted([(t, "a", p) for t, p in yes_a] + [(t, "b", p) for t, p in yes_b])
    for t, who, p in merged:
        if who == "a":
            have_a = p
        else:
            have_b = p
        if have_a is not None and have_b is not None:
            pair["t0_a"] = have_a
            pair["t0_b"] = have_b
            pair["t0_ts"] = t
            pair["t0_label"] = "no-start first two-sided"
            return


def window_end(pair: dict) -> int | None:
    start_dt = pair.get("start_dt")
    t0 = pair.get("t0_ts")
    minutes = duration_min(pair.get("sport") or "")
    if start_dt is not None:
        return int(to_et(start_dt).timestamp()) + minutes * 60
    if t0 is not None:
        return t0 + minutes * 60
    return None


def side_vol(t0: float, ticks: list[tuple[int, float]]) -> dict:
    if not ticks:
        return {
            "in_min": None, "in_max": None, "range": None, "max_dip": None,
            "ever_below": False, "t_first_dip": None, "t_first_50": None, "n_ticks": 0,
        }
    prices = [p for _, p in ticks]
    in_min = min(prices)
    in_max = max(prices)
    dip_t = None
    cross50 = None
    for ts, px in ticks:
        if dip_t is None and px < t0:
            dip_t = ts
        if cross50 is None and px < 0.50:
            cross50 = ts
    return {
        "in_min": in_min,
        "in_max": in_max,
        "range": in_max - in_min,
        "max_dip": max(0.0, t0 - in_min),
        "ever_below": in_min < t0,
        "t_first_dip": dip_t,
        "t_first_50": cross50,
        "n_ticks": len(ticks),
    }


def analyze_vol(pairs: list[dict]) -> None:
    for pair in pairs:
        assign_t0(pair)
        t0_ts = pair.get("t0_ts")
        end_ts = window_end(pair)
        pair["in_a"] = []
        pair["in_b"] = []
        if t0_ts is None or pair.get("t0_a") is None or pair.get("t0_b") is None:
            pair["vol_a"] = side_vol(0, [])
            pair["vol_b"] = side_vol(0, [])
            pair["usable"] = False
            continue
        if end_ts is None:
            end_ts = t0_ts + duration_min(pair.get("sport") or "") * 60
        start_dt = pair.get("start_dt")
        if start_dt is not None:
            start_ts = int(to_et(start_dt).timestamp())
            vol_lo = max(t0_ts, start_ts)
        else:
            start_ts = None
            vol_lo = t0_ts
        pair["end_ts"] = end_ts
        pair["vol_lo"] = vol_lo
        hedge_a = ticks_between(pair["yes_a"], t0_ts, end_ts)
        hedge_b = ticks_between(pair["yes_b"], t0_ts, end_ts)
        pair["in_a"] = hedge_a
        pair["in_b"] = hedge_b
        pair["in_no_a"] = ticks_between(pair["no_a"], t0_ts, end_ts) if pair["no_a"] else []
        pair["in_no_b"] = ticks_between(pair["no_b"], t0_ts, end_ts) if pair["no_b"] else []
        absorb = first_absorbing(hedge_a, hedge_b)
        vol_hi = min(end_ts, absorb - 1) if absorb else end_ts
        vol_a_ticks = ticks_between(pair["yes_a"], vol_lo, vol_hi)
        vol_b_ticks = ticks_between(pair["yes_b"], vol_lo, vol_hi)
        pair["vol_a"] = side_vol(pair["t0_a"], vol_a_ticks)
        pair["vol_b"] = side_vol(pair["t0_b"], vol_b_ticks)
        c0 = (pair.get("t0_a") or 0) + (pair.get("t0_b") or 0)
        pair["good_book"] = 0.90 <= c0 <= 1.15
        n_live = (pair["vol_a"].get("n_ticks") or 0) + (pair["vol_b"].get("n_ticks") or 0)
        pair["usable"] = n_live >= 2
        pair["n_live"] = n_live
        if pair["t0_a"] >= pair["t0_b"]:
            pair["fav"] = "a"
            pair["t0_fav"] = pair["t0_a"]
            pair["vol_fav"] = pair["vol_a"]
            pair["fav_side"] = pair["side_a"]
            pair["dog_side"] = pair["side_b"]
            pair["t0_dog"] = pair["t0_b"]
        else:
            pair["fav"] = "b"
            pair["t0_fav"] = pair["t0_b"]
            pair["vol_fav"] = pair["vol_b"]
            pair["fav_side"] = pair["side_b"]
            pair["dog_side"] = pair["side_a"]
            pair["t0_dog"] = pair["t0_a"]
        pair["c0"] = pair["t0_a"] + pair["t0_b"]
        vf = pair["vol_fav"]
        pair["fav_dip"] = vf.get("max_dip") or 0.0
        pair["fav_ever_below"] = bool(vf.get("ever_below"))
        pair["range_mean"] = None
        ra, rb = pair["vol_a"].get("range"), pair["vol_b"].get("range")
        if ra is not None and rb is not None:
            pair["range_mean"] = (ra + rb) / 2.0
        pair["range_max"] = max([x for x in (ra, rb) if x is not None], default=None)


def mins_after(ts: int | None, origin: int | None) -> float | None:
    if ts is None or origin is None:
        return None
    return (ts - origin) / 60.0


def attach_pair_results(pairs: list[dict], settlements: list[dict]) -> None:
    index = build_index(settlements)
    crosses = []
    last_map = {}
    for i, pair in enumerate(pairs):
        for letter, side, ticks in (("a", pair["side_a"], pair["yes_a"]), ("b", pair["side_b"], pair["yes_b"])):
            key = f"pair{i}|{letter}"
            last_px = ticks[-1][1] if ticks else None
            last_ts = ticks[-1][0] if ticks else None
            last_map[key] = {
                "price": last_px,
                "seen_at": datetime.fromtimestamp(last_ts, ET).isoformat() if last_ts else "",
                "game_start": pair.get("start") or "",
                "sport": pair.get("sport") or "",
            }
            crosses.append({
                "key": key,
                "sport": pair.get("sport") or "",
                "game": pair.get("game") or "",
                "market_type": "moneyline",
                "side": side,
                "side_key": game_norm(side),
                "number": "",
                "venue": pair.get("venue") or "",
                "cross_time": datetime.fromtimestamp(pair["t0_ts"], ET).isoformat() if pair.get("t0_ts") else "",
                "game_start": pair.get("start") or "",
            })
    attach_results(crosses, last_map, settlements, index)
    by_key = {c["key"]: c for c in crosses}
    for i, pair in enumerate(pairs):
        ca = by_key.get(f"pair{i}|a") or {}
        cb = by_key.get(f"pair{i}|b") or {}
        pair["off_a"] = ca.get("official") or "pending"
        pair["off_b"] = cb.get("official") or "pending"
        pair["off_src_a"] = ca.get("official_source") or ""
        pair["off_src_b"] = cb.get("official_source") or ""
        winner = None
        if pair["off_a"] == "win" and pair["off_b"] == "loss":
            winner = "a"
        elif pair["off_b"] == "win" and pair["off_a"] == "loss":
            winner = "b"
        elif pair["off_a"] == "win" and pair["off_b"] != "win":
            winner = "a"
        elif pair["off_b"] == "win" and pair["off_a"] != "win":
            winner = "b"
        pair["winner"] = winner
        pair["settled"] = winner is not None


def merged_times(pair: dict) -> list[int]:
    bags = []
    for name in ("in_a", "in_b", "in_no_a", "in_no_b"):
        bags.extend(ts for ts, _ in pair.get(name) or [])
    times = sorted(set(bags))
    if len(times) > 8000:
        step = max(1, len(times) // 8000)
        times = times[::step]
    return times


def hedge_search(pair: dict) -> dict:
    out = {
        "c0": pair.get("c0"),
        "hold_pnl": None,
        "already_lock": False,
        "add1_lock": {t: None for t in TARGETS},
        "add2_lock": {t: None for t in TARGETS},
        "offset": None,
        "risen_no": None,
        "same_player_cheap_after": None,
        "two_yes_095": None,
        "buy_dog_wait_fav": None,
        "buy_fav_wait_dog": None,
        "n_times": 0,
    }
    if not pair.get("usable") or pair.get("t0_a") is None:
        return out
    c0 = pair["c0"]
    out["hold_pnl"] = 1.0 - c0
    if c0 <= LOCK_SUM:
        out["already_lock"] = True
    times = merged_times(pair)
    out["n_times"] = len(times)
    if not times:
        return out
    fa = forward_fill(pair["yes_a"], times)
    fb = forward_fill(pair["yes_b"], times)
    na = forward_fill(pair["no_a"], times) if pair.get("no_a") else {}
    nb = forward_fill(pair["no_b"], times) if pair.get("no_b") else {}
    t0a, t0b = pair["t0_a"], pair["t0_b"]
    t0_ts = pair["t0_ts"]

    def record_first(slot: dict, target: float, ts: int, payload: dict) -> None:
        if slot.get(target) is None:
            payload = dict(payload)
            payload["ts"] = ts
            payload["mins"] = mins_after(ts, t0_ts)
            slot[target] = payload

    for t in times:
        ya, yb = fa.get(t), fb.get(t)
        nxa, nxb = na.get(t), nb.get(t)
        if ya is None or yb is None:
            continue
        # 1-contract adds after 1+1: floor payout stays $1
        for extra_cost in (ya, yb, nxa, nxb):
            if extra_cost is None:
                continue
            worst = 1.0 - (c0 + extra_cost)
            for target in TARGETS:
                if worst + 1e-12 >= target:
                    record_first(out["add1_lock"], target, t, {
                        "kind": "1-contract add",
                        "worst": worst,
                        "cost": c0 + extra_cost,
                    })
        # 2-contract that can raise BOTH worlds: extra Yes X + No X (second same-player pair)
        if nxa is not None:
            cost = c0 + ya + nxa
            worst = 2.0 - cost
            for target in TARGETS:
                if worst + 1e-12 >= target:
                    record_first(out["add2_lock"], target, t, {
                        "kind": "extra Yes A + No A",
                        "worst": worst,
                        "cost": cost,
                        "pair_sum": ya + nxa,
                    })
        if nxb is not None:
            cost = c0 + yb + nxb
            worst = 2.0 - cost
            for target in TARGETS:
                if worst + 1e-12 >= target:
                    record_first(out["add2_lock"], target, t, {
                        "kind": "extra Yes B + No B",
                        "worst": worst,
                        "cost": cost,
                        "pair_sum": yb + nxb,
                    })
        # Offset: buy No on X, leftover Yes remains
        if out["offset"] is None:
            for label, t0x, nx in (("a", t0a, nxa), ("b", t0b, nxb)):
                if nx is None:
                    continue
                if t0x + nx <= LOCK_SUM:
                    pnl_x_wins = 1.0 - c0 - nx
                    pnl_other = 2.0 - c0 - nx
                    out["offset"] = {
                        "player": pair["side_a"] if label == "a" else pair["side_b"],
                        "n": nx,
                        "same_player_cost": t0x + nx,
                        "pnl_if_that_player_wins": pnl_x_wins,
                        "pnl_if_other_wins": pnl_other,
                        "worst": min(pnl_x_wins, pnl_other),
                        "ts": t,
                        "mins": mins_after(t, t0_ts),
                    }
                    break
        # Buy-No the risen side
        if out["risen_no"] is None:
            for label, t0x, yx, nx in (("a" , t0a, ya, nxa), ("b", t0b, yb, nxb)):
                if nx is None or yx is None or yx <= t0x:
                    continue
                worst = 1.0 - c0 - nx
                out["risen_no"] = {
                    "player": pair["side_a"] if label == "a" else pair["side_b"],
                    "yes_now": yx,
                    "n": nx,
                    "worst": worst,
                    "pnl_if_risen_wins": worst,
                    "pnl_if_other_wins": 2.0 - c0 - nx,
                    "ts": t,
                    "mins": mins_after(t, t0_ts),
                }
                break
        if out["same_player_cheap_after"] is None:
            for yx, nx in ((ya, nxa), (yb, nxb)):
                if yx is None or nx is None:
                    continue
                if yx + nx <= LOCK_SUM:
                    out["same_player_cheap_after"] = {
                        "sum": yx + nx,
                        "ts": t,
                        "mins": mins_after(t, t0_ts),
                    }
                    break
        if out["two_yes_095"] is None and ya + yb <= LOCK_SUM:
            out["two_yes_095"] = {
                "sum": ya + yb,
                "ts": t,
                "mins": mins_after(t, t0_ts),
            }
        # buy dog at T0, wait for fav Yes cheap enough
        if out["buy_dog_wait_fav"] is None:
            fav_now = ya if pair.get("fav") == "a" else yb
            dog_t0 = pair.get("t0_dog")
            if fav_now is not None and dog_t0 is not None and dog_t0 + fav_now <= LOCK_SUM:
                out["buy_dog_wait_fav"] = {
                    "sum": dog_t0 + fav_now,
                    "ts": t,
                    "mins": mins_after(t, t0_ts),
                    "lock_pnl": 1.0 - (dog_t0 + fav_now),
                }
        if out["buy_fav_wait_dog"] is None:
            dog_now = yb if pair.get("fav") == "a" else ya
            fav_t0 = pair.get("t0_fav")
            if dog_now is not None and fav_t0 is not None and fav_t0 + dog_now <= LOCK_SUM:
                out["buy_fav_wait_dog"] = {
                    "sum": fav_t0 + dog_now,
                    "ts": t,
                    "mins": mins_after(t, t0_ts),
                    "lock_pnl": 1.0 - (fav_t0 + dog_now),
                }
    return out


def take_pnl(pair: dict, hedge: dict, target: float) -> dict:
    """P&L if we take first qualifying 2-contract lock vs hold. Official winner only."""
    hold = hedge.get("hold_pnl")
    hit = (hedge.get("add2_lock") or {}).get(target)
    winner = pair.get("winner")
    out = {"hold": hold, "take": None, "delta": None}
    if hold is None:
        return out
    if not pair.get("settled") or winner is None:
        return out
    if hit is None:
        out["take"] = hold
        out["delta"] = 0.0
        return out
    # extra Yes X + No X: always +$1 vs hold (pays $2, costs extra yes+no), regardless of winner
    extra = hit.get("pair_sum")
    if extra is None:
        out["take"] = hold
        out["delta"] = 0.0
        return out
    take = 2.0 - (pair["c0"] + extra)
    out["take"] = take
    out["delta"] = take - hold
    return out


def sport_vol_rows(pairs: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        if p.get("usable") and p.get("good_book", True):
            by[p.get("sport") or "unknown"].append(p)
    rows = []
    for sport, items in by.items():
        ranges = [p["range_mean"] for p in items if p.get("range_mean") is not None]
        favs = [p for p in items if p.get("vol_fav")]
        n = len(items)
        n_fav = len(favs)
        dip5 = sum(1 for p in favs if (p.get("fav_dip") or 0) >= 0.05)
        dip10 = sum(1 for p in favs if (p.get("fav_dip") or 0) >= 0.10)
        dip15 = sum(1 for p in favs if (p.get("fav_dip") or 0) >= 0.15)
        ever = sum(1 for p in favs if p.get("fav_ever_below"))
        t_dip = []
        t_50 = []
        for p in favs:
            origin = p.get("vol_lo") or p.get("t0_ts")
            d = mins_after((p.get("vol_fav") or {}).get("t_first_dip"), origin)
            c = mins_after((p.get("vol_fav") or {}).get("t_first_50"), origin)
            if d is not None:
                t_dip.append(d)
            if c is not None:
                t_50.append(c)
        dips = [p.get("fav_dip") or 0 for p in favs]
        rows.append({
            "sport": sport,
            "n": n,
            "median_range": fmt_px(median(ranges)),
            "mean_range": fmt_px(mean(ranges)),
            "median_fav_dip": fmt_px(median(dips)),
            "mean_fav_dip": fmt_px(mean(dips)),
            "pct_ever_below": pct(ever, n_fav),
            "pct_dip5": pct(dip5, n_fav),
            "pct_dip10": pct(dip10, n_fav),
            "pct_dip15": pct(dip15, n_fav),
            "n_ever_below": ever,
            "n_dip5": dip5,
            "n_dip10": dip10,
            "n_dip15": dip15,
            "median_t_dip": fmt_n(median(t_dip)),
            "median_t_50": fmt_n(median(t_50)),
            "n_cross50": len(t_50),
            "note": tiny_note(n),
            "_sort_range": median(ranges) or -1,
        })
    rows.sort(key=lambda r: (-(r["_sort_range"]), -(r["n"])))
    return rows


def hedge_sport_rows(pairs: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        if p.get("usable") and p.get("good_book", True) and p.get("hedge"):
            by[p.get("sport") or "unknown"].append(p)
    rows = []
    for sport, items in by.items():
        n = len(items)
        settled = [p for p in items if p.get("settled")]
        hold_pnls = [p["hedge"]["hold_pnl"] for p in settled if p["hedge"].get("hold_pnl") is not None]
        rec = {
            "sport": sport,
            "n": n,
            "n_settled": len(settled),
            "median_c0": fmt_px(median([p["c0"] for p in items if p.get("c0") is not None])),
            "median_hold": fmt_px(median(hold_pnls)),
            "mean_hold": fmt_px(mean(hold_pnls)),
            "pct_already_lock": pct(sum(1 for p in items if p["hedge"].get("already_lock")), n),
            "note": tiny_note(n),
        }
        for target in TARGETS:
            lab = f"{int(target * 100):02d}"
            add1 = sum(1 for p in items if p["hedge"]["add1_lock"].get(target))
            add2 = sum(1 for p in items if p["hedge"]["add2_lock"].get(target))
            mins = [p["hedge"]["add2_lock"][target]["mins"] for p in items if p["hedge"]["add2_lock"].get(target) and p["hedge"]["add2_lock"][target].get("mins") is not None]
            rec[f"pct_add1_{lab}"] = pct(add1, n)
            rec[f"pct_add2_{lab}"] = pct(add2, n)
            rec[f"n_add2_{lab}"] = add2
            rec[f"med_t_add2_{lab}"] = fmt_n(median(mins))
            takes = []
            holds = []
            for p in settled:
                got = take_pnl(p, p["hedge"], target)
                if got.get("take") is not None and got.get("hold") is not None:
                    takes.append(got["take"])
                    holds.append(got["hold"])
            rec[f"mean_take_{lab}"] = fmt_px(mean(takes))
            rec[f"mean_hold_{lab}"] = fmt_px(mean(holds))
        rec["pct_offset"] = pct(sum(1 for p in items if p["hedge"].get("offset")), n)
        rec["pct_risen_no"] = pct(sum(1 for p in items if p["hedge"].get("risen_no")), n)
        rec["pct_two_yes"] = pct(sum(1 for p in items if p["hedge"].get("two_yes_095")), n)
        rec["pct_dog_wait"] = pct(sum(1 for p in items if p["hedge"].get("buy_dog_wait_fav")), n)
        rec["pct_fav_wait"] = pct(sum(1 for p in items if p["hedge"].get("buy_fav_wait_dog")), n)
        rec["pct_same_player"] = pct(sum(1 for p in items if p["hedge"].get("same_player_cheap_after")), n)
        rows.append(rec)
    rows.sort(key=lambda r: (-r["n"], r["sport"]))
    return rows


def downsample_path(ticks: list[tuple[int, float]], origin: int, max_points: int = 180) -> list[dict]:
    if not ticks:
        return []
    by_min: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for ts, px in ticks:
        by_min[int((ts - origin) // 60)].append((ts, px))
    rows = []
    for minute in sorted(by_min):
        chunk = by_min[minute]
        lo = min(chunk, key=lambda x: x[1])
        hi = max(chunk, key=lambda x: x[1])
        last = chunk[-1]
        rows.append({
            "minute": minute,
            "min": lo[1],
            "max": hi[1],
            "last": last[1],
            "n": len(chunk),
        })
    if len(rows) > max_points:
        step = math.ceil(len(rows) / max_points)
        kept = rows[::step]
        if rows[-1] not in kept:
            kept.append(rows[-1])
        rows = kept
    return rows


def _side_ticks(priz: dict, name: str) -> list[tuple[int, float]]:
    if name in (priz.get("side_a") or "").lower():
        return priz.get("yes_a") or []
    if name in (priz.get("side_b") or "").lower():
        return priz.get("yes_b") or []
    return []


def svg_path(priz: dict) -> str:
    origin = priz.get("start_ts") or priz.get("t0_ts")
    if origin is None:
        return "<p class='note'>No clocked start, no chart.</p>"
    a = [(ts, px) for ts, px in _side_ticks(priz, "prizmic") if ts >= origin - 600]
    b = [(ts, px) for ts, px in _side_ticks(priz, "dzumhur") if ts >= origin - 600]
    if not a and not b:
        return "<p class='note'>No Yes ticks to chart.</p>"
    end = origin + duration_min("tennis") * 60
    a = [(t, p) for t, p in a if t <= end]
    b = [(t, p) for t, p in b if t <= end]
    if not a:
        return "<p class='note'>No Prizmic Yes ticks in window.</p>"
    a = thin_ticks(a)
    b = thin_ticks(b)
    w, h, pad = 920, 280, 36
    tmin = origin
    if priz.get("t0_ts"):
        tmin = min(tmin, priz["t0_ts"])
    tmax = max(a[-1][0], b[-1][0] if b else a[-1][0], origin + 60)
    span = max(1, tmax - tmin)

    def xy(ts, px):
        x = pad + (ts - tmin) / span * (w - 2 * pad)
        y = pad + (1.0 - px) * (h - 2 * pad)
        return x, y

    def poly(ticks, color):
        if not ticks:
            return ""
        pts = " ".join(f"{xy(t, p)[0]:.1f},{xy(t, p)[1]:.1f}" for t, p in ticks)
        return f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{pts}" />'

    story = [
        (0.685, "#94a3b8", "asked 68.5"),
        (0.579, "#f97316", "asked low 57.9"),
        (0.741, "#16a34a", "asked high 74.1"),
        (0.50, "#64748b", "50"),
    ]
    guides = []
    for px, color, lab in story:
        y = pad + (1.0 - px) * (h - 2 * pad)
        guides.append(
            f'<line x1="{pad}" x2="{w - pad}" y1="{y:.1f}" y2="{y:.1f}" stroke="{color}" '
            f'stroke-dasharray="4 3" stroke-width="1" />'
            f'<text x="{w - pad + 4}" y="{y + 4:.1f}" font-size="11" fill="{color}">{esc(lab)}</text>'
        )
    t0x, _ = xy(priz["t0_ts"], priz["t0_a"]) if priz.get("t0_ts") else (pad, 0)
    clear_ts = None
    for ts, px in (priz.get("yes_b") or []):
        if ts >= origin and px >= 0.80:
            clear_ts = ts
            break
    extra = ""
    if clear_ts:
        cx, _ = xy(clear_ts, 0.8)
        extra = (
            f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{pad}" y2="{h - pad}" stroke="#7c3aed" '
            f'stroke-dasharray="2 2" />'
            f'<text x="{cx + 4:.1f}" y="{pad + 10}" font-size="11" fill="#7c3aed">Dzumhur Yes ≥ 0.80</text>'
        )
    hours = []
    for hr in range(0, 6):
        ts = origin + hr * 3600
        if ts > tmax:
            break
        x, _ = xy(ts, 0)
        hours.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{h - pad}" y2="{h - pad + 6}" stroke="#94a3b8" />'
            f'<text x="{x:.1f}" y="{h - 8}" font-size="11" text-anchor="middle" fill="#64748b">{hr}h</text>'
        )
    return f"""
<svg viewBox="0 0 {w} {h}" width="100%" height="280" role="img" aria-label="Prizmic vs Dzumhur Yes path">
  <rect x="0" y="0" width="{w}" height="{h}" fill="#fff" />
  {''.join(guides)}
  <line x1="{t0x:.1f}" x2="{t0x:.1f}" y1="{pad}" y2="{h - pad}" stroke="#0f172a" stroke-dasharray="2 2" />
  {poly(a, "#2563eb")}
  {poly(b, "#dc2626")}
  {extra}
  {''.join(hours)}
  <text x="{pad}" y="16" font-size="12" fill="#2563eb">Prizmic Yes</text>
  <text x="{pad + 110}" y="16" font-size="12" fill="#dc2626">Dzumhur Yes</text>
</svg>
<p class="note">Blue is Dino Prizmic Yes. Red is Damir Dzumhur Yes. Dashed grey/orange/green are the 68.5 / 57.9 / 74.1 figures from the ask — our prints are the lines, not those guides. Purple is the first time Dzumhur Yes printed at 80 cents or more. Horizontal axis is hours after listed start.</p>
"""


def load_prior_ideas() -> dict:
    out = {}
    decade = RAW / "tennis_decade_at_start_20261020.json"
    ninety = RAW / "polymarket_tennis_no_90plus_20261020.json"
    jump = RAW / "pattern_tracking_20261020.json"
    roi = RAW / "odds_cross_no_roi_60_70_20261020.json"
    if decade.is_file():
        data = json.loads(decade.read_text(encoding="utf-8"))
        hy = {h["id"]: h for h in data.get("hypotheses") or []}
        out["t0_90"] = hy.get("A") or {}
        out["t2_4049"] = hy.get("B") or {}
    if ninety.is_file():
        data = json.loads(ninety.read_text(encoding="utf-8"))
        out["opener90_no"] = data.get("primary") or {}
        out["opener90_tight"] = data.get("tight") or {}
    if jump.is_file():
        data = json.loads(jump.read_text(encoding="utf-8"))
        out["jump"] = data.get("jump") or {}
    if roi.is_file():
        data = json.loads(roi.read_text(encoding="utf-8"))
        out["roi6070"] = data.get("primary") or {}
    return out


def prizmic_pairs(pairs: list[dict]) -> list[dict]:
    hits = []
    for p in pairs:
        blob = (p.get("game") or "") + " " + (p.get("side_a") or "") + " " + (p.get("side_b") or "")
        low = blob.lower()
        if "prizmic" in low and "dzumhur" in low:
            hits.append(p)
    return hits


def idea_dip_follow(pairs: list[dict]) -> dict:
    """Favorite dips ≥10¢ in-match: does that side still win? Follow vs fade."""
    by = defaultdict(list)
    for p in pairs:
        if not p.get("usable") or not p.get("good_book", True) or not p.get("settled"):
            continue
        if (p.get("fav_dip") or 0) < 0.10:
            continue
        fav = p.get("fav")
        won = p.get("winner") == fav
        by[p.get("sport") or "unknown"].append(won)
        by["all"].append(won)
    rows = []
    for sport, flags in sorted(by.items(), key=lambda kv: (0 if kv[0] == "all" else 1, kv[0])):
        n = len(flags)
        wins = sum(1 for x in flags if x)
        rows.append({
            "sport": sport,
            "n": n,
            "fav_wins_after_dip10": wins,
            "win_pct": pct(wins, n),
            "fade_no_would_win": n - wins,
            "fade_pct": pct(n - wins, n),
            "note": tiny_note(n),
        })
    return {"n": len(by.get("all") or []), "rows": rows}


def write_html(payload: dict) -> None:
    now = payload["written_at"]
    stream = payload["stream"]
    vol_rows = payload["vol_rows"]
    hedge_rows = payload["hedge_rows"]
    ideas = payload["ideas"]
    prior = payload["prior"]
    priz_list = payload["priz"]
    dip_follow = payload["dip_follow"]
    usable = payload["n_usable"]
    n_pairs = payload["n_pairs"]
    big = [r for r in vol_rows if int(r.get("n") or 0) >= 20]
    headline_sport = (big[0]["sport"] if big else (vol_rows[0]["sport"] if vol_rows else "n/a"))
    add2_05 = sum(int(r.get("n_add2_05") or 0) for r in hedge_rows)
    n_hedge = sum(int(r.get("n") or 0) for r in hedge_rows)

    priz_html = "<p class='note'>Prizmic vs Dzumhur was not on this tape.</p>"
    priz_tables = ""
    if priz_list:
        chunks = []
        for priz in priz_list:
            start_ts = int(to_et(priz["start_dt"]).timestamp()) if priz.get("start_dt") else priz.get("t0_ts")
            priz["start_ts"] = start_ts
            va, vb = priz.get("vol_a") or {}, priz.get("vol_b") or {}
            asked = {"t0": 0.685, "low": 0.579, "high": 0.741}
            priz_is_a = "prizmic" in (priz.get("side_a") or "").lower()
            our_t0 = priz.get("t0_a") if priz_is_a else priz.get("t0_b")
            our_vol = va if priz_is_a else vb
            priz_ticks = priz.get("yes_a") if priz_is_a else priz.get("yes_b")
            pre50 = []
            if start_ts:
                for ts, px in priz_ticks or []:
                    if ts <= start_ts:
                        continue
                    if px < 0.50:
                        break
                    pre50.append(px)
            pre50_min = min(pre50) if pre50 else None
            pre50_max = max(pre50) if pre50 else None
            snap = payload.get("snap_t0") or {}
            snap_row = snap.get((game_norm(priz["game"]), game_norm("Dino Prizmic"), priz["venue"]))
            path = downsample_path(
                ticks_between(priz["yes_a"] if "prizmic" in priz["side_a"].lower() else priz["yes_b"], (start_ts or 0) - 1, priz.get("end_ts") or 0),
                start_ts or priz.get("t0_ts") or 0,
            )
            path_rows = [{
                "minute": r["minute"],
                "min": fmt_px(r["min"]),
                "max": fmt_px(r["max"]),
                "last": fmt_px(r["last"]),
                "n": r["n"],
            } for r in path]
            first50 = mins_after(our_vol.get("t_first_50"), start_ts)
            chunks.append(f"""
<h3>{esc(priz['venue'])}</h3>
<p class="note">Listed start {esc(priz.get('start') or '')}. T0 label: {esc(priz.get('t0_label') or '')}.
T0 Yes Prizmic {fmt_px(our_t0)} (ask said 68.5¢). Before first print under 50¢ (the “lost the first set” cut): min {fmt_px(pre50_min)} (ask 57.9¢), max {fmt_px(pre50_max)} (ask 74.1¢).
Live in-match min/max until a 5¢/95¢ absorbing print: {fmt_px(our_vol.get('in_min'))} / {fmt_px(our_vol.get('in_max'))}, range {fmt_px(our_vol.get('range'))}.
Max dip below T0 {fmt_px(our_vol.get('max_dip'))}. First print under 50¢: {fmt_n(first50) or 'never in window'} minutes after start.
T0 pair cost C = {fmt_px(priz.get('c0'))}. Hold 1+1 P&amp;L if settled = {fmt_px((priz.get('hedge') or {}).get('hold_pnl'))}.
Official: {esc(priz.get('side_a'))} {esc(priz.get('off_a'))} / {esc(priz.get('side_b'))} {esc(priz.get('off_b'))}
({esc(priz.get('off_src_a') or priz.get('off_src_b') or 'pending')}).
Snapshot T0 file: {fmt_px((snap_row or {}).get('yes_price')) if snap_row else 'none'} at {esc((snap_row or {}).get('at') or '')} ({esc((snap_row or {}).get('source') or '')}).</p>
{svg_path(priz)}
<p class="note">Minute table is min/max/last Yes for Prizmic in that minute after start. Click headers to sort.</p>
{table(
    [("Minute after start", "num"), ("Min Yes", "num"), ("Max Yes", "num"), ("Last Yes", "num"), ("Price-change ticks", "num")],
    path_rows,
    ["minute", "min", "max", "last", "n"],
)}
""")
        priz_html = chunks[0] if chunks else priz_html
        priz_tables = "".join(chunks[1:])

    t0_90 = prior.get("t0_90") or {}
    t2 = prior.get("t2_4049") or {}
    jump = prior.get("jump") or {}
    roi = prior.get("roi6070") or {}
    opener90 = prior.get("opener90_no") or {}

    idea_rows = []
    for row in ideas:
        idea_rows.append(row)

    tennis = next((r for r in vol_rows if r["sport"] == "tennis"), {})
    nfl = next((r for r in vol_rows if r["sport"] == "pro football"), {})
    nhl = next((r for r in vol_rows if r["sport"] == "pro hockey"), {})

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>In-match volatility and both-Yes hedge 2026-10-21</title>
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
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>In-match price swings and the both-Yes-then-hedge idea</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Short October 2026 live tape — no in-sample / out-of-sample split, no KEEP.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
<p>Worked $1.15 example: you buy one Yes on each player for $0.685 and $0.465. You spent $1.15. Settlement pays $1 to the winning Yes and $0 to the loser, so you lose $0.15 if you stand pat. To lock +$0.05 you need the worse of the two outcomes to return at least $1.20 after every ticket you bought. Extra Yes on the dipped player pays $2 if he comes back and still $1 if he loses — worst case is now $1 minus a bigger bill. Extra No on the risen player pairs with the Yes you already hold and pays $1 on that name in both worlds, but the leftover Yes still only pays in one world: worst case is $1 minus $1.15 minus the No price, which is a bigger loss. You cannot lock +$0.05 after buying both Yes unless you trade out of a position at a better price (sell the leftover Yes, or buy a later Yes+No pair so cheap it covers the vig). Our venues encode a buy of No / Polymarket BUY_SHORT, not a free sell at the Yes ask.</p>
</div>

<div class="hl">
<p><strong>Volatility ranking (median in-match Yes range, two-sided moneylines):</strong> among sports with N≥20, widest is {esc(headline_sport)} (tennis {esc(tennis.get('median_range') or 'n/a')}, N {tennis.get('n') or 0}). Pro football (NFL) {esc(nfl.get('median_range') or 'n/a')} (N {nfl.get('n') or 0}). Pro hockey (NHL) {esc(nhl.get('median_range') or 'n/a')} (N {nhl.get('n') or 0}, tiny). College football printed a wider median on this tape but N is tiny — see the table. Do not read a tiny-N sport as a law.</p>
<p><strong>Does the opening favorite print lower at some point?</strong> Share of matches where the T0 favorite later printed at least 5 / 10 / 15 cents below T0 is in the sport table. A dip is common. A dip that is deep enough to lock a profit after buying both sides first is not.</p>
<p><strong>Both-Yes then hedge for +0.05 / +0.10 / +0.25:</strong> a one-contract add never locks both outcomes (floor stays $1, cost rises). The only two-contract add that pays in both worlds is buying a later Yes and No on the <em>same</em> player, which needs that later pair to be cheap enough to cover the opening vig. Matches where that +0.05 lock ever printed: {add2_05} of {n_hedge}. Optimal cash-in among 0.05 / 0.10 / 0.25 is not a choice we can take — those locks almost never appear after paying vig first. The clean version is: do not buy both at T0; wait until two Yes (or Yes+No on one name) sum to $0.95 or less.</p>
<p>National Football League (NFL), National Hockey League (NHL), National Collegiate Athletic Association football (NCAAF / college football). ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. SMA is Simple Moving Average (not used here).</p>
</div>

<div class="warn">
<p><strong>Hold 1+1 to the end is always a loss when C &gt; 1.</strong> P&amp;L = $1 − C. That is labeled in the hedge table as median/mean hold P&amp;L. It is not a maybe.</p>
<p>Fills at the printed ask are optimistic (we may not get that size). Short sample ~17–21 Oct 2026. No KEEP. Not gold. Not DailyRun.</p>
</div>

<h2>Freeze</h2>
<ul>
<li>Universe: two-sided moneyline (exactly two named Yes sides on the same game and venue). Spreads and totals left out.</li>
<li>T0: last Yes at or before listed start for both sides. If that is missing, first two-sided in-game print, labeled. Odds-snapshot T0 is shown for Prizmic as a cross-check, not as the study T0.</li>
<li>In-match window for range/dip: after listed start (or after in-game T0) through start plus a typical length (tennis 360 minutes; NFL 210; NHL 200; college football 240). Stops before the first 5¢ or 95¢ print so settlement 1¢ ticks are not the “range.” Hedge search still uses the full window. Exact $0 and $1 empty-book prints skipped. Two Yes summing under $0.90 or over $1.15 are dropped from the sport ranking (broken or one-sided books).</li>
<li>Hedge: BUY only, 1-contract steps, at printed Yes or No ask. No assumed sell at the Yes bid.</li>
<li>P&amp;L uses official venue settlement when both sides (or a same-game fallback) resolve. Pending games are excluded from P&amp;L means.</li>
<li>Tape: <code>raw/price_memory.jsonl</code>. Yes/No change-ticks {stream.get('n_hits') or 0:,} of {stream.get('n_lines') or 0:,} lines. First quote {esc(stream.get('seen_min') or '')}. Last quote {esc(stream.get('seen_max') or '')}. Two-sided pairs {n_pairs}. Live in-match ticks (usable) {usable}.</li>
</ul>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>

<h2>1. In-match range by sport</h2>
<p class="note">Range is in-match max Yes minus min Yes, averaged across the two sides. Favorite dip is T0 Yes minus later in-match low, for the T0 favorite only. Time to first dip / first print under 50¢ is minutes after listed start (or after in-game T0). Tiny N labeled. Upcoming games with no live ticks are not in this table.</p>
{table(
    [("Sport", "text"), ("N matches", "num"), ("Median range", "num"), ("Mean range", "num"),
     ("Median fav dip", "num"), ("Mean fav dip", "num"),
     ("% fav ever below T0", "num"), ("% dip ≥5¢", "num"), ("% dip ≥10¢", "num"), ("% dip ≥15¢", "num"),
     ("N ever below", "num"), ("N dip5", "num"), ("N dip10", "num"), ("N dip15", "num"),
     ("Median min to first dip", "num"), ("Median min to &lt;50¢", "num"), ("N that crossed 50", "num"),
     ("Note", "text")],
    vol_rows,
    ["sport", "n", "median_range", "mean_range", "median_fav_dip", "mean_fav_dip",
     "pct_ever_below", "pct_dip5", "pct_dip10", "pct_dip15",
     "n_ever_below", "n_dip5", "n_dip10", "n_dip15",
     "median_t_dip", "median_t_50", "n_cross50", "note"],
)}

<h2>2. Prizmic vs Dzumhur — our prints vs the 68.5 / 57.9 / 74.1 story</h2>
<p class="note">These are stored Yes asks, not reconstructed from memory of the match. The ask’s 68.5 / 57.9 / 74.1 are drawn as dashed guides; if our line never tags those numbers, we did not print them.</p>
{priz_html}
{priz_tables}

<h2>3. Both-Yes then hedge — what can actually lock</h2>
<p class="note">C is T0 Yes A + T0 Yes B. Hold P&amp;L is $1 − C on settled matches (always a loss when C &gt; 1). Add-1 lock % is the share of matches where some later 1-contract Yes or No made min(payout A, payout B) − total cost ≥ target. That should be ~0: the floor stays $1. Add-2 lock is extra Yes and No on the same player later, which pays $2 in both worlds and needs that later pair to be cheap enough to cover opening vig. Offset is the first time T0 Yes X + later No X ≤ $0.95; leftover Yes remains, so the two P&amp;Ls are not both profits. Risen-No is the first No ask on a side that has risen vs T0. Two-Yes ≤0.95 is the clean lock <em>without</em> having bought both at T0. Buy-dog-wait-fav is: buy the T0 underdog only, then wait until the favorite Yes is cheap enough that those two Yes sum ≤ $0.95. Buy-fav-wait-dog is the blowout version (buy favorite at T0, wait until the dog Yes is leftover-cheap).</p>
{table(
    [("Sport", "text"), ("N", "num"), ("Settled N", "num"), ("Median C", "num"),
     ("Median hold P&amp;L", "num"), ("Mean hold P&amp;L", "num"),
     ("% already ≤0.95 at T0", "num"),
     ("% add-1 +0.05", "num"), ("% add-2 +0.05", "num"), ("N add-2 +0.05", "num"), ("Median min to add-2 +0.05", "num"),
     ("Mean take +0.05", "num"), ("Mean hold (same rows)", "num"),
     ("% add-1 +0.10", "num"), ("% add-2 +0.10", "num"), ("N add-2 +0.10", "num"), ("Median min to add-2 +0.10", "num"),
     ("% add-1 +0.25", "num"), ("% add-2 +0.25", "num"), ("N add-2 +0.25", "num"),
     ("% offset cheap No", "num"), ("% risen-No print", "num"),
     ("% in-match two Yes ≤0.95", "num"), ("% same-player Yes+No ≤0.95 later", "num"),
     ("% buy dog wait fav lock", "num"), ("% buy fav wait dog lock", "num"),
     ("Note", "text")],
    hedge_rows,
    ["sport", "n", "n_settled", "median_c0", "median_hold", "mean_hold", "pct_already_lock",
     "pct_add1_05", "pct_add2_05", "n_add2_05", "med_t_add2_05", "mean_take_05", "mean_hold_05",
     "pct_add1_10", "pct_add2_10", "n_add2_10", "med_t_add2_10",
     "pct_add1_25", "pct_add2_25", "n_add2_25",
     "pct_offset", "pct_risen_no", "pct_two_yes", "pct_same_player", "pct_dog_wait", "pct_fav_wait",
     "note"],
)}

<h3>Offset lock — two outcome P&amp;Ls (not a two-way profit)</h3>
<p class="note">First time we could buy No on player X so T0 Yes X + that No ≤ $0.95. If X wins: payout $1 (Yes X + No X), leftover Yes loses, P&amp;L = 1 − C − n. If the other player wins: $2, P&amp;L = 2 − C − n. Worst case is the first number. Shown only when that No printed. Cap 80 rows.</p>
{table(
    [("Sport", "text"), ("Match", "text"), ("Venue", "text"), ("No on", "text"),
     ("C", "num"), ("No ask", "num"), ("Same-player cost", "num"),
     ("P&amp;L if that player wins", "num"), ("P&amp;L if other wins", "num"),
     ("Worst", "num"), ("Minutes after T0", "num")],
    payload.get("offset_rows") or [],
    ["sport", "game", "venue", "player", "c0", "n", "same_player_cost",
     "pnl_if_that_player_wins", "pnl_if_other_wins", "worst", "mins"],
)}

<h2>4. Other trackable ideas (from this tape, not vibes)</h2>
<p class="note">Each idea keeps the current settled N. HOLD until N is large. Not a send rule.</p>
{table(
    [("Id", "text"), ("Idea", "text"), ("What it is", "text"), ("Universal vs per sport", "text"),
     ("Current N", "num"), ("What the tape says now", "text"), ("Verdict", "text")],
    idea_rows,
    ["id", "name", "definition", "scope", "n", "result", "verdict"],
)}

<h3>Favorite dips ≥10¢ then win? Follow vs fade</h3>
<p class="note">Among two-sided matches where the T0 favorite later printed at least 10 cents below T0 and we have an official winner: did that favorite still win? If yes-rate is high, buying No on the dip (fade) is the expensive side. If yes-rate is low, the dip was information. Tiny N labeled.</p>
{table(
    [("Sport", "text"), ("Settled N with ≥10¢ dip", "num"), ("Favorite still won", "num"),
     ("Win %", "num"), ("Fade-No would have won", "num"), ("Fade %", "num"), ("Note", "text")],
    dip_follow.get("rows") or [],
    ["sport", "n", "fav_wins_after_dip10", "win_pct", "fade_no_would_win", "fade_pct", "note"],
)}

<h2>5. Widest in-match ranges (cap 80)</h2>
{table(
    [("Sport", "text"), ("Match", "text"), ("Venue", "text"), ("T0 label", "text"),
     ("Favorite", "text"), ("T0 fav", "num"), ("T0 dog", "num"), ("C", "num"),
     ("Fav in-min", "num"), ("Fav in-max", "num"), ("Fav range", "num"), ("Fav dip", "num"),
     ("Ever below T0", "text"), ("Official fav", "text")],
    payload.get("wide_rows") or [],
    ["sport", "game", "venue", "t0_label", "fav_side", "t0_fav", "t0_dog", "c0",
     "in_min", "in_max", "range", "dip", "ever_below", "official"],
)}

<h2>How to read this</h2>
<ul>
<li>Volatility is real, especially tennis on this tape. A T0 favorite printing a few cents lower is common, not rare.</li>
<li>Buying both Yes at the open pays the vig up front. The “inevitable dip” does not refund that vig.</li>
<li>0.05 vs 0.10 vs 0.25 is the wrong knob after 1+1: the floor payout is $1. The 0.05 that already exists on this desk is “both asks ≤ $0.95 <em>before</em> you buy.”</li>
<li>Prior studies cited: 40–49 at T−2h HOLD (settled N {t2.get('settled') or 0}, win % {esc(t2.get('win_pct') or 'n/a')}); ≥90 at T0 HOLD (settled N {t0_90.get('settled') or 0}, win % {esc(t0_90.get('win_pct') or 'n/a')} so fade-No is likely the expensive side); in-game 60→70 give-back on the jump tracker settled N {jump.get('n_settled') or 0}, keep % {esc(jump.get('keep_pct') or 'n/a')}; 60→70 No-ROI companion settled N {roi.get('n') or 0}. Opener-90 No (first print, not T0) is a different, weaker test — opener Yes 90+ No-ROI settled N {opener90.get('n') or 0}.</li>
</ul>
<p class="note">Acronyms: NFL is National Football League. NHL is National Hockey League. NCAAF is National Collegiate Athletic Association football. ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. T0 is match start. T−2h is two hours before listed start. Vig is the overround in two Yes prices summing over $1. IOC is immediate-or-cancel (not used on this page).</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def build_ideas(pairs: list[dict], hedge_rows: list[dict], vol_rows: list[dict], prior: dict, dip_follow: dict) -> list[dict]:
    tennis = next((r for r in vol_rows if r["sport"] == "tennis"), {})
    nfl = next((r for r in vol_rows if r["sport"] == "pro football"), {})
    nhl = next((r for r in vol_rows if r["sport"] == "pro hockey"), {})
    t2 = prior.get("t2_4049") or {}
    t0_90 = prior.get("t0_90") or {}
    jump = prior.get("jump") or {}
    roi = prior.get("roi6070") or {}
    n_two = 0
    n_use = 0
    n_dog = 0
    n_favw = 0
    n_same = 0
    for p in pairs:
        if not p.get("usable") or not p.get("good_book", True):
            continue
        n_use += 1
        h = p.get("hedge") or {}
        if h.get("two_yes_095"):
            n_two += 1
        if h.get("buy_dog_wait_fav"):
            n_dog += 1
        if h.get("buy_fav_wait_dog"):
            n_favw += 1
        if h.get("same_player_cheap_after"):
            n_same += 1
    dip_all = next((r for r in (dip_follow.get("rows") or []) if r.get("sport") == "all"), {})
    return [
        {
            "id": "1",
            "name": "Wait for two-sided sum ≤ $0.95 (current lock)",
            "definition": "Do not buy both Yes at T0. Buy Yes A and Yes B only when those two live asks sum to $0.95 or less (or Yes+No on one name). That is a locked $1 payout for ≤ $0.95 spent.",
            "scope": "Universal construction; how often it prints is per sport (tennis swings more, so leftover-cheap is more common than NFL).",
            "n": n_use,
            "result": f"In-match two Yes ≤0.95 on {n_two} / {n_use} usable matches ({pct(n_two, n_use) or 'n/a'}%). Same-player Yes+No ≤0.95 later on {n_same} / {n_use}. This is the clean version of the hedge without paying vig first.",
            "verdict": "HOLD — already the live lock rule; this page does not wire sends.",
        },
        {
            "id": "2",
            "name": "40–49 at T−2h (existing HOLD)",
            "definition": "Polymarket tennis moneyline Yes in 40–49 two hours before listed start. Follow that same player; not a both-Yes hedge.",
            "scope": "Tennis / Polymarket. Not universal.",
            "n": t2.get("settled") or 0,
            "result": f"Win % {t2.get('win_pct') or 'n/a'} on settled N {t2.get('settled') or 0}. {t2.get('note') or 'HOLD'}.",
            "verdict": "HOLD",
        },
        {
            "id": "3",
            "name": "≥90 at T0 fade-No is likely the expensive side",
            "definition": "Polymarket tennis favorite in 90–99 at match start. Buying No fades a side that has been winning about 98% on this tape.",
            "scope": "Tennis / Polymarket T0. Opener-90 (first print) is a weaker, different test and is not this row.",
            "n": t0_90.get("settled") or 0,
            "result": f"Yes win % {t0_90.get('win_pct') or 'n/a'} on settled N {t0_90.get('settled') or 0}. Fade-No would have lost that often.",
            "verdict": "HOLD — do not treat fade-No of 90+ T0 as a plus-EV default.",
        },
        {
            "id": "4",
            "name": "In-game 60→70 give-back vs No-ROI",
            "definition": "Side prints under 60¢ then first print over 70¢, 15–60 minutes after start. Jump tracker: did that side keep the win? Companion: buy No at that 70¢ print.",
            "scope": "Per sport in the parent cross study; tennis-heavy on the jump tracker.",
            "n": jump.get("n_settled") or roi.get("n") or 0,
            "result": f"Jump keep % {jump.get('keep_pct') or 'n/a'} (gave back {jump.get('give_back_pct') or 'n/a'}) settled N {jump.get('n_settled') or 0}. 60→70 No-ROI mean {fmt_n((roi.get('avg_roi_pct')), 1) or 'n/a'}% on settled N {roi.get('n') or 0}, median ROI −100% (most No tickets die). {jump.get('note') or roi.get('note') or ''}",
            "verdict": "HOLD — small sample, median No loses.",
        },
        {
            "id": "5",
            "name": "Buy T0 underdog, wait for favorite to dip into a two-Yes lock",
            "definition": "Buy only the cheaper T0 Yes. If the favorite later prints cheap enough that T0 dog + later fav ≤ $0.95, buy the favorite and lock. This is the user’s dip story without paying vig on both sides first. Needs a deep favorite dip, not a 5¢ wiggle.",
            "scope": "More plausible in tennis (wider range) than NFL/NHL on this tape.",
            "n": n_use,
            "result": f"Lock ever appeared on {n_dog} / {n_use} ({pct(n_dog, n_use) or 'n/a'}%). Tennis median range {tennis.get('median_range') or 'n/a'} vs NFL {nfl.get('median_range') or 'n/a'} vs NHL {nhl.get('median_range') or 'n/a'}.",
            "verdict": "HOLD — track; do not send.",
        },
        {
            "id": "6",
            "name": "Buy T0 favorite, wait for dog Yes leftover-cheap (blowout lock)",
            "definition": "Opposite of the dip story: favorite is winning, dog Yes collapses, T0 fav + later dog ≤ $0.95. You already own the favorite; the cheap dog is the leftover lock. Same math as the live one-leg leftover, except T0 fav was bought at the ask, not after a lock fill.",
            "scope": "Universal math; frequency per sport.",
            "n": n_use,
            "result": f"Lock ever appeared on {n_favw} / {n_use} ({pct(n_favw, n_use) or 'n/a'}%). Favorite still won after a ≥10¢ dip in {dip_all.get('win_pct') or 'n/a'}% of settled dip matches (N {dip_all.get('n') or 0}).",
            "verdict": "HOLD — related to leftover watch, not a new send.",
        },
    ]


def wide_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        if not p.get("usable") or p.get("range_max") is None:
            continue
        vf = p.get("vol_fav") or {}
        fav = p.get("fav")
        off = p.get("off_a") if fav == "a" else p.get("off_b")
        rows.append({
            "sport": p.get("sport") or "",
            "game": p.get("game") or "",
            "venue": p.get("venue") or "",
            "t0_label": p.get("t0_label") or "",
            "fav_side": p.get("fav_side") or "",
            "t0_fav": fmt_px(p.get("t0_fav")),
            "t0_dog": fmt_px(p.get("t0_dog")),
            "c0": fmt_px(p.get("c0")),
            "in_min": fmt_px(vf.get("in_min")),
            "in_max": fmt_px(vf.get("in_max")),
            "range": fmt_px(vf.get("range")),
            "dip": fmt_px(p.get("fav_dip")),
            "ever_below": "yes" if p.get("fav_ever_below") else "no",
            "official": off or "",
            "_range": vf.get("range") or 0,
        })
    rows.sort(key=lambda r: -r["_range"])
    return rows[:80]


def offset_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        h = (p.get("hedge") or {}).get("offset")
        if not h:
            continue
        rows.append({
            "sport": p.get("sport") or "",
            "game": p.get("game") or "",
            "venue": p.get("venue") or "",
            "player": h.get("player") or "",
            "c0": fmt_px(p.get("c0")),
            "n": fmt_px(h.get("n")),
            "same_player_cost": fmt_px(h.get("same_player_cost")),
            "pnl_if_that_player_wins": fmt_px(h.get("pnl_if_that_player_wins")),
            "pnl_if_other_wins": fmt_px(h.get("pnl_if_other_wins")),
            "worst": fmt_px(h.get("worst")),
            "mins": fmt_n(h.get("mins")),
        })
    rows.sort(key=lambda r: r.get("game") or "")
    return rows[:80]


def json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [json_safe(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def main() -> None:
    print("loading settlements and catalog", flush=True)
    catalog = load_catalog()
    settlements = load_settlements()
    start_lookup = start_lookup_from(settlements, catalog)
    stream = stream_moneylines()
    pairs = pair_matches(stream["series"], start_lookup)
    analyze_vol(pairs)
    attach_pair_results(pairs, settlements)
    n_usable = 0
    for p in pairs:
        if p.get("usable"):
            p["hedge"] = hedge_search(p)
            n_usable += 1
        else:
            p["hedge"] = hedge_search(p)
    print(f"usable T0 pairs {n_usable}", flush=True)
    vol_rows = sport_vol_rows(pairs)
    hedge_rows = hedge_sport_rows(pairs)
    prior = load_prior_ideas()
    dip = idea_dip_follow(pairs)
    ideas = build_ideas(pairs, hedge_rows, vol_rows, prior, dip)
    priz = prizmic_pairs(pairs)
    snap_t0 = load_snapshot_t0()
    now = iso_now()
    payload = {
        "written_at": now,
        "stream": {
            "n_lines": stream["n_lines"],
            "n_hits": stream["n_hits"],
            "seen_min": stream["seen_min"],
            "seen_max": stream["seen_max"],
            "n_series": len(stream["series"]),
        },
        "n_pairs": len(pairs),
        "n_usable": n_usable,
        "vol_rows": vol_rows,
        "hedge_rows": hedge_rows,
        "ideas": ideas,
        "prior": prior,
        "dip_follow": dip,
        "priz": priz,
        "snap_t0": snap_t0,
        "offset_rows": offset_rows(pairs),
        "wide_rows": wide_rows(pairs),
        "research_only": True,
        "not_gold": True,
        "not_dailrun": True,
    }
    # HTML needs live pair objects for Prizmic charts; JSON gets summaries only
    write_html(payload)
    slim_priz = []
    for p in priz:
        slim_priz.append({
            "sport": p.get("sport"),
            "game": p.get("game"),
            "venue": p.get("venue"),
            "side_a": p.get("side_a"),
            "side_b": p.get("side_b"),
            "t0_label": p.get("t0_label"),
            "t0_a": p.get("t0_a"),
            "t0_b": p.get("t0_b"),
            "c0": p.get("c0"),
            "start": p.get("start"),
            "fav_side": p.get("fav_side"),
            "vol_a": p.get("vol_a"),
            "vol_b": p.get("vol_b"),
            "off_a": p.get("off_a"),
            "off_b": p.get("off_b"),
            "winner": p.get("winner"),
            "hedge": {k: v for k, v in (p.get("hedge") or {}).items() if k != "n_times"} | {"n_times": (p.get("hedge") or {}).get("n_times")},
        })
    JSON_OUT.write_text(json.dumps(json_safe({
        "written_at": now,
        "asked": ASKED,
        "stream": payload["stream"],
        "n_pairs": len(pairs),
        "n_usable": n_usable,
        "vol_rows": vol_rows,
        "hedge_rows": hedge_rows,
        "ideas": ideas,
        "dip_follow": dip,
        "priz": slim_priz,
        "note": "Research only. Not gold. Not DailyRun. No KEEP. Short Oct 2026 tape.",
    }), indent=2, default=str), encoding="utf-8")
    print(f"wrote {JSON_OUT}", flush=True)
    copy_g(PAGE)
    print("done", flush=True)


if __name__ == "__main__":
    main()
