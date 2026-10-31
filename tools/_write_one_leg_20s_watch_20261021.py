"""Write the one-leg 20-second all-venues watch page. Does not place an order. Does not commit."""
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
import novig_live  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
PAGE = STAMP / "one_leg_20s_watch_20261021.html"
OLD_PAGE = STAMP / "one_leg_minute_watch_20261020.html"
ASKED = (
    "let's adjust this plan accordingly [one_leg_minute_watch_20261020.html]. If there is only one fill, "
    "that fill is likely to move in price. we should do the following as it does. we should check all of "
    "the venues for the opposite bet including the one that took the initial leg. let's do that every 20 "
    "seconds. IF the opposite bet shows us a 0.05 profit, we sequentially try to place that bet on each "
    "venue. if the first one fills, we stop trying, if it doesn't we keep trying. if none fill, we wait "
    "20 seconds and try again. make sense? can you implement this now?"
)
PLAIN = (
    "Sometimes we buy one side of a two-sided lock and the other side does not fill. "
    "That leftover price can move. New pair attempts stay off so we are not holding two naked legs at once. "
    "Every 20 seconds we look at the opposite bet on Kalshi, Gemini, Polymarket US, and Novig — including "
    "the same venue that already filled us (buying Yes and No on one market is a completed lock). "
    "Opposite means Yes if we already hold No, and No if we already hold Yes, for the same game, date, "
    "side, and number. If that opposite still leaves at least a nickel after fees (both sides plus fees "
    "cost $0.95 or less), we send one immediate-or-cancel for one contract, cheapest venue first. "
    "If it fills, we stop and turn orders back on. If it misses, we try the next cheap enough venue in "
    "that same 20-second pass. If none fill, we wait 20 seconds and look again. We do not bid above the "
    "leftover cap. Novig is quoted; Novig orders stay off unless that switch is already on (it is not). "
    "The watch stops, with the stop-note left in place, if the market is settled or the 8:00 AM Eastern "
    "Time deadline on October 22, 2026 arrives."
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


def write_old_redirect() -> Path:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>One-leg minute watch 2026-10-20 — replaced</title>
<style>
body {{ margin: 0; padding: 16px 16px 48px; font: 16px/1.45 system-ui, Segoe UI, sans-serif; color: #0f172a; background: #fff; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
p {{ margin: 0.4rem 0 0.7rem; }}
.callout {{ border-left: 4px solid #1d4ed8; background: #f8fafc; padding: 10px 12px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
</style>
</head>
<body>
<h1>Once-a-minute leftover watch — replaced</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. This filename is kept so old links still open. The live leftover watch is now every 20 seconds on all venues.</p>
<div class="callout">
<h2>What you asked</h2>
<p>I have noticed that sometimes after we buy one leg in a bet, the bet goes in the right direction, which means eventually the no bet comes down in price. what if we checked once a minute after we make our initial attempts and if it comes down to a profitable purchase, then we go ahead and execute it and turn orders back on</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>That once-a-minute missed-venue-only watch is no longer the live plan. Current page: <a href="one_leg_20s_watch_20261021.html">one_leg_20s_watch_20261021.html</a>.</p>
</div>
<p>Related: <a href="architecture.html">architecture.html</a>, <a href="one_leg_note.html">one_leg_note.html</a>, <a href="orders.html">orders.html</a>.</p>
</body>
</html>
"""
    OLD_PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OLD_PAGE.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(OLD_PAGE)
    return OLD_PAGE


def write_page(watch: dict | None, reconstruct_note: str, latch_text: str, leftover_note: str) -> Path:
    watch = watch or {}
    venues = watch.get("venues") if isinstance(watch.get("venues"), dict) else {}
    venue_rows = []
    for name in ("kalshi", "gemini", "polymarket", "novig"):
        info = venues.get(name) if isinstance(venues.get(name), dict) else {}
        venue_rows.append([
            name,
            str(info.get("instrument") or ""),
            "quote only" if name == "novig" and not novig_live.NOVIG_ORDERS_ENABLED else "orders allowed if ≥ 0.05 profit",
        ])
    steps = _table(
        [("Step", "num"), ("What happens", "text")],
        [
            ["1", "Simultaneous IOC pair, then the existing recovery walk, still leaves exactly one fill."],
            ["2", "Keep orders_stopped.json so new pairs are not sent. Write raw/one_leg_watch.json with the filled leg (venue, instrument, side, cash fill, fee), the settlement identity (game/date/side/number), origin venue, opposite side, and any known instruments on Kalshi, Gemini, Polymarket US, and Novig."],
            ["3", "A dedicated leftover timer ticks about every 20 seconds (the supervisor’s 60s loop is only for status HTML). Refresh books/websocket quotes on all four venues, including the origin venue. Buying the other side on the same market is allowed."],
            ["4", "0.05 profit means after-fee net of (filled cash + filled fee + opposite cash + opposite fee) ≤ 0.95, each price under 1, size 1. Recheck using the price about to be sent. Unread or short balance fails closed."],
            ["5", "Among venues that currently show a qualifying opposite, sequentially IOC one contract, cheapest opposite first (largest remaining profit). Novig is quoted always and is not sent unless NOVIG_ORDERS_ENABLED is already True."],
            ["6", "Fill ≥ 1: stop trying other venues this cycle, complete the lock, clear the watch, delete orders_stopped.json, set ORDERS_ENABLED True in this process, ntfy that orders are on, refresh balances."],
            ["7", "If that IOC misses, try the next qualifying venue in the same 20s cycle. If none fill, wait 20 seconds and scan again. Do not send a venue that is not ≥ 0.05 profit. Do not walk above the cap."],
            ["8", "Stop watching (latch stays on, ntfy once) if the origin market is closed/resolved or the 8:00 AM ET REQUIRED_DEADLINE has passed. One naked leg at a time."],
        ],
    )
    freeze = _table(
        [("Knob", "text"), ("Value", "text")],
        [
            ["Size", "1 contract"],
            ["Cap", "fill cash + opposite cash + both fees ≤ 0.95, each price < 1"],
            ["Watch cadence", "dedicated leftover timer ~20s; supervisor loop stays ~60s for status HTML"],
            ["Venue scan", "Kalshi, Gemini, Polymarket US, Novig quotes; origin included"],
            ["Send order", "sequential IOC, cheapest qualifying opposite first; stop the cycle on fill ≥ 1"],
            ["Novig orders", f"NOVIG_ORDERS_ENABLED={novig_live.NOVIG_ORDERS_ENABLED} (quote only unless already True)"],
            ["Send price", "min(current ask, venue max) and only if that ask still leaves ≥ 0.05 after fees"],
            ["Latch", "orders_stopped.json stays on while watching; file absent does not restore ORDERS_ENABLED — a completed lock sets it True"],
            ["Second pair", "blocked while the watch or latch is on"],
            ["Deadline", "2026-10-22 08:00 America/New_York"],
        ],
    )
    loaded_rows = [
        ["Game", str(watch.get("game") or "")],
        ["Bet key", str(watch.get("bet_key") or "")],
        ["Settlement", f"{watch.get('sport') or ''} {watch.get('date') or ''} {watch.get('market_type') or ''} {watch.get('claim_side') or ''} {watch.get('number') or ''}"],
        ["Filled", f"{watch.get('filled_venue') or ''} {watch.get('filled_side') or ''} {watch.get('filled_instrument') or ''} @ {watch.get('fill_px') or ''} fee {watch.get('fill_fee') or ''}"],
        ["Origin / opposite", f"{watch.get('origin_venue') or watch.get('filled_venue') or ''} / {watch.get('opposite_side') or ''}"],
        ["Original missed", f"{watch.get('missed_venue') or ''} {watch.get('missed_side') or ''} {watch.get('missed_instrument') or ''}"],
        ["Watch mode", str(watch.get("watch_mode") or "")],
        ["Started", str(watch.get("started_at") or "")],
        ["Watch status", "stopped" if watch.get("stopped") else ("active" if watch else "none")],
        ["Stop reason", str(watch.get("stop_reason") or "")],
        ["Latch", latch_text],
        ["Reconstruct note", reconstruct_note],
        ["Leftover note", leftover_note],
    ]
    loaded = _table([("Field", "text"), ("Value", "text")], loaded_rows)
    venue_table = _table([("Venue", "text"), ("Instrument on watch", "text"), ("Orders", "text")], venue_rows)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>One-leg 20s all-venues watch 2026-10-21</title>
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
<h1>20-second all-venues watch after a one-leg fill</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. This page does not place an order and does not transfer money. The latch file was left as-is. Replaces <a href="one_leg_minute_watch_20261020.html">one_leg_minute_watch_20261020.html</a>.</p>
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
<p class="note">{_esc(leftover_note)}</p>
{SWIPE_NOTE_HTML}
{loaded}

<h2>Venues on the watch file</h2>
{SWIPE_NOTE_HTML}
{venue_table}

<p class="note">Related: <a href="architecture.html">architecture.html</a>, <a href="one_leg_note.html">one_leg_note.html</a>, <a href="one_leg_minute_watch_20261020.html">prior minute-watch page</a>, <a href="orders.html">orders.html</a>, <a href="pattern_tracking_20261020.html">pattern tracking</a>.</p>
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


def leftover_note_from_ledger() -> str:
    watch = live_lock_orders.load_one_leg_watch() or {}
    mtu_both = False
    try:
        for row in live_lock_orders._read_orders():
            if not isinstance(row, dict):
                continue
            if "mtufiu" not in str(row.get("bet_key") or ""):
                continue
            if "48.5" not in str(row.get("bet_key") or ""):
                continue
            if row.get("event") == "filled" and row.get("venue") == "gemini":
                mtu_both = True
    except Exception:
        pass
    bits = []
    if mtu_both:
        bits.append(
            "Middle Tennessee vs FIU total over 48.5 is not an open leftover: Kalshi No filled at 0.33 cash, "
            "then Gemini Yes filled at 0.44 on the old minute watch. That lock completed. No new pair was invented."
        )
    game = str(watch.get("game") or "")
    if watch and watch.get("stopped"):
        bits.append(
            f"The watch file is {game or 'present'} and is already stopped "
            f"({watch.get('stop_reason') or 'stopped'}). It was left as-is; latch stays on. "
            "An open watch would have been rewritten to the 20s all-venues schema."
        )
    elif live_lock_orders.watch_is_active(watch):
        bits.append(
            f"Open leftover on the watch file: {game}. Schema is all-venues 20s. Latch stays on until the opposite fills or the watch stops."
        )
    else:
        bits.append("No open leftover watch. Latch was left as-is.")
    return " ".join(bits)


def main() -> None:
    latch_on = live_lock_orders.ORDERS_STOP.exists()
    latch_text = "set" if latch_on else "not set"
    try:
        if latch_on:
            data = json.loads(live_lock_orders.ORDERS_STOP.read_text(encoding="utf-8"))
            latch_text = f"set — {data.get('reason') or ''} — {data.get('timestamp') or ''}"
    except (OSError, json.JSONDecodeError):
        pass
    existing = live_lock_orders.load_one_leg_watch()
    reconstruct_note = "watch file left as-is (no new pair invented)"
    watch = existing
    if live_lock_orders.watch_is_active(existing) and str(existing.get("watch_mode") or "") != "all_venues_20s":
        watch = live_lock_orders.migrate_watch_schema(existing)
        live_lock_orders._write_one_leg_watch(watch)
        reconstruct_note = "open watch rewritten to all-venues 20s schema"
    leftover_note = leftover_note_from_ledger()
    path = write_page(watch, reconstruct_note, latch_text, leftover_note)
    old = write_old_redirect()
    _copy_g(path)
    _copy_g(old)
    print(path)
    print(old)
    print(reconstruct_note)
    print(leftover_note)
    if watch:
        print(watch.get("game"), watch.get("stopped"), watch.get("watch_mode"))


if __name__ == "__main__":
    main()
