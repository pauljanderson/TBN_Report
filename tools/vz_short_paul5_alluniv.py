#!/usr/bin/env python3
"""VZ short-only ALL universe + post-hoc Paul>=5 subset — research stamp.

1. Live short-only on full universe (ALL) — isolated -o; house pin unchanged.
2. Export Paul>=5 names from ALL short Summary → drive/universes/VZ_short_paul5_<stamp>.csv
3. Live short-only on Paul>=5 CSV — isolated -o.
4. Sortable compare HTML + BASELINE / AB_PLAN.

Selection honesty: Paul>=5 is post-hoc on ALL short book. Not house replace. Not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import subprocess
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import format_money, format_money_delta, overlay_ann_ror_max_dd, parse_number  # noqa: E402

DRIVE = ROOT / "drive"
STAMP_DIR = DRIVE / "paul_experiments" / "vz_short_paul5_alluniv_20260819"
ALL_DIR = STAMP_DIR / "live_all_short"
PAUL5_DIR = STAMP_DIR / "live_paul5_short"
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT = 500_000.0
EXIT_KEYS = ("TARGET", "STOP_LOSS", "GAP_UP", "GAP_DOWN", "TIME", "STOP")
PY = Path(r"C:\Users\songg\AppData\Local\Programs\Python\Python310\python.exe")


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


def read_stamp_from_dir(d: Path) -> str:
    for p in sorted(d.glob("VZ_last_run_ts.txt")) + sorted(d.glob("VZ_Closed_*.csv")):
        if p.name == "VZ_last_run_ts.txt":
            t = p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            if t:
                return t
        if p.name.startswith("VZ_Closed_"):
            return p.stem.replace("VZ_Closed_", "")
    raise FileNotFoundError(f"No stamp in {d}")


def find_closed(stamp: str, d: Path) -> Path:
    p = d / f"VZ_Closed_{stamp}.csv"
    if p.exists():
        return p
    hits = sorted(d.glob("VZ_Closed_*.csv"))
    if hits:
        return hits[-1]
    raise FileNotFoundError(f"VZ_Closed_{stamp}.csv not in {d}")


def find_summary(stamp: str, d: Path) -> Path:
    p = d / f"VZ_Summary_{stamp}.csv"
    if p.exists():
        return p
    hits = sorted(d.glob("VZ_Summary_*.csv"))
    if hits:
        return hits[-1]
    raise FileNotFoundError(f"VZ_Summary_{stamp}.csv not in {d}")


def find_summary_symbols(stamp: str, d: Path) -> Optional[Path]:
    p = d / f"VZ_Summary_Symbols_{stamp}.csv"
    return p if p.exists() else None


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
                    "side": _row_get(raw, "SIDE").upper() or "SHORT",
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
    rs = [t["r"] for t in trades if math.isfinite(t["r"])]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    cap = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT)
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
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "be": sum(1 for p in pnls if p == 0),
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
        "cap_days": float(cap["capital_days"] or 0.0),
        "ppc": (total_d / float(cap["capital_days"] or 0)) if cap.get("capital_days") else float("nan"),
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "wl_n": (len(wins) / len(losses)) if losses else float("nan"),
        "wl_d": (win_d / loss_d) if loss_d > 0 else float("nan"),
        "exp_pct": sum(pnls) / n,
        "exp_d": sheet / n,
        "tpy": tpy,
        "exits": dict(exits),
    }


def pack(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    is_t = [t for t in trades if t["opened"] < IS_CUT]
    oos_t = [t for t in trades if t["opened"] >= IS_CUT]
    return {
        "name": name,
        "full": book_stats(trades),
        "is": book_stats(is_t),
        "oos": book_stats(oos_t),
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
            f"IS quality not better vs ALL short (AvgPnL {cand['is']['avg_pnl']:.2f} vs "
            f"{ctrl['is']['avg_pnl']:.2f}; N {cand['is']['n']} vs {ctrl['is']['n']})."
        )
    if n_thin:
        return "HOLD", (
            f"IS quality up but N collapsed ({cand['is']['n']} vs {ctrl['is']['n']}, "
            f"{100 * n_frac:.0f}% retained). Post-hoc Paul cut — do not KEEP."
        )
    if oos_down:
        return "HOLD", (
            f"IS quality up (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}) "
            f"but OOS softened — do not retune."
        )
    if lift >= 0.50 and n_frac >= 0.70:
        return "LEAN KEEP", (
            f"IS quality up vs ALL short; OOS did not soften. Still post-hoc — research-only."
        )
    return "HOLD", (
        f"Modest IS lift (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}); "
        f"post-hoc Paul>=5 on short book. Research-only."
    )


def export_paul5_universe(summary_path: Path, stamp: str) -> tuple[Path, list[str], dict[str, Any]]:
    with summary_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys()) if rows else []
    truncated = "SHEET_PNL" not in cols and "AVG_TRADES_PER_YEAR" not in cols

    def paul(r: dict) -> float:
        return parse_number(r.get("PAUL_SCORE"))

    ge5 = [r for r in rows if (paul(r) or -1) >= 5]
    eq5 = [r for r in rows if paul(r) == 5]
    syms = sorted({(r.get("SYMBOL") or "").strip().upper() for r in ge5 if (r.get("SYMBOL") or "").strip()})

    out = DRIVE / "universes" / f"VZ_short_paul5_{stamp}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        f.write(f"# Post-hoc PAUL_SCORE>=5 from ALL short Summary {stamp}\n")
        f.write("# Truncated Summary ceiling=5 → >=5 == ==5 when truncated\n")
        f.write(f"# N={len(syms)} names. Research-only. Not house replace.\n")
        for s in syms:
            f.write(f"{s}\n")

    meta = {
        "n_summary": len(rows),
        "truncated": truncated,
        "n_ge5": len(ge5),
        "n_eq5": len(eq5),
        "n_syms": len(syms),
        "syms": syms,
    }
    return out, syms, meta


def run_paul5_short(univ_csv: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rel_out = out_dir.relative_to(ROOT).as_posix()
    rel_univ = univ_csv.relative_to(ROOT).as_posix()
    cmd = (
        f'set PY={PY}&& set VZ_TRADE_SIDE=short&& cd /d {ROOT} && '
        f'run_vz.bat {rel_univ} -o {rel_out}'
    )
    print(f"[run] {cmd}", flush=True)
    subprocess.run(cmd, shell=True, check=True)


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


def metrics_table_2arm(rows: list[tuple], packed: list[dict], split: str, title: str) -> str:
    head = sortable_th("Metric", "text")
    for p in packed:
        head += sortable_th(p["name"], "num")
    head += sortable_th("Δ Paul5 vs ALL", "num")
    body = ""
    for label, key, nd, money in rows:
        body += f"<tr><td>{html_mod.escape(label)}</td>"
        vals = [p[split][key] for p in packed]
        for v in vals:
            cell = format_money(v) if money else fmt_n(v, nd)
            body += f'<td class="num">{cell}</td>'
        body += f'<td class="num">{delta_cell(vals[1], vals[0], nd, money=money)}</td></tr>'
    return (
        f"<h3>{html_mod.escape(title)}</h3>"
        f"<p class='small'>Click column headers to sort.</p>"
        f"<table class='sortable'><caption>Click column headers to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def closed_rows() -> list[tuple]:
    keys = [
        ("Closed N", "n", 0, False),
        ("Win %", "wr", 1, False),
        ("Avg PnL %", "avg_pnl", 2, False),
        ("Book AVG_PNL_PCT_WO_MAX", "avg_wo_max", 2, False),
        ("AvgR", "avg_r", 2, False),
        ("Profit factor", "pf", 2, False),
        ("Ann ROR % (overlay $45k / $500k DD)", "ann_ror", 1, False),
        ("Max DD % (overlay $500k)", "max_dd", 2, False),
        ("Sheet PnL $", "sheet", 2, True),
        ("Avg days held", "avg_days", 1, False),
        ("Trades / year", "tpy", 2, False),
        ("Names traded", "syms", 0, False),
    ]
    return keys


def build_compare(
    all_stamp: str,
    paul5_stamp: str,
    paul_meta: dict[str, Any],
    univ_path: Path,
    out_dir: Path,
) -> Path:
    all_trades = load_trades(find_closed(all_stamp, ALL_DIR))
    paul5_trades = load_trades(find_closed(paul5_stamp, PAUL5_DIR))
    ctrl = pack(f"00_ALL short {all_stamp}", all_trades)
    cand = pack(f"01_Paul>=5 short {paul5_stamp}", paul5_trades)
    packed = [ctrl, cand]
    verdict, why = arm_verdict(ctrl, cand)

    ss_path = find_summary_symbols(all_stamp, ALL_DIR)
    ss_rows: list[dict] = []
    if ss_path:
        with ss_path.open(encoding="utf-8-sig", newline="") as f:
            ss_rows = list(csv.DictReader(f))
    ss_ge5 = [
        r
        for r in ss_rows
        if (parse_number(r.get("PAUL_SCORE")) or -1) >= 5
    ]
    ss_oos_ge5 = [
        r
        for r in ss_rows
        if (parse_number(r.get("PAUL_SCORE")) or -1) >= 5
        and (parse_number(r.get("PAUL_SCORE_OOS")) or -1) >= 5
    ]

    baseline = f"""# BASELINE — VZ short ALL + post-hoc Paul>=5 — vz_short_paul5_alluniv_20260819

