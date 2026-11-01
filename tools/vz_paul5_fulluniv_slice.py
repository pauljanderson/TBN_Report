"""Slice HVN-off ALL Closed onto post-hoc Paul==5 names from fulluniv Summary 260817214643.

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

OUT = ROOT / "drive" / "paul_experiments" / "vz_paul5_fulluniv_20260819"
SUMMARY = ROOT / "drive" / "VZ_Summary_260817214643.csv"
SUMMARY_SYM = ROOT / "drive" / "VZ_Summary_Symbols_260817214643.csv"
UNIV_DP = ROOT / "drive" / "universes" / "VZ_universe.csv"
UNIV_764 = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CLOSED_ALL = ROOT / "drive" / "VZ_Closed_260817214643.csv"
CLOSED_DP = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "vz_hvn_engine_ab_20260819"
    / "live_ctrl"
    / "VZ_Closed_260819140929.csv"
)

# User dump: "Paul-5 AEM" then names. AEM treated as candidate ticker.
USER_TYPED = [
    "AEM",
    "AEO",
    "AMKR",
    "AOUT",
    "APA",
    "ATI",
    "AU",
    "BC",
    "BELFA",
    "BYD",
    "CDE",
    "CRWD",
    "CVNA",
    "CZR",
    "DRD",
    "DY",
    "EHC",
    "FNV",
    "GGAL",
    "GHM",
    "GME",
    "HBM",
    "IESC",
    "JACK",
    "JMIA",
    "KGC",
    "LBRT",
    "LPG",
    "LSCC",
    "NBIX",
    "NEM",
    "NXPI",
    "NXST",
    "ONDS",
    "PAG",
    "PENN",
    "PLPC",
    "PRU",
    "RBLX",
    "SBH",
    "SCCO",
    "SENEA",
    "SKYW",
    "SMTOY",
    "STRL",
    "TGB",
    "TKO",
    "TOL",
    "TWLO",
    "UAN",
    "UUUU",
    "VFC",
    "WBD",
    "WCC",
    "WSM",
    "WYNN",
    "YETI",
    "ZM",
    "ZS",
]

# Sibling list: HVN-on 764 Summary 260819145708 PAUL_SCORE==5
PAUL5_764 = [
    "AEIS",
    "AEO",
    "AGX",
    "AMKR",
    "APA",
    "ATI",
    "AU",
    "AXP",
    "BC",
    "BYD",
    "DY",
    "EC",
    "EHC",
    "FNV",
    "GGAL",
    "HBM",
    "IESC",
    "JACK",
    "KGC",
    "LIN",
    "MOS",
    "NBIX",
    "NEM",
    "NXST",
    "PAG",
    "PENN",
    "PRU",
    "SBH",
    "SCCO",
    "SHW",
    "STRL",
    "STX",
    "TKO",
    "TOL",
    "VFC",
    "VNO",
    "WBD",
    "WCC",
    "WSM",
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
      bindSortHeader(table, col === 0 ? th : th, col);
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


def wo_max_avg(pnls: list[float]) -> float:
    if not pnls:
        return float("nan")
    if len(pnls) == 1:
        return pnls[0]
    mx = max(pnls)
    rest = [p for p in pnls if p != mx]
    if len(rest) == len(pnls):
        rest = pnls[:-1]
    return sum(rest) / len(rest) if rest else float("nan")


def stats(trades: list[dict]) -> dict:
    n = len(trades)
    empty = {
        "n": 0,
        "wr": float("nan"),
        "avg_pnl": float("nan"),
        "avg_pnl_wo_max": float("nan"),
        "avg_r": float("nan"),
        "pf": float("nan"),
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "sheet_pnl": 0.0,
        "avg_days": float("nan"),
        "expectancy_pct": float("nan"),
        "n_names": 0,
    }
    if n == 0:
        return empty
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
    days = [t["days"] for t in trades if t["days"] is not None]
    avg_days = sum(days) / len(days) if days else float("nan")
    return {
        "n": n,
        "wr": wr,
        "avg_pnl": avg_pnl,
        "avg_pnl_wo_max": wo_max_avg(pnls),
        "avg_r": avg_r,
        "pf": pf,
        "ann_ror": cap["ann_ror"],
        "max_dd": cap["max_dd"],
        "sheet_pnl": sheet,
        "avg_days": avg_days,
        "expectancy_pct": avg_pnl,
        "n_names": len({t["sym"] for t in trades}),
    }


def fmt_n(v, d=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if d == 0:
        return str(int(round(v)))
    return f"{v:.{d}f}"


def exit_mix(trades: list[dict]) -> Counter:
    c = Counter()
    for t in trades:
        e = t["exit"] or "UNKNOWN"
        c[e] += 1
    return c


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    user = list(dict.fromkeys(USER_TYPED))
    user_set = set(user)
    p5_764 = set(PAUL5_764)

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
    ge5_ss = [r for r in ss_rows if (paul(r) or -1) >= 5]
    dual_ss = [
        r
        for r in ss_rows
        if (paul(r) or -1) >= 7 and (paul_oos(r) or -1) >= 7
    ]
    dual_ss_syms = sorted((r.get("SYMBOL") or "").strip().upper() for r in dual_ss)

    eq5_syms = {(r.get("SYMBOL") or "").strip().upper() for r in eq5_sum}
    ge5_syms = {(r.get("SYMBOL") or "").strip().upper() for r in ge5_sum}
    eq5_ss_syms = {(r.get("SYMBOL") or "").strip().upper() for r in eq5_ss}

    ss_by = {(r.get("SYMBOL") or "").strip().upper(): r for r in ss_rows}
    sum_by = {(r.get("SYMBOL") or "").strip().upper(): r for r in sum_rows}

    in_summary = sorted(s for s in user if s in sum_by)
    in_ss = sorted(s for s in user if s in ss_by)
    missing_all = sorted(s for s in user if s not in sum_by and s not in ss_by)
    missing_sum = sorted(s for s in user if s not in sum_by)
    missing_ss = sorted(s for s in user if s not in ss_by)

    missing_vs_eq5 = sorted(user_set - eq5_syms)
    extra_eq5 = sorted(eq5_syms - user_set)

    # If AEM is the only extra/missing, call it out
    aem_sum_paul = paul(sum_by.get("AEM") or {})
    aem_ss_paul = paul(ss_by.get("AEM") or {})
    aem_ss_oos = paul_oos(ss_by.get("AEM") or {})

    oos_blank = []
    oos_ge7 = []
    oos_lt7 = []
    dual_like = []
    for s in user:
        r = ss_by.get(s)
        if not r:
            oos_blank.append((s, None, "missing_ss"))
            continue
        po = paul_oos(r)
        ps = paul(r)
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
    overlap_dp = sorted(user_set & dp)
    only_paul5 = sorted(user_set - dp)
    only_dp = sorted(dp - user_set)
    in_764 = sorted(user_set & u764)
    not_764 = sorted(user_set - u764)
    overlap_39 = sorted(user_set & p5_764)
    only_full = sorted(user_set - p5_764)
    only_39 = sorted(p5_764 - user_set)

    closed_all = load_closed(CLOSED_ALL)
    closed_dp_live = load_closed(CLOSED_DP)

    def slice_syms(closed, names):
        want = set(names)
        return [t for t in closed if t["sym"] in want]

    # Primary: ALL HVN-off Closed sliced to user list (validated names in Closed or list)
    books = {
        "Paul5 fulluniv slice (ALL HVN-off 260817214643)": slice_syms(closed_all, user_set),
        "Paul5==5 Summary exact (ALL HVN-off)": slice_syms(closed_all, eq5_syms),
        "DualPaul78 slice of ALL Closed": slice_syms(closed_all, dp),
        "ALL HVN-off (260817214643)": closed_all,
        "DualPaul78 live HVN-off (260819140929)": closed_dp_live,
    }

    metric_rows = []
    for name, trades in books.items():
        sp = split_book(trades)
        for split, tr in sp.items():
            st = stats(tr)
            metric_rows.append({"book": name, "split": split.upper(), **st})

    hist = Counter(int(paul(r)) if paul(r) is not None else -99 for r in sum_rows)
    hist_ss = Counter(int(paul(r)) if paul(r) is not None else -99 for r in ss_rows)
    hist_ss_oos = Counter()
    for r in ss_rows:
        po = paul_oos(r)
        hist_ss_oos[int(po) if po is not None else -99] += 1

    # Exit mix on primary Paul5 slice OOS/IS
    p5_trades = slice_syms(closed_all, user_set)
    p5_split = split_book(p5_trades)
    mix_full = exit_mix(p5_split["full"])
    mix_oos = exit_mix(p5_split["oos"])

    n_user = len(user)
    n_eq5 = len(eq5_sum)
    ss_paul_hist_user = Counter()
    for s in user:
        r = ss_by.get(s) or {}
        v = paul(r)
        ss_paul_hist_user[int(v) if v is not None else -99] += 1
    user_ss_eq5 = [s for s in user if paul(ss_by.get(s) or {}) == 5]
    user_ss_ge6 = [s for s in user if (paul(ss_by.get(s) or {}) or -1) >= 6]
    user_ss_6 = [s for s in user if paul(ss_by.get(s) or {}) == 6]

    baseline = f"""# BASELINE — post-hoc Paul==5 sleeve from fulluniv ALL Summary — vz_paul5_fulluniv_20260819

