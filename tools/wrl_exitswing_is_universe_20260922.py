#!/usr/bin/env python3
"""Adopt WRL EXIT_swing freeze + full-universe IS symbol summary — 2026-09-22.

Weekly Range / Swing (WRL). Research only. Not gold. Not DailyRun.

Parent: ``drive/paul_experiments/wrl_firstpass_ab_20260922/`` control
+ one change: ``wrl_target_mode=swing`` (EXIT_swing).

min-zone OFF. Cooldown off (do not wire cooldown_until). Stop at swing low.
Scale 50/50 leftover unused under swing mode.

Full run = production WRL universe (published Closed pin or rocket_wrl ALL).
IS only for the name-pick table: entry_date < 2024-01-01.
OOS is a one-line report-only book headline. Do not rank names from OOS.
Do not retune on OOS. Do not pick the universe.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
    parse_number,
)
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS  # noqa: E402
from rocket_wrl import (  # noqa: E402
    WRL_CLOSED_HEADER,
    WrlConfig,
    _run_wrl_symbol_tasks,
    _wrl_cfg_dict,
    write_wrl_outputs,
)
from tbn_host_sizing import HostSizingConfig, apply_host_dollar_scale  # noqa: E402

STAMP_DIR = REPO / "drive" / "paul_experiments" / "wrl_exitswing_is_universe_20260922"
DATA_DIR = REPO / "data" / "newdata" / "data"
PUBLISHED_CLOSED = REPO / "drive" / "WRL_Closed_260906140457.csv"
DRIVE_SUMMARY_COPY = REPO / "drive" / "WRL_IS_SymbolSummary_exitswing.csv"
PARENT_STAMP = "wrl_firstpass_ab_20260922"
IS_CUT = date(2024, 1, 1)
SHEET_CASH = 47_500.0
INIT = 500_000.0
BATCH = 250

ORIGINAL_REQUEST = (
    "wait. scratch that. let's adopt exit_swing and give me the summary for that please"
)

# House control leftover + the one adopted knob.
ADOPTED_OVERRIDES: dict[str, Any] = {"wrl_target_mode": "swing"}


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _parse_ymd(val: Any) -> Optional[date]:
    s = str(val or "").strip().replace("-", "")
    if len(s) < 8 or not s[:8].isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _f(x: Any, default: float = 0.0) -> float:
    n = parse_number(x)
    return default if n is None else float(n)


def _host_cfg() -> HostSizingConfig:
    return HostSizingConfig(
        brt_cash=SHEET_CASH,
        initial_capital=INIT,
        aggressive_max_multiple=2.0,
        margin_utilization=0.6,
        max_positions=0,
        aggressive=True,
        aggressive_margin_interest=0.10,
        aggressive_avg_positions=0.0,
        aggressive_sizing_equity_cap=10.0,
        aggressive_sell="false",
        equity_fast_aggressive=True,
    )


def _list_data_symbols() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    out: list[str] = []
    for p in DATA_DIR.glob("*.csv"):
        stem = p.stem.strip().upper()
        if not stem or stem == "SPY":
            continue
        out.append(stem)
    return sorted(set(out))


def _published_closed_symbols() -> list[str]:
    if not PUBLISHED_CLOSED.is_file():
        return []
    seen: set[str] = set()
    with PUBLISHED_CLOSED.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            s = str(row.get("SYMBOL") or "").strip().upper()
            if s:
                seen.add(s)
    return sorted(seen)


def _resolve_universe() -> tuple[list[str], str]:
    data_syms = set(_list_data_symbols())
    pin_syms = _published_closed_symbols()
    if pin_syms:
        kept = [s for s in pin_syms if s in data_syms]
        missing = [s for s in pin_syms if s not in data_syms]
        note = (
            f"Production Closed pin {PUBLISHED_CLOSED.name} "
            f"({len(pin_syms)} symbols; {len(kept)} with local OHLC"
        )
        if missing:
            note += f"; {len(missing)} missing on disk"
        note += "). Same universe as latest rocket_wrl full run — not Paul Twenty."
        return kept, note
    kept = sorted(data_syms)
    return (
        kept,
        "Published Closed pin missing; using rocket_wrl default ALL "
        f"({len(kept)} CSVs in data/newdata/data, SPY skipped).",
    )


def _load_symbol(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    if "Date" not in df.columns:
        return None
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").set_index("Date")
    for c in ("Open", "High", "Low", "Close"):
        if c not in df.columns:
            return None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df if len(df) >= 40 else None


def _adv20_from_frame(df: pd.DataFrame) -> Optional[float]:
    if df is None or "Volume" not in df.columns or len(df) < 20:
        return None
    vol = pd.to_numeric(df["Volume"], errors="coerce").dropna()
    if len(vol) < 20:
        return None
    v = float(vol.iloc[-20:].mean())
    return v if math.isfinite(v) and v > 0 else None


def _load_mcap_cache() -> dict[str, Optional[float]]:
    path = REPO / "yfinance_cache.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Optional[float]] = {}
    for k, rec in raw.items():
        sym = str(k).strip().upper()
        if not isinstance(rec, dict):
            continue
        mc = rec.get("market_cap")
        if mc is None:
            mc = rec.get("marketCap")
        n = parse_number(mc)
        out[sym] = float(n) if n is not None and n > 0 else None
    return out


def _chunks(xs: list[str], n: int) -> list[list[str]]:
    return [xs[i : i + n] for i in range(0, len(xs), n)]


def _run_full(
    symbols: list[str],
    workers: int,
) -> tuple[list[Any], list[dict[str, Any]], dict[str, Optional[float]], list[str]]:
    cfg = WrlConfig()
    for k, v in ADOPTED_OVERRIDES.items():
        setattr(cfg, k, v)
    assert str(cfg.wrl_target_mode).strip().lower() == "swing"
    assert float(cfg.wrl_min_zone_pct or 0.0) == 0.0
    assert int(cfg.symbol_reentry_cooldown_days or 0) == 0
    cfg_d = _wrl_cfg_dict(cfg)
    closed: list[Any] = []
    opens: list[dict[str, Any]] = []
    adv: dict[str, Optional[float]] = {}
    skipped: list[str] = []
    t0 = time.time()
    batches = _chunks(symbols, BATCH)
    for bi, batch in enumerate(batches, 1):
        frames: dict[str, pd.DataFrame] = {}
        for sym in batch:
            df = _load_symbol(sym)
            if df is None:
                skipped.append(sym)
                continue
            frames[sym] = df
            adv[sym] = _adv20_from_frame(df)
        tasks = [(sym, frames[sym], cfg_d) for sym in batch if sym in frames]
        print(
            f"[WRL-SWING] batch {bi}/{len(batches)}: {len(tasks)} symbols "
            f"({time.time() - t0:.0f}s elapsed)",
            flush=True,
        )
        if not tasks:
            continue
        results = _run_wrl_symbol_tasks(tasks, workers)
        for res in results:
            if res.skip_reason:
                skipped.append(res.symbol)
                continue
            closed.extend(res.closed)
            opens.extend(res.open_rows)
        del frames
        del tasks
    closed.sort(key=lambda r: (r.date_opened, r.symbol))
    print(
        f"[WRL-SWING] engine done: {len(closed)} closed / {len(opens)} open "
        f"in {time.time() - t0:.1f}s; skipped={len(skipped)}",
        flush=True,
    )
    return closed, opens, adv, skipped


def _write_closed_csv(path: Path, closed: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WRL_CLOSED_HEADER)
        for r in closed:
            w.writerow(r.to_csv_row())


def _row_from_engine(r: Any) -> dict[str, Any]:
    opened = _parse_ymd(getattr(r, "date_opened", ""))
    closed = _parse_ymd(getattr(r, "date_closed", ""))
    entry = float(getattr(r, "entry_price", 0.0) or 0.0)
    stop = float(getattr(r, "stop_price", 0.0) or 0.0)
    pnl = float(getattr(r, "pnl_pct", 0.0) or 0.0)
    risk_pct = ((entry - stop) / entry * 100.0) if entry > 0 and stop < entry else None
    r_mult = (pnl / risk_pct) if risk_pct and risk_pct > 1e-9 else None
    return {
        "symbol": str(getattr(r, "symbol", "")).upper(),
        "opened": opened,
        "closed": closed,
        "pnl": pnl,
        "pnl_d": float(getattr(r, "pnl_dollars", 0.0) or 0.0),
        "days": float(getattr(r, "days_held", 0) or 0),
        "exit": str(getattr(r, "exit_type", "") or "").strip().upper(),
        "entry": entry,
        "stop": stop,
        "r_mult": r_mult,
        "win": pnl > 0,
    }


def _row_from_csv(row: dict[str, Any]) -> dict[str, Any]:
    opened = _parse_ymd(row.get("DATE_OPENED") or row.get("DATE OPENED"))
    closed = _parse_ymd(row.get("DATE_CLOSED") or row.get("DATE CLOSED"))
    entry = _f(row.get("ENTRY_PRICE") or row.get("ENTRY PRICE"))
    stop = _f(row.get("STOP_PRICE") or row.get("STOP PRICE"))
    pnl = _f(row.get("PNL_PCT") if row.get("PNL_PCT") not in (None, "") else row.get("PNL %"))
    risk_pct = ((entry - stop) / entry * 100.0) if entry > 0 and stop < entry else None
    r_mult = (pnl / risk_pct) if risk_pct and risk_pct > 1e-9 else None
    return {
        "symbol": str(row.get("SYMBOL") or "").upper(),
        "opened": opened,
        "closed": closed,
        "pnl": pnl,
        "pnl_d": _f(row.get("PNL_DOLLARS") or row.get("PNL $") or row.get("PNL")),
        "days": _f(row.get("DAYS_HELD") or row.get("DAYS HELD")),
        "exit": str(row.get("EXIT_TYPE") or row.get("EXIT TYPE") or "").strip().upper(),
        "entry": entry,
        "stop": stop,
        "r_mult": r_mult,
        "win": pnl > 0,
    }


def _load_published_rows() -> list[dict[str, Any]]:
    if not PUBLISHED_CLOSED.is_file():
        return []
    out: list[dict[str, Any]] = []
    with PUBLISHED_CLOSED.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            rec = _row_from_csv(row)
            if rec["symbol"]:
                out.append(rec)
    return out


def _slice_is(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("opened") and r["opened"] < IS_CUT]


def _slice_oos(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("opened") and r["opened"] >= IS_CUT]


def _cum_dd_pct(pnls: list[float]) -> Optional[float]:
    if not pnls:
        return None
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _book(rows: list[dict[str, Any]], *, n_univ: int, cash: float) -> dict[str, Any]:
    n = len(rows)
    pnls = [float(r["pnl"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr = (100.0 * len(wins) / n) if n else 0.0
    avg = (sum(pnls) / n) if n else 0.0
    sum_w = sum(float(r["pnl_d"]) for r in rows if r["pnl_d"] > 0)
    sum_l = abs(sum(float(r["pnl_d"]) for r in rows if r["pnl_d"] < 0))
    pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
    days = [float(r["days"]) for r in rows if r.get("days") is not None]
    rs = [float(r["r_mult"]) for r in rows if r.get("r_mult") is not None]
    ov = overlay_ann_ror_max_dd(
        rows,
        cash=cash,
        initial_account=INIT,
        start_date=None,
        end_date_exclusive=None,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl",
    )
    return {
        "n_univ": n_univ,
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": wr,
        "avg_pnl_pct": avg,
        "avg_r": (sum(rs) / len(rs)) if rs else None,
        "exp_pct": avg,
        "exp_d": (sum(float(r["pnl_d"]) for r in rows) / n) if n else 0.0,
        "pf": pf,
        "sum_pnl_pct": sum(pnls),
        "sum_pnl_d": sum(float(r["pnl_d"]) for r in rows),
        "med_days": statistics.median(days) if days else 0.0,
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "worst": min(pnls) if pnls else None,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "note": ov.get("note") or "",
    }


def _symbol_rows(
    is_rows: list[dict[str, Any]],
    adv: dict[str, Optional[float]],
    mcap: dict[str, Optional[float]],
) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in is_rows:
        if r.get("symbol"):
            by[r["symbol"]].append(r)
    out: list[dict[str, Any]] = []
    for sym in sorted(by):
        recs = by[sym]
        pnls = [float(r["pnl"]) for r in recs]
        wins = [p for p in pnls if p > 0]
        n = len(recs)
        sum_w = sum(float(r["pnl_d"]) for r in recs if r["pnl_d"] > 0)
        sum_l = abs(sum(float(r["pnl_d"]) for r in recs if r["pnl_d"] < 0))
        pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
        days = [float(r["days"]) for r in recs if r.get("days") is not None]
        rs = [float(r["r_mult"]) for r in recs if r.get("r_mult") is not None]
        opened = [r["opened"] for r in recs if r.get("opened")]
        out.append(
            {
                "symbol": sym,
                "n": n,
                "wr": (100.0 * len(wins) / n) if n else 0.0,
                "avg_pnl_pct": (sum(pnls) / n) if n else 0.0,
                "avg_r": (sum(rs) / len(rs)) if rs else None,
                "pf": pf,
                "exp_pct": (sum(pnls) / n) if n else 0.0,
                "sum_pnl_pct": sum(pnls),
                "sum_pnl_d": sum(float(r["pnl_d"]) for r in recs),
                "med_days": statistics.median(days) if days else None,
                "worst": min(pnls) if pnls else None,
                "max_dd_pct": _cum_dd_pct(pnls),
                "first": min(opened) if opened else None,
                "last": max(opened) if opened else None,
                "adv20": adv.get(sym),
                "mcap": mcap.get(sym),
            }
        )
    return out


def _fmt_num(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):.{nd}f}"


def _fmt_int(v: Any) -> str:
    if v is None:
        return "—"
    return f"{int(round(float(v))):,}"


def _fmt_adv(v: Any) -> str:
    if v is None or not math.isfinite(float(v)) or float(v) <= 0:
        return "—"
    return f"{float(v):,.0f}"


def _fmt_mcap(v: Any) -> str:
    if v is None or not math.isfinite(float(v)) or float(v) <= 0:
        return "—"
    n = float(v)
    if n >= 1e12:
        return f"${n / 1e12:.2f}T"
    if n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if n >= 1e6:
        return f"${n / 1e6:.1f}M"
    return format_money(n)


def _fmt_date(d: Any) -> str:
    if d is None:
        return "—"
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def _write_symbol_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "SYMBOL",
        "N_IS",
        "WIN_PCT",
        "AVG_PNL_PCT",
        "AVG_R",
        "PROFIT_FACTOR",
        "EXPECTANCY_PCT",
        "SUM_PNL_PCT",
        "SUM_PNL_DOLLARS",
        "MEDIAN_DAYS_HELD",
        "WORST_TRADE_PCT",
        "MAX_DD_CUM_PNL_PCT",
        "FIRST_IS_ENTRY",
        "LAST_IS_ENTRY",
        "ADV20",
        "MARKET_CAP",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "SYMBOL": r["symbol"],
                    "N_IS": r["n"],
                    "WIN_PCT": f"{r['wr']:.4f}",
                    "AVG_PNL_PCT": f"{r['avg_pnl_pct']:.4f}",
                    "AVG_R": "" if r["avg_r"] is None else f"{r['avg_r']:.4f}",
                    "PROFIT_FACTOR": f"{r['pf']:.4f}",
                    "EXPECTANCY_PCT": f"{r['exp_pct']:.4f}",
                    "SUM_PNL_PCT": f"{r['sum_pnl_pct']:.4f}",
                    "SUM_PNL_DOLLARS": f"{r['sum_pnl_d']:.2f}",
                    "MEDIAN_DAYS_HELD": "" if r["med_days"] is None else f"{r['med_days']:.2f}",
                    "WORST_TRADE_PCT": "" if r["worst"] is None else f"{r['worst']:.4f}",
                    "MAX_DD_CUM_PNL_PCT": (
                        "" if r["max_dd_pct"] is None else f"{r['max_dd_pct']:.4f}"
                    ),
                    "FIRST_IS_ENTRY": _fmt_date(r["first"]),
                    "LAST_IS_ENTRY": _fmt_date(r["last"]),
                    "ADV20": "" if r["adv20"] is None else f"{r['adv20']:.4f}",
                    "MARKET_CAP": "" if r["mcap"] is None else f"{r['mcap']:.2f}",
                }
            )


def _book_headline(label: str, b: dict[str, Any]) -> str:
    return (
        f"{label}: N={b['n']:,} · WR={b['wr']:.1f}% · "
        f"Avg PnL%={b['avg_pnl_pct']:+.2f} · PF={b['pf']:.2f}"
    )


def _write_baseline(
    path: Path,
    *,
    univ_note: str,
    n_univ: int,
    is_book: dict[str, Any],
    oos_book: dict[str, Any],
    pin_note: str,
) -> None:
    freeze_new = (
        "`wrl_mode=true`, **`wrl_target_mode=swing`** (EXIT_swing — full size out at swing high), "
        "`wrl_scale_frac=0.50` (unused under swing), `stop_pct=1.0` (multiplier on swing low), "
        "`wrl_min_zone_pct=0` (OFF), `wrl_time_stop_bars=0`, `symbol_reentry_cooldown_days=0` "
        "(OFF; do not wire `cooldown_until`), host `$500k × 2.0 × 0.6` like `run_wrl.bat`."
    )
    freeze_prior = (
        "Parent control (`wrl_firstpass_ab_20260922` / house `WRL_BASELINE`): "
        "`wrl_target_mode=scale` (50/50 range then swing), min-zone off, cooldown off, "
        "stop at swing low, same host."
    )
    lines = [
        "# WRL EXIT_swing IS universe summary — 2026-09-22",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        "Weekly Range / Swing (WRL) waits for a daily close in last week's lower pocket, "
        "then buys the next session if price trades back up through that week's low. "
        "The house default takes half off at last week's high and the rest at the swing high. "
        "**EXIT_swing** sells the whole position at the swing high instead. "
        "Paul cancelled adopting the 1% min-zone entry gate. This page re-runs the full "
        "production universe with swing-exit only, then lists each name's in-sample "
        "(before 2024) trade quality so he can pick a tradable list. We do not pick names here.",
        "",
        "## Delta from prior",
        "",
        f"- **Parent stamp:** `drive/paul_experiments/{PARENT_STAMP}/` **control** (not ENTRY_minzone01).",
        f"- **Prior freeze:** {freeze_prior}",
        f"- **This freeze:** {freeze_new}",
        "- **One change:** `wrl_target_mode` `scale` → `swing` (same knob as first-pass `EXIT_swing`).",
        "- **Not kept:** `wrl_min_zone_pct=0.01` (scratched). Min-zone stays **OFF**.",
        "- **Not kept:** `symbol_reentry_cooldown_days` / `cooldown_until` (stays OFF; engine still does not assign it).",
        "- **Universe change (not a knob):** Paul Twenty first-pass → full production WRL universe for this summary.",
        "- Parent Paul Twenty EXIT_swing was **HOLD** (Avg +0.27, PF +0.07, WR −6.3pp vs control; "
        "same $ winner pattern as the old Mag10 page). Adopted here anyway as the freeze for this "
        "universe-selection pass.",
        "",
        "## Freeze (everything else locked)",
        "",
        freeze_new,
        "",
        f"Universe: {univ_note}",
        f"Symbols with OHLC used: {n_univ}.",
        "IS = `entry_date < 2024-01-01`. OOS report-only. Do not retune on OOS.",
        "",
        "## Book-level IS headline (name-pick lens)",
        "",
        f"- {_book_headline('Adopted EXIT_swing IS', is_book)}",
        f"- {_book_headline('Adopted EXIT_swing OOS (report only — do not pick names from this)', oos_book)}",
        "",
        "## Pin vs published Closed",
        "",
        pin_note,
        "",
        "## Selection bias",
        "",
        "Choosing a name list after seeing this IS table is in-sample selection. "
        "After Paul picks names, **re-score IS/OOS under this freeze** on that list. "
        "Do not treat this page as gold or DailyRun.",
        "",
        "## Promotion",
        "",
        "Research candidate only. Not gold. Not DailyRun. No `run_wrl.bat` change.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_hypothesis(
    path: Path,
    *,
    univ_note: str,
    is_book: dict[str, Any],
    oos_book: dict[str, Any],
) -> None:
    freeze = (
        "parent control + `wrl_target_mode=swing`; min-zone 0; cooldown 0; "
        "stop_pct=1.0; scale_frac=0.50 unused; host $500k×2.0×0.6"
    )
    text = "\n".join(
        [
            "# Hypothesis test — WRL EXIT_swing IS universe 20260922",
            "",
            "| Field | Fill |",
            "|---|---|",
            "| System / prefix | WRL — Weekly Range / Swing |",
            f"| Baseline stamp | parent `{PARENT_STAMP}` **control** (scale 50/50) |",
            f"| Universe | Full production WRL ({univ_note}) |",
            "| Evidence | First-pass `EXIT_swing` on Paul Twenty: HOLD (Avg +0.27, PF +0.07, WR −6.3pp). Paul adopted it for this universe-selection pass anyway. |",
            "| Hypothesis | Swing-target exit (full size at swing high) is the freeze; IS per-symbol table lets Paul pick a tradable list. |",
            "| Single knob | `wrl_target_mode=swing` (EXIT identity) |",
            f"| Frozen settings | {freeze} |",
            "| Alternatives | none this stamp — adopt + summarize, not a new A/B |",
            "| Decision | freeze adopted for research universe-pick only; not gold / not DailyRun |",
            f"| IS book | N={is_book['n']}, WR={is_book['wr']:.1f}%, Avg%={is_book['avg_pnl_pct']:+.2f}, PF={is_book['pf']:.2f} |",
            f"| OOS book (report only) | N={oos_book['n']}, WR={oos_book['wr']:.1f}%, Avg%={oos_book['avg_pnl_pct']:+.2f}, PF={oos_book['pf']:.2f} |",
            "| PO sign-off | no |",
            "| Reconcile freeze | no — research only |",
            "",
            "OOS is report-only. Do not retune on OOS. After names are picked, re-score IS/OOS.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def _metric_compare_table(
    adopted: dict[str, Any],
    published: Optional[dict[str, Any]],
) -> str:
    rows: list[tuple[str, str, str, Any, Any]] = [
        ("Universe size", "int", "n_univ", adopted.get("n_univ"), (published or {}).get("n_univ")),
        ("Total trades", "int", "n", adopted.get("n"), (published or {}).get("n")),
        ("Wins", "int", "wins", adopted.get("wins"), (published or {}).get("wins")),
        ("Losses", "int", "losses", adopted.get("losses"), (published or {}).get("losses")),
        ("Win %", "pct", "wr", adopted.get("wr"), (published or {}).get("wr")),
        ("Avg PnL %", "num", "avg", adopted.get("avg_pnl_pct"), (published or {}).get("avg_pnl_pct")),
        ("Avg R (if stop < entry)", "num", "avgr", adopted.get("avg_r"), (published or {}).get("avg_r")),
        ("Expectancy %", "num", "exp", adopted.get("exp_pct"), (published or {}).get("exp_pct")),
        ("Expectancy $", "money", "expd", adopted.get("exp_d"), (published or {}).get("exp_d")),
        ("Profit factor", "num", "pf", adopted.get("pf"), (published or {}).get("pf")),
        ("Ann ROR %", "num", "ror", adopted.get("ann_ror"), (published or {}).get("ann_ror")),
        ("Max DD %", "num", "dd", adopted.get("max_dd"), (published or {}).get("max_dd")),
        ("Calmar", "num", "cal", adopted.get("calmar"), (published or {}).get("calmar")),
        ("Sharpe", "num", "sh", adopted.get("sharpe"), (published or {}).get("sharpe")),
        ("Median days held", "num", "md", adopted.get("med_days"), (published or {}).get("med_days")),
        ("Worst trade %", "num", "wst", adopted.get("worst"), (published or {}).get("worst")),
    ]

    def _cell(v: Any, kind: str) -> str:
        if kind == "int":
            return _fmt_int(v) if v is not None else "—"
        if kind == "pct":
            return "—" if v is None else f"{float(v):.2f}%"
        if kind == "money":
            return format_money(v)
        return _fmt_num(v)

    def _delta(a: Any, b: Any, kind: str) -> str:
        if a is None or b is None:
            return "—"
        try:
            d = float(a) - float(b)
        except (TypeError, ValueError):
            return "—"
        if kind == "int":
            return f"{d:+,.0f}"
        if kind == "pct":
            return f"{d:+.2f}pp"
        if kind == "money":
            return format_money_delta(d)
        return f"{d:+.2f}"

    ths = (
        _sortable_th("Metric", "text")
        + _sortable_th("Adopted EXIT_swing IS", "num")
        + _sortable_th("Published Closed IS (scale, no swing)", "num")
        + _sortable_th("Δ adopted − published", "num")
    )
    body = []
    for label, kind, _k, a, p in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td class='num'>{_cell(a, kind)}</td>"
            f"<td class='num'>{_cell(p, kind)}</td>"
            f"<td class='num'>{_delta(a, p, kind)}</td>"
            "</tr>"
        )
    return f"""
