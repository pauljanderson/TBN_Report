"""Slice ALL BRT Closed onto post-hoc PAUL_SCORE==8 names from fulluniv Summary 260819234529.

Research-only. Does not replace drive/universes/BRT_universe.csv. Not DailyRun.
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

OUT = ROOT / "drive" / "paul_experiments" / "brt_paul8_fulluniv_20260819"
SUMMARY_ALL = ROOT / "drive" / "BRT_Summary_260819234529.csv"
SUMMARY_764 = ROOT / "drive" / "BRT_Summary_260819133252.csv"
SUMMARY_42 = ROOT / "drive" / "BRT_Summary_260819183616.csv"
UNIV_42 = ROOT / "drive" / "universes" / "BRT_universe.csv"
UNIV_764 = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CLOSED_ALL = ROOT / "drive" / "BRT_Closed_260819234529.csv"
CLOSED_764 = ROOT / "drive" / "BRT_Closed_260819133252.csv"
CLOSED_42 = ROOT / "drive" / "BRT_Closed_260819183616.csv"

USER_TYPED = [
    "AAON", "ADPT", "ALB", "ALGN", "ALNT", "AMAT", "AMD", "AMN", "ANET", "ANIK",
    "APP", "ARGX", "ATEYY", "ATLC", "AU", "AVAV", "BBW", "BKTI", "BLBD", "BLDR",
    "BX", "CAMT", "CGC", "CHCI", "CIEN", "CORT", "CPA", "CZR", "DASH", "DDS",
    "DHI", "DKS", "DRS", "DY", "FTAI", "FTNT", "FUNC", "GFI", "GHM", "GNRC",
    "HOOD", "HUBS", "IBP", "IESC", "IRMD", "LAD", "LITE", "LMB", "LRCX", "LSCC",
    "LUGDF", "MDB", "MOH", "MPWR", "MRVL", "MYRG", "NBIX", "NEM", "NEO", "NET",
    "NFLX", "NGL", "NOW", "NVDA", "NXST", "ONDS", "ONTO", "PDEX", "PFSI", "PLUS",
    "PODD", "PSIX", "RCMT", "RDNT", "REAL", "RMBS", "RNG", "SAIA", "SANM", "SE",
    "SGI", "SOFI", "SRPT", "STLD", "SVM", "TATT", "TAYD", "TEAM", "TGB", "TGLS",
    "THC", "TSEM", "UAL", "URI", "UTI", "VECO", "VLO", "VRT", "WCC", "WLDN",
    "WSM", "XPO", "ZETA", "ZS",
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
    raw = []
    with path.open(encoding="utf-8-sig") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.lstrip().startswith("#"):
                continue
            raw.append(s)
    if not raw:
        return []
    header = raw[0].split(",")[0].strip().upper()
    if header == "SYMBOL":
        out = []
        for row in csv.DictReader(raw):
            s = (row.get("SYMBOL") or "").strip().upper()
            if s:
                out.append(s)
        return out
    return [ln.split(",")[0].strip().upper() for ln in raw if ln.split(",")[0].strip()]


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


def paul_oos(r: dict | None):
    if not r:
        return None
    return parse_number(r.get("PAUL_SCORE_OOS"))


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
        "total_pnl_d": sum(t["pnl_d"] or 0.0 for t in trades),
        "avg_days": avg_days,
        "expectancy_pct": avg_pnl,
        "n_names": len({t["sym"] for t in trades}),
        "avg_win": sum(wins_p) / len(wins_p) if wins_p else float("nan"),
        "avg_loss": sum(loss_p) / len(loss_p) if loss_p else float("nan"),
        "capital_days": cap.get("capital_days", float("nan")),
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
    truncated_paul = "SHEET_PNL" not in sum_cols and "AVG_TRADES_PER_YEAR" not in sum_cols
    has_oos_col = "PAUL_SCORE_OOS" in sum_cols

    def by_sym(rows):
        return {(r.get("SYMBOL") or "").strip().upper(): r for r in rows}

    all_by = by_sym(sum_all)
    s764_by = by_sym(sum_764)
    s42_by = by_sym(sum_42)

    eq8_all = [r for r in sum_all if paul(r) == 8]
    ge8_all = [r for r in sum_all if (paul(r) or -1) >= 8]
    ge7_all = [r for r in sum_all if (paul(r) or -1) >= 7]
    eq8_syms = [(r.get("SYMBOL") or "").strip().upper() for r in eq8_all]
    eq8_set = set(eq8_syms)
    ge8_set = {(r.get("SYMBOL") or "").strip().upper() for r in ge8_all}

    extra_eq8 = sorted(eq8_set - user_set)
    missing_eq8 = [s for s in user if s not in eq8_set]
    order_file = eq8_syms
    order_match = user == order_file
    sorted_match = user == sorted(eq8_set)

    eq8_764 = {(r.get("SYMBOL") or "").strip().upper() for r in sum_764 if paul(r) == 8}
    extra_764 = sorted(eq8_764 - user_set)
    miss_764 = [s for s in user if s not in eq8_764]

    eq8_42 = {(r.get("SYMBOL") or "").strip().upper() for r in sum_42 if paul(r) == 8}

    dp42 = set(load_syms(UNIV_42))
    u764 = set(load_syms(UNIV_764))
    overlap_42 = [s for s in user if s in dp42]
    only_p8 = sorted(user_set - dp42)
    only_42 = sorted(dp42 - user_set)
    in_764 = [s for s in user if s in u764]
    not_764 = [s for s in user if s not in u764]

    closed_all = load_closed(CLOSED_ALL)
    closed_764 = load_closed(CLOSED_764)
    closed_42 = load_closed(CLOSED_42)

    books = {
        "Paul8 ALL slice (260819234529)": slice_syms(closed_all, user_set),
        "42 production slice of ALL Closed": slice_syms(closed_all, dp42),
        "764 tradable slice of ALL Closed": slice_syms(closed_all, u764),
        "ALL Closed (260819234529)": closed_all,
        "42 live Closed (260819183616)": closed_42,
        "764 live Closed (260819133252)": closed_764,
        "Paul8-of-764 slice of 764 Closed": slice_syms(closed_764, eq8_764),
    }

    metric_rows = []
    for name, trades in books.items():
        sp = split_book(trades)
        for split, tr in sp.items():
            st = stats(tr)
            metric_rows.append({"book": name, "split": split.upper(), **st})

    hist = Counter(int(paul(r)) if paul(r) is not None else -99 for r in sum_all)
    hist_764 = Counter(int(paul(r)) if paul(r) is not None else -99 for r in sum_764)
    hist_42 = Counter(int(paul(r)) if paul(r) is not None else -99 for r in sum_42)

    p8_trades = slice_syms(closed_all, user_set)
    p8_split = split_book(p8_trades)
    mix_full = exit_mix(p8_split["full"])
    mix_oos = exit_mix(p8_split["oos"])

    # Per-name IS/OOS from ALL Closed (no PAUL_SCORE_OOS column on BRT Summary)
    def avg_pnl(trs):
        pn = [t["pnl"] for t in trs if t["pnl"] is not None]
        return sum(pn) / len(pn) if pn else None

    by_name_split = {}
    for t in p8_trades:
        d = by_name_split.setdefault(t["sym"], {"is": [], "oos": [], "full": []})
        d["full"].append(t)
        if t["opened"] and t["opened"] < HOLD_CUT:
            d["is"].append(t)
        elif t["opened"]:
            d["oos"].append(t)

    oos_blank_n = sum(1 for s in user if not by_name_split.get(s, {}).get("oos"))
    oos_pos = sum(
        1
        for s in user
        if (avg_pnl(by_name_split.get(s, {}).get("oos") or []) or 0) > 0
    )

    n_user = len(user)

    def find_m(book, split):
        for m in metric_rows:
            if m["book"] == book and m["split"] == split:
                return m
        return None

    m_p8_oos = find_m("Paul8 ALL slice (260819234529)", "OOS")
    m_42_oos = find_m("42 production slice of ALL Closed", "OOS")
    m_764_oos = find_m("764 tradable slice of ALL Closed", "OOS")
    m_all_oos = find_m("ALL Closed (260819234529)", "OOS")
    m_p8_is = find_m("Paul8 ALL slice (260819234529)", "IS")
    m_42_is = find_m("42 production slice of ALL Closed", "IS")
    m_764_is = find_m("764 tradable slice of ALL Closed", "IS")
    m_all_is = find_m("ALL Closed (260819234529)", "IS")

    baseline = f"""# BASELINE — post-hoc Paul==8 sleeve from BRT fulluniv ALL Summary — brt_paul8_fulluniv_20260819

