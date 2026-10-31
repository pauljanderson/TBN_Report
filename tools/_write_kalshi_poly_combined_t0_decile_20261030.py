"""Combined Kalshi + Polymarket hist T0 cheapest-ticket decile report.

Research display only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not leftover-GTC A.
Does not DailyRun. Does not retune live B/C/D/E. Does not rewrite dashboard.html.
Does not start a hist pull.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras  # noqa: E402
import t0_all_games_stats as t0  # noqa: E402
from compare_format import format_money  # noqa: E402
from kalshi_ticker_decode import CFB_TEAMS, NFL_TEAMS, decode_kalshi_ticker  # noqa: E402
from live_t0_yes import last_name_token  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP  # noqa: E402
from t0_fav_lt90_baseline_20261024 import (  # noqa: E402
    COMPARE_HEADERS as QUALITY_HEADERS,
    fmt_ann,
    fmt_num,
    fmt_pct,
    quality,
    quality_row,
)
from write_t0_band_from_stay_above import documented_leg_fee  # noqa: E402
import _write_sport_league_t0_decile_20261027 as decile_w  # noqa: E402

ET = ZoneInfo("America/New_York")
STAMP_SUB = STAMP / "kalshi_poly_combined_t0_decile_20261030"
PAGE = STAMP / "kalshi_poly_combined_t0_decile_20261030.html"
JSON_OUT = STAMP_SUB / "summary.json"
BASELINE = STAMP_SUB / "BASELINE.md"
PARENT_HTML = STAMP / "sport_league_t0_decile_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/kalshi_poly_combined_t0_decile_20261030.html"
)
HIST_DIR = LOCAL_STAMP / "hist"
IS_CUT = "2024-01-01"
MAX_GAP_SEC = 18 * 3600
DATE_SLACK_DAYS = 1
DECADES = decile_w.DECADES
STOP_NAME = {
    "van", "de", "da", "di", "le", "la", "el", "del", "von", "der", "the", "mc",
    "fc", "cf", "sc", "afc", "vs", "v", "and", "at", "of",
}
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_KDATE = re.compile(
    r"-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})",
    re.I,
)
_POLY_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_POLY_TEAMS = re.compile(
    r"^(?:aec-)?(nfl|cfb|ncaaf|nba|wnba|nhl|mlb|epl|mls|ucl)"
    r"-([a-z0-9]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})",
    re.I,
)
_CODE_ALIAS = {
    "wsh": "was", "jac": "jax", "lar": "la", "gs": "gsw", "no": "nop",
    "ny": "nyk", "sa": "sas", "pho": "phx", "brk": "bkn", "njn": "bkn",
    "cho": "cha", "uth": "uta", "sj": "sjs", "tb": "tbl", "nj": "njd",
    "mon": "mtl", "lv": "vgk", "veg": "vgk", "ari_nhl": "uta",
    "tbr": "tb", "sdp": "sd", "sfg": "sf", "kcr": "kc", "ath": "oak",
    "ncaaf": "cfb",
}

# Compact nickname maps so Poly “Eagles” meets Kalshi “Philadelphia”.
_EXTRA_TEAMS: dict[str, dict[str, str]] = {
    "pro football": NFL_TEAMS,
    "college football": CFB_TEAMS,
    "basketball": {
        "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
        "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
        "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
        "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
        "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
        "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
        "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
        "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
        "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
        "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
        "NYL": "New York Liberty", "LAS": "Los Angeles Sparks", "LVA": "Las Vegas Aces",
        "CON": "Connecticut Sun", "GSV": "Golden State Valkyries", "SEA": "Seattle Storm",
        "DALW": "Dallas Wings", "CHIW": "Chicago Sky", "ATL W": "Atlanta Dream",
        "PHO": "Phoenix Mercury", "MINW": "Minnesota Lynx", "INDW": "Indiana Fever",
        "WASW": "Washington Mystics",
    },
    "hockey": {
        "ANA": "Anaheim Ducks", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres",
        "CGY": "Calgary Flames", "CAR": "Carolina Hurricanes", "CHI": "Chicago Blackhawks",
        "COL": "Colorado Avalanche", "CBJ": "Columbus Blue Jackets", "DAL": "Dallas Stars",
        "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers", "FLA": "Florida Panthers",
        "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild", "MTL": "Montreal Canadiens",
        "NSH": "Nashville Predators", "NJD": "New Jersey Devils", "NYI": "New York Islanders",
        "NYR": "New York Rangers", "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers",
        "PIT": "Pittsburgh Penguins", "SJS": "San Jose Sharks", "SEA": "Seattle Kraken",
        "STL": "St Louis Blues", "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs",
        "UTA": "Utah Hockey Club", "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights",
        "WSH": "Washington Capitals", "WPG": "Winnipeg Jets",
    },
    "baseball": {
        "ARI": "Arizona Diamondbacks", "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
        "BOS": "Boston Red Sox", "CHC": "Chicago Cubs", "CWS": "Chicago White Sox",
        "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians", "COL": "Colorado Rockies",
        "DET": "Detroit Tigers", "HOU": "Houston Astros", "KC": "Kansas City Royals",
        "LAA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers", "MIA": "Miami Marlins",
        "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYM": "New York Mets",
        "NYY": "New York Yankees", "OAK": "Oakland Athletics", "PHI": "Philadelphia Phillies",
        "PIT": "Pittsburgh Pirates", "SD": "San Diego Padres", "SF": "San Francisco Giants",
        "SEA": "Seattle Mariners", "STL": "St Louis Cardinals", "TB": "Tampa Bay Rays",
        "TEX": "Texas Rangers", "TOR": "Toronto Blue Jays", "WSH": "Washington Nationals",
    },
}

ASKED = (
    "Paul (Fri 30 Oct 2026): can you run a combined declie report of combining "
    "both kalshi and polymarket historical data? if both have the same game on "
    "tape, take the least expensive of the 2. if they don't have the same game, "
    "just use the one. keep track of how many times kalshi is less expensive vs. "
    "polymarket. let me know the results by sport/bet type/ decile."
)
PLAIN = (
    "Two phone books of already-finished games sit on disk. Kalshi’s opening "
    "price is the Yes ask (the posted take-it price). Polymarket’s opening price "
    "on this hist tape is the last trade on the global Central Limit Order Book "
    "(CLOB) — not an ask, and not Polymarket US. If both shops listed the same "
    "game, same bet type (Moneyline / Spread / Points Total), and the same named "
    "Yes, we keep the cheaper ticket after the shop’s take-a-trade fee. If only "
    "one shop had it, we keep that one. Then we drop each kept ticket into a "
    "10-cent opening-price bucket and ask whether buying one Yes there, paying "
    "the fee, and holding to the result made money. Moneyline (ML) is who wins. "
    "Spread is whether a side covers a point line. Points Total is the over/under "
    "on combined score. Association of Tennis Professionals (ATP), Women’s Tennis "
    "Association (WTA), International Tennis Federation (ITF), National Football "
    "League (NFL), college football (CFB), National Basketball Association (NBA), "
    "National Hockey League (NHL), Major League Baseball (MLB), English Premier "
    "League (EPL), Ultimate Fighting Championship (UFC), and Professional Golfers’ "
    "Association (PGA) are whatever the books actually have. Live B/C/D/E knobs "
    "were not changed from this table."
)

CHEAP_HEADERS = [
    ("Slice", "text"),
    ("Dual N", "num"),
    ("Kalshi cheaper after-fee", "num"),
    ("Poly cheaper after-fee", "num"),
    ("Tie after-fee", "num"),
    ("% Kalshi cheaper", "num"),
    ("% Poly cheaper", "num"),
    ("Kalshi cheaper raw", "num"),
    ("Poly cheaper raw", "num"),
    ("Tie raw (same cent)", "num"),
]
NEAR50 = ("40-49", "50-59")


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def fnum(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x <= 0.0 or x >= 1.0:
        return None
    return x


def parse_line(value) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("+", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        m = re.search(r"(-?\d+(?:\.\d+)?)", text)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None


def line_key(value) -> str:
    n = parse_line(value)
    if n is None:
        return ""
    return f"{n:.1f}"


def same_cent(a: float, b: float) -> bool:
    return round(float(a) * 100.0) == round(float(b) * 100.0)


def after_fee_cash(venue: str, px: float) -> float | None:
    fee = documented_leg_fee(venue, px)
    if fee is None:
        return None
    return float(Decimal(str(px)) + Decimal(str(fee)))


def pid(name: str) -> str:
    text = str(name or "").strip()
    if "," in text:
        text = text.split(",", 1)[0]
    bits = [
        t for t in re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
        if t and t not in STOP_NAME and len(t) >= 3
    ]
    if bits:
        return bits[-1]
    return last_name_token(text)


def compact_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def names_equal(left: str, right: str) -> bool:
    a, b = str(left or "").strip(), str(right or "").strip()
    if not a or not b:
        return False
    if a.lower() == b.lower():
        return True
    pa, pb = pid(a), pid(b)
    if pa and pa == pb:
        return True
    ca, cb = compact_alnum(a), compact_alnum(b)
    if ca and ca == cb:
        return True
    if pa and (cb.endswith(pa) or ca.endswith(pb)):
        return True
    if pb and (ca.endswith(pb) or cb.endswith(pa)):
        return True
    return False


def _shift_date(iso: str, days: int) -> str:
    try:
        d = datetime.fromisoformat(str(iso)[:10]).date()
    except ValueError:
        return ""
    return (d + timedelta(days=days)).isoformat()


def parse_kalshi_date(ticker: str, entry_date: str) -> str:
    m = _KDATE.search(str(ticker or ""))
    if m:
        yy, mon, dd = int(m.group(1)), MONTHS[m.group(2).upper()], int(m.group(3))
        try:
            return datetime(2000 + yy, mon, dd).date().isoformat()
        except ValueError:
            pass
    return str(entry_date or "")[:10]


def parse_poly_date(slug: str, entry_date: str) -> str:
    m = _POLY_DATE.search(str(slug or ""))
    if m:
        return m.group(1)
    return str(entry_date or "")[:10]


def dates_close(a: str, b: str, slack: int = DATE_SLACK_DAYS) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    for d in range(1, slack + 1):
        if _shift_date(a, d) == b or _shift_date(a, -d) == b:
            return True
    return False


def _alias_maps() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = defaultdict(dict)

    def add(sport: str, code: str, *names: str) -> None:
        canon = str(code or "").strip().lower()
        if not canon:
            return
        bag = out[sport]
        bag[canon] = canon
        bag[_CODE_ALIAS.get(canon, canon)] = _CODE_ALIAS.get(canon, canon)
        for name in names:
            low = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
            if not low:
                continue
            bag[low] = canon
            bag[compact_alnum(low)] = canon
            bits = [t for t in low.split() if t not in STOP_NAME]
            if bits:
                bag[bits[-1]] = canon
                if len(bits[-1]) >= 3:
                    bag[bits[-1][:4]] = bag.get(bits[-1][:4], canon)

    for sport, mapping in _EXTRA_TEAMS.items():
        firsts: dict[str, list[str]] = defaultdict(list)
        for code, name in mapping.items():
            add(sport, code, name, code)
            first = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
            if first:
                firsts[first[0]].append(code.lower())
        for word, codes in firsts.items():
            uniq = {c for c in codes}
            if len(uniq) == 1 and word not in STOP_NAME:
                add(sport, next(iter(uniq)), word)
    # sport aliases share basketball map for WNBA rows labeled basketball
    out["wnba"] = dict(out.get("basketball") or {})
    return out


ALIAS = _alias_maps()


def team_canon(text: str, sport: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    sport_l = str(sport or "").lower()
    bag = ALIAS.get(sport_l) or {}
    key = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
    if key in bag:
        return bag[key]
    compact = compact_alnum(raw)
    if compact in bag:
        return bag[compact]
    aliased = _CODE_ALIAS.get(compact, compact)
    if aliased in bag:
        return bag[aliased]
    last = pid(raw)
    if last in bag:
        return bag[last]
    if compact:
        return aliased or compact
    return last


def poly_team_codes(slug: str) -> tuple[str, str, str] | None:
    m = _POLY_TEAMS.match(str(slug or "").strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2).lower(), m.group(3).lower()


def kalshi_team_codes(ticker: str, sport: str) -> tuple[str, str] | None:
    decoded = decode_kalshi_ticker(str(ticker or ""))
    if decoded.away_code and decoded.home_code:
        return team_canon(decoded.away_code, sport), team_canon(decoded.home_code, sport)
    text = str(ticker or "")
    m = _KDATE.search(text)
    if not m:
        return None
    rest = text[m.end():].lstrip("-")
    rest = rest.split("-")[0]
    # optional HHMM on MLB (26OCT262000MILTB)
    if len(rest) >= 8 and rest[:4].isdigit():
        rest = rest[4:]
    blob = re.sub(r"[^A-Za-z]", "", rest).upper()
    if len(blob) >= 4:
        for i in range(2, len(blob) - 1):
            left, right = blob[:i], blob[i:]
            if 2 <= len(left) <= 4 and 2 <= len(right) <= 4:
                return team_canon(left, sport), team_canon(right, sport)
        mid = len(blob) // 2
        return team_canon(blob[:mid], sport), team_canon(blob[mid:], sport)
    return None


def ou_of(name: str) -> str:
    low = str(name or "").lower()
    if "under" in low:
        return "under"
    if "over" in low:
        return "over"
    return ""


def signed_spread(name: str, number) -> float | None:
    n = parse_line(number)
    if n is None:
        n = parse_line(name)
    if n is None:
        return None
    low = str(name or "").lower()
    raw = str(number or "")
    if raw.startswith("+") or (n < 0 and "wins by" not in low):
        return n
    if any(tok in low for tok in ("wins by", "win by", "more than", "cover")):
        return -abs(n)
    return n


def yes_id(row: dict) -> str:
    kind = str(row.get("kind") or "moneyline")
    name = str(row.get("fav_name") or "")
    sport = str(row.get("sport") or "")
    if kind == "total":
        ou = ou_of(name)
        lk = line_key(row.get("number") or name)
        return f"total|{ou}|{lk}" if ou else ""
    if kind == "spread":
        team = team_canon(name.split(" wins")[0].split(" win")[0], sport)
        if not team:
            team = pid(name)
        signed = signed_spread(name, row.get("number"))
        lk = f"{signed:.1f}" if signed is not None else line_key(row.get("number"))
        return f"spread|{team}|{lk}"
    if sport.lower() in {"tennis", "mma", "golf"}:
        token = pid(name)
        return f"ml|{token}" if token else ""
    if name.strip().lower() in {"yes", "no", "tie"}:
        return ""
    team = team_canon(name, sport)
    return f"ml|{team or pid(name)}"


def game_tokens_from_sides(sides: list[dict], sport: str) -> frozenset[str]:
    names = [str(s.get("fav_name") or "") for s in sides]
    if sport.lower() in {"tennis", "mma"}:
        ids = {pid(n) for n in names if pid(n) and str(n).strip().lower() not in {"yes", "no", "tie"}}
        return frozenset(x for x in ids if x)
    ids = set()
    for n in names:
        if str(n).strip().lower() in {"yes", "no", "tie", "over", "under"}:
            continue
        if ou_of(n):
            continue
        token = team_canon(str(n).split(" wins")[0].split(" win")[0], sport)
        if token:
            ids.add(token)
    return frozenset(ids)


def event_is_three_way(sides: list[dict]) -> bool:
    for row in sides:
        name = str(row.get("fav_name") or "").strip().lower()
        ticker = str(row.get("ticker") or "").upper()
        if name == "tie" or ticker.endswith("-TIE") or "-TIE" in ticker:
            return True
    return False


def attach_event_keys(rows: list[dict]) -> tuple[list[dict], dict]:
    """Annotate each valid T0 side with date / game tokens / yes id / after-fee cash."""
    bags: dict[tuple, list[dict]] = defaultdict(list)
    n_skip_px = 0
    n_skip_fee = 0
    n_skip_void = 0
    for raw in rows:
        if raw.get("void"):
            n_skip_void += 1
            continue
        px = fnum(raw.get("t0_fav") if raw.get("t0_fav") is not None else raw.get("t0_a"))
        if px is None:
            n_skip_px += 1
            continue
        venue = str(raw.get("venue") or "").strip().lower()
        cash = after_fee_cash(venue, px)
        if cash is None:
            n_skip_fee += 1
            continue
        row = dict(raw)
        row["t0_fav"] = px
        row["t0_a"] = px
        row["_cash"] = cash
        row["_venue"] = venue
        sport = str(row.get("sport") or "unknown")
        kind = str(row.get("kind") or "moneyline")
        if venue.startswith("poly"):
            row["_date"] = parse_poly_date(row.get("game") or row.get("game_n") or "", row.get("entry_date") or "")
        else:
            row["_date"] = parse_kalshi_date(row.get("ticker") or row.get("game") or "", row.get("entry_date") or "")
        bags[(sport.lower(), str(row.get("game_n") or row.get("game") or ""), kind)].append(row)

    out = []
    n_three_way = 0
    for (sport, _game, kind), group in bags.items():
        three = event_is_three_way(group)
        if three:
            n_three_way += 1
        tokens = game_tokens_from_sides(group, sport)
        # ticker/slug codes fill in when names are Over/Under or Yes/No
        for row in group:
            codes = None
            if str(row.get("venue") or "").lower().startswith("poly"):
                parsed = poly_team_codes(str(row.get("game") or row.get("game_n") or ""))
                if parsed:
                    codes = (
                        team_canon(parsed[1], sport),
                        team_canon(parsed[2], sport),
                    )
            else:
                codes = kalshi_team_codes(str(row.get("ticker") or row.get("game") or ""), sport)
            game_ids = set(tokens)
            if codes:
                game_ids.update(c for c in codes if c)
            row["_game_ids"] = frozenset(game_ids)
            row["_three_way"] = three
            row["_yes_id"] = yes_id(row)
            row["_kind"] = kind
            date = str(row.get("_date") or row.get("entry_date") or "")
            ids = "|".join(sorted(row["_game_ids"]))
            row["_market"] = (
                f"{sport}|{kind}|{date}|{ids}|{line_key(row.get('number'))}"
            )
            out.append(row)
    stats = {
        "n_in": len(rows),
        "n_ok": len(out),
        "n_skip_px": n_skip_px,
        "n_skip_fee": n_skip_fee,
        "n_skip_void": n_skip_void,
        "n_three_way_events": n_three_way,
    }
    return out, stats


def _game_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 2 and len(b) >= 2 and len(a & b) >= 2:
        return True
    # tennis slug compact vs last-name: one shared last name is not enough;
    # require both names via containment
    if len(a) == 2 and len(b) == 2:
        hits = 0
        for x in a:
            if any(x == y or x.endswith(y) or y.endswith(x) or compact_alnum(x) == compact_alnum(y) for y in b):
                hits += 1
        return hits >= 2
    return False


def match_dual(kalshi: list[dict], poly: list[dict]) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Pair same settlement. Conservative: require yes_id + overlapping game tokens + date."""
    index: dict[tuple, list[dict]] = defaultdict(list)
    for row in poly:
        yes = row.get("_yes_id") or ""
        kind = row.get("_kind") or "moneyline"
        sport = str(row.get("sport") or "").lower()
        if not yes:
            continue
        if row.get("_three_way"):
            continue
        index[(sport, kind, yes)].append(row)

    matched = []
    used: set[int] = set()
    n_no_yes = 0
    n_no_cand = 0
    n_date = 0
    n_game = 0
    n_winner = 0
    n_ambiguous = 0
    leftover_k = []
    for krow in kalshi:
        yes = krow.get("_yes_id") or ""
        if not yes:
            n_no_yes += 1
            leftover_k.append(krow)
            continue
        sport = str(krow.get("sport") or "").lower()
        kind = krow.get("_kind") or "moneyline"
        cands = [c for c in index.get((sport, kind, yes), []) if id(c) not in used]
        if not cands:
            n_no_cand += 1
            leftover_k.append(krow)
            continue
        kdate = str(krow.get("_date") or "")
        dated = [c for c in cands if dates_close(kdate, str(c.get("_date") or ""))]
        if not dated:
            n_date += 1
            leftover_k.append(krow)
            continue
        kids = krow.get("_game_ids") or frozenset()
        gamed = [c for c in dated if _game_overlap(kids, c.get("_game_ids") or frozenset())]
        if not gamed:
            n_game += 1
            leftover_k.append(krow)
            continue
        kts = krow.get("t0_ts")
        if kts:
            with_ts = [c for c in gamed if c.get("t0_ts")]
            pool = with_ts or gamed
            if with_ts:
                pool = sorted(with_ts, key=lambda c: abs(int(c["t0_ts"]) - int(kts)))
                if abs(int(pool[0]["t0_ts"]) - int(kts)) > MAX_GAP_SEC:
                    pool = [c for c in gamed if not c.get("t0_ts")] or []
        else:
            pool = gamed
        if not pool:
            n_date += 1
            leftover_k.append(krow)
            continue
        if len(pool) > 1 and not kts:
            # same date + same yes without a clock: only take if unique game overlap is unique
            best = [c for c in pool if (c.get("_game_ids") or frozenset()) == kids]
            pool = best or pool
        if len(pool) > 1:
            # still ambiguous if two equally close
            if kts and pool[0].get("t0_ts") and len(pool) > 1:
                g0 = abs(int(pool[0]["t0_ts"]) - int(kts))
                g1 = abs(int(pool[1]["t0_ts"]) - int(kts)) if pool[1].get("t0_ts") else 10**12
                if g0 == g1:
                    n_ambiguous += 1
                    leftover_k.append(krow)
                    continue
            elif not kts:
                n_ambiguous += 1
                leftover_k.append(krow)
                continue
        chosen = pool[0]
        kw = bool(krow.get("fav_won"))
        pw = bool(chosen.get("fav_won"))
        if kw != pw:
            n_winner += 1
            leftover_k.append(krow)
            continue
        used.add(id(chosen))
        union = (krow.get("_game_ids") or frozenset()) | (chosen.get("_game_ids") or frozenset())
        k_use = dict(krow)
        p_use = dict(chosen)
        k_use["_game_ids"] = union
        p_use["_game_ids"] = union
        if k_use.get("_date") and p_use.get("_date"):
            p_use["_date"] = k_use["_date"]
        matched.append((k_use, p_use))
    leftover_p = [r for r in poly if id(r) not in used]
    stats = {
        "n_kalshi": len(kalshi),
        "n_poly": len(poly),
        "n_dual": len(matched),
        "n_kalshi_only": len(leftover_k),
        "n_poly_only": len(leftover_p),
        "n_no_yes_id": n_no_yes,
        "n_no_candidate": n_no_cand,
        "n_date_miss": n_date,
        "n_game_miss": n_game,
        "n_winner_disagree": n_winner,
        "n_ambiguous": n_ambiguous,
        "match_rate_k": (100.0 * len(matched) / len(kalshi)) if kalshi else None,
        "match_rate_p": (100.0 * len(matched) / len(poly)) if poly else None,
    }
    return matched, leftover_k, leftover_p, stats


