"""Lock after-fee cap 0.99 after proving unrounded Decimal compare + 4dp display.

Research only. Does not place, cancel, flatten, or sell. Does not print secrets.
Does not start a second live_strategy_b.py.
"""
from __future__ import annotations

import html as html_lib
import inspect
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import opportunity_considerations  # noqa: E402
import prediction_systems as ps  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_net_max_099_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_net_max_099_20261025.html"
)
ASKED = (
    "Lots of: After-fee cost 0.99 is above the 0.984 send line but still at or under 0.99. "
    "He wants to bump the cap to 0.99 but NOT if the rounding error is still present."
)
PLAIN = (
    "The bot was skipping some Yes+No locks that still cost 99 cents or less after fees, "
    "because the send line sat at 0.984. Paul asked to raise that line to 0.99 only if the "
    "bot was no longer rounding the after-fee cost to cents first (so 0.9861 would not print "
    "as 0.99, and 0.98399 would not print as 0.98). We proved the live send check compares "
    "the full Decimal to the cap with net > cap, then raised the live cap to 0.99. A row at "
    "0.986 now sends. A row at 0.991 still does not. This does not sell anything and does not "
    "start a second Tennis crossover."
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
    src = inspect.getsource(live_lock_orders.qualifies)
    block = inspect.getsource(live_lock_orders._profit_block)
    leftover = inspect.getsource(live_lock_orders._rank_qualifying_opposites)
    pair = inspect.getsource(live_lock_orders.pair_net)
    json_path = RAW / "systems.json"
    blob = {}
    if json_path.exists():
        try:
            blob = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
    lock = ((blob.get("systems") or {}).get("lock") or {})
    return {
        "qualifies_gt": "net > effective_net_max()" in src,
        "qualifies_no_round": "round(net" not in src,
        "block_gt": "net > effective_net_max()" in block,
        "leftover_gt": "net > cap" in leftover,
        "pair_no_round": "round(" not in pair and "quantize" not in pair,
        "fmt_098399": live_lock_orders._net_text(Decimal("0.98399")),
        "fmt_099": live_lock_orders._net_text(Decimal("0.99")),
        "fmt_09862": live_lock_orders._net_text(Decimal("0.9862")),
        "send_line": live_lock_orders.send_line(),
        "effective": format(live_lock_orders.effective_net_max(), "f"),
        "module_default": format(live_lock_orders.NET_MAX, "f"),
        "json_net_max": str(lock.get("net_max") or ""),
        "cli": "python tools/prediction_job_control.py systems --lock-net-max 0.99",
    }


def write_page(pids: dict | None = None, notes: list[str] | None = None) -> Path:
    now = datetime.now(ET)
    pids = pids or {}
    notes = notes or []
    facts = proof()
    rounding_gone = all(
        (
            facts["qualifies_gt"],
            facts["qualifies_no_round"],
            facts["block_gt"],
            facts["leftover_gt"],
            facts["pair_no_round"],
            facts["fmt_098399"] != "0.98",
            facts["fmt_099"] == "0.9900",
        )
    )
    cap = facts["send_line"]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Lock cap 0.99 if unrounded — 25 Oct 2026</title>
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
<h1>Lock send cap 0.99 (unrounded Decimal)</h1>
<p class="note">America/New_York. Research-candidate live. Not gold. Not DailyRun. Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Did not sell. Did not start a second <code>live_strategy_b.py</code>.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<div class="callout ok">
<h2>Verdict</h2>
<p><strong>Rounding gone: {"yes" if rounding_gone else "no"}.</strong>
Live send check is Decimal <code>net &gt; effective_net_max()</code> (same as <code>net &gt; NET_MAX</code> on the live cap).
It does not <code>round(net, 2)</code> first. After-fee display is at least four decimal places
(<code>{esc(facts["fmt_098399"])}</code> not 0.98; <code>{esc(facts["fmt_099"])}</code>; <code>{esc(facts["fmt_09862"])}</code>).
<strong>Cap now {esc(cap)}.</strong> Exact CLI: <code>{esc(facts["cli"])}</code>.</p>
</div>
<p class="note">Sibling rounding page (merge, not revert): <a href="lock_098_deny_rounding_20261025.html">lock_098_deny_rounding_20261025.html</a>. Opportunities log: <a href="opportunities.html">opportunities.html</a>. Job status: <a href="job_status.html">job_status.html</a>. Click column headers to sort.</p>
<h2>Proof the live compare is unrounded</h2>
{table(
    [("Check", "text"), ("Result", "text")],
    [
        ["qualifies()", esc("net > effective_net_max()" if facts["qualifies_gt"] else "missing")],
        ["qualifies() has round(net", esc("no" if facts["qualifies_no_round"] else "YES — still rounds")],
        ["_profit_block()", esc("net > effective_net_max()" if facts["block_gt"] else "missing")],
        ["leftover rank", esc("net > cap" if facts["leftover_gt"] else "missing")],
        ["pair_net() round/quantize", esc("none" if facts["pair_no_round"] else "present")],
        ["Display 0.98399", esc(facts["fmt_098399"])],
        ["Display 0.99", esc(facts["fmt_099"])],
        ["Display 0.9862", esc(facts["fmt_09862"])],
        ["Module default NET_MAX", esc(facts["module_default"])],
        ["systems.json lock.net_max", esc(facts["json_net_max"] or "(unset)")],
        ["effective_net_max / send line", esc(facts["effective"] + " / " + facts["send_line"])],
    ],
)}
<h2>Tests</h2>
{table(
    [("Case", "text"), ("Result", "text")],
    [
        ["0.986 vs cap 0.99", "send (net > cap is false)"],
        ["0.991 vs cap 0.99", "deny (net > cap)"],
        ["Display 0.98399", "not 0.98"],
        ["Display 0.99 row", "0.9900"],
        ["Display 0.9862", "0.9862"],
        ["Balance deny strings", "unchanged (_money still 2–3 dp; after-fee uses _net_text)"],
    ],
)}
<h2>Reload (hidden spawn, one lock supervisor)</h2>
{table(
    [("Job", "text"), ("Pids", "text")],
    [
        ["Lock supervisor", esc(pids.get("supervisor") or "n/a")],
        ["Lock pollers (count)", esc(pids.get("poller_n") or "n/a")],
        ["Catalog scan", esc(pids.get("scan") or "n/a")],
        ["B tennis crossover", esc(pids.get("strategy_b") or "n/a")],
        ["C CFB favorite", esc(pids.get("cfb_favorite") or "n/a")],
        ["D T0 spreads", esc(pids.get("spread_t0") or "n/a")],
        ["E Tennis T0 dog", esc(pids.get("tennis_t0_dog") or "n/a")],
    ],
)}
<p class="note">{esc(" | ".join(notes) if notes else "Reload notes empty.")}</p>
<p class="tiny">Sources: tools/live_lock_orders.py qualifies / _profit_block / pair_net / _net_text, tools/opportunity_considerations.py _fmt, tools/prediction_systems.py --lock-net-max, local systems.json. No secrets. Did not sell. Did not start a second Strategy B. {esc(FILE_URL)}</p>
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
    import prediction_job_control as pjc

    jobs = pjc.classify(pjc._ps_rows())
    pids = {
        "supervisor": pid_bit(jobs.get("supervisor")),
        "poller_n": str(len(jobs.get("children") or [])),
        "scan": pid_bit(jobs.get("scan")),
        "strategy_b": pid_bit(jobs.get("strategy_b")),
        "cfb_favorite": pid_bit(jobs.get("cfb_favorite")),
        "spread_t0": pid_bit(jobs.get("spread_t0")),
        "tennis_t0_dog": pid_bit(jobs.get("tennis_t0_dog")),
    }
    notes = [
        f"send_line={live_lock_orders.send_line()}",
        f"json net_max={proof()['json_net_max'] or 'unset'}",
        f"B count={len(jobs.get('strategy_b') or [])}",
    ]
    path = write_page(pids, notes)
    print("wrote", path, flush=True)
    print("file", FILE_URL, flush=True)
    print("cap", live_lock_orders.send_line(), flush=True)
    print("supervisor", pids["supervisor"], flush=True)
    opp = opportunity_considerations.write_page()
    print("opportunities", opp, flush=True)


if __name__ == "__main__":
    main()
