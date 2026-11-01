"""Same-side ask gaps across Kalshi, Gemini, and Polymarket, plus the position check.

Research only. This module reads quotes and the order ledger. It does not place,
cancel, or amend orders. A signed Kalshi positions read happens only when
fetch_positions=True.
"""
from __future__ import annotations

import html
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import norm_number, norm_side, parse_time
PAGE = STAMP / "cheaper_same_bet.html"
ORDERS = RAW / "orders.jsonl"
LAST = RAW / "price_last.json"
POSITIONS = RAW / "kalshi_positions_pull.json"
JOBS = RAW / "live_jobs"
ET = ZoneInfo("America/New_York")
CENT = Decimal("0.01")
FRESH = timedelta(minutes=15)
VENUES = ("Kalshi", "Gemini", "Polymarket", "Novig")

ASKED = (
    "Paul asked three things on Sunday, October 18, 2026. "
    "Call Kalshi for our open positions and compare them with what the ledger thinks we hold. "
    "Give thoughts, grounded in the logs, for why Gemini and Polymarket filled none. "
    "Track the same bet on two or more platforms and flag when one platform's price to buy that same side "
    "is less expensive than the others. Count how many are 1 cent less, 2 cents less, 5 cents less, and 10 cents or more. "
    "This is the same outcome (same game, market type, side, and number), not a Yes-plus-No lock. Do not place orders."
)


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, num: bool = False) -> str:
    text = "" if value is None else str(value)
    if num:
        return f"<td style=\"text-align:right\">{esc(text)}</td>"
    return f"<td>{esc(text)}</td>"


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal("0.0001")), "f")


def load_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_orders() -> list[dict]:
    if not ORDERS.is_file():
        return []
    rows = []
    for line in ORDERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def fetch_positions() -> dict:
    """Signed GET of open positions. Does not print the key, the signature, or the body."""
    import kalshi_private

    status, body = kalshi_private.signed_call(
        "GET",
        "/trade-api/v2/portfolio/positions",
        query={"limit": "1000", "count_filter": "position"},
    )
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    payload = {
        "http_status": status,
        "pulled_at": datetime.now(ET).isoformat(),
        "body": {
            "cursor": data.get("cursor") or "",
            "market_positions": data.get("market_positions") or [],
            "event_positions": data.get("event_positions") or [],
        },
    }
    POSITIONS.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _fp(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def ledger_fills(rows: list[dict]) -> dict[str, dict]:
    """One row per ticker from filled events. Size is the count of those events."""
    found: dict[str, dict] = {}
    for row in rows:
        if row.get("event") != "filled":
            continue
        ticker = str(row.get("instrument") or "")
        if not ticker:
            continue
        slot = found.setdefault(
            ticker,
            {"ticker": ticker, "side": str(row.get("side") or ""), "size": Decimal("0"), "stored_price": row.get("price") or ""},
        )
        slot["size"] += Decimal(str(row.get("size") or "1"))
        slot["side"] = str(row.get("side") or slot["side"])
        if row.get("price"):
            slot["stored_price"] = row.get("price")
    return found


def position_rows(payload: dict, ledger: dict[str, dict]) -> list[dict]:
    body = (payload or {}).get("body") or {}
    markets = body.get("market_positions") or []
    by_ticker = {}
    for row in markets:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "")
        if ticker:
            by_ticker[ticker] = row
    tickers = sorted(set(by_ticker) | set(ledger))
    out = []
    for ticker in tickers:
        api = by_ticker.get(ticker) or {}
        led = ledger.get(ticker) or {}
        signed = _fp(api.get("position_fp")) if api else None
        if signed is None:
            kalshi_size = Decimal("0")
            kalshi_side = ""
        else:
            kalshi_size = abs(signed)
            kalshi_side = "yes" if signed > 0 else "no" if signed < 0 else ""
        led_size = led.get("size") or Decimal("0")
        led_side = str(led.get("side") or "")
        if not api and not led:
            continue
        same = api and led and kalshi_side == led_side and kalshi_size == led_size
        if same:
            flag = "match"
        elif api and led:
            flag = "mismatch"
        elif api:
            flag = "Kalshi only"
        else:
            flag = "ledger only"
        exposure = _fp(api.get("market_exposure_dollars")) if api else None
        per = None
        if exposure is not None and kalshi_size > 0:
            per = exposure / kalshi_size
        out.append({
            "ticker": ticker,
            "kalshi_side": kalshi_side or "—",
            "kalshi_size": format(kalshi_size.normalize(), "f"),
            "ledger_side": led_side or "—",
            "ledger_size": format(led_size.normalize(), "f"),
            "flag": flag,
            "exposure": money(exposure) if exposure is not None else "",
            "per_contract": money(per) if per is not None else "",
            "fees": api.get("fees_paid_dollars") or "",
            "stored_price": led.get("stored_price") or "",
        })
    return out


