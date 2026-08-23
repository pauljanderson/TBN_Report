"""Slice HVN-on ALL Closed 260819151232 onto post-hoc Paul==5 names.

Correction vs vz_paul5_fulluniv_20260819: the paste was this stamp (fulluniv HVN ON),
not ALL HVN-off 260817214643.

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

OUT = ROOT / "drive" / "paul_experiments" / "vz_paul5_hvn_all_20260819"
OLD_FULLUNIV = ROOT / "drive" / "paul_experiments" / "vz_paul5_fulluniv_20260819"
SUMMARY = ROOT / "drive" / "VZ_Summary_260819151232.csv"
SUMMARY_SYM = ROOT / "drive" / "VZ_Summary_Symbols_260819151232.csv"
UNIV_DP = ROOT / "drive" / "universes" / "VZ_universe.csv"
UNIV_764 = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CLOSED_HVN_ON = ROOT / "drive" / "VZ_Closed_260819151232.csv"
CLOSED_ALL_HVN_OFF = ROOT / "drive" / "VZ_Closed_260819150528.csv"  # same-day ALL HVN-off
CLOSED_ALL_HVN_OFF_OLD = ROOT / "drive" / "VZ_Closed_260817214643.csv"
CLOSED_DP_LIVE = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "vz_hvn_engine_ab_20260819"
    / "live_ctrl"
    / "VZ_Closed_260819140929.csv"
)
CLOSED_DP_HOUSE = ROOT / "drive" / "VZ_Closed_260817212836.csv"

# User dump from HVN-on ALL Summary 260819151232 PAUL_SCORE==5 (exact 59).
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
        "avg_win": float("nan"),
        "avg_loss": float("nan"),
        "trades_per_year": float("nan"),
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades if t["pnl"] is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = 100.0 * len(wins) / n if n else float("nan")
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
    opened = [t["opened"] for t in trades if t["opened"] is not None]
    tpy = float("nan")
    if len(opened) >= 2:
        span = (max(opened) - min(opened)).days / 365.25
        if span > 0:
            tpy = n / span
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
        "avg_win": sum(wins) / len(wins) if wins else float("nan"),
        "avg_loss": sum(losses) / len(losses) if losses else float("nan"),
        "trades_per_year": tpy,
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


def patch_old_fulluniv_banner() -> None:
    html_path = OLD_FULLUNIV / "compare.html"
    if not html_path.exists():
        return
    txt = html_path.read_text(encoding="utf-8")
    banner = (
        '<div class="card" style="border:2px solid #92400e;background:#fffbeb;">'
        "<h2>Correction (2026-08-19)</h2>"
        "<p>The Paul-5 paste was <strong>not</strong> ALL HVN-off "
        "<code>260817214643</code>. It was fulluniv HVN-<strong>on</strong> "
        "<code>VZ_Summary_260819151232</code> "
        "(<code>vz_require_hvn_overlap=true</code>, 1110 names). "
        "This folder used the wrong stamp. See "
        "<a href=\"../vz_paul5_hvn_all_20260819/compare.html\">"
        "vz_paul5_hvn_all_20260819/compare.html</a>. "
        "Universe recommendation remains <strong>No</strong> "
        "(do not replace DualPaul78 / <code>VZ_universe.csv</code>).</p>"
        "</div>\n"
    )
    if "Correction (2026-08-19)" in txt:
        return
    needle = "<body>\n"
    if needle in txt:
        html_path.write_text(txt.replace(needle, needle + banner, 1), encoding="utf-8")
    md = OLD_FULLUNIV / "BASELINE.md"
    if md.exists():
        old = md.read_text(encoding="utf-8")
        note = (
            "\n\n## Correction (2026-08-19)\n\n"
            "The paste was **not** this ALL HVN-off stamp. Source was HVN-on "
            "fulluniv `260819151232`. See `../vz_paul5_hvn_all_20260819/`. "
            "Verdict still **No**.\n"
        )
        if "Correction (2026-08-19)" not in old:
            md.write_text(old + note, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    user = list(dict.fromkeys(USER_TYPED))
    user_set = set(user)

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
    eq5_ss_syms = {(r.get("SYMBOL") or "").strip().upper() for r in eq5_ss}

    ss_by = {(r.get("SYMBOL") or "").strip().upper(): r for r in ss_rows}
    sum_by = {(r.get("SYMBOL") or "").strip().upper(): r for r in sum_rows}

    missing_all = sorted(s for s in user if s not in sum_by and s not in ss_by)
    missing_sum = sorted(s for s in user if s not in sum_by)
    missing_ss = sorted(s for s in user if s not in ss_by)
    missing_vs_eq5 = sorted(user_set - eq5_syms)
    extra_eq5 = sorted(eq5_syms - user_set)
    exact_eq5 = not missing_vs_eq5 and not extra_eq5 and len(user) == len(eq5_syms)

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

    closed_hvn_on = load_closed(CLOSED_HVN_ON)
    closed_all_off = load_closed(CLOSED_ALL_HVN_OFF)
    closed_all_off_old = load_closed(CLOSED_ALL_HVN_OFF_OLD)
    closed_dp_live = load_closed(CLOSED_DP_LIVE)
    closed_dp_house = load_closed(CLOSED_DP_HOUSE)

    def slice_syms(closed, names):
        want = set(names)
        return [t for t in closed if t["sym"] in want]

    books = {
        "Paul5 HVN-on slice (260819151232)": slice_syms(closed_hvn_on, user_set),
        "DualPaul78 live HVN-off (260819140929)": closed_dp_live,
        "DualPaul78 house HVN-off (260817212836)": closed_dp_house,
        "DualPaul78 slice of HVN-on ALL Closed": slice_syms(closed_hvn_on, dp),
        "ALL HVN-on (260819151232)": closed_hvn_on,
        "ALL HVN-off same-day (260819150528)": closed_all_off,
        "Paul5 names on ALL HVN-off (150528, mixed)": slice_syms(closed_all_off, user_set),
        "ALL HVN-off older (260817214643)": closed_all_off_old,
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

    p5_trades = slice_syms(closed_hvn_on, user_set)
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
    user_ss_6 = [s for s in user if paul(ss_by.get(s) or {}) == 6]

    def find_m(book, split):
        for m in metric_rows:
            if m["book"] == book and m["split"] == split:
                return m
        return None

    m_p5_oos = find_m("Paul5 HVN-on slice (260819151232)", "OOS")
    m_p5_is = find_m("Paul5 HVN-on slice (260819151232)", "IS")
    m_p5_full = find_m("Paul5 HVN-on slice (260819151232)", "FULL")
    m_dp_oos = find_m("DualPaul78 live HVN-off (260819140929)", "OOS")
    m_dp_is = find_m("DualPaul78 live HVN-off (260819140929)", "IS")
    m_dp_full = find_m("DualPaul78 live HVN-off (260819140929)", "FULL")
    m_dph_oos = find_m("DualPaul78 house HVN-off (260817212836)", "OOS")
    m_dph_is = find_m("DualPaul78 house HVN-off (260817212836)", "IS")

    def finite(v):
        return v is not None and isinstance(v, (int, float)) and math.isfinite(v)

    oos_shock = False
    oos_shock_why = "insufficient Dual/Paul5 OOS rows"
    if m_p5_oos and m_dp_oos and finite(m_p5_oos["wr"]) and finite(m_dp_oos["wr"]):
        wr_ok = m_p5_oos["wr"] >= m_dp_oos["wr"]
        r_ok = finite(m_p5_oos["avg_r"]) and finite(m_dp_oos["avg_r"]) and (
            m_p5_oos["avg_r"] >= m_dp_oos["avg_r"]
        )
        dd_ok = (
            finite(m_p5_oos["max_dd"])
            and finite(m_dp_oos["max_dd"])
            and m_p5_oos["max_dd"] <= m_dp_oos["max_dd"]
        )
        oos_shock = wr_ok and r_ok and dd_ok
        oos_shock_why = (
            f"WR {fmt_n(m_p5_oos['wr'],1)} vs Dual {fmt_n(m_dp_oos['wr'],1)} "
            f"({'beat' if wr_ok else 'lose'}); "
            f"AvgR {fmt_n(m_p5_oos['avg_r'],2)} vs {fmt_n(m_dp_oos['avg_r'],2)} "
            f"({'beat' if r_ok else 'lose'}); "
            f"MaxDD {fmt_n(m_p5_oos['max_dd'],2)} vs {fmt_n(m_dp_oos['max_dd'],2)} "
            f"({'better-or-equal' if dd_ok else 'worse'})"
        )

    rec_changed = "No"
    verdict = "No"
    if oos_shock:
        verdict = "HOLD research-only (do not replace VZ_universe.csv)"
        rec_changed = "No — OOS quality is strong vs Dual, still HOLD not house"

    baseline = f"""# BASELINE — post-hoc Paul==5 sleeve from HVN-on ALL Summary — vz_paul5_hvn_all_20260819