def cheaper_cmp(k_cash: float, p_cash: float, k_raw: float, p_raw: float) -> tuple[str, str]:
    """Return (after_fee_label, pick_venue). Tie pick: lower raw, then Kalshi."""
    k4, p4 = round(float(k_cash), 4), round(float(p_cash), 4)
    if k4 < p4:
        af = "kalshi"
    elif p4 < k4:
        af = "poly"
    else:
        af = "tie"
    if af == "kalshi":
        pick = "kalshi"
    elif af == "poly":
        pick = "poly"
    elif float(k_raw) + 1e-12 < float(p_raw) and not same_cent(k_raw, p_raw):
        pick = "kalshi"
    elif float(p_raw) + 1e-12 < float(k_raw) and not same_cent(k_raw, p_raw):
        pick = "poly"
    else:
        pick = "kalshi"
    return af, pick


def raw_cmp(k_raw: float, p_raw: float) -> str:
    if same_cent(k_raw, p_raw):
        return "tie"
    if float(k_raw) < float(p_raw):
        return "kalshi"
    return "poly"


def stamp_selected(row: dict, *, listing: str, source_venue: str, dual: dict | None = None) -> dict:
    out = dict(row)
    out["_listing"] = listing
    out["_source_venue"] = source_venue
    out["venue"] = source_venue
    sport = str(out.get("sport") or "unknown")
    kind = str(out.get("kind") or "moneyline")
    date = str(out.get("_date") or out.get("entry_date") or "")
    ids = "|".join(sorted(out.get("_game_ids") or []))
    yes = out.get("_yes_id") or pid(out.get("fav_name") or "")
    out["game_n"] = f"{sport}|{kind}|{date}|{ids}|{yes}"
    out["_market"] = f"{sport}|{kind}|{date}|{ids}|{line_key(out.get('number'))}"
    if dual:
        out["_dual"] = dual
    return out


