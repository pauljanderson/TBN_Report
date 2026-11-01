"""Shimizu 50-cross lag report. Research only. Not gold. Not DailyRun.

Does not change P&L or settlement. Does not start a second Strategy B.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP, ensure_dirs  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = DRIVE_STAMP / "b_crossover_lag_shimizu_20261028.html"


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers, rows) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = []
        for i, ((_, kind), val) in enumerate(zip(headers, row)):
            extra = ' class="num"' if kind == "num" else ""
            cells.append(f"<td{extra}>{esc(val)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def main() -> Path:
    ensure_dirs()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    clocks = table(
        [
            ("Clock ET", "text"),
            ("Source", "text"),
            ("Shimizu Yes", "num"),
            ("Hsu Yes", "num"),
            ("All-in C (asks + 2¢+2¢ fees)", "num"),
            ("Would send?", "text"),
            ("What actually happened", "text"),
        ],
        [
            [
                "00:01:02.180",
                "orders.jsonl T0 send",
                "0.46",
                "0.55",
                "1.05",
                "T0 yes (not a 50-cross)",
                "Both Yes filled. Dog is Shimizu at 46¢. Waiting for Shimizu through 50¢ from below.",
            ],
            [
                "00:20:00–00:23:42",
                "price_memory tennis.jsonl (live poller)",
                "<0.50",
                "0.53–0.68",
                "—",
                "No",
                "Memory poller wrote every change (websocket + 5s HTTP fallback). No B-cross send; dog still under 50¢.",
            ],
            [
                "00:23:46.552",
                "orders.jsonl T0 skip (other listing)",
                "—",
                "—",
                "1.1048",
                "n/a",
                "Strategy B tick was already in the tennis-slate T0 hunt (Hsu@Shimizu Novig/Poly skip). maybe_cross for this match had already returned earlier in the same tick.",
            ],
            [
                "00:23:57.410",
                "price_memory first ≥50¢",
                "0.52",
                "0.49",
                "1.05",
                "YES — legal 50-cross",
                "First trusted print of T0-dog through 50¢. Fav 49¢ is below dog. All-in C=1.05. No skip tape. No send.",
            ],
            [
                "00:24:03.038",
                "price_memory (Paul’s 53¢)",
                "0.53",
                "0.48",
                "1.05",
                "YES — legal 50-cross",
                "Still legal. B was still walking other T0 skips (00:24:00 Novig Shimizu vs Hsu, 00:24:19 Tabur).",
            ],
            [
                "00:24:23.408",
                "price_memory",
                "0.53",
                "0.50",
                "1.07",
                "No — C>1.05",
                "Would skip cross_allin_c_over_105 if REST had run. Silent on tape because maybe_cross never reached this pair.",
            ],
            [
                "00:25:14.330",
                "price_memory",
                "0.61",
                "0.40",
                "1.05",
                "YES — legal again",
                "Second legal window after 00:23:57. Still no send. Slate hunt continued.",
            ],
            [
                "00:26:20.575",
                "orders.jsonl T0 skip Wolf vs Milavsky",
                "—",
                "—",
                "1.0824",
                "n/a",
                "Same second as the 0.63/0.38 memory print. Proof the sender was still REST-hunting T0s, not watching the 50-cross.",
            ],
            [
                "00:26:20.965",
                "price_memory",
                "0.63",
                "0.38",
                "1.05",
                "YES — the send pair",
                "Same 63¢/38¢ pair the later REST send used. 39s before orders.jsonl cross send.",
            ],
            [
                "00:26:46.414",
                "price_memory (same quote rewrite)",
                "0.63",
                "0.38",
                "1.05",
                "YES",
                "price_memory rewrites the same pay-price after 20s. Still no send.",
            ],
            [
                "00:26:59.999",
                "orders.jsonl cross send",
                "0.63",
                "0.38",
                "1.05",
                "Sent",
                "Only cross tape for this game: action=send reason=ok. quote_seen_at=00:26:59.999.",
            ],
            [
                "00:27:00.289",
                "venue fill",
                "0.60 fill + 0.02 fee",
                "—",
                "—",
                "Filled 1",
                "Limit 63¢, fill 60¢+2¢. 3m 3s after first 50¢ memory tick. Book had already moved 52¢→63¢.",
            ],
        ],
    )
    gates = table(
        [("Gate", "text"), ("This game", "text"), ("Blocked the 00:23:57 send?", "text")],
        [
            ["C ≤ 1.05 (asks + documented taker fees)", "0.52+0.49+0.02+0.02=1.05 at first 50¢ tick", "No. Legal. HOLD on C=1.05 as a profit number."],
            ["Favorite Yes strictly below dog Yes", "Hsu 0.49 < Shimizu 0.52", "No."],
            ["Skip-if already filled this cross", "cross_ioc_sent was false until 00:27", "No."],
            ["Sequential ORDER_LOCK / one-process B", "One live_strategy_b.py. Confirm after T0 was long ago (00:01).", "No. The lock did not hold this send."],
            ["IOC / FOK 1 contract", "Sent FOK→IOC size 1 when it finally ran", "No. That is the send, not the wait."],
            ["Need both quotes", "Memory had both Yes at 00:23:57", "No for detection. REST confirm still required before send (kept)."],
            ["Must see prev<50 then ≥50 on the SAME loop", "Only after a miss (cross_need_reset). First up-cross does not need both prints on one REST loop.", "No. First cross: ask>0.50 is enough."],
            ["Debounce / only-once", "_tape_once is skip-row de-dupe, not a send delay", "No."],
            ["T0_GRACE (5 minutes)", "T0 window only. Cross has no grace clock.", "No."],
            ["REST recheck backoff", "Confirm-before-send is required. The bug was using REST as the *detector* inside a 3-minute T0-slate walk.", "Yes — the wait, not the confirm."],
            ["Windows sleep / cmd polling", "loop slept 1s *after* each tick. Tick itself lasted ~3 minutes. Not a 3-minute scheduled --tick.", "Sleep is 1s. The 3m is tick duration."],
            ["Poller cadence", "live_game_pollers worker: websocket + HTTP fallback 5s. SAME_QUOTE_SEC=20 only rewrites an unchanged price.", "No. Memory saw 52¢ at 00:23:57. Sender ignored it."],
        ],
    )
    before_after = table(
        [("Slice", "text"), ("Before (this game)", "text"), ("After the patch", "text")],
        [
            [
                "Who notices T0-dog ≥50¢",
                "maybe_cross REST-fetched the book once per Strategy B tick. Memory ticks were pumped into _series but not used to fire the extra.",
                "latest_yes / price_memory tick. If dog Yes is still ≤50¢, no REST. First print >50¢ → REST both books now → send now.",
            ],
            [
                "Loop that is allowed to SEND",
                "live_strategy_b.loop → tick() → process_open → maybe_cross. Intended cadence TICK_SEC=1. Actual tick walked the whole tennis slate with try_t0 REST (Kalshi/Gemini/Poly/Novig, EVENT_CACHE 20s) while open < 4.",
                "tick() processes 50-cross watches first. tick_cross_only pumps memory every 50ms while a cross is armed. T0 hunt is time-boxed (0.2s while waiting on a 50-cross, 1.0s otherwise) and re-checks the cross after each T0 probe.",
            ],
            [
                "REST confirm-before-send",
                "fetch_book_ask(pace=True) waited on the shared venue slot, and only ran when maybe_cross ran — minutes later.",
                "Still required. Inline, pace=False (skip the shared slot). Sub-second HTTP, not the next slate loop.",
            ],
            [
                "Expected time, first 50¢ memory tick → send attempt",
                "3m 3s (00:23:57.410 → 00:26:59.999). Fill 0.29s after that.",
                "Sub-second to a few seconds: memory pump (≤50ms idle) + two unpaced book GETs + IOC. Not 180s.",
            ],
            [
                "Double-send / skip-if filled",
                "One send this game (good).",
                "Unchanged: stage leaves CROSS_STAGES after a fill; extra_stuck / cross_need_reset after a miss. Tests: 0.49 does not send; 0.52 sends once.",
            ],
        ],
    )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>B crossover lag — Shimizu vs Hsu 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; padding: 0 0 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
td.num {{ text-align: right; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>B crossover lag — Shimizu vs Hsu</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now)}. Research only. Not gold. Not DailyRun. C=1.05 HOLD. Did not retune stake, D NFL, leftover GTC, or P&amp;L/settlement.</p>

<div class="callout">
<h2>What you asked</h2>
<p>The 3-minute Shimizu crossover delay is 100% unacceptable. Close the crossover as soon as we see it. Explain why it took 3m 3s, then fix so the send is as close as possible to the first 50¢ cross. Memory first saw Shimizu 52¢ at 00:23:57 (Hsu Yes 49¢). Paul’s 53¢ is 00:24:03. Only cross tape send 00:26:59.999 dog Yes 0.63 fav Yes 0.38 all-in C=1.05. Fill 60¢+2¢ at 00:27:00.289. Late part is 3m 3s from first 50¢ memory tick to REST send while book 52¢→63¢ — not a skipped name.</p>
<h2>In plain English</h2>
<p>We already knew Shimizu’s Yes had crossed 50 cents. The bot that is allowed to buy waited, then bought 11 cents worse. The fast tape (the live poller) saw 52¢. The slow worker (Tennis crossover / Strategy B) was busy checking other tennis matches for a T0 buy and only looked at Shimizu’s live book again three minutes later. Confirm-before-send stays — but it has to be “check the book right now,” not “wait for the next three-minute lap.”</p>
</div>

<div class="warn">
<p><strong>Verdict.</strong> Not a skipped name. Not C=1.05 blocking the first print. The architecture was dense memory + a REST sender that only ran once per long <code>tick()</code>. On this game that tick was a full tennis-slate T0 hunt. First legal 50-cross was 00:23:57 at 52¢/49¢ (all-in C=1.05). Send was 00:26:59 at 63¢/38¢. We paid 11¢ extra on the extra Yes.</p>
</div>

<h2>Walk this game’s clocks</h2>
<p>Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{clocks}

<h2>Why 3m 3s</h2>
<p>Two loops. <strong>Memory:</strong> <code>live_game_pollers</code> worker for this Polymarket tennis moneyline (websocket compare, 50ms coalesce, HTTP fallback every 5s) wrote <code>raw/price_memory/2026-10-28/tennis.jsonl</code>. That is the 00:23:57.410 Shimizu 0.52 / Hsu 0.49 print. Cadence is seconds, not minutes.</p>
<p><strong>Sender:</strong> only <code>live_strategy_b.maybe_cross</code> may send a 50-cross. It did not read that memory print. It REST-fetched the dog book (<code>recheck_yes</code> → <code>fetch_book_ask</code>, paced) once per <code>tick()</code>. The intended sleep is 1s (<code>TICK_SEC=1</code>). The actual tick, when <code>currently_open &lt; 4</code>, walked <em>every</em> other tennis listing with <code>try_t0</code> → <code>moneyline_yes_books</code> / <code>_fetch_events</code> (Kalshi + Gemini + Polymarket + Novig, 20s event cache). Skip rows from that hunt sit on the tape through the whole window: 00:23:46 Hsu@Shimizu, 00:24:00 Shimizu vs Hsu Novig, 00:24:19 Tabur, 00:26:13 Guillen, 00:26:17 Mayo, 00:26:20 Wolf. <code>maybe_cross</code> had already run at the <em>start</em> of that tick, before 00:23:57, when REST was still ≤50¢ (silent — <code>extras_cross_ready</code> failures do not tape). The next <code>maybe_cross</code> is the 00:26:59.999 send. 00:23:57.410 → 00:26:59.999 = 3m 2.589s, rounded 3m 3s.</p>

<h2>Why the extra 39s after 00:26:20</h2>
<p>Memory already showed the send pair 0.63 / 0.38 at 00:26:20.966. The same second, B taped a T0 skip on Wolf vs Milavsky. So the sender was still inside the slate walk. The rest of that tick (more T0 probes that <code>_tape_once</code> hid, plus <code>note_settled_holds</code> → <code>venue_snapshot</code> up to 60s cache miss, plus the 1s loop sleep) ran out around 00:26:59. Next tick’s <code>maybe_cross</code> REST-saw 0.63/0.38 and sent. 39s is leftover of the same long tick, not a second gate.</p>

<h2>Gates (this game)</h2>
{gates}

<h2>What changed</h2>
<ul>
<li><code>tools/live_strategy_b.py</code> — memory tick of T0-dog Yes &gt; 50¢ wakes an immediate unpaced REST recheck of both Yes books, then IOC/FOK. If memory is still ≤50¢, skip REST. <code>tick()</code> processes 50-cross watches <em>before</em> postponed REST and before T0 hunting. T0 hunt is time-boxed and re-pumps memory after each probe. While a 50-cross is armed, the loop idles 50ms and runs <code>tick_cross_only</code> (no slate walk, no venue snapshot). Confirm-before-send stays. One contract. C=1.05 skip-if-over stays. Skip-if already filled stays.</li>
<li><code>tools/test_live_strategy_b.py</code> — Shimizu replay: 00:23:57 0.52 sends immediately with mock REST (no 180s sleep); 0.49 does not send and does not REST; second call does not double-send. T0-arm budget shrinks while waiting on a 50-cross.</li>
<li>Did not touch <code>write_dashboard.py</code>, fill cash, or settlement. Did not start a second B process from this writer.</li>
</ul>

<h2>Before vs after expected latency</h2>
{before_after}

<p>Poller cadence was not the 3-minute hole and was not slowed. Live T0 dog (E) / <code>live_t0_yes.py</code> is a different send path and was not retuned.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html_out, encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = main()
    print(path)
