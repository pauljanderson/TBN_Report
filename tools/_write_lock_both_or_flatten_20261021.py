"""One-shot freeze note for both-or-flatten. Does not place orders."""
from __future__ import annotations

import html as html_mod
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP
from report_page_extras import (
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_both_or_flatten_20261021.html"


def th(kind: str, label: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def main() -> None:
    stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lock both-or-flatten — 21 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
ul {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Live lock: both legs or flatten</h1>
<p class="note">America/New_York. Written {html_mod.escape(stamp)}. Research live. Not gold. Not DailyRun. This page does not place or cancel orders. Immediate-or-cancel (IOC) cannot guarantee both fills — that is why flatten exists. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul is looking at Onclin vs Jan-Lennard Struff and says we are still wiring things backwards or still allowing purchases when we do not have both legs of a trade. He bought Onclin at 0.18, never filled Struff; he thought Struff never came to 0.77 (0.18+0.77=0.95). Fix the live lock bot: both legs of the lock or nothing. Do not keep a directional 0.18 Onclin because the other IOC missed. Do not dump the existing 0.18.</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A lock is supposed to buy both sides of the same one-dollar payout so we keep about a nickel no matter who wins. Today the bot sent two immediate-or-cancel orders at once. Only the cheap Onclin ticket filled. The other order missed. The bot then bought another ticket that pays if Onclin wins — the same bet twice — instead of buying Struff or getting out. Going forward: if both books are not actually buyable under 95 cents, send neither. If one fills and one misses, offset the filled ticket right away (flatten). Only if that unwind also misses do we keep watching, and only for a true opposite ticket — never a second copy of the same winner. Immediate-or-cancel still cannot promise both fills; flatten is the safety net.</p>
</div>

<div class="callout warn">
<h2>Onclin vs Struff — ledger facts</h2>
<ol>
<li><strong>Intended claim was a house lock, Yes+No the same player (Struff wins), not dual-Yes Onclin+Struff.</strong> At send 14:41:07 ET: Kalshi Yes Struff quoted 0.75 (websocket, size 42647.76) plus Polymarket No-Struff encoded as Yes-Onclin quoted 0.1700 (websocket, size 43827.48). Claim net 0.93.</li>
<li><strong>Filled:</strong> Polymarket Yes Onclin 0.1700, order D82DDSP010JR, sent 14:41:07.458 ET, HTTP 200. Paul's 0.18 is that 0.17 plus about a 0.01 Polymarket fee. <strong>Missed:</strong> Kalshi Yes Struff ticker KXATPMATCH-26OCT21ONCSTR-STR at 0.7500, HTTP 201, order 01a15fc4-59d0-7301-96f6-f0809fad896d, fill_count 0.00.</li>
<li><strong>At send Struff was not actually takeable at 0.75.</strong> Websocket said 0.75 with huge size; the IOC came back fill_count 0. A Kalshi book two seconds later implied Yes ask about 0.84. The pair was already not both-fillable. A live book recheck would have sent neither.</li>
<li><strong>Wiring backwards: yes, same Goffin pattern.</strong> We bought the cheap dog (Poly Yes-Onclin = Poly encoding of No-Struff) and missed Kalshi Yes-Struff. Leftover then bought Kalshi No on the Struff ticker at 0.84 (No cash 0.16) at 14:41:24 — that is the same bet as Yes-Onclin, not the missing Struff Yes. <code>_watch_already_both</code> treated that same-bet No as lock complete and resumed orders.</li>
<li><strong>Struff Yes did print at 0.77 later.</strong> First Kalshi Struff Yes at or under 0.77 after the fill was 14:58:05 ET at 0.77. Same print for Onclin No. We did not send because leftover had already stacked the same bet and marked the watch done. That is a watch/wiring bug, not a 0.77-never-printed story.</li>
</ol>
<p>Existing Onclin 0.18 (and the wrongly stacked Kalshi No-Struff) is left in place. Paul did not ask to sell it. Going-forward only.</p>
</div>

<div class="callout ok">
<h2>Going-forward freeze (research live)</h2>
<ul>
<li>Send gate: recheck both books immediately before either HTTP. Both need takeable size at least 1 at prices that still net 0.95 or less after documented fees. Empty, no size, or over cap → send neither. Skip is logged to orders.jsonl and job_status last skip reason.</li>
<li>After send: both true-lock fills (Yes+No same player, or dual-Yes two complementary players) keep. One miss → immediately flatten the filled contract (buy the opposite on that same venue/instrument) at the rechecked book. Phone ping on flatten send and result.</li>
<li>If flatten also misses: leftover-watch only a true hedge of the filled player: (a) missed intended instrument in cap, (b) same-player No on another venue, (c) opponent Yes that completes dual-Yes in cap. Never (d) opponent No when we already hold dog Yes.</li>
<li>Strategy B T0 both-Yes is the same both-or-nothing: flatten the filled Yes; independent of the lock latch.</li>
<li>Immediate-or-cancel cannot guarantee both fills. Flatten exists because of that.</li>
</ul>
</div>

<h2>Onclin vs Struff sent legs</h2>
<p class="note">Kalshi bid = buy Yes Struff (the intended lock). Kalshi ask = buy No Struff = Onclin wins (same bet as Polymarket Yes Onclin).</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{th("text", "Game")}{th("date", "Time ET")}{th("text", "Venue")}{th("text", "Instrument")}{th("text", "Book side")}{th("text", "Player")}{th("num", "Limit")}{th("num", "Quote")}{th("text", "Filled")}{th("num", "Fill cash")}{th("text", "Step")}{th("text", "Pays if")}
</tr></thead><tbody>
<tr><td>Onclin vs Struff</td><td>2026-10-21T14:41:07.458-04:00</td><td>polymarket</td><td>aec-atp-gauonc-janstr-2026-10-21</td><td>yes</td><td>Gauthier Onclin</td><td>0.170</td><td>0.1700</td><td>yes</td><td>0.1700</td><td>simultaneous</td><td>win:Onclin</td></tr>
<tr><td>Onclin vs Struff</td><td>2026-10-21T14:41:07.458-04:00</td><td>kalshi</td><td>KXATPMATCH-26OCT21ONCSTR-STR</td><td>yes</td><td>Jan-Lennard Struff</td><td>0.7500</td><td>0.75</td><td>no (fill_count 0.00)</td><td></td><td>simultaneous</td><td>win:Struff</td></tr>
<tr><td>Onclin vs Struff</td><td>2026-10-21T14:41:24.264-04:00</td><td>kalshi</td><td>KXATPMATCH-26OCT21ONCSTR-STR</td><td>no</td><td>Jan-Lennard Struff</td><td>0.8400</td><td>0.1600</td><td>yes</td><td>0.1600</td><td>watch (same bet)</td><td>win:Onclin</td></tr>
</tbody></table></div>

<h2>After-fill tape (cap 0.77)</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{th("text", "What")}{th("date", "When ET")}{th("text", "Venue")}{th("num", "Price")}{th("text", "Note")}
</tr></thead><tbody>
<tr><td>Kalshi Struff Yes at send quote</td><td>2026-10-21T14:41:06.422-04:00</td><td>Kalshi</td><td>0.75</td><td>websocket; IOC then fill_count 0</td></tr>
<tr><td>Poly Onclin Yes fill</td><td>2026-10-21T14:41:07.458-04:00</td><td>Polymarket</td><td>0.17</td><td>plus about 0.01 fee = 0.18 cash</td></tr>
<tr><td>Leftover bought Kalshi No-Struff</td><td>2026-10-21T14:41:24.264-04:00</td><td>Kalshi</td><td>0.16</td><td>same bet as Yes-Onclin; watch marked done</td></tr>
<tr><td>First Struff Yes at or under 0.77 after fill</td><td>2026-10-21T14:58:05.905-04:00</td><td>Kalshi</td><td>0.77</td><td>printed; we did not send</td></tr>
<tr><td>First Onclin No at or under 0.77 after fill</td><td>2026-10-21T14:58:05.905-04:00</td><td>Kalshi</td><td>0.77</td><td>same print; we did not send</td></tr>
</tbody></table></div>

<p class="note">Leftover watch file is gone (already_both resumed). Flatten is in source; running pollers still have the old import until supervisor reload. This job did not kill pollers and did not sell the existing Onclin.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
