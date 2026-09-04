#!/usr/bin/env python3
"""Cheap EXIT overlay: after +X (1R or +10%), raise stop to breakeven on existing Closed.

Replay walks local OHLC only for trades already in a Closed stamp. Does not
re-run entries, portfolio, or DailyRun. Research-only — not a DailyRun wire.

Arms (one knob each):
  RL  — after High >= entry * 1.10, stop = entry  (restore Trail-1 BE; prod trail off)
  RS  — after High >= entry + 1R, stop = entry     (gold Closed % stop)
  VZ  — after High >= entry + 1R, stop = entry     (DualPaul78 Closed)

Usage:
  python tools/be_stop_replay_ab.py
"""
from __future__ import annotations

import csv
import html as html_mod
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    filter_html_compare_columns,
    format_money,
    format_money_delta,
)

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = datetime.now().strftime("%Y%m%d")
OUT_DIR = DRIVE / "paul_experiments" / f"be_stop_replay_{STAMP}"
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0

RL_CASH = 47_500.0
RS_CASH = 16_216.0  # typical RS share scale from gold Closed PnL/$ vs %
VZ_CASH = 45_000.0

JOBS = [
    {
        "sys": "RL",
        "label": "EXIT",
        "knob": "rl_trail_profit=0.10 + rl_trail_stop=0 (BE after +10%)",
        "arm_mode": "pct10",
        "closed": DRIVE / "RL_LatestRun_Closed.csv",
        "cash": RL_CASH,
        "exists": "Yes — AWK/Python Trail 1 (`RL_TRAIL_PROFIT` / `rl_trail_profit`); DailyRun off (0).",
        "style": "rl",
    },
    {
        "sys": "RS",
        "label": "EXIT",
        "knob": "after MFE ≥ +1R, working stop = entry",
        "arm_mode": "1r",
        "closed": DRIVE
        / "paul_experiments"
        / "rs_baseline_260807141317"
        / "engine_closed"
        / "RS_Closed_260807141317.csv",
        "cash": RS_CASH,
        "exists": "No BE. Percent stop 0.85 / target 1.25 / time 252. `trailing_stop_increment=0`.",
        "style": "tbn",
    },
    {
        "sys": "VZ",
        "label": "EXIT",
        "knob": "after MFE ≥ +1R, working stop = entry (keep original target/time)",
        "arm_mode": "1r",
        "closed": DRIVE / "VZ_Closed_260817212836.csv",
        "cash": VZ_CASH,
        "exists": "No production BE. Research `EXIT_trail_be1r` already sketched in vz_improve_hints_ab.",
        "style": "tbn",
    },
]


