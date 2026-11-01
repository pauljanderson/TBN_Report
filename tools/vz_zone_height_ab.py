#!/usr/bin/env python3
"""One-knob VZ HL zone-height AB on DualPaul78 Closed (slice, no run_vz).

HL zone = max-vol day's High–Low. Closed DNA has ZONE_LO + ZONE_ID (HL_YYYY-MM-DD)
but not ZONE_HI; reconstruct hi from local OHLC High on that date.

Thresholds are frozen from the IS (entry < 2024-01-01) height distribution only,
then applied to IS and OOS. OOS is report-only — do not retune.
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
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "vz_zone_height_ab_20260819"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
DUAL_STAMP = "260817212836"
CLOSED_PATH = DRIVE / f"VZ_Closed_{DUAL_STAMP}.csv"
UNIV_PATH = DRIVE / "universes" / "VZ_universe.csv"
SHEET = 45_000.0
INITIAL_ACCOUNT = DEFAULT_INITIAL_ACCOUNT
IS_CUT = date(2024, 1, 1)

FREEZE = (
    "HL-only, first_retest, mt≥1, eps=0.005, lb=126, rw=63, next_open, "
    "EXIT_atr4_s025_r15, min_atr_pct=4, stop 0.25 ATR, 1.5R, ts40"
)


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


def _parse_zone_id_date(zone_id: str) -> Optional[date]:
    s = str(zone_id or "").strip()
    if "_" not in s:
        return None
    tail = s.split("_", 1)[1].strip()
    return _parse_d(tail[:10])


def load_universe(path: Path) -> set[str]:
    out: set[str] = set()
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.add(s.split(",")[0].strip().upper())
    return out


def _ohlc_path(sym: str) -> Optional[Path]:
    for name in (f"{sym}.csv", f"{sym}.CSV"):
        p = DATA_DIR / name
        if p.is_file():
            return p
    return None


def load_hl_map(sym: str, cache: dict[str, dict[date, tuple[float, float]]]) -> dict[date, tuple[float, float]]:
    if sym in cache:
        return cache[sym]
    path = _ohlc_path(sym)
    m: dict[date, tuple[float, float]] = {}
    if path is None:
        cache[sym] = m
        return m
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            d = _parse_d(raw.get("Date") or raw.get("DATE") or "")
            if d is None:
                continue
            hi = _f(raw.get("High") or raw.get("HIGH"))
            lo = _f(raw.get("Low") or raw.get("LOW"))
            if math.isfinite(hi) and math.isfinite(lo) and hi > 0 and lo > 0:
                m[d] = (hi, lo)
    cache[sym] = m
    return m


def nearest_bar(m: dict[date, tuple[float, float]], d: date, tol: int = 3) -> Optional[tuple[date, float, float]]:
    if d in m:
        hi, lo = m[d]
        return d, hi, lo
    best: Optional[tuple[int, date]] = None
    for k in m:
        delta = abs((k - d).days)
        if delta <= tol and (best is None or delta < best[0] or (delta == best[0] and k < best[1])):
            best = (delta, k)
    if best is None:
        return None
    hi, lo = m[best[1]]
    return best[1], hi, lo


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
        "avg_days": sum(t["days"] for t in trades) / n,
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


def load_closed(path: Path, univ: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ohlc_cache: dict[str, dict[date, tuple[float, float]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE_OPENED") or raw.get("DATE OPENED") or "")
            if opened is None:
                continue
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            if not sym or (univ and sym not in univ):
                continue
            kind = str(raw.get("ZONE_KIND") or "").strip().upper()
            zid = str(raw.get("ZONE_ID") or "").strip()
            if not kind and zid:
                kind = zid.split("_", 1)[0].upper()
            if kind and kind != "HL":
                continue
            entry = _f(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE"))
            zlo_csv = _f(raw.get("ZONE_LO") or raw.get("ZONE LO"))
            zhi_csv = _f(raw.get("ZONE_HI") or raw.get("ZONE_HIGH") or raw.get("ZONE HI"))
            mv = _parse_zone_id_date(zid)
            recon_hi = recon_lo = float("nan")
            bar_date: Optional[date] = None
            if mv is not None:
                hit = nearest_bar(load_hl_map(sym, ohlc_cache), mv)
                if hit is not None:
                    bar_date, recon_hi, recon_lo = hit
            lo = zlo_csv if math.isfinite(zlo_csv) and zlo_csv > 0 else recon_lo
            hi = zhi_csv if math.isfinite(zhi_csv) and zhi_csv > 0 else recon_hi
            mid = (hi + lo) / 2.0 if math.isfinite(hi) and math.isfinite(lo) and hi > 0 and lo > 0 else float("nan")
            rng = (hi - lo) if math.isfinite(hi) and math.isfinite(lo) else float("nan")
            pct_mid = 100.0 * rng / mid if math.isfinite(rng) and math.isfinite(mid) and mid > 0 else float("nan")
            pct_entry = (
                100.0 * rng / entry if math.isfinite(rng) and math.isfinite(entry) and entry > 0 else float("nan")
            )
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "entry": entry,
                    "pnl": _f(raw.get("PNL_PCT") or raw.get("PNL %"), 0.0),
                    "r": _f(raw.get("R_MULT") or raw.get("R_MULTIPLE"), 0.0),
                    "days": _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD"), 0.0),
                    "pnl_d": _f(raw.get("PNL_DOLLARS"), 0.0),
                    "exit": str(raw.get("EXIT_TYPE") or "").strip(),
                    "closed": _parse_d(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED") or ""),
                    "kind": kind,
                    "zid": zid,
                    "lo": lo,
                    "hi": hi,
                    "mid": mid,
                    "pct_mid": pct_mid,
                    "pct_entry": pct_entry,
                    "atr_pct": _f(raw.get("ATR_PCT_AT_ENTRY")),
                    "bar_date": bar_date,
                    "recon_ok": math.isfinite(pct_mid) and pct_mid > 0,
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
    """Return verdict, winning arm name, why. Rule frozen before looking at OOS retune."""
    notes = []
    keep_arm = None
    dismiss_all = True
    for a in arms:
        is_up = quality_better(a["is"], control["is"])
        oos_down = oos_softer(a["oos"], control["oos"])
        if is_up:
            dismiss_all = False
        if is_up and not oos_down:
            keep_arm = a["name"]
            notes.append(
                f"{a['name']}: IS quality up vs control (AvgPnL {a['is']['avg_pnl']:.2f} vs "
                f"{control['is']['avg_pnl']:.2f}); OOS did not soften."
            )
        elif is_up and oos_down:
            notes.append(
                f"{a['name']}: IS quality up but OOS softened "
                f"(OOS AvgPnL {a['oos']['avg_pnl']:.2f} vs control {control['oos']['avg_pnl']:.2f}) — HOLD, do not retune."
            )
        else:
            notes.append(
                f"{a['name']}: IS quality not better than control "
                f"(IS AvgPnL {a['is']['avg_pnl']:.2f} vs {control['is']['avg_pnl']:.2f})."
            )
    if keep_arm:
        return "KEEP (research-only)", keep_arm, " ".join(notes)
    if dismiss_all:
        return "DISMISS", "", "Neither smaller-zone arm improved IS quality vs unfiltered DualPaul78. " + " ".join(notes)
    return "HOLD", "", " ".join(notes)


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


def quintile_table(usable: list[dict[str, Any]], field: str) -> str:
    ranked = sorted(usable, key=lambda t: t[field])
    n = len(ranked)
    if n < 5:
        return "<p>Not enough trades for quintiles.</p>"
    head = (
        sortable_th("IS quintile (pct_mid)", "text")
        + sortable_th("N", "num")
        + sortable_th("WR %", "num")
        + sortable_th("Avg PnL %", "num")
        + sortable_th("AvgR", "num")
        + sortable_th("PF", "num")
        + sortable_th("Height mid % (min–max)", "text")
    )
    body = ""
    for i in range(5):
        a = int(round(i * n / 5))
        b = int(round((i + 1) * n / 5))
        chunk = ranked[a:b]
        st = book_stats(chunk)
        xs = [t[field] for t in chunk]
        body += (
            f"<tr><td>Q{i + 1} {'smallest' if i == 0 else 'largest' if i == 4 else ''}</td>"
            f'<td class="num">{st["n"]}</td>'
            f'<td class="num">{fmt_n(st["wr"], 1)}</td>'
            f'<td class="num">{fmt_n(st["avg_pnl"], 2)}</td>'
            f'<td class="num">{fmt_n(st["avg_r"], 2)}</td>'
            f'<td class="num">{fmt_n(st["pf"], 2)}</td>'
            f"<td>{fmt_n(min(xs), 2)}–{fmt_n(max(xs), 2)}</td></tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table>"
    )


def main() -> int:
    univ = load_universe(UNIV_PATH)
    trades = load_closed(CLOSED_PATH, univ)
    usable = [t for t in trades if t["recon_ok"]]
    is_u, oos_u = split_is_oos(usable)
    is_h = [t["pct_mid"] for t in is_u]
    is_e = [t["pct_entry"] for t in is_u]
    p25 = quantile(is_h, 0.25)
    p50 = quantile(is_h, 0.50)
    p75 = quantile(is_h, 0.75)
    # Pre-agreed arms from IS distribution only (before quality). Round to 2 dp for freeze.
    thr_p25 = round(p25, 2)
    thr_med = round(p50, 2)
    alias_note = (
        f"8% is near the IS median ({thr_med:.2f}%); 12% is not an IS p25/median cut "
        f"(IS p75={p75:.2f}%) and was not used as an arm."
    )

    control_trades = usable  # reconstructed height required so arms share the same DNA set
    arm_med = [t for t in usable if t["pct_mid"] <= thr_med]
    arm_p25 = [t for t in usable if t["pct_mid"] <= thr_p25]

    packed = [
        pack("Control (no height filter)", control_trades),
        pack(f"Smaller <= IS median ({thr_med:.2f}% mid)", arm_med),
        pack(f"Smaller <= IS p25 ({thr_p25:.2f}% mid)", arm_p25),
    ]
    verdict, keep_arm, why = decide(packed[0], packed[1:])

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Trade-level dump for audit
    dump_path = OUT_DIR / "trades_with_zone_height.csv"
    with dump_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "SYMBOL",
                "DATE_OPENED",
                "SPLIT",
                "ZONE_ID",
                "ZONE_LO",
                "ZONE_HI_RECON",
                "ZONE_MID",
                "PCT_MID",
                "PCT_ENTRY",
                "ENTRY",
                "PNL_PCT",
                "R_MULT",
                "ATR_PCT_AT_ENTRY",
                "LE_MEDIAN",
                "LE_P25",
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
                    "ZONE_LO": f"{t['lo']:.4f}",
                    "ZONE_HI_RECON": f"{t['hi']:.4f}",
                    "ZONE_MID": f"{t['mid']:.4f}",
                    "PCT_MID": f"{t['pct_mid']:.4f}",
                    "PCT_ENTRY": f"{t['pct_entry']:.4f}",
                    "ENTRY": f"{t['entry']:.4f}",
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "R_MULT": f"{t['r']:.4f}",
                    "ATR_PCT_AT_ENTRY": f"{t['atr_pct']:.4f}" if math.isfinite(t["atr_pct"]) else "",
                    "LE_MEDIAN": int(t["pct_mid"] <= thr_med),
                    "LE_P25": int(t["pct_mid"] <= thr_p25),
                }
            )

    dist_rows = []
    for label, xs in (("IS pct_mid", is_h), ("IS pct_entry", is_e), ("OOS pct_mid", [t["pct_mid"] for t in oos_u])):
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

    atr_pairs = [
        (t["pct_mid"], t["atr_pct"])
        for t in is_u
        if math.isfinite(t["atr_pct"]) and t["atr_pct"] > 0
    ]
    corr_note = "n/a"
    if len(atr_pairs) >= 10:
        xs = [a for a, _ in atr_pairs]
        ys = [b for _, b in atr_pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        num = sum((a - mx) * (b - my) for a, b in atr_pairs)
        den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
        corr_note = f"{num / den:.3f}" if den > 0 else "n/a"

    formula = (
        "HL zone height % of mid = 100 × (zone_hi − zone_lo) / ((zone_hi + zone_lo) / 2). "
        "zone_lo = Closed ZONE_LO (engine stop = max-vol Low). "
        "zone_hi reconstructed from local OHLC High on ZONE_ID date (HL_YYYY-MM-DD). "
        "Also computed 100 × (hi − lo) / entry for reference; filter uses mid %."
    )

    md = f"""# VZ zone-height AB — {STAMP}

