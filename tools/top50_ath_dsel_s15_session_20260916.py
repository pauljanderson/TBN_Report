#!/usr/bin/env python3
"""Session-only A/B on the selected dsel_2x_entry_s15 freeze (research only).

Control = parent ``dsel_2x_entry_s15`` trades (multi-day +2D / 1.5D stop).
Candidate 1 = same entries, flatten at the entry-day Close (daily honesty).
Candidate 2 = same entries on 1m if the tape exists: no new entry after 15:30 ET,
flatten at 15:55 ET (regular-session close window).

Does **not** write into ``top50_ath_2x_drop_ab_20260916``.
Does not retune D / stop / target. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
import time
from datetime import date, time as dtime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

import compare_format as cf  # noqa: E402
import run_spx_diversification as spx  # noqa: E402
import top50_ath_2x_drop_ab_20260916 as ab2x  # noqa: E402
import top50_ath_drawdown_20260916 as ath  # noqa: E402
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m  # noqa: E402

STAMP_ID = "top50_ath_dsel_s15_session_20260916"
STAMP_DIR = REPO / "drive" / "paul_experiments" / STAMP_ID
PARENT_ID = "top50_ath_2x_drop_ab_20260916"
PARENT_DIR = REPO / "drive" / "paul_experiments" / PARENT_ID

CONTROL_ARM = "dsel_2x_entry_s15"
EOD_ARM = "dsel_s15_eod_flat"
M1_ARM = "dsel_s15_rth_1530_eod"

SHEET_CASH = ab2x.SHEET_CASH
INITIAL_ACCOUNT = ab2x.INITIAL_ACCOUNT
IS_CUT = ab2x.IS_CUT
D_PCT = 5.0
STOP_MULT = 1.5
TARGET_MODE = "two_d_entry"

RTH_OPEN = dtime(9, 30)
ENTRY_CUTOFF = dtime(15, 30)
FLAT_FROM = dtime(15, 55)
RTH_CLOSE = dtime(16, 0)

ORIGINAL_REQUEST = (
    "what if we add to this never trade after 3:30? i don't want to hold overnight"
)
LAYMAN = (
    "“This” is the paper rule you liked on the 2×-drop table: buy a mega-cap the "
    "first day it is 5% below its closing all-time high (ATH), aim for a +10% bounce "
    "(two times that 5% drop), and sit a 7.5% stop under the buy. That book holds "
    "about 50 days. You asked to add two living-room rules: do not start a new trade "
    "after 3:30 p.m. Eastern, and do not hold overnight. Those rules change the "
    "system. A +10% bounce almost never happens between a 5% dip and the same day's "
    "close — you would need a rare same-day spike. So this stamp keeps your selected "
    "entries and only changes session identity: (1) the original multi-day book as "
    "control; (2) sell at that day's closing price on the daily chart (honest "
    "no-overnight without inventing a 3:30 clock); (3) if one-minute bars exist, "
    "enter only when the 5% line is first tagged at or before 3:30 p.m. Eastern and "
    "flatten at 3:55 p.m. Regular Trading Hours (RTH) are 9:30 a.m.–4:00 p.m. "
    "Eastern. In-sample (IS) is entries before 2024; out-of-sample (OOS) is 2024+ "
    "report-only. We do not retune the 5% / +10% / 7.5% numbers. Research only — "
    "not gold and not DailyRun."
)

ARM_NOTES = {
    CONTROL_ARM: (
        "CONTROL / selected parent: first-touch 5% off closing ATH; target +2D "
        "(+10%) from entry; stop 1.5D (7.5% below entry). Multi-day hold. Reused "
        "from top50_ath_2x_drop_ab_20260916. D/stop/target frozen."
    ),
    EOD_ARM: (
        "One change = session exit: same parent fills. If the trigger bar already "
        "tagged stop or +2D, keep that same-day exit. Else flatten at the "
        "entry-day Close (TIME). Same-day capital counts as 1 calendar day. "
        "Does not invent 15:30."
    ),
    M1_ARM: (
        "One change = RTH clock on the same parent trigger dates. Enter only if "
        "the 5% line is first tagged on 1m RTH at or before 15:30 ET. Stop-first "
        "then +2D target on later minutes; else flatten at the 15:55–16:00 ET "
        "close (fallback last RTH bar ≤16:00). Missing 1m days are marked, not "
        "silently dropped. Yahoo 1m tape is short (~Jul–Sep 2026); no 2024 IS."
    ),
}


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _th(label: str, sort_type: str) -> str:
    return spx._sortable_th(label, sort_type)


def _fmt_num(v: Any, digits: int = 2) -> str:
    return ab2x._fmt_num(v, digits)


def _fmt_int(v: Any) -> str:
    return ab2x._fmt_int(v)


def _fmt_pct(v: Any, digits: int = 2) -> str:
    return ab2x._fmt_pct(v, digits)


def _fmt_delta(v: Any, digits: int = 2, *, pct: bool = False) -> str:
    return ab2x._fmt_delta(v, digits, pct=pct)


def _load_control_trades() -> pd.DataFrame:
    path = PARENT_DIR / "trades.csv"
    if not path.is_file():
        raise RuntimeError(f"Missing parent trades: {path}")
    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df = df[df["arm"] == CONTROL_ARM].copy()
    if df.empty:
        raise RuntimeError(f"No {CONTROL_ARM} rows in {path}")
    df["trigger_date"] = pd.to_datetime(df["trigger_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    return df.reset_index(drop=True)


def _daily_close_map(symbols: list[str]) -> dict[tuple[str, date], dict[str, float]]:
    raw = ath._load_ohlc(sorted(set(symbols)))
    out: dict[tuple[str, date], dict[str, float]] = {}
    for rec in raw.to_dict("records"):
        key = (str(rec["symbol"]).upper(), pd.Timestamp(rec["Date"]).date())
        out[key] = {
            "open": float(rec["Open"]) if pd.notna(rec["Open"]) else float("nan"),
            "high": float(rec["High"]) if pd.notna(rec["High"]) else float("nan"),
            "low": float(rec["Low"]) if pd.notna(rec["Low"]) else float("nan"),
            "close": float(rec["Close"]) if pd.notna(rec["Close"]) else float("nan"),
        }
    return out


def _trade_dict(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    row = {
        "symbol": base["symbol"],
        "ath_seq": base.get("ath_seq"),
        "ath_date": str(pd.Timestamp(base["ath_date"]).date()) if pd.notna(base.get("ath_date")) else "",
        "ath_close": base.get("ath_close"),
        "trigger_date": pd.Timestamp(base["trigger_date"]),
        "entry": float(base["entry"]),
        "stop": float(base["stop"]),
        "target": float(base["target"]),
        "d_pct": float(base.get("d_pct") or D_PCT),
        "stop_mult": float(base.get("stop_mult") or STOP_MULT),
        "target_mode": str(base.get("target_mode") or TARGET_MODE),
    }
    row.update(overrides)
    t_tr = pd.Timestamp(row["trigger_date"])
    t_ex = pd.Timestamp(row["exit_date"])
    entry = float(row["entry"])
    exit_px = float(row["exit"])
    pnl_pct = (exit_px / entry - 1.0) * 100.0 if entry > 0 else float("nan")
    row["pnl_pct"] = pnl_pct
    row["pnl_d"] = SHEET_CASH * pnl_pct / 100.0
    if "cal_days_held" not in overrides:
        row["cal_days_held"] = max(int((t_ex.normalize() - t_tr.normalize()).days), 0)
    if "td_days_held" not in overrides:
        row["td_days_held"] = base.get("td_days_held")
    row["closed"] = int(str(row.get("exit_type") or "") != "OPEN")
    row["is_oos"] = int(t_tr >= IS_CUT)
    return row


def _control_rows(ctrl: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in ctrl.to_dict("records"):
        t_tr = pd.Timestamp(rec["trigger_date"])
        t_ex = pd.Timestamp(rec["exit_date"])
        out.append(
            _trade_dict(
                rec,
                arm=CONTROL_ARM,
                exit_date=t_ex,
                exit=float(rec["exit"]),
                exit_type=str(rec["exit_type"]),
                cal_days_held=int(rec["cal_days_held"]),
                td_days_held=rec.get("td_days_held"),
            )
        )
        out[-1]["trigger_date"] = t_tr
    return out


def _eod_rows(
    ctrl: pd.DataFrame, daily: dict[tuple[str, date], dict[str, float]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Same parent fills; flatten at entry-day Close unless already same-day STOP/TARGET."""
    trades: list[dict[str, Any]] = []
    n_kept_same = 0
    n_flat = 0
    n_missing_close = 0
    n_same_target = 0
    n_same_stop = 0
    for rec in ctrl.to_dict("records"):
        t_tr = pd.Timestamp(rec["trigger_date"])
        t_ex = pd.Timestamp(rec["exit_date"])
        etype = str(rec["exit_type"] or "")
        same_day = t_tr.normalize() == t_ex.normalize()
        if same_day and etype in ("STOP", "TARGET"):
            n_kept_same += 1
            if etype == "TARGET":
                n_same_target += 1
            else:
                n_same_stop += 1
            trades.append(
                _trade_dict(
                    rec,
                    arm=EOD_ARM,
                    exit_date=t_ex,
                    exit=float(rec["exit"]),
                    exit_type=etype,
                    cal_days_held=1,
                    td_days_held=0,
                    session_note="kept_same_bar_stop_or_target",
                )
            )
            continue
        bar = daily.get((str(rec["symbol"]).upper(), t_tr.date()))
        close = None if bar is None else bar.get("close")
        if close is None or not np.isfinite(close) or float(close) <= 0:
            n_missing_close += 1
            trades.append(
                _trade_dict(
                    rec,
                    arm=EOD_ARM,
                    exit_date=t_tr,
                    exit=float(rec["entry"]),
                    exit_type="OPEN",
                    cal_days_held=1,
                    td_days_held=0,
                    session_note="missing_entry_day_close",
                )
            )
            continue
        n_flat += 1
        trades.append(
            _trade_dict(
                rec,
                arm=EOD_ARM,
                exit_date=t_tr,
                exit=float(close),
                exit_type="TIME",
                cal_days_held=1,
                td_days_held=0,
                session_note="flatten_entry_day_close",
            )
        )
    stats = {
        "n_control": int(len(ctrl)),
        "n_kept_same_bar": n_kept_same,
        "n_same_day_target": n_same_target,
        "n_same_day_stop": n_same_stop,
        "n_eod_flat": n_flat,
        "n_missing_close": n_missing_close,
        "pct_same_day_target": (
            100.0 * n_same_target / len(ctrl) if len(ctrl) else None
        ),
    }
    return trades, stats


