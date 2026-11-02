"""Paul-facing on/off + sizing for live prediction systems A–G.

Does not print secrets. Does not sell tickets. Does not wire GTC.
Does not start a second live_strategy_b.py. Config lives under local raw,
not Drive. Lock leftover / flatten stay in live_lock_orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from zoneinfo import ZoneInfo

from prediction_paths import RAW_DIR as RAW, ROOT, ensure_dirs

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

ET = ZoneInfo("America/New_York")
CONFIG_PATH = RAW / "systems.json"
LOCK_DEFAULT_MAX = 3
NEW_SYSTEM_DEFAULT_MAX = 2
DEFAULT_STAKE = Decimal("1.00")
DEFAULT_SIZE = 1
YES_LO = Decimal("0.50")
YES_HI = Decimal("0.90")
DOG_LO = Decimal("0.10")
DOG_HI = Decimal("0.50")
SPREAD_F_LO = Decimal("0.20")
SPREAD_F_HI = Decimal("0.50")
TOTAL_G_LO = Decimal("0.20")
TOTAL_G_HI = Decimal("0.50")
VENUE_RANK = ("kalshi", "gemini", "polymarket", "novig")
# Send allowlist follows venue module flags (Gemini GEMINI_ORDERS_ENABLED /
# systems.json "gemini_orders"; Novig NOVIG_ORDERS_ENABLED). Quotes stay in
# VENUE_RANK for compare / favorite truth. for_send=True pickers skip soft-disabled
# venues so C/D/E/F/G never POST there. Flip gemini_orders in systems.json to
# re-enable Gemini sends without hunting every bot.

SYSTEM_IDS = (
    "lock",
    "tennis_crossover",
    "cfb_favorite",
    "spread_t0",
    "tennis_t0_dog",
    "tennis_t0_spread",
    "soccer_t0_total",
)
LIVE_BOT_IDS = (
    "tennis_crossover",
    "cfb_favorite",
    "spread_t0",
    "tennis_t0_dog",
    "tennis_t0_spread",
    "soccer_t0_total",
)
LETTER = {
    "lock": "A",
    "tennis_crossover": "B",
    "cfb_favorite": "C",
    "spread_t0": "D",
    "tennis_t0_dog": "E",
    "tennis_t0_spread": "F",
    "soccer_t0_total": "G",
}
DISPLAY = {
    "lock": "Lock gap",
    "tennis_crossover": "Tennis crossover",
    "cfb_favorite": "College football favorite",
    "spread_t0": "T0 spreads",
    "tennis_t0_dog": "Tennis T0 dog",
    "tennis_t0_spread": "Tennis spread",
    "soccer_t0_total": "Soccer total",
}
ALIASES = {
    "lock": "lock",
    "a": "lock",
    "tennis-crossover": "tennis_crossover",
    "tennis_crossover": "tennis_crossover",
    "b": "tennis_crossover",
    "strategy-b": "tennis_crossover",
    "strategy_b": "tennis_crossover",
    "cfb-favorite": "cfb_favorite",
    "cfb_favorite": "cfb_favorite",
    "c": "cfb_favorite",
    "spread-t0": "spread_t0",
    "spread_t0": "spread_t0",
    "d": "spread_t0",
    "tennis-t0-dog": "tennis_t0_dog",
    "tennis_t0_dog": "tennis_t0_dog",
    "e": "tennis_t0_dog",
    "p2": "tennis_t0_dog",
    "tennis-t0-spread": "tennis_t0_spread",
    "tennis_t0_spread": "tennis_t0_spread",
    "f": "tennis_t0_spread",
    "soccer-t0-total": "soccer_t0_total",
    "soccer_t0_total": "soccer_t0_total",
    "g": "soccer_t0_total",
}
SCRIPTS = {
    "tennis_crossover": ROOT / "tools" / "live_strategy_b.py",
    "cfb_favorite": ROOT / "tools" / "live_cfb_favorite.py",
    "spread_t0": ROOT / "tools" / "live_spread_t0.py",
    "tennis_t0_dog": ROOT / "tools" / "live_tennis_t0_dog.py",
    "tennis_t0_spread": ROOT / "tools" / "live_tennis_t0_spread.py",
    "soccer_t0_total": ROOT / "tools" / "live_soccer_t0_total.py",
}
CONSOLE_LOGS = {
    "tennis_crossover": RAW / "strategy_b.console.log",
    "cfb_favorite": RAW / "cfb_favorite.console.log",
    "spread_t0": RAW / "spread_t0.console.log",
    "tennis_t0_dog": RAW / "tennis_t0_dog.console.log",
    "tennis_t0_spread": RAW / "tennis_t0_spread.console.log",
    "soccer_t0_total": RAW / "soccer_t0_total.console.log",
}
WATCH_FILES = {
    "tennis_crossover": RAW / "strategy_b_watch.json",
    "cfb_favorite": RAW / "cfb_favorite_watch.json",
    "spread_t0": RAW / "spread_t0_watch.json",
    "tennis_t0_dog": RAW / "tennis_t0_dog_watch.json",
    "tennis_t0_spread": RAW / "tennis_t0_spread_watch.json",
    "soccer_t0_total": RAW / "soccer_t0_total_watch.json",
}
CLASSIFY_KEY = {
    "tennis_crossover": "strategy_b",
    "cfb_favorite": "cfb_favorite",
    "spread_t0": "spread_t0",
    "tennis_t0_dog": "tennis_t0_dog",
    "tennis_t0_spread": "tennis_t0_spread",
    "soccer_t0_total": "soccer_t0_total",
}
NEEDLE = {
    "tennis_crossover": "live_strategy_b.py",
    "cfb_favorite": "live_cfb_favorite.py",
    "spread_t0": "live_spread_t0.py",
    "tennis_t0_dog": "live_tennis_t0_dog.py",
    "tennis_t0_spread": "live_tennis_t0_spread.py",
    "soccer_t0_total": "live_soccer_t0_total.py",
}


def iso_now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _dec(value, default: Decimal | None = None) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def in_fav_band(ask) -> bool:
    """True when favorite Yes is in (0.50, 0.90). 0.50 and 0.90 are skips."""
    px = _dec(ask)
    if px is None:
        return False
    return YES_LO < px < YES_HI


def in_dog_band(ask) -> bool:
    """True when unique dog Yes is in (0.10, 0.50). 0.10 and 0.50 are skips."""
    px = _dec(ask)
    if px is None:
        return False
    return DOG_LO < px < DOG_HI


def in_f_spread_band(ask) -> bool:
    """True when tennis spread Yes is in [0.20, 0.50). 20¢ included, 50¢ skipped.

    20–49 inclusive cents. Matches E's exclusive-open style on the open end
    (50¢ out) and includes 20¢. Sensitivity 10–49 is not this freeze.
    """
    px = _dec(ask)
    if px is None:
        return False
    return SPREAD_F_LO <= px < SPREAD_F_HI


def in_f_spread_band_sens(ask) -> bool:
    """Sensitivity 10–49: [0.10, 0.50). Freeze remains 20–49."""
    px = _dec(ask)
    if px is None:
        return False
    return DOG_LO <= px < SPREAD_F_HI


def in_g_total_band(ask) -> bool:
    """True when soccer Points Total Yes is in [0.20, 0.50). Same cents as F.

    20¢ included, 50¢ skipped. 20–49 inclusive cents. Sensitivity 10–49 is
    not this freeze.
    """
    px = _dec(ask)
    if px is None:
        return False
    return TOTAL_G_LO <= px < TOTAL_G_HI


def in_g_total_band_sens(ask) -> bool:
    """Sensitivity 10–49: [0.10, 0.50). Freeze remains 20–49."""
    px = _dec(ask)
    if px is None:
        return False
    return DOG_LO <= px < TOTAL_G_HI


def total_quote_fee_ok(row: dict | None) -> bool:
    """False when Novig has no documented fee. Other venues are ok."""
    row = row if isinstance(row, dict) else {}
    venue = str(row.get("venue") or "").strip().lower()
    if venue != "novig":
        return True
    spec = row.get("spec") if isinstance(row.get("spec"), dict) else {}
    for blob in (row, spec):
        if blob.get("fee_coefficient") not in (None, ""):
            return True
        if blob.get("fee_charged") not in (None, ""):
            return True
    return False


def contracts_for_stake(ask, *, size: int = DEFAULT_SIZE, stake_usd=DEFAULT_STAKE) -> int:
    """Whole contracts only. Cash cost of N contracts must be <= stake_usd.

    At these prices $1 ≈ 1 contract (a 50–89¢ Yes). Never fractional.
    """
    px = _dec(ask)
    stake = _dec(stake_usd, DEFAULT_STAKE) or DEFAULT_STAKE
    n_cap = max(0, int(size))
    if px is None or px <= 0 or n_cap <= 0 or stake <= 0:
        return 0
    if px > stake:
        return 0
    by_stake = int((stake / px).to_integral_value(rounding=ROUND_DOWN))
    return max(0, min(n_cap, by_stake))


def _median(xs: list[Decimal]) -> Decimal | None:
    if not xs:
        return None
    ordered = sorted(xs)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def pick_dog_primary(side_asks: dict[str, Decimal | None]) -> str | None:
    """Unique lower T0 Yes ask. Must be in (0.10, 0.50). Skip 50-50 / junk / missing."""
    ranked = []
    for name, raw in (side_asks or {}).items():
        px = _dec(raw)
        if not name or px is None:
            continue
        ranked.append((px, str(name)))
    if len(ranked) < 2:
        return None
    ranked.sort()
    if ranked[0][0] == ranked[1][0]:
        return None
    if not in_dog_band(ranked[0][0]):
        return None
    return ranked[0][1]


def resolve_dog_across_venues(team_asks: dict[str, list]) -> str | None:
    """Unique cheaper Yes across venues. Skip ties, 50-50, and junk ≤0.10."""
    best: dict[str, Decimal] = {}
    for team, raws in (team_asks or {}).items():
        xs = []
        for raw in raws or []:
            px = _dec(raw)
            if px is not None:
                xs.append(px)
        if xs:
            best[str(team)] = min(xs)
    if len(best) < 2:
        return None
    ranked = sorted(best.items(), key=lambda item: item[1])
    if ranked[0][1] == ranked[1][1]:
        return None
    if not in_dog_band(ranked[0][1]):
        return None
    return ranked[0][0]


def pick_favorite_primary(side_asks: dict[str, Decimal | None]) -> str | None:
    """Primary-read favorite: higher Yes ask. Skip 50-50 / missing."""
    ranked = []
    for name, raw in (side_asks or {}).items():
        px = _dec(raw)
        if not name or px is None:
            continue
        ranked.append((px, str(name)))
    if len(ranked) < 2:
        return None
    ranked.sort(reverse=True)
    if ranked[0][0] <= YES_LO:
        return None
    if ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def resolve_favorite_across_venues(team_asks: dict[str, list]) -> str | None:
    """When venues disagree: team with a Yes >50; if both, higher median Yes.

    Favorite = team whose best (lowest) Yes ask among asks >50 is defined.
    If both teams have a venue >50, pick the higher median Yes. Skip 50-50.
    """
    above: dict[str, list[Decimal]] = {}
    for team, raws in (team_asks or {}).items():
        xs = []
        for raw in raws or []:
            px = _dec(raw)
            if px is not None and px > YES_LO:
                xs.append(px)
        if xs:
            above[str(team)] = xs
    if not above:
        return None
    if len(above) == 1:
        return next(iter(above))
    meds = []
    for team, xs in above.items():
        med = _median(xs)
        if med is None:
            continue
        best = min(xs)
        meds.append((med, -best, team))
    if len(meds) < 2:
        return meds[0][2] if meds else None
    meds.sort(reverse=True)
    if meds[0][0] == meds[1][0]:
        return None
    return meds[0][2]


def venue_sendable(venue: str) -> bool:
    """True when this venue may be chosen as a live send leg.

    Gemini / Novig follow their module orders_live() flags (quote-only when
    False). Kalshi and Polymarket stay sendable. Unknown venues are not.
    """
    v = str(venue or "").strip().lower()
    if v not in VENUE_RANK:
        return False
    if v == "gemini":
        import gemini_private

        return bool(gemini_private.orders_live())
    if v == "novig":
        import novig_live

        return bool(novig_live.orders_live())
    return True


def best_venue_yes(quotes: list[dict], team: str, *, for_send: bool = False) -> dict | None:
    """Cheapest Yes ask for this team. Kalshi > Gemini > Poly > Novig on ties.

    for_send=True skips soft-disabled send venues (Gemini quote-only, Novig
    orders off). Compare / favorite truth keep for_send=False so Gemini quotes
    still shape price discovery.
    """
    want = _norm_side(team)
    ranked = []
    for row in quotes or []:
        if _norm_side(row.get("side") or row.get("team") or "") != want:
            continue
        px = _dec(row.get("yes") if row.get("yes") is not None else row.get("ask"))
        if px is None:
            continue
        venue = str(row.get("venue") or "").lower()
        if for_send and not venue_sendable(venue):
            continue
        rank = VENUE_RANK.index(venue) if venue in VENUE_RANK else 9
        ranked.append((px, rank, venue, row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[0][3]


def pick_cheapest_spread_yes(quotes: list[dict], *, lo=None, hi=None, for_send: bool = False) -> dict | None:
    """Cheapest spread Yes in [lo, hi). Skip moneyline and Points Total.

    Venue rank Kalshi > Gemini > Poly > Novig on price ties. F freeze is
    lo=0.20, hi=0.50. Does not require a unique dog or pair <= 1.05.
    for_send=True skips soft-disabled send venues.
    """
    low = _dec(lo, SPREAD_F_LO) or SPREAD_F_LO
    high = _dec(hi, SPREAD_F_HI) or SPREAD_F_HI
    ranked = []
    for row in quotes or []:
        kind = str(row.get("kind") or "").strip().lower()
        if kind != "spread":
            continue
        px = _dec(row.get("yes") if row.get("yes") is not None else row.get("ask"))
        if px is None or px < low or px >= high:
            continue
        venue = str(row.get("venue") or "").lower()
        if for_send and not venue_sendable(venue):
            continue
        rank = VENUE_RANK.index(venue) if venue in VENUE_RANK else 9
        ranked.append((px, rank, venue, str(row.get("number") or ""), row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return ranked[0][4]


def pick_cheapest_total_yes(quotes: list[dict], *, lo=None, hi=None, for_send: bool = False) -> dict | None:
    """Cheapest Points Total Yes in [lo, hi). Skip moneyline and spread.

    Venue rank Kalshi > Gemini > Poly > Novig on price ties. G freeze is
    lo=0.20, hi=0.50. Skip Novig when fee is unknown. Does not pick across
    A–F trading systems — venues on this game+line+side only.
    for_send=True skips soft-disabled send venues.
    """
    low = _dec(lo, TOTAL_G_LO) or TOTAL_G_LO
    high = _dec(hi, TOTAL_G_HI) or TOTAL_G_HI
    ranked = []
    for row in quotes or []:
        kind = str(row.get("kind") or "").strip().lower()
        if kind != "total":
            continue
        if not total_quote_fee_ok(row):
            continue
        px = _dec(row.get("yes") if row.get("yes") is not None else row.get("ask"))
        if px is None or px < low or px >= high:
            continue
        venue = str(row.get("venue") or "").lower()
        if for_send and not venue_sendable(venue):
            continue
        rank = VENUE_RANK.index(venue) if venue in VENUE_RANK else 9
        ranked.append((px, rank, venue, str(row.get("number") or ""), row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return ranked[0][4]


def pick_spread_line(lines: list[dict], *, all_lines: bool = False) -> list[dict]:
    """One qualifying two-sided traditional spread per game, closest to 50¢.

    Live D ignores `--d-all-lines` (that flag is not stored). Totals and team
    totals stay out of the send. Leftover max_open slots go to the next game,
    never extra lines on the same kickoff.
    """
    del all_lines
    qual = []
    for row in lines or []:
        kind = str(row.get("kind") or "")
        if kind != "spread":
            continue
        if not row.get("two_sided"):
            continue
        px = _dec(row.get("fav_ask") if row.get("fav_ask") is not None else row.get("ask"))
        if px is None or not in_fav_band(px):
            continue
        qual.append(dict(row, fav_ask=px))
    if not qual:
        return []
    qual.sort(key=lambda row: (abs(row["fav_ask"] - YES_LO), str(row.get("number") or "")))
    return [qual[0]]


def _norm_side(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def same_side(left: str, right: str) -> bool:
    a = _norm_side(left)
    b = _norm_side(right)
    if not a or not b:
        return False
    if a == b:
        return True
    compact_a = a.replace(" ", "")
    compact_b = b.replace(" ", "")
    if compact_a == compact_b:
        return True
    if compact_a in compact_b or compact_b in compact_a:
        return True
    ta = a.split()[-1]
    tb = b.split()[-1]
    return bool(ta and ta == tb and len(ta) >= 3)


@dataclass
class SystemCfg:
    id: str
    on: bool
    max_open: int
    stake_usd: Decimal
    size: int
    net_max: Decimal | None = None

    def as_dict(self) -> dict:
        out = {
            "id": self.id,
            "display": DISPLAY[self.id],
            "on": bool(self.on),
            "max_open": int(self.max_open),
            "stake_usd": format(self.stake_usd, "f"),
            "size": int(self.size),
        }
        if self.id == "lock" and self.net_max is not None:
            out["net_max"] = format(self.net_max, "f")
        return out


def _default_max(sid: str) -> int:
    if sid == "lock":
        return LOCK_DEFAULT_MAX
    if sid == "tennis_crossover":
        watch = _load_json(WATCH_FILES["tennis_crossover"])
        raw = watch.get("max_open_b_matches")
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = NEW_SYSTEM_DEFAULT_MAX
        return n if n >= 1 else NEW_SYSTEM_DEFAULT_MAX
    return NEW_SYSTEM_DEFAULT_MAX


def empty_config() -> dict[str, SystemCfg]:
    return {
        sid: SystemCfg(
            id=sid,
            on=sid in ("lock", "tennis_crossover"),
            max_open=_default_max(sid),
            stake_usd=DEFAULT_STAKE,
            size=DEFAULT_SIZE,
        )
        for sid in SYSTEM_IDS
    }


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config(path: Path | None = None) -> dict[str, SystemCfg]:
    target = path or CONFIG_PATH
    base = empty_config()
    blob = _load_json(target)
    rows = blob.get("systems") if isinstance(blob.get("systems"), dict) else blob
    if not isinstance(rows, dict):
        return base
    for sid, cfg in base.items():
        raw = rows.get(sid)
        if not isinstance(raw, dict):
            continue
        if "on" in raw:
            cfg.on = bool(raw.get("on"))
        if raw.get("max_open") not in (None, ""):
            try:
                cfg.max_open = max(1, int(raw.get("max_open")))
            except (TypeError, ValueError):
                pass
        stake = _dec(raw.get("stake_usd"), cfg.stake_usd)
        if stake is not None and stake > 0:
            cfg.stake_usd = stake
        if raw.get("size") not in (None, ""):
            try:
                cfg.size = max(1, int(raw.get("size")))
            except (TypeError, ValueError):
                pass
        if sid == "lock" and raw.get("net_max") not in (None, ""):
            nm = _dec(raw.get("net_max"))
            if nm is not None and nm > 0:
                cfg.net_max = nm
    return base


def save_config(cfgs: dict[str, SystemCfg], path: Path | None = None) -> Path:
    target = path or CONFIG_PATH
    ensure_dirs()
    payload = {
        "updated_at": iso_now(),
        "note": (
            "$1 ≈ 1 contract at these prices. Size is whole contracts. "
            "Stake-usd is the cash cap for those contracts. "
            "Lock leftover/flatten unchanged. Profit cap NET_MAX is lock only. "
            "C, D, and E are directional Yes; no 0.984 gate. Research-candidate live, not gold, not DailyRun."
        ),
        "systems": {sid: cfgs[sid].as_dict() for sid in SYSTEM_IDS},
    }
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def get_system(sid: str, path: Path | None = None) -> SystemCfg:
    sid = ALIASES.get(str(sid or "").strip().lower(), str(sid or ""))
    cfgs = load_config(path)
    if sid not in cfgs:
        raise KeyError(sid)
    return cfgs[sid]


def is_on(sid: str, path: Path | None = None) -> bool:
    try:
        return bool(get_system(sid, path).on)
    except KeyError:
        return False


def parse_on_off(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if raw in {"on", "true", "yes", "1"}:
        return True
    if raw in {"off", "false", "no", "0"}:
        return False
    raise ValueError(f"need on or off, got {text!r}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prediction_job_control.py systems",
        description="Turn live systems on/off and set stake / max open.",
    )
    p.add_argument("--lock", "--a", dest="lock", metavar="on|off")
    p.add_argument("--tennis-crossover", "--b", dest="tennis_crossover", metavar="on|off")
    p.add_argument("--cfb-favorite", "--c", dest="cfb_favorite", metavar="on|off")
    p.add_argument("--spread-t0", "--d", dest="spread_t0", metavar="on|off")
    p.add_argument("--tennis-t0-dog", "--e", dest="tennis_t0_dog", metavar="on|off")
    p.add_argument("--tennis-t0-spread", "--f", dest="tennis_t0_spread", metavar="on|off")
    p.add_argument("--soccer-t0-total", "--g", dest="soccer_t0_total", metavar="on|off")
    p.add_argument("--lock-max", "--a-max", dest="lock_max", type=int)
    p.add_argument("--tennis-crossover-max", "--b-max", dest="tennis_crossover_max", type=int)
    p.add_argument("--cfb-favorite-max", "--c-max", dest="cfb_favorite_max", type=int)
    p.add_argument("--spread-t0-max", "--d-max", dest="spread_t0_max", type=int)
    p.add_argument("--tennis-t0-dog-max", "--e-max", dest="tennis_t0_dog_max", type=int)
    p.add_argument("--tennis-t0-spread-max", "--f-max", dest="tennis_t0_spread_max", type=int)
    p.add_argument("--soccer-t0-total-max", "--g-max", dest="soccer_t0_total_max", type=int)
    p.add_argument(
        "--lock-net-max",
        "--lock-gap",
        dest="lock_net_max",
        type=str,
        metavar="0.984",
        help=(
            "Lock after-fee send cap (NET_MAX). Example 0.984 or 0.99. "
            "Default stays 0.984 until this flag is set. "
            "--lock / --lock-max / --lock-stake do not change it."
        ),
    )
    p.add_argument("--lock-stake", "--lock-stake-usd", "--a-stake", dest="lock_stake", type=str)
    p.add_argument("--tennis-crossover-stake", "--b-stake", dest="tennis_crossover_stake", type=str)
    p.add_argument("--cfb-favorite-stake", "--c-stake", dest="cfb_favorite_stake", type=str)
    p.add_argument("--spread-t0-stake", "--d-stake", dest="spread_t0_stake", type=str)
    p.add_argument("--tennis-t0-dog-stake", "--e-stake", dest="tennis_t0_dog_stake", type=str)
    p.add_argument("--tennis-t0-spread-stake", "--f-stake", dest="tennis_t0_spread_stake", type=str)
    p.add_argument("--soccer-t0-total-stake", "--g-stake", dest="soccer_t0_total_stake", type=str)
    p.add_argument("--lock-size", "--a-size", dest="lock_size", type=int)
    p.add_argument("--tennis-crossover-size", "--b-size", dest="tennis_crossover_size", type=int)
    p.add_argument("--cfb-favorite-size", "--c-size", dest="cfb_favorite_size", type=int)
    p.add_argument("--spread-t0-size", "--d-size", dest="spread_t0_size", type=int)
    p.add_argument("--tennis-t0-dog-size", "--e-size", dest="tennis_t0_dog_size", type=int)
    p.add_argument("--tennis-t0-spread-size", "--f-size", dest="tennis_t0_spread_size", type=int)
    p.add_argument("--soccer-t0-total-size", "--g-size", dest="soccer_t0_total_size", type=int)
    p.add_argument(
        "--d-all-lines",
        action="store_true",
        help="Ignored. D is one traditional spread (wins-by-n) per game. Not stored.",
    )
    p.add_argument("--config", type=str, default="")
    p.add_argument("--no-apply", action="store_true", help="Write config only. Tests / dry-run.")
    return p


def flags_touched(ns: argparse.Namespace) -> dict[str, dict]:
    """Map system id -> fields to change. Empty means status-only."""
    out: dict[str, dict] = {}

    def slot(sid: str) -> dict:
        return out.setdefault(sid, {})

    mapping = (
        ("lock", "lock"),
        ("tennis_crossover", "tennis_crossover"),
        ("cfb_favorite", "cfb_favorite"),
        ("spread_t0", "spread_t0"),
        ("tennis_t0_dog", "tennis_t0_dog"),
        ("tennis_t0_spread", "tennis_t0_spread"),
        ("soccer_t0_total", "soccer_t0_total"),
    )
    for attr, sid in mapping:
        val = getattr(ns, attr, None)
        if val is not None:
            slot(sid)["on"] = parse_on_off(val)
        mx = getattr(ns, f"{attr}_max", None)
        if mx is not None:
            if int(mx) < 1:
                raise ValueError(f"{sid} max_open must be >= 1")
            slot(sid)["max_open"] = int(mx)
        stake = getattr(ns, f"{attr}_stake", None)
        if stake is not None:
            px = _dec(stake)
            if px is None or px <= 0:
                raise ValueError(f"{sid} stake must be > 0")
            slot(sid)["stake_usd"] = px
        size = getattr(ns, f"{attr}_size", None)
        if size is not None:
            if int(size) < 1:
                raise ValueError(f"{sid} size must be >= 1")
            slot(sid)["size"] = int(size)
    lock_net = getattr(ns, "lock_net_max", None)
    if lock_net is not None:
        px = _dec(lock_net)
        if px is None or px <= 0:
            raise ValueError("lock net_max must be > 0")
        slot("lock")["net_max"] = px
    return out


def merge_updates(cfgs: dict[str, SystemCfg], updates: dict[str, dict]) -> dict[str, SystemCfg]:
    for sid, fields in updates.items():
        cfg = cfgs[sid]
        if "on" in fields:
            cfg.on = bool(fields["on"])
        if "max_open" in fields:
            cfg.max_open = int(fields["max_open"])
        if "stake_usd" in fields:
            cfg.stake_usd = fields["stake_usd"]
        if "size" in fields:
            cfg.size = int(fields["size"])
        if "net_max" in fields:
            cfg.net_max = fields["net_max"]
    return cfgs


def _pid_alive(pid: int) -> bool:
    if not pid or int(pid) <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
        except OSError:
            return False
        return True
    import ctypes

    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    kernel.CloseHandle(handle)
    return True


def classify_jobs(jobs: dict | None = None) -> dict:
    if jobs is not None:
        return jobs
    import prediction_job_control

    return prediction_job_control.classify(prediction_job_control._ps_rows())


def pids_for(sid: str, jobs: dict | None = None) -> list[int]:
    jobs = classify_jobs(jobs)
    key = CLASSIFY_KEY.get(sid)
    if not key:
        return []
    return [int(row["pid"]) for row in (jobs.get(key) or []) if row.get("pid")]


def _spawn_script(sid: str) -> None:
    import prediction_job_control

    script = SCRIPTS[sid]
    log = CONSOLE_LOGS[sid]
    prediction_job_control._spawn(script, log, hidden=True)


def ensure_system(sid: str, jobs: dict | None = None) -> bool:
    """Start this system if it is on and missing. Never starts a second B."""
    if sid == "lock":
        return False
    if not is_on(sid):
        return False
    jobs = classify_jobs(jobs)
    if pids_for(sid, jobs):
        return False
    _spawn_script(sid)
    return True


def stop_system(sid: str, jobs: dict | None = None) -> list[int]:
    if sid == "lock":
        return []
    import prediction_job_control

    jobs = classify_jobs(jobs)
    pids = pids_for(sid, jobs)
    if pids:
        prediction_job_control._stop_pids(pids)
        deadline = time.time() + 20.0
        while time.time() < deadline:
            left = pids_for(sid)
            if not left:
                break
            time.sleep(0.4)
    return pids


def reload_system(sid: str, jobs: dict | None = None) -> str:
    """Stop the live pid if any, then start one. Never a second B. Does not sell."""
    if sid == "lock":
        return "lock lives in live_lock_sender.py; supervisor respawns it"
    jobs = classify_jobs(jobs)
    was = pids_for(sid, jobs)
    if was:
        stop_system(sid, jobs)
    if not is_on(sid):
        return f"{DISPLAY[sid]} off; stopped {was or 'none'}"
    left = pids_for(sid)
    if left:
        return (
            f"{DISPLAY[sid]} still listed pid {left[0]} after stop; "
            f"did not start a second process"
        )
    _spawn_script(sid)
    return f"{DISPLAY[sid]} reloaded one process (was {was[0] if was else 'none'})"


def apply_process(sid: str, cfg: SystemCfg, jobs: dict | None = None, fields: dict | None = None) -> str:
    """Reload in place when the pid is alive. Start if on+dead. Stop if off.

    Lock lives inside the pollers; on/off, max_open, and net_max are read from
    systems.json each tick (same as D max). No lock restart.
    Never spawn a second tennis crossover.
    """
    if sid == "lock":
        if fields and fields.get("on") is True:
            try:
                import live_lock_orders

                live_lock_orders.clear_one_leg_new_pair_latch()
            except Exception:
                pass
        return "lock config written; lock sender reads it in place (no restart)"
    jobs = classify_jobs(jobs)
    live = pids_for(sid, jobs)
    if not cfg.on:
        if live:
            stop_system(sid, jobs)
            return f"{DISPLAY[sid]} stopped pids {live}"
        return f"{DISPLAY[sid]} already off"
    if live:
        return (
            f"{DISPLAY[sid]} pid {live[0]} alive; config re-read in place "
            f"(did not start a second process)"
        )
    _spawn_script(sid)
    return f"{DISPLAY[sid]} started"


def apply_updates(
    updates: dict[str, dict],
    *,
    path: Path | None = None,
    spawn: bool = True,
    jobs: dict | None = None,
) -> tuple[dict[str, SystemCfg], list[str]]:
    cfgs = load_config(path)
    if updates:
        cfgs = merge_updates(cfgs, updates)
        save_config(cfgs, path)
    notes = []
    if spawn and updates:
        for sid in updates:
            notes.append(apply_process(sid, cfgs[sid], jobs, fields=updates.get(sid)))
    return cfgs, notes


def last_action(sid: str) -> str:
    if sid == "lock":
        skip = _load_json(RAW / "lock_last_skip.json")
        when = str(skip.get("at") or skip.get("when") or "")
        reason = str(skip.get("reason") or skip.get("event") or "")
        if reason:
            try:
                import live_lock_orders

                reason = live_lock_orders.rewrite_send_line_copy(reason)
            except Exception:
                pass
        if when or reason:
            return f"{when} {reason}".strip()
        return "-"
    watch = _load_json(WATCH_FILES.get(sid, Path()))
    last = str(watch.get("last_send") or watch.get("last_action") or watch.get("updated_at") or "")
    note = str(watch.get("last_skip_reason") or watch.get("note") or "")
    if last or note:
        return f"{last} {note}".strip()
    return "-"


def open_now_display(value) -> str:
    """Open now is a count. Cap belongs in Max, not mashed as n/max."""
    text = "" if value is None else str(value).strip()
    if not text:
        return "-"
    if "/" in text:
        left = text.split("/", 1)[0].strip()
        if left.lstrip("-").isdigit():
            return left
    return text


def currently_open(sid: str, *, snapshot=None, positions=None) -> str:
    """Open now is the count of Positions rows by system when a bundle is given."""
    letter = LETTER.get(sid, "")
    if isinstance(positions, dict) and isinstance(positions.get("rows"), list):
        counts = positions.get("open_now")
        if isinstance(counts, dict) and letter in counts:
            return open_now_display(counts[letter])
        n = sum(1 for row in positions["rows"] if str(row.get("letter") or "") == letter)
        return open_now_display(n)
    if sid == "lock":
        try:
            import live_lock_orders

            return str(len(live_lock_orders.open_lock_keys()))
        except Exception:
            return "-"
    try:
        import open_count_sync

        return open_now_display(open_count_sync.open_count(sid, snapshot=snapshot))
    except Exception:
        pass
    watch = _load_json(WATCH_FILES.get(sid, Path()))
    if sid == "tennis_crossover":
        return open_now_display(watch.get("currently_open") if watch else "-")
    n = watch.get("currently_open")
    if n is None:
        matches = [row for row in (watch.get("matches") or []) if isinstance(row, dict)]
        n = sum(1 for row in matches if str(row.get("stage") or "") in {"waiting_t0", "filled", "holding", "open"})
    return open_now_display(n)


def status_rows(jobs: dict | None = None, *, snapshot=None, positions=None) -> list[dict]:
    cfgs = load_config()
    jobs = classify_jobs(jobs)
    rows = []
    for sid in SYSTEM_IDS:
        cfg = cfgs[sid]
        pids = pids_for(sid, jobs) if sid != "lock" else []
        if sid == "lock":
            # A sends via live_lock_sender.py (supervisor child). Do not fall
            # back to the supervisor PID — that made "On + PID" look live while
            # Lock sender (A) was DOWN.
            sender = (jobs.get("lock_sender") or [None])[0]
            if sender and sender.get("pid"):
                pid_text = str(sender.get("pid"))
            else:
                pid_text = "-"
            extra = ""
        else:
            pid_text = str(pids[0]) if pids else "-"
            extra = ", ".join(str(p) for p in pids[1:])
        name = DISPLAY[sid]
        if sid == "lock":
            cap = format(cfg.net_max, "f") if cfg.net_max is not None else ""
            if not cap:
                try:
                    import live_lock_orders

                    cap = live_lock_orders.send_line()
                except Exception:
                    cap = "0.984"
            name = f"Lock gap (cap {cap})"
        if sid == "spread_t0":
            name = "T0 spreads (on except NFL)"
        rows.append({
            "id": sid,
            "letter": LETTER[sid],
            "name": name,
            "on": "on" if cfg.on else "off",
            "stake": format(cfg.stake_usd, "f"),
            "size": str(cfg.size),
            "max_open": str(cfg.max_open),
            "open": open_now_display(currently_open(sid, snapshot=snapshot, positions=positions)),
            "pid": pid_text,
            "extra_pids": extra,
            "last": last_action(sid),
            "alive": (
                bool(pids)
                if sid != "lock"
                else bool(jobs.get("lock_sender") or [])
            ),
        })
    return rows


def format_status_table(rows: list[dict] | None = None) -> str:
    rows = rows if rows is not None else status_rows()
    headers = (
        f"{'Sys':<4} {'Name':<28} {'On':<4} {'Stake':>6} {'Size':>4} "
        f"{'Max':>4} {'Open':>8} {'PID':>8} Last"
    )
    lines = ["Systems A-G  ($1 ~ 1 contract at these prices)", headers, "-" * len(headers)]
    for row in rows:
        lines.append(
            f"{row['letter']:<4} {row['name']:<28} {row['on']:<4} {row['stake']:>6} "
            f"{row['size']:>4} {row['max_open']:>4} {str(row['open']):>8} "
            f"{str(row['pid']):>8} {row['last']}"
        )
        if row.get("extra_pids"):
            lines.append(f"     extra pids {row['extra_pids']}")
    return "\n".join(lines)


def ensure_live_bots(jobs: dict | None = None) -> list[str]:
    """Start C/D/E/F/G/B when on and dead. Never a second B. Does not restart lock.

    F stays off until Paul runs --tennis-t0-spread on. G stays off until Paul
    runs --soccer-t0-total on. Default config is off.
    """
    jobs = classify_jobs(jobs)
    started = []
    for sid in LIVE_BOT_IDS:
        if ensure_system(sid, jobs):
            started.append(sid)
            jobs = classify_jobs()
    return started


def systems_cli(argv: list[str]) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    path = Path(ns.config) if ns.config else CONFIG_PATH
    try:
        updates = flags_touched(ns)
    except ValueError as exc:
        print(exc)
        return 2
    notes = []
    if updates:
        _cfgs, notes = apply_updates(
            updates,
            path=path,
            spawn=not ns.no_apply,
        )
    else:
        load_config(path)
    rows = status_rows()

    def emit(text: str) -> None:
        payload = str(text)
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            print(payload)
        except UnicodeEncodeError:
            print(payload.encode(enc, "replace").decode(enc, "replace"))

    emit(format_status_table(rows))
    if notes:
        emit("")
        for note in notes:
            emit(note)
    emit(f"Config: {path}")
    emit("Double-click run_prediction_systems.bat for this table. Does not sell tickets.")
    return 0