def select_combined(
    matched: list[tuple[dict, dict]],
    leftover_k: list[dict],
    leftover_p: list[dict],
) -> tuple[list[dict], dict]:
    selected = []
    n_k_af = n_p_af = n_tie_af = 0
    n_k_raw = n_p_raw = n_tie_raw = 0
    by: dict[tuple, dict] = defaultdict(lambda: {
        "dual": 0, "k_af": 0, "p_af": 0, "tie_af": 0, "k_raw": 0, "p_raw": 0, "tie_raw": 0,
    })
    for krow, prow in matched:
        k_px, p_px = float(krow["t0_fav"]), float(prow["t0_fav"])
        k_cash, p_cash = float(krow["_cash"]), float(prow["_cash"])
        af, pick = cheaper_cmp(k_cash, p_cash, k_px, p_px)
        raw = raw_cmp(k_px, p_px)
        if af == "kalshi":
            n_k_af += 1
        elif af == "poly":
            n_p_af += 1
        else:
            n_tie_af += 1
        if raw == "kalshi":
            n_k_raw += 1
        elif raw == "poly":
            n_p_raw += 1
        else:
            n_tie_raw += 1
        sport = str(krow.get("sport") or prow.get("sport") or "")
        kind = str(krow.get("kind") or prow.get("kind") or "moneyline")
        rec = by[(sport, kind)]
        rec["dual"] += 1
        rec["k_af"] += int(af == "kalshi")
        rec["p_af"] += int(af == "poly")
        rec["tie_af"] += int(af == "tie")
        rec["k_raw"] += int(raw == "kalshi")
        rec["p_raw"] += int(raw == "poly")
        rec["tie_raw"] += int(raw == "tie")
        chosen = krow if pick == "kalshi" else prow
        other = prow if pick == "kalshi" else krow
        dual = {
            "af": af,
            "raw": raw,
            "pick": pick,
            "k_px": k_px,
            "p_px": p_px,
            "k_cash": k_cash,
            "p_cash": p_cash,
            "other_venue": str(other.get("venue") or ""),
            "other_px": float(other["t0_fav"]),
        }
        selected.append(stamp_selected(chosen, listing="dual", source_venue=pick if pick != "poly" else "polymarket", dual=dual))
        if pick == "poly":
            selected[-1]["venue"] = "polymarket"
            selected[-1]["_source_venue"] = "polymarket"
    for row in leftover_k:
        selected.append(stamp_selected(row, listing="kalshi_only", source_venue="kalshi"))
    for row in leftover_p:
        selected.append(stamp_selected(row, listing="poly_only", source_venue="polymarket"))
    counts = {
        "dual_n": len(matched),
        "kalshi_cheaper_af": n_k_af,
        "poly_cheaper_af": n_p_af,
        "tie_af": n_tie_af,
        "kalshi_cheaper_raw": n_k_raw,
        "poly_cheaper_raw": n_p_raw,
        "tie_raw": n_tie_raw,
        "by_sport_kind": {f"{s}|{k}": v for (s, k), v in sorted(by.items())},
        "by": [{"sport": s, "kind": k, **v} for (s, k), v in sorted(by.items())],
        "n_combined": len(selected),
        "n_kalshi_only": len(leftover_k),
        "n_poly_only": len(leftover_p),
    }
    return selected, counts


