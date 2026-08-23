"""Slice ALL BRT Closed onto post-hoc PAUL_SCORE>=8 AND FIT_SCORE>=6 AND FIT_SCORE_ROBUST>=6.

Research-only. Does not replace drive/universes/BRT_universe.csv. Not DailyRun.

Sibling arm: Paul==8 fulluniv (104) lives in brt_paul8_fulluniv_20260819.
This stamp also overlays that Paul8-only book on the same Closed tape so both
winner-cuts sit on one HTML.
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

OUT = ROOT / "drive" / "paul_experiments" / "brt_paul8_fit6_20260819"
SUMMARY_ALL = ROOT / "drive" / "BRT_Summary_260819234529.csv"
SUMMARY_764 = ROOT / "drive" / "BRT_Summary_260819133252.csv"
SUMMARY_42 = ROOT / "drive" / "BRT_Summary_260819183616.csv"
UNIV_42 = ROOT / "drive" / "universes" / "BRT_universe.csv"
UNIV_764 = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CLOSED_ALL = ROOT / "drive" / "BRT_Closed_260819234529.csv"
CLOSED_764 = ROOT / "drive" / "BRT_Closed_260819133252.csv"
CLOSED_42 = ROOT / "drive" / "BRT_Closed_260819183616.csv"
SIBLING_HTML = ROOT / "drive" / "paul_experiments" / "brt_paul8_fulluniv_20260819" / "compare.html"

# User paste: Paul >= 8 AND FIT score AND FIT robust >= 6
USER_TYPED = [
    "NGL", "ZETA", "ADPT", "AMAT", "MPWR", "ONDS", "RNG", "AAON", "ALGN", "AMD",
    "ANET", "APP", "ARGX", "ATEYY", "ATLC", "BX", "CGC", "CHCI", "CORT", "CZR",
    "DASH", "DDS", "DHI", "DY", "GHM", "GNRC", "IBP", "IESC", "IRMD", "LAD",
    "LMB", "LRCX", "LUGDF", "NFLX", "NOW", "NXST", "ONTO", "PDEX", "PFSI", "PLUS",
    "PODD", "PSIX", "RCMT", "RDNT", "SAIA", "SANM", "SE", "SRPT", "STLD", "SVM",
    "TATT", "TAYD", "TGLS", "TSEM", "UAL", "URI", "UTI", "VLO", "VRT", "WCC",
    "WSM", "ZS",
]

HOLD_CUT = datetime(2024, 1, 1)
SHEET = 47_500.0
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
        s = (row.get("SYMBOL") or row.get("ticker") or "").strip().upper()
        if s:
            out.append(s)
    if not out:
        with path.open(encoding="utf-8-sig") as f:
            for ln in f:
                s = ln.strip().upper()
                if not s or s.startswith("#") or s == "SYMBOL":
                    continue
                out.append(s.split(",")[0].strip())
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


def load_summary(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def paul(r: dict | None):
    if not r:
        return None
    return parse_number(r.get("PAUL_SCORE"))


def fit_score(r: dict | None):
    if not r:
        return None
    return parse_number(r.get("FIT_SCORE"))


def fit_robust(r: dict | None):
    if not r:
        return None
    return parse_number(r.get("FIT_SCORE_ROBUST"))


def pass_p8_fit6(r: dict) -> bool:
    p = paul(r)
    fs = fit_score(r)
    fr = fit_robust(r)
    return (p is not None and p >= 8) and (fs is not None and fs >= 6) and (fr is not None and fr >= 6)


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
        "total_pnl_d": 0.0,
        "avg_days": float("nan"),
        "expectancy_pct": float("nan"),
        "n_names": 0,
        "avg_win": float("nan"),
        "avg_loss": float("nan"),
        "capital_days": float("nan"),
        "profit_per_cd": float("nan"),
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades if t["pnl"] is not None]
    wins_p = [p for p in pnls if p > 0]
    loss_p = [p for p in pnls if p < 0]
    wins = len(wins_p)
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
    cap_d = cap.get("capital_days", float("nan"))
    pnl_d = sum(t["pnl_d"] or 0.0 for t in trades)
    ppc = (pnl_d / cap_d) if cap_d and math.isfinite(cap_d) and cap_d != 0 else float("nan")
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
        "total_pnl_d": pnl_d,
        "avg_days": avg_days,
        "expectancy_pct": avg_pnl,
        "n_names": len({t["sym"] for t in trades}),
        "avg_win": sum(wins_p) / len(wins_p) if wins_p else float("nan"),
        "avg_loss": sum(loss_p) / len(loss_p) if loss_p else float("nan"),
        "capital_days": cap_d,
        "profit_per_cd": ppc,
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


def slice_syms(closed, names):
    want = set(names)
    return [t for t in closed if t["sym"] in want]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    user = list(dict.fromkeys(USER_TYPED))
    user_set = set(user)

    sum_all = load_summary(SUMMARY_ALL)
    sum_764 = load_summary(SUMMARY_764)
    sum_42 = load_summary(SUMMARY_42)
    n_sum = len(sum_all)
    sum_cols = list(sum_all[0].keys()) if sum_all else []
    has_oos_col = "PAUL_SCORE_OOS" in sum_cols

    def by_sym(rows):
        return {(r.get("SYMBOL") or "").strip().upper(): r for r in rows}

    all_by = by_sym(sum_all)
    s764_by = by_sym(sum_764)
    s42_by = by_sym(sum_42)

    p8_all = [r for r in sum_all if (paul(r) or -1) >= 8]
    p8_syms = [(r.get("SYMBOL") or "").strip().upper() for r in p8_all]
    p8_set = set(p8_syms)

    fit6_all = [r for r in sum_all if pass_p8_fit6(r)]
    fit6_syms = [(r.get("SYMBOL") or "").strip().upper() for r in fit6_all]
    fit6_set = set(fit6_syms)

    # Alternate: FIT text High + robust >=6 (should not be the paste if numeric AND)
    fit_high_p8 = [
        (r.get("SYMBOL") or "").strip().upper()
        for r in sum_all
        if (paul(r) or -1) >= 8 and str(r.get("FIT") or "").strip().lower() == "high"
    ]

    extra = sorted(fit6_set - user_set)
    missing = [s for s in user if s not in fit6_set]
    order_file = user == fit6_syms
    sorted_match = user == sorted(fit6_set)

    # Paul8-only extras vs this paste
    p8_not_fit6 = sorted(p8_set - fit6_set)
    paste_not_p8 = [s for s in user if s not in p8_set]

    fit6_764 = {
        (r.get("SYMBOL") or "").strip().upper()
        for r in sum_764
        if pass_p8_fit6(r)
    }
    p8_764 = {(r.get("SYMBOL") or "").strip().upper() for r in sum_764 if (paul(r) or -1) >= 8}
    fit6_42s = {
        (r.get("SYMBOL") or "").strip().upper()
        for r in sum_42
        if pass_p8_fit6(r)
    }

    dp42 = set(load_syms(UNIV_42))
    u764 = set(load_syms(UNIV_764))
    overlap_42 = [s for s in user if s in dp42]
    only_fit6 = sorted(user_set - dp42)
    only_42 = sorted(dp42 - user_set)
    in_764 = [s for s in user if s in u764]
    not_764 = [s for s in user if s not in u764]
    overlap_p8 = sorted(user_set & p8_set)

    # Why missing (if any)
    miss_why = []
    for s in missing:
        r = all_by.get(s)
        if not r:
            miss_why.append(f"{s}: not on ALL Summary")
            continue
        miss_why.append(
            f"{s}: PAUL={paul(r)} FIT_SCORE={fit_score(r)} FIT_SCORE_ROBUST={fit_robust(r)} FIT={r.get('FIT')}"
        )

    closed_all = load_closed(CLOSED_ALL)
    closed_764 = load_closed(CLOSED_764)
    closed_42 = load_closed(CLOSED_42)

    books = {
        "Paul8+FIT6 ALL slice (260819234529)": slice_syms(closed_all, user_set if not extra and not missing else fit6_set),
        "Paul8-only ALL slice (104, sibling)": slice_syms(closed_all, p8_set),
        "42 production slice of ALL Closed": slice_syms(closed_all, dp42),
        "764 tradable slice of ALL Closed": slice_syms(closed_all, u764),
        "ALL Closed (260819234529)": closed_all,
        "42 live Closed (260819183616)": closed_42,
        "764 live Closed (260819133252)": closed_764,
        "Paul8+FIT6 of 764 slice of 764 Closed": slice_syms(closed_764, fit6_764),
    }
    # If paste != disk, also show paste-as-typed overlay
    if extra or missing:
        books["User paste slice of ALL Closed"] = slice_syms(closed_all, user_set)
        books["Disk Paul8+FIT6 slice of ALL Closed"] = slice_syms(closed_all, fit6_set)

    metric_rows = []
    for name, trades in books.items():
        sp = split_book(trades)
        for split, tr in sp.items():
            st = stats(tr)
            metric_rows.append({"book": name, "split": split.upper(), **st})

    hist_paul = Counter(int(paul(r)) if paul(r) is not None else -99 for r in sum_all)
    hist_fit = Counter(int(fit_score(r)) if fit_score(r) is not None else -99 for r in p8_all)
    hist_rob = Counter(int(fit_robust(r)) if fit_robust(r) is not None else -99 for r in p8_all)

    primary_set = user_set if not extra and not missing else fit6_set
    p6_trades = slice_syms(closed_all, primary_set)
    p6_split = split_book(p6_trades)
    mix_full = exit_mix(p6_split["full"])
    mix_oos = exit_mix(p6_split["oos"])

    def avg_pnl(trs):
        pn = [t["pnl"] for t in trs if t["pnl"] is not None]
        return sum(pn) / len(pn) if pn else None

    by_name_split = {}
    for t in slice_syms(closed_all, user_set | fit6_set):
        d = by_name_split.setdefault(t["sym"], {"is": [], "oos": [], "full": []})
        d["full"].append(t)
        if t["opened"] and t["opened"] < HOLD_CUT:
            d["is"].append(t)
        elif t["opened"]:
            d["oos"].append(t)

    n_user = len(user)

    def find_m(book, split):
        for m in metric_rows:
            if m["book"] == book and m["split"] == split:
                return m
        return None

    book_p6 = "Paul8+FIT6 ALL slice (260819234529)"
    book_p8 = "Paul8-only ALL slice (104, sibling)"
    book_42 = "42 production slice of ALL Closed"
    book_764 = "764 tradable slice of ALL Closed"
    book_all = "ALL Closed (260819234529)"

    m_p6_oos = find_m(book_p6, "OOS")
    m_p8_oos = find_m(book_p8, "OOS")
    m_42_oos = find_m(book_42, "OOS")
    m_764_oos = find_m(book_764, "OOS")
    m_all_oos = find_m(book_all, "OOS")
    m_p6_is = find_m(book_p6, "IS")
    m_p8_is = find_m(book_p8, "IS")
    m_42_is = find_m(book_42, "IS")
    m_764_is = find_m(book_764, "IS")
    m_all_is = find_m(book_all, "IS")

    sibling_note = (
        f"Sibling Paul8-only HTML: `{SIBLING_HTML.as_posix()}` exists={SIBLING_HTML.exists()}."
    )

    exact = (not extra) and (not missing)
    baseline = f"""# BASELINE — post-hoc Paul>=8 AND FIT_SCORE>=6 AND FIT_SCORE_ROBUST>=6 — brt_paul8_fit6_20260819

