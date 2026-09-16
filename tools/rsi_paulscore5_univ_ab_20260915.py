#!/usr/bin/env python3
"""RSI universe A/B: house 149 vs Paul Score >=5 IS-only list (N=81).

Same freeze (ob70 / max_trigger60 / atr5 / ts20 / next_open).
Control = latest house pin (149 HighFIT/ISgood).
Candidate = RSIN_PaulScore5_IS_20260915.csv live run.
IS/OOS. OOS report-only. Not gold. Does not flip DailyRun.
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)

STAMP = "rsi_paulscore5_univ_ab_20260915"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
DRIVE = REPO / "drive"
IS_CUT = date(2024, 1, 1)
SHEET = 10_000.0
INIT = DEFAULT_INITIAL_ACCOUNT
CTRL_TS = (DRIVE / "RSI_house_last_run_ts.txt").read_text(encoding="utf-8").strip().splitlines()[0]
CAND_TS = "260915093927"
UNIV = REPO / "drive" / "universes" / "RSIN_PaulScore5_IS_20260915.csv"

ORIGINAL_REQUEST = (
    "let's try this universe for RSI\n"
    + "\n".join(
        ln.strip()
        for ln in UNIV.read_text(encoding="utf-8").splitlines()
        if ln.strip() and ln.strip().lower() != "symbol"
    )
    + "\n\nthese are the stocks that scored 5 or greater in the paul score using only the IS sample"
)

PLAIN_ENGLISH = (
    "Relative Strength Index (RSI) is the same buy/sell rule as DailyRun "
    "(cool-off from hot, trigger RSI under 60, Average True Range percent at "
    "least 5, sell at 70 or day 20). You asked to replay it on the 81 names "
    "whose Paul Score was 5 or higher when we only looked at trades that "
    "opened before 2024. That list was picked on the in-sample book, so it "
    "is allowed to look great before 2024 — the honest check is 2024 and "
    "after. We did not change DailyRun’s 149-name house list."
)

SORTABLE_TH_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""
SORTABLE_TABLE_SCRIPT = """
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
    rows.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      th.addEventListener("click", function () {
        var type = th.dataset.sort || "text";
        var dir = th.dataset.dir === "asc" ? -1 : 1;
        table.querySelectorAll("th.sortable-th").forEach(function (h) {
          h.dataset.dir = ""; h.classList.remove("sort-asc", "sort-desc");
        });
        th.dataset.dir = dir === 1 ? "asc" : "desc";
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        sortTable(table, col, type, dir);
      });
    });
  });
})();
"""


def sortable_th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(typ)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _parse_date(raw: Any) -> Optional[date]:
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt != "%Y%m%d" else s[:8], fmt).date()
        except ValueError:
            continue
    return None


def _parse_num(raw: Any) -> Optional[float]:
    s = str(raw or "").strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "n/a", "—", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_closed(ts: str) -> list[dict[str, Any]]:
    path = DRIVE / f"RSI_Closed_{ts}.csv"
    out = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = _parse_date(raw.get("DATE_OPENED"))
            pnl = _parse_num(raw.get("PNL_PCT"))
            if opened is None or pnl is None:
                continue
            days = _parse_num(raw.get("DAYS_HELD")) or 0.0
            out.append(
                {
                    "symbol": str(raw.get("SYMBOL") or "").strip(),
                    "opened": opened,
                    "closed": _parse_date(raw.get("DATE_CLOSED")),
                    "pnl": pnl,
                    "days": days,
                    "exit": str(raw.get("EXIT_TYPE") or "").strip().upper(),
                }
            )
    return out


def slc(rows: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [r for r in rows if r["opened"] < IS_CUT]
    if which == "OOS":
        return [r for r in rows if r["opened"] >= IS_CUT]
    return list(rows)


def pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    empty = {"n": 0}
    if not n:
        return empty
    wins = sum(1 for r in rows if r["pnl"] > 0)
    losses = sum(1 for r in rows if r["pnl"] < 0)
    pcts = [r["pnl"] for r in rows]
    avg = sum(pcts) / n
    wo = sorted(pcts)
    avg_wo = (sum(wo[:-1]) / (n - 1)) if n > 1 else avg
    w = [p for p in pcts if p > 0]
    l = [p for p in pcts if p < 0]
    days = [r["days"] for r in rows if r["days"] > 0]
    overlay = [
        {
            "pnl": r["pnl"],
            "pnl_d": r["pnl"] / 100.0 * SHEET,
            "days": r["days"],
            "closed": r["closed"],
            "opened": r["opened"],
        }
        for r in rows
    ]
    ov = overlay_ann_ror_max_dd(overlay, cash=SHEET, initial_account=INIT)
    pnls_d = [r["pnl"] / 100.0 * SHEET for r in rows]
    sw = sum(x for x in pnls_d if x > 0)
    sl_ = abs(sum(x for x in pnls_d if x < 0))
    pf = (sw / sl_) if sl_ > 0 else sw
    cap = ov.get("capital_days") or sum(days)
    total = float(ov.get("pnl_d") or sum(pnls_d))
    exits = Counter(r["exit"] or "?" for r in rows)
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_pct": 100.0 * wins / n,
        "avg_pnl_pct": avg,
        "avg_wo_max": avg_wo,
        "avg_win_pct": (sum(w) / len(w)) if w else 0.0,
        "avg_loss_pct": (sum(l) / len(l)) if l else 0.0,
        "expectancy_pct": avg,
        "pf": pf,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "median_days": sorted(days)[len(days) // 2] if days else 0.0,
        "p90_days": sorted(days)[int(0.9 * (len(days) - 1))] if days else 0.0,
        "capital_days": cap,
        "profit_per_cap_day": (total / cap) if cap else 0.0,
        "exits": dict(exits),
        "n_syms": len({r["symbol"] for r in rows}),
    }


def _fmt_pct(v: Any) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):.2f}%"


def _fmt_num(v: Any, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):,.{d}f}"


def note_full(ctrl: dict, cand: dict, oos_ctrl: dict, oos_cand: dict) -> str:
    """IS-selected univ: OOS softening → HOLD. Do not KEEP from FULL/IS lift."""
    d_avg = float(cand["avg_pnl_pct"]) - float(ctrl["avg_pnl_pct"])
    d_oos = float(oos_cand["avg_pnl_pct"]) - float(oos_ctrl["avg_pnl_pct"])
    if d_oos <= -1.0:
        return "HOLD (OOS softened vs house — do not adopt an IS-selected list)"
    if d_avg <= -0.4:
        return "DISMISS (FULL quality vs house — IS-selected list)"
    if d_avg >= 0.3:
        return "LEAN KEEP (research) — still IS-selected; see OOS"
    return "HOLD"


def row_html(name: str, knob: str, st: dict, ctrl: dict, sl: str, full_note: str = "") -> str:
    d_avg = float(st["avg_pnl_pct"]) - float(ctrl["avg_pnl_pct"])
    d_dd = float(st["max_dd"]) - float(ctrl["max_dd"])
    if sl == "OOS":
        note = "report-only"
    elif sl == "FULL" and name != "CONTROL":
        note = full_note
    else:
        note = ""
    cells = [
        name,
        knob,
        f"{st['n']:,}",
        str(st.get("n_syms") or ""),
        _fmt_pct(st["win_pct"]),
        _fmt_pct(st["avg_pnl_pct"]),
        _fmt_pct(st["avg_wo_max"]),
        _fmt_pct(st["expectancy_pct"]),
        _fmt_pct(st["avg_win_pct"]),
        _fmt_pct(st["avg_loss_pct"]),
        _fmt_num(st["pf"]),
        _fmt_pct(st["ann_ror"]),
        _fmt_pct(st["max_dd"]),
        _fmt_num(st["calmar"]),
        _fmt_num(st["sharpe"]),
        _fmt_num(st["avg_days"], 1),
        _fmt_num(st["median_days"], 1),
        _fmt_num(st["p90_days"], 1),
        _fmt_num(st["capital_days"], 0),
        format_money(st["profit_per_cap_day"]),
        _fmt_pct(d_avg),
        _fmt_pct(d_dd),
        note,
    ]
    return "<tr>" + "".join(f"<td>{html_mod.escape(str(c))}</td>" for c in cells) + "</tr>"


def table_html(ctrl_rows: list, cand_rows: list, sl: str, full_note: str = "") -> str:
    ctrl = pack(ctrl_rows)
    cand = pack(cand_rows)
    headers = [
        ("Arm", "text"),
        ("Knob", "text"),
        ("N", "num"),
        ("Names", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Expectancy %", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("PF", "num"),
        ("Ann ROR %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Avg days", "num"),
        ("Median days", "num"),
        ("P90 days", "num"),
        ("Capital days", "num"),
        ("Profit / cap day", "num"),
        ("Δ Avg PnL % vs ctrl", "num"),
        ("Δ Max DD vs ctrl", "num"),
        ("Note", "text"),
    ]
    th = "".join(sortable_th(h, t) for h, t in headers)
    title = {
        "IS": "IS (entry &lt; 2024-01-01) — list was picked here",
        "OOS": "OOS (entry ≥ 2024-01-01) — report-only",
        "FULL": "FULL (all history)",
    }[sl]
    return (
        f"<h3>{title}</h3>"
        f'<p class="meta">Click column headers to sort. Sheet $ omitted. '
        f"Overlay $10k/fill on $500k seed.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>'
        f"{row_html('CONTROL', 'universe', ctrl, ctrl, sl, full_note)}"
        f"{row_html('UNIV_paulscore5_IS', 'universe', cand, ctrl, sl, full_note)}"
        f"</tbody></table>"
    )


def main() -> int:
    ctrl_all = load_closed(CTRL_TS)
    cand_all = load_closed(CAND_TS)
    packs = {
        sl: (pack(slc(ctrl_all, sl)), pack(slc(cand_all, sl)))
        for sl in ("IS", "OOS", "FULL")
    }
    c_full, a_full = packs["FULL"]
    c_oos, a_oos = packs["OOS"]
    c_is, a_is = packs["IS"]
    full_note = note_full(c_full, a_full, c_oos, a_oos)
    oos_avg = float(a_oos["avg_pnl_pct"]) - float(c_oos["avg_pnl_pct"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = f"""# BASELINE — {STAMP}

