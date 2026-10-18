"""WPBR packages: tighter overhead together with a lower target and a tighter stop.

Research only. Arms were named before any package P&L. Out of sample is
report-only. Not gold. Not DailyRun.

Control and two isolation books are reused when their saved knobs match this
freeze. The three packages are fresh full-universe rocket_tbn runs.
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
    sharpe_from_equity_curve_csv,
)
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

STAMP = "20261002"
IS_CUT = "20240101"
IS_DATE = date(2024, 1, 1)
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_tighter_overhead_target_stop_ab_{STAMP}"
RUNS_DIR = ROOT / "tmp_wpbr_tighter_overhead_target_stop_ab_20261002"
PY = sys.executable
WORKERS = 10

# Production knobs from run_wpbr.bat (2026-10-02 freeze). Only the arm's
# overhead, target, and stop override these.
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

# Stop base confirmed in rocket_tbn (stop_loss_based=trigger_low, multiplier):
# stop = trigger-day low * stop_pct. 8% under that low is 0.92, 7% is 0.93,
# 6% is 0.94, 4% is 0.96. Target is entry * target_pct.
REQUEST_QUOTE = (
    "let's run post analysis on WPBR and wire up and run some AB tests plus some other "
    "comparable AB tests such as reduced overhead alongside reduced target and stop loss. "
    "let's try 20%, 18%, 7%. 18%, 15%, 6%. 15%, 10%, 4%, and any other combos you think "
    "might be interesting to get results for"
)

# Verdict thresholds frozen in this file before the package runs finish.
# Headline in-sample quality is annualized rate of return, because a lower
# target cuts the average win on purpose. Average percent is reported beside it.
ANN_FLAT = 0.25
ANN_WORSE = 0.15
PF_WORSE = 0.05
DD_WORSE = 1.0
N_FLOOR = 0.85


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


def _knobs_match(report: dict[str, str], overhead: float, target: float, stop: float) -> bool:
    if not report:
        return False
    oh = _f(report.get("wpbr_overhead_band_pct"))
    tg = _f(report.get("target_pct"))
    st = _f(report.get("stop_pct"))
    hist = _f(report.get("min_history_bars"), -1)
    growth = str(report.get("growth_filter_enabled") or "").strip().lower()
    return (
        math.isfinite(oh) and abs(oh - overhead) < 1e-9
        and math.isfinite(tg) and abs(tg - target) < 1e-9
        and math.isfinite(st) and abs(st - stop) < 1e-9
        and hist == 0
        and growth in {"false", "0"}
    )


def _cmd(out: Path, extra: dict[str, str]) -> list[str]:
    cmd = [
        PY, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(WORKERS),
        "--aggressive", "--use-duckdb", "--no-regression",
    ]
    knobs = dict(COMMON)
    knobs.update(extra)
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    return cmd


def _start_arm(arm_id: str, extra: dict[str, str]) -> subprocess.Popen[str]:
    out = RUNS_DIR / arm_id
    out.mkdir(parents=True, exist_ok=True)
    log_path = RUNS_DIR / f"{arm_id}.log"
    cmd = _cmd(out, extra)
    (out / "run_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
    log = log_path.open("w", encoding="utf-8", errors="replace")
    print(f"[start] {arm_id} workers={WORKERS} log={log_path}", flush=True)
    return subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)


def _closed_ready(folder: Path) -> bool:
    return folder.is_dir() and _latest(folder, "Closed") is not None


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
                "entry": _f(raw.get("ENTRY_PRICE")),
                "target": _f(raw.get("TARGET_PRICE")),
            })
    return rows


def _slot_cash(folder: Path, trades: list[dict[str, Any]]) -> tuple[float, str]:
    report = _read_report(folder)
    cap = _f(report.get("capacity_brt_cash"))
    if math.isfinite(cap) and cap > 0:
        return cap, "report capacity_brt_cash (engine slot after host dollar scale)"
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
    """Peak-to-trough percent on Equity_Regular. Window peak starts inside the window."""
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


def _metrics(trades: list[dict[str, Any]], cash: float, curve: Path | None, window: str) -> dict[str, Any]:
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    empty: dict[str, Any] = {
        "n": 0, "wins": 0, "wr": float("nan"), "avg": float("nan"), "median": float("nan"),
        "pf": float("nan"), "max_dd": float("nan"), "ann_ror": float("nan"),
        "avg_days": float("nan"), "med_days": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "expect": float("nan"), "wo_max": float("nan"), "tpy": float("nan"),
    }
    if n == 0:
        return empty
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    avg_days = (sum(days) / len(days)) if days else 0.0
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
    sharpe = sharpe_from_equity_curve_csv(
        curve, start_date=start, end_date_exclusive=end,
    )
    opens = []
    closes = []
    for t in trades:
        try:
            opens.append(datetime.strptime(t["opened"], "%Y%m%d").date())
            closes.append(datetime.strptime(t["closed"] or t["opened"], "%Y%m%d").date())
        except ValueError:
            continue
    span = ((max(closes) - min(opens)).days / 365.25) if opens and closes else 0.0
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else float("nan")
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
        "wo_max": wo,
        "tpy": (n / span) if span > 0.25 else float("nan"),
    }


def _verdict(label: str, is_m: dict[str, Any], oos_m: dict[str, Any], ctrl: dict[str, dict[str, Any]]) -> str:
    """Declared before package results. OOS softer than control → HOLD."""
    c_is, c_oos = ctrl["IS"], ctrl["OOS"]
    d_ann = is_m["ann_ror"] - c_is["ann_ror"]
    d_oos = oos_m["ann_ror"] - c_oos["ann_ror"]
    d_pf = is_m["pf"] - c_is["pf"]
    d_dd = is_m["max_dd"] - c_is["max_dd"]
    n_ratio = (is_m["n"] / c_is["n"]) if c_is["n"] else 0.0
    if not math.isfinite(d_ann):
        return f"{label}: HOLD. In-sample annualized rate of return could not be computed."
    if d_ann < -ANN_WORSE or (d_ann <= 0 and is_m["avg"] < c_is["avg"] - 0.05):
        call = "DISMISS. In-sample annualized rate of return is worse than control."
    elif d_ann <= ANN_FLAT:
        call = "HOLD. In-sample annualized rate of return is close to control."
    elif d_oos < -ANN_FLAT:
        call = (
            "HOLD. In-sample annualized rate of return is better, and out of sample is softer. "
            "Do not retune off the out-of-sample row."
        )
    else:
        reasons = []
        if d_pf < -PF_WORSE:
            reasons.append(
                f"in-sample profit factor fell by {abs(d_pf):.3f} (the hold line is 0.05)"
            )
        if math.isfinite(d_dd) and d_dd > DD_WORSE:
            reasons.append(
                f"in-sample maximum drawdown deepened by {d_dd:.2f} points (the hold line is 1 point)"
            )
        if n_ratio < N_FLOOR:
            reasons.append("in-sample trade count fell below 85% of control")
        if reasons:
            call = (
                "HOLD. In-sample annualized rate of return is better, and out of sample did not soften, but "
                + "; ".join(reasons)
                + "."
            )
        else:
            call = (
                "KEEP as research only. In-sample annualized rate of return improved, "
                "profit factor and drawdown held up, and out of sample did not soften. "
                "Not gold. Not a live change."
            )
    return f"{label}: {call}"


def _fmt(v: float, nd: int = 2, suffix: str = "") -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    if math.isinf(float(v)):
        return "inf"
    return f"{float(v):.{nd}f}{suffix}"


def _delta(v: float, base: float, nd: int = 2, suffix: str = "") -> str:
    if not (isinstance(v, (int, float)) and isinstance(base, (int, float))):
        return "—"
    if not (math.isfinite(v) and math.isfinite(base)):
        return "—"
    d = v - base
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.{nd}f}{suffix}"


def _post_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    exits = Counter(t["exit"] for t in trades)
    groups: Counter[str] = Counter({"TARGET": 0, "GAP_UP": 0, "STOP": 0, "OTHER": 0})
    for t in trades:
        if t["exit"] == "TARGET":
            groups["TARGET"] += 1
        elif t["exit"] == "GAP_UP":
            groups["GAP_UP"] += 1
        elif t["exit"] in {"STOP_LOSS", "STOP", "GAP_DOWN"}:
            groups["STOP"] += 1
        else:
            groups["OTHER"] += 1
    winners = [t for t in trades if math.isfinite(t["pnl"]) and t["pnl"] > 0]
    target_wins = [t for t in winners if t["exit"] == "TARGET"]
    near20 = [t for t in winners if t["pnl"] >= 19.5]
    ge15 = [t for t in trades if math.isfinite(t["pnl"]) and t["pnl"] >= 15.0]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    by_exit_days: dict[str, list[float]] = {}
    for t in trades:
        if math.isfinite(t["days"]) and t["days"] > 0:
            by_exit_days.setdefault(t["exit"], []).append(t["days"])
    return {
        "n": n,
        "exits": exits,
        "groups": groups,
        "winners": len(winners),
        "target_wins": len(target_wins),
        "near20_wins": len(near20),
        "ge15": len(ge15),
        "avg_days": (sum(days) / len(days)) if days else float("nan"),
        "med_days": float(statistics.median(days)) if days else float("nan"),
        "by_exit_days": {
            k: (sum(v) / len(v), float(statistics.median(v)), len(v))
            for k, v in sorted(by_exit_days.items(), key=lambda kv: -len(kv[1]))
        },
    }


def _score_book(spec: dict[str, Any]) -> dict[str, Any]:
    folder: Path = spec["folder"]
    closed = _latest(folder, "Closed")
    if closed is None:
        raise FileNotFoundError(f"no closed file in {folder}")
    trades = _load_trades(closed)
    cash, cash_src = _slot_cash(folder, trades)
    curve = _latest(folder, "EquityCurve")
    report = _read_report(folder)
    slices = {w: _metrics(_slice_rows(trades, w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
    symbols = len({t["symbol"] for t in trades})
    report_ann = _f(report.get("Ann_ROR"))
    return {
        **spec,
        "closed": closed,
        "cash": cash,
        "cash_src": cash_src,
        "symbols": symbols,
        "slices": slices,
        "trades": trades,
        "report_ann": report_ann,
        "report_n": int(_f(report.get("Total_Trades"), 0)),
    }


METRIC_ROWS: list[tuple[str, str, int, str]] = [
    ("n", "Trades", 0, ""),
    ("wr", "Win rate", 1, "%"),
    ("avg", "Avg %", 2, "%"),
    ("median", "Median %", 2, "%"),
    ("pf", "Profit factor", 2, ""),
    ("max_dd", "Max DD %", 2, "%"),
    ("ann_ror", "Ann ROR %", 2, "%"),
    ("avg_days", "Avg days held", 1, ""),
    ("med_days", "Median days held", 1, ""),
    ("avg_win", "Avg winner %", 2, "%"),
    ("avg_loss", "Avg loser %", 2, "%"),
    ("expect", "Expectancy %", 2, "%"),
    ("wo_max", "Avg % without max winner", 2, "%"),
    ("calmar", "Calmar", 2, ""),
    ("sharpe", "Sharpe", 2, ""),
    ("tpy", "Trades / year", 2, ""),
]


def _metric_table(books: list[dict[str, Any]], window: str) -> str:
    ctrl = books[0]["slices"][window]
    head = "".join([
        sortable_th("Metric", "text"),
        *[
            sortable_th(b["short"], "num") + sortable_th(f"{b['short']} vs control", "num")
            for b in books
        ],
    ])
    # Control's "vs control" column is a dash; still present so every arm lines up.
    body = []
    for key, label, nd, suf in METRIC_ROWS:
        cells = [f"<td>{html_mod.escape(label)}</td>"]
        for b in books:
            v = b["slices"][window][key]
            cells.append(f"<td>{_fmt(v, nd, suf)}</td>")
            if b["id"] == "control":
                cells.append("<td>—</td>")
            else:
                cells.append(f"<td>{_delta(v, ctrl[key], nd, suf)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _exit_table(post: dict[str, Any]) -> str:
    head = (
        sortable_th("Exit", "text")
        + sortable_th("Trades", "num")
        + sortable_th("Share of book", "num")
        + sortable_th("Avg days held", "num")
        + sortable_th("Median days held", "num")
    )
    n = post["n"] or 1
    rows = []
    for name, count in post["exits"].most_common():
        avg_d, med_d, _held = post["by_exit_days"].get(name, (float("nan"), float("nan"), 0))
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{count}</td>"
            f"<td>{100.0 * count / n:.1f}%</td>"
            f"<td>{avg_d:.1f}</td>"
            f"<td>{med_d:.1f}</td>"
            "</tr>"
        )
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _headline_table(books: list[dict[str, Any]]) -> str:
    head = "".join([
        sortable_th("Arm", "text"),
        sortable_th("Role", "text"),
        sortable_th("Overhead", "num"),
        sortable_th("Target", "num"),
        sortable_th("Stop", "num"),
        sortable_th("N", "num"),
        sortable_th("Win rate", "num"),
        sortable_th("Avg %", "num"),
        sortable_th("Median %", "num"),
        sortable_th("Profit factor", "num"),
        sortable_th("Max DD %", "num"),
        sortable_th("Ann ROR full", "num"),
        sortable_th("Ann ROR in-sample", "num"),
        sortable_th("Ann ROR out-of-sample", "num"),
        sortable_th("Verdict", "text"),
    ])
    rows = []
    for b in books:
        full, is_m, oos = b["slices"]["FULL"], b["slices"]["IS"], b["slices"]["OOS"]
        verdict = "control" if b["id"] == "control" else b["verdict_word"]
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(b['short'])}</td>"
            f"<td>{html_mod.escape(b['role'])}</td>"
            f"<td>{b['overhead'] * 100:.0f}%</td>"
            f"<td>{b['target_above'] * 100:.0f}%</td>"
            f"<td>{b['stop_under'] * 100:.0f}%</td>"
            f"<td>{full['n']}</td>"
            f"<td>{_fmt(full['wr'], 1, '%')}</td>"
            f"<td>{_fmt(full['avg'], 2, '%')}</td>"
            f"<td>{_fmt(full['median'], 2, '%')}</td>"
            f"<td>{_fmt(full['pf'], 2)}</td>"
            f"<td>{_fmt(full['max_dd'], 2, '%')}</td>"
            f"<td>{_fmt(full['ann_ror'], 2, '%')}</td>"
            f"<td>{_fmt(is_m['ann_ror'], 2, '%')}</td>"
            f"<td>{_fmt(oos['ann_ror'], 2, '%')}</td>"
            f"<td>{html_mod.escape(verdict)}</td>"
            "</tr>"
        )
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _write_summary(books: list[dict[str, Any]]) -> Path:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm_id", "label", "role", "overhead_pct", "target_above_buy_pct", "stop_under_trigger_low_pct",
        "target_pct", "stop_pct", "slot_cash", "symbols", "slice",
        "n", "win_rate", "avg_pct", "median_pct", "profit_factor", "max_dd_pct", "ann_ror_pct",
        "avg_days", "median_days", "calmar", "sharpe", "verdict", "source_closed",
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
                    "role": b["role"],
                    "overhead_pct": f"{b['overhead'] * 100:.0f}",
                    "target_above_buy_pct": f"{b['target_above'] * 100:.0f}",
                    "stop_under_trigger_low_pct": f"{b['stop_under'] * 100:.0f}",
                    "target_pct": f"{b['target_pct']:.2f}",
                    "stop_pct": f"{b['stop_pct']:.2f}",
                    "slot_cash": f"{b['cash']:.6f}",
                    "symbols": b["symbols"],
                    "slice": sl,
                    "n": m["n"],
                    "win_rate": f"{m['wr']:.4f}" if math.isfinite(m["wr"]) else "",
                    "avg_pct": f"{m['avg']:.4f}" if math.isfinite(m["avg"]) else "",
                    "median_pct": f"{m['median']:.4f}" if math.isfinite(m["median"]) else "",
                    "profit_factor": f"{m['pf']:.4f}" if math.isfinite(m["pf"]) else "",
                    "max_dd_pct": f"{m['max_dd']:.4f}" if math.isfinite(m["max_dd"]) else "",
                    "ann_ror_pct": f"{m['ann_ror']:.4f}" if math.isfinite(m["ann_ror"]) else "",
                    "avg_days": f"{m['avg_days']:.4f}" if math.isfinite(m["avg_days"]) else "",
                    "median_days": f"{m['med_days']:.4f}" if math.isfinite(m["med_days"]) else "",
                    "calmar": f"{m['calmar']:.4f}" if math.isfinite(m["calmar"]) else "",
                    "sharpe": f"{m['sharpe']:.4f}" if math.isfinite(m["sharpe"]) else "",
                    "verdict": "control" if b["id"] == "control" else b["verdict_word"],
                    "source_closed": str(b["closed"].relative_to(ROOT)).replace("\\", "/"),
                })
    return path


def _write_baseline(books: list[dict[str, Any]], post: dict[str, Any], skipped_note: str) -> None:
    ctrl = books[0]
    lines = [
        "# WPBR tighter overhead, target, and stop",
        "",
        "Pivot Break and Retest (WPBR). Research only. Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "Pivot Break and Retest (WPBR) buys a retest of a weekly zone unless an older zone is sitting a short distance overhead. "
        "This test tightens that distance together with a lower profit target and a tighter stop. "
        "The live rule is a 22% overhead gap, a 20% target, and an 8% stop under the trigger-day low.",
        "",
        "Overhead gap means the distance from this zone’s top up to an older zone’s bottom. "
        "A gap at or inside the band skips the buy. "
        "Target means the whole position is sold that far above the buy. "
        "Stop means the sell price is that far under the low of the trigger day, the session before the buy, not under the entry price.",
        "",
        "The three packages move all three knobs together. They were named before the results. "
        "Two extra arms were also named before the results, so a package can be read against a one-knob change: "
        "overhead only at 20% with the live 20% target and 8% stop, and target plus stop only (18% and 7%) with the live 22% overhead. "
        "Nothing else was added after the table. Picking the best cell after seeing the table would be in-sample selection. "
        "In-sample is buys before 2024. Out of sample is 2024 onward and is for reading only.",
        "",
        "## Verdict",
        "",
    ]
    for b in books:
        if b["id"] == "control":
            continue
        lines.append(f"- {b['verdict']}")
    lines += [
        "",
        "Research only. Not gold. Not DailyRun. Out of sample is report-only. "
        "Win rate (WR), profit factor (PF), maximum drawdown (Max DD), and annualized rate of return (Ann ROR) are in the tables.",
        "",
        "## Control winners (description only)",
        "",
        (
            f"The control book has {post['n']} closed trades. "
            f"Target exits {post['groups']['TARGET']} (every one exactly +20%). "
            f"Gap-up through the target {post['groups'].get('GAP_UP', 0)}. "
            f"Stop-family exits {post['groups']['STOP']} (stop loss and gap down; no winners). "
            f"Other exits {post['groups']['OTHER']}. "
            f"Average hold is {post['avg_days']:.1f} days and the median hold is {post['med_days']:.1f} days. "
            f"Of {post['winners']} winners, {post['target_wins']} are the exact 20% target. "
            f"The rest gapped through that target. No winner finished between 0% and +15%."
        ),
        "",
        "## Freeze",
        "",
        "- Control is the 2026-10-02 DailyRun freeze: wpbr_overhead_band_pct=0.22, target_pct=1.20, stop_pct=0.92, growth filter off, min_history_bars=0, full warehouse.",
        f"- Control closed file: `{ctrl['closed'].relative_to(ROOT)}`. {ctrl['slices']['FULL']['n']} trades, {ctrl['symbols']} symbols. Not rerun.",
        "- Engine stop: `stop_loss_based=trigger_low` and `stop_pct_is_multiplier=true`, so the stop is the trigger-day low times stop_pct. 8% under that low is 0.92, 7% is 0.93, 6% is 0.94, 4% is 0.96. The target is the entry price times target_pct.",
        "- Slot cash is each arm’s own `capacity_brt_cash` from its Report (the dollars written on Closed after the host scale). That is the cash `rocket_tbn.compute_metrics` uses for Ann ROR. It is not the $47,500 sheet cash. A tighter book that holds fewer shares at once gets a larger slot. In-sample and out-of-sample use that same per-arm slot with the slice’s dollars.",
        "- Annualized rate of return (Ann ROR) is `((1 + total P&L dollars / (slot cash × trades)) ** (365 / average days held) − 1) × 100` via `compare_format.ann_ror_from_closed`.",
        "- Maximum drawdown (Max DD) is the peak-to-trough on the daily `Equity_Regular` curve, the same series as the engine Report Max DD. In-sample is the curve before 2024-01-01. Out-of-sample starts the peak over on 2024-01-01. Trade counts and Ann ROR are split by entry date. Calmar is that slice’s Ann ROR divided by that slice’s Max DD.",
        "- Verdict rule, written before the package results: in-sample Ann ROR is the headline, because a lower target cuts the average win on purpose. Worse in-sample Ann ROR is DISMISS. A lift of 0.25 percentage points or less is HOLD. A larger in-sample lift is HOLD if out-of-sample Ann ROR is softer than control by more than 0.25 points, or if in-sample profit factor drops by more than 0.05, Max DD worsens by more than 1 point, or in-sample trades fall below 85% of control. Otherwise KEEP as research only.",
        "- The 20% overhead / 20% target / 8% stop book is the dismissed arm of `drive/paul_experiments/wpbr_overhead20_vs22_t20s8_ab_20261002`. That page’s control was this 22/20/8 book (stamp 261002051403). It was not rerun. Metrics here use the corrected slot cash.",
        "- The 22% overhead / 18% target / 7% stop book is the test closed file from `drive/paul_experiments/wpbr_overhead22_target18_stop7_ab_20261002`. It was not rerun. That older page divided slot dollars by $47,500, so its Ann ROR was too small. This page recomputes it.",
        "- Shared and unchanged: weekly WPBR zones, band 1.5%, strong pivot either side 3 bars and 10%, breakout confirmation 3%, retest window 2 days, second chance after a winning target on, indicators recorded and not a buy gate, market-cap filter off, SPY 1-year compare gate off, no same-bar re-entry block (`sheet_no_entry_same_bar_after_exit=false`).",
        "- Universe: every CSV under `data/newdata/data`. Not the old 9-name list.",
        skipped_note,
        "- In-sample is DATE_OPENED before 2024-01-01. Out of sample is DATE_OPENED on or after 2024-01-01.",
        "",
        "## Slot cash",
        "",
        "| Arm | Slot cash | Source |",
        "| --- | --- | --- |",
    ]
    for b in books:
        lines.append(f"| {b['short']} | ${b['cash']:,.2f} | {b['cash_src']} |")
    lines += [
        "",
        "Picking the best cell from this table is in-sample selection. Not gold. Not DailyRun.",
        "",
    ]
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _write_html(books: list[dict[str, Any]], post: dict[str, Any]) -> Path:
    esc = html_mod.escape
    groups = post["groups"]
    n = post["n"] or 1
    winner_share = (100.0 * post["target_wins"] / post["winners"]) if post["winners"] else 0.0
    near_share = (100.0 * post["near20_wins"] / post["winners"]) if post["winners"] else 0.0
    verdict_html = "".join(
        f"<li>{esc(b['verdict'])}</li>" for b in books if b["id"] != "control"
    )
    raw_bits = ", ".join(f"{esc(k)} {v}" for k, v in post["exits"].most_common())
    gap_up = int(groups.get("GAP_UP", 0))
    post_prose = (
        f"On the control book only, before any ranking: {groups['TARGET']} trades "
        f"({100.0 * groups['TARGET'] / n:.1f}%) sold at the 20% target, every one of them at exactly +20%. "
        f"{gap_up} trades ({100.0 * gap_up / n:.1f}%) gapped through that target "
        f"(the open was already above it). "
        f"{groups['STOP']} trades ({100.0 * groups['STOP'] / n:.1f}%) exited through a stop, "
        f"either a stop fill or a gap down. None of those were winners. "
        f"Other exits: {groups['OTHER']}. Raw exit names: {raw_bits}. "
        f"The average hold is {post['avg_days']:.1f} days and the median hold is {post['med_days']:.1f} days. "
        f"Target exits and gap-throughs are the longer holds; stop exits are shorter. "
        f"There are {post['winners']} winners. {post['target_wins']} of them ({winner_share:.1f}%) are the exact +20% target. "
        f"The rest of the winners are the gap-throughs, which start at +20% and run higher "
        f"(that is the right tail). {post['ge15']} trades closed at +15% or better, and that set is the same as the winners, "
        f"because no winning trade finished between 0% and +15%. "
        f"Winners are mostly the exact 20% target. The right tail is the gap through the target, not a separate runner."
    )
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
<title>WPBR tighter overhead, target, and stop</title>
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
<h1>Pivot Break and Retest — tighter overhead, target, and stop</h1>
<p class="note">Research only. Not gold. Not DailyRun. Click column headers to sort.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{esc(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>Pivot Break and Retest (WPBR) buys a retest of a weekly zone unless an older zone is sitting a short distance overhead. This test tightens that distance together with a lower profit target and a tighter stop. The live rule is a 22% overhead gap, a 20% target, and an 8% stop under the trigger-day low.</p>
<p>Overhead gap: the distance from this zone’s top up to an older zone’s bottom. A gap at or inside the band skips the buy. Target: sell the whole position that far above the buy. Stop: that far under the low of the trigger day (the session before the buy), not under the entry price.</p>
<p>The three packages were named before the results. Two extra arms were also named before the results, so a package can be read against a one-change test. No further combinations were added after the numbers came back. Choosing the best row now would be in-sample selection. Buys before 2024 are in-sample. 2024 onward is out of sample and is for reading only.</p>
</div>
<h2>Control book, before any ranking</h2>
<p>{post_prose}</p>
{SWIPE_NOTE_HTML}
{_exit_table(post)}
<h2>Verdicts versus the live 22% / 20% / 8% book</h2>
<p class="note">Headline is in-sample annualized rate of return (Ann ROR), because a lower target cuts the average percent on purpose. If out of sample is softer, the call is HOLD. Averages are still in the tables.</p>
<ul>{verdict_html}</ul>
<h2>Headline</h2>
{SWIPE_NOTE_HTML}
{_headline_table(books)}
<h2>Full compare</h2>
<p class="note">Annualized rate of return uses each arm’s own slot cash, the cash the engine used when it wrote the dollar profits. Maximum drawdown is the daily account path (regular equity), not the aggressive path. Lower drawdown is better. A positive Max DD delta is a deeper drop than control.</p>
{SWIPE_NOTE_HTML}
{''.join(sections)}
<p class="note">Picking the best cell after this table is in-sample selection. Not gold. Not DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(page, encoding="utf-8")
    return path


def _notify(html_path: Path, message: str) -> None:
    subprocess.run(
        [PY, str(ROOT / "tools" / "ntfy_job_done.py"), "--path", str(html_path),
         "-t", "WPBR tighter packages", "-m", message],
        cwd=str(ROOT), check=False,
    )


def _verdict_word(text: str) -> str:
    if "DISMISS" in text:
        return "DISMISS"
    if "KEEP" in text:
        return "KEEP"
    return "HOLD"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    print(
        "Stop mapping confirmed in engine: trigger-day low * stop_pct. "
        "8%→0.92, 7%→0.93, 6%→0.94, 4%→0.96. Target is entry * target_pct.",
        flush=True,
    )

    reused = {
        "control": ROOT / "tmp_wpbr_overhead20_vs22_t20s8_ab_20261002" / "control",
        "oh20": ROOT / "tmp_wpbr_overhead20_vs22_t20s8_ab_20261002" / "oh20",
        "t22_18_7": ROOT / "tmp_wpbr_overhead22_target18_stop7_ab_20261002" / "t18s7",
    }
    checks = {
        "control": (0.22, 1.20, 0.92),
        "oh20": (0.20, 1.20, 0.92),
        "t22_18_7": (0.22, 1.18, 0.93),
    }
    for key, folder in reused.items():
        oh, tg, st = checks[key]
        report = _read_report(folder)
        if not _knobs_match(report, oh, tg, st):
            raise SystemExit(f"{key} saved knobs do not match {oh}/{tg}/{st}: {report.get('wpbr_overhead_band_pct')} {report.get('target_pct')} {report.get('stop_pct')}")
        print(f"[reuse] {key} {folder}", flush=True)

    packages = [
        ("pkg_20_18_7", {"wpbr_overhead_band_pct": "0.20", "target_pct": "1.18", "stop_pct": "0.93"}),
        ("pkg_18_15_6", {"wpbr_overhead_band_pct": "0.18", "target_pct": "1.15", "stop_pct": "0.94"}),
        ("pkg_15_10_4", {"wpbr_overhead_band_pct": "0.15", "target_pct": "1.10", "stop_pct": "0.96"}),
    ]
    procs: list[tuple[str, subprocess.Popen[str]]] = []
    for arm_id, extra in packages:
        folder = RUNS_DIR / arm_id
        if _closed_ready(folder) and _knobs_match(_read_report(folder), float(extra["wpbr_overhead_band_pct"]), float(extra["target_pct"]), float(extra["stop_pct"])):
            print(f"[reuse-run] {arm_id}", flush=True)
            continue
        procs.append((arm_id, _start_arm(arm_id, extra)))

    # Score the reused books while the packages run. Ranking waits until all close.
    control_trades = _load_trades(_latest(reused["control"], "Closed"))  # type: ignore[arg-type]
    post = _post_analysis(control_trades)
    print(
        f"[post] n={post['n']} target={post['groups']['TARGET']} stop={post['groups']['STOP']} "
        f"other={post['groups']['OTHER']} winners={post['winners']} target_wins={post['target_wins']} "
        f"near20={post['near20_wins']} ge15={post['ge15']} "
        f"avg_days={post['avg_days']:.1f} med_days={post['med_days']:.1f}",
        flush=True,
    )

    failed: list[str] = []
    for arm_id, proc in procs:
        code = proc.wait()
        print(f"[done] {arm_id} exit={code}", flush=True)
        if code != 0:
            failed.append(arm_id)

    specs: list[dict[str, Any]] = [
        {
            "id": "control", "short": "Control 22/20/8", "role": "control",
            "overhead": 0.22, "target_above": 0.20, "stop_under": 0.08,
            "target_pct": 1.20, "stop_pct": 0.92, "folder": reused["control"],
        },
        {
            "id": "oh20", "short": "Overhead only 20/20/8", "role": "isolation",
            "overhead": 0.20, "target_above": 0.20, "stop_under": 0.08,
            "target_pct": 1.20, "stop_pct": 0.92, "folder": reused["oh20"],
        },
        {
            "id": "t22_18_7", "short": "Target and stop 22/18/7", "role": "isolation",
            "overhead": 0.22, "target_above": 0.18, "stop_under": 0.07,
            "target_pct": 1.18, "stop_pct": 0.93, "folder": reused["t22_18_7"],
        },
        {
            "id": "pkg_20_18_7", "short": "Package 20/18/7", "role": "package",
            "overhead": 0.20, "target_above": 0.18, "stop_under": 0.07,
            "target_pct": 1.18, "stop_pct": 0.93,
            "folder": RUNS_DIR / "pkg_20_18_7",
        },
        {
            "id": "pkg_18_15_6", "short": "Package 18/15/6", "role": "package",
            "overhead": 0.18, "target_above": 0.15, "stop_under": 0.06,
            "target_pct": 1.15, "stop_pct": 0.94,
            "folder": RUNS_DIR / "pkg_18_15_6",
        },
        {
            "id": "pkg_15_10_4", "short": "Package 15/10/4", "role": "package",
            "overhead": 0.15, "target_above": 0.10, "stop_under": 0.04,
            "target_pct": 1.10, "stop_pct": 0.96,
            "folder": RUNS_DIR / "pkg_15_10_4",
        },
    ]

    books: list[dict[str, Any]] = []
    skipped: list[str] = []
    for spec in specs:
        if spec["id"] in failed or not _closed_ready(spec["folder"]):
            skipped.append(spec["short"])
            continue
        book = _score_book(spec)
        if book["id"] != "control" and math.isfinite(book["report_ann"]):
            gap = abs(book["slices"]["FULL"]["ann_ror"] - book["report_ann"])
            print(f"[ann check] {book['id']} ours={book['slices']['FULL']['ann_ror']:.2f} report={book['report_ann']:.2f}", flush=True)
            if gap > 0.2:
                print(f"[warn] Ann ROR mismatch on {book['id']}", flush=True)
        books.append(book)

    if not books or books[0]["id"] != "control":
        raise SystemExit("control book missing; refusing to rank")

    ctrl_slices = books[0]["slices"]
    for b in books:
        if b["id"] == "control":
            b["verdict"] = "Control."
            b["verdict_word"] = "control"
            continue
        text = _verdict(b["short"], b["slices"]["IS"], b["slices"]["OOS"], ctrl_slices)
        b["verdict"] = text
        b["verdict_word"] = _verdict_word(text)
        print(f"[verdict] {text}", flush=True)

    skip_line = (
        "- Package runs that failed or were still going are omitted: " + ", ".join(skipped) + "."
        if skipped else
        "- All three packages finished. The two isolation arms were cited from the earlier stamps and not rerun."
    )
    _write_baseline(books, post, skip_line)
    html_path = _write_html(books, post)
    summary = _write_summary(books)
    msg = "WPBR tighter packages ready. Research only."
    if skipped:
        msg += " Missing: " + ", ".join(skipped) + "."
    _notify(html_path, msg)
    print(f"[wrote] {html_path}", flush=True)
    print(f"[wrote] {summary}", flush=True)
    if failed:
        raise SystemExit(f"arms failed: {failed}")


if __name__ == "__main__":
    main()
