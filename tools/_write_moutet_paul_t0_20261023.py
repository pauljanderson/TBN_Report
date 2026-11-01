"""Moutet vs Paul Kalshi screenshot vs venue-fill autopsy HTML. Does not place orders."""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "moutet_paul_t0_20261023.html"
NET_MAX = Decimal("0.984")

ASKED = (
    "please provide more details on the lock tape for Moutet v Paul. I want to know what "
    "orders were attempted, when and why. Every lock look from T0 (~08:00) through settlement, "
    "attempts not only fills: intended Yes player+venue+price and No player+venue+price, "
    "after-fee net vs NET_MAX 0.984, why attempted or why not sent, HTTP/fill/empty cancel, "
    "recovery/leftover/flatten. Especially the 10:47–10:51 cluster and Poly misses "
    "D988YSS011N2 and D98A8TYG11R3. Strategy B T0 ~08:00 is context only (label it B, not lock). "
    "Earlier: we had both systems trading this same game. what were the transactions for the "
    "lock bot? those to me still look weird. Match: Corentin Moutet vs Tommy Paul, "
    "Kalshi KXATPMATCH-26OCT23MOUPAU-*, 2026-10-23."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total:
        cells = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _clock(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(ET).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


def _venue(name: str | None) -> str:
    low = str(name or "").strip().lower()
    if low == "kalshi":
        return "Kalshi"
    if low == "polymarket":
        return "Polymarket US"
    if low == "novig":
        return "Novig"
    if low == "gemini":
        return "Gemini"
    return str(name or "")


def _player(side: str | None) -> str:
    text = " ".join(str(side or "").split())
    if "moutet" in text.lower():
        return "Corentin Moutet"
    if "paul" in text.lower():
        return "Tommy Paul"
    return text or "?"


def _money(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    try:
        return format(Decimal(raw), "f")
    except (InvalidOperation, ValueError):
        return raw


def _net_vs_cap(net) -> str:
    raw = _money(net)
    if raw == "—":
        return "—"
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return f"{esc(raw)} vs 0.984"
    if amount <= NET_MAX:
        return f"{esc(raw)} ≤ 0.984"
    return f"{esc(raw)} > 0.984"


def _why(row: dict, sent_n: int) -> str:
    decision = str(row.get("decision") or "")
    reason = str(row.get("reason") or "")
    net = _money(row.get("net"))
    yes_sz = _money(row.get("yes_size"))
    no_sz = _money(row.get("no_size"))
    if decision == "sent":
        extra = ""
        if sent_n == 1:
            extra = (
                " Recheck Yes Poly 0.13 + No Kalshi 0.84 + Poly fee ~0.01 = 0.98 ≤ 0.984."
            )
        elif sent_n == 2:
            extra = (
                " Recheck Yes Poly 0.82 + No Kalshi 0.11 + Poly fee ~0.01 = 0.94 ≤ 0.984."
            )
        return (
            f"Attempted: after-fee {esc(net)} was at or under the 0.984 send line after "
            f"REST book recheck. Simultaneous 1-contract IOC both legs.{extra}"
        )
    if "Strategy B" in reason:
        return (
            "Not sent: B-open skip — Strategy B still had this tennis title open "
            "(holding T0 both-Yes). Last supervisor B-open skip 10:35:36."
        )
    if "over cap after book recheck" in reason:
        return f"Not sent: claimed under the cap on the websocket quote, then REST book recheck went over $1 / over 0.984. {esc(reason)}"
    if reason.startswith("Missing size"):
        return (
            "Not sent: book — a leg had no takeable size of 1 contract "
            f"(Yes size {esc(yes_sz)}, No size {esc(no_sz)})."
        )
    if "Duplicate" in reason:
        return "Not sent: duplicate of a pair already claimed or sent on this title."
    if "above the 0.984" in reason or "above the" in reason:
        return (
            f"Not sent: after-fee {esc(net)} is above NET_MAX 0.984 "
            "(still written because it is at or under 0.99)."
        )
    return f"Not sent: {esc(reason)}"


def _sent_recovery(sent_n: int) -> tuple[str, str]:
    if sent_n == 1:
        filled = (
            "Kalshi No filled qty 1 (HTTP 201 fill_count 1.00, GET qty 1 @ 0.8400). "
            "Poly Yes miss qty 0: D988YSS011N2 HTTP 200 cumQuantity 0 then cancel HTTP 200. "
            "Kalshi 201 with fill_count 0 would not be a fill; this one was fill_count 1.00."
        )
        rec = (
            "Leftover one-leg No on Kalshi. Flatten fired: buy Yes Moutet Kalshi @ 19¢, "
            "1 IOC, HTTP 201 fill_count 1.00, GET qty 1 @ 0.1900 + fee 0.0108 = 20.08¢. "
            "Why flatten: Poly empty, do not keep a one-sided No."
        )
        return filled, rec
    if sent_n == 2:
        filled = (
            "Kalshi No filled qty 1 (HTTP 201 fill_count 1.00, GET qty 1 @ 0.1100). "
            "Poly Yes-Paul miss qty 0: D98A8TYG11R3 HTTP 200 BUY_SHORT @ 18¢ "
            "(ORDER_SIDE_SELL, cumQuantity 0) then cancel HTTP 200."
        )
        rec = (
            "Leftover one-leg No on Kalshi. Flatten fired: buy Yes Paul Kalshi @ 93¢, "
            "1 IOC, HTTP 201 fill_count 1.00, GET qty 1 @ 0.9300 + fee 0.0046 = 93.46¢. "
            "Why flatten: Poly empty, do not keep a one-sided No."
        )
        return filled, rec
    return "None", "—"


def _load_considerations() -> list[dict]:
    path = RAW / "considerations.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    rows = []
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("game") or "") != "Moutet vs Paul":
            continue
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("at") or ""))
    return rows


def _clock_override(row: dict, sent_n: int) -> str:
    reason = str(row.get("reason") or "")
    if sent_n == 1:
        return "10:47:36–10:48:22 (logged 10:48:56 after flatten)"
    if sent_n == 2:
        return "10:50:21–10:51:08 (logged 10:51:42 after flatten)"
    if "over cap after book recheck" in reason and "limit=0.88" in reason:
        return "10:45:45–10:45:46 (logged 10:45:53)"
    if "over cap after book recheck" in reason and "limit=0.9" in reason:
        return "10:49:05–10:49:06 (logged 10:49:14)"
    return _clock(row.get("at"))


