"""System E (tennis T0 dog / P2) freeze page. Research-candidate live. Not gold.

Does not commit. Does not print secrets. Does not start a second live_strategy_b.py.
Does not sell tickets. Does not wire GTC.
"""
from __future__ import annotations

import html as html_mod
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "system_e.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_e.html"
)
JOB_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/job_status.html"
)

ASKED = (
    "Wire E in NOW. Do not leave tennis T0 dog off. He previously asked for P2 as "
    "system E. Turn it on (max 2, stake $1). Tennis ML, trusted T0, unique dog Yes "
    "ask < 0.50 and > 0.10, 1 contract cheapest venue, Poly FOK, hold to settle, "
    "skip if B already on the match, max 2. Research-candidate live. Not gold. Not DailyRun."
)
PLAIN = (
    "System E buys the tennis underdog at the first trusted start — the cheaper "
    "player, not both players, and not a wait for a 50-cent crossover. The ticket "
    "has to cost more than 10 cents and less than 50 cents, one contract, cheapest "
    "shop. If Tennis crossover (B) already has that match, E stands down. Hold until "
    "the match settles. This is a live research bot, not a finished house system."
)

FREEZE = [
    ("Sport / market", "Tennis moneyline only"),
    ("Clock", "Trusted T0: Kalshi/Gemini occurrence, else listed/feed with seconds=00. 5-minute grace."),
    ("Side", "Unique dog = uniquely lower Yes ask. Skip 50-50 / ties."),
    ("Band", "Dog Yes ask in (0.10, 0.50). Exclusive. 0.10 and 0.50 skip."),
    ("Size", "1 whole contract. Stake $1. Cheapest venue; Kalshi > Gemini > Poly > Novig on price ties."),
    ("Poly", "Fill-or-kill (FOK). Other venues IOC."),
    ("Hold", "Hold to settlement. No flatten. No 50-cross. No favorite dip. No both-Yes."),
    ("Skip B", "If Tennis crossover already holds the match, E does not send."),
    ("Max open", "2 matches"),
    ("Promotion", "Research-candidate live. Not gold. Not DailyRun."),
]

CLI_ROWS = [
    ("Turn E on (this freeze)", "python tools/prediction_job_control.py systems --tennis-t0-dog on --tennis-t0-dog-max 2 --tennis-t0-dog-stake 1"),
    ("Same, short flags", "python tools/prediction_job_control.py systems --e on --e-max 2 --e-stake 1"),
    ("Status table", "python tools/prediction_job_control.py systems"),
    ("Turn E off", "python tools/prediction_job_control.py systems --e off"),
]


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def html_table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f"<table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def main() -> int:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    freeze_rows = [[esc(a), esc(b)] for a, b in FREEZE]
    cli_rows = [[esc(a), "<code>" + esc(b) + "</code>"] for a, b in CLI_ROWS]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System E — Tennis T0 dog</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
pre {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px 12px; overflow: auto; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>System E — Tennis T0 dog (P2)</h1>
<p class="banner"><strong>Research-candidate live. Not gold. Not DailyRun.</strong> Written {esc(now)}.
Did not start a second <code>live_strategy_b.py</code>. Did not sell tickets. Did not wire GTC.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<p class="note">Live ops: <a href="job_status.html">job_status.html</a>.
P2 backtest: <a href="new_systems_backtest_20261024/compare.html">new_systems_backtest_20261024/compare.html</a>.
A–D CLI: <a href="systems_abcd_cli_20261024.html">systems_abcd_cli_20261024.html</a>.</p>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
<h2>Freeze</h2>
{html_table([("Knob", "text"), ("Rule", "text")], freeze_rows)}
<h2>CLI that is live</h2>
{html_table([("Action", "text"), ("Command", "text")], cli_rows)}
<pre>python tools/prediction_job_control.py systems --tennis-t0-dog on --tennis-t0-dog-max 2 --tennis-t0-dog-stake 1</pre>
<h2>Live files</h2>
<ul>
<li><code>tools/live_tennis_t0_dog.py</code> — E process</li>
<li><code>tools/live_t0_yes.py</code> — shared T0 send (C/D/E)</li>
<li><code>tools/prediction_systems.py</code> — <code>--tennis-t0-dog</code> / <code>--e</code></li>
<li><code>tools/live_strategy_b.py</code> — B; E skips when B holds the match</li>
</ul>
<p class="tiny">Generator: <code>tools/_write_system_e.py</code>. Bookmark <code>{esc(FILE_URL)}</code>. job_status <code>{esc(JOB_URL)}</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    html = report_page_extras.inject_report_page_extras(page)
    PAGE.write_text(html, encoding="utf-8")
    stamp = STAMP / "system_e_t0_dog_20261025.html"
    stamp.write_text(html, encoding="utf-8")
    print(PAGE)
    print(stamp)
    print(FILE_URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
