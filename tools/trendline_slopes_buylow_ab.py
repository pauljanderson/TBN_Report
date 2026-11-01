#!/usr/bin/env python3
"""Buy-low / regime variants on PaulTwenty fractal trendline slopes.

Builds on trendline_slopes_paultwenty_20260831 day-by-day slope book.

Hypotheses (research-only, labeled separately — not one KEEP lever across all):
  A  Regime buy-low: monthly support UP + weekly support UP + daily support DOWN
     → buy next open. Control = M+W support UP (any daily). Alt = D resistance DOWN.
  B  Proximity: weekly support UP and |dist_pct to weekly support| <= 2% (frozen X).
     Control = weekly support UP (no proximity).
  C1 All three TF supports UP (trend continuation).
  C2 M+W UP + weekly proximity (<=2%) + daily support turns UP today (was not UP yesterday).

Frozen exit (all arms): next-open fill; time-stop 40 bars; or close back below weekly support.
IS = opened < 2024-01-01; OOS = opened >= 2024-01-01. Report-only OOS.

Research only — not gold, not DailyRun.

Usage:
  python tools/trendline_slopes_buylow_ab.py
"""
from __future__ import annotations

import html as html_mod
import math
import sys
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
STAMP = "trendline_slopes_buylow_20260904"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
TIME_STOP_BARS = 40
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
MIN_PRICE = 5.0
MIN_ADV20 = 500_000.0
MIN_DAILY_BARS = 400
PROX_PCT = 2.0  # frozen proximity band for weekly support
FWD_HORIZONS = (5, 10, 20, 40)

# Arm definitions: (arm_id, label, group)
# group used for control-vs-candidate pairing in verdicts
ARMS = [
    ("ctrl_mw_up", "Control A — M+W support UP", "A"),
    ("A_mw_up_d_down", "A — M+W UP + D support DOWN", "A"),
    ("Aalt_dres_down", "A-alt — M+W UP + D resistance DOWN", "A"),
    ("ctrl_w_up", "Control B — weekly support UP", "B"),
    ("B_wup_prox2", "B — W UP + |dist|≤2% of weekly support", "B"),
    ("C1_all_up", "C1 — M+W+D support all UP", "C"),
    ("C2_touch_turn", "C2 — M+W UP + prox2 + D support turns UP", "C"),
]

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


def wide_for_symbol(g: pd.DataFrame) -> pd.DataFrame:
    """One row per date with M/W/D support (and D resistance) dirs + dist + line px."""
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


def add_signals(w: pd.DataFrame) -> pd.DataFrame:
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
    d_down = w["daily_support_dir"] == "DOWN"
    dres_down = w["daily_resistance_dir"] == "DOWN"
    dist = pd.to_numeric(w["weekly_support_dist"], errors="coerce")
    prox = dist.abs() <= PROX_PCT
    d_prev = w["daily_support_dir"].shift(1)
    d_turn_up = d_up & (d_prev.notna()) & (d_prev != "UP")

    have_mw = m_up & w_up & w["monthly_support_dir"].notna() & w["weekly_support_dir"].notna()
    have_d = w["daily_support_dir"].notna() & (w["daily_support_dir"] != "")
    have_w = w_up & w["weekly_support_dir"].notna()

    w["sig_ctrl_mw_up"] = have_mw
    w["sig_A_mw_up_d_down"] = have_mw & have_d & d_down
    w["sig_Aalt_dres_down"] = have_mw & (w["daily_resistance_dir"] == "DOWN")
    w["sig_ctrl_w_up"] = have_w
    w["sig_B_wup_prox2"] = have_w & prox & dist.notna()
    w["sig_C1_all_up"] = have_mw & have_d & d_up
    w["sig_C2_touch_turn"] = have_mw & prox & dist.notna() & d_turn_up

    # Rising-edge only for high-frequency state regimes (avoid holding every day)
    for col in (
        "sig_ctrl_mw_up",
        "sig_A_mw_up_d_down",
        "sig_Aalt_dres_down",
        "sig_ctrl_w_up",
        "sig_B_wup_prox2",
        "sig_C1_all_up",
    ):
        prev = w[col].shift(1).fillna(False).astype(bool)
        w[col + "_edge"] = w[col].astype(bool) & (~prev)
    # C2 is already an edge (turn up)
    w["sig_C2_touch_turn_edge"] = w["sig_C2_touch_turn"]
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
                "dres_dir": row.get("daily_resistance_dir") or "",
                "w_dist": _f(row.get("weekly_support_dist")),
                "close_signal": c,
            }
        )
        i = exit_i + 1
    return trades


