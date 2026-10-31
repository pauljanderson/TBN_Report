"""One-shot: Nagal 07:37:58 ET quote-vs-order page, plus backfill of that pair's log rows."""
from __future__ import annotations

import html as html_lib
import json
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from report_page_extras import CACHE_META, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402
import order_ledger  # noqa: E402
import venue_pace  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "nagal_trigger_quotes_20261020.html"
ORDERS = RAW / "orders.jsonl"
ORDER_IO = RAW / "order_io.jsonl"
ORDER_LOCK = RAW / "orders.lock"

ASKED = (
    "why did we send it for 0.59 the first time? did we see that that was the most recent bid on "
    "the kalshi feed? can you improve the log by showing what triggered the trades exactly? i assume "
    "it's the websocket feeds from both. show me the timestamps on the data we got and when we placed "
    "the orders"
)
PLAIN = (
    "We bought Kalshi Yes on Sumit Nagal at 0.59 and Polymarket No at 0.34 (wired as a short at 0.66) "
    "at 07:37:58 Eastern Time on October 20, 2026. 0.59 was the latest Kalshi Yes ask we would pay — "
    "a limit buy hits the ask, not the bid. Paul asked about the most recent bid; that is not what we "
    "used. The pair fired from the live websocket books: Polymarket printed No 0.34 at 07:37:57.491, "
    "and the same compare still had Kalshi Yes ask 0.59. Kalshi did not write that 0.59 into the quote "
    "history file (the ticker was not stored as a moneyline), but the live lock used the in-memory ask. "
    "Kalshi's order left 1.3 seconds after that Polymarket print; Polymarket's order left 1.6 seconds after. "
    "The order log now stores, for each leg, the quote source, quote price, quote time, send time, lag, "
    "and which quote update caused the claim."
)

KALSHI_SEEN = "2026-10-20T07:37:57.491377-04:00"
POLY_SEEN = "2026-10-20T07:37:57.491377-04:00"
TRIGGER = {
    "trigger_venue": "polymarket",
    "trigger_side": "no",
    "trigger_price": "0.3400",
    "trigger_seen_at": POLY_SEEN,
    "trigger_source": "websocket",
}
KALSHI_SENT = "2026-10-20T07:37:58.746686-04:00"
POLY_SENT = "2026-10-20T07:37:59.112686-04:00"
RECOVERY_SEEN = "2026-10-20T07:37:59.409193-04:00"
RECOVERY_SENT = "2026-10-20T07:38:00.258375-04:00"
KALSHI_OID = "01a1591a-8e38-77b7-8c14-cf870ec532e5"
POLY_OID = "D77RH8VG10JR"
RECOVERY_OID = "01a1591a-9220-7d8a-9e71-c85852bd93ee"
BET = "tennis\tnagsan\t2026-10-20\tmoneyline\tcode:NAG\t\tkalshi\tpolymarket"


