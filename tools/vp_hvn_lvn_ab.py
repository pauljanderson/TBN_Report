#!/usr/bin/env python3
"""Daily volume-profile HVN/LVN overlay ABs on Closed+OHLC (not full-engine).

Frozen VP (same bins as compute_volume_poc): 60d lookback, 0.5% typical-price bins.
HVN = bin vol >= 50% of POC bin. LVN = interior valley < 20% of POC and lower than
both neighbors. Daily-bar approximation — not Thinkorswim tick LVN/HVN.

Research-only. Not DailyRun. One hypothesis per arm. OOS report-only.
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
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from vec_zones import (  # noqa: E402
    VP_BIN_PCT,
    VP_HVN_FRAC,
    VP_LOOKBACK,
    VP_LVN_FRAC,
    compute_volume_poc,
    compute_volume_profile,
)
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "vp_hvn_lvn_ab_20260819"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
POC_NEAR = 0.01  # entry within 1% of 60d POC
HEIGHT_DUMP = DRIVE / "paul_experiments" / "vz_zone_height_ab_20260819" / "trades_with_zone_height.csv"
THR_MED = 8.68
THR_P75 = 13.28

BRT_BAND = 0.0154
WPBR_BAND = 0.015
VEC_BAND = 0.012


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


def _parse_zone_id_date(zone_id: str) -> Optional[date]:
    s = str(zone_id or "").strip()
    if "_" not in s:
        return _parse_d(s)
    return _parse_d(s.split("_", 1)[1].strip()[:10])


class OhlcCache:
    def __init__(self) -> None:
        self._bars: dict[str, dict[str, Any]] = {}
        self._prof: dict[tuple[str, date], Any] = {}

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
        dates = [d.date() for d in df[dcol]]
        def col(*names: str) -> np.ndarray:
            for n in names:
                if n in df.columns:
                    return pd.to_numeric(df[n], errors="coerce").to_numpy(dtype=np.float64)
            return np.full(len(df), np.nan)
        pack = {
            "dates": dates,
            "high": col("High", "HIGH"),
            "low": col("Low", "LOW"),
            "close": col("Close", "CLOSE"),
            "volume": col("Volume", "VOLUME"),
            "date_to_i": {d: i for i, d in enumerate(dates)},
        }
        self._bars[sym] = pack
        return pack

    def hl_on(self, sym: str, d: date, tol: int = 3) -> Optional[tuple[float, float]]:
        b = self.bars(sym)
        if not b:
            return None
        idx = b["date_to_i"].get(d)
        if idx is None:
            best = None
            for k, i in b["date_to_i"].items():
                delta = abs((k - d).days)
                if delta <= tol and (best is None or delta < best[0] or (delta == best[0] and k < best[1])):
                    best = (delta, k, i)
            if best is None:
                return None
            idx = best[2]
        hi, lo = float(b["high"][idx]), float(b["low"][idx])
        if hi > 0 and lo > 0 and math.isfinite(hi) and math.isfinite(lo):
            return hi, lo
        return None

    def profile_before(self, sym: str, opened: date):
        """VP ending on last daily bar strictly before DATE_OPENED (no same-day volume)."""
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
        )
        self._prof[key] = prof
        return prof


def load_closed(path: Path, univ: set[str], *, vz_hl: bool, cache: OhlcCache, band_pct: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE_OPENED", "DATE OPENED"))
            if opened is None:
                continue
            sym = _row_get(raw, "SYMBOL").upper()
            if not sym or (univ and sym not in univ):
                continue
            entry = _f(_row_get(raw, "ENTRY_PRICE", "ENTRY PRICE"))
            if not (math.isfinite(entry) and entry > 0):
                continue
            zlo = _f(_row_get(raw, "ZONE_LOW", "ZONE_LO", "ZONE LO", "ZONE LOW"))
            zhi = _f(_row_get(raw, "ZONE_HIGH", "ZONE_HI", "ZONE HI", "ZONE HIGH"))
            zc = _f(_row_get(raw, "ZONE_CENTER", "ZONE CENTER", "TOUCH_PRICE"))
            zid = _row_get(raw, "ZONE_ID", "ZONE ID")
            if vz_hl:
                kind = _row_get(raw, "ZONE_KIND", "ZONE KIND").upper()
                if not kind and zid:
                    kind = zid.split("_", 1)[0].upper()
                if kind and kind != "HL":
                    continue
                mv = _parse_zone_id_date(zid)
                if mv is not None:
                    hit = cache.hl_on(sym, mv)
                    if hit is not None:
                        recon_hi, recon_lo = hit
                        if not (math.isfinite(zlo) and zlo > 0):
                            zlo = recon_lo
                        if not (math.isfinite(zhi) and zhi > 0):
                            zhi = recon_hi
            if not (math.isfinite(zlo) and math.isfinite(zhi) and zhi > 0 and zlo > 0):
                if math.isfinite(zc) and zc > 0 and band_pct > 0:
                    zlo, zhi = zc * (1.0 - band_pct), zc * (1.0 + band_pct)
                elif math.isfinite(entry) and band_pct > 0:
                    zlo, zhi = entry * (1.0 - band_pct), entry * (1.0 + band_pct)
                    zc = entry
            if math.isfinite(zlo) and math.isfinite(zhi) and zhi < zlo:
                zlo, zhi = zhi, zlo
            if not (math.isfinite(zc) and zc > 0) and math.isfinite(zlo) and math.isfinite(zhi):
                zc = 0.5 * (zlo + zhi)
            pnl = _f(_row_get(raw, "PNL_PCT", "PNL %"), 0.0)
            r = _f(_row_get(raw, "R_MULT", "R_MULTIPLE", "R MULTIPLE"), 0.0)
            days = _f(_row_get(raw, "DAYS_HELD", "DAYS HELD"), 0.0)
            pnl_d = _f(_row_get(raw, "PNL_DOLLARS"), 0.0)
            xt = _row_get(raw, "EXIT_TYPE", "EXIT TYPE")
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "entry": entry,
                    "pnl": pnl,
                    "r": r,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exit": xt,
                    "closed": _parse_d(_row_get(raw, "DATE_CLOSED", "DATE CLOSED")),
                    "zid": zid,
                    "zlo": zlo,
                    "zhi": zhi,
                    "zc": zc,
                    "has_zone": math.isfinite(zlo) and math.isfinite(zhi) and zlo > 0 and zhi > 0,
                }
            )
    return rows


def book_stats(trades: list[dict[str, Any]], sheet: float, initial_account: float = DEFAULT_INITIAL_ACCOUNT) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_r": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "avg_days": 0.0,
        "syms": 0,
        "avg_wo_max": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
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
    rs = [t["r"] for t in trades if math.isfinite(t["r"])]
    cap = overlay_ann_ror_max_dd(trades, cash=sheet, initial_account=initial_account)
    return {
        "n": n,
        "wins": len(wins),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": (sum(rs) / len(rs)) if rs else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * sheet for p in pnls),
        "avg_days": sum(t["days"] for t in trades) / n,
        "syms": len({t["sym"] for t in trades}),
        "avg_wo_max": wo,
        "ann_ror": cap["ann_ror"],
        "max_dd": cap["max_dd"],
        "cap_days": cap["capital_days"],
        "equity_note": cap["note"],
        "exits": dict(exits),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def pack(name: str, trades: list[dict[str, Any]], sheet: float, initial_account: float = DEFAULT_INITIAL_ACCOUNT) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    return {
        "name": name,
        "full": book_stats(trades, sheet, initial_account),
        "is": book_stats(is_t, sheet, initial_account),
        "oos": book_stats(oos_t, sheet, initial_account),
        "n_loaded": len(trades),
    }


def quality_better(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if cand["n"] <= 0 or ctrl["n"] <= 0:
        return False
    return cand["avg_pnl"] > ctrl["avg_pnl"] and (
        cand["avg_r"] > ctrl["avg_r"] or cand["pf"] > ctrl["pf"] or cand["wr"] > ctrl["wr"]
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


def annotate(trades: list[dict[str, Any]], cache: OhlcCache, *, zone_mode: bool) -> tuple[list[dict[str, Any]], dict[str, int]]:
    scored: list[dict[str, Any]] = []
    miss = {"no_ohlc": 0, "no_profile": 0, "no_zone": 0}
    for t in trades:
        if zone_mode and not t["has_zone"]:
            miss["no_zone"] += 1
            continue
        prof = cache.profile_before(t["sym"], t["opened"])
        if prof is None:
            if cache.bars(t["sym"]) is None:
                miss["no_ohlc"] += 1
            else:
                miss["no_profile"] += 1
            continue
        t2 = dict(t)
        t2["poc"] = float(prof.poc)
        t2["n_hvn"] = int(len(prof.hvn_idx))
        t2["n_lvn"] = int(len(prof.lvn_idx))
        t2["poc_near"] = bool(prof.poc_proximity(t["entry"], POC_NEAR))
        t2["entry_lvn"] = bool(prof.price_in_lvn(t["entry"]))
        if t["has_zone"]:
            t2["hvn_ol"] = bool(prof.overlaps_hvn_or_poc(t["zlo"], t["zhi"]))
            t2["lvn_cross"] = bool(prof.crosses_lvn(t["zlo"], t["zhi"]))
        else:
            t2["hvn_ol"] = False
            t2["lvn_cross"] = False
        scored.append(t2)
    return scored, miss


def metrics_table(packed: list[dict[str, Any]], split_key: str, split_label: str) -> str:
    ctrl = packed[0][split_key]
    specs = [
        ("Closed N", "n", 0, False),
        ("Wins", "wins", 0, False),
        ("Win %", "wr", 1, False),
        ("Avg PnL %", "avg_pnl", 2, False),
        ("AvgR", "avg_r", 2, False),
        ("Profit factor", "pf", 2, False),
        ("Sheet PnL $", "sheet", 2, True),
        ("Ann ROR %", "ann_ror", 1, False),
        ("Max DD %", "max_dd", 2, False),
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


def run_job(job: dict[str, Any], cache: OhlcCache) -> dict[str, Any]:
    path = resolve_closed(job["closed_cands"])
    if path is None:
        return {
            "sys": job["sys"],
            "skipped": True,
            "reason": "Closed file missing: " + "; ".join(p.as_posix() for p in job["closed_cands"]),
        }
    univ = load_universe(job["univ"]) if job.get("univ") else set()
    trades = load_closed(path, univ, vz_hl=bool(job.get("vz_hl")), cache=cache, band_pct=float(job.get("band", 0.0)))
    scored, miss = annotate(trades, cache, zone_mode=job["kind"] == "zone")
    sheet = float(job.get("sheet", 45_000.0))
    init = float(job.get("initial", DEFAULT_INITIAL_ACCOUNT))
    ctrl = pack("control (no VP filter)", scored, sheet, init)
    arms: list[dict[str, Any]] = [ctrl]
    verdicts: list[dict[str, Any]] = []
    if job["kind"] == "zone":
        a1 = pack("HVN overlap (keep if zone intersects HVN/POC)", [t for t in scored if t["hvn_ol"]], sheet, init)
        a2 = pack("LVN veto (drop if zone crosses LVN)", [t for t in scored if not t["lvn_cross"]], sheet, init)
        arms.extend([a1, a2])
        for a in (a1, a2):
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
    else:
        a1 = pack("POC proximity (entry within 1% of 60d POC)", [t for t in scored if t["poc_near"]], sheet, init)
        a2 = pack("LVN skip (drop if entry in LVN bin)", [t for t in scored if not t["entry_lvn"]], sheet, init)
        arms.extend([a1, a2])
        for a in (a1, a2):
            v, why = arm_verdict(ctrl, a)
            cap_is = (
                f" IS Ann ROR {a['is']['ann_ror']:.1f} vs {ctrl['is']['ann_ror']:.1f}; "
                f"Max DD {a['is']['max_dd']:.2f} vs {ctrl['is']['max_dd']:.2f}."
                if math.isfinite(a["is"].get("ann_ror", float("nan")))
                and math.isfinite(ctrl["is"].get("ann_ror", float("nan")))
                else ""
            )
            verdicts.append({"arm": a["name"], "verdict": v, "why": why + cap_is})
    hvn_rate = 100.0 * sum(1 for t in scored if t["hvn_ol"]) / len(scored) if scored and job["kind"] == "zone" else None
    lvn_rate = (
        100.0 * sum(1 for t in scored if t["lvn_cross"]) / len(scored)
        if scored and job["kind"] == "zone"
        else (100.0 * sum(1 for t in scored if t["entry_lvn"]) / len(scored) if scored else None)
    )
    poc_rate = 100.0 * sum(1 for t in scored if t["poc_near"]) / len(scored) if scored else None
    nested: Optional[list[dict[str, Any]]] = None
    if str(job.get("sys", "")).startswith("VZ") and scored:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        flags_path = OUT_DIR / "vz_hvn_flags.csv"
        with flags_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["SYMBOL", "DATE_OPENED", "ZONE_ID", "HVN_OL", "LVN_CROSS"])
            w.writeheader()
            for t in scored:
                w.writerow(
                    {
                        "SYMBOL": t["sym"],
                        "DATE_OPENED": t["opened"].isoformat(),
                        "ZONE_ID": str(t.get("zid") or ""),
                        "HVN_OL": int(bool(t.get("hvn_ol"))),
                        "LVN_CROSS": int(bool(t.get("lvn_cross"))),
                    }
                )
        height: dict[tuple[str, str, str], float] = {}
        if HEIGHT_DUMP.is_file():
            with HEIGHT_DUMP.open(newline="", encoding="utf-8-sig") as f:
                for raw in csv.DictReader(f):
                    opened = _parse_d(raw.get("DATE_OPENED") or "")
                    if opened is None:
                        continue
                    pct = _f(raw.get("PCT_MID"))
                    if not math.isfinite(pct) or pct <= 0:
                        continue
                    sym = str(raw.get("SYMBOL") or "").strip().upper()
                    zid = str(raw.get("ZONE_ID") or "").strip()
                    height[(sym, opened.isoformat(), zid)] = pct
        dna: list[dict[str, Any]] = []
        for t in scored:
            key = (t["sym"], t["opened"].isoformat(), str(t.get("zid") or ""))
            if key not in height:
                continue
            t2 = dict(t)
            t2["pct_mid"] = height[key]
            dna.append(t2)
        if dna:
            nested = [
                pack("Nested control (VP+height DNA)", dna, sheet, init),
                pack(f"Taller ≥ IS median ({THR_MED:.2f}%)", [t for t in dna if t["pct_mid"] >= THR_MED], sheet, init),
                pack(f"Taller ≥ IS p75 ({THR_P75:.2f}%)", [t for t in dna if t["pct_mid"] >= THR_P75], sheet, init),
                pack("HVN-only (zone ∩ HVN/POC)", [t for t in dna if t.get("hvn_ol")], sheet, init),
                pack(
                    "HVN + taller-median (exploratory AND)",
                    [t for t in dna if t.get("hvn_ol") and t["pct_mid"] >= THR_MED],
                    sheet,
                    init,
                ),
            ]
    return {
        "sys": job["sys"],
        "skipped": False,
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "kind": job["kind"],
        "univ_n": len(univ),
        "n_closed": len(trades),
        "n_scored": len(scored),
        "miss": miss,
        "note": job.get("note", ""),
        "packed": arms,
        "verdicts": verdicts,
        "hvn_rate": hvn_rate,
        "lvn_rate": lvn_rate,
        "poc_rate": poc_rate,
        "mean_hvn": (sum(t["n_hvn"] for t in scored) / len(scored)) if scored else 0.0,
        "mean_lvn": (sum(t["n_lvn"] for t in scored) / len(scored)) if scored else 0.0,
        "nested": nested,
    }


def jobs() -> list[dict[str, Any]]:
    rs_gold = [
        DRIVE / "paul_experiments" / "rs_baseline_260807141317" / "engine_closed" / "RS_Closed_260807141317.csv",
        DRIVE / "RS_Closed_260807141317.csv",
        DRIVE / "RS_LatestRun_Closed.csv",
    ]
    return [
        {
            "sys": "BRT Latest",
            "kind": "zone",
            "band": BRT_BAND,
            "sheet": 50_000.0,
            "univ": DRIVE / "universes" / "BRT_universe.csv",
            "closed_cands": [DRIVE / "BRT_LatestRun_Closed.csv"],
            "note": "Zone band = ZONE_LOW/HIGH if present else ZONE_CENTER ± 1.54%.",
        },
        {
            "sys": "WPBR Mag9",
            "kind": "zone",
            "band": WPBR_BAND,
            "sheet": 50_000.0,
            "univ": DRIVE / "universes" / "WPBR_universe.csv",
            "closed_cands": [DRIVE / "WPBR_LatestRun_Closed.csv"],
            "note": "Sliced to WPBR Mag9 universe. Band ± 1.50%.",
        },
        {
            "sys": "VZ DualPaul78 260817212836",
            "kind": "zone",
            "band": 0.0,
            "vz_hl": True,
            "sheet": 45_000.0,
            "univ": DRIVE / "universes" / "VZ_universe.csv",
            "closed_cands": [DRIVE / "VZ_Closed_260817212836.csv"],
            "note": "HL-only. ZONE_HI reconstructed from OHLC High on ZONE_ID date when missing.",
        },
        {
            "sys": "VEC Latest",
            "kind": "zone",
            "band": VEC_BAND,
            "sheet": 45_000.0,
            "univ": DRIVE / "universes" / "VEC_universe.csv",
            "closed_cands": [DRIVE / "VEC_LatestRun_Closed.csv"],
            "note": "Natural VP fit (POC already in VEC). Band ± 1.20% from run_vec.bat. Skip if Closed missing.",
        },
        {
            "sys": "RS gold 260807141317",
            "kind": "price",
            "sheet": 16_216.0,
            "univ": DRIVE / "universes" / "RS_universe.csv",
            "closed_cands": rs_gold,
            "note": "Weaker VP fit. POC proximity + LVN skip on entry price.",
        },
        {
            "sys": "SB Latest",
            "kind": "price",
            "sheet": 45_000.0,
            "univ": DRIVE / "universes" / "SB_universe.csv",
            "closed_cands": [DRIVE / "SB_LatestRun_Closed.csv"],
            "note": "Weaker VP fit.",
        },
        {
            "sys": "RL Latest",
            "kind": "price",
            "sheet": 47_500.0,
            "univ": DRIVE / "universes" / "RL_universe.csv",
            "closed_cands": [DRIVE / "RL_LatestRun_Closed.csv"],
            "note": "Weaker VP fit.",
        },
        {
            "sys": "YH Latest",
            "kind": "price",
            "sheet": 50_000.0,
            "univ": DRIVE / "universes" / "YH_universe.csv",
            "closed_cands": [DRIVE / "YH_LatestRun_Closed.csv"],
            "note": "YH Mag9-style; entry-price arms only (not zone HVN).",
        },
        {
            "sys": "MTS Latest",
            "kind": "price",
            "sheet": 45_000.0,
            "univ": DRIVE / "universes" / "MTS_universe.csv",
            "closed_cands": [DRIVE / "MTS_LatestRun_Closed.csv"],
            "note": "Weaker VP fit.",
        },
    ]


def pick_next(results: list[dict[str, Any]]) -> str:
    ranked: list[tuple[int, str, str]] = []
    rank = {"KEEP": 3, "LEAN KEEP": 2, "HOLD": 1, "DISMISS": 0}
    for r in results:
        if r.get("skipped"):
            continue
        for v in r["verdicts"]:
            ranked.append((rank.get(v["verdict"], 0), r["sys"], v["arm"]))
    keep = [x for x in ranked if x[0] == 3]
    if keep:
        return f"{keep[0][1]} / {keep[0][2]}"
    lean = [x for x in ranked if x[0] == 2]
    if lean:
        return f"{lean[0][1]} / {lean[0][2]} (LEAN KEEP only — do not treat as gold)"
    return "none — no KEEP; do not grid VP knobs"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = OhlcCache()
    results = [run_job(j, cache) for j in jobs()]
    next_try = pick_next(results)

    # Sanity: POC from profile == compute_volume_poc on one scored symbol if possible
    poc_ok = "n/a"
    for r in results:
        if r.get("skipped") or r.get("n_scored", 0) <= 0:
            continue
        # probe AAPL if loaded
        b = cache.bars("AAPL") or cache.bars("MSFT")
        if b and len(b["dates"]) > 80:
            ei = len(b["dates"]) - 2
            p1 = compute_volume_poc(b["high"], b["low"], b["close"], b["volume"], ei, VP_LOOKBACK, VP_BIN_PCT)
            p2 = compute_volume_profile(b["high"], b["low"], b["close"], b["volume"], ei)
            poc_ok = "PASS" if p2 is not None and abs(float(p1) - float(p2.poc)) < 1e-9 else "FAIL"
        break

    verdict_rows = ""
    md_verdicts: list[str] = []
    equity_gaps: list[str] = []
    for r in results:
        if r.get("skipped"):
            verdict_rows += (
                f"<tr><td>{html_mod.escape(r['sys'])}</td><td>—</td><td>SKIP</td>"
                f"<td>{html_mod.escape(r['reason'])}</td></tr>"
            )
            md_verdicts.append(f"- **{r['sys']}**: SKIP — {r['reason']}")
            continue
        note = (r.get("packed") or [{}])[0].get("full", {}).get("equity_note") or ""
        if note:
            equity_gaps.append(f"{r['sys']}: {note}")
        for v in r["verdicts"]:
            verdict_rows += (
                f"<tr><td>{html_mod.escape(r['sys'])}</td>"
                f"<td>{html_mod.escape(v['arm'])}</td>"
                f"<td><strong>{html_mod.escape(v['verdict'])}</strong></td>"
                f"<td>{html_mod.escape(v['why'])}</td></tr>"
            )
            md_verdicts.append(f"- **{r['sys']} / {v['arm']}**: {v['verdict']} — {v['why']}")

    body_html = ""
    for r in results:
        if r.get("skipped"):
            body_html += (
                f"<h2>{html_mod.escape(r['sys'])}</h2>"
                f'<p class="card">Skipped: {html_mod.escape(r["reason"])}</p>'
            )
            continue
        miss = r["miss"]
        rates = []
        if r["hvn_rate"] is not None:
            rates.append(f"zone intersects HVN {r['hvn_rate']:.1f}%")
        if r["lvn_rate"] is not None:
            rates.append(f"LVN hit {r['lvn_rate']:.1f}%")
        if r["poc_rate"] is not None:
            rates.append(f"POC±1% {r['poc_rate']:.1f}%")
        body_html += f"<h2>{html_mod.escape(r['sys'])}</h2>"
        body_html += (
            f'<p class="sub">Closed <code>{html_mod.escape(r["path"])}</code> · kind={r["kind"]} · '
            f"closed N={r['n_closed']} scored N={r['n_scored']} (univ {r['univ_n']}) · "
            f"miss ohlc={miss['no_ohlc']} profile={miss['no_profile']} zone={miss['no_zone']} · "
            f"mean HVN bins {r['mean_hvn']:.1f} / LVN bins {r['mean_lvn']:.1f}"
            + (f" · {' · '.join(rates)}" if rates else "")
            + f". {html_mod.escape(r['note'])}</p>"
        )
        body_html += metrics_table(r["packed"], "full", "Full book")
        body_html += metrics_table(r["packed"], "is", "IS (entry &lt; 2024-01-01)")
        body_html += metrics_table(r["packed"], "oos", "OOS (entry ≥ 2024-01-01, report-only)")
        nested = r.get("nested")
        if nested:
            body_html += (
                "<h3>Exploratory nested: taller zones × HVN (DualPaul78) — not a KEEP trigger</h3>"
                "<p class='small'>Two knobs if ANDed. Control vs HVN-only remains the one-knob KEEP. "
                "Taller cuts frozen from IS height (median 8.68%, p75 13.28%). "
                "Ann ROR uses sheet notional; Max DD is $500k seed on DATE_CLOSED dollars. "
                "Click column headers to sort.</p>"
            )
            body_html += metrics_table(nested, "is", "Nested IS")
            body_html += metrics_table(nested, "oos", "Nested OOS (report-only)")
            body_html += metrics_table(nested, "full", "Nested full book")
            body_html += (
                "<p class='card'><strong>Adopt?</strong> Taller zones: HOLD (OOS AvgR soften; N/2 or N/4; "
                "IS-selected percentiles; overlay not portfolio). HVN overlap: KEEP research-only if "
                "quality + Ann ROR + Max DD hold vs control (LVN veto DISMISS). Combine: follow-on "
                "one-knob on a freeze — not this week's DailyRun.</p>"
            )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Daily VP HVN/LVN overlay AB — 20260819</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1600px; }}
h1 {{ font-size: 1.35rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.12rem; margin: 32px 0 8px; }}
h3 {{ font-size: 1.0rem; margin: 18px 0 6px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
.warn {{ color: #7a3b00; }}
</style>
</head>
<body>
<h1>Daily volume-profile HVN / LVN overlay ABs</h1>
<p class="sub">Cheap Closed + local OHLC overlay — not a full-engine rerun of eight systems.
<strong>Not gold. Not DailyRun.</strong> Click column headers to sort.</p>
<div class="card">
<p><strong>Frozen VP (daily bars, not Thinkorswim tick volume-at-price).</strong>
Lookback <code>{VP_LOOKBACK}</code> sessions ending on the last bar <em>strictly before</em>
<code>DATE_OPENED</code>. Typical price <code>(H+L+C)/3</code>, bin width = median(tp)×<code>{VP_BIN_PCT}</code>
(0.5%). POC = max bin (same as <code>compute_volume_poc</code>; sanity {html_mod.escape(poc_ok)}).
HVN = bins with volume ≥ {int(VP_HVN_FRAC*100)}% of the POC bin (includes POC; not top-3).
LVN = interior local valley: bin vol &lt; {int(VP_LVN_FRAC*100)}% of POC <em>and</em> lower than both neighbors
(not “gap between two HVNs”).</p>
<p>IS = entry &lt; 2024-01-01 (judge KEEP/HOLD/DISMISS). OOS is report-only — if OOS softens, HOLD, do not retune.
One hypothesis per arm. MVCP parked (skipped). Control = same scored DNA (valid profile required).</p>
</div>
<h2>Verdicts — what might work vs not</h2>
<p class="small">Click column headers to sort. KEEP/LEAN KEEP on IS quality without collapsing N; OOS soften → HOLD.</p>
<table class="sortable">
<thead><tr>
{sortable_th("System", "text")}{sortable_th("Arm", "text")}{sortable_th("Verdict", "text")}{sortable_th("Why", "text")}
</tr></thead>
<tbody>{verdict_rows}</tbody>
</table>
<p class="card"><strong>What to try next (at most one KEEP candidate):</strong> {html_mod.escape(next_try)}.
Do not open a 20-knob VP grid (lookback × bin × K × depth).</p>
{body_html}
<p class="small">Stamp <code>{STAMP}</code>. Selection honesty: arms were pre-registered (HVN overlap, LVN veto,
POC±1%, LVN skip) — not chosen after seeing this table. Overlay screening ≠ portfolio capital BT.</p>
{SORT_JS}
</body>
</html>
"""
    html_path = OUT_DIR / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    md = f"""# Daily VP HVN/LVN overlay AB — {STAMP}

**Research only. Not gold. Not DailyRun.** Overlay on existing Closed books + local daily OHLC.
This is a **daily-bar volume-at-price approximation**, not Thinkorswim tick LVN/HVN/value area.

## Frozen VP definition (do not retune in this stamp)

| Knob | Freeze |
|------|--------|
| Lookback | **60** sessions (`compute_volume_poc` / `vec_vp_lookback`) |
| Price in bin | Typical price **(H+L+C)/3** |
| Bin width | **0.5%** of median typical price in the window |
| POC | Max-volume bin center (same histogram as `compute_volume_poc`) |
| HVN | Bins with volume **≥ 50% of POC bin** (includes POC). Not top-3. |
| LVN | Interior **local valley**: vol **< 20% of POC** AND lower than **both neighbors**. Not HVN-gap. |
| As-of | Last daily bar **strictly before** `DATE_OPENED` (no same-day / future volume) |
| POC proximity arm | Entry within **1%** of POC |

Not frozen here (and not searched): lookback, bin %, HVN/LVN fractions, top-K, value area.

POC vs profile sanity: **{poc_ok}**.

## Systems / Closed

Zone arms (HVN overlap keep; LVN veto drop): BRT Latest, WPBR Mag9, VZ DualPaul78 `260817212836`, VEC Latest (if Closed exists).
Price arms (POC±1% keep; LVN skip if entry in LVN bin): RS gold `260807141317`, SB Latest, RL Latest, YH Latest, MTS Latest.
**MVCP skipped** (parked). Missing Closed → skip with a note.

## Selection honesty

Arms were **pre-registered** in the job prompt (not picked after the quality table).
Judging KEEP vs DISMISS after seeing one overlay table is still **in-sample selection** of a filter.
OOS is **report-only**. If OOS softens vs IS, **HOLD — do not retune** HVN/LVN fractions on OOS.
Quality over count (WR, Avg PnL%, PF). Overlay ≠ engine/portfolio BT.
Keep/lean requires IS Avg PnL% lift **≥ 0.25 pp** vs control and IS N **≥ 40%** of control; KEEP also wants **≥ 0.50 pp** and **≥ 70%** N retained. OOS soften → HOLD.
Ann ROR / Max DD are required on the compare table even for Closed overlays: Ann ROR = rocket_tbn book formula with stamp sheet/`brt_cash`; Max DD = peak-to-trough on `PNL_DOLLARS` by `DATE_CLOSED` seeded at **$500,000**. If both IS Ann ROR falls and Max DD worsens, KEEP is downgraded to HOLD.

## DualPaul78 taller × HVN (exploratory, not KEEP)

Taller is a **separate** one-knob (`vz_zone_height_taller_ab_20260819`) currently **HOLD** (OOS AvgR soften). Combining HVN ∩ taller is two changes. Nested table on compare.html is labeled exploratory. Do not DailyRun either overlay this week.

IS: `entry_date < 2024-01-01`. OOS: `>= 2024-01-01`.

## Verdicts

{chr(10).join(md_verdicts)}

## Equity notes

{chr(10).join("- " + x for x in equity_gaps) if equity_gaps else "All scored books had dated PnL dollars (or sheet fallback from PnL%). Cells show — when dollars/dates cannot form Ann ROR or Max DD."}

## What to try next

**{next_try}**

At most one KEEP-class candidate. Do not run a VP parameter grid in the next stamp.
"""
    (OUT_DIR / "BASELINE.md").write_text(md, encoding="utf-8")

    slim = []
    for r in results:
        if r.get("skipped"):
            slim.append({"sys": r["sys"], "skipped": True, "reason": r["reason"]})
            continue
        slim.append(
            {
                "sys": r["sys"],
                "path": r["path"],
                "n_closed": r["n_closed"],
                "n_scored": r["n_scored"],
                "verdicts": r["verdicts"],
                "full": {p["name"]: p["full"] for p in r["packed"]},
                "is": {p["name"]: p["is"] for p in r["packed"]},
                "oos": {p["name"]: p["oos"] for p in r["packed"]},
                "nested": (
                    {p["name"]: {"is": p["is"], "oos": p["oos"], "full": p["full"]} for p in r["nested"]}
                    if r.get("nested")
                    else None
                ),
            }
        )
    (OUT_DIR / "overlay_stats.json").write_text(json.dumps({"next": next_try, "results": slim}, indent=2, default=str), encoding="utf-8")
    print(html_path)
    print("next:", next_try.encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