**Research only. Not gold. Not DailyRun.** DualPaul78 sleeve.

## Freeze (unchanged)

{FREEZE}

Universe: `drive/universes/VZ_universe.csv` sliced from Closed `{DUAL_STAMP}`.

## Formula

{formula}

## Thresholds (IS distribution only)

IS N with reconstructable HL height = {len(is_u)}.

| | p10 | p25 | **median (p50)** | p75 | p90 | mean |
|--|--|--|--|--|--|--|
| IS pct_mid | {quantile(is_h,0.1):.2f} | **{p25:.2f}** | **{p50:.2f}** | {p75:.2f} | {quantile(is_h,0.9):.2f} | {sum(is_h)/len(is_h):.2f} |

Pre-registered arms (before quality table):

1. Control — no height filter (same reconstructable DNA set)
2. `pct_mid <= {thr_med:.2f}` (IS median)
3. `pct_mid <= {thr_p25:.2f}` (IS 25th percentile)

8% / 12% round numbers: {alias_note}

**Selection bias label:** quantile cuts were chosen from the IS *size* distribution, not from a PnL horse-race. Still in-sample size selection (which trades exist). OOS is report-only; do not retune if OOS softens.

IS vs OOS split: entry_date < 2024-01-01 vs ≥ 2024-01-01.

