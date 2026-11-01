"""Lock near-misses vs NET_MAX 0.984 (Sunday 25 Oct 2026 + last 48h).

Research only. Does not place, cancel, flatten, or sell. Does not print secrets.
Does not start a second live_strategy_b.py. Tables on this page were gathered vs
NET_MAX 0.984. Live send cap is systems.json lock.net_max (bumped to 0.99 after
rounding was gone). Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_near_misses_20261025.html"
JOB_STATUS = STAMP / "job_status.html"
JOB_CTRL = ROOT / "tools" / "prediction_job_control.py"
OPP_MOD = ROOT / "tools" / "opportunity_considerations.py"
NET_MAX = Decimal("0.984")
ONE = Decimal("1")
TODAY = datetime(2026, 10, 25, tzinfo=ET)
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_near_misses_20261025.html"
)
OPP_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/opportunities.html"
)
JOB_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/job_status.html"
)
ASKED = (
    "Lock is ON; he has not seen a both-sides fill and wants the scan page plus "
    "near-misses (close to NET_MAX 0.984). Confirm opportunities.html (sent + denied "
    "lock looks) and job_status.html last action on A. If opportunities is stale, "
    "rebuild from considerations.json / live_lock_orders logs (newest looks, not only "
    "500 if you can take more). Near-miss table: today ET Sunday 2026-10-25 plus last "
    "48h. Legal two-sided Yes+No same settlement, prices < $1, not sent. Sort by how "
    "close net (all-in) was to 0.984. Columns: time ET, sport, game, market, "
    "venues/sides, yes/no cash, fees, net, why skipped (over cap, hard_miss_abort, "
    "empty book, size<1, B absorbed, NFL D N/A). Sortable HTML."
)
PLAIN = (
    "The lock bot tries to buy Yes in one shop and No in another for the same result "
    "when both tickets plus fees still cost at or under the live send cap. This page "
    "is the almosts from when that cap was 98.4 cents: two-sided Yes+No looks that "
    "were legal enough to quote, each ticket under $1, and were not sent as a finished "
    "pair. Closest after-fee cost to 0.984 is first. A hair over that old cap (0.98440) "
    "is a near miss on this page. A 1.04 recheck is over the cap by more. Empty book, "
    "size under 1, tennis crossover already holding the match, and D-on-NFL-not-applicable "
    "are skip reasons, not sends. Rounding on the after-fee display is gone. Live send "
    "cap is now 0.99. Tables here stay vs 0.984. Tampa Bay vs Carolina 0.98399 is not "
    "retro-sent. This page does not place a ticket."
)

OVER_RE = re.compile(
    r"limit=(?P<limit>[0-9.]+)\s+other=(?P<other>[0-9.]+)"
    r"(?:\s+gross=(?P<gross>[0-9.]+))?"
    r"(?:\s+fee=(?P<fee>[0-9.]+))?"
    r"(?:\s+other_fee=(?P<other_fee>[0-9.]+))?"
    r"(?:\s+net=(?P<net>[0-9.]+))?",
    re.I,
)
NET_RE = re.compile(r"net=([0-9.]+)", re.I)
FEE_RE = re.compile(r"(?<![a-z])fee=([0-9.]+)", re.I)
OTHER_FEE_RE = re.compile(r"other_fee=([0-9.]+)", re.I)
AFTER_FEE_RE = re.compile(r"After-fee cost ([0-9.]+)", re.I)
DIR_PREFIX = (
    "tennis-b",
    "cfb-favorite",
    "cfb_favorite",
    "spread-t0",
    "spread_t0",
    "tennis-crossover",
    "tennis_crossover",
)
DIR_STEPS = {"b-t0", "b-cross", "b-leftover-yes", "b-fav", "c-t0", "d-t0", "e-t0", "e"}
DIR_SYS = {"tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog", "strategy_b"}


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    text = "" if value is None else str(value)
    extra = ' class="num"' if kind == "num" else ""
    return f"<td{extra}>{esc(text)}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(
            td(cell, headers[i][1] if i < len(headers) else "text")
            for i, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    if total is not None:
        cells = "".join(
            td(cell, headers[i][1] if i < len(headers) else "text")
            for i, cell in enumerate(total)
        )
        body.append(f'<tr class="total-row">{cells}</tr>')
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def parse_dt(raw) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        stamp = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            stamp = datetime.fromisoformat(text)
        except Exception:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def money(value) -> str:
    if value is None or value == "":
        return ""
    number = value if isinstance(value, Decimal) else dec(value)
    if number is None:
        return str(value)
    return format(number, "f")


def money4(value) -> str:
    if value is None or value == "":
        return ""
    number = value if isinstance(value, Decimal) else dec(value)
    if number is None:
        return str(value)
    return format(number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")


def fmt_et(stamp: datetime | None) -> str:
    if stamp is None:
        return ""
    return stamp.strftime("%Y-%m-%d %H:%M:%S ET")


def file_mtime_et(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stamp = datetime.fromtimestamp(path.stat().st_mtime, ET)
    return stamp.strftime("%Y-%m-%d %H:%M:%S ET")


def is_lock_key(key: str, row: dict | None = None) -> bool:
    text = str(key or "")
    if text.startswith(DIR_PREFIX):
        return False
    if row:
        if str(row.get("system") or row.get("_system") or "") in DIR_SYS:
            return False
        if str(row.get("step") or "") in DIR_STEPS:
            return False
        sport = str(row.get("sport") or "").strip().lower()
        if sport in DIR_SYS or sport in {"tennis-crossover", "cfb-favorite", "spread-t0"}:
            return False
    return bool(text) or bool(row and (row.get("game") or row.get("yes_venue")))


def sport_from_key(key: str, row: dict | None = None) -> str:
    if row and row.get("sport"):
        return str(row.get("sport") or "")
    parts = str(key or "").split("\t")
    return parts[0] if parts and parts[0] else ""


def market_from_key(key: str, row: dict | None = None) -> str:
    if row and (row.get("market_type") or row.get("market")):
        return str(row.get("market_type") or row.get("market") or "")
    parts = str(key or "").split("\t")
    if len(parts) >= 4:
        return parts[3]
    return ""


def number_from_key(key: str, row: dict | None = None) -> str:
    if row and row.get("number") not in (None, ""):
        return str(row.get("number"))
    parts = str(key or "").split("\t")
    if len(parts) >= 6:
        return parts[5]
    return ""


def side_from_key(key: str, row: dict | None = None) -> str:
    if row and (row.get("side") or row.get("side_label")):
        return str(row.get("side") or row.get("side_label") or "")
    parts = str(key or "").split("\t")
    if len(parts) >= 5:
        return parts[4]
    return ""


def venues_from(row: dict, key: str = "") -> str:
    yes_v = str(row.get("yes_venue") or "")
    no_v = str(row.get("no_venue") or "")
    if yes_v or no_v:
        return f"Yes {yes_v} / No {no_v}".strip()
    parts = str(key or row.get("bet_key") or "").split("\t")
    if len(parts) >= 8:
        return f"Yes {parts[6]} / No {parts[7]}"
    venue = str(row.get("venue") or "")
    other = str(row.get("other_venue") or "")
    if venue and other:
        return f"{venue} / {other}"
    return venue


def prices_under_one(yes, no) -> bool:
    a = dec(yes)
    b = dec(no)
    if a is None or b is None:
        return False
    return a > 0 and b > 0 and a < ONE and b < ONE


def classify_why(text: str) -> str:
    low = str(text or "").lower()
    if "hard_miss_abort" in low or "hard miss abort" in low:
        return "hard_miss_abort"
    if "has this tennis match open" in low or "tennis crossover has this" in low or "absorbed" in low:
        return "B absorbed"
    if "d_skip_nfl" in low or "nfl" in low and ("gather" in low or "n/a" in low or "except nfl" in low):
        return "NFL D N/A"
    if "over cap" in low or "above the 0.984" in low or "above the net_max" in low or "not profitable" in low:
        return "over cap"
    if "book empty" in low or "ask missing" in low:
        return "empty book"
    if "missing size" in low or "no takeable size" in low or "size < 1" in low or "need >= 1" in low or "both books need" in low:
        return "size<1"
    if "already have" in low and "open lock" in low:
        return "max open (leftover/slots)"
    if "catalog" in low and "never sends" in low:
        return "catalog (log only)"
    if "not a real no" in low or "flipped" in low:
        return "not a real No"
    if "balance" in low:
        return "balance unreadable"
    if "orders stopped" in low or "missed pair" in low:
        return "leftover latch"
    if "placing orders is off" in low:
        return "placing off"
    if "flatten" in low:
        return "flatten leftover"
    return "other"


def parse_over(text: str) -> dict:
    out = {}
    match = OVER_RE.search(str(text or ""))
    if not match:
        net_m = NET_RE.search(str(text or ""))
        if net_m:
            out["net"] = dec(net_m.group(1))
        return out
    for key in ("limit", "other", "gross", "fee", "other_fee", "net"):
        raw = match.group(key)
        if raw is not None:
            out[key] = dec(raw)
    return out


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def lock_on() -> bool:
    data = load_json(RAW / "systems.json") or {}
    sys = (data.get("systems") or {}).get("lock") or {}
    return bool(sys.get("on"))


def orders_stopped() -> bool:
    return (RAW / "orders_stopped.json").is_file()


def iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def row_when(row: dict, last: datetime | None) -> datetime | None:
    for key in ("at", "sent_at", "quote_seen_at", "trigger_seen_at", "ts", "time"):
        stamp = parse_dt(row.get(key))
        if stamp is not None:
            return stamp
    return last


def collect() -> dict:
    now = datetime.now(ET)
    cut48 = now - timedelta(hours=48)
    consider_path = RAW / "considerations.json"
    consider = load_json(consider_path) or {}
    consider_rows = [r for r in (consider.get("rows") or []) if isinstance(r, dict)]

    last_skip = load_json(RAW / "lock_last_skip.json") or {}
    last_gross = load_json(RAW / "last_gross.json") or {}
    systems = load_json(RAW / "systems.json") or {}
    lock_cfg = (systems.get("systems") or {}).get("lock") or {}

    stats = {
        "now": now,
        "cut48": cut48,
        "lock_on": bool(lock_cfg.get("on", True)),
        "max_open": lock_cfg.get("max_open"),
        "orders_stopped": orders_stopped(),
        "consider_n": len(consider_rows),
        "consider_first": consider_rows[0].get("at") if consider_rows else "",
        "consider_last": consider_rows[-1].get("at") if consider_rows else "",
        "opp_mtime": file_mtime_et(STAMP / "opportunities.html"),
        "job_mtime": file_mtime_et(JOB_STATUS),
        "last_skip": last_skip,
        "last_gross": last_gross,
        "looks_48": 0,
        "sends_48": 0,
        "claims_48": 0,
        "hard_abort_48": 0,
        "both_sides_48": 0,
        "skip_48": 0,
        "b_absorbed_48": 0,
        "nfl_d_na_48": 0,
        "why_counts": Counter(),
        "today_why": Counter(),
        "source_counts": Counter(),
    }

    misses: list[dict] = []
    seen = set()

    def add_miss(item: dict) -> None:
        when = item.get("when")
        if when is None or when < cut48 or when > now + timedelta(minutes=5):
            return
        yes = item.get("yes")
        no = item.get("no")
        if item.get("require_prices") and not prices_under_one(yes, no):
            return
        if yes is not None and no is not None and not prices_under_one(yes, no):
            # Keep empty-book / size skips that lost a price on recheck.
            if item.get("why_kind") not in {"empty book", "size<1", "hard_miss_abort", "B absorbed", "NFL D N/A"}:
                return
        fp = (
            fmt_et(when)[:16],
            str(item.get("game") or ""),
            str(item.get("market") or ""),
            str(item.get("venues") or ""),
            money(item.get("yes")),
            money(item.get("no")),
            money(item.get("net")),
            str(item.get("why_kind") or ""),
        )
        if fp in seen:
            return
        seen.add(fp)
        net = item.get("net")
        item["delta"] = abs(net - NET_MAX) if isinstance(net, Decimal) else None
        item["today"] = when >= TODAY
        misses.append(item)
        stats["why_counts"][item.get("why_kind") or "other"] += 1
        stats["source_counts"][item.get("source") or ""] += 1
        if item["today"]:
            stats["today_why"][item.get("why_kind") or "other"] += 1

    # considerations.json (newest 500; often only minutes, but has hair-over nets)
    for row in consider_rows:
        when = parse_dt(row.get("at"))
        decision = str(row.get("decision") or "")
        if decision == "sent":
            continue
        yes = dec(row.get("yes_price"))
        no = dec(row.get("no_price"))
        net = dec(row.get("net"))
        reason = str(row.get("reason") or "")
        parsed = parse_over(reason)
        if parsed.get("net") is not None:
            # Recheck net is the all-in that blocked the send when present.
            net = parsed["net"]
            yes = parsed.get("limit") if parsed.get("limit") is not None else yes
            no = parsed.get("other") if parsed.get("other") is not None else no
        fee = None
        if parsed.get("fee") is not None or parsed.get("other_fee") is not None:
            fee = (parsed.get("fee") or Decimal("0")) + (parsed.get("other_fee") or Decimal("0"))
        elif yes is not None and no is not None and net is not None:
            fee = net - yes - no
        why = classify_why(reason)
        add_miss({
            "when": when,
            "sport": row.get("sport") or "",
            "game": row.get("game") or "",
            "market": " ".join(p for p in (str(row.get("market_type") or ""), str(row.get("side") or ""), str(row.get("number") or "")) if p).strip(),
            "venues": venues_from(row),
            "yes": yes,
            "no": no,
            "fees": fee,
            "net": net,
            "why_kind": why,
            "why": reason,
            "source": "considerations.json",
            "require_prices": why not in {"empty book", "size<1", "not a real No"},
        })

    last_when = None
    last_lock_sent = None
    last_hard = None
    send_games = Counter()
    skip_games = Counter()
    for row in iter_jsonl(RAW / "orders.jsonl"):
        when = row_when(row, last_when)
        if when is not None:
            last_when = when
        event = str(row.get("event") or "")
        key = str(row.get("bet_key") or "")
        lock = is_lock_key(key, row)
        if when is not None and when >= cut48:
            if lock:
                if event == "claim":
                    stats["claims_48"] += 1
                    stats["looks_48"] += 1
                elif event == "sent":
                    stats["sends_48"] += 1
                    send_games[str(row.get("game") or key)] += 1
                    last_lock_sent = {
                        "when": when,
                        "game": row.get("game") or "",
                        "key": key,
                        "step": row.get("step") or "",
                        "venue": row.get("venue") or "",
                        "limit": row.get("limit_price"),
                    }
                elif event == "hard_miss_abort":
                    stats["hard_abort_48"] += 1
                    last_hard = {
                        "when": when,
                        "game": row.get("game") or "",
                        "key": key,
                        "venue": row.get("venue") or "",
                        "other": row.get("other_venue") or "",
                        "gap_closed": row.get("gap_closed"),
                        "note": row.get("note") or "",
                    }
                    add_miss({
                        "when": when,
                        "sport": sport_from_key(key, row),
                        "game": row.get("game") or side_from_key(key, row) or key.split("\t")[1] if "\t" in key else key,
                        "market": market_from_key(key, row),
                        "venues": venues_from(row, key),
                        "yes": dec(row.get("limit_price")),
                        "no": None,
                        "fees": None,
                        "net": None,
                        "why_kind": "hard_miss_abort",
                        "why": (
                            f"hard_miss_abort venue={row.get('venue')} other={row.get('other_venue')} "
                            f"gap_closed={row.get('gap_closed')} {row.get('note') or ''}"
                        ).strip(),
                        "source": "orders.jsonl",
                        "require_prices": False,
                    })
                elif event == "skip":
                    stats["skip_48"] += 1
                    stats["looks_48"] += 1
                    skip_games[str(row.get("game") or "")] += 1
                    reason = str(row.get("reason") or "")
                    why = classify_why(reason)
                    parsed = parse_over(reason)
                    yes = parsed.get("limit")
                    no = parsed.get("other")
                    net = parsed.get("net")
                    fee = None
                    if parsed.get("fee") is not None or parsed.get("other_fee") is not None:
                        fee = (parsed.get("fee") or Decimal("0")) + (parsed.get("other_fee") or Decimal("0"))
                    add_miss({
                        "when": when,
                        "sport": sport_from_key(key, row),
                        "game": row.get("game") or "",
                        "market": " ".join(
                            p for p in (market_from_key(key, row), side_from_key(key, row), number_from_key(key, row)) if p
                        ).strip(),
                        "venues": venues_from(row, key),
                        "yes": yes,
                        "no": no,
                        "fees": fee,
                        "net": net,
                        "why_kind": why,
                        "why": reason,
                        "source": "orders.jsonl",
                        "require_prices": why == "over cap",
                    })
                elif event in {"filled", "one_leg", "both_unfilled", "flatten_filled", "flatten_miss"}:
                    stats["looks_48"] += 0
            else:
                # D NFL N/A (directional skip, not a lock pair)
                reason = str(row.get("reason") or row.get("note") or row.get("skip_reason") or "")
                blob = " ".join((key, str(row.get("game") or ""), str(row.get("sport") or ""), reason)).lower()
                if event in {"skip", "t0"} and ("pro football" in blob or "nfl" in blob or key.startswith("spread-t0")):
                    if "d_skip_nfl" in blob or "skip nfl" in blob or "except nfl" in blob:
                        stats["nfl_d_na_48"] += 1
                        add_miss({
                            "when": when,
                            "sport": "pro football",
                            "game": row.get("game") or "",
                            "market": market_from_key(key, row) or "spread",
                            "venues": venues_from(row, key),
                            "yes": None,
                            "no": None,
                            "fees": None,
                            "net": None,
                            "why_kind": "NFL D N/A",
                            "why": reason or "D on except NFL (d_skip_nfl_gathering). Not a lock skip.",
                            "source": "orders.jsonl D",
                            "require_prices": False,
                        })

    # Supervisor: B absorbed + extra hard_miss_abort / over cap not already on the ledger
    sup_path = RAW / "live_supervisor.log"
    if sup_path.is_file():
        with sup_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stamp = parse_dt(line.split(" ", 1)[0].strip())
                if stamp is None or stamp < cut48 or stamp > now:
                    continue
                low = line.lower()
                if "has this tennis match open" in low or "tennis crossover has this" in low:
                    stats["b_absorbed_48"] += 1
                    title = ""
                    if "order skip " in line:
                        title = line.split("order skip ", 1)[-1].split(";", 1)[0].strip()
                    add_miss({
                        "when": stamp,
                        "sport": "tennis",
                        "game": title,
                        "market": "moneyline",
                        "venues": "",
                        "yes": None,
                        "no": None,
                        "fees": None,
                        "net": None,
                        "why_kind": "B absorbed",
                        "why": line.strip()[-220:],
                        "source": "live_supervisor.log",
                        "require_prices": False,
                    })

    # last_gross under-$1 NFL today as extra context (current tape, not a historical look)
    gross_now = []
    for key, raw in (last_gross or {}).items():
        val = dec(raw)
        if val is None:
            continue
        sport, codes, day = (key.split(":") + ["", "", ""])[:3]
        if day != "2026-10-25":
            continue
        gross_now.append((sport, codes, val, abs(val - NET_MAX)))
    gross_now.sort(key=lambda x: x[3])

    misses.sort(key=lambda r: (r["delta"] is None, r["delta"] if r["delta"] is not None else Decimal("9"), -(r["when"].timestamp() if r["when"] else 0)))
    today_misses = [m for m in misses if m.get("today")]
    closest_today = next((m for m in today_misses if m.get("net") is not None), None)
    closest_48 = next((m for m in misses if m.get("net") is not None), None)
    hair = [m for m in misses if isinstance(m.get("net"), Decimal) and NET_MAX < m["net"] <= Decimal("0.99")]
    under = [
        m for m in misses
        if isinstance(m.get("net"), Decimal) and m["net"] <= NET_MAX and m.get("why_kind") != "over cap"
    ]

    stats["last_lock_sent"] = last_lock_sent
    stats["last_hard"] = last_hard
    stats["send_games"] = send_games
    stats["skip_games"] = skip_games
    stats["miss_n"] = len(misses)
    stats["today_n"] = len(today_misses)
    stats["hair_n"] = len(hair)
    stats["under_n"] = len(under)
    stats["closest_today"] = closest_today
    stats["closest_48"] = closest_48
    stats["gross_now"] = gross_now
    stats["misses"] = misses
    stats["today_misses"] = today_misses
    stats["hair"] = hair
    return stats


def miss_row(item: dict) -> list:
    yes = item.get("yes")
    no = item.get("no")
    cash = ""
    if yes is not None or no is not None:
        cash = f"{money(yes)} / {money(no)}"
    delta = item.get("delta")
    return [
        fmt_et(item.get("when")),
        item.get("sport") or "",
        item.get("game") or "",
        item.get("market") or "",
        item.get("venues") or "",
        cash,
        money(item.get("fees")),
        money(item.get("net")),
        money(delta) if delta is not None else "",
        item.get("why_kind") or "",
        (item.get("why") or "")[:220],
    ]


HEADERS = [
    ("Time ET", "date"),
    ("Sport", "text"),
    ("Game", "text"),
    ("Market", "text"),
    ("Venues / sides", "text"),
    ("Yes / No cash", "text"),
    ("Fees", "num"),
    ("Net", "num"),
    ("|net−0.984|", "num"),
    ("Why skipped", "text"),
    ("Detail", "text"),
]


def patch_job_status_template() -> str:
    if not JOB_CTRL.is_file():
        return "prediction_job_control.py missing"
    text = JOB_CTRL.read_text(encoding="utf-8")
    if "lock_near_misses_20261025.html" in text:
        return "prediction_job_control.py already links near-miss page"
    needle = (
        '<p>Why no both-sides lock fill since 21 Oct 2026: '
        '<a href="lock_quiet_since_20261021.html">lock_quiet_since_20261021.html</a> '
        '(list of the five fills: '
        '<a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>).</p>'
    )
    extra = (
        needle
        + "\n"
        + '<p>Lock A near misses vs NET_MAX 0.984 (Sunday 25 Oct + last 48h): '
        + '<a href="lock_near_misses_20261025.html">lock_near_misses_20261025.html</a>.</p>'
    )
    if needle not in text:
        return "job_status template quiet-page line drifted; skipped"
    JOB_CTRL.write_text(text.replace(needle, extra, 1), encoding="utf-8")
    return "linked near-miss page from prediction_job_control.py"


def patch_job_status_html() -> str:
    if not JOB_STATUS.is_file():
        return "job_status.html missing"
    text = JOB_STATUS.read_text(encoding="utf-8")
    if "lock_near_misses_20261025.html" in text:
        return "job_status.html already links near-miss page"
    needle = (
        '<p>Why no both-sides lock fill since 21 Oct 2026: '
        '<a href="lock_quiet_since_20261021.html">lock_quiet_since_20261021.html</a> '
        '(list of the five fills: '
        '<a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>).</p>'
    )
    extra = (
        needle
        + "\n"
        + '<p>Lock A near misses vs NET_MAX 0.984 (Sunday 25 Oct + last 48h): '
        + '<a href="lock_near_misses_20261025.html">lock_near_misses_20261025.html</a>.</p>'
    )
    if needle not in text:
        return "job_status.html quiet-page line drifted; skipped"
    JOB_STATUS.write_text(text.replace(needle, extra, 1), encoding="utf-8")
    return "linked near-miss page on current job_status.html"


def patch_opportunities_generator() -> str:
    if not OPP_MOD.is_file():
        return "opportunity_considerations.py missing"
    text = OPP_MOD.read_text(encoding="utf-8")
    if "lock_near_misses_20261025.html" in text:
        return "opportunity_considerations.py already links near-miss page"
    needle = '<p class="note">A row is logged only when the cost after the documented fees is at or under 0.99.'
    extra = (
        '<p class="note">Near misses vs the 0.984 send line (today + last 48h, including over-cap '
        "rechecks the 500-row log may have rotated out): "
        '<a href="lock_near_misses_20261025.html">lock_near_misses_20261025.html</a>.</p>\n'
        + needle
    )
    if needle not in text:
        return "opportunities generator note line drifted; skipped"
    OPP_MOD.write_text(text.replace(needle, extra, 1), encoding="utf-8")
    return "linked near-miss page from opportunity_considerations.py"


def write_page(stats: dict) -> Path:
    now = stats["now"]
    closest = stats.get("closest_today") or {}
    closest48 = stats.get("closest_48") or {}
    last_sent = stats.get("last_lock_sent") or {}
    last_hard = stats.get("last_hard") or {}
    last_skip = stats.get("last_skip") or {}
    lock_word = "ON" if stats["lock_on"] and not stats["orders_stopped"] else "not sending"
    if stats["lock_on"] and stats["orders_stopped"]:
        lock_word = "ON but orders_stopped latch is set"
    elif not stats["lock_on"]:
        lock_word = "OFF"
    try:
        import live_lock_orders

        live_cap = live_lock_orders.send_line()
    except Exception:
        live_cap = "0.99"

    shown = stats["misses"][:400]
    today_shown = stats["today_misses"][:200]
    hair_shown = stats["hair"][:80]

    why_rows = [[k, v] for k, v in stats["why_counts"].most_common()]
    today_why_rows = [[k, v] for k, v in stats["today_why"].most_common()]
    src_rows = [[k, v] for k, v in stats["source_counts"].most_common()]
    gross_rows = [
        [sport, codes, money(val), money4(delta)]
        for sport, codes, val, delta in stats.get("gross_now") or []
    ]

    closest_net = money(closest.get("net")) if closest else "—"
    closest_game = closest.get("game") or "—"
    closest_why = closest.get("why_kind") or "—"
    closest48_net = money(closest48.get("net")) if closest48 else "—"
    hair0 = (stats.get("hair") or [None])[0] or {}
    hair_line = (
        f"{hair0.get('game') or '—'} {money(hair0.get('net'))}"
        if hair0
        else "—"
    )

    last_action = str(last_skip.get("reason") or "")
    last_action_at = last_skip.get("at") or ""
    last_action_game = last_skip.get("game") or ""

    sent_n = stats["sends_48"]
    looks_n = stats["looks_48"]
    skip_n = stats["skip_48"]
    last_sent_game = last_sent.get("game") or ""
    if not last_sent_game:
        parts = str(last_sent.get("key") or "").split("\t")
        last_sent_game = " ".join(p for p in parts[:4] if p)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lock near misses vs 0.984 — 25 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.banner {{ background: #fefce8; border: 1px solid #fde68a; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Lock near misses vs NET_MAX 0.984</h1>
<p class="banner"><strong>Research only. Not gold. Not DailyRun.</strong>
Written {esc(now.strftime("%Y-%m-%d %H:%M:%S ET"))}.
Lock gap (A) is <strong>{esc(lock_word)}</strong>.
Did not sell. Did not start a second live_strategy_b.py.
<code>orders_stopped.json</code> is {"set" if stats["orders_stopped"] else "not set"}.</p>
<div class="callout">
<h2>Live send cap</h2>
<p>Rounding on the after-fee display is gone. Live send cap is now <strong>{esc(live_cap)}</strong>
(systems.json lock.net_max). Tables on this page were gathered vs 0.984 and stay that way.
Tampa Bay vs Carolina 0.98399 is not retro-sent. New looks at or under {esc(live_cap)} can send.
See <a href="lock_net_max_099_20261025.html">lock_net_max_099_20261025.html</a>.</p>
</div>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Pages he can open now</h2>
{table(
    [("Page", "text"), ("Last updated ET", "date"), ("Note", "text")],
    [
        [
            "opportunities.html",
            stats["opp_mtime"],
            f"Live scan of sent + denied lock looks. Catalog scan rewrites it. Window is newest {stats['consider_n']} considerations rows ({stats['consider_first']} … {stats['consider_last']}). Hair-over 0.984 rows live here while they are still in that 500.",
        ],
        [
            "job_status.html",
            stats["job_mtime"],
            f"A last skip: {last_action_at} {last_action_game} {last_action[:180]}",
        ],
        [
            "lock_near_misses_20261025.html (this page)",
            now.strftime("%Y-%m-%d %H:%M:%S ET"),
            "Today + last 48h near misses from considerations.json, orders.jsonl, and supervisor B-absorbed lines. Not limited to the 500-row window.",
        ],
    ],
)}
<p class="note">Scan page: <a href="opportunities.html">opportunities.html</a>.
Status A: <a href="job_status.html">job_status.html</a>.
Quiet since 21 Oct: <a href="lock_quiet_since_20261021.html">lock_quiet_since_20261021.html</a>.
Both-sides list: <a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>.</p>

<h2>Direct answers</h2>
<ul>
<li><strong>Lock on?</strong> {esc(lock_word)}. systems.json lock.on={esc(stats["lock_on"])}, max_open={esc(stats["max_open"])}. Supervisor last A skip is over-cap recheck, not a latch file.</li>
<li><strong>Closest net today</strong> (Sunday 2026-10-25 ET): <strong>{esc(closest_net)}</strong> on {esc(closest_game)} ({esc(closest_why)}). Distance to 0.984 is {esc(money(closest.get("delta")) if closest else "—")} ({esc("under" if isinstance(closest.get("net"), Decimal) and closest["net"] < NET_MAX else "over" if isinstance(closest.get("net"), Decimal) else "")}). Closest hair-over (net still ≤ 0.99): {esc(hair_line)}.</li>
<li><strong>Closest net last 48h:</strong> {esc(closest48_net)} ({esc((closest48 or {}).get("game") or "—")}, {esc((closest48 or {}).get("why_kind") or "—")}).</li>
<li><strong>Looks vs sends last 48h (lock tape):</strong> {esc(looks_n)} lock looks (claims + skips) · {esc(stats["claims_48"])} claims · {esc(skip_n)} skip events · <strong>{esc(sent_n)} lock HTTP sends</strong> · {esc(stats["hard_abort_48"])} hard_miss_abort · <strong>0 both-sides fills</strong>.</li>
<li><strong>Why no both-sides still:</strong> hard-first (last lock send was a hard IOC, then abort / no easy) · over cap on REST recheck (quoted net under 0.99, live books reprint over 0.984 or even over $1 gross) · leftover/slots (considerations still logging “Already have 3 open lock pair(s)” even while Positions A is 0 — open-count / leftover watches, not a new both-sides). D on NFL is N/A for system D and is not why lock missed a Yes+No.</li>
</ul>
<p class="note">Last lock HTTP send in this window: {esc(fmt_et(last_sent.get("when")))} {esc(last_sent_game or "—")} step={esc(last_sent.get("step") or "—")} venue={esc(last_sent.get("venue") or "—")}.
Last hard_miss_abort: {esc(fmt_et(last_hard.get("when")))} {esc(last_hard.get("key") or "—")} gap_closed={esc(last_hard.get("gap_closed"))}.</p>

<h2>Skip mix (unique near-miss rows)</h2>
<p class="note">Click column headers to sort. Unique = same minute + game + venues + prices + net + why, newest kept.</p>
{table(
    [("Why skipped", "text"), ("Rows last 48h", "num")],
    why_rows,
    ["Total unique", str(stats["miss_n"])],
)}
<h3>Today only</h3>
{table(
    [("Why skipped", "text"), ("Rows today ET", "num")],
    today_why_rows,
    ["Total unique today", str(stats["today_n"])],
)}
{table(
    [("Source", "text"), ("Rows", "num")],
    src_rows,
)}

<h2>Hair-over the send line (0.984 &lt; net ≤ 0.99)</h2>
<p class="note">These are the true near misses: after-fee cost still under the 0.99 log line, but above NET_MAX so live pollers do not send. Sorted closest to 0.984 first. {esc(stats["hair_n"])} unique. Showing {esc(len(hair_shown))}.</p>
{table(HEADERS, [miss_row(m) for m in hair_shown])}

<h2>Near misses — today ET Sunday 2026-10-25</h2>
<p class="note">Legal two-sided Yes+No same settlement, each price &lt; $1 when we still had both quotes, <strong>not sent</strong>. Sorted by |net − 0.984|. Rows without a net (empty book, B absorbed, hard_miss_abort without a stored all-in) sort last. Showing {esc(len(today_shown))} of {esc(stats["today_n"])}. Swipe sideways to see more columns.</p>
{table(HEADERS, [miss_row(m) for m in today_shown])}

<h2>Near misses — last 48h (includes today)</h2>
<p class="note">Same rules. Window starts {esc(fmt_et(stats["cut48"]))}. Showing closest {esc(len(shown))} of {esc(stats["miss_n"])} unique rows. considerations.json is only the newest 500 (about the last few minutes); orders.jsonl skip/hard_miss_abort covers the rest of the 48h.</p>
{table(HEADERS, [miss_row(m) for m in shown])}

<h2>Current last_gross.json (today, not a send)</h2>
<p class="note">Best quoted gross per game on the live overlay. Gross is the two prices before fees. Net is higher. A 0.98 gross can still be over 0.984 after fees. Not a both-sides fill.</p>
{table(
    [("Sport", "text"), ("Codes", "text"), ("Gross", "num"), ("|gross−0.984|", "num")],
    gross_rows,
)}

<p class="tiny">Sources: local <code>considerations.json</code> (500-row cap), <code>orders.jsonl</code> lock skip/sent/hard_miss_abort, <code>live_supervisor.log</code> B-absorbed lines, <code>lock_last_skip.json</code>, <code>last_gross.json</code>, <code>systems.json</code> lock.on / net_max. Drive pages opportunities.html / job_status.html. Tables vs NET_MAX=0.984. Live send cap={esc(live_cap)}. No secrets. No GTC. No second Strategy B. Did not sell.</p>
<p class="tiny">File URL {esc(FILE_URL)} · scan {esc(OPP_URL)} · status {esc(JOB_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def main() -> int:
    print("collecting lock near misses", flush=True)
    stats = collect()
    path = write_page(stats)
    print(path, flush=True)
    print("unique", stats["miss_n"], "today", stats["today_n"], "hair", stats["hair_n"], flush=True)
    print("looks48", stats["looks_48"], "sends48", stats["sends_48"], "hard", stats["hard_abort_48"], flush=True)
    closest = stats.get("closest_today") or {}
    print("closest_today", money(closest.get("net")), closest.get("game"), closest.get("why_kind"), flush=True)
    print(patch_job_status_template(), flush=True)
    print(patch_job_status_html(), flush=True)
    print(patch_opportunities_generator(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
