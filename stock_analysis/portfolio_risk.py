"""Portfolio-level risk for the live book: one view across every system.

The book-guard in live_style_sizing caps names (8) and gross (<= equity) but
cannot see three things that drove the 2026-06/07 drawdown:

  heat        $ lost if every open lot hits its stop = sum qty * max(0, price - stop)
  loss halts  today's and month-to-date P&L across ALL systems (realized + open)
  overlap     open names that move together; 8 names at avg corr 0.6 is ~1.6 bets

`evaluate()` turns that into a decision the allotment step obeys:
  halt_new_buys  -> every new trigger becomes NONE (risk halt)
  max_new_buys   -> how many TAKEs the remaining heat budget allows

Freeze: RISK_STAMP below. Change limits only through governance/adopt.py.
CLI:    python stock_analysis/portfolio_risk.py   (prints today's status)
"""
from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OHLCV_DIR = REPO / "data" / "newdata" / "data"
CLOSED_LOG = REPO / "closed_positions_log.csv"
GETTARGET_OUT = REPO / "getTarget_output.csv"

RISK_STAMP = "portfolio_risk_v1_20261112"


@dataclass(frozen=True)
class RiskLimits:
    max_heat_frac: float = 0.05        # open risk to stops <= 5% of equity
    daily_loss_halt_frac: float = 0.02  # no new buys after a -2% day (whole book)
    mtd_loss_halt_frac: float = 0.06    # no new buys after -6% month-to-date
    risk_per_new_trade_frac: float = 0.01  # matches live_style_sizing RISK_FRAC
    corr_window: int = 60
    warn_avg_corr: float = 0.5


@dataclass
class Position:
    symbol: str
    system: str
    qty: float
    entry: float
    stop: Optional[float]
    price: Optional[float]
    prev_close: Optional[float]
    month_ref: Optional[float]  # entry if bought this month, else prior month's last close

    @property
    def notional(self) -> float:
        return self.qty * (self.price or self.entry)

    @property
    def heat(self) -> float:
        """$ lost to the stop from here. No stop = whole position at risk."""
        px = self.price or self.entry
        if self.stop is None or self.stop <= 0:
            return self.qty * px
        return self.qty * max(0.0, px - self.stop)


@dataclass
class RiskReport:
    stamp: str
    asof: str
    equity: float
    n_positions: int
    gross: float
    heat: float
    heat_frac: float
    day_pnl: float
    day_frac: float
    mtd_pnl: float
    mtd_frac: float
    avg_corr: Optional[float]
    effective_bets: Optional[float]
    halt_new_buys: bool
    halt_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    max_new_buys: int = 0
    positions: list[dict] = field(default_factory=list)
    limits: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _closes(symbol: str, data_dir: Path) -> Optional[pd.Series]:
    p = data_dir / f"{symbol}.csv"
    if not p.is_file():
        return None
    df = pd.read_csv(p, usecols=["Date", "Close"], parse_dates=["Date"])
    return df.set_index("Date")["Close"].sort_index()


def build_positions(
    lots: Iterable[Any],
    stops: Mapping[str, float],
    *,
    asof: date,
    data_dir: Path = OHLCV_DIR,
) -> list[Position]:
    """Lots are Lot-like objects or dicts with symbol, qty, buy_price (and optional system, buy_date)."""
    out: list[Position] = []
    m0 = pd.Timestamp(asof.year, asof.month, 1)
    for lot in lots:
        g = (lambda k, d=None: lot.get(k, d)) if isinstance(lot, Mapping) else (lambda k, d=None: getattr(lot, k, d))
        sym = str(g("symbol", "") or "").strip().upper()
        qty = _f(g("qty")) or 0.0
        entry = _f(g("buy_price")) or 0.0
        if not sym or qty <= 0 or entry <= 0:
            continue
        cl = _closes(sym, data_dir)
        price = prev = ref = None
        if cl is not None and len(cl):
            cl = cl[: pd.Timestamp(asof)]
            price = float(cl.iloc[-1])
            prev = float(cl.iloc[-2]) if len(cl) > 1 else None
            before = cl[cl.index < m0]
            ref = float(before.iloc[-1]) if len(before) else None
        bdate = pd.to_datetime(str(g("buy_date", "") or ""), errors="coerce")
        if pd.notna(bdate) and bdate >= m0:
            ref = entry
        if pd.notna(bdate) and prev is not None and bdate.normalize() == pd.Timestamp(asof):
            prev = entry  # bought today: today's P&L is from the fill
        out.append(Position(sym, str(g("system", "") or ""), qty, entry, stops.get(sym), price, prev, ref))
    return out


