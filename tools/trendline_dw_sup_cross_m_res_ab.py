#!/usr/bin/env python3
"""ENTRY A/B: daily+weekly support lines cross above monthly resistance.

Hypothesis (one knob = entry):
  Buy when the *lines* themselves cross — daily support AND weekly support
  line_price both newly sit above monthly resistance line_price — not when
  close merely breaks monthly resistance (that is the control).

Same frozen exit on both arms:
  next-open fill, time-stop 40, or close back below monthly resistance.

Look-ahead: uses trendline_slopes_paultwenty_20260831 (confirmed pivots only).
Line-roll days (any of D-sup / W-sup / M-res pivot pair changes) are excluded
from the candidate signal so a new swing identity cannot fake a crossover.

Research only — not gold, not DailyRun.

Usage:
  python tools/trendline_dw_sup_cross_m_res_ab.py
"""
from __future__ import annotations

import html as html_mod
import math
import sys
from collections import defaultdict
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
STAMP = "trendline_dw_sup_cross_m_res_paultwenty_20260831"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
TIME_STOP_BARS = 40
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
MIN_PRICE = 5.0
MIN_ADV20 = 500_000.0
MIN_DAILY_BARS = 400
FWD_HORIZONS = (5, 10, 20, 40)

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 74rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 74rem; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
.up { color: #047857; font-weight: 600; }
.down { color: #b91c1c; font-weight: 600; }
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
        "d1",
        "d2",
        "p1",
        "p2",
        "line_price_at_asof",
        "close",
    ]
    df = pd.read_csv(SLOPES_CSV, usecols=usecols)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def wide_for_symbol(g: pd.DataFrame) -> pd.DataFrame:
    """One row per date with D-sup / W-sup / M-res line prices + identities."""
    g = g.copy()
    key = g["timeframe"] + "_" + g["side"]
    g = g.assign(_key=key)
    keep = g[_key_mask(g, ("daily_support", "weekly_support", "monthly_resistance"))]
    if keep.empty:
        return pd.DataFrame()
    rows = []
    for d, sg in keep.groupby("date", sort=True):
        rec: dict[str, Any] = {"date": d, "close": float(sg["close"].iloc[0])}
        for _, r in sg.iterrows():
            k = r["_key"]
            rec[f"{k}_px"] = float(r["line_price_at_asof"])
            rec[f"{k}_d1"] = r["d1"]
            rec[f"{k}_d2"] = r["d2"]
            rec[f"{k}_dir"] = r["direction"]
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _key_mask(g: pd.DataFrame, keys: tuple[str, ...]) -> pd.Series:
    return g["_key"].isin(keys)


def add_signals(wide: pd.DataFrame) -> pd.DataFrame:
    w = wide.copy()
    for col in ("daily_support_px", "weekly_support_px", "monthly_resistance_px"):
        if col not in w.columns:
            w[col] = np.nan
    ds = w["daily_support_px"].astype(float)
    ws = w["weekly_support_px"].astype(float)
    mr = w["monthly_resistance_px"].astype(float)
    have = ds.notna() & ws.notna() & mr.notna() & (mr > 0)
    both_above = have & (ds > mr) & (ws > mr)
    prev_above = both_above.shift(1).fillna(False)
    id_cols = [
        "daily_support_d1",
        "daily_support_d2",
        "weekly_support_d1",
        "weekly_support_d2",
        "monthly_resistance_d1",
        "monthly_resistance_d2",
    ]
    for c in id_cols:
        if c not in w.columns:
            w[c] = np.nan
    rolled = pd.Series(False, index=w.index)
    for c in id_cols:
        prev = w[c].shift(1)
        rolled = rolled | (w[c].notna() & prev.notna() & (w[c] != prev))
    w["both_above"] = both_above
    w["line_roll"] = rolled
    w["sig_line_cross"] = both_above & (~prev_above) & (~rolled) & have
    w["sig_line_cross_incl_roll"] = both_above & (~prev_above) & have
    prev_c = w["close"].shift(1)
    w["sig_px_break_mres"] = (
        have
        & prev_c.notna()
        & (prev_c <= mr)
        & (w["close"] > mr)
    )
    rising = (w.get("daily_support_dir") == "UP") & (w.get("weekly_support_dir") == "UP")
    w["sig_line_cross_rising"] = w["sig_line_cross"] & rising
    return w


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
        mr = row.get("monthly_resistance_px")
        if mr is None or not math.isfinite(float(mr)) or float(mr) <= 0:
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
            mr_j = m.iloc[j].get("monthly_resistance_px")
            close_j = float(m.iloc[j]["Close"])
            if (
                j > entry_i
                and mr_j is not None
                and math.isfinite(float(mr_j))
                and float(mr_j) > 0
                and close_j < float(mr_j)
            ):
                exit_i = j
                exit_type = "STOP_MRES"
                break
        if exit_i is None:
            exit_i = last
            exit_type = "TIME" if exit_i < n - 1 or (exit_i - entry_i) >= TIME_STOP_BARS else "EOD"
        fill = float(m.iloc[exit_i]["Close"])
        if exit_type == "STOP_MRES":
            # close-cross exit at that bar's close (look-ahead safe vs same-day open)
            fill = float(m.iloc[exit_i]["Close"])
        pnl_pct = (fill / entry - 1.0) * 100.0
        days = (m.iloc[exit_i]["Date"] - opened).days
        bars = int(exit_i - entry_i)
        pnl_d = SHEET * (pnl_pct / 100.0)
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
                "pnl_d": pnl_d,
                "days": days,
                "bars": bars,
                "exit_type": exit_type,
                "mres_px_signal": float(mr),
                "dsup_px": _f(row.get("daily_support_px")),
                "wsup_px": _f(row.get("weekly_support_px")),
                "dsup_dir": row.get("daily_support_dir") or "",
                "wsup_dir": row.get("weekly_support_dir") or "",
                "mres_dir": row.get("monthly_resistance_dir") or "",
                "close_signal": c,
            }
        )
        i = exit_i + 1
    return trades


