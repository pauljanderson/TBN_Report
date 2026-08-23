#!/usr/bin/env python3
"""Live DualPaul78 VZ trade-side A/B — long vs short vs both.

Control vs short-only vs long+short union. Research-only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import format_money, format_money_delta, overlay_ann_ror_max_dd  # noqa: E402

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments" / "vz_short_side_20260819"
CTRL_STAMP = "260819140929"
CTRL_DIR = DRIVE / "paul_experiments" / "vz_hvn_engine_ab_20260819" / "live_ctrl"
SHORT_STAMP = ""
BOTH_STAMP = ""
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT = 500_000.0
EXIT_KEYS = ("TARGET", "STOP_LOSS", "GAP_UP", "GAP_DOWN", "TIME", "STOP")


def _f(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s or s.upper() in {"N/A", "NONE"}:
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


def load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE_OPENED"))
            if opened is None:
                continue
            pnl = _f(_row_get(raw, "PNL_PCT", "PNL %"), 0.0)
            side = _row_get(raw, "SIDE").upper() or "LONG"
            rows.append(
                {
                    "sym": _row_get(raw, "SYMBOL").upper(),
                    "side": side,
                    "opened": opened,
                    "closed": _parse_d(_row_get(raw, "DATE_CLOSED")),
                    "pnl": pnl,
                    "r": _f(_row_get(raw, "R_MULT"), 0.0),
                    "days": _f(_row_get(raw, "DAYS_HELD"), 0.0),
                    "pnl_d": _f(_row_get(raw, "PNL_DOLLARS"), 0.0),
                    "exit": _row_get(raw, "EXIT_TYPE"),
                    "zone_id": _row_get(raw, "ZONE_ID"),
                }
            )
    return rows


def _p90(vals: list[float]) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    return float(s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))])


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "be": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_r": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "total_pnl_d": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "p90_days": float("nan"),
        "syms": 0,
        "avg_wo_max": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "cap_days": 0.0,
        "ppc": float("nan"),
        "avg_win": float("nan"),
        "avg_loss": float("nan"),
        "wl_n": float("nan"),
        "wl_d": float("nan"),
        "exp_pct": 0.0,
        "exp_d": 0.0,
        "tpy": float("nan"),
        "equity_note": "no trades",
        "exits": {},
        "long_n": 0,
        "short_n": 0,
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    be = [p for p in pnls if p == 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else pnls[0]
    rs = [t["r"] for t in trades if math.isfinite(t["r"])]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    cap = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT)
    cap_days = float(cap["capital_days"] or 0.0)
    sheet = sum(p / 100.0 * SHEET for p in pnls)
    total_d = sum(t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"]))
    opens = [t["opened"] for t in trades if t["opened"]]
    closes = [t["closed"] for t in trades if t["closed"]]
    span = None
    if opens:
        lo = min(opens)
        hi = max(closes) if closes else max(opens)
        span = (hi - lo).days / 365.25
    tpy = (n / span) if span and span > 0 else float("nan")
    win_d = sum(t["pnl_d"] for t in trades if t["pnl"] > 0 and math.isfinite(t["pnl_d"]))
    loss_d = abs(sum(t["pnl_d"] for t in trades if t["pnl"] < 0 and math.isfinite(t["pnl_d"])))
    exits = Counter(str(t.get("exit") or "").strip().upper() or "?" for t in trades)
    long_n = sum(1 for t in trades if t.get("side") == "LONG")
    short_n = sum(1 for t in trades if t.get("side") == "SHORT")
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "be": len(be),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": (sum(rs) / len(rs)) if rs else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sheet,
        "total_pnl_d": total_d,
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "med_days": sorted(days)[len(days) // 2] if days else 0.0,
        "p90_days": _p90(days),
        "syms": len({t["sym"] for t in trades if t["sym"]}),
        "avg_wo_max": wo,
        "ann_ror": cap["ann_ror"],
        "max_dd": cap["max_dd"],
        "cap_days": cap_days,
        "ppc": (total_d / cap_days) if cap_days > 0 else float("nan"),
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "wl_n": (len(wins) / len(losses)) if losses else float("nan"),
        "wl_d": (win_d / loss_d) if loss_d > 0 else float("nan"),
        "exp_pct": sum(pnls) / n,
        "exp_d": sheet / n,
        "tpy": tpy,
        "equity_note": cap["note"],
        "exits": dict(exits),
        "long_n": long_n,
        "short_n": short_n,
    }


def pack(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    is_t = [t for t in trades if t["opened"] < IS_CUT]
    oos_t = [t for t in trades if t["opened"] >= IS_CUT]
    long_t = [t for t in trades if t.get("side") == "LONG"]
    short_t = [t for t in trades if t.get("side") == "SHORT"]
    return {
        "name": name,
        "full": book_stats(trades),
        "is": book_stats(is_t),
        "oos": book_stats(oos_t),
        "long": book_stats(long_t),
        "short": book_stats(short_t),
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
    ann_c, ann_k = cand["is"]["ann_ror"], ctrl["is"]["ann_ror"]
    dd_c, dd_k = cand["is"]["max_dd"], ctrl["is"]["max_dd"]
    ann_dd_worse = (
        math.isfinite(ann_c)
        and math.isfinite(ann_k)
        and math.isfinite(dd_c)
        and math.isfinite(dd_k)
        and ann_c < ann_k
        and dd_c > dd_k
    )
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
            f"but OOS softened — do not retune."
        )
    if ann_dd_worse:
        return "HOLD", "IS Ann ROR fell and Max DD worsened vs control — downgrade KEEP to HOLD."
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
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        table.querySelectorAll("th.sortable-th").forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        sortTable(table, idx, type, asc ? "asc" : "desc");
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  });
})();
</script>
"""


