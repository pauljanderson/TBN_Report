#!/usr/bin/env python3
"""One-knob A/Bs under CONTROL = Neutral-after-OB + exit RSI≥70 + ATR%≥5 + ts20 + max_rsi_trigger=60.

Control preference-adopts ENTRY_max_rsi_60 (HOLD under rsi70+atr5+ts20 parent; N cut hard)
into the freeze — same preference-adopt pattern as prior stamps. Research only.

Usage:
  python tools/rsi_ob_neutral_rsi70_atr5_ts20_maxrsi60_ab_20260911.py
"""
from __future__ import annotations

import html as html_mod
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

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
STAMP = "rsi_ob_neutral_rsi70_atr5_ts20_maxrsi60_20260911"
OUT_DIR = ROOT / "drive" / "paul_experiments" / STAMP
PRIOR_FREEZE = "rsi_ob_neutral_rsi70_atr5_ts20_20260911"
PAUL_TWENTY = ROOT / "drive" / "universes" / "PaulTwenty_universe.csv"
IS_CUTOFF = pd.Timestamp("2024-01-01")
RSI_OB = 70.0
RSI_OS = 30.0
CTRL_EXIT_RSI = 70.0
CTRL_MIN_ATR = 5.0
CTRL_TIME_STOP = 20
CTRL_MAX_RSI = 60.0  # preference-adopted entry gate (was HOLD arm)
NOTIONAL = 10_000.0
ACCOUNT = DEFAULT_INITIAL_ACCOUNT
ORIGINAL_REQUEST = (
    "lets adopt this ENTRY_max_rsi_60 and please five me a summary file of IS "
    "so i can pick a univwrse. feel free to make a universe recomendation"
)

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; touch-action: manipulation; -webkit-tap-highlight-color: rgba(0,0,0,.08); }
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
.caveat { color: #9a3412; font-size: .9rem; max-width: 78rem; }
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
  function bindSortHeader(table, th, col) {
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


@dataclass
class Arm:
    name: str
    knob: str
    hypothesis: str
    exit_rsi: float = CTRL_EXIT_RSI
    time_stop_days: int = CTRL_TIME_STOP
    min_atr_pct: float = CTRL_MIN_ATR
    max_rsi_trigger: float = CTRL_MAX_RSI  # control freezes trigger RSI < 60
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
    exit_signal_rsi = float("nan")

    def _close(exit_i: int, exit_px: float, exit_type: str) -> None:
        nonlocal entry_px, entry_i, signal_i, exit_signal_rsi
        if entry_i < 0 or not np.isfinite(entry_px) or entry_px <= 0:
            return
        if not np.isfinite(exit_px) or exit_px <= 0:
            return
        pnl = (exit_px / entry_px - 1.0) * 100.0
        days = int((dates.iloc[exit_i] - dates.iloc[entry_i]).days)
        sig_rsi = float(rsi[signal_i]) if signal_i >= 0 and np.isfinite(rsi[signal_i]) else float("nan")
        trades.append(
            {
                "opened": dates.iloc[entry_i],
                "closed": dates.iloc[exit_i],
                "signal_date": dates.iloc[signal_i] if signal_i >= 0 else dates.iloc[entry_i],
                "entry": float(entry_px),
                "exit": float(exit_px),
                "pnl": float(pnl),
                "pnl_d": float(NOTIONAL * pnl / 100.0),
                "days": max(days, 0),
                "exit_type": exit_type,
                "rsi_trigger": sig_rsi,
                "rsi_exit": float(exit_signal_rsi) if np.isfinite(exit_signal_rsi) else float("nan"),
            }
        )
        entry_px = float("nan")
        entry_i = -1
        signal_i = -1
        exit_signal_rsi = float("nan")

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
                exit_signal_rsi = float(rsi[i])
            elif timed:
                pending_exit = True
                pending_exit_type = "TIME"
                exit_signal_rsi = float(rsi[i]) if np.isfinite(rsi[i]) else float("nan")
        elif bool(buy_base[i]) and gate_ok(arm, i, feat, None):
            pending_entry = True
            signal_i = i

    if in_pos and entry_i >= 0:
        last = float(close[-1])
        if last > 0 and np.isfinite(last):
            exit_signal_rsi = float(rsi[-1]) if np.isfinite(rsi[-1]) else float("nan")
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


def ymd(x: object) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def load_corr(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path)


def fixed_arms() -> list[Arm]:
    """Pre-declared one-knob arms vs maxrsi60+rsi70+atr5+ts20 control (no corr pick)."""
    return [
        Arm(
            "CONTROL",
            "none",
            "Frozen: Neutral-after-OB buy with trigger RSI < 60, min ATR%≥5, sell RSI≥70, "
            "time stop 20 calendar days, next open. Preference-adopt of ENTRY_max_rsi_60.",
        ),
        Arm(
            "ENTRY_no_max_rsi",
            "max_rsi_trigger",
            "Ablate the new gate: restore max_rsi_trigger=70 (Neutral band top) — proves the adopt.",
            max_rsi_trigger=RSI_OB,
        ),
        Arm(
            "ENTRY_max_rsi_55",
            "max_rsi_trigger",
            "Nearby notch: require deeper cool-off (trigger RSI < 55).",
            max_rsi_trigger=55.0,
        ),
        Arm(
            "ENTRY_max_rsi_65",
            "max_rsi_trigger",
            "Nearby notch: slightly looser cool-off (trigger RSI < 65).",
            max_rsi_trigger=65.0,
        ),
        Arm(
            "EXIT_rsi75",
            "exit_rsi",
            "One notch higher exit: sell at RSI≥75 (still maxrsi60 + ATR%≥5 + ts20).",
            exit_rsi=75.0,
        ),
        Arm(
            "EXIT_rsi80",
            "exit_rsi",
            "Ablate exit upward: sell when RSI≥80 (still maxrsi60 + ATR%≥5 + ts20).",
            exit_rsi=80.0,
        ),
        Arm(
            "ENTRY_min_atr4",
            "min_atr_pct",
            "Ablate atr5 downward: require ATR%≥4 at trigger (still maxrsi60 + exit 70 + ts20).",
            min_atr_pct=4.0,
        ),
        Arm(
            "ENTRY_min_atr6",
            "min_atr_pct",
            "Nudge atr5 upward: require ATR%≥6 at trigger (still maxrsi60 + exit 70 + ts20).",
            min_atr_pct=6.0,
        ),
        Arm(
            "ENTRY_no_atr_gate",
            "min_atr_pct",
            "Ablate atr5 entirely: no ATR% gate (still maxrsi60 + exit 70 + ts20).",
            min_atr_pct=0.0,
        ),
        Arm(
            "TIME_stop_none",
            "time_stop_days",
            "Ablate ts20: no time stop (still maxrsi60 + exit 70 + atr5).",
            time_stop_days=0,
        ),
        Arm(
            "TIME_stop_40d",
            "time_stop_days",
            "Softer time stop at 40 calendar days (still maxrsi60 + exit 70 + atr5).",
            time_stop_days=40,
        ),
    ]


def pick_extra_arms(corr_is: pd.DataFrame) -> list[Arm]:
    """At most 3 one-knob arms from NEW-control IS |R_PNL_PCT| (trigger-time only).

    Skip ATR% gates (already frozen at 5), time-stop / days-held, and RSI14_AT_TRIGGER
    (already frozen at max_rsi_trigger=60). Cap extras to avoid combinatorial explode.
    """
    skip = {
        "PNL_PCT", "ANN_ROR_PCT", "POST_ENTRY_GAIN_HIT", "MAX_PRICE",
        "PNL_DOLLARS", "DAYS_HELD", "RSI14_AT_EXIT", "RSI14_AT_TRIGGER",
    }
    useful: list[tuple[str, float]] = []
    if corr_is is None or corr_is.empty:
        return []
    for _, r in corr_is.iterrows():
        var = str(r.get("Variable") or "")
        if not var or var.upper() in skip:
            continue
        if var.upper().startswith("RSI14_AT_EXIT") or var.upper().startswith("RSI14_AT_TRIGGER"):
            continue
        # ATR already frozen in control — do not re-add atr arms
        if "ATR_PCT_AT_TRIGGER" in var.upper() or "ATR_14_AT_TRIGGER" in var.upper():
            continue
        # Time stop already frozen — skip hold-duration / time-stop confusers
        if "TIME_STOP" in var.upper() or "DAYS_HELD" in var.upper():
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
        if "DIST_TO_52W" in vu and rp < 0:
            extra.append(Arm(
                "ENTRY_max_dist52_20", "max_dist52",
                f"IS corr (new control) {var} R_PNL={rp:+.3f}: prefer closer to 52w high (dist≤20%).",
                max_dist52=20.0,
            ))
            seen.add(vu)
        elif "DIST_TO_52W" in vu and rp > 0:
            extra.append(Arm(
                "ENTRY_min_dist52_15", "min_dist52",
                f"IS corr (new control) {var} R_PNL={rp:+.3f}: prefer more washed-out (dist≥15%).",
                min_dist52=15.0,
            ))
            seen.add(vu)
        elif "CLOSE_VS_SMA50" in vu and rp > 0:
            extra.append(Arm(
                "ENTRY_above_sma50", "require_above_sma50",
                f"IS corr (new control) {var} R_PNL={rp:+.3f}: only buy if trigger close ≥ SMA50.",
                require_above_sma50=True,
            ))
            seen.add(vu)
        elif "REL_VOL_ON_TRIGGER" in vu and rp > 0:
            extra.append(Arm(
                "ENTRY_min_relvol_1", "min_rel_vol",
                f"IS corr (new control) {var} R_PNL={rp:+.3f}: require trigger rel vol ≥ 1.0.",
                min_rel_vol=1.0,
            ))
            seen.add(vu)
        elif "RSI14_DROP_FROM_OB" in vu and rp > 0:
            extra.append(Arm(
                "ENTRY_min_rsi_drop_10", "min_rsi_drop",
                f"IS corr (new control) {var} R_PNL={rp:+.3f}: require ≥10 RSI pts cool from prior OB.",
                min_rsi_drop=10.0,
            ))
            seen.add(vu)
        elif "Z_SCORE_AT_TRIGGER" in vu and rp < 0:
            extra.append(Arm(
                "ENTRY_max_z_1", "max_zscore",
                f"IS corr (new control) {var} R_PNL={rp:+.3f}: skip stretched 20-bar z > 1.",
                max_zscore=1.0,
            ))
            seen.add(vu)
        elif "SPY_COMPARE_1Y" in vu and rp > 0:
            extra.append(Arm(
                "ENTRY_min_spy1y_0", "min_spy_1y",
                f"IS corr (new control) {var} R_PNL={rp:+.3f}: require 1y RS vs SPY ≥ 0.",
                min_spy_1y=0.0,
            ))
            seen.add(vu)
        if len(extra) >= 3:
            break
    return extra


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
            print(f"  {i}/{len(syms)}  first_arm_trades={n0} ({arms[0].name})", flush=True)
    return by_arm


def write_closed_csv(path: Path, trades: list[dict]) -> None:
    rows = []
    for t in trades:
        rows.append(
            {
                "SYMBOL": t["symbol"],
                "DATE_OPENED": ymd(t["opened"]),
                "DATE_CLOSED": ymd(t["closed"]),
                "SIGNAL_DATE": ymd(t.get("signal_date", t["opened"])),
                "ENTRY_PRICE": f"{float(t['entry']):.4f}",
                "EXIT_PRICE": f"{float(t['exit']):.4f}",
                "PNL_PCT": f"{t['pnl']:.4f}",
                "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                "DAYS_HELD": t["days"],
                "EXIT_TYPE": t["exit_type"],
                "RSI14_AT_TRIGGER": (
                    f"{t['rsi_trigger']:.2f}" if np.isfinite(t.get("rsi_trigger", float("nan"))) else ""
                ),
                "RSI14_AT_EXIT": (
                    f"{t['rsi_exit']:.2f}" if np.isfinite(t.get("rsi_exit", float("nan"))) else ""
                ),
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


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
    ctrl_is = next(b for b in books["CONTROL"] if b["slice"] == "IS")
    ctrl_oos = next(b for b in books["CONTROL"] if b["slice"] == "OOS")

    def book_table_for_slice(slice_name: str, title: str, blurb: str) -> str:
        headers = [
            ("Arm", "text"), ("Knob", "text"),
            ("N", "num"), ("Win %", "num"), ("Avg PnL %", "num"),
            ("AVG_PNL_PCT_WO_MAX", "num"), ("Expectancy %", "num"),
            ("Avg win %", "num"), ("Avg loss %", "num"), ("PF", "num"),
            ("Ann ROR %", "num"), ("Max DD %", "num"), ("Calmar", "num"),
            ("Sharpe", "num"), ("Avg days", "num"), ("Median days", "num"),
            ("P90 days", "num"), ("Capital days", "num"),
            ("Profit / cap day", "num"), ("Exit OB", "num"),
            ("Exit TIME", "num"), ("Exit EOD", "num"),
            ("Δ Avg PnL % vs ctrl", "num"), ("Δ Max DD vs ctrl", "num"),
            ("Note", "text"),
        ]
        th = "".join(sortable_th(a, b) for a, b in headers)
        cslice = next(x for x in books["CONTROL"] if x["slice"] == slice_name)
        body = []
        for a in arms:
            b = next(x for x in books[a.name] if x["slice"] == slice_name)
            d_avg = b["avg_pnl_pct"] - cslice["avg_pnl_pct"] if a.name != "CONTROL" else 0.0
            d_dd = b["max_dd"] - cslice["max_dd"] if a.name != "CONTROL" else 0.0
            note = ""
            if a.name != "CONTROL":
                if slice_name == "FULL":
                    note = verdict_row(cslice, b)
                elif slice_name == "OOS":
                    note = "report-only"
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(a.name)}</td>"
                f"<td>{html_mod.escape(a.knob)}</td>"
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
            f"<h3>{html_mod.escape(title)}</h3>"
            f'<p class="meta">{html_mod.escape(blurb)} Click headers to sort.</p>'
            f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
        )

    def book_tables() -> str:
        intro = (
            '<p class="meta">Three tables — <strong>IS</strong>, <strong>OOS</strong>, '
            "<strong>FULL</strong>. Sheet PnL $ omitted. OOS is report-only (do not retune). "
            "Judge quality (Avg PnL%, win%, Max DD, Calmar), not trade count. "
            "FULL Note = KEEP/HOLD/DISMISS vs that slice’s control.</p>"
        )
        return intro + "".join(
            [
                book_table_for_slice(
                    "IS",
                    "IS (entry &lt; 2024-01-01)",
                    "In-sample book under the maxrsi60+rsi70+atr5+ts20 control.",
                ),
                book_table_for_slice(
                    "OOS",
                    "OOS (entry ≥ 2024-01-01) — report-only",
                    "Holdout check only; not used to pick or retune.",
                ),
                book_table_for_slice(
                    "FULL",
                    "FULL (all history)",
                    "Combined book; verdicts in the Note column.",
                ),
            ]
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
<h1>RSI Neutral-after-OB — CONTROL = max_rsi_trigger&lt;60 + exit RSI≥70 + ATR%≥5 + TIME_stop 20d</h1>
<p class="badge">Research only · not gold · not DailyRun · OOS report-only · preference adopt</p>
<p class="meta">Stamp <code>{STAMP}</code> · {date.today().isoformat()} · click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>Relative Strength Index (RSI) Neutral-after-Overbought (OB) buys when a name cools from
hot (RSI was ≥70) into the middle band, but only if the trigger RSI is still under 60
(a deeper cool-off), with Average True Range percent (ATR%) ≥5, sell at RSI≥70, and flatten
by day 20 if needed. Under the prior freeze <code>{PRIOR_FREEZE}</code>, the arm
<code>ENTRY_max_rsi_60</code> was <strong>HOLD</strong> (Avg% up, MaxDD down, but trade count
cut hard ~6948→948). You liked that arm and asked to freeze it into control and re-run.
That is a preference adoption — <em>not</em> a KEEP from metrics. This stamp re-scores
FULL/IS/OOS under the new freeze and runs one-change tests (ablate the max-RSI gate, nearby
55/65 notches, exit 75/80, atr4/6/none, time-stop none/40d). Later years (2024+) are a check
only; we did not retune. Also: per-stock summary + universe recommendation artifacts in this
folder. Research only — not gold, not wired to DailyRun.</p>
</div>
<div class="insight">
<p><strong>Control FULL</strong> N={fmt_int(ctrl_full['n_trades'])}
Win%={fmt_pct_pts(ctrl_full['win_pct'])}
Avg PnL%={fmt_pct_pts(ctrl_full['avg_pnl_pct'])}
Max DD%={fmt_pct_pts(ctrl_full['max_dd'])}.</p>
<p><strong>Control IS</strong> N={fmt_int(ctrl_is['n_trades'])}
Win%={fmt_pct_pts(ctrl_is['win_pct'])}
Avg%={fmt_pct_pts(ctrl_is['avg_pnl_pct'])}
MaxDD={fmt_pct_pts(ctrl_is['max_dd'])}
· <strong>OOS</strong> N={fmt_int(ctrl_oos['n_trades'])}
Win%={fmt_pct_pts(ctrl_oos['win_pct'])}
Avg%={fmt_pct_pts(ctrl_oos['avg_pnl_pct'])}
MaxDD={fmt_pct_pts(ctrl_oos['max_dd'])}.</p>
<p class="meta">{html_mod.escape(extra_note)}</p>
<p class="caveat"><strong>Selection honesty:</strong> Under <code>{PRIOR_FREEZE}</code>,
<code>ENTRY_max_rsi_60</code> was <strong>HOLD</strong> on FULL (quality up, N cut hard).
Paul preference-adopts it into control — same pattern as prior preference adoptions,
<em>not</em> a KEEP from metrics. We re-scored FULL/IS/OOS under the frozen
maxrsi60+rsi70+atr5+ts20 combo; OOS was not used to pick or retune.
Research only · not gold · not DailyRun.</p>
</div>
<h2>1. Arms (one knob each vs maxrsi60 control)</h2>
<ul class="meta">{hyps}</ul>
<h2>2. Book compare (canonical overlay)</h2>
{book_tables()}
<h2>3. Correlation on NEW control Closed</h2>
{corr_table(corr_is, "IS only (entry &lt; 2024-01-01) — used to pick extra arms")}
{corr_table(corr_full, "Full-sample correlation (inspection; not for picking)")}
<p class="meta">Control Closed: <code>{STAMP}/closed_CONTROL.csv</code> and
<code>RSIN_Closed_20260911.csv</code>. Post-run / STOCK_SUMMARY / UNIVERSE_RECOMMENDATION
in the same stamp folder.</p>
{SORT_JS}
</body>
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
        "## In plain English",
        "",
        "Relative Strength Index (RSI) Neutral-after-Overbought (OB) with a deeper cool-off",
        "gate (trigger RSI < 60), exit RSI≥70, Average True Range percent (ATR%) ≥5, and a",
        "20-day time stop. Under the prior freeze, ENTRY_max_rsi_60 was HOLD (Avg% up, DD",
        "down, N cut hard). Paul liked it and preference-adopts it into control — not a KEEP",
        "from metrics. Re-score one-change A/Bs; also per-stock summary + universe recommendation.",
        "",
        "## Control freeze",
        "",
        "- Buy: prior RSI≥70 and today Neutral (30<RSI<70); next-open fill",
        f"- **NEW entry gate: trigger RSI < {CTRL_MAX_RSI:g}** (`max_rsi_trigger={CTRL_MAX_RSI:g}`) — preference adopt of HOLD arm",
        f"- Entry gate: ATR% at trigger ≥ {CTRL_MIN_ATR:g}",
        f"- Sell: RSI ≥ {CTRL_EXIT_RSI:g}; next-open fill",
        f"- Time stop: flatten at {CTRL_TIME_STOP} calendar days if still not exit-RSI",
        "- Universe: all `data/newdata/data/*.csv`",
        "- Costs 0 · $10k notional · $500k overlay",
        "- IS: entry < 2024-01-01; OOS ≥ 2024-01-01 (report-only)",
        "",
        "## Provenance / selection honesty",
        "",
        f"Prior freeze: `{PRIOR_FREEZE}`. There, **ENTRY_max_rsi_60** was **HOLD** FULL ",
        "(Avg% up, MaxDD down, but N cut hard ~6948→948; OOS Avg%≈2.76 MaxDD≈3.90). ",
        "Paul preference-adopts it into this control — same pattern as prior preference ",
        "adoptions, **not** a KEEP from metrics. This stamp **re-scores** FULL/IS/OOS under ",
        "the frozen maxrsi60+rsi70+atr5+ts20 combo and runs new one-knob arms around it. ",
        "OOS is report-only — do not retune on OOS. Not gold. Not DailyRun.",
        "",
        "## Arms (one knob vs control)",
        "",
    ]
    for a in arms:
        lines.append(f"- `{a.name}` knob=`{a.knob}` — {a.hypothesis}")
    lines += [
        "",
        "## Extra entry gates",
        "",
        "Any correlation-driven extras were picked from **IS correlation on this stamp's ",
        "control Closed only** (`RSIN_Correlation_IS_20260911.csv`). Full-sample corr is ",
        "inspection-only. ATR%, time-stop / days-held, and RSI14_AT_TRIGGER skipped ",
        "(already frozen at max_rsi_trigger=60). Cap ≤3 extras. No combinatorial grid.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary(path: Path, arms: list[Arm], books: dict[str, list[dict]]) -> None:
    ctrl_full = next(b for b in books["CONTROL"] if b["slice"] == "FULL")
    ctrl_is = next(b for b in books["CONTROL"] if b["slice"] == "IS")
    ctrl_oos = next(b for b in books["CONTROL"] if b["slice"] == "OOS")
    lines = [
        f"# SUMMARY — {STAMP}",
        "",
        "Research only. Not gold. Not DailyRun. Control = max_rsi_trigger<60 + exit RSI≥70 + ",
        f"min ATR%≥5 + TIME_stop 20d (preference-adopted HOLD arm from `{PRIOR_FREEZE}` — ",
        "not a KEEP from metrics).",
        "",
        "## What you asked",
        "",
        ORIGINAL_REQUEST,
        "",
        "## In plain English",
        "",
        "Relative Strength Index (RSI) Neutral-after-OB with deeper cool-off (trigger RSI < 60), ",
        "sell at RSI 70, Average True Range percent (ATR%) ≥5, plus a 20-day calendar time stop — ",
        "frozen by preference after you liked the HOLD arm. One change at a time around that freeze. ",
        "Quality over count; OOS is a check only. Per-stock summary + universe recommendation ",
        "live in this stamp folder.",
        "",
        "## Control headlines",
        "",
        f"- **FULL** N={ctrl_full['n_trades']:,} Win%={ctrl_full['win_pct']:.2f} "
        f"AvgPnL%={ctrl_full['avg_pnl_pct']:.3f} MaxDD={ctrl_full['max_dd']:.2f}",
        f"- **IS**   N={ctrl_is['n_trades']:,} Win%={ctrl_is['win_pct']:.2f} "
        f"AvgPnL%={ctrl_is['avg_pnl_pct']:.3f} MaxDD={ctrl_is['max_dd']:.2f}",
        f"- **OOS**  N={ctrl_oos['n_trades']:,} Win%={ctrl_oos['win_pct']:.2f} "
        f"AvgPnL%={ctrl_oos['avg_pnl_pct']:.3f} MaxDD={ctrl_oos['max_dd']:.2f}",
        "",
        "## Per-arm FULL verdicts vs control",
        "",
    ]
    keeps, holds, dismiss = [], [], []
    for a in arms:
        if a.name == "CONTROL":
            continue
        full = next(b for b in books[a.name] if b["slice"] == "FULL")
        oos = next(b for b in books[a.name] if b["slice"] == "OOS")
        v = verdict_row(ctrl_full, full)
        line = (
            f"- `{a.name}` ({a.knob}): **{v}** — "
            f"N={full['n_trades']:,} Win%={full['win_pct']:.2f} "
            f"Avg%={full['avg_pnl_pct']:.3f} (Δ{full['avg_pnl_pct']-ctrl_full['avg_pnl_pct']:+.3f}) "
            f"MaxDD={full['max_dd']:.2f} (Δ{full['max_dd']-ctrl_full['max_dd']:+.2f}); "
            f"OOS Avg%={oos['avg_pnl_pct']:.3f} MaxDD={oos['max_dd']:.2f}"
        )
        lines.append(line)
        if "KEEP" in v:
            keeps.append(a.name)
        elif "DISMISS" in v:
            dismiss.append(a.name)
        else:
            holds.append(a.name)
    soft: list[str] = []
    for name in list(keeps):
        oos = next(b for b in books[name] if b["slice"] == "OOS")
        if (
            np.isfinite(oos["avg_pnl_pct"])
            and np.isfinite(ctrl_oos["avg_pnl_pct"])
            and float(oos["avg_pnl_pct"]) + 0.15 < float(ctrl_oos["avg_pnl_pct"])
        ) or (
            np.isfinite(oos["max_dd"])
            and np.isfinite(ctrl_oos["max_dd"])
            and float(oos["max_dd"]) > float(ctrl_oos["max_dd"]) + 2.0
        ):
            soft.append(name)
            keeps.remove(name)
            holds.append(name)
    lines += [
        "",
        "## Roll-up",
        "",
        f"- LEAN KEEP (research): {', '.join(keeps) if keeps else 'none'}",
        f"- HOLD (incl. OOS-softened): {', '.join(holds) if holds else 'none'}"
        + (f" — OOS softened vs control: {', '.join(soft)}" if soft else ""),
        f"- DISMISS: {', '.join(dismiss) if dismiss else 'none'}",
        "",
        "No OOS retune. No DailyRun wire. No gold claim.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def enrich_control_closed() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run enrich script for this stamp; return corr_full, corr_is DataFrames."""
    enrich_script = ROOT / "tools" / "rsi_ob_neutral_rsi70_atr5_ts20_maxrsi60_enrich_20260911.py"
    import subprocess
    r = subprocess.run(
        [sys.executable, str(enrich_script)],
        cwd=str(ROOT),
        check=False,
    )
    if r.returncode != 0:
        print(f"WARN enrich exit {r.returncode}", flush=True)
    corr_full = load_corr(OUT_DIR / "RSIN_Correlation_20260911.csv")
    corr_is = load_corr(OUT_DIR / "RSIN_Correlation_IS_20260911.csv")
    return corr_full, corr_is


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = fixed_arms()
    print(f"Phase 1: {len(arms)} fixed arms (control = maxrsi60 + rsi70 + atr5 + ts20)", flush=True)
    by_arm = run_all(arms)

    # Write control Closed early for enrich
    write_closed_csv(OUT_DIR / "closed_CONTROL.csv", by_arm["CONTROL"])
    # Alias for enrich SRC
    write_closed_csv(OUT_DIR / "closed_fulluniv.csv", by_arm["CONTROL"])
    print(f"Wrote control Closed N={len(by_arm['CONTROL']):,}", flush=True)

    print("Phase 2: enrich control + IS correlation…", flush=True)
    corr_full, corr_is = enrich_control_closed()
    extras = pick_extra_arms(corr_is)
    extra_note = (
        f"Added {len(extras)} IS-corr entry arm(s) from NEW-control |R_PNL|≥0.03 "
        f"(ATR + time-stop + RSI14_AT_TRIGGER skipped; cap 3): "
        + (", ".join(a.name for a in extras) if extras else "none passed the floor.")
    )
    print(extra_note, flush=True)

    if extras:
        print(f"Phase 3: replay {len(extras)} extra arm(s)…", flush=True)
        extra_by = run_all(extras)
        for a in extras:
            by_arm[a.name] = extra_by[a.name]
            arms.append(a)

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
    pd.DataFrame(rows).to_csv(OUT_DIR / "compare_book_metrics.csv", index=False)
    for a in arms:
        write_closed_csv(OUT_DIR / f"closed_{a.name}.csv", by_arm[a.name])
    # Keep closed_fulluniv as control alias
    write_closed_csv(OUT_DIR / "closed_fulluniv.csv", by_arm["CONTROL"])

    # PaulTwenty replay under SAME freeze (CONTROL arm) for universe recommendation
    pt_syms: list[str] = []
    if PAUL_TWENTY.is_file():
        pt = pd.read_csv(PAUL_TWENTY)
        col = "symbol" if "symbol" in [c.lower() for c in pt.columns] else pt.columns[0]
        # find actual column case-insensitively
        for c in pt.columns:
            if str(c).lower() in ("symbol", "ticker", "sym"):
                col = c
                break
        pt_syms = sorted({str(x).strip().upper() for x in pt[col].dropna() if str(x).strip()})
    pt_trades: list[dict] = []
    if pt_syms:
        print(f"PaulTwenty replay ({len(pt_syms)} symbols) under CONTROL freeze…", flush=True)
        for sym in pt_syms:
            df = load_ohlcv(sym)
            if df is None or len(df) < 20:
                continue
            feat = features(df)
            ctrl = next(a for a in arms if a.name == "CONTROL")
            for t in backtest_arm(df, feat, ctrl):
                t["symbol"] = sym
                pt_trades.append(t)
        write_closed_csv(OUT_DIR / "closed_PaulTwenty.csv", pt_trades)
        pt_books = [book_metrics(filter_slice(pt_trades, s), s) for s in ("FULL", "IS", "OOS")]
        pd.DataFrame([{"universe": "PaulTwenty", **b} for b in pt_books]).to_csv(
            OUT_DIR / "compare_paultwenty_book.csv", index=False
        )
        print(f"  PaulTwenty FULL N={pt_books[0]['n_trades']}", flush=True)

    write_baseline(OUT_DIR / "BASELINE.md", arms)
    write_summary(OUT_DIR / "SUMMARY.md", arms, books)
    html_path = OUT_DIR / "compare.html"
    write_html(html_path, arms, books, corr_full, corr_is, extra_note)
    print(f"HTML {html_path}", flush=True)
    print(f"SUMMARY {OUT_DIR / 'SUMMARY.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
