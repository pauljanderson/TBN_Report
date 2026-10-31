"""T0 buy 1 Yes, GTC sell at +G cents, by decile / sport / bet type.

Report only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start a second Tennis crossover (B). Does not leftover-GTC on A.
Does not DailyRun. Does not retune live B D=0.25, C 51–89, D spreads, or E 11–49.
Does not rewrite dashboard.html. Does not start a second Kalshi hist pull.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import live_strategy_b  # noqa: E402
import prediction_systems as systems  # noqa: E402
import report_page_extras  # noqa: E402
import t0_all_games_stats as t0  # noqa: E402
from compare_format import format_money  # noqa: E402
from nfl_t0_type_a_collect import explode_cover_yes_sides, line_won  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP  # noqa: E402
from t0_fav_lt90_baseline_20261024 import quality, fmt_ann, fmt_pct  # noqa: E402
from write_t0_band_from_stay_above import documented_leg_fee  # noqa: E402
import _write_sport_league_t0_decile_20261027 as decile_w  # noqa: E402

ET = ZoneInfo("America/New_York")
STAMP_SUB = STAMP / "t0_buy_sell_gain_decile_sport_bet_20261030"
PAGE = STAMP / "t0_buy_sell_gain_decile_sport_bet_20261030.html"
JSON_OUT = STAMP_SUB / "summary.json"
BASELINE = STAMP_SUB / "BASELINE.md"
PARENT_HTML = STAMP / "sport_league_t0_decile_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_buy_sell_gain_decile_sport_bet_20261030.html"
)
HIST_DIR = LOCAL_STAMP / "hist"
IS_CUT = "2024-01-01"
LIVE_D = Decimal("0.25")
C_HI = Decimal("1.05")
GAIN_CENTS = (1, 2, 3, 4, 5, 10, 15, 20, 25)
HEADLINE_G = (1, 5, 10)
DECADES = decile_w.DECADES
DIST_BANDS = ("0-9", "10-19", "20-29", "30-39", "40-50")
NEAR_DEC = ("40-49", "50-59")
FAR_DEC = ("0-9", "90-99")
SLICES = (
    ("cheaper_yes", "Cheaper Yes (one named side per market, usually 0–49)"),
    ("nearest_50", "Nearest-to-50¢ Yes (fav-to-cover / the Yes closer to 50)"),
    ("named_yes", "Named Yes both sides (parent sport/league T0 decile identity)"),
)

ASKED = (
    "Paul (Fri 30 Oct 2026): i feel like this did NOT do a full analysis "
    "(this page). why? the max # Ns there are for a sport/bet type / decile combo "
    "is 60 on this report it's 5425 (sport_league_t0_decile_20261027.html). "
    "Original: thanks. let's see if we can bank on movement. "
    "theory: bets closer to 50c at the start move more. can you create a decile "
    "type report and break it down to different sports and bet types and show if "
    "we buy at the decile would we make money if we sold at gains on 1c, 5c, 10c, etc."
)
PLAIN = (
    "At the opening price of a game (T0 — the trusted kickoff clock, not a random "
    "first tick) we buy one Yes ticket in that 10-cent starting-price bucket. If "
    "the in-play Yes ask later goes up by G cents, we sell it. If it never gets "
    "there, we ride the ticket to the game result: a win pays $1, a loss pays $0. "
    "Shop take-a-trade fees come off both the buy and the sell (or only the buy "
    "if we never sell). The theory is that games sitting near a coin-flip — about "
    "50 cents — twitch more during play than 5-cent dogs or 95-cent favorites, so "
    "a resting sell at +1 / +5 / +10 cents might actually fill. Moneyline (ML) is "
    "who wins. Spread is whether a side covers a point line. Points Total is the "
    "over/under on combined score. Association of Tennis Professionals (ATP), "
    "Women’s Tennis Association (WTA), and International Tennis Federation (ITF) "
    "are tennis tours; National Football League (NFL), college football (CFB), "
    "National Basketball Association (NBA), National Hockey League (NHL), English "
    "Premier League (EPL), Ultimate Fighting Championship (UFC), and Professional "
    "Golfers’ Association (PGA) are whatever the books actually have. Live B/C/D/E "
    "bands were not changed from this table."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def decile_of(px) -> str | None:
    return decile_w.decile_of(px)


def dist50_band(px) -> str | None:
    if px is None:
        return None
    try:
        d = abs(float(px) - 0.50) * 100.0
    except (TypeError, ValueError):
        return None
    if d < 10.0 - 1e-9:
        return "0-9"
    if d < 20.0 - 1e-9:
        return "10-19"
    if d < 30.0 - 1e-9:
        return "20-29"
    if d < 40.0 - 1e-9:
        return "30-39"
    return "40-50"


def kind_label(kind: str) -> str:
    return decile_w.kind_label(kind)


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
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f"<table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def money(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        return format_money(value)
    except Exception:
        return f"{float(value):+.4f}"


def _mean(xs: list[float]) -> float | None:
    nums = [float(x) for x in xs if x is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _pct(part, whole, digits: int = 1) -> str:
    if part is None or not whole:
        return "—"
    return f"{100.0 * float(part) / float(whole):.{digits}f}%"


def first_gain_fill(
    t0_px: float,
    t0_ts: int,
    ticks: list[tuple[int, float]],
    target: float,
) -> dict | None:
    """Sell fill: gain price (target), or the open/print if the path opens through."""
    if target <= float(t0_px) + 1e-12:
        return {
            "ts": int(t0_ts),
            "print_px": float(t0_px),
            "fill_px": float(t0_px),
            "how": "open_through_t0",
        }
    prev = float(t0_px)
    first_post = True
    for ts, px in ticks:
        if int(ts) <= int(t0_ts):
            continue
        price = float(px)
        if price >= target - 1e-12:
            traded_through = prev < target - 1e-12 and price > target + 1e-12
            if first_post and price > target + 1e-12:
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
                "how": "print_at_or_above_target",
            }
        prev = price
        first_post = False
    return None


def gain_pnl(venue: str, entry: float, fill_px, *, won: bool, hit: bool) -> dict | None:
    buy_fee = documented_leg_fee(venue, entry)
    if buy_fee is None or entry is None:
        return None
    buy_cash = float(Decimal(str(entry)) + Decimal(str(buy_fee)))
    if hit:
        if fill_px is None:
            return None
        sell_fee = documented_leg_fee(venue, fill_px)
        if sell_fee is None:
            return None
        proceeds = float(Decimal(str(fill_px)) - Decimal(str(sell_fee)))
        pnl = proceeds - buy_cash
        return {
            "pnl": pnl,
            "buy_cash": buy_cash,
            "buy_fee": float(buy_fee),
            "sell_fee": float(sell_fee),
            "proceeds": proceeds,
            "cost": buy_cash,
        }
    pnl = (1.0 - buy_cash) if won else (-buy_cash)
    return {
        "pnl": pnl,
        "buy_cash": buy_cash,
        "buy_fee": float(buy_fee),
        "sell_fee": 0.0,
        "proceeds": 1.0 if won else 0.0,
        "cost": buy_cash,
    }


def move_stats(t0_px: float, ticks: list[tuple[int, float]]) -> dict:
    if not ticks:
        return {
            "n_post": 0, "max_up": None, "max_down": None, "range": None, "last": None,
        }
    xs = [float(px) for _ts, px in ticks]
    hi, lo, last = max(xs), min(xs), xs[-1]
    t0v = float(t0_px)
    return {
        "n_post": len(ticks),
        "max_up": max(0.0, hi - t0v),
        "max_down": max(0.0, t0v - lo),
        "range": hi - lo,
        "last": last,
    }


def _side(**kwargs) -> dict:
    """Test helper / compact side defaults."""
    row = {
        "sport": "tennis",
        "league": "ATP",
        "kind": "moneyline",
        "number": "",
        "venue": "kalshi",
        "game": "",
        "game_n": "",
        "letter": "a",
        "name": "",
        "t0_px": 0.40,
        "t0_ts": 0,
        "end_ts": 0,
        "won": False,
        "entry_date": "2026-10-20",
        "ticks": [],
        "days": 0.0,
        "opened": None,
        "closed": None,
        "slice": "",
    }
    row.update(kwargs)
    return row


def market_key(side: dict) -> tuple:
    return (
        str(side.get("sport") or "").lower(),
        str(side.get("game_n") or side.get("game") or ""),
        str(side.get("kind") or "moneyline"),
        str(side.get("number") or ""),
    )


def pick_named_yes(sides: list[dict]) -> list[dict]:
    out = []
    for side in sides:
        row = dict(side)
        row["slice"] = "named_yes"
        out.append(row)
    return out


def pick_cheaper(sides: list[dict]) -> list[dict]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for side in sides:
        bags[market_key(side)].append(side)
    out = []
    for group in bags.values():
        ordered = sorted(group, key=lambda s: (float(s["t0_px"]), str(s.get("letter") or "")))
        lo = ordered[0]
        if len(ordered) >= 2:
            hi = ordered[-1]
            if float(hi["t0_px"]) - float(lo["t0_px"]) <= 1e-12:
                continue
        elif float(lo["t0_px"]) >= 0.50 - 1e-12:
            continue
        row = dict(lo)
        row["slice"] = "cheaper_yes"
        out.append(row)
    return out


def pick_nearest_50(sides: list[dict]) -> list[dict]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for side in sides:
        bags[market_key(side)].append(side)
    out = []
    for group in bags.values():
        best = min(
            group,
            key=lambda s: (
                abs(int(round(float(s["t0_px"]) * 100.0)) - 50),
                float(s["t0_px"]),
                str(s.get("letter") or ""),
            ),
        )
        row = dict(best)
        row["slice"] = "nearest_50"
        out.append(row)
    return out


def post_ticks(book: dict) -> list[tuple[int, float]]:
    letter = str(book.get("_side_letter") or book.get("fav") or "a")
    bag = book.get("yes_a") or [] if letter != "b" else (book.get("yes_b") or [])
    t0_ts = book.get("t0_ts")
    if t0_ts is None:
        return []
    end_ts = book.get("end_ts")
    out = []
    for ts, px in bag:
        if int(ts) <= int(t0_ts):
            continue
        if end_ts is not None and int(ts) > int(end_ts):
            continue
        try:
            price = float(px)
        except (TypeError, ValueError):
            continue
        if 0.0 < price < 1.0:
            out.append((int(ts), price))
    out.sort(key=lambda row: row[0])
    return out


def compact_side(book: dict) -> dict | None:
    if book.get("void"):
        return None
    won = line_won(book)
    if won is None:
        return None
    px = book.get("t0_fav")
    if px is None:
        px = book.get("t0_a") if str(book.get("_side_letter") or "") != "b" else book.get("t0_b")
    if px is None:
        return None
    t0_ts = book.get("t0_ts")
    if t0_ts is None:
        return None
    venue = str(book.get("venue") or "")
    if documented_leg_fee(venue, px) is None:
        return None
    ticks = post_ticks(book)
    opened = datetime.fromtimestamp(int(t0_ts), ET)
    end_ts = book.get("end_ts") or t0_ts
    closed = datetime.fromtimestamp(int(end_ts), ET)
    days = max(0.0, (int(end_ts) - int(t0_ts)) / 86400.0)
    sport = str(book.get("sport") or "unknown")
    return {
        "sport": sport,
        "league": decile_w.league_of_side(book),
        "kind": str(book.get("kind") or "moneyline"),
        "number": str(book.get("number") or ""),
        "venue": venue,
        "game": str(book.get("game") or ""),
        "game_n": str(book.get("game_n") or book.get("game") or ""),
        "letter": str(book.get("_side_letter") or ""),
        "name": str(book.get("fav_name") or ""),
        "t0_px": float(px),
        "t0_ts": int(t0_ts),
        "end_ts": int(end_ts),
        "won": bool(won),
        "entry_date": opened.date().isoformat(),
        "ticks": ticks,
        "days": days,
        "opened": opened,
        "closed": closed,
        "decile": decile_of(px),
        "dist50": dist50_band(px),
        "move": move_stats(float(px), ticks),
        "n_venues": int(book.get("_n_venues") or 1),
    }


def live_knobs() -> dict:
    e_lo = systems.DOG_LO
    e_hi = systems.DOG_HI
    return {
        "b_d": str(live_strategy_b.D),
        "b_c_lo": str(live_strategy_b.C_LO),
        "b_c_hi": str(live_strategy_b.C_HI),
        "c_band": "51–89 (YES_LO exclusive 0.50 to YES_HI 0.90)",
        "d_spreads": "live D spreads unchanged",
        "e_dog_lo": str(e_lo),
        "e_dog_hi": str(e_hi),
        "unchanged": (
            live_strategy_b.D == LIVE_D
            and live_strategy_b.C_HI == C_HI
            and e_lo == Decimal("0.10")
            and e_hi == Decimal("0.50")
        ),
    }


def simulate_side(side: dict, g_cents) -> dict | None:
    entry = float(side["t0_px"])
    venue = side["venue"]
    won = bool(side["won"])
    opened = side.get("opened")
    closed = side.get("closed")
    days = float(side.get("days") or 0.0)
    if g_cents == "hold":
        rec = gain_pnl(venue, entry, None, won=won, hit=False)
        if rec is None:
            return None
        rec.update({
            "g": "hold",
            "kind": "hold_to_settle",
            "hit": False,
            "fill_px": None,
            "fill_how": "",
            "won_flag": rec["pnl"] > 1e-12,
            "entry_date": side.get("entry_date") or "",
            "opened": opened,
            "closed": closed,
            "days": days,
            "pnl_d": rec["pnl"],
            "pnl": (rec["pnl"] / rec["cost"] * 100.0) if rec["cost"] else None,
            "cost": rec["cost"],
            "sport": side.get("sport") or "",
            "decile": side.get("decile") or "",
        })
        return rec
    g = int(g_cents)
    target = entry + g / 100.0
    ticks = side.get("ticks") or []
    if not ticks:
        return {
            "g": g,
            "kind": "t0_only_skip_gtc",
            "hit": False,
            "pnl": None,
            "n_path": 0,
        }
    if target >= 0.995 - 1e-12:
        return {
            "g": g,
            "kind": "target_off_board",
            "hit": False,
            "pnl": None,
            "n_path": len(ticks),
        }
    fill = first_gain_fill(entry, int(side["t0_ts"]), ticks, target)
    if fill is None:
        rec = gain_pnl(venue, entry, None, won=won, hit=False)
        if rec is None:
            return None
        kind = "settle_miss"
        hit = False
        fill_px = None
        how = ""
        fill_ts = int(side.get("end_ts") or side["t0_ts"])
    else:
        rec = gain_pnl(venue, entry, fill["fill_px"], won=won, hit=True)
        if rec is None:
            return None
        kind = "take_profit"
        hit = True
        fill_px = fill["fill_px"]
        how = fill["how"]
        fill_ts = int(fill["ts"])
        closed = datetime.fromtimestamp(fill_ts, ET)
        days = max(0.0, (fill_ts - int(side["t0_ts"])) / 86400.0)
    rec.update({
        "g": g,
        "kind": kind,
        "hit": hit,
        "fill_px": fill_px,
        "fill_how": how,
        "won_flag": rec["pnl"] > 1e-12,
        "entry_date": side.get("entry_date") or "",
        "opened": opened,
        "closed": closed,
        "days": days,
        "pnl_d": rec["pnl"],
        "pnl": (rec["pnl"] / rec["cost"] * 100.0) if rec["cost"] else None,
        "cost": rec["cost"],
        "sport": side.get("sport") or "",
        "decile": side.get("decile") or "",
        "n_path": len(ticks),
    })
    return rec


def score_trades(trades: list[dict], arm: str) -> dict:
    usable = [t for t in trades if t.get("pnl") is not None or t.get("pnl_d") is not None]
    for t in usable:
        t.setdefault("won", t.get("won_flag"))
    if not usable:
        return {
            "n": 0, "n_hit": 0, "n_miss": 0, "n_skip": 0,
            "hit_pct": None, "avg_pnl": None, "pnl_sum": None, "win_pct": None,
            "ann_ror": None, "ann_ror_is": None, "ann_ror_oos": None,
            "ann_note": "no closed with-fee trades",
            "is_note": "n/a",
            "n_is": 0, "n_oos": 0,
        }
    q = quality(usable, arm_id=arm, label=arm, grain="t0-yes-1")
    n_hit = sum(1 for t in usable if t.get("hit"))
    n_miss = sum(1 for t in usable if t.get("kind") == "settle_miss")
    n_skip = sum(1 for t in trades if t.get("kind") in ("t0_only_skip_gtc", "target_off_board"))
    n_is = int(q.get("n_is") or 0)
    q_pub = {
        "n": int(q.get("n") or 0),
        "n_hit": n_hit,
        "n_miss": n_miss,
        "n_skip": n_skip,
        "hit_pct": (100.0 * n_hit / len(usable)) if usable else None,
        "avg_pnl": q.get("mean"),
        "pnl_sum": q.get("pnl_sum"),
        "win_pct": q.get("win_pct"),
        "n_win": q.get("n_win"),
        "pf": q.get("pf"),
        "avg_pnl_pct": q.get("avg_pnl_pct"),
        "avg_pnl_pct_wo_max": q.get("avg_pnl_pct_wo_max"),
        "expectancy": q.get("expectancy"),
        "avg_win": q.get("avg_win"),
        "avg_loss": q.get("avg_loss"),
        "avg_days": q.get("avg_days"),
        "ann_ror": q.get("ann_ror"),
        "ann_ror_is": q.get("ann_ror_is"),
        "ann_ror_oos": q.get("ann_ror_oos"),
        "ann_note": q.get("ann_note") or "",
        "is_note": q.get("is_note") or "",
        "n_is": n_is,
        "n_oos": int(q.get("n_oos") or 0),
        "max_dd_d": q.get("max_dd_d"),
        "max_dd": q.get("max_dd"),
        "calmar": q.get("calmar"),
        "sharpe": q.get("sharpe"),
        "median_cost": q.get("median_cost"),
    }
    return q_pub


def path_sides(sides: list[dict]) -> list[dict]:
    return [s for s in sides if (s.get("ticks") or s.get("move", {}).get("n_post"))]


def attach_sims(sides: list[dict]) -> None:
    """Walk each in-play path once; cache hold + every G."""
    for side in sides:
        if side.get("_sims"):
            continue
        sims = {"hold": simulate_side(side, "hold")}
        for g in GAIN_CENTS:
            sims[g] = simulate_side(side, g)
        side["_sims"] = sims


def score_gain(sides: list[dict], g_cents, *, arm: str) -> dict:
    eligible = path_sides(sides)
    attach_sims(eligible)
    trades = []
    n_skip = 0
    for side in eligible:
        rec = (side.get("_sims") or {}).get(g_cents)
        if rec is None:
            rec = simulate_side(side, g_cents)
        if rec is None:
            continue
        if rec.get("kind") in ("t0_only_skip_gtc", "target_off_board"):
            n_skip += 1
            continue
        trades.append(rec)
    scored = score_trades(trades, arm)
    scored["n_skip"] = n_skip
    scored["n_universe"] = len(sides)
    scored["n_path"] = len(path_sides(sides))
    scored["g"] = g_cents
    return scored


def group_key_sides(sides: list[dict], *, sport=None, league=None, kind=None, decile=None,
                    dist=None, near=None, far=None) -> list[dict]:
    out = []
    for side in sides:
        if sport is not None and str(side.get("sport") or "") != sport:
            continue
        if league is not None and str(side.get("league") or "") != league:
            continue
        if kind is not None and str(side.get("kind") or "") != kind:
            continue
        if decile is not None and str(side.get("decile") or "") != decile:
            continue
        if dist is not None and str(side.get("dist50") or "") != dist:
            continue
        band = str(side.get("decile") or "")
        if near is True and band not in NEAR_DEC:
            continue
        if far is True and band not in FAR_DEC:
            continue
        out.append(side)
    return out


def move_summary(sides: list[dict]) -> dict:
    path = path_sides(sides)
    ups = [s["move"]["max_up"] for s in path if s.get("move") and s["move"].get("max_up") is not None]
    downs = [s["move"]["max_down"] for s in path if s.get("move") and s["move"].get("max_down") is not None]
    ranges = [s["move"]["range"] for s in path if s.get("move") and s["move"].get("range") is not None]
    hit5 = sum(1 for s in path if (s.get("move") or {}).get("max_up") is not None
               and s["move"]["max_up"] >= 0.05 - 1e-12)
    hit10 = sum(1 for s in path if (s.get("move") or {}).get("max_up") is not None
                and s["move"]["max_up"] >= 0.10 - 1e-12)
    n = len(path)
    return {
        "n": len(sides),
        "n_path": n,
        "avg_max_up": _mean(ups),
        "avg_max_down": _mean(downs),
        "avg_range": _mean(ranges),
        "hit5_pct": (100.0 * hit5 / n) if n else None,
        "hit10_pct": (100.0 * hit10 / n) if n else None,
    }


def hist_census() -> dict:
    cov_path = HIST_DIR / "coverage.json"
    k_path = HIST_DIR / "books_kalshi.json"
    p_path = HIST_DIR / "books_poly.json"
    coverage = decile_w.load_json_list(cov_path)
    k_sides = decile_w.load_json_list(k_path)
    p_sides = decile_w.load_json_list(p_path)
    t0_dir = HIST_DIR / "kalshi" / "t0"
    n_t0_lines = 0
    n_with_path = 0
    candle_ns = []
    if t0_dir.is_dir():
        for path in t0_dir.glob("*.jsonl"):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    n_t0_lines += 1
                    try:
                        rec = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if rec.get("path") or rec.get("candles") or rec.get("yes_ask_path"):
                        n_with_path += 1
                    n_c = rec.get("n")
                    if n_c is not None:
                        try:
                            candle_ns.append(int(n_c))
                        except (TypeError, ValueError):
                            pass
    k_n = len(k_sides)
    k_settled = sum(1 for r in k_sides if r.get("settled") and r.get("fav_won") is not None)
    p_n = len(p_sides)
    span = ""
    dates = [str(r.get("entry_date") or "") for r in k_sides if r.get("entry_date")]
    if dates:
        span = f"{min(dates)} .. {max(dates)}"
    is_n = sum(1 for r in k_sides if str(r.get("entry_date") or "9999") < IS_CUT)
    oos_n = sum(1 for r in k_sides if str(r.get("entry_date") or "") >= IS_CUT)
    sports = sorted({str(r.get("sport") or "") for r in k_sides if r.get("sport")})
    kinds = sorted({str(r.get("kind") or "") for r in k_sides if r.get("kind")})
    return {
        "kalshi_n_sides": k_n,
        "kalshi_n_settled": k_settled,
        "kalshi_span": span,
        "kalshi_is": is_n,
        "kalshi_oos": oos_n,
        "kalshi_sports": sports,
        "kalshi_kinds": kinds,
        "poly_n_sides": p_n,
        "poly_price_kind": "CLOB last-trade (not Yes ask) — skipped for GTC",
        "coverage_n": len(coverage),
        "t0_jsonl_lines": n_t0_lines,
        "t0_jsonl_with_path": n_with_path,
        "median_candle_n": (
            sorted(candle_ns)[len(candle_ns) // 2] if candle_ns else None
        ),
        "note": (
            "Kalshi hist stores 1-min yes_ask.close at T0 only. In-play candles were "
            "fetched (n on the T0 row is the API candle count) but the path was not "
            "kept, so GTC hit tests are skipped. Did not start a second leftover pull."
        ),
    }


def live_sides_from_books(books: list[dict]) -> list[dict]:
    exploded = explode_cover_yes_sides(books)
    picked = decile_w.pick_one_side(exploded)
    out = []
    for book in picked:
        row = compact_side(book)
        if row and row.get("decile"):
            out.append(row)
    return out


def ann_cell(rec: dict, key: str) -> str:
    if rec.get("ann_note") and rec.get(key) is None:
        return "omitted (same-day)"
    if key == "ann_ror_is" and rec.get("n_is") == 0:
        return rec.get("is_note") or "n/a (no IS)"
    val = rec.get(key)
    if val is None:
        return rec.get("ann_note") or "—"
    return fmt_ann(val)


def metric_row(label: str, rec: dict, extra: dict | None = None) -> dict:
    row = {
        "label": label,
        "n": rec.get("n") or 0,
        "n_path": rec.get("n_path") or "",
        "n_hit": rec.get("n_hit") or 0,
        "n_miss": rec.get("n_miss") or 0,
        "hit_pct": fmt_pct(rec.get("hit_pct")) if rec.get("n") else "—",
        "avg_pnl": money(rec.get("avg_pnl")) if rec.get("n") else "—",
        "pnl_sum": money(rec.get("pnl_sum")) if rec.get("n") else "—",
        "win_pct": fmt_pct(rec.get("win_pct")) if rec.get("n") else "—",
        "pf": f"{rec['pf']:.2f}" if rec.get("pf") is not None else "—",
        "avg_pct": f"{rec['avg_pnl_pct']:.1f}" if rec.get("avg_pnl_pct") is not None else "—",
        "wo_max": (
            f"{rec['avg_pnl_pct_wo_max']:.1f}"
            if rec.get("avg_pnl_pct_wo_max") is not None else "—"
        ),
        "ann": ann_cell(rec, "ann_ror"),
        "ann_is": ann_cell(rec, "ann_ror_is"),
        "ann_oos": ann_cell(rec, "ann_ror_oos"),
        "max_dd": money(rec.get("max_dd_d")) if rec.get("max_dd_d") is not None else "—",
        "n_is": rec.get("n_is") or 0,
        "n_oos": rec.get("n_oos") or 0,
        "note": rec.get("ann_note") or rec.get("is_note") or "",
    }
    if extra:
        row.update(extra)
    return row


METRIC_HEADERS = [
    ("Slice", "text"),
    ("N", "num"),
    ("Take-profit N", "num"),
    ("Settle-miss N", "num"),
    ("Hit%", "num"),
    ("Avg P&L", "num"),
    ("Total P&L", "num"),
    ("Win%", "num"),
    ("PF", "num"),
    ("Avg P&L %", "num"),
    ("AVG_PNL_PCT_WO_MAX", "num"),
    ("Ann ROR full", "num"),
    ("Ann ROR IS", "num"),
    ("Ann ROR OOS", "num"),
    ("Max DD $", "num"),
    ("N IS", "num"),
    ("N OOS", "num"),
    ("Note", "text"),
]
METRIC_FIELDS = [
    "label", "n", "n_hit", "n_miss", "hit_pct", "avg_pnl", "pnl_sum", "win_pct",
    "pf", "avg_pct", "wo_max", "ann", "ann_is", "ann_oos", "max_dd", "n_is", "n_oos",
    "note",
]


def theory_yes_no(near_move: dict, far_move: dict) -> tuple[str, str]:
    a = near_move.get("avg_range")
    b = far_move.get("avg_range")
    au = near_move.get("avg_max_up")
    bu = far_move.get("avg_max_up")
    if a is None or b is None:
        return "n/a", "Not enough in-play path to compare range."
    more = a > b + 1e-12
    word = "yes" if more else "no"
    detail = (
        f"|T0−50¢| 0–9¢ (near coin-flip) avg range {a*100:.1f}¢ vs "
        f"|T0−50¢| 40–50¢ (far) avg range {b*100:.1f}¢"
    )
    if au is not None and bu is not None:
        detail += (
            f"; avg max up {au*100:.1f}¢ vs {bu*100:.1f}¢"
        )
    return word, detail


def freeze_md(payload: dict) -> str:
    kn = payload["knobs"]
    hist = payload["hist"]
    theory = payload["theory"]
    return "\n".join([
        "# T0 buy then sell at +G — freeze",
        "",
        f"Written {payload['written_at']}. Report only. Live B/C/D/E knobs were not patched.",
        "",
        "## What you asked",
        "",
        ASKED,
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Freeze",
        "",
        "- **Entry:** 1 contract at T0 Yes ask (after-fee cash on the fill). House T0 =",
        "  later(occurrence, listed :00, next-day live start) via `t0_all_games_stats.pick_trusted_clock`",
        "  — same as sport_league_t0_decile / B / C / D. Last two-sided Yes at or before that",
        "  clock, else mixed pre-start + first in-game. Not tape-resume. Not first-competitive.",
        "- **Primary identity:** named cheaper Yes per market at T0 (after one-venue-per-side",
        "  pick, same as `sport_league_t0_decile`). Fills 0–49. Ties skipped.",
        "- **Nearest-to-50¢:** the Yes closer to 50¢ (fav-to-cover). Equal distance → cheaper.",
        "  Fills 40–49 and 50–59. Labeled `nearest_50`.",
        "- **Named Yes both sides:** parent decile identity so 90–99 exists for far-from-50.",
        "- **Decile:** 0-based 10¢ buckets on the T0 Yes **ask before fee** (house `decile_of`).",
        "- **Exit:** sell at first in-play Yes-ask print ≥ entry + G. Fill at the gain price,",
        "  or at the open if the path opens through it. No time exit. Never-hit → hold to",
        "  settlement (binary 0/1). With-fee P&L on both take-profit and settle-miss.",
        "- **G:** 1, 2, 3, 4, 5, 10, 15, 20, 25 cents. 2/3/4 are nearby cheap cents.",
        "- **Fees:** Kalshi 0.07×p×(1−p) both legs; Gemini ceil-cent; Polymarket theta.",
        "  Novig fee unknown → skip (not treated as zero). Do not double-count. Do not mix sportsbooks.",
        "- **Path:** live four-platform Yes-ask ticks (`price_memory` / `price_last_games`).",
        "  Labeled `live_tick_ask`. Oct 2026 tape only.",
        f"- **Kalshi hist:** T0-only 1-min yes_ask.close. jsonl lines={hist.get('t0_jsonl_lines')},",
        f"  with stored path={hist.get('t0_jsonl_with_path')} (skip GTC). sides={hist.get('kalshi_n_sides')}.",
        "  Did not start a second leftover pull (387121 already finished).",
        "- **Poly hist:** last-trade, not ask — skipped for GTC hit tests.",
        "- **One change:** EXIT-at-gain vs hold-to-settle on the same T0 identity. Not a live-knob retune.",
        "- **IS / OOS:** entry_date < 2024-01-01 vs ≥ 2024-01-01. Live tape is Oct 2026 — IS N=0.",
        "  Never retune on OOS. If OOS softens, HOLD.",
        "- **Selection:** do not pick a live band or G from this table. HOLD C/D/E/B.",
        "",
        "## Live knobs (read, not written)",
        "",
        f"- B D = {kn['b_d']} (HOLD 0.25)",
        f"- B C_HI = {kn['b_c_hi']} (HOLD 1.05)",
        f"- C band = {kn['c_band']} HOLD",
        f"- D spreads = {kn['d_spreads']}",
        f"- E dog = ({kn['e_dog_lo']}, {kn['e_dog_hi']}) exclusive (11–49¢) HOLD",
        f"- Unchanged this job: {kn['unchanged']}",
        "",
        "## Theory headline",
        "",
        f"- Near-50 move more? **{theory.get('verdict')}**. {theory.get('detail')}",
        "",
        "## Do not",
        "",
        "- Do not pick G or a live band from this page.",
        "- Do not DailyRun. Do not leftover-GTC A. Do not start a second B.",
        "",
    ])


def svg_range(rows: list[dict]) -> str:
    pts = [(r["band"], r["avg_range"]) for r in rows if r.get("avg_range") is not None]
    if len(pts) < 2:
        return ""
    w, h, pad = 720, 220, 40
    ys = [p[1] for p in pts]
    lo, hi = min(ys + [0.0]), max(ys + [0.0])
    if abs(hi - lo) < 1e-9:
        hi = lo + 0.01

    def X(i: int) -> float:
        return pad + (w - 2 * pad) * i / max(1, len(pts) - 1)

    def Y(val: float) -> float:
        return h - pad - (h - 2 * pad) * (val - lo) / (hi - lo)

    path = " ".join(
        f"{'M' if i == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for i, (_b, v) in enumerate(pts)
    )
    dots = "".join(
        f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.5" fill="#4c1d95"/>'
        f'<text x="{X(i):.1f}" y="{Y(v) - 8:.1f}" text-anchor="middle" '
        f'font-size="10" fill="#334155">{esc(b)}</text>'
        for i, (b, v) in enumerate(pts)
    )
    return (
        f'<svg class="chart" viewBox="0 0 {w} {h}" width="100%" height="220" '
        f'role="img" aria-label="Average in-play range versus distance to 50 cents">'
        f'<path d="{path}" fill="none" stroke="#4c1d95" stroke-width="2"/>'
        f"{dots}</svg>"
    )


def write_html(payload: dict) -> str:
    kn = payload["knobs"]
    hist = payload["hist"]
    theory = payload["theory"]
    now = payload["written_at"]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>T0 buy then sell at +G — decile / sport / bet type</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout.warn {{ background: #fff7ed; border-color: #fdba74; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
.chart {{ max-width: 720px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>T0 buy then sell at +G cents</h1>
<p class="note">Written {esc(now)}. Live B D stays {esc(kn.get('b_d'))} (HOLD 25¢).
C 51–89, D spreads, and E 11–49 were not retuned. Did not pick a G from this table.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{PLAIN}</p></div>
<div class="callout warn" id="why-60-vs-5425">
<h2>Why max N is 60 here vs 5,425 on the sport/league page</h2>
<p><strong>This page is live-tape only. It is not the 5,425 hist book.</strong></p>
<p>The 5,425 cell is tennis moneyline 90–99 on
<a href="sport_league_t0_decile_20261027.html">sport_league_t0_decile_20261027.html</a>
— Kalshi history T0 Yes-ask → settle (who won). No in-play path needed.
This gain study needs a path after kickoff to know if +1 / +5 / +10¢ hit.
Kalshi hist stored 0 in-play paths (T0 window ~46 min, one close kept).
Polymarket hist stored 0 paths (one last-trade, not an ask).
October 2026 live Yes-ask tape only — max sport / bet / decile combo N=60
(tennis moneyline 40–49). Hist through-game pull + scored book:
<a href="t0_buy_sell_gain_hist_20261030.html">t0_buy_sell_gain_hist_20261030.html</a>.</p>
</div>
<div class="callout"><h2>Does near-50 move more?</h2>
<p><strong>{esc(theory.get('verdict', '').upper())}</strong> — {esc(theory.get('detail'))}</p>
<p class="note">{esc(theory.get('g_line') or '')}</p>
<p class="note">HOLD live B/C/D/E. This page is an exit-at-gain study on the T0 tape, not a send rule.</p>
</div>
<div class="callout"><h2>Three tapes, never blended</h2>
<p><strong>Live four-platform Yes-ask ticks</strong> (Oct 2026) are the GTC book.
<strong>Kalshi hist</strong> is 1-minute yes_ask.close at T0 only — settled sides
{esc(hist.get('kalshi_n_settled'))} / raw sides {esc(hist.get('kalshi_n_sides'))},
span {esc(hist.get('kalshi_span') or 'n/a')}, stored in-play path
{esc(hist.get('t0_jsonl_with_path'))} of {esc(hist.get('t0_jsonl_lines'))} jsonl lines
(median API candle n={esc(hist.get('median_candle_n'))}). GTC hit skipped on T0-only.
<strong>Polymarket CLOB last-trade</strong> hist N={esc(hist.get('poly_n_sides'))} is
<strong>not ask</strong> — skipped for GTC, not mixed into live. Did not mix sportsbooks.
Did not start a second leftover Kalshi pull.</p>
<p>Related: <a href="sport_league_t0_decile_20261027.html">sport / league / T0 decile (hold-to-settle)</a>
 · <a href="t0_buy_sell_gain_hist_20261030.html">Kalshi hist in-play gain (30 Oct)</a>.</p>
</div>
<div class="callout"><h2>Identities (labeled, not mixed)</h2>
<p>Cheaper Yes = the lower T0 Yes ask on that market after one-venue-per-side pick
(fills 0–49). Nearest-to-50¢ = the Yes closer to 50¢ so 50–59 and 40–59 exist.
Named Yes both sides = parent decile book (0–9 … 90–99). Decile is the T0 Yes
<strong>ask before fee</strong>, 0-based 10¢ buckets.</p></div>

<h2>Distance-to-50 — theory test (named Yes, in-play path)</h2>
<p class="note">Click column headers to sort. |T0−50¢| uses the ask before fee.
Avg move is the in-play Yes-ask range / max up / max down after T0. G=5 and G=10
are with-fee average P&amp;L for buy-then-sell-at-G on that same bucket (settle-miss
included). Annualized rate of return is omitted on same-day holds (house formula
<code>compare_format.ann_ror_from_closed</code> would overflow).</p>
{payload['html']['dist_table']}
{payload['html']['dist_svg']}

<h2>Near-50 vs far-from-50 — G=1 / 5 / 10 with-fee avg P&amp;L</h2>
<p class="note">Near = T0 deciles 40–49 and 50–59. Far = 0–9 and 90–99.
Cheaper Yes has no 90–99 (that is the expensive side); named Yes both sides fills far 90–99.
Hold-to-settle on the same in-play universe is the control. Do not judge on max single-trade PnL.</p>
{payload['html']['near_far']}

<h2>Canonical book metrics — cheaper Yes, in-play path</h2>
<p class="note">Hold-to-settle vs sell-at-G. Same T0 cheaper-Yes identity. Click headers to sort.
Win% here is share with with-fee P&amp;L &gt; 0 (take-profit or winning settle-miss).
IS = entry before 2024-01-01 (none on this October 2026 live tape).</p>
{payload['html']['canonical']}

<h2>Cheaper Yes — G × decile</h2>
<p class="note">Primary identity. 0–9 … 40–49. Matrix of with-fee avg P&amp;L, then the long sortable table.</p>
{payload['html']['cheap_matrix']}
{payload['html']['cheap_long']}

<h2>Cheaper Yes — sport × bet type × G=1/5/10</h2>
{payload['html']['cheap_sport']}

<h2>Cheaper Yes — sport × league × bet type × decile × G</h2>
<p class="note">Full grain. League is ATP / WTA / ITF / NFL / CFB / NBA / NHL / EPL / UFC / PGA when the ticker says so.</p>
{payload['html']['cheap_detail']}

<h2>Nearest-to-50¢ slice</h2>
<p class="note">One Yes per market: the side closer to 50¢. This is how 50–59 exists without taking every favorite.</p>
{payload['html']['near_matrix']}
{payload['html']['near_sport']}

<h2>Named Yes both sides — G × decile 0–9 … 90–99</h2>
<p class="note">Parent sport/league T0 decile identity (both named Yes after one-venue pick).</p>
{payload['html']['named_matrix']}
{payload['html']['named_long']}
{payload['html']['named_sport']}

<h2>IS / OOS</h2>
<p class="note">Live tape is all October 2026, so every T0 is out-of-sample versus 2024-01-01.
Kalshi hist span {esc(hist.get('kalshi_span') or 'n/a')}: IS N={esc(hist.get('kalshi_is'))},
OOS N={esc(hist.get('kalshi_oos'))}. Hist has no in-play path, so GTC is not scored there.
If a later hist path book softens versus IS, HOLD — do not retune OOS. Did not pick G from OOS.</p>
{payload['html']['isoos']}

<p class="tiny">Generator: <code>tools/_write_t0_buy_sell_gain_decile_sport_bet_20261030.py</code>.
Parent: <a href="sport_league_t0_decile_20261027.html">sport_league_t0_decile_20261027.html</a>.
T0 / ticks: <code>tools/t0_all_games_stats.py</code> / <code>price_memory</code>.
Fees: <code>write_t0_band_from_stay_above.documented_leg_fee</code>.
File URL {esc(FILE_URL)}.
Did not sell, start a second B, leftover-GTC A, DailyRun, or retune live B D=0.25 / C 51–89 / D spreads / E 11–49.
Did not rewrite dashboard.html.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return str(PAGE)


def matrix_rows(sides: list[dict], decades: tuple[str, ...], gains=GAIN_CENTS) -> list[dict]:
    rows = []
    for band in decades:
        bag = group_key_sides(sides, decile=band)
        row = {"decile": band, "n": len(bag), "n_path": len(path_sides(bag))}
        for g in gains:
            rec = score_gain(bag, g, arm=f"{band}|g{g}")
            row[f"g{g}"] = money(rec.get("avg_pnl")) if rec.get("n") else "—"
            row[f"n{g}"] = rec.get("n") or 0
        hold = score_gain(bag, "hold", arm=f"{band}|hold")
        row["hold"] = money(hold.get("avg_pnl")) if hold.get("n") else "—"
        rows.append(row)
    return rows


def matrix_html(rows: list[dict], decades_note: str) -> str:
    headers = [("Decile", "text"), ("N", "num"), ("N path", "num")]
    fields = ["decile", "n", "n_path"]
    for g in GAIN_CENTS:
        headers.append((f"G={g}¢ avg P&L", "num"))
        fields.append(f"g{g}")
    headers.append(("Hold avg P&L", "num"))
    fields.append("hold")
    _ = decades_note
    return table(headers, rows, fields)


def long_rows(sides: list[dict], *, include_league: bool) -> list[dict]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for side in sides:
        key = (
            str(side.get("sport") or ""),
            str(side.get("league") or "") if include_league else "ALL",
            str(side.get("kind") or ""),
            str(side.get("decile") or ""),
        )
        bags[key].append(side)
    rows = []
    for key in sorted(bags):
        sport, league, kind, band = key
        bag = bags[key]
        for g in GAIN_CENTS:
            rec = score_gain(bag, g, arm=f"{sport}|{league}|{kind}|{band}|g{g}")
            if not rec.get("n") and not rec.get("n_skip"):
                continue
            rows.append(metric_row(
                f"G={g}¢",
                rec,
                extra={
                    "sport": sport,
                    "league": league,
                    "kind": kind_label(kind),
                    "decile": band,
                    "g": g,
                    "label": f"G={g}¢",
                },
            ))
        hold = score_gain(bag, "hold", arm=f"{sport}|{league}|{kind}|{band}|hold")
        rows.append(metric_row(
            "hold",
            hold,
            extra={
                "sport": sport,
                "league": league,
                "kind": kind_label(kind),
                "decile": band,
                "g": "hold",
                "label": "hold",
            },
        ))
    return rows


def long_html(rows: list[dict], *, include_league: bool) -> str:
    headers = [
        ("Sport", "text"),
        ("League", "text") if include_league else ("League", "text"),
        ("Bet type", "text"),
        ("Decile", "text"),
        ("G", "text"),
    ] + METRIC_HEADERS[1:]
    fields = ["sport", "league", "kind", "decile", "g"] + METRIC_FIELDS[1:]
    return table(headers, rows, fields)


def sport_kind_html(sides: list[dict]) -> str:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for side in sides:
        bags[(str(side.get("sport") or ""), str(side.get("kind") or ""))].append(side)
    headers = [
        ("Sport", "text"), ("Bet type", "text"), ("N path", "num"),
        ("Hold avg P&L", "num"),
        ("G=1¢ avg", "num"), ("G=1 hit%", "num"),
        ("G=5¢ avg", "num"), ("G=5 hit%", "num"),
        ("G=10¢ avg", "num"), ("G=10 hit%", "num"),
        ("G=1 total", "num"), ("G=5 total", "num"), ("G=10 total", "num"),
    ]
    rows = []
    for sport, kind in sorted(bags):
        bag = bags[(sport, kind)]
        hold = score_gain(bag, "hold", arm=f"{sport}|{kind}|hold")
        row = {
            "sport": sport,
            "kind": kind_label(kind),
            "n_path": len(path_sides(bag)),
            "hold": money(hold.get("avg_pnl")) if hold.get("n") else "—",
        }
        for g in HEADLINE_G:
            rec = score_gain(bag, g, arm=f"{sport}|{kind}|g{g}")
            row[f"g{g}"] = money(rec.get("avg_pnl")) if rec.get("n") else "—"
            row[f"h{g}"] = fmt_pct(rec.get("hit_pct")) if rec.get("n") else "—"
            row[f"t{g}"] = money(rec.get("pnl_sum")) if rec.get("n") else "—"
        rows.append(row)
    fields = ["sport", "kind", "n_path", "hold", "g1", "h1", "g5", "h5", "g10", "h10", "t1", "t5", "t10"]
    return table(headers, rows, fields)


def dist_html(sides: list[dict]) -> tuple[str, str, list[dict]]:
    headers = [
        ("|T0−50¢|", "text"), ("N", "num"), ("N path", "num"),
        ("Avg max up ¢", "num"), ("Avg max down ¢", "num"), ("Avg range ¢", "num"),
        ("Hit +5¢ %", "num"), ("Hit +10¢ %", "num"),
        ("G=5 avg P&L", "num"), ("G=10 avg P&L", "num"),
        ("G=5 hit%", "num"), ("G=10 hit%", "num"),
    ]
    rows = []
    svg_src = []
    for band in DIST_BANDS:
        bag = group_key_sides(sides, dist=band)
        mv = move_summary(bag)
        g5 = score_gain(bag, 5, arm=f"dist{band}|g5")
        g10 = score_gain(bag, 10, arm=f"dist{band}|g10")
        def cents(val):
            return f"{val*100:.1f}" if val is not None else "—"
        rows.append({
            "band": band,
            "n": mv["n"],
            "n_path": mv["n_path"],
            "up": cents(mv["avg_max_up"]),
            "down": cents(mv["avg_max_down"]),
            "rng": cents(mv["avg_range"]),
            "h5": fmt_pct(mv["hit5_pct"]),
            "h10": fmt_pct(mv["hit10_pct"]),
            "g5": money(g5.get("avg_pnl")) if g5.get("n") else "—",
            "g10": money(g10.get("avg_pnl")) if g10.get("n") else "—",
            "gh5": fmt_pct(g5.get("hit_pct")) if g5.get("n") else "—",
            "gh10": fmt_pct(g10.get("hit_pct")) if g10.get("n") else "—",
            "avg_range": mv["avg_range"],
        })
        svg_src.append({"band": band, "avg_range": mv["avg_range"] or 0.0})
    fields = ["band", "n", "n_path", "up", "down", "rng", "h5", "h10", "g5", "g10", "gh5", "gh10"]
    return table(headers, rows, fields), svg_range(svg_src), rows


def near_far_html(identities: dict) -> str:
    headers = [
        ("Identity", "text"), ("Bucket", "text"), ("N path", "num"),
        ("Avg range ¢", "num"), ("Hold avg P&L", "num"),
        ("G=1 avg", "num"), ("G=1 hit%", "num"), ("G=1 total", "num"),
        ("G=5 avg", "num"), ("G=5 hit%", "num"), ("G=5 total", "num"),
        ("G=10 avg", "num"), ("G=10 hit%", "num"), ("G=10 total", "num"),
    ]
    rows = []
    for slice_id, label in SLICES:
        sides = identities[slice_id]
        for name, kwargs in (("near 40–49+50–59", {"near": True}), ("far 0–9+90–99", {"far": True})):
            bag = group_key_sides(sides, **kwargs)
            mv = move_summary(bag)
            hold = score_gain(bag, "hold", arm=f"{slice_id}|{name}|hold")
            row = {
                "id": label,
                "bucket": name,
                "n_path": mv["n_path"],
                "rng": f"{mv['avg_range']*100:.1f}" if mv.get("avg_range") is not None else "—",
                "hold": money(hold.get("avg_pnl")) if hold.get("n") else "—",
            }
            for g in HEADLINE_G:
                rec = score_gain(bag, g, arm=f"{slice_id}|{name}|g{g}")
                row[f"g{g}"] = money(rec.get("avg_pnl")) if rec.get("n") else "—"
                row[f"h{g}"] = fmt_pct(rec.get("hit_pct")) if rec.get("n") else "—"
                row[f"t{g}"] = money(rec.get("pnl_sum")) if rec.get("n") else "—"
            rows.append(row)
    fields = ["id", "bucket", "n_path", "rng", "hold",
              "g1", "h1", "t1", "g5", "h5", "t5", "g10", "h10", "t10"]
    return table(headers, rows, fields)


def canonical_html(sides: list[dict]) -> str:
    rows = []
    hold = score_gain(sides, "hold", arm="cheap|hold")
    rows.append(metric_row("Hold to settle (control)", hold))
    for g in GAIN_CENTS:
        rec = score_gain(sides, g, arm=f"cheap|g{g}")
        rows.append(metric_row(f"Sell at +{g}¢", rec))
    return table(METRIC_HEADERS, rows, METRIC_FIELDS)


def isoos_html(sides: list[dict]) -> str:
    is_sides = [s for s in sides if (s.get("entry_date") or "9999") < IS_CUT]
    oos_sides = [s for s in sides if (s.get("entry_date") or "") >= IS_CUT]
    headers = [("Slice", "text"), ("N", "num"), ("G=5 avg P&L", "num"), ("G=10 avg P&L", "num"),
               ("Hold avg P&L", "num"), ("Note", "text")]
    rows = []
    for name, bag in (("IS entry < 2024-01-01", is_sides), ("OOS entry ≥ 2024-01-01", oos_sides)):
        g5 = score_gain(bag, 5, arm=f"{name}|g5")
        g10 = score_gain(bag, 10, arm=f"{name}|g10")
        hold = score_gain(bag, "hold", arm=f"{name}|hold")
        rows.append({
            "name": name,
            "n": len(bag),
            "g5": money(g5.get("avg_pnl")) if g5.get("n") else "—",
            "g10": money(g10.get("avg_pnl")) if g10.get("n") else "—",
            "hold": money(hold.get("avg_pnl")) if hold.get("n") else "—",
            "note": "live tape is Oct 2026 — expect IS N=0" if name.startswith("IS") else "whole live book",
        })
    return table(headers, rows, ["name", "n", "g5", "g10", "hold", "note"])


def g_line(identities: dict) -> str:
    bits = []
    named = identities["named_yes"]
    near = group_key_sides(named, near=True)
    far = group_key_sides(named, far=True)
    for g in HEADLINE_G:
        nr = score_gain(near, g, arm=f"named|near|g{g}")
        fr = score_gain(far, g, arm=f"named|far|g{g}")
        bits.append(
            f"G={g}¢ named-Yes near avg {money(nr.get('avg_pnl')) if nr.get('n') else '—'} "
            f"(N={nr.get('n') or 0}) vs far {money(fr.get('avg_pnl')) if fr.get('n') else '—'} "
            f"(N={fr.get('n') or 0})"
        )
    cheap = identities["cheaper_yes"]
    cnear = group_key_sides(cheap, near=True)
    cfar = group_key_sides(cheap, far=True)
    for g in HEADLINE_G:
        nr = score_gain(cnear, g, arm=f"cheap|near|g{g}")
        fr = score_gain(cfar, g, arm=f"cheap|far|g{g}")
        bits.append(
            f"G={g}¢ cheaper-Yes 40–49 avg {money(nr.get('avg_pnl')) if nr.get('n') else '—'} "
            f"vs 0–9 {money(fr.get('avg_pnl')) if fr.get('n') else '—'}"
        )
    return " ".join(bits)


def patch_parent_html() -> None:
    if not PARENT_HTML.is_file():
        return
    text = PARENT_HTML.read_text(encoding="utf-8")
    needle = ' · <a href="#poly-history">Polymarket last-trade</a></p>'
    insert = (
        ' · <a href="#poly-history">Polymarket last-trade</a>'
        ' · <a href="t0_buy_sell_gain_decile_sport_bet_20261030.html">'
        "T0 buy then sell at +G (30 Oct)</a></p>"
    )
    if "t0_buy_sell_gain_decile_sport_bet_20261030.html" in text:
        return
    if needle in text:
        PARENT_HTML.write_text(text.replace(needle, insert, 1), encoding="utf-8")


def patch_parent_writer() -> None:
    path = ROOT / "tools" / "_write_sport_league_t0_decile_20261027.py"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if "t0_buy_sell_gain_decile_sport_bet_20261030.html" in text:
        return
    old = ' · <a href="#poly-history">Polymarket last-trade</a></p></div>'
    new = (
        ' · <a href="#poly-history">Polymarket last-trade</a>\n'
        ' · <a href="t0_buy_sell_gain_decile_sport_bet_20261030.html">'
        "T0 buy then sell at +G (30 Oct)</a></p></div>"
    )
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


def build_payload(live_books: list[dict], hist: dict, now: str) -> dict:
    _out(f"compacting {len(live_books)} venue books")
    named_src = live_sides_from_books(live_books)
    _out(f"named Yes sides {len(named_src)} path {len(path_sides(named_src))}")
    identities = {
        "named_yes": pick_named_yes(named_src),
        "cheaper_yes": pick_cheaper(named_src),
        "nearest_50": pick_nearest_50(named_src),
    }
    for key, bag in identities.items():
        _out(f"  {key} n={len(bag)} path={len(path_sides(bag))}")

    named_path = path_sides(identities["named_yes"])
    near_d = group_key_sides(named_path, dist="0-9")
    far_d = group_key_sides(named_path, dist="40-50")
    near_mv = move_summary(near_d)
    far_mv = move_summary(far_d)
    verdict, detail = theory_yes_no(near_mv, far_mv)

    cheap = identities["cheaper_yes"]
    nearest = identities["nearest_50"]
    named = identities["named_yes"]

    dist_table, dist_svg, _dist_rows = dist_html(named)
    html = {
        "dist_table": dist_table,
        "dist_svg": dist_svg,
        "near_far": near_far_html(identities),
        "canonical": canonical_html(path_sides(cheap)),
        "cheap_matrix": matrix_html(matrix_rows(cheap, ("0-9", "10-19", "20-29", "30-39", "40-49")), "cheaper"),
        "cheap_long": long_html(long_rows(cheap, include_league=False), include_league=False),
        "cheap_sport": sport_kind_html(cheap),
        "cheap_detail": long_html(long_rows(cheap, include_league=True), include_league=True),
        "near_matrix": matrix_html(matrix_rows(nearest, DECADES), "nearest"),
        "near_sport": sport_kind_html(nearest),
        "named_matrix": matrix_html(matrix_rows(named, DECADES), "named"),
        "named_long": long_html(long_rows(named, include_league=False), include_league=False),
        "named_sport": sport_kind_html(named),
        "isoos": isoos_html(cheap),
    }
    theory = {
        "verdict": verdict,
        "detail": detail,
        "near_move": near_mv,
        "far_move": far_mv,
        "g_line": g_line(identities),
    }
    knobs = live_knobs()
    headline = {}
    for slice_id in ("cheaper_yes", "nearest_50", "named_yes"):
        sides = identities[slice_id]
        headline[slice_id] = {}
        for name, kwargs in (("near", {"near": True}), ("far", {"far": True}), ("all", {})):
            bag = group_key_sides(sides, **kwargs) if kwargs else sides
            headline[slice_id][name] = {
                "move": move_summary(bag),
                "hold": score_gain(bag, "hold", arm=f"{slice_id}|{name}|hold"),
            }
            for g in HEADLINE_G:
                headline[slice_id][name][f"g{g}"] = score_gain(
                    bag, g, arm=f"{slice_id}|{name}|g{g}"
                )
    return {
        "written_at": now,
        "knobs": knobs,
        "hist": hist,
        "theory": theory,
        "html": html,
        "headline": headline,
        "n_named": len(named),
        "n_cheaper": len(cheap),
        "n_nearest": len(nearest),
        "n_named_path": len(path_sides(named)),
        "n_cheaper_path": len(path_sides(cheap)),
        "live_span": "Oct 2026 four-platform Yes-ask",
    }


def json_dump(payload: dict) -> dict:
    theory = payload["theory"]
    return {
        "written_at": payload["written_at"],
        "n_named": payload["n_named"],
        "n_cheaper": payload["n_cheaper"],
        "n_nearest": payload["n_nearest"],
        "n_named_path": payload["n_named_path"],
        "n_cheaper_path": payload["n_cheaper_path"],
        "theory_verdict": theory.get("verdict"),
        "theory_detail": theory.get("detail"),
        "g_line": theory.get("g_line"),
        "near_move": theory.get("near_move"),
        "far_move": theory.get("far_move"),
        "headline": payload["headline"],
        "hist": payload["hist"],
        "knobs": payload["knobs"],
        "live_knobs_unchanged": payload["knobs"].get("unchanged"),
    }


def main() -> int:
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    _out("hist census + live T0 tape (parallel)")
    with ThreadPoolExecutor(max_workers=2) as pool:
        hist_f = pool.submit(hist_census)
        live = t0.build_payload()
        hist = hist_f.result()
    _out(
        f"live books {len(live.get('books') or [])} hist kalshi={hist.get('kalshi_n_sides')} "
        f"path_stored={hist.get('t0_jsonl_with_path')}"
    )
    payload = build_payload(live.get("books") or [], hist, now)
    path = write_html(payload)
    BASELINE.write_text(freeze_md(payload), encoding="utf-8")
    JSON_OUT.write_text(json.dumps(json_dump(payload), indent=2, default=str), encoding="utf-8")
    patch_parent_html()
    patch_parent_writer()
    _out(f"wrote {path}")
    _out(f"theory {payload['theory']['verdict']}: {payload['theory']['detail']}")
    _out(payload["theory"]["g_line"])
    _out(f"live knobs unchanged={payload['knobs']['unchanged']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
