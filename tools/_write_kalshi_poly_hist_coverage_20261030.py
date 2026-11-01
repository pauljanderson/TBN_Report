"""Kalshi + Polymarket hist coverage HTML — 30 Oct 2026.

Report of files on disk. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not leftover-GTC A.
Does not DailyRun. Does not retune B/C/D/E. Does not start F or G.
Does not rewrite dashboard.html. Does not start a second through-game pull.
"""
from __future__ import annotations

import html as html_mod
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
import _pull_kalshi_inplay_path_20261030 as inplay  # noqa: E402
import _pull_pm_hist_t0_20261028 as t0pull  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "kalshi_poly_hist_coverage_20261030.html"
PAGE_SLOT = STAMP / "kalshi_hist_coverage_20261029.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/kalshi_poly_hist_coverage_20261030.html"
)
POLY_INV_URL = "poly_hist_inventory_20261030.html"
DECILE_URL = "sport_league_t0_decile_20261027.html"
HIST = LOCAL_STAMP / "hist"
INPLAY_PID = 58212

ASKED = (
    "can you continue making sure we get all the data for kalshi and polymarket "
    "that they have? I saw some json from my earlier request, but i'd really like an HTML"
)
PLAIN = (
    "This page is the phone-book of what we already have from Kalshi and Polymarket, "
    "not a dump of the raw files. For each shop we count named sides (one Yes per "
    "player or team), the date range, and whether we stored the starting price, the "
    "final result, and the price path while the game was on. Kalshi history stores "
    "the Yes ask at kickoff (the price you pay to buy Yes) plus who won. Polymarket "
    "history stores the last trade on the global book at kickoff, not the Yes ask, "
    "plus who won. The through-game Kalshi pull (process 58212, resume of dead 70628) "
    "is the only tape that keeps in-play Yes-ask bars; we did not start a second copy "
    "of it. Leftover "
    "kickoff pulls fill holes (missing Yes-asks, empty series, Polymarket leagues "
    "the public list still shows). Live tennis crossover, leftover-GTC on A, and "
    "Systems F/G were not started from this page."
)


def esc(text) -> str:
    return html_mod.escape("" if text is None else str(text))


def now_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def mtime_et(path: Path) -> str:
    if not path.exists():
        return "—"
    return datetime.fromtimestamp(path.stat().st_mtime, ET).strftime("%Y-%m-%d %H:%M ET")