**Do not use as the VZ universe. Do not replace `drive/universes/VZ_universe.csv`. Not gold. Not DailyRun.**

## What the user saw

Source: `drive/VZ_Summary_260817214643.csv` (`run_vz.bat ALL`, **1110** requested, HVN-**off**, freeze `EXIT_atr4_s025_r15` / rw63). Stamp folder: `drive/paul_experiments/vz_run_260817214643/`.

- Summary rows: **{n_sum}** (traded names on ALL; not 1110 — names with no trades omitted)
- Summary_Symbols rows: **{n_ss}** (~1110 universe including no-trade rows)
- Integer **PAUL_SCORE == 5** on Summary: **{n_eq5}**
- PAUL_SCORE **≥ 5** on Summary: **{len(ge5_sum)}** (truncated file: ceiling **5**, so ≥5 == ==5)
- Truncated Paul on `VZ_Summary_*`: **{truncated_paul}** (no SHEET_PNL / AVG_TRADES_PER_YEAR). Score 5 is **top-of-file**, not DualPaul “middling 5/8”.
- `PAUL_SCORE_OOS` is **not** on Summary; it is on Summary_Symbols (0–8)
- Summary_Symbols PAUL_SCORE == 5: **{len(eq5_ss)}**; ≥5: **{len(ge5_ss)}**
- Dual Paul 7–8 **on this ALL stamp** (SS PAUL≥7 **and** PAUL_OOS≥7): **{len(dual_ss)}** names — this is how DualPaul78 was originally cut (fulluniv), not this Paul-5 list