**Do not use as the BRT universe. Do not replace `drive/universes/BRT_universe.csv`. Not gold. Not DailyRun.**

## What the user saw

Source: `drive/BRT_Summary_260819234529.csv` (`run_brt.bat ALL`, **{n_sum}** traded names). Columns used: `PAUL_SCORE`, `FIT_SCORE`, `FIT_SCORE_ROBUST` (text `FIT` is a tier label, not the cut). Companion Closed `BRT_Closed_260819234529.csv`.

- PAUL_SCORE ≥ 8: **{len(p8_all)}** (sibling Paul8-only arm)
- PAUL≥8 AND FIT_SCORE≥6 AND FIT_SCORE_ROBUST≥6: **{len(fit6_all)}**
- `PAUL_SCORE_OOS` on Summary: **{has_oos_col}**
- PAUL≥8 AND text FIT==High: **{len(fit_high_p8)}** (not the paste definition)

User pasted **{n_user}** names. Vs disk AND-cut: in both **{n_user - len(missing)}**; user-not-in-bin **{len(missing)}**; bin-not-in-user **{len(extra)}**. Sorted-set vs paste: **{'exact' if sorted_match else 'no'}**. File-order vs paste: **{'exact' if order_file else 'no'}**. Exact match: **{exact}**.

Missing why: {'; '.join(miss_why) if miss_why else 'none'}.
Paul8 names that fail FIT6 AND: **{len(p8_not_fit6)}**.

