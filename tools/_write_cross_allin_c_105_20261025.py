"""50-cross extra all-in C<=1.05 AND page. Research live. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
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
PAGE = STAMP / "cross_allin_c_105_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/cross_allin_c_105_20261025.html"
)

ASKED = (
    "Do we also want 50-cross extra only if favorite Yes already under dog AND "
    "the two combined still at or below the 1.05 we have? Yes — wire that AND."
)

PLAIN = (
    "Strategy B already buys one Yes on each tennis player at the first trusted "
    "start (T0), then later may buy one extra ticket on the cheaper player after "
    "that cheaper Yes prints above 50 cents from below. We already skip that extra "
    "unless the original favorite's live Yes is strictly cheaper than the extra we "
    "would pay. The new AND: add up those two live Yes prices plus the house's "
    "documented take-a-trade fees (same all-in C as T0). If that total is over "
    "$1.05, skip the extra and log it. No extra means no later favorite dip from "
    "this illegal cross — we keep the T0 tickets and wait. Patel at 80 cents plus "
    "Kamboj at 81 cents fails both checks. A 52-cent cheaper Yes with a 48-cent "
    "favorite is about $1.03 all-in and still sends. A 52-cent cheaper Yes with a "
    "51-cent favorite is 1 cent under the dog, but fees push the pair over $1.05, "
    "so skip. A 70-cent cheaper Yes with a 40-cent favorite has the favorite under "
    "the dog, but 70 plus 40 is already over $1.05, so skip. We did not sell. "
    "Research-candidate live, not gold, not DailyRun."
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


def table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
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


def main(b_pid: str = "", b_n: str = "1") -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    c_hi = money(live_strategy_b.C_HI)
    d_val = money(live_strategy_b.D)
    fav_token = live_strategy_b.CROSS_FAV_NOT_BELOW
    c_token = live_strategy_b.CROSS_ALLIN_OVER
    t0_token = live_strategy_b.T0_C_OVER_SKIP

    p_8081 = all_in("0.80", "0.81", "polymarket")
    k_5248 = all_in("0.52", "0.48", "kalshi")
    p_5248 = all_in("0.52", "0.48", "polymarket")
    p_5251 = all_in("0.52", "0.51", "polymarket")
    k_5251 = all_in("0.52", "0.51", "kalshi")
    p_7040 = all_in("0.70", "0.40", "polymarket")
    p_5252 = all_in("0.52", "0.52", "polymarket")
    p_t0 = all_in("0.23", "0.80", "polymarket")

    cases = table(
        [
            ("Case", "text"),
            ("Dog Yes", "num"),
            ("Fav Yes", "num"),
            ("Fav under dog?", "text"),
            ("All-in C (Poly)", "num"),
            ("Wired AND", "text"),
        ],
        [
            [
                "Patel / Kamboj tape (fails both)",
                "0.80",
                "0.81",
                f"no — skip {esc(fav_token)}",
                esc(money(p_8081)),
                f"skip (would also hit {esc(c_token)})",
            ],
            [
                "dog 0.52 + fav 0.48",
                "0.52",
                "0.48",
                "yes",
                esc(money(p_5248)),
                f"send (Kalshi all-in {esc(money(k_5248))} ~1.03)",
            ],
            [
                "dog 0.52 + fav 0.51",
                "0.52",
                "0.51",
                "yes (1¢ under)",
                esc(money(p_5251)),
                f"skip {esc(c_token)} (Kalshi {esc(money(k_5251))})",
            ],
            [
                "dog 0.52 + fav 0.52 (tie)",
                "0.52",
                "0.52",
                f"no — skip {esc(fav_token)}",
                esc(money(p_5252)),
                "skip under-dog first",
            ],
            [
                "dog 0.70 + fav 0.40",
                "0.70",
                "0.40",
                "yes",
                esc(money(p_7040)),
                f"skip {esc(c_token)} even though fav is under dog",
            ],
        ],
    )

    knobs = table(
        [
            ("Knob", "text"),
            ("Value", "text"),
            ("Note", "text"),
        ],
        [
            [
                "50-cross extra, gate 1",
                "fav Yes strictly below dog Yes",
                f"Unchanged. REST both Yes asks. Log {esc(fav_token)}. Keep waiting.",
            ],
            [
                "50-cross extra, gate 2 (new AND)",
                f"all-in C ≤ {esc(c_hi)}",
                f"Dog Yes + fav Yes + documented taker fees. Same T0 fee model. Over or fee unknown: log {esc(c_token)}, no extra, no dip from this illegal cross.",
            ],
            [
                "T0 both-Yes all-in C",
                f"≤ {esc(c_hi)}",
                f"Unchanged. Skip {esc(t0_token)}. Patel T0 0.23+0.80 Poly all-in {esc(money(p_t0))}.",
            ],
            [
                "D extra-pair lock",
                d_val,
                "Dip only after a legal cross fill. Illegal cross does not arm the dip.",
            ],
            ["Poly extra order", "FOK, 1 contract", "Unchanged. Fill Or Kill. No partials-as-1."],
            ["Patel ticket", "held", "Did not sell."],
            [
                "Live B",
                f"one process, PID {esc(b_pid)} (n={esc(b_n)})",
                "Hidden spawn via reload_strategy_b. No second live_strategy_b.py. Did not turn E off.",
            ],
            ["Status", "research-candidate live", "Not gold. Not DailyRun."],
        ],
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>50-cross extra all-in C ≤ 1.05 AND — 25 Oct 2026</title>
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
<h1>50-cross extra only if favorite under dog AND all-in C ≤ $1.05</h1>
<p class="note">Written {esc(now)}. Times America/New_York (EDT, UTC−4). Research-candidate live. Not gold. Not DailyRun. Did not sell. No second Strategy B. Did not turn E off. Poly Fill Or Kill (FOK) and T0 all-in C≤{esc(c_hi)} stay. No secrets.</p>

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
<li><strong>Both gates are live.</strong> Before the 50-cross extra, REST both Yes asks. Send only if T0 favorite Yes &lt; dog Yes <em>and</em> all-in C (those two asks + documented taker fees) ≤ {esc(c_hi)}. Same fee model as T0.</li>
<li><strong>Patel 0.80+0.81 fails both.</strong> Favorite 81¢ is not under dog 80¢, so skip <code>{esc(fav_token)}</code> first. All-in would also be {esc(money(p_8081))} &gt; {esc(c_hi)}.</li>
<li><strong>dog 0.52 + fav 0.48 sends.</strong> Favorite is under the dog. Kalshi all-in {esc(money(k_5248))} (~1.03). Poly all-in {esc(money(p_5248))} ≤ {esc(c_hi)}.</li>
<li><strong>dog 0.52 + fav 0.51 skips the new C gate.</strong> Favorite is 1¢ under the dog, so the under-dog gate passes. Poly all-in {esc(money(p_5251))} / Kalshi {esc(money(k_5251))} &gt; {esc(c_hi)}. Log <code>{esc(c_token)}</code>. No extra. No dip from this illegal cross. (Equal 0.52/0.52 still skips <code>{esc(fav_token)}</code>.)</li>
<li><strong>dog 0.70 + fav 0.40 skips even though favorite is under the dog.</strong> Wire 1.10; Poly all-in {esc(money(p_7040))} &gt; {esc(c_hi)}.</li>
<li><strong>Unchanged:</strong> T0 skip <code>{esc(t0_token)}</code>. D={esc(d_val)} dip only after a legal cross fill. Poly FOK. Did not sell. One B.</li>
<li><strong>Status:</strong> research-candidate live. Not gold. Not DailyRun. Live B PID {esc(b_pid)}.</li>
</ul>
</div>

<h2>Wired AND</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns. Tests in <code>tools/test_live_strategy_b.py</code> <code>test_cross_allin_c_105_paul_cases</code>.</p>
{SWIPE_NOTE_HTML}
{cases}

<h2>Live freeze (this knob only)</h2>
{SWIPE_NOTE_HTML}
{knobs}

<p class="note">Prior opponent-under-dog page <a href="patel_kamboj_cross_20261024.html">patel_kamboj_cross_20261024.html</a> left the extra all-in C cap off; this job adds it as the AND. Sources: <code>tools/live_strategy_b.py</code> <code>cross_fav_below_dog</code> / <code>cross_allin_c_ok</code> / <code>{esc(fav_token)}</code> / <code>{esc(c_token)}</code> / <code>maybe_cross</code>. Same T0 helpers <code>t0_all_in_from_asks</code> / <code>t0_leg_fee</code>. Tests <code>test_cross_allin_c_105_paul_cases</code>, <code>test_cross_fav_not_below_dog_skips_and_sends</code>, <code>test_patel_1137_replay_skips_fav_still_above_dog</code>. Live B PID {esc(b_pid)}. File URL {esc(FILE_URL)}</p>
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
