"""Rescore the 80/20 WPBR A/B with position-weighted capital days.

Does not rerun the engine. Uses existing closed books.
Before the +15% scale, capital days = 100%. After selling 80%, leftover 20% until exit.
Control has no scale, so weighted days equal DAYS_HELD.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime
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
    ann_ror_from_closed,
    calmar_ratio,
    format_money,
    sharpe_from_equity_curve_csv,
)
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    RESPONSIVE_TABLE_CSS,
    SWIPE_NOTE_HTML,
)

IS_CUT = "20240101"
IS_DATE = date(2024, 1, 1)
OUT_DIR = ROOT / "drive" / "mark_experiments" / "wpbr_d40_t15_p80_be30_weighted_cap_20261003"
RUNS = ROOT / "tmp_wpbr_d40_t15_p80_be30_ab_20261003"
CONTROL_SRC = ROOT / "tmp_wpbr_d40_target15_ab_20261003" / "test"
CONTROL_DIR = CONTROL_SRC
TEST_DIR = RUNS / "test"
PY = sys.executable
WORKERS = 30

ANN_FLAT = 0.25
ANN_WORSE = 0.15
PF_WORSE = 0.05
DD_WORSE = 1.0
N_FLOOR = 0.85

REQUEST_QUOTE = (
    "Audit the capital-efficiency calculations in the corrected WPBR 80/20 report. Do not change "
    "any trades, entries, exits, P&L, or system rules. Specifically verify the formulas and inputs "
    "used for PPCD $, slot cash, weighted capital days, weighted average days held, and annualized "
    "ROR for both the control and 80/20 test. Explain mathematically why IS PPCD falls from $3.37 "
    "to $2.17 when Avg P&L rises from 4.09% to 4.20% and weighted capital days increase only 6.34%. "
    "Show the actual numerator and denominator used for each PPCD calculation and the actual "
    "slot-cash calculation used for each ROR calculation. If any metric is incorrectly treating the "
    "remaining 20% position, released 80% capital, trade count, or closed P&L, correct it and "
    "regenerate the same FULL / IS / OOS comparison. Do not run any new parameter tests."
)

ARMS: list[dict[str, Any]] = [
    {
        "id": "control",
        "short": "Control full +15% D40",
        "folder": CONTROL_DIR,
        "change": "100% sale at +15% (unweighted days = DAYS_HELD)",
    },
    {
        "id": "test",
        "short": "Test 80/20 +15 then +30",
        "folder": TEST_DIR,
        "change": "80/20 P&L unchanged; capital days weighted 100% then 20%",
    },
]

METRIC_ROWS: list[tuple[str, str, int, str]] = [
    ("n", "Closed trades", 0, ""),
    ("wr", "Win rate (WR)", 1, "%"),
    ("avg", "Avg P&L %", 2, "%"),
    ("pf", "Profit factor (PF)", 2, ""),
    ("expect", "Expectancy %", 2, "%"),
    ("max_dd", "Max DD %", 2, "%"),
    ("ann_ror", "Ann ROR %", 2, "%"),
    ("calmar", "Calmar", 2, ""),
    ("sharpe", "Sharpe", 2, ""),
    ("avg_win", "Avg winner %", 2, "%"),
    ("avg_loss", "Avg loser %", 2, "%"),
    ("avg_days", "Avg weighted days held", 1, ""),
    ("med_days", "Median weighted days held", 1, ""),
    ("capital_days", "Weighted capital days", 0, ""),
    ("ppcd", "PPCD $ (equal-slot)", 2, ""),
    ("tpy", "Trades / year", 2, ""),
]

DELTA_KEYS = {
    "n", "wr", "avg", "pf", "expect", "max_dd", "ann_ror", "calmar", "sharpe",
    "avg_win", "avg_loss", "avg_days", "med_days", "capital_days", "ppcd", "tpy",
}

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
    "growth_bars": "756",
    "growth_history_slack_bars": "0",
    "min_history_bars": "0",
    "growth_filter_strict_gt": "false",
    "growth_min_pct": "0",
    "wpbr_overhead_band_pct": "0.22",
    "min_spy_compare_1y_at_trigger": "-1000",
    "ind_score_weights_path": "",
    "too_high_multiplier": "0",
    "target_pct": "1.15",
    "stop_pct": "0.92",
    "wpbr_underwater_time_stop_bars": "40",
    "brt_scale_gain": "0",
    "brt_scale_sell_frac": "0.80",
    "brt_scale_stop_gain": "0",
    "brt_scale_runner_gain": "0.30",
    "sheet_no_entry_same_bar_after_exit": "false",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
}

UW_EXIT = "WPBR_UW_TS40"


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


def _latest(folder: Path, needle: str) -> Path | None:
    hits = sorted(folder.glob(f"WPBR_{needle}_*.csv"), key=lambda p: p.stat().st_mtime)
    if needle == "EquityCurve":
        primary = [p for p in hits if "_Aggressive_" not in p.name and "_Regular_" not in p.name]
        if primary:
            return primary[-1]
    return hits[-1] if hits else None


def _read_report(folder: Path) -> dict[str, str]:
    path = _latest(folder, "Report")
    if path is None:
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def _weighted_days(opened: str, closed: str, scale_date: str, sold_frac: float, days_held: float) -> float:
    leftover = 1.0 - sold_frac if math.isfinite(sold_frac) and 0.0 < sold_frac < 1.0 else 1.0
    if leftover >= 1.0 - 1e-12 or not scale_date:
        return days_held if math.isfinite(days_held) else float("nan")
    o = _to_date(opened)
    c = _to_date(closed or opened)
    s = _to_date(scale_date)
    if o is None or c is None or s is None:
        return days_held if math.isfinite(days_held) else float("nan")
    if s < o:
        s = o
    if s > c:
        s = c
    pre = float((s - o).days)
    post = float((c - s).days)
    return pre + leftover * post


def _to_date(ymd: str):
    raw = _ymd(ymd)
    if len(raw) != 8:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def _load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _ymd(str(raw.get("DATE_OPENED") or ""))
            if not opened:
                continue
            closed = _ymd(str(raw.get("DATE_CLOSED") or ""))
            days_held = _f(raw.get("DAYS_HELD"))
            sold = _f(raw.get("SCALE_SOLD_FRAC"), 0.0)
            scale_date = _ymd(str(raw.get("SCALE_DATE") or ""))
            wdays = _weighted_days(opened, closed, scale_date, sold, days_held)
            rows.append({
                "symbol": str(raw.get("SYMBOL") or "").strip().upper(),
                "opened": opened,
                "closed": closed,
                "pnl": _f(raw.get("PNL_PCT")),
                "pnl_d": _f(raw.get("PNL_DOLLARS")),
                "days": wdays if math.isfinite(wdays) else days_held,
                "days_raw": days_held,
                "exit": str(raw.get("EXIT_TYPE") or "").strip() or "?",
            })
    return rows


def _slot_cash(folder: Path, trades: list[dict[str, Any]]) -> tuple[float, str]:
    report = _read_report(folder)
    cap = _f(report.get("capacity_brt_cash"))
    if math.isfinite(cap) and cap > 0:
        return cap, "report capacity_brt_cash"
    notions: list[float] = []
    for t in trades:
        if math.isfinite(t["pnl_d"]) and math.isfinite(t["pnl"]) and abs(t["pnl"]) > 0.05:
            notions.append(abs(t["pnl_d"]) / (abs(t["pnl"]) / 100.0))
    if not notions:
        raise RuntimeError(f"no slot cash in {folder}")
    notions.sort()
    return notions[len(notions) // 2], "median |PNL_DOLLARS| / |PNL_PCT|"


def _slice_rows(trades: list[dict[str, Any]], window: str) -> list[dict[str, Any]]:
    if window == "FULL":
        return trades
    if window == "IS":
        return [t for t in trades if t["opened"] < IS_CUT]
    return [t for t in trades if t["opened"] >= IS_CUT]


def _profit_factor(pnls: list[float]) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    if gl > 0:
        return gp / gl
    return float("inf") if gp > 0 else float("nan")


def _equity_max_dd(path: Path | None, start: date | None, end_excl: date | None) -> float:
    if path is None or not path.is_file():
        return float("nan")
    peak = None
    worst = 0.0
    seen = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw_d = str(row.get("Date") or "")[:10]
            try:
                d = datetime.strptime(raw_d, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start is not None and d < start:
                continue
            if end_excl is not None and d >= end_excl:
                continue
            v = _f(row.get("Equity_Regular"))
            if not math.isfinite(v) or v <= 0:
                continue
            seen += 1
            if peak is None or v > peak:
                peak = v
            if peak and peak > 0:
                worst = max(worst, (peak - v) / peak)
    if seen < 2:
        return float("nan")
    return worst * 100.0


def _uw_stats(trades: list[dict[str, Any]]) -> tuple[int, float, float, float]:
    vel = [t for t in trades if t["exit"] == UW_EXIT]
    if not vel:
        return 0, float("nan"), float("nan"), float("nan")
    pnls = [t["pnl"] for t in vel if math.isfinite(t["pnl"])]
    dols = [t["pnl_d"] for t in vel if math.isfinite(t["pnl_d"])]
    avg = (sum(pnls) / len(pnls)) if pnls else float("nan")
    med = float(statistics.median(pnls)) if pnls else float("nan")
    avg_d = (sum(dols) / len(dols)) if dols else float("nan")
    return len(vel), avg, med, avg_d


def _metrics(
    trades: list[dict[str, Any]],
    engine_cash: float,
    compare_cash: float,
    curve: Path | None,
    window: str,
) -> dict[str, Any]:
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    empty: dict[str, Any] = {
        "n": 0, "wins": 0, "wr": float("nan"), "avg": float("nan"), "median": float("nan"),
        "pf": float("nan"), "max_dd": float("nan"), "ann_ror": float("nan"),
        "avg_days": float("nan"), "med_days": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "expect": float("nan"), "capital_days": 0.0, "ppcd": float("nan"),
        "ppcd_engine": float("nan"), "total_file": float("nan"), "total_eq": float("nan"),
        "engine_cash": engine_cash, "compare_cash": compare_cash,
        "tpy": float("nan"), "vel_n": 0, "vel_avg": float("nan"), "vel_med": float("nan"),
        "vel_avg_d": float("nan"),
    }
    if n == 0:
        return empty
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    avg_days = (sum(days) / len(days)) if days else 0.0
    capital_days = float(sum(days)) if days else 0.0
    dols = [t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"])]
    total_file = sum(dols) if len(dols) == n else sum(p / 100.0 * engine_cash for p in pnls)
    total_eq = sum(p / 100.0 * compare_cash for p in pnls)
    ann = ann_ror_from_closed(
        total_pnl=total_eq, n_trades=n, avg_days_held=avg_days, brt_cash=compare_cash,
    )
    if window == "IS":
        start, end = None, IS_DATE
    elif window == "OOS":
        start, end = IS_DATE, None
    else:
        start, end = None, None
    max_dd = _equity_max_dd(curve, start, end)
    ann_v = float(ann) if ann is not None else float("nan")
    calmar = calmar_ratio(ann_v, max_dd)
    sharpe = sharpe_from_equity_curve_csv(curve, start_date=start, end_date_exclusive=end)
    opens = []
    closes = []
    for t in trades:
        try:
            opens.append(datetime.strptime(t["opened"], "%Y%m%d").date())
            closes.append(datetime.strptime(t["closed"] or t["opened"], "%Y%m%d").date())
        except ValueError:
            continue
    span = ((max(closes) - min(opens)).days / 365.25) if opens and closes else 0.0
    vel_n, vel_avg, vel_med, vel_avg_d = _uw_stats(trades)
    ppcd = (total_eq / capital_days) if capital_days > 0 else float("nan")
    ppcd_engine = (total_file / capital_days) if capital_days > 0 else float("nan")
    return {
        "n": n,
        "wins": len(wins),
        "wr": 100.0 * len(wins) / n,
        "avg": sum(pnls) / n,
        "median": float(statistics.median(pnls)),
        "pf": _profit_factor(pnls),
        "max_dd": max_dd,
        "ann_ror": ann_v,
        "avg_days": avg_days,
        "med_days": float(statistics.median(days)) if days else float("nan"),
        "calmar": float(calmar) if calmar is not None else float("nan"),
        "sharpe": float(sharpe) if sharpe is not None else float("nan"),
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "expect": sum(pnls) / n,
        "capital_days": capital_days,
        "ppcd": ppcd,
        "ppcd_engine": ppcd_engine,
        "total_file": total_file,
        "total_eq": total_eq,
        "engine_cash": engine_cash,
        "compare_cash": compare_cash,
        "tpy": (n / span) if span > 0.25 else float("nan"),
        "vel_n": vel_n,
        "vel_avg": vel_avg,
        "vel_med": vel_med,
        "vel_avg_d": vel_avg_d,
    }

def _verdict(label: str, is_m: dict[str, Any], oos_m: dict[str, Any], ctrl: dict[str, dict[str, Any]]) -> str:
    c_is, c_oos = ctrl["IS"], ctrl["OOS"]
    d_ann = is_m["ann_ror"] - c_is["ann_ror"]
    d_oos = oos_m["ann_ror"] - c_oos["ann_ror"]
    d_pf = is_m["pf"] - c_is["pf"]
    d_avg = is_m["avg"] - c_is["avg"]
    d_dd = is_m["max_dd"] - c_is["max_dd"]
    n_ratio = (is_m["n"] / c_is["n"]) if c_is["n"] else 0.0
    if not math.isfinite(d_ann):
        return f"{label}: HOLD. In-sample annualized rate of return could not be computed."
    if d_ann < -ANN_WORSE or (d_ann <= 0 and d_avg < -0.05):
        return f"{label}: DISMISS. In-sample annualized rate of return is worse than control."
    if d_ann <= ANN_FLAT:
        return f"{label}: HOLD. In-sample annualized rate of return is close to control."
    if d_ann > 0 and d_avg < 0 and d_pf < 0:
        return (
            f"{label}: HOLD. In-sample annualized rate of return is higher, "
            "but average percent and profit factor are both worse."
        )
    if d_oos < -ANN_FLAT:
        return (
            f"{label}: HOLD. In-sample annualized rate of return is better, and out of sample is softer. "
            "Do not retune off the out-of-sample row."
        )
    reasons = []
    if d_pf < -PF_WORSE:
        reasons.append(f"in-sample profit factor fell by {abs(d_pf):.3f}")
    if math.isfinite(d_dd) and d_dd > DD_WORSE:
        reasons.append(f"in-sample maximum drawdown deepened by {d_dd:.2f} points")
    if n_ratio < N_FLOOR:
        reasons.append("in-sample trade count fell below 85% of control")
    if reasons:
        return (
            f"{label}: HOLD. In-sample annualized rate of return is better, and out of sample did not soften, but "
            + "; ".join(reasons)
            + "."
        )
    return (
        f"{label}: KEEP as research only. In-sample annualized rate of return improved, "
        "profit factor and drawdown held up, and out of sample did not soften. "
        "Not gold. Not a live change."
    )


def _verdict_word(text: str) -> str:
    if "DISMISS" in text:
        return "DISMISS"
    if "KEEP" in text:
        return "KEEP"
    return "HOLD"


def _fmt(v: float, nd: int = 2, suffix: str = "") -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    if math.isinf(float(v)):
        return "inf"
    if nd == 0:
        return f"{int(round(float(v)))}{suffix}"
    return f"{float(v):.{nd}f}{suffix}"


def _delta(v: float, base: float, nd: int = 2, suffix: str = "") -> str:
    if not (isinstance(v, (int, float)) and isinstance(base, (int, float))):
        return "—"
    if not (math.isfinite(v) and math.isfinite(base)):
        return "—"
    d = v - base
    sign = "+" if d > 0 else ""
    if nd == 0:
        return f"{sign}{int(round(d))}{suffix}"
    return f"{sign}{d:.{nd}f}{suffix}"


def _pct_delta(v: float, base: float) -> str:
    if not (isinstance(v, (int, float)) and isinstance(base, (int, float))):
        return "—"
    if not (math.isfinite(v) and math.isfinite(base)) or abs(base) < 1e-12:
        return "—"
    d = 100.0 * (v - base) / abs(base)
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.2f}%"


def _score(spec: dict[str, Any], compare_cash: float) -> dict[str, Any]:
    folder = spec["folder"]
    closed = _latest(folder, "Closed")
    if closed is None:
        raise FileNotFoundError(f"no closed file in {folder}")
    trades = _load_trades(closed)
    engine_cash, cash_src = _slot_cash(folder, trades)
    report = _read_report(folder)
    max_pos = _f(report.get("Max_Positions"))
    curve = _latest(folder, "EquityCurve")
    slices = {
        w: _metrics(_slice_rows(trades, w), engine_cash, compare_cash, curve, w)
        for w in ("FULL", "IS", "OOS")
    }
    exits = Counter(t["exit"] for t in trades)
    return {
        **spec,
        "closed": str(closed),
        "slot_cash": compare_cash,
        "engine_cash": engine_cash,
        "slot_src": cash_src,
        "max_positions": max_pos,
        "slices": slices,
        "exits": exits,
        "n_full": slices["FULL"]["n"],
        "trades": trades,
    }


def _metric_table(books: list[dict[str, Any]], window: str) -> str:
    ctrl = books[0]["slices"][window]
    test = books[1]["slices"][window]
    head = "".join([
        sortable_th("Metric", "text"),
        sortable_th(books[0]["short"], "num"),
        sortable_th(books[1]["short"], "num"),
        sortable_th("Abs change", "num"),
        sortable_th("% change", "num"),
    ])
    body = []
    for key, label, nd, suf in METRIC_ROWS:
        cv = ctrl[key]
        tv = test[key]
        if key == "ppcd":
            c_s = f"${cv:,.{nd}f}" if isinstance(cv, (int, float)) and math.isfinite(cv) else "—"
            t_s = f"${tv:,.{nd}f}" if isinstance(tv, (int, float)) and math.isfinite(tv) else "—"
            if isinstance(tv, (int, float)) and isinstance(cv, (int, float)) and math.isfinite(tv) and math.isfinite(cv):
                d = tv - cv
                sign = "+" if d >= 0 else "-"
                abs_s = f"{sign}${abs(d):,.{nd}f}"
            else:
                abs_s = "—"
        else:
            c_s = _fmt(cv, nd, suf)
            t_s = _fmt(tv, nd, suf)
            abs_s = _delta(tv, cv, nd, suf)
        pct_s = _pct_delta(tv, cv) if key in DELTA_KEYS else "—"
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(label)}</td>"
            f"<td>{c_s}</td><td>{t_s}</td><td>{abs_s}</td><td>{pct_s}</td>"
            "</tr>"
        )
    return (
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _headline_table(books: list[dict[str, Any]]) -> str:
    head = "".join([
        sortable_th("Arm", "text"),
        sortable_th("Slice", "text"),
        sortable_th("N", "num"),
        sortable_th("WR", "num"),
        sortable_th("Avg P&L %", "num"),
        sortable_th("PF", "num"),
        sortable_th("Expectancy %", "num"),
        sortable_th("Max DD %", "num"),
        sortable_th("Ann ROR %", "num"),
        sortable_th("Calmar", "num"),
        sortable_th("Sharpe", "num"),
        sortable_th("Avg wtd days", "num"),
        sortable_th("Med wtd days", "num"),
        sortable_th("Wtd capital days", "num"),
        sortable_th("PPCD $", "num"),
        sortable_th("Avg win %", "num"),
        sortable_th("Avg loss %", "num"),
        sortable_th("Trades/yr", "num"),
        sortable_th("Verdict", "text"),
    ])
    rows = []
    for b in books:
        for sl in ("FULL", "IS", "OOS"):
            m = b["slices"][sl]
            verdict = "control" if b["id"] == "control" else (b["verdict_word"] if sl == "FULL" else "")
            ppcd = f"${m['ppcd']:,.2f}" if math.isfinite(m["ppcd"]) else "—"
            rows.append(
                "<tr>"
                f"<td>{html_mod.escape(b['short'])}</td>"
                f"<td>{sl}</td>"
                f"<td>{m['n']}</td>"
                f"<td>{_fmt(m['wr'], 1, '%')}</td>"
                f"<td>{_fmt(m['avg'], 2, '%')}</td>"
                f"<td>{_fmt(m['pf'], 2)}</td>"
                f"<td>{_fmt(m['expect'], 2, '%')}</td>"
                f"<td>{_fmt(m['max_dd'], 2, '%')}</td>"
                f"<td>{_fmt(m['ann_ror'], 2, '%')}</td>"
                f"<td>{_fmt(m['calmar'], 2)}</td>"
                f"<td>{_fmt(m['sharpe'], 2)}</td>"
                f"<td>{_fmt(m['avg_days'], 1)}</td>"
                f"<td>{_fmt(m['med_days'], 1)}</td>"
                f"<td>{_fmt(m['capital_days'], 0)}</td>"
                f"<td>{ppcd}</td>"
                f"<td>{_fmt(m['avg_win'], 2, '%')}</td>"
                f"<td>{_fmt(m['avg_loss'], 2, '%')}</td>"
                f"<td>{_fmt(m['tpy'], 2)}</td>"
                f"<td>{html_mod.escape(verdict)}</td>"
                "</tr>"
            )
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _exit_table(books: list[dict[str, Any]]) -> str:
    names: list[str] = []
    for b in books:
        for name in b["exits"]:
            if name not in names:
                names.append(name)
    if UW_EXIT in names:
        names.remove(UW_EXIT)
        names.insert(0, UW_EXIT)
    head = sortable_th("Exit", "text") + "".join(
        sortable_th(b["short"] + " trades", "num") + sortable_th(b["short"] + " share", "num")
        for b in books
    )
    rows = []
    for name in names:
        cells = [f"<td>{html_mod.escape(name)}</td>"]
        for b in books:
            n = b["n_full"] or 1
            c = int(b["exits"].get(name, 0))
            cells.append(f"<td>{c}</td><td>{100.0 * c / n:.1f}%</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _audit_table(books: list[dict[str, Any]]) -> str:
    head = "".join([
        sortable_th("Arm", "text"),
        sortable_th("Slice", "text"),
        sortable_th("Engine slot $", "num"),
        sortable_th("Max positions", "num"),
        sortable_th("Equal-slot $", "num"),
        sortable_th("N", "num"),
        sortable_th("File P&L $ (num.)", "num"),
        sortable_th("Equal-slot P&L $ (num.)", "num"),
        sortable_th("Wtd capital days (den.)", "num"),
        sortable_th("Avg wtd days", "num"),
        sortable_th("PPCD engine $", "num"),
        sortable_th("PPCD equal-slot $", "num"),
        sortable_th("Ann ROR %", "num"),
    ])
    rows = []
    for b in books:
        for sl in ("FULL", "IS", "OOS"):
            m = b["slices"][sl]
            mp = b.get("max_positions", float("nan"))
            rows.append(
                "<tr>"
                f"<td>{html_mod.escape(b['short'])}</td>"
                f"<td>{sl}</td>"
                f"<td>${m['engine_cash']:,.2f}</td>"
                f"<td>{_fmt(mp, 0)}</td>"
                f"<td>${m['compare_cash']:,.2f}</td>"
                f"<td>{m['n']}</td>"
                f"<td>${m['total_file']:,.2f}</td>"
                f"<td>${m['total_eq']:,.2f}</td>"
                f"<td>{_fmt(m['capital_days'], 1)}</td>"
                f"<td>{_fmt(m['avg_days'], 2)}</td>"
                f"<td>${m['ppcd_engine']:,.4f}</td>"
                f"<td>${m['ppcd']:,.4f}</td>"
                f"<td>{_fmt(m['ann_ror'], 2, '%')}</td>"
                "</tr>"
            )
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _copy_artifacts(books: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for b in books:
        dest = OUT_DIR / b["id"]
        dest.mkdir(parents=True, exist_ok=True)
        folder = Path(b["folder"])
        for needle in ("Closed", "Report", "Summary", "EquityMeta", "EquityCurve", "Open"):
            src = _latest(folder, needle)
            if src is None:
                continue
            shutil.copy2(src, dest / src.name)
        # Prefer Regular curve too
        for p in folder.glob("WPBR_EquityCurve_Regular_*.csv"):
            shutil.copy2(p, dest / p.name)


def _write_summary(books: list[dict[str, Any]]) -> Path:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm_id", "label", "one_change", "slice",
        "n", "win_rate", "avg_pct", "profit_factor", "expectancy_pct",
        "max_dd_pct", "ann_ror_pct", "avg_days", "median_days",
        "capital_days", "sharpe", "ppcd", "ppcd_engine", "total_file", "total_eq",
        "engine_cash", "compare_cash", "calmar",
        "vel_exits", "vel_avg_pnl_pct", "vel_med_pnl_pct", "vel_avg_pnl_dollars",
        "slot_cash", "verdict", "source_closed",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b in books:
            for sl in ("FULL", "IS", "OOS"):
                m = b["slices"][sl]
                w.writerow({
                    "arm_id": b["id"],
                    "label": b["short"],
                    "one_change": b["change"],
                    "slice": sl,
                    "n": m["n"],
                    "win_rate": m["wr"],
                    "avg_pct": m["avg"],
                    "profit_factor": m["pf"],
                    "expectancy_pct": m["expect"],
                    "max_dd_pct": m["max_dd"],
                    "ann_ror_pct": m["ann_ror"],
                    "avg_days": m["avg_days"],
                    "median_days": m["med_days"],
                    "capital_days": m["capital_days"],
                    "sharpe": m["sharpe"],
                    "ppcd": m["ppcd"],
                    "ppcd_engine": m.get("ppcd_engine"),
                    "total_file": m.get("total_file"),
                    "total_eq": m.get("total_eq"),
                    "engine_cash": m.get("engine_cash"),
                    "compare_cash": m.get("compare_cash"),
                    "calmar": m["calmar"],
                    "vel_exits": m["vel_n"],
                    "vel_avg_pnl_pct": m["vel_avg"],
                    "vel_med_pnl_pct": m["vel_med"],
                    "vel_avg_pnl_dollars": m["vel_avg_d"],
                    "slot_cash": b["slot_cash"],
                    "verdict": "" if b["id"] == "control" else b["verdict"],
                    "source_closed": b["closed"],
                })
    return path


def _audit_math_md(ctrl: dict[str, Any], test: dict[str, Any]) -> list[str]:
    cis = ctrl["slices"]["IS"]
    tis = test["slices"]["IS"]
    cash_c = cis["engine_cash"]
    cash_t = tis["engine_cash"]
    n_c, n_t = cis["n"], tis["n"]
    avg_c, avg_t = cis["avg"], tis["avg"]
    cd_c, cd_t = cis["capital_days"], tis["capital_days"]
    slot_ratio = cash_t / cash_c if cash_c else float("nan")
    n_ratio = n_t / n_c if n_c else float("nan")
    avg_ratio = avg_t / avg_c if avg_c else float("nan")
    cd_ratio = cd_c / cd_t if cd_t else float("nan")
    ppcd_ratio = slot_ratio * n_ratio * avg_ratio * cd_ratio
    cd_up = 100.0 * (cd_t / cd_c - 1.0) if cd_c else float("nan")
    return [
        "## Capital-efficiency audit",
        "",
        "Formulas (unchanged books):",
        "",
        "- Weighted days (scaled names): `(SCALE_DATE − DATE_OPENED).days × 1 + "
        "(DATE_CLOSED − SCALE_DATE).days × (1 − SCALE_SOLD_FRAC)`. Else `DAYS_HELD`.",
        "- Weighted capital days = sum of those days. Weighted average days = that sum / N.",
        "- Engine PPCD $ = `sum(Closed PNL_DOLLARS)` / weighted capital days.",
        "- Equal-slot PPCD $ = `sum(PNL_PCT/100 × control slot cash)` / weighted capital days.",
        "- Ann ROR % = `((1 + equal-slot $ / (compare_cash × N)) ** (365 / avg weighted days) − 1) × 100`.",
        "- Engine slot cash = Report `capacity_brt_cash` = account D / Max_Positions. Test Max_Positions "
        "is larger because leftover 20% still occupies a full slot in the engine.",
        "",
        "Released 80% is **not** in the capital-days denominator after `SCALE_DATE` (leftover weight 0.20). "
        "Trade count is unweighted (one closed name = one trade). Closed P&L % already blends 80/20 fills.",
        "",
        f"### Why IS engine PPCD went ${cis['ppcd_engine']:.2f} → ${tis['ppcd_engine']:.2f}",
        "",
        "Not because leftover days were under-counted (those days are already 20% weighted). "
        "Not because Avg P&L % fell (it rose). Because Closed dollars were scaled to a smaller slot "
        f"(${cash_t:,.2f} vs ${cash_c:,.2f}) while capital days are full-slot-equivalent units.",
        "",
        "Engine PPCD = (slot × N × avg%/100) / CD, so",
        "",
        f"`test/control = ({cash_t:.2f}/{cash_c:.2f}) × ({n_t}/{n_c}) × "
        f"({avg_t:.4f}/{avg_c:.4f}) × ({cd_c:.1f}/{cd_t:.1f})`",
        "",
        f"= {slot_ratio:.6f} × {n_ratio:.6f} × {avg_ratio:.6f} × {cd_ratio:.6f} = {ppcd_ratio:.6f}.",
        "",
        f"`{cis['ppcd_engine']:.4f} × {ppcd_ratio:.6f} = {cis['ppcd_engine'] * ppcd_ratio:.4f}` "
        f"(matches test engine PPCD ${tis['ppcd_engine']:.4f}).",
        "",
        f"Slot ratio {slot_ratio:.4f} is the main term. Capital days up {cd_up:.2f}% is the clock move. "
        "Equal-slot PPCD puts both arms on control cash so that slot ratio is 1.",
        "",
        f"IS control PPCD numerator/denominator: ${cis['total_file']:,.2f} / {cd_c:,.1f} = "
        f"${cis['ppcd_engine']:.4f} (engine); equal-slot ${cis['total_eq']:,.2f} / {cd_c:,.1f} = "
        f"${cis['ppcd']:.4f}.",
        "",
        f"IS test PPCD numerator/denominator: ${tis['total_file']:,.2f} / {cd_t:,.1f} = "
        f"${tis['ppcd_engine']:.4f} (engine); equal-slot ${tis['total_eq']:,.2f} / {cd_t:,.1f} = "
        f"${tis['ppcd']:.4f}.",
        "",
        f"Ann ROR slot: compare_cash = ${cis['compare_cash']:,.2f} on both arms. "
        f"IS control: total_eq ${cis['total_eq']:,.2f}, N={n_c}, avg days {cis['avg_days']:.4f}. "
        f"IS test: total_eq ${tis['total_eq']:,.2f}, N={n_t}, avg days {tis['avg_days']:.4f}.",
        "",
    ]


def _write_ab_plan() -> None:
    text = """# Rescore — 80/20 WPBR with position-weighted capital days