**Research-only. Not gold. Not DailyRun. Do not replace `drive/universes/VZ_universe.csv`. House trade_side stays long.**

## Universe question

**Short VZ uses the same universe CSV / ALL token as long.** Only `vz_trade_side=short` changes signal direction (HL break-down mirror). Default DualPaul78 long house is unchanged.

## Freeze (both arms)

HL-only, first_retest_only, min_touches>=1, retest_eps_pct=0.005, lookback=126, retest_window=63,
entry_on=next_open, exit=EXIT_atr4_s025_r15, min_atr_pct=4.0, **vz_require_hvn_overlap=false**, **vz_trade_side=short**.

## Runs (isolated `-o`; `VZ_house_last_run_ts.txt` pin unchanged)

| Arm | Dir | Stamp | Universe |
|-----|-----|-------|----------|
| Control | `live_all_short` | `{all_stamp}` | ALL (~1110 requested) |
| Candidate | `live_paul5_short` | `{paul5_stamp}` | `{univ_path.name}` ({paul_meta['n_syms']} names) |

## Paul definition (selection honesty)

- **Cut source:** integer **`PAUL_SCORE >= 5`** on **`VZ_Summary_{all_stamp}.csv`** from the ALL short book.
- Summary rows (traded names only): **{paul_meta['n_summary']}**; truncated Summary (ceiling 5): **{paul_meta['truncated']}**.
- On truncated Summary, **>=5 == ==5** (max score 5). **{paul_meta['n_eq5']}** names at PAUL==5; exported **{paul_meta['n_syms']}**.
- **`PAUL_SCORE_OOS`** is **not** on Summary; on Summary_Symbols (0–8). SS with PAUL>=5: **{len(ss_ge5)}**; dual SS Paul>=5 **and** PAUL_OOS>=5: **{len(ss_oos_ge5)}**.
- This is a **post-hoc winner-cut on the ALL short book** — same selection-bias class as `vz_paul5_fulluniv_20260819` / DualPaul78 DISMISS stamps. **OOS report-only; do not retune.**

