"""Tennis: T0 dog Yes + GTC favorite Yes at $1 − fees − dog − D.

Report only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start a second Tennis crossover (B). Does not retune live B D=0.25,
C_HI=1.05, or E 11–49. Does not leftover-GTC on A. Does not DailyRun.
Does not rewrite dashboard.html.
"""
from __future__ import annotations

import html as html_mod
import json
import math
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
import prediction_systems as systems  # noqa: E402
import report_page_extras  # noqa: E402
from dense_inplay_yes_dip_20261021 import attach_start_sources, iso_now  # noqa: E402
from inmatch_vol_hedge_20261021 import (  # noqa: E402
    attach_pair_results,
    last_at_or_before,
    pair_matches,
)
from odds_cross_no_roi_60_70_20261020 import tiny_note  # noqa: E402
from odds_cross_winrate_20261020 import as_float, game_norm  # noqa: E402
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP, RAW_DIR as RAW  # noqa: E402
from tennis_decade_at_start_20261020 import start_lookup_from  # noqa: E402
from tennis_dual_yes_dip_no_20261021 import stream_tennis  # noqa: E402

ET = ZoneInfo("America/New_York")
STAMP_SUB = STAMP / "tennis_dog_t0_gtc_fav_d_sweep_20261030"
PAGE = STAMP / "tennis_dog_t0_gtc_fav_d_sweep_20261030.html"
JSON_OUT = STAMP_SUB / "sweep.json"
BASELINE = STAMP_SUB / "BASELINE.md"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tennis_dog_t0_gtc_fav_d_sweep_20261030.html"
)
HIST_T0 = LOCAL_STAMP / "hist" / "kalshi" / "t0"
LIVE_D = Decimal("0.25")
C_HI = Decimal("1.05")
YES_LO = 0.10
YES_HI = 0.90
DOG_LT = 0.50
PAUL_D = (0.01, 0.05, 0.10, 0.15, 0.25, 0.30, 0.40)
NEARBY_D = (0.02, 0.03, 0.04, 0.20, 0.35)
D_CENTS = tuple(sorted(set(PAUL_D) | set(NEARBY_D)))
PM_VENUES = ("kalshi", "gemini", "polymarket", "novig")
KALSHI_TENNIS_PREFIX = (
    "KXATPMATCH",
    "KXWTAMATCH",
    "KXITFMATCH",
    "KXITFWMATCH",
    "KXATPCHALLENGERMATCH",
    "KXWTACHALLENGERMATCH",
    "KXTGLMATCH",
    "KXPRESCUPMATCH",
)
VOID = {"void", "refund", "push", "cancelled", "canceled", "n/a", "na"}

ASKED = (
    "Paul: run a test. What would PnL be if we bought the tennis loser (underdog) "
    "at the beginning of the match and then put a GTC on the winner (favorite at T0) "
    "for ($1 - fees - dog - D) with D = 1c, 5c, 10c, 15c, 25c, 30c, 40c, and other "
    "nearby cents if cheap."
)
PLAIN = (
    "A Yes ticket pays $1 if that named tennis player wins the match. At first serve "
    "(T0) we buy the cheaper player — the underdog, usually under 50 cents. Then we "
    "leave a good-till-canceled buy for the favorite: if that favorite ever gets cheap "
    "enough that the two tickets plus the shops’ documented take-a-trade fees still "
    "cost less than $1 by D cents, both names pay $1 together and we lock D cents "
    "(or more if we got a better print). If that resting order never fills, we just "
    "hold the cheap player to the final: we make about a dollar minus what we paid "
    "when the dog wins, and we lose that ticket when the favorite wins. No clock to "
    "exit. One contract. This is not Tennis crossover (B), which buys both players "
    "at the start. Live B still uses a 25-cent extra-pair dip after a 50-cent "
    "crossover; this page does not change that. Skip-if-B is off here because the "
    "whole idea is the dog-then-favorite-GTC book."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value) -> str:
    return f"<td>{esc('' if value is None else value)}</td>"