## Verdict

**{verdict}** {keep_arm}

{why}

IS/OOS ATR% vs zone-height correlation (IS): {corr_note} (zone height is related to, but not identical to, `min_atr_pct=4` already in the freeze).

Capital model (now on compare.html): Ann ROR = rocket_tbn book formula with sheet **$45,000**; Max DD = peak-to-trough on `PNL_DOLLARS` by `DATE_CLOSED` seeded at **$500,000**. Overlay slice, not concurrent-position equity.

Post-hoc (not an arm / not KEEP): IS quintiles rise with height (Q1 AvgPnL ~1.3% vs Q5 ~8.5%). A larger-than-median filter would be a new hypothesis, not this AB.
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
<title>VZ zone-height AB DualPaul78</title>
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
<h1>VZ: smaller HL zones (height %) vs control</h1>
<p class="sub">One-knob slice of DualPaul78 Closed <code>VZ_Closed_{DUAL_STAMP}.csv</code>.
Freeze: {html_mod.escape(FREEZE)}. Not DailyRun. Click column headers to sort.</p>
<div class="card">
<strong>Verdict: {html_mod.escape(verdict)}</strong>
{f"<p>Arm: {html_mod.escape(keep_arm)}</p>" if keep_arm else ""}
<p>{html_mod.escape(why)}</p>
</div>
<h2>Formula</h2>
<p>{html_mod.escape(formula)}</p>
<p>Primary filter field: <code>pct_mid</code>. Alternate <code>pct_entry</code> is reported in the distribution table only.</p>
<h2>IS height distribution (thresholds frozen here)</h2>
<p class="small">p25 / median taken from IS <code>pct_mid</code> only, then applied to OOS. Reconstructable trades: {len(usable)} / {len(trades)} loaded (HL). IS {len(is_u)} · OOS {len(oos_u)}. Dropped without height: {len(trades) - len(usable)}.</p>
{dist_html}
<p>Frozen cuts: IS median <strong>{thr_med:.2f}%</strong> · IS p25 <strong>{thr_p25:.2f}%</strong>.
{html_mod.escape(alias_note)}
IS ATR% vs pct_mid correlation: <strong>{html_mod.escape(corr_note)}</strong>.</p>
<p><strong>Selection bias:</strong> quantile cuts come from the IS size distribution, not from scanning a quality table for 8%/12%. Still in-sample size selection. Exploratory quintiles (and any larger-zone pattern) are post-hoc — not KEEP arms. Do not retune OOS.</p>
{metrics_table(packed, "is", "IS (entry < 2024-01-01)", packed[0]["name"])}
{metrics_table(packed, "oos", "OOS (entry ≥ 2024-01-01) — report only", packed[0]["name"])}
{metrics_table(packed, "full", "Full book (IS+OOS, not for KEEP)", packed[0]["name"])}
<h2>IS quintiles of pct_mid (exploratory — not an arm)</h2>
<p class="small">Do not KEEP from this table. Shown so the two frozen cuts can be read against the IS size–quality shape. Click headers to sort.</p>
{quintile_table(is_u, "pct_mid")}
<h2>OOS quintiles of pct_mid (exploratory — report only)</h2>
{quintile_table(oos_u, "pct_mid")}
<p class="small">Artifacts: <code>{html_mod.escape((OUT_DIR / "BASELINE.md").relative_to(ROOT).as_posix())}</code>,
<code>{html_mod.escape(dump_path.relative_to(ROOT).as_posix())}</code>.</p>
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

    print(f"loaded={len(trades)} usable={len(usable)} missing_height={len(trades)-len(usable)}")
    print(f"IS p25={p25:.4f} median={p50:.4f} p75={p75:.4f} mean={sum(is_h)/len(is_h):.4f}")
    print(f"frozen thr_p25={thr_p25:.2f} thr_med={thr_med:.2f}")
    print(f"IS ATR-height corr={corr_note}")
    for p in packed:
        print(p["name"])
        print(f"  IS  {show(p, 'is')}")
        print(f"  OOS {show(p, 'oos')}")
    print(f"VERDICT {verdict}")
    print(f"HTML {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