## Verdict vs ALL short control: **{verdict}**

{why}

Default remains **long** DualPaul78 HVN-off for house VZ.
"""
    (out_dir / "BASELINE.md").write_text(baseline, encoding="utf-8")
    (out_dir / "AB_PLAN.md").write_text(
        f"""# AB_PLAN — vz_short_paul5_alluniv_20260819

**Hypothesis:** After seeing ALL short Summary `{all_stamp}`, a Paul>=5 subset improves short-only quality vs ALL short.

**Control:** ALL short-only `{all_stamp}` (`live_all_short`).

**Candidate:** Paul>=5 short-only `{paul5_stamp}` on `{univ_path.name}` ({paul_meta['n_syms']} names).

**One knob:** universe (post-hoc Paul cut). Freeze: short side, HVN off, rw63, EXIT_atr4.

**OOS:** report-only. Do not retune. Do not wire DailyRun. Do not change default trade_side.

**Verdict:** {verdict} — {why}
""",
        encoding="utf-8",
    )

    sym_list = ", ".join(paul_meta["syms"][:40])
    if len(paul_meta["syms"]) > 40:
        sym_list += f", … (+{len(paul_meta['syms']) - 40} more)"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ short ALL vs Paul>=5 — 20260819</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1500px; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.12rem; margin-top: 28px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
.verdict {{ border: 2px solid #b45309; background: #fff7ed; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.84rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
th.sortable-th {{ cursor: pointer; user-select: none; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>VZ short-only: ALL vs post-hoc Paul>=5</h1>
<p class="sub">Same universe CSV as long — only <code>vz_trade_side=short</code> (break-down mirror).
House freeze HVN-off rw63 EXIT_atr4. IS = entry &lt; 2024-01-01. Research-only.</p>
<div class="card">
<p><strong>Universe:</strong> ALL short <code>{html_mod.escape(all_stamp)}</code> vs Paul>=5 short
<code>{html_mod.escape(paul5_stamp)}</code> ({paul_meta['n_syms']} names from
<code>{html_mod.escape(univ_path.name)}</code>).</p>
<p><strong>Paul cut:</strong> integer <code>PAUL_SCORE&gt;=5</code> on ALL short Summary
({paul_meta['n_summary']} traded rows; truncated={paul_meta['truncated']}).
8-pt SS PAUL&gt;=5: {len(ss_ge5)}; SS Paul&gt;=5 &amp; PAUL_OOS&gt;=5: {len(ss_oos_ge5)}.</p>
<p class="small">Tickers: {html_mod.escape(sym_list)}</p>
</div>
<div class="card verdict">
<h2>Paul>=5 short vs ALL short: {html_mod.escape(verdict)}</h2>
<p>{html_mod.escape(why)}</p>
<p>Post-hoc selection on ALL short book. Default trade_side stays <strong>long</strong>. Not DailyRun.</p>
</div>
<h2>IS / OOS headline (Closed overlay)</h2>
{metrics_table_2arm(closed_rows(), packed, "is", "IS (entry < 2024-01-01)")}
{metrics_table_2arm(closed_rows(), packed, "oos", "OOS (entry >= 2024-01-01, report-only)")}
{metrics_table_2arm(closed_rows(), packed, "full", "Full book")}
<p class="small">Sheet $45k; Max DD overlay on $500k seed. Canonical metrics per CANONICAL_COMPARE_METRICS.md.</p>
{SORT_JS}
</body>
</html>
"""
    html_path = out_dir / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    stats = {
        "all_stamp": all_stamp,
        "paul5_stamp": paul5_stamp,
        "paul_meta": paul_meta,
        "univ_csv": str(univ_path),
        "verdict": verdict,
        "why": why,
        "control": {k: ctrl[k] for k in ("full", "is", "oos")},
        "candidate": {k: cand[k] for k in ("full", "is", "oos")},
    }
    (out_dir / "short_paul5_stats.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    print(f"verdict={verdict}")
    print(why)
    print(f"html={html_path}")
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-only", action="store_true", help="Export Paul>=5 CSV from ALL short Summary")
    ap.add_argument("--run-paul5", action="store_true", help="Run Paul>=5 short after export")
    ap.add_argument("--compare-only", action="store_true", help="Build HTML from existing runs")
    ap.add_argument("--all-stamp", default="")
    ap.add_argument("--paul5-stamp", default="")
    args = ap.parse_args()

    STAMP_DIR.mkdir(parents=True, exist_ok=True)

    if args.compare_only:
        all_stamp = args.all_stamp or read_stamp_from_dir(ALL_DIR)
        paul5_stamp = args.paul5_stamp or read_stamp_from_dir(PAUL5_DIR)
        univ = DRIVE / "universes" / f"VZ_short_paul5_{all_stamp}.csv"
        syms = [ln.strip() for ln in univ.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
        meta = {"n_syms": len(syms), "syms": syms, "n_summary": 0, "truncated": True, "n_ge5": len(syms), "n_eq5": len(syms)}
        build_compare(all_stamp, paul5_stamp, meta, univ, STAMP_DIR)
        return 0

    all_stamp = args.all_stamp or read_stamp_from_dir(ALL_DIR)
    summary = find_summary(all_stamp, ALL_DIR)
    univ_path, syms, meta = export_paul5_universe(summary, all_stamp)
    print(f"exported {univ_path} N={len(syms)}")

    if args.export_only and not args.run_paul5:
        return 0

    run_paul5_short(univ_path, PAUL5_DIR)
    paul5_stamp = read_stamp_from_dir(PAUL5_DIR)
    build_compare(all_stamp, paul5_stamp, meta, univ_path, STAMP_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
