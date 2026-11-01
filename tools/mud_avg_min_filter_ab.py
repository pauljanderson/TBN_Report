#!/usr/bin/env python3
"""MUD entry filter AB: side-specific IS averages as minimums.

Control = unfiltered MUD L5_R1 Closed.
Candidate = keep long (resp. short) only if every listed trigger/size field
is >= that field's in-sample mean on that side.

Writes:
  - thresholds.json / BASELINE.md
  - MUD_Closed_longs_avgmin_*.csv
  - MUD_Closed_shorts_avgmin_*.csv
  - MUD_Closed_filtered_avgmin_*.csv  (both sleeves)
  - compare.html

Usage:
  python tools/mud_avg_min_filter_ab.py
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    filter_html_compare_metric_rows,
    format_money,
    format_money_delta,
    is_excluded_html_compare_label,
    max_dd_pct_from_closed_pnl_by_date,
    sharpe_from_closed_pnl_by_date,
)
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

SRC_STAMP = _PE / "mud_system_L5_R1_20261005"
OUT_STAMP = _PE / "mud_avg_min_filter_ab_20261005"
IS_CUT = date(2024, 1, 1)

LONG_FIELDS = [
    "ATR_PCT_AT_TRIGGER",
    "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
    "LOG10_MARKET_CAP",
    "REL_VOL_AT_TRIGGER",
    "VOLUME_AT_TRIGGER",
]
SHORT_FIELDS = [
    "LOOKBACK_RETURN_PCT",
    "ATR_PCT_AT_TRIGGER",
    "HIGH_52W_AT_TRIGGER",
    "SHORT_PERCENT_OF_FLOAT",
    "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
]

ASK = (
    "OK. let's take the avg of the following and make that the minimum for those "
    "types of entries. Longs: ATR_PCT_AT_TRIGGER, DIST_TO_52W_HIGH_PCT_AT_TRIGGER, "
    "LOG10_MARKET_CAP, REL_VOL_AT_TRIGGER, VOLUME_AT_TRIGGER. Shorts: "
    "LOOKBACK_RETURN_PCT, ATR_PCT_AT_TRIGGER, HIGH_52W_AT_TRIGGER, "
    "SHORT_PERCENT_OF_FLOAT, DIST_TO_52W_HIGH_PCT_AT_TRIGGER. show me full results "
    "compared to the control and give me closed file for longs and closed file for shorts please"
)
PLAIN = (
    "We kept the same Most Up / Most Down (MUD) L5_R1 book as control, then only "
    "allowed long (or short) trades when every listed field was at least that field's "
    "average on in-sample trades of the same side. In-sample means entry before "
    "2024-01-01; out-of-sample is report-only. Separate Closed files list the kept "
    "longs and the kept shorts."
)


def _latest_closed(stamp: Path) -> Path:
    files = sorted(stamp.glob("MUD_Closed_*.csv"))
    # Prefer the full research Closed (largest), skip earlier partials.
    if not files:
        raise SystemExit(f"No MUD_Closed_*.csv in {stamp}")
    return max(files, key=lambda p: p.stat().st_size)


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _fmt_num(v: Any, nd: int = 4) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    if abs(x) >= 1000:
        return f"{x:,.{nd}f}" if nd else f"{x:,.0f}"
    return f"{x:.{nd}f}"


def _fmt_pct(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{float(v):.{nd}f}%"


def _delta(a: Any, b: Any) -> Optional[float]:
    try:
        if a is None or b is None:
            return None
        fa, fb = float(a), float(b)
        if not (math.isfinite(fa) and math.isfinite(fb)):
            return None
        return fb - fa
    except (TypeError, ValueError):
        return None


def _finite_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(x) else x


def _dated_pnls(df: pd.DataFrame) -> list[tuple[Any, float]]:
    """(exit_date, pnl_$) for Max DD / Sharpe — groupby, no per-row dicts."""
    if len(df) == 0:
        return []
    tmp = pd.DataFrame(
        {
            "closed": pd.to_datetime(df["DATE_CLOSED"], errors="coerce"),
            "pnl_d": pd.to_numeric(df["PNL_DOLLARS"], errors="coerce"),
        }
    ).dropna()
    if tmp.empty:
        return []
    g = tmp.groupby(tmp["closed"].dt.date, sort=True)["pnl_d"].sum()
    return [(d, float(v)) for d, v in g.items() if math.isfinite(v)]


def _capital_overlay(df: pd.DataFrame, *, cash: Optional[float]) -> dict[str, Any]:
    """Ann ROR (house) + Max DD + Sharpe from Closed columns."""
    if len(df) == 0:
        return {
            "ann_ror": None,
            "max_dd": None,
            "calmar": None,
            "sharpe": None,
            "note": "no trades",
            "sharpe_source": "",
            "cash": cash,
        }
    pnl_d = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    days = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    notional = (
        pd.to_numeric(df["ENTRY_NOTIONAL"], errors="coerce")
        if "ENTRY_NOTIONAL" in df.columns
        else pd.Series(dtype=float)
    )
    if cash is None:
        cash = float(notional.mean()) if notional.notna().any() else None
    n = int(len(df))
    total_pnl = float(pnl_d.sum()) if pnl_d.notna().any() else 0.0
    days_ok = days[days > 0]
    avg_days = float(days_ok.mean()) if len(days_ok) else 0.0
    ann = None
    if cash and cash > 0 and n > 0 and avg_days > 0:
        ann = ann_ror_from_closed(
            total_pnl=total_pnl,
            n_trades=n,
            avg_days_held=avg_days,
            brt_cash=float(cash),
        )
    dated = _dated_pnls(df)
    max_dd = max_dd_pct_from_closed_pnl_by_date(
        dated, initial_account=DEFAULT_INITIAL_ACCOUNT
    )
    sharpe = sharpe_from_closed_pnl_by_date(
        dated, initial_account=DEFAULT_INITIAL_ACCOUNT
    )
    calmar = None
    if ann is not None and max_dd is not None and abs(max_dd) > 1e-12:
        calmar = float(ann) / abs(float(max_dd))
    return {
        "ann_ror": _finite_or_none(ann),
        "max_dd": _finite_or_none(max_dd),
        "calmar": _finite_or_none(calmar),
        "sharpe": _finite_or_none(sharpe),
        "note": "",
        "sharpe_source": "closed_exit_date_equity:rf0:obs_per_year" if sharpe is not None else "",
        "cash": cash,
    }


def _book_stats(df: pd.DataFrame, *, cash: Optional[float] = None) -> dict[str, Any]:
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "win_pct": None,
        "avg_pnl_pct": None,
        "avg_pnl_pct_wo_max": None,
        "expectancy_pct": None,
        "expectancy_d": None,
        "avg_win_pct": None,
        "avg_loss_pct": None,
        "wl_count": None,
        "wl_dollars": None,
        "profit_factor": None,
        "ann_ror": None,
        "ann_ror_is": None,
        "ann_ror_oos": None,
        "max_dd": None,
        "calmar": None,
        "sharpe": None,
        "ppcd": None,
        "capital_days": None,
        "avg_days": None,
        "median_days": None,
        "p90_days": None,
        "losing_streak": None,
        "symbols": 0,
        "cash": None,
        "total_pnl_d": None,
        "exit_mix": {},
        "note": "no trades",
        "sharpe_source": "",
    }
    if df is None or len(df) == 0:
        return empty

    pnl = pd.to_numeric(df["PNL_PCT"], errors="coerce")
    pnl_d = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    days = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    notional = (
        pd.to_numeric(df["ENTRY_NOTIONAL"], errors="coerce")
        if "ENTRY_NOTIONAL" in df.columns
        else pd.Series(dtype=float)
    )
    n = int(len(df))
    wins_m = pnl > 0
    losses_m = pnl < 0
    wins = int(wins_m.sum())
    losses = int(losses_m.sum())
    win_pct = 100.0 * wins / n if n else None
    avg_pnl = float(pnl.mean()) if pnl.notna().any() else None
    if pnl.notna().sum() > 1:
        wo = pnl.dropna()
        avg_wo = float(wo.drop(wo.idxmax()).mean()) if len(wo) > 1 else float(wo.mean())
    else:
        avg_wo = avg_pnl
    avg_win = float(pnl[wins_m].mean()) if wins else None
    avg_loss = float(pnl[losses_m].mean()) if losses else None
    wl_count = (wins / losses) if losses else (float(wins) if wins else None)
    sum_w = float(pnl_d[pnl_d > 0].sum()) if pnl_d.notna().any() else 0.0
    sum_l = float((-pnl_d[pnl_d < 0]).sum()) if pnl_d.notna().any() else 0.0
    wl_d = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else None)
    pf = wl_d
    total_pnl = float(pnl_d.sum()) if pnl_d.notna().any() else 0.0
    days_ok = days[days > 0]
    capital_days = float(days_ok.sum()) if len(days_ok) else 0.0
    avg_days = float(days_ok.mean()) if len(days_ok) else None
    median_days = float(days_ok.median()) if len(days_ok) else None
    p90_days = float(days_ok.quantile(0.9)) if len(days_ok) else None
    ppcd = (total_pnl / capital_days) if capital_days > 0 else None
    if cash is None:
        cash = float(notional.mean()) if notional.notna().any() else None

    # losing streak (vectorized run-length on chronological PnL)
    ordered_pnl = pd.to_numeric(
        df.sort_values("DATE_OPENED")["PNL_PCT"], errors="coerce"
    ).to_numpy()
    max_streak = 0
    streak = 0
    for v in ordered_pnl:
        if not np.isfinite(v):
            continue
        if v < 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0

    exit_mix: dict[str, int] = {}
    if "EXIT_TYPE" in df.columns:
        for k, c in df["EXIT_TYPE"].fillna("").astype(str).value_counts().items():
            exit_mix[str(k) or "(blank)"] = int(c)

    overlay = _capital_overlay(df, cash=cash)
    cash = overlay["cash"]
    opened_ts = pd.to_datetime(df["DATE_OPENED"], errors="coerce")
    ann_is = _capital_overlay(df[opened_ts < pd.Timestamp(IS_CUT)], cash=None)["ann_ror"]
    ann_oos = _capital_overlay(df[opened_ts >= pd.Timestamp(IS_CUT)], cash=None)["ann_ror"]

    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_pct": win_pct,
        "avg_pnl_pct": avg_pnl,
        "avg_pnl_pct_wo_max": avg_wo,
        "expectancy_pct": avg_pnl,
        "expectancy_d": float(pnl_d.mean()) if pnl_d.notna().any() else None,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "wl_count": wl_count,
        "wl_dollars": wl_d,
        "profit_factor": pf,
        "ann_ror": overlay["ann_ror"],
        "ann_ror_is": ann_is,
        "ann_ror_oos": ann_oos,
        "max_dd": overlay["max_dd"],
        "calmar": overlay["calmar"],
        "sharpe": overlay["sharpe"],
        "ppcd": ppcd,
        "capital_days": capital_days,
        "avg_days": avg_days,
        "median_days": median_days,
        "p90_days": p90_days,
        "losing_streak": max_streak,
        "symbols": int(df["SYMBOL"].nunique()) if "SYMBOL" in df.columns else 0,
        "cash": cash,
        "total_pnl_d": total_pnl,
        "exit_mix": exit_mix,
        "note": overlay["note"],
        "sharpe_source": overlay["sharpe_source"],
    }


def _pass_mins(df: pd.DataFrame, fields: list[str], thresholds: dict[str, float]) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for f in fields:
        thr = thresholds[f]
        col = pd.to_numeric(df[f], errors="coerce")
        mask &= col.notna() & (col >= thr)
    return mask


def main() -> int:
    closed_path = _latest_closed(SRC_STAMP)
    out = OUT_STAMP
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%y%m%d%H%M%S")

    print(f"Reading {closed_path} …", flush=True)
    df = pd.read_csv(closed_path, low_memory=False)
    df["DATE_OPENED"] = pd.to_datetime(df["DATE_OPENED"], errors="coerce")
    df["DATE_CLOSED"] = pd.to_datetime(df["DATE_CLOSED"], errors="coerce")
    side = df["SIDE"].astype(str).str.lower()
    df["_side"] = side
    mcap = pd.to_numeric(df.get("MARKET_CAP"), errors="coerce")
    df["LOG10_MARKET_CAP"] = np.where(
        (mcap > 0) & np.isfinite(mcap), np.log10(mcap), np.nan
    )

    is_mask = df["DATE_OPENED"] < pd.Timestamp(IS_CUT)
    long_is = df[is_mask & (side == "long")]
    short_is = df[is_mask & (side == "short")]

    long_thr: dict[str, float] = {}
    short_thr: dict[str, float] = {}
    for f in LONG_FIELDS:
        s = pd.to_numeric(long_is[f], errors="coerce").dropna()
        if len(s) < 30:
            raise SystemExit(f"Not enough IS long samples for {f}: {len(s)}")
        long_thr[f] = float(s.mean())
    for f in SHORT_FIELDS:
        s = pd.to_numeric(short_is[f], errors="coerce").dropna()
        if len(s) < 30:
            raise SystemExit(f"Not enough IS short samples for {f}: {len(s)}")
        short_thr[f] = float(s.mean())

    long_all = df[side == "long"]
    short_all = df[side == "short"]
    long_keep = long_all[_pass_mins(long_all, LONG_FIELDS, long_thr)]
    short_keep = short_all[_pass_mins(short_all, SHORT_FIELDS, short_thr)]
    filtered = pd.concat([long_keep, short_keep], axis=0).sort_values(
        ["DATE_OPENED", "SYMBOL"]
    )

    # Drop helper cols from Closed exports
    drop_cols = [c for c in ("_side", "LOG10_MARKET_CAP") if c in long_keep.columns]
    # Keep LOG10_MARKET_CAP on exports — useful; only drop _side
    drop_cols = ["_side"]

    def _write_closed(path: Path, frame: pd.DataFrame) -> None:
        out_df = frame.drop(columns=[c for c in drop_cols if c in frame.columns], errors="ignore")
        # ensure LOG10 present for longs file convenience
        if "LOG10_MARKET_CAP" not in out_df.columns and "MARKET_CAP" in out_df.columns:
            mc = pd.to_numeric(out_df["MARKET_CAP"], errors="coerce")
            out_df["LOG10_MARKET_CAP"] = np.where(
                (mc > 0) & np.isfinite(mc), np.log10(mc), np.nan
            )
        out_df.to_csv(path, index=False)
        print(f"Wrote {path} ({len(out_df):,} rows)", flush=True)

    longs_path = out / f"MUD_Closed_longs_avgmin_{stamp}.csv"
    shorts_path = out / f"MUD_Closed_shorts_avgmin_{stamp}.csv"
    filt_path = out / f"MUD_Closed_filtered_avgmin_{stamp}.csv"
    _write_closed(longs_path, long_keep)
    _write_closed(shorts_path, short_keep)
    _write_closed(filt_path, filtered)

    arms = {
        "Control (full)": df,
        "Filtered (both sleeves)": filtered,
        "Control longs": long_all,
        "Filtered longs": long_keep,
        "Control shorts": short_all,
        "Filtered shorts": short_keep,
    }
    stats = {name: _book_stats(frame) for name, frame in arms.items()}

    thr_payload = {
        "source_closed": str(closed_path),
        "is_cut": str(IS_CUT),
        "threshold_source": "IS mean by side (entry_date < 2024-01-01)",
        "long_fields": LONG_FIELDS,
        "short_fields": SHORT_FIELDS,
        "long_thresholds": long_thr,
        "short_thresholds": short_thr,
        "n_control": int(len(df)),
        "n_filtered": int(len(filtered)),
        "n_long_control": int(len(long_all)),
        "n_long_filtered": int(len(long_keep)),
        "n_short_control": int(len(short_all)),
        "n_short_filtered": int(len(short_keep)),
        "selection_bias": (
            "Fields chosen after correlation inspect on the same Closed book; "
            "thresholds = IS means. In-sample selection — research only."
        ),
    }
    (out / "thresholds.json").write_text(json.dumps(thr_payload, indent=2), encoding="utf-8")

    baseline = f"""# MUD avg-min entry filter AB

