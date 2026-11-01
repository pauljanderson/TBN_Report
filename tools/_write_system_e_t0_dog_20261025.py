"""System E (P2 tennis T0 dog) freeze HTML. Research-candidate live. Not gold.

Does not commit. Does not print secrets. Does not start a second live_strategy_b.py.
Does not sell tickets. Does not auto-start E.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import prediction_systems as ps  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "system_e_t0_dog_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_e_t0_dog_20261025.html"
)
ON_CMD = (
    "python tools/prediction_job_control.py systems --tennis-t0-dog on "
    "--tennis-t0-dog-max 2 --tennis-t0-dog-stake 1"
)
OFF_CMD = "python tools/prediction_job_control.py systems --e off"

ASKED = (
    "Implement P2 as system E. P2 Tennis T0 dog (no both-Yes): buy the T0 tennis underdog "
    "at the T0 ask, hold to settle. Biggest drawdown, biggest net $ on the week backtest "
    "(+$20.60 N=91 KEEP research). Provide the CLI to set it up."
)
PLAIN = (
    "A fifth live bot that buys the cheaper tennis player at match start and holds that "
    "ticket until the match is over. It does not also buy the favorite, and it does not "
    "wait for a 50-cent bounce. It skips a match Tennis crossover already took. It stays "
    "off until you paste the on command. Research live, not gold, not DailyRun."
)


def esc(value) -> str:
    import html as html_mod

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
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def persist_e_off() -> None:
    """Write E into systems.json as off if missing. Does not spawn."""
    blob = ps._load_json(ps.CONFIG_PATH)
    rows = blob.get("systems") if isinstance(blob.get("systems"), dict) else blob
    if isinstance(rows, dict) and "tennis_t0_dog" in rows:
        return
    cfgs = ps.load_config()
    cfgs["tennis_t0_dog"].on = False
    ps.save_config(cfgs)


def write_page() -> Path:
    persist_e_off()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    cfg = ps.load_config().get("tennis_t0_dog")
    on_now = "on" if cfg and cfg.on else "off"
    freeze_rows = [
        ["Universe", "Tennis moneyline only. Trusted T0: same first trusted serve as B (Kalshi/Gemini occurrence, else listed with seconds=00)."],
        ["Dog", "Unique lower T0 Yes ask, must be in (0.10, 0.50). Skip 50-50. Skip dog Yes ≤ 0.10 (B junk band)."],
        ["Send", "Buy 1 contract (stake $1 ≈ 1 contract) IOC/FOK on the cheapest venue Yes for that player among Kalshi / Gemini / Polymarket / Novig."],
        ["Poly", "FOK. Displayed size < qty → poly_size_lt_qty_skip, no POST."],
        ["Recheck", "REST recheck before send. Venue confirm qty ≥ 1 is a fill. Hold to settlement."],
        ["Not this system", "No 50-cross. No favorite dip. No both-Yes."],
        ["Skip B", "Skip if Tennis crossover already has this match (absorbed / T0 sent). If B skipped all-in C>1.05, E may still send the dog. Skip-if-B-open lives in live_tennis_t0_dog.py."],
        ["Max open", "Default 2 unique games with venue-confirmed qty ≥ 1 still unsettled. Do not exceed."],
        ["Balance / ntfy", "Balance check before POST. ntfy on order HTTP. job_status Systems + Positions tag E."],
        ["Promotion", "Research-candidate live. Not gold. Not DailyRun. Selection bias: chosen after the week table (P2 KEEP research)."],
    ]
    body = [
        ["Control · tennis T0 favorite", "91", "42.9%", "−$24.51", "−$0.27", "$24.95"],
        ["Candidate · tennis T0 dog (P2 / E)", "91", "57.1%", "+$20.60", "+$0.23", "$1.89"],
    ]
    cli_rows = [
        ["See what's on", "python tools/prediction_job_control.py systems"],
        ["Turn E on (paste this)", ON_CMD],
        ["Turn E off", OFF_CMD],
        ["Letter alias", "--e"],
        ["Long alias", "--tennis-t0-dog"],
        ["Double-click table", "run_prediction_systems.bat"],
    ]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>System E tennis T0 dog — 25 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
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
<h1>System E — tennis T0 dog</h1>
<p class="banner"><strong>Research-candidate live. Not gold. Not DailyRun.</strong> Written {esc(now)}.
E is <strong>{esc(on_now)}</strong> in systems.json until Paul runs the CLI.
Did not start a second <code>live_strategy_b.py</code>. Did not sell Patel / Namigata / Kalshi.
Did not auto-start E. Hidden spawn is <code>win_hidden</code> when you turn it on.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<p class="note">Live ops: <a href="job_status.html">job_status.html</a>.
A–E CLI: <a href="systems_abcd_cli_20261024.html">systems_abcd_cli_20261024.html</a>.
Week table: <a href="new_systems_backtest_20261024/compare.html">new_systems_backtest_20261024/compare.html</a>.</p>

<h2>CLI cheat sheet — exact commands</h2>
<p class="note">Click column headers to sort. Starting E starts one <code>live_tennis_t0_dog.py</code> process, hidden. Never a second Tennis crossover.</p>
{html_table([("Action", "text"), ("Command", "text")], [[esc(a), "<code>"+esc(b)+"</code>"] for a, b in cli_rows])}
<pre>{esc(ON_CMD)}
{esc(OFF_CMD)}</pre>

<h2>Live freeze</h2>
{html_table([("Knob", "text"), ("Rule", "text")], [[esc(a), esc(b)] for a, b in freeze_rows])}

<h2>Week backtest that picked P2</h2>
<p class="note">KEEP (research only). Selection bias: this arm was chosen after looking at the week table. IS N=0 (all T0 ≥ 2024-01-01; this tape is 2026). Ann ROR omitted — same-day contracts. Not gold. Not DailyRun.</p>
{html_table(
    [("Arm", "text"), ("N", "num"), ("Win %", "num"), ("With-fee net $", "num"), ("Mean $", "num"), ("Max DD $", "num")],
    [[esc(a), esc(n), esc(w), esc(p), esc(m), esc(d)] for a, n, w, p, m, d in body],
)}

<h2>Live files</h2>
<ul>
<li><code>tools/live_tennis_t0_dog.py</code> — skip-if-B-open, plan_send, process entry</li>
<li><code>tools/live_t0_yes.py</code> — shared T0 clock, quotes, IOC send for C/D/E</li>
<li><code>tools/prediction_systems.py</code> — <code>--e</code> / <code>--tennis-t0-dog</code>, systems.json</li>
<li><code>run_prediction_systems.bat</code> — A–E table</li>
</ul>
<p class="tiny">Generator: <code>tools/_write_system_e_t0_dog_20261025.py</code>. Tests: <code>tools/test_live_tennis_t0_dog.py</code>. Bookmark <code>{esc(FILE_URL)}</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


if __name__ == "__main__":
    path = write_page()
    print(path)
    print("config", ps.CONFIG_PATH)
    print("e.on", ps.get_system("tennis_t0_dog").on)
