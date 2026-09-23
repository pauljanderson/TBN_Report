#!/usr/bin/env python3
"""EXIT A/Bs to lock RSI winners that ImprovePriority said we give back.

Frozen entries = stamp 260916125816 Closed book (atr=2.93, no min_dist,
exit RSI 70, time stop 20). Research-only Closed overlay — not DailyRun.

Usage:
  python tools/rsi_giveback_lockin_ab_20260916.py
  python tools/rsi_giveback_lockin_ab_20260916.py --html-only
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from rocket_tbn import _wilder_rsi14_arr  # noqa: E402
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    filter_html_compare_columns,
    format_money,
    overlay_ann_ror_max_dd,
)

DATA_DIR = ROOT / "data" / "newdata" / "data"
SRC_CLOSED = ROOT / "drive" / "RSI_Closed_260916125816.csv"
SRC_PRIO = ROOT / "drive" / "RSI_ImprovePriority_260916125816.html"
SRC_HINTS = ROOT / "drive" / "RSI_ImproveHints_260916125816.md"
STAMP = "rsi_giveback_lockin_ab_20260916"
OUT_DIR = ROOT / "drive" / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
SHEET = 10_000.0
INIT = DEFAULT_INITIAL_ACCOUNT
CTRL_TS = 20
CTRL_EXIT_RSI = 70.0
CTRL_ATR = 2.93
SRC_TS = "260916125816"

ORIGINAL_REQUEST = (
    'looking at this RSI_ImprovePriority_260916125816.html can you come up with '
    'some AB tests to see if we can lock in some of those winners that we are giving back?'
)
PLAIN_ENGLISH = (
    "Relative Strength Index (RSI) buys after a cool-off from a hot reading, then "
    "sells when RSI gets hot again or after 20 calendar days. The ImprovePriority "
    "report said many winners ran up at least 15% (maximum favorable excursion, MFE) "
    "and then gave back 10 or more percentage points before the 20-day time stop. "
    "These tests keep the same buys and only change how we sell, to see if we can "
    "keep more of those runs. In-sample is entries before 2024; after that is "
    "report-only. Research only — not wired into DailyRun."
)
PRIO_QUOTE = (
    "Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out "
    "may lock more of the run (hypothesis; one trail knob)."
)
PRIO_EVIDENCE = (
    "KINS peak~41% -> exit +28.4% (giveback~13pp, 22d, TIME); "
    "CHCI peak~48% -> exit +38.3% (giveback~10pp, 22d, TIME); "
    "CHCI peak~40% -> exit +24.8% (giveback~16pp, 21d, TIME); "
    "CECO peak~16% -> exit +0.8% (giveback~15pp, 21d, TIME); "
    "ALBY peak~25% -> exit +12.5% (giveback~12pp, 22d, TIME)"
)

SORT_CSS = """
th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; touch-action:manipulation; }
th.sortable-th:hover { background:#e2e8f0; }
th.sortable-th .sort-ind::after { content:" \\2195"; opacity:.35; font-size:.85em; }
th.sortable-th.sort-asc .sort-ind::after { content:" \\2191"; opacity:.9; }
th.sortable-th.sort-desc .sort-ind::after { content:" \\2193"; opacity:.9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.4rem; color:#0f172a; background:#f8fafc; }
h1 { font-size:1.35rem; margin:0 0 .35rem; }
h2 { font-size:1.08rem; margin:1.4rem 0 .4rem; border-bottom:1px solid #cbd5e1; padding-bottom:.2rem; }
.meta { color:#475569; font-size:.92rem; max-width:88rem; }
.ask { background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:.75rem 1rem; margin:.7rem 0; max-width:88rem; }
.insight { background:#fff; border:1px solid #e2e8f0; border-radius:8px; padding:.75rem 1rem; margin:.7rem 0; max-width:88rem; }
.keep { background:#dcfce7; }
.hold { background:#fef9c3; }
.dismiss { background:#fee2e2; }
table.sortable { border-collapse:collapse; background:#fff; font-size:.82rem; margin:.45rem 0 1rem; }
table.sortable th, table.sortable td { border:1px solid #e2e8f0; padding:.3rem .45rem; text-align:left; }
table.sortable th { background:#f1f5f9; }
blockquote { margin:.4rem 0; padding-left:.8rem; border-left:3px solid #94a3b8; color:#334155; }
code { font-size:.86em; }
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
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate(e) {
        if (e && e.type === "touchend") e.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) { x.classList.remove("sort-asc", "sort-desc"); x.setAttribute("aria-sort", "none"); });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(e); }
      });
      th.addEventListener("touchend", activate, { passive: false });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(typ)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


@dataclass(frozen=True)
class Arm:
    name: str
    knob: str
    kind: str
    hypothesis: str
    quote: str
    time_stop: int = CTRL_TS
    mfe_arm: float = 0.0
    tight_ts: int = 0
    trail_giveback: float = 0.0
    rsi_drop: float = 0.0
    tp_pct: float = 0.0


ARMS: list[Arm] = [
    Arm(
        "CONTROL",
        "none",
        "control",
        "Frozen stamp exits: sell RSI14 ≥ 70 next open, else flatten at 20 calendar days.",
        "Control book — same TIME-exit giveback ImprovePriority scored.",
    ),
    Arm(
        "EXIT_ts15",
        "rsi_time_stop_days",
        "ts",
        "Flatten 5 days sooner (15 calendar days) so TIME exits do not sit through the last week of giveback.",
        "Evidence exits were 21–22d TIME; HTML: giveback on TIME.",
        time_stop=15,
    ),
    Arm(
        "EXIT_mfe15_ts12",
        "mfe_conditional_time_stop",
        "mfe_ts",
        "Only tighten time stop on the flagged runners: if MFE ≥ 15%, flatten at 12 calendar days; else keep 20d.",
        "winner_peak_giveback: peaked ≥15% MFE then TIME giveback ≥10pp.",
        mfe_arm=15.0,
        tight_ts=12,
    ),
    Arm(
        "EXIT_trail15_8pp",
        "trail_giveback_pp",
        "trail",
        "After MFE ≥ 15%, sell next open once close is ≥8 percentage points below the in-trade peak.",
        "Trail or scale-out may lock more of the run (hypothesis; one trail knob).",
        mfe_arm=15.0,
        trail_giveback=8.0,
    ),
    Arm(
        "EXIT_trail15_10pp",
        "trail_giveback_pp",
        "trail",
        "After MFE ≥ 15%, sell next open once close is ≥10 percentage points below the in-trade peak (HTML threshold).",
        "exited ≥10pp below peak — one trail knob at the scored giveback cut.",
        mfe_arm=15.0,
        trail_giveback=10.0,
    ),
    Arm(
        "EXIT_rsi_roll8",
        "rsi_rollover_drop",
        "rsi_roll",
        "Sell next open when RSI14 drops 8 points from the in-trade high, instead of waiting for RSI 70.",
        "TIME exits waited for 70 while the run had already rolled over.",
        rsi_drop=8.0,
    ),
    Arm(
        "EXIT_tp20",
        "take_profit_pct",
        "tp",
        "Take profit at +20% close (next open). Lock the meat of 16–48% peaks before TIME fade.",
        "KINS/CHCI/ALBY peaks 25–48% then gave back 10–16pp into TIME.",
        tp_pct=20.0,
    ),
]


def _parse_date(raw: Any) -> Optional[date]:
    s = str(raw or "").strip()
    if not s:
        return None
    compact = s.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((s[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (s[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _iso(d: date) -> str:
    return d.isoformat()


def load_ohlcv(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.is_file():
        path = DATA_DIR / f"{sym.lower()}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    if not all(k in cols for k in ("date", "open", "high", "close")):
        return None
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]], errors="coerce").dt.normalize(),
            "Open": pd.to_numeric(df[cols["open"]], errors="coerce"),
            "High": pd.to_numeric(df[cols["high"]], errors="coerce"),
            "Close": pd.to_numeric(df[cols["close"]], errors="coerce"),
        }
    )
    out = out.dropna(subset=["Date", "Open", "Close"]).sort_values("Date").drop_duplicates("Date")
    return out.reset_index(drop=True)


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = _parse_date(raw.get("DATE_OPENED"))
            closed = _parse_date(raw.get("DATE_CLOSED"))
            if opened is None or closed is None:
                continue
            entry = float(raw.get("ENTRY_PRICE") or 0)
            exit_px = float(raw.get("EXIT_PRICE") or 0)
            if entry <= 0 or exit_px <= 0:
                continue
            pnl = float(raw.get("PNL_PCT") or 0)
            days = int(float(raw.get("DAYS_HELD") or 0))
            max_px = float(raw.get("MAX_PRICE") or 0)
            mfe = ((max_px / entry) - 1.0) * 100.0 if max_px > 0 else float("nan")
            rows.append(
                {
                    "symbol": str(raw.get("SYMBOL") or "").upper(),
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "exit_px": exit_px,
                    "exit": str(raw.get("EXIT_TYPE") or ""),
                    "days": days,
                    "pnl": pnl,
                    "pnl_d": SHEET * pnl / 100.0,
                    "max_px": max_px,
                    "mfe": mfe,
                    "giveback": (mfe - pnl) if math.isfinite(mfe) else float("nan"),
                    "rsi_exit": raw.get("RSI14_AT_EXIT"),
                    "early": str(raw.get("EARLY") or "0").strip() in {"1", "true", "True"},
                    "src": raw,
                }
            )
    return rows


def control_trade(src: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": src["symbol"],
        "opened": src["opened"],
        "closed": src["closed"],
        "entry": src["entry"],
        "exit_px": src["exit_px"],
        "exit": src["exit"],
        "days": src["days"],
        "pnl": src["pnl"],
        "pnl_d": src["pnl_d"],
        "mfe": src["mfe"],
        "giveback": src["giveback"],
        "early": False,
    }


def overlay_exit(
    src: dict[str, Any],
    dates: list[date],
    open_: np.ndarray,
    high: np.ndarray,
    close: np.ndarray,
    rsi: np.ndarray,
    arm: Arm,
    date_ix: dict[date, int],
) -> dict[str, Any]:
    if arm.kind == "control":
        return control_trade(src)
    ei = date_ix.get(src["opened"])
    xi = date_ix.get(src["closed"])
    if ei is None or xi is None or xi <= ei:
        return control_trade(src)
    entry = float(src["entry"])
    peak = max(entry, float(high[ei]) if np.isfinite(high[ei]) else entry)
    max_rsi = float(rsi[ei]) if np.isfinite(rsi[ei]) else float("nan")
    n = len(dates)
    for i in range(ei, xi):
        if i > ei:
            if np.isfinite(high[i]):
                peak = max(peak, float(high[i]))
            if np.isfinite(rsi[i]):
                max_rsi = float(rsi[i]) if not math.isfinite(max_rsi) else max(max_rsi, float(rsi[i]))
        held = (dates[i] - dates[ei]).days
        mfe = (peak / entry - 1.0) * 100.0 if entry > 0 else 0.0
        c_pct = (float(close[i]) / entry - 1.0) * 100.0 if entry > 0 and np.isfinite(close[i]) else float("nan")
        giveback = mfe - c_pct if math.isfinite(c_pct) else float("nan")
        fire = ""
        if arm.kind == "ts":
            if np.isfinite(rsi[i]) and rsi[i] >= CTRL_EXIT_RSI:
                fire = "OVERBOUGHT"
            elif held >= arm.time_stop:
                fire = "TIME"
        elif arm.kind == "mfe_ts":
            if np.isfinite(rsi[i]) and rsi[i] >= CTRL_EXIT_RSI:
                fire = "OVERBOUGHT"
            elif arm.mfe_arm > 0 and mfe >= arm.mfe_arm and held >= arm.tight_ts:
                fire = "TIME"
            elif held >= CTRL_TS:
                fire = "TIME"
        elif arm.kind == "trail":
            if (
                arm.mfe_arm > 0
                and mfe >= arm.mfe_arm
                and math.isfinite(giveback)
                and giveback >= arm.trail_giveback
            ):
                fire = "TRAIL"
            elif np.isfinite(rsi[i]) and rsi[i] >= CTRL_EXIT_RSI:
                fire = "OVERBOUGHT"
            elif held >= CTRL_TS:
                fire = "TIME"
        elif arm.kind == "rsi_roll":
            if (
                arm.rsi_drop > 0
                and math.isfinite(max_rsi)
                and np.isfinite(rsi[i])
                and (max_rsi - float(rsi[i])) >= arm.rsi_drop
            ):
                fire = "RSI_ROLL"
            elif np.isfinite(rsi[i]) and rsi[i] >= CTRL_EXIT_RSI:
                fire = "OVERBOUGHT"
            elif held >= CTRL_TS:
                fire = "TIME"
        elif arm.kind == "tp":
            if arm.tp_pct > 0 and math.isfinite(c_pct) and c_pct >= arm.tp_pct:
                fire = "TARGET"
            elif np.isfinite(rsi[i]) and rsi[i] >= CTRL_EXIT_RSI:
                fire = "OVERBOUGHT"
            elif held >= CTRL_TS:
                fire = "TIME"
        if not fire:
            continue
        fill_i = i + 1
        if fill_i >= n:
            break
        px = float(open_[fill_i])
        if not (px > 0 and math.isfinite(px)):
            break
        out_d = dates[fill_i]
        pnl = (px / entry - 1.0) * 100.0
        days = max(1, (out_d - dates[ei]).days)
        return {
            "symbol": src["symbol"],
            "opened": src["opened"],
            "closed": out_d,
            "entry": entry,
            "exit_px": px,
            "exit": fire,
            "days": days,
            "pnl": pnl,
            "pnl_d": SHEET * pnl / 100.0,
            "mfe": mfe,
            "giveback": (mfe - pnl) if math.isfinite(mfe) else float("nan"),
            "early": out_d < src["closed"],
        }
    return control_trade(src)


def slc(rows: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [r for r in rows if r["opened"] < IS_CUT]
    if which == "OOS":
        return [r for r in rows if r["opened"] >= IS_CUT]
    return list(rows)


def _median(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[len(s) // 2]


def _p90(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[int(0.9 * (len(s) - 1))]


def _losing_streak(rows: list[dict[str, Any]]) -> int:
    seq = sorted(rows, key=lambda r: (r["closed"], r["symbol"]))
    best = 0
    cur = 0
    for r in seq:
        if r["pnl"] < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    empty = {
        "n": 0, "wins": 0, "losses": 0, "be": 0, "win_pct": float("nan"),
        "avg_pnl_pct": float("nan"), "avg_wo_max": float("nan"),
        "avg_win_pct": float("nan"), "avg_loss_pct": float("nan"),
        "expectancy_pct": float("nan"), "expectancy_d": float("nan"),
        "pf": float("nan"), "wl_count": float("nan"), "wl_dollar": float("nan"),
        "ann_ror": float("nan"), "max_dd": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_days": float("nan"), "median_days": float("nan"),
        "p90_days": float("nan"), "capital_days": 0.0, "profit_per_cap_day": float("nan"),
        "exits": {}, "n_syms": 0, "losing_streak": 0, "early_n": 0,
        "pct_max_sym": float("nan"), "pct_max_trade": float("nan"),
        "pct_top10": float("nan"), "pct_bot10": float("nan"),
    }
    if not n:
        return empty
    pcts = [float(r["pnl"]) for r in rows]
    dolls = [float(r["pnl_d"]) for r in rows]
    days = [float(r["days"]) for r in rows if r["days"] > 0]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    be = sum(1 for p in pcts if p == 0)
    wo = sorted(pcts)
    avg = float(np.mean(pcts))
    avg_wo = float(np.mean(wo[:-1])) if n > 1 else avg
    sw = sum(x for x in dolls if x > 0)
    sl_ = abs(sum(x for x in dolls if x < 0))
    pf = (sw / sl_) if sl_ > 0 else (sw if sw > 0 else float("nan"))
    ov = overlay_ann_ror_max_dd(
        [
            {
                "pnl": r["pnl"],
                "pnl_d": r["pnl_d"],
                "days": r["days"],
                "closed": r["closed"],
                "opened": r["opened"],
            }
            for r in rows
        ],
        cash=SHEET,
        initial_account=INIT,
    )
    cap = float(ov.get("capital_days") or sum(days))
    total = float(ov.get("pnl_d") or sum(dolls))
    by_sym: dict[str, float] = {}
    for r in rows:
        by_sym[r["symbol"]] = by_sym.get(r["symbol"], 0.0) + float(r["pnl_d"])
    pos_d = [x for x in dolls if x > 0]
    pos_d_sorted = sorted(pos_d, reverse=True)
    top10 = sum(pos_d_sorted[: max(1, int(math.ceil(0.1 * len(pos_d_sorted))))]) if pos_d_sorted else 0.0
    bot = sorted([x for x in dolls if x < 0])
    bot10 = sum(bot[: max(1, int(math.ceil(0.1 * len(bot))))]) if bot else 0.0
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "be": be,
        "win_pct": 100.0 * len(wins) / n,
        "avg_pnl_pct": avg,
        "avg_wo_max": avg_wo,
        "avg_win_pct": float(np.mean(wins)) if wins else float("nan"),
        "avg_loss_pct": float(np.mean(losses)) if losses else float("nan"),
        "expectancy_pct": avg,
        "expectancy_d": total / n,
        "pf": float(pf),
        "wl_count": (len(wins) / len(losses)) if losses else float(len(wins)),
        "wl_dollar": (sw / sl_) if sl_ > 0 else sw,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "avg_days": (sum(days) / len(days)) if days else float("nan"),
        "median_days": _median(days),
        "p90_days": _p90(days),
        "capital_days": cap,
        "profit_per_cap_day": (total / cap) if cap else float("nan"),
        "exits": dict(Counter(str(r["exit"] or "?") for r in rows)),
        "n_syms": len({r["symbol"] for r in rows}),
        "losing_streak": _losing_streak(rows),
        "early_n": sum(1 for r in rows if r.get("early")),
        "pct_max_sym": (100.0 * max(by_sym.values()) / total) if total > 0 else float("nan"),
        "pct_max_trade": (100.0 * max(dolls) / total) if total > 0 else float("nan"),
        "pct_top10": (100.0 * top10 / sw) if sw > 0 else float("nan"),
        "pct_bot10": (100.0 * bot10 / sl_) if sl_ > 0 else float("nan"),
    }


def giveback_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    flagged = [
        r
        for r in rows
        if math.isfinite(r.get("mfe") or float("nan"))
        and r["mfe"] >= 15.0
        and math.isfinite(r.get("giveback") or float("nan"))
        and r["giveback"] >= 10.0
        and r["pnl"] > 0
    ]
    time_flagged = [r for r in flagged if str(r["exit"]).upper() == "TIME"]
    time_n = sum(1 for r in rows if str(r["exit"]).upper() == "TIME")
    return {
        "n_flagged": len(flagged),
        "n_flagged_time": len(time_flagged),
        "n_time": time_n,
        "n_ob": sum(1 for r in rows if str(r["exit"]).upper() == "OVERBOUGHT"),
        "mean_giveback_flagged": float(np.mean([r["giveback"] for r in flagged])) if flagged else float("nan"),
        "mean_mfe_flagged": float(np.mean([r["mfe"] for r in flagged])) if flagged else float("nan"),
        "syms": sorted({r["symbol"] for r in flagged})[:20],
    }


def fmt_pct(x: Any, d: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}%"


def fmt_num(x: Any, d: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}"


def fmt_int(x: Any) -> str:
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_delta_pct(a: Any, b: Any, d: int = 2) -> str:
    try:
        va, vb = float(a), float(b)
    except (TypeError, ValueError):
        return "—"
    if not (math.isfinite(va) and math.isfinite(vb)):
        return "—"
    return f"{va - vb:+.{d}f}"


def verdict_for(ctrl: dict[str, dict[str, Any]], cand: dict[str, dict[str, Any]]) -> str:
    """KEEP only if IS quality up and DD not worse; OOS soften → HOLD."""
    c_is, a_is = ctrl["IS"], cand["IS"]
    c_oos, a_oos = ctrl["OOS"], cand["OOS"]
    if a_is["n"] <= 0:
        return "HOLD"
    n_ok = a_is["n"] >= 0.9 * c_is["n"]
    avg_up = a_is["avg_pnl_pct"] > c_is["avg_pnl_pct"] + 0.05
    exp_up = a_is["expectancy_pct"] > c_is["expectancy_pct"] + 0.05
    dd_ok = True
    if math.isfinite(float(a_is["max_dd"] or float("nan"))) and math.isfinite(
        float(c_is["max_dd"] or float("nan"))
    ):
        dd_ok = float(a_is["max_dd"]) <= float(c_is["max_dd"]) + 0.20
    avg_down = a_is["avg_pnl_pct"] < c_is["avg_pnl_pct"] - 0.10
    oos_soft = False
    if a_oos["n"] > 0 and c_oos["n"] > 0:
        oos_soft = a_oos["avg_pnl_pct"] < c_oos["avg_pnl_pct"] - 0.10
    if avg_down or not n_ok:
        return "DISMISS"
    if avg_up and exp_up and dd_ok:
        if oos_soft:
            return "HOLD"
        return "KEEP"
    return "HOLD"


def run_overlay(src_rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for r in src_rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    cache: dict[str, tuple[list[date], np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[date, int]]] = {}
    miss = 0
    for sym in by_sym:
        df = load_ohlcv(sym)
        if df is None or df.empty:
            miss += 1
            continue
        dates = [d.date() if hasattr(d, "date") else d for d in df["Date"]]
        open_ = df["Open"].to_numpy(dtype=float)
        high = df["High"].to_numpy(dtype=float)
        close = df["Close"].to_numpy(dtype=float)
        rsi = _wilder_rsi14_arr(close)
        ix = {d: i for i, d in enumerate(dates)}
        cache[sym] = (dates, open_, high, close, rsi, ix)
    print(f"Loaded OHLC for {len(cache)} / {len(by_sym)} symbols ({miss} missing files)", flush=True)
    out: dict[str, list[dict[str, Any]]] = {a.name: [] for a in ARMS}
    replay_mismatch = 0
    for src in src_rows:
        pack_sym = cache.get(src["symbol"])
        for arm in ARMS:
            if pack_sym is None:
                out[arm.name].append(control_trade(src))
                continue
            dates, open_, high, close, rsi, ix = pack_sym
            t = overlay_exit(src, dates, open_, high, close, rsi, arm, ix)
            out[arm.name].append(t)
        # sanity: replaying CONTROL rules (ts=20 + RSI70) should usually match
        if pack_sym is not None:
            dates, open_, high, close, rsi, ix = pack_sym
            replay = overlay_exit(
                src, dates, open_, high, close, rsi,
                Arm("REPLAY", "none", "ts", "", "", time_stop=CTRL_TS),
                ix,
            )
            if abs(replay["pnl"] - src["pnl"]) > 0.75 or replay["exit"] != src["exit"]:
                replay_mismatch += 1
    return out, {"missing_symbols": miss, "replay_mismatch": replay_mismatch, "n_src": len(src_rows)}


def _exit_cell(exits: dict[str, int], key: str) -> str:
    n = int(exits.get(key, 0))
    tot = sum(exits.values()) or 1
    return f"{n} ({100.0 * n / tot:.1f}%)"


def write_csv_books(by_arm: dict[str, list[dict[str, Any]]]) -> None:
    for name, rows in by_arm.items():
        path = OUT_DIR / f"overlay_{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "SYMBOL", "DATE_OPENED", "DATE_CLOSED", "ENTRY_PRICE", "EXIT_PRICE",
                    "EXIT_TYPE", "DAYS_HELD", "PNL_PCT", "PNL_DOLLARS", "EARLY",
                ],
            )
            w.writeheader()
            for r in rows:
                w.writerow(
                    {
                        "SYMBOL": r["symbol"],
                        "DATE_OPENED": r["opened"].strftime("%Y%m%d"),
                        "DATE_CLOSED": r["closed"].strftime("%Y%m%d"),
                        "ENTRY_PRICE": f"{r['entry']:.4f}",
                        "EXIT_PRICE": f"{r['exit_px']:.4f}",
                        "EXIT_TYPE": r["exit"],
                        "DAYS_HELD": r["days"],
                        "PNL_PCT": f"{r['pnl']:.4f}",
                        "PNL_DOLLARS": f"{r['pnl_d']:.2f}",
                        "EARLY": int(bool(r.get("early"))),
                    }
                )


def _metric_row(label: str, typ: str, getter) -> tuple[str, str, Any]:
    return (label, typ, getter)


def write_html(
    packs: dict[str, dict[str, dict[str, Any]]],
    verdicts: dict[str, str],
    gb: dict[str, Any],
    sanity: dict[str, int],
) -> Path:
    names = [a.name for a in ARMS]
    ctrl = packs["CONTROL"]
    headline_cols = filter_html_compare_columns(
        [("Arm", "text"), ("Kind", "text"), ("Verdict", "text"), ("Knob", "text")]
        + [
            (f"{sl} N", "num")
            for sl in ("FULL", "IS", "OOS")
        ]
        + [
            (f"{sl} Avg%", "num")
            for sl in ("FULL", "IS", "OOS")
        ]
        + [
            (f"{sl} Ann ROR %", "num")
            for sl in ("FULL", "IS", "OOS")
        ]
        + [
            (f"{sl} ΔAvg% vs ctrl", "num")
            for sl in ("FULL", "IS", "OOS")
        ]
        + [
            ("IS Max DD%", "num"),
            ("OOS Max DD%", "num"),
            ("FULL early exits", "num"),
        ]
    )
    hth = "".join(sortable_th(a, b) for a, b in headline_cols)
    hbody = []
    for arm in ARMS:
        p = packs[arm.name]
        v = verdicts.get(arm.name, "—")
        hbody.append(
            "<tr>"
            f"<td>{html_mod.escape(arm.name)}</td>"
            f"<td>EXIT</td>"
            f"<td>{html_mod.escape(v)}</td>"
            f"<td>{html_mod.escape(arm.knob)}</td>"
            f"<td>{fmt_int(p['FULL']['n'])}</td>"
            f"<td>{fmt_int(p['IS']['n'])}</td>"
            f"<td>{fmt_int(p['OOS']['n'])}</td>"
            f"<td>{fmt_pct(p['FULL']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_pct(p['IS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_pct(p['OOS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_pct(p['FULL']['ann_ror'])}</td>"
            f"<td>{fmt_pct(p['IS']['ann_ror'])}</td>"
            f"<td>{fmt_pct(p['OOS']['ann_ror'])}</td>"
            f"<td>{fmt_delta_pct(p['FULL']['avg_pnl_pct'], ctrl['FULL']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_delta_pct(p['IS']['avg_pnl_pct'], ctrl['IS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_delta_pct(p['OOS']['avg_pnl_pct'], ctrl['OOS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_pct(p['IS']['max_dd'])}</td>"
            f"<td>{fmt_pct(p['OOS']['max_dd'])}</td>"
            f"<td>{fmt_int(p['FULL']['early_n'])}</td>"
            "</tr>"
        )

    # Canonical book table: one row per metric, columns = slice × arm (FULL first)
    metric_specs: list[tuple[str, str, str]] = [
        ("Total trades", "num", "n"),
        ("Wins", "num", "wins"),
        ("Losses", "num", "losses"),
        ("Win %", "num", "win_pct"),
        ("Avg PnL %", "num", "avg_pnl_pct"),
        ("Book AVG_PNL_PCT_WO_MAX", "num", "avg_wo_max"),
        ("Expectancy $", "money", "expectancy_d"),
        ("Expectancy %", "num", "expectancy_pct"),
        ("Avg win %", "num", "avg_win_pct"),
        ("Avg loss %", "num", "avg_loss_pct"),
        ("Win/Loss ratio (count)", "num", "wl_count"),
        ("Win/Loss ratio $", "num", "wl_dollar"),
        ("Profit factor", "num", "pf"),
        ("Ann ROR %", "num", "ann_ror"),
        ("Max DD %", "num", "max_dd"),
        ("Calmar", "num", "calmar"),
        ("Sharpe", "num", "sharpe"),
        ("Profit per capital day", "money", "profit_per_cap_day"),
        ("Capital days", "num", "capital_days"),
        ("Avg days held", "num", "avg_days"),
        ("Median days held", "num", "median_days"),
        ("P90 days held", "num", "p90_days"),
        ("Losing streak", "num", "losing_streak"),
        ("Pct PnL max symbol", "num", "pct_max_sym"),
        ("Pct PnL max trade", "num", "pct_max_trade"),
        ("Pct PnL top10", "num", "pct_top10"),
        ("Pct PnL bottom10", "num", "pct_bot10"),
    ]
    # Universe size as extra
    book_headers = [("Metric", "text"), ("Slice", "text")]
    for nm in names:
        book_headers.append((nm, "num"))
        if nm != "CONTROL":
            book_headers.append((f"Δ {nm}", "num"))
    book_headers = filter_html_compare_columns(book_headers)
    bth = "".join(sortable_th(a, b) for a, b in book_headers)
    bbody = []
    na_note_rows = [
        ("Universe size", "FULL", "n_syms"),
    ]
    for sl in ("FULL", "IS", "OOS"):
        bbody.append(
            "<tr>"
            f"<td>Universe size (symbols traded)</td><td>{sl}</td>"
            + "".join(
                (
                    f"<td>{fmt_int(packs[nm][sl]['n_syms'])}</td>"
                    + (
                        f"<td>{fmt_int(packs[nm][sl]['n_syms'] - ctrl[sl]['n_syms'])}</td>"
                        if nm != "CONTROL"
                        else ""
                    )
                )
                for nm in names
            )
            + "</tr>"
        )
        for label, typ, key in metric_specs:
            cells = [f"<td>{html_mod.escape(label)}</td>", f"<td>{sl}</td>"]
            for nm in names:
                val = packs[nm][sl][key]
                if typ == "money":
                    cell = format_money(val)
                elif key in {
                    "win_pct", "avg_pnl_pct", "avg_wo_max", "expectancy_pct",
                    "avg_win_pct", "avg_loss_pct", "ann_ror", "max_dd",
                    "pct_max_sym", "pct_max_trade", "pct_top10", "pct_bot10",
                }:
                    cell = fmt_pct(val)
                elif key in {"n", "wins", "losses", "capital_days", "losing_streak"}:
                    cell = fmt_int(val)
                else:
                    cell = fmt_num(val)
                cells.append(f"<td>{cell}</td>")
                if nm != "CONTROL":
                    cv = ctrl[sl][key]
                    if typ == "money":
                        try:
                            dlt = float(val) - float(cv)
                            cells.append(f"<td>{dlt:+,.2f}</td>")
                        except (TypeError, ValueError):
                            cells.append("<td>—</td>")
                    elif key in {"n", "wins", "losses", "capital_days", "losing_streak"}:
                        try:
                            cells.append(f"<td>{int(val) - int(cv):+,d}</td>")
                        except (TypeError, ValueError):
                            cells.append("<td>—</td>")
                    else:
                        cells.append(f"<td>{fmt_delta_pct(val, cv)}</td>")
            bbody.append("<tr>" + "".join(cells) + "</tr>")
        # N/A overlay rows once per slice
        for lab in (
            "Avg days underwater",
            "P90 days underwater",
            "Max days underwater (equity)",
            "% days underwater (equity)",
            "Avg positions",
            "Median positions",
            "Max positions",
            "Aggressive Total PnL $",
            "Aggressive Max DD %",
            "Pct PnL max industry",
            "CES avg",
            "CES median",
            "Σ Paul Score",
            "Mean Paul Score",
            "Σ FIT Score",
            "Mean FIT Score",
            "Σ FIT Score Robust",
            "Mean FIT Score Robust",
            "Mean AVG_PNL_PCT_WO_MAX",
            "Mean OUTLIER_PCT_OF_WINS",
            "Mean AVG_TRADES_PER_YEAR",
            "Mean MAX_WIN_PCT",
        ):
            cells = [f"<td>{html_mod.escape(lab)}</td>", f"<td>{sl}</td>"]
            for nm in names:
                cells.append("<td>N/A</td>")
                if nm != "CONTROL":
                    cells.append("<td>—</td>")
            bbody.append("<tr>" + "".join(cells) + "</tr>")

    exit_keys = sorted({k for arm in ARMS for k in packs[arm.name]["FULL"]["exits"]})
    eth = "".join(
        sortable_th(a, b)
        for a, b in [("Arm", "text"), ("Slice", "text")]
        + [(k, "text") for k in exit_keys]
    )
    ebody = []
    for sl in ("FULL", "IS", "OOS"):
        for arm in ARMS:
            ex = packs[arm.name][sl]["exits"]
            ebody.append(
                "<tr>"
                f"<td>{html_mod.escape(arm.name)}</td><td>{sl}</td>"
                + "".join(f"<td>{_exit_cell(ex, k)}</td>" for k in exit_keys)
                + "</tr>"
            )

    arm_rows = []
    for arm in ARMS:
        v = verdicts.get(arm.name, "—")
        klass = v.lower() if v in {"KEEP", "HOLD", "DISMISS"} else ""
        arm_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm.name)}</td>"
            f"<td>EXIT</td>"
            f"<td>{html_mod.escape(arm.knob)}</td>"
            f"<td>{html_mod.escape(arm.hypothesis)}</td>"
            f"<td>{html_mod.escape(arm.quote)}</td>"
            f"<td class='{klass}'>{html_mod.escape(v)}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RSI giveback lock-in EXIT AB — {STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>RSI giveback lock-in — EXIT A/B (research only)</h1>
<p class="meta">Stamp <code>{STAMP}</code> · source Closed <code>RSI_Closed_{SRC_TS}.csv</code> ·
entries frozen · overlay exits only · IS = entry &lt; 2024-01-01 · OOS report-only ·
not gold · not DailyRun. Click column headers to sort.</p>

<div class="ask">
  <h2>What you asked</h2>
  <p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
  <h2>In plain English</h2>
  <p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>

<div class="insight">
  <h2>What ImprovePriority said we give back</h2>
  <p><strong>Taken-trade pattern</strong> <code>winner_peak_giveback</code> — 41 symbols / 52 trades.
  Lever: trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out.</p>
  <blockquote>{html_mod.escape(PRIO_QUOTE)}</blockquote>
  <blockquote>{html_mod.escape(PRIO_EVIDENCE)}</blockquote>
  <p>Parameter-tweak cards: none met threshold. Peer-learn: no countable adopt pattern.
  Closed overlay on this book: {fmt_int(gb['n_flagged'])} winners with MFE ≥15% and giveback ≥10pp
  ({fmt_int(gb['n_flagged_time'])} of them TIME). Control exit mix: TIME {fmt_int(gb['n_time'])},
  OVERBOUGHT {fmt_int(gb['n_ob'])}. Replay sanity: {sanity['replay_mismatch']} / {sanity['n_src']}
  trades differ vs a raw RSI≥70 / 20d replay (control uses the stamp Closed as-is).</p>
</div>

<div class="insight">
  <h2>Freeze (ENTRY unchanged)</h2>
  <p>Stamp <code>{SRC_TS}</code>: Neutral-after-overbought, <code>rsi_ob=70</code>,
  <code>rsi_os=30</code>, <code>rsi_max_trigger=60</code>, <code>rsi_min_atr_pct={CTRL_ATR:g}</code>,
  min distance to 52-week high <strong>off</strong>, <code>rsi_exit=70</code>,
  <code>rsi_time_stop_days=20</code>, fill next open, sheet ${SHEET:,.0f}.
  Overlay Max DD / Sharpe seed ${INIT:,.0f} (exit-date equity). Paul / FIT / daily underwater /
  position counts are N/A on this Closed overlay (no per-arm Summary / EquityCurve rebuild).
  Sibling DailyRun atr=2.93 / no min_dist wire was left alone.</p>
</div>

<h2>Arms (all EXIT, one knob)</h2>
<p class="meta">One hypothesis per arm. Trail has two pre-agreed cuts (8pp and the HTML 10pp). Existing engine knob: <code>rsi_time_stop_days</code> on EXIT_ts15. Other arms are research overlay only (flags default off / not wired).</p>
<table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Kind", "text")}{sortable_th("Knob", "text")}{sortable_th("Hypothesis", "text")}{sortable_th("ImprovePriority line tested", "text")}{sortable_th("Verdict", "text")}
</tr></thead><tbody>{"".join(arm_rows)}</tbody></table>

<h2>Headline N / Avg% (FULL / IS / OOS)</h2>
<p class="meta">Click column headers to sort. Ann ROR (Annualized Rate of Return) is the same Closed-overlay figure already in the canonical table (<code>overlay_ann_ror_max_dd</code>, $10k notional, $500k seed, exit-date equity). KEEP needs IS Avg% and expectancy up without wrecking N or DD; OOS soften → HOLD. Quality over count.</p>
<table class="sortable"><thead><tr>{hth}</tr></thead><tbody>{"".join(hbody)}</tbody></table>

<h2>Canonical book metrics (Closed overlay)</h2>
<p class="meta">Click column headers to sort. Sheet / Total PnL $ omitted. Ann ROR / Max DD / Calmar / Sharpe from Closed overlay ($10k notional, $500k seed, exit-date equity). Deltas vs CONTROL on the same slice. Underwater / positions / Paul / FIT = N/A (no daily curve or Summary rebuild).</p>
<table class="sortable"><thead><tr>{bth}</tr></thead><tbody>{"".join(bbody)}</tbody></table>

<h2>Exit mix</h2>
<p class="meta">Click column headers to sort. Counts and % of that slice.</p>
<table class="sortable"><thead><tr>{eth}</tr></thead><tbody>{"".join(ebody)}</tbody></table>

<div class="insight">
  <h2>Honesty</h2>
  <ul>
    <li>EXIT overlay on frozen entries. Choosing these knobs after seeing ImprovePriority on the same Closed book is <strong>in-sample selection</strong>.</li>
    <li>OOS is report-only. Do not retune on OOS. OOS soften → HOLD, not a new hunt.</li>
    <li>Research candidate only. Not gold. Not DailyRun. Do not steal LatestRun.</li>
    <li>Overlay cannot invent a later fill that the original time-stop already closed; arms only exit <em>earlier or same</em>.</li>
    <li>All six arms <strong>DISMISS</strong>: earlier exits cut average win % more than they saved giveback. Least-bad was <code>EXIT_trail15_10pp</code>. <code>EXIT_rsi_roll8</code> was worst. Do not hunt a new trail cut on this same book.</li>
  </ul>
</div>
{SORT_JS}
</body>
</html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(
    packs: dict[str, dict[str, dict[str, Any]]],
    verdicts: dict[str, str],
    gb: dict[str, Any],
    sanity: dict[str, int],
) -> Path:
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "**Status:** Research-only EXIT overlay. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "## ImprovePriority lines tested",
        "",
        f"- Pattern: `winner_peak_giveback` (41 symbols / 52 trades).",
        f"- Suggestion: {PRIO_QUOTE}",
        f"- Evidence: {PRIO_EVIDENCE}",
        "- Parameter suggestions: none met threshold.",
        "- Peer-learn: no countable adopt pattern.",
        f"- Closed recount on stamp `{SRC_TS}`: {gb['n_flagged']} winners with MFE≥15% and giveback≥10pp "
        f"({gb['n_flagged_time']} TIME). Control TIME={gb['n_time']} OVERBOUGHT={gb['n_ob']}.",
        "",
        "## Freeze (ENTRY unchanged)",
        "",
        f"| Knob | Value |",
        f"|------|-------|",
        f"| Source Closed | `drive/RSI_Closed_{SRC_TS}.csv` |",
        f"| Kind | EXIT overlay (entries frozen) |",
        f"| rsi_ob / rsi_os | 70 / 30 |",
        f"| rsi_max_trigger | 60 |",
        f"| rsi_min_atr_pct | {CTRL_ATR:g} |",
        f"| min_dist_to_52w_high | off |",
        f"| rsi_exit | 70 |",
        f"| rsi_time_stop_days (control) | 20 calendar |",
        f"| Fill | next open |",
        f"| Sheet notional | ${SHEET:,.0f} |",
        f"| Overlay seed | ${INIT:,.0f} |",
        f"| IS cut | entry_date < 2024-01-01 |",
        "",
        "Do not retune entries. Sibling DailyRun atr=2.93 / no min_dist wire was not touched.",
        "",
        "## Arms",
        "",
        "| Arm | Kind | Knob | Hypothesis | Verdict |",
        "|-----|------|------|------------|---------|",
    ]
    for arm in ARMS:
        lines.append(
            f"| {arm.name} | EXIT | `{arm.knob}` | {arm.hypothesis} | {verdicts.get(arm.name, '—')} |"
        )
    lines += [
        "",
        "## FULL / IS / OOS Avg% vs control",
        "",
        "Ann ROR (Annualized Rate of Return) is the same Closed-overlay figure as `overlay_ann_ror_max_dd` on compare.html.",
        "",
        "| Arm | FULL N | FULL Avg% | FULL Ann ROR | Δ FULL | IS N | IS Avg% | IS Ann ROR | Δ IS | OOS N | OOS Avg% | OOS Ann ROR | Δ OOS | Verdict |",
        "|-----|--------|-----------|--------------|--------|------|---------|------------|------|-------|----------|-------------|-------|---------|",
    ]
    ctrl = packs["CONTROL"]
    for arm in ARMS:
        p = packs[arm.name]
        lines.append(
            f"| {arm.name} | {p['FULL']['n']} | {p['FULL']['avg_pnl_pct']:.2f}% | "
            f"{p['FULL']['ann_ror']:.2f}% | "
            f"{p['FULL']['avg_pnl_pct'] - ctrl['FULL']['avg_pnl_pct']:+.2f} | "
            f"{p['IS']['n']} | {p['IS']['avg_pnl_pct']:.2f}% | "
            f"{p['IS']['ann_ror']:.2f}% | "
            f"{p['IS']['avg_pnl_pct'] - ctrl['IS']['avg_pnl_pct']:+.2f} | "
            f"{p['OOS']['n']} | {p['OOS']['avg_pnl_pct']:.2f}% | "
            f"{p['OOS']['ann_ror']:.2f}% | "
            f"{p['OOS']['avg_pnl_pct'] - ctrl['OOS']['avg_pnl_pct']:+.2f} | "
            f"{verdicts.get(arm.name, '—')} |"
        )
    lines += [
        "",
        "## Honesty",
        "",
        "- One knob per arm. Trail 8pp vs 10pp are two pre-agreed alternatives of the same trail hypothesis.",
        "- Knobs chosen from ImprovePriority on this same Closed book → in-sample selection. Labeled.",
        "- OOS report-only. Soften vs IS → HOLD, do not retune OOS.",
        "- Quality over count. KEEP only if IS Avg% / expectancy / DD improve without wrecking N.",
        f"- Overlay replay sanity: {sanity['replay_mismatch']} / {sanity['n_src']} trades differ vs RSI≥70/20d rebuild; control uses stamp Closed prices.",
        "- Paul / FIT / daily underwater N/A (Closed overlay, no Summary rebuild).",
        "- Why all DISMISS: earlier exits cut avg win % more than they saved giveback. Least-bad was `EXIT_trail15_10pp`. `EXIT_rsi_roll8` was worst. Do not hunt a new trail cut on this same book.",
        "- Research candidate ≠ gold ≠ DailyRun. No exit wire.",
        "",
        f"Compare: `drive/paul_experiments/{STAMP}/compare.html`",
        "",
    ]
    path = OUT_DIR / "BASELINE.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_hypothesis() -> Path:
    text = f"""# HYPOTHESIS — {STAMP}

| Field | Fill |
|-------|------|
| System / prefix | RSI (Relative Strength Index) |
| Baseline stamp | `{SRC_TS}` Closed |
| Universe | Same names/fills as `RSI_Closed_{SRC_TS}.csv` (atr=2.93, no min_dist) |
| Evidence | ImprovePriority `winner_peak_giveback` — 41 sym / 52 trades; TIME 21–22d giveback after MFE≥15% |
| Hypothesis | One-knob EXIT overlays can lock more of those runs without wrecking IS quality |
| Single knob | One per arm (see BASELINE) |
| Frozen settings | Entries + rsi_exit=70 + ts=20 unless the arm's one EXIT knob |
| Alternatives | ≤6 EXIT arms; trail has 8pp and 10pp |
| Decision | Research KEEP/HOLD/DISMISS on quality; not DailyRun |

OOS (`entry_date >= 2024-01-01`) is report-only.
"""
    path = OUT_DIR / "HYPOTHESIS.md"
    path.write_text(text, encoding="utf-8")
    return path


def write_plan() -> Path:
    text = f"""# AB_PLAN — {STAMP}

## Evidence → knob

Quoted from `RSI_ImprovePriority_{SRC_TS}.html` / ImproveHints:

> {PRIO_QUOTE}

> {PRIO_EVIDENCE}

| Arm | Knob | Why this line |
|-----|------|----------------|
| EXIT_ts15 | `rsi_time_stop_days=15` | Giveback is on TIME 21–22d |
| EXIT_mfe15_ts12 | MFE≥15% → time-stop 12d | Only the flagged runners |
| EXIT_trail15_8pp | trail 8pp after MFE≥15% | “one trail knob” |
| EXIT_trail15_10pp | trail 10pp after MFE≥15% | HTML ≥10pp giveback cut |
| EXIT_rsi_roll8 | RSI drop 8 from in-trade max | vs wait for 70 |
| EXIT_tp20 | take profit +20% | lock 16–48% peaks before TIME fade |

Skipped: ENTRY retunes, peer-learn (no edge), parameter band cards (none met threshold),
partial scale-out (two-fill book; not one overlay price).

## Execution

Closed overlay on stamp `{SRC_TS}`. Same entries. Exit earlier or same. IS/OOS reported.
"""
    path = OUT_DIR / "AB_PLAN.md"
    path.write_text(text, encoding="utf-8")
    return path


def rebuild_html_from_overlays() -> int:
    """Repack existing overlay_*.csv books and rewrite compare.html / BASELINE.md."""
    src_rows = load_closed(SRC_CLOSED)
    gb = giveback_stats(src_rows)
    meta_path = OUT_DIR / "run_meta.json"
    sanity = {"missing_symbols": 0, "replay_mismatch": 0, "n_src": len(src_rows)}
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        sanity = {**sanity, **(meta.get("sanity") or {})}
    packs: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in ARMS:
        path = OUT_DIR / f"overlay_{arm.name}.csv"
        if not path.is_file():
            print(f"Missing {path}", file=sys.stderr)
            return 2
        rows = load_closed(path)
        packs[arm.name] = {sl: pack(slc(rows, sl)) for sl in ("FULL", "IS", "OOS")}
    verdicts = {"CONTROL": "CONTROL"}
    for arm in ARMS:
        if arm.name == "CONTROL":
            continue
        verdicts[arm.name] = verdict_for(packs["CONTROL"], packs[arm.name])
    html_path = write_html(packs, verdicts, gb, sanity)
    base_path = write_baseline(packs, verdicts, gb, sanity)
    print(f"Wrote {html_path}", flush=True)
    print(f"Wrote {base_path}", flush=True)
    return 0


def main() -> int:
    if "--html-only" in sys.argv:
        return rebuild_html_from_overlays()
    if not SRC_CLOSED.is_file():
        print(f"Missing {SRC_CLOSED}", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src_rows = load_closed(SRC_CLOSED)
    print(f"Loaded {len(src_rows)} Closed trades from {SRC_CLOSED.name}", flush=True)
    gb = giveback_stats(src_rows)
    print(
        f"Giveback flag MFE>=15 & >=10pp: {gb['n_flagged']} "
        f"(TIME {gb['n_flagged_time']}); TIME={gb['n_time']} OB={gb['n_ob']}",
        flush=True,
    )
    by_arm, sanity = run_overlay(src_rows)
    write_csv_books(by_arm)
    packs: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in ARMS:
        rows = by_arm[arm.name]
        packs[arm.name] = {sl: pack(slc(rows, sl)) for sl in ("FULL", "IS", "OOS")}
        print(
            f"{arm.name:20s} FULL N={packs[arm.name]['FULL']['n']:4d} "
            f"Avg%={packs[arm.name]['FULL']['avg_pnl_pct']:.2f} "
            f"IS={packs[arm.name]['IS']['avg_pnl_pct']:.2f} "
            f"OOS={packs[arm.name]['OOS']['avg_pnl_pct']:.2f} "
            f"early={packs[arm.name]['FULL']['early_n']}",
            flush=True,
        )
    verdicts = {"CONTROL": "CONTROL"}
    for arm in ARMS:
        if arm.name == "CONTROL":
            continue
        verdicts[arm.name] = verdict_for(packs["CONTROL"], packs[arm.name])
    html_path = write_html(packs, verdicts, gb, sanity)
    base_path = write_baseline(packs, verdicts, gb, sanity)
    write_hypothesis()
    write_plan()
    (OUT_DIR / "run_meta.json").write_text(
        json.dumps(
            {
                "source_closed": str(SRC_CLOSED.as_posix()),
                "improve_priority": str(SRC_PRIO.as_posix()),
                "improve_hints": str(SRC_HINTS.as_posix()),
                "sanity": sanity,
                "giveback": {k: (v if not isinstance(v, list) else v) for k, v in gb.items()},
                "verdicts": verdicts,
                "n_src": len(src_rows),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {html_path}", flush=True)
    print(f"Wrote {base_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
