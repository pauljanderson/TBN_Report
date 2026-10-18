"""WPBR full-universe stop tightness A/B. One knob: stop_pct.

Control is the 2026-09-27 full-universe book (stop 0.91, 9% under the
trigger-day low). A/B/C rerun the same rules at 0.92 / 0.93 / 0.94.

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
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import calmar_ratio, overlay_ann_ror_max_dd  # noqa: E402

STAMP = "20260928"
IS_CUT = "20240101"
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_stop_9_8_7_6_fulluniv_ab_{STAMP}"
# Engine files stay outside Drive. Drive locks new folders while it syncs.
RUNS_DIR = ROOT / "tmp_wpbr_stop_ab_20260928"
TAG = f"wpbr_stop_9_8_7_6_fulluniv_ab_{STAMP}"

# stop_pct is a multiplier on the trigger-day low. 0.91 means 9% under that low.
# All four arms are fresh runs so they share one universe. Knobs match run_wpbr.bat
# and the 2026-09-27 full-universe report, except the stop.
ARMS: list[tuple[str, str, float]] = [
    ("stop09", "Control −9%", 0.91),
    ("stop08", "A −8%", 0.92),
    ("stop07", "B −7%", 0.93),
    ("stop06", "C −6%", 0.94),
]

COMMON: dict[str, str] = {
    "wpbr_zones": "true",
    "brt_zones": "false",
    "yh_zones": "false",
    "vec_zones": "false",
    "band_pct": "0.015",
    "strong_pre_pivot_bars": "3",
    "strong_pre_pivot_pct": "0.10",
    "strong_post_pivot_bars": "3",
    "strong_post_pivot_pct": "0.10",
    "strong_pivot_mode": "either",
    "wpbr_breakout_confirmation": "0.03",
    "wpbr_max_days_after_retest": "2",
    "wpbr_second_chance_after_win": "true",
    "growth_filter_enabled": "false",
    "min_spy_compare_1y_at_trigger": "-1000",
    "ind_score_weights_path": "ind_score_weights_260609152353.json",
    "too_high_multiplier": "0",
    "target_pct": "1.22",
    "stop_loss_based": "trigger_low",
    "stop_pct_is_multiplier": "true",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
    "sheet_no_entry_same_bar_after_exit": "false",
}

REQUEST_PROMPT = """using the full universe run these stop A/B tests:
Test  Stop
Control  −9%
A  −8%
B  −7%
C  −6%

