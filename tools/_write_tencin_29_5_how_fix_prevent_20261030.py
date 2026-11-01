"""Paul's three questions: how TEN/CIN 29.5 sent, the matcher fix, prevent again.

Display only. Does not sell. Does not start a second A or B.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import job_status_positions as jsp
import opportunity_considerations as oc
import price_memory
from prediction_paths import DRIVE_STAMP as STAMP, ONE_LEG_WATCH, RAW_DIR as RAW
from report_page_extras import (
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)
from write_orders_performance import table

ET = ZoneInfo("America/New_York")
OUT = STAMP / "tencin_29_5_how_fix_prevent_20261030.html"
ORDERS = RAW / "orders.jsonl"
CONSIDER = RAW / "considerations.json"
KPOS = RAW / "kalshi_positions_pull.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tencin_29_5_how_fix_prevent_20261030.html"
)

KALSHI_TEAM = "KXNFLTEAMTOTAL-26NOV01TENCIN-CIN30"
KALSHI_GAME = "KXNFLTOTAL-26NOV01TENCIN-30"
NOVIG_MARKET = "01a178fd-2f52-71a3-93b5-4c671fd27ff8"

PAUL = (
    "1. How did this happen? Read live_lock_sender / game-key / line matching. "
    "Why did 29.5 + TEN/CIN + Over/Under pass as a lock? (team total ticker vs game total, "
    "Novig “Under 29.5” unlabeled as game, same-line match without bet-type). Quote the code path. "
    "Not a flatten bug — a false same-settlement send. "
    "2. What are you going to do to fix it? Matcher: team total ≠ game total ≠ spread ≠ ML. "
    "Same line + same team/side. TEN/CIN fixture must NOT send. Open now / opportunities: label "
    "this pair not a lock (holding two directional). Do not flatten/sell unless Paul later asks. "
    "Scan other open A pairs for the same mismatch; list them; don’t silently sell. Reload one A "
    "so live code has the matcher. "
    "3. What are you going to do to make sure it does not happen again? Tests (this fixture + a "
    "true lock of team-over vs team-under same 29.5 that SHOULD still match). REST recheck must "
    "see bet type. Don’t pair on line number alone."
)


def esc(value) -> str:
    return oc._esc(value)


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def scan_mismatched_open() -> list[dict]:
    """Open A pairs whose legs are not the same settlement. Does not sell."""
    groups: dict[str, list[dict]] = defaultdict(list)
    if ORDERS.exists():
        with ORDERS.open(encoding="utf-8") as handle:
            for line in handle:
                if "sent" not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("event") != "sent":
                    continue
                ident = str(row.get("instrument") or row.get("ticker") or "")
                if not ident:
                    continue
                key = str(row.get("bet_key") or "") or "\t".join(
                    str(row.get(k) or "") for k in ("game", "sport")
                )
                groups[key].append(row)
    tape_bad = jsp.tape_mismatch_idents()
    held = set()
    kpos = load_json(KPOS) or {}
    body = kpos.get("body") if isinstance(kpos.get("body"), dict) else kpos
    for item in (body or {}).get("market_positions") or (body or {}).get("positions") or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "")
        try:
            qty = float(item.get("position_fp") or item.get("position") or 0)
        except (TypeError, ValueError):
            qty = 0
        if ticker and abs(qty) >= 1:
            held.add(ticker)
    watch = load_json(ONE_LEG_WATCH) or {}
    watches = watch.get("watches") if isinstance(watch.get("watches"), list) else []
    if isinstance(watch, dict) and watch.get("bet_key") and not watches:
        watches = [watch]
    watch_idents = set()
    for item in watches:
        if not isinstance(item, dict) or item.get("stopped"):
            continue
        for key in ("filled_instrument", "missed_instrument"):
            ident = str(item.get(key) or "")
            if ident:
                watch_idents.add(ident)

    out: list[dict] = []
    seen: set[str] = set()
    for key, rows in groups.items():
        idents = [str(r.get("instrument") or r.get("ticker") or "") for r in rows]
        extras = []
        parts = key.split("\t")
        if len(parts) >= 4:
            extras.append(parts[3])
        kinds = price_memory.settlement_kinds(*idents, *extras)
        if len(kinds) <= 1 and not any(i in tape_bad for i in idents):
            continue
        still = [i for i in idents if i in held or i in watch_idents]
        if not still and KALSHI_TEAM not in idents:
            # Closed/sold pairs stay off this open list.
            if not any(i in held for i in idents):
                continue
        mark = key + "|" + "|".join(sorted(set(idents)))
        if mark in seen:
            continue
        seen.add(mark)
        sample = rows[0]
        parts = key.split("\t")
        game = str(sample.get("game") or "")
        sport = str(sample.get("sport") or "")
        if not sport and parts:
            sport = parts[0]
        if not game and len(parts) > 1:
            game = parts[1]
        if game == "tencin":
            game = "Tennessee vs Cincinnati Pro Football"
        out.append({
            "game": game,
            "sport": sport,
            "idents": sorted(set(idents)),
            "kinds": " vs ".join(sorted(kinds)),
            "held": "yes" if any(i in held for i in idents) else "no",
            "open_now": "yes" if any(i in held or i in watch_idents for i in idents) else "no",
            "venues": ", ".join(sorted({str(r.get("venue") or "") for r in rows})),
            "note": "team total vs game total" if kinds == {"team_total", "total"} else "mixed bet types",
        })
    # Kalshi-held TEAMTOTAL even if the Novig leg is not in positions.
    if KALSHI_TEAM in held and not any(KALSHI_TEAM in row["idents"] for row in out):
        out.append({
            "game": "Tennessee vs Cincinnati Pro Football",
            "sport": "pro football",
            "idents": [KALSHI_TEAM, NOVIG_MARKET],
            "kinds": "team_total vs total",
            "held": "yes",
            "open_now": "yes",
            "venues": "kalshi, novig",
            "note": "team total vs game total",
        })
    return out


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    mismatched = scan_mismatched_open()
    tape_bad = sorted(jsp.tape_mismatch_idents())
    consider_type = oc._attempt_type({
        "market_type": "total",
        "side": "Cincinnati over 29.5 points scored",
        "kalshi_ticker": KALSHI_TEAM,
        "decision": "sent",
        "source": "websocket",
    })
    mismatch_rows = [
        [
            row.get("game") or "",
            row.get("sport") or "",
            row.get("venues") or "",
            ", ".join(row.get("idents") or []),
            row.get("kinds") or "",
            row.get("open_now") or "",
            row.get("held") or "",
            row.get("note") or "",
        ]
        for row in mismatched
    ]
    if not mismatch_rows:
        mismatch_rows = [["—", "—", "—", "none besides TEN/CIN if it already listed above", "—", "—", "—", "no other open mismatch found"]]
    mismatch_table = table(
        [
            ("Game", "text"),
            ("Sport", "text"),
            ("Venues", "text"),
            ("Instruments", "text"),
            ("Bet types", "text"),
            ("Open now", "text"),
            ("Kalshi held", "text"),
            ("Why not a lock", "text"),
        ],
        mismatch_rows,
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>TEN vs CIN 29.5 — how, fix, prevent</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
.loud {{ background: #fef2f2; border: 2px solid #dc2626; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
pre {{ background: #0f172a; color: #e2e8f0; padding: 12px 14px; overflow: auto; font-size: 0.85em; }}
{SORTABLE_TH_CSS}
.swipe-note {{ color: #555; font-size: 0.95em; }}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>TEN vs CIN 29.5 — how it sent, the fix, how it stays fixed</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now)}.
Did not commit. Did not start a second B. Did not leftover-GTC on A. Did not DailyRun.
Did not sell the TEN/CIN tickets.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: “{esc(PAUL)}”</p>
<h2>In plain English</h2>
<p>We bought two different football questions that share the number 29.5. Kalshi pays $1
if the Bengals score 30 or more. Novig pays $1 if the whole game stays under 29.5 combined
points. Those are not Yes and No of one contract, so this is not a lock. Both tickets filled.
We are holding both. The matcher is now required to check bet type (team total vs game total
vs spread vs moneyline), not just the game and the line. Open now / opportunities label this
pair <strong>not a lock (two directional)</strong>. Did not sell.</p>
</div>

<div class="loud">
<p><strong>Same-settlement: no.</strong> Holding both. Kalshi
<code>{KALSHI_TEAM}</code> (Bengals team Over 29.5) vs Novig Under 29.5 (full game).
Kalshi’s own game total is <code>{KALSHI_GAME}</code>. Opportunities type for this pair:
<code>{esc(consider_type)}</code>.</p>
</div>

<h2>1. How did this happen?</h2>
<p>Not a flatten bug. A <strong>false same-settlement send</strong>.</p>
<p>Lock gap A does not match inside <code>live_lock_sender.py</code>. The sender reads
per-game hint files and calls <code>execute_locks</code>. The match is built earlier:
poller → <code>novig_live.novig_candidates</code> → <code>_pair_rows</code>, which buckets
views by <code>(kind, side_key, number)</code>. Same game (TEN/CIN) + same line (29.5) +
Over on one shop vs Under/No on the other was treated as one $1 question.</p>
<p>Kalshi’s contract title is “Cincinnati over 29.5 points scored”.
<code>overnight_scan.parse_side</code> saw the words “over 29.5” and returned
<code>kind="total"</code> (game total). The ticker is <code>KXNFLTEAMTOTAL</code>, a
<strong>team</strong> total, but <code>contract_view</code> then kept the parsed kind
<code>total</code> and only allowed moneyline / spread / total — so a true
<code>team_total</code> either collapsed into a game total or was dropped.</p>
<p>For game totals, <code>side_key</code> is only <code>"over"</code> or <code>"under"</code>.
Novig’s unlabeled “Under 29.5” is a full-game total. Kalshi Yes (team Over) therefore
bucketed with Novig No (game Under). After-fee 0.53+0.09+fee = 0.6375, under the send
line, so A sent it: hard Kalshi first 18:19:50, easy Novig 18:19:52. REST recheck only
re-read those two books’ prices and sizes. It did not ask whether they settle the same
question.</p>
<pre>parse_side("Cincinnati over 29.5 points scored") → ("total", "over", "29.5")  # old
contract_view: kind not in (moneyline, spread, total) → drop team_total
_pair_rows key = (kind, side_key, number) = ("total", "over", "29.5")
live_lock_sender → execute_locks → qualifies (no bet-type check) → send</pre>
<p>Sibling explainer (settlement identity, fills, payout matrix):
<a href="tencin_29_5_not_same_settlement_20261030.html">tencin_29_5_not_same_settlement_20261030.html</a>.</p>

<h2>2. What are you going to do to fix it?</h2>
<ul>
<li><strong>Matcher:</strong> ticker series wins. Team total ≠ game total ≠ spread ≠ moneyline.
Same game, same bet type, same line, and for a team total the same team. Over on one shop
only locks with Under/No of that same total. TEN/CIN 29.5 team vs game must not send.</li>
<li><strong>Send gate:</strong> <code>qualifies</code> and REST recheck reject mixed kinds
on the instruments, not the line number alone.</li>
<li><strong>Open now / opportunities:</strong> this pair is labeled
<strong>not a lock (two directional)</strong>. Holding both. Did not flatten or sell.</li>
<li><strong>Scan:</strong> other open A pairs with mixed settlement are listed below. Did
not silently sell any of them.</li>
<li><strong>Reload one A</strong> (<code>prediction_job_control.py reload-lock</code>) so
the live supervisor / sender load this matcher. Not a second A. Not a second B.</li>
</ul>

<h2>3. What are you going to do to make sure it does not happen again?</h2>
<ul>
<li>Tests in <code>tools/test_tencin_same_settlement.py</code>: this TEN/CIN fixture must
<strong>not</strong> pair or qualify. A true lock of Bengals team Over 29.5 vs team Under
29.5 on the other shop <strong>must still match</strong>.</li>
<li>REST recheck now sees bet type on each leg’s instrument (<code>same_settlement_legs</code>).
A leftover hint file with the old pair cannot send after reload.</li>
<li>Do not pair on line number alone. 29.5 team CIN is not 29.5 game.</li>
</ul>

<h2>Open A pairs that are not the same $1</h2>
<p>Click column headers to sort.</p>
{mismatch_table}
<p>Tape instruments flagged mixed-settlement: {esc(", ".join(tape_bad) or "none")}.</p>
<p>Other open A on the kitchen (not mixed-settlement sends): PHI vs WAS is Yes+No of the
same moneyline (true lock). MIN vs DET has a spread ticket and a separate moneyline
ticket — two holdings, not a team-vs-game pair we sent. Did not sell any of them.</p>
<p>Did not leftover-GTC. Holding TEN/CIN until Paul asks otherwise.</p>

<p class="note">Manual: <code>python tools/_write_tencin_29_5_how_fix_prevent_20261030.html</code>
is this generator. Matcher: <code>overnight_scan.contract_view</code> /
<code>views_same_settlement</code>, <code>novig_live._pair_rows</code>,
<code>live_lock_orders.qualifies</code>. {esc(FILE_URL)}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    # Fix the accidental .html in the manual line
    html = html.replace(
        "python tools/_write_tencin_29_5_how_fix_prevent_20261030.html",
        "python tools/_write_tencin_29_5_how_fix_prevent_20261030.py",
    )
    OUT.write_text(html, encoding="utf-8")
    print(OUT)
    print("mismatched_open", json.dumps(mismatched, ensure_ascii=False))
    print("tape_bad", json.dumps(tape_bad))


if __name__ == "__main__":
    main()
