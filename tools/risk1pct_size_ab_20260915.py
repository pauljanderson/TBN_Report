#!/usr/bin/env python3
"""1% risk-to-stop size overlay vs Kelly size A/B (research only).

Delta from ``kelly_size_ab_20260915``: same Closed pins, same Kelly arms
(not retuned), plus SIZE_risk1pct_stop* overlays.

Rule: dollars = (equity_at_fill * 0.01) / stop_loss_pct
  stop_loss_pct = |entry − STOP_PRICE| / entry from Closed (not invented).

Not gold. Not DailyRun. Entries / exits frozen.
"""
from __future__ import annotations

import csv
import html as html_mod
import importlib.util
import json
import math
import sys
from collections import Counter
from datetime import date
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
)
from kelly_sizing import (  # noqa: E402
    KellyFit,
    risk_notional,
    slot_dollars,
)

_KELLY_AB = REPO / "tools" / "kelly_size_ab_20260915.py"
_spec = importlib.util.spec_from_file_location("kelly_size_ab_20260915", _KELLY_AB)
kab = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["kelly_size_ab_20260915"] = kab
_spec.loader.exec_module(kab)

STAMP = "risk1pct_size_ab_20260915"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
IS_CUT = kab.IS_CUT
INIT = DEFAULT_INITIAL_ACCOUNT
DEPLOYABLE = kab.DEPLOYABLE  # $500k × 2 × 0.6 = $600k
MIN_RISK_PCT = 0.002  # same floor as kelly_sizing.risk_notional
RISK_FRAC = 0.01

ORIGINAL_REQUEST = (
    "what if we try a different approach to position sizing. what if we use 1% "
    "of our current portfolio balance as the maximum loss expected on any trade. "
    "for example if we are currently at $526,896 and we are entering a trade "
    "where the stop loss will be 6% below entry, then we would invest $87,816 "
    "in that stock, as the most we expect to lose would be $5,268.96. How would "
    "this look compared to those kelly runs and control?"
)
PLAIN_ENGLISH = (
    "Instead of a fixed dollar slot or Kelly fraction, size each fill so that "
    "if the stop hits, you lose about 1% of the account as it stood that day. "
    "Example: account $526,896, stop 6% under entry → buy $87,816 of stock "
    "(1% of $526,896 is $5,269). Compare that to the existing Kelly A/B and "
    "equal-slot Control. Kelly is a bet-size rule from win rate and payoff. "
    "Relative Strength Index (RSI) here is the house 149-name book (not "
    "RSIN_PaulScore5_IS). Volume Zone (VZ) and Break and ReTest (BRT) already "
    "write a price stop. RSI has no live stop — size uses labeled "
    "RSI_STOP_PROXY = Average True Range (ATR) % at the trigger bar, not a "
    "silent 6%."
)
FOLLOWUP_REQUEST = (
    "for this report file:///C:/Users/songg/Downloads/stockresearch/drive/"
    "paul_experiments/risk1pct_size_ab_20260915/compare.html how did you "
    "calculate the peak deployed? why are these so large - was it because the "
    "portfolio grew so much? $2.4B seems like a lot. again, the MAX potential "
    "downside of any trade should be 1% of the cash total."
)
FOLLOWUP_PLAIN = (
    "Peak deployed is the most dollars we had in stocks at once. $2.4 billion "
    "looks insane. Paul wants to know if that is because the account snowballed, "
    "because many names were open at once, because a tight stop sized a huge "
    "position, or because we measured the wrong thing. He is restating the "
    "rule: the most you can lose on any one trade is 1% of cash -- not "
    "'put 1% of cash into the stock.'"
)
RSI_FOLLOWUP_REQUEST = (
    "also, for that same report i don't understand how RSI has no entries "
    "when using the 1% rule. ALL entries should be the same, it's just a "
    "different position size"
)
RSI_FOLLOWUP_PLAIN = (
    "The 1% rule only changes how many dollars we put on each fill. Every "
    "Relative Strength Index (RSI) trade Control took should still be there. "
    "Showing N/A or zero RSI entries is wrong — we skipped them because "
    "STOP_PRICE was 0, which treated a missing stop as “no trade.”"
)
# Labeled proxy when Closed has no price stop (RSI engine writes STOP_PRICE=0).
# Source: ATR_PCT_AT_TRIGGER on the same Closed row (Average True Range % at
# the trigger bar). Not a live stop. Not a silent 6%.
RSI_STOP_PROXY = "RSI_STOP_PROXY"
RSI_STOP_PROXY_COL = "ATR_PCT_AT_TRIGGER"

sortable_th = kab.sortable_th
SORTABLE_TH_CSS = kab.SORTABLE_TH_CSS
SORTABLE_TABLE_SCRIPT = kab.SORTABLE_TABLE_SCRIPT
_fmt_pct = kab._fmt_pct
_fmt_num = kab._fmt_num
load_trades = kab.load_trades
slice_trades = kab.slice_trades
risk_pct = kab.risk_pct
fit_from_trades = kab.fit_from_trades
book_stats = kab.book_stats
resolve_closed = kab.resolve_closed
SysSpec = kab.SysSpec
Trade = kab.Trade


def usable_risk_pct(t: Any) -> Optional[float]:
    rp = risk_pct(t)
    if rp is None or rp < MIN_RISK_PCT:
        return None
    return rp