def pick_cheaper_yes(sides: list[dict]) -> list[dict]:
    bags: dict[str, list[dict]] = defaultdict(list)
    for row in sides:
        key = str(row.get("_market") or "")
        if not key:
            key = (
                f"{str(row.get('sport') or '').lower()}|{row.get('kind') or 'moneyline'}|"
                f"{row.get('game_n') or row.get('game') or ''}|{row.get('number') or ''}"
            )
        bags[key].append(row)
    out = []
    n_tie = 0
    for group in bags.values():
        ordered = sorted(group, key=lambda s: (float(s["t0_fav"]), str(s.get("fav_name") or "")))
        lo = ordered[0]
        if len(ordered) >= 2:
            hi = ordered[-1]
            if abs(float(hi["t0_fav"]) - float(lo["t0_fav"])) <= 1e-12:
                n_tie += 1
                continue
        elif float(lo["t0_fav"]) >= 0.50 - 1e-12:
            continue
        row = dict(lo)
        row["_slice"] = "cheaper_yes"
        out.append(row)
    return out


def pick_named_yes(sides: list[dict]) -> list[dict]:
    out = []
    for row in sides:
        copy = dict(row)
        copy["_slice"] = "named_yes"
        out.append(copy)
    return out


def score_sides(sides: list[dict], *, arm: str) -> dict:
    tables = decile_w.build_tables(sides)
    trades = []
    for row in sides:
        trade = decile_w.yes_trade(row)
        if trade is not None:
            trades.append(trade)
    q = quality(trades, arm_id=arm, label=arm, grain="unique-game-side") if trades else {}
    tables["quality"] = q
    tables["n_trades_fee"] = len(trades)
    return tables