## Type

Scoring-only. Same closed books as `wpbr_d40_t15_p80_be30_ab_20261003`. No engine rerun.
P&L, entries, exits, and rules are unchanged.

## Weighted capital days

Calendar days match `DAYS_HELD` (`DATE_CLOSED - DATE_OPENED`).
If `SCALE_DATE` is present and `SCALE_SOLD_FRAC` is in (0, 1):

`weighted = (SCALE_DATE - DATE_OPENED).days × 1.0 + (DATE_CLOSED - SCALE_DATE).days × (1 - SCALE_SOLD_FRAC)`

No scale (control, or names that never tagged +15%): weighted = `DAYS_HELD`.

Ann ROR uses the house formula with weighted average days held and **equal-slot** dollars
(control `capacity_brt_cash` applied to both arms' P&L %). That ratio is the same as using
each arm's own file dollars with its own engine cash, because Closed `PNL_DOLLARS` already
equals `PNL_PCT/100 × engine slot`.

PPCD on the compare table uses equal-slot dollars / weighted capital days so leftover runners
do not shrink the dollar unit via Max_Positions. The audit table also shows the old engine-dollar PPCD.


## Split

IS = `DATE_OPENED < 2024-01-01`. OOS report-only. KEEP/HOLD/DISMISS on IS quality using rescored Ann ROR.
"""
    (OUT_DIR / "AB_PLAN.md").write_text(text, encoding="utf-8")


def _write_baseline(books: list[dict[str, Any]]) -> None:
    test = next(b for b in books if b["id"] == "test")
    ctrl = next(b for b in books if b["id"] == "control")
    lines = [
        "# WPBR 80/20 vs full +15%: position-weighted capital days",
        "",
        "Scoring-only rescore of the existing 80/20 book. No new trades. Research only. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "Control sells the whole position at +15%. Test sells 80% at +15% and leaves about 20% on "
        "until +30% or the leftover stop/Day-40. This page does not change those trades. It checks "
        "whether profit-per-capital-day and annualized rate of return used the same dollar slot on "
        "both arms. The leftover 20% is already in the weighted-days clock; the 80% sale is already "
        "in P&L %. Buys before 2024 are in-sample. 2024 onward is for reading only.",
        "",
        "## Verdict",
        "",
        f"- {test['verdict']}",
        "",
        "Research only. Not gold. Not DailyRun. Out of sample is report-only. Do not retune on OOS.",
        "",
        "## Freeze",
        "",
        "- **Scoring only.** Closed books unchanged: control stamp **261003124834**, test stamp **261003135702**.",
        "- Weighted days: 100% of calendar days from entry to `SCALE_DATE`, then 20% from scale to exit "
        "(`1 - SCALE_SOLD_FRAC`). No scale → `DAYS_HELD`.",
        "- Equal-slot PPCD / Ann ROR dollars: `sum(PNL_PCT/100 × control capacity_brt_cash) / weighted capital days`. "
        "Engine file dollars stay in the audit table. Leftover 20% is **not** used to shrink the slot for the whole trade.",
        "- Ann ROR: `((1 + equal-slot $ / (compare_cash × N)) ** (365 / avg weighted days) − 1) × 100`. "
        "Because equal-slot $ / (compare_cash × N) = average P&L %, this matches using each arm's own cash with its own file $.",
        "- P&L %, PF, win rate, exit mix unchanged. Max DD / Sharpe from the existing equity curve. "
        "Calmar uses rescored Ann ROR.",
        "- Frozen system: 22% overhead, +15% then leftover +30% on test, −8% stop, Day-40-below-entry.",
        "- IS cut: `DATE_OPENED < 2024-01-01`. OOS report-only. DailyRun not changed.",
        f"- Engine slot cash (D/Max_Positions): control ${ctrl['engine_cash']:,.2f} "
        f"(Max_Positions {_fmt(ctrl.get('max_positions', float('nan')), 0)}); "
        f"test ${test['engine_cash']:,.2f} "
        f"(Max_Positions {_fmt(test.get('max_positions', float('nan')), 0)}).",
        f"- Compare / equal-slot cash: ${ctrl['slot_cash']:,.2f} (control capacity_brt_cash).",
        "",
        "## Headline metrics",
        "",
    ]
    for sl in ("FULL", "IS", "OOS"):
        lines.append(f"### {sl}")
        lines.append("")
        lines.append("| Metric | Control | Test | Abs change | % change |")
        lines.append("| --- | --- | --- | --- | --- |")
        for key, label, nd, suf in METRIC_ROWS:
            cv = ctrl["slices"][sl][key]
            tv = test["slices"][sl][key]
            pct = _pct_delta(tv, cv) if key in DELTA_KEYS else "—"
            if key == "ppcd":
                c_s = f"${cv:,.2f}" if isinstance(cv, (int, float)) and math.isfinite(cv) else "—"
                t_s = f"${tv:,.2f}" if isinstance(tv, (int, float)) and math.isfinite(tv) else "—"
                if isinstance(tv, (int, float)) and isinstance(cv, (int, float)) and math.isfinite(tv) and math.isfinite(cv):
                    d = tv - cv
                    sign = "+" if d >= 0 else "-"
                    d_s = f"{sign}${abs(d):,.2f}"
                else:
                    d_s = "—"
                lines.append(f"| {label} | {c_s} | {t_s} | {d_s} | {pct} |")
            else:
                lines.append(
                    f"| {label} | {_fmt(cv, nd, suf)} | {_fmt(tv, nd, suf)} | {_delta(tv, cv, nd, suf)} | {pct} |"
                )
        lines.append("")
    lines.extend(_audit_math_md(ctrl, test))
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _write_html(books: list[dict[str, Any]]) -> Path:
    esc = html_mod.escape
    test = next(b for b in books if b["id"] == "test")
    ctrl = next(b for b in books if b["id"] == "control")
    cis = ctrl["slices"]["IS"]
    tis = test["slices"]["IS"]
    cash_c = cis["engine_cash"]
    cash_t = tis["engine_cash"]
    n_c, n_t = cis["n"], tis["n"]
    avg_c, avg_t = cis["avg"], tis["avg"]
    cd_c, cd_t = cis["capital_days"], tis["capital_days"]
    slot_ratio = cash_t / cash_c if cash_c else float("nan")
    n_ratio = n_t / n_c if n_c else float("nan")
    avg_ratio = avg_t / avg_c if avg_c else float("nan")
    cd_ratio = cd_c / cd_t if cd_t else float("nan")
    ppcd_ratio = slot_ratio * n_ratio * avg_ratio * cd_ratio
    cd_up = 100.0 * (cd_t / cd_c - 1.0) if cd_c else float("nan")
    sections = []
    for sl, title in (
        ("FULL", "Full book"),
        ("IS", "In-sample (entry before 2024-01-01)"),
        ("OOS", "Out-of-sample (entry on or after 2024-01-01) — report only"),
    ):
        sections.append(f"<h3>{esc(title)}</h3>\n{_metric_table(books, sl)}")
    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>WPBR 80/20 position-weighted capital days</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1c1917; max-width: 1200px; }}
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
<h1>Pivot Break and Retest — 80/20 vs full +15%, position-weighted capital days</h1>
<p class="note">Scoring only. Same trades as the 80/20 A/B. P&amp;L unchanged. Not gold. Not DailyRun. Click column headers to sort. Swipe sideways to see more columns.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{esc(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>Control sells the whole position at +15%. Test sells 80% at +15% and leaves about 20% on until +30% or the leftover stop/Day-40. This page does not change those trades. It checks whether profit-per-capital-day mixed two different dollar slots. The leftover 20% is already in the weighted-days clock; the 80% sale is already in P&amp;L %. Buys before 2024 are in-sample. 2024 onward is for reading only.</p>
</div>
<h2>Verdict</h2>
<p class="note">Call uses in-sample quality. Out of sample is report-only. Soft OOS → HOLD. No OOS retune.</p>
<ul><li>{esc(test['verdict'])}</li></ul>
<h2>Headline (FULL / IS / OOS)</h2>
{SWIPE_NOTE_HTML}
{_headline_table(books)}
<h2>Capital-efficiency audit</h2>
<p class="note">No new parameter tests. Closed P&amp;L %, entries, and exits are unchanged. Headline PPCD $ uses equal-slot dollars (control capacity_brt_cash on both arms). Engine PPCD $ is Closed PNL_DOLLARS / weighted capital days — that is the $3.37 → $2.17 drop.</p>
<p>Weighted days for a scaled name: calendar days to the +15% sale at 100% size, then calendar days after that sale at leftover size (1 − SCALE_SOLD_FRAC = 0.20). Names that never scale use DAYS_HELD. Weighted capital days = sum of those days. Weighted average days held = that sum divided by trade count (unweighted N).</p>
<p>Engine slot cash = Report <code>capacity_brt_cash</code> = account D / Max_Positions. The engine still counts a leftover 20% as a full slot, so the test book has more Max_Positions and a smaller dollar per trade. Released 80% is correctly omitted from the capital-days denominator after SCALE_DATE. Closed P&amp;L already blends 0.8× scale fill + 0.2× remainder.</p>
<p><strong>Why IS engine PPCD fell from ${cis['ppcd_engine']:.2f} to ${tis['ppcd_engine']:.2f} while Avg P&amp;L rose {avg_c:.2f}% → {avg_t:.2f}% and weighted capital days rose only {cd_up:.2f}%:</strong> engine PPCD = (slot cash × N × avg%/100) / capital days. The test/control ratio is</p>
<p><code>({cash_t:.2f}/{cash_c:.2f}) × ({n_t}/{n_c}) × ({avg_t:.4f}/{avg_c:.4f}) × ({cd_c:.1f}/{cd_t:.1f}) = {slot_ratio:.6f} × {n_ratio:.6f} × {avg_ratio:.6f} × {cd_ratio:.6f} = {ppcd_ratio:.6f}</code></p>
<p><code>${cis['ppcd_engine']:.4f} × {ppcd_ratio:.6f} = ${cis['ppcd_engine'] * ppcd_ratio:.4f}</code> (test engine PPCD ${tis['ppcd_engine']:.4f}). The slot ratio {slot_ratio:.4f} dominates. Equal-slot PPCD sets that ratio to 1.</p>
<p>IS control PPCD: numerator ${cis['total_file']:,.2f} (file $) or ${cis['total_eq']:,.2f} (equal-slot $); denominator {cd_c:,.1f} weighted days → ${cis['ppcd_engine']:.4f} engine / ${cis['ppcd']:.4f} equal-slot.</p>
<p>IS test PPCD: numerator ${tis['total_file']:,.2f} (file $) or ${tis['total_eq']:,.2f} (equal-slot $); denominator {cd_t:,.1f} weighted days → ${tis['ppcd_engine']:.4f} engine / ${tis['ppcd']:.4f} equal-slot.</p>
<p>Ann ROR uses compare_cash ${cis['compare_cash']:,.2f} on both arms, total_eq in the numerator, N, and weighted average days. That is the same % as using each arm’s own file $ with its own engine slot, because file $ = pct × engine slot.</p>
{SWIPE_NOTE_HTML}
{_audit_table(books)}
<h2>Exit mix (FULL)</h2>
{SWIPE_NOTE_HTML}
{_exit_table(books)}
<h2>Full compare</h2>
<p class="note">Headline PPCD $ is equal-slot (control cash × P&amp;L % / weighted days). Ann ROR uses the house formula with that same compare cash and weighted average days held. Max DD and Sharpe are from the existing equity curve. Calmar uses the rescored Ann ROR. P&amp;L %, win rate, and profit factor are unchanged from the original 80/20 book.</p>
{SWIPE_NOTE_HTML}
{''.join(sections)}
<p class="note">Picking the best cell after this table is in-sample selection. Research only. Not gold. Not DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(page, encoding="utf-8")
    return path


def _test_cmd() -> list[str]:
    cmd = [
        PY, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(TEST_DIR), "-w", str(WORKERS),
        "--aggressive", "--use-duckdb", "--no-regression",
    ]
    knobs = dict(COMMON)
    knobs["brt_scale_gain"] = "0.15"
    knobs["brt_scale_sell_frac"] = "0.80"
    knobs["brt_scale_stop_gain"] = "0"
    knobs["brt_scale_runner_gain"] = "0.30"
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    return cmd


def _prepare_control() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    if _latest(CONTROL_DIR, "Closed") is None:
        raise FileNotFoundError(f"missing control closed book at {CONTROL_DIR}")
    print(f"control reused: {CONTROL_DIR}", flush=True)


def _run_test() -> None:
    if _latest(TEST_DIR, "Closed") is not None:
        print(f"test closed already present in {TEST_DIR}", flush=True)
        return
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUNS / "test.log"
    cmd = _test_cmd()
    (TEST_DIR / "run_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
    print(f"[start] test workers={WORKERS} log={log_path}", flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            time.sleep(30)
            print(f"[wait] test pid={proc.pid} closed_ready={_latest(TEST_DIR, 'Closed') is not None}", flush=True)
        if proc.returncode != 0:
            raise RuntimeError(f"test run failed rc={proc.returncode}; see {log_path}")
    if _latest(TEST_DIR, "Closed") is None:
        raise FileNotFoundError(f"test finished but no Closed CSV in {TEST_DIR}")
    print("test closed ready", flush=True)


def _publish() -> Path:
    ctrl_trades = _load_trades(_latest(CONTROL_DIR, "Closed"))
    compare_cash, _ = _slot_cash(CONTROL_DIR, ctrl_trades)
    books = [_score(spec, compare_cash) for spec in ARMS]
    ctrl = books[0]["slices"]
    for b in books:
        if b["id"] == "control":
            b["verdict"] = ""
            b["verdict_word"] = "control"
        else:
            b["verdict"] = _verdict(b["short"], b["slices"]["IS"], b["slices"]["OOS"], ctrl)
            b["verdict_word"] = _verdict_word(b["verdict"])
            print(b["verdict"], flush=True)
    _copy_artifacts(books)
    _write_ab_plan()
    summary = _write_summary(books)
    _write_baseline(books)
    html_path = _write_html(books)
    print(f"wrote {html_path}", flush=True)
    print(f"wrote {summary}", flush=True)
    subprocess.run(
        [
            PY, str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path", str(html_path),
            "-t", "WPBR 80/20 capital-efficiency audit",
        ],
        cwd=str(ROOT),
        check=False,
    )
    return html_path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _prepare_control()
    _publish()


if __name__ == "__main__":
    main()
