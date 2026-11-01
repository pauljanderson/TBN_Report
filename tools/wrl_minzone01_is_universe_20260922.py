#!/usr/bin/env python3
"""WRL min-zone 1% adopt — full-universe IS symbol summary, 2026-09-22.

Weekly Range / Swing (WRL). Paul adopted ENTRY_minzone01 from
``wrl_firstpass_ab_20260922`` as the new freeze (HOLD on Paul Twenty, not KEEP).
This stamp re-runs the **full** rocket_wrl / production universe with that one
knob and writes a per-symbol in-sample book so he can cut names.

Research only. Not gold. Not DailyRun. Do not retune on OOS.
IS = entry_date < 2024-01-01. Universe pick is IS (correct). After he picks,
re-score IS/OOS under this freeze — that later score is selection-biased until labeled.
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
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))
sys.path.insert(0, str(REPO))

from compare_format import (  # noqa: E402
    canonical_book_order_html,
    filter_html_compare_metric_rows,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
    parse_number,
)
from rocket_wrl import (  # noqa: E402
    WRL_CLOSED_HEADER,
    WrlClosedRow,
    WrlConfig,
    _process_wrl_symbol,
    _wrl_cfg_dict,
    write_wrl_outputs,
)
from tbn_host_sizing import HostSizingConfig, apply_host_dollar_scale  # noqa: E402

try:
    from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS
except ImportError:  # pragma: no cover
    SORTABLE_TABLE_SCRIPT = ""
    SORTABLE_TH_CSS = ""

STAMP_DIR = REPO / "drive" / "paul_experiments" / "wrl_minzone01_is_universe_20260922"
DATA_DIR = REPO / "data" / "newdata" / "data"
PAUL20 = REPO / "drive" / "universes" / "PaulTwenty_universe.csv"
PIN_CLOSED = REPO / "drive" / "WRL_Closed_260906140457.csv"
YF_CACHE = REPO / "yfinance_cache.json"
FUND_DB = REPO / "drive" / "fundamentals_cache.duckdb"
DRIVE_COPY = REPO / "drive" / "WRL_IS_SymbolSummary_minzone01.csv"
IS_CUT = date(2024, 1, 1)
SHEET_CASH = 47_500.0
INIT = 500_000.0
PARENT = "drive/paul_experiments/wrl_firstpass_ab_20260922/"
PIN_TS = "260906140457"

ORIGINAL_REQUEST = (
    "i like the entry_minzone01 run. let's adopt that and do a another full run "
    "on IS only, and give me the summary file, so i can choose the universe please"
)

FREEZE = (
    "`wrl_mode=true`, `wrl_target_mode=scale`, `wrl_scale_frac=0.50`, "
    "`stop_pct=1.0` (multiplier on swing low), `wrl_min_zone_pct=0.01` (1% ON), "
    "`wrl_time_stop_bars=0`, `symbol_reentry_cooldown_days=0` "
    "(engine never sets `cooldown_until` — not silently wired), "
    "host `$500k × 2.0 × 0.6` like `run_wrl.bat`."
)


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _load_paul20() -> set[str]:
    if not PAUL20.is_file():
        return set()
    out: set[str] = set()
    for line in PAUL20.read_text(encoding="utf-8").splitlines():
        t = line.strip().upper()
        if t and not t.startswith("#"):
            out.add(t)
    return out


def _list_universe_files() -> list[tuple[str, Path]]:
    """Same discovery as rocket_tbn.load_all_tickers (skip SPY)."""
    files: list[tuple[str, Path]] = []
    if not DATA_DIR.is_dir():
        return files
    for p in sorted(DATA_DIR.glob("*.csv")):
        sym = p.stem.upper()
        if sym == "SPY":
            continue
        files.append((sym, p))
    return files


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


def _load_symbol_frame(path: Path) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    if "Date" not in df.columns:
        return None
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")
    for c in ("Open", "High", "Low", "Close"):
        if c not in df.columns:
            return None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df if len(df) >= 30 else None


def _adv20_from_df(df: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    if df is None or len(df) < 1:
        return None, None
    tail = df.tail(20)
    if "Volume" not in tail.columns:
        return None, None
    vol = pd.to_numeric(tail["Volume"], errors="coerce")
    close = pd.to_numeric(tail["Close"], errors="coerce")
    if vol.notna().sum() < 5:
        return None, None
    shares = float(vol.mean())
    dollars = float((vol * close).mean()) if close.notna().any() else None
    return shares, dollars


def _process_symbol_path(args: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    """Worker: load one CSV, backtest, return closed rows + ADV20. Import-safe."""
    sym, path_s, cfg_d = args
    path = Path(path_s)
    df = _load_symbol_frame(path)
    if df is None:
        return {"symbol": sym, "skip": "no_ohlc", "closed": [], "open": [], "watch": [], "adv20_sh": None, "adv20_d": None}
    adv_sh, adv_d = _adv20_from_df(df)
    res = _process_wrl_symbol((sym, df, cfg_d))
    closed_dicts = []
    for r in res.closed:
        closed_dicts.append(
            {
                "symbol": r.symbol,
                "date_opened": r.date_opened,
                "date_closed": r.date_closed,
                "entry_price": r.entry_price,
                "stop_price": r.stop_price,
                "exit_type": r.exit_type,
                "days_held": r.days_held,
                "pnl_pct": r.pnl_pct,
                "pnl_dollars": r.pnl_dollars,
                "range_low": r.range_low,
                "swing_low": r.swing_low,
            }
        )
    return {
        "symbol": sym,
        "skip": res.skip_reason or "",
        "closed": closed_dicts,
        "open": res.open_rows,
        "watch": res.watch,
        "scanner": res.scanner,
        "closed_objs": res.closed,
        "adv20_sh": adv_sh,
        "adv20_d": adv_d,
    }


def _load_mcap_cache() -> dict[str, dict[str, Any]]:
    """Cache-only market cap / sector. Do not hit Yahoo."""
    out: dict[str, dict[str, Any]] = {}
    if YF_CACHE.is_file():
        try:
            data = json.loads(YF_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for k, e in data.items():
                if not isinstance(e, dict):
                    continue
                mc = e.get("market_cap")
                if mc in (None, "", 0, 0.0):
                    continue
                try:
                    mc_f = float(mc)
                except (TypeError, ValueError):
                    continue
                out[str(k).upper()] = {
                    "market_cap": mc_f,
                    "sector": str(e.get("sector") or ""),
                    "industry": str(e.get("industry") or ""),
                    "src": "yfinance_cache.json",
                }
    if FUND_DB.is_file():
        try:
            import duckdb  # type: ignore

            con = duckdb.connect(str(FUND_DB), read_only=True)
            rows = con.execute(
                "SELECT symbol, market_cap, sector, industry FROM yf_symbol_info "
                "WHERE market_cap IS NOT NULL AND market_cap > 0"
            ).fetchall()
            con.close()
            for rec in rows:
                sym = str(rec[0] or "").upper()
                if not sym or sym in out:
                    continue
                try:
                    mc_f = float(rec[1])
                except (TypeError, ValueError):
                    continue
                out[sym] = {
                    "market_cap": mc_f,
                    "sector": str(rec[2] or "") if len(rec) > 2 else "",
                    "industry": str(rec[3] or "") if len(rec) > 3 else "",
                    "src": "fundamentals_cache.duckdb",
                }
        except Exception:
            pass
    return out


def _closed_obj_from_d(d: dict[str, Any]) -> WrlClosedRow:
    return WrlClosedRow(
        symbol=str(d["symbol"]),
        side="LONG",
        date_opened=str(d["date_opened"]),
        entry_price=float(d["entry_price"]),
        stop_price=float(d["stop_price"]),
        target_price=0.0,
        target2_price=0.0,
        date_closed=str(d["date_closed"]),
        exit_price=0.0,
        exit_type=str(d.get("exit_type") or ""),
        days_held=int(d.get("days_held") or 0),
        pnl_pct=float(d["pnl_pct"]),
        pnl_dollars=float(d["pnl_dollars"]),
        ann_ror_pct=0.0,
        max_price=0.0,
        range_high=0.0,
        range_low=float(d.get("range_low") or 0.0),
        swing_high=0.0,
        swing_low=float(d.get("swing_low") or 0.0),
        watch_date="",
        signal_date="",
        range_week_end="",
        one_liner="",
    )


def _row_from_closed_dict(d: dict[str, Any]) -> dict[str, Any]:
    opened = _parse_ymd(d.get("date_opened") or d.get("DATE_OPENED"))
    closed = _parse_ymd(d.get("date_closed") or d.get("DATE_CLOSED"))
    entry = _f(d.get("entry_price") if "entry_price" in d else d.get("ENTRY_PRICE"))
    stop = _f(d.get("stop_price") if "stop_price" in d else d.get("STOP_PRICE"))
    rl = _f(d.get("range_low") if "range_low" in d else d.get("RANGE_LOW"))
    sl = _f(d.get("swing_low") if "swing_low" in d else d.get("SWING_LOW"))
    risk_pct = ((entry - stop) / entry * 100.0) if entry > 0 and stop > 0 and entry > stop else None
    zone = ((rl / sl) - 1.0) * 100.0 if sl > 0 else None
    pnl = _f(d.get("pnl_pct") if "pnl_pct" in d else d.get("PNL_PCT"))
    r_mult = (pnl / risk_pct) if risk_pct and abs(risk_pct) > 1e-12 else None
    return {
        "symbol": str(d.get("symbol") or d.get("SYMBOL") or "").upper(),
        "opened": opened,
        "closed": closed,
        "pnl": pnl,
        "pnl_d": _f(d.get("pnl_dollars") if "pnl_dollars" in d else d.get("PNL_DOLLARS")),
        "days": _f(d.get("days_held") if "days_held" in d else d.get("DAYS_HELD")),
        "exit": str(d.get("exit_type") or d.get("EXIT_TYPE") or "").strip().upper(),
        "win": pnl > 0,
        "risk_pct": risk_pct,
        "r_mult": r_mult,
        "zone_pct": zone,
    }


def _slice_rows(rows: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [r for r in rows if r.get("opened") and r["opened"] < IS_CUT]
    if which == "OOS":
        return [r for r in rows if r.get("opened") and r["opened"] >= IS_CUT]
    return list(rows)


def _pctile(xs: list[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def _wo_max_mean(pcts: list[float]) -> Optional[float]:
    if not pcts:
        return None
    if len(pcts) == 1:
        return pcts[0]
    drop = max(pcts)
    rest = [x for x in pcts if x != drop]
    if len(rest) < len(pcts):
        return sum(rest) / len(rest)
    return sum(pcts[:-1]) / (len(pcts) - 1)


def _symbol_max_dd(pnls_in_order: list[float]) -> Optional[float]:
    """Peak-to-trough of cumulative PnL% (percentage points)."""
    if not pnls_in_order:
        return None
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls_in_order:
        eq += p
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _book_from_rows(
    rows: list[dict[str, Any]],
    *,
    cash: float,
    n_univ: int,
    start_date: Optional[date] = None,
    end_date_exclusive: Optional[date] = None,
) -> dict[str, Any]:
    n = len(rows)
    pnls = [float(r["pnl"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr = (100.0 * len(wins) / n) if n else 0.0
    avg = (sum(pnls) / n) if n else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    wl_count = (len(wins) / len(losses)) if losses else (float(len(wins)) if wins else 0.0)
    sum_w = sum(float(r["pnl_d"]) for r in rows if r["pnl_d"] > 0)
    sum_l = abs(sum(float(r["pnl_d"]) for r in rows if r["pnl_d"] < 0))
    pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
    days = [float(r["days"]) for r in rows if r.get("days") is not None]
    avg_days = (sum(days) / len(days)) if days else 0.0
    med_days = statistics.median(days) if days else 0.0
    p90_days = _pctile(days, 0.90) or 0.0
    ov = overlay_ann_ror_max_dd(
        rows,
        cash=cash,
        initial_account=INIT,
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl",
    )
    exits = Counter(str(r.get("exit") or "UNKNOWN") for r in rows)
    n_ex = sum(exits.values()) or 1
    wo = _wo_max_mean(pnls)
    profit_day = None
    if ov["capital_days"] and ov["capital_days"] > 0:
        profit_day = ov["pnl_d"] / ov["capital_days"]
    rs = [float(r["r_mult"]) for r in rows if r.get("r_mult") is not None]
    return {
        "n_univ": n_univ,
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": wr,
        "avg_pnl_pct": avg,
        "wo_max": wo,
        "exp_pct": avg,
        "exp_d": (sum(float(r["pnl_d"]) for r in rows) / n) if n else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "wl_count": wl_count,
        "wl_d": (sum_w / sum_l) if sum_l > 0 else 0.0,
        "pf": pf,
        "ann_ror": ov["ann_ror"],
        "max_dd": ov["max_dd"],
        "calmar": ov["calmar"],
        "sharpe": ov["sharpe"],
        "sharpe_src": ov["sharpe_source"],
        "profit_day": profit_day,
        "capital_days": ov["capital_days"],
        "avg_days": avg_days,
        "med_days": med_days,
        "p90_days": p90_days,
        "exits": exits,
        "exit_n": n_ex,
        "pnl_d": ov["pnl_d"],
        "avg_r": (sum(rs) / len(rs)) if rs else None,
        "note": ov.get("note") or "",
        "n_sym": len({r["symbol"] for r in rows if r.get("symbol")}),
    }


def _load_pin_rows() -> list[dict[str, Any]]:
    if not PIN_CLOSED.is_file():
        return []
    out: list[dict[str, Any]] = []
    with PIN_CLOSED.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            out.append(_row_from_closed_dict(row))
    return out


def _per_symbol_is(
    is_rows: list[dict[str, Any]],
    *,
    adv: dict[str, tuple[Optional[float], Optional[float]]],
    mcap: dict[str, dict[str, Any]],
    paul20: set[str],
) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in is_rows:
        if r.get("symbol"):
            by[r["symbol"]].append(r)
    out: list[dict[str, Any]] = []
    for sym, rows in by.items():
        rows_s = sorted(rows, key=lambda x: (x.get("opened") or date.min, x.get("closed") or date.min))
        pnls = [float(r["pnl"]) for r in rows_s]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        n = len(rows_s)
        wr = 100.0 * len(wins) / n if n else 0.0
        avg = sum(pnls) / n if n else 0.0
        sum_w = sum(float(r["pnl_d"]) for r in rows_s if r["pnl_d"] > 0)
        sum_l = abs(sum(float(r["pnl_d"]) for r in rows_s if r["pnl_d"] < 0))
        pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
        days = [float(r["days"]) for r in rows_s]
        rs = [float(r["r_mult"]) for r in rows_s if r.get("r_mult") is not None]
        zones = [float(r["zone_pct"]) for r in rows_s if r.get("zone_pct") is not None]
        risks = [float(r["risk_pct"]) for r in rows_s if r.get("risk_pct") is not None]
        opens = [r["opened"] for r in rows_s if r.get("opened")]
        adv_sh, adv_d = adv.get(sym, (None, None))
        mc = mcap.get(sym, {})
        out.append(
            {
                "symbol": sym,
                "n": n,
                "wins": len(wins),
                "losses": len(losses),
                "wr": wr,
                "avg_pnl_pct": avg,
                "avg_r": (sum(rs) / len(rs)) if rs else None,
                "expectancy_pct": avg,
                "pf": pf,
                "sum_pnl_pct": sum(pnls),
                "sum_pnl_d": sum(float(r["pnl_d"]) for r in rows_s),
                "med_days": statistics.median(days) if days else None,
                "avg_days": (sum(days) / len(days)) if days else None,
                "worst_pct": min(pnls) if pnls else None,
                "best_pct": max(pnls) if pnls else None,
                "max_dd_pct": _symbol_max_dd(pnls),
                "first_is": min(opens) if opens else None,
                "last_is": max(opens) if opens else None,
                "adv20_shares": adv_sh,
                "adv20_dollars": adv_d,
                "market_cap": mc.get("market_cap"),
                "sector": mc.get("sector") or "",
                "min_zone_pct": min(zones) if zones else None,
                "med_zone_pct": statistics.median(zones) if zones else None,
                "mean_zone_pct": (sum(zones) / len(zones)) if zones else None,
                "mean_risk_pct": (sum(risks) / len(risks)) if risks else None,
                "in_paul20": "Y" if sym in paul20 else "N",
            }
        )
    out.sort(key=lambda r: (-int(r["n"]), str(r["symbol"])))
    return out


SUMMARY_FIELDS = [
    "symbol",
    "n",
    "wins",
    "losses",
    "wr",
    "avg_pnl_pct",
    "avg_r",
    "expectancy_pct",
    "pf",
    "sum_pnl_pct",
    "sum_pnl_d",
    "med_days",
    "avg_days",
    "worst_pct",
    "best_pct",
    "max_dd_pct",
    "first_is",
    "last_is",
    "adv20_shares",
    "adv20_dollars",
    "market_cap",
    "sector",
    "min_zone_pct",
    "med_zone_pct",
    "mean_zone_pct",
    "mean_risk_pct",
    "in_paul20",
]


def _fmt_num(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return ""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        w.writeheader()
        for r in rows:
            out = {}
            for k in SUMMARY_FIELDS:
                v = r.get(k)
                if isinstance(v, date):
                    out[k] = v.isoformat()
                elif v is None:
                    out[k] = ""
                elif isinstance(v, float):
                    out[k] = f"{v:.6g}" if abs(v) >= 1e6 else f"{v:.4f}"
                else:
                    out[k] = v
            w.writerow(out)


def _run_engine(workers: int) -> tuple[list[dict[str, Any]], dict[str, tuple[Optional[float], Optional[float]]], dict[str, Any], Path]:
    files = _list_universe_files()
    if not files:
        raise SystemExit(f"no ticker CSVs in {DATA_DIR}")
    cfg = WrlConfig()
    cfg.wrl_target_mode = "scale"  # pin: this stamp was min-zone on the old scale house
    cfg.wrl_min_zone_pct = 0.01
    cfg_d = _wrl_cfg_dict(cfg)
    print(
        f"[WRL-MZ01] full universe {len(files)} CSVs, workers={workers}, "
        f"wrl_min_zone_pct={cfg.wrl_min_zone_pct} -> {STAMP_DIR}",
        flush=True,
    )
    t0 = time.time()
    closed_dicts: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    scanner: list[dict[str, Any]] = []
    closed_objs: list[WrlClosedRow] = []
    adv: dict[str, tuple[Optional[float], Optional[float]]] = {}
    n_skip = 0
    n_done = 0
    tasks = [(sym, str(path), cfg_d) for sym, path in files]
    n_w = max(1, min(int(workers), len(tasks), 32))
    with ProcessPoolExecutor(max_workers=n_w) as ex:
        futs = {ex.submit(_process_symbol_path, t): t[0] for t in tasks}
        for fut in as_completed(futs):
            sym = futs[fut]
            n_done += 1
            try:
                res = fut.result()
            except Exception as e:
                n_skip += 1
                print(f"[WRL-MZ01] skip {sym}: {e}", flush=True)
                continue
            if res.get("skip") and not res.get("closed"):
                n_skip += 1
            closed_dicts.extend(res.get("closed") or [])
            open_rows.extend(res.get("open") or [])
            watch.extend(res.get("watch") or [])
            scanner.extend(res.get("scanner") or [])
            closed_objs.extend(res.get("closed_objs") or [])
            adv[res["symbol"]] = (res.get("adv20_sh"), res.get("adv20_d"))
            if n_done % 200 == 0 or n_done == len(tasks):
                print(
                    f"[WRL-MZ01] {n_done}/{len(tasks)} symbols  closed={len(closed_dicts)}  "
                    f"elapsed={time.time() - t0:.0f}s",
                    flush=True,
                )
    if not closed_objs and closed_dicts:
        closed_objs = [_closed_obj_from_d(d) for d in closed_dicts]
    closed_objs.sort(key=lambda r: (r.date_opened, r.symbol))
    hcfg = _host_cfg()
    host_meta: dict[str, Any] = {}
    if closed_objs:
        adj, scale, max_pos = apply_host_dollar_scale(closed_objs, open_rows, hcfg)
        cfg.brt_cash = adj
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
        }
        # Keep dict dollars in sync with scaled objects.
        by_key = {(r.symbol, r.date_opened, round(r.entry_price, 4)): r for r in closed_objs}
        for d in closed_dicts:
            obj = by_key.get((d["symbol"], d["date_opened"], round(float(d["entry_price"]), 4)))
            if obj is not None:
                d["pnl_dollars"] = obj.pnl_dollars
    ts = time.strftime("%y%m%d%H%M%S")
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    # Write Closed / Open / Watch / Scanner. Skip host equity + yfinance analysis
    # (full-universe equity over all tickers is expensive; not needed for universe pick).
    write_wrl_outputs(
        STAMP_DIR,
        ts,
        closed_objs,
        open_rows,
        watch,
        scanner,
        cfg,
        host_meta=host_meta,
        tickers=None,
        host_cfg=None,
        tbn_cfg=None,
        no_yfinance=True,
    )
    (STAMP_DIR / "STAMP.txt").write_text(
        f"stamp={ts}\narm=ENTRY_minzone01_adopt\noverrides={{'wrl_min_zone_pct': 0.01}}\n"
        f"universe=ALL ({len(files)} csv, skip SPY)\n"
        f"n_closed={len(closed_objs)}\nn_skip={n_skip}\n"
        f"elapsed_s={time.time() - t0:.1f}\nhost={host_meta}\n"
        f"note=write_wrl_outputs without host equity / yfinance (universe-pick stamp)\n",
        encoding="utf-8",
    )
    print(
        f"[WRL-MZ01] engine done: {len(closed_objs)} closed / {len(open_rows)} open  "
        f"({time.time() - t0:.1f}s) skip={n_skip}",
        flush=True,
    )
    meta = {
        "ts": ts,
        "n_files": len(files),
        "n_skip": n_skip,
        "elapsed_s": time.time() - t0,
        "host_meta": host_meta,
        "cash": float(cfg.brt_cash or SHEET_CASH),
    }
    return closed_dicts, adv, meta, STAMP_DIR / f"WRL_Closed_{ts}.csv"


def _fmt(v: Any, kind: str = "num") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    if kind == "money":
        return format_money(v)
    if kind == "money_d":
        return format_money_delta(v)
    if kind == "pct":
        return f"{float(v):.2f}%"
    if kind in ("calmar", "sharpe"):
        return f"{float(v):.2f}"
    if kind == "int":
        return f"{int(round(float(v)))}"
    return f"{float(v):.2f}"


def _delta(a: Any, b: Any) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if math.isnan(fa) or math.isnan(fb):
        return None
    return fa - fb


def _compare_table(title: str, books: dict[str, dict[str, Any]], arms: list[str], control: str) -> str:
    def g(arm: str, key: str) -> Any:
        return books.get(arm, {}).get(key)

    raw_rows: list[tuple[str, str, dict[str, Any]]] = [
        ("Universe size", "int", {a: g(a, "n_univ") for a in arms}),
        ("Symbols with trades", "int", {a: g(a, "n_sym") for a in arms}),
        ("Total trades", "int", {a: g(a, "n") for a in arms}),
        ("Wins", "int", {a: g(a, "wins") for a in arms}),
        ("Losses", "int", {a: g(a, "losses") for a in arms}),
        ("Win %", "pct", {a: g(a, "wr") for a in arms}),
        ("Avg PnL %", "num", {a: g(a, "avg_pnl_pct") for a in arms}),
        ("Book AVG_PNL_PCT_WO_MAX", "num", {a: g(a, "wo_max") for a in arms}),
        ("Expectancy $", "money", {a: g(a, "exp_d") for a in arms}),
        ("Expectancy %", "num", {a: g(a, "exp_pct") for a in arms}),
        ("AvgR", "num", {a: g(a, "avg_r") for a in arms}),
        ("Avg win %", "num", {a: g(a, "avg_win") for a in arms}),
        ("Avg loss %", "num", {a: g(a, "avg_loss") for a in arms}),
        ("Win/Loss ratio (count)", "num", {a: g(a, "wl_count") for a in arms}),
        ("Win/Loss ratio $", "num", {a: g(a, "wl_d") for a in arms}),
        ("Profit factor", "num", {a: g(a, "pf") for a in arms}),
        ("Ann ROR %", "num", {a: g(a, "ann_ror") for a in arms}),
        ("Max DD %", "num", {a: g(a, "max_dd") for a in arms}),
        ("Calmar", "calmar", {a: g(a, "calmar") for a in arms}),
        ("Sharpe", "sharpe", {a: g(a, "sharpe") for a in arms}),
        ("Profit per capital day", "money", {a: g(a, "profit_day") for a in arms}),
        ("Capital days", "int", {a: g(a, "capital_days") for a in arms}),
        ("Avg days held", "num", {a: g(a, "avg_days") for a in arms}),
        ("Median days held", "num", {a: g(a, "med_days") for a in arms}),
        ("P90 days held", "num", {a: g(a, "p90_days") for a in arms}),
    ]
    wanted = set(canonical_book_order_html()) | {"AvgR", "Symbols with trades"}
    raw_rows = [r for r in raw_rows if r[0] in wanted or r[0] == "AvgR"]
    raw_rows = filter_html_compare_metric_rows(raw_rows, label_index=0)
    ths = [_sortable_th("Metric", "text")]
    for a in arms:
        ths.append(_sortable_th(a, "num"))
        if a != control:
            ths.append(_sortable_th(f"Δ {a}", "num"))
    body = []
    for label, kind, vals in raw_rows:
        tds = [f"<td>{html.escape(label)}</td>"]
        cv = vals.get(control)
        for a in arms:
            v = vals.get(a)
            tds.append(f"<td class='num'>{_fmt(v, kind)}</td>")
            if a != control:
                d = _delta(v, cv)
                dkind = "money_d" if kind == "money" else kind
                tds.append(f"<td class='num'>{_fmt(d, dkind)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    notes = [books[a].get("note") or "" for a in arms]
    note_html = ""
    if any(notes):
        note_html = "<p class='muted'>" + " · ".join(html.escape(n) for n in notes if n) + "</p>"
    return f"""