def cheap_rows(counts: dict) -> list[list[str]]:
    dual = int(counts.get("dual_n") or 0)

    def pct(part) -> str:
        if not dual:
            return "—"
        return f"{100.0 * int(part) / dual:.1f}%"

    rows = [[
        "ALL dual-listed",
        str(dual),
        str(counts.get("kalshi_cheaper_af") or 0),
        str(counts.get("poly_cheaper_af") or 0),
        str(counts.get("tie_af") or 0),
        pct(counts.get("kalshi_cheaper_af") or 0),
        pct(counts.get("poly_cheaper_af") or 0),
        str(counts.get("kalshi_cheaper_raw") or 0),
        str(counts.get("poly_cheaper_raw") or 0),
        str(counts.get("tie_raw") or 0),
    ]]
    for rec in counts.get("by") or []:
        n = int(rec.get("dual") or 0)
        def lp(part, whole=n) -> str:
            if not whole:
                return "—"
            return f"{100.0 * int(part) / whole:.1f}%"
        rows.append([
            f"{rec.get('sport')} · {decile_w.kind_label(rec.get('kind') or '')}",
            str(n),
            str(rec.get("k_af") or 0),
            str(rec.get("p_af") or 0),
            str(rec.get("tie_af") or 0),
            lp(rec.get("k_af") or 0),
            lp(rec.get("p_af") or 0),
            str(rec.get("k_raw") or 0),
            str(rec.get("p_raw") or 0),
            str(rec.get("tie_raw") or 0),
        ])
    return rows


def near50_rows(cells: dict) -> list[list[str]]:
    rows = []
    # overall
    for band in NEAR50 + ("ALL",):
        rec = cells.get(("ALL", "ALL", "ALL", band if band != "ALL" else "ALL")) or {}
        if band != "ALL" and not rec:
            rec = {}
        n = int(rec.get("n") or 0)
        n_fee = int(rec.get("n_fee") or 0)
        avg = rec.get("avg_pnl")
        green = avg is not None and float(avg) > 0
        rows.append([
            "ALL",
            "ALL bet types",
            band if band != "ALL" else "ALL deciles",
            str(n),
            fmt_pct(rec.get("win_pct")) if n else "—",
            decile_w.money_cell(avg, n_fee=n_fee),
            decile_w.money_cell(rec.get("pnl_sum"), n_fee=n_fee),
            "green after fees" if green else ("flat/red after fees" if n_fee else "—"),
        ])
    # by sport × kind × near-50
    for (sport, league, kind, band), rec in sorted(cells.items()):
        if league != "ALL" or kind in ("", "ALL") or sport in ("", "ALL"):
            continue
        if band not in NEAR50:
            continue
        n = int(rec.get("n") or 0)
        if not n:
            continue
        n_fee = int(rec.get("n_fee") or 0)
        avg = rec.get("avg_pnl")
        green = avg is not None and float(avg) > 0
        rows.append([
            sport,
            decile_w.kind_label(kind),
            band,
            str(n),
            fmt_pct(rec.get("win_pct")),
            decile_w.money_cell(avg, n_fee=n_fee),
            decile_w.money_cell(rec.get("pnl_sum"), n_fee=n_fee),
            "green after fees" if green else "flat/red after fees",
        ])
    return rows


