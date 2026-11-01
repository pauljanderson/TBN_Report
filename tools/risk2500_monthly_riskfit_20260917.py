#!/usr/bin/env python3
"""Lower monthly risk-to-stop so later 5-sys signals fit under 2× BP.

Writes drive/paul_experiments/risk2500_five_sys_20260917/monthly_riskfit.html
beside the sibling 1% / rotation / $7,500 pages. Does not overwrite them.
Does not run DailyRun. Research only — not gold.

r is picked from In-Sample (entry < 2024-01-01) skip counts, then the full
path is reported at that freeze. Do not retune on Out-of-Sample.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "risk2500_five_sys_20260917",
    REPO / "tools" / "risk2500_five_sys_20260917.py",
)
f = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["risk2500_five_sys_20260917"] = f
_SPEC.loader.exec_module(f)

STAMP = f.STAMP
OUT_DIR = f.OUT_DIR
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
IS_CUT = f.IS_CUT
IS_THROUGH = date(2023, 12, 31)
HTML_NAME = "monthly_riskfit.html"

# Halving grid Paul asked for. Search stops once IS BP-skips hit ~0, then
# binary-search the last gap for the largest such r (IS only).
GRID_PCT = (1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125)
BINSEARCH_ITERS = 8
BINSEARCH_TOL_PCT = 0.005  # percentage points
MIN_R_PCT = 0.001

ORIGINAL_SIBLING = f.ORIGINAL_REQUEST
ADDON_REQUEST = (
    "in addition to that what would we need to lower our 1% max stop loss at "
    "for each position to make room for all the subsequent positions? and how "
    "would that compare to any of the above"
)
PLAIN_ENGLISH = (
    "The 1% risk-to-stop stack fills the 2× buying-power cap, so later signals "
    "are scaled or skipped. Instead of selling a loser, the oldest name, or a "
    "winner to free room, shrink the frozen monthly risk percent (r) so every "
    "later signal still fits. r is a constant percent of beginning-of-month "
    "(BOM) Closed-only equity — still reset each month, still the same r for "
    "StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic "
    "Touch (MTS), and Rocket Launcher (RL). RSI dollars in = (r/100 × equity) "
    "÷ 0.0651 (In-Sample average-loser freeze; do not retune after 2024). "
    "Other systems: shares = risk dollars ÷ (entry − stop). Tight-stop clips "
    "to leftover buying power still happen (broker math, not a skip). A skip "
    "is only leftover buying power under $1. We pick the largest r with about "
    "zero In-Sample buying-power skips, then report the full book at that "
    "freeze. If one ultra-tight stop still eats the whole 2× even at tiny r, "
    "we say so and keep the residual skip count. This is not gold and not "
    "DailyRun. If the book only works by taking everything at postage-stamp "
    "size, that is HOLD — quality over trade count."
)


def _skip_bp(t: f.r.OverlayTrade) -> bool:
    return (not t.sized) and t.skip_reason in {"bp_empty", "bp_too_small"}


def _annotate(pack: dict[str, Any], *, risk_pct: float, through: date) -> dict[str, Any]:
    trades = pack["trades"]
    pack["risk_pct"] = float(risk_pct)
    pack["risk_frac"] = float(risk_pct) / 100.0
    pack["through"] = through.isoformat()
    pack["n_skip_bp_is"] = sum(1 for t in trades if _skip_bp(t) and t.opened < IS_CUT)
    pack["n_skip_bp_oos"] = sum(1 for t in trades if _skip_bp(t) and t.opened >= IS_CUT)
    pack["n_skip_bp_full"] = pack["led"].n_skip_bp
    pack["n_sized"] = sum(1 for t in trades if t.sized)
    pack["n_src"] = len(trades)
    pack["risk_on_250k"] = ACCOUNT * pack["risk_frac"]
    return pack


def run_fit_arm(
    static: list[f.r.OverlayTrade],
    *,
    risk_pct: float,
    rotate: str = "none",
    through: date = ASOF,
    label: Optional[str] = None,
) -> dict[str, Any]:
    rf = float(risk_pct) / 100.0
    if label is None:
        if rotate == "none":
            label = f"5-sys r={risk_pct:g}% take-all"
        else:
            label = f"5-sys 1% sell {rotate}"
    print(
        f"[run] {label} r={risk_pct:g}% rotate={rotate} through={through} "
        f"n_src={len(static)}",
        flush=True,
    )
    pack = f._run_arm(
        static,
        rank=f.FIVE_RANK,
        rotate=rotate,
        withdraw=False,
        label=label,
        risk_frac=rf,
        through=through,
    )
    return _annotate(pack, risk_pct=risk_pct, through=through)


def _is_zero_skip(pack: dict[str, Any]) -> bool:
    # IS-only runs: every skip is an IS skip. Full runs: use IS count for the pick.
    if date.fromisoformat(pack["through"]) <= IS_THROUGH:
        return pack["led"].n_skip_bp == 0
    return pack["n_skip_bp_is"] == 0


def _is_skip_n(pack: dict[str, Any]) -> int:
    if date.fromisoformat(pack["through"]) <= IS_THROUGH:
        return int(pack["led"].n_skip_bp)
    return int(pack["n_skip_bp_is"])


def search_r_is(static: list[f.r.OverlayTrade]) -> dict[str, Any]:
    """Largest r with ~0 IS BP-skips. Grid first, then binary search the last gap."""
    grid_packs: list[dict[str, Any]] = []
    first_zero: Optional[dict[str, Any]] = None
    last_pos: Optional[dict[str, Any]] = None
    for pct in GRID_PCT:
        pack = run_fit_arm(
            static,
            risk_pct=pct,
            through=IS_THROUGH,
            label=f"IS probe r={pct:g}%",
        )
        grid_packs.append(pack)
        n = _is_skip_n(pack)
        print(f"  [IS grid] r={pct:g}% skip_bp={n} scaled={pack['led'].n_scaled}", flush=True)
        if n == 0:
            first_zero = pack
            break
        last_pos = pack

    residual = False
    chosen_pct: float
    if first_zero is None:
        # Keep halving below the grid until 0 or we hit MIN_R_PCT.
        pct = GRID_PCT[-1]
        extra = last_pos
        while pct > MIN_R_PCT:
            pct = pct / 2.0
            extra = run_fit_arm(
                static,
                risk_pct=pct,
                through=IS_THROUGH,
                label=f"IS probe r={pct:g}%",
            )
            grid_packs.append(extra)
            n = _is_skip_n(extra)
            print(f"  [IS extra] r={pct:g}% skip_bp={n}", flush=True)
            if n == 0:
                first_zero = extra
                break
            last_pos = extra
        if first_zero is None:
            residual = True
            # Smallest r among those that minimize IS skips.
            min_n = min(_is_skip_n(p) for p in grid_packs)
            cands = [p for p in grid_packs if _is_skip_n(p) == min_n]
            # User: smallest r that minimizes skips when 0 is impossible.
            pick = min(cands, key=lambda p: p["risk_pct"])
            chosen_pct = pick["risk_pct"]
            print(
                f"  [IS] 0 skips impossible; min IS skips={min_n} at r={chosen_pct:g}%",
                flush=True,
            )
            return {
                "grid_is": grid_packs,
                "chosen_pct": chosen_pct,
                "residual": True,
                "residual_is_skips": min_n,
                "pick_note": (
                    f"Exactly 0 In-Sample buying-power skips was not reachable "
                    f"(tight-stop name can still consume leftover 2×). "
                    f"Smallest r that minimizes In-Sample skips is {chosen_pct:g}% "
                    f"({min_n} residual skips)."
                ),
            }

    lo_pct = first_zero["risk_pct"]  # 0 skips
    hi_pct = last_pos["risk_pct"] if last_pos is not None else lo_pct
    best_pct = lo_pct
    refine: list[dict[str, Any]] = []
    if last_pos is not None and hi_pct - lo_pct > BINSEARCH_TOL_PCT:
        print(
            f"  [IS binsearch] largest r with 0 skips in ({lo_pct:g}%, {hi_pct:g}%]",
            flush=True,
        )
        lo, hi = lo_pct, hi_pct
        for i in range(BINSEARCH_ITERS):
            if hi - lo < BINSEARCH_TOL_PCT:
                break
            mid = (lo + hi) / 2.0
            pack = run_fit_arm(
                static,
                risk_pct=mid,
                through=IS_THROUGH,
                label=f"IS binsearch {i+1} r={mid:.4f}%",
            )
            refine.append(pack)
            n = _is_skip_n(pack)
            print(f"  [IS mid] r={mid:.4f}% skip_bp={n}", flush=True)
            if n == 0:
                best_pct = mid
                lo = mid
            else:
                hi = mid
        chosen_pct = best_pct
    else:
        chosen_pct = lo_pct

    # Nice 4-decimal freeze; re-check IS at the rounded value if we rounded down.
    nice = round(chosen_pct, 4)
    if nice > chosen_pct:
        nice = round(chosen_pct - 0.00005, 4)
    if abs(nice - chosen_pct) > 1e-9:
        chk = run_fit_arm(
            static,
            risk_pct=nice,
            through=IS_THROUGH,
            label=f"IS rounded r={nice:g}%",
        )
        refine.append(chk)
        if _is_skip_n(chk) != 0 and not residual:
            # Rounding up broke zero-skip; keep the unrounded / last zero.
            nice = chosen_pct
    chosen_pct = nice
    print(f"  [IS pick] r={chosen_pct:g}% (largest with ~0 IS BP-skips)", flush=True)
    return {
        "grid_is": grid_packs,
        "refine_is": refine,
        "chosen_pct": chosen_pct,
        "residual": False,
        "residual_is_skips": 0,
        "pick_note": (
            f"Largest r with 0 In-Sample buying-power skips is {chosen_pct:g}% "
            f"(${ACCOUNT * chosen_pct / 100.0:,.2f} risk on a $250,000 start). "
            "Picked on In-Sample skip counts only (entry before 2024-01-01)."
        ),
    }


def _quality_tuple(st: dict[str, Any]) -> tuple[float, float, float, float]:
    def _f(key: str, default: float = 0.0) -> float:
        v = st.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    return (_f("win_pct"), _f("avg_pnl_pct"), _f("pf"), _f("max_dd"))


def _verdict(
    ctrl: dict[str, Any],
    fit: dict[str, Any],
    rots: list[dict[str, Any]],
    spy: dict[str, Any],
    *,
    residual: bool,
) -> str:
    c_wr, c_avg, c_pf, c_dd = _quality_tuple(ctrl["stats_is"])
    f_wr, f_avg, f_pf, f_dd = _quality_tuple(fit["stats_is"])
    r_pct = fit["risk_pct"]
    n_skip = fit["led"].n_skip_bp
    tiny = r_pct < 0.2
    better_quality = (
        f_wr >= c_wr - 0.25
        and f_avg >= c_avg
        and f_pf >= c_pf
        and (f_dd <= c_dd or f_dd <= 0)
    )
    worse_quality = f_avg < c_avg - 0.15 or f_pf < c_pf * 0.95
    lead = (
        f"HOLD — do not adopt r={r_pct:g}% from this In-Sample size search. "
        if (tiny or worse_quality or not better_quality)
        else f"LEAN KEEP (research-only) — r={r_pct:g}% quality did not collapse vs 1% skip. "
    )
    if tiny and not better_quality:
        lead = (
            f"HOLD — r={r_pct:g}% is “take every later signal at tiny size.” "
            "Quality over count; do not adopt. "
        )
    rot_bits = ", ".join(
        f"{a['label']} {format_money(a['led'].end_equity)}" for a in rots
    )
    extra = (
        f"Residual full-sample buying-power skips: {n_skip}. "
        if residual or n_skip
        else "Full-sample buying-power skips at the freeze: 0. "
    )
    return (
        f"{lead}"
        f"To take later signals without selling, we would need to lower 1% to "
        f"{r_pct:g}% (~{format_money(ACCOUNT * r_pct / 100.0)} risk on $250k). "
        f"{extra}"
        f"5-sys 1% skip ends {format_money(ctrl['led'].end_equity)}; "
        f"r={r_pct:g}% take-all ends {format_money(fit['led'].end_equity)}; "
        f"SPY total-return {format_money(spy['tr_end'])}. "
        f"Rotation paper endings: {rot_bits}. "
        "In-Sample win% / Avg% / profit factor vs 1% skip: "
        f"{f_wr:.2f}% / {f_avg:.3f}% / {f_pf:.3f} vs "
        f"{c_wr:.2f}% / {c_avg:.3f}% / {c_pf:.3f}. "
        "Read 2010–2012. Not gold. Not DailyRun."
    )


def _grid_table(rows: list[dict[str, Any]], *, chosen_pct: float) -> str:
    head = f._sortable_head(
        [
            ("r % of equity", "num"),
            ("$ risk on $250k", "num"),
            ("Window", "text"),
            ("BP-skip (IS)", "num"),
            ("BP-skip (OOS)", "num"),
            ("BP-skip (full)", "num"),
            ("Full fills", "num"),
            ("Scaled (tight-stop clip)", "num"),
            ("Sized closed N", "num"),
            ("Ending equity", "num"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("Interest paid", "num"),
            ("Peak deployed", "num"),
            ("Win % (FULL)", "num"),
            ("Avg PnL % (FULL)", "num"),
            ("Profit factor (FULL)", "num"),
            ("Max DD % (FULL)", "num"),
            ("Pick?", "text"),
        ]
    )
    body = ""
    for p in rows:
        st = p.get("stats_full") or {}
        is_fit = (
            abs(p["risk_pct"] - chosen_pct) < 1e-9
            and p.get("rotate", "none") == "none"
        )
        pick = "YES — largest r with ~0 IS skips" if is_fit else ""
        is_oos = p.get("n_skip_bp_is"), p.get("n_skip_bp_oos"), p.get("n_skip_bp_full")
        body += (
            "<tr>"
            f"<td>{p['risk_pct']:g}</td>"
            f"<td>{format_money(p['risk_on_250k'])}</td>"
            f"<td>{html_mod.escape(p.get('through') or '')}</td>"
            f"<td>{is_oos[0]}</td>"
            f"<td>{is_oos[1] if is_oos[1] is not None else '—'}</td>"
            f"<td>{is_oos[2]}</td>"
            f"<td>{p['led'].n_full}</td>"
            f"<td>{p['led'].n_scaled}</td>"
            f"<td>{p['n_sized_closed']}</td>"
            f"<td>{format_money(p['led'].end_equity)}</td>"
            f"<td>{format_money(p['led'].eq_2010)}</td>"
            f"<td>{format_money(p['led'].eq_2011)}</td>"
            f"<td>{format_money(p['led'].eq_2012)}</td>"
            f"<td>{format_money(p['led'].interest)}</td>"
            f"<td>{format_money(p['led'].peak_reserved)}</td>"
            f"<td>{f.r._fmt_kind(st.get('win_pct'), 'pct')}</td>"
            f"<td>{f.r._fmt_kind(st.get('avg_pnl_pct'), 'pct')}</td>"
            f"<td>{f.r._fmt_kind(st.get('pf'), 'num')}</td>"
            f"<td>{f.r._fmt_kind(st.get('max_dd'), 'pct')}</td>"
            f"<td class=\"small\">{html_mod.escape(pick)}</td>"
            "</tr>"
        )
    if rows:
        last = rows[-1]
        body += (
            '<tr class="total-row"><th>Total / last row</th>'
            f"<td>{format_money(last['risk_on_250k'])}</td>"
            "<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>"
            f"<td>{format_money(last['led'].end_equity)}</td>"
            "<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>"
            "<td>—</td><td>—</td><td class=\"small\">Pinned last row</td></tr>"
        )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "In-Sample (IS) = entry before 2024-01-01; Out-of-Sample (OOS) report-only. "
        "r pick uses IS buying-power skips only.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _fit_path_table(
    arms: list[dict[str, Any]],
    spy: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("Cap / extra rule", "text"),
            ("Ending equity", "num"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("Interest paid", "num"),
            ("Peak deployed", "num"),
            ("Peak loan", "num"),
            ("Sized closed N", "num"),
            ("Rotated / BP-skip", "text"),
            ("Win % (FULL)", "num"),
            ("Avg PnL % (FULL)", "num"),
            ("Profit factor (FULL)", "num"),
            ("Max DD % (FULL)", "num"),
            ("Read as", "text"),
        ]
    )

    def _m(v: Any) -> str:
        if v is None:
            return "—"
        return format_money(float(v))

    rows_html = ""
    spy_row = (
        "<tr>"
        "<td>SPY buy-hold $250k (total return)</td>"
        "<td class=\"small\">Sit in the S&amp;P 500 tracker (SPY); dividends reinvested via Adjusted Close</td>"
        f"<td>{_m(spy['tr_end'])}</td>"
        f"<td>{_m(spy['years'].get(2010, {}).get('tr'))}</td>"
        f"<td>{_m(spy['years'].get(2011, {}).get('tr'))}</td>"
        f"<td>{_m(spy['years'].get(2012, {}).get('tr'))}</td>"
        f"<td>{_m(0)}</td>"
        f"<td>{_m(spy['tr_end'])}</td>"
        f"<td>{_m(0)}</td>"
        "<td>1</td><td>0 / 0</td>"
        "<td>—</td><td>—</td><td>—</td><td>—</td>"
        "<td class=\"small\">The benchmark. Not capacity fiction.</td>"
        "</tr>"
    )
    rows_html += spy_row
    rows_html += (
        "<tr>"
        "<td>SPY buy-hold $250k (price-only)</td>"
        "<td class=\"small\">Close / Close — no dividends</td>"
        f"<td>{_m(spy['price_end'])}</td>"
        f"<td>{_m(spy['years'].get(2010, {}).get('price'))}</td>"
        f"<td>{_m(spy['years'].get(2011, {}).get('price'))}</td>"
        f"<td>{_m(spy['years'].get(2012, {}).get('price'))}</td>"
        f"<td>{_m(0)}</td>"
        f"<td>{_m(spy['price_end'])}</td>"
        f"<td>{_m(0)}</td>"
        "<td>1</td><td>0 / 0</td>"
        "<td>—</td><td>—</td><td>—</td><td>—</td>"
        "<td class=\"small\">Same shares, ignores dividends.</td>"
        "</tr>"
    )
    for a in arms:
        led = a["led"]
        st = a.get("stats_full") or {}
        rows_html += (
            "<tr>"
            f"<td>{html_mod.escape(a['label'])}</td>"
            f"<td class=\"small\">{html_mod.escape(a.get('cap') or '')}</td>"
            f"<td>{_m(led.end_equity)}</td>"
            f"<td>{_m(led.eq_2010)}</td>"
            f"<td>{_m(led.eq_2011)}</td>"
            f"<td>{_m(led.eq_2012)}</td>"
            f"<td>{_m(led.interest)}</td>"
            f"<td>{_m(led.peak_reserved)}</td>"
            f"<td>{_m(led.peak_loan)}</td>"
            f"<td>{int(a['n_sized_closed'])}</td>"
            f"<td>{led.n_rotate} / {led.n_skip_bp}</td>"
            f"<td>{f.r._fmt_kind(st.get('win_pct'), 'pct')}</td>"
            f"<td>{f.r._fmt_kind(st.get('avg_pnl_pct'), 'pct')}</td>"
            f"<td>{f.r._fmt_kind(st.get('pf'), 'num')}</td>"
            f"<td>{f.r._fmt_kind(st.get('max_dd'), 'pct')}</td>"
            f"<td class=\"small\">{html_mod.escape(a.get('read') or '')}</td>"
            "</tr>"
        )
    return (
        '<p class="small">Same house Closed pins. Only the monthly risk percent / '
        "rotation rule changes. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{rows_html}</tbody></table></div>"
    )


def build_html(
    *,
    ctrl: dict[str, Any],
    fit: dict[str, Any],
    rots: list[dict[str, Any]],
    grid_full: list[dict[str, Any]],
    grid_is: list[dict[str, Any]],
    spy: dict[str, Any],
    verdict: str,
    pick_note: str,
    residual: bool,
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    r_pct = fit["risk_pct"]
    r_dol = ACCOUNT * r_pct / 100.0
    arms_all = [ctrl] + rots + [fit]
    for a, cap, read in (
        (
            ctrl,
            "5 systems · open ≤ 2× · 10.5% · 1% BOM · skip if no buying power (BP)",
            "Sibling control. Later signals skipped when leftover BP < $1.",
        ),
        (
            fit,
            f"5 systems · open ≤ 2× · 10.5% · r={r_pct:g}% BOM · take all (clip OK)",
            "This page’s arm. r picked on In-Sample skip counts.",
        ),
    ):
        a["cap"] = cap
        a["read"] = read
    rot_caps = {
        "loser": "1% BOM · at 2× cap, sell worst $ mark-to-market (last close vs entry)",
        "oldest": "1% BOM · at 2× cap, sell longest hold",
        "winner": "1% BOM · at 2× cap, sell best $ open mark (last close vs entry)",
    }
    for a in rots:
        a["cap"] = rot_caps.get(a["rotate"], a["rotate"])
        a["read"] = "Sibling rotation. HOLD — in-sample horse-race."

    cards = f"""
  <div class="card card-shared">
    <h3>Lower 1% to this r (IS pick)</h3>
    <div class="metric">{r_pct:g}%</div>
    <div class="small">{format_money(r_dol)} risk on a $250,000 start</div>
    <div class="small">Full-sample BP-skip {fit['led'].n_skip_bp} · IS skip {fit['n_skip_bp_is']} · OOS skip {fit['n_skip_bp_oos']}</div>
  </div>
  <div class="card">
    <h3>r={r_pct:g}% take-all ending equity</h3>
    <div class="metric">{format_money(fit['led'].end_equity)}</div>
    <div class="small">2010 {format_money(fit['led'].eq_2010)} · 2011 {format_money(fit['led'].eq_2011)} · 2012 {format_money(fit['led'].eq_2012)}</div>
    <div class="small">Interest {format_money(fit['led'].interest)}</div>
  </div>
  <div class="card">
    <h3>1% skip (sibling control)</h3>
    <div class="metric">{format_money(ctrl['led'].end_equity)}</div>
    <div class="small">BP-skip {ctrl['led'].n_skip_bp} · scaled {ctrl['led'].n_scaled}</div>
    <div class="small">2010 {format_money(ctrl['led'].eq_2010)}</div>
  </div>
  <div class="card card-shared">
    <h3>SPY $250k since 2010-01-04 (total return)</h3>
    <div class="metric">{format_money(spy['tr_end'])}</div>
    <div class="small">{spy['tr_mult']:.2f}× · price-only {format_money(spy['price_end'])}</div>
  </div>"""
    for a in rots:
        cards += f"""
  <div class="card">
    <h3>{html_mod.escape(a['label'])}</h3>
    <div class="metric">{format_money(a['led'].end_equity)}</div>
    <div class="small">Rotates {a['led'].n_rotate} · BP-skip {a['led'].n_skip_bp}</div>
  </div>"""

    compare_sections = ""
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01. r was picked here (skip count, not quality). Do not retune OOS."),
        ("OOS", "Out-of-Sample — report-only. Wallet dollars already felt the IS path."),
        ("FULL", verdict),
    ):
        cols = [(ctrl["label"], ctrl[col_map[sl]])]
        for a in rots:
            cols.append((a["label"], a[col_map[sl]]))
        cols.append((fit["label"], fit[col_map[sl]]))
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""

    is_probe_rows = []
    for p in grid_is:
        is_probe_rows.append(p)
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    residual_html = ""
    if residual:
        residual_html = (
            '<div class="warn"><strong>Zero buying-power skips was not reachable.</strong> '
            "At least one tight-stop name still wants more notional than leftover buying "
            "power after prior fills, then leftover buying power falls under $1 and the "
            f"next signal skips. {html_mod.escape(pick_note)}</div>"
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lower 1% so later signals fit — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly risk-fit — lower 1% so all later 5-system signals fit</h1>
<p class="sub">
Stamp <code>{STAMP}</code> · <code>{HTML_NAME}</code>. Research only.
<strong>Not gold. Not DailyRun.</strong>
Sits beside the sibling
<a href="monthly.html">monthly.html</a> /
<a href="compare.html">compare.html</a>
(1% skip / sell loser / oldest / winner / $7,500 wires). Does not overwrite them.
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<p class="small">Original proceed job (sibling page):</p>
<blockquote>{html_mod.escape(ORIGINAL_SIBLING)}</blockquote>
<p class="small">Add-on for this page (quoted):</p>
<blockquote>{html_mod.escape(ADDON_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="lead">
<h2>Headline</h2>
<p>To take every later signal without selling a loser / oldest / winner, we would
need to lower the monthly 1% risk-to-stop to
<strong>{r_pct:g}%</strong>
(~<strong>{format_money(r_dol)}</strong> risk on a $250,000 start;
still reset from beginning-of-month Closed-only equity).</p>
<p>{html_mod.escape(pick_note)}</p>
<p>That book ends at {format_money(fit['led'].end_equity)} vs 1% skip
{format_money(ctrl['led'].end_equity)} vs SPY total-return
{format_money(spy['tr_end'])}. Full-sample buying-power skips:
{fit['led'].n_skip_bp} (IS {fit['n_skip_bp_is']}, OOS {fit['n_skip_bp_oos']}).
Scaled tight-stop clips (not skips): {fit['led'].n_scaled}.</p>
</div>
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
{residual_html}
<div class="warn">
<strong>Selection label.</strong> r was searched on In-Sample buying-power skip
counts (and a small binary search in the last gap). That is in-sample selection
of the size knob. Out-of-Sample is report-only — we did not shop r on OOS quality.
Relative Strength Index (RSI) average-loser 6.51% stays frozen. Tight-stop clip
to leftover buying power is allowed. Skip = leftover buying power under $1.
Margin interest is 10.5% / 365 daily compound on the debit.
</div>
<div class="cards">{cards}</div>
<section>
<h2>What we would need to lower 1% to (r grid + pick)</h2>
<p class="small">Full-sample wallet at each published r. The pick is the largest
r with about zero In-Sample buying-power skips (or the smallest r that minimizes
skips if zero is impossible). Click headers to sort.</p>
{_grid_table(grid_full, chosen_pct=r_pct)}
</section>
<section>
<h2>In-Sample probe (used to pick r)</h2>
<p class="small">Wallet stopped at {IS_THROUGH.isoformat()} so later years cannot
leak into the pick. Ending equity here is IS-window only — do not compare it to
full-sample endings. Click headers to sort.</p>
{_grid_table(is_probe_rows, chosen_pct=r_pct)}
</section>
<section>
<h2>Compare vs skip / sell-loser / oldest / winner / SPY</h2>
{_fit_path_table(arms_all, spy)}
</section>
<section>
<h2>Year-end equity vs SPY</h2>
{f._year_vs_spy_table(arms_all, spy)}
</section>
{compare_sections}
<section>
<h2>Buying-power + interest ledger (r={r_pct:g}% take-all)</h2>
{f._ledger_table(fit['snaps'])}
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Sibling monthly (untouched):
<a href="monthly.html">monthly.html</a>.
Sibling compare (untouched):
<a href="compare.html">compare.html</a>.
Acronyms: StockBee (SB); Relative Strength Index (RSI); Volume Zone (VZ);
Magic Touch (MTS); Rocket Launcher (RL); In-Sample (IS); Out-of-Sample (OOS);
buying power (BP); beginning-of-month (BOM); S&amp;P 500 tracker (SPY);
DailyRun = the live wired systems (this page is not wired).</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = f.spy_buyhold()
    five_static = f.load_static(f.FIVE)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"systems five: {', '.join(f.FIVE)}",
        "r pick: IS buying-power skip count (entry < 2024-01-01); binary search last gap",
        "full-sample report at frozen r; OOS report-only",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "fill order: older closes; DailyRun system then symbol; same-day exits",
        "interest: 10.5% / 365 daily compound on max(0, −cash)",
        "tight-stop clip to remaining BP allowed; skip only if BP < $1",
        "sibling 1% / rotation pages not overwritten",
    ]

    search = search_r_is(five_static)
    chosen_pct = float(search["chosen_pct"])
    residual = bool(search["residual"])

    print("[full] 1% skip + rotations + r grid + chosen", flush=True)
    ctrl = run_fit_arm(
        five_static,
        risk_pct=1.0,
        rotate="none",
        label="5-sys 1% skip (control)",
    )
    rot_loser = run_fit_arm(
        five_static,
        risk_pct=1.0,
        rotate="loser",
        label="5-sys 1% sell biggest loser",
    )
    rot_oldest = run_fit_arm(
        five_static,
        risk_pct=1.0,
        rotate="oldest",
        label="5-sys 1% sell oldest",
    )
    rot_winner = run_fit_arm(
        five_static,
        risk_pct=1.0,
        rotate="winner",
        label="5-sys 1% sell most profitable",
    )
    rots = [rot_loser, rot_oldest, rot_winner]

    grid_full: list[dict[str, Any]] = []
    seen: set[float] = set()
    publish_pcts: list[float] = []
    for p in search["grid_is"]:
        publish_pcts.append(p["risk_pct"])
        if _is_skip_n(p) == 0:
            break
    if chosen_pct not in publish_pcts:
        publish_pcts.append(chosen_pct)
    for pct in publish_pcts:
        key = round(pct, 6)
        if key in seen:
            continue
        seen.add(key)
        if abs(pct - 1.0) < 1e-12:
            grid_full.append(ctrl)
            continue
        grid_full.append(
            run_fit_arm(
                five_static,
                risk_pct=pct,
                rotate="none",
                label=f"5-sys r={pct:g}% take-all",
            )
        )

    fit = next(
        (p for p in grid_full if abs(p["risk_pct"] - chosen_pct) < 1e-9 and p["rotate"] == "none"),
        None,
    )
    if fit is None:
        fit = run_fit_arm(
            five_static,
            risk_pct=chosen_pct,
            rotate="none",
            label=f"5-sys r={chosen_pct:g}% take-all",
        )
        grid_full.append(fit)

    verdict = _verdict(ctrl, fit, rots, spy, residual=residual)
    print(f"[verdict] {verdict}", flush=True)

    f.r.write_overlay_csv(fit["trades"], OUT_DIR / "ALL_overlay_five_riskfit.csv")

    now = datetime.now(tz=ET)
    html = build_html(
        ctrl=ctrl,
        fit=fit,
        rots=rots,
        grid_full=grid_full,
        grid_is=search["grid_is"] + list(search.get("refine_is") or []),
        spy=spy,
        verdict=verdict,
        pick_note=search["pick_note"],
        residual=residual,
        sources=sources,
        generated=now,
    )
    out_html = OUT_DIR / HTML_NAME
    out_html.write_text(html, encoding="utf-8")

    summary = {
        "chosen_r_pct": chosen_pct,
        "risk_on_250k": ACCOUNT * chosen_pct / 100.0,
        "residual": residual,
        "residual_is_skips": search.get("residual_is_skips"),
        "pick_note": search["pick_note"],
        "fit_end": fit["led"].end_equity,
        "fit_2010": fit["led"].eq_2010,
        "fit_2011": fit["led"].eq_2011,
        "fit_2012": fit["led"].eq_2012,
        "fit_skip_full": fit["led"].n_skip_bp,
        "fit_skip_is": fit["n_skip_bp_is"],
        "fit_skip_oos": fit["n_skip_bp_oos"],
        "fit_scaled": fit["led"].n_scaled,
        "ctrl_end": ctrl["led"].end_equity,
        "ctrl_skip": ctrl["led"].n_skip_bp,
        "rot_loser_end": rot_loser["led"].end_equity,
        "rot_oldest_end": rot_oldest["led"].end_equity,
        "rot_winner_end": rot_winner["led"].end_equity,
        "spy_tr_end": spy["tr_end"],
        "verdict": verdict,
    }
    (OUT_DIR / "riskfit_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"wrote {out_html}", flush=True)
    print(json.dumps({k: v for k, v in summary.items() if k != "verdict"}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
