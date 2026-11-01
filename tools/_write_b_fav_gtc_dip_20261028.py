"""Strategy B favorite-dip GTC wire note. Research only. Not gold. Not DailyRun."""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import live_strategy_b  # noqa: E402
from prediction_paths import DRIVE_STAMP, RAW, ensure_dirs  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = DRIVE_STAMP / "b_fav_gtc_dip_20261028.html"

ASKED = (
    "let's go ahead and implement GTC for the dip once we get the crossover on system B"
)

PLAIN = (
    "After Strategy B buys the original underdog when that Yes goes through 50 cents, "
    "it still wants one more Yes on the original favorite, cheap enough to lock 25 cents "
    "on that extra pair. That price is $1 minus the 50-cross fill minus 25 cents — not "
    "“cross minus 25 cents.” Example: Shimizu fills at 60 cents → Hsu Yes GTC at 15 cents. "
    "Until now the bot waited and sent an immediate-or-cancel (IOC) only if Hsu’s ask was "
    "already 15 cents or lower. Hsu’s live Yes stayed at or above 38 cents, so that IOC "
    "never fired. Wired now: as soon as the 50-cross fills, rest one 1-contract good-til-canceled "
    "(GTC) buy at 15 cents. If the favorite is already at or below the target, take it now "
    "with today’s IOC / fill-or-kill (FOK). Do not send both. Cancel the rest if the match "
    "absorbs, settles, or is postponed. Not gold. Not DailyRun."
)


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
        for (_, kind), val in zip(headers, row):
            extra = ' class="num"' if kind == "num" else ""
            cells.append(f"<td{extra}>{esc(val)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def b_pid() -> str:
    path = RAW / "strategy_b.pid"
    if not path.exists():
        return "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.read_text(encoding="utf-8")[:80]
    return str(data.get("pid") or "")


def main() -> Path:
    ensure_dirs()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    pid = b_pid()
    platforms = table(
        [
            ("Platform", "text"),
            ("GTC resting TIF", "text"),
            ("Today’s take (T0 / 50-cross / at-target dip)", "text"),
            ("Dip GTC wired?", "text"),
            ("Notes", "text"),
        ],
        [
            [
                "Kalshi",
                "time_in_force=good_till_canceled",
                "immediate_or_cancel",
                "Yes",
                "No expiration_time. post_only stays false so the bid can take when the ask falls.",
            ],
            [
                "Gemini predictions",
                "timeInForce=good-til-cancel",
                "immediate-or-cancel",
                "Yes",
                "makerOrCancel false (not post-only). Same POST /v1/prediction-markets/order.",
            ],
            [
                "Polymarket US",
                live_lock_orders.POLY_TIF_GTC,
                live_lock_orders.POLY_TIF_FOK,
                "Yes",
                "Dip GTC is not FOK. Displayed ask size is not a skip (this is a rest, not a take). House cash still uses the BUY_SHORT debit, not Yes-wire.",
            ],
            [
                "Novig",
                "tif=GTC",
                "tif=IOC",
                "Yes, when Novig orders are live",
                "Do not wait_order_terminal on a GTC rest. Confirm later with GET fills. Lock leftover GTC is not wired.",
            ],
        ],
    )
    hsu = table(
        [
            ("Step", "text"),
            ("Price", "num"),
            ("Old IOC dip", "text"),
            ("Wired GTC dip", "text"),
        ],
        [
            [
                "T0 favorite Hsu Yes / dog Shimizu Yes",
                "0.55 / 0.46",
                "Both Yes filled. Wait for Shimizu through 50¢ from below.",
                "Unchanged. 50-cross is still ping-and-wait, not a GTC at 51¢.",
            ],
            [
                "Legal 50-cross fill (Shimizu Yes)",
                "0.60",
                "Stage waiting_fav_dip. Target 1 − 0.60 − 0.25 = 0.15. No order yet.",
                "Same target 15¢. Immediately REST-recheck Hsu Yes, then rest one GTC buy at 15¢ (qty 1).",
            ],
            [
                "Hsu Yes min print this match",
                "0.38",
                "38¢ > 15¢, so IOC never sent. Sat in waiting_fav_dip until absorb/settle.",
                "GTC already resting at 15¢. Does not need a 15¢ print first. Does not send a second IOC.",
            ],
            [
                "If Hsu ask were already ≤ 15¢",
                "≤0.15",
                "IOC / FOK at the live ask, one shot.",
                "Same: fill now with IOC/FOK. Do not also rest GTC.",
            ],
            [
                "Absorb / settle / postponed / game over",
                "—",
                "Stop watching. No resting order id to cancel.",
                "Cancel the GTC. Skip-if already filled. Confirm fill with the platform; persist house cash.",
            ],
        ],
    )
    tests = table(
        [
            ("Test", "text"),
            ("What it checks", "text"),
            ("Result", "text"),
        ],
        [
            [
                "test_hsu_gtc_rests_at_15c_after_60c_cross",
                "Mock cross fill 0.60, Hsu ask 0.38 → one GTC at 0.15. Second call does not send again.",
                "pass",
            ],
            [
                "test_fav_already_at_target_uses_ioc_not_gtc",
                "Ask already 0.15 → IOC, not GTC. Stage done. House cash persisted.",
                "pass",
            ],
            [
                "test_gtc_not_rested_when_extra_pair_net_fails",
                "extra_pair_net_ok False → do not rest. No IOC loop.",
                "pass",
            ],
            [
                "test_absorb_cancels_resting_fav_gtc",
                "Absorb cancels the resting GTC order id.",
                "pass",
            ],
            [
                "test_poly_fav_gtc_tif_is_not_fok",
                "Poly dip body tif is TIME_IN_FORCE_GOOD_TILL_CANCEL. No cancel of a still-open GTC.",
                "pass",
            ],
            [
                "test_venue_gtc_tif_strings",
                "Kalshi / Gemini / Poly / Novig GTC strings. Lock-A / T0 builders stay IOC/FOK.",
                "pass",
            ],
        ],
    )
    freeze = table(
        [
            ("Knob", "text"),
            ("Value", "text"),
            ("This job", "text"),
        ],
        [
            ["D (extra-pair lock profit)", "0.25", "Unchanged"],
            ["fav_target", "1 − cross_fill − D", "Unchanged formula. 0.60 → 0.15, not 0.35."],
            ["C all-in", "1.05", "Unchanged. Not retuned."],
            ["Stake / size", "1 contract", "Unchanged"],
            ["Leftover GTC on lock A", "not wired", "Did not wire"],
            ["D NFL / System E / second B", "leave alone", "Did not retune. Reloaded the existing B pid only."],
            ["Venue fill + venue settle", "sibling", "Did not revert"],
        ],
    )
    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Strategy B favorite-dip GTC — 28 Oct 2026</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.ok {{ background: #f0fdf4; padding: 10px 12px; border: 1px solid #86efac; margin: 12px 0; }}
.warn {{ background: #fffbeb; padding: 10px 12px; border: 1px solid #fbbf24; margin: 12px 0; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Strategy B favorite-dip GTC is wired</h1>
<p class="note">America/New_York. Written {esc(now)}. Research-candidate live on Tennis crossover (system B) only. Not gold. Not DailyRun. Click column headers to sort.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="ok">
<p><strong>Wired: yes, Strategy B only.</strong> After a legal 50-cross fill (step b-cross), B immediately REST-rechecks the original favorite Yes and rests <strong>one</strong> 1-contract GTC buy at <code>fav_target = $1 − cross_fill − 0.25</code>. Live B pid after reload: <code>{esc(pid)}</code> (one process). Lock leftover GTC is not wired. C=1.05, D=0.25, stake, E, and a second B were not touched.</p>
</div>
<h2>Hsu / Shimizu walk</h2>
<p>Shimizu 50-cross fill 60¢ → Hsu Yes GTC at <strong>15¢</strong> (<code>1 − 0.60 − 0.25</code>). Not 35¢. Hsu’s live Yes never printed 15¢ (min 38¢), so the old IOC wait did nothing. The same replay now rests the 15¢ GTC as soon as the cross fills.</p>
{SWIPE_NOTE_HTML}
{hsu}
<div class="warn">
<p><strong>extra_pair_net_ok still:</strong> the extra pair after documented fees must stay ≤ $1 − D (75¢). If a GTC at the target would violate that, it is not rested (tape reason, no IOC loop). Tests that rest Hsu 15¢ mock that gate true, matching other B dip tests. A live Poly 60¢ + 15¢ + taker fee is over 75¢, so that exact Hsu pair would skip unless fees fit — same 25¢ lock as today’s IOC, not a retune of D.</p>
</div>
<h2>Platforms</h2>
{SWIPE_NOTE_HTML}
{platforms}
<h2>Freeze / what this job did not do</h2>
{SWIPE_NOTE_HTML}
{freeze}
<h2>Tests</h2>
<p class="note"><code>python tools/test_live_strategy_b.py</code> — ok. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
{tests}
<h2>Send path</h2>
<ul>
<li><code>maybe_cross</code> still IOC/FOKs the 50-cross. On a house fill it sets <code>fav_target</code> and, in the same <code>process_open</code> tick, calls <code>maybe_fav_dip</code>.</li>
<li><code>maybe_fav_dip</code>: REST recheck inline (not a 3-minute loop). Ask already ≤ target → <code>send_yes_ioc</code>. Else <code>send_yes_gtc</code> at the target. Stage <code>waiting_fav_dip</code> becomes <code>fav_gtc_resting</code>. <code>fav_ioc_sent</code> blocks a second send.</li>
<li>Cancel on absorb / venue settle / postponed. Confirm later fills with the platform. Persist house cash (<code>_actual_fill_cash</code>; Poly BUY_SHORT debit, not Yes-wire).</li>
<li>Lock A order bodies are still IOC/FOK. Novig GTC does not poll <code>wait_order_terminal</code>.</li>
</ul>
<p class="note">Sources: <code>tools/live_strategy_b.py</code> <code>maybe_fav_dip</code> / <code>send_yes_gtc</code> / <code>fav_target</code>; <code>tools/live_lock_orders.py</code> TIF helpers (IOC/FOK defaults unchanged); tests in <code>tools/test_live_strategy_b.py</code>. Prior notes: <a href="gtc_stop_feasibility_20261022.html">GTC feasibility</a>, <a href="live_architecture_20261028.html">live architecture</a> (GTC dip was discuss-only). {esc(PAGE.as_posix())}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html_out, encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = main()
    print(path)