<h3>{html.escape(title)}</h3>
<p class="muted">Click column headers to sort. Total PnL $ / Sheet PnL $ omitted from HTML (canonical rule).</p>
<div class="table-wrap"><table class="sortable">
<caption>{html.escape(title)} — absolute values and deltas vs {html.escape(control)}</caption>
<thead><tr>{''.join(ths)}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table></div>
{note_html}
"""


def _symbol_table(rows: list[dict[str, Any]]) -> str:
    cols = [
        ("Symbol", "text", "symbol", "text"),
        ("N IS", "num", "n", "int"),
        ("Win %", "num", "wr", "pct"),
        ("Avg PnL %", "num", "avg_pnl_pct", "num"),
        ("AvgR", "num", "avg_r", "num"),
        ("PF", "num", "pf", "num"),
        ("Expectancy %", "num", "expectancy_pct", "num"),
        ("Sum PnL %", "num", "sum_pnl_pct", "num"),
        ("Med days", "num", "med_days", "num"),
        ("Worst %", "num", "worst_pct", "num"),
        ("Sym max DD %", "num", "max_dd_pct", "num"),
        ("First IS", "date", "first_is", "date"),
        ("Last IS", "date", "last_is", "date"),
        ("ADV20 $", "num", "adv20_dollars", "money"),
        ("Mkt cap", "num", "market_cap", "money"),
        ("Min zone %", "num", "min_zone_pct", "num"),
        ("Med zone %", "num", "med_zone_pct", "num"),
        ("Paul20", "text", "in_paul20", "text"),
    ]
    ths = [_sortable_th(lab, st) for lab, st, *_ in cols]
    body = []
    for r in rows:
        tds = []
        for lab, st, key, kind in cols:
            v = r.get(key)
            if kind == "date":
                tds.append(f"<td>{v.isoformat() if isinstance(v, date) else '—'}</td>")
            elif kind == "text":
                tds.append(f"<td>{html.escape(str(v or ''))}</td>")
            elif kind == "int":
                tds.append(f"<td class='num'>{_fmt(v, 'int')}</td>")
            elif kind == "pct":
                tds.append(f"<td class='num'>{_fmt(v, 'pct')}</td>")
            elif kind == "money":
                tds.append(f"<td class='num'>{_fmt(v, 'money')}</td>")
            else:
                tds.append(f"<td class='num'>{_fmt(v, 'num')}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f"""
