"""Bobichon vs Kelm: was the blocking orders.html rebuild a blessing?

Research only. Does not sell, start a second B, commit, print secrets,
wire leftover GTC, wire D NFL, bump stake, retune B C=1.05, or add a
wait-on-purpose sleep.
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
PAGE = STAMP / "bobichon_kelm_rebuild_blessing_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/bobichon_kelm_rebuild_blessing_20261026.html"
)
RECONCILE = "bobichon_kelm_venue_reconcile_20261026.html"

ASKED = (
    "Paul: was the blocking page rebuild a blessing, that allowed us time to wait "
    "and then we got lucky? Bobichon vs Kelm A lock 25 Oct 2026 ET: Poly hard "
    "Bobichon Yes HTTP 15:30:03 (UI 3:30 PM, $0.27 @ 26%), easy book 15:31:23, "
    "Kalshi IOC 15:33:00 Sold Yes 49.25¢ (buy No; POST Yes-wire 0.51 + fee 0.0175). "
    "Limit 34¢ sell-Yes was through the book. Filled immediately once sent. "
    "~2 min gap attributed to hard-then-easy PLUS blocking orders.html rebuild "
    "after confirm. At 15:30:03, could Kalshi easy have filled immediately at a "
    "similar or better after-fee No? Did Yes-ask / No-ask move 15:30→15:33? Size "
    "at the fill level? If we had sent at 15:30: miss vs fill vs worse price? "
    "Blessing = wait was required for the fill. Not a blessing = book was already "
    "there. Got lucky = we cannot show the wait caused the fill. Do not add a "
    "2-minute sleep. If the wait helped, that is leftover-watch / book timing, "
    "not keep blocking the UI rebuild."
)
PLAIN = (
    "We bought “Bobichon wins” on Polymarket at 3:30 PM, then the bot sat rewriting "
    "the order pages before it sent the opposite ticket on Kalshi (sell Bobichon Yes "
    "= buy No). Paul wonders if that sit was secretly helpful — empty book at 3:30, "
    "good book at 3:33. The Kalshi shop already had a 34¢ Yes buyer at 3:29 and still "
    "at 3:31, plenty of size for our one contract, so the opposite ticket would have "
    "filled without waiting. Waiting did get a cheaper No (49¢ vs 66¢) because the "
    "book moved after 3:31. That is market luck, not a reason to keep freezing the "
    "pages or to insert a two-minute pause on purpose."
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
    quotes = table(
        [
            ("Clock ET", "date"),
            ("Source", "text"),
            ("Bobichon Yes ask", "num"),
            ("Bobichon No ask", "num"),
            ("Best Yes bid / size", "text"),
            ("Size at Yes 51¢ (fill level)", "num"),
            ("34¢ sell-Yes IOC", "text"),
            ("After-fee No if we lift best bid", "num"),
        ],
        [
            [
                esc("15:29:26"),
                esc("Kalshi websocket tick (last before Poly fill)"),
                esc("0.3300"),
                esc("0.6800"),
                esc("implied 0.32 (1 − No ask); WS does not store size"),
                esc("unknown"),
                esc("WS 32¢ bid is below a 34¢ sell-Yes limit (would miss on WS alone). Send path uses REST, not this tick."),
                esc("0.6952 if lift 32¢ (fee 0.0152) — not the send tape"),
            ],
            [
                esc("15:29:33"),
                esc("Kalshi REST BOBKEL-BOB (hard-first recheck; 30s before Poly HTTP done)"),
                esc("0.3500"),
                esc("0.6600"),
                esc("0.3400 / 21,643.43"),
                esc("0"),
                esc("Fill at 34¢ Yes / 66¢ No"),
                esc("0.6757 (fee 0.0157)"),
            ],
            [
                esc("15:30:03"),
                esc("Poly hard HTTP done. No Kalshi REST. WS silent."),
                esc("no snapshot — use 15:29:33 REST"),
                esc("0.6600 (REST 30s earlier; WS last No 0.68 at 15:29:26)"),
                esc("0.3400 / 21,643.43 at 15:29:33"),
                esc("0 at last REST"),
                esc("Fill, not miss. Worse No than 15:33."),
                esc("0.6757 on last REST"),
            ],
            [
                esc("15:31:23"),
                esc("Kalshi REST easy recheck (quote stamp / sent_at)"),
                esc("0.3700"),
                esc("0.6600"),
                esc("0.3400 / 97.33"),
                esc("0"),
                esc("Fill at 34¢ Yes / 66¢ No (size still ≥1)"),
                esc("0.6757 (fee 0.0157)"),
            ],
            [
                esc("15:33:00"),
                esc("Kalshi IOC HTTP 201; ts_ms → 15:33:00.267. No REST book. WS still silent."),
                esc("unknown (next WS Yes ask 0.60 at 15:38:34)"),
                esc("0.4900 implied by fill (Yes-wire 0.51)"),
                esc("≥1 at 0.51 (we filled qty 1); 0 at 15:31:23"),
                esc("Filled immediately at 51¢ Yes / 49¢ No (limit 34¢ was through)"),
                esc("0.5075 (POST fee 0.0175)"),
            ],
        ],
        "Click column headers to sort. Yes ask = 1 − best No bid. No ask = 1 − best Yes bid. "
        "House Kalshi fee 0.07 × p × (1 − p) to $0.0001; 15:33 uses POST average_fee_paid. "
        "No REST book exists at 15:30:03 or 15:33:00.",
    )

    move = table(
        [
            ("Window", "text"),
            ("Yes ask", "text"),
            ("No ask", "text"),
            ("What moved", "text"),
        ],
        [
            [
                esc("15:29:26 WS → 15:29:33 REST"),
                esc("0.33 → 0.35"),
                esc("0.68 → 0.66"),
                esc("One to two ticks. Easy quote used REST No 0.66 size 21,643."),
            ],
            [
                esc("15:29:33 REST → 15:31:23 REST"),
                esc("0.35 → 0.37"),
                esc("0.66 → 0.66 (unchanged)"),
                esc("Yes ask widened 2¢. 34¢ Yes bid size collapsed 21,643 → 97. Still enough for 1. Size at 51¢ still 0."),
            ],
            [
                esc("15:31:23 REST → 15:33:00 fill"),
                esc("0.37 → unknown"),
                esc("0.66 → 0.49 (fill)"),
                esc("No ask improved 17¢ on the fill. 51¢ Yes bid was not on the 15:31:23 book. WS has no tick in this window."),
            ],
            [
                esc("15:29:26 → 15:38:34 WS"),
                esc("0.33 → 0.60 (gap)"),
                esc("0.68 → 0.41 (gap)"),
                esc("Websocket stored no Bobichon tick for 9 min 8 s. Next print is a 27¢ jump. Cannot reconstruct 15:33 from ticks."),
            ],
        ],
        "Same-price Kalshi ticks normally print at least every 20s when messages arrive. Silence here is a hole, not a flat 0.66 tape.",
    )

    clock = table(
        [
            ("Clock ET", "date"),
            ("Tape", "text"),
        ],
        [
            [
                esc("15:29:26"),
                esc("Trigger: Kalshi Yes websocket 0.3300."),
            ],
            [
                esc("15:29:33"),
                esc("Hard-first decision. REST Poly Yes 0.29 size 58; REST Kalshi No 0.66 size 21,643. Supervisor hard-first send."),
            ],
            [
                esc("15:30:03–05"),
                esc("Poly HTTP 200 FOK Yes 0.29 filled 0.26 + $0.01 = $0.27. UI 3:30 PM. Order DANGJ0Y011MV."),
            ],
            [
                esc("15:30:05 → 15:31:23"),
                esc("Hard confirm + blocking orders.html / opportunities / orders_performance rebuild, then easy REST book."),
            ],
            [
                esc("15:31:23.969"),
                esc("Easy quote stamp. No 0.66 size 97.33. Limit posted ask 0.3400. sent_at is here; HTTP is not."),
            ],
            [
                esc("15:31:23 → 15:33:02"),
                esc("order_io shows other games using the Kalshi book slot (NFL spreads/totals, Gemini) before this IOC returns. Not a resting GTC."),
            ],
            [
                esc("15:33:00–02"),
                esc("Kalshi IOC 201. Yes-wire 0.51 + fee 0.0175; GET No 0.49; UI Sold Yes 49.25. Order 01a1748d-4de0-70ae-ae4c-3ea62b42ef50."),
            ],
        ],
        "Poly 15:30:03 vs Kalshi 15:33:00 is sequential hard-then-easy plus send-path delay, not leftover-watch and not a 2-minute sleep we added.",
    )

    body = f"""
