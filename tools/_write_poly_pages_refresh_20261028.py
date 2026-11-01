"""Kitchen page refresh after Poly price/result fix. No send. No commit."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from report_page_extras import (
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    inject_report_page_extras,
)
from write_orders_performance import table

STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "poly_pages_refresh_20261028.html"
ET = ZoneInfo("America/New_York")
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/poly_pages_refresh_20261028.html"
)
ASKED = (
    "Paul: now that Polymarket price and winner are corrected, rerun/rebuild these pages "
    "so they are accurate. Tell him which were already fixed vs rebuilt now. He will refresh "
    "the file:// URLs. Pages: orders.html, opportunities.html, orders_performance.html, "
    "job_status.html, new_systems_backtest_20261024/compare.html. Also check dashboard.html."
)
PLAIN = (
    "We used to store the wrong cost on some Polymarket shorts and mark the wrong winner "
    "from a ticker name. The scoring code already copies what Polymarket charged (Hsu short "
    "56¢) and what it paid at redeem (Hsu won). This job rebuilt the kitchen scoreboards "
    "from those generators so a file:// refresh is current. The Oct 24 new-system backtest "
    "is a different book — collected T0 Yes asks, size 1 — not the live Polymarket ledger, "
    "so those numbers were left alone."
)


def mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, ET).strftime("%Y-%m-%d %H:%M:%S ET")


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    rows = [
        [
            "orders.html",
            "Y",
            "Y — Hsu BUY_SHORT cash 0.55 already on the ledger before this job",
            "Hsu short cash 0.55 fee 0.01 (56¢). Shimizu Yes 0.46 / 0.60. No P&L column (ledger, not settle).",
            mtime(STAMP / "orders.html"),
        ],
        [
            "opportunities.html",
            "Y",
            "Y — look log, not the settle book",
            "Shimizu/Hsu/Bucsa not in the last 500 looks. Not a trade P&L page.",
            mtime(STAMP / "opportunities.html"),
        ],
        [
            "orders_performance.html",
            "Y",
            "Y — already Hsu-won −0.48 / +0.44 / −0.62 before this rewrite",
            "T0 Shimizu −$0.48, Hsu +$0.44 (56¢), extra Shimizu −$0.62, game −$0.66. Bucsa/Joint four Kalshi fills clustered T0 −$0.04 + extra +$0.28 = +$0.24.",
            mtime(STAMP / "orders_performance.html"),
        ],
        [
            "job_status.html",
            "Y",
            "Y — up/down + open overlay, not the Shimizu settle book",
            "No Shimizu/Hsu/Bucsa rows (open positions kitchen). Did not start/stop jobs.",
            mtime(STAMP / "job_status.html"),
        ],
        [
            "new_systems_backtest_20261024/compare.html",
            "N — numbers frozen; one-line kitchen-book note added",
            "Y for its own tape — T0 Yes-ask size-1 backtest, not live Poly fills",
            "Not on this page. Live Shimizu/Hsu is a different book. P2 still $20.60 N=91. Did not mix live fills in.",
            mtime(STAMP / "new_systems_backtest_20261024" / "compare.html"),
        ],
        [
            "dashboard.html",
            "Y — write_orders_performance then job_status overlay",
            "Y — Hsu-won −0.48 / +0.44 / −0.62 / game −0.66 already on the kitchen",
            "Hsu won. Shimizu T0 −$0.48, Hsu +$0.44, Shimizu cross −$0.62, game −$0.66. No What you asked block.",
            mtime(STAMP / "dashboard.html"),
        ],
    ]
    page_table = table(
        [
            ("Page", "text"),
            ("Rebuilt now", "text"),
            ("Already correct", "text"),
            ("Shimizu check", "text"),
            ("LastWriteTime", "date"),
        ],
        rows,
    )
    shim = table(
        [
            ("When ET", "date"),
            ("Type", "text"),
            ("Side", "text"),
            ("Wire", "num"),
            ("Fee", "num"),
            ("After-fee", "num"),
            ("Outcome", "text"),
            ("P&L", "num"),
        ],
        [
            ["2026-10-28 00:27:00 ET", "crossover lock", "Yes Yuta Shimizu", "0.6000", "0.0200", "0.6200", "settled loss", "−$0.62"],
            ["2026-10-28 00:01:02 ET", "initial Hi lock", "Yes Yu-Hsiou Hsu", "0.5500", "0.0100", "0.5600", "settled win", "+$0.44"],
            ["2026-10-28 00:01:02 ET", "initial low lock", "Yes Yuta Shimizu", "0.4600", "0.0200", "0.4800", "settled loss", "−$0.48"],
        ],
        total=["Game (Hsu won)", "", "", "", "", "", "venue-true", "−$0.66"],
    )
    buc = table(
        [
            ("When ET", "date"),
            ("Side", "text"),
            ("Wire", "num"),
            ("Fee", "num"),
            ("After-fee", "num"),
            ("Outcome", "text"),
            ("P&L", "num"),
        ],
        [
            ["2026-10-28 00:34:36 ET", "Yes Cristina Bucsa wins", "0.4600", "0.0174", "0.4774", "settled loss", "−$0.48"],
            ["2026-10-28 00:34:36 ET", "Yes Maya Joint wins", "0.5500", "0.0174", "0.5674", "settled win", "+$0.43"],
            ["2026-10-28 01:33:54 ET", "Yes Cristina Bucsa wins", "0.5100", "0.0175", "0.5275", "settled loss", "−$0.53"],
            ["2026-10-28 02:08:03 ET", "Yes Maya Joint wins", "0.1800", "0.0104", "0.1904", "settled win", "+$0.81"],
        ],
        total=["Four Kalshi fills", "", "", "", "", "clustered +$0.24", "legs +$0.23"],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Poly kitchen pages refresh 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; max-width: 1100px; margin: 24px auto; padding: 0 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Poly kitchen pages refresh — 28 Oct 2026</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}. Kitchen refresh from current generators. Did not commit. Did not start a second B. Did not retune C=1.05, D NFL, leftover GTC, or stake. Venue truth (BUY_SHORT house cash, settlementPx) left in place. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{ASKED}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{PLAIN}</p>
</div>

<h2>Each page</h2>
{page_table}

<h2>Dashboard Shimizu vs Hsu (Hsu won)</h2>
<p>Matches the kitchen check: Hsu 56¢ win +$0.44, two Shimizu losses, game −$0.66. Old inverted book is gone.</p>
{shim}

<h2>Bucsa vs Joint (Kalshi, on the book)</h2>
<p>Four fills. Clustered T0 −$0.04 + extra +$0.28 = <strong>+$0.24</strong>. Summing the four displayed legs is +$0.23 (penny rounding on the 2-decimal cells).</p>
{buc}

<p class="warn">compare.html is a frozen 2026-10-24 research backtest on collected T0 Yes asks (size 1), not the live Polymarket kitchen. Inputs were not the inverted live Poly winner / Yes-wire cash book, so numbers were left. One-line note added. Refresh file:// URLs.</p>
<p>File URL: {FILE_URL}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    OUT.write_text(inject_report_page_extras(html), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
