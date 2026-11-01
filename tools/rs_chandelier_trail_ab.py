#!/usr/bin/env python3
"""RS chandelier ATR trail EXIT overlay A/B (N% arm × k×ATR(14 Wilder)).

Research-only. Same entries as control; only stop trailing changes.

Freeze (prod TODAY 2026-09-04 via run_rs.bat / rs_baseline_260807141317):
  rs_mode, rs_require_tc_strong=true, rs_spy_int_tc_not_weak=true,
  symbol_reentry_cooldown_days=60,
  stop_pct=0.85 (multiplier), target_pct=1.25, time_stop_days=252,
  trailing_stop_increment=0 (off).

Control Closed: gold freeze engine Closed RS_Closed_260807141317.csv
  (same control as rs_lockin_trail_ab_20260904).

Formula (ratcheting chandelier):
  peak_pct = (max High since entry − entry) / entry
  once peak_pct >= N/100:
    chan_stop = highest_high_since_entry − k × ATR(14 Wilder, prior bar)
    ratchet only upward; never loosen
  Exit CHANDELIER_TRAIL when Low ≤ chan_stop (gap Open ≤ stop → fill @Open).
  Fill bar: update peak/arm only; do not stop. Never extends past original close.
  If chandelier never fires → keep control exit (TARGET / TIME / STOP / …).

Arms: control + N=10 × k∈{2.0,2.5,3.0} + N∈{8,12} at k=2.5 (cheap extras).

Usage:
  python tools/rs_chandelier_trail_ab.py
  python tools/rs_chandelier_trail_ab.py --closed path/to/RS_Closed_*.csv --out drive/paul_experiments/foo
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import (  # noqa: E402
    RS_CASH,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    book_stats,
    load_closed,
    load_ohlc,
    split_is_oos,
    sortable_th,
)
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    filter_html_compare_columns,
    format_money,
    overlay_ann_ror_max_dd,
)

STAMP = "20260904"
DEFAULT_CLOSED = (
    DRIVE
    / "paul_experiments"
    / "rs_baseline_260807141317"
    / "engine_closed"
    / "RS_Closed_260807141317.csv"
)
DEFAULT_OUT = DRIVE / "paul_experiments" / f"rs_chandelier_trail_ab_{STAMP}"
IS_CUT = date(2024, 1, 1)
INIT = DEFAULT_INITIAL_ACCOUNT
OUT_DIR = DEFAULT_OUT
CLOSED = DEFAULT_CLOSED
ATR_N = 14


def _build_arms() -> list[dict[str, Any]]:
    arms: list[dict[str, Any]] = [
        {
            "key": "control",
            "label": "control (prod 0.85/1.25/252, trails off)",
            "role": "control",
            "n_pct": None,
            "k": None,
        }
    ]
    for k in (2.0, 2.5, 3.0):
        k_tag = f"{k:.1f}".replace(".", "p")
        arms.append(
            {
                "key": f"n10_k{k_tag}",
                "label": f"N=10% × k={k:.1f}×ATR14",
                "role": "candidate",
                "n_pct": 10.0,
                "k": float(k),
            }
        )
    # Cheap extras at k=2.5
    for n in (8, 12):
        arms.append(
            {
                "key": f"n{n}_k2p5",
                "label": f"N={n}% × k=2.5×ATR14",
                "role": "candidate",
                "n_pct": float(n),
                "k": 2.5,
            }
        )
    return arms


ARMS = _build_arms()

# Per-symbol Wilder ATR(14) cache (aligned to OHLC index)
_atr_cache: dict[str, pd.Series] = {}


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_N) -> np.ndarray:
    """True Wilder / RMA ATR: seed = SMA(TR, n); then (prev*(n-1)+TR)/n."""
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    tr = np.empty(len(close), dtype=float)
    tr[0] = high[0] - low[0]
    if len(close) > 1:
        prev = close[:-1]
        tr[1:] = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)),
        )
    atr = np.full(len(tr), np.nan, dtype=float)
    if len(tr) < n:
        return atr
    atr[n - 1] = float(np.mean(tr[:n]))
    for i in range(n, len(tr)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def atr_series_for(sym: str, ohlc: pd.DataFrame) -> pd.Series:
    if sym in _atr_cache:
        return _atr_cache[sym]
    atr = wilder_atr(
        ohlc["High"].to_numpy(dtype=float),
        ohlc["Low"].to_numpy(dtype=float),
        ohlc["Close"].to_numpy(dtype=float),
        ATR_N,
    )
    s = pd.Series(atr, index=ohlc.index)
    _atr_cache[sym] = s
    return s


def replay_chandelier(
    trade: dict[str, Any],
    ohlc: pd.DataFrame,
    atr_s: pd.Series,
    n_pct: float,
    k: float,
) -> dict[str, Any]:
    """Chandelier ATR trail overlay. See module docstring for freeze."""
    entry = float(trade["entry"])
    n_frac = float(n_pct) / 100.0
    opened = trade["opened"]
    closed = trade["closed"]
    try:
        window = ohlc.loc[opened:closed]
    except Exception:
        return {
            **trade,
            "chan_hit": False,
            "missing_bars": True,
            "armed": False,
            "peak_pct": 0.0,
            "chan_stop": None,
        }
    if window.empty:
        return {
            **trade,
            "chan_hit": False,
            "missing_bars": True,
            "armed": False,
            "peak_pct": 0.0,
            "chan_stop": None,
        }

    # Full-index positions for prior-bar ATR lookup
    all_dates = list(ohlc.index)
    date_to_i = {d: i for i, d in enumerate(all_dates)}
    atr_vals = atr_s.to_numpy(dtype=float)

    dates = list(window.index)
    peak_high = entry
    armed = False
    chan_stop: float | None = None

    def _exit_at(d: Any, exit_px: float, how: str) -> dict[str, Any]:
        pnl = (exit_px - entry) / entry * 100.0
        days = max((d - opened).days, 1)
        if abs(trade["pnl"]) > 1e-9:
            notional = trade["pnl_d"] / (trade["pnl"] / 100.0)
            pnl_d = notional * pnl / 100.0
        else:
            pnl_d = 0.0
        peak_pct = (peak_high - entry) / entry * 100.0 if entry else 0.0
        return {
            **trade,
            "pnl": pnl,
            "pnl_d": pnl_d,
            "days": float(days),
            "exit": "CHANDELIER_TRAIL",
            "exit_px": exit_px,
            "chan_hit": True,
            "missing_bars": False,
            "armed": True,
            "peak_pct": peak_pct,
            "chan_stop": chan_stop,
            "chan_how": how,
        }

    for i, d in enumerate(dates):
        o = float(window.loc[d, "Open"])
        h = float(window.loc[d, "High"])
        lo = float(window.loc[d, "Low"])

        # 1) Prior-bar armed: gap through chandelier stop at Open
        if i > 0 and armed and chan_stop is not None and o <= chan_stop:
            return _exit_at(d, o, "gap_open")

        # 2) Update peak from High; arm / ratchet with prior-bar ATR
        if h > peak_high:
            peak_high = h
        peak_frac = (peak_high - entry) / entry if entry else 0.0
        if peak_frac >= n_frac:
            gi = date_to_i.get(d)
            atr_prior = float("nan")
            if gi is not None and gi > 0:
                atr_prior = float(atr_vals[gi - 1])
            if math.isfinite(atr_prior) and atr_prior > 0:
                new_stop = peak_high - float(k) * atr_prior
                if not armed or chan_stop is None or new_stop > chan_stop:
                    chan_stop = new_stop
                armed = True

        # 3) Fill bar: arm only
        if i == 0:
            continue

        # 4) Intraday stop vs Low
        if armed and chan_stop is not None and lo <= chan_stop:
            return _exit_at(d, float(chan_stop), "low")

    peak_pct = (peak_high - entry) / entry * 100.0 if entry else 0.0
    return {
        **trade,
        "chan_hit": False,
        "missing_bars": False,
        "armed": armed,
        "peak_pct": peak_pct,
        "chan_stop": chan_stop,
    }


def apply_arm(
    ctrl: list[dict[str, Any]],
    n_pct: float | None,
    k: float | None,
) -> tuple[list[dict[str, Any]], int]:
    if n_pct is None or k is None:
        out = [
            {
                **t,
                "chan_hit": False,
                "missing_bars": False,
                "armed": False,
                "peak_pct": 0.0,
                "chan_stop": None,
            }
            for t in ctrl
        ]
        return out, 0
    cand: list[dict[str, Any]] = []
    missing = 0
    for t in ctrl:
        df = load_ohlc(t["sym"])
        if df is None:
            missing += 1
            cand.append(
                {
                    **t,
                    "chan_hit": False,
                    "missing_bars": True,
                    "armed": False,
                    "peak_pct": 0.0,
                    "chan_stop": None,
                }
            )
            continue
        atr_s = atr_series_for(t["sym"], df)
        cand.append(replay_chandelier(t, df, atr_s, n_pct, k))
    return cand, missing


def _enrich(m: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    cap = overlay_ann_ror_max_dd(trades, cash=RS_CASH, initial_account=INIT)
    m["max_dd"] = cap["max_dd"]
    m["calmar"] = cap.get("calmar", float("nan"))
    m["cap_days"] = float(cap["capital_days"] or 0.0)
    m["exp_d"] = (m["pnl_d"] / m["n"]) if m["n"] else float("nan")
    sh = cap.get("sharpe", float("nan"))
    m["sharpe"] = float(sh) if sh is not None and math.isfinite(float(sh)) else float("nan")
    m["sharpe_source"] = str(cap.get("sharpe_source") or "")
    m["chan_n"] = sum(1 for t in trades if t.get("chan_hit"))
    m["armed_n"] = sum(1 for t in trades if t.get("armed"))
    return m


def _fmt_sharpe(m: dict[str, Any]) -> str:
    s = m.get("sharpe", float("nan"))
    return "—" if not math.isfinite(float(s)) else f"{float(s):.2f}"


def verdict_is(
    ctrl_is: dict,
    cand_is: dict,
    ctrl_oos: dict,
    cand_oos: dict,
) -> tuple[str, str]:
    """KEEP/HOLD/DISMISS on IS quality; OOS soften → HOLD. Overlay N fixed."""
    d_avg = cand_is["avg_pnl"] - ctrl_is["avg_pnl"]
    d_wr = cand_is["wr"] - ctrl_is["wr"]
    d_pf = cand_is["pf"] - ctrl_is["pf"]
    d_wo = cand_is["wo_max"] - ctrl_is["wo_max"]
    is_better = (d_avg > 0.05 and d_wo > -0.05) or (d_avg > -0.05 and d_wr > 0.5 and d_pf > 0)
    is_worse = d_avg < -0.05 and d_wo < 0 and d_pf <= 0
    oos_soft = False
    oos_note = "OOS n/a"
    if ctrl_oos["n"] >= 20 and cand_oos["n"] >= 20:
        oos_soft = (cand_oos["avg_pnl"] < ctrl_oos["avg_pnl"] - 0.15) or (
            cand_oos["wr"] < ctrl_oos["wr"] - 1.0
        )
        oos_note = (
            f"OOS ΔAvgPnL {cand_oos['avg_pnl']-ctrl_oos['avg_pnl']:+.2f}pp, "
            f"ΔWR {cand_oos['wr']-ctrl_oos['wr']:+.1f}pp"
        )
        if oos_soft:
            oos_note += " — softened"
    if is_worse:
        return "DISMISS", f"IS ΔAvg={d_avg:+.2f}pp ΔWR={d_wr:+.1f}pp; {oos_note}"
    if is_better and oos_soft:
        return "HOLD", f"IS up (ΔAvg={d_avg:+.2f}pp) but {oos_note} (do not retune OOS)"
    if is_better and not oos_soft:
        return "KEEP", f"IS ΔAvg={d_avg:+.2f}pp ΔWR={d_wr:+.1f}pp ΔPF={d_pf:+.2f}; {oos_note} — research-only"
    return "HOLD", f"IS flat/mixed (ΔAvg={d_avg:+.2f}pp ΔWR={d_wr:+.1f}pp); {oos_note}"


def pack(ctrl: list[dict], trades: list[dict], arm: dict, missing: int) -> dict[str, Any]:
    is_c, oos_c = split_is_oos(ctrl)
    is_a, oos_a = split_is_oos(trades)
    cash = RS_CASH
    m_full = _enrich(book_stats(trades, cash), trades)
    m_is = _enrich(book_stats(is_a, cash), is_a)
    m_oos = _enrich(book_stats(oos_a, cash), oos_a)
    m_ctrl_full = _enrich(book_stats(ctrl, cash), ctrl)
    m_ctrl_is = _enrich(book_stats(is_c, cash), is_c)
    m_ctrl_oos = _enrich(book_stats(oos_c, cash), oos_c)
    if arm["role"] == "control":
        verd, note = "CONTROL", "prod freeze trails off; chandelier overlay off"
    else:
        verd, note = verdict_is(m_ctrl_is, m_is, m_ctrl_oos, m_oos)
    return {
        "arm": arm,
        "trades": trades,
        "missing": missing,
        "m_full": m_full,
        "m_is": m_is,
        "m_oos": m_oos,
        "m_ctrl_full": m_ctrl_full,
        "m_ctrl_is": m_ctrl_is,
        "m_ctrl_oos": m_ctrl_oos,
        "verd": verd,
        "note": note,
    }


def fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def fmt_pp(x: float) -> str:
    return f"{x:+.2f}pp"


def exit_mix(d: dict) -> str:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k}:{v}" for k, v in items[:8])


def write_closed_csv(trades: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "SYMBOL",
        "DATE_OPENED",
        "ENTRY_PRICE",
        "DATE_CLOSED",
        "DAYS_HELD",
        "EXIT_PRICE",
        "PNL_PCT",
        "PNL_DOLLARS",
        "EXIT_TYPE",
        "CHAN_HIT",
        "ARMED",
        "PEAK_PCT",
        "CHAN_STOP",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in trades:
            w.writerow(
                [
                    t.get("sym", ""),
                    t.get("opened", ""),
                    f"{float(t['entry']):.4f}" if t.get("entry") is not None else "",
                    t.get("closed", ""),
                    t.get("days", ""),
                    f"{float(t['exit_px']):.4f}" if t.get("exit_px") is not None else "",
                    f"{float(t['pnl']):.4f}",
                    f"{float(t['pnl_d']):.2f}",
                    t.get("exit", ""),
                    "1" if t.get("chan_hit") else "0",
                    "1" if t.get("armed") else "0",
                    f"{float(t.get('peak_pct') or 0):.4f}",
                    f"{float(t['chan_stop']):.4f}" if t.get("chan_stop") is not None else "",
                ]
            )


def load_overlay_closed(path: Path) -> list[dict[str, Any]]:
    """Reload stamp overlay Closed (includes CHAN_HIT / PNL $)."""
    from be_stop_replay_ab import _f, _parse_d, _row_get  # type: ignore

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
            closed = _parse_d(_row_get(raw, "DATE CLOSED", "DATE_CLOSED"))
            entry = _f(_row_get(raw, "ENTRY PRICE", "ENTRY_PRICE"))
            exit_px = _f(_row_get(raw, "EXIT PRICE", "EXIT_PRICE"))
            pnl = _f(_row_get(raw, "PNL %", "PNL_PCT"))
            days = _f(_row_get(raw, "DAYS HELD", "DAYS_HELD"))
            pnl_d = _f(_row_get(raw, "PNL $", "PNL_DOLLARS", "PNL_$"))
            if abs(pnl_d) < 1e-12 and abs(pnl) > 1e-9:
                pnl_d = RS_CASH * pnl / 100.0
            xt = _row_get(raw, "EXIT TYPE", "EXIT_TYPE")
            sym = _row_get(raw, "SYMBOL").upper()
            if not sym or opened is None or closed is None or entry <= 0:
                continue
            chan_hit = str(_row_get(raw, "CHAN_HIT") or "").strip() in {"1", "true", "True", "YES"}
            armed = str(_row_get(raw, "ARMED") or "").strip() in {"1", "true", "True", "YES"}
            peak = _f(_row_get(raw, "PEAK_PCT"))
            chan_stop_raw = _row_get(raw, "CHAN_STOP")
            chan_stop = _f(chan_stop_raw) if str(chan_stop_raw or "").strip() else None
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "exit_px": exit_px,
                    "pnl": pnl,
                    "days": days if days > 0 else max((closed - opened).days, 1),
                    "pnl_d": pnl_d,
                    "exit": xt or "",
                    "chan_hit": chan_hit,
                    "armed": armed,
                    "peak_pct": peak,
                    "chan_stop": chan_stop if chan_stop and chan_stop > 0 else None,
                    "missing_bars": False,
                }
            )
    return rows


def metric_table(results: list[dict], book_key: str, caption: str) -> str:
    headers = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Role", "text"),
            ("N", "num"),
            ("Win%", "num"),
            ("Avg PnL%", "num"),
            ("AVG_PNL_PCT_WO_MAX", "num"),
            ("Avg win%", "num"),
            ("Avg loss%", "num"),
            ("PF", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
            ("Expect $", "num"),
            ("Avg days", "num"),
            ("Capital days", "num"),
            ("Chan hits", "num"),
            ("Armed", "num"),
            ("Δ Avg PnL%", "num"),
            ("Δ Win%", "num"),
            ("Δ PF", "num"),
            ("Exit mix", "text"),
            ("Verdict", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl_m = results[0][book_key]
    parts = []
    for r in results:
        m = r[book_key]
        d_avg = m["avg_pnl"] - ctrl_m["avg_pnl"]
        d_wr = m["wr"] - ctrl_m["wr"]
        d_pf = m["pf"] - ctrl_m["pf"]
        cells = [
            html_mod.escape(r["arm"]["label"]),
            r["arm"]["role"],
            str(m["n"]),
            fmt_pct(m["wr"]),
            fmt_pct(m["avg_pnl"]),
            fmt_pct(m["wo_max"]),
            fmt_pct(m["avg_win"]),
            fmt_pct(m["avg_loss"]),
            f"{m['pf']:.2f}",
            fmt_pct(m["ann_ror"]),
            fmt_pct(m["max_dd"]) if math.isfinite(m.get("max_dd", float("nan"))) else "—",
            f"{m['calmar']:.2f}" if math.isfinite(m.get("calmar", float("nan"))) else "—",
            _fmt_sharpe(m),
            format_money(m["exp_d"]) if math.isfinite(m.get("exp_d", float("nan"))) else "—",
            f"{m['avg_days']:.1f}",
            f"{m.get('cap_days', 0):.0f}",
            str(m.get("chan_n", 0)),
            str(m.get("armed_n", 0)),
            "—" if r["arm"]["role"] == "control" else fmt_pp(d_avg),
            "—" if r["arm"]["role"] == "control" else fmt_pp(d_wr),
            "—" if r["arm"]["role"] == "control" else f"{d_pf:+.2f}",
            html_mod.escape(exit_mix(m["exits"])),
            html_mod.escape(r["verd"] if book_key in ("m_full", "m_is") else ""),
        ]
        parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return (
        f'<table class="sortable"><caption>{html_mod.escape(caption)}</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(parts)}</tbody></table>"
    )


def isoos_table(results: list[dict]) -> str:
    headers = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Split", "text"),
            ("N", "num"),
            ("Win%", "num"),
            ("Avg PnL%", "num"),
            ("WO_MAX", "num"),
            ("PF", "num"),
            ("Chan hits", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
            ("Avg days", "num"),
            ("Δ Avg PnL% vs ctrl split", "num"),
            ("Δ Win% vs ctrl split", "num"),
            ("Verdict (IS)", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl = results[0]
    parts = []
    for r in results:
        for split, mk, ck in (("IS", "m_is", "m_ctrl_is"), ("OOS", "m_oos", "m_ctrl_oos")):
            m = r[mk]
            c = r[ck] if r["arm"]["role"] != "control" else ctrl[mk]
            d_avg = m["avg_pnl"] - c["avg_pnl"]
            d_wr = m["wr"] - c["wr"]
            cells = [
                html_mod.escape(r["arm"]["label"]),
                split,
                str(m["n"]),
                fmt_pct(m["wr"]),
                fmt_pct(m["avg_pnl"]),
                fmt_pct(m["wo_max"]),
                f"{m['pf']:.2f}",
                str(m.get("chan_n", 0)),
                fmt_pct(m["ann_ror"]),
                fmt_pct(m["max_dd"]) if math.isfinite(m.get("max_dd", float("nan"))) else "—",
                f"{m['calmar']:.2f}" if math.isfinite(m.get("calmar", float("nan"))) else "—",
                _fmt_sharpe(m),
                f"{m['avg_days']:.1f}",
                "—" if r["arm"]["role"] == "control" else fmt_pp(d_avg),
                "—" if r["arm"]["role"] == "control" else fmt_pp(d_wr),
                html_mod.escape(r["verd"] if split == "IS" else ""),
            ]
            parts.append("<tr>" + "".join(f"<td>{x}</td>" for x in cells) + "</tr>")
    return (
        '<table class="sortable"><caption>IS = entry_date &lt; 2024-01-01; OOS report-only. '
        "Click column headers to sort. Sharpe: EquityCurve if present else Closed exit-date equity "
        "(rf=0, annualized by exit-date obs/year — not √252 daily MTM).</caption>"
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(parts)}</tbody></table>"
    )


def _pick_best(results: list[dict]) -> dict[str, Any] | None:
    """Best candidate by IS quality score (Avg PnL primary, then WR, PF)."""
    cands = [r for r in results if r["arm"]["role"] == "candidate"]
    if not cands:
        return None
    return max(
        cands,
        key=lambda r: (r["m_is"]["avg_pnl"], r["m_is"]["wr"], r["m_is"]["pf"], r["m_is"]["wo_max"]),
    )


def write_html(results: list[dict], closed: Path) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    best = _pick_best(results)
    verd_bits = " · ".join(
        f"{r['arm']['key']}={r['verd']}" for r in results if r["arm"]["role"] != "control"
    )
    best_line = ""
    if best:
        bi, bc = best["m_is"], results[0]["m_is"]
        best_line = (
            f"<strong>Best IS arm:</strong> {html_mod.escape(best['arm']['label'])} → "
            f"<strong>{html_mod.escape(best['verd'])}</strong> — "
            f"IS WR {bi['wr']:.1f}% / Avg {bi['avg_pnl']:.2f}% / PF {bi['pf']:.2f} "
            f"(ctrl IS {bc['wr']:.1f}% / {bc['avg_pnl']:.2f}% / {bc['pf']:.2f}); "
            f"{html_mod.escape(best['note'])}"
        )
    rel = closed.as_posix()
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>RS chandelier ATR trail A/B — {STAMP}</title>
<style>
:root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4; --fill:#f0eee6; --accent:#2a4a5c; }}
body {{ margin:0; font-family:"Segoe UI",Georgia,serif; font-size:15px; color:var(--ink); background:var(--bg); }}
.wrap {{ max-width:1400px; margin:0 auto; padding:32px 20px 64px; }}
h1 {{ font-size:1.55rem; margin:0 0 8px; }}
h2 {{ font-size:1.12rem; margin:28px 0 10px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.muted {{ color:var(--muted); font-size:0.9rem; }}
.callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:14px 0; }}
.table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
th, td {{ border:1px solid var(--line); padding:5px 7px; text-align:left; vertical-align:top; }}
thead th {{ background:var(--fill); }}
{SORTABLE_TH_CSS}
caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
code {{ background:var(--fill); padding:0.08em 0.3em; font-size:0.86em; }}
</style></head><body>
<div class="wrap">
<p class="muted">Relative Strength (RS) · EXIT overlay · FIT universe (gold freeze 65) · research candidate · not gold · not DailyRun</p>
<h1>RS chandelier ATR trail — N% arm × k×ATR(14 Wilder)</h1>
<p><strong>EXIT</strong> overlay only (same entries as control). When peak mark-to-market gain
vs entry reaches <strong>N%</strong>, raise stop to
<code>highest_high_since_entry − k × ATR(14 Wilder)</code> using <strong>prior-bar ATR</strong>
(ratchet upward only). Target (entry×1.25), stop (entry×0.85), time stop (252 bars), and other
control exits unchanged unless chandelier fires first.</p>
<div class="callout">
<strong>Stop formula:</strong>
<code>peak_pct = (max_High − entry) / entry</code>; once
<code>peak_pct ≥ N/100</code>,
<code>chan_stop = HH_since_entry − k × ATR14_Wilder(prior)</code> with
<code>k ∈ {{2.0, 2.5, 3.0}}</code> (primary grid at N=10; extras N=8/12 at k=2.5); never loosen.<br/>
<strong>Grid verdicts:</strong> {html_mod.escape(verd_bits)}<br/>
{best_line}
</div>

<h2>IS book (decision split)</h2>
<p class="muted">KEEP/HOLD/DISMISS judged on IS quality. Click column headers to sort.
Sharpe via <code>compare_format</code>: prefer host EquityCurve; else Closed exit-date equity
(rf=0, obs/year annualization — understates intratrade MTM vol).</p>
<div class="table-wrap">{metric_table(results, "m_is", "IS · entry_date &lt; 2024-01-01 · click headers to sort")}</div>

<h2>Full book vs control</h2>
<div class="table-wrap">{metric_table(results, "m_full", "Full book · click headers to sort. Overlay keeps N fixed.")}</div>

<h2>IS / OOS detail</h2>
<div class="table-wrap">{isoos_table(results)}</div>

<h2>Freeze / method</h2>
<ul>
<li><strong>Label:</strong> EXIT overlay (not entry).</li>
<li><strong>Universe:</strong> RS FIT expand freeze (65 names on Closed; live
  <code>RS_universe.csv</code> is 64 after ATEYY remove 2026-08-10).</li>
<li><strong>Control Closed:</strong> <code>{html_mod.escape(rel)}</code>
  — gold <code>rs_baseline_260807141317</code> (matches prod
  <code>run_rs.bat</code>: stop 0.85 / target 1.25 / time 252 / cd 60 /
  <code>rs_spy_int_tc_not_weak=true</code>, trails off). Same control as
  <code>rs_lockin_trail_ab_20260904</code>.</li>
<li><strong>Knob:</strong> chandelier trail N% arm × k×ATR(14 Wilder). Engine
  <code>trailing_stop_increment=0</code> / <code>chandelier_enabled=false</code> in production.</li>
<li><strong>ATR:</strong> true Wilder RMA of True Range (seed = SMA of first 14 TRs);
  stop uses <strong>prior completed bar</strong> ATR (no same-bar look-ahead).</li>
<li><strong>Convention:</strong> fill bar arms/ratchets only; subsequent Open gap or Low ≤ chan_stop →
  <code>CHANDELIER_TRAIL</code>; never past original close; missing OHLC → control exit.</li>
<li>IS = entry_date &lt; 2024-01-01; OOS report-only. Do not retune on OOS.</li>
<li>Ann ROR / Max DD / Calmar: Closed overlay at $16,216 cash / $500k initial.</li>
<li><strong>Sharpe:</strong> prefer daily EquityCurve (rf=0, √252). Overlay fallback =
  same exit-date equity path as Max DD, then rf=0 returns annualized by
  <code>sqrt(n_exit_obs / calendar_years)</code>
  (<code>compare_format.resolve_overlay_sharpe</code> /
  <code>sharpe_from_closed_pnl_by_date</code>). Descriptive only; not gold.</li>
<li>Not DailyRun. Research-only ≠ gold. Sibling of RL chandelier stamp (separate tool/stamp).</li>
</ul>
<p class="muted">Generated {STAMP} by <code>tools/rs_chandelier_trail_ab.py</code>.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(results: list[dict], closed: Path) -> Path:
    best = _pick_best(results)
    lines = [
        f"# BASELINE — `rs_chandelier_trail_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. Not gold. Not DailyRun. **EXIT** overlay.",
        "",
        "## Hypothesis",
        "",
        "If we arm a chandelier stop (HH since entry − k×ATR14 Wilder) once peak ≥ N%,",
        "volatility-scaled giveback after strong MFE becomes a trail exit without changing RS entries.",
        "",
        "## Freeze (control = prod 2026-09-04)",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | RS FIT expand (gold Closed 65; live CSV 64 post-ATEYY) |",
        f"| Control Closed | `{closed.as_posix()}` (`rs_baseline_260807141317`) |",
        "| Prod source | `run_rs.bat` / `rocket_tbn.py --relative-strength` |",
        "| `stop_pct` | 0.85 (multiplier) |",
        "| `target_pct` | 1.25 |",
        "| `time_stop_days` | 252 |",
        "| `symbol_reentry_cooldown_days` | 60 |",
        "| `rs_spy_int_tc_not_weak` | true |",
        "| `rs_require_tc_strong` | true |",
        "| Engine trails | off (`trailing_stop_increment=0`, `chandelier_enabled=false`) |",
        "| Knob | EXIT chandelier: N% arm × k×ATR(14 Wilder, prior bar) |",
        "| Arms | control + N=10×k∈{2.0,2.5,3.0} + N∈{8,12} at k=2.5 |",
        "| Split | IS entry_date < 2024-01-01; OOS report-only |",
        "| Method | Closed + local OHLC replay; N fixed |",
        "| Sibling | Parallel to RL chandelier; same control as `rs_lockin_trail_ab_20260904` |",
        "| Sharpe | EquityCurve if present; else Closed exit-date equity "
        "(rf=0, obs/year via `compare_format.sharpe_from_closed_pnl_by_date`) |",
        "",
        "## Exact stop formula (frozen)",
        "",
        "```",
        "peak_pct = (max_High_since_entry - entry) / entry",
        "if peak_pct >= N/100:                              # primary N=10; extras 8,12",
        "    atr = Wilder_ATR(14)[prior bar]                # RMA of TR; no same-bar ATR",
        "    chan_stop = highest_high_since_entry - k * atr # k in {2.0, 2.5, 3.0}",
        "    # ratchet: chan_stop := max(prior_chan_stop, new); never loosen",
        "```",
        "",
        "- Activates only after peak ≥ N%; then tracks rising HH − k×ATR.",
        "- Fill bar: update peak/arm only; do not stop. Gap Open ≤ stop → fill @Open;",
        "  else Low ≤ stop → fill @chan_stop. Exit type `CHANDELIER_TRAIL`.",
        "- Never extends past original Closed exit. Missing OHLC → control exit.",
        "",
        "Do **not** retune on OOS. Do **not** overwrite `RS_universe.csv`. Do **not** wire DailyRun.",
        "",
        "## Verdicts (IS quality)",
        "",
    ]
    for r in results:
        if r["arm"]["role"] == "control":
            continue
        mi = r["m_is"]
        lines.append(
            f"- **{r['arm']['label']}** → **{r['verd']}** "
            f"(IS N={mi['n']} WR={mi['wr']:.1f}% Avg={mi['avg_pnl']:.2f}% PF={mi['pf']:.2f} "
            f"chan={mi.get('chan_n', 0)}) — {r['note']}"
        )
    if best:
        lines.extend(
            [
                "",
                "## Best arm (IS)",
                "",
                f"**{best['arm']['label']}** → **{best['verd']}** — {best['note']}",
            ]
        )
    path = OUT_DIR / "BASELINE.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_summary(results: list[dict]) -> Path:
    best = _pick_best(results)
    ctrl_is = results[0]["m_is"]
    lines = [
        f"# SUMMARY — `rs_chandelier_trail_ab_{STAMP}`",
        "",
        "EXIT overlay: chandelier N% × k×ATR(14 Wilder) on RS gold Closed "
        "`rs_baseline_260807141317`. Research only. Sibling of RL chandelier.",
        "",
        f"**Control IS:** WR={ctrl_is['wr']:.1f}% Avg={ctrl_is['avg_pnl']:.2f}% "
        f"PF={ctrl_is['pf']:.2f} N={ctrl_is['n']}",
        "",
    ]
    if best:
        bi = best["m_is"]
        lines.append(
            f"**Best IS:** `{best['arm']['key']}` → **{best['verd']}** — "
            f"IS WR={bi['wr']:.1f}% Avg={bi['avg_pnl']:.2f}% PF={bi['pf']:.2f} "
            f"(ΔAvg={bi['avg_pnl']-ctrl_is['avg_pnl']:+.2f}pp ΔWR={bi['wr']-ctrl_is['wr']:+.1f}pp) "
            f"— {best['note']}"
        )
        lines.append("")
    lines.extend(
        [
            "| Arm | IS WR / Avg / PF / chan | OOS WR / Avg / PF | Verdict |",
            "|-----|-------------------------|-------------------|---------|",
        ]
    )
    for r in results:
        m, o = r["m_is"], r["m_oos"]
        lines.append(
            f"| {r['arm']['label']} | {m['wr']:.1f}% / {m['avg_pnl']:.2f}% / {m['pf']:.2f} / "
            f"C={m.get('chan_n', 0)} | {o['wr']:.1f}% / {o['avg_pnl']:.2f}% / {o['pf']:.2f} | {r['verd']} |"
        )
    lines.extend(["", "## Notes", ""])
    for r in results:
        if r["arm"]["role"] == "control":
            continue
        lines.append(f"- **{r['arm']['key']}**: {r['verd']} — {r['note']}")
    path = OUT_DIR / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    global OUT_DIR, CLOSED
    parser = argparse.ArgumentParser()
    parser.add_argument("--closed", type=Path, default=DEFAULT_CLOSED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--reuse-closed",
        action="store_true",
        help="Rebuild metrics/HTML from OUT/closed/RS_Closed_overlay_*.csv (skip OHLC replay)",
    )
    args = parser.parse_args()
    CLOSED = args.closed
    OUT_DIR = args.out
    if not CLOSED.is_file() and not args.reuse_closed:
        print(f"[RS-CHAN] missing Closed {CLOSED}", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    closed_dir = OUT_DIR / "closed"
    closed_dir.mkdir(parents=True, exist_ok=True)

    if args.reuse_closed:
        print(f"[RS-CHAN] reuse-closed from {closed_dir} ...", flush=True)
        ctrl_path = closed_dir / "RS_Closed_overlay_control.csv"
        if not ctrl_path.is_file():
            print(f"[RS-CHAN] missing {ctrl_path}", flush=True)
            return 1
        ctrl = load_overlay_closed(ctrl_path)
        print(f"[RS-CHAN] N={len(ctrl)} arms={len(ARMS)} (reuse)", flush=True)
        results: list[dict[str, Any]] = []
        for arm in ARMS:
            p = closed_dir / f"RS_Closed_overlay_{arm['key']}.csv"
            if not p.is_file():
                print(f"[RS-CHAN] missing {p}", flush=True)
                return 1
            trades = load_overlay_closed(p)
            r = pack(ctrl, trades, arm, missing=0)
            results.append(r)
            print(
                f"  {arm['key']}: chan={r['m_full'].get('chan_n', 0)} "
                f"IS WR={r['m_is']['wr']:.1f} Avg={r['m_is']['avg_pnl']:.2f} "
                f"Sharpe={_fmt_sharpe(r['m_is'])} -> {r['verd']}",
                flush=True,
            )
    else:
        print(f"[RS-CHAN] loading {CLOSED} ...", flush=True)
        ctrl = load_closed(CLOSED, "tbn")
        print(f"[RS-CHAN] N={len(ctrl)} arms={len(ARMS)}", flush=True)

        results = []
        for arm in ARMS:
            trades, missing = apply_arm(ctrl, arm["n_pct"], arm["k"])
            r = pack(ctrl, trades, arm, missing)
            results.append(r)
            write_closed_csv(trades, closed_dir / f"RS_Closed_overlay_{arm['key']}.csv")
            print(
                f"  {arm['key']}: chan={r['m_full'].get('chan_n', 0)} "
                f"armed={r['m_full'].get('armed_n', 0)} "
                f"IS WR={r['m_is']['wr']:.1f} Avg={r['m_is']['avg_pnl']:.2f} "
                f"PF={r['m_is']['pf']:.2f} Sharpe={_fmt_sharpe(r['m_is'])} "
                f"missing={missing} -> {r['verd']}",
                flush=True,
            )

    html_path = write_html(results, CLOSED if CLOSED.is_file() else closed_dir / "RS_Closed_overlay_control.csv")
    write_baseline(results, CLOSED if CLOSED.is_file() else closed_dir / "RS_Closed_overlay_control.csv")
    write_summary(results)
    print(f"[RS-CHAN] wrote {html_path}", flush=True)

    best = _pick_best(results)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        msg = "chandelier ATR trail grid done"
        if best:
            msg = f"best IS {best['arm']['key']} -> {best['verd']}"
        subprocess.run(
            [
                sys.executable,
                str(ntfy),
                "--path",
                str(html_path),
                "-t",
                "RS chandelier trail AB",
                "-m",
                msg,
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
