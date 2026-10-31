"""Live tennis Yes-ask tape: minutes from listed T0 until cheapest both-Yes after-fee <= 1.05.

Does not sell. Does not start live_strategy_b.py. HOLD C_HI=1.05 and D=0.25.
Kalshi hist is T0-only; this uses price_memory tennis.jsonl (live tape).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_strategy_b  # noqa: E402
from prediction_paths import RAW_DIR as RAW, DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
C_HI = Decimal("1.05")
HORIZON_MIN = 90
LEAD_SEC = 15
NOVIG_COEF = Decimal("0.06")
OUT = STAMP / "b_t0_window_and_cheapest_across_20261031.json"
POD_WHEN = "2026-10-30T20:00:40"
VENUE_MAP = {
    "kalshi": "kalshi",
    "gemini": "gemini",
    "polymarket": "polymarket",
    "polymarket us": "polymarket",
    "novig": "novig",
}


def parse_et(text: str) -> datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def scheduled(dt: datetime | None) -> bool:
    return dt is not None and dt.second == 0 and dt.microsecond == 0


def venue_of(row: dict) -> str:
    return VENUE_MAP.get(str(row.get("venue") or "").strip().lower(), "")


def spec_for(venue: str, player: str, pay: Decimal) -> dict:
    spec = {"venue": venue, "player": player, "pay": pay, "instrument": f"{venue}-{player}"}
    if venue == "novig":
        spec["fee_coefficient"] = str(NOVIG_COEF)
        spec["fee_charged"] = "ALWAYS"
        spec["event_status"] = "OPEN_INGAME"
    if venue == "polymarket":
        spec["fee_coefficient"] = str(live_strategy_b.POLY_T0_THETA)
        spec["intent"] = "ORDER_INTENT_BUY_LONG"
    return spec


def cheapest_pair(quotes: dict[tuple[str, str], tuple[Decimal, str]]) -> dict | None:
    """Min Yes ask per player across shops, then after-fee sum. No C_HI gate."""
    best: dict[str, dict] = {}
    for (pid, venue), (pay, name) in quotes.items():
        if not pid or venue not in live_strategy_b.VENUE_ORDER:
            continue
        if not live_strategy_b.in_yes_band(pay) or live_strategy_b.is_absorbing(pay):
            continue
        spec = spec_for(venue, name or pid, pay)
        if live_strategy_b.t0_leg_fee(spec, pay) is None:
            continue
        prev = best.get(pid)
        prev_pay = live_strategy_b._dec(prev.get("pay")) if prev else None
        take = prev is None or (prev_pay is not None and pay < prev_pay)
        if not take and prev_pay == pay:
            prev_v = str((prev or {}).get("venue") or "")
            if prev_v in live_strategy_b.VENUE_ORDER and venue in live_strategy_b.VENUE_ORDER:
                take = live_strategy_b.VENUE_ORDER.index(venue) < live_strategy_b.VENUE_ORDER.index(prev_v)
        if take:
            best[pid] = spec
    if len(best) < 2:
        return None
    ids = list(best.keys())[:2]
    a, b = best[ids[0]], best[ids[1]]
    pa = live_strategy_b._dec(a.get("pay"))
    pb = live_strategy_b._dec(b.get("pay"))
    all_in = live_strategy_b.t0_all_in_from_asks(a, pa, b, pb)
    same = str(a.get("venue") or "") == str(b.get("venue") or "")
    return {
        "ids": ids,
        "a": a,
        "b": b,
        "c": all_in,
        "same_shop": same,
        "venues": f"{a.get('venue')}+{b.get('venue')}",
    }


def shop_snapshot(quotes: dict[tuple[str, str], tuple[Decimal, str]]) -> list[dict]:
    by_venue: dict[str, list] = defaultdict(list)
    for (pid, venue), (pay, name) in quotes.items():
        by_venue[venue].append({"player": name or pid, "pay": pay, "venue": venue, **spec_for(venue, name or pid, pay)})
    books = []
    for venue, players in by_venue.items():
        books.append({"venue": venue, "title": "snapshot", "players": players})
    return books


def tennis_files() -> list[Path]:
    root = RAW / "price_memory"
    out = []
    for day in sorted(root.glob("2026-10-2*/tennis.jsonl")) + sorted(root.glob("2026-10-3*/tennis.jsonl")):
        if day.name == "tennis.jsonl":
            out.append(day)
    # 21–31 Oct 2026
    keep = []
    for path in sorted(root.glob("*/tennis.jsonl")):
        day = path.parent.name
        if "2026-10-21" <= day <= "2026-10-31":
            keep.append(path)
    return keep


def pass_starts(paths: list[Path]) -> dict[str, dict]:
    games: dict[str, dict] = {}
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if '"moneyline"' not in line or '"yes"' not in line.lower():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if str(row.get("market_type") or "") != "moneyline":
                    continue
                if str(row.get("pay") or "").lower() != "yes":
                    continue
                if not venue_of(row):
                    continue
                game = str(row.get("game") or "").strip()
                if not game:
                    continue
                bag = games.setdefault(
                    game,
                    {"starts": set(), "odd_starts": set(), "n_ticks": 0},
                )
                bag["n_ticks"] += 1
                start = parse_et(row.get("game_start") or "")
                if start is None:
                    continue
                key = start.isoformat()
                if scheduled(start):
                    bag["starts"].add(key)
                else:
                    bag["odd_starts"].add(key)
    return games


def choose_t0(bag: dict) -> datetime | None:
    starts = [parse_et(x) for x in bag.get("starts") or []]
    starts = [x for x in starts if x is not None]
    if not starts:
        return None
    return max(starts)


def pass_samples(paths: list[Path], games_meta: dict[str, dict]) -> dict[str, dict]:
    windows = {}
    for game, bag in games_meta.items():
        t0 = choose_t0(bag)
        if t0 is None:
            continue
        windows[game] = {
            "t0": t0,
            "t0_iso": t0.isoformat(),
            "lo": t0 - timedelta(seconds=LEAD_SEC),
            "hi": t0 + timedelta(minutes=HORIZON_MIN),
            "quotes": {},
            "samples": [],
            "last_sec": -999,
            "n_after": 0,
            "absorb_sec": None,
            "pre_t0_during": False,
        }
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if '"moneyline"' not in line or '"yes"' not in line.lower():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if str(row.get("market_type") or "") != "moneyline":
                    continue
                if str(row.get("pay") or "").lower() != "yes":
                    continue
                venue = venue_of(row)
                if not venue:
                    continue
                game = str(row.get("game") or "").strip()
                state = windows.get(game)
                if state is None:
                    continue
                seen = parse_et(row.get("seen_at") or "")
                if seen is None or seen > state["hi"]:
                    continue
                pay = live_strategy_b._dec(row.get("price"))
                if pay is None:
                    continue
                pid = live_strategy_b._player_id(str(row.get("side") or row.get("side_key") or ""))
                name = str(row.get("side") or "")
                if not pid:
                    continue
                state["quotes"][(pid, venue)] = (pay, name)
                if seen < state["lo"]:
                    if str(row.get("phase") or "") == "during":
                        state["pre_t0_during"] = True
                    continue
                sec = (seen - state["t0"]).total_seconds()
                if live_strategy_b.is_absorbing(pay) and state["absorb_sec"] is None and sec >= 0:
                    state["absorb_sec"] = sec
                if not state.get("sampled_t0") and seen >= state["t0"]:
                    pair0 = cheapest_pair(state["quotes"])
                    if pair0 is not None and pair0.get("c") is not None:
                        state["samples"].append(
                            {
                                "sec": 0.0,
                                "c": str(pair0["c"]),
                                "venues": pair0["venues"],
                                "same_shop": pair0["same_shop"],
                                "a_px": str(pair0["a"].get("pay")),
                                "b_px": str(pair0["b"].get("pay")),
                                "a_venue": pair0["a"].get("venue"),
                                "b_venue": pair0["b"].get("venue"),
                                "a_player": pair0["a"].get("player"),
                                "b_player": pair0["b"].get("player"),
                            }
                        )
                        state["last_sec"] = 0.0
                        state["n_after"] += 1
                    state["sampled_t0"] = True
                if sec - state["last_sec"] < 10 and state["samples"]:
                    continue
                pair = cheapest_pair(state["quotes"])
                if pair is None or pair.get("c") is None:
                    continue
                state["last_sec"] = sec
                state["n_after"] += 1
                state["samples"].append(
                    {
                        "sec": round(sec, 1),
                        "c": str(pair["c"]),
                        "venues": pair["venues"],
                        "same_shop": pair["same_shop"],
                        "a_px": str(pair["a"].get("pay")),
                        "b_px": str(pair["b"].get("pay")),
                        "a_venue": pair["a"].get("venue"),
                        "b_venue": pair["b"].get("venue"),
                        "a_player": pair["a"].get("player"),
                        "b_player": pair["b"].get("player"),
                    }
                )
    return windows


def hit_and_stay(samples: list[dict]) -> tuple[float | None, float | None]:
    """Minutes from T0 until first C<=1.05, and until it stays <=1.05 (never back above)."""
    if not samples:
        return None, None
    first = None
    last_above = None
    for row in samples:
        sec = float(row["sec"])
        if sec < 0:
            continue
        c = Decimal(row["c"])
        if c <= C_HI:
            if first is None:
                first = sec / 60.0
        else:
            last_above = sec / 60.0
    if first is None:
        return None, None
    stay = first
    if last_above is not None and last_above > first:
        # first sample after last_above that is <= 1.05
        stay = None
        for row in samples:
            sec = float(row["sec"])
            if sec < 0:
                continue
            mins = sec / 60.0
            if mins < last_above:
                continue
            if Decimal(row["c"]) <= C_HI:
                stay = mins
                break
    return first, stay


def bucket(mins: float | None) -> str:
    if mins is None:
        return "never"
    if mins <= 0:
        return "at T0 (0)"
    edges = [1, 2, 5, 10, 15, 20, 30, 45, 60, 90]
    lo = 0
    for hi in edges:
        if mins <= hi:
            return f"{lo}–{hi} min"
        lo = hi
    return ">90 min"


def percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    xs = sorted(values)

    def p(q: float) -> float:
        if len(xs) == 1:
            return round(xs[0], 2)
        i = (len(xs) - 1) * q
        lo = int(i)
        hi = min(lo + 1, len(xs) - 1)
        frac = i - lo
        return round(xs[lo] * (1 - frac) + xs[hi] * frac, 2)

    return {
        "n": len(xs),
        "p25": p(0.25),
        "p50": p(0.50),
        "p75": p(0.75),
        "p90": p(0.90),
        "p95": p(0.95),
        "max": round(xs[-1], 2),
        "min": round(xs[0], 2),
    }


def still_le(samples: list[dict], at_min: float) -> bool | None:
    hit = None
    for row in samples:
        sec = float(row["sec"])
        if sec < 0:
            continue
        mins = sec / 60.0
        if mins > at_min + 0.75:
            break
        if mins >= at_min - 0.75:
            hit = Decimal(row["c"]) <= C_HI
    return hit


def podoroska_snapshot(path: Path) -> dict:
    quotes: dict[tuple[str, str], tuple[Decimal, str, str]] = {}
    ticks = []
    lo = "2026-10-30T19:50:00"
    hi = "2026-10-30T20:06:00"
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if "podoro" not in line.lower() and "monnet" not in line.lower():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if str(row.get("market_type") or "") != "moneyline":
                continue
            if str(row.get("pay") or "").lower() != "yes":
                continue
            venue = venue_of(row)
            if not venue:
                continue
            seen = str(row.get("seen_at") or "")
            if seen < lo or seen > hi:
                continue
            pay = live_strategy_b._dec(row.get("price"))
            if pay is None:
                continue
            name = str(row.get("side") or "")
            pid = live_strategy_b._player_id(name)
            ticks.append(
                {
                    "seen": seen,
                    "venue": venue,
                    "player": name,
                    "pid": pid,
                    "pay": str(pay),
                    "game": row.get("game"),
                    "game_start": row.get("game_start"),
                }
            )
            if seen <= "2026-10-30T20:00:40.999":
                quotes[(pid, venue)] = (pay, name, seen)
    slim = {(k[0], k[1]): (v[0], v[1]) for k, v in quotes.items()}
    pair = cheapest_pair(slim)
    books = []
    by_venue: dict[str, dict[str, dict]] = defaultdict(dict)
    for (pid, venue), (pay, name, seen) in quotes.items():
        by_venue[venue][pid] = spec_for(venue, name, pay) | {"seen": seen}
    for venue, players in by_venue.items():
        books.append(
            {
                "venue": venue,
                "title": "Podoroska vs Monnet",
                "players": list(players.values()),
            }
        )
    picked = live_strategy_b.pick_cheapest_legs(books)
    picked_out = None
    if picked is not None:
        picked_out = {
            "venue": picked.get("venue"),
            "shop_pick": picked.get("shop_pick"),
            "players": [
                {"player": r.get("player"), "venue": r.get("venue"), "pay": str(r.get("pay"))}
                for r in (picked.get("players") or [])
            ],
        }
    same_shop_c = {}
    for venue, players in by_venue.items():
        if len(players) < 2:
            continue
        rows = list(players.values())
        c = live_strategy_b.t0_all_in_from_asks(
            rows[0], live_strategy_b._dec(rows[0].get("pay")),
            rows[1], live_strategy_b._dec(rows[1].get("pay")),
        )
        same_shop_c[venue] = {
            "c": str(c) if c is not None else None,
            "legs": [{"player": r.get("player"), "pay": str(r.get("pay"))} for r in rows],
        }
    return {
        "when": POD_WHEN,
        "last_quotes": {
            f"{pid}|{venue}": {"pay": str(pay), "player": name, "seen": seen}
            for (pid, venue), (pay, name, seen) in quotes.items()
        },
        "cheapest_pair": None
        if pair is None
        else {
            "c": str(pair["c"]),
            "venues": pair["venues"],
            "same_shop": pair["same_shop"],
            "a": {"player": pair["a"].get("player"), "venue": pair["a"].get("venue"), "pay": str(pair["a"].get("pay"))},
            "b": {"player": pair["b"].get("player"), "venue": pair["b"].get("venue"), "pay": str(pair["b"].get("pay"))},
        },
        "pick_cheapest_legs": picked_out,
        "same_shop_c": same_shop_c,
        "n_ticks_window": len(ticks),
        "game_starts": sorted({t.get("game_start") or "" for t in ticks}),
    }


def b_t0_tape() -> dict:
    path = RAW / "orders.jsonl"
    missed = 0
    over = 0
    send = 0
    other = 0
    samples = []
    if not path.exists():
        return {"missed_window": 0, "c_over": 0, "send": 0, "other": 0, "n": 0}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if '"t0"' not in line and "t0_allin" not in line and "missed T0" not in line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if str(row.get("event") or "") != "t0":
                continue
            reason = str(row.get("reason") or row.get("note") or row.get("why") or "")
            action = str(row.get("action") or "")
            if action == "send":
                send += 1
            elif "missed T0 window" in reason:
                missed += 1
            elif "t0_allin_c_over_105" in reason:
                over += 1
            else:
                other += 1
            if len(samples) < 40 and (action == "send" or "missed T0" in reason or "t0_allin" in reason):
                samples.append(
                    {
                        "at": row.get("at") or row.get("ts") or row.get("when") or "",
                        "game": row.get("game") or "",
                        "action": action,
                        "reason": reason[:180],
                        "c": row.get("all_in") or row.get("c") or row.get("all_in_c") or "",
                    }
                )
    return {
        "missed_window": missed,
        "c_over": over,
        "send": send,
        "other": other,
        "n": missed + over + send + other,
        "samples": samples,
    }


def recommend(hist_first: dict, pct_first: dict, n_after5: int, n_hit: int, n_still15: int, n_still30: int, n_usable: int) -> dict:
    """Pick 15 or 30 from the live curve. HOLD 1.05. Not OOS shopping of C or D."""
    p90 = float((pct_first or {}).get("p90") or 0)
    share_after5 = (n_after5 / n_hit) if n_hit else 0
    still15 = (n_still15 / n_usable) if n_usable else 0
    still30 = (n_still30 / n_usable) if n_usable else 0
    # Modest longer watch: 15 covers the 5–15 tail and retries while C often still <=1.05.
    # 30 only if a large tail still first-hits after 15 or C is still good at 30 and not 15.
    new = 15
    why = (
        f"p90 first-hit {p90} min; {n_after5}/{n_hit} first drop to <=1.05 after 5 min "
        f"({share_after5:.0%}). C still <=1.05 near +15 min on {n_still15}/{n_usable} "
        f"usable matches, near +30 min on {n_still30}/{n_usable}."
    )
    if p90 > 15 or (n_hit and share_after5 >= 0.25 and p90 > 12):
        if still30 >= still15 - 0.05:
            new = 30
            why += " Tail past 15 minutes, so the longer 30-minute watch."
        else:
            why += " 15 minutes covers the observed first-hit tail."
    else:
        why += " 15 minutes is the documented longer watch (was 5) from this curve."
    return {"new_grace_sec": int(new * 60), "new_min": new, "why": why}


def main() -> None:
    paths = tennis_files()
    print("files", [p.parent.name for p in paths])
    meta = pass_starts(paths)
    print("games_seen", len(meta), "with_scheduled", sum(1 for b in meta.values() if b.get("starts")))
    windows = pass_samples(paths, meta)
    rows = []
    hist_first: dict[str, int] = defaultdict(int)
    hist_stay: dict[str, int] = defaultdict(int)
    firsts = []
    stays = []
    n_after5 = 0
    n_stay_after5 = 0
    n_hit = 0
    n_usable = 0
    n_still = {5: 0, 15: 0, 30: 0}
    n_mixed = 0
    n_same = 0
    for game, state in sorted(windows.items()):
        samples = state.get("samples") or []
        if not samples:
            continue
        n_usable += 1
        first, stay = hit_and_stay(samples)
        if first is not None:
            n_hit += 1
            firsts.append(first)
            if first > 5:
                n_after5 += 1
        if stay is not None:
            stays.append(stay)
            if stay > 5:
                n_stay_after5 += 1
        hist_first[bucket(first)] += 1
        hist_stay[bucket(stay)] += 1
        for mark in (5, 15, 30):
            flag = still_le(samples, mark)
            if flag:
                n_still[mark] += 1
        mixed = sum(1 for s in samples if not s.get("same_shop"))
        same = sum(1 for s in samples if s.get("same_shop"))
        if mixed:
            n_mixed += 1
        if same:
            n_same += 1
        c0 = next((s["c"] for s in samples if float(s["sec"]) >= 0), samples[0]["c"])
        rows.append(
            {
                "game": game,
                "t0": state["t0_iso"],
                "pre_t0_during": bool(state.get("pre_t0_during")),
                "n_samples": len(samples),
                "c_at_t0": c0,
                "first_hit_min": None if first is None else round(first, 2),
                "stay_min": None if stay is None else round(stay, 2),
                "absorb_min": None if state.get("absorb_sec") is None else round(state["absorb_sec"] / 60.0, 2),
                "venues_at_t0": next((s["venues"] for s in samples if float(s["sec"]) >= 0), samples[0]["venues"]),
                "same_shop_at_t0": next((s["same_shop"] for s in samples if float(s["sec"]) >= 0), samples[0]["same_shop"]),
            }
        )
    pct_first = percentiles(firsts)
    pct_stay = percentiles(stays)
    rec = recommend(hist_first, pct_first, n_after5, n_hit, n_still[15], n_still[30], n_usable)
    oct30 = RAW / "price_memory" / "2026-10-30" / "tennis.jsonl"
    pod = podoroska_snapshot(oct30) if oct30.exists() else {}
    tape = b_t0_tape()
    out = {
        "written_at": datetime.now(ET).isoformat(),
        "n_files": len(paths),
        "n_games_ticks": len(meta),
        "n_games_scheduled_t0": sum(1 for b in meta.values() if b.get("starts")),
        "n_usable": n_usable,
        "n_hit_105": n_hit,
        "n_never": n_usable - n_hit,
        "n_first_after_5": n_after5,
        "n_stay_after_5": n_stay_after5,
        "n_still_le_5": n_still[5],
        "n_still_le_15": n_still[15],
        "n_still_le_30": n_still[30],
        "n_games_any_mixed_shop": n_mixed,
        "n_games_any_same_shop": n_same,
        "hist_first": dict(hist_first),
        "hist_stay": dict(hist_stay),
        "pct_first": pct_first,
        "pct_stay": pct_stay,
        "recommend": rec,
        "current_grace_sec": int(live_strategy_b.T0_GRACE_SEC),
        "current_lead_sec": int(live_strategy_b.T0_LEAD_SEC),
        "c_hi": str(live_strategy_b.C_HI),
        "d": str(live_strategy_b.D),
        "podoroska": pod,
        "b_t0_tape": tape,
        "matches": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("usable", n_usable, "hit", n_hit, "first_after5", n_after5)
    print("pct_first", pct_first)
    print("pct_stay", pct_stay)
    print("still", n_still)
    print("recommend", rec)
    print("pod", json.dumps(pod.get("cheapest_pair"), default=str))
    print("pick", json.dumps(pod.get("pick_cheapest_legs"), default=str))
    print("same_shop_c", json.dumps(pod.get("same_shop_c"), default=str))
    print("b_tape", {k: tape.get(k) for k in ("n", "send", "missed_window", "c_over", "other")})
    print("wrote", OUT)


if __name__ == "__main__":
    main()
