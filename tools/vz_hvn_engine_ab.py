#!/usr/bin/env python3
"""Compare DualPaul78 VZ control vs engine HVN-on Closed books.

Control: house freeze stamp (default 260817212836), HVN off.
Candidate: live run_vz with vz_require_hvn_overlap=true.

Research-only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments" / "vz_hvn_engine_ab_20260819"
CONTROL_STAMP = "260817212836"
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT = 500_000.0


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


def load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE_OPENED"))
            if opened is None:
                continue
            pnl = _f(_row_get(raw, "PNL_PCT", "PNL %"), 0.0)
            rows.append(
                {
                    "sym": _row_get(raw, "SYMBOL").upper(),
                    "opened": opened,
                    "closed": _parse_d(_row_get(raw, "DATE_CLOSED")),
                    "pnl": pnl,
                    "r": _f(_row_get(raw, "R_MULT"), 0.0),
                    "days": _f(_row_get(raw, "DAYS_HELD"), 0.0),
                    "pnl_d": _f(_row_get(raw, "PNL_DOLLARS"), 0.0),
                    "exit": _row_get(raw, "EXIT_TYPE"),
                }
            )
    return rows


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
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
    rs = [t["r"] for t in trades if math.isfinite(t["r"])]
    cap = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT)
    return {
        "n": n,
        "wins": len(wins),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": (sum(rs) / len(rs)) if rs else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * SHEET for p in pnls),
        "avg_days": sum(t["days"] for t in trades) / n,
        "syms": len({t["sym"] for t in trades if t["sym"]}),
        "avg_wo_max": wo,
        "ann_ror": cap["ann_ror"],
        "max_dd": cap["max_dd"],
        "cap_days": cap["capital_days"],
        "equity_note": cap["note"],
    }


def pack(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    is_t = [t for t in trades if t["opened"] < IS_CUT]
    oos_t = [t for t in trades if t["opened"] >= IS_CUT]
    return {"name": name, "full": book_stats(trades), "is": book_stats(is_t), "oos": book_stats(oos_t)}


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
        return "HOLD", (
            "IS Ann ROR fell and Max DD worsened vs control — downgrade KEEP to HOLD."
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
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, idx) {
      th.addEventListener("click", function () {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        table.querySelectorAll("th.sortable-th").forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        sortTable(table, idx, type, asc ? "asc" : "desc");
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
    d = cand - ctrl
    if money:
        return format_money_delta(d)
    if not (math.isfinite(cand) and math.isfinite(ctrl)):
        return "—"
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.{nd}f}"


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
        f"<p class='small'>Click column headers to sort.</p>"
        f"<table class='sortable'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def find_closed(stamp: str) -> Path:
    cands = [
        DRIVE / f"VZ_Closed_{stamp}.csv",
        OUT_DIR / "cand_out" / f"VZ_Closed_{stamp}.csv",
        OUT_DIR / f"VZ_Closed_{stamp}.csv",
    ]
    for p in cands:
        if p.is_file():
            return p
    raise SystemExit(f"missing Closed for stamp {stamp}: tried {cands}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control-stamp", default=CONTROL_STAMP)
    ap.add_argument("--cand-stamp", required=True)
    args = ap.parse_args()
    ctrl_path = find_closed(args.control_stamp)
    cand_path = find_closed(args.cand_stamp)
    ctrl = pack(f"control HVN-off {args.control_stamp}", load_trades(ctrl_path))
    cand = pack(f"HVN-on engine {args.cand_stamp}", load_trades(cand_path))
    verdict, why = arm_verdict(ctrl, cand)
    packed = [ctrl, cand]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ HVN engine AB — DualPaul78 — 20260819</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1400px; }}
h1 {{ font-size: 1.35rem; }}
.sub, .small {{ color: #555; }}
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
</style>
</head>
<body>
<h1>VZ HVN engine A/B — DualPaul78</h1>
<p class="sub"><strong>Engine one-knob</strong> (not Closed overlay). Control = house freeze
<code>{html_mod.escape(args.control_stamp)}</code> HVN off.
Candidate = <code>vz_require_hvn_overlap=true</code> stamp
<code>{html_mod.escape(args.cand_stamp)}</code>. Same universe, EXIT_atr4, next_open.
<strong>Not gold. Not DailyRun.</strong> Click column headers to sort.</p>
<div class="card">
<p>Gate: zone ∩ HVN/POC at <strong>signal_idx</strong> (60d VP, 0.5% typical-price bins, HVN ≥ 50% of POC).
Missing profile drops. <code>first_retest_only</code> consumes a failed first retest (overlay-equivalent).
Default flag remains <strong>false</strong>.</p>
<p>IS = entry &lt; 2024-01-01 (KEEP/HOLD/DISMISS). OOS report-only — soften → HOLD, do not retune.
DualPaul78 is a Paul 7–8 winner-cut sleeve (survivor bias).</p>
</div>
<div class="card"><strong>Verdict: {html_mod.escape(verdict)}</strong> — {html_mod.escape(why)}</div>
{metrics_table(packed, "is", "IS (entry &lt; 2024-01-01)")}
{metrics_table(packed, "oos", "OOS (entry ≥ 2024-01-01, report-only)")}
{metrics_table(packed, "full", "Full book")}
<p class="small">Ann ROR = rocket_tbn book formula at sheet $45,000. Max DD = peak-to-trough on
PNL_DOLLARS by DATE_CLOSED seeded at $500,000. Overlay KEEP on 260817212836 is not this table.</p>
{SORT_JS}
</body>
</html>
"""
    html_path = OUT_DIR / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    summary = {
        "control_stamp": args.control_stamp,
        "cand_stamp": args.cand_stamp,
        "verdict": verdict,
        "why": why,
        "control": {k: ctrl[k] for k in ("full", "is", "oos")},
        "candidate": {k: cand[k] for k in ("full", "is", "oos")},
    }
    (OUT_DIR / "engine_ab_stats.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"verdict={verdict}")
    print(why)
    print(f"html={html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
