"""Patel vs Kamboj 50-cross opponent-under-dog page. Does not place orders."""
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
PAGE = STAMP / "patel_kamboj_cross_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/patel_kamboj_cross_20261024.html"
)

ASKED = (
    "Parv Patel vs Udit Kamboj (Polymarket). I think we bought Patel at a "
    "crossover above 50 at 81¢ around 11:37 PM ET. At that point the opponent "
    "was still at 81¢ too. Restrict buying the crossover to when and if the "
    "opponent has gone under that number."
)

PLAIN = (
    "Strategy B already buys both players at the first trusted tennis start (T0), "
    "then later buys one extra ticket on the cheaper player if that cheaper Yes "
    "prints above 50¢ after having been at or under 50¢. That extra used to fire "
    "as soon as the cheaper Yes crossed 50, even if the other player was still "
    "just as expensive. Tonight we bought extra Patel at 80¢ while Kamboj was "
    "still 81¢ — two expensive tickets at once. The new rule: before buying that "
    "extra, look at both live Yes prices. Buy only if the original favorite is "
    "now cheaper than the extra we would pay. If both are 81, or the favorite "
    "is still 80 while the cheaper side spikes to 81, skip. We did not sell the "
    "Patel ticket we already own. Research-candidate live, not gold, not DailyRun."
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


def all_in(pa, pb) -> Decimal | None:
    spec = {"venue": "polymarket", "fee_coefficient": "0.0695"}
    return live_strategy_b.t0_all_in_from_asks(
        spec, Decimal(str(pa)), spec, Decimal(str(pb))
    )


def main(b_pid: str = "", b_n: str = "1") -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    token = live_strategy_b.CROSS_FAV_NOT_BELOW
    c_hi = money(live_strategy_b.C_HI)
    d_val = money(live_strategy_b.D)
    t0_allin = all_in("0.23", "0.80")
    extra_allin = all_in("0.80", "0.81")

    tape = table(
        [
            ("When ET", "text"),
            ("What", "text"),
            ("Patel Yes", "num"),
            ("Kamboj Yes", "num"),
            ("Fill / qty", "text"),
            ("FOK / partial", "text"),
        ],
        [
            [
                "23:30:00",
                "Listed / trusted T0 clock (seconds=00)",
                "0.22 then 0.23",
                "0.80",
                "—",
                "—",
            ],
            [
                "23:31:11.648",
                "B T0 Patel Yes (dog)",
                "0.23",
                "0.80",
                "1 @ 0.230",
                "Poly FOK, full 1",
            ],
            [
                "23:31:17.695",
                "B T0 Kamboj Yes (favorite; Poly No @ 0.200)",
                "0.23",
                "0.80",
                "1 @ 0.200 No / Yes ask 0.80",
                "Poly FOK, full 1",
            ],
            [
                "23:31:25",
                "Patel Yes jump (still ≤50)",
                "0.47",
                "0.80",
                "no extra",
                "—",
            ],
            [
                "23:35:01.430",
                "First from-below 50-cross on T0 dog",
                "0.46 → 0.80",
                "0.81 (last 23:34:56)",
                "not sent yet",
                "—",
            ],
            [
                "23:37:39.426",
                "Last ticks before extra send",
                "0.80",
                "0.81",
                "—",
                "—",
            ],
            [
                "23:37:44.948",
                "B extra send DA7WQ65011MQ (b-cross)",
                "0.80 book / 0.800 limit",
                "0.81 (not REST-gated)",
                "1 @ 0.800",
                "Poly FOK, full 1, not partial",
            ],
            [
                "23:38:27",
                "Ticks after send",
                "0.80",
                "0.81",
                "holding extra",
                "—",
            ],
        ],
    )

    vs_ui = table(
        [
            ("Source", "text"),
            ("Patel", "text"),
            ("Kamboj", "text"),
            ("What we own", "text"),
        ],
        [
            [
                "Paul / Poly UI now",
                "24% · cost $0.81 to win $1 · qty ~0.22 showing",
                "77%",
                "Patel ticket still held. Did not sell.",
            ],
            [
                "House tape extra",
                "80¢ Yes, FOK qty 1 @ 23:37:44 ET",
                "81¢ Yes at the extra send",
                "T0 Patel 1 @ 23¢ plus extra Patel 1 @ 80¢",
            ],
            [
                "House tape T0",
                "23¢ Yes at 23:31:11",
                "80¢ Yes at 23:31:17 (C wire 1.03)",
                f"All-in C {esc(money(t0_allin))} ≤ {esc(c_hi)} — legal T0",
            ],
        ],
    )

    gates = table(
        [
            ("Case", "text"),
            ("Dog Yes", "num"),
            ("Fav Yes", "num"),
            ("Old B", "text"),
            ("New gate", "text"),
        ],
        [
            [
                "Both 81 (Paul’s read)",
                "0.81",
                "0.81",
                "would send",
                f"skip {esc(token)}",
            ],
            [
                "Patel tape 23:37:44",
                "0.80",
                "0.81",
                "sent FOK 1 @ 0.800",
                f"skip {esc(token)} — favorite not under the dog print",
            ],
            ["Dog 0.52 fav 0.51", "0.52", "0.51", "send", "send"],
            ["Dog 0.52 fav 0.52", "0.52", "0.52", "send", f"skip {esc(token)}"],
            ["Dog 0.52 fav 0.48", "0.52", "0.48", "send", "send"],
            [
                "Dog 50-spike 81, fav still 80",
                "0.81",
                "0.80",
                "send",
                f"skip {esc(token)}",
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
                "50-cross extra",
                "fav Yes strictly below dog Yes",
                f"REST both Yes asks. Log {esc(token)}. No extra if favorite ≥ dog.",
            ],
            [
                "T0 both-Yes all-in C",
                f"≤ {esc(c_hi)}",
                "Unchanged. Same t0_allin_c_over_105 skip. Not a second C cap at the cross.",
            ],
            [
                "Optional extra all-in C at cross",
                "not added",
                f"Patel extra 0.80+0.81 Poly all-in would be {esc(money(extra_allin))}. Paul asked opponent-under-dog, not a second C cap.",
            ],
            [
                "D extra-pair lock",
                d_val,
                "Dip only after a legal cross fill. Patel extra 0.80 → fav target −0.05 (impossible).",
            ],
            ["Poly extra order", "FOK, 1 contract", "Unchanged. Patel extra was full 1, not a partial."],
            ["Patel ticket", "held", "Did not sell."],
            ["Live B", f"one process, PID {esc(b_pid)} (n={esc(b_n)})", "Hidden spawn via reload_strategy_b. No second live_strategy_b.py."],
            ["Status", "research-candidate live", "Not gold. Not DailyRun."],
        ],
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Patel vs Kamboj 50-cross — opponent under dog — 24 Oct 2026</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.callout h2 {{ margin: 0 0 6px; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>50-cross only if the favorite is under the dog</h1>
<p class="note">Written {esc(now)}. Times America/New_York (EDT, UTC−4). Research-candidate live. Not gold. Not DailyRun. Did not sell the Patel ticket. No second Strategy B. Poly FOK and T0 all-in C≤{esc(c_hi)} stay. No secrets.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout warn">
<h2>Verdict</h2>
<ul>
<li><strong>Yes — the extra bought Patel while Kamboj was still as expensive.</strong> House tape fill is <strong>80¢</strong> (not 81¢) at <strong>11:37:44 PM ET</strong>, Poly FOK qty 1, first from-below 50-cross on the T0 dog. Kamboj Yes was <strong>81¢</strong> on the last ticks before and after that send. Paul’s 81/81 read matches the Poly UI cost $0.81; the books were 80/81. Same gap: favorite had not gone under the dog print.</li>
<li><strong>New gate is live:</strong> before the dog extra, REST both Yes asks. Send only if T0 favorite Yes &lt; dog Yes we would pay. Else skip and log <code>{esc(token)}</code>. Keep waiting — do not mark the extra stuck.</li>
<li><strong>T0 was legal.</strong> 23:31 ET Patel 23¢ + Kamboj 80¢, wire C 1.03, all-in {esc(money(t0_allin))} ≤ {esc(c_hi)}. That both-Yes gate is unchanged.</li>
<li><strong>Did not sell.</strong> Patel T0 + extra stay. Dip still uses D={esc(d_val)} only after a <em>legal</em> cross fill (this one would not have been legal).</li>
<li><strong>Status:</strong> research-candidate live. Not gold. Not DailyRun. One B, PID {esc(b_pid)}.</li>
</ul>
</div>

<h2>Tape vs screenshot</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns. Extra send used only the dog book; favorite Yes was not a send gate until this job.</p>
{SWIPE_NOTE_HTML}
{vs_ui}
{SWIPE_NOTE_HTML}
{tape}

<h2>New gate</h2>
<p class="note">Opponent-under-dog is the required gate. A same-time all-in C&gt;1.05 skip at the cross was optional and was <strong>not</strong> added. Tests in <code>tools/test_live_strategy_b.py</code>.</p>
{SWIPE_NOTE_HTML}
{gates}

<h2>Live freeze (this knob only)</h2>
{SWIPE_NOTE_HTML}
{knobs}

<p class="note">Sources: <code>tools/live_strategy_b.py</code> <code>cross_fav_below_dog</code> / <code>{esc(token)}</code> / <code>maybe_cross</code>. Orders <code>DA7SQ91011R3</code> (T0 Patel), <code>DA7ST5S011MC</code> (T0 Kamboj), <code>DA7WQ65011MQ</code> (extra Patel). Watch <code>tennis_patelkamboj_2026_10_25</code>. Price-memory ticks 24 Oct 23:30–23:44 ET. Tests <code>test_cross_fav_below_dog_paul_cases</code>, <code>test_cross_fav_not_below_dog_skips_and_sends</code>, <code>test_patel_1137_replay_skips_fav_still_above_dog</code>. Live B PID {esc(b_pid)}. File URL {esc(FILE_URL)}</p>
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
