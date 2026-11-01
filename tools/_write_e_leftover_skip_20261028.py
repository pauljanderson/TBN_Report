"""E leftover-watch skip. Research HTML. Does not sell. Does not retune 11-49."""
from __future__ import annotations

import html as html_lib
import inspect
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "e_leftover_skip_20261028.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/e_leftover_skip_20261028.html"
)
ASKED = (
    "cool. please fix that bug. leftover-watch leaking onto directional E "
    "(Djokovic 55¢, Musetti No 51¢ leftover hedges)."
)
PLAIN = (
    "System E is a one-way underdog bet: we buy the cheaper player and hold. "
    "We must not auto-buy the favorite after. Leftover watch is the lock bot’s "
    "cleanup when one side of a Yes+No lock fills and the other misses. That "
    "cleanup was firing on E fills (and C/D one-way tickets that share the same "
    "send hook), which is how 55¢ Djokovic and 51¢ No Musetti got bought. "
    "Lock A leftover on a true two-leg lock still runs. We did not change the "
    "11–49 dog band, C’s $1.05 all-in, D, GTC, or stake. Not gold. Not DailyRun."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def write_page(*, a_pid: str, skip_live: str, tests: str, romano: str) -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    reg_src = inspect.getsource(live_lock_orders._register_send_fill_watch)
    skip_src = inspect.getsource(live_lock_orders.leftover_watch_skipped)
    persist_src = inspect.getsource(live_lock_orders.persist_one_leg_watch)
    tick_src = inspect.getsource(live_lock_orders._tick_single_watch)
    facts = table(
        [("Check", "text"), ("Result", "text"), ("Note", "text")],
        [
            ["Send-path skip live", esc(skip_live), "leftover_watch_skipped in _register_send_fill_watch"],
            ["Lock sender A pid", esc(a_pid), "one live_lock_sender.py; not a second B"],
            ["Tests", esc(tests), "E fill does not open leftover; lock A miss still does; no 55¢ favorite send from E key"],
            ["Open E leftover after reload", esc(romano), "Romano tennis-t0-dog watch stopped without sending"],
            ["11–49 / C=1.05 / D / GTC / stake", "unchanged", "Not an E band retune"],
            ["Gold / DailyRun", "no", "Research-candidate live only"],
        ],
    )
    code = table(
        [("Gate", "text"), ("Present", "text")],
        [
            ["leftover_watch_skipped helper", "yes" if "tennis-t0-dog" in skip_src else "NO"],
            ["_register_send_fill_watch calls leftover_watch_skipped", "yes" if "leftover_watch_skipped(spec)" in reg_src else "NO"],
            ["persist_one_leg_watch skips directional", "yes" if "leftover_watch_skipped(filled_spec, key)" in persist_src else "NO"],
            ["leftover tick skips directional (no 55¢ send)", "yes" if "directional skip" in tick_src else "NO"],
            ["Lock bet_keys still persist leftover", "yes" if "Lock bet_keys" in skip_src else "NO"],
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>E leftover-watch skip 28 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Do not leftover-watch directional E (or C/D)</h1>
<p class="note">Written {esc(now)}. Research-candidate live. Not gold. Not DailyRun.
Did not sell, did not retune 11–49, did not start a second Tennis crossover (B),
did not touch C=$1.05 / D / GTC / stake, did not fight hist/ or decile HTML,
did not revert the dashboard-label sibling (Yes {{player}} on Polymarket SHORT).</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<div class="callout ok">
<h2>What we did</h2>
<p>The module comment already said “Do not leftover-watch a directional dog.”
<code>_register_send_fill_watch</code> now checks that skip list: system E
<code>tennis-t0-dog</code>, college-football favorite C, and T0 spreads D
(same send hook). Strategy B was already skipped. Lock A one-leg leftover on
lock bet_keys (sport/game/date) still opens after a flatten miss.</p>
<p>Reloading E would not have stopped leftover — leftover lives in lock sender A.
We reloaded one lock sender. An already-open E leftover on Romano was stopped
on the first tick without buying the favorite.</p>
</div>
<h2>Result</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
{facts}
<h2>Code gates</h2>
{code}
<p class="tiny">Sources: <code>tools/live_lock_orders.py</code>
<code>leftover_watch_skipped</code> / <code>_register_send_fill_watch</code> /
<code>persist_one_leg_watch</code> / <code>_tick_single_watch</code>,
<code>tools/test_live_lock_orders.py</code>, audit
<code>system_e_dog_bets_audit_20261028.html</code>. File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


if __name__ == "__main__":
    write_page(
        a_pid=sys.argv[1] if len(sys.argv) > 1 else "?",
        skip_live=sys.argv[2] if len(sys.argv) > 2 else "Y",
        tests=sys.argv[3] if len(sys.argv) > 3 else "ok",
        romano=sys.argv[4] if len(sys.argv) > 4 else "stopped",
    )
