"""WPBR diagnostic: path to +15/+18/+20 after Day-40-below-entry survivors.

Book: 22/20/8 + wpbr_underwater_time_stop_bars=40
      tmp_wpbr_day40_underwater_ab_20261003/test stamp 261003081714.

Qualifying = closed trades whose EXIT_TYPE is not WPBR_UW_TS40.
Reach uses engine target-hit semantics for longs: High >= entry * (1 + pct).
Open-through is a subset of that (Open >= level implies High >= level).
Trading-bar offset from entry (entry bar = 0), scan capped at the exit bar.
No rule changes. No target recommendation. Mark experiments HTML only.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import statistics
import subprocess
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from _gen_too_high_diff import SORTABLE_TH_CSS, sortable_th  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TABLE_SCRIPT,
    SWIPE_NOTE_HTML,
)

IS_DATE = date(2024, 1, 1)
UW_EXIT = "WPBR_UW_TS40"
CLOSED = (
    ROOT
    / "tmp_wpbr_day40_underwater_ab_20261003"
    / "test"
    / "WPBR_Closed_261003081714.csv"
)
DB = ROOT / "data" / "ohlcv.duckdb"
OUT = ROOT / "drive" / "mark_experiments" / "wpbr_day40_survivor_path_diag_20261003"
PY = sys.executable
LEVELS = (15.0, 18.0, 20.0)
EPS = 1e-12

REQUEST_QUOTE = (
    "Run one diagnostic analysis on the current WPBR research system. "
    "Use the existing control: 22% overhead exclusion, +20% target, 8% stop under "
    "trigger-day low, plus the Day-40-below-entry exit rule. At the close of trading "
    "bar 40, exit only if the close is below the original entry. Otherwise continue "
    "normally. Do not change any entry, exit, universe, sizing, execution, or Day-40 "
    "logic. Do not test alternative targets. This is diagnostic only. For every trade "
    "that is NOT exited by the Day-40 rule, track its price path using the engine's "
    "existing target-hit semantics. Report IS, OOS, and FULL for reach rates, time to "
    "first reach, continuation from +15 and +18 toward +20, extra bars, and eventual "
    "exits for names that stall. Do not recommend a new target or optimize any parameters."
)


def _f(raw: Any, default: float = float("nan")) -> float:
    if raw is None:
        return default
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _ymd(raw: str) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _to_date(ymd: str) -> date | None:
    s = _ymd(ymd)
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _mean(xs: list[float]) -> float:
    ok = [x for x in xs if math.isfinite(x)]
    return float(sum(ok) / len(ok)) if ok else float("nan")


def _median(xs: list[float]) -> float:
    ok = [x for x in xs if math.isfinite(x)]
    return float(statistics.median(ok)) if ok else float("nan")


def _fmt(v: float, nd: int = 2, suffix: str = "") -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    if nd == 0:
        return f"{int(round(float(v)))}{suffix}"
    return f"{float(v):.{nd}f}{suffix}"


def _pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else float("nan")


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _to_date(str(raw.get("DATE_OPENED") or ""))
            closed = _to_date(str(raw.get("DATE_CLOSED") or ""))
            if opened is None:
                continue
            exit_type = str(raw.get("EXIT_TYPE") or "").strip()
            rows.append(
                {
                    "symbol": str(raw.get("SYMBOL") or "").strip().upper(),
                    "opened": opened,
                    "closed": closed,
                    "entry": _f(raw.get("ENTRY_PRICE")),
                    "exit_type": exit_type,
                    "pnl": _f(raw.get("PNL_PCT")),
                    "days": _f(raw.get("DAYS_HELD")),
                    "window": "IS" if opened < IS_DATE else "OOS",
                    "uw": exit_type == UW_EXIT,
                }
            )
    return rows


def load_prices(symbols: list[str]) -> dict[str, pd.DataFrame]:
    import duckdb

    con = duckdb.connect(str(DB), read_only=True)
    try:
        con.register("syms", pd.DataFrame({"symbol": symbols}))
        raw = con.execute(
            """
            SELECT
                symbol,
                date AS Date,
                open AS Open,
                high AS High,
                low AS Low,
                close AS Close
            FROM prices
            WHERE symbol IN (SELECT symbol FROM syms)
            ORDER BY symbol, date
            """
        ).fetchdf()
    finally:
        con.close()
    if raw.empty:
        return {}
    raw["Date"] = pd.to_datetime(raw["Date"])
    for col in ("Open", "High", "Low", "Close"):
        raw[col] = raw[col].astype("float64")
    out: dict[str, pd.DataFrame] = {}
    for sym, g in raw.groupby("symbol", sort=False):
        df = g.drop(columns=["symbol"]).set_index("Date").sort_index()
        out[str(sym).upper()] = df
    return out


def _bar_index(idx: pd.DatetimeIndex, d: date | None) -> int:
    if d is None:
        return -1
    ts = pd.Timestamp(d)
    pos = int(idx.searchsorted(ts, side="left"))
    if pos >= len(idx):
        return -1
    return pos


def first_reach_bars(high: np.ndarray, entry_i: int, exit_i: int, ep: float, pct: float) -> int | None:
    if ep <= 0 or entry_i < 0 or exit_i < entry_i or exit_i >= len(high):
        return None
    thr = ep * (1.0 + pct / 100.0)
    sl = high[entry_i : exit_i + 1]
    hits = np.flatnonzero(sl >= thr - EPS)
    if hits.size == 0:
        return None
    return int(hits[0])


def annotate(trades: list[dict[str, Any]], prices: dict[str, pd.DataFrame]) -> None:
    missing = 0
    for t in trades:
        df = prices.get(t["symbol"])
        t["b15"] = t["b18"] = t["b20"] = None
        t["path_ok"] = False
        if df is None or df.empty or t["closed"] is None or not math.isfinite(t["entry"]):
            missing += 1
            continue
        idx = pd.DatetimeIndex(df.index)
        eb = _bar_index(idx, t["opened"])
        xb = _bar_index(idx, t["closed"])
        if eb < 0 or xb < eb:
            missing += 1
            continue
        high = np.asarray(df["High"], dtype=np.float64)
        ep = float(t["entry"])
        t["b15"] = first_reach_bars(high, eb, xb, ep, 15.0)
        t["b18"] = first_reach_bars(high, eb, xb, ep, 18.0)
        t["b20"] = first_reach_bars(high, eb, xb, ep, 20.0)
        t["path_ok"] = True
    print(f"path annotated missing_or_bad={missing} / {len(trades)}", flush=True)


def _exit_mix(rows: list[dict[str, Any]]) -> list[tuple[str, int, float, float, float, float]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["exit_type"] or "(blank)", []).append(r)
    n = len(rows)
    out = []
    for name, grp in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        pnls = [g["pnl"] for g in grp]
        days = [g["days"] for g in grp]
        out.append((name, len(grp), _pct(len(grp), n), _mean(pnls), _mean(days), _median(days)))
    return out


def score_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    n15 = sum(1 for r in rows if r["b15"] is not None)
    n18 = sum(1 for r in rows if r["b18"] is not None)
    n20 = sum(1 for r in rows if r["b20"] is not None)
    t15 = [float(r["b15"]) for r in rows if r["b15"] is not None]
    t18 = [float(r["b18"]) for r in rows if r["b18"] is not None]
    t20 = [float(r["b20"]) for r in rows if r["b20"] is not None]
    from15_18 = [r for r in rows if r["b15"] is not None and r["b18"] is not None]
    from15_20 = [r for r in rows if r["b15"] is not None and r["b20"] is not None]
    from18_20 = [r for r in rows if r["b18"] is not None and r["b20"] is not None]
    extra_15_18 = [float(r["b18"] - r["b15"]) for r in from15_18]
    extra_15_20 = [float(r["b20"] - r["b15"]) for r in from15_20]
    extra_18_20 = [float(r["b20"] - r["b18"]) for r in from18_20]
    stall15 = [r for r in rows if r["b15"] is not None and r["b20"] is None]
    stall18 = [r for r in rows if r["b18"] is not None and r["b20"] is None]
    same_bar_15_20 = sum(1 for r in from15_20 if r["b20"] == r["b15"])
    same_bar_18_20 = sum(1 for r in from18_20 if r["b20"] == r["b18"])
    return {
        "n": n,
        "n15": n15,
        "n18": n18,
        "n20": n20,
        "p15": _pct(n15, n),
        "p18": _pct(n18, n),
        "p20": _pct(n20, n),
        "avg15": _mean(t15),
        "med15": _median(t15),
        "avg18": _mean(t18),
        "med18": _median(t18),
        "avg20": _mean(t20),
        "med20": _median(t20),
        "n15_18": len(from15_18),
        "p15_18": _pct(len(from15_18), n15),
        "n15_20": len(from15_20),
        "p15_20": _pct(len(from15_20), n15),
        "n18_20": len(from18_20),
        "p18_20": _pct(len(from18_20), n18),
        "avg_x1518": _mean(extra_15_18),
        "med_x1518": _median(extra_15_18),
        "avg_x1520": _mean(extra_15_20),
        "med_x1520": _median(extra_15_20),
        "avg_x1820": _mean(extra_18_20),
        "med_x1820": _median(extra_18_20),
        "same1520": same_bar_15_20,
        "same1820": same_bar_18_20,
        "stall15_n": len(stall15),
        "stall15_pnl": _mean([r["pnl"] for r in stall15]),
        "stall15_avg_d": _mean([r["days"] for r in stall15]),
        "stall15_med_d": _median([r["days"] for r in stall15]),
        "stall15_exits": _exit_mix(stall15),
        "stall18_n": len(stall18),
        "stall18_pnl": _mean([r["pnl"] for r in stall18]),
        "stall18_avg_d": _mean([r["days"] for r in stall18]),
        "stall18_med_d": _median([r["days"] for r in stall18]),
        "stall18_exits": _exit_mix(stall18),
        "path_ok": sum(1 for r in rows if r["path_ok"]),
    }


def _table(headers: list[tuple[str, str]], body_rows: list[list[str]]) -> str:
    head = "".join(sortable_th(lab, kind) for lab, kind in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in body_rows)
    return (
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def slice_html(label: str, s: dict[str, Any]) -> str:
    esc = html_mod.escape
    reach = _table(
        [("Metric", "text"), ("N", "num"), ("% of qualifying", "num"), ("Avg bars to first reach", "num"), ("Median bars to first reach", "num")],
        [
            ["Reach +15%", str(s["n15"]), _fmt(s["p15"], 1, "%"), _fmt(s["avg15"], 1), _fmt(s["med15"], 1)],
            ["Reach +18%", str(s["n18"]), _fmt(s["p18"], 1, "%"), _fmt(s["avg18"], 1), _fmt(s["med18"], 1)],
            ["Reach +20%", str(s["n20"]), _fmt(s["p20"], 1, "%"), _fmt(s["avg20"], 1), _fmt(s["med20"], 1)],
        ],
    )
    cont = _table(
        [("From / to", "text"), ("N that continue", "num"), ("% of from-group", "num"), ("Avg extra bars", "num"), ("Median extra bars", "num"), ("Same-bar finish", "num")],
        [
            ["+15% → +18%", str(s["n15_18"]), _fmt(s["p15_18"], 1, "%"), _fmt(s["avg_x1518"], 1), _fmt(s["med_x1518"], 1), "—"],
            ["+15% → +20%", str(s["n15_20"]), _fmt(s["p15_20"], 1, "%"), _fmt(s["avg_x1520"], 1), _fmt(s["med_x1520"], 1), str(s["same1520"])],
            ["+18% → +20%", str(s["n18_20"]), _fmt(s["p18_20"], 1, "%"), _fmt(s["avg_x1820"], 1), _fmt(s["med_x1820"], 1), str(s["same1820"])],
        ],
    )

    def stall_block(title: str, n: int, pnl: float, avg_d: float, med_d: float, exits: list) -> str:
        if n == 0:
            mix = "<p class=\"note\">None.</p>"
        else:
            mix = _table(
                [("Exit", "text"), ("N", "num"), ("Share", "num"), ("Avg final P&L %", "num"), ("Avg days held", "num"), ("Median days held", "num")],
                [
                    [
                        esc(name),
                        str(cnt),
                        _fmt(share, 1, "%"),
                        _fmt(ap, 2, "%"),
                        _fmt(ad, 1),
                        _fmt(md, 1),
                    ]
                    for name, cnt, share, ap, ad, md in exits
                ],
            )
        return (
            f"<h4>{esc(title)}</h4>"
            f"<p class=\"note\">N={n}. Average final P&amp;L {_fmt(pnl, 2, '%')}. "
            f"Average days held {_fmt(avg_d, 1)}; median {_fmt(med_d, 1)}.</p>"
            f"{mix}"
        )

    return f"""
