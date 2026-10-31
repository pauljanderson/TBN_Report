"""Paul 25 Oct 17:35: systems on / 0 open, Mesa tennis crossover, Missing order fields."""
from __future__ import annotations

import html as html_mod
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "b_zero_open_mesa_mccormick_20261025.html"
AUDIT = RAW / "_mesa_b_audit_20261025.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/b_zero_open_mesa_mccormick_20261025.html"
)

ASKED = (
    "it looks like all systems are on, can you confirm, but we have 0 open trades. "
    "any reason we didn't get in on this as a tennis crossover? Bernardo Munk Mesa vs. "
    "Tristan McCormick there seem to have been plenty of opportunities for tennis crossover, "
    "why aren't we taking any? why is this popping up on opportunities reason? Missing order fields."
)
PLAIN = (
    "All five research bots (A lock gap, B tennis crossover, C college-football favorite, "
    "D T0 spreads, E tennis T0 dog) are on, with one live process each. Open now is 0 because "
    "the sportsbooks are not showing live tickets, not because the bots are off. "
    "Mesa vs McCormick is tennis. Strategy B never filled a T0 both-Yes on it, so the later "
    "50-cross (dog through 50 cents) was illegal to take. At the first listed start (1:20 PM ET) "
    "Polymarket both-Yes all-in was exactly $1.05 (allowed); Kalshi was $1.0547 (too expensive); "
    "Novig fees are unknown so Novig is skipped. B pid 52768 was hitting a Windows file-lock "
    "error around that window, then we reloaded B at 2:05 PM for the local-cash change. "
    "After that the start time kept slipping (3:20, then 3:55). Re-looks were Novig fee-unknown "
    "or Kalshi a hair over $1.05. No T0 fill means no crossover extras. The “Missing order fields” "
    "line is lock A (Yes+No on two books), not B, and not the catalog scan. It hid which ticker/"
    "slug/intent was blank. The label now names those fields. We did not sell, did not start a "
    "second B, did not reload B (it is alive)."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    if not rows:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    if total:
        body.append(
            '<tr class="total-row">' + "".join(f"<td>{cell}</td>" for cell in total) + "</tr>"
        )
    return (
        f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def load_audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def main() -> None:
    audit = load_audit()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    systems = ((audit.get("systems") or {}).get("systems") or {})
    pids = audit.get("pids") or {}
    pos = audit.get("positions_cache") or {}
    kpos = audit.get("kalshi_positions") or {}
    ppos = audit.get("poly_positions") or {}
    b_watch = audit.get("b_watch") or {}
    b_counts = audit.get("b_counts") or {}
    mesa = audit.get("mesa") or {}
    miss = audit.get("missing_order_fields") or {}
    e = audit.get("e") or {}
    c = audit.get("c") or {}
    d = audit.get("d") or {}

    sys_rows = []
    letters = [
        ("A", "lock", "Lock gap", "51684", "supervisor + pollers"),
        ("B", "tennis_crossover", "Tennis crossover", "30908", "live_strategy_b.py"),
        ("C", "cfb_favorite", "College football favorite", "44956", "live_cfb_favorite.py"),
        ("D", "spread_t0", "T0 spreads (on except NFL)", "49784", "live_spread_t0.py"),
        ("E", "tennis_t0_dog", "Tennis T0 dog", "51492", "live_tennis_t0_dog.py"),
    ]
    letter_open = {"A": "0", "B": str(b_watch.get("currently_open") or 0), "C": str(c.get("currently_open") or 0), "D": str(d.get("currently_open") or 0), "E": str(e.get("currently_open") or 0)}
    last_action = {
        "A": "17:33 ET over cap after book recheck Denver vs Arizona net 1.0500 vs cap 0.99",
        "B": str(b_watch.get("last_skip_reason") or ""),
        "C": str(c.get("last_skip") or ""),
        "D": str(d.get("last_skip") or "") + " (D skips NFL while gathering T0 spread data)",
        "E": str(e.get("last_skip") or "ticking; no last skip"),
    }
    for letter, key, name, default_pid, proc in letters:
        cfg = systems.get(key) or {}
        live = pids.get({"A": "supervisor", "B": "b", "C": "c", "D": "d", "E": "e"}[letter]) or {}
        pid = live.get("pid") or default_pid
        alive = "alive" if live.get("alive") else "down"
        net = cfg.get("net_max") if key == "lock" else "—"
        sys_rows.append(
            [
                esc(letter),
                esc(name),
                esc("on" if cfg.get("on") else "off"),
                esc(cfg.get("stake_usd")),
                esc(cfg.get("size")),
                esc(cfg.get("max_open")),
                esc(net),
                esc(letter_open[letter]),
                esc(pid),
                esc(alive),
                esc(proc),
                esc(last_action[letter]),
            ]
        )

    pid_rows = [
        ["Lock supervisor", esc((pids.get("supervisor") or {}).get("pid")), esc((pids.get("supervisor") or {}).get("started_at")), "1 python live_game_pollers.py", "alive" if (pids.get("supervisor") or {}).get("alive") else "down"],
        ["Catalog scan", "30972", "2026-10-25T14:03:34-04:00", "1 python overnight_scan.py", "alive"],
        ["B Tennis crossover", esc((pids.get("b") or {}).get("pid")), esc((pids.get("b") or {}).get("started_at")), "1 python live_strategy_b.py (notepad also has the file open; that is not a second B)", "alive" if (pids.get("b") or {}).get("alive") else "down"],
        ["C CFB favorite", esc((pids.get("c") or {}).get("pid")), esc((pids.get("c") or {}).get("started_at")), "1 python live_cfb_favorite.py", "alive" if (pids.get("c") or {}).get("alive") else "down"],
        ["D T0 spreads", esc((pids.get("d") or {}).get("pid")), esc((pids.get("d") or {}).get("started_at")), "1 python live_spread_t0.py", "alive" if (pids.get("d") or {}).get("alive") else "down"],
        ["E Tennis T0 dog", esc((pids.get("e") or {}).get("pid")), esc((pids.get("e") or {}).get("started_at")), "1 python live_tennis_t0_dog.py", "alive" if (pids.get("e") or {}).get("alive") else "down"],
        ["Mesa Kalshi/Poly/Novig poller", "19008", "2026-10-25T14:03:40-04:00", "1 python --poll-one tennis_munmcc_2026_10_25", "alive"],
        ["Mesa Gemini-style listing poller", "38896", "2026-10-25T15:54:08-04:00", "1 python --poll-one Tristan McCormick @ Bernardo Munk Mesa", "alive"],
    ]

    skip_mid = b_counts.get("skip_midnight") or []
    skip_6 = b_counts.get("skip_6h") or []
    skip_fr = b_counts.get("skip_freeze") or []
    skip_rows = []
    for reason, n in skip_mid[:12]:
        n6 = next((c for r, c in skip_6 if r == reason), 0)
        nf = next((c for r, c in skip_fr if r == reason), 0)
        skip_rows.append([esc(reason), esc(n), esc(n6), esc(nf)])

    t0_rows = []
    for row in mesa.get("t0_skips") or []:
        t0_rows.append(
            [
                esc(row.get("at")),
                esc(row.get("game")),
                esc(row.get("venue") or "—"),
                esc(row.get("player_a") or "—"),
                esc(row.get("yes_a") or "—"),
                esc(row.get("player_b") or "—"),
                esc(row.get("yes_b") or "—"),
                esc(row.get("reason")),
            ]
        )

    lock_rows = []
    for row in mesa.get("lock") or []:
        lock_rows.append(
            [
                esc(row.get("at") or "—"),
                esc(row.get("event")),
                esc(row.get("venue") or "—"),
                esc(row.get("net") or "—"),
                esc(row.get("reason") or row.get("note") or "—"),
                esc(row.get("confirm_qty") or "—"),
            ]
        )

    miss_rows = []
    for row in miss.get("rows") or []:
        miss_rows.append(
            [
                esc(row.get("at")),
                esc(row.get("sport")),
                esc(row.get("game")),
                esc(row.get("market_type")),
                esc(row.get("side")),
                esc(f"{row.get('yes_venue')}/{row.get('no_venue')}"),
                esc(row.get("yes_price")),
                esc(row.get("no_price")),
                esc(row.get("net")),
                esc(row.get("source") or "live poller (blank)"),
                "Missing order fields. (old label)",
                "Missing order fields for a polymarket/novig pair: ticker, slug, intent, Novig market/outcome id, or Novig orders not live. Live poller send block, not the catalog scan.",
            ]
        )

    last_yes = []
    for row in mesa.get("last_yes") or []:
        game = str(row.get("game") or "").lower()
        if "munk mesa" not in game and "mccormick" not in game:
            continue
        last_yes.append(
            [
                esc(row.get("venue")),
                esc(row.get("side")),
                esc(row.get("price")),
                esc(row.get("seen_at")),
                esc(row.get("game")),
            ]
        )

    starts = mesa.get("game_starts") or []
    start_rows = [[esc(gs), esc(n)] for gs, n in starts]

    sends = b_counts.get("sends_today") or []
    send_rows = [
        [esc(r.get("at")), esc(r.get("event")), esc(r.get("game")), esc(r.get("venue"))]
        for r in sends
    ]

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>B zero open / Mesa vs McCormick — 25 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; margin: 0 0 0.4rem; }}
h2 {{ font-size: 1.15rem; margin: 1.3rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.note {{ color: #334155; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Zero open, Mesa vs McCormick, Missing order fields</h1>
<p class="note">Written {esc(now)}. Research-candidate live. Not gold. Not DailyRun.
Did not sell. Did not transfer money. Did not start a second <code>live_strategy_b.py</code>.
Did not reload B (pid 30908 is alive and on). Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout ok">
<h2>Short answers</h2>
<ul>
<li><strong>A–E are on.</strong> systems.json updated 13:58 ET: A on stake $1 max 3 net_max 0.99; B on stake $1 max 4; C on stake $1 max 4; D on stake $1 max 2; E on stake $1 max 2. One live python each. Catalog one. Mesa poller one.</li>
<li><strong>Open now is 0, Positions is 0, Kalshi GET is empty (HTTP 200).</strong> Gemini/Novig have no positions book. Polymarket last GET (16:58 ET, ~40 min older than Positions) still listed leftover slug Enzo Lima vs Bruno from a 0.09 unexpected FOK partial that B already cancelled; that is not a house 1-contract open and is not a dropped confirmed 1-fill on an OPEN lock. Ghost-open cap still counts unique games with venue-confirmed qty still unsettled.</li>
<li><strong>Mesa vs McCormick is tennis.</strong> B did not take the 50-cross because it never filled a legal T0 both-Yes. Hard skip <code>t0_allin_c_over_105</code> means no T0, no 50-cross, no dip. Extra-Yes-on-dip stays DISMISS.</li>
<li><strong>B is taking looks, not nothing.</strong> Since midnight: 1222 B tape rows, 33 sends, 1154 skips are all-in C over $1.05 or Novig fee unknown. Since the 14:05 local-cash reload: 326 looks, 2 sends (Bobichon, Del Pino), 324 <code>t0_allin_c_over_105</code>. Last B tape 17:34 ET (Paula Vargas, C=1.3). Not frozen like D at 12:53.</li>
<li><strong>“Missing order fields” is lock A, not B, not catalog.</strong> Four live-poller rows at 17:25 ET: Denver vs Arizona and Green Bay vs Detroit moneyline, Polymarket Yes + Novig No (and the flip). The bot could not build a send body for one leg. The old sentence hid which field. New sends name the field. Old rows on opportunities.html now say polymarket/novig ticker-slug-intent-or-Novig-not-live.</li>
</ul>
</div>

<h2>Systems A–E vs live pids</h2>
<p class="note">Read from raw/systems.json (not assumed). Open now is Positions/watch overlay, not a second counter. Hidden START / CREATE_NO_WINDOW is how these start; the python PIDs below are the live ones.</p>
{table(
    [("Sys", "text"), ("Name", "text"), ("On/off", "text"), ("Stake $", "num"), ("Size", "num"), ("Max open", "num"), ("lock.net_max", "num"), ("Open now", "num"), ("PID", "num"), ("Process", "text"), ("Binary", "text"), ("Last action", "text")],
    sys_rows,
)}

<h2>Live processes (one each)</h2>
{table(
    [("Role", "text"), ("PID", "num"), ("Started ET", "date"), ("Count", "text"), ("Alive", "text")],
    pid_rows,
)}

<div class="callout warn">
<h2>Venue truth for “0 open”</h2>
<p>Positions cache {esc(pos.get("pulled_at"))}: <strong>{esc((pos.get("footer") or pos).get("n") if isinstance(pos.get("footer"), dict) else pos.get("n"))} rows</strong>, warnings {esc(pos.get("warnings"))}.</p>
<p>Kalshi positions GET HTTP {esc(kpos.get("http"))} at {esc(kpos.get("pulled_at"))}: market_positions {esc(kpos.get("n_market"))}, event_positions {esc(kpos.get("n_event"))}. That is actually empty.</p>
<p>Polymarket US positions GET HTTP {esc(ppos.get("http"))} at {esc(ppos.get("pulled_at"))}: n={esc(ppos.get("n"))} slug(s) {esc(", ".join(ppos.get("slugs") or []) or "none")}. Empty Poly GET must not drop a confirmed fill while the market is OPEN. This leftover slug is the Enzo Lima 0.09 FOK partial (B log 13:28 ET <code>poly_fok_partial_unexpected cum=0.09</code>), not a 1-contract lock fill. B currently_open 0. We did not flatten or sell it.</p>
<p>B currently_open {esc(b_watch.get("currently_open"))} (watch updated {esc(b_watch.get("updated_at"))}). E currently_open {esc(e.get("currently_open"))}. C {esc(c.get("currently_open"))}. D {esc(d.get("currently_open"))}.</p>
</div>

<h2>Mesa vs McCormick autopsy</h2>
<p class="note">Tennis moneyline. Two listings: Kalshi/Poly/Novig <code>Munk Mesa vs McCormick</code> (poller tennis_munmcc pid 19008) and the Gemini-style <code>Tristan McCormick @ Bernardo Munk Mesa 1st Qualifying Round</code> (pid 38896). Listed start slipped on the tape (seconds=00 clocks):</p>
{table([("Listed / tape game_start", "date"), ("Yes ticks using that clock", "num")], start_rows)}
<p class="note">Trusted T0 is a 5-minute window around occurrence when clocked, else listed start with seconds=00 plus grace. First listed start 13:20:00 ET. B pid 52768 had been up since 00:25 ET; local-cash reload started pid 30908 at 14:05:10 ET. Tennis pollers for this match spawned with the supervisor at 14:03:40 ET (after the 13:20 window). B does its own REST books; it does not need the lock poller to send, but the 13:20 window still needed B to be looping cleanly.</p>

<div class="callout warn">
<h2>T0 both-Yes at 13:15–13:25 ET (the first listed start)</h2>
<p>Yes in (0.10, 0.90): yes. Favorite from T0 Yes asks: Bernardo Munk Mesa ~0.55, dog Tristan McCormick ~0.47. All-in C (asks + documented taker fees), house formula:</p>
<ul>
<li><strong>Kalshi</strong> 0.55 + 0.47 + 0.0173 + 0.0174 = <strong>1.0547</strong> → over 1.05 → skip <code>t0_allin_c_over_105</code>.</li>
<li><strong>Polymarket</strong> 0.55 + 0.46 + 0.02 + 0.02 = <strong>1.05</strong> exactly → allowed (≤ 1.05). pick_t0_book prefers a legal book closest to $1, so Poly should have been the T0 venue.</li>
<li><strong>Novig</strong> 0.545 + 0.46, fee schedule missing → all-in unknown → skip. B is allowed to send Novig when orders are live, but unknown fee is a hard skip, not a $0 fee.</li>
</ul>
<p>B tape has <strong>no Mesa T0 row between 11:54 and 14:18</strong>. Around 13:20 pid 52768 logged Enzo Lima work and <code>strategy b loop PermissionError</code> at 13:24, then a stack of PermissionError from 13:41–13:58, then the 14:05 reload. That is why the Poly-legal T0 did not send. It is not “system off”, not MAX_OPEN (open 0 / max 4), not E-already-on-match (E has no Mesa row), not Poly ask size &lt; qty at that print, not FOK miss on Mesa.</p>
</div>

<h2>B T0 skip tape for Mesa (exact ET)</h2>
<p class="note">From orders.jsonl event=t0 system=tennis_crossover. Zero cross events for this match. Zero B sends for this match.</p>
{table(
    [("Time ET", "date"), ("Game", "text"), ("Venue", "text"), ("Player A", "text"), ("Yes A", "num"), ("Player B", "text"), ("Yes B", "num"), ("Skip reason", "text")],
    t0_rows,
)}

<div class="callout">
<h2>Why the later “plenty of crossover” prints were not B</h2>
<p>After a legal T0, B may buy the T0-dog extra only when that dog Yes goes from below 0.50 through 0.50, the T0 favorite’s current Yes is strictly below the dog Yes we would pay, and all-in C ≤ 1.05. Live D=0.25 is the post-cross lock profit target, not a 25¢ dip. Extra-Yes-on-dip is DISMISS.</p>
<p>McCormick Yes did print 0.50 at 16:50:50 ET on Kalshi websocket (lock poller claim). That looks like a 50-cross. B still would not buy it: there was never a confirmed T0 both-Yes fill, and the 16:24 Kalshi all-in C=1.0536 / Novig fee-unknown skips are hard <code>t0_allin_c_over_105</code> (no T0, no 50-cross, no dip).</p>
<p>What <em>did</em> fire at 16:50 is <strong>lock A</strong> (Yes+No on two books), not tennis crossover:</p>
</div>
{table(
    [("Time ET", "date"), ("Event", "text"), ("Venue", "text"), ("Net", "text"), ("Note", "text"), ("Confirm qty", "num")],
    lock_rows,
)}
<p class="note">Lock A sequential hard-first: Polymarket HTTP 200 confirm qty 0 (activities GET empty) → hard_miss_abort, did not send the easy Kalshi leg. Six minutes later the other Mesa lock looked net 0.93 then REST recheck net 1.0300 vs cap 0.99. Those rows are on opportunities.html. They are not B setups. Catalog never sends.</p>

<h2>Last Yes asks (when this page was gathered)</h2>
{table(
    [("Venue", "text"), ("Side", "text"), ("Yes", "num"), ("Seen ET", "date"), ("Game", "text")],
    last_yes,
)}
<p class="note">Mesa ~6¢ / McCormick ~95¢. That is absorbed, not a T0 band. Too late for B even if we wanted a retro send. We did not send.</p>

<h2>Why B is taking none right now (but did take some today)</h2>
<p class="note">B pid 30908 updated strategy_b_watch.json at {esc(b_watch.get("updated_at"))}. Last skip: {esc(b_watch.get("last_skip_reason"))}. Last tape {esc((b_counts.get("last_b") or {}).get("at"))} {esc((b_counts.get("last_b") or {}).get("game"))} {esc((b_counts.get("last_b") or {}).get("reason"))}. Progressing, not stuck in REST. Tennis pollers are spawning (105 live --poll-one, including Mesa). Hidden window is intended. The 14:05 reload did miss T0s whose 5-minute window had already passed; mid-slate start skips those on purpose.</p>
{table(
    [("Slice", "text"), ("B tape looks", "num"), ("Sends", "num"), ("Top skip", "text")],
    [
        ["Since midnight ET", esc(b_counts.get("looks_midnight")), esc(b_counts.get("sends_midnight")), "t0_allin_c_over_105 × 1154"],
        ["Last 6 hours", esc(b_counts.get("looks_6h")), esc(b_counts.get("sends_6h")), "t0_allin_c_over_105 × 407"],
        ["Since 14:05 local-cash reload", esc(b_counts.get("looks_freeze")), esc(b_counts.get("sends_freeze")), "t0_allin_c_over_105 × 324 (only skip in this slice)"],
    ],
)}
<h3>B skip reasons since midnight</h3>
{table(
    [("Reason (prefix)", "text"), ("Since midnight", "num"), ("Last 6h", "num"), ("Since 14:05", "num")],
    skip_rows,
    total=["Top reasons are all-in C over 1.05 / Novig fee unknown, then Poly ask size &lt; 1, then cross_fav_not_below_dog / cross_allin_c_over_105", "", "", ""],
)}
<h3>B sends today (tape action=send)</h3>
<p class="note">Those matches are now absorbed / postponed / abandoned / settled, so Open now is 0 even though B did trade this morning and early afternoon.</p>
{table(
    [("Time ET", "date"), ("Event", "text"), ("Game", "text"), ("Venue", "text")],
    send_rows,
)}

<h2>“Missing order fields” on opportunities</h2>
<p class="note">Exact old string in <code>tools/live_lock_orders.py</code> execute path: <code>_log_consider("denied", "Missing order fields.")</code> when <code>_leg_spec</code> returned None. That helper needs a venue, a Yes/No price in (0,1), and then Kalshi ticker / Gemini symbol / Polymarket slug+intent / Novig market+outcome id with Novig orders live. None of those is a catalog skip. Catalog rows say “This is the catalog scan; it never sends.” These four rows have a blank source, which is the live poller.</p>
{table(
    [("Time ET", "date"), ("Sport", "text"), ("Game", "text"), ("Market", "text"), ("Side", "text"), ("Venues", "text"), ("Yes", "num"), ("No", "num"), ("After-fee", "num"), ("Source", "text"), ("Old reason", "text"), ("New label", "text")],
    miss_rows,
)}
<p class="note">This is a <strong>real send block</strong> on lock A, not a display-only bug. After-fee cost was under 0.99 (0.97401 and 0.93712), so they belong on the page. The bug was the sentence: it hid whether Novig orders were off, or a Poly intent/slug was blank, or a Novig outcome id was blank. New denies name the missing field. opportunities.html rewrite of the four old rows names the polymarket/novig pair. Did not revert hard-first, flatten-first, Poly FOK, D NFL skip, E, skip-absorbed-B, leftover deadline removed, local cash hourly, lock.net_max 0.99, ghost open cap, or unrounded after-fee ≥4 decimals.</p>

<h2>What we did not do</h2>
<ul>
<li>Did not reload B. One B pid 30908. systems.json was not clobbered off.</li>
<li>Did not sell, flatten, or transfer money.</li>
<li>Did not treat Mesa lock-A hard-miss as a B crossover miss.</li>
<li>Did not retune the 1.05 all-in cap. Research live only.</li>
</ul>
<p class="note">Sources: raw/systems.json, job_status.html, strategy_b_watch.json, strategy_b.log, strategy_b.pid, orders.jsonl, considerations.json, tennis.jsonl 25 Oct, live_health tennis_munmcc, kalshi_positions_pull.json, polymarket_positions_pull.json, job_status_positions_cache.json, tools/live_strategy_b.py, tools/live_lock_orders.py. {esc(FILE_URL)}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    html_out = page
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(html_out, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)


if __name__ == "__main__":
    main()
