"""Kalshi sports ticker → game names, market type, and who the $1 pays.

Kitchen overlay was printing the raw ticker and “Yes no 0.5300 Kalshi”
because Yes/No (the contract) was treated as the team. This helper parses
KXNFLGAME / KXNFLSPREAD / KXNFLTOTAL (and the CFB/NCAAF twins) into English.

Tennis MATCH tickers are left alone so “Yes Yuta Shimizu” stays intact.
Does not place, cancel, or sell. Does not print secrets. Not gold. Not DailyRun.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from prediction_paths import RAW_DIR as RAW

TITLE_CACHE = RAW / "kalshi_market_title_cache.json"

# National Football League (NFL) ticker codes as Kalshi concatenates them.
NFL_TEAMS: dict[str, str] = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAC": "Jacksonville Jaguars",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
    "WSH": "Washington Commanders",
}

# College football (NCAA FBS) codes we have seen on Kalshi KXNCAAF* / KXCFB*.
CFB_TEAMS: dict[str, str] = {
    "AFA": "Air Force",
    "AKR": "Akron",
    "ALA": "Alabama",
    "APP": "App State",
    "ARIZ": "Arizona",
    "ARK": "Arkansas",
    "ARMY": "Army",
    "ARST": "Arkansas State",
    "ASU": "Arizona State",
    "AUB": "Auburn",
    "BALL": "Ball State",
    "BAY": "Baylor",
    "BC": "Boston College",
    "BGSU": "Bowling Green",
    "BSU": "Boise State",
    "BUFF": "Buffalo",
    "BYU": "BYU",
    "CAL": "California",
    "CCU": "Coastal Carolina",
    "CHAR": "Charlotte",
    "CIN": "Cincinnati",
    "CLEM": "Clemson",
    "CMU": "Central Michigan",
    "COLO": "Colorado",
    "CSU": "Colorado State",
    "DUKE": "Duke",
    "ECU": "East Carolina",
    "EMU": "Eastern Michigan",
    "FAU": "Florida Atlantic",
    "FIU": "FIU",
    "FLA": "Florida",
    "FRES": "Fresno State",
    "FSU": "Florida State",
    "GAST": "Georgia State",
    "GASO": "Georgia Southern",
    "GT": "Georgia Tech",
    "HAW": "Hawaii",
    "HOU": "Houston",
    "ILL": "Illinois",
    "IND": "Indiana",
    "IOWA": "Iowa",
    "ISU": "Iowa State",
    "KENT": "Kent State",
    "KSU": "Kansas State",
    "KU": "Kansas",
    "LIB": "Liberty",
    "LOU": "Louisville",
    "LSU": "LSU",
    "LT": "Louisiana Tech",
    "MARY": "Maryland",
    "MEM": "Memphis",
    "MIA": "Miami",
    "MICH": "Michigan",
    "MINN": "Minnesota",
    "MISS": "Ole Miss",
    "MIZ": "Missouri",
    "MSST": "Mississippi State",
    "MSU": "Michigan State",
    "MTU": "Middle Tennessee",
    "NAVY": "Navy",
    "NCST": "NC State",
    "ND": "Notre Dame",
    "NEB": "Nebraska",
    "NEV": "Nevada",
    "NIU": "Northern Illinois",
    "NM": "New Mexico",
    "NMSU": "New Mexico State",
    "NW": "Northwestern",
    "ODU": "Old Dominion",
    "OKLA": "Oklahoma",
    "OKST": "Oklahoma State",
    "ORE": "Oregon",
    "ORST": "Oregon State",
    "OSU": "Ohio State",
    "PITT": "Pitt",
    "PSU": "Penn State",
    "PUR": "Purdue",
    "RICE": "Rice",
    "RUTG": "Rutgers",
    "SDSU": "San Diego State",
    "SJSU": "San Jose State",
    "SMU": "SMU",
    "STAN": "Stanford",
    "SYR": "Syracuse",
    "TCU": "TCU",
    "TEM": "Temple",
    "TENN": "Tennessee",
    "TEX": "Texas",
    "TLSA": "Tulsa",
    "TROY": "Troy",
    "TTU": "Texas Tech",
    "TXAM": "Texas A&M",
    "TXST": "Texas State",
    "UAB": "UAB",
    "UCF": "UCF",
    "UCLA": "UCLA",
    "UCONN": "UConn",
    "UGA": "Georgia",
    "UK": "Kentucky",
    "UL": "Louisiana",
    "ULM": "ULM",
    "UMASS": "UMass",
    "UNC": "North Carolina",
    "UNLV": "UNLV",
    "UNT": "North Texas",
    "USC": "USC",
    "USF": "South Florida",
    "USM": "Southern Miss",
    "USU": "Utah State",
    "UTAH": "Utah",
    "UTEP": "UTEP",
    "UTSA": "UTSA",
    "UVA": "Virginia",
    "VAN": "Vanderbilt",
    "VT": "Virginia Tech",
    "WAKE": "Wake Forest",
    "WASH": "Washington",
    "WISC": "Wisconsin",
    "WMU": "Western Michigan",
    "WSU": "Washington State",
    "WVU": "West Virginia",
    "WYO": "Wyoming",
}

_DATE = re.compile(r"^(\d{2}[A-Za-z]{3}\d{2})([A-Za-z0-9]+)$")
_SPORTS_SERIES = re.compile(
    r"^KX(NFL|NCAAF|CFB|NBA|NHL|MLB)(GAME|SPREAD|TOTAL|TEAMTOTAL)$",
    re.I,
)
_YES_NO = frozenset({"yes", "no"})


@dataclass
class DecodedTicker:
    ticker: str
    series: str = ""
    kind: str = ""  # moneyline / spread / total / team_total
    sport: str = ""
    away_code: str = ""
    home_code: str = ""
    away_name: str = ""
    home_name: str = ""
    yes_code: str = ""
    yes_name: str = ""
    line: str = ""  # signed spread (“-4”) or total points (“49”)
    line_raw: str = ""
    title: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def game(self) -> str:
        if self.away_name and self.home_name:
            return f"{self.away_name} vs {self.home_name}"
        if self.away_code and self.home_code:
            return f"{self.away_code} vs {self.home_code}"
        return ""

    @property
    def game_short(self) -> str:
        if self.away_code and self.home_code:
            return f"{self.away_code} vs {self.home_code}"
        return self.game

    @property
    def market(self) -> str:
        if self.kind == "total":
            return f"Points Total {self.line_raw or self.line}".strip()
        if self.kind == "team_total":
            who = self.yes_name or self.yes_code
            pts = self.line_raw or self.line
            return f"{who} team total {pts}".strip()
        if self.kind == "spread":
            who = self.yes_name or self.yes_code
            line = self.line or self.line_raw
            return f"spread {who} {line}".strip() if who else "spread"
        if self.kind == "moneyline":
            return "moneyline"
        return self.kind

    def opponent_name(self) -> str:
        if self.yes_code and self.yes_code == self.away_code:
            return self.home_name or self.home_code
        if self.yes_code and self.yes_code == self.home_code:
            return self.away_name or self.away_code
        return self.home_name or self.away_name or ""

    def opponent_code(self) -> str:
        if self.yes_code and self.yes_code == self.away_code:
            return self.home_code
        if self.yes_code and self.yes_code == self.home_code:
            return self.away_code
        return self.home_code or self.away_code


def looks_like_ticker(text: str) -> bool:
    value = str(text or "").strip()
    if not value.upper().startswith("KX"):
        return False
    return bool(re.search(r"-\d{2}[A-Za-z]{3}\d{2}", value))


def is_sports_ticker(ticker: str) -> bool:
    series = str(ticker or "").split("-", 1)[0]
    return bool(_SPORTS_SERIES.match(series))


def is_yes_no_token(text: str) -> bool:
    return str(text or "").strip().lower() in _YES_NO


def _maps_for(series: str) -> dict[str, str]:
    up = str(series or "").upper()
    if "NFL" in up:
        return NFL_TEAMS
    if "NCAAF" in up or "CFB" in up:
        return CFB_TEAMS
    return {**NFL_TEAMS, **CFB_TEAMS}


def _sport_for(series: str) -> str:
    up = str(series or "").upper()
    if "NFL" in up:
        return "pro football"
    if "NCAAF" in up or "CFB" in up:
        return "college football"
    if "NBA" in up:
        return "pro basketball"
    if "NHL" in up:
        return "pro hockey"
    if "MLB" in up:
        return "pro baseball"
    return ""


def _kind_for(series: str) -> str:
    up = str(series or "").upper()
    if "TEAMTOTAL" in up:
        return "team_total"
    if "TOTAL" in up:
        return "total"
    if "SPREAD" in up:
        return "spread"
    if "GAME" in up:
        return "moneyline"
    return ""


def split_team_blob(blob: str, codes: dict[str, str]) -> tuple[str, str] | None:
    """Split concatenated away+home codes using a known abbreviation set."""
    text = str(blob or "").upper()
    if not text:
        return None
    hits: list[tuple[int, int, str, str]] = []
    for i in range(2, len(text) - 1):
        left, right = text[:i], text[i:]
        if left in codes and right in codes:
            # Prefer a split that uses longer codes (GAST+ARST over GAS+TARST).
            hits.append((len(left) + len(right), min(len(left), len(right)), left, right))
    if hits:
        hits.sort(key=lambda row: (-row[0], -row[1], -len(row[2])))
        return hits[0][2], hits[0][3]
    keys = sorted(codes, key=len, reverse=True)
    for key in keys:
        if text.startswith(key) and text[len(key) :] in codes:
            return key, text[len(key) :]
    return None


def _name(code: str, codes: dict[str, str]) -> str:
    return codes.get(str(code or "").upper(), str(code or ""))


def _split_side_token(token: str, codes: dict[str, str]) -> tuple[str, str]:
    text = str(token or "").upper()
    if not text:
        return "", ""
    if text.isdigit() or re.fullmatch(r"\d+\.\d+", text):
        return "", text
    keys = sorted(codes, key=len, reverse=True)
    for key in keys:
        if text.startswith(key) and (len(text) == len(key) or text[len(key) :].replace(".", "", 1).isdigit()):
            return key, text[len(key) :]
    letters = re.match(r"^([A-Z]+)", text)
    digits = re.search(r"(\d+(?:\.\d+)?)$", text)
    return (letters.group(1) if letters else ""), (digits.group(1) if digits else "")


def _flip_line(line: str) -> str:
    text = str(line or "").strip()
    if not text:
        return ""
    if text.startswith("+"):
        rest = text[1:]
        return f"-{rest}" if rest and rest != "0" else (rest or "0")
    if text.startswith("-"):
        rest = text[1:]
        return f"+{rest}" if rest else text
    return f"+{text}"


def _spread_from_title(title: str, team_code: str, team_name: str, raw: str) -> str:
    """Kalshi Yes on TEAM{n} is ‘will TEAM win by over n (−.5)’. Title wins when it names a sign."""
    text = str(title or "")
    if not text:
        return f"-{raw}" if raw else ""
    blob = text
    team_bits = [b for b in (team_code, team_name, (team_name or "").rsplit(" ", 1)[-1]) if b]
    plus = re.search(
        r"(?:%s).{0,40}?\+(\d+(?:\.\d+)?)" % "|".join(re.escape(b) for b in team_bits),
        blob,
        flags=re.I,
    ) if team_bits else None
    if plus:
        return f"+{plus.group(1)}"
    plus_any = re.search(r"\+(\d+(?:\.\d+)?)", blob)
    minus = re.search(r"(?<![A-Za-z])-(\d+(?:\.\d+)?)", blob)
    over = re.search(
        r"(?:win(?:s)? by over|more than|win by more than)\s+(\d+(?:\.\d+)?)",
        blob,
        flags=re.I,
    )
    if plus_any and not minus:
        return f"+{plus_any.group(1)}"
    if over:
        return f"-{over.group(1)}"
    if minus:
        return f"-{minus.group(1)}"
    return f"-{raw}" if raw else ""


def decode_kalshi_ticker(
    ticker: str,
    *,
    title: str = "",
    pay: str = "",
) -> DecodedTicker:
    """Best-effort parse. Empty kind means ‘not a sports GAME/SPREAD/TOTAL ticker’."""
    text = str(ticker or "").strip()
    out = DecodedTicker(ticker=text, title=str(title or ""))
    if not text:
        return out
    parts = [p for p in text.split("-") if p]
    if len(parts) < 2:
        return out
    series = parts[0]
    if not _SPORTS_SERIES.match(series):
        return out
    out.series = series.upper()
    out.kind = _kind_for(series)
    out.sport = _sport_for(series)
    codes = _maps_for(series)
    mid = parts[1]
    suffix = parts[2] if len(parts) >= 3 else ""
    match = _DATE.match(mid)
    blob = match.group(2) if match else mid
    split = split_team_blob(blob, codes)
    if split:
        out.away_code, out.home_code = split
        out.away_name = _name(out.away_code, codes)
        out.home_name = _name(out.home_code, codes)
    yes_code, raw_line = _split_side_token(suffix, codes)
    out.yes_code = yes_code
    out.line_raw = raw_line
    if out.kind == "total":
        out.line = raw_line or suffix
        out.line_raw = out.line
        out.yes_code = ""
        out.yes_name = ""
    elif out.kind == "spread":
        out.yes_name = _name(yes_code, codes) if yes_code else ""
        out.line = _spread_from_title(title, yes_code, out.yes_name, raw_line)
        if not out.line and raw_line:
            out.line = f"-{raw_line}"
    elif out.kind == "team_total":
        out.yes_name = _name(yes_code, codes) if yes_code else ""
        out.line = raw_line
    else:
        out.yes_name = _name(yes_code, codes) if yes_code else ""
        out.line = ""
        if not out.yes_code and suffix.upper() in codes:
            out.yes_code = suffix.upper()
            out.yes_name = _name(out.yes_code, codes)
    if title:
        _apply_title(out, title)
    _ = pay  # callers pass pay for kitchen_phrase; parse itself is pay-agnostic
    return out


def _apply_title(decoded: DecodedTicker, title: str) -> None:
    text = str(title or "").strip()
    if not text:
        return
    decoded.title = text
    if decoded.kind == "total":
        pts = re.search(r"(\d+(?:\.\d+)?)\s*(?:points?)?", text, flags=re.I)
        over = re.search(r"over\s+(\d+(?:\.\d+)?)", text, flags=re.I)
        if over:
            decoded.line = over.group(1)
            decoded.line_raw = over.group(1)
        elif pts and not decoded.line_raw:
            decoded.line = pts.group(1)
            decoded.line_raw = pts.group(1)
        return
    if decoded.kind == "spread" and decoded.yes_code:
        decoded.line = _spread_from_title(
            text, decoded.yes_code, decoded.yes_name, decoded.line_raw
        )


def sold_yes_buy_no_gloss(pay: str) -> str:
    """Kalshi UI 'Sold Yes' is kitchen buy No. Empty for a Yes seat."""
    return "Sold Yes = buy No" if pay_of(pay) == "no" else ""


def pay_of(pay: str, fallback: str = "yes") -> str:
    text = str(pay or "").strip().lower()
    if text in _YES_NO:
        return text
    return fallback if fallback in _YES_NO else "yes"


def pay_from_garbled_bet(text: str) -> str:
    """Recover the real Yes/No from ‘Yes no 0.5300 Kalshi’ (first word was a default Yes)."""
    bits = str(text or "").strip().split()
    tokens = [b.lower() for b in bits if b.lower() in _YES_NO]
    if len(tokens) >= 2 and tokens[0] == "yes" and tokens[1] in _YES_NO:
        return tokens[1]
    if tokens:
        return tokens[0]
    return ""


def yes_no_label(decoded: DecodedTicker, pay: str) -> str:
    side = pay_of(pay)
    if decoded.kind in {"total", "team_total"}:
        return "No (Under)" if side == "no" else "Yes (Over)"
    if side == "no":
        return "No"
    return "Yes"


def bet_for_who(decoded: DecodedTicker, pay: str) -> str:
    """Who the $1 pays if they win / cover / go over."""
    side = pay_of(pay)
    if decoded.kind in {"total", "team_total"}:
        if decoded.kind == "team_total" and (decoded.yes_name or decoded.yes_code):
            who = decoded.yes_name or decoded.yes_code
            ou = "Under" if side == "no" else "Over"
            pts = decoded.line_raw or decoded.line
            return f"{who} {ou} {pts}".strip()
        return "Under" if side == "no" else "Over"
    if decoded.kind == "spread":
        if side != "no":
            who = decoded.yes_name or decoded.yes_code
            return f"{who} {decoded.line}".strip()
        who = decoded.opponent_name()
        return f"{who} {_flip_line(decoded.line)}".strip()
    # moneyline
    if side != "no":
        return decoded.yes_name or decoded.yes_code
    return decoded.opponent_name() or decoded.yes_name or decoded.yes_code


def kitchen_phrase(decoded: DecodedTicker, pay: str) -> str:
    """Seat we hold: Yes/No of the named contract, not who $1 pays.

    Kalshi No on the Eagles ticker is ‘No Philadelphia Eagles’ (pays if
    Commanders win). ‘No Washington Commanders’ would be the other ticket.
    """
    side = pay_of(pay)
    if decoded.kind == "total":
        return "No (Under)" if side == "no" else "Yes (Over)"
    if decoded.kind == "team_total":
        yn = "No (Under)" if side == "no" else "Yes (Over)"
        who = decoded.yes_name or decoded.yes_code
        return f"{yn} {who}".strip() if who else yn
    yn = "No" if side == "no" else "Yes"
    if decoded.kind == "spread":
        who = decoded.yes_name or decoded.yes_code
        line = decoded.line or decoded.line_raw
        bits = [yn]
        if who:
            bits.append(who)
        if line:
            bits.append(line)
        return " ".join(bits) if who or line else yn
    who = decoded.yes_name or decoded.yes_code
    if not who:
        return yn
    return f"{yn} {who}"


def pays_if_label(decoded: DecodedTicker, pay: str) -> str:
    """Who must win / cover / go over for this seat to pay $1."""
    who = bet_for_who(decoded, pay)
    if not who:
        return ""
    if decoded.kind in {"total", "team_total"}:
        return who
    if decoded.kind == "spread":
        return f"{who} cover"
    return f"{who} win"


def kitchen_clear(decoded: DecodedTicker, pay: str) -> str:
    """Kitchen cell: seat plus who $1 pays when No on a named team would confuse."""
    phrase = kitchen_phrase(decoded, pay)
    pays = pays_if_label(decoded, pay)
    side = pay_of(pay)
    if decoded.kind == "moneyline" and side == "no" and pays:
        return f"{phrase} (pays if {pays})"
    return phrase


def display_row(ticker: str, pay: str, *, title: str = "") -> dict:
    decoded = decode_kalshi_ticker(ticker, title=title, pay=pay)
    side = pay_of(pay)
    return {
        "ticker": ticker,
        "game": decoded.game,
        "type": decoded.market or decoded.kind,
        "kind": decoded.kind,
        "bet_for": bet_for_who(decoded, side),
        "yes_no": yes_no_label(decoded, side),
        "phrase": kitchen_phrase(decoded, side),
        "sport": decoded.sport,
        "away": decoded.away_name,
        "home": decoded.home_name,
        "line": decoded.line,
    }


def load_title_cache(path: Path | None = None) -> dict:
    target = path or TITLE_CACHE
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_title_cache(cache: dict, path: Path | None = None) -> None:
    target = path or TITLE_CACHE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass


def cached_title(ticker: str, cache: dict | None = None) -> str:
    blob = cache if cache is not None else load_title_cache()
    item = blob.get(str(ticker or ""))
    if isinstance(item, dict):
        return str(item.get("title") or item.get("yes_sub_title") or "")
    if isinstance(item, str):
        return item
    return ""


def fetch_market_record(ticker: str, *, timeout: float = 12.0) -> dict | None:
    """Public GET /markets/{ticker}. Amounts + title only. No secrets."""
    ident = str(ticker or "").strip()
    if not ident:
        return None
    url = (
        "https://api.elections.kalshi.com/trade-api/v2/markets/"
        + urllib.parse.quote(ident, safe="")
    )
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "stockresearch-kalshi-ticker-decode"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        status = exc.code
    except Exception:
        return None
    if status != 200:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    market = payload.get("market") if isinstance(payload, dict) else None
    if not isinstance(market, dict):
        market = payload if isinstance(payload, dict) else {}
    title = str(
        market.get("title")
        or market.get("yes_sub_title")
        or market.get("subtitle")
        or ""
    )
    if not title and not market:
        return None
    return {
        "title": title,
        "yes_sub_title": str(market.get("yes_sub_title") or ""),
        "subtitle": str(market.get("subtitle") or ""),
        "floor_strike": market.get("floor_strike"),
        "ticker": str(market.get("ticker") or ident),
    }


def title_for(ticker: str, *, cache: dict | None = None, fetch: bool = False) -> tuple[str, dict]:
    """Return (title, cache). Fetches once when fetch=True and the cache misses."""
    blob = cache if cache is not None else load_title_cache()
    ident = str(ticker or "").strip()
    title = cached_title(ident, blob)
    if title or not fetch or not ident:
        return title, blob
    got = fetch_market_record(ident)
    if got:
        blob[ident] = got
        save_title_cache(blob)
        title = str(got.get("title") or got.get("yes_sub_title") or "")
    return title, blob


def decode_with_cached_title(ticker: str, *, pay: str = "", fetch: bool = False, cache: dict | None = None) -> DecodedTicker:
    title, _blob = title_for(ticker, cache=cache, fetch=fetch)
    return decode_kalshi_ticker(ticker, title=title, pay=pay)
