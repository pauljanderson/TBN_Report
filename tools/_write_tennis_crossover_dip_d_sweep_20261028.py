"""Tennis crossover vs favorite-dip D sweep. Report only.

Rebuilds from price_memory tennis, live Strategy B watches, Q2 helpers, and
the prior 182-book dense freeze. Does not place, cancel, or amend orders.
Does not print secrets. Does not change live D=0.25, C=1.05, GTC, second B,
D NFL, leftover GTC, or stake. Does not overwrite live_architecture_20261028.html.
Not gold. Not DailyRun.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_strategy_b  # noqa: E402
import report_page_extras  # noqa: E402
from dense_inplay_fav_lock_cross_smalld_20261021 import (  # noqa: E402
    ORIGINAL_N,
    ORIGINAL_PAGE,
    assign_favorite,
    first_cross_yes,
    first_yes_at_or_below,
    freeze_keys_from_original_html,
    pair_key,
    simulate_b_variant,
    ticks_of,
)
from dense_inplay_yes_dip_20261021 import (  # noqa: E402
    ABSORB,
    assign_actual_t0,
    attach_start_sources,
    esc,
    iso_now,
    mark_inplay,
)
from inmatch_vol_hedge_20261021 import attach_pair_results, last_at_or_before, pair_matches  # noqa: E402
from odds_cross_no_roi_60_70_20261020 import table, tiny_note  # noqa: E402
from odds_cross_winrate_20261020 import as_float, game_norm, parse_dt  # noqa: E402
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from t0_all_games_stats import classify_dog_cross  # noqa: E402
from tennis_decade_at_start_20261020 import start_lookup_from  # noqa: E402
from tennis_dual_yes_dip_no_20261021 import last_name, stream_tennis  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "tennis_crossover_dip_d_sweep_20261028.html"
JSON_OUT = STAMP / "tennis_crossover_dip_d_sweep_20261028.json"
LIVE_ARCH = STAMP / "live_architecture_20261028.html"
WATCH = RAW / "strategy_b_watch.json"
DECILE_JSON = STAMP / "sport_league_t0_decile_20261027.json"
Q2_PAGE = STAMP / "t0_all_games_stats.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tennis_crossover_dip_d_sweep_20261028.html"
)

CROSS = 0.50
C_HI = 1.05
YES_LO = 0.10
YES_HI = 0.90
LIVE_D = 0.25
DIPS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40)
HEADLINE_D = 0.25
VOID = {"void", "refund", "push", "cancelled", "canceled", "n/a", "na"}

ASKED = (
    "Paul: “this is correct. now tell me How many tennis matches have a crossover, "
    "but no dip at the price we need. IS 25c still the optimal price to secure? we "
    "need to account for all the matches that will cost somewhere between 1 and 5 "
    "cents just to enter both as a buy at the outset. plus those that crossover but "
    "don't dip (enough)”"
)

PLAIN = (
    "A Yes ticket pays $1 if that named tennis player wins the match. At game start "
    "(T0) Tennis crossover buys Yes on both players when the two prices plus the "
    "house’s documented take-a-trade fees add up to at most $1.05. Only one player "
    "can win, so those two tickets always pay $1. If they cost $0.97 you lock 3 cents; "
    "if they cost $1.03 you are already down 3 cents — that 1–5 cent bill is the price "
    "of walking in the door, not a bug. A crossover is the cheaper player’s Yes later "
    "printing through 50 cents from below; we then buy one more of that cheaper name. "
    "A dip is buying one more of the original favorite cheap enough that the extra pair "
    "locks D cents: favorite Yes at or below $1 minus the crossover fill minus D. Live "
    "D is 25 cents. Hsu after a 60-cent Shimizu fill needed 15 cents, not 35 cents "
    "(60 minus 25). The extra dog is not locked without the dip — if the cheaper player "
    "loses, that extra ticket is a loss (Shimizu extra about −62 cents). This page "
    "rebuilds how often tennis actually crossed 50 cents, how often the favorite then "
    "printed at the live dip price, and whether 25 cents is still the best D on quality "
    "(average dollars and hit rate), not on getting the most fills. Research only. Not "
    "gold. Not DailyRun. Live D stays 25 cents."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:+.3f}" if number < 0 or number > 0 else "0.000"


def _px(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _pct(part: int, whole: int, digits: int = 1) -> str:
    if whole <= 0:
        return ""
    return f"{100.0 * part / whole:.{digits}f}"


def _median(values: list[float]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return float(statistics.median(nums))


def _mean(values: list[float]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _fmt_mins(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)


def fee_float(venue: str, price: float | None) -> float | None:
    if price is None:
        return None
    spec = {"venue": str(venue or "").strip()}
    got = live_strategy_b.t0_leg_fee(spec, Decimal(str(price)))
    if got is None:
        return None
    return float(got)


def all_in_from_asks(venue: str, pa: float | None, pb: float | None) -> float | None:
    if pa is None or pb is None:
        return None
    spec = {"venue": str(venue or "").strip()}
    got = live_strategy_b.t0_all_in_from_asks(
        spec, Decimal(str(pa)), spec, Decimal(str(pb))
    )
    if got is None:
        return None
    return float(got)


def in_yes_band(px: float | None) -> bool:
    return px is not None and YES_LO < px < YES_HI


def lock_bucket(all_in: float | None) -> str:
    """1–5¢ profit if C<$1; 1–5¢ cost is the door charge when C is $1.01–$1.05."""
    if all_in is None:
        return "fee unknown"
    profit = 1.0 - float(all_in)
    cents = int(round(abs(profit) * 100.0))
    if abs(profit) < 0.005:
        return "0¢ (even)"
    if profit > 0:
        if cents >= 6:
            return ">5¢ profit"
        return f"{cents}¢ profit"
    if cents <= 5:
        return f"{cents}¢ cost"
    return "loser (>$1 by >5¢)"


def assign_live_b_t0(pair: dict, start_lookup: dict) -> None:
    attach_start_sources(pair, start_lookup)
    clock_dt, src = live_strategy_b.live_trusted_clock(pair)
    pair["t0_a"] = None
    pair["t0_b"] = None
    pair["t0_ts"] = None
    pair["t0_label"] = ""
    pair["clock_src"] = src
    pair["skip_reason"] = ""
    if clock_dt is None:
        pair["game_start"] = pair.get("listed_start") or pair.get("start") or ""
        pair["skip_reason"] = "no trusted clock"
        return
    pair["game_start"] = clock_dt.isoformat()
    start_ts = int(clock_dt.timestamp())
    yes_a = pair.get("yes_a") or []
    yes_b = pair.get("yes_b") or []
    if not yes_a or not yes_b:
        pair["skip_reason"] = "missing Yes ticks"
        return
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
    pair["skip_reason"] = "no two-sided T0 quotes"


def first_from_below_cross(
    t0_px: float,
    t0_ts: int,
    ticks: list[tuple[int, float]],
    hi: int | None,
) -> dict | None:
    """T0-dog Yes through 50¢ from below. Matches extras_cross_ready / Q2."""
    prev = float(t0_px)
    for ts, px in ticks:
        if ts <= t0_ts:
            continue
        if hi is not None and ts > hi:
            break
        price = float(px)
        if price <= ABSORB + 1e-12 or price >= 0.95 - 1e-12:
            prev = price
            continue
        if prev <= CROSS + 1e-12 and price > CROSS:
            return {"ts": int(ts), "px": price}
        prev = price
    return None


def min_fav_after(
    ticks: list[tuple[int, float]],
    after_ts: int,
    hi: int | None,
) -> dict | None:
    best = None
    for ts, px in ticks:
        if ts <= after_ts:
            continue
        if hi is not None and ts > hi:
            break
        price = float(px)
        if price <= ABSORB + 1e-12:
            continue
        if best is None or price < best["px"]:
            best = {"ts": int(ts), "px": price}
    return best


def pnl_parts(
    *,
    t0_all_in: float | None,
    cross_px: float | None,
    cross_fee: float | None,
    dip_px: float | None,
    dip_fee: float | None,
    winner: str | None,
    fav: str | None,
    dog: str | None,
) -> dict:
    rec = {
        "t0_pnl": None,
        "extra_dog_pnl": None,
        "extra_fav_pnl": None,
        "total": None,
        "payout": None,
        "cost": None,
    }
    if t0_all_in is None or winner not in ("a", "b") or not fav or not dog:
        return rec
    cost = float(t0_all_in)
    paid = 1.0
    rec["t0_pnl"] = 1.0 - float(t0_all_in)
    if cross_px is not None:
        cfee = float(cross_fee or 0.0)
        cost += float(cross_px) + cfee
        dog_pay = 1.0 if winner == dog else 0.0
        paid += dog_pay
        rec["extra_dog_pnl"] = dog_pay - float(cross_px) - cfee
    if dip_px is not None:
        dfee = float(dip_fee or 0.0)
        cost += float(dip_px) + dfee
        fav_pay = 1.0 if winner == fav else 0.0
        paid += fav_pay
        rec["extra_fav_pnl"] = fav_pay - float(dip_px) - dfee
    rec["payout"] = paid
    rec["cost"] = cost
    rec["total"] = paid - cost
    return rec


def summarize_pnls(pnls: list[float]) -> dict:
    nums = [float(x) for x in pnls if x is not None]
    out = {
        "n": len(nums),
        "wins": 0,
        "losses": 0,
        "win_pct": None,
        "mean": None,
        "median": None,
        "total": None,
        "pf": None,
        "avg_win": None,
        "avg_loss": None,
        "max_dd": None,
        "note": tiny_note(len(nums)),
    }
    if not nums:
        return out
    wins = [x for x in nums if x > 1e-12]
    losses = [x for x in nums if x < -1e-12]
    out["wins"] = len(wins)
    out["losses"] = len(losses)
    out["win_pct"] = 100.0 * len(wins) / len(nums)
    out["mean"] = sum(nums) / len(nums)
    out["median"] = float(statistics.median(nums))
    out["total"] = sum(nums)
    out["avg_win"] = (sum(wins) / len(wins)) if wins else None
    out["avg_loss"] = (sum(losses) / len(losses)) if losses else None
    if losses:
        out["pf"] = (sum(wins) / abs(sum(losses))) if wins else 0.0
    elif wins:
        out["pf"] = None
    peak = 0.0
    cum = 0.0
    dd = 0.0
    for x in nums:
        cum += x
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    out["max_dd"] = dd
    return out


def pick_verdict(sweep: list[dict]) -> tuple[str, str]:
    """Quality vs live D=0.25. No live retune. Research-only."""
    by_d = {round(r["d"], 2): r for r in sweep}
    ctrl = by_d.get(LIVE_D)
    if not ctrl or ctrl.get("crossed_mean") is None:
        return "HOLD", "Not enough settled crossed games to rank D."
    ranked = sorted(
        [r for r in sweep if r.get("crossed_mean") is not None],
        key=lambda r: (r["crossed_mean"], r.get("hit_rate") or 0.0),
        reverse=True,
    )
    best = ranked[0]
    neighbors = [by_d.get(x) for x in (0.20, 0.30) if by_d.get(x)]
    ctrl_mean = float(ctrl["crossed_mean"])
    best_mean = float(best["crossed_mean"])
    gap = best_mean - ctrl_mean
    if best["d"] == LIVE_D:
        return (
            "KEEP",
            f"On this October 2026 tennis tape, D=25¢ has the best (or tied) "
            f"with-fee average $ on crossed games ({_money(ctrl_mean)}). "
            "Hit rate is not the score — quality is. Live D stays 25¢. No IS row.",
        )
    if gap < 0.005:
        return (
            "HOLD",
            f"D={int(best['d']*100)}¢ is a hair better on crossed-game EV "
            f"({_money(best_mean)} vs {_money(ctrl_mean)} at 25¢). Gap is under "
            "half a cent and there is no in-sample row. HOLD live 25¢. Do not retune.",
        )
    neigh_better = [
        r for r in neighbors
        if r and r.get("crossed_mean") is not None and r["crossed_mean"] > ctrl_mean + 0.005
    ]
    if neigh_better:
        who = ", ".join(f"{int(r['d']*100)}¢ {_money(r['crossed_mean'])}" for r in neigh_better)
        return (
            "HOLD",
            f"Neighbor {who} beats 25¢ ({_money(ctrl_mean)}) on this OOS tape. "
            "That is in-sample selection on the same book if we moved live D. "
            "HOLD 25¢. Do not retune OOS. Research only.",
        )
    return (
        "HOLD",
        f"Best crossed-game EV is D={int(best['d']*100)}¢ at {_money(best_mean)}; "
        f"live 25¢ is {_money(ctrl_mean)}. Tape is 2026 only (no IS). HOLD live 25¢.",
    )


def svg_line(
    points: list[tuple[str, float]],
    *,
    title: str,
    color: str,
    y_suffix: str = "",
    highlight: str | None = None,
    zero_line: bool = False,
) -> str:
    width, height = 760, 240
    pad_l, pad_r, pad_t, pad_b = 52, 18, 30, 40
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    ys = [p[1] for p in points] or [0.0]
    lo = min(ys)
    hi = max(ys)
    if zero_line:
        lo = min(0.0, lo)
        hi = max(0.0, hi)
    span = hi - lo or 1.0
    lo -= span * 0.08
    hi += span * 0.12
    span = hi - lo or 1.0
    n = max(len(points) - 1, 1)

    def xy(i: int, yv: float) -> tuple[float, float]:
        x = pad_l + (i / n) * inner_w
        y = pad_t + (hi - yv) / span * inner_h
        return x, y

    coords = [xy(i, yv) for i, (_lab, yv) in enumerate(points)]
    d = " ".join(
        ("M" if i == 0 else "L") + f" {x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords)
    )
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="240" role="img" '
        f'aria-label="{esc(title)}">',
        f'<text x="{pad_l}" y="18" font-size="13" fill="#334155">{esc(title)}</text>',
    ]
    if zero_line:
        zy = pad_t + (hi - 0.0) / span * inner_h
        parts.append(
            f'<line x1="{pad_l}" y1="{zy:.1f}" x2="{width - pad_r}" y2="{zy:.1f}" '
            f'stroke="#cbd5e1" stroke-width="1"/>'
        )
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.5"/>')
    for i, ((lab, yv), (x, y)) in enumerate(zip(points, coords)):
        is_hl = highlight is not None and lab == highlight
        r = 5 if is_hl else 3.5
        fill = "#b45309" if is_hl else color
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"/>')
        label = f"{yv:.1f}{y_suffix}" if abs(yv) >= 1 else f"{yv:.3f}{y_suffix}"
        if y_suffix == "%":
            label = f"{yv:.1f}%"
        elif y_suffix == "$":
            label = f"{yv:+.3f}"
        parts.append(
            f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-size="11" '
            f'fill="#0f172a">{esc(label)}</text>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{height - 14}" text-anchor="middle" font-size="11" '
            f'fill="#475569">{esc(lab)}</text>'
        )
    parts.append("</svg>")
    return f'<div class="chart">{"".join(parts)}</div>'


def simulate_pair(pair: dict) -> dict:
    assign_favorite(pair)
    venue = str(pair.get("venue") or "")
    t0a = as_float(pair.get("t0_a"))
    t0b = as_float(pair.get("t0_b"))
    all_in = all_in_from_asks(venue, t0a, t0b)
    wire = (t0a or 0) + (t0b or 0) if t0a is not None and t0b is not None else None
    fav = pair.get("fav")
    dog = pair.get("dog")
    t0_dog = as_float(pair.get("t0_dog"))
    t0_fav = as_float(pair.get("t0_fav"))
    lo = pair.get("lo")
    hi = pair.get("hi")
    rec = {
        "game": pair.get("game") or "",
        "platform": venue,
        "side": f"fav {last_name(pair.get('fav_name'))} / dog {last_name(pair.get('dog_name'))}",
        "fav_name": pair.get("fav_name") or "",
        "dog_name": pair.get("dog_name") or "",
        "game_start": pair.get("game_start") or pair.get("actual_start") or pair.get("start") or "",
        "t0_label": pair.get("t0_label") or "",
        "clock_src": pair.get("clock_src") or "",
        "t0_fav": t0_fav,
        "t0_dog": t0_dog,
        "t0_wire": wire,
        "t0_all_in": all_in,
        "t0_lock": (1.0 - all_in) if all_in is not None else None,
        "bucket": lock_bucket(all_in),
        "yes_ok": in_yes_band(t0a) and in_yes_band(t0b),
        "c_ok": all_in is not None and all_in <= C_HI + 1e-12,
        "fee_unknown": all_in is None and t0a is not None and t0b is not None,
        "settled": bool(pair.get("settled") and pair.get("winner") in ("a", "b")),
        "winner": pair.get("winner"),
        "winner_name": "",
        "off_a": pair.get("off_a") or "",
        "off_b": pair.get("off_b") or "",
        "crossed": False,
        "cross_px": None,
        "cross_ts": None,
        "cross_mins": None,
        "q2_kind": "",
        "q2_n_cross": 0,
        "dog_started_lt50": t0_dog is not None and t0_dog < CROSS - 1e-12,
        "dips": {},
        "min_fav_px": None,
        "min_fav_ts": None,
        "fav": fav,
        "dog": dog,
        "t0_ts": pair.get("t0_ts"),
        "date": "",
    }
    if pair.get("winner") == "a":
        rec["winner_name"] = pair.get("side_a") or ""
    elif pair.get("winner") == "b":
        rec["winner_name"] = pair.get("side_b") or ""
    t0_ts = pair.get("t0_ts")
    if t0_ts:
        rec["date"] = datetime.fromtimestamp(int(t0_ts), ET).strftime("%Y-%m-%d")
    if dog and lo is not None:
        dog_ticks = ticks_of(pair, dog, "yes")
        post = [(ts, px) for ts, px in dog_ticks if ts > int(lo) and (hi is None or ts <= hi)]
        cross = None
        if t0_dog is not None:
            q2 = classify_dog_cross(float(t0_dog), int(lo), post)
            rec["q2_kind"] = q2.get("kind") or ""
            rec["q2_n_cross"] = int(q2.get("n_cross") or 0)
            cross = first_from_below_cross(float(t0_dog), int(lo), dog_ticks, hi)
        if cross:
            rec["crossed"] = True
            rec["cross_px"] = cross["px"]
            rec["cross_ts"] = cross["ts"]
            rec["cross_mins"] = (cross["ts"] - int(lo)) / 60.0
    if rec["crossed"] and fav:
        fav_ticks = ticks_of(pair, fav, "yes")
        low = min_fav_after(fav_ticks, rec["cross_ts"], hi)
        if low:
            rec["min_fav_px"] = low["px"]
            rec["min_fav_ts"] = low["ts"]
        cross_fee = fee_float(venue, rec["cross_px"])
        rec["cross_fee"] = cross_fee
        for dip in DIPS:
            target = 1.0 - float(rec["cross_px"]) - float(dip)
            extra = first_yes_at_or_below(fav_ticks, rec["cross_ts"], hi if hi is not None else 10**18, target)
            hit = extra is not None
            dip_px = extra["px"] if extra else None
            dip_ts = extra["ts"] if extra else None
            dip_fee = fee_float(venue, dip_px) if dip_px is not None else None
            mins = None
            if dip_ts is not None:
                mins = (int(dip_ts) - int(rec["cross_ts"])) / 60.0
            gap = None
            if rec["min_fav_px"] is not None:
                gap = float(rec["min_fav_px"]) - float(target)
            parts = pnl_parts(
                t0_all_in=all_in,
                cross_px=rec["cross_px"],
                cross_fee=cross_fee,
                dip_px=dip_px if hit else None,
                dip_fee=dip_fee if hit else None,
                winner=pair.get("winner"),
                fav=fav,
                dog=dog,
            )
            rec["dips"][dip] = {
                "d": dip,
                "target": target,
                "hit": hit,
                "dip_px": dip_px,
                "dip_ts": dip_ts,
                "dip_mins": mins,
                "dip_fee": dip_fee,
                "gap": gap,
                "pnl": parts,
            }
    elif rec["settled"] and all_in is not None:
        parts = pnl_parts(
            t0_all_in=all_in,
            cross_px=None,
            cross_fee=None,
            dip_px=None,
            dip_fee=None,
            winner=pair.get("winner"),
            fav=fav,
            dog=dog,
        )
        rec["t0_only_pnl"] = parts
    return rec


def t0_qualified(row: dict) -> bool:
    return bool(row.get("yes_ok") and row.get("c_ok") and row.get("t0_all_in") is not None)


def load_live_b() -> dict:
    if not WATCH.is_file():
        return {"n": 0, "rows": [], "source": str(WATCH), "missing": True}
    data = json.loads(WATCH.read_text(encoding="utf-8"))
    rows = []
    for match in data.get("matches") or []:
        if not isinstance(match, dict):
            continue
        t0 = match.get("t0_yes") if isinstance(match.get("t0_yes"), dict) else {}
        a = t0.get("a") if isinstance(t0.get("a"), dict) else {}
        b = t0.get("b") if isinstance(t0.get("b"), dict) else {}
        fill_a = as_float(a.get("fill_px") or a.get("price"))
        fill_b = as_float(b.get("fill_px") or b.get("price"))
        fee_a = as_float(a.get("fill_fee"))
        fee_b = as_float(b.get("fill_fee"))
        both = bool(a.get("filled") and b.get("filled"))
        all_in = None
        if both and fill_a is not None and fill_b is not None:
            fa = fee_a if fee_a is not None else fee_float(match.get("venue") or "", fill_a)
            fb = fee_b if fee_b is not None else fee_float(match.get("venue") or "", fill_b)
            if fa is not None and fb is not None:
                all_in = fill_a + fill_b + fa + fb
        cross_px = as_float(match.get("cross_fill"))
        dog = str(match.get("t0_dog_player") or match.get("dog_player") or "")
        fav = str(match.get("t0_fav_player") or match.get("fav_player") or "")
        who = str(match.get("cross_player") or "")
        real_cross = (
            cross_px is not None
            and cross_px > CROSS + 1e-12
            and (not who or not fav or game_norm(who) != game_norm(fav))
        )
        note = str(match.get("note") or "")
        dip_hit = bool(match.get("fav_ioc_sent")) and (
            "B complete" in note or str(match.get("stage") or "") == "done"
        )
        target = None
        if cross_px is not None:
            raw_t = as_float(match.get("fav_target"))
            target = raw_t if raw_t is not None else float(1.0 - cross_px - LIVE_D)
        rows.append({
            "game": match.get("game") or "",
            "platform": match.get("venue") or "",
            "side": f"fav {last_name(fav)} / dog {last_name(dog)}",
            "game_start": match.get("listed_start") or match.get("t0_when") or "",
            "stage": match.get("stage") or "",
            "note": note[:180],
            "t0_both": both,
            "t0_all_in": all_in,
            "bucket": lock_bucket(all_in) if all_in is not None else "",
            "t0_lock": (1.0 - all_in) if all_in is not None else None,
            "crossed": real_cross,
            "cross_px": cross_px if real_cross else None,
            "fav_target": target if real_cross else None,
            "dip_hit": dip_hit if real_cross else False,
            "fav_ioc_sent": bool(match.get("fav_ioc_sent")),
            "waiting_dip": str(match.get("stage") or "") == "waiting_fav_dip",
            "key": match.get("key") or "",
            "date": str(match.get("t0_when") or match.get("opened_at") or "")[:10],
        })
    t0s = [r for r in rows if r["t0_both"]]
    crossed = [r for r in t0s if r["crossed"]]
    dipped = [r for r in crossed if r["dip_hit"]]
    missed = [r for r in crossed if not r["dip_hit"]]
    pending = [r for r in missed if r["waiting_dip"]]
    return {
        "n": len(rows),
        "n_t0": len(t0s),
        "n_cross": len(crossed),
        "n_dip": len(dipped),
        "n_miss": len(missed),
        "n_pending_dip": len(pending),
        "rows": rows,
        "t0s": t0s,
        "crossed": crossed,
        "dipped": dipped,
        "missed": missed,
        "source": "raw/strategy_b_watch.json (live B tape)",
        "missing": False,
        "d": str((data.get("d") if isinstance(data, dict) else None) or "0.25"),
    }


def replay_dense_freeze(pairs: list[dict], start_lookup: dict) -> dict:
    out = {
        "available": False,
        "n_keys": ORIGINAL_N,
        "n_matched": 0,
        "n_settled": 0,
        "n_cross": 0,
        "n_dip": 0,
        "n_miss": 0,
        "hit_pct": "",
        "note": "",
    }
    if not ORIGINAL_PAGE.is_file():
        out["note"] = f"missing {ORIGINAL_PAGE.name}"
        return out
    try:
        keys = set(freeze_keys_from_original_html())
    except Exception as exc:
        out["note"] = f"could not read freeze keys: {type(exc).__name__}"
        return out
    by_key = {pair_key(p): p for p in pairs}
    matched = []
    for key in keys:
        pair = by_key.get(key)
        if pair is None:
            continue
        assign_actual_t0(pair, start_lookup)
        mark_inplay(pair)
        assign_favorite(pair)
        dog = pair.get("dog")
        lo, hi = pair.get("lo"), pair.get("hi")
        cross = None
        if dog and lo is not None and hi is not None:
            cross = first_cross_yes(ticks_of(pair, dog, "yes"), lo, hi)
        rec = simulate_b_variant(
            pair,
            LIVE_D,
            cross,
            cross["px"] if cross else None,
            cross["ts"] if cross else None,
            "first print > 0.50",
        )
        matched.append((pair, rec))
    settled = [(p, r) for p, r in matched if p.get("settled") and p.get("winner") in ("a", "b")]
    crossed = [(p, r) for p, r in settled if r.get("crossed")]
    dipped = [(p, r) for p, r in crossed if r.get("lock_filled")]
    out.update({
        "available": True,
        "n_matched": len(matched),
        "n_settled": len(settled),
        "n_cross": len(crossed),
        "n_dip": len(dipped),
        "n_miss": len(crossed) - len(dipped),
        "hit_pct": _pct(len(dipped), len(crossed)),
        "note": (
            "Replay of the 182-book dense freeze (tape-resume T0 allowed; C was 0.95–1.20; "
            "optimistic first print >50¢). Prior stamp said 46/76 (60.5%) on 119 settled. "
            "This is a labeled prior, not the live-B C≤1.05 book."
        ),
    })
    return out


def sweep_from_rows(rows: list[dict]) -> list[dict]:
    settled = [r for r in rows if r.get("settled")]
    crossed = [r for r in settled if r.get("crossed")]
    out = []
    for dip in DIPS:
        hits = []
        miss_gaps = []
        dip_mins = []
        pnl_all_t0 = []
        pnl_crossed = []
        pnl_dipped = []
        n_hit = 0
        n_miss = 0
        for row in settled:
            if not row.get("crossed"):
                parts = row.get("t0_only_pnl") or {}
                if parts.get("total") is not None:
                    pnl_all_t0.append(parts["total"])
                continue
            rec = (row.get("dips") or {}).get(dip) or {}
            hit = bool(rec.get("hit"))
            if hit:
                n_hit += 1
                if rec.get("dip_mins") is not None:
                    dip_mins.append(rec["dip_mins"])
            else:
                n_miss += 1
                if rec.get("gap") is not None:
                    miss_gaps.append(rec["gap"])
            total = (rec.get("pnl") or {}).get("total")
            if total is not None:
                pnl_all_t0.append(total)
                pnl_crossed.append(total)
                if hit:
                    pnl_dipped.append(total)
        s_all = summarize_pnls(pnl_all_t0)
        s_x = summarize_pnls(pnl_crossed)
        s_d = summarize_pnls(pnl_dipped)
        n_cross = n_hit + n_miss
        out.append({
            "d": dip,
            "arm": f"D={int(round(dip * 100))}¢",
            "role": "CONTROL" if abs(dip - LIVE_D) < 1e-12 else "candidate",
            "n_t0_settled": len(settled),
            "n_cross": n_cross,
            "n_hit": n_hit,
            "n_miss": n_miss,
            "hit_rate": (100.0 * n_hit / n_cross) if n_cross else None,
            "median_mins": _median(dip_mins),
            "median_gap": _median(miss_gaps),
            "t0_mean": s_all.get("mean"),
            "t0_n": s_all.get("n"),
            "crossed_mean": s_x.get("mean"),
            "crossed_n": s_x.get("n"),
            "crossed_wr": s_x.get("win_pct"),
            "crossed_pf": s_x.get("pf"),
            "crossed_dd": s_x.get("max_dd"),
            "dipped_mean": s_d.get("mean"),
            "dipped_n": s_d.get("n"),
            "dipped_wr": s_d.get("win_pct"),
            "note": tiny_note(n_cross),
        })
    return out


def sensitivity_by_t0_bucket(rows: list[dict]) -> list[dict]:
    """Best D inside each T0 lock-profit bucket. Rank can move because the matches differ."""
    settled = [r for r in rows if r.get("settled") and r.get("crossed")]
    groups = defaultdict(list)
    for row in settled:
        groups[row.get("bucket") or ""].append(row)
    out = []
    for bucket, bag in sorted(groups.items(), key=lambda kv: kv[0]):
        best = None
        best_mean = None
        means = {}
        for dip in DIPS:
            pnls = []
            for row in bag:
                rec = (row.get("dips") or {}).get(dip) or {}
                total = (rec.get("pnl") or {}).get("total")
                if total is not None:
                    pnls.append(total)
            mean = _mean(pnls)
            means[dip] = mean
            if mean is not None and (best_mean is None or mean > best_mean):
                best_mean = mean
                best = dip
        out.append({
            "bucket": bucket,
            "n": len(bag),
            "best_d": f"{int(best * 100)}¢" if best is not None else "",
            "best_mean": best_mean,
            "d25_mean": means.get(LIVE_D),
            "moved": bool(best is not None and abs(best - LIVE_D) > 1e-12),
            "note": tiny_note(len(bag)),
        })
    return out


def constant_t0_shift(rows: list[dict], t0_pnl: float) -> list[dict]:
    """Replace every game's T0 lock with a fixed 1¢ or 5¢ cost. D rank cannot change."""
    settled = [r for r in rows if r.get("settled")]
    out = []
    for dip in DIPS:
        pnls = []
        for row in settled:
            extra = 0.0
            if row.get("crossed"):
                rec = (row.get("dips") or {}).get(dip) or {}
                parts = rec.get("pnl") or {}
                if parts.get("extra_dog_pnl") is not None:
                    extra += parts["extra_dog_pnl"]
                if parts.get("extra_fav_pnl") is not None:
                    extra += parts["extra_fav_pnl"]
            elif (row.get("t0_only_pnl") or {}).get("total") is None:
                continue
            pnls.append(float(t0_pnl) + extra)
        s = summarize_pnls(pnls)
        out.append({
            "d": dip,
            "arm": f"D={int(round(dip * 100))}¢",
            "mean": s.get("mean"),
            "n": s.get("n"),
        })
    return out


