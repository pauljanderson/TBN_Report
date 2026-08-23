"""OOS hold-up for true IS-only BRT Paul>=6 AND FIT>=6 AND robust FIT>=6 cut.

Selection stamp: BRT_Summary_260820002407 (ALL + entry_end_date=2023-12-31).
OOS overlay: full-history ALL Closed (prefer 260819234529).

Research-only. Does not replace drive/universes/BRT_universe.csv. Not DailyRun.
"""
from __future__ import annotations

import csv
import math
import sys
from collections import Counter, defaultdict
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

OUT = ROOT / "drive" / "paul_experiments" / "brt_is_paul6_fit6_20260820"
SUMMARY_IS = ROOT / "drive" / "BRT_Summary_260820002407.csv"
REPORT_IS = ROOT / "drive" / "BRT_Report_260820002407.csv"
AUDIT_IS = ROOT / "drive" / "BRT_Audit_Report_260820002407.csv"
CLOSED_IS = ROOT / "drive" / "BRT_Closed_260820002407.csv"
CLOSED_FULL = ROOT / "drive" / "BRT_Closed_260819234529.csv"
SUMMARY_FULL = ROOT / "drive" / "BRT_Summary_260819234529.csv"
UNIV_42 = ROOT / "drive" / "universes" / "BRT_universe.csv"
FREEZE_CSV = ROOT / "drive" / "universes" / "BRT_is_paul6_fit6_260820002407.csv"
PRIOR_P8_CSV = ROOT / "drive" / "universes" / "BRT_is_paul8_fit6_260820002407.csv"

STAMP_ID = "260820002407"
FULL_STAMP = "260819234529"

# User paste (claimed Paul>=6 AND FIT>=6 AND robust>=6 from 260820002407)
USER_TYPED = [
    "AAON", "ABG", "ACA", "ACAD", "ACLS", "ACU", "ADBE", "ADSK", "AEIS", "AER",
    "AFL", "AFRM", "AGM", "AGYS", "AI", "AIG", "AIR", "ALFVY", "ALGN", "ALNT",
    "AMAT", "AMD", "AMZN", "ANET", "ANF", "APPS", "ARGX", "ARIS", "ATLC", "AVAV",
    "AVGO", "AXON", "BAC", "BELFB", "BFC", "BKNG", "BLDR", "BXMT", "CASH", "CBRE",
    "CDNS", "CE", "CECO", "CGC", "CHDN", "CHTR", "CI", "CLF", "CMG", "CNC",
    "COKE", "COO", "COR", "CORT", "CPA", "CRM", "CRUS", "CSX", "CUBE", "CVCO",
    "CZR", "DHI", "DHT", "DKNG", "DKS", "DOCN", "DPZ", "DRD", "DSGX", "DVA",
    "DY", "ENPH", "ENVA", "EQIX", "ESOA", "EVR", "EXLS", "EXR", "EXTR", "FBP",
    "FHB", "FIVN", "FIX", "FLEX", "FNF", "FNV", "FOX", "FUNC", "GNRC", "GOOG",
    "GRMN", "GSHD", "HALO", "HCI", "HPQ", "HUBS", "IBP", "INOD", "INTU", "IPAR",
    "IR", "IRMD", "ITT", "ITW", "JOE", "KEYS", "LAD", "LBRT", "LEN", "LHX",
    "LINC", "LITE", "LPG", "LRCX", "LUGDF", "LUV", "MCRI", "MELI", "META", "MLI",
    "MLM", "MOH", "MOS", "MPC", "MPWR", "MRVL", "MSFT", "MYRG", "NDSN", "NE",
    "NET", "NFLX", "NMIH", "NOW", "NUE", "NVDA", "NVR", "NXPI", "NXST", "ODFL",
    "OMAB", "ON", "ONDS", "ONTO", "P", "PATK", "PCAR", "PDEX", "PENN", "PFSI",
    "PH", "PHM", "PIPR", "PLUS", "PODD", "PTC", "PVH", "RBC", "RCMT", "RDNT",
    "REAL", "REGN", "RNG", "RNMBY", "ROK", "SAIA", "SANM", "SCCO", "SE", "SHOO",
    "SIMO", "SKYW", "SMID", "SNDX", "SNEX", "SOFI", "SRPT", "SSNC", "SSRM", "STLD",
    "STRL", "STX", "SUPN", "TBBK", "TCI", "TDG", "TEAM", "TEL", "TENB", "TKO",
    "TMUS", "TSCO", "TSEM", "TSLA", "TT", "TTWO", "UAL", "UHS", "UNM", "URI",
    "UTI", "VRT", "VRTX", "VSEC", "WDAY", "WINA", "WSM", "WWD", "XPO", "YETI",
    "ZETA", "ZS",
]

HOLD_CUT = datetime(2024, 1, 1)
SHEET = 47_500.0
INITIAL = 500_000.0
EXPECTED_END = "2023-12-31"

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