**Do not use as the BRT universe. Do not replace `drive/universes/BRT_universe.csv`. Not gold. Not DailyRun.**

## What the user saw

Source: `drive/BRT_Summary_260819234529.csv` (`run_brt.bat ALL`, **{n_sum}** traded names, freeze = production BRT knobs). Companion Closed `BRT_Closed_260819234529.csv`.

- Integer **PAUL_SCORE == 8**: **{len(eq8_all)}**
- PAUL_SCORE **≥ 8**: **{len(ge8_all)}** (same set — 8 is the ceiling)
- Truncated Paul on this Summary: **{truncated_paul}** (SHEET_PNL / AVG_TRADES_PER_YEAR present → **full 0–8**, not the 5-pt truncated Summary class)
- `PAUL_SCORE_OOS` on Summary: **{has_oos_col}** (BRT does not write `BRT_Summary_Symbols_*`; DualPaul-style AND with OOS Paul cannot be read off this file)
- PAUL_SCORE ≥7 on ALL Summary: **{len(ge7_all)}**

User pasted **{n_user}** names (alpha order). Vs Summary PAUL==8: in both **{n_user - len(missing_eq8)}**; user-not-in-bin **{len(missing_eq8)}**; bin-not-in-user **{len(extra_eq8)}**. File order of ==8 vs paste: **{'exact' if order_match else 'not file-order'}**. Sorted-set vs paste: **{'exact' if sorted_match else 'no'}**.

