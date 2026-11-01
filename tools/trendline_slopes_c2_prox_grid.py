#!/usr/bin/env python3
"""C2 one-knob proximity fine-tune — prox 2% / 3% / 4% / 5% (or subset).

Freeze from trendline_slopes_buylow_20260904 C2 ENTRY, vary only weekly-support
proximity X. Everything else frozen:

  ENTRY: monthly support UP + weekly support UP
         + |dist_pct to weekly support| <= X%
         + daily support turns UP (was not UP yesterday)
  EXIT:  next-open fill; time-stop 40 bars; or close below weekly support
  Universe: PaulTwenty (default) or --universe (e.g. ALL_ohlc)
  IS/OOS: opened < 2024-01-01 vs >= (OOS report-only)

Control / reference = prox2 (C2 baseline). Candidates = other prox arms.
Research-only — not gold, not DailyRun.

Usage:
  python tools/trendline_slopes_c2_prox_grid.py
  python tools/trendline_slopes_c2_prox_grid.py --prox 2,3,5 --universe drive/universes/ALL_ohlc_universe.csv \\
      --stamp trendline_slopes_c2_prox_fulluniv_20260905 --compute-slopes --workers 16
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    filter_html_compare_columns,
    format_money,
    overlay_ann_ror_max_dd,
)

DATA_DIR = ROOT / "data" / "newdata" / "data"
DRIVE = ROOT / "drive"
SLOPES_CSV = (
    DRIVE
    / "paul_experiments"
    / "trendline_slopes_paultwenty_20260831"
    / "trendline_slopes_long.csv"
)
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
ALL_OHLC = DRIVE / "universes" / "ALL_ohlc_universe.csv"
PRIOR_STAMP = "trendline_slopes_buylow_20260904"
STAMP = "trendline_slopes_c2_prox_grid_20260904"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
UNIVERSE_PATH = PAULTWENTY
UNIVERSE_LABEL = "`drive/universes/PaulTwenty_universe.csv`"
LINE_BOOK_LABEL = "`trendline_slopes_paultwenty_20260831/trendline_slopes_long.csv`"
IS_CUT = date(2024, 1, 1)
TIME_STOP_BARS = 40
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
MIN_PRICE = 5.0
MIN_ADV20 = 500_000.0
MIN_DAILY_BARS = 400
PROX_GRID = (2.0, 3.0, 4.0, 5.0)
CONTROL_PROX = 2.0

# Arm definitions: (arm_id, label, prox_pct) — rebuilt by configure()
ARMS: list[tuple[str, str, float]] = []
CONTROL_ARM = f"C2_prox{int(CONTROL_PROX)}"


def _rebuild_arms() -> None:
    global ARMS, CONTROL_ARM
    ARMS = [
        (f"C2_prox{int(x)}", f"C2 — M+W UP + prox≤{int(x)}% + D turns UP", x)
        for x in PROX_GRID
    ]
    CONTROL_ARM = f"C2_prox{int(CONTROL_PROX)}"


_rebuild_arms()


def configure(
    *,
    stamp: str,
    universe: Path,
    prox: tuple[float, ...],
    slopes_csv: Optional[Path],
    line_book_label: str,
) -> None:
    global STAMP, OUT_DIR, UNIVERSE_PATH, UNIVERSE_LABEL, LINE_BOOK_LABEL
    global SLOPES_CSV, PROX_GRID
    STAMP = stamp
    OUT_DIR = DRIVE / "paul_experiments" / STAMP
    UNIVERSE_PATH = universe
    try:
        rel = universe.resolve().relative_to(ROOT.resolve())
        UNIVERSE_LABEL = f"`{rel.as_posix()}`"
    except ValueError:
        UNIVERSE_LABEL = f"`{universe}`"
    LINE_BOOK_LABEL = line_book_label
    if slopes_csv is not None:
        SLOPES_CSV = slopes_csv
    PROX_GRID = prox
    _rebuild_arms()


def prox_list_str() -> str:
    return " / ".join(str(int(x)) for x in PROX_GRID)

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 78rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
.up { color: #047857; font-weight: 600; }
.down { color: #b91c1c; font-weight: 600; }
.hold { color: #b45309; font-weight: 600; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .88rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .35rem .55rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.total-row { font-weight: 700; background: #f8fafc; }
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


def load_universe(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.append(s.split(",")[0].strip())
    return out


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    need = ("date", "open", "high", "low", "close")
    if not all(k in cols for k in need):
        return None
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]]).dt.date,
            "Open": df[cols["open"]].astype(float),
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": df[cols["close"]].astype(float),
        }
    )
    if "volume" in cols:
        out["Volume"] = df[cols["volume"]].astype(float)
    else:
        out["Volume"] = np.nan
    return out.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)


def load_slopes() -> pd.DataFrame:
    usecols = [
        "symbol",
        "date",
        "timeframe",
        "side",
        "direction",
        "dist_pct",
        "line_price_at_asof",
        "close",
    ]
    df = pd.read_csv(SLOPES_CSV, usecols=usecols)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["symbol"] = df["symbol"].astype(str).str.upper()
    return df


def slopes_frame_from_rows(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "date",
                "timeframe",
                "side",
                "direction",
                "dist_pct",
                "line_price_at_asof",
                "close",
            ]
        )
    df = pd.DataFrame(rows)
    keep = [
        "symbol",
        "date",
        "timeframe",
        "side",
        "direction",
        "dist_pct",
        "line_price_at_asof",
        "close",
    ]
    df = df[keep].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["symbol"] = df["symbol"].astype(str).str.upper()
    return df


def _worker_compute_sym(
    sym: str, prox_grid: tuple[float, ...]
) -> tuple[str, list[dict], dict[str, int], str]:
    """Process-pool worker: slopes → C2 trades (no multi-GB long book)."""
    # Local imports for Windows spawn
    sys.path.insert(0, str(ROOT / "tools"))
    from trendline_slopes_paultwenty import load_ohlc as _load_ohlc  # noqa: WPS433
    from trendline_slopes_paultwenty import rows_for_symbol  # noqa: WPS433

    ohlc = _load_ohlc(sym)
    if ohlc is None or len(ohlc) < MIN_DAILY_BARS + 50:
        return sym, [], {}, "short_ohlc"
    rows = rows_for_symbol(sym, ohlc)
    g = slopes_frame_from_rows(rows)
    if g.empty:
        return sym, [], {}, "no_slopes"
    wide = wide_for_symbol(g)
    if wide.empty:
        return sym, [], {}, "no_wide"
    wide = add_signals(wide, prox_grid=prox_grid)
    trades: list[dict] = []
    events: dict[str, int] = {}
    for x in prox_grid:
        arm_id = f"C2_prox{int(x)}"
        edge = f"sig_{arm_id}_edge"
        if edge not in wide.columns:
            continue
        events[arm_id] = int(wide[edge].fillna(False).sum())
        trades.extend(simulate_arm(ohlc, wide, sym, arm_id, edge))
    return sym, trades, events, "ok"


def wide_for_symbol(g: pd.DataFrame) -> pd.DataFrame:
    """One row per date with M/W/D support dirs + dist + line px + C2 prox signals."""
    g = g.copy()
    g["_key"] = g["timeframe"] + "_" + g["side"]
    want = {
        "daily_support",
        "daily_resistance",
        "weekly_support",
        "monthly_support",
    }
    keep = g[g["_key"].isin(want)]
    if keep.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for d, sg in keep.groupby("date", sort=True):
        rec: dict[str, Any] = {"date": d, "close": float(sg["close"].iloc[0])}
        for _, r in sg.iterrows():
            k = r["_key"]
            rec[f"{k}_dir"] = r["direction"]
            rec[f"{k}_dist"] = float(r["dist_pct"]) if pd.notna(r["dist_pct"]) else float("nan")
            rec[f"{k}_px"] = (
                float(r["line_price_at_asof"])
                if pd.notna(r["line_price_at_asof"])
                else float("nan")
            )
        rows.append(rec)
    w = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return add_signals(w)


def add_signals(
    w: pd.DataFrame, prox_grid: Optional[tuple[float, ...]] = None
) -> pd.DataFrame:
    grid = prox_grid if prox_grid is not None else PROX_GRID
    for c in (
        "daily_support_dir",
        "daily_resistance_dir",
        "weekly_support_dir",
        "monthly_support_dir",
        "weekly_support_dist",
        "weekly_support_px",
    ):
        if c not in w.columns:
            w[c] = np.nan if c.endswith(("_dist", "_px")) else ""

    m_up = w["monthly_support_dir"] == "UP"
    w_up = w["weekly_support_dir"] == "UP"
    d_up = w["daily_support_dir"] == "UP"
    dist = pd.to_numeric(w["weekly_support_dist"], errors="coerce")
    d_prev = w["daily_support_dir"].shift(1)
    d_turn_up = d_up & (d_prev.notna()) & (d_prev != "UP")
    have_mw = m_up & w_up & w["monthly_support_dir"].notna() & w["weekly_support_dir"].notna()

    for x in grid:
        arm = f"C2_prox{int(x)}"
        prox = dist.abs() <= float(x)
        # C2 is turn-up by construction — signal == edge
        sig = have_mw & prox & dist.notna() & d_turn_up
        w[f"sig_{arm}"] = sig
        w[f"sig_{arm}_edge"] = sig
    return w


def _f(x: Any) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def simulate_arm(
    ohlc: pd.DataFrame,
    wide: pd.DataFrame,
    sym: str,
    arm: str,
    sig_col: str,
) -> list[dict[str, Any]]:
    m = ohlc.merge(wide, left_on="Date", right_on="date", how="left")
    if "Volume" in m.columns:
        adv20 = m["Volume"].astype(float).rolling(20, min_periods=20).mean().to_numpy()
    else:
        adv20 = np.full(len(m), np.nan)
    n = len(m)
    trades: list[dict[str, Any]] = []
    i = max(MIN_DAILY_BARS, 21)
    while i < n - 2:
        row = m.iloc[i]
        if not bool(row.get(sig_col)):
            i += 1
            continue
        c = float(row["Close"])
        if c < MIN_PRICE:
            i += 1
            continue
        adv = float(adv20[i]) if math.isfinite(float(adv20[i])) else 0.0
        if adv < MIN_ADV20:
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n:
            break
        entry = float(m.iloc[entry_i]["Open"])
        if entry <= 0 or not math.isfinite(entry):
            i += 1
            continue
        opened = m.iloc[entry_i]["Date"]
        exit_i = None
        exit_type = "TIME"
        last = min(n - 1, entry_i + TIME_STOP_BARS)
        for j in range(entry_i, last + 1):
            if j == entry_i:
                continue
            ws_px = m.iloc[j].get("weekly_support_px")
            close_j = float(m.iloc[j]["Close"])
            if (
                ws_px is not None
                and math.isfinite(float(ws_px))
                and float(ws_px) > 0
                and close_j < float(ws_px)
            ):
                exit_i = j
                exit_type = "STOP_WSUP"
                break
        if exit_i is None:
            exit_i = last
            exit_type = "TIME" if (exit_i - entry_i) >= TIME_STOP_BARS else "EOD"
        fill = float(m.iloc[exit_i]["Close"])
        pnl_pct = (fill / entry - 1.0) * 100.0
        days = (m.iloc[exit_i]["Date"] - opened).days
        trades.append(
            {
                "arm": arm,
                "symbol": sym,
                "signal_date": row["Date"],
                "opened": opened,
                "closed": m.iloc[exit_i]["Date"],
                "entry": entry,
                "exit": fill,
                "pnl": pnl_pct,
                "pnl_d": SHEET * (pnl_pct / 100.0),
                "days": days,
                "bars": int(exit_i - entry_i),
                "exit_type": exit_type,
                "m_dir": row.get("monthly_support_dir") or "",
                "w_dir": row.get("weekly_support_dir") or "",
                "d_dir": row.get("daily_support_dir") or "",
                "w_dist": _f(row.get("weekly_support_dist")),
                "close_signal": c,
            }
        )
        i = exit_i + 1
    return trades


def slice_trades(trades: list[dict], *, oos: bool | None) -> list[dict]:
    if oos is None:
        return trades
    out = []
    for t in trades:
        d = t["opened"]
        if isinstance(d, pd.Timestamp):
            d = d.date()
        is_oos = d >= IS_CUT
        if oos and is_oos:
            out.append(t)
        elif (not oos) and (not is_oos):
            out.append(t)
    return out


def book_metrics(trades: list[dict], label: str) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "slice": label,
        "n": 0,
        "wins": 0,
        "losses": 0,
        "win_pct": float("nan"),
        "avg_pnl_pct": float("nan"),
        "avg_pnl_pct_wo_max": float("nan"),
        "avg_win_pct": float("nan"),
        "avg_loss_pct": float("nan"),
        "expectancy_pct": float("nan"),
        "pf": float("nan"),
        "avg_days": float("nan"),
        "median_days": float("nan"),
        "p90_days": float("nan"),
        "capital_days": 0.0,
        "profit_per_cap_day": float("nan"),
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "exit_stop": 0,
        "exit_time": 0,
        "trades_per_year": float("nan"),
        "pnl_d_sum": 0.0,
    }
    if n == 0:
        return empty
    pnls = np.array([float(t["pnl"]) for t in trades], dtype=float)
    days = np.array([float(t["days"]) for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    wo = np.sort(pnls)
    avg_wo = float(wo[:-1].mean()) if n > 1 else float(pnls.mean())
    gp = float(wins.sum()) if len(wins) else 0.0
    gl = float(-losses.sum()) if len(losses) else 0.0
    ov = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT_ACCT)
    opened = [t["opened"] for t in trades]
    span_days = (max(opened) - min(opened)).days if n else 0
    tpy = n / (span_days / 365.25) if span_days > 0 else float("nan")
    cap_days = float(ov.get("capital_days") or days.sum())
    pnl_d_sum = float(sum(float(t["pnl_d"]) for t in trades))
    return {
        "slice": label,
        "n": n,
        "wins": int((pnls > 0).sum()),
        "losses": int((pnls <= 0).sum()),
        "win_pct": float((pnls > 0).mean() * 100.0),
        "avg_pnl_pct": float(pnls.mean()),
        "avg_pnl_pct_wo_max": avg_wo,
        "avg_win_pct": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss_pct": float(losses.mean()) if len(losses) else float("nan"),
        "expectancy_pct": float(pnls.mean()),
        "pf": (gp / gl) if gl > 0 else float("nan"),
        "avg_days": float(days.mean()),
        "median_days": float(np.median(days)),
        "p90_days": float(np.percentile(days, 90)),
        "capital_days": cap_days,
        "profit_per_cap_day": (pnl_d_sum / cap_days) if cap_days > 0 else float("nan"),
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "exit_stop": sum(1 for t in trades if t["exit_type"] == "STOP_WSUP"),
        "exit_time": sum(1 for t in trades if t["exit_type"] == "TIME"),
        "trades_per_year": tpy,
        "pnl_d_sum": pnl_d_sum,
    }


def fmt_pct(x: Any, d: int = 2) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{d}f}%"


def fmt_num(x: Any, d: int = 2) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{d}f}"


def fmt_delta(x: Any, d: int = 2, suffix: str = "") -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return "—"
    sign = "+" if float(x) > 0 else ""
    return f"{sign}{float(x):.{d}f}{suffix}"


def td_cls(x: Any) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return ""
    if float(x) > 0:
        return "up"
    if float(x) < 0:
        return "down"
    return ""


def decide_verdict(cand: dict, ctrl: dict, name: str) -> dict[str, str]:
    """Research KEEP / HOLD / DISMISS on quality (Avg PnL %, WR, PF) without collapsing N."""
    cn, kn = int(cand.get("n") or 0), int(ctrl.get("n") or 0)
    if cn < 25:
        return {
            "hypothesis": name,
            "verdict": "HOLD",
            "reason": f"Too few candidate trades (N={cn}<25) for KEEP/DISMISS.",
        }
    c_avg, k_avg = cand.get("avg_pnl_pct"), ctrl.get("avg_pnl_pct")
    c_wr, k_wr = cand.get("win_pct"), ctrl.get("win_pct")
    c_pf, k_pf = cand.get("pf"), ctrl.get("pf")
    if not all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in (c_avg, k_avg)):
        return {"hypothesis": name, "verdict": "HOLD", "reason": "Missing Avg PnL %."}
    better_avg = float(c_avg) > float(k_avg) + 0.15
    worse_avg = float(c_avg) < float(k_avg) - 0.15
    wr_ok = True
    if isinstance(c_wr, (int, float)) and isinstance(k_wr, (int, float)):
        wr_ok = float(c_wr) >= float(k_wr) - 2.0
    pf_ok = True
    if isinstance(c_pf, (int, float)) and isinstance(k_pf, (int, float)) and math.isfinite(float(k_pf)):
        pf_ok = float(c_pf) >= float(k_pf) * 0.95
    n_ok = cn >= max(25, int(0.15 * kn)) if kn > 0 else True
    if better_avg and wr_ok and pf_ok and n_ok:
        return {
            "hypothesis": name,
            "verdict": "LEAN KEEP",
            "reason": (
                f"Full-book Avg PnL % {c_avg:.2f} vs prox2 {k_avg:.2f}; "
                f"WR {c_wr:.1f}% vs {k_wr:.1f}%; N={cn}. Research-only — not gold."
            ),
        }
    if worse_avg and (
        not wr_ok
        or (
            isinstance(c_pf, float)
            and isinstance(k_pf, float)
            and math.isfinite(c_pf)
            and math.isfinite(k_pf)
            and c_pf < k_pf * 0.9
        )
    ):
        return {
            "hypothesis": name,
            "verdict": "DISMISS",
            "reason": (
                f"Quality worse: Avg PnL % {c_avg:.2f} vs prox2 {k_avg:.2f}; "
                f"WR {c_wr:.1f}% vs {k_wr:.1f}%; N={cn}."
            ),
        }
    return {
        "hypothesis": name,
        "verdict": "HOLD",
        "reason": (
            f"Flat / mixed vs prox2 (Avg {c_avg:.2f} vs {k_avg:.2f}, "
            f"WR {c_wr:.1f}% vs {k_wr:.1f}%, N={cn}). No OOS retune."
        ),
    }


def metrics_table(rows: list[dict], title: str) -> str:
    cols = filter_html_compare_columns(
        [
            ("slice", "text"),
            ("N", "num"),
            ("Win %", "num"),
            ("Avg PnL %", "num"),
            ("AVG_PNL_PCT_WO_MAX", "num"),
            ("Avg win %", "num"),
            ("Avg loss %", "num"),
            ("Expectancy %", "num"),
            ("PF", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Calmar", "num"),
            ("Profit / cap day", "num"),
            ("Capital days", "num"),
            ("Avg days", "num"),
            ("Median days", "num"),
            ("P90 days", "num"),
            ("Trades/year", "num"),
            ("STOP_WSUP", "num"),
            ("TIME", "num"),
        ]
    )
    head = "".join(sortable_th(a, b) for a, b in cols)
    body = []
    for r in rows:
        cells = {
            "slice": html_mod.escape(str(r["slice"])),
            "N": str(r["n"]),
            "Win %": fmt_pct(r["win_pct"]),
            "Avg PnL %": fmt_pct(r["avg_pnl_pct"]),
            "AVG_PNL_PCT_WO_MAX": fmt_pct(r["avg_pnl_pct_wo_max"]),
            "Avg win %": fmt_pct(r["avg_win_pct"]),
            "Avg loss %": fmt_pct(r["avg_loss_pct"]),
            "Expectancy %": fmt_pct(r["expectancy_pct"]),
            "PF": fmt_num(r["pf"]),
            "Ann ROR %": fmt_pct(r["ann_ror"]),
            "Max DD %": fmt_pct(r["max_dd"]),
            "Calmar": fmt_num(r["calmar"]),
            "Profit / cap day": format_money(r.get("profit_per_cap_day")),
            "Capital days": fmt_num(r["capital_days"], 0),
            "Avg days": fmt_num(r["avg_days"], 1),
            "Median days": fmt_num(r["median_days"], 1),
            "P90 days": fmt_num(r["p90_days"], 1),
            "Trades/year": fmt_num(r["trades_per_year"], 2),
            "STOP_WSUP": str(r["exit_stop"]),
            "TIME": str(r["exit_time"]),
        }
        tds = []
        for lab, _ in cols:
            raw = {
                "Avg PnL %": r["avg_pnl_pct"],
                "Win %": r["win_pct"],
                "Expectancy %": r["expectancy_pct"],
                "Ann ROR %": r["ann_ror"],
            }.get(lab)
            cls = td_cls(raw)
            tds.append(f'<td class="{cls}">{cells[lab]}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        f"<h2>{html_mod.escape(title)}</h2>"
        "<p class='meta'>Click column headers to sort.</p>"
        f"<table class='sortable'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def delta_table(rows: list[dict], title: str) -> str:
    """IS quality vs prox2 control with absolute + delta columns."""
    cols = [
        ("arm", "text"),
        ("N", "num"),
        ("ΔN", "num"),
        ("Win %", "num"),
        ("ΔWR pp", "num"),
        ("Avg PnL %", "num"),
        ("ΔAvg pp", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("PF", "num"),
        ("ΔPF", "num"),
        ("Expectancy %", "num"),
        ("Ann ROR %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Profit / cap day", "num"),
        ("Avg days", "num"),
        ("Trades/year", "num"),
        ("Verdict", "text"),
    ]
    head = "".join(sortable_th(a, b) for a, b in cols)
    body = []
    for r in rows:
        tds = [
            f"<td>{html_mod.escape(str(r['arm']))}</td>",
            f"<td>{r['n']}</td>",
            f"<td class='{td_cls(r.get('d_n'))}'>{fmt_delta(r.get('d_n'), 0)}</td>",
            f"<td class='{td_cls(r.get('win_pct'))}'>{fmt_pct(r.get('win_pct'))}</td>",
            f"<td class='{td_cls(r.get('d_wr'))}'>{fmt_delta(r.get('d_wr'), 2, ' pp')}</td>",
            f"<td class='{td_cls(r.get('avg_pnl_pct'))}'>{fmt_pct(r.get('avg_pnl_pct'))}</td>",
            f"<td class='{td_cls(r.get('d_avg'))}'>{fmt_delta(r.get('d_avg'), 2, ' pp')}</td>",
            f"<td>{fmt_pct(r.get('avg_pnl_pct_wo_max'))}</td>",
            f"<td>{fmt_num(r.get('pf'))}</td>",
            f"<td class='{td_cls(r.get('d_pf'))}'>{fmt_delta(r.get('d_pf'))}</td>",
            f"<td class='{td_cls(r.get('expectancy_pct'))}'>{fmt_pct(r.get('expectancy_pct'))}</td>",
            f"<td class='{td_cls(r.get('ann_ror'))}'>{fmt_pct(r.get('ann_ror'))}</td>",
            f"<td>{fmt_pct(r.get('max_dd'))}</td>",
            f"<td>{fmt_num(r.get('calmar'))}</td>",
            f"<td>{format_money(r.get('profit_per_cap_day'))}</td>",
            f"<td>{fmt_num(r.get('avg_days'), 1)}</td>",
            f"<td>{fmt_num(r.get('trades_per_year'), 2)}</td>",
            f"<td class='{r.get('vcls', '')}'>{html_mod.escape(str(r.get('verdict', '')))}</td>",
        ]
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        f"<h2>{html_mod.escape(title)}</h2>"
        "<p class='meta'>Click column headers to sort. Deltas vs prox2 control on the same slice.</p>"
        f"<table class='sortable'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def write_docs(
    verdicts: list[dict],
    event_counts: dict[str, int],
    books_by_arm_slice: dict[str, dict[str, dict]],
) -> None:
    prox_set = "{" + ",".join(str(int(x)) for x in PROX_GRID) + "}"
    prox_pct = ", ".join(f"{int(x)}%" for x in PROX_GRID)
    hyp = f"""# HYPOTHESIS — {STAMP}