def stops_from_gettarget(path: Path = GETTARGET_OUT) -> dict[str, float]:
    """Live stop per symbol: the higher of StopTrailing / StopInitial (getTarget owns these)."""
    out: dict[str, float] = {}
    if not path.is_file():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sym = str(row.get("Symbol", "")).strip().upper()
            vals = [v for v in (_f(row.get("StopTrailing")), _f(row.get("StopInitial"))) if v and v > 0]
            if sym and vals:
                out[sym] = max(out.get(sym, 0.0), max(vals))
    return out


def realized_mtd(asof: date, path: Path = CLOSED_LOG) -> float:
    if not path.is_file():
        return 0.0
    df = pd.read_csv(path)
    if df.empty or "sell_date" not in df:
        return 0.0
    sd = pd.to_datetime(df["sell_date"], errors="coerce")
    m = (sd.dt.year == asof.year) & (sd.dt.month == asof.month) & (sd.dt.date <= asof)
    return float(pd.to_numeric(df.loc[m, "pnl_dollars"], errors="coerce").fillna(0).sum())


def realized_on(asof: date, path: Path = CLOSED_LOG) -> float:
    if not path.is_file():
        return 0.0
    df = pd.read_csv(path)
    if df.empty or "sell_date" not in df:
        return 0.0
    sd = pd.to_datetime(df["sell_date"], errors="coerce").dt.date
    return float(pd.to_numeric(df.loc[sd == asof, "pnl_dollars"], errors="coerce").fillna(0).sum())


def correlation(symbols: list[str], *, asof: date, window: int, data_dir: Path = OHLCV_DIR) -> tuple[Optional[float], Optional[float]]:
    """(average pairwise correlation of daily returns, effective independent bets)."""
    syms = sorted(set(symbols))
    if len(syms) < 2:
        return None, (float(len(syms)) if syms else None)
    rets = {}
    for s in syms:
        cl = _closes(s, data_dir)
        if cl is not None:
            rets[s] = cl[: pd.Timestamp(asof)].pct_change().tail(window)
    df = pd.DataFrame(rets).dropna()
    if df.shape[1] < 2 or len(df) < 20:
        return None, None
    c = df.corr().to_numpy()
    n = c.shape[0]
    rho = float((c.sum() - n) / (n * (n - 1)))
    eff = n / (1 + (n - 1) * max(rho, 0.0))
    return round(rho, 3), round(eff, 2)


