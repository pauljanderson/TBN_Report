"""WPBR A/B: 20% overhead + 18% target + 7% stop vs current 22/20/8 control.

CONTROL: wpbr_overhead_band_pct=0.22, target_pct=1.20, stop_pct=0.92
         reused stamp 261002172253 (tmp_wpbr_day40_vel10_ab_20261002/control).

TEST: overhead 0.20, target 1.18, stop 0.93 (7% under trigger-day low).
Reward/risk ~2.57 vs control 20/8 = 2.5.

Research only. IS cut DATE_OPENED < 2024-01-01. OOS report-only. Not DailyRun.
HTML under drive/mark_experiments/.
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
OUT_DIR = ROOT / "drive" / "mark_experiments" / "wpbr_oh20_t18_s7_ab_20261003"
RUNS = ROOT / "tmp_wpbr_oh20_t18_s7_ab_20261003"
CONTROL_SRC = ROOT / "tmp_wpbr_day40_vel10_ab_20261002" / "control"
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
    "Can you run that again, but use 7% for the stop in the 20/18 group. I want to maintain "
    "the Risk/reward. Control remains current 22% overhead, 20% profit target, 8% stop under "
    "trigger-day low. Test: 20% overhead, 18% profit target, 7% stop under trigger-day low. "
    "Keep all other WPBR entry logic, universe, sizing, execution rules, and settings identical "
    "to the current control. Report IS, OOS, and FULL. Research only."
)

ARMS: list[dict[str, Any]] = [
    {
        "id": "control",
        "short": "Control 22/20/8",
        "folder": CONTROL_DIR,
        "change": "overhead 22%, target +20%, stop −8%",
    },
    {
        "id": "test",
        "short": "Test 20/18/7",
        "folder": TEST_DIR,
        "change": "overhead 20%, target +18%, stop −7%",
    },
]

METRIC_ROWS: list[tuple[str, str, int, str]] = [
    ("n", "Closed trades", 0, ""),
    ("wr", "Win rate (WR)", 1, "%"),
    ("avg", "Avg P&L %", 2, "%"),
    ("pf", "Profit factor (PF)", 2, ""),
    ("avg_win", "Avg winner %", 2, "%"),
    ("avg_loss", "Avg loser %", 2, "%"),
    ("max_dd", "Max DD %", 2, "%"),
    ("ann_ror", "Ann ROR %", 2, "%"),
    ("avg_days", "Avg days held", 1, ""),
    ("med_days", "Median days held", 1, ""),
    ("capital_days", "Capital Days", 0, ""),
    ("ppcd", "PPCD $", 2, ""),
]

DELTA_KEYS = {
    "n", "avg", "pf", "ann_ror", "avg_days", "med_days", "capital_days", "ppcd",
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
    "target_pct": "1.20",
    "stop_pct": "0.92",
    "sheet_no_entry_same_bar_after_exit": "false",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
}

UW_EXIT = ""  # unused leftover slot in _uw_stats / summary.csv


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


def _metrics(trades: list[dict[str, Any]], cash: float, curve: Path | None, window: str) -> dict[str, Any]:
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    empty: dict[str, Any] = {
        "n": 0, "wins": 0, "wr": float("nan"), "avg": float("nan"), "median": float("nan"),
        "pf": float("nan"), "max_dd": float("nan"), "ann_ror": float("nan"),
        "avg_days": float("nan"), "med_days": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "expect": float("nan"), "capital_days": 0.0, "ppcd": float("nan"),
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
    total = sum(dols) if len(dols) == n else sum(p / 100.0 * cash for p in pnls)
    ann = ann_ror_from_closed(
        total_pnl=total, n_trades=n, avg_days_held=avg_days, brt_cash=cash,
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
    ppcd = (total / capital_days) if capital_days > 0 else float("nan")
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


def _score(spec: dict[str, Any]) -> dict[str, Any]:
    folder = spec["folder"]
    closed = _latest(folder, "Closed")
    if closed is None:
        raise FileNotFoundError(f"no closed file in {folder}")
    trades = _load_trades(closed)
    cash, cash_src = _slot_cash(folder, trades)
    curve = _latest(folder, "EquityCurve")
    slices = {w: _metrics(_slice_rows(trades, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    exits = Counter(t["exit"] for t in trades)
    return {
        **spec,
        "closed": str(closed),
        "slot_cash": cash,
        "slot_src": cash_src,
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
        sortable_th("Avg days", "num"),
        sortable_th("Med days", "num"),
        sortable_th("Capital Days", "num"),
        sortable_th("PPCD $", "num"),
        sortable_th("Avg win %", "num"),
        sortable_th("Avg loss %", "num"),
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
        "capital_days", "sharpe", "ppcd", "calmar",
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


def _write_ab_plan() -> None:
    text = """# AB plan — WPBR 20/18/7 vs 22/20/8

## Type

Three named knobs on the test arm: overhead exclusion, profit target, and stop.
Control is the live 22/20/8 freeze. Research only. Not DailyRun.

The 7% stop is there so reward/risk stays near the live book:
control +20% / −8% = 2.5; test +18% / −7% ≈ 2.57.

## Hypothesis

A slightly tighter overhead skip (20% instead of 22%) plus a closer target (+18%) and
a matching tighter stop (−7%) may keep quality vs 22/20/8 without stretching risk/reward.

## Arms

| Arm | Knobs |
| --- | --- |
| CONTROL | `wpbr_overhead_band_pct=0.22`, `target_pct=1.20`, `stop_pct=0.92` |
| TEST | `wpbr_overhead_band_pct=0.20`, `target_pct=1.18`, `stop_pct=0.93` |

