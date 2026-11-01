#!/usr/bin/env python3
"""Research A/B: buy Neutral-after-Overbought, sell when RSI returns Overbought.

Universes: PaulTwenty vs full local OHLC (data/newdata/data).
Long-only, next-open fill, costs = 0. Research only — not gold, not DailyRun.

Usage:
  python tools/rsi_ob_neutral_exit_ob_ab_20260910.py
"""
from __future__ import annotations

import html as html_mod
import math
import sys
from collections import defaultdict
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

from rocket_tbn import _wilder_rsi14_arr  # noqa: E402

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    overlay_ann_ror_max_dd,
)

DATA_DIR = ROOT / "data" / "newdata" / "data"
DRIVE = ROOT / "drive"
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
STAMP = "rsi_ob_to_neutral_exit_ob_20260910"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUTOFF = pd.Timestamp("2024-01-01")
TRADING_DAYS_PER_YEAR = 252
RSI_OB = 70.0
RSI_OS = 30.0
NOTIONAL = 10_000.0
ACCOUNT = DEFAULT_INITIAL_ACCOUNT
ORIGINAL_REQUEST = (
    "can you make sure our overbought/oversold sentiment is calculated on "
    "trigger day and not entry? also, can you run a test of a new system. "
    "use the paultwenty and full universe to compare. buy when a stock goes "
    "neutral after being overbought and sell when the stock goes back into "
    "overbought range"
)

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 76rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 76rem; }
.ask { background: #eff6ff; border: 1px solid #bfdbfe; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .86rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .35rem .55rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.up { color: #047857; font-weight: 600; }
.down { color: #b91c1c; font-weight: 600; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
.chart-wrap { max-width: 76rem; margin: 1rem 0; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem; }
svg.eq { width: 100%; height: auto; display: block; }
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


def load_universe_csv(path: Path) -> list[str]:
    out: list[str] = []
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            tok = s.split(",")[0].strip().strip('"')
            if tok and tok not in {"*", "ALL"}:
                out.append(tok)
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def list_full_universe() -> list[str]:
    out: list[str] = []
    if not DATA_DIR.is_dir():
        return out
    for p in sorted(DATA_DIR.glob("*.csv")):
        stem = p.stem.strip().upper()
        if stem:
            out.append(stem)
    return out


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
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
            "Close": pd.to_numeric(df[cols["close"]], errors="coerce"),
        }
    )
    out = out.dropna(subset=["Date", "Open", "Close"]).sort_values("Date").drop_duplicates("Date")
    return out.reset_index(drop=True)


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return float("nan")
    peak = np.maximum.accumulate(equity)
    dd = equity / np.where(peak > 0, peak, np.nan) - 1.0
    return float(np.nanmin(dd))


def ann_ror_from_total(total_ret: float, n_days: int) -> float:
    if n_days <= 0 or not np.isfinite(total_ret) or total_ret <= -1.0:
        return float("nan")
    years = n_days / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return float("nan")
    return float((1.0 + total_ret) ** (1.0 / years) - 1.0)


def sharpe_from_daily(rets: np.ndarray) -> float:
    r = rets[np.isfinite(rets)]
    if len(r) < 2:
        return float("nan")
    sd = float(np.std(r, ddof=1))
    if sd <= 0:
        return float("nan")
    return float(np.mean(r) / sd * math.sqrt(TRADING_DAYS_PER_YEAR))


def fmt_pct(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * x:.{digits}f}%"


def fmt_pct_pts(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{digits}f}%"


def fmt_pct_signed(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * x:+.{digits}f}%"


def fmt_num(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{digits}f}"


def fmt_int(x: object) -> str:
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "—"