def arm_quality_rows(arms: dict[str, dict], control_id: str) -> list[list[str]]:
    control_q = (arms.get(control_id) or {}).get("quality") or {}
    rows = []
    for name, tables in arms.items():
        q = tables.get("quality") or {}
        if not q:
            continue
        row = quality_row(q, control_q if name != control_id else None)
        row[0] = esc(name)
        rows.append(row)
    return rows


def freeze_rows() -> list[list[str]]:
    return [
        ["Kalshi hist", "books_kalshi.json — T0 Yes-ask (1-min yes_ask.close), ~131,590 settled sides before 0&lt;p&lt;1 filter"],
        ["Polymarket hist", "books_poly.json — T0 last-trade on global CLOB, not Yes-ask, not Polymarket US, ~62,110 settled sides"],
        ["Sportsbooks", "Not mixed. Odds API closes are out."],
        ["Same settlement", "Same sport + bet type + named Yes + overlapping game tokens (last names / team codes / slug-vs-ticker) + date ±1 day + T0 clock ≤ 18h. Winner must agree."],
        ["Least expensive", "After-fee cash. Kalshi 0.07×p×(1−p). Polymarket house theta 0.0695×p×(1−p) rounded to a cent."],
        ["Tie rule", "After-fee rounded to 4 decimals. Tie counted separately. Pick lower raw T0, then Kalshi."],
        ["Decile", "0-based 10¢ buckets on the selected T0 quote (Kalshi ask-before-fee, Poly last-trade). Not after-fee cash. House 0–9 … 90–99."],
        ["Main book", "Named cheaper Yes per market (one row, usually 0–49). Ties skipped."],
        ["Both-sides book", "Every selected named Yes after venue pick."],
        ["Exit", "Hold to settlement (binary $1 / $0). With-fee P&L = 1 − ask − fee on a win, else −ask − fee."],
        ["IS / OOS", "IS = entry_date &lt; 2024-01-01; OOS ≥ 2024-01-01. This tape starts Apr 2025 so IS is empty. Do not retune on OOS."],
        ["Ann ROR", "House compare_format.ann_ror_from_closed / overlay. Hist end_ts = T0 so average days held is ~0 — Ann ROR omitted (same-day overflow guard)."],
        ["Live knobs", "HOLD. Did not start a second B, leftover-GTC A, DailyRun, or retune B/C/D/E."],
        ["T0=1.00 rows", "Dropped. Fee formula needs 0&lt;p&lt;1; a $1 candle is settlement, not an opening ask."],
    ]


def write_baseline(payload: dict, now: str) -> None:
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    counts = payload.get("counts") or {}
    match = payload.get("match") or {}
    k_stats = payload.get("k_stats") or {}
    p_stats = payload.get("p_stats") or {}
    cheap = payload.get("cheap_grand") or {}
    near = payload.get("near50_note") or ""
    text = f"""# Combined Kalshi + Polymarket T0 cheapest-ticket decile — freeze

Written {now}. Report only. Live B/C/D/E knobs were not patched.

## What you asked

{ASKED}

## In plain English

{PLAIN}

## Freeze

- **Data:** Kalshi hist `books_kalshi.json` (T0 **Yes-ask**) + Poly hist `books_poly.json` (T0 **last-trade, not ask**). Do not mix sportsbooks.
- **Kalshi kept:** {k_stats.get('n_ok')} of {k_stats.get('n_in')} (skipped px not in (0,1): {k_stats.get('n_skip_px')}; fee unknown: {k_stats.get('n_skip_fee')}).
- **Poly kept:** {p_stats.get('n_ok')} of {p_stats.get('n_in')} (skipped px not in (0,1): {p_stats.get('n_skip_px')}).
- **Match:** same sport + moneyline/spread/total + same named Yes + overlapping game tokens (tennis last names, NFL/NBA/NHL/MLB/CFB slug-vs-ticker codes) + date ±1 + T0 ≤ 18h. Winner must agree. Soccer 3-way Tie vs Poly Yes/No is not the same settlement — left unmatched.
- **Dual N:** {counts.get('dual_n')}
- **Kalshi-only / Poly-only leftovers:** {counts.get('n_kalshi_only')} / {counts.get('n_poly_only')}
- **Match rate:** Kalshi {match.get('match_rate_k')}% of valid Kalshi sides; Poly {match.get('match_rate_p')}% of valid Poly sides.
- **Unmatched reasons:** no Yes-id {match.get('n_no_yes_id')}; no candidate {match.get('n_no_candidate')}; date miss {match.get('n_date_miss')}; game-token miss {match.get('n_game_miss')}; winner disagree {match.get('n_winner_disagree')}; ambiguous {match.get('n_ambiguous')}.
- **Least expensive:** after-fee cash. Kalshi 0.07×p×(1−p). Poly house theta. Ties (4-decimal after-fee) counted separately; pick lower raw then Kalshi.
- **Kalshi cheaper vs Poly cheaper vs tie (dual, after-fee):** {counts.get('kalshi_cheaper_af')} / {counts.get('poly_cheaper_af')} / {counts.get('tie_af')}
- **Raw-price cheaper (same cent = tie):** {counts.get('kalshi_cheaper_raw')} / {counts.get('poly_cheaper_raw')} / {counts.get('tie_raw')}
- **Decile:** selected T0 quote before fee (Kalshi ask, Poly last-trade), house 0–9 … 90–99.
- **Main identity:** cheaper named Yes per market. Both-sides table is secondary.
- **Exit:** hold to settlement. With-fee avg P&L / WR / N.
- **IS / OOS:** entry_date &lt; 2024-01-01 vs ≥ 2024-01-01. Book starts Apr 2025 — IS N=0. Do not retune on OOS. Quality over N. Do not judge on max single-trade PnL.
- **Ann ROR:** house formula; omitted because hist end_ts = T0 (same-day).
- **Live knobs:** HOLD. Did not start a second B, leftover-GTC A, DailyRun, or rewrite dashboard.html.

## Cheaper-Yes combined grand

- N={cheap.get('n')} wins={cheap.get('n_win')} win%={cheap.get('win_pct')} with-fee P&L={cheap.get('pnl_sum')} avg={cheap.get('avg_pnl')}

## Near-50 after fees

{near}

## Selection

Do not pick a live band from this table. HOLD C/D/E/B.
"""
    BASELINE.write_text(text, encoding="utf-8")