def pid_alive(pid) -> bool:
    try:
        pid_i = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_i <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid_i)
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid_i, 0)
    except OSError:
        return False
    return True


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], *, total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    foot = ""
    if total:
        foot = (
            '<tr class="total-row">'
            + "".join(f"<td>{cell}</td>" for cell in total)
            + "</tr>"
        )
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}{foot}</tbody></table></div>"
    )


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def comma(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def span_of(sides: list[dict]) -> str:
    dates = [str(s.get("entry_date") or "") for s in sides if s.get("entry_date")]
    dates = [d for d in dates if d]
    if not dates:
        return "—"
    return f"{min(dates)} .. {max(dates)}"


def sport_kind_rows(sides: list[dict]) -> list[list[str]]:
    c = Counter()
    for side in sides:
        sport = str(side.get("sport") or "—")
        kind = str(side.get("kind") or "—")
        c[(sport, kind)] += 1
    rows = []
    for (sport, kind), n in sorted(c.items()):
        rows.append([esc(sport), esc(kind), comma(n)])
    return rows


def line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for _ in handle:
            n += 1
    return n


def http_404_by_series() -> dict[str, int]:
    out: Counter = Counter()
    folder = HIST / "kalshi" / "t0"
    if not folder.is_dir():
        return {}
    for path in folder.glob("*.jsonl"):
        n = 0
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if int(row.get("http") or 0) == 404:
                    n += 1
        if n:
            out[path.stem] = n
    return dict(out)


def leftover_status_line(path: Path, fallback_pid: str = "—") -> str:
    rec = load_json(path) or {}
    pid = rec.get("pid") or fallback_pid
    alive = pid_alive(pid)
    running = bool(rec.get("running")) and alive
    current = rec.get("current_series") or "—"
    queue = rec.get("series_queue") or []
    n_q = len(queue) if isinstance(queue, list) else "—"
    state = "running" if running else ("status file, process not alive" if rec else "not started on disk")
    return (
        f"{state}; pid={pid}; current={current}; queue N={n_q}; "
        f"mtime {mtime_et(path)}"
    )


def inplay_progress() -> dict:
    st = inplay.census_inplay()
    pid = st.get("pid") or INPLAY_PID
    alive = pid_alive(pid) or pid_alive(INPLAY_PID)
    return {
        "pid": pid,
        "alive": alive,
        "running_flag": bool(st.get("running")),
        "n_target": st.get("n_target") or 0,
        "n_done": st.get("n_done") or 0,
        "n_usable": st.get("n_usable") or 0,
        "n_usable_5425": st.get("n_usable_5425") or 0,
        "n_usable_tennis": st.get("n_usable_tennis") or 0,
        "n_target_5425": st.get("n_target_5425") or 0,
        "current": st.get("current_series") or "—",
        "last_ticker": st.get("last_ticker") or "—",
        "written_at": st.get("written_at") or mtime_et(HIST / "inplay_status.json"),
        "by_series": st.get("by_series") or {},
        "status_mtime": mtime_et(HIST / "inplay_status.json"),
        "log_mtime": mtime_et(HIST / "inplay_pull.log"),
    }


def main() -> int:
    now = now_et()
    books_k = load_json(HIST / "books_kalshi.json") or []
    books_p = load_json(HIST / "books_poly.json") or []
    coverage = load_json(HIST / "coverage.json") or []
    n404 = http_404_by_series()
    ip = inplay_progress()
    k_n = len(books_k)
    p_n = len(books_p)
    k_span = span_of(books_k)
    p_span = span_of(books_p)

    leftover_k = leftover_status_line(HIST / "leftover_kalshi_status.json")
    leftover_p = leftover_status_line(HIST / "leftover_poly_status.json")
    inplay_alive = "yes — one process" if ip["alive"] else "no — did not start a second copy"
    inplay_yesno = (
        f"hist T0 tape: no. Through-game pull: {comma(ip['n_usable'])} usable of "
        f"{comma(ip['n_target'])} target; process alive={inplay_alive}"
    )

    vs_tbl = table(
        [
            ("Venue", "text"),
            ("N sides", "num"),
            ("Date span (entry_date)", "text"),
            ("Quote type", "text"),
            ("Beginning odds", "text"),
            ("Ending result", "text"),
            ("In-play Yes-ask path", "text"),
            ("Leftover T0 pull", "text"),
        ],
        [
            [
                "Kalshi",
                comma(k_n),
                esc(k_span),
                "Yes-ask (candle close at kickoff clock)",
                "yes — last yes_ask.close at/just before occurrence",
                "yes — market result yes/no",
                esc(inplay_yesno),
                esc(leftover_k),
            ],
            [
                "Polymarket",
                comma(p_n),
                esc(p_span),
                "CLOB last-trade (not Yes-ask; global book, not Polymarket US)",
                "yes — last trade at/just before gameStartTime",
                "yes — outcomePrices 0 or 1",
                "no on hist (0 stored paths). CLOB through-game last-trade not started, not mixed.",
                esc(leftover_p),
            ],
        ],
        total=["Both books", comma(k_n + p_n), "do not blend", "different quote types", "—", "—", "—", "—"],
    )

    k_sk = sport_kind_rows(books_k)
    p_sk = sport_kind_rows(books_p)
    k_sk_tbl = table(
        [("Sport", "text"), ("Bet type", "text"), ("N sides", "num")],
        k_sk,
        total=["Kalshi all", "—", comma(k_n)],
    )
    p_sk_tbl = table(
        [("Sport", "text"), ("Bet type", "text"), ("N sides", "num")],
        p_sk,
        total=["Poly all", "—", comma(p_n)],
    )

    hole_rows = []
    cov_k = [r for r in coverage if r.get("platform") == "kalshi"]
    for row in sorted(cov_k, key=lambda r: str(r.get("series") or "")):
        series = str(row.get("series") or "")
        n_t0 = int(row.get("n_t0") or 0)
        n_miss = int(row.get("n_missing") or 0)
        n_ev = int(row.get("n_events") or 0)
        fetched = bool(row.get("candles_fetched"))
        http_n = n404.get(series, 0)
        cap = ""
        if n_ev >= 16000:
            cap = "Kalshi event pager cap (~16,200 = 81×200)"
        reasons = []
        if n_t0 == 0:
            reasons.append("0 T0")
        if n_miss > 0:
            reasons.append(f"missing candles {n_miss:,}")
        if http_n:
            reasons.append(f"HTTP 404 ×{http_n:,}")
        if cap:
            reasons.append(cap)
        if not fetched:
            reasons.append("candles_fetched=false")
        if not reasons:
            continue
        if t0pull.leftover_should_skip(row) and not http_n and not cap:
            continue
        hole_rows.append([
            "Kalshi",
            esc(series),
            esc(row.get("sport") or ""),
            esc(row.get("kind") or ""),
            comma(n_ev),
            comma(n_t0),
            comma(n_miss),
            comma(http_n),
            esc("; ".join(reasons)),
        ])
    # Series on leftover list with no coverage row.
    cov_series = {str(r.get("series")) for r in cov_k}
    t0_dir = HIST / "kalshi" / "t0"
    for ticker in t0pull.LEFTOVER_TICKER:
        if ticker in cov_series:
            continue
        n_t0 = line_count(t0_dir / f"{ticker}.jsonl") if t0_dir.is_dir() else 0
        hole_rows.append([
            "Kalshi", esc(ticker), "—", "—", "—", comma(n_t0), "—",
            comma(n404.get(ticker, 0)),
            "no coverage.json row" + ("" if n_t0 else "; 0 T0 file"),
        ])

    poly_t0 = HIST / "poly" / "t0"
    poly_ev = HIST / "poly" / "events"
    for key in list(t0pull.POLY_SPORT_KEYS) + list(t0pull.POLY_HOLE_KEYS):
        n_t0 = line_count(poly_t0 / f"{key}.jsonl")
        n_ev = line_count(poly_ev / f"{key}.jsonl")
        reasons = []
        if n_t0 == 0:
            reasons.append("0 T0")
        if n_ev == 0 and key in t0pull.POLY_HOLE_KEYS:
            reasons.append("no events file yet; Gamma lists the sport")
        if n_ev >= 2050:
            reasons.append("event-list cap 2,050")
        if n_ev > 0 and n_t0 == 0:
            reasons.append("events on disk, last-trade not candled")
        if not reasons:
            continue
        hole_rows.append([
            "Polymarket",
            esc(key),
            esc(t0pull._poly_sport_league(key)[0]),
            "ml / spread / total",
            comma(n_ev),
            comma(n_t0),
            "—",
            "—",
            esc("; ".join(reasons)),
        ])

    hole_tbl = table(
        [
            ("Venue", "text"), ("Series / league", "text"), ("Sport", "text"),
            ("Bet type", "text"), ("Events on disk", "num"), ("T0 N", "num"),
            ("Missing T0", "num"), ("HTTP 404 rows", "num"), ("Hole", "text"),
        ],
        hole_rows,
    )

    ip_rows = [
        ["PID", str(ip["pid"])],
        ["Process alive", "yes" if ip["alive"] else "no"],
        ["Status file running flag", "yes" if ip["running_flag"] else "no"],
        ["Command", "python -u tools/_pull_kalshi_inplay_path_20261030.py"],
        ["Target sides", comma(ip["n_target"] or 51435)],
        ["Fetched jsonl rows", comma(ip["n_done"])],
        ["Usable in-play paths", comma(ip["n_usable"])],
        ["Usable tennis (any decile)", comma(ip["n_usable_tennis"])],
        ["Target tennis ML 90-99", comma(ip["n_target_5425"])],
        ["Usable tennis ML 90-99", comma(ip["n_usable_5425"])],
        ["Current series (last status)", esc(ip["current"])],
        ["Last ticker", esc(ip["last_ticker"])],
        ["Status written", esc(ip["written_at"])],
        ["inplay_status.json mtime", esc(ip["status_mtime"])],
        ["inplay_pull.log mtime", esc(ip["log_mtime"])],
        ["Second copy", "not started"],
    ]
    ip_tbl = table([("Item", "text"), ("Value", "text")], ip_rows)

    series_rows = []
    for series, rec in sorted((ip.get("by_series") or {}).items()):
        series_rows.append([esc(series), comma(rec.get("n")), comma(rec.get("usable"))])
    series_tbl = table(
        [("In-play series file", "text"), ("Rows fetched", "num"), ("Usable paths", "num")],
        series_rows,
        total=["All in-play jsonl", comma(ip["n_done"]), comma(ip["n_usable"])],
    )

    if ip["alive"]:
        inplay_verdict = (
            f"Through-game pull pid {ip['pid']} is still one process. "
            f"Usable paths {ip['n_usable']:,} / target {ip['n_target'] or 51435:,}; tennis first."
        )
    else:
        inplay_verdict = (
            f"Through-game pull pid {INPLAY_PID} is not running "
            f"(last status {ip['written_at']}, usable {ip['n_usable']:,} / "
            f"target {ip['n_target'] or 51435:,} on disk). Did not start a second copy. "
            "In-play jsonl was not deleted."
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Kalshi + Polymarket hist coverage 30 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.hold {{ background: #fef3c7; border-color: #f59e0b; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Kalshi + Polymarket history coverage</h1>
<p class="note">Written {esc(now)}. Inventory of kickoff tapes on disk plus leftover T0
resume and the through-game pull. Click column headers to sort. Did not sell tickets,
start a second Tennis crossover (B), leftover-GTC A, DailyRun, retune B/C/D/E, start
F or G, rewrite dashboard.html, or start a second through-game pull.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout hold">
<h2>What we have today</h2>
<p>Kalshi book <strong>{esc(comma(k_n))}</strong> named sides, Yes-ask at kickoff plus
result, span {esc(k_span)}. Polymarket book <strong>{esc(comma(p_n))}</strong> named sides,
last-trade at kickoff plus result, span {esc(p_span)}. Hist T0 tapes do not keep the
in-play path. {esc(inplay_verdict)}</p>
<p>Related:
<a href="{esc(POLY_INV_URL)}">poly_hist_inventory_20261030.html</a> ·
<a href="{esc(DECILE_URL)}">sport_league_t0_decile_20261027.html</a>.
This file also refreshed the 29 Oct slot
<code>kalshi_hist_coverage_20261029.html</code>.</p>
</div>

<h2>Kalshi vs Polymarket</h2>
<p class="note">Do not blend the two books. Click column headers to sort.</p>
{vs_tbl}

<h2>N by sport × bet type — Kalshi</h2>
<p class="note">From <code>hist/books_kalshi.json</code> (Yes-ask T0, both named sides
when stored). Click column headers to sort.</p>
{k_sk_tbl}

<h2>N by sport × bet type — Polymarket</h2>
<p class="note">From <code>hist/books_poly.json</code> (CLOB last-trade, both named sides).
Click column headers to sort.</p>
{p_sk_tbl}

<h2>Holes</h2>
<p class="note">0 T0, missing candles inside a series, HTTP 404 on a candle fetch,
event-list caps (Kalshi ~16,200 events, Poly 2,050), and Gamma sports we have not
candled. Still-downloading leftover jobs are in the leftover column above.
Click column headers to sort.</p>
{hole_tbl}

<h2>In-play path pull ({esc(ip['pid'])})</h2>
<p class="note">Kalshi 1-minute Yes-ask through the game, tennis first, target
{esc(comma(ip['n_target'] or 51435))} unique mid-price tickers. Live numbers from
<code>hist/inplay_status.json</code>, <code>hist/inplay_pull.log</code>, and
<code>hist/kalshi/inplay/*.jsonl</code>. Did not throw those bars away.</p>
{ip_tbl}
{series_tbl}

<p class="tiny">hist dir <code>{esc(HIST.as_posix())}</code>.
coverage.json {esc(mtime_et(HIST / 'coverage.json'))};
books_kalshi.json {esc(mtime_et(HIST / 'books_kalshi.json'))};
books_poly.json {esc(mtime_et(HIST / 'books_poly.json'))}.
Generator <code>tools/_write_kalshi_poly_hist_coverage_20261030.py</code>.
File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html, encoding="utf-8")
    PAGE_SLOT.write_text(html, encoding="utf-8")
    print(PAGE)
    print(PAGE_SLOT)
    print(FILE_URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
