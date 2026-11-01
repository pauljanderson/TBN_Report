"""Yastremska vs Volynets: one Kalshi fill was shown as both a win and a loss.

Research only. Does not sell, start a second B, commit, print secrets,
wire D NFL, bump stake, leftover GTC, or retune C=1.05.
"""
from __future__ import annotations

import html as html_lib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "yastremska_volynets_fill_dup_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/yastremska_volynets_fill_dup_20261027.html"
)

ASKED = (
    "Paul: dashboard shows the SAME B fill as both a win and a loss. "
    "Rows (identical except outcome/P&L): 2026-10-27 02:24:52 ET B Tennis crossover "
    "Yastremska vs Volynets WTA kalshi Yes Dayana Yastremska wins 0.4600 0.0174 0.4774 "
    "kalshi HTTP 201 fill 1.00 fill_count 1.00 yes — venue fill qty ≥ 1 settled loss "
    "lost bet (settled with-fee P&L < 0) −$0.05 AND settled win — +$0.52. "
    "Find every real order on this match. Fill-history is truth. Do not sell, second B, "
    "commit, secrets, bump stake. Fix dashboard so one venue fill is one row, one P&L, "
    "win XOR loss. Rebuild dashboard.html."
)
PLAIN = (
    "We bought three real Kalshi tickets on Yastremska vs Volynets. At match start we "
    "bought Yes Yastremska at 46¢ and Yes Volynets at 56¢ (Tennis crossover T0 both-Yes). "
    "Later we bought another Yes Yastremska at 55¢ (the extra/cross). Yastremska won, so "
    "the two Yastremska tickets pay $1 each and the Volynets ticket pays $0. After Kalshi "
    "fees that is +52¢, −58¢, and +43¢, about +38¢ for the match. The scoreboard printed "
    "the 55¢ extra buy twice, both times using the 46¢ start price, once as a 5¢ loss "
    "(the T0 pair’s net) and once as a 52¢ win (the start Yastremska ticket’s own P&L). "
    "Same timestamp, same ticker, same 46¢. That was one fill with two stories, not two "
    "fills. No flatten. No lock. Fix: keep T0 and extra on separate rows, never copy a "
    "pair’s P&L onto every ticket, and never reuse the start fill price on a later Yes "
    "of the same player."
)


def esc(value) -> str:
    return html_lib.escape(str("" if value is None else value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    cap = f"<p class=\"note\">{esc(caption)}</p>" if caption else ""
    return (
        f"{cap}{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def write_page() -> Path:
    fills = table(
        [
            ("When ET", "date"),
            ("Step", "text"),
            ("Side", "text"),
            ("Ticker", "text"),
            ("Order id", "text"),
            ("Fill id", "text"),
            ("Qty", "num"),
            ("Yes price", "num"),
            ("Fee", "num"),
            ("After-fee", "num"),
            ("Venue result", "text"),
            ("Who won this ticket", "text"),
            ("With-fee P&L", "num"),
        ],
        [
            [
                esc("2026-10-27 02:00:53 ET"),
                esc("B T0"),
                esc("Yes Katie Volynets wins"),
                esc("KXWTAMATCH-26OCT26YASVOL-VOL"),
                esc("01a17bf2-8208-73a7-8b40-276df04918be"),
                esc("07249420-f461-b1ea-81fc-0a820f274a35"),
                esc("1.00"),
                esc("0.5600"),
                esc("0.0173"),
                esc("0.5773"),
                esc("no (Volynets lost)"),
                esc("loss"),
                esc("−$0.5773"),
            ],
            [
                esc("2026-10-27 02:01:08 ET"),
                esc("B T0"),
                esc("Yes Dayana Yastremska wins"),
                esc("KXWTAMATCH-26OCT26YASVOL-YAS"),
                esc("01a17bf2-bca0-76a2-8f0a-415c540b5ea6"),
                esc("07249422-7da9-add1-9d8d-96714d987402"),
                esc("1.00"),
                esc("0.4600"),
                esc("0.0174"),
                esc("0.4774"),
                esc("yes (Yastremska won)"),
                esc("win"),
                esc("+$0.5226"),
            ],
            [
                esc("2026-10-27 02:25:25 ET"),
                esc("B extra/cross"),
                esc("Yes Dayana Yastremska wins"),
                esc("KXWTAMATCH-26OCT26YASVOL-YAS"),
                esc("01a17c08-f808-72d5-b9b9-210693c8a94f"),
                esc("07248c24-3331-bf58-5ab5-55b4ec96e738"),
                esc("1.00"),
                esc("0.5500"),
                esc("0.0174"),
                esc("0.5674"),
                esc("yes (Yastremska won)"),
                esc("win"),
                esc("+$0.4326"),
            ],
        ],
        "Three Kalshi GET /trade-api/v2/portfolio/fills rows. Qty 1.00 each. No flatten. No A lock. Click headers to sort.",
    )
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yastremska vs Volynets fill duplicate 27 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 14px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
.verdict {{ background: #fefce8; border: 1px solid #facc15; padding: 10px 12px; margin: 8px 0 16px; }}
ul {{ margin-top: 0.3rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Yastremska vs Volynets — one fill was not a win and a loss</h1>
<p class="updated">Written {esc(now)}</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="verdict">
<p><strong>Three real Kalshi tickets.</strong> True with-fee P&amp;L for the match is <strong>+$0.3779</strong> (about +38¢). The page doubled because the extra Yes at 55¢ was left on the T0 row list and relabeled with the 46¢ start price, then the pair’s −5¢ and the start ticket’s +52¢ were both stamped on that same row. Fix shipped on dashboard.html and the performance generator. Did not sell.</p>
</div>
<h2>Venue fill-history (truth)</h2>
{fills}
<h2>Why the page said win AND loss</h2>
<ol>
<li>Tennis crossover (B) bought both players at trusted start (T0), then a later extra Yes on Yastremska when she was the underdog.</li>
<li>The performance splitter kept all three tickets on the T0 cluster’s <code>legs</code> list and also copied the extra onto a second cluster.</li>
<li>The scoreboard walked <code>legs</code> and copied each cluster’s total P&amp;L onto every ticket. T0 net is −$0.05 (one of those two Yes tickets must lose). Extra was scored as +$0.52 because the start fill price 46¢ was pasted onto the 55¢ extra order (same Kalshi ticker).</li>
<li>So 02:24:52 / Yes Yastremska / 0.4600 printed twice: settled loss −$0.05 and settled win +$0.52. Same order, two stories.</li>
</ol>
<h2>What we did not buy</h2>
<ul>
<li>No flatten (we did not sell either ticket back).</li>
<li>No A lock (no Yes+No hedge on one player).</li>
<li>No second extra B send. HTTP 201 fill_count 1.00 three times, three fill ids.</li>
</ul>
<p class="note">Dashboard: <a href="dashboard.html">dashboard.html</a>. Performance: <a href="orders_performance.html">orders_performance.html</a>. {esc(FILE_URL)}</p>
<p class="tiny">Written {esc(now)}. Sources: orders.jsonl, order_io.jsonl, strategy_b_watch.json, Kalshi GET fills (YAS + VOL), settlements YAS result=yes / VOL result=no. Research only. Not gold. Not DailyRun.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html = report_page_extras.inject_report_page_extras(page)
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    return PAGE


def main() -> int:
    write_page()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