def load_atr_fracs(path: Path) -> list[Optional[float]]:
    """ATR_PCT_AT_TRIGGER as a fraction, same row filter as load_trades."""
    out: list[Optional[float]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = kab._parse_date(raw.get("DATE_OPENED") or raw.get("DATE OPENED"))
            pnl = kab._parse_num(raw.get("PNL_PCT") or raw.get("PNL %") or raw.get("PNL%"))
            entry = kab._parse_num(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE"))
            if opened is None or pnl is None or entry is None or entry <= 0:
                continue
            atr = kab._parse_num(
                raw.get("ATR_PCT_AT_TRIGGER") or raw.get("ATR_PCT")
            )
            if atr is None or atr <= 0 or not math.isfinite(atr):
                out.append(None)
            else:
                out.append(float(atr) / 100.0)
    return out


def is_avg_abs_loss_frac(trades: Sequence[Any]) -> Optional[float]:
    """IS-only mean |loss| of losing fills (fraction). Sensitivity note, not size."""
    losses = [
        -t.pnl_pct / 100.0
        for t in slice_trades(list(trades), "IS")
        if t.pnl_pct < 0
    ]
    if not losses:
        return None
    return sum(losses) / len(losses)


def overlay_risks(
    trades: Sequence[Any],
    atr_fracs: Sequence[Optional[float]],
    *,
    is_loss_fallback: Optional[float],
) -> tuple[list[Optional[float]], dict[str, int]]:
    """Price stop first; else labeled ATR proxy; else IS avg |loss|."""
    n = len(trades)
    risks: list[Optional[float]] = [None] * n
    n_price = n_atr = n_is_loss = n_miss = 0
    for i, t in enumerate(trades):
        rp = usable_risk_pct(t)
        if rp is not None:
            risks[i] = rp
            n_price += 1
            continue
        atr = atr_fracs[i] if i < len(atr_fracs) else None
        if atr is not None and atr >= MIN_RISK_PCT:
            risks[i] = atr
            n_atr += 1
            continue
        if is_loss_fallback is not None and is_loss_fallback >= MIN_RISK_PCT:
            risks[i] = is_loss_fallback
            n_is_loss += 1
            continue
        n_miss += 1
    return risks, {
        "price": n_price,
        "atr": n_atr,
        "is_loss": n_is_loss,
        "miss": n_miss,
    }


def pick_risk(
    t: Any,
    i: int,
    risks: Optional[Sequence[Optional[float]]],
) -> Optional[float]:
    if risks is not None:
        if i < 0 or i >= len(risks):
            return None
        rp = risks[i]
        if rp is None or rp < MIN_RISK_PCT:
            return None
        return float(rp)
    return usable_risk_pct(t)


def atr_stats(atr_fracs: Sequence[Optional[float]]) -> dict[str, Any]:
    vals = [float(x) for x in atr_fracs if x is not None and x > 0]
    vals.sort()

    def _q(p: float) -> Optional[float]:
        if not vals:
            return None
        i = int(round(p * (len(vals) - 1)))
        return vals[i]

    return {
        "n": len(atr_fracs),
        "n_ok": len(vals),
        "min": vals[0] if vals else None,
        "p50": _q(0.5),
        "p90": _q(0.9),
        "max": vals[-1] if vals else None,
        "mean": (sum(vals) / len(vals)) if vals else None,
    }


def sensitivity_note(*, seed: float = INIT) -> str:
    s5 = seed * RISK_FRAC / 0.05
    s10 = seed * RISK_FRAC / 0.10
    return (
        f"Sensitivity (note, not a second universe): at ${seed:,.0f}, a flat "
        f"5% {RSI_STOP_PROXY} sizes ${s5:,.0f}; a flat 10% {RSI_STOP_PROXY} "
        f"sizes ${s10:,.0f} (half as large)."
    )


def stop_coverage(
    trades: Sequence[Any],
    risks: Optional[Sequence[Optional[float]]] = None,
) -> dict[str, Any]:
    n = len(trades)
    usable = 0
    missing = 0
    tiny = 0
    price_risks: list[float] = []
    for t in trades:
        rp = risk_pct(t)
        if rp is None:
            missing += 1
            continue
        if rp < MIN_RISK_PCT:
            tiny += 1
            continue
        usable += 1
        price_risks.append(rp)
    price_risks.sort()

    def _q(vals: list[float], p: float) -> Optional[float]:
        if not vals:
            return None
        i = int(round(p * (len(vals) - 1)))
        return vals[i]

    overlay = [r for r in (risks or []) if r is not None and r >= MIN_RISK_PCT]
    overlay.sort()
    return {
        "n": n,
        "usable": usable,
        "missing": missing,
        "tiny": tiny,
        "no_stop": missing + tiny,
        "risk_min": price_risks[0] if price_risks else None,
        "risk_p50": _q(price_risks, 0.5),
        "risk_p90": _q(price_risks, 0.9),
        "risk_max": price_risks[-1] if price_risks else None,
        "risk_mean": (sum(price_risks) / len(price_risks)) if price_risks else None,
        "overlay_usable": len(overlay),
        "overlay_min": overlay[0] if overlay else None,
        "overlay_p50": _q(overlay, 0.5),
        "overlay_mean": (sum(overlay) / len(overlay)) if overlay else None,
        "overlay_max": overlay[-1] if overlay else None,
    }


def _losing_streak(trades: Sequence[Any]) -> int:
    cur = peak = 0
    for t in trades:
        if t.pnl_pct < 0:
            cur += 1
            if cur > peak:
                peak = cur
        else:
            cur = 0
    return peak


def _span(t: Any) -> tuple[date, date]:
    opened = t.opened
    closed = t.closed or t.opened
    if closed < opened:
        closed = opened
    return opened, closed


def peak_exposure(
    trades: Sequence[Any],
    notionals: Sequence[float],
    *,
    equity_at: Optional[Sequence[float]] = None,
    equity_ref: float,
    risks: Optional[Sequence[Optional[float]]] = None,
) -> dict[str, Any]:
    """Concurrent peak notional and peak stop-risk (not a sum of all history).

    Peak notional $ = max over the calendar sweep of sum(position $ of names
    still open that day). Opens process before closes on the same day.
    Peak risk $ = same sweep of sum(position $ × stop%). That is *not* the
    same as peak notional: a 3% stop on a huge fill is a lot of stock but
    still only 1% of that fill's cash if the 1% rule was applied.
    """
    n = len(trades)
    eq = list(equity_at) if equity_at is not None else [float(equity_ref)] * n
    if len(eq) != n:
        eq = [float(equity_ref)] * n
    events: list[tuple[date, int, int, float]] = []
    for i, t in enumerate(trades):
        opened, closed = _span(t)
        ntl = float(notionals[i]) if i < len(notionals) else 0.0
        events.append((opened, 0, i, ntl))
        events.append((closed, 1, i, ntl))
    events.sort(key=lambda x: (x[0], x[1], -x[3], trades[x[2]].symbol, x[2]))

    open_idx: set[int] = set()
    peak_n = 0.0
    peak_r = 0.0
    peak_names = 0
    peak_n_date: Optional[date] = None
    peak_r_date: Optional[date] = None
    peak_n_ids: list[int] = []
    peak_r_ids: list[int] = []

    def _risk_of(j: int) -> float:
        rp = pick_risk(trades[j], j, risks) or 0.0
        return float(notionals[j]) * rp

    for d, kind, i, _ntl in events:
        if kind == 0:
            open_idx.add(i)
        else:
            open_idx.discard(i)
        cur_n = sum(float(notionals[j]) for j in open_idx)
        cur_r = sum(_risk_of(j) for j in open_idx)
        if cur_n > peak_n:
            peak_n = cur_n
            peak_n_date = d
            peak_n_ids = sorted(open_idx)
        if cur_r > peak_r:
            peak_r = cur_r
            peak_r_date = d
            peak_r_ids = sorted(open_idx)
        if len(open_idx) > peak_names:
            peak_names = len(open_idx)

    cash_then = float(equity_ref)
    if peak_r_ids:
        cash_then = max((float(eq[j]) for j in peak_r_ids), default=float(equity_ref))
    max_single = max((float(x) for x in notionals), default=0.0)
    max_eq = max((float(x) for x in eq), default=float(equity_ref))
    seed_pct = (100.0 * peak_r / equity_ref) if equity_ref > 0 else 0.0
    cash_pct = (100.0 * peak_r / cash_then) if cash_then > 0 else 0.0
    return {
        "peak_notional": peak_n,
        "peak_notional_date": peak_n_date.isoformat() if peak_n_date else None,
        "peak_notional_names": len(peak_n_ids),
        "peak_conc_risk_d": peak_r,
        "peak_risk_date": peak_r_date.isoformat() if peak_r_date else None,
        "peak_risk_names": len(peak_r_ids),
        "peak_conc_risk_pct": seed_pct,
        "peak_risk_pct_of_cash": cash_pct,
        "peak_cash_then": cash_then,
        "peak_conc_names": peak_names,
        "max_single_notional": max_single,
        "max_path_equity": max_eq,
    }


def peak_concurrent_risk(
    trades: Sequence[Any],
    notionals: Sequence[float],
    *,
    equity_ref: float,
    risks: Optional[Sequence[Optional[float]]] = None,
) -> tuple[float, float, int]:
    """Back-compat wrapper: peak risk $, % of equity_ref, peak names."""
    ex = peak_exposure(trades, notionals, equity_ref=equity_ref, risks=risks)
    return (
        float(ex["peak_conc_risk_d"]),
        float(ex["peak_conc_risk_pct"]),
        int(ex["peak_conc_names"]),
    )


def size_risk1pct(
    trades: Sequence[Any],
    *,
    seed: float,
    path_dependent: bool,
    cap_mode: str,
    risks: Optional[Sequence[Optional[float]]] = None,
) -> tuple[list[float], list[float], int]:
    """Return notionals + equity_at_fill aligned with ``trades`` order.

    ``cap_mode``: ``none`` | ``equity`` | ``host``.
    Path-dependent equity = seed + realized $ of fills already *closed*
    on or before this open date (same-day close is available). No mark-to-market.
    Same-day opens share the morning equity (do not compound within the day).
    """
    n = len(trades)
    notionals = [0.0] * n
    eq_at = [float(seed)] * n
    if n == 0:
        return notionals, eq_at, 0

    order = sorted(range(n), key=lambda i: (trades[i].opened, trades[i].symbol, i))
    pending: list[tuple[date, float]] = []
    equity = float(seed)
    n_skip = 0
    last_open: Optional[date] = None
    day_eq = float(seed)

    for i in order:
        t = trades[i]
        if path_dependent:
            if last_open is None or t.opened != last_open:
                while pending and pending[0][0] <= t.opened:
                    _cd, pnl = heappop(pending)
                    equity += pnl
                day_eq = equity
                last_open = t.opened
            eq_use = day_eq
        else:
            eq_use = float(seed)
        eq_at[i] = eq_use
        rp = pick_risk(t, i, risks)
        if rp is None:
            n_skip += 1
            notionals[i] = 0.0
            continue
        cap: Optional[float]
        if cap_mode == "equity":
            cap = eq_use
        elif cap_mode == "host":
            cap = DEPLOYABLE
        else:
            cap = None
        raw = risk_notional(
            q=RISK_FRAC,
            bankroll=eq_use,
            risk_pct=rp,
            sheet_cap=cap,
            min_risk_pct=MIN_RISK_PCT,
        )
        ntl = float(raw) if raw is not None else 0.0
        notionals[i] = ntl
        if path_dependent:
            pnl = (t.pnl_pct / 100.0) * ntl
            heappush(pending, (t.closed or t.opened, pnl))
    return notionals, eq_at, n_skip


def kelly_arms_and_slots(spec: Any, fit: KellyFit) -> tuple[list[dict[str, Any]], dict[str, float]]:
    q_slot = slot_dollars(fit, bankroll=INIT, kelly_fraction=0.25, sheet_cap=spec.sheet)
    h_slot = slot_dollars(fit, bankroll=INIT, kelly_fraction=0.50, sheet_cap=spec.sheet)
    host_slot = slot_dollars(fit, bankroll=DEPLOYABLE, kelly_fraction=0.25, sheet_cap=spec.sheet)
    q_risk = (0.25 * fit.f_star / float(fit.peak_concurrent)) if spec.has_stop else 0.0
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
            "slot": q_slot,
            "desc": (
                f"Quarter-Kelly equal slot: 0.25×f*×$500k / peak_conc_IS "
                f"(clamp ≤ sheet). Slot ${q_slot:,.0f}."
            ),
        },
        {
            "arm": "SIZE_hkelly_slot",
            "knob": "equal_slot",
            "kind": "equal",
            "slot": h_slot,
            "desc": (
                f"Half-Kelly equal slot: 0.50×f*×$500k / peak_conc_IS "
                f"(clamp ≤ sheet). Slot ${h_slot:,.0f}."
            ),
        },
        {
            "arm": "SIZE_host_qkelly",
            "knob": "host_bankroll",
            "kind": "equal",
            "slot": host_slot,
            "desc": (
                f"Quarter-Kelly using $600k deployable as bankroll / peak_conc_IS "
                f"(clamp ≤ sheet). Slot ${host_slot:,.0f}."
            ),
        },
    ]
    if spec.has_stop:
        arms.append(
            {
                "arm": "SIZE_risk_qkelly",
                "knob": "risk_fraction",
                "kind": "risk",
                "q": q_risk,
                "renorm": False,
                "desc": (
                    f"Risk $ = 0.25×f* × $500k / peak_conc_IS; shares from "
                    f"(entry−stop); clamp notional ≤ sheet. q={q_risk:.4f}."
                ),
            }
        )
        arms.append(
            {
                "arm": "SIZE_risk_qkelly_renorm",
                "knob": "risk_mix",
                "kind": "risk",
                "q": q_risk,
                "renorm": True,
                "desc": (
                    "Same risk-fraction as SIZE_risk_qkelly, then scale so mean "
                    "notional equals the sheet (pure mix, not a gross-size cut)."
                ),
            }
        )
    new_arms = [
        {
            "arm": "SIZE_risk1pct_stop",
            "knob": "risk1pct_path",
            "kind": "risk1pct",
            "path": True,
            "cap": "none",
            "desc": (
                "Paul rule, path-dependent realized equity, no cap: "
                "dollars = (equity_at_fill × 0.01) / stop%. Seed $500k. "
                "Same-day closes count before later opens. No mark-to-market."
            ),
        },
        {
            "arm": "SIZE_risk1pct_stop_seed",
            "knob": "risk1pct_seed",
            "kind": "risk1pct",
            "path": False,
            "cap": "none",
            "desc": (
                "Same 1%/stop formula with frozen $500k seed (not path). "
                "Paul’s $526,896 example is the same math on a different balance "
                "($526,896 × 0.01 / 0.06 = $87,816; $500k × 0.01 / 0.06 = $83,333)."
            ),
        },
        {
            "arm": "SIZE_risk1pct_stop_cap1x",
            "knob": "risk1pct_path_cap",
            "kind": "risk1pct",
            "path": True,
            "cap": "equity",
            "desc": (
                "Path-dependent 1%/stop with notional ≤ equity_at_fill "
                "(100% of that day’s account). Does not stop compounding: once "
                "equity is huge, 100% of huge is still huge."
            ),
        },
        {
            "arm": "SIZE_risk1pct_stop_cap600k",
            "knob": "risk1pct_path_hostcap",
            "kind": "risk1pct",
            "path": True,
            "cap": "host",
            "desc": (
                "Path-dependent 1%/stop with host sanity cap: notional ≤ $600k "
                "($500k × 2 × 0.6 deployable). Paul did not specify a cap; this "
                "is the labeled ceiling so tight stops cannot buy infinite stock."
            ),
        },
    ]
    slots = {
        "q_slot": q_slot,
        "h_slot": h_slot,
        "host_slot": host_slot,
        "q_risk": q_risk,
    }
    return arms + new_arms, slots


