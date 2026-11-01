#!/usr/bin/env python3
"""Cross-system overlap *outcome* report (research only).

What happens when 2+ DailyRun sleeves buy the same ticker — same day /
adjacent session, or overlapping holds. Not the live name-count page
(``generate_system_convergence_report.py``); this is PnL after overlap.

House pins / LatestRun Closed only. Does not mutate DailyRun freezes.
Not gold. Not a wire-up.

Usage:
  python tools/cross_system_overlap_20260915.py
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)
from dailyrun_system_status import (  # noqa: E402
    DAILYRUN_REGISTRY,
    LIVE_EXCLUDE,
    live_convergence_systems,
    live_wired_systems,
)

DRIVE = ROOT / "drive"
STAMP = "cross_system_overlap_20260915"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
SLOT_10K = 10_000.0

ORIGINAL_REQUEST = (
    "can you run a full cross-system report to see what happens when 2 "
    "systems overlap a buy order on a stock?"
)
LAYMAN = (
    "Sometimes two DailyRun sleeves want the same ticker. This report lists "
    "those overlaps and whether the second buy helped, hurt, or just doubled "
    "exposure — vs names only one system bought. In-sample means the trade "
    "opened before 2024; later years are a check only. This is research, not "
    "a live change."
)

SYSTEM_EXPAND: dict[str, str] = {
    "BRT": "Break and ReTest (BRT)",
    "IND": "Industry (IND, deprecated — not DailyRun-wired)",
    "RL": "Rocket Launcher (RL)",
    "YH": "Year High (YH)",
    "MTS": "Magic Touch (MTS)",
    "WPBR": "Weekly Pivot Break and Retest (WPBR)",
    "RS": "Relative Strength vs SPY (RS)",
    "SB": "StockBee (SB)",
    "VZ": "Volume Zone (VZ)",
    "RSI": "Relative Strength Index (RSI)",
    "WRL": "Weekly Range / Swing (WRL, research — not DailyRun gold)",
}

SHEET_CASH: dict[str, float] = {
    "VZ": 45_000.0,
    "RSI": 10_000.0,
    "BRT": 47_500.0,
    "RL": 47_500.0,
    "YH": 47_500.0,
    "MTS": 47_500.0,
    "WPBR": 47_500.0,
    "RS": 47_500.0,
    "SB": 47_500.0,
    "IND": 47_500.0,
    "WRL": 47_500.0,
}

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
h3 { font-size: 1.02rem; margin: 1.1rem 0 .4rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 88rem; }
.callout { background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; padding: .85rem 1.1rem; margin: .75rem 0; max-width: 88rem; }
.ask { border-left: 4px solid #2563eb; }
.plain { border-left: 4px solid #047857; }
.warn { border-left: 4px solid #b45309; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
.HOLD { background: #fef3c7; }
.KEEP, .LEAN { background: #d1fae5; }
.DISMISS { background: #fee2e2; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.total-row { font-weight: 700; background: #f8fafc; }
.delta-pos { color: #047857; }
.delta-neg { color: #b91c1c; }
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
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _parse_date(v: Any) -> Optional[date]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    if len(s) >= 8 and s[:8].isdigit() and "-" not in s[:8]:
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    try:
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def _num(v: Any) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    s = str(v).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.lower() in ("nan", "none"):
        return float("nan")
    try:
        x = float(s)
    except ValueError:
        return float("nan")
    return x if math.isfinite(x) else float("nan")


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    want = {n.upper().replace("_", " ") for n in names}
    for c in df.columns:
        key = str(c).upper().replace("_", " ")
        if key in want:
            return str(c)
    return None


def _read_ts_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        ts = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return None
    return ts if ts.isdigit() and len(ts) == 12 else None


def next_session(d: date) -> date:
    """Next weekday (holiday-blind). Friday → Monday."""
    wd = d.weekday()
    if wd == 4:
        return d + timedelta(days=3)
    if wd == 5:
        return d + timedelta(days=2)
    return d + timedelta(days=1)


def discover_systems(drive: Path) -> list[str]:
    """Wired DailyRun + LatestRun extras (IND / WRL if present). No RSIN."""
    seen: list[str] = []
    extras = live_convergence_systems(drive) if drive.is_dir() else []
    for sys in (*live_wired_systems(), *extras):
        key = str(sys or "").strip().upper()
        if not key or key in LIVE_EXCLUDE:
            continue
        if key not in seen:
            seen.append(key)
    return seen


def resolve_closed_path(drive: Path, system: str) -> tuple[Optional[Path], str]:
    """House pin first for VZ / RSI; else LatestRun Closed. No newest-glob."""
    sys = system.upper()
    if sys in {"VZ", "RSI"}:
        ts = _read_ts_file(drive / f"{sys}_house_last_run_ts.txt")
        if ts:
            house = drive / f"{sys}_Closed_{ts}.csv"
            if house.is_file():
                return house, ts
    latest = drive / f"{sys}_LatestRun_Closed.csv"
    if latest.is_file():
        return latest, "LatestRun"
    if sys == "WPBR":
        legacy = drive / "PBR_LatestRun_Closed.csv"
        if legacy.is_file():
            return legacy, "LatestRun(PBR)"
    return None, ""


def load_closed_fills(prefix: str, drive: Path) -> tuple[list[dict[str, Any]], str, str]:
    path, pin = resolve_closed_path(drive, prefix)
    if path is None:
        return [], pin, ""
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    except Exception:
        return [], pin, str(path.name)
    if df.empty:
        return [], pin, path.name
    sym_c = _col(df, "SYMBOL")
    open_c = _col(df, "DATE_OPENED", "DATE OPENED")
    close_c = _col(df, "DATE_CLOSED", "DATE CLOSED")
    entry_c = _col(df, "ENTRY_PRICE", "ENTRY PRICE")
    pnl_c = _col(df, "PNL_PCT", "PNL %", "PNL%")
    pnl_d_c = _col(df, "PNL_DOLLARS", "PNL $", "PNL$")
    days_c = _col(df, "DAYS_HELD", "DAYS HELD")
    exit_c = _col(df, "EXIT_TYPE", "EXIT TYPE")
    side_c = _col(df, "SIDE")
    if not sym_c or not open_c:
        return [], pin, path.name
    cash = SHEET_CASH.get(prefix.upper(), 47_500.0)
    out: list[dict[str, Any]] = []
    syms = df[sym_c].tolist()
    opens = df[open_c].tolist()
    closes = df[close_c].tolist() if close_c else [None] * len(df)
    entries = df[entry_c].tolist() if entry_c else [None] * len(df)
    pnls = df[pnl_c].tolist() if pnl_c else [None] * len(df)
    pnl_ds = df[pnl_d_c].tolist() if pnl_d_c else [None] * len(df)
    days_col = df[days_c].tolist() if days_c else [None] * len(df)
    exits = df[exit_c].tolist() if exit_c else ["—"] * len(df)
    sides = df[side_c].tolist() if side_c else ["LONG"] * len(df)
    for i in range(len(df)):
        sym = str(syms[i] or "").strip().upper()
        opened = _parse_date(opens[i])
        if not sym or opened is None:
            continue
        pnl = _num(pnls[i])
        pnl_d = _num(pnl_ds[i])
        if not math.isfinite(pnl_d) and math.isfinite(pnl):
            pnl_d = cash * pnl / 100.0
        if not math.isfinite(pnl) and math.isfinite(pnl_d) and cash:
            pnl = pnl_d / cash * 100.0
        if not math.isfinite(pnl):
            pnl = 0.0
        if not math.isfinite(pnl_d):
            pnl_d = 0.0
        days = _num(days_col[i])
        closed = _parse_date(closes[i])
        if closed is None and math.isfinite(days) and days >= 0:
            closed = opened + timedelta(days=int(round(days)))
        if closed is None:
            closed = opened
        if closed < opened:
            closed = opened
        days_v = days if math.isfinite(days) and days > 0 else max(1.0, float((closed - opened).days or 1))
        out.append(
            {
                "system": prefix.upper(),
                "sym": sym,
                "opened": opened,
                "closed": closed,
                "entry": _num(entries[i]),
                "pnl": float(pnl),
                "pnl_d": float(pnl_d),
                "pnl_d_10k": SLOT_10K * float(pnl) / 100.0,
                "days": float(days_v),
                "exit": str(exits[i] or "—"),
                "side": str(sides[i] or "LONG").strip().upper(),
                "cash": cash,
                "src": path.name,
            }
        )
    return out, pin, path.name


def _pctile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    i = int(round(q * (len(ys) - 1)))
    return float(ys[i])


def book_stats(trades: list[dict[str, Any]], cash: float, *, pnl_d_key: str = "pnl_d") -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "wo_max": 0.0,
        "exp_pct": 0.0,
        "exp_d": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "wl_count": 0.0,
        "pf": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "p90_days": 0.0,
        "capital_days": 0.0,
        "ppc": float("nan"),
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "losing_streak": 0,
        "exits": {},
    }
    if n == 0:
        return empty
    overlay_rows = []
    for t in trades:
        pdv = float(t.get(pnl_d_key) if t.get(pnl_d_key) is not None else t["pnl_d"])
        overlay_rows.append(
            {
                "pnl": float(t["pnl"]),
                "pnl_d": pdv,
                "days": float(t["days"]),
                "closed": t["closed"],
                "opened": t["opened"],
            }
        )
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg = sum(pnls) / n
    wo = (sum(pnls) - max(pnls)) / (n - 1) if n >= 2 else avg
    days = [float(t["days"]) for t in trades]
    avg_days = sum(days) / n
    pnl_d = sum(float(r["pnl_d"]) for r in overlay_rows)
    ov = overlay_ann_ror_max_dd(overlay_rows, cash=cash, initial_account=INIT_ACCT) or {}
    streak = 0
    best_streak = 0
    for t in sorted(trades, key=lambda x: (x.get("closed") or date.min, x["opened"], x["sym"])):
        if float(t["pnl"]) < 0:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
    cap_days = float(ov.get("capital_days") or sum(days))
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": avg,
        "wo_max": wo,
        "exp_pct": avg,
        "exp_d": pnl_d / n,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "wl_count": (len(wins) / len(losses)) if losses else (float(len(wins)) if wins else 0.0),
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "pnl_d": pnl_d,
        "avg_days": avg_days,
        "med_days": float(np.median(days)),
        "p90_days": _pctile(days, 0.90),
        "capital_days": cap_days,
        "ppc": (pnl_d / cap_days) if cap_days else float("nan"),
        "ann_ror": float(ov.get("ann_ror", float("nan"))),
        "max_dd": float(ov.get("max_dd", float("nan"))),
        "calmar": float(ov.get("calmar", float("nan"))),
        "sharpe": float(ov.get("sharpe", float("nan"))),
        "losing_streak": best_streak,
        "exits": dict(Counter(str(t.get("exit") or "—") for t in trades)),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def _fmt_num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:.{digits}f}"


def _fmt_pct(v: Any, digits: int = 2) -> str:
    s = _fmt_num(v, digits)
    return "—" if s == "—" else f"{s}%"


def exit_mix_text(exits: dict[str, int]) -> str:
    if not exits:
        return "—"
    n = sum(exits.values()) or 1
    parts = []
    for k, c in sorted(exits.items(), key=lambda kv: (-kv[1], kv[0])):
        parts.append(f"{k} {c} ({100.0 * c / n:.0f}%)")
    return "; ".join(parts[:8])


def tag_overlaps(fills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Return (pair events, per-fill tags). Honest double-count: each Closed row stays."""
    for i, f in enumerate(fills):
        f["id"] = i
        f["n_other"] = 0
        f["same_day_systems"] = set()
        f["adj_systems"] = set()
        f["hold_systems"] = set()
        f["max_conc"] = 1
        f["bucket"] = "solo"

    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in fills:
        by_sym[f["sym"]].append(f)

    pair_map: dict[tuple[int, int], dict[str, Any]] = {}

    def _add_pair(a: dict[str, Any], b: dict[str, Any], *, same_day: bool, adj: bool, hold: bool) -> None:
        if a["id"] == b["id"] or a["system"] == b["system"]:
            return
        i, j = (a["id"], b["id"]) if a["id"] < b["id"] else (b["id"], a["id"])
        key = (i, j)
        existing = pair_map.get(key)
        if existing:
            existing["same_day"] = existing["same_day"] or same_day
            existing["adjacent"] = existing["adjacent"] or adj
            existing["hold"] = existing["hold"] or hold
        else:
            first, second = (a, b) if (a["opened"], a["system"]) <= (b["opened"], b["system"]) else (b, a)
            pair_map[key] = {
                "id_a": i,
                "id_b": j,
                "sym": a["sym"],
                "sys_a": first["system"],
                "sys_b": second["system"],
                "opened_a": first["opened"],
                "opened_b": second["opened"],
                "closed_a": first["closed"],
                "closed_b": second["closed"],
                "pnl_a": float(first["pnl"]),
                "pnl_b": float(second["pnl"]),
                "later_sys": second["system"] if second["opened"] > first["opened"] else (
                    "tie" if second["opened"] == first["opened"] else first["system"]
                ),
                "later_pnl": float(second["pnl"]) if second["opened"] >= first["opened"] else float(first["pnl"]),
                "first_pnl": float(first["pnl"]),
                "same_day": same_day,
                "adjacent": adj,
                "hold": hold,
                "combined_10k": float(first["pnl_d_10k"]) + float(second["pnl_d_10k"]),
                "first_10k": float(first["pnl_d_10k"]),
                "later_10k": float(second["pnl_d_10k"]) if second["opened"] >= first["opened"] else float(first["pnl_d_10k"]),
            }
        if same_day:
            a["same_day_systems"].add(b["system"])
            b["same_day_systems"].add(a["system"])
        if adj:
            a["adj_systems"].add(b["system"])
            b["adj_systems"].add(a["system"])
        if hold:
            a["hold_systems"].add(b["system"])
            b["hold_systems"].add(a["system"])

    pileups: list[dict[str, Any]] = []

    for sym, rows in by_sym.items():
        rows_sorted = sorted(rows, key=lambda x: (x["opened"], x["closed"], x["system"], x["id"]))
        # Hold overlap via sweep of currently open fills.
        active: list[dict[str, Any]] = []
        for f in rows_sorted:
            active = [a for a in active if a["closed"] >= f["opened"]]
            for a in active:
                _add_pair(a, f, same_day=(a["opened"] == f["opened"]), adj=False, hold=True)
            active.append(f)

        # Same-day / adjacent session (may already be hold-tagged).
        by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for f in rows:
            by_date[f["opened"]].append(f)
        dates = sorted(by_date)
        date_set = set(dates)
        for d0 in dates:
            nxt = next_session(d0)
            for a in by_date[d0]:
                for b in by_date[d0]:
                    if a["id"] < b["id"]:
                        _add_pair(a, b, same_day=True, adj=False, hold=False)
                if nxt in date_set:
                    for b in by_date[nxt]:
                        _add_pair(a, b, same_day=False, adj=True, hold=False)

        # Max concurrent systems on this symbol (unique systems open that day).
        events: list[tuple[date, int, str, int]] = []
        for f in rows:
            events.append((f["opened"], 0, f["system"], f["id"]))
            events.append((f["closed"] + timedelta(days=1), 1, f["system"], f["id"]))
        events.sort(key=lambda x: (x[0], x[1]))
        open_ids: dict[int, str] = {}
        fill_max: dict[int, int] = {f["id"]: 1 for f in rows}
        peak_win: Optional[tuple[date, int, tuple[str, ...]]] = None
        cur_date = None
        for d0, kind, sys, fid in events:
            if kind == 1:
                open_ids.pop(fid, None)
            else:
                open_ids[fid] = sys
            conc = len(set(open_ids.values()))
            for oid in open_ids:
                if conc > fill_max[oid]:
                    fill_max[oid] = conc
            if conc >= 3:
                sys_t = tuple(sorted(set(open_ids.values())))
                if peak_win is None or conc > peak_win[1] or (conc == peak_win[1] and d0 < peak_win[0]):
                    peak_win = (d0, conc, sys_t)
            cur_date = d0
        for f in rows:
            f["max_conc"] = fill_max.get(f["id"], 1)
        if peak_win and peak_win[1] >= 3:
            pileups.append(
                {
                    "sym": sym,
                    "when": peak_win[0].isoformat(),
                    "n_systems": peak_win[1],
                    "systems": "+".join(peak_win[2]),
                }
            )
        _ = cur_date

    tags: dict[int, dict[str, Any]] = {}
    for f in fills:
        others = set(f["same_day_systems"]) | set(f["adj_systems"]) | set(f["hold_systems"])
        f["n_other"] = len(others)
        n_sys = 1 + f["n_other"]
        if n_sys >= 3 or f["max_conc"] >= 3:
            f["bucket"] = "3+"
        elif n_sys == 2:
            f["bucket"] = "2-system"
        else:
            f["bucket"] = "solo"
        tags[f["id"]] = {
            "bucket": f["bucket"],
            "n_other": f["n_other"],
            "max_conc": f["max_conc"],
            "same_day": sorted(f["same_day_systems"]),
            "adj": sorted(f["adj_systems"]),
            "hold": sorted(f["hold_systems"]),
        }
    return list(pair_map.values()), tags, pileups