def event_forwards(
    ohlc: pd.DataFrame, wide: pd.DataFrame, sig_col: str, arm: str
) -> list[dict[str, Any]]:
    dates = list(ohlc["Date"])
    closes = ohlc["Close"].astype(float).to_numpy()
    idx = {d: i for i, d in enumerate(dates)}
    out = []
    hits = wide[wide[sig_col] == True]  # noqa: E712
    for _, r in hits.iterrows():
        d = r["date"]
        i = idx.get(d)
        if i is None or i < MIN_DAILY_BARS:
            continue
        rec: dict[str, Any] = {"arm": arm, "date": d, "symbol": None, "close": float(closes[i])}
        for h in FWD_HORIZONS:
            j = i + h
            if j < len(closes) and closes[i] > 0:
                rec[f"fwd_{h}"] = (closes[j] / closes[i] - 1.0) * 100.0
            else:
                rec[f"fwd_{h}"] = float("nan")
        out.append(rec)
    return out


def baseline_forwards(ohlc: pd.DataFrame, sym: str) -> list[dict[str, Any]]:
    """Every eligible day forward return — buy-hold / unconditional reference."""
    closes = ohlc["Close"].astype(float).to_numpy()
    dates = list(ohlc["Date"])
    if "Volume" in ohlc.columns:
        adv20 = ohlc["Volume"].astype(float).rolling(20, min_periods=20).mean().to_numpy()
    else:
        adv20 = np.full(len(ohlc), np.nan)
    out = []
    for i in range(MIN_DAILY_BARS, len(closes) - max(FWD_HORIZONS) - 1):
        c = float(closes[i])
        if c < MIN_PRICE:
            continue
        adv = float(adv20[i]) if math.isfinite(float(adv20[i])) else 0.0
        if adv < MIN_ADV20:
            continue
        rec: dict[str, Any] = {
            "arm": "baseline_all_days",
            "date": dates[i],
            "symbol": sym,
            "close": c,
        }
        for h in FWD_HORIZONS:
            j = i + h
            rec[f"fwd_{h}"] = (closes[j] / closes[i] - 1.0) * 100.0
        out.append(rec)
    return out


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


def fwd_summary(events: list[dict], label: str) -> dict[str, Any]:
    rec: dict[str, Any] = {"slice": label, "n_events": len(events)}
    for h in FWD_HORIZONS:
        xs = np.array(
            [e[f"fwd_{h}"] for e in events if math.isfinite(e.get(f"fwd_{h}", float("nan")))],
            dtype=float,
        )
        rec[f"fwd_{h}_n"] = int(len(xs))
        rec[f"fwd_{h}_mean"] = float(xs.mean()) if len(xs) else float("nan")
        rec[f"fwd_{h}_med"] = float(np.median(xs)) if len(xs) else float("nan")
        rec[f"fwd_{h}_wr"] = float((xs > 0).mean() * 100.0) if len(xs) else float("nan")
    return rec


def fmt_pct(x: Any, d: int = 2) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{d}f}%"


