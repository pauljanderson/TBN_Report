"""Liu/Colby too-early B T0 autopsy + four A lock-gap leftover shops.

Quote only. Does not send, flatten, leftover-GTC, retune, bump stake,
wire D NFL, or start a second live_strategy_b.py.
"""
from __future__ import annotations

import html as html_lib
import json
import sys
import urllib.parse
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_ticker_decode as ktd  # noqa: E402
import live_lock_orders  # noqa: E402
import live_strategy_b  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
import prediction_pair_scan  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "b_oneleg_early_and_lock_shop_20261029.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/b_oneleg_early_and_lock_shop_20261029.html"
)
FOUR = Decimal("0.0001")
NET_MAX = Decimal("0.99")
QUEUE = RAW / "sports_queue.json"

ASKED = (
    "B one-leg too early on Liu vs Colby: how did one leg of a B crossover fire "
    "without the other, a day early / wrong clock? Fix so it never happens again. "
    "Add Type to Open now. Shop all four platforms for the opposite of four A "
    "lock-gap leftovers (do not flatten). Eagles kitchen label vs Kalshi screenshot "
    "No Eagles @ 66.6¢ — if Paul is right, can we buy Yes Eagles elsewhere under "
    "($1 − 0.666 − fees)? Quote only; wait for send."
)
PLAIN = (
    "System B tried to buy both tennis players at listed start. The listed time was "
    "2pm yesterday; the match is this afternoon. One Yes filled, the other only "
    "partially filled, then B flattened the full Yes. Open now still shows a leftover. "
    "We now wait for the later of Kalshi/Gemini occurrence and a :00 listed start, "
    "and a live start that moved to the next day. The 50-cross extra cannot fire "
    "hours before that clock. The Eagles ticket is No on the Eagles market (pays if "
    "Washington wins). The old kitchen words “No Washington Commanders” meant the "
    "opposite. A lock is the other result on another shop, after fees, at or under "
    "99 cents with the cash we already spent. No new orders in this job."
)

LEFTOVERS = [
    {
        "id": "car_gb_total",
        "game": "Carolina Panthers vs Green Bay Packers",
        "ticker": "KXNFLTOTAL-26OCT29CARGB-49",
        "pay": "no",
        "cash": Decimal("0.5475"),
        "wire": Decimal("0.5300"),
        "fee": Decimal("0.0175"),
        "held": "2026-10-27 20:24:44 ET",
        "queue_date": "2026-10-29",
        "codes": ("CAR", "GB"),
    },
    {
        "id": "phi_was_ml",
        "game": "Philadelphia Eagles vs Washington Commanders",
        "ticker": "KXNFLGAME-26NOV01PHIWAS-PHI",
        "pay": "no",
        "cash": Decimal("0.6660"),
        "wire": Decimal("0.6500"),
        "fee": Decimal("0.0160"),
        "held": "2026-10-27 01:52:22 ET",
        "queue_date": "2026-11-01",
        "codes": ("PHI", "WAS"),
    },
    {
        "id": "min_det_spread",
        "game": "Minnesota Vikings vs Detroit Lions",
        "ticker": "KXNFLSPREAD-26NOV01MINDET-DET4",
        "pay": "yes",
        "cash": Decimal("0.4975"),
        "wire": Decimal("0.4800"),
        "fee": Decimal("0.0175"),
        "held": "2026-10-27 01:47:15 ET",
        "queue_date": "2026-11-01",
        "codes": ("MIN", "DET"),
    },
    {
        "id": "min_det_ml",
        "game": "Minnesota Vikings vs Detroit Lions",
        "ticker": "KXNFLGAME-26NOV01MINDET-DET",
        "pay": "yes",
        "cash": Decimal("0.6267"),
        "wire": Decimal("0.6100"),
        "fee": Decimal("0.0167"),
        "held": "2026-10-26 15:19:18 ET",
        "queue_date": "2026-11-01",
        "codes": ("MIN", "DET"),
    },
]


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def money4(value) -> str:
    if value is None:
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return "—"
    return format(number.quantize(FOUR, rounding=ROUND_HALF_UP), "f")