def match_rows_for_html(rows: list[dict], dip: float = HEADLINE_D) -> list[dict]:
    out = []
    for row in rows:
        rec = (row.get("dips") or {}).get(dip) or {}
        parts = rec.get("pnl") or row.get("t0_only_pnl") or {}
        mix = "T0 only"
        if row.get("crossed") and rec.get("hit"):
            mix = "cross + dip"
        elif row.get("crossed"):
            mix = "cross, no dip"
        out.append({
            "platform": row.get("platform") or "",
            "side": row.get("side") or "",
            "game": row.get("game") or "",
            "game_start": (row.get("game_start") or "")[:25],
            "date": row.get("date") or "",
            "t0_fav": _px(row.get("t0_fav")),
            "t0_dog": _px(row.get("t0_dog")),
            "t0_all_in": _px(row.get("t0_all_in")),
            "bucket": row.get("bucket") or "",
            "cross_px": _px(row.get("cross_px")),
            "target": _px(rec.get("target")),
            "min_fav": _px(row.get("min_fav_px")),
            "gap": _px(rec.get("gap")),
            "hit": "yes" if rec.get("hit") else ("no" if row.get("crossed") else ""),
            "dip_mins": _fmt_mins(rec.get("dip_mins")),
            "mix": mix,
            "winner": last_name(row.get("winner_name") or ""),
            "pnl": _money(parts.get("total")),
            "t0_pnl": _money(parts.get("t0_pnl") if parts.get("t0_pnl") is not None else row.get("t0_lock")),
            "dog_pnl": _money(parts.get("extra_dog_pnl")),
            "fav_pnl": _money(parts.get("extra_fav_pnl")),
            "settled": "yes" if row.get("settled") else "no",
            "q2": row.get("q2_kind") or "",
        })
    return out