| Field | Fill in |
|-------|---------|
| System / prefix | Trendline slopes C2 (fractal M/W/D support) |
| Prior stamp | `{PRIOR_STAMP}` (C2 baseline prox≤2%) / PaulTwenty grid `trendline_slopes_c2_prox_grid_20260904` |
| Universe | {UNIVERSE_LABEL} |
| **Evidence** | C2 entry quality may be sensitive to weekly-support proximity band |
| **Hypothesis** | Widening proximity X across {prox_pct} improves (or preserves) C2 quality vs prox2 |
| **Single knob** | Proximity X (`\\|dist_pct\\| ≤ X%` to upward weekly support) |
| Frozen settings | C2 ENTRY otherwise; next_open; time_stop {TIME_STOP_BARS}; exit close < weekly support; sheet $45k; MIN_PRICE 5; MIN_ADV20 500k; IS cut 2024-01-01 |
| Decision | research-only; no gold / DailyRun |

Acronyms: TF = timeframe. Support = last two confirmed swing lows. M/W/D = monthly / weekly / daily. C2 = M+W support UP + proximity + daily support turns UP.
"""
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "Research-only **one-knob** C2 proximity grid on fractal trendline slopes.",
        f"Delta from prior `{PRIOR_STAMP}` / PaulTwenty C2 grid: freeze C2 ENTRY/EXIT; vary only weekly-support proximity X ∈ {prox_set}%.",
        "",
        "## Freeze",
        "",
        "| Knob | Value |",
        "|------|-------|",
        f"| Universe | {UNIVERSE_LABEL} |",
        f"| Line book | {LINE_BOOK_LABEL} |",
        "| Algorithm | Fractal last-two swings; daily k=5, weekly W-FRI k=3, monthly ME k=2 |",
        "| Look-ahead | Confirmed pivots only (inherited from slope book / on-the-fly compute) |",
        "| ENTRY | Monthly support UP + weekly support UP + `|dist_pct| ≤ X%` to weekly support + daily support turns UP |",
        f"| **Knob under test** | Proximity X ∈ {{{prox_pct}}} |",
        "| Control / reference | prox2 (C2 baseline from prior stamp) |",
        "| Signal style | C2 turn-up by construction (edge = signal) |",
        "| Entry fill | Next open |",
        f"| Exit | First of: daily close below weekly support, or {TIME_STOP_BARS} bars |",
        f"| Sheet / initial | ${SHEET:,.0f} / ${INIT_ACCT:,.0f} |",
        "| IS / OOS | opened < 2024-01-01 / opened >= 2024-01-01 (OOS report-only) |",
        "| Costs | 0 |",
        "",
        "## Arms",
        "",
        "| Arm | Definition |",
        "|-----|------------|",
    ]
    for arm_id, label, x in ARMS:
        tag = " **(control)**" if arm_id == CONTROL_ARM else ""
        lines.append(f"| {arm_id} | {label}{tag} |")
    lines += [
        "",
        "## Event counts (C2 turn-up days, pre-liquidity filter in sim)",
        "",
    ]
    for k, v in event_counts.items():
        lines.append(f"- `{k}`: {v}")
    lines += [
        "",
        "## IS quality vs prox2 (report)",
        "",
        "| Arm | N | Avg PnL % | WR % | PF | ΔAvg vs prox2 |",
        "|-----|---|-----------|------|----|---------------|",
    ]
    ctrl_is = books_by_arm_slice.get(CONTROL_ARM, {}).get("IS", {})
    k_avg = ctrl_is.get("avg_pnl_pct")
    for arm_id, _label, _x in ARMS:
        m = books_by_arm_slice.get(arm_id, {}).get("IS", {})
        d_avg = (
            float(m["avg_pnl_pct"]) - float(k_avg)
            if isinstance(m.get("avg_pnl_pct"), (int, float))
            and isinstance(k_avg, (int, float))
            and math.isfinite(float(m["avg_pnl_pct"]))
            and math.isfinite(float(k_avg))
            else float("nan")
        )
        lines.append(
            f"| {arm_id} | {m.get('n', 0)} | {fmt_pct(m.get('avg_pnl_pct'))} | "
            f"{fmt_pct(m.get('win_pct'))} | {fmt_num(m.get('pf'))} | {fmt_delta(d_avg, 2, ' pp')} |"
        )
    lines += [
        "",
        "## Selection / verdicts (research-only)",
        "",
        "Judged on **full-book** quality vs prox2 control. OOS is report-only — do not retune.",
        "Selection among prox arms on the same history is in-sample; stamp labeled research-only.",
        "",
        "| Hypothesis | Verdict | Reason |",
        "|------------|---------|--------|",
    ]
    for v in verdicts:
        lines.append(f"| {v['hypothesis']} | **{v['verdict']}** | {v['reason']} |")
    lines += [
        "",
        "## Scope",
        "",
        "Not gold. Not DailyRun. Toy exit (time 40 + weekly-support giveback).",
        "Fine-tune #1 for C2 only — one knob (proximity).",
        "",
    ]
    summary = [
        f"# SUMMARY — {STAMP}",
        "",
        f"C2 proximity grid ({prox_list_str().replace(' / ', '/')}%) — {UNIVERSE_LABEL}, "
        "frozen exit (next-open / time 40 / stop weekly support).",
        "",
        "## Verdicts",
        "",
    ]
    for v in verdicts:
        summary.append(f"- **{v['verdict']}** — {v['hypothesis']}: {v['reason']}")
    summary += [
        "",
        "## N per arm (FULL)",
        "",
    ]
    for arm_id, _label, _x in ARMS:
        m = books_by_arm_slice.get(arm_id, {}).get("FULL", {})
        summary.append(f"- `{arm_id}`: N={m.get('n', 0)}")
    summary += [
        "",
        "## IS vs prox2 (Avg / WR / PF)",
        "",
    ]
    for arm_id, _label, _x in ARMS:
        m = books_by_arm_slice.get(arm_id, {}).get("IS", {})
        d_avg = (
            float(m["avg_pnl_pct"]) - float(k_avg)
            if isinstance(m.get("avg_pnl_pct"), (int, float))
            and isinstance(k_avg, (int, float))
            and math.isfinite(float(m["avg_pnl_pct"]))
            and math.isfinite(float(k_avg))
            else float("nan")
        )
        summary.append(
            f"- `{arm_id}` IS: N={m.get('n', 0)}, Avg {fmt_pct(m.get('avg_pnl_pct'))}, "
            f"WR {fmt_pct(m.get('win_pct'))}, PF {fmt_num(m.get('pf'))}, "
            f"ΔAvg {fmt_delta(d_avg, 2, ' pp')}"
        )
    summary += [
        "",
        "Research-only. OOS report-only — do not retune. Not gold / not DailyRun.",
        "",
        f"HTML: `drive/paul_experiments/{STAMP}/compare.html`",
        "",
    ]
    (OUT_DIR / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def write_html(
    *,
    books: list[dict],
    delta_is: list[dict],
    delta_full: list[dict],
    verdicts: list[dict],
    trades: pd.DataFrame,
) -> Path:
    book_html = metrics_table(books, "Book — arms (full / IS / OOS)")
    d_is_html = delta_table(delta_is, "IS quality vs prox2 (control)")
    d_full_html = delta_table(delta_full, "FULL book vs prox2 (control)")

    vcls = {"LEAN KEEP": "up", "KEEP": "up", "DISMISS": "down", "HOLD": "hold"}
    vb = []
    for v in verdicts:
        cls = vcls.get(v["verdict"], "")
        vb.append(
            "<tr>"
            f"<td>{html_mod.escape(v['hypothesis'])}</td>"
            f"<td class='{cls}'>{html_mod.escape(v['verdict'])}</td>"
            f"<td>{html_mod.escape(v['reason'])}</td>"
            "</tr>"
        )
    verd_html = (
        "<h2>Research verdicts</h2>"
        "<p class='meta'>Click column headers to sort. Not gold / not DailyRun. "
        "Full-book primary; OOS soften → HOLD.</p>"
        "<table class='sortable'><thead><tr>"
        + sortable_th("Hypothesis", "text")
        + sortable_th("Verdict", "text")
        + sortable_th("Reason", "text")
        + "</tr></thead><tbody>"
        + "".join(vb)
        + "</tbody></table>"
    )

    tcols = [
        ("arm", "text"),
        ("symbol", "text"),
        ("signal", "date"),
        ("opened", "date"),
        ("closed", "date"),
        ("pnl %", "num"),
        ("days", "num"),
        ("exit", "text"),
        ("w_dist %", "num"),
        ("M", "text"),
        ("W", "text"),
        ("D", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in tcols)
    show = trades.sort_values(["arm", "opened"]).head(800) if len(trades) else trades
    tb = []
    for _, r in show.iterrows():
        tb.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r['arm']))}</td>"
            f"<td>{html_mod.escape(str(r['symbol']))}</td>"
            f"<td>{r['signal_date']}</td>"
            f"<td>{r['opened']}</td>"
            f"<td>{r['closed']}</td>"
            f"<td class='{td_cls(r['pnl'])}'>{fmt_pct(r['pnl'])}</td>"
            f"<td>{int(r['days'])}</td>"
            f"<td>{html_mod.escape(str(r['exit_type']))}</td>"
            f"<td>{fmt_num(r.get('w_dist'))}</td>"
            f"<td>{html_mod.escape(str(r.get('m_dir') or ''))}</td>"
            f"<td>{html_mod.escape(str(r.get('w_dir') or ''))}</td>"
            f"<td>{html_mod.escape(str(r.get('d_dir') or ''))}</td>"
            "</tr>"
        )
    trade_html = (
        f"<h2>Trades (first {len(show)} of {len(trades)})</h2>"
        "<p class='meta'>Click column headers to sort. Full book in CSV.</p>"
        f"<table class='sortable'><thead><tr>{th}</tr></thead><tbody>{''.join(tb)}</tbody></table>"
    )

    insight_items = "".join(
        f"<li><span class='{vcls.get(v['verdict'], '')}'><strong>{html_mod.escape(v['verdict'])}</strong></span> "
        f"— {html_mod.escape(v['hypothesis'])}: {html_mod.escape(v['reason'])}</li>"
        for v in verdicts
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>C2 proximity grid — {STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>Trendline slopes C2 — proximity grid ({html_mod.escape(prox_list_str())}%)</h1>
<p class="meta">Stamp <span class="badge">{html_mod.escape(STAMP)}</span> · {html_mod.escape(UNIVERSE_LABEL)} ·
prior <code>{PRIOR_STAMP}</code> · one-knob ENTRY proximity ·
exit time {TIME_STOP_BARS} / stop weekly support ·
IS cut 2024-01-01. Research only — not gold, not DailyRun. Click column headers to sort.</p>
<div class="insight">
<strong>Plain-English takeaways</strong>
<ul>{insight_items}</ul>
</div>
<p class="caveat"><strong>Caveats:</strong> Fractal last-two-swing lines (look-ahead-safe confirmation).
C2 = M+W UP + prox band + daily support turns UP. Toy exit. OOS is report-only — do not retune on OOS.
Selecting among prox arms after seeing the table is in-sample selection — research-only.</p>
{verd_html}
{d_is_html}
{d_full_html}
{book_html}
{trade_html}
{SORT_JS}
</body>
</html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def build_delta_rows(
    by_arm: dict[str, list[dict]],
    *,
    oos: bool | None,
    verdict_map: dict[str, str],
) -> list[dict]:
    vcls_map = {"LEAN KEEP": "up", "KEEP": "up", "DISMISS": "down", "HOLD": "hold"}
    ctrl = book_metrics(slice_trades(by_arm[CONTROL_ARM], oos=oos), CONTROL_ARM)
    rows = []
    for arm_id, label, _x in ARMS:
        m = book_metrics(slice_trades(by_arm[arm_id], oos=oos), arm_id)
        d_avg = (
            float(m["avg_pnl_pct"]) - float(ctrl["avg_pnl_pct"])
            if math.isfinite(float(m.get("avg_pnl_pct") or float("nan")))
            and math.isfinite(float(ctrl.get("avg_pnl_pct") or float("nan")))
            else float("nan")
        )
        d_wr = (
            float(m["win_pct"]) - float(ctrl["win_pct"])
            if math.isfinite(float(m.get("win_pct") or float("nan")))
            and math.isfinite(float(ctrl.get("win_pct") or float("nan")))
            else float("nan")
        )
        d_pf = (
            float(m["pf"]) - float(ctrl["pf"])
            if math.isfinite(float(m.get("pf") or float("nan")))
            and math.isfinite(float(ctrl.get("pf") or float("nan")))
            else float("nan")
        )
        verd = "control" if arm_id == CONTROL_ARM else verdict_map.get(arm_id, "")
        rows.append(
            {
                "arm": f"{arm_id}" + (" (control)" if arm_id == CONTROL_ARM else ""),
                "n": m["n"],
                "d_n": int(m["n"]) - int(ctrl["n"]),
                "win_pct": m["win_pct"],
                "d_wr": d_wr,
                "avg_pnl_pct": m["avg_pnl_pct"],
                "d_avg": d_avg,
                "avg_pnl_pct_wo_max": m["avg_pnl_pct_wo_max"],
                "pf": m["pf"],
                "d_pf": d_pf,
                "expectancy_pct": m["expectancy_pct"],
                "ann_ror": m["ann_ror"],
                "max_dd": m["max_dd"],
                "calmar": m["calmar"],
                "profit_per_cap_day": m["profit_per_cap_day"],
                "avg_days": m["avg_days"],
                "trades_per_year": m["trades_per_year"],
                "verdict": verd,
                "vcls": "" if arm_id == CONTROL_ARM else vcls_map.get(verd, ""),
                "_label": label,
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=STAMP)
    ap.add_argument("--universe", type=Path, default=PAULTWENTY)
    ap.add_argument(
        "--prox",
        default="2,3,4,5",
        help="Comma-separated proximity %% arms (default 2,3,4,5)",
    )
    ap.add_argument(
        "--slopes",
        type=Path,
        default=None,
        help="Optional prebuilt trendline_slopes_long.csv (ignored if --compute-slopes)",
    )
    ap.add_argument(
        "--compute-slopes",
        action="store_true",
        help="Compute fractal slopes on the fly (no multi-GB long CSV). Required for full univ.",
    )
    ap.add_argument("--workers", type=int, default=1, help="Process workers for --compute-slopes")
    ap.add_argument("--limit", type=int, default=0, help="Debug: first N symbols only")
    args = ap.parse_args()

    prox = tuple(float(x.strip()) for x in str(args.prox).split(",") if x.strip())
    if not prox:
        print("Empty --prox", file=sys.stderr)
        return 1
    if CONTROL_PROX not in prox:
        print(f"Control prox {CONTROL_PROX} must be in --prox", file=sys.stderr)
        return 1

    compute = bool(args.compute_slopes)
    if args.universe.resolve() != PAULTWENTY.resolve() and args.slopes is None:
        compute = True
    if args.slopes is not None and not args.compute_slopes:
        compute = False

    if compute:
        line_book = (
            "on-the-fly via `trendline_slopes_paultwenty.rows_for_symbol` "
            "(same algo as PaulTwenty long book; full long CSV not stored — multi-GB)"
        )
        slopes_path = None
    else:
        slopes_path = args.slopes or SLOPES_CSV
        try:
            rel = slopes_path.resolve().relative_to(ROOT.resolve())
            line_book = f"`{rel.as_posix()}`"
        except ValueError:
            line_book = f"`{slopes_path}`"

    configure(
        stamp=args.stamp,
        universe=args.universe,
        prox=prox,
        slopes_csv=slopes_path,
        line_book_label=line_book,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    symbols = load_universe(UNIVERSE_PATH)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]
    print(
        f"Universe: {len(symbols)} symbols  prox={prox}  compute_slopes={compute}  "
        f"workers={args.workers}  stamp={STAMP}",
        flush=True,
    )
    t0 = time.time()

    all_trades: list[dict] = []
    event_counts: dict[str, int] = {aid: 0 for aid, _, _ in ARMS}
    used = 0
    skipped = 0

    if compute:
        prox_t = tuple(PROX_GRID)
        workers = max(1, int(args.workers))
        done = 0

        def _ingest(sym: str, trades: list[dict], events: dict[str, int], status: str) -> None:
            nonlocal used, skipped
            if status != "ok":
                skipped += 1
                return
            used += 1
            for arm_id, n_ev in events.items():
                if arm_id in event_counts:
                    event_counts[arm_id] += int(n_ev)
            all_trades.extend(trades)

        if workers == 1:
            for i, sym in enumerate(symbols, 1):
                sym, trades, events, status = _worker_compute_sym(sym, prox_t)
                _ingest(sym, trades, events, status)
                if i % 25 == 0 or i == len(symbols):
                    print(
                        f"  progress {i}/{len(symbols)} used={used} skipped={skipped} "
                        f"trades={len(all_trades)} elapsed={time.time()-t0:.0f}s",
                        flush=True,
                    )
        else:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_worker_compute_sym, sym, prox_t): sym for sym in symbols}
                for fut in as_completed(futs):
                    sym, trades, events, status = fut.result()
                    done += 1
                    _ingest(sym, trades, events, status)
                    if done % 25 == 0 or done == len(symbols):
                        print(
                            f"  progress {done}/{len(symbols)} used={used} skipped={skipped} "
                            f"trades={len(all_trades)} elapsed={time.time()-t0:.0f}s",
                            flush=True,
                        )
    else:
        slopes = load_slopes()
        print(f"Slopes rows: {len(slopes):,}", flush=True)
        for sym in symbols:
            ohlc = load_ohlc(sym)
            if ohlc is None or len(ohlc) < MIN_DAILY_BARS + 50:
                print(f"  skip {sym}: no/short OHLC", flush=True)
                skipped += 1
                continue
            g = slopes[slopes["symbol"] == sym]
            if g.empty:
                print(f"  skip {sym}: no slopes", flush=True)
                skipped += 1
                continue
            wide = wide_for_symbol(g)
            if wide.empty:
                skipped += 1
                continue
            used += 1
            for arm_id, _label, _x in ARMS:
                edge = f"sig_{arm_id}_edge"
                if edge not in wide.columns:
                    continue
                event_counts[arm_id] += int(wide[edge].fillna(False).sum())
                all_trades.extend(simulate_arm(ohlc, wide, sym, arm_id, edge))
            print(f"  {sym}: trades so far {len(all_trades)}", flush=True)

    print(
        f"Sim done used={used} skipped={skipped} trades={len(all_trades)} "
        f"elapsed={time.time()-t0:.0f}s",
        flush=True,
    )

    trades_df = pd.DataFrame(all_trades)
    if not trades_df.empty:
        trades_df.to_csv(OUT_DIR / "closed_trades.csv", index=False)

    books: list[dict] = []
    by_arm: dict[str, list[dict]] = {}
    books_by_arm_slice: dict[str, dict[str, dict]] = {}
    for arm_id, label, _ in ARMS:
        arm_trades = [t for t in all_trades if t["arm"] == arm_id]
        by_arm[arm_id] = arm_trades
        books_by_arm_slice[arm_id] = {}
        for oos, tag in ((None, "FULL"), (False, "IS"), (True, "OOS")):
            sl = slice_trades(arm_trades, oos=oos)
            m = book_metrics(sl, f"{label} · {tag}")
            books.append(m)
            books_by_arm_slice[arm_id][tag] = m

    books_df = pd.DataFrame(books)
    books_df.to_csv(OUT_DIR / "book_metrics.csv", index=False)

    def full_of(arm_id: str) -> dict:
        return books_by_arm_slice[arm_id]["FULL"]

    ctrl_full = full_of(CONTROL_ARM)
    verdicts: list[dict] = []
    verdict_map: dict[str, str] = {}
    for arm_id, label, x in ARMS:
        if arm_id == CONTROL_ARM:
            continue
        v = decide_verdict(full_of(arm_id), ctrl_full, f"prox{int(x)} vs prox2")
        # OOS soften → HOLD
        if v["verdict"] in ("LEAN KEEP", "KEEP"):
            cand_oos = books_by_arm_slice[arm_id]["OOS"]
            cand_is = books_by_arm_slice[arm_id]["IS"]
            ctrl_oos = books_by_arm_slice[CONTROL_ARM]["OOS"]
            ca, ka = cand_oos.get("avg_pnl_pct"), ctrl_oos.get("avg_pnl_pct")
            cis = cand_is.get("avg_pnl_pct")
            soft_vs_ctrl = (
                isinstance(ca, (int, float))
                and isinstance(ka, (int, float))
                and math.isfinite(float(ca))
                and math.isfinite(float(ka))
                and float(ca) < float(ka) - 0.1
            )
            soft_vs_is = (
                isinstance(ca, (int, float))
                and isinstance(cis, (int, float))
                and math.isfinite(float(ca))
                and math.isfinite(float(cis))
                and float(ca) < float(cis) - 0.5
            )
            if soft_vs_ctrl or soft_vs_is:
                v["verdict"] = "HOLD"
                v["reason"] = (
                    v["reason"]
                    + f" OOS softens (OOS Avg {ca:.2f}% vs IS {cis:.2f}% / ctrl OOS {ka:.2f}%)"
                    " → HOLD, do not retune."
                )
        verdicts.append(v)
        verdict_map[arm_id] = v["verdict"]

    delta_is = build_delta_rows(by_arm, oos=False, verdict_map=verdict_map)
    delta_full = build_delta_rows(by_arm, oos=None, verdict_map=verdict_map)
    pd.DataFrame(delta_is).drop(columns=["_label"], errors="ignore").to_csv(
        OUT_DIR / "is_vs_prox2.csv", index=False
    )

    write_docs(verdicts, event_counts, books_by_arm_slice)
    html_path = write_html(
        books=books,
        delta_is=delta_is,
        delta_full=delta_full,
        verdicts=verdicts,
        trades=trades_df,
    )

    print("\n=== N (FULL) ===", flush=True)
    for arm_id, _, _ in ARMS:
        print(f"  {arm_id}: {books_by_arm_slice[arm_id]['FULL']['n']}", flush=True)
    print("\n=== IS vs prox2 ===", flush=True)
    for r in delta_is:
        msg = (
            f"  {r['arm']}: N={r['n']} Avg={fmt_pct(r['avg_pnl_pct'])} "
            f"ΔAvg={fmt_delta(r['d_avg'], 2, 'pp')} WR={fmt_pct(r['win_pct'])} "
            f"PF={fmt_num(r['pf'])} → {r['verdict']}"
        )
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
    print("\n=== VERDICTS ===", flush=True)
    for v in verdicts:
        msg = f"  {v['verdict']:10s}  {v['hypothesis']}: {v['reason']}"
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
    print(f"\nHTML: {html_path}", flush=True)
    print(f"OUT:  {OUT_DIR}", flush=True)
    print(f"Elapsed: {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