def _f(v: Any, default: float = 0.0) -> float:
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
    s = str(s or "").strip()
    if not s:
        return None
    compact = s.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((s[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (s[:10], "%m/%d/%Y")):
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
            if k.strip() == n and v not in (None, ""):
                return str(v).strip()
    return ""


def load_closed(path: Path, style: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            if style == "rl":
                opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
                closed = _parse_d(_row_get(raw, "DATE CLOSED", "DATE_CLOSED"))
                entry = _f(_row_get(raw, "ENTRY PRICE", "ENTRY_PRICE"))
                stop = _f(_row_get(raw, "ORIGINAL STOP", "STOP LOSS AT CLOSE", "STOP_PRICE"))
                target = _f(_row_get(raw, "ORIGINAL TARGET", "TARGET_PRICE"))
                exit_px = _f(_row_get(raw, "EXIT PRICE", "EXIT_PRICE"))
                pnl = _f(_row_get(raw, "PNL %", "PNL_PCT"))
                days = _f(_row_get(raw, "DAYS HELD", "DAYS_HELD"))
                pnl_d = _f(_row_get(raw, "PNL_DOLLARS"))
                if pnl_d == 0.0 and pnl != 0.0:
                    pnl_d = RL_CASH * pnl / 100.0
                xt = _row_get(raw, "EXIT TYPE", "EXIT_TYPE")
            else:
                opened = _parse_d(_row_get(raw, "DATE_OPENED", "DATE OPENED"))
                closed = _parse_d(_row_get(raw, "DATE_CLOSED", "DATE CLOSED"))
                entry = _f(_row_get(raw, "ENTRY_PRICE", "ENTRY PRICE"))
                stop = _f(_row_get(raw, "STOP_PRICE", "ORIGINAL STOP"))
                target = _f(_row_get(raw, "TARGET_PRICE", "ORIGINAL TARGET"))
                exit_px = _f(_row_get(raw, "EXIT_PRICE", "EXIT PRICE"))
                pnl = _f(_row_get(raw, "PNL_PCT", "PNL %"))
                days = _f(_row_get(raw, "DAYS_HELD", "DAYS HELD"))
                pnl_d = _f(_row_get(raw, "PNL_DOLLARS"))
                xt = _row_get(raw, "EXIT_TYPE", "EXIT TYPE")
            sym = _row_get(raw, "SYMBOL").upper()
            if not sym or opened is None or closed is None or entry <= 0:
                continue
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "stop": stop if stop > 0 else entry * 0.90,
                    "target": target,
                    "exit_px": exit_px,
                    "pnl": pnl,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exit": xt or "UNKNOWN",
                }
            )
    return rows


_ohlc_cache: dict[str, Optional[pd.DataFrame]] = {}


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    if sym in _ohlc_cache:
        return _ohlc_cache[sym]
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        _ohlc_cache[sym] = None
        return None
    df = pd.read_csv(path, usecols=lambda c: str(c).lower() in {"date", "open", "high", "low", "close"})
    cols = {str(c).lower(): c for c in df.columns}
    df = df.rename(
        columns={
            cols["date"]: "Date",
            cols["open"]: "Open",
            cols["high"]: "High",
            cols["low"]: "Low",
            cols["close"]: "Close",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df = df.sort_values("Date").drop_duplicates("Date")
    out = df.set_index("Date")[["Open", "High", "Low", "Close"]].astype(float)
    _ohlc_cache[sym] = out
    return out


def replay_be(trade: dict[str, Any], ohlc: pd.DataFrame, arm_mode: str) -> dict[str, Any]:
    """Overlay BE stop. If never hit, keep original Closed exit."""
    entry = float(trade["entry"])
    stop0 = float(trade["stop"])
    risk = max(entry - stop0, entry * 0.005)
    arm_px = entry * 1.10 if arm_mode == "pct10" else entry + risk
    be = entry
    opened = trade["opened"]
    closed = trade["closed"]
    try:
        window = ohlc.loc[opened:closed]
    except Exception:
        return {**trade, "be_hit": False, "missing_bars": True}
    if window.empty:
        return {**trade, "be_hit": False, "missing_bars": True}
    dates = list(window.index)
    armed = False
    for i, d in enumerate(dates):
        o = float(window.loc[d, "Open"])
        h = float(window.loc[d, "High"])
        lo = float(window.loc[d, "Low"])
        if i == 0:
            # Entry session: arm on High only; do not BE-stop the fill bar.
            if h >= arm_px:
                armed = True
            continue
        if (not armed) and h >= arm_px:
            armed = True
        if not armed:
            continue
        # Stop-first vs target: BE is at entry. Gap through → open.
        if o <= be:
            pnl = (o - entry) / entry * 100.0
            days = max((d - opened).days, 1)
            if abs(trade["pnl"]) > 1e-9:
                notional = trade["pnl_d"] / (trade["pnl"] / 100.0)
                pnl_d = notional * pnl / 100.0
            else:
                pnl_d = 0.0
            return {
                **trade,
                "pnl": pnl,
                "pnl_d": pnl_d,
                "days": float(days),
                "exit": "TRAIL_BE",
                "exit_px": o,
                "be_hit": True,
                "missing_bars": False,
                "armed": True,
            }
        if lo <= be:
            pnl = 0.0
            days = max((d - opened).days, 1)
            return {
                **trade,
                "pnl": pnl,
                "pnl_d": 0.0,
                "days": float(days),
                "exit": "TRAIL_BE",
                "exit_px": be,
                "be_hit": True,
                "missing_bars": False,
                "armed": True,
            }
    return {**trade, "be_hit": False, "missing_bars": False, "armed": armed}


def book_stats(trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "ann_ror": 0.0,
        "wo_max": 0.0,
        "exits": {},
        "be_n": 0,
    }
    if n == 0:
        return empty
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg = sum(pnls) / n
    wo = (sum(pnls) - max(pnls)) / (n - 1) if n >= 2 else avg
    avg_days = sum(float(t["days"]) for t in trades) / n
    pnl_d = sum(float(t["pnl_d"]) for t in trades)
    sheet = sum(p / 100.0 * SHEET for p in pnls)
    ann = ann_ror_from_closed(total_pnl=pnl_d, n_trades=n, avg_days_held=avg_days, brt_cash=cash) or 0.0
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": avg,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sheet,
        "pnl_d": pnl_d,
        "avg_days": avg_days,
        "ann_ror": ann,
        "wo_max": wo,
        "exits": dict(Counter(str(t["exit"]) for t in trades)),
        "be_n": sum(1 for t in trades if t.get("be_hit")),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def verdict(ctrl: dict, cand: dict, oos_c: dict, oos_a: dict) -> tuple[str, str]:
    """Quality over N. OOS soften → HOLD. Overlay keeps N fixed."""
    d_avg = cand["avg_pnl"] - ctrl["avg_pnl"]
    d_wr = cand["wr"] - ctrl["wr"]
    d_pf = cand["pf"] - ctrl["pf"]
    d_wo = cand["wo_max"] - ctrl["wo_max"]
    is_better = (d_avg > 0.05 and d_wo > -0.05) or (d_avg > -0.05 and d_wr > 0.5 and d_pf > 0)
    is_worse = d_avg < -0.05 and d_wo < 0 and d_pf <= 0
    oos_soft = False
    oos_note = "OOS n/a"
    if oos_c["n"] >= 20 and oos_a["n"] >= 20:
        oos_soft = (oos_a["avg_pnl"] < oos_c["avg_pnl"] - 0.15) or (oos_a["wr"] < oos_c["wr"] - 1.0)
        oos_note = (
            f"OOS ΔAvgPnL {oos_a['avg_pnl']-oos_c['avg_pnl']:+.2f}pp, "
            f"ΔWR {oos_a['wr']-oos_c['wr']:+.1f}pp"
        )
        if oos_soft:
            oos_note += " — softened"
    if is_worse:
        return "DISMISS", oos_note
    if is_better and oos_soft:
        return "HOLD", oos_note + " (IS up, do not retune OOS)"
    if is_better and not oos_soft:
        return "KEEP", oos_note + " — research-only, not DailyRun"
    return "HOLD", oos_note + " (flat/mixed quality)"


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e8e4d8}
.sort-ind{display:inline-block;width:0.9em;margin-left:4px;color:#9a9588;font-size:10px}
th.sort-asc .sort-ind::after{content:"▲";color:#1c1b19}
th.sort-desc .sort-ind::after{content:"▼";color:#1c1b19}
"""

SORTABLE_TABLE_SCRIPT = r"""
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
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""

SKIPPED_IDEAS = [
    (
        "BRT",
        "EXIT",
        "No BE. `trailing_stop_increment=0` (DailyRun). ATR schedule off on whitelist. Gain ratchet exists in DNA but is not BE.",
        "After High ≥ entry+1R, raise working stop to entry (keep stop_pct/target_pct).",
        "No — full TBN run skipped (week-scale).",
        "—",
    ),
    (
        "WPBR",
        "EXIT",
        "No BE. Percent stop 0.91 / target 1.22. Same TBN exit host as BRT.",
        "After +1R, stop to entry (one knob vs Mag9 freeze).",
        "No — Mag9 DailyRun-scale skipped.",
        "—",
    ),
    (
        "YH",
        "EXIT",
        "No BE. stop_pct=0.934 / target 1.21.",
        "After +1R, stop to entry.",
        "No — skipped.",
        "—",
    ),
    (
        "SB",
        "EXIT",
        "No BE. LOD stop; target 1.097; NO_FT 3d; TIME 5d.",
        "After High ≥ entry+0.5R, stop to entry (keep 5d TIME).",
        "No — 5d sleeve; BE rarely binds; skipped.",
        "—",
    ),
    (
        "MTS",
        "EXIT",
        "No BE. Trigger-low × 0.934; target 1.22.",
        "After +1R vs trigger-low risk, stop to entry.",
        "No — skipped.",
        "—",
    ),
    (
        "MVCP",
        "EXIT",
        "Parked (2026-08-12). stop 0.92 / target 1.25. No BE in engine.",
        "Parked — do not AB. If revived: +1R then BE.",
        "No — parked.",
        "Parked",
    ),
]


def fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def fmt_pp(x: float) -> str:
    return f"{x:+.2f}pp"


def exit_mix(d: dict) -> str:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k}:{v}" for k, v in items[:8])


def run_job(job: dict) -> dict[str, Any]:
    ctrl = load_closed(job["closed"], job["style"])
    cand: list[dict[str, Any]] = []
    missing_sym = 0
    for t in ctrl:
        df = load_ohlc(t["sym"])
        if df is None:
            missing_sym += 1
            cand.append({**t, "be_hit": False, "missing_bars": True, "armed": False})
            continue
        cand.append(replay_be(t, df, job["arm_mode"]))
    is_c, oos_c = split_is_oos(ctrl)
    is_a, oos_a = split_is_oos(cand)
    cash = job["cash"]
    m_ctrl = book_stats(ctrl, cash)
    m_cand = book_stats(cand, cash)
    m_is_c = book_stats(is_c, cash)
    m_is_a = book_stats(is_a, cash)
    m_oos_c = book_stats(oos_c, cash)
    m_oos_a = book_stats(oos_a, cash)
    verd, note = verdict(m_ctrl, m_cand, m_oos_c, m_oos_a)
    return {
        "job": job,
        "ctrl": ctrl,
        "cand": cand,
        "m_ctrl": m_ctrl,
        "m_cand": m_cand,
        "m_is_c": m_is_c,
        "m_is_a": m_is_a,
        "m_oos_c": m_oos_c,
        "m_oos_a": m_oos_a,
        "verd": verd,
        "note": note,
        "missing_sym": missing_sym,
    }


def metric_rows_html(results: list[dict]) -> str:
    parts = []
    headers = filter_html_compare_columns(
        [
            ("System", "text"),
            ("Book", "text"),
            ("N", "num"),
            ("Win%", "num"),
            ("Avg PnL%", "num"),
            ("AVG_PNL_PCT_WO_MAX", "num"),
            ("Avg win%", "num"),
            ("Avg loss%", "num"),
            ("PF", "num"),
            ("Sheet PnL $", "num"),
            ("Total PnL $", "num"),
            ("Ann ROR%", "num"),
            ("Avg days", "num"),
            ("BE hits", "num"),
            ("Exit mix", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in headers)
    for r in results:
        job = r["job"]
        for label, m, delta in (
            ("control", r["m_ctrl"], False),
            ("BE candidate", r["m_cand"], False),
            ("Δ candidate−control", None, True),
        ):
            if delta:
                a, b = r["m_cand"], r["m_ctrl"]
                cells = [
                    job["sys"],
                    label,
                    str(a["n"] - b["n"]),
                    fmt_pp(a["wr"] - b["wr"]),
                    fmt_pp(a["avg_pnl"] - b["avg_pnl"]),
                    fmt_pp(a["wo_max"] - b["wo_max"]),
                    fmt_pp(a["avg_win"] - b["avg_win"]),
                    fmt_pp(a["avg_loss"] - b["avg_loss"]),
                    f"{a['pf']-b['pf']:+.2f}",
                    fmt_pp(a["ann_ror"] - b["ann_ror"]),
                    f"{a['avg_days']-b['avg_days']:+.1f}",
                    str(a["be_n"]),
                    "",
                ]
            else:
                cells = [
                    job["sys"],
                    label,
                    str(m["n"]),
                    fmt_pct(m["wr"]),
                    fmt_pct(m["avg_pnl"]),
                    fmt_pct(m["wo_max"]),
                    fmt_pct(m["avg_win"]),
                    fmt_pct(m["avg_loss"]),
                    f"{m['pf']:.2f}",
                    fmt_pct(m["ann_ror"]),
                    f"{m['avg_days']:.1f}",
                    str(m["be_n"]),
                    html_mod.escape(exit_mix(m["exits"])),
                ]
            parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f'<table class="sortable"><caption>Click column headers to sort. Overlay keeps trade count fixed.</caption><thead><tr>{th}</tr></thead><tbody>{"".join(parts)}</tbody></table>'


def isoos_html(results: list[dict]) -> str:
    headers = filter_html_compare_columns(
        [
            ("System", "text"),
            ("Arm", "text"),
            ("Split", "text"),
            ("N", "num"),
            ("Win%", "num"),
            ("Avg PnL%", "num"),
            ("WO_MAX", "num"),
            ("PF", "num"),
            ("Sheet PnL $", "num"),
            ("Ann ROR%", "num"),
            ("Avg days", "num"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in headers)
    parts = []
    for r in results:
        sys = r["job"]["sys"]
        for arm, keyc, keya in (("control", "m_is_c", "m_oos_c"), ("BE", "m_is_a", "m_oos_a")):
            for split, mk in (("IS", keyc), ("OOS", keya)):
                m = r[mk]
                parts.append(
                    "<tr>"
                    + "".join(
                        f"<td>{c}</td>"
                        for c in [
                            sys,
                            arm,
                            split,
                            str(m["n"]),
                            fmt_pct(m["wr"]),
                            fmt_pct(m["avg_pnl"]),
                            fmt_pct(m["wo_max"]),
                            f"{m['pf']:.2f}",
                            fmt_pct(m["ann_ror"]),
                            f"{m['avg_days']:.1f}",
                        ]
                    )
                    + "</tr>"
                )
    return f'<table class="sortable"><caption>IS = entry_date &lt; 2024-01-01; OOS report-only. Click headers to sort.</caption><thead><tr>{th}</tr></thead><tbody>{"".join(parts)}</tbody></table>'


def idea_table_html(results: list[dict]) -> str:
    by = {r["job"]["sys"]: r for r in results}
    headers = [
        ("System", "text"),
        ("ENTRY vs EXIT", "text"),
        ("BE already exists?", "text"),
        ("Proposed one-knob", "text"),
        ("AB ran?", "text"),
        ("Verdict", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    rows = []
    for job in JOBS:
        r = by[job["sys"]]
        rows.append(
            (
                job["sys"],
                job["label"],
                job["exists"],
                job["knob"],
                f"Yes — Closed OHLC overlay ({r['m_cand']['be_n']} BE hits; missing OHLC symbols={r['missing_sym']})",
                f"{r['verd']} — {r['note']}",
            )
        )
    rows.extend(SKIPPED_IDEAS)
    body = "".join(
        "<tr>" + "".join(f"<td>{html_mod.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows
    )
    return f'<table class="sortable"><caption>Click column headers to sort.</caption><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def write_html(results: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    verd_bits = " · ".join(f"{r['job']['sys']} {r['verd']}" for r in results)
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>BE stop overlay A/B — {STAMP}</title>
<style>
:root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4; --fill:#f0eee6; --accent:#2a4a5c; }}
body {{ margin:0; font-family:"Segoe UI",Georgia,serif; font-size:15px; color:var(--ink); background:var(--bg); }}
.wrap {{ max-width:1200px; margin:0 auto; padding:32px 20px 64px; }}
h1 {{ font-size:1.55rem; margin:0 0 8px; }}
h2 {{ font-size:1.12rem; margin:28px 0 10px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.muted {{ color:var(--muted); font-size:0.9rem; }}
.callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:14px 0; }}
.table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
thead th {{ background:var(--fill); }}
{SORTABLE_TH_CSS}
caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
code {{ background:var(--fill); padding:0.08em 0.3em; font-size:0.86em; }}
</style></head><body>
<div class="wrap">
<p class="muted">Twin Beacon Networks (TBN) · research candidate · not gold · not DailyRun</p>
<h1>Move-stop-to-breakeven overlay A/B</h1>
<p>Control = existing Closed books. Candidate = same trades, EXIT only: after the arm threshold, raise stop to entry.
No entry changes. Max 3 cheap OHLC replays (RL, RS, VZ). Judge quality (WR, Avg PnL%, PF, WO_MAX), not N.
Chronological split: IS entry &lt; 2024-01-01; OOS report-only. OOS soften → HOLD, do not retune.</p>
<div class="callout"><strong>Verdicts:</strong> {html_mod.escape(verd_bits)}</div>

<h2>Per-system idea table</h2>
<div class="table-wrap">{idea_table_html(results)}</div>

<h2>Book metrics (full history)</h2>
<p class="muted">Canonical compare set (subset of <code>CANONICAL_COMPARE_METRICS.md</code>): N, Win%, Avg PnL%, AVG_PNL_PCT_WO_MAX, avg win/loss, PF, Sheet PnL, Total PnL, Ann ROR, days held, exit mix. Dollar fields use $nnn,nnn.nn.</p>
<div class="table-wrap">{metric_rows_html(results)}</div>

<h2>IS / OOS</h2>
<div class="table-wrap">{isoos_html(results)}</div>

<h2>Freeze / method</h2>
<ul>
<li><strong>RL control:</strong> <code>drive/RL_LatestRun_Closed.csv</code> — production trail off (<code>rl_trail_profit=0</code>). DNA already has Trail 1 = entry × (1+<code>RL_TRAIL_STOP</code>) after High ≥ entry × (1+<code>RL_TRAIL_PROFIT</code>). Knob tested: profit=0.10, stop=0 (BE).</li>
<li><strong>RS control:</strong> gold freeze <code>rs_baseline_260807141317</code> stop 0.85 / target 1.25 / time 252. Knob: +1R then BE.</li>
<li><strong>VZ control:</strong> DualPaul78 stamp <code>260817212836</code> (Closed already has STOP/TARGET). Knob: +1R then BE. Stamp exit mix is the stamp’s recipe, not necessarily <code>zone_atr05_ts40</code>.</li>
<li>Replay starts the session after fill; BE can only exit earlier than the original close (never extends a hold).</li>
<li>Missing local OHLC → trade left on control exit.</li>
<li>Ann ROR uses Closed PnL $ + freeze cash (RL $47,500 / RS ~$16,216 / VZ $45,000) — not a full equity curve.</li>
</ul>
<p class="muted">Generated {STAMP} by <code>tools/be_stop_replay_ab.py</code>.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "be_stop_replay_ab.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(results: list[dict]) -> Path:
    lines = [
        "# BE stop overlay — freeze / hypothesis",
        "",
        "Research-only Closed OHLC overlay. Not DailyRun. One EXIT knob per system.",
        "",
        "| System | Control stamp | Knob | Frozen | Selection |",
        "|---|---|---|---|---|",
        "| RL | RL_LatestRun_Closed | EXIT `rl_trail_profit=0.10`, `rl_trail_stop=0` | entries, SMA target, stop_pct, no trail2 | overlay on production-off trail |",
        "| RS | 260807141317 gold | EXIT +1R then BE | stop 0.85 / target 1.25 / time 252 / univ 64–65 | overlay |",
        "| VZ | DualPaul78 260817212836 | EXIT +1R then BE | stamp entries + stop/target | overlay |",
        "",
        "IS = entry_date < 2024-01-01; OOS report-only.",
        "",
    ]
    for r in results:
        lines.append(f"- **{r['job']['sys']}** → **{r['verd']}** ({r['note']})")
    path = OUT_DIR / "BASELINE.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    results = []
    for job in JOBS:
        print(f"[BE] {job['sys']} loading {job['closed'].name} ...", flush=True)
        r = run_job(job)
        results.append(r)
        print(
            f"  N={r['m_ctrl']['n']} BE_hits={r['m_cand']['be_n']} "
            f"dAvgPnl={r['m_cand']['avg_pnl']-r['m_ctrl']['avg_pnl']:+.3f} "
            f"dWR={r['m_cand']['wr']-r['m_ctrl']['wr']:+.2f} -> {r['verd']}",
            flush=True,
        )
    html_path = write_html(results)
    write_baseline(results)
    print(f"[BE] wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
