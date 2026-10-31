"""Write the one-leg minute-watch page. Does not place an order. Does not commit."""
from __future__ import annotations

import html as html_lib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from report_page_extras import (  # noqa: E402
    CACHE_META,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

import live_lock_orders  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
PAGE = STAMP / "one_leg_minute_watch_20261020.html"
ASKED = (
    "I have noticed that sometimes after we buy one leg in a bet, the bet goes in the right direction, "
    "which means eventually the no bet comes down in price. what if we checked once a minute after we "
    "make our initial attempts and if it comes down to a profitable purchase, then we go ahead and "
    "execute it and turn orders back on"
)
PLAIN = (
    "Sometimes we buy one side of a two-sided lock and the other side does not fill. "
    "New pair attempts stay off so we are not holding two naked legs at once. "
    "Once a minute we look at the leftover side's ask (the price we would pay right now). "
    "If that ask is cheap enough that both sides plus fees still cost $0.95 or less, we send one "
    "immediate-or-cancel for one contract. If it fills, the lock is complete and orders turn back on. "
    "If it misses, we wait another minute. We do not bid above the leftover cap, and we stop watching "
    "if the game is settled or 8:00 AM Eastern Time on October 21, 2026 arrives."
)


def _esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{_esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def _table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(_th(label, kind) for label, kind in headers)
    body = []
    for cells in rows:
        tds = "".join(f"<td>{_esc(cell)}</td>" for cell in cells)
        body.append(f"<tr>{tds}</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _copy_g(path: Path) -> None:
    dest_dir = Path(r"G:\My Drive\paul_experiments\prediction_market_arb_exhaustive_20261017")
    if not (dest_dir.parent.exists() or Path("G:/").exists()):
        return
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest_dir / path.name)
    except OSError:
        return


def write_page(watch: dict | None, reconstruct_note: str, latch_text: str) -> Path:
    watch = watch or {}
    steps = _table(
        [("Step", "num"), ("What happens", "text")],
        [
            ["1", "Simultaneous IOC pair, then the existing recovery walk, still leaves exactly one fill."],
            ["2", "Keep orders_stopped.json so new pairs are not sent. Write raw/one_leg_watch.json with the fill, the missed leg, and max_other_price from the 0.95 cap on the actual fill (cash of the missed leg)."],
            ["3", "About once a minute the supervisor refreshes the missed ask (live websocket last quote if that stream is fresh, else book HTTP). Recheck: other_limit + fill + both fees ≤ 0.95, prices under 1, size 1, unread/short balance fails closed."],
            ["4", "If that ask is ≤ max_other_price, send ONE IOC at min(ask, max). Log quote time vs send time. ntfy because an order HTTP left."],
            ["5", "Fill ≥ 1: both legs done. Clear the watch, delete orders_stopped.json, set ORDERS_ENABLED True in this process, ntfy that orders are on, refresh balances."],
            ["6", "IOC miss: keep watching. Do not walk above the cap. Do not send a higher-than-ask clip unless it is still ≤ max. Wait another minute."],
            ["7", "Stop watching (latch stays on, ntfy once) if the market is closed, the leftover ask can never be profitable, or the 8:00 AM ET deadline on REQUIRED_DEADLINE."],
            ["8", "Supervisor restart resumes the watch file. Latch without a watch keeps orders off. Kalshi 404 shard retries stay 2s / same price / that error only."],
        ],
    )
    freeze = _table(
        [("Knob", "text"), ("Value", "text")],
        [
            ["Size", "1 contract"],
            ["Cap", "fill cash + missed cash + both fees ≤ 0.95, each price < 1"],
            ["Watch cadence", "supervisor loop ~60s; no busy-poll"],
            ["Send price", "min(current ask, max_other_price) and only if ask ≤ max"],
            ["Polymarket No", "pay-side cash (Faria/Nagal). Wire Yes-price is 1 − cash. Max other is cash of the missed leg."],
            ["Latch", "orders_stopped.json stays on while watching; file absent does not restore ORDERS_ENABLED — a completed lock sets it True"],
            ["Second pair", "blocked while the watch or latch is on"],
            ["Deadline", "2026-10-21 08:00 America/New_York"],
        ],
    )
    loaded_rows = [
        ["Game", str(watch.get("game") or "")],
        ["Bet key", str(watch.get("bet_key") or "")],
        ["Filled", f"{watch.get('filled_venue') or ''} {watch.get('filled_side') or ''} {watch.get('filled_instrument') or ''} @ {watch.get('fill_px') or ''} fee {watch.get('fill_fee') or ''}"],
        ["Missed", f"{watch.get('missed_venue') or ''} {watch.get('missed_side') or ''} {watch.get('missed_instrument') or ''}"],
        ["Max other (cash)", str(watch.get("max_other_price") or "")],
        ["Started", str(watch.get("started_at") or "")],
        ["Reconstructed", "yes" if watch.get("reconstructed") else "no"],
        ["Watch status", "stopped" if watch.get("stopped") else ("active" if watch else "none")],
        ["Latch", latch_text],
        ["Reconstruct note", reconstruct_note],
    ]
    loaded = _table([("Field", "text"), ("Value", "text")], loaded_rows)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>One-leg minute watch 2026-10-20</title>
<style>
body {{ margin: 0; padding: 16px 16px 48px; font: 16px/1.45 system-ui, Segoe UI, sans-serif; color: #0f172a; background: #fff; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
p {{ margin: 0.4rem 0 0.7rem; }}
.callout {{ border-left: 4px solid #1d4ed8; background: #f8fafc; padding: 10px 12px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Once-a-minute watch after a one-leg fill</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. This page does not place an order and does not transfer money. The latch file was left as-is.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{_esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{_esc(PLAIN)}</p>
</div>

<h2>How the watch works</h2>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{steps}

<h2>Freeze</h2>
{SWIPE_NOTE_HTML}
{freeze}

<h2>Tonight’s leftover leg</h2>
<p class="note">The latest one-leg on the ledger is Middle Tennessee vs FIU total over 48.5. Kalshi No filled at 0.33 cash. Gemini Yes recovery max was 0.60. Immediate recovery sent 0.58 then skipped a 0.73 book ask as over the cap. That is the open naked leg loaded into the watch file. Latch stays on until the Gemini ask is ≤ 0.60 and an IOC fills, or the watch stops for close/deadline.</p>
{SWIPE_NOTE_HTML}
{loaded}

<p class="note">Related: <a href="architecture.html">architecture.html</a>, <a href="one_leg_note.html">one_leg_note.html</a>, <a href="orders.html">orders.html</a>.</p>
<p class="note">Research only. Not gold. Not DailyRun. Restart leaves the latch. No test order was sent from this page.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    """Keep this filename. The live leftover page is the 20s all-venues write."""
    import _write_one_leg_20s_watch_20261021 as current

    current.main()


if __name__ == "__main__":
    main()
