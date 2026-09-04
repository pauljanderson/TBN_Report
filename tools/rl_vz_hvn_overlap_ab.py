#!/usr/bin/env python3
"""RL × VZ HL zone + HVN overlap overlay AB (research-only).

Tests whether RL Closed trades perform better when entry overlaps active VZ HL
zones and/or when the matched HL band intersects daily VP HVN/POC bins
(same VP params as ``vz_require_hvn_overlap`` / ``vp_hvn_lvn_ab``).

Control = full RL book (house freeze). Overlay only — no engine rerun.
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from vec_zones import (  # noqa: E402
    VP_BIN_PCT,
    VP_HVN_FRAC,
    VP_LOOKBACK,
    compute_volume_profile,
)
from vol_zone_break_retest import Zone, build_zones  # noqa: E402
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "rl_vz_hvn_overlap_ab_20260826"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
VZ_LOOKBACK = 126
NEAR_PCT = 0.015  # entry within 1.5% pad of HL band counts as "at/near"
RL_CASH = 47_500.0
CLOSED_CANDS = [
    DRIVE / "RL_LatestRun_Closed.csv",
    DRIVE
    / "paul_experiments"
    / "rl_expansion_ab_dip105_16_17_20260824"
    / "runs"
    / "control_dip105"
    / "RL_Closed_260824191932.csv",
]
UNIV_PATH = DRIVE / "universes" / "RL_universe.csv"


def _f(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_d(s: Any) -> Optional[date]:
    t = str(s or "").strip()
    if not t:
        return None
    compact = t.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((t[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (t[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _row_get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
        for k, v in row.items():
            if str(k).strip().upper().replace(" ", "_") == n.upper().replace(" ", "_") and v not in (None, ""):
                return str(v).strip()
    return ""


def load_universe(path: Path) -> set[str]:
    out: set[str] = set()
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.add(s.split(",")[0].strip().upper())
    return out


def resolve_closed(cands: list[Path]) -> Optional[Path]:
    for p in cands:
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


class OhlcCache:
    def __init__(self) -> None:
        self._bars: dict[str, dict[str, Any]] = {}
        self._prof: dict[tuple[str, date], Any] = {}
        self._zones: dict[str, list[Zone]] = {}

    def _path(self, sym: str) -> Optional[Path]:
        for name in (f"{sym}.csv", f"{sym}.CSV"):
            p = DATA_DIR / name
            if p.is_file():
                return p
        return None

    def bars(self, sym: str) -> Optional[dict[str, Any]]:
        if sym in self._bars:
            return self._bars[sym] or None
        path = self._path(sym)
        if path is None:
            self._bars[sym] = {}
            return None
        df = pd.read_csv(path)
        dcol = "Date" if "Date" in df.columns else "DATE"
        df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
        df = df.dropna(subset=[dcol]).sort_values(dcol)
        if "Volume" not in df.columns and "VOLUME" in df.columns:
            df["Volume"] = df["VOLUME"]
        if "Open" not in df.columns and "OPEN" in df.columns:
            df["Open"] = df["OPEN"]
        dates = [d.date() for d in df[dcol]]

        def col(*names: str) -> np.ndarray:
            for n in names:
                if n in df.columns:
                    return pd.to_numeric(df[n], errors="coerce").to_numpy(dtype=np.float64)
            return np.full(len(df), np.nan)

        pack = {
            "dates": dates,
            "open": col("Open", "OPEN"),
            "high": col("High", "HIGH"),
            "low": col("Low", "LOW"),
            "close": col("Close", "CLOSE"),
            "volume": col("Volume", "VOLUME"),
            "date_to_i": {d: i for i, d in enumerate(dates)},
        }
        self._bars[sym] = pack
        return pack

    def zones(self, sym: str) -> Optional[list[Zone]]:
        if sym in self._zones:
            return self._zones[sym]
        b = self.bars(sym)
        if not b or len(b["dates"]) <= VZ_LOOKBACK:
            self._zones[sym] = []
            return []
        df = pd.DataFrame(
            {
                "Date": pd.to_datetime(b["dates"]),
                "Open": b["open"],
                "High": b["high"],
                "Low": b["low"],
                "Close": b["close"],
                "Volume": b["volume"],
            }
        )
        try:
            zlist = build_zones(df, VZ_LOOKBACK)
        except ValueError:
            zlist = []
        self._zones[sym] = zlist
        return zlist

    def profile_before(self, sym: str, opened: date):
        """VP ending on last daily bar strictly before DATE_OPENED (overlay timing)."""
        key = (sym, opened)
        if key in self._prof:
            return self._prof[key]
        b = self.bars(sym)
        if not b:
            self._prof[key] = None
            return None
        end_i = None
        for i, d in enumerate(b["dates"]):
            if d < opened:
                end_i = i
            else:
                break
        if end_i is None or end_i + 1 < 10:
            self._prof[key] = None
            return None
        prof = compute_volume_profile(
            b["high"],
            b["low"],
            b["close"],
            b["volume"],
            end_i,
            lookback=VP_LOOKBACK,
            bin_pct=VP_BIN_PCT,
            hvn_frac=VP_HVN_FRAC,
        )
        self._prof[key] = prof
        return prof


def _bar_intersects(lo: float, hi: float, bar_lo: float, bar_hi: float) -> bool:
    return bar_lo <= hi and bar_hi >= lo


def _price_near_zone(entry: float, lo: float, hi: float, near_pct: float = NEAR_PCT) -> bool:
    zlo, zhi = min(lo, hi), max(lo, hi)
    pad_lo = zlo * (1.0 - near_pct)
    pad_hi = zhi * (1.0 + near_pct)
    return pad_lo <= entry <= pad_hi


def active_hl_zones(zlist: list[Zone], entry_idx: int) -> list[Zone]:
    out: list[Zone] = []
    for z in zlist:
        if z.kind != "HL":
            continue
        if z.created_on_idx <= entry_idx <= z.last_winner_idx:
            out.append(z)
    return out


def load_rl_closed(path: Path, univ: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
            if opened is None:
                continue
            sym = _row_get(raw, "SYMBOL").upper()
            if not sym or (univ and sym not in univ):
                continue
            entry = _f(_row_get(raw, "ENTRY PRICE", "ENTRY PRICE"))
            if not (math.isfinite(entry) and entry > 0):
                continue
            pnl = _f(_row_get(raw, "PNL %", "PNL_PCT"), 0.0)
            days = _f(_row_get(raw, "DAYS HELD", "DAYS_HELD"), 0.0)
            pnl_d = _f(_row_get(raw, "PNL_DOLLARS"), 0.0)
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = RL_CASH * pnl / 100.0
            xt = _row_get(raw, "EXIT TYPE", "EXIT_TYPE")
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": _parse_d(_row_get(raw, "DATE CLOSED", "DATE_CLOSED")),
                    "entry": entry,
                    "pnl": pnl,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exit": xt or "UNKNOWN",
                }
            )
    return rows


def annotate(trades: list[dict[str, Any]], cache: OhlcCache) -> tuple[list[dict[str, Any]], dict[str, int]]:
    scored: list[dict[str, Any]] = []
    miss = {"no_ohlc": 0, "no_profile": 0, "no_entry_bar": 0, "no_zones": 0, "short_history": 0}
    for t in trades:
        b = cache.bars(t["sym"])
        if not b:
            miss["no_ohlc"] += 1
            continue
        entry_idx = b["date_to_i"].get(t["opened"])
        if entry_idx is None:
            miss["no_entry_bar"] += 1
            continue
        zlist = cache.zones(t["sym"])
        if not zlist:
            miss["no_zones"] += 1
            continue
        active = active_hl_zones(zlist, entry_idx)
        if not active:
            miss["short_history"] += 1
            continue
        bar_lo = float(b["low"][entry_idx])
        bar_hi = float(b["high"][entry_idx])
        overlapping: list[Zone] = []
        for z in active:
            if _price_near_zone(t["entry"], z.lo, z.hi) or _bar_intersects(z.lo, z.hi, bar_lo, bar_hi):
                overlapping.append(z)
        best = min(active, key=lambda z: abs(0.5 * (z.lo + z.hi) - t["entry"]))
        match = overlapping[0] if overlapping else best
        if overlapping:
            match = min(overlapping, key=lambda z: abs(0.5 * (z.lo + z.hi) - t["entry"]))
        prof = cache.profile_before(t["sym"], t["opened"])
        if prof is None:
            miss["no_profile"] += 1
            continue
        zlo, zhi = float(match.lo), float(match.hi)
        t2 = dict(t)
        t2["vz_hl"] = bool(overlapping)
        t2["hvn_ol"] = bool(prof.overlaps_hvn_or_poc(zlo, zhi))
        t2["zone_id"] = match.zone_id
        t2["zlo"] = zlo
        t2["zhi"] = zhi
        t2["n_active_hl"] = len(active)
        t2["n_overlap_hl"] = len(overlapping)
        t2["poc"] = float(prof.poc)
        scored.append(t2)
    return scored, miss


def book_stats(trades: list[dict[str, Any]], sheet: float, initial_account: float = DEFAULT_INITIAL_ACCOUNT) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "avg_days": 0.0,
        "syms": 0,
        "avg_wo_max": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "cap_days": 0.0,
        "equity_note": "no trades",
        "exits": {},
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else pnls[0]
    exits = Counter(str(t.get("exit") or "") for t in trades)
    cap = overlay_ann_ror_max_dd(trades, cash=sheet, initial_account=initial_account)
    ann = cap["ann_ror"]
    mdd = cap["max_dd"]
    calmar = (ann / abs(mdd)) if math.isfinite(ann) and math.isfinite(mdd) and abs(mdd) > 1e-9 else float("nan")
    return {
        "n": n,
        "wins": len(wins),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * sheet for p in pnls),
        "avg_days": sum(t["days"] for t in trades) / n,
        "syms": len({t["sym"] for t in trades}),
        "avg_wo_max": wo,
        "ann_ror": ann,
        "max_dd": mdd,
        "calmar": calmar,
        "cap_days": cap["capital_days"],
        "equity_note": cap["note"],
        "exits": dict(exits),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def pack(name: str, trades: list[dict[str, Any]], sheet: float) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    return {
        "name": name,
        "full": book_stats(trades, sheet),
        "is": book_stats(is_t, sheet),
        "oos": book_stats(oos_t, sheet),
        "n_loaded": len(trades),
    }


def quality_better(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if cand["n"] <= 0 or ctrl["n"] <= 0:
        return False
    return cand["avg_pnl"] > ctrl["avg_pnl"] and (
        cand["pf"] > ctrl["pf"] or cand["wr"] > ctrl["wr"]
    )


def oos_softer(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if cand["n"] < 8 or ctrl["n"] < 8:
        return cand["avg_pnl"] < ctrl["avg_pnl"]
    return cand["avg_pnl"] < ctrl["avg_pnl"] or cand["pf"] < ctrl["pf"]


def arm_verdict(ctrl: dict[str, Any], cand: dict[str, Any]) -> tuple[str, str]:
    lift = cand["is"]["avg_pnl"] - ctrl["is"]["avg_pnl"]
    is_up = quality_better(cand["is"], ctrl["is"]) and lift >= 0.25
    n_frac = (cand["is"]["n"] / ctrl["is"]["n"]) if ctrl["is"]["n"] else 0.0
    n_thin = cand["is"]["n"] < 15 or n_frac < 0.40
    oos_down = oos_softer(cand["oos"], ctrl["oos"])
    if not is_up:
        return "DISMISS", (
            f"IS quality not better / flat (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}; "
            f"N {cand['is']['n']} vs {ctrl['is']['n']})."
        )
    if n_thin:
        return "HOLD", (
            f"IS quality up but N collapsed ({cand['is']['n']} vs {ctrl['is']['n']}, "
            f"{100 * n_frac:.0f}% retained). Do not KEEP."
        )
    if oos_down:
        return "HOLD", (
            f"IS quality up (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}) "
            f"but OOS softened (AvgPnL {cand['oos']['avg_pnl']:.2f} vs {ctrl['oos']['avg_pnl']:.2f}) — do not retune."
        )
    if lift >= 0.50 and n_frac >= 0.70:
        return "KEEP", (
            f"IS quality up (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}, "
            f"N retained {100 * n_frac:.0f}%); OOS did not soften. Research-only — not DailyRun."
        )
    return "LEAN KEEP", (
        f"IS quality up (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}); "
        f"OOS did not soften. Modest lift and/or N drop — lean only. Research-only."
    )


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
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
      var av = parseSortValue(a.cells[col] ? a.cells[col].innerText : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].innerText : "", type);
      var cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return dir === "asc" ? cmp : -cmp;
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""

SORT_CSS = """
<style>
body { font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 1200px; }
h1,h2,h3 { margin-top: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; }
th, td { border: 1px solid #ccc; padding: 0.35rem 0.5rem; text-align: right; }
th { background: #f4f4f4; }
td:first-child, th:first-child { text-align: left; }
.num { font-variant-numeric: tabular-nums; }
.small, .sub { color: #555; font-size: 0.92rem; }
.card { background: #fafafa; border: 1px solid #ddd; padding: 0.75rem 1rem; border-radius: 6px; }
th.sortable-th { cursor: pointer; user-select: none; position: relative; padding-right: 1.2rem; }
th.sortable-th:hover { background: #eaeaea; }
.sort-ind::after { content: "⇅"; position: absolute; right: 0.35rem; opacity: 0.35; font-size: 0.75rem; }
th.sort-asc .sort-ind::after { content: "▲"; opacity: 0.9; }
th.sort-desc .sort-ind::after { content: "▼"; opacity: 0.9; }
.verdict-KEEP { color: #0a7; font-weight: 600; }
.verdict-DISMISS { color: #a33; }
.verdict-HOLD { color: #a60; }
</style>
"""


def fmt_n(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    if nd == 0:
        return f"{int(round(x))}"
    return f"{x:.{nd}f}"


def delta_cell(cand: float, ctrl: float, nd: int, *, money: bool = False) -> str:
    d = cand - ctrl
    if money:
        return format_money_delta(d)
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.{nd}f}"


def metrics_table(packed: list[dict[str, Any]], split_key: str, split_label: str) -> str:
    ctrl = packed[0][split_key]
    specs = [
        ("Closed N", "n", 0, False),
        ("Wins", "wins", 0, False),
        ("Win %", "wr", 1, False),
        ("Avg PnL %", "avg_pnl", 2, False),
        ("Profit factor", "pf", 2, False),
        ("Sheet PnL $", "sheet", 2, True),
        ("Ann ROR %", "ann_ror", 1, False),
        ("Max DD %", "max_dd", 2, False),
        ("Calmar", "calmar", 2, False),
        ("Avg PnL% wo max", "avg_wo_max", 2, False),
        ("Avg days held", "avg_days", 1, False),
        ("Capital days", "cap_days", 0, False),
        ("Names", "syms", 0, False),
    ]
    head = sortable_th("Metric", "text") + "".join(sortable_th(p["name"], "num") for p in packed)
    for i in range(1, len(packed)):
        head += sortable_th(f"Δ vs control (arm{i})", "num")
    body = ""
    for label, key, nd, money in specs:
        body += f"<tr><td>{html_mod.escape(label)}</td>"
        for p in packed:
            v = p[split_key][key]
            cell = format_money(v) if money else fmt_n(v, nd)
            body += f'<td class="num">{cell}</td>'
        for p in packed[1:]:
            body += f'<td class="num">{delta_cell(p[split_key][key], ctrl[key], nd, money=money)}</td>'
        body += "</tr>"
    return (
        f"<h3>{html_mod.escape(split_label)}</h3>"
        f'<p class="small">Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    )


def write_flags_csv(scored: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "SYMBOL",
                "DATE_OPENED",
                "ENTRY_PRICE",
                "ZONE_ID",
                "ZONE_LO",
                "ZONE_HI",
                "VZ_HL",
                "HVN_OL",
                "N_ACTIVE_HL",
                "N_OVERLAP_HL",
                "PNL_PCT",
            ],
        )
        w.writeheader()
        for t in scored:
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "DATE_OPENED": t["opened"].isoformat(),
                    "ENTRY_PRICE": f"{t['entry']:.4f}",
                    "ZONE_ID": t.get("zone_id", ""),
                    "ZONE_LO": f"{t.get('zlo', float('nan')):.4f}",
                    "ZONE_HI": f"{t.get('zhi', float('nan')):.4f}",
                    "VZ_HL": int(bool(t.get("vz_hl"))),
                    "HVN_OL": int(bool(t.get("hvn_ol"))),
                    "N_ACTIVE_HL": t.get("n_active_hl", 0),
                    "N_OVERLAP_HL": t.get("n_overlap_hl", 0),
                    "PNL_PCT": f"{t['pnl']:.4f}",
                }
            )


def write_metrics_csv(packed: list[dict[str, Any]], path: Path) -> None:
    rows: list[dict[str, str]] = []
    for p in packed:
        for split in ("full", "is", "oos"):
            s = p[split]
            rows.append(
                {
                    "arm": p["name"],
                    "split": split,
                    "n": str(s["n"]),
                    "win_pct": fmt_n(s["wr"], 2),
                    "avg_pnl_pct": fmt_n(s["avg_pnl"], 2),
                    "pf": fmt_n(s["pf"], 2),
                    "sheet_pnl": format_money(s["sheet"]),
                    "ann_ror": fmt_n(s["ann_ror"], 2),
                    "max_dd": fmt_n(s["max_dd"], 2),
                    "calmar": fmt_n(s["calmar"], 2),
                    "avg_wo_max": fmt_n(s["avg_wo_max"], 2),
                    "avg_days": fmt_n(s["avg_days"], 1),
                    "cap_days": fmt_n(s["cap_days"], 0),
                    "syms": str(s["syms"]),
                }
            )
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["arm"])
        w.writeheader()
        w.writerows(rows)


def write_baseline(path: Path, closed_rel: str, n_closed: int, n_scored: int, miss: dict[str, int]) -> None:
    text = f"""# BASELINE — `{STAMP}`

**Research only. Not gold. Not DailyRun. Do not wire `run_rl.bat`.**

Generated: {datetime.now():%Y-%m-%d %H:%M}. Overlay AB: RL Closed × computed VZ HL zones + VP HVN overlap.

## Selection bias / prior context

- No prior RL-specific VZ zone overlap AB.
- Prior `vp_hvn_lvn_ab_20260819`: RL VP-at-entry arms **DISMISS**; VZ HVN overlap tested on VZ/BRT/WPBR only.
- Prior `vz_hvn_engine_ab_20260819`: `vz_require_hvn_overlap` on VZ engine **HOLD** (not adopted).
- This stamp compares **three overlay filters** on one RL book — label in-sample selection if picking among arms.

## Control freeze (RL engine — unchanged)

| Knob | Value | Note |
|------|-------|------|
| `rl_dip_pct` | 1.041 | house |
| `rl_expansion` | 1.163 | house |
| `rl_too_high` | 0.0 (off) | house |
| `rl_stop_pct` | 0.934 | house |
| `rl_target_pct` | 1.2 | house |
| `rl_cash` | $47,500 | overlay sheet |
| `brt_zones` | false | RL has no VZ zone DNA on Closed |
| Universe | drive/universes/RL_universe.csv (59) | |
| Closed input | `{closed_rel}` | house LatestRun preferred |

## Overlay method (not engine rerun)

| Item | Value |
|------|-------|
| VZ zones | `build_zones(OHLC, lookback=126)` HL only |
| Active at entry | `created_on_idx ≤ entry_idx ≤ last_winner_idx` |
| VZ HL arm | Entry price within HL band ± {NEAR_PCT*100:.1f}% **or** entry-day bar intersects band |
| HVN arm | Matched HL zone lo/hi vs 60d VP (bins 0.5%, HVN ≥50% POC); VP ends **day before** `DATE_OPENED` (overlay timing; differs from engine signal-bar gate) |
| Combined arm | VZ HL overlap **and** HVN overlap on matched zone |

## Arms

| Arm | Filter | Role |
|-----|--------|------|
| control | All scored RL trades (OHLC + zones + VP) | control |
| vz_hl_overlap | `vz_hl` true | candidate |
| hvn_overlap | `hvn_ol` true on matched HL zone | candidate |
| vz_hl_and_hvn | both true | exploratory AND (two filters) |

## IS / OOS

- **IS:** `entry_date` < 2024-01-01
- **OOS:** `entry_date` ≥ 2024-01-01 — report-only; never pick winners from OOS.
- KEEP/HOLD/DISMISS on **IS quality** vs control. OOS soften → HOLD, do not retune.

## Data coverage

- Closed loaded: {n_closed}
- Scored (OHLC + zones + VP): {n_scored}
- Miss: no_ohlc={miss.get('no_ohlc',0)}, no_entry_bar={miss.get('no_entry_bar',0)}, no_zones={miss.get('no_zones',0)}, short_history={miss.get('short_history',0)}, no_profile={miss.get('no_profile',0)}

## Artifacts

- `compare.html` — sortable IS/OOS/full
- `metrics_all.csv` — flat metrics
- `rl_vz_hvn_flags.csv` — per-trade flags
- `SUMMARY.md` — verdicts
"""
    path.write_text(text, encoding="utf-8")


def write_summary(path: Path, verdicts: list[dict[str, Any]], rates: dict[str, float], miss: dict[str, int]) -> None:
    lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        "**Research only. Not gold. Not DailyRun.**",
        "",
        "## Flag rates (scored book)",
        "",
        f"- VZ HL overlap at/near entry: **{rates['vz_hl']:.1f}%**",
        f"- HVN overlap on matched HL zone: **{rates['hvn']:.1f}%**",
        f"- Both: **{rates['both']:.1f}%**",
        "",
        f"Miss counts: {json.dumps(miss)}",
        "",
        "## Verdicts (IS quality vs control; OOS report-only)",
        "",
    ]
    for v in verdicts:
        lines.append(f"- **{v['arm']}**: **{v['verdict']}** — {v['why']}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Overlay only — does not re-run RL or VZ engines.",
            "- HVN timing = day-before-entry VP (matches `vp_hvn_lvn_ab`), not VZ signal-bar gate.",
            "- Combined arm is exploratory (two filters); do not treat as one-knob KEEP.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    closed_path = resolve_closed(CLOSED_CANDS)
    if closed_path is None:
        print("ERROR: no RL Closed CSV found", file=sys.stderr)
        return 1
    univ = load_universe(UNIV_PATH)
    cache = OhlcCache()
    trades = load_rl_closed(closed_path, univ)
    scored, miss = annotate(trades, cache)

    ctrl = pack("control (all scored RL)", scored, RL_CASH)
    a_vz = pack("VZ HL overlap at/near entry", [t for t in scored if t["vz_hl"]], RL_CASH)
    a_hvn = pack("HVN overlap (matched HL zone x HVN/POC)", [t for t in scored if t["hvn_ol"]], RL_CASH)
    a_both = pack("VZ HL + HVN overlap (exploratory AND)", [t for t in scored if t["vz_hl"] and t["hvn_ol"]], RL_CASH)
    packed = [ctrl, a_vz, a_hvn, a_both]

    verdicts: list[dict[str, Any]] = []
    for a in (a_vz, a_hvn, a_both):
        v, why = arm_verdict(ctrl, a)
        if v in ("KEEP", "LEAN KEEP") and math.isfinite(a["is"]["ann_ror"]) and math.isfinite(a["is"]["max_dd"]):
            dd_worse = a["is"]["max_dd"] > ctrl["is"]["max_dd"] + 0.25
            ror_down = a["is"]["ann_ror"] < ctrl["is"]["ann_ror"] - 0.25
            if dd_worse and ror_down:
                v = "HOLD"
                why = why + " Capital mixed/worse (IS Ann ROR down and Max DD worse) — HOLD, not KEEP."
        cap_is = (
            f" IS Ann ROR {a['is']['ann_ror']:.1f} vs {ctrl['is']['ann_ror']:.1f}; "
            f"Max DD {a['is']['max_dd']:.2f} vs {ctrl['is']['max_dd']:.2f}."
            if math.isfinite(a["is"]["ann_ror"]) and math.isfinite(ctrl["is"]["ann_ror"])
            else ""
        )
        verdicts.append({"arm": a["name"], "verdict": v, "why": why + cap_is})

    n_scored = len(scored)
    rates = {
        "vz_hl": 100.0 * sum(1 for t in scored if t["vz_hl"]) / n_scored if n_scored else 0.0,
        "hvn": 100.0 * sum(1 for t in scored if t["hvn_ol"]) / n_scored if n_scored else 0.0,
        "both": 100.0 * sum(1 for t in scored if t["vz_hl"] and t["hvn_ol"]) / n_scored if n_scored else 0.0,
    }

    closed_rel = str(closed_path.relative_to(ROOT)).replace("\\", "/")
    write_flags_csv(scored, OUT_DIR / "rl_vz_hvn_flags.csv")
    write_metrics_csv(packed, OUT_DIR / "metrics_all.csv")
    write_baseline(OUT_DIR / "BASELINE.md", closed_rel, len(trades), n_scored, miss)
    write_summary(OUT_DIR / "SUMMARY.md", verdicts, rates, miss)

    verdict_rows = ""
    for v in verdicts:
        cls = f"verdict-{v['verdict'].replace(' ', '-')}"
        verdict_rows += (
            f"<tr><td>{html_mod.escape(v['arm'])}</td>"
            f'<td class="{cls}"><strong>{html_mod.escape(v["verdict"])}</strong></td>'
            f"<td>{html_mod.escape(v['why'])}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP} — RL VZ HL + HVN overlap AB</title>
{SORT_CSS}
</head><body>
<h1>{STAMP}</h1>
<p class="card"><strong>Research only.</strong> RL overlay on <code>{html_mod.escape(closed_rel)}</code>.
Universe {len(univ)} names · closed N={len(trades)} · scored N={n_scored}.
VZ HL flag {rates['vz_hl']:.1f}% · HVN {rates['hvn']:.1f}% · both {rates['both']:.1f}%.
Miss: {html_mod.escape(json.dumps(miss))}.</p>

<h2>Verdicts</h2>
<table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Verdict", "text")}{sortable_th("Why", "text")}
</tr></thead><tbody>{verdict_rows}</tbody></table>

{metrics_table(packed, "full", "Full book")}
{metrics_table(packed, "is", "IS (entry &lt; 2024-01-01)")}
{metrics_table(packed, "oos", "OOS (entry ≥ 2024-01-01, report-only)")}

<p class="small">Overlay: VZ HL from <code>build_zones(126)</code>; HVN VP ends day before entry.
Combined arm = two filters — not one-knob. OOS report-only.</p>
{SORT_JS}
</body></html>
"""
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")

    print(f"Wrote {OUT_DIR / 'compare.html'}")
    print(f"Scored {n_scored}/{len(trades)} trades")
    for v in verdicts:
        print(f"  {v['arm']}: {v['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