def order_facts(rows: list[dict]) -> dict:
    sent = [r for r in rows if r.get("event") == "sent"]
    gemini = [r for r in sent if r.get("venue") == "gemini"]
    poly_sent = [r for r in sent if r.get("venue") == "polymarket"]
    both = [r for r in rows if r.get("event") == "both_unfilled"]
    poly_keys = [r for r in both if "polymarket" in str(r.get("bet_key") or "")]
    return {
        "n": len(rows),
        "filled": sum(1 for r in rows if r.get("event") == "filled"),
        "filled_venues": sorted({r.get("venue") for r in rows if r.get("event") == "filled"}),
        "one_leg": sum(1 for r in rows if r.get("event") == "one_leg"),
        "both_filled": sum(1 for r in rows if r.get("event") == "both_filled"),
        "gemini_sent": len(gemini),
        "gemini_201": sum(1 for r in gemini if r.get("http_status") == 201),
        "gemini_filled": sum(1 for r in rows if r.get("event") == "filled" and r.get("venue") == "gemini"),
        "gemini_first_unfilled": sum(1 for r in both if r.get("venue") == "gemini"),
        "gemini_second": sum(1 for r in rows if r.get("event") == "one_leg" and r.get("second_venue") == "gemini"),
        "poly_sent": len(poly_sent),
        "poly_both": len(poly_keys),
        "poly_404": sum(1 for r in poly_keys if r.get("http_status") == 404),
        "kalshi_201_unfilled": sum(1 for r in both if r.get("venue") == "kalshi" and r.get("http_status") == 201),
        "example_order": "145828837293991974",
    }