def evaluate(
    positions: list[Position],
    *,
    equity: float,
    asof: date,
    limits: RiskLimits = RiskLimits(),
    realized_today: float = 0.0,
    realized_month: float = 0.0,
    data_dir: Path = OHLCV_DIR,
) -> RiskReport:
    eq = max(float(equity), 1.0)
    gross = sum(p.notional for p in positions)
    heat = sum(p.heat for p in positions)
    day = realized_today + sum(p.qty * (p.price - p.prev_close) for p in positions
                               if p.price is not None and p.prev_close is not None)
    mtd = realized_month + sum(p.qty * (p.price - p.month_ref) for p in positions
                               if p.price is not None and p.month_ref is not None)
    rho, eff = correlation([p.symbol for p in positions], asof=asof, window=limits.corr_window, data_dir=data_dir)

    reasons, warns = [], []
    if heat / eq >= limits.max_heat_frac:
        reasons.append(f"heat {heat / eq:.1%} of equity >= {limits.max_heat_frac:.0%} cap")
    if day / eq <= -limits.daily_loss_halt_frac:
        reasons.append(f"today {day / eq:+.1%} <= -{limits.daily_loss_halt_frac:.0%} daily halt")
    if mtd / eq <= -limits.mtd_loss_halt_frac:
        reasons.append(f"month-to-date {mtd / eq:+.1%} <= -{limits.mtd_loss_halt_frac:.0%} monthly halt")
    no_stop = [p.symbol for p in positions if p.stop is None]
    if no_stop:
        warns.append(f"no live stop for {', '.join(no_stop)} (counted as fully at risk)")
    if rho is not None and rho >= limits.warn_avg_corr:
        warns.append(f"open names move together (avg corr {rho:.2f}, ~{eff:.1f} independent bets)")

    room = limits.max_heat_frac * eq - heat
    per_trade = limits.risk_per_new_trade_frac * eq
    max_new = 0 if reasons else max(0, int(room // per_trade)) if per_trade > 0 else 0

    return RiskReport(
        stamp=RISK_STAMP, asof=str(asof), equity=eq, n_positions=len(positions),
        gross=round(gross, 2), heat=round(heat, 2), heat_frac=round(heat / eq, 4),
        day_pnl=round(day, 2), day_frac=round(day / eq, 4), mtd_pnl=round(mtd, 2), mtd_frac=round(mtd / eq, 4),
        avg_corr=rho, effective_bets=eff, halt_new_buys=bool(reasons), halt_reasons=reasons, warnings=warns,
        max_new_buys=max_new,
        positions=[{"symbol": p.symbol, "system": p.system, "qty": p.qty, "price": p.price, "stop": p.stop,
                    "notional": round(p.notional, 2), "heat": round(p.heat, 2)} for p in positions],
        limits=asdict(limits),
    )


def format_risk_html(r: RiskReport) -> str:
    """Small panel for investment.html, same visual language as the allotment block."""
    import html as _h
    state = "HALT — no new buys" if r.halt_new_buys else f"OK — room for {r.max_new_buys} new buy(s)"
    color = "#b42318" if r.halt_new_buys else "#067647"
    corr = "—" if r.avg_corr is None else f"{r.avg_corr:.2f} (~{r.effective_bets:.1f} bets)"
    lines = "".join(f"<li>{_h.escape(x)}</li>" for x in r.halt_reasons + r.warnings)
    return (
        f'<div class="portfolio-risk" style="border:1px solid {color};border-radius:8px;padding:10px 14px;margin:12px 0">'
        f'<div style="font-weight:600;color:{color}">Portfolio risk: {_h.escape(state)}</div>'
        f'<div class="small">Heat (loss if every stop hits) ${r.heat:,.0f} = {r.heat_frac:.1%} of equity '
        f'(cap {r.limits["max_heat_frac"]:.0%}) · Gross ${r.gross:,.0f} · Today ${r.day_pnl:+,.0f} ({r.day_frac:+.1%}) · '
        f'Month ${r.mtd_pnl:+,.0f} ({r.mtd_frac:+.1%}) · Avg corr {corr} · {r.n_positions} open</div>'
        + (f'<ul class="small" style="margin:6px 0 0 18px">{lines}</ul>' if lines else "")
        + f'<div class="small" style="opacity:.7">Freeze {_h.escape(r.stamp)}</div></div>'
    )


def main() -> int:
    import json
    import sys
    sys.path.insert(0, str(REPO / "stock_analysis"))
    from live_style_sizing import load_account_state  # noqa: E402

    acct = load_account_state()
    asof = date.today()
    lots = []
    gt = REPO / "getTarget_output.csv"
    if gt.is_file():
        for row in csv.DictReader(open(gt, newline="", encoding="utf-8")):
            lots.append({"symbol": row.get("Symbol"), "system": row.get("System"), "buy_date": row.get("PurchaseDate"),
                         "buy_price": row.get("EntryPrice"), "qty": row.get("SuggestedShares")})
    pos = build_positions(lots, stops_from_gettarget(), asof=asof)
    rep = evaluate(pos, equity=acct.current_equity, asof=asof,
                   realized_today=realized_on(asof), realized_month=realized_mtd(asof))
    print(json.dumps(rep.to_dict(), indent=2, default=str))
    print("\nNOTE: CLI uses getTarget SuggestedShares as qty; the report uses the real open lots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