Not the 764 stamp `260819133252` (Summary n={len(sum_764)}, PAUL==8 n={len(eq8_764)}; paste ∩ that bin = {len(user_set & eq8_764)}; extra on 764==8 = {len(extra_764)}; paste missing from 764==8 = {len(miss_764)}).
Not LatestRun/42 Summary `260819183616` (n={len(sum_42)}, PAUL==8 n={len(eq8_42)}: {', '.join(sorted(eq8_42)) or 'none'}).

## Overlap vs production 42

- Production whitelist `BRT_universe.csv`: **{len(dp42)}** names
- Paul8 ∩ 42: **{len(overlap_42)}** ({', '.join(overlap_42) if overlap_42 else 'none'})
- Paul8 not in 42: **{len(only_p8)}**
- 42 not in Paul8: **{len(only_42)}**
- Tradable 764 ∩ Paul8: **{len(in_764)}**; not in 764: **{len(not_764)}** ({', '.join(not_764)})

## Closed overlay (primary = ALL `260819234529`)

Capital: sheet ${SHEET:,.0f} (stamp `sheet_brt_cash`); Max DD $500k seed. IS = entry < 2024-01-01. Overlay slice ≠ concurrent-position house equity.

Judge overlay quality on WR / Avg PnL% / PF / sheet PnL. Overlay Ann ROR / Max DD on the ALL Closed file use mega-book `PNL_DOLLARS` (not comparable to live 42 Ann ROR / Max DD). Live Closed `260819183616` is the production identity for ROR/DD.

See `compare.html`.

## Selection honesty

Post-hoc integer Paul==8 on the **fulluniv Summary the user already saw** is an **in-sample winner-cut** (same class as DualPaul / IS Paul78). OOS is report-only — do not retune. Do not overwrite `BRT_universe.csv`.

## Verdict: **DISMISS as house universe** (research sleeve only)