<div class="table-wrap"><table class="sortable">
<caption>Book-level IS only. Click column headers to sort. Total / Sheet PnL $ omitted (canonical HTML rule). Pin labeled below.</caption>
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table></div>
"""


def _symbol_table(rows: list[dict[str, Any]]) -> str:
    ths = "".join(
        [
            _sortable_th("Symbol", "text"),
            _sortable_th("N trades (IS)", "num"),
            _sortable_th("Win%", "num"),
            _sortable_th("Avg PnL%", "num"),
            _sortable_th("AvgR", "num"),
            _sortable_th("PF", "num"),
            _sortable_th("Expectancy %", "num"),
            _sortable_th("Sum PnL%", "num"),
            _sortable_th("Sum PnL $", "num"),
            _sortable_th("Median days", "num"),
            _sortable_th("Worst trade %", "num"),
            _sortable_th("Max DD (cum %)", "num"),
            _sortable_th("First IS entry", "date"),
            _sortable_th("Last IS entry", "date"),
            _sortable_th("ADV20", "num"),
            _sortable_th("Market cap", "num"),
        ]
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(r['symbol'])}</td>"
            f"<td class='num'>{r['n']}</td>"
            f"<td class='num'>{r['wr']:.1f}</td>"
            f"<td class='num'>{r['avg_pnl_pct']:+.2f}</td>"
            f"<td class='num'>{_fmt_num(r['avg_r'])}</td>"
            f"<td class='num'>{_fmt_num(r['pf'])}</td>"
            f"<td class='num'>{r['exp_pct']:+.2f}</td>"
            f"<td class='num'>{r['sum_pnl_pct']:+.2f}</td>"
            f"<td class='num'>{format_money(r['sum_pnl_d'])}</td>"
            f"<td class='num'>{_fmt_num(r['med_days'])}</td>"
            f"<td class='num'>{_fmt_num(r['worst'])}</td>"
            f"<td class='num'>{_fmt_num(r['max_dd_pct'])}</td>"
            f"<td>{_fmt_date(r['first'])}</td>"
            f"<td>{_fmt_date(r['last'])}</td>"
            f"<td class='num'>{_fmt_adv(r['adv20'])}</td>"
            f"<td class='num'>{_fmt_mcap(r['mcap'])}</td>"
            "</tr>"
        )
    return f"""