**Do not use as the VZ universe. Do not replace `drive/universes/VZ_universe.csv`. Not gold. Not DailyRun.**

## Correction vs prior folder

`vz_paul5_fulluniv_20260819` assumed the paste was ALL HVN-**off** `260817214643`. The paste was **`VZ_Summary_260819151232`**: fulluniv **1110**, **`vz_require_hvn_overlap=true`**. Numbers differ. Universe recommendation does **not** change unless OOS vs Dual is shockingly better on WR/AvgR/DD — even then HOLD research-only.

## Stamp knobs (`260819151232`)

Confirmed from `drive/paul_experiments/vz_run_260819151232/BASELINE.md`, `VZ_Report_260819151232.txt`, and Audit DNA:

| Knob | Value |
|------|-------|
| Universe | ALL / fulluniv **1110** requested, 1110 ok (SS rows={n_ss}). Stamp folder text still mentions DualPaul78 as the *default* research univ — this run was `run_vz.bat ALL`. |
| `vz_require_hvn_overlap` | **True** (house default false; HVN is HOLD, not adopted) |
| lookback / rw / eps / first_retest / mt / zones / entry | 126 / 63 / 0.005 / True / 1 / HL / next_open |
| Exit | `EXIT_atr4_s025_r15` (0.25 ATR stop, 1.5R, ts 40d) |
| min ATR % | 4 |