No other combinations.

## Split

IS = `DATE_OPENED < 2024-01-01`. OOS = `DATE_OPENED >= 2024-01-01` (report-only). No OOS retune.

## Selection bias

One three-knob candidate named before results. KEEP/HOLD/DISMISS on IS quality; OOS softens → HOLD.
"""
    (OUT_DIR / "AB_PLAN.md").write_text(text, encoding="utf-8")


def _write_baseline(books: list[dict[str, Any]]) -> None:
    test = next(b for b in books if b["id"] == "test")
    ctrl = next(b for b in books if b["id"] == "control")
    lines = [
        "# WPBR 20/18/7 vs 22/20/8",
        "",
        "Pivot Break and Retest (WPBR). Test: 20% overhead, +18% target, −7% stop. "
        "Control: 22/20/8. Research only. Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "Control is the current live-style Pivot Break and Retest book: skip a buy if an older "
        "weekly zone sits within 22% overhead, take +20% profit on the whole position, and stop "
        "8% under the low of the trigger day (reward/risk 20÷8 = 2.5). The test book uses the same "
        "universe, entries, and sizing, but skips at 20% overhead, takes profit at +18%, and stops "
        "7% under the trigger-day low so reward/risk stays about the same (18÷7 ≈ 2.57). Buys "
        "before 2024 are in-sample. 2024 onward is out of sample and is for reading only.",
        "",
        "## Verdict",
        "",
        f"- {test['verdict']}",
        "",
        "Research only. Not gold. Not DailyRun. Out of sample is report-only. Do not retune on OOS.",
        "",
        "## Freeze",
        "",
        "- **ENTRY + EXIT mix:** overhead band (who enters), profit target, and stop (7% vs 8%).",
        "- Control reused from `tmp_wpbr_day40_vel10_ab_20261002/control` (engine stamp **261002172253**). "
        "Knobs match that freeze: `wpbr_overhead_band_pct=0.22`, `target_pct=1.20`, "
        "`stop_pct=0.92`, `growth_filter_enabled=false`, `use_indicators=true` (record-only).",
        "- Test is a fresh full-universe run with `wpbr_overhead_band_pct=0.20`, `target_pct=1.18`, `stop_pct=0.93`.",
        "- Shared: full warehouse, weekly WPBR zones, band 0.015, strong pivot either 3/10%, "
        "breakout confirm 0.03, retest window 2, second chance after win on, indicators record-only, "
        "market-cap filter off, SPY 1y gate off, `min_history_bars=0`.",
        "- IS cut: `DATE_OPENED < 2024-01-01`. OOS report-only.",
        "- Annualized rate of return (Ann ROR) is the house formula via `compare_format.ann_ror_from_closed` with each "
        f"arm's slot cash (control ${ctrl['slot_cash']:,.2f}; test ${test['slot_cash']:,.2f}).",
        "- Profit per capital day (PPCD) = total closed P&L $ / Capital Days.",
        "- Selection bias: one named 20/18/7 candidate. `run_wpbr.bat` / DailyRun were **not** changed.",
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
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _write_html(books: list[dict[str, Any]]) -> Path:
    esc = html_mod.escape
    test = next(b for b in books if b["id"] == "test")
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
<title>WPBR 20/18/7 vs 22/20/8 A/B</title>
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
<h1>Pivot Break and Retest — 20/18/7 vs 22/20/8</h1>
<p class="note">Research only. Test uses 20% overhead, +18% target, −7% stop to keep reward/risk near the live 20/8 book. Not gold. Not DailyRun. Click column headers to sort. Swipe sideways to see more columns.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{esc(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>Control is the current live-style Pivot Break and Retest book: skip a buy if an older weekly zone sits within 22% overhead, take +20% profit on the whole position, and stop 8% under the low of the trigger day (reward/risk 20÷8 = 2.5). The test book uses the same universe, entries, and sizing, but skips at 20% overhead, takes profit at +18%, and stops 7% under the trigger-day low so reward/risk stays about the same (18÷7 ≈ 2.57). Buys before 2024 are in-sample. 2024 onward is out of sample and is for reading only.</p>
</div>
<h2>Verdict</h2>
<p class="note">Call uses in-sample quality. Out of sample is report-only. Soft OOS → HOLD. No OOS retune.</p>
<ul><li>{esc(test['verdict'])}</li></ul>
<h2>Headline (FULL / IS / OOS)</h2>
{SWIPE_NOTE_HTML}
{_headline_table(books)}
<h2>Exit mix (FULL)</h2>
{SWIPE_NOTE_HTML}
{_exit_table(books)}
<h2>Full compare</h2>
<p class="note">Corrected annualized rate of return (Ann ROR) uses each arm's slot cash via the house formula. Total PnL $ / Sheet PnL $ omitted from tables. A positive Max DD delta is a deeper drop than control. Capital Days is the sum of days held. Profit per capital day (PPCD) is total closed dollars divided by Capital Days.</p>
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
    knobs["wpbr_overhead_band_pct"] = "0.20"
    knobs["target_pct"] = "1.18"
    knobs["stop_pct"] = "0.93"
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
    books = [_score(spec) for spec in ARMS]
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
            "-t", "WPBR 20/18/7 vs 22/20/8",
        ],
        cwd=str(ROOT),
        check=False,
    )
    return html_path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    score_only = "--score-only" in sys.argv
    _prepare_control()
    if not score_only:
        _run_test()
    _publish()


if __name__ == "__main__":
    main()
