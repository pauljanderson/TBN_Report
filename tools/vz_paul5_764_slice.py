"""Slice HVN-off 764 Closed onto post-hoc Paul==5 names from HVN-on Summary 260819145708.

Research-only. Does not replace VZ_universe.csv. Not DailyRun.
"""
from __future__ import annotations

import csv
import math
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    format_money,
    overlay_ann_ror_max_dd,
    parse_number,
)

OUT = ROOT / "drive" / "paul_experiments" / "vz_paul5_764_slice_20260819"
SUMMARY = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "vz_hvn_tradable764_20260819"
    / "live_cand"
    / "VZ_Summary_260819145708.csv"
)
SUMMARY_SYM = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "vz_hvn_tradable764_20260819"
    / "live_cand"
    / "VZ_Summary_Symbols_260819145708.csv"
)
UNIV_DP = ROOT / "drive" / "universes" / "VZ_universe.csv"
UNIV_764 = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CLOSED_HVN_OFF = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "vz_hvn_tradable764_20260819"
    / "live_ctrl"
    / "VZ_Closed_260818232232.csv"
)
CLOSED_HVN_ON = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "vz_hvn_tradable764_20260819"
    / "live_cand"
    / "VZ_Closed_260819145708.csv"
)
CLOSED_DP = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "vz_hvn_engine_ab_20260819"
    / "live_ctrl"
    / "VZ_Closed_260819140929.csv"
)

USER_LIST = [
    "AEIS", "AEO", "AGX", "AMKR", "APA", "ATI", "AU", "AXP", "BC", "BYD",
    "DY", "EC", "EHC", "FNV", "GGAL", "HBM", "IESC", "JACK", "KGC", "LIN",
    "MOS", "NBIX", "NEM", "NXST", "PAG", "PENN", "PRU", "SBH", "SCCO", "SHW",
    "STRL", "STX", "TKO", "TOL", "VFC", "VNO", "WBD", "WCC", "WSM",
]
HOLD_CUT = datetime(2024, 1, 1)
SHEET = 45_000.0
INITIAL = 500_000.0

SORTABLE_TH_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""
SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
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
        f'role="columnheader" aria-sort="none">{escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def load_syms(path: Path) -> list[str]:
    out = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    for row in csv.DictReader(lines):
        s = (row.get("SYMBOL") or "").strip().upper()
        if s:
            out.append(s)
    return out


def parse_dt(s: str):
    s = (s or "").strip()
    if not s:
        return None
    digits = s.replace("-", "")[:8]
    if len(digits) == 8 and digits.isdigit():
        return datetime.strptime(digits, "%Y%m%d")
    return None


def load_closed(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            opened = parse_dt(r.get("DATE_OPENED") or "")
            closed = parse_dt(r.get("DATE_CLOSED") or "")
            pnl = parse_number(r.get("PNL_PCT"))
            pnl_d = parse_number(r.get("PNL_DOLLARS"))
            days = parse_number(r.get("DAYS_HELD"))
            r_mult = parse_number(r.get("R_MULT"))
            rows.append(
                {
                    "sym": (r.get("SYMBOL") or "").strip().upper(),
                    "opened": opened,
                    "closed": closed,
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "days": days,
                    "r": r_mult,
                    "exit": (r.get("EXIT_TYPE") or "").strip(),
                }
            )
    return rows


def split_book(trades: list[dict]) -> dict[str, list[dict]]:
    is_, oos, full = [], [], []
    for t in trades:
        if t["opened"] is None:
            continue
        full.append(t)
        if t["opened"] < HOLD_CUT:
            is_.append(t)
        else:
            oos.append(t)
    return {"is": is_, "oos": oos, "full": full}


def stats(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "n": 0,
            "wr": float("nan"),
            "avg_pnl": float("nan"),
            "avg_r": float("nan"),
            "pf": float("nan"),
            "ann_ror": float("nan"),
            "max_dd": float("nan"),
            "sheet_pnl": 0.0,
        }
    pnls = [t["pnl"] for t in trades if t["pnl"] is not None]
    wins = sum(1 for p in pnls if p > 0)
    wr = 100.0 * wins / n if n else float("nan")
    avg_pnl = sum(pnls) / len(pnls) if pnls else float("nan")
    rs = [t["r"] for t in trades if t["r"] is not None]
    avg_r = sum(rs) / len(rs) if rs else float("nan")
    pos = sum(t["pnl_d"] or 0.0 for t in trades if (t["pnl_d"] or 0) > 0)
    neg = abs(sum(t["pnl_d"] or 0.0 for t in trades if (t["pnl_d"] or 0) < 0))
    pf = pos / neg if neg > 0 else (pos if pos > 0 else float("nan"))
    cap = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INITIAL)
    sheet = sum((t["pnl"] or 0.0) / 100.0 * SHEET for t in trades)
    return {
        "n": n,
        "wr": wr,
        "avg_pnl": avg_pnl,
        "avg_r": avg_r,
        "pf": pf,
        "ann_ror": cap["ann_ror"],
        "max_dd": cap["max_dd"],
        "sheet_pnl": sheet,
    }