def kelly_notionals(arm: dict[str, Any], spec: Any, book: list[Any]) -> list[float]:
    if arm["arm"] == "CONTROL":
        return [spec.sheet] * len(book)
    if arm["kind"] == "equal":
        return [float(arm["slot"])] * len(book)
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
            out = [x * (spec.sheet / mean) for x in out]
    return out


def _note(arm: str, sl: str, ctrl: dict, cand: dict) -> str:
    if sl == "OOS":
        return "report-only"
    if sl != "FULL":
        return ""
    if arm == "CONTROL":
        return ""
    if cand.get("n_sized") == 0 and str(arm).startswith("SIZE_risk1pct"):
        return "N/A - no usable stop (do not invent 6%)"
    kelly_note = kab._note(arm, sl, ctrl, cand)
    if not str(arm).startswith("SIZE_risk1pct"):
        return kelly_note.replace("\u2192", "->")

    c_dd = ctrl.get("max_dd")
    a_dd = cand.get("max_dd")
    lev = float(cand.get("implied_lev") or 0)
    exploded = bool(cand.get("exploded"))
    c_ror = float(ctrl.get("ann_ror_acct") or 0)
    a_ror = float(cand.get("ann_ror_acct") or 0)
    c_pf = float(ctrl.get("pf") or 0)
    a_pf = float(cand.get("pf") or 0)
    peak_risk = float(cand.get("peak_conc_risk_pct") or 0)
    if exploded or lev >= 50:
        return (
            "DISMISS (path dollars exploded; 1% stacks and compounds; not usable)"
        )
    if c_dd is None or a_dd is None or math.isnan(float(c_dd)) or math.isnan(float(a_dd)):
        return "HOLD"
    dd_c = float(c_dd)
    dd_a = float(a_dd)
    if dd_a >= 20.0:
        return (
            "DISMISS (Max DD blew up; 1% stacks across open names; research-only)"
        )
    mean_c = float(ctrl.get("mean_notional") or 0)
    mean_a = float(cand.get("mean_notional") or 0)
    if peak_risk >= 80.0 and dd_a > dd_c:
        return (
            "DISMISS (host cap still stacks 1% across many names; worse DD; "
            "research-only)"
        )
    if dd_a >= dd_c + 2.5 and a_pf <= c_pf + 0.05:
        return "DISMISS (worse Max DD without a quality lift; research-only)"
    if mean_c > 0 and mean_a > 5.0 * mean_c and dd_a > dd_c:
        return "DISMISS (much larger $ and worse DD; scale != edge)"
    # Small mix wiggles on the same book are not KEEP.
    if abs(a_pf - c_pf) < 0.08 and abs(dd_a - dd_c) < 1.0:
        return "HOLD (WR/Avg% unchanged; mix/DD move is small; not an edge)"
    if a_pf >= c_pf - 0.02 and dd_a <= dd_c - 0.25 and a_ror >= c_ror * 0.85:
        return "LEAN KEEP (research; selection on same Closed book)"
    if a_ror > c_ror * 1.05 and dd_a >= dd_c - 0.10:
        return "HOLD (size-aware ROR moves with $; not a new entry edge)"
    if a_ror < c_ror * 0.6 and dd_a < dd_c:
        return "HOLD (smaller/safer $; shrink != edge)"
    if peak_risk >= 40:
        return "HOLD (1% stacks per open name; no quality lift vs Control)"
    return "HOLD"


