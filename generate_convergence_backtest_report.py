#!/usr/bin/env python3
"""
31-day historical backtest: on the first day a symbol appears on 2+ systems
(IND/BRT/RL/YH watchlist or scanner — cross-system only), enter at next session open.

Exit rules (long):
  target = entry * (1 + 2.2 * ATR_PCT_trigger / 100)
  stop   = entry * (1 - 0.6 * ATR_PCT_trigger / 100)

ATR_PCT on trigger day from report row when present, else computed from OHLCV.
"""
from __future__ import annotations

import argparse
import html as html_mod
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "Drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
ET = ZoneInfo("America/New_York")

SYSTEMS = ("IND", "BRT", "RL", "YH")
LIST_KINDS = ("Watchlist", "Scanner")
FILE_RE = re.compile(r"^(IND|BRT|RL|YH)_(Watchlist|Scanner)_(\d{12})\.csv$", re.I)

ATR_TARGET_MULT = 2.2
ATR_STOP_MULT = 0.6
NOTIONAL = 10_000.0


@dataclass
class ListHit:
    system: str
    kind: str
    path: Path
    row: dict


@dataclass
class Signal:
    symbol: str
    overlap_date: date
    systems: set[str]
    lists: list[str]
    hits: list[ListHit] = field(default_factory=list)


@dataclass
class Trade:
    symbol: str
    overlap_date: date
    systems: str
    lists: str
    trigger_date: date
    atr_pct_trigger: float
    entry_date: date
    entry_price: float
    stop_price: float
    target_price: float
    exit_date: Optional[date]
    exit_price: Optional[float]
    exit_type: str
    days_held: int
    pnl_pct: float
    pnl_dollars: float
    max_favorable_pct: float
    max_adverse_pct: float
    still_open: bool


def _resolve_drive(drive: Path) -> Path:
    d = drive.resolve()
    if d.is_dir():
        return d
    alt = ROOT / "drive"
    if alt.is_dir():
        return alt.resolve()
    raise FileNotFoundError(f"Drive folder not found: {drive}")


def _parse_yyyymmdd(v) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _row_date(row: dict, report_date: date) -> date:
    for col in ("AS_OF_DATE", "ASOF_DATE", "DATE", "TRIGGER_DATE", "ENTRY_DATE"):
        d = _parse_yyyymmdd(row.get(col))
        if d:
            return d
    return report_date


def _first_numeric(row: dict, cols: list[str]) -> Optional[float]:
    for c in cols:
        if c not in row:
            continue
        v = row.get(c)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        try:
            return float(str(v).replace(",", "").replace("%", ""))
        except ValueError:
            continue
    return None


