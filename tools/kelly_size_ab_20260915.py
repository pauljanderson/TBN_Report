#!/usr/bin/env python3
"""Kelly position-size A/Bs on house Closed books (overlay, same entries/exits).

Fit p / b / peak concurrent on IS (entry < 2024-01-01) only. Apply frozen
size to IS / OOS / FULL. Not gold. Does not flip DailyRun defaults.

Systems: VZ, BRT, RSI. RSI skips risk-fraction arms (no price stop).
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    overlay_ann_ror_max_dd,
)
from kelly_sizing import (  # noqa: E402
    KellyFit,
    fit_kelly_from_pnl_pct,
    risk_notional,
    slot_dollars,
)

STAMP = "kelly_size_ab_20260915"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
DRIVE = REPO / "drive"
IS_CUT = date(2024, 1, 1)
INIT = DEFAULT_INITIAL_ACCOUNT
DEPLOYABLE = 600_000.0  # 500k × 2.0 × 0.6

ORIGINAL_REQUEST = (
    "in this report, i am surprised to see the ann ROR is the same for most of "
    "them. i would expect that to actually be different if we are more "
    "aggressive in some than others"
)
PLAIN_ENGLISH = (
    "If one Kelly arm bets bigger than another, yearly return should move. If "
    "the table shows the same Annualized Rate of Return (Ann ROR) for most "
    "arms, either size is not actually changing, or Ann ROR is computed in a "
    "way that ignores size (for example a fixed $10k/fill overlay). Explain "
    "which, in everyday terms."
)
KELLY_WIRE_REQUEST = "let's wire in and run those kelly AB tests please."
KELLY_WIRE_PLAIN = (
    "Kelly is a bet-size rule: if you know how often you win and how big wins "
    "are versus losses, it says what fraction of the pile to put on the next "
    "trade. We did not change when Volume Zone (VZ), Break and ReTest (BRT), or "
    "Relative Strength Index (RSI) buy or sell. We only resized the same closed "
    "trades. The formula was fit on trades that opened before 2024 and then "
    "applied to later years as a check — we did not retune on 2024+. Equal "
    "Kelly slots mostly just make every trade smaller, which almost always "
    "lowers drawdown on a $500k account; that is not a new edge. The "
    "interesting test is risk-fraction Kelly on VZ/BRT (size from stop "
    "distance, then optionally scaled back so the average dollars match the "
    "sheet). Full Kelly is too aggressive; we used a quarter (and a half-Kelly "
    "notch). Not gold. DailyRun still uses the old fixed sheet dollars."
)
ANN_ROR_TIE = (
    "Ann ROR in the main column is a percent-on-the-slot number, not yearly "
    "return on the $500k house. The overlay formula is "
    "((1 + total_$ / (cash × n)) ** (365 / avg days) − 1). For equal-slot "
    "arms we set cash to that arm’s mean dollars, so size cancels: $924 and "
    "$45,000 at the same +5% per fill print the same Ann ROR. Aggression is "
    "real and is not the old sheet-cap clone (VZ/BRT quarter-Kelly slots are "
    "far below the sheet; only RSI half-Kelly clamps to $10k and therefore "
    "matches CONTROL). Look at mean $, mean shares, peak deployed, implied "
    "leverage, Max DD %, and profit / capital day. The extra columns Ann ROR "
    "$500k and Ann ROR $600k keep the same dollar PnL but use a fixed "
    "account / host-deployable cash so bigger bets raise yearly return and "
    "smaller bets lower it. KEEP/DISMISS unchanged — equal-slot shrink is "
    "still HOLD, not a new edge."
)

SORTABLE_TH_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; touch-action: manipulation; }
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
    if not s or s.lower() in {"nan", "none"}:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt != "%Y%m%d" else s[:8], fmt).date()
        except ValueError:
            continue
    return None


def _parse_num(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "n/a", "—", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class Trade:
    symbol: str
    opened: date
    closed: Optional[date]
    entry: float
    stop: Optional[float]
    pnl_pct: float
    days: float
    exit_type: str
    side: str


@dataclass
class SysSpec:
    prefix: str
    sheet: float
    has_stop: bool
    closed_path: Path
    pin: str


def _read_pin(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()


# Pins from the first stamp write. Do not follow live house_last_run_ts —
# sibling DailyRun / convergence jobs may rewrite those.
STAMPED_PINS = {
    "VZ": "260914184242",
    "BRT": "LatestRun",
    "RSI": "260914223813",
}


def resolve_closed(prefix: str) -> tuple[Path, str]:
    stamped = STAMPED_PINS.get(prefix)
    if stamped == "LatestRun":
        latest = DRIVE / f"{prefix}_LatestRun_Closed.csv"
        if latest.is_file():
            return latest, "LatestRun"
    elif stamped:
        p = DRIVE / f"{prefix}_Closed_{stamped}.csv"
        if p.is_file():
            return p, stamped
    house = DRIVE / f"{prefix}_house_last_run_ts.txt"
    pin = _read_pin(house)
    if pin:
        p = DRIVE / f"{prefix}_Closed_{pin}.csv"
        if p.is_file():
            return p, pin
    latest = DRIVE / f"{prefix}_LatestRun_Closed.csv"
    if latest.is_file():
        return latest, "LatestRun"
    cands = sorted(DRIVE.glob(f"{prefix}_Closed_*.csv"))
    if not cands:
        raise FileNotFoundError(f"no {prefix} Closed CSV")
    return cands[-1], cands[-1].stem


def load_trades(path: Path) -> list[Trade]:
    rows: list[Trade] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = _parse_date(raw.get("DATE_OPENED") or raw.get("DATE OPENED"))
            closed = _parse_date(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED"))
            pnl = _parse_num(raw.get("PNL_PCT") or raw.get("PNL %") or raw.get("PNL%"))
            entry = _parse_num(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE"))
            if opened is None or pnl is None or entry is None or entry <= 0:
                continue
            stop = _parse_num(raw.get("STOP_PRICE") or raw.get("STOP PRICE"))
            if stop is not None and stop <= 0:
                stop = None
            days = _parse_num(raw.get("DAYS_HELD") or raw.get("DAYS HELD")) or 0.0
            rows.append(
                Trade(
                    symbol=str(raw.get("SYMBOL") or "").strip(),
                    opened=opened,
                    closed=closed,
                    entry=float(entry),
                    stop=stop,
                    pnl_pct=float(pnl),
                    days=float(days),
                    exit_type=str(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip(),
                    side=str(raw.get("SIDE") or "LONG").strip().upper() or "LONG",
                )
            )
    return rows


def slice_trades(trades: Sequence[Trade], which: str) -> list[Trade]:
    if which == "IS":
        return [t for t in trades if t.opened < IS_CUT]
    if which == "OOS":
        return [t for t in trades if t.opened >= IS_CUT]
    return list(trades)


def risk_pct(t: Trade) -> Optional[float]:
    if t.stop is None or t.entry <= 0:
        return None
    return abs(t.entry - t.stop) / t.entry


def fit_from_trades(trades: list[Trade]) -> KellyFit:
    return fit_kelly_from_pnl_pct(
        [t.pnl_pct for t in trades],
        [(t.opened, t.closed or t.opened) for t in trades],
    )


def book_stats(trades: list[Trade], notionals: list[float], *, cash_for_ann: float) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    losses = sum(1 for t in trades if t.pnl_pct < 0)
    pcts = [t.pnl_pct for t in trades]
    avg = sum(pcts) / n
    wo = sorted(pcts)
    avg_wo = (sum(wo[:-1]) / (n - 1)) if n > 1 else avg
    win_pcts = [p for p in pcts if p > 0]
    loss_pcts = [p for p in pcts if p < 0]
    avg_w = (sum(win_pcts) / len(win_pcts)) if win_pcts else 0.0
    avg_l = (sum(loss_pcts) / len(loss_pcts)) if loss_pcts else 0.0
    days = [t.days for t in trades if t.days > 0]
    avg_days = (sum(days) / len(days)) if days else 0.0
    med_days = sorted(days)[len(days) // 2] if days else 0.0
    p90_days = sorted(days)[int(0.9 * (len(days) - 1))] if days else 0.0
    overlay_rows = []
    pnls_d = []
    for t, notion in zip(trades, notionals):
        pd = (t.pnl_pct / 100.0) * float(notion)
        pnls_d.append(pd)
        overlay_rows.append(
            {
                "pnl": t.pnl_pct,
                "pnl_d": pd,
                "days": t.days,
                "closed": t.closed,
                "opened": t.opened,
            }
        )
    ov = overlay_ann_ror_max_dd(overlay_rows, cash=float(cash_for_ann), initial_account=INIT)
    sum_w = sum(x for x in pnls_d if x > 0)
    sum_l = abs(sum(x for x in pnls_d if x < 0))
    pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
    exits = Counter((t.exit_type or "?").upper() for t in trades)
    mean_not = (sum(notionals) / n) if n else 0.0
    mean_shares = (
        sum(float(notion) / t.entry for t, notion in zip(trades, notionals) if t.entry > 0)
        / n
        if n
        else 0.0
    )
    cap_days = ov.get("capital_days") or sum(days)
    total_pnl = float(ov.get("pnl_d") or sum(pnls_d))
    ppc = (total_pnl / cap_days) if cap_days else 0.0
    peak_dep = _peak_deployed(trades, notionals)
    # Size-aware Ann ROR: same $ PnL, fixed cash so slot size does not cancel.
    ann_acct = (
        ann_ror_from_closed(
            total_pnl=total_pnl,
            n_trades=n,
            avg_days_held=avg_days,
            brt_cash=INIT,
        )
        if avg_days > 0
        else None
    )
    ann_host = (
        ann_ror_from_closed(
            total_pnl=total_pnl,
            n_trades=n,
            avg_days_held=avg_days,
            brt_cash=DEPLOYABLE,
        )
        if avg_days > 0
        else None
    )
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_pct": 100.0 * wins / n,
        "avg_pnl_pct": avg,
        "avg_wo_max": avg_wo,
        "avg_win_pct": avg_w,
        "avg_loss_pct": avg_l,
        "expectancy_pct": avg,
        "pf": pf,
        "ann_ror": ov.get("ann_ror"),
        "ann_ror_acct": ann_acct,
        "ann_ror_host": ann_host,
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "avg_days": avg_days,
        "median_days": med_days,
        "p90_days": p90_days,
        "capital_days": cap_days,
        "profit_per_cap_day": ppc,
        "mean_notional": mean_not,
        "mean_shares": mean_shares,
        "peak_deployed": peak_dep,
        "implied_lev": (peak_dep / INIT) if INIT else 0.0,
        "exits": dict(exits),
        "total_pnl": total_pnl,
    }


def _peak_deployed(trades: list[Trade], notionals: list[float]) -> float:
    events: list[tuple[date, float]] = []
    for t, n in zip(trades, notionals):
        opened = t.opened
        closed = t.closed or t.opened
        if closed < opened:
            closed = opened
        events.append((opened, float(n)))
        events.append((closed, -float(n)))
    events.sort(key=lambda x: (x[0], -x[1]))
    cur = 0.0
    peak = 0.0
    for _d, delta in events:
        cur += delta
        if cur > peak:
            peak = cur
    return peak


def _fmt_pct(v: Any) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):.2f}%"


def _fmt_num(v: Any, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):,.{d}f}"


def _note(arm: str, sl: str, ctrl: dict, cand: dict) -> str:
    if sl == "OOS":
        return "report-only"
    if sl != "FULL":
        return ""
    if arm == "CONTROL":
        return ""
    c_dd = ctrl.get("max_dd")
    a_dd = cand.get("max_dd")
    c_slot = ctrl.get("mean_notional") or 0
    a_slot = cand.get("mean_notional") or 0
    if arm in {"SIZE_qkelly_slot", "SIZE_hkelly_slot", "SIZE_host_qkelly"}:
        if a_slot < c_slot * 0.98:
            return "HOLD (smaller size → lower DD%; not an edge)"
        if a_slot > c_slot * 1.02:
            return "HOLD (larger than sheet — first pass was shrink-only; unclamped)"
        return "HOLD"
    if arm == "SIZE_risk_qkelly":
        if a_slot < c_slot * 0.98:
            return "HOLD (smaller mean $; use renorm for mix-only)"
        return "HOLD"
    if arm == "SIZE_risk_qkelly_renorm":
        if c_dd is None or a_dd is None or math.isnan(float(c_dd)) or math.isnan(float(a_dd)):
            return "HOLD"
        dd_delta = float(a_dd) - float(c_dd)
        pf_delta = float(cand.get("pf") or 0) - float(ctrl.get("pf") or 0)
        if dd_delta <= -0.25 and pf_delta >= -0.05:
            return "LEAN KEEP (research)"
        if dd_delta >= 0.40 and pf_delta < 0:
            return "DISMISS"
        return "HOLD"
    return "HOLD"


def run_system(spec: SysSpec) -> dict[str, Any]:
    trades = load_trades(spec.closed_path)
    is_tr = slice_trades(trades, "IS")
    fit = fit_from_trades(is_tr)
    fit_r = None
    if spec.has_stop:
        r_is = [t for t in is_tr if risk_pct(t) is not None]
        # Kelly on R: win if pnl>0, b = avg_win% / |avg_loss%| still (same as $ if equal size)
        # Risk-fraction q uses the same f* (edge on the % book) as the isolated bet.
        fit_r = fit

    q_slot = slot_dollars(fit, bankroll=INIT, kelly_fraction=0.25, sheet_cap=spec.sheet)
    h_slot = slot_dollars(fit, bankroll=INIT, kelly_fraction=0.50, sheet_cap=spec.sheet)
    host_slot = slot_dollars(fit, bankroll=DEPLOYABLE, kelly_fraction=0.25, sheet_cap=spec.sheet)
    # Risk $ per fill = (fraction × f* × bankroll) / peak concurrent.
    # Using 0.25×f* with no concurrent split is ~9% of the whole pile per
    # name — every fill then hits the sheet cap and clones CONTROL.
    q_risk = (
        (0.25 * fit_r.f_star / float(fit_r.peak_concurrent)) if fit_r else 0.0
    )

    arms: list[dict[str, Any]] = [
        {
            "arm": "CONTROL",
            "knob": "none",
            "kind": "equal",
            "desc": f"Frozen sheet ${spec.sheet:,.0f} per fill (DailyRun identity).",
        },
        {
            "arm": "SIZE_qkelly_slot",
            "knob": "equal_slot",
            "kind": "equal",
            "desc": (
                f"Quarter-Kelly equal slot: 0.25×f*×$500k / peak_conc_IS "
                f"(clamp ≤ sheet). Slot ${q_slot:,.0f}."
            ),
            "slot": q_slot,
        },
        {
            "arm": "SIZE_hkelly_slot",
            "knob": "equal_slot",
            "kind": "equal",
            "desc": (
                f"Half-Kelly equal slot: 0.50×f*×$500k / peak_conc_IS "
                f"(clamp ≤ sheet). Slot ${h_slot:,.0f}."
            ),
            "slot": h_slot,
        },
        {
            "arm": "SIZE_host_qkelly",
            "knob": "host_bankroll",
            "kind": "equal",
            "desc": (
                f"Quarter-Kelly using $600k deployable as bankroll / peak_conc_IS "
                f"(clamp ≤ sheet). Slot ${host_slot:,.0f}."
            ),
            "slot": host_slot,
        },
    ]
    if spec.has_stop:
        arms.append(
            {
                "arm": "SIZE_risk_qkelly",
                "knob": "risk_fraction",
                "kind": "risk",
                "desc": (
                    f"Risk $ = 0.25×f* × $500k / peak_conc_IS; shares from "
                    f"(entry−stop); clamp notional ≤ sheet. q={q_risk:.4f}."
                ),
                "q": q_risk,
                "renorm": False,
            }
        )
        arms.append(
            {
                "arm": "SIZE_risk_qkelly_renorm",
                "knob": "risk_mix",
                "kind": "risk",
                "desc": (
                    "Same risk-fraction as SIZE_risk_qkelly, then scale so mean "
                    "notional equals the sheet (pure mix, not a gross-size cut)."
                ),
                "q": q_risk,
                "renorm": True,
            }
        )

    def notionals_for(arm: dict, book: list[Trade]) -> list[float]:
        if arm["arm"] == "CONTROL":
            return [spec.sheet] * len(book)
        if arm["kind"] == "equal":
            slot = float(arm["slot"])
            return [slot] * len(book)
        out: list[float] = []
        for t in book:
            rp = risk_pct(t)
            n = risk_notional(
                q=float(arm["q"]),
                bankroll=INIT,
                risk_pct=rp or 0.0,
                sheet_cap=spec.sheet,
            )
            if n is None:
                n = spec.sheet
            out.append(float(n))
        if arm.get("renorm") and out:
            mean = sum(out) / len(out)
            if mean > 0:
                scale = spec.sheet / mean
                out = [x * scale for x in out]
        return out

    tables: dict[str, list[dict[str, Any]]] = {}
    for sl in ("IS", "OOS", "FULL"):
        book = slice_trades(trades, sl)
        rows = []
        ctrl_stats = None
        for arm in arms:
            notion = notionals_for(arm, book)
            cash = (
                spec.sheet
                if arm["arm"] == "CONTROL"
                else (sum(notion) / len(notion) if notion else spec.sheet)
            )
            st = book_stats(book, notion, cash_for_ann=cash)
            st["arm"] = arm["arm"]
            st["knob"] = arm["knob"]
            if ctrl_stats is None:
                ctrl_stats = st
            st["d_avg"] = float(st.get("avg_pnl_pct") or 0) - float(
                ctrl_stats.get("avg_pnl_pct") or 0
            )
            st["d_dd"] = float(st.get("max_dd") or 0) - float(ctrl_stats.get("max_dd") or 0)
            st["note"] = _note(arm["arm"], sl, ctrl_stats, st)
            rows.append(st)
        tables[sl] = rows

    return {
        "spec": spec,
        "n_all": len(trades),
        "fit": fit,
        "q_slot": q_slot,
        "h_slot": h_slot,
        "host_slot": host_slot,
        "q_risk": q_risk,
        "arms": arms,
        "tables": tables,
    }


def _sys_specs() -> list[SysSpec]:
    out: list[SysSpec] = []
    for prefix, sheet, has_stop in (
        ("VZ", 45_000.0, True),
        ("BRT", 47_500.0, True),
        ("RSI", 10_000.0, False),
    ):
        path, pin = resolve_closed(prefix)
        out.append(SysSpec(prefix, sheet, has_stop, path, pin))
    return out


def write_baseline(results: list[dict[str, Any]]) -> None:
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "**Status:** Research size overlay. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "## Why Ann ROR ties (honesty)",
        "",
        ANN_ROR_TIE,
        "",
        "Earlier wire-up request:",
        "",
        f"> {KELLY_WIRE_REQUEST}",
        "",
        KELLY_WIRE_PLAIN,
        "",
        "## Honesty",
        "",
        "- Same Closed trades as the first stamp write (VZ 260914184242, "
        "BRT LatestRun, RSI 260914223813). Entries and exits frozen. "
        "Does not follow live house_last_run_ts.",
        "- Kelly inputs (win rate, payoff, peak concurrent) fit on **IS only**.",
        "- OOS is report-only. Do not retune the Kelly fraction on OOS.",
        "- Equal-slot shrink almost always lowers overlay Max DD on a $500k seed.",
        "  That is not a KEEP for a new edge.",
        "- DailyRun still uses fixed sheet notionals (VZ $45k, BRT $47.5k, RSI $10k).",
        "- Main **Ann ROR %** is slot-normalized (cash = mean $). It will match "
        "across equal-slot arms even when dollars change. Use **Ann ROR $500k** / "
        "**Ann ROR $600k**, mean $, mean shares, peak deployed, Max DD.",
        "",
        "## Frozen control (per system)",
        "",
        "- Overlay seed: $500,000",
        "- IS cut: entry_date < 2024-01-01",
        "- Host deployable (SIZE_host_qkelly bankroll): $600,000",
        "",
    ]
    for r in results:
        spec: SysSpec = r["spec"]
        fit: KellyFit = r["fit"]
        lines += [
            f"### {spec.prefix}  ({spec.closed_path.name} / {spec.pin})",
            "",
            f"- Sheet control: ${spec.sheet:,.0f}",
            f"- IS N={fit.n} WR={100*fit.win_rate:.2f}% avgW={fit.avg_win_pct:.2f}% "
            f"avgL={fit.avg_loss_pct:.2f}% b={fit.payoff_b:.3f} f*={fit.f_star:.4f} "
            f"peak_conc={fit.peak_concurrent}",
            f"- Quarter-Kelly slot (clamped): ${r['q_slot']:,.2f}",
            f"- Half-Kelly slot (clamped): ${r['h_slot']:,.2f}",
            f"- Host-bankroll quarter-Kelly slot (clamped): ${r['host_slot']:,.2f}",
        ]
        if spec.has_stop:
            lines.append(f"- Risk q (0.25×f*): {r['q_risk']:.4f}")
        if fit.note:
            lines.append(f"- Fit note: {fit.note}")
        lines.append("")
        full = {row["arm"]: row for row in r["tables"]["FULL"]}
        for arm in r["arms"]:
            st = full[arm["arm"]]
            lines.append(
                f"- **{arm['arm']} FULL** N={st['n']} WR={st['win_pct']:.2f}% "
                f"Avg%={st['avg_pnl_pct']:.2f} MaxDD={_fmt_pct(st['max_dd'])} "
                f"AnnROR(slot)={_fmt_pct(st['ann_ror'])} "
                f"AnnROR$500k={_fmt_pct(st.get('ann_ror_acct'))} "
                f"AnnROR$600k={_fmt_pct(st.get('ann_ror_host'))} "
                f"Calmar={_fmt_num(st['calmar'])} "
                f"mean$={st['mean_notional']:.0f} shares={st.get('mean_shares') or 0:.1f} "
                f"lev={st['implied_lev']:.2f} "
                f"note={st['note']}"
            )
        lines.append("")
    lines += [
        "## Arms",
        "",
        "- `CONTROL` — sheet notional",
        "- `SIZE_qkelly_slot` — quarter-Kelly equal slot, clamp to sheet",
        "- `SIZE_hkelly_slot` — half-Kelly equal slot, clamp to sheet",
        "- `SIZE_host_qkelly` — quarter-Kelly with $600k deployable bankroll",
        "- `SIZE_risk_qkelly` — VZ/BRT only; risk-fraction, clamp to sheet",
        "- `SIZE_risk_qkelly_renorm` — VZ/BRT only; risk mix, mean $ = sheet",
        "",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _table_html(rows: list[dict[str, Any]], sl: str) -> str:
    headers = [
        ("Arm", "text"),
        ("Knob", "text"),
        ("N", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Expectancy %", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("PF", "num"),
        ("Ann ROR (slot) %", "num"),
        ("Ann ROR $500k %", "num"),
        ("Ann ROR $600k %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Avg days", "num"),
        ("Median days", "num"),
        ("P90 days", "num"),
        ("Capital days", "num"),
        ("Profit / cap day", "num"),
        ("Mean notional", "num"),
        ("Mean shares", "num"),
        ("Peak deployed", "num"),
        ("Implied lev", "num"),
        ("Δ Avg PnL % vs ctrl", "num"),
        ("Δ Max DD vs ctrl", "num"),
        ("Note", "text"),
    ]
    th = "".join(sortable_th(h, t) for h, t in headers)
    body = []
    for st in rows:
        body.append(
            "<tr>"
            + "".join(
                [
                    f"<td>{html_mod.escape(str(st['arm']))}</td>",
                    f"<td>{html_mod.escape(str(st['knob']))}</td>",
                    f"<td>{st['n']:,}</td>",
                    f"<td>{_fmt_pct(st['win_pct'])}</td>",
                    f"<td>{_fmt_pct(st['avg_pnl_pct'])}</td>",
                    f"<td>{_fmt_pct(st['avg_wo_max'])}</td>",
                    f"<td>{_fmt_pct(st['expectancy_pct'])}</td>",
                    f"<td>{_fmt_pct(st['avg_win_pct'])}</td>",
                    f"<td>{_fmt_pct(st['avg_loss_pct'])}</td>",
                    f"<td>{_fmt_num(st['pf'])}</td>",
                    f"<td>{_fmt_pct(st['ann_ror'])}</td>",
                    f"<td>{_fmt_pct(st.get('ann_ror_acct'))}</td>",
                    f"<td>{_fmt_pct(st.get('ann_ror_host'))}</td>",
                    f"<td>{_fmt_pct(st['max_dd'])}</td>",
                    f"<td>{_fmt_num(st['calmar'])}</td>",
                    f"<td>{_fmt_num(st['sharpe'])}</td>",
                    f"<td>{_fmt_num(st['avg_days'], 1)}</td>",
                    f"<td>{_fmt_num(st['median_days'], 1)}</td>",
                    f"<td>{_fmt_num(st['p90_days'], 1)}</td>",
                    f"<td>{_fmt_num(st['capital_days'], 0)}</td>",
                    f"<td>{format_money(st['profit_per_cap_day'])}</td>",
                    f"<td>{format_money(st['mean_notional'])}</td>",
                    f"<td>{_fmt_num(st.get('mean_shares'), 1)}</td>",
                    f"<td>{format_money(st['peak_deployed'])}</td>",
                    f"<td>{_fmt_num(st['implied_lev'])}</td>",
                    f"<td>{_fmt_pct(st['d_avg'])}</td>",
                    f"<td>{_fmt_pct(st['d_dd'])}</td>",
                    f"<td>{html_mod.escape(st.get('note') or '')}</td>",
                ]
            )
            + "</tr>"
        )
    cap = (
        "IS (entry &lt; 2024-01-01)"
        if sl == "IS"
        else (
            "OOS (entry ≥ 2024-01-01) — report-only"
            if sl == "OOS"
            else "FULL (all history)"
        )
    )
    return (
        f"<h3>{cap}</h3>"
        f'<p class="meta">Click column headers to sort. Sheet / total $ omitted. '
        f"<strong>Ann ROR (slot)</strong> uses cash = mean $ so equal-size arms "
        f"tie. <strong>Ann ROR $500k / $600k</strong> use a fixed account / "
        f"host-deployable cash and the arm’s actual dollars — those move with "
        f"aggression. Overlay Max DD / Sharpe seed $500k, exit-date equity.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def write_html(results: list[dict[str, Any]]) -> Path:
    chunks = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>",
        f"<title>{STAMP}</title><style>",
        SORTABLE_TH_CSS,
        "body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }",
        "h1 { font-size: 1.4rem; margin: 0 0 .35rem; }",
        "h2 { font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }",
        ".meta { color: #475569; font-size: .92rem; max-width: 78rem; }",
        ".insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }",
        ".ask { background: #eff6ff; border: 1px solid #bfdbfe; }",
        "table.sortable { border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }",
        "table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }",
        "table.sortable th { background: #f1f5f9; }",
        ".badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }",
        ".caveat { color: #9a3412; font-size: .9rem; max-width: 78rem; }",
        ".ror { background: #fff7ed; border: 1px solid #fdba74; }",
        "blockquote.meta { margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }",
        "</style></head><body>",
        "<h1>Kelly size A/Bs — VZ / BRT / RSI Closed overlay</h1>",
        '<p class="badge">Research only · not gold · not DailyRun · OOS report-only · SIZE / overlay</p>',
        f'<p class="meta">Stamp <code>{STAMP}</code> · 2026-09-15 · click column headers to sort</p>',
        '<div class="insight ask"><h2 style="margin-top:0;border:0">What you asked</h2>',
        f'<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>',
        "<h2>In plain English</h2>",
        f"<p>{html_mod.escape(PLAIN_ENGLISH)}</p></div>",
        '<div class="insight ror"><h2 style="margin-top:0;border:0">'
        "Why Ann ROR matches on most arms</h2>"
        f"<p>{html_mod.escape(ANN_ROR_TIE)}</p></div>",
        '<div class="insight"><p class="caveat"><strong>Selection honesty:</strong> '
        "Kelly fractions are fit on the same IS Closed book we then score. That is "
        "in-sample sizing. Equal-slot arms that shrink dollars will look better on "
        "Max DD — do not read that as a new system. DailyRun is unchanged. "
        "KEEP/DISMISS below are the original stamp; this page only adds the "
        "Ann ROR honesty note and size-aware columns.</p>"
        f"<p class=\"meta\">Earlier wire-up: <em>{html_mod.escape(KELLY_WIRE_REQUEST)}</em></p></div>",
    ]
    for r in results:
        spec: SysSpec = r["spec"]
        fit: KellyFit = r["fit"]
        chunks.append(f"<h2>{spec.prefix} — {html_mod.escape(spec.closed_path.name)}</h2>")
        chunks.append(
            f'<p class="meta">Sheet ${spec.sheet:,.0f} · pin {html_mod.escape(spec.pin)} · '
            f"IS N={fit.n} WR={100*fit.win_rate:.2f}% b={fit.payoff_b:.3f} "
            f"f*={fit.f_star:.4f} peak_conc={fit.peak_concurrent} · "
            f"q-slot ${r['q_slot']:,.0f} · h-slot ${r['h_slot']:,.0f} · "
            f"host-slot ${r['host_slot']:,.0f}"
            + (f" · risk q={r['q_risk']:.4f}" if spec.has_stop else "")
            + (f" · {html_mod.escape(fit.note)}" if fit.note else "")
            + "</p>"
        )
        chunks.append("<ul class='meta'>")
        for arm in r["arms"]:
            chunks.append(
                f"<li><code>{html_mod.escape(arm['arm'])}</code> — "
                f"{html_mod.escape(arm['desc'])}</li>"
            )
        chunks.append("</ul>")
        for sl in ("IS", "OOS", "FULL"):
            chunks.append(_table_html(r["tables"][sl], sl))
    chunks.append(f"<script>{SORTABLE_TABLE_SCRIPT}</script></body></html>")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "compare.html"
    path.write_text("".join(chunks), encoding="utf-8")
    return path


def main() -> int:
    results = [run_system(s) for s in _sys_specs()]
    write_baseline(results)
    html_path = write_html(results)
    payload = []
    for r in results:
        fit: KellyFit = r["fit"]
        spec: SysSpec = r["spec"]
        payload.append(
            {
                "prefix": spec.prefix,
                "closed": str(spec.closed_path),
                "pin": spec.pin,
                "sheet": spec.sheet,
                "fit": {
                    "n": fit.n,
                    "win_rate": fit.win_rate,
                    "payoff_b": fit.payoff_b,
                    "f_star": fit.f_star,
                    "peak_concurrent": fit.peak_concurrent,
                    "note": fit.note,
                },
                "q_slot": r["q_slot"],
                "h_slot": r["h_slot"],
                "host_slot": r["host_slot"],
                "q_risk": r["q_risk"],
                "full": r["tables"]["FULL"],
            }
        )
    (OUT_DIR / "summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(f"[kelly AB] wrote {html_path}")
    for r in results:
        spec: SysSpec = r["spec"]
        print(
            f"  {spec.prefix}: N={r['n_all']} IS f*={r['fit'].f_star:.4f} "
            f"q-slot=${r['q_slot']:.0f} pin={spec.pin}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
