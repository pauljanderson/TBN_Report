"""Write Dos Santos vs Malla fill note. Does not place orders. Does not touch the latch."""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "dos_santos_malla_fills_20261021.html"
STATE = RAW / "strategy_b_watch.json"
ONE_LEG = RAW / "one_leg_watch.json"


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def main() -> None:
    rows = [
        {
            "time": "2026-10-21 16:37:41",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "Yes Paulo Andre Saraiva Dos Santos",
            "cash": "0.6200",
            "wire": "0.6200",
            "qty": "1.00",
            "fill": "FILL 1.00",
            "oid": "D842S72010JH",
            "fee": "0.0200",
            "source": "strategy B T0",
            "note": "BUY_LONG IOC. Final ORDER_STATE_FILLED, lastShares 1.00, avgPx 0.62. No filled row in orders.jsonl.",
        },
        {
            "time": "2026-10-21 16:37:42",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "0.3900",
            "wire": "0.6100",
            "qty": "0.62",
            "fill": "PARTIAL 0.62 then expired",
            "oid": "D842S8H010JR",
            "fee": "0.0100",
            "source": "strategy B T0",
            "note": "BUY_SHORT IOC limit 0.61 (Yes-wire). Cash = 1 − 0.61 = 0.39. cumQuantity 0.62 then ORDER_STATE_EXPIRED. Bot cancelled and treated fill_qty as 0.",
        },
        {
            "time": "2026-10-21 16:37:45",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "0.5100",
            "wire": "0.4900",
            "qty": "0.06",
            "fill": "PARTIAL 0.06 then expired",
            "oid": "D842T46G10JQ",
            "fee": "not logged",
            "source": "strategy B leftover",
            "note": "Leftover-yes ~3s after T0 miss. limit 0.49 Yes-wire; cash 1 − 0.49 = 0.51. Expired with 0.06 filled. Then cancel HTTP 200.",
        },
        {
            "time": "2026-10-21 16:37:48",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "—",
            "wire": "0.4900",
            "qty": "0",
            "fill": "MISS",
            "oid": "D842TWT010JB",
            "fee": "0",
            "source": "strategy B leftover",
            "note": "IOC expired 0/1. Cancel HTTP 200.",
        },
        {
            "time": "2026-10-21 16:37:51",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "—",
            "wire": "0.4900",
            "qty": "0",
            "fill": "MISS",
            "oid": "D842VNAG10JH",
            "fee": "0",
            "source": "strategy B leftover",
            "note": "IOC expired 0/1. Cancel HTTP 200.",
        },
        {
            "time": "2026-10-21 16:37:54",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "—",
            "wire": "0.4900",
            "qty": "0",
            "fill": "MISS",
            "oid": "D842WEBG10JB",
            "fee": "0",
            "source": "strategy B leftover",
            "note": "IOC expired 0/1. Cancel HTTP 200.",
        },
        {
            "time": "2026-10-21 16:37:57",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "—",
            "wire": "0.4900",
            "qty": "0",
            "fill": "MISS",
            "oid": "D842X71G10JR",
            "fee": "0",
            "source": "strategy B leftover",
            "note": "IOC expired 0/1. Cancel HTTP 200.",
        },
        {
            "time": "2026-10-21 16:38:00",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "—",
            "wire": "0.4900",
            "qty": "0",
            "fill": "MISS",
            "oid": "D842XZ6G10JB",
            "fee": "0",
            "source": "strategy B leftover",
            "note": "IOC expired 0/1. Cancel HTTP 200. Last leftover from pid 104872.",
        },
        {
            "time": "2026-10-21 16:38:48",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "0.5300",
            "wire": "0.4700",
            "qty": "1.00",
            "fill": "FILL 1.00",
            "oid": "D8439K0G10JE",
            "fee": "0.0200",
            "source": "strategy B leftover",
            "note": "B restarted pid 112436 at 16:38:43. BUY_SHORT limit 0.47; cash 1 − 0.47 = 0.53. ORDER_STATE_FILLED lastShares 1.00. No cancel.",
        },
        {
            "time": "2026-10-21 16:38:51",
            "venue": "Polymarket",
            "instrument": "aec-itfme-pausan-basmal-2026-10-21",
            "side": "No Santos token = Yes Bastian Malla",
            "cash": "0.5300",
            "wire": "0.4700",
            "qty": "1.00",
            "fill": "FILL 1.00",
            "oid": "D843ADG010JH",
            "fee": "0.0200",
            "source": "strategy B D=25 cross",
            "note": "Malla Yes already > 0.50 after leftover fill, so B immediately bought one more dog Yes. ORDER_STATE_FILLED lastShares 1.00.",
        },
    ]
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{esc(row['time'])} ET</td>"
            f"<td>{esc(row['venue'])}</td>"
            f"<td>{esc(row['instrument'])}</td>"
            f"<td>{esc(row['side'])}</td>"
            f"<td>{esc(row['cash'])}</td>"
            f"<td>{esc(row['wire'])}</td>"
            f"<td>{esc(row['qty'])}</td>"
            f"<td>{esc(row['fill'])}</td>"
            f"<td>{esc(row['oid'])}</td>"
            f"<td>{esc(row['fee'])}</td>"
            f"<td>{esc(row['source'])}</td>"
            f"<td>{esc(row['note'])}</td>"
            "</tr>"
        )
    head = "".join(
        [
            th("Time ET", "date"),
            th("Venue", "text"),
            th("Instrument", "text"),
            th("Side (Yes/No whose name)", "text"),
            th("Cash", "num"),
            th("Yes-wire", "num"),
            th("Qty filled", "num"),
            th("Fill vs miss", "text"),
            th("Order id", "text"),
            th("Fee", "text"),
            th("Source", "text"),
            th("Ledger note", "text"),
        ]
    )
    hold_head = "".join(
        [
            th("Ticket", "text"),
            th("Qty", "num"),
            th("Cash each", "num"),
            th("Fee logged", "text"),
            th("Cash outlay", "num"),
            th("Pays if", "text"),
        ]
    )
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    data = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    match = next(
        (row for row in (data.get("matches") or []) if "santosmalla" in str(row.get("key") or "")),
        {},
    )
    one_leg = "absent" if not ONE_LEG.exists() else "present"
    asked = (
        "we've made a bunch of purchases in this game. that's a bug. "
        "Game: Paulo Andre Saraiva Dos Santos vs. Bastian Malla."
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
{CACHE_META}
{FORCE_RELOAD_SCRIPT}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dos Santos vs Malla fills — 21 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.note {{ color: #475569; font-size: 14px; }}
ul {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Dos Santos vs Malla — every order</h1>
<p class="note">Written {esc(now)}. Research live. Not gold. Not DailyRun. Tickets from local <code>orders.jsonl</code> and <code>order_io.jsonl</code>. No new orders. Existing tickets held. Latch not cleared. Pollers not killed.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(asked)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A Yes is a ticket that pays $1 if that named tennis player wins the match. On Polymarket US this market is one Santos/Malla slug. Buying Yes is Santos wins. Buying No (BUY_SHORT) is Malla wins; cash on that No is 1 minus the Yes-wire price, same house rule as Kalshi No.</p>
<p>Strategy B (D=25) is a separate tennis bot from the Yes+No lock bot. At T0 it tries to buy Yes on both names. If one misses, it is supposed to keep buying only the missed name’s Yes. After both T0 Yes fill, if the underdog Yes later prints above 50 cents, it buys one more of that underdog, then waits to buy one more of the favorite cheap enough to lock 25 cents on that extra pair.</p>
<p><strong>What we hold:</strong> 1.00 Santos Yes and 2.68 Malla Yes, all on Polymarket slug <code>aec-itfme-pausan-basmal-2026-10-21</code>. Cash at risk about $2.0224 including logged fees (the 0.06 crumb has no fee in the response). If Santos wins we collect $1.00. If Malla wins we collect $2.68. That is not a true lock.</p>
</div>

<div class="callout warn">
<h2>Why more than two tickets</h2>
<p>This is the Goffin/Onclin leftover pattern, on Strategy B, not the lock-bot 20-second loop.</p>
<ul>
<li><strong>Lock bot did not buy this match.</strong> <code>orders_stopped.json</code> has been latched since 14:42:02 ET (“one leg filled and the other missed”). <code>leftover_watch_stats.jsonl</code> has no Santos/Malla lines. <code>one_leg_watch.json</code> is {esc(one_leg)}. job_status leftover table does not list this game. All 10 sends are <code>tennis-b</code> / Strategy B.</li>
<li><strong>T0 both-Yes:</strong> Santos Yes filled 1.00 at cash 0.62 + fee 0.02 (order D842S72010JH). Malla Yes (BUY_SHORT) only filled 0.62 of 1 at Yes-wire 0.61 (No cash 0.39) then expired (D842S8H010JR). The bot cancelled because the order still looked open, then set fill_qty to 0 — so it treated a real 0.62 fill as a miss. <code>orders.jsonl</code> has sent rows only; no filled events. Fill dropped, leftover started.</li>
<li><strong>Leftover every ~3 seconds buying the same Malla Yes</strong> (not opponent No). Six leftover IOCs from 16:37:45 to 16:38:01, then another after a B restart. The current file says leftover gap 15 seconds; the live pid 104872 fired about every 3 seconds. First leftover expired with another 0.06 fill (D842T46G10JQ). Five later leftovers missed 0/1.</li>
<li><strong>Two B processes / restarts:</strong> strategy_b.log starts pid 62620 at 16:35:32, pid 104872 at 16:37:24 (this match), pid 112436 at 16:38:43. After the third start, leftover filled a full 1.00 Malla Yes at 16:38:48 (cash 0.53), B marked T0 both complete, Malla Yes was already above 0.50, and it immediately bought the D=25 cross — a second full 1.00 Malla Yes at 16:38:51 (cash 0.53).</li>
<li><strong>Fav-dip would have been a fourth ticket.</strong> Stage was <code>waiting_fav_dip</code> at target 0.28 Santos Yes. Last quotes Santos 0.48 / Malla 0.53. That extra Santos Yes was not sent. This page set the match <code>stopped: true</code> and <code>stage: abandoned</code> in <code>strategy_b_watch.json</code> at 16:45:01 ET so the 2-second B loop will not send another IOC on this game. Latch untouched. Other B matches can still arm (max_open slot is now free).</li>
</ul>
<p>Not “two legal lock pairs both firing because the latch never set.” The latch was already on. Not lock-bot leftover buying opponent No. Bug: Strategy B leftover + a B restart + a 50-cent cross on a book that was already through 50 cents, plus partial fills zeroed after cancel.</p>
</div>

<h2>Every order (10 sends)</h2>
<p class="note">Click column headers to sort. Cash for a Polymarket No/BUY_SHORT is 1 minus the Yes-wire (ledger avgPx). Qty is max cumQuantity / lastShares from the order response, not the bot’s fill_qty after cancel.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table></div>

<h2>Hold vs cash</h2>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>{hold_head}</tr></thead>
<tbody>
<tr><td>Santos Yes D842S72010JH</td><td>1.00</td><td>0.6200</td><td>0.0200</td><td>0.6400</td><td>Santos wins</td></tr>
<tr><td>Malla Yes D842S8H010JR (T0 partial)</td><td>0.62</td><td>0.3900</td><td>0.0100</td><td>0.2518</td><td>Malla wins</td></tr>
<tr><td>Malla Yes D842T46G10JQ (leftover crumb)</td><td>0.06</td><td>0.5100</td><td>not logged</td><td>0.0306</td><td>Malla wins</td></tr>
<tr><td>Malla Yes D8439K0G10JE (leftover fill)</td><td>1.00</td><td>0.5300</td><td>0.0200</td><td>0.5500</td><td>Malla wins</td></tr>
<tr><td>Malla Yes D843ADG010JH (B cross)</td><td>1.00</td><td>0.5300</td><td>0.0200</td><td>0.5500</td><td>Malla wins</td></tr>
<tr class="total-row"><td>Total</td><td>Santos 1.00 / Malla 2.68</td><td></td><td></td><td>2.0224</td><td>not a $1 lock</td></tr>
</tbody>
</table></div>
<p>If Santos wins: collect $1.00 on 1.00 ticket (about −$1.02 vs cash out). If Malla wins: collect $2.68 on 2.68 tickets (about +$0.66). Directional extra on Malla. No flatten/sell was sent.</p>

<h2>What we changed (this game only)</h2>
<ul>
<li><code>strategy_b_watch.json</code> match <code>tennis_santosmalla_2026_10_21</code>: was <code>waiting_fav_dip</code> (would buy Santos Yes at/below 0.28). Set <code>stage: abandoned</code>, <code>stopped: true</code>, <code>stopped_at: 2026-10-21T16:45:01-04:00</code>. Note: Paul stop further buys on this match only. Existing tickets held. Latch untouched. Fav-dip IOC not sent. Currently open went 1 → 0.</li>
<li><code>one_leg_watch.json</code>: file absent. Lock leftover 20s loop was not aiming at this match. Nothing to mark stopped there.</li>
<li><code>orders_stopped.json</code>: left as-is (stopped true since 14:42:02 ET).</li>
<li>Did not rewrite <code>live_lock_orders.py</code> or Strategy B Python. Did not kill pollers. Did not flatten. Did not commit.</li>
</ul>
<p class="note">Sources: local raw <code>orders.jsonl</code> lines 3425–3434 (sent only), <code>order_io.jsonl</code> lines 3284–3308, <code>strategy_b_watch.json</code>, <code>strategy_b.log</code> (three starts: 62620 / 104872 / 112436), <code>orders_stopped.json</code>, <code>leftover_watch_stats.jsonl</code> (no hits), <code>one_leg_watch.json</code> absent, Drive <code>job_status.html</code> Strategy B block. B stage at write: {esc(match.get("stage"))}, stopped={esc(match.get("stopped"))}.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)


if __name__ == "__main__":
    main()