def fmt_num(x: Any, d: int = 2) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{d}f}"


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
    # Soften if OOS called separately — here full-book primary
    better_avg = float(c_avg) > float(k_avg) + 0.15  # ~15 bps edge
    worse_avg = float(c_avg) < float(k_avg) - 0.15
    wr_ok = True
    if isinstance(c_wr, (int, float)) and isinstance(k_wr, (int, float)):
        wr_ok = float(c_wr) >= float(k_wr) - 2.0
    pf_ok = True
    if isinstance(c_pf, (int, float)) and isinstance(k_pf, (int, float)) and math.isfinite(float(k_pf)):
        pf_ok = float(c_pf) >= float(k_pf) * 0.95
    # N collapse: candidate < 40% of control (when control is a broad state)
    n_ok = cn >= max(25, int(0.15 * kn)) if kn > 0 else True
    if better_avg and wr_ok and pf_ok and n_ok:
        return {
            "hypothesis": name,
            "verdict": "LEAN KEEP",
            "reason": (
                f"Full-book Avg PnL % {c_avg:.2f} vs control {k_avg:.2f}; "
                f"WR {c_wr:.1f}% vs {k_wr:.1f}%; N={cn}. Research-only — not gold."
            ),
        }
    if worse_avg and (not wr_ok or (isinstance(c_pf, float) and isinstance(k_pf, float) and c_pf < k_pf * 0.9)):
        return {
            "hypothesis": name,
            "verdict": "DISMISS",
            "reason": (
                f"Quality worse: Avg PnL % {c_avg:.2f} vs {k_avg:.2f}; "
                f"WR {c_wr:.1f}% vs {k_wr:.1f}%; N={cn}."
            ),
        }
    return {
        "hypothesis": name,
        "verdict": "HOLD",
        "reason": (
            f"Flat / mixed vs control (Avg {c_avg:.2f} vs {k_avg:.2f}, "
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


def write_docs(verdicts: list[dict], event_counts: dict[str, int]) -> None:
    hyp = f"""# HYPOTHESIS — {STAMP}

| Field | Fill in |
|-------|---------|
| System / prefix | Trendline slopes (fractal M/W/D support & resistance) |
| Baseline stamp | `trendline_slopes_paultwenty_20260831` |
| Universe | PaulTwenty (liquid-763 slope book not available for this stamp) |
| **Evidence** | Higher-TF uptrend + lower-TF pullback / proximity as buy-low |
| **Hypothesis A** | Monthly support UP + weekly support UP + daily support DOWN improves longs vs M+W UP alone |
| **Hypothesis B** | When weekly support is UP, buying within {PROX_PCT:g}% of the weekly support line improves vs W-UP alone |
| **Hypothesis C1** | All three TF supports UP (continuation) |
| **Hypothesis C2** | M+W UP + weekly proximity + daily support turns UP |
| **Single knob** | ENTRY definition (per hypothesis); exit frozen |
| Frozen settings | next_open; time_stop {TIME_STOP_BARS}; exit also if close < weekly support; prox X={PROX_PCT:g}%; sheet $45k; MIN_PRICE 5; MIN_ADV20 500k; IS cut 2024-01-01 |
| Decision | research-only; no gold / DailyRun |

Acronyms: TF = timeframe. Support = last two confirmed swing lows. Resistance = last two confirmed swing highs. M/W/D = monthly / weekly / daily.
"""
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "Research-only buy-low / regime variants on PaulTwenty fractal trendline slopes.",
        "",
        "## Freeze",
        "",
        "| Knob | Value |",
        "|------|-------|",
        "| Universe | `drive/universes/PaulTwenty_universe.csv` |",
        "| Line book | `trendline_slopes_paultwenty_20260831/trendline_slopes_long.csv` |",
        "| Algorithm | Fractal last-two swings; daily k=5, weekly W-FRI k=3, monthly ME k=2 |",
        "| Look-ahead | Confirmed pivots only (inherited from slope book) |",
        f"| Proximity X | `|dist_pct| ≤ {PROX_PCT:g}%` to weekly support (frozen a priori) |",
        "| Signal style | Rising-edge of regime (state→true); C2 is turn-up by construction |",
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
        "| ctrl_mw_up | Monthly support UP AND weekly support UP |",
        "| A_mw_up_d_down | Control A + daily support DOWN |",
        "| Aalt_dres_down | Control A + daily resistance DOWN |",
        "| ctrl_w_up | Weekly support UP |",
        f"| B_wup_prox2 | Weekly support UP AND `|dist_pct| ≤ {PROX_PCT:g}%` |",
        "| C1_all_up | M+W+D support all UP |",
        f"| C2_touch_turn | M+W UP + prox≤{PROX_PCT:g}% + daily support turns UP |",
        "",
        "## Event counts (rising-edge days, pre-liquidity filter in sim)",
        "",
    ]
    for k, v in event_counts.items():
        lines.append(f"- `{k}`: {v}")
    lines += [
        "",
        "## Selection / verdicts (research-only)",
        "",
        "Judged on full-book quality vs paired control. OOS is report-only — do not retune.",
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
        "Liquid-763 deferred — no all-universe slope long CSV in Drive for this run.",
        "",
    ]
    (OUT_DIR / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def write_html(
    *,
    books: list[dict],
    fwd_rows: list[dict],
    verdicts: list[dict],
    trades: pd.DataFrame,
) -> Path:
    book_html = metrics_table(books, "Book — arms (full / IS / OOS)")
    fwd_cols = [("slice", "text"), ("N events", "num")]
    for h in FWD_HORIZONS:
        fwd_cols += [(f"fwd{h} mean %", "num"), (f"fwd{h} med %", "num"), (f"fwd{h} WR", "num")]
    fh = "".join(sortable_th(a, b) for a, b in fwd_cols)
    fb = []
    for r in fwd_rows:
        tds = [f"<td>{html_mod.escape(str(r['slice']))}</td>", f"<td>{r['n_events']}</td>"]
        for h in FWD_HORIZONS:
            tds.append(f"<td class='{td_cls(r.get(f'fwd_{h}_mean'))}'>{fmt_pct(r.get(f'fwd_{h}_mean'))}</td>")
            tds.append(f"<td>{fmt_pct(r.get(f'fwd_{h}_med'))}</td>")
            tds.append(f"<td>{fmt_pct(r.get(f'fwd_{h}_wr'))}</td>")
        fb.append("<tr>" + "".join(tds) + "</tr>")
    fwd_html = (
        "<h2>Event-study forward close-to-close (diagnostic)</h2>"
        "<p class='meta'>Click column headers to sort. From signal-day close; overlapping events allowed. "
        "baseline_all_days = every liquid day (buy-hold reference).</p>"
        f"<table class='sortable'><thead><tr>{fh}</tr></thead><tbody>{''.join(fb)}</tbody></table>"
    )

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
        "<p class='meta'>Click column headers to sort. Not gold / not DailyRun.</p>"
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
    # Cap trade table for HTML size
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
<title>Trendline slopes buy-low — {STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>Trendline slopes — buy-low / regime variants</h1>
<p class="meta">Stamp <span class="badge">{html_mod.escape(STAMP)}</span> · PaulTwenty ·
source <code>trendline_slopes_paultwenty_20260831</code> ·
proximity X={PROX_PCT:g}% · exit time {TIME_STOP_BARS} / stop weekly support ·
IS cut 2024-01-01. Research only — not gold, not DailyRun. Click column headers to sort.</p>
<div class="insight">
<strong>Plain-English takeaways</strong>
<ul>{insight_items}</ul>
</div>
<p class="caveat"><strong>Caveats:</strong> Fractal last-two-swing lines (look-ahead-safe confirmation).
Signals are rising-edge of regime states. Toy exit. OOS is report-only — do not retune on OOS.
Liquid-763 not run (no matching all-universe slope long CSV).</p>
{verd_html}
{book_html}
{fwd_html}
{trade_html}
{SORT_JS}
</body>
</html>
"""
    path = OUT_DIR / "trendline_slopes_buylow_compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    symbols = load_universe(PAULTWENTY)
    print(f"Universe: {len(symbols)} symbols", flush=True)
    slopes = load_slopes()
    print(f"Slopes rows: {len(slopes):,}", flush=True)

    all_trades: list[dict] = []
    all_fwd: list[dict] = []
    base_fwd: list[dict] = []
    event_counts: dict[str, int] = {aid: 0 for aid, _, _ in ARMS}

    for sym in symbols:
        ohlc = load_ohlc(sym)
        if ohlc is None or len(ohlc) < MIN_DAILY_BARS + 50:
            print(f"  skip {sym}: no/short OHLC", flush=True)
            continue
        g = slopes[slopes["symbol"] == sym]
        if g.empty:
            print(f"  skip {sym}: no slopes", flush=True)
            continue
        wide = wide_for_symbol(g)
        if wide.empty:
            continue
        base_fwd.extend(baseline_forwards(ohlc, sym))
        for arm_id, _label, _grp in ARMS:
            edge = f"sig_{arm_id}_edge"
            if edge not in wide.columns:
                continue
            event_counts[arm_id] += int(wide[edge].fillna(False).sum())
            trades = simulate_arm(ohlc, wide, sym, arm_id, edge)
            for t in trades:
                all_trades.append(t)
            ev = event_forwards(ohlc, wide, edge, arm_id)
            for e in ev:
                e["symbol"] = sym
            all_fwd.extend(ev)
        print(f"  {sym}: trades so far {len(all_trades)}", flush=True)

    trades_df = pd.DataFrame(all_trades)
    if not trades_df.empty:
        trades_df.to_csv(OUT_DIR / "closed_trades.csv", index=False)

    books: list[dict] = []
    by_arm: dict[str, list[dict]] = {}
    for arm_id, label, _ in ARMS:
        arm_trades = [t for t in all_trades if t["arm"] == arm_id]
        by_arm[arm_id] = arm_trades
        for oos, tag in ((None, "FULL"), (False, "IS"), (True, "OOS")):
            sl = slice_trades(arm_trades, oos=oos)
            books.append(book_metrics(sl, f"{label} · {tag}"))

    books_df = pd.DataFrame(books)
    books_df.to_csv(OUT_DIR / "book_metrics.csv", index=False)

    # Forward summaries (subsample baseline for speed in summary — use all)
    fwd_rows = [fwd_summary(base_fwd, "baseline_all_days (buy-hold ref)")]
    for arm_id, label, _ in ARMS:
        ev = [e for e in all_fwd if e["arm"] == arm_id]
        fwd_rows.append(fwd_summary(ev, label))
    pd.DataFrame(fwd_rows).to_csv(OUT_DIR / "forward_event_summary.csv", index=False)

    # Verdicts on FULL books vs paired controls
    full = {r["slice"]: r for r in books if r["slice"].endswith("· FULL")}

    def full_of(arm_id: str) -> dict:
        label = next(l for a, l, _ in ARMS if a == arm_id)
        return full.get(f"{label} · FULL", book_metrics([], f"{label} · FULL"))

    verdicts = [
        decide_verdict(full_of("A_mw_up_d_down"), full_of("ctrl_mw_up"), "A — M/W up + D support down"),
        decide_verdict(full_of("Aalt_dres_down"), full_of("ctrl_mw_up"), "A-alt — M/W up + D resistance down"),
        decide_verdict(full_of("B_wup_prox2"), full_of("ctrl_w_up"), "B — proximity ≤2% to weekly support"),
        decide_verdict(full_of("C1_all_up"), full_of("ctrl_mw_up"), "C1 — all three TF supports up"),
        decide_verdict(full_of("C2_touch_turn"), full_of("ctrl_mw_up"), "C2 — prox + daily support turns up"),
    ]
    # OOS soften vs IS or vs control → HOLD (do not retune)
    for v, cand_id, ctrl_id in (
        (verdicts[0], "A_mw_up_d_down", "ctrl_mw_up"),
        (verdicts[1], "Aalt_dres_down", "ctrl_mw_up"),
        (verdicts[2], "B_wup_prox2", "ctrl_w_up"),
        (verdicts[3], "C1_all_up", "ctrl_mw_up"),
        (verdicts[4], "C2_touch_turn", "ctrl_mw_up"),
    ):
        if v["verdict"] not in ("LEAN KEEP", "KEEP"):
            continue
        cand_oos = book_metrics(slice_trades(by_arm[cand_id], oos=True), "oos")
        cand_is = book_metrics(slice_trades(by_arm[cand_id], oos=False), "is")
        ctrl_oos = book_metrics(slice_trades(by_arm[ctrl_id], oos=True), "oos")
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

    write_docs(verdicts, event_counts)
    html_path = write_html(books=books, fwd_rows=fwd_rows, verdicts=verdicts, trades=trades_df)

    print("\n=== VERDICTS ===", flush=True)
    for v in verdicts:
        msg = f"  {v['verdict']:10s}  {v['hypothesis']}: {v['reason']}"
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
    print(f"\nHTML: {html_path}", flush=True)
    print(f"OUT:  {OUT_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