def _rth_mask(ts: pd.Series) -> pd.Series:
    clock = ts.dt.tz_convert(ET).dt.time
    return (clock >= RTH_OPEN) & (clock <= RTH_CLOSE)


def _flatten_px(day: pd.DataFrame) -> tuple[float | None, pd.Timestamp | None, str]:
    clock = day["ts"].dt.tz_convert(ET).dt.time
    window = day.loc[(clock >= FLAT_FROM) & (clock <= RTH_CLOSE)]
    if not window.empty:
        last = window.iloc[-1]
        return float(last["close"]), pd.Timestamp(last["ts"]), "flat_1555_1600"
    if day.empty:
        return None, None, "no_rth_bars"
    last = day.iloc[-1]
    return float(last["close"]), pd.Timestamp(last["ts"]), "flat_last_rth_le_1600"


def _simulate_1m_day(
    day: pd.DataFrame, *, entry: float, stop: float, target: float
) -> dict[str, Any]:
    tagged = day[day["low"].to_numpy(dtype=float) <= entry + 1e-12]
    if tagged.empty:
        return {"skip_reason": "rth_never_tagged", "entered": 0}
    first = tagged.iloc[0]
    tag_ts = pd.Timestamp(first["ts"]).tz_convert(ET)
    tag_clock = tag_ts.time()
    if tag_clock > ENTRY_CUTOFF:
        return {
            "skip_reason": "first_tag_after_1530",
            "entered": 0,
            "first_tag_ts": tag_ts,
            "first_tag_et": tag_clock.strftime("%H:%M"),
        }
    # Walk from the first tag bar inclusive. Stop-first, then target, else flatten.
    rest = day.loc[day["ts"] >= first["ts"]]
    for rec in rest.to_dict("records"):
        lo = float(rec["low"])
        hi = float(rec["high"])
        ts = pd.Timestamp(rec["ts"]).tz_convert(ET)
        if lo <= stop + 1e-12:
            return {
                "entered": 1,
                "skip_reason": "",
                "first_tag_ts": tag_ts,
                "first_tag_et": tag_clock.strftime("%H:%M"),
                "exit": stop,
                "exit_ts": ts,
                "exit_type": "STOP",
                "flatten_rule": "stop_first",
            }
        if hi >= target - 1e-12:
            return {
                "entered": 1,
                "skip_reason": "",
                "first_tag_ts": tag_ts,
                "first_tag_et": tag_clock.strftime("%H:%M"),
                "exit": target,
                "exit_ts": ts,
                "exit_type": "TARGET",
                "flatten_rule": "target_2d",
            }
    flat_px, flat_ts, rule = _flatten_px(day)
    if flat_px is None or flat_ts is None:
        return {
            "entered": 0,
            "skip_reason": "no_flatten_bar",
            "first_tag_ts": tag_ts,
            "first_tag_et": tag_clock.strftime("%H:%M"),
        }
    return {
        "entered": 1,
        "skip_reason": "",
        "first_tag_ts": tag_ts,
        "first_tag_et": tag_clock.strftime("%H:%M"),
        "exit": float(flat_px),
        "exit_ts": pd.Timestamp(flat_ts).tz_convert(ET),
        "exit_type": "TIME",
        "flatten_rule": rule,
    }


