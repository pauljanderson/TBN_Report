"""Write Nagal ask-vs-cap page. No orders. No secrets. Does not commit."""
from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from report_page_extras import (  # noqa: E402
    CACHE_META,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
PAGE = STAMP / "nagal_ask_vs_cap_20261020.html"

ASKED = (
    "if we know what the ask is, why did we bid under it? was that the max?"
)
PLAIN = (
    "We did not bid under the Kalshi Yes ask. We sent 0.59 because that is the "
    "Kalshi Yes ask we were looking at, and it happened to be exactly the most "
    "we could still pay after the Polymarket 0.34 plus a 2-cent fee. A limit "
    "buy hits the ask (the price sellers want), not the bid (the price other "
    "buyers want). Immediate-or-cancel means fill right now or vanish. Kalshi "
    "took the order and filled nothing: the 0.59 offer was gone or the advertised "
    "size of 2 was not actually sitting there. We did not clip a higher live ask "
    "down to 0.59. There is no book snapshot of a higher ask at send."
)


def _esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{_esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def _rows_html(rows: list[tuple[str, ...]], kinds: list[str]) -> str:
    head = "".join(_th(label, kind) for label, kind in zip(rows[0], kinds))
    body = []
    for cells in rows[1:]:
        body.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def write_page() -> Path:
    timeline = _rows_html(
        [
            ("Time ET", "What", "Kalshi Yes", "Poly No cash", "Size / fill", "Source"),
            (
                "2026-10-20 07:37:56.963",
                "Polymarket print",
                "(not in price_memory)",
                "0.3800",
                "",
                "price_memory.jsonl websocket",
            ),
            (
                "2026-10-20 07:37:56.952–07:37:57.139",
                "HTTP compare / gap_open Sumit Nagal wins",
                "0.59 implied (gross 0.97 − poly 0.38)",
                "0.38",
                "yes_size 2, no_size 38055.13, net 0.99",
                "live_checks.prev.jsonl; transport=request",
            ),
            (
                "2026-10-20 07:37:57.491",
                "Polymarket print that made net 0.95",
                "",
                "0.3400 (prior 0.3800)",
                "",
                "price_memory.jsonl",
            ),
            (
                "2026-10-20 07:37:57.903",
                "Simultaneous send log",
                "kalshi/yes@0.5900",
                "polymarket/no@0.340",
                "",
                "live_supervisor.log",
            ),
            (
                "2026-10-20 07:37:58.747",
                "Kalshi IOC bid sent",
                "limit 0.5900 side=bid",
                "",
                "HTTP 201 fill_count 0.00 remaining 0.00",
                "order_io.jsonl",
            ),
            (
                "2026-10-20 07:37:59.409",
                "Recovery cap",
                "max=0.5900 after fill=0.340",
                "0.340 filled",
                "",
                "live_supervisor.log",
            ),
            (
                "2026-10-20 07:38:00.258",
                "Recovery Kalshi IOC",
                "limit 0.5900 side=bid",
                "",
                "HTTP 201 fill_count 0.00 remaining 0.00; no HTTP book",
                "order_io.jsonl",
            ),
            (
                "2026-10-20 07:38:10.618",
                "gap_close same pair",
                "still gross 0.93 ⇒ 0.59 + 0.34",
                "0.34",
                "yes_size still 2",
                "live_checks.prev.jsonl",
            ),
        ],
        ["date", "text", "text", "num", "text", "text"],
    )
    answers = _rows_html(
        [
            ("#", "Question", "Answer"),
            (
                "1",
                "What number did we think was the Kalshi Yes ASK, and from which field?",
                "0.59 from yes_ask_dollars (the ask you pay). Not last. Not yes_bid.",
            ),
            (
                "2",
                "Did we send AT that ask or UNDER it?",
                "AT it. First send uses the quoted ask. It does not clip down to the cap.",
            ),
            (
                "3",
                "If under: was 0.59 the 0.95 cap and the live ask higher?",
                "Not under. 0.59 also equals the cap (0.95 − 0.34 − 0.02). No higher ask is on disk at send.",
            ),
            (
                "4",
                "If at the ask and fill 0: lag/size?",
                "Yes. Size 2 at 0.59 about 1.6s before the Kalshi send; IOC filled 0. Memory still said size 2 twelve seconds later.",
            ),
            (
                "5",
                "What SHOULD we send vs what code does today?",
                "Should: min(live ask, max profitable). Today: first send is the raw ask or skip if over cap. Recovery does not clip to max if the live ask is higher.",
            ),
        ],
        ["num", "text", "text"],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nagal 0.59: ask or cap? 2026-10-20</title>
<style>
body {{ margin: 0; padding: 16px 16px 48px; font: 16px/1.45 system-ui, Segoe UI, sans-serif; color: #0f172a; background: #fff; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
p {{ margin: 0.4rem 0 0.7rem; }}
.callout {{ border-left: 4px solid #1d4ed8; background: #f8fafc; padding: 10px 12px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #ecfdf5; border: 1px solid #059669; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
ol {{ padding-left: 1.3rem; }}
ol li {{ margin: 0.45rem 0; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Nagal 0.59: we bid the ask, which was also the max</h1>
<div class="callout">
<h2>What you asked</h2>
<p>{_esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{_esc(PLAIN)}</p>
</div>
<div class="banner"><strong>Verdict.</strong> 0.59 was the Kalshi Yes ask we used, sent as-is. It was also the 0.95 cap. We did not bid under a higher live ask on purpose.</div>

<h2>The five answers</h2>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{answers}

<h2>1. What ask did we think we were hitting?</h2>
<p><strong>0.59, from Kalshi <code>yes_ask_dollars</code></strong> — the Yes ask, not last, not the bid. A Kalshi Yes buy is <code>side=bid</code> at that ask.</p>
<p>Independent of the later quote-time backfill:</p>
<ul>
<li>Supervisor: <code>order simultaneous send Nagal vs Sanchez Quilez kalshi/yes@0.5900 + polymarket/no@0.340</code> at 07:37:57.903 ET.</li>
<li>Candidate Yes price is <code>contract_view</code> <code>yes = d(raw.get("yes_ask_dollars"))</code> in <code>overnight_scan.py</code>. That is the ask. <code>yes_bid_dollars</code> is not the send price.</li>
<li>HTTP gap_open 07:37:57.139: same pair, gross 0.97, net 0.99, <code>yes_size</code> 2. Polymarket No was 0.38 one tenth of a second earlier, so Kalshi Yes ask = 0.97 − 0.38 = <strong>0.59</strong>.</li>
<li><code>price_memory.jsonl</code> and <code>price_last.json</code> have <strong>zero</strong> Kalshi Nagal rows (MATCH ticker was not stored as moneyline then). No last-print fallback.</li>
</ul>

<h2>2. AT the ask or under it?</h2>
<p><strong>AT the ask.</strong> First send uses the quoted candidate pay. It does not clip to <code>max_leg_price</code>.</p>
<p><code>_send_pair</code> takes <code>price_a = _dec(first.get("pay"))</code> from the compare, builds the IOC at that pay, and posts it if the pair is still under the cap. The Kalshi body is <code>side=bid price=0.5900 time_in_force=immediate_or_cancel</code>.</p>

<h2>3. Was 0.59 the cap, with a higher live ask?</h2>
<p>0.59 <em>is</em> the cap, and there is <strong>no on-disk higher ask at send</strong>.</p>
<p>Arithmetic: Polymarket No cash 0.34, Kalshi fee 0, Polymarket taker fee <code>0.0695 × 0.34 × 0.66</code> = 0.0156 → <strong>0.02</strong>. Then 0.95 − 0.34 − 0.02 = <strong>0.59</strong>. Supervisor recovery line: <code>order recovery max=0.5900 ... after fill=0.340</code>.</p>
<p>If the live Kalshi ask had been 0.65, first send would have <em>skipped</em> (net 1.01 &gt; 0.95), not clipped to 0.59. There is no skip-not-profitable line for this pair. There is no Kalshi HTTP <code>kind=book</code> row for NAGSAN in <code>order_io.jsonl</code>. Overlay later shows Kalshi Yes 0.85 around 08:07 — that is half an hour later, not the send book.</p>

<h2>4. At the ask, fill 0: lag / size</h2>
<p>The 0.59 ask with size 2 was already on the HTTP compare at 07:37:57.139. Polymarket then printed 0.34 at 07:37:57.491. Kalshi IOC left at 07:37:58.747 (1.255s after that print, 1.608s after the HTTP ask). Fill 0, remaining 0, no status field.</p>
<p>At 07:38:10 the same gap still shows <code>yes_size</code> 2 and gross 0.93 (0.59 + 0.34). So our in-memory book still claimed 2 contracts at 0.59 <em>after</em> both misses. Either the matching engine had no 0.59 offer (stale size), or size was gone for the ~1.6s we needed and the field did not drop.</p>

<h2>5. What we should send vs what the code does</h2>
<p><strong>Should:</strong> send <code>min(live ask, max profitable)</code>. If live ask &gt; max, skip or send max (IOC miss likely).</p>
<p><strong>Today:</strong></p>
<ul>
<li><strong>First simultaneous send:</strong> raw quoted ask. If that ask makes net &gt; 0.95, skip the pair. Do not clip down to max.</li>
<li><strong>Recovery:</strong> websocket ask, then HTTP book, then halfway to max. Websocket 0.59 equaled the cap, so it sent 0.59 again.</li>
<li>Kalshi’s empty IOC body has no <code>status=cancelled</code>, so <code>ioc_nothing_filled</code> is false and recovery <strong>did not fetch the HTTP book</strong> this time.</li>
<li>If live ask &gt; max on recovery, midway is <code>(ask + max) / 2</code> and is dropped when that is above max. The code does <strong>not</strong> send the max as a clip.</li>
</ul>

<h2>Timeline</h2>
<p class="note">Click column headers to sort. Kalshi Yes never appears in price_memory for this match.</p>
{SWIPE_NOTE_HTML}
{timeline}

<p class="note">Research only. Not gold. Not DailyRun. No orders placed. <code>orders_stopped.json</code> was not touched.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = write_page()
    print(path)