def write_html(payload: dict, *, now: str) -> str:
    counts = payload.get("counts") or {}
    match = payload.get("match") or {}
    cheap_t = payload.get("cheap_tables") or {}
    both_t = payload.get("both_tables") or {}
    arms = payload.get("arms") or {}
    k_stats = payload.get("k_stats") or {}
    p_stats = payload.get("p_stats") or {}
    cheap_grand = cheap_t.get("grand") or {}
    dual = int(counts.get("dual_n") or 0)
    k_af = int(counts.get("kalshi_cheaper_af") or 0)
    p_af = int(counts.get("poly_cheaper_af") or 0)
    t_af = int(counts.get("tie_af") or 0)
    near_tbl = t0.table(
        [
            ("Sport", "text"), ("Bet type", "text"), ("Decile", "text"),
            ("N", "num"), ("Win%", "num"), ("With-fee avg P&L", "num"),
            ("With-fee total P&L", "num"), ("After fees", "text"),
        ],
        near50_rows(cheap_t.get("cells") or {}),
    )
    quality_tbl = t0.table(QUALITY_HEADERS, arm_quality_rows(arms, "Combined (dual-min + singles)"))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Kalshi + Polymarket combined T0 cheapest-ticket decile</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Kalshi + Polymarket combined T0 cheapest-ticket decile</h1>
<p class="note">Written {esc(now)}. Did not retune live A–E. Did not start a second B. Did not leftover-GTC A. Did not DailyRun. Did not rewrite dashboard.html.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout"><h2>Quote type — do not read Poly hist as an ask</h2>
<p>Kalshi history is a T0 <strong>Yes ask</strong> (1-minute yes_ask.close at the venue clock).
Polymarket history is a T0 <strong>last trade</strong> on the global CLOB (clob.polymarket.com),
not a Yes ask and not Polymarket US. “Least expensive” still uses each shop’s documented
taker fee on that quoted price. We did not mix sportsbook closes.</p></div>

<div class="callout"><h2>Freeze</h2>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table([("Knob", "text"), ("Value", "text")], freeze_rows())}
</div>

<div class="callout"><h2>Match rate</h2>
<p>Valid T0 in (0,1) exclusive: Kalshi {esc(k_stats.get('n_ok'))} of {esc(k_stats.get('n_in'))}
(dropped {esc(k_stats.get('n_skip_px'))} with p=0 or p=1, mostly $1 post-settle candles).
Polymarket {esc(p_stats.get('n_ok'))} of {esc(p_stats.get('n_in'))}.</p>
<p>Dual-listed same settlement <strong>N={esc(dual)}</strong>
({esc(fmt_pct(match.get('match_rate_k')))} percent of valid Kalshi sides,
{esc(fmt_pct(match.get('match_rate_p')))} percent of valid Poly sides).
Kalshi-only leftovers {esc(counts.get('n_kalshi_only'))}.
Poly-only leftovers {esc(counts.get('n_poly_only'))}.
Winner-disagree skipped {esc(match.get('n_winner_disagree'))}.
Ambiguous skipped {esc(match.get('n_ambiguous'))}.
Soccer 3-way (Kalshi Tie) is not paired with Polymarket Yes/No — different settlement.
Tennis last-name set + date; NFL/CFB/NBA/NHL/MLB slug-vs-ticker codes; totals Over/Under + line.
Click column headers to sort.</p></div>

<h2>1. Kalshi cheaper vs Polymarket cheaper vs tie (dual-listed only)</h2>
<p class="note">After-fee cash is the pick rule. Raw-price counts are the same dual set without fees
(same cent = tie). Combined book N={esc(counts.get('n_combined'))} = dual {esc(dual)}
+ Kalshi-only {esc(counts.get('n_kalshi_only'))} + Poly-only {esc(counts.get('n_poly_only'))}.
<strong>After-fee: Kalshi cheaper {esc(k_af)}, Polymarket cheaper {esc(p_af)}, tie {esc(t_af)}.</strong></p>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(CHEAP_HEADERS, cheap_rows(counts))}

<h2>2. Combined cheaper-Yes vs Kalshi-only vs Poly-only vs dual-min</h2>
<p class="note">{esc(decile_w.KIND_NOTE)} Combined = dual-min after-fee plus unmatched leftovers.
Kalshi-only / Poly-only are the unblended valid tapes (no cross-shop pick).
Dual-min is the overlap slice only. Grain is named cheaper Yes per market.
Canonical compare metrics; annualized rate of return (Ann ROR) uses the house formula
and is omitted here because hist holds are same-day (end clock = T0).
IS is empty — the book starts April 2025, after 2024-01-01. Do not retune on OOS.
Do not judge on max single-trade P&amp;L. Quality over N. Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{quality_tbl}

<h2>3. Combined cheaper Yes — sport × bet type × decile</h2>
<p class="note">One named cheaper Yes per market after the venue pick. Decile is the selected T0
quote (Kalshi ask-before-fee / Poly last-trade), house 0–9 through 90–99.
Win% is how often that named side won. With-fee P&amp;L is buy one Yes, pay the documented
taker fee, hold to settlement. Click column headers to sort.</p>
<p class="note">{esc(decile_w.book_blurb(cheap_t, label="Cheaper-Yes combined"))}</p>
{report_page_extras.SWIPE_NOTE_HTML}
<h3>All sports — each decile</h3>
{t0.table(decile_w.HEADERS, cheap_t.get("all_decile") or [])}
<h3>Sport × bet type × decile</h3>
{t0.table(decile_w.HEADERS, cheap_t.get("sport_decile") or [])}
<h3>Sport × league × bet type × decile</h3>
{t0.table(decile_w.HEADERS, cheap_t.get("detail") or [])}
<h3>Overall (rollups)</h3>
{t0.table(decile_w.HEADERS, cheap_t.get("overall") or [])}

<h2>Near 50¢ — did the coin-flip bucket make money after fees?</h2>
<p class="note">40–49 and 50–59 on the cheaper-Yes combined book. Green means with-fee average P&amp;L &gt; 0.
All-sports deciles 0–9 through 90–99 are red after fees on that combined book. Some sport × bet-type
buckets are green (hockey moneyline 40–49, NFL moneyline 10–39, a few basketball slices) — quality over N,
do not pick a live band from a green cell. Dual-min only (overlap slice) is a tiny average plus; that is
selection on games both shops listed, not a retune. Small N is still small N.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{near_tbl}

<h2>4. Combined both named Yes sides — sport × bet type × decile</h2>
<p class="note">Same venue pick, but favorite and dog both stay. This is how 90–99 exists.
Not the main book. {esc(decile_w.book_blurb(both_t, label="Both-sides combined"))}</p>
{report_page_extras.SWIPE_NOTE_HTML}
<h3>All sports — each decile</h3>
{t0.table(decile_w.HEADERS, both_t.get("all_decile") or [])}
<h3>Sport × bet type × decile</h3>
{t0.table(decile_w.HEADERS, both_t.get("sport_decile") or [])}

