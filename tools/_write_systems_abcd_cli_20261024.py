"""Systems A–D CLI + C/D live freeze HTML. Research-candidate live. Not gold.

Does not commit. Does not print secrets. Does not start a second live_strategy_b.py.
Does not sell tickets. Does not wire GTC.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers  # noqa: E402
import prediction_systems as ps  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "systems_abcd_cli_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/systems_abcd_cli_20261024.html"
)
DAYS = ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24")

ASKED = (
    "Add systems and an easy on/off + sizing CLI. A Lock gap (existing live lock bot). "
    "B Strategy B display name Tennis crossover (keep live_strategy_b.py). "
    "C College football favorite: best Yes ask for the T0 favorite across all venues, "
    "buy if under 90¢ — baseline arm t0_fav_lt_90 restricted to college football moneyline "
    "(as long as that is T0 favorite Yes < 0.90). "
    "D T0 spreads: buy any spread at trusted T0 whose favorite Yes is >50¢ and <90¢ "
    "(the baseline row he quoted: T0 favorite Yes < 0.90 on spreads, N=72, WR 95.8%, "
    "+$16.93, mean +$0.24). He thought there would be a lot more spreads — audit logging "
    "and turn spread collection on if pollers/catalog were moneyline-only. "
    "CLI to turn each system on or off, set stake per game (default $1), set max open "
    "at the same time per system (default 2). Easy to see what's on."
)
PLAIN = (
    "Five live bots, each with an on/off switch, a dollar cap per game, and a cap on how "
    "many games can be open at once. Lock gap still buys Yes on one site and No on another "
    "when the pair is cheap enough. Tennis crossover is the old Strategy B with a clearer name. "
    "College football favorite buys the team the market likes at kickoff on the who-wins market, "
    "only when that ticket costs more than 50 cents and less than 90 cents, at the cheapest venue. "
    "T0 spreads does the same for one point-spread line per game. "
    "Tennis T0 dog buys the cheaper tennis player at match start and holds to the result; it stays "
    "off until you paste the CLI. $1 is about one contract at these prices. Research live, not gold, not DailyRun."
)


def esc(value) -> str:
    import html as html_mod

    return html_mod.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def html_table(headers: list[tuple[str, str]], rows: list[list[str]], *, total: bool = False) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for i, row in enumerate(rows):
        klass = ' class="total-row"' if total and i == len(rows) - 1 else ""
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr{klass}>{cells}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f"<table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def catalog_ticker_counts() -> dict:
    counts = {
        "cfb_games": 0,
        "cfb_ml": 0,
        "cfb_spread": 0,
        "cfb_total": 0,
        "cfb_ml_missing_kalshi": 0,
        "other_games": 0,
        "other_spread": 0,
    }
    path = RAW / "cfb_game_list.json"
    if path.exists():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
        for game in blob.get("matched") or []:
            counts["cfb_games"] += 1
            if game.get("kalshi_game_ticker") or game.get("gemini_moneyline_ticker"):
                counts["cfb_ml"] += 1
            if game.get("kalshi_spread_ticker") or game.get("gemini_spread_ticker"):
                counts["cfb_spread"] += 1
            if game.get("kalshi_total_ticker") or game.get("gemini_total_ticker"):
                counts["cfb_total"] += 1
            if not game.get("kalshi_game_ticker") and game.get("kalshi_spread_ticker"):
                counts["cfb_ml_missing_kalshi"] += 1
    sports_path = RAW / "sports_queue.json"
    if sports_path.exists():
        try:
            blob = json.loads(sports_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
        for sport in blob.get("sports") or []:
            for game in sport.get("matched") or []:
                counts["other_games"] += 1
                kalshi = game.get("kalshi") or {}
                gem = game.get("gemini") or {}
                if kalshi.get("spread") or gem.get("spread") or game.get("kalshi_spread_ticker") or game.get("gemini_spread_ticker"):
                    counts["other_spread"] += 1
    return counts


def tape_kind_counts() -> dict:
    by_sport: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    series: dict[str, set] = defaultdict(set)
    n_lines = 0
    for day in DAYS:
        folder = RAW / "price_memory" / day
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.jsonl")):
            sport = path.stem
            try:
                handle = path.open("r", encoding="utf-8")
            except OSError:
                continue
            with handle:
                for line in handle:
                    n_lines += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = str(row.get("market_type") or "moneyline") or "moneyline"
                    by_sport[sport][kind] += 1
                    by_day[day][kind] += 1
                    series[kind].add(
                        (
                            sport,
                            str(row.get("game") or ""),
                            kind,
                            str(row.get("number") or ""),
                            str(row.get("venue") or ""),
                        )
                    )
    return {
        "n_lines": n_lines,
        "by_sport": {k: dict(v) for k, v in by_sport.items()},
        "by_day": {k: dict(v) for k, v in by_day.items()},
        "n_series": {k: len(v) for k, v in series.items()},
    }


def sibling_example() -> list[str]:
    k, g = live_game_pollers.expand_sibling_tickers(
        ["KXNCAAFGAME-26OCT24LSUAUB"],
        ["NCAAF-2610241930-LSU-AUB-M"],
        "college football",
    )
    return [f"Kalshi {', '.join(k)}", f"Gemini {', '.join(g)}"]


def write_page() -> Path:
    cat = catalog_ticker_counts()
    tape = tape_kind_counts()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    sport_rows = []
    totals = {"moneyline": 0, "spread": 0, "total": 0}
    for sport, kinds in sorted((tape.get("by_sport") or {}).items()):
        sport_rows.append([
            esc(sport),
            str(kinds.get("moneyline") or 0),
            str(kinds.get("spread") or 0),
            str(kinds.get("total") or 0),
        ])
        for k in totals:
            totals[k] += int(kinds.get(k) or 0)
    sport_rows.append(["Total ticks", str(totals["moneyline"]), str(totals["spread"]), str(totals["total"])])
    series = tape.get("n_series") or {}
    freeze_rows = [
        ["C universe", "College football moneyline only, two-sided, trusted T0"],
        ["C favorite", "Primary higher Yes; if venues disagree, team with Yes>50 and higher median; skip 50-50"],
        ["C send", "One IOC on cheapest Yes ask in (0.50, 0.90); REST recheck; hold to settlement"],
        ["D universe", "Any sport with spread markets (CFB, NFL, …). Totals out."],
        ["D pick", "One qualifying two-sided spread per game, closest to 50¢. --d-all-lines off."],
        ["D send", "Same band (0.50, 0.90), best venue for that line/side, one shot at T0"],
        ["Size", "Whole contracts. Default size=1 and stake-usd=$1. $1 ≈ 1 contract at these prices."],
        ["Max open", "Lock gap stays 3 until Paul sets it. New systems default 2. C/D/E = open games."],
        ["NET_MAX 0.984", "Lock only. Default stays 0.984 until Paul sets --lock-net-max. C, D, and E are directional; no 0.984 gate."],
        ["Latch", "One-leg miss still stops new lock pairs only. B/C/D/E ignore orders_stopped.json."],
        ["E Tennis T0 dog", "Off until Paul runs CLI. Tennis ML unique lower T0 Yes in (0.10, 0.50). Skip if B has the match. Hold to settle."],
        ["Promotion", "Research-candidate live. Not gold. Not DailyRun."],
    ]
    cli_rows = [
        ["See what's on", "python tools/prediction_job_control.py systems"],
        ["Or double-click", "run_prediction_systems.bat"],
        ["Lock on, max 3, $1", "python tools/prediction_job_control.py systems --lock on --lock-max 3 --lock-stake 1"],
        ["Lock send cap (NET_MAX)", "python tools/prediction_job_control.py systems --lock-net-max 0.984"],
        ["Lock send cap alias", "python tools/prediction_job_control.py systems --lock-gap 0.99"],
        ["Tennis crossover off", "python tools/prediction_job_control.py systems --tennis-crossover off"],
        ["CFB favorite on", "python tools/prediction_job_control.py systems --cfb-favorite on --cfb-favorite-max 2 --cfb-favorite-stake 1"],
        ["T0 spreads on", "python tools/prediction_job_control.py systems --spread-t0 on --spread-t0-max 2 --spread-t0-stake 1"],
        ["Tennis T0 dog on", "python tools/prediction_job_control.py systems --tennis-t0-dog on --tennis-t0-dog-max 2 --tennis-t0-dog-stake 1"],
        ["Tennis T0 dog off", "python tools/prediction_job_control.py systems --e off"],
        ["Letter aliases", "--a / --b / --c / --d / --e"],
    ]
    cat_rows = [
        ["CFB matched games", str(cat.get("cfb_games") or 0)],
        ["CFB with a moneyline ticker", str(cat.get("cfb_ml") or 0)],
        ["CFB with a spread ticker", str(cat.get("cfb_spread") or 0)],
        ["CFB with a totals ticker", str(cat.get("cfb_total") or 0)],
        ["CFB rows with Kalshi spread but no Kalshi GAME ticker", str(cat.get("cfb_ml_missing_kalshi") or 0)],
        ["Other-sport matched games", str(cat.get("other_games") or 0)],
        ["Other-sport with a spread ticker", str(cat.get("other_spread") or 0)],
        ["Tape ticks Oct 17–24", str(tape.get("n_lines") or 0)],
        ["Tape series moneyline", str(series.get("moneyline") or 0)],
        ["Tape series spread", str(series.get("spread") or 0)],
        ["Tape series total", str(series.get("total") or 0)],
    ]
    examples = sibling_example()
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Systems A–E CLI — 24 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
pre {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px 12px; overflow: auto; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Systems A–E — on/off + sizing CLI</h1>
<p class="banner"><strong>Research-candidate live. Not gold. Not DailyRun.</strong> Written {esc(now)}.
Did not start a second <code>live_strategy_b.py</code>. Did not sell tickets. Did not wire GTC.
Lock leftover / flatten / skip-absorbed B stay. Skip lock also covers an open C or D ticket on the same event.
Supervisor sleep stays 60s. Hidden spawn is <code>win_hidden</code> CREATE_NO_WINDOW.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<p class="note">job_status <strong>Open now</strong> is how many are open right now (a count). The cap is the <strong>Max</strong> column (Lock gap 3), not mashed into Open as 0/3.</p>
<p class="note">Live ops panel: <a href="job_status.html">job_status.html</a>.
System E freeze: <a href="system_e_t0_dog_20261025.html">system_e_t0_dog_20261025.html</a>.
Lock sequential hard-first: <a href="lock_hard_leg_first_20261024.html">lock_hard_leg_first_20261024.html</a>.
Field guide: <a href="strategies_layman.html">strategies_layman.html</a>.
Baseline: <a href="t0_fav_lt90_baseline_20261024/compare.html">t0_fav_lt90_baseline_20261024/compare.html</a>.
Config (this PC only): <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/systems.json</code>.</p>

<h2>CLI cheat sheet</h2>
<p class="note">Click column headers to sort. Writing config reloads only that process: start if on and dead, stop if off, leave a live Tennis crossover pid in place (config re-read, never a second B).
<code>--lock on --lock-max 3 --lock-stake 1</code> does not change the 0.984 send cap.
Set it with <code>python tools/prediction_job_control.py systems --lock-net-max 0.984</code>
(alias <code>--lock-gap</code>). Lock pollers reread <code>systems.json</code> each tick like D max; no lock restart.</p>
{html_table([("Action", "text"), ("Command", "text")], [[esc(a), "<code>"+esc(b)+"</code>"] for a, b in cli_rows])}
<pre>python tools/prediction_job_control.py systems
python tools/prediction_job_control.py systems --lock on --lock-max 3 --lock-stake 1
python tools/prediction_job_control.py systems --lock-net-max 0.984
python tools/prediction_job_control.py systems --lock-gap 0.99
python tools/prediction_job_control.py systems --tennis-crossover off
python tools/prediction_job_control.py systems --cfb-favorite on --cfb-favorite-max 2 --cfb-favorite-stake 1
python tools/prediction_job_control.py systems --spread-t0 on --spread-t0-max 2 --spread-t0-stake 1
python tools/prediction_job_control.py systems --tennis-t0-dog on --tennis-t0-dog-max 2 --tennis-t0-dog-stake 1
python tools/prediction_job_control.py systems --e off</pre>

<h2>Freeze</h2>
{html_table([("Knob", "text"), ("Rule", "text")], [[esc(a), esc(b)] for a, b in freeze_rows])}

<h2>Why N=72 spreads felt small</h2>
<p>The catalog was <strong>not</strong> moneyline-only. College football matched rows often already list
<code>kalshi_spread_ticker</code> and <code>kalshi_total_ticker</code>. Pollers already fetched those event
tickers when the catalog filled them. Tennis is moneyline-only on purpose (MATCH books, no spread sibling).</p>
<p>What <em>was</em> thin: many CFB rows have a Kalshi <strong>spread</strong> ticker and a Gemini <strong>moneyline</strong>
ticker, but a null Kalshi GAME ticker and a null Gemini spread ticker. Polymarket/Novig spreads only attach when
Kalshi or Gemini already listed that number. The T0-favorite &lt;90¢ baseline then keeps only settled two-sided
unique-favorite books with documented fees — so N=72 is a research grain, not “how many spread series existed.”</p>
<p>This job turns sibling collection <strong>on</strong> for tracked non-tennis games: if we have
<code>…GAME…</code> / <code>-M</code>, we also request <code>…SPREAD…</code> / <code>-S</code> (and totals) without
dropping moneyline. Coverage is logged to <code>spread_coverage.jsonl</code> and on each poller state file.</p>
<p class="tiny">Sibling example after the patch: {esc(examples[0])}. {esc(examples[1])}.</p>
{html_table([("Coverage", "text"), ("N", "num")], [[esc(a), esc(b)] for a, b in cat_rows])}
<p class="note">Click column headers to sort. Tape ticks Oct 17–24 by sport and market type (change-ticks, not unique games).</p>
{html_table(
    [("Sport", "text"), ("Moneyline ticks", "num"), ("Spread ticks", "num"), ("Total ticks", "num")],
    sport_rows,
    total=True,
)}

<h2>Live files</h2>
<ul>
<li><code>tools/prediction_systems.py</code> — CLI, systems.json, gates</li>
<li><code>tools/live_cfb_favorite.py</code> / <code>tools/live_spread_t0.py</code> / <code>tools/live_tennis_t0_dog.py</code> / <code>tools/live_t0_yes.py</code></li>
<li><code>tools/live_strategy_b.py</code> — still the Tennis crossover module</li>
<li><code>run_prediction_systems.bat</code> — double-click status</li>
</ul>
<p class="tiny">Generator: <code>tools/_write_systems_abcd_cli_20261024.py</code>. Tests: <code>tools/test_prediction_systems.py</code>. Bookmark <code>{esc(FILE_URL)}</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


if __name__ == "__main__":
    path = write_page()
    print(path)
    print("config", ps.CONFIG_PATH)
