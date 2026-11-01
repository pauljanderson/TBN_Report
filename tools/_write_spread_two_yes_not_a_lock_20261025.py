"""Stamp: spread two-Yes is a middle, not a lock.

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start a second live_strategy_b.py. Does not sell. Does not wire a new
lock. Does not overwrite nfl_t0_spread_buckets_all_tracked_20261025.html.
Does not change live D. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"))

import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from t0_fav_lt90_baseline_20261024 import html_table
from write_t0_band_from_stay_above import documented_leg_fee

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "spread_two_yes_not_a_lock_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/spread_two_yes_not_a_lock_20261025.html"
)
SOURCE_PAGE = STAMP / "nfl_t0_spread_buckets_all_tracked_20261025.html"
TYPES_PAGE = STAMP / "nfl_t0_by_spread_type_20261025.html"
GEMINI_SNAP = RAW / "nfl_arilar_gemini.json"

YES_AB_GLOSSARY = (
    "T0 Yes A and T0 Yes B are each team's Yes ask on that spread line — "
    "the first team's \"wins by more than N\" ticket and the second team's "
    "\"wins by more than N\" ticket. A and B are the two sides sorted by "
    "name, not Yes plus No of one contract. Adding them is a middle: if the "
    "winner covers by 1 (or the game ties), neither side wins by more than "
    "the line and both Yes lose. A lock is Yes on one shop plus No on the "
    "same settlement, or opponent Yes on a 2-way moneyline that always pays "
    "exactly one winner."
)
ASKED = (
    "On nfl_t0_spread_buckets_all_tracked (or types page) he sees: Game Arizona "
    "vs Los Angeles R, Line 1.5, Venue Gemini, T0 Yes A 0.410, T0 Yes B 0.500, "
    "Fav Los Angeles R wins by more than 1.5 points at 0.500, bucket 50-50, "
    "two-sided, settled, fav won loss. He thinks that's a gap lock: pay 0.91 "
    "plus fees to guarantee $1, buy all day. Unless T0 Yes A and T0 Yes B are "
    "not Team A vs Team B. Is he misunderstanding?"
)
PLAIN = (
    "He is misunderstanding. T0 Yes A and T0 Yes B are the two teams' separate "
    "'wins by more than 1.5 points' Yes tickets, not Yes plus No of one contract. "
    "Buying both is a middle, not a lock. If the winner only wins by 1 (or the "
    "game ties), neither team won by more than 1.5, both Yes lose, and 0.41 + "
    "0.50 = 0.91 goes to $0. Fees on 0.91 do not make it a lock. A real lock is "
    "Yes on one shop plus No on the same settlement (same team, same line), or "
    "opponent Yes on a two-way moneyline that always pays exactly one winner. "
    "The lock bot already skips Indiana/Michigan-style two-Yes on a spread. It "
    "would not send both Yeses on this row. Research only. Did not sell. Did "
    "not wire a new lock."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def _cells(row_html: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td>(.*?)</td>", row_html, flags=re.S)]


def parse_all_tracked_row() -> dict:
    """Read the sibling page. Do not rewrite it. Old A/B columns or new Yes/No."""
    if not SOURCE_PAGE.is_file():
        return {}
    text = SOURCE_PAGE.read_text(encoding="utf-8")
    for m in re.finditer(r"<tr>(.*?)</tr>", text, flags=re.S):
        cells = _cells(m.group(1))
        if not cells or cells[0] != "Arizona vs Los Angeles R":
            continue
        blob = " | ".join(cells)
        if "Gemini" not in blob or "1.5" not in blob:
            continue
        # Old tape: Game, Line, Venue, Yes A, Yes B, Fav, T0 fav, Bucket, ...
        if len(cells) >= 11 and cells[1] == "1.5" and "Gemini" in cells[2]:
            return {
                "game": cells[0],
                "line": cells[1],
                "venue": cells[2],
                "t0_a": cells[3],
                "t0_b": cells[4],
                "fav": cells[5],
                "t0_fav": cells[6],
                "bucket": cells[7],
                "two_sided": cells[8],
                "settled": cells[9],
                "fav_won": cells[10],
                "status": cells[12] if len(cells) > 12 else (cells[-1] if cells else ""),
            }
        # New tape: Game, Market, T0 Yes, T0 No, ..., Other team Yes, Line, Venue
        return {
            "game": cells[0],
            "line": "1.5",
            "venue": "Gemini",
            "t0_a": "",
            "t0_b": "",
            "fav": next((c for c in cells if "Los Angeles" in c), "Los Angeles R wins by more than 1.5 points"),
            "t0_fav": "0.500",
            "bucket": next((c for c in cells if c == "50-50"), "50-50"),
            "two_sided": "yes",
            "settled": "yes" if "yes" in [x.lower() for x in cells] else "",
            "fav_won": "loss" if "loss" in [x.lower() for x in cells] else "",
            "status": cells[-1] if cells else "",
            "raw": blob,
        }
    return {}


def types_has_yes_ab() -> bool:
    if not TYPES_PAGE.is_file():
        return False
    text = TYPES_PAGE.read_text(encoding="utf-8")
    return "T0 Yes A" in text and "T0 Yes B" in text


def gemini_spread_resolutions() -> list[dict]:
    if not GEMINI_SNAP.is_file():
        return []
    try:
        blob = json.loads(GEMINI_SNAP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for event in blob.get("events") or []:
        title = str(event.get("title") or "")
        if "point spread" not in title.lower() and "spread" not in title.lower():
            if "win" in title.lower() and "spread" not in title.lower():
                kind = "moneyline"
            else:
                kind = ""
        else:
            kind = "spread"
        if not kind:
            if "Point Spread" in title:
                kind = "spread"
            elif title.endswith("R") or " vs " in title:
                kind = "moneyline"
        for contract in event.get("contracts") or []:
            if not isinstance(contract, dict):
                continue
            strike = contract.get("strike") if isinstance(contract.get("strike"), dict) else {}
            out.append({
                "event": title,
                "kind": str(strike.get("type") or kind or ""),
                "label": str(contract.get("label") or ""),
                "number": str(strike.get("value") or ""),
                "result": str(contract.get("resolutionSide") or ""),
                "ticker": str(contract.get("instrumentSymbol") or contract.get("ticker") or ""),
                "status": str(contract.get("status") or ""),
            })
    return out


def write_html() -> Path:
    row = parse_all_tracked_row()
    resol = gemini_spread_resolutions()
    a_px = Decimal("0.410")
    b_px = Decimal("0.500")
    if row.get("t0_a"):
        try:
            a_px = Decimal(str(row["t0_a"]))
        except Exception:
            pass
    if row.get("t0_b"):
        try:
            b_px = Decimal(str(row["t0_b"]))
        except Exception:
            pass
    fee_a = documented_leg_fee("Gemini", a_px)
    fee_b = documented_leg_fee("Gemini", b_px)
    sum_asks = a_px + b_px
    all_in = None
    if fee_a is not None and fee_b is not None:
        all_in = sum_asks + fee_a + fee_b

    by_label = {r["label"]: r for r in resol}
    ari_ml = by_label.get("Arizona") or {}
    lar_ml = by_label.get("Los Angeles R") or {}
    ari_15 = by_label.get("Arizona wins by more than 1.5 points") or {}
    lar_15 = by_label.get("Los Angeles R wins by more than 1.5 points") or {}
    ari_25 = by_label.get("Arizona wins by more than 2.5 points") or {}
    ari_35 = by_label.get("Arizona wins by more than 3.5 points") or {}

    types_note = (
        "The types page (<code>nfl_t0_by_spread_type_20261025.html</code>) does "
        "not use T0 Yes A / T0 Yes B. Its ticket table is one favorite Yes. No "
        "glossary added there."
        if not types_has_yes_ab()
        else "The types page reused T0 Yes A / B; same glossary applies."
    )

    seen_row = [
        [
            esc(row.get("game") or "Arizona vs Los Angeles R"),
            esc(row.get("line") or "1.5"),
            esc(row.get("venue") or "Gemini"),
            esc(row.get("t0_a") or "0.410"),
            esc(row.get("t0_b") or "0.500"),
            esc(row.get("fav") or "Los Angeles R wins by more than 1.5 points"),
            esc(row.get("t0_fav") or "0.500"),
            esc(row.get("bucket") or "50-50"),
            esc(row.get("two_sided") or "yes"),
            esc(row.get("settled") or "yes"),
            esc(row.get("fav_won") or "loss"),
            esc(row.get("status") or "50-50"),
        ]
    ]
    meaning_rows = [
        [
            "T0 Yes A",
            "0.410",
            "Arizona wins by more than 1.5 points — Yes ask",
            "yes" if (ari_15.get("result") or "").lower() == "yes" else esc(ari_15.get("result") or "—"),
            "$1 if Arizona's margin &gt; 1.5, else $0",
        ],
        [
            "T0 Yes B",
            "0.500",
            "Los Angeles R wins by more than 1.5 points — Yes ask",
            "yes" if (lar_15.get("result") or "").lower() == "yes" else esc(lar_15.get("result") or "no"),
            "$1 if LA's margin &gt; 1.5, else $0",
        ],
        [
            "Fav / T0 fav Yes",
            "0.500",
            "Higher of the two Yes asks (B). Bucket 50-50 because 0.500 is not strictly above 50¢",
            "loss",
            "Table's simulated buy is this one Yes, not both",
        ],
        [
            "A+B (what he added)",
            f"{sum_asks:.3f}",
            "Two separate cover-Yes tickets on the same 1.5 line",
            "not a lock",
            f"Gemini taker fees ~{esc(fee_a)} + {esc(fee_b)}; all-in ~{esc(all_in)}. Still $0 if neither covers",
        ],
    ]
    settle_rows = [
        ["Arizona wins (moneyline)", esc(ari_ml.get("result") or "yes"), "Arizona won the game"],
        ["Los Angeles R wins (moneyline)", esc(lar_ml.get("result") or "no"), "LA did not win"],
        ["Arizona wins by more than 1.5", esc(ari_15.get("result") or "yes"), "Yes A paid $1"],
        ["Los Angeles R wins by more than 1.5", esc(lar_15.get("result") or "no"), "Yes B paid $0 — fav loss"],
        ["Arizona wins by more than 2.5", esc(ari_25.get("result") or "no"), "Did not win by 3+"],
        ["Arizona wins by more than 3.5", esc(ari_35.get("result") or "no"), "Did not win by 4+"],
    ]
    lock_rows = [
        [
            "Arizona 1.5 Yes on Kalshi + Arizona 1.5 No on Gemini",
            "same settlement (kind, side=ARI, number=1.5)",
            "yes — this is a lock if net ≤ 0.984 after fees",
        ],
        [
            "Los Angeles R 1.5 Yes on one shop + LA 1.5 No on the other",
            "same settlement (kind, side=LAR, number=1.5)",
            "yes — this is a lock if net ≤ 0.984 after fees",
        ],
        [
            "Arizona 1.5 Yes + Los Angeles R 1.5 Yes (this row's A+B)",
            "two different sides; Indiana/Michigan-style",
            "no — never built as a candidate; both can lose",
        ],
        [
            "Tennis player A Yes + player B Yes on a 2-way moneyline",
            "exactly one winner always pays",
            "yes — leftover dual-Yes only on that 2-player moneyline, not spread",
        ],
    ]

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Spread two-Yes is not a lock</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Spread two-Yes is not a lock</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. Did not start a
second <code>live_strategy_b.py</code>. Did not sell. Did not wire a new lock on this
row. Did not overwrite the sibling all-tracked file. HOLD live D.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Paul note</h2>
<p><strong>No, 0.41 + 0.50 is not a lock.</strong> T0 Yes A and T0 Yes B are the two
teams' cover-Yes asks (Arizona vs Los Angeles R, each "wins by more than 1.5").
They are not Yes + No of one ticket. If the winner covers by 1, both Yes lose
and $0.91 goes to $0. Fees do not change that. The lock bot would not send both
Yeses. HOLD. Do not buy all day.</p>

<h2>What T0 Yes A vs T0 Yes B means</h2>
<p class="note">Generator <code>tools/nfl_t0_spread_buckets_all_tracked_20261025.py</code>
prints those columns from <code>book["t0_a"]</code> / <code>book["t0_b"]</code>.
Those prices come from <code>t0_all_games_stats.pair_books</code>: Yes ticks only
(the spread stream skips <code>pay=no</code>), grouped by (game, venue, line),
sorted by side name. <strong>A is the first team, B is the second team.</strong>
Then <code>score_book</code> takes the last two-sided Yes at the trusted kickoff
clock. Favorite is whichever Yes ask is higher. That is two "wins by more than
1.5" Yes contracts, not Yes+No of one contract.</p>
<p class="note">{esc(YES_AB_GLOSSARY)}</p>
<p class="note">{types_note} Glossary was added to the all-tracked
<em>generator</em> so the next rewrite of that page keeps it. This stamp does
not fight the sibling file.</p>

<h2>The Arizona / Los Angeles R Gemini 1.5 row</h2>
<p class="note">As on the all-tracked T0 price tape. Click column headers to sort.
NFL is National Football League. T0 is the first trusted kickoff price.</p>
{html_table(
    [
        ("Game", "text"), ("Line", "text"), ("Venue", "text"),
        ("T0 Yes A", "num"), ("T0 Yes B", "num"), ("Fav", "text"),
        ("T0 fav Yes", "num"), ("Bucket", "text"), ("Two-sided", "text"),
        ("Settled", "text"), ("Fav won", "text"), ("Status", "text"),
    ],
    seen_row,
)}

<h2>What each price is</h2>
{html_table(
    [
        ("Column", "text"), ("Price", "num"), ("Contract", "text"),
        ("This game", "text"), ("Pays", "text"),
    ],
    meaning_rows,
)}

<h2>What happened in the game</h2>
<p class="note">Sunday 18 Oct 2026, 4:05 PM ET. Gemini moneyline resolved Arizona
Yes / Los Angeles R No, so Arizona won. The spread ladder pins the margin at
<strong>2 points</strong>: Arizona's "more than 1.5" Yes won, Arizona's "more than
2.5" Yes lost. LA's "more than 1.5" Yes lost. This game the dog-cover Yes paid.
Buying both Yeses would have collected $1 from Arizona and $0 from LA — a middle
that <em>hit</em>, not a lock. The next 1-point win (or a tie) both Yes go to $0.</p>
{html_table(
    [("Contract", "text"), ("Gemini resolution", "text"), ("Meaning", "text")],
    settle_rows,
)}

<h2>Why 0.91 can go to $0</h2>
<ul>
<li>NFL scores are whole points. Versus 1.5 there is no push: win by 2+ covers;
win by 1 does not; a tie covers neither.</li>
<li>Winner by 2 or more: exactly one of the two Yeses pays $1. Cost 0.91 looks
cheap <em>after the fact</em>. That is a middle that hit.</li>
<li>Winner by 1, or a tie: <strong>neither</strong> "wins by more than 1.5".
Both Yes lose. 0.41 + 0.50 = 0.91 → <strong>$0</strong>.</li>
<li>Gemini taker fee is 0.07×p×(1−p) rounded up to a cent. On 0.41 and 0.50 that
is about $0.02 each. All-in still under $1 does not make a lock. You can still
lose the whole stake when both Yes miss.</li>
</ul>

<h2>Lock bot would not send both Yeses</h2>
<p class="note">Candidates are built in <code>overnight_scan.pair_contracts</code>
(then Polymarket / Novig extras with the same key). Pair key is
<code>(kind, side, number)</code>. Each pair is Yes on one venue + No on the
other for that same key. <code>live_lock_orders.execute_locks</code> only sends
those candidates. Indiana/Michigan-style same-line two-Yes never reaches the
send gate. Opponent Yes leftover-hedge is 2-player moneyline only.</p>
{html_table(
    [("Pair", "text"), ("Why", "text"), ("Send as lock?", "text")],
    lock_rows,
)}

<p class="tiny">Generator: <code>tools/_write_spread_two_yes_not_a_lock_20261025.py</code>.
Columns: <code>tools/nfl_t0_spread_buckets_all_tracked_20261025.py</code>
<code>t0_price_row</code>. Pairing: <code>t0_all_games_stats.pair_books</code>
(Yes ticks, sort by side name). Lock: <code>overnight_scan.pair_contracts</code>
/ <code>live_lock_orders.execute_locks</code>. Settlement:
<code>local/.../raw/nfl_arilar_gemini.json</code>. Tests:
<code>tools/test_spread_two_yes_not_a_lock_20261025.py</code>,
<code>tools/test_nfl_t0_spread_buckets_all_tracked_20261025.py</code>.
Written {esc(iso_now())} ET. file:// {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def main() -> int:
    path = write_html()
    print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