def _m1_rows(ctrl: pd.DataFrame) -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, Any]]:
    cache: dict[str, pd.DataFrame] = {}
    span: dict[str, tuple[str, str, int]] = {}
    coverage: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    skip_counts: dict[str, int] = {}

    symbols = sorted(ctrl["symbol"].astype(str).str.upper().unique())
    for sym in symbols:
        df = read_1m(sym)
        cache[sym] = df
        if df.empty:
            span[sym] = ("", "", 0)
        else:
            span[sym] = (
                str(pd.Timestamp(df["ts"].min()).date()),
                str(pd.Timestamp(df["ts"].max()).date()),
                int(len(df)),
            )

    for rec in ctrl.to_dict("records"):
        sym = str(rec["symbol"]).upper()
        t_tr = pd.Timestamp(rec["trigger_date"])
        trig = t_tr.date()
        mn, mx, nbar = span.get(sym, ("", "", 0))
        row: dict[str, Any] = {
            "symbol": sym,
            "ath_date": str(pd.Timestamp(rec["ath_date"]).date()) if pd.notna(rec.get("ath_date")) else "",
            "trigger_date": str(trig),
            "entry": float(rec["entry"]),
            "stop": float(rec["stop"]),
            "target": float(rec["target"]),
            "control_exit_type": str(rec.get("exit_type") or ""),
            "control_pnl_pct": float(rec["pnl_pct"]),
            "has_1m_file": int(nbar > 0),
            "m1_min_date": mn,
            "m1_max_date": mx,
            "n_1m_bars_symbol": nbar,
            "has_1m_on_trigger_date": 0,
            "n_rth_bars": 0,
            "first_tag_et": "",
            "entered": 0,
            "skip_reason": "",
            "m1_exit_type": "",
            "m1_pnl_pct": None,
            "flatten_rule": "",
        }
        df = cache[sym]
        if df.empty:
            row["skip_reason"] = "no_1m_file"
            skip_counts["no_1m_file"] = skip_counts.get("no_1m_file", 0) + 1
            coverage.append(row)
            continue
        day = df[df["ts"].dt.tz_convert(ET).dt.date == trig].copy()
        if day.empty:
            row["skip_reason"] = "no_1m_on_trigger_date"
            skip_counts["no_1m_on_trigger_date"] = skip_counts.get("no_1m_on_trigger_date", 0) + 1
            coverage.append(row)
            continue
        day = day.loc[_rth_mask(day["ts"])].sort_values("ts")
        row["has_1m_on_trigger_date"] = 1
        row["n_rth_bars"] = int(len(day))
        if day.empty:
            row["skip_reason"] = "no_rth_bars"
            skip_counts["no_rth_bars"] = skip_counts.get("no_rth_bars", 0) + 1
            coverage.append(row)
            continue
        sim = _simulate_1m_day(
            day,
            entry=float(rec["entry"]),
            stop=float(rec["stop"]),
            target=float(rec["target"]),
        )
        row["first_tag_et"] = str(sim.get("first_tag_et") or "")
        row["skip_reason"] = str(sim.get("skip_reason") or "")
        row["flatten_rule"] = str(sim.get("flatten_rule") or "")
        if not int(sim.get("entered") or 0):
            skip_counts[row["skip_reason"] or "skipped"] = (
                skip_counts.get(row["skip_reason"] or "skipped", 0) + 1
            )
            coverage.append(row)
            continue
        exit_px = float(sim["exit"])
        exit_ts = pd.Timestamp(sim["exit_ts"])
        pnl_pct = (exit_px / float(rec["entry"]) - 1.0) * 100.0
        row["entered"] = 1
        row["m1_exit_type"] = str(sim["exit_type"])
        row["m1_pnl_pct"] = pnl_pct
        coverage.append(row)
        trades.append(
            _trade_dict(
                rec,
                arm=M1_ARM,
                exit_date=pd.Timestamp(exit_ts.tz_localize(None) if exit_ts.tzinfo else exit_ts).normalize(),
                exit=exit_px,
                exit_type=str(sim["exit_type"]),
                cal_days_held=1,
                td_days_held=0,
                session_note=str(sim.get("flatten_rule") or ""),
                first_tag_et=row["first_tag_et"],
            )
        )

    cov_df = pd.DataFrame(coverage)
    n_ctrl = int(len(ctrl))
    n_file = int((cov_df["has_1m_file"] == 1).sum()) if not cov_df.empty else 0
    n_day = int((cov_df["has_1m_on_trigger_date"] == 1).sum()) if not cov_df.empty else 0
    n_ent = int((cov_df["entered"] == 1).sum()) if not cov_df.empty else 0
    tape_mins = [s[0] for s in span.values() if s[0]]
    tape_maxs = [s[1] for s in span.values() if s[1]]
    stats = {
        "n_control": n_ctrl,
        "n_symbols": int(len(symbols)),
        "n_symbols_with_1m_file": int(sum(1 for s in symbols if span[s][2] > 0)),
        "n_symbols_missing_1m_file": int(sum(1 for s in symbols if span[s][2] <= 0)),
        "n_control_with_1m_file": n_file,
        "n_control_with_1m_day": n_day,
        "n_entered": n_ent,
        "pct_control_with_1m_day": (100.0 * n_day / n_ctrl) if n_ctrl else None,
        "pct_entered_of_control": (100.0 * n_ent / n_ctrl) if n_ctrl else None,
        "pct_entered_of_1m_day": (100.0 * n_ent / n_day) if n_day else None,
        "skip_counts": skip_counts,
        "tape_min": min(tape_mins) if tape_mins else "",
        "tape_max": max(tape_maxs) if tape_maxs else "",
        "entry_cutoff_et": "15:30",
        "flatten_et": "15:55-16:00 (fallback last RTH bar <= 16:00)",
        "1m_dir": str(DEFAULT_1M_DIR),
    }
    return trades, cov_df, stats