Two knobs vs house: **HVN-on (HOLD flag)** + **post-hoc Paul==5 winner-cut** after seeing this Summary. DualPaul78 is HVN-**off**. Adopting this list as house would silently AND HVN-on names from a HOLD flag.

## What the user saw

- Summary rows: **{n_sum}** traded names (truncated PAUL ceiling 5; no SHEET_PNL)
- Summary_Symbols rows: **{n_ss}**
- Integer **PAUL_SCORE == 5** on Summary: **{n_eq5}**
- PAUL_SCORE **≥ 5** on Summary: **{len(ge5_sum)}** (ceiling 5 → ==5)
- Truncated Paul: **{truncated_paul}**. Score 5 is **top-of-file**, not DualPaul middling 5/8.
- Typed list **{n_user}** (AEM included). Exact match to Summary PAUL==5: **{exact_eq5}** (user-not-in-bin {len(missing_vs_eq5)}; bin-not-in-user {len(extra_eq5)})
- 8-pt SS PAUL==5 ∩ list = {len(user_ss_eq5)} (they did not mean middling 5/8). Typed SS hist: {dict(ss_paul_hist_user)}. SS==6: {', '.join(user_ss_6) or 'none'}
- Dual-like on **this HVN-on** SS (Paul≥7 **and** OOS≥7): **{len(dual_like)}** / {n_user}. Stamp Dual 7–8 both: **{len(dual_ss)}** (not house DualPaul78=83; HVN changes who scores 7–8)

AEM: Summary PAUL={aem_sum_paul}; SS PAUL={aem_ss_paul}; PAUL_SCORE_OOS={aem_ss_oos}. DualPaul78: **{'Y' if 'AEM' in dp else 'N'}**.

Missing from Summary: {missing_sum or 'none'}. Completely absent: {missing_all or 'none'}.

## PAUL_SCORE_OOS on the typed list (HVN-on SS)

