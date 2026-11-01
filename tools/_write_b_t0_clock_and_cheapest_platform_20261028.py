"""Parks vs Birrell early T0 clock + cheapest-platform shop. Research only.

Does not sell. Does not un-buy Parks/Birrell. Does not start a second B.
Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP, RAW_DIR as RAW, ensure_dirs  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = DRIVE_STAMP / "b_t0_clock_and_cheapest_platform_20261028.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/b_t0_clock_and_cheapest_platform_20261028.html"
)
ASKED = (
    "Tennis T0 (game-start both-Yes) sometimes fires hours early. Example: "
    "Parks vs Birrell on Kalshi already bought; game still 5h 44m away "
    "(~15:49 ET 2026-10-28). We should wait until just before game time "
    "(existing intent: ~15s before trusted start through T0_GRACE). Diagnose "
    "this fill: when sent, what clock was used, why it was “near T0.” Fix so "
    "tomorrow’s/hours-away matches cannot T0. Pollers may spawn 5 min before "
    "for data; sends stay just-before-start. Do not un-buy Parks/Birrell. "
    "System B: shop all platforms that list the game (Kalshi, Gemini, "
    "Polymarket, Novig) and buy each side on the cheapest book. Example: "
    "Birrell 0.61 Kalshi vs 0.60 Poly → buy Birrell Poly 0.60; opponent 0.40 "
    "Poly vs 0.39 Kalshi → buy opponent Kalshi 0.39. Same for 50-cross "
    "(cheapest T0-dog Yes) and the GTC dip (cheapest original-favorite Yes at "
    "fav_target). Cross-platform pair is allowed. All-in C≤1.05 HOLD still on "
    "the sum of the two chosen after-fee asks. 1 contract per leg. REST recheck "
    "inline on the chosen books immediately before send (not a 3-min slate walk). "
    "Do not REST-hunt the world. Use live poller/price_memory quotes to pick min "
    "ask per player, then unpaced REST confirm those 1–2 books, then IOC/FOK "
    "(T0+cross) or GTC (dip). If memory stale, one confirm is enough."
)
PLAIN = (
    "The bot bought both sides of Parks vs Birrell at 12:32 AM because Kalshi’s "
    "“occurrence” clock said 12:30 AM. The real match time on the listing "
    "(Polymarket game start / listed 9:30 PM ET) was still hours away, and the "
    "market period was not started. We now wait until about 15 seconds before "
    "that later clock, then keep a five-minute grace after it. Helpers can still "
    "wake five minutes early just to watch prices. They cannot send. Separately, "
    "when it is time to buy, B looks at every shop that lists the match and takes "
    "the cheaper Yes for each player — even if that means Parks on Kalshi and "
    "Birrell on Polymarket. We still refuse the pair if those two after-fee prices "
    "add up to more than $1.05. We do not sell the Parks/Birrell tickets we "
    "already have."
)


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers, rows) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = []
        for (_, kind), val in zip(headers, row):
            extra = ' class="num"' if kind == "num" else ""
            cells.append(f"<td{extra}>{esc(val)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _parks_match() -> dict:
    watch = _load(RAW / "strategy_b_watch.json") or {}
    for row in watch.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if "parks" in str(row.get("game") or "").lower() and "birrell" in str(row.get("game") or "").lower():
            return row
    return {}


def _b_pid() -> str:
    pid = _load(RAW / "strategy_b.pid") or {}
    if isinstance(pid, dict) and pid.get("pid"):
        return str(pid.get("pid"))
    return "—"


def cheapest_figure() -> str:
    return """<svg viewBox="0 0 980 280" role="img" aria-label="Cheapest Yes per player then confirm the winners">
  <rect x="8" y="8" width="964" height="264" fill="#f8fafc" stroke="#d8dee9"/>
  <text x="24" y="36" font-family="system-ui,sans-serif" font-size="16" font-weight="600">How cheapest pick works</text>
  <text x="24" y="58" font-family="system-ui,sans-serif" font-size="12" fill="#475569">Memory / live poller quotes. No four-venue REST hunt.</text>
  <rect x="24" y="80" width="200" height="72" fill="#fff" stroke="#94a3b8"/>
  <text x="34" y="104" font-family="system-ui,sans-serif" font-size="13">Birrell Yes</text>
  <text x="34" y="124" font-family="system-ui,sans-serif" font-size="12">Kalshi 0.61</text>
  <text x="34" y="142" font-family="system-ui,sans-serif" font-size="12" fill="#166534">Poly 0.60 ← buy</text>
  <rect x="248" y="80" width="200" height="72" fill="#fff" stroke="#94a3b8"/>
  <text x="258" y="104" font-family="system-ui,sans-serif" font-size="13">Parks Yes</text>
  <text x="258" y="124" font-family="system-ui,sans-serif" font-size="12">Poly 0.40</text>
  <text x="258" y="142" font-family="system-ui,sans-serif" font-size="12" fill="#166534">Kalshi 0.39 ← buy</text>
  <path d="M448 116 H 500" stroke="#334155" stroke-width="2"/>
  <polygon points="500,110 512,116 500,122" fill="#334155"/>
  <rect x="520" y="80" width="220" height="72" fill="#eef6ff" stroke="#64748b"/>
  <text x="530" y="104" font-family="system-ui,sans-serif" font-size="13">Sum the two chosen</text>
  <text x="530" y="124" font-family="system-ui,sans-serif" font-size="12">asks + documented fees</text>
  <text x="530" y="142" font-family="system-ui,sans-serif" font-size="12">C ≤ 1.05 HOLD else skip</text>
  <path d="M740 116 H 792" stroke="#334155" stroke-width="2"/>
  <polygon points="792,110 804,116 792,122" fill="#334155"/>
  <rect x="812" y="80" width="144" height="72" fill="#ecfdf3" stroke="#166534"/>
  <text x="822" y="108" font-family="system-ui,sans-serif" font-size="13">REST confirm</text>
  <text x="822" y="128" font-family="system-ui,sans-serif" font-size="12">those 1–2 books</text>
  <text x="822" y="146" font-family="system-ui,sans-serif" font-size="12">then IOC/FOK/GTC</text>
  <text x="24" y="184" font-family="system-ui,sans-serif" font-size="12" fill="#334155">Same-platform 0.61+0.40 is worse. Cross-platform 0.60+0.39 is the send pair. One contract per leg.</text>
  <text x="24" y="208" font-family="system-ui,sans-serif" font-size="12" fill="#334155">50-cross: cheapest T0-dog Yes. Dip GTC: cheapest original-favorite Yes at fav_target. Memory stale → one confirm of the winners, not a world hunt.</text>
  <text x="24" y="244" font-family="system-ui,sans-serif" font-size="12" fill="#475569">This is faster than walking Kalshi then Gemini then Poly then Novig on every tick, because only the winning 1–2 books are confirmed.</text>