User typed **{n_user}** tokens (AEM included as ticker). Vs Summary PAUL==5 (the 55-name top bin): in both **{n_user - len(missing_vs_eq5)}**; user-not-in-bin **{len(missing_vs_eq5)}**; bin-not-in-user **{len(extra_eq5)}**. **Not an exact dump of the 55.**

On 8-pt Summary_Symbols, **zero** typed names have PAUL_SCORE==5 (SS==5 n=69, ∩ user = {len(user_ss_eq5)}). Typed SS Paul histogram: {dict(ss_paul_hist_user)} (≥6: {len(user_ss_ge6)}; ==6: {len(user_ss_6)}: {', '.join(user_ss_6) or 'none'}). “Paul-5” here is the **truncated Summary ceiling**, Dual-like 7–8 on SS for only **{len(dual_like)}** of {n_user}.

AEM on this stamp: Summary PAUL={aem_sum_paul}; SS PAUL={aem_ss_paul}; PAUL_SCORE_OOS={aem_ss_oos}. In DualPaul78: **{'Y' if 'AEM' in dp else 'N'}**.

Missing from Summary (typos / no trades): {missing_sum or 'none'}.
Missing from Summary_Symbols: {missing_ss or 'none'}. Completely absent: {missing_all or 'none'}.

## PAUL_SCORE_OOS on the typed list

