#!/usr/bin/env python3
"""One-knob VZ taller HL-zone AB on DualPaul78 Closed (slice, no run_vz).

Hypothesis (NEW vs vz_zone_height_ab_20260819, which DISMISS'd smaller):
keep trades with pct_mid >= frozen IS cuts (median 8.68%, p75 13.28%).

Heights reused from prior reconstruction dump (OHLC High on ZONE_ID date).
Thresholds are frozen from that IS distribution — not recomputed / not fished.
OOS is report-only — do not retune.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import sys
from collections import Counter
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
STAMP = "vz_zone_height_taller_ab_20260819"
PRIOR_STAMP = "vz_zone_height_ab_20260819"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
PRIOR_DUMP = DRIVE / "paul_experiments" / PRIOR_STAMP / "trades_with_zone_height.csv"
DUAL_STAMP = "260817212836"
CLOSED_PATH = DRIVE / f"VZ_Closed_{DUAL_STAMP}.csv"
SHEET = 45_000.0
INITIAL_ACCOUNT = DEFAULT_INITIAL_ACCOUNT  # rocket_vz EquityMeta seed
IS_CUT = date(2024, 1, 1)
HVN_FLAGS = DRIVE / "paul_experiments" / "vp_hvn_lvn_ab_20260819" / "vz_hvn_flags.csv"

# Frozen from prior IS pct_mid distribution (N=858). Do not recompute.
THR_MED = 8.68
THR_P75 = 13.28

FREEZE = (
    "HL-only, first_retest, mt≥1, eps=0.005, lb=126, rw=63, next_open, "
    "EXIT_atr4_s025_r15, min_atr_pct=4, stop 0.25 ATR, 1.5R, ts40"
)

N_MIN_IS = 80
N_MIN_FRAC = 0.15


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


def _parse_d(s: str) -> Optional[date]:
    s = str(s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt != "%Y%m%d" else s[:8], fmt).date()
        except ValueError:
            continue
    return None


def quantile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    pos = q * (len(ys) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ys[lo]
    w = pos - lo
    return ys[lo] * (1.0 - w) + ys[hi] * w


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
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "syms": 0,
        "avg_wo_max": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "cap_days": 0.0,
        "equity_note": "no trades",
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
    exits = Counter(str(t.get("exit") or "") for t in trades)
    days_ok = [t["days"] for t in trades if math.isfinite(t["days"])]
    cap = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INITIAL_ACCOUNT)
    return {
        "n": n,
        "wins": len(wins),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": sum(t["r"] for t in trades) / n,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * SHEET for p in pnls),
        "pnl_d": cap["pnl_d"],
        "avg_days": (sum(days_ok) / len(days_ok)) if days_ok else 0.0,
        "syms": len({t["sym"] for t in trades}),
        "avg_wo_max": wo,
        "ann_ror": cap["ann_ror"],
        "max_dd": cap["max_dd"],
        "cap_days": cap["capital_days"],
        "equity_note": cap["note"],
        "exits": dict(exits),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


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
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def load_closed_extra(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    extra: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not path.is_file():
        return extra
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE_OPENED") or raw.get("DATE OPENED") or "")
            if opened is None:
                continue
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            zid = str(raw.get("ZONE_ID") or "").strip()
            extra[(sym, opened.isoformat(), zid)] = {
                "days": _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD"), 0.0),
                "pnl_d": _f(raw.get("PNL_DOLLARS"), 0.0),
                "exit": str(raw.get("EXIT_TYPE") or "").strip(),
                "closed": _parse_d(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED") or ""),
            }
    return extra


def load_prior_dump(path: Path, extra: dict[tuple[str, str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE_OPENED") or "")
            if opened is None:
                continue
            pct_mid = _f(raw.get("PCT_MID"))
            if not math.isfinite(pct_mid) or pct_mid <= 0:
                continue
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            zid = str(raw.get("ZONE_ID") or "").strip()
            ex = extra.get((sym, opened.isoformat(), zid), {})
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "zid": zid,
                    "lo": _f(raw.get("ZONE_LO")),
                    "hi": _f(raw.get("ZONE_HI_RECON")),
                    "mid": _f(raw.get("ZONE_MID")),
                    "pct_mid": pct_mid,
                    "pct_entry": _f(raw.get("PCT_ENTRY")),
                    "entry": _f(raw.get("ENTRY")),
                    "pnl": _f(raw.get("PNL_PCT"), 0.0),
                    "r": _f(raw.get("R_MULT"), 0.0),
                    "atr_pct": _f(raw.get("ATR_PCT_AT_ENTRY")),
                    "days": _f(ex.get("days"), float("nan")),
                    "pnl_d": _f(ex.get("pnl_d"), 0.0),
                    "exit": str(ex.get("exit") or ""),
                    "closed": ex.get("closed"),
                }
            )
    return rows


def fmt_n(v: Any, nd: int = 2) -> str:
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


def quality_better(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    """Quality up if Avg PnL% and (AvgR or PF) improve; WR not a veto if expectancy up."""
    return cand["avg_pnl"] > ctrl["avg_pnl"] and (
        cand["avg_r"] > ctrl["avg_r"] or cand["pf"] > ctrl["pf"]
    )


def oos_softer(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    return cand["avg_pnl"] < ctrl["avg_pnl"] or cand["avg_r"] < ctrl["avg_r"] or cand["pf"] < ctrl["pf"]


def n_collapsed(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if ctrl["n"] <= 0:
        return True
    return cand["n"] < N_MIN_IS or (cand["n"] / ctrl["n"]) < N_MIN_FRAC


def pack(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    return {
        "name": name,
        "full": book_stats(trades),
        "is": book_stats(is_t),
        "oos": book_stats(oos_t),
        "n_loaded": len(trades),
    }


def delta_cell(cand: float, ctrl: float, nd: int, *, money: bool = False) -> str:
    d = cand - ctrl
    if money:
        return format_money_delta(d)
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.{nd}f}"


def decide(control: dict[str, Any], arms: list[dict[str, Any]]) -> tuple[str, str, str]:
    notes = []
    keep_arm = None
    any_is_up = False
    any_hold = False
    for a in arms:
        is_up = quality_better(a["is"], control["is"])
        oos_down = oos_softer(a["oos"], control["oos"])
        collapsed = n_collapsed(a["is"], control["is"])
        n_note = (
            f"IS N {a['is']['n']} vs control {control['is']['n']} "
            f"({100.0 * a['is']['n'] / control['is']['n']:.0f}% kept)"
            if control["is"]["n"]
            else f"IS N {a['is']['n']}"
        )
        if is_up:
            any_is_up = True
        if is_up and collapsed:
            any_hold = True
            notes.append(
                f"{a['name']}: IS quality up (AvgPnL {a['is']['avg_pnl']:.2f} vs "
                f"{control['is']['avg_pnl']:.2f}) but N collapsed ({n_note}) — HOLD, not KEEP."
            )
        elif is_up and oos_down:
            any_hold = True
            soft = []
            if a["oos"]["avg_pnl"] < control["oos"]["avg_pnl"]:
                soft.append(
                    f"AvgPnL {a['oos']['avg_pnl']:.2f} vs {control['oos']['avg_pnl']:.2f}"
                )
            if a["oos"]["avg_r"] < control["oos"]["avg_r"]:
                soft.append(f"AvgR {a['oos']['avg_r']:.2f} vs {control['oos']['avg_r']:.2f}")
            if a["oos"]["pf"] < control["oos"]["pf"]:
                soft.append(f"PF {a['oos']['pf']:.2f} vs {control['oos']['pf']:.2f}")
            notes.append(
                f"{a['name']}: IS quality up ({n_note}) but OOS softened "
                f"({'; '.join(soft) or 'quality'}) — HOLD, do not retune."
            )
        elif is_up and not oos_down:
            keep_arm = a["name"]
            notes.append(
                f"{a['name']}: IS quality up vs control (AvgPnL {a['is']['avg_pnl']:.2f} vs "
                f"{control['is']['avg_pnl']:.2f}); {n_note}; OOS did not soften."
            )
        else:
            notes.append(
                f"{a['name']}: IS quality not better than control "
                f"(IS AvgPnL {a['is']['avg_pnl']:.2f} vs {control['is']['avg_pnl']:.2f}; {n_note})."
            )
    if keep_arm:
        return "KEEP (research-only)", keep_arm, " ".join(notes)
    if any_hold or any_is_up:
        return "HOLD", "", " ".join(notes)
    return "DISMISS", "", "Neither taller-zone arm improved IS quality vs unfiltered DualPaul78. " + " ".join(notes)


def cap_note(a: dict[str, Any], control: dict[str, Any], split: str) -> str:
    c, t = control[split], a[split]
    def g(d: dict[str, Any], k: str) -> str:
        v = d.get(k)
        return fmt_n(v, 1 if k == "ann_ror" else 2)
    return (
        f"{split.upper()} Ann ROR {g(t, 'ann_ror')} vs {g(c, 'ann_ror')}; "
        f"Max DD {g(t, 'max_dd')} vs {g(c, 'max_dd')}"
    )


def adoption_text(
    verdict: str,
    control: dict[str, Any],
    arms: list[dict[str, Any]],
    nested: Optional[list[dict[str, Any]]],
) -> str:
    """One-knob adoption. Nested HVN+taller is exploratory — not a KEEP trigger."""
    lines = []
    lines.append(
        "**Adopt taller zones?** Stay **HOLD** unless Ann ROR and Max DD clearly support KEEP "
        "*and* OOS AvgR is not softer. Mixed quality → HOLD. Overlay ≠ engine/portfolio BT; "
        "IS-selected percentiles; DualPaul78 research sleeve; N roughly 1/2 (median) or 1/4 (p75). "
        "Not gold / not DailyRun."
    )
    for a in arms:
        lines.append(
            f"- {a['name']}: {cap_note(a, control, 'is')}. {cap_note(a, control, 'oos')} (OOS report-only)."
        )
    if verdict == "HOLD":
        lines.append(
            "Prior OOS AvgR soften still stands. Ann ROR/Max DD here are extra evidence, not a retune trigger."
        )
    lines.append(
        "**Adopt HVN overlap (zone intersects HVN/POC)?** One-knob KEEP research-only on the HVN stamp "
        "if IS quality holds and Ann ROR/Max DD do not deteriorate. LVN veto remains DISMISS. Not DailyRun."
    )
    lines.append(
        "**Combine taller + HVN?** Two knobs. Nested overlay below is **exploratory / selection-biased** "
        "— not a KEEP trigger. Follow-on would freeze HVN (or taller) first, then one-change the other. "
        "Not this week's DailyRun."
    )
    if nested:
        names = ", ".join(p["name"] for p in nested)
        lines.append(f"Nested DualPaul78 DNA arms (same Closed book): {names}.")
        ctrl_n = nested[0]
        for p in nested[1:]:
            lines.append(
                f"- Nested {p['name']}: IS N={p['is']['n']} Ann ROR {fmt_n(p['is']['ann_ror'],1)} vs "
                f"{fmt_n(ctrl_n['is']['ann_ror'],1)}; Max DD {fmt_n(p['is']['max_dd'],2)} vs "
                f"{fmt_n(ctrl_n['is']['max_dd'],2)}. OOS AvgR {fmt_n(p['oos']['avg_r'],2)} vs "
                f"{fmt_n(ctrl_n['oos']['avg_r'],2)} (exploratory)."
            )
    return "\n\n".join(lines)


def metrics_table(packed: list[dict[str, Any]], split_key: str, split_label: str, control_name: str) -> str:
    ctrl = next(p for p in packed if p["name"] == control_name)[split_key]
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
        f"<h2>{html_mod.escape(split_label)}</h2>"
        f'<p class="small">Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    )


def exit_mix_table(packed: list[dict[str, Any]], split_key: str, split_label: str) -> str:
    keys: set[str] = set()
    for p in packed:
        keys.update(p[split_key]["exits"].keys())
    names = sorted(k for k in keys if k)
    if not names:
        return ""
    head = sortable_th("EXIT_TYPE", "text") + "".join(sortable_th(p["name"] + " N", "num") for p in packed)
    head += "".join(sortable_th(p["name"] + " %", "num") for p in packed)
    body = ""
    for k in names:
        body += f"<tr><td>{html_mod.escape(k)}</td>"
        for p in packed:
            n = p[split_key]["exits"].get(k, 0)
            tot = p[split_key]["n"]
            body += f'<td class="num">{n}</td>'
        for p in packed:
            n = p[split_key]["exits"].get(k, 0)
            tot = p[split_key]["n"]
            pct = 100.0 * n / tot if tot else 0.0
            body += f'<td class="num">{fmt_n(pct, 1)}</td>'
        body += "</tr>"
    return (
        f"<h2>Exit mix — {html_mod.escape(split_label)}</h2>"
        f'<p class="small">Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    )


def main() -> int:
    extra = load_closed_extra(CLOSED_PATH)
    usable = load_prior_dump(PRIOR_DUMP, extra)
    if not usable:
        raise SystemExit(f"No trades loaded from {PRIOR_DUMP}")
    is_u, oos_u = split_is_oos(usable)
    is_h = [t["pct_mid"] for t in is_u]

    control_trades = usable
    arm_med = [t for t in usable if t["pct_mid"] >= THR_MED]
    arm_p75 = [t for t in usable if t["pct_mid"] >= THR_P75]

    packed = [
        pack("Control (no height filter)", control_trades),
        pack(f"Taller ≥ IS median ({THR_MED:.2f}% mid)", arm_med),
        pack(f"Taller ≥ IS p75 ({THR_P75:.2f}% mid)", arm_p75),
    ]
    verdict, keep_arm, why = decide(packed[0], packed[1:])
    cap_bits = []
    for a in packed[1:]:
        cap_bits.append(cap_note(a, packed[0], "is") + "; " + cap_note(a, packed[0], "oos") + ".")
    if cap_bits:
        why = why + " Capital (Closed replay, $45k sheet / $500k initial): " + " ".join(cap_bits)
    eq_notes = [p["full"].get("equity_note") or "" for p in packed]
    if any(eq_notes) and any("omitted" in n for n in eq_notes):
        why += " Equity note: " + " | ".join(n for n in eq_notes if n)

    nested_packed: list[dict[str, Any]] = []
    hvn_map: dict[tuple[str, str, str], int] = {}
    if HVN_FLAGS.is_file():
        with HVN_FLAGS.open(newline="", encoding="utf-8-sig") as f:
            for raw in csv.DictReader(f):
                opened = _parse_d(raw.get("DATE_OPENED") or "")
                if opened is None:
                    continue
                sym = str(raw.get("SYMBOL") or "").strip().upper()
                zid = str(raw.get("ZONE_ID") or "").strip()
                hvn_map[(sym, opened.isoformat(), zid)] = int(_f(raw.get("HVN_OL"), 0.0))
        if hvn_map:
            for t in usable:
                t["hvn_ol"] = bool(hvn_map.get((t["sym"], t["opened"].isoformat(), t["zid"]), 0))
            dna = [t for t in usable if (t["sym"], t["opened"].isoformat(), t["zid"]) in hvn_map]
            nested_packed = [
                pack("Nested control (VP+height DNA)", dna),
                pack(f"Taller ≥ median ({THR_MED:.2f}%)", [t for t in dna if t["pct_mid"] >= THR_MED]),
                pack(f"Taller ≥ p75 ({THR_P75:.2f}%)", [t for t in dna if t["pct_mid"] >= THR_P75]),
                pack("HVN-only (zone ∩ HVN/POC)", [t for t in dna if t.get("hvn_ol")]),
                pack(
                    "HVN + taller-median (exploratory AND)",
                    [t for t in dna if t.get("hvn_ol") and t["pct_mid"] >= THR_MED],
                ),
            ]

    adopt = adoption_text(verdict, packed[0], packed[1:], nested_packed or None)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dump_path = OUT_DIR / "trades_taller_flags.csv"
    with dump_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "SYMBOL",
                "DATE_OPENED",
                "SPLIT",
                "ZONE_ID",
                "PCT_MID",
                "PNL_PCT",
                "R_MULT",
                "GE_MEDIAN",
                "GE_P75",
            ],
        )
        w.writeheader()
        for t in usable:
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "DATE_OPENED": t["opened"].isoformat(),
                    "SPLIT": "IS" if t["opened"] < IS_CUT else "OOS",
                    "ZONE_ID": t["zid"],
                    "PCT_MID": f"{t['pct_mid']:.4f}",
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "R_MULT": f"{t['r']:.4f}",
                    "GE_MEDIAN": int(t["pct_mid"] >= THR_MED),
                    "GE_P75": int(t["pct_mid"] >= THR_P75),
                }
            )

    dist_rows = []
    for label, xs in (
        ("IS pct_mid (verify, not for new cuts)", is_h),
        ("OOS pct_mid", [t["pct_mid"] for t in oos_u]),
    ):
        if not xs:
            continue
        dist_rows.append(
            {
                "label": label,
                "n": len(xs),
                "p10": quantile(xs, 0.10),
                "p25": quantile(xs, 0.25),
                "p50": quantile(xs, 0.50),
                "p75": quantile(xs, 0.75),
                "p90": quantile(xs, 0.90),
                "mean": sum(xs) / len(xs),
            }
        )

    formula = (
        "HL zone height % of mid = 100 × (zone_hi − zone_lo) / ((zone_hi + zone_lo) / 2). "
        "Heights reused from prior reconstruction dump "
        f"({PRIOR_STAMP}/trades_with_zone_height.csv): zone_lo = Closed ZONE_LO; "
        "zone_hi = local OHLC High on ZONE_ID date."
    )
    selection = (
        "Prior stamp DISMISS'd smaller-zone filters. IS quintiles on that stamp were "
        "in-sample exploration (Q1 AvgPnL ~1.26% vs Q5 ~8.45%). This AB reuses those "
        "frozen IS size cuts (median 8.68%, p75 13.28%) as ≥ filters — still "
        "selection-aware (cuts chosen after seeing the quintile shape). OOS report-only."
    )

    md = f"""# VZ taller zone-height AB — {STAMP}