def _quality_vs_control(arm: dict[str, Any], ctrl: dict[str, Any]) -> str:
    a, c = arm.get("avg_pnl_pct"), ctrl.get("avg_pnl_pct")
    if a is None or c is None or not np.isfinite(a) or not np.isfinite(c):
        return "unknown"
    if a + 0.05 < c:
        return "worse"
    if a > c + 0.05 and ab2x._quality_better(arm, ctrl):
        return "better"
    return "flat"


def _verdict_for(
    arm_id: str,
    books: dict[tuple[str, str], dict[str, Any]],
    *,
    eod_stats: dict[str, Any],
    m1_stats: dict[str, Any],
) -> str:
    if arm_id == CONTROL_ARM:
        return "CONTROL / SELECTED (parent pick after 2× table; selection bias; not gold)"
    is_arm = books.get((arm_id, "IS"))
    oos_arm = books.get((arm_id, "OOS"))
    is_ctrl = books.get((CONTROL_ARM, "IS"))
    full_arm = books.get((arm_id, "FULL")) or {}

    if arm_id == M1_ARM:
        n = int(full_arm.get("n_trades") or 0)
        n_day = int(m1_stats.get("n_control_with_1m_day") or 0)
        if n < 30 or n_day < 30:
            return (
                "HOLD (1m Yahoo tape is ~8 weeks; no IS before 2024; N too small; "
                "research only)"
            )
        return "HOLD (short-tape 1m; no IS; research only)"

    if not is_arm or not is_ctrl:
        return "HOLD"
    q = _quality_vs_control(is_arm, is_ctrl)
    same_tgt = eod_stats.get("pct_same_day_target")
    thesis_dead = same_tgt is not None and float(same_tgt) < 5.0
    a = is_arm.get("avg_pnl_pct")
    if q == "worse" or (a is not None and np.isfinite(a) and a <= 0):
        if thesis_dead:
            return (
                "DISMISS (same-day flatten kills the +10% / 50-day measured-move; "
                "quality worse on IS)"
            )
        return "DISMISS"
    if q == "better":
        if not oos_arm or ab2x._oos_softens(is_arm, oos_arm):
            return "HOLD"
        return "LEAN KEEP (research only; not gold; not DailyRun)"
    if thesis_dead:
        return "HOLD (session-only is a different system; +10% same-day is rare)"
    return "HOLD"


def _book_table_html(df: pd.DataFrame, cols: list[tuple[str, str, str]]) -> str:
    return ab2x._table(df, cols, row_class_key="verdict")