- Blank / missing OOS Paul: **{len(oos_blank)}**
- PAUL_SCORE_OOS ≥ 7: **{len(oos_ge7)}**
- PAUL_SCORE_OOS < 7: **{len(oos_lt7)}**
- Dual-like: **{len(dual_like)}** — Paul 5 truncated ≠ DualPaul 7–8 both on HVN-off

## Overlap DualPaul78 (HVN-off house universe)

- DualPaul78: **{len(dp)}** names
- Paul5 ∩ DualPaul78: **{len(overlap_dp)}** ({', '.join(overlap_dp) if overlap_dp else 'none'})
- Paul5 not in DualPaul78: **{len(only_paul5)}**
- DualPaul78 not in Paul5: **{len(only_dp)}**
- Tradable 764 ∩ Paul5: **{len(in_764)}**; not in 764: {not_764 or 'none'}

## Closed slice

Primary candidate = **this HVN-on Closed** sliced to the 59 names. Control = DualPaul78 live HVN-off `260819140929` (and house pin `260817212836`). Overlay slice ≠ concurrent-position house equity. Sheet $45k; Max DD $500k seed. IS = entry < 2024-01-01.

OOS shockingly better vs Dual live (WR **and** AvgR **and** Max DD not worse): **{'yes' if oos_shock else 'no'}** — {oos_shock_why}

## Selection honesty

HVN-on ALL + post-hoc Paul-5 = **two knobs** (HVN HOLD + winner-cut) + selection after seeing HVN-on Summary. Weaker case than DualPaul78, not stronger. Same class as `vz_is_paul78_20260818` DISMISS (IS winner-cut). OOS report-only — do not retune. Do not AND a HOLD HVN flag into the house universe by adopting this list.

## Verdict: **{verdict}**