def _esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{_esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def _lag(seen: str, sent: str) -> str:
    a = datetime.fromisoformat(seen)
    b = datetime.fromisoformat(sent)
    return format(Decimal(str(round((b - a).total_seconds(), 3))), "f")


def _backfill() -> None:
    kalshi_quote = {
        "quote_source": "websocket",
        "quote_price": "0.5900",
        "quote_seen_at": KALSHI_SEEN,
        **TRIGGER,
    }
    poly_quote = {
        "quote_source": "websocket",
        "quote_price": "0.3400",
        "quote_seen_at": POLY_SEEN,
        **TRIGGER,
    }
    recovery_quote = {
        "quote_source": "websocket",
        "quote_price": "0.5900",
        "quote_seen_at": RECOVERY_SEEN,
        **TRIGGER,
    }
    with venue_pace.FileLock(ORDER_LOCK):
        if ORDERS.exists():
            lines = ORDERS.read_text(encoding="utf-8").splitlines()
            out = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    out.append(line)
                    continue
                if row.get("bet_key") != BET:
                    out.append(json.dumps(row, ensure_ascii=False, default=str))
                    continue
                if row.get("event") == "claim":
                    row.update(TRIGGER)
                    row["compared_at"] = POLY_SEEN
                    row["legs"] = [
                        {"venue": "kalshi", "side": "yes", "quote_source": "websocket", "quote_price": "0.5900", "quote_seen_at": KALSHI_SEEN},
                        {"venue": "polymarket", "side": "no", "quote_source": "websocket", "quote_price": "0.3400", "quote_seen_at": POLY_SEEN},
                    ]
                elif row.get("event") == "sent" and row.get("venue") == "kalshi" and row.get("order_id") == KALSHI_OID:
                    row.update(kalshi_quote)
                    row["sent_at"] = KALSHI_SENT
                    row["lag_seconds"] = _lag(KALSHI_SEEN, KALSHI_SENT)
                elif row.get("event") == "sent" and row.get("venue") == "polymarket":
                    row.update(poly_quote)
                    row["sent_at"] = POLY_SENT
                    row["lag_seconds"] = _lag(POLY_SEEN, POLY_SENT)
                elif row.get("event") == "sent" and row.get("venue") == "kalshi" and row.get("order_id") == RECOVERY_OID:
                    row.update(recovery_quote)
                    row["sent_at"] = RECOVERY_SENT
                    row["lag_seconds"] = _lag(RECOVERY_SEEN, RECOVERY_SENT)
                out.append(json.dumps(row, ensure_ascii=False, default=str))
            tmp = ORDERS.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
            tmp.replace(ORDERS)
        if ORDER_IO.exists():
            lines = ORDER_IO.read_text(encoding="utf-8").splitlines()
            out = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    out.append(line)
                    continue
                req = row.get("request") if isinstance(row.get("request"), dict) else {}
                ticker = str(req.get("ticker") or req.get("marketSlug") or "")
                stamp = str(row.get("timestamp") or "")
                quote = None
                sent_at = ""
                if ticker == "KXATPCHALLENGERMATCH-26OCT20NAGSAN-NAG" and stamp.startswith("2026-10-20T07:37:58"):
                    quote = dict(kalshi_quote)
                    sent_at = KALSHI_SENT
                    quote["sent_at"] = sent_at
                    quote["lag_seconds"] = _lag(KALSHI_SEEN, KALSHI_SENT)
                elif ticker == "aec-atp-sumnag-alequi-2026-10-20" and stamp.startswith("2026-10-20T07:37:58"):
                    quote = dict(poly_quote)
                    sent_at = POLY_SENT
                    quote["sent_at"] = sent_at
                    quote["lag_seconds"] = _lag(POLY_SEEN, POLY_SENT)
                elif ticker == "KXATPCHALLENGERMATCH-26OCT20NAGSAN-NAG" and stamp.startswith("2026-10-20T07:37:59"):
                    quote = dict(recovery_quote)
                    sent_at = RECOVERY_SENT
                    quote["sent_at"] = sent_at
                    quote["lag_seconds"] = _lag(RECOVERY_SEEN, RECOVERY_SENT)
                if quote:
                    row["quote"] = quote
                    for key, value in quote.items():
                        row.setdefault(key, value)
                    if sent_at:
                        row["sent_at"] = sent_at
                out.append(json.dumps(row, ensure_ascii=False, default=str))
            tmp = ORDER_IO.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
            tmp.replace(ORDER_IO)


def _rows_html(rows: list[tuple[str, ...]], kinds: list[str]) -> str:
    head = "".join(_th(label, kind) for label, kind in zip(rows[0], kinds))
    body = []
    for cells in rows[1:]:
        body.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def write_page() -> Path:
    quote_table = _rows_html(
        [
            (
                "Kind", "Venue", "Side / pay", "Price", "Source", "Seen at ET",
                "Prior price", "Prior seen ET", "Move", "Notes",
            ),
            (
                "Trigger print", "Polymarket", "No / Sumit Nagal (Sanchez Yes)", "0.3400",
                "websocket", "2026-10-20 07:37:57.491", "0.3800", "2026-10-20 07:37:56.963",
                "-0.0400", "This is the quote update that made the pair qualify at net 0.95.",
            ),
            (
                "Same print (other name)", "Polymarket", "Yes / Alejo Sanchez Quilez", "0.3400",
                "websocket", "2026-10-20 07:37:57.491", "0.3800", "2026-10-20 07:37:56.963",
                "-0.0400", "Same book. Buying Nagal No is buying Sanchez Yes.",
            ),
            (
                "Prior Polymarket print", "Polymarket", "No / Sumit Nagal", "0.3800",
                "websocket", "2026-10-20 07:37:56.963", "0.4500", "2026-10-20 07:34:49.236",
                "-0.0700", "Big move 0.5s earlier. Not yet 0.34.",
            ),
            (
                "Kalshi Yes ask used", "Kalshi", "Yes / Sumit Nagal wins", "0.5900",
                "websocket ask (in-memory book)", "same compare ~07:37:57.491",
                "(not in price_memory.jsonl)", "", "",
                "yes_ask_dollars. Not the bid. Limit buy is a Kalshi bid that hits this ask.",
            ),
            (
                "Kalshi Yes bid (not used)", "Kalshi", "Yes bid", "(not stored)",
                "websocket bid field exists but is not the send price", "",
                "", "", "",
                "A bid is someone willing to buy Yes. We were the buyer. We take the ask.",
            ),
        ],
        ["text", "text", "text", "num", "text", "date", "num", "date", "num", "text"],
    )
    order_table = _rows_html(
        [
            (
                "Leg", "Venue", "Side", "Limit sent", "Quote source", "Quote price",
                "Quote seen ET", "Order sent ET", "Lag seconds", "HTTP", "Filled", "Step",
            ),
            (
                "1 simultaneous", "Kalshi", "Yes (bid / buy Yes)", "0.5900", "websocket", "0.5900",
                "2026-10-20 07:37:57.491", "2026-10-20 07:37:58.747", _lag(KALSHI_SEEN, KALSHI_SENT),
                "201", "no (fill_count 0)", "simultaneous",
            ),
            (
                "2 simultaneous", "Polymarket", "No (BUY_SHORT)", "0.660 wire / 0.340 No",
                "websocket", "0.3400",
                "2026-10-20 07:37:57.491", "2026-10-20 07:37:59.113", _lag(POLY_SEEN, POLY_SENT),
                "200", "yes at 0.6600", "simultaneous",
            ),
            (
                "3 recovery", "Kalshi", "Yes (bid / buy Yes)", "0.5900", "websocket", "0.5900",
                "2026-10-20 07:37:59.409", "2026-10-20 07:38:00.258", _lag(RECOVERY_SEEN, RECOVERY_SENT),
                "201", "no (fill_count 0)", "websocket recovery, cap 0.5900",
            ),
        ],
        ["text", "text", "text", "text", "text", "num", "date", "date", "num", "num", "text", "text"],
    )
    written = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Nagal quote trigger 2026-10-20</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Nagal 07:37:58 ET: why Kalshi was 0.59</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. Nothing on this page places an order.</p>
<div class="callout"><h2>What you asked</h2><p>{_esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{_esc(PLAIN)}</p></div>
<p class="note">Click column headers to sort. Times are America/New_York. Written {_esc(written)}.</p>
{SWIPE_NOTE_HTML}
<h2>Answer</h2>
<ul>
<li><strong>0.59 was the latest Kalshi Yes ask</strong> on the live websocket book at the compare that claimed the pair. It was not the bid.</li>
<li>A Kalshi Yes order is sent as side <code>bid</code> (limit buy). That order takes the ask. The most recent bid is the other side of the book.</li>
<li>The trigger print was Polymarket No 0.34 at 07:37:57.491 (websocket). Kalshi Yes 0.59 + Polymarket No 0.34 + the Polymarket fee is net 0.95, which is the send line.</li>
<li>Kalshi order HTTP 201 at 07:37:58.747, lag 1.255s from that quote print. Polymarket filled at 07:37:59.113, lag 1.621s. Kalshi filled nothing; recovery at the same 0.59 also filled nothing.</li>
<li>The live lock does not re-read a fresh websocket price for the first simultaneous send. It posts the candidate pays from that compare: <code>kalshi/yes@0.5900 + polymarket/no@0.340</code>.</li>
</ul>
<h2>Quotes in the seconds before the send</h2>
<p class="note">Kalshi Yes Nagal never appears in <code>price_memory.jsonl</code> for this match. The ticker <code>KXATPCHALLENGERMATCH</code> was not classified as a moneyline in the quote-history writer (it looks for GAME, not MATCH). The 0.59 still came from the in-memory Kalshi websocket field <code>yes_ask_dollars</code>. That classifier now treats MATCH as moneyline so later Kalshi tennis asks are stored.</p>
{quote_table}
<h2>Orders vs quote times</h2>
{order_table}
<h2>Code path</h2>
<p class="note">Websocket change on the Nagal worker → compare → candidate Yes Kalshi 0.59 / No Polymarket 0.34 → <code>execute_locks</code> claim → <code>_send_pair</code> simultaneous immediate-or-cancel at those quoted pays. Polymarket BUY_SHORT wires 1 − 0.34 = 0.66. Recovery uses the three-step walk (websocket, then book, then cap); this recovery stayed on websocket 0.59 because that was also the max profitable cap after the Polymarket fill.</p>
<p class="note">Sibling of the Kalshi immediate-or-cancel process page. This page is only the quote trigger and timestamps.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def _copy_g(path: Path) -> None:
    dest_dir = Path(r"G:\My Drive\paul_experiments\prediction_market_arb_exhaustive_20261017")
    if not (dest_dir.parent.exists() or Path("G:/").exists()):
        return
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest_dir / path.name)
        orders = STAMP / "orders.html"
        if orders.exists():
            shutil.copy2(orders, dest_dir / orders.name)
    except OSError:
        return


def main() -> None:
    _backfill()
    order_ledger.write_page()
    path = write_page()
    _copy_g(path)
    print(path)


if __name__ == "__main__":
    main()
