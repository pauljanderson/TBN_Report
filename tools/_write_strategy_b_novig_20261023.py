"""Strategy B Novig send-venue note. Research page. Does not place orders."""
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
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "strategy_b_novig_20261023.html"

ASKED = (
    "Paul: why do we not use Novig for Strategy B? I think we should."
)
PLAIN = (
    "Strategy B is the tennis start play: buy Yes on both players at the first "
    "trusted serve, then later buy extra of the underdog if he prints above 50 "
    "cents, then the original favorite cheap enough that the extra pair still "
    "locks in 25 cents. Until today B was only allowed to send those tickets on "
    "Kalshi, Gemini, and Polymarket US. Novig was already a live send venue for "
    "the other bot (the Yes+No gap lock bot). Paul overrode that freeze. B may "
    "now send Novig too, still one contract, Immediate or Cancel, at most two "
    "open B matches. We did not change the 25-cent extra-pair profit, and we "
    "did not start a second Strategy B."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def main() -> None:
    venues = ", ".join(live_strategy_b.VENUE_ORDER)
    rows = [
        ("Why it was off", "A freeze in live_strategy_b.py, not a risk finding. VENUE_ORDER was Kalshi / Gemini / Polymarket US only. Comments said “never sent by Strategy B” / “Novig is quoted never-sent.” Dual-Yes T0 and the favorite dip never built a Novig leg. Lock-bot already had Novig send + GET /v3/portfolio/fills confirm."),
        ("What changed", "VENUE_ORDER now includes Novig. B may send T0 both-Yes, the later favorite dip, leftover Yes, and a same-venue flatten on Novig when Novig orders are live (switch + trading key)."),
        ("Unchanged", f"Size {live_strategy_b.SIZE} contract. Immediate or Cancel. D={live_strategy_b.D} extra-pair lock profit. Combined Yes C in [{live_strategy_b.C_LO}, {live_strategy_b.C_HI}]. Each Yes in ({live_strategy_b.YES_LO}, {live_strategy_b.YES_HI}). Dog must print strictly above {live_strategy_b.CROSS} before the extra. MAX_OPEN_B_MATCHES={live_strategy_b.MAX_OPEN_B_MATCHES}. No GTC. Do not sell existing tickets. Lock-bot Novig path reused, not rewritten."),
        ("Send rules on Novig", "Same as other B venues: 1 contract, IOC, REST book recheck before every send, then venue confirm GET /v3/portfolio/fills before treating as a fill. Named deny if Novig cash is too low (historically ~$10). A $0 read is not cached forever."),
        ("Venues B may send today", venues),
        ("Promotion", "Research live. Not gold. Not DailyRun."),
    ]
    head = "".join(th(label, kind) for label, kind in (("Topic", "text"), ("Now", "text")))
    body = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in rows)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy B may send Novig — 2026-10-23</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Strategy B may send Novig</h1>
<p class="note">Written {esc(datetime.now(ET).isoformat(timespec="seconds"))}. Research live. Not gold. Not DailyRun. 1 contract. Immediate or Cancel. D stays 0.25. Max open B matches stays 2.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<h2>Why it was off</h2>
<p>The only reason in code, comments, and the layman field guide was a freeze: B never constructed Novig legs. <code>VENUE_ORDER</code> listed Kalshi, Gemini, and Polymarket US. Status text said <code>novig_orders: never sent by Strategy B</code>. The dual-Yes T0 picker and the later favorite-dip send used that list, so Novig Yes books were never a B send venue. Novig was already live on the lock bot. There is no separate risk memo, fee block, or “Novig tennis is unsafe” comment. Paul overrode the freeze.</p>
<h2>It is on now</h2>
<p>Strategy B may send Novig for T0 both-Yes, the later favorite dip, leftover missed-player Yes, and a same-venue flatten if B flattens on Novig. Same rules as the other B venues. Post-order truth is Novig <code>GET /v3/portfolio/fills</code>, not the order tape alone.</p>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>{body}</tbody>
</table></div>
<p class="note">Acronyms: T0 is the trusted match start used here. C is the two T0 Yes prices added together. IOC is Immediate or Cancel (fill now or cancel; nothing rests). D is the 25-cent lock profit on the extra post-cross pair. REST is the ordinary HTTP book read before a send.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)


if __name__ == "__main__":
    main()
