"""Poly FOK no-partials report. Does not sell. Does not print secrets."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import novig_live  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "poly_fok_no_partials_20261024.html"
ASKED = (
    "He does not want to buy partial shares. Only fill if the # contracts we are "
    "ordering are available. Polymarket only (that is the venue with 0.02 / 0.19 / "
    "~0.32 leftovers)."
)


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def pid_bit(rows) -> str:
    pids = []
    for row in rows or []:
        pid = row.get("pid") if isinstance(row, dict) else row
        if pid:
            pids.append(str(pid))
    return ", ".join(pids) if pids else "none"


def write_page(pids: dict | None = None, reload_notes: list[str] | None = None) -> Path:
    now = datetime.now(ET)
    pids = pids or {}
    notes = reload_notes or []
    body = live_lock_orders.polymarket_order_body(
        "slug", "ORDER_INTENT_BUY_LONG", Decimal("0.40")
    )
    kalshi = live_lock_orders.kalshi_order_body("KX", "yes", Decimal("0.40"), "cid")
    gemini = live_lock_orders.gemini_order_payload("GEMI", "yes", Decimal("0.40"))
    novig = novig_live.order_body("oid", Decimal("0.40"), "cid") or {}
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Poly FOK no partials — 24 Oct 2026</title>
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
<h1>Polymarket fill-or-kill — no partial shares</h1>
<p class="banner"><strong>Research-candidate live. Not gold. Not DailyRun.</strong>
Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Fill-or-kill (FOK) means fill the whole
order now or cancel it. Immediate-or-cancel (IOC) can take a slice and cancel the rest.
Did not sell Namigata 0.19/0.32 or Guajardo 0.19. Did not start a second Strategy B.
Kalshi / Gemini / Novig stay IOC. Did not wire GTC.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>Polymarket was letting us buy a sliver of a contract (2¢, 19¢, ~32¢ leftovers) because
the live order type was IOC: take whatever is showing, dump the rest. You only want a fill
when the whole number of contracts we ordered is actually on the book. We switched every
live Polymarket buy to fill-or-kill, and we also peek at the displayed ask size first: if
that size is smaller than the contracts we are sending (default 1), we do not even POST.
A leftover 0.19 is not “we hold 1.” We do not flatten it as if we hold 1, and we do not
send a second order to complete the share.</p>
</div>

<h2>FOK live?</h2>
<p><strong>Yes.</strong> Official consumer SDK on the path we already post
(<code>POST /v1/orders</code>) lists <code>FILL_OR_KILL</code>. Repo freeze:
<code>tools/_write_gtc_feasibility_20261022.py</code> — “Official consumer SDK also lists
GOOD_TILL_DATE, IMMEDIATE_OR_CANCEL, FILL_OR_KILL.” Exact live field:</p>
<p><code>tif = TIME_IN_FORCE_FILL_OR_KILL</code> on <code>polymarket_order_body</code>
(quantity is a whole integer, default 1). We did not invent a flag.</p>
<p>Live body right now: <code>tif={esc(body.get("tif"))}</code>,
<code>quantity={esc(body.get("quantity"))}</code>.</p>

<h2>Every live Poly POST</h2>
<p class="note">Click column headers to sort. All of these go through
<code>polymarket_order_body</code> → <code>POST /v1/orders</code>.</p>
{table(
    [("Path", "text"), ("Helper", "text"), ("Was", "text"), ("Now", "text")],
    [
        ["Lock pair legs", "<code>_leg_spec</code> / <code>_spec_at_price</code> / <code>_send</code>", "IOC", "FOK"],
        ["Lock leftover watch", "<code>_send_watch_ioc</code> → <code>_one_ioc</code> → <code>_send</code>", "IOC", "FOK"],
        ["Lock flatten (Poly buy of the opposite)", "<code>flatten_filled_leg</code> → <code>_one_ioc</code>", "IOC", "FOK"],
        ["Tennis crossover B T0 / 50-cross / fav dip / leftover Yes", "<code>send_yes_ioc</code> → <code>_spec_at_price</code> → <code>_send</code>", "IOC", "FOK"],
        ["C college football favorite", "<code>live_t0_yes.send_yes</code> same helper", "IOC", "FOK"],
        ["D T0 spreads", "<code>live_t0_yes.send_yes</code> same helper", "IOC", "FOK"],
    ],
)}

<h2>Other venues (unchanged)</h2>
{table(
    [("Venue", "text"), ("Field", "text"), ("Value", "text")],
    [
        ["Kalshi", "<code>time_in_force</code>", esc(kalshi.get("time_in_force"))],
        ["Gemini", "<code>timeInForce</code>", esc(gemini.get("timeInForce"))],
        ["Novig", "<code>tif</code>", esc(novig.get("tif"))],
    ],
)}

<h2>REST size skip</h2>
<p><strong>Live.</strong> Before a Poly POST, REST recheck of displayed ask size. If
size &lt; order qty, do not send, even though FOK would reject. Log token
<code>poly_size_lt_qty_skip</code>. Qty is whole contracts, default 1. Guajardo 0.02
book replays as a skip, not a 0.02 fill.</p>

<h2>House fill</h2>
<p>This order’s <code>cumQuantity</code> must be ≥ the qty we sent. Partial
0 &lt; q &lt; qty is <strong>not</strong> a house 1-contract fill. With FOK the venue
should return 0 or ≥ qty. If a partial still appears: ntfy + log
<code>poly_fok_partial_unexpected</code>, do not treat as T0 filled, do not flatten
as if we hold 1, do not send a second IOC to complete the share. Existing Namigata
0.19/0.32 and Guajardo 0.19 were not sold.</p>

<h2>Tests</h2>
{table(
    [("Case", "text"), ("Result", "text")],
    [
        ["Book size 0.19 + FOK", "No POST / no house open (<code>poly_size_lt_qty_skip</code>)"],
        ["Size ≥ 1 + FOK fill 1", "POST <code>TIME_IN_FORCE_FILL_OR_KILL</code> qty 1; house open 1"],
        ["Kalshi / Gemini / Novig", "Still IOC"],
        ["Guajardo 0.02 book replay", "Poly leftover skip; no send"],
        ["50-cross Poly partial", "Not flattened as 1; extra_stuck; no second IOC"],
    ],
)}

<h2>Reload (hidden spawn, one of each)</h2>
{table(
    [("Job", "text"), ("Pids", "text")],
    [
        ["Lock supervisor", esc(pids.get("supervisor") or "n/a")],
        ["Lock pollers", esc(pids.get("children") or "n/a")],
        ["Catalog scan", esc(pids.get("scan") or "n/a")],
        ["B tennis crossover", esc(pids.get("strategy_b") or "n/a")],
        ["C CFB favorite", esc(pids.get("cfb_favorite") or "n/a")],
        ["D T0 spreads", esc(pids.get("spread_t0") or "n/a")],
    ],
)}
<p class="tiny">{esc(" | ".join(notes) if notes else "Reload notes empty.")}</p>

<p class="note">Sources: <code>tools/live_lock_orders.py</code> <code>polymarket_order_body</code>,
<code>poly_size_lt_qty_skip</code>, <code>_send</code>, leftover watch, flatten;
<code>tools/live_strategy_b.py</code> <code>send_yes_ioc</code>;
<code>tools/live_t0_yes.py</code> C/D; <code>tools/venue_fill_confirm.py</code>
<code>house_size_of</code>; <code>tools/_write_gtc_feasibility_20261022.py</code>.
No secrets. Did not sell. Did not start a second <code>live_strategy_b.py</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")
    return PAGE


def main() -> int:
    write_page()
    print(PAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
