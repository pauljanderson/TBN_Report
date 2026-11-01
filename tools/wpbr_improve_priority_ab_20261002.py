"""Score the pre-declared WPBR improve-priority arms. Does not launch the engine.

Control is the live 22% overhead / 20% target / 8% stop book
(stamp 261002051403). It is not rerun.

Arms (named from the priority page before these P&L numbers):
- target15: target 15% only. Answers slow trips to the 20% target.
- stop15rs: stop 15% under the trigger-day low only. That is the
  Relative Strength peer stop risk printed on the priority page (15.0%).
- time100: sell at 100 bars if still open. Answers the same slow-target
  note with the page's alternate time cap. One knob.

Research only. Out of sample is report-only. Not gold. Not DailyRun.
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

IS_CUT = "20240101"
IS_DATE = date(2024, 1, 1)
OUT_DIR = ROOT / "drive" / "paul_experiments" / "wpbr_improve_priority_ab_20261002"
RUNS = ROOT / "tmp_wpbr_improve_priority_20261002"
CONTROL_DIR = ROOT / "tmp_wpbr_overhead20_vs22_t20s8_ab_20261002" / "control"
PY = sys.executable

ANN_FLAT = 0.25
ANN_WORSE = 0.15
PF_WORSE = 0.05
DD_WORSE = 1.0
N_FLOOR = 0.85

REQUEST_QUOTE = (
    "great - now wire up and run some potential solutions to solve the items listed here: "
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "wpbr_tighter_overhead_target_stop_ab_20261002/control_ImprovePriority.html"
)

ARMS: list[dict[str, Any]] = [
    {
        "id": "control",
        "short": "Control 22/20/8",
        "folder": CONTROL_DIR,
        "role": "Live book, not rerun",
        "priority": "Baseline",
        "overhead": 0.22,
        "target_above": 0.20,
        "stop_under": 0.08,
        "time_stop": 0,
        "change": "None",
    },
    {
        "id": "target15",
        "short": "Closer target 15%",
        "folder": RUNS / "target15",
        "role": "One change: target 15%",
        "priority": "slow_target_grind (and the closer-target side of the mixed target note)",
        "overhead": 0.22,
        "target_above": 0.15,
        "stop_under": 0.08,
        "time_stop": 0,
        "change": "target_pct 1.15",
    },
    {
        "id": "stop15rs",
        "short": "Wider stop 15% (RS)",
        "folder": RUNS / "stop15rs",
        "role": "One change: stop 15% under the trigger-day low",
        "priority": "peer_wider_stop_won_rs (and the wider-stop lean on stops that bounce back)",
        "overhead": 0.22,
        "target_above": 0.20,
        "stop_under": 0.15,
        "time_stop": 0,
        "change": "stop_pct 0.85",
    },
    {
        "id": "time100",
        "short": "Time cap 100 bars",
        "folder": RUNS / "time100",
        "role": "One change: sell after 100 bars",
        "priority": "slow_target_grind alternate: shorter time stop",
        "overhead": 0.22,
        "target_above": 0.20,
        "stop_under": 0.08,
        "time_stop": 100,
        "change": "time_stop_days 100",
    },
]

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
        reasons.append(f"in-sample profit factor fell by {abs(d_pf):.3f} (the hold line is 0.05)")
    if math.isfinite(d_dd) and d_dd > DD_WORSE:
        reasons.append(
            f"in-sample maximum drawdown deepened by {d_dd:.2f} points (the hold line is 1 point)"
        )
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
    return f"{float(v):.{nd}f}{suffix}"


def _delta(v: float, base: float, nd: int = 2, suffix: str = "") -> str:
    if not (isinstance(v, (int, float)) and isinstance(base, (int, float))):
        return "—"
    if not (math.isfinite(v) and math.isfinite(base)):
        return "—"
    d = v - base
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.{nd}f}{suffix}"


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
    symbols = len({t["symbol"] for t in trades if t["symbol"]})
    return {
        **spec,
        "closed": str(closed),
        "slot_cash": cash,
        "slot_src": cash_src,
        "symbols": symbols,
        "slices": slices,
        "exits": exits,
        "n_full": slices["FULL"]["n"],
    }


def _metric_table(books: list[dict[str, Any]], window: str) -> str:
    ctrl = books[0]["slices"][window]
    head = "".join([
        sortable_th("Metric", "text"),
        *[
            sortable_th(b["short"], "num") + sortable_th(f"{b['short']} vs control", "num")
            for b in books
        ],
    ])
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


def _headline_table(books: list[dict[str, Any]]) -> str:
    head = "".join([
        sortable_th("Arm", "text"),
        sortable_th("Priority it answers", "text"),
        sortable_th("One change", "text"),
        sortable_th("N", "num"),
        sortable_th("Win rate", "num"),
        sortable_th("Avg %", "num"),
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
            f"<td>{html_mod.escape(b['priority'])}</td>"
            f"<td>{html_mod.escape(b['change'])}</td>"
            f"<td>{full['n']}</td>"
            f"<td>{_fmt(full['wr'], 1, '%')}</td>"
            f"<td>{_fmt(full['avg'], 2, '%')}</td>"
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


def _write_summary(books: list[dict[str, Any]]) -> Path:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm_id", "label", "priority", "one_change", "slice",
        "n", "win_rate", "avg_pct", "profit_factor", "max_dd_pct", "ann_ror_pct",
        "median_pct", "avg_days", "median_days", "calmar", "sharpe",
        "avg_win_pct", "avg_loss_pct", "expectancy_pct", "avg_pct_wo_max", "trades_per_year",
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
                    "priority": b["priority"],
                    "one_change": b["change"],
                    "slice": sl,
                    "n": m["n"],
                    "win_rate": m["wr"],
                    "avg_pct": m["avg"],
                    "profit_factor": m["pf"],
                    "max_dd_pct": m["max_dd"],
                    "ann_ror_pct": m["ann_ror"],
                    "median_pct": m["median"],
                    "avg_days": m["avg_days"],
                    "median_days": m["med_days"],
                    "calmar": m["calmar"],
                    "sharpe": m["sharpe"],
                    "avg_win_pct": m["avg_win"],
                    "avg_loss_pct": m["avg_loss"],
                    "expectancy_pct": m["expect"],
                    "avg_pct_wo_max": m["wo_max"],
                    "trades_per_year": m["tpy"],
                    "slot_cash": b["slot_cash"],
                    "verdict": "" if b["id"] == "control" else b["verdict"],
                    "source_closed": b["closed"],
                })
    return path


def _write_baseline(books: list[dict[str, Any]]) -> None:
    lines = [
        "# WPBR improve-priority tests",
        "",
        "Pivot Break and Retest (WPBR). Research only. Not gold. Not DailyRun. Nothing was adopted.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "The standard post-run page listed problems on the live book: slow trips to the 20% target, "
        "stops that recover, and other systems doing better on the same names. Each test changes one "
        "thing to answer one of those notes.",
        "",
        "Pivot Break and Retest buys a retest of a weekly zone. The live rule is a 22% overhead gap, "
        "a 20% target, and an 8% stop under the trigger-day low (the session before the buy), not under "
        "the entry price. Relative Strength is another system whose wider stop beat this book on overlapping "
        "trades. Annualized rate of return is how fast the book compounds once hold time and slot size are counted.",
        "",
        "## Arms (named before these results)",
        "",
        "- Closer target 15%: answers `slow_target_grind` (781 target exits held 100 days or more) and the "
        "closer-target side of the mixed target note. The page does not name a closer percent, so the "
        "pre-declared test is 15% (`target_pct=1.15`). Overhead stays 22%. Stop stays 8% (`stop_pct=0.92`).",
        "- Wider stop 15%: answers `peer_wider_stop_won_rs` and the page's lean to a wider stop when stops "
        "snap back above entry. The page prints Relative Strength stop risk of 15.0% (examples such as ALGN "
        "and ANET). This arm uses that distance: 15% under the trigger-day low (`stop_pct=0.85`). It is still "
        "a Pivot Break and Retest stop measured from the trigger-day low, not a copy of the other system's entry stop. "
        "Overhead stays 22%. Target stays 20%.",
        "- Time cap 100 bars: answers the same slow-target note through the page's alternate lever, a shorter "
        "time stop. `time_stop_days=100` sells at the close once the trade has been open 100 bars, if the "
        "target or stop has not already filled. Overhead, target, and stop stay at the live settings.",
        "",
        "A “do not sell at the target and hold longer” arm was not run. The high-confidence longer-hold note "
        "is Rocket Launcher still in the trade after this system stopped out. That is the wider-stop question, "
        "which the 15% stop arm tests. Turning the target off is not a single named setting on the page, and "
        "the mixed target card says to pick one direction. The direction picked was the closer target.",
        "",
        "The 15/10/4 neighborhood grid was not rerun. These three engines were started while the machine was idle. "
        "They did not wait for that grid to finish.",
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
        "Research only. Not gold. Not DailyRun. Out of sample is report-only. Do not adopt.",
        "",
        "Verdict bar, written before these results: in-sample annualized rate of return is the headline. "
        "Worse than control is DISMISS. A lift of 0.25 percentage points or less is HOLD. A higher in-sample "
        "annualized rate of return with a worse average percent and a worse profit factor is HOLD. A larger "
        "in-sample lift is HOLD if out-of-sample annualized rate of return is softer than control by more than "
        "0.25 points, or if in-sample profit factor drops by more than 0.05, maximum drawdown worsens by more "
        "than 1 point, or in-sample trades fall below 85% of control. Otherwise KEEP as research only.",
        "",
        "## Freeze",
        "",
        "- Control closed file: `tmp_wpbr_overhead20_vs22_t20s8_ab_20261002/control/WPBR_Closed_261002051403.csv`. "
        "Not rerun. Growth filter off, `min_history_bars=0`, full warehouse.",
        "- Engine stop: trigger-day low times `stop_pct`. 8% under that low is 0.92. 15% under that low is 0.85.",
        "- Slot cash is each arm’s own `capacity_brt_cash` from its Report. It is not $47,500. In-sample and "
        "out-of-sample use that same per-arm slot with the slice’s dollars.",
        "- Annualized rate of return is `((1 + total P&L dollars / (slot cash × trades)) ** (365 / average days held) − 1) × 100` "
        "via `compare_format.ann_ror_from_closed`.",
        "- Maximum drawdown is the peak-to-trough on the daily `Equity_Regular` curve. In-sample is the curve "
        "before 2024-01-01. Out-of-sample starts the peak over on 2024-01-01. Trade counts and annualized rate "
        "of return are split by entry date.",
        "- Profit factor is the sum of winning percents divided by the absolute sum of losing percents, the same "
        "definition as the tighter-package page this bar comes from.",
        "- In-sample is DATE_OPENED before 2024-01-01. Out of sample is DATE_OPENED on or after 2024-01-01.",
        "- Picking the best row after seeing this table is in-sample selection.",
        "",
        "## Slot cash",
        "",
        "| Arm | Slot cash | Source |",
        "| --- | --- | --- |",
    ]
    for b in books:
        lines.append(f"| {b['short']} | ${b['slot_cash']:,.2f} | {b['slot_src']} |")
    lines.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _write_html(books: list[dict[str, Any]]) -> Path:
    esc = html_mod.escape
    verdict_html = "".join(
        f"<li>{esc(b['verdict'])}</li>" for b in books if b["id"] != "control"
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
<title>WPBR improve-priority tests</title>
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
<h1>Pivot Break and Retest — improve-priority tests</h1>
<p class="note">Research only. Not gold. Not DailyRun. Click column headers to sort. Swipe sideways to see more columns.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{esc(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>The standard post-run page listed problems on the live book: slow trips to the 20% target, stops that recover, and other systems doing better on the same names. Each test changes one thing to answer one of those notes.</p>
<p>Pivot Break and Retest buys a retest of a weekly zone. The live rule keeps a 22% overhead gap, a 20% target, and an 8% stop under the trigger-day low. Relative Strength is the other system whose wider stop beat this book on overlapping names. Annualized rate of return counts how fast the book compounds after hold time and the cash tied up in one slot.</p>
<p>The closer-target test sells at 15% instead of 20%, so capital is not tied up waiting on the slow trips. The wider-stop test places the stop 15% under the trigger-day low, the stop distance the page prints for Relative Strength, so a dip that later recovers is less likely to kick the trade out. The time-cap test sells after 100 bars if the 20% target or the stop has not already filled. Nothing else moves. Buys before 2024 are in-sample. 2024 onward is out of sample and is for reading only.</p>
</div>
<h2>What was skipped</h2>
<p>A “do not sell at the target and hold longer” test was not added. The page’s longer-hold note is Rocket Launcher still holding after this system had already stopped out. That question is the wider stop, which has its own arm. Turning the target off is not a single named setting, and the mixed target card says to pick one direction. The direction tested is the closer target. The 15/10/4 neighborhood was not rerun.</p>
<h2>Verdicts versus the live 22% / 20% / 8% book</h2>
<p class="note">The call uses in-sample quality. A higher in-sample annualized rate of return (Ann ROR) with a worse average and a worse profit factor is HOLD. Out of sample is report-only. These are not live changes.</p>
<ul>{verdict_html}</ul>
<h2>Headline</h2>
{SWIPE_NOTE_HTML}
{_headline_table(books)}
<h2>Exit mix</h2>
{SWIPE_NOTE_HTML}
{_exit_table(books)}
<h2>Full compare</h2>
<p class="note">Annualized rate of return uses each arm’s own slot cash, the cash the engine used when it wrote the dollar profits. It is not the $47,500 sheet cash. Maximum drawdown is the daily regular equity path. A positive Max DD delta is a deeper drop than control.</p>
{SWIPE_NOTE_HTML}
{''.join(sections)}
<p class="note">Picking the best cell after this table is in-sample selection. Not gold. Not DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
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
    summary = _write_summary(books)
    _write_baseline(books)
    html_path = _write_html(books)
    print(f"wrote {html_path}", flush=True)
    print(f"wrote {summary}", flush=True)
    subprocess.run(
        [
            PY, str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path", str(html_path),
            "-t", "WPBR priority tests",
        ],
        cwd=str(ROOT),
        check=False,
    )


if __name__ == "__main__":
    main()