def live_rows_for_html(live: dict) -> list[dict]:
    out = []
    for row in live.get("t0s") or []:
        mix = "T0 only"
        if row.get("crossed") and row.get("dip_hit"):
            mix = "cross + dip"
        elif row.get("crossed") and row.get("waiting_dip"):
            mix = "cross, waiting dip"
        elif row.get("crossed"):
            mix = "cross, no dip"
        out.append({
            "platform": row.get("platform") or "",
            "side": row.get("side") or "",
            "game": row.get("game") or "",
            "game_start": (row.get("game_start") or "")[:25],
            "stage": row.get("stage") or "",
            "t0_all_in": _px(row.get("t0_all_in")),
            "bucket": row.get("bucket") or "",
            "cross_px": _px(row.get("cross_px")),
            "target": _px(row.get("fav_target")),
            "mix": mix,
            "note": row.get("note") or "",
        })
    return out


def build_html(payload: dict) -> str:
    freeze = table(
        [("Knob", "text"), ("Freeze", "text")],
        payload["freeze_rows"],
        ["k", "v"],
    )
    bucket_tbl = table(
        [
            ("After-fee T0 lock", "text"),
            ("N T0-qualified", "num"),
            ("N settled", "num"),
            ("% of T0-qualified", "num"),
            ("Sample", "text"),
        ],
        payload["bucket_rows"],
        ["bucket", "n", "n_settled", "pct", "note"],
    )
    sweep_tbl = table(
        [
            ("Arm", "text"),
            ("Role", "text"),
            ("N T0 settled", "num"),
            ("N crossed", "num"),
            ("Hit dip", "num"),
            ("Miss dip", "num"),
            ("Hit %", "num"),
            ("Median min to dip", "num"),
            ("Median miss gap $ (min fav − target)", "num"),
            ("EV $ / T0 game", "num"),
            ("EV $ / crossed game", "num"),
            ("Crossed win %", "num"),
            ("Crossed PF", "num"),
            ("1-contract Max DD $", "num"),
            ("EV $ / dipped game", "num"),
            ("Dipped N", "num"),
            ("Note", "text"),
        ],
        payload["sweep_rows"],
        [
            "arm", "role", "n_t0_settled", "n_cross", "n_hit", "n_miss", "hit_rate",
            "median_mins", "median_gap", "t0_mean", "crossed_mean", "crossed_wr",
            "crossed_pf", "crossed_dd", "dipped_mean", "dipped_n", "note",
        ],
    )
    q2_tbl = table(
        [
            ("Path", "text"),
            ("N", "num"),
            ("% of tennis Q2 denom", "num"),
            ("Sample", "text"),
        ],
        payload["q2_rows"],
        ["path", "n", "pct", "note"],
    )
    live_sum = table(
        [
            ("Live B tape", "text"),
            ("N", "num"),
            ("Note", "text"),
        ],
        payload["live_sum_rows"],
        ["label", "n", "note"],
    )
    live_tbl = table(
        [
            ("Platform", "text"),
            ("Side", "text"),
            ("Game", "text"),
            ("Game start", "date"),
            ("Stage", "text"),
            ("T0 all-in", "num"),
            ("T0 lock bucket", "text"),
            ("Cross fill", "num"),
            ("Fav target D=25", "num"),
            ("Mix", "text"),
            ("Note", "text"),
        ],
        payload["live_match_rows"],
        [
            "platform", "side", "game", "game_start", "stage", "t0_all_in",
            "bucket", "cross_px", "target", "mix", "note",
        ],
    )
    match_tbl = table(
        [
            ("Platform", "text"),
            ("Side", "text"),
            ("Game", "text"),
            ("Game start", "date"),
            ("Date", "date"),
            ("T0 fav", "num"),
            ("T0 dog", "num"),
            ("T0 all-in", "num"),
            ("T0 lock", "text"),
            ("Cross fill", "num"),
            ("Fav target D=25", "num"),
            ("Min fav print", "num"),
            ("Miss gap $", "num"),
            ("Hit D=25", "text"),
            ("Min to dip", "num"),
            ("Mix", "text"),
            ("Winner", "text"),
            ("Settled", "text"),
            ("T0 P&L", "num"),
            ("Extra dog P&L", "num"),
            ("Extra fav P&L", "num"),
            ("Combined P&L", "num"),
            ("Q2 path", "text"),
        ],
        payload["match_rows"],
        [
            "platform", "side", "game", "game_start", "date", "t0_fav", "t0_dog",
            "t0_all_in", "bucket", "cross_px", "target", "min_fav", "gap", "hit",
            "dip_mins", "mix", "winner", "settled", "t0_pnl", "dog_pnl", "fav_pnl",
            "pnl", "q2",
        ],
    )
    miss_tbl = table(
        [
            ("Platform", "text"),
            ("Side", "text"),
            ("Game", "text"),
            ("Game start", "date"),
            ("Cross fill", "num"),
            ("Fav target D=25", "num"),
            ("Min fav print", "num"),
            ("Miss gap $", "num"),
            ("Winner", "text"),
            ("Extra dog P&L", "num"),
            ("Combined P&L", "num"),
        ],
        payload["miss_rows"],
        [
            "platform", "side", "game", "game_start", "cross_px", "target",
            "min_fav", "gap", "winner", "dog_pnl", "pnl",
        ],
    )
    sens_tbl = table(
        [
            ("T0 lock bucket", "text"),
            ("N crossed settled", "num"),
            ("Best D on EV", "text"),
            ("Best EV $", "num"),
            ("D=25 EV $", "num"),
            ("Optimal D moved?", "text"),
            ("Sample", "text"),
        ],
        payload["sens_rows"],
        ["bucket", "n", "best_d", "best_mean", "d25_mean", "moved", "note"],
    )
    prior_tbl = table(
        [
            ("Source", "text"),
            ("Grain", "text"),
            ("N", "text"),
            ("What it was", "text"),
            ("Rebuilt here", "text"),
        ],
        payload["prior_rows"],
        ["src", "grain", "n", "was", "now"],
    )
    h = payload["headline"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis crossover vs dip D sweep 2026-10-28</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.hl {{ background: #fef9c3; border: 1px solid #eab308; padding: 10px 12px; margin: 0 0 1rem; }}
.warn {{ background: #fef2f2; border: 1px solid #f87171; padding: 10px 12px; margin: 0 0 1rem; }}
.ok {{ background: #ecfdf5; border: 1px solid #34d399; padding: 10px 12px; margin: 0 0 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
.chart {{ margin: 0.6rem 0 1rem; max-width: 900px; }}
.kpi-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 1rem; }}
.kpi {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 10px 12px; min-width: 9rem; }}
.kpi-label {{ font-size: 0.78rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.03em; }}
.kpi-value {{ font-size: 1.25rem; font-weight: 650; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Tennis crossover, but no dip — is 25¢ still the price?</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun.
Does not place orders. Live D=0.25, C=1.05, GTC, second B, leftover GTC, and stake are unchanged.
The whole tape is out-of-sample (OOS): every T0 is on or after 2024-01-01. There is no in-sample (IS) row.
Verdict: <strong>{esc(payload['verdict'])}</strong>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Headline (research tape, live-B T0, C≤1.05 after fee, settled):</strong>
{esc(h['n_cross'])} tennis books crossed 50¢ on the T0 dog;
<strong>{esc(h['n_miss'])} had no dip at D=25¢</strong>
({esc(h['miss_pct'])}% miss / {esc(h['hit_pct'])}% hit, {esc(h['n_hit'])}/{esc(h['n_cross'])}).
Unique games: {esc(h['n_cross_games'])} crossed, {esc(h['n_miss_games'])} no dip.</p>
<p><strong>Is 25¢ still optimal?</strong> {esc(payload['verdict_why'])}</p>
<p><strong>How 1–5¢ T0 is in the EV:</strong> every T0-qualified game keeps
$1 minus after-fee both-Yes cost, whether or not it later crosses.
A 3¢ door charge is −$0.03 on that game before any extra tickets.
The extra dog is added only if they cross; the extra favorite only if they dip.
Fees sit on each ticket. Shimizu-style extras stay directional until a dip fills.</p>
</div>

<div class="kpi-row">
<div class="kpi"><div class="kpi-label">Tennis two-sided books</div><div class="kpi-value">{esc(payload['n_pairs'])}</div></div>
<div class="kpi"><div class="kpi-label">Trusted T0</div><div class="kpi-value">{esc(payload['n_trusted'])}</div></div>
<div class="kpi"><div class="kpi-label">T0 both-Yes C≤1.05</div><div class="kpi-value">{esc(payload['n_t0'])}</div></div>
<div class="kpi"><div class="kpi-label">Settled in that book</div><div class="kpi-value">{esc(payload['n_t0_settled'])}</div></div>
<div class="kpi"><div class="kpi-label">Crossed / no dip @25¢</div><div class="kpi-value">{esc(h['n_cross'])} / {esc(h['n_miss'])}</div></div>
<div class="kpi"><div class="kpi-label">Hit % @25¢</div><div class="kpi-value">{esc(h['hit_pct'])}%</div></div>
</div>

<div class="warn">
<p>Live knobs are not changed. Ranking D after seeing this table is selection on the same
October 2026 book. There is no IS. Same-day tennis, so annualized rate of return (Ann ROR)
is omitted — average days held is hours, and the house formula would explode. Fills on the
research tape are optimistic at the printed Yes. Live IOC/FOK can miss. Hsu is the worked
miss: cross fill 0.60 → target 0.15; favorite never printed 15¢ (min about 0.38).</p>
</div>

<h2>Definitions (match live B)</h2>
<ul>
<li><strong>T0 both-Yes:</strong> buy both players at the trusted game start, all-in C ≤ 1.05 HOLD.
Profit if both fill = $1 − after-fee cost. Code: <code>live_strategy_b.t0_yes_asks_send_ok</code>,
<code>C_HI=1.05</code>, <code>t0_all_in_from_asks</code>.</li>
<li><strong>Crossover:</strong> T0-dog Yes through 50¢ from below, then IOC/FOK one extra dog ticket.
Code: <code>extras_cross_ready</code> (ask &gt; 0.50), <code>CROSS=0.50</code>. Legal live send also
needs favorite Yes strictly below the dog Yes and all-in ≤ 1.05. Headline counts the 50¢ print
itself (user: extra dog is still bought; not locked without the dip).</li>
<li><strong>Dip:</strong> extra original-favorite Yes, IOC when ask ≤
<code>fav_target = $1 − cross_fill − D</code>. Live D=0.25.
<code>fav_target(0.60) = 0.15</code>, not “cross minus 25¢” (that would be 0.35). Hsu min print 0.38 → no dip.
Code: <code>live_strategy_b.fav_target</code>.</li>
<li><strong>Crossover but no dip:</strong> settled tennis with a 50¢ cross on the T0 dog and the
favorite Yes never printed at or below that game’s <code>fav_target</code> (actual cross fill if
known on the live tape; else first from-below cross price on the research tape).</li>
</ul>

<h2>Freeze</h2>
<p class="note">Click column headers to sort.</p>
{freeze}

<h2>1. Universe</h2>
<p class="note">Research tape = <code>price_memory</code> tennis moneyline (archive + dated shards)
{esc(payload['seen_min'])} through {esc(payload['seen_max'])}. Grain is platform × game
(same match on Kalshi and Polymarket is two rows). T0 is live B’s trusted clock
(occurrence, else a listed/feed time with seconds = 00). Tape-resume and clockless first-competitive
are skipped. Settlements are official venue results.</p>
<ul>
<li>Two-sided tennis moneyline books: <strong>{esc(payload['n_pairs'])}</strong>.</li>
<li>Trusted T0 with both Yes quotes: <strong>{esc(payload['n_trusted'])}</strong>
(skipped no clock {esc(payload['n_no_clock'])}).</li>
<li>Both Yes in (0.10, 0.90) and all-in C ≤ $1.05: <strong>{esc(payload['n_t0'])}</strong>
(fee unknown / Novig without a schedule {esc(payload['n_fee_unknown'])}; C over 1.05 {esc(payload['n_c_over'])};
Yes outside band {esc(payload['n_band'])}).</li>
<li>Settled in that C≤1.05 book: <strong>{esc(payload['n_t0_settled'])}</strong>.
Still open / unmatched: {esc(payload['n_t0_open'])}.</li>
<li>Q2-style tennis (trusted T0, cheaper player started under 50¢, post-start path, settled):
<strong>{esc(payload['q2_denom'])}</strong>. That is the 201-ish prior, rebuilt, tennis-only.</li>
</ul>

<h2>2. Game-start both-Yes 1–5¢ bill</h2>
<p class="note">After-fee lock profit = $1 − all-in C. Loser means the two tickets plus fees
cost more than a dollar (you pay 1–5 cents to walk in). Click column headers to sort.</p>
{bucket_tbl}

<h2>3. Headline — crossover but no dip at D=25¢</h2>
<p>On the C≤1.05 settled research tape: <strong>{esc(h['n_cross'])}</strong> crossed 50¢;
<strong>{esc(h['n_hit'])}</strong> later printed the original favorite at or below
$1 − cross fill − 0.25; <strong>{esc(h['n_miss'])}</strong> never did
({esc(h['hit_pct'])}% hit / {esc(h['miss_pct'])}% miss).</p>
<p class="note">Live B tape (actual fills, not optimistic prints): T0 both filled
{esc(payload['live']['n_t0'])}; real 50¢ dog-cross {esc(payload['live']['n_cross'])};
dip IOC filled {esc(payload['live']['n_dip'])}; crossed with no dip fill
{esc(payload['live']['n_miss'])} (of which still waiting {esc(payload['live']['n_pending_dip'])}).
Cross fill must be &gt; 50¢ and not on the T0 favorite — some old “B complete” rows stored a
T0 fill in <code>cross_fill</code> and are not counted as crossovers.</p>
{live_sum}

<h2>4. D sweep — hit rate and EV</h2>
<p class="note">One knob: D. Same T0, same first from-below 50¢ fill, same fees.
Hit % is among crossed games. EV / T0 game includes the 1–5¢ door charge on games that never
cross. EV / crossed game includes the unhedged extra dog when they miss the dip.
EV / dipped game is only the extra-pair locks (looks great; it ignores Shimizu).
Click column headers to sort.</p>
{payload['chart_hit']}
{payload['chart_ev']}
{sweep_tbl}

<h2>5. Two books at D=25¢</h2>
<ul>
<li><strong>All crossed games</strong> (extra dog is live even without a dip):
N={esc(payload['book_cross']['n'])}, mean {esc(_money(payload['book_cross']['mean']))},
win% {esc(payload['book_cross']['win_pct_s'])}, Max DD {esc(_money(payload['book_cross']['max_dd']))}.
This is the book that contains Shimizu: extra dog pays $1 if the dog wins, else 0.</li>
<li><strong>Only games that also dipped</strong> (extra pair locked):
N={esc(payload['book_dip']['n'])}, mean {esc(_money(payload['book_dip']['mean']))}.
Quality looks high because the miss path is excluded. Do not pick D from this book alone.</li>
<li><strong>All T0-qualified settled games</strong> (door charge + extras when they happen):
N={esc(payload['book_t0']['n'])}, mean {esc(_money(payload['book_t0']['mean']))}.</li>
</ul>

<h2>6. Sensitivity — 1¢ vs 5¢ door charge</h2>
<p>Replacing every game’s T0 lock with a constant −1¢ or −5¢ <em>cannot</em> change which D
wins: T0 does not depend on D. It only slides the whole strategy up or down.
A 5¢ door charge makes the whole book worse by 4¢ versus a 1¢ door charge, on every D.</p>
<p>Splitting the crossed book by the <em>actual</em> T0 bucket can move the best D, because
those are different matches. Click column headers to sort.</p>
{sens_tbl}
<p class="note">Constant shift (same games): T0 cost 1¢ best D = {esc(payload['shift_1']['best'])}
at {esc(_money(payload['shift_1']['mean']))}; T0 cost 5¢ best D = {esc(payload['shift_5']['best'])}
at {esc(_money(payload['shift_5']['mean']))}. Rank {esc(payload['shift_move'])}.</p>

<h2>7. IS vs OOS</h2>
<p>Every T0 on this tape is October 2026, after 2024-01-01. <strong>There is no in-sample row.</strong>
We did not invent one. OOS is report-only. HOLD, do not retune live D from this page.</p>

<h2>8. Prior numbers, rebuilt not copied</h2>
{prior_tbl}
<p class="tiny">Q2 page: <a href="t0_all_games_stats.html">t0_all_games_stats.html</a>.
Sport/league T0 decile: <a href="sport_league_t0_decile_20261027.html">sport_league_t0_decile_20261027.html</a>
(win% by opening bucket, not a crossover/dip study). Prior D=25 dip fill:
<a href="../strategy_b_D25_dip_come_back_win_20261023/compare.html">strategy_b_D25_dip_come_back_win_20261023</a>.
Did not overwrite <a href="live_architecture_20261028.html">live_architecture_20261028.html</a>.</p>

<h2>9. Worked miss — Hsu / Shimizu</h2>
<p>{esc(payload['hsu_text'])}</p>

<h2>10. Crossed but no dip at D=25¢ (research tape)</h2>
<p class="note">Settled C≤1.05 books that crossed 50¢ and never printed the favorite at
<code>1 − cross_fill − 0.25</code>. Extra dog P&amp;L is the Shimizu path. Click column headers to sort.</p>
{miss_tbl}

<h2>11. Live B T0 fills</h2>
<p class="note">Actual bot fills from <code>strategy_b_watch.json</code>. Platform, side, game, game start.
Click column headers to sort.</p>
{live_tbl}

<h2>12. Per-book research tape (T0-qualified)</h2>
<p class="note">One row per platform × game in the C≤1.05 book. Combined P&amp;L is D=25¢ with fees.
Click column headers to sort.</p>
{match_tbl}

<h2>Process notes</h2>
<ul>
<li>KEEP / HOLD / DISMISS is quality versus live D=25¢ (EV / average $ / hit rate), not max N.</li>
<li>OOS softened or a neighbor looks better → HOLD, do not retune OOS.</li>
<li>Research candidate. Not gold. Not DailyRun. Live <code>tools/live_strategy_b.py</code> stays at D=0.25.</li>
<li>Acronyms: T0 is game-start both-Yes. C is the two Yes prices plus documented taker fees.
D is lock profit on the extra post-cross pair. IOC is immediate-or-cancel. FOK is fill-or-kill.
GTC is good-til-canceled (not used here). IS is in-sample; OOS is out-of-sample.
Ann ROR is annualized rate of return (omitted). PF is profit factor. Max DD is maximum drawdown.</li>
</ul>
<p class="tiny">Generator: <code>tools/_write_tennis_crossover_dip_d_sweep_20261028.py</code>. File URL:
<code>{esc(FILE_URL)}</code>. Tape lines {esc(payload['n_lines'])}; Yes-change ticks {esc(payload['n_hits'])}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def fmt_sweep_rows(sweep: list[dict]) -> list[dict]:
    out = []
    for row in sweep:
        out.append({
            "arm": row["arm"],
            "role": row["role"],
            "n_t0_settled": row["n_t0_settled"],
            "n_cross": row["n_cross"],
            "n_hit": row["n_hit"],
            "n_miss": row["n_miss"],
            "hit_rate": f"{row['hit_rate']:.1f}" if row.get("hit_rate") is not None else "",
            "median_mins": _fmt_mins(row.get("median_mins")),
            "median_gap": _px(row.get("median_gap")),
            "t0_mean": _money(row.get("t0_mean")),
            "crossed_mean": _money(row.get("crossed_mean")),
            "crossed_wr": f"{row['crossed_wr']:.1f}" if row.get("crossed_wr") is not None else "",
            "crossed_pf": f"{row['crossed_pf']:.2f}" if row.get("crossed_pf") is not None else "",
            "crossed_dd": _money(row.get("crossed_dd")),
            "dipped_mean": _money(row.get("dipped_mean")),
            "dipped_n": row.get("dipped_n") or 0,
            "note": row.get("note") or "",
        })
    return out


def best_arm(shift: list[dict]) -> dict:
    ranked = [r for r in shift if r.get("mean") is not None]
    if not ranked:
        return {"best": "", "mean": None}
    best = max(ranked, key=lambda r: r["mean"])
    return {"best": best["arm"], "mean": best["mean"]}


def main() -> int:
    if LIVE_ARCH.is_file():
        _out(f"leaving sibling alone: {LIVE_ARCH.name}")
    _out("streaming tennis price_memory")
    streamed = stream_tennis()
    series = streamed["series"]
    catalog = load_catalog()
    settlements = load_settlements()
    start_lookup = start_lookup_from(settlements, catalog)
    pairs = pair_matches(series, start_lookup)
    _out(f"pairs {len(pairs)}; attaching settlements")
    attach_pair_results(pairs, settlements)

    n_no_clock = 0
    trusted = []
    for pair in pairs:
        assign_live_b_t0(pair, start_lookup)
        if pair.get("t0_a") is None or pair.get("t0_b") is None:
            n_no_clock += 1
            continue
        mark_inplay(pair)
        trusted.append(pair)
    _out(f"trusted T0 {len(trusted)} / {len(pairs)}; skipped {n_no_clock}")

    sims = [simulate_pair(p) for p in trusted]
    n_fee_unknown = sum(1 for r in sims if r.get("fee_unknown"))
    n_c_over = sum(1 for r in sims if r.get("yes_ok") and r.get("t0_all_in") is not None and not r.get("c_ok"))
    n_band = sum(1 for r in sims if not r.get("yes_ok"))
    t0_rows = [r for r in sims if t0_qualified(r)]
    t0_settled = [r for r in t0_rows if r.get("settled")]
    t0_open = len(t0_rows) - len(t0_settled)

    # Q2 tennis (trusted T0, dog started <50, settled with a post-T0 path)
    q2_pool = [
        r for r in sims
        if r.get("dog_started_lt50") and r.get("settled") and r.get("t0_ts")
    ]
    q2_kinds = Counter(r.get("q2_kind") or "no_path" for r in q2_pool)
    q2_denom = sum(q2_kinds[k] for k in q2_kinds if k not in {"already_ge_50"})
    # already_ge_50 shouldn't be in q2_pool; denom is len(q2_pool)
    q2_denom = len(q2_pool)
    q2_any_cross = sum(1 for r in q2_pool if (r.get("q2_n_cross") or 0) >= 1 or r.get("crossed"))
    q2_multi = q2_kinds.get("multi_cross", 0)

    crossed = [r for r in t0_settled if r.get("crossed")]
    d25 = []
    for row in crossed:
        rec = (row.get("dips") or {}).get(HEADLINE_D) or {}
        d25.append((row, rec))
    n_hit = sum(1 for _row, rec in d25 if rec.get("hit"))
    n_miss = len(d25) - n_hit
    miss_rows_src = [row for row, rec in d25 if not rec.get("hit")]

    def uniq(bag: list[dict]) -> int:
        return len({game_norm(r.get("game") or "") for r in bag if r.get("game")})

    sweep = sweep_from_rows(t0_settled)
    sweep_html = fmt_sweep_rows(sweep)
    verdict, why = pick_verdict(sweep)

    ctrl = next((r for r in sweep if abs(r["d"] - LIVE_D) < 1e-12), {})
    book_t0 = summarize_pnls([
        ((r.get("dips") or {}).get(HEADLINE_D) or {}).get("pnl", {}).get("total")
        if r.get("crossed")
        else (r.get("t0_only_pnl") or {}).get("total")
        for r in t0_settled
    ])
    book_cross = summarize_pnls([
        ((r.get("dips") or {}).get(HEADLINE_D) or {}).get("pnl", {}).get("total")
        for r in crossed
    ])
    book_dip = summarize_pnls([
        ((r.get("dips") or {}).get(HEADLINE_D) or {}).get("pnl", {}).get("total")
        for r in crossed
        if ((r.get("dips") or {}).get(HEADLINE_D) or {}).get("hit")
    ])
    for book in (book_t0, book_cross, book_dip):
        wr = book.get("win_pct")
        book["win_pct_s"] = f"{wr:.1f}" if wr is not None else ""

    buckets = Counter(r.get("bucket") for r in t0_rows)
    buckets_settled = Counter(r.get("bucket") for r in t0_settled)
    bucket_rows = []
    order = [
        "1¢ profit", "2¢ profit", "3¢ profit", "4¢ profit", "5¢ profit", ">5¢ profit",
        "0¢ (even)",
        "1¢ cost", "2¢ cost", "3¢ cost", "4¢ cost", "5¢ cost",
        "loser (>$1 by >5¢)", "fee unknown",
    ]
    seen_b = set(buckets)
    for name in order + sorted(seen_b - set(order)):
        n = buckets.get(name, 0)
        if not n:
            continue
        ns = buckets_settled.get(name, 0)
        bucket_rows.append({
            "bucket": name,
            "n": n,
            "n_settled": ns,
            "pct": _pct(n, len(t0_rows)),
            "note": tiny_note(n),
        })

    q2_rows = []
    labels = [
        ("one_cross_hold", "Crossed once from below and stayed >50¢"),
        ("never_cross", "Never crossed 50¢"),
        ("cross_then_fail", "Crossed then fell back (exactly one from-below cross)"),
        ("multi_cross", "Crossed from below more than once"),
        ("no_path", "Trusted T0 but no post-T0 dog ticks"),
    ]
    for key, label in labels:
        n = q2_kinds.get(key, 0)
        q2_rows.append({
            "path": label,
            "n": n,
            "pct": _pct(n, q2_denom) if q2_denom else "",
            "note": tiny_note(n),
        })

    live = load_live_b()
    live_sum_rows = [
        {"label": "Watch rows", "n": live.get("n") or 0, "note": live.get("source") or ""},
        {"label": "T0 both Yes filled", "n": live.get("n_t0") or 0, "note": "actual venue fills"},
        {"label": "Real 50¢ dog-cross filled", "n": live.get("n_cross") or 0, "note": "cross_fill > 50¢, not T0 favorite"},
        {"label": "Dip IOC filled (D=25)", "n": live.get("n_dip") or 0, "note": "fav_ioc_sent + B complete / done"},
        {"label": "Crossed, no dip fill", "n": live.get("n_miss") or 0, "note": "includes absorbed-after-cross (Hsu)"},
        {"label": "Still waiting fav dip", "n": live.get("n_pending_dip") or 0, "note": "stage waiting_fav_dip"},
    ]

    dense = replay_dense_freeze(pairs, start_lookup)
    prior_rows = [
        {
            "src": "t0_all_games_stats Q2 (all sports, older 201)",
            "grain": "venue × game, all sports",
            "n": "201 cheaper <50¢; 85/201 (42%) multi-cross",
            "was": "Not tennis-only. Dip 46/76 was a different stamp.",
            "now": (
                f"This rebuild tennis Q2 denom {q2_denom}; multi-cross {q2_multi}/"
                f"{q2_denom} ({_pct(q2_multi, q2_denom)}%); any 50¢ cross {q2_any_cross}."
            ),
        },
        {
            "src": "Q2 live HTML (this folder)",
            "grain": "venue × game, all sports vs tennis",
            "n": "HTML on disk: 202 all-sports; tennis 154 (3.9% one-cross-hold)",
            "was": "Copied into the 28 Oct overview as 202 / 85 / 46/76.",
            "now": f"Tennis Q2 rebuilt on this tape: denom {q2_denom}. See table above.",
        },
        {
            "src": "strategy_b_D25_dip_come_back_win_20261023",
            "grain": "182 dense tennis books, 119 settled",
            "n": "46/76 (60.5%) printed original favorite ≤ $1−cross−25¢",
            "was": "Tape-resume T0; C 0.95–1.20; optimistic first print >50¢.",
            "now": (
                f"Replay matched {dense['n_matched']}/{dense['n_keys']} keys; settled "
                f"{dense['n_settled']}; cross {dense['n_cross']}; dip {dense['n_dip']}/"
                f"{dense['n_cross']} ({dense['hit_pct']}%). {dense['note']}"
            ),
        },
        {
            "src": "This page — live-B T0 + C≤1.05",
            "grain": "platform × tennis moneyline",
            "n": f"{len(crossed)} crossed / {n_miss} no dip @25¢",
            "was": "The question this stamp answers.",
            "now": f"Hit {n_hit}/{len(crossed)} ({_pct(n_hit, len(crossed))}%).",
        },
    ]

    hsu = next(
        (
            r for r in sims
            if "shimizu" in (r.get("game") or "").lower()
            and "hsu" in (r.get("game") or "").lower()
        ),
        None,
    )
    live_hsu = next(
        (
            r for r in (live.get("rows") or [])
            if "shimizu" in (r.get("game") or "").lower()
            and "hsu" in (r.get("game") or "").lower()
            and r.get("t0_both")
        ),
        None,
    )
    hsu_bits = []
    if live_hsu:
        hsu_bits.append(
            f"Live B: {live_hsu.get('game')} on {live_hsu.get('platform')}, "
            f"T0 all-in {_px(live_hsu.get('t0_all_in'))} ({live_hsu.get('bucket')}), "
            f"cross fill {_px(live_hsu.get('cross_px'))}, fav_target {_px(live_hsu.get('fav_target'))}, "
            f"stage {live_hsu.get('stage')}. {live_hsu.get('note')}"
        )
    if hsu:
        rec = (hsu.get("dips") or {}).get(HEADLINE_D) or {}
        hsu_bits.append(
            f"Research tape ({hsu.get('platform')}): T0 fav {_px(hsu.get('t0_fav'))} / dog {_px(hsu.get('t0_dog'))}, "
            f"all-in {_px(hsu.get('t0_all_in'))}, first 50¢ cross {_px(hsu.get('cross_px'))}, "
            f"target {_px(rec.get('target'))}, min fav print {_px(hsu.get('min_fav_px'))}, "
            f"hit D=25 {'yes' if rec.get('hit') else 'no'}."
        )
    if not hsu_bits:
        hsu_bits.append(
            "Hsu vs Shimizu is the definition check: fill 0.60 → target 0.15; min print 0.38 is not a dip. "
            "That row was not found as a settled C≤1.05 book on this rebuild, or the name did not match."
        )
    hsu_text = " ".join(hsu_bits)

    hit_pts = [(r["arm"], float(r["hit_rate"] or 0.0)) for r in sweep]
    ev_pts = [(r["arm"], float(r["crossed_mean"] or 0.0)) for r in sweep]
    chart_hit = svg_line(
        hit_pts, title="Hit rate vs D (among crossed, research tape)", color="#0f766e",
        y_suffix="%", highlight="D=25¢",
    )
    chart_ev = svg_line(
        ev_pts, title="EV $ per crossed game vs D (with fees, includes unhedged extra dog)",
        color="#4c1d95", y_suffix="$", highlight="D=25¢", zero_line=True,
    )

    sens = sensitivity_by_t0_bucket(t0_settled)
    sens_rows = []
    for row in sens:
        sens_rows.append({
            "bucket": row["bucket"],
            "n": row["n"],
            "best_d": row["best_d"],
            "best_mean": _money(row["best_mean"]),
            "d25_mean": _money(row["d25_mean"]),
            "moved": "yes" if row["moved"] else "no",
            "note": row["note"],
        })
    shift_1 = constant_t0_shift(t0_settled, -0.01)
    shift_5 = constant_t0_shift(t0_settled, -0.05)
    b1 = best_arm(shift_1)
    b5 = best_arm(shift_5)
    shift_move = "did not move" if b1.get("best") == b5.get("best") else "moved"

    matches = match_rows_for_html(t0_rows)
    miss_html = match_rows_for_html(miss_rows_src)
    live_html = live_rows_for_html(live)

    freeze_rows = [
        {"k": "System", "v": "B Tennis crossover (live_strategy_b.py). Research report only."},
        {"k": "T0", "v": "Trusted clock (occurrence or listed seconds=00). Both Yes in (0.10, 0.90). All-in C ≤ 1.05 HOLD."},
        {"k": "Crossover", "v": "T0-dog Yes through 50¢ from below. Extra dog at first such print (research) or live fill."},
        {"k": "Dip / D", "v": "fav_target = 1 − cross_fill − D. Live D=0.25 unchanged. Sweep 5¢…40¢."},
        {"k": "Fees", "v": "Same documented taker model as live T0 (Kalshi 0.07p(1−p), Gemini round-up cent, Poly 0.0695). Novig unknown → skip all-in."},
        {"k": "Size", "v": "1 contract. Stacking all-in<$1 is live; this page scores one pair."},
        {"k": "Fills", "v": "Research tape: optimistic at printed Yes. Live tape: strategy_b_watch fills."},
        {"k": "IS / OOS", "v": "No IS. Entire October 2026 tape is OOS vs 2024-01-01."},
        {"k": "Live knobs", "v": "Do not change D=0.25, C=1.05, GTC, second B, D NFL, leftover GTC, stake."},
        {"k": "Gold / DailyRun", "v": "No. Research candidate page."},
    ]

    headline = {
        "n_cross": len(crossed),
        "n_hit": n_hit,
        "n_miss": n_miss,
        "hit_pct": _pct(n_hit, len(crossed)),
        "miss_pct": _pct(n_miss, len(crossed)),
        "n_cross_games": uniq(crossed),
        "n_miss_games": uniq(miss_rows_src),
    }

    payload = {
        "written_at": iso_now(),
        "verdict": verdict,
        "verdict_why": why,
        "n_pairs": len(pairs),
        "n_trusted": len(trusted),
        "n_no_clock": n_no_clock,
        "n_t0": len(t0_rows),
        "n_t0_settled": len(t0_settled),
        "n_t0_open": t0_open,
        "n_fee_unknown": n_fee_unknown,
        "n_c_over": n_c_over,
        "n_band": n_band,
        "q2_denom": q2_denom,
        "n_lines": streamed.get("n_lines") or 0,
        "n_hits": streamed.get("n_hits") or 0,
        "seen_min": streamed.get("seen_min") or "",
        "seen_max": streamed.get("seen_max") or "",
        "headline": headline,
        "freeze_rows": freeze_rows,
        "bucket_rows": bucket_rows,
        "sweep_rows": sweep_html,
        "q2_rows": q2_rows,
        "live": live,
        "live_sum_rows": live_sum_rows,
        "live_match_rows": live_html,
        "match_rows": matches,
        "miss_rows": miss_html,
        "prior_rows": prior_rows,
        "hsu_text": hsu_text,
        "chart_hit": chart_hit,
        "chart_ev": chart_ev,
        "book_t0": book_t0,
        "book_cross": book_cross,
        "book_dip": book_dip,
        "sens_rows": sens_rows,
        "shift_1": b1,
        "shift_5": b5,
        "shift_move": shift_move,
        "dense": dense,
        "ctrl": ctrl,
    }
    html = build_html(payload)
    if "live_architecture_20261028.html" in PAGE.name:
        raise SystemExit("refusing to write live_architecture page")
    PAGE.write_text(html, encoding="utf-8")
    slim = {
        "written_at": payload["written_at"],
        "verdict": verdict,
        "verdict_why": why,
        "headline": headline,
        "n_pairs": payload["n_pairs"],
        "n_trusted": payload["n_trusted"],
        "n_t0": payload["n_t0"],
        "n_t0_settled": payload["n_t0_settled"],
        "q2_denom": q2_denom,
        "q2_multi": q2_multi,
        "q2_any_cross": q2_any_cross,
        "live": {
            "n_t0": live.get("n_t0"),
            "n_cross": live.get("n_cross"),
            "n_dip": live.get("n_dip"),
            "n_miss": live.get("n_miss"),
            "n_pending_dip": live.get("n_pending_dip"),
        },
        "dense": dense,
        "sweep": [
            {
                "d": r["d"],
                "hit_rate": r.get("hit_rate"),
                "n_hit": r.get("n_hit"),
                "n_miss": r.get("n_miss"),
                "t0_mean": r.get("t0_mean"),
                "crossed_mean": r.get("crossed_mean"),
                "dipped_mean": r.get("dipped_mean"),
            }
            for r in sweep
        ],
        "book_t0_mean": book_t0.get("mean"),
        "book_cross_mean": book_cross.get("mean"),
        "book_dip_mean": book_dip.get("mean"),
        "page": str(PAGE),
        "research_only": True,
        "gold": False,
        "dailrun": False,
        "live_d_unchanged": 0.25,
    }
    JSON_OUT.write_text(json.dumps(slim, indent=2, default=str) + "\n", encoding="utf-8")
    _out(f"wrote {PAGE}")
    _out(
        f"HEADLINE crossed={headline['n_cross']} no-dip={headline['n_miss']} "
        f"hit={headline['hit_pct']}% verdict={verdict}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
