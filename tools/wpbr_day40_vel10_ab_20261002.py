"""WPBR Day-40 velocity (+10% High) A/B — score control vs test and publish stamp.

CONTROL: live run_wpbr.bat freeze (22% overhead / +20% target / -8% stop), reused from
tmp_wpbr_velocity_cols_rerun_20261002 (stamp 261002172253) — no velocity exit.

TEST: identical except wpbr_velocity_time_stop_bars=40 and
wpbr_velocity_time_stop_min_gain=0.10 (exit type WPBR_VEL_TS40).

Research only. EXIT one-knob. IS cut entry_date < 2024-01-01. OOS report-only.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import shutil
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
OUT_DIR = ROOT / "drive" / "paul_experiments" / "wpbr_day40_vel10_ab_20261002"
RUNS = ROOT / "tmp_wpbr_day40_vel10_ab_20261002"
CONTROL_DIR = RUNS / "control"
TEST_DIR = RUNS / "test"
PY = sys.executable
VEL_EXIT = "WPBR_VEL_TS40"

ANN_FLAT = 0.25
ANN_WORSE = 0.15
PF_WORSE = 0.05
DD_WORSE = 1.0
N_FLOOR = 0.85

REQUEST_QUOTE = (
    "Run one WPBR A/B test. CONTROL: Current 22% overhead / +20% target / -8% stop system. "
    "TEST: Identical system, except exit at the Day-40 CLOSE if the trade has NOT reached "
    "+10% from entry at any point during its first 40 trading bars. Use intraday HIGH to "
    "determine whether +10% was reached. Change nothing else. Report IS, OOS, and FULL with "
    "trade count, WR, Avg P&L, PF, Expectancy, Max DD, Ann ROR, Avg/Median Days Held, "
    "Capital Days, Sharpe, and PPCD. Also report the number of Day-40 velocity exits and "
    "their average exit P&L. include compare, closed reports and put in Pauls experiments folder"
)

ARMS: list[dict[str, Any]] = [
    {
        "id": "control",
        "short": "Control 22/20/8",
        "folder": CONTROL_DIR,
        "change": "None (velocity exit off)",
    },
    {
        "id": "test",
        "short": "Day-40 vel +10%",
        "folder": TEST_DIR,
        "change": "wpbr_velocity_time_stop_bars=40; min_gain=0.10",
    },
]

METRIC_ROWS: list[tuple[str, str, int, str]] = [
    ("n", "Trades", 0, ""),
    ("wr", "Win rate (WR)", 1, "%"),
    ("avg", "Avg P&L %", 2, "%"),
    ("pf", "Profit factor (PF)", 2, ""),
    ("expect", "Expectancy %", 2, "%"),
    ("max_dd", "Max DD %", 2, "%"),
    ("ann_ror", "Ann ROR %", 2, "%"),
    ("avg_days", "Avg days held", 1, ""),
    ("med_days", "Median days held", 1, ""),
    ("capital_days", "Capital Days", 0, ""),
    ("sharpe", "Sharpe", 2, ""),
    ("ppcd", "PPCD $", 2, ""),
    ("median", "Median P&L %", 2, "%"),
    ("avg_win", "Avg winner %", 2, "%"),
    ("avg_loss", "Avg loser %", 2, "%"),
    ("calmar", "Calmar", 2, ""),
    ("tpy", "Trades / year", 2, ""),
    ("vel_n", "Day-40 velocity exits", 0, ""),
    ("vel_avg", "Day-40 vel avg P&L %", 2, "%"),
    ("vel_avg_d", "Day-40 vel avg P&L $", 2, ""),
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


def _vel_stats(trades: list[dict[str, Any]]) -> tuple[int, float, float]:
    vel = [t for t in trades if t["exit"] == VEL_EXIT]
    if not vel:
        return 0, float("nan"), float("nan")
    pnls = [t["pnl"] for t in vel if math.isfinite(t["pnl"])]
    dols = [t["pnl_d"] for t in vel if math.isfinite(t["pnl_d"])]
    avg = (sum(pnls) / len(pnls)) if pnls else float("nan")
    avg_d = (sum(dols) / len(dols)) if dols else float("nan")
    return len(vel), avg, avg_d


def _metrics(trades: list[dict[str, Any]], cash: float, curve: Path | None, window: str) -> dict[str, Any]:
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    empty: dict[str, Any] = {
        "n": 0, "wins": 0, "wr": float("nan"), "avg": float("nan"), "median": float("nan"),
        "pf": float("nan"), "max_dd": float("nan"), "ann_ror": float("nan"),
        "avg_days": float("nan"), "med_days": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "expect": float("nan"), "capital_days": 0.0, "ppcd": float("nan"),
        "tpy": float("nan"), "vel_n": 0, "vel_avg": float("nan"), "vel_avg_d": float("nan"),
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
    vel_n, vel_avg, vel_avg_d = _vel_stats(trades)
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
            if key == "ppcd" or key == "vel_avg_d":
                cells.append(f"<td>{_fmt(v, nd, '') if math.isfinite(float(v)) else '—'}</td>"
                             if isinstance(v, (int, float)) else "<td>—</td>")
                # money-ish: prefix $
                if isinstance(v, (int, float)) and math.isfinite(float(v)):
                    cells[-1] = f"<td>${float(v):,.{nd}f}</td>"
            else:
                cells.append(f"<td>{_fmt(v, nd, suf)}</td>")
            if b["id"] == "control":
                cells.append("<td>—</td>")
            else:
                if key in ("ppcd", "vel_avg_d") and isinstance(v, (int, float)) and math.isfinite(float(v)) and math.isfinite(float(ctrl[key])):
                    d = float(v) - float(ctrl[key])
                    sign = "+" if d >= 0 else "-"
                    cells.append(f"<td>{sign}${abs(d):,.{nd}f}</td>")
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
        sortable_th("Slice", "text"),
        sortable_th("N", "num"),
        sortable_th("WR", "num"),
        sortable_th("Avg P&L %", "num"),
        sortable_th("PF", "num"),
        sortable_th("Expectancy %", "num"),
        sortable_th("Max DD %", "num"),
        sortable_th("Ann ROR %", "num"),
        sortable_th("Avg days", "num"),
        sortable_th("Med days", "num"),
        sortable_th("Capital Days", "num"),
        sortable_th("Sharpe", "num"),
        sortable_th("PPCD $", "num"),
        sortable_th("Vel exits", "num"),
        sortable_th("Vel avg %", "num"),
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
                f"<td>{_fmt(m['avg_days'], 1)}</td>"
                f"<td>{_fmt(m['med_days'], 1)}</td>"
                f"<td>{_fmt(m['capital_days'], 0)}</td>"
                f"<td>{_fmt(m['sharpe'], 2)}</td>"
                f"<td>{ppcd}</td>"
                f"<td>{_fmt(m['vel_n'], 0)}</td>"
                f"<td>{_fmt(m['vel_avg'], 2, '%')}</td>"
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
    # Put velocity exit near top if present
    if VEL_EXIT in names:
        names.remove(VEL_EXIT)
        names.insert(0, VEL_EXIT)
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
        "vel_exits", "vel_avg_pnl_pct", "vel_avg_pnl_dollars",
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
                    "vel_avg_pnl_dollars": m["vel_avg_d"],
                    "slot_cash": b["slot_cash"],
                    "verdict": "" if b["id"] == "control" else b["verdict"],
                    "source_closed": b["closed"],
                })
    return path


def _write_ab_plan() -> None:
    text = """# AB plan — WPBR Day-40 velocity (+10%)

