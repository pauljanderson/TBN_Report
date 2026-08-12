#!/usr/bin/env python3
"""QULL as market-timing gate A/B (post-hoc Closed filter).

Build a QULL \"active\" calendar from a QULL Closed+Open book: a calendar day is
active if any QULL position has DATE_OPENED <= day <= DATE_CLOSED (open-inclusive;
Open positions extend through last SPY bar / today).

For each other production system, keep Closed trades whose DATE_OPENED falls on
an active QULL day; compare vs the unfiltered control Closed book.

Capacity-adjusted Total PnL (Option A, primary):
  coverage = n_gated / n_control
  scale_A = 1 / coverage = n_control / n_gated
  Each kept trade's PNL_DOLLARS is multiplied by scale_A (full redeploy of freed
  capital into remaining trades — no liquidity/correlation frictions).

Option B (secondary, simple non-overlapping proxy):
  scale_B = initial_account / brt_cash  (each gated trade sized at full host V,
  as if max concurrent positions = 1). Not concurrency-calendar accurate.

Unscaled Ann ROR / PPCD remain the efficiency lenses; scaled Total PnL is the
capacity lens. Ann ROR under Option A proportional sizing is scale-invariant
(brt_cash and PnL both × scale_A).

This does **not** re-simulate portfolio concurrency / host cash — same spirit as
IND_DIFF gate ABs. Engine ``-v`` live gating is future work.

Usage (repo root)::

  python tools/run_qull_timing_gate_ab.py
  python tools/run_qull_timing_gate_ab.py --qull-stamp 260810110101
  python tools/run_qull_timing_gate_ab.py --systems SB,RS,RL,YH,BRT,WPBR,MTS,MVCP

Writes ``drive/paul_experiments/qull_timing_gate_ab/``:
  comparison.html, comparison.csv, DECISION_LOG.md, qull_active_days.csv
"""
from __future__ import annotations

import argparse
import csv
import html
import math
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
DRIVE = REPO / "drive"
OUT_ROOT = DRIVE / "paul_experiments" / "qull_timing_gate_ab"
SPY_PATH = REPO / "data" / "newdata" / "data" / "SPY.csv"
DEFAULT_QULL_STAMP = "260810110101"
DEFAULT_INITIAL_ACCOUNT = 500_000.0

# IND skipped (deprecated). Production systems to gate.
DEFAULT_SYSTEMS = ("SB", "RS", "RL", "YH", "BRT", "WPBR", "MTS", "MVCP")

# LatestRun stamp resolution (size+mtime match to stamped Closed).
SYSTEM_STAMP_HINTS: dict[str, str] = {
    "SB": "260810121023",
    "RS": "260810121005",
    "RL": "260810120523",
    "YH": "260810120559",
    "BRT": "260810120531",
    "WPBR": "260810120843",
    "MTS": "260810120611",
    "MVCP": "260810121030",
}

sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    format_money,
    format_money_delta,
    parse_number,
)

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e8e8e0}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.better{color:#166534;font-weight:600}
.worse{color:#991b1b}
.note{color:#64748b;font-size:.92em;max-width:58rem}
.def{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;margin:12px 0;font-size:.92rem}
code{background:#f5f5f5;padding:.1em .3em;border-radius:3px}
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim().replace(/[$,%+]/g,"").replace(/,/g,"");
    if(type==="num"||type==="date"||type==="month"){var n=parseFloat(t); return isNaN(n)?null:n;}
    return t.toLowerCase();
  }
  function bind(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th, colIdx){
      function activate(e){
        if(e && e.type==="touchend") e.preventDefault();
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        ths.forEach(function(x){x.classList.remove("sort-asc","sort-desc"); x.setAttribute("aria-sort","none");});
        th.classList.add(asc?"sort-asc":"sort-desc");
        th.setAttribute("aria-sort", asc?"ascending":"descending");
        var tbody=table.tBodies[0]; if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll("tr")).filter(function(r){return !r.classList.contains("total-row");});
        rows.sort(function(a,b){
          var av=parseCell(a.children[colIdx], type), bv=parseCell(b.children[colIdx], type);
          if(av==null&&bv==null) return 0;
          if(av==null) return 1; if(bv==null) return -1;
          if(av<bv) return asc?-1:1; if(av>bv) return asc?1:-1; return 0;
        });
        rows.forEach(function(r){tbody.appendChild(r);});
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function(e){ if(e.key==="Enter"||e.key===" "){e.preventDefault(); activate(e);} });
      th.addEventListener("touchend", activate, {passive:false});
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str = "num") -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _ymd8(v: Any) -> str:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s[:8] if len(s) >= 8 else ""


def _col(row: dict[str, str], *names: str) -> str:
    lower = {str(k).strip().lower().replace(" ", "_"): k for k in row.keys()}
    for n in names:
        key = n.lower().replace(" ", "_")
        k = lower.get(key)
        if k is not None:
            return str(row.get(k, "") or "")
    return ""


def _safe_num(x: Any) -> float:
    n = parse_number(x)
    return float(n) if n is not None else 0.0


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


def _date_opened(row: dict[str, str]) -> str:
    return _ymd8(_col(row, "DATE_OPENED", "DATE OPENED", "Date Opened"))


def _date_closed(row: dict[str, str]) -> str:
    return _ymd8(_col(row, "DATE_CLOSED", "DATE CLOSED", "Date Closed"))


def _pnl_pct(row: dict[str, str]) -> float:
    return _safe_num(_col(row, "PNL_PCT", "PNL %", "PNL%"))


def _pnl_dollars(row: dict[str, str], *, brt_cash: float = 0.0) -> float:
    raw = _col(row, "PNL_DOLLARS", "PNL $", "PNL$", "PNL")
    if str(raw).strip():
        return _safe_num(raw)
    # AWK-style Closed (e.g. RL): synthesize fixed-notional dollars from PNL%
    pct = _pnl_pct(row)
    if brt_cash > 0 and pct != 0.0:
        return brt_cash * (pct / 100.0)
    return 0.0


def _days_held(row: dict[str, str]) -> float:
    return _safe_num(_col(row, "DAYS_HELD", "DAYS HELD", "DAYS_OPEN", "DAYS OPEN"))


def load_spy_trading_days(path: Path = SPY_PATH) -> list[str]:
    if not path.exists():
        return []
    days: list[str] = []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ymd = _ymd8(row.get("Date") or row.get("date") or "")
            if len(ymd) == 8:
                days.append(ymd)
    return days


def last_bar_ymd(spy_days: list[str], today: Optional[date] = None) -> str:
    today = today or date.today()
    today_s = today.strftime("%Y%m%d")
    if spy_days:
        return max(spy_days[-1], today_s) if spy_days[-1] <= today_s else spy_days[-1]
    return today_s


def build_qull_active_set(
    closed_rows: list[dict[str, str]],
    open_rows: list[dict[str, str]],
    *,
    spy_days: list[str],
    open_end_ymd: str,
) -> tuple[set[str], list[dict[str, str]], dict[str, Any]]:
    """Return (active_ymd_set, interval_rows, meta)."""
    spy_set = set(spy_days)
    intervals: list[dict[str, str]] = []
    active: set[str] = set()

    def _add_interval(sym: str, start: str, end: str, src: str) -> None:
        if len(start) != 8:
            return
        if len(end) != 8:
            end = open_end_ymd
        if end < start:
            end = start
        intervals.append(
            {
                "SYMBOL": sym,
                "DATE_OPENED": start,
                "DATE_CLOSED": end,
                "SOURCE": src,
            }
        )
        # Prefer trading days when SPY calendar available; else fill calendar days.
        if spy_days:
            for d in spy_days:
                if d < start:
                    continue
                if d > end:
                    break
                active.add(d)
        else:
            y, m, dd = int(start[:4]), int(start[4:6]), int(start[6:8])
            cur = date(y, m, dd)
            ey, em, ed = int(end[:4]), int(end[4:6]), int(end[6:8])
            end_d = date(ey, em, ed)
            while cur <= end_d:
                active.add(cur.strftime("%Y%m%d"))
                cur = date.fromordinal(cur.toordinal() + 1)

    for r in closed_rows:
        _add_interval(
            _col(r, "SYMBOL", "Symbol").strip().upper(),
            _date_opened(r),
            _date_closed(r) or open_end_ymd,
            "Closed",
        )
    for r in open_rows:
        _add_interval(
            _col(r, "SYMBOL", "Symbol").strip().upper(),
            _date_opened(r),
            open_end_ymd,
            "Open",
        )

    meta = {
        "closed_n": len(closed_rows),
        "open_n": len(open_rows),
        "intervals": len(intervals),
        "active_days": len(active),
        "open_end_ymd": open_end_ymd,
        "spy_days_available": len(spy_set),
    }
    return active, intervals, meta


def calendar_coverage(
    active: set[str],
    spy_days: list[str],
    *,
    span_start: str,
    span_end: str,
) -> dict[str, Any]:
    if spy_days and span_start and span_end:
        window = [d for d in spy_days if span_start <= d <= span_end]
    else:
        window = sorted(active)
    n_win = len(window)
    n_on = sum(1 for d in window if d in active)
    pct = (100.0 * n_on / n_win) if n_win else 0.0
    return {
        "span_start": span_start,
        "span_end": span_end,
        "trading_days_in_span": n_win,
        "qull_active_days": n_on,
        "pct_days_on": round(pct, 2),
    }


def resolve_system_closed(system: str, drive: Path = DRIVE) -> tuple[Path, str]:
    """Prefer LatestRun Closed; document matched stamp when possible."""
    latest = drive / f"{system}_LatestRun_Closed.csv"
    hint = SYSTEM_STAMP_HINTS.get(system, "")
    if hint:
        stamped = drive / f"{system}_Closed_{hint}.csv"
        if stamped.exists():
            return stamped, hint
    if latest.exists():
        # Match by size to a stamped Closed
        lr = latest
        matches = [
            p
            for p in drive.glob(f"{system}_Closed_*.csv")
            if p.stat().st_size == lr.stat().st_size
        ]
        if matches:
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            stamp = matches[0].stem.split("_")[-1]
            return matches[0], stamp
        return latest, "LatestRun"
    # Fallback: newest stamped Closed
    files = sorted(
        drive.glob(f"{system}_Closed_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"No Closed book for {system}")
    stamp = files[0].stem.split("_")[-1]
    return files[0], stamp


def load_brt_cash(system: str, stamp: str, drive: Path = DRIVE) -> float:
    candidates = [
        drive / f"{system}_Report_{stamp}.csv",
        drive / f"{system}_LatestRun_Report.csv",
        drive / f"{system}_Audit_Report_{stamp}.csv",
        drive / f"{system}_LatestRun_Audit_Report.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        rows = _load_csv(path)
        if not rows:
            continue
        if "metric" in rows[0]:
            d = {str(r.get("metric", "")).strip(): r.get("value", "") for r in rows}
            n = parse_number(d.get("brt_cash") or d.get("audit_brt_cash_1m"))
            if n and n > 0:
                return float(n)
        else:
            r = rows[0]
            n = parse_number(r.get("brt_cash") or r.get("audit_brt_cash_1m"))
            if n and n > 0:
                return float(n)
    return 50_000.0


def max_dd_pct(
    rows: list[dict[str, str]],
    *,
    brt_cash: float = 0.0,
    initial_account: float = DEFAULT_INITIAL_ACCOUNT,
    pnl_scale: float = 1.0,
) -> float:
    ordered = sorted(
        rows,
        key=lambda r: (_date_opened(r), _col(r, "SYMBOL", "Symbol").upper()),
    )
    initial = initial_account if initial_account > 0 else DEFAULT_INITIAL_ACCOUNT
    equity = initial
    eq_path: list[float] = []
    scale = float(pnl_scale) if pnl_scale and math.isfinite(pnl_scale) else 1.0
    for r in ordered:
        equity += _pnl_dollars(r, brt_cash=brt_cash) * scale
        eq_path.append(equity)
    try:
        sys.path.insert(0, str(REPO / "stock_analysis"))
        from BRT_DrawdownCalc import max_drawdown_from_equity_path as _mdd_path

        return float(_mdd_path(eq_path, initial)) * 100.0
    except Exception:
        hwm = initial
        max_dd_frac = 0.0
        for eq in eq_path:
            if eq > hwm:
                hwm = eq
            if hwm > 0:
                max_dd_frac = max(max_dd_frac, (hwm - eq) / hwm)
        return max_dd_frac * 100.0


def _clamp_ann_ror(ann: Optional[float]) -> float:
    if ann is None or not math.isfinite(ann):
        return 0.0
    if ann > 50_000:
        return 50_000.0
    if ann < -100.0:
        return -100.0
    return float(ann)


def book_metrics(
    rows: list[dict[str, str]],
    *,
    brt_cash: float,
    initial_account: float = DEFAULT_INITIAL_ACCOUNT,
    pnl_scale: float = 1.0,
    brt_cash_scale: Optional[float] = None,
) -> dict[str, Any]:
    """Book metrics from Closed rows.

    ``pnl_scale`` multiplies each trade's dollar PnL (capacity redeploy).
    ``brt_cash_scale`` defaults to ``pnl_scale`` so Ann ROR stays scale-invariant
    under proportional sizing (PnL and notional both × scale). Pass 1.0 to keep
    Report ``brt_cash`` fixed while scaling dollars (inflates Ann ROR — avoid for
    Option A capacity).
    """
    n = len(rows)
    cash_scale = float(pnl_scale if brt_cash_scale is None else brt_cash_scale)
    if not math.isfinite(cash_scale) or cash_scale <= 0:
        cash_scale = 1.0
    scale = float(pnl_scale) if pnl_scale and math.isfinite(pnl_scale) else 1.0
    eff_cash = (brt_cash if brt_cash > 0 else 50_000.0) * cash_scale
    if n == 0:
        return {
            "trades": 0,
            "wins": 0,
            "wr": 0.0,
            "total_pnl": 0.0,
            "avg_pnl_pct": 0.0,
            "ann_ror": 0.0,
            "max_dd": 0.0,
            "avg_days": 0.0,
            "capital_days": 0.0,
            "ppcd": 0.0,
            "profit_factor": 0.0,
            "pnl_scale": round(scale, 6),
            "brt_cash_eff": round(eff_cash, 2),
        }
    pnls_pct = [_pnl_pct(r) for r in rows]
    pnls_d = [_pnl_dollars(r, brt_cash=brt_cash) * scale for r in rows]
    days = [_days_held(r) for r in rows]
    wins = sum(1 for p in pnls_pct if p > 0)
    wr = 100.0 * wins / n
    total_pnl = float(sum(pnls_d))
    avg_pct = float(sum(pnls_pct) / n)
    avg_days = float(sum(days) / n) if n else 0.0
    capital_days = float(sum(max(d, 0.0) for d in days))
    ppcd = (total_pnl / capital_days) if capital_days > 1e-12 else 0.0
    gross_win = sum(p for p in pnls_d if p > 0)
    gross_loss = -sum(p for p in pnls_d if p < 0)
    pf = (gross_win / gross_loss) if gross_loss > 1e-12 else (999.0 if gross_win > 0 else 0.0)
    ann = _clamp_ann_ror(
        ann_ror_from_closed(
            total_pnl=total_pnl,
            n_trades=n,
            avg_days_held=max(avg_days, 1.0),
            brt_cash=eff_cash,
        )
    )
    return {
        "trades": n,
        "wins": wins,
        "wr": round(wr, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_pct": round(avg_pct, 4),
        "ann_ror": round(float(ann), 2),
        "max_dd": round(
            max_dd_pct(
                rows,
                brt_cash=brt_cash,
                initial_account=initial_account,
                pnl_scale=scale,
            ),
            2,
        ),
        "avg_days": round(avg_days, 2),
        "capital_days": round(capital_days, 1),
        "ppcd": round(ppcd, 2),
        "profit_factor": round(pf, 2),
        "pnl_scale": round(scale, 6),
        "brt_cash_eff": round(eff_cash, 2),
    }


def capacity_scales(
    *,
    n_control: int,
    n_gated: int,
    brt_cash: float,
    initial_account: float = DEFAULT_INITIAL_ACCOUNT,
    ctrl_capital_days: float = 0.0,
    gate_capital_days: float = 0.0,
) -> dict[str, float]:
    """Return Option A / Option B scale factors.

    Option A (primary): ``n_control / n_gated`` (= 1/coverage). Matches the
    ~4–5× intuition when coverage is ~19–28%.

    Option B (secondary): simple non-overlapping proxy — size each gated trade
    at full host capital ``V / 1`` where ``V = initial_account``, so
    ``scale_B = V / brt_cash``. Also report capital-days redeploy
    ``ctrl_capital_days / gate_capital_days`` as a concurrency-lite check.
    """
    scale_a = (float(n_control) / float(n_gated)) if n_gated > 0 else 0.0
    cash = brt_cash if brt_cash > 0 else 50_000.0
    v = initial_account if initial_account > 0 else DEFAULT_INITIAL_ACCOUNT
    scale_b = v / cash
    scale_cd = (
        float(ctrl_capital_days) / float(gate_capital_days)
        if gate_capital_days and gate_capital_days > 1e-12
        else 0.0
    )
    coverage = (float(n_gated) / float(n_control)) if n_control > 0 else 0.0
    return {
        "coverage": coverage,
        "scale_a": scale_a,
        "scale_b_nonoverlap": scale_b,
        "scale_capital_days": scale_cd,
    }


def filter_on_active(
    rows: list[dict[str, str]], active: set[str]
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    kept: list[dict[str, str]] = []
    missing_open = 0
    for r in rows:
        d = _date_opened(r)
        if not d:
            missing_open += 1
            continue
        if d in active:
            kept.append(r)
    cov = {
        "control_trades": len(rows),
        "kept_trades": len(kept),
        "coverage_pct": round(100.0 * len(kept) / len(rows), 2) if rows else 0.0,
        "missing_date_opened": missing_open,
    }
    return kept, cov


def _delta(a: float, b: float) -> float:
    return round(a - b, 4 if abs(a - b) < 10 else 2)


def _fmt_pct(v: float, *, signed: bool = False) -> str:
    if signed:
        return f"{v:+.2f}%"
    return f"{v:.2f}%"


def _fmt_num(v: float, digits: int = 2) -> str:
    return f"{v:.{digits}f}"


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build_html(
    *,
    qull_stamp: str,
    qull_meta: dict[str, Any],
    cal: dict[str, Any],
    results: list[dict[str, Any]],
    sources: list[str],
) -> str:
    # Efficiency lens: unscaled Ann ROR / PPCD. Capacity lens: Option A scaled PnL.
    helped_pnl_raw = [r for r in results if r["d_total_pnl"] > 0]
    helped_pnl_scaled = [r for r in results if r["d_total_pnl_scaled_a"] > 0]
    helped_ror = [r for r in results if r["d_ann_ror"] > 0]
    helped_ppcd = [r for r in results if r["d_ppcd"] > 0]
    helped_capacity = [
        r
        for r in results
        if r["d_total_pnl_scaled_a"] > 0 and r["d_ann_ror"] > 0 and r["d_ppcd"] > 0
    ]
    helped_all_raw = [
        r
        for r in results
        if r["d_total_pnl"] > 0 and r["d_ann_ror"] > 0 and r["d_ppcd"] > 0
    ]

    def verdict_li(label: str, rows: list[dict[str, Any]], key: str) -> str:
        if not rows:
            return f"<li><strong>{html.escape(label)}</strong>: none.</li>"

        def _fmt_delta(r: dict[str, Any]) -> str:
            if key in (
                "d_total_pnl",
                "d_total_pnl_scaled_a",
                "d_total_pnl_scaled_b",
                "d_ppcd",
                "d_ppcd_scaled_a",
            ):
                return format_money_delta(r[key])
            return f"{r[key]:+.2f}"

        bits = ", ".join(
            f"{html.escape(r['system'])} (Δ {_fmt_delta(r)})" for r in rows
        )
        return f"<li><strong>{html.escape(label)}</strong>: {bits}.</li>"

    ths = "".join(
        [
            sortable_th("System", "text"),
            sortable_th("Arm", "text"),
            sortable_th("Stamp", "text"),
            sortable_th("Trades", "num"),
            sortable_th("Coverage %", "num"),
            sortable_th("Scale A (1/cov)", "num"),
            sortable_th("Win %", "num"),
            sortable_th("Total PnL $ (unscaled)", "num"),
            sortable_th("Δ PnL unscaled", "num"),
            sortable_th("Total PnL $ (scaled A)", "num"),
            sortable_th("Δ PnL scaled A", "num"),
            sortable_th("Total PnL $ (scaled B)", "num"),
            sortable_th("Δ PnL scaled B", "num"),
            sortable_th("Ann ROR % (eff)", "num"),
            sortable_th("Δ Ann ROR", "num"),
            sortable_th("PPCD $ (eff)", "num"),
            sortable_th("Δ PPCD $", "num"),
            sortable_th("PPCD $ (scaled A)", "num"),
            sortable_th("Max DD % (unscaled)", "num"),
            sortable_th("Max DD % (scaled A)", "num"),
            sortable_th("Avg days", "num"),
            sortable_th("PF", "num"),
            sortable_th("Beats ctrl scaled PnL?", "text"),
            sortable_th("Beats ctrl Ann ROR?", "text"),
            sortable_th("Beats ctrl PPCD?", "text"),
        ]
    )

    body_rows: list[str] = []
    for r in results:
        for arm in ("control", "qull_timing", "qull_timing_scaled_A"):
            if arm == "control":
                cells = [
                    r["system"],
                    "control",
                    r["stamp"],
                    str(r["ctrl_trades"]),
                    "100.00",
                    "1.00",
                    _fmt_num(r["ctrl_wr"]),
                    format_money(r["ctrl_total_pnl"]),
                    "—",
                    format_money(r["ctrl_total_pnl"]),
                    "—",
                    format_money(r["ctrl_total_pnl"]),
                    "—",
                    _fmt_num(r["ctrl_ann_ror"]),
                    "—",
                    format_money(r["ctrl_ppcd"]),
                    "—",
                    format_money(r["ctrl_ppcd"]),
                    _fmt_num(r["ctrl_max_dd"]),
                    _fmt_num(r["ctrl_max_dd"]),
                    _fmt_num(r["ctrl_avg_days"]),
                    _fmt_num(r["ctrl_pf"]),
                    "",
                    "",
                    "",
                ]
            elif arm == "qull_timing":
                cells = [
                    r["system"],
                    "qull_timing (unscaled)",
                    r["stamp"],
                    str(r["gate_trades"]),
                    _fmt_num(r["coverage_pct"]),
                    _fmt_num(r["scale_a"], 3),
                    _fmt_num(r["gate_wr"]),
                    format_money(r["gate_total_pnl"]),
                    format_money_delta(r["d_total_pnl"]),
                    "—",
                    "—",
                    "—",
                    "—",
                    _fmt_num(r["gate_ann_ror"]),
                    f"{r['d_ann_ror']:+.2f}",
                    format_money(r["gate_ppcd"]),
                    format_money_delta(r["d_ppcd"]),
                    "—",
                    _fmt_num(r["gate_max_dd"]),
                    "—",
                    _fmt_num(r["gate_avg_days"]),
                    _fmt_num(r["gate_pf"]),
                    "yes" if r["d_total_pnl_scaled_a"] > 0 else "no",
                    "yes" if r["d_ann_ror"] > 0 else "no",
                    "yes" if r["d_ppcd"] > 0 else "no",
                ]
            else:
                cells = [
                    r["system"],
                    "qull_timing (scaled A)",
                    r["stamp"],
                    str(r["gate_trades"]),
                    _fmt_num(r["coverage_pct"]),
                    _fmt_num(r["scale_a"], 3),
                    _fmt_num(r["gate_wr"]),
                    "—",
                    "—",
                    format_money(r["gate_total_pnl_scaled_a"]),
                    format_money_delta(r["d_total_pnl_scaled_a"]),
                    format_money(r["gate_total_pnl_scaled_b"]),
                    format_money_delta(r["d_total_pnl_scaled_b"]),
                    _fmt_num(r["gate_ann_ror"]),  # scale-invariant under A
                    f"{r['d_ann_ror']:+.2f}",
                    "—",
                    "—",
                    format_money(r["gate_ppcd_scaled_a"]),
                    "—",
                    _fmt_num(r["gate_max_dd_scaled_a"]),
                    _fmt_num(r["gate_avg_days"]),
                    _fmt_num(r["gate_pf"]),
                    "yes" if r["d_total_pnl_scaled_a"] > 0 else "no",
                    "yes" if r["d_ann_ror"] > 0 else "no",
                    "yes" if r["d_ppcd"] > 0 else "no",
                ]
            flag_idxs = {22, 23, 24}
            tds = "".join(
                f"<td class='num'>{html.escape(c)}</td>"
                if i >= 3 and i not in flag_idxs
                else f"<td>{html.escape(c)}</td>"
                for i, c in enumerate(cells)
            )
            body_rows.append(f"<tr>{tds}</tr>")

    # Compact capacity summary table
    cap_ths = "".join(
        [
            sortable_th("System", "text"),
            sortable_th("Coverage %", "num"),
            sortable_th("Scale A", "num"),
            sortable_th("Scale B (V/cash)", "num"),
            sortable_th("Ctrl PnL", "num"),
            sortable_th("Unscaled PnL", "num"),
            sortable_th("Scaled A PnL", "num"),
            sortable_th("Δ Scaled A vs ctrl", "num"),
            sortable_th("Scaled B PnL", "num"),
            sortable_th("Ann ROR ctrl", "num"),
            sortable_th("Ann ROR gate", "num"),
            sortable_th("PPCD ctrl", "num"),
            sortable_th("PPCD gate (eff)", "num"),
            sortable_th("PPCD scaled A", "num"),
        ]
    )
    cap_rows: list[str] = []
    for r in results:
        cells = [
            r["system"],
            _fmt_num(r["coverage_pct"]),
            _fmt_num(r["scale_a"], 3),
            _fmt_num(r["scale_b"], 3),
            format_money(r["ctrl_total_pnl"]),
            format_money(r["gate_total_pnl"]),
            format_money(r["gate_total_pnl_scaled_a"]),
            format_money_delta(r["d_total_pnl_scaled_a"]),
            format_money(r["gate_total_pnl_scaled_b"]),
            _fmt_num(r["ctrl_ann_ror"]),
            _fmt_num(r["gate_ann_ror"]),
            format_money(r["ctrl_ppcd"]),
            format_money(r["gate_ppcd"]),
            format_money(r["gate_ppcd_scaled_a"]),
        ]
        tds = "".join(
            f"<td class='num'>{html.escape(c)}</td>" if i >= 1 else f"<td>{html.escape(c)}</td>"
            for i, c in enumerate(cells)
        )
        cls = "better" if r["d_total_pnl_scaled_a"] > 0 else "worse"
        cap_rows.append(f"<tr class='{cls}'>{tds}</tr>")

    src_lis = "".join(f"<li>{html.escape(s)}</li>" for s in sources)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>QULL timing gate A/B (capacity-adjusted)</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;line-height:1.45;color:#1a1a1a;max-width:1600px}}
h1{{font-size:1.45rem}} h2{{font-size:1.1rem;margin-top:1.6rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.85rem}}
th,td{{border:1px solid #ccc;padding:.35rem .5rem;text-align:left}}
th{{background:#f3f3f3}}
tr.better td:first-child{{box-shadow:inset 3px 0 0 #166534}}
tr.worse td:first-child{{box-shadow:inset 3px 0 0 #991b1b}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>QULL as market-timing gate A/B (capacity-adjusted)</h1>
<p class="note">Post-hoc filter: keep a system's Closed trade only if its
<code>DATE_OPENED</code> falls on a day when Qullamaggie High Tight Flag (QULL)
was opening or already in a trade. Does <strong>not</strong> re-run engines.
Click column headers to sort. Dollar fields use <code>$nnn,nnn.nn</code>.</p>
<div class="def">
<strong>QULL calendar stamp:</strong> <code>{html.escape(qull_stamp)}</code>
(Closed={qull_meta.get('closed_n')} Open={qull_meta.get('open_n')};
active trading days={qull_meta.get('active_days')}; open-end={qull_meta.get('open_end_ymd')}).<br>
<strong>Calendar coverage:</strong> {cal.get('pct_days_on')}% of SPY trading days
in [{html.escape(str(cal.get('span_start')))} … {html.escape(str(cal.get('span_end')))}]
({cal.get('qull_active_days')} / {cal.get('trading_days_in_span')}).<br>
<strong>Gate:</strong> <code>qull_timing</code> = DATE_OPENED ∈ QULL active set
(open-inclusive intervals).<br>
<strong>Capacity Option A (primary):</strong> <code>scale_A = n_control / n_gated</code>
(= 1/coverage). Each kept trade's <code>PNL_DOLLARS</code> × scale_A, then re-sum.
Assumes <em>full redeploy</em> of freed capital into remaining trades
(no liquidity / correlation / fill frictions).<br>
<strong>Capacity Option B (secondary):</strong> simple non-overlapping proxy
<code>scale_B = initial_account / brt_cash</code> (each gated trade sized at full
host V as if max concurrent = 1). Not a true overlap-calendar re-sim.<br>
<strong>Efficiency:</strong> Ann ROR % and PPCD on <em>unscaled</em> fixed-notional
book (Report <code>brt_cash</code>). Under Option A proportional sizing, Ann ROR is
scale-invariant (PnL and notional both × scale_A).<br>
<strong>Skipped:</strong> IND (deprecated). Live engine <code>-v</code> QULL-day
overlay = future work.
</div>
<h2>Verdict (capacity-aware)</h2>
<ul>
{verdict_li("Scaled A Total PnL improved", helped_pnl_scaled, "d_total_pnl_scaled_a")}
{verdict_li("Unscaled Total PnL improved (fixed notional)", helped_pnl_raw, "d_total_pnl")}
{verdict_li("Ann ROR improved (efficiency)", helped_ror, "d_ann_ror")}
{verdict_li("PPCD improved (efficiency)", helped_ppcd, "d_ppcd")}
<li><strong>Capacity joint (scaled A PnL + Ann ROR + PPCD)</strong>:
{"none." if not helped_capacity else ", ".join(html.escape(r["system"]) for r in helped_capacity) + "."}</li>
<li><strong>Raw joint (unscaled PnL + Ann ROR + PPCD)</strong>:
{"none." if not helped_all_raw else ", ".join(html.escape(r["system"]) for r in helped_all_raw) + "."}</li>
</ul>
<h2>Capacity summary</h2>
<p class="note">Coverage → Scale A (~4–5× when coverage ~20–25%). Scaled A PnL =
unscaled gate PnL × Scale A. Green/red edge = scaled A Δ vs control.</p>
<table class="sortable">
<thead><tr>{cap_ths}</tr></thead>
<tbody>
{''.join(cap_rows)}
</tbody>
</table>
<h2>Sources</h2>
<ul class="note">{src_lis}</ul>
<h2>Full comparison</h2>
<p class="note">Primary lenses: capacity-scaled Total PnL $ (Option A), Ann ROR %
(efficiency), Profit per capital day (efficiency). Max DD from sequential Closed
PnL equity path seeded at $500,000.</p>
<table class="sortable">
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def write_decision_log(
    path: Path,
    *,
    qull_stamp: str,
    qull_meta: dict[str, Any],
    cal: dict[str, Any],
    results: list[dict[str, Any]],
    sources: list[str],
) -> None:
    helped_pnl_raw = [r for r in results if r["d_total_pnl"] > 0]
    helped_pnl_scaled = [r for r in results if r["d_total_pnl_scaled_a"] > 0]
    helped_ror = [r for r in results if r["d_ann_ror"] > 0]
    helped_ppcd = [r for r in results if r["d_ppcd"] > 0]
    helped_capacity = [
        r
        for r in results
        if r["d_total_pnl_scaled_a"] > 0 and r["d_ann_ror"] > 0 and r["d_ppcd"] > 0
    ]
    lines = [
        "# QULL timing gate A/B — DECISION_LOG",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Hypothesis",
        "",
        "Use Qullamaggie High Tight Flag (QULL) as a **market timing** filter: "
        "only allow other production systems to open when QULL is opening or "
        "already in a trade.",
        "",
        "## Method",
        "",
        f"- QULL book stamp: `{qull_stamp}` (prefer full-universe control).",
        f"- Closed positions: {qull_meta.get('closed_n')}; Open: {qull_meta.get('open_n')}.",
        "- Active day: any position with DATE_OPENED ≤ day ≤ DATE_CLOSED "
        "(open-inclusive). Open rows extend through last SPY bar / today "
        f"(`{qull_meta.get('open_end_ymd')}`).",
        "- Post-hoc filter of each system's Closed: keep if DATE_OPENED ∈ active set.",
        "- **Unscaled metrics**: fixed-notional sum of filtered Closed (Report "
        "`brt_cash`); Ann ROR via `compare_format.ann_ror_from_closed`; Max DD via "
        "equity path; PPCD = Total PnL / capital days.",
        "- **Capacity Option A (primary)**: `scale_A = n_control / n_gated` "
        "(= 1/coverage). Multiply each kept trade `PNL_DOLLARS` by scale_A, re-sum "
        "Total PnL; PPCD_scaled = scaled_PnL / capital_days; Max DD on scaled "
        "equity path. Ann ROR under proportional sizing (notional also × scale_A) "
        "is unchanged vs unscaled — report unscaled Ann ROR as efficiency.",
        "- **Capacity Option B (secondary)**: simple non-overlapping proxy "
        "`scale_B = initial_account / brt_cash` (full host V per gated trade). "
        "Not an overlap-calendar re-sim.",
        "- **Assumption (explicit)**: scaled Total PnL assumes full redeploy of "
        "freed capital into remaining trades — no liquidity, correlation, or fill "
        "frictions.",
        "- Does **not** re-simulate host cash / concurrency. Engine `-v` live "
        "gate = future work.",
        "- IND skipped (deprecated).",
        "",
        "## Calendar coverage",
        "",
        f"- Span: `{cal.get('span_start')}` … `{cal.get('span_end')}` (SPY trading days).",
        f"- QULL on: **{cal.get('pct_days_on')}%** "
        f"({cal.get('qull_active_days')} / {cal.get('trading_days_in_span')}).",
        "",
        "## Sources",
        "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    lines += [
        "",
        "## Per-system results (capacity-adjusted)",
        "",
        "| System | Cov% | ScaleA | Unscaled PnL | ScaledA PnL | Δ ScaledA vs ctrl | "
        "ScaledB PnL | Ctrl PnL | AnnROR ctrl | AnnROR gate | PPCD ctrl | PPCD gate | PPCD scaledA |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['system']} | {r['coverage_pct']:.1f} | {r['scale_a']:.3f} | "
            f"{format_money(r['gate_total_pnl'])} | "
            f"{format_money(r['gate_total_pnl_scaled_a'])} | "
            f"{format_money_delta(r['d_total_pnl_scaled_a'])} | "
            f"{format_money(r['gate_total_pnl_scaled_b'])} | "
            f"{format_money(r['ctrl_total_pnl'])} | "
            f"{r['ctrl_ann_ror']:.2f} | {r['gate_ann_ror']:.2f} | "
            f"{format_money(r['ctrl_ppcd'])} | {format_money(r['gate_ppcd'])} | "
            f"{format_money(r['gate_ppcd_scaled_a'])} |"
        )
    lines += [
        "",
        "## Unscaled detail (fixed notional — prior reject lens)",
        "",
        "| System | Stamp | Ctrl N | Gate N | Cov% | Ctrl PnL | Gate PnL | "
        "ΔPnL | Ctrl AnnROR | Gate AnnROR | ΔROR | Ctrl PPCD | Gate PPCD | ΔPPCD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['system']} | `{r['stamp']}` | {r['ctrl_trades']} | {r['gate_trades']} | "
            f"{r['coverage_pct']:.1f} | {format_money(r['ctrl_total_pnl'])} | "
            f"{format_money(r['gate_total_pnl'])} | {format_money_delta(r['d_total_pnl'])} | "
            f"{r['ctrl_ann_ror']:.2f} | {r['gate_ann_ror']:.2f} | {r['d_ann_ror']:+.2f} | "
            f"{format_money(r['ctrl_ppcd'])} | {format_money(r['gate_ppcd'])} | "
            f"{format_money_delta(r['d_ppcd'])} |"
        )
    lines += ["", "## Verdict", ""]
    n_scaled_win = len(helped_pnl_scaled)
    if helped_capacity:
        lines.append(
            "**Capacity-aware: research follow-up** on "
            + ", ".join(r["system"] for r in helped_capacity)
            + " — beat control on **scaled-A Total PnL** + Ann ROR + PPCD "
            "(assumes full redeploy of freed capital; no liquidity/correlation frictions)."
        )
    elif n_scaled_win > 0:
        lines.append(
            f"**Capacity-aware: mixed / not a clean production overlay.** "
            f"{n_scaled_win}/{len(results)} systems beat control on Option-A scaled "
            "Total PnL, but **none** jointly beat on scaled-A PnL **and** Ann ROR "
            "**and** PPCD. Unscaled (fixed-notional) Total PnL still loses everywhere."
        )
    else:
        lines.append(
            "**Reject as a production timing overlay** even after Option-A capacity "
            "scaling: no system beat control on scaled-A Total PnL, and none jointly "
            "beat on scaled PnL + Ann ROR + PPCD."
        )
    lines.append("")
    if helped_pnl_scaled:
        lines.append(
            "- Scaled-A Total PnL up: "
            + ", ".join(
                f"{r['system']} ({format_money_delta(r['d_total_pnl_scaled_a'])})"
                for r in helped_pnl_scaled
            )
        )
    else:
        lines.append("- Scaled-A Total PnL up: none")
    if helped_pnl_raw:
        lines.append(
            "- Unscaled Total PnL up: "
            + ", ".join(
                f"{r['system']} ({format_money_delta(r['d_total_pnl'])})"
                for r in helped_pnl_raw
            )
        )
    else:
        lines.append("- Unscaled Total PnL up: none")
    if helped_ror:
        lines.append(
            "- Ann ROR up (efficiency): "
            + ", ".join(f"{r['system']} ({r['d_ann_ror']:+.2f})" for r in helped_ror)
        )
    else:
        lines.append("- Ann ROR up (efficiency): none")
    if helped_ppcd:
        lines.append(
            "- PPCD up (efficiency): "
            + ", ".join(
                f"{r['system']} ({format_money_delta(r['d_ppcd'])})" for r in helped_ppcd
            )
        )
    else:
        lines.append("- PPCD up (efficiency): none")
    if helped_capacity:
        lines.append(
            "- Capacity joint winners: " + ", ".join(r["system"] for r in helped_capacity)
        )
    else:
        lines.append("- Capacity joint winners: none")
    lines += [
        "",
        "## Notes",
        "",
        "- Prior reject used **unscaled** fixed-notional Total PnL (sum of filtered "
        "Closed at Report `brt_cash`). That understates capacity when coverage is "
        "~19–28% and freed capital could size remaining trades ~4–5×.",
        "- Option A scaled PnL = unscaled gate PnL × (n_control / n_gated). Explicit "
        "assumption: full redeploy into remaining trades; no liquidity / correlation / "
        "fill frictions.",
        "- Option B (non-overlap V/brt_cash) is a secondary upper-bound style proxy, "
        "not a host overlap re-sim.",
        "- Ann ROR / unscaled PPCD remain efficiency metrics; scaled PPCD = "
        "scaled_PnL / capital_days.",
        "- Post-hoc keep/drop still does not invent alternative entries on QULL-off days.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qull-stamp", default=DEFAULT_QULL_STAMP)
    ap.add_argument(
        "--systems",
        default=",".join(DEFAULT_SYSTEMS),
        help="Comma-separated system prefixes",
    )
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--drive", type=Path, default=DRIVE)
    args = ap.parse_args(argv)

    out: Path = args.out
    drive: Path = args.drive
    out.mkdir(parents=True, exist_ok=True)

    qull_stamp = str(args.qull_stamp).strip()
    qull_closed_path = drive / f"QULL_Closed_{qull_stamp}.csv"
    qull_open_path = drive / f"QULL_Open_{qull_stamp}.csv"
    if not qull_closed_path.exists():
        # Fallback LatestRun
        alt = drive / "QULL_LatestRun_Closed.csv"
        if alt.exists():
            qull_closed_path = alt
            qull_open_path = drive / "QULL_LatestRun_Open.csv"
            qull_stamp = f"LatestRun(fallback; wanted {qull_stamp})"
        else:
            raise SystemExit(f"Missing QULL Closed: {qull_closed_path}")

    spy_days = load_spy_trading_days()
    open_end = last_bar_ymd(spy_days)
    closed_rows = _load_csv(qull_closed_path)
    open_rows = _load_csv(qull_open_path) if qull_open_path.exists() else []
    active, intervals, qull_meta = build_qull_active_set(
        closed_rows, open_rows, spy_days=spy_days, open_end_ymd=open_end
    )
    qull_meta["stamp"] = qull_stamp
    qull_meta["closed_path"] = str(qull_closed_path.relative_to(REPO)).replace("\\", "/")
    qull_meta["open_path"] = (
        str(qull_open_path.relative_to(REPO)).replace("\\", "/")
        if qull_open_path.exists()
        else ""
    )

    # Span for % on: QULL book min open → max close (or open_end)
    all_starts = [_date_opened(r) for r in closed_rows + open_rows]
    all_ends = [
        _date_closed(r) or open_end for r in closed_rows
    ] + ([open_end] if open_rows else [])
    all_starts = [d for d in all_starts if d]
    all_ends = [d for d in all_ends if d]
    span_start = min(all_starts) if all_starts else (spy_days[0] if spy_days else "")
    span_end = max(all_ends) if all_ends else open_end
    cal = calendar_coverage(active, spy_days, span_start=span_start, span_end=span_end)

    # Persist active calendar
    active_sorted = sorted(active)
    with (out / "qull_active_days.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ymd", "active"])
        if spy_days:
            for d in spy_days:
                if span_start <= d <= span_end:
                    w.writerow([d, 1 if d in active else 0])
        else:
            for d in active_sorted:
                w.writerow([d, 1])
    with (out / "qull_intervals.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["SYMBOL", "DATE_OPENED", "DATE_CLOSED", "SOURCE"]
        )
        w.writeheader()
        for row in intervals:
            w.writerow(row)

    systems = [s.strip().upper() for s in str(args.systems).split(",") if s.strip()]
    results: list[dict[str, Any]] = []
    sources: list[str] = [
        f"QULL Closed: {qull_meta['closed_path']} (stamp {qull_stamp})",
        f"QULL Open: {qull_meta.get('open_path') or '(none)'} "
        f"(open_n={qull_meta.get('open_n')})",
        f"Calendar: {cal.get('pct_days_on')}% SPY days on "
        f"({cal.get('qull_active_days')}/{cal.get('trading_days_in_span')}) "
        f"in [{cal.get('span_start')}…{cal.get('span_end')}]",
    ]

    csv_rows: list[dict[str, Any]] = []
    for system in systems:
        if system == "IND":
            sources.append(f"{system}: skipped (deprecated)")
            continue
        try:
            closed_path, stamp = resolve_system_closed(system, drive)
        except FileNotFoundError as e:
            sources.append(f"{system}: MISSING ({e})")
            continue
        rows = _load_csv(closed_path)
        cash = load_brt_cash(system, stamp, drive)
        ctrl = book_metrics(rows, brt_cash=cash)
        kept, cov = filter_on_active(rows, active)
        gate = book_metrics(kept, brt_cash=cash)
        scales = capacity_scales(
            n_control=ctrl["trades"],
            n_gated=gate["trades"],
            brt_cash=cash,
            initial_account=DEFAULT_INITIAL_ACCOUNT,
            ctrl_capital_days=ctrl["capital_days"],
            gate_capital_days=gate["capital_days"],
        )
        scale_a = scales["scale_a"]
        scale_b = scales["scale_b_nonoverlap"]
        # Option A: PnL × scale_A; Ann ROR scale-invariant via proportional notional.
        gate_a = book_metrics(kept, brt_cash=cash, pnl_scale=scale_a)
        # Option B: non-overlap full-account sizing (secondary).
        gate_b = book_metrics(
            kept, brt_cash=cash, pnl_scale=scale_b, brt_cash_scale=scale_b
        )
        rel = str(closed_path.relative_to(REPO)).replace("\\", "/")
        sources.append(
            f"{system}: {rel} (stamp {stamp}, brt_cash={cash:.2f}, "
            f"coverage {cov['coverage_pct']:.1f}% = {cov['kept_trades']}/{cov['control_trades']}, "
            f"scale_A={scale_a:.3f}, scale_B={scale_b:.3f})"
        )
        rec = {
            "system": system,
            "stamp": stamp,
            "closed_path": rel,
            "brt_cash": cash,
            "ctrl_trades": ctrl["trades"],
            "gate_trades": gate["trades"],
            "coverage_pct": cov["coverage_pct"],
            "scale_a": round(scale_a, 6),
            "scale_b": round(scale_b, 6),
            "scale_capital_days": round(scales["scale_capital_days"], 6),
            "ctrl_wr": ctrl["wr"],
            "gate_wr": gate["wr"],
            "ctrl_total_pnl": ctrl["total_pnl"],
            "gate_total_pnl": gate["total_pnl"],
            "d_total_pnl": round(gate["total_pnl"] - ctrl["total_pnl"], 2),
            "gate_total_pnl_scaled_a": gate_a["total_pnl"],
            "d_total_pnl_scaled_a": round(gate_a["total_pnl"] - ctrl["total_pnl"], 2),
            "gate_total_pnl_scaled_b": gate_b["total_pnl"],
            "d_total_pnl_scaled_b": round(gate_b["total_pnl"] - ctrl["total_pnl"], 2),
            "ctrl_ann_ror": ctrl["ann_ror"],
            "gate_ann_ror": gate["ann_ror"],
            "d_ann_ror": round(gate["ann_ror"] - ctrl["ann_ror"], 2),
            "gate_ann_ror_scaled_a": gate_a["ann_ror"],
            "ctrl_max_dd": ctrl["max_dd"],
            "gate_max_dd": gate["max_dd"],
            "d_max_dd": round(gate["max_dd"] - ctrl["max_dd"], 2),
            "gate_max_dd_scaled_a": gate_a["max_dd"],
            "d_max_dd_scaled_a": round(gate_a["max_dd"] - ctrl["max_dd"], 2),
            "ctrl_ppcd": ctrl["ppcd"],
            "gate_ppcd": gate["ppcd"],
            "d_ppcd": round(gate["ppcd"] - ctrl["ppcd"], 2),
            "gate_ppcd_scaled_a": gate_a["ppcd"],
            "d_ppcd_scaled_a": round(gate_a["ppcd"] - ctrl["ppcd"], 2),
            "ctrl_avg_days": ctrl["avg_days"],
            "gate_avg_days": gate["avg_days"],
            "ctrl_pf": ctrl["profit_factor"],
            "gate_pf": gate["profit_factor"],
            "ctrl_capital_days": ctrl["capital_days"],
            "gate_capital_days": gate["capital_days"],
            "ctrl_avg_pnl_pct": ctrl["avg_pnl_pct"],
            "gate_avg_pnl_pct": gate["avg_pnl_pct"],
        }
        results.append(rec)

        def _csv_arm(arm: str, m: dict[str, Any], *, scaled_vs: str = "") -> dict[str, Any]:
            is_ctrl = arm == "control"
            d_pnl = 0.0
            beats_pnl = ""
            if not is_ctrl:
                if scaled_vs == "A":
                    d_pnl = rec["d_total_pnl_scaled_a"]
                    beats_pnl = "yes" if d_pnl > 0 else "no"
                elif scaled_vs == "B":
                    d_pnl = rec["d_total_pnl_scaled_b"]
                    beats_pnl = "yes" if d_pnl > 0 else "no"
                else:
                    d_pnl = rec["d_total_pnl"]
                    beats_pnl = "yes" if d_pnl > 0 else "no"
            return {
                "system": system,
                "arm": arm,
                "stamp": stamp,
                "closed_path": rel,
                "brt_cash": cash,
                "trades": m["trades"],
                "coverage_pct": 100.0 if is_ctrl else cov["coverage_pct"],
                "scale_a": 1.0 if is_ctrl else scale_a,
                "scale_b": 1.0 if is_ctrl else scale_b,
                "pnl_scale_applied": m.get("pnl_scale", 1.0),
                "win_pct": m["wr"],
                "total_pnl": m["total_pnl"],
                "total_pnl_unscaled": gate["total_pnl"] if not is_ctrl else ctrl["total_pnl"],
                "ann_ror": m["ann_ror"],
                "max_dd": m["max_dd"],
                "ppcd": m["ppcd"],
                "avg_days": m["avg_days"],
                "capital_days": m["capital_days"],
                "profit_factor": m["profit_factor"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "d_total_pnl": d_pnl if not is_ctrl else 0.0,
                "d_total_pnl_scaled_a": rec["d_total_pnl_scaled_a"] if not is_ctrl else 0.0,
                "d_total_pnl_scaled_b": rec["d_total_pnl_scaled_b"] if not is_ctrl else 0.0,
                "d_ann_ror": rec["d_ann_ror"] if not is_ctrl else 0.0,
                "d_max_dd": (
                    rec["d_max_dd_scaled_a"]
                    if scaled_vs == "A"
                    else (rec["d_max_dd"] if not is_ctrl else 0.0)
                ),
                "d_ppcd": (
                    rec["d_ppcd_scaled_a"]
                    if scaled_vs == "A"
                    else (rec["d_ppcd"] if not is_ctrl else 0.0)
                ),
                "beats_ctrl_pnl_unscaled": ""
                if is_ctrl
                else ("yes" if rec["d_total_pnl"] > 0 else "no"),
                "beats_ctrl_pnl_scaled_a": ""
                if is_ctrl
                else ("yes" if rec["d_total_pnl_scaled_a"] > 0 else "no"),
                "beats_ctrl_ann_ror": ""
                if is_ctrl
                else ("yes" if rec["d_ann_ror"] > 0 else "no"),
                "beats_ctrl_ppcd": ""
                if is_ctrl
                else ("yes" if rec["d_ppcd"] > 0 else "no"),
                "beats_ctrl_pnl": beats_pnl,
            }

        csv_rows.append(_csv_arm("control", ctrl))
        csv_rows.append(_csv_arm("qull_timing", gate))
        csv_rows.append(_csv_arm("qull_timing_scaled_A", gate_a, scaled_vs="A"))
        csv_rows.append(_csv_arm("qull_timing_scaled_B", gate_b, scaled_vs="B"))

    fieldnames = [
        "system",
        "arm",
        "stamp",
        "closed_path",
        "brt_cash",
        "trades",
        "coverage_pct",
        "scale_a",
        "scale_b",
        "pnl_scale_applied",
        "win_pct",
        "total_pnl",
        "total_pnl_unscaled",
        "ann_ror",
        "max_dd",
        "ppcd",
        "avg_days",
        "capital_days",
        "profit_factor",
        "avg_pnl_pct",
        "d_total_pnl",
        "d_total_pnl_scaled_a",
        "d_total_pnl_scaled_b",
        "d_ann_ror",
        "d_max_dd",
        "d_ppcd",
        "beats_ctrl_pnl",
        "beats_ctrl_pnl_unscaled",
        "beats_ctrl_pnl_scaled_a",
        "beats_ctrl_ann_ror",
        "beats_ctrl_ppcd",
    ]
    write_csv(out / "comparison.csv", csv_rows, fieldnames)
    (out / "comparison.html").write_text(
        build_html(
            qull_stamp=qull_stamp,
            qull_meta=qull_meta,
            cal=cal,
            results=results,
            sources=sources,
        ),
        encoding="utf-8",
    )
    write_decision_log(
        out / "DECISION_LOG.md",
        qull_stamp=qull_stamp,
        qull_meta=qull_meta,
        cal=cal,
        results=results,
        sources=sources,
    )

    print(f"QULL stamp={qull_stamp} active_days={qull_meta['active_days']} "
          f"pct_on={cal['pct_days_on']}%")
    print(f"Wrote {out / 'comparison.html'}")
    print(f"Wrote {out / 'comparison.csv'}")
    print(f"Wrote {out / 'DECISION_LOG.md'}")
    for r in results:
        print(
            f"  {r['system']}: cov={r['coverage_pct']:.1f}% scaleA={r['scale_a']:.2f} "
            f"PnL unscaled {format_money(r['gate_total_pnl'])} "
            f"scaledA {format_money(r['gate_total_pnl_scaled_a'])} "
            f"({format_money_delta(r['d_total_pnl_scaled_a'])} vs ctrl "
            f"{format_money(r['ctrl_total_pnl'])}) "
            f"AnnROR {r['ctrl_ann_ror']:.1f}->{r['gate_ann_ror']:.1f} "
            f"({r['d_ann_ror']:+.1f}) "
            f"PPCD {format_money(r['ctrl_ppcd'])}->{format_money(r['gate_ppcd'])} "
            f"({format_money_delta(r['d_ppcd'])})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
