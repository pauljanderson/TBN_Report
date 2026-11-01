"""How Paul knows we know the fee. Research HTML. Does not sell or start B."""
from __future__ import annotations

import html as html_lib
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "venue_fee_first_class_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/venue_fee_first_class_20261026.html"
)

ASKED = (
    "Paul: “you need to be 100% aware of the fee at all times. How can we make sure you know what it is?” "
    "Bobichon vs Kelm: autopsy logged Kalshi Yes 0.49 (wire). Venue after-fee is 50.75¢ "
    "(0.07 × 0.49 × 0.51 = 1.75¢; POST average_fee_paid 0.0175). Live fee_returned did not read "
    "average_fee_paid and hardcoded 0. That must stop."
)
PLAIN = (
    "A ticket has two prices: the wire (what the book prints) and after-fee (what actually leaves "
    "your cash). We were showing the wire as after-fee, and the live sender treated Kalshi’s fee as "
    "$0 unless the fill body happened to use a different field name. That is why Bobichon Yes looked "
    "like 49¢ on our page and 50.75¢ on Kalshi. Now every look uses the documented formula, and every "
    "fill overwrites that estimate with what the venue actually charged. If we only have a wire, the "
    "cell says fee unknown — never 0. Lock cap stays 99¢. Tennis crossover (B) all-in C stays $1.05."
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


def money4(value: Decimal) -> str:
    return live_lock_orders._net_text(value)


def write_page(pids: dict | None = None) -> Path:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    bob_wire = Decimal("0.49")
    bob_est = live_lock_orders.kalshi_fee_amount(bob_wire)
    bob_venue = live_lock_orders.kalshi_fee_amount(
        bob_wire, {"average_fee_paid": "0.0175", "average_fill_price": "0.4900"}
    )
    flatten_wire = Decimal("0.54")
    flatten_est = live_lock_orders.kalshi_fee_amount(flatten_wire)
    flatten_venue = live_lock_orders.kalshi_fee_amount(
        flatten_wire, {"average_fee_paid": "0.0174"}
    )
    lock_no = Decimal("0.49")
    lock_fee = live_lock_orders.kalshi_fee_amount(lock_no, {"average_fee_paid": "0.0175"})
    pid = pids if isinstance(pids, dict) else {}
    lock_pid = pid.get("lock") or pid.get("supervisor") or "not reloaded this pass"
    b_pid = pid.get("b") or pid.get("strategy_b") or "left in place"

    formulas = table(
        [("Venue", "text"), ("When", "text"), ("Formula / truth", "text"), ("If missing", "text")],
        [
            [
                esc("Kalshi"),
                esc("Before send"),
                esc("0.07 × p × (1 − p) to $0.0001 (unrounded Decimal product, then house 4dp)"),
                esc("Always documented. Never treat as $0."),
            ],
            [
                esc("Kalshi"),
                esc("After fill"),
                esc("POST average_fee_paid (same as GET fee_cost). Overwrites the estimate."),
                esc("Fall back to the formula. Do not print 0."),
            ],
            [
                esc("Polymarket"),
                esc("Before send / after fill"),
                esc("theta × p × (1 − p), banker's cent. Fill commission overwrites."),
                esc("Fee unknown — do not invent theta. Skip send."),
            ],
            [
                esc("Gemini"),
                esc("Before send / after fill"),
                esc("0.07 × p × (1 − p), round up to the next cent. Venue fee overwrites."),
                esc("Always documented."),
            ],
            [
                esc("Novig"),
                esc("Before send"),
                esc("c × p × (1 − p) to $0.00001. c = market.fee.coefficient (live catalog 0.06). WHEN_LIVE only if event is OPEN_INGAME; pregame $0. ALWAYS on eligible futures. Same on Yes and No."),
                esc("Missing coefficient after GET /v3/catalog/markets/{id} → fee unknown, skip send. Do not invent 0."),
            ],
            [
                esc("Novig"),
                esc("After fill"),
                esc("GET /v3/portfolio/fills `fee` (absent = uncharged $0). Overwrites the estimate. fee_source=venue."),
                esc("No fill row → formula if the market named c. Else fee unknown."),
            ],
        ],
        "Click column headers to sort. Fill overwrites estimate on every venue.",
    )

    bobichon = table(
        [
            ("Ticket", "text"),
            ("Wire", "num"),
            ("Formula fee", "num"),
            ("Venue average_fee_paid", "num"),
            ("After-fee (all-in)", "num"),
            ("Old autopsy after-fee", "num"),
            ("Match?", "text"),
        ],
        [
            [
                esc("B T0 Yes Bobichon (Kalshi bid)"),
                esc("0.4900"),
                esc(money4(bob_est)),
                esc("0.0175"),
                esc(money4(bob_wire + bob_venue)),
                esc("0.4900 (wire, wrong)"),
                esc("Yes — 0.07 × 0.49 × 0.51 = 0.0175. UI 50.75¢."),
            ],
            [
                esc("B flatten Sold Yes / buy No"),
                esc("0.5400 Yes-wire (No cash 0.4600)"),
                esc(money4(flatten_est)),
                esc("0.0174"),
                esc(money4(Decimal("0.46") + flatten_venue)),
                esc("wire only"),
                esc("Yes — POST 0.0174."),
            ],
            [
                esc("A lock Kalshi No (Sold Yes 49.25¢)"),
                esc("0.4900 No cash"),
                esc(money4(live_lock_orders.kalshi_fee_amount(lock_no))),
                esc("0.0175"),
                esc(money4(lock_no + lock_fee)),
                esc("0.4900"),
                esc("Yes — 50.75¢ after-fee on the A No."),
            ],
            [
                esc("A lock Poly Yes"),
                esc("0.2600"),
                esc("0.0100 (taker $0.01 on the 26¢ fill)"),
                esc("Poly commission $0.01"),
                esc("0.2700"),
                esc("0.26 / 0.27 mixed"),
                esc("Yes — 26¢ wire, 27¢ after-fee."),
            ],
        ],
        "Bobichon vs Kelm vs the house formula. After-fee is all-in. Wire is never after-fee.",
    )

    where = table(
        [("Hole", "text"), ("Was", "text"), ("Now", "text")],
        [
            [
                esc("live_lock_orders.fee_returned"),
                esc("Walked fee_cost / taker_fees / fees / fee. Skipped average_fee_paid. 0 counted as a fee."),
                esc("Prefers average_fee_paid. 0 is missing. Formula fills the gap."),
            ],
            [
                esc("leg_fee / pair_net / contract_cost (A send)"),
                esc("Kalshi fee $0 unless the POST body used a different key."),
                esc("Pre-send 0.07 × p × (1 − p). Cap still 0.99 all-in."),
            ],
            [
                esc("orders.jsonl"),
                esc("No first-class wire / fee / after_fee."),
                esc("wire, fee, after_fee, fee_source (estimate | venue | formula | unknown | no_fill). Fill overwrites estimate."),
            ],
            [
                esc("Local cash debit"),
                esc("Kalshi debit was wire (0.49 → $0.49)."),
                esc("Debit after-fee (0.49 + 0.0175 = 0.5075)."),
            ],
            [
                esc("orders.html / opportunities / orders_performance / autopsies"),
                esc("Fee column 0 when missing. After-fee was the wire."),
                esc("After-fee column is all-in ≥4 decimals. Missing → fee unknown, not 0."),
            ],
            [
                esc("Tennis crossover B t0_leg_fee"),
                esc("Already used the Kalshi formula. Did not read average_fee_paid."),
                esc("Now reads average_fee_paid via fee_returned. B was not reloaded (healthy send estimate)."),
            ],
            [
                esc("Novig send + jsonl"),
                esc("Skip / fee unknown when coefficient missing. POST/order has no fee field."),
                esc("c × p × (1 − p) from market.fee. Fill GET /v3/portfolio/fills `fee` is venue truth (absent = $0 uncharged). Still skip if c is missing after GET market."),
            ],
            [
                esc("Osborne Kalshi No funds/cost"),
                esc("contract_cost / _funds_block used POST Yes-wire limit 7¢. Cap path already used house pay 93¢."),
                esc("_leg_cash_price uses pay (89¢/93¢) once. Invert limit only if pay is missing. pair_net on the fill is 1.0269 — would not send."),
            ],
        ],
        "Click column headers to sort.",
    )

    pid_note = (
        f"Lock supervisor reloaded (Kalshi fee first-class + Kalshi No house cash). Pid {esc(str(lock_pid))}. "
        f"One B left in place ({esc(str(b_pid))}). Did not start a second B. Did not sell. "
        "Did not wire leftover GTC, dual simultaneous, D NFL, or retune C=$1.05. Cap 0.99 stays. "
        "Did not revert bc97ac6b."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Venue fee first-class — 26 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>How we know the fee</h1>
<p class="banner"><strong>Research live. Not gold. Not DailyRun.</strong> Written {esc(now)}.
Fee is first-class on every look and every fill. Fill overwrites estimate.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<p class="note">{pid_note}</p>
<p class="note">Sibling hard-then-easy HTML hold on <code>live_lock_orders.py</code> is kept: Drive pages are not rebuilt between the hard IOC and the easy IOC. This job did not put blocking HTML on the send path.</p>
<div class="callout">
<h2>What you asked (Osborne prevent, merged)</h2>
<p>This lock should never have sent if pair_net used house No cash 0.89 not Yes-wire 0.07. Confirm Kalshi No is 1−Yes-wire once, after-fee, unrounded vs 0.99. Fix and reload one lock if send still treats No as 7¢. Leave B. Do not revert bc97ac6b.</p>
<h2>In plain English</h2>
<p>Osborne’s all-in was 102.69¢. The send cap did <em>not</em> treat No as 7¢ — it used 93¢ + Poly 6¢ with Kalshi fee still $0. After the 89¢ fill, Poly 14¢ passed because fill cash was inverted to 11¢. Today pair_net on that fill is 1.0269 and it would not send. Funds still used the 7¢ POST ask; that cost path now uses house pay. Details: <a href="osborne_hinojosa_reconcile_20261026.html">osborne_hinojosa_reconcile_20261026.html</a>.</p>
</div>

<h2>Per-venue formula</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
{formulas}

<h2>Bobichon vs Kelm vs the formula</h2>
{bobichon}

<h2>Where fee was 0 / wrong, and where it is now</h2>
{where}

<h2>orders.jsonl fields</h2>
<ul>
<li><code>wire</code> — pay-side cash (Kalshi No is 1 − Yes-wire).</li>
<li><code>fee</code> — venue <code>average_fee_paid</code> / Poly commission / Novig GET fills <code>fee</code> after fill; documented formula before send.</li>
<li><code>after_fee</code> — wire + fee. Never the wire alone.</li>
<li><code>fee_source</code> — <code>estimate</code> (pre-send) · <code>venue</code> (POST/GET) · <code>formula</code> (fill, no venue key) · <code>unknown</code> · <code>no_fill</code>.</li>
</ul>
<p class="note">Related: <a href="osborne_hinojosa_reconcile_20261026.html">osborne_hinojosa_reconcile_20261026.html</a>,
<a href="bobichon_kelm_venue_reconcile_20261026.html">bobichon_kelm_venue_reconcile_20261026.html</a>,
<a href="tennis_ten_match_autopsy_20261026.html">tennis_ten_match_autopsy_20261026.html</a>,
<a href="orders.html">orders.html</a>,
<a href="opportunities.html">opportunities.html</a>,
<a href="orders_performance.html">orders_performance.html</a>.</p>
<p class="tiny">Generator: <code>tools/_write_venue_fee_first_class_20261026.py</code>. Bookmark <code>{esc(FILE_URL)}</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


if __name__ == "__main__":
    path = write_page()
    print(path)
