"""B T0 one-leg: flatten-first vs retry. Kelm 41¢ confirm 0.

Research only. Does not sell, start a second B, commit, print secrets,
wire leftover GTC, or retune B C=1.05.
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
PAGE = STAMP / "b_flatten_vs_retry_kelm_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/b_flatten_vs_retry_kelm_20261026.html"
)

ASKED = (
    "Kelm Yes at 41¢ was accepted, then confirm 0 — that’s why we flattened. "
    "aren't we supposed to retry these? do we try it once and then flatten? "
    "what are the rules the code is using? have we run any tests that we could "
    "get a match if we wait n minutes. what percent of the time would that work?"
)

PLAIN = (
    "Tennis crossover (system B) tries to buy both players’ Yes at the start of "
    "the match, one contract each, Immediate-or-Cancel (IOC: take it now or the "
    "leftover dies). If Kalshi says “order created” (HTTP 201) but the fill "
    "history is empty (confirm 0), that Yes did not fill. The code does not rest "
    "that missed Yes, and it does not wait N minutes. As soon as it knows one "
    "Yes filled and the other missed, it dumps the filled Yes on the same shop "
    "(flatten: buy No / sell Yes). Only if that dump also misses does it leftover-"
    "watch the missed player’s Yes — one more IOC, then stop. Lock gap (system A) "
    "is a different bot: Yes+No on the same player across shops; it also dumps "
    "first, then leftover-watches a true hedge, and a one-leg miss now turns A "
    "off only."
)


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


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
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    cap = f'<p class="note">{esc(caption)}</p>' if caption else ""
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}{cap}"
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def write_html() -> Path:
    now = datetime.now(ET)
    rules = table(
        [("System", "text"), ("After one fill + other miss", "text"), ("Retry / wait", "text"), ("IOC vs GTC", "text"), ("Function", "text")],
        [
            [
                esc("B Tennis crossover"),
                esc(
                    "Flatten the filled Yes immediately (buy No on that same venue/ticker). "
                    "Do not hold a directional dog. If flatten fills: stage waiting_t0, "
                    "retry both-Yes only inside the 5-minute T0 window. If flatten misses: "
                    "leftover-watch the missed player’s Yes only — never opponent No."
                ),
                esc(
                    "Missed Yes is not retried before flatten. Empty Kalshi 201 / confirm 0 "
                    "is not repeated. Both-Yes miss (neither filled) increments t0_retries; "
                    "abandon after 3. Leftover Yes: one IOC the first time the rechecked ask "
                    "is in band; miss or partial marks that extra done — never another IOC "
                    "3s later. Kalshi shard 404 only: same limit up to 2 more times, 2s apart."
                ),
                esc("Kalshi/Gemini/Novig IOC. Polymarket Fill-or-Kill (FOK). No leftover GTC."),
                esc(
                    "mark_t0_results → flatten_t0_leg → live_lock_orders.flatten_filled_leg. "
                    "send_t0_both / send_yes_ioc. maybe_one_leg_yes. fire_t0 t0_retries>=3. "
                    "T0_GRACE_SEC=300. _post_same_limit shard retry."
                ),
            ],
            [
                esc("A Lock gap"),
                esc(
                    "Flatten-first the filled leg (same-shop opposite). If flatten fills: "
                    "flat, no leftover, latch not written. If flatten misses: leftover watch "
                    "a true hedge of the filled player (missed instrument / same-player No / "
                    "opponent Yes for dual-Yes). Never opponent-No of a Yes-dog leftover. "
                    "One-leg miss turns Lock gap (A) off only; leftover flatten/hedge still run; "
                    "B–E stay on."
                ),
                esc(
                    "Does not leftover-watch a directional dog before flatten. Zero-fill leftover "
                    "IOC marks that ticket done — no second leftover IOC. No clock cutoff on leftover "
                    "(runs until settle / hedge fill / Paul turns lock off)."
                ),
                esc("Live lock and flatten bodies stay IOC. GTC leftover HOLD, not wired."),
                esc(
                    "live_lock_orders._send_pair (hard-then-easy) → flatten_filled_leg. "
                    "_tick_single_watch / _send_watch_ioc. stop_orders sets lock.on false. "
                    "_send_blocked: B/C/D/E and leftover still post."
                ),
            ],
        ],
        "Shared helper: flatten_filled_leg in live_lock_orders.py. A and B both call it. "
        "Do not mix leftover-watch targets: A hedges the filled player; B leftover-watches the missed Yes only.",
    )

    kelm = table(
        [("Clock ET", "date"), ("What the code did", "text"), ("Tape", "text")],
        [
            [
                esc("14:34:32"),
                esc("B T0: recheck both Yes books, then ThreadPool both IOC. Not sequential hard-first (that is A)."),
                esc("Bobichon Yes ask 0.60 size 12. Kelm Yes ask 0.41 size 174. All-in C=1.0437 under freeze 1.05."),
            ],
            [
                esc("14:35:31"),
                esc("Kelm Yes HTTP 201, fill_count 0, fills GET empty → confirm 0. Code treats this as a miss, not a fill. Does not retry that IOC."),
                esc("Order 01a17458-a568-7b46-9326-22fbead76204. attempt=1. step=b-t0."),
            ],
            [
                esc("14:37:34"),
                esc("Nothing. B is still waiting for the other T0 thread. It does not rest GTC on Kelm and does not leftover-watch yet."),
                esc("Kalshi Kelm Yes ask printed 0.41 again (124s after the miss). Anecdote N=1, not a B study."),
            ],
            [
                esc("14:40:16"),
                esc("Bobichon Yes HTTP 201 confirm 1 @ 0.49 + fee 0.0175. mark_t0_results sees one fill + one miss and calls flatten_t0_leg immediately."),
                esc("Order 01a1745d-0680-77c7-820c-bf77357ab3df. Quote stamp was still 14:34:32. Ledger/page lock serialized the second HTTP."),
            ],
            [
                esc("14:41:16"),
                esc("Flatten book recheck, then IOC buy Bobichon No (Kalshi posts sell Yes). Not a Kelm retry."),
                esc("No ask quoted 0.51 size 10.10. POST ask 0.49."),
            ],
            [
                esc("14:46:03"),
                esc("Flatten HTTP 201 confirm 1. Stage waiting_t0. Will retry both-Yes only inside the 5-minute T0 window. Leftover-watch never armed (flatten filled)."),
                esc("Yes-wire 0.54 fee 0.0174; GET No 0.46. UI Sold Yes 52.26¢. All-in about +1.51¢ vs $1."),
            ],
            [
                esc("14:55:57"),
                esc("Next T0 look skipped t0_allin_c_over_105 fee unknown → abandoned. No second Kelm Yes IOC. t0_retries was never incremented (that counter is both-miss only)."),
                esc("strategy_b_watch.json stage=abandoned. one_leg_miss empty. leftover_ioc_sent unset. flattened=true on Bobichon."),
            ],
        ],
        "Try once then flatten: yes, for the missed Kelm Yes. The ~6 minutes is wait-for-the-other-HTTP plus flatten send lag, not a wait-N retry rule.",
    )

    tests = table(
        [
            ("Study", "text"),
            ("System", "text"),
            ("N", "num"),
            ("Hit% / result", "text"),
            ("Median wait", "text"),
            ("P&L with fees", "text"),
            ("Wired?", "text"),
        ],
        [
            [
                esc("Missed-leg GTC at the REST ask (lock_missed_leg_gtc_20261024.html, 24 Oct 20:48 ET)"),
                esc("A lock-bot one-legs only. Explicitly not Strategy B."),
                esc("15 / 32"),
                esc("46.9% later best-ask ≤ intended GTC limit before settle. 10/15 still a legal lock ≤0.984."),
                esc("82 seconds"),
                esc(
                    "Complementary GTC lock P&L on 13 hits: +92.25¢. On 11 rows that also have flatten/leftover P&L: GTC +50.42¢ vs actual leftover/flatten +161.43¢ (GTC − actual = −111.01¢)."
                ),
                esc("HOLD. Not wired. Cancel-on-resolve still missing."),
            ],
            [
                esc("Ask come-back, send-day (one_leg_miss_gtc_vs_flatten_20261023.html)"),
                esc("A lock-bot. Not B."),
                esc("13 / 27 known"),
                esc("48.1% of known. 1 unknown ticks."),
                esc("82 seconds (1.4 min)"),
                esc("Flatten 14 leftovers −40.90¢. Complementary GTC on 7 come-backs +60.52¢. Both-P&L rows n=2, GTC−flatten +17.83¢."),
                esc("HOLD. Not wired."),
            ],
            [
                esc("Flatten-first vs hold-to-settle (flatten_rule_and_tape_20261024.html)"),
                esc("A lock-bot. B T0-flatten rows excluded from that book."),
                esc("15 flatten fills / 32 one-legs"),
                esc("Flatten round-trip win% 13.3%. HOLD — Paul chooses."),
                esc("—"),
                esc(
                    "Flatten fills net −$0.61. Hold-to-settle those leftovers (N=27 known winners) +$1.84. Booked leftover (flatten dumped + leftover held) +$2.19."
                ),
                esc("HOLD flatten-first as live. Did not wire wait-N or GTC."),
            ],
            [
                esc("Leftover vs GTC dollars (same lock GTC page overlap)"),
                esc("A lock-bot."),
                esc("11 rows with both P&L"),
                esc("DISMISS leftover-GTC as a wire: leftover/actual +$1.61 beat hypothetical GTC +$0.50 on the overlap. Booked leftover +$2.19 vs complementary GTC +$0.92 on 13 hits."),
                esc("median 82s on GTC hits"),
                esc("See lock_missed_leg_gtc_20261024.html headline."),
                esc("HOLD GTC. Live leftover stays one IOC after flatten miss."),
            ],
            [
                esc("B T0 second-Yes retry / wait N minutes"),
                esc("B Tennis crossover"),
                esc("No study"),
                esc(
                    "Does not exist. GTC/flatten pages skip tennis-b keys. Tape count of B T0 pairs (quote-grouped, not a horse-race): 28 both-fill, 6 one-leg, 17 both-empty. Empty Kalshi 201 confirm 0 in that one-leg list includes Cobolli, Kelm, Del Pino. No wait-N hit% on those."
                ),
                esc("—"),
                esc("Not computed. Kelm flatten all-in about +1.51¢ vs $1 (fees from POST average_fee_paid)."),
                esc("Not wired. Do not invent a B hit%."),
            ],
            [
                esc("Kelm 41¢ ask after the miss (anecdote)"),
                esc("B, this one match"),
                esc("1"),
                esc("Kalshi Kelm Yes best-ask printed 0.41 again 124s after confirm 0 (14:37:34). Later min ask 0.01 (absorb). Not a percent."),
                esc("124 seconds"),
                esc("Not scored as a GTC P&L. Flatten already closed Bobichon."),
                esc("Not a wire. N=1."),
            ],
        ],
        "Click column headers to sort. Wait-N / GTC hit% we actually measured is lock A, not B.",
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
{report_page_extras.CACHE_META}
{report_page_extras.FORCE_RELOAD_SCRIPT}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>B flatten vs retry — Kelm 26 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.hold {{ background: #eef2ff; border-color: #a5b4fc; }}
.note {{ color: #475569; font-size: 14px; }}
.hl {{ font-size: 1.12rem; }}
ul {{ margin-top: 0.3rem; }}
code {{ font-size: 0.9em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>B: try once then flatten — Kelm Yes 41¢ confirm 0</h1>
<p class="note">Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. America/New_York. Research only. Not gold. Not DailyRun. Did not sell. Did not start a second Tennis crossover. Did not wire leftover GTC. Did not retune C=1.05. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout ok">
<h2>Headline</h2>
<p class="hl"><strong>B tries the missed Yes once (IOC), then flattens the filled Yes. It does not wait N minutes for Kelm 41¢ to come back.</strong> Kelm HTTP 201 + confirm 0 is an empty cancel. That is not retried. Flatten is immediate after both T0 results are known. The ~6 minutes on this match is the other HTTP plus flatten send lag, not a retry clock.</p>
</div>

<div class="callout hold">
<h2>HOLD</h2>
<p>Leftover GTC stays HOLD, not wired (cancel-on-resolve still missing). B all-in C = $1.05 stays. This page does not change live flatten. A leftover rule is flatten-first then leftover watch; a one-leg miss turns A off only — do not mix that with B’s missed-Yes leftover.</p>
</div>

<h2>Exact B rule after T0 one-leg fill + other Yes miss</h2>
<ol>
<li><code>send_t0_both</code>: recheck both Yes books; if either book fails the gate, send neither. Else ThreadPool two <code>send_yes_ioc</code> (Kalshi IOC / Poly FOK).</li>
<li>Venue confirm is fill truth. Kalshi HTTP 201 with <code>fill_count</code> 0 / empty fills GET is confirm 0: not a fill (<code>filled_contracts</code> / <code>send_yes_ioc</code>).</li>
<li><code>mark_t0_results</code>: two fills → wait 50-cross. One fill → <code>flatten_t0_leg</code> immediately (buy No on the filled Yes ticker). Zero fills → <code>t0_retries += 1</code>, stay in the T0 window; abandon after 3 both-misses (<code>fire_t0</code>).</li>
<li>Flatten fills → stage <code>waiting_t0</code>, “retry both-Yes in the T0 window” (5 minutes from trusted actual start, <code>T0_GRACE_SEC=300</code>). That retry is both Yes again, not “rest Kelm at 41¢.” Flatten miss → stage <code>one_leg_miss</code>, leftover-watch the missed Yes only (<code>maybe_one_leg_yes</code>): one IOC, then stop.</li>
<li>Extras (50-cross / fav dip): one IOC each; miss or partial is done. No leftover-retry on extras.</li>
</ol>
<p class="note">Shard-404 retry (up to two extra posts, 2 seconds apart) is only for Kalshi “Exchange user not found” / insufficient shard. A normal 201 with nothing filled is not repeated.</p>

{rules}

<h2>What happened on Kelm vs those rules</h2>
{kelm}

<p>So: <strong>try the second Yes once, then flatten</strong>. Logs show Kelm <code>attempt=1</code> only. No leftover Yes IOC. No GTC. After flatten filled, B did not fire another Kelm 41¢. The later 14:55 skip is C over / fee unknown, then abandoned.</p>

<h2>A leftover, one line</h2>
<p>Lock gap (A): if the easy lock leg misses, dump the filled leg on that same shop first; only if that dump also misses, leftover-watch a true hedge; a one-leg miss turns A off only (B–E stay on). <a href="lock_oneleg_off_a_only_20261026.html">lock_oneleg_off_a_only_20261026.html</a>.</p>

<h2>Wait N minutes — what we actually measured</h2>
{tests}

<p>If you wait N minutes for a missed REST ask to come back, the number we have is <strong>lock A: 15 of 32 = 47%, median 82 seconds</strong>, HOLD not wired. There is no B T0 second-Yes wait-N hit rate. Kelm’s own book printed 41¢ again in 124 seconds on this one match; that is N=1, not a percent we would wire from.</p>

<h2>What this page did not do</h2>
<ul>
<li>Did not rest or wire leftover GTC.</li>
<li>Did not retune C=1.05.</li>
<li>Did not sell, start a second B, or commit.</li>
<li>Did not overwrite sibling HTML (A legs unblock; persist real fees).</li>
</ul>
<p class="note">Sources: <code>tools/live_strategy_b.py</code> (<code>mark_t0_results</code>, <code>flatten_t0_leg</code>, <code>maybe_one_leg_yes</code>, <code>fire_t0</code>, <code>send_t0_both</code>), <code>tools/live_lock_orders.py</code> (<code>flatten_filled_leg</code>, leftover watch, shard retry, confirm 0), local <code>orders.jsonl</code> / <code>strategy_b_watch.json</code> / <code>price_memory</code> 25 Oct tennis. Prior: <a href="bobichon_kelm_venue_reconcile_20261026.html">bobichon_kelm_venue_reconcile_20261026.html</a>, <a href="lock_missed_leg_gtc_20261024.html">lock_missed_leg_gtc_20261024.html</a>, <a href="flatten_rule_and_tape_20261024.html">flatten_rule_and_tape_20261024.html</a>, <a href="one_leg_miss_gtc_vs_flatten_20261023.html">one_leg_miss_gtc_vs_flatten_20261023.html</a>. File URL {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    return PAGE


if __name__ == "__main__":
    write_html()
