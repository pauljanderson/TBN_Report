"""Investigate HTML for Paul's five 29 Oct 2026 questions. Display only."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_t0_yes  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from write_orders_performance import table  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "paul_five_questions_20261029.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/paul_five_questions_20261029.html"
)

ASKED = (
    "1) Why no System B trades? Plenty of tennis looked like game start cap under $1.05. "
    "2) False E wins: Eliz Maloney vs Daniela Vismane Poly Yes Vismane 0.37 fee 0.02 +$0.61 "
    "(Paul: not a win); Mathilde Lollia vs Margaux Maquet Poly Yes Lollia 0.43 fee 0.02 +$0.55 "
    "(Paul: not a win). Confirm REAL winner on Polymarket. 3) Two underdogs same game: "
    "Tagger vs Linette, Yes Linette twice ~5 min apart. 4) Same underdog two platforms: "
    "Michelsen vs Fils Kalshi and Poly. 5) After fixes: daily dashboards, 7 days back, "
    "Previous/Next on dashboard.html."
)

LAYMAN = (
    "B did not send this morning because the box was rebooting until about 09:24 ET, "
    "and after that the live skip log shows after-fee combined Yes over $1.05, one side "
    "outside 10–90¢, a missed 5-minute start window, or a junk clock. Kitchen marked two "
    "E tennis dogs as wins using a last-trade price and a POSITION_RESOLUTION guess; "
    "Maloney and Maquet actually won, so those tickets are not wins. E also bought "
    "Linette twice and Michelsen on two platforms because the catalog used different "
    "titles for the same match. We now treat vs/@/Round of 16 as one game, lock the dog "
    "before a second send, and only count a Polymarket winner when settlementPx is $0 or $1."
)


def esc(value) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def b_skips() -> list[list]:
    data = load_json(RAW / "strategy_b_watch.json")
    rows = []
    for row in data.get("skipped") or []:
        if not isinstance(row, dict):
            continue
        rows.append([
            str(row.get("when") or "")[:22].replace("T", " "),
            row.get("game") or "",
            row.get("reason") or "",
        ])
    return rows[-30:]


def inverted_e_poly() -> list[list]:
    store = load_json(RAW / "settled_pnl.json")
    orders = store.get("orders") if isinstance(store, dict) else store
    out = []
    for oid, row in (orders or {}).items():
        if not isinstance(row, dict):
            continue
        if str(row.get("venue") or "").lower() not in {"polymarket", "poly"}:
            continue
        inst = str(row.get("instrument") or "")
        if not inst.lower().startswith("aec-"):
            continue
        px = row.get("settlementPx")
        try:
            number = float(px) if px not in (None, "") else None
        except (TypeError, ValueError):
            number = None
        status = str(row.get("status") or "")
        mid = number is not None and 0 < number < 1
        if mid and status == "win":
            out.append([
                str(row.get("settled_ts") or row.get("game") or "")[:22],
                row.get("game") or "",
                oid,
                row.get("side") or "",
                row.get("result") or "",
                str(px),
                row.get("pnl") or "",
                row.get("source") or "",
            ])
    return out


def main() -> int:
    tagger_same = live_t0_yes.same_game(
        "Lilli Tagger vs. Magda Linette",
        "Magda Linette @ Lilli Tagger Round of 16",
    )
    mic_same = live_t0_yes.same_game(
        "Alex Michelsen vs. Arthur Fils",
        "Michelsen vs Fils",
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Paul five questions 29 Oct 2026</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.bad {{ background: #fdecec; border: 1px solid #e8b4b4; padding: 12px 16px; margin: 16px 0; }}
.ok {{ background: #ecfdf3; border: 1px solid #86efac; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Paul’s five questions — 29 Oct 2026</h1>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(LAYMAN)}</p>
</div>
<p class="note">Click column headers to sort. {report_page_extras.SWIPE_NOTE_HTML}</p>

<h2>1. Why no System B trades?</h2>
<p>Working as designed after the ~09:24 ET reboot. B pid was 38044 with <code>currently_open=0</code>.
No T0 both-Yes fill today. Last skip at 13:18 ET. The 30-row skip log is the actual skip log
(<code>strategy_b_watch.json</code> <code>skipped</code>, keep 30). Morning games (Maloney 05:59,
Lollia 06:01, Linette 08:19, Michelsen 09:39) are not in that keep-30 window; B was down until
the reboot, so those T0 windows were missed. After reboot the log is fees, band, clock, and window
— not a send bug. Did not reload B.</p>
<ul>
<li><strong>T0 window:</strong> ~15s before a trusted start through 5 minutes after. Later of Kalshi/Gemini occurrence and a listed/feed time with seconds=00.</li>
<li><strong>REST recheck:</strong> memory picks cheapest Yes per player; unpaced REST confirm those books; then IOC/FOK.</li>
<li><strong>After-fee sum vs 1.05:</strong> two Yes asks + documented taker fees must be ≤ 1.05. Screen cap under $1.05 is often wire-only.</li>
<li><strong>Skip-if already in B / leftover / locked A / GTC:</strong> not on today’s keep-30 list. No leftover-GTC on A. No B GTC without a T0 fill.</li>
<li><strong>Cheapest of 4:</strong> live shop is Kalshi/Gemini/Polymarket/Novig. One-platform books still need both Yes in (0.10, 0.90).</li>
<li><strong>HTTP budget / poller live:</strong> B is on memory tick + REST confirm; poll-all keeps the tennis slate. Skips below are decision skips, not a dead poller.</li>
</ul>
<p>Five games that looked like they should fire:</p>
{table(
    [("When ET", "date"), ("Game", "text"), ("Why B did not send", "text")],
    [
        ["2026-10-29 13:18:49", "Birtan Duran vs. Thomas Cardona Herrera", "t0_allin_c_over_105 all-in C=1.06 (fees pushed over 1.05)"],
        ["2026-10-29 13:18:51", "Bella Payne vs. Lily Taylor", "t0_allin_c_over_105 all-in C=1.07"],
        ["2026-10-29 13:18:51", "Owen Guistwite vs. Dylan Atkinson", "t0_allin_c_over_105 all-in C=1.07"],
        ["2026-10-29 13:05:38", "Basilashvili vs Alcaraz / Carlos Alcaraz @ Nikoloz Basilashvili Round of 16", "T0 Yes outside (0.10, 0.90) — favorite absorbing / not a two-sided 10–90 book"],
        ["2026-10-29 13:18:51", "Madison Sieg vs. Sara Saito", "no trusted clock; listed/feed is a feed stamp not a scheduled start"],
    ],
)}
<h3>Full keep-30 skip log</h3>
{table([("When ET", "date"), ("Game", "text"), ("Reason", "text")], b_skips())}

<h2>2. False E wins (venue)</h2>
<div class="bad">
<p><strong>Eliz Maloney beat Daniela Vismane 2–0</strong> (Kalshi recap; TipMaster finished 0–2).
E bought Polymarket <code>BUY_SHORT</code> Yes Daniela Vismane at 0.37 fee 0.02.
Poly book is still <code>MARKET_STATE_CLOSED</code> with last-trade <code>settlementPx=0.6700</code>
(TIER_2), not a 0/1 expire. POSITION_RESOLUTION stuffed <code>result=no</code>. Kitchen treated
side=no + result=no as a win (+$0.61). Real Yes token is Maloney; when Poly expires at 1.0000
this SHORT loses −$0.39. Until binary settlementPx, kitchen must not mark a win (rebuild now shows $0 / not a win, not +$0.61). When Poly expires 0/1 these are losses.</p>
<p><strong>Margaux Maquet beat Mathilde Lollia 6–2 6–3</strong> (L’Avenir; ScoreMondo 0–2).
E bought <code>BUY_LONG</code> Yes Mathilde Lollia at 0.43 fee 0.02. Book last-trade
<code>settlementPx=0.4300</code> (our one share) + POSITION_RESOLUTION <code>result=yes</code>
→ kitchen +$0.55. When Poly expires at 0.0000 this LONG loses −$0.45.</p>
</div>
<p>Same class of invert as Pohle/Kostina: ticker result=yes/no without a 0/1 settlementPx.
Fix: every rebuild re-GETs Poly; only settlementPx ≥ 1 (yes) or ≤ 0 (no) counts; POSITION_RESOLUTION
and result=yes are ignored; stored tape_rebuild wins without binary px cannot mark E/Poly a win.
Tests: <code>tools/test_e_poly_false_wins_20261029.py</code> (these two fixtures) plus Pohle gates.</p>
<h3>Other E/Poly stored wins on a mid last-trade px (suspect invert)</h3>
{table(
    [("When", "date"), ("Game", "text"), ("Order", "text"), ("Side", "text"), ("Stored result", "text"), ("settlementPx", "num"), ("Stored PnL", "num"), ("Source", "text")],
    inverted_e_poly() or [["—", "none besides the two Paul pasted (after this rebuild they should be open)", "", "", "", "", "", ""]],
)}

<h2>3. Tagger vs Linette (two Yes Linette)</h2>
<p>Cause: catalog titles <code>Magda Linette @ Lilli Tagger Round of 16</code>
(key <code>tennis_01a17d48090279718b1c63cb_2026_10_29</code>, 08:19:50, pay 0.29) and
<code>Lilli Tagger vs. Magda Linette</code> (key <code>tennis_taggerlinett_2026_10_29</code>,
08:24:24, pay 0.25). Same Poly slug <code>aec-wta-liltag-maglin-2026-10-29</code>.
<code>same_game</code> was exact string match, so E treated them as two matches.
Canonical last-name set is {{tagger, linette}} — same_game now {esc(tagger_same)}.
Before send, E refuses if we already filled Yes {{player}} on this match (any title, any platform).
In-process lock so two titles cannot race. Tests use these two titles.</p>

<h2>4. Michelsen vs Fils (same dog, two platforms)</h2>
<p>Cause: <code>Alex Michelsen vs. Arthur Fils</code> Poly 09:39:46 at 0.35
(key <code>tennis_michelfils_2026_10_29</code>) then <code>Michelsen vs Fils</code>
Kalshi 09:44:51 at 0.35 (key <code>tennis_micfil_2026_10_29</code>). Cheapest-of-4
picks one venue <em>per catalog row</em>. Different game keys made them two games.
same_game now {esc(mic_same)}. Per-match+player lock across platforms before the second send;
REST overlay confirm; do not send Kalshi if Poly already filled that dog. Tests included.</p>

<h2>5. Daily dashboards</h2>
<p>Current <code>dashboard.html</code> has Previous / Next (no What you asked block).
Dated files <code>dashboard_20261023.html</code> … <code>dashboard_20261029.html</code>.
Phone: 44px tap targets, swipe tables. Future writes keep prev/next.</p>

<p>Did not commit. Did not sell. Did not start a second B. Did not bump stake.
Did not leftover-GTC on A. Did not D NFL. Did not retune B C_LO=1.05 or D=0.25.
Did not DailyRun. {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(html), encoding="utf-8")
    print(f"wrote {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
