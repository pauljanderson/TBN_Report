"""Ten tennis-match autopsy for Paul. Research HTML. Does not sell or start B."""
from __future__ import annotations

import html as html_lib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "tennis_ten_match_autopsy_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tennis_ten_match_autopsy_20261026.html"
)
ASKED = (
    "Paul: “walk me through what you mean by these?” then pastes the autopsy table "
    "header (Match, T0 ET, Intended, Filled, Missed, Verdict) plus the Bobichon vs Kelm "
    "row. “explain everything in laymen's terms.” Earlier autopsy ask still on this page: "
    "for each of these matches, tell him (1) intended system, (2) orders placed and filled, "
    "(3) tried and not filled, (4) what went right, what went wrong, (5) what if anything we "
    "should change. Matches (Bobichon vs Kelm listed twice — one section): Matisse Bobichon "
    "vs. Yannik Kelm; Zane Stevens vs. Eric Tripathi; Enzo Lima vs. Bruno Vieira Alves "
    "Malacarne Bruno; Tom Paris vs. Romain Faucon; Patricio Llanes Echavarria vs. Edgar "
    "Hipolito Cruz Vazquez; Uchijima vs Mertens; Trotter vs Svajda; Baris vs Heck; Bobichon "
    "vs Kelm (same as first); Del Pino vs Leite."
)
PLAIN = (
    "Paul wanted the table columns and the Bobichon vs Kelm row in kitchen English, not "
    "trader shorthand. Kitchen walkthrough is the yellow box under this. The rest of the "
    "page still replays nine unique tennis matches (Bobichon vs Kelm is one section, not two): "
    "which bot was supposed to act, which tickets actually filled, which tries missed, and "
    "whether we should change anything. T0 is the trusted match-start snapshot. Fill-or-kill "
    "(FOK) is Polymarket’s all-or-nothing order; immediate-or-cancel (IOC) is Kalshi’s "
    "take-what-you-can-now order. Fill-history confirm is truth: a Polymarket HTTP 200 is not "
    "a fill by itself, an empty activities list must not wipe a this-order filled quantity, "
    "and an empty positions list must not drop a confirmed fill while the market is still open. "
    "We did not sell tickets, did not start a second Tennis crossover, did not bump stake, and "
    "did not retune B’s all-in C=$1.05 from this horse-race."
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


OH = [
    ("Time ET", "date"),
    ("System", "text"),
    ("Step", "text"),
    ("Venue", "text"),
    ("Side / player", "text"),
    ("Limit", "num"),
    ("TIF", "text"),
    ("HTTP", "num"),
    ("Confirm qty", "num"),
    ("Fill px", "num"),
    ("Fee", "num"),
    ("After-fee", "num"),
    ("Confirm note", "text"),
    ("Order id", "text"),
]

SYS = [
    ("System", "text"),
    ("Considered?", "text"),
    ("Skip / send", "text"),
]


def write_page() -> Path:
    summary = table(
        [
            ("Match", "text"),
            ("T0 ET", "date"),
            ("Intended", "text"),
            ("Filled", "text"),
            ("Missed", "text"),
            ("Verdict", "text"),
        ],
        [
            [
                esc("Bobichon vs Kelm"),
                esc("2026-10-25 14:30 occurrence"),
                esc("B then A"),
                esc("B: Kalshi Bobichon Yes 1 @ 0.49 fee 0.0175 (UI 50.75¢), flatten ask/sell Yes 0.54 fee 0.0174 (No 0.46; UI 52.26¢). A: Poly Yes 1 @ 0.26+$0.01 + Kalshi No 1 @ 0.49 fee 0.0175 (Sold Yes 49.25¢)"),
                esc("B Kelm Yes bid 0.41 HTTP 201 confirm 0"),
                esc("Right / HOLD — fees corrected; see bobichon_kelm_venue_reconcile_20261026.html"),
            ],
            [
                esc("Stevens vs Tripathi"),
                esc("2026-10-25 19:00 listed"),
                esc("B"),
                esc("Poly both T0 Yes 1 @ 0.84 and No/Tripathi 1 @ 0.83"),
                esc("None on this match"),
                esc("Right / HOLD"),
            ],
            [
                esc("Lima vs Bruno"),
                esc("2026-10-25 08:30 listed"),
                esc("B"),
                esc("Poly T0 both 1 @ 0.71 / 0.70. Cross 0.09 FOK partial (not a house 1)"),
                esc("First T0 size skip; 50-cross C=1.61 skip; 0.09 not treated as 1"),
                esc("Right / HOLD"),
            ],
            [
                esc("Paris vs Faucon"),
                esc("2026-10-25 11:30 listed"),
                esc("A leftover (B skipped)"),
                esc("Poly hard No 1 @ 0.77"),
                esc("Easy Kalshi not sent (gap closed). Flatten HTTP not on orders.jsonl"),
                esc("HOLD — leftover flatten tape gap"),
            ],
            [
                esc("Llanes vs Vazquez"),
                esc("2026-10-25 12:00 listed"),
                esc("B"),
                esc("Poly both T0 1 @ 0.74 / 0.74"),
                esc("First T0 size skip 0.14"),
                esc("Right / HOLD (postponed)"),
            ],
            [
                esc("Uchijima vs Mertens"),
                esc("2026-10-25 23:55 listed"),
                esc("A (B skipped)"),
                esc("Kalshi No Mertens 1 @ 0.17, flatten Yes 1 @ 0.85"),
                esc("Easy Poly size 0.50; B Novig fee unknown"),
                esc("Right / HOLD"),
            ],
            [
                esc("Trotter vs Svajda"),
                esc("2026-10-25 16:30 listed"),
                esc("A leftover (B skipped)"),
                esc("Kalshi No Trotter 1 @ 0.28"),
                esc("Easy Poly not sent; flatten Yes 0.79 confirm 0; leftover asks too high"),
                esc("Right / HOLD"),
            ],
            [
                esc("Baris vs Heck"),
                esc("2026-10-25 18:40 occurrence"),
                esc("A then B"),
                esc("None (fill-history)"),
                esc("A Poly hard miss; B Kalshi both confirm 0 (Heck tape 1.00 vs GET empty)"),
                esc("Right / HOLD"),
            ],
            [
                esc("Del Pino vs Leite"),
                esc("2026-10-25 15:10 occurrence"),
                esc("A miss, then B"),
                esc("B Kalshi Leite Yes 1 @ 0.46, leftover Del Yes 1 @ 0.69"),
                esc("A Poly hard confirm 0; B T0 Del miss; flatten Leite No miss"),
                esc("Right / HOLD (postponed)"),
            ],
        ],
        "Click column headers to sort. Nine unique matches; Bobichon vs Kelm is one row.",
    )

    sections = [
        _bobichon(),
        _stevens(),
        _lima(),
        _paris(),
        _llanes(),
        _uchijima(),
        _trotter(),
        _baris(),
        _delpino(),
    ]
    body = f"""
<h1>Ten tennis matches — autopsy 26 Oct 2026</h1>
<p class="tiny">Stamp drive/paul_experiments/prediction_market_arb_exhaustive_20261017/. Tape: orders.jsonl, order_io.jsonl, strategy_b_watch.json, leftover_watch_stats.jsonl, live_supervisor.log. Fill-history confirm is truth. {esc(FILE_URL)}</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
{_kitchen()}
<h2>Freeze (not retuned from this page)</h2>
<p class="note">A lock gap — Yes one venue + No other, same settlement, sequential hard-first, net ≤ 0.99 after fees, leftover flatten-first then leftover watch; one-leg now turns A off only. B tennis crossover — T0 both-Yes in (0.10, 0.90), all-in C ≤ $1.05; 50-cross only if T0 fav Yes strictly below dog Yes AND all-in ≤ 1.05; D=0.25 extra-Yes DISMISS; Poly FOK; skip E if B on match. C college-football favorite only — skip tennis. D T0 spreads — skip tennis / NFL skip. E tennis T0 dog — unique lower Yes in (0.10, 0.50) at T0, skip if B already on match.</p>
<h2>All nine (sortable)</h2>
{summary}
<h2>What we should change</h2>
<ul>
<li><strong>HOLD B all-in C = $1.05.</strong> Several skips were C over 1.05 or Novig fee unknown. This page is not a horse-race to move that gate. Bobichon T0 send C=1.0437 was under the freeze.</li>
<li><strong>HOLD stake, HOLD second B, HOLD D NFL, do not turn systems off, do not sell.</strong></li>
<li><strong>Bobichon vs Kelm Kalshi fees:</strong> autopsy after-fee had been fill px with fee 0. Venue POST <code>average_fee_paid</code> is 0.0175 / 0.0174 / 0.0175. Numbers on this match and on <a href="bobichon_kelm_venue_reconcile_20261026.html">bobichon_kelm_venue_reconcile_20261026.html</a> are corrected. Live <code>fee_returned</code> still does not read <code>average_fee_paid</code> — not wired this job.</li>
<li><strong>More A locks:</strong> HOLD leftover GTC (15/32 = 46.9%, cancel-on-resolve missing). HOLD dual-simultaneous for A (already hard-first). Frozen try, not wired: do not rebuild orders.html between the hard IOC and the easy IOC (this row sat ~2 min). Do not claim we can guarantee fills. Tiny N=1.</li>
<li><strong>Paris leftover flatten HTTP is missing from orders.jsonl</strong> after supervisor logged “flatten hard, easy not sent.” leftover_watch_stats.jsonl has no Paris rows. Research: confirm whether leftover actually armed. If it never posted flatten and never watched, that is a lock leftover-arm gap to fix in A — not a B retune. We did not sell the Poly No.</li>
<li><strong>Baris Heck Kalshi tape fill_count 1.00 vs fills GET empty:</strong> confirm 0 was used (fill-history truth). Same class as “empty Poly activities must not override cumQuantity,” but Kalshi GET empty is the fill-history. HOLD unless a later fills GET shows qty ≥ 1 on order 01a1753b-1df8-7aaf-b94a-4717a2dfe800.</li>
<li><strong>E tennis T0 dog</strong> was on, but tennis_t0_dog.log is starts plus PermissionError loops; watch skipped[] is empty. Do not claim E considered these names. Ops file-lock, not a knob change.</li>
<li><strong>Lima 0.09:</strong> Poly FOK still returned a 0.09 cumQuantity. Wired path: not a house 1-contract, not flatten as 1, cancel remainder if still open. HOLD. Do not treat it as a dropped 1-fill.</li>
</ul>
{"".join(sections)}
<p class="tiny">Written {esc(datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"))}. Research only. Not gold. Not DailyRun.</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ten tennis match autopsy 26 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
h3 {{ font-size: 1.02rem; margin: 1.1rem 0 0.35rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 14px; }}
.callout h2 {{ margin: 0 0 6px; }}
.kitchen {{ background: #fffbeb; border: 1px solid #fcd34d; padding: 12px 14px; margin: 0 0 16px; }}
.kitchen h2 {{ margin: 0 0 8px; }}
.kitchen h3 {{ margin: 1rem 0 0.4rem; }}
.kitchen dt {{ font-weight: 600; margin-top: 0.45rem; }}
.kitchen dd {{ margin: 0.15rem 0 0.55rem 0; }}
.kitchen ol {{ padding-left: 1.2rem; }}
.kitchen li {{ margin: 0.35rem 0; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
.verdict {{ background: #f0fdf4; border: 1px solid #86efac; padding: 10px 12px; margin: 8px 0 16px; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 10px 12px; margin: 8px 0 16px; }}
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


def _sys_rows(rows: list[list[str]]) -> str:
    return table(SYS, rows, "Which systems looked. C and D skip tennis by freeze.")


def _ord(rows: list[list[str]], caption: str) -> str:
    return table(OH, rows, caption)


def _kitchen() -> str:
    return """
<div class="kitchen" id="kitchen">
<h2>In kitchen English</h2>
<p>Paul asked what the table columns mean, then what the Bobichon vs Kelm row actually did. Later he pasted Kalshi + Polymarket screenshots — map and fees are on <a href="bobichon_kelm_venue_reconcile_20261026.html">bobichon_kelm_venue_reconcile_20261026.html</a>. No invented fills. Fills below are orders.jsonl confirm plus Kalshi POST <code>average_fee_paid</code> from order_io. The 22 Oct venue fill-history pull does not contain these 25 Oct order ids.</p>

<h3>What each column means</h3>
<dl>
<dt>Match</dt>
<dd>Which tennis match this row is about. Two players play. Shops sell tickets on who wins.</dd>
<dt>T0 ET</dt>
<dd>Eastern Time of the first trusted start clock we use. <strong>Occurrence</strong> means Kalshi’s first-serve / match-actually-starting time, not the poster time on the listing. For this row that clock is 25 Oct 2026, 14:30 ET (listed start was 13:45; an old 05:09 label on the watch is a stale tape-resume stamp, not the T0 we used).</dd>
<dt>Intended</dt>
<dd>Which bot was supposed to try, in order. <strong>B then A</strong> means Tennis crossover (System B) goes first at T0; Lock gap (System A) may try later only if the frozen rules still allow it.</dd>
<dt>Filled</dt>
<dd>Tickets we actually own. Count comes from fill-history (the shop’s “what did you buy” list, or this-order filled quantity), not from a polite “order accepted” ping. Qty 1 means one $1 ticket. Prices are dollars: 0.49 is 49¢.</dd>
<dt>Missed</dt>
<dd>We sent an order. The shop took the request. Fill-history quantity is 0, so we do not own that ticket. <strong>Confirm 0</strong> = order went out, fill-history qty 0.</dd>
<dt>Verdict — Right / HOLD</dt>
<dd>The tape did what the frozen rules said. <strong>HOLD</strong> means do not retune B’s $1.05 all-in cap from this row. Do not bump stake, do not start a second Tennis crossover, do not sell, do not wire D on NFL from this.</dd>
</dl>

<h3>The two bots, in kitchen English</h3>
<p>Imagine two tennis players. Shops sell “Bobichon wins” (Yes), “Kelm wins” (Yes), or the No of either (pays if that player loses).</p>
<ol>
<li><strong>System B — Tennis crossover.</strong> At T0 it tries to buy <em>both</em> Yes tickets if they add up to <strong>$1.05 or less after fees</strong> (that sum is all-in C). One of them must win, so paying ≤ $1.05 for two $1 tickets is the B idea. Band: each Yes in (10¢, 90¢).</li>
<li><strong>System A — Lock gap.</strong> It buys Yes on one shop and No on the other shop for the <em>same</em> player, after-fee ≤ $0.99, so one side must pay $1. Hard leg first, then the easy leg.</li>
</ol>

<h3>Bobichon vs Kelm as a story (25 Oct 2026, Eastern)</h3>
<ol>
<li><strong>Morning.</strong> B looked and skipped: all-in C over $1.05, or Novig fee unknown. That skip is the freeze, not a bug.</li>
<li><strong>After 14:05 local-cash reload.</strong> B opened the match at 14:22. Occurrence clock 14:30. All-in C at the send that counted: 1.0437 (under the $1.05 cap).</li>
<li><strong>14:34:32 — B tries both Yes on Kalshi.</strong> Quote stamp is 14:34:32. Kelm HTTP 201 at <strong>14:35:31</strong> bid 41¢ fill_count 0.00, fills GET empty, <strong>confirm 0</strong> (order 01a17458-a568-7b46-9326-22fbead76204). Bobichon HTTP 201 at <strong>14:40:16</strong> (Kalshi Created; our quote stamp was 14:34:32) bid 60¢ filled <strong>Yes 1 @ 49¢ + fee 1.75¢ = 50.75¢</strong> (POST average_fee_paid 0.0175, order 01a1745d-0680-77c7-820c-bf77357ab3df). That 50.75 is Kalshi’s after-fee avg — the old after-fee column that printed 0.49 missed the fee.</li>
<li><strong>14:46:03 — flatten, not a Kelm hedge.</strong> B still held leftover Bobichon Yes. Flatten buys Bobichon <em>No</em> on the same ticker, which Kalshi posts as <code>side=ask</code> (sell Yes). Quote stamp 14:41:16; HTTP 14:46:03. POST Yes-wire <strong>54¢ + fee 1.74¢</strong>; GET No 46¢; UI Sold Yes avg <strong>52.26¢</strong> = 54 − 1.74 (order 01a17462-51f8-7a90-bd57-e1ab3ad79b23). Wire 49+46=95¢ looked like +5¢; all-in 50.75+47.74=98.49¢ → about <strong>+1.51¢</strong>. Not break-even, not negative.</li>
<li><strong>Why A was allowed after B — tape, not a guess.</strong> Skip-absorbed-B (gloss: A must not hunt a tennis match B still holds, including absorbed T0) logs as “Tennis crossover has this tennis match open.” After flatten, B’s own note is one-leg flattened, not holding directional. At 14:55 B retried T0 and skipped <code>t0_allin_c_over_105</code> fee unknown; watch stage became <strong>abandoned</strong>. Abandoned is not in the skip-absorbed-B open list. <code>live_supervisor.log</code> for Bobichon vs Kelm has <strong>zero</strong> “Tennis crossover has this tennis match open” lines. Contrast Del Pino vs Leite, where B still held leftover-Yes and A <em>did</em> skip that way. First A look after flatten is 15:06: claim then skip over cap (net 1.11) — A was hunting, not blocked by B.</li>
<li><strong>15:30 then 15:33 — A’s true lock on Bobichon.</strong> Hard HTTP 15:30:03: Polymarket Bobichon Yes 1 @ 26¢ + $0.01 = $0.27 (UI 3:30 PM; order DANGJ0Y011MV). Easy HTTP 15:33:00: Kalshi POST ask 34¢ (sell Yes = buy No at 66¢), filled Yes-wire 51¢ + fee 1.75¢; GET No 49¢; UI Sold Yes 49.25¢ (order 01a1748d-4de0-70ae-ae4c-3ea62b42ef50). ~2 min is hard-then-easy plus page rebuild, not a resting GTC. All-in 27¢ + 50.75¢ = 77.75¢ vs $1 → about <strong>+22.25¢</strong> (Paul’s 23.75¢ added the 49.25 sell avg as if it were the No debit). Settlement file for 25 Oct was not in the 22 Oct fill-history pull.</li>
<li><strong>After that.</strong> Later A claims 15:37–15:58 skipped over cap (nets 1.00–1.11) or duplicate. No second lock send. Watch skip_reason <code>t0_allin_c_over_105</code> after the flatten is a stale display, not a second B send.</li>
</ol>

<h3>What went right</h3>
<p>B did not count a Kelm ticket it did not get. Flatten closed the leftover Yes instead of sitting naked on Bobichon. A then locked Bobichon because B was no longer holding — flatten already closed B, then abandoned — not because we turned skip-absorbed-B off. Empty Polymarket activities did not wipe the qty-1 fill. Kalshi portfolio “No Bobichon” 1 @ 50.75¢ is the A lock’s No, not a leftover B Yes. <strong>HOLD</strong> = do not move B’s $1.05 all-in cap from this row. Venue screenshot map: <a href="bobichon_kelm_venue_reconcile_20261026.html">bobichon_kelm_venue_reconcile_20261026.html</a>.</p>
</div>
"""


def _bobichon() -> str:
    sys_t = _sys_rows(
        [
            [esc("B tennis crossover"), esc("Yes"), esc("Morning t0_allin_c_over_105 (C=1.06 / Novig fee unknown). After 14:05 local-cash reload, T0 quote 14:34 ET. Kelm Yes bid 0.41 HTTP 14:35:31 confirm 0. Bobichon Yes HTTP 14:40:16. Flatten ask/sell Yes HTTP 14:46:03.")],
            [esc("A lock gap"), esc("Yes"), esc("15:29 hard Poly Yes then easy Kalshi No, both confirm qty 1. Later claims over cap / duplicate.")],
            [esc("C CFB fav"), esc("No"), esc("Skip tennis")],
            [esc("D T0 spreads"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Should skip"), esc("B already on match after 14:34. E watch skipped[] empty; log PermissionError.")],
        ]
    )
    orders = _ord(
        [
            [esc("14:40:16"), esc("B"), esc("b-t0"), esc("Kalshi"), esc("Yes / Matisse Bobichon (POST bid)"), esc("0.6000"), esc("IOC"), esc("201"), esc("1.00"), esc("0.4900"), esc("0.0175"), esc("0.5075"), esc("POST average_fill_price 0.4900 average_fee_paid 0.0175; UI Bought Yes 50.75¢ Created 14:40:16; quote stamp 14:34:32"), esc("01a1745d-0680-77c7-820c-bf77357ab3df")],
            [esc("14:35:31"), esc("B"), esc("b-t0"), esc("Kalshi"), esc("Yes / Yannik Kelm (POST bid)"), esc("0.4100"), esc("IOC"), esc("201"), esc("0"), esc(""), esc(""), esc(""), esc("POST fill_count 0.00; fills GET empty; book 0.41 size 174 at 14:34:32"), esc("01a17458-a568-7b46-9326-22fbead76204")],
            [esc("14:46:03"), esc("B"), esc("flatten"), esc("Kalshi"), esc("ask/sell Yes = No / Bobichon"), esc("0.4900"), esc("IOC"), esc("201"), esc("1.00"), esc("0.4600"), esc("0.0174"), esc("0.4774"), esc("POST side=ask Yes-wire 0.5400 fee 0.0174; GET No 0.4600; UI Sold Yes 52.26¢ Limit 49¢; quote stamp 14:41:16"), esc("01a17462-51f8-7a90-bd57-e1ab3ad79b23")],
            [esc("15:30:03"), esc("A"), esc("hard"), esc("Polymarket"), esc("Yes / Bobichon"), esc("0.290"), esc("FOK"), esc("200"), esc("1"), esc("0.2600"), esc("0.01"), esc("0.2700"), esc("UI $0.27 @ 26% 3:30 PM; activities GET empty; this-order cumQuantity 1 @ 0.2600; quote stamp 15:29:33"), esc("DANGJ0Y011MV")],
            [esc("15:33:00"), esc("A"), esc("easy"), esc("Kalshi"), esc("ask/sell Yes = No / Bobichon"), esc("0.3400"), esc("IOC"), esc("201"), esc("1.00"), esc("0.4900"), esc("0.0175"), esc("0.5075"), esc("POST side=ask Yes-wire 0.5100 fee 0.0175; GET No 0.4900; UI Sold Yes 49.25¢ Limit 34¢; quote stamp 15:31:23"), esc("01a1748d-4de0-70ae-ae4c-3ea62b42ef50")],
        ],
        "HTTP orders. TIF: Poly FOK requested; Kalshi IOC. Times in the first column are Kalshi/Poly Created (HTTP), not the quote stamp. Fees are POST average_fee_paid. Empty Poly activities did not override cumQuantity 1.",
    )
    return f"""
<h2 id="bobichon">Matisse Bobichon vs. Yannik Kelm</h2>
<p class="note">Listed twice in the ask — one section. T0 ET: Kalshi occurrence <strong>14:30</strong> 25 Oct 2026 (listed 13:45; watch also stored a stale 05:09 tape-resume label). B opened 14:22 after the 14:05 local-cash reload. All-in C at send 1.0437. Kitchen-English walkthrough of this row is <a href="#kitchen">at the top</a>.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>B Kelm Yes bid 0.41, HTTP 201 at 14:35:31, fill_count 0.00, confirm 0. That 41¢ is the price we could not get. A later lock claims 15:06–15:58 skipped over cap (nets 1.00–1.11) or duplicate.</p>
<h3>P&amp;L with fees</h3>
<p>B closed: wire 0.49 + 0.46 = 0.95 looked like +5¢; POST fees 0.0175 + 0.0174 → all-in 0.9849 vs $1 Yes+No on the same ticker → about <strong>+1.51¢</strong> (UI 50.75 buy vs 52.26 sell). A lock: Poly 0.27 + Kalshi No all-in 0.5075 = 0.7775 vs $1 → about <strong>+22.25¢</strong> (Paul 23.75¢ added Sold Yes 49.25 as the No cost; old autopsy ~24¢ skipped the Kalshi fee). Venue settlement file for 25 Oct was not in the 22 Oct fill-history pull. Screenshot map: <a href="bobichon_kelm_venue_reconcile_20261026.html">bobichon_kelm_venue_reconcile_20261026.html</a>.</p>
<div class="verdict"><strong>Right / HOLD.</strong> B flatten after Kelm miss worked. A both-leg lock worked. Fees now from POST average_fee_paid. Empty Poly activities kept cumQuantity 1. Do not retune C=1.05. Do not claim we can guarantee more A fills.</div>
"""


def _stevens() -> str:
    sys_t = _sys_rows(
        [
            [esc("B tennis crossover"), esc("Yes"), esc("T0 send 19:04, all-in C=1.03, stack stop all-in ≥ $1. Absorbed both-Yes. No extras.")],
            [esc("A lock gap"), esc("No send"), esc("No claim/sent on this moneyline in orders.jsonl")],
            [esc("C / D"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Should skip"), esc("B absorbed on match")],
        ]
    )
    orders = _ord(
        [
            [esc("19:04:01"), esc("B"), esc("b-t0"), esc("Polymarket"), esc("Yes / Zane Stevens"), esc("0.840"), esc("FOK"), esc("200"), esc("1"), esc("0.8400"), esc("0.01"), esc("0.8500"), esc("activities GET empty; this-order cumQuantity 1 @ 0.8400"), esc("DARJX8T011TB")],
            [esc("19:04:01"), esc("B"), esc("b-t0"), esc("Polymarket"), esc("No / Eric Tripathi"), esc("0.830"), esc("FOK"), esc("200"), esc("1"), esc("0.8300"), esc("0.01"), esc("0.8400"), esc("activities GET empty; this-order cumQuantity 1 @ 0.8300"), esc("DARJXAMG11R3")],
        ],
        "Not Barry-Sato vs Stevens-Thompson (23 Oct, different match).",
    )
    return f"""
<h2 id="stevens">Zane Stevens vs. Eric Tripathi</h2>
<p class="note">T0 ET: listed/feed <strong>19:00</strong> 25 Oct 2026. Yes 0.84 / 0.17, all-in C=1.03.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>None on this match. HTTP 200 plus empty activities would have been a false miss if we had dropped cumQuantity; we kept qty 1 on both legs.</p>
<h3>P&amp;L with fees</h3>
<p>Both-Yes cash about 0.84+0.01 + 0.17 equivalent (No fill 0.83) + 0.01 = 1.03. Absorbed; hold to settlement. Winner not in the 22 Oct venue fill-history pull.</p>
<div class="verdict"><strong>Right / HOLD.</strong> Empty Poly activities did not override cumQuantity. No extras, as freeze when no legal 50-cross.</div>
"""


def _lima() -> str:
    sys_t = _sys_rows(
        [
            [esc("B tennis crossover"), esc("Yes"), esc("08:30 size skip; 08:34 T0 both filled C=1.03; 12:52 cross skip C=1.61; 13:25 cross FOK partial 0.09")],
            [esc("A lock gap"), esc("No send"), esc("No lock HTTP on this ITF slug")],
            [esc("C / D"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Should skip"), esc("B absorbed after T0 both filled")],
        ]
    )
    orders = _ord(
        [
            [esc("08:34:40"), esc("B"), esc("b-t0"), esc("Polymarket"), esc("No / Bruno"), esc("0.700"), esc("FOK"), esc("200"), esc("1.0000"), esc("0.7000"), esc("0.01"), esc("0.7100"), esc("polymarket activities GET qty 1.0000 @ 0.7000"), esc("DAFJHS6G11TB")],
            [esc("08:34:40"), esc("B"), esc("b-t0"), esc("Polymarket"), esc("Yes / Enzo Lima"), esc("0.710"), esc("FOK"), esc("200"), esc("1.0000"), esc("0.7100"), esc("0.01"), esc("0.7200"), esc("polymarket activities GET qty 1.0000 @ 0.7100"), esc("DAFJPBB011MV")],
            [esc("13:25:19"), esc("B"), esc("b-cross"), esc("Polymarket"), esc("No / Bruno extra"), esc("0.120"), esc("FOK"), esc("200"), esc("0.09"), esc("0.1200"), esc(""), esc(""), esc("activities GET empty; this-order cumQuantity 0.09 (not house fill) @ 0.1200"), esc("DAKREZQG51MQ")],
        ],
        "T0 request tif FOK. Venue may echo IOC on the fill tape. 0.09 is not a dropped 1-contract.",
    )
    return f"""
<h2 id="lima">Enzo Lima vs. Bruno Vieira Alves Malacarne Bruno</h2>
<p class="note">T0 ET: listed/feed <strong>08:30</strong> 25 Oct 2026. First look skipped <code>poly_size_lt_qty_skip need≥1 saw=0.1000</code>. Retry filled both.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>08:30 neither T0 leg sent (size). 12:52 50-cross skip all-in C=1.61. 13:25 extra Yes/No 0.09 cumQuantity: <code>poly_fok_partial_unexpected</code> — not a house 1-contract fill, not flattening as 1, no second IOC. Wired remainder cancel if the order was still open. extra_stuck on the watch. This is the leftover slug from the Mesa note, not a dropped 1-fill.</p>
<h3>P&amp;L with fees</h3>
<p>T0 both-Yes all-in 1.03 (0.71+0.30+two $0.01). Absorbed; hold to settlement. 0.09 dust is not in house P&amp;L as a 1-lot.</p>
<div class="verdict"><strong>Right / HOLD.</strong> Size skip then T0 fill is the freeze. FOK partial handled as designed. Do not retune C=1.05 from the 1.61 cross skip.</div>
"""


def _paris() -> str:
    sys_t = _sys_rows(
        [
            [esc("B tennis crossover"), esc("Yes — skip"), esc("Repeated t0_allin_c_over_105 Novig fee unknown (Yes ~0.67–0.73 / 0.29–0.31). No B HTTP.")],
            [esc("A lock gap"), esc("Yes"), esc("13:54–13:55 over cap. 13:56 hard Poly No filled. Easy not sent (gap 1.69). Open leftover.")],
            [esc("C / D"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Allowed if B skipped C>1.05"), esc("Faucon Yes ~0.29 in (0.10,0.50). E watch skipped[] empty; no E send.")],
        ]
    )
    orders = _ord(
        [
            [esc("13:56:33"), esc("A"), esc("hard"), esc("Polymarket"), esc("No / Tom Paris"), esc("0.600"), esc("FOK"), esc("200"), esc("1.0000"), esc("0.7700"), esc("0.01"), esc("0.7800"), esc("polymarket activities GET qty 1.0000 @ 0.7700"), esc("DAM66PD011MV")],
        ],
        "Quote at send 0.400, limit 0.600, fill 0.7700. Easy Kalshi Yes was not posted.",
    )
    return f"""
<h2 id="paris">Tom Paris vs. Romain Faucon</h2>
<p class="note">T0 ET: listed/feed <strong>11:30</strong> 25 Oct 2026 (odds snapshot T0 10:20 feed). B never sent. Lock at 13:56 is in-play leftover, not a T0 both-Yes.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>A easy Kalshi not sent: supervisor 13:58 “hard filled gap closed … flatten hard, easy not sent.” <strong>No flatten HTTP</strong> in orders.jsonl after that fill. leftover_watch_stats.jsonl has <strong>no Paris rows</strong>. Last tape Poly Tom Paris No 0.01 at 14:10 ET (Paris likely won), so a Paris-No leftover would pay about $0 if that is settlement.</p>
<h3>P&amp;L with fees</h3>
<p>Cash 0.77 + ~$0.01 Poly fee. Settlement not in the 22 Oct fill-history pull. If Paris won, leftover No ≈ −$0.78. We did not sell it from this job.</p>
<div class="warn"><strong>HOLD — leftover flatten tape gap.</strong> Hard-first abort of the easy leg is right. Flatten-first then leftover watch is the freeze; the flatten POST is not on the order tape and leftover stats never named this game. Confirm whether leftover actually armed before calling it a live A bug. Do not retune B. Do not sell from this page.</div>
"""


def _llanes() -> str:
    sys_t = _sys_rows(
        [
            [esc("B tennis crossover"), esc("Yes"), esc("12:00 size skip 0.14; 12:04 T0 both filled C=1.03. Postponed closed without settlement.")],
            [esc("A / C / D"), esc("No send / skip"), esc("No lock HTTP. C/D skip tennis")],
            [esc("E T0 dog"), esc("Should skip"), esc("B T0 filled")],
        ]
    )
    orders = _ord(
        [
            [esc("12:04:16"), esc("B"), esc("b-t0"), esc("Polymarket"), esc("Yes / Llanes Echavarria"), esc("0.740"), esc("FOK"), esc("200"), esc("1.0000"), esc("0.7400"), esc("0.01"), esc("0.7500"), esc("polymarket activities GET qty 1.0000 @ 0.7400"), esc("DAJJGZ7G31MQ")],
            [esc("12:04:16"), esc("B"), esc("b-t0"), esc("Polymarket"), esc("No / Cruz Vazquez"), esc("0.730"), esc("FOK"), esc("200"), esc("1.0000"), esc("0.7400"), esc("0.01"), esc("0.7500"), esc("polymarket activities GET qty 1.0000 @ 0.7400"), esc("DAJJPE2011N2")],
        ],
        "Watch: postponed 15:42 ET closed without settlement; holdings stay.",
    )
    return f"""
<h2 id="llanes">Patricio Llanes Echavarria vs. Edgar Hipolito Cruz Vazquez</h2>
<p class="note">T0 ET: listed/feed <strong>12:00</strong> 25 Oct 2026. Yes 0.74 / 0.27, all-in C=1.03.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>12:00:41 neither T0 leg sent (<code>poly_size_lt_qty_skip need≥1 saw=0.1400</code>). Retry filled both.</p>
<h3>P&amp;L with fees</h3>
<p>All-in 1.03. Watch: postponed, closed without settlement — P&amp;L unknown until venue pays or voids. We did not sell.</p>
<div class="verdict"><strong>Right / HOLD.</strong> Size skip then fill is the freeze. Postponed is the venue, not a bot miss.</div>
"""


def _uchijima() -> str:
    sys_t = _sys_rows(
        [
            [esc("B tennis crossover"), esc("Yes — skip"), esc("Novig t0_allin_c_over_105 fee unknown all day (Yes ~0.15–0.19 / 0.85–0.89). No B HTTP.")],
            [esc("A lock gap"), esc("Yes"), esc("24 Oct 23:31 hard Kalshi No filled; easy Poly size 0.50 skip; flatten Yes filled.")],
            [esc("C / D"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Allowed (B skipped C/fee)"), esc("Uchijima Yes ~0.15 in (0.10,0.50). No E send on tape.")],
        ]
    )
    orders = _ord(
        [
            [esc("23:31:51"), esc("A"), esc("hard"), esc("Kalshi"), esc("No / Elise Mertens"), esc("0.8300"), esc("IOC"), esc("201"), esc("1.00"), esc("0.1700"), esc("0"), esc("0.1700"), esc("kalshi fills GET qty 1.00 @ 0.1700"), esc("01a1711d-ae48-74e7-91b3-729f2aee8341")],
            [esc("23:32:39"), esc("A"), esc("flatten"), esc("Kalshi"), esc("Yes / Mertens"), esc("0.8500"), esc("IOC"), esc("201"), esc("1.00"), esc("0.8500"), esc("0"), esc("0.8500"), esc("kalshi fills GET qty 1.00 @ 0.8500"), esc("01a1711e-42b8-7fe6-8a86-ad4c6788b125")],
        ],
        "Times 24 Oct 2026 ET, before listed start 25 Oct 23:55. Easy Poly not sent (size 0.50).",
    )
    return f"""
<h2 id="uchijima">Uchijima vs Mertens</h2>
<p class="note">T0 ET for B: listed <strong>23:55</strong> 25 Oct 2026. Lock fill is 24 Oct 23:31 ET (pre-start / prior session), not a B T0 both-Yes.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>Easy Poly Yes not sent: <code>poly_size_lt_qty_skip need≥1 saw=0.5000</code>; flatten hard instead. B never posted.</p>
<h3>P&amp;L with fees</h3>
<p>Flatten Yes+No on the same Kalshi ticker: 0.17+0.85=1.02 cash vs $1 payout → about <strong>−$0.02</strong> (tape Kalshi fee 0).</p>
<div class="verdict"><strong>Right / HOLD.</strong> Hard-first, size skip, flatten. B C/fee skip is the freeze. Do not bump C to catch Novig fee-unknown rows.</div>
"""


def _trotter() -> str:
    sys_t = _sys_rows(
        [
            [esc("B tennis crossover"), esc("Yes — skip"), esc("C=1.06 at 05:25 Poly; Novig fee unknown the rest of the day. No B HTTP.")],
            [esc("A lock gap"), esc("Yes"), esc("19:13 hard Kalshi No filled; easy not sent; flatten miss; leftover watch until Kalshi closed.")],
            [esc("C / D"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Allowed (B skipped C>1.05)"), esc("Trotter Yes ~0.43 in band at the 05:25 look. No E send.")],
        ]
    )
    orders = _ord(
        [
            [esc("19:13:52"), esc("A"), esc("hard"), esc("Kalshi"), esc("No / James Kent Trotter"), esc("0.5800"), esc("IOC"), esc("201"), esc("1.00"), esc("0.2800"), esc("0"), esc("0.2800"), esc("kalshi fills GET qty 1.00 @ 0.2800"), esc("01a17558-2f60-706c-85d6-019b82218f44")],
            [esc("19:16:45"), esc("A"), esc("flatten"), esc("Kalshi"), esc("Yes / Trotter"), esc("0.7900"), esc("IOC"), esc("201"), esc("0"), esc(""), esc(""), esc(""), esc("kalshi fills GET empty"), esc("01a1755b-a618-7c2c-9261-108d7753eee0")],
        ],
        "Leftover watch 19:26–19:50: 841 ask_above_max, 49 ask_missing, then resolved_first closed_why=kalshi closed. One flatten HTTP only — not 453 leftover IOCs.",
    )
    return f"""
<h2 id="trotter">Trotter vs Svajda</h2>
<p class="note">T0 ET: listed <strong>16:30</strong> 25 Oct 2026. Lock 19:13 is in-play leftover. One-leg turns A off only; leftover watch stayed on this ticket.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>A claims skipped poly size 0.10/0.20 and over cap 1.08–1.11. Easy Poly not sent (gap 1.45). Flatten Yes confirm 0. Leftover never buyable (asks ~0.81 vs max other ~0.26–0.27).</p>
<h3>P&amp;L with fees</h3>
<p>Naked Kalshi No Trotter 1 @ 0.28, fee 0 on tape. Pays $1 if Trotter lost, $0 if Trotter won. Winner not in the 22 Oct fill-history pull. leftover resolved_first at 19:50:55 ET.</p>
<div class="verdict"><strong>Right / HOLD.</strong> Flatten-first then leftover watch refused over-max asks. Do not wire a second IOC spam. Do not retune C=1.05 from the 1.06 B skip.</div>
"""


def _baris() -> str:
    sys_t = _sys_rows(
        [
            [esc("A lock gap"), esc("Yes"), esc("18:22 hard Poly miss confirm 0; hard_miss_abort; easy not sent.")],
            [esc("B tennis crossover"), esc("Yes"), esc("18:41 T0 both posted; fill-history confirm 0 / 0. Watch skip_reason t0_allin_c_over_105 after.")],
            [esc("C / D"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Allowed if B confirm 0 and C skip"), esc("Heck Yes 0.14 in (0.10,0.50). No E send.")],
        ]
    )
    orders = _ord(
        [
            [esc("18:22:28"), esc("A"), esc("hard"), esc("Polymarket"), esc("Yes / (supervisor: No @ 0.690)"), esc("0.690"), esc("FOK"), esc("200"), esc("0"), esc(""), esc(""), esc(""), esc("polymarket activities GET empty"), esc("DAQZYSP011MM")],
            [esc("18:41:50"), esc("B"), esc("b-t0"), esc("Kalshi"), esc("Yes / Ozan Baris"), esc("0.8700"), esc("IOC"), esc("201"), esc("0"), esc(""), esc(""), esc(""), esc("kalshi fills GET empty"), esc("01a17545-5340-72cf-abf5-c8402a2380e2")],
            [esc("18:41:50"), esc("B"), esc("b-t0"), esc("Kalshi"), esc("Yes / Hunter Heck"), esc("0.1400"), esc("IOC"), esc("201"), esc("0"), esc(""), esc(""), esc(""), esc("kalshi fills GET empty; mismatch tape qty 1.00, using confirm"), esc("01a1753b-1df8-7aaf-b94a-4717a2dfe800")],
        ],
        "Heck tape fill_count 1.00 vs fills GET empty → confirm 0 (fill-history truth).",
    )
    return f"""
<h2 id="baris">Baris vs Heck</h2>
<p class="note">T0 ET: occurrence <strong>18:40</strong> 25 Oct 2026 (listed 18:15). B all-in C at send 1.0358.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>All three HTTP posts: confirm qty 0. A easy not sent. B did not leftover-yes because confirm said neither T0 leg filled.</p>
<h3>P&amp;L with fees</h3>
<p>None on fill-history. If a later Kalshi fills GET shows qty ≥ 1 on the Heck order, that would be a GET-lag miss to reopen — not assumed here.</p>
<div class="verdict"><strong>Right / HOLD.</strong> HTTP 200/201 is not a fill. Using Kalshi fills GET over tape 1.00 matches “fill-history is truth.” Do not flatten a 0-confirm as 1.</div>
"""


def _delpino() -> str:
    sys_t = _sys_rows(
        [
            [esc("A lock gap"), esc("Yes"), esc("13:54 over cap. 13:55 hard Poly miss confirm 0. After B opened, lock skipped “Tennis crossover has this tennis match open.”")],
            [esc("B tennis crossover"), esc("Yes"), esc("After 14:05 reload. T0 15:10 Leite filled, Del miss; leftover-yes Del filled 15:42. Postponed.")],
            [esc("C / D"), esc("No"), esc("Skip tennis")],
            [esc("E T0 dog"), esc("Should skip after B T0"), esc("Del Yes 0.40 in dog band at T0; B already sending.")],
        ]
    )
    orders = _ord(
        [
            [esc("13:55:40"), esc("A"), esc("hard"), esc("Polymarket"), esc("Yes / Mateo Del Pino"), esc("0.300"), esc("FOK"), esc("200"), esc("0"), esc(""), esc(""), esc(""), esc("polymarket activities GET empty"), esc("DAM6S2RG11N2")],
            [esc("15:10:17"), esc("B"), esc("b-t0"), esc("Kalshi"), esc("Yes / Mateo Del Pino"), esc("0.4000"), esc("IOC"), esc("201"), esc("0"), esc(""), esc(""), esc(""), esc("kalshi fills GET empty"), esc("01a1747a-5668-71c0-9af1-dd973b290cb3")],
            [esc("15:10:17"), esc("B"), esc("b-t0"), esc("Kalshi"), esc("Yes / Wilson Leite"), esc("0.6100"), esc("IOC"), esc("201"), esc("1.00"), esc("0.4600"), esc("0"), esc("0.4600"), esc("kalshi fills GET qty 1.00 @ 0.4600"), esc("01a1747c-fe18-71a9-bb48-fbc86c7b0440")],
            [esc("15:16:13"), esc("B"), esc("flatten"), esc("Kalshi"), esc("No / Leite"), esc("0.3700"), esc("IOC"), esc("201"), esc("0"), esc(""), esc(""), esc(""), esc("kalshi fills GET empty"), esc("01a17484-f910-7151-8242-5beeda7a33d2")],
            [esc("15:42:22"), esc("B"), esc("b-leftover-yes"), esc("Kalshi"), esc("Yes / Mateo Del Pino"), esc("0.6900"), esc("IOC"), esc("201"), esc("1.00"), esc("0.6900"), esc("0"), esc("0.6900"), esc("kalshi fills GET qty 1.00 @ 0.6900"), esc("01a17496-d748-794f-9069-6985881bbe51")],
        ],
        "A Poly miss: tape_qty 0 and activities empty — true miss, not an empty-GET wipe of cumQuantity.",
    )
    return f"""
<h2 id="delpino">Del Pino vs Leite</h2>
<p class="note">T0 ET: occurrence <strong>15:10</strong> 25 Oct 2026 (listed 13:05). B all-in C 1.0435. Morning B skips C=1.05–1.27 / Novig fee unknown. Send after 14:05 reload.</p>
{sys_t}
<h3>Orders</h3>
{orders}
<h3>Tried and not filled</h3>
<p>A hard Poly confirm 0 (tape 0). B T0 Del confirm 0. Flatten Leite No confirm 0 (also flatten_miss 15:33). Lock later skipped because B had the match open — correct skip-if-B for A on an open B match.</p>
<h3>P&amp;L with fees</h3>
<p>B ended with both Yes: Leite 0.46 + leftover Del 0.69 = 1.15 cash (Kalshi fee 0 on tape), not a lock. Watch: postponed 15:54 closed without settlement. P&amp;L unknown until venue pays or voids.</p>
<div class="verdict"><strong>Right / HOLD.</strong> B leftover-yes filled the T0 miss instead of calling it a dropped 1. A Poly 200 with tape 0 stayed a miss. Do not start a second B. Do not sell postponed holdings from this page.</div>
"""


def main() -> None:
    path = write_page()
    print(path)


if __name__ == "__main__":
    main()
