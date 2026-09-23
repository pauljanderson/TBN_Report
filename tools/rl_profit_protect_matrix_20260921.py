#!/usr/bin/env python3
"""RL Exit Research — Profit Protection Matrix (Control + A–L).

Research-only EXIT overlay. Entries frozen from no-SMA +20%/60d Control Closed.
Fib trails are not engine knobs; replay OHLC from entry (may extend past Control exit).

Control: pct20_d60 from rl_no_sma_target_exit_ab_20260905
  (rl_sma_target_off=1, rl_exit_percent=0.20, rl_exit_days=60, th113_vol entry freeze)

IS = entry < 2024-01-01; OOS report-only; no OOS retune / no auto-pick max PnL.

Usage:
  python tools/rl_profit_protect_matrix_20260921.py
  python tools/rl_profit_protect_matrix_20260921.py --summarize-only
  python tools/rl_profit_protect_matrix_20260921.py --arms B
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))

from be_stop_replay_ab import (  # noqa: E402
    RL_CASH,
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

STAMP = "20260921"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_profit_protect_matrix_{STAMP}"
DEFAULT_CLOSED = (
    DRIVE
    / "paul_experiments"
    / "rl_no_sma_target_exit_ab_20260905"
    / "closed"
    / "pct20_d60_RL_Closed_260905205015.csv"
)
IS_CUT = date(2024, 1, 1)
INIT = DEFAULT_INITIAL_ACCOUNT
TERMINAL_DAYS = 60
# If first OHLC bar after entry is more than this many calendar days later, treat as
# missing history (keep Control exit). Guards truncated stubs like EA.csv (6 bars).
MAX_ENTRY_GAP_DAYS = 14


def _as_date(d: Any) -> date:
    # datetime is a date subclass — normalize via Y/M/D
    if isinstance(d, date):
        return date(d.year, d.month, d.day)
    if hasattr(d, "date") and callable(getattr(d, "date")):
        try:
            out = d.date()
            if isinstance(out, date):
                return date(out.year, out.month, out.day)
        except Exception:
            pass
    return date.fromisoformat(str(d)[:10])

REQUEST_PROMPT = """\
RL Exit Research — Profit Protection Matrix
Purpose: Test profit-protection architectures after an RL trade has established a meaningful gain.
This is research, not parameter optimization. Keep all entry rules frozen.
Control: Current no-SMA-target +20% milestone / 60 trading-day exit logic.
Variants A–L: activation +20%/+25%, partial 50%/none, protection fixed +10% / 50% Fib / 61.8% Fib.
60-day terminal exit from activation for ALL variants. Fib from entry → highest HIGH; ratchet up only.
Run IS/OOS/FULL for Control and A–L; retain trade-level output. Do not auto-select highest-profit.
"""

LAYMAN_TRANSLATION = """\
Once an RL trade is meaningfully green (+20% or +25%), we test different ways to protect that gain
before the usual 60-trading-day clock forces a full exit: cash out half at the milestone or keep
the whole position; then either lock a hard floor at +10% from entry, or trail a Fibonacci
retracement from the best high seen so far (50% or 61.8%). Same entries as today’s no-envelope
+20%/60-day control — only the profit-protection sell rules change. We compare on in-sample
quality; out-of-sample is validation only, not a knob to retune.
"""


@dataclass(frozen=True)
class ArmSpec:
    key: str
    label: str
    role: str  # control | candidate
    activation: Optional[float]  # 0.20 / 0.25; None = control passthrough
    partial: bool
    protect: Optional[str]  # fixed10 | fib50 | fib618


def _build_arms() -> list[ArmSpec]:
    arms: list[ArmSpec] = [
        ArmSpec("control", "Control: no-SMA +20% then 60d (no mid-protect)", "control", None, False, None),
    ]
    # A–L matrix
    matrix = [
        ("A", 0.20, True, "fixed10", "+20% · sell 50% · fixed stop +10%"),
        ("B", 0.25, True, "fixed10", "+25% · sell 50% · fixed stop +10%"),
        ("C", 0.20, True, "fib50", "+20% · sell 50% · 50% Fib trail"),
        ("D", 0.20, True, "fib618", "+20% · sell 50% · 61.8% Fib trail"),
        ("E", 0.25, True, "fib50", "+25% · sell 50% · 50% Fib trail"),
        ("F", 0.25, True, "fib618", "+25% · sell 50% · 61.8% Fib trail"),
        ("G", 0.20, False, "fib50", "+20% · no partial · 50% Fib trail"),
        ("H", 0.20, False, "fib618", "+20% · no partial · 61.8% Fib trail"),
        ("I", 0.25, False, "fib50", "+25% · no partial · 50% Fib trail"),
        ("J", 0.25, False, "fib618", "+25% · no partial · 61.8% Fib trail"),
        ("K", 0.20, False, "fixed10", "+20% · no partial · fixed stop +10%"),
        ("L", 0.25, False, "fixed10", "+25% · no partial · fixed stop +10%"),
    ]
    for key, act, partial, protect, label in matrix:
        arms.append(ArmSpec(key, label, "candidate", act, partial, protect))
    return arms


ARMS = _build_arms()


def _fib_retrace(protect: str) -> float:
    if protect == "fib50":
        return 0.50
    if protect == "fib618":
        return 0.618
    raise ValueError(protect)


def _fib_stop(entry: float, peak_high: float, fib: float) -> float:
    """stop = peak − fib × (peak − entry); ratchet upward only at caller."""
    advance = peak_high - entry
    if advance <= 0:
        return entry
    return peak_high - fib * advance


def _notional(trade: dict[str, Any]) -> float:
    pnl = float(trade.get("pnl") or 0.0)
    pnl_d = float(trade.get("pnl_d") or 0.0)
    if abs(pnl) > 1e-9:
        return abs(pnl_d / (pnl / 100.0))
    return float(RL_CASH)


def replay_protect(
    trade: dict[str, Any],
    ohlc: Any,
    activation: float,
    partial: bool,
    protect: str,
) -> dict[str, Any]:
    """Replay profit-protection exit from entry; may extend past Control close."""
    entry = float(trade["entry"])
    stop0 = float(trade["stop"])
    opened = trade["opened"]
    notional = _notional(trade)

    try:
        # Extend past control exit — need path until protect/terminal/stop or data end.
        window = ohlc.loc[opened:]
    except Exception:
        return {**trade, "missing_bars": True, "activated": False, "protect_hit": False}

    if window.empty:
        return {**trade, "missing_bars": True, "activated": False, "protect_hit": False}

    dates = list(window.index)
    first = _as_date(dates[0])
    opened_d = _as_date(opened)
    if (first - opened_d).days > MAX_ENTRY_GAP_DAYS:
        # Truncated / late-start series — do not invent a path from stub bars.
        return {**trade, "missing_bars": True, "activated": False, "protect_hit": False}

    peak_high = entry
    activated = False
    time_counter = 0
    protect_stop: Optional[float] = None
    rem_frac = 1.0
    partial_pnl_frac = 0.0  # contribution to total return (fraction of entry)
    partial_px: Optional[float] = None
    partial_date: Optional[Any] = None
    act_date: Optional[Any] = None
    fib = _fib_retrace(protect) if protect.startswith("fib") else None

    def _finish(
        d: Any,
        exit_px: float,
        how: str,
        *,
        rem: float,
    ) -> dict[str, Any]:
        rem_ret = (exit_px - entry) / entry if entry else 0.0
        total_ret = partial_pnl_frac + rem * rem_ret
        pnl = total_ret * 100.0
        # Weighted avg exit for remaining + partial legs
        if partial_px is not None and rem < 0.999:
            sold = 1.0 - rem
            avg_exit = sold * float(partial_px) + rem * exit_px
        else:
            avg_exit = exit_px
        opened_d = _as_date(opened)
        closed_d = _as_date(d)
        days = max((closed_d - opened_d).days, 1)
        peak_pct = (peak_high - entry) / entry * 100.0 if entry else 0.0
        rem_pnl_pct = rem_ret * 100.0
        part_pnl_pct = (
            ((float(partial_px) - entry) / entry * 100.0)
            if partial_px is not None and entry
            else None
        )
        act_d = _as_date(act_date) if act_date is not None else None
        days_to_act = (act_d - opened_d).days if act_d is not None else None
        act_to_close = (closed_d - act_d).days if act_d is not None else None
        protect_hit = how.startswith("PROTECT") or how.startswith("FIXED") or how.startswith("FIB")
        act_to_protect = (closed_d - act_d).days if (act_d is not None and protect_hit) else None
        giveback = peak_pct - rem_pnl_pct
        return {
            **trade,
            "pnl": pnl,
            "pnl_d": notional * total_ret,
            "days": float(days),
            "exit": how,
            "exit_px": float(avg_exit),
            "final_exit_px": float(exit_px),
            "closed": d,
            "missing_bars": False,
            "activated": activated,
            "activation_date": act_date,
            "partial": bool(partial and partial_px is not None),
            "partial_px": partial_px,
            "partial_date": partial_date,
            "partial_pnl_pct": part_pnl_pct,
            "remainder_pnl_pct": rem_pnl_pct,
            "total_pnl_pct": pnl,
            "days_to_activation": days_to_act,
            "activation_to_close": act_to_close,
            "activation_to_protect_hit": act_to_protect,
            "giveback_from_peak": giveback,
            "protect_hit": protect_hit,
            "protect_stop": protect_stop,
            "peak_pct": peak_pct,
            "peak_high": peak_high,
            "time_counter": time_counter,
            "rem_frac": rem,
        }

    for i, d in enumerate(dates):
        o = float(window.loc[d, "Open"])
        h = float(window.loc[d, "High"])
        lo = float(window.loc[d, "Low"])

        # Effective stop: protective after activation, else original stop.
        eff_stop = protect_stop if (activated and protect_stop is not None) else stop0

        # 1) Prior-bar stop: gap through at Open (skip entry bar)
        if i > 0 and o <= eff_stop:
            if activated and protect_stop is not None and o <= protect_stop:
                tag = "FIXED10_GAP" if protect == "fixed10" else "FIB_GAP"
                return _finish(d, o, tag, rem=rem_frac)
            return _finish(d, o, "STOP_GAP", rem=rem_frac)

        # 2) Update peak from High
        if h > peak_high:
            peak_high = h

        # 3) Activation on High
        if not activated and h >= entry * (1.0 + activation):
            activated = True
            act_date = d
            time_counter = 0
            # Partial @ High of activation bar (engine partial fill convention)
            if partial and rem_frac > 0.5:
                sell = 0.5
                rem_frac -= sell
                partial_px = h
                partial_date = d
                partial_pnl_frac += sell * ((h - entry) / entry)
            # Arm protection
            if protect == "fixed10":
                protect_stop = entry * 1.10
            else:
                assert fib is not None
                protect_stop = _fib_stop(entry, peak_high, fib)

        # 4) After activation: ratchet fib; increment terminal clock
        if activated:
            time_counter += 1
            if protect != "fixed10" and fib is not None:
                new_stop = _fib_stop(entry, peak_high, fib)
                if protect_stop is None or new_stop > protect_stop:
                    protect_stop = new_stop

        # 5) Entry bar: arm only; no stop exit on fill session
        if i == 0:
            continue

        # 6) Intraday stop vs Low
        if activated and protect_stop is not None and lo <= protect_stop:
            tag = "FIXED10" if protect == "fixed10" else ("FIB50" if protect == "fib50" else "FIB618")
            return _finish(d, float(protect_stop), tag, rem=rem_frac)
        if (not activated) and lo <= stop0:
            return _finish(d, float(stop0), "STOP_LOSS", rem=rem_frac)

        # 7) 60 trading-day terminal from activation (fill @ Open next convention:
        #    engine exits same bar when counter >= days after increment; fill @ Open.
        #    Mirror: after increment, if >= 60, exit remaining @ Open of this bar.)
        if activated and time_counter >= TERMINAL_DAYS:
            return _finish(d, o, "RL_EXIT_DAYS", rem=rem_frac)

    # Fell off end of data — force close at last Close
    last = dates[-1]
    last_px = float(window.loc[last, "Close"])
    return _finish(last, last_px, "EOD_DATA", rem=rem_frac)


def apply_arm(ctrl: list[dict[str, Any]], arm: ArmSpec) -> tuple[list[dict[str, Any]], int]:
    if arm.role == "control":
        out = []
        for t in ctrl:
            out.append(
                {
                    **t,
                    "missing_bars": False,
                    "activated": str(t.get("exit", "")).upper() in {"RL_EXIT_DAYS"}
                    or float(t.get("pnl") or 0) >= 20.0,
                    "protect_hit": False,
                    "partial": False,
                    "peak_pct": 0.0,
                    "protect_stop": None,
                    "final_exit_px": t.get("exit_px"),
                }
            )
        return out, 0

    assert arm.activation is not None and arm.protect is not None
    cand: list[dict[str, Any]] = []
    missing = 0
    for t in ctrl:
        df = load_ohlc(t["sym"])
        if df is None:
            missing += 1
            cand.append({**t, "missing_bars": True, "activated": False, "protect_hit": False})
            continue
        cand.append(
            replay_protect(
                t,
                df,
                activation=float(arm.activation),
                partial=bool(arm.partial),
                protect=str(arm.protect),
            )
        )
        if cand[-1].get("missing_bars"):
            missing += 1
    return cand, missing


def _enrich(m: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    cap = overlay_ann_ror_max_dd(trades, cash=RL_CASH, initial_account=INIT)
    m["max_dd"] = cap["max_dd"]
    m["calmar"] = cap.get("calmar", float("nan"))
    m["cap_days"] = float(cap["capital_days"] or 0.0)
    m["ann_ror"] = cap.get("ann_ror", m.get("ann_ror", float("nan")))
    m["exp_d"] = (m["pnl_d"] / m["n"]) if m["n"] else float("nan")
    sh = cap.get("sharpe", float("nan"))
    m["sharpe"] = float(sh) if sh is not None and math.isfinite(float(sh)) else float("nan")
    m["activated_n"] = sum(1 for t in trades if t.get("activated"))
    m["protect_n"] = sum(1 for t in trades if t.get("protect_hit"))
    m["partial_n"] = sum(1 for t in trades if t.get("partial"))
    m["exit_mix"] = dict(Counter(str(t.get("exit") or "UNK") for t in trades))
    return m


def _struct_note(arm: ArmSpec, m_is: dict, m_ctrl_is: dict) -> str:
    """Structural behavior note — not auto KEEP on max PnL."""
    if arm.role == "control":
        return "Frozen control book (no mid-protect after +20%)."
    d_avg = m_is["avg_pnl"] - m_ctrl_is["avg_pnl"]
    d_wr = m_is["wr"] - m_ctrl_is["wr"]
    d_pf = m_is["pf"] - m_ctrl_is["pf"]
    d_dd = float(m_is.get("max_dd") or 0) - float(m_ctrl_is.get("max_dd") or 0)
    d_days = m_is["avg_days"] - m_ctrl_is["avg_days"]
    return (
        f"IS ΔAvg={d_avg:+.2f}pp ΔWR={d_wr:+.1f}pp ΔPF={d_pf:+.2f} "
        f"ΔMaxDD={d_dd:+.2f}pp ΔAvgDays={d_days:+.1f} · "
        f"activated={m_is.get('activated_n', 0)} protect_exits={m_is.get('protect_n', 0)} "
        f"partials={m_is.get('partial_n', 0)} — research structural read only"
    )


def pack(ctrl: list[dict], trades: list[dict], arm: ArmSpec, missing: int) -> dict[str, Any]:
    is_c, oos_c = split_is_oos(ctrl)
    is_a, oos_a = split_is_oos(trades)
    cash = RL_CASH
    m_full = _enrich(book_stats(trades, cash), trades)
    m_is = _enrich(book_stats(is_a, cash), is_a)
    m_oos = _enrich(book_stats(oos_a, cash), oos_a)
    m_ctrl_is = _enrich(book_stats(is_c, cash), is_c)
    m_ctrl_oos = _enrich(book_stats(oos_c, cash), oos_c)
    verd = "CONTROL" if arm.role == "control" else "RESEARCH"
    note = _struct_note(arm, m_is, m_ctrl_is)
    return {
        "arm": arm,
        "trades": trades,
        "missing": missing,
        "m_full": m_full,
        "m_is": m_is,
        "m_oos": m_oos,
        "m_ctrl_is": m_ctrl_is,
        "m_ctrl_oos": m_ctrl_oos,
        "verd": verd,
        "note": note,
    }


def _fmt_opt_pct(v: Any) -> str:
    if v is None:
        return ""
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return ""


def _fmt_opt_int(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return ""


def write_closed_csv(trades: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "SYMBOL",
        "DATE OPENED",
        "ENTRY PRICE",
        "ORIGINAL STOP",
        "DATE CLOSED",
        "DAYS HELD",
        "EXIT PRICE",
        "FINAL EXIT PRICE",
        "PNL %",
        "PNL $",
        "EXIT TYPE",
        "ACTIVATED",
        "ACTIVATION_DATE",
        "PARTIAL",
        "PARTIAL_PX",
        "PARTIAL_DATE",
        "PARTIAL_PNL_%",
        "REMAINDER_PNL_%",
        "TOTAL_PNL_%",
        "DAYS_TO_ACTIVATION",
        "ACTIVATION_TO_CLOSE",
        "ACTIVATION_TO_PROTECT_HIT",
        "GIVEBACK_FROM_PEAK",
        "PROTECT_HIT",
        "PROTECT_STOP",
        "PEAK_HIGH",
        "PEAK_PCT",
        "TIME_COUNTER",
        "REM_FRAC",
        "MISSING_BARS",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in trades:
            # TOTAL_PNL_% is the weighted full-position return (same as PNL % after overlay).
            total_pnl = t.get("total_pnl_pct")
            if total_pnl is None and t.get("pnl") is not None:
                total_pnl = t.get("pnl")
            w.writerow(
                [
                    t.get("sym", ""),
                    t.get("opened", ""),
                    f"{float(t['entry']):.4f}" if t.get("entry") is not None else "",
                    f"{float(t['stop']):.4f}" if t.get("stop") is not None else "",
                    t.get("closed", ""),
                    t.get("days", ""),
                    f"{float(t['exit_px']):.4f}" if t.get("exit_px") is not None else "",
                    f"{float(t['final_exit_px']):.4f}" if t.get("final_exit_px") is not None else "",
                    f"{float(t['pnl']):.4f}",
                    f"{float(t['pnl_d']):.2f}",
                    t.get("exit", ""),
                    "1" if t.get("activated") else "0",
                    t.get("activation_date", ""),
                    "1" if t.get("partial") else "0",
                    f"{float(t['partial_px']):.4f}" if t.get("partial_px") is not None else "",
                    t.get("partial_date", ""),
                    _fmt_opt_pct(t.get("partial_pnl_pct")),
                    _fmt_opt_pct(t.get("remainder_pnl_pct")),
                    _fmt_opt_pct(total_pnl),
                    _fmt_opt_int(t.get("days_to_activation")),
                    _fmt_opt_int(t.get("activation_to_close")),
                    _fmt_opt_int(t.get("activation_to_protect_hit")),
                    _fmt_opt_pct(t.get("giveback_from_peak")),
                    "1" if t.get("protect_hit") else "0",
                    f"{float(t['protect_stop']):.4f}" if t.get("protect_stop") is not None else "",
                    f"{float(t['peak_high']):.4f}" if t.get("peak_high") is not None else "",
                    f"{float(t.get('peak_pct') or 0):.4f}",
                    t.get("time_counter", ""),
                    f"{float(t.get('rem_frac') if t.get('rem_frac') is not None else 1):.4f}",
                    "1" if t.get("missing_bars") else "0",
                ]
            )


def _fmt_sharpe(m: dict[str, Any]) -> str:
    s = m.get("sharpe", float("nan"))
    return "—" if not math.isfinite(float(s)) else f"{float(s):.2f}"


def _fmt_calmar(m: dict[str, Any]) -> str:
    c = m.get("calmar", float("nan"))
    return "—" if not math.isfinite(float(c)) else f"{float(c):.2f}"


def exit_mix_str(d: dict) -> str:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k}:{v}" for k, v in items[:8])


def metric_table(results: list[dict], book_key: str, caption: str) -> str:
    headers = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Label", "text"),
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
            ("Activated", "num"),
            ("Protect exits", "num"),
            ("Partials", "num"),
            ("Δ Avg PnL%", "num"),
            ("Δ Win%", "num"),
            ("Δ PF", "num"),
            ("Δ Max DD%", "num"),
            ("Exit mix", "text"),
            ("Tag", "text"),
            ("Structural note", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl_m = results[0][book_key]
    parts = []
    for r in results:
        arm: ArmSpec = r["arm"]
        m = r[book_key]
        d_avg = m["avg_pnl"] - ctrl_m["avg_pnl"]
        d_wr = m["wr"] - ctrl_m["wr"]
        d_pf = m["pf"] - ctrl_m["pf"]
        d_dd = float(m.get("max_dd") or 0) - float(ctrl_m.get("max_dd") or 0)
        parts.append(
            "<tr>"
            f"<td>{html_mod.escape(arm.key)}</td>"
            f"<td>{html_mod.escape(arm.label)}</td>"
            f"<td class='num'>{m['n']}</td>"
            f"<td class='num'>{m['wr']:.1f}</td>"
            f"<td class='num'>{m['avg_pnl']:.2f}</td>"
            f"<td class='num'>{m.get('wo_max', float('nan')):.2f}</td>"
            f"<td class='num'>{m.get('avg_win', float('nan')):.2f}</td>"
            f"<td class='num'>{m.get('avg_loss', float('nan')):.2f}</td>"
            f"<td class='num'>{m['pf']:.2f}</td>"
            f"<td class='num'>{float(m.get('ann_ror') or float('nan')):.2f}</td>"
            f"<td class='num'>{float(m.get('max_dd') or float('nan')):.2f}</td>"
            f"<td class='num'>{_fmt_calmar(m)}</td>"
            f"<td class='num'>{_fmt_sharpe(m)}</td>"
            f"<td class='num'>{format_money(m.get('exp_d'))}</td>"
            f"<td class='num'>{m['avg_days']:.1f}</td>"
            f"<td class='num'>{float(m.get('cap_days') or 0):.0f}</td>"
            f"<td class='num'>{m.get('activated_n', 0)}</td>"
            f"<td class='num'>{m.get('protect_n', 0)}</td>"
            f"<td class='num'>{m.get('partial_n', 0)}</td>"
            f"<td class='num'>{d_avg:+.2f}</td>"
            f"<td class='num'>{d_wr:+.1f}</td>"
            f"<td class='num'>{d_pf:+.2f}</td>"
            f"<td class='num'>{d_dd:+.2f}</td>"
            f"<td>{html_mod.escape(exit_mix_str(m.get('exit_mix') or {}))}</td>"
            f"<td>{html_mod.escape(r['verd'])}</td>"
            f"<td>{html_mod.escape(r['note'])}</td>"
            "</tr>"
        )
    return (
        f"<section class='card'><h2>{html_mod.escape(caption)}</h2>"
        f"<p class='meta'>Click column headers to sort. Judge on IS quality; OOS is validation only. "
        f"Do not auto-pick highest PnL.</p>"
        f"<table class='sortable'><thead><tr>{th}</tr></thead><tbody>"
        + "".join(parts)
        + "</tbody></table></section>"
    )


def write_compare_html(results: list[dict], out: Path) -> None:
    css = (
        "body{font-family:Segoe UI,system-ui,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}"
        ".card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;margin:16px 0}"
        "h1{margin:0 0 8px} h2{margin:0 0 10px;font-size:1.15rem}"
        ".meta{color:#475569;font-size:.92rem} pre{white-space:pre-wrap;background:#f1f5f9;padding:12px;border-radius:8px}"
        "table{border-collapse:collapse;width:100%;font-size:.88rem}"
        "th,td{border-bottom:1px solid #e2e8f0;padding:6px 8px;text-align:left;vertical-align:top}"
        "td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}"
        "th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}"
        "th.sortable-th:hover{background:#e2e8f0}"
        + SORTABLE_TH_CSS
    )
    freeze_rows = "".join(
        f"<tr><td>{html_mod.escape(a.key)}</td><td>{html_mod.escape(a.label)}</td>"
        f"<td>{'—' if a.activation is None else f'{a.activation*100:.0f}%'}</td>"
        f"<td>{'50%' if a.partial else ('—' if a.role=='control' else 'none')}</td>"
        f"<td>{html_mod.escape(a.protect or 'none (timed only)')}</td></tr>"
        for a in ARMS
    )
    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>RL Profit Protection Matrix {STAMP}</title>
<style>{css}</style></head><body>
<h1>RL Exit Research — Profit Protection Matrix</h1>
<p class="meta">Stamp <code>{STAMP}</code> · Control Closed <code>{html_mod.escape(str(DEFAULT_CLOSED.name))}</code>
· IS cut {IS_CUT.isoformat()} · RESEARCH only · not gold · not DailyRun</p>

<section class="card">
<h2>What you asked</h2>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
</section>

<section class="card">
<h2>In plain English</h2>
<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
</section>

<section class="card">
<h2>Paul note</h2>
<ul>
<li>EXIT architecture matrix only — entries frozen from no-SMA +20%/60d Control.</li>
<li>Fib stop = highest HIGH − fib×(HIGH − entry); ratchet up only; High not Close.</li>
<li>60 trading-day terminal starts at first activation (+20% or +25% per arm).</li>
<li>Compare/selection on <strong>IS</strong>; OOS report-only. No auto-select on max PnL.</li>
<li>Tags stay <code>RESEARCH</code> — structural read of each architecture, not a KEEP race.</li>
</ul>
</section>

<section class="card">
<h2>Arm freeze</h2>
<table class="sortable"><caption>Click headers to sort</caption>
<thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Label", "text")}{sortable_th("Activation", "text")}
{sortable_th("Partial", "text")}{sortable_th("Protection", "text")}
</tr></thead><tbody>{freeze_rows}</tbody></table>
</section>

{metric_table(results, "m_is", "IS (entry &lt; 2024-01-01) — selection / comparison")}
{metric_table(results, "m_oos", "OOS (entry ≥ 2024-01-01) — validation only")}
{metric_table(results, "m_full", "FULL book")}

<section class="card">
<h2>Trade-level outputs</h2>
<ul>
{"".join(f"<li><code>closed/{html_mod.escape(a.key)}_RL_Closed_overlay.csv</code></li>" for a in ARMS)}
</ul>
</section>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    out.write_text(body, encoding="utf-8")


def write_baseline(results: list[dict], out: Path) -> None:
    lines = [
        f"# BASELINE — `rl_profit_protect_matrix_{STAMP}`",
        "",
        "**Status:** RESEARCH only. EXIT profit-protection matrix. Entries frozen.",
        "**Control:** no-SMA-target +20% milestone / 60 trading-day (`pct20_d60`).",
        "Not gold. Not DailyRun. Do not auto-select highest-profit arm.",
        "",
        "## What you asked",
        "",
        "```",
        REQUEST_PROMPT.strip(),
        "```",
        "",
        "## In plain English",
        "",
        LAYMAN_TRANSLATION.strip(),
        "",
        "## Freeze",
        "",
        "- Entry: same as `rl_no_sma_target_exit_ab_20260905` / `pct20_d60` (th113_vol + sma_target_off)",
        "- Control Closed source: `" + str(DEFAULT_CLOSED).replace("\\", "/") + "`",
        "- IS = entry < 2024-01-01; OOS report-only",
        "- Fib from entry → highest HIGH; ratchet up only",
        "- Terminal: 60 trading days after activation for A–L",
        "",
        "## IS snapshot (structural — not KEEP ranking)",
        "",
        "| Arm | N | WR | Avg% | PF | MaxDD | AvgDays | Activated | Protect | Note |",
        "|-----|---|----|------|----|-------|---------|-----------|---------|------|",
    ]
    for r in results:
        a: ArmSpec = r["arm"]
        m = r["m_is"]
        lines.append(
            f"| `{a.key}` | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | {m['pf']:.2f} | "
            f"{float(m.get('max_dd') or 0):.2f} | {m['avg_days']:.1f} | {m.get('activated_n', 0)} | "
            f"{m.get('protect_n', 0)} | {r['note'][:80]} |"
        )
    lines += [
        "",
        "## Data quality note (2026-09-21 re-run)",
        "",
        "Two EA rows in A–L previously exited `EOD_DATA` on 2026-08-10 with multi-year holds "
        "(~800–1100% PnL). Cause: `data/newdata/data/EA.csv` was truncated to 6 bars "
        "(2026-07-17→2026-08-10); replay activated on the first available bar and never "
        "reached the 60-day terminal. Restored EA from DuckDB (4175 bars, 2010-01-04→2026-08-10). "
        "Hardened `pygetallMore._history_covers_start` so tiny recent stubs no longer skip "
        "full backfill. Replay now treats first-bar gaps > "
        f"`MAX_ENTRY_GAP_DAYS` ({MAX_ENTRY_GAP_DAYS} calendar) as `missing_bars` "
        "(keep Control exit). Post-fix: EA 2011-06-10 → STOP_LOSS; "
        "EA 2013-03-21 → RL_EXIT_DAYS.",
        "",
        "## Selection-bias / discipline",
        "",
        "A–L were a-priori from Paul's matrix (activation × partial × protect). "
        "No extra knobs. Judge structural behavior on IS; OOS softens → HOLD, do not retune.",
        "",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_metrics_csv(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "arm",
        "book",
        "n",
        "wr",
        "avg_pnl",
        "wo_max",
        "pf",
        "ann_ror",
        "max_dd",
        "calmar",
        "sharpe",
        "avg_days",
        "cap_days",
        "activated_n",
        "protect_n",
        "partial_n",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            a: ArmSpec = r["arm"]
            for book in ("m_is", "m_oos", "m_full"):
                m = r[book]
                w.writerow(
                    {
                        "arm": a.key,
                        "book": book[2:].upper(),
                        "n": m["n"],
                        "wr": f"{m['wr']:.4f}",
                        "avg_pnl": f"{m['avg_pnl']:.4f}",
                        "wo_max": f"{m.get('wo_max', float('nan')):.4f}",
                        "pf": f"{m['pf']:.4f}",
                        "ann_ror": f"{float(m.get('ann_ror') or float('nan')):.4f}",
                        "max_dd": f"{float(m.get('max_dd') or float('nan')):.4f}",
                        "calmar": f"{float(m.get('calmar') or float('nan')):.4f}",
                        "sharpe": f"{float(m.get('sharpe') or float('nan')):.4f}",
                        "avg_days": f"{m['avg_days']:.4f}",
                        "cap_days": f"{float(m.get('cap_days') or 0):.2f}",
                        "activated_n": m.get("activated_n", 0),
                        "protect_n": m.get("protect_n", 0),
                        "partial_n": m.get("partial_n", 0),
                    }
                )


def run_matrix(
    ctrl: list[dict[str, Any]],
    jobs: int,
    *,
    arm_keys: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    closed_dir = OUT_DIR / "closed"
    closed_dir.mkdir(parents=True, exist_ok=True)

    arms = [a for a in ARMS if arm_keys is None or a.key in arm_keys]
    if not arms:
        raise ValueError(f"No arms matched filter {sorted(arm_keys or [])}")

    # Sequential is safer for shared OHLC cache; jobs>1 still ok via threads in caller.
    for arm in arms:
        print(f"[arm] {arm.key} …", flush=True)
        trades, missing = apply_arm(ctrl, arm)
        write_closed_csv(trades, closed_dir / f"{arm.key}_RL_Closed_overlay.csv")
        packed = pack(ctrl, trades, arm, missing)
        results.append(packed)
        m = packed["m_full"]
        print(
            f"  N={m['n']} Avg%={m['avg_pnl']:.2f} WR={m['wr']:.1f} PF={m['pf']:.2f} "
            f"missing={missing} protect={m.get('protect_n', 0)}",
            flush=True,
        )
    return results


def main() -> int:
    global OUT_DIR, DEFAULT_CLOSED
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--closed", type=Path, default=DEFAULT_CLOSED)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument(
        "--arms",
        type=str,
        default="",
        help="Comma-separated arm keys to run (e.g. B or control,B). Default: all.",
    )
    args = ap.parse_args()

    OUT_DIR = args.out
    DEFAULT_CLOSED = args.closed
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DEFAULT_CLOSED.is_file():
        print(f"ERROR: missing control Closed: {DEFAULT_CLOSED}", file=sys.stderr)
        return 2

    arm_keys: Optional[set[str]] = None
    if str(args.arms).strip():
        arm_keys = {k.strip() for k in str(args.arms).split(",") if k.strip()}
        known = {a.key for a in ARMS}
        bad = sorted(arm_keys - known)
        if bad:
            print(f"ERROR: unknown arm keys: {bad}; known={sorted(known)}", file=sys.stderr)
            return 2

    ctrl = load_closed(DEFAULT_CLOSED, "rl")
    print(f"[control] loaded N={len(ctrl)} from {DEFAULT_CLOSED.name}", flush=True)
    if args.summarize_only:
        print("[summarize-only] replaying arms from Control Closed (same as full run)", flush=True)
    results = run_matrix(ctrl, args.jobs, arm_keys=arm_keys)
    # Only rewrite compare/baseline/metrics when the full matrix is present
    # (subset runs refresh closed CSVs only so we do not clobber prior summary).
    if arm_keys is None or arm_keys >= {a.key for a in ARMS}:
        write_compare_html(results, OUT_DIR / "compare.html")
        write_baseline(results, OUT_DIR / "BASELINE.md")
        write_metrics_csv(results, OUT_DIR / "metrics_all.csv")
        (OUT_DIR / "SUMMARY.md").write_text(
            f"# SUMMARY — rl_profit_protect_matrix_{STAMP}\n\n"
            f"Control N={results[0]['m_full']['n']}. "
            f"See compare.html + BASELINE.md. RESEARCH structural matrix — no auto KEEP.\n",
            encoding="utf-8",
        )
        print(f"[done] {OUT_DIR / 'compare.html'}", flush=True)
    else:
        print(
            f"[done] closed refresh only for arms={sorted(arm_keys)} -> {OUT_DIR / 'closed'}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