def _compute_atr_14(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    if n > 1:
        hl = high[1:] - low[1:]
        h_pc = np.abs(high[1:] - close[:-1])
        l_pc = np.abs(low[1:] - close[:-1])
        tr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr = np.full(n, np.nan, dtype=np.float64)
    if n >= period:
        atr[period - 1 :] = np.convolve(tr, np.ones(period) / period, mode="valid")
    return atr


class PriceBook:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._cache: dict[str, pd.DataFrame] = {}

    def load(self, symbol: str) -> Optional[pd.DataFrame]:
        sym = symbol.upper()
        if sym in self._cache:
            return self._cache[sym]
        path = self.data_dir / f"{sym}.csv"
        if not path.is_file():
            self._cache[sym] = None  # type: ignore[assignment]
            return None
        df = pd.read_csv(path)
        if df.empty or "Date" not in df.columns:
            self._cache[sym] = None  # type: ignore[assignment]
            return None
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
        df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ("Open", "High", "Low", "Close"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        self._cache[sym] = df
        return df

    def atr_pct_on(self, symbol: str, on_date: date) -> Optional[float]:
        df = self.load(symbol)
        if df is None or df.empty:
            return None
        idx = df.index[df["Date"] == on_date]
        if len(idx) == 0:
            return None
        i = int(idx[0])
        hi = df["High"].to_numpy(dtype=np.float64)
        lo = df["Low"].to_numpy(dtype=np.float64)
        cl = df["Close"].to_numpy(dtype=np.float64)
        atr = _compute_atr_14(hi, lo, cl)
        a14 = float(atr[i])
        px = float(cl[i])
        if not (np.isfinite(a14) and np.isfinite(px) and px > 0):
            return None
        return (a14 / px) * 100.0

    def next_open_after(self, symbol: str, after_date: date) -> tuple[Optional[date], Optional[float]]:
        df = self.load(symbol)
        if df is None:
            return None, None
        sub = df[df["Date"] > after_date]
        if sub.empty:
            return None, None
        row = sub.iloc[0]
        op = float(row["Open"]) if pd.notna(row["Open"]) else None
        return row["Date"], op

    def simulate_long(
        self,
        symbol: str,
        entry_date: date,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> tuple[Optional[date], Optional[float], str, int, float, float]:
        df = self.load(symbol)
        if df is None:
            return None, None, "NO_DATA", 0, 0.0, 0.0
        sub = df[df["Date"] >= entry_date].reset_index(drop=True)
        if sub.empty:
            return None, None, "NO_DATA", 0, 0.0, 0.0

        max_fav = 0.0
        max_adv = 0.0
        for i, row in sub.iterrows():
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            d = row["Date"]
            if i == 0:
                # Entry bar: evaluate from entry open
                max_fav = max(max_fav, (h / entry_price - 1) * 100)
                max_adv = min(max_adv, (l / entry_price - 1) * 100)
                if l <= stop_price:
                    xp = o if o <= stop_price else stop_price
                    return d, xp, "STOP", i, max_fav, max_adv
                if h >= target_price:
                    xp = o if o >= target_price else target_price
                    return d, xp, "TARGET", i, max_fav, max_adv
                continue
            max_fav = max(max_fav, (h / entry_price - 1) * 100)
            max_adv = min(max_adv, (l / entry_price - 1) * 100)
            if o <= stop_price:
                return d, o, "STOP", i, max_fav, max_adv
            if l <= stop_price:
                return d, stop_price, "STOP", i, max_fav, max_adv
            if o >= target_price:
                return d, o, "TARGET", i, max_fav, max_adv
            if h >= target_price:
                return d, target_price, "TARGET", i, max_fav, max_adv

        last = sub.iloc[-1]
        return last["Date"], float(last["Close"]), "OPEN", len(sub) - 1, max_fav, max_adv


def _index_files_by_day(drive: Path, start: date, end: date) -> dict[date, dict[str, Path]]:
    """For each calendar day, latest file per SYSTEM_Kind."""
    best: dict[tuple[date, str], tuple[str, Path]] = {}
    for path in drive.glob("*.csv"):
        m = FILE_RE.match(path.name)
        if not m:
            continue
        sys_name, kind, ts = m.group(1).upper(), m.group(2), m.group(3)
        d = date(2000 + int(ts[:2]), int(ts[2:4]), int(ts[4:6]))
        if d < start or d > end:
            continue
        key = (d, f"{sys_name}_{kind}")
        if key not in best or ts > best[key][0]:
            best[key] = (ts, path)

    out: dict[date, dict[str, Path]] = {}
    for (d, sk), (_, path) in best.items():
        out.setdefault(d, {})[sk] = path
    return out


def _symbols_from_file(path: Path, report_date: date) -> dict[str, ListHit]:
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if df.empty or "SYMBOL" not in df.columns:
        return {}
    parts = path.stem.split("_")
    system = parts[0].upper()
    kind = parts[1]
    hits: dict[str, ListHit] = {}
    for _, row in df.iterrows():
        sym = str(row.get("SYMBOL", "")).strip().upper()
        if not sym or sym in hits:
            continue
        hits[sym] = ListHit(system=system, kind=kind, path=path, row=row.to_dict())
    return hits


def _daily_cross_system(day_files: dict[str, Path], report_date: date) -> dict[str, Signal]:
    by_system: dict[str, dict[str, ListHit]] = {s: {} for s in SYSTEMS}
    for key, path in day_files.items():
        sys_name = key.split("_")[0]
        if sys_name not in by_system:
            continue
        for sym, hit in _symbols_from_file(path, report_date).items():
            by_system[sys_name][sym] = hit

    symbol_systems: dict[str, set[str]] = {}
    symbol_hits: dict[str, list[ListHit]] = {}
    for sys_name, sym_map in by_system.items():
        for sym in sym_map:
            symbol_systems.setdefault(sym, set()).add(sys_name)
            symbol_hits.setdefault(sym, []).append(sym_map[sym])

    signals: dict[str, Signal] = {}
    for sym, systems in symbol_systems.items():
        if len(systems) < 2:
            continue
        lists = sorted({f"{h.system}_{h.kind}" for h in symbol_hits[sym]})
        signals[sym] = Signal(
            symbol=sym,
            overlap_date=report_date,
            systems=systems,
            lists=lists,
            hits=symbol_hits[sym],
        )
    return signals


def _atr_pct_for_signal(signal: Signal, prices: PriceBook) -> tuple[float, date]:
    trigger_dates = [_row_date(h.row, signal.overlap_date) for h in signal.hits]
    trigger_date = min(trigger_dates)
    atr_vals: list[float] = []
    for h in signal.hits:
        v = _first_numeric(h.row, ["ATR_PCT_AT_TRIGGER", "ATR_PCT_AT_ENTRY"])
        if v is not None and v > 0:
            atr_vals.append(v)
    if atr_vals:
        return float(np.median(atr_vals)), trigger_date
    computed = prices.atr_pct_on(signal.symbol, trigger_date)
    if computed is not None and computed > 0:
        return computed, trigger_date
    # fallback: try overlap report date
    computed = prices.atr_pct_on(signal.symbol, signal.overlap_date)
    if computed is not None and computed > 0:
        return computed, signal.overlap_date
    return 0.0, trigger_date


def run_backtest(
    drive_dir: Path,
    *,
    lookback_days: int = 31,
    end_date: Optional[date] = None,
    data_dir: Path = DATA_DIR,
) -> tuple[pd.DataFrame, dict]:
    drive = _resolve_drive(drive_dir)
    end = end_date or datetime.now(tz=ET).date()
    start = end - timedelta(days=lookback_days)

    by_day = _index_files_by_day(drive, start, end)
    prices = PriceBook(data_dir)

    traded: set[str] = set()
    trades: list[Trade] = []
    overlap_events = 0

    for d in sorted(by_day.keys()):
        signals = _daily_cross_system(by_day[d], d)
        overlap_events += len(signals)
        for sym, sig in sorted(signals.items()):
            if sym in traded:
                continue
            atr_pct, trigger_date = _atr_pct_for_signal(sig, prices)
            if atr_pct <= 0:
                continue
            entry_date, entry_price = prices.next_open_after(sym, trigger_date)
            if entry_date is None or entry_price is None or entry_price <= 0:
                continue

            stop = entry_price * (1.0 - ATR_STOP_MULT * atr_pct / 100.0)
            target = entry_price * (1.0 + ATR_TARGET_MULT * atr_pct / 100.0)
            exit_date, exit_price, exit_type, days_held, max_fav, max_adv = prices.simulate_long(
                sym, entry_date, entry_price, stop, target
            )
            still_open = exit_type == "OPEN"
            pnl_pct = 0.0
            pnl_dollars = 0.0
            if exit_price is not None and entry_price > 0:
                pnl_pct = (exit_price / entry_price - 1.0) * 100.0
                pnl_dollars = NOTIONAL * (exit_price / entry_price - 1.0)

            traded.add(sym)
            trades.append(
                Trade(
                    symbol=sym,
                    overlap_date=sig.overlap_date,
                    systems=", ".join(sorted(sig.systems)),
                    lists=", ".join(sig.lists),
                    trigger_date=trigger_date,
                    atr_pct_trigger=round(atr_pct, 4),
                    entry_date=entry_date,
                    entry_price=round(entry_price, 4),
                    stop_price=round(stop, 4),
                    target_price=round(target, 4),
                    exit_date=exit_date,
                    exit_price=round(exit_price, 4) if exit_price is not None else None,
                    exit_type=exit_type,
                    days_held=days_held,
                    pnl_pct=round(pnl_pct, 4),
                    pnl_dollars=round(pnl_dollars, 2),
                    max_favorable_pct=round(max_fav, 4),
                    max_adverse_pct=round(max_adv, 4),
                    still_open=still_open,
                )
            )

    df = pd.DataFrame([t.__dict__ for t in trades])
    closed = df[~df["still_open"]] if not df.empty else df
    meta = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days_with_files": len(by_day),
        "overlap_events": overlap_events,
        "trades_entered": len(df),
        "closed_trades": len(closed),
        "wins": int((closed["pnl_pct"] > 0).sum()) if not closed.empty else 0,
        "losses": int((closed["pnl_pct"] < 0).sum()) if not closed.empty else 0,
        "total_pnl_pct": float(closed["pnl_pct"].sum()) if not closed.empty else 0.0,
        "total_pnl_dollars": float(closed["pnl_dollars"].sum()) if not closed.empty else 0.0,
        "avg_pnl_pct": float(closed["pnl_pct"].mean()) if not closed.empty else 0.0,
        "avg_days_held": float(closed["days_held"].mean()) if not closed.empty else 0.0,
    }
    return df, meta


def _write_html(df: pd.DataFrame, meta: dict, path: Path) -> None:
    rows = []
    cols = [
        "symbol",
        "overlap_date",
        "systems",
        "lists",
        "trigger_date",
        "atr_pct_trigger",
        "entry_date",
        "entry_price",
        "stop_price",
        "target_price",
        "exit_date",
        "exit_price",
        "exit_type",
        "days_held",
        "pnl_pct",
        "pnl_dollars",
        "max_favorable_pct",
        "max_adverse_pct",
        "still_open",
    ]
    for _, r in df.iterrows():
        rows.append("<tr>" + "".join(f"<td>{html_mod.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>")

    table = (
        "<table><thead><tr>"
        + "".join(f"<th>{html_mod.escape(c)}</th>" for c in cols)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        if not df.empty
        else "<p>No trades entered.</p>"
    )

    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Convergence Backtest</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1400px; }}
h1 {{ font-size:1.4rem; }}
.sub {{ color:#64748b; margin-bottom:16px; line-height:1.5; }}
.cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }}
.card {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px; min-width:140px; }}
.card h3 {{ margin:0 0 6px; font-size:12px; color:#475569; }}
.metric {{ font-size:1.4rem; font-weight:700; }}
table {{ border-collapse:collapse; font-size:11px; width:100%; min-width:900px; }}
th, td {{ border:1px solid #e2e8f0; padding:6px 8px; text-align:left; }}
th {{ background:#f1f5f9; }}
.table-wrap {{ overflow-x:auto; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
</style></head><body>
<h1>Cross-System Convergence Backtest (31 days)</h1>
<p class="sub">
  First cross-system overlap (IND/BRT/RL/YH watchlist or scanner) → buy next open.<br>
  Target = entry × (1 + {ATR_TARGET_MULT}×ATR%) · Stop = entry × (1 − {ATR_STOP_MULT}×ATR%) · ATR% on trigger day.<br>
  Window: {html_mod.escape(meta['start'])} → {html_mod.escape(meta['end'])} · Days with files: {meta['days_with_files']}
</p>
<div class="cards">
  <div class="card"><h3>Trades entered</h3><div class="metric">{meta['trades_entered']}</div></div>
  <div class="card"><h3>Closed</h3><div class="metric">{meta['closed_trades']}</div></div>
  <div class="card"><h3>W / L</h3><div class="metric">{meta['wins']} / {meta['losses']}</div></div>
  <div class="card"><h3>Total PnL ($10k/trade)</h3><div class="metric {'pos' if meta['total_pnl_dollars']>=0 else 'neg'}">${meta['total_pnl_dollars']:+,.0f}</div></div>
  <div class="card"><h3>Total PnL %</h3><div class="metric {'pos' if meta['total_pnl_pct']>=0 else 'neg'}">{meta['total_pnl_pct']:+.2f}%</div></div>
  <div class="card"><h3>Avg PnL %</h3><div class="metric">{meta['avg_pnl_pct']:+.2f}%</div></div>
  <div class="card"><h3>Avg days held</h3><div class="metric">{meta['avg_days_held']:.1f}</div></div>
  <div class="card"><h3>Overlap events</h3><div class="metric">{meta['overlap_events']}</div></div>
</div>
<div class="table-wrap">{table}</div>
<p class="sub"><a href="convergence.html">Latest convergence</a> · <a href="investment.html">Investment report</a> · <a href="index.html">Scanner open report</a></p>
</body></html>"""
    path.write_text(body, encoding="utf-8")


def build_report(
    drive_dir: Path,
    *,
    lookback_days: int = 31,
    output_path: Optional[Path] = None,
) -> tuple[Path, Path, pd.DataFrame, dict]:
    df, meta = run_backtest(drive_dir, lookback_days=lookback_days)
    drive = _resolve_drive(drive_dir)
    stamp = datetime.now(tz=ET).strftime("%Y%m%d_%H%M%S")
    out_csv = output_path or (drive / f"Convergence_Backtest_{stamp}.csv")
    out_html = out_csv.with_suffix(".html")
    df.to_csv(out_csv, index=False)
    _write_html(df, meta, out_html)
    latest_csv = drive / "Convergence_Backtest_Latest.csv"
    latest_html = drive / "Convergence_Backtest_Latest.html"
    shutil.copy2(out_csv, latest_csv)
    shutil.copy2(out_html, latest_html)
    return out_csv, out_html, df, meta


def main() -> int:
    p = argparse.ArgumentParser(description="31-day cross-system convergence backtest")
    p.add_argument("--drive", type=Path, default=DRIVE)
    p.add_argument("--days", type=int, default=31)
    p.add_argument("-o", "--output", type=Path, default=None)
    args = p.parse_args()

    out_csv, out_html, df, meta = build_report(args.drive, lookback_days=args.days, output_path=args.output)
    print(f"Wrote {out_csv} ({len(df)} trades)")
    print(f"Wrote {out_html}")
    print(
        f"Closed: {meta['closed_trades']} · W/L: {meta['wins']}/{meta['losses']} · "
        f"Total PnL: {meta['total_pnl_pct']:+.2f}% · Avg: {meta['avg_pnl_pct']:+.2f}%"
    )
    if not df.empty:
        sold = df[~df["still_open"]].sort_values("pnl_pct", ascending=False)
        if not sold.empty:
            print("\nTop 10 winners (closed):")
            print(
                sold.head(10)[
                    ["symbol", "systems", "entry_date", "exit_date", "days_held", "pnl_pct", "exit_type"]
                ].to_string(index=False)
            )
            print("\nTop 10 losers (closed):")
            print(
                sold.tail(10)[
                    ["symbol", "systems", "entry_date", "exit_date", "days_held", "pnl_pct", "exit_type"]
                ].to_string(index=False)
            )
            by_sys = sold.groupby("systems").agg(
                n=("symbol", "count"),
                pnl_pct=("pnl_pct", "sum"),
                pnl_dollars=("pnl_dollars", "sum"),
                avg_days=("days_held", "mean"),
            )
            print("\nBy system pair (closed):")
            print(by_sys.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