def table(headers: list[tuple[str, str]], rows: list[dict], fields: list[str]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cls = ' class="total-row"' if row.get("_total") else ""
        cells = [td(row.get(field, "")) for field in fields]
        body.append(f"<tr{cls}>" + "".join(cells) + "</tr>")
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _money(value, digits: int = 3) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    if abs(number) < 0.5 * 10 ** (-digits):
        return f"{0:.{digits}f}"
    return f"{number:+.{digits}f}"


def _px(value, digits: int = 2) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _pct(part: int | float | None, whole: int | float | None, digits: int = 1) -> str:
    if part is None or not whole:
        return "—"
    return f"{100.0 * float(part) / float(whole):.{digits}f}%"


def _mean(xs: list[float]) -> float | None:
    nums = [float(x) for x in xs if x is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def venue_norm(value: str) -> str:
    name = str(value or "").strip().lower()
    if name.startswith("polymarket"):
        return "polymarket"
    return name


def is_pm_venue(value: str) -> bool:
    return venue_norm(value) in PM_VENUES


def leg_fee(venue: str, price: float | None) -> float | None:
    if price is None:
        return None
    spec = {"venue": venue_norm(venue)}
    got = live_strategy_b.t0_leg_fee(spec, Decimal(str(price)))
    if got is None:
        return None
    return float(got)


def cash_of(venue: str, price: float | None) -> float | None:
    fee = leg_fee(venue, price)
    if price is None or fee is None:
        return None
    return float(price) + float(fee)


def pair_after_fee(venue: str, dog_px: float, fav_px: float) -> float | None:
    d = cash_of(venue, dog_px)
    f = cash_of(venue, fav_px)
    if d is None or f is None:
        return None
    return d + f


def gtc_target(venue: str, dog_cash: float, d: float) -> dict | None:
    """Highest 1-cent favorite Yes p with p + fav_fee(p) <= 1 - dog_cash - D.

    That is Paul's $1 − fees − dog − D: fees are the dog-leg fee already inside
    dog_cash plus the favorite-leg fee at the resting price.
    """
    cap = 1.0 - float(dog_cash) - float(d)
    if cap < 0.01 - 1e-12:
        return None
    best = None
    spec = {"venue": venue_norm(venue)}
    for cents in range(1, 100):
        p = Decimal(cents) / Decimal(100)
        fee = live_strategy_b.t0_leg_fee(spec, p)
        if fee is None:
            continue
        all_in = float(p) + float(fee)
        if all_in <= cap + 1e-12:
            best = {
                "target": float(p),
                "fav_fee_at_target": float(fee),
                "fav_cash_at_target": all_in,
                "cap": cap,
            }
    return best


def first_gtc_fill(
    t0_fav: float,
    t0_ts: int,
    ticks: list[tuple[int, float]],
    target: float,
) -> dict | None:
    """House fill: gain price (target), or the open/print if already through."""
    if t0_fav <= target + 1e-12:
        return {
            "ts": int(t0_ts),
            "print_px": float(t0_fav),
            "fill_px": float(t0_fav),
            "how": "open_through_t0",
        }
    prev = float(t0_fav)
    first_post = True
    for ts, px in ticks:
        if ts <= t0_ts:
            continue
        price = float(px)
        if price <= target + 1e-12:
            traded_through = prev > target + 1e-12 and price < target - 1e-12
            if first_post and price < target - 1e-12:
                return {
                    "ts": int(ts),
                    "print_px": price,
                    "fill_px": price,
                    "how": "open_through_first_print",
                }
            if traded_through:
                return {
                    "ts": int(ts),
                    "print_px": price,
                    "fill_px": float(target),
                    "how": "traded_through_fill_at_target",
                }
            return {
                "ts": int(ts),
                "print_px": price,
                "fill_px": price,
                "how": "print_at_or_below_target",
            }
        prev = price
        first_post = False
    return None


def in_e_band(dog_px: float) -> bool:
    return YES_LO < float(dog_px) < DOG_LT


def b_would_take(dog_px: float, fav_px: float, pair_af: float | None) -> bool:
    if pair_af is None:
        return False
    return (
        YES_LO < float(dog_px) < YES_HI
        and YES_LO < float(fav_px) < YES_HI
        and float(pair_af) <= float(C_HI) + 1e-12
    )


def tape_winner(pair: dict) -> tuple[str | None, str]:
    """Official first (already on the pair). Else last Yes 0.99/0.01, else 0.95/0.05 absorb."""
    if pair.get("settled") and pair.get("winner") in ("a", "b"):
        return pair.get("winner"), "official"
    yes_a = pair.get("yes_a") or []
    yes_b = pair.get("yes_b") or []
    if not yes_a or not yes_b:
        return None, ""
    la = float(yes_a[-1][1])
    lb = float(yes_b[-1][1])
    if la >= 0.99 - 1e-12 and lb <= 0.01 + 1e-12:
        return "a", "tape_last_yes_01_99"
    if lb >= 0.99 - 1e-12 and la <= 0.01 + 1e-12:
        return "b", "tape_last_yes_01_99"
    if la >= 0.95 - 1e-12 and lb <= 0.05 + 1e-12:
        return "a", "tape_absorb_05_95"
    if lb >= 0.95 - 1e-12 and la <= 0.05 + 1e-12:
        return "b", "tape_absorb_05_95"
    return None, ""


def apply_tape_settlement(pairs: list[dict]) -> None:
    for pair in pairs:
        winner, src = tape_winner(pair)
        pair["settle_src"] = src
        if winner in ("a", "b"):
            pair["winner"] = winner
            pair["settled"] = True
        else:
            pair["settled"] = bool(pair.get("settled") and pair.get("winner") in ("a", "b"))
            if not pair["settled"]:
                pair["settle_src"] = pair.get("settle_src") or "pending"


def assign_trusted_t0(pair: dict, start_lookup: dict) -> None:
    attach_start_sources(pair, start_lookup)
    clock_dt, src = live_strategy_b.live_trusted_clock(pair)
    pair["t0_a"] = None
    pair["t0_b"] = None
    pair["t0_ts"] = None
    pair["t0_label"] = ""
    pair["clock_src"] = src
    pair["skip_reason"] = ""
    if clock_dt is None:
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


def summarize_pnls(pnls: list[float | None]) -> dict:
    nums = [float(x) for x in pnls if x is not None]
    out = {
        "n": len(nums),
        "wins": 0,
        "win_pct": None,
        "mean": None,
        "total": None,
        "note": tiny_note(len(nums)),
    }
    if not nums:
        return out
    wins = [x for x in nums if x > 1e-12]
    out["wins"] = len(wins)
    out["win_pct"] = 100.0 * len(wins) / len(nums)
    out["mean"] = sum(nums) / len(nums)
    out["total"] = sum(nums)
    return out


def score_arm(books: list[dict], d: float) -> dict:
    n = 0
    n_hit = 0
    n_dog_only = 0
    n_lock = 0
    n_no_target = 0
    n_no_path = 0
    pnls: list[float] = []
    wins = 0
    for book in books:
        rec = (book.get("dips") or {}).get(d) or {}
        pnl = rec.get("pnl")
        if pnl is None:
            continue
        n += 1
        pnls.append(float(pnl))
        if rec.get("hit"):
            n_hit += 1
            n_lock += 1
        else:
            n_dog_only += 1
        if rec.get("no_target"):
            n_no_target += 1
        if rec.get("no_path") and not rec.get("hit"):
            n_no_path += 1
        if float(pnl) > 1e-12:
            wins += 1
    mean = (sum(pnls) / len(pnls)) if pnls else None
    total = sum(pnls) if pnls else None
    return {
        "d": d,
        "d_cents": int(round(d * 100)),
        "n": n,
        "n_hit": n_hit,
        "n_lock": n_lock,
        "n_dog_only": n_dog_only,
        "n_no_target": n_no_target,
        "n_no_path": n_no_path,
        "hit_pct": (100.0 * n_hit / n) if n else None,
        "total_pnl": total,
        "avg_pnl": mean,
        "wins": wins,
        "win_pct": (100.0 * wins / n) if n else None,
        "note": tiny_note(n),
    }


def simulate_book(pair: dict) -> dict | None:
    venue = venue_norm(pair.get("venue") or "")
    if not is_pm_venue(venue):
        return None
    t0_a = as_float(pair.get("t0_a"))
    t0_b = as_float(pair.get("t0_b"))
    t0_ts = pair.get("t0_ts")
    if t0_a is None or t0_b is None or t0_ts is None:
        return None
    if t0_a == t0_b:
        return None
    if t0_a < t0_b:
        dog, fav = "a", "b"
        dog_px, fav_px = t0_a, t0_b
        dog_name = pair.get("side_a") or ""
        fav_name = pair.get("side_b") or ""
        fav_ticks = pair.get("yes_b") or []
    else:
        dog, fav = "b", "a"
        dog_px, fav_px = t0_b, t0_a
        dog_name = pair.get("side_b") or ""
        fav_name = pair.get("side_a") or ""
        fav_ticks = pair.get("yes_a") or []
    if dog_px >= DOG_LT - 1e-12:
        return None
    dog_fee = leg_fee(venue, dog_px)
    if dog_fee is None:
        return {
            "skip": "dog_fee_unknown",
            "venue": venue,
            "game": pair.get("game") or "",
        }
    dog_cash = float(dog_px) + float(dog_fee)
    pair_af = pair_after_fee(venue, dog_px, fav_px)
    n_post = sum(1 for ts, _px in fav_ticks if ts > int(t0_ts))
    winner = pair.get("winner")
    settled = bool(pair.get("settled") and winner in ("a", "b"))
    dog_won = bool(settled and winner == dog)
    dips = {}
    for d in D_CENTS:
        tgt = gtc_target(venue, dog_cash, d)
        rec = {
            "d": d,
            "hit": False,
            "no_target": tgt is None,
            "no_path": n_post == 0,
            "target": None if tgt is None else tgt["target"],
            "fill_px": None,
            "fill_how": "",
            "fav_cash": None,
            "pnl": None,
            "kind": "dog_only",
        }
        fill = None
        if tgt is not None:
            rec["target"] = tgt["target"]
            fill = first_gtc_fill(float(fav_px), int(t0_ts), fav_ticks, tgt["target"])
        if fill is not None and tgt is not None:
            fill_px = float(fill["fill_px"])
            fav_fee = leg_fee(venue, fill_px)
            if fav_fee is None:
                rec["kind"] = "fee_unknown_fill"
            else:
                fav_cash = fill_px + float(fav_fee)
                rec["hit"] = True
                rec["fill_px"] = fill_px
                rec["fill_how"] = fill["how"]
                rec["fav_cash"] = fav_cash
                rec["pnl"] = 1.0 - dog_cash - fav_cash
                rec["kind"] = "lock"
        elif settled:
            rec["pnl"] = (1.0 if dog_won else 0.0) - dog_cash
            rec["kind"] = "dog_only"
        dips[d] = rec
    entry_date = ""
    start = pair.get("game_start") or pair.get("start") or ""
    if start:
        entry_date = str(start)[:10]
    return {
        "game": pair.get("game") or "",
        "venue": venue,
        "dog": dog,
        "fav": fav,
        "dog_name": dog_name,
        "fav_name": fav_name,
        "dog_px": float(dog_px),
        "fav_px": float(fav_px),
        "dog_fee": float(dog_fee),
        "dog_cash": dog_cash,
        "pair_af": pair_af,
        "t0_ts": int(t0_ts),
        "t0_label": pair.get("t0_label") or "",
        "clock_src": pair.get("clock_src") or "",
        "entry_date": entry_date,
        "settled": settled,
        "winner": winner,
        "dog_won": dog_won,
        "n_post_fav": n_post,
        "e_band": in_e_band(dog_px),
        "b_would": b_would_take(dog_px, fav_px, pair_af),
        "pair_gt_105": pair_af is not None and pair_af > float(C_HI) + 1e-12,
        "path_kind": "live_tick_ask",
        "settle_src": pair.get("settle_src") or "",
        "dips": dips,
    }


def arm_rows(score: dict) -> dict:
    return {
        "d": f"{score['d_cents']}¢",
        "n": score["n"],
        "hit": _pct(score["n_hit"], score["n"]),
        "n_hit": score["n_hit"],
        "n_dog": score["n_dog_only"],
        "n_lock": score["n_lock"],
        "total": _money(score["total_pnl"]),
        "avg": _money(score["avg_pnl"]),
        "wr": _pct(score["wins"], score["n"]) if score["n"] else "—",
        "note": score["note"],
        "d_sort": score["d_cents"],
    }


def slice_books(books: list[dict], kind: str) -> list[dict]:
    if kind == "primary":
        return [b for b in books if b.get("settled")]
    if kind == "e":
        return [b for b in books if b.get("settled") and b.get("e_band")]
    if kind == "b_would":
        return [b for b in books if b.get("settled") and b.get("b_would")]
    if kind == "pair_gt_105":
        return [b for b in books if b.get("settled") and b.get("pair_gt_105")]
    if kind == "kalshi":
        return [b for b in books if b.get("settled") and b.get("venue") == "kalshi"]
    return [b for b in books if b.get("settled")]


def sweep_table(books: list[dict]) -> tuple[list[dict], list[dict]]:
    scores = [score_arm(books, d) for d in D_CENTS]
    rows = [arm_rows(s) for s in scores]
    return scores, rows


def live_knobs() -> dict:
    return {
        "b_d": str(live_strategy_b.D),
        "b_c_lo": str(live_strategy_b.C_LO),
        "b_c_hi": str(live_strategy_b.C_HI),
        "b_enabled": bool(live_strategy_b.STRATEGY_B_ENABLED),
        "e_dog_lo": str(systems.DOG_LO),
        "e_dog_hi": str(systems.DOG_HI),
        "e_skip_if_b": True,
        "unchanged": (
            live_strategy_b.D == LIVE_D
            and live_strategy_b.C_HI == C_HI
            and systems.DOG_LO == Decimal("0.10")
            and systems.DOG_HI == Decimal("0.50")
        ),
    }


def load_kalshi_hist_tennis() -> list[dict]:
    """T0 1-min yes_ask candle close. No in-play favorite path → dog-only only."""
    files = []
    if HIST_T0.is_dir():
        for path in sorted(HIST_T0.glob("KX*.jsonl")):
            stem = path.stem.upper()
            if any(stem == p or stem.startswith(p) for p in KALSHI_TENNIS_PREFIX):
                files.append(path)
    bags: dict[str, list[dict]] = defaultdict(list)
    n_lines = 0
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                n_lines += 1
                ev = str(rec.get("event_ticker") or "")
                if not ev:
                    continue
                bags[ev].append(rec)
    out = []
    n_lt2 = n_tie = n_no_dog = n_unsettled = 0
    for ev, rows in bags.items():
        by_ticker = {}
        for rec in rows:
            tick = str(rec.get("ticker") or "")
            if tick:
                by_ticker[tick] = rec
        sides = list(by_ticker.values())
        if len(sides) != 2:
            n_lt2 += 1
            continue
        a, b = sides[0], sides[1]
        pa = as_float(a.get("yes_ask"))
        pb = as_float(b.get("yes_ask"))
        if pa is None or pb is None:
            continue
        if pa == pb:
            n_tie += 1
            continue
        if pa < pb:
            dog, fav = a, b
            dog_px, fav_px = pa, pb
        else:
            dog, fav = b, a
            dog_px, fav_px = pb, pa
        if dog_px >= DOG_LT - 1e-12:
            n_no_dog += 1
            continue
        res = str(dog.get("result") or "").strip().lower()
        oth = str(fav.get("result") or "").strip().lower()
        if res in VOID or oth in VOID:
            n_unsettled += 1
            continue
        if res not in ("yes", "no") or oth not in ("yes", "no"):
            n_unsettled += 1
            continue
        dog_fee = leg_fee("kalshi", dog_px)
        if dog_fee is None:
            continue
        dog_cash = float(dog_px) + float(dog_fee)
        dog_won = res == "yes"
        pnl = (1.0 if dog_won else 0.0) - dog_cash
        out.append({
            "event": ev,
            "dog": dog.get("yes_sub_title") or "",
            "fav": fav.get("yes_sub_title") or "",
            "dog_px": dog_px,
            "fav_px": fav_px,
            "dog_cash": dog_cash,
            "dog_won": dog_won,
            "pnl": pnl,
            "e_band": in_e_band(dog_px),
            "path_kind": "kalshi_1min_yes_ask_t0_only",
            "occurrence": dog.get("occurrence") or fav.get("occurrence") or "",
        })
    _out(
        f"kalshi hist tennis events {len(bags)} lines {n_lines} dog-books {len(out)} "
        f"lt2={n_lt2} tie={n_tie} no_dog={n_no_dog} unset={n_unsettled}"
    )
    return out


def svg_avg(scores: list[dict]) -> str:
    pts = [(s["d_cents"], s["avg_pnl"]) for s in scores if s.get("avg_pnl") is not None]
    if len(pts) < 2:
        return ""
    w, h, pad = 720, 220, 36
    ys = [p[1] for p in pts]
    lo, hi = min(ys + [0.0]), max(ys + [0.0])
    if abs(hi - lo) < 1e-9:
        hi = lo + 0.01
    xs = [p[0] for p in pts]
    x0, x1 = min(xs), max(xs)

    def X(cents: float) -> float:
        return pad + (w - 2 * pad) * (cents - x0) / (x1 - x0 if x1 != x0 else 1)

    def Y(val: float) -> float:
        return h - pad - (h - 2 * pad) * (val - lo) / (hi - lo)

    zero = Y(0.0)
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{X(c):.1f},{Y(v):.1f}" for i, (c, v) in enumerate(pts)
    )
    dots = "".join(
        f'<circle cx="{X(c):.1f}" cy="{Y(v):.1f}" r="3.5" fill="#4c1d95"/>'
        f'<text x="{X(c):.1f}" y="{Y(v) - 8:.1f}" text-anchor="middle" '
        f'font-size="10" fill="#334155">{c}¢</text>'
        for c, v in pts
    )
    return (
        f'<svg class="chart" viewBox="0 0 {w} {h}" width="100%" height="220" '
        f'role="img" aria-label="Average with-fee P&amp;L versus D">'
        f'<line x1="{pad}" x2="{w - pad}" y1="{zero:.1f}" y2="{zero:.1f}" '
        f'stroke="#cbd5e1" stroke-dasharray="4 4"/>'
        f'<path d="{path}" fill="none" stroke="#4c1d95" stroke-width="2"/>'
        f"{dots}</svg>"
    )


def match_rows_html(books: list[dict], d: float, limit: int = 400) -> list[dict]:
    rows = []
    for book in books[:limit]:
        rec = (book.get("dips") or {}).get(d) or {}
        rows.append({
            "game": book.get("game") or "",
            "venue": book.get("venue") or "",
            "dog": book.get("dog_name") or "",
            "dog_px": _px(book.get("dog_px")),
            "fav": book.get("fav_name") or "",
            "fav_px": _px(book.get("fav_px")),
            "target": _px(rec.get("target")),
            "hit": "yes" if rec.get("hit") else "no",
            "fill": _px(rec.get("fill_px")),
            "how": rec.get("fill_how") or rec.get("kind") or "",
            "pnl": _money(rec.get("pnl")),
            "e": "yes" if book.get("e_band") else "no",
            "b": "yes" if book.get("b_would") else "no",
            "settle": book.get("settle_src") or "",
        })
    return rows


def formula_text() -> str:
    return (
        "dog_cash = dog_ask + documented_taker_fee(venue, dog_ask). "
        "GTC rest price = max 1-cent p in {0.01 … 0.99} such that "
        "p + documented_taker_fee(venue, p) ≤ 1 − dog_cash − D. "
        "That is $1 − fees − dog − D, with fees = dog-leg fee + favorite-leg fee "
        "at the resting price. Fill at the target (gain price) if the favorite "
        "Yes path trades through it after T0; fill at the T0/open print if that "
        "print is already at or through the target. Lock P&L = 1 − dog_cash − "
        "(fill + fav_fee(fill)). Never-fill P&L = (1 if dog wins else 0) − dog_cash. "
        "SIZE=1. No time exit. Skip-if-B off."
    )


def write_baseline(payload: dict) -> None:
    kn = payload["knobs"]
    scores = payload["primary_scores"]
    lines = [
        "# Tennis T0 dog + GTC favorite D sweep — freeze",
        "",
        f"Written {payload['written_at']}. Report only. Live B/E knobs were not patched.",
        "",
        "## What you asked",
        "",
        ASKED,
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Formula",
        "",
        formula_text(),
        "",
        "Live B `fav_target(cross_fill) = 1 − cross_fill − D` does **not** subtract",
        "fees from the resting price; `extra_pair_net_ok` checks fees at send time.",
        "This experiment **does** bake both leg fees into the GTC rest price because",
        "Paul wrote `$1 - fees - dog - D`.",
        "",
        "## Freeze",
        "",
        "- **Entry:** trusted T0 (Kalshi/Gemini occurrence or listed/feed seconds=00).",
        "  Last two-sided Yes at or before that clock, else mixed pre-start + first in-game.",
        "  Not tape-resume. Not first-competitive.",
        "- **Dog:** unique cheaper named Yes, strictly below 50¢. Ties skipped.",
        "- **Favorite:** the other named Yes on that same venue book.",
        "- **Grain:** prediction-market venue × tennis moneyline (Kalshi, Gemini,",
        "  Polymarket, Novig). Do not mix sportsbooks.",
        "- **Path:** live Yes-ask ticks from `price_memory` (archive + dated",
        "  `price_last_games` / B memory writers). Labeled `live_tick_ask`.",
        "- **Kalshi hist:** 1-minute `yes_ask` candle close at T0 only. Those files",
        "  do not store the in-play favorite path, so they are **not** used for GTC",
        "  hit tests. Poly last-trade hist is not an ask — skipped for GTC.",
        "- **Fees:** same documented taker model as live T0 (`t0_leg_fee`). Novig",
        "  without `fee_coefficient` → fee unknown → book dropped from with-fee P&L.",
        "- **D sweep:** 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40 cents.",
        "  2/3/4/20/35 are nearby cents around Paul’s list.",
        "- **Fills:** target, or open/print if the path is already through.",
        "- **Winner:** official cache first, else last Yes 0.99/0.01, else 5¢/95¢ absorb.",
        "- **Primary book:** all settled tennis T0 with dog < 50¢ (skip-if-B **off**).",
        "- **E slice:** 0.10 < dog < 0.50 (live E band; skip-if-B still off).",
        "- **B slice:** both Yes in (0.10, 0.90) and after-fee pair ≤ 1.05 vs pair > 1.05.",
        "- **SIZE:** 1 contract. No time exit. No leftover-GTC on A.",
        "- **IS / OOS:** IS = entry_date < 2024-01-01; OOS = entry_date ≥ 2024-01-01.",
        "  This tape is all 2026 — IS N=0. Same-day tennis, Ann ROR omitted.",
        "- **Selection:** do not pick a live D from this table. HOLD 25¢ on B.",
        "  If live vs hist disagree, HOLD, do not retune.",
        "",
        "## Live knobs (read, not written)",
        "",
        f"- B D = {kn['b_d']} (must stay 0.25)",
        f"- B C_LO constant = {kn['b_c_lo']} (send still uses C_HI only)",
        f"- B C_HI = {kn['b_c_hi']} (must stay 1.05)",
        f"- E dog band = ({kn['e_dog_lo']}, {kn['e_dog_hi']}) exclusive",
        f"- Unchanged this job: {kn['unchanged']}",
        "- Did not start a second B. Did not leftover-GTC on A. Did not DailyRun.",
        "- Did not rewrite dashboard.html.",
        "",
        "## Headline (primary settled book)",
        "",
    ]
    for s in scores:
        lines.append(
            f"- D={s['d_cents']}¢ N={s['n']} hit={s['n_hit']}/{s['n']} "
            f"lock={s['n_lock']} dog-only={s['n_dog_only']} "
            f"total={s['total_pnl']} avg={s['avg_pnl']} win%={s['win_pct']}"
        )
    lines.extend([
        "",
        f"HTML: `{PAGE.as_posix()}`",
        f"N trusted tennis T0 dog books: {payload.get('n_dog_books')}",
        f"N settled primary: {payload.get('n_primary')}",
        "",
    ])
    BASELINE.write_text("\n".join(lines), encoding="utf-8")


def build_html(payload: dict) -> str:
    kn = payload["knobs"]
    freeze_rows = [
        {"k": "Entry", "v": "Buy 1 Yes on the T0 dog (cheaper named Yes < 50¢) at the T0 ask, after-fee cash."},
        {"k": "GTC", "v": "Rest 1 Yes on the T0 favorite at max 1-cent p with p + fav_fee(p) ≤ 1 − dog_cash − D."},
        {"k": "Fill", "v": "Target (gain price), or T0/open print if already through. No time exit. SIZE=1."},
        {"k": "Lock / miss", "v": "Fill → both Yes, P&L = 1 − dog_cash − fav_cash. Miss → directional dog to settlement."},
        {"k": "T0", "v": "Trusted clock (occurrence or listed :00). Last two-sided Yes ≤ clock. Not tape-resume."},
        {"k": "Path", "v": "Live four-platform Yes-ask ticks (price_memory / price_last_games / B memory). Not Poly last-trade hist."},
        {"k": "Kalshi hist", "v": "1-min yes_ask T0 candle only — no in-play favorite path, so no GTC hit test. Dog-only check."},
        {"k": "Skip-if-B", "v": "Off on this research book. Third slice still shows “B would have taken the pair” vs pair > 1.05."},
        {"k": "Live B / E", "v": f"D={kn['b_d']} C_HI={kn['b_c_hi']} C_LO-constant={kn['b_c_lo']} E=({kn['e_dog_lo']},{kn['e_dog_hi']}). Unchanged={kn['unchanged']}."},
        {"k": "IS / OOS", "v": "No IS. Entire October 2026 tape is OOS vs 2024-01-01. Same-day tennis: Ann ROR omitted."},
        {"k": "Live D", "v": "Do not pick a live D from this table. HOLD 25¢ on B. If live vs hist disagree, HOLD not retune."},
    ]
    d25 = next((s for s in payload["primary_scores"] if abs(s["d"] - 0.25) < 1e-12), {})
    kpi = [
        ("N matches (settled venue books)", str(payload.get("n_primary") or 0)),
        ("Unique games", str(payload.get("n_games") or 0)),
        ("D=25¢ hit rate", _pct(d25.get("n_hit"), d25.get("n"))),
        ("D=25¢ avg with-fee P&L", _money(d25.get("avg_pnl"))),
        ("Live B/E unchanged", "yes" if kn.get("unchanged") else "CHECK"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-label">{esc(a)}</div>'
        f'<div class="kpi-value">{esc(b)}</div></div>'
        for a, b in kpi
    )
    hist = payload.get("hist") or {}
    live_k = payload.get("live_kalshi_dog_only") or {}
    hist_note = hist.get("note") or ""
    disagree = payload.get("live_vs_hist") or ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis T0 dog + GTC favorite D sweep 2026-10-30</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.hl {{ background: #fef9c3; border: 1px solid #eab308; padding: 10px 12px; margin: 0 0 1rem; }}
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
<h1>Tennis T0 dog + GTC on the favorite — D sweep</h1>
<p class="tiny">Written {esc(payload.get("written_at"))}. Click column headers to sort. Path: {esc(FILE_URL)}</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<strong>Formula.</strong> {esc(formula_text())}
</div>

<div class="ok">
<strong>Live B and E were left unchanged.</strong>
B D stays {esc(kn.get("b_d"))} (HOLD 25¢). B all-in cap C_HI stays {esc(kn.get("b_c_hi"))}.
C_LO constant in code is still {esc(kn.get("b_c_lo"))} (send does not use that floor).
E stays exclusive ({esc(kn.get("e_dog_lo"))}, {esc(kn.get("e_dog_hi"))}).
Did not start a second B. Did not leftover-GTC on A. Did not DailyRun.
Did not rewrite dashboard.html. Do not pick a live D from the table below.
</div>
<p class="note">Follow-up: same book sliced by 10¢ dog decile (0–9 … 40–49) is
<a href="{esc(DECILE_PAGE_NAME)}">{esc(DECILE_PAGE_NAME)}</a>
({esc(DECILE_FILE_URL)}).</p>

<div class="kpi-row">{kpi_html}</div>

<h2>1. Primary book — all tennis T0 with a dog under 50¢</h2>
<p class="note">Settled prediction-market venue × match. Skip-if-B is <strong>off</strong>.
Path is live Yes-ask ticks, not last-trade. Nearby cents (2, 3, 4, 20, 35) sit next to
Paul’s 1 / 5 / 10 / 15 / 25 / 30 / 40. N={esc(payload.get("n_primary"))} settled of
{esc(payload.get("n_dog_books"))} T0 dog books ({esc(payload.get("n_pending"))} pending).
Fee-unknown (mostly Novig without a coefficient) dropped: {esc(payload.get("n_fee_unknown"))}.
Unique games {esc(payload.get("n_games"))}. Tape {esc(payload.get("seen_min"))} → {esc(payload.get("seen_max"))}.
Winner is official settlement when the cache has it, else last Yes 0.99/0.01, else 5¢/95¢ absorb on the tape.</p>
<h3>Venue mix (primary)</h3>
{table(
    [("Venue", "text"), ("N", "num"), ("% of book", "num")],
    payload.get("venue_rows") or [],
    ["venue", "n", "pct"],
)}
<h3>How the winner was known (primary)</h3>
{table(
    [("Source", "text"), ("N", "num"), ("% of book", "num")],
    payload.get("settle_rows") or [],
    ["src", "n", "pct"],
)}
{table(
    [("D", "text"), ("N", "num"), ("Dip-hit %", "num"), ("Lock N", "num"),
     ("Dog-only N", "num"), ("With-fee total P&L", "num"), ("Avg with-fee P&L", "num"),
     ("Win %", "num"), ("Note", "text")],
    payload["primary_rows"],
    ["d", "n", "hit", "n_lock", "n_dog", "total", "avg", "wr", "note"],
)}
{payload.get("chart") or ""}

<h2>2. E slice — dog 11–49¢ (0.10 &lt; px &lt; 0.50)</h2>
<p class="note">Same freeze as live E’s band, but skip-if-B is still off. Live E was not retuned.</p>
{table(
    [("D", "text"), ("N", "num"), ("Dip-hit %", "num"), ("Lock N", "num"),
     ("Dog-only N", "num"), ("With-fee total P&L", "num"), ("Avg with-fee P&L", "num"),
     ("Win %", "num"), ("Note", "text")],
    payload["e_rows"],
    ["d", "n", "hit", "n_lock", "n_dog", "total", "avg", "wr", "note"],
)}

<h2>3. Pair after-fee ≤ $1.05 (“B would have taken”) vs pair &gt; $1.05</h2>
<p class="note">Not skip-if-B. B shops cheapest legs across platforms; this slice is
<strong>same-venue</strong> after-fee sum, so it is “would this venue book have cleared
B’s C≤1.05 gate,” not live B.</p>
<h3>Pair after-fee ≤ 1.05</h3>
{table(
    [("D", "text"), ("N", "num"), ("Dip-hit %", "num"), ("Lock N", "num"),
     ("Dog-only N", "num"), ("With-fee total P&L", "num"), ("Avg with-fee P&L", "num"),
     ("Win %", "num"), ("Note", "text")],
    payload["b_rows"],
    ["d", "n", "hit", "n_lock", "n_dog", "total", "avg", "wr", "note"],
)}
<h3>Pair after-fee &gt; 1.05</h3>
{table(
    [("D", "text"), ("N", "num"), ("Dip-hit %", "num"), ("Lock N", "num"),
     ("Dog-only N", "num"), ("With-fee total P&L", "num"), ("Avg with-fee P&L", "num"),
     ("Win %", "num"), ("Note", "text")],
    payload["gt105_rows"],
    ["d", "n", "hit", "n_lock", "n_dog", "total", "avg", "wr", "note"],
)}

<h2>4. Live vs Kalshi hist (dog-only — hist has no in-play GTC path)</h2>
<p class="note">Kalshi hist is a 1-minute <code>yes_ask</code> candle close at T0, labeled
candle not live tick. Those files do not cover the in-play favorite after T0, so GTC hit
tests are skipped. Poly last-trade hist is not an ask and is skipped. Dog-only here is
“bought the cheap player at T0 and held,” the miss branch of this strategy.
{esc(disagree)}</p>
{table(
    [("Book", "text"), ("N", "num"), ("Dog WR", "num"), ("Avg with-fee P&L", "num"),
     ("Total", "num"), ("Path", "text"), ("Note", "text")],
    [
        {"book": "Live Kalshi T0 dog-only (ignore GTC)", "n": live_k.get("n"),
         "wr": _pct(live_k.get("wins"), live_k.get("n")), "avg": _money(live_k.get("mean")),
         "total": _money(live_k.get("total")), "path": "live tick ask",
         "note": live_k.get("note") or ""},
        {"book": "Kalshi hist T0 dog-only", "n": hist.get("n"),
         "wr": _pct(hist.get("wins"), hist.get("n")), "avg": _money(hist.get("mean")),
         "total": _money(hist.get("total")), "path": "1-min yes_ask candle close (T0 only)",
         "note": hist_note},
    ],
    ["book", "n", "wr", "avg", "total", "path", "note"],
)}

<h2>5. Freeze</h2>
{table(
    [("Knob", "text"), ("Freeze", "text")],
    freeze_rows,
    ["k", "v"],
)}

<h2>6. Per-match at D=25¢ (primary settled, first {esc(payload.get("n_match_shown"))})</h2>
<p class="note">Headline D on this table is 25¢ so it can sit next to live B without
adopting a new live D. Click headers to sort.</p>
{table(
    [("Game", "text"), ("Venue", "text"), ("Dog", "text"), ("Dog px", "num"),
     ("Favorite", "text"), ("Fav px", "num"), ("GTC target", "num"), ("Hit", "text"),
     ("Fill", "num"), ("How", "text"), ("With-fee P&L", "num"), ("E 11–49", "text"),
     ("B pair ≤1.05", "text"), ("Winner source", "text")],
    payload["match_rows"],
    ["game", "venue", "dog", "dog_px", "fav", "fav_px", "target", "hit", "fill", "how", "pnl", "e", "b", "settle"],
)}

<p class="tiny">Sources: <code>tools/_write_tennis_dog_t0_gtc_fav_d_sweep_20261030.py</code>,
<code>live_strategy_b.t0_leg_fee</code> / <code>live_trusted_clock</code>,
<code>price_memory</code> tennis shards + archive, settlements/catalog for clocks.
BASELINE: <code>drive/paul_experiments/prediction_market_arb_exhaustive_20261017/tennis_dog_t0_gtc_fav_d_sweep_20261030/BASELINE.md</code>.
Did not print secrets. Did not commit.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


DECILE_PAGE_NAME = "tennis_dog_t0_gtc_fav_d_by_decile_20261030.html"
DECILE_FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tennis_dog_t0_gtc_fav_d_by_decile_20261030.html"
)


def load_primary_books() -> tuple[list[dict], dict]:
    """Same freeze as the D-sweep page. Research book only — no live sends."""
    streamed = stream_tennis()
    series = streamed["series"]
    n_lines = streamed.get("n_lines") or 0
    settlements = load_settlements()
    catalog = load_catalog()
    start_lookup = start_lookup_from(settlements, catalog)
    pairs = pair_matches(series, start_lookup)
    n_no_clock = 0
    trusted = []
    for pair in pairs:
        if not is_pm_venue(str(pair.get("venue") or "")):
            continue
        assign_trusted_t0(pair, start_lookup)
        if pair.get("t0_a") is None or pair.get("t0_b") is None:
            n_no_clock += 1
            continue
        trusted.append(pair)
    _out(f"trusted T0 tennis PM pairs {len(trusted)} / {len(pairs)}; no-clock {n_no_clock}")
    attach_pair_results(trusted, settlements)
    apply_tape_settlement(trusted)
    books = []
    n_fee_unknown = 0
    n_no_dog = 0
    for pair in trusted:
        rec = simulate_book(pair)
        if rec is None:
            n_no_dog += 1
            continue
        if rec.get("skip") == "dog_fee_unknown":
            n_fee_unknown += 1
            continue
        books.append(rec)
    meta = {
        "n_lines": n_lines,
        "n_pairs": len(pairs),
        "n_trusted": len(trusted),
        "n_no_clock": n_no_clock,
        "n_no_dog": n_no_dog,
        "n_fee_unknown": n_fee_unknown,
        "n_dog_books": len(books),
        "seen_min_stream": streamed.get("seen_min") or "",
        "seen_max_stream": streamed.get("seen_max") or "",
    }
    return books, meta


def self_check() -> None:
    # dog 40¢ Kalshi: fee = 0.07*0.4*0.6 = 0.0168 → 0.0168; dog_cash=0.4168
    dog_cash = 0.40 + float(live_strategy_b.t0_leg_fee({"venue": "kalshi"}, Decimal("0.40")))
    tgt = gtc_target("kalshi", dog_cash, 0.25)
    assert tgt is not None, "expected a 25c target on a 40c Kalshi dog"
    cap = 1.0 - dog_cash - 0.25
    assert tgt["target"] + tgt["fav_fee_at_target"] <= cap + 1e-9
    fill = first_gtc_fill(0.62, 100, [(110, 0.20)], tgt["target"])
    assert fill is not None and fill["how"] == "open_through_first_print"
    fill2 = first_gtc_fill(0.62, 100, [(110, 0.50), (120, 0.10)], 0.33)
    assert fill2 is not None and abs(fill2["fill_px"] - 0.33) < 1e-12
    assert live_strategy_b.D == LIVE_D
    assert live_strategy_b.C_HI == C_HI


def main() -> int:
    self_check()
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    knobs = live_knobs()
    _out(f"live knobs {knobs}")

    books, meta = load_primary_books()
    n_lines = meta.get("n_lines") or 0
    n_no_clock = meta.get("n_no_clock") or 0
    n_no_dog = meta.get("n_no_dog") or 0
    n_fee_unknown = meta.get("n_fee_unknown") or 0
    pairs_n = meta.get("n_pairs") or 0
    trusted_n = meta.get("n_trusted") or 0
    _out(
        "dog books "
        + str(Counter((b.get("venue") or "", bool(b.get("settled"))) for b in books))
    )
    primary = slice_books(books, "primary")
    e_books = slice_books(books, "e")
    b_books = slice_books(books, "b_would")
    gt_books = slice_books(books, "pair_gt_105")
    k_books = slice_books(books, "kalshi")
    pending = [b for b in books if not b.get("settled")]
    games = {game_norm(b.get("game") or "") for b in primary if b.get("game")}
    venue_counts = Counter(b.get("venue") or "" for b in primary)
    settle_counts = Counter(b.get("settle_src") or "" for b in primary)
    venue_rows = [
        {"venue": name or "(blank)", "n": n, "pct": _pct(n, len(primary))}
        for name, n in sorted(venue_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    settle_rows = [
        {"src": name or "(blank)", "n": n, "pct": _pct(n, len(primary))}
        for name, n in sorted(settle_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    p_scores, p_rows = sweep_table(primary)
    _e_scores, e_rows = sweep_table(e_books)
    _b_scores, b_rows = sweep_table(b_books)
    _g_scores, g_rows = sweep_table(gt_books)

    # Live Kalshi dog-only (ignore GTC) for hist disagreement
    k_dog_pnls = []
    k_wins = 0
    for b in k_books:
        pnl = (1.0 if b.get("dog_won") else 0.0) - float(b.get("dog_cash") or 0)
        k_dog_pnls.append(pnl)
        if b.get("dog_won"):
            k_wins += 1
    live_k = summarize_pnls(k_dog_pnls)
    live_k["wins"] = k_wins

    hist_rows = load_kalshi_hist_tennis()
    hist = summarize_pnls([r["pnl"] for r in hist_rows])
    hist["wins"] = sum(1 for r in hist_rows if r.get("dog_won"))
    hist["note"] = tiny_note(len(hist_rows)) + " T0 candle only; no GTC path"

    live_mean = live_k.get("mean")
    hist_mean = hist.get("mean")
    disagree = "HOLD 25¢ on B — this table is not a live retune."
    if live_mean is not None and hist_mean is not None:
        if (live_mean > 0) != (hist_mean > 0):
            disagree = (
                f"Live Kalshi dog-only avg {live_mean:+.3f} and hist candle dog-only "
                f"avg {hist_mean:+.3f} disagree in sign. HOLD, do not retune live B/E."
            )
        else:
            disagree = (
                f"Live Kalshi dog-only avg {live_mean:+.3f} and hist candle dog-only "
                f"avg {hist_mean:+.3f} have the same sign. Still HOLD 25¢ on B — "
                "do not pick a live D from the GTC sweep."
            )

    # tape window
    times = []
    for b in books:
        if b.get("t0_ts"):
            times.append(int(b["t0_ts"]))
    seen_min = datetime.fromtimestamp(min(times), ET).isoformat() if times else ""
    seen_max = datetime.fromtimestamp(max(times), ET).isoformat() if times else ""

    n_show = min(400, len(primary))
    payload = {
        "written_at": iso_now(),
        "knobs": knobs,
        "n_pairs": pairs_n,
        "n_trusted": trusted_n,
        "n_no_clock": n_no_clock,
        "n_no_dog": n_no_dog,
        "n_fee_unknown": n_fee_unknown,
        "n_dog_books": len(books),
        "n_primary": len(primary),
        "n_pending": len(pending),
        "n_games": len(games),
        "n_e": len(e_books),
        "n_b_would": len(b_books),
        "n_gt105": len(gt_books),
        "seen_min": seen_min,
        "seen_max": seen_max,
        "n_lines": n_lines,
        "primary_scores": p_scores,
        "primary_rows": p_rows,
        "e_rows": e_rows,
        "b_rows": b_rows,
        "gt105_rows": g_rows,
        "chart": svg_avg(p_scores),
        "hist": hist,
        "live_kalshi_dog_only": live_k,
        "live_vs_hist": disagree,
        "match_rows": match_rows_html(primary, 0.25, n_show),
        "n_match_shown": n_show,
        "venue_rows": venue_rows,
        "settle_rows": settle_rows,
        "formula": formula_text(),
        "page": str(PAGE),
        "live_b_e_unchanged": knobs["unchanged"],
    }
    write_baseline(payload)
    html = build_html(payload)
    if "dashboard.html" in PAGE.name:
        raise SystemExit("refusing to write dashboard.html")
    PAGE.write_text(html, encoding="utf-8")
    slim = {
        "written_at": payload["written_at"],
        "formula": payload["formula"],
        "n_primary": payload["n_primary"],
        "n_games": payload["n_games"],
        "n_dog_books": payload["n_dog_books"],
        "n_pending": payload["n_pending"],
        "n_fee_unknown": payload["n_fee_unknown"],
        "seen_min": seen_min,
        "seen_max": seen_max,
        "knobs": knobs,
        "live_vs_hist": disagree,
        "primary": p_scores,
        "e": [score_arm(e_books, d) for d in D_CENTS],
        "b_would": [score_arm(b_books, d) for d in D_CENTS],
        "pair_gt_105": [score_arm(gt_books, d) for d in D_CENTS],
        "hist_dog_only": {k: hist.get(k) for k in ("n", "mean", "total", "wins", "win_pct")},
        "live_kalshi_dog_only": {k: live_k.get(k) for k in ("n", "mean", "total", "wins", "win_pct")},
        "page": str(PAGE),
        "live_b_e_unchanged": knobs["unchanged"],
        "hold_b_d": 0.25,
    }
    JSON_OUT.write_text(json.dumps(slim, indent=2, default=str) + "\n", encoding="utf-8")
    _out(f"wrote {PAGE}")
    d25 = next((s for s in p_scores if abs(s["d"] - 0.25) < 1e-12), {})
    _out(
        f"PRIMARY N={len(primary)} games={len(games)} D25 hit={d25.get('n_hit')}/{d25.get('n')} "
        f"avg={d25.get('avg_pnl')} unchanged={knobs['unchanged']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