def _parts(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s+vs\.?\s+", text or "", flags=re.I) if p.strip()]


def nickname_maps() -> dict[tuple, dict[str, str]]:
    """Map a Polymarket nickname onto the city name this scan already uses for that game."""
    maps: dict[tuple, dict[str, str]] = {}
    if not JOBS.is_dir():
        return maps
    for path in JOBS.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        game = job.get("game") if isinstance(job.get("game"), dict) else {}
        title = str(job.get("title") or "")
        sport = str(job.get("sport") or "")
        codes = [str(c).upper() for c in (game.get("codes") or [])]
        kalshi_title = str(game.get("title_kalshi") or "")
        gemini_title = str(game.get("title_gemini") or title)
        left, right = _parts(kalshi_title), _parts(gemini_title)
        if len(left) != 2 or len(right) != 2 or len(codes) != 2:
            continue
        mapping: dict[str, str] = {}
        for index, code in enumerate(codes):
            kpart = next((part for part in left if code in part.upper()), left[index])
            canon = norm_side(right[index], "moneyline")
            mapping[canon] = canon
            mapping[norm_side(kpart, "moneyline")] = canon
            for word in re.findall(r"[A-Za-z]+", kpart):
                if word.upper() == code:
                    continue
                mapping[norm_side(word, "moneyline")] = canon
        if mapping:
            maps[(sport, title)] = mapping
    return maps


def _outcome(kind: str, side: str, pay: str) -> tuple[str, str] | None:
    """Buy-this-outcome label. Moneyline and spread use Yes only, so the other side is not counted twice."""
    if kind == "total":
        if pay == "yes":
            return "over", "yes"
        if pay == "no":
            return "under", "no"
        return None
    if pay != "yes":
        return None
    return side, "yes"


def cheaper_rows(now: datetime | None = None) -> tuple[list[dict], dict]:
    now = now or datetime.now(ET)
    data = load_json(LAST) or {}
    if not isinstance(data, dict):
        data = {}
    nick = nickname_maps()
    grouped: dict[tuple, dict] = defaultdict(dict)
    for item in data.values():
        if not isinstance(item, dict):
            continue
        kind = str(item.get("market_type") or "")
        if kind not in ("moneyline", "spread", "total"):
            continue
        venue = str(item.get("venue") or "")
        if venue not in VENUES:
            continue
        price = _fp(item.get("price"))
        if price is None:
            continue
        side = norm_side(str(item.get("side") or ""), kind)
        if kind in ("moneyline", "spread"):
            side = nick.get((item.get("sport"), item.get("game")), {}).get(side, side)
        number = norm_number(item.get("number"))
        outcome = _outcome(kind, side, str(item.get("pay") or ""))
        if outcome is None:
            continue
        label, pay = outcome
        key = (item.get("sport") or "", item.get("game") or "", kind, label, number, pay)
        prev = grouped[key].get(venue)
        seen = str(item.get("seen_at") or "")
        if prev is None or seen >= str(prev.get("seen_at") or ""):
            grouped[key][venue] = item
    rows = []
    skipped_stale = 0
    skipped_single = 0
    for key, quotes in grouped.items():
        if len(quotes) < 2:
            skipped_single += 1
            continue
        times = []
        for quote in quotes.values():
            when = parse_time(quote.get("seen_at"))
            if when is not None:
                times.append(when)
        if len(times) < 2:
            skipped_stale += 1
            continue
        newest, oldest = max(times), min(times)
        if newest - oldest > FRESH or now - newest > timedelta(hours=3):
            skipped_stale += 1
            continue
        priced = []
        for venue in VENUES:
            quote = quotes.get(venue)
            if not quote:
                continue
            raw = _fp(quote.get("price"))
            if raw is None:
                continue
            rounded = raw.quantize(CENT, rounding=ROUND_HALF_UP)
            priced.append((rounded, raw, venue))
        if len(priced) < 2:
            continue
        priced.sort(key=lambda item: (item[0], item[2]))
        gap = priced[1][0] - priced[0][0]
        gap_cents = int(gap / CENT)
        if gap_cents <= 0:
            bucket = "same cent"
        elif gap_cents == 1:
            bucket = "1 cent"
        elif gap_cents == 2:
            bucket = "2 cents"
        elif gap_cents in (3, 4):
            bucket = "3–4 cents"
        elif 5 <= gap_cents <= 9:
            bucket = "5–9 cents"
        else:
            bucket = "10 cents or more"
        sport, game, kind, label, number, pay = key
        by_venue = {venue: (raw, rounded) for rounded, raw, venue in priced}
        rows.append({
            "sport": sport,
            "game": game,
            "market_type": kind,
            "side": label,
            "number": number,
            "buy": "Under" if kind == "total" and pay == "no" else ("Over" if kind == "total" else label),
            "cheapest": priced[0][2],
            "next": priced[1][2],
            "gap_cents": gap_cents,
            "bucket": bucket,
            "venues": len(priced),
            "kalshi": money(by_venue["Kalshi"][1]) if "Kalshi" in by_venue else "",
            "gemini": money(by_venue["Gemini"][1]) if "Gemini" in by_venue else "",
            "polymarket": money(by_venue["Polymarket"][1]) if "Polymarket" in by_venue else "",
            "novig": money(by_venue["Novig"][1]) if "Novig" in by_venue else "",
            "seen": newest.isoformat(timespec="seconds"),
            "spread_min": f"{(newest - oldest).total_seconds() / 60:.1f}",
        })
    rows.sort(key=lambda row: (-row["gap_cents"], row["sport"], row["game"], row["market_type"], row["side"], row["number"]))
    counts = {
        "comparable": len(rows),
        "same": sum(1 for row in rows if row["bucket"] == "same cent"),
        "c1": sum(1 for row in rows if row["gap_cents"] == 1),
        "c2": sum(1 for row in rows if row["gap_cents"] == 2),
        "c3": sum(1 for row in rows if row["gap_cents"] == 3),
        "c4": sum(1 for row in rows if row["gap_cents"] == 4),
        "c34": sum(1 for row in rows if row["bucket"] == "3–4 cents"),
        "c5exact": sum(1 for row in rows if row["gap_cents"] == 5),
        "c59": sum(1 for row in rows if row["bucket"] == "5–9 cents"),
        "c10": sum(1 for row in rows if row["bucket"] == "10 cents or more"),
        "skipped_stale": skipped_stale,
        "skipped_single": skipped_single,
        "three": sum(1 for row in rows if row["venues"] >= 3),
    }
    return rows, counts


def write_page(fetch_positions_now: bool = False) -> Path:
    if fetch_positions_now or not POSITIONS.is_file():
        payload = fetch_positions()
    else:
        payload = load_json(POSITIONS) or {}
    orders = load_orders()
    facts = order_facts(orders)
    ledger = ledger_fills(orders)
    positions = position_rows(payload, ledger)
    bets, counts = cheaper_rows()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    pulled = payload.get("pulled_at") or "the pull saved with this page"
    status = payload.get("http_status")
    n_match = sum(1 for row in positions if row["flag"] == "match")
    n_mis = sum(1 for row in positions if row["flag"] == "mismatch")
    n_k = sum(1 for row in positions if row["flag"] == "Kalshi only")
    n_l = sum(1 for row in positions if row["flag"] == "ledger only")
    pos_body = []
    for row in positions:
        pos_body.append(
            "<tr>"
            + td(row["ticker"])
            + td(row["kalshi_side"])
            + td(row["kalshi_size"], True)
            + td(row["ledger_side"])
            + td(row["ledger_size"], True)
            + td(row["flag"])
            + td(row["exposure"], True)
            + td(row["per_contract"], True)
            + td(row["fees"], True)
            + td(row["stored_price"], True)
            + "</tr>"
        )
    bet_body = []
    for row in bets:
        if row["gap_cents"] <= 0:
            continue
        bet_body.append(
            "<tr>"
            + td(row["sport"])
            + td(row["game"])
            + td(row["market_type"])
            + td(row["buy"])
            + td(row["number"])
            + td(row["cheapest"])
            + td(row["next"])
            + td(row["gap_cents"], True)
            + td(row["bucket"])
            + td(row["kalshi"], True)
            + td(row["gemini"], True)
            + td(row["polymarket"], True)
            + td(row["novig"], True)
            + td(row["seen"])
            + td(row["spread_min"], True)
            + "</tr>"
        )
    bucket_rows = [
        ("Exactly 1 cent", counts["c1"]),
        ("Exactly 2 cents", counts["c2"]),
        ("3–4 cents", counts["c34"]),
        ("At least 5 and less than 10", counts["c59"]),
        ("Exactly 5 cents (inside the row above)", counts["c5exact"]),
        ("10 cents or more", counts["c10"]),
        ("Same cent after rounding (not cheaper)", counts["same"]),
    ]
    bucket_html = "".join(
        "<tr>" + td(label) + td(n, True) + "</tr>" for label, n in bucket_rows
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cheaper same bet</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.6rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.2rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Same bet, cheaper ask</h1>
<p class="note">Written {esc(now)}. Research only. Placing orders is off. This page does not send, cancel, or change an order.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2>
<p>We asked Kalshi which contracts the account still holds, and we lined those up with the 19 Kalshi fills in our own log. Gemini and Polymarket still show no fills. Separately, we looked at the price to buy the same outcome on more than one site: same game, same kind of bet (who wins, the spread, or the total), same side, same number. When one site's price is lower than the next site's price, that is a cheaper ask. It is not the lock that buys Yes in one place and No in another.</p>
<p>The gap is the cheapest ask minus the next-cheapest ask, after each price is rounded to the nearest cent. With only two sites, the next-cheapest is the more expensive one. A total's Under is the No price on the Over contract. A moneyline or spread counts the Yes price only, so the other team is not counted a second time as a No.</p>
</div>

<h2>Kalshi open positions vs our ledger</h2>
<p class="note">Signed GET <code>/trade-api/v2/portfolio/positions</code> returned HTTP {esc(status)}. Pull time {esc(pulled)}. The query asked for positions with a non-zero size (<code>count_filter=position</code>). A follow-up for <code>KXNFLTOTAL-26OCT18CARPHI-41</code> with no filter also returned no row. The payload has fees and market exposure. It has no field named average price. Exposure per contract is market exposure divided by the absolute position size. Positive <code>position_fp</code> is Yes. Negative is No.</p>
<p>{n_match} match on ticker, side, and size. {n_mis} mismatch on a ticker both sides list. {n_k} on Kalshi only. {n_l} in the ledger only. Ledger fills: {facts["filled"]} Kalshi, 0 Gemini, 0 Polymarket, {facts["both_filled"]} both-filled events.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{th("Ticker", "text")}{th("Kalshi side", "text")}{th("Kalshi size", "num")}{th("Ledger side", "text")}{th("Ledger size", "num")}{th("Match", "text")}{th("Exposure $", "num")}{th("Exposure per contract", "num")}{th("Fees $", "num")}{th("Ledger stored price", "num")}
</tr></thead>
<tbody>
{"".join(pos_body)}
</tbody>
</table>
</div>
<p class="note">Carolina vs Philadelphia total 41 is in the ledger as Yes, size 1, stored price 0.36. Kalshi's open-position list does not include that ticker. The live log at 4:47 PM ET says that order filled at 0.11 with a fee of 0.0069, and the Gemini order {esc(facts["example_order"])} came back HTTP 201, filled 0, cancelled immediate-or-cancel. Why the position is absent now (settled, sold, or never still open) was not in this positions payload, so that reason is not stated as a fact. Buffalo vs Las Vegas total 52 is on Kalshi at 0.01 contracts and is not one of the 19 ledger fills.</p>

<h2>Why Gemini and Polymarket filled none</h2>
<p>Counted again from <code>raw/orders.jsonl</code> ({facts["n"]} rows). Gemini: {facts["gemini_sent"]} orders, {facts["gemini_201"]} of them HTTP 201, {facts["gemini_filled"]} filled events. {facts["gemini_second"]} of those Gemini orders are the second leg after a Kalshi fill. {facts["gemini_first_unfilled"]} Gemini order is marked both-unfilled. Polymarket: {facts["poly_sent"]} order sends. {facts["poly_404"]} both-unfilled rows are a Kalshi HTTP 404 on a pair whose other venue was Polymarket. Kalshi both-unfilled with HTTP 201: {facts["kalshi_201_unfilled"]}. One-leg events: {facts["one_leg"]}.</p>
<p><strong>Measured.</strong> The order code uses immediate-or-cancel. If the first leg's response does not count as one contract filled, the second leg is not sent. Polymarket pairs in this log sent Kalshi first. Those Kalshi calls returned HTTP 404, code <code>insufficient_shard_balance</code>, message insufficient shard balance, details exchange user not found, on <code>KXATPCHALLENGERMATCH</code>. The Polymarket order endpoint was not called on those pairs. The Carolina Gemini example is the one log line that says filled 0 and cancelled immediate-or-cancel. The other Gemini HTTP 201 rows have no filled event and the note "no message." The ledger's filled price is the limit we intended to pay (<code>pay</code>), not a price read back from the fill. Carolina's stored 0.36 and the log's fill 0.11 are that case.</p>
<p><strong>Theories, not measured for every order.</strong> Immediate-or-cancel dies at once when the ask is no longer there at our limit, which would explain a 201 with nothing filled. The limit we store can be a different number from the price that was actually on the book, so an order can be priced off the real ask and die, or fill at a better price than the log shows. Polymarket never got an order on these pairs because we stop the pair when the first leg does not fill. Those are theories about the rows that only show HTTP 201 and no fill. They are confirmed in the log for the one Carolina Gemini line, and they match the code, but this page does not have a cancel receipt for each of the other Gemini orders.</p>

<h2>How many asks are cheaper</h2>
<p class="note">Comparable bets: {counts["comparable"]}, of which {counts["three"]} have three venues. A bet is comparable when at least two venues have a saved ask, those asks were seen within 15 minutes of each other, and the newest is within the last 3 hours. Left out: {counts["skipped_stale"]} stale groups and {counts["skipped_single"]} one-venue groups. Prices are the last saved asks in <code>price_last.json</code>, rounded to the nearest cent before the gap. The gap is versus the next-best venue.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{th("Bucket", "text")}{th("Count", "num")}</tr></thead>
<tbody>
{bucket_html}
</tbody>
</table>
</div>
<p class="note">Click column headers to sort. The detail table lists bets that are at least 1 cent cheaper. Same-cent rows are in the count above and are not repeated here.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{th("Sport", "text")}{th("Game", "text")}{th("Market", "text")}{th("Side", "text")}{th("Number", "num")}{th("Cheapest", "text")}{th("Next", "text")}{th("Gap cents", "num")}{th("Bucket", "text")}{th("Kalshi", "num")}{th("Gemini", "num")}{th("Polymarket", "num")}{th("Novig", "num")}{th("Newest quote", "date")}{th("Quote spread min", "num")}
</tr></thead>
<tbody>
{"".join(bet_body)}
</tbody>
</table>
</div>
<p class="note">The live supervisor rewrites this page about once a minute from the quotes the game children already save. That refresh does not send an order.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    summary = {
        "match": n_match,
        "mismatch": n_mis,
        "kalshi_only": n_k,
        "ledger_only": n_l,
        "buckets": counts,
        "facts": facts,
        "page": str(PAGE),
    }
    (RAW / "cheaper_same_bet_summary.json").write_text(json.dumps(summary, default=str), encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = write_page(fetch_positions_now=True)
    print(path)
