"""WPBR full-universe exit A/B. One pair change: 18% target and 7% stop.

Both arms keep the 22% overhead-zone refusal on unrestricted WPBR. Control is
the 20% target and 8% stop. The test book uses an 18% target and a 7% stop.

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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import (  # noqa: E402
    calmar_ratio,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

STAMP = "20261002"
IS_CUT = "20240101"
LOOKBACK = 756
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_overhead22_target18_stop7_ab_{STAMP}"
RUNS_DIR = ROOT / "tmp_wpbr_overhead22_target18_stop7_ab_20261002"
PRIOR_CONTROL = ROOT / "tmp_wpbr_overhead22_target20_stop8_ab_20261002" / "t20s8"
TAG = f"wpbr_overhead22_target18_stop7_ab_{STAMP}"
CASH = 47500.0
ACCOUNT = 500_000.0

# Unrestricted WPBR plus the 22% overhead refusal. Control keeps target 1.20
# and stop 0.92. The test arm sets target 1.18 and stop 0.93.
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
    "min_history_bars": "0",
    "growth_filter_strict_gt": "false",
    "growth_min_pct": "0",
    "wpbr_overhead_band_pct": "0.22",
    "min_spy_compare_1y_at_trigger": "-1000",
    "ind_score_weights_path": "",
    "too_high_multiplier": "0",
    "target_pct": "1.20",
    "stop_pct": "0.92",
    "sheet_no_entry_same_bar_after_exit": "false",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
}

ARMS: list[tuple[str, str, dict[str, str]]] = [
    ("control", "20% target / 8% stop", {}),
    ("t18s7", "18% target / 7% stop", {"target_pct": "1.18", "stop_pct": "0.93"}),
]

REQUEST_PROMPT = """Can you run an AB with Control: 20% target / 8% stop.
Test: 18% target / 7% stop.
Keep the 22% overhead rule fixed and change nothing else. Give me summary and closed for the test group."""

LAYMAN = (
    "We kept Pivot Break and Retest (WPBR) the same and only moved the sell prices. "
    "Both books skip a buy when an older WPBR zone has its bottom above the top of the zone being bought, and that gap is 22% or less. "
    "A gap of exactly 22% is still skipped. A wider gap is allowed through. "
    "Neither book requires the close to be higher than it was 756 trading sessions earlier, and neither book requires 756 sessions of history. "
    "Control sells the whole position at 20% above the buy, and the stop is 8% under the low of the day before the buy. "
    "The test sells at 18% above the buy, and the stop is 7% under that same low. "
    "A stock that opens through the stop is sold at the open, so the loss can be larger than 7% or 8%. "
    "In-sample is buys before 2024. Out of sample is 2024 onward and is for reading only. "
    "This does not change the live system. "
    "The summary and closed files on this page are the test book only."
)


def _notify(py: str, paths: list[Path], message: str) -> None:
    cmd = [py, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR 18% target 7% stop"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def _latest(folder: Path, needle: str) -> Path:
    hits = sorted(folder.glob(f"WPBR_{needle}_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no WPBR_{needle} in {folder}")
    return hits[-1]


def ensure_control() -> Path:
    """Reuse the 2026-10-02 20% target / 8% stop arm. Those knobs are this control."""
    dest = RUNS_DIR / "control"
    if dest.is_dir() and any(dest.glob("WPBR_Closed_*.csv")):
        print(f"[{TAG}] reuse control {dest}", flush=True)
        return dest
    if not PRIOR_CONTROL.is_dir() or not any(PRIOR_CONTROL.glob("WPBR_Closed_*.csv")):
        raise FileNotFoundError(f"missing prior control run {PRIOR_CONTROL}")
    print(f"[{TAG}] copy control from {PRIOR_CONTROL}", flush=True)
    shutil.copytree(PRIOR_CONTROL, dest)
    return dest


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
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"{arm_id} exited {proc.returncode}. See {log_path}\n{tail}")
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


def _gain_frac(row: dict[str, str]) -> float:
    now = _f(row.get("TRIGGER_CLOSE"))
    ago = _f(row.get("CLOSE_LOOKBACK"))
    if math.isfinite(now) and math.isfinite(ago) and ago > 0:
        return now / ago - 1.0
    return float("nan")


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
    ("avg_days", "Avg days held", 1, "", "num"),
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

TEST_IDS = ("t18s7",)


def _reject_counts(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    keys = ("OVERHEAD_22", "GROWTH", "GROWTH_FLAT", "MIN_HISTORY")
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
    return out


def _verdict(ctrl: dict[str, Any], test: dict[str, Any], label: str) -> str:
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
        call = "DISMISS. In-sample average P&L is worse than control."
    else:
        call = "HOLD. In-sample average P&L is close to control."
    return f"{label}: {call}"


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
    by_id = {b["id"]: b for b in books}
    ctrl = by_id["control"]
    tests = [by_id[i] for i in TEST_IDS]
    verdicts = [_verdict(ctrl, b, b["label"]) for b in tests]
    slices = ("IS", "OOS", "FULL")

    sections = []
    for sl in slices:
        head = sortable_th("Metric", "text") + sortable_th("Control", "num")
        for b in tests:
            head += sortable_th(b["label"], "num") + sortable_th(f"{b['label']} delta", "num")
        body = []
        for key, label, nd, suffix, kind in METRIC_ROWS:
            cells = [f"<td>{esc(label)}</td>", f"<td>{esc(_cell(ctrl['slices'][sl][key], kind, nd, suffix))}</td>"]
            cv = ctrl["slices"][sl][key]
            for b in tests:
                tv = b["slices"][sl][key]
                cells.append(f"<td>{esc(_cell(tv, kind, nd, suffix))}</td>")
                cells.append(f"<td>{esc(_dcell(tv, cv, kind, nd, suffix))}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        sections.append(
            f"<section><h2>{esc(sl)}</h2>"
            "<p class=\"muted\">Click column headers to sort.</p>"
            + SWIPE_NOTE_HTML
            + "<div class=\"table-wrap\"><table class=\"sortable\">"
            + f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div></section>"
        )

    rej_keys = (
        ("OVERHEAD_22", "Turned away: an earlier zone sits within 22% above the entry zone"),
        ("GROWTH", "Turned away: close not higher than 756 sessions earlier"),
        ("GROWTH_FLAT", "Turned away: close equal to 756 sessions earlier"),
        ("MIN_HISTORY", "Not eligible: fewer than 756 sessions of real history"),
    )
    rej_head = sortable_th("Reason", "text")
    for b in books:
        rej_head += sortable_th(f"IS {b['label']}", "num")
    for b in books:
        rej_head += sortable_th(f"FULL {b['label']}", "num")
    rej_rows = []
    for key, label in rej_keys:
        cells = [f"<td>{esc(label)}</td>"]
        for sl in ("IS", "FULL"):
            for b in books:
                cells.append(f"<td>{b['rejects'][key][sl]}</td>")
        rej_rows.append("<tr>" + "".join(cells) + "</tr>")

    exit_names = sorted({name for b in books for name in b["slices"]["FULL"]["exits"]})
    exit_head = sortable_th("Exit", "text")
    for b in books:
        exit_head += sortable_th(f"{b['label']} n", "num") + sortable_th(f"{b['label']} %", "text")
    exit_rows = []
    for name in exit_names:
        cells = [f"<td>{esc(name)}</td>"]
        for b in books:
            n = b["slices"]["FULL"]["exits"].get(name, 0)
            base = b["slices"]["FULL"]["n"] or 1
            cells.append(f"<td>{n}</td><td>{100.0 * n / base:.1f}%</td>")
        exit_rows.append("<tr>" + "".join(cells) + "</tr>")

    score_head = sortable_th("Score", "text") + "".join(sortable_th(b["label"], "num") for b in books)
    score_rows = []
    for key, label, nd in (
        ("paul", "Mean Paul score", 2),
        ("fit", "Mean FIT", 2),
        ("robust", "Mean robust FIT", 2),
        ("symbols", "Symbols", 0),
    ):
        cells = [f"<td>{esc(label)}</td>"]
        for b in books:
            cells.append(f"<td>{_fmt(b['means'][key], nd)}</td>")
        score_rows.append("<tr>" + "".join(cells) + "</tr>")

    scope = "full universe (every CSV under data/newdata/data)" if not symbols else f"symbols {symbols}"
    freeze = [
        "Both arms are unrestricted WPBR plus the 22% overhead refusal: growth_filter_enabled=false, growth_filter_strict_gt=false, growth_min_pct=0, min_history_bars=0, wpbr_overhead_band_pct=0.22. The close does not have to be higher than it was 756 sessions earlier, and a short history does not block the buy. An entry is rejected when any earlier WPBR zone has its lower edge strictly above the active entry zone's upper edge and (lower - upper) / upper is 22% or less. A gap of exactly 22% is rejected. A wider gap is not.",
        "Control is target_pct=1.20 and stop_pct=0.92. The whole position sells at 20% above the buy. The stop is 8% under the low of the trigger day, the day before the buy.",
        "Test only: target_pct=1.18 and stop_pct=0.93. The whole position sells at 18% above the buy. The stop is 7% under that same trigger-day low.",
        "Control outputs are the 2026-10-02 20% target / 8% stop arm, stamp 261002051403. Those knobs match this control, and the price files have not changed since that run. The 18% / 7% arm is a fresh full-universe run.",
        "Live run_wpbr.bat still uses target_pct=1.22, stop_pct=0.91, min_history_bars=756, and no overhead gate. This pair is the research book named in the request. It is not a DailyRun wire.",
        "Shared on every arm: weekly WPBR zones, band_pct 0.015, strong pivot either side 3 bars and 10%, breakout confirmation 0.03, retest window 2 days, second chance after a winning target on, full exit at the target, indicators recorded and not used as a buy gate, market-cap filter off, SPY 1-year compare gate off.",
        "In-sample is DATE_OPENED before 2024-01-01. Out of sample is DATE_OPENED on or after 2024-01-01. Out of sample is report-only.",
        "Annualized rate of return (Ann ROR) uses the house formula: ((1 + total P&L dollars / (cash per trade × trades)) ** (365 / average days held) − 1) × 100, via compare_format.overlay_ann_ror_max_dd. Cash per trade $47,500. Account $500,000 for maximum drawdown and Sharpe. Profit per capital day (PPCD) is total closed dollars divided by capital days.",
        f"Universe: {scope}.",
        "One test was named before the run. Research only. Not gold. Not DailyRun.",
    ]

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR 18% target / 7% stop</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1500px;margin:0 auto;padding:1rem}}
h1{{font-size:1.35rem;margin:0 0 .4rem}}
h2{{font-size:1.05rem;margin:0 0 .5rem}}
.muted{{color:var(--muted)}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap;font-size:.9rem}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.82rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .45rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
th.sortable-th{{color:var(--text)}}
.swipe-note{{color:var(--muted)}}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
@media (max-width: 800px) {{
  table.sortable > thead > tr > th.sortable-th:first-child,
  table.sortable > tbody > tr > td:first-child {{
    background: #1a2332;
    color: #e7ecf3;
  }}
}}
</style></head><body>
<header>
<h1>WPBR 20% target / 8% stop vs 18% target / 7% stop</h1>
<p class="muted">Pivot Break and Retest (WPBR). The 22% overhead-zone rule is on both books. Research only. Not gold. Not DailyRun. Deltas are versus the 20% target and 8% stop. Swipe sideways to see more columns.</p>
</header>
<main>
<div class="callout"><h2>What you asked</h2>
<pre>{esc(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {esc(LAYMAN)}</p>
</div>
<section><h2>Verdict</h2>
{''.join(f'<p>{esc(v)}</p>' for v in verdicts)}
<p class="muted">Judged on in-sample average profit and loss and profit factor (PF). Out of sample (OOS) is reported and is not used to pick the rule. Win rate is WR. Maximum drawdown is Max DD. Profit per capital day is PPCD. Annualized rate of return is Ann ROR after this sentence.</p>
</section>
<section><h2>How to read the tables</h2>
<p class="muted">IS is in-sample: buys before 2024. OOS is out of sample: 2024 onward. FULL is both. Expectancy % is the average closed P&amp;L %. Expectancy $ is average closed dollars. PPCD is total closed dollars divided by capital days. Avg days are calendar days held. Ann ROR is the house annualized rate of return.</p>
</section>
{''.join(sections)}
<section><h2>Setups these rules turned away</h2>
<p class="muted">These counts are setups that already cleared the other WPBR rules, then failed the named check. Both books use the 22% overhead refusal. Exit prices do not change these counts. Both books leave the growth filter and the 756-session history requirement off, so those rows should be zero.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>{rej_head}</tr></thead>
<tbody>{''.join(rej_rows)}</tbody></table></div>
</section>
<section><h2>Exit mix, full book</h2>
<div class="table-wrap"><table class="sortable">
<thead><tr>{exit_head}</tr></thead>
<tbody>{''.join(exit_rows)}</tbody></table></div>
</section>
<section><h2>Symbol scores (mean, symbols with at least one trade)</h2>
<div class="table-wrap"><table class="sortable">
<thead><tr>{score_head}</tr></thead>
<tbody>{''.join(score_rows)}</tbody></table></div>
</section>
<section><h2>Freeze</h2><ul>{''.join(f'<li>{esc(line)}</li>' for line in freeze)}</ul></section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = OUT_DIR / "compare.html"
    html_path.write_text(page, encoding="utf-8")
    md = [
        "# WPBR 20% target / 8% stop vs 18% / 7%",
        "",
        "Pivot Break and Retest (WPBR). Research only.",
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
    ]
    md.extend(verdicts)
    md.extend([
        "",
        "Research only. Not gold. Not DailyRun. Out of sample is report-only.",
        "Win rate (WR), profit factor (PF), maximum drawdown (Max DD), profit per capital day (PPCD), and annualized rate of return (Ann ROR) are in the tables.",
        "",
        "## Freeze",
        "",
    ])
    md.extend(f"- {line}" for line in freeze)
    for sl in slices:
        md.extend(["", f"## {sl}", ""])
        hdr = ["Metric", "Control"]
        for b in tests:
            hdr.extend([b["label"], f"{b['label']} delta"])
        md.append("| " + " | ".join(hdr) + " |")
        md.append("| " + " | ".join("---" for _ in hdr) + " |")
        for key, label, nd, suffix, kind in METRIC_ROWS:
            cells = [label, _cell(ctrl["slices"][sl][key], kind, nd, suffix)]
            cv = ctrl["slices"][sl][key]
            for b in tests:
                tv = b["slices"][sl][key]
                cells.extend([_cell(tv, kind, nd, suffix), _dcell(tv, cv, kind, nd, suffix)])
            md.append("| " + " | ".join(cells) + " |")
    md.extend(["", "## Rejects (IS / FULL)", ""])
    for key, label in rej_keys:
        bits = [label]
        for b in books:
            c = b["rejects"][key]
            bits.append(f"{b['label']} IS {c['IS']} FULL {c['FULL']}")
        md.append("- " + "; ".join(bits) + ".")
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
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR 18% target / 7% stop</title></head>
<body><h1>WPBR 20% target / 8% stop vs 18% target / 7% stop</h1>
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
    ap.add_argument("--arms", default="", help="Comma list of arm ids to run. Empty = control and t18s7.")
    args = ap.parse_args()
    py = sys.executable
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {s.strip() for s in args.arms.split(",") if s.strip()} or {a[0] for a in ARMS}
    try:
        for arm_id, _label, extra in ARMS:
            if arm_id not in wanted:
                continue
            if arm_id == "control" and not args.symbols.strip():
                ensure_control()
                continue
            run_arm(py, arm_id, extra, args.workers, args.symbols.strip())
        books = []
        books = []
        for arm_id, label, _extra in ARMS:
            folder = RUNS_DIR / arm_id
            has_closed = folder.is_dir() and any(folder.glob("WPBR_Closed_*.csv"))
            if arm_id not in wanted and not has_closed:
                continue
            if not has_closed:
                raise FileNotFoundError(f"missing arm folder {folder}")
            if arm_id not in wanted:
                print(f"[{TAG}] reuse {arm_id} from {folder}", flush=True)
            books.append(_book(arm_id, label, folder))
        if "control" not in {b["id"] for b in books} or any(i not in {b["id"] for b in books} for i in TEST_IDS):
            lines = []
            for b in books:
                full = b["slices"]["FULL"]
                avg = full["avg_pnl"]
                avg_s = f"{avg:.2f}" if math.isfinite(avg) else "nan"
                lines.append(
                    f"{b['id']} trades={full['n']} avg={avg_s} "
                    f"overhead={b['rejects']['OVERHEAD_22']['FULL']}"
                )
            print(f"[{TAG}] partial arms only, report skipped: " + "; ".join(lines), flush=True)
            return 0
        html_path, md_path = write_reports(books, args.symbols.strip())
        test_dir = RUNS_DIR / "t18s7"
        summary_src = _latest(test_dir, "Summary")
        closed_src = _latest(test_dir, "Closed")
        summary_out = OUT_DIR / "test_summary.csv"
        closed_out = OUT_DIR / "test_closed.csv"
        shutil.copyfile(summary_src, summary_out)
        shutil.copyfile(closed_src, closed_out)
        bits = []
        for b in books:
            full = b["slices"]["FULL"]
            bits.append(f"{b['label']} {full['n']} trades avg {_fmt(full['avg_pnl'])}%")
        msg = "; ".join(bits)
        print(f"[{TAG}] Wrote {html_path}", flush=True)
        print(f"[{TAG}] Wrote {summary_out}", flush=True)
        print(f"[{TAG}] Wrote {closed_out}", flush=True)
        print(f"[{TAG}] {msg}", flush=True)
        _notify(py, [html_path, md_path], msg)
        return 0
    except Exception:
        err = traceback.format_exc()
        print(err, flush=True)
        path = write_failure(err)
        _notify(py, [path], "WPBR 18% target / 7% stop run failed. See the HTML.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
