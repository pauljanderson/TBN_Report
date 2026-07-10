#!/usr/bin/env python3
"""Gap-up on entry day — all symbols, all systems (SHEET, BRT, YH, IND, RL).

Overnight gap = (entry-day OPEN / trigger-day CLOSE - 1) * 100.

Trigger day:
  - BRT / YH: CLOSE_ABOVE_DATE (retest day)
  - IND: CLOSE_ABOVE_DATE when present, else prior session before DATE_OPENED
  - RL: prior trading session before DATE OPENED (50-trigger)
  - SHEET: ledger trigger column (MAG7+NFLX only in sheet_trade_ledgers.py)

Usage:
  python tools/gap_up_all_systems.py              # newest Closed_* per engine
  python tools/gap_up_all_systems.py 260626133218 # same run id where available
  python tools/gap_up_all_systems.py --mag7-only
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from compare_sheet_trades import _trading_days, load_sheet, next_td  # noqa: E402
from sheet_trade_ledgers import DEFAULT_SYMBOLS, SHEET_LEDGER  # noqa: E402

DATA = ROOT / "data" / "newdata" / "data"
ENGINE_PREFIXES = ("BRT", "YH", "IND", "RL")
MAG7 = DEFAULT_SYMBOLS


@dataclass
class GapStats:
    system: str
    picks: int = 0
    gap_up: int = 0
    gap_sum: float = 0.0
    gap_up_sum: float = 0.0
    by_symbol: dict[str, tuple[int, int, float, float]] = field(default_factory=dict)
    thresholds: dict[float, int] = field(default_factory=dict)

    def add(self, sym: str, gap_pct: float) -> None:
        self.picks += 1
        self.gap_sum += gap_pct
        is_up = gap_pct > 0
        if is_up:
            self.gap_up += 1
            self.gap_up_sum += gap_pct
        for thr in (0.5, 1.0, 2.0, 5.0):
            if gap_pct >= thr:
                self.thresholds[thr] = self.thresholds.get(thr, 0) + 1
        p, u, gs, us = self.by_symbol.get(sym, (0, 0, 0.0, 0.0))
        self.by_symbol[sym] = (p + 1, u + int(is_up), gs + gap_pct, us + (gap_pct if is_up else 0.0))


@lru_cache(maxsize=4096)
def _ohlc_map(sym: str) -> dict[str, tuple[float, float, float, float]]:
    path = DATA / f"{sym}.csv"
    if not path.is_file():
        return {}
    df = pd.read_csv(path, parse_dates=["Date"]).sort_values("Date")
    return {
        row.Date.strftime("%Y-%m-%d"): (float(row.Open), float(row.High), float(row.Low), float(row.Close))
        for row in df.itertuples()
    }


@lru_cache(maxsize=8192)
def _prev_td(sym: str, iso: str) -> str:
    days = _trading_days(sym)
    if iso not in days:
        return ""
    i = days.index(iso)
    return days[i - 1] if i > 0 else ""


def _gap_for(sym: str, trigger: str, purchase: str) -> float | None:
    cmap = _ohlc_map(sym)
    tc = cmap.get(trigger)
    te = cmap.get(purchase)
    if not tc or not te:
        return None
    trig_close = tc[3]
    entry_open = te[0]
    if trig_close <= 0:
        return None
    return (entry_open / trig_close - 1.0) * 100.0


def _newest_closed(prefix: str) -> Path | None:
    best: tuple[Path, float] | None = None
    for sub in ("drive", "Drive"):
        d = ROOT / sub
        if not d.is_dir():
            continue
        for p in d.glob(f"{prefix}_Closed_[0-9]*.csv"):
            mt = p.stat().st_mtime
            if best is None or mt > best[1]:
                best = (p, mt)
    return best[0] if best else None


def _resolve_path(prefix: str, run_id: str | None) -> Path | None:
    if run_id:
        for sub in ("drive", "Drive"):
            p = ROOT / sub / f"{prefix}_Closed_{run_id}.csv"
            if p.is_file():
                return p
    return _newest_closed(prefix)


def _run_id(path: Path) -> str:
    for prefix in ENGINE_PREFIXES:
        tag = f"{prefix}_Closed_"
        if path.stem.startswith(tag):
            return path.stem[len(tag) :]
    return path.stem


def _load_sheet_stats(symbols: list[str] | None) -> GapStats:
    stats = GapStats("SHEET")
    syms = symbols if symbols else list(SHEET_LEDGER.keys())
    for sym in syms:
        if sym not in SHEET_LEDGER:
            continue
        iso = _trading_days(sym)
        sh = load_sheet(SHEET_LEDGER[sym])
        for _, r in sh.iterrows():
            trig = r["trigger_d"]
            purch = next_td(iso, trig)
            gap = _gap_for(sym, trig, purch)
            if gap is not None:
                stats.add(sym, gap)
    return stats


def _load_cad_stats(path: Path, prefix: str, symbols: list[str] | None) -> GapStats:
    stats = GapStats(f"{prefix}({_run_id(path)})")
    sym_set = set(s.upper() for s in symbols) if symbols else None
    usecols = ["SYMBOL", "DATE_OPENED", "CLOSE_ABOVE_DATE"]
    # IND exports often omit CLOSE_ABOVE_DATE; fall back to prior session (same as RL).
    cad_fallback_prev_td = prefix == "IND"
    for chunk in pd.read_csv(path, usecols=lambda c: c in usecols, chunksize=250_000):
        if sym_set is not None:
            chunk = chunk[chunk["SYMBOL"].astype(str).str.upper().isin(sym_set)]
        for _, r in chunk.iterrows():
            sym = str(r["SYMBOL"]).upper()
            cad = pd.to_datetime(r.get("CLOSE_ABOVE_DATE"), errors="coerce")
            if pd.isna(cad):
                if not cad_fallback_prev_td:
                    continue
                purch = pd.to_datetime(str(r["DATE_OPENED"]), format="%Y%m%d").strftime("%Y-%m-%d")
                trig = _prev_td(sym, purch)
                if not trig:
                    continue
            else:
                trig = cad.strftime("%Y-%m-%d")
                purch = pd.to_datetime(str(r["DATE_OPENED"]), format="%Y%m%d").strftime("%Y-%m-%d")
            gap = _gap_for(sym, trig, purch)
            if gap is not None:
                stats.add(sym, gap)
    return stats


def _load_rl_stats(path: Path, symbols: list[str] | None) -> GapStats:
    stats = GapStats(f"RL({_run_id(path)})")
    sym_set = set(s.upper() for s in symbols) if symbols else None
    usecols = ["SYMBOL", "DATE OPENED"]
    for chunk in pd.read_csv(path, usecols=lambda c: c in usecols, chunksize=250_000):
        if sym_set is not None:
            chunk = chunk[chunk["SYMBOL"].astype(str).str.upper().isin(sym_set)]
        for _, r in chunk.iterrows():
            sym = str(r["SYMBOL"]).upper()
            purch = pd.to_datetime(str(r["DATE OPENED"]), format="%Y%m%d").strftime("%Y-%m-%d")
            trig = _prev_td(sym, purch)
            if not trig:
                continue
            gap = _gap_for(sym, trig, purch)
            if gap is not None:
                stats.add(sym, gap)
    return stats


def _print_system(stats: GapStats) -> None:
    n = stats.picks
    if n == 0:
        print(f"\n{stats.system}: no picks with OHLC")
        return
    up = stats.gap_up
    print(f"\n{'=' * 90}")
    print(f"{stats.system}")
    print(f"  Picks (all symbols): {n:,}")
    print(f"  Gap-up (>0):         {up:,} ({100*up/n:.1f}%)")
    print(f"  Avg gap all picks:   {stats.gap_sum/n:+.3f}%")
    if up:
        print(f"  Avg gap when up:     {stats.gap_up_sum/up:+.3f}%")
    print(f"  Unique symbols:      {len(stats.by_symbol):,}")
    print("  Thresholds:")
    for thr in (0.5, 1.0, 2.0, 5.0):
        cnt = stats.thresholds.get(thr, 0)
        print(f"    >= {thr:4.1f}%: {cnt:6,} ({100*cnt/n:5.1f}%)")


def _top_symbols(stats: GapStats, min_picks: int = 10, top_n: int = 15) -> pd.DataFrame:
    rows = []
    for sym, (p, u, gs, us) in stats.by_symbol.items():
        if p < min_picks:
            continue
        rows.append(
            {
                "symbol": sym,
                "picks": p,
                "gap_up": u,
                "pct_up": 100.0 * u / p,
                "avg_all": gs / p,
                "avg_when_up": us / u if u else float("nan"),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["pct_up", "avg_when_up", "picks"], ascending=False).head(top_n)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gap-up analysis all systems, all symbols")
    ap.add_argument("run_id", nargs="?", default=None, help="BRT/YH/IND/RL run id (newest if omitted)")
    ap.add_argument("--mag7-only", action="store_true", help="Limit to MAG7+NFLX")
    ap.add_argument("--min-picks", type=int, default=10, help="Min picks per symbol for symbol ranking")
    args = ap.parse_args()

    symbols = MAG7 if args.mag7_only else None

    print("Overnight gap = entry-day OPEN vs trigger-day CLOSE")
    print(f"Universe: {'MAG7+NFLX' if symbols else 'ALL symbols in each Closed export'}")
    print(f"Run id: {args.run_id or 'newest per system'}")
    if not symbols:
        print("Note: SHEET ledger only covers MAG7+NFLX (embedded in sheet_trade_ledgers.py)")

    all_stats: list[GapStats] = []
    all_stats.append(_load_sheet_stats(symbols))

    for prefix in ENGINE_PREFIXES:
        path = _resolve_path(prefix, args.run_id)
        if path is None or not path.is_file():
            print(f"WARNING: missing {prefix}_Closed", file=sys.stderr)
            continue
        print(f"Loading {prefix} from {path.name}...", file=sys.stderr)
        if prefix == "RL":
            all_stats.append(_load_rl_stats(path, symbols))
        else:
            all_stats.append(_load_cad_stats(path, prefix, symbols))

    print("\n" + "=" * 90)
    print("SYSTEM RANKING — % of picks with overnight gap-up on entry")
    print("=" * 90)
    ranked = sorted(
        [s for s in all_stats if s.picks > 0],
        key=lambda s: (s.gap_up / s.picks, s.gap_up_sum / s.gap_up if s.gap_up else 0),
        reverse=True,
    )
    print(f"{'System':<28} {'Picks':>8} {'GapUp':>8} {'%Up':>7} {'AvgAll':>9} {'AvgUp':>9} {'Syms':>6}")
    print("-" * 90)
    for s in ranked:
        n, up = s.picks, s.gap_up
        avg_up = f"{s.gap_up_sum/up:+8.3f}%" if up else f"{'n/a':>9}"
        print(
            f"{s.system:<28} {n:8,} {up:8,} {100*up/n:6.1f}% "
            f"{s.gap_sum/n:+8.3f}% {avg_up} {len(s.by_symbol):6,}"
        )

    if ranked:
        best = ranked[0]
        print(
            f"\nMost gap-up entries: {best.system} — {100*best.gap_up/best.picks:.1f}% of picks "
            f"(avg +{best.gap_up_sum/best.gap_up:.2f}% when up, {best.picks:,} total picks)"
        )

    for s in ranked:
        _print_system(s)

    print("\n" + "=" * 90)
    print(f"TOP SYMBOLS BY GAP-UP RATE (min {args.min_picks} picks in that system)")
    print("=" * 90)
    for s in ranked:
        top = _top_symbols(s, min_picks=args.min_picks)
        print(f"\n{s.system}:")
        if top.empty:
            print("  (no symbols with enough picks)")
            continue
        for _, r in top.iterrows():
            print(
                f"  {r['symbol']:<6} {int(r['gap_up'])}/{int(r['picks'])} ({r['pct_up']:.1f}%)  "
                f"avg all {r['avg_all']:+.2f}%  avg when up {r['avg_when_up']:+.2f}%"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