Not the 764 stamp `260819133252` (AND-cut n={len(fit6_764)}; PAUL≥8 n={len(p8_764)}; paste ∩ 764-AND = {len(user_set & fit6_764)}).
Not LatestRun/42 Summary `260819183616` (AND-cut n={len(fit6_42s)}: {', '.join(sorted(fit6_42s)) or 'none'}).

## Overlap vs production 42 and vs Paul8-only

- Production whitelist: **{len(dp42)}**
- Paul8+FIT6 paste ∩ 42: **{len(overlap_42)}** ({', '.join(overlap_42) if overlap_42 else 'none'})
- Paste not in 42: **{len(only_fit6)}**
- 42 not in paste: **{len(only_42)}**
- Paste ∩ Paul8 disk: **{len(overlap_p8)}** / paste {n_user} / Paul8 {len(p8_set)}
- Tradable 764 ∩ paste: **{len(in_764)}**; not in 764: **{len(not_764)}** ({', '.join(not_764)})

{sibling_note}

## Closed overlay (primary = ALL `260819234529`)

Capital: sheet ${SHEET:,.0f}; Max DD $500k seed. IS = entry < 2024-01-01. Overlay slice ≠ concurrent-position house equity.

See `compare.html` (both Paul8-only and Paul8+FIT6 arms).

