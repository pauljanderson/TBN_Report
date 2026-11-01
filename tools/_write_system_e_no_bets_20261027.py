"""Diagnose why System E (tennis T0 dog) is not sending. Does not fix.

Research only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Not gold. Not DailyRun.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers
import live_t0_yes
import prediction_systems as systems
import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP
from prediction_paths import RAW_DIR as RAW
from t0_all_games_stats import table

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "system_e_no_bets_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_e_no_bets_20261027.html"
)
ASKED = (
    "Investigate why we aren't making system E bets, but don't fix it yet. "
    "I want the last report to be finished first."
)
PLAIN = (
    "System E is supposed to buy one cheap tennis underdog at the first trusted start "
    "(T0), Yes price between 10 and 50 cents, one contract, hold to the end. "
    "The last performance rebuild showed zero E tickets. This page says why. "
    "Nothing was changed. Research only — not gold, not DailyRun."
)


def esc(value) -> str:
    import html as html_mod

    return html_mod.escape("" if value is None else str(value), quote=True)


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def pid_alive(pid: int) -> bool:
    return bool(live_game_pollers.pid_alive(pid))


def order_hits() -> int:
    path = RAW / "orders.jsonl"
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if "e-t0" in line or "tennis-t0-dog" in line or '"tennis_t0_dog"' in line:
                n += 1
    return n


def main() -> int:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    cfg = systems.get_system("tennis_t0_dog")
    watch = _load(RAW / "tennis_t0_dog_watch.json")
    pid_blob = _load(RAW / "tennis_t0_dog.pid")
    pid = int(pid_blob.get("pid") or watch.get("pid") or 0)
    scan = live_game_pollers.load_scan()
    sports = scan.load_sports()
    tennis_rows = live_game_pollers.tennis_rows(scan)
    slate = live_t0_yes.slate_near_t0(scan, "tennis_t0_dog")
    live = live_game_pollers.live_games(scan)
    live_tennis = [row for row in live if str(row.get("sport") or "").lower() == "tennis"]
    b = _load(RAW / "strategy_b_watch.json")
    log_text = (RAW / "tennis_t0_dog.log").read_text(encoding="utf-8") if (RAW / "tennis_t0_dog.log").exists() else ""
    perm = log_text.count("loop PermissionError")
    starts = log_text.count("tennis_t0_dog start")
    n_orders = order_hits()
    queue_sports = ", ".join(sorted(sports.keys()) or ["(empty)"])

    facts = table(
        [("Check", "text"), ("Value", "text")],
        [
            ["E on in systems.json", "yes" if cfg.on else "no"],
            ["Stake / size / max open", f"${cfg.stake_usd} / {cfg.size} / {cfg.max_open}"],
            ["Process pid", f"{pid} {'alive' if pid_alive(pid) else 'down'} since {pid_blob.get('started_at') or '—'}"],
            ["Watch updated", str(watch.get("updated_at") or "—")],
            ["Watch matches / skipped / open", f"{len(watch.get('matches') or [])} / {len(watch.get('skipped') or [])} / {watch.get('currently_open')}"],
            ["Last send / last skip", f"{watch.get('last_send') or '(empty)'} / {watch.get('last_skip_reason') or '(empty)'}"],
            ["orders.jsonl e-t0 / tennis-t0-dog rows", str(n_orders)],
            ["sports_queue.json sports (E slate source)", queue_sports],
            ["E slate_near_t0 tennis games", str(len(slate))],
            ["tennis_rows (B / live_games tennis source)", str(len(tennis_rows))],
            ["live_games tennis count", str(len(live_tennis))],
            ["B currently open / absorbed (history)", f"{b.get('currently_open')} / {sum(1 for m in (b.get('matches') or []) if str(m.get('stage')) == 'absorbed')}"],
            ["E log start lines / loop PermissionError", f"{starts} / {perm}"],
        ],
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Why System E is not betting</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Why System E is not making bets</h1>
<p class="note">Written {esc(now)}. Diagnose only. Did not change send code. Research only. Not gold. Not DailyRun.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{PLAIN}</p></div>
<p class="note">E is <strong>on</strong>, the process is <strong>alive</strong>, and it is ticking the watch file.
It still has never sent, because its game list is the overnight sports queue, and that queue has no tennis.
Tennis lives on a different list that Strategy B already uses. Click headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h2>What we checked</h2>
{facts}

<h2>Root cause</h2>
<p class="note"><code>live_t0_yes.slate_near_t0</code> for E walks <code>live_game_pollers.iter_matched</code>
(<code>overnight_scan.load_college</code> + <code>load_sports</code> from <code>sports_queue.json</code>).
That file’s sports tonight are {esc(queue_sports)}. There is no tennis key, so E’s slate is always empty:
<code>consider_game</code> never runs, the watch stays <code>matches=[] skipped=[]</code>, and
<code>orders.jsonl</code> has {esc(n_orders)} E rows. Performance rebuild “E clusters 0” is the same empty set,
not a clustering bug.</p>
<p class="note">Tennis is loaded separately: <code>live_game_pollers.tennis_rows</code> (Polymarket tennis books + Novig).
<code>live_games()</code> already appends that list, and Strategy B’s <code>tennis_slate()</code> uses it
({esc(len(tennis_rows))} rows right now, {esc(len(live_tennis))} of them in <code>live_games</code>).
E never calls that function.</p>

<h2>Not the main reason (would only matter after E can see tennis)</h2>
<ul>
<li>Skip-if-B-open would block matches B already has (absorbed / T0 sent / waiting). B C&gt;1.05 skip does <em>not</em> block E. That gate never ran, because E never saw a match.</li>
<li>Dog band is exclusive (0.10, 0.50). Five-minute T0 window. REST recheck. None of those fired.</li>
<li>E log has {esc(perm)} <code>loop PermissionError</code> lines (Windows file lock / Drive import). Those drop a tick; they do not explain three days of an empty slate. Last errors sit next to later successful empty ticks.</li>
</ul>
<p class="tiny">Sources: <code>systems.json</code>, <code>tennis_t0_dog_watch.json</code>, <code>tennis_t0_dog.log</code>,
<code>orders.jsonl</code>, <code>sports_queue.json</code>, <code>strategy_b_watch.json</code>.
Code: <code>tools/live_t0_yes.py</code> <code>slate_near_t0</code>, <code>tools/live_game_pollers.py</code>
<code>iter_matched</code> / <code>tennis_rows</code> / <code>live_games</code>, <code>tools/live_tennis_t0_dog.py</code>,
<code>tools/live_strategy_b.py</code> <code>tennis_slate</code>. File URL {esc(FILE_URL)}.
Did not sell, start a second B, bump stake, wire D NFL, leftover GTC, or retune C=1.05. Did not patch E.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    print(
        json.dumps(
            {
                "on": cfg.on,
                "pid": pid,
                "alive": pid_alive(pid),
                "slate": len(slate),
                "tennis_rows": len(tennis_rows),
                "orders": n_orders,
                "queue_sports": list(sports.keys()),
            },
            default=str,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
