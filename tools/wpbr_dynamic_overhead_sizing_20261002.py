"""WPBR dynamic overhead sizing vs live 22/20/8 control.

Research only. One candidate arm. Out of sample is report-only.
Not gold. Not DailyRun. Does not change run_wpbr.bat freezes.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
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
    sharpe_from_equity_curve_csv,
)
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

STAMP = "20261002"
IS_CUT = "20240101"
IS_DATE = date(2024, 1, 1)
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_dynamic_overhead_sizing_{STAMP}"
RUNS_DIR = ROOT / "tmp_wpbr_dynamic_overhead_sizing_20261002"
CONTROL_DIR = ROOT / "tmp_wpbr_overhead20_vs22_t20s8_ab_20261002" / "control"
PY = sys.executable
WORKERS = 10
ENGINE_CAP = 8
CPU_CAP = 90

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
    "wpbr_dynamic_overhead": "false",
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

REQUEST_QUOTE = (
    "run a single test for WPBR. but instead of not entering based on an overhead "
    "clearance of 22%, let's make it dynamic. for example, if there is NO overhead "
    "zone then use 22% OH, 20% target and 8% stop loss. If there IS an overhead zone, "
    "adjust the target and stop accordingly. example. let's say there is an overhead "
    "zone at 22%, we set the target to 90% of the overhead zone bottom, so it would be "
    "19.8%. we set the stop loss to be 40% of the target so 7.92%. if it were 16% "
    "overhead, target becomes 14.4% and stop loss 5.76. run this through and tell me "
    "what the results are and if there is a certain level where if an overhead zone is "
    "so close it is not worth it."
)

LAYMAN = (
    "Pivot Break and Retest (WPBR) usually skips a buy when an older zone sits within "
    "22% above the zone you want to buy. This test instead takes those buys and shrinks "
    "the profit target and stop to fit under that older zone: the target is 90% of the "
    "gap to the older zone’s bottom, and the stop under the trigger-day low is 40% of "
    "that target. When there is no older zone above, the book keeps the live 20% target "
    "and 8% stop. We also sorted the new book by how close that older zone was, to see "
    "whether a very tight gap is not worth taking. Research only — live DailyRun is unchanged."
)

# G bins for "how close is too close" (percent points).
G_BINS: list[tuple[str, float | None, float | None]] = [
    ("no overhead", None, None),
    ("G < 8%", 0.0, 8.0),
    ("8–12%", 8.0, 12.0),
    ("12–16%", 12.0, 16.0),
    ("16–22%", 16.0, 22.0),
    ("22–30%", 22.0, 30.0),
    ("G > 30%", 30.0, None),
]

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


def _fmt(v: float, nd: int = 2, suf: str = "") -> str:
    if not math.isfinite(v):
        return "—"
    if nd == 0:
        return f"{v:.0f}{suf}"
    return f"{v:.{nd}f}{suf}"


def _delta(a: float, b: float, nd: int = 2, suf: str = "") -> str:
    if not math.isfinite(a) or not math.isfinite(b):
        return "—"
    d = a - b
    sign = "+" if d > 0 else ""
    return f"{sign}{_fmt(d, nd, suf)}"


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


def _engine_count() -> int:
    ps = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -match 'rocket_tbn|wpbr|stock_analysis' "
        "-and $_.CommandLine -notmatch 'http\\.server|hv15m' "
        "} | Measure-Object | Select-Object -ExpandProperty Count"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        cwd=str(ROOT), capture_output=True, text=True, check=False,
    )
    try:
        return int((r.stdout or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def _cpu_load() -> float:
    ps = "Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average | Select-Object -ExpandProperty Average"
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        cwd=str(ROOT), capture_output=True, text=True, check=False,
    )
    try:
        return float((r.stdout or "100").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 100.0


def _wait_for_slot() -> None:
    while True:
        n = _engine_count()
        cpu = _cpu_load()
        print(f"[cap] engines={n} cpu={cpu:.0f}% (need <{ENGINE_CAP} and <={CPU_CAP})", flush=True)
        if n < ENGINE_CAP and cpu <= CPU_CAP:
            return
        time.sleep(45)


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


def _closed_ready(folder: Path) -> bool:
    return folder.is_dir() and _latest(folder, "Closed") is not None


def _recover_g_pct(raw: dict[str, Any]) -> float | None:
    """Percent-point overhead gap G for binning.

    Prefer OVERHEAD_GAP_PCT when present. The 20261002 candidate book left that
    column blank because closed-trade construction dropped ``wpbr_overhead_gap_pct``.
    Recover from the dynamic-sizing identity: target gain = 0.90×G (fraction);
    clear sky keeps the static 20% target (target_pct=1.20) → no overhead.
    """
    g = _f(raw.get("OVERHEAD_GAP_PCT"))
    if math.isfinite(g):
        return g
    entry = _f(raw.get("ENTRY_PRICE"))
    target = _f(raw.get("TARGET_PRICE"))
    if not (math.isfinite(entry) and entry > 0 and math.isfinite(target) and target > 0):
        return None
    gain = target / entry - 1.0
    # Static clear-sky target; also swallows the knife-edge G≈22.22% case.
    if abs(gain - 0.20) < 0.002:
        return None
    if gain <= 0:
        return None
    return (gain / 0.90) * 100.0


def _load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _ymd(str(raw.get("DATE_OPENED") or ""))
            if not opened:
                continue
            g = _recover_g_pct(raw)
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
                "stop": _f(raw.get("STOP_PRICE")),
                "g_pct": g,
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
        "total_pnl": float("nan"),
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
        "total_pnl": total,
    }


def _g_bin(g: float | None) -> str:
    if g is None or not math.isfinite(g):
        return "no overhead"
    if g < 8.0:
        return "G < 8%"
    if g < 12.0:
        return "8–12%"
    if g < 16.0:
        return "12–16%"
    if g < 22.0:
        return "16–22%"
    if g <= 30.0:
        return "22–30%"
    return "G > 30%"


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
    return {
        **spec,
        "closed": closed,
        "cash": cash,
        "cash_src": cash_src,
        "symbols": symbols,
        "slices": slices,
        "trades": trades,
        "report": report,
        "curve": curve,
    }


def _verdict(cand: dict[str, Any], ctrl: dict[str, Any]) -> tuple[str, str]:
    """KEEP/HOLD/DISMISS on IS quality vs control. OOS report-only."""
    is_c = cand["slices"]["IS"]
    is_0 = ctrl["slices"]["IS"]
    oos_c = cand["slices"]["OOS"]
    oos_0 = ctrl["slices"]["OOS"]
    label = cand["short"]
    if not math.isfinite(is_c["ann_ror"]) or not math.isfinite(is_0["ann_ror"]):
        return "HOLD", f"{label}: HOLD — in-sample Ann ROR missing."
    d_ann = is_c["ann_ror"] - is_0["ann_ror"]
    d_pf = (is_c["pf"] - is_0["pf"]) if math.isfinite(is_c["pf"]) and math.isfinite(is_0["pf"]) else 0.0
    d_dd = (is_c["max_dd"] - is_0["max_dd"]) if math.isfinite(is_c["max_dd"]) and math.isfinite(is_0["max_dd"]) else 0.0
    n_ok = is_c["n"] >= N_FLOOR * max(1, is_0["n"])
    oos_soft = (
        math.isfinite(oos_c["ann_ror"]) and math.isfinite(oos_0["ann_ror"])
        and (oos_c["ann_ror"] + ANN_FLAT) < oos_0["ann_ror"]
    )
    if d_ann < -ANN_WORSE:
        return "DISMISS", (
            f"{label}: DISMISS — in-sample Ann ROR {_fmt(is_c['ann_ror'], 2, '%')} vs control "
            f"{_fmt(is_0['ann_ror'], 2, '%')} (Δ {_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')})."
        )
    if d_ann <= ANN_FLAT:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lift is flat "
            f"({_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')}; need > {ANN_FLAT:.2f} pts)."
        )
    if not n_ok:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted but trade count fell below "
            f"{N_FLOOR:.0%} of control ({is_c['n']} vs {is_0['n']})."
        )
    if d_pf < -PF_WORSE:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted but profit factor softened "
            f"({_delta(is_c['pf'], is_0['pf'], 2)})."
        )
    if d_dd > DD_WORSE:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted but Max DD worsened "
            f"({_delta(is_c['max_dd'], is_0['max_dd'], 2, '%')})."
        )
    if oos_soft:
        return "HOLD", (
            f"{label}: HOLD — in-sample Ann ROR lifted "
            f"({_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')}) but out-of-sample Ann ROR "
            f"softened vs control ({_delta(oos_c['ann_ror'], oos_0['ann_ror'], 2, '%')}; report-only)."
        )
    return "KEEP", (
        f"{label}: KEEP (research only) — in-sample Ann ROR {_fmt(is_c['ann_ror'], 2, '%')} vs "
        f"{_fmt(is_0['ann_ror'], 2, '%')} (Δ {_delta(is_c['ann_ror'], is_0['ann_ror'], 2, '%')}); "
        f"PF/DD/N ok; OOS not softer. Not gold. Not DailyRun."
    )


def _floor_note(cand: dict[str, Any]) -> tuple[str, str]:
    """Recommend a minimum G floor from candidate G-bin quality (FULL then IS)."""
    cash = cand["cash"]
    curve = cand["curve"]
    by_bin: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in G_BINS}
    for t in cand["trades"]:
        by_bin[_g_bin(t.get("g_pct"))].append(t)
    rows = []
    for name, _, _ in G_BINS:
        rows.append((name, {w: _metrics(_slice_rows(by_bin[name], w), cash, curve, w) for w in ("FULL", "IS", "OOS")}))
    # Prefer clear sky / wide G as reference for "collapse".
    clear = next(m for n, m in rows if n == "no overhead")
    clear_avg = clear["FULL"]["avg"]
    clear_ann = clear["FULL"]["ann_ror"]
    bad: list[str] = []
    for name, m in rows:
        if name == "no overhead":
            continue
        full = m["FULL"]
        if full["n"] < 30:
            continue
        avg_bad = math.isfinite(full["avg"]) and math.isfinite(clear_avg) and full["avg"] < (clear_avg - 1.0)
        ann_bad = math.isfinite(full["ann_ror"]) and math.isfinite(clear_ann) and full["ann_ror"] < (clear_ann - 1.0)
        wr_bad = math.isfinite(full["wr"]) and full["wr"] < 35.0
        if (avg_bad and ann_bad) or (avg_bad and wr_bad):
            bad.append(name)
    if not bad:
        note = (
            "No clear “not worth it” floor from the G bins: no overhead-present bin with N≥30 "
            "collapses average % and Ann ROR together versus clear-sky (or WR under 35% with soft avg). "
            "A hard skip floor is not recommended from this single book; treat close-G bins as watch items."
        )
        return "none", note
    # Map first bad bin to a suggested floor.
    order = ["G < 8%", "8–12%", "12–16%", "16–22%", "22–30%", "G > 30%"]
    first = next((b for b in order if b in bad), bad[0])
    floor_map = {
        "G < 8%": "8%",
        "8–12%": "12%",
        "12–16%": "16%",
        "16–22%": "22%",
        "22–30%": "30%",
        "G > 30%": "none (wide gaps also weak — revisit sizing)",
    }
    suggested = floor_map.get(first, "none")
    note = (
        f"Weak full-book bins vs clear sky: {', '.join(bad)}. "
        f"Suggested research floor: skip (or do not size) when overhead G is below about {suggested} "
        f"(first collapsing bin: {first}). Confirm on a fresh holdout before adopting; OOS is report-only."
    )
    return suggested, note


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
        sortable_th("Role", "text"),
        sortable_th("N full", "num"),
        sortable_th("WR full", "num"),
        sortable_th("Avg % full", "num"),
        sortable_th("PF full", "num"),
        sortable_th("Max DD full", "num"),
        sortable_th("Ann ROR full", "num"),
        sortable_th("Ann ROR IS", "num"),
        sortable_th("Ann ROR OOS", "num"),
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


def _exit_table(trades: list[dict[str, Any]]) -> str:
    exits = Counter(t["exit"] for t in trades)
    n = len(trades) or 1
    head = (
        sortable_th("Exit", "text")
        + sortable_th("Trades", "num")
        + sortable_th("Share", "num")
    )
    rows = []
    for name, count in exits.most_common():
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{count}</td>"
            f"<td>{100.0 * count / n:.1f}%</td>"
            "</tr>"
        )
    return (
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _g_bucket_table(cand: dict[str, Any]) -> str:
    cash = cand["cash"]
    curve = cand["curve"]
    by_bin: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in G_BINS}
    for t in cand["trades"]:
        by_bin[_g_bin(t.get("g_pct"))].append(t)
    head = "".join([
        sortable_th("Overhead G bin", "text"),
        sortable_th("N full", "num"),
        sortable_th("WR full", "num"),
        sortable_th("Avg % full", "num"),
        sortable_th("Ann ROR full", "num"),
        sortable_th("N IS", "num"),
        sortable_th("WR IS", "num"),
        sortable_th("Avg % IS", "num"),
        sortable_th("Ann ROR IS", "num"),
        sortable_th("N OOS", "num"),
        sortable_th("WR OOS", "num"),
        sortable_th("Avg % OOS", "num"),
        sortable_th("Ann ROR OOS", "num"),
    ])
    rows = []
    for name, _, _ in G_BINS:
        m = {w: _metrics(_slice_rows(by_bin[name], w), cash, curve, w) for w in ("FULL", "IS", "OOS")}
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{m['FULL']['n']}</td>"
            f"<td>{_fmt(m['FULL']['wr'], 1, '%')}</td>"
            f"<td>{_fmt(m['FULL']['avg'], 2, '%')}</td>"
            f"<td>{_fmt(m['FULL']['ann_ror'], 2, '%')}</td>"
            f"<td>{m['IS']['n']}</td>"
            f"<td>{_fmt(m['IS']['wr'], 1, '%')}</td>"
            f"<td>{_fmt(m['IS']['avg'], 2, '%')}</td>"
            f"<td>{_fmt(m['IS']['ann_ror'], 2, '%')}</td>"
            f"<td>{m['OOS']['n']}</td>"
            f"<td>{_fmt(m['OOS']['wr'], 1, '%')}</td>"
            f"<td>{_fmt(m['OOS']['avg'], 2, '%')}</td>"
            f"<td>{_fmt(m['OOS']['ann_ror'], 2, '%')}</td>"
            "</tr>"
        )
    return (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _write_baseline(books: list[dict[str, Any]], floor_sug: str, floor_note: str) -> None:
    ctrl, cand = books[0], books[1]
    path = OUT_DIR / "BASELINE.md"
    lines = [
        "# WPBR dynamic overhead sizing",
        "",
        "Pivot Break and Retest (WPBR). Research only. Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Verdict",
        "",
        f"- {cand['verdict']}",
        f"- Overhead floor suggestion: **{floor_sug}**. {floor_note}",
        "",
        "Selection bias label: this is a **research candidate**. Knobs and the dynamic rule were frozen before reading OOS. "
        "KEEP/HOLD/DISMISS is on in-sample quality vs control only. Out of sample is report-only — do not retune on OOS. "
        "Do not adopt into DailyRun from this stamp alone.",
        "",
        "## Freeze",
        "",
        "- Control (live 2026-10-02 freeze, stamp 261002051403): `wpbr_overhead_band_pct=0.22`, `target_pct=1.20`, `stop_pct=0.92`, "
        "`wpbr_dynamic_overhead=false`, growth filter off, `min_history_bars=0`, full warehouse.",
        f"- Control closed file reused (not recomputed): `{ctrl['closed'].relative_to(ROOT).as_posix()}`. "
        f"N={ctrl['slices']['FULL']['n']}, symbols={ctrl['symbols']}.",
        "- Candidate: `wpbr_dynamic_overhead=true`, `wpbr_overhead_band_pct=0` (hard ≤22% skip off). "
        "Clear sky (no earlier zone above): fixed target 20% / stop 8% under trigger-day low. "
        "When nearest overhead gap is G (fraction): target gain = 0.90×G, stop under trigger-day low = 0.40×(0.90×G). "
        "Same entry structure, universe, and other knobs as control.",
        f"- Candidate closed: `{cand['closed'].relative_to(ROOT).as_posix()}`.",
        "- Exit identity: whole position at target or stop (no partial exit strategy). "
        "`stop_loss_based=trigger_low`, `stop_pct_is_multiplier=true`.",
        "- Slot cash: each arm’s own `capacity_brt_cash` (trade dollars), not $47,500.",
        "- Ann ROR: house formula `compare_format.ann_ror_from_closed` with that slot cash. "
        "Reported for FULL, IS (`DATE_OPENED` < 2024-01-01), and OOS (`DATE_OPENED` ≥ 2024-01-01).",
        "- Shared unchanged: weekly WPBR zones, band 1.5%, strong pivot either 3/10%, breakout confirm 3%, "
        "retest window 2 days, second chance after win on, indicators recorded not a buy gate, mcap off, "
        "SPY 1y gate off, `sheet_no_entry_same_bar_after_exit=false`.",
        "- Universe: every CSV under `data/newdata/data`.",
        "- Engine flag default remains off so DailyRun / `run_wpbr.bat` are untouched.",
        "- G-bin recovery: candidate `OVERHEAD_GAP_PCT` was blank (closed-trade copy omitted "
        "`wpbr_overhead_gap_pct`). Bins use post-process recovery from target: clear sky when "
        "target gain ≈ 20%; else G% = (target/entry − 1) / 0.90 × 100.",
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
        "## Headline (FULL / IS Ann ROR / OOS Ann ROR)",
        "",
        "| Arm | N | WR | Avg % | PF | Max DD | Ann ROR full | Ann ROR IS | Ann ROR OOS |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in books:
        f, i, o = b["slices"]["FULL"], b["slices"]["IS"], b["slices"]["OOS"]
        lines.append(
            f"| {b['short']} | {f['n']} | {_fmt(f['wr'], 1, '%')} | {_fmt(f['avg'], 2, '%')} | "
            f"{_fmt(f['pf'], 2)} | {_fmt(f['max_dd'], 2, '%')} | {_fmt(f['ann_ror'], 2, '%')} | "
            f"{_fmt(i['ann_ror'], 2, '%')} | {_fmt(o['ann_ror'], 2, '%')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_html(books: list[dict[str, Any]], floor_sug: str, floor_note: str) -> Path:
    ctrl, cand = books[0], books[1]
    path = OUT_DIR / "compare.html"
    css = SORTABLE_TH_CSS + RESPONSIVE_TABLE_CSS + """
    body{font-family:Segoe UI,system-ui,sans-serif;margin:1.2rem;max-width:1100px;line-height:1.45;color:#1a1a1a}
    h1{font-size:1.45rem;margin:0 0 .4rem} h2{font-size:1.15rem;margin:1.4rem 0 .5rem}
    .callout{background:#f4f7fb;border-left:4px solid #3b6ea5;padding:.75rem 1rem;margin:1rem 0}
    .verdict{background:#fff8e8;border-left:4px solid #c48a00;padding:.75rem 1rem;margin:1rem 0}
    .muted{color:#555;font-size:.92rem} code{font-size:.9em}
    """
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR dynamic overhead sizing</title>
<style>{css}</style>
</head><body>
<h1>WPBR dynamic overhead sizing (research)</h1>
<p class="muted">Stamp {STAMP}. Control reused from live freeze 261002051403. Candidate is one research arm. Not gold. Not DailyRun.</p>

<div class="callout">
<strong>What you asked</strong>
<blockquote>{html_mod.escape(REQUEST_QUOTE)}</blockquote>
<strong>In plain English</strong>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="verdict">
<strong>Verdict:</strong> {html_mod.escape(cand['verdict'])}<br/>
<strong>How close is too close:</strong> suggested floor <strong>{html_mod.escape(floor_sug)}</strong>.
{html_mod.escape(floor_note)}
</div>

<p>{SWIPE_NOTE_HTML} Click column headers to sort.</p>

<h2>Headline</h2>
{_headline_table(books)}

<h2>Full book</h2>
{_metric_table(books, "FULL")}

<h2>In-sample (entry before 2024-01-01)</h2>
{_metric_table(books, "IS")}

<h2>Out-of-sample (entry on/after 2024-01-01) — report only</h2>
{_metric_table(books, "OOS")}

<h2>Candidate overhead G bins (how close is too close)</h2>
<p class="muted">G is the gap from this zone’s top to the nearest older zone’s bottom (same definition as the live overhead gate), in percent. Clear sky = no older zone above. Slot cash for Ann ROR is the candidate’s own capacity (${cand['cash']:,.2f}).
OVERHEAD_GAP_PCT was blank on the closed book (engine dropped <code>wpbr_overhead_gap_pct</code> when closing the trade); G is recovered post-process from the dynamic target identity (target gain = 0.90×G; static 20% target = clear sky).</p>
{_g_bucket_table(cand)}

<h2>Exit mix — control</h2>
{_exit_table(ctrl['trades'])}

<h2>Exit mix — candidate</h2>
{_exit_table(cand['trades'])}

<p class="muted">Control closed: <code>{html_mod.escape(ctrl['closed'].relative_to(ROOT).as_posix())}</code>
(N={ctrl['slices']['FULL']['n']}, slot ${ctrl['cash']:,.2f}).
Candidate closed: <code>{html_mod.escape(cand['closed'].relative_to(ROOT).as_posix())}</code>
(N={cand['slices']['FULL']['n']}, slot ${cand['cash']:,.2f}).
Annualized rate of return (Ann ROR) uses house formula with slot cash matching trade dollars.</p>

{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")
    return path


def _write_summary_csv(books: list[dict[str, Any]], g_bin_rows: list[dict[str, Any]] | None = None) -> Path:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm_id", "label", "slice", "n", "win_rate", "avg_pct", "median_pct", "profit_factor",
        "max_dd_pct", "ann_ror_pct", "avg_days", "calmar", "sharpe", "slot_cash", "verdict",
        "source_closed", "g_bin",
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
                    "slice": sl,
                    "n": m["n"],
                    "win_rate": f"{m['wr']:.4f}" if math.isfinite(m["wr"]) else "",
                    "avg_pct": f"{m['avg']:.4f}" if math.isfinite(m["avg"]) else "",
                    "median_pct": f"{m['median']:.4f}" if math.isfinite(m["median"]) else "",
                    "profit_factor": f"{m['pf']:.4f}" if math.isfinite(m["pf"]) else "",
                    "max_dd_pct": f"{m['max_dd']:.4f}" if math.isfinite(m["max_dd"]) else "",
                    "ann_ror_pct": f"{m['ann_ror']:.4f}" if math.isfinite(m["ann_ror"]) else "",
                    "avg_days": f"{m['avg_days']:.4f}" if math.isfinite(m["avg_days"]) else "",
                    "calmar": f"{m['calmar']:.4f}" if math.isfinite(m["calmar"]) else "",
                    "sharpe": f"{m['sharpe']:.4f}" if math.isfinite(m["sharpe"]) else "",
                    "slot_cash": f"{b['cash']:.6f}",
                    "verdict": "control" if b["id"] == "control" else b["verdict_word"],
                    "source_closed": str(b["closed"].relative_to(ROOT)).replace("\\", "/"),
                    "g_bin": "",
                })
        for row in g_bin_rows or []:
            w.writerow(row)
    return path


def _g_bin_summary_rows(cand: dict[str, Any]) -> list[dict[str, Any]]:
    cash = cand["cash"]
    curve = cand["curve"]
    by_bin: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in G_BINS}
    for t in cand["trades"]:
        by_bin[_g_bin(t.get("g_pct"))].append(t)
    rows: list[dict[str, Any]] = []
    src = str(cand["closed"].relative_to(ROOT)).replace("\\", "/")
    for name, _, _ in G_BINS:
        for sl in ("FULL", "IS", "OOS"):
            m = _metrics(_slice_rows(by_bin[name], sl), cash, curve, sl)
            rows.append({
                "arm_id": "dynamic_gbin",
                "label": "Dynamic OH sizing",
                "slice": sl,
                "n": m["n"],
                "win_rate": f"{m['wr']:.4f}" if math.isfinite(m["wr"]) else "",
                "avg_pct": f"{m['avg']:.4f}" if math.isfinite(m["avg"]) else "",
                "median_pct": f"{m['median']:.4f}" if math.isfinite(m["median"]) else "",
                "profit_factor": f"{m['pf']:.4f}" if math.isfinite(m["pf"]) else "",
                "max_dd_pct": f"{m['max_dd']:.4f}" if math.isfinite(m["max_dd"]) else "",
                "ann_ror_pct": f"{m['ann_ror']:.4f}" if math.isfinite(m["ann_ror"]) else "",
                "avg_days": f"{m['avg_days']:.4f}" if math.isfinite(m["avg_days"]) else "",
                "calmar": f"{m['calmar']:.4f}" if math.isfinite(m["calmar"]) else "",
                "sharpe": f"{m['sharpe']:.4f}" if math.isfinite(m["sharpe"]) else "",
                "slot_cash": f"{cash:.6f}",
                "verdict": cand.get("verdict_word", ""),
                "source_closed": src,
                "g_bin": name,
            })
    return rows


def _run_candidate() -> Path:
    out = RUNS_DIR / "dynamic"
    out.mkdir(parents=True, exist_ok=True)
    if _closed_ready(out):
        report = _read_report(out)
        dyn = str(report.get("wpbr_dynamic_overhead") or "").strip().lower()
        if dyn in {"true", "1", "yes", "on"}:
            print(f"[reuse] candidate closed already ready in {out}", flush=True)
            return out
    _wait_for_slot()
    log_path = RUNS_DIR / "dynamic.log"
    cmd = _cmd(out, {
        "wpbr_dynamic_overhead": "true",
        "wpbr_overhead_band_pct": "0",
        "target_pct": "1.20",
        "stop_pct": "0.92",
    })
    (out / "run_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
    print(f"[start] dynamic workers={WORKERS} log={log_path}", flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    while proc.poll() is None:
        time.sleep(30)
        print(f"[wait] dynamic pid={proc.pid} running…", flush=True)
    if proc.returncode != 0:
        raise SystemExit(f"candidate engine failed rc={proc.returncode}; see {log_path}")
    if not _closed_ready(out):
        raise SystemExit(f"candidate finished but no Closed CSV in {out}")
    return out


def main() -> None:
    report_only = "--report-only" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if not _closed_ready(CONTROL_DIR):
        raise SystemExit(f"control closed missing: {CONTROL_DIR}")

    cand_dir = RUNS_DIR / "dynamic" if report_only else _run_candidate()
    if report_only and not _closed_ready(cand_dir):
        raise SystemExit(f"--report-only but candidate closed missing: {cand_dir}")

    ctrl = _score_book({
        "id": "control",
        "short": "Control 22/20/8",
        "role": "live freeze (reused)",
        "folder": CONTROL_DIR,
    })
    cand = _score_book({
        "id": "dynamic",
        "short": "Dynamic OH sizing",
        "role": "research candidate",
        "folder": cand_dir,
    })
    word, text = _verdict(cand, ctrl)
    cand["verdict_word"] = word
    cand["verdict"] = text
    floor_sug, floor_note = _floor_note(cand)
    books = [ctrl, cand]
    g_rows = _g_bin_summary_rows(cand)

    _write_baseline(books, floor_sug, floor_note)
    html = _write_html(books, floor_sug, floor_note)
    _write_summary_csv(books, g_rows)

    # Print G-bin table for the job log / parent agent.
    by_bin: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in G_BINS}
    for t in cand["trades"]:
        by_bin[_g_bin(t.get("g_pct"))].append(t)
    print("[g_bins] bin | N_full WR avg AnnROR | N_IS WR avg AnnROR | N_OOS WR avg AnnROR", flush=True)
    for name, _, _ in G_BINS:
        m = {w: _metrics(_slice_rows(by_bin[name], w), cand["cash"], cand["curve"], w) for w in ("FULL", "IS", "OOS")}
        print(
            f"[g_bins] {name} | "
            f"{m['FULL']['n']} {_fmt(m['FULL']['wr'], 1, '%')} {_fmt(m['FULL']['avg'], 2, '%')} {_fmt(m['FULL']['ann_ror'], 2, '%')} | "
            f"{m['IS']['n']} {_fmt(m['IS']['wr'], 1, '%')} {_fmt(m['IS']['avg'], 2, '%')} {_fmt(m['IS']['ann_ror'], 2, '%')} | "
            f"{m['OOS']['n']} {_fmt(m['OOS']['wr'], 1, '%')} {_fmt(m['OOS']['avg'], 2, '%')} {_fmt(m['OOS']['ann_ror'], 2, '%')}",
            flush=True,
        )

    ntfy_title = "WPBR dynamic G bins" if report_only else "WPBR dynamic overhead"
    subprocess.run(
        [
            PY, str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path", str(html),
            "-t", ntfy_title,
            "-m", f"{word}: floor={floor_sug}; G bins recomputed from target recovery",
        ],
        cwd=str(ROOT),
        check=False,
    )
    print(f"[done] {html}", flush=True)
    print(f"[verdict] {text}", flush=True)
    print(f"[floor] {floor_sug}: {floor_note}", flush=True)


if __name__ == "__main__":
    main()
