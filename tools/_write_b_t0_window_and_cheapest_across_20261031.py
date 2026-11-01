"""B T0 watch window from live tape + cheapest Yes per player across shops.

Display only. Does not sell. Does not start a second B. HOLD C_HI=1.05 and D=0.25.
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

import live_strategy_b  # noqa: E402
import live_t0_yes  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    inject_report_page_extras,
)
from write_orders_performance import table  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = STAMP / "b_t0_window_and_cheapest_across_20261031.html"
DATA = STAMP / "b_t0_window_and_cheapest_across_20261031.json"

PAUL = (
    "it looks like system B tries to lock in both sides for about 5 minutes. "
    "can we try longer? can you look at past data to see if prices stabilize after a certain point? "
    "also, is it always looking on the same platform to lock in both sides? System B should always "
    "we looking on all platforms the game is on and look for the cheapest price for each of the types of bets."
)

BUCKET_ORDER = [
    "at T0 (0)",
    "0–1 min",
    "1–2 min",
    "2–5 min",
    "5–10 min",
    "10–15 min",
    "15–20 min",
    "20–30 min",
    "30–45 min",
    "45–60 min",
    "60–90 min",
    "never",
]


def esc(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def b_pid() -> str:
    path = RAW / "strategy_b.pid"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "?"
    return str(data.get("pid") or "?")


def _norm_bucket(text: str) -> str:
    out = []
    for ch in str(text).lower():
        out.append(ch if ch.isalnum() else " ")
    return " ".join("".join(out).split())


def hist_table(hist: dict, n: int) -> str:
    rows = []
    used = set()
    for bucket in BUCKET_ORDER:
        count = 0
        want = _norm_bucket(bucket)
        for key, value in (hist or {}).items():
            if _norm_bucket(key) == want:
                count = int(value)
                used.add(key)
                break
        share = f"{(100.0 * count / n):.1f}%" if n else ""
        rows.append([bucket, count, share])
    for key, value in (hist or {}).items():
        if key in used:
            continue
        count = int(value)
        share = f"{(100.0 * count / n):.1f}%" if n else ""
        rows.append([key, count, share])
    return table(
        [("Minutes from listed T0", "text"), ("Matches", "num"), ("Share of usable", "num")],
        rows,
    )


def pct_row(label: str, bag: dict) -> list:
    if not bag:
        return [label, "", "", "", "", "", "", ""]
    return [
        label,
        bag.get("n", ""),
        bag.get("p25", ""),
        bag.get("p50", ""),
        bag.get("p75", ""),
        bag.get("p90", ""),
        bag.get("p95", ""),
        bag.get("max", ""),
    ]


def match_rows(rows: list[dict]) -> str:
    body = []
    for row in rows:
        first = row.get("first_hit_min")
        if first is None:
            continue
        if float(first) <= 5:
            continue
        body.append(
            [
                row.get("game") or "",
                (row.get("t0") or "")[:19].replace("T", " "),
                row.get("c_at_t0") or "",
                first,
                row.get("stay_min") if row.get("stay_min") is not None else "never back-stable",
                row.get("venues_at_t0") or "",
                "same shop" if row.get("same_shop_at_t0") else "two shops",
                "yes" if row.get("pre_t0_during") else "",
            ]
        )
    body.sort(key=lambda r: float(r[3]))
    return table(
        [
            ("Match", "text"),
            ("Listed T0 ET", "date"),
            ("C at/after T0", "num"),
            ("First <=1.05 (min)", "num"),
            ("Stays <=1.05 (min)", "text"),
            ("Cheapest shops then", "text"),
            ("Same shop?", "text"),
            ("Tape already in-play before listed", "text"),
        ],
        body,
    )


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    n_usable = int(data.get("n_usable") or 0)
    n_hit = int(data.get("n_hit_105") or 0)
    rec = data.get("recommend") or {}
    pct_first = data.get("pct_first") or {}
    pct_stay = data.get("pct_stay") or {}
    pod = data.get("podoroska") or {}
    cheap = pod.get("cheapest_pair") or {}
    same = pod.get("same_shop_c") or {}
    pid = b_pid()
    grace = int(live_strategy_b.T0_GRACE_SEC)
    grace_min = live_strategy_b.t0_grace_minutes()
    hist_first = hist_table(data.get("hist_first") or {}, n_usable)
    hist_stay = hist_table(data.get("hist_stay") or {}, n_usable)
    pct_tbl = table(
        [
            ("Curve", "text"),
            ("N", "num"),
            ("p25", "num"),
            ("p50", "num"),
            ("p75", "num"),
            ("p90", "num"),
            ("p95", "num"),
            ("max", "num"),
        ],
        [pct_row("First drop to after-fee C <= 1.05 (minutes)", pct_first),
         pct_row("Then stays <= 1.05 (never back above; minutes)", pct_stay)],
    )
    knobs = table(
        [("Knob", "text"), ("Was", "text"), ("Now", "text"), ("Held?", "text")],
        [
            ["B T0 both-Yes watch (T0_GRACE_SEC)", "300 s (5 min)", f"{grace} s ({grace_min} min)", "window only"],
            ["T0 lead", "15 s before trusted start", "15 s (unchanged)", "yes"],
            ["C_HI (all-in both-Yes)", "1.05", str(live_strategy_b.C_HI), "HOLD"],
            ["D (25c lock profit on extra pair)", "0.25", str(live_strategy_b.D), "HOLD"],
            ["E/F/G T0 grace (live_t0_yes)", "300 s", f"{live_t0_yes.T0_GRACE_SEC} s", "not B"],
            ["Tennis poller spawn", "5 min before listed", "5 min (unchanged)", "not the send window"],
        ],
    )
    verdict = table(
        [("Question", "text"), ("Answer", "text")],
        [
            ["Current B T0 watch", f"{grace_min} minutes after trusted start (~15 s before through T0_GRACE). Was 5 minutes."],
            ["When does cheapest both-Yes after-fee first hit <= 1.05?",
             f"Live tennis Yes-ask tape 21–31 Oct 2026. Usable matches with two Yes in band: {n_usable}. "
             f"Hit <=1.05 inside 90 min: {n_hit}. Median first hit {pct_first.get('p50')} min "
             f"(already at T0 for half). p75 {pct_first.get('p75')} min. p90 {pct_first.get('p90')} min. "
             f"{data.get('n_first_after_5')} first drop after 5 min."],
            ["When does it stay there?",
             f"C often comes back above 1.05. Stay-median {pct_stay.get('p50')} min among "
             f"{pct_stay.get('n')} that eventually stop crossing back. Not a 5-minute settle."],
            ["New window",
             f"{grace_min} minutes. From the first-hit p90 (~{pct_first.get('p90')} min) and "
             f"{data.get('n_first_after_5')} matches whose first sendable print is after 5 min. "
             f"C still <=1.05 near +15 and +30 min on {data.get('n_still_le_15')}/{n_usable}. "
             "HOLD 1.05 / 0.25. Not an OOS shop of C or D."],
            ["Cheapest across all shops?",
             "Picker was already min Yes-ask per player across Kalshi / Polymarket US / Gemini / Novig "
             "(omit a shop with no ticker). Mixed shops allowed. Bug: T0 REST used only the 1–2 memory "
             "winner shops, so a live Novig listing could skip without seeing a cheaper Poly/Kalshi leg. "
             "Fixed: T0 now REST-reads every sendable shop with a ticker, then pick_cheapest_legs."],
            ["Podoroska 20:00 both-Novig",
             "Not cheapest-each-on-Novig. Tape at 20:00:40: Poly Podoroska 0.49 + Poly Monnet 0.52 "
             "(C=1.05) beat both-Novig REST 0.490+0.585 (C=1.10456 skip). Stale Novig memory 0.51/0.495 "
             "was also mixed-cheaper with Poly 0.49. Same-shop-only REST is why B taped Novig 1.10456."],
            ["B pid (still one)", pid],
        ],
    )
    code = table(
        [("Function", "text"), ("What it does", "text")],
        [
            ["pick_cheapest_legs / rank_cheapest_legs",
             "Min raw Yes ask per player across Kalshi, Polymarket, Gemini, Novig. Sum after-fee. "
             "Same shop only if that shop is cheapest for both."],
            ["_prepare_book",
             "Was REST-only memory winners. Now moneyline_yes_books(scan, spec) with no venue filter."],
            ["t0_ready",
             f"~15 s before trusted start through {grace} s after. Missed T0 window after that. "
             "Clock bug (listed 18:10 vs play 17:30) is not this send window."],
        ],
    )
    pod_tbl = table(
        [("Shop / pair at or before 20:00:40", "text"), ("Podoroska Yes", "num"), ("Monnet Yes", "num"), ("After-fee C", "num"), ("Cheapest each?", "text")],
        [
            ["Polymarket both (20:00:21)", "0.4900", "0.5200", (same.get("polymarket") or {}).get("c") or "1.0500", "No — Monnet cheaper on stale Novig"],
            ["Novig both (last tape 19:59:35)", "0.5100", "0.4950", (same.get("novig") or {}).get("c"), "No — Podoroska cheaper on Poly 0.49"],
            ["Cheapest-each on tape (Poly + Novig)",
             (cheap.get("a") or {}).get("pay"),
             (cheap.get("b") or {}).get("pay"),
             cheap.get("c"),
             "Yes — two shops"],
            ["B skip tape 20:00:40 (Novig REST)", "0.490", "0.585", "1.10456", "No — memory/REST Novig-only"],
        ],
    )
    tail = match_rows(data.get("matches") or [])
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>B T0 window and cheapest across shops — 31 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
code {{ font-size: 13px; }}
pre {{ white-space: pre-wrap; background: #f8fafc; border: 1px solid #e2e8f0; padding: 8px 10px; font-size: 13px; }}
ul {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>B T0 both-Yes: longer watch, cheapest each shop</h1>
<p class="note">America/New_York. Written {esc(now)}. Stamp <code>prediction_market_arb_exhaustive_20261017</code>.
Did not commit. One B pid {esc(pid)}. Did not leftover-GTC A.
Did not retune C_HI=1.05 or D=0.25. Did not sell TEN/CIN. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<pre>{esc(PAUL)}</pre>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>System B buys <strong>both tennis winners Yes</strong> right around first serve.
It had only about <strong>five minutes</strong> after that start to get both tickets.
We looked at the live Yes-ask tape (not Kalshi’s start-only history) to see when the
two cheapest tickets plus fees first add up to <strong>$1.05 or less</strong>, and
when that pair stops bouncing back over $1.05.</p>
<p>Half the matches are already there at first serve. About one in five only get
there after five minutes. Prices do not “settle” in five minutes — they often
cross back over $1.05. So B now watches for <strong>{esc(grace_min)} minutes</strong>.
The $1.05 cap and the 25-cent extra-pair rule did not change.</p>
<p>B was already allowed to put each player on a different shop. A T0 shortcut
was only refreshing the shop that looked cheapest in memory, so it could miss a
cheaper ticket on another platform. That shortcut is gone. “Types of bets” here
is the two moneyline Yes tickets, not spreads (that is system F).</p>
</div>

<div class="callout ok">
<h2>What changed</h2>
<ul>
<li><strong>Watch:</strong> 5 minutes → {esc(grace_min)} minutes after trusted start. Lead still ~15 seconds before.</li>
<li><strong>Shops:</strong> T0 now reads every platform the match is on (Kalshi, Polymarket US, Gemini, Novig if it has a ticker), then cheapest Yes per player.</li>
<li><strong>Held:</strong> C_HI=1.05, D=0.25. Poller still spawns 5 minutes before listed start. E/F/G still 5-minute T0. Listed 18:10 vs play 17:30 is a clock bug, not this window.</li>
<li><strong>B pid:</strong> {esc(pid)} (one process).</li>
</ul>
</div>

<h2>Answers</h2>
{verdict}

<h2>Knobs</h2>
{knobs}

<h2>First time cheapest both-Yes after-fee is &le; 1.05</h2>
<p class="note">Live <code>price_memory</code> tennis Yes asks, 21–31 Oct 2026. Trusted clock here is listed
<code>game_start</code> with seconds=00. Kalshi historical files are T0-only, so they cannot show in-play
stabilize. After-fee uses the same house taker formulas B uses (Novig 0.06 in-play). Click headers to sort.</p>
{pct_tbl}
{hist_first}

<h2>Until it stays &le; 1.05 (does not go back above)</h2>
<p class="note">If the pair keeps crossing $1.05, “stay” is later than first hit. That is why a longer
watch helps even when the first print is already good: B can retry while C is back under the cap.
HOLD the cap, so a late print over 1.05 still does not send.</p>
{hist_stay}

<h2>Code</h2>
{code}
<pre>def rank_cheapest_legs(books):
    # Min Yes ask per player across venues. Cross-platform pair allowed.
    ...
    # not both legs on one shop unless that shop is cheapest for both

def _prepare_book(scan, spec):
    books = moneyline_yes_books(scan, spec)  # all sendable shops with a ticker
    ranked = rank_cheapest_legs(books)</pre>

<h2>Podoroska vs Monnet 20:00:40 ET 30 Oct</h2>
<p>B skipped both-Novig at C=1.10456. That was <strong>not</strong> “Novig was cheapest for each
player.” Poly already had Podoroska at 0.49 and Monnet at 0.52 (all-in 1.05). The skip path had
REST’d Novig only. Game start on this tape is listed 18:10 — the 17:30 first serve is a clock
bug, separate from the 5-minute send window.</p>
{pod_tbl}

<h2>Matches whose first &le;1.05 is after 5 minutes</h2>
<p class="note">These are the matches a 5-minute watch never sees as sendable. Doubles and
qualifiers are included (still moneyline both-Yes). Swipe sideways to see more columns.</p>
{tail}

<p class="note">Sources: live tennis <code>price_memory/*/tennis.jsonl</code>, orders.jsonl event=t0,
<code>tools/live_strategy_b.py</code> T0_GRACE_SEC / pick_cheapest_legs / _prepare_book,
<code>tools/live_t0_yes.py</code> (E/F/G grace unchanged),
<code>tools/live_game_pollers.py</code> TENNIS_PRE_START_MIN=5.
Did not start a second <code>live_strategy_b.py</code>. No secrets.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(OUT)
    print("pid", pid)
    print("grace", grace)


if __name__ == "__main__":
    main()