def build_full_lock_tape() -> tuple[str, dict[str, int]]:
    rows = _load_considerations()
    body = []
    counts = {
        "looks": 0,
        "sent": 0,
        "denied": 0,
        "b_open": 0,
        "missing_size": 0,
        "over_cap_quote": 0,
        "over_cap_recheck": 0,
        "duplicate": 0,
        "other": 0,
    }
    sent_n = 0
    for row in rows:
        counts["looks"] += 1
        decision = str(row.get("decision") or "")
        reason = str(row.get("reason") or "")
        this_sent = 0
        if decision == "sent":
            counts["sent"] += 1
            sent_n += 1
            this_sent = sent_n
        else:
            counts["denied"] += 1
            if "Strategy B" in reason:
                counts["b_open"] += 1
            elif "over cap after book recheck" in reason:
                counts["over_cap_recheck"] += 1
            elif reason.startswith("Missing size"):
                counts["missing_size"] += 1
            elif "Duplicate" in reason:
                counts["duplicate"] += 1
            elif "above the 0.984" in reason:
                counts["over_cap_quote"] += 1
            else:
                counts["other"] += 1
        player = _player(row.get("side"))
        yes = (
            f"Yes {esc(player)} on {_venue(row.get('yes_venue'))} @ "
            f"{esc(_money(row.get('yes_price')))}"
        )
        no = (
            f"No {esc(player)} on {_venue(row.get('no_venue'))} @ "
            f"{esc(_money(row.get('no_price')))}"
        )
        if this_sent:
            sent_label = f"Sent #{this_sent}"
            filled, rec = _sent_recovery(this_sent)
        else:
            sent_label = "Not sent"
            filled = "None"
            rec = "—"
            if "10:40" <= _clock(row.get("at")) and "Strategy B" not in reason:
                rec = (
                    "Absorbed hole: last B-open skip was 10:35:36. Absorbed was not "
                    "yet in the lock skip set, so the bot kept hunting this title."
                )
        look_no = str(counts["looks"])
        if this_sent:
            look_no = f"{look_no} (sent #{this_sent})"
        body.append(
            [
                look_no,
                esc(_clock_override(row, this_sent)),
                yes,
                no,
                _net_vs_cap(row.get("net")),
                sent_label,
                _why(row, this_sent),
                filled,
                rec,
            ]
        )
    opp_note_rows = [
        [
            "opp 08:12",
            "08:12:47",
            "Yes Tommy Paul on Kalshi @ 0.76",
            "No Tommy Paul on Polymarket US @ 0.23",
            "1.00 > 0.99",
            "Not sent",
            "Not sent: after-fee 1.00 is above the 0.99 log line, so it is not a considerations row. opportunities.jsonl snapshot only.",
            "None",
            "—",
        ],
        [
            "opp 08:12",
            "08:12:47",
            "Yes Corentin Moutet on Polymarket US @ 0.23",
            "No Corentin Moutet on Kalshi @ 0.76",
            "1.00 > 0.99",
            "Not sent",
            "Not sent: after-fee 1.00 is above the 0.99 log line. Same snapshot, other settlement.",
            "None",
            "—",
        ],
        [
            "opp 08:14",
            "08:14:14",
            "Yes Tommy Paul on Polymarket US @ 0.77",
            "No Tommy Paul on Kalshi @ 0.22",
            "1.00 > 0.99",
            "Not sent",
            "Not sent: after-fee 1.00 is above the 0.99 log line. opportunities.jsonl snapshot only.",
            "None",
            "—",
        ],
        [
            "opp 08:14",
            "08:14:14",
            "Yes Corentin Moutet on Kalshi @ 0.22",
            "No Corentin Moutet on Polymarket US @ 0.77",
            "1.00 > 0.99",
            "Not sent",
            "Not sent: after-fee 1.00 is above the 0.99 log line. Same snapshot, other settlement.",
            "None",
            "—",
        ],
    ]
    full_rows = opp_note_rows + body
    html_table = table(
        [
            ("Look", "text"),
            ("Clock ET", "text"),
            ("Intended Yes", "text"),
            ("Intended No", "text"),
            ("After-fee net vs 0.984", "text"),
            ("Sent?", "text"),
            ("Why attempted / why not sent", "text"),
            ("HTTP / fill / cancel", "text"),
            ("Recovery / leftover / flatten", "text"),
        ],
        full_rows,
        [
            f"{counts['looks']} looks in 0.99 log + 4 above-0.99 snapshots",
            "08:12–10:56",
            "Same-settlement Yes",
            "Same-settlement No",
            "Send only ≤ 0.984",
            f"{counts['sent']} sent / {counts['denied']} denied",
            (
                f"B-open {counts['b_open']}; missing size {counts['missing_size']}; "
                f"quote above 0.984 {counts['over_cap_quote']}; recheck over cap "
                f"{counts['over_cap_recheck']}; duplicate {counts['duplicate']}"
            ),
            "2 Poly empty cancels; 4 Kalshi 201 fills (2 leftover + 2 flatten)",
            "Both leftovers flattened. Lock cash −10.18¢. 0 true locks.",
        ],
    )
    return html_table, counts


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    full_lock_tape, tape_counts = build_full_lock_tape()
    lock_attempts = table(
        [
            ("#", "num"),
            ("Clock ET", "text"),
            ("Intended Yes", "text"),
            ("Intended No", "text"),
            ("Claim after-fee net vs 0.984", "text"),
            ("Sent after recheck", "text"),
            ("What filled", "text"),
            ("Recovery / leftover", "text"),
        ],
        [
            [
                "0",
                "10:45:45–10:45:46",
                "Yes Tommy Paul on Kalshi (ws 16¢, recheck ask 88¢)",
                "No Tommy Paul on Polymarket (ws 13¢, recheck 16¢)",
                "Claim net 0.98 ≤ 0.984",
                "Not sent. Book recheck 0.88+0.16+0.01=1.05 over cap",
                "None",
                "Skip. Supervisor: over cap after book recheck.",
            ],
            [
                "1",
                "10:47:36–10:48:22",
                "Yes Corentin Moutet on Polymarket @ 13¢ (BUY_LONG)",
                "No Corentin Moutet on Kalshi @ 84¢ (POST ask Yes @ 16¢)",
                "Ws claim net 0.96 (Yes 11¢ + No 84¢ + Poly ~1¢). Recheck 0.13+0.84+0.01=0.98 ≤ 0.984",
                "Yes. Simultaneous 1 IOC both legs 10:47:38",
                "Kalshi No filled qty 1. Poly Yes miss qty 0 (D988YSS011N2)",
                "One-leg leftover. Flatten-first: buy Yes Moutet Kalshi @ 19¢",
            ],
            [
                "—",
                "10:49:05–10:49:06",
                "Yes Tommy Paul on Kalshi (ws 84¢, recheck 90¢)",
                "No Tommy Paul on Polymarket (ws 11¢, recheck 11¢)",
                "Claim net 0.96 ≤ 0.984",
                "Not sent. Recheck 0.90+0.11+0.01=1.02 over cap",
                "None",
                "Skip.",
            ],
            [
                "2",
                "10:50:21–10:51:08",
                "Yes Tommy Paul on Polymarket @ 82¢ (posted BUY_SHORT @ 18¢ on the Moutet-long slug)",
                "No Tommy Paul on Kalshi @ 11¢ (POST ask Yes @ 89¢)",
                "Ws claim net 0.98 (Yes 85¢ + No 12¢ + Poly ~1¢). Recheck 0.82+0.11+0.01=0.94 ≤ 0.984",
                "Yes. Simultaneous 1 IOC both legs 10:50:23",
                "Kalshi No filled qty 1. Poly Yes-Paul miss qty 0 (D98A8TYG11R3)",
                "One-leg leftover. Flatten-first: buy Yes Paul Kalshi @ 93¢",
            ],
        ],
        [
            "2 sent",
            "10:47 and 10:50",
            "Poly Yes each time",
            "Kalshi No each time",
            "Both sent nets ≤ 0.984 (Kalshi fee not in cap)",
            "Both Poly legs empty; both Kalshi legs filled",
            "0 true locks",
            "Both leftovers flattened. Lock cash −10.18¢",
        ],
    )
    lock_fills = table(
        [
            ("Attempt", "num"),
            ("Role", "text"),
            ("Venue", "text"),
            ("Ticket", "text"),
            ("HTTP", "text"),
            ("POST", "text"),
            ("Venue confirm", "text"),
            ("Qty", "num"),
            ("Yes wire", "num"),
            ("No wire", "num"),
            ("Fee", "num"),
            ("UI all-in", "num"),
            ("House cash", "num"),
            ("Order id", "text"),
            ("Fill ET", "date"),
        ],
        [
            [
                "1",
                "Lock Yes leg",
                "Polymarket US",
                "Yes Moutet BUY_LONG",
                "200",
                "limit 0.130 IOC, intent BUY_LONG, slug aec-atp-cormou-tompau-2026-10-23",
                "activities GET empty; cumQuantity 0; then cancel HTTP 200",
                "0",
                "0.13",
                "—",
                "0",
                "—",
                "0",
                "D988YSS011N2",
                "2026-10-23 10:47:38 (miss)",
            ],
            [
                "1",
                "Lock No leg",
                "Kalshi",
                "No Moutet = Sold Yes on the Moutet Yes page",
                "201",
                "side=ask, price 0.1600, tif IOC, count 1",
                "GET action=sell book_side=ask side=no yes 0.1600 no 0.8400 fee 0.0095 qty 1",
                "1",
                "0.1600",
                "0.8400",
                "0.009500",
                "0.1695",
                "+0.1505",
                "01a1693b-81f0-7f13-8ed3-0c666d9c4a7f",
                "2026-10-23 10:47:50.964",
            ],
            [
                "1",
                "Flatten leftover",
                "Kalshi",
                "Buy Yes Moutet (opposite of leftover No)",
                "201",
                "side=bid, price 0.1900, tif IOC, count 1. Flatten is unwind, not a 0.984 lock",
                "GET action=buy book_side=bid side=yes yes 0.1900 fee 0.0108 qty 1",
                "1",
                "0.1900",
                "0.8100",
                "0.010800",
                "0.2008",
                "−0.2008",
                "01a1693b-fef0-7f23-9825-977f56f0dc3f",
                "2026-10-23 10:48:22.899",
            ],
            [
                "2",
                "Lock Yes leg",
                "Polymarket US",
                "Yes Paul via BUY_SHORT @ 18¢ (1 − 0.82) on Moutet-long slug",
                "200",
                "limit 0.180 IOC, intent BUY_SHORT, ORDER_SIDE_SELL",
                "activities GET empty; cumQuantity 0; then cancel HTTP 200",
                "0",
                "0.82",
                "0.18",
                "0",
                "—",
                "0",
                "D98A8TYG11R3",
                "2026-10-23 10:50:23 (miss)",
            ],
            [
                "2",
                "Lock No leg",
                "Kalshi",
                "No Paul = Sold Yes on the Paul Yes page",
                "201",
                "side=ask, price 0.8900, tif IOC, count 1",
                "GET action=sell book_side=ask side=no yes 0.8900 no 0.1100 fee 0.0069 qty 1",
                "1",
                "0.8900",
                "0.1100",
                "0.006900",
                "0.8969",
                "+0.8831",
                "01a1693d-eb20-7327-87dd-fb8b2d9f8647",
                "2026-10-23 10:50:28.328",
            ],
            [
                "2",
                "Flatten leftover",
                "Kalshi",
                "Buy Yes Paul (opposite of leftover No)",
                "201",
                "side=bid, price 0.9300, tif IOC, count 1. Flatten is unwind, not a 0.984 lock",
                "GET action=buy book_side=bid side=yes yes 0.9300 fee 0.0046 qty 1",
                "1",
                "0.9300",
                "0.0700",
                "0.004600",
                "0.9346",
                "−0.9346",
                "01a1693e-8760-79dc-861c-e8c3d774e862",
                "2026-10-23 10:51:08.563",
            ],
        ],
        [
            "2 sent",
            "4 Kalshi fills + 2 Poly misses",
            "Kalshi + Poly",
            "No true Yes+No lock",
            "201 / 200",
            "All IOC, size 1, no GTC",
            "GET n=4 lock fills; Poly activities n=0",
            "4",
            "—",
            "—",
            "0.0318 Kalshi lock fees",
            "—",
            "−0.1018",
            "six order ids (2 empty Poly)",
            "10:47–10:51",
        ],
    )
    lock_pnl = table(
        [
            ("Step", "text"),
            ("Clock ET", "date"),
            ("What Kalshi UI shows", "text"),
            ("What it actually was", "text"),
            ("Cash", "num"),
            ("Running lock cash", "num"),
        ],
        [
            [
                "1 leftover",
                "10:47:50",
                "Sold Yes Moutet ~16¢",
                "Bought No Moutet 84¢. POST ask Yes @ 16¢. Fee 0.95¢. Receive 16−0.95=15.05¢",
                "+0.1505",
                "+0.1505",
            ],
            [
                "1 flatten",
                "10:48:22",
                "Bought Yes Moutet ~20.08¢",
                "Unwind leftover No: buy Yes 19¢ + fee 1.08¢ = 20.08¢. Limit 19¢ filled 19¢",
                "−0.2008",
                "−0.0503",
            ],
            [
                "2 leftover",
                "10:50:28",
                "Sold Yes Paul ~89.71¢",
                "Bought No Paul 11¢. POST ask Yes @ 89¢. Fee 0.69¢. Receive 89−0.69=88.31¢",
                "+0.8831",
                "+0.8328",
            ],
            [
                "2 flatten",
                "10:51:08",
                "Bought Yes Paul ~93.46¢ (screenshot dark “3.45¢” is 93.46¢)",
                "Unwind leftover No: buy Yes 93¢ + fee 0.46¢ = 93.46¢. Limit 93¢ filled 93¢",
                "−0.9346",
                "−0.1018",
            ],
        ],
        [
            "Lock bot only",
            "Paul won; leftover+flatten restored T0 Yes on both tickers",
            "Sell then buy on each Yes page",
            "Two failed locks, two flatten round-trips. Settlement $1 is T0’s, not lock’s",
            "−0.1018",
            "−10.18¢",
        ],
    )
    kalshi = table(
        [
            ("UI page", "text"),
            ("UI row (screenshot)", "text"),
            ("GET action", "text"),
            ("Ticker", "text"),
            ("Qty", "num"),
            ("Yes wire", "num"),
            ("No wire", "num"),
            ("Fee", "num"),
            ("UI all-in (yes+fee)", "num"),
            ("House cash", "num"),
            ("Limit sent", "num"),
            ("Order id", "text"),
            ("Fill ET", "date"),
            ("Which bot", "text"),
            ("Why", "text"),
        ],
        [
            [
                "Corentin Moutet Yes",
                "Bought Yes ~25.28¢, Limit ~24¢, ~8:00 AM",
                "buy / bid / Yes",
                "KXATPMATCH-26OCT23MOUPAU-MOU",
                "1",
                "0.2400",
                "0.7600",
                "0.012800",
                "0.2528",
                "−0.2528",
                "0.2400",
                "01a168a1-d230-7983-9af8-e529dc5062e4",
                "2026-10-23 07:59:58.474",
                "Strategy B T0",
                "Both-Yes open. Dog leg. strategy_b.log 08:00:15. order_io POST bid IOC. GET fill_id 0724ca08-f589-98f9-cba6-4602a0df9883.",
            ],
            [
                "Tommy Paul Yes",
                "Bought Yes ~78.24¢, ~8:00 AM",
                "buy / bid / Yes",
                "KXATPMATCH-26OCT23MOUPAU-PAU",
                "1",
                "0.7700",
                "0.2300",
                "0.012400",
                "0.7824",
                "−0.7824",
                "0.7700",
                "01a168a1-f170-763f-968f-9a0e0c6d1973",
                "2026-10-23 08:00:06.247",
                "Strategy B T0",
                "Both-Yes open. Favorite leg. strategy_b.log 08:00:22. Same GET. HTTP 201 fill_count 1.00.",
            ],
            [
                "Corentin Moutet Yes",
                "Sold Yes ~19¢ (~10:47). Venue: 16.00¢ wire / 16.95¢ all-in, Limit 16¢. Dark 16 can read as 19 next to the 20.08¢ buy.",
                "sell / ask / No",
                "KXATPMATCH-26OCT23MOUPAU-MOU",
                "1",
                "0.1600",
                "0.8400",
                "0.009500",
                "0.1695",
                "+0.1505",
                "0.1600 ask",
                "01a1693b-81f0-7f13-8ed3-0c666d9c4a7f",
                "2026-10-23 10:47:50.964",
                "Lock-bot leftover (simultaneous)",
                "Yes+No gap after B had absorbed. Kalshi No filled; Polymarket Yes D988YSS011N2 qty 0. House leftover: flatten-first, 1 IOC. GET action=sell so the Yes page shows Sold Yes.",
            ],
            [
                "Corentin Moutet Yes",
                "Bought Yes ~20¢ (~10:47). Venue: 20.08¢ all-in at 10:48:22.",
                "buy / bid / Yes",
                "KXATPMATCH-26OCT23MOUPAU-MOU",
                "1",
                "0.1900",
                "0.8100",
                "0.010800",
                "0.2008",
                "−0.2008",
                "0.1900",
                "01a1693b-fef0-7f23-9825-977f56f0dc3f",
                "2026-10-23 10:48:22.899",
                "Lock-bot flatten",
                "Unwind the leftover No: buy Yes on the same ticker, 1 contract IOC. Not a B 50-cross. orders.jsonl step=flatten, flatten_filled.",
            ],
            [
                "Tommy Paul Yes",
                "Sold Yes ~89.71¢, 10:50 AM. Venue: 89.00¢ wire / 89.69¢ all-in at 10:50:28.",
                "sell / ask / No",
                "KXATPMATCH-26OCT23MOUPAU-PAU",
                "1",
                "0.8900",
                "0.1100",
                "0.006900",
                "0.8969",
                "+0.8831",
                "0.8900 ask",
                "01a1693d-eb20-7327-87dd-fb8b2d9f8647",
                "2026-10-23 10:50:28.328",
                "Lock-bot leftover (simultaneous)",
                "Second gap on Paul. Kalshi No filled; Polymarket BUY_SHORT D98A8TYG11R3 qty 0. Same flatten-first rule. GET action=sell = Sold Yes on the Paul page.",
            ],
            [
                "Tommy Paul Yes",
                "Bought Yes ~03.45¢, 10:51 AM. Venue: 93.00¢ wire / 93.46¢ all-in. Same column as 78.24¢ = 77+1.24. The 9 is the crushed first digit.",
                "buy / bid / Yes",
                "KXATPMATCH-26OCT23MOUPAU-PAU",
                "1",
                "0.9300",
                "0.0700",
                "0.004600",
                "0.9346",
                "−0.9346",
                "0.9300",
                "01a1693e-8760-79dc-861c-e8c3d774e862",
                "2026-10-23 10:51:08.563",
                "Lock-bot flatten",
                "Unwind the leftover No Paul: buy Yes 1 IOC. POST and GET both 0.9300, not 0.03. orders.jsonl confirm_qty 1.00 @ 0.9300.",
            ],
        ],
        [
            "All 6 GET fills",
            "3 Paul + 3 Moutet",
            "4 buys, 2 sells",
            "MOU+PAU",
            "6",
            "—",
            "—",
            "0.0570",
            "—",
            "−1.1370 before $1 Paul payout",
            "—",
            "six order ids, six GET rows",
            "—",
            "B T0 ×2, lock leftover ×2, lock flatten ×2",
            "No other Kalshi print on this event.",
        ],
    )
    waterfall = table(
        [
            ("Step", "text"),
            ("Clock ET", "date"),
            ("Bot", "text"),
            ("Cash", "num"),
            ("Running", "num"),
            ("Note", "text"),
        ],
        [
            [
                "1. Buy Yes Moutet T0",
                "07:59:58",
                "Strategy B T0",
                "−0.2528",
                "−0.2528",
                "Pay 24.00¢ + 1.28¢ fee. Paul later won, so this Yes pays $0.",
            ],
            [
                "2. Buy Yes Paul T0",
                "08:00:06",
                "Strategy B T0",
                "−0.7824",
                "−1.0352",
                "Pay 77.00¢ + 1.24¢ fee. T0 both-Yes all-in $1.0352 vs $1. This is the old −3.52¢ hair — T0 only.",
            ],
            [
                "3. Sell Yes Moutet (buy No)",
                "10:47:50",
                "Lock leftover",
                "+0.1505",
                "−0.8847",
                "Receive 16.00¢, pay 0.95¢ fee. Kalshi GET action=sell. Same ticker as T0 Yes Moutet.",
            ],
            [
                "4. Buy Yes Moutet flatten",
                "10:48:22",
                "Lock flatten",
                "−0.2008",
                "−1.0855",
                "Pay 19.00¢ + 1.08¢ fee. 1-contract IOC. Unwinds the leftover No. Round-trip on Moutet −5.03¢.",
            ],
            [
                "5. Sell Yes Paul (buy No)",
                "10:50:28",
                "Lock leftover",
                "+0.8831",
                "−0.2024",
                "Receive 89.00¢, pay 0.69¢ fee. This is the 10:50 Sold Yes on the Paul screenshot — on top of the 8:00 T0 Yes.",
            ],
            [
                "6. Buy Yes Paul flatten",
                "10:51:08",
                "Lock flatten",
                "−0.9346",
                "−1.1370",
                "Pay 93.00¢ + 0.46¢ fee. Not 3.45¢. Round-trip on Paul −5.15¢.",
            ],
            [
                "7. Settlement, Paul won",
                "finalized",
                "Venue result",
                "+1.0000",
                "−0.1370",
                "GET markets: PAU result=yes, MOU result=no. Ending Yes Paul pays $1. Ending Yes Moutet pays $0.",
            ],
        ],
        [
            "All tickets, with fees, Paul won",
            "—",
            "B + lock",
            "−0.1370",
            "−13.70¢",
            "Corrects the old T0-only −3.5¢. Lock leftover+flatten added −10.18¢. Fees on all six fills: 5.70¢.",
        ],
    )
    books = table(
        [
            ("Game on the tape", "text"),
            ("Venue", "text"),
            ("Yes Moutet", "num"),
            ("Yes Paul", "num"),
            ("Wire C", "num"),
            ("Est. all-in C", "num"),
            ("Legal B pair at 08:00?", "text"),
            ("Seen ET", "date"),
        ],
        [
            [
                "Moutet vs Paul",
                "Kalshi",
                "0.24",
                "0.77",
                "1.01",
                "1.0352 (venue fees)",
                "Yes — this is the pair we sent",
                "2026-10-23 07:59:44.735 (recheck 07:59:52.530)",
            ],
            [
                "Moutet vs Paul",
                "Polymarket US",
                "0.24",
                "0.77",
                "1.01",
                "1.03 (0.01+0.01 taker, theta 0.0695)",
                "Yes, same-venue both-Yes. Not picked: C tie, Kalshi first in VENUE_ORDER.",
                "2026-10-23 07:59:44.735",
            ],
            [
                "Moutet vs Paul",
                "Novig",
                "0.24",
                "0.77",
                "1.01",
                "unknown (coefficient not on the tape)",
                "No. Novig was not a Strategy B send venue until ~08:29 ET.",
                "2026-10-23 07:59:44.735 / 07:59:47.538",
            ],
            [
                "Moutet vs Paul",
                "Gemini",
                "—",
                "—",
                "—",
                "—",
                "No market. live_jobs gemini {}.",
                "—",
            ],
        ],
    )
    poly_misses = table(
        [
            ("Time ET", "date"),
            ("Bot", "text"),
            ("Venue", "text"),
            ("Ticket", "text"),
            ("Limit", "num"),
            ("Qty filled", "num"),
            ("Order id", "text"),
            ("Filled?", "text"),
        ],
        [
            [
                "2026-10-23 10:47:38",
                "Lock simultaneous",
                "Polymarket US",
                "Yes Moutet BUY_LONG",
                "0.13",
                "0",
                "D988YSS011N2",
                "No. HTTP 200, activities GET empty, confirm_qty 0. Kalshi No filled instead → leftover.",
            ],
            [
                "2026-10-23 10:50:23",
                "Lock simultaneous",
                "Polymarket US",
                "Yes Paul via BUY_SHORT (Moutet-long slug)",
                "0.18 (= 1 − 0.82)",
                "0",
                "D98A8TYG11R3",
                "No. HTTP 200, confirm_qty 0. Intended Yes Paul at 82¢ (BUY_SHORT 18¢). Kalshi No filled instead → leftover.",
            ],
        ],
    )
    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moutet vs Paul — lock bot only — 23 Oct 2026</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Corentin Moutet vs Tommy Paul — lock bot only</h1>