def connected_keep_first(fills: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Skip-second arm: keep earliest fill in each overlap-connected component."""
    parent = {f["id"]: f["id"] for f in fills}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for p in pairs:
        union(p["id_a"], p["id_b"])

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_id = {f["id"]: f for f in fills}
    for f in fills:
        groups[find(f["id"])].append(f)

    keep: list[dict[str, Any]] = []
    for members in groups.values():
        members.sort(key=lambda x: (x["opened"], x["system"], x["id"]))
        keep.append(members[0])
        # Isolated fills (no pair) are their own component — kept.
        _ = by_id
    return keep


def pair_stats_table(
    pairs: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    which: str,
) -> list[dict[str, Any]]:
    if which == "IS":
        use = [p for p in pairs if p["opened_b"] < IS_CUT]
    elif which == "OOS":
        use = [p for p in pairs if p["opened_b"] >= IS_CUT]
    else:
        use = list(pairs)
    solo_by_sys: dict[str, list[float]] = defaultdict(list)
    for f in fills:
        if which == "IS" and f["opened"] >= IS_CUT:
            continue
        if which == "OOS" and f["opened"] < IS_CUT:
            continue
        if f["bucket"] == "solo":
            solo_by_sys[f["system"]].append(float(f["pnl"]))

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for p in use:
        a, b = sorted((p["sys_a"], p["sys_b"]))
        buckets[(a, b)].append(p)

    rows = []
    for (sa, sb), evs in sorted(buckets.items()):
        n = len(evs)
        pnls_a = [p["pnl_a"] if p["sys_a"] == sa else p["pnl_b"] for p in evs]
        pnls_b = [p["pnl_b"] if p["sys_b"] == sb else p["pnl_a"] for p in evs]
        later = [p["later_pnl"] for p in evs]
        firsts = [p["first_pnl"] for p in evs]
        wr_later = 100.0 * sum(1 for x in later if x > 0) / n
        solo_a = solo_by_sys.get(sa) or []
        solo_b = solo_by_sys.get(sb) or []
        rows.append(
            {
                "pair": f"{sa}∩{sb}",
                "sys_a": sa,
                "sys_b": sb,
                "n": n,
                "avg_a": sum(pnls_a) / n,
                "avg_b": sum(pnls_b) / n,
                "avg_first": sum(firsts) / n,
                "avg_later": sum(later) / n,
                "wr_later": wr_later,
                "solo_a": (sum(solo_a) / len(solo_a)) if solo_a else float("nan"),
                "solo_b": (sum(solo_b) / len(solo_b)) if solo_b else float("nan"),
                "n_solo_a": len(solo_a),
                "n_solo_b": len(solo_b),
                "n_same_day": sum(1 for p in evs if p["same_day"]),
                "n_adj": sum(1 for p in evs if p["adjacent"]),
                "n_hold": sum(1 for p in evs if p["hold"]),
                "combined_10k": sum(p["combined_10k"] for p in evs),
                "first_only_10k": sum(p["first_10k"] for p in evs),
            }
        )
    return rows


def decide_verdict(
    solo_is: dict,
    two_is: dict,
    later_is: dict,
    first_is: dict,
    take_is: dict,
    skip_is: dict,
    conv_is: dict,
    solo_oos: dict,
    two_oos: dict,
    skip_oos: dict,
) -> tuple[str, str]:
    notes = [
        "research overlay — not gold, not DailyRun",
        "overlap buckets are descriptive; KEEP would require a frozen one-knob arm",
    ]
    if two_is["n"] < 40 or solo_is["n"] < 40:
        notes.append("IS N tiny on a bucket — HOLD")
        return "HOLD", "; ".join(notes)
    d_avg = two_is["avg_pnl"] - solo_is["avg_pnl"]
    d_later = later_is["avg_pnl"] - first_is["avg_pnl"] if first_is["n"] and later_is["n"] else float("nan")
    d_skip = skip_is["avg_pnl"] - take_is["avg_pnl"] if take_is["n"] and skip_is["n"] else float("nan")
    notes.append(f"IS 2-sys vs solo ΔAvg {d_avg:+.2f}pp (N {two_is['n']} vs {solo_is['n']})")
    if math.isfinite(d_later):
        notes.append(f"IS later vs first ΔAvg {d_later:+.2f}pp")
    if math.isfinite(d_skip):
        notes.append(f"IS skip-second vs take-both ΔAvg {d_skip:+.2f}pp")
    oos_soft = False
    if two_oos["n"] >= 20 and solo_oos["n"] >= 20:
        if two_oos["avg_pnl"] < solo_oos["avg_pnl"] - 0.15:
            oos_soft = True
            notes.append(
                f"OOS 2-sys vs solo ΔAvg {two_oos['avg_pnl']-solo_oos['avg_pnl']:+.2f}pp — softened"
            )
    else:
        notes.append("OOS thin — report-only")
    if oos_soft:
        notes.append("OOS softened — do not retune; HOLD")
        return "HOLD", "; ".join(notes)
    # Quality bar: later fill as good as first AND 2-sys quality ≥ solo, no N collapse.
    later_ok = later_is["n"] >= 40 and math.isfinite(d_later) and d_later >= -0.15
    two_better = d_avg >= 0.25 and two_is["wo_max"] >= solo_is["wo_max"] - 0.10
    skip_better = math.isfinite(d_skip) and d_skip >= 0.25 and skip_is["wo_max"] >= take_is["wo_max"] - 0.10
    if two_better and later_ok and not skip_better:
        notes.append("IS 2-sys quality ≥ solo and later ≈ first — LEAN KEEP take-both is not earned; overlap as selection only")
        return "HOLD", "; ".join(notes)
    if skip_better and (not later_ok or d_later < -0.25):
        notes.append("IS later fill worse — skip-second quality lift is descriptive; still HOLD (selection on this table)")
        return "HOLD", "; ".join(notes)
    if conv_is["n"] >= 40 and conv_is["avg_pnl"] >= solo_is["avg_pnl"] + 0.25:
        notes.append(
            "CONVERGE_ENTRY IS Avg% beat solo — IS-selected if we picked after the table; "
            "separate research arm, do not wire"
        )
        return "HOLD", "; ".join(notes)
    notes.append("flat / mixed quality — HOLD")
    return "HOLD", "; ".join(notes)


def metric_rows_multi(cols: list[tuple[str, dict]]) -> list[list[str]]:
    """Canonical book rows; omit Total / Sheet PnL $."""
    specs = [
        ("N (fills)", "n", 0, False),
        ("Wins", "wins", 0, False),
        ("Losses", "losses", 0, False),
        ("Win %", "wr", 2, True),
        ("Avg PnL %", "avg_pnl", 2, True),
        ("AVG_PNL_PCT_WO_MAX", "wo_max", 2, True),
        ("Expectancy %", "exp_pct", 2, True),
        ("Expectancy $ (this overlay)", "exp_d", 2, False),
        ("Avg win %", "avg_win", 2, True),
        ("Avg loss %", "avg_loss", 2, True),
        ("Win/Loss count ratio", "wl_count", 2, False),
        ("Profit factor", "pf", 2, False),
        ("Ann ROR % (overlay slot)", "ann_ror", 2, True),
        ("Max DD %", "max_dd", 2, True),
        ("Calmar", "calmar", 2, False),
        ("Sharpe (exit-date equity)", "sharpe", 2, False),
        ("Avg days held", "avg_days", 1, False),
        ("Median days held", "med_days", 1, False),
        ("P90 days held", "p90_days", 1, False),
        ("Capital days", "capital_days", 0, False),
        ("Profit / capital day", "ppc", 2, False),
        ("Losing streak", "losing_streak", 0, False),
    ]
    out = []
    for label, key, digits, pct in specs:
        row = [label]
        for _name, st in cols:
            v = st.get(key)
            if key == "ppc":
                row.append(format_money(v) if v is not None and math.isfinite(float(v) if v == v else float("nan")) else "—")
            elif key == "exp_d":
                row.append(format_money(v) if v is not None and isinstance(v, (int, float)) and math.isfinite(v) else "—")
            elif key in ("n", "wins", "losses", "capital_days", "losing_streak"):
                row.append(str(int(v or 0)))
            elif pct:
                row.append(_fmt_pct(v, digits))
            else:
                row.append(_fmt_num(v, digits))
        out.append(row)
    # Exit mix as last row
    mix = ["Exit mix"]
    for _name, st in cols:
        mix.append(exit_mix_text(st.get("exits") or {}))
    out.append(mix)
    return out


def html_table(headers: list[tuple[str, str]], body_rows: list[list[str]], *, caption: str = "") -> str:
    thead = "".join(sortable_th(l, t) for l, t in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in body_rows
    )
    cap = f'<p class="meta">{html_mod.escape(caption)} Click column headers to sort.</p>' if caption else '<p class="meta">Click column headers to sort.</p>'
    return (
        f"{cap}<table class=\"sortable\"><thead><tr>{thead}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def write_baseline(
    path: Path,
    *,
    systems: list[str],
    pins: dict[str, str],
    sources: dict[str, str],
    missing: list[str],
    n_fills: int,
    n_pairs: int,
    n_same_day: int,
    n_adj: int,
    n_hold: int,
    n_pile: int,
    verdict: str,
    note: str,
    headline: dict[str, Any],
) -> None:
    expand = ", ".join(SYSTEM_EXPAND.get(s, s) for s in systems)
    pin_lines = "\n".join(
        f"- **{k}:** `{pins.get(k, '')}` · `{sources.get(k, '')}`"
        + (
            " (house pin)"
            if k in {"VZ", "RSI"} and pins.get(k) not in ("", "LatestRun")
            else ""
        )
        + (
            " — deprecated, LatestRun only"
            if k == "IND"
            else (" — research sleeve, not DailyRun gold" if k == "WRL" else "")
        )
        for k in systems
    )
    miss = ", ".join(missing) if missing else "(none)"
    text = f"""# BASELINE — `{STAMP}`

**Status:** Research overlay. **Not gold. Not DailyRun.** Do not change DailyRun freezes. Do not wire as a live filter.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Overlap definitions (both used, labeled)

1. **Same-symbol same-entry-date (or next session)** — two systems issued a buy on the same ticker on the same calendar day, or on the next weekday session (Friday→Monday). Holidays are treated as sessions (slight overcount of “adjacent”). This is **entry agreement**.
2. **Overlapping hold** — system B opens while system A is still in the same symbol: `DATE_OPENED_B` is in `[DATE_OPENED_A, DATE_CLOSED_A]`. This is **crowded exposure**.

**3+ system pile-ups** are reported separately (max concurrent unique systems ≥ 3 on the same symbol, or a fill that touches 2+ other systems).

**Dedup honesty:** if two Closed rows are the same symbol + date on two systems, that is the overlap event. Both fills stay in the book. We do not hide the double-count.

Same-system re-entries (one sleeve buying the same name twice) are **not** cross-system overlap.

## Systems (discovered, not a frozen tuple)

{expand}

Source: `tools/dailyrun_system_status.py` (`DAILYRUN_REGISTRY` / `live_wired_systems` / `live_convergence_systems` + LatestRun extras). Relative Strength Index (RSI) is the house pin (149-name book), **not** `RSIN_PaulScore5_IS`. Industry (IND) is deprecated / not wired. Weekly Range / Swing (WRL) is research-only / not DailyRun gold. Both appear when LatestRun Closed exists.

Missing Closed this run: {miss}

## Pins (house / LatestRun)

{pin_lines}

## Frozen knobs

| Knob | Value |
|------|-------|
| Books | House pin Closed for VZ / RSI; `*_LatestRun_Closed.csv` otherwise |
| Entries / exits | Unchanged from those Closed files |
| IS / OOS | entry &lt; / ≥ 2024-01-01 (OOS **report-only**) |
| Overlay seed | ${INIT_ACCT:,.0f} exit-date equity for Max DD / Sharpe |
| Slot overlay | $10,000 / fill (Ann ROR is %-on-slot). Combined $ = both fills if taken (double slot) |
| Sheet cash (labeled, not HTML Total $) | VZ $45k · RSI $10k · others $47.5k |
| Adjacent session | Next weekday; holiday-blind |
| Same-system pairs | Excluded |

## Arms (research)

| Arm | Meaning |
|-----|---------|
| SOLO | Fills that never overlap another system (either definition) |
| 2-SYSTEM | Fills that touch exactly one other system |
| 3+ | Fills in a 3+ pile-up / 2+ other systems |
| FIRST of pair | Earlier `DATE_OPENED` (tie → system name) |
| LATER of pair | Later fill — the “second ticket” |
| TAKE_BOTH | Every Closed fill (honest double-count, $10k each) |
| SKIP_SECOND | Keep only the earliest fill in each overlap-connected component |
| CONVERGE_ENTRY | **Separate research arm.** Keep a fill only if another system bought the same name the same day or next session (agreement *before* / at entry). IS-selected if we pick after seeing this table. Do **not** wire DailyRun. |

## Headline — wired DailyRun only (do not KEEP from OOS)

Primary judge is **wired** sleeves (BRT, RL, YH, MTS, WPBR, RS, SB, VZ, RSI). Industry (IND) and Weekly Range / Swing (WRL) stay in the all-systems tables so they do not silently drive the verdict.

| Split | Solo N | Solo Avg% | 2-sys N | 2-sys Avg% | Later Avg% | First Avg% |
|-------|--------|-----------|---------|------------|------------|------------|
| FULL | {headline['solo_full']['n']} | {headline['solo_full']['avg_pnl']:.2f} | {headline['two_full']['n']} | {headline['two_full']['avg_pnl']:.2f} | {headline['later_full']['avg_pnl']:.2f} | {headline['first_full']['avg_pnl']:.2f} |
| IS | {headline['solo_is']['n']} | {headline['solo_is']['avg_pnl']:.2f} | {headline['two_is']['n']} | {headline['two_is']['avg_pnl']:.2f} | {headline['later_is']['avg_pnl']:.2f} | {headline['first_is']['avg_pnl']:.2f} |
| OOS (report-only) | {headline['solo_oos']['n']} | {headline['solo_oos']['avg_pnl']:.2f} | {headline['two_oos']['n']} | {headline['two_oos']['avg_pnl']:.2f} | {headline['later_oos']['avg_pnl']:.2f} | {headline['first_oos']['avg_pnl']:.2f} |

Pair events: **{n_pairs}** (same-day {n_same_day} · adjacent {n_adj} · hold {n_hold}; a pair can wear more than one label). 3+ pile-up symbols: **{n_pile}**. Fills loaded: **{n_fills}**.

**Verdict:** {verdict}

{note}

## Selection bias

Judging TAKE_BOTH vs SKIP_SECOND vs CONVERGE_ENTRY on this same Closed history is **in-sample selection**. After any pick: re-report IS/OOS under a freeze; still research-only until a promotion bar. OOS is report-only. If OOS softens or N is tiny → HOLD. Do not retune on OOS.

## Related live page

Overlap *counts* (watch / scan / open names today): `drive/System_Convergence_Latest.html`. This stamp does not replace that report.

## Acronyms

Break and ReTest (BRT); Industry (IND); Rocket Launcher (RL); Year High (YH); Magic Touch (MTS); Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS); StockBee (SB); Volume Zone (VZ); Relative Strength Index (RSI); Weekly Range / Swing (WRL); In-Sample (IS); Out-of-Sample (OOS); Win Rate (WR); Profit Factor (PF); Annualized Rate of Return (Ann ROR); Maximum Drawdown (Max DD).
"""
    path.write_text(text, encoding="utf-8")


def write_html(
    path: Path,
    *,
    systems: list[str],
    pins: dict[str, str],
    sources: dict[str, str],
    missing: list[str],
    pair_rows_full: list[dict[str, Any]],
    pair_rows_is: list[dict[str, Any]],
    pair_rows_oos: list[dict[str, Any]],
    buckets: dict[str, dict[str, dict]],
    arms: dict[str, dict[str, dict]],
    later_books: dict[str, dict],
    first_books: dict[str, dict],
    pileups: list[dict[str, Any]],
    sample_pairs: list[dict[str, Any]],
    verdict: str,
    note: str,
    n_pairs: int,
    n_fills: int,
    buckets_w: dict[str, dict[str, dict]] | None = None,
    arms_w: dict[str, dict[str, dict]] | None = None,
    later_w: dict[str, dict] | None = None,
    first_w: dict[str, dict] | None = None,
) -> None:
    expand_list = "</li><li>".join(
        html_mod.escape(SYSTEM_EXPAND.get(s, s))
        + f" — pin `{html_mod.escape(str(pins.get(s, '')))}` / `{html_mod.escape(str(sources.get(s, '')))}`"
        for s in systems
    )
    miss = html_mod.escape(", ".join(missing)) if missing else "none"

    def book_table(title: str, named: list[tuple[str, dict]]) -> str:
        rows = metric_rows_multi(named)
        heads = [("Metric", "text")] + [(n, "num") for n, _ in named]
        # last row exit mix is text-ish; still sortable as text on first col
        body = [[html_mod.escape(str(c)) for c in r] for r in rows]
        return f"<h3>{html_mod.escape(title)}</h3>" + html_table(heads, body)

    def pair_html(title: str, rows: list[dict[str, Any]]) -> str:
        heads = [
            ("Pair", "text"),
            ("N overlaps", "num"),
            ("Avg% A", "num"),
            ("Avg% B", "num"),
            ("Avg% first", "num"),
            ("Avg% later", "num"),
            ("Later WR %", "num"),
            ("Solo Avg% A", "num"),
            ("Solo N A", "num"),
            ("Solo Avg% B", "num"),
            ("Solo N B", "num"),
            ("Same-day N", "num"),
            ("Adjacent N", "num"),
            ("Hold N", "num"),
            ("Both $10k sum", "num"),
            ("First-only $10k", "num"),
        ]
        body = []
        for r in rows:
            body.append(
                [
                    html_mod.escape(r["pair"]),
                    str(r["n"]),
                    _fmt_pct(r["avg_a"]),
                    _fmt_pct(r["avg_b"]),
                    _fmt_pct(r["avg_first"]),
                    _fmt_pct(r["avg_later"]),
                    _fmt_pct(r["wr_later"]),
                    _fmt_pct(r["solo_a"]),
                    str(r["n_solo_a"]),
                    _fmt_pct(r["solo_b"]),
                    str(r["n_solo_b"]),
                    str(r["n_same_day"]),
                    str(r["n_adj"]),
                    str(r["n_hold"]),
                    format_money(r["combined_10k"]),
                    format_money(r["first_only_10k"]),
                ]
            )
        return f"<h3>{html_mod.escape(title)}</h3>" + html_table(
            heads, body, caption="Per pair of systems. Later = second ticket. "
        )

    sample_heads = [
        ("Symbol", "text"),
        ("First sys", "text"),
        ("Later sys", "text"),
        ("Opened first", "date"),
        ("Opened later", "date"),
        ("First %", "num"),
        ("Later %", "num"),
        ("Same day", "text"),
        ("Adjacent", "text"),
        ("Hold", "text"),
        ("Both $10k", "num"),
    ]
    sample_body = []
    for p in sample_pairs:
        sample_body.append(
            [
                html_mod.escape(p["sym"]),
                html_mod.escape(p["sys_a"]),
                html_mod.escape(p["sys_b"]),
                p["opened_a"].isoformat(),
                p["opened_b"].isoformat(),
                _fmt_pct(p["first_pnl"]),
                _fmt_pct(p["later_pnl"]),
                "Y" if p["same_day"] else "",
                "Y" if p["adjacent"] else "",
                "Y" if p["hold"] else "",
                format_money(p["combined_10k"]),
            ]
        )

    pile_heads = [("Symbol", "text"), ("When (peak)", "date"), ("N systems", "num"), ("Systems", "text")]
    pile_body = [
        [
            html_mod.escape(p["sym"]),
            html_mod.escape(str(p["when"])),
            str(p["n_systems"]),
            html_mod.escape(p["systems"]),
        ]
        for p in sorted(pileups, key=lambda x: (-x["n_systems"], x["sym"]))[:200]
    ]

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Cross-system overlap outcomes · {STAMP}</title>
<style>{SORT_CSS}</style>
</head><body>
<h1>Cross-system overlap — what happens when 2+ sleeves buy the same stock</h1>
<p class="meta">Stamp <code>{STAMP}</code> · research only · not gold · not DailyRun.
Live name-count page: <a href="../../System_Convergence_Latest.html">System_Convergence_Latest.html</a>
(this page is the <em>outcome</em> report, not a replacement).</p>

<div class="callout ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
</div>
<div class="callout plain">
<h2>In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="callout warn">
<p><strong>Verdict: <span class="badge {html_mod.escape(verdict)}">{html_mod.escape(verdict)}</span></strong>
{html_mod.escape(note)}</p>
<p>In-Sample (IS) = entry before 2024-01-01. Out-of-Sample (OOS) = entry on/after that date, report-only.
Quality over count. Do not KEEP from OOS. Do not wire DailyRun.</p>
</div>

<h2>How overlap is defined</h2>
<ol>
<li><strong>Same-symbol same-entry-date (or next session)</strong> — two systems bought the same ticker on the same day, or the next weekday (Friday→Monday). Holiday-blind. This is entry agreement.</li>
<li><strong>Overlapping hold</strong> — system B opens while system A still holds the same symbol (<code>DATE_OPENED_B</code> in <code>[A open, A close]</code>). This is crowded exposure.</li>
</ol>
<p class="meta">3+ pile-ups are separate (three or more unique systems open on the same name at once, or a fill that touches two or more other systems).
Same-symbol same-date Closed rows on two systems are the overlap event — both fills stay (honest double-count). Same-system re-entries are not cross-system overlap.</p>

<h2>Systems this run</h2>
<ul><li>{expand_list}</li></ul>
<p class="meta">Discovered from <code>DAILYRUN_REGISTRY</code> / <code>live_wired_systems</code> / LatestRun extras — not a stale frozen tuple.
RSI house pin only (not RSIN). Missing Closed: {miss}. Fills: {n_fills}. Pair events: {n_pairs}.</p>

<h2>Headline buckets — wired DailyRun only ($10k / fill)</h2>
<p class="meta">Primary judge: Break and ReTest (BRT), Rocket Launcher (RL), Year High (YH), Magic Touch (MTS), Weekly Pivot Break and Retest (WPBR), Relative Strength vs SPY (RS), StockBee (SB), Volume Zone (VZ), Relative Strength Index (RSI). Industry (IND) and Weekly Range / Swing (WRL) are excluded here so a 100k-row research sleeve cannot dominate. Annualized Rate of Return (Ann ROR) is percent-on-the-slot ($10k/fill). Combined dollars if both tickets are taken = two slots. Sheet / Total PnL $ omitted. Maximum Drawdown (Max DD) and Sharpe use exit-date equity on a ${INIT_ACCT:,.0f} seed. Click column headers to sort.</p>
{book_table("WIRED FULL", [
    ("1-system only", (buckets_w or buckets)["FULL"]["solo"]),
    ("2-system", (buckets_w or buckets)["FULL"]["2-system"]),
    ("3+", (buckets_w or buckets)["FULL"]["3+"]),
    ("Later fill", (later_w or later_books)["FULL"]),
    ("First fill", (first_w or first_books)["FULL"]),
]) if buckets_w else ""}
{book_table("WIRED IS (entry < 2024-01-01)", [
    ("1-system only", buckets_w["IS"]["solo"]),
    ("2-system", buckets_w["IS"]["2-system"]),
    ("3+", buckets_w["IS"]["3+"]),
    ("Later fill", later_w["IS"]),
    ("First fill", first_w["IS"]),
]) if buckets_w and later_w and first_w else ""}
{book_table("WIRED OOS (entry ≥ 2024-01-01) — report-only", [
    ("1-system only", buckets_w["OOS"]["solo"]),
    ("2-system", buckets_w["OOS"]["2-system"]),
    ("3+", buckets_w["OOS"]["3+"]),
    ("Later fill", later_w["OOS"]),
    ("First fill", first_w["OOS"]),
]) if buckets_w and later_w and first_w else ""}

<h2>Take both vs skip second vs converge-as-filter — wired</h2>
<p class="meta">TAKE_BOTH = every Closed fill at $10k (double slot when two systems overlap).
SKIP_SECOND = keep only the earliest fill in each overlap cluster.
CONVERGE_ENTRY is a <strong>separate research arm</strong>: only buys where another system agreed the same day or next session. Picking it after this table is in-sample selection. Do not wire DailyRun.</p>
{book_table("WIRED FULL arms ($10k/fill)", [
    ("TAKE_BOTH", (arms_w or arms)["FULL"]["take"]),
    ("SKIP_SECOND", (arms_w or arms)["FULL"]["skip"]),
    ("CONVERGE_ENTRY", (arms_w or arms)["FULL"]["conv"]),
])}
{book_table("WIRED IS arms ($10k/fill)", [
    ("TAKE_BOTH", (arms_w or arms)["IS"]["take"]),
    ("SKIP_SECOND", (arms_w or arms)["IS"]["skip"]),
    ("CONVERGE_ENTRY", (arms_w or arms)["IS"]["conv"]),
])}
{book_table("WIRED OOS arms ($10k/fill) — report-only", [
    ("TAKE_BOTH", (arms_w or arms)["OOS"]["take"]),
    ("SKIP_SECOND", (arms_w or arms)["OOS"]["skip"]),
    ("CONVERGE_ENTRY", (arms_w or arms)["OOS"]["conv"]),
])}

<h2>All discovered systems (includes IND + WRL)</h2>
<p class="meta">Honesty slice: Weekly Range / Swing (WRL) has a very large Closed book and will dominate these rows. Do not judge DailyRun from this block.</p>
{book_table("ALL FULL", [
    ("1-system only", buckets["FULL"]["solo"]),
    ("2-system", buckets["FULL"]["2-system"]),
    ("3+", buckets["FULL"]["3+"]),
    ("Later fill", later_books["FULL"]),
    ("First fill", first_books["FULL"]),
])}
{book_table("ALL IS", [
    ("1-system only", buckets["IS"]["solo"]),
    ("2-system", buckets["IS"]["2-system"]),
    ("3+", buckets["IS"]["3+"]),
    ("Later fill", later_books["IS"]),
    ("First fill", first_books["IS"]),
])}
{book_table("ALL OOS — report-only", [
    ("1-system only", buckets["OOS"]["solo"]),
    ("2-system", buckets["OOS"]["2-system"]),
    ("3+", buckets["OOS"]["3+"]),
    ("Later fill", later_books["OOS"]),
    ("First fill", first_books["OOS"]),
])}
{book_table("ALL FULL arms ($10k/fill)", [
    ("TAKE_BOTH", arms["FULL"]["take"]),
    ("SKIP_SECOND", arms["FULL"]["skip"]),
    ("CONVERGE_ENTRY", arms["FULL"]["conv"]),
])}

<h2>Per pair of systems</h2>
<p class="meta">Avg% of each sleeve’s overlapping fill, Avg% of the later fill, later win rate, vs that sleeve’s solo fills. Combined $10k = both tickets taken.</p>
{pair_html("FULL pairs", pair_rows_full)}
{pair_html("IS pairs", pair_rows_is)}
{pair_html("OOS pairs — report-only", pair_rows_oos)}

<h2>3+ system pile-ups</h2>
<p class="meta">Peak concurrent unique systems on one symbol (first 200 by size). Full list in <code>pileups.csv</code>.</p>
{html_table(pile_heads, pile_body) if pile_body else "<p class='meta'>None.</p>"}

<h2>Overlap events (largest |later %|, sample)</h2>
<p class="meta">Full event list: <code>overlap_events.csv</code>. Sample below is the 150 later fills with the biggest absolute percent (honest double-count).</p>
{html_table(sample_heads, sample_body)}

<p class="caveat">Acronyms: Break and ReTest (BRT); Industry (IND); Rocket Launcher (RL); Year High (YH); Magic Touch (MTS); Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS); StockBee (SB); Volume Zone (VZ); Relative Strength Index (RSI); Weekly Range / Swing (WRL); In-Sample (IS); Out-of-Sample (OOS); Win Rate (WR); Profit Factor (PF); Annualized Rate of Return (Ann ROR); Maximum Drawdown (Max DD).
Sharpe is descriptive (exit-date equity, rf=0, not √252). Not a forecast.</p>
{SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else round(obj, 6)
    if isinstance(obj, (np.floating,)):
        x = float(obj)
        return None if not math.isfinite(x) else round(x, 6)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj


def run() -> dict[str, Any]:
    systems = discover_systems(DRIVE)
    print(f"[overlap] systems={systems}")
    fills: list[dict[str, Any]] = []
    pins: dict[str, str] = {}
    sources: dict[str, str] = {}
    missing: list[str] = []
    for sys_name in systems:
        rows, pin, src = load_closed_fills(sys_name, DRIVE)
        pins[sys_name] = pin
        sources[sys_name] = src
        if not rows:
            missing.append(sys_name)
            print(f"[overlap] {sys_name} MISSING pin={pin} src={src}")
            continue
        fills.extend(rows)
        print(f"[overlap] {sys_name} pin={pin} n={len(rows)} src={src}")

    print(f"[overlap] total fills={len(fills)}")
    pairs, _tags, pileups = tag_overlaps(fills)
    n_same = sum(1 for p in pairs if p["same_day"])
    n_adj = sum(1 for p in pairs if p["adjacent"])
    n_hold = sum(1 for p in pairs if p["hold"])
    print(f"[overlap] pairs={len(pairs)} same_day={n_same} adj={n_adj} hold={n_hold} pileup_syms={len(pileups)}")

    solo = [f for f in fills if f["bucket"] == "solo"]
    two = [f for f in fills if f["bucket"] == "2-system"]
    three = [f for f in fills if f["bucket"] == "3+"]

    later_fills: list[dict[str, Any]] = []
    first_fills: list[dict[str, Any]] = []
    by_id = {f["id"]: f for f in fills}
    seen_later: set[int] = set()
    seen_first: set[int] = set()
    for p in pairs:
        a = by_id[p["id_a"]]
        b = by_id[p["id_b"]]
        first, second = (a, b) if (a["opened"], a["system"]) <= (b["opened"], b["system"]) else (b, a)
        if first["id"] not in seen_first:
            first_fills.append(first)
            seen_first.add(first["id"])
        if second["id"] not in seen_later:
            later_fills.append(second)
            seen_later.add(second["id"])

    skip_fills = connected_keep_first(fills, pairs)
    conv_fills = [
        f
        for f in fills
        if f["same_day_systems"] or f["adj_systems"]
    ]

    def overlay_copy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for t in rows:
            u = dict(t)
            u["pnl_d"] = float(t["pnl_d_10k"])
            out.append(u)
        return out

    def books_for(rows: list[dict[str, Any]]) -> dict[str, dict]:
        is_, oos = split_is_oos(rows)
        return {
            "FULL": book_stats(overlay_copy(rows), SLOT_10K),
            "IS": book_stats(overlay_copy(is_), SLOT_10K),
            "OOS": book_stats(overlay_copy(oos), SLOT_10K),
        }

    solo_b = books_for(solo)
    two_b = books_for(two)
    three_b = books_for(three)
    later_books = books_for(later_fills)
    first_books = books_for(first_fills)
    take_b = books_for(fills)
    skip_b = books_for(skip_fills)
    conv_b = books_for(conv_fills)
    buckets = {
        "FULL": {"solo": solo_b["FULL"], "2-system": two_b["FULL"], "3+": three_b["FULL"]},
        "IS": {"solo": solo_b["IS"], "2-system": two_b["IS"], "3+": three_b["IS"]},
        "OOS": {"solo": solo_b["OOS"], "2-system": two_b["OOS"], "3+": three_b["OOS"]},
    }
    arms = {
        "FULL": {"take": take_b["FULL"], "skip": skip_b["FULL"], "conv": conv_b["FULL"]},
        "IS": {"take": take_b["IS"], "skip": skip_b["IS"], "conv": conv_b["IS"]},
        "OOS": {"take": take_b["OOS"], "skip": skip_b["OOS"], "conv": conv_b["OOS"]},
    }

    wired = set(live_wired_systems())
    fills_wired = [f for f in fills if f["system"] in wired]
    # Re-bucket on the wired-only graph: a fill is solo if it does not overlap another *wired* system.
    pairs_wired = [
        p for p in pairs if p["sys_a"] in wired and p["sys_b"] in wired
    ]
    # n_other still counts IND/WRL; recount wired others
    wired_other: dict[int, set[str]] = defaultdict(set)
    for p in pairs_wired:
        fa, fb = by_id[p["id_a"]], by_id[p["id_b"]]
        wired_other[fa["id"]].add(fb["system"])
        wired_other[fb["id"]].add(fa["system"])
    solo_w = [f for f in fills_wired if not wired_other.get(f["id"])]
    two_w = [f for f in fills_wired if len(wired_other.get(f["id"], ())) == 1]
    three_w = [f for f in fills_wired if len(wired_other.get(f["id"], ())) >= 2]
    skip_w = connected_keep_first(fills_wired, pairs_wired)
    conv_w = [
        f
        for f in fills_wired
        if (set(f["same_day_systems"]) | set(f["adj_systems"])) & wired
    ]
    solo_w_b = books_for(solo_w)
    two_w_b = books_for(two_w)
    three_w_b = books_for(three_w)
    later_w: list[dict[str, Any]] = []
    first_w: list[dict[str, Any]] = []
    seen_lw: set[int] = set()
    seen_fw: set[int] = set()
    for p in pairs_wired:
        a = by_id[p["id_a"]]
        b = by_id[p["id_b"]]
        first, second = (a, b) if (a["opened"], a["system"]) <= (b["opened"], b["system"]) else (b, a)
        if first["id"] not in seen_fw:
            first_w.append(first)
            seen_fw.add(first["id"])
        if second["id"] not in seen_lw:
            later_w.append(second)
            seen_lw.add(second["id"])
    later_w_b = books_for(later_w)
    first_w_b = books_for(first_w)
    take_w_b = books_for(fills_wired)
    skip_w_b = books_for(skip_w)
    conv_w_b = books_for(conv_w)
    buckets_w = {
        "FULL": {"solo": solo_w_b["FULL"], "2-system": two_w_b["FULL"], "3+": three_w_b["FULL"]},
        "IS": {"solo": solo_w_b["IS"], "2-system": two_w_b["IS"], "3+": three_w_b["IS"]},
        "OOS": {"solo": solo_w_b["OOS"], "2-system": two_w_b["OOS"], "3+": three_w_b["OOS"]},
    }
    arms_w = {
        "FULL": {"take": take_w_b["FULL"], "skip": skip_w_b["FULL"], "conv": conv_w_b["FULL"]},
        "IS": {"take": take_w_b["IS"], "skip": skip_w_b["IS"], "conv": conv_w_b["IS"]},
        "OOS": {"take": take_w_b["OOS"], "skip": skip_w_b["OOS"], "conv": conv_w_b["OOS"]},
    }

    pair_full = pair_stats_table(pairs, fills, "FULL")
    pair_is = pair_stats_table(pairs, fills, "IS")
    pair_oos = pair_stats_table(pairs, fills, "OOS")

    verdict, note = decide_verdict(
        buckets_w["IS"]["solo"],
        buckets_w["IS"]["2-system"],
        later_w_b["IS"],
        first_w_b["IS"],
        arms_w["IS"]["take"],
        arms_w["IS"]["skip"],
        arms_w["IS"]["conv"],
        buckets_w["OOS"]["solo"],
        buckets_w["OOS"]["2-system"],
        arms_w["OOS"]["skip"],
    )

    sample = sorted(pairs, key=lambda p: abs(float(p["later_pnl"])), reverse=True)[:150]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headline = {
        "solo_full": buckets_w["FULL"]["solo"],
        "two_full": buckets_w["FULL"]["2-system"],
        "later_full": later_w_b["FULL"],
        "first_full": first_w_b["FULL"],
        "solo_is": buckets_w["IS"]["solo"],
        "two_is": buckets_w["IS"]["2-system"],
        "later_is": later_w_b["IS"],
        "first_is": first_w_b["IS"],
        "solo_oos": buckets_w["OOS"]["solo"],
        "two_oos": buckets_w["OOS"]["2-system"],
        "later_oos": later_w_b["OOS"],
        "first_oos": first_w_b["OOS"],
    }
    headline_all = {
        "solo_full": buckets["FULL"]["solo"],
        "two_full": buckets["FULL"]["2-system"],
        "later_full": later_books["FULL"],
        "first_full": first_books["FULL"],
        "solo_is": buckets["IS"]["solo"],
        "two_is": buckets["IS"]["2-system"],
        "later_is": later_books["IS"],
        "first_is": first_books["IS"],
        "solo_oos": buckets["OOS"]["solo"],
        "two_oos": buckets["OOS"]["2-system"],
        "later_oos": later_books["OOS"],
        "first_oos": first_books["OOS"],
    }
    write_baseline(
        OUT_DIR / "BASELINE.md",
        systems=systems,
        pins=pins,
        sources=sources,
        missing=missing,
        n_fills=len(fills),
        n_pairs=len(pairs),
        n_same_day=n_same,
        n_adj=n_adj,
        n_hold=n_hold,
        n_pile=len(pileups),
        verdict=verdict,
        note=note,
        headline=headline,
    )
    write_html(
        OUT_DIR / "compare.html",
        systems=systems,
        pins=pins,
        sources=sources,
        missing=missing,
        pair_rows_full=pair_full,
        pair_rows_is=pair_is,
        pair_rows_oos=pair_oos,
        buckets=buckets,
        arms=arms,
        later_books=later_books,
        first_books=first_books,
        pileups=pileups,
        sample_pairs=sample,
        verdict=verdict,
        note=note,
        n_pairs=len(pairs),
        n_fills=len(fills),
        buckets_w=buckets_w,
        arms_w=arms_w,
        later_w=later_w_b,
        first_w=first_w_b,
    )

    ev_path = OUT_DIR / "overlap_events.csv"
    with ev_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "sym",
                "sys_a",
                "sys_b",
                "opened_a",
                "opened_b",
                "closed_a",
                "closed_b",
                "pnl_a",
                "pnl_b",
                "first_pnl",
                "later_pnl",
                "later_sys",
                "same_day",
                "adjacent",
                "hold",
                "combined_10k",
                "first_10k",
                "later_10k",
            ],
        )
        w.writeheader()
        for p in pairs:
            w.writerow(
                {
                    "sym": p["sym"],
                    "sys_a": p["sys_a"],
                    "sys_b": p["sys_b"],
                    "opened_a": p["opened_a"].isoformat(),
                    "opened_b": p["opened_b"].isoformat(),
                    "closed_a": p["closed_a"].isoformat() if p["closed_a"] else "",
                    "closed_b": p["closed_b"].isoformat() if p["closed_b"] else "",
                    "pnl_a": f"{p['pnl_a']:.4f}",
                    "pnl_b": f"{p['pnl_b']:.4f}",
                    "first_pnl": f"{p['first_pnl']:.4f}",
                    "later_pnl": f"{p['later_pnl']:.4f}",
                    "later_sys": p["later_sys"],
                    "same_day": int(p["same_day"]),
                    "adjacent": int(p["adjacent"]),
                    "hold": int(p["hold"]),
                    "combined_10k": f"{p['combined_10k']:.2f}",
                    "first_10k": f"{p['first_10k']:.2f}",
                    "later_10k": f"{p['later_10k']:.2f}",
                }
            )

    with (OUT_DIR / "pileups.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sym", "when", "n_systems", "systems"])
        w.writeheader()
        for p in pileups:
            w.writerow(p)

    pair_csv = OUT_DIR / "pair_stats.csv"
    with pair_csv.open("w", encoding="utf-8", newline="") as f:
        if pair_full:
            w = csv.DictWriter(f, fieldnames=list(pair_full[0].keys()))
            w.writeheader()
            for r in pair_full:
                w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in r.items()})

    summary = {
        "stamp": STAMP,
        "systems": systems,
        "pins": pins,
        "sources": sources,
        "missing": missing,
        "n_fills": len(fills),
        "n_pairs": len(pairs),
        "n_same_day": n_same,
        "n_adjacent": n_adj,
        "n_hold": n_hold,
        "n_pileup_symbols": len(pileups),
        "verdict": verdict,
        "note": note,
        "headline": {
            split: {
                "solo_n": headline[f"solo_{split}"]["n"],
                "solo_avg": headline[f"solo_{split}"]["avg_pnl"],
                "two_n": headline[f"two_{split}"]["n"],
                "two_avg": headline[f"two_{split}"]["avg_pnl"],
                "later_avg": headline[f"later_{split}"]["avg_pnl"],
                "first_avg": headline[f"first_{split}"]["avg_pnl"],
            }
            for split in ("full", "is", "oos")
        },
        "arms": {
            split: {
                "take_n": arms[split.upper()]["take"]["n"],
                "take_avg": arms[split.upper()]["take"]["avg_pnl"],
                "skip_n": arms[split.upper()]["skip"]["n"],
                "skip_avg": arms[split.upper()]["skip"]["avg_pnl"],
                "conv_n": arms[split.upper()]["conv"]["n"],
                "conv_avg": arms[split.upper()]["conv"]["avg_pnl"],
            }
            for split in ("full", "is", "oos")
        },
        "headline_all_incl_ind_wrl": {
            split: {
                "solo_n": headline_all[f"solo_{split}"]["n"],
                "solo_avg": headline_all[f"solo_{split}"]["avg_pnl"],
                "two_n": headline_all[f"two_{split}"]["n"],
                "two_avg": headline_all[f"two_{split}"]["avg_pnl"],
            }
            for split in ("full", "is", "oos")
        },
        "arms_wired": {
            split: {
                "take_n": arms_w[split.upper()]["take"]["n"],
                "take_avg": arms_w[split.upper()]["take"]["avg_pnl"],
                "skip_n": arms_w[split.upper()]["skip"]["n"],
                "skip_avg": arms_w[split.upper()]["skip"]["avg_pnl"],
                "conv_n": arms_w[split.upper()]["conv"]["n"],
                "conv_avg": arms_w[split.upper()]["conv"]["avg_pnl"],
            }
            for split in ("full", "is", "oos")
        },
        "best_pairs_full": sorted(pair_full, key=lambda r: r["avg_later"], reverse=True)[:8],
        "worst_pairs_full": sorted(pair_full, key=lambda r: r["avg_later"])[:8],
        "html": str(OUT_DIR / "compare.html"),
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(_json_safe(summary), indent=2) + "\n", encoding="utf-8"
    )
    print(f"[overlap] wrote {OUT_DIR / 'compare.html'}")
    print(f"[overlap] verdict={verdict}")
    print(
        f"[overlap] FULL solo N={buckets['FULL']['solo']['n']} Avg%={buckets['FULL']['solo']['avg_pnl']:.2f} "
        f"2sys N={buckets['FULL']['2-system']['n']} Avg%={buckets['FULL']['2-system']['avg_pnl']:.2f}"
    )
    return summary


if __name__ == "__main__":
    run()
