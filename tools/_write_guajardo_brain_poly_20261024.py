"""Guajardo vs Brain Polymarket autopsy HTML. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "guajardo_brain_poly_20261024.html"

ASKED = (
    "He's confused about some Polymarket orders. Review this match, tell him what you "
    "think we ordered: Alexander Guajardo vs. Lachlan Brain. Then fetch data from "
    "Polymarket and compare to what was actually ordered. Same? Different? What happened "
    "and why? What if anything will we fix?"
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], totals: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if totals:
        cells = "".join(f"<td>{cell}</td>" for cell in totals)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def main(b_pid: str = "", checked: str = "") -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    checked = checked or now
    compare = table(
        [
            ("When ET", "date"),
            ("System", "text"),
            ("Player / side we meant", "text"),
            ("Poly wire", "text"),
            ("Limit", "num"),
            ("IOC", "text"),
            ("HTTP", "num"),
            ("Tape qty", "num"),
            ("Confirm at send", "text"),
            ("Poly activities now", "text"),
            ("Same?", "text"),
            ("House fill (≥1)?", "text"),
            ("Note", "text"),
        ],
        [
            [
                "2026-10-24 13:42:46",
                "B T0",
                "Yes Alexander Guajardo",
                "BUY_LONG Yes Guajardo @ 0.47",
                "0.470",
                "IOC",
                "200",
                "0.02",
                "qty 0.0200 @ 0.4700 (not house fill) order D9ZCAFZ011KJ",
                "0.01 + 0.01 = 0.02 @ 0.47 aggressor D9ZCAFZ011KJ trades D9ZCAFZG71KN / D9ZCAFZG71KR",
                "Same",
                "No — real 0.02 ticket",
                "Book only had 0.02. Partial is a real venue ticket. Not a 1-contract T0 fill.",
            ],
            [
                "2026-10-24 13:42:46",
                "B T0",
                "Yes Lachlan Brain",
                "BUY_SHORT (buy No Guajardo / sell Yes) @ 0.46 = 1 − 0.54 Yes Brain ask",
                "0.460",
                "IOC",
                "200",
                "1",
                "qty 1.0000 @ 0.4600 order D9ZCDDRG11M3",
                "1.0000 @ 0.46 aggressor D9ZCDDRG11M3 trade D9ZCDDS091KN",
                "Same",
                "Yes",
                "Poly UI often labels this Sold Yes Guajardo (~0.54) or Bought No. House Yes Brain. price.value is the 0.46 No/short limit, not the 0.54 Yes ask.",
            ],
            [
                "2026-10-24 13:43:34",
                "B flatten",
                "Sell/unwind leftover Yes Brain",
                "not sent",
                "—",
                "would be IOC",
                "",
                "0",
                "skip flatten no takeable size (saw 0.2000)",
                "no flatten trade",
                "Same (nothing sent)",
                "No",
                "One-leg miss: Guajardo T0 was not a house fill. Flatten of the filled Brain Yes saw only 0.20 size, so B kept the Brain ticket.",
            ],
            [
                "2026-10-24 13:43:49",
                "B leftover-yes",
                "Yes Alexander Guajardo (retry missed T0)",
                "BUY_LONG Yes Guajardo @ 0.48",
                "0.480",
                "IOC",
                "200",
                "0.19",
                "activities GET empty; mismatch tape 0.19, using confirm 0. House note: IOC miss. Order D9ZCT3CG11KJ",
                "0.01 @ 0.47 + 0.18 @ 0.48 = 0.19 aggressor D9ZCT3CG11KJ trades D9ZCT3CGF1KQ / D9ZCT3CGH1KP",
                "Different at send; Poly now matches the HTTP tape",
                "No — real 0.19 ticket",
                "HTTP executions: PARTIALLY_FILLED cumQuantity 0.01 then 0.19, then EXPIRED. Confirm treated empty activities as a miss. That is the bug.",
            ],
        ],
    )
    systems = table(
        [
            ("System", "text"),
            ("On this match?", "text"),
            ("Evidence", "text"),
        ],
        [
            ["A lock Yes+No", "No", "No lock send / leftover-watch / skip-absorbed row. Tennis B latch left as-is."],
            ["B tennis crossover", "Yes", "strategy_b_watch tennis_guajarbrain_2026_10_24 stage one_leg_miss. Three Poly IOCs + one flatten skip."],
            ["C CFB favorite", "No", "College football only. cfb_favorite_watch has no Guajardo/Brain."],
            ["D T0 spreads", "No", "Moneyline tennis, not a spread. spread_t0_watch has no this match."],
        ],
    )
    pnl = table(
        [
            ("Book", "text"),
            ("Qty / side", "text"),
            ("Cash paid", "num"),
            ("Fee (C × θ × p × (1−p), banker’s cent)", "num"),
            ("Settles at 0.50 (void/push)", "num"),
            ("Net", "num"),
        ],
        [
            ["T0 Yes Guajardo", "0.02 @ 0.47", "0.0094", "0.00", "0.0100", "+0.0006"],
            ["Leftover Yes Guajardo", "0.01 @ 0.47 + 0.18 @ 0.48", "0.0911", "0.00", "0.0950", "+0.0039"],
            ["T0 Yes Brain (BUY_SHORT)", "1.00 @ 0.46 No cash", "0.4600", "0.02", "0.5000", "+0.0200"],
        ],
        ["Primary with fees", "0.21 Yes Guajardo + 1.00 Yes Brain", "0.5605", "0.02", "0.6050", "+0.0245"],
    )
    ui = table(
        [
            ("House label", "text"),
            ("What Poly US UI usually shows", "text"),
            ("Why it looks confusing", "text"),
        ],
        [
            [
                "Yes Guajardo BUY_LONG 0.47 / 0.48",
                "Bought Yes · Alexander Guajardo",
                "Small 0.02 and 0.19 sizes. House ≥1 filter hid leftover as a miss even though Poly lists the 0.19.",
            ],
            [
                "Yes Brain via BUY_SHORT 0.46",
                "Sold Yes Guajardo (about 0.54) or Bought No Guajardo. price.value on the wire is 0.46.",
                "Same binary market. Buying Brain Yes is selling Guajardo Yes. Not a second player market.",
            ],
            [
                "Watch: leftover Yes Guajardo IOC miss",
                "Two leftover trades totaling 0.19 Yes Guajardo still in history after 50¢ settlement",
                "Confirm GET empty at 13:43:49 ET. Poly history later has both leftover trades. Positions GET is empty after MARKET_STATE_EXPIRED settlement 0.50.",
            ],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guajardo vs Brain Poly — 24 Oct 2026</title>
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
<h1>Alexander Guajardo vs Lachlan Brain — Polymarket vs tape</h1>
<p class="note">Written {esc(now)}. Times America/New_York (EDT, UTC−4) on 2026-10-24. Research live. Not gold. Not DailyRun. No sells. No second Strategy B. No secrets. No Kalshi quotes on this page.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A Yes ticket pays $1 if that tennis player wins. Strategy B (tennis crossover) at the first trusted start (T0) tries to buy one Yes on each man if the two prices add up to something in the 95¢–$1.20 band. Size 1. Immediate or Cancel (fill now or cancel). If only one man fills, B tries to flatten that leftover, then one extra try to buy the missed man’s Yes. It does not buy the opponent’s No on the leftover watch (Goffin rule).</p>
<p>What we <strong>think</strong> we ordered, from the local tape before looking at Polymarket: at 13:42:46 ET, Yes Guajardo at 47¢ and Yes Brain at 54¢ (wired as buy-No / BUY_SHORT at 46¢) on Polymarket slug <code>aec-utr-guaale-bralac-2026-10-24</code>. C=1.01. Favorite Brain, dog Guajardo, from T0 Yes asks — not a Trungelliti invert. Guajardo only got 0.02 so it was not a house 1-contract fill. Brain filled 1. Flatten of Brain saw only 0.20 size, so it skipped. Then one leftover Yes Guajardo at 48¢. The watch said that leftover missed.</p>
<p>Polymarket’s official GET /v1/portfolio/activities (same fill-history the live bot uses after each POST) shows the same three order ids and the leftover 0.19 that the watch called a miss. The market later expired at a 50¢ settlement (void/push), so neither man paid $1.</p>
</div>

<div class="callout warn">
<h2>Verdict</h2>
<ul>
<li><strong>Same or different?</strong> T0 both tickets: <strong>same</strong> (0.02 Yes Guajardo, 1.00 Yes Brain). Leftover Yes Guajardo: <strong>different at send time</strong> — house used confirm 0 / “IOC miss”; HTTP tape and Poly history both have <strong>0.19</strong>. Not a wrong player. Not a false 1-contract fill. Not a duplicate 50-cross.</li>
<li><strong>What we ordered (B only):</strong> Yes Guajardo 0.47 IOC, Yes Brain 0.54 ask / 0.46 BUY_SHORT IOC, flatten skipped, leftover Yes Guajardo 0.48 IOC. Systems A, C, and D did not trade this match.</li>
<li><strong>What Poly has:</strong> five TRADE rows, three aggressor ids. 0.02 + 0.19 Yes Guajardo BUY_LONG, 1.00 BUY_SHORT Brain. Positions GET empty after 50¢ settlement (MARKET_STATE_EXPIRED, settlementPx 0.50 at 16:04 ET).</li>
<li><strong>Why leftover looked like a miss:</strong> confirm treated an empty activities GET as known qty 0 even though this order’s executions already showed PARTIALLY_FILLED cumQuantity 0.19. House fill is still qty ≥ 1, so T0 both-Yes never completed. Partial &lt; 1 is a real venue ticket.</li>
<li><strong>P&amp;L with fees:</strong> cash 0.5605 + 0.02 fee = 0.5805. 50¢ settlement pays 0.6050. Net about <strong>+$0.02</strong>. Not a winner/loser tennis payout.</li>
<li><strong>Fix:</strong> done (not gold, not DailyRun). If Poly activities are empty, use this order’s own <code>cumQuantity</code>. HTTP 200 with cumQuantity 0 is still not a fill. Replay tests added. Live B reloaded; PID {esc(b_pid)}. Did not flatten/sell this match. Did not start a second B.</li>
</ul>
</div>

<h2>We thought vs Poly said</h2>
<p class="note">Click column headers to sort. Match on order id / aggressor / trade id, not only the player name.</p>
{SWIPE_NOTE_HTML}
{compare}

<h2>Systems A / B / C / D</h2>
{SWIPE_NOTE_HTML}
{systems}

<h2>How Poly UI labels vs house Yes/No</h2>
{SWIPE_NOTE_HTML}
{ui}
<p>Screenshot-quality: one Polymarket US market, title Alexander Guajardo vs. Lachlan Brain, outcome Yes = Guajardo. House “Yes Brain” is the other seat of that same contract (No Guajardo). Poly’s activity list shows Sold Yes when we BUY_SHORT. The limit on that ticket is 0.46, which is 1 − the 0.54 Yes Brain ask B froze at T0. That is not the Trungelliti bug (both fill_px 0.41). Favorite/dog here stayed Brain / Guajardo from the Yes asks.</p>

<h2>Intended story</h2>
<p>T0 both-Yes: yes, that is what B sent. 50-cross extra dog: no, never armed (Guajardo never became a house fill, so extras never started). Favorite dip: no. Lock Yes+No: no (A did not send; B flatten of the Brain leftover did not send). Flatten: tried, skipped, no takeable size 0.20. We did not sell this match in this job.</p>

<h2>Primary P&amp;L with fees</h2>
<p class="note">θ = 0.0695 from the market feeCoefficient. Fee = θ × C × p × (1−p), banker’s cent. Settlement 0.50 on both seats (EVENT_TIER_1). Positions GET 0 rows after expiry.</p>
{SWIPE_NOTE_HTML}
{pnl}

<h2>Fix</h2>
<p><code>venue_fill_confirm.confirm_order</code>: when Polymarket activities are empty, take max <code>cumQuantity</code> on this order id from the IOC body. That leftover 0.19 is a partial, not an IOC miss. Nested book <code>qtyDecimal</code> is ignored so a 664-share book cannot look like a fill. HTTP 200 + cumQuantity 0 stays qty 0. Tests: <code>test_guajardo_leftover_empty_activities_uses_this_order_cumqty</code>, <code>test_guajardo_brain_leftover_empty_confirm_is_partial</code>. Live B reloaded via <code>prediction_job_control.reload_strategy_b</code> (one process). Lock / C / D pids left alone.</p>

<p class="note">Sources: Polymarket US GET /v1/portfolio/activities (5 TRADE rows, aggressor ids D9ZCAFZ011KJ / D9ZCDDRG11M3 / D9ZCT3CG11KJ), GET /v1/portfolio/positions (0, n_all 0), public book settlementPx 0.50 MARKET_STATE_EXPIRED; Kalshi fills 0; Gemini history 0 match; Novig fills 0. Local orders.jsonl, order_io.jsonl, strategy_b_watch.json, price_memory tennis ticks. Code: venue_fill_confirm.py, live_strategy_b.py. Pulled {esc(now)}. Status Checked {esc(checked)}. Live B PID {esc(b_pid)}.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print("wrote", PAGE)


if __name__ == "__main__":
    b_pid = ""
    checked = ""
    try:
        import prediction_job_control

        snap = prediction_job_control.snapshot()
        row = snap.get("strategy_b") or {}
        b_pid = str((row or {}).get("pid") or "")
        checked = str(snap.get("checked") or "")
    except Exception:
        pass
    main(b_pid=b_pid, checked=checked)