def fmt_n(v: Any, nd: int) -> str:
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
    try:
        c = float(cand)
        k = float(ctrl)
        if not (math.isfinite(c) and math.isfinite(k)):
            return "—"
    except (TypeError, ValueError):
        return "—"
    d = c - k
    if money:
        return format_money_delta(d)
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.{nd}f}"


def metrics_table_3arm(
    rows: list[tuple],
    packed: list[dict[str, Any]],
    title: str,
    caption: str,
    split: str = "full",
) -> str:
    """packed[0]=control, [1]=short, [2]=both."""
    head = sortable_th("Metric", "text")
    for p in packed:
        head += sortable_th(p["name"], "num")
    head += sortable_th("Δ short vs ctrl", "num")
    head += sortable_th("Δ both vs ctrl", "num")
    body = ""
    for label, getter, nd, money in rows:
        body += f"<tr><td>{html_mod.escape(label)}</td>"
        vals = []
        for p in packed:
            v = getter(p)
            vals.append(v)
            cell = format_money(v) if money else fmt_n(v, nd)
            body += f'<td class="num">{cell}</td>'
        body += f'<td class="num">{delta_cell(vals[1], vals[0], nd, money=money)}</td>'
        body += f'<td class="num">{delta_cell(vals[2], vals[0], nd, money=money)}</td></tr>'
    return (
        f"<h3>{html_mod.escape(title)}</h3>"
        f"<p class='small'>{html_mod.escape(caption)} Click column headers to sort.</p>"
        f"<table class='sortable'><caption>Click column headers to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def closed_spec(split: str) -> list[tuple]:
    g = lambda k: (lambda p, _k=k, _s=split: p[_s][_k])
    rows = [
        ("Closed N (context)", g("n"), 0, False),
        ("Wins", g("wins"), 0, False),
        ("Losses", g("losses"), 0, False),
        ("BE", g("be"), 0, False),
        ("Win %", g("wr"), 1, False),
        ("Total PnL $ (Closed dollars)", g("total_pnl_d"), 2, True),
        ("Sheet PnL $", g("sheet"), 2, True),
        ("Avg PnL %", g("avg_pnl"), 2, False),
        ("Book AVG_PNL_PCT_WO_MAX", g("avg_wo_max"), 2, False),
        ("AvgR", g("avg_r"), 2, False),
        ("Expectancy $ / trade", g("exp_d"), 2, True),
        ("Expectancy %", g("exp_pct"), 2, False),
        ("Avg win %", g("avg_win"), 2, False),
        ("Avg loss %", g("avg_loss"), 2, False),
        ("Win/Loss ratio (count)", g("wl_n"), 2, False),
        ("Win/Loss ratio $", g("wl_d"), 2, False),
        ("Profit factor", g("pf"), 2, False),
        ("Ann ROR % (Closed overlay, $45k / $500k DD)", g("ann_ror"), 1, False),
        ("Max DD % (Closed overlay $500k)", g("max_dd"), 2, False),
        ("Profit / capital day $", g("ppc"), 2, True),
        ("Capital days", g("cap_days"), 0, False),
        ("Avg days held", g("avg_days"), 1, False),
        ("Median days held", g("med_days"), 1, False),
        ("P90 days held", g("p90_days"), 1, False),
        ("Trades / year (span)", g("tpy"), 2, False),
        ("Names", g("syms"), 0, False),
        ("LONG count (SIDE)", g("long_n"), 0, False),
        ("SHORT count (SIDE)", g("short_n"), 0, False),
    ]
    for ek in EXIT_KEYS:
        rows.append((f"Exit {ek} N", lambda p, e=ek, s=split: float(p[s]["exits"].get(e, 0)), 0, False))
        rows.append(
            (
                f"Exit {ek} %",
                lambda p, e=ek, s=split: (
                    100.0 * p[s]["exits"].get(e, 0) / p[s]["n"] if p[s]["n"] else float("nan")
                ),
                1,
                False,
            )
        )
    return rows


def side_breakdown_table(both_pack: dict[str, Any], split: str, title: str) -> str:
    """LONG vs SHORT within the both arm only."""
    rows = closed_spec(split)
    long_p = {"name": "both LONG", split: both_pack[split] if split != "long" else both_pack["long"]}
    short_p = {"name": "both SHORT", split: both_pack[split] if split != "short" else both_pack["short"]}
    # Re-pack as pseudo packs with only the split we need
    lp = {"name": "both LONG", split: both_pack["long" if split == "full" else split.replace("is", "is").replace("oos", "oos")]}
    sp = {"name": "both SHORT", split: both_pack["short" if split == "full" else ("long" if split == "long" else "short")]}
    if split == "is":
        lp = {"name": "both LONG (IS)", "is": book_stats([t for t in []])}
        sp = {"name": "both SHORT (IS)", "is": both_pack["short"] if False else both_pack.get("short", {})}
    # Simpler: use precomputed long/short splits on both_pack
    split_map = {"full": ("long", "short"), "is": ("long", "short"), "oos": ("long", "short")}
    # both_pack has long/short at top level for full; for is/oos we need nested - extend pack()
    head = sortable_th("Metric", "text") + sortable_th("both LONG", "num") + sortable_th("both SHORT", "num")
    body = ""
    src_long = both_pack.get("long", {}).get(split, both_pack.get("long", {})) if split in ("is", "oos") else both_pack["long"]
    src_short = both_pack.get("short", {}).get(split, both_pack.get("short", {})) if split in ("is", "oos") else both_pack["short"]
    if split in ("is", "oos"):
        # Recompute from stored - pack stores long/short at top as full only; use keys is/oos on long/short sub-packs
        pass
    # pack() stores long/short as book_stats of filtered trades - only full split
    # For IS/OOS side breakdown, filter during pack - add is_long, is_short later if needed
    long_stats = both_pack["long"] if split == "full" else (
        both_pack.get(f"{split}_long") or both_pack["long"]
    )
    short_stats = both_pack["short"] if split == "full" else (
        both_pack.get(f"{split}_short") or both_pack["short"]
    )
    for label, getter, nd, money in closed_spec(split):
        # getter expects pack dict with split key - build fake packs
        fake_l = {split: long_stats}
        fake_s = {split: short_stats}
        vl = getter(fake_l)
        vs = getter(fake_s)
        body += f"<tr><td>{html_mod.escape(label)}</td>"
        body += f'<td class="num">{format_money(vl) if money else fmt_n(vl, nd)}</td>'
        body += f'<td class="num">{format_money(vs) if money else fmt_n(vs, nd)}</td></tr>'
    return (
        f"<h3>{html_mod.escape(title)}</h3>"
        f"<p class='small'>Within <code>vz_trade_side=both</code> arm only. Click column headers to sort.</p>"
        f"<table class='sortable'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def load_first_row(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        row = next(r, None)
        return dict(row) if row else {}


def mean_num(rows: list[dict], *keys: str) -> float:
    vals = []
    for r in rows:
        v = _f(_row_get(r, *keys))
        if math.isfinite(v):
            vals.append(v)
    return (sum(vals) / len(vals)) if vals else float("nan")


def sum_num(rows: list[dict], *keys: str) -> float:
    vals = []
    for r in rows:
        v = _f(_row_get(r, *keys))
        if math.isfinite(v):
            vals.append(v)
    return float(sum(vals)) if vals else float("nan")


def report_pack(folder: Path, stamp: str, name: str) -> dict[str, Any]:
    rep = load_first_row(folder / f"VZ_Report_{stamp}.csv")
    meta = load_first_row(folder / f"VZ_EquityMeta_{stamp}.csv")
    summ_path = folder / f"VZ_Summary_Symbols_{stamp}.csv"
    srows: list[dict[str, str]] = []
    if summ_path.is_file():
        with summ_path.open(newline="", encoding="utf-8-sig") as f:
            srows = list(csv.DictReader(f))
    return {
        "name": name,
        "total_pnl": _f(_row_get(rep, "Total_PNL")),
        "sheet": _f(_row_get(rep, "sheet_PnL", "Sheet_PnL")),
        "n": _f(_row_get(rep, "Total_Trades")),
        "wins": _f(_row_get(rep, "Wins")),
        "losses": _f(_row_get(rep, "Losses")),
        "be": _f(_row_get(rep, "BE")),
        "wr": _f(_row_get(rep, "Pct_Wins")),
        "avg_pnl": _f(_row_get(rep, "Avg_PNL_Pct")),
        "pf": _f(_row_get(rep, "Profit_Factor")),
        "ann_ror": _f(_row_get(rep, "Ann_ROR")),
        "max_dd": _f(_row_get(rep, "Max_DD")),
        "exp": _f(_row_get(rep, "Expectancy")),
        "exp_pct": _f(_row_get(rep, "Expectancy_Pct")),
        "avg_win": _f(_row_get(rep, "Avg_Win_Pct")),
        "avg_loss": _f(_row_get(rep, "Avg_Loss_Pct")),
        "wl_n": _f(_row_get(rep, "Win_Loss_Ratio")),
        "wl_d": _f(_row_get(rep, "Win_Loss_Ratio_Dollar")),
        "avg_days": _f(_row_get(rep, "Avg_Days_Held")),
        "med_days": _f(_row_get(rep, "Median_Days_Held")),
        "p90_days": _f(_row_get(rep, "P90_Days")),
        "avg_uw": _f(_row_get(rep, "Avg_Days_Underwater")),
        "p90_uw": _f(_row_get(rep, "P90_Days_Underwater")),
        "cap_days": _f(_row_get(rep, "Capital_Days")),
        "ppc": _f(_row_get(rep, "Profit_Per_Capital_Day")),
        "streak": _f(_row_get(rep, "Losing_Streak")),
        "ces_avg": _f(_row_get(rep, "CES_AVG")),
        "ces_med": _f(_row_get(rep, "CES_Median")),
        "top10": _f(_row_get(rep, "Pct_PNL_Top10")),
        "bot10": _f(_row_get(rep, "Pct_PNL_Bottom10")),
        "max_pos": _f(_row_get(rep, "Max_Positions")),
        "avg_pos": _f(_row_get(rep, "Avg_Positions")),
        "med_pos": _f(_row_get(rep, "Median_Positions")),
        "conc_sym": _f(_row_get(rep, "Pct_PNL_Max_Symbol")),
        "conc_tr": _f(_row_get(rep, "Pct_PNL_Max_Trade")),
        "conc_ind": _f(_row_get(rep, "Pct_PNL_Max_Industry")),
        "agg_pnl": _f(_row_get(rep, "Aggressive_Total_PNL")),
        "agg_dd": _f(_row_get(rep, "Aggressive_Max_DD")),
        "eq_dd": _f(_row_get(meta, "Max_Drawdown_pct")),
        "eq_uw_days": _f(_row_get(meta, "Max_Days_Underwater")),
        "eq_uw_pct": _f(_row_get(meta, "Pct_Days_Underwater")),
        "sum_paul": sum_num(srows, "PAUL_SCORE"),
        "mean_paul": mean_num(srows, "PAUL_SCORE"),
        "sum_fit": sum_num(srows, "FIT_SCORE"),
        "mean_fit": mean_num(srows, "FIT_SCORE"),
        "sum_robust": sum_num(srows, "FIT_SCORE_ROBUST"),
        "mean_robust": mean_num(srows, "FIT_SCORE_ROBUST"),
        "mean_wo": mean_num(srows, "AVG_PNL_PCT_WO_MAX"),
        "mean_out": mean_num(srows, "OUTLIER_PCT_OF_WINS"),
        "mean_tpy": mean_num(srows, "AVG_TRADES_PER_YEAR"),
        "mean_maxw": mean_num(srows, "MAX_WIN_PCT"),
        "n_sym_sum": float(len(srows)),
    }


def report_spec() -> list[tuple]:
    g = lambda k: (lambda p, _k=k: p[_k])
    return [
        ("Universe names (Summary_Symbols rows)", g("n_sym_sum"), 0, False),
        ("Total trades", g("n"), 0, False),
        ("Wins", g("wins"), 0, False),
        ("Losses", g("losses"), 0, False),
        ("BE", g("be"), 0, False),
        ("Win %", g("wr"), 1, False),
        ("Total PnL $ (Report)", g("total_pnl"), 2, True),
        ("Sheet PnL $ (Report)", g("sheet"), 2, True),
        ("Avg PnL %", g("avg_pnl"), 2, False),
        ("Expectancy $", g("exp"), 2, True),
        ("Expectancy %", g("exp_pct"), 2, False),
        ("Avg win %", g("avg_win"), 2, False),
        ("Avg loss %", g("avg_loss"), 2, False),
        ("Win/Loss ratio (count)", g("wl_n"), 2, False),
        ("Win/Loss ratio $", g("wl_d"), 2, False),
        ("Profit factor", g("pf"), 2, False),
        ("Ann ROR % (Report / Audit)", g("ann_ror"), 1, False),
        ("Max DD % (Report host MTM)", g("max_dd"), 2, False),
        ("EquityMeta Max DD %", g("eq_dd"), 2, False),
        ("Profit / capital day $", g("ppc"), 2, True),
        ("Capital days", g("cap_days"), 0, False),
        ("Avg days held", g("avg_days"), 1, False),
        ("Median days held", g("med_days"), 1, False),
        ("P90 days held", g("p90_days"), 1, False),
        ("Avg days underwater", g("avg_uw"), 1, False),
        ("P90 days underwater", g("p90_uw"), 1, False),
        ("EquityMeta max days UW", g("eq_uw_days"), 0, False),
        ("EquityMeta % days UW", g("eq_uw_pct"), 1, False),
        ("Losing streak", g("streak"), 0, False),
        ("Avg positions", g("avg_pos"), 2, False),
        ("Median positions", g("med_pos"), 1, False),
        ("Max positions", g("max_pos"), 0, False),
        ("Aggressive Total PnL $", g("agg_pnl"), 2, True),
        ("Aggressive Max DD %", g("agg_dd"), 2, False),
        ("Pct PnL max symbol", g("conc_sym"), 2, False),
        ("Pct PnL max trade", g("conc_tr"), 2, False),
        ("Pct PnL max industry", g("conc_ind"), 2, False),
        ("Pct PnL top10", g("top10"), 1, False),
        ("Pct PnL bottom10", g("bot10"), 1, False),
        ("CES avg", g("ces_avg"), 2, False),
        ("CES median", g("ces_med"), 2, False),
        ("Σ Paul Score", g("sum_paul"), 0, False),
        ("Mean Paul Score", g("mean_paul"), 2, False),
        ("Σ FIT_SCORE", g("sum_fit"), 0, False),
        ("Mean FIT_SCORE", g("mean_fit"), 2, False),
        ("Σ FIT_SCORE_ROBUST", g("sum_robust"), 0, False),
        ("Mean FIT_SCORE_ROBUST", g("mean_robust"), 2, False),
        ("Mean AVG_PNL_PCT_WO_MAX", g("mean_wo"), 2, False),
        ("Mean OUTLIER_PCT_OF_WINS", g("mean_out"), 1, False),
        ("Mean AVG_TRADES_PER_YEAR", g("mean_tpy"), 2, False),
        ("Mean MAX_WIN_PCT", g("mean_maxw"), 2, False),
    ]


def pack_extended(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    base = pack(name, trades)
    is_t = [t for t in trades if t["opened"] < IS_CUT]
    oos_t = [t for t in trades if t["opened"] >= IS_CUT]
    base["is_long"] = book_stats([t for t in is_t if t.get("side") == "LONG"])
    base["is_short"] = book_stats([t for t in is_t if t.get("side") == "SHORT"])
    base["oos_long"] = book_stats([t for t in oos_t if t.get("side") == "LONG"])
    base["oos_short"] = book_stats([t for t in oos_t if t.get("side") == "SHORT"])
    return base


def side_breakdown_table_v2(both_pack: dict[str, Any], split: str, title: str) -> str:
    key_long = f"{split}_long" if split in ("is", "oos") else "long"
    key_short = f"{split}_short" if split in ("is", "oos") else "short"
    long_stats = both_pack[key_long]
    short_stats = both_pack[key_short]
    head = sortable_th("Metric", "text") + sortable_th("both LONG", "num") + sortable_th("both SHORT", "num")
    body = ""
    for label, getter, nd, money in closed_spec(split):
        fake_l = {split: long_stats}
        fake_s = {split: short_stats}
        vl = getter(fake_l)
        vs = getter(fake_s)
        body += f"<tr><td>{html_mod.escape(label)}</td>"
        body += f'<td class="num">{format_money(vl) if money else fmt_n(vl, nd)}</td>'
        body += f'<td class="num">{format_money(vs) if money else fmt_n(vs, nd)}</td></tr>'
    return (
        f"<h3>{html_mod.escape(title)}</h3>"
        f"<p class='small'>Within <code>vz_trade_side=both</code> arm. Click column headers to sort.</p>"
        f"<table class='sortable'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def overlap_stats(both_trades: list[dict[str, Any]]) -> dict[str, int]:
    long_keys = {(t["sym"], t["zone_id"], t["opened"]) for t in both_trades if t.get("side") == "LONG"}
    short_keys = {(t["sym"], t["zone_id"], t["opened"]) for t in both_trades if t.get("side") == "SHORT"}
    sym_long = {t["sym"] for t in both_trades if t.get("side") == "LONG"}
    sym_short = {t["sym"] for t in both_trades if t.get("side") == "SHORT"}
    sym_both = sym_long & sym_short
    return {
        "long_n": len(long_keys),
        "short_n": len(short_keys),
        "sym_overlap": len(sym_both),
        "sym_long": len(sym_long),
        "sym_short": len(sym_short),
    }


def find_closed(stamp: str, folder: Path) -> Path:
    p = folder / f"VZ_Closed_{stamp}.csv"
    if p.is_file():
        return p
    raise SystemExit(f"missing Closed for stamp {stamp} in {folder}")


def read_stamp_from_dir(folder: Path) -> str:
    for name in ("VZ_last_run_ts.txt", "last_run_ts.txt"):
        p = folder / name
        if p.is_file():
            ts = p.read_text(encoding="utf-8").strip()
            if ts:
                return ts
    closed = sorted(folder.glob("VZ_Closed_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    if closed:
        return closed[0].stem.replace("VZ_Closed_", "")
    raise SystemExit(f"no stamp in {folder}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control-stamp", default=CTRL_STAMP)
    ap.add_argument("--control-dir", type=Path, default=CTRL_DIR)
    ap.add_argument("--short-stamp", default="")
    ap.add_argument("--short-dir", type=Path, default=OUT_DIR / "live_short")
    ap.add_argument("--both-stamp", default="")
    ap.add_argument("--both-dir", type=Path, default=OUT_DIR / "live_both")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    short_stamp = args.short_stamp or read_stamp_from_dir(args.short_dir)
    both_stamp = args.both_stamp or read_stamp_from_dir(args.both_dir)

    ctrl_path = find_closed(args.control_stamp, args.control_dir)
    short_path = find_closed(short_stamp, args.short_dir)
    both_path = find_closed(both_stamp, args.both_dir)

    ctrl_trades = load_trades(ctrl_path)
    short_trades = load_trades(short_path)
    both_trades = load_trades(both_path)

    ctrl = pack_extended(f"00_control long {args.control_stamp}", ctrl_trades)
    short = pack_extended(f"01_short {short_stamp}", short_trades)
    both = pack_extended(f"02_both {both_stamp}", both_trades)
    packed = [ctrl, short, both]

    v_short, why_short = arm_verdict(ctrl, short)
    v_both, why_both = arm_verdict(ctrl, both)
    overlap = overlap_stats(both_trades)

    r_ctrl = report_pack(args.control_dir, args.control_stamp, ctrl["name"])
    r_short = report_pack(args.short_dir, short_stamp, short["name"])
    r_both = report_pack(args.both_dir, both_stamp, both["name"])
    rpacks = [r_ctrl, r_short, r_both]

    is_summary_rows = [
        ("N", lambda p: p["is"]["n"], 0, False),
        ("Win %", lambda p: p["is"]["wr"], 1, False),
        ("Avg PnL %", lambda p: p["is"]["avg_pnl"], 2, False),
        ("AvgR", lambda p: p["is"]["avg_r"], 2, False),
        ("PF", lambda p: p["is"]["pf"], 2, False),
        ("Ann ROR %", lambda p: p["is"]["ann_ror"], 1, False),
        ("Max DD %", lambda p: p["is"]["max_dd"], 2, False),
        ("Sheet PnL $", lambda p: p["is"]["sheet"], 2, True),
    ]
    oos_summary_rows = [
        ("N", lambda p: p["oos"]["n"], 0, False),
        ("Win %", lambda p: p["oos"]["wr"], 1, False),
        ("Avg PnL %", lambda p: p["oos"]["avg_pnl"], 2, False),
        ("AvgR", lambda p: p["oos"]["avg_r"], 2, False),
        ("PF", lambda p: p["oos"]["pf"], 2, False),
        ("Ann ROR %", lambda p: p["oos"]["ann_ror"], 1, False),
        ("Max DD %", lambda p: p["oos"]["max_dd"], 2, False),
        ("Sheet PnL $", lambda p: p["oos"]["sheet"], 2, True),
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ trade-side A/B — DualPaul78 — canonical metrics</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1600px; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.12rem; margin-top: 28px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
.verdict {{ border: 2px solid #b45309; background: #fff7ed; }}
.verdict h2 {{ margin: 0 0 8px; font-size: 1.1rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.84rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
table.sortable caption {{ text-align: left; color: #555; padding: 4px 0; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>VZ trade-side A/B — DualPaul78 — canonical metrics</h1>
<p class="sub">One knob: <code>vz_trade_side</code> (long | short | both). House freeze unchanged (HL-only, rw63, EXIT_atr4_s025_r15, HVN false).
Universe: DualPaul78 (<code>drive/universes/VZ_universe.csv</code>). IS = entry &lt; 2024-01-01; OOS report-only.
Research candidate ≠ gold ≠ DailyRun. Isolated <code>-o</code>; house pin unchanged.</p>
<div class="card">
<p><strong>Stamps:</strong> control <code>{html_mod.escape(args.control_stamp)}</code> (reused from HVN AB live_ctrl) ·
short <code>{html_mod.escape(short_stamp)}</code> · both <code>{html_mod.escape(both_stamp)}</code>.</p>
<p><strong>Both-arm overlap:</strong> {overlap['long_n']} LONG + {overlap['short_n']} SHORT trades;
{overlap['sym_overlap']} symbols traded both directions (long sleeve {overlap['sym_long']} names, short sleeve {overlap['sym_short']} names).
Same symbol can appear long and short on different zones/dates — not double-counted in N.</p>
</div>
<div class="card verdict">
<h2>01_short vs control: {html_mod.escape(v_short)}</h2>
<p>{html_mod.escape(why_short)}</p>
<h2>02_both vs control: {html_mod.escape(v_both)}</h2>
<p>{html_mod.escape(why_both)}</p>
<p>Default remains <strong>long</strong>. OOS soften → HOLD, do not retune.</p>
</div>
<h2>IS / OOS headline (Closed overlay)</h2>
{metrics_table_3arm(is_summary_rows, packed, "IS (entry < 2024-01-01)", "Judge KEEP/HOLD/DISMISS on quality over N.")}
{metrics_table_3arm(oos_summary_rows, packed, "OOS (entry >= 2024-01-01, report-only)", "Soften → HOLD.")}
<h2>Full book — Report / EquityMeta / Summary_Symbols</h2>
{metrics_table_3arm(report_spec(), rpacks, "Report + EquityMeta + Paul/FIT", "Host book sizing path.")}
<h2>IS / OOS / full — Closed overlay</h2>
{metrics_table_3arm(closed_spec("is"), packed, "IS Closed overlay", "Primary judge split.")}
{metrics_table_3arm(closed_spec("oos"), packed, "OOS Closed overlay", "Report-only.")}
{metrics_table_3arm(closed_spec("full"), packed, "Full Closed overlay", "Ann ROR sheet $45k; Max DD seeds $500k.")}
<h2>SIDE breakdown — both arm only</h2>
{side_breakdown_table_v2(both, "full", "Both arm — full book LONG vs SHORT")}
{side_breakdown_table_v2(both, "is", "Both arm — IS LONG vs SHORT")}
{side_breakdown_table_v2(both, "oos", "Both arm — OOS LONG vs SHORT")}
<p class="small">Do not judge on max single-trade PnL. Full metric set per CANONICAL_COMPARE_METRICS.md.</p>
{SORT_JS}
</body>
</html>
"""

    # Fix OOS summary table - the lambda hack above is broken; build properly
    oos_rows = [
        ("N", lambda p: p["oos"]["n"], 0, False),
        ("Win %", lambda p: p["oos"]["wr"], 1, False),
        ("Avg PnL %", lambda p: p["oos"]["avg_pnl"], 2, False),
        ("AvgR", lambda p: p["oos"]["avg_r"], 2, False),
        ("PF", lambda p: p["oos"]["pf"], 2, False),
        ("Ann ROR %", lambda p: p["oos"]["ann_ror"], 1, False),
        ("Max DD %", lambda p: p["oos"]["max_dd"], 2, False),
        ("Sheet PnL $", lambda p: p["oos"]["sheet"], 2, True),
    ]
    html_path = out_dir / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    summary = {
        "control_stamp": args.control_stamp,
        "short_stamp": short_stamp,
        "both_stamp": both_stamp,
        "verdict_short": v_short,
        "why_short": why_short,
        "verdict_both": v_both,
        "why_both": why_both,
        "overlap": overlap,
        "control": {k: ctrl[k] for k in ("full", "is", "oos")},
        "short": {k: short[k] for k in ("full", "is", "oos")},
        "both": {k: both[k] for k in ("full", "is", "oos")},
    }
    (out_dir / "short_side_ab_stats.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"short_verdict={v_short}")
    print(why_short)
    print(f"both_verdict={v_both}")
    print(why_both)
    print(f"html={html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