def _empty_peak_fields() -> dict[str, Any]:
    return {
        "peak_deployed": 0.0,
        "peak_notional": 0.0,
        "peak_notional_date": None,
        "peak_notional_names": 0,
        "peak_conc_risk_d": 0.0,
        "peak_risk_date": None,
        "peak_risk_names": 0,
        "peak_conc_risk_pct": 0.0,
        "peak_risk_pct_of_cash": 0.0,
        "peak_cash_then": 0.0,
        "peak_conc_names": 0,
        "max_single_notional": 0.0,
        "max_path_equity": 0.0,
    }


def enrich_stats(
    st: dict[str, Any],
    book: list[Any],
    notion: list[float],
    *,
    n_skip: int,
    equity_at: Optional[Sequence[float]] = None,
    risks: Optional[Sequence[Optional[float]]] = None,
) -> dict[str, Any]:
    n = len(book)
    n_sized = sum(1 for x in notion if x > 0)
    ex = peak_exposure(
        book, notion, equity_at=equity_at, equity_ref=INIT, risks=risks
    )
    pnls_d = [(t.pnl_pct / 100.0) * float(nt) for t, nt in zip(book, notion)]
    exp_d = (sum(pnls_d) / n) if n else 0.0
    st["n_sized"] = n_sized
    st["n_no_stop"] = n_skip
    st["peak_deployed"] = float(ex["peak_notional"])
    st["peak_notional"] = float(ex["peak_notional"])
    st["peak_notional_date"] = ex["peak_notional_date"]
    st["peak_notional_names"] = ex["peak_notional_names"]
    st["peak_conc_risk_d"] = ex["peak_conc_risk_d"]
    st["peak_risk_date"] = ex["peak_risk_date"]
    st["peak_risk_names"] = ex["peak_risk_names"]
    st["peak_conc_risk_pct"] = ex["peak_conc_risk_pct"]
    st["peak_risk_pct_of_cash"] = ex["peak_risk_pct_of_cash"]
    st["peak_cash_then"] = ex["peak_cash_then"]
    st["peak_conc_names"] = ex["peak_conc_names"]
    st["max_single_notional"] = ex["max_single_notional"]
    st["max_path_equity"] = ex["max_path_equity"]
    st["implied_lev"] = (float(ex["peak_notional"]) / INIT) if INIT else 0.0
    st["expectancy_d"] = exp_d
    st["lose_streak"] = _losing_streak(book)
    st["exploded"] = False
    lev = float(st.get("implied_lev") or 0)
    ror = st.get("ann_ror_acct")
    if lev >= 50 or (ror is not None and abs(float(ror)) > 500):
        st["ann_ror"] = None
        st["ann_ror_acct"] = None
        st["ann_ror_host"] = None
        st["calmar"] = None
        st["exploded"] = True
    return st


def run_system(spec: Any) -> dict[str, Any]:
    trades = load_trades(spec.closed_path)
    atr_fracs = load_atr_fracs(spec.closed_path)
    if len(atr_fracs) != len(trades):
        raise RuntimeError(
            f"{spec.prefix}: ATR rows {len(atr_fracs)} != trades {len(trades)}"
        )
    is_loss = is_avg_abs_loss_frac(trades)
    risks, risk_src = overlay_risks(
        trades, atr_fracs, is_loss_fallback=is_loss
    )
    is_tr = slice_trades(trades, "IS")
    fit = fit_from_trades(is_tr)
    cov = {
        "FULL": stop_coverage(trades, risks),
        "IS": stop_coverage(
            is_tr,
            [risks[i] for i, t in enumerate(trades) if t.opened < IS_CUT],
        ),
        "OOS": stop_coverage(
            slice_trades(trades, "OOS"),
            [risks[i] for i, t in enumerate(trades) if t.opened >= IS_CUT],
        ),
    }
    exits = Counter((t.exit_type or "?").upper() for t in trades)
    arms, slots = kelly_arms_and_slots(spec, fit)

    # Path / seed 1% notionals on the FULL book, then slice (OOS inherits IS path).
    risk1_full: dict[str, tuple[list[float], list[float], int]] = {}
    for arm in arms:
        if arm["kind"] != "risk1pct":
            continue
        notion, eq_at, n_skip = size_risk1pct(
            trades,
            seed=INIT,
            path_dependent=bool(arm["path"]),
            cap_mode=str(arm["cap"]),
            risks=risks,
        )
        risk1_full[arm["arm"]] = (notion, eq_at, n_skip)

    tables: dict[str, list[dict[str, Any]]] = {}
    for sl in ("IS", "OOS", "FULL"):
        book = slice_trades(trades, sl)
        # Index map: FULL order → slice (load_trades order is file order; slice preserves it)
        if sl == "FULL":
            idx = list(range(len(trades)))
        elif sl == "IS":
            idx = [i for i, t in enumerate(trades) if t.opened < IS_CUT]
        else:
            idx = [i for i, t in enumerate(trades) if t.opened >= IS_CUT]
        risk_slice = [risks[i] for i in idx]
        rows: list[dict[str, Any]] = []
        ctrl_stats: Optional[dict[str, Any]] = None
        for arm in arms:
            eq_slice: list[float]
            if arm["kind"] == "risk1pct":
                full_n, full_eq, n_skip_full = risk1_full[arm["arm"]]
                notion = [full_n[i] for i in idx]
                eq_slice = [full_eq[i] for i in idx]
                n_skip = sum(1 for r in risk_slice if r is None or r < MIN_RISK_PCT)
                _ = n_skip_full
            else:
                notion = kelly_notionals(arm, spec, book)
                eq_slice = [float(INIT)] * len(book)
                n_skip = sum(1 for r in risk_slice if r is None or r < MIN_RISK_PCT)
            if arm["kind"] == "risk1pct" and sum(1 for x in notion if x > 0) == 0:
                st = {
                    "n": len(book),
                    "wins": 0,
                    "losses": 0,
                    "win_pct": None,
                    "avg_pnl_pct": None,
                    "avg_wo_max": None,
                    "avg_win_pct": None,
                    "avg_loss_pct": None,
                    "expectancy_pct": None,
                    "pf": None,
                    "ann_ror": None,
                    "ann_ror_acct": None,
                    "ann_ror_host": None,
                    "max_dd": None,
                    "calmar": None,
                    "sharpe": None,
                    "avg_days": None,
                    "median_days": None,
                    "p90_days": None,
                    "capital_days": None,
                    "profit_per_cap_day": None,
                    "mean_notional": 0.0,
                    "mean_shares": 0.0,
                    "implied_lev": 0.0,
                    "exits": dict(exits),
                    "total_pnl": 0.0,
                    "n_sized": 0,
                    "n_no_stop": n_skip,
                    "expectancy_d": None,
                    "lose_streak": _losing_streak(book),
                    **_empty_peak_fields(),
                }
            else:
                cash = (
                    spec.sheet
                    if arm["arm"] == "CONTROL"
                    else (sum(notion) / len(notion) if notion else spec.sheet)
                )
                if cash <= 0:
                    cash = spec.sheet
                st = book_stats(book, notion, cash_for_ann=cash)
                enrich_stats(
                    st,
                    book,
                    notion,
                    n_skip=n_skip,
                    equity_at=eq_slice,
                    risks=risk_slice,
                )
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
        "cov": cov,
        "exits": dict(exits),
        "arms": arms,
        "tables": tables,
        "risk_src": risk_src,
        "is_avg_abs_loss": is_loss,
        "atr": atr_stats(atr_fracs),
        **slots,
    }


def _sys_specs() -> list[Any]:
    out = []
    for prefix, sheet, has_stop in (
        ("VZ", 45_000.0, True),
        ("BRT", 47_500.0, True),
        ("RSI", 10_000.0, False),
    ):
        path, pin = resolve_closed(prefix)
        out.append(SysSpec(prefix, sheet, has_stop, path, pin))
    return out