def _ymd(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def backtest_symbol(sym: str, ohlc: pd.DataFrame, acc: Optional[dict] = None) -> tuple[list[dict], dict]:
    """Next-open long-only: buy Neutral-after-OB, sell when RSI returns OB."""
    n = len(ohlc)
    empty_meta = {
        "symbol": sym,
        "n_days": n,
        "n_buys": 0,
        "n_sells": 0,
        "n_trades": 0,
        "strat_total_ret": float("nan"),
        "bh_total_ret": float("nan"),
        "delta_total_ret": float("nan"),
        "time_in_market": float("nan"),
        "skipped": "short_history" if n < 20 else "",
    }
    if n < 20:
        return [], empty_meta

    close = ohlc["Close"].to_numpy(dtype=np.float64)
    open_ = ohlc["Open"].to_numpy(dtype=np.float64)
    dates = ohlc["Date"]
    rsi = _wilder_rsi14_arr(close)
    prev = np.roll(rsi, 1)
    prev[0] = np.nan
    buy_sig = (prev >= RSI_OB) & (rsi > RSI_OS) & (rsi < RSI_OB)
    sell_sig = rsi >= RSI_OB

    strat = np.zeros(n, dtype=np.float64)
    bh = np.zeros(n, dtype=np.float64)
    exec_pos = np.zeros(n, dtype=np.int8)
    for i in range(1, n):
        if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(close[i]):
            bh[i] = close[i] / close[i - 1] - 1.0

    trades: list[dict] = []
    in_pos = False
    pending_entry = False
    pending_exit = False
    entry_px = float("nan")
    entry_i = -1
    signal_i = -1
    signal_rsi = float("nan")
    n_buys = 0
    n_sells = 0

    def _close_trade(exit_i: int, exit_px: float, exit_type: str) -> None:
        nonlocal entry_px, entry_i, signal_i, signal_rsi
        if entry_i < 0 or not np.isfinite(entry_px) or entry_px <= 0:
            return
        if not np.isfinite(exit_px) or exit_px <= 0:
            return
        pnl_pct = (exit_px / entry_px - 1.0) * 100.0
        days = int((dates.iloc[exit_i] - dates.iloc[entry_i]).days)
        if days < 0:
            days = 0
        trades.append(
            {
                "symbol": sym,
                "opened": dates.iloc[entry_i],
                "closed": dates.iloc[exit_i],
                "signal_date": dates.iloc[signal_i] if signal_i >= 0 else dates.iloc[entry_i],
                "entry": float(entry_px),
                "exit": float(exit_px),
                "pnl": float(pnl_pct),
                "pnl_d": float(NOTIONAL * pnl_pct / 100.0),
                "days": days,
                "exit_type": exit_type,
                "rsi_trigger": float(signal_rsi) if np.isfinite(signal_rsi) else float("nan"),
                "rsi_exit": float(rsi[exit_i]) if np.isfinite(rsi[exit_i]) else float("nan"),
            }
        )
        entry_px = float("nan")
        entry_i = -1
        signal_i = -1
        signal_rsi = float("nan")

    for i in range(n):
        was_in = in_pos
        if pending_entry and not in_pos:
            px = float(open_[i])
            if px > 0 and np.isfinite(px):
                in_pos = True
                entry_px = px
                entry_i = i
                n_buys += 1
            pending_entry = False
        elif pending_exit and in_pos:
            px = float(open_[i])
            if px > 0 and np.isfinite(px):
                _close_trade(i, px, "OVERBOUGHT")
                in_pos = False
                n_sells += 1
            pending_exit = False

        exec_pos[i] = 1 if in_pos else 0
        if was_in and in_pos:
            if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(close[i]):
                strat[i] = close[i] / close[i - 1] - 1.0
        elif (not was_in) and in_pos:
            if open_[i] > 0 and np.isfinite(open_[i]) and np.isfinite(close[i]):
                strat[i] = close[i] / open_[i] - 1.0
        elif was_in and (not in_pos):
            if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(open_[i]) and open_[i] > 0:
                strat[i] = open_[i] / close[i - 1] - 1.0

        if i == n - 1:
            continue
        if not np.isfinite(rsi[i]):
            continue
        if in_pos:
            if bool(sell_sig[i]):
                pending_exit = True
        elif bool(buy_sig[i]):
            pending_entry = True
            signal_i = i
            signal_rsi = float(rsi[i])

    if in_pos and entry_i >= 0:
        last_px = float(close[-1])
        if last_px > 0 and np.isfinite(last_px):
            _close_trade(n - 1, last_px, "EOD")
            n_sells += 1
            in_pos = False

    if acc is not None:
        for i in range(n):
            slot = acc[dates.iloc[i]]
            slot["n"] += 1
            slot["strat_sum"] += float(strat[i])
            slot["bh_sum"] += float(bh[i])
            slot["n_long"] += int(exec_pos[i])
            if i > 0 and exec_pos[i] == 1 and exec_pos[i - 1] == 0:
                slot["n_buys"] += 1
            if i > 0 and exec_pos[i] == 0 and exec_pos[i - 1] == 1:
                slot["n_sells"] += 1

    strat_total = float(np.prod(1.0 + strat) - 1.0)
    bh_total = float(np.prod(1.0 + bh) - 1.0)
    meta = {
        "symbol": sym,
        "n_days": n,
        "n_buys": n_buys,
        "n_sells": n_sells,
        "n_trades": len(trades),
        "strat_total_ret": strat_total,
        "bh_total_ret": bh_total,
        "delta_total_ret": strat_total - bh_total,
        "time_in_market": float(np.mean(exec_pos)) if n else float("nan"),
        "strat_max_dd": max_drawdown(np.cumprod(1.0 + strat)),
        "bh_max_dd": max_drawdown(np.cumprod(1.0 + bh)),
        "skipped": "",
    }
    return trades, meta


def portfolio_from_acc(acc: dict) -> pd.DataFrame:
    if not acc:
        return pd.DataFrame()
    rows = []
    for d in sorted(acc):
        s = acc[d]
        n = max(int(s["n"]), 1)
        rows.append(
            {
                "Date": d,
                "strat_ret": s["strat_sum"] / n,
                "bh_ret": s["bh_sum"] / n,
                "n_symbols": int(s["n"]),
                "n_long": int(s["n_long"]),
                "n_buys": int(s["n_buys"]),
                "n_sells": int(s["n_sells"]),
                "position_frac": s["n_long"] / n,
            }
        )
    port = pd.DataFrame(rows)
    port["strat_eq"] = (1.0 + port["strat_ret"]).cumprod()
    port["bh_eq"] = (1.0 + port["bh_ret"]).cumprod()
    return port


def port_metrics(port: pd.DataFrame, label: str, n_buys: int, n_sells: int) -> dict:
    if port is None or port.empty:
        return {
            "slice": label,
            "start": "",
            "end": "",
            "n_days": 0,
            "strat_total_ret": float("nan"),
            "bh_total_ret": float("nan"),
            "delta_total_ret": float("nan"),
            "strat_ann_ror": float("nan"),
            "bh_ann_ror": float("nan"),
            "delta_ann_ror": float("nan"),
            "strat_max_dd": float("nan"),
            "bh_max_dd": float("nan"),
            "delta_max_dd": float("nan"),
            "strat_sharpe": float("nan"),
            "bh_sharpe": float("nan"),
            "delta_sharpe": float("nan"),
            "time_in_market": float("nan"),
            "n_buys": n_buys,
            "n_sells": n_sells,
        }
    strat = port["strat_ret"].to_numpy(dtype=float)
    bh = port["bh_ret"].to_numpy(dtype=float)
    strat_eq = port["strat_eq"].to_numpy(dtype=float)
    bh_eq = port["bh_eq"].to_numpy(dtype=float)
    n = len(port)
    strat_total = float(strat_eq[-1] - 1.0)
    bh_total = float(bh_eq[-1] - 1.0)
    return {
        "slice": label,
        "start": _ymd(port["Date"].iloc[0]),
        "end": _ymd(port["Date"].iloc[-1]),
        "n_days": n,
        "strat_total_ret": strat_total,
        "bh_total_ret": bh_total,
        "delta_total_ret": strat_total - bh_total,
        "strat_ann_ror": ann_ror_from_total(strat_total, n),
        "bh_ann_ror": ann_ror_from_total(bh_total, n),
        "delta_ann_ror": ann_ror_from_total(strat_total, n) - ann_ror_from_total(bh_total, n),
        "strat_max_dd": max_drawdown(strat_eq),
        "bh_max_dd": max_drawdown(bh_eq),
        "delta_max_dd": max_drawdown(strat_eq) - max_drawdown(bh_eq),
        "strat_sharpe": sharpe_from_daily(strat),
        "bh_sharpe": sharpe_from_daily(bh),
        "delta_sharpe": sharpe_from_daily(strat) - sharpe_from_daily(bh),
        "time_in_market": float(port["position_frac"].mean()) if n else float("nan"),
        "n_buys": n_buys,
        "n_sells": n_sells,
    }


def slice_port(port: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    sub = port.loc[mask].copy()
    if sub.empty:
        return sub
    sub["strat_eq"] = (1.0 + sub["strat_ret"]).cumprod()
    sub["bh_eq"] = (1.0 + sub["bh_ret"]).cumprod()
    return sub.reset_index(drop=True)


def book_metrics(trades: list[dict], label: str) -> dict:
    n = len(trades)
    empty = {
        "slice": label,
        "n_trades": 0,
        "n_wins": 0,
        "n_losses": 0,
        "win_pct": float("nan"),
        "avg_pnl_pct": float("nan"),
        "avg_pnl_pct_wo_max": float("nan"),
        "expectancy_pct": float("nan"),
        "avg_win_pct": float("nan"),
        "avg_loss_pct": float("nan"),
        "profit_factor": float("nan"),
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "sharpe_source": "",
        "avg_days": float("nan"),
        "median_days": float("nan"),
        "p90_days": float("nan"),
        "capital_days": 0,
        "profit_per_cap_day": float("nan"),
        "exit_ob": 0,
        "exit_eod": 0,
        "n_symbols": 0,
    }
    if n <= 0:
        return empty
    pnls = np.array([float(t["pnl"]) for t in trades], dtype=float)
    days = np.array([float(t["days"]) for t in trades], dtype=float)
    dolls = np.array([float(t["pnl_d"]) for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    win_d = dolls[dolls > 0]
    loss_d = dolls[dolls < 0]
    wo = pnls.copy()
    if len(wo) >= 2:
        wo = np.delete(wo, int(np.argmax(wo)))
    sum_w = float(win_d.sum()) if len(win_d) else 0.0
    sum_l = float(abs(loss_d.sum())) if len(loss_d) else 0.0
    pf = sum_w / sum_l if sum_l > 0 else (sum_w if sum_w > 0 else float("nan"))
    avg_days = float(np.mean(days)) if len(days) else float("nan")
    overlay = overlay_ann_ror_max_dd(
        trades,
        cash=NOTIONAL,
        initial_account=ACCOUNT,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl",
    )
    ann = overlay.get("ann_ror")
    if ann is None or (isinstance(ann, float) and not np.isfinite(ann)):
        tot = float(dolls.sum())
        ann = ann_ror_from_closed(
            total_pnl=tot,
            n_trades=n,
            avg_days_held=avg_days,
            brt_cash=NOTIONAL,
        )
        if ann is None:
            ann = float("nan")
    max_dd = overlay.get("max_dd")
    if max_dd is None:
        max_dd = float("nan")
    calmar = overlay.get("calmar")
    if calmar is None or (isinstance(calmar, float) and not np.isfinite(calmar)):
        if np.isfinite(float(ann)) and np.isfinite(float(max_dd)) and abs(float(max_dd)) > 1e-12:
            calmar = float(ann) / abs(float(max_dd))
        else:
            calmar = float("nan")
    cap_days = int(np.nansum(days))
    tot_d = float(dolls.sum())
    return {
        "slice": label,
        "n_trades": n,
        "n_wins": int(len(wins)),
        "n_losses": int(len(losses)),
        "win_pct": 100.0 * len(wins) / n,
        "avg_pnl_pct": float(np.mean(pnls)),
        "avg_pnl_pct_wo_max": float(np.mean(wo)) if len(wo) else float("nan"),
        "expectancy_pct": float(np.mean(pnls)),
        "avg_win_pct": float(np.mean(wins)) if len(wins) else float("nan"),
        "avg_loss_pct": float(np.mean(losses)) if len(losses) else float("nan"),
        "profit_factor": float(pf),
        "ann_ror": float(ann),
        "max_dd": float(max_dd),
        "calmar": float(calmar) if calmar is not None else float("nan"),
        "sharpe": float(overlay.get("sharpe")) if overlay.get("sharpe") is not None else float("nan"),
        "sharpe_source": str(overlay.get("sharpe_source") or ""),
        "avg_days": avg_days,
        "median_days": float(np.median(days)),
        "p90_days": float(np.percentile(days, 90)),
        "capital_days": cap_days,
        "profit_per_cap_day": (tot_d / cap_days) if cap_days > 0 else float("nan"),
        "exit_ob": int(sum(1 for t in trades if t.get("exit_type") == "OVERBOUGHT")),
        "exit_eod": int(sum(1 for t in trades if t.get("exit_type") == "EOD")),
        "n_symbols": len({t["symbol"] for t in trades}),
    }


def filter_trades(trades: list[dict], which: str) -> list[dict]:
    if which == "FULL":
        return list(trades)
    if which == "IS":
        return [t for t in trades if pd.Timestamp(t["opened"]) < IS_CUTOFF]
    return [t for t in trades if pd.Timestamp(t["opened"]) >= IS_CUTOFF]


def svg_equity_chart(port: pd.DataFrame, width: int = 900, height: int = 300) -> str:
    if port is None or len(port) < 2:
        return "<p class='meta'>Not enough points for chart.</p>"
    dates = port["Date"]
    strat_eq = port["strat_eq"].to_numpy(dtype=float)
    bh_eq = port["bh_eq"].to_numpy(dtype=float)
    pad_l, pad_r, pad_t, pad_b = 52, 16, 16, 36
    xs = np.linspace(pad_l, width - pad_r, len(dates))
    y_all = np.concatenate([strat_eq, bh_eq])
    ymin, ymax = float(np.nanmin(y_all)), float(np.nanmax(y_all))
    if ymin == ymax:
        ymax = ymin + 1e-6

    def ymap(v: float) -> float:
        return pad_t + (1.0 - (v - ymin) / (ymax - ymin)) * (height - pad_t - pad_b)

    def path(eq: np.ndarray) -> str:
        pts = [f"{xs[i]:.1f},{ymap(float(eq[i])):.1f}" for i in range(len(eq))]
        return "M " + " L ".join(pts)

    lab_idx = np.linspace(0, len(dates) - 1, 6).astype(int)
    labels = []
    for i in lab_idx:
        labels.append(
            f'<text x="{xs[i]:.1f}" y="{height - 10}" text-anchor="middle" '
            f'font-size="11" fill="#64748b">{pd.Timestamp(dates.iloc[i]).strftime("%Y-%m")}</text>'
        )
    ylabs = []
    for v in np.linspace(ymin, ymax, 5):
        ylabs.append(
            f'<text x="{pad_l - 6}" y="{ymap(float(v)) + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#64748b">{v:.2f}</text>'
            f'<line x1="{pad_l}" y1="{ymap(float(v)):.1f}" x2="{width - pad_r}" '
            f'y2="{ymap(float(v)):.1f}" stroke="#e2e8f0" stroke-width="1"/>'
        )
    return f"""
<svg class="eq" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Equity curves">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>
  {''.join(ylabs)}
  <path d="{path(bh_eq)}" fill="none" stroke="#94a3b8" stroke-width="2"/>
  <path d="{path(strat_eq)}" fill="none" stroke="#0369a1" stroke-width="2.25"/>
  {''.join(labels)}
  <rect x="{width - 210}" y="12" width="12" height="12" fill="#0369a1"/>
  <text x="{width - 194}" y="22" font-size="12" fill="#334155">Strategy</text>
  <rect x="{width - 120}" y="12" width="12" height="12" fill="#94a3b8"/>
  <text x="{width - 104}" y="22" font-size="12" fill="#334155">Buy&amp;hold EW</text>
</svg>
"""


def run_universe(name: str, symbols: list[str]) -> dict:
    print(f"[{name}] {len(symbols)} symbols", flush=True)
    trades: list[dict] = []
    metas: list[dict] = []
    acc: dict = defaultdict(lambda: {
        "n": 0, "strat_sum": 0.0, "bh_sum": 0.0, "n_long": 0, "n_buys": 0, "n_sells": 0,
    })
    n_ok = 0
    n_skip = 0
    for i, sym in enumerate(symbols, 1):
        ohlc = load_ohlc(sym)
        if ohlc is None or ohlc.empty:
            n_skip += 1
            metas.append({
                "symbol": sym, "n_days": 0, "n_buys": 0, "n_sells": 0, "n_trades": 0,
                "strat_total_ret": float("nan"), "bh_total_ret": float("nan"),
                "delta_total_ret": float("nan"), "time_in_market": float("nan"),
                "skipped": "missing_ohlc",
            })
            continue
        tlist, meta = backtest_symbol(sym, ohlc, acc)
        trades.extend(tlist)
        metas.append(meta)
        n_ok += 1
        if i % 100 == 0 or i == len(symbols):
            print(f"  [{name}] {i}/{len(symbols)}  trades={len(trades)}", flush=True)
    port = portfolio_from_acc(acc)
    n_buys = int(sum(m.get("n_buys") or 0 for m in metas))
    n_sells = int(sum(m.get("n_sells") or 0 for m in metas))
    if port is not None and not port.empty:
        is_mask = port["Date"] < IS_CUTOFF
        oos_mask = port["Date"] >= IS_CUTOFF
        port_rows = [
            port_metrics(port, "FULL", n_buys, n_sells),
            port_metrics(
                slice_port(port, is_mask),
                "IS",
                int(sum(1 for t in trades if pd.Timestamp(t["opened"]) < IS_CUTOFF)),
                int(sum(1 for t in trades if pd.Timestamp(t["opened"]) < IS_CUTOFF and t["exit_type"] != "")),
            ),
            port_metrics(
                slice_port(port, oos_mask),
                "OOS",
                int(sum(1 for t in trades if pd.Timestamp(t["opened"]) >= IS_CUTOFF)),
                int(sum(1 for t in trades if pd.Timestamp(t["opened"]) >= IS_CUTOFF)),
            ),
        ]
    else:
        port_rows = [port_metrics(port, s, 0, 0) for s in ("FULL", "IS", "OOS")]
    books = [book_metrics(filter_trades(trades, s), s) for s in ("FULL", "IS", "OOS")]
    return {
        "name": name,
        "n_listed": len(symbols),
        "n_ok": n_ok,
        "n_skip": n_skip,
        "trades": trades,
        "metas": metas,
        "port": port,
        "port_rows": port_rows,
        "books": books,
        "n_buys": n_buys,
        "n_sells": n_sells,
    }


def verdict_from_results(pt: dict, full: dict) -> str:
    pt_b = next((b for b in pt["books"] if b["slice"] == "FULL"), {})
    fu_b = next((b for b in full["books"] if b["slice"] == "FULL"), {})
    pt_oos = next((b for b in pt["books"] if b["slice"] == "OOS"), {})
    fu_oos = next((b for b in full["books"] if b["slice"] == "OOS"), {})
    pt_avg = pt_b.get("avg_pnl_pct")
    fu_avg = fu_b.get("avg_pnl_pct")
    pt_wr = pt_b.get("win_pct")
    fu_wr = fu_b.get("win_pct")

    def _ok(x: object) -> bool:
        try:
            return bool(np.isfinite(float(x)))
        except (TypeError, ValueError):
            return False

    if not _ok(pt_avg) and not _ok(fu_avg):
        return "INCONCLUSIVE — no closed trades."
    # Quality over count. OOS report-only.
    oos_soft = False
    if _ok(pt_avg) and _ok(pt_oos.get("avg_pnl_pct")) and float(pt_oos["avg_pnl_pct"]) < float(pt_avg) - 0.25:
        oos_soft = True
    if _ok(fu_avg) and _ok(fu_oos.get("avg_pnl_pct")) and float(fu_oos["avg_pnl_pct"]) < float(fu_avg) - 0.25:
        oos_soft = True
    both_neg = (_ok(pt_avg) and float(pt_avg) <= 0) and (_ok(fu_avg) and float(fu_avg) <= 0)
    both_pos = (_ok(pt_avg) and float(pt_avg) > 0) and (_ok(fu_avg) and float(fu_avg) > 0)
    if both_neg:
        return (
            "DISMISS (research) — average trade is not profitable on PaulTwenty or full universe. "
            "Do not wire DailyRun."
        )
    pt_dd = pt_b.get("max_dd")
    fu_dd = fu_b.get("max_dd")
    pt_oos_dd = pt_oos.get("max_dd")
    fu_oos_dd = fu_oos.get("max_dd")
    dd_soft = False
    if _ok(fu_dd) and _ok(fu_oos_dd) and float(fu_oos_dd) > float(fu_dd) + 3.0:
        dd_soft = True
    if _ok(pt_dd) and _ok(pt_oos_dd) and float(pt_oos_dd) > float(pt_dd) + 3.0:
        dd_soft = True
    if (oos_soft or dd_soft) and both_pos:
        return (
            "HOLD — FULL book is positive on Avg PnL% / win%, but OOS quality softens "
            "(drawdown and/or Avg PnL%). Report-only on OOS; do not retune. "
            "Research candidate only, not gold."
        )
    if both_pos and _ok(pt_wr) and _ok(fu_wr) and float(pt_wr) >= 45 and float(fu_wr) >= 45:
        return (
            "INTERESTING (research candidate) — quality (Avg PnL% / win%) is positive on both "
            "universes. Still not gold / not DailyRun. No OOS retune."
        )
    if both_pos:
        return (
            "LEAN KEEP / HOLD (research) — Avg PnL% positive on both books but win% or robustness "
            "is mixed. Not gold. Not DailyRun."
        )
    return (
        "HOLD — mixed quality across universes (one book weaker). Research only; "
        "do not pick a universe from OOS."
    )


def write_baseline(path: Path, pt: dict, full: dict) -> None:
    text = f"""# BASELINE — {STAMP}

Research only. Not gold. Not DailyRun. OOS is report-only (no retune).

## Original request

{ORIGINAL_REQUEST}

## Hypothesis (one idea)

After Relative Strength Index (RSI) — a 0–100 “too hot / too cold” speedometer on the last 14 closes — has been **Overbought** (≥70) and then prints **Neutral** (between 30 and 70), a long entry has edge. Exit when RSI prints **Overbought** again.

## Frozen knobs

| Knob | Value |
|------|--------|
| RSI | Wilder RSI(14), same as `rocket_tbn._wilder_rsi14_arr` / trendline charts |
| Overbought | RSI ≥ 70 |
| Oversold | RSI ≤ 30 |
| Neutral | 30 < RSI < 70 |
| BUY | Prior bar Overbought **and** today Neutral (skip if today is Oversold) |
| SELL | Today Overbought (while long) |
| Side | Long-only |
| Fill | Next open after signal close (no same-bar look-ahead) |
| Stops / targets / time stop | None (exit = Overbought or last-bar EOD mark) |
| Costs | 0 |
| Sizing | $10,000 notional / trade; overlay account $500,000 |
| One position / symbol | Yes |
| Universes | PaulTwenty (`drive/universes/PaulTwenty_universe.csv`, {pt['n_listed']} listed / {pt['n_ok']} with OHLC) vs full `data/newdata/data/*.csv` ({full['n_listed']} listed / {full['n_ok']} with OHLC) |
| IS / OOS | IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01` (report-only) |

## Sentiment fix (same job, not this AB)

Closed `RSI14_OB_OS` is now labeled from **trigger-bar** RSI (`RSI14_AT_TRIGGER`). `RSI14_AT_ENTRY` remains the fill-bar number so VZ `max_rsi14_at_entry` stays an entry gate.

## Selection honesty

Rules taken from the ask. No grid. No OOS-driven KEEP. Comparing two universes with the same freeze is a **universe A/B**, not an exit horse-race.
"""
    path.write_text(text, encoding="utf-8")


def write_summary(path: Path, pt: dict, full: dict, verdict: str) -> None:
    lines = [
        f"# SUMMARY — {STAMP}",
        "",
        f"**Verdict:** {verdict}",
        "",
        "Research only. RSI = Relative Strength Index (Wilder 14).",
        "",
        "## Book (closed trades, $10k notional)",
        "",
        "| Universe | Slice | N | Win% | Avg PnL% | Avg% w/o max | PF | Ann ROR% | Max DD% | Calmar | Sharpe | Avg days |",
        "|----------|-------|---|------|----------|--------------|----|----------|---------|--------|--------|----------|",
    ]
    for u in (pt, full):
        for b in u["books"]:
            lines.append(
                f"| {u['name']} | {b['slice']} | {b['n_trades']} | {fmt_pct_pts(b['win_pct'])} | "
                f"{fmt_pct_pts(b['avg_pnl_pct'])} | {fmt_pct_pts(b['avg_pnl_pct_wo_max'])} | "
                f"{fmt_num(b['profit_factor'])} | {fmt_pct_pts(b['ann_ror'])} | {fmt_pct_pts(b['max_dd'])} | "
                f"{fmt_num(b['calmar'])} | {fmt_num(b['sharpe'])} | {fmt_num(b['avg_days'], 1)} |"
            )
    lines += [
        "",
        f"Stamp: `drive/paul_experiments/{STAMP}/`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _book_table(pt: dict, full: dict) -> str:
    headers = [
        ("Universe", "text"),
        ("Slice", "text"),
        ("N symbols traded", "num"),
        ("N trades", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Expectancy %", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Profit factor", "num"),
        ("Ann ROR %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Sharpe (exit-date overlay)", "num"),
        ("Avg days held", "num"),
        ("Median days", "num"),
        ("P90 days", "num"),
        ("Capital days", "num"),
        ("Profit / capital day", "num"),
        ("Exit OVERBOUGHT", "num"),
        ("Exit EOD", "num"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    body = []
    for u in (pt, full):
        for b in u["books"]:
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(u['name'])}</td>"
                f"<td>{b['slice']}</td>"
                f"<td>{fmt_int(b['n_symbols'])}</td>"
                f"<td>{fmt_int(b['n_trades'])}</td>"
                f"<td>{fmt_int(b['n_wins'])}</td>"
                f"<td>{fmt_int(b['n_losses'])}</td>"
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
                f"<td>{fmt_int(b['exit_eod'])}</td>"
                "</tr>"
            )
    return (
        '<p class="meta">Click column headers to sort. Total/Sheet PnL $ omitted from HTML. '
        "Ann ROR / Max DD / Calmar / Sharpe from Closed overlay ($10k notional, $500k seed). "
        "OOS is report-only.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def _port_table(pt: dict, full: dict) -> str:
    headers = [
        ("Universe", "text"),
        ("Slice", "text"),
        ("Start", "date"),
        ("End", "date"),
        ("N days", "num"),
        ("Strat total", "num"),
        ("BH total", "num"),
        ("Δ total", "num"),
        ("Strat Ann ROR", "num"),
        ("BH Ann ROR", "num"),
        ("Δ Ann ROR", "num"),
        ("Strat Max DD", "num"),
        ("BH Max DD", "num"),
        ("Δ Max DD", "num"),
        ("Strat Sharpe", "num"),
        ("BH Sharpe", "num"),
        ("Time in mkt", "num"),
        ("# Buys", "num"),
        ("# Sells", "num"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    body = []
    for u in (pt, full):
        for r in u["port_rows"]:
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(u['name'])}</td>"
                f"<td>{r['slice']}</td>"
                f"<td>{r['start']}</td>"
                f"<td>{r['end']}</td>"
                f"<td>{fmt_int(r['n_days'])}</td>"
                f"<td>{fmt_pct(r['strat_total_ret'])}</td>"
                f"<td>{fmt_pct(r['bh_total_ret'])}</td>"
                f"<td>{fmt_pct_signed(r['delta_total_ret'])}</td>"
                f"<td>{fmt_pct(r['strat_ann_ror'])}</td>"
                f"<td>{fmt_pct(r['bh_ann_ror'])}</td>"
                f"<td>{fmt_pct_signed(r['delta_ann_ror'])}</td>"
                f"<td>{fmt_pct(r['strat_max_dd'])}</td>"
                f"<td>{fmt_pct(r['bh_max_dd'])}</td>"
                f"<td>{fmt_pct_signed(r['delta_max_dd'])}</td>"
                f"<td>{fmt_num(r['strat_sharpe'])}</td>"
                f"<td>{fmt_num(r['bh_sharpe'])}</td>"
                f"<td>{fmt_pct(r['time_in_market'], 1)}</td>"
                f"<td>{fmt_int(r['n_buys'])}</td>"
                f"<td>{fmt_int(r['n_sells'])}</td>"
                "</tr>"
            )
    return (
        '<p class="meta">Equal-weight daily mean of names present that day (flats count as 0). '
        "Buy-hold is the same basket always long. Click headers to sort.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def _sym_table(metas: list[dict], limit: int = 40) -> str:
    ranked = sorted(
        [m for m in metas if not m.get("skipped")],
        key=lambda m: (m.get("strat_total_ret") if np.isfinite(m.get("strat_total_ret") or float("nan")) else -9e9),
        reverse=True,
    )
    show = ranked[:limit]
    headers = [
        ("Symbol", "text"),
        ("Trades", "num"),
        ("Buys", "num"),
        ("Strat total", "num"),
        ("BH total", "num"),
        ("Δ total", "num"),
        ("Time in mkt", "num"),
        ("Strat Max DD", "num"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    body = []
    for m in show:
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(str(m['symbol']))}</td>"
            f"<td>{fmt_int(m.get('n_trades'))}</td>"
            f"<td>{fmt_int(m.get('n_buys'))}</td>"
            f"<td>{fmt_pct(m.get('strat_total_ret'))}</td>"
            f"<td>{fmt_pct(m.get('bh_total_ret'))}</td>"
            f"<td>{fmt_pct_signed(m.get('delta_total_ret'))}</td>"
            f"<td>{fmt_pct(m.get('time_in_market'), 1)}</td>"
            f"<td>{fmt_pct(m.get('strat_max_dd'))}</td>"
            "</tr>"
        )
    return (
        f'<p class="meta">Top {len(show)} by strategy total return (click headers to sort the shown rows).</p>'
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def write_html(path: Path, pt: dict, full: dict, verdict: str) -> None:
    pt_full = next((b for b in pt["books"] if b["slice"] == "FULL"), {})
    fu_full = next((b for b in full["books"] if b["slice"] == "FULL"), {})
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>Buy Neutral-after-Overbought / sell Overbought — PaulTwenty vs full universe</h1>
<p class="badge">Research only · not gold · not DailyRun · OOS report-only</p>
<p class="meta">Stamp <code>{STAMP}</code> · generated {date.today().isoformat()} · click column headers to sort</p>

<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>Two jobs in one. First, the “too hot / too cold / in the middle” label on closed trades now uses the
<strong>day the system fired</strong> (the trigger), not the next morning we bought. The fill-day RSI number is still stored separately.</p>
<p>Second, we tested a simple new rule on two baskets: <strong>PaulTwenty</strong> (your 20-name list) and the
<strong>full universe</strong> (every daily price file we keep). <em>Overbought</em> means Wilder RSI(14) — a 0–100
speedometer of recent up vs down closes — is 70 or higher (“too hot”). <em>Neutral</em> means it cooled into the
middle (above 30 and below 70). The test <strong>buys the next morning</strong> after a stock prints Neutral
following an Overbought day, and <strong>sells the next morning</strong> after it prints Overbought again.
No extra stop, target, or time limit. We did <strong>not</strong> peek at the later (out-of-sample) years to pick the rule.</p>
</div>

<div class="insight">
<strong>Verdict:</strong> {html_mod.escape(verdict)}
<p class="meta">Judge quality (win%, Avg PnL%, expectancy, Ann ROR, Max DD), not trade count.
PaulTwenty FULL: N={fmt_int(pt_full.get('n_trades'))}, Win%={fmt_pct_pts(pt_full.get('win_pct'))},
Avg PnL%={fmt_pct_pts(pt_full.get('avg_pnl_pct'))}.
Full univ FULL: N={fmt_int(fu_full.get('n_trades'))}, Win%={fmt_pct_pts(fu_full.get('win_pct'))},
Avg PnL%={fmt_pct_pts(fu_full.get('avg_pnl_pct'))}.</p>
</div>

<h2>1. Book metrics (canonical overlay)</h2>
{_book_table(pt, full)}

<h2>2. Equal-weight daily portfolio vs buy-hold</h2>
{_port_table(pt, full)}

<h2>3. Equity — PaulTwenty</h2>
<div class="chart-wrap">{svg_equity_chart(pt['port'])}</div>
<h2>4. Equity — full universe</h2>
<div class="chart-wrap">{svg_equity_chart(full['port'])}</div>

<h2>5. PaulTwenty names (contribution)</h2>
{_sym_table(pt['metas'], limit=30)}

<h2>6. Full universe — strongest names (sample)</h2>
{_sym_table(full['metas'], limit=40)}

<h2>Freeze</h2>
<ul class="meta">
<li>RSI: Wilder 14 · OB ≥ 70 · OS ≤ 30 · Neutral in between</li>
<li>BUY: prior OB and today Neutral · SELL: today OB · next-open fill</li>
<li>IS &lt; 2024-01-01 · OOS ≥ 2024-01-01 (report-only)</li>
<li>$10,000 / trade · $500,000 overlay account · costs 0</li>
<li>Sentiment columns on house Closed files: <code>RSI14_OB_OS</code> from trigger; <code>RSI14_AT_ENTRY</code> still fill bar</li>
</ul>
<p class="caveat">This is a research candidate, not a DailyRun system. Same-day Neutral-after-OB that skips straight
to Oversold is <em>not</em> a buy. Open trades at the last bar are marked EOD at the last close.</p>
</body>
{SORT_JS}
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_trades_csv(path: Path, trades: list[dict]) -> None:
    rows = []
    for t in trades:
        rows.append(
            {
                "SYMBOL": t["symbol"],
                "DATE_OPENED": _ymd(t["opened"]),
                "DATE_CLOSED": _ymd(t["closed"]),
                "SIGNAL_DATE": _ymd(t["signal_date"]),
                "ENTRY_PRICE": f"{t['entry']:.4f}",
                "EXIT_PRICE": f"{t['exit']:.4f}",
                "PNL_PCT": f"{t['pnl']:.4f}",
                "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                "DAYS_HELD": t["days"],
                "EXIT_TYPE": t["exit_type"],
                "RSI14_AT_TRIGGER": f"{t['rsi_trigger']:.2f}" if np.isfinite(t["rsi_trigger"]) else "",
                "RSI14_AT_EXIT": f"{t['rsi_exit']:.2f}" if np.isfinite(t["rsi_exit"]) else "",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> int:
    pt_syms = load_universe_csv(PAULTWENTY)
    if not pt_syms:
        print(f"ERROR missing PaulTwenty universe: {PAULTWENTY}", flush=True)
        return 1
    full_syms = list_full_universe()
    if not full_syms:
        print(f"ERROR no OHLC under {DATA_DIR}", flush=True)
        return 1

    pt = run_universe("PaulTwenty", pt_syms)
    full = run_universe("FullUniverse", full_syms)
    verdict = verdict_from_results(pt, full)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_trades_csv(OUT_DIR / "closed_paultwenty.csv", pt["trades"])
    write_trades_csv(OUT_DIR / "closed_fulluniv.csv", full["trades"])
    pd.DataFrame(pt["metas"]).to_csv(OUT_DIR / "per_symbol_paultwenty.csv", index=False)
    pd.DataFrame(full["metas"]).to_csv(OUT_DIR / "per_symbol_fulluniv.csv", index=False)
    if pt["port"] is not None and not pt["port"].empty:
        p = pt["port"].copy()
        p["Date"] = pd.to_datetime(p["Date"]).dt.strftime("%Y-%m-%d")
        p.to_csv(OUT_DIR / "daily_equity_paultwenty.csv", index=False)
    if full["port"] is not None and not full["port"].empty:
        p = full["port"].copy()
        p["Date"] = pd.to_datetime(p["Date"]).dt.strftime("%Y-%m-%d")
        p.to_csv(OUT_DIR / "daily_equity_fulluniv.csv", index=False)
    book_rows = []
    for u in (pt, full):
        for b in u["books"]:
            row = {"universe": u["name"], **b}
            book_rows.append(row)
    pd.DataFrame(book_rows).to_csv(OUT_DIR / "compare_book_metrics.csv", index=False)
    port_rows = []
    for u in (pt, full):
        for r in u["port_rows"]:
            port_rows.append({"universe": u["name"], **r})
    pd.DataFrame(port_rows).to_csv(OUT_DIR / "compare_port_metrics.csv", index=False)

    write_baseline(OUT_DIR / "BASELINE.md", pt, full)
    write_summary(OUT_DIR / "SUMMARY.md", pt, full, verdict)
    html_path = OUT_DIR / "compare.html"
    write_html(html_path, pt, full, verdict)

    print("\n=== BOOK FULL ===", flush=True)
    for u in (pt, full):
        b = next(x for x in u["books"] if x["slice"] == "FULL")
        print(
            f"  {u['name']}: N={b['n_trades']} WR={b['win_pct']:.2f} Avg%={b['avg_pnl_pct']:.3f} "
            f"PF={b['profit_factor']:.3f} AnnROR={b['ann_ror']:.2f} MaxDD={b['max_dd']:.2f}",
            flush=True,
        )
    print(f"\nVerdict: {verdict}", flush=True)
    print(f"HTML: {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