</svg>"""


def main(extra: dict | None = None) -> Path:
    ensure_dirs()
    extra = extra or {}
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    parks = _parks_match()
    t0 = parks.get("t0_yes") or {}
    a = t0.get("a") or {}
    b = t0.get("b") or {}
    last = parks.get("last_order") or {}
    tape = table(
        [
            ("Field", "text"),
            ("Value", "text"),
            ("What it means", "text"),
        ],
        [
            ["Game", parks.get("game") or "Parks vs Birrell", "Do not un-buy. Stage left as-is."],
            ["Key / ticker date", f"{parks.get('key') or 'tennis_parbir_2026_10_27'} / KXWTAMATCH-26OCT27PARBIR", "Kalshi event is 26OCT27. Listed first serve is 28 Oct 21:30 ET."],
            ["Opened waiting_t0", parks.get("opened_at") or "2026-10-28T00:16:35.786-04:00", "near-window used occurrence 00:30 (14 min ahead), not listed 21:30."],
            ["t0_label", parks.get("t0_label") or "mixed pre-start + first in-game (occurrence)", "Research label from assign_actual_t0. Send clock was occurrence."],
            ["Clock used at send", parks.get("t0_when") or parks.get("occurrence") or "2026-10-28T00:30:00-04:00", "Kalshi occurrence 00:30 ET. That is why it was “near T0.”"],
            ["Listed / Poly game start", parks.get("listed_start") or "2026-10-28T21:30:00-04:00", "Scheduled seconds=00. Still hours away at send. Period NS (not started)."],
            ["Sent", last.get("time") or "2026-10-28T00:32:46-04:00", "Both Yes IOC on Kalshi ~2 minutes after the false 00:30 clock."],
            ["Parks Yes", f"{a.get('fill_px') or a.get('price') or '0.4'} {a.get('venue') or 'kalshi'} {a.get('instrument') or '…-PAR'}", "1 contract. Holding."],
            ["Birrell Yes", f"{b.get('fill_px') or b.get('price') or '0.61'} {b.get('venue') or 'kalshi'} {b.get('instrument') or '…-BIR'}", "1 contract. Holding. Same-venue pair; cheapest-shop was not wired yet."],
            ["All-in C", "1.0435", "Under 1.05 HOLD, so the send itself was legal on cost. The clock was wrong."],
            ["Stage now", parks.get("stage") or "waiting_cross", "Waiting T0-dog through 0.50. Did not sell."],
        ],
    )
    window = table(
        [
            ("Slice", "text"),
            ("Before", "text"),
            ("After", "text"),
        ],
        [
            [
                "Trusted send clock",
                "Kalshi/Gemini occurrence wins even if a scheduled listed start is hours later.",
                "Later of occurrence and scheduled listed (seconds=00). Too-early occurrence cannot beat a still-future listed first-serve.",
            ],
            [
                "T0 send window",
                "15s before that clock through T0_GRACE=300s after.",
                "Same 15s / 300s window, but on the later clock. Named T0_LEAD_SEC=15. Shared with E via live_t0_yes.choose_trusted_t0_clock.",
            ],
            [
                "Parks vs Birrell at 00:32 ET",
                "In window (occurrence 00:30). Sent both Yes.",
                "Waiting (listed 21:30). Would not T0. Would not even occupy waiting_t0 (not within 15 minutes of the later clock).",
            ],
            [
                "Parks vs Birrell at 21:29:50 ET",
                "Missed T0 window vs the 00:30 occurrence (grace ended 00:35).",
                "In window vs listed 21:30. Can send if C≤1.05.",
            ],
            [
                "Poller spawn",
                "Live-window 5 min before trusted/listed start (just landed). Not reverted.",
                "Unchanged. Data helpers may be up 5 min early. Sends stay just-before-start.",
            ],
            [
                "Miyoshi (listed ~2 min ahead, two-sided already moving)",
                "Hide in-play → no trusted clock.",
                "Unchanged near listed. Hours-away listed is not treated as in-play just because the pre-market wiggled.",
            ],
            [
                "E tennis T0 dog 11–49 band",
                "Same occurrence-first clock if it reached consider_game.",
                "Shared later-clock helper. Band not retuned. E slate still 15 min before listed, so Parks at 00:16 was already off E’s slate.",
            ],
        ],
    )
    tests = table(
        [
            ("Test", "text"),
            ("Result", "text"),
        ],
        [
            ["Hours-away listed + early occurrence does not T0", "pass"],
            ["Within 15s of later listed does T0; 20s before does not", "pass"],
            ["Cheapest picker: Poly 0.60 + Kalshi 0.39 over same-platform 0.61+0.40", "pass"],
            ["50-cross uses cheapest dog platform", "pass"],
            ["Dip GTC rests on cheapest fav platform", "pass"],
            ["No double-send (existing Shimizu + Hsu GTC tests)", "pass"],
            ["E choose_trusted_t0_clock waits for later listed", "pass"],
        ],
    )
    wired = table(
        [
            ("Path", "text"),
            ("Cheapest-platform wired", "text"),
            ("REST", "text"),
        ],
        [
            ["T0 both-Yes", "Y — pick_cheapest_legs across Kalshi/Gemini/Polymarket/Novig", "Memory picks 1–2 venues; unpaced REST confirm those books; then IOC/FOK"],
            ["50-cross", "Y — cheapest T0-dog Yes", "Memory first; REST only the winning dog (+ fav for C) inline"],
            ["GTC dip", "Y — cheapest original-favorite Yes at fav_target", "REST that book; rest GTC (or IOC if already at target). No double-send if already resting"],
        ],
    )
    b_pid = extra.get("b_pid") or _b_pid()
    e_note = extra.get("e_note") or "shared clock in live_t0_yes; E reloaded only if this job did so"
    facts = table(
        [
            ("Fact", "text"),
            ("Value", "text"),
        ],
        [
            ["Live B pid (one)", b_pid],
            ["Cheapest-platform T0/cross/dip", "Y / Y / Y"],
            ["T0 send window now", "~15s before later(occurrence, scheduled listed) through T0_GRACE=300s"],
            ["D / C / E band", "D=0.25, C=1.05 HOLD, E 11–49 not retuned"],
            ["Parks/Birrell tickets", "left in place; not sold"],
            ["Poller 5-min spawn / venue-fill cash", "not reverted"],
            ["E", e_note],
            ["Gold / DailyRun", "no"],
        ],
    )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>B T0 clock and cheapest platform — 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; padding: 0 0 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
td.num {{ text-align: right; }}
svg {{ width: 100%; height: auto; margin: 12px 0; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>B T0 clock and cheapest platform</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now)}. Research only. Not gold. Not DailyRun. Did not retune D=0.25, C=1.05, D NFL, leftover GTC on A, stake, or E’s 11–49 band.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="warn">
<p><strong>Why Parks/Birrell fired early.</strong> Sent 00:32:46 ET 28 Oct on Kalshi (Parks Yes 0.40, Birrell Yes 0.61, all-in C=1.0435). The send clock was Kalshi <code>occurrence</code> <strong>00:30 ET</strong>. Listed / Polymarket game start was <strong>21:30 ET</strong> the same day, period NS. Occurrence won because live T0 preferred it over listed. 00:32 is inside 15s-before through T0_GRACE of 00:30, so the bot called it “near T0.” It was not first serve.</p>
</div>

<h2>Parks vs Birrell tape</h2>
<p>Click column headers to sort. Holdings stay.</p>
{SWIPE_NOTE_HTML}
{tape}

<h2>T0 send window before / after</h2>
{SWIPE_NOTE_HTML}
{window}

<h2>How cheapest pick works</h2>
{cheapest_figure()}
{SWIPE_NOTE_HTML}
{wired}

<h2>Tests</h2>
{SWIPE_NOTE_HTML}
{tests}

<h2>Live</h2>
{SWIPE_NOTE_HTML}
{facts}

<p class="note">Code: <code>tools/live_strategy_b.py</code>, <code>tools/live_t0_yes.py</code> <code>choose_trusted_t0_clock</code>. Poller live-window 5-min spawn in <code>live_game_pollers</code> left alone. Venue-fill house cash / settlementPx left alone. {esc(FILE_URL)}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html_out, encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = main()
    print(path)