<p class="note">Written {esc(now)}. Times are America/New_York (EDT, UTC−4) on 2026-10-23 unless marked UTC. Research live. Not gold. Not DailyRun. One contract. No new sells. No second Strategy B. D stays 0.25. No secrets. Strategy B T0 ~08:00 is on this page only as inventory context — those two buys are not the question.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>The lock bot tries to buy Yes of a result in one shop and No of the same result in another shop, when the two prices plus the documented fees still cost at most 98.4 cents. One of those two tickets must pay $1, so the gap is locked profit — if both fill. Strategy B’s 8:00 both-Yes buys are a different bot (labeled B below). They are not lock orders.</p>
<p>From 08:12 through 10:56 the lock bot <em>looked</em> at this match {esc(tape_counts.get("looks", 0))} times in the 0.99 log, plus four 08:12/08:14 snapshots that cost $1.00 so they never entered that log. Only two looks were actually sent (10:47 and 10:50). Polymarket came back empty both times. Kalshi filled the No leg both times. House leftover rule is flatten-first. Lock-bot cash, with fees: <strong>−10.18¢</strong>.</p>
</div>

<div class="callout warn">
<h2>Addendum — 200/201, leftover 84¢ No, GTC vs flatten</h2>
<p><strong>Poly HTTP 200 is not a fill.</strong> <code>D988YSS011N2</code> HTTP 200, cumQuantity 0, then cancel 200 is an empty Immediate-or-Cancel. Success of the HTTP call ≠ qty 1.</p>
<p><strong>Kalshi HTTP 201 is not a fail.</strong> 201 Created means the order was accepted. The fill is <code>fill_count</code>. This leftover was fill_count 1.00 No at 84¢ (UI Sold Yes 16¢). fill_count 0 on a 201 is an empty IOC — that was the old false-fill bug; it is not this row.</p>
<p><strong>Wrong economics:</strong> they did not spend 0.06¢ to exit a 13¢ Poly Yes. That 13¢ never filled. The leftover was Kalshi No 84¢. Flatten bought Yes 19¢ + 1.08¢ fee = 20.08¢. Round-trip 84+19+fees = $1.0503 → <strong>−5.03¢</strong>.</p>
<p>You would rather rest GTC on the missed Poly Yes at 13¢ than flatten. That is research-only. Historical one-leg misses, whether the missed price came back, and flatten vs hypothetical GTC dollars (with fees): <a href="one_leg_miss_gtc_vs_flatten_20261023.html">one_leg_miss_gtc_vs_flatten_20261023.html</a>. Not wired. Cancel-on-resolve still missing. D stays 0.25. NET_MAX stays 0.984.</p>
</div>

