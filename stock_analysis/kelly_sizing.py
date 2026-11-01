"""Kelly fraction helpers for Closed-overlay size A/Bs.

Fit ``p`` / ``b`` on in-sample trades only. Full Kelly is ``p - (1-p)/b``.
House experiments use a fraction (quarter / half) and divide by peak
concurrent names so overlapping fills do not each take the isolated-bet stake.

This module does not change DailyRun defaults. Callers clamp to the current
sheet notional when the first pass is shrink-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class KellyFit:
    n: int
    n_wins: int
    n_losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    payoff_b: float
    f_star: float
    peak_concurrent: int
    note: str


def kelly_f_star(win_rate: float, payoff_b: float) -> float:
    """Isolated-bet Kelly fraction of bankroll. Floor at 0 (no bet if no edge)."""
    p = float(win_rate)
    b = float(payoff_b)
    if b <= 0 or p <= 0:
        return 0.0
    return max(0.0, p - (1.0 - p) / b)


def peak_concurrent(spans: Iterable[tuple[date, date]]) -> int:
    """Max names open at once. Same-day open+close counts as 1 (opens first)."""
    events: list[tuple[date, int]] = []
    for opened, closed in spans:
        if opened is None or closed is None:
            continue
        if closed < opened:
            closed = opened
        events.append((opened, 1))
        events.append((closed, -1))
    if not events:
        return 0
    events.sort(key=lambda x: (x[0], -x[1]))
    cur = 0
    peak = 0
    for _d, delta in events:
        cur += delta
        if cur > peak:
            peak = cur
    return int(peak)


def fit_kelly_from_pnl_pct(
    pnl_pcts: Sequence[float],
    spans: Sequence[tuple[date, date]],
) -> KellyFit:
    """``pnl_pcts`` are percent points (e.g. 12.2 for +12.2%)."""
    wins = [x for x in pnl_pcts if x > 0]
    losses = [x for x in pnl_pcts if x < 0]
    n = len(pnl_pcts)
    n_w = len(wins)
    n_l = len(losses)
    wr = (n_w / n) if n else 0.0
    avg_w = (sum(wins) / n_w) if n_w else 0.0
    avg_l = (sum(losses) / n_l) if n_l else 0.0
    b = (avg_w / abs(avg_l)) if avg_l < 0 else 0.0
    f = kelly_f_star(wr, b)
    peak = peak_concurrent(spans)
    note = ""
    if n < 30:
        note = "small IS N"
    if f <= 0:
        note = (note + "; " if note else "") + "no Kelly edge (f*=0)"
    return KellyFit(
        n=n,
        n_wins=n_w,
        n_losses=n_l,
        win_rate=wr,
        avg_win_pct=avg_w,
        avg_loss_pct=avg_l,
        payoff_b=b,
        f_star=f,
        peak_concurrent=max(peak, 1),
        note=note,
    )


def slot_dollars(
    fit: KellyFit,
    *,
    bankroll: float,
    kelly_fraction: float,
    sheet_cap: Optional[float] = None,
) -> float:
    """Equal dollars per fill: (fraction × f* × bankroll) / peak concurrent."""
    if fit.f_star <= 0 or fit.peak_concurrent <= 0 or bankroll <= 0:
        return 0.0
    raw = (float(kelly_fraction) * fit.f_star * float(bankroll)) / float(
        fit.peak_concurrent
    )
    if sheet_cap is not None and sheet_cap > 0:
        raw = min(raw, float(sheet_cap))
    return max(0.0, raw)


def risk_notional(
    *,
    q: float,
    bankroll: float,
    risk_pct: float,
    sheet_cap: Optional[float] = None,
    min_risk_pct: float = 0.002,
) -> Optional[float]:
    """Dollar notional so dollar risk = q × bankroll. ``risk_pct`` is (entry-stop)/entry.

    ``q`` must already be concurrent-aware (typically
    ``kelly_fraction * f_star / peak_concurrent``). Isolated ``0.25 * f_star``
    as a risk fraction over-bets once many names are on.
    """
    rp = float(risk_pct)
    if rp < min_risk_pct or q <= 0 or bankroll <= 0:
        return None
    raw = (float(q) * float(bankroll)) / rp
    if sheet_cap is not None and sheet_cap > 0:
        raw = min(raw, float(sheet_cap))
    return max(0.0, raw)