<h1>Bobichon vs Kelm — was the page-rebuild wait a blessing?</h1>
<p class="tiny">Stamp drive/paul_experiments/prediction_market_arb_exhaustive_20261017/. Tape: order_io.jsonl REST books, price_memory/2026-10-25/tennis.jsonl, live_supervisor.log, orders.jsonl. Venue map: <a href="{esc(RECONCILE)}">{esc(RECONCILE)}</a>. Did not sell. Did not start a second B. Did not wire leftover GTC. Did not add a 2-minute sleep. {esc(FILE_URL)}</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="verdict">
<p><strong>Not a blessing</strong> — Kalshi already had 21,643 contracts bidding Yes at 34¢ at 15:29:33 (still 97 at 15:31:23), so a 34¢ sell-Yes / buy-No IOC would have filled as soon as Poly was done; the rebuild did not create the fill.</p>
<p>The 15:33 fill at Yes 51¢ / No 49¢ after-fee 50.75¢ is <strong>better</strong> than the 15:30 book (No after-fee 67.57¢). That improvement is leftover book timing after 15:31:23, not evidence to keep blocking <code>orders.html</code>. Websocket is silent 15:29:26–15:38:34, so we cannot show the wait caused the 51¢ bid — only that the IOC printed it. <strong>Did not add a wait-on-purpose.</strong></p>
</div>