## What you asked

{ASK}

## In plain English

{PLAIN}

## Freeze

- Control: MUD L5_R1 unfiltered Closed (`{closed_path.name}`)
- Candidate: AND of field >= IS-side mean for listed fields (side-specific)
- Thresholds frozen from **IS only** (`entry_date < 2024-01-01`); OOS report-only
- Lookback 5 trading days / rebalance 1 trading day (unchanged)
- Research only — not gold, not DailyRun

## Long minimums (IS mean)

| Field | Min |
|-------|-----|
{chr(10).join(f"| `{k}` | {v:.6g} |" for k, v in long_thr.items())}

## Short minimums (IS mean)

| Field | Min |
|-------|-----|
{chr(10).join(f"| `{k}` | {v:.6g} |" for k, v in short_thr.items())}

## Counts

| Arm | N |
|-----|---|
| Control full | {len(df):,} |
| Filtered both | {len(filtered):,} |
| Control longs | {len(long_all):,} |
| Filtered longs | {len(long_keep):,} |
| Control shorts | {len(short_all):,} |
| Filtered shorts | {len(short_keep):,} |

## Selection bias

Fields were picked after looking at the correlation table on this same book.
Thresholds are IS averages. Label: **in-sample selection / research candidate**.
Do not retune on OOS.

