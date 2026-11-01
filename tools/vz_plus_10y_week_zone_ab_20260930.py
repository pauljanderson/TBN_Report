#!/usr/bin/env python3
"""VZ plus a second zone: highest-volume WEEK in the trailing 10 years.

Control is the frozen DailyRun Volume Zone (VZ) book:
  126-session max-volume DAY, High–Low zone, Paul78.142, EXIT_atr4_s025_r15_ts20.

Candidate keeps that zone and ALSO draws a High–Low zone from the single
highest-volume completed ISO week in the trailing 10 calendar years.
One position per symbol. Research only. Does not touch the house pin.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from vol_zone_break_retest import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    Zone,
    atr14,
    build_zones,
    load_ohlcv,
    load_universe_symbols,
    run_symbol_with_params,
    sortable_th,
)
from rocket_vz import (  # noqa: E402
    VzConfig,
    enrich_trade_rows,
    exit_spec_from_cfg,
    filter_sigs_max_rsi14_at_entry,
    filter_sigs_min_atr_pct,
    filter_sigs_min_dist_52w_at_trigger,
    params_from_cfg,
)
from compare_format import format_money  # noqa: E402

STAMP = "vz_plus_10y_week_zone_20260930"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
DATA_DIR = REPO / "data" / "newdata" / "data"
UNIV_PATH = REPO / "drive" / "universes" / "VZ_universe.csv"
IS_CUT = date(2024, 1, 1)
WEEK_YEARS = 10
LOOKBACK_DAYS = 126  # frozen trailing window; not 26 weeks and not 182 calendar days

ORIGINAL_REQUEST = (
    "how might we be able to expand on our VZ idea? can we draw more zones than just "
    "the highest volume in the last 6 months? what happens to our results if we also "
    "draw a zone for the highest volume week in the past 10-year period? can you send "
    "me a compare + ntfy when done?"
)


def _shift_years(ts: pd.Timestamp, years: int) -> pd.Timestamp:
    """Calendar years. Feb 29 lands on Feb 28."""
    y = int(ts.year) + int(years)
    try:
        return ts.replace(year=y)
    except ValueError:
        return ts.replace(year=y, day=28)


def build_10y_week_hl_zones(df: pd.DataFrame) -> tuple[list[Zone], dict[str, Any]]:
    """Persistent HL zones from the rolling max-volume completed ISO week.

    Frozen before P&L:
    - A week is an ISO week (Monday–Sunday) of sessions present in the file.
    - Week volume is the sum of those sessions' volume. The band is that week's
      low to that week's high (same High–Low idea as the day zone).
    - A week qualifies only after it has closed: every week that is followed by
      a later week, plus a final week only when its last bar is a Friday.
    - As of day t, the winner is the highest volume among closed weeks whose
      close date is inside (t minus 10 calendar years, t]. Ties keep the earlier week.
    - No zone is drawn until the symbol's first bar is at least 10 calendar
      years before t. Until then the 10-year zone is absent.
    - The zone is born on the first day it is that winner (on or after the
      week's close). Touches and breaks start the next session.
    """
    dates = pd.to_datetime(df["Date"])
    iso = dates.dt.isocalendar()
    iso_year = iso.year.to_numpy()
    iso_week = iso.week.to_numpy()
    vol = df["Volume"].to_numpy(dtype=np.float64)
    highs = df["High"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    n = len(df)
    meta: dict[str, Any] = {
        "n_closed_weeks": 0,
        "n_week_zones": 0,
        "history_years": 0.0,
        "week_eligible": False,
        "first_bar": "",
        "last_bar": "",
    }
    if n == 0:
        return [], meta
    first = pd.Timestamp(dates.iloc[0]).normalize()
    last = pd.Timestamp(dates.iloc[-1]).normalize()
    meta["first_bar"] = str(first.date())
    meta["last_bar"] = str(last.date())
    meta["history_years"] = (last - first).days / 365.25

    weeks: list[dict[str, Any]] = []
    i = 0
    while i < n:
        y = int(iso_year[i])
        w = int(iso_week[i])
        j = i + 1
        while j < n and int(iso_year[j]) == y and int(iso_week[j]) == w:
            j += 1
        end = j - 1
        followed = j < n
        friday = int(pd.Timestamp(dates.iloc[end]).weekday()) == 4
        if followed or friday:
            v = float(vol[i : end + 1].sum())
            lo = float(np.min(lows[i : end + 1]))
            hi = float(np.max(highs[i : end + 1]))
            if v > 0 and math.isfinite(lo) and math.isfinite(hi) and hi > lo:
                weeks.append(
                    {
                        "end": end,
                        "end_date": pd.Timestamp(dates.iloc[end]).normalize(),
                        "volume": v,
                        "lo": lo,
                        "hi": hi,
                    }
                )
        i = j
    meta["n_closed_weeks"] = len(weeks)
    if not weeks:
        return [], meta

    first_eligible = _shift_years(first, WEEK_YEARS)
    active: deque[int] = deque()
    nxt = 0
    first_active: dict[int, int] = {}
    last_active: dict[int, int] = {}
    order: list[int] = []

    for t in range(n):
        t_date = pd.Timestamp(dates.iloc[t]).normalize()
        if t_date < first_eligible:
            continue
        meta["week_eligible"] = True
        while nxt < len(weeks) and int(weeks[nxt]["end"]) <= t:
            active.append(nxt)
            nxt += 1
        cutoff = _shift_years(t_date, -WEEK_YEARS)
        while active and weeks[active[0]]["end_date"] < cutoff:
            active.popleft()
        if not active:
            continue
        best = active[0]
        best_v = float(weeks[best]["volume"])
        for k in list(active)[1:]:
            v = float(weeks[k]["volume"])
            if v > best_v:
                best = k
                best_v = v
        if best not in first_active:
            first_active[best] = t
            order.append(best)
        last_active[best] = t

    zones: list[Zone] = []
    for k in order:
        wk = weeks[k]
        created_t = int(first_active[k])
        if created_t < int(wk["end"]):
            raise AssertionError("week zone created before the week closed")
        if pd.Timestamp(dates.iloc[created_t]).normalize() < first_eligible:
            raise AssertionError("week zone created before 10 years of history")
        end_date = pd.Timestamp(wk["end_date"])
        zones.append(
            Zone(
                zone_id=f"HL_W10_{end_date.date()}",
                kind="HL",
                max_vol_idx=int(wk["end"]),
                max_vol_date=end_date,
                volume=int(wk["volume"]),
                lo=float(wk["lo"]),
                hi=float(wk["hi"]),
                created_on_idx=created_t,
                created_on=pd.Timestamp(dates.iloc[created_t]),
                last_winner_idx=int(last_active[k]),
                last_winner_date=pd.Timestamp(dates.iloc[last_active[k]]),
            )
        )
    meta["n_week_zones"] = len(zones)
    return zones, meta


def _book(
    symbol: str,
    df: pd.DataFrame,
    atr: np.ndarray,
    zones: list[Zone],
    cfg: VzConfig,
    params,
    exit_spec,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    sigs, _, _ = run_symbol_with_params(symbol, df, zones, atr, params)
    n_raw = len(sigs)
    sigs = filter_sigs_min_atr_pct(
        sigs, df, atr, float(cfg.min_atr_pct_at_entry or 0.0)
    )
    sigs = filter_sigs_min_atr_pct(
        sigs, df, atr, float(cfg.min_atr_pct_at_trigger or 0.0), at_trigger=True
    )
    sigs = filter_sigs_min_dist_52w_at_trigger(
        sigs, df, float(cfg.min_dist_to_52w_high_pct_at_trigger or 0.0)
    )
    sigs = filter_sigs_max_rsi14_at_entry(sigs, df, float(cfg.max_rsi14_at_entry or 0.0))
    closed, opens = enrich_trade_rows(
        symbol,
        df,
        sigs,
        params,
        atr,
        exit_spec,
        cfg.sheet_notional,
        cooldown_after_target_days=int(cfg.cooldown_after_target_days or 0),
    )
    return closed, opens, n_raw


def _strip_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k != "_signal" and not str(k).startswith("_")}
    zid = str(out.get("ZONE_ID") or "")
    out["ZONE_SOURCE"] = "10y_week" if zid.startswith("HL_W10_") else "6m_day"
    return out


def process_symbol(sym: str) -> dict[str, Any]:
    cfg = VzConfig()
    # Freeze guard: do not silently drift off the house knobs.
    assert int(cfg.lookback_days) == LOOKBACK_DAYS
    assert int(cfg.retest_window) == 63
    assert str(cfg.entry_on) == "next_open"
    assert tuple(cfg.zone_kinds) == ("HL",)
    assert bool(cfg.first_retest_only) is True
    assert int(cfg.min_touches_before_entry) == 1
    assert abs(float(cfg.retest_eps_pct) - 0.005) < 1e-12
    assert abs(float(cfg.min_atr_pct_at_trigger) - 4.0) < 1e-12
    assert abs(float(cfg.min_atr_pct_at_entry)) < 1e-12
    assert abs(float(cfg.stop_atr_buffer) - 0.25) < 1e-12
    assert abs(float(cfg.target_r) - 1.5) < 1e-12
    assert int(cfg.exit_bars) == 20
    assert int(cfg.cooldown_after_target_days) == 10
    assert bool(cfg.require_hvn_overlap) is False
    assert str(cfg.exit_name) == "EXIT_atr4_s025_r15_ts20"

    csv_path = DATA_DIR / f"{sym}.csv"
    if not csv_path.is_file():
        return {"symbol": sym, "status": "missing", "note": f"missing {csv_path.name}"}
    try:
        df = load_ohlcv(csv_path)
        atr = atr14(df)
        params = params_from_cfg(cfg)
        exit_spec = exit_spec_from_cfg(cfg)
        day_zones = build_zones(df, params.lookback_days)
        week_zones, meta = build_10y_week_hl_zones(df)
        c_closed, c_open, c_raw = _book(sym, df, atr, day_zones, cfg, params, exit_spec)
        k_closed, k_open, k_raw = _book(
            sym, df, atr, list(day_zones) + list(week_zones), cfg, params, exit_spec
        )
    except Exception as exc:  # noqa: BLE001 — research scan keeps going
        return {"symbol": sym, "status": "error", "note": str(exc)}
    return {
        "symbol": sym,
        "status": "ok",
        "meta": meta,
        "n_day_zones": sum(1 for z in day_zones if z.kind == "HL"),
        "control_raw": c_raw,
        "candidate_raw": k_raw,
        "control_closed": [_strip_row(r) for r in c_closed],
        "control_open": [_strip_row(r) for r in c_open],
        "candidate_closed": [_strip_row(r) for r in k_closed],
        "candidate_open": [_strip_row(r) for r in k_open],
    }


def _parse_d(s: Any) -> Optional[date]:
    t = str(s or "").strip()
    if not t:
        return None
    compact = t.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((t[:10], "%Y-%m-%d"), (compact, "%Y%m%d")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _f(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x


def rows_to_trades(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for raw in rows:
        opened = _parse_d(raw.get("DATE_OPENED"))
        closed = _parse_d(raw.get("DATE_CLOSED"))
        if opened is None or closed is None:
            continue
        pnl = _f(raw.get("PNL_PCT"), 0.0)
        trades.append(
            {
                "sym": str(raw.get("SYMBOL") or "").upper(),
                "opened": opened,
                "closed": closed,
                "entry": _f(raw.get("ENTRY_PRICE")),
                "exit_px": _f(raw.get("EXIT_PRICE")),
                "pnl": pnl,
                "pnl_d": _f(raw.get("PNL_DOLLARS"), 0.0),
                "days": _f(raw.get("DAYS_HELD"), 0.0),
                "r": _f(raw.get("R_MULT"), 0.0),
                "exit": str(raw.get("EXIT_TYPE") or ""),
                "zone_id": str(raw.get("ZONE_ID") or ""),
                "source": str(raw.get("ZONE_SOURCE") or ""),
            }
        )
    return trades


def _exit_norm(raw: str) -> str:
    s = str(raw or "").strip().upper().replace(" ", "_")
    if s in {"STOP", "STOP_LOSS"} or "STOP" in s:
        return "STOP_LOSS"
    if "TARGET" in s:
        return "TARGET"
    if s == "TIME" or "TIME" in s:
        return "TIME"
    if "GAP_UP" in s:
        return "GAP_UP"
    if "GAP_DOWN" in s:
        return "GAP_DOWN"
    return s or "OTHER"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def fmt_num(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def fmt_delta(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:+.{nd}f}"


def _quality_line(label: str, m: dict[str, Any]) -> str:
    return (
        f"{label}: N={m['n']}, WR={fmt_num(m['wr'])}%, "
        f"avg {fmt_num(m['avg_pnl'])}%"
    )


METRIC_ROWS: list[tuple[str, str, str, bool]] = [
    # key, label, kind (num/money/pp), lower_better
    ("n", "Closed trades", "int", False),
    ("wins", "Wins", "int", False),
    ("losses", "Losses", "int", True),
    ("wr", "Win %", "num", False),
    ("avg_pnl", "Avg PnL %", "num", False),
    ("avg_wo_max", "AVG_PNL_PCT_WO_MAX", "num", False),
    ("med_pnl", "Median PnL %", "num", False),
    ("expectancy_pct", "Expectancy %", "num", False),
    ("expectancy_d", "Expectancy $", "money", False),
    ("avg_win", "Avg win %", "num", False),
    ("avg_loss", "Avg loss %", "num", False),
    ("wl_count", "Win/Loss count ratio", "num", False),
    ("wl_dollar", "Win/Loss $ ratio", "num", False),
    ("pf", "Profit factor", "num", False),
    ("ann_ror", "Ann ROR %", "num", False),
    ("max_dd", "Max DD %", "num", True),
    ("calmar", "Calmar", "num", False),
    ("sharpe", "Sharpe", "num", False),
    ("profit_per_cd", "Profit per capital day", "money", False),
    ("capital_days", "Capital days", "num", True),
    ("avg_days", "Avg days held", "num", True),
    ("med_days", "Median days held", "num", True),
    ("p90_days", "P90 days held", "num", True),
    ("trades_per_year", "Trades / year", "num", False),
    ("losing_streak", "Losing streak", "int", True),
    ("pct_max_sym", "Pct PnL max symbol", "num", True),
    ("pct_max_trade", "Pct PnL max trade", "num", True),
    ("pct_top10", "Pct PnL top 10 symbols", "num", False),
    ("mean_paul", "Mean Paul Score", "num", False),
    ("sum_paul", "Sum Paul Score", "num", False),
    ("mean_fit", "Mean FIT", "num", False),
    ("sum_fit", "Sum FIT", "num", False),
    ("mean_fit_r", "Mean robust FIT", "num", False),
    ("sum_fit_r", "Sum robust FIT", "num", False),
    ("mean_pf_sym", "Mean symbol profit factor", "num", False),
    ("mean_wo_sym", "Mean symbol AVG_PNL_PCT_WO_MAX", "num", False),
    ("mean_outlier", "Mean OUTLIER_PCT_OF_WINS", "num", True),
    ("mean_tpy", "Mean trades / year (symbol)", "num", False),
]


def _fit_get(m: dict[str, Any], key: str) -> float:
    fit = m.get("fit") or {}
    alias = {
        "mean_paul": "mean_paul",
        "sum_paul": "sum_paul",
        "mean_fit": "mean_fit",
        "sum_fit": "sum_fit",
        "mean_fit_r": "mean_fit_r",
        "sum_fit_r": "sum_fit_r",
        "mean_pf_sym": "mean_pf",
        "mean_wo_sym": "mean_wo",
        "mean_outlier": "mean_outlier",
        "mean_tpy": "mean_tpy",
    }
    return _f(fit.get(alias[key]) if key in alias else m.get(key))


def _metric_value(m: dict[str, Any], key: str) -> float:
    if key in {
        "mean_paul",
        "sum_paul",
        "mean_fit",
        "sum_fit",
        "mean_fit_r",
        "sum_fit_r",
        "mean_pf_sym",
        "mean_wo_sym",
        "mean_outlier",
        "mean_tpy",
    }:
        return _fit_get(m, key)
    return _f(m.get(key))


def _cell(kind: str, v: float) -> str:
    if not math.isfinite(v):
        return "—"
    if kind == "money":
        return format_money(v)
    if kind == "int":
        return str(int(round(v)))
    return fmt_num(v, 3 if kind == "num" else 2)


def _delta_cell(kind: str, d: float) -> str:
    if not math.isfinite(d):
        return "—"
    if kind == "money":
        sign = "+" if d >= 0 else "-"
        return f"{sign}{format_money(abs(d))}"
    if kind == "int":
        return f"{int(round(d)):+d}"
    return fmt_delta(d, 3)


def write_compare_html(
    path: Path,
    *,
    packs: dict[str, dict[str, Any]],
    verdict: str,
    verdict_why: str,
    oos_note: str,
    coverage: dict[str, Any],
    exit_rows: list[tuple[str, int, int]],
) -> None:
    ctrl = packs["control"]
    cand = packs["candidate"]

    def pack_table(slice_name: str, title: str) -> str:
        c = ctrl[slice_name]
        k = cand[slice_name]
        body = []
        for key, label, kind, _lower in METRIC_ROWS:
            cv = _metric_value(c, key)
            kv = _metric_value(k, key)
            dv = kv - cv if math.isfinite(cv) and math.isfinite(kv) else float("nan")
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(label)}</td>"
                f"<td>{_cell(kind, cv)}</td>"
                f"<td>{_cell(kind, kv)}</td>"
                f"<td>{_delta_cell(kind, dv)}</td>"
                "</tr>"
            )
        heads = "".join(
            [
                sortable_th("Metric", "text"),
                sortable_th("Control (6-month day zone)", "num"),
                sortable_th("Candidate (day + 10-year week)", "num"),
                sortable_th("Delta (candidate − control)", "num"),
            ]
        )
        return (
            f"<h2>{html_mod.escape(title)}</h2>"
            '<div class="table-wrap"><table class="sortable">'
            "<caption>Click column headers to sort.</caption>"
            f"<thead><tr>{heads}</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    q_rows = []
    for slice_name, label in (("full", "Full book"), ("is", "In-sample"), ("oos", "Out-of-sample")):
        c = ctrl[slice_name]
        k = cand[slice_name]
        q_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(label)}</td>"
            f"<td>{int(c['n'])}</td><td>{fmt_num(c['wr'])}</td><td>{fmt_num(c['avg_pnl'])}</td>"
            f"<td>{int(k['n'])}</td><td>{fmt_num(k['wr'])}</td><td>{fmt_num(k['avg_pnl'])}</td>"
            f"<td>{int(k['n']) - int(c['n']):+d}</td>"
            f"<td>{fmt_delta(k['wr'] - c['wr'])}</td>"
            f"<td>{fmt_delta(k['avg_pnl'] - c['avg_pnl'])}</td>"
            "</tr>"
        )
    q_heads = "".join(
        [
            sortable_th("Slice", "text"),
            sortable_th("Control N", "num"),
            sortable_th("Control WR %", "num"),
            sortable_th("Control avg %", "num"),
            sortable_th("Candidate N", "num"),
            sortable_th("Candidate WR %", "num"),
            sortable_th("Candidate avg %", "num"),
            sortable_th("Δ N", "num"),
            sortable_th("Δ WR pp", "num"),
            sortable_th("Δ avg %", "num"),
        ]
    )
    exit_heads = "".join(
        [
            sortable_th("Exit", "text"),
            sortable_th("Control N", "num"),
            sortable_th("Control %", "num"),
            sortable_th("Candidate N", "num"),
            sortable_th("Candidate %", "num"),
        ]
    )
    c_n = max(int(ctrl["full"]["n"]), 1)
    k_n = max(int(cand["full"]["n"]), 1)
    exit_body = []
    for name, cn, kn in exit_rows:
        exit_body.append(
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{cn}</td><td>{fmt_num(100.0 * cn / c_n)}</td>"
            f"<td>{kn}</td><td>{fmt_num(100.0 * kn / k_n)}</td>"
            "</tr>"
        )
    c_ex = sum(cn for _, cn, _ in exit_rows)
    k_ex = sum(kn for _, _, kn in exit_rows)
    exit_body.append(
        '<tr class="total-row">'
        "<td>Total</td>"
        f"<td>{c_ex}</td><td>100.00</td>"
        f"<td>{k_ex}</td><td>100.00</td>"
        "</tr>"
    )

    src = coverage
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ + 10-year week zone</title>
<style>
:root {{
  --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
  --card:#fff; --accent:#2a4a5c; --fill:#f0eee6;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Segoe UI", Helvetica, Arial, sans-serif; background:var(--bg); color:var(--ink); line-height:1.5; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:28px 20px 64px; }}
h1 {{ font-size:1.55rem; margin:0 0 8px; }}
h2 {{ font-size:1.12rem; margin:28px 0 8px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:12px 0 16px; }}
.callout.warn {{ background:#f7efe0; border-left-color:#8a5a12; }}
p {{ margin:0 0 10px; max-width:80ch; }}
code {{ font-family:Consolas, monospace; background:var(--fill); padding:0.05em 0.3em; }}
.table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; background:var(--card); }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
thead th {{ background:var(--fill); }}
caption {{ caption-side:top; text-align:left; color:var(--muted); font-size:0.82rem; margin:0 0 6px; }}
tr.total-row td {{ font-weight:700; background:#f4f1e8; }}
.badge {{ display:inline-block; font-weight:700; padding:2px 8px; background:#f7efe0; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
<h1>Volume Zone (VZ) plus a 10-year high-volume week</h1>
<p class="badge">{html_mod.escape(verdict)}</p>
<p>{html_mod.escape(verdict_why)}. {html_mod.escape(oos_note)}</p>

<div class="callout">
<h2 style="margin-top:0;border:0">What you asked</h2>
<p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
</div>
<div class="callout">
<h2 style="margin-top:0;border:0">In plain English</h2>
<p>A volume zone is a price area where a lot of shares traded. The current idea uses the busiest stretch in the last 6 months. In the frozen system that stretch is one day: the session with the most shares in the last 126 trading sessions (about six months of sessions, not 26 calendar weeks). This test also draws a second area from the single busiest week in the past 10 years, and then uses the same buy and sell rules on both areas.</p>
<p><strong>Control.</strong> One zone, the high and low of that busiest day. Buy only after price breaks above it and then comes back to it. Same name cannot hold two lots at once.</p>
<p><strong>Candidate.</strong> That same day zone stays. A second zone is added: the high and low of the single busiest completed week in the 10 years before the signal. Price can buy off either zone. If both say to buy the same name, only the first fill is taken. If they want in on the same day and their breaks are on the same bar, the original 6-month day zone is kept and the week zone waits.</p>
<p>Quality line — {_quality_line("Full control", ctrl["full"])}. {_quality_line("Full candidate", cand["full"])}. {_quality_line("IS control", ctrl["is"])}. {_quality_line("IS candidate", cand["is"])}. {_quality_line("OOS control", ctrl["oos"])}. {_quality_line("OOS candidate", cand["oos"])}.</p>
</div>

<h2>How the two zones interact</h2>
<p>Each zone is its own price band. They are not merged when they overlap or when one sits inside the other. A close above the inner high can start a break of the inner zone while price is still inside the outer zone. The only de-duplication is the house rule: one position per symbol, plus a 10-calendar-day pause after a target exit. A name without 10 years of history keeps the 6-month zone and has no 10-year zone until that history exists.</p>
<p>The week zone is born the first day that week is the busiest completed week in the trailing 10 years. That cannot happen until the symbol has 10 years of data. The buy is the same as a day zone: a close above the band, then a return to the band within 63 sessions. If the busiest week is an old climax and price is already far above that band when the zone is born, the next session counts as the break, and the trade only happens if price comes back within those 63 sessions. Many old weeks never do.</p>
<p>Coverage: {src["n_symbols"]} symbols requested, {src["n_ok"]} scanned, {src["n_missing"]} missing files, {src["n_error"]} errors, {src["n_short"]} with no 10-year week zone because history is shorter than 10 years. Closed trades from the week zone in the candidate book: {src["n_week_closed"]} of {src["n_cand_closed"]}. Open positions (not in the quality score): control {src["n_ctrl_open"]}, candidate {src["n_cand_open"]}.</p>

<h2>Quality line</h2>
<div class="table-wrap"><table class="sortable">
<caption>Win rate, average percent, and trade count. Click column headers to sort. In-sample is entry before 2024-01-01. Out-of-sample is entry on or after that date and is report-only.</caption>
<thead><tr>{q_heads}</tr></thead>
<tbody>{"".join(q_rows)}</tbody>
</table></div>

{pack_table("full", "Full book — canonical compare")}
{pack_table("is", "In-sample (entry before 2024-01-01) — judge on this slice")}
{pack_table("oos", "Out-of-sample (entry on or after 2024-01-01) — report only")}

<h2>Exit mix (closed trades)</h2>
<div class="table-wrap"><table class="sortable">
<caption>Click column headers to sort. The total row stays at the bottom.</caption>
<thead><tr>{exit_heads}</tr></thead>
<tbody>{"".join(exit_body)}</tbody>
</table></div>

<div class="callout warn">
<p>Research only. Not gold. Not DailyRun. This is an in-sample-capable horse-race: the full history is visible in the same report as the in-sample slice. The keep / hold / dismiss call uses the in-sample quality rule frozen before the run. Out-of-sample does not pick the winner and is not a retune trigger. Sheet dollars use a fixed $45,000 per trade. Annualized rate of return (Ann ROR) and max drawdown (Max DD) are a closed-trade overlay ($45,000 sheet cash, $500,000 starting account). Sharpe is from that exit-date equity, not a daily mark-to-market curve, so it is descriptive only. Days held are the house bar count. Average Daily Range is not a knob in this test. High Volume Node overlap stays off.</p>
</div>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def write_baseline(path: Path, coverage: dict[str, Any], verdict: str, verdict_why: str) -> None:
    text = f"""# BASELINE — VZ plus 10-year week zone — `{STAMP}`

## What you asked

{ORIGINAL_REQUEST}

## In plain English

A volume zone is a price area where a lot of shares traded. The current Volume Zone (VZ) idea uses the busiest day in the last 126 trading sessions (the frozen “about 6 months” window — not 26 weeks and not 182 calendar days). This test also draws a second area from the single busiest completed week in the past 10 calendar years, and uses the same buy and sell rules on both areas.

## Status

**Research candidate only.** Not gold. Not DailyRun. Do not wire `run_vz.bat`.

This stamp is an **in-sample-capable horse-race**: control and candidate are scored on the same full history, and the full-book table is visible before anyone reads the verdict. The verdict uses the in-sample rule frozen below. Out-of-sample is report-only. Do not retune on out-of-sample.

Verdict: **{verdict}**. {verdict_why}

## Frozen control (house VZ, unchanged)

| Knob | Value |
|---|---|
| Universe | Paul78.142 (`drive/universes/VZ_universe.csv`) — not changed |
| Zone | One High–Low band from the max-volume **day** in the trailing **126 sessions** |
| `lookback_days` | 126 |
| `zone_kinds` | HL only |
| `retest_window` | 63 |
| `retest_eps_pct` | 0.005 |
| `first_retest_only` | true |
| `min_touches_before_entry` | 1 |
| `entry_on` | next_open (signal known at the retest bar close; fill is the next open) |
| `min_atr_pct_at_trigger` | 4.0 (14-day Average True Range at least 4% of the trigger close). Entry-priced gate off |
| `require_hvn_overlap` | false |
| Exit | `EXIT_atr4_s025_r15_ts20` |
| Stop | zone low − 0.25 × 14-day Average True Range (ATR) |
| Target | 1.5R |
| Time stop | 20 bars |
| Cooldown | 10 calendar days after a TARGET exit, same symbol |
| Positions | one per symbol |

## The one candidate change

Add a second High–Low zone. Do not replace the 126-session day zone. Do not change stops, targets, the 6-month window, the universe, or the exit.

- Week = ISO week (Monday–Sunday) of sessions in the file.
- Week volume = sum of those sessions. Band = week low to week high.
- A week qualifies only after it has closed (a later week has started, or the file’s last week ends on a Friday). The current partial week is ignored.
- As of each day t, the winner is the highest-volume closed week whose close date is inside the trailing 10 calendar years (close date ≥ t − 10 years and ≤ t). An earlier week wins a volume tie.
- The zone is born the first day it is that winner, which is always on or after the week’s last session. Breaks and retests start the next session. No future volume.
- If the symbol’s first bar is less than 10 calendar years before t, the 10-year zone is absent. The 6-month day zone still trades.

## How two zones interact (frozen before P&L)

Same entry logic as house VZ, applied to each zone:

- Price can trigger off either zone (break above that zone’s high, then a support retest inside the 63-bar window).
- Two zones on the same name do **not** open two positions. `enrich_trade_rows` keeps one lot. A later signal while the name is still held is skipped. The 10-day post-target cooldown still applies to the symbol, whichever zone produced the target.
- Same entry bar: the earlier break is kept. If the break bar is also the same, the 6-month day zone id (`HL_YYYY-MM-DD`) sorts ahead of the week zone id (`HL_W10_YYYY-MM-DD`) in the house ordering, so the original zone is kept.
- Overlap: bands are not merged and not suppressed when one sits inside the other. An inner break can fire while price is still inside the outer band. One-position is the only de-duplication.
- The week zone is born the first day it is the trailing-10-year winner (on or after that week’s close, and only once 10 years of history exist). The house break is the first later close above the band. The retest clock is 63 sessions from that break. An old climax whose band is already far under price usually does not get a retest in time, so it adds no trade. That is the frozen entry logic, not a second knob.

## IS / OOS

- In-sample (IS) = `entry_date` < 2024-01-01. This is the judge.
- Out-of-sample (OOS) = `entry_date` ≥ 2024-01-01. Report-only.
- KEEP / LEAN KEEP / HOLD / DISMISS uses the same quality bars as `tools/vz_lookback_zonegap_ab_20260907.py` `verdict_is` (win rate, average R, average percent, profit factor, annualized rate of return, max drawdown, robust FIT, and sample size). Those bars were not fit on this stamp.
- If that rule would KEEP or LEAN KEEP and out-of-sample softens (`oos_softens` in that file), the stamp verdict is **HOLD**. Do not retune.

## Coverage

- Symbols requested: {coverage["n_symbols"]}
- Scanned: {coverage["n_ok"]}
- Missing file: {coverage["n_missing"]}
- Errors: {coverage["n_error"]}
- No 10-year week zone (history shorter than 10 years): {coverage["n_short"]}
- Candidate closed trades from the week zone: {coverage["n_week_closed"]} of {coverage["n_cand_closed"]}

## Metrics

Closed-trade overlay. Sheet notional $45,000. Initial account $500,000. Ann ROR uses `compare_format.overlay_ann_ror_max_dd`. Sharpe is the closed exit-date fallback (not √252 daily), labeled in the compare note. Paul Score and FIT come from the same symbol-fit helper as the 2026-09-07 lookback stamp. No daily equity curve, so days underwater and aggressive account PnL are not invented.

## Do not

- Overwrite older VZ freezes.
- Move the house pin or DailyRun.
- Call this gold.
"""
    path.write_text(text, encoding="utf-8")


def _attach_extras(stats: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Book-level trades/year and top-10 share. Does not change the frozen score keys."""
    out = dict(stats)
    if not trades:
        out["trades_per_year"] = float("nan")
        out["pct_top10"] = float("nan")
        return out
    first = min(t["opened"] for t in trades)
    last = max(t["closed"] for t in trades)
    span = max((last - first).days, 1) / 365.25
    out["trades_per_year"] = len(trades) / span
    by_sym: dict[str, float] = {}
    for t in trades:
        by_sym[t["sym"]] = by_sym.get(t["sym"], 0.0) + float(t["pnl_d"])
    tot = sum(float(t["pnl_d"]) for t in trades)
    top = sorted(by_sym.values(), reverse=True)[:10]
    out["pct_top10"] = (100.0 * sum(top) / tot) if tot else float("nan")
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", default="", help="Comma list; default = VZ universe")
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()
    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = load_universe_symbols(UNIV_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"symbols={len(symbols)} workers={args.workers}", flush=True)

    results: list[dict[str, Any]] = []
    workers = max(1, int(args.workers))
    if workers == 1 or len(symbols) == 1:
        for i, sym in enumerate(symbols, 1):
            results.append(process_symbol(sym))
            print(f"  {i}/{len(symbols)} {sym} {results[-1].get('status')}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(process_symbol, sym): sym for sym in symbols}
            done = 0
            for fut in as_completed(futs):
                done += 1
                row = fut.result()
                results.append(row)
                if done % 10 == 0 or row.get("status") != "ok":
                    print(f"  {done}/{len(symbols)} {row.get('symbol')} {row.get('status')}", flush=True)

    ok = [r for r in results if r.get("status") == "ok"]
    ctrl_rows: list[dict[str, Any]] = []
    cand_rows: list[dict[str, Any]] = []
    ctrl_open: list[dict[str, Any]] = []
    cand_open: list[dict[str, Any]] = []
    meta_rows: list[dict[str, Any]] = []
    for r in results:
        meta = r.get("meta") or {}
        meta_rows.append(
            {
                "SYMBOL": r.get("symbol"),
                "STATUS": r.get("status"),
                "NOTE": r.get("note", ""),
                "FIRST_BAR": meta.get("first_bar", ""),
                "LAST_BAR": meta.get("last_bar", ""),
                "HISTORY_YEARS": meta.get("history_years", ""),
                "WEEK_ELIGIBLE": meta.get("week_eligible", ""),
                "N_WEEK_ZONES": meta.get("n_week_zones", ""),
                "N_DAY_HL_ZONES": r.get("n_day_zones", ""),
                "CONTROL_RAW_SIGNALS": r.get("control_raw", ""),
                "CANDIDATE_RAW_SIGNALS": r.get("candidate_raw", ""),
                "CONTROL_CLOSED": len(r.get("control_closed") or []),
                "CANDIDATE_CLOSED": len(r.get("candidate_closed") or []),
            }
        )
        if r.get("status") != "ok":
            continue
        ctrl_rows.extend(r["control_closed"])
        cand_rows.extend(r["candidate_closed"])
        ctrl_open.extend(r["control_open"])
        cand_open.extend(r["candidate_open"])

    _write_csv(OUT_DIR / "control_closed.csv", ctrl_rows)
    _write_csv(OUT_DIR / "candidate_closed.csv", cand_rows)
    _write_csv(OUT_DIR / "control_open.csv", ctrl_open)
    _write_csv(OUT_DIR / "candidate_open.csv", cand_open)
    _write_csv(OUT_DIR / "symbol_coverage.csv", meta_rows)

    from vz_lookback_zonegap_ab_20260907 import (  # noqa: WPS433
        oos_softens,
        score_pack,
        verdict_is,
    )

    ctrl_tr = rows_to_trades(ctrl_rows)
    cand_tr = rows_to_trades(cand_rows)
    ctrl_pack = score_pack(ctrl_tr)
    cand_pack = score_pack(cand_tr)
    for pack, tr in ((ctrl_pack, ctrl_tr), (cand_pack, cand_tr)):
        for sl, subset in (
            ("full", tr),
            ("is", [t for t in tr if t["opened"] < IS_CUT]),
            ("oos", [t for t in tr if t["opened"] >= IS_CUT]),
        ):
            pack[sl] = _attach_extras(pack[sl], subset)

    label, why = verdict_is("CANDIDATE", cand_pack["is"], ctrl_pack["is"])
    softened = oos_softens(cand_pack["oos"], ctrl_pack["oos"])
    if label in {"KEEP", "LEAN KEEP"} and softened:
        verdict = "HOLD"
        why = (
            f"In-sample rule said {label} ({why}). Out-of-sample softened versus control, "
            "so the stamp is HOLD. OOS is report-only. Do not retune."
        )
    else:
        verdict = label
        if softened and label == "HOLD":
            why = why + " Out-of-sample also softer than control (report-only; not a retune)."
        elif softened:
            why = why + " Out-of-sample softened versus control (report-only; not a retune)."
    oos_note = (
        "Out-of-sample is softer than control on the pre-frozen soften check."
        if softened
        else "Out-of-sample did not trip the pre-frozen soften check. It still does not pick the winner."
    )

    exits_c = Counter(_exit_norm(t["exit"]) for t in ctrl_tr)
    exits_k = Counter(_exit_norm(t["exit"]) for t in cand_tr)
    names = sorted(set(exits_c) | set(exits_k))
    exit_rows = [(n, int(exits_c.get(n, 0)), int(exits_k.get(n, 0))) for n in names]

    coverage = {
        "n_symbols": len(symbols),
        "n_ok": len(ok),
        "n_missing": sum(1 for r in results if r.get("status") == "missing"),
        "n_error": sum(1 for r in results if r.get("status") == "error"),
        "n_short": sum(
            1
            for r in ok
            if not (r.get("meta") or {}).get("week_eligible")
        ),
        "n_week_closed": sum(1 for t in cand_tr if t["source"] == "10y_week"),
        "n_cand_closed": len(cand_tr),
        "n_ctrl_open": len(ctrl_open),
        "n_cand_open": len(cand_open),
    }
    write_compare_html(
        OUT_DIR / "compare.html",
        packs={"control": ctrl_pack, "candidate": cand_pack},
        verdict=verdict,
        verdict_why=why,
        oos_note=oos_note,
        coverage=coverage,
        exit_rows=exit_rows,
    )
    write_baseline(OUT_DIR / "BASELINE.md", coverage, verdict, why)
    print("VERDICT", verdict, flush=True)
    print("WHY", why, flush=True)
    for sl in ("full", "is", "oos"):
        c, k = ctrl_pack[sl], cand_pack[sl]
        print(
            f"{sl} ctrl N={c['n']} WR={c['wr']:.2f} avg={c['avg_pnl']:.3f} "
            f"PF={c['pf']:.3f} ROR={c['ann_ror']:.2f} DD={c['max_dd']:.2f} | "
            f"cand N={k['n']} WR={k['wr']:.2f} avg={k['avg_pnl']:.3f} "
            f"PF={k['pf']:.3f} ROR={k['ann_ror']:.2f} DD={k['max_dd']:.2f}",
            flush=True,
        )
    print("coverage", coverage, flush=True)
    err = [r for r in results if r.get("status") == "error"]
    for r in err[:8]:
        print("ERR", r.get("symbol"), r.get("note"), flush=True)


if __name__ == "__main__":
    main()
