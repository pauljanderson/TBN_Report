"""Wire note: System E now reads B's tennis_rows. Research only.

Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers
import live_t0_yes
import live_tennis_t0_dog as e
import prediction_job_control as jc
import prediction_systems as systems
import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP
from prediction_paths import RAW_DIR as RAW
from t0_all_games_stats import table

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "system_e_tennis_slate_20261028.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_e_tennis_slate_20261028.html"
)
ASKED = (
    "perfect. let's wire that up please. System E (tennis T0 dog) should actually "
    "see tennis and send under the freeze we just confirmed."
)
PLAIN = (
    "System E buys one cheap tennis underdog at the first trusted start (T0), "
    "Yes price from 11 cents through 49 cents, one contract, hold to the end. "
    "It was looking at the overnight sports list (football, baseball, and so on), "
    "which has no tennis. We pointed it at the same tennis list Strategy B already uses. "
    "If B already has that match, E still skips. Knobs did not change. Research only."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value), quote=True)


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _pids(jobs: dict, key: str) -> list[int]:
    return [int(row["pid"]) for row in (jobs.get(key) or []) if row.get("pid")]


def _money(value) -> str:
    if value is None:
        return "—"
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except Exception:
        return str(value)


def _dog_from_quotes(quotes: list[dict]) -> dict:
    rows = [row for row in quotes if str(row.get("kind") or "") in {"", "moneyline"}]
    for row in rows:
        if not row.get("kind"):
            row["kind"] = "moneyline"
    snap = live_t0_yes.dog_line_snapshot(rows)
    if not snap:
        primary = live_t0_yes.primary_side_asks(rows)
        dog = systems.pick_dog_primary(primary) if len(primary) >= 2 else None
        return {
            "dog": dog or "—",
            "ask": "—",
            "venue": "—",
            "in_band": "no",
            "note": "no unique dog in (0.10, 0.50)",
        }
    ask = snap.get("dog_ask")
    return {
        "dog": snap.get("dog") or "—",
        "ask": _money(ask),
        "venue": str((snap.get("best") or {}).get("venue") or "—"),
        "in_band": "yes" if systems.in_dog_band(ask) else "no",
        "note": snap.get("why") or "",
    }


def main() -> int:
    now = datetime.now(ET)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S ET")
    cfg = systems.get_system("tennis_t0_dog")
    jobs = jc.classify(jc._ps_rows())
    e_pids = _pids(jobs, "tennis_t0_dog")
    b_pids = _pids(jobs, "strategy_b")
    watch = _load(RAW / "tennis_t0_dog_watch.json")
    pid_blob = _load(RAW / "tennis_t0_dog.pid")
    b_watch = _load(RAW / "strategy_b_watch.json")
    scan = live_game_pollers.load_scan()
    sports = scan.load_sports()
    tennis_rows = live_game_pollers.tennis_rows(scan)
    slate = live_t0_yes.slate_near_t0(scan, "tennis_t0_dog")
    live = live_game_pollers.live_games(scan)
    live_tennis = [row for row in live if str(row.get("sport") or "").lower() == "tennis"]

    candidate_rows = []
    in_send = []
    in_band_now = []
    for spec in slate:
        title = str(spec.get("title") or "")
        listed = str(spec.get("listed_start") or spec.get("start") or "")
        clock, clock_src = live_t0_yes.trusted_t0_clock(listed, [], [])
        ready, why = live_t0_yes.t0_window(clock)
        holds = e.b_holds_match(title, sport="tennis", b_status=b_watch)
        dog_info = {"dog": "—", "ask": "—", "venue": "—", "in_band": "—", "note": "not quoted (outside T0 send window)"}
        if ready and not holds:
            try:
                quotes, kalshi_events, gemini_events, _p, _n = live_t0_yes.collect_quotes(
                    scan, spec.get("game") or {}, "tennis"
                )
                clock2, src2 = live_t0_yes.trusted_t0_clock(listed, gemini_events, kalshi_events)
                if clock2 is not None:
                    clock, clock_src = clock2, src2
                    ready, why = live_t0_yes.t0_window(clock)
                dog_info = _dog_from_quotes(quotes)
            except Exception as exc:
                dog_info = {
                    "dog": "—",
                    "ask": "—",
                    "venue": "—",
                    "in_band": "—",
                    "note": f"quote {type(exc).__name__}",
                }
        elif holds:
            dog_info["note"] = "B already on match"
        if ready:
            in_send.append(title)
            if dog_info.get("in_band") == "yes" and not holds:
                in_band_now.append(f"{title} {dog_info.get('dog')} @{dog_info.get('ask')} {dog_info.get('venue')}")
        candidate_rows.append([
            esc(title),
            esc(spec.get("sport") or "tennis"),
            esc(listed),
            esc(clock.isoformat() if clock else "—"),
            esc(clock_src or "—"),
            esc(why),
            esc("yes" if holds else "no"),
            esc(dog_info.get("dog")),
            esc(dog_info.get("ask")),
            esc(dog_info.get("venue")),
            esc(dog_info.get("in_band")),
            esc(dog_info.get("note")),
        ])

    facts = table(
        [("Check", "text"), ("Value", "text")],
        [
            ["Change", "live_t0_yes.slate_near_t0 — E now iterates tennis_rows (B's list)"],
            ["E on / stake / size / max_open", f"{'on' if cfg.on else 'off'} / ${cfg.stake_usd} / {cfg.size} / {cfg.max_open}"],
            ["E pid after reload", ", ".join(str(p) for p in e_pids) or "(none)"],
            ["E pid file", f"{pid_blob.get('pid')} started {pid_blob.get('started_at') or '—'}"],
            ["B pid (unchanged, still one)", ", ".join(str(p) for p in b_pids) or "(none)"],
            ["Watch pid / updated", f"{watch.get('pid')} / {watch.get('updated_at') or '—'}"],
            ["Watch matches / skipped / open", f"{len(watch.get('matches') or [])} / {len(watch.get('skipped') or [])} / {watch.get('currently_open')}"],
            ["Last skip", str(watch.get("last_skip_reason") or "(empty)")],
            ["sports_queue.json sports (old E source)", ", ".join(sorted(sports.keys()) or ["(empty)"])],
            ["tennis_rows (B / new E source)", str(len(tennis_rows))],
            ["live_games tennis count", str(len(live_tennis))],
            ["E slate_near_t0 tennis games", str(len(slate))],
            ["In T0 send window now (15s before through 300s after)", str(len(in_send))],
            ["Unique dog Yes in (0.10, 0.50) in that window", str(len(in_band_now))],
        ],
    )

    freeze = table(
        [("Knob", "text"), ("Freeze", "text")],
        [
            ["Universe", "Tennis moneyline underdog only. Unique cheaper player."],
            ["Band", "DOG_LO < px < DOG_HI with 0.10 and 0.50 exclusive → 11¢ through 49¢"],
            ["T0", "First trusted start. 15 seconds before through T0_GRACE_SEC=300 after."],
            ["Overlap", "Skip if B already has the match. Exception: B skipped all-in C>1.05."],
            ["Hold", "Hold to settle. No flatten, no 50-cross, no favorite dip, no both-Yes."],
            ["Size", "1 contract, stake $1, max_open 2"],
            ["Venue", "Cheapest Yes among kalshi, gemini, polymarket, novig; Kalshi wins ties. Poly FOK; others IOC."],
        ],
    )

    if candidate_rows:
        candidates = table(
            [
                ("Match", "text"),
                ("Sport", "text"),
                ("Listed start", "text"),
                ("Trusted T0", "text"),
                ("T0 source", "text"),
                ("T0 window", "text"),
                ("B holds", "text"),
                ("Dog", "text"),
                ("Dog Yes", "num"),
                ("Venue", "text"),
                ("In 11–49", "text"),
                ("Note", "text"),
            ],
            candidate_rows,
        )
    else:
        candidates = "<p class=\"note\">No tennis matches in E's gather window right now (15 minutes before listed start through a typical tennis length). The new slate is live; E will see the next tennis_rows match when it enters that window.</p>"

    in_band_html = (
        "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in in_band_now) + "</ul>"
        if in_band_now
        else "<p class=\"note\">None right now. Either nothing is inside the five-minute T0 send window, B already holds it, or the unique cheaper Yes is not 11–49¢.</p>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>System E tennis slate wired</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>System E now reads B's tennis list</h1>
<p class="note">Written {esc(now_s)}. Research-candidate live. Not gold. Not DailyRun. Did not sell, start a second B, bump stake, wire D NFL, leftover GTC, or retune C=1.05.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{PLAIN}</p></div>
<p class="note">One function changed: <code>live_t0_yes.slate_near_t0</code>. When the system is tennis T0 dog (E), it walks <code>live_game_pollers.tennis_rows</code> (same function Strategy B uses) and keeps sport=tennis. It does not pull NFL or college football into E. Skip-if-B-open is still the overlap control. Click headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h2>What changed and what is live</h2>
{facts}

<h2>Freeze (unchanged)</h2>
{freeze}

<h2>Candidate tennis matches in E's gather window now</h2>
{candidates}

<h2>Tennis dogs in the 11–49¢ T0 send window now</h2>
{in_band_html}

<p class="tiny">Sources: <code>systems.json</code>, <code>tennis_t0_dog_watch.json</code>, <code>tennis_t0_dog.pid</code>,
<code>strategy_b_watch.json</code>, <code>sports_queue.json</code>, live <code>tennis_rows</code>.
Code: <code>tools/live_t0_yes.py</code> <code>slate_near_t0</code>, <code>tools/live_game_pollers.py</code>
<code>tennis_rows</code>, <code>tools/live_tennis_t0_dog.py</code>, <code>tools/live_strategy_b.py</code>
<code>tennis_slate</code>. File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    print(
        json.dumps(
            {
                "e_pids": e_pids,
                "b_pids": b_pids,
                "b_count": len(b_pids),
                "on": cfg.on,
                "stake": str(cfg.stake_usd),
                "size": cfg.size,
                "max_open": cfg.max_open,
                "tennis_rows": len(tennis_rows),
                "slate": len(slate),
                "in_t0_window": in_send,
                "in_band": in_band_now,
                "watch_pid": watch.get("pid"),
                "watch_updated": watch.get("updated_at"),
                "last_skip": watch.get("last_skip_reason"),
            },
            default=str,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