**Research only. Not gold. Not DailyRun.** DualPaul78 sleeve.

Prior AB (smaller): `{PRIOR_STAMP}` **DISMISS**. New hypothesis: keep **taller** HL zones.

## Freeze (unchanged)

{FREEZE}

Universe: DualPaul78 Closed `{DUAL_STAMP}` reconstructable HL DNA from `{PRIOR_STAMP}/trades_with_zone_height.csv`.

## Formula

{formula}

## Thresholds (frozen; not refished)

From prior IS distribution (IS N=858): median **{THR_MED:.2f}%**, p75 **{THR_P75:.2f}%**.

Pre-registered arms:

1. Control — no height filter (same reconstructable DNA set)
2. `pct_mid ≥ {THR_MED:.2f}` (IS median)
3. `pct_mid ≥ {THR_P75:.2f}` (IS 75th percentile)

**Selection bias label:** {selection}

IS vs OOS split: entry_date < 2024-01-01 vs ≥ 2024-01-01.

## Verdict

**{verdict}** {keep_arm}

{why}

## Adoption (one-knob; do not DailyRun)

{adopt}

Capital model: Ann ROR = rocket_tbn book formula with sheet notional **$45,000**; Max DD = peak-to-trough on realized `PNL_DOLLARS` by `DATE_CLOSED` seeded at **$500,000** (`rocket_vz.write_equity`). Overlay slice ≠ concurrent-position equity. Missing dollars/dates → omit, do not invent.
"""
    (OUT_DIR / "BASELINE.md").write_text(md, encoding="utf-8")

    dist_html = ""
    dh = sortable_th("Series", "text") + "".join(
        sortable_th(c, "num") for c in ("N", "p10", "p25", "median", "p75", "p90", "mean")
    )
    db = ""
    for r in dist_rows:
        db += (
            f"<tr><td>{html_mod.escape(r['label'])}</td>"
            f'<td class="num">{r["n"]}</td>'
            + "".join(f'<td class="num">{fmt_n(r[k], 2)}</td>' for k in ("p10", "p25", "p50", "p75", "p90", "mean"))
            + "</tr>"
        )
    dist_html = f'<table class="sortable"><thead><tr>{dh}</tr></thead><tbody>{db}</tbody></table>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ taller HL zones AB DualPaul78</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1500px; }}
h1 {{ font-size: 1.35rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.1rem; margin: 28px 0 8px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 8px 0 16px; }}
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
<h1>VZ: taller HL zones (height % ≥ freeze) vs control</h1>
<p class="sub">One-knob slice of DualPaul78 Closed <code>VZ_Closed_{DUAL_STAMP}.csv</code>.
Freeze: {html_mod.escape(FREEZE)}. Not DailyRun. Click column headers to sort.</p>
<div class="card">
<strong>Verdict: {html_mod.escape(verdict)}</strong>
{f"<p>Arm: {html_mod.escape(keep_arm)}</p>" if keep_arm else ""}
<p>{html_mod.escape(why)}</p>
<p>{html_mod.escape(adopt).replace("**", "").replace(chr(10), "<br/>")}</p>
</div>
<h2>Hypothesis</h2>
<p>Prior smaller-zone AB (<code>{PRIOR_STAMP}</code>) was <strong>DISMISS</strong>.
This stamp tests the opposite one-knob: keep trades whose HL height <code>pct_mid</code>
is <strong>at or above</strong> frozen IS cuts.</p>
<p>{html_mod.escape(selection)}</p>
<h2>Formula</h2>
<p>{html_mod.escape(formula)}</p>
<p>Primary filter field: <code>pct_mid</code>. Frozen cuts reused (not refished):
IS median <strong>{THR_MED:.2f}%</strong> · IS p75 <strong>{THR_P75:.2f}%</strong>.</p>
<h2>IS height distribution (verification only)</h2>
<p class="small">Shown to confirm the prior dump. Do not pick new cuts from this table.
Reconstructable trades: {len(usable)}. IS {len(is_u)} · OOS {len(oos_u)}.</p>
{dist_html}
{metrics_table(packed, "is", "IS (entry < 2024-01-01)", packed[0]["name"])}
{metrics_table(packed, "oos", "OOS (entry ≥ 2024-01-01) — report only", packed[0]["name"])}
{metrics_table(packed, "full", "Full book (IS+OOS, not for KEEP)", packed[0]["name"])}
{"".join(
    [
        "<h2>Exploratory nested overlay (taller × HVN) — not a KEEP trigger</h2>",
        "<p class='small'>Two knobs if ANDed. Same DualPaul78 Closed DNA with VP flags from "
        f"<code>{html_mod.escape(HVN_FLAGS.relative_to(ROOT).as_posix())}</code>. "
        "Selection-biased. Click column headers to sort. One-knob KEEP/DISMISS is unchanged.</p>",
        metrics_table(nested_packed, "is", "Nested IS", nested_packed[0]["name"]),
        metrics_table(nested_packed, "oos", "Nested OOS (report only)", nested_packed[0]["name"]),
        metrics_table(nested_packed, "full", "Nested full book", nested_packed[0]["name"]),
    ]
) if nested_packed else "<p class='small'>Nested HVN+taller table: run <code>vp_hvn_lvn_ab.py</code> first (writes vz_hvn_flags.csv).</p>"}
{exit_mix_table(packed, "is", "IS")}
{exit_mix_table(packed, "oos", "OOS")}
<p class="small">Artifacts: <code>{html_mod.escape((OUT_DIR / "BASELINE.md").relative_to(ROOT).as_posix())}</code>,
<code>{html_mod.escape(dump_path.relative_to(ROOT).as_posix())}</code>.
Height source: <code>{html_mod.escape(PRIOR_DUMP.relative_to(ROOT).as_posix())}</code>.</p>
{SORT_JS}
</body>
</html>
"""
    html_path = OUT_DIR / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    def show(p: dict[str, Any], sk: str) -> str:
        s = p[sk]
        return (
            f"N={s['n']} WR={s['wr']:.1f} AvgPnL={s['avg_pnl']:.2f} AvgR={s['avg_r']:.2f} "
            f"PF={s['pf']:.2f} AnnROR={fmt_n(s.get('ann_ror'), 1)} MaxDD={fmt_n(s.get('max_dd'), 2)}"
        )

    print(f"usable={len(usable)} IS={len(is_u)} OOS={len(oos_u)}")
    print(f"frozen thr_med={THR_MED:.2f} thr_p75={THR_P75:.2f} (not recomputed)")
    if is_h:
        print(
            f"verify IS p50={quantile(is_h,0.5):.4f} p75={quantile(is_h,0.75):.4f} n={len(is_h)}"
        )
    for p in packed:
        print(p["name"].replace("≥", ">="))
        print(f"  IS  {show(p, 'is')}")
        print(f"  OOS {show(p, 'oos')}")
    print(f"VERDICT {verdict}")
    if keep_arm:
        print(f"KEEP_ARM {keep_arm}")
    print(f"HTML {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
