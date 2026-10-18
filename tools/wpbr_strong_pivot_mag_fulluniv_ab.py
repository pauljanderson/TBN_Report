"""WPBR full-universe strong-pivot magnitude A/B.

One change: strong_pre_pivot_pct and strong_post_pivot_pct move together.
Control is 10% (production). A is 12.5%, B is 15%, C is 20%.
strong_pivot_mode stays either. Bar counts stay 3.

Research only. Out of sample is report-only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import (  # noqa: E402
    calmar_ratio,
    find_host_equity_curve_csv,
    sharpe_from_equity_curve_csv,
)

STAMP = "20260929"
IS_CUT = "20240101"
IS_DATE = datetime.strptime(IS_CUT, "%Y%m%d").date()
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_strong_pivot_mag_fulluniv_ab_{STAMP}"
RUNS_DIR = ROOT / "tmp_wpbr_pivot_mag_ab_20260929"
# Today's production Control book. Same knobs, including 10% / 10% strong pivots.
CONTROL_SRC = ROOT / "drive" / "paul_experiments" / "wpbr_retest_vs_zone_20260929"
TAG = f"wpbr_strong_pivot_mag_fulluniv_ab_{STAMP}"

# id, label, magnitude as a fraction (both pre and post)
ARMS: list[tuple[str, str, float]] = [
    ("pct10", "Control 10%", 0.10),
    ("pct125", "A 12.5%", 0.125),
    ("pct15", "B 15%", 0.15),
    ("pct20", "C 20%", 0.20),
]

COMMON: dict[str, str] = {
    "wpbr_zones": "true",
    "brt_zones": "false",
    "yh_zones": "false",
    "vec_zones": "false",
    "band_pct": "0.015",
    "strong_pre_pivot_bars": "3",
    "strong_post_pivot_bars": "3",
    "strong_pivot_mode": "either",
    "wpbr_breakout_confirmation": "0.03",
    "wpbr_max_days_after_retest": "2",
    "wpbr_second_chance_after_win": "true",
    "growth_filter_enabled": "false",
    "min_spy_compare_1y_at_trigger": "-1000",
    "ind_score_weights_path": "",
    "too_high_multiplier": "0",
    "target_pct": "1.22",
    "stop_pct": "0.91",
    "stop_loss_based": "trigger_low",
    "stop_pct_is_multiplier": "true",
    "sheet_no_entry_same_bar_after_exit": "false",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
}

REQUEST_PROMPT = """Run a research-only A/B test on WPBR strong-pivot magnitude using the full universe.
Keep the current production WPBR Control completely unchanged except for strong_pre_pivot_pct and strong_post_pivot_pct.
Test:
- Control: 10%
- A: 12.5%
- B: 15%
- C: 20%
For each test, set both strong_pre_pivot_pct and strong_post_pivot_pct to the same tested value.
Keep strong_pivot_mode=either and strong_pre_pivot_bars=3 / strong_post_pivot_bars=3 unchanged. Keep every other WPBR production setting frozen, including the 1.5% zone band, 3% breakout confirmation, 2-day retest window, −9% stop under trigger-day low, +22% target, and second-chance-after-win rule. Growth filter remains OFF.
Run on the full universe.
Report IS / OOS / FULL for each magnitude with:
- Trade count
- Trade-count reduction versus 10% Control
- WR
- Actual average winner
- Actual average loser
- Realized reward/risk
- Avg P&L
- PF
- Expectancy
- Max DD
- Avg days held
- Capital days
- Annual ROR
- Calmar
- Sharpe
- Avg P&L excluding biggest winner
- Trades/year
IS = entries before 2024-01-01. OOS = entries on or after 2024-01-01 and is report-only.
Change only strong-pivot magnitude. Do not change pivot-bar count, pivot mode, entry logic, exit logic, or any other WPBR parameter.
Research only. Not gold. Not DailyRun."""

LAYMAN = (
    "We kept Pivot Break and Retest (WPBR) the same and only asked the weekly pivot to be a bigger move before it can start a zone. "
    "Control is today’s production book: the pivot has to be at least a 10% move, either before the pivot or after it, over 3 bars. "
    "A raises that bar to 12.5%. B raises it to 15%. C raises it to 20%. "
    "A higher bar usually means fewer trades. The question is whether the trades that remain are better. "
    "The stop, target, zone width, breakout confirmation, and retest window stay exactly where production has them. "
    "The stop is still 9% under the low of the trigger day, and the target is still 22% above the buy. "
    "In-sample is a buy before 2024. Out of sample is a buy in 2024 or later, and that side is for reading only. "
    "This is a research test, not a live-system change."
)


def _notify(py: str, paths: list[Path], message: str) -> None:
    cmd = [py, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR pivot magnitude"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def _latest(folder: Path, needle: str) -> Path:
    hits = sorted(folder.glob(f"WPBR_{needle}_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no WPBR_{needle} in {folder}")
    return hits[-1]


def _has_closed(folder: Path) -> bool:
    return folder.is_dir() and any(folder.glob("WPBR_Closed_*.csv"))


def run_fresh(py: str, arm_id: str, magnitude: float, workers: int) -> Path:
    out = RUNS_DIR / arm_id
    if _has_closed(out):
        print(f"[{TAG}] reuse {arm_id}", flush=True)
        return out
    if out.exists():
        for attempt in range(8):
            try:
                shutil.rmtree(out)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(2)
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        py, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(workers), "--aggressive", "--use-duckdb", "--no-regression",
    ]
    knobs = dict(COMMON)
    text = f"{magnitude:.3f}"
    knobs["strong_pre_pivot_pct"] = text
    knobs["strong_post_pivot_pct"] = text
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    print(f"[{TAG}] start {arm_id} strong_pre/post_pivot_pct={text}", flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"{arm_id} exited {proc.returncode}")
    print(f"[{TAG}] done {arm_id}", flush=True)
    return out


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


def _load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = str(raw.get("DATE_OPENED") or "").strip()
            if len(opened) < 8:
                continue
            opened = opened[:8]
            closed = str(raw.get("DATE_CLOSED") or "").strip()
            closed = closed[:8] if len(closed) >= 8 else ""
            rows.append(
                {
                    "opened": opened,
                    "closed": closed,
                    "pnl": _f(raw.get("PNL_PCT")),
                    "days": _f(raw.get("DAYS_HELD"), 0.0),
                    "pnl_d": _f(raw.get("PNL_DOLLARS"), 0.0),
                }
            )
    return rows


def _split(trades: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [t for t in trades if t["opened"] < IS_CUT]
    if which == "OOS":
        return [t for t in trades if t["opened"] >= IS_CUT]
    return list(trades)


def _report_cash(folder: Path) -> float:
    path = _latest(folder, "Report")
    with path.open(newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    cash = _f(row.get("capacity_brt_cash"))
    if not math.isfinite(cash) or cash <= 0:
        raise RuntimeError(f"missing capacity_brt_cash in {path}")
    return cash


def _curve_path(folder: Path) -> Path | None:
    found = find_host_equity_curve_csv(folder)
    return Path(found) if found else None


def _parse_date(text: str):
    raw = str(text or "").strip()
    if not raw:
        return None
    compact = raw.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((raw[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (raw[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _equity_max_dd(path: Path | None, which: str) -> float:
    """Peak-to-trough on Equity_Regular, the same series as the engine Max DD."""
    if path is None or not path.is_file():
        return float("nan")
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return float("nan")
    col = "Equity_Regular" if any((r.get("Equity_Regular") or "").strip() for r in rows) else "Equity"
    peak = None
    worst = 0.0
    seen = 0
    for row in rows:
        day = _parse_date(row.get("Date") or row.get("date") or "")
        if day is None:
            continue
        if which == "IS" and day >= IS_DATE:
            continue
        if which == "OOS" and day < IS_DATE:
            continue
        value = _f(row.get(col) or "")
        if not math.isfinite(value) or value <= 0:
            continue
        seen += 1
        if peak is None or value > peak:
            peak = value
        if peak:
            drop = (peak - value) / peak * 100.0
            if drop > worst:
                worst = drop
    return worst if seen else float("nan")


def _ann_ror(total_pnl: float, n: int, avg_days: float, cash: float) -> float:
    if n <= 0 or avg_days <= 0 or cash <= 0:
        return float("nan")
    base = 1.0 + total_pnl / (cash * n)
    if base <= 0:
        return float("nan")
    return (base ** (365.0 / avg_days) - 1.0) * 100.0


def _metrics(trades: list[dict[str, Any]], cash: float, curve: Path | None, which: str) -> dict[str, Any]:
    empty = {
        "n": 0, "wr": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "rr": float("nan"), "avg_pnl": float("nan"), "pf": float("nan"),
        "expectancy": float("nan"), "max_dd": float("nan"), "ann_ror": float("nan"),
        "calmar": float("nan"), "sharpe": float("nan"), "avg_days": float("nan"),
        "cap_days": 0.0, "wo_max": float("nan"), "tpy": float("nan"),
    }
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    if n == 0:
        return empty
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg_win = sum(wins) / len(wins) if wins else float("nan")
    avg_loss = sum(losses) / len(losses) if losses else float("nan")
    avg_pnl = sum(pnls) / n
    # Win rate times average winner, plus loss rate times average loser.
    # Breakeven trades sit in the count and pull this toward the average.
    wr_unit = len(wins) / n
    lr_unit = len(losses) / n
    expectancy = 0.0
    if wins:
        expectancy += wr_unit * avg_win
    if losses:
        expectancy += lr_unit * avg_loss
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else float("nan")
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    avg_days = (sum(days) / len(days)) if days else float("nan")
    total_d = sum(t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"]))
    ann = _ann_ror(total_d, n, avg_days if math.isfinite(avg_days) else 0.0, cash)
    dd = _equity_max_dd(curve, which)
    cal = calmar_ratio(ann, dd) if calmar_ratio else None
    if which == "IS":
        sharpe = sharpe_from_equity_curve_csv(curve, end_date_exclusive=IS_DATE)
    elif which == "OOS":
        sharpe = sharpe_from_equity_curve_csv(curve, start_date=IS_DATE)
    else:
        sharpe = sharpe_from_equity_curve_csv(curve)
    opens = []
    closes = []
    for t in trades:
        try:
            opens.append(datetime.strptime(t["opened"], "%Y%m%d").date())
            if t["closed"]:
                closes.append(datetime.strptime(t["closed"], "%Y%m%d").date())
        except ValueError:
            continue
    span = ((max(closes) - min(opens)).days / 365.25) if opens and closes else 0.0
    return {
        "n": n,
        "wr": 100.0 * len(wins) / n,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "rr": (avg_win / abs(avg_loss)) if wins and losses and avg_loss else float("nan"),
        "avg_pnl": avg_pnl,
        "pf": (gp / gl) if gl > 0 else float("nan"),
        "expectancy": expectancy,
        "max_dd": dd,
        "ann_ror": ann,
        "calmar": float(cal) if cal is not None else float("nan"),
        "sharpe": float(sharpe) if isinstance(sharpe, (int, float)) else float("nan"),
        "avg_days": avg_days,
        "cap_days": float(sum(days)) if days else 0.0,
        "wo_max": wo,
        "tpy": (n / span) if span > 0 else float("nan"),
    }


def _pct(v: float, digits: int = 2) -> str:
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return ""
    return f"{v:.{digits}f}%"


def _num(v: float, digits: int = 2) -> str:
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return ""
    return f"{v:,.{digits}f}"


def _int(v: float) -> str:
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return ""
    return f"{int(round(v)):,}"


def _signed_int(v: float) -> str:
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return ""
    n = int(round(v))
    return f"{n:+,}"


def _th(headers: list[tuple[str, str]]) -> str:
    return "".join(sortable_th(label, kind) for label, kind in headers)


def _cells(vals: list[str]) -> str:
    return "".join(f"<td>{html_mod.escape(v)}</td>" for v in vals)


def _row(book: dict[str, Any], name: str, control_n: int) -> list[str]:
    m = book["slices"][name]
    reduction = control_n - m["n"]
    return [
        book["label"],
        name,
        _int(m["n"]),
        _signed_int(reduction),
        _pct(100.0 * reduction / control_n, 1) if control_n else "",
        _pct(m["wr"], 1),
        _pct(m["avg_win"]),
        _pct(m["avg_loss"]),
        _num(m["rr"], 2),
        _pct(m["avg_pnl"]),
        _num(m["pf"], 2),
        _pct(m["expectancy"]),
        _pct(m["max_dd"]),
        _num(m["avg_days"], 1),
        _int(m["cap_days"]),
        _pct(m["ann_ror"]),
        _num(m["calmar"], 2),
        _num(m["sharpe"], 2),
        _pct(m["wo_max"]),
        _num(m["tpy"], 1),
    ]


PRIMARY = [
    ("Test", "text"), ("Slice", "text"), ("Trades", "num"),
    ("Fewer trades vs 10%", "num"), ("Fewer vs 10%", "num"),
    ("WR", "num"), ("Avg winner", "num"), ("Avg loser", "num"),
    ("Realized R/R", "num"), ("Avg P&L", "num"), ("PF", "num"),
    ("Expectancy", "num"), ("Max DD", "num"), ("Avg days", "num"),
    ("Capital days", "num"), ("Ann ROR", "num"), ("Calmar", "num"),
    ("Sharpe", "num"), ("Avg P&L ex biggest winner", "num"), ("Trades / year", "num"),
]


def write_html(books: list[dict[str, Any]]) -> Path:
    by_id = {b["id"]: b for b in books}
    control = by_id["pct10"]
    rows = []
    for book in books:
        for name in ("IS", "OOS", "FULL"):
            rows.append("<tr>" + _cells(_row(book, name, control["slices"][name]["n"])) + "</tr>")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR strong-pivot magnitude 10% / 12.5% / 15% / 20%</title>
<style>
:root{{--bg:#0f1419;--card:#1a2332;--text:#e7ecf3;--muted:#8b9bb4;--line:#2a384d;--accent:#7eb6ff}}
body{{margin:0;font-family:Segoe UI,system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1400px;margin:0 auto;padding:1rem 1.25rem}}
h1{{font-size:1.35rem;margin:0 0 .4rem}} h2{{font-size:1.05rem;margin:1.2rem 0 .4rem}}
.muted{{color:var(--muted)}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:0 0 1rem}}
.callout pre{{white-space:pre-wrap;font-family:inherit;margin:.4rem 0 0}}
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:0 0 1rem}}
table{{border-collapse:collapse;width:100%;font-size:.8rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
{SORTABLE_TH_CSS}
</style></head><body>
<header>
<h1>WPBR full universe — strong-pivot magnitude 10%, 12.5%, 15%, 20%</h1>
<p class="muted">Stamp <code>{TAG}</code>. Research only. Not gold. Not DailyRun. Click a column header to sort.</p>
</header>
<main>
<div class="callout">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {html_mod.escape(LAYMAN)}</p>
</div>
<div class="callout">
<p>One change: how large a pivot must be. Production uses either side, over 3 bars. Control keeps both the before-pivot and after-pivot thresholds at 10%. A sets both to 12.5%. B sets both to 15%. C sets both to 20%. Nothing else moves. The zone band stays 1.5%. Breakout confirmation stays 3%. The retest window stays 2 days. The stop stays 9% under the trigger-day low (stop multiplier 0.91 on that low). The target stays 22% above the entry (1.22 times the entry). Second chance after a win stays on. The growth filter stays off. Overlapping zones are not merged. The book is every daily file under data/newdata/data.</p>
<p>In-sample (IS) is an entry before 2024-01-01. Out of sample (OOS) is an entry on or after that date. Judge the change on IS. OOS is for reading. Do not pick a magnitude because OOS looks better. Choosing among these four after seeing this table is an in-sample choice.</p>
<p>“Fewer trades vs 10%” is the Control trade count minus this book’s trade count, on the same slice. A positive number is fewer trades. “Fewer vs 10%” is that drop as a percent of the Control count. Win rate (WR) is winners divided by all trades. Realized reward/risk is the average winner divided by the absolute average loser. Profit factor (PF) is the sum of winning percents divided by the absolute sum of losing percents. Expectancy is win rate times the average winner, plus loss rate times the average loser. Average P&amp;L is the plain average of every trade, including breakevens. Average P&amp;L excluding the biggest winner drops the single largest percent trade, then averages the rest.</p>
<p>Annual rate of return (Ann ROR) uses the production book formula on that entry slice: compound the slice’s dollar profits with that book’s capacity cash and 365 days. Max drawdown (Max DD) and Sharpe are the daily regular equity curve. The full book matches the engine report. IS and OOS cut that same curve at 2024-01-01, so those two risk numbers follow the calendar, while the trade counts follow the entry date. Calmar is Ann ROR divided by the absolute Max DD. Capital days is the sum of days held. Trades per year uses the first entry and the last exit in the slice.</p>
</div>
<section><h2>IS / OOS / full book</h2>
<p class="muted">Click a column header to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{_th(PRIMARY)}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_csv(books: list[dict[str, Any]]) -> None:
    path = OUT_DIR / "metrics_all.csv"
    fields = [
        "arm", "label", "magnitude", "slice", "trades", "fewer_vs_control", "fewer_vs_control_pct",
        "wr", "avg_winner", "avg_loser", "realized_rr", "avg_pnl", "pf", "expectancy",
        "max_dd", "avg_days", "capital_days", "ann_ror", "calmar", "sharpe",
        "avg_pnl_wo_max", "trades_per_year", "capacity_cash",
    ]
    control = {b["id"]: b for b in books}["pct10"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for book in books:
            for name in ("IS", "OOS", "FULL"):
                m = book["slices"][name]
                base_n = control["slices"][name]["n"]
                fewer = base_n - m["n"]
                w.writerow(
                    {
                        "arm": book["id"],
                        "label": book["label"],
                        "magnitude": f"{book['magnitude']:.3f}",
                        "slice": name,
                        "trades": m["n"],
                        "fewer_vs_control": fewer,
                        "fewer_vs_control_pct": (100.0 * fewer / base_n) if base_n else "",
                        "wr": m["wr"],
                        "avg_winner": m["avg_win"],
                        "avg_loser": m["avg_loss"],
                        "realized_rr": m["rr"],
                        "avg_pnl": m["avg_pnl"],
                        "pf": m["pf"],
                        "expectancy": m["expectancy"],
                        "max_dd": m["max_dd"],
                        "avg_days": m["avg_days"],
                        "capital_days": m["cap_days"],
                        "ann_ror": m["ann_ror"],
                        "calmar": m["calmar"],
                        "sharpe": m["sharpe"],
                        "avg_pnl_wo_max": m["wo_max"],
                        "trades_per_year": m["tpy"],
                        "capacity_cash": book["cash"],
                    }
                )


def write_baseline(books: list[dict[str, Any]], html_path: Path) -> None:
    lines = [
        f"# BASELINE — `{TAG}`",
        "",
        "**Status:** RESEARCH only. One change: strong-pivot magnitude. Full universe. Not gold. Not DailyRun.",
        "",
        "Control is the 2026-09-29 production full-universe book at 10% / 10%.",
        "A, B, and C are fresh runs. Each sets both `strong_pre_pivot_pct` and `strong_post_pivot_pct` to the same value: 0.125, 0.15, or 0.20.",
        "They move together because production uses one magnitude and the request tests that magnitude, not two separate knobs.",
        "`strong_pivot_mode=either`. `strong_pre_pivot_bars=3`. `strong_post_pivot_bars=3`.",
        "Frozen with Control: band 0.015, breakout confirmation 0.03, retest window 2,",
        "stop 0.91 under the trigger-day low (`stop_loss_based=trigger_low`, multiplier), target 1.22,",
        "second chance after a win on, growth filter off, overlapping zones not merged.",
        "",
        "IS = entry date before 2024-01-01. OOS = entry date on or after 2024-01-01. OOS is report-only.",
        "Picking a magnitude from this table is in-sample selection. Do not retune on OOS.",
        "",
        "Max DD and Sharpe use the daily regular equity curve. The full book matches the engine report.",
        "IS and OOS cut that curve on the calendar at 2024-01-01. Trade counts follow the entry date.",
        "Ann ROR uses the production formula with that book’s `capacity_brt_cash`.",
        "Realized reward/risk = average winner / absolute average loser.",
        "Expectancy = win rate × average winner + loss rate × average loser.",
        "",
        "## What you asked",
        "",
        "```",
        REQUEST_PROMPT.strip(),
        "```",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Split snapshot",
        "",
    ]
    control = {b["id"]: b for b in books}["pct10"]
    for book in books:
        for name in ("IS", "OOS", "FULL"):
            m = book["slices"][name]
            base = control["slices"][name]["n"]
            fewer = base - m["n"]
            lines.append(
                f"- **{book['label']} {name}:** N={m['n']} fewer vs 10%={fewer} "
                f"WR={m['wr']:.1f}% avg win={m['avg_win']:.2f}% avg loss={m['avg_loss']:.2f}% "
                f"R/R={m['rr']:.2f} avg={m['avg_pnl']:.2f}% PF={m['pf']:.2f} "
                f"MaxDD={m['max_dd']:.2f}% AnnROR={m['ann_ror']:.2f}% "
                f"days={m['avg_days']:.1f} cap days={m['cap_days']:.0f}"
            )
    lines.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _arm_folder(arm_id: str) -> Path:
    if arm_id == "pct10" and _has_closed(CONTROL_SRC):
        return CONTROL_SRC
    return RUNS_DIR / arm_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    try:
        if not args.summarize_only:
            for aid, _label, mag in ARMS:
                if aid == "pct10" and _has_closed(CONTROL_SRC):
                    print(f"[{TAG}] reuse Control from {CONTROL_SRC}", flush=True)
                    continue
                run_fresh(py, aid, mag, args.workers)
        books = []
        for aid, label, mag in ARMS:
            folder = _arm_folder(aid)
            if not _has_closed(folder):
                raise FileNotFoundError(f"missing closed book for {aid} in {folder}")
            trades = _load(_latest(folder, "Closed"))
            cash = _report_cash(folder)
            curve = _curve_path(folder)
            books.append(
                {
                    "id": aid,
                    "label": label,
                    "magnitude": mag,
                    "cash": cash,
                    "slices": {
                        name: _metrics(_split(trades, name), cash, curve, name)
                        for name in ("IS", "OOS", "FULL")
                    },
                }
            )
        write_csv(books)
        html_path = write_html(books)
        write_baseline(books, html_path)
    except Exception as exc:
        path = OUT_DIR / "compare.html"
        path.write_text(
            "<!DOCTYPE html><html><body><h1>WPBR strong-pivot magnitude test did not finish</h1>"
            "<h2>What you asked</h2>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p><strong>In plain English.</strong> {html_mod.escape(LAYMAN)}</p>"
            f"<pre>{html_mod.escape(str(exc))}</pre></body></html>",
            encoding="utf-8",
        )
        _notify(py, [path], f"WPBR pivot magnitude test failed: {exc}")
        print(f"[{TAG}] FAIL {exc}", flush=True)
        return 1
    control = {b["id"]: b for b in books}["pct10"]
    for book in books:
        full = book["slices"]["FULL"]
        fewer = control["slices"]["FULL"]["n"] - full["n"]
        print(
            f"[{TAG}] {book['label']} FULL N={full['n']} fewer={fewer} WR={full['wr']:.1f} "
            f"avg={full['avg_pnl']:.2f} PF={full['pf']:.2f} MaxDD={full['max_dd']:.2f}",
            flush=True,
        )
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    _notify(
        py,
        [html_path],
        "WPBR strong-pivot magnitude: Control 10%, A 12.5%, B 15%, C 20%.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