<div class="table-wrap"><table class="sortable">
<caption>Per-symbol in-sample book — click column headers to sort. Default order is N trades descending. Not a recommended list.</caption>
<thead><tr>{''.join(ths)}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table></div>
"""


def _oos_line(book: dict[str, Any]) -> str:
    return (
        f"OOS report-only (entry ≥ 2024-01-01): N={book['n']:,}  WR={book['wr']:.1f}%  "
        f"Avg={book['avg_pnl_pct']:+.2f}%  PF={book['pf']:.2f}  "
        f"Ann ROR={_fmt(book.get('ann_ror'), 'num')}%  Max DD={_fmt(book.get('max_dd'), 'num')}%. "
        "Do not rank or cut the universe on OOS."
    )


def write_reports(
    *,
    adopted_rows: list[dict[str, Any]],
    pin_rows: list[dict[str, Any]],
    sym_rows: list[dict[str, Any]],
    meta: dict[str, Any],
    n_univ: int,
    mcap_n: int,
    adv_n: int,
) -> list[Path]:
    cash_ad = float(meta.get("cash") or SHEET_CASH)
    ad_full = _book_from_rows(adopted_rows, cash=cash_ad, n_univ=n_univ)
    ad_is = _book_from_rows(
        _slice_rows(adopted_rows, "IS"),
        cash=cash_ad,
        n_univ=n_univ,
        end_date_exclusive=IS_CUT,
    )
    ad_oos = _book_from_rows(
        _slice_rows(adopted_rows, "OOS"),
        cash=cash_ad,
        n_univ=n_univ,
        start_date=IS_CUT,
    )
    pin_is = _book_from_rows(
        _slice_rows(pin_rows, "IS"),
        cash=SHEET_CASH,
        n_univ=n_univ,
        end_date_exclusive=IS_CUT,
    )
    pin_full = _book_from_rows(pin_rows, cash=SHEET_CASH, n_univ=n_univ)
    pin_oos = _book_from_rows(
        _slice_rows(pin_rows, "OOS"),
        cash=SHEET_CASH,
        n_univ=n_univ,
        start_date=IS_CUT,
    )

    headline = (
        f"IS adopted (min-zone 1%): N={ad_is['n']:,}  WR={ad_is['wr']:.1f}%  "
        f"Avg={ad_is['avg_pnl_pct']:+.2f}%  PF={ad_is['pf']:.2f}  "
        f"Ann ROR={_fmt(ad_is.get('ann_ror'), 'num')}%  symbols={ad_is.get('n_sym')}"
    )
    (STAMP_DIR / "HEADLINE.txt").write_text(
        headline + "\n" + _oos_line(ad_oos) + "\n",
        encoding="utf-8",
    )

    baseline = f"""# WRL min-zone 1% adopt — IS universe pick — 2026-09-22

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

