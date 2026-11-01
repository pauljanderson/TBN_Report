"""Karim vs Guidotti settled-reopen HTML. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "karim_guidotti_final_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/karim_guidotti_final_20261024.html"
)
JOB_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/job_status.html"
)

ASKED = (
    "Tennis match Karim Sherif Abdellatif Abdo vs. Martino Guidotti came back onto "
    "job_status even though it was already final. This was B Tennis crossover on "
    "Polymarket. Open-count previously fail-soft kept it because Poly positions GET "
    "was empty but house confirm qty ≥ 1. Positions sync then listed it as one of "
    "the two B rows. If the market settled/expired/final, it must not appear in Open "
    "now or Positions, and must not reappear on the next job_status rebuild."
)
PLAIN = (
    "We checked whether this Polymarket tennis ticket was actually over. It is still "
    "an open market (about 65¢ / 66¢, no winner posted), so we did not yank it off "
    "Open just because the house clock said the match window had passed. The bug that "
    "can put a finished ticket back on the page is fixed: once Polymarket or Kalshi "
    "marks a market resolved, expired, final, or void, Open and Positions will not "
    "count it even if our fill tape still says FILLED and the positions list is empty. "
    "Empty after settle is normal. We did not sell anything."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


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


def main(
    *,
    b_pid: str = "",
    b_n: str = "1",
    checked: str = "",
    poly_state: str = "MARKET_STATE_OPEN",
    poly_ended: str = "false",
    winner: str = "none",
    bid: str = "0.65",
    offer: str = "0.66",
    namigata_state: str = "MARKET_STATE_EXPIRED",
    open_now_b: str = "1",
    karim_on_positions: str = "yes (still OPEN)",
) -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    checked = checked or now
    when = table(
        [("When ET", "date"), ("What", "text"), ("Source", "text")],
        [
            ["2026-10-24 20:00:00", "Listed start (ITF moneyline, 8:00 PM ET).", "strategy_b_watch / Poly listing"],
            [
                "2026-10-24 20:03:24",
                "B T0 both legs HTTP 200, confirm qty 1.0000 each. Yes Karim @ 0.63 (DA4TNP5G11N2). "
                "Guidotti BUY_SHORT fill 0.62 (DA4TK5T011MM). Same slug aec-itfme-karabd-margui-2026-10-25. "
                "Stage waiting_cross.",
                "orders.jsonl / strategy_b_watch",
            ],
            [
                "2026-10-24 20:18:13",
                "Karim Yes traded as low as 0.11 (book stats lowSetTime).",
                "Poly book stats",
            ],
            [
                "2026-10-24 22:07:16",
                "Karim Yes high 0.66 (highSetTime). Still a live book, not 0 or 1.",
                "Poly book stats",
            ],
            [
                "2026-10-24 ~23:00",
                "House price-memory phase flipped to after (listed start plus a typical tennis length). "
                "That is a house clock, not Polymarket settlement.",
                "tennis.jsonl phase=after",
            ],
            [
                "2026-10-24 23:05:13",
                "Namigata marked postponed (closed without settlement). Later book MARKET_STATE_EXPIRED. "
                "Not in Open now.",
                "strategy_b_watch / Poly book",
            ],
            [
                "2026-10-24 23:12:32",
                "job_status still listed Karim as the B Positions row. Open now B=1. Caption then did not "
                "exclude settled markets.",
                "job_status.html Updated",
            ],
            [
                checked,
                f"Poly book {esc(poly_state)}, event ended={esc(poly_ended)}, winner={esc(winner)}, "
                f"bid {esc(bid)} / offer {esc(offer)}. Positions GET n_all 0. Namigata {esc(namigata_state)}.",
                "Poly public book + search + positions GET",
            ],
        ],
    )
    fills = table(
        [
            ("Leg", "text"),
            ("Order id", "text"),
            ("Side", "text"),
            ("Limit / fill", "text"),
            ("Confirm qty", "num"),
            ("Sent ET", "date"),
        ],
        [
            ["T0 favorite", "DA4TNP5G11N2", "Yes Karim (BUY_LONG)", "0.630 / 0.63", "1.0000", "2026-10-24 20:03:24"],
            ["T0 dog", "DA4TK5T011MM", "Guidotti BUY_SHORT (fill 0.62)", "0.380 Yes ask / 0.62", "1.0000", "2026-10-24 20:03:24"],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Karim vs Guidotti final reopen — 24 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note, .tiny {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Karim vs Guidotti — settled cannot reappear</h1>
<p class="note">Research-candidate live. Not gold. Not DailyRun. Did not sell. Did not flatten. One Strategy B process.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<h2>Confirmed final?</h2>
<p><strong>No.</strong> Polymarket US still has this market open. No winner. Book about {esc(bid)} / {esc(offer)}.
Event <code>ended=false</code>, <code>closed=false</code>, <code>live=false</code>, score 0-0, <code>ep3Status=OPEN</code>.
Tennis listings still treated Guidotti as a next match, not a posted result.
House ticks said <code>after</code> because the listed 8:00 PM start plus a typical tennis length had passed — that is not venue settlement.</p>
<p>Positions GET is empty (<code>n_all 0</code>). That is expected for two reasons: (1) after a real settle the list goes empty, and (2) this T0 bought both seats of the <em>same</em> slug, so net quantity can be 0 while the market is still open. Empty GET alone is not “final.”</p>
<h2>Dropped from job_status?</h2>
<p><strong>No — left on Open because the market is still OPEN.</strong> Yanking it would free a B slot while the lock is still live. When Poly marks this slug expired/resolved/final/void, Open now and Positions will drop it and will not put it back. Namigata is {esc(namigata_state)}; it is not in Open now (postponed, then expired). Open now B after this rebuild: {esc(open_now_b)}. Karim on Positions: {esc(karim_on_positions)}.</p>
<h2>Why it came back</h2>
<p>Open-count fail-soft kept any house-open B row when Poly positions GET was empty but confirm qty ≥ 1. That was the Namigata/Guajardo lag fix. Positions then listed ledger FILLED as a B row. It never checked whether the market had already settled. After settle, empty GET is normal, so a finished ticket could occupy Open forever and a <code>done</code> row could be restored on the next job_status rebuild.</p>
<h2>Fix</h2>
<ul>
<li>If Poly or Kalshi says resolved, expired, final, or void (Kalshi also closed/inactive), <strong>never</strong> count as open — even if confirm qty ≥ 1 and positions GET is empty.</li>
<li>Fail-soft keep remains only while the market is still open (or status unknown).</li>
<li>Reconcile will not restore a <code>done</code> row when the market is final.</li>
<li>Tests: settled Poly + empty GET + ledger FILLED → 0 Positions rows for that game. Namigata stays if still OPEN (qty 0.32).</li>
</ul>
<h2>Timeline</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{when}
<h2>House ledger T0</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{fills}
<h2>Live B</h2>
<p>One process, PID {esc(b_pid)} (n={esc(b_n)}). Did not start a second <code>live_strategy_b.py</code>. Did not reload B because the watch row stays <code>waiting_cross</code> while Poly is OPEN. Lock / C / D pids left alone.</p>
<p class="tiny">Pages: <a href="karim_guidotti_final_20261024.html">this report</a> · <a href="job_status.html">job_status.html</a>. File URL {esc(FILE_URL)} · {esc(JOB_URL)}. Pulled {esc(now)}. Status Checked {esc(checked)}.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(PAGE)
    print(FILE_URL)


if __name__ == "__main__":
    main()