<div class="table-wrap"><table class="sortable">
<caption>In-sample only (entry &lt; 2024-01-01). Default order is A–Z — we are not ranking names. Click column headers to sort.</caption>
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table></div>
"""


def write_html(
    *,
    univ_note: str,
    n_univ: int,
    is_book: dict[str, Any],
    oos_book: dict[str, Any],
    pub_book: Optional[dict[str, Any]],
    pin_note: str,
    symbol_rows: list[dict[str, Any]],
    skipped: list[str],
    elapsed_s: float,
    closed_path: Path,
) -> str:
    pub_html = (
        _metric_compare_table(is_book, pub_book)
        if pub_book is not None
        else "<p class='muted'>Published Closed pin not found on disk — no compare row.</p>"
    )
    skip_note = (
        f"<p class='muted'>Skipped (no/short OHLC): {html.escape(','.join(skipped[:40]))}"
        + ("…" if len(skipped) > 40 else "")
        + f" ({len(skipped)})</p>"
        if skipped
        else ""
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WRL EXIT_swing IS universe — 2026-09-22</title>
<style>
  :root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
    --card:#fff; --accent:#2a4a5c; --ok:#2d6a4f; --ok-bg:#e8f2ec;
    --warn:#8a5a12; --warn-bg:#f7efe0; --bad:#9b2226; --bad-bg:#fdecea; --fill:#f0eee6; }}
  body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",Georgia,serif; font-size:15px;
    line-height:1.55; color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:1.55rem; margin:0 0 8px; }}
  h2 {{ font-size:1.12rem; margin:26px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }}
  .lede, .muted {{ color:var(--muted); }}
  .badge {{ display:inline-block; font-size:0.75rem; font-weight:700; padding:2px 8px; background:var(--bad-bg); color:var(--bad); }}
  .callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:12px 0; }}
  .callout.warn {{ background:var(--warn-bg); border-left-color:var(--warn); }}
  .cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:12px 0 8px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; min-width:160px; flex:1 1 160px; }}
  .card .k {{ font-size:0.75rem; color:var(--muted); font-weight:700; }}
  .card .v {{ font-size:1.25rem; font-weight:700; }}
  .table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
  thead th {{ background:var(--fill); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
  th.sortable-th:hover {{ background:#e6e2d6; }}
  .sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#9a9588; font-size:10px; }}
  th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
  th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
  caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
  code {{ background:var(--fill); padding:0.08em 0.3em; }}
  {SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <p class="muted">WRL — Weekly Range / Swing · research stamp 2026-09-22 · parent <code>{html.escape(PARENT_STAMP)}</code></p>
  <h1>WRL EXIT_swing · full-universe IS name table</h1>
  <div class="badge">Research candidate — not gold — not DailyRun</div>
  <p class="lede">Adopted freeze: swing-target exit. Min-zone off. Cooldown off. Pick names from the IS table; we re-score after you choose.</p>

  <div class="callout">
    <strong>What you asked</strong>
    <p>{html.escape(ORIGINAL_REQUEST)}</p>
  </div>
  <div class="callout">
    <strong>In plain English</strong>
    <p>Weekly Range / Swing (WRL) is a weekly demand-zone idea: wait for a daily close in the
    pocket under last week’s range, then buy the next session if price trades back up through
    that week’s low. The house default <em>at this stamp</em> scaled out — half at last week’s high, half at the
    higher swing high. <strong>EXIT_swing</strong> skips the half-sale and exits the whole
    position at the swing high. (House engine default flipped to swing on 2026-09-22; this page is the prior research run.)</p>
    <p>You cancelled adopting the 1% min-zone entry filter. This page is only the swing-exit
    freeze, re-run on the <em>full</em> production universe (not the 20-name first-pass),
    using trades that opened before 2024 so you can choose which names belong in a tradable
    list. We are not choosing the list. After you pick, we will re-score in-sample and
    out-of-sample on that list. This is research, not a live DailyRun wire.</p>
  </div>

  <div class="callout warn">
    <strong>Selection bias.</strong> Picking names after seeing this in-sample table is
    in-sample selection even if we later print an out-of-sample row. After you choose,
    we re-score IS/OOS under this freeze. Out-of-sample is report-only — do not rank or
    retune from it.
  </div>

  <h2>Freeze (delta from prior)</h2>
  <p>Parent <code>{html.escape(PARENT_STAMP)}</code> <strong>control</strong> + one change:
  <code>wrl_target_mode=swing</code>. Min-zone <strong>off</strong> (not 1%). Scale 50/50
  leftover unused. Stop at swing low. Cooldown off — do not wire <code>cooldown_until</code>.</p>
  <p>Parent Paul Twenty EXIT_swing was HOLD (Avg +0.27, PF +0.07, WR −6.3pp vs control).
  Adopted here anyway as the freeze for this universe-selection pass.</p>
  <p class="muted">{html.escape(univ_note)} · {n_univ} symbols with OHLC · engine {elapsed_s:.0f}s ·
  Closed <code>{html.escape(str(closed_path.as_posix()))}</code></p>

  <h2>Book-level IS headline</h2>
  <div class="cards">
    <div class="card"><div class="k">IS trades</div><div class="v">{is_book['n']:,}</div></div>
    <div class="card"><div class="k">IS win %</div><div class="v">{is_book['wr']:.1f}%</div></div>
    <div class="card"><div class="k">IS Avg PnL%</div><div class="v">{is_book['avg_pnl_pct']:+.2f}</div></div>
    <div class="card"><div class="k">IS profit factor</div><div class="v">{is_book['pf']:.2f}</div></div>
  </div>
  <p class="muted">{html.escape(_book_headline('Adopted EXIT_swing IS', is_book))}</p>
  <p class="muted">OOS report-only (do not pick names from this): {html.escape(_book_headline('EXIT_swing OOS', oos_book))}</p>

  <h2>Adopted full-IS vs published Closed IS (scale, no swing)</h2>
  <p class="muted">{html.escape(pin_note)}</p>
  {pub_html}

  <h2>Per-symbol IS summary — you pick the names</h2>
  <p>Columns: trades, win rate, average gain (and average R when the stop is below the fill),
  profit factor / expectancy, sum of gains, typical hold, worst trade, a cheap cumulative
  drawdown of that name’s in-sample PnL% path, first/last in-sample entry, plus ADV20
  (20-session average volume from local bars) and market cap when already in
  <code>yfinance_cache.json</code>. Missing ADV/cap is a dash — we did not run a Yahoo fetch.</p>
  {_symbol_table(symbol_rows)}
  {skip_note}

  <p class="muted">Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M"))} ·
  <code>tools/wrl_exitswing_is_universe_20260922.py</code> · research ≠ gold ≠ DailyRun</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    return page


def _latest_closed(stamp: Path) -> Optional[Path]:
    files = sorted(stamp.glob("WRL_Closed_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _closed_from_csv(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            rec = _row_from_csv(row)
            if rec["symbol"]:
                out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="WRL EXIT_swing full-univ IS summary 20260922")
    ap.add_argument("--workers", type=int, default=max(1, min(12, os.cpu_count() or 4)))
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--write-full-outputs", action="store_true",
                    help="Also call write_wrl_outputs (slower; Summary/Report/Audit)")
    args = ap.parse_args()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)

    symbols, univ_note = _resolve_universe()
    if not symbols:
        print("[WRL-SWING] no universe symbols", flush=True)
        return 1
    print(f"[WRL-SWING] {len(symbols)} symbols · {univ_note}", flush=True)
    print(
        "[WRL-SWING] freeze: wrl_target_mode=swing, min_zone=0, cooldown=0, stop_pct=1.0",
        flush=True,
    )

    t0 = time.time()
    skipped: list[str] = []
    adv: dict[str, Optional[float]] = {}
    closed_path: Optional[Path] = None
    rows: list[dict[str, Any]] = []

    if args.summarize_only:
        closed_path = _latest_closed(STAMP_DIR)
        if not closed_path:
            print("[WRL-SWING] --summarize-only but no stamp Closed CSV", flush=True)
            return 1
        rows = _closed_from_csv(closed_path)
        print(f"[WRL-SWING] summarize-only from {closed_path} ({len(rows)} rows)", flush=True)
        # ADV from disk only for symbols we will list (cheap-ish; skip huge extra if already present)
        is_syms = sorted({r["symbol"] for r in _slice_is(rows)})
        for i, sym in enumerate(is_syms, 1):
            if i % 200 == 0:
                print(f"[WRL-SWING] ADV scan {i}/{len(is_syms)}", flush=True)
            df = _load_symbol(sym)
            if df is not None:
                adv[sym] = _adv20_from_frame(df)
    else:
        closed, opens, adv, skipped = _run_full(symbols, int(args.workers))
        hcfg = _host_cfg()
        host_meta: dict[str, Any] = {}
        cfg = WrlConfig()
        for k, v in ADOPTED_OVERRIDES.items():
            setattr(cfg, k, v)
        if closed:
            adj, scale, max_pos = apply_host_dollar_scale(closed, opens, hcfg)
            cfg.brt_cash = adj
            host_meta = {
                "host_max_positions": max_pos,
                "host_brt_cash": adj,
                "host_pnl_scale": scale,
            }
            print(
                f"[WRL-SWING] host scale ×{scale:.6g}; brt_cash -> {adj:,.0f} (max_pos={max_pos})",
                flush=True,
            )
        ts = time.strftime("%y%m%d%H%M%S")
        closed_path = STAMP_DIR / f"WRL_Closed_{ts}.csv"
        if args.write_full_outputs:
            write_wrl_outputs(
                STAMP_DIR,
                ts,
                closed,
                opens,
                [],
                [],
                cfg,
                host_meta=host_meta,
                tickers=None,
                host_cfg=hcfg,
                no_yfinance=True,
            )
            closed_path = STAMP_DIR / f"WRL_Closed_{ts}.csv"
        else:
            _write_closed_csv(closed_path, closed)
        (STAMP_DIR / "STAMP.txt").write_text(
            f"stamp={ts}\narm=EXIT_swing\noverrides={ADOPTED_OVERRIDES}\n"
            f"wrl_min_zone_pct=0\nsymbol_reentry_cooldown_days=0\n"
            f"n_symbols={len(symbols)}\nn_closed={len(closed)}\n"
            f"elapsed_s={time.time() - t0:.1f}\nuniverse={univ_note}\n",
            encoding="utf-8",
        )
        rows = [_row_from_engine(r) for r in closed]

    is_rows = _slice_is(rows)
    oos_rows = _slice_oos(rows)
    n_univ = len({r["symbol"] for r in rows}) or len(symbols)
    is_book = _book(is_rows, n_univ=n_univ, cash=SHEET_CASH)
    oos_book = _book(oos_rows, n_univ=n_univ, cash=SHEET_CASH)

    pub_book: Optional[dict[str, Any]] = None
    pin_note = (
        f"Pin: published production Closed `{PUBLISHED_CLOSED.name}` "
        "(2026-09-06; house scale 50/50; min-zone off; no swing exit). "
        "IS slice only. Research compare — not gold."
    )
    pub_rows = _load_published_rows()
    if pub_rows:
        pub_is = _slice_is(pub_rows)
        pub_univ = len({r["symbol"] for r in pub_rows})
        pub_book = _book(pub_is, n_univ=pub_univ, cash=SHEET_CASH)
        pin_note += (
            f" Published IS N={pub_book['n']:,} WR={pub_book['wr']:.1f}% "
            f"Avg={pub_book['avg_pnl_pct']:+.2f} PF={pub_book['pf']:.2f}."
        )
    else:
        pin_note = "Published Closed pin not on disk; skipped adopted-vs-published IS compare."

    mcap = _load_mcap_cache()
    sym_rows = _symbol_rows(is_rows, adv, mcap)
    csv_path = STAMP_DIR / "WRL_IS_SymbolSummary.csv"
    _write_symbol_csv(csv_path, sym_rows)
    try:
        DRIVE_SUMMARY_COPY.write_bytes(csv_path.read_bytes())
    except OSError as e:
        print(f"[WRL-SWING] drive copy skipped: {e}", flush=True)

    elapsed = time.time() - t0
    assert closed_path is not None
    page = write_html(
        univ_note=univ_note,
        n_univ=n_univ,
        is_book=is_book,
        oos_book=oos_book,
        pub_book=pub_book,
        pin_note=pin_note,
        symbol_rows=sym_rows,
        skipped=skipped,
        elapsed_s=elapsed,
        closed_path=closed_path,
    )
    summary = STAMP_DIR / "summary.html"
    compare = STAMP_DIR / "compare.html"
    summary.write_text(page, encoding="utf-8")
    compare.write_text(page, encoding="utf-8")
    _write_baseline(
        STAMP_DIR / "BASELINE.md",
        univ_note=univ_note,
        n_univ=n_univ,
        is_book=is_book,
        oos_book=oos_book,
        pin_note=pin_note,
    )
    _write_hypothesis(
        STAMP_DIR / "HYPOTHESIS.md",
        univ_note=univ_note,
        is_book=is_book,
        oos_book=oos_book,
    )
    (STAMP_DIR / "HEADLINE.txt").write_text(
        _book_headline("Adopted EXIT_swing IS", is_book) + "\n"
        + _book_headline("Adopted EXIT_swing OOS (report only)", oos_book) + "\n",
        encoding="utf-8",
    )
    print(f"[WRL-SWING] wrote {summary}", flush=True)
    print(f"[WRL-SWING] wrote {csv_path}", flush=True)
    print(f"[WRL-SWING] {_book_headline('IS', is_book)}", flush=True)
    print(f"[WRL-SWING] {_book_headline('OOS report-only', oos_book)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