<div class="callout">
<h2>What flatten is</h2>
<p>If only one of the two lock tickets fills, you are left holding a one-sided bet — a leftover. <strong>Flatten</strong> means: close that leftover by trading the opposite on the <em>same shop</em>, immediately, 1 contract, Immediate or Cancel (not Good Till Cancel). Flatten is an unwind. It does not wait for the 98.4-cent lock cap.</p>
<p>On Kalshi there is no separate “buy No” button on the Yes page. Buying No is posted as selling Yes, so the Yes page prints Sold Yes. That leftover is a No. Flatten then buys Yes on that same ticker to cancel it out. In one line: leftover one-leg → close it by trading the opposite on the same shop; Kalshi buy No = Sold Yes.</p>
</div>

<div class="callout warn">
<h2>Lock bot cash is −10.18¢. The sell-then-buy rows are leftover then flatten</h2>
<ul>
<li><strong>Attempt 1, Moutet:</strong> wanted Yes Moutet on Polymarket at 13¢ + No Moutet on Kalshi at 84¢ (after-fee 0.98 vs cap 0.984). Poly miss <code>D988YSS011N2</code>. Kalshi filled No. Flatten bought Yes Moutet at 19¢ + 1.08¢ fee = 20.08¢. Round-trip <strong>−5.03¢</strong>.</li>
<li><strong>Attempt 2, Paul:</strong> wanted Yes Paul on Polymarket at 82¢ + No Paul on Kalshi at 11¢ (after-fee 0.94 vs cap 0.984). Poly miss <code>D98A8TYG11R3</code>. Kalshi filled No. Flatten bought Yes Paul at 93¢ + 0.46¢ fee = 93.46¢. The dark “3.45¢” is this 93.46¢. Round-trip <strong>−5.15¢</strong>.</li>
<li><strong>Why Sold Yes then Bought Yes:</strong> Kalshi has no separate “buy No” button on the Yes page. Buying No is an ask on the Yes book (sell Yes at 1 − No). GET <code>action=sell</code>. Flatten then buys Yes to unwind that leftover No. Kalshi nets one position per ticker, so it sits on top of the 8:00 T0 Yes as sell then buy.</li>
<li><strong>Why lock was allowed after B absorbed:</strong> lock skip for an open B match only covered waiting_t0 / waiting_cross / waiting_fav_dip / one_leg_miss. Absorbed was not on that list. Last B-open skip 10:35:36. By 10:40 the lock bot was hunting the same title while B still held T0 both-Yes. This job added <code>absorbed</code> to that skip set so it does not repeat.</li>
</ul>
</div>

