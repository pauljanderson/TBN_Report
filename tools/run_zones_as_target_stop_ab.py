#!/usr/bin/env python3
"""Replay Closed trades using shared zone catalog levels as target/stop.

Hypothesis: for systems that do *not* compute zones (RS, RL, SB — and optionally
zone systems for comparison), does replacing static target%/stop% with the
nearest catalog zone above (target) and/or below (stop) change outcomes?

Arms test **one side at a time** as well as both together::

  - zones_target_only — zone above = target; keep Closed static stop
  - zones_stop_only   — zone below = stop; keep Closed static target
  - zones_as_ts       — both sides from catalog (prior arm)

This is **not** a product “zone exit” mode. Prior mid-run experiments
(``zone_exits`` / ``zone_exits_union``) attached zone DNA inside the same engine
run; this experiment uses a **shared persisted catalog** applied post-hoc to
each system's production entries. Zones are price levels only.

Pipeline::

  1. Ensure catalog exists (``tools/build_zone_catalog.py``)
  2. Load gold/LatestRun Closed per target system
  3. For each trade: apply catalog level(s) per arm; resimulate exits on OHLC
  4. Compare metrics vs control Closed

Fallback (document): missing zone above → keep static target; missing zone
below → keep static stop (trade still taken). RR arms (optional, both-sides
only): missing either side → **skip** trade.

Usage (repo root)::

  python tools/run_zones_as_target_stop_ab.py
  python tools/run_zones_as_target_stop_ab.py --systems RS,RL,SB,BRT,YH,WPBR,MTS
  python tools/run_zones_as_target_stop_ab.py --systems RS,RL,SB --rr ""
  python tools/run_zones_as_target_stop_ab.py --recompute-from-runs --systems RS,RL,SB,BRT,YH,WPBR,MTS
  python tools/run_zones_as_target_stop_ab.py --build-catalog

Default arms: control, zones_target_only, zones_stop_only, zones_as_ts, zones_rr2/3/4.

Writes ``drive/paul_experiments/zones_as_target_stop_ab/``.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
DRIVE = REPO / "drive"
OUT_ROOT = DRIVE / "paul_experiments" / "zones_as_target_stop_ab"
CATALOG_DIR = DRIVE / "paul_experiments" / "zone_catalog"
MARKTEN = {"AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"}

sys.path.insert(0, str(SA))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(OUT_ROOT.parent))

from ohlcv_store import load_symbol_df  # noqa: E402
from compare_format import format_money, format_money_delta  # noqa: E402
from davey_experiment_common import safe_num  # noqa: E402

# Per-system time_stop (bars) used when replaying; 0 = off.
SYSTEM_TIME_STOP = {
    "RS": 252,
    "RL": 0,
    "SB": 0,
    "BRT": 0,
    "YH": 0,
    "WPBR": 0,
    "MTS": 0,
}

COMPARE_COLS: list[tuple[str, str, str]] = [
    ("Total_Trades", "Total trades", "int"),
    ("Wins", "Wins", "int"),
    ("Pct_Wins", "Win %", "pct"),
    ("Total_PNL", "Total PnL $", "money"),
    ("Sheet_PNL", "Sheet PnL $", "money"),
    ("Avg_PNL_Pct", "Avg PnL %", "pct"),
    ("Profit_Factor", "Profit factor", "num"),
    ("Ann_ROR", "Ann ROR %", "pct"),
    ("Max_DD", "Max DD %", "pct"),
    ("Expectancy", "Expectancy $", "money"),
    ("Profit_Per_Capital_Day", "Profit / capital day", "money"),
    ("Avg_Days_Held", "Avg days held", "num"),
    ("Median_Days_Held", "Median days held", "num"),
    ("Losing_Streak", "Losing streak", "int"),
    ("Capital_Days", "Capital days", "num"),
    ("Exit_TARGET", "Exit TARGET", "int"),
    ("Exit_STOP_LOSS", "Exit STOP_LOSS", "int"),
    ("Exit_GAP_UP", "Exit GAP_UP", "int"),
    ("Exit_GAP_DOWN", "Exit GAP_DOWN", "int"),
    ("Exit_TIME", "Exit TIME", "int"),
    ("Exit_OTHER", "Exit OTHER", "int"),
    ("Fallback_Static", "Fallback static #", "int"),
    ("Skipped_RR", "Skipped RR #", "int"),
]

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e8e8e0}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.better{color:#166534;font-weight:600}
.worse{color:#991b1b}
.note{color:#64748b;font-size:.92em}
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
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _parse_date(s: str) -> Optional[pd.Timestamp]:
    t = (s or "").strip()
    if not t:
        return None
    if t.isdigit() and len(t) == 8:
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    try:
        return pd.Timestamp(t)
    except Exception:
        return None


def _col(row: dict, *names: str) -> str:
    upper = {k.upper().replace("_", " "): k for k in row}
    upper2 = {k.upper(): k for k in row}
    for n in names:
        nu = n.upper()
        if nu in upper2:
            return row.get(upper2[nu], "") or ""
        nsp = nu.replace("_", " ")
        if nsp in upper:
            return row.get(upper[nsp], "") or ""
    # fuzzy
    for k, v in row.items():
        ku = k.upper().replace(" ", "_")
        for n in names:
            if ku == n.upper().replace(" ", "_"):
                return v or ""
    return ""


@dataclass
class TradeIn:
    symbol: str
    side: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    exit_type: str
    days_held: float
    pnl_pct: float
    pnl_dollars: float
    notional: float


def load_closed(path: Path) -> list[TradeIn]:
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        raw = list(csv.DictReader(f))
    out: list[TradeIn] = []
    for r in raw:
        sym = (_col(r, "SYMBOL", "TICKER") or "").upper().strip()
        if not sym:
            continue
        ep = safe_num(_col(r, "ENTRY_PRICE", "ENTRY PRICE"))
        xp = safe_num(_col(r, "EXIT_PRICE", "EXIT PRICE"))
        sp = safe_num(_col(r, "STOP_PRICE", "ORIGINAL STOP", "STOP LOSS AT CLOSE"))
        tp = safe_num(_col(r, "TARGET_PRICE", "ORIGINAL TARGET"))
        pnl_pct = safe_num(_col(r, "PNL_PCT", "PNL %"))
        pnl_d = safe_num(_col(r, "PNL_DOLLARS", "PNL $"))
        # Some Closed omit PNL_DOLLARS; derive later.
        if abs(pnl_pct) > 1e-12 and abs(pnl_d) > 1e-12:
            notional = abs(pnl_d / (pnl_pct / 100.0))
        else:
            notional = 47500.0
        side = (_col(r, "SIDE") or "LONG").upper().strip() or "LONG"
        out.append(
            TradeIn(
                symbol=sym,
                side=side,
                entry_date=str(_col(r, "DATE_OPENED", "DATE OPENED", "ENTRY_DATE") or ""),
                exit_date=str(_col(r, "DATE_CLOSED", "DATE CLOSED", "EXIT_DATE") or ""),
                entry_price=ep,
                exit_price=xp,
                stop_price=sp,
                target_price=tp,
                exit_type=str(_col(r, "EXIT_TYPE", "EXIT TYPE") or "").upper(),
                days_held=safe_num(_col(r, "DAYS_HELD", "DAYS HELD")),
                pnl_pct=pnl_pct,
                pnl_dollars=pnl_d,
                notional=notional,
            )
        )
    return out


@dataclass
class Zone:
    symbol: str
    source: str
    low: float
    high: float
    center: float
    mature_date: str


def load_catalog(path: Path) -> dict[str, list[Zone]]:
    by: dict[str, list[Zone]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            sym = (r.get("symbol") or "").upper().strip()
            if not sym:
                continue
            try:
                z = Zone(
                    symbol=sym,
                    source=(r.get("source_system") or "").upper(),
                    low=float(r["zone_low"]),
                    high=float(r["zone_high"]),
                    center=float(r["zone_center"]),
                    mature_date=str(r.get("mature_date") or r.get("as_of_date") or "")[:10],
                )
            except (KeyError, TypeError, ValueError):
                continue
            if z.low > 0 and z.high > z.low and z.mature_date:
                by[sym].append(z)
    for sym in by:
        by[sym].sort(key=lambda z: z.mature_date)
    return by


def nearest_zones(
    zones: list[Zone],
    *,
    entry_price: float,
    entry_date: str,
) -> tuple[Optional[Zone], Optional[Zone]]:
    """Nearest zone above (low > entry) and below (high < entry) matured by entry_date."""
    ed = (_parse_date(entry_date) or pd.Timestamp.max).strftime("%Y-%m-%d")
    above: Optional[Zone] = None
    below: Optional[Zone] = None
    best_above = float("inf")
    best_below = -float("inf")
    ep = float(entry_price)
    for z in zones:
        if z.mature_date > ed:
            continue
        if z.low > ep:
            if z.low < best_above:
                best_above = z.low
                above = z
        if z.high < ep:
            if z.high > best_below:
                best_below = z.high
                below = z
    return above, below


def resolve_levels(
    trade: TradeIn,
    zones: list[Zone],
    *,
    rr_min: float,
    mode: str = "both",
) -> tuple[float, float, str, Optional[float], bool]:
    """Return (target, stop, level_source, rr, skip).

    mode: both | target_only | stop_only
    level_source: catalog | static_fallback | skipped_rr
    """
    mode = (mode or "both").strip().lower()
    if mode not in ("both", "target_only", "stop_only"):
        raise ValueError(f"Unknown level mode: {mode}")

    is_long = trade.side != "SHORT"
    above, below = nearest_zones(zones, entry_price=trade.entry_price, entry_date=trade.entry_date)
    ep = trade.entry_price
    if is_long:
        zt = float(above.low) if above is not None else None
        zs = float(below.high) if below is not None else None
        if zt is not None and zt <= ep:
            zt = None
        if zs is not None and zs >= ep:
            zs = None
        reward = (zt - ep) if zt is not None else None
        risk = (ep - zs) if zs is not None else None
    else:
        zt = float(below.high) if below is not None else None
        zs = float(above.low) if above is not None else None
        if zt is not None and zt >= ep:
            zt = None
        if zs is not None and zs <= ep:
            zs = None
        reward = (ep - zt) if zt is not None else None
        risk = (zs - ep) if zs is not None else None

    rr = None
    if reward is not None and risk is not None and risk > 0:
        rr = float(reward) / float(risk)

    # RR gates only apply to the both-sides arm (catalog RR needs both levels).
    if rr_min > 0 and mode == "both":
        if rr is None or rr <= rr_min:
            return trade.target_price, trade.stop_price, "skipped_rr", rr, True

    used_fallback = False
    if mode == "target_only":
        target = zt if zt is not None else trade.target_price
        stop = trade.stop_price
        used_fallback = zt is None
    elif mode == "stop_only":
        target = trade.target_price
        stop = zs if zs is not None else trade.stop_price
        used_fallback = zs is None
    else:
        target = zt if zt is not None else trade.target_price
        stop = zs if zs is not None else trade.stop_price
        used_fallback = zt is None or zs is None

    src = "static_fallback" if used_fallback else "catalog"
    return float(target), float(stop), src, rr, False


def replay_exit(
    df: pd.DataFrame,
    trade: TradeIn,
    target: float,
    stop: float,
    *,
    time_stop_days: int,
) -> tuple[str, float, float, int]:
    """Returns exit_type, exit_price, pnl_pct, days_held."""
    ed = _parse_date(trade.entry_date)
    if ed is None or df.empty or trade.entry_price <= 0:
        return trade.exit_type, trade.exit_price, trade.pnl_pct, int(trade.days_held or 0)
    # locate entry bar
    idx = df.index
    # normalize to date
    dates = pd.DatetimeIndex(idx).normalize()
    ed_n = ed.normalize()
    pos = int(np.searchsorted(dates.values, np.datetime64(ed_n), side="left"))
    if pos >= len(df):
        return "NO_DATA", trade.entry_price, 0.0, 0
    if dates[pos] != ed_n:
        # try exact match nearby
        matches = np.where(dates == ed_n)[0]
        if len(matches) == 0:
            return "NO_ENTRY_BAR", trade.entry_price, 0.0, 0
        pos = int(matches[0])

    is_long = trade.side != "SHORT"
    ep = float(trade.entry_price)
    open_a = df["Open"].to_numpy(dtype=float)
    high_a = df["High"].to_numpy(dtype=float)
    low_a = df["Low"].to_numpy(dtype=float)
    close_a = df["Close"].to_numpy(dtype=float)

    last_i = len(df) - 1
    for i in range(pos, last_i + 1):
        op, hi, lo, cl = float(open_a[i]), float(high_a[i]), float(low_a[i]), float(close_a[i])
        held = i - pos
        if is_long:
            gap_down = op <= stop
            gap_up = op >= target
            stop_hit = lo <= stop
            target_hit = hi >= target
        else:
            gap_up = op >= stop
            gap_down = op <= target
            stop_hit = hi >= stop
            target_hit = lo <= target

        if is_long and gap_down:
            xp, et = op, "GAP_DOWN"
        elif is_long and gap_up:
            xp, et = op, "GAP_UP"
        elif (not is_long) and gap_up:
            xp, et = op, "GAP_UP"
        elif (not is_long) and gap_down:
            xp, et = op, "GAP_DOWN"
        elif stop_hit:
            xp, et = stop, "STOP_LOSS"
        elif target_hit:
            xp, et = target, "TARGET"
        elif time_stop_days > 0 and held >= time_stop_days:
            xp, et = cl, "TIME"
        else:
            continue
        pnl_pct = ((xp / ep) - 1.0) * 100.0 if is_long else ((ep / xp) - 1.0) * 100.0
        # calendar-ish days held from timestamps
        days = int((dates[i] - dates[pos]).days) if hasattr(dates[i] - dates[pos], "days") else held
        return et, float(xp), float(pnl_pct), max(days, held)

    # end of data
    xp = float(close_a[last_i])
    pnl_pct = ((xp / ep) - 1.0) * 100.0 if is_long else ((ep / xp) - 1.0) * 100.0
    days = int((dates[last_i] - dates[pos]).days)
    return "END_OF_DATA", xp, float(pnl_pct), max(days, last_i - pos)


# Rocket EquityMeta default account seed for Max DD (see BRT/RL/WPBR EquityMeta).
DEFAULT_INITIAL_ACCOUNT = 500_000.0


def compute_metrics(
    rows: list[dict[str, Any]],
    *,
    cash_hint: float = 47500.0,
    initial_account: float = DEFAULT_INITIAL_ACCOUNT,
) -> dict[str, float]:
    if not rows:
        return {k: 0.0 for k, _, _ in COMPARE_COLS}
    pnls = [safe_num(r.get("pnl_dollars")) for r in rows]
    pcts = [safe_num(r.get("pnl_pct")) for r in rows]
    days = [safe_num(r.get("days_held")) for r in rows]
    n = len(rows)
    wins = sum(1 for p in pnls if p > 0)
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    pf = (gross_win / gross_loss) if gross_loss > 1e-12 else (999.0 if gross_win > 0 else 0.0)
    total_pnl = sum(pnls)
    avg_days = float(np.mean(days)) if days else 0.0
    med_days = float(np.median(days)) if days else 0.0
    # Ann ROR book formula (canonical): ((1 + Total_PNL/(cash*n_trades))**(365/avg_days)-1)*100
    # Guard tiny hold / tiny-n samples so RR gates cannot explode into nonsense %.
    cash = cash_hint if cash_hint > 0 else 47500.0
    if n >= 5 and cash > 0:
        hold = max(float(avg_days), 1.0)
        base = 1.0 + total_pnl / (cash * n)
        if base > 0:
            ann = (base ** (365.0 / hold) - 1.0) * 100.0
            if not math.isfinite(ann) or ann > 50_000:
                ann = 50_000.0
            elif ann < -100.0:
                ann = -100.0
        else:
            ann = -100.0
    else:
        ann = 0.0
    # Max DD: peak-to-trough on equity = initial_account + cumulative realized PnL
    # (same rule as BRT_DrawdownCalc.max_drawdown_from_equity_path). Prior bug
    # started equity at 0 and divided dollar DD by one-trade cash → values >>100%.
    # Seed matches rocket EquityMeta Initial_Account_Size ($500k), not per-trade cash.
    ordered = sorted(rows, key=lambda r: (r.get("entry_date") or "", r.get("symbol") or ""))
    initial = float(initial_account) if initial_account > 0 else DEFAULT_INITIAL_ACCOUNT
    equity = initial
    eq_path: list[float] = []
    for r in ordered:
        equity += safe_num(r.get("pnl_dollars"))
        eq_path.append(equity)
    try:
        from BRT_DrawdownCalc import max_drawdown_from_equity_path as _mdd_path

        max_dd = float(_mdd_path(eq_path, initial)) * 100.0
    except Exception:
        port_hwm = initial
        max_dd_frac = 0.0
        for eq in eq_path:
            if eq > port_hwm:
                port_hwm = eq
            if port_hwm > 0:
                max_dd_frac = max(max_dd_frac, (port_hwm - eq) / port_hwm)
        max_dd = max_dd_frac * 100.0
    capital_days = sum(max(d, 0.0) for d in days)
    ppcd = (total_pnl / capital_days) if capital_days > 1e-12 else 0.0
    # losing streak
    streak = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    exit_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        et = str(r.get("exit_type") or "OTHER").upper()
        if et in ("TARGET", "STOP_LOSS", "GAP_UP", "GAP_DOWN", "TIME"):
            exit_counts[et] += 1
        else:
            exit_counts["OTHER"] += 1
    return {
        "Total_Trades": float(n),
        "Wins": float(wins),
        "Pct_Wins": 100.0 * wins / n if n else 0.0,
        "Total_PNL": float(total_pnl),
        "Sheet_PNL": float(total_pnl),  # fixed-notional path ≈ book here
        "Avg_PNL_Pct": float(np.mean(pcts)) if pcts else 0.0,
        "Profit_Factor": float(pf),
        "Ann_ROR": float(ann),
        "Max_DD": float(max_dd),
        "Expectancy": float(total_pnl / n) if n else 0.0,
        "Profit_Per_Capital_Day": float(ppcd),
        "Avg_Days_Held": float(avg_days),
        "Median_Days_Held": float(med_days),
        "Losing_Streak": float(streak),
        "Capital_Days": float(capital_days),
        "Exit_TARGET": float(exit_counts.get("TARGET", 0)),
        "Exit_STOP_LOSS": float(exit_counts.get("STOP_LOSS", 0)),
        "Exit_GAP_UP": float(exit_counts.get("GAP_UP", 0)),
        "Exit_GAP_DOWN": float(exit_counts.get("GAP_DOWN", 0)),
        "Exit_TIME": float(exit_counts.get("TIME", 0)),
        "Exit_OTHER": float(exit_counts.get("OTHER", 0)),
        "Fallback_Static": float(sum(1 for r in rows if r.get("level_source") == "static_fallback")),
        "Skipped_RR": float(sum(1 for r in rows if r.get("level_source") == "skipped_rr")),
    }


def control_rows_from_trades(trades: list[TradeIn]) -> list[dict[str, Any]]:
    rows = []
    for t in trades:
        pnl_d = t.pnl_dollars
        if abs(pnl_d) < 1e-12 and abs(t.pnl_pct) > 1e-12:
            pnl_d = t.notional * (t.pnl_pct / 100.0)
        rows.append(
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "stop_price": t.stop_price,
                "target_price": t.target_price,
                "exit_type": t.exit_type,
                "days_held": t.days_held,
                "pnl_pct": t.pnl_pct,
                "pnl_dollars": pnl_d,
                "level_source": "control_static",
                "rr": "",
            }
        )
    return rows


def run_arm(
    trades: list[TradeIn],
    catalog: dict[str, list[Zone]],
    ohlc_cache: dict[str, pd.DataFrame],
    *,
    system: str,
    rr_min: float,
    use_catalog: bool,
    mode: str = "both",
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    time_stop = int(SYSTEM_TIME_STOP.get(system.upper(), 0))
    out_rows: list[dict[str, Any]] = []
    for t in trades:
        if t.symbol not in ohlc_cache:
            df = load_symbol_df(t.symbol)
            ohlc_cache[t.symbol] = df if df is not None else pd.DataFrame()
        df = ohlc_cache[t.symbol]
        if not use_catalog:
            # control: keep Closed outcomes
            out_rows.append(control_rows_from_trades([t])[0])
            continue
        target, stop, src, rr, skip = resolve_levels(
            t, catalog.get(t.symbol, []), rr_min=rr_min, mode=mode
        )
        if skip:
            out_rows.append(
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_date": t.entry_date,
                    "exit_date": "",
                    "entry_price": t.entry_price,
                    "exit_price": "",
                    "stop_price": stop,
                    "target_price": target,
                    "exit_type": "SKIPPED_RR",
                    "days_held": 0,
                    "pnl_pct": 0.0,
                    "pnl_dollars": 0.0,
                    "level_source": "skipped_rr",
                    "rr": "" if rr is None else f"{rr:.4f}",
                }
            )
            continue
        et, xp, pnl_pct, days = replay_exit(df, t, target, stop, time_stop_days=time_stop)
        pnl_d = t.notional * (pnl_pct / 100.0)
        out_rows.append(
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_date": t.entry_date,
                "exit_date": "",
                "entry_price": t.entry_price,
                "exit_price": xp,
                "stop_price": stop,
                "target_price": target,
                "exit_type": et,
                "days_held": days,
                "pnl_pct": pnl_pct,
                "pnl_dollars": pnl_d,
                "level_source": src,
                "rr": "" if rr is None else f"{rr:.4f}",
            }
        )
    # For RR arms, metrics exclude skipped trades (they were not taken).
    kept = [r for r in out_rows if r.get("level_source") != "skipped_rr"]
    skipped_n = sum(1 for r in out_rows if r.get("level_source") == "skipped_rr")
    notions = [t.notional for t in trades if t.notional > 0]
    cash_hint = float(np.median(notions)) if notions else 47500.0
    m = compute_metrics(kept, cash_hint=cash_hint)
    m["Skipped_RR"] = float(skipped_n)
    m["Fallback_Static"] = float(sum(1 for r in kept if r.get("level_source") == "static_fallback"))
    return out_rows, m


def _fmt_cell(fmt: str, value: Any) -> str:
    if value is None or value == "":
        return "—"
    n = safe_num(value)
    if fmt == "money":
        return format_money(n)
    if fmt == "pct":
        return f"{n:.2f}%"
    if fmt == "int":
        return str(int(round(n)))
    return f"{n:.3f}" if abs(n) < 10 else f"{n:.2f}"


def _delta_class(key: str, delta: float) -> str:
    lower_better = {
        "Max_DD",
        "Losing_Streak",
        "Avg_Days_Held",
        "Median_Days_Held",
        "Capital_Days",
        "Fallback_Static",
        "Skipped_RR",
    }
    if abs(delta) < 1e-12:
        return ""
    good = (delta < 0) if key in lower_better else (delta > 0)
    return "better" if good else "worse"


def write_html(results: list[dict[str, Any]], path: Path, recommendation: str, catalog_meta: dict) -> None:
    systems = sorted({r["system"] for r in results})
    sections: list[str] = []
    for system in systems:
        arms = {r["id"]: r for r in results if r["system"] == system}
        preferred = (
            "control",
            "zones_target_only",
            "zones_stop_only",
            "zones_as_ts",
            "zones_rr2",
            "zones_rr3",
            "zones_rr4",
        )
        order = [a for a in preferred if a in arms]
        # Any unexpected arms last (stable).
        order += [a for a in sorted(arms) if a not in order]
        ctrl = arms.get("control")
        ctrl_m = (ctrl or {}).get("metrics") or {}
        head = (
            "<tr>"
            + sortable_th("Arm", "text")
            + "".join(sortable_th(lab, "num") for _, lab, _ in COMPARE_COLS)
            + "".join(sortable_th(f"Δ {lab}", "num") for _, lab, _ in COMPARE_COLS)
            + "</tr>"
        )
        body: list[str] = []
        for aid in order:
            r = arms[aid]
            m = r.get("metrics") or {}
            cells = [f"<td>{html.escape(aid)}</td>"]
            for key, _lab, fmt in COMPARE_COLS:
                cells.append(f'<td class="num">{_fmt_cell(fmt, m.get(key))}</td>')
            for key, _lab, fmt in COMPARE_COLS:
                if not ctrl or aid == "control":
                    cells.append('<td class="num">—</td>')
                    continue
                d = safe_num(m.get(key)) - safe_num(ctrl_m.get(key))
                cls = _delta_class(key, d)
                if fmt == "money":
                    txt = format_money_delta(d)
                elif fmt == "pct":
                    txt = f"{d:+.2f}%"
                elif fmt == "int":
                    txt = f"{int(round(d)):+d}"
                else:
                    txt = f"{d:+.3f}"
                cells.append(f'<td class="num {cls}">{txt}</td>')
            body.append("<tr>" + "".join(cells) + "</tr>")
        sections.append(
            f"<h2>{html.escape(system)}</h2>"
            f'<p class="note">{html.escape((arms.get("control") or {}).get("closed_path", ""))} '
            f"→ catalog levels as target and/or stop (one side at a time + both)</p>"
            f'<table class="sortable"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'
        )
    src_counts = catalog_meta.get("rows_by_source", {})
    doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Zones as target/stop — shared catalog replay</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#1e293b;background:#fafaf7}}
h1{{font-size:1.4rem}} h2{{margin-top:2rem;font-size:1.15rem}}
table{{border-collapse:collapse;width:100%;margin:12px 0 28px;background:#fff;font-size:.9rem}}
th,td{{border:1px solid #d4d4d0;padding:6px 8px}}
th{{background:#f0f0ea}}
{SORTABLE_TH_CSS}
.verdict{{background:#eef6ff;border:1px solid #bfdbfe;padding:12px 16px;border-radius:6px;margin:16px 0}}
</style></head><body>
<h1>Zones as target/stop — shared catalog replay</h1>
<p class="note">Click column headers to sort. Hypothesis test: do shared BRT/YH/WPBR/MTS
catalog zones work as <em>levels</em> (target-only, stop-only, both, or both+RR) vs static
target%/stop% on RS/RL/SB (etc.) Closed entries?</p>
<p class="note"><strong>PPCD-first reassessment:</strong> see
<a href="PPCD_REASSESSMENT.html">PPCD_REASSESSMENT.html</a> —
soft-hold RL/WPBR target-only on PPCD+Ann ROR (Max DD = peak-to-trough on $500k equity seed;
RR2/RR3/RR4 included).</p>
<div class="verdict"><strong>Verdict (Total PnL + Ann ROR capacity):</strong> {html.escape(recommendation)}</div>
<p class="note">Catalog: {html.escape(str(catalog_meta.get("catalog_csv","")))}
 — {catalog_meta.get("n_rows",0)} zones / {catalog_meta.get("n_symbols",0)} symbols
 — by source {html.escape(str(src_counts))}</p>
<p class="note"><strong>Framing:</strong> zones as price levels, not a product “zone exit.”
Prior <code>zone_exits</code> / <code>zone_exits_union</code> were mid-run DNA overlays;
this run persists a catalog then replays production entries one side at a time.</p>
{"".join(sections)}
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path.write_text(doc, encoding="utf-8")


def write_decision_log(
    path: Path,
    *,
    recommendation: str,
    results: list[dict[str, Any]],
    catalog_meta: dict,
    fallback_policy: str,
) -> None:
    lines = [
        "# Zones as target/stop — shared catalog (decision log)",
        "",
        "**Hypothesis:** Using price zones from BRT / YH / WPBR / MTS as *levels* "
        "(nearest zone above = target and/or nearest zone below = stop) on *other* "
        "systems' production entries (RS, RL, SB, …) may improve outcomes vs static "
        "`target_pct` / `stop_pct`. Test **one side at a time** so a bad stop cannot "
        "mask a useful target (or vice versa).",
        "",
        "See `docs/HYPOTHESIS_TEST.md`.",
        "",
        "## Framing",
        "",
        "Zones are catalog price bands used as target/stop **levels** — not a product "
        "“zone exit” mode. This is a post-hoc Closed replay against a shared catalog.",
        "",
        "## How this differs from prior `zone_exits` / `zone_exits_union`",
        "",
        "| Experiment | What it did |",
        "|------------|-------------|",
        "| `zone_exits_ab` / `zone_exits_union_ab` | Mid-run overlay: nearest zone from "
        "**that run's** zone DNA (own or union BRT+YH+WPBR+VEC) while the **same** "
        "zone-system was trading |",
        "| **This run** (`zones_as_target_stop_ab`) | **Phase A:** persist all zones from "
        "BRT/YH/WPBR/MTS into a shared catalog. **Phase B:** keep RS/RL/SB (etc.) "
        "**entries exactly as production Closed**, replace target and/or stop with "
        "nearest catalog zone above/below, resimulate exits |",
        "",
        "## Fallback policy",
        "",
        fallback_policy,
        "",
        "## Catalog",
        "",
        f"- Path: `{catalog_meta.get('catalog_csv')}`",
        f"- Rows: **{catalog_meta.get('n_rows')}** across **{catalog_meta.get('n_symbols')}** symbols",
        f"- Sources: `{catalog_meta.get('rows_by_source')}`",
        f"- Scope note: {catalog_meta.get('scope_note', '')}",
        "",
        "## Arms",
        "",
        "| Arm | Behavior |",
        "|-----|----------|",
        "| control | Production Closed static target/stop outcomes |",
        "| zones_target_only | Catalog nearest above = target; keep Closed static stop; "
        "missing above → static target |",
        "| zones_stop_only | Catalog nearest below = stop; keep Closed static target; "
        "missing below → static stop |",
        "| zones_as_ts | Both sides from catalog; missing side → that side's static |",
        "| zones_rr2/3/4 | Both + require catalog RR > 2/3/4; missing/fail → skip (optional) |",
        "",
        f"## Results ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "",
        f"**Recommendation:** {recommendation}",
        "",
    ]
    for r in sorted(results, key=lambda x: (x["system"], x["id"])):
        m = r.get("metrics") or {}
        lines.append(
            f"- `{r['system']}` / `{r['id']}`: trades={int(m.get('Total_Trades',0))} "
            f"PnL={format_money(m.get('Total_PNL'))} AnnROR={safe_num(m.get('Ann_ROR')):.2f}% "
            f"PF={safe_num(m.get('Profit_Factor')):.2f} MaxDD={safe_num(m.get('Max_DD')):.2f}% "
            f"fallback={int(m.get('Fallback_Static',0))} skipRR={int(m.get('Skipped_RR',0))}"
        )
    # Explicit RS/RL/SB answer block — one-sided + both
    lines += ["", "## Verdict (RS / RL / SB) — one-sided vs both", ""]
    for system in ("RS", "RL", "SB"):
        arms = {r["id"]: r for r in results if r["system"] == system}
        ctrl = arms.get("control", {}).get("metrics") or {}
        if not ctrl:
            lines.append(f"- **{system}:** no Closed stamp / not run")
            continue
        c_pnl = safe_num(ctrl.get("Total_PNL"))
        c_ror = safe_num(ctrl.get("Ann_ROR"))
        bits = []
        any_yes = False
        for aid in ("zones_target_only", "zones_stop_only", "zones_as_ts"):
            m = arms.get(aid, {}).get("metrics") or {}
            if not m:
                bits.append(f"{aid}=n/a")
                continue
            pnl = safe_num(m.get("Total_PNL"))
            ror = safe_num(m.get("Ann_ROR"))
            yes = pnl > c_pnl and ror >= c_ror - 1e-9
            any_yes = any_yes or yes
            bits.append(
                f"{aid} {'YES' if yes else 'NO'} "
                f"(PnL {format_money(pnl)}, AnnROR {ror:.2f}%)"
            )
        lines.append(
            f"- **{system}:** {'partial help' if any_yes else 'no one-sided/both help'} — "
            f"control PnL {format_money(c_pnl)} AnnROR {c_ror:.2f}%; " + "; ".join(bits)
        )
    lines += [
        "",
        "**Adopt / reject / hold:** see Recommendation above. Judge primarily on Total PnL "
        "capacity with Ann ROR secondary; do not promote on max single-trade PnL.",
        "",
        "## Reproduce",
        "",
        "```bat",
        "python tools/run_zones_as_target_stop_ab.py --systems RS,RL,SB,BRT,YH,WPBR,MTS",
        "```",
        "",
        "Optional RR gates (both-sides arm only):",
        "",
        "```bat",
        "python tools/run_zones_as_target_stop_ab.py --systems RS,RL,SB --rr 2,3,4",
        "```",
        "",
        "## Paths",
        "",
        f"- Catalog dir: `drive/paul_experiments/zone_catalog/`",
        f"- Compare HTML: `drive/paul_experiments/zones_as_target_stop_ab/comparison.html`",
        f"- This log: `drive/paul_experiments/zones_as_target_stop_ab/DECISION_LOG.md`",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_catalog(build: bool, jobs: int) -> tuple[Path, dict]:
    latest = CATALOG_DIR / "zone_catalog_latest.csv"
    meta_path = CATALOG_DIR / "zone_catalog_latest_meta.json"
    if build or not latest.is_file():
        print("[zones_as_ts] building catalog…")
        import subprocess

        cmd = [
            sys.executable,
            str(REPO / "tools" / "build_zone_catalog.py"),
            "--from-closed",
            "RS,RL,SB",
            "--include-markten",
            "--jobs",
            str(jobs),
        ]
        subprocess.run(cmd, cwd=str(REPO), check=True)
    meta = {}
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        # minimal meta from csv
        n = sum(1 for _ in latest.open(encoding="utf-8")) - 1
        meta = {
            "catalog_csv": str(latest.relative_to(REPO)).replace("\\", "/"),
            "n_rows": n,
            "n_symbols": "?",
            "rows_by_source": {},
            "scope_note": "see build_zone_catalog.py",
        }
    return latest, meta


ARM_LABELS: dict[str, str] = {
    "control": "Production static target/stop (Closed)",
    "zones_target_only": "Catalog nearest above=target; keep Closed static stop",
    "zones_stop_only": "Catalog nearest below=stop; keep Closed static target",
    "zones_as_ts": "Catalog nearest zone above/below as target/stop (both)",
    "zones_rr2": "Catalog both levels + RR>2",
    "zones_rr3": "Catalog both levels + RR>3",
    "zones_rr4": "Catalog both levels + RR>4",
}


def _cash_hint_from_rows(rows: list[dict[str, Any]]) -> float:
    notions: list[float] = []
    for r in rows:
        pct = safe_num(r.get("pnl_pct"))
        dollars = safe_num(r.get("pnl_dollars"))
        if abs(pct) > 1e-9:
            notions.append(abs(dollars / (pct / 100.0)))
    return float(np.median(notions)) if notions else 47500.0


def _latest_arm_csvs(sys_dir: Path, system: str) -> dict[str, Path]:
    """Pick newest CSV per arm id under runs/<system>/."""
    best: dict[str, Path] = {}
    best_mtime: dict[str, float] = {}
    prefix = f"{system}_"
    for p in sys_dir.glob(f"{system}_*.csv"):
        name = p.stem  # SYSTEM_arm_stamp
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix) :]
        # arm may contain underscores (zones_target_only); stamp is last _YYMMDDHHMMSS
        parts = rest.rsplit("_", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        arm = parts[0]
        mtime = p.stat().st_mtime
        if mtime >= best_mtime.get(arm, -1.0):
            best[arm] = p
            best_mtime[arm] = mtime
    return best


def recompute_from_runs(systems: list[str], meta: dict) -> list[dict[str, Any]]:
    """Rebuild metrics from newest on-disk arm CSVs (no OHLC replay)."""
    results: list[dict[str, Any]] = []
    for system in systems:
        sys_dir = OUT_ROOT / "runs" / system.lower()
        if not sys_dir.is_dir():
            print(f"[zones_as_ts] recompute skip {system}: no {sys_dir}")
            continue
        arms = _latest_arm_csvs(sys_dir, system)
        if not arms:
            print(f"[zones_as_ts] recompute skip {system}: no arm CSVs")
            continue
        closed_path = DRIVE / f"{system}_LatestRun_Closed.csv"
        for aid in sorted(arms.keys()):
            path = arms[aid]
            with path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            skipped_n = sum(1 for r in rows if (r.get("level_source") or "") == "skipped_rr")
            kept = [r for r in rows if (r.get("level_source") or "") != "skipped_rr"]
            cash_hint = _cash_hint_from_rows(kept) if kept else 47500.0
            metrics = compute_metrics(kept, cash_hint=cash_hint)
            metrics["Skipped_RR"] = float(skipped_n)
            metrics["Fallback_Static"] = float(
                sum(1 for r in kept if (r.get("level_source") or "") == "static_fallback")
            )
            print(
                f"[recompute] {system}/{aid}: trades={int(metrics['Total_Trades'])} "
                f"PnL={format_money(metrics['Total_PNL'])} "
                f"AnnROR={metrics['Ann_ROR']:.2f}% MaxDD={metrics['Max_DD']:.2f}% "
                f"PPCD={metrics['Profit_Per_Capital_Day']:.2f} from {path.name}"
            )
            results.append(
                {
                    "system": system,
                    "id": aid,
                    "label": ARM_LABELS.get(aid, aid),
                    "ok": True,
                    "metrics": metrics,
                    "closed_path": str(closed_path),
                    "out_csv": str(path),
                }
            )
    return results


def write_outputs(results: list[dict[str, Any]], meta: dict, recommendation: str) -> None:
    write_html(results, OUT_ROOT / "comparison.html", recommendation, meta)
    with (OUT_ROOT / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["system", "arm"] + [k for k, _, _ in COMPARE_COLS]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            row = {"system": r["system"], "arm": r["id"]}
            row.update({k: (r.get("metrics") or {}).get(k, "") for k, _, _ in COMPARE_COLS})
            w.writerow(row)
    fallback_policy = (
        "- **zones_target_only:** missing zone above → keep Closed static target; "
        "stop always Closed static.\n"
        "- **zones_stop_only:** missing zone below → keep Closed static stop; "
        "target always Closed static.\n"
        "- **zones_as_ts (both, no RR):** missing above and/or below → keep that side's "
        "static level from the Closed row; trade still taken.\n"
        "- **zones_rrN (optional, both only):** if either side missing or reward/risk ≤ N, "
        "**skip** the trade (not counted in Total_Trades / PnL)."
    )
    write_decision_log(
        OUT_ROOT / "DECISION_LOG.md",
        recommendation=recommendation,
        results=results,
        catalog_meta=meta,
        fallback_policy=fallback_policy,
    )
    (OUT_ROOT / "README.md").write_text(
        "# Zones as target/stop (shared catalog)\n\n"
        "Research replay: catalog zones from BRT/YH/WPBR/MTS → apply as **levels** "
        "(target-only, stop-only, both, or both+RR gate) on other systems' Closed entries. "
        "Not a product “zone exit” feature.\n\n"
        "See `DECISION_LOG.md`, `comparison.html`, and `PPCD_REASSESSMENT.html`.\n",
        encoding="utf-8",
    )
    # Refresh PPCD-first note + append Max DD / soft-hold sections on DECISION_LOG.
    ppcd_writer = OUT_ROOT / "_write_ppcd_reassessment.py"
    if ppcd_writer.is_file():
        import subprocess

        subprocess.run([sys.executable, str(ppcd_writer)], cwd=str(REPO), check=False)


def recommend(results: list[dict[str, Any]]) -> str:
    """Judge primarily on Total PnL capacity; Ann ROR secondary when PnL is not collapsed."""
    parts: list[str] = []
    beats: list[str] = []
    for system in sorted({r["system"] for r in results}):
        arms = {r["id"]: r for r in results if r["system"] == system and r.get("ok")}
        ctrl = arms.get("control")
        if not ctrl:
            continue
        c_ror = safe_num((ctrl.get("metrics") or {}).get("Ann_ROR"))
        c_pnl = safe_num((ctrl.get("metrics") or {}).get("Total_PNL"))
        c_n = safe_num((ctrl.get("metrics") or {}).get("Total_Trades"))
        best_id = ""
        best_pnl = c_pnl
        best_ror = c_ror
        for aid in ("zones_target_only", "zones_stop_only", "zones_as_ts"):
            a = arms.get(aid)
            if not a:
                continue
            m = a.get("metrics") or {}
            pnl = safe_num(m.get("Total_PNL"))
            ror = safe_num(m.get("Ann_ROR"))
            if pnl > best_pnl and ror >= c_ror - 1e-9:
                best_id, best_pnl, best_ror = aid, pnl, ror
            elif pnl > best_pnl and not best_id:
                # track PnL leader even if ROR lags (reported in control-wins note)
                pass
        # RR arms only "beat" if they keep >=40% of control PnL and lift Ann ROR.
        rr_beat_id = ""
        rr_beat_ror = c_ror
        rr_beat_pnl = c_pnl
        for aid in ("zones_rr2", "zones_rr3", "zones_rr4"):
            a = arms.get(aid)
            if not a:
                continue
            m = a.get("metrics") or {}
            ror = safe_num(m.get("Ann_ROR"))
            pnl = safe_num(m.get("Total_PNL"))
            n = safe_num(m.get("Total_Trades"))
            if n < max(10.0, 0.15 * c_n):
                continue
            if pnl < 0.4 * c_pnl:
                continue
            if ror > rr_beat_ror + 1e-9 and pnl >= 0.4 * c_pnl:
                rr_beat_id, rr_beat_ror, rr_beat_pnl = aid, ror, pnl
        # Snapshot one-sided metrics for the summary string.
        def _snap(aid: str) -> str:
            m = (arms.get(aid) or {}).get("metrics") or {}
            if not m:
                return f"{aid}=n/a"
            return (
                f"{aid} PnL={safe_num(m.get('Total_PNL')):.0f} "
                f"AnnROR={safe_num(m.get('Ann_ROR')):.2f}"
            )

        if best_id:
            beats.append(f"{system}:{best_id}")
            parts.append(
                f"{system}: {best_id} BEATS control "
                f"(AnnROR {best_ror:.2f} vs {c_ror:.2f}, PnL {best_pnl:.0f} vs {c_pnl:.0f}); "
                f"{_snap('zones_target_only')}; {_snap('zones_stop_only')}; {_snap('zones_as_ts')}"
            )
        elif rr_beat_id:
            beats.append(f"{system}:{rr_beat_id}")
            parts.append(
                f"{system}: {rr_beat_id} beats on AnnROR with capacity kept "
                f"(AnnROR {rr_beat_ror:.2f} vs {c_ror:.2f}, PnL {rr_beat_pnl:.0f} vs {c_pnl:.0f})"
            )
        else:
            parts.append(
                f"{system}: control wins "
                f"(ctrl AnnROR={c_ror:.2f} PnL={c_pnl:.0f}; "
                f"{_snap('zones_target_only')}; {_snap('zones_stop_only')}; {_snap('zones_as_ts')})"
            )
    if not beats:
        return (
            "Reject — neither one-sided arm (target-only / stop-only) nor both-sides "
            "catalog levels beat static control on Total PnL + Ann ROR. "
            + "; ".join(parts)
        )
    return (
        "Partial — one or more catalog-level arms beat control on some systems. "
        + "; ".join(parts)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--systems", default="RS,RL,SB", help="Comma target systems")
    ap.add_argument(
        "--rr",
        default="2,3,4",
        help='Comma RR gates for both-sides arm only (default: "2,3,4"; pass "" to skip)',
    )
    ap.add_argument("--build-catalog", action="store_true", help="Force rebuild catalog")
    ap.add_argument("--catalog", default="", help="Catalog CSV path override")
    ap.add_argument("--jobs", type=int, default=6, help="Catalog build workers")
    ap.add_argument(
        "--markten-only-trades",
        action="store_true",
        help="Filter Closed to MarkTen symbols only",
    )
    ap.add_argument(
        "--recompute-from-runs",
        action="store_true",
        help="Skip OHLC replay; rebuild comparison/DECISION_LOG from latest arm CSVs on disk",
    )
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if args.catalog:
        catalog_path = Path(args.catalog)
        meta = {"catalog_csv": str(catalog_path), "n_rows": 0, "n_symbols": 0, "rows_by_source": {}}
        if not catalog_path.is_file():
            raise SystemExit(f"Catalog not found: {catalog_path}")
    else:
        catalog_path, meta = ensure_catalog(args.build_catalog, args.jobs)

    catalog = load_catalog(catalog_path)
    meta.setdefault("n_rows", sum(len(v) for v in catalog.values()))
    meta.setdefault("n_symbols", len(catalog))
    if "rows_by_source" not in meta or not meta["rows_by_source"]:
        by_src: dict[str, int] = defaultdict(int)
        for zs in catalog.values():
            for z in zs:
                by_src[z.source] += 1
        meta["rows_by_source"] = dict(by_src)

    systems = [s.strip().upper() for s in args.systems.split(",") if s.strip()]
    rr_list = [float(x) for x in args.rr.split(",") if x.strip()] if args.rr.strip() else []

    if args.recompute_from_runs:
        results = recompute_from_runs(systems, meta)
        recommendation = recommend(results)
        write_outputs(results, meta, recommendation)
        print(f"[zones_as_ts] HTML {OUT_ROOT / 'comparison.html'}")
        print(f"[zones_as_ts] LOG  {OUT_ROOT / 'DECISION_LOG.md'}")
        print(f"[zones_as_ts] VERDICT: {recommendation}")
        return 0

    # (id, label, use_catalog, rr_min, mode)
    arms_spec: list[tuple[str, str, bool, float, str]] = [
        ("control", "Production static target/stop (Closed)", False, 0.0, "both"),
        (
            "zones_target_only",
            "Catalog nearest above=target; keep Closed static stop",
            True,
            0.0,
            "target_only",
        ),
        (
            "zones_stop_only",
            "Catalog nearest below=stop; keep Closed static target",
            True,
            0.0,
            "stop_only",
        ),
        (
            "zones_as_ts",
            "Catalog nearest zone above/below as target/stop (both)",
            True,
            0.0,
            "both",
        ),
    ]
    for r in rr_list:
        arms_spec.append(
            (f"zones_rr{int(r)}", f"Catalog both levels + RR>{r:g}", True, float(r), "both")
        )

    results: list[dict[str, Any]] = []
    ohlc_cache: dict[str, pd.DataFrame] = {}
    stamp = datetime.now().strftime("%y%m%d%H%M%S")

    for system in systems:
        closed_path = DRIVE / f"{system}_LatestRun_Closed.csv"
        if not closed_path.is_file():
            print(f"[zones_as_ts] skip {system}: missing {closed_path}")
            continue
        trades = load_closed(closed_path)
        if args.markten_only_trades:
            trades = [t for t in trades if t.symbol in MARKTEN]
        print(f"[zones_as_ts] {system}: {len(trades)} trades from {closed_path.name}")
        sys_out = OUT_ROOT / "runs" / system.lower()
        sys_out.mkdir(parents=True, exist_ok=True)

        for aid, label, use_cat, rr_min, mode in arms_spec:
            t0 = time.time()
            rows, metrics = run_arm(
                trades,
                catalog,
                ohlc_cache,
                system=system,
                rr_min=rr_min,
                use_catalog=use_cat,
                mode=mode,
            )
            # drop skipped from closed export for cleaner diffs; keep all in detail
            out_csv = sys_out / f"{system}_{aid}_{stamp}.csv"
            with out_csv.open("w", newline="", encoding="utf-8") as f:
                fields = [
                    "symbol",
                    "side",
                    "entry_date",
                    "exit_date",
                    "entry_price",
                    "exit_price",
                    "stop_price",
                    "target_price",
                    "exit_type",
                    "days_held",
                    "pnl_pct",
                    "pnl_dollars",
                    "level_source",
                    "rr",
                ]
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for row in rows:
                    w.writerow(row)
            elapsed = time.time() - t0
            print(
                f"  {aid}: trades={int(metrics['Total_Trades'])} "
                f"PnL={format_money(metrics['Total_PNL'])} "
                f"AnnROR={metrics['Ann_ROR']:.2f}% ({elapsed:.1f}s)"
            )
            results.append(
                {
                    "system": system,
                    "id": aid,
                    "label": label,
                    "ok": True,
                    "metrics": metrics,
                    "closed_path": str(closed_path),
                    "out_csv": str(out_csv),
                }
            )

    recommendation = recommend(results)
    write_outputs(results, meta, recommendation)
    print(f"[zones_as_ts] HTML {OUT_ROOT / 'comparison.html'}")
    print(f"[zones_as_ts] LOG  {OUT_ROOT / 'DECISION_LOG.md'}")
    print(f"[zones_as_ts] VERDICT: {recommendation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