Weekly Range / Swing (WRL) waits for a daily close in last week's lower pocket, then buys if price trades back up through that week's low. You liked the first-pass arm that **refuses skinny demand zones** (the pocket must be at least 1% tall). That arm was only a modest lift on Paul Twenty (HOLD, not KEEP), but you asked to **adopt it as the new freeze** and re-run the **full name list** so you can sort symbols and cut a tradable universe yourself.

This page is that full-universe in-sample scorecard. It is **not** a recommended list. After you pick names, we re-score that list under this freeze (in-sample and out-of-sample). That later score is selection-biased until we label it. Not gold. Not DailyRun.

## Delta from prior

Parent stamp: `{PARENT}` (Paul Twenty first-pass A/B, 2026-09-22).

| Knob | Parent control | This freeze |
|---|---|---|
| `wrl_min_zone_pct` | `0` (off) | **`0.01` (1% ON)** — the one change |
| `wrl_target_mode` / `wrl_scale_frac` | scale / 0.50 | same |
| `stop_pct` | 1.0 at swing low | same |
| `wrl_time_stop_bars` | 0 | same |
| `symbol_reentry_cooldown_days` | 0 | same — engine never assigns `cooldown_until`; not silently wired |
| Host | `$500k × 2.0 × 0.6` | same |
| Universe | Paul Twenty | **full WRL / rocket_wrl ALL** (same discovery as `{PIN_CLOSED.name}`) |