<h2>Full lock tape — every look, not only fills</h2>
<p class="note">Click column headers to sort. Strategy B T0 at 08:00 is <strong>not</strong> in this table — that is B, labeled later. Looks with after-fee above 0.99 are left off the considerations log by design; the four 08:12/08:14 <code>opportunities.jsonl</code> snapshots at $1.00 are included at the top so T0→settlement is not a hole. The 500-row considerations window’s first Moutet vs Paul row is 08:19:59. Last look 10:56:06 (match then settled). Last B-open skip 10:35:36; after that absorbed was still holding T0, but absorbed was not yet in the lock skip set. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{full_lock_tape}

<h2>10:47–10:51 cluster (the two sends + two recheck skips)</h2>
<p class="note">Click column headers to sort. This is the same cluster as the Kalshi Sold-then-Bought screenshots. Cap treats Kalshi fee as 0 and only adds the Polymarket taker fee. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{lock_attempts}

<h2>Each sent leg: HTTP + venue confirm</h2>
<p class="note">Fresh Kalshi GET /trade-api/v2/portfolio/fills HTTP 200 this job. Polymarket GET /v1/portfolio/activities HTTP 200, activities=[], eof. Gemini and Novig: 0 fills on this match. A Kalshi HTTP 201 with fill_count 0 is not a fill; both leftover Kalshi POSTs here were fill_count 1.00. Poly HTTP 200 with cumQuantity 0 is an empty IOC, then cancel HTTP 200.</p>
{SWIPE_NOTE_HTML}
{lock_fills}

