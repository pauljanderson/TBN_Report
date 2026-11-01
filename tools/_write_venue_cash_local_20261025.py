"""Stamp: local venue cash slip. Does not trade. No secrets. No live dollar amounts."""
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

import prediction_job_control  # noqa: E402
import venue_cash_local  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    inject_report_page_extras,
)
from t0_fav_lt90_baseline_20261024 import html_table  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "venue_cash_local_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/venue_cash_local_20261025.html"
)
ASKED = (
    "why don't you store the cash balance locally, and each time a bet is made "
    "and confirmed update it. and then confirm it once an hour?"
)
PLAIN = (
    "We keep a local wallet slip on this PC. When a bet is made and the venue "
    "says the fill is real (fill-history, at least one contract), we subtract "
    "the after-fee cost from that slip. We ask Kalshi (and the other shops) "
    "\"how much cash is actually there?\" at most once an hour to make sure "
    "the slip still matches. We do not ask on every football book. If Kalshi "
    "says slow down (HTTP 429), we keep the slip and wait; we do not flood "
    "the phone with \"balance unreadable.\""
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def file_bits() -> list[list[str]]:
    cash = venue_cash_local.CASH_FILE
    exists = cash.is_file()
    venues = []
    confirm_age = "no file yet"
    if exists:
        try:
            data = json.loads(cash.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        meta = data.get("venues") if isinstance(data, dict) else {}
        now = datetime.now().timestamp()
        for venue in venue_cash_local.VENUES:
            row = meta.get(venue) if isinstance(meta, dict) else {}
            if not isinstance(row, dict):
                continue
            ts = float(row.get("last_venue_confirm_ts") or 0)
            due = venue_cash_local.confirm_due(data, venue, now=now)
            venues.append(venue)
            if ts:
                age_min = max(0, int((now - ts) / 60))
                confirm_age = f"{age_min} min since a venue confirm (hourly if due)"
    return [
        [esc("Local slip"), esc(str(cash).replace(str(ROOT), "stockresearch"))],
        [esc("Helper"), esc("tools/venue_cash_local.py")],
        [esc("File on disk?"), esc("yes" if exists else "no — first hourly confirm will create it")],
        [esc("Venues on the slip"), esc(", ".join(venues) if venues else "kalshi, gemini, polymarket, novig")],
        [esc("Hourly clock"), esc(confirm_age)],
        [esc("On git / Drive?"), esc("No. local/ raw only.")],
    ]


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
    jobs = prediction_job_control.classify(prediction_job_control._ps_rows())
    who = html_table(
        [("Who", "text"), ("Reads local slip?", "text"), ("Wallet GET?", "text"), ("Debit on fill?", "text")],
        [
            [esc("tools/venue_cash_local.py"), esc("Yes — the slip"), esc("At most once per venue per hour"), esc("apply_delta after confirm qty ≥ 1")],
            [esc("tools/live_lock_orders.py"), esc("ensure_venue_balance / _funds_block"), esc("Only hourly confirm_from_venue"), esc("_after_send_hooks → _apply_confirmed_fill_to_local_cash")],
            [esc("Lock poller children"), esc("Same helper"), esc("Shared hourly; not every book"), esc("Same hook after fill-history confirm")],
            [esc("B live_strategy_b.py"), esc("At send via _funds_block"), esc("Hourly, not every look"), esc("Same _send hook")],
            [esc("C live_cfb_favorite.py"), esc("At send via _funds_block"), esc("Hourly"), esc("Same _send hook. Did not change C_HI.")],
            [esc("D live_t0_yes.py / live_spread_t0.py"), esc("At send via _funds_block"), esc("Hourly"), esc("Same _send hook. Did not change D NFL skip.")],
            [esc("E live_tennis_t0_dog.py"), esc("At send via _funds_block"), esc("Hourly"), esc("Same _send hook. Did not change E.")],
        ],
    )
    rules = html_table(
        [("Rule", "text"), ("What happens", "text")],
        [
            [esc("Before send"), esc("Read the local slip. Skip only if cash is too low, or missing and the hourly confirm failed.")],
            [esc("Confirmed fill (qty ≥ 1)"), esc("Subtract after-fee cost. Fill-history is truth, not the order HTTP tape.")],
            [esc("Kalshi 201 + fill_count 0"), esc("Empty cancel. Do not debit.")],
            [esc("Poly HTTP 200"), esc("HTTP OK only. Fill is this order’s cumQuantity / confirm qty. Empty activities do not override cumQuantity.")],
            [esc("Flatten buy-opposite"), esc("Still a buy: debit the opposite contract. A true SELL intent would credit proceeds.")],
            [esc("Hourly confirm"), esc("One GET per venue per hour, locked so 164 children share it. Overwrite the slip. Log drift locally. 429 keeps the slip, backs off, no ntfy spam.")],
            [esc("Unread phrase"), esc("“Kalshi balance unreadable” only if the slip is empty and the hourly GET failed. First + every 5 minutes. Not every book.")],
        ],
    )
    leftover = html_table(
        [("Still a GET?", "text"), ("When", "text"), ("Wallet?", "text")],
        [
            [esc("Gemini terms/status"), esc("Capability probe, ~5 min per process"), esc("No — prediction-market terms, not cash")],
            [esc("live_lock_orders.smoke()"), esc("Manual diagnostic only"), esc("Yes — not on the live poller tick")],
            [esc("kalshi_private.balance_usd"), esc("Called only by the hourly confirm fetch"), esc("Yes — 8s race guard + 429 backoff, not the send path")],
        ],
    )
    files = html_table(
        [("Item", "text"), ("Value", "text")],
        file_bits(),
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
<title>Local venue cash slip — 2026-10-25</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.verdict {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Local venue cash slip</h1>
<p class="note">Done {esc(iso_now())}. Did not sell. Did not print secrets. Did not start a second live_strategy_b.py. Did not transfer money. Did not change C_HI / FOK / D NFL skip / E / NET_MAX. Research live only. Not gold. Not DailyRun.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="verdict">
<p><strong>Replaced</strong> the 60-second wallet GET cache (the band-aid after this morning’s HTTP 429 “balance unreadable” spam) with your pattern: local slip, debit on confirmed fill, venue confirm once an hour.</p>
<p><strong>Kalshi wallet GET is now hourly</strong>, shared across lock children and B/C/D/E. It is not on every book or every game.</p>
</div>
<h2>Where the slip lives</h2>
<p class="note">Click headers to sort. No live dollar amounts on this page.</p>
{files}
<h2>Who uses it</h2>
{who}
<h2>Rules</h2>
{rules}
<h2>Leftover GETs that are not the wallet-every-look problem</h2>
{leftover}
<h2>Pids after reload</h2>
<p class="note">Lock supervisor + catalog scan + poller children were reloaded so they load the new helper. B/C/D/E each reloaded one process (stop then start one; never a second B). Children respawn one per live game.</p>
{pids}
<p class="note">Debit hook: <code>live_lock_orders._after_send_hooks</code> → <code>_apply_confirmed_fill_to_local_cash</code> after venue fill-history confirm. Tests: <code>tools/test_venue_cash_local.py</code>, lock-order debit / empty-cancel tests. No secrets on this page.</p>
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