Parent IS on Paul Twenty for `ENTRY_minzone01` vs control: WR +2.8pp, Avg +0.10 — overall **HOLD**. You adopted anyway. This stamp does **not** re-judge that adopt and does **not** retune on OOS.

## Freeze (locked)

{FREEZE}

IS = `entry_date < 2024-01-01`. OOS is report-only. Do not retune on OOS. Do not pick names from OOS.

## Compare pin (control, no second engine run)

Old full-universe control (min-zone off) = published Closed `{PIN_CLOSED.name}` (6 Sep 2026 production stamp). IS slice of that file vs this adopted full run's IS slice. Ann ROR / Max DD from Closed overlay (`compare_format.overlay_ann_ror_max_dd`), not a new host equity curve.

## Selection bias

Universe pick from this IS table is the correct house step. After you choose names, we must **re-score IS and OOS under this freeze** on that list. Choosing names after seeing this table is in-sample selection. Research candidate only.

## Promotion

Research only. Not gold. Not DailyRun. No `run_wrl.bat` change.

## Engine

- `stock_analysis/rocket_wrl.py` + `wrl_zones.py`
- Runner: `tools/wrl_minzone01_is_universe_20260922.py`
- Stamp: `{meta.get("ts", "")}` · {meta.get("n_files", "?")} CSVs · {meta.get("elapsed_s", 0):.0f}s
- Host dollar-scale applied to Closed dollars; host equity curve skipped (not needed to pick names)
- ADV20 = last 20 local bars (Volume × Close). Market cap = cache only (`yfinance_cache.json` / `fundamentals_cache.duckdb`); {mcap_n} names hit, {adv_n} have ADV20. No Yahoo fetch.
"""
    (STAMP_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")
    (STAMP_DIR / "HYPOTHESIS.md").write_text(
        "\n".join(
            [
                "# Hypothesis test — WRL min-zone 1% adopt / IS universe 20260922",
                "",
                "| Field | Fill |",
                "|---|---|",
                "| System / prefix | WRL — Weekly Range / Swing |",
                f"| Baseline stamp | parent `{PARENT}` control; adopt `ENTRY_minzone01` |",
                "| Universe | full rocket_wrl ALL (not Paul Twenty) — then Paul cuts names from IS table |",
                "| Evidence | Parent first-pass `ENTRY_minzone01` modest IS lift on Paul Twenty (WR +2.8pp, Avg +0.10). PO adopt of a HOLD arm. |",
                "| Hypothesis | 1% min-zone is now the freeze; a per-symbol IS book on the full universe lets Paul cut a tradable list. |",
                "| Single knob | `wrl_min_zone_pct=0.01` (delta from prior control `0`) |",
                f"| Frozen settings | {FREEZE} |",
                "| Alternatives | none this stamp — adopt, do not sweep |",
                f"| Decision | adopt already decided by PO. This stamp is the IS summary for universe pick. Pin compare vs `{PIN_CLOSED.name}` IS. |",
                "| PO sign-off | adopt of min-zone 1% freeze — yes (this request). Universe list — **you choose**. Gold — no. |",
                "| Reconcile freeze | no — research only |",
                "",
                "After names are chosen: re-score IS/OOS under this freeze. Label selection bias. Do not gold from this table.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    is_books = {"PIN_Closed_IS (min-zone off)": pin_is, "ADOPTED_minzone01_IS": ad_is}
    oos_books = {"PIN_Closed_OOS (min-zone off)": pin_oos, "ADOPTED_minzone01_OOS": ad_oos}
    full_books = {"PIN_Closed_FULL": pin_full, "ADOPTED_minzone01_FULL": ad_full}

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WRL min-zone 1% — IS universe pick — 2026-09-22</title>
<style>
  :root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
    --card:#fff; --accent:#2a4a5c; --ok:#2d6a4f; --ok-bg:#e8f2ec;
    --warn:#8a5a12; --warn-bg:#f7efe0; --bad:#9b2226; --bad-bg:#fdecea; --fill:#f0eee6; }}
  body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",Georgia,serif; font-size:15px;
    line-height:1.55; color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:1.55rem; margin:0 0 8px; }}
  h2 {{ font-size:1.12rem; margin:26px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:1.0rem; margin:18px 0 8px; }}
  .lede, .muted {{ color:var(--muted); }}
  .badge {{ display:inline-block; font-size:0.75rem; font-weight:700; padding:2px 8px; background:var(--bad-bg); color:var(--bad); }}
  .callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:12px 0; }}
  .callout.ok {{ background:var(--ok-bg); border-left-color:var(--ok); }}
  .callout.warn {{ background:var(--warn-bg); border-left-color:var(--warn); }}
  .callout.bad {{ background:var(--bad-bg); border-left-color:var(--bad); }}
  .table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
  thead th {{ background:var(--fill); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
  code {{ background:var(--fill); padding:0.08em 0.3em; }}
  .heads {{ display:flex; flex-wrap:wrap; gap:10px; margin:12px 0; }}
  .stat {{ background:var(--card); border:1px solid var(--line); padding:10px 14px; min-width:120px; }}
  .stat .v {{ font-size:1.25rem; font-weight:700; font-variant-numeric:tabular-nums; }}
  .stat .l {{ font-size:0.75rem; color:var(--muted); }}
  th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
  th.sortable-th:hover {{ background:#e4e4dc; }}
  .sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
  th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
  th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
  {SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <p class="muted">WRL philosophy: <code>docs/systems/wrl.html</code> · research stamp 2026-09-22 · parent <code>{html.escape(PARENT)}</code></p>
  <h1>WRL — Weekly Range / Swing · min-zone 1% adopt · IS universe pick</h1>
  <div class="badge">Research candidate — not gold — not DailyRun</div>
  <p class="lede">Full universe · freeze = parent control + 1% min-zone · IS for you to cut names · OOS report-only.</p>

  <div class="callout">
    <strong>What you asked</strong>
    <p>{html.escape(ORIGINAL_REQUEST)}</p>
  </div>
  <div class="callout">
    <strong>In plain English</strong>
    <p>Weekly Range / Swing (WRL) is a weekly demand-zone idea: wait for a daily close in the pocket
    under last week’s range, then buy the next session if price trades back up through that week’s low
    (a buy-stop, not a chase). “Min-zone 1%” means we skip pockets that are thinner than 1%
    (range low versus swing low). You liked that setting on Paul Twenty even though the house verdict
    was HOLD, not KEEP. This run applies that one change to the <em>full</em> name list — the same
    firehose as the 6 Sep 2026 production Closed book — and shows each symbol’s in-sample record
    so <em>you</em> can sort and cut a universe.</p>
    <p>In-sample means trades that opened before 1 Jan 2024. That is the correct window for picking
    names. Out-of-sample is printed once so we do not hide it; do not use it to rank or drop names.
    After you choose, we re-score that list. Choosing after seeing this table is in-sample selection.
    Not gold. Not DailyRun.</p>
  </div>

  <h2>Adopted freeze</h2>
  <p>{html.escape(FREEZE)}</p>
  <p class="muted">Delta from prior: only <code>wrl_min_zone_pct</code> 0 → 0.01. Cooldown stays off
  (engine never sets <code>cooldown_until</code>). Full write-up in <code>BASELINE.md</code>.</p>

  <h2>Book-level IS headline (adopted freeze)</h2>
  <div class="heads">
    <div class="stat"><div class="v">{ad_is['n']:,}</div><div class="l">IS trades</div></div>
    <div class="stat"><div class="v">{ad_is['wr']:.1f}%</div><div class="l">Win %</div></div>
    <div class="stat"><div class="v">{ad_is['avg_pnl_pct']:+.2f}%</div><div class="l">Avg PnL %</div></div>
    <div class="stat"><div class="v">{ad_is['pf']:.2f}</div><div class="l">Profit factor</div></div>
    <div class="stat"><div class="v">{_fmt(ad_is.get('ann_ror'), 'num')}%</div><div class="l">Ann ROR % (overlay)</div></div>
    <div class="stat"><div class="v">{ad_is.get('n_sym') or 0:,}</div><div class="l">Symbols with IS trades</div></div>
  </div>
  <div class="callout warn"><strong>OOS — report only.</strong> {html.escape(_oos_line(ad_oos))}</div>
  <div class="callout warn"><strong>Selection bias.</strong> Pick names from the IS table below.
  We will re-score the chosen universe under this freeze (IS + OOS) after you choose.
  Do not treat this table as gold or wire DailyRun.</div>

  <h2>Canonical compare — adopted full-IS vs published Closed IS (min-zone off)</h2>
  <p>Control pin = <code>{html.escape(PIN_CLOSED.name)}</code> (6 Sep 2026 production, min-zone off).
  No second full control engine run. Overlay Ann ROR / Max DD / Sharpe from Closed (no host equity curve on this stamp).
  Dollars on the pin are the published host-scaled file; adopted dollars use the same host formula on this run.
  Judge quality (WR, Avg%, PF, DD) — not trade count, not Total PnL.</p>
  {_compare_table("IS (entry &lt; 2024-01-01) — decide / cut here", is_books, ["PIN_Closed_IS (min-zone off)", "ADOPTED_minzone01_IS"], "PIN_Closed_IS (min-zone off)")}

  <h2>OOS (report only — do not cut here)</h2>
  {_compare_table("OOS (entry ≥ 2024-01-01)", oos_books, ["PIN_Closed_OOS (min-zone off)", "ADOPTED_minzone01_OOS"], "PIN_Closed_OOS (min-zone off)")}

  <h2>FULL book (context)</h2>
  {_compare_table("FULL (all entries)", full_books, ["PIN_Closed_FULL", "ADOPTED_minzone01_FULL"], "PIN_Closed_FULL")}

  <h2>Per-symbol IS summary — you choose the universe</h2>
  <p class="muted">{len(sym_rows):,} symbols with at least one IS trade.
  ADV20 from local last-20 bars ({adv_n} names). Market cap from cache only ({mcap_n} hits) — no Yahoo fetch.
  Zone % = <code>(RANGE_LOW / SWING_LOW − 1) × 100</code> (the min-zone gate is 1.0).
  AvgR = PnL% / stop-distance % (entry to swing-low stop).
  Sym max DD % = peak-to-trough of that name’s cumulative IS PnL% (not book Max DD).
  <code>Paul20</code> = already on Paul Twenty (flag only; not a recommendation).
  CSV: <code>WRL_IS_SymbolSummary.csv</code> and <code>drive/WRL_IS_SymbolSummary_minzone01.csv</code>.</p>
  {_symbol_table(sym_rows)}

  <p class="muted">Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M"))} ·
  <code>tools/wrl_minzone01_is_universe_20260922.py</code> · stamp {html.escape(str(meta.get("ts") or ""))} ·
  research ≠ gold ≠ DailyRun</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    summary = STAMP_DIR / "summary.html"
    compare = STAMP_DIR / "compare.html"
    summary.write_text(html_page, encoding="utf-8")
    compare.write_text(html_page, encoding="utf-8")
    print(f"[WRL-MZ01] wrote {summary}", flush=True)
    print(f"[WRL-MZ01] {headline}", flush=True)
    return [summary, compare, STAMP_DIR / "BASELINE.md", STAMP_DIR / "HYPOTHESIS.md"]


def _latest_closed(stamp_dir: Path) -> Optional[Path]:
    files = sorted(stamp_dir.glob("WRL_Closed_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    skip = {"WRL_Closed_IS"}
    for p in files:
        if "LatestRun" in p.name:
            continue
        if any(s in p.name for s in skip):
            continue
        return p
    return files[0] if files else None


def _rows_from_closed_csv(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            out.append(_row_from_closed_dict(row))
    return out


def _ntfy(paths: list[Path]) -> None:
    ntfy = REPO / "tools" / "ntfy_job_done.py"
    if not ntfy.is_file():
        return
    cmd = [sys.executable, str(ntfy)]
    for p in paths:
        if p.suffix.lower() == ".html" and "drive" in p.as_posix():
            cmd.extend(["--path", str(p)])
    cmd.extend(["-t", "WRL min-zone 1% IS universe"])
    if cmd.count("--path") == 0:
        return
    os.system(" ".join(f'"{c}"' if " " in c else c for c in cmd))


def main() -> int:
    ap = argparse.ArgumentParser(description="WRL min-zone 1% adopt — full-universe IS summary")
    ap.add_argument("--workers", type=int, default=max(1, min(12, os.cpu_count() or 4)))
    ap.add_argument("--summarize-only", action="store_true")
    args = ap.parse_args()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)

    if args.summarize_only:
        closed_path = _latest_closed(STAMP_DIR)
        if not closed_path:
            print("[WRL-MZ01] no Closed in stamp; run without --summarize-only", flush=True)
            return 1
        print(f"[WRL-MZ01] summarize-only from {closed_path}", flush=True)
        adopted_dicts_raw = None
        rows = _rows_from_closed_csv(closed_path)
        adv: dict[str, tuple[Optional[float], Optional[float]]] = {}
        # cheap ADV20 for symbols that appear
        need = {r["symbol"] for r in rows if r.get("symbol")}
        for sym in need:
            p = DATA_DIR / f"{sym}.csv"
            if not p.is_file():
                continue
            df = _load_symbol_frame(p)
            if df is None:
                continue
            adv[sym] = _adv20_from_df(df)
        meta = {"ts": closed_path.stem.replace("WRL_Closed_", ""), "n_files": len(need), "elapsed_s": 0, "cash": SHEET_CASH}
        closed_dicts_for_rows = None
        adopted_rows = rows
        n_univ = len(_list_universe_files())
    else:
        closed_dicts, adv, meta, closed_path = _run_engine(int(args.workers))
        adopted_rows = [_row_from_closed_dict(d) for d in closed_dicts]
        n_univ = int(meta.get("n_files") or 0)

    mcap = _load_mcap_cache()
    paul20 = _load_paul20()
    is_rows = _slice_rows(adopted_rows, "IS")
    # write IS-only Closed slice
    ts = str(meta.get("ts") or time.strftime("%y%m%d%H%M%S"))
    is_closed = STAMP_DIR / f"WRL_Closed_IS_{ts}.csv"
    src = _latest_closed(STAMP_DIR)
    if src and src.is_file():
        with src.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or WRL_CLOSED_HEADER
            keep = []
            for row in reader:
                opened = _parse_ymd(row.get("DATE_OPENED"))
                if opened and opened < IS_CUT:
                    keep.append(row)
        with is_closed.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(keep)

    pin_rows = _load_pin_rows()
    print(f"[WRL-MZ01] pin Closed rows={len(pin_rows)}  adopted={len(adopted_rows)}  IS={len(is_rows)}", flush=True)
    sym_rows = _per_symbol_is(is_rows, adv=adv, mcap=mcap, paul20=paul20)
    csv_stable = STAMP_DIR / "WRL_IS_SymbolSummary.csv"
    csv_ts = STAMP_DIR / f"WRL_IS_SymbolSummary_{ts}.csv"
    _write_summary_csv(csv_stable, sym_rows)
    _write_summary_csv(csv_ts, sym_rows)
    _write_summary_csv(DRIVE_COPY, sym_rows)
    print(f"[WRL-MZ01] wrote {csv_stable} ({len(sym_rows)} symbols)", flush=True)

    adv_n = sum(1 for v in adv.values() if v[0] is not None)
    htmls = write_reports(
        adopted_rows=adopted_rows,
        pin_rows=pin_rows,
        sym_rows=sym_rows,
        meta=meta,
        n_univ=n_univ,
        mcap_n=len(mcap),
        adv_n=adv_n,
    )
    _ntfy([p for p in htmls if p.suffix.lower() == ".html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
