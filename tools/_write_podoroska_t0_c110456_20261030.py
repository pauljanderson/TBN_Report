"""Why B skipped Podoroska vs Monnet at 20:00:40 ET with C=1.10456. Display only."""
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

from report_page_extras import (  # noqa: E402
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    inject_report_page_extras,
)
from write_orders_performance import table  # noqa: E402

ET = ZoneInfo("America/New_York")
STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "podoroska_monnet_t0_c110456_20261030.html"

PAUL = (
    "Paul: why was this skipped? 2026-10-30T20:00:40-04:00 t0 skip "
    "t0_allin_c_over_105 all-in C=1.10456. Find the exact live_strategy_b / kitchen / "
    "opportunities row at that timestamp. Name the match, both Yes (player, venue, raw px, "
    "fee, after-fee), sum = 1.10456. B skip rule: both Yes at T0 only if after-fee pair "
    "<= C_HI 1.05. 1.10456 is about 5.5c over. HOLD the cap. Explain, do not change it "
    "unless a fee-math bug (wrong fee, inverted Yes/No, Novig unknown treated as 1.1, "
    "Poly vs Kalshi)."
)


def esc(text) -> str:
    return html_lib.escape(str(text))


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    pa, pb = Decimal("0.490"), Decimal("0.585")
    fa, fb = Decimal("0.01499"), Decimal("0.01457")
    tape = table(
        [
            ("When ET", "date"),
            ("Source", "text"),
            ("Match", "text"),
            ("Action", "text"),
            ("Venue", "text"),
            ("Yes A", "num"),
            ("Yes B", "num"),
            ("All-in C", "num"),
            ("Reason", "text"),
        ],
        [
            [
                "2026-10-30T20:00:40.105-04:00",
                "orders.jsonl event=t0",
                "Podoroska vs Monnet",
                "skip",
                "(blank on tape)",
                "(blank)",
                "(blank)",
                "1.10456",
                "t0_allin_c_over_105 all-in C=1.10456",
            ],
            [
                "2026-10-30T20:00:16.932-04:00",
                "orders.jsonl event=t0 (24s earlier)",
                "Podoroska vs Monnet",
                "skip",
                "(blank on tape)",
                "(blank)",
                "(blank)",
                "1.0545",
                "t0_allin_c_over_105 all-in C=1.0545",
            ],
            [
                "2026-10-30T20:00:02.834-04:00",
                "orders.jsonl event=t0 (same match, Novig listing)",
                "Carole Monnet @ Nadia Podoroska Quarterfinals",
                "skip",
                "novig",
                "0.63 Nadia Podoroska",
                "0.38 C. Monnet",
                "",
                "t0_allin_c_over_105 all-in fee unknown",
            ],
        ],
    )
    legs = table(
        [
            ("Player", "text"),
            ("Venue", "text"),
            ("Side", "text"),
            ("Raw Yes px", "num"),
            ("Fee (c=0.06)", "num"),
            ("After-fee", "num"),
        ],
        [
            [
                "Nadia Podoroska (dog; Kalshi nearby had her cheaper)",
                "Novig",
                "Yes",
                f"{pa}",
                f"{fa}",
                f"{pa + fa}",
            ],
            [
                "Carole Monnet (favorite; Kalshi nearby had her richer)",
                "Novig",
                "Yes",
                f"{pb}",
                f"{fb}",
                f"{pb + fb}",
            ],
        ],
        ["Sum", "Novig both-Yes", "Yes+Yes", f"{pa + pb}", f"{fa + fb}", "1.10456"],
    )
    bugs = table(
        [
            ("Check", "text"),
            ("Result", "text"),
        ],
        [
            [
                "Wrong fee schedule",
                "No. 1.10456 has five decimals. Novig fees quantize to $0.00001. "
                "Kalshi is $0.0001 (would print 1.1045). Polymarket US is banker's cent "
                "(would print 1.08 / 1.11). Gemini rounds up to a cent. House Novig "
                "coefficient on live books is 0.06, not Polymarket's 0.0695.",
            ],
            [
                "Inverted Yes/No",
                "No. This is System B both-Yes, not a lock-bot Yes+No. A Yes+No pair "
                "at these shops around then nets ~0.99–1.01 after fee, not 1.10456.",
            ],
            [
                "Novig unknown treated as 1.1",
                "No. That bug would print C=1.1 (two decimals) or “fee unknown.” "
                "The 19:38 skip on the Poly listing is C=1.1. The 20:00:02 Novig listing "
                "is fee unknown. This 20:00:40 row is a computed 1.10456.",
            ],
            [
                "Poly vs Kalshi mix-up",
                "No. Same-venue first over-cap book (tape blanked the shop because "
                "the skip is the _prepare_book over-C path). Five-decimal C is Novig. "
                "Kalshi 24s earlier on this same listing is C=1.0545 = 0.45 + 0.57 + "
                "0.0173 + 0.0172.",
            ],
        ],
    )
    nearby = table(
        [
            ("When ET", "date"),
            ("What", "text"),
            ("Podoroska Yes", "num"),
            ("Monnet Yes", "num"),
            ("Note", "text"),
        ],
        [
            [
                "2026-10-30T20:00:16",
                "B T0 skip (Kalshi both-Yes)",
                "0.45",
                "0.57",
                "All-in 1.0545 = 0.45+0.57+0.0173+0.0172. 0.45¢ over $1.05. Same cap.",
            ],
            [
                "2026-10-30T20:00:40",
                "B T0 skip (this row)",
                "0.490",
                "0.585",
                "Novig both-Yes after-fee 1.10456. ~5.46¢ over $1.05.",
            ],
            [
                "2026-10-30T20:01:08",
                "Kalshi memory + first opportunities row",
                "0.48 / then 0.42",
                "0.54 / then 0.59",
                "Lock-bot Yes+No: Kalshi Yes Podoroska 0.42 / Poly No 0.57 net 1.01. Not B.",
            ],
            [
                "2026-10-30T20:05:48",
                "Kitchen / lock-bot send then flatten",
                "",
                "",
                "Kalshi No Monnet fill 0.46 fee 0.0174 after-fee 0.4774; Poly miss 0; flatten Kalshi Yes 0.55. Not B. Not this skip.",
            ],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Podoroska vs Monnet T0 skip C=1.10456 — 30 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
code {{ font-size: 13px; }}
pre {{ white-space: pre-wrap; background: #f8fafc; border: 1px solid #e2e8f0; padding: 8px 10px; font-size: 13px; }}
ul {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Podoroska vs Monnet — why B skipped at 20:00:40</h1>
<p class="note">America/New_York. Written {esc(now)}. Stamp <code>prediction_market_arb_exhaustive_20261017</code>.
Did not commit. Did not start a second B. Did not leftover-GTC A. Did not DailyRun.
Did not retune C_HI=1.05 or D=0.25. Did not sell TEN/CIN. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<pre>{esc(PAUL)}</pre>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>System B only buys <strong>both players Yes</strong> at the first-serve window (T0)
if those two tickets plus each shop’s documented taker fee add up to <strong>$1.05 or
less</strong>. At 20:00:40 it looked at Podoroska vs Monnet, added the two Novig Yes
asks plus Novig fees, got <strong>$1.10456</strong> — about 5½ cents over the cap —
and skipped. No tickets went out. The $1.05 cap is unchanged.</p>
</div>

<div class="callout ok">
<h2>Verdict</h2>
<ul>
<li><strong>Match:</strong> Podoroska vs Monnet (WTA Challenger; same game as
Carole Monnet @ Nadia Podoroska Quarterfinals / Nadia Podoroska vs. Carole Monnet).</li>
<li><strong>Two Yes legs:</strong> Novig Yes Nadia Podoroska 0.490 + fee 0.01499 = 0.50499;
Novig Yes Carole Monnet 0.585 + fee 0.01457 = 0.59957.</li>
<li><strong>1.10456 is correct math</strong> under the live B fee model
(<code>0.06 × p × (1−p)</code> to $0.00001, WHEN_LIVE in-game or ALWAYS).</li>
<li><strong>Skip is working as designed.</strong> After-fee pair 1.10456 &gt; C_HI 1.05.
Not a fee bug. HOLD the cap.</li>
</ul>
</div>

<h2>Exact tape row</h2>
<p><code>local/.../raw/orders.jsonl</code> event=t0 at 20:00:40.105. The skip path
(<code>_prepare_book</code> first same-venue book over $1.05) tapes the reason but
leaves player / venue / yes_a / yes_b blank. Kitchen has no B fill at this timestamp
(B never sent). Opportunities has no row at 20:00:40; the first Podoroska vs Monnet
opportunities line is 20:01:08 (lock-bot Yes+No, not both-Yes).</p>
{tape}

<h2>Reconstructed both-Yes (sum = 1.10456)</h2>
<p>Five-decimal C only comes from Novig’s $0.00001 fee quantize. With live Novig
coefficient 0.06, the only both-Yes pair in the 40–65¢ band that equals 1.10456 is
<strong>0.490 + 0.585</strong>. Player names are inferred from Kalshi 24s before /
28s after (Monnet the richer Yes). Swapping names does not change C.</p>
{legs}
<p class="note">0.490 + 0.585 + 0.01499 + 0.01457 = 1.10456. Cap 1.05. Over by 0.05456
(~5.5¢). <code>t0_yes_asks_send_ok</code> returns
<code>t0_allin_c_over_105 all-in C=1.10456</code> — exact match to the tape.</p>

<h2>Fee-math bug checks</h2>
{bugs}

<h2>Same minute, nearby books</h2>
{nearby}

<p class="note">Sources: orders.jsonl, strategy_b.log (PermissionError after the tape,
not the skip), strategy_b_watch.json, opportunities.jsonl, price_memory tennis.jsonl,
live_jobs tennis_podmon, live_strategy_b.py C_HI=1.05 / t0_leg_fee / t0_all_in_from_asks,
novig_live.taker_fee. Did not start a second B. No secrets.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
