"""T0 all-in C_HI=1.05 skip page. Research live. Does not place orders."""
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

import live_strategy_b  # noqa: E402
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
PAGE = STAMP / "t0_allin_c_hi_105_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_allin_c_hi_105_20261024.html"
)

ASKED = (
    "Set the live cap to All-in C ≤ $1.05. Tennis crossover B T0 both-Yes only. "
    "Lock NET_MAX / C / D unchanged."
)

PLAIN = (
    "At the first trusted tennis start (T0), Strategy B buys one Yes on each player. "
    "A Yes pays $1 if that player wins, so the two tickets always pay $1 together. "
    "All-in C is those two Yes prices plus the house's documented take-a-trade fees. "
    "Overnight we used the two prices alone with a $1.01 cap. That skipped a 1.02-wire "
    "book even when fees still left the real cost at or under $1.05 (Broady-like), and "
    "it would have sent a $1.01 wire even if fees then pushed the real cost over $1.05. "
    "Live T0 now sends only when both Yes asks sit in (10¢, 90¢) and all-in C is $1.05 "
    "or less. If all-in C is over $1.05, or the fee schedule is missing (Novig without "
    "ALWAYS / WHEN_LIVE + coefficient), log t0_allin_c_over_105, skip that match, and "
    "go to the next game. No T0, no 50-cent cross, no favorite dip on a skipped match. "
    "Stacking more 1-contract copies after a legal T0, only while all-in stays under $1, "
    "is unchanged. Research-candidate live, not gold, not DailyRun."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def money(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    return format(value.normalize(), "f")


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total:
        cells = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def all_in(pa, pb, venue: str, fee_coefficient=None) -> Decimal | None:
    spec = {"venue": venue, "fee_coefficient": fee_coefficient}
    return live_strategy_b.t0_all_in_from_asks(
        spec, Decimal(str(pa)), spec, Decimal(str(pb))
    )


def main(b_pid: str = "") -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    c_hi = format(live_strategy_b.C_HI, "f")
    token = live_strategy_b.T0_C_OVER_SKIP
    d_val = format(live_strategy_b.D, "f")

    k_4754 = all_in("0.47", "0.54", "kalshi")
    p_4754 = all_in("0.47", "0.54", "polymarket")
    k_8129 = all_in("0.81", "0.29", "kalshi")
    p_8129 = all_in("0.81", "0.29", "polymarket")
    p_8913 = all_in("0.89", "0.13", "polymarket")
    p_6834 = all_in("0.68", "0.34", "polymarket")
    p_5051 = all_in("0.50", "0.51", "polymarket")
    g_5051 = all_in("0.50", "0.51", "gemini")
    k_5051 = all_in("0.50", "0.51", "kalshi")
    p_4755 = all_in("0.47", "0.55", "polymarket")
    g_5052 = all_in("0.50", "0.52", "gemini")
    n_5051 = all_in("0.50", "0.51", "novig")

    tests = table(
        [
            ("Case", "text"),
            ("Venue", "text"),
            ("Yes A", "num"),
            ("Yes B", "num"),
            ("Wire C", "num"),
            ("All-in C", "num"),
            ("Overnight 1.01 wire", "text"),
            ("Live all-in 1.05", "text"),
        ],
        [
            [
                "0.47+0.54 ~1.03/1.04 send",
                "kalshi",
                "0.47",
                "0.54",
                "1.01",
                esc(money(k_4754)),
                "send",
                "send",
            ],
            [
                "0.47+0.54 Poly on the cap",
                "polymarket",
                "0.47",
                "0.54",
                "1.01",
                esc(money(p_4754)),
                "send",
                "send (exactly 1.05)",
            ],
            [
                "0.81+0.29 Namigata tape",
                "kalshi / polymarket",
                "0.81",
                "0.29",
                "1.10",
                f"{esc(money(k_8129))} / {esc(money(p_8129))}",
                "skip",
                f"skip {esc(token)}",
            ],
            [
                "Broady-like wire 1.02, all-in ≤1.05",
                "polymarket",
                "0.89",
                "0.13",
                "1.02",
                esc(money(p_8913)),
                "skip (wire 1.02)",
                "send",
            ],
            [
                "Actual Broady 0.68+0.34",
                "polymarket",
                "0.68",
                "0.34",
                "1.02",
                esc(money(p_6834)),
                "skip",
                f"skip {esc(token)} (fees to 1.06)",
            ],
            [
                "Wire 1.01 Poly 0.50+0.51",
                "polymarket",
                "0.50",
                "0.51",
                "1.01",
                esc(money(p_5051)),
                "send",
                "send (on the cap)",
            ],
            [
                "Wire 1.01 Gemini 0.50+0.51",
                "gemini",
                "0.50",
                "0.51",
                "1.01",
                esc(money(g_5051)),
                "send",
                "send (on the cap)",
            ],
            [
                "Wire 1.01 Kalshi 0.50+0.51",
                "kalshi",
                "0.50",
                "0.51",
                "1.01",
                esc(money(k_5051)),
                "send",
                "send",
            ],
            [
                "Wire 1.01 Novig, fee unknown",
                "novig",
                "0.50",
                "0.51",
                "1.01",
                esc(money(n_5051)),
                "send",
                f"skip {esc(token)} (fee unknown)",
            ],
            [
                "Fees push over 1.05 (Poly 0.47+0.55)",
                "polymarket",
                "0.47",
                "0.55",
                "1.02",
                esc(money(p_4755)),
                "skip",
                f"skip {esc(token)}",
            ],
            [
                "Fees push over 1.05 (Gemini 0.50+0.52)",
                "gemini",
                "0.50",
                "0.52",
                "1.02",
                esc(money(g_5052)),
                "skip",
                f"skip {esc(token)}",
            ],
        ],
    )
    fees = table(
        [
            ("Venue", "text"),
            ("Documented 1-contract taker fee", "text"),
            ("If unknown", "text"),
        ],
        [
            [
                "Kalshi",
                "0.07 × p × (1 − p), rounded to $0.0001 (half up). Not the lock-bot Kalshi-as-$0 default.",
                "formula always used for T0 all-in",
            ],
            [
                "Gemini",
                "0.07 × p × (1 − p), rounded up to the next cent",
                "formula always used",
            ],
            [
                "Polymarket",
                "0.0695 × p × (1 − p), banker's cent, when the market coefficient is missing",
                "defaults to 0.0695 for T0 all-in",
            ],
            [
                "Novig",
                "coefficient × p × (1 − p) only when fee_charged is ALWAYS, or WHEN_LIVE during OPEN_INGAME, and coefficient is on the spec",
                "skip T0 (not wire-only). Log t0_allin_c_over_105 all-in fee unknown. No 50-cross / dip.",
            ],
        ],
    )
    knobs = table(
        [("Knob", "text"), ("Live value", "text"), ("Notes", "text")],
        [
            [
                "T0 all-in C_HI",
                c_hi,
                "two Yes asks + documented taker fees. Replaces overnight wire 1.01.",
            ],
            ["Each Yes", "(0.10, 0.90)", "unchanged"],
            [
                "Skip token",
                token,
                "no T0, no 50-cross, no dip, next game. Was t0_c_over_101.",
            ],
            [
                "All-in stack under $1",
                "unchanged",
                "only after a legal T0; cap 10 pairs/match. Not a 1.05 restack.",
            ],
            ["D extra-pair lock profit", d_val, "unchanged"],
            [
                "Lock-bot NET_MAX",
                "untouched",
                "this job did not edit live_lock_orders",
            ],
            [
                "Systems C / D",
                "untouched",
                "no second B; leftover-deadline and Open-now-sync left alone",
            ],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>T0 all-in C ≤ 1.05 — 24 Oct 2026</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.callout h2 {{ margin: 0 0 6px; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>T0 skip if all-in C &gt; $1.05</h1>
<p class="note">Written {esc(now)}. Times America/New_York (EDT, UTC−4). Research-candidate live. Not gold. Not DailyRun. No sells. No second Strategy B. Lock / C / D unchanged. No secrets.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout ok">
<h2>Verdict</h2>
<ul>
<li><strong>Overnight 1.01 wire is replaced.</strong> That gate (two Yes asks ≤ $1.01, skip token <code>t0_c_over_101</code>) is off. Live T0 send is both Yes in (0.10, 0.90) and <strong>all-in C ≤ {esc(c_hi)}</strong>.</li>
<li><strong>Skip:</strong> all-in C &gt; 1.05, or fee unknown. Log <code>{esc(token)}</code>. No T0, no 50-cross, no dip on that match. Next game.</li>
<li><strong>Broady-like:</strong> a 1.02 wire that overnight 1.01 would skip now sends if all-in stays ≤ 1.05 (example 0.89+0.13 Poly = {esc(money(p_8913))}). Actual Broady Poly 0.68+0.34 is 1.02 wire / {esc(money(p_6834))} all-in and still skips — fees over 1.05.</li>
<li><strong>Wire 1.01 + fees:</strong> Kalshi / Gemini / Poly 0.0695 1-contract fees on a 1.01 wire land at or under 1.05 (Poly/Gemini mid is exactly 1.05, send). They do not push a 1.01 wire over 1.05. Novig without a documented schedule skips. Poly 0.47+0.55 and Gemini 0.50+0.52 show fees pushing a 1.02-class book over 1.05.</li>
<li><strong>Unchanged:</strong> all-in stack under $1 after a legal T0. Lock-bot NET_MAX. Systems C and D. Did not sell tickets.</li>
<li><strong>Status:</strong> research-candidate live. Not gold. Not DailyRun.</li>
<li><strong>Live B:</strong> one process, PID {esc(b_pid)}, hidden spawn via <code>reload_strategy_b</code>.</li>
</ul>
</div>

<h2>Tests</h2>
<p class="note">Click column headers to sort. <code>tools/test_live_strategy_b.py</code> <code>test_t0_allin_c_hi_105_paul_cases</code>. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{tests}

<h2>Fees (same as live, documented)</h2>
<p class="note">Click column headers to sort. T0 all-in uses these formulas, not the lock-bot Kalshi-as-$0 default.</p>
{SWIPE_NOTE_HTML}
{fees}

<h2>Live freeze (this knob only)</h2>
{SWIPE_NOTE_HTML}
{knobs}

<p class="note">Sources: <code>tools/live_strategy_b.py</code> C_HI / t0_yes_asks_send_ok / t0_leg_fee / t0_allin_c_over_105. Overnight wire page <a href="t0_c_hi_101_20261024.html">t0_c_hi_101_20261024.html</a>. Broady wire from <a href="t0_c_on_b_winners_20261024.html">t0_c_on_b_winners_20261024.html</a> (0.68+0.34 Poly). Tests in <code>tools/test_live_strategy_b.py</code>. Live B PID {esc(b_pid)}. File URL {esc(FILE_URL)}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(PAGE)
    print(FILE_URL)


if __name__ == "__main__":
    main(*sys.argv[1:])
