"""Verify Polymarket price/result fix. No live orders besides one lock reload. No commit."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report_page_extras import (  # noqa: E402
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
)
from write_orders_performance import table  # noqa: E402

STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "poly_price_result_status_20261028.html"
ET = ZoneInfo("America/New_York")
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/poly_price_result_status_20261028.html"
)


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    three = table(
        [
            ("Line", "text"),
            ("Y/N", "text"),
            ("What we verified", "text"),
        ],
        [
            [
                "Historical book recoded",
                "Y",
                "Dashboard + cache Shimizu/Hsu is Hsu won, T0 −$0.48 / +$0.44 / cross −$0.62, game −$0.66. Old kitchen +0.52 / −0.46 / +0.38 is gone. 87 settled Poly games: 0 with two Yes winners.",
            ],
            [
                "Live new-fill path",
                "Y in files; lock reloaded this job; B already on it; C/D/E not",
                "BUY_SHORT persist uses poly_house_cash (spread/debit) not Yes-wire. confirm_order stamps house_cash. Settlement prefers settlementPx, not ticker result=yes. B pid 74812 started 14:46 after those files — left running (one B, four open). Lock supervisor 38656 (26 Oct) → 60888 at 15:18:46; 104 new pollers. Did not start a second B.",
            ],
            [
                "Still open",
                "Y — listed, not retuned",
                "GTC dip not wired (still IOC). C pid 3064 / D 62576 (26 Oct) and E 38620 (09:36 today) still pre-fix. leftover GTC not asked. this_order_cum_qty still reads avgPx when activities GET is empty; attach_house_cash overwrites on current files.",
            ],
        ],
    )
    cells = table(
        [
            ("When ET", "date"),
            ("Type", "text"),
            ("Side", "text"),
            ("Wire", "num"),
            ("Fee", "num"),
            ("After-fee", "num"),
            ("Outcome", "text"),
            ("P&L if settled", "num"),
        ],
        [
            ["2026-10-28 00:27:00 ET", "crossover lock", "Yes Yuta Shimizu", "0.6000", "0.0200", "0.6200", "settled loss", "−$0.62"],
            ["2026-10-28 00:01:02 ET", "initial Hi lock", "Yes Yu-Hsiou Hsu", "0.5500", "0.0100", "0.5600", "settled win", "+$0.44"],
            ["2026-10-28 00:01:02 ET", "initial low lock", "Yes Yuta Shimizu", "0.4600", "0.0200", "0.4800", "settled loss", "−$0.48"],
        ],
        total=["Game (Hsu won)", "", "", "", "", "", "venue-true", "−$0.66"],
    )
    procs = table(
        [
            ("Process", "text"),
            ("PID now", "text"),
            ("Started", "date"),
            ("vs fill-path files", "text"),
            ("This job", "text"),
        ],
        [
            [
                "B Tennis crossover (live_strategy_b.py)",
                "74812",
                "2026-10-28 14:46:00",
                "After venue_fill_confirm 14:43 / order_ledger 14:45 / live_lock_orders 14:39 — already on fill-cash code",
                "Left. Did not reload. One B.",
            ],
            [
                "A Lock supervisor (live_game_pollers.py)",
                "60888 (was 38656)",
                "2026-10-28 15:18:46",
                "Was 26 Oct 21:08 — before the fix. 89/112 pollers were pre-14:39",
                "Reloaded one lock. New pollers 104 at/after 15:18:46.",
            ],
            [
                "Dashboard writer (cheap refresh inside supervisor)",
                "60888",
                "2026-10-28 15:18:46",
                "write_dashboard.py 13:09 display-only; scored tape is dashboard_cache.json trades_at 14:59:26",
                "Came along with lock reload. Did not rebuild the book.",
            ],
            [
                "C CFB favorite / D T0 spreads / E Tennis T0 dog",
                "3064 / 62576 / 38620",
                "26 Oct 14:31 / 26 Oct 14:31 / 28 Oct 09:36",
                "All started before the fill-cash files",
                "Left. Not asked to reload C/D/E. No C=1.05 / D NFL retune.",
            ],
        ],
    )
    holes = table(
        [
            ("Hole", "text"),
            ("Status", "text"),
            ("Note", "text"),
        ],
        [
            ["GTC dip", "Not wired", "Live dip is still IOC. Architecture: recommendation, not this job."],
            ["Type on orders_performance", "Present", "Column is Order type (T0 initial low/Hi; cross = crossover lock). Dashboard Type matches."],
            ["Settled Poly vs venue", "Shimizu/Hsu matches −0.66", "87 settled Poly games on the cache; 0 with two Yes winners. Did not re-pull every venue receipt this verify."],
            ["Confirm-after-send avgPx", "Fixed in current files", "confirm_order → attach_house_cash. Empty GET still parses avgPx in this_order_cum_qty, then house_cash overwrites. Pre-fix lock pollers were the live hole; those were reloaded."],
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Polymarket price/result status 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; max-width: 1100px; margin: 24px auto; padding: 0 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Polymarket price/result — verify 28 Oct 2026</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}. Research only. Not gold. Not DailyRun. Did not commit. Did not start a second B. Did not retune C=1.05 / D NFL / leftover GTC / GTC dip. Did not overwrite the D=25 dip sweep HTML.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Have ALL changes been made to correct the wrong prices and results on Polymarket trades? Verify the kitchen book (Shimizu vs Hsu), the live new-fill path, and whether B / lock A / dashboard writer are running the current files. Do not re-implement unless the dashboard still shows the old wrong book. If only a process reload is needed, reload one lock and one B after confirming pids.</p>
<h2>In plain English</h2>
<p>We used to store the wrong cost on some Polymarket shorts and mark the wrong winner from a ticker name. That made Hsu look like a loser and Shimizu a winner, and it understated Hsu’s ticket by 10 cents. This check is whether the scoreboard now copies what Polymarket charged and what it paid at redeem, and whether the live bots will store that correctly on the next fill — not a retune of the tennis dip or the $1.05 cap.</p>
</div>

<h2>Honest three lines</h2>
{three}

<h2>Dashboard now — Yuta Shimizu vs. Yu Hsiou Hsu</h2>
<p>Winner on the kitchen: <strong>Hsu</strong> (Hsu T0 settled win; both Shimizu Yes tickets settled loss). Not the old inverted book. Cache <code>trades_at</code> 2026-10-28 14:59:26 ET. Quoted from <code>dashboard.html</code> after the lock reload’s cheap refresh (15:18:53 ET). Click column headers to sort.</p>
{cells}

<h2>Process start vs file mtime</h2>
<p>Fill-path files: <code>live_lock_orders.py</code> 14:39:32, <code>settled_pnl_store.py</code> 14:40:54, <code>open_count_sync.py</code> 14:42:35, <code>venue_fill_confirm.py</code> 14:43:20, <code>live_strategy_b.py</code> 14:43:51, <code>order_ledger.py</code> 14:45:15, <code>write_orders_performance.py</code> 14:50:12 (scoring, not send). <code>write_dashboard.py</code> 13:09:01 display-only.</p>
{procs}

<h2>Remaining gaps</h2>
{holes}

<p class="warn">B was already on the fill-cash files (14:46 vs 14:45). Reloading it would have dropped four open B matches for no code gain. Lock was the stale sender: old pollers would have stored Yes-wire on a new BUY_SHORT. One lock reload; still one B (74812).</p>
<p>Tests re-run this job: autopsy five PASS (Hsu 0.55 not 0.45; game −0.66; Type column; settlementPx 0 is no). File URL: {FILE_URL}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