def _write_baseline(
    path: Path,
    *,
    ohlc_start: str,
    ohlc_end: str,
    n_names: int,
    n_control: int,
    eod_stats: dict[str, Any],
    m1_stats: dict[str, Any],
    books: pd.DataFrame,
    verdicts: dict[str, str],
) -> None:
    def _row(arm: str, sl: str) -> dict[str, Any]:
        sub = books[(books["arm"] == arm) & (books["slice"] == sl)]
        return sub.iloc[0].to_dict() if len(sub) else {}

    def _line(arm: str) -> str:
        isr, oos = _row(arm, "IS"), _row(arm, "OOS")
        return (
            f"- `{arm}` verdict **{verdicts.get(arm, '')}** — "
            f"IS N={isr.get('n_trades')} WR={isr.get('win_pct')} "
            f"AvgPnL%={isr.get('avg_pnl_pct')} PF={isr.get('profit_factor')} "
            f"AnnROR={isr.get('ann_ror')} MaxDD={isr.get('max_dd')}; "
            f"OOS N={oos.get('n_trades')} WR={oos.get('win_pct')} "
            f"AvgPnL%={oos.get('avg_pnl_pct')} PF={oos.get('profit_factor')} "
            f"AnnROR={oos.get('ann_ror')} MaxDD={oos.get('max_dd')}."
        )

    lines = [
        f"# BASELINE — {STAMP_ID}",
        "",
        "**Status:** Research session-only overlay on the selected parent arm. **Not gold. Not DailyRun.** No adopt.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Freeze (do not silently mutate)",
        "",
        f"- **Parent stamp (do not overwrite):** `{PARENT_ID}`. Control fills reused from that folder's `trades.csv` arm `{CONTROL_ARM}`.",
        "- **Selection note:** Paul picked `dsel_2x_entry_s15` after seeing the parent 2× A/B table. That pick is **in-sample selection**. This stamp does **not** retune D / stop / target on IS or OOS. The only knob is **session identity** (ENTRY/EXIT clock / no overnight).",
        "- **Universe:** same ever-top-50 mega-cap names as the parent (100 names on the reused book).",
        "- **ATH:** new **closing** high in the local sample. Not a 52-week high.",
        "- **Entry (frozen):** first-touch **D = 5%** — first daily Low ≤ 5% below the ATH close; fill at that 5% line (optimistic if the bar gaps through).",
        "- **Target (frozen):** +2D from entry = **+10%**. High-tag on the multi-day control.",
        "- **Stop (frozen):** 1.5D = **7.5%** below entry. Same-bar Low through stop = STOP first.",
        "- **Control exit identity:** hold to +2D or 1.5D stop (or OPEN at sample end). Avg hold ~50 calendar days. This is a measured-move swing book.",
        "- **Candidate `dsel_s15_eod_flat` exit identity:** flatten at the **entry-day Close**. Same-day STOP/TARGET on the trigger bar are kept. Same-day capital = 1 calendar day so annualized rate of return (Ann ROR) is defined. Daily bars have no 15:30 clock — this is the honest no-overnight test.",
        "- **Candidate `dsel_s15_rth_1530_eod` exit/entry identity:** Regular Trading Hours (RTH) 09:30–16:00 ET. Enter only if the 5% line is first tagged on 1-minute RTH at or before **15:30 ET**. Flatten at the **15:55–16:00 ET** close (fallback last RTH bar ≤16:00). Stop-first then +2D on later minutes. Missing 1m trigger days are listed in `m1_coverage.csv` — names/dates are not silently dropped.",
        "- **Not in this stamp:** no D/stop/target shop; no multi-day time-stop on the control book; no occupancy re-sim (later first-touches the 50-day hold blocked stay blocked — that would be a second change).",
        f"- **OHLC window (parent / daily):** {ohlc_start} → {ohlc_end}.",
        f"- **1m store:** `{DEFAULT_1M_DIR}` (Yahoo 1-minute parquet; not ticks). Tape span {m1_stats.get('tape_min')} → {m1_stats.get('tape_max')}.",
        "- **IS / OOS:** IS = `trigger_date < 2024-01-01`; OOS = `trigger_date ≥ 2024-01-01` (report-only; do not retune). The 1m arm has **no IS** — the local tape starts in 2026.",
        "- **Sizing:** $10,000 sheet notional / trade; Max drawdown (DD) / Sharpe seed $500,000 on exit-date equity. Costs = 0.",
        "- **Not DailyRun. Not gold.**",
        "",
        "## Counts",
        "",
        f"- Names on the control book: **{n_names}**",
        f"- Control trades reused: **{n_control}**",
        f"- Same-day STOP or TARGET already on control (kept in EOD arm): **{eod_stats.get('n_kept_same_bar')}** "
        f"(TARGET {eod_stats.get('n_same_day_target')}, STOP {eod_stats.get('n_same_day_stop')})",
        f"- EOD flatten at entry-day Close: **{eod_stats.get('n_eod_flat')}**",
        f"- Same-day +10% TARGET rate on control fills: **{_fmt_pct(eod_stats.get('pct_same_day_target'))}**",
        f"- 1m: symbols with a parquet file **{m1_stats.get('n_symbols_with_1m_file')}** / **{m1_stats.get('n_symbols')}**; "
        f"control dates with a 1m RTH day **{m1_stats.get('n_control_with_1m_day')}** / **{n_control}** "
        f"({_fmt_pct(m1_stats.get('pct_control_with_1m_day'))}); entered ≤15:30 **{m1_stats.get('n_entered')}**.",
        f"- 1m skip reasons: {m1_stats.get('skip_counts')}",
        "",
        "## Overlay vs selected control (research only)",
        "",
        "Judge quality (win%, Avg Profit and Loss (PnL) %, expectancy, profit factor (PF), Ann ROR, Max DD, Calmar, Sharpe), not trade count. OOS report-only. HOLD if OOS softens. Ann ROR on a 1-day flatten is **not** comparable to a 50-day hold — do not use it to rescue a dead measured-move.",
        "",
        _line(CONTROL_ARM),
        _line(EOD_ARM),
        _line(M1_ARM),
        "",
        "## Honesty / selection",
        "",
        "- Parent arm was chosen after the 2× table (selection bias). Frozen here; OOS not used to retune D/stop/target.",
        "- Session-only is a **different system** from a 50-day +10% measured move. They cannot coexist except on rare same-day spikes.",
        "- Daily EOD flatten cannot encode 15:30. The 1m arm is the 15:30 test and is coverage-limited.",
        "- First-touch fill at exactly D% is optimistic when the trigger bar gaps through.",
        "- Yahoo 1m ≠ ticks; gaps happen; daily vs 1m print can disagree (`rth_never_tagged`).",
        "- No Paul Score / FIT / robust FIT (closed overlay; no host Summary).",
        "- Survivorship; sample ATH from 2010; dividends ignored; no costs.",
        "- OOS softens → HOLD. Do not retune D / stop / target on 2024+.",
        "",
        "## Verdict",
        "",
        "**Research only.** See HTML verdict column. **Not gold. Not DailyRun.** Do not wire DailyRun.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_hypothesis(path: Path) -> None:
    text = f"""# HYPOTHESIS — {STAMP_ID}

Research. **None of these is gold / DailyRun.**

| Field | Fill |
|-------|------|
| System / prefix | Session-only overlay on selected parent `{CONTROL_ARM}` |
| Evidence | Parent `{PARENT_ID}` trades/books (reused fills; folder not mutated except a one-line pointer) |
| Single knob | Session identity only: no overnight / no new entry after 15:30 ET |
| Frozen | Universe + closing ATH + D=5% first-touch + target +2D + stop 1.5D + $10k + one position / symbol occupancy from the parent book |
| Not tested | D, target multiple, stop multiple, multi-day time-stop, occupancy re-sim |
| Control | `{CONTROL_ARM}` as already computed (multi-day hold) |
| Candidate A | `{EOD_ARM}` — same fills, flatten entry-day Close |
| Candidate B | `{M1_ARM}` — same trigger dates, 1m RTH ≤15:30 entry, flatten 15:55 ET |
| IS / OOS | trigger_date < 2024-01-01 / ≥ 2024-01-01 (OOS report-only). 1m arm has no IS. |
| Selection | Parent pick was after the 2× table (labeled). This stamp does not re-shop D/stop/target. |

Judge quality not count. OOS report-only. HOLD if OOS softens.

**Honesty:** a +10% measured move and “flatten before overnight” are different jobs. Same-day +10% after a 5% first-touch is the exception, not the rule.
"""
    path.write_text(text, encoding="utf-8")


def _write_html(
    path: Path,
    *,
    books: pd.DataFrame,
    deltas: pd.DataFrame,
    verdicts: dict[str, str],
    eod_stats: dict[str, Any],
    m1_stats: dict[str, Any],
    cov: pd.DataFrame,
    ohlc_start: str,
    ohlc_end: str,
    n_names: int,
    n_control: int,
) -> None:
    book_cols = [
        ("Arm", "text", "arm"),
        ("Slice", "text", "slice"),
        ("Verdict", "text", "verdict"),
        ("N trades", "num", "n_trades"),
        ("Wins", "num", "n_wins"),
        ("Losses", "num", "n_losses"),
        ("Win %", "num", "win_pct"),
        ("Avg PnL %", "num", "avg_pnl_pct"),
        ("AVG_PNL_PCT_WO_MAX", "num", "avg_pnl_pct_wo_max"),
        ("Expectancy %", "num", "expectancy_pct"),
        ("Expectancy $", "num", "expectancy_d"),
        ("Avg win %", "num", "avg_win_pct"),
        ("Avg loss %", "num", "avg_loss_pct"),
        ("W/L count", "num", "win_loss_count_ratio"),
        ("Profit factor", "num", "profit_factor"),
        ("Ann ROR %", "num", "ann_ror"),
        ("Max DD %", "num", "max_dd"),
        ("Calmar", "num", "calmar"),
        ("Sharpe", "num", "sharpe"),
        ("Profit / capital day", "num", "profit_per_capital_day"),
        ("Capital days", "num", "capital_days"),
        ("Avg days held", "num", "avg_days_held"),
        ("Med days held", "num", "median_days_held"),
        ("P90 days held", "num", "p90_days_held"),
        ("Losing streak", "num", "losing_streak"),
        ("Avg positions", "num", "avg_positions"),
        ("Med positions", "num", "median_positions"),
        ("Max positions", "num", "max_positions"),
        ("N TARGET", "num", "n_target"),
        ("% TARGET", "num", "pct_target"),
        ("N STOP", "num", "n_stop"),
        ("% STOP", "num", "pct_stop"),
        ("N TIME", "num", "n_time"),
        ("% TIME", "num", "pct_time"),
        ("N OPEN", "num", "n_open"),
        ("% OPEN", "num", "pct_open"),
        ("Paul / FIT / robust FIT", "text", "fit_label"),
        ("Note", "text", "note"),
    ]
    delta_cols = [
        ("Arm", "text", "arm"),
        ("Slice", "text", "slice"),
        ("Verdict", "text", "verdict"),
        ("Δ N", "num", "d_n_trades"),
        ("Δ Win %", "num", "d_win_pct"),
        ("Δ Avg PnL %", "num", "d_avg_pnl_pct"),
        ("Δ WO_MAX %", "num", "d_avg_pnl_pct_wo_max"),
        ("Δ PF", "num", "d_profit_factor"),
        ("Δ Ann ROR %", "num", "d_ann_ror"),
        ("Δ Max DD %", "num", "d_max_dd"),
        ("Δ Calmar", "num", "d_calmar"),
        ("Δ Sharpe", "num", "d_sharpe"),
        ("Δ expectancy $", "num", "d_expectancy_d"),
        ("Δ profit / cap day", "num", "d_profit_per_capital_day"),
        ("Δ avg days", "num", "d_avg_days_held"),
    ]
    cov_cols = [
        ("Symbol", "text", "symbol"),
        ("Trigger", "date", "trigger_date"),
        ("Has 1m file", "num", "has_1m_file"),
        ("1m day?", "num", "has_1m_on_trigger_date"),
        ("RTH bars", "num", "n_rth_bars"),
        ("First tag ET", "text", "first_tag_et"),
        ("Entered", "num", "entered"),
        ("Skip reason", "text", "skip_reason"),
        ("1m exit", "text", "m1_exit_type"),
        ("1m PnL %", "num", "m1_pnl_pct"),
        ("Flatten rule", "text", "flatten_rule"),
        ("Control exit", "text", "control_exit_type"),
        ("Control PnL %", "num", "control_pnl_pct"),
        ("1m min", "date", "m1_min_date"),
        ("1m max", "date", "m1_max_date"),
    ]
    show_books = books.copy()
    show_books["fit_label"] = "N/A (closed overlay; no host Summary)"
    show_books["verdict"] = show_books["arm"].map(lambda a: verdicts.get(str(a), ""))
    show_deltas = deltas.copy()
    show_deltas["verdict"] = show_deltas["arm"].map(lambda a: verdicts.get(str(a), ""))
    cov_show = cov.copy() if cov is not None and not cov.empty else pd.DataFrame()
    if not cov_show.empty:
        # Full coverage is 2k+ rows; HTML shows the 1m-day rows plus a skip-reason rollup.
        day_rows = cov_show[cov_show["has_1m_on_trigger_date"] == 1].copy()
        skip_roll = (
            cov_show.groupby("skip_reason", dropna=False)
            .size()
            .reset_index(name="n")
            .sort_values("n", ascending=False)
        )
        skip_roll["skip_reason"] = skip_roll["skip_reason"].fillna("(entered)")
    else:
        day_rows = pd.DataFrame()
        skip_roll = pd.DataFrame()
    skip_cols = [("Skip / empty = entered", "text", "skip_reason"), ("N control dates", "num", "n")]

    def _b(arm: str, sl: str) -> dict[str, Any]:
        sub = books[(books["arm"] == arm) & (books["slice"] == sl)]
        return sub.iloc[0].to_dict() if len(sub) else {}

    ctrl_is, eod_is = _b(CONTROL_ARM, "IS"), _b(EOD_ARM, "IS")
    ctrl_oos, eod_oos = _b(CONTROL_ARM, "OOS"), _b(EOD_ARM, "OOS")
    m1_full = _b(M1_ARM, "FULL")
    vtxt = "; ".join(f"{k}={v}" for k, v in verdicts.items())

    cards = [
        (
            "Control avg hold",
            f"{_fmt_num(_b(CONTROL_ARM, 'FULL').get('avg_days_held'), 1)} days",
            f"N={_fmt_int(n_control)} · selected parent {CONTROL_ARM}",
        ),
        (
            "Same-day +10% TARGET",
            _fmt_pct(eod_stats.get("pct_same_day_target")),
            f"{_fmt_int(eod_stats.get('n_same_day_target'))} of {_fmt_int(n_control)} parent fills already tagged +2D on the trigger bar",
        ),
        (
            "EOD flatten IS Avg PnL %",
            _fmt_pct(eod_is.get("avg_pnl_pct")),
            f"vs control IS {_fmt_pct(ctrl_is.get('avg_pnl_pct'))} · verdict {verdicts.get(EOD_ARM, '')}",
        ),
        (
            "1m dates covered",
            f"{_fmt_int(m1_stats.get('n_control_with_1m_day'))} / {_fmt_int(n_control)}",
            f"Tape {m1_stats.get('tape_min')} → {m1_stats.get('tape_max')} · entered {_fmt_int(m1_stats.get('n_entered'))}",
        ),
        (
            "1m FULL Avg PnL %",
            _fmt_pct(m1_full.get("avg_pnl_pct")),
            f"N={_fmt_int(m1_full.get('n_trades'))} · no IS (tape is 2026)",
        ),
        (
            "Names / daily window",
            f"{_fmt_int(n_names)} / {ohlc_start}→{ohlc_end}",
            "Research only. Not gold. Not DailyRun.",
        ),
    ]
    card_html = "".join(
        f'<div class="card"><h3>{_esc(t)}</h3><div class="metric">{m}</div><div class="small">{_esc(n)}</div></div>'
        for t, m, n in cards
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Session-only on dsel_2x_entry_s15 — {STAMP_ID}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.sub, .meta {{ color: #475569; font-size: .92rem; max-width: 76rem; line-height: 1.5; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 76rem; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; min-width: 200px; flex: 1 1 210px; }}
.card h3 {{ margin: 0 0 8px; font-size: 13px; color: #475569; }}
.metric {{ font-size: 1.2rem; font-weight: 700; line-height: 1.25; }}
.small {{ font-size: 12px; color: #64748b; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 12px; width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.total-row td {{ background: #e0f2fe; font-weight: 600; }}
tr.ctrl td {{ background: #f1f5f9; }}
tr.keep td {{ background: #ecfdf5; }}
tr.hold td {{ background: #fffbeb; }}
tr.dismiss td {{ background: #fef2f2; }}
{spx.SORTABLE_TH_CSS}
</style></head><body>
<h1>Can we add “no trade after 3:30 / no overnight” to the selected 5% / +10% arm?</h1>
<p class="sub">Research only. Not gold. Not DailyRun. Stamp <code>{STAMP_ID}</code>.
Parent <code>{PARENT_ID}</code> was not overwritten. Daily OHLC {_esc(ohlc_start)} → {_esc(ohlc_end)}.
Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>
<div class="cards">{card_html}</div>
<div class="callout">
<h2 style="margin-top:0">Answer</h2>
<p><strong>You cannot bolt “flatten before overnight / no new entry after 3:30” onto this arm and keep the +10% measured-move.</strong>
The selected book’s edge is sitting ~50 days for a +10% bounce (or taking a 7.5% stop).
Only {_fmt_pct(eod_stats.get('pct_same_day_target'))} of the parent fills already tagged +10% on the entry day
({_fmt_int(eod_stats.get('n_same_day_target'))} of {_fmt_int(n_control)}).
Everyone else, under a no-overnight rule, is just selling the same day’s close after buying a 5% dip —
that is a same-day mean-reversion scalp, not the swing you liked.</p>
<p><strong>Daily no-overnight (must-run).</strong> Same { _fmt_int(n_control) } fills. IS Avg PnL %
{_fmt_pct(eod_is.get('avg_pnl_pct'))} vs control {_fmt_pct(ctrl_is.get('avg_pnl_pct'))};
IS win % {_fmt_pct(eod_is.get('win_pct'))} vs {_fmt_pct(ctrl_is.get('win_pct'))};
IS profit factor {_fmt_num(eod_is.get('profit_factor'))} vs {_fmt_num(ctrl_is.get('profit_factor'))}.
OOS (report-only) Avg PnL % {_fmt_pct(eod_oos.get('avg_pnl_pct'))} vs control {_fmt_pct(ctrl_oos.get('avg_pnl_pct'))}.
Verdict: <strong>{_esc(verdicts.get(EOD_ARM, ''))}</strong>.</p>
<p><strong>1-minute 15:30 cutoff.</strong> Local Yahoo 1m covers {_esc(str(m1_stats.get('tape_min')))} → {_esc(str(m1_stats.get('tape_max')))}.
{_fmt_int(m1_stats.get('n_control_with_1m_day'))} of {_fmt_int(n_control)} parent trigger dates have a 1m Regular Trading Hours (RTH) day
({_fmt_pct(m1_stats.get('pct_control_with_1m_day'))}); {_fmt_int(m1_stats.get('n_entered'))} entered at or before 15:30 ET.
Missing dates are in the coverage table — not dropped. There is <em>no</em> in-sample 1m tape before 2024.
Verdict: <strong>{_esc(verdicts.get(M1_ARM, ''))}</strong>.</p>
<p><strong>Ann ROR warning.</strong> Flattening in one session turns capital every day. Annualized rate of return (Ann ROR)
will look loud or empty next to a 50-day hold even when average Profit and Loss (PnL) % is worse. Judge Avg PnL %, win %,
profit factor, and Max drawdown (DD) — not Ann ROR as a rescue. Total / sheet PnL $ omitted from the table.</p>
</div>

<h2>Arms (one change = session identity)</h2>
<ul class="meta">
<li><code>{CONTROL_ARM}</code> — {_esc(ARM_NOTES[CONTROL_ARM])}</li>
<li><code>{EOD_ARM}</code> — {_esc(ARM_NOTES[EOD_ARM])}</li>
<li><code>{M1_ARM}</code> — {_esc(ARM_NOTES[M1_ARM])}</li>
</ul>
<p class="small">$10,000 sheet notional / trade; Ann ROR uses that cash; Max DD / Sharpe seed $500,000 on exit-date equity
(no daily curve — Sharpe is closed-exit-date, not √252). Costs = 0. IS = trigger before 2024-01-01;
OOS = 2024+ report-only. Do not retune D / stop / target. Verdicts: {_esc(vtxt)}.</p>
{_book_table_html(show_books, book_cols)}
<h3>Deltas vs <code>{CONTROL_ARM}</code> (same slice)</h3>
<p class="small">Max DD Δ: negative = smaller drawdown (better). Quality over count. HOLD if OOS softens — do not retune.
Ann ROR Δ on the 1-day arms is not a KEEP signal.</p>
{_book_table_html(show_deltas, delta_cols)}

<h2>1-minute coverage (do not silently drop names)</h2>
<p class="small">Every parent trigger date is scored. All { _fmt_int(m1_stats.get('n_symbols')) } control names have a 1m parquet
unless the missing-file count says otherwise (missing files: {_fmt_int(m1_stats.get('n_symbols_missing_1m_file'))}).
The hole is <em>dates</em>, not tickers: Yahoo 1m retention is weeks, not 2010–2026.
Skip-reason rollup first; then every trigger date that actually has a 1m RTH day. Full list: <code>m1_coverage.csv</code>.
Click headers to sort.</p>
{ab2x._table(skip_roll, skip_cols) if not skip_roll.empty else '<p class="small">No coverage rows.</p>'}
<h3>Parent trigger dates that have a 1m RTH day</h3>
{ab2x._table(day_rows, cov_cols) if not day_rows.empty else '<p class="small">No 1m trigger days.</p>'}

<h2>Definitions</h2>
<ul class="meta">
<li><strong>ATH</strong> — all-time high: new closing high in the local sample. Not a 52-week high.</li>
<li><strong>RTH</strong> — Regular Trading Hours, 9:30 a.m.–4:00 p.m. America/New_York (Eastern).</li>
<li><strong>IS / OOS</strong> — in-sample triggers before 2024-01-01; out-of-sample is 2024+ and is report-only.</li>
<li><strong>PnL</strong> — Profit and Loss. Avg PnL % is the headline quality number here.</li>
<li><strong>Ann ROR</strong> — annualized rate of return from the closed-overlay formula (sheet cash × trade count, scaled by hold days).</li>
<li><strong>Max DD</strong> — maximum drawdown on $500,000 exit-date equity.</li>
<li><strong>+2D / 1.5D</strong> — two times the 5% drop (+10% target) and 1.5 times the drop (7.5% stop), frozen from the parent.</li>
</ul>
<p class="meta">Caveats: parent pick after the 2× table (selection labeled); survivorship; dividends ignored; High-tag control is optimistic vs Close;
1m ≠ ticks. See <a href="BASELINE.md">BASELINE.md</a>.</p>
<script>
{spx.SORTABLE_TABLE_SCRIPT}
</script>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    t0 = time.time()
    if PARENT_ID in str(STAMP_DIR) and STAMP_DIR == PARENT_DIR:
        raise RuntimeError("refusing to write into the parent 2x stamp")
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    print("[session] loading parent dsel_2x_entry_s15 trades...", flush=True)
    ctrl = _load_control_trades()
    symbols = sorted(ctrl["symbol"].astype(str).str.upper().unique())
    print(f"[session] control N={len(ctrl)} names={len(symbols)}; loading daily OHLC...", flush=True)
    daily = _daily_close_map(symbols)
    ohlc_dates = [k[1] for k in daily]
    ohlc_start = str(min(ohlc_dates)) if ohlc_dates else ""
    ohlc_end = str(max(ohlc_dates)) if ohlc_dates else ""

    control_trades = _control_rows(ctrl)
    eod_trades, eod_stats = _eod_rows(ctrl, daily)
    print(f"[session] EOD flatten stats {eod_stats}", flush=True)
    print("[session] scoring 1m coverage + 15:30 arm...", flush=True)
    m1_trades, cov, m1_stats = _m1_rows(ctrl)
    _m1_print = {k: v for k, v in m1_stats.items() if k != "skip_counts"}
    print("[session] 1m stats", _m1_print, "skips=", m1_stats.get("skip_counts"), flush=True)

    trades_by_arm = {
        CONTROL_ARM: control_trades,
        EOD_ARM: eod_trades,
        M1_ARM: m1_trades,
    }
    notes = dict(ARM_NOTES)
    book_rows: list[dict[str, Any]] = []
    book_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    arm_order = [CONTROL_ARM, EOD_ARM, M1_ARM]
    for arm in arm_order:
        rows = trades_by_arm.get(arm, [])
        is_tr = [t for t in rows if pd.Timestamp(t["trigger_date"]) < IS_CUT]
        oos_tr = [t for t in rows if pd.Timestamp(t["trigger_date"]) >= IS_CUT]
        for sl, chunk in (("FULL", rows), ("IS", is_tr), ("OOS", oos_tr)):
            rec = ab2x._book_metrics(chunk, label=arm, note=notes.get(arm, ""))
            rec["slice"] = sl
            book_rows.append(rec)
            book_lookup[(arm, sl)] = rec

    verdicts = {
        arm: _verdict_for(arm, book_lookup, eod_stats=eod_stats, m1_stats=m1_stats)
        for arm in arm_order
    }
    for rec in book_rows:
        rec["verdict"] = verdicts.get(str(rec["arm"]), "")

    books = pd.DataFrame(book_rows)
    delta_rows = []
    for rec in book_rows:
        if rec["arm"] == CONTROL_ARM:
            continue
        ctrl_rec = book_lookup.get((CONTROL_ARM, rec["slice"]))
        if not ctrl_rec:
            continue
        delta_rows.append(ab2x._delta_row(rec, ctrl_rec))
        delta_rows[-1]["verdict"] = verdicts.get(str(rec["arm"]), "")
    deltas = pd.DataFrame(delta_rows)

    books.to_csv(STAMP_DIR / "books.csv", index=False)
    deltas.to_csv(STAMP_DIR / "books_delta_vs_ctrl.csv", index=False)
    cov.to_csv(STAMP_DIR / "m1_coverage.csv", index=False)
    all_tr = []
    for arm in arm_order:
        for t in trades_by_arm.get(arm, []):
            row = dict(t)
            row["trigger_date"] = pd.Timestamp(row["trigger_date"]).strftime("%Y-%m-%d")
            row["exit_date"] = pd.Timestamp(row["exit_date"]).strftime("%Y-%m-%d")
            all_tr.append(row)
    pd.DataFrame(all_tr).to_csv(STAMP_DIR / "trades.csv", index=False)
    (STAMP_DIR / "eod_stats.json").write_text(
        json.dumps(eod_stats, indent=2, default=str), encoding="utf-8"
    )
    (STAMP_DIR / "m1_stats.json").write_text(
        json.dumps(m1_stats, indent=2, default=str), encoding="utf-8"
    )

    _write_baseline(
        STAMP_DIR / "BASELINE.md",
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        n_names=len(symbols),
        n_control=int(len(ctrl)),
        eod_stats=eod_stats,
        m1_stats=m1_stats,
        books=books,
        verdicts=verdicts,
    )
    _write_hypothesis(STAMP_DIR / "HYPOTHESIS.md")
    _write_html(
        STAMP_DIR / "report.html",
        books=books,
        deltas=deltas,
        verdicts=verdicts,
        eod_stats=eod_stats,
        m1_stats=m1_stats,
        cov=cov,
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        n_names=len(symbols),
        n_control=int(len(ctrl)),
    )
    (STAMP_DIR / "compare.html").write_text(
        (STAMP_DIR / "report.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    summary = {
        "stamp": STAMP_ID,
        "parent": PARENT_ID,
        "parent_not_overwritten": True,
        "control_arm": CONTROL_ARM,
        "ohlc_start": ohlc_start,
        "ohlc_end": ohlc_end,
        "n_names": len(symbols),
        "n_control": int(len(ctrl)),
        "d_pct": D_PCT,
        "stop_mult": STOP_MULT,
        "target_mode": TARGET_MODE,
        "eod_stats": eod_stats,
        "m1_stats": m1_stats,
        "verdicts": verdicts,
        "elapsed_sec": time.time() - t0,
        "not_dailyrun": True,
        "not_gold": True,
    }
    (STAMP_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"verdicts": verdicts, "eod_stats": eod_stats, "m1_n": m1_stats.get("n_entered")}, indent=2, default=str), flush=True)
    print(f"[session] wrote {STAMP_DIR} in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