def _f(x: Any) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def event_forwards(ohlc: pd.DataFrame, wide: pd.DataFrame, sig_col: str) -> list[dict[str, Any]]:
    """Close-to-close forward returns from signal close (diagnostic, not the trade)."""
    dates = list(ohlc["Date"])
    closes = ohlc["Close"].astype(float).to_numpy()
    idx = {d: i for i, d in enumerate(dates)}
    out = []
    hits = wide[wide[sig_col] == True]  # noqa: E712
    for _, r in hits.iterrows():
        d = r["date"]
        i = idx.get(d)
        if i is None:
            continue
        rec = {"date": d, "close": float(closes[i])}
        for h in FWD_HORIZONS:
            j = i + h
            if j < len(closes) and closes[i] > 0:
                rec[f"fwd_{h}"] = (closes[j] / closes[i] - 1.0) * 100.0
            else:
                rec[f"fwd_{h}"] = float("nan")
        rec["dsup_dir"] = r.get("daily_support_dir") or ""
        rec["wsup_dir"] = r.get("weekly_support_dir") or ""
        rec["mres_dir"] = r.get("monthly_resistance_dir") or ""
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
        "exit_stop": sum(1 for t in trades if t["exit_type"] == "STOP_MRES"),
        "exit_time": sum(1 for t in trades if t["exit_type"] == "TIME"),
        "trades_per_year": tpy,
        "pnl_d_sum": pnl_d_sum,
    }


