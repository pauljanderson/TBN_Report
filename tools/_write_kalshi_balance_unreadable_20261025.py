"""Stamp: Kalshi balance unreadable spam. Does not trade. No secrets."""
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

import kalshi_private  # noqa: E402
import prediction_job_control  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)
from t0_fav_lt90_baseline_20261024 import html_table  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "kalshi_balance_unreadable_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/kalshi_balance_unreadable_20261025.html"
)
ORDERS = RAW / "orders.jsonl"
ASKED = (
    "He is getting Kalshi balance unreadable a lot. Investigate."
)
PLAIN = (
    "The lock helpers asked Kalshi \"how much cash is in the wallet?\" from "
    "every live-game process. Kalshi answered HTTP 429 (slow down). The code "
    "treated that as \"wallet unreadable\" on every football book, wrote skip "
    "rows, filled the opportunities page with denials, and flipped the last-skip "
    "line. The JSON itself was fine: HTTP 200 uses the same field names as "
    "before (balance in cents plus balance_dollars). It was not a renamed field "
    "and not a dead key. Fix: share one good read for 60 seconds, back off on "
    "429/401/5xx, keep last known cash so a flake does not block sending, and "
    "skip the order only — do not flood the opportunities log. Phone pings for "
    "this reason drop to first plus every 5 minutes, and only when there is "
    "actually no cash on file at send time."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def skip_counts() -> tuple[int, str, str]:
    n = 0
    first = last = ""
    if not ORDERS.is_file():
        return 0, "", ""
    for line in ORDERS.read_text(encoding="utf-8").splitlines():
        if "Kalshi balance unreadable" not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        at = str(row.get("at") or "")
        if not at.startswith("2026-10-25"):
            continue
        n += 1
        first = first or at
        last = at
    return n, first, last


def consider_unread() -> tuple[int, int]:
    path = RAW / "considerations.json"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    rows = blob.get("rows") if isinstance(blob, dict) else []
    if not isinstance(rows, list):
        return 0, 0
    n = sum(1 for row in rows if "Kalshi balance unreadable" in str((row or {}).get("reason") or ""))
    return n, len(rows)


def pid_rows(jobs: dict) -> list[list[str]]:
    labels = (
        ("supervisor", "A lock supervisor (live_game_pollers.py)"),
        ("scan", "Catalog scan (overnight_scan.py)"),
        ("strategy_b", "B tennis crossover"),
        ("cfb_favorite", "C college football favorite"),
        ("spread_t0", "D T0 spreads"),
        ("tennis_t0_dog", "E tennis T0 dog"),
        ("children", "Lock --poll-one children"),
    )
    out = []
    for key, label in labels:
        rows = jobs.get(key) or []
        pids = [str(row.get("pid") or "") for row in rows]
        if key == "children":
            shown = f"{len(pids)} (many on purpose; one per live game)"
        else:
            shown = ", ".join(pids) if pids else "none"
        one = "yes" if key == "children" or len(pids) == 1 else ("none" if not pids else f"NO — {len(pids)}")
        out.append([esc(label), esc(str(len(pids))), esc(shown), esc(one)])
    return out


def main() -> int:
    n_skip, first, last = skip_counts()
    n_cons, keep = consider_unread()
    jobs = prediction_job_control.classify(prediction_job_control._ps_rows())
    sample = kalshi_private.parse_balance_usd(
        {
            "balance": 2135,
            "balance_dollars": "21.3500",
            "portfolio_value": 0,
            "updated_ts": 1761410000,
            "balance_breakdown": [{"balance": "21.3500", "exchange_index": 0}],
        }
    )
    who = html_table(
        [("Who", "text"), ("Logs the string?", "text"), ("ntfy?", "text"), ("Every book or send only?", "text")],
        [
            [esc("tools/live_lock_orders.py"), esc("Yes — builds “Kalshi balance unreadable”"), esc("Skip rows did not ntfy before. After: first + every 5 min only if cash is missing at send."), esc("Was every ready lock book after a 429. After: skip send only.")],
            [esc("Lock poller children"), esc("Yes — they import live_lock_orders"), esc("Same helper"), esc("Was every book. After: send only.")],
            [esc("overnight_scan catalog"), esc("No send; opportunities catalog only"), esc("No"), esc("Catalog never sends.")],
            [esc("B live_strategy_b.py"), esc("At send via _funds_block"), esc("No on funds skip"), esc("Send only.")],
            [esc("C live_cfb_favorite.py"), esc("At send if it hits _funds_block"), esc("No"), esc("Send only. Did not change C_HI.")],
            [esc("D live_t0_yes.py / live_spread_t0.py"), esc("At send via _funds_block"), esc("No"), esc("Send only. Did not change D NFL skip.")],
            [esc("E live_tennis_t0_dog.py"), esc("At send via _funds_block"), esc("No"), esc("Send only. Did not change E.")],
            [esc("ntfy_job_done.py"), esc("Not the source of the phrase"), esc("This job pings once for the HTML"), esc("Not every poller tick.")],
        ],
    )
    live = html_table(
        [("Check", "text"), ("Result", "text")],
        [
            [esc("Live GET /trade-api/v2/portfolio/balance"), esc("HTTP 200, then the next GET in the same second was HTTP 429")],
            [esc("200 body keys (redacted)"), esc("balance (int cents), balance_dollars (string), portfolio_value (int), balance_breakdown, updated_ts")],
            [esc("Parse of that schema"), esc("Decimal >= 0 (prefer balance_dollars). Not a field rename.")],
            [esc("401 / dead key?"), esc("No. Positions pull today was HTTP 200. First balance GET was 200.")],
            [esc("Sample payload test"), esc(f"parse_balance_usd(today’s keys) = Decimal>=0 ({sample is not None and sample >= 0})")],
            [esc("Today skip rows in orders.jsonl"), esc(f"{n_skip} from {first or '—'} through {last or '—'}")],
            [esc("Opportunities keep (500)"), esc(f"{n_cons} rows still say Kalshi balance unreadable")],
        ],
    )
    pids = html_table(
        [("Job", "text"), ("Count after reload", "num"), ("Pid(s)", "text"), ("Still one each?", "text")],
        pid_rows(jobs),
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kalshi balance unreadable — 2026-10-25</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.verdict {{ background: #fff7ed; border: 1px solid #fdba74; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Kalshi balance unreadable</h1>
<p class="note">Investigated {esc(iso_now())}. Did not sell. Did not print secrets. Did not start a second live_strategy_b.py. Did not change C_HI / FOK / D NFL skip / E.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="verdict">
<p><strong>Why it spammed:</strong> HTTP <strong>429</strong> from too many wallet GETs (164 live-game children each asking), not a renamed JSON field and not 401. One 429 made the lock helper treat Kalshi as unreadable for five minutes and deny every ready book.</p>
<p><strong>Fix:</strong> parse <code>balance_dollars</code> (and cents <code>balance</code>); share one good read for 60 seconds; back off 429/401/5xx; keep last-good cash so a flake can still send; skip the <em>send</em> only; log/ntfy first + every 5 minutes if cash is actually missing.</p>
<p><strong>ntfy volume will drop: yes.</strong> Skip events did not already ntfy, but last-skip and opportunities were noisy. After this, unread does not flood those pages, and a phone ping fires at most first + every 5 minutes when we needed cash to send and had none.</p>
</div>
<h2>Who logs the exact string</h2>
<p class="note">Grep of tools/: the phrase is built in <code>_balance_deny_reason</code> in live_lock_orders.py. Tests assert it. B and D/E call that helper at send time. Click headers to sort.</p>
{who}
<h2>Root cause</h2>
{live}
<h2>Fix in code</h2>
<ul>
<li><code>tools/kalshi_private.py</code> — <code>parse_balance_usd</code> prefers <code>balance_dollars</code>, then <code>available_balance</code>, then integer cents <code>balance</code>. Shared 60s cache. 429 backs off 60s, 401 5 min, 5xx 30s. Fail log first + every 5 min, no dollar amounts.</li>
<li><code>tools/live_lock_orders.py</code> — a 429 probe uses last-good cash instead of marking Kalshi incapable. Unreadable skips the send only (no opportunities denied row per book). Skip ledger / ntfy first + every 5 min, shared across children.</li>
<li>Reloaded the noisiest path only: lock supervisor + catalog scan + poller children (<code>restart-lock</code>). B/C/D/E pids unchanged.</li>
</ul>
<h2>Pids after reload</h2>
<p class="note">Before reload: supervisor 45432, scan 6548, B 52768, C 38640, D 60628, E 33372, 164 poll-one children. After: new supervisor/scan; B/C/D/E same; children respawning (one per live game, not a second B).</p>
{pids}
<p class="note">Tests: <code>tools/test_kalshi_private.py</code> (today’s 200 schema parses to a Decimal ≥ 0; 429 backs off without a second GET) and lock-order tests for last-good on 429 plus unread skip rate-limit. No secrets on this page.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(PAGE)
    print(FILE_URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
