"""WPBR full-universe entry A/B. One change: a 3-year positive close filter.

Both arms use current WPBR production knobs and require 756 prior sessions
with a real close exactly that far back before a trade can be taken.
The test arm also requires trigger-day close > that lookback close.

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
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import (  # noqa: E402
    calmar_ratio,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)

STAMP = "20260929"
IS_CUT = "20240101"
LOOKBACK = 756
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_growth_3y_fulluniv_ab_{STAMP}"
RUNS_DIR = ROOT / "tmp_wpbr_growth3y_ab_20260929"
TAG = f"wpbr_growth_3y_fulluniv_ab_{STAMP}"
CASH = 47500.0
ACCOUNT = 500_000.0

# Current production knobs from run_wpbr.bat, plus the shared 756-session history gate.
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
    "growth_bars": str(LOOKBACK),
    "growth_history_slack_bars": "0",
    "min_history_bars": str(LOOKBACK),
    "growth_filter_strict_gt": "false",
    "min_spy_compare_1y_at_trigger": "-1000",
    "ind_score_weights_path": "",
    "too_high_multiplier": "0",
    "target_pct": "1.22",
    "stop_pct": "0.91",
    "sheet_no_entry_same_bar_after_exit": "false",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
}

TEST_EXTRA: dict[str, str] = {
    "growth_filter_enabled": "true",
    "growth_filter_strict_gt": "true",
    "growth_bars": str(LOOKBACK),
    "growth_history_slack_bars": "0",
}

REQUEST_PROMPT = """Run a WPBR full-universe A/B test of a 3-year positive price-growth filter.
Control: Current WPBR production settings.
Test: Same settings, but require trigger-day close > close 3 years earlier.
Both arms must require 3 full years of prior price history before any trade is eligible, so the comparison starts on the same eligible date. No shorter lookback.
Report IS / OOS / FULL: Trades, WR, Avg P&L, Avg Winner, Avg Loser, PF, Expectancy, Max DD, Avg Days, Capital Days, Ann ROR, Calmar, Sharpe, PPCD, plus trades rejected by the growth filter.
Research only."""

LAYMAN = (
    "We tested one extra buy rule on Pivot Break and Retest (WPBR). "
    "Control is today’s live WPBR setup. "
    "Both books skip any signal that does not already have 756 trading days of prices behind it. "
    "That is about three years, and it keeps a new listing’s early years out of both sides so the start line matches. "
    "The test book adds one rule: on the trigger day (the day before the buy), the close has to be higher than the close from exactly 756 trading days earlier. "
    "The same close, or a lower close, is turned away. "
    "If that old close is missing, the signal is not eligible. We do not use a nearer day. "
    "In-sample is buys before 2024. Out of sample is 2024 onward and is for reading only. "
    "This does not change the live system."
)


def _notify(py: str, paths: list[Path], message: str) -> None:
    cmd = [py, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR 3-year growth"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def _latest(folder: Path, needle: str) -> Path:
    hits = sorted(folder.glob(f"WPBR_{needle}_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no WPBR_{needle} in {folder}")
    return hits[-1]


def run_arm(py: str, arm_id: str, extra: dict[str, str], workers: int, symbols: str) -> Path:
    out = RUNS_DIR / arm_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        py, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(workers), "--aggressive", "--use-duckdb",
        "--no-regression", "--emit-would-have",
    ]
    if symbols:
        cmd.extend(["-s", symbols])
    knobs = dict(COMMON)
    knobs.update(extra)
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    log_path = RUNS_DIR / f"{arm_id}.log"
    print(f"[{TAG}] start {arm_id} log={log_path}", flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"{arm_id} exited {proc.returncode}. See {log_path}")
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


def _ymd(raw: str) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _ymd(str(raw.get("DATE_OPENED") or ""))
            if not opened:
                continue
            rows.append({
                "symbol": str(raw.get("SYMBOL") or "").strip().upper(),
                "opened": opened,
                "closed": _ymd(str(raw.get("DATE_CLOSED") or "")),
                "pnl": _f(raw.get("PNL_PCT")),
                "pnl_d": _f(raw.get("PNL_DOLLARS")),
                "days": _f(raw.get("DAYS_HELD")),
                "exit": str(raw.get("EXIT_TYPE") or "").strip(),
            })
    return rows


def _load_rejects(folder: Path) -> list[dict[str, str]]:
    hits = sorted(folder.glob("WPBR_WouldHave_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        return []
    with hits[-1].open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _slice_name(opened: str) -> str:
    if not opened:
        return ""
    return "IS" if opened < IS_CUT else "OOS"


def _metrics(trades: list[dict[str, Any]], equity: Path | None, window: str) -> dict[str, Any]:
    empty = {
        "n": 0, "wins": 0, "losses": 0, "wr": float("nan"),
        "avg_win": float("nan"), "avg_loss": float("nan"),
        "avg_pnl": float("nan"), "wo_max": float("nan"), "pf": float("nan"),
        "expect_pct": float("nan"), "expect_d": float("nan"),
        "ann_ror": float("nan"), "max_dd": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_days": float("nan"), "cap_days": 0.0,
        "ppcd": float("nan"), "tpy": float("nan"), "exits": {},
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
    mx = max(pnls) if pnls else float("nan")
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 and math.isfinite(mx) else float("nan")
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    parsed = []
    for t in trades:
        try:
            opened_d = datetime.strptime(t["opened"], "%Y%m%d").date()
            closed_raw = t["closed"] or t["opened"]
            closed_d = datetime.strptime(closed_raw, "%Y%m%d").date()
        except ValueError:
            continue
        parsed.append({**t, "opened": opened_d, "closed": closed_d, "days": t["days"]})
    start = end = None
    if window == "IS":
        end = datetime.strptime(IS_CUT, "%Y%m%d").date()
    elif window == "OOS":
        start = datetime.strptime(IS_CUT, "%Y%m%d").date()
    cap = overlay_ann_ror_max_dd(
        parsed,
        cash=CASH,
        initial_account=ACCOUNT,
        equity_curve_path=str(equity) if equity and equity.is_file() else None,
        start_date=start,
        end_date_exclusive=end,
    )
    opens = [t["opened"] for t in parsed]
    closes = [t["closed"] for t in parsed]
    span = ((max(closes) - min(opens)).days / 365.25) if opens else 0.0
    cap_days = float(cap.get("capital_days") or 0.0)
    pnl_d = sum(t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"]))
    calmar = cap.get("calmar")
    if calmar_ratio and (calmar is None or not isinstance(calmar, (int, float)) or not math.isfinite(float(calmar))):
        calmar = calmar_ratio(cap.get("ann_ror"), cap.get("max_dd"))
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": (100.0 * len(wins) / n) if n else float("nan"),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_pnl": (sum(pnls) / n) if n else float("nan"),
        "wo_max": wo,
        "pf": (gp / gl) if gl > 0 else float("nan"),
        "expect_pct": (sum(pnls) / n) if n else float("nan"),
        "expect_d": (pnl_d / n) if n else float("nan"),
        "ann_ror": float(cap.get("ann_ror", float("nan"))),
        "max_dd": float(cap.get("max_dd", float("nan"))),
        "calmar": float(calmar) if isinstance(calmar, (int, float)) and math.isfinite(float(calmar)) else float("nan"),
        "sharpe": float(cap.get("sharpe", float("nan"))),
        "avg_days": (sum(days) / len(days)) if days else float("nan"),
        "cap_days": cap_days,
        "ppcd": (pnl_d / cap_days) if cap_days > 0 else float("nan"),
        "tpy": (n / span) if span > 0.25 else float("nan"),
        "exits": dict(Counter(t["exit"] or "?" for t in trades)),
    }


def _summary_means(path: Path) -> dict[str, float]:
    paul, fit, robust = [], [], []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if _f(row.get("TRADES"), 0) <= 0:
                continue
            for bucket, key in ((paul, "PAUL_SCORE"), (fit, "FIT_SCORE"), (robust, "FIT_SCORE_ROBUST")):
                v = _f(row.get(key))
                if math.isfinite(v):
                    bucket.append(v)

    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else float("nan")

    return {"paul": mean(paul), "fit": mean(fit), "robust": mean(robust), "symbols": float(len(paul))}


def _fmt(v: float, nd: int = 2, suffix: str = "") -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    return f"{float(v):.{nd}f}{suffix}"


def _delta(v: float, base: float, nd: int = 2, suffix: str = "") -> str:
    if not (math.isfinite(v) and math.isfinite(base)):
        return "—"
    d = v - base
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.{nd}f}{suffix}"


def _money_delta(v: float, base: float) -> str:
    if not (math.isfinite(v) and math.isfinite(base)):
        return "—"
    return format_money_delta(v - base)


METRIC_ROWS: list[tuple[str, str, int, str, str]] = [
    ("n", "Trades", 0, "", "num"),
    ("wr", "Win rate", 1, "%", "pct"),
    ("avg_pnl", "Avg P&L %", 2, "%", "pct"),
    ("avg_win", "Avg winner %", 2, "%", "pct"),
    ("avg_loss", "Avg loser %", 2, "%", "pct"),
    ("pf", "Profit factor", 2, "", "num"),
    ("expect_pct", "Expectancy %", 2, "%", "pct"),
    ("expect_d", "Expectancy $", 2, "", "money"),
    ("max_dd", "Max DD %", 2, "%", "pct"),
    ("avg_days", "Avg days", 1, "", "num"),
    ("cap_days", "Capital days", 0, "", "num"),
    ("ann_ror", "Ann ROR %", 2, "%", "pct"),
    ("calmar", "Calmar", 2, "", "num"),
    ("sharpe", "Sharpe", 2, "", "num"),
    ("ppcd", "PPCD", 2, "", "money"),
    ("wo_max", "Avg P&L % without max winner", 2, "%", "pct"),
    ("wins", "Wins", 0, "", "num"),
    ("losses", "Losses", 0, "", "num"),
    ("tpy", "Trades / year", 2, "", "num"),
]


def _reject_counts(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    keys = ("GROWTH", "GROWTH_FLAT", "MIN_HISTORY")
    out = {k: {"IS": 0, "OOS": 0, "FULL": 0} for k in keys}
    for row in rows:
        reason = str(row.get("REJECT_REASON") or "").strip()
        if reason not in out:
            continue
        opened = _ymd(str(row.get("WOULD_ENTER_DATE") or row.get("TRIGGER_DATE") or ""))
        out[reason]["FULL"] += 1
        bucket = _slice_name(opened)
        if bucket:
            out[reason][bucket] += 1
    out["GROWTH_ALL"] = {
        sl: out["GROWTH"][sl] + out["GROWTH_FLAT"][sl] for sl in ("IS", "OOS", "FULL")
    }
    return out


def _verdict(ctrl: dict[str, Any], test: dict[str, Any]) -> str:
    i, c = test["slices"]["IS"], ctrl["slices"]["IS"]
    o, co = test["slices"]["OOS"], ctrl["slices"]["OOS"]
    better_is = (
        math.isfinite(i["avg_pnl"]) and math.isfinite(c["avg_pnl"]) and i["avg_pnl"] > c["avg_pnl"] + 0.05
        and math.isfinite(i["pf"]) and math.isfinite(c["pf"]) and i["pf"] >= c["pf"] - 0.02
    )
    worse_is = math.isfinite(i["avg_pnl"]) and math.isfinite(c["avg_pnl"]) and i["avg_pnl"] < c["avg_pnl"] - 0.05
    oos_soft = math.isfinite(o["avg_pnl"]) and math.isfinite(co["avg_pnl"]) and o["avg_pnl"] < co["avg_pnl"] - 0.15
    n_drop = c["n"] > 0 and i["n"] < 0.85 * c["n"]
    if better_is and oos_soft:
        call = "HOLD. In-sample average P&L is better, and out of sample is softer. Do not retune off the out-of-sample row."
    elif better_is and n_drop:
        call = "HOLD. In-sample average is higher, but the trade count fell."
    elif better_is:
        call = "LEAN KEEP as research only. In-sample quality improved and out of sample did not soften on average P&L. Not gold. Not a live change."
    elif worse_is:
        call = "DISMISS. In-sample average P&L is worse than current WPBR production with the same history rule."
    else:
        call = "HOLD. In-sample average P&L is close to control."
    return call


def _cell(v: float, kind: str, nd: int, suffix: str) -> str:
    if kind == "money":
        return format_money(v) if math.isfinite(v) else "—"
    return _fmt(v, nd, suffix)


def _dcell(v: float, base: float, kind: str, nd: int, suffix: str) -> str:
    if kind == "money":
        return _money_delta(v, base)
    return _delta(v, base, nd, suffix)


def write_reports(books: list[dict[str, Any]], symbols: str) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    esc = html_mod.escape
    ctrl = next(b for b in books if b["id"] == "control")
    test = next(b for b in books if b["id"] == "growth3y")
    verdict = _verdict(ctrl, test)
    slices = ("IS", "OOS", "FULL")

    metric_rows = []
    for key, label, nd, suffix, kind in METRIC_ROWS:
        cells = [f"<td>{esc(label)}</td>"]
        for sl in slices:
            cv = ctrl["slices"][sl][key]
            tv = test["slices"][sl][key]
            cells.append(f"<td>{esc(_cell(cv, kind, nd, suffix))}</td>")
            cells.append(f"<td>{esc(_cell(tv, kind, nd, suffix))}</td>")
            cells.append(f"<td>{esc(_dcell(tv, cv, kind, nd, suffix))}</td>")
        metric_rows.append("<tr>" + "".join(cells) + "</tr>")

    head = (
        sortable_th("Metric", "text")
        + "".join(
            sortable_th(f"{sl} {name}", "num")
            for sl in slices
            for name in ("Control", "3-year growth", "Delta")
        )
    )

    def rej_row(label: str, key: str) -> str:
        bits = [f"<td>{esc(label)}</td>"]
        for sl in slices:
            c = ctrl["rejects"][key][sl]
            t = test["rejects"][key][sl]
            bits.append(f"<td>{c}</td><td>{t}</td><td>{t - c:+d}</td>")
        return "<tr>" + "".join(bits) + "</tr>"

    reject_body = "".join([
        rej_row("Rejected by growth filter (close not higher)", "GROWTH_ALL"),
        rej_row("Close lower than 756 days earlier", "GROWTH"),
        rej_row("Close equal to 756 days earlier", "GROWTH_FLAT"),
        rej_row("Not eligible: fewer than 756 sessions of real history", "MIN_HISTORY"),
    ])

    exit_names = sorted(set(ctrl["slices"]["FULL"]["exits"]) | set(test["slices"]["FULL"]["exits"]))
    exit_rows = []
    for name in exit_names:
        cn = ctrl["slices"]["FULL"]["exits"].get(name, 0)
        tn = test["slices"]["FULL"]["exits"].get(name, 0)
        cb = ctrl["slices"]["FULL"]["n"] or 1
        tb = test["slices"]["FULL"]["n"] or 1
        exit_rows.append(
            "<tr>"
            f"<td>{esc(name)}</td><td>{cn}</td><td>{100.0 * cn / cb:.1f}%</td>"
            f"<td>{tn}</td><td>{100.0 * tn / tb:.1f}%</td>"
            "</tr>"
        )

    scope = "full universe (every CSV under data/newdata/data)" if not symbols else f"symbols {symbols}"
    freeze = [
        "Shared on both arms, from run_wpbr.bat: weekly WPBR zones, band_pct 0.015, strong pivot either side 3 bars and 10%, breakout confirmation 0.03, retest window 2 days, second chance after a winning target on, stop 0.91 under the trigger-day low, full exit at target_pct 1.22, indicators recorded and not used as a buy gate, market-cap filter off, SPY 1-year compare gate off.",
        f"Shared history gate: min_history_bars={LOOKBACK}. The trigger bar must have a real positive close exactly {LOOKBACK} sessions earlier (3 × 252 trading days). growth_history_slack_bars=0. A missing or non-positive lookback close is not eligible. Bar 0 is not used as a stand-in.",
        "Test only: growth_filter_enabled=true and growth_filter_strict_gt=true. Trigger-day close must be greater than that exact lookback close. Equal closes are rejected.",
        "The older sheet growth gate (close greater than or equal, and a 2-bar slack that can compare to the first bar) is not this test.",
        "In-sample is DATE_OPENED before 2024-01-01. Out of sample is DATE_OPENED on or after 2024-01-01. Out of sample is report-only.",
        f"Cash per trade $47,500. Account $500,000 for drawdown and Sharpe. Universe: {scope}.",
        "Selecting this filter after seeing this table is in-sample selection. Research only. Not gold. Not DailyRun.",
    ]

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR 3-year growth filter</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1400px;margin:0 auto;padding:1rem}}
h1{{font-size:1.35rem;margin:0 0 .4rem}}
h2{{font-size:1.05rem;margin:0 0 .5rem}}
.muted{{color:var(--muted)}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap;font-size:.9rem}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.82rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .45rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS}
</style></head><body>
<header>
<h1>WPBR 3-year positive price-growth filter</h1>
<p class="muted">Research only. Not gold. Not DailyRun. Click column headers to sort.</p>
</header>
<main>
<div class="callout"><h2>What you asked</h2>
<pre>{esc(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {esc(LAYMAN)}</p>
</div>
<section><h2>Verdict</h2><p>{esc(verdict)}</p>
<p class="muted">Judged on in-sample average P&amp;L and profit factor. Out of sample is reported and is not used to pick the knob.</p>
</section>
<section><h2>Control vs 3-year growth</h2>
<p class="muted">PPCD is profit per capital day (total closed dollars divided by capital days). Expectancy % is the average closed P&amp;L %. Avg days are calendar days held.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(metric_rows)}
</tbody></table></div>
</section>
<section><h2>Trades the growth filter turned away</h2>
<p class="muted">A growth reject is a setup that already cleared the other WPBR rules and the 756-session history rule, then failed trigger close &gt; close from exactly 756 sessions earlier. The history row is the shared eligibility cut, not the growth filter. Counts are setups, not closed trades. Dropping one setup can free the symbol for a later trade, so the trade-count gap is not the same number.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>{sortable_th("Reason", "text")}{''.join(sortable_th(f"{sl} {name}", "num") for sl in slices for name in ("Control", "Test", "Delta"))}</tr></thead>
<tbody>{reject_body}</tbody></table></div>
</section>
<section><h2>Exit mix, full book</h2>
<div class="table-wrap"><table class="sortable">
<thead><tr>{sortable_th("Exit", "text")}{sortable_th("Control n", "num")}{sortable_th("Control %", "text")}{sortable_th("Test n", "num")}{sortable_th("Test %", "text")}</tr></thead>
<tbody>{''.join(exit_rows)}</tbody></table></div>
</section>
<section><h2>Symbol scores (mean, symbols with at least one trade)</h2>
<div class="table-wrap"><table class="sortable">
<thead><tr>{sortable_th("Score", "text")}{sortable_th("Control", "num")}{sortable_th("Test", "num")}</tr></thead>
<tbody>
<tr><td>Mean Paul score</td><td>{_fmt(ctrl["means"]["paul"], 2)}</td><td>{_fmt(test["means"]["paul"], 2)}</td></tr>
<tr><td>Mean FIT</td><td>{_fmt(ctrl["means"]["fit"], 2)}</td><td>{_fmt(test["means"]["fit"], 2)}</td></tr>
<tr><td>Mean robust FIT</td><td>{_fmt(ctrl["means"]["robust"], 2)}</td><td>{_fmt(test["means"]["robust"], 2)}</td></tr>
<tr><td>Symbols</td><td>{int(ctrl["means"]["symbols"])}</td><td>{int(test["means"]["symbols"])}</td></tr>
</tbody></table></div>
</section>
<section><h2>Freeze</h2><ul>{''.join(f"<li>{esc(line)}</li>" for line in freeze)}</ul></section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = OUT_DIR / "compare.html"
    html_path.write_text(page, encoding="utf-8")
    md = [
        "# WPBR 3-year growth filter",
        "",
        "## What you asked",
        "",
        REQUEST_PROMPT.strip(),
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Verdict",
        "",
        verdict,
        "",
        "Research only. Not gold. Not DailyRun. Out of sample is report-only.",
        "",
        "## Freeze",
        "",
    ]
    md.extend(f"- {line}" for line in freeze)
    md.extend(["", "## Metrics", ""])
    hdr = ["Metric"]
    for sl in slices:
        hdr.extend([f"{sl} control", f"{sl} test", f"{sl} delta"])
    md.append("| " + " | ".join(hdr) + " |")
    md.append("| " + " | ".join("---" for _ in hdr) + " |")
    for key, label, nd, suffix, kind in METRIC_ROWS:
        cells = [label]
        for sl in slices:
            cv = ctrl["slices"][sl][key]
            tv = test["slices"][sl][key]
            cells.extend([
                _cell(cv, kind, nd, suffix),
                _cell(tv, kind, nd, suffix),
                _dcell(tv, cv, kind, nd, suffix),
            ])
        md.append("| " + " | ".join(cells) + " |")
    md.extend(["", "## Growth-filter rejects", ""])
    for label, key in (
        ("Close not higher", "GROWTH_ALL"),
        ("Close lower", "GROWTH"),
        ("Close equal", "GROWTH_FLAT"),
        ("Short of 756 sessions", "MIN_HISTORY"),
    ):
        c = ctrl["rejects"][key]
        t = test["rejects"][key]
        md.append(
            f"- {label}: control IS {c['IS']} / OOS {c['OOS']} / FULL {c['FULL']}; "
            f"test IS {t['IS']} / OOS {t['OOS']} / FULL {t['FULL']}."
        )
    md_path = OUT_DIR / "BASELINE.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return html_path, md_path


def _book(arm_id: str, label: str, folder: Path) -> dict[str, Any]:
    closed = _latest(folder, "Closed")
    equity_hits = sorted(folder.glob("WPBR_EquityCurve_Regular_*.csv"))
    equity = equity_hits[-1] if equity_hits else None
    trades = _load_trades(closed)
    slices = {}
    for name, pred in (
        ("IS", lambda t: t["opened"] < IS_CUT),
        ("OOS", lambda t: t["opened"] >= IS_CUT),
        ("FULL", lambda t: True),
    ):
        chosen = [t for t in trades if pred(t)]
        slices[name] = _metrics(chosen, equity, name)
    summary = _latest(folder, "Summary")
    return {
        "id": arm_id,
        "label": label,
        "slices": slices,
        "rejects": _reject_counts(_load_rejects(folder)),
        "means": _summary_means(summary),
        "closed": closed,
    }


def write_failure(message: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "compare.html"
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><title>WPBR 3-year growth filter</title></head>
<body><h1>WPBR 3-year growth filter</h1>
<h2>What you asked</h2><pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {html_mod.escape(LAYMAN)}</p>
<p>The run failed before a comparison table was ready.</p>
<pre>{html_mod.escape(message)}</pre></body></html>"""
    path.write_text(body, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--symbols", default="", help="Comma list for a smoke run. Empty = full universe.")
    args = ap.parse_args()
    py = sys.executable
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        run_arm(py, "control", {}, args.workers, args.symbols.strip())
        run_arm(py, "growth3y", TEST_EXTRA, args.workers, args.symbols.strip())
        books = [
            _book("control", "Control", RUNS_DIR / "control"),
            _book("growth3y", "3-year growth", RUNS_DIR / "growth3y"),
        ]
        html_path, md_path = write_reports(books, args.symbols.strip())
        full = books[1]["slices"]["FULL"]
        ctrl = books[0]["slices"]["FULL"]
        rej = books[1]["rejects"]["GROWTH_ALL"]["FULL"]
        msg = (
            f"Control {ctrl['n']} trades, avg {_fmt(ctrl['avg_pnl'])}%. "
            f"Test {full['n']} trades, avg {_fmt(full['avg_pnl'])}%. "
            f"Growth filter turned away {rej} setups."
        )
        print(f"[{TAG}] Wrote {html_path}", flush=True)
        print(f"[{TAG}] {msg}", flush=True)
        _notify(py, [html_path, md_path], msg)
        return 0
    except Exception:
        err = traceback.format_exc()
        print(err, flush=True)
        path = write_failure(err)
        _notify(py, [path], "WPBR 3-year growth run failed. See the HTML.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