- Blank / missing OOS Paul: **{len(oos_blank)}**
- PAUL_SCORE_OOS ≥ 7: **{len(oos_ge7)}**
- PAUL_SCORE_OOS < 7: **{len(oos_lt7)}**
- Dual-like (SS Paul ≥7 **and** OOS ≥7): **{len(dual_like)}** — Paul 5 is **not** DualPaul

## Overlap

- DualPaul78 (`VZ_universe.csv`): **{len(dp)}** names
- Paul5 ∩ DualPaul78: **{len(overlap_dp)}** ({', '.join(overlap_dp) if overlap_dp else 'none'})
- Paul5 not in DualPaul78: **{len(only_paul5)}**
- DualPaul78 not in Paul5: **{len(only_dp)}**
- Tradable 764 ∩ Paul5: **{len(in_764)}**; not in 764: {not_764 or 'none'}
- ∩ HVN-on 764 Paul5 (39 names): **{len(overlap_39)}**
- Fulluniv-only vs 39: **{len(only_full)}**; 39-only: **{len(only_39)}** ({', '.join(only_39) if only_39 else 'none'})

## Closed slice (primary = ALL HVN-off `260817214643`)

Capital: sheet $45,000; Max DD $500k seed. IS = entry < 2024-01-01. Overlay slice ≠ concurrent-position house equity.

See `compare.html`.

## Selection honesty

Post-hoc integer Paul==5 on the **fulluniv Summary the user already saw** is an **in-sample winner-cut**. Weaker than DualPaul78 (Paul **7–8 both** IS and OOS). Same class as `vz_is_paul78_20260818` **DISMISS**. OOS is report-only — do not retune.

## Verdict: **No** (research-only / do not adopt)

