"""System F tennis spread T0 backtest: combined hist + live tape, labeled separately.

Does not place, cancel, or sell. Does not print secrets. Does not start F live.
Does not start a second live_strategy_b.py. Does not leftover-GTC A.
Does not DailyRun-wire. Does not retune B D=0.25 / C / D / E knobs.
Does not rewrite dashboard.html.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras  # noqa: E402
import t0_all_games_stats as t0  # noqa: E402
import prediction_job_control  # noqa: E402
import prediction_systems as systems  # noqa: E402
from compare_format import format_money  # noqa: E402
from nfl_t0_type_a_collect import line_won  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP, RAW_DIR as RAW  # noqa: E402
from t0_fav_lt90_baseline_20261024 import (  # noqa: E402
    COMPARE_HEADERS,
    fmt_ann,
    quality,
    quality_row,
)
from write_t0_band_from_stay_above import documented_leg_fee  # noqa: E402
import _write_kalshi_poly_combined_t0_decile_20261030 as comb  # noqa: E402
import _write_sport_league_t0_decile_20261027 as decile_w  # noqa: E402
from price_memory import iter_tick_lines, load_last_sport  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "system_f_tennis_spread_20261030.html"
JSON_OUT = STAMP / "system_f_tennis_spread_20261030.json"
RECS = STAMP / "combined_t0_decile_system_recs_20261030.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_f_tennis_spread_20261030.html"
)
CLI = (
    "python tools/prediction_job_control.py systems "
    "--tennis-t0-spread on --tennis-t0-spread-max 2 --tennis-t0-spread-stake 1"
)
IS_CUT = "2024-01-01"
VENUE_RANK = {"kalshi": 0, "gemini": 1, "polymarket": 2, "novig": 3}
ASKED = (
    "OK. wire me up 1 new system F Tennis spreads tennis buy the cheapest spread "
    "in the 20-49 range. wire this up and run a historical backtest using the "
    "combined poly+klashi data AND a separete one for the tape we have downloaded "
    "and collected. and show me the expected results and then give me the command "
    "line to set it up like this python tools/prediction_job_control.py systems "
    "--tennis-t0-dog on --tennis-t0-dog-max 2 --tennis-t0-dog-stake 1"
)
PLAIN = (
    "We built a sixth live helper, F, that only bets tennis spreads — a point or "
    "set line such as “Player A wins by 1.5 sets,” not moneyline (who wins the "
    "match) and not Points Total (over/under on games). At listed start it buys "
    "one $1 contract on the cheapest Yes in 20–49 cents (20 included, 50 skipped). "
    "If Tennis crossover (B) already has that match, F sits out. It does not pair "
    "both sides and leftover-watch must not hedge it. Two history books, not mixed: "
    "the combined Kalshi+Polymarket finished-game tape (cheaper after-fee when both "
    "shops listed the same named Yes; else the one shop; Kalshi T0 is the Yes ask, "
    "Polymarket T0 on this hist is a last trade), and the live kitchen tape we "
    "collected in October 2026 (Yes asks from price_memory / price_last_games). "
    "This hist starts about April 2025, so there is no pre-2024 in-sample. Paul "
    "chose 20–49; 10–49 is a sensitivity row only. F is wired and off until you "
    "run the command below."
)


def esc(text) -> str:
    return html_mod.escape(str(text or ""), quote=True)


def avg_s(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(float(value)):.4f}"


def match_key(row: dict) -> tuple:
    sport = str(row.get("sport") or "").strip().lower()
    date = str(row.get("_date") or row.get("entry_date") or "")[:10]
    ids = "|".join(sorted(str(x) for x in (row.get("_game_ids") or []) if x))
    if not ids:
        ids = str(row.get("game_n") or row.get("game") or "")
        ids = ids.rsplit("|", 1)[0] if ids.count("|") >= 4 else ids
    return (sport, date, ids)


def in_band(px, *, lo: float, hi: float) -> bool:
    try:
        p = float(px)
    except (TypeError, ValueError):
        return False
    return lo - 1e-12 <= p < hi - 1e-12


def pick_match_cheapest(rows: list[dict], *, lo: float, hi: float) -> dict | None:
    """One cheapest tennis spread Yes per match in [lo, hi). After-fee cash first."""
    cands = []
    for row in rows or []:
        if str(row.get("kind") or "").lower() != "spread":
            continue
        if str(row.get("sport") or "").strip().lower() != "tennis":
            continue
        px = row.get("t0_fav")
        if px is None:
            px = row.get("t0_a")
        if not in_band(px, lo=lo, hi=hi):
            continue
        cash = row.get("_cash")
        if cash is None:
            fee = documented_leg_fee(str(row.get("venue") or ""), px)
            if fee is None:
                continue
            cash = float(Decimal(str(px)) + Decimal(str(fee)))
        venue = str(row.get("venue") or "").strip().lower()
        rank = VENUE_RANK.get(venue, 9)
        cands.append((float(cash), float(px), rank, venue, str(row.get("number") or ""), row))
    if not cands:
        return None
    cands.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
    return cands[0][5]


def book_from_sides(sides: list[dict], *, lo: float, hi: float) -> list[dict]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for row in sides or []:
        if str(row.get("sport") or "").strip().lower() != "tennis":
            continue
        if str(row.get("kind") or "").lower() != "spread":
            continue
        bags[match_key(row)].append(row)
    out = []
    for group in bags.values():
        picked = pick_match_cheapest(group, lo=lo, hi=hi)
        if picked is not None:
            out.append(picked)
    return out


def score_book(sides: list[dict], *, arm: str) -> dict:
    trades = []
    n_won = 0
    n_known = 0
    for row in sides:
        won = line_won(row)
        if won is None and row.get("fav_won") is not None:
            won = bool(row.get("fav_won"))
        if won is True:
            n_won += 1
        if won is not None:
            n_known += 1
        copy = dict(row)
        if copy.get("t0_fav") is None and copy.get("t0_a") is not None:
            copy["t0_fav"] = copy.get("t0_a")
        if won is not None:
            copy["fav_won"] = bool(won)
        trade = decile_w.yes_trade(copy)
        if trade is not None:
            trades.append(trade)
    q = quality(trades, arm_id=arm, label=arm, grain="one cheapest spread per match") if trades else {}
    n = len(sides)
    pnl = q.get("pnl_sum") if trades else None
    avg = (pnl / len(trades)) if trades and pnl is not None else None
    wr = (100.0 * n_won / n_known) if n_known else None
    dates = [str(t.get("entry_date") or "") for t in trades if t.get("entry_date")]
    return {
        "arm": arm,
        "n": n,
        "n_settled_fee": len(trades),
        "n_won": n_won,
        "n_known": n_known,
        "wr": wr,
        "pnl": None if pnl is None else round(float(pnl), 4),
        "avg": None if avg is None else round(float(avg), 6),
        "quality": q,
        "first": min(dates) if dates else "",
        "last": max(dates) if dates else "",
        "n_is": int(q.get("n_is") or 0),
        "n_oos": int(q.get("n_oos") or 0),
        "ann_note": q.get("ann_note") or "",
        "is_note": "n/a — no IS (all T0 ≥ 2024-01-01; this tape starts Apr 2025)",
    }


def last_at_or_before(ticks: list[tuple[int, float]], clock_ts: int) -> tuple[int, float] | None:
    hit = None
    for ts, px in ticks or []:
        if ts <= clock_ts:
            hit = (ts, px)
        else:
            break
    return hit


def first_after(ticks: list[tuple[int, float]], clock_ts: int) -> tuple[int, float] | None:
    for ts, px in ticks or []:
        if ts >= clock_ts:
            return (ts, px)
    return None


def t0_px(ticks: list[tuple[int, float]], clock_ts: int | None) -> tuple[int, float] | None:
    if not ticks:
        return None
    if clock_ts is None:
        return ticks[0]
    pre = last_at_or_before(ticks, clock_ts)
    if pre:
        return pre
    return first_after(ticks, clock_ts)


def settle_from_ticks(ticks: list[tuple[int, float]]) -> bool | None:
    if not ticks:
        return None
    last = ticks[-1][1]
    if last >= 0.95:
        return True
    if last <= 0.05:
        return False
    return None


def game_norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def stream_live_tennis_spreads() -> tuple[dict, dict]:
    """Oct 2026 kitchen tennis spread Yes ticks. Not mixed with hist last-trade."""
    sides: dict[tuple, dict] = {}
    n_lines = 0
    n_yes = 0
    seen_min = ""
    seen_max = ""
    days = []
    hist_dir = RAW / "price_memory"
    if hist_dir.is_dir():
        days = sorted(
            p.name for p in hist_dir.iterdir()
            if p.is_dir() and p.name.startswith("2026-10")
        )
    if not days:
        days = [f"2026-10-{d:02d}" for d in range(1, 31)]
    for day in days:
        for line in iter_tick_lines(sport="tennis", day=day, include_archive=False):
            n_lines += 1
            if '"pay": "no"' in line or '"pay":"no"' in line:
                continue
            if "spread" not in line.lower():
                continue
            text = line.strip()
            if not text:
                continue
            try:
                rec = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if str(rec.get("pay") or "yes").lower() != "yes":
                continue
            if str(rec.get("sport") or "").strip().lower() != "tennis":
                continue
            kind = str(rec.get("market_type") or rec.get("kind") or "").strip().lower()
            if kind != "spread":
                continue
            venue_raw = str(rec.get("venue") or "").strip()
            if venue_raw not in t0.VENUES and venue_raw.lower() not in {v.lower() for v in t0.VENUES}:
                continue
            venue = venue_raw.lower()
            price = t0.as_float(rec.get("price"))
            if price is None or price <= 0.0 or price >= 1.0:
                continue
            seen = rec.get("seen_at") or ""
            ts = t0._ts(seen)
            if ts is None:
                continue
            game = rec.get("game") or ""
            number = str(rec.get("number") or "")
            side_key = str(rec.get("side_key") or rec.get("side") or "").strip().lower()
            if not game or not side_key:
                continue
            ident = ("tennis", game_norm(game), "spread", venue, number, side_key)
            st = sides.get(ident)
            if st is None:
                st = {
                    "sport": "tennis",
                    "game": game,
                    "kind": "spread",
                    "venue": venue,
                    "number": number,
                    "side": rec.get("side") or rec.get("side_label") or side_key,
                    "side_key": side_key,
                    "game_start": rec.get("game_start") or "",
                    "ticks": [],
                }
                sides[ident] = st
            else:
                if rec.get("game_start") and not st.get("game_start"):
                    st["game_start"] = rec.get("game_start") or ""
                if rec.get("game") and len(str(rec.get("game") or "")) > len(st.get("game") or ""):
                    st["game"] = rec.get("game") or st["game"]
            if st["ticks"] and st["ticks"][-1][0] == ts:
                st["ticks"][-1] = (ts, price)
            else:
                st["ticks"].append((ts, price))
            n_yes += 1
            if seen:
                if not seen_min or seen < seen_min:
                    seen_min = seen
                if not seen_max or seen > seen_max:
                    seen_max = seen
    n_overlay = 0
    try:
        last = load_last_sport("tennis")
    except Exception:
        last = {}
    if isinstance(last, dict):
        for rec in last.values():
            if not isinstance(rec, dict):
                continue
            if str(rec.get("sport") or "").strip().lower() != "tennis":
                continue
            kind = str(rec.get("market_type") or rec.get("kind") or "").strip().lower()
            if kind != "spread":
                continue
            if str(rec.get("pay") or "yes").lower() != "yes":
                continue
            venue = str(rec.get("venue") or "").strip().lower()
            if venue not in {v.lower() for v in t0.VENUES}:
                continue
            price = t0.as_float(rec.get("price"))
            ts = t0._ts(rec.get("seen_at") or "")
            game = rec.get("game") or ""
            number = str(rec.get("number") or "")
            side_key = str(rec.get("side_key") or rec.get("side") or "").strip().lower()
            if not game or not side_key or ts is None or price is None:
                continue
            ident = ("tennis", game_norm(game), "spread", venue, number, side_key)
            st = sides.get(ident)
            if st is None:
                continue
            if rec.get("game_start") and not st.get("game_start"):
                st["game_start"] = rec.get("game_start") or ""
            if not st["ticks"] or ts > st["ticks"][-1][0]:
                st["ticks"].append((ts, price))
                n_overlay += 1
    for st in sides.values():
        st["ticks"].sort(key=lambda row: row[0])
    return sides, {
        "n_lines": n_lines,
        "n_yes": n_yes,
        "n_sides": len(sides),
        "n_overlay": n_overlay,
        "seen_min": seen_min,
        "seen_max": seen_max,
        "days": days,
    }


def live_book(sides: dict, *, lo: float, hi: float) -> list[dict]:
    by_game: dict[str, list[dict]] = defaultdict(list)
    for st in sides.values():
        ticks = st.get("ticks") or []
        if not ticks:
            continue
        start = t0.parse_dt(st.get("game_start") or "") if hasattr(t0, "parse_dt") else None
        if start is None:
            start = t0.parse_time(str(st.get("game_start") or "")) if hasattr(t0, "parse_time") else None
        clock_ts = int(start.timestamp()) if start is not None else None
        hit = t0_px(ticks, clock_ts)
        if hit is None:
            continue
        ts, px = hit
        if not in_band(px, lo=lo, hi=hi):
            continue
        won = settle_from_ticks(ticks)
        by_game[game_norm(st.get("game") or "")].append({
            "sport": "tennis",
            "kind": "spread",
            "venue": st.get("venue") or "",
            "game": st.get("game") or "",
            "game_n": game_norm(st.get("game") or ""),
            "number": st.get("number") or "",
            "fav_name": st.get("side") or "",
            "t0_fav": px,
            "t0_a": px,
            "t0_ts": ts,
            "end_ts": ticks[-1][0],
            "fav_won": won,
            "entry_date": datetime.fromtimestamp(ts, ET).date().isoformat(),
            "_cash": None,
            "_game_ids": frozenset({game_norm(st.get("game") or "")}),
            "_date": datetime.fromtimestamp(ts, ET).date().isoformat(),
        })
    out = []
    for group in by_game.values():
        for row in group:
            fee = documented_leg_fee(str(row.get("venue") or ""), row["t0_fav"])
            if fee is None:
                continue
            row["_cash"] = float(Decimal(str(row["t0_fav"])) + Decimal(str(fee)))
        picked = pick_match_cheapest(group, lo=lo, hi=hi)
        if picked is not None and picked.get("fav_won") is not None:
            out.append(picked)
    return out


def f_running() -> list[int]:
    try:
        jobs = prediction_job_control.classify(prediction_job_control._ps_rows())
    except Exception:
        return []
    return [int(row["pid"]) for row in (jobs.get("tennis_t0_spread") or []) if row.get("pid")]


def quality_table(books: list[dict]) -> str:
    rows = []
    control = None
    for rec in books:
        q = rec.get("quality") or {}
        if not q:
            q = {
                "arm": rec.get("arm") or "",
                "grain": "one cheapest spread per match",
                "n": rec.get("n") or 0,
                "n_win": rec.get("n_won") or 0,
                "win_pct": rec.get("wr"),
                "pnl_sum": rec.get("pnl"),
                "mean": rec.get("avg"),
                "n_is": rec.get("n_is") or 0,
                "n_oos": rec.get("n_oos") or 0,
                "ann_note": rec.get("ann_note") or "",
                "is_note": rec.get("is_note") or "",
            }
        if control is None:
            control = q
            rows.append(quality_row(q, None))
        else:
            rows.append(quality_row(q, control))
    return t0.table(COMPARE_HEADERS, rows)


def summary_rows(books: list[dict]) -> list[list[str]]:
    rows = []
    for rec in books:
        q = rec.get("quality") or {}
        ann_full = rec.get("ann_note") or (q.get("ann_note") if q else "") or fmt_ann(q.get("ann_ror") if q else None)
        ann_is = rec.get("is_note") or (q.get("is_note") if q else "") or "n/a — no IS"
        ann_oos = rec.get("ann_note") or (q.get("ann_note") if q else "") or fmt_ann(q.get("ann_ror_oos") if q else None)
        rows.append([
            rec.get("arm") or "",
            rec.get("label") or "",
            rec.get("band") or "",
            str(rec.get("n") or 0),
            str(rec.get("n_settled_fee") or 0),
            str(rec.get("n_won") or 0),
            f"{rec['wr']:.1f}" if rec.get("wr") is not None else "—",
            format_money(rec.get("pnl")) if rec.get("pnl") is not None else "—",
            avg_s(rec.get("avg")),
            esc(ann_full),
            esc(ann_is),
            esc(ann_oos),
            str(rec.get("n_is") or 0),
            str(rec.get("n_oos") or 0),
            rec.get("first") or "—",
            rec.get("last") or "—",
            rec.get("note") or "",
        ])
    return rows


def write_html(payload: dict, now: str) -> Path:
    hist20 = payload["hist_20_49"]
    hist10 = payload["hist_10_49"]
    tape20 = payload["tape_20_49"]
    tape10 = payload["tape_10_49"]
    pids = payload.get("f_pids") or []
    running = "NOT running" if not pids else f"RUNNING pids {pids} (unexpected)"
    live_meta = payload.get("live_meta") or {}
    headers = [
        ("Book", "text"),
        ("Identity", "text"),
        ("Band", "text"),
        ("N matches", "num"),
        ("N with-fee", "num"),
        ("Wins", "num"),
        ("Win%", "num"),
        ("With-fee P&L", "num"),
        ("Avg with-fee P&L", "num"),
        ("Ann ROR full", "text"),
        ("Ann ROR IS", "text"),
        ("Ann ROR OOS", "text"),
        ("N IS", "num"),
        ("N OOS", "num"),
        ("First T0", "date"),
        ("Last T0", "date"),
        ("Note", "text"),
    ]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>F Tennis spread — combined hist vs live tape (30 Oct)</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.callout.cli {{ border-color: #86efac; background: #f0fdf4; }}
code.cli {{ display: block; white-space: pre-wrap; font-size: 0.95rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>F Tennis spread — cheapest T0 Yes in 20–49¢</h1>
<p class="note">Written {esc(now)}. Wired in code, left off. F is <strong>{esc(running)}</strong>.
Did not start F. Did not start a second B. Did not leftover-GTC A. Did not retune B/C/D/E.
Click column headers to sort. Swipe sideways to see more columns.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout cli">
<h2>Command to turn F on (Paul runs this)</h2>
<p class="note">Copy as one line. Does not start a second B. Stake $1, max open 2.</p>
<code class="cli">{esc(CLI)}</code>
</div>

<p class="note">A <strong>spread</strong> is a point or set line (wins-by-n). <strong>Moneyline (ML)</strong>
is who wins the match. F buys spreads only. E still buys tennis moneyline dogs. D buys
favorite-to-cover spreads on other sports (skipping the National Football League). F does
not require the pair to cost ≤ $1.05 and does not use sequential hard-first.</p>

<h2>Expected results (two books, not mixed)</h2>
<p class="note">Live kitchen tape N=0 tennis spreads: {esc(live_meta.get('n_lines') or 0)} tennis Yes-ask
lines on Oct 21–30 2026 <code>price_memory</code> shards plus <code>price_last_games/tennis</code>
are moneyline only (who wins the match). No spread (wins-by-n) prints were collected on that tape,
so the live book cannot be scored yet. Combined hist is the expected-result book for F.</p>
<p class="note">Freeze is <code>0.20 &lt;= px &lt; 0.50</code> (20–49 inclusive cents). 10–49 is a
sensitivity row only — Paul chose 20–49; the green cell on the combined cheaper-Yes page
was 10–49. One cheapest spread Yes per match, 1 contract, hold to settle, with-fee average
P&amp;L. Combined hist identity matches
<a href="kalshi_poly_combined_t0_decile_20261030.html">kalshi_poly_combined_t0_decile_20261030</a>:
same game keep cheaper after-fee; else the one shop. Kalshi T0 = Yes-ask. Polymarket T0 on
that hist = last-trade (labeled). Live tape is the kitchen Yes-ask collection for October 2026
(<code>price_memory</code> / <code>price_last_games</code>), labeled separately. In-sample
versus 2024-01-01 is empty because this book starts ~April 2025. Do not retune the band from
out-of-sample. Annualized rate of return uses the house formula
<code>compare_format.ann_ror_from_closed</code>; tennis same-day holds omit it rather than overflow.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(headers, summary_rows([hist20, hist10, tape20, tape10]))}

<h2>Canonical quality (full metric set)</h2>
<p class="note">Same columns as other T0 experiment compares. Deltas on later rows are versus
the first row (combined hist 20–49 freeze). Do not judge on max single-trade P&amp;L.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{quality_table([hist20, hist10, tape20, tape10])}

<h2>Freeze</h2>
<ul>
<li>Sport: tennis only (ATP/WTA/ITF/Challenger as E if those markets exist).</li>
<li>Bet type: spread only, not moneyline, not Points Total.</li>
<li>Band: <code>0.20 &lt;= px &lt; 0.50</code> after-fee cash; cheapest venue/side on the match.</li>
<li>Stake $1, max_open 2, 1 contract. Skip if B already on the match. Leftover-watch does not hedge F.</li>
<li>REST recheck before send. Polymarket US fill-or-kill, same T0 send as E.</li>
</ul>

<p class="tiny">Parent recs:
<a href="combined_t0_decile_system_recs_20261030.html">combined_t0_decile_system_recs_20261030.html</a>
· live runner <code>tools/live_tennis_t0_spread.py</code>
· flags <code>--tennis-t0-spread</code>
· File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return PAGE


def link_recs_page() -> None:
    if not RECS.is_file():
        return
    html = RECS.read_text(encoding="utf-8")
    needle = "system_f_tennis_spread_20261030.html"
    if needle in html:
        return
    bit = (
        ' · <a href="system_f_tennis_spread_20261030.html">'
        "F Tennis spread (30 Oct)</a>"
    )
    html = html.replace(
        '<a href="kalshi_poly_combined_t0_decile_20261030.html">combined cheapest T0 decile (30 Oct)</a>',
        '<a href="kalshi_poly_combined_t0_decile_20261030.html">combined cheapest T0 decile (30 Oct)</a>'
        + bit,
        1,
    )
    RECS.write_text(html, encoding="utf-8")
    py = Path(__file__).resolve().parents[0] / "_write_combined_t0_decile_system_recs_20261030.py"
    if py.is_file():
        src = py.read_text(encoding="utf-8")
        if needle not in src:
            src = src.replace(
                '<a href="kalshi_poly_combined_t0_decile_20261030.html">combined cheapest T0 decile (30 Oct)</a>',
                '<a href="kalshi_poly_combined_t0_decile_20261030.html">combined cheapest T0 decile (30 Oct)</a>'
                + bit,
                1,
            )
            py.write_text(src, encoding="utf-8")


def pack(rec: dict, *, label: str, band: str, note: str) -> dict:
    out = dict(rec)
    out["label"] = label
    out["band"] = band
    out["note"] = note
    q = out.get("quality") or {}
    if q:
        q.pop("trades", None)
    return out


def main() -> int:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    print("loading combined hist", flush=True)
    hist_dir = LOCAL_STAMP / "hist"
    k_raw = decile_w.load_json_list(hist_dir / "books_kalshi.json")
    p_raw = decile_w.load_json_list(hist_dir / "books_poly.json")
    print(f"raw kalshi={len(k_raw)} poly={len(p_raw)}", flush=True)
    k_sides, _k_stats = comb.attach_event_keys(k_raw)
    p_sides, _p_stats = comb.attach_event_keys(p_raw)
    matched, leftover_k, leftover_p, match = comb.match_dual(k_sides, p_sides)
    selected, counts = comb.select_combined(matched, leftover_k, leftover_p)
    print(
        f"combined n={len(selected)} dual={match.get('n_dual')} "
        f"k_only={match.get('n_kalshi_only')} p_only={match.get('n_poly_only')}",
        flush=True,
    )
    hist20_sides = book_from_sides(selected, lo=0.20, hi=0.50)
    hist10_sides = book_from_sides(selected, lo=0.10, hi=0.50)
    hist20 = score_book(hist20_sides, arm="Combined hist 20–49 freeze")
    hist10 = score_book(hist10_sides, arm="Combined hist 10–49 sensitivity")
    print(
        f"hist 20-49 N={hist20['n']} avg={hist20['avg']}  "
        f"10-49 N={hist10['n']} avg={hist10['avg']}",
        flush=True,
    )
    print("streaming live tape Oct 2026 tennis spreads", flush=True)
    live_sides, live_meta = stream_live_tennis_spreads()
    print(
        f"live sides={live_meta.get('n_sides')} yes={live_meta.get('n_yes')} "
        f"lines={live_meta.get('n_lines')} overlay={live_meta.get('n_overlay')}",
        flush=True,
    )
    tape20_sides = live_book(live_sides, lo=0.20, hi=0.50)
    tape10_sides = live_book(live_sides, lo=0.10, hi=0.50)
    tape20 = score_book(tape20_sides, arm="Live tape Oct 2026 20–49 freeze")
    tape10 = score_book(tape10_sides, arm="Live tape Oct 2026 10–49 sensitivity")
    print(
        f"tape 20-49 N={tape20['n']} avg={tape20['avg']}  "
        f"10-49 N={tape10['n']} avg={tape10['avg']}",
        flush=True,
    )
    pids = f_running()
    payload = {
        "written": now,
        "cli": CLI,
        "f_pids": pids,
        "f_running": bool(pids),
        "band_freeze": "0.20 <= px < 0.50",
        "match": {k: match.get(k) for k in ("n_dual", "n_kalshi_only", "n_poly_only") if k in match},
        "counts": {
            "kalshi_cheaper_af": counts.get("kalshi_cheaper_af"),
            "poly_cheaper_af": counts.get("poly_cheaper_af"),
            "tie_af": counts.get("tie_af"),
        },
        "live_meta": live_meta,
        "hist_20_49": pack(
            hist20,
            label="Combined Kalshi+Poly hist (cheaper after-fee / one shop)",
            band="20–49 freeze",
            note="Kalshi T0 Yes-ask; Poly T0 last-trade. One cheapest spread per match.",
        ),
        "hist_10_49": pack(
            hist10,
            label="Combined Kalshi+Poly hist (sensitivity)",
            band="10–49 sensitivity",
            note="Not the freeze. Green cell on the cheaper-Yes page was 10–49.",
        ),
        "tape_20_49": pack(
            tape20,
            label="Live kitchen tape Oct 2026 (price_memory / price_last_games)",
            band="20–49 freeze",
            note=(
                "Kitchen tennis ticks Oct 21–30 2026 are moneyline only "
                f"({live_meta.get('n_lines') or 0} lines, 0 spread Yes). "
                "price_last_games tennis files have no spread market_type. "
                "N=0 is labeled, not mixed with hist."
            ),
        ),
        "tape_10_49": pack(
            tape10,
            label="Live kitchen tape Oct 2026 (sensitivity)",
            band="10–49 sensitivity",
            note="Not the freeze.",
        ),
        "html": str(PAGE),
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    path = write_html(payload, now)
    link_recs_page()
    print(f"wrote {path} F running={bool(pids)} pids={pids}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
