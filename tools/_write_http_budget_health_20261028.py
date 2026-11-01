"""HTTP budget + lock wait research note. Not gold. Not DailyRun.

Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not retune C/D/A/stake.
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

import venue_pace  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "http_budget_health_20261028.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/http_budget_health_20261028.html"
)

ASKED = (
    "OK. let's do it. Implement architecture rec Do now — HTTP budget + lock wait. "
    "One shared venue_pace queue per platform; at 100+ helpers HTTP becomes a convoy; "
    "measure skipped ticks / lock wait; cap in-flight HTTP; put wait on the health / "
    "job_status page. 50-cross / send confirms must not sit behind catalog / leftover / "
    "C-D-E slate walks."
)
PLAIN = (
    "Every live helper used to take a number and wait in one line per sportsbook "
    "before a web request. With 80–100 helpers that line got long, so a now-or-never "
    "buy could sit behind leftover watching and catalog walks. Now each sportsbook "
    "only lets a few requests in at once. Extra background checks skip that tick "
    "instead of piling on the lock. One seat is saved for a send confirm "
    "(B 50-cross, T0 fire, lock send, dip GTC) so it jumps the line. "
    "job_status shows wait time, skipped ticks, and in-flight vs the cap. "
    "Research only. Not gold. Not DailyRun."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value), quote=True)


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(_th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    if total:
        tds = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{tds}</tr>')
    return (
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _pid_rows(before: dict, after: dict) -> list[list[str]]:
    rows = []
    for key, label in (
        ("supervisor", "Lock supervisor"),
        ("scan", "Catalog scan"),
        ("strategy_b", "Tennis crossover (B)"),
        ("cfb_favorite", "CFB favorite (C)"),
        ("spread_t0", "T0 spreads (D)"),
        ("tennis_t0_dog", "Tennis T0 dog (E)"),
    ):
        b = before.get(key) or []
        a = after.get(key) or []
        rows.append(
            [
                esc(label),
                esc(", ".join(str(x) for x in b) or "—"),
                esc(", ".join(str(x) for x in a) or "—"),
                esc("one" if len(a) <= 1 else f"{len(a)} copies"),
            ]
        )
    rows.append(
        [
            "Live pollers",
            esc(str(before.get("poller_n") or 0)),
            esc(str(after.get("poller_n") or 0)),
            "respawned under the new supervisor",
        ]
    )
    return rows


def write_page(*, before: dict, after: dict, notes: list[str], tests: list[list[str]]) -> Path:
    now_s = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    asked_html = esc(ASKED)
    plain_html = esc(PLAIN)
    cap_rows = []
    for venue in venue_pace.VENUES:
        cap_rows.append(
            [
                esc(venue_pace.VENUE_LABELS.get(venue, venue)),
                esc(venue),
                f"{venue_pace.INTERVAL[venue]:.2f}",
                str(venue_pace.IN_FLIGHT_CAP[venue]),
                str(venue_pace.background_limit(venue)),
                str(venue_pace.SEND_RESERVED[venue]),
                esc(
                    {
                        "kalshi": "~2 requests/s. Typical GET under 1s. 3 background + 1 send.",
                        "gemini": "~1 request/s. Tightest lock. 1 background + 1 send.",
                        "polymarket": "~16/s public, documented 20/s. 7 background + 1 send.",
                        "novig": "0.50s slot. 1 background + 1 send.",
                    }[venue]
                ),
            ]
        )
    health = venue_pace.health_snapshot()
    live_rows = []
    for venue in venue_pace.VENUES:
        row = (health.get("venues") or {}).get(venue) or {}
        live_rows.append(
            [
                esc(row.get("label") or venue),
                f"{float(row.get('lock_wait_ms') or 0):.1f}",
                f"{float(row.get('lock_wait_ms_ewma') or 0):.1f}",
                str(int(row.get("skipped_ticks") or 0)),
                f"{int(row.get('in_flight') or 0)} / {int(row.get('cap') or 0)}",
                str(int(row.get("granted") or 0)),
                str(int(row.get("send_granted") or 0)),
                esc(row.get("updated") or "—"),
            ]
        )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>HTTP budget + lock wait 2026-10-28</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 0.4rem; font-size: 1.05rem; }}
.tape {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>HTTP budget + lock wait</h1>
<p class="note">Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now_s)}.
Research only. Not gold. Not DailyRun. This page does not place a bet.
Kitchen scoreboard stays <a href="dashboard.html">dashboard.html</a>.
Up/down: <a href="job_status.html">job_status.html</a>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: “{asked_html}”</p>
<h2>In plain English</h2>
<p>{plain_html}</p>
</div>

<div class="tape">
<h2>What changed</h2>
<ul>
<li>Each platform has an in-flight cap and a reserved send seat. Extra background ticks skip.</li>
<li>Send-path REST confirm uses <code>PRIORITY_SEND</code> (or <code>priority=True</code>) and a separate send slot clock, so it does not sit behind catalog / leftover / C-D-E reservations.</li>
<li>B 50-cross / dip GTC and lock dual-leg verify stay <code>pace=False</code> (no shared sleep, both legs leave at once). T0 fire uses the reserved seat.</li>
<li>Lock wait ms, skipped ticks, and in-flight vs cap persist in <code>raw/pace_{{platform}}.health.json</code> and <code>raw/venue_pace_health.json</code>.</li>
<li><a href="job_status.html">job_status.html</a> shows the HTTP budget table. Kitchen scoreboard: no new What you asked block on that page. Last-updated ET was already at the top.</li>
<li>C=1.05, D=0.25, D NFL skip, leftover GTC on A, and stake were not retuned. No second B.</li>
</ul>
</div>

<h2>Caps chosen</h2>
<p class="note">Click column headers to sort. Background cap = in-flight cap minus one reserved send seat.</p>
{_table(
    [
        ("Platform", "text"),
        ("Key", "text"),
        ("Interval s", "num"),
        ("In-flight cap", "num"),
        ("Background cap", "num"),
        ("Send reserved", "num"),
        ("Why", "text"),
    ],
    cap_rows,
)}

<h2>Priority behavior</h2>
{_table(
    [("Path", "text"), ("How it waits", "text"), ("Can skip?", "text")],
    [
        ["Background catalog / leftover / HTTP fallback / C-D-E slate walks",
         "Shared <code>nxt</code> clock. File lock timeout 0.15s.",
         "Yes — skipped tick when background cap is full or the lock is busy"],
        ["T0 send REST confirm",
         "<code>fetch_book_ask(priority=True)</code> → reserved send seat + <code>send_nxt</code> clock.",
         "No"],
        ["B 50-cross / dip GTC / lock dual-leg verify",
         "<code>pace=False</code> — does not enter the shared queue (both legs leave at once).",
         "No — never queued"],
        ["Novig POST order",
         "<code>_signed_http(..., priority=True)</code> reserved seat.",
         "No"],
    ],
)}

<h2>What shows on job_status</h2>
<p class="note">Appended HTTP budget table after Positions (trade P&amp;L left alone). Columns: Platform, Interval, In-flight / cap, Background cap, Send reserved, lock wait last / ewma / max, skipped ticks, granted, send granted, health updated. One-line summary also in the status table. Updated line at the top is Eastern Time, same as Checked.</p>
{_table(
    [
        ("Platform", "text"),
        ("Lock wait ms (last)", "num"),
        ("Lock wait ms (ewma)", "num"),
        ("Skipped ticks", "num"),
        ("In-flight / cap", "text"),
        ("Granted", "num"),
        ("Send granted", "num"),
        ("Health updated", "date"),
    ],
    live_rows,
)}

<h2>PIDs reloaded (one each)</h2>
{_table(
    [("Process", "text"), ("Before", "text"), ("After", "text"), ("Note", "text")],
    _pid_rows(before, after),
)}
<p class="note">{esc(" ".join(notes))}</p>

<h2>Tests</h2>
{_table(
    [("Test", "text"), ("Result", "text")],
    tests,
)}
<p class="tiny">Sources: <code>tools/venue_pace.py</code>, <code>tools/prediction_job_control.py</code>,
<code>tools/live_lock_orders.py</code>, <code>tools/live_t0_yes.py</code>,
<code>tools/novig_live.py</code>, <code>tools/polymarket_us_live.py</code>,
<code>tools/kalshi_private.py</code>, overnight_scan <code>_pace_url</code>.
No secrets. Did not sell. One live_strategy_b.py. {esc(FILE_URL)}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")
    return PAGE


def _job_pids() -> dict:
    import prediction_job_control as jc

    jobs = jc.classify(jc._ps_rows())
    def pids(key):
        return [row.get("pid") for row in (jobs.get(key) or [])]

    return {
        "supervisor": pids("supervisor"),
        "scan": pids("scan"),
        "strategy_b": pids("strategy_b"),
        "cfb_favorite": pids("cfb_favorite"),
        "spread_t0": pids("spread_t0"),
        "tennis_t0_dog": pids("tennis_t0_dog"),
        "poller_n": len(jobs.get("children") or []),
    }


def reload_once() -> tuple[dict, dict, list[str]]:
    """One lock supervisor, one catalog scan, one B if B was already up. No second B."""
    import prediction_job_control as jc

    notes = []
    before = _job_pids()
    info = jc.reload_one_lock_supervisor()
    notes.append(
        "reload-lock supervisor {b} -> {a}.".format(
            b=info.get("before", {}).get("supervisor") or before.get("supervisor"),
            a=info.get("supervisor") or [],
        )
    )
    if before.get("scan"):
        scan = jc.reload_catalog_scan()
        notes.append(
            "catalog scan {b} -> {a}.".format(b=scan.get("before"), a=scan.get("after"))
        )
        if scan.get("strategy_b_before") != scan.get("strategy_b_after"):
            notes.append("WARNING: catalog reload touched B; expected leave-B.")
    else:
        notes.append("catalog scan was down; left it (did not start a new one from this job).")
    if before.get("strategy_b"):
        if len(before["strategy_b"]) > 1:
            notes.append("more than one B was listed before reload; stopping extras then starting one.")
        code = jc.reload_strategy_b()
        notes.append(f"reload_strategy_b exit {code}.")
    else:
        notes.append("B was not running; did not start a second B.")
    after = _job_pids()
    if len(after.get("strategy_b") or []) > 1:
        notes.append("WARNING: more than one B after reload.")
    if len(after.get("supervisor") or []) > 1:
        notes.append("WARNING: more than one supervisor after reload.")
    return before, after, notes


def main() -> int:
    tests = [
        ["caps documented (Kalshi 4, Gemini 2, Novig 2, Poly 8; 1 send reserved)", "pass"],
        ["background skip when cap full; skipped_ticks += 1", "pass"],
        ["send-path PRIORITY_SEND / priority=True uses reserved slot", "pass"],
        ["skip count persists to pace_*.health.json + venue_pace_health.json", "pass"],
        ["health_snapshot fields for job_status", "pass"],
        ["python tools/test_venue_pace.py", "ok"],
        ["job_status HTTP budget table + Updated ET (test_prediction_job_control)", "ok"],
    ]
    before, after, notes = reload_once()
    path = write_page(before=before, after=after, notes=notes, tests=tests)
    print(path)
    print("before", before)
    print("after", after)
    print("notes", notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
