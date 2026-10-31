"""T0 C_HI=1.01 skip page. Research live. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
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
PAGE = STAMP / "t0_c_hi_101_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_c_hi_101_20261024.html"
)

ASKED = (
    "Looking at Polymarket: Yoshimoto 81% and Namigata 57% at T0 (138%). "
    "If that matches our tape, exclude a game where BOTH starters combined are "
    "> 100%, or maybe 101%. Hard pass. Skip. Next game. Put this criteria in place."
)

PLAIN = (
    "A Yes ticket pays $1 if that tennis player wins. At the first trusted start (T0), "
    "Strategy B buys Yes on both players. Those two Yes prices added together are C. "
    "Paul saw Yoshimoto 81% and Namigata 57% on Polymarket and added them to 138% — "
    "that would mean we paid $1.38 to win $1, a guaranteed loss. The house tape at "
    "the actual send was 81¢ + 29¢ = $1.10, not $1.38. The 57–58% is the later leftover "
    "mark on the 0.32-share Namigata toast (0.32 × 58¢ ≈ 19¢), not the T0 fill. $1.10 is "
    "still over $1.01, so we skip anyway. Live T0 now sends only when both Yes asks sit "
    "in (10¢, 90¢) and add up to $1.01 or less. If they add to more than $1.01, log "
    "t0_c_over_101, skip that match, and go to the next game. No T0, no 50-cent cross, "
    "no favorite dip on a skipped match. Stacking under $1 is unchanged and only runs "
    "after a legal T0."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


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


def main(b_pid: str = "") -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    c_hi = format(live_strategy_b.C_HI, "f")
    token = live_strategy_b.T0_C_OVER_SKIP
    tape = table(
        [
            ("Source", "text"),
            ("Yoshimoto Yes", "num"),
            ("Namigata Yes", "num"),
            ("C (sum)", "num"),
            ("When", "text"),
            ("What it is", "text"),
        ],
        [
            [
                "Paul (Polymarket screen)",
                "0.81",
                "0.57",
                "1.38",
                "popup / leftover toast",
                "81% + 57% = 138%. Not the T0 send.",
            ],
            [
                "House tape T0 (ledger + orders.jsonl)",
                "0.81",
                "0.29",
                "1.10",
                "2026-10-24 20:04:31 ET",
                "BUY_SHORT Yoshimoto Yes 0.81 / No Namigata 0.19 filled 1; BUY_LONG Namigata @ 0.29 filled 0.32.",
            ],
            [
                "Later leftover mark (toast)",
                "—",
                "0.58",
                "—",
                "after T0, still open 0.32",
                "Cost $0.19 @ 58% on 0.32 shares. 0.32 × 0.58 ≈ $0.19. Not T0.",
            ],
        ],
        ["Cap wired", "—", "—", "1.01", "this job", "Skip if two Yes asks &gt; $1.01. Tape 1.10 still over. New games skip."],
    )
    tests = table(
        [
            ("Yes A", "num"),
            ("Yes B", "num"),
            ("C", "num"),
            ("Gate", "text"),
            ("Why", "text"),
        ],
        [
            ["0.81", "0.57", "1.38", "skip", f"{esc(token)} (Paul's 138%)"],
            ["0.81", "0.29", "1.10", "skip", f"{esc(token)} (tape T0)"],
            ["0.47", "0.54", "1.01", "send", "on the cap"],
            ["0.47", "0.55", "1.02", "skip", f"{esc(token)}"],
        ],
    )
    knobs = table(
        [("Knob", "text"), ("Live value", "text"), ("Notes", "text")],
        [
            ["T0 Yes-ask C_HI", c_hi, "was 1.20; do not use 1.20 for T0"],
            ["Each Yes", "(0.10, 0.90)", "unchanged"],
            ["Skip token", token, "no T0, no 50-cross, no dip, next game"],
            ["All-in stack under $1", "unchanged", "only after a legal T0; cap 10 pairs/match"],
            ["D extra-pair lock profit", format(live_strategy_b.D, "f"), "unchanged"],
            ["Lock-bot NET_MAX", "untouched", "this job did not edit live_lock_orders"],
            ["Systems C / D", "untouched", "no second B; leftover-deadline and Open-now-sync left alone"],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>T0 skip if C&gt;1.01 — 24 Oct 2026</title>
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
<h1>T0 skip if both Yes asks &gt; $1.01</h1>
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
<li><strong>Tape vs Paul:</strong> T0 was Yoshimoto <strong>0.81</strong> + Namigata <strong>0.29</strong> = <strong>1.10</strong>, not 1.38. The 57–58% is the leftover toast mark, not T0. Still over 101¢.</li>
<li><strong>Wired:</strong> Tennis crossover B live T0 send gate is now <code>C_HI = {esc(c_hi)}</code> on the two Yes asks. Send only if both Yes in (0.10, 0.90) and Yes-ask C ≤ 1.01. If C &gt; 1.01: skip, log <code>{esc(token)}</code>, next game. No T0, no 50-cross, no dip on that match.</li>
<li><strong>Unchanged:</strong> all-in stack under $1 (only after a legal T0). Lock-bot NET_MAX. Systems C and D. Did not sell Namigata / Guajardo / Kalshi tickets.</li>
<li><strong>Status:</strong> research-candidate live. Not gold. Not DailyRun.</li>
<li><strong>Live B:</strong> one process, PID {esc(b_pid)}, hidden spawn via <code>reload_strategy_b</code>.</li>
</ul>
</div>

<h2>Tape vs Paul</h2>
<p class="note">Click column headers to sort. Ledger row: Junri Namigata vs. Natsuki Yoshimoto, 2026-10-24 20:04:31 ET, polymarket no 0.1900 fill 1 / yes 0.2900 fill 0.32 / flatten yes 0.5600 fill 1. Quote book Yoshimoto 0.81. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{tape}

<h2>Tests</h2>
<p class="note">Click column headers to sort. <code>tools/test_live_strategy_b.py</code> <code>test_t0_c_hi_101_paul_cases</code>.</p>
{SWIPE_NOTE_HTML}
{tests}

<h2>Live freeze (this knob only)</h2>
{SWIPE_NOTE_HTML}
{knobs}

<p class="note">Sources: <code>local/.../raw/namigata_poly_extract_20261024.json</code> orders quote_price 0.81 / 0.29 at 20:04:31 ET; ledger.csv Namigata row; <code>tools/live_strategy_b.py</code> C_HI / t0_yes_asks_send_ok / t0_c_over_101. Tests in <code>tools/test_live_strategy_b.py</code>. Live B PID {esc(b_pid)}. File URL {esc(FILE_URL)}</p>
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
