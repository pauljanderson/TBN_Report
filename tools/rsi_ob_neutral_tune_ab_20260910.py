#!/usr/bin/env python3
"""One-knob tune A/Bs on the RSI Neutral-after-OB full-universe system.

Control = frozen buy Neutral-after-OB / sell OB (next open, no extra gates).
Arms are one change each (exit RSI, time stop, or a trigger-time entry gate
from IS correlation / post-run). Research only — not gold, not DailyRun.

Usage:
  python tools/rsi_ob_neutral_tune_ab_20260910.py
"""
from __future__ import annotations

import html as html_mod
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "stock_analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "stock_analysis"))
if str(ROOT / "drive" / "paul_experiments") not in sys.path:
    sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from rocket_tbn import _compute_atr_14_arr, _wilder_rsi14_arr  # noqa: E402
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    overlay_ann_ror_max_dd,
)

DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "rsi_ob_neutral_tune_ab_20260910"
OUT_DIR = ROOT / "drive" / "paul_experiments" / STAMP
SRC_STAMP = ROOT / "drive" / "paul_experiments" / "rsi_ob_to_neutral_exit_ob_20260910"
IS_CUTOFF = pd.Timestamp("2024-01-01")
RSI_OB = 70.0
RSI_OS = 30.0
NOTIONAL = 10_000.0
ACCOUNT = DEFAULT_INITIAL_ACCOUNT
ORIGINAL_REQUEST = (
    "can you give me a full universe closed file? run a post run alanysis on it "
    "and tune up and run some AB tests, but also look at the correlation file to "
    "see what other variables may be useful to configure and add them to the AB "
    "tests as well?"
)

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.4rem; margin: 0 0 .35rem; }
h2 { font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
.meta { color: #475569; font-size: .92rem; max-width: 78rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }
.ask { background: #eff6ff; border: 1px solid #bfdbfe; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .84rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
"""

SORT_JS = r"""
<script>
(function () {
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
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      function onActivate(e) {
        if (e.type === "touchend") e.preventDefault();
        var type = th.dataset.sort || "text";
        var dir = th.dataset.dir === "asc" ? -1 : 1;
        table.querySelectorAll("th.sortable-th").forEach(function (h) {
          h.dataset.dir = ""; h.classList.remove("sort-asc", "sort-desc");
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


@dataclass
class Arm:
    name: str
    knob: str
    hypothesis: str
    exit_rsi: float = RSI_OB
    time_stop_days: int = 0
    min_atr_pct: float = 0.0
    max_rsi_trigger: float = RSI_OB
    max_dist52: Optional[float] = None
    min_dist52: Optional[float] = None
    require_above_sma50: bool = False
    min_rel_vol: float = 0.0
    min_rsi_drop: float = 0.0
    max_zscore: Optional[float] = None
    min_spy_1y: Optional[float] = None


def list_universe() -> list[str]:
    return sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv") if p.stem.strip())


def load_ohlcv(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    need = ("date", "open", "high", "low", "close")
    if not all(k in cols for k in need):
        return None
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]], errors="coerce").dt.normalize(),
            "Open": pd.to_numeric(df[cols["open"]], errors="coerce"),
            "High": pd.to_numeric(df[cols["high"]], errors="coerce"),
            "Low": pd.to_numeric(df[cols["low"]], errors="coerce"),
            "Close": pd.to_numeric(df[cols["close"]], errors="coerce"),
        }
    )
    if "volume" in cols:
        out["Volume"] = pd.to_numeric(df[cols["volume"]], errors="coerce")
    else:
        out["Volume"] = np.nan
    out = out.dropna(subset=["Date", "Open", "Close"]).sort_values("Date").drop_duplicates("Date")
    return out.reset_index(drop=True)


def features(df: pd.DataFrame) -> dict[str, np.ndarray]:
    close = df["Close"].to_numpy(dtype=np.float64)
    high = df["High"].to_numpy(dtype=np.float64)
    low = df["Low"].to_numpy(dtype=np.float64)
    vol = df["Volume"].to_numpy(dtype=np.float64)
    n = len(close)
    rsi = _wilder_rsi14_arr(close)
    atr = _compute_atr_14_arr(high, low, close, 14)
    atr_pct = np.where((close > 0) & np.isfinite(atr), atr / close * 100.0, np.nan)
    close_s = pd.Series(close)
    high_s = pd.Series(high)
    vol_s = pd.Series(vol)
    sma50 = close_s.rolling(50, min_periods=50).mean().to_numpy()
    hi52 = high_s.rolling(252, min_periods=20).max().to_numpy()
    dist52 = np.where((hi52 > 0) & np.isfinite(close), (1.0 - close / hi52) * 100.0, np.nan)
    avg10 = vol_s.rolling(10, min_periods=5).mean().to_numpy()
    rel_vol = np.where((avg10 > 0) & np.isfinite(vol), vol / avg10, np.nan)
    mu20 = close_s.rolling(20, min_periods=5).mean().to_numpy()
    sd20 = close_s.rolling(20, min_periods=5).std(ddof=0).to_numpy()
    z = np.where((sd20 > 0) & np.isfinite(close), (close - mu20) / sd20, np.nan)
    prior_ob = np.full(n, np.nan)
    last = np.nan
    for i in range(n):
        if np.isfinite(rsi[i]) and rsi[i] >= RSI_OB:
            last = rsi[i]
        prior_ob[i] = last
    return {
        "close": close,
        "open": df["Open"].to_numpy(dtype=np.float64),
        "rsi": rsi,
        "atr_pct": atr_pct,
        "sma50": sma50,
        "dist52": dist52,
        "rel_vol": rel_vol,
        "z": z,
        "prior_ob": prior_ob,
    }


def gate_ok(arm: Arm, i: int, feat: dict[str, np.ndarray], spy_1y: Optional[float]) -> bool:
    rsi = feat["rsi"][i]
    if not np.isfinite(rsi) or rsi >= arm.max_rsi_trigger:
        return False
    if arm.min_atr_pct > 0:
        a = feat["atr_pct"][i]
        if not np.isfinite(a) or a < arm.min_atr_pct:
            return False
    if arm.max_dist52 is not None:
        d = feat["dist52"][i]
        if not np.isfinite(d) or d > arm.max_dist52:
            return False
    if arm.min_dist52 is not None:
        d = feat["dist52"][i]
        if not np.isfinite(d) or d < arm.min_dist52:
            return False
    if arm.require_above_sma50:
        s = feat["sma50"][i]
        c = feat["close"][i]
        if not (np.isfinite(s) and np.isfinite(c) and s > 0 and c >= s):
            return False
    if arm.min_rel_vol > 0:
        v = feat["rel_vol"][i]
        if not np.isfinite(v) or v < arm.min_rel_vol:
            return False
    if arm.min_rsi_drop > 0:
        p = feat["prior_ob"][i]
        if not np.isfinite(p) or (p - rsi) < arm.min_rsi_drop:
            return False
    if arm.max_zscore is not None:
        z = feat["z"][i]
        if not np.isfinite(z) or z > arm.max_zscore:
            return False
    if arm.min_spy_1y is not None:
        if spy_1y is None or not np.isfinite(spy_1y) or spy_1y < arm.min_spy_1y:
            return False
    return True


def backtest_arm(df: pd.DataFrame, feat: dict[str, np.ndarray], arm: Arm) -> list[dict]:
    n = len(df)
    if n < 20:
        return []
    close = feat["close"]
    open_ = feat["open"]
    rsi = feat["rsi"]
    dates = df["Date"]
    prev = np.roll(rsi, 1)
    prev[0] = np.nan
    buy_base = (prev >= RSI_OB) & (rsi > RSI_OS) & (rsi < RSI_OB)
    trades: list[dict] = []
    in_pos = False
    pending_entry = False
    pending_exit = False
    pending_exit_type = "OVERBOUGHT"
    entry_px = float("nan")
    entry_i = -1
    signal_i = -1

    def _close(exit_i: int, exit_px: float, exit_type: str) -> None:
        nonlocal entry_px, entry_i, signal_i
        if entry_i < 0 or not np.isfinite(entry_px) or entry_px <= 0:
            return
        if not np.isfinite(exit_px) or exit_px <= 0:
            return
        pnl = (exit_px / entry_px - 1.0) * 100.0
        days = int((dates.iloc[exit_i] - dates.iloc[entry_i]).days)
        trades.append(
            {
                "opened": dates.iloc[entry_i],
                "closed": dates.iloc[exit_i],
                "pnl": float(pnl),
                "pnl_d": float(NOTIONAL * pnl / 100.0),
                "days": max(days, 0),
                "exit_type": exit_type,
            }
        )
        entry_px = float("nan")
        entry_i = -1
        signal_i = -1

    for i in range(n):
        if pending_entry and not in_pos:
            px = float(open_[i])
            if px > 0 and np.isfinite(px):
                in_pos = True
                entry_px = px
                entry_i = i
            pending_entry = False
        elif pending_exit and in_pos:
            px = float(open_[i])
            if px > 0 and np.isfinite(px):
                _close(i, px, pending_exit_type)
                in_pos = False
            pending_exit = False

        if i == n - 1:
            continue
        if in_pos:
            sell = np.isfinite(rsi[i]) and rsi[i] >= arm.exit_rsi
            timed = False
            if arm.time_stop_days > 0 and entry_i >= 0:
                held = int((dates.iloc[i] - dates.iloc[entry_i]).days)
                timed = held >= arm.time_stop_days
            if sell:
                pending_exit = True
                pending_exit_type = "OVERBOUGHT"
            elif timed:
                pending_exit = True
                pending_exit_type = "TIME"
        elif bool(buy_base[i]) and gate_ok(arm, i, feat, None):
            pending_entry = True
            signal_i = i

    if in_pos and entry_i >= 0:
        last = float(close[-1])
        if last > 0 and np.isfinite(last):
            _close(n - 1, last, "EOD")
    return trades


def book_metrics(trades: list[dict], label: str) -> dict:
    n = len(trades)
    empty = {
        "slice": label, "n_trades": 0, "n_wins": 0, "n_losses": 0,
        "win_pct": float("nan"), "avg_pnl_pct": float("nan"),
        "avg_pnl_pct_wo_max": float("nan"), "expectancy_pct": float("nan"),
        "avg_win_pct": float("nan"), "avg_loss_pct": float("nan"),
        "profit_factor": float("nan"), "ann_ror": float("nan"),
        "max_dd": float("nan"), "calmar": float("nan"), "sharpe": float("nan"),
        "avg_days": float("nan"), "median_days": float("nan"),
        "p90_days": float("nan"), "capital_days": 0,
        "profit_per_cap_day": float("nan"), "exit_ob": 0, "exit_time": 0, "exit_eod": 0,
    }
    if n <= 0:
        return empty
    pnls = np.array([float(t["pnl"]) for t in trades], dtype=float)
    days = np.array([float(t["days"]) for t in trades], dtype=float)
    dolls = np.array([float(t["pnl_d"]) for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    wo = pnls.copy()
    if len(wo) >= 2:
        wo = np.delete(wo, int(np.argmax(wo)))
    sum_w = float(dolls[dolls > 0].sum())
    sum_l = float(abs(dolls[dolls < 0].sum()))
    pf = sum_w / sum_l if sum_l > 0 else (sum_w if sum_w > 0 else float("nan"))
    avg_days = float(np.mean(days))
    overlay = overlay_ann_ror_max_dd(
        trades, cash=NOTIONAL, initial_account=ACCOUNT,
        pnl_d_key="pnl_d", days_key="days", closed_key="closed",
        opened_key="opened", pnl_pct_key="pnl",
    )
    ann = overlay.get("ann_ror")
    if ann is None or not np.isfinite(float(ann)):
        ann = ann_ror_from_closed(
            total_pnl=float(dolls.sum()), n_trades=n,
            avg_days_held=avg_days, brt_cash=NOTIONAL,
        ) or float("nan")
    max_dd = overlay.get("max_dd")
    if max_dd is None:
        max_dd = float("nan")
    calmar = overlay.get("calmar")
    if calmar is None or not np.isfinite(float(calmar or 0)):
        if np.isfinite(float(ann)) and np.isfinite(float(max_dd)) and abs(float(max_dd)) > 1e-12:
            calmar = float(ann) / abs(float(max_dd))
        else:
            calmar = float("nan")
    cap = int(np.nansum(days))
    return {
        "slice": label, "n_trades": n,
        "n_wins": int(len(wins)), "n_losses": int(len(losses)),
        "win_pct": 100.0 * len(wins) / n,
        "avg_pnl_pct": float(np.mean(pnls)),
        "avg_pnl_pct_wo_max": float(np.mean(wo)) if len(wo) else float("nan"),
        "expectancy_pct": float(np.mean(pnls)),
        "avg_win_pct": float(np.mean(wins)) if len(wins) else float("nan"),
        "avg_loss_pct": float(np.mean(losses)) if len(losses) else float("nan"),
        "profit_factor": float(pf),
        "ann_ror": float(ann),
        "max_dd": float(max_dd),
        "calmar": float(calmar),
        "sharpe": float(overlay.get("sharpe") or float("nan")),
        "avg_days": avg_days,
        "median_days": float(np.median(days)),
        "p90_days": float(np.percentile(days, 90)),
        "capital_days": cap,
        "profit_per_cap_day": (float(dolls.sum()) / cap) if cap > 0 else float("nan"),
        "exit_ob": int(sum(1 for t in trades if t["exit_type"] == "OVERBOUGHT")),
        "exit_time": int(sum(1 for t in trades if t["exit_type"] == "TIME")),
        "exit_eod": int(sum(1 for t in trades if t["exit_type"] == "EOD")),
    }


def filter_slice(trades: list[dict], which: str) -> list[dict]:
    if which == "FULL":
        return list(trades)
    if which == "IS":
        return [t for t in trades if pd.Timestamp(t["opened"]) < IS_CUTOFF]
    return [t for t in trades if pd.Timestamp(t["opened"]) >= IS_CUTOFF]


def fmt_pct_pts(x: float, d: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{d}f}%"


def fmt_num(x: float, d: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{d}f}"


def fmt_int(x: object) -> str:
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "—"


def load_corr(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path)


def pick_extra_arms(corr_is: pd.DataFrame) -> list[Arm]:
    """Add at most a few one-knob arms from IS |R_PNL_PCT| (trigger-time only)."""
    skip = {
        "PNL_PCT", "ANN_ROR_PCT", "POST_ENTRY_GAIN_HIT", "MAX_PRICE",
        "PNL_DOLLARS", "DAYS_HELD", "RSI14_AT_EXIT",
    }
    useful: list[tuple[str, float]] = []
    if corr_is is None or corr_is.empty:
        return []
    for _, r in corr_is.iterrows():
        var = str(r.get("Variable") or "")
        if not var or var.upper() in skip:
            continue
        if var.upper().startswith("RSI14_AT_EXIT"):
            continue
        try:
            rp = float(r.get("R_PNL_PCT"))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(rp) or abs(rp) < 0.03:
            continue
        useful.append((var, rp))
    useful.sort(key=lambda x: abs(x[1]), reverse=True)
    extra: list[Arm] = []
    seen = set()
    for var, rp in useful:
        vu = var.upper()
        if vu in seen:
            continue
        if "ATR_PCT_AT_TRIGGER" in vu and rp > 0:
            extra.append(Arm("ENTRY_min_atr4", "min_atr_pct", f"IS corr {var} R_PNL={rp:+.3f}: keep livelier names (ATR%≥4).", min_atr_pct=4.0))
            seen.add(vu)
        elif "DIST_TO_52W" in vu and rp < 0:
            extra.append(Arm("ENTRY_max_dist52_20", "max_dist52", f"IS corr {var} R_PNL={rp:+.3f}: prefer names closer to the 52-week high (dist≤20%).", max_dist52=20.0))
            seen.add(vu)
        elif "DIST_TO_52W" in vu and rp > 0:
            extra.append(Arm("ENTRY_min_dist52_15", "min_dist52", f"IS corr {var} R_PNL={rp:+.3f}: prefer more washed-out names (dist≥15%).", min_dist52=15.0))
            seen.add(vu)
        elif "CLOSE_VS_SMA50" in vu and rp > 0:
            extra.append(Arm("ENTRY_above_sma50", "require_above_sma50", f"IS corr {var} R_PNL={rp:+.3f}: only buy if trigger close ≥ SMA50.", require_above_sma50=True))
            seen.add(vu)
        elif "REL_VOL_ON_TRIGGER" in vu and rp > 0:
            extra.append(Arm("ENTRY_min_relvol_1", "min_rel_vol", f"IS corr {var} R_PNL={rp:+.3f}: require trigger rel vol ≥ 1.0.", min_rel_vol=1.0))
            seen.add(vu)
        elif "RSI14_DROP_FROM_OB" in vu and rp > 0:
            extra.append(Arm("ENTRY_min_rsi_drop_10", "min_rsi_drop", f"IS corr {var} R_PNL={rp:+.3f}: require ≥10 RSI points of cooling from the prior OB print.", min_rsi_drop=10.0))
            seen.add(vu)
        elif "Z_SCORE_AT_TRIGGER" in vu and rp < 0:
            extra.append(Arm("ENTRY_max_z_1", "max_zscore", f"IS corr {var} R_PNL={rp:+.3f}: skip stretched 20-bar z-score > 1.", max_zscore=1.0))
            seen.add(vu)
        elif "SPY_COMPARE_1Y" in vu and rp > 0:
            extra.append(Arm("ENTRY_min_spy1y_0", "min_spy_1y", f"IS corr {var} R_PNL={rp:+.3f}: require 1y relative strength vs SPY ≥ 0.", min_spy_1y=0.0))
            seen.add(vu)
        elif "RSI14_AT_TRIGGER" in vu and rp < 0:
            extra.append(Arm("ENTRY_max_rsi_60", "max_rsi_trigger", f"IS corr {var} R_PNL={rp:+.3f}: require a deeper cool-off (trigger RSI < 60).", max_rsi_trigger=60.0))
            seen.add(vu)
        if len(extra) >= 4:
            break
    return extra


def default_tune_arms() -> list[Arm]:
    return [
        Arm("CONTROL", "none", "Frozen: buy Neutral-after-OB, sell OB≥70, next open, no extra gates."),
        Arm("EXIT_rsi65", "exit_rsi", "Sell sooner when RSI returns to 65 (less giveback).", exit_rsi=65.0),
        Arm("EXIT_rsi75", "exit_rsi", "Sell later when RSI reaches 75 (let strength run).", exit_rsi=75.0),
        Arm("TIME_stop_20d", "time_stop_days", "Post-run turnover: flatten at 20 calendar days if still not OB.", time_stop_days=20),
        Arm("TIME_stop_40d", "time_stop_days", "Softer time stop at 40 calendar days.", time_stop_days=40),
        Arm("ENTRY_max_rsi_60", "max_rsi_trigger", "Tune: only buy if Neutral cools below 60 (not a 69 print).", max_rsi_trigger=60.0),
    ]


def run_all(arms: list[Arm]) -> dict[str, list[dict]]:
    syms = list_universe()
    by_arm: dict[str, list[dict]] = {a.name: [] for a in arms}
    print(f"Replay {len(syms)} symbols × {len(arms)} arms", flush=True)
    for i, sym in enumerate(syms, 1):
        df = load_ohlcv(sym)
        if df is None or len(df) < 20:
            continue
        feat = features(df)
        for a in arms:
            for t in backtest_arm(df, feat, a):
                t["symbol"] = sym
                by_arm[a.name].append(t)
        if i % 100 == 0 or i == len(syms):
            n0 = len(by_arm[arms[0].name])
            print(f"  {i}/{len(syms)}  control_trades={n0}", flush=True)
    return by_arm


def verdict_row(ctrl: dict, cand: dict) -> str:
    def ok(x: object) -> bool:
        try:
            return bool(np.isfinite(float(x)))
        except (TypeError, ValueError):
            return False
    if not ok(cand.get("avg_pnl_pct")):
        return "INCONCLUSIVE"
    d_avg = float(cand["avg_pnl_pct"]) - float(ctrl["avg_pnl_pct"])
    d_wr = float(cand["win_pct"]) - float(ctrl["win_pct"])
    d_dd = float(cand["max_dd"]) - float(ctrl["max_dd"]) if ok(cand.get("max_dd")) and ok(ctrl.get("max_dd")) else 0.0
    n_ratio = cand["n_trades"] / max(ctrl["n_trades"], 1)
    if d_avg > 0.15 and d_dd <= 1.0 and n_ratio >= 0.4:
        return "LEAN KEEP (research)"
    if d_avg < -0.15 or (d_wr < -3 and d_avg <= 0):
        return "DISMISS"
    return "HOLD"


def write_html(
    path: Path,
    arms: list[Arm],
    books: dict[str, list[dict]],
    corr_full: pd.DataFrame,
    corr_is: pd.DataFrame,
    extra_note: str,
) -> None:
    ctrl_full = next(b for b in books["CONTROL"] if b["slice"] == "FULL")

    def book_table() -> str:
        headers = [
            ("Arm", "text"), ("Knob", "text"), ("Slice", "text"),
            ("N", "num"), ("Win %", "num"), ("Avg PnL %", "num"),
            ("AVG_PNL_PCT_WO_MAX", "num"), ("Expectancy %", "num"),
            ("Avg win %", "num"), ("Avg loss %", "num"), ("PF", "num"),
            ("Ann ROR %", "num"), ("Max DD %", "num"), ("Calmar", "num"),
            ("Sharpe", "num"), ("Avg days", "num"), ("Median days", "num"),
            ("P90 days", "num"), ("Capital days", "num"),
            ("Profit / cap day", "num"), ("Exit OB", "num"),
            ("Exit TIME", "num"), ("Exit EOD", "num"),
            ("Δ Avg PnL % vs ctrl", "num"), ("Δ Max DD vs ctrl", "num"),
            ("IS/OOS note", "text"),
        ]
        th = "".join(sortable_th(a, b) for a, b in headers)
        body = []
        for a in arms:
            for b in books[a.name]:
                cslice = next(x for x in books["CONTROL"] if x["slice"] == b["slice"])
                d_avg = b["avg_pnl_pct"] - cslice["avg_pnl_pct"] if a.name != "CONTROL" else 0.0
                d_dd = b["max_dd"] - cslice["max_dd"] if a.name != "CONTROL" else 0.0
                note = ""
                if b["slice"] == "FULL" and a.name != "CONTROL":
                    note = verdict_row(cslice, b)
                body.append(
                    "<tr>"
                    f"<td>{html_mod.escape(a.name)}</td>"
                    f"<td>{html_mod.escape(a.knob)}</td>"
                    f"<td>{b['slice']}</td>"
                    f"<td>{fmt_int(b['n_trades'])}</td>"
                    f"<td>{fmt_pct_pts(b['win_pct'])}</td>"
                    f"<td>{fmt_pct_pts(b['avg_pnl_pct'])}</td>"
                    f"<td>{fmt_pct_pts(b['avg_pnl_pct_wo_max'])}</td>"
                    f"<td>{fmt_pct_pts(b['expectancy_pct'])}</td>"
                    f"<td>{fmt_pct_pts(b['avg_win_pct'])}</td>"
                    f"<td>{fmt_pct_pts(b['avg_loss_pct'])}</td>"
                    f"<td>{fmt_num(b['profit_factor'])}</td>"
                    f"<td>{fmt_pct_pts(b['ann_ror'])}</td>"
                    f"<td>{fmt_pct_pts(b['max_dd'])}</td>"
                    f"<td>{fmt_num(b['calmar'])}</td>"
                    f"<td>{fmt_num(b['sharpe'])}</td>"
                    f"<td>{fmt_num(b['avg_days'], 1)}</td>"
                    f"<td>{fmt_num(b['median_days'], 1)}</td>"
                    f"<td>{fmt_num(b['p90_days'], 1)}</td>"
                    f"<td>{fmt_int(b['capital_days'])}</td>"
                    f"<td>{format_money(b['profit_per_cap_day'])}</td>"
                    f"<td>{fmt_int(b['exit_ob'])}</td>"
                    f"<td>{fmt_int(b['exit_time'])}</td>"
                    f"<td>{fmt_int(b['exit_eod'])}</td>"
                    f"<td>{fmt_pct_pts(d_avg)}</td>"
                    f"<td>{fmt_pct_pts(d_dd)}</td>"
                    f"<td>{html_mod.escape(note)}</td>"
                    "</tr>"
                )
        return (
            '<p class="meta">Click headers to sort. Total/Sheet PnL $ omitted. '
            "OOS is report-only. Judge quality (Avg PnL%, win%, Max DD, Calmar), not trade count.</p>"
            f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
        )

    def corr_table(df: pd.DataFrame, title: str) -> str:
        if df is None or df.empty:
            return f"<p class='meta'>{html_mod.escape(title)}: missing.</p>"
        show = df.head(25)
        headers = [("Variable", "text"), ("R_PNL_PCT", "num"), ("R_ANN_ROR_PCT", "num"),
                   ("R_POST_ENTRY_GAIN_HIT", "num"), ("R_Total", "num")]
        th = "".join(sortable_th(a, b) for a, b in headers)
        body = []
        for _, r in show.iterrows():
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(str(r.get('Variable', '')))}</td>"
                f"<td>{fmt_num(float(r['R_PNL_PCT'])) if pd.notna(r.get('R_PNL_PCT')) else '—'}</td>"
                f"<td>{fmt_num(float(r['R_ANN_ROR_PCT'])) if pd.notna(r.get('R_ANN_ROR_PCT')) else '—'}</td>"
                f"<td>{fmt_num(float(r['R_POST_ENTRY_GAIN_HIT'])) if pd.notna(r.get('R_POST_ENTRY_GAIN_HIT')) else '—'}</td>"
                f"<td>{fmt_num(float(r['R_Total'])) if pd.notna(r.get('R_Total')) else '—'}</td>"
                "</tr>"
            )
        return (
            f"<h3>{html_mod.escape(title)}</h3>"
            "<p class='meta'>Top 25 by |R_Total|. Trigger-time fields only should drive gates. "
            "Do not gate on realized outcomes. Click headers to sort.</p>"
            f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
        )

    hyps = "".join(
        f"<li><code>{html_mod.escape(a.name)}</code> — <strong>{html_mod.escape(a.knob)}</strong>: "
        f"{html_mod.escape(a.hypothesis)}</li>"
        for a in arms
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP}</title><style>{SORT_CSS}</style></head>
<body>
<h1>RSI Neutral-after-OB — full-universe Closed, post-run, one-knob A/Bs</h1>
<p class="badge">Research only · not gold · not DailyRun · OOS report-only</p>
<p class="meta">Stamp <code>{STAMP}</code> · {date.today().isoformat()} · click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>We saved the <strong>full-universe closed-trade file</strong> (every completed buy/sell from the
“cool off from too-hot, then sell when too-hot again” idea). Then we ran the usual
<strong>after-the-run checkup</strong> (how trades behaved, what to try next) and a
<strong>correlation sheet</strong> (which numbers known on the signal day move with profit).
Finally we ran <strong>one-change tests</strong>: same system, only one setting different —
either how we sell, a time limit, or a filter suggested by the correlation file.
We judged on trade quality, not how many trades we kept. The later years (2024+) are
shown only as a check; we did not retune to make those look better.</p>
</div>
<div class="insight">
<p><strong>Control FULL</strong> N={fmt_int(ctrl_full['n_trades'])}
Win%={fmt_pct_pts(ctrl_full['win_pct'])}
Avg PnL%={fmt_pct_pts(ctrl_full['avg_pnl_pct'])}
Max DD%={fmt_pct_pts(ctrl_full['max_dd'])}.</p>
<p class="meta">{html_mod.escape(extra_note)}</p>
</div>
<h2>1. Arms (one knob each)</h2>
<ul class="meta">{hyps}</ul>
<h2>2. Book compare (canonical overlay)</h2>
{book_table()}
<h2>3. Correlation (why these extra gates)</h2>
{corr_table(corr_is, "IS only (entry &lt; 2024-01-01) — used to pick extra arms")}
{corr_table(corr_full, "Full-sample correlation (inspection; not for picking)")}
<p class="meta">Closed file: <code>drive/RSIN_LatestRun_Closed.csv</code> and
<code>drive/paul_experiments/rsi_ob_to_neutral_exit_ob_20260910/RSIN_Closed_20260910.csv</code>.
Post-run HTML lives in that same stamp folder.</p>
</body>
{SORT_JS}
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_baseline(path: Path, arms: list[Arm]) -> None:
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "Research only. Not gold. Not DailyRun. OOS report-only.",
        "",
        "## Original request",
        "",
        ORIGINAL_REQUEST,
        "",
        "## Control freeze",
        "",
        "- Buy: prior RSI≥70 and today Neutral (30<RSI<70); next-open fill",
        "- Sell: RSI ≥ 70; next-open fill",
        "- Universe: all `data/newdata/data/*.csv`",
        "- Costs 0 · $10k notional · $500k overlay",
        "- IS: entry < 2024-01-01; OOS ≥ 2024-01-01 (report-only)",
        "",
        "## Arms (one knob vs control)",
        "",
    ]
    for a in arms:
        lines.append(f"- `{a.name}` knob=`{a.knob}` — {a.hypothesis}")
    lines += [
        "",
        "## Selection honesty",
        "",
        "Tune exits (RSI 65/75, time stop) were pre-declared. Extra entry gates were chosen from ",
        "**IS correlation only** (`RSIN_Correlation_IS_20260910.csv`). Full-sample correlation is shown ",
        "but was not used to pick arms. No combinatorial grid. No OOS retune.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    corr_full = load_corr(SRC_STAMP / "RSIN_Correlation_20260910.csv")
    corr_is = load_corr(SRC_STAMP / "RSIN_Correlation_IS_20260910.csv")
    arms = default_tune_arms()
    extras = pick_extra_arms(corr_is)
    have = {a.name for a in arms}
    for a in extras:
        if a.name not in have:
            arms.append(a)
            have.add(a.name)
    extra_note = (
        f"Added {len(extras)} correlation-driven entry arm(s) from IS |R_PNL|>=0.03: "
        + (", ".join(a.name for a in extras) if extras else "none passed the floor.")
    )
    print(extra_note, flush=True)
    by_arm = run_all(arms)
    books: dict[str, list[dict]] = {}
    rows = []
    for a in arms:
        books[a.name] = [book_metrics(filter_slice(by_arm[a.name], s), s) for s in ("FULL", "IS", "OOS")]
        for b in books[a.name]:
            rows.append({"arm": a.name, "knob": a.knob, **b})
            if b["slice"] == "FULL":
                print(
                    f"  {a.name}: N={b['n_trades']} WR={b['win_pct']:.2f} "
                    f"Avg%={b['avg_pnl_pct']:.3f} DD={b['max_dd']:.2f}",
                    flush=True,
                )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT_DIR / "compare_book_metrics.csv", index=False)
    for a in arms:
        recs = []
        for t in by_arm[a.name]:
            recs.append(
                {
                    "SYMBOL": t["symbol"],
                    "DATE_OPENED": pd.Timestamp(t["opened"]).strftime("%Y-%m-%d"),
                    "DATE_CLOSED": pd.Timestamp(t["closed"]).strftime("%Y-%m-%d"),
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                    "DAYS_HELD": t["days"],
                    "EXIT_TYPE": t["exit_type"],
                }
            )
        pd.DataFrame(recs).to_csv(OUT_DIR / f"closed_{a.name}.csv", index=False)
    write_baseline(OUT_DIR / "BASELINE.md", arms)
    html_path = OUT_DIR / "compare.html"
    write_html(html_path, arms, books, corr_full, corr_is, extra_note)
    print(f"HTML {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