def fwd_summary(events: list[dict], label: str) -> dict[str, Any]:
    rec: dict[str, Any] = {"slice": label, "n_events": len(events)}
    for h in FWD_HORIZONS:
        xs = np.array([e[f"fwd_{h}"] for e in events if math.isfinite(e.get(f"fwd_{h}", float("nan")))])
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
            ("STOP_MRES", "num"),
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
            "STOP_MRES": str(r["exit_stop"]),
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
    return f"<h2>{html_mod.escape(title)}</h2><p class='meta'>Click column headers to sort.</p><table class='sortable'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def write_docs(n_line: int, n_px: int, n_roll_extra: int) -> None:
    hyp = f"""# HYPOTHESIS — {STAMP}

| Field | Fill in |
|-------|---------|
| System / prefix | Trendline (fractal M/W/D support & resistance) |
| Baseline stamp | `trendline_slopes_paultwenty_20260831` (line book) / `trendline_break_paul20_20260827` (price-break cousin) |
| Universe | PaulTwenty |
| **Evidence** | Geometry question: shorter-term supports eating monthly resistance as a structural long |
| **Hypothesis** | Buy quality improves vs price-break of monthly resistance when **daily support AND weekly support line prices both newly sit above monthly resistance** (same-line identity, no roll) |
| **Single knob** | ENTRY definition |
| Frozen settings | next_open; time_stop 40; exit also if close back below monthly resistance; sheet $45k; MIN_PRICE 5; MIN_ADV20 500k; IS cut 2024-01-01 |
| Alternatives | control = close crosses above monthly resistance; candidate = D-sup + W-sup cross above M-res |
| Decision | research-only; no gold / DailyRun |

Acronyms: TF = timeframe. Support = last two confirmed swing lows. Resistance = last two confirmed swing highs.
"""
    base = f"""# BASELINE — {STAMP}

Research-only ENTRY A/B on PaulTwenty fractal trendlines.

## Freeze

| Knob | Value |
|------|-------|
| Universe | `drive/universes/PaulTwenty_universe.csv` |
| Line book | `trendline_slopes_paultwenty_20260831/trendline_slopes_long.csv` |
| Algorithm | Fractal last-two swings; daily k=5, weekly W-FRI k=3, monthly ME k=2 |
| Look-ahead | Confirmed pivots only (inherited from slope book) |
| Control entry | Daily close crosses above active monthly **resistance** line |
| Candidate entry | Daily **support** line_px AND weekly **support** line_px both newly `>` monthly **resistance** line_px |
| Line-roll filter | Candidate ignores days where any of the three pivot pairs (d1/d2) changed vs prior day ({n_roll_extra} extra raw events dropped from trade book) |
| Entry fill | Next open |
| Exit | First of: daily close back below monthly resistance, or {TIME_STOP_BARS} bars |
| Sheet / initial | ${SHEET:,.0f} / ${INIT_ACCT:,.0f} |
| IS / OOS | opened < 2024-01-01 / opened >= 2024-01-01 |
| Costs | 0 |

## Selection

Control vs candidate chosen a priori (geometry vs price-break). Rising-support cut is **diagnostic only**, not the KEEP lever.

## Scope

Not gold. Not DailyRun. Toy exit (time 40 + M-res giveback) — quality over count.
Events in line book: candidate-style crosses (no roll)={n_line}; control price-breaks={n_px}.
"""
    (OUT_DIR / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")
    (OUT_DIR / "BASELINE.md").write_text(base, encoding="utf-8")


def write_html(
    *,
    books: list[dict],
    fwd_rows: list[dict],
    by_sym: pd.DataFrame,
    trades: pd.DataFrame,
    n_state_days: int,
    n_line: int,
    n_px: int,
    n_rising: int,
    n_incl_roll: int,
) -> Path:
    book_html = metrics_table(books, "Book — control vs candidate (full / IS / OOS)")
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
        "<h2>Event-study forward close-to-close (diagnostic, not the trade)</h2>"
        "<p class='meta'>Click column headers to sort. Measured from signal-day close; includes events that may overlap.</p>"
        f"<table class='sortable'><thead><tr>{fh}</tr></thead><tbody>{''.join(fb)}</tbody></table>"
    )

    scols = [
        ("symbol", "text"),
        ("arm", "text"),
        ("N", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("PF", "num"),
        ("Avg days", "num"),
    ]
    sh = "".join(sortable_th(a, b) for a, b in scols)
    sb = []
    for _, r in by_sym.iterrows():
        sb.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r['symbol']))}</td>"
            f"<td>{html_mod.escape(str(r['arm']))}</td>"
            f"<td>{int(r['n'])}</td>"
            f"<td class='{td_cls(r['win_pct'])}'>{fmt_pct(r['win_pct'])}</td>"
            f"<td class='{td_cls(r['avg_pnl'])}'>{fmt_pct(r['avg_pnl'])}</td>"
            f"<td>{fmt_num(r['pf'])}</td>"
            f"<td>{fmt_num(r['avg_days'], 1)}</td>"
            "</tr>"
        )
    sym_html = (
        "<h2>Per-symbol trade book</h2><p class='meta'>Click column headers to sort.</p>"
        f"<table class='sortable'><thead><tr>{sh}</tr></thead><tbody>{''.join(sb)}</tbody></table>"
    )

    tcols = [
        ("arm", "text"),
        ("symbol", "text"),
        ("opened", "date"),
        ("closed", "date"),
        ("exit", "text"),
        ("PnL %", "num"),
        ("days", "num"),
        ("D-sup dir", "text"),
        ("W-sup dir", "text"),
        ("M-res dir", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in tcols)
    tb = []
    show = trades.sort_values(["opened", "symbol"]).head(400)
    for _, r in show.iterrows():
        tb.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r['arm']))}</td>"
            f"<td>{html_mod.escape(str(r['symbol']))}</td>"
            f"<td>{r['opened']}</td><td>{r['closed']}</td>"
            f"<td>{html_mod.escape(str(r['exit_type']))}</td>"
            f"<td class='{td_cls(r['pnl'])}'>{fmt_pct(r['pnl'])}</td>"
            f"<td>{int(r['days'])}</td>"
            f"<td>{html_mod.escape(str(r.get('dsup_dir') or ''))}</td>"
            f"<td>{html_mod.escape(str(r.get('wsup_dir') or ''))}</td>"
            f"<td>{html_mod.escape(str(r.get('mres_dir') or ''))}</td>"
            "</tr>"
        )
    trades_html = (
        "<h2>Trades (first 400 by date)</h2><p class='meta'>Click column headers to sort. Full book in trades.csv.</p>"
        f"<table class='sortable'><thead><tr>{th}</tr></thead><tbody>{''.join(tb)}</tbody></table>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>{STAMP}</title>
<style>{SORT_CSS}</style></head><body>
<h1>Daily + weekly support crossing monthly resistance</h1>
<p class="meta">
PaulTwenty · research only · not gold · not DailyRun.
<strong>TF</strong> = timeframe (daily / weekly / monthly fractal swing lines).
Support = last two confirmed swing lows; resistance = last two confirmed swing highs.
</p>
<div class="insight">
<strong>Hypothesis (ENTRY knob):</strong> a long is better when the <em>support lines</em>
themselves overtake monthly resistance — daily support <em>and</em> weekly support
<code>line_price</code> both newly above monthly resistance — versus the existing
idea of price closing through monthly resistance.
</div>
<div class="insight">
<strong>Geometry counts (all days, before liquidity / one-trade-at-a-time):</strong>
{n_state_days} symbol-days with D-sup and W-sup already above M-res ·
{n_line} first-day same-line crosses (candidate) ·
{n_incl_roll} first-day crosses if line-rolls counted ·
{n_rising} of the same-line crosses have rising D+W support ·
{n_px} price close-crosses of monthly resistance (control).
</div>
<p class="caveat">
Frozen exit on both arms: next open, then first of close back below monthly resistance
or {TIME_STOP_BARS} bars. Line-roll days excluded from candidate so a new pivot pair
cannot jump the line overnight and print a fake cross. IS = opened &lt; 2024-01-01;
OOS is report-only. Judge quality (WR / Avg PnL% / PF / DD), not trade count.
</p>
{book_html}
{fwd_html}
{sym_html}
{trades_html}
<p class="meta">Source: {html_mod.escape(str(SLOPES_CSV))} · stamp {STAMP}</p>
{SORT_JS}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def per_symbol_table(trades: list[dict]) -> pd.DataFrame:
    rows = []
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in trades:
        by[(t["symbol"], t["arm"])].append(t)
    for (sym, arm), ts in sorted(by.items()):
        pnls = np.array([t["pnl"] for t in ts], dtype=float)
        wins = pnls[pnls > 0].sum()
        loss = -pnls[pnls <= 0].sum()
        rows.append(
            {
                "symbol": sym,
                "arm": arm,
                "n": len(ts),
                "win_pct": float((pnls > 0).mean() * 100.0),
                "avg_pnl": float(pnls.mean()),
                "pf": (wins / loss) if loss > 0 else float("nan"),
                "avg_days": float(np.mean([t["days"] for t in ts])),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    univ = load_universe(PAULTWENTY)
    slopes = load_slopes()
    slopes = slopes[slopes["symbol"].isin(univ)]
    print(f"slopes rows={len(slopes)} symbols={slopes['symbol'].nunique()}", flush=True)

    all_trades: list[dict] = []
    ev_line: list[dict] = []
    ev_px: list[dict] = []
    ev_rise: list[dict] = []
    n_state = 0
    n_line = n_px = n_rising = n_incl_roll = 0

    for sym in univ:
        ohlc = load_ohlc(sym)
        if ohlc is None or len(ohlc) < MIN_DAILY_BARS:
            print(f"skip {sym}: no/short OHLC")
            continue
        g = slopes[slopes["symbol"] == sym]
        wide = wide_for_symbol(g)
        if wide.empty:
            print(f"skip {sym}: no wide lines")
            continue
        wide = add_signals(wide)
        n_state += int(wide["both_above"].sum())
        n_line += int(wide["sig_line_cross"].sum())
        n_incl_roll += int(wide["sig_line_cross_incl_roll"].sum())
        n_rising += int(wide["sig_line_cross_rising"].sum())
        n_px += int(wide["sig_px_break_mres"].sum())
        ev_line.extend({"symbol": sym, **e} for e in event_forwards(ohlc, wide, "sig_line_cross"))
        ev_px.extend({"symbol": sym, **e} for e in event_forwards(ohlc, wide, "sig_px_break_mres"))
        ev_rise.extend({"symbol": sym, **e} for e in event_forwards(ohlc, wide, "sig_line_cross_rising"))
        all_trades.extend(simulate_arm(ohlc, wide, sym, "px_break_mres", "sig_px_break_mres"))
        all_trades.extend(simulate_arm(ohlc, wide, sym, "dw_sup_cross_mres", "sig_line_cross"))
        print(
            f"{sym}: line_x={int(wide['sig_line_cross'].sum())} "
            f"px_brk={int(wide['sig_px_break_mres'].sum())} "
            f"state_days={int(wide['both_above'].sum())}",
            flush=True,
        )

    books = []
    for arm, name in (
        ("px_break_mres", "control px_break_mres"),
        ("dw_sup_cross_mres", "candidate dw_sup_cross_mres"),
    ):
        ts = [t for t in all_trades if t["arm"] == arm]
        books.append(book_metrics(ts, f"{name} FULL"))
        books.append(book_metrics(slice_trades(ts, oos=False), f"{name} IS"))
        books.append(book_metrics(slice_trades(ts, oos=True), f"{name} OOS"))

    fwd_rows = [
        fwd_summary(ev_px, "control px_break_mres"),
        fwd_summary(ev_line, "candidate dw_sup_cross_mres"),
        fwd_summary(ev_rise, "diagnostic rising D+W (not KEEP lever)"),
    ]
    trades_df = pd.DataFrame(all_trades)
    if not trades_df.empty:
        trades_df.to_csv(OUT_DIR / "trades.csv", index=False)
    by_sym = per_symbol_table(all_trades)
    by_sym.to_csv(OUT_DIR / "symbol_summary.csv", index=False)
    pd.DataFrame(books).to_csv(OUT_DIR / "book_metrics.csv", index=False)
    pd.DataFrame(fwd_rows).to_csv(OUT_DIR / "event_fwd.csv", index=False)

    write_docs(n_line, n_px, n_incl_roll - n_line)
    html_path = write_html(
        books=books,
        fwd_rows=fwd_rows,
        by_sym=by_sym,
        trades=trades_df if not trades_df.empty else pd.DataFrame(),
        n_state_days=n_state,
        n_line=n_line,
        n_px=n_px,
        n_rising=n_rising,
        n_incl_roll=n_incl_roll,
    )
    print(f"wrote {html_path}")
    print(f"events line={n_line} incl_roll={n_incl_roll} rising={n_rising} px={n_px} state_days={n_state}")
    for b in books:
        print(
            f"  {b['slice']}: n={b['n']} wr={b['win_pct']} avg={b['avg_pnl_pct']} "
            f"pf={b['pf']} ann={b['ann_ror']} dd={b['max_dd']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