<h2>10:47–10:51, second by second</h2>
<ol>
<li><strong>10:45:45–10:45:46 — Look, not sent.</strong> Websocket claimed Yes Paul Kalshi 16¢ + No Paul Poly 13¢, net 0.98. REST recheck Yes ask 88¢ + No 16¢ + Poly fee 1¢ = 1.05 over cap. Supervisor: over cap after book recheck. No HTTP.</li>
<li><strong>10:47:36 claim / 10:47:38 send — Attempt 1, Moutet.</strong> Intended Yes Moutet Polymarket @ 13¢ + No Moutet Kalshi @ 84¢. Recheck 0.13+0.84+0.01=0.98 ≤ 0.984. Why attempted: under the send line after book recheck. Simultaneous 1 IOC.</li>
<li><strong>10:47:38–10:48:00 — Poly miss D988YSS011N2.</strong> POST BUY_LONG limit 0.130, tif IOC, HTTP 200, cumQuantity 0, leavesQuantity 1. Activities GET empty. Cancel HTTP 200 at 10:48:00. Empty cancel — not a fill.</li>
<li><strong>10:47:38–10:47:50 — Kalshi leftover fill.</strong> POST ask Yes @ 16¢ (buy No @ 84¢), tif IOC, HTTP 201 fill_count 1.00. GET action=sell book_side=ask side=no yes 0.1600 no 0.8400 fee 0.0095 qty 1. This is a fill.</li>
<li><strong>10:48:16–10:48:22 — Flatten 1.</strong> Why: one-leg leftover No. Buy Yes Moutet Kalshi @ 19¢, 1 IOC, not a 0.984 lock. HTTP 201 fill_count 1.00. GET buy yes 0.1900 fee 0.0108 qty 1. Flatten filled. Supervisor 10:48:56: flattened one-leg.</li>
<li><strong>10:49:05–10:49:06 — Look, not sent.</strong> Claimed Yes Paul Kalshi 84¢ + No Paul Poly 11¢, net 0.96. Recheck 0.90+0.11+0.01=1.02 over cap. No HTTP.</li>
<li><strong>10:50:21 claim / 10:50:23 send — Attempt 2, Paul.</strong> Intended Yes Paul Polymarket @ 82¢ + No Paul Kalshi @ 11¢. Recheck 0.82+0.11+0.01=0.94 ≤ 0.984. Why attempted: under the send line. Simultaneous 1 IOC.</li>
<li><strong>10:50:23–10:50:53 — Poly miss D98A8TYG11R3.</strong> Posted BUY_SHORT @ 18¢ (1 − 0.82) on the Moutet-long slug, ORDER_SIDE_SELL, HTTP 200, cumQuantity 0. Activities GET empty. Cancel HTTP 200 at 10:50:53. Empty cancel — not a fill.</li>
<li><strong>10:50:23–10:50:28 — Kalshi leftover fill.</strong> POST ask Yes Paul @ 89¢ (buy No @ 11¢), HTTP 201 fill_count 1.00. GET action=sell yes 0.8900 no 0.1100 fee 0.0069 qty 1.</li>
<li><strong>10:51:02–10:51:08 — Flatten 2.</strong> Why: one-leg leftover No. Buy Yes Paul Kalshi @ 93¢, 1 IOC. HTTP 201 fill_count 1.00. GET buy yes 0.9300 fee 0.0046 qty 1. Supervisor 10:51:42: flattened one-leg.</li>
<li><strong>10:54:43 — Duplicate, not sent.</strong> Yes Moutet Poly 4¢ + No Moutet Kalshi 94¢, net 0.98. Denied duplicate. No HTTP.</li>
</ol>