<h2>Would immediate easy have filled?</h2>
<p><strong>Fill, not miss, worse after-fee No.</strong> Last Kalshi REST before Poly’s 15:30:03 is 15:29:33: best Yes bid 34¢, size 21,643. Easy limit was sell-Yes 34¢ (pay No 66¢). That is through the bid. After-fee No ≈ 0.6757 vs the actual 0.5075. With Poly 0.27 the lock is still under $1 (~+5.4¢ vs the +22.25¢ we got). 15:31:23 is the same 34¢ / 66¢ print, size 97.33 — still a fill for 1 contract. Size at the 51¢ fill level was <strong>0</strong> on both REST books; the 51¢ bid showed up after 15:31:23.</p>

<h2>Kalshi quotes 15:30 / 15:31 / 15:33</h2>
{quotes}

<h2>Did Yes-ask / No-ask move 15:30→15:33?</h2>
{move}
<p>No ask was 66¢ on both REST snapshots bracketing Poly’s fill. It was 49¢ on the 15:33 fill. Yes ask went 35¢ → 37¢ on REST, then we have no REST at 15:33. Do not treat the 51¢ fill as the 15:30 book.</p>

<h2>Clock (unchanged from the venue tape)</h2>
{clock}

<h2>What this is not</h2>
<ul>
<li>Not a reason to keep blocking the UI rebuild on the send path. Sibling job is removing that block; this page does not put it back.</li>
<li>Not a 2-minute sleep. If a later fill is cheaper, that is book timing / leftover-watch research, not a freeze-the-pages knob.</li>
<li>Not leftover GTC, not a second B, not D NFL, not a C=1.05 retune, not a stake bump.</li>
</ul>

<p class="tiny">Written {esc(datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"))}. Research only. Not gold. Not DailyRun. Tiny N=1.</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Bobichon vs Kelm rebuild blessing 26 Oct 2026</title>
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
{body}
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    page = report_page_extras.inject_report_page_extras(page)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    print(write_page())


if __name__ == "__main__":
    main()
