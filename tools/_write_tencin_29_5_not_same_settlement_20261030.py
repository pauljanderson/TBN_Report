"""TEN vs CIN 29.5 Type A gap lock: team total vs game total. Display only."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_lock_orders
import opportunity_considerations as oc
from report_page_extras import (
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
)
from write_orders_performance import table

ET = ZoneInfo("America/New_York")
STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "tencin_29_5_not_same_settlement_20261030.html"
RAW = Path("local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw")
ORDERS = RAW / "orders.jsonl"

PAUL = (
    "thanks. i'll look at that next. help me understand the gap lock execution we have here"
)

KALSHI_TICKER = "KXNFLTEAMTOTAL-26NOV01TENCIN-CIN30"
GAME_TOTAL_TICKER = "KXNFLTOTAL-26NOV01TENCIN-30"
NOVIG_MARKET = "01a178fd-2f52-71a3-93b5-4c671fd27ff8"
NOVIG_ORDER = "aia702035792"


def money4(value) -> str:
    return format(Decimal(str(value)), "f")


def load_sents() -> list[dict]:
    out: list[dict] = []
    with ORDERS.open(encoding="utf-8") as handle:
        for line in handle:
            if KALSHI_TICKER not in line and NOVIG_MARKET not in line:
                continue
            row = json.loads(line)
            if row.get("event") != "sent":
                continue
            out.append(row)
    return out


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    sents = load_sents()
    kalshi = next(r for r in sents if r.get("venue") == "kalshi")
    novig = next(r for r in sents if r.get("venue") == "novig")
    cap = live_lock_orders.effective_net_max()
    pair = Decimal(str(kalshi["after_fee"])) + Decimal(str(novig["after_fee"]))
    consider = {
        "at": "2026-10-30T18:19:58.980-04:00",
        "sport": "pro football",
        "game": "Tennessee vs Cincinnati Pro Football",
        "market_type": "total",
        "side": "Cincinnati over 29.5 points scored",
        "number": "29.5",
        "yes_venue": "kalshi",
        "no_venue": "novig",
        "yes_price": "0.5300",
        "no_price": "0.090",
        "yes_size": "2",
        "no_size": "966.64",
        "net": "0.6375",
        "decision": "sent",
        "source": "websocket",
        "reason": (
            "Type A sequential hard-first. Both legs filled. Holding both. "
            f"kalshi HTTP 201 fill 1.00 fill_count 1.00 confirm {kalshi.get('confirm_note')}. "
            f"novig HTTP 201 fill 1.00 FILLED confirm {novig.get('confirm_note')}."
        ),
        "venue_return": (
            f"kalshi HTTP 201 fill 1.00 fill_count 1.00 confirm {kalshi.get('confirm_note')}. "
            f"novig HTTP 201 fill 1.00 FILLED confirm {novig.get('confirm_note')}."
        ),
        "hold_now": "both",
        "filled_venues": "kalshi novig",
    }
    headers = "".join(oc._th(label, kind) for label, kind in oc.TABLE_HEADERS)
    consider_table = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + headers
        + "</tr></thead><tbody>"
        + oc._cells(consider, sents)
        + "</tbody></table></div>"
    )
    identity = table(
        [
            ("Contract", "text"),
            ("Platform", "text"),
            ("Ticker / market", "text"),
            ("Official settle rule", "text"),
            ("Ask at send", "num"),
            ("Same $1 as the other leg?", "text"),
        ],
        [
            [
                "Bengals team total Over 29.5",
                "Kalshi",
                KALSHI_TICKER,
                "If Cincinnati scores over 29.5 points, Yes.",
                "0.5300",
                "No — one team's points",
            ],
            [
                "Game total Over 29.5 (full game)",
                "Kalshi (not bought)",
                GAME_TOTAL_TICKER,
                "If Tennessee and Cincinnati collectively score more than 29.5, Yes.",
                "0.9300 Yes / 0.0900 No",
                "This is the Novig 9¢ twin, not the Kalshi ticket we hold",
            ],
            [
                "Under 29.5 (screenshot: TEN vs CIN, no team name)",
                "Novig",
                NOVIG_MARKET,
                "Novig UI Under 29.5 at 11.1x ($0.09 to pay $1). Price matches Kalshi full-game No, not Bengals team-total No (49¢).",
                "0.0900",
                "No — combined points",
            ],
        ],
    )
    cash = table(
        [
            ("Leg", "text"),
            ("UI", "text"),
            ("House wire", "num"),
            ("Fee", "num"),
            ("After-fee cash", "num"),
            ("Confirm qty", "num"),
        ],
        [
            [
                "Kalshi Yes Bengals Over 29.5",
                "Bought Yes 54.75¢ · Cost $0.55 · Fees $0.02 · Limit 53¢ Taker",
                "0.5300",
                "0.0175",
                "0.5475",
                "1",
            ],
            [
                "Novig Under 29.5",
                "Amount $0.09 · To pay $1.00 · 11.1x · MATCHED · " + NOVIG_ORDER,
                "0.0900",
                "0.0000",
                "0.0900",
                "1",
            ],
        ],
        [
            "Pair",
            f"after-fee {money4(pair)} vs live NET_MAX {money4(cap)} (Paul 0.99 band also under)",
            "",
            "0.0175",
            money4(pair),
            "2",
        ],
    )
    payout = table(
        [
            ("Sunday result", "text"),
            ("Kalshi Bengals Over 29.5", "text"),
            ("Novig game Under 29.5", "text"),
            ("Cash back", "num"),
            ("PnL vs $0.6375 spent", "num"),
        ],
        [
            [
                "Bengals score 30+ (game total then at least 30)",
                "Pays $1",
                "Loses (game cannot be under 29.5)",
                "1.0000",
                "+0.3625",
            ],
            [
                "Combined points under 29.5 (both teams quiet)",
                "Loses",
                "Pays $1",
                "1.0000",
                "+0.3625",
            ],
            [
                "Bengals 29 or fewer AND game 29.5+ (normal NFL score, e.g. 24–21)",
                "Loses",
                "Loses",
                "0.0000",
                "−0.6375",
            ],
        ],
    )
    exec_rows = table(
        [
            ("Step", "text"),
            ("When ET", "date"),
            ("What", "text"),
        ],
        [
            ["Trigger", "2026-10-30 18:19:48 ET", "Kalshi websocket Yes 0.5300 + Novig No 0.090 (sizes 2 vs 966.64)"],
            ["REST recheck both books", "2026-10-30 18:19:48 ET", "Kalshi Yes still 0.5300 size 2; Novig No still 0.090 size 966.64; after-fee still under cap"],
            ["Hard first", "2026-10-30 18:19:50.601 ET", "Kalshi IOC Yes 1 @ 0.5300 HTTP 201 fill 1.00 (thin ask was Kalshi)"],
            ["Easy recheck then send", "2026-10-30 18:19:52.786 ET", "Novig REST book still 0.090 size 966.64; IOC No 1 HTTP 201 FILLED confirm qty 1.00"],
            ["Flatten?", "—", "None. Both filled. Holding both. Did not sell."],
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>TEN vs CIN 29.5 — not the same $1</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.ok {{ background: #ecfdf3; border: 1px solid #86efac; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
.loud {{ background: #fef2f2; border: 2px solid #dc2626; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
.swipe-note {{ color: #555; font-size: 0.95em; }}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>TEN vs CIN 29.5 — not the same $1 question</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}.
Did not commit. Did not start a second B. Did not leftover-GTC on A. Did not retune.
Did not DailyRun. Did not sell.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: “{oc._esc(PAUL)}”</p>
<p>Screenshots: Kalshi TEN Titans vs CIN Bengals Team Total, CIN Bengals over 29.5,
Bought Yes 54.75¢, 1 contract, $0.55, $0.02 fee, Limit 53¢ Taker, Oct 30 18:19:49 ET.
Novig TEN vs CIN Sunday 1:00 PM, Under 29.5 11.1x, $0.09 to pay $1.00, MATCHED,
id {NOVIG_ORDER}, placed 6:19 PM. Same $1? Execution? House cash? Why they look unrelated?</p>
<h2>In plain English</h2>
<p>We bought <strong>two different football questions</strong> that happen to share the
number 29.5. Kalshi pays $1 if the <em>Bengals</em> score 30 or more. Novig pays $1 if
the <em>whole game</em> stays under 29.5 combined points. Those are not Yes and No of
one contract, so this is not a lock. Both tickets filled. We are holding both. Did not
sell.</p>
</div>

<div class="loud">
<p><strong>Same-settlement: no.</strong> Not a lock. Kalshi ticker is
<code>{KALSHI_TICKER}</code> (team total). Kalshi’s own full-game 29.5 is a different
contract, <code>{GAME_TOTAL_TICKER}</code>, whose No is 9¢ — that is the price twin of
the Novig Under 29.5, not the 53¢ Bengals ticket we bought.</p>
</div>

<h2>Two-leg tape (opportunities consideration columns)</h2>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>
{consider_table}

<h2>Settlement identity</h2>
{identity}

<h2>House cash vs the two websites</h2>
{cash}
<p>Kalshi UI 54.75¢ is house after-fee: 53¢ wire + 1.75¢ taker fee
(0.07 × 0.53 × 0.47 ≈ 0.0174, venue billed 0.0175). Cost $0.55 and fee $0.02 are the
same dollars rounded to a cent. Novig 11.1x is 1 / 0.09. Pair after-fee
<strong>{money4(pair)}</strong>, under live NET_MAX {money4(cap)} and under 0.99.
1 contract each.</p>

<h2>If Over vs Under “wins”</h2>
{payout}
<p>If these were the same $1, one side would always pay $1 and we would keep about
36¢. Because they are not, a normal NFL score (Bengals under 30, game over 29.5) loses
both tickets. Bengals 30+ cannot also be a game under 29.5, so both tickets never pay
together.</p>

<h2>Type A execution</h2>
{exec_rows}
<p>Hard/thin-first was Kalshi (displayed ask size 2 vs Novig 966.64). Sequential: Kalshi
first HTTP 201, then Novig REST recheck, then Novig HTTP 201. Second leg filled. No
flatten. Kitchen still open: Yes (Over) Cincinnati Bengals on Kalshi, No Cincinnati over
29.5 on Novig. Kalshi positions pull still shows qty 1 on <code>{KALSHI_TICKER}</code>.</p>

<h2>Why the two websites look unrelated</h2>
<ul>
<li>Kalshi sells <strong>Yes</strong> on a named team-total ticker. Novig sells
<strong>Under</strong> as a decimal price 11.1x. Same 9¢ cash, different shop language.</li>
<li>The matcher read Kalshi’s title “Cincinnati over 29.5 points scored”, treated the
word “over 29.5” as a <em>game</em> total, and paired it with Novig’s full-game Under
29.5. Team vs game was dropped. That is why a 53¢ coin-flip sat next to a 9¢ longshot
and still printed under $1.</li>
<li>You are looking at two real filled tickets. They are just not two sides of one
question.</li>
</ul>

<p>Did not sell. Did not flatten. Holding both until Sunday settles.</p>
<p>Manual: <code>python tools/_write_tencin_29_5_not_same_settlement_20261030.py</code>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