**Status:** Research universe A/B. **Not gold. Not DailyRun.** OOS report-only.

## What you asked

> let's try this universe for RSI
> (81 names with Paul Score ≥ 5 on the IS sample only)

## In plain English

{PLAIN_ENGLISH}

## Honesty

- One knob: universe. Freeze unchanged (RSI 70/60/atr5/ts20/next_open).
- The 81 names were selected on **IS Paul Score ≥ 5** — in-sample selection.
- OOS is report-only. Do not retune the list on OOS.
- DailyRun house stays `drive/universes/rsi_universe.csv` (149).

## Control vs candidate

| Arm | Universe | Stamp | Names |
|-----|----------|-------|-------|
| CONTROL | rsi_universe.csv (HighFIT/ISgood 149) | {CTRL_TS} | 149 |
| UNIV_paulscore5_IS | RSIN_PaulScore5_IS_20260915.csv | {CAND_TS} | 81 |

### CONTROL
- **IS** N={c_is['n']} WR={c_is['win_pct']:.2f}% Avg%={c_is['avg_pnl_pct']:.2f} MaxDD={c_is['max_dd']:.2f}
- **OOS** N={c_oos['n']} WR={c_oos['win_pct']:.2f}% Avg%={c_oos['avg_pnl_pct']:.2f} MaxDD={c_oos['max_dd']:.2f}
- **FULL** N={c_full['n']} WR={c_full['win_pct']:.2f}% Avg%={c_full['avg_pnl_pct']:.2f} MaxDD={c_full['max_dd']:.2f}