def fmt_n(v, d=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if d == 0:
        return str(int(round(v)))
    return f"{v:.{d}f}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    user = set(USER_LIST)

    with SUMMARY.open(encoding="utf-8-sig", newline="") as f:
        sum_rows = list(csv.DictReader(f))
    with SUMMARY_SYM.open(encoding="utf-8-sig", newline="") as f:
        ss_rows = list(csv.DictReader(f))

    def paul(r):
        return parse_number(r.get("PAUL_SCORE"))

    def paul_oos(r):
        return parse_number(r.get("PAUL_SCORE_OOS"))

    n_sum = len(sum_rows)
    n_ss = len(ss_rows)
    sum_cols = list(sum_rows[0].keys()) if sum_rows else []
    truncated_paul = "SHEET_PNL" not in sum_cols and "AVG_TRADES_PER_YEAR" not in sum_cols
    eq5_sum = [r for r in sum_rows if paul(r) == 5]
    ge5_sum = [r for r in sum_rows if (paul(r) or -1) >= 5]
    eq5_ss = [r for r in ss_rows if paul(r) == 5]
    dual_ss = [
        r
        for r in ss_rows
        if (paul(r) or -1) >= 7 and (paul_oos(r) or -1) >= 7
    ]
    dual_ss_syms = sorted((r.get("SYMBOL") or "").strip().upper() for r in dual_ss)

    eq5_syms = {(r.get("SYMBOL") or "").strip().upper() for r in eq5_sum}
    ge5_syms = {(r.get("SYMBOL") or "").strip().upper() for r in ge5_sum}
    eq5_ss_syms = {(r.get("SYMBOL") or "").strip().upper() for r in eq5_ss}

    missing_user = sorted(user - eq5_syms)
    extra_eq5 = sorted(eq5_syms - user)

    ss_by = {(r.get("SYMBOL") or "").strip().upper(): r for r in ss_rows}
    sum_by = {(r.get("SYMBOL") or "").strip().upper(): r for r in sum_rows}
    oos_vals = []
    oos_blank = []
    dual_like = []
    oos_ge7 = []
    oos_lt7 = []
    for s in USER_LIST:
        r = ss_by.get(s)
        if not r:
            oos_blank.append((s, None, "missing"))
            continue
        po = paul_oos(r)
        ps = paul(r)
        oos_vals.append((s, ps, po))
        if po is None:
            oos_blank.append((s, ps, "blank_oos"))
        elif po >= 7:
            oos_ge7.append((s, ps, po))
        else:
            oos_lt7.append((s, ps, po))
        if (ps or -1) >= 7 and (po or -1) >= 7:
            dual_like.append(s)

    dp = set(load_syms(UNIV_DP))
    u764 = set(load_syms(UNIV_764))
    overlap_dp = sorted(user & dp)
    only_paul5 = sorted(user - dp)
    only_dp = sorted(dp - user)
    in_764 = sorted(user & u764)
    not_764 = sorted(user - u764)

    closed_off = load_closed(CLOSED_HVN_OFF)
    closed_on = load_closed(CLOSED_HVN_ON)
    closed_dp = load_closed(CLOSED_DP)

    def slice_syms(closed, names):
        want = set(names)
        return [t for t in closed if t["sym"] in want]

    books = {
        "Paul5 HVN-off 764 slice (260818232232)": slice_syms(closed_off, user),
        "Paul5 HVN-on 764 slice (260819145708)": slice_syms(closed_on, user),
        "Full 764 HVN-off (260818232232)": closed_off,
        "DualPaul78 HVN-off house (260819140929)": closed_dp,
    }

    metric_rows = []
    for name, trades in books.items():
        sp = split_book(trades)
        for split, tr in sp.items():
            st = stats(tr)
            metric_rows.append({"book": name, "split": split.upper(), **st})

    # PAUL_SCORE histogram on Summary
    hist = Counter(int(paul(r)) if paul(r) is not None else -99 for r in sum_rows)
    hist_ss = Counter(int(paul(r)) if paul(r) is not None else -99 for r in ss_rows)
    hist_ss_oos = Counter()
    for r in ss_rows:
        po = paul_oos(r)
        hist_ss_oos[int(po) if po is not None else -99] += 1

    # Write BASELINE
    baseline = f"""# BASELINE — post-hoc Paul==5 sleeve from HVN-on 764 Summary — vz_paul5_764_slice_20260819

**Do not use as the VZ universe. Do not replace `drive/universes/VZ_universe.csv`. Not gold. Not DailyRun.**

## What the user saw

File: `vz_hvn_tradable764_20260819/live_cand/VZ_Summary_260819145708.csv` (HVN-**on** live 764).

- Summary rows: **{n_sum}**
- Integer **PAUL_SCORE == 5**: **{len(eq5_sum)}** (matches the 39-name list)
- PAUL_SCORE **≥ 5**: **{len(ge5_sum)}** (same 39 — **5 is the ceiling** on this file)
- Truncated Paul on `VZ_Summary_*`: columns lack SHEET_PNL and AVG_TRADES_PER_YEAR (and PCT_WINS is WIN_RATE_PCT), so house 0–8 Paul can only fire ~5 components. **Score 5 here is top-of-file, not DualPaul “middling 5/8”.**
- `PAUL_SCORE_OOS` is **not** on `VZ_Summary_*`; it is on `VZ_Summary_Symbols_*` ({n_ss} rows; full 0–8)
- Summary_Symbols PAUL_SCORE == 5: **{len(eq5_ss)}** (different set; SS==5 ≠ Summary==5)
- Dual Paul 7–8 on **this** HVN-on Summary_Symbols (PAUL≥7 **and** PAUL_OOS≥7): **{len(dual_ss)}** names ({', '.join(dual_ss_syms) if dual_ss_syms else 'none'}) — still post-hoc on a HOLD stamp; not DualPaul78 house

User list vs Summary PAUL_SCORE==5: missing={missing_user or 'none'}; extra={extra_eq5 or 'none'}.

## PAUL_SCORE_OOS on the 39

- Blank / missing OOS Paul: **{len(oos_blank)}** (no OOS trades → DualPaul78 would **fail**)
- PAUL_SCORE_OOS ≥ 7: **{len(oos_ge7)}**
- PAUL_SCORE_OOS < 7 (incl. 0–6): **{len(oos_lt7)}**
- Dual-like on this stamp (IS Paul ≥7 **and** OOS ≥7): **{len(dual_like)}** — Paul 5 is **not** DualPaul

## Overlap

- DualPaul78 (`VZ_universe.csv`): **{len(dp)}** names
- Tradable 764: **{len(u764)}** names
- Paul5 ∩ DualPaul78: **{len(overlap_dp)}** / 39 ({', '.join(overlap_dp) if overlap_dp else 'none'})
- Paul5 only (not DualPaul78): **{len(only_paul5)}**
- DualPaul78 not in Paul5: **{len(only_dp)}**
- Paul5 ∩ 764: **{len(in_764)}** / 39; not in 764 file: {not_764 or 'none'}

## Closed slice (primary = HVN-off 764 control)

Capital: sheet $45,000; Max DD $500k seed. IS = entry < 2024-01-01. Overlay slice ≠ concurrent-position house equity.

See `compare.html`.

## Verdict: **No** (research-only / do not adopt)

The 39 were taken from an HVN-**on** HOLD stamp after seeing Summary = **two knobs** (universe + HVN) + **post-hoc winner-cut**. Same class as IS-only Paul 7–8 **DISMISS**. DualPaul78 is Paul 7–8 on **both** IS and OOS from fulluniv (winner-cut sleeve already); a truncated-Summary top bin on 764 HVN-on does not replace it. DualPaul78 survivor bias is not fixed by a different Paul cut on 764.

On the 8-pt Summary_Symbols score for these 39: only **{len(dual_like)}** pass Dual-like (≥7 and OOS≥7); **{len(oos_blank)}** have blank OOS Paul; **{len(oos_lt7)}** have OOS Paul <7. HVN-off Closed slice OOS quality is **worse** than DualPaul78 house (WR / Avg PnL% / Max DD) even though IS looks better — expected after picking winners.

HVN engine A/B was HOLD on DualPaul78 and HOLD on 764. House VZ stays DualPaul78 HVN-**off**.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    def td_num(v, d=2):
        return f'<td class="num">{fmt_n(v, d)}</td>'

    metric_head = "".join(
        sortable_th(lab, typ)
        for lab, typ in [
            ("Book", "text"),
            ("Split", "text"),
            ("N", "num"),
            ("Win %", "num"),
            ("Avg PnL %", "num"),
            ("Avg R", "num"),
            ("PF", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Sheet PnL $", "num"),
        ]
    )
    metric_body = []
    for m in metric_rows:
        metric_body.append(
            "<tr>"
            f"<td>{escape(m['book'])}</td>"
            f"<td>{escape(m['split'])}</td>"
            f"{td_num(m['n'], 0)}"
            f"{td_num(m['wr'], 1)}"
            f"{td_num(m['avg_pnl'], 2)}"
            f"{td_num(m['avg_r'], 2)}"
            f"{td_num(m['pf'], 2)}"
            f"{td_num(m['ann_ror'], 1)}"
            f"{td_num(m['max_dd'], 2)}"
            f'<td class="num">{format_money(m["sheet_pnl"])}</td>'
            "</tr>"
        )

    name_head = "".join(
        sortable_th(lab, typ)
        for lab, typ in [
            ("SYMBOL", "text"),
            ("Summary PAUL (file ceiling 5)", "num"),
            ("SS PAUL_SCORE (0–8)", "num"),
            ("PAUL_SCORE_OOS", "num"),
            ("In DualPaul78", "text"),
            ("OOS_TRADES", "num"),
            ("IS_AVG_PNL_PCT", "num"),
            ("OOS_AVG_PNL_PCT", "num"),
        ]
    )
    name_body = []
    for s in USER_LIST:
        r = ss_by.get(s, {})
        sr = sum_by.get(s, {})
        po = paul_oos(r)
        po_s = "—" if po is None else fmt_n(po, 0)
        name_body.append(
            "<tr>"
            f"<td>{escape(s)}</td>"
            f"{td_num(paul(sr), 0)}"
            f"{td_num(paul(r), 0)}"
            f'<td class="num">{po_s}</td>'
            f"<td>{'Y' if s in dp else 'N'}</td>"
            f"{td_num(parse_number(r.get('OOS_TRADES')), 0)}"
            f"{td_num(parse_number(r.get('IS_AVG_PNL_PCT')), 2)}"
            f"{td_num(parse_number(r.get('OOS_AVG_PNL_PCT')), 2)}"
            "</tr>"
        )

    hist_rows = "".join(
        f"<tr><td class=\"num\">{k if k != -99 else 'blank'}</td>{td_num(hist[k], 0)}</tr>"
        for k in sorted(hist)
    )
    hist_ss_rows = "".join(
        f"<tr><td class=\"num\">{k if k != -99 else 'blank'}</td>{td_num(hist_ss[k], 0)}</tr>"
        for k in sorted(hist_ss)
    )
    oos_hist_rows = "".join(
        f"<tr><td class=\"num\">{k if k != -99 else 'blank'}</td>{td_num(hist_ss_oos[k], 0)}</tr>"
        for k in sorted(hist_ss_oos)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ Paul==5 764 post-hoc slice — 20260819</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1400px; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.12rem; margin-top: 28px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
.verdict {{ border: 2px solid #991b1b; background: #fef2f2; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.84rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
table.sortable caption {{ text-align: left; color: #555; padding: 4px 0; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
{SORTABLE_TH_CSS}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Should Paul==5 (39 names) be the VZ universe?</h1>
<p class="sub"><strong>No.</strong> Post-hoc integer <code>PAUL_SCORE==5</code> on HVN-on 764 Summary
<code>260819145708</code>. Not DualPaul78. Not gold. Not DailyRun. Click column headers to sort.</p>
<div class="card verdict">
<h2>Verdict: No — do not replace DualPaul78</h2>
<p>Cut taken after seeing HVN-on HOLD Summary = two knobs (universe + HVN) + winner-cut.
Same class as IS-only Paul 7–8 DISMISS. DualPaul78 survivor bias is not fixed by this sleeve.
<code>VZ_Summary</code> Paul 5 is the <strong>ceiling</strong> of a truncated 5-component score, not DualPaul middling 5/8.
On 8-pt Summary_Symbols, only {len(dual_like)} of 39 are Dual-like (IS≥7 and OOS≥7).
HVN stays off. Keep <code>VZ_universe.csv</code>.</p>
</div>
<div class="card">
<p><strong>How they got 39:</strong> <code>VZ_Summary_260819145708.csv</code> has {n_sum} rows;
integer PAUL_SCORE==5 = {len(eq5_sum)}; ≥5 = {len(ge5_sum)} (truncated Paul, ceiling 5;
truncated={truncated_paul}). OOS Paul is not on Summary — only on Summary_Symbols ({n_ss} rows).
List matches ==5 exactly.</p>
<p><strong>OOS Paul on the 39 (Summary_Symbols):</strong> blank {len(oos_blank)}; ≥7 {len(oos_ge7)}; &lt;7 {len(oos_lt7)}.
Dual-like among the 39: {len(dual_like)} ({escape(', '.join(dual_like) or 'none')}).
This stamp Dual 7–8 both: {len(dual_ss)} names (not the house 83).</p>
<p><strong>Overlap:</strong> DualPaul78 n={len(dp)}; ∩ Paul5 = {len(overlap_dp)}
({escape(', '.join(overlap_dp) if overlap_dp else 'none')}).
Paul5 not in DualPaul78: {len(only_paul5)}. In 764 file: {len(in_764)} / 39.</p>
</div>
<h2>Closed overlay IS / OOS</h2>
<p class="small">Primary sleeve for “should this be house universe” is <strong>HVN-off</strong>
<code>260818232232</code> sliced to the 39. HVN-on slice is labeled. DualPaul78 is live HVN-off
<code>260819140929</code> (house freeze; pin in AB was 260817212836, N matched). Sheet $45k; Max DD $500k seed.</p>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{metric_head}</tr></thead>
<tbody>
{''.join(metric_body)}
</tbody>
</table>
<h2>The 39 names — Paul IS / OOS</h2>
<table class="sortable">
<caption>Click column headers to sort. PAUL_SCORE_OOS blank = no OOS trades on this HVN-on book.</caption>
<thead><tr>{name_head}</tr></thead>
<tbody>
{''.join(name_body)}
</tbody>
</table>
<h2>PAUL_SCORE histogram (Summary {n_sum} rows — truncated, max 5)</h2>
<table class="sortable"><thead><tr>{sortable_th('PAUL_SCORE','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist_rows}</tbody></table>
<h2>PAUL_SCORE histogram (Summary_Symbols {n_ss} rows — 0–8)</h2>
<table class="sortable"><thead><tr>{sortable_th('PAUL_SCORE','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist_ss_rows}</tbody></table>
<h2>PAUL_SCORE_OOS histogram (Summary_Symbols {n_ss} rows)</h2>
<table class="sortable"><thead><tr>{sortable_th('PAUL_SCORE_OOS','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{oos_hist_rows}</tbody></table>
<p class="small">See BASELINE.md. HVN engine A/B HOLD DualPaul78 and HOLD 764.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    print("SUMMARY_ROWS", n_sum)
    print("PAUL==5", len(eq5_sum), sorted(eq5_syms))
    print("PAUL>=5", len(ge5_sum))
    print("SS_ROWS", n_ss, "SS_PAUL==5", len(eq5_ss))
    print("DUAL_ON_THIS_STAMP", len(dual_ss), dual_ss_syms)
    print("TRUNCATED", truncated_paul, "SUM_HIST", dict(hist))
    print("SS_PAUL==5", len(eq5_ss), "SS_HIST", dict(hist_ss))
    print("MISSING_USER", missing_user)
    print("OOS_BLANK", len(oos_blank), oos_blank)
    print("OOS_GE7", len(oos_ge7), oos_ge7)
    print("OOS_LT7", len(oos_lt7), oos_lt7)
    print("DUAL_LIKE_IN_39", dual_like)
    print("OVERLAP_DP", len(overlap_dp), overlap_dp)
    print("PAUL5_ONLY", len(only_paul5), only_paul5)
    print("DP_N", len(dp), "U764", len(u764), "IN_764", len(in_764))
    for m in metric_rows:
        print(
            f"{m['book']}|{m['split']}|N={m['n']}|WR={fmt_n(m['wr'],1)}|"
            f"Avg={fmt_n(m['avg_pnl'],2)}|Ann={fmt_n(m['ann_ror'],1)}|DD={fmt_n(m['max_dd'],2)}"
        )
    print("WROTE", html_path)


if __name__ == "__main__":
    main()