<h2>Why the flatten prices look weird</h2>
<ol>
<li><strong>Moutet 10:47 sell ~16¢ Yes (No 84¢) then buy Yes 20.08¢.</strong> Intended No cost was 84¢. Kalshi posts that as ask Yes at 16¢, so the Yes page prints Sold Yes 16¢. Poly’s Yes at 13¢ never filled, so we were holding only No Moutet. Flatten does not wait for a 0.984 gap — it buys the opposite at the live ask, 1 IOC. Book ask Yes was 19¢; GET fill 19¢ + fee 1.08¢ = 20.08¢. No 84¢ + Yes 19¢ + fees 2.03¢ = $1.0503 for a $1 pair.</li>
<li><strong>Paul 10:50 sell ~89¢ Yes (No 11¢) then buy Yes 93.46¢.</strong> Same pattern on the favorite. Intended No cost 11¢ posts as ask Yes at 89¢. Screenshot ~89.71¢ is 89¢ + 0.69¢ fee in Kalshi’s “Avg. px fee” column (same column as T0 78.24¢ = 77+1.24). Poly’s Yes Paul at 82¢ was sent as BUY_SHORT 18¢ on the Moutet-long slug (1 − 0.82) and missed. Flatten bought Yes at the live 93¢ ask + 0.46¢ fee = 93.46¢. The crushed first digit is 9, not 0. No 11¢ + Yes 93¢ + fees 1.15¢ = $1.0515 for a $1 pair.</li>
<li><strong>Two Poly IOC misses.</strong> <code>D988YSS011N2</code> is attempt 1’s Yes Moutet BUY_LONG @ 13¢. <code>D98A8TYG11R3</code> is attempt 2’s Yes Paul (BUY_SHORT @ 18¢ / quote 82¢). Both HTTP 200, cumQuantity 0, activities GET empty, then cancel HTTP 200. Those are the missing other legs, not extra Kalshi trades.</li>
</ol>

<h2>Lock-bot cash waterfall (T0 inventory restored; $1 payout is T0’s)</h2>
<p class="note">Leftover sell then flatten buy returns each ticker to +1 Yes, which is also what T0 opened. So lock P&amp;L does not depend on who won. Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{lock_pnl}

<div class="callout ok">
<h2>Skip-absorbed is now in live_lock_orders</h2>
<p>One line: <code>absorbed</code> is in <code>_STRATEGY_B_OPEN</code>, so <code>strategy_b_blocks_lock</code> skips the same tennis title after B marks absorbed (still holding T0). Test: <code>test_lock_bot_skip_absorbed_b</code>. D stays 0.25. No second B. No GTC. Did not sell more.</p>
</div>

<div class="callout">
<h2>Strategy B T0 (not the question — those two buys are the 8:00 rows)</h2>
<p>Yes Moutet 24¢ + 1.28¢ fee = 25.28¢. Yes Paul 77¢ + 1.24¢ fee = 78.24¢. Combined all-in $1.0352. Paul won, T0 alone −3.52¢. All six Kalshi tickets together −13.70¢ = T0 −3.52¢ + lock −10.18¢. B did not send again after T0. Watch: absorbed before 50c cross; holding T0 both-Yes.</p>
</div>

<div class="callout warn">
<h2>Earlier page note (all six Kalshi prints)</h2>
<ul>
<li><strong>T0 is still too expensive versus $1:</strong> Yes Moutet 24¢ + 1.28¢ fee = 25.28¢. Yes Paul 77¢ + 1.24¢ fee = 78.24¢. Combined all-in $1.0352. Paul won, T0 alone would be <strong>−3.52¢</strong>. That part of the old page was right, and it is not the full P&amp;L.</li>
<li><strong>Your two screenshots are the other four prints:</strong> 10:47 Sold Yes Moutet then Bought Yes Moutet, 10:50 Sold Yes Paul then 10:51 Bought Yes Paul. Those are lock-bot leftover then flatten, not a Strategy B 50-cross, not a second B.</li>
<li><strong>The 10:51 “~03.45¢” buy is 93.46¢ all-in.</strong> Fresh GET 2026-10-23 ~{esc(now)}: ticker PAU, action=buy, book_side=bid, yes_price 0.9300, fee 0.004600. Kalshi’s “Avg. px fee” column is wire plus fee — the same column that shows T0 Paul as 78.24¢ (77+1.24) and T0 Moutet as 25.28¢ (24+1.28). The crushed screenshot’s first digit is a 9, not a 0. POST <code>average_fill_price</code> 0.9300 matches GET.</li>
<li><strong>The ~19¢ Moutet sell is 16.00¢ wire / 16.95¢ all-in</strong> at 10:47:50 (Limit 16¢, GET action=sell). The ~20¢ buy is 19.00¢ + 1.08¢ = 20.08¢ at 10:48:22. Those two sit next to each other on the Moutet Yes page.</li>
<li><strong>Corrected cash, Paul won:</strong> T0 −3.52¢, plus Moutet leftover+flatten −5.03¢, plus Paul leftover+flatten −5.15¢ = <strong>−13.70¢</strong>. Fees on all six fills: 5.70¢. Markets GET: PAU <code>result=yes</code>, MOU <code>result=no</code>, both finalized.</li>
</ul>
</div>

<h2>Every Kalshi order on both sides</h2>
<p class="note">Click column headers to sort. Six GET fills, HTTP 200, n=6, no extras on this event. UI all-in is Yes wire plus GET <code>fee_cost</code> — that is the Kalshi Order history “Avg. px fee” number (25.28, 78.24, 20.08, 93.46). House cash for a buy is −(wire+fee); for a sell it is +(Yes wire−fee). Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{kalshi}

