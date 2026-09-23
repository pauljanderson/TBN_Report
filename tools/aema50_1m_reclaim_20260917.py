#!/usr/bin/env python3
"""KAMA(50) 1m failed-tag reclaim (research).

No shop adaptive EMA / AMA / KAMA / AEMA existed — freeze is Kaufman KAMA
ER length 50, fast 2, slow 30. Long the second close-through after a failed
high-tag from below. Stop = next RTH open after a 1m close below KAMA.

Arm A: may hold overnight; gap through KAMA = stop at 09:30 open.
Arm B: flatten 15:55 ET; no overnight fill.

Research only. Not gold. Not DailyRun.

Usage:
  python tools/aema50_1m_reclaim_20260917.py
  python tools/aema50_1m_reclaim_20260917.py -s AAPL,MSFT,NVDA
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import sys
from datetime import date, time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "aema50_1m_reclaim_20260917"
SYSTEM = "aema50_1m_reclaim"

# --- Freeze (see BASELINE.md; written before the scan) ---
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
FLAT_T = time(15, 55)  # Arm B
KAMA_ER = 50
KAMA_FAST = 2
KAMA_SLOW = 30
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0
SHORT_TAPE_OOS = date(2026, 9, 2)
MIN_RTH_BARS = 60
ARM_A = "arm_a_overnight"
ARM_B = "arm_b_flat_1555"
ARMS = (ARM_A, ARM_B)
CONTROL_ARM = ARM_A

ORIGINAL_REQUEST = (
    "can you run a backtest on our 1m data. track the adaptive EMA (50) and when a "
    "1m chart goes below the ema and then comes up and hits it and then goes below "
    "again, but then breaks through on a 1m close - we buy. we then move the stop "
    "loss to a close below the ema. how would this system perform?"
)

PLAIN_ENGLISH = (
    "Watch a 1-minute chart and a 50-period adaptive average. Wait until price is "
    "below that line, pokes it from underneath, fails (closes back under), and only "
    "then closes through it. Buy the second success, not the first poke. After you "
    "are in, the stop rides the same average: a 1-minute close back under it gets "
    "you out. One extra question: hold overnight, or flatten before the cash close?"
)

SORT_CSS = """
th.sortable-th {
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  white-space: nowrap;
  padding: 12px 10px;
  min-height: 44px;
  touch-action: manipulation;
}
th.sortable-th:hover, th.sortable-th:active { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""

SORT_JS = r"""
<script>
(function () {
  var lastTouchTs = 0;
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\d{4})-(\d{2})-(\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") {
        lastTouchTs = Date.now();
        e.preventDefault();
      } else if (e.type === "click" && Date.now() - lastTouchTs < 500) {
        return;
      }
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def list_parquet_symbols(data_dir: Path) -> list[str]:
    return sorted(p.stem.upper() for p in data_dir.glob("*.parquet") if p.is_file())


def rth_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "symbol"])
    t = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    tod = t.dt.time
    mask = (tod >= SESSION_OPEN) & (tod < SESSION_CLOSE)
    out = df.loc[mask].copy()
    out["ts"] = t.loc[mask]
    return out.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)


def kama_close(
    close: np.ndarray,
    *,
    er_len: int = KAMA_ER,
    fast: int = KAMA_FAST,
    slow: int = KAMA_SLOW,
) -> np.ndarray:
    """Kaufman Adaptive Moving Average on close (ER window = er_len)."""
    n = int(len(close))
    out = np.full(n, np.nan, dtype=float)
    if n <= er_len:
        return out
    abs_chg = np.abs(np.diff(close.astype(float)))
    if abs_chg.size == 0:
        return out
    csum = np.cumsum(abs_chg)
    fast_sc = 2.0 / (float(fast) + 1.0)
    slow_sc = 2.0 / (float(slow) + 1.0)
    prev = float("nan")
    for i in range(er_len, n):
        c_i = float(close[i])
        c_er = float(close[i - er_len])
        if not (math.isfinite(c_i) and math.isfinite(c_er)):
            out[i] = prev
            continue
        change = abs(c_i - c_er)
        end = i - 1
        start = i - er_len
        if start <= 0:
            vol = float(csum[end])
        else:
            vol = float(csum[end] - csum[start - 1])
        er = (change / vol) if vol > 0.0 else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        if not math.isfinite(prev):
            prev = c_i
        else:
            prev = prev + sc * (c_i - prev)
        out[i] = prev
    return out


# Setup states
ST_SEEK_BELOW = 0
ST_SEEK_TAG = 1
ST_SEEK_BACK = 2
ST_SEEK_BREAK = 3


def _tod_min(ts: Any) -> int:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize(ET)
    else:
        t = t.tz_convert(ET)
    tt = t.timetz().replace(tzinfo=None) if False else t.time().replace(tzinfo=None)
    return int(tt.hour) * 60 + int(tt.minute)


def scan_symbol(sym: str, df_rth: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    n = len(df_rth)
    ts = pd.to_datetime(df_rth["ts"], utc=True).dt.tz_convert(ET)
    o = df_rth["open"].to_numpy(dtype=float)
    h = df_rth["high"].to_numpy(dtype=float)
    c = df_rth["close"].to_numpy(dtype=float)
    kama = kama_close(c)
    sess = ts.dt.strftime("%Y-%m-%d").to_numpy()
    tod = (ts.dt.hour.to_numpy(dtype=int) * 60 + ts.dt.minute.to_numpy(dtype=int)).astype(int)
    dates = ts.dt.date.to_numpy()
    ts_np = ts.to_numpy()

    flat_min = FLAT_T.hour * 60 + FLAT_T.minute
    open_min = SESSION_OPEN.hour * 60 + SESSION_OPEN.minute

    n_sess = int(pd.Series(sess).nunique()) if n else 0
    cov = {
        "symbol": sym,
        "n_1m": n,
        "n_sessions": n_sess,
        "min_ts": str(ts.min()) if n else "",
        "max_ts": str(ts.max()) if n else "",
        "usable": n >= MIN_RTH_BARS,
    }
    if n < MIN_RTH_BARS:
        return [], cov

    trades: list[dict[str, Any]] = []
    for arm in ARMS:
        overnight = arm == ARM_A
        state = ST_SEEK_BELOW
        in_pos = False
        entry_i = -1
        entry_px = float("nan")
        pending_stop = False
        below_ts = tag_ts = back_ts = signal_ts = ""
        below_px = tag_kama = back_px = signal_kama = float("nan")

        def reset_setup() -> None:
            nonlocal state, below_ts, tag_ts, back_ts, signal_ts
            nonlocal below_px, tag_kama, back_px, signal_kama
            state = ST_SEEK_BELOW
            below_ts = tag_ts = back_ts = signal_ts = ""
            below_px = tag_kama = back_px = signal_kama = float("nan")

        def close_trade(exit_i: int, exit_px: float, exit_type: str) -> None:
            nonlocal in_pos, pending_stop, entry_i, entry_px
            if not in_pos or entry_i < 0:
                in_pos = False
                pending_stop = False
                return
            if not (math.isfinite(entry_px) and entry_px > 0 and math.isfinite(exit_px) and exit_px > 0):
                in_pos = False
                pending_stop = False
                reset_setup()
                return
            if exit_i == entry_i:
                in_pos = False
                pending_stop = False
                reset_setup()
                return
            shares = int(SHEET // entry_px)
            if shares < 1:
                in_pos = False
                pending_stop = False
                reset_setup()
                return
            pnl_pct = (exit_px / entry_px - 1.0) * 100.0
            if COSTS_BPS:
                pnl_pct -= 2.0 * (COSTS_BPS / 100.0)
            pnl_usd = shares * (exit_px - entry_px)
            et = pd.Timestamp(ts_np[entry_i])
            xt = pd.Timestamp(ts_np[exit_i])
            hold_min = max(0.0, (xt - et).total_seconds() / 60.0)
            ed = et.date()
            trades.append(
                {
                    "symbol": sym,
                    "arm": arm,
                    "entry_date": ed.isoformat(),
                    "session": ed.isoformat(),
                    "split": "OOS" if ed >= SHORT_TAPE_OOS else "IS",
                    "entry_ts": str(et),
                    "exit_ts": str(xt),
                    "entry_px": float(entry_px),
                    "exit_px": float(exit_px),
                    "shares": shares,
                    "pnl_pct": float(pnl_pct),
                    "pnl_usd": float(pnl_usd),
                    "hold_min": float(hold_min),
                    "hold_days": float(hold_min / 1440.0),
                    "exit_type": exit_type,
                    "below_ts": below_ts,
                    "tag_ts": tag_ts,
                    "back_ts": back_ts,
                    "signal_ts": signal_ts,
                    "entry_kama": float(kama[entry_i]) if math.isfinite(float(kama[entry_i])) else float("nan"),
                    "exit_kama": float(kama[exit_i]) if math.isfinite(float(kama[exit_i])) else float("nan"),
                    "below_px": float(below_px) if math.isfinite(below_px) else float("nan"),
                    "tag_kama": float(tag_kama) if math.isfinite(tag_kama) else float("nan"),
                    "back_px": float(back_px) if math.isfinite(back_px) else float("nan"),
                    "signal_kama": float(signal_kama) if math.isfinite(signal_kama) else float("nan"),
                    "win": 1 if pnl_pct > 0 else 0,
                }
            )
            in_pos = False
            pending_stop = False
            entry_i = -1
            entry_px = float("nan")
            reset_setup()

        for i in range(n):
            ki = float(kama[i])
            oi = float(o[i])
            hi = float(h[i])
            ci = float(c[i])
            k_prev = float(kama[i - 1]) if i > 0 else float("nan")

            if in_pos:
                new_sess = i > 0 and sess[i] != sess[i - 1]
                if overnight and new_sess and math.isfinite(k_prev) and math.isfinite(oi) and oi < k_prev:
                    close_trade(i, oi, "GAP_STOP")
                    # fall through so this bar can start a new setup
                elif (not overnight) and tod[i] >= flat_min:
                    close_trade(i, oi, "EOD_FLAT")
                    continue
                elif pending_stop:
                    close_trade(i, oi, "STOP")
                    # fall through

            if in_pos:
                if math.isfinite(ci) and math.isfinite(ki) and ci < ki:
                    pending_stop = True
                continue

            # --- setup (flat) ---
            if not (math.isfinite(ci) and math.isfinite(ki)):
                continue

            if state == ST_SEEK_BELOW:
                if ci < ki:
                    state = ST_SEEK_TAG
                    below_ts = str(pd.Timestamp(ts_np[i]))
                    below_px = ci
            elif state == ST_SEEK_TAG:
                tagged = math.isfinite(hi) and hi >= ki
                if tagged and ci > ki:
                    reset_setup()
                    # now above — stay SEEK_BELOW
                elif tagged and ci < ki:
                    state = ST_SEEK_BREAK
                    tag_ts = str(pd.Timestamp(ts_np[i]))
                    tag_kama = ki
                    back_ts = tag_ts
                    back_px = ci
                elif tagged:
                    state = ST_SEEK_BACK
                    tag_ts = str(pd.Timestamp(ts_np[i]))
                    tag_kama = ki
                elif ci < ki:
                    below_ts = str(pd.Timestamp(ts_np[i]))
                    below_px = ci
            elif state == ST_SEEK_BACK:
                if ci > ki:
                    reset_setup()
                elif ci < ki:
                    state = ST_SEEK_BREAK
                    back_ts = str(pd.Timestamp(ts_np[i]))
                    back_px = ci
            elif state == ST_SEEK_BREAK:
                if ci > ki:
                    # signal: fill next open
                    if i + 1 >= n:
                        reset_setup()
                        continue
                    fill_i = i + 1
                    fill_px = float(o[fill_i])
                    if not (math.isfinite(fill_px) and fill_px > 0):
                        reset_setup()
                        continue
                    if not overnight:
                        if sess[fill_i] != sess[i] or int(tod[fill_i]) >= flat_min:
                            reset_setup()
                            continue
                    # skip same-bar fill + immediate stop
                    k_sig = ki
                    k_fill_prev = k_sig
                    gap_dead = (
                        overnight
                        and sess[fill_i] != sess[i]
                        and math.isfinite(k_fill_prev)
                        and fill_px < k_fill_prev
                    )
                    if gap_dead:
                        reset_setup()
                        continue
                    signal_ts = str(pd.Timestamp(ts_np[i]))
                    signal_kama = ki
                    in_pos = True
                    entry_i = fill_i
                    entry_px = fill_px
                    pending_stop = False
                    # jump index conceptually: the fill bar is processed next loop
                    # If fill bar close is already below, pending_stop will set on that iteration
                    # We must not skip fill_i — loop will hit it next.
                    # If we filled, do not also advance setup on bar i.
                    continue
                # stay in SEEK_BREAK while still waiting

        if in_pos:
            last = n - 1
            close_trade(last, float(c[last]), "TAPE_END")

    cov["n_trades_all_arms"] = len(trades)
    return trades, cov


def metrics_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "N": 0,
        "Wins": 0,
        "Losses": 0,
        "Win%": float("nan"),
        "Avg_PnL_%": float("nan"),
        "AVG_PNL_PCT_WO_MAX": float("nan"),
        "Expectancy_%": float("nan"),
        "Expectancy_$": float("nan"),
        "Avg_Win_%": float("nan"),
        "Avg_Loss_%": float("nan"),
        "WL_count_ratio": float("nan"),
        "Profit_Factor": float("nan"),
        "Ann_ROR_%": float("nan"),
        "Max_DD_%": float("nan"),
        "Calmar": float("nan"),
        "Sharpe": float("nan"),
        "Avg_min_held": float("nan"),
        "Med_min_held": float("nan"),
        "Avg_days_held": float("nan"),
        "Med_days_held": float("nan"),
        "Capital_days": float("nan"),
        "Profit_per_cap_day": float("nan"),
        "Losing_streak": 0,
        "stop_out_%": float("nan"),
        "n_symbols": 0,
        "exit_mix": {},
    }
    if n == 0:
        return empty
    pnls = [float(t["pnl_pct"]) for t in trades]
    usds = [float(t["pnl_usd"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    w_usd = [u for u in usds if u > 0]
    l_usd = [u for u in usds if u <= 0]
    gross_win = sum(w_usd)
    gross_loss = abs(sum(l_usd))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else float("nan"))
    wo = pnls.copy()
    if wins:
        wo.remove(max(pnls))
    ov_rows = []
    holds = []
    streak = max_streak = 0
    for t in trades:
        et = pd.Timestamp(t["entry_ts"])
        xt = pd.Timestamp(t["exit_ts"])
        hold_days = max(1.0 / 1440.0, (xt - et).total_seconds() / 86400.0)
        hm = float(t.get("hold_min") or hold_days * 1440.0)
        holds.append(hm)
        ov_rows.append(
            {
                "pnl_d": float(t["pnl_usd"]),
                "pnl": float(t["pnl_pct"]),
                "days": hold_days,
                "closed": xt.date(),
                "opened": et.date(),
            }
        )
        if float(t["pnl_pct"]) <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    ov = overlay_ann_ror_max_dd(ov_rows, cash=SHEET, initial_account=INIT_ACCT) or {}
    cap_days = float(sum(holds)) / 1440.0
    tot_usd = float(sum(usds))
    exit_mix: dict[str, int] = {}
    for t in trades:
        exit_mix[str(t["exit_type"])] = exit_mix.get(str(t["exit_type"]), 0) + 1
    n_stop = exit_mix.get("STOP", 0) + exit_mix.get("GAP_STOP", 0)
    return {
        "N": n,
        "Wins": len(wins),
        "Losses": len(losses),
        "Win%": 100.0 * len(wins) / n,
        "Avg_PnL_%": float(np.mean(pnls)),
        "AVG_PNL_PCT_WO_MAX": float(np.mean(wo)) if wo else float("nan"),
        "Expectancy_%": float(np.mean(pnls)),
        "Expectancy_$": float(np.mean(usds)),
        "Avg_Win_%": float(np.mean(wins)) if wins else float("nan"),
        "Avg_Loss_%": float(np.mean(losses)) if losses else float("nan"),
        "WL_count_ratio": (len(wins) / len(losses)) if losses else float("nan"),
        "Profit_Factor": pf,
        "Ann_ROR_%": ov.get("ann_ror", float("nan")),
        "Max_DD_%": ov.get("max_dd", float("nan")),
        "Calmar": ov.get("calmar", float("nan")),
        "Sharpe": ov.get("sharpe", float("nan")),
        "Avg_min_held": float(np.mean(holds)) if holds else float("nan"),
        "Med_min_held": float(np.median(holds)) if holds else float("nan"),
        "Avg_days_held": float(np.mean(holds)) / 1440.0 if holds else float("nan"),
        "Med_days_held": float(np.median(holds)) / 1440.0 if holds else float("nan"),
        "Capital_days": cap_days,
        "Profit_per_cap_day": (tot_usd / cap_days) if cap_days > 0 else float("nan"),
        "Losing_streak": max_streak,
        "stop_out_%": 100.0 * n_stop / n,
        "n_symbols": len({t["symbol"] for t in trades}),
        "exit_mix": exit_mix,
    }


def fmt_num(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(x):
        return "—"
    if abs(x) == float("inf"):
        return "inf"
    return f"{x:.{nd}f}"


def fmt_delta(cur: Any, base: Any, nd: int = 2) -> str:
    try:
        a = float(cur)
        b = float(base)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(a) or not math.isfinite(b):
        return "—"
    return f"{a - b:+.{nd}f}"


def quality_score(m: dict[str, Any]) -> tuple[float, float, float]:
    avg = m.get("Avg_PnL_%")
    pf = m.get("Profit_Factor")
    wr = m.get("Win%")
    a = float(avg) if avg is not None and math.isfinite(float(avg)) else -999.0
    p = float(pf) if pf is not None and math.isfinite(float(pf)) else 0.0
    p = min(p, 10.0)
    w = float(wr) if wr is not None and math.isfinite(float(wr)) else 0.0
    return (a, p, w)


def oos_softened(is_m: dict[str, Any], oos_m: dict[str, Any]) -> bool:
    if is_m.get("N", 0) < 8 or oos_m.get("N", 0) < 5:
        return False
    try:
        if float(oos_m.get("Avg_PnL_%") or 0) < float(is_m.get("Avg_PnL_%") or 0) - 0.01:
            return True
    except (TypeError, ValueError):
        pass
    pf_is = is_m.get("Profit_Factor")
    pf_oos = oos_m.get("Profit_Factor")
    try:
        if (
            math.isfinite(float(pf_is))
            and math.isfinite(float(pf_oos))
            and float(pf_oos) < float(pf_is) * 0.85
        ):
            return True
    except (TypeError, ValueError):
        pass
    return False


def judge_book(m: dict[str, Any], *, oos_soft: bool, thin_n: int = 30) -> str:
    """System-quality verdict (not 'beat control'). Quality over count."""
    n = int(m.get("N") or 0)
    if oos_soft:
        return "HOLD"
    if n < thin_n:
        return "HOLD"
    avg = m.get("Avg_PnL_%")
    pf = m.get("Profit_Factor")
    try:
        a = float(avg)
        p = float(pf)
    except (TypeError, ValueError):
        return "HOLD"
    if not math.isfinite(a) or not math.isfinite(p):
        return "HOLD"
    if a > 0.02 and p >= 1.05:
        return "KEEP"
    if a <= 0.0 and p < 1.0:
        return "DISMISS"
    return "HOLD"


def judge_vs_control(cand: dict[str, Any], ctrl: dict[str, Any], *, oos_soft: bool) -> str:
    if oos_soft:
        return "HOLD"
    if cand.get("N", 0) < 8 or ctrl.get("N", 0) < 8:
        return "HOLD"
    ca, _, _ = quality_score(cand)
    ba, _, _ = quality_score(ctrl)
    n_ratio = cand["N"] / max(1, ctrl["N"])
    if n_ratio < 0.4:
        return "HOLD"
    pf_c = cand.get("Profit_Factor")
    pf_b = ctrl.get("Profit_Factor")
    try:
        pf_ok = math.isfinite(float(pf_c)) and math.isfinite(float(pf_b)) and float(pf_c) >= float(pf_b) * 0.95
    except (TypeError, ValueError):
        pf_ok = False
    if ca > ba + 0.02 and pf_ok:
        if ca <= 0 and (not math.isfinite(float(pf_c or 0)) or float(pf_c) < 1.0):
            return "HOLD"
        return "LEAN KEEP"
    if ca < ba - 0.02:
        return "DISMISS"
    return "HOLD"


def write_baseline(
    path: Path,
    *,
    stamp: str,
    symbols: list[str],
    coverage_rows: list[dict[str, Any]],
    n_trades: int,
    verdict_line: str,
) -> None:
    usable = [r for r in coverage_rows if r.get("usable")]
    firsts = [r["min_ts"] for r in usable if r.get("min_ts")]
    lasts = [r["max_ts"] for r in usable if r.get("max_ts")]
    n_1m = sum(int(r.get("n_1m") or 0) for r in usable)
    n_sess = max((int(r.get("n_sessions") or 0) for r in usable), default=0)
    text = f"""# BASELINE — Adaptive EMA(50) 1m failed-tag reclaim — `{stamp}`

**System:** `{SYSTEM}` (research only). **Not** DailyRun. **Not** gold.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

Exponential Moving Average (**EMA**) is the usual smoothed average. The shop has **no** in-repo Adaptive Exponential Moving Average (**AEMA**) / Kaufman Adaptive Moving Average (**KAMA**) / Adaptive Moving Average (**AMA**) — searched `adaptive EMA`, `AMA`, `KAMA`, `AEMA`. Fallback is **not** a plain EMA(50). Frozen indicator: **KAMA**.

Regular Trading Hours (**RTH**) = the cash session 09:30–16:00 US/Eastern. In-Sample (**IS**) / Out-Of-Sample (**OOS**) = the chronological holdout. Profit and Loss (**PnL**) = percent (and sheet dollars) per trade.

## Adaptive average (frozen)

| Knob | Value |
|------|--------|
| Indicator | Kaufman Adaptive Moving Average (**KAMA**) |
| ER length (Kaufman “length”) | **{KAMA_ER}** (Paul’s “adaptive EMA (50)”) |
| Fast end | **{KAMA_FAST}** (textbook) |
| Slow end | **{KAMA_SLOW}** (textbook) |
| Seed | First valid KAMA = close at the first bar where ER is defined |
| Series | RTH 1-minute closes only (sessions concatenated; no pre/post-market) |
| Textbook note | Classic Kaufman ER window is **10**. We use **{KAMA_ER}** so the length matches Paul’s “50”. We did **not** shop ER / fast / slow. |
| Not used | Plain EMA(50). Do not retune to EMA if KAMA looks bad. |

KAMA update: `ER = |close - close[50]| / sum(|Δclose|, 50)`; `SC = [ER × (2/3 − 2/31) + 2/31]²`; `KAMA = prior + SC × (close − prior)`.

## User mapping

Long-only 1-minute **failed tag** of KAMA(50) from below, then a later **close through**. Do **not** buy the first reclaim.

## Freeze — entry

Sequence on **completed** 1-minute bars, RTH only (`tod >= 09:30` and `tod < 16:00` ET).

1. **Below:** 1m close < KAMA.
2. **Hit from below:** a later 1m **high ≥ KAMA** (wick tag; frozen as **high**, not close).
3. **Back below:** a later 1m close < KAMA. Same-bar wick tag + close still below **counts** as tag + back-below (failed-test candle).
4. **Break through:** a later 1m **close > KAMA**. **Do not buy** if the first tag bar also closes through (first reclaim — cancel).
5. **Fill:** **next RTH 1m open** after the break-through close (no same-bar look-ahead).

| Knob | Value |
|------|--------|
| Side | Long only |
| Positions | One per symbol. Ignore new signals while in a trade. |
| Sequence timeout | **None** (may span sessions). |
| Arm B fill gate | Same session and **before 15:55 ET**. |
| Arm A fill | Next RTH open, including the next session. |
| Warmup | No signal until KAMA is defined (bar index ≥ {KAMA_ER}). |
| Costs | {COSTS_BPS:g} bps (research, no slippage) |
| Sheet / overlay | ${SHEET:,.0f} / trade floor-shares; Max DD on ${INIT_ACCT:,.0f} seed |

## Freeze — exit

Stop = **1m close < KAMA** (trails). Fill = **next RTH 1m open**.

| Arm | Session identity |
|-----|------------------|
| **A (`{ARM_A}`)** | May hold overnight. Resume 09:30 next RTH. Open < prior KAMA → **GAP_STOP at open**. |
| **B (`{ARM_B}`)** | Flatten at **15:55 ET open** (`EOD_FLAT`). No overnight. |

Last bar of tape: `TAPE_END` at that close.

## Split

Canonical shop IS (`entry_date < 2024-01-01`) is **N/A** — Yahoo 1m here is Jul–Sep 2026 only.

Short-tape chronological split (same cut as `intraday_htf_retest_20260916`): **IS** = `entry_date < {SHORT_TAPE_OOS.isoformat()}`; **OOS** = `entry_date >= {SHORT_TAPE_OOS.isoformat()}`. OOS is report-only. If OOS softens vs IS → **HOLD**, do not retune.

## Coverage

Usable symbols (RTH 1m bars ≥ {MIN_RTH_BARS}): **{len(usable)}** of {len(symbols)} parquet names.
RTH 1m bars (usable): **{n_1m:,}**. Max sessions on a name: **{n_sess}**.
Store span (min first / max last): {min(firsts) if firsts else "—"} → {max(lasts) if lasts else "—"}.

Closed trades this stamp (both arms): **N={n_trades}**.

{verdict_line}

## Selection bias

Arm A vs Arm B is one session knob on the **same** short tape. In-sample selection even with an OOS row. Research candidate only. No KAMA param shopping after seeing the table.

## Promotion

Research candidate. **Not** gold. **Not** DailyRun.
"""
    path.write_text(text, encoding="utf-8")


METRIC_COLS = [
    ("N", "num"),
    ("n_symbols", "num"),
    ("Win%", "num"),
    ("Avg PnL %", "num"),
    ("Avg% w/o max", "num"),
    ("Expectancy %", "num"),
    ("Expectancy $", "num"),
    ("Avg win %", "num"),
    ("Avg loss %", "num"),
    ("W/L count", "num"),
    ("PF", "num"),
    ("Ann ROR %", "num"),
    ("Max DD %", "num"),
    ("Calmar", "num"),
    ("Sharpe", "num"),
    ("Avg min held", "num"),
    ("Med min held", "num"),
    ("Avg days held", "num"),
    ("Capital days", "num"),
    ("Profit / cap day", "num"),
    ("Lose streak", "num"),
    ("Stop-out %", "num"),
]


def _metric_cells(m: dict[str, Any]) -> list[str]:
    return [
        str(int(m.get("N") or 0)),
        str(int(m.get("n_symbols") or 0)),
        fmt_num(m.get("Win%"), 1),
        fmt_num(m.get("Avg_PnL_%"), 3),
        fmt_num(m.get("AVG_PNL_PCT_WO_MAX"), 3),
        fmt_num(m.get("Expectancy_%"), 3),
        format_money(m.get("Expectancy_$")),
        fmt_num(m.get("Avg_Win_%"), 3),
        fmt_num(m.get("Avg_Loss_%"), 3),
        fmt_num(m.get("WL_count_ratio"), 2),
        fmt_num(m.get("Profit_Factor"), 2),
        fmt_num(m.get("Ann_ROR_%"), 1),
        fmt_num(m.get("Max_DD_%"), 2),
        fmt_num(m.get("Calmar"), 2),
        fmt_num(m.get("Sharpe"), 2),
        fmt_num(m.get("Avg_min_held"), 1),
        fmt_num(m.get("Med_min_held"), 1),
        fmt_num(m.get("Avg_days_held"), 4),
        fmt_num(m.get("Capital_days"), 1),
        format_money(m.get("Profit_per_cap_day")),
        str(int(m.get("Losing_streak") or 0)),
        fmt_num(m.get("stop_out_%"), 1),
    ]


def exit_mix_text(m: dict[str, Any]) -> str:
    mix = m.get("exit_mix") or {}
    n = int(m.get("N") or 0)
    if not mix or n <= 0:
        return "—"
    parts = []
    for k in sorted(mix):
        c = int(mix[k])
        parts.append(f"{k} {c} ({100.0 * c / n:.1f}%)")
    return "; ".join(parts)


def write_html(
    path: Path,
    *,
    stamp: str,
    symbols: list[str],
    coverage_rows: list[dict[str, Any]],
    books: list[dict[str, Any]],
    per_symbol: list[dict[str, Any]],
    sample_trades: list[dict[str, Any]],
    n_trades_total: int,
    verdict_note: str,
    headline: str,
    coverage_note: str,
) -> None:
    id_cols = [
        ("book", "text"),
        ("arm", "text"),
        ("split", "text"),
        ("verdict", "text"),
        ("exit mix", "text"),
    ]
    extra = (("Δ Avg% vs A", "num"), ("Δ PF vs A", "num"), ("Δ WR vs A", "num"))
    head = "".join(sortable_th(c, t) for c, t in id_cols + METRIC_COLS)
    head_ab = "".join(sortable_th(c, t) for c, t in id_cols + METRIC_COLS + list(extra))

    def row_html(b: dict[str, Any], *, deltas: bool = False) -> str:
        cells = [
            html_mod.escape(str(b.get("book", ""))),
            html_mod.escape(str(b.get("arm", ""))),
            html_mod.escape(str(b.get("split", ""))),
            html_mod.escape(str(b.get("verdict", ""))),
            html_mod.escape(exit_mix_text(b["m"])),
        ]
        cells.extend(_metric_cells(b["m"]))
        if deltas:
            cells.extend(
                [
                    html_mod.escape(str(b.get("d_avg", "—"))),
                    html_mod.escape(str(b.get("d_pf", "—"))),
                    html_mod.escape(str(b.get("d_wr", "—"))),
                ]
            )
        cls = ' class="total-row"' if b.get("total") else ""
        return f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    full_books = [b for b in books if b.get("table") == "full"]
    split_books = [b for b in books if b.get("table") == "split"]

    cov_head = "".join(
        sortable_th(c, t)
        for c, t in (
            ("symbol", "text"),
            ("1m bars", "num"),
            ("sessions", "num"),
            ("first", "date"),
            ("last", "date"),
            ("usable", "text"),
        )
    )
    cov_rows_html = []
    for r in coverage_rows:
        cov_rows_html.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{r['n_1m']}</td><td>{r['n_sessions']}</td>"
            f"<td>{html_mod.escape(str(r['min_ts'])[:19])}</td>"
            f"<td>{html_mod.escape(str(r['max_ts'])[:19])}</td>"
            f"<td>{'yes' if r.get('usable') else 'no'}</td>"
            "</tr>"
        )

    sym_head = "".join(
        sortable_th(c, t)
        for c, t in (
            ("symbol", "text"),
            ("arm", "text"),
            ("N", "num"),
            ("Win%", "num"),
            ("Avg PnL %", "num"),
            ("PF", "num"),
            ("Avg min held", "num"),
            ("Med min held", "num"),
            ("Expectancy $", "num"),
        )
    )
    sym_rows = []
    for r in per_symbol:
        m = r["m"]
        if int(m.get("N") or 0) <= 0:
            continue
        sym_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{html_mod.escape(r['arm'])}</td>"
            f"<td>{int(m.get('N') or 0)}</td>"
            f"<td>{fmt_num(m.get('Win%'), 1)}</td>"
            f"<td>{fmt_num(m.get('Avg_PnL_%'), 3)}</td>"
            f"<td>{fmt_num(m.get('Profit_Factor'), 2)}</td>"
            f"<td>{fmt_num(m.get('Avg_min_held'), 1)}</td>"
            f"<td>{fmt_num(m.get('Med_min_held'), 1)}</td>"
            f"<td>{format_money(m.get('Expectancy_$'))}</td>"
            "</tr>"
        )

    ev_cols = [
        ("symbol", "text"),
        ("arm", "text"),
        ("split", "text"),
        ("entry", "date"),
        ("exit", "date"),
        ("entry px", "num"),
        ("exit px", "num"),
        ("PnL %", "num"),
        ("PnL $", "num"),
        ("min held", "num"),
        ("exit", "text"),
    ]
    ehead = "".join(sortable_th(c, t) for c, t in ev_cols)
    erows = []
    for t in sample_trades[:400]:
        erows.append(
            "<tr>"
            f"<td>{html_mod.escape(t['symbol'])}</td>"
            f"<td>{html_mod.escape(t['arm'])}</td>"
            f"<td>{html_mod.escape(t['split'])}</td>"
            f"<td>{html_mod.escape(str(t['entry_ts'])[:19])}</td>"
            f"<td>{html_mod.escape(str(t['exit_ts'])[:19])}</td>"
            f"<td>{fmt_num(t.get('entry_px'), 4)}</td>"
            f"<td>{fmt_num(t.get('exit_px'), 4)}</td>"
            f"<td>{fmt_num(t.get('pnl_pct'), 3)}</td>"
            f"<td>{format_money(t.get('pnl_usd'))}</td>"
            f"<td>{fmt_num(t.get('hold_min'), 1)}</td>"
            f"<td>{html_mod.escape(str(t.get('exit_type')))}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(stamp)} — KAMA(50) 1m reclaim</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, Segoe UI, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 28px 0 8px; }}
p, li {{ line-height: 1.45; }}
.meta, .note {{ color: #475569; font-size: 0.95rem; }}
.callout {{ background: #fff; border: 1px solid #cbd5e1; border-left: 4px solid #0369a1; padding: 12px 16px; margin: 16px 0; }}
.callout h2 {{ margin-top: 0; }}
blockquote {{ margin: 8px 0; padding-left: 12px; border-left: 3px solid #94a3b8; color: #334155; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.85rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; }}
table.sortable th {{ background: #f1f5f9; position: sticky; top: 0; }}
.wrap {{ overflow-x: auto; }}
{SORT_CSS}
</style>
</head>
<body>
<h1>KAMA(50) 1-minute failed-tag reclaim — {html_mod.escape(stamp)}</h1>
<p class="meta">Research only. Not gold. Not DailyRun. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>Exponential Moving Average (<strong>EMA</strong>) is the usual smoothed average. No shop Adaptive Exponential Moving Average (<strong>AEMA</strong>) / Kaufman Adaptive Moving Average (<strong>KAMA</strong>) / Adaptive Moving Average (<strong>AMA</strong>) exists — we froze <strong>KAMA</strong> length 50 (Efficiency Ratio / <strong>ER</strong> window 50, fast 2, slow 30). Regular Trading Hours (<strong>RTH</strong>) = 09:30–16:00 ET. In-Sample (<strong>IS</strong>) = entry before 2026-09-02; Out-Of-Sample (<strong>OOS</strong>) = on/after (report-only). Profit and Loss (<strong>PnL</strong>) is percent per trade. Hold is native <strong>minutes</strong>.</p>
</div>

<p><strong>Headline:</strong> {html_mod.escape(headline)}</p>
<p class="note">{html_mod.escape(verdict_note)}</p>
<p class="note">{html_mod.escape(coverage_note)} Universe: {len(symbols)} parquet names. Costs {COSTS_BPS:g} bps. Sheet {format_money(SHEET)} / trade; overlay seed {format_money(INIT_ACCT)}. Annualized Rate of Return (<strong>Ann ROR</strong>) is the Closed overlay — minute holds make the 365-day compound noisy; judge Avg% / profit factor / win% first. Max Drawdown (<strong>DD</strong>) uses the $500k seed path.</p>

<h2>Full book (both arms)</h2>
<p class="meta">Arm A is the literal overnight reading (control). Arm B flattens at 15:55. Verdict on each book is system quality (KEEP / HOLD / DISMISS), not only “beat A”.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{head_ab}</tr></thead>
<tbody>
{''.join(row_html(b, deltas=True) for b in full_books)}
</tbody>
</table>
</div>

<h2>Short-tape IS / OOS</h2>
<p class="note">Shop default <code>entry &lt; 2024-01-01</code> is empty on this tape. Labeled alternative: IS = entry before {SHORT_TAPE_OOS.isoformat()}; OOS = on/after. If OOS Avg% or PF softens vs IS on the same arm → HOLD, do not retune.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(row_html(b) for b in split_books)}
</tbody>
</table>
</div>

<h2>Per-symbol (N &gt; 0)</h2>
<p class="meta">Click headers to sort. Names with zero trades omitted here; see coverage.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{sym_head}</tr></thead>
<tbody>
{''.join(sym_rows)}
</tbody>
</table>
</div>

<h2>Coverage</h2>
<div class="wrap">
<table class="sortable">
<thead><tr>{cov_head}</tr></thead>
<tbody>
{''.join(cov_rows_html)}
</tbody>
</table>
</div>

<h2>Trades (first {min(400, len(sample_trades))} of {n_trades_total})</h2>
<div class="wrap">
<table class="sortable">
<thead><tr>{ehead}</tr></thead>
<tbody>
{''.join(erows)}
</tbody>
</table>
</div>

<p class="note">Full book: <code>trades.csv</code>. Freeze: <code>BASELINE.md</code>. Hypothesis: <code>HYPOTHESIS.md</code>. Research candidate only.</p>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    if not trades:
        path.write_text("", encoding="utf-8")
        return
    keys = list(trades[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writerow = w.writerow  # keep
        w.writeheader()
        for t in trades:
            row = dict(t)
            for k, v in row.items():
                if isinstance(v, float):
                    row[k] = f"{v:.6f}" if math.isfinite(v) else ""
            w.writerow(row)


def write_equity(path: Path, trades: list[dict[str, Any]]) -> None:
    by_d: dict[str, float] = {}
    for t in trades:
        d = str(pd.Timestamp(t["exit_ts"]).date())
        by_d[d] = by_d.get(d, 0.0) + float(t["pnl_usd"])
    eq = INIT_ACCT
    peak = INIT_ACCT
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "day_pnl_usd", "equity", "dd_pct"])
        for d in sorted(by_d):
            eq += by_d[d]
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100.0 if peak else 0.0
            w.writerow([d, f"{by_d[d]:.2f}", f"{eq:.2f}", f"{dd:.4f}"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("-s", "--symbols", default="", help="Comma override")
    ap.add_argument("--max-symbols", type=int, default=0, help="Debug cap (0 = all usable parquet)")
    args = ap.parse_args()
    stamp = args.stamp
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.symbols.strip():
        symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    else:
        symbols = list_parquet_symbols(DEFAULT_1M_DIR)
    if args.max_symbols and args.max_symbols > 0:
        symbols = symbols[: int(args.max_symbols)]

    print(
        f"stamp={stamp} parquet_names={len(symbols)} KAMA ER={KAMA_ER} "
        f"fast={KAMA_FAST} slow={KAMA_SLOW} costs={COSTS_BPS}bps",
        flush=True,
    )

    all_trades: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    usable_syms: list[str] = []
    for i, sym in enumerate(symbols, 1):
        raw = read_1m(sym)
        df = rth_filter(raw)
        if i == 1 or i % 50 == 0 or i == len(symbols):
            print(f"[{i}/{len(symbols)}] {sym} raw={len(raw)} rth={len(df)}", flush=True)
        tr, cov = scan_symbol(sym, df)
        coverage_rows.append(cov)
        if cov.get("usable"):
            usable_syms.append(sym)
        all_trades.extend(tr)

    def subset(*, arm: Optional[str] = None, split: Optional[str] = None) -> list[dict[str, Any]]:
        rows = all_trades
        if arm:
            rows = [t for t in rows if t["arm"] == arm]
        if split:
            rows = [t for t in rows if t["split"] == split]
        return rows

    books: list[dict[str, Any]] = []
    ctrl_full = metrics_from_trades(subset(arm=CONTROL_ARM))
    for arm in ARMS:
        m = metrics_from_trades(subset(arm=arm))
        is_m = metrics_from_trades(subset(arm=arm, split="IS"))
        oos_m = metrics_from_trades(subset(arm=arm, split="OOS"))
        soft = oos_softened(is_m, oos_m)
        sys_v = judge_book(m, oos_soft=soft)
        vs_a = "control" if arm == CONTROL_ARM else judge_vs_control(m, ctrl_full, oos_soft=soft)
        verdict = sys_v if arm == CONTROL_ARM else f"{sys_v} · vs A: {vs_a}"
        if soft:
            verdict += " · OOS soft"
        books.append(
            {
                "table": "full",
                "book": f"{arm} FULL",
                "arm": arm,
                "split": "FULL",
                "verdict": verdict,
                "m": m,
                "d_avg": "—" if arm == CONTROL_ARM else fmt_delta(m.get("Avg_PnL_%"), ctrl_full.get("Avg_PnL_%"), 3),
                "d_pf": "—" if arm == CONTROL_ARM else fmt_delta(m.get("Profit_Factor"), ctrl_full.get("Profit_Factor"), 2),
                "d_wr": "—" if arm == CONTROL_ARM else fmt_delta(m.get("Win%"), ctrl_full.get("Win%"), 1),
            }
        )
        books.append(
            {
                "table": "split",
                "book": f"{arm} IS",
                "arm": arm,
                "split": "IS",
                "verdict": "",
                "m": is_m,
            }
        )
        books.append(
            {
                "table": "split",
                "book": f"{arm} OOS",
                "arm": arm,
                "split": "OOS",
                "verdict": "HOLD" if soft else "",
                "m": oos_m,
            }
        )

    per_symbol: list[dict[str, Any]] = []
    by_sym_arm: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for t in all_trades:
        by_sym_arm.setdefault((t["symbol"], t["arm"]), []).append(t)
    for (sym, arm), rows in sorted(by_sym_arm.items()):
        per_symbol.append({"symbol": sym, "arm": arm, "m": metrics_from_trades(rows)})

    a_m = next(b["m"] for b in books if b["table"] == "full" and b["arm"] == ARM_A)
    b_m = next(b["m"] for b in books if b["table"] == "full" and b["arm"] == ARM_B)
    a_v = next(b["verdict"] for b in books if b["table"] == "full" and b["arm"] == ARM_A)
    b_v = next(b["verdict"] for b in books if b["table"] == "full" and b["arm"] == ARM_B)
    headline = (
        f"Arm A (overnight) N={a_m['N']} WR={fmt_num(a_m.get('Win%'),1)}% "
        f"Avg={fmt_num(a_m.get('Avg_PnL_%'),3)}% PF={fmt_num(a_m.get('Profit_Factor'),2)} "
        f"hold={fmt_num(a_m.get('Avg_min_held'),1)}m => {a_v}. "
        f"Arm B (flat 15:55) N={b_m['N']} WR={fmt_num(b_m.get('Win%'),1)}% "
        f"Avg={fmt_num(b_m.get('Avg_PnL_%'),3)}% PF={fmt_num(b_m.get('Profit_Factor'),2)} "
        f"hold={fmt_num(b_m.get('Avg_min_held'),1)}m => {b_v}."
    )
    any_soft = any("OOS soft" in str(b.get("verdict")) for b in books if b.get("table") == "full")
    verdict_note = (
        "Short Yahoo 1m window (all post-2024). "
        + ("OOS softened on at least one arm → HOLD, do not retune. " if any_soft else "")
        + "Research candidate only; not gold; not DailyRun. "
        + "KEEP needs Avg%>0 and PF≥1.05 with N≥30; losing books with enough N → DISMISS; thin N → HOLD."
    )
    n_1m = sum(int(r["n_1m"]) for r in coverage_rows if r.get("usable"))
    n_sess = max((int(r["n_sessions"]) for r in coverage_rows if r.get("usable")), default=0)
    coverage_note = (
        f"{len(usable_syms)} usable of {len(symbols)} parquet symbols, {n_1m:,} RTH 1m bars, "
        f"up to {n_sess} sessions (typical mega-cap ~Jul 23–Sep 16 2026; some names shorter)."
    )

    write_trades_csv(out_dir / "trades.csv", all_trades)
    write_equity(out_dir / "equity_arm_a.csv", subset(arm=ARM_A))
    write_equity(out_dir / "equity_arm_b.csv", subset(arm=ARM_B))
    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        symbols=symbols,
        coverage_rows=coverage_rows,
        n_trades=len(all_trades),
        verdict_line=headline,
    )
    write_html(
        out_dir / "compare.html",
        stamp=stamp,
        symbols=symbols,
        coverage_rows=coverage_rows,
        books=books,
        per_symbol=per_symbol,
        sample_trades=all_trades,
        n_trades_total=len(all_trades),
        verdict_note=verdict_note,
        headline=headline,
        coverage_note=coverage_note,
    )

    books_path = out_dir / "books.csv"
    with books_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "table",
                "book",
                "arm",
                "split",
                "verdict",
                "N",
                "Win%",
                "Avg_PnL_%",
                "PF",
                "Ann_ROR_%",
                "Max_DD_%",
                "Calmar",
                "Sharpe",
                "Avg_min_held",
                "Capital_days",
                "stop_out_%",
                "exit_mix",
            ]
        )
        for b in books:
            m = b["m"]
            w.writerow(
                [
                    b.get("table"),
                    b.get("book"),
                    b.get("arm"),
                    b.get("split"),
                    b.get("verdict"),
                    m.get("N"),
                    m.get("Win%"),
                    m.get("Avg_PnL_%"),
                    m.get("Profit_Factor"),
                    m.get("Ann_ROR_%"),
                    m.get("Max_DD_%"),
                    m.get("Calmar"),
                    m.get("Sharpe"),
                    m.get("Avg_min_held"),
                    m.get("Capital_days"),
                    m.get("stop_out_%"),
                    json.dumps(m.get("exit_mix") or {}),
                ]
            )

    summary = {
        "stamp": stamp,
        "indicator": "KAMA",
        "kama": {"er": KAMA_ER, "fast": KAMA_FAST, "slow": KAMA_SLOW},
        "n_parquet": len(symbols),
        "n_usable": len(usable_syms),
        "n_trades": len(all_trades),
        "headline": headline,
        "arm_a": {k: a_m[k] for k in a_m if k != "exit_mix"} | {"exit_mix": a_m.get("exit_mix")},
        "arm_b": {k: b_m[k] for k in b_m if k != "exit_mix"} | {"exit_mix": b_m.get("exit_mix")},
        "verdicts": {"arm_a": a_v, "arm_b": b_v},
    }

    def _jsonable(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: _jsonable(v) for k, v in x.items()}
        if isinstance(x, float) and not math.isfinite(x):
            return None
        return x

    (out_dir / "summary.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")

    print(headline, flush=True)
    print(f"wrote {out_dir / 'compare.html'}", flush=True)
    print(f"trades={len(all_trades)} usable={len(usable_syms)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