def normalize_ymd(raw: str) -> str:
    raw = (raw or "").strip()
    digits = raw.replace("-", "")[:8]
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def load_closed(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            opened = parse_dt(r.get("DATE_OPENED") or "")
            closed = parse_dt(r.get("DATE_CLOSED") or "")
            rows.append(
                {
                    "sym": (r.get("SYMBOL") or "").strip().upper(),
                    "opened": opened,
                    "closed": closed,
                    "pnl": parse_number(r.get("PNL_PCT")),
                    "pnl_d": parse_number(r.get("PNL_DOLLARS")),
                    "days": parse_number(r.get("DAYS_HELD")),
                    "r": parse_number(r.get("R_MULT")),
                    "exit": (r.get("EXIT_TYPE") or "").strip(),
                }
            )
    return rows


def load_summary(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_entry_end(path: Path) -> str:
    if not path.exists():
        return ""
    rep = list(csv.DictReader(path.open(encoding="utf-8-sig")))[0]
    return str(rep.get("entry_end_date") or "").strip()


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


def pass_p6_fit6(r: dict) -> bool:
    p = paul(r)
    fs = fit_score(r)
    fr = fit_robust(r)
    return (
        (p is not None and p >= 6)
        and (fs is not None and fs >= 6)
        and (fr is not None and fr >= 6)
    )


def pass_p8_fit6(r: dict) -> bool:
    p = paul(r)
    fs = fit_score(r)
    fr = fit_robust(r)
    return (
        (p is not None and p >= 8)
        and (fs is not None and fs >= 6)
        and (fr is not None and fr >= 6)
    )


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
    wr = 100.0 * len(wins_p) / n if n else float("nan")
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
        c[t["exit"] or "UNKNOWN"] += 1
    return c


def slice_syms(closed, names):
    want = set(names)
    return [t for t in closed if t["sym"] in want]


def dlt(a, b):
    if a is None or b is None:
        return float("nan")
    if isinstance(a, float) and not math.isfinite(a):
        return float("nan")
    if isinstance(b, float) and not math.isfinite(b):
        return float("nan")
    return a - b


def decide_verdict(m_cand_oos, m_cand_is, m_42_oos, leak_n: int) -> tuple[str, str]:
    """Research-sleeve verdict. Leak noted; KEEP/HOLD/DISMISS from OOS quality vs IS and vs 42."""
    leak_note = (
        f" Selection stamp still has {leak_n} DATE_OPENED>=2024-01-01 leak(s) "
        "(same as prior Paul8 v2 note) — label selection imperfect; OOS report-only."
        if leak_n
        else ""
    )
    if not m_cand_oos or m_cand_oos["n"] == 0:
        return "HOLD", "OOS N collapsed / empty — research sleeve only; do not promote." + leak_note

    soft_vs_is = False
    worse_vs_is = False
    if m_cand_is and m_cand_is["n"] > 0:
        if (m_cand_oos["avg_pnl"] < m_cand_is["avg_pnl"] - 0.5) or (
            m_cand_oos["pf"] < m_cand_is["pf"] - 0.15
        ) or (m_cand_oos["wr"] < m_cand_is["wr"] - 3.0):
            soft_vs_is = True
        if (m_cand_oos["avg_pnl"] < m_cand_is["avg_pnl"] - 2.0) or (
            m_cand_oos["pf"] < m_cand_is["pf"] - 0.4
        ) or (m_cand_oos["wr"] < m_cand_is["wr"] - 8.0):
            worse_vs_is = True

    soft_vs_42 = False
    worse_vs_42 = False
    if m_42_oos and m_42_oos["n"] > 0:
        if (m_cand_oos["avg_pnl"] < m_42_oos["avg_pnl"] - 0.25) or (
            m_cand_oos["pf"] < m_42_oos["pf"] - 0.1
        ) or (m_cand_oos["wr"] < m_42_oos["wr"] - 2.0):
            soft_vs_42 = True
        if (m_cand_oos["avg_pnl"] < m_42_oos["avg_pnl"] - 1.5) or (
            m_cand_oos["pf"] < m_42_oos["pf"] - 0.35
        ) or (m_cand_oos["wr"] < m_42_oos["wr"] - 6.0):
            worse_vs_42 = True

    if worse_vs_is or worse_vs_42:
        return (
            "DISMISS",
            "OOS clearly worse vs IS and/or vs 42 overlay on quality — research discard; house stays 42."
            + leak_note,
        )
    if soft_vs_is or soft_vs_42:
        return (
            "HOLD",
            "OOS softens vs IS and/or vs 42 overlay — research sleeve only; OOS report-only; do not retune."
            + leak_note,
        )

    n_ok = m_cand_oos["n"] >= max(30, int(0.15 * (m_cand_is["n"] if m_cand_is else 100)))
    if n_ok and m_cand_oos["avg_pnl"] > 0 and m_cand_oos["pf"] >= 1.0:
        return (
            "LEAN KEEP",
            "OOS holds quality without collapsing N — research-only lean keep; not house replace; not gold."
            + leak_note,
        )
    return (
        "HOLD",
        "OOS mixed / inconclusive — research sleeve only; do not replace BRT_universe.csv." + leak_note,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    user = list(dict.fromkeys(USER_TYPED))
    user_set = set(user)
    n_user = len(user)

    sum_is = load_summary(SUMMARY_IS)
    sum_full = load_summary(SUMMARY_FULL) if SUMMARY_FULL.exists() else []
    n_sum = len(sum_is)
    sum_cols = list(sum_is[0].keys()) if sum_is else []

    def by_sym(rows):
        return {(r.get("SYMBOL") or "").strip().upper(): r for r in rows}

    is_by = by_sym(sum_is)
    full_by = by_sym(sum_full)

    fit6_all = [r for r in sum_is if pass_p6_fit6(r)]
    fit6_syms = [(r.get("SYMBOL") or "").strip().upper() for r in fit6_all]
    fit6_set = set(fit6_syms)
    p6_all = [r for r in sum_is if (paul(r) or -1) >= 6]
    p6_set = {(r.get("SYMBOL") or "").strip().upper() for r in p6_all}
    p8_fit6_disk = {(r.get("SYMBOL") or "").strip().upper() for r in sum_is if pass_p8_fit6(r)}

    extra = sorted(fit6_set - user_set)
    missing = [s for s in user if s not in fit6_set]
    exact = (not extra) and (not missing)
    sorted_match = user == sorted(fit6_set)
    order_file = user == fit6_syms

    # Primary sleeve = true disk AND-cut (paste may be supersized)
    sleeve = fit6_syms
    sleeve_set = fit6_set
    n_sleeve = len(sleeve)

    miss_why = []
    for s in missing[:25]:
        r = is_by.get(s)
        if not r:
            miss_why.append(f"{s}: not on Summary")
            continue
        miss_why.append(
            f"{s}: PAUL={paul(r)} FIT={fit_score(r)} ROB={fit_robust(r)}"
        )
    if len(missing) > 25:
        miss_why.append(f"... +{len(missing) - 25} more")

    closed_is_stamp = load_closed(CLOSED_IS)
    opens_is = [t["opened"] for t in closed_is_stamp if t["opened"]]
    oos_on_is_stamp = sum(1 for d in opens_is if d >= HOLD_CUT)
    max_open_is = max(opens_is).date().isoformat() if opens_is else "—"
    min_open_is = min(opens_is).date().isoformat() if opens_is else "—"

    cnt = defaultdict(lambda: {"is": 0, "oos": 0, "full": 0})
    for t in closed_is_stamp:
        if not t["opened"]:
            continue
        cnt[t["sym"]]["full"] += 1
        if t["opened"] < HOLD_CUT:
            cnt[t["sym"]]["is"] += 1
        else:
            cnt[t["sym"]]["oos"] += 1
    match_full = match_is_only = 0
    for s, r in is_by.items():
        t = int(parse_number(r.get("TRADES")) or 0)
        if t == cnt[s]["full"]:
            match_full += 1
        if t == cnt[s]["is"]:
            match_is_only += 1

    entry_end_report = read_entry_end(REPORT_IS)
    entry_end_audit = read_entry_end(AUDIT_IS)
    entry_end_norm = normalize_ymd(entry_end_report)
    entry_end_ok = entry_end_norm == EXPECTED_END and normalize_ymd(
        entry_end_audit or entry_end_report
    ) == EXPECTED_END
    digits = entry_end_report.replace("-", "")[:8]
    entry_end_8ok = len(digits) == 8 and digits.isdigit() and digits == "20231231"

    leak_rows = [
        t for t in closed_is_stamp if t["opened"] is not None and t["opened"] >= HOLD_CUT
    ]
    leak_syms = sorted({t["sym"] for t in leak_rows})
    is_only_claim_ok = oos_on_is_stamp == 0 and max_open_is <= EXPECTED_END

    score_diffs = 0
    for s in sorted(set(is_by) | set(full_by)):
        a, b = is_by.get(s), full_by.get(s)
        if not a or not b:
            continue
        if (
            paul(a),
            fit_score(a),
            fit_robust(a),
            parse_number(a.get("TRADES")),
        ) != (
            paul(b),
            fit_score(b),
            fit_robust(b),
            parse_number(b.get("TRADES")),
        ):
            score_diffs += 1

    closed_full = load_closed(CLOSED_FULL) if CLOSED_FULL.exists() else closed_is_stamp
    closed_src = FULL_STAMP if CLOSED_FULL.exists() else STAMP_ID
    opens_full = [t["opened"] for t in closed_full if t["opened"]]
    oos_on_full = sum(1 for d in opens_full if d >= HOLD_CUT)
    max_open_full = max(opens_full).date().isoformat() if opens_full else "—"

    frozen_missing = sorted(sleeve_set - {t["sym"] for t in closed_full})

    prior55 = set(load_syms(PRIOR_P8_CSV)) if PRIOR_P8_CSV.exists() else set(p8_fit6_disk)
    if not prior55:
        prior55 = set(p8_fit6_disk)
    only_wider = sorted(sleeve_set - prior55)
    only_p8 = sorted(prior55 - sleeve_set)
    both_cuts = sorted(sleeve_set & prior55)

    dp42 = set(load_syms(UNIV_42))
    overlap_42 = [s for s in sleeve if s in dp42]
    only_fit6 = sorted(sleeve_set - dp42)
    only_42 = sorted(dp42 - sleeve_set)

    book_cand = f"IS-cut Paul6+FIT6 ({n_sleeve}) FULL Closed"
    book_paste = f"User paste ({n_user}) FULL Closed"
    book_p8 = f"Prior Paul8+FIT6 ({len(prior55)}) FULL Closed"
    book_42 = "42 production slice of FULL Closed"
    book_all = "ALL FULL Closed"
    books = {
        book_cand: slice_syms(closed_full, sleeve_set),
        book_p8: slice_syms(closed_full, prior55),
        book_42: slice_syms(closed_full, dp42),
        book_all: closed_full,
    }
    if not exact:
        books[book_paste] = slice_syms(closed_full, user_set)

    metric_rows = []
    for name, trades in books.items():
        sp = split_book(trades)
        for split, tr in sp.items():
            st = stats(tr)
            metric_rows.append({"book": name, "split": split.upper(), **st})

    sel_slice = slice_syms(closed_is_stamp, sleeve_set)
    m_sel_all = stats(sel_slice)
    m_sel_is = stats([t for t in sel_slice if t["opened"] and t["opened"] < HOLD_CUT])
    metric_rows.append(
        {
            "book": f"Selection Closed {STAMP_ID} (disk AND {n_sleeve})",
            "split": "ALL(=IS)",
            **m_sel_all,
        }
    )

    def find_m(book, split):
        for m in metric_rows:
            if m["book"] == book and m["split"] == split:
                return m
        return None

    m_c_oos = find_m(book_cand, "OOS")
    m_c_is = find_m(book_cand, "IS")
    m_c_full = find_m(book_cand, "FULL")
    m_p8_oos = find_m(book_p8, "OOS")
    m_p8_is = find_m(book_p8, "IS")
    m_p8_full = find_m(book_p8, "FULL")
    m_42_oos = find_m(book_42, "OOS")
    m_42_is = find_m(book_42, "IS")
    m_42_full = find_m(book_42, "FULL")
    m_all_oos = find_m(book_all, "OOS")
    m_all_is = find_m(book_all, "IS")
    m_all_full = find_m(book_all, "FULL")
    m_paste_oos = find_m(book_paste, "OOS") if not exact else None
    m_paste_is = find_m(book_paste, "IS") if not exact else None

    verdict, verdict_why = decide_verdict(m_c_oos, m_c_is, m_42_oos, oos_on_is_stamp)

    cand_trades = slice_syms(closed_full, sleeve_set)
    cand_split = split_book(cand_trades)
    mix_full = exit_mix(cand_split["full"])
    mix_oos = exit_mix(cand_split["oos"])

    def avg_pnl(trs):
        pn = [t["pnl"] for t in trs if t["pnl"] is not None]
        return sum(pn) / len(pn) if pn else None

    by_name_split = {}
    for t in cand_trades:
        d = by_name_split.setdefault(t["sym"], {"is": [], "oos": [], "full": []})
        d["full"].append(t)
        if t["opened"] and t["opened"] < HOLD_CUT:
            d["is"].append(t)
        elif t["opened"]:
            d["oos"].append(t)

    FREEZE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with FREEZE_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL"])
        for s in sleeve:
            w.writerow([s])

    honesty = (
        f"Report entry_end_date raw=`{entry_end_report}` (norm={entry_end_norm}); "
        f"Audit raw=`{entry_end_audit}`. Expected `{EXPECTED_END}`. "
        f"entry_end_ok={entry_end_ok}; 8-digit valid={entry_end_8ok}. "
        f"Closed stamp entries: {min_open_is}->{max_open_is}; OOS entries on stamp Closed: {oos_on_is_stamp} "
        f"(syms={','.join(leak_syms) or 'none'}). "
        f"Summary TRADES match Closed full-count for {match_full}/{n_sum}; match IS-only for {match_is_only}/{n_sum}. "
        f"Paul/FIT/TRADES vs fulluniv Summary {FULL_STAMP}: score/trade diffs={score_diffs} (expected: IS!=full). "
        f"IS-only Closed claim held={is_only_claim_ok}."
    )

    baseline = f"""# BASELINE — OOS hold-up: true IS-only Paul>=6 AND FIT>=6 AND robust FIT>=6 — brt_is_paul6_fit6_20260820

**Do not use as the BRT universe. Do not replace `drive/universes/BRT_universe.csv`. Not gold. Not DailyRun.**

## Selection stamp

- Stamp id: **`{STAMP_ID}`**
- Summary: `drive/BRT_Summary_{STAMP_ID}.csv` (ALL, **{n_sum}** traded names)
- Report: `drive/BRT_Report_{STAMP_ID}.csv` — `entry_end_date` raw = `{entry_end_report}` (norm `{entry_end_norm}`)
- Audit: `drive/BRT_Audit_Report_{STAMP_ID}.csv` — `entry_end_date` raw = `{entry_end_audit}`
- Companion Closed stamp: `BRT_Closed_{STAMP_ID}.csv` ({len(closed_is_stamp)} trades; entry range {min_open_is} → {max_open_is})

### Cut verification

- Gate: `PAUL_SCORE>=6` AND `FIT_SCORE>=6` AND `FIT_SCORE_ROBUST>=6`
- Disk AND-cut N: **{n_sleeve}**; paste N: **{n_user}**
- Extra on disk (not in paste): {len(extra)} ({', '.join(extra) or 'none'}); missing vs disk (in paste, fail AND): {len(missing)}
- Exact match: **{exact}**; sorted-set exact: **{sorted_match}**; file-order exact: **{order_file}**
- PAUL>=6 alone: **{len(p6_set)}**
- Missing sample (fail FIT AND): {'; '.join(miss_why) if miss_why else 'none'}
- **Primary research sleeve frozen = disk AND-cut ({n_sleeve})**, not the supersized paste.

### IS-only honesty

{honesty}

Same 2-entry leak note as Paul8 v2 (`DATE_OPENED` on 2024-01-02) still applies to this selection stamp.

### vs prior Paul8+FIT6 (55 from same stamp)

- Prior freeze: `{PRIOR_P8_CSV.as_posix()}` (N={len(prior55)}; disk Paul8 AND={len(p8_fit6_disk)})
- Shared: **{len(both_cuts)}**
- Only in Paul6 AND ({n_sleeve}): **{len(only_wider)}**
- Only in prior Paul8: **{len(only_p8)}** ({', '.join(only_p8) or 'none'})

## OOS overlay source

Primary Closed: `BRT_Closed_{closed_src}.csv` (entries → {max_open_full}; OOS N={oos_on_full}).
Frozen names missing from Closed: {', '.join(frozen_missing) or 'none'}.
Freeze file (research only): `{FREEZE_CSV.as_posix()}`.

Capital: sheet ${SHEET:,.0f}; Max DD $500k seed. IS = entry < 2024-01-01. Overlay ≠ concurrent house equity.

## Selection Closed context (all IS expected)

| Book | N | WR | Avg PnL% | PF | Ann ROR | Max DD | Sheet PnL |
|------|---|----|----------|----|---------|--------|-----------|
| Selection {n_sleeve} on `{STAMP_ID}` | {fmt_n(m_sel_all['n'],0)} | {fmt_n(m_sel_all['wr'],1)} | {fmt_n(m_sel_all['avg_pnl'],2)} | {fmt_n(m_sel_all['pf'],2)} | {fmt_n(m_sel_all['ann_ror'],1)} | {fmt_n(m_sel_all['max_dd'],2)} | {format_money(m_sel_all['sheet_pnl'])} |

KEEP/HOLD/DISMISS judged from **OOS on FULL Closed**, not selection Closed alone.

## Overlap vs production 42

- Production whitelist: **{len(dp42)}**
- Sleeve ∩ 42: **{len(overlap_42)}** ({', '.join(overlap_42) if overlap_42 else 'none'})
- Sleeve not in 42: **{len(only_fit6)}**
- 42 not in sleeve: **{len(only_42)}**

## Headline IS / OOS (canonical overlay on FULL Closed)

| Book | Split | N | WR | Avg PnL% | AvgR | PF | Ann ROR | Max DD | Sheet PnL |
|------|-------|---|----|----------|------|----|---------|--------|-----------|
| Paul6+FIT6 {n_sleeve} | IS | {fmt_n(m_c_is['n'],0) if m_c_is else '—'} | {fmt_n(m_c_is['wr'],1) if m_c_is else '—'} | {fmt_n(m_c_is['avg_pnl'],2) if m_c_is else '—'} | {fmt_n(m_c_is['avg_r'],2) if m_c_is else '—'} | {fmt_n(m_c_is['pf'],2) if m_c_is else '—'} | {fmt_n(m_c_is['ann_ror'],1) if m_c_is else '—'} | {fmt_n(m_c_is['max_dd'],2) if m_c_is else '—'} | {format_money(m_c_is['sheet_pnl']) if m_c_is else '—'} |
| Paul6+FIT6 {n_sleeve} | OOS | {fmt_n(m_c_oos['n'],0) if m_c_oos else '—'} | {fmt_n(m_c_oos['wr'],1) if m_c_oos else '—'} | {fmt_n(m_c_oos['avg_pnl'],2) if m_c_oos else '—'} | {fmt_n(m_c_oos['avg_r'],2) if m_c_oos else '—'} | {fmt_n(m_c_oos['pf'],2) if m_c_oos else '—'} | {fmt_n(m_c_oos['ann_ror'],1) if m_c_oos else '—'} | {fmt_n(m_c_oos['max_dd'],2) if m_c_oos else '—'} | {format_money(m_c_oos['sheet_pnl']) if m_c_oos else '—'} |
| Paul8+FIT6 {len(prior55)} | IS | {fmt_n(m_p8_is['n'],0) if m_p8_is else '—'} | {fmt_n(m_p8_is['wr'],1) if m_p8_is else '—'} | {fmt_n(m_p8_is['avg_pnl'],2) if m_p8_is else '—'} | {fmt_n(m_p8_is['avg_r'],2) if m_p8_is else '—'} | {fmt_n(m_p8_is['pf'],2) if m_p8_is else '—'} | {fmt_n(m_p8_is['ann_ror'],1) if m_p8_is else '—'} | {fmt_n(m_p8_is['max_dd'],2) if m_p8_is else '—'} | {format_money(m_p8_is['sheet_pnl']) if m_p8_is else '—'} |
| Paul8+FIT6 {len(prior55)} | OOS | {fmt_n(m_p8_oos['n'],0) if m_p8_oos else '—'} | {fmt_n(m_p8_oos['wr'],1) if m_p8_oos else '—'} | {fmt_n(m_p8_oos['avg_pnl'],2) if m_p8_oos else '—'} | {fmt_n(m_p8_oos['avg_r'],2) if m_p8_oos else '—'} | {fmt_n(m_p8_oos['pf'],2) if m_p8_oos else '—'} | {fmt_n(m_p8_oos['ann_ror'],1) if m_p8_oos else '—'} | {fmt_n(m_p8_oos['max_dd'],2) if m_p8_oos else '—'} | {format_money(m_p8_oos['sheet_pnl']) if m_p8_oos else '—'} |
| 42 overlay | IS | {fmt_n(m_42_is['n'],0) if m_42_is else '—'} | {fmt_n(m_42_is['wr'],1) if m_42_is else '—'} | {fmt_n(m_42_is['avg_pnl'],2) if m_42_is else '—'} | {fmt_n(m_42_is['avg_r'],2) if m_42_is else '—'} | {fmt_n(m_42_is['pf'],2) if m_42_is else '—'} | {fmt_n(m_42_is['ann_ror'],1) if m_42_is else '—'} | {fmt_n(m_42_is['max_dd'],2) if m_42_is else '—'} | {format_money(m_42_is['sheet_pnl']) if m_42_is else '—'} |
| 42 overlay | OOS | {fmt_n(m_42_oos['n'],0) if m_42_oos else '—'} | {fmt_n(m_42_oos['wr'],1) if m_42_oos else '—'} | {fmt_n(m_42_oos['avg_pnl'],2) if m_42_oos else '—'} | {fmt_n(m_42_oos['avg_r'],2) if m_42_oos else '—'} | {fmt_n(m_42_oos['pf'],2) if m_42_oos else '—'} | {fmt_n(m_42_oos['ann_ror'],1) if m_42_oos else '—'} | {fmt_n(m_42_oos['max_dd'],2) if m_42_oos else '—'} | {format_money(m_42_oos['sheet_pnl']) if m_42_oos else '—'} |
| ALL | IS | {fmt_n(m_all_is['n'],0) if m_all_is else '—'} | {fmt_n(m_all_is['wr'],1) if m_all_is else '—'} | {fmt_n(m_all_is['avg_pnl'],2) if m_all_is else '—'} | {fmt_n(m_all_is['avg_r'],2) if m_all_is else '—'} | {fmt_n(m_all_is['pf'],2) if m_all_is else '—'} | {fmt_n(m_all_is['ann_ror'],1) if m_all_is else '—'} | {fmt_n(m_all_is['max_dd'],2) if m_all_is else '—'} | {format_money(m_all_is['sheet_pnl']) if m_all_is else '—'} |
| ALL | OOS | {fmt_n(m_all_oos['n'],0) if m_all_oos else '—'} | {fmt_n(m_all_oos['wr'],1) if m_all_oos else '—'} | {fmt_n(m_all_oos['avg_pnl'],2) if m_all_oos else '—'} | {fmt_n(m_all_oos['avg_r'],2) if m_all_oos else '—'} | {fmt_n(m_all_oos['pf'],2) if m_all_oos else '—'} | {fmt_n(m_all_oos['ann_ror'],1) if m_all_oos else '—'} | {fmt_n(m_all_oos['max_dd'],2) if m_all_oos else '—'} | {format_money(m_all_oos['sheet_pnl']) if m_all_oos else '—'} |

See `compare.html`.

## Selection honesty

Post-hoc DualPaul-style AND on Summary already seen = **in-sample winner-cut**. OOS is report-only — do not retune OOS. Do not overwrite `BRT_universe.csv`.

## Verdict: **{verdict} as research sleeve** (not house replace)

{verdict_why}

House BRT remains the 42-name production whitelist.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")
    (OUT / "AB_PLAN.md").write_text(
        f"""# AB_PLAN — brt_is_paul6_fit6_20260820 (research-only OOS hold-up)

**Hypothesis (universe sleeve):** Names passing PAUL>=6 AND FIT>=6 AND robust FIT>=6 on true IS-only ALL Summary `{STAMP_ID}` hold OOS quality on full-history Closed (research sleeve; not house replace). Wider than prior Paul8+FIT6 (55).

**Control:** `drive/universes/BRT_universe.csv` (42) on same FULL Closed `{closed_src}`.

**Candidate:** Disk AND-cut N={n_sleeve} on Summary `{STAMP_ID}` (paste was {n_user}; exact={exact}).

**Comparator:** Prior Paul8+FIT6 freeze ({len(prior55)}).

**OOS:** report-only. Do not retune. Do not replace `BRT_universe.csv`. Do not DailyRun-wire.

**Judge:** quality (WR, Avg PnL%, AvgR, PF, Ann ROR, Max DD, sheet PnL). OOS softens or trails 42 → HOLD/DISMISS; holds without N collapse → LEAN KEEP research-only.

**Verdict:** {verdict} as research sleeve.
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

    delta_pairs = [
        (f"Paul6+FIT6 {n_sleeve} vs 42 OOS", m_c_oos, m_42_oos),
        (f"Paul6+FIT6 {n_sleeve} vs 42 IS", m_c_is, m_42_is),
        (f"Paul6+FIT6 {n_sleeve} vs Paul8+FIT6 OOS", m_c_oos, m_p8_oos),
        (f"Paul6+FIT6 {n_sleeve} vs Paul8+FIT6 IS", m_c_is, m_p8_is),
        (f"Paul6+FIT6 {n_sleeve} vs ALL OOS", m_c_oos, m_all_oos),
        (f"Paul6+FIT6 {n_sleeve} vs ALL IS", m_c_is, m_all_is),
        (f"Paul6+FIT6 {n_sleeve} OOS vs IS (self)", m_c_oos, m_c_is),
        ("Paul8+FIT6 OOS vs IS (self)", m_p8_oos, m_p8_is),
        ("42 OOS vs IS (self)", m_42_oos, m_42_is),
    ]
    if m_paste_oos and m_paste_is:
        delta_pairs.insert(0, (f"Paste {n_user} vs disk AND {n_sleeve} OOS", m_paste_oos, m_c_oos))
        delta_pairs.insert(1, (f"Paste {n_user} vs disk AND {n_sleeve} IS", m_paste_is, m_c_is))

    delta_head = "".join(
        sortable_th(lab, typ)
        for lab, typ in [
            ("Compare", "text"),
            ("Δ N", "num"),
            ("Δ Win %", "num"),
            ("Δ Avg PnL %", "num"),
            ("Δ WO_MAX", "num"),
            ("Δ Avg R", "num"),
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
            f"{td_num(dlt(cand['avg_r'], ctrl['avg_r']), 2)}"
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
            ("PAUL_SCORE", "num"),
            ("FIT_SCORE", "num"),
            ("FIT_SCORE_ROBUST", "num"),
            ("FIT tier", "text"),
            ("In 42 whitelist", "text"),
            ("In prior Paul8+FIT6", "text"),
            ("IS N", "num"),
            ("OOS N", "num"),
            ("IS Avg PnL %", "num"),
            ("OOS Avg PnL %", "num"),
        ]
    )
    name_body = []
    for s in sleeve:
        sr = is_by.get(s, {})
        parts = by_name_split.get(s, {"is": [], "oos": []})
        name_body.append(
            "<tr>"
            f"<td>{escape(s)}</td>"
            f"{td_num(paul(sr), 0)}"
            f"{td_num(fit_score(sr), 0)}"
            f"{td_num(fit_robust(sr), 0)}"
            f"<td>{escape(str(sr.get('FIT') or ''))}</td>"
            f"<td>{'Y' if s in dp42 else 'N'}</td>"
            f"<td>{'Y' if s in prior55 else 'N'}</td>"
            f"{td_num(len(parts.get('is') or []), 0)}"
            f"{td_num(len(parts.get('oos') or []), 0)}"
            f"{td_num(avg_pnl(parts.get('is') or []), 2)}"
            f"{td_num(avg_pnl(parts.get('oos') or []), 2)}"
            "</tr>"
        )

    mix_keys = sorted(set(mix_full) | set(mix_oos))
    mix_body = []
    n_full = max(len(cand_split["full"]), 1)
    n_oos_m = max(len(cand_split["oos"]), 1)
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

    yes_no = "Yes — exact match" if exact else "No — paste is NOT the disk AND-cut"
    verdict_color = {
        "LEAN KEEP": ("#166534", "#f0fdf4"),
        "HOLD": ("#92400e", "#fffbeb"),
        "DISMISS": ("#991b1b", "#fef2f2"),
    }.get(verdict, ("#92400e", "#fffbeb"))
    border, bg = verdict_color

    leak_detail = ", ".join(
        f"{t['sym']}@{t['opened'].date().isoformat()}" for t in leak_rows
    ) or "none"
    is_claim_html = (
        f"<p><strong>IS-only leak (same as Paul8 v2):</strong> Report/Audit "
        f"<code>entry_end_date</code>=<code>{escape(entry_end_norm)}</code> typed ok, "
        f"but stamp Closed has <strong>{oos_on_is_stamp}</strong> entries with "
        f"DATE_OPENED>=2024-01-01 (max={escape(max_open_is)}): {escape(leak_detail)}. "
        f"Summary TRADES match IS-only {match_is_only}/{n_sum}. "
        f"OOS overlay uses FULL Closed <code>{escape(closed_src)}</code>.</p>"
    )

    paste_note = ""
    if not exact:
        paste_note = (
            f"<p><strong>Paste mismatch:</strong> typed {n_user} names; disk AND = {n_sleeve}. "
            f"Extras on disk={len(extra)}; paste-not-AND={len(missing)} "
            f"(mostly PAUL>=6 but FIT/robust &lt;6). "
            f"Primary sleeve = <strong>disk AND {n_sleeve}</strong>. "
            f"Paste-as-typed also shown in metrics for honesty.</p>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>BRT IS-only Paul>=6+FIT>=6 OOS hold-up — {STAMP_ID}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1400px; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.12rem; margin-top: 28px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
.verdict {{ border: 2px solid {border}; background: {bg}; }}
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
<h1>OOS hold-up — true IS-only Paul>=6 AND FIT>=6 AND robust FIT>=6</h1>
<p class="sub"><strong>{escape(yes_no)}</strong> on Summary <code>{STAMP_ID}</code>
({n_sum} names). Gate: <code>PAUL_SCORE&gt;=6</code> and <code>FIT_SCORE&gt;=6</code> and
<code>FIT_SCORE_ROBUST&gt;=6</code>. Click column headers to sort. Research sleeve only —
<code>BRT_universe.csv</code> not edited.</p>
<div class="card verdict">
<h2>Verdict: {escape(verdict)} as research sleeve (not house replace)</h2>
<p>{escape(verdict_why)}</p>
<p>Label: IS-only cut from <code>{STAMP_ID}</code>; OOS report-only on FULL Closed <code>{escape(closed_src)}</code>. Not gold. Not DailyRun.</p>
</div>
<div class="card">
<p><strong>Paste:</strong> {n_user} names. Disk AND-cut N=<strong>{n_sleeve}</strong>.
Extra={len(extra)} ({escape(', '.join(extra) or 'none')}); missing={len(missing)}.
Sorted-set exact={sorted_match}; file-order exact={order_file}.
PAUL>=6 alone={len(p6_set)}. Prior Paul8+FIT6={len(prior55)} (shared={len(both_cuts)}; only wider={len(only_wider)}).</p>
{paste_note}
{is_claim_html}
<p><strong>Overlap 42:</strong> {len(overlap_42)} / {n_sleeve}
({escape(', '.join(overlap_42) if overlap_42 else 'none')}).
42 not in sleeve: {len(only_42)}. Freeze CSV: <code>{escape(FREEZE_CSV.as_posix())}</code>.</p>
</div>
<h2>Closed overlay IS / OOS (canonical quality)</h2>
<p class="small">Primary = FULL Closed <code>{escape(closed_src)}</code> sliced to Paul6+FIT6 {n_sleeve} / Paul8+FIT6 / 42 / ALL.
Selection Closed <code>{STAMP_ID}</code> row is context. Sheet ${SHEET:,.0f}; Max DD on $500k seed.
Judge KEEP/HOLD/DISMISS from OOS on FULL Closed (disk AND sleeve).</p>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{metric_head}</tr></thead>
<tbody>
{''.join(metric_body)}
</tbody>
</table>
<table class="sortable">
<caption>Deltas (same FULL Closed). Click headers to sort.</caption>
<thead><tr>{delta_head}</tr></thead>
<tbody>{''.join(delta_body)}</tbody>
</table>
<p class="small">Headline OOS Avg PnL%: Paul6 {fmt_n(m_c_oos['avg_pnl'] if m_c_oos else None, 2)}
vs Paul8 {fmt_n(m_p8_oos['avg_pnl'] if m_p8_oos else None, 2)}
vs 42 {fmt_n(m_42_oos['avg_pnl'] if m_42_oos else None, 2)}
vs ALL {fmt_n(m_all_oos['avg_pnl'] if m_all_oos else None, 2)}.
IS Avg PnL%: Paul6 {fmt_n(m_c_is['avg_pnl'] if m_c_is else None, 2)}
vs Paul8 {fmt_n(m_p8_is['avg_pnl'] if m_p8_is else None, 2)}
vs 42 {fmt_n(m_42_is['avg_pnl'] if m_42_is else None, 2)}
vs ALL {fmt_n(m_all_is['avg_pnl'] if m_all_is else None, 2)}.
OOS WR: Paul6 {fmt_n(m_c_oos['wr'] if m_c_oos else None, 1)} vs Paul8 {fmt_n(m_p8_oos['wr'] if m_p8_oos else None, 1)} vs 42 {fmt_n(m_42_oos['wr'] if m_42_oos else None, 1)}.
OOS PF: Paul6 {fmt_n(m_c_oos['pf'] if m_c_oos else None, 2)} vs Paul8 {fmt_n(m_p8_oos['pf'] if m_p8_oos else None, 2)} vs 42 {fmt_n(m_42_oos['pf'] if m_42_oos else None, 2)}.
OOS Ann ROR: Paul6 {fmt_n(m_c_oos['ann_ror'] if m_c_oos else None, 1)} vs Paul8 {fmt_n(m_p8_oos['ann_ror'] if m_p8_oos else None, 1)} vs 42 {fmt_n(m_42_oos['ann_ror'] if m_42_oos else None, 1)}.
OOS Max DD: Paul6 {fmt_n(m_c_oos['max_dd'] if m_c_oos else None, 2)} vs Paul8 {fmt_n(m_p8_oos['max_dd'] if m_p8_oos else None, 2)} vs 42 {fmt_n(m_42_oos['max_dd'] if m_42_oos else None, 2)}.
FULL N: Paul6={fmt_n(m_c_full['n'] if m_c_full else None, 0)},
Paul8={fmt_n(m_p8_full['n'] if m_p8_full else None, 0)},
42={fmt_n(m_42_full['n'] if m_42_full else None, 0)}, ALL={fmt_n(m_all_full['n'] if m_all_full else None, 0)}.
Selection Closed {n_sleeve}: N={fmt_n(m_sel_all['n'],0)} Avg={fmt_n(m_sel_all['avg_pnl'],2)} WR={fmt_n(m_sel_all['wr'],1)}
(IS-only slice N={fmt_n(m_sel_is['n'],0)}).</p>
<h2>Exit mix (Paul6+FIT6 {n_sleeve} of FULL Closed)</h2>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{sortable_th('EXIT_TYPE','text')}{sortable_th('FULL N','num')}{sortable_th('FULL %','num')}{sortable_th('OOS N','num')}{sortable_th('OOS %','num')}</tr></thead>
<tbody>{''.join(mix_body)}</tbody>
</table>
<h2>Frozen names (disk AND) — scores + Closed IS/OOS</h2>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{name_head}</tr></thead>
<tbody>
{''.join(name_body)}
</tbody>
</table>
<p class="small">See BASELINE.md. House BRT remains the 42-name production whitelist. Columns on Summary: {escape(', '.join(sum_cols))}.</p>
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

    print("SUMMARY", n_sum, "AND_CUT", n_sleeve, "USER", n_user)
    print("EXACT", exact, "SORTED", sorted_match, "FILE_ORDER", order_file)
    print("EXTRA", len(extra), "MISSING", len(missing))
    print("ENTRY_END_REPORT", entry_end_report, "AUDIT", entry_end_audit, "OK", entry_end_ok, "8DIG", entry_end_8ok)
    print("OOS_ON_IS_STAMP", oos_on_is_stamp, "MAX_OPEN_IS", max_open_is)
    print("LEAKS", [(t["sym"], t["opened"].date().isoformat()) for t in leak_rows])
    print("MATCH_FULL", match_full, "MATCH_IS", match_is_only, "SCORE_DIFFS", score_diffs)
    print("PRIOR55", len(prior55), "SHARED", len(both_cuts), "ONLY_WIDER", len(only_wider), "ONLY_P8", only_p8)
    print("CLOSED_SRC", closed_src, "OOS_FULL", oos_on_full)
    print("OVERLAP_42", len(overlap_42), overlap_42)
    print("VERDICT", verdict)
    print("HTML", html_path)
    print("FREEZE", FREEZE_CSV)
    for m in metric_rows:
        print(
            f"{m['book']}|{m['split']}|names={m['n_names']}|N={m['n']}|"
            f"WR={fmt_n(m['wr'],1)}|Avg={fmt_n(m['avg_pnl'],2)}|"
            f"AvgR={fmt_n(m['avg_r'],2)}|PF={fmt_n(m['pf'],2)}|"
            f"Ann={fmt_n(m['ann_ror'],1)}|DD={fmt_n(m['max_dd'],2)}|"
            f"Sheet={m['sheet_pnl']:.2f}"
        )


if __name__ == "__main__":
    main()