### UNIV_paulscore5_IS
- **IS** N={a_is['n']} WR={a_is['win_pct']:.2f}% Avg%={a_is['avg_pnl_pct']:.2f} MaxDD={a_is['max_dd']:.2f}
- **OOS** N={a_oos['n']} WR={a_oos['win_pct']:.2f}% Avg%={a_oos['avg_pnl_pct']:.2f} MaxDD={a_oos['max_dd']:.2f}
- **FULL** N={a_full['n']} WR={a_full['win_pct']:.2f}% Avg%={a_full['avg_pnl_pct']:.2f} MaxDD={a_full['max_dd']:.2f}

- **FULL note:** {full_note}
- **OOS Δ Avg%:** {oos_avg:+.2f} (report-only)
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP}</title>
<style>
{SORTABLE_TH_CSS}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 78rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; }}
table.sortable th {{ background: #f1f5f9; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }}
.caveat {{ color: #9a3412; font-size: .9rem; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }}
</style></head><body>
<h1>RSI universe — house 149 vs Paul Score ≥5 IS (81)</h1>
<p class="badge">Research only · not gold · not DailyRun · OOS report-only · universe A/B</p>
<p class="meta">Stamp <code>{STAMP}</code> · 2026-09-15 · click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">let's try this universe for RSI … these are the stocks that scored 5 or greater in the paul score using only the IS sample</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="insight">
<p><strong>FULL note:</strong> {html_mod.escape(full_note)}</p>
<p class="caveat"><strong>Selection honesty:</strong> The 81 names were chosen because Paul Score was ≥5 on
the in-sample (pre-2024) book. That can inflate IS. OOS is the check; we did not retune the list
on 2024+. House DailyRun list is still 149 names.</p>
<p class="meta">Control stamp <code>{CTRL_TS}</code> · Candidate <code>{CAND_TS}</code> ·
CSV <code>drive/universes/RSIN_PaulScore5_IS_20260915.csv</code></p>
</div>
<h2>Book compare (same RSI freeze)</h2>
{table_html(slc(ctrl_all, "IS"), slc(cand_all, "IS"), "IS")}
{table_html(slc(ctrl_all, "OOS"), slc(cand_all, "OOS"), "OOS")}
{table_html(slc(ctrl_all, "FULL"), slc(cand_all, "FULL"), "FULL", full_note)}
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>
"""
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {"ctrl_ts": CTRL_TS, "cand_ts": CAND_TS, "slices": {
                k: {"control": v[0], "candidate": v[1]} for k, v in packs.items()
            }, "full_note": full_note},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[rsi univ] wrote {OUT_DIR / 'compare.html'}")
    print(f"  CONTROL {CTRL_TS} FULL N={c_full['n']} Avg%={c_full['avg_pnl_pct']:.2f} OOS Avg%={c_oos['avg_pnl_pct']:.2f}")
    print(f"  CAND    {CAND_TS} FULL N={a_full['n']} Avg%={a_full['avg_pnl_pct']:.2f} OOS Avg%={a_oos['avg_pnl_pct']:.2f}")
    print(f"  note {full_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