## Closed outputs

- Longs: `{longs_path.name}`
- Shorts: `{shorts_path.name}`
- Combined filtered: `{filt_path.name}`

## Metrics note

Annualized rate of return (Ann ROR) uses `compare_format.overlay_ann_ror_max_dd` /
`ann_ror_from_closed` with `brt_cash` = mean `ENTRY_NOTIONAL` on that arm/slice.
Max DD / Sharpe from exit-date equity seeded at $500,000.
"""
    (out / "BASELINE.md").write_text(baseline, encoding="utf-8")

    # --- HTML ---
    def metric_rows(ctrl: dict[str, Any], cand: dict[str, Any]) -> list[tuple[str, str, str, str]]:
        rows: list[tuple[str, str, str, str, str]] = []

        def add(label: str, a: Any, b: Any, *, kind: str = "num", fmt: str = "num") -> None:
            if is_excluded_html_compare_label(label):
                return
            if fmt == "money":
                sa, sb = format_money(a), format_money(b)
                d = _delta(a, b)
                sd = format_money_delta(d) if d is not None else "—"
            elif fmt == "pct":
                sa, sb = _fmt_pct(a), _fmt_pct(b)
                d = _delta(a, b)
                sd = "—" if d is None else f"{d:+.2f} pp"
            elif fmt == "ann":
                sa, sb = _fmt_pct(a), _fmt_pct(b)
                d = _delta(a, b)
                sd = "—" if d is None else f"{d:+.2f} pp"
            elif fmt == "int":
                sa = "—" if a is None else f"{int(a):,}"
                sb = "—" if b is None else f"{int(b):,}"
                d = _delta(a, b)
                sd = "—" if d is None else f"{d:+,.0f}"
            else:
                sa, sb = _fmt_num(a, 4), _fmt_num(b, 4)
                d = _delta(a, b)
                sd = "—" if d is None else f"{d:+.4f}"
            rows.append((label, sa, sb, sd, kind))

        add("Universe size", ctrl["symbols"], cand["symbols"], fmt="int", kind="num")
        add("Total trades", ctrl["n"], cand["n"], fmt="int", kind="num")
        add("Wins", ctrl["wins"], cand["wins"], fmt="int", kind="num")
        add("Losses", ctrl["losses"], cand["losses"], fmt="int", kind="num")
        add("Win %", ctrl["win_pct"], cand["win_pct"], fmt="pct", kind="num")
        add("Avg PnL %", ctrl["avg_pnl_pct"], cand["avg_pnl_pct"], fmt="num", kind="num")
        add(
            "Book AVG_PNL_PCT_WO_MAX",
            ctrl["avg_pnl_pct_wo_max"],
            cand["avg_pnl_pct_wo_max"],
            fmt="num",
            kind="num",
        )
        add("Expectancy $", ctrl["expectancy_d"], cand["expectancy_d"], fmt="money", kind="num")
        add("Expectancy %", ctrl["expectancy_pct"], cand["expectancy_pct"], fmt="num", kind="num")
        add("Avg win %", ctrl["avg_win_pct"], cand["avg_win_pct"], fmt="num", kind="num")
        add("Avg loss %", ctrl["avg_loss_pct"], cand["avg_loss_pct"], fmt="num", kind="num")
        add("Win/Loss ratio (count)", ctrl["wl_count"], cand["wl_count"], fmt="num", kind="num")
        add("Win/Loss ratio $", ctrl["wl_dollars"], cand["wl_dollars"], fmt="num", kind="num")
        add("Profit factor", ctrl["profit_factor"], cand["profit_factor"], fmt="num", kind="num")
        add("Ann ROR %", ctrl["ann_ror"], cand["ann_ror"], fmt="ann", kind="num")
        add("Ann ROR % (IS)", ctrl["ann_ror_is"], cand["ann_ror_is"], fmt="ann", kind="num")
        add("Ann ROR % (OOS)", ctrl["ann_ror_oos"], cand["ann_ror_oos"], fmt="ann", kind="num")
        add("Max DD %", ctrl["max_dd"], cand["max_dd"], fmt="pct", kind="num")
        add("Calmar", ctrl["calmar"], cand["calmar"], fmt="num", kind="num")
        add("Sharpe", ctrl["sharpe"], cand["sharpe"], fmt="num", kind="num")
        add("Profit per capital day", ctrl["ppcd"], cand["ppcd"], fmt="money", kind="num")
        add("Capital days", ctrl["capital_days"], cand["capital_days"], fmt="num", kind="num")
        add("Avg days held", ctrl["avg_days"], cand["avg_days"], fmt="num", kind="num")
        add("Median days held", ctrl["median_days"], cand["median_days"], fmt="num", kind="num")
        add("P90 days held", ctrl["p90_days"], cand["p90_days"], fmt="num", kind="num")
        add("Losing streak", ctrl["losing_streak"], cand["losing_streak"], fmt="int", kind="num")
        add("Slot cash (mean ENTRY_NOTIONAL)", ctrl["cash"], cand["cash"], fmt="money", kind="num")
        # filter excluded
        cleaned = filter_html_compare_metric_rows(
            [(r[0], r[1], r[2], r[3]) for r in rows], label_index=0
        )
        # restore kind as num for all
        return [(a, b, c, d) for a, b, c, d in cleaned]

    def compare_table(title: str, ctrl_name: str, cand_name: str) -> str:
        rows = metric_rows(stats[ctrl_name], stats[cand_name])
        ths = "".join(
            [
                _th("Metric", "text"),
                _th(ctrl_name, "num"),
                _th(cand_name, "num"),
                _th("Δ (cand − ctrl)", "num"),
            ]
        )
        body = []
        for label, a, b, d in rows:
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(label)}</td>"
                f"<td>{html_mod.escape(a)}</td>"
                f"<td>{html_mod.escape(b)}</td>"
                f"<td>{html_mod.escape(d)}</td>"
                "</tr>"
            )
        return (
            f"<h2>{html_mod.escape(title)}</h2>"
            f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
            f"<thead><tr>{ths}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )

    def thr_table(title: str, thr: dict[str, float], fields: list[str], n_is: int) -> str:
        ths = "".join([_th("Field", "text"), _th("IS mean (= min)", "num"), _th("When", "text")])
        body = []
        for f in fields:
            when = (
                "trigger"
                if "TRIGGER" in f
                else ("other" if f in ("LOOKBACK_RETURN_PCT", "LOG10_MARKET_CAP", "SHORT_PERCENT_OF_FLOAT") else "entry")
            )
            if f == "LOG10_MARKET_CAP":
                when = "fund (log10 market cap)"
            if f == "SHORT_PERCENT_OF_FLOAT":
                when = "fund"
            if f == "LOOKBACK_RETURN_PCT":
                when = "rank input"
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(f)}</td>"
                f"<td>{thr[f]:.6g}</td>"
                f"<td>{html_mod.escape(when)}</td>"
                "</tr>"
            )
        return (
            f"<h3>{html_mod.escape(title)} (IS N={n_is:,})</h3>"
            f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
            f"<thead><tr>{ths}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )

    def exit_table(name: str) -> str:
        mix = stats[name]["exit_mix"]
        if not mix:
            return f"<p>{html_mod.escape(name)}: no EXIT_TYPE mix.</p>"
        n = stats[name]["n"] or 1
        ths = "".join([_th("EXIT_TYPE", "text"), _th("Count", "num"), _th("%", "num")])
        body = []
        for k, c in sorted(mix.items(), key=lambda kv: -kv[1]):
            body.append(
                f"<tr><td>{html_mod.escape(k)}</td><td>{c:,}</td>"
                f"<td>{100.0 * c / n:.2f}%</td></tr>"
            )
        return (
            f"<h3>Exit mix — {html_mod.escape(name)}</h3>"
            f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
            f"<thead><tr>{ths}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )

    c_full = stats["Control (full)"]
    f_full = stats["Filtered (both sleeves)"]
    verdict_bits = []
    if f_full["avg_pnl_pct"] is not None and c_full["avg_pnl_pct"] is not None:
        if f_full["avg_pnl_pct"] > c_full["avg_pnl_pct"] and (f_full["n"] or 0) > 0:
            verdict_bits.append("Avg PnL % up vs control")
        elif f_full["avg_pnl_pct"] < c_full["avg_pnl_pct"]:
            verdict_bits.append("Avg PnL % down vs control")
        else:
            verdict_bits.append("Avg PnL % flat")
    if f_full["ann_ror_oos"] is not None and c_full["ann_ror_oos"] is not None:
        if f_full["ann_ror_oos"] < c_full["ann_ror_oos"]:
            verdict_bits.append("OOS Ann ROR softer → HOLD (do not retune OOS)")
        elif f_full["ann_ror_oos"] > c_full["ann_ror_oos"]:
            verdict_bits.append("OOS Ann ROR higher (still research-only; selection bias labeled)")
    keep = "HOLD / research candidate"
    if (
        f_full["avg_pnl_pct"] is not None
        and c_full["avg_pnl_pct"] is not None
        and f_full["ann_ror_is"] is not None
        and c_full["ann_ror_is"] is not None
        and f_full["avg_pnl_pct"] > c_full["avg_pnl_pct"]
        and f_full["ann_ror_is"] > c_full["ann_ror_is"]
        and (f_full["n"] or 0) >= 0.2 * (c_full["n"] or 1)
    ):
        keep = "LEAN KEEP (research only — not gold / not DailyRun)"

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD avg-min filter AB</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.2rem;line-height:1.45;color:#222;max-width:1100px}}
.callout{{background:#f4f7fb;border-left:4px solid #2a6;padding:.8rem 1rem;margin:1rem 0}}
.callout.warn{{background:#f7efe0;border-left-color:#8a5a12}}
code{{font-family:ui-monospace,Consolas,monospace;font-size:.92em}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>MUD — IS-average minimums on long/short entries vs control</h1>
<div class="callout"><h2>What you asked</h2><p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2><p>{html_mod.escape(PLAIN)}</p></div>
<div class="callout warn"><strong>Verdict:</strong> {html_mod.escape(keep)}.
{" ".join(html_mod.escape(x) for x in verdict_bits)}.
Fields chosen after the correlation look = in-sample selection. OOS is report-only.</div>
<p>Source Closed: <code>{html_mod.escape(str(closed_path))}</code>.
Thresholds = side-specific IS means (<code>entry_date &lt; 2024-01-01</code>), AND across listed fields.
Slot cash for Ann ROR = mean <code>ENTRY_NOTIONAL</code> on that arm. Max DD / Sharpe: exit-date equity @ $500,000.
Click column headers to sort.</p>
<h2>Frozen minimums</h2>
{thr_table("Longs", long_thr, LONG_FIELDS, len(long_is))}
{thr_table("Shorts", short_thr, SHORT_FIELDS, len(short_is))}
<p>Kept longs: <strong>{len(long_keep):,}</strong> / {len(long_all):,}
({100.0 * len(long_keep) / max(len(long_all), 1):.1f}%).
Kept shorts: <strong>{len(short_keep):,}</strong> / {len(short_all):,}
({100.0 * len(short_keep) / max(len(short_all), 1):.1f}%).</p>
{compare_table("Full book — control vs filtered (both sleeves)", "Control (full)", "Filtered (both sleeves)")}
{compare_table("Long sleeve only", "Control longs", "Filtered longs")}
{compare_table("Short sleeve only", "Control shorts", "Filtered shorts")}
<h2>Exit mix</h2>
{exit_table("Control (full)")}
{exit_table("Filtered (both sleeves)")}
<h2>Closed files</h2>
<ul>
<li>Longs: <code>{html_mod.escape(longs_path.name)}</code></li>
<li>Shorts: <code>{html_mod.escape(shorts_path.name)}</code></li>
<li>Combined filtered: <code>{html_mod.escape(filt_path.name)}</code></li>
</ul>
<p>Research only. Not gold. Not DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = out / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {html_path}", flush=True)
    print(f"Wrote {out / 'thresholds.json'}", flush=True)
    print(f"Wrote {out / 'BASELINE.md'}", flush=True)

    # quick console summary
    for name in (
        "Control (full)",
        "Filtered (both sleeves)",
        "Control longs",
        "Filtered longs",
        "Control shorts",
        "Filtered shorts",
    ):
        s = stats[name]
        print(
            f"{name}: N={s['n']:,} WR={_fmt_pct(s['win_pct'])} "
            f"AvgPnL%={_fmt_num(s['avg_pnl_pct'], 4)} "
            f"AnnROR={_fmt_pct(s['ann_ror'])} "
            f"IS={_fmt_pct(s['ann_ror_is'])} OOS={_fmt_pct(s['ann_ror_oos'])}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