Keep house BRT = 42-name production whitelist. Even if overlay OOS looks better than 42, that is expected after picking the top Paul bin on the same tape.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")
    (OUT / "AB_PLAN.md").write_text(
        """# AB_PLAN — brt_paul8_fulluniv_20260819 (research-only)

**Hypothesis (universe, not exit):** After seeing ALL BRT Summary `260819234529`, use PAUL_SCORE==8 names as house BRT universe instead of the 42-name production whitelist.

**Control:** `drive/universes/BRT_universe.csv` (42). Same Closed overlay `BRT_Closed_260819234529.csv` (fair) plus live 42 Closed `260819183616`.

**Candidate:** User typed 104 names = exact PAUL_SCORE==8 on ALL Summary. Post-hoc IS winner-cut. Same class as DualPaul / `vz_is_paul78_20260818` DISMISS.

**OOS:** report-only. Do not retune. Do not replace `BRT_universe.csv`. Do not DailyRun-wire.

**Judge:** quality (WR, Avg PnL%, PF, Ann ROR, Max DD), not trade count.

**Verdict:** DISMISS as house replacement. HOLD/research sleeve only if they want a DualPaul-style BRT cut (still not gold).
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
            ("PF", "num"),
            ("Avg days", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Sheet PnL $", "num"),
            ("Total PnL $", "num"),
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
            f"{td_num(m['pf'], 2)}"
            f"{td_num(m['avg_days'], 1)}"
            f"{td_num(m['ann_ror'], 1)}"
            f"{td_num(m['max_dd'], 2)}"
            f'<td class="num">{format_money(m["sheet_pnl"])}</td>'
            f'<td class="num">{format_money(m["total_pnl_d"])}</td>'
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
        ("Paul8 vs 42 overlay OOS", m_p8_oos, m_42_oos),
        ("Paul8 vs 42 overlay IS", m_p8_is, m_42_is),
        ("Paul8 vs 764 overlay OOS", m_p8_oos, m_764_oos),
        ("Paul8 vs ALL overlay OOS", m_p8_oos, m_all_oos),
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
            ("764 PAUL_SCORE", "num"),
            ("42 PAUL_SCORE", "num"),
            ("In 42 whitelist", "text"),
            ("In 764 tradable", "text"),
            ("IS N", "num"),
            ("OOS N", "num"),
            ("IS Avg PnL %", "num"),
            ("OOS Avg PnL %", "num"),
        ]
    )
    name_body = []
    for s in user:
        sr = all_by.get(s, {})
        r764 = s764_by.get(s, {})
        r42 = s42_by.get(s, {})
        parts = by_name_split.get(s, {"is": [], "oos": []})
        name_body.append(
            "<tr>"
            f"<td>{escape(s)}</td>"
            f"{td_num(paul(sr), 0)}"
            f"{td_num(paul(r764) if r764 else None, 0)}"
            f"{td_num(paul(r42) if r42 else None, 0)}"
            f"<td>{'Y' if s in dp42 else 'N'}</td>"
            f"<td>{'Y' if s in u764 else 'N'}</td>"
            f"{td_num(len(parts.get('is') or []), 0)}"
            f"{td_num(len(parts.get('oos') or []), 0)}"
            f"{td_num(avg_pnl(parts.get('is') or []), 2)}"
            f"{td_num(avg_pnl(parts.get('oos') or []), 2)}"
            "</tr>"
        )

    hist_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist[k], 0)}</tr>'
        for k in sorted(hist)
    )
    hist764_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist_764[k], 0)}</tr>'
        for k in sorted(hist_764)
    )
    hist42_rows = "".join(
        f'<tr><td class="num">{k if k != -99 else "blank"}</td>{td_num(hist_42[k], 0)}</tr>'
        for k in sorted(hist_42)
    )

    mix_keys = sorted(set(mix_full) | set(mix_oos))
    mix_body = []
    n_full = max(len(p8_split["full"]), 1)
    n_oos = max(len(p8_split["oos"]), 1)
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
<title>BRT Paul==8 fulluniv post-hoc slice — 20260819</title>
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
<h1>Is this Paul 8 from the entire BRT universe?</h1>
<p class="sub"><strong>Yes — exact match.</strong> Integer <code>PAUL_SCORE==8</code> on ALL Summary
<code>260819234529</code> ({n_sum} traded names). Full 0–8 (not truncated 5-pt). Not ≥8 vs ==8
(they are the same; ceiling 8). Not <code>PAUL_SCORE_OOS</code> (column absent). Click column headers to sort.</p>
<div class="card verdict">
<h2>Verdict: DISMISS as house universe — do not replace the 42</h2>
<p>Post-hoc winner-cut after seeing fulluniv Summary. Same class as DualPaul / IS Paul78.
House stays 42-name <code>BRT_universe.csv</code> (not DualPaul). Research sleeve only if you want
a DualPaul-style BRT cut — still not gold, not DailyRun. File was not edited.</p>
</div>
<div class="card">
<p><strong>Stamp:</strong> <code>BRT_Summary_260819234529.csv</code> ALL.
PAUL==8 N=<strong>{len(eq8_all)}</strong> = paste N=<strong>{n_user}</strong>.
Extra on disk: {len(extra_eq8) or 0}. Missing from paste vs ==8: {len(missing_eq8) or 0}.
Paste is alphabetical of that bin (sorted-set exact={sorted_match}; file-order exact={order_match}).</p>
<p><strong>Not</strong> 764 honest tape <code>260819133252</code> (PAUL==8 n={len(eq8_764)};
∩ paste={len(user_set & eq8_764)}; extra={len(extra_764)}; paste missing={len(miss_764)}).</p>
<p><strong>Not</strong> production/Latest 42 <code>260819183616</code> (PAUL==8 n={len(eq8_42)}:
{escape(', '.join(sorted(eq8_42)) or 'none')}).</p>
<p><strong>Overlap 42:</strong> {len(overlap_42)} / {n_user}
({escape(', '.join(overlap_42) if overlap_42 else 'none')}).
42 not in Paul8: {len(only_42)}. ∩ tradable 764: {len(in_764)}. Not in 764: {len(not_764)}
({escape(', '.join(not_764))}).</p>
<p><code>PAUL_SCORE_OOS</code> not on BRT Summary / no Summary_Symbols. Names with no OOS trades
on ALL Closed: {oos_blank_n}. Names with OOS avg PnL% &gt; 0: {oos_pos} / {n_user}.</p>
</div>
<h2>Closed overlay IS / OOS (canonical quality)</h2>
<p class="small">Primary = ALL Closed <code>260819234529</code> sliced to Paul8 / 42 / 764 / ALL.
Live 42 <code>260819183616</code> and live 764 <code>260819133252</code> are identity books (different
universe run). Sheet ${SHEET:,.0f}; Max DD on $500k seed. Overlay ≠ concurrent house equity.
<strong>Judge overlay on WR / Avg PnL% / PF / sheet PnL.</strong> Overlay Ann ROR / Max DD use ALL-run
<code>PNL_DOLLARS</code> (tiny per trade vs 200+ concurrent names), so they are not the house 42
Ann ROR (~19% full / ~28% OOS on live Closed). Live-42 rows are the production identity for ROR/DD.</p>
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
<p class="small">Headline OOS Avg PnL%: Paul8 {fmt_n(m_p8_oos['avg_pnl'] if m_p8_oos else None, 2)}
vs 42 overlay {fmt_n(m_42_oos['avg_pnl'] if m_42_oos else None, 2)}
vs 764 overlay {fmt_n(m_764_oos['avg_pnl'] if m_764_oos else None, 2)}
vs ALL {fmt_n(m_all_oos['avg_pnl'] if m_all_oos else None, 2)}.
IS Avg PnL%: Paul8 {fmt_n(m_p8_is['avg_pnl'] if m_p8_is else None, 2)}
vs 42 {fmt_n(m_42_is['avg_pnl'] if m_42_is else None, 2)}
vs 764 {fmt_n(m_764_is['avg_pnl'] if m_764_is else None, 2)}
vs ALL {fmt_n(m_all_is['avg_pnl'] if m_all_is else None, 2)}
(IS lift vs ALL is expected — we picked Summary winners).</p>
<h2>Exit mix (Paul8 slice of ALL Closed)</h2>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>{sortable_th('EXIT_TYPE','text')}{sortable_th('FULL N','num')}{sortable_th('FULL %','num')}{sortable_th('OOS N','num')}{sortable_th('OOS %','num')}</tr></thead>
<tbody>{''.join(mix_body)}</tbody>
</table>
<h2>Typed names — ALL / 764 / 42 Paul + Closed IS/OOS</h2>
<table class="sortable">
<caption>Click column headers to sort. 764/42 Paul blank = name not on that Summary.</caption>
<thead><tr>{name_head}</tr></thead>
<tbody>
{''.join(name_body)}
</tbody>
</table>
<h2>PAUL_SCORE histogram (ALL Summary {n_sum} — full 0–8)</h2>
<table class="sortable"><thead><tr>{sortable_th('PAUL_SCORE','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist_rows}</tbody></table>
<h2>PAUL_SCORE histogram (764 Summary {len(sum_764)})</h2>
<table class="sortable"><thead><tr>{sortable_th('PAUL_SCORE','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist764_rows}</tbody></table>
<h2>PAUL_SCORE histogram (42 Summary {len(sum_42)})</h2>
<table class="sortable"><thead><tr>{sortable_th('PAUL_SCORE','num')}{sortable_th('N','num')}</tr></thead>
<tbody>{hist42_rows}</tbody></table>
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

    print("ALL_SUMMARY", n_sum, "TRUNCATED", truncated_paul, "OOS_COL", has_oos_col)
    print("PAUL==8", len(eq8_all), ">=8", len(ge8_set), ">=7", len(ge7_all))
    print("USER_N", n_user, "EXTRA", extra_eq8, "MISSING", missing_eq8)
    print("ORDER_FILE", order_match, "SORTED", sorted_match)
    print("OVERLAP_42", len(overlap_42), overlap_42)
    print("ONLY_42", len(only_42))
    print("IN_764", len(in_764), "NOT_764", not_764)
    print("EQ8_764", len(eq8_764), "INTERSECT", len(user_set & eq8_764))
    print("EQ8_42", sorted(eq8_42))
    print("HTML", html_path)
    for m in metric_rows:
        print(
            f"{m['book']}|{m['split']}|names={m['n_names']}|N={m['n']}|"
            f"WR={fmt_n(m['wr'],1)}|Avg={fmt_n(m['avg_pnl'],2)}|"
            f"WOMAX={fmt_n(m['avg_pnl_wo_max'],2)}|"
            f"PF={fmt_n(m['pf'],2)}|Ann={fmt_n(m['ann_ror'],1)}|DD={fmt_n(m['max_dd'],2)}|"
            f"Sheet={m['sheet_pnl']:.2f}"
        )


if __name__ == "__main__":
    main()