<h2>Plain English chronology of the six prints</h2>
<ol>
<li><strong>07:59:58 ET — Strategy B T0, buy Yes Moutet 24¢.</strong> Trusted start 08:00. Rechecked book 07:59:52.530: Yes asks 0.24 / 0.77, C=1.01, inside the 95¢–$1.20 band. IOC bid. GET buy. Screenshot: Bought Yes 25.28¢, Limit 24¢.</li>
<li><strong>08:00:06 ET — Strategy B T0, buy Yes Paul 77¢.</strong> Same send. GET buy. Screenshot: Bought Yes 78.24¢. B then waited for Moutet (the T0 dog) to print strictly above 50¢. Max on the tape was 44¢ at 09:57. Watch note: “absorbed before 50c cross; holding T0 both-Yes.” B did not send again. D stayed 0.25. No second B.</li>
<li><strong>10:47:38–10:47:50 ET — lock-bot leftover, sell Yes Moutet 16¢.</strong> Lock skip for an open B match did not include absorbed, so after B gave up on the 50-cross the lock bot hunted a Yes+No gap on the same title. It sent Kalshi No (POST ask Yes @ 16¢) and Polymarket Yes @ 13¢ together. Poly came back empty (<code>D988YSS011N2</code>). Kalshi GET: action=sell, side=no, yes_price 0.1600, no_price 0.8400. Screenshot: Sold Yes on the Moutet page.</li>
<li><strong>10:48:16–10:48:22 ET — lock-bot flatten, buy Yes Moutet 19¢.</strong> House leftover: do not keep a one-legged No. Flatten-first, 1 contract IOC, opposite side, same ticker. GET buy yes 0.1900 + fee 0.0108 = 20.08¢. Screenshot: Bought Yes ~20¢. This is not a B favorite-dip or 50-cross.</li>
<li><strong>10:50:23–10:50:28 ET — lock-bot leftover, sell Yes Paul 89¢.</strong> Second gap, now on Paul. Kalshi No filled (POST ask Yes @ 89¢); Polymarket Yes Paul missed (<code>D98A8TYG11R3</code> BUY_SHORT @ 18¢ = quote 82¢). GET action=sell, yes_price 0.8900, fee 0.0069. Screenshot: Sold Yes ~89.71¢ at 10:50. That sell sits on the same Yes Paul market as the 8:00 T0 buy.</li>
<li><strong>10:51:02–10:51:08 ET — lock-bot flatten, buy Yes Paul 93¢.</strong> Same flatten-first 1 IOC. GET buy yes 0.9300 + fee 0.0046 = 93.46¢. Screenshot time 10:51 matches. The dark “~03.45¢” is this row’s 93.46¢ with the 9 crushed. Match settled. Paul won.</li>
</ol>
<p>Gemini and Novig: zero fills on this match. Polymarket activities GET: zero trades. Only the two Poly IOC misses above.</p>

<h2>Full with-fee cash waterfall (Paul won)</h2>
<p class="note">Running column starts at $0. Settlement is GET markets, not a tape guess. Kalshi nets one signed position per ticker; leftover sell then flatten buy returns each ticker to +1 Yes, which is also the inventory T0 opened.</p>
{SWIPE_NOTE_HTML}
{waterfall}

<h2>Why leftover+flatten costs ~5¢ per name</h2>
<p>Each lock attempt wanted a Yes+No pair under the 0.984 cap. One leg filled, so flatten bought the other side at the live ask, 1 IOC, without that cap (flatten is an unwind, not a new lock). Moutet: No at 84¢ + Yes at 19¢ + 2.03¢ fees = $1.0503 for a $1 pair (−5.03¢). Paul: No at 11¢ + Yes at 93¢ + 1.15¢ fees = $1.0515 for a $1 pair (−5.15¢). Those two pairs sit on top of T0’s already-expensive both-Yes. That is why the screenshots show a 10:47 buy+sell and a 10:50 sell + 10:51 buy on the same Yes pages as the 8:00 rows.</p>

<h2>Yes books at the T0 second</h2>
<p class="note">Trusted clock 08:00:00 ET. Book recheck 07:59:52.530 ET. B may only send a same-venue both-Yes pair. C band is on Yes asks, not all-in.</p>
{SWIPE_NOTE_HTML}
{books}

<h2>Polymarket misses (not on the Kalshi screenshots)</h2>
{SWIPE_NOTE_HTML}
{poly_misses}

<h2>What the old page got wrong</h2>
<ul>
<li>It treated lock leftover/flatten as a footnote and left the headline P&amp;L at T0 −3.5¢. The screenshots are those four later Kalshi rows. All-in book is −13.70¢.</li>
<li>It labeled leftover as “No Moutet / No Paul” without mapping GET <code>action=sell</code> to the Yes Order history Sold Yes rows you actually pasted.</li>
<li>It did not say that the 10:51 Paul flatten is 93.46¢ all-in, so a crushed 93.45¢ could be read as 03.45¢.</li>
</ul>
<p>T0 itself was still a legal B send. 0.24 and 0.77 are inside (0.10, 0.90) and C=1.01 is inside [0.95, 1.20]. Fees are not subtracted from C. Watch stored <code>fill_fee 0</code>; POST and GET both have the fees. Moutet never printed above 50¢, so there was no 50-cross and no favorite dip. Not the Trungelliti BUY_SHORT invert.</p>

<h2>Agree or not</h2>
<p>The lock-bot rows look weird because Kalshi prints a buy-No as Sold Yes, then flatten buys Yes back. They are not a second Strategy B. Two sent attempts, both one-leg, both flattened. Lock-bot P&amp;L <strong>−10.18¢</strong>. Whole book after Paul won is still −13.70¢ (T0 −3.52¢ + lock −10.18¢).</p>
<p class="note">Sources: considerations.json 34 Moutet vs Paul rows (32 denied, 2 sent) in the 500-row window 08:19:59–10:56:06; opportunities.jsonl four 08:12/08:14 net 1.00 snapshots; Kalshi GET /trade-api/v2/portfolio/fills HTTP 200 n=6 (action/book_side/side/fees); Polymarket US GET /v1/portfolio/activities HTTP 200 activities=[] eof; order_io.jsonl POSTs (ask 0.16 / bid 0.19 / ask 0.89 / bid 0.93; Poly BUY_LONG D988YSS011N2 cancel HTTP 200, BUY_SHORT D98A8TYG11R3 cancel HTTP 200); orders.jsonl claim/sent/flatten/skip; live_supervisor.log simultaneous send + last B-open skip 10:35:36 + duplicate 10:54:43; strategy_b_watch.json stage absorbed. Pulled {esc(now)}. Skip-absorbed already in live_lock_orders (test_lock_bot_skip_absorbed_b). No second Strategy B. D=0.25. No GTC. No secrets. Did not sell. Did not touch fernandez_alexandrova_20261023.html.</p>

{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html_out, encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