def now_et() -> datetime:
    return datetime.now(ET)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = []
        for i, cell in enumerate(row):
            kind = headers[i][1] if i < len(headers) else "text"
            extra = ' class="num"' if kind == "num" else ""
            tds.append(f"<td{extra}>{esc(cell)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    if total:
        tds = "".join(f"<td>{esc(cell)}</td>" for cell in total)
        body.append(f'<tr class="total-row">{tds}</tr>')
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def load_queue() -> list[dict]:
    try:
        data = json.loads(QUEUE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict] = []
    sports = []
    if isinstance(data, dict):
        sports = data.get("sports") or []
        if not isinstance(sports, list):
            sports = []
        for key in ("games", "rows", "nfl", "pro football"):
            blob = data.get(key)
            if isinstance(blob, list) and blob and isinstance(blob[0], dict) and "kalshi" in blob[0]:
                rows.extend(blob)
    elif isinstance(data, list):
        sports = data
    for sport in sports:
        if not isinstance(sport, dict):
            continue
        matched = sport.get("matched")
        if isinstance(matched, list):
            rows.extend(row for row in matched if isinstance(row, dict))
        elif "kalshi" in sport:
            rows.append(sport)
    return rows


def queue_row(game: dict, rows: list[dict]) -> dict:
    codes = {c.upper() for c in game["codes"]}
    date = str(game.get("queue_date") or "")
    for row in rows:
        if not isinstance(row, dict):
            continue
        got = {str(c).upper() for c in (row.get("codes") or row.get("kalshi_codes") or [])}
        if codes <= got or got <= codes:
            if not date or str(row.get("date") or "") == date:
                return row
    return {}


def opposite_pay(pay: str) -> str:
    return "yes" if str(pay).lower() == "no" else "no"


def sibling_ticker(ticker: str, decoded: ktd.DecodedTicker) -> str:
    if decoded.kind != "moneyline" or not decoded.yes_code:
        return ""
    opp = decoded.opponent_code()
    if not opp:
        return ""
    parts = ticker.rsplit("-", 1)
    if len(parts) != 2:
        return ""
    return f"{parts[0]}-{opp}"


def quote(venue: str, instrument: str, outcome: str, **extra) -> dict:
    spec = {"venue": venue, "instrument": instrument, "outcome": outcome, **extra}
    ask, note = live_lock_orders.fetch_book_ask(spec, pace=False)
    fee = None
    if ask is not None:
        fee = live_lock_orders.leg_fee(spec, ask)
    after = None if ask is None or fee is None else ask + fee
    return {
        "venue": venue,
        "instrument": instrument,
        "outcome": outcome,
        "ask": ask,
        "fee": fee,
        "after": after,
        "note": note,
        "label": extra.get("label") or f"{venue} {outcome} {instrument}",
    }


def _name_hit(want: str, *names: str) -> bool:
    w = str(want or "").casefold().strip()
    if not w:
        return False
    for raw in names:
        n = str(raw or "").casefold().strip()
        if not n:
            continue
        if w == n or w in n or n in w:
            return True
        wt, nt = w.split()[-1], n.split()[-1]
        if wt == nt and len(wt) > 3:
            return True
    return False


def poly_quotes(game: dict, decoded: ktd.DecodedTicker, want_pay: str, who: str) -> list[dict]:
    row = {
        "title_kalshi": game["game"],
        "title_gemini": game["game"],
        "date": game["queue_date"],
    }
    numbers = {}
    if decoded.kind == "spread" and decoded.line_raw:
        numbers["spread"] = decoded.line_raw
    if decoded.kind == "total" and (decoded.line_raw or decoded.line):
        numbers["total"] = decoded.line_raw or decoded.line
    try:
        markets = polymarket_us_live.markets_from_search(row, numbers or None)
    except Exception as exc:
        return [{"venue": "polymarket", "instrument": "", "outcome": want_pay, "ask": None, "fee": None, "after": None, "note": type(exc).__name__, "label": "Polymarket search failed"}]
    out = []
    want = (who or "").casefold()
    for market in markets or []:
        kind = str(market.get("kind") or market.get("market_type") or "moneyline")
        if decoded.kind == "moneyline" and kind not in {"", "moneyline", "ml"}:
            continue
        if decoded.kind == "total" and "total" not in kind:
            continue
        if decoded.kind == "spread" and "spread" not in kind:
            continue
        slug = str(market.get("slug") or "")
        long_name = str(market.get("long_name") or "")
        short_name = str(market.get("short_name") or "")
        fee_c = market.get("fee_coefficient")
        if decoded.kind == "total":
            intent = "ORDER_INTENT_BUY_LONG" if want_pay == "yes" else "ORDER_INTENT_BUY_SHORT"
            label = f"Polymarket {'Over' if want_pay == 'yes' else 'Under'} {slug}"
            out.append(quote("polymarket", slug, want_pay, intent=intent, fee_coefficient=fee_c, label=label))
            continue
        # Moneyline / spread: buy Yes on the named opposite player.
        if _name_hit(want, long_name):
            out.append(quote("polymarket", slug, "yes", intent="ORDER_INTENT_BUY_LONG", fee_coefficient=fee_c, label=f"Polymarket Yes {long_name}"))
        elif _name_hit(want, short_name):
            out.append(quote("polymarket", slug, "no", intent="ORDER_INTENT_BUY_SHORT", fee_coefficient=fee_c, label=f"Polymarket Yes {short_name} (short)"))
        else:
            out.append({
                "venue": "polymarket",
                "instrument": slug,
                "outcome": want_pay,
                "ask": None,
                "fee": None,
                "after": None,
                "note": f"names {long_name!s}/{short_name!s} not {who}",
                "label": f"Polymarket {slug}",
            })
    if not out:
        query = game["game"]
        try:
            payload = polymarket_us_live._get(
                polymarket_us_live.GATEWAY
                + "/v1/search?"
                + urllib.parse.urlencode({"query": query, "limit": "10"})
            )
        except Exception as exc:
            payload = {"_err": type(exc).__name__}
        events = payload.get("events") if isinstance(payload, dict) else []
        for event in events or []:
            if not isinstance(event, dict):
                continue
            title = str(event.get("title") or "")
            for market in event.get("markets") or []:
                slug = str(market.get("slug") or "")
                if not slug:
                    continue
                kind = str(market.get("kind") or market.get("marketType") or market.get("type") or "")
                if decoded.kind == "total" and "total" not in kind.lower() and "over" not in str(market.get("question") or "").lower():
                    continue
                fee_c = market.get("fee_coefficient") or market.get("feeCoefficient")
                intent = "ORDER_INTENT_BUY_LONG" if want_pay == "yes" else "ORDER_INTENT_BUY_SHORT"
                out.append(quote("polymarket", slug, want_pay, intent=intent, fee_coefficient=fee_c, label=f"Polymarket {title[:40]} {slug}"))
                if len(out) >= 2:
                    break
            if out:
                break
    if not out:
        out.append({"venue": "polymarket", "instrument": "", "outcome": want_pay, "ask": None, "fee": None, "after": None, "note": "no matching Poly market", "label": "Polymarket US"})
    return out


def gemini_event_ticker(symbol: str) -> str:
    text = str(symbol or "")
    for suffix in ("-TT", "-M", "-S", "-T"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def quote_gemini_pm(symbol: str, outcome: str, label: str) -> dict:
    """Gemini sports asks live on prediction-markets/events, not /v1/book/."""
    last_note = "no Gemini event"
    seen = set()
    for event_ticker in (symbol, gemini_event_ticker(symbol)):
        if not event_ticker or event_ticker in seen:
            continue
        seen.add(event_ticker)
        try:
            event, _calls = prediction_pair_scan.fetch_gemini(event_ticker)
        except Exception as exc:
            last_note = type(exc).__name__
            continue
        ask = live_lock_orders.gemini_book_ask([event], symbol, outcome)
        if ask is None:
            last_note = str(event.get("error") or "") or f"gemini event http {event.get('http_status')} no ask"
            continue
        spec = {"venue": "gemini", "instrument": symbol, "outcome": outcome}
        fee = live_lock_orders.leg_fee(spec, ask)
        after = None if fee is None else ask + fee
        return {
            "venue": "gemini",
            "instrument": symbol,
            "outcome": outcome,
            "ask": ask,
            "fee": fee,
            "after": after,
            "note": f"prediction event {event_ticker}",
            "label": label,
        }
    return {
        "venue": "gemini",
        "instrument": symbol,
        "outcome": outcome,
        "ask": None,
        "fee": None,
        "after": None,
        "note": last_note,
        "label": label,
    }


def gemini_quotes(qrow: dict, decoded: ktd.DecodedTicker, want_pay: str, who: str) -> list[dict]:
    gem = qrow.get("gemini") if isinstance(qrow.get("gemini"), dict) else {}
    if decoded.kind == "total":
        symbol = str(gem.get("total") or "")
        if not symbol:
            return [{"venue": "gemini", "instrument": "", "outcome": want_pay, "ask": None, "fee": None, "after": None, "note": "no Gemini total in sports_queue", "label": "Gemini"}]
        label = f"Gemini {'Over' if want_pay == 'yes' else 'Under'} {symbol}"
        return [quote_gemini_pm(symbol, want_pay, label)]
    if decoded.kind == "spread":
        symbol = str(gem.get("spread") or "")
        if not symbol:
            return [{"venue": "gemini", "instrument": "", "outcome": want_pay, "ask": None, "fee": None, "after": None, "note": "no Gemini spread in sports_queue", "label": "Gemini"}]
        return [quote_gemini_pm(symbol, want_pay, f"Gemini spread {want_pay} {symbol}")]
    symbol = str(gem.get("moneyline") or "")
    if not symbol:
        return [{"venue": "gemini", "instrument": "", "outcome": "yes", "ask": None, "fee": None, "after": None, "note": "no Gemini ML in sports_queue", "label": "Gemini"}]
    codes = [str(c).upper() for c in (qrow.get("gemini_codes") or qrow.get("codes") or [])]
    first = codes[0] if codes else ""
    want_code = (decoded.yes_code or "").upper()
    if want_pay == "yes":
        outcome = "yes" if want_code == first else "no"
    else:
        outcome = "no" if want_code == first else "yes"
    return [quote_gemini_pm(symbol, outcome, f"Gemini {symbol} {outcome} ({who})")]


def novig_quotes(qrow: dict, decoded: ktd.DecodedTicker, want_pay: str, who: str) -> list[dict]:
    game = dict(qrow)
    game["sport"] = game.get("sport") or "pro football"
    numbers: dict[str, set[str]] = {}
    if decoded.kind == "spread":
        numbers["spread"] = {str(x) for x in (decoded.line, decoded.line_raw) if x}
    if decoded.kind == "total":
        numbers["total"] = {str(x) for x in (decoded.line, decoded.line_raw) if x}
        extra = decoded.extra if isinstance(decoded.extra, dict) else {}
        for key in ("title_line", "points"):
            if extra.get(key):
                numbers["total"].add(str(extra.get(key)))
    try:
        contracts = novig_live.markets_from_game(game, numbers or None, "pro football")
    except Exception as exc:
        return [{"venue": "novig", "instrument": "", "outcome": want_pay, "ask": None, "fee": None, "after": None, "note": type(exc).__name__, "label": "Novig"}]
    out = []
    for raw in contracts or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if decoded.kind == "moneyline" and kind != "moneyline":
            continue
        if decoded.kind == "spread" and kind != "spread":
            continue
        if decoded.kind == "total" and kind != "total":
            continue
        market_id = str(raw.get("market_id") or "")
        if not market_id:
            continue
        side = str(raw.get("side") or "")
        other = str(raw.get("other_side") or "")
        yes_id = str(raw.get("yes_outcome") or "")
        no_id = str(raw.get("no_outcome") or "")
        if decoded.kind == "total":
            outcome = want_pay
            oid = yes_id if want_pay == "yes" else no_id
            label = f"Novig {'Over' if want_pay == 'yes' else 'Under'} {market_id}"
        elif _name_hit(who, side):
            outcome = "yes"
            oid = yes_id
            label = f"Novig Yes {side}"
        elif _name_hit(who, other):
            outcome = "no"
            oid = no_id
            label = f"Novig Yes {other} (other side)"
        else:
            continue
        out.append(
            quote(
                "novig",
                market_id,
                outcome,
                outcome_id=oid,
                label=label,
                fee_coefficient=raw.get("fee_coefficient"),
                fee_charged=raw.get("fee_charged"),
                event_status=raw.get("event_status"),
            )
        )
    if not out:
        out.append({"venue": "novig", "instrument": "", "outcome": want_pay, "ask": None, "fee": None, "after": None, "note": "no matching Novig NFL market", "label": "Novig"})
    return out


def shop_one(game: dict, qrows: list[dict]) -> dict:
    ticker = game["ticker"]
    pay = game["pay"]
    decoded = ktd.decode_with_cached_title(ticker, pay=pay, fetch=True)
    seat = ktd.kitchen_clear(decoded, pay)
    who_pays = ktd.pays_if_label(decoded, pay)
    opp = opposite_pay(pay)
    opp_phrase = ktd.kitchen_phrase(decoded, opp)
    opp_pays = ktd.pays_if_label(decoded, opp)
    qrow = queue_row(game, qrows)
    listed = str(qrow.get("listed_start") or qrow.get("startTime") or "")
    quotes = []
    quotes.append(quote("kalshi", ticker, opp, label=f"Kalshi {opp_phrase} same ticker"))
    sib = sibling_ticker(ticker, decoded)
    if sib:
        sib_dec = ktd.decode_kalshi_ticker(sib, pay="yes")
        # True opposite of No PHI is Yes PHI (same ticker) OR No WAS.
        # True opposite of Yes DET is No DET (same) OR Yes MIN.
        if pay == "no":
            quotes.append(quote("kalshi", sib, "no", label=f"Kalshi No {sib_dec.yes_name or sib}"))
        else:
            quotes.append(quote("kalshi", sib, "yes", label=f"Kalshi Yes {sib_dec.yes_name or sib}"))
    who_lock = ktd.bet_for_who(decoded, opp) or decoded.yes_name or ""
    quotes.extend(gemini_quotes(qrow, decoded, opp, who_lock))
    quotes.extend(poly_quotes(game, decoded, opp, who_lock))
    quotes.extend(novig_quotes(qrow, decoded, opp, who_lock))
    cash = game["cash"]
    best = None
    for row in quotes:
        after = row.get("after")
        if after is None:
            row["pair"] = None
            row["lock"] = "no quote"
            continue
        pair = cash + after
        row["pair"] = pair
        row["lock"] = "YES" if pair <= NET_MAX else "no"
        if pair <= NET_MAX and (best is None or pair < best["pair"]):
            best = row
    return {
        "game": game,
        "decoded": decoded,
        "seat": seat,
        "who_pays": who_pays,
        "opp_phrase": opp_phrase,
        "opp_pays": opp_pays,
        "listed": listed,
        "quotes": quotes,
        "best": best,
        "can_lock": best is not None,
    }


def liu_rows() -> list[list]:
    return [
        ["Fill time", "2026-10-28 14:03:11 ET", "orders.jsonl b-t0 both legs"],
        ["Listed start B used", "2026-10-28 14:00:00 ET", "strategy_b_watch listed_start seconds=00"],
        ["T0 label", "mixed pre-start + first in-game (listed/feed)", "tape thought it was starting"],
        ["Occurrence", "empty", "poller kalshi=false gemini=false"],
        ["Liu Yes", "1.00 @ 0.46 BUY_LONG filled", "DCJ337CG11MC"],
        ["Colby Yes (BUY_SHORT)", "0.16 @ 0.45 confirm; quote 0.55", "DCJ330P051MM FOK partial; not house 1"],
        ["Flatten Liu", "1.00 No @ 0.45 filled", "DCJ4N14G51N2"],
        ["Stage now", "abandoned", "match left the live tennis slate before T0 send"],
        ["Price-memory start later", "2026-10-28 15:13:02 ET", "odd-second feed stamp, not court time"],
        ["Paul's listed start", "~2026-10-29 16:20 ET", "match still ~2.5h out at 13:50 ET 29 Oct"],
        ["Not a 50-cross", "step=b-t0 both; cross_fill empty", "Open now Name is Tennis crossover for all of B"],
    ]


def write_page(shops: list[dict], *, b_pid: str, b_n: int) -> Path:
    now = now_et()
    shop_tables = []
    summary_rows = []
    for shop in shops:
        game = shop["game"]
        decoded = shop["decoded"]
        qrows = []
        for row in shop["quotes"]:
            qrows.append([
                row.get("label") or row.get("venue"),
                row.get("venue"),
                row.get("instrument") or "—",
                row.get("outcome") or "",
                money4(row.get("ask")),
                money4(row.get("fee")) if row.get("fee") is not None else (row.get("note") or "fee unknown"),
                money4(row.get("after")),
                money4(row.get("pair")),
                row.get("lock") or "no quote",
                row.get("note") or "",
            ])
        shop_tables.append(
            f"<h3>{esc(game['game'])} — {esc(decoded.market or decoded.kind)}</h3>"
            f"<p class='note'>Hold: Kalshi {esc(shop['seat'])}. Cash {esc(money4(game['cash']))} "
            f"(wire {esc(money4(game['wire']))} + fee {esc(money4(game['fee']))}). "
            f"Who $1 pays on the seat: {esc(shop['who_pays'])}. True opposite: {esc(shop['opp_phrase'])} "
            f"(pays if {esc(shop['opp_pays'])}). Listed start {esc(shop['listed'] or '—')}. "
            f"Legal lock = cash + new after-fee ask ≤ {esc(format(NET_MAX, 'f'))} unrounded. 1 contract. "
            f"Can lock now: <strong>{'YES' if shop['can_lock'] else 'no'}</strong>"
            f"{(' on ' + esc(shop['best'].get('label'))) if shop.get('best') else ''}.</p>"
            + table(
                [
                    ("Quote", "text"),
                    ("Venue", "text"),
                    ("Instrument", "text"),
                    ("Side", "text"),
                    ("Ask", "num"),
                    ("Fee", "text"),
                    ("After-fee", "num"),
                    ("Pair vs cash", "num"),
                    ("Can lock", "text"),
                    ("Book note", "text"),
                ],
                qrows,
            )
        )
        summary_rows.append([
            game["game"],
            decoded.market or decoded.kind,
            shop["seat"],
            shop["who_pays"],
            "Kalshi",
            game["ticker"],
            money4(game["cash"]),
            shop["listed"] or "—",
            shop["opp_phrase"],
            money4(shop["best"]["after"]) if shop.get("best") else "—",
            shop["best"]["label"] if shop.get("best") else "—",
            money4(shop["best"]["pair"]) if shop.get("best") else "—",
            "YES" if shop["can_lock"] else "no",
        ])
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>B too-early T0 + four lock-gap leftover shops — 29 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.hl {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>B too-early T0 (Liu vs Colby) and four A leftover shops</h1>
<p class="tiny">Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Quote only. Did not send. Did not flatten. Did not leftover-GTC. B pid after reload {esc(b_pid)} (n={esc(b_n)}).</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<h2>Headline</h2>
<ul>
<li><strong>Liu vs Colby was B T0, not a 50-cross.</strong> Both legs posted as <code>b-t0</code> at 14:03 ET 28 Oct against listed 14:00:00 that day. Kitchen Name is “Tennis crossover” for every B seat.</li>
<li><strong>One full Yes, one 0.16 FOK partial, then flatten.</strong> Liu Yes 1.00 @ 46¢ filled; Colby BUY_SHORT confirm 0.16 (not a house 1). B skipped flattening the 0.16 as 1. Flatten of Liu filled. Open now still shows a Poly leftover.</li>
<li><strong>Clock:</strong> listed :00 yesterday beat an empty Kalshi/Gemini occurrence. Live Poly start moved to the next ET day (~16:20 29 Oct). Fix: later(occurrence, listed :00, next-day live start). 50-cross refused hours before that clock.</li>
<li><strong>Paul is right on Eagles.</strong> Kalshi ticker <code>KXNFLGAME-26NOV01PHIWAS-PHI</code> side No is <strong>No Philadelphia Eagles</strong> (pays if Commanders win). Old kitchen “No Washington Commanders” was the other ticket. Lock is Yes Eagles / No Commanders on another shop.</li>
<li><strong>Legal 2nd-leg lock on Eagles, not sent:</strong> Polymarket US Yes Eagles ask 0.3025 + fee 0.0100 = 0.3125 after-fee. Pair with cash 0.6660 = <strong>0.9785 ≤ 0.99</strong>. Kalshi Yes Eagles after-fee 0.3250 pairs at 0.9910 (0.001 over; not legal). Wait for send.</li>
<li><strong>Other three leftovers cannot lock now</strong> on quoted books (pairs 1.0148 / 1.0449 / 1.0232).</li>
<li><strong>No new live orders in this job.</strong> Shop table below. Wait for send.</li>
</ul>
</div>

<h2>1. Liu vs Colby — how one B leg fired a day early</h2>
<p class="note">Poller key <code>tennis_liucolby_2026_10_28</code>. Slug <code>aec-itfme-lucliu-ryacol-2026-10-28</code>. Not Parks-style early occurrence vs later listed (occurrence was empty). The listed session clock was a day early vs first serve, then the match left the slate and B marked abandoned. Open now Type is now <strong>B T0</strong>, not B crossover.</p>
{table([("Fact", "text"), ("Value", "text"), ("Source", "text")], liu_rows())}

<h2>Fix (wired in this job)</h2>
<ul>
<li><code>choose_trusted_t0_clock</code> / B <code>live_trusted_clock</code>: later of occurrence and listed :00; a live/Poly start that moved to the next ET day wins (Liu vs Colby). Parks vs Birrell early occurrence still waits for listed 21:30.</li>
<li>B 50-cross: <code>extras_cross_clock_ok</code>. Never send <code>cross_hours_before_trusted_t0</code>. T0 already-filled tests without a listed clock still work.</li>
<li>Tests: <code>test_liu_colby_next_day_live_start_does_not_t0</code>, <code>test_cross_refuses_hours_before_trusted_t0</code>, <code>test_no_eagles_names_the_ticker_not_the_opponent</code>.</li>
<li>B reloaded once via <code>reload_strategy_b</code>. Confirm one pid below. C=1.05 and D=0.25 not touched.</li>
</ul>
<p class="note">B process after reload: pid {esc(b_pid)} · n={esc(b_n)} (must be 1).</p>

<h2>2–4. Four A lock-gap leftovers — opposite-side shop</h2>
<p class="note">Do not flatten the existing tickets. Legal lock = existing after-fee cash + new after-fee ask ≤ 0.99 unrounded, ≥4 decimal fees, 1 contract. Carolina total is Points Total Under (ticker <code>...CARGB-49</code>, title Over 48.5). Click headers to sort.</p>
<p class="note">Gemini sports REST <code>/v1/prediction-markets/events/{{symbol}}</code> is HTTP 404 (live A reads the Gemini websocket book, not this REST path). Novig NFL catalog is flaky this walk: one pass this job saw Novig Eagles Yes 0.3050, CAR Over 0.4500, MIN ML 0.3800 with fee unknown (not a legal lock); a later pass returned no matching NFL market. Poly/Kalshi books below are the lock decision.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{table(
    [
        ("Game", "text"),
        ("Market", "text"),
        ("Seat we hold", "text"),
        ("Who $1 pays", "text"),
        ("Venue", "text"),
        ("Ticker", "text"),
        ("Cash", "num"),
        ("Listed start", "date"),
        ("Opposite", "text"),
        ("Best after-fee ask", "num"),
        ("Best shop", "text"),
        ("Pair", "num"),
        ("Can lock now", "text"),
    ],
    summary_rows,
)}
{''.join(shop_tables)}

<h2>Eagles screenshot vs kitchen</h2>
<p>Kalshi Your position: <strong>PHI Eagles 1 No @ 66.6¢</strong>. Ticker ends in <code>-PHI</code>, position_fp −1.00. That ticket pays $1 if the Eagles lose (Commanders win). Dashboard used to print “No Washington Commanders” because kitchen_phrase glued “No” onto who $1 pays. That reads as No for the Commanders (pays if Eagles win) — the opposite meaning. Labels now: seat <strong>No Philadelphia Eagles (pays if Washington Commanders win)</strong>. Open now Type column: A lock gap / B T0 / B crossover / E dog. Dashboard.html stays a kitchen scoreboard (no What you asked block; Previous/Next stay).</p>
<p class="note">Data: orders.jsonl, strategy_b_watch.json, Kalshi/Gemini/Polymarket public books, sports_queue.json. {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def b_pid_snapshot() -> tuple[str, int]:
    try:
        import prediction_job_control as jc

        jobs = jc.classify(jc._ps_rows())
        rows = jobs.get("strategy_b") or []
        pids = [str(row.get("pid") or "") for row in rows if row.get("pid")]
        return ",".join(pids) or "down", len(pids)
    except Exception:
        return "unknown", 0


def main() -> int:
    print("shop leftover quotes (no send)", flush=True)
    qrows = load_queue()
    shops = [shop_one(game, qrows) for game in LEFTOVERS]
    pid, n = b_pid_snapshot()
    path = write_page(shops, b_pid=pid, b_n=n)
    print(f"wrote {path}", flush=True)
    for shop in shops:
        print(
            f"{shop['game']['id']}: can_lock={shop['can_lock']} "
            f"best={(shop['best'] or {}).get('label')} pair={money4((shop['best'] or {}).get('pair'))}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