<h3>{esc(label)}</h3>
<p class="note">Qualifying closed trades (not {esc(UW_EXIT)}): <strong>{s['n']}</strong>.
Price path found for {s['path_ok']} of them. Bars are trading sessions from entry (entry = 0).</p>
{SWIPE_NOTE_HTML}
{reach}
<h4>Continuation after first reach</h4>
{SWIPE_NOTE_HTML}
{cont}
{stall_block("Reached +15% but never +20%", s["stall15_n"], s["stall15_pnl"], s["stall15_avg_d"], s["stall15_med_d"], s["stall15_exits"])}
{stall_block("Reached +18% but never +20%", s["stall18_n"], s["stall18_pnl"], s["stall18_avg_d"], s["stall18_med_d"], s["stall18_exits"])}
"""


def write_baseline(uw_n: int, scored: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# WPBR Day-40 survivor path diagnostic",
        "",
        "Pivot Break and Retest (WPBR). Diagnostic only. No rule change. No target recommendation.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "We took the existing Pivot Break and Retest research book that already skips buys with "
        "a weekly zone within 22% overhead, sells the whole position at +20%, stops 8% under the "
        "trigger-day low, and also sells at the Day-40 close if that close is still below the original "
        "buy. We then threw out the trades that were cut by that Day-40 rule. For everyone else, we "
        "watched the daily high the same way the engine tags a profit target: the first trading day "
        "the high prints at least +15%, +18%, or +20% from the buy. The question is whether names "
        "that already worked spent a lot of extra sessions grinding from +15% or +18% to the live "
        "+20% target. Buys before 2024 are in-sample. 2024 onward is out of sample and is for reading only.",
        "",
        "## Observed path (not a recommendation)",
        "",
        "This page reports what happened. It does not pick a new target or change DailyRun.",
        "",
        "## Freeze",
        "",
        "- Closed book: `tmp_wpbr_day40_underwater_ab_20261003/test` stamp **261003081714**.",
        "- Knobs: `wpbr_overhead_band_pct=0.22`, `target_pct=1.20`, `stop_pct=0.92`, "
        "`wpbr_underwater_time_stop_bars=40`. Universe, entries, sizing, execution unchanged.",
        f"- Day-40 underwater exits excluded from the path set: **{uw_n}** trades labeled `{UW_EXIT}`.",
        "- Reach rule (longs): first bar where `High >= entry × (1 + pct)`. Matches engine `target_hit` "
        "(`hi >= tp`). A gap through the level (`Open >= level`) is included because High is at least Open.",
        "- Entry bar = 0. Scan stops on the exit date (inclusive). Post-exit prints do not count.",
        "- Extra bars = (bars to later level) − (bars to earlier level). Zero means both tagged the same session.",
        "- Days held and final P&L on stall groups are the actual closed-trade fields.",
        "- IS: `DATE_OPENED < 2024-01-01`. OOS report-only. Not gold. Not DailyRun.",
        "",
    ]
    for sl in ("FULL", "IS", "OOS"):
        s = scored[sl]
        lines += [
            f"### {sl}",
            "",
            f"- Qualifying N: {s['n']}",
            f"- Reach +15% / +18% / +20%: {s['n15']} ({_fmt(s['p15'],1,'%')}) / "
            f"{s['n18']} ({_fmt(s['p18'],1,'%')}) / {s['n20']} ({_fmt(s['p20'],1,'%')})",
            f"- Avg (median) bars to first +15 / +18 / +20: "
            f"{_fmt(s['avg15'],1)} ({_fmt(s['med15'],1)}) / "
            f"{_fmt(s['avg18'],1)} ({_fmt(s['med18'],1)}) / "
            f"{_fmt(s['avg20'],1)} ({_fmt(s['med20'],1)})",
            f"- Of +15% names, later +18% / +20%: {s['n15_18']} ({_fmt(s['p15_18'],1,'%')}) / "
            f"{s['n15_20']} ({_fmt(s['p15_20'],1,'%')})",
            f"- Of +18% names, later +20%: {s['n18_20']} ({_fmt(s['p18_20'],1,'%')})",
            f"- Extra bars +15→+18 / +15→+20 / +18→+20 avg (median): "
            f"{_fmt(s['avg_x1518'],1)} ({_fmt(s['med_x1518'],1)}) / "
            f"{_fmt(s['avg_x1520'],1)} ({_fmt(s['med_x1520'],1)}) / "
            f"{_fmt(s['avg_x1820'],1)} ({_fmt(s['med_x1820'],1)})",
            f"- +15 never +20: N={s['stall15_n']}, avg P&L {_fmt(s['stall15_pnl'],2,'%')}, "
            f"avg/median days {_fmt(s['stall15_avg_d'],1)} / {_fmt(s['stall15_med_d'],1)}",
            f"- +18 never +20: N={s['stall18_n']}, avg P&L {_fmt(s['stall18_pnl'],2,'%')}, "
            f"avg/median days {_fmt(s['stall18_avg_d'],1)} / {_fmt(s['stall18_med_d'],1)}",
            "",
        ]
    (OUT / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def write_html(uw_n: int, scored: dict[str, dict[str, Any]]) -> Path:
    sections = []
    for sl, title in (
        ("FULL", "Full book"),
        ("IS", "In-sample (entry before 2024-01-01)"),
        ("OOS", "Out-of-sample (entry on or after 2024-01-01) — report only"),
    ):
        sections.append(slice_html(title, scored[sl]))
    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>WPBR Day-40 survivor path to +15 / +18 / +20</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1c1917; max-width: 1100px; }}
h1 {{ font-size: 1.5rem; }}
.callout {{ background: #f5f5f0; border: 1px solid #d6d3d1; padding: 12px 16px; margin: 12px 0 18px; }}
blockquote {{ margin: 8px 0; }}
td, th {{ padding: 4px 8px; border-bottom: 1px solid #e7e5e4; }}
td {{ text-align: right; }}
td:first-child, th:first-child {{ text-align: left; }}
.note {{ font-size: 0.95rem; color: #44403c; }}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style>
</head><body>
{FORCE_RELOAD_SCRIPT}
<h1>Pivot Break and Retest — path after Day-40-below-entry survivors</h1>
<p class="note">Diagnostic only. No rule change. No new target. Not gold. Not DailyRun. Click column headers to sort. Swipe sideways to see more columns.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>We used the existing research book: skip a buy if an older weekly zone sits within 22% overhead, take +20% on the whole position, stop 8% under the trigger-day low, and sell at the Day-40 close only if that close is still below the original buy. Trades cut by that Day-40 rule are out of this page ({uw_n} of them). For everyone else we asked when the daily high first tagged +15%, +18%, and +20% from the buy — the same High test the engine uses for a profit target. The research question is whether names that already worked spent a lot of extra sessions getting from +15% or +18% to the live +20% target. Buys before 2024 are in-sample. 2024 onward is for reading only.</p>
</div>
<h2>How reach is counted</h2>
<p class="note">Long target-hit in the engine is <code>High &gt;= target</code> (and <code>Open &gt;= target</code> is a gap-through, which already implies High is at least Open). We use that on hypothetical +15% / +18% / +20% levels. Entry session = bar 0. We stop at the actual exit date. Same-session extra bars = 0. This page does not recommend cutting the target.</p>
{''.join(sections)}
<p class="note">Observed path only. Not gold. Not DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT / "compare.html"
    path.write_text(page, encoding="utf-8")
    return path


def write_summary(scored: dict[str, dict[str, Any]]) -> Path:
    path = OUT / "summary.csv"
    fields = [
        "slice", "qualifying_n",
        "n15", "pct15", "avg_bars15", "med_bars15",
        "n18", "pct18", "avg_bars18", "med_bars18",
        "n20", "pct20", "avg_bars20", "med_bars20",
        "n15_to_18", "pct15_to_18", "n15_to_20", "pct15_to_20", "n18_to_20", "pct18_to_20",
        "avg_extra_15_18", "med_extra_15_18",
        "avg_extra_15_20", "med_extra_15_20",
        "avg_extra_18_20", "med_extra_18_20",
        "stall15_n", "stall15_avg_pnl", "stall15_avg_days", "stall15_med_days",
        "stall18_n", "stall18_avg_pnl", "stall18_avg_days", "stall18_med_days",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for sl in ("FULL", "IS", "OOS"):
            s = scored[sl]
            w.writerow({
                "slice": sl,
                "qualifying_n": s["n"],
                "n15": s["n15"], "pct15": s["p15"], "avg_bars15": s["avg15"], "med_bars15": s["med15"],
                "n18": s["n18"], "pct18": s["p18"], "avg_bars18": s["avg18"], "med_bars18": s["med18"],
                "n20": s["n20"], "pct20": s["p20"], "avg_bars20": s["avg20"], "med_bars20": s["med20"],
                "n15_to_18": s["n15_18"], "pct15_to_18": s["p15_18"],
                "n15_to_20": s["n15_20"], "pct15_to_20": s["p15_20"],
                "n18_to_20": s["n18_20"], "pct18_to_20": s["p18_20"],
                "avg_extra_15_18": s["avg_x1518"], "med_extra_15_18": s["med_x1518"],
                "avg_extra_15_20": s["avg_x1520"], "med_extra_15_20": s["med_x1520"],
                "avg_extra_18_20": s["avg_x1820"], "med_extra_18_20": s["med_x1820"],
                "stall15_n": s["stall15_n"], "stall15_avg_pnl": s["stall15_pnl"],
                "stall15_avg_days": s["stall15_avg_d"], "stall15_med_days": s["stall15_med_d"],
                "stall18_n": s["stall18_n"], "stall18_avg_pnl": s["stall18_pnl"],
                "stall18_avg_days": s["stall18_avg_d"], "stall18_med_days": s["stall18_med_d"],
            })
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows = load_closed(CLOSED)
    uw = [t for t in all_rows if t["uw"]]
    qual = [t for t in all_rows if not t["uw"]]
    print(f"closed={len(all_rows)} uw={len(uw)} qualifying={len(qual)}", flush=True)
    symbols = sorted({t["symbol"] for t in qual})
    print(f"loading duckdb symbols={len(symbols)}", flush=True)
    prices = load_prices(symbols)
    print(f"price frames={len(prices)}", flush=True)
    annotate(qual, prices)
    scored = {
        "FULL": score_slice(qual),
        "IS": score_slice([t for t in qual if t["window"] == "IS"]),
        "OOS": score_slice([t for t in qual if t["window"] == "OOS"]),
    }
    write_baseline(len(uw), scored)
    html_path = write_html(len(uw), scored)
    summary = write_summary(scored)
    print(f"wrote {html_path}", flush=True)
    print(f"wrote {summary}", flush=True)
    full = scored["FULL"]
    print(
        f"FULL n={full['n']} +15={full['n15']} +18={full['n18']} +20={full['n20']} "
        f"extra15-20 avg={full['avg_x1520']} med={full['med_x1520']} "
        f"extra18-20 avg={full['avg_x1820']} med={full['med_x1820']}",
        flush=True,
    )
    subprocess.run(
        [
            PY, str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path", str(html_path),
            "-t", "WPBR Day40 survivor path diag",
        ],
        cwd=str(ROOT),
        check=False,
    )


if __name__ == "__main__":
    main()