Recommendation changed vs prior “don’t use as VZ universe” call? **{rec_changed}**. Keep house VZ = DualPaul78 HVN-**off**. `VZ_universe.csv` was not edited.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")
    (OUT / "AB_PLAN.md").write_text(
        """# AB_PLAN — vz_paul5_hvn_all_20260819 (research-only)

**Hypothesis (universe, mixed knobs — not a clean one-change AB):** After seeing fulluniv HVN-on Summary `260819151232`, use typed Paul==5 names (exact 59) as house VZ universe instead of DualPaul78.

**Control:** DualPaul78 `drive/universes/VZ_universe.csv`, HVN **off**, exit `EXIT_atr4_s025_r15` / rw63. Live Closed `260819140929` (engine A/B control) and house pin `260817212836`.

**Candidate:** User typed list = truncated Summary PAUL==5 on HVN-on ALL. **Two knobs:** `vz_require_hvn_overlap=true` (HOLD, not adopted) + in-sample winner-cut. Weaker than Dual 7–8 both on HVN-off. Adopting the list as house silently ANDs HVN-on.

**OOS:** report-only. Do not retune. Do not replace `VZ_universe.csv`. Do not DailyRun.

**Judge:** quality (WR, AvgR, Max DD, Avg PnL%, PF) on OOS vs Dual — not IS, not trade count. KEEP only if OOS is shockingly better; even then HOLD research-only.

**Verdict:** No (recommendation unchanged).
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
            ("Avg win %", "num"),
            ("Avg loss %", "num"),
            ("Avg R", "num"),
            ("PF", "num"),
            ("Avg days", "num"),
            ("Trades/yr", "num"),
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
            f"{td_num(m['avg_win'], 2)}"
            f"{td_num(m['avg_loss'], 2)}"
            f"{td_num(m['avg_r'], 2)}"
            f"{td_num(m['pf'], 2)}"
            f"{td_num(m['avg_days'], 1)}"
            f"{td_num(m['trades_per_year'], 1)}"
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

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ Paul==5 HVN-on ALL post-hoc slice — 20260819</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1400px; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.12rem; margin-top: 28px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
.verdict {{ border: 2px solid #991b1b; background: #fef2f2; }}
.warn {{ border: 2px solid #92400e; background: #fffbeb; }}
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
<h1>Should HVN-on ALL Paul==5 ({n_user} names) be the VZ universe?</h1>
<p class="sub"><strong>No.</strong> Source <code>VZ_Summary_260819151232</code> — fulluniv 1110,
<code>vz_require_hvn_overlap=true</code>. Not DualPaul78. Not gold. Not DailyRun.
Click column headers to sort.</p>
<div class="card warn">
<h2>Correction</h2>
<p>Prior folder <code>vz_paul5_fulluniv_20260819</code> scored ALL HVN-<strong>off</strong>
<code>260817214643</code>. The paste was <strong>this</strong> HVN-on stamp. Numbers differ.
Recommendation still <strong>No</strong> unless OOS vs Dual is shockingly better on WR/AvgR/DD
(not just IS). Even then HOLD research-only — do not replace <code>VZ_universe.csv</code>.</p>
</div>
<div class="card verdict">
<h2>Verdict: {escape(verdict)}</h2>
<p>Two knobs vs house: HVN HOLD flag <strong>on</strong> + post-hoc truncated-Summary Paul==5
winner-cut after seeing this book. Weaker case than DualPaul78 (Paul 7–8 <strong>both</strong>
on HVN-<strong>off</strong>), not stronger. DualPaul78 is HVN-off; adopting this list as house
would silently AND HVN-on names from a HOLD flag. Recommendation changed?
<strong>{escape(rec_changed)}</strong>.</p>
<p>OOS shockingly better vs Dual live 140929 (WR and AvgR and Max DD not worse):
<strong>{'yes' if oos_shock else 'no'}</strong> — {escape(oos_shock_why)}.</p>
</div>
<div class="card">
<p><strong>Stamp knobs:</strong> ALL/fulluniv <strong>1110</strong> (SS {n_ss}; Summary traded {n_sum});
<code>vz_require_hvn_overlap=true</code> (Audit DNA + Report <code>hvn=True</code>);
lookback 126, rw 63, HL, first_retest, mt≥1, next_open, <code>EXIT_atr4_s025_r15</code>, min ATR 4.
Stamp folder text still names DualPaul78 as the default univ file — this run was ALL.</p>
<p><strong>PAUL_SCORE==5 on this Summary:</strong> <strong>{n_eq5}</strong> (ceiling 5, so ≥5 == ==5).
Typed list ∩ that bin = <strong>{n_user - len(missing_vs_eq5)} / {n_user}</strong>
({'exact match' if exact_eq5 else 'not exact'}). Extra in bin: {len(extra_eq5)}.
8-pt SS PAUL==5 ∩ list = {len(user_ss_eq5)}. Typed SS hist {escape(str(dict(ss_paul_hist_user)))}.
SS==6: {escape(', '.join(user_ss_6) or 'none')}.</p>
<p><strong>AEM:</strong> ticker. Summary PAUL={fmt_n(aem_sum_paul,0)}; SS PAUL={fmt_n(aem_ss_paul,0)};
OOS Paul={fmt_n(aem_ss_oos,0)}; DualPaul78={'Y' if 'AEM' in dp else 'N'}.</p>
<p><strong>OOS Paul on typed list:</strong> blank {len(oos_blank)}; ≥7 {len(oos_ge7)}; &lt;7 {len(oos_lt7)}.
Dual-like on <em>this HVN-on</em> SS (SS≥7 and OOS≥7): {len(dual_like)}
({escape(', '.join(dual_like) or 'none')}).
HVN-on stamp Dual 7–8 both: {len(dual_ss)} (house DualPaul78 is 83 on HVN-off).</p>
<p><strong>Overlap DualPaul78:</strong> {len(overlap_dp)} / {n_user}
({escape(', '.join(overlap_dp) if overlap_dp else 'none')}).
Not in Dual: {len(only_paul5)}. ∩ tradable 764: {len(in_764)}.
Absent / typo: {escape(', '.join(missing_all) if missing_all else 'none')}.</p>
</div>
<h2>Closed overlay IS / OOS (canonical-ish quality)</h2>
<p class="small">Primary = HVN-on Closed <code>260819151232</code> sliced to the typed 59.
Control = DualPaul78 HVN-off live <code>260819140929</code> and house pin <code>260817212836</code>.
Same-day ALL HVN-off <code>260819150528</code> is context (not the paste). Dual slice of HVN-on Closed
shows the silent AND. Sheet $45k; Max DD on $500k seed. Overlay ≠ concurrent house equity.
Click headers to sort.</p>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{metric_head}</tr></thead>
<tbody>
{''.join(metric_body)}
</tbody>
</table>
<p class="small">Headline OOS: Paul5 HVN-on WR {fmt_n(m_p5_oos['wr'] if m_p5_oos else None, 1)}%
AvgPnL {fmt_n(m_p5_oos['avg_pnl'] if m_p5_oos else None, 2)} AvgR {fmt_n(m_p5_oos['avg_r'] if m_p5_oos else None, 2)}
MaxDD {fmt_n(m_p5_oos['max_dd'] if m_p5_oos else None, 2)} (N={fmt_n(m_p5_oos['n'] if m_p5_oos else None, 0)})
vs Dual live WR {fmt_n(m_dp_oos['wr'] if m_dp_oos else None, 1)}%
AvgPnL {fmt_n(m_dp_oos['avg_pnl'] if m_dp_oos else None, 2)} AvgR {fmt_n(m_dp_oos['avg_r'] if m_dp_oos else None, 2)}
MaxDD {fmt_n(m_dp_oos['max_dd'] if m_dp_oos else None, 2)} (N={fmt_n(m_dp_oos['n'] if m_dp_oos else None, 0)}).
IS Avg PnL% Paul5 {fmt_n(m_p5_is['avg_pnl'] if m_p5_is else None, 2)} vs Dual live
{fmt_n(m_dp_is['avg_pnl'] if m_dp_is else None, 2)} (IS looks better — expected after picking Summary winners).
House pin 212836 OOS WR {fmt_n(m_dph_oos['wr'] if m_dph_oos else None, 1)}% AvgR
{fmt_n(m_dph_oos['avg_r'] if m_dph_oos else None, 2)}.</p>
<h2>Exit mix (Paul5 slice of HVN-on Closed)</h2>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{sortable_th('EXIT_TYPE','text')}{sortable_th('FULL N','num')}{sortable_th('FULL %','num')}{sortable_th('OOS N','num')}{sortable_th('OOS %','num')}</tr></thead>
<tbody>{''.join(mix_body)}</tbody>
</table>
<h2>Typed names — Paul IS / OOS (HVN-on Summary_Symbols)</h2>
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
<p class="small">See BASELINE.md. DualPaul78 remains the research default. HVN flag stays HOLD/off.
<code>VZ_universe.csv</code> was not edited.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    patch_old_fulluniv_banner()

    print("SUMMARY_ROWS", n_sum, "SS_ROWS", n_ss)
    print("TRUNCATED", truncated_paul, "SUM_HIST", dict(hist))
    print("PAUL==5", len(eq5_sum), "PAUL>=5", len(ge5_sum), "EXACT_MATCH", exact_eq5)
    print("USER_N", n_user)
    print("MISSING_VS_EQ5", missing_vs_eq5)
    print("EXTRA_EQ5", extra_eq5)
    print("MISSING_ALL", missing_all)
    print("AEM", aem_sum_paul, aem_ss_paul, aem_ss_oos, "AEM_IN_DP", "AEM" in dp)
    print("OOS_BLANK", len(oos_blank), [x[0] for x in oos_blank])
    print("OOS_GE7", len(oos_ge7), [x[0] for x in oos_ge7])
    print("OOS_LT7", len(oos_lt7))
    print("DUAL_LIKE", dual_like)
    print("STAMP_DUAL78", len(dual_ss))
    print("OVERLAP_DP", len(overlap_dp), overlap_dp)
    print("PAUL5_ONLY_N", len(only_paul5))
    print("IN_764", len(in_764), "NOT_764", not_764)
    print("OOS_SHOCK", oos_shock, oos_shock_why)
    print("REC_CHANGED", rec_changed)
    print("VERDICT", verdict)
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