## Selection honesty

Post-hoc DualPaul-style AND (Paul 8 **and** FIT≥6 **and** robust FIT≥6) on the **fulluniv Summary already seen** is an **in-sample winner-cut**. Tightening Paul8 (104) with FIT does not remove that label. OOS is report-only — do not retune. Do not overwrite `BRT_universe.csv`.

## Verdict: **DISMISS as house universe** (HOLD as research sleeve only)

Keep house BRT = 42-name production whitelist. DualPaul-style AND is still a winner-cut after seeing the book. Research sleeve only; selection labeled. Not gold.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")
    (OUT / "AB_PLAN.md").write_text(
        """# AB_PLAN — brt_paul8_fit6_20260819 (research-only)

**Hypothesis (universe, not exit):** After seeing ALL BRT Summary `260819234529`, use PAUL_SCORE>=8 AND FIT_SCORE>=6 AND FIT_SCORE_ROBUST>=6 as house BRT universe instead of the 42-name production whitelist (second DualPaul-style AND vs sibling Paul8-only 104).

**Control:** `drive/universes/BRT_universe.csv` (42). Same Closed overlay `BRT_Closed_260819234529.csv`.

**Candidate A (this stamp):** typed Paul8+FIT6 names. Post-hoc IS winner-cut.

**Candidate B (sibling, same overlay):** PAUL_SCORE==8 on the same Summary (104 names) — `brt_paul8_fulluniv_20260819`.

**OOS:** report-only. Do not retune. Do not replace `BRT_universe.csv`. Do not DailyRun-wire.

**Judge:** quality (WR, Avg PnL%, PF, Ann ROR, Max DD), not trade count. FIT-AND after seeing Paul8 is still selection on the same tape.

**Verdict:** DISMISS as house replacement. HOLD/research sleeve only.
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
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Sheet PnL $", "num"),
            ("Total PnL $", "num"),
            ("Capital days", "num"),
            ("Profit / cap day $", "num"),
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
            f"{td_num(m['ann_ror'], 1)}"
            f"{td_num(m['max_dd'], 2)}"
            f'<td class="num">{format_money(m["sheet_pnl"])}</td>'
            f'<td class="num">{format_money(m["total_pnl_d"])}</td>'
            f"{td_num(m['capital_days'], 0)}"
            f'<td class="num">{format_money(m["profit_per_cd"])}</td>'
            "</tr>"
        )

    def dlt(a, b):
        if a is None or b is None:
            return float("nan")
        if isinstance(a, float) and not math.isfinite(a):
            return float("nan")
        if isinstance(b, float) and not math.isfinite(b):
            return float("nan")
        return a - b

    delta_pairs = [
        ("Paul8+FIT6 vs 42 overlay OOS", m_p6_oos, m_42_oos),
        ("Paul8+FIT6 vs 42 overlay IS", m_p6_is, m_42_is),
        ("Paul8+FIT6 vs Paul8-only OOS", m_p6_oos, m_p8_oos),
        ("Paul8+FIT6 vs Paul8-only IS", m_p6_is, m_p8_is),
        ("Paul8+FIT6 vs 764 overlay OOS", m_p6_oos, m_764_oos),
        ("Paul8+FIT6 vs ALL overlay OOS", m_p6_oos, m_all_oos),
        ("Paul8-only vs 42 overlay OOS", m_p8_oos, m_42_oos),
        ("Paul8-only vs 42 overlay IS", m_p8_is, m_42_is),
    ]
    delta_head = "".join(
        sortable_th(lab, typ)
        for lab, typ in [
            ("Compare", "text"),
            ("Δ N", "num"),
            ("Δ Win %", "num"),
            ("Δ Avg PnL %", "num"),
            ("Δ WO_MAX", "num"),
            ("Δ PF", "num"),
            ("Δ Ann ROR %", "num"),
            ("Δ Max DD % (cand−ctrl; lower DD better so + is worse)", "num"),
            ("Δ Sheet PnL $", "num"),
        ]
    )
    delta_body = []
    for label, cand, ctrl in delta_pairs:
        if not cand or not ctrl:
            continue
        d_sheet = dlt(cand["sheet_pnl"], ctrl["sheet_pnl"])
        delta_body.append(
            "<tr>"
            f"<td>{escape(label)}</td>"
            f"{td_num(dlt(cand['n'], ctrl['n']), 0)}"
            f"{td_num(dlt(cand['wr'], ctrl['wr']), 1)}"
            f"{td_num(dlt(cand['avg_pnl'], ctrl['avg_pnl']), 2)}"
            f"{td_num(dlt(cand['avg_pnl_wo_max'], ctrl['avg_pnl_wo_max']), 2)}"
            f"{td_num(dlt(cand['pf'], ctrl['pf']), 2)}"
            f"{td_num(dlt(cand['ann_ror'], ctrl['ann_ror']), 1)}"
            f"{td_num(dlt(cand['max_dd'], ctrl['max_dd']), 2)}"
            f'<td class="num">{format_money(d_sheet) if math.isfinite(d_sheet) else "—"}</td>'
            "</tr>"
        )

    name_head = "".join(
        sortable_th(lab, typ)
        for lab, typ in [
            ("SYMBOL", "text"),
            ("ALL PAUL_SCORE", "num"),
            ("FIT_SCORE", "num"),
            ("FIT_SCORE_ROBUST", "num"),
            ("FIT tier", "text"),
            ("Pass AND-cut", "text"),
            ("In Paul8 bin", "text"),
            ("In 42 whitelist", "text"),
            ("In 764 tradable", "text"),
            ("IS N", "num"),
            ("OOS N", "num"),
            ("IS Avg PnL %", "num"),
            ("OOS Avg PnL %", "num"),
        ]
    )
    name_body = []
    shown = list(dict.fromkeys(user + extra))
    for s in shown:
        sr = all_by.get(s, {})
        parts = by_name_split.get(s, {"is": [], "oos": []})
        name_body.append(
            "<tr>"
            f"<td>{escape(s)}</td>"
            f"{td_num(paul(sr), 0)}"
            f"{td_num(fit_score(sr), 0)}"
            f"{td_num(fit_robust(sr), 0)}"
            f"<td>{escape(str(sr.get('FIT') or ''))}</td>"
            f"<td>{'Y' if s in fit6_set else 'N'}</td>"
            f"<td>{'Y' if s in p8_set else 'N'}</td>"
            f"<td>{'Y' if s in dp42 else 'N'}</td>"
            f"<td>{'Y' if s in u764 else 'N'}</td>"
            f"{td_num(len(parts.get('is') or []), 0)}"
            f"{td_num(len(parts.get('oos') or []), 0)}"
            f"{td_num(avg_pnl(parts.get('is') or []), 2)}"
            f"{td_num(avg_pnl(parts.get('oos') or []), 2)}"
            "</tr>"
        )

    hist_p_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist_paul[k], 0)}</tr>'
        for k in sorted(hist_paul)
    )
    hist_f_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist_fit[k], 0)}</tr>'
        for k in sorted(hist_fit)
    )
    hist_r_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist_rob[k], 0)}</tr>'
        for k in sorted(hist_rob)
    )

    mix_keys = sorted(set(mix_full) | set(mix_oos))
    mix_body = []
    n_full = max(len(p6_split["full"]), 1)
    n_oos_m = max(len(p6_split["oos"]), 1)
    for k in mix_keys:
        cf, co = mix_full[k], mix_oos[k]
        mix_body.append(
            "<tr>"
            f"<td>{escape(k)}</td>"
            f"{td_num(cf, 0)}"
            f"{td_num(100.0 * cf / n_full, 1)}"
            f"{td_num(co, 0)}"
            f"{td_num(100.0 * co / n_oos_m, 1)}"
            "</tr>"
        )

    yes_no = "Yes — exact match" if exact else "No — not an exact disk match"
    sibling_link = ""
    if SIBLING_HTML.exists():
        sibling_link = (
            '<p class="small">Sibling Paul8-only report: '
            '<a href="../brt_paul8_fulluniv_20260819/compare.html">'
            "brt_paul8_fulluniv_20260819/compare.html</a>.</p>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>BRT Paul≥8 AND FIT≥6 AND robust FIT≥6 — 20260819</title>
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
<h1>Is this Paul≥8 AND FIT_SCORE≥6 AND FIT_SCORE_ROBUST≥6 from ALL BRT?</h1>
<p class="sub"><strong>{escape(yes_no)}.</strong> Cut on ALL Summary
<code>260819234529.csv</code> ({n_sum} names): <code>PAUL_SCORE&gt;=8</code> and
<code>FIT_SCORE&gt;=6</code> and <code>FIT_SCORE_ROBUST&gt;=6</code>. Text <code>FIT</code> is a
tier, not the gate. Click column headers to sort.</p>
<div class="card verdict">
<h2>Verdict: DISMISS as house universe — do not replace the 42</h2>
<p>DualPaul-style AND after seeing the fulluniv book is still an in-sample winner-cut.
House stays 42-name <code>BRT_universe.csv</code>. Research sleeve only — not gold, not DailyRun.
<code>BRT_universe.csv</code> was not edited. Tightening Paul8 (104) with FIT≥6 does not clear
selection bias.</p>
</div>
<div class="card">
<p><strong>Stamp:</strong> ALL <code>260819234529</code>. Disk AND-cut N=<strong>{len(fit6_all)}</strong>;
paste N=<strong>{n_user}</strong>. Extra on disk: {len(extra)} ({escape(', '.join(extra) or 'none')}).
Missing vs disk: {len(missing)} ({escape(', '.join(missing) or 'none')}). Sorted-set exact={sorted_match};
file-order exact={order_file}.</p>
<p><strong>Paul8-only sibling:</strong> PAUL≥8 N=<strong>{len(p8_set)}</strong>. Paste ∩ Paul8 =
{len(overlap_p8)}. Paul8 failing FIT AND: {len(p8_not_fit6)}.</p>
<p><strong>Not</strong> 764 <code>260819133252</code> (AND n={len(fit6_764)}; ∩ paste={len(user_set & fit6_764)}).
<strong>Not</strong> 42 Summary <code>260819183616</code> (AND n={len(fit6_42s)}:
{escape(', '.join(sorted(fit6_42s)) or 'none')}).</p>
<p><strong>Overlap 42:</strong> {len(overlap_42)} / {n_user}
({escape(', '.join(overlap_42) if overlap_42 else 'none')}).
42 not in paste: {len(only_42)}. ∩ tradable 764: {len(in_764)}. Not in 764: {len(not_764)}
({escape(', '.join(not_764))}).</p>
<p><code>PAUL_SCORE_OOS</code> on Summary: {has_oos_col}. Columns: {escape(', '.join(sum_cols))}.</p>
</div>
{sibling_link}
<h2>Closed overlay IS / OOS (canonical quality)</h2>
<p class="small">Primary = ALL Closed <code>260819234529</code> sliced to Paul8+FIT6 / Paul8-only / 42 / 764 / ALL.
Live 42 and live 764 are identity books. Sheet ${SHEET:,.0f}; Max DD on $500k seed. Overlay ≠ concurrent house equity.</p>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{metric_head}</tr></thead>
<tbody>
{''.join(metric_body)}
</tbody>
</table>
<table class="sortable">
<caption>Deltas vs overlay control (same ALL Closed). Click headers to sort.</caption>
<thead><tr>{delta_head}</tr></thead>
<tbody>{''.join(delta_body)}</tbody>
</table>
<p class="small">Headline OOS Avg PnL%: Paul8+FIT6 {fmt_n(m_p6_oos['avg_pnl'] if m_p6_oos else None, 2)}
vs Paul8-only {fmt_n(m_p8_oos['avg_pnl'] if m_p8_oos else None, 2)}
vs 42 overlay {fmt_n(m_42_oos['avg_pnl'] if m_42_oos else None, 2)}
vs 764 {fmt_n(m_764_oos['avg_pnl'] if m_764_oos else None, 2)}
vs ALL {fmt_n(m_all_oos['avg_pnl'] if m_all_oos else None, 2)}.
IS Avg PnL%: Paul8+FIT6 {fmt_n(m_p6_is['avg_pnl'] if m_p6_is else None, 2)}
vs Paul8-only {fmt_n(m_p8_is['avg_pnl'] if m_p8_is else None, 2)}
vs 42 {fmt_n(m_42_is['avg_pnl'] if m_42_is else None, 2)}
vs 764 {fmt_n(m_764_is['avg_pnl'] if m_764_is else None, 2)}
vs ALL {fmt_n(m_all_is['avg_pnl'] if m_all_is else None, 2)}.
OOS Ann ROR: FIT6 {fmt_n(m_p6_oos['ann_ror'] if m_p6_oos else None, 1)} vs 42 {fmt_n(m_42_oos['ann_ror'] if m_42_oos else None, 1)}.
OOS Max DD: FIT6 {fmt_n(m_p6_oos['max_dd'] if m_p6_oos else None, 2)} vs 42 {fmt_n(m_42_oos['max_dd'] if m_42_oos else None, 2)}
(IS lift vs ALL is expected — we picked Summary winners).</p>
<h2>Exit mix (Paul8+FIT6 slice of ALL Closed)</h2>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{sortable_th('EXIT_TYPE','text')}{sortable_th('FULL N','num')}{sortable_th('FULL %','num')}{sortable_th('OOS N','num')}{sortable_th('OOS %','num')}</tr></thead>
<tbody>{''.join(mix_body)}</tbody>
</table>
<h2>Typed names — Paul / FIT / robust + Closed IS/OOS</h2>
<table class="sortable">
<caption>Click column headers to sort.</caption>
<thead><tr>{name_head}</tr></thead>
<tbody>
{''.join(name_body)}
</tbody>
</table>
<h2>PAUL_SCORE histogram (ALL Summary {n_sum})</h2>
<table class="sortable"><thead><tr>{sortable_th('PAUL_SCORE','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist_p_rows}</tbody></table>
<h2>FIT_SCORE among PAUL≥8 ({len(p8_all)} names)</h2>
<table class="sortable"><thead><tr>{sortable_th('FIT_SCORE','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist_f_rows}</tbody></table>
<h2>FIT_SCORE_ROBUST among PAUL≥8</h2>
<table class="sortable"><thead><tr>{sortable_th('FIT_SCORE_ROBUST','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist_r_rows}</tbody></table>
<p class="small">See BASELINE.md. House BRT remains the 42-name production whitelist.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    with (OUT / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(metric_rows[0].keys()) if metric_rows else [])
        w.writeheader()
        w.writerows(metric_rows)

    with (OUT / "names.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "in_paste", "in_disk_and", "PAUL_SCORE", "FIT_SCORE", "FIT_SCORE_ROBUST", "FIT"])
        for s in sorted(user_set | fit6_set):
            r = all_by.get(s, {})
            w.writerow([s, int(s in user_set), int(s in fit6_set), paul(r), fit_score(r), fit_robust(r), r.get("FIT")])

    print("ALL_SUMMARY", n_sum, "COLS", sum_cols)
    print("PAUL>=8", len(p8_set), "AND_FIT6", len(fit6_set))
    print("USER_N", n_user, "EXTRA", extra, "MISSING", missing)
    print("EXACT", exact, "SORTED", sorted_match, "FILE_ORDER", order_file)
    print("OVERLAP_42", len(overlap_42), overlap_42)
    print("ONLY_42", len(only_42))
    print("OVERLAP_P8", len(overlap_p8), "P8_FAIL_FIT", len(p8_not_fit6))
    print("IN_764", len(in_764), "NOT_764", not_764)
    print("FIT6_764", len(fit6_764), "FIT6_42", sorted(fit6_42s))
    print("HTML", html_path)
    for m in metric_rows:
        print(
            f"{m['book']}|{m['split']}|names={m['n_names']}|N={m['n']}|"
            f"WR={fmt_n(m['wr'],1)}|Avg={fmt_n(m['avg_pnl'],2)}|"
            f"Ann={fmt_n(m['ann_ror'],1)}|DD={fmt_n(m['max_dd'],2)}"
        )


if __name__ == "__main__":
    main()