<p class="tiny">Parent: <a href="sport_league_t0_decile_20261027.html">sport / league / T0 decile (27 Oct)</a>
(unblended Kalshi vs Poly books). Generator:
<code>tools/_write_kalshi_poly_combined_t0_decile_20261030.py</code>.
Fees: <code>write_t0_band_from_stay_above.documented_leg_fee</code>.
File URL {esc(FILE_URL)}.
Did not sell, start a second B, leftover-GTC A, DailyRun, or retune C/D/E.
Did not mix Odds API / sportsbook closes.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return str(PAGE)


def compact_grand(tables: dict) -> dict:
    g = tables.get("grand") or {}
    return {
        "n": g.get("n"),
        "n_win": g.get("n_win"),
        "win_pct": g.get("win_pct"),
        "n_fee": g.get("n_fee"),
        "pnl_sum": g.get("pnl_sum"),
        "avg_pnl": g.get("avg_pnl"),
        "ann_ror": g.get("ann_ror"),
        "ann_note": g.get("ann_note"),
        "is_note": g.get("is_note"),
        "n_is": (tables.get("quality") or {}).get("n_is"),
        "n_oos": (tables.get("quality") or {}).get("n_oos"),
    }


def near50_note(cells: dict) -> str:
    bits = []
    any_green = False
    for band in NEAR50:
        rec = cells.get(("ALL", "ALL", "ALL", band)) or {}
        avg = rec.get("avg_pnl")
        n = int(rec.get("n") or 0)
        green = avg is not None and float(avg) > 0
        any_green = any_green or green
        bits.append(
            f"{band} N={n} win%={fmt_pct(rec.get('win_pct')) if n else '—'} "
            f"avg={decile_w.money_cell(avg, n_fee=int(rec.get('n_fee') or 0))} "
            f"({'green' if green else 'not green'})"
        )
    return (
        "Cheaper-Yes combined near-50: " + "; ".join(bits) + ". "
        + ("At least one near-50 bucket is green after fees." if any_green else "Neither 40–49 nor 50–59 is green after fees on the combined cheaper-Yes book.")
    )


def link_parent_page() -> None:
    needle = 't0_buy_sell_gain_decile_sport_bet_20261030.html">T0 buy then sell at +G (30 Oct)</a>'
    extra = (
        needle
        + ' · <a href="kalshi_poly_combined_t0_decile_20261030.html">'
        + "Kalshi+Poly combined cheapest T0 (30 Oct)</a>"
    )
    if PARENT_HTML.is_file():
        html = PARENT_HTML.read_text(encoding="utf-8")
        if "kalshi_poly_combined_t0_decile_20261030.html" not in html and needle in html:
            PARENT_HTML.write_text(html.replace(needle, extra, 1), encoding="utf-8")
    src = ROOT / "tools" / "_write_sport_league_t0_decile_20261027.py"
    if src.is_file():
        py = src.read_text(encoding="utf-8")
        if "kalshi_poly_combined_t0_decile_20261030.html" not in py and needle in py:
            src.write_text(py.replace(needle, extra, 1), encoding="utf-8")


def dump_json(payload: dict, path: str) -> None:
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    out = {
        "counts": payload.get("counts"),
        "match": payload.get("match"),
        "k_stats": payload.get("k_stats"),
        "p_stats": payload.get("p_stats"),
        "cheap_grand": compact_grand(payload.get("cheap_tables") or {}),
        "both_grand": compact_grand(payload.get("both_tables") or {}),
        "near50_note": payload.get("near50_note"),
        "arms": {
            name: compact_grand(tables)
            for name, tables in (payload.get("arms") or {}).items()
        },
        "html": path,
        "poly_price_kind": "CLOB last-trade (not Yes ask)",
        "kalshi_price_kind": "1-min yes_ask candle close",
        "decile_on": "selected T0 quote before fee",
        "is_cut": IS_CUT,
    }
    JSON_OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")


def main() -> int:
    _out("loading hist books")
    k_raw = decile_w.load_json_list(HIST_DIR / "books_kalshi.json")
    p_raw = decile_w.load_json_list(HIST_DIR / "books_poly.json")
    _out(f"raw kalshi={len(k_raw)} poly={len(p_raw)}")
    k_sides, k_stats = attach_event_keys(k_raw)
    p_sides, p_stats = attach_event_keys(p_raw)
    _out(f"valid kalshi={k_stats['n_ok']} poly={p_stats['n_ok']}")
    matched, leftover_k, leftover_p, match = match_dual(k_sides, p_sides)
    _out(
        f"dual={match['n_dual']} k_only={match['n_kalshi_only']} p_only={match['n_poly_only']} "
        f"winner_disagree={match['n_winner_disagree']}"
    )
    selected, counts = select_combined(matched, leftover_k, leftover_p)
    cheap = pick_cheaper_yes(selected)
    both = pick_named_yes(selected)
    dual_rows = [r for r in selected if r.get("_listing") == "dual"]
    dual_cheap = pick_cheaper_yes(dual_rows)
    k_only_book = pick_cheaper_yes(k_sides)
    p_only_book = pick_cheaper_yes(p_sides)
    _out(f"scoring combined cheap={len(cheap)} both={len(both)} dual_cheap={len(dual_cheap)}")
    jobs = {
        "Combined (dual-min + singles)": cheap,
        "Kalshi-only (unblended)": k_only_book,
        "Poly-only (unblended last-trade)": p_only_book,
        "Dual-min only": dual_cheap,
    }
    arms: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(score_sides, rows, arm=name): name for name, rows in jobs.items()}
        both_fut = pool.submit(score_sides, both, arm="combined_both_sides")
        for fut, name in futs.items():
            arms[name] = fut.result()
            _out(f"scored {name} n={arms[name].get('n_settled')}")
        both_tables = both_fut.result()
    cheap_tables = arms["Combined (dual-min + singles)"]
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    payload = {
        "counts": counts,
        "match": match,
        "k_stats": k_stats,
        "p_stats": p_stats,
        "cheap_tables": cheap_tables,
        "both_tables": both_tables,
        "arms": arms,
        "cheap_grand": compact_grand(cheap_tables),
        "near50_note": near50_note(cheap_tables.get("cells") or {}),
    }
    path = write_html(payload, now=now)
    write_baseline(payload, now)
    dump_json(payload, path)
    link_parent_page()
    _out(
        f"wrote {path} dual={counts['dual_n']} "
        f"k_cheaper={counts['kalshi_cheaper_af']} p_cheaper={counts['poly_cheaper_af']} "
        f"tie={counts['tie_af']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