Keep house VZ = DualPaul78 HVN-**off**. Do not replace `VZ_universe.csv`. Even if overlay OOS looks decent, HOLD research-only — this cut was chosen after seeing ALL Summary.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")
    (OUT / "AB_PLAN.md").write_text(
        """# AB_PLAN — vz_paul5_fulluniv_20260819 (research-only)

**Hypothesis (universe, not exit):** After seeing ALL HVN-off Summary `260817214643`, use typed “Paul-5” names as house VZ universe instead of DualPaul78.

**Control:** DualPaul78 `drive/universes/VZ_universe.csv` (Paul ≥7 **and** PAUL_SCORE_OOS ≥7 on fulluniv). HVN off. Exit `EXIT_atr4_s025_r15` / rw63. Same Closed overlay `VZ_Closed_260817214643.csv`.

**Candidate:** User typed list (59 names, AEM included). Post-hoc truncated-Summary top bin / mixed dump — **in-sample winner-cut**. Weaker than Dual 7–8 both. Same class as `vz_is_paul78_20260818` DISMISS.

**OOS:** report-only. Do not retune. Do not replace `VZ_universe.csv`.

**Judge:** quality (WR, Avg PnL%, AvgR, PF, Max DD, sheet PnL), not trade count. KEEP only if OOS is shockingly robust vs Dual **and** even then HOLD research-only.

**Verdict:** No.
""",
        encoding="utf-8",
    )

    def td_num(v, d=2):
        return f'<td class="num">{fmt_n(v, d)}</td>'

    metric_head = "".join(
        sortable_th(lab, typ)
        for lab, typ in [
            ("Book", "text"),
            ("Split", "text"),
            ("Names", "num"),
            ("N", "num"),
            ("Win %", "num"),
            ("Avg PnL %", "num"),
            ("WO_MAX Avg PnL %", "num"),
            ("Avg R", "num"),
            ("PF", "num"),
            ("Avg days", "num"),
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
            f"{td_num(m['n_names'], 0)}"
            f"{td_num(m['n'], 0)}"
            f"{td_num(m['wr'], 1)}"
            f"{td_num(m['avg_pnl'], 2)}"
            f"{td_num(m['avg_pnl_wo_max'], 2)}"
            f"{td_num(m['avg_r'], 2)}"
            f"{td_num(m['pf'], 2)}"
            f"{td_num(m['avg_days'], 1)}"
            f"{td_num(m['ann_ror'], 1)}"
            f"{td_num(m['max_dd'], 2)}"
            f'<td class="num">{format_money(m["sheet_pnl"])}</td>'
            "</tr>"
        )

    name_head = "".join(
        sortable_th(lab, typ)
        for lab, typ in [
            ("SYMBOL", "text"),
            ("In Summary", "text"),
            ("Summary PAUL (ceiling 5)", "num"),
            ("SS PAUL_SCORE (0–8)", "num"),
            ("PAUL_SCORE_OOS", "num"),
            ("In DualPaul78", "text"),
            ("In 764", "text"),
            ("In 39 HVN-on", "text"),
            ("OOS_TRADES", "num"),
            ("IS_AVG_PNL_PCT", "num"),
            ("OOS_AVG_PNL_PCT", "num"),
        ]
    )
    name_body = []
    for s in user:
        r = ss_by.get(s, {})
        sr = sum_by.get(s, {})
        po = paul_oos(r) if r else None
        po_s = "—" if po is None else fmt_n(po, 0)
        name_body.append(
            "<tr>"
            f"<td>{escape(s)}</td>"
            f"<td>{'Y' if s in sum_by else 'N'}</td>"
            f"{td_num(paul(sr) if sr else None, 0)}"
            f"{td_num(paul(r) if r else None, 0)}"
            f'<td class="num">{po_s}</td>'
            f"<td>{'Y' if s in dp else 'N'}</td>"
            f"<td>{'Y' if s in u764 else 'N'}</td>"
            f"<td>{'Y' if s in p5_764 else 'N'}</td>"
            f"{td_num(parse_number(r.get('OOS_TRADES')) if r else None, 0)}"
            f"{td_num(parse_number(r.get('IS_AVG_PNL_PCT')) if r else None, 2)}"
            f"{td_num(parse_number(r.get('OOS_AVG_PNL_PCT')) if r else None, 2)}"
            "</tr>"
        )

    hist_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist[k], 0)}</tr>'
        for k in sorted(hist)
    )
    hist_ss_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist_ss[k], 0)}</tr>'
        for k in sorted(hist_ss)
    )
    oos_hist_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist_ss_oos[k], 0)}</tr>'
        for k in sorted(hist_ss_oos)
    )

    mix_keys = sorted(set(mix_full) | set(mix_oos))
    mix_body = []
    n_full = max(len(p5_split["full"]), 1)
    n_oos = max(len(p5_split["oos"]), 1)
    for k in mix_keys:
        cf, co = mix_full[k], mix_oos[k]
        mix_body.append(
            "<tr>"
            f"<td>{escape(k)}</td>"
            f"{td_num(cf, 0)}"
            f"{td_num(100.0 * cf / n_full, 1)}"
            f"{td_num(co, 0)}"
            f"{td_num(100.0 * co / n_oos, 1)}"
            "</tr>"
        )

    # Pull OOS rows for headline
    def find_m(book, split):
        for m in metric_rows:
            if m["book"] == book and m["split"] == split:
                return m
        return None

    m_p5_oos = find_m("Paul5 fulluniv slice (ALL HVN-off 260817214643)", "OOS")
    m_dp_oos = find_m("DualPaul78 slice of ALL Closed", "OOS")
    m_all_oos = find_m("ALL HVN-off (260817214643)", "OOS")
    m_p5_is = find_m("Paul5 fulluniv slice (ALL HVN-off 260817214643)", "IS")
    m_dp_is = find_m("DualPaul78 slice of ALL Closed", "IS")

    oos_shock = False
    if m_p5_oos and m_dp_oos:
        # "shockingly robust" = beat Dual on WR and Avg PnL and not worse DD
        oos_shock = (
            (m_p5_oos["wr"] or 0) >= (m_dp_oos["wr"] or 0)
            and (m_p5_oos["avg_pnl"] or -999) >= (m_dp_oos["avg_pnl"] or 0)
            and (m_p5_oos["n"] or 0) >= 80
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ Paul==5 fulluniv post-hoc slice — 20260819</title>
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
<h1>Should fulluniv Paul==5 ({n_user} names, AEM included) be the VZ universe?</h1>
<p class="sub"><strong>No.</strong> Post-hoc integer <code>PAUL_SCORE==5</code> on ALL Summary
<code>260817214643</code> (~{n_sum} traded / 1110 requested). Not DualPaul78. Not gold. Not DailyRun.
Click column headers to sort.</p>
<div class="card verdict">
<h2>Verdict: No — do not replace DualPaul78</h2>
<p>Winner-cut after seeing fulluniv Summary. Weaker class than Dual Paul 7–8 <strong>both</strong>
PAUL_SCORE and PAUL_SCORE_OOS. Same class as IS-only Paul 7–8 <strong>DISMISS</strong>
(<code>vz_is_paul78_20260818</code>). House stays DualPaul78 HVN-off.
<code>VZ_universe.csv</code> was not edited. OOS shockingly-robust vs Dual: <strong>{'yes' if oos_shock else 'no'}</strong>
— even then this would be HOLD research-only, not a house replace.</p>
</div>
<div class="card">
<p><strong>Source stamp:</strong> <code>VZ_Summary_260817214643.csv</code> ALL HVN-off
(1110 requested; Summary {n_sum} traded rows; SS {n_ss}). Truncated Summary PAUL==5 = {n_eq5}
(== ≥5; ceiling 5). Typed list ∩ that bin = {n_user - len(missing_vs_eq5)} / {n_user};
{len(missing_vs_eq5)} typed names are <em>not</em> Summary==5; {len(extra_eq5)} Summary==5 names were omitted.
<strong>8-pt SS PAUL==5 ∩ list = {len(user_ss_eq5)}</strong> — they did not mean middling 5/8.</p>
<p><strong>AEM:</strong> treated as ticker. Summary PAUL={fmt_n(aem_sum_paul,0)}; SS PAUL={fmt_n(aem_ss_paul,0)};
OOS Paul={fmt_n(aem_ss_oos,0)}; DualPaul78={'Y' if 'AEM' in dp else 'N'}.</p>
<p><strong>OOS Paul on typed list:</strong> blank {len(oos_blank)}; ≥7 {len(oos_ge7)}; &lt;7 {len(oos_lt7)}.
Dual-like (SS≥7 and OOS≥7): {len(dual_like)} ({escape(', '.join(dual_like) or 'none')}).
ALL-stamp Dual 7–8 both: {len(dual_ss)} (house DualPaul78 is 83, not this Paul-5 cut).</p>
<p><strong>Overlap DualPaul78:</strong> {len(overlap_dp)} / {n_user}
({escape(', '.join(overlap_dp) if overlap_dp else 'none')}).
Not in Dual: {len(only_paul5)}. ∩ tradable 764: {len(in_764)}. ∩ HVN-on 39: {len(overlap_39)}.
Absent / likely typo: {escape(', '.join(missing_all) if missing_all else 'none')}.</p>
</div>
<h2>Closed overlay IS / OOS (canonical quality)</h2>
<p class="small">Primary = ALL HVN-off Closed <code>260817214643</code> sliced to the typed list.
DualPaul78 slice uses the same Closed (fair). Live Dual <code>260819140929</code> is the house HVN-off book.
Sheet $45k; Max DD on $500k seed. Overlay ≠ concurrent house equity. Click headers to sort.</p>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{metric_head}</tr></thead>
<tbody>
{''.join(metric_body)}
</tbody>
</table>
<p class="small">Headline OOS Avg PnL%: Paul5 slice {fmt_n(m_p5_oos['avg_pnl'] if m_p5_oos else None, 2)}
vs Dual slice {fmt_n(m_dp_oos['avg_pnl'] if m_dp_oos else None, 2)}
vs ALL {fmt_n(m_all_oos['avg_pnl'] if m_all_oos else None, 2)}.
IS Avg PnL%: Paul5 {fmt_n(m_p5_is['avg_pnl'] if m_p5_is else None, 2)} vs Dual {fmt_n(m_dp_is['avg_pnl'] if m_dp_is else None, 2)}
(IS looks better — expected after picking Summary winners).</p>
<h2>Exit mix (Paul5 slice of ALL Closed)</h2>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{sortable_th('EXIT_TYPE','text')}{sortable_th('FULL N','num')}{sortable_th('FULL %','num')}{sortable_th('OOS N','num')}{sortable_th('OOS %','num')}</tr></thead>
<tbody>{''.join(mix_body)}</tbody>
</table>
<h2>Typed names — Paul IS / OOS</h2>
<table class="sortable">
<caption>Click column headers to sort. PAUL_SCORE_OOS blank = no OOS trades on ALL book.</caption>
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
<p class="small">See BASELINE.md. DualPaul78 remains the research default. IS-Paul78 was DISMISS because OOS collapsed vs Dual.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    print("SUMMARY_ROWS", n_sum, "SS_ROWS", n_ss)
    print("TRUNCATED", truncated_paul, "SUM_HIST", dict(hist))
    print("PAUL==5", len(eq5_sum), "PAUL>=5", len(ge5_sum))
    print("USER_N", n_user, "IN_SUMMARY", len(in_summary), "IN_SS", len(in_ss))
    print("MISSING_VS_EQ5", missing_vs_eq5)
    print("EXTRA_EQ5", extra_eq5)
    print("MISSING_ALL", missing_all)
    print("AEM", aem_sum_paul, aem_ss_paul, aem_ss_oos, "AEM_IN_DP", "AEM" in dp)
    print("OOS_BLANK", len(oos_blank), oos_blank)
    print("OOS_GE7", len(oos_ge7))
    print("OOS_LT7", len(oos_lt7))
    print("DUAL_LIKE", dual_like)
    print("STAMP_DUAL78", len(dual_ss))
    print("OVERLAP_DP", len(overlap_dp), overlap_dp)
    print("PAUL5_ONLY_N", len(only_paul5))
    print("IN_764", len(in_764), "NOT_764", not_764)
    print("OVERLAP_39", len(overlap_39), overlap_39)
    print("ONLY_FULL_VS_39_N", len(only_full), "ONLY_39", only_39)
    print("OOS_SHOCK", oos_shock)
    for m in metric_rows:
        print(
            f"{m['book']}|{m['split']}|names={m['n_names']}|N={m['n']}|"
            f"WR={fmt_n(m['wr'],1)}|Avg={fmt_n(m['avg_pnl'],2)}|"
            f"WOMAX={fmt_n(m['avg_pnl_wo_max'],2)}|R={fmt_n(m['avg_r'],2)}|"
            f"PF={fmt_n(m['pf'],2)}|Ann={fmt_n(m['ann_ror'],1)}|DD={fmt_n(m['max_dd'],2)}|"
            f"Sheet={m['sheet_pnl']:.2f}"
        )
    print("WROTE", html_path)


if __name__ == "__main__":
    main()