Have the report show IS / OOS / FULL for each stop with: trade count, WR, actual avg winner, actual avg loser, realized reward/risk, Avg P&L, PF, expectancy, Max DD, Avg days held, and capital days.
Also have it report gap-loss exits separately, because tightening the nominal stop may not reduce realized losses proportionally when stocks gap through it. compare and closed reports"""

LAYMAN = (
    "We kept the Pivot Break and Retest (WPBR) rules the same and only moved the stop. "
    "The stop sits under the low of the trigger day (the day before the buy), not under the buy price. "
    "Control is 9% under that low, which is the production stop. A is 8% under, B is 7%, and C is 6%. "
    "A tighter stop can cut a slow loser sooner. It does not help when the stock opens the next day "
    "already through the stop: you sell at that open, and the loss can be larger than the printed stop. "
    "Those gap sales are counted in their own table. In-sample is before 2024. Out of sample is 2024 onward "
    "and is for reading only. This is a research test, not a live-system change."
)

SHOW = [
    ("SYMBOL", "Symbol", "text"),
    ("SIDE", "Side", "text"),
    ("DATE_OPENED", "Opened", "date"),
    ("DATE_CLOSED", "Closed", "date"),
    ("ENTRY_PRICE", "Entry", "num"),
    ("EXIT_PRICE", "Exit px", "num"),
    ("PNL_PCT", "P&L %", "num"),
    ("DAYS_HELD", "Days", "num"),
    ("EXIT_TYPE", "Exit", "text"),
    ("STOP_PRICE", "Stop", "num"),
    ("TARGET_PRICE", "Target", "num"),
]


def _notify(py: str, paths: list[Path], message: str) -> None:
    cmd = [py, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR stop 9/8/7/6"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def _latest(folder: Path, needle: str) -> Path:
    hits = sorted(folder.glob(f"WPBR_{needle}_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no WPBR_{needle} in {folder}")
    return hits[-1]


def run_fresh(py: str, arm_id: str, stop: float, workers: int) -> Path:
    out = RUNS_DIR / arm_id
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
        py, str(ROOT / "stock_analysis" / "rocket_tbn.py"), str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(workers), "--aggressive", "--use-duckdb", "--no-regression",
    ]
    knobs = dict(COMMON)
    knobs["stop_pct"] = f"{stop:.2f}"
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    print(f"[{TAG}] start {arm_id} stop_pct={stop:.2f}", flush=True)
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
            opened = str(raw.get("DATE_OPENED") or raw.get("DATE OPENED") or "").strip()
            if len(opened) < 8:
                continue
            opened = opened[:8]
            closed = str(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED") or "").strip()
            closed = closed[:8] if len(closed) >= 8 else ""
            rows.append(
                {
                    "opened": opened,
                    "closed": closed,
                    "pnl": _f(raw.get("PNL_PCT") or raw.get("PNL %")),
                    "days": _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD"), 0.0),
                    "pnl_d": _f(raw.get("PNL_DOLLARS"), 0.0),
                    "exit": str(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip().upper(),
                    "entry": _f(raw.get("ENTRY_PRICE")),
                    "stop": _f(raw.get("STOP_PRICE")),
                }
            )
    return rows


def _split(trades: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [t for t in trades if t["opened"] < IS_CUT]
    if which == "OOS":
        return [t for t in trades if t["opened"] >= IS_CUT]
    return list(trades)


def _metrics(trades: list[dict[str, Any]], nominal: float) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0, "wr": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "rr": float("nan"), "avg_pnl": float("nan"), "pf": float("nan"),
        "expectancy": float("nan"), "max_dd": float("nan"), "ann_ror": float("nan"),
        "calmar": float("nan"), "sharpe": float("nan"), "avg_days": float("nan"),
        "cap_days": 0.0, "wo_max": float("nan"), "tpy": float("nan"), "exits": {},
        "gap_n": 0, "gap_avg": float("nan"), "gap_sum": 0.0,
        "stop_n": 0, "stop_avg": float("nan"), "stop_sum": 0.0,
        "gap_share_exits": float("nan"), "gap_share_loss": float("nan"),
        "loss_dollars": 0.0,
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg_win = sum(wins) / len(wins) if wins else float("nan")
    avg_loss = sum(losses) / len(losses) if losses else float("nan")
    mx = max(pnls) if pnls else float("nan")
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 and math.isfinite(mx) else float("nan")
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    parsed = []
    for t in trades:
        try:
            opened_d = datetime.strptime(t["opened"], "%Y%m%d").date()
            closed_d = datetime.strptime(t["closed"], "%Y%m%d").date() if t["closed"] else opened_d
        except ValueError:
            continue
        parsed.append({**t, "opened": opened_d, "closed": closed_d})
    cap = overlay_ann_ror_max_dd(parsed, cash=10_000.0)
    opens = [t["opened"] for t in parsed]
    closes = [t["closed"] for t in parsed]
    span = ((max(closes) - min(opens)).days / 365.25) if opens else 0.0
    gaps = [t["pnl"] for t in trades if t["exit"] == "GAP_DOWN" and math.isfinite(t["pnl"])]
    stops = [t["pnl"] for t in trades if t["exit"] == "STOP_LOSS" and math.isfinite(t["pnl"])]
    gap_sum = sum(gaps)
    stop_sum = sum(stops)
    loss_dollars = abs(sum(p for p in pnls if p < 0))
    gap_loss = abs(sum(p for p in gaps if p < 0))
    stop_related = len(gaps) + len(stops)
    ann = cap["ann_ror"]
    dd = cap["max_dd"]
    cal = calmar_ratio(ann, dd) if calmar_ratio else float("nan")
    return {
        "n": n,
        "wr": 100.0 * len(wins) / n if n else float("nan"),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "rr": (avg_win / abs(avg_loss)) if wins and losses and avg_loss else float("nan"),
        "avg_pnl": sum(pnls) / n if n else float("nan"),
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "expectancy": sum(pnls) / n if n else float("nan"),
        "max_dd": dd,
        "ann_ror": ann,
        "calmar": cal if cal is not None else float("nan"),
        "sharpe": float(cap["sharpe"]) if isinstance(cap.get("sharpe"), (int, float)) else float("nan"),
        "avg_days": (sum(days) / len(days)) if days else float("nan"),
        "cap_days": float(sum(days)) if days else 0.0,
        "wo_max": wo,
        "tpy": (n / span) if span and span > 0 else float("nan"),
        "exits": dict(Counter(t["exit"] or "?" for t in trades)),
        "gap_n": len(gaps),
        "gap_avg": (sum(gaps) / len(gaps)) if gaps else float("nan"),
        "gap_sum": gap_sum,
        "stop_n": len(stops),
        "stop_avg": (sum(stops) / len(stops)) if stops else float("nan"),
        "stop_sum": stop_sum,
        "gap_share_exits": (100.0 * len(gaps) / stop_related) if stop_related else float("nan"),
        "gap_share_loss": (100.0 * gap_loss / loss_dollars) if loss_dollars else float("nan"),
        "loss_dollars": loss_dollars,
        "nominal": nominal,
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


def _th(headers: list[tuple[str, str]]) -> str:
    return "".join(sortable_th(label, kind) for label, kind in headers)


def _cells(vals: list[str]) -> str:
    return "".join(f"<td>{html_mod.escape(v)}</td>" for v in vals)


def write_closed_html(closed_path: Path, dest: Path, title: str, note: str) -> Path:
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    headers = _th([(label, kind) for _key, label, kind in SHOW])
    body = []
    for raw in rows:
        vals = []
        for key, _label, kind in SHOW:
            v = str(raw.get(key) or "").strip()
            if kind == "num" and v:
                num = _f(v)
                v = _num(num, 2) if math.isfinite(num) else v
            elif key.startswith("DATE") and len(v) >= 8 and v[:8].isdigit():
                v = f"{v[:4]}-{v[4:6]}-{v[6:8]}"
            vals.append(v)
        body.append(f"<tr>{_cells(vals)}</tr>")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(title)}</title>
<style>
:root{{--bg:#0f1419;--card:#1a2332;--text:#e7ecf3;--muted:#8b9bb4;--line:#2a384d;--accent:#7eb6ff}}
body{{margin:0;font-family:Segoe UI,system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1200px;margin:0 auto;padding:1rem 1.25rem}}
h1{{font-size:1.25rem;margin:0 0 .4rem}} .muted{{color:var(--muted)}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:0 0 1rem}}
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:.82rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS}
</style></head><body>
<header><h1>{html_mod.escape(title)}</h1>
<p class="muted">{len(rows):,} closed trades. Click a column header to sort.</p></header>
<main>
<div class="callout"><p>{html_mod.escape(note)}</p>
<p class="muted">Gap-through-stop sales are labeled GAP_DOWN. A normal stop touch is STOP_LOSS. Sort the Exit column to see them together.</p></div>
<div class="table-wrap"><table class="sortable"><thead><tr>{headers}</tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    dest.write_text(html, encoding="utf-8")
    return dest


def write_html(
    books: list[dict[str, Any]],
    closed_pages: list[Path],
) -> Path:
    primary = [
        ("Test", "text"), ("Stop", "text"), ("Slice", "text"), ("Trades", "num"),
        ("WR", "num"), ("Avg winner", "num"), ("Avg loser", "num"),
        ("Realized R/R", "num"), ("Avg P&L", "num"), ("PF", "num"),
        ("Expectancy", "num"), ("Max DD", "num"), ("Avg days", "num"),
        ("Capital days", "num"),
    ]
    gap_h = [
        ("Test", "text"), ("Stop", "text"), ("Slice", "text"),
        ("Gap-loss exits", "num"), ("Gap % of trades", "num"), ("Gap avg P&L", "num"),
        ("Stop-touch exits", "num"), ("Stop-touch avg P&L", "num"),
        ("Gaps as % of gap+stop exits", "num"), ("Gaps as % of losing P&L", "num"),
        ("Printed stop", "text"),
    ]
    extra_h = [
        ("Test", "text"), ("Slice", "text"), ("Ann ROR", "num"), ("Calmar", "num"),
        ("Sharpe", "num"), ("Avg P&L without biggest winner", "num"), ("Trades / year", "num"),
    ]
    prim_rows, gap_rows, extra_rows, exit_rows = [], [], [], []
    exit_names = sorted({k for b in books for name, m in b["slices"].items() if name == "FULL" for k in m["exits"]})
    for b in books:
        for name in ("IS", "OOS", "FULL"):
            m = b["slices"][name]
            prim_rows.append(
                "<tr>"
                + _cells(
                    [
                        b["label"],
                        b["stop_label"],
                        name,
                        _int(m["n"]),
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
                    ]
                )
                + "</tr>"
            )
            gap_pct = (100.0 * m["gap_n"] / m["n"]) if m["n"] else float("nan")
            gap_rows.append(
                "<tr>"
                + _cells(
                    [
                        b["label"],
                        b["stop_label"],
                        name,
                        _int(m["gap_n"]),
                        _pct(gap_pct, 1),
                        _pct(m["gap_avg"]),
                        _int(m["stop_n"]),
                        _pct(m["stop_avg"]),
                        _pct(m["gap_share_exits"], 1),
                        _pct(m["gap_share_loss"], 1),
                        b["stop_label"],
                    ]
                )
                + "</tr>"
            )
            extra_rows.append(
                "<tr>"
                + _cells(
                    [
                        b["label"],
                        name,
                        _pct(m["ann_ror"]),
                        _num(m["calmar"], 2),
                        _num(m["sharpe"], 2),
                        _pct(m["wo_max"]),
                        _num(m["tpy"], 1),
                    ]
                )
                + "</tr>"
            )
        full = b["slices"]["FULL"]
        exit_rows.append(
            "<tr>"
            + _cells([b["label"]] + [_int(full["exits"].get(k, 0)) for k in exit_names])
            + "</tr>"
        )
    links = "".join(
        f'<li><a href="{html_mod.escape(p.name)}">{html_mod.escape(p.stem)}</a></li>'
        for p in closed_pages
    )
    exit_head = sortable_th("Test", "text") + "".join(sortable_th(k, "num") for k in exit_names)
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR stop −9% / −8% / −7% / −6%</title>
<style>
:root{{--bg:#0f1419;--card:#1a2332;--text:#e7ecf3;--muted:#8b9bb4;--line:#2a384d;--accent:#7eb6ff}}
body{{margin:0;font-family:Segoe UI,system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1280px;margin:0 auto;padding:1rem 1.25rem}}
h1{{font-size:1.35rem;margin:0 0 .4rem}} h2{{font-size:1.05rem;margin:1.2rem 0 .4rem}}
.muted{{color:var(--muted)}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:0 0 1rem}}
.callout pre{{white-space:pre-wrap;font-family:inherit;margin:.4rem 0 0}}
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:0 0 1rem}}
table{{border-collapse:collapse;width:100%;font-size:.82rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
a{{color:var(--accent)}}
{SORTABLE_TH_CSS}
</style></head><body>
<header>
<h1>WPBR full universe — stop 9%, 8%, 7%, 6% under the trigger low</h1>
<p class="muted">Stamp <code>{TAG}</code>. Research only. Not gold. Not DailyRun.</p>
</header>
<main>
<div class="callout">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN)}</p>
</div>
<div class="callout">
<p>One change only: how far under the trigger-day low the stop sits. Production anchor is that low, times the stop multiplier. Control is 0.91 (9% under). A is 0.92 (8%). B is 0.93 (7%). C is 0.94 (6%). Year-high, breakout-retest, and volume-profile zone modes are off. The zone band is 1.5%. Strong pivots are 3 bars and 10% on either side. Breakout confirmation stays 3%, the retest window stays 2 days, the target stays 1.22 times entry, and the second-chance-after-a-win rule stays on. Overlapping zones are not merged. All four books were run the same day on the same full daily-file universe.</p>
<p>In-sample (IS) is an entry before 2024-01-01. Out of sample (OOS) is an entry on or after that date. OOS is for reading. Do not pick a stop because OOS looks better. Choosing among these four after seeing the table is an in-sample choice.</p>
<p>Realized reward/risk is the actual average winner divided by the absolute value of the actual average loser. Expectancy is the average percent profit per trade (the same number as Avg P&amp;L). Max drawdown (Max DD) is a closed-trade equity replay on that slice, so IS, OOS, and the full book use the same method. Capital days is the sum of days held. A gap-loss exit is a long sale labeled GAP_DOWN: the stock opened through the stop. STOP_LOSS is a stop that was touched without that gap.</p>
</div>
<div class="callout"><strong>Closed-trade pages</strong><ul>{links}</ul>
<p class="muted">Click a column header to sort. On a closed page, sort Exit to pull GAP_DOWN together.</p></div>
<section><h2>IS / OOS / full book</h2>
<p class="muted">Click a column header to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{_th(primary)}</tr></thead>
<tbody>{''.join(prim_rows)}</tbody></table></div></section>
<section><h2>Gap-loss exits, separate from stop touches</h2>
<p class="muted">A tighter printed stop does not change a sale that already opened through it. Compare the gap average with the stop-touch average. If those two stay far apart, the tighter stop is mostly changing the slow losers, not the gaps.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{_th(gap_h)}</tr></thead>
<tbody>{''.join(gap_rows)}</tbody></table></div></section>
<section><h2>Other book measures</h2>
<p class="muted">Annual rate of return (Ann ROR), Calmar, and Sharpe use the same closed-trade replay. Total dollar profit and sheet dollar profit are left off this page.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{_th(extra_h)}</tr></thead>
<tbody>{''.join(extra_rows)}</tbody></table></div></section>
<section><h2>How the full book ended</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>{exit_head}</tr></thead>
<tbody>{''.join(exit_rows)}</tbody></table></div></section>
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
        "arm", "label", "stop_pct", "slice", "trades", "wr", "avg_winner", "avg_loser",
        "realized_rr", "avg_pnl", "pf", "expectancy", "max_dd", "avg_days", "capital_days",
        "gap_n", "gap_avg", "stop_n", "stop_avg", "gap_share_of_gap_plus_stop",
        "gap_share_of_losing_pnl", "ann_ror", "calmar", "sharpe", "avg_pnl_wo_max", "trades_per_year",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b in books:
            for name in ("IS", "OOS", "FULL"):
                m = b["slices"][name]
                w.writerow(
                    {
                        "arm": b["id"],
                        "label": b["label"],
                        "stop_pct": f"{b['stop']:.2f}",
                        "slice": name,
                        "trades": m["n"],
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
                        "gap_n": m["gap_n"],
                        "gap_avg": m["gap_avg"],
                        "stop_n": m["stop_n"],
                        "stop_avg": m["stop_avg"],
                        "gap_share_of_gap_plus_stop": m["gap_share_exits"],
                        "gap_share_of_losing_pnl": m["gap_share_loss"],
                        "ann_ror": m["ann_ror"],
                        "calmar": m["calmar"],
                        "sharpe": m["sharpe"],
                        "avg_pnl_wo_max": m["wo_max"],
                        "trades_per_year": m["tpy"],
                    }
                )


def write_baseline(books: list[dict[str, Any]], html_path: Path) -> None:
    lines = [
        f"# BASELINE — `{TAG}`",
        "",
        "**Status:** RESEARCH only. One knob: `stop_pct` on the trigger-day low. Full universe. Not gold. Not DailyRun.",
        "",
        "All four arms are fresh runs on the same day. Control is `stop_pct=0.91`. A/B/C are 0.92, 0.93, and 0.94.",
        "Other knobs match `run_wpbr.bat` and the 2026-09-27 full-universe report:",
        "WPBR zones on, year-high / breakout-retest / volume-profile zones off, band 0.015,",
        "strong pivots 3 bars / 10% either side, confirmation 0.03, retest window 2,",
        "second chance after a win on, overlapping zones not merged, target 1.22.",
        "",
        "IS = entry date before 2024-01-01. OOS = entry date on or after 2024-01-01. OOS is report-only.",
        "Picking a stop from this table is in-sample selection. Do not retune on OOS.",
        "",
        "The percent is under the trigger-day low (`stop_loss_based=trigger_low`, multiplier). It is not 9% under the fill.",
        "GAP_DOWN is a long that opened through the stop. STOP_LOSS is a stop touch without that gap.",
        "Max DD is a closed-trade equity replay on each slice. Capital days is the sum of days held.",
        "Realized reward/risk = average winner / absolute average loser. Expectancy = average percent P&L.",
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
    for b in books:
        for name in ("IS", "OOS", "FULL"):
            m = b["slices"][name]
            lines.append(
                f"- **{b['label']} {name}:** N={m['n']} WR={m['wr']:.1f}% avg win={m['avg_win']:.2f}% "
                f"avg loss={m['avg_loss']:.2f}% R/R={m['rr']:.2f} avg={m['avg_pnl']:.2f}% PF={m['pf']:.2f} "
                f"MaxDD={m['max_dd']:.2f}% days={m['avg_days']:.1f} cap days={m['cap_days']:.0f} "
                f"gaps={m['gap_n']} gap avg={m['gap_avg']:.2f}%"
            )
    lines.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    try:
        if not args.summarize_only:
            # One arm at a time. Four full-universe engines at once crashed the
            # process pool (PyEval_SaveThread / broken worker) on 2026-09-28.
            for aid, _label, stop in ARMS:
                run_fresh(py, aid, stop, args.workers)
        books = []
        closed_pages = []
        for aid, label, stop in ARMS:
            folder = RUNS_DIR / aid
            closed = _latest(folder, "Closed")
            trades = _load(closed)
            books.append(
                {
                    "id": aid,
                    "label": label,
                    "stop": stop,
                    "stop_label": label.split(" ", 1)[-1],
                    "slices": {name: _metrics(_split(trades, name), -100.0 * (1.0 - stop)) for name in ("IS", "OOS", "FULL")},
                }
            )
            note = (
                f"{label}. Stop is {100.0 * (1.0 - stop):.0f}% under the trigger-day low "
                f"(stop multiplier {stop:.2f}). Other WPBR rules match the 2026-09-27 full-universe freeze."
            )
            closed_pages.append(write_closed_html(closed, OUT_DIR / f"closed_{aid}.html", f"WPBR closed — {label}", note))
        write_csv(books)
        html_path = write_html(books, closed_pages)
        write_baseline(books, html_path)
    except Exception as exc:
        path = OUT_DIR / "compare.html"
        path.write_text(
            "<!DOCTYPE html><html><body><h1>WPBR stop test did not finish</h1>"
            f"<p>{html_mod.escape(str(exc))}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN)}</p></body></html>",
            encoding="utf-8",
        )
        _notify(py, [path], f"WPBR stop test failed: {exc}")
        print(f"[{TAG}] FAIL {exc}", flush=True)
        return 1
    for b in books:
        full = b["slices"]["FULL"]
        print(
            f"[{TAG}] {b['label']} FULL N={full['n']} WR={full['wr']:.1f} avg={full['avg_pnl']:.2f} "
            f"PF={full['pf']:.2f} gaps={full['gap_n']} gap_avg={full['gap_avg']:.2f}",
            flush=True,
        )
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    _notify(
        py,
        [html_path, *closed_pages],
        "WPBR full-universe stop test: control -9%, A -8%, B -7%, C -6%. Compare and closed pages.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