def _exit_table(exits: dict[str, int]) -> str:
    n = sum(exits.values()) or 1
    headers = [("EXIT_TYPE", "text"), ("N", "num"), ("% of book", "num")]
    th = "".join(sortable_th(h, t) for h, t in headers)
    body = []
    for k, v in sorted(exits.items(), key=lambda kv: (-kv[1], kv[0])):
        body.append(
            f"<tr><td>{html_mod.escape(k)}</td><td>{v:,}</td>"
            f"<td>{100.0 * v / n:.2f}%</td></tr>"
        )
    return (
        '<p class="meta">Exit mix is frozen (same for every size arm). '
        "Click column headers to sort.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _cov_html(cov: dict[str, Any]) -> str:
    headers = [
        ("Slice", "text"),
        ("N", "num"),
        ("Price stop usable", "num"),
        ("Price stop missing", "num"),
        (f"Price stop &lt; {100*MIN_RISK_PCT:.1f}%", "num"),
        ("Sized (price or proxy)", "num"),
        ("Price stop % p50", "num"),
        ("Price stop % mean", "num"),
        ("Price stop % min / max", "text"),
        ("Proxy/size % p50", "num"),
        ("Proxy/size % mean", "num"),
    ]
    th = "".join(sortable_th(h, t) for h, t in headers)
    body = []
    for sl in ("IS", "OOS", "FULL"):
        c = cov[sl]
        mn = c.get("risk_min")
        mx = c.get("risk_max")
        mm = (
            f"{100*mn:.2f}% / {100*mx:.2f}%"
            if mn is not None and mx is not None
            else "—"
        )
        body.append(
            "<tr>"
            + "".join(
                [
                    f"<td>{sl}</td>",
                    f"<td>{c['n']:,}</td>",
                    f"<td>{c['usable']:,}</td>",
                    f"<td>{c['missing']:,}</td>",
                    f"<td>{c['tiny']:,}</td>",
                    f"<td>{c.get('overlay_usable', 0):,}</td>",
                    f"<td>{_fmt_pct(100*c['risk_p50'] if c.get('risk_p50') is not None else None)}</td>",
                    f"<td>{_fmt_pct(100*c['risk_mean'] if c.get('risk_mean') is not None else None)}</td>",
                    f"<td>{mm}</td>",
                    f"<td>{_fmt_pct(100*c['overlay_p50'] if c.get('overlay_p50') is not None else None)}</td>",
                    f"<td>{_fmt_pct(100*c['overlay_mean'] if c.get('overlay_mean') is not None else None)}</td>",
                ]
            )
            + "</tr>"
        )
    return (
        '<p class="meta">Price stop = Closed <code>STOP_PRICE</code> &gt; 0 and '
        f"(entry−stop)/entry ≥ {100*MIN_RISK_PCT:.1f}% (Kelly risk floor). "
        "Fills with no price stop are <strong>not dropped</strong> — they use "
        f"labeled <code>{RSI_STOP_PROXY}</code> = "
        f"<code>{RSI_STOP_PROXY_COL}</code> / 100 (Average True Range % at the "
        "trigger bar). Same entries as Control; only dollars change. "
        "Do not invent a silent 6%. Click column headers to sort.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _table_html(rows: list[dict[str, Any]], sl: str) -> str:
    headers = [
        ("Arm", "text"),
        ("Knob", "text"),
        ("N", "num"),
        ("N sized", "num"),
        ("No stop", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Expectancy %", "num"),
        ("Expectancy $", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("PF", "num"),
        ("Ann ROR (slot) %", "num"),
        ("Ann ROR $500k %", "num"),
        ("Ann ROR $600k %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Losing streak", "num"),
        ("Avg days", "num"),
        ("Median days", "num"),
        ("P90 days", "num"),
        ("Capital days", "num"),
        ("Profit / cap day", "num"),
        ("Mean notional", "num"),
        ("Mean shares", "num"),
        ("Peak notional $", "num"),
        ("Implied lev", "num"),
        ("Peak risk $", "num"),
        ("Peak risk % of cash then", "num"),
        ("Peak risk % of $500k seed", "num"),
        ("Cash then (path / seed)", "num"),
        ("Peak conc. names", "num"),
        ("Max 1-name notional $", "num"),
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
                    f"<td>{st.get('n_sized', st['n']):,}</td>",
                    f"<td>{st.get('n_no_stop', 0):,}</td>",
                    f"<td>{_fmt_pct(st.get('win_pct'))}</td>",
                    f"<td>{_fmt_pct(st.get('avg_pnl_pct'))}</td>",
                    f"<td>{_fmt_pct(st.get('avg_wo_max'))}</td>",
                    f"<td>{_fmt_pct(st.get('expectancy_pct'))}</td>",
                    f"<td>{format_money(st.get('expectancy_d'))}</td>",
                    f"<td>{_fmt_pct(st.get('avg_win_pct'))}</td>",
                    f"<td>{_fmt_pct(st.get('avg_loss_pct'))}</td>",
                    f"<td>{_fmt_num(st.get('pf'))}</td>",
                    f"<td>{_fmt_pct(st.get('ann_ror'))}</td>",
                    f"<td>{_fmt_pct(st.get('ann_ror_acct'))}</td>",
                    f"<td>{_fmt_pct(st.get('ann_ror_host'))}</td>",
                    f"<td>{_fmt_pct(st.get('max_dd'))}</td>",
                    f"<td>{_fmt_num(st.get('calmar'))}</td>",
                    f"<td>{_fmt_num(st.get('sharpe'))}</td>",
                    f"<td>{st.get('lose_streak') if st.get('lose_streak') is not None else '—'}</td>",
                    f"<td>{_fmt_num(st.get('avg_days'), 1)}</td>",
                    f"<td>{_fmt_num(st.get('median_days'), 1)}</td>",
                    f"<td>{_fmt_num(st.get('p90_days'), 1)}</td>",
                    f"<td>{_fmt_num(st.get('capital_days'), 0)}</td>",
                    f"<td>{format_money(st.get('profit_per_cap_day'))}</td>",
                    f"<td>{format_money(st.get('mean_notional'))}</td>",
                    f"<td>{_fmt_num(st.get('mean_shares'), 1)}</td>",
                    f"<td>{format_money(st.get('peak_notional', st.get('peak_deployed')))}</td>",
                    f"<td>{_fmt_num(st.get('implied_lev'))}</td>",
                    f"<td>{format_money(st.get('peak_conc_risk_d'))}</td>",
                    f"<td>{_fmt_pct(st.get('peak_risk_pct_of_cash'))}</td>",
                    f"<td>{_fmt_pct(st.get('peak_conc_risk_pct'))}</td>",
                    f"<td>{format_money(st.get('peak_cash_then'))}</td>",
                    f"<td>{st.get('peak_conc_names') if st.get('peak_conc_names') is not None else '—'}</td>",
                    f"<td>{format_money(st.get('max_single_notional'))}</td>",
                    f"<td>{_fmt_pct(st.get('d_avg'))}</td>",
                    f"<td>{_fmt_pct(st.get('d_dd'))}</td>",
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
        f"host-deployable cash and the arm’s actual dollars. Overlay Max DD / "
        f"Sharpe seed $500k, exit-date equity. <strong>Peak notional $</strong> "
        f"(old label: peak deployed) = max concurrent sum of position dollars — "
        f"not a sum of all history. <strong>Peak risk $</strong> = concurrent "
        f"sum of (position $ × stop%). <strong>Peak risk % of cash then</strong> "
        f"divides that risk by the largest equity-at-fill among names open on "
        f"the peak-risk day (path arms = snowballed cash; seed arm = $500k). "
        f"<strong>Peak risk % of $500k seed</strong> always uses the frozen "
        f"house pile so path-arm fantasy stays visible. Per-trade 1% stacks: "
        f"expect ~1% × overlapping names, not 1% for the whole book. "
        f"<strong>N sized / No stop</strong> = fills with / without a usable "
        f"price stop or labeled <code>{RSI_STOP_PROXY}</code>. Missing "
        f"<code>STOP_PRICE</code> no longer drops the fill.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _peak_breakdown_html(rows: list[dict[str, Any]]) -> str:
    headers = [
        ("Arm", "text"),
        ("Peak notional $", "num"),
        ("Peak notional date", "date"),
        ("Names at peak ntl", "num"),
        ("Peak risk $", "num"),
        ("Peak risk date", "date"),
        ("Names at peak risk", "num"),
        ("Peak risk % of cash then", "num"),
        ("Peak risk % of $500k", "num"),
        ("Cash then", "num"),
        ("Max 1-name $", "num"),
        ("Max path equity", "num"),
        ("Note", "text"),
    ]
    th = "".join(sortable_th(h, t) for h, t in headers)
    body = []
    for st in rows:
        if st["arm"] == "CONTROL" or str(st["arm"]).startswith("SIZE_risk1pct"):
            body.append(
                "<tr>"
                + "".join(
                    [
                        f"<td>{html_mod.escape(str(st['arm']))}</td>",
                        f"<td>{format_money(st.get('peak_notional', st.get('peak_deployed')))}</td>",
                        f"<td>{html_mod.escape(str(st.get('peak_notional_date') or '—'))}</td>",
                        f"<td>{st.get('peak_notional_names') if st.get('peak_notional_names') is not None else '—'}</td>",
                        f"<td>{format_money(st.get('peak_conc_risk_d'))}</td>",
                        f"<td>{html_mod.escape(str(st.get('peak_risk_date') or '—'))}</td>",
                        f"<td>{st.get('peak_risk_names') if st.get('peak_risk_names') is not None else '—'}</td>",
                        f"<td>{_fmt_pct(st.get('peak_risk_pct_of_cash'))}</td>",
                        f"<td>{_fmt_pct(st.get('peak_conc_risk_pct'))}</td>",
                        f"<td>{format_money(st.get('peak_cash_then'))}</td>",
                        f"<td>{format_money(st.get('max_single_notional'))}</td>",
                        f"<td>{format_money(st.get('max_path_equity'))}</td>",
                        f"<td>{html_mod.escape(st.get('note') or '')}</td>",
                    ]
                )
                + "</tr>"
            )
    return (
        "<h3>Peak notional vs peak risk (FULL)</h3>"
        '<p class="meta">Click column headers to sort. Peak notional $ is what '
        "we used to label peak deployed. Peak risk $ is the concurrent stop "
        "loss in dollars. Peak risk % of cash then ≈ 1% × names open that day "
        "when the 1% rule is applied without a cap. Path arms can still show "
        "huge $ because cash-then itself compounded.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def write_baseline(results: list[dict[str, Any]]) -> None:
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "**Status:** Research size overlay. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "**Delta from prior:** `kelly_size_ab_20260915` — same Closed pins, same "
        "Kelly arms (not retuned). This stamp adds 1% risk-to-stop sizing only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        f"> {FOLLOWUP_REQUEST}",
        "",
        f"> {RSI_FOLLOWUP_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        FOLLOWUP_PLAIN,
        "",
        RSI_FOLLOWUP_PLAIN,
        "",
        "## Honesty",
        "",
        "- Same Closed trades as the Kelly stamp (VZ 260914184242, BRT LatestRun, "
        "RSI 260914223813). Entries and exits frozen. Does not follow live "
        "house_last_run_ts.",
        "- RSI house pin / 149-name universe only. Not RSIN_PaulScore5_IS.",
        "- Kelly inputs still IS-only; Kelly arms not retuned.",
        "- OOS is report-only. Do not KEEP from OOS. Do not retune on OOS.",
        "- Win % / Avg PnL % are unweighted by size — they match Control when "
        "the same trades stay in the book. Judge 1% risk on size-aware Ann ROR, "
        "Max DD, $ PF, peak notional, and peak risk $.",
        "- Equal-slot Kelly shrink is still HOLD (shrink ≠ edge).",
        "- Picking among overlays on this same history is in-sample selection.",
        "- Main **Ann ROR %** is slot-normalized (cash = mean $). Use "
        "**Ann ROR $500k** / **Ann ROR $600k**, mean $, Max DD.",
        "- Path equity = $500k seed + realized $ of trades already closed on or "
        "before the fill’s open date. No daily mark-to-market. Same-day opens "
        "share morning equity. OOS path sizes inherit the IS equity path "
        "(not reset).",
        "- Stop % from Closed `STOP_PRICE` when present. Floor: stop% < 0.20% is "
        "treated as no usable *price* stop (same floor as "
        "`kelly_sizing.risk_notional`). Do not invent a silent 6%.",
        "- RSI house pin / 149-name book: engine writes `STOP_PRICE=0` on every "
        "Closed row; exits are TIME / OVERBOUGHT. Prior stamp showed N/A / zero "
        "1% entries — that was a skip bug (missing stop treated as no trade). "
        "Paul is correct: **same entries, different size.** All 428 fills stay.",
        f"- RSI 1% size uses labeled `{RSI_STOP_PROXY}` = Closed "
        f"`{RSI_STOP_PROXY_COL}` / 100 (Average True Range % at the trigger "
        "bar; entry gate is ATR% ≥ 5). Not a live price stop. If ATR were "
        "missing, fallback would be IS-only mean |loss| of losing RSI trades "
        "(not used on this pin — ATR is present on all 428). "
        + sensitivity_note(),
        "- Paul did not specify a cap. No-cap path arms can size huge on tight "
        "stops and then compound. `SIZE_risk1pct_stop_cap1x` caps notional at "
        "100% of path equity (still explodes once the account is huge). "
        "`SIZE_risk1pct_stop_cap600k` caps each fill at the $600k host ceiling.",
        "- 1% is **per trade**. Concurrent names stack. Peak risk % of cash then "
        "should be about 1% × names open that day. Peak risk % of the $500k seed "
        "is also reported so path-arm fantasy is not hidden.",
        "- **Peak notional $** (old label: peak deployed) is a concurrent sweep: "
        "on each open date add that fill's dollars, on each close date subtract "
        "them, keep the max. It is **not** a sum of all history and **not** "
        "dollar risk. Control VZ = 49 × $45,000 = $2,205,000 (sanity check).",
        "- The ~$11.9 billion VZ path-arm peak is real for `SIZE_risk1pct_stop` "
        "(DISMISS / compounded). It is **not** the frozen-seed arm. There is no "
        "$2.4B row: closest are $11.89B path notional and one seed-arm tight-stop "
        "fill at $2.44 million (SHOP, 0.205% stop). Do not treat path $ as the "
        "house $500k rule.",
        "- If Paul meant **1% total book** across all open names, that is a "
        "different arm. Do not silently switch.",
        "- DailyRun still uses fixed sheet notionals (VZ $45k, BRT $47.5k, RSI $10k).",
        "",
        "## Peak notional vs peak risk (this follow-up)",
        "",
        "- Formula: concurrent sweep. Open date → +position $; close date → "
        "−position $. Keep the max. Same-day opens before closes. **Not** a "
        "sum of all history. Control VZ = 49 × $45,000 = $2,205,000.",
        "- Peak risk $ = same sweep of (position $ × stop%). Different from "
        "notional: 1% of cash / 3% stop ≈ 33% of cash in that name.",
        "- VZ `SIZE_risk1pct_stop` (path, no cap, DISMISS): peak notional "
        "$11.89 billion on 2026-06-23 with 18 names; path cash then ≈ $6.2B; "
        "peak risk $1.09B ≈ 17.5% of that cash (≈ 1% × 18). Fantasy "
        "compounding — do not treat as the frozen-seed arm.",
        "- VZ `SIZE_risk1pct_stop_seed` (frozen $500k): peak notional $4.46M "
        "(tight-stop stack); peak risk $245,000 = 49.00% of $500k = 1% × 49 "
        "overlapping names. Per-trade 1% is working; book risk stacks.",
        "- No $2.4B row. Closest: $11.89B path notional, or $2.44M one-name "
        "SHOP seed fill (0.205% stop).",
        "- 1% total book across all open names is a different arm. Not run.",
        "",
        "## Frozen control (per system)",
        "",
        "- Overlay seed: $500,000 (Paul’s $526,896 is an example current balance, "
        "not a second freeze)",
        "- IS cut: entry_date < 2024-01-01",
        "- Host deployable (SIZE_host_qkelly / host cap context): $600,000",
        "- Risk fraction: 1.00% of equity_at_fill",
        f"- Min usable stop: {100*MIN_RISK_PCT:.2f}%",
        f"- `{RSI_STOP_PROXY}` (RSI / no-price-stop fills): "
        f"`{RSI_STOP_PROXY_COL}` / 100. Not a silent 6%.",
        "",
    ]
    for r in results:
        spec = r["spec"]
        fit: KellyFit = r["fit"]
        cfull = r["cov"]["FULL"]
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
            f"- Stops FULL: price_usable={cfull['usable']} "
            f"price_missing={cfull['missing']} "
            f"tiny(&lt;{100*MIN_RISK_PCT:.1f}%)={cfull['tiny']} "
            f"sized_price_or_proxy={cfull.get('overlay_usable', 0)} of N={cfull['n']}",
        ]
        src = r.get("risk_src") or {}
        atr = r.get("atr") or {}
        if src:
            lines.append(
                f"- Size-risk source FULL: price_stop={src.get('price', 0)} "
                f"{RSI_STOP_PROXY}_ATR={src.get('atr', 0)} "
                f"IS_avg_|loss|={src.get('is_loss', 0)} still_missing={src.get('miss', 0)}"
            )
        if atr.get("n_ok"):
            mean_atr = atr.get("mean")
            p50_atr = atr.get("p50")
            lines.append(
                f"- ATR_PCT_AT_TRIGGER: n={atr.get('n_ok')} "
                f"p50={100 * p50_atr:.2f}% mean={100 * mean_atr:.2f}% "
                f"min={100 * atr['min']:.2f}% max={100 * atr['max']:.2f}%"
                if mean_atr is not None and p50_atr is not None and atr.get("min") is not None
                else f"- ATR_PCT_AT_TRIGGER: n={atr.get('n_ok')}"
            )
        if r.get("is_avg_abs_loss") is not None:
            lines.append(
                f"- IS avg |loss| of losers (sensitivity only, not used for size "
                f"on this pin): {100 * float(r['is_avg_abs_loss']):.2f}%"
            )
        if spec.has_stop:
            lines.append(f"- Risk q (0.25×f*): {r['q_risk']:.4f}")
        if fit.note:
            lines.append(f"- Fit note: {fit.note}")
        lines.append("")
        full = {row["arm"]: row for row in r["tables"]["FULL"]}
        for arm in r["arms"]:
            st = full[arm["arm"]]
            lines.append(
                f"- **{arm['arm']} FULL** N={st['n']} sized={st.get('n_sized', st['n'])} "
                f"nostop={st.get('n_no_stop', 0)} "
                f"WR={_fmt_pct(st.get('win_pct'))} "
                f"Avg%={_fmt_pct(st.get('avg_pnl_pct'))} "
                f"MaxDD={_fmt_pct(st.get('max_dd'))} "
                f"AnnROR(slot)={_fmt_pct(st.get('ann_ror'))} "
                f"AnnROR$500k={_fmt_pct(st.get('ann_ror_acct'))} "
                f"AnnROR$600k={_fmt_pct(st.get('ann_ror_host'))} "
                f"Calmar={_fmt_num(st.get('calmar'))} "
                f"mean$={_fmt_num(st.get('mean_notional'), 0)} "
                f"shares={_fmt_num(st.get('mean_shares'), 1)} "
                f"lev={_fmt_num(st.get('implied_lev'))} "
                f"peakNtl={_fmt_num(st.get('peak_notional', st.get('peak_deployed')), 0)} "
                f"peakRisk$={_fmt_num(st.get('peak_conc_risk_d'), 0)} "
                f"peakRisk%cash={_fmt_pct(st.get('peak_risk_pct_of_cash'))} "
                f"peakRisk%seed={_fmt_pct(st.get('peak_conc_risk_pct'))} "
                f"cashThen={_fmt_num(st.get('peak_cash_then'), 0)} "
                f"max1name={_fmt_num(st.get('max_single_notional'), 0)} "
                f"note={st['note']}"
            )
        lines.append("")
    lines += [
        "## Arms",
        "",
        "- `CONTROL` — sheet notional",
        "- `SIZE_qkelly_slot` — quarter-Kelly equal slot, clamp to sheet (prior freeze)",
        "- `SIZE_hkelly_slot` — half-Kelly equal slot, clamp to sheet (prior freeze)",
        "- `SIZE_host_qkelly` — quarter-Kelly with $600k deployable bankroll (prior freeze)",
        "- `SIZE_risk_qkelly` — VZ/BRT only; Kelly risk-fraction, clamp to sheet (prior freeze)",
        "- `SIZE_risk_qkelly_renorm` — VZ/BRT only; risk mix, mean $ = sheet (prior freeze)",
        "- `SIZE_risk1pct_stop` — **new** path-dependent 1% of realized equity / stop%, no cap",
        "- `SIZE_risk1pct_stop_seed` — **new** frozen $500k × 1% / stop%, no cap",
        "- `SIZE_risk1pct_stop_cap1x` — **new** path-dependent 1%/stop, notional ≤ path equity",
        "- `SIZE_risk1pct_stop_cap600k` — **new** path-dependent 1%/stop, notional ≤ $600k host cap",
        "",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(results: list[dict[str, Any]]) -> Path:
    chunks = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>",
        f"<title>{STAMP}</title><style>",
        SORTABLE_TH_CSS,
        "body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }",
        "h1 { font-size: 1.4rem; margin: 0 0 .35rem; }",
        "h2 { font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }",
        ".meta { color: #475569; font-size: .92rem; max-width: 92rem; }",
        ".insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 92rem; }",
        ".ask { background: #eff6ff; border: 1px solid #bfdbfe; }",
        "table.sortable { border-collapse: collapse; background: #fff; font-size: .78rem; margin: .5rem 0 1rem; }",
        "table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }",
        "table.sortable th { background: #f1f5f9; }",
        ".badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }",
        ".caveat { color: #9a3412; font-size: .9rem; max-width: 92rem; }",
        ".ror { background: #fff7ed; border: 1px solid #fdba74; }",
        "blockquote.meta { margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }",
        "</style></head><body>",
        "<h1>1% risk-to-stop size vs Kelly vs Control — VZ / BRT / RSI overlay</h1>",
        '<p class="badge">Research only · not gold · not DailyRun · OOS report-only · SIZE / overlay</p>',
        f'<p class="meta">Stamp <code>{STAMP}</code> · delta from '
        f"<code>kelly_size_ab_20260915</code> · 2026-09-15 · click column headers to sort</p>",
        '<div class="insight ask"><h2 style="margin-top:0;border:0">What you asked</h2>',
        f'<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>',
        f'<blockquote class="meta">{html_mod.escape(FOLLOWUP_REQUEST)}</blockquote>',
        f'<blockquote class="meta">{html_mod.escape(RSI_FOLLOWUP_REQUEST)}</blockquote>',
        "<h2>In plain English</h2>",
        f"<p>{html_mod.escape(PLAIN_ENGLISH)}</p>",
        f"<p>{html_mod.escape(FOLLOWUP_PLAIN)}</p>",
        f"<p>{html_mod.escape(RSI_FOLLOWUP_PLAIN)}</p></div>",
        '<div class="insight ror"><h2 style="margin-top:0;border:0">'
        "How we calculated peak deployed (notional vs risk)</h2>",
        "<p><strong>Formula (not a bug):</strong> Peak notional $ (old label: "
        "peak deployed) is a <em>concurrent</em> sweep, not a sum of every "
        "trade in history. On each fill date we add that position's dollars; "
        "on each exit date we subtract them; we keep the maximum of the running "
        "total. Same-day opens count before same-day closes. Control Volume "
        "Zone (VZ) is the sanity check: 49 names open × $45,000 sheet = "
        "$2,205,000.00 exactly.</p>"
        "<p><strong>There is no $2.4 billion row.</strong> The insane number is "
        "<strong>$11.89 billion</strong> peak notional on VZ "
        "<code>SIZE_risk1pct_stop</code> (path-dependent 1%, no cap). That arm "
        "is already <strong>DISMISS</strong> — compounded fantasy. Do not treat "
        "it as the frozen-seed house rule. Closest other figures: one seed-arm "
        "tight-stop fill (SHOP, 0.205% stop) is $2.44 million in a single name; "
        "VZ <code>SIZE_risk1pct_stop_cap600k</code> peaks at $24.05 million "
        "notional (49 names, each capped at $600k).</p>"
        "<p><strong>Why the path arm is huge (all three drivers, not one):</strong> "
        "by 2026-06-23 path equity had snowballed to about $6.2 billion "
        "(realized closes only, no mark-to-market). Eighteen names were open. "
        "Each was sized <code>dollars = equity_at_fill × 1% / stop%</code>, so "
        "a 2.94% stop on $6.2B is $2.11 billion of GGAL alone. Peak "
        "<em>risk</em> that day is $1.09 billion ≈ 17.5% of that $6.2B cash "
        "(about 1% × 18 names). Peak <em>notional</em> is $11.89 billion "
        "because notional = risk / stop% — a 3% stop needs ~33× the risk "
        "dollars in stock. Tightest path fill: UUUU at 0.461% stop on $3.30B "
        "equity = $7.15 billion in one name (1% stop would have been 100% of "
        "equity).</p>"
        "<p><strong>Frozen $500k seed arm is the honest 1% rule:</strong> VZ "
        "<code>SIZE_risk1pct_stop_seed</code> peaks at $4.46 million notional "
        "(2011-11-02, 22 names, driven by tight stops — WBS 0.36% → $1.38M in "
        "one name). Peak <em>risk</em> is $245,000.00 = 49.00% of $500k on "
        "2020-04-22 when 49 names were open (exactly 1% × 49). So the rule "
        "worked per trade; overlapping trades stack the book risk.</p>"
        "<p>If you meant <strong>1% total book</strong> across all open names "
        "(not 1% per trade), that is a different arm — we did not silently "
        "switch.</p></div>",
        '<div class="insight ror"><h2 style="margin-top:0;border:0">'
        "How to read Ann ROR and this 1% rule</h2>",
        "<p>Ann ROR in the slot column is a percent-on-the-slot number, not yearly "
        "return on the $500k house. Equal-slot Kelly arms will still tie there. "
        "Use <strong>Ann ROR $500k / $600k</strong>, mean $, peak notional $, Max DD, "
        "and peak risk $. The new rule is "
        "<code>dollars = (equity × 1%) / stop%</code> — Paul’s $526,896 / 6% example "
        "is $87,816. We seed $500k (house). Path-dependent equity is realized closes "
        "only (no daily mark-to-market). 1% is per trade and stacks when many names "
        "are open. RSI has no live price stop — we size the same 428 fills with "
        f"labeled <code>{RSI_STOP_PROXY}</code> = <code>{RSI_STOP_PROXY_COL}</code> "
        "/ 100, not a silent 6%.</p></div>",
        '<div class="insight ask"><h2 style="margin-top:0;border:0">'
        "RSI “no entries” was a skip bug</h2>",
        "<p>Paul is right: the 1% rule only changes dollars, not which fills exist. "
        "The house Relative Strength Index (RSI) Closed pin writes "
        "<code>STOP_PRICE=0</code> on all 428 rows (exits TIME / OVERBOUGHT). "
        "The first stamp treated a missing stop as skip, so 1% arms showed N/A "
        "and N sized = 0. Control and Kelly already had all 428. We now keep "
        f"every fill and size with <code>{RSI_STOP_PROXY}</code> = Closed "
        f"<code>{RSI_STOP_PROXY_COL}</code> (Average True Range percent at the "
        "trigger bar) ÷ 100. That is an engine column, not a live stop. "
        "If ATR were missing we would use the in-sample mean |loss| of losing "
        "RSI trades — not needed here (ATR is on all 428). "
        f"{html_mod.escape(sensitivity_note())}</p></div>",
        '<div class="insight"><p class="caveat"><strong>Selection honesty:</strong> '
        "Kelly fractions were fit on the same IS Closed book. Choosing among these "
        "overlays after seeing the table is in-sample selection. Equal-slot shrink "
        "is HOLD, not a new edge. KEEP/DISMISS on the 1% arms uses size-aware ROR "
        "and drawdown, not trade count. DailyRun is unchanged.</p></div>",
    ]
    for r in results:
        spec = r["spec"]
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
        chunks.append("<h3>Stop coverage</h3>")
        chunks.append(_cov_html(r["cov"]))
        src = r.get("risk_src") or {}
        atr = r.get("atr") or {}
        if src.get("atr") or src.get("is_loss") or not spec.has_stop:
            mean_atr = atr.get("mean")
            p50_atr = atr.get("p50")
            atr_txt = (
                f"ATR p50 {100 * p50_atr:.2f}%, mean {100 * mean_atr:.2f}% "
                f"(min {100 * atr['min']:.2f}% / max {100 * atr['max']:.2f}%)"
                if mean_atr is not None and p50_atr is not None and atr.get("min") is not None
                else "ATR present on Closed"
            )
            is_loss = r.get("is_avg_abs_loss")
            is_txt = (
                f"IS avg |loss| of losers {100 * float(is_loss):.2f}% (note only; not used for size)."
                if is_loss is not None
                else ""
            )
            chunks.append(
                '<div class="insight"><p class="meta">'
                f"<strong>{html_mod.escape(spec.prefix)} size-risk:</strong> "
                f"price-stop fills {src.get('price', 0):,}; "
                f"<code>{RSI_STOP_PROXY}</code> from "
                f"<code>{RSI_STOP_PROXY_COL}</code> {src.get('atr', 0):,}; "
                f"IS |loss| fallback {src.get('is_loss', 0):,}; "
                f"still missing {src.get('miss', 0):,}. {html_mod.escape(atr_txt)} "
                f"{html_mod.escape(is_txt)} Same N as Control.</p></div>"
            )
        chunks.append("<h3>Exit mix (frozen)</h3>")
        chunks.append(_exit_table(r["exits"]))
        chunks.append("<ul class='meta'>")
        for arm in r["arms"]:
            chunks.append(
                f"<li><code>{html_mod.escape(arm['arm'])}</code> — "
                f"{html_mod.escape(arm['desc'])}</li>"
            )
        chunks.append("</ul>")
        full_map = {row["arm"]: row for row in r["tables"]["FULL"]}
        chunks.append('<div class="insight ror"><p class="caveat"><strong>FULL verdicts (research-only; not from OOS):</strong></p><ul class="meta">')
        for arm in r["arms"]:
            if arm["arm"] == "CONTROL" or arm["arm"].startswith("SIZE_risk1pct") or arm["arm"] == "SIZE_qkelly_slot":
                st = full_map[arm["arm"]]
                chunks.append(
                    f"<li><code>{html_mod.escape(arm['arm'])}</code> — "
                    f"{html_mod.escape((st.get('note') or 'Control (sheet slot)') )}</li>"
                )
        chunks.append("</ul></div>")
        chunks.append(_peak_breakdown_html(r["tables"]["FULL"]))
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
        spec = r["spec"]
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
                "coverage": r["cov"],
                "risk_src": r.get("risk_src"),
                "atr": r.get("atr"),
                "is_avg_abs_loss": r.get("is_avg_abs_loss"),
                "exits": r["exits"],
                "q_slot": r["q_slot"],
                "h_slot": r["h_slot"],
                "host_slot": r["host_slot"],
                "q_risk": r["q_risk"],
                "full": r["tables"]["FULL"],
                "is": r["tables"]["IS"],
                "oos": r["tables"]["OOS"],
            }
        )
    (OUT_DIR / "summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(f"[risk1pct AB] wrote {html_path}")
    for r in results:
        spec = r["spec"]
        c = r["cov"]["FULL"]
        print(
            f"  {spec.prefix}: N={r['n_all']} price_stop={c['usable']} "
            f"sized={c.get('overlay_usable', 0)} no_price_stop={c['no_stop']} "
            f"src={r.get('risk_src')} pin={spec.pin}"
        )
        full = {row["arm"]: row for row in r["tables"]["FULL"]}
        for name in (
            "CONTROL",
            "SIZE_qkelly_slot",
            "SIZE_risk1pct_stop",
            "SIZE_risk1pct_stop_seed",
            "SIZE_risk1pct_stop_cap1x",
            "SIZE_risk1pct_stop_cap600k",
        ):
            st = full.get(name)
            if not st:
                continue
            note = str(st.get("note") or "").replace("\u2192", "->").replace("\u2014", "-")
            print(
                f"    {name}: mean$={st.get('mean_notional')} "
                f"AnnROR500k={st.get('ann_ror_acct')} DD={st.get('max_dd')} "
                f"peakNtl={st.get('peak_notional', st.get('peak_deployed'))} "
                f"peakRisk$={st.get('peak_conc_risk_d')} "
                f"peakRisk%cash={st.get('peak_risk_pct_of_cash')} "
                f"peakRisk%seed={st.get('peak_conc_risk_pct')} note={note}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
