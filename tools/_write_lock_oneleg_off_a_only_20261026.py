"""One-leg fill turns Lock gap (A) off only. Research HTML. Does not sell."""
from __future__ import annotations

import html as html_lib
import inspect
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import prediction_job_control  # noqa: E402
import prediction_systems as ps  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_oneleg_off_a_only_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_oneleg_off_a_only_20261026.html"
)
ASKED = (
    "can we move the turn the system off flag when we have a single order filled "
    "in a two leg bet, to be simply turning off system A the lock gap?"
)
PLAIN = (
    "A lock is a Yes on one shop and a No on the other for the same game. Sometimes "
    "only one of those two tickets fills. The bot used to flip a global “orders off” "
    "latch that read like the whole prediction stack was stopped. That latch is now "
    "just Lock gap (system A): new lock pairs stop, leftover flatten/hedge for that "
    "naked ticket still runs, and Tennis crossover B, college-football favorite C, "
    "T0 spreads D, and tennis T0 dog E keep running and may still send. Paul turns "
    "A back on with python tools/prediction_job_control.py systems --lock on, or A "
    "comes back when leftover is fully hedged or flattened. We did not sell tickets "
    "and we did not start a second Tennis crossover."
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


def pid_bit(rows) -> str:
    pids = []
    for row in rows or []:
        pid = row.get("pid") if isinstance(row, dict) else row
        if pid:
            pids.append(str(pid))
    return ", ".join(pids) if pids else "none"


def proof() -> dict:
    stop_src = inspect.getsource(live_lock_orders.stop_orders)
    send_src = inspect.getsource(live_lock_orders._send_blocked)
    exec_src = inspect.getsource(live_lock_orders.execute_locks)
    resume_src = inspect.getsource(live_lock_orders.resume_orders_after_lock)
    apply_src = inspect.getsource(ps.apply_process)
    bat = (ROOT / "run_prediction_orders_on.bat").read_text(encoding="utf-8", errors="replace")
    job_src = Path(prediction_job_control.__file__).read_text(encoding="utf-8")
    blob = {}
    path = RAW / "systems.json"
    if path.exists():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
    systems = blob.get("systems") if isinstance(blob.get("systems"), dict) else {}
    return {
        "stop_sets_lock": "set_lock_system_on(False)" in stop_src,
        "stop_scope_lock": '"scope": "lock"' in stop_src,
        "send_b": "spec.get(\"_strategy_b\")" in send_src,
        "send_cde": "_DIRECTIONAL_SYSTEMS" in send_src,
        "send_watch": "_watch_recovery" in send_src,
        "send_a_off": "lock gap is off" in send_src,
        "exec_lock_on": "lock_system_on()" in exec_src,
        "exec_no_halt_gate": "orders_halted()" not in exec_src.split("if strategy_b_blocks_lock", 1)[-1][:1800],
        "resume_turns_a_on": "set_lock_system_on(True)" in resume_src,
        "cli_clears_latch": "clear_one_leg_new_pair_latch" in apply_src,
        "bat_lock_on": "systems --lock on" in bat and "restart" not in bat.lower(),
        "reload_lock_cli": "reload-lock" in job_src,
        "net_max": live_lock_orders.send_line(),
        "systems": systems,
        "latch": (RAW / "orders_stopped.json").exists(),
    }


def write_page(jobs: dict | None = None) -> Path:
    now = datetime.now(ET)
    jobs = jobs or {}
    facts = proof()
    systems = facts["systems"] or {}
    sys_rows = []
    for sid, letter, name in (
        ("lock", "A", "Lock gap"),
        ("tennis_crossover", "B", "Tennis crossover"),
        ("cfb_favorite", "C", "College football favorite"),
        ("spread_t0", "D", "T0 spreads"),
        ("tennis_t0_dog", "E", "Tennis T0 dog"),
    ):
        row = systems.get(sid) if isinstance(systems.get(sid), dict) else {}
        pids = pid_bit(jobs.get("supervisor") if sid == "lock" else jobs.get(
            {
                "tennis_crossover": "strategy_b",
                "cfb_favorite": "cfb_favorite",
                "spread_t0": "spread_t0",
                "tennis_t0_dog": "tennis_t0_dog",
            }.get(sid)
        ))
        sys_rows.append([
            letter,
            esc(name),
            "on" if row.get("on") else "off",
            esc(row.get("stake_usd") or row.get("stake") or ""),
            esc(row.get("max_open") or ""),
            esc(row.get("net_max") or ("0.99 send cap" if sid == "lock" else "—")),
            esc(pids),
        ])
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>One-leg fill turns Lock gap (A) off only — 26 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>One-leg fill turns Lock gap (A) off only</h1>
<p class="note">America/New_York. Research-candidate live. Not gold. Not DailyRun. Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Did not sell. Did not start a second <code>live_strategy_b.py</code>. Did not bump stake. Did not wire D NFL. lock.net_max stays 0.99.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<div class="callout ok">
<h2>What changed</h2>
<p><strong>Used to:</strong> a one-leg lock fill wrote <code>orders_stopped.json</code> and flipped an in-process “orders off” switch. Job status showed “New pair orders are off.” The phone ping said “Orders off.” <code>run_prediction_orders_on.bat</code> deleted that file and ran <code>restart</code>, which stopped the lock supervisor, catalog scan, <em>and</em> Tennis crossover B, then started one of each.</p>
<p><strong>Now:</strong> the same one-leg miss sets <code>systems.json lock.on = false</code> (A only). B, C, D, and E stay on and may still send. Leftover flatten-first watch still runs for that lock ticket. New lock pairs wait until leftover is fully hedged/flattened, or until Paul turns A back on. Job status shows A off and B–E on. Phone ping is “Lock gap off.”</p>
<p><strong>Turn A back on:</strong> <code>python tools/prediction_job_control.py systems --lock on</code> (or double-click <code>run_prediction_orders_on.bat</code>). That does not stop B and does not start a second Tennis crossover. Reload lock only with <code>python tools/prediction_job_control.py reload-lock</code>.</p>
</div>
<p class="note">Click column headers to sort. Live status: <a href="job_status.html">job_status.html</a>. Parallel pages left alone: orders_performance-on-close, NFL No-deciles.</p>
<h2>Flag then vs now</h2>
{table(
    [("Piece", "text"), ("Used to disable", "text"), ("Disables now", "text")],
    [
        ["systems.json lock.on (A)", "Unchanged by one-leg (could stay on while latch blocked sends)", "Set false. New lock pairs stop. Pollers reread each tick."],
        ["tennis_crossover (B)", "Not gated at send if _strategy_b was set; restart-orders-on bat killed the B pid", "Stays on. Send still allowed. Pid left in place."],
        ["cfb_favorite (C)", "Not gated at send if _system=cfb_favorite", "Stays on. Send still allowed."],
        ["spread_t0 (D)", "Not gated at send if _system=spread_t0. NFL still skipped.", "Stays on. NFL still not wired."],
        ["tennis_t0_dog (E)", "Not gated at send if _system=tennis_t0_dog", "Stays on. Send still allowed."],
        ["Catalog scan / lock supervisor", "orders-on bat restarted supervisor + catalog + B together", "reload-lock restarts one lock supervisor only. Catalog and B stay."],
        ["orders_stopped.json", "Global new-pair latch; job_status banner “the system” off", "Leftover metadata (reconstruct watch, leftover HTML). Send switch is lock.on."],
        ["Leftover flatten / hedge", "Kept running while latch was on", "Unchanged. Flatten-first. Does not sell extra tickets."],
        ["Phone ping", "“Orders off”", "“Lock gap off” — A off, B–E stay on"],
    ],
)}
<h2>How Paul turns A back on</h2>
{table(
    [("Action", "text"), ("What it does", "text")],
    [
        ["<code>python tools/prediction_job_control.py systems --lock on</code>", "Writes lock.on=true. Clears leftover latch file. Does not stop B/C/D/E."],
        ["<code>run_prediction_orders_on.bat</code>", "Same CLI. No longer calls restart (that used to kill B)."],
        ["Leftover fully hedged or flattened", "Existing leftover policy: A comes back on. Latch file dropped."],
        ["Leftover watch still open", "Flatten/hedge still runs. New lock pairs wait until leftover finishes or Paul turns A on; leftover watch_is_active still blocks a second new lock pair."],
    ],
)}
<h2>Code proof</h2>
{table(
    [("Check", "text"), ("Result", "text")],
    [
        ["stop_orders sets lock.on false", esc("yes" if facts["stop_sets_lock"] else "NO")],
        ["latch file scope=lock / letter=A", esc("yes" if facts["stop_scope_lock"] else "NO")],
        ["_send_blocked exempts B", esc("yes" if facts["send_b"] else "NO")],
        ["_send_blocked exempts C/D/E", esc("yes" if facts["send_cde"] else "NO")],
        ["_send_blocked exempts leftover watch", esc("yes" if facts["send_watch"] else "NO")],
        ["lock send blocked with lock gap is off", esc("yes" if facts["send_a_off"] else "NO")],
        ["execute_locks new pairs use lock_system_on", esc("yes" if facts["exec_lock_on"] else "NO")],
        ["leftover complete turns A back on", esc("yes" if facts["resume_turns_a_on"] else "NO")],
        ["--lock on clears leftover latch", esc("yes" if facts["cli_clears_latch"] else "NO")],
        ["orders-on bat is systems --lock on, not restart", esc("yes" if facts["bat_lock_on"] else "NO")],
        ["reload-lock CLI exists", esc("yes" if facts["reload_lock_cli"] else "NO")],
        ["Live send cap (lock.net_max)", esc(facts["net_max"])],
        ["orders_stopped.json now", esc("set" if facts["latch"] else "not set")],
    ],
)}
<h2>Live systems after lock reload</h2>
{table(
    [("Sys", "text"), ("Name", "text"), ("On/off", "text"), ("Stake $", "num"), ("Max open", "num"), ("Cap", "text"), ("PID", "num")],
    sys_rows,
)}
<h2>Pids (one B)</h2>
{table(
    [("Job", "text"), ("Pid", "text")],
    [
        ["Lock supervisor (new)", esc(pid_bit(jobs.get("supervisor")))],
        ["Lock pollers (count)", esc(len(jobs.get("children") or []))],
        ["Catalog scan (left)", esc(pid_bit(jobs.get("scan")))],
        ["B Tennis crossover (left)", esc(pid_bit(jobs.get("strategy_b")))],
        ["C CFB favorite (left)", esc(pid_bit(jobs.get("cfb_favorite")))],
        ["D T0 spreads (left)", esc(pid_bit(jobs.get("spread_t0")))],
        ["E Tennis T0 dog (left)", esc(pid_bit(jobs.get("tennis_t0_dog")))],
    ],
)}
<p class="tiny">Sources: tools/live_lock_orders.py stop_orders / _send_blocked / execute_locks / resume_orders_after_lock, tools/prediction_systems.py apply_process, tools/prediction_job_control.py reload-lock / job_status copy, run_prediction_orders_on.bat, local systems.json. No secrets. Did not sell. One live_strategy_b.py. {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    jobs = prediction_job_control.classify(prediction_job_control._ps_rows())
    path = write_page(jobs)
    b = jobs.get("strategy_b") or []
    print("wrote", path, flush=True)
    print("file", FILE_URL, flush=True)
    print("supervisor", pid_bit(jobs.get("supervisor")), flush=True)
    print("B", pid_bit(b), "count", len(b), flush=True)
    print("C", pid_bit(jobs.get("cfb_favorite")), flush=True)
    print("D", pid_bit(jobs.get("spread_t0")), flush=True)
    print("E", pid_bit(jobs.get("tennis_t0_dog")), flush=True)
    print("scan", pid_bit(jobs.get("scan")), flush=True)
    print("B count must be 1:", len(b) == 1, flush=True)


if __name__ == "__main__":
    main()