## Type

**EXIT** one-knob A/B (not ENTRY). Research only.

## Hypothesis

Trades that never touch +10% (by intraday High) in the first 40 trading bars are slow / weak;
cutting them at the Day-40 CLOSE frees capital without changing entries, target, stop, or overhead.

## Arms

| Arm | Knobs |
| --- | --- |
| CONTROL | Live `run_wpbr.bat` freeze: `wpbr_overhead_band_pct=0.22`, `target_pct=1.20`, `stop_pct=0.92`, `growth_filter_enabled=false`, `wpbr_velocity_time_stop_bars=0` |
| TEST | Identical + `wpbr_velocity_time_stop_bars=40`, `wpbr_velocity_time_stop_min_gain=0.10` |

## Bar indexing

- Entry bar = 0 (`bars_held = idx − entry_bar`).
- Day-40 = first bar where `bars_held == 40` (40 bars after entry).
- Peak High checked over `entry .. entry+40` inclusive.
- Fill at that bar's CLOSE. Stop/target still win first on the same bar.
- Exit label: `WPBR_VEL_TS40`.

## Split

IS = `DATE_OPENED < 2024-01-01`. OOS = `DATE_OPENED >= 2024-01-01` (report-only). No OOS retune.

## Selection bias

One EXIT candidate named before results. KEEP/HOLD/DISMISS on IS quality; OOS softens → HOLD.
"""
    (OUT_DIR / "AB_PLAN.md").write_text(text, encoding="utf-8")


def _write_baseline(books: list[dict[str, Any]]) -> None:
    test = next(b for b in books if b["id"] == "test")
    ctrl = next(b for b in books if b["id"] == "control")
    lines = [
        "# WPBR Day-40 velocity (+10%) A/B",
        "",
        "Pivot Break and Retest (WPBR). **EXIT** one-knob. Research only. Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "We kept the live Pivot Break and Retest book the same — 22% overhead skip, sell the whole "
        "position at +20% from the buy, stop 8% under the low of the day before the buy — and only "
        "changed when a lagging trade is cut. On the test book, if the stock's intraday high never "
        "reaches +10% above the buy in the first 40 trading sessions (entry day = day 0, so day 40 "
        "is 40 sessions later), we sell at that day's closing price. Everything else is unchanged. "
        "Buys before 2024 are in-sample. 2024 onward is out of sample and is for reading only.",
        "",
        "## Verdict",
        "",
        f"- {test['verdict']}",
        "",
        "Research only. Not gold. Not DailyRun. Out of sample is report-only. Do not retune on OOS.",
        "",
        "## Freeze",
        "",
        "- **EXIT vs ENTRY:** EXIT only. Entries, universe, sizing, overhead, target, and stop frozen.",
        "- Control reused from `tmp_wpbr_velocity_cols_rerun_20261002` (engine stamp **261002172253**). "
        "Knobs match current `run_wpbr.bat` including `wpbr_overhead_band_pct=0.22`, `target_pct=1.20`, "
        "`stop_pct=0.92`, `growth_filter_enabled=false`, and no velocity exit (`wpbr_velocity_time_stop_bars=0`).",
        "- Test is a fresh full-universe run with only "
        "`wpbr_velocity_time_stop_bars=40` and `wpbr_velocity_time_stop_min_gain=0.10`.",
        "- Bar rule: entry bar = 0; at `bars_held >= 40`, if max High over entry..entry+40 never "
        f"hit entry×1.10, exit at CLOSE as `{VEL_EXIT}`.",
        "- Shared: full warehouse, weekly WPBR zones, band 0.015, strong pivot either 3/10%, "
        "breakout confirm 0.03, retest window 2, second chance after win on, indicators record-only, "
        "market-cap filter off, SPY 1y gate off, `min_history_bars=0`.",
        "- IS cut: `DATE_OPENED < 2024-01-01`. OOS report-only.",
        "- Ann ROR house formula via `compare_format.ann_ror_from_closed` with each arm's slot cash "
        f"(control ${ctrl['slot_cash']:,.2f}; test ${test['slot_cash']:,.2f}).",
        "- PPCD = total closed P&L $ / Capital Days. Selection bias: one named EXIT candidate.",
        "- `run_wpbr.bat` / DailyRun defaults were **not** changed.",
        "",
        "## Day-40 velocity exits",
        "",
        "| Slice | Control N | Test N | Test avg P&L % | Test avg P&L $ |",
        "| --- | --- | --- | --- | --- |",
    ]
    for sl in ("FULL", "IS", "OOS"):
        m = test["slices"][sl]
        c = ctrl["slices"][sl]
        avg = _fmt(m["vel_avg"], 2, "%")
        avg_d = f"${m['vel_avg_d']:,.2f}" if math.isfinite(m["vel_avg_d"]) else "—"
        lines.append(
            f"| {sl} | {int(c['vel_n'])} | {int(m['vel_n'])} | {avg} | {avg_d} |"
        )
    lines += ["", "## Headline metrics", ""]
    for sl in ("FULL", "IS", "OOS"):
        lines.append(f"### {sl}")
        lines.append("")
        lines.append(
            "| Metric | Control | Test | Delta |"
        )
        lines.append("| --- | --- | --- | --- |")
        for key, label, nd, suf in METRIC_ROWS:
            cv = ctrl["slices"][sl][key]
            tv = test["slices"][sl][key]
            if key in ("ppcd", "vel_avg_d"):
                c_s = f"${cv:,.2f}" if isinstance(cv, (int, float)) and math.isfinite(cv) else "—"
                t_s = f"${tv:,.2f}" if isinstance(tv, (int, float)) and math.isfinite(tv) else "—"
                d_s = _delta(tv, cv, nd, "")
                if isinstance(tv, (int, float)) and isinstance(cv, (int, float)) and math.isfinite(tv) and math.isfinite(cv):
                    d = tv - cv
                    sign = "+" if d >= 0 else "-"
                    d_s = f"{sign}${abs(d):,.2f}"
                lines.append(f"| {label} | {c_s} | {t_s} | {d_s} |")
            else:
                lines.append(
                    f"| {label} | {_fmt(cv, nd, suf)} | {_fmt(tv, nd, suf)} | {_delta(tv, cv, nd, suf)} |"
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
<title>WPBR Day-40 velocity (+10%) A/B</title>
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
<h1>Pivot Break and Retest — Day-40 velocity (+10%) A/B</h1>
<p class="note">Research only. EXIT one-knob. Not gold. Not DailyRun. Click column headers to sort. Swipe sideways to see more columns.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{esc(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>We kept the live Pivot Break and Retest book the same — 22% overhead skip, sell the whole position at +20% from the buy, stop 8% under the low of the day before the buy — and only changed when a lagging trade is cut. On the test book, if the stock's intraday high never reaches +10% above the buy in the first 40 trading sessions (entry day = day 0, so day 40 is 40 sessions later), we sell at that day's closing price. Everything else is unchanged. Buys before 2024 are in-sample. 2024 onward is out of sample and is for reading only.</p>
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
<p class="note">Annualized rate of return (Ann ROR) uses each arm's slot cash via the house formula. Total PnL $ / Sheet PnL $ omitted from tables. A positive Max DD delta is a deeper drop than control. Capital Days is the sum of days held. Profit per capital day (PPCD) is total closed dollars divided by Capital Days.</p>
{SWIPE_NOTE_HTML}
{''.join(sections)}
<p class="note">Picking the best cell after this table is in-sample selection. Research only. Not gold. Not DailyRun.</p>
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
            full = b["slices"]["FULL"]
            print(
                f"VEL FULL n={full['vel_n']} avg%={full['vel_avg']:.2f} avg$={full['vel_avg_d']:.2f}",
                flush=True,
            )
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
            "-t", "WPBR Day40 vel AB",
        ],
        cwd=str(ROOT),
        check=False,
    )


if __name__ == "__main__":
    main()
