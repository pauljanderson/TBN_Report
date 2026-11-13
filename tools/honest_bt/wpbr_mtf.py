#!/usr/bin/env python3
"""WPBR on any pair of timeframes (research only; production WPBR is untouched).

Production WPBR = pivots/breakout/confirmation on WEEKLY bars, retest/entry/exits on DAILY bars.
This re-implements the same rules on a generic (pivot TF, retest TF) pair, reusing the zone
helpers in stock_analysis/wpbr_zones.py:

  1. Pivot high on the pivot TF: high above the 3 bars before and after, and >= strong% above the
     lowest low of the 3 bars before OR after.
  2. Zone = pivot high +/- band%, HALF_UP to 2 dp.
  3. Breakout = first pivot-TF close > zone top (from the pivot bar); confirmation = first pivot-TF
     high > top*(1+conf%) on/after it.
  4. Retest scan starts at the first retest-TF bar after the confirmation bar ends. Retest = low <=
     top and close > top, abandoned on a close < bottom. Signal = first green close > top within 2
     bars of the retest. Fill = next retest-TF bar open.
  5. Skip when an older zone's bottom is above this top by <= overhead%.
  6. Exits on retest-TF bars: gap through stop/target at the open fills at the open; else stop
     (stop_mult x signal-bar low) before target (entry x (1+target%)). One position per symbol;
     a winning first trade lets the zone trade once more (second chance).

Percent knobs are WPBR's production values times a timeframe scale `s` (volatility of the pivot TF
relative to weekly bars; s=1 reproduces production). `--placebo shift_level:<seed>` moves each
zone level by a random 5-15% x s (direction random), keeping everything else.

Modes:
  validate   weekly->daily on data/pit_daily, compare with the engine's pit/WPBR trades.
  run        --pivot-tf {W,D} --retest-tf {D,60,30} on a symbol list; writes trades CSV.

Examples:
  python tools/honest_bt/wpbr_mtf.py validate --limit 300
  python tools/honest_bt/wpbr_mtf.py run --pivot-tf D --retest-tf 60 --out drive/honest_bt/20261113/mtf/D_60
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "stock_analysis"))
import wpbr_zones as wz  # noqa: E402

PIT_DAILY = REPO / "data" / "pit_daily"
PIT_30M = REPO / "data" / "pit_30m"

# Production WPBR (run_wpbr.bat)
PROD = dict(pre=3, post=3, strong=0.10, band=0.015, conf=0.03, max_days=2,
            overhead=0.22, target=0.20, stop_mult=0.92)


@dataclass
class Params:
    s: float = 1.0                 # timeframe scale on every percent knob
    overhead_mode: str = "engine"  # engine | confirmed | causal (see overhead_blocked)
    placebo: str = ""              # "" or "shift_level:<seed>"
    second_chance: bool = True

    @property
    def strong(self): return PROD["strong"] * self.s
    @property
    def band(self): return PROD["band"] * self.s
    @property
    def conf(self): return PROD["conf"] * self.s
    @property
    def overhead(self): return PROD["overhead"] * self.s
    @property
    def target(self): return PROD["target"] * self.s
    @property
    def stop_mult(self): return 1.0 - (1.0 - PROD["stop_mult"]) * self.s


# ----------------------------------------------------------------------------- bars
def load_daily(sym: str) -> pd.DataFrame | None:
    p = PIT_DAILY / f"{sym}.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p, index_col=0, parse_dates=True)[["Open", "High", "Low", "Close", "Volume"]]
    d = d.dropna(subset=["Close"])
    d.index = pd.DatetimeIndex(d.index).normalize()
    d["start"] = d.index + pd.Timedelta(hours=9, minutes=30)
    d["end"] = d.index + pd.Timedelta(hours=16)
    return d


def load_intraday(sym: str, minutes: int) -> pd.DataFrame | None:
    p = PIT_30M / f"{sym}.parquet"
    if not p.exists():
        return None
    x = pd.read_parquet(p)
    if x.empty:
        return None
    x = x.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    if minutes == 30:
        b = x.set_index("ts")[["Open", "High", "Low", "Close", "Volume"]]
    else:
        # session-anchored buckets: 09:30, 10:30, ... (last bucket of the day is shorter)
        mins = (x.ts.dt.hour * 60 + x.ts.dt.minute) - (9 * 60 + 30)
        x["bucket"] = x["date"] + pd.Timedelta(hours=9, minutes=30) + pd.to_timedelta((mins // minutes) * minutes, unit="m")
        b = x.groupby("bucket").agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
                                    Close=("Close", "last"), Volume=("Volume", "sum"))
    b = b.sort_index()
    b["start"] = b.index
    day_end = b.index.normalize() + pd.Timedelta(hours=16)
    b["end"] = np.minimum((b.index + pd.Timedelta(minutes=minutes)).values, day_end.values)
    return b


def weekly_from_daily(d: pd.DataFrame) -> pd.DataFrame:
    w = wz.aggregate_weekly(d[["Open", "High", "Low", "Close", "Volume"]])
    g = d.groupby(pd.Grouper(freq="W-FRI"))
    w["start"] = g["start"].min().reindex(w.index)
    w["end"] = g["end"].max().reindex(w.index)
    return w.dropna(subset=["start"])


# ----------------------------------------------------------------------------- core
def _placebo_mult(spec: str, sym: str, pivot_key: str, s: float) -> float:
    if not spec:
        return 1.0
    mode, _, seed = spec.partition(":")
    if mode != "shift_level":
        raise SystemExit(f"unknown placebo {spec}")
    h = hashlib.sha256(f"{seed}|{sym}|{pivot_key}".encode()).digest()
    u1 = int.from_bytes(h[:8], "big") / 2**64
    u2 = int.from_bytes(h[8:16], "big") / 2**64
    mag = (0.05 + 0.10 * u1) * s
    return 1.0 + mag if u2 < 0.5 else 1.0 - mag


def simulate(sym: str, piv: pd.DataFrame, ret: pd.DataFrame, P: Params) -> list[dict]:
    wh = piv["High"].to_numpy(float)
    wl = piv["Low"].to_numpy(float)
    wc = piv["Close"].to_numpy(float)
    p_start = piv["start"].to_numpy("datetime64[ns]")
    p_end = piv["end"].to_numpy("datetime64[ns]")
    r_start = ret["start"].to_numpy("datetime64[ns]")
    r_end = ret["end"].to_numpy("datetime64[ns]")
    op = ret["Open"].to_numpy(float)
    hi = ret["High"].to_numpy(float)
    lo = ret["Low"].to_numpy(float)
    cl = ret["Close"].to_numpy(float)
    n = len(ret)
    if n < 5 or len(piv) < 8:
        return []
    lo_hu = wz._half_up_array(lo, 2)
    cl_hu = wz._half_up_array(cl, 2)
    op_hu = wz._half_up_array(op, 2)

    pivots = wz._weekly_pivot_indices(wh, wl, pre_bars=PROD["pre"], post_bars=PROD["post"],
                                      pre_pct=P.strong, post_pct=P.strong, pivot_mode="either")
    zones = []
    for wi in pivots:
        level = float(wh[wi]) * _placebo_mult(P.placebo, sym, str(p_start[wi]), P.s)
        _, zl, zh = wz._round_bounds(level, P.band, 2)
        # engine: an overhead zone counts from the first retest bar of its pivot bar (before the pivot
        # is known). confirmed/causal: only once the post bars have closed (confirm_t).
        born = int(np.searchsorted(r_start, p_start[wi], side="left"))
        if born >= n:
            continue
        cw = wi + PROD["post"]
        confirm_t = p_end[cw] if cw < len(piv) else np.datetime64("2262-01-01")
        _, conf = wz._find_weekly_breakout_and_confirm(wc, wh, start_week=wi, zone_upper=zh, confirm_pct=P.conf)
        scan = int(np.searchsorted(r_start, p_end[conf], side="left")) if conf is not None else None
        zones.append({"id": len(zones), "zl": zl, "zh": zh, "born": born, "scan": scan, "confirm_t": confirm_t,
                      "pivot": str(pd.Timestamp(p_start[wi]).date())})
    if not zones:
        return []
    z_born = np.array([z["born"] for z in zones])
    z_conf = np.array([z["confirm_t"] for z in zones], dtype="datetime64[ns]")
    z_lo = np.array([z["zl"] for z in zones])
    pre, post = PROD["pre"], PROD["post"]

    def _candidate_lowers(sig) -> list[float]:
        """Pivot-shaped highs visible at the signal close whose post bars have not all closed yet."""
        c = int(np.searchsorted(p_end, r_end[sig], side="right"))  # completed pivot-TF bars
        out = []
        for t in range(max(pre, c - post), c):
            h = float(wh[t])
            if not (h > float(np.max(wh[t - pre:t]))):
                continue
            if t + 1 < c and not (h > float(np.max(wh[t + 1:c]))):
                continue
            pre_ok = (h / float(np.min(wl[t - pre:t])) - 1.0) >= P.strong - 1e-12
            post_ok = t + 1 < c and (h / float(np.min(wl[t + 1:c])) - 1.0) >= P.strong - 1e-12
            if not (pre_ok or post_ok):
                continue
            lvl = h * _placebo_mult(P.placebo, sym, str(p_start[t]), P.s)
            out.append(wz._round_bounds(lvl, P.band, 2)[1])
        return out

    def overhead_blocked(z, sig):
        """Skip when an older zone's bottom sits above this zone's top by <= overhead.

        engine:    every zone whose pivot bar started before the signal (production; uses the future,
                   because a pivot is only known `post` bars later).
        confirmed: only zones whose pivot was confirmed by the signal close.
        causal:    confirmed zones plus still-unconfirmed pivot-shaped highs visible at the signal close.
        """
        up = z["zh"]
        gap = (z_lo - up) / up
        if P.overhead_mode == "engine":
            seen = z_born < sig
        else:
            seen = z_conf <= r_end[sig]
        q = (np.arange(len(zones)) != z["id"]) & seen & (z_lo > up) & (gap <= P.overhead)
        if q.any():
            return True
        if P.overhead_mode == "causal":
            return any(up < cl_ <= up * (1.0 + P.overhead) for cl_ in _candidate_lowers(sig))
        return False

    def find(z, start):
        if start is None or start >= n:
            return None, None, None
        return wz.find_wpbr_retest_and_signal(lo_hu, cl_hu, op_hu, scan_start=start, zone_lower=z["zl"],
                                              zone_upper=z["zh"], max_days_after_retest=PROD["max_days"],
                                              n=n, prices_already_half_up=True)

    def run_trade(sig, fill):
        entry = float(op[fill])
        stop = round(P.stop_mult * float(lo[sig]), 2)
        tgt = round(entry * (1.0 + P.target), 2)
        for j in range(fill, n):
            if j > fill:
                if op[j] <= stop:
                    return j, float(op[j]), "GAP_DOWN", entry, stop, tgt
                if op[j] >= tgt:
                    return j, float(op[j]), "GAP_UP", entry, stop, tgt
            if lo[j] <= stop:
                return j, stop, "STOP_LOSS", entry, stop, tgt
            if hi[j] >= tgt:
                return j, tgt, "TARGET", entry, stop, tgt
        return None, float(cl[n - 1]), "OPEN", entry, stop, tgt

    heap: list = []
    for z in zones:
        rt, sig, fill = find(z, z["scan"])
        if fill is not None:
            heapq.heappush(heap, (fill, z["id"], 0, sig, rt))
    trades = []
    flat_from = -1  # first bar on which a new entry is allowed
    while heap:
        fill, zid, k, sig, rt = heapq.heappop(heap)
        z = zones[zid]
        ok = fill >= flat_from and not overhead_blocked(z, sig)
        if ok:
            xb, xp, xt, entry, stop, tgt = run_trade(sig, fill)
            trades.append({"symbol": sym, "opened": pd.Timestamp(r_start[fill]), "entry": entry, "stop": stop,
                           "target": tgt, "closed": pd.Timestamp(r_start[xb]) if xb is not None else pd.NaT,
                           "exit": xp, "exit_type": xt, "gross": (xp / entry - 1.0) * 100.0, "zone_pivot": z["pivot"],
                           "zone_lower": z["zl"], "zone_upper": z["zh"], "purchase": k + 1})
            if xb is None:
                break
            flat_from = xb
            if k == 0 and P.second_chance and xp > entry:
                nxt = xb + 1
                while True:
                    rt2, sig2, fill2 = find(z, nxt)
                    if fill2 is not None:
                        heapq.heappush(heap, (fill2, zid, 1, sig2, rt2))
                        break
                    if rt2 is not None and sig2 is None:
                        nxt = rt2 + PROD["max_days"] + 1
                        continue
                    break
        elif k == 1:
            # a skipped second-chance signal: look for a later retest from the next bar
            nxt = sig + 1
            while True:
                rt2, sig2, fill2 = find(z, nxt)
                if fill2 is not None:
                    heapq.heappush(heap, (fill2, zid, 1, sig2, rt2))
                    break
                if rt2 is not None and sig2 is None:
                    nxt = rt2 + PROD["max_days"] + 1
                    continue
                break
    return trades


def one_symbol(args) -> list[dict]:
    sym, pivot_tf, retest_tf, P = args
    d = load_daily(sym)
    if d is None or len(d) < 30:
        return []
    piv = weekly_from_daily(d) if pivot_tf == "W" else d
    if retest_tf == "D":
        ret = d
    else:
        ret = load_intraday(sym, int(retest_tf))
        if ret is None:
            return []
        # pivots only matter where retest bars exist; keep a lookback for pivot formation
        piv = piv[piv["end"] >= ret["start"].iloc[0] - pd.Timedelta(days=400)]
    try:
        return simulate(sym, piv, ret, P)
    except Exception as e:  # keep the batch going; report
        print(f"[mtf] {sym} failed: {e}", file=sys.stderr)
        return []


def run_many(symbols, pivot_tf, retest_tf, P, workers=8) -> pd.DataFrame:
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(one_symbol, [(s, pivot_tf, retest_tf, P) for s in symbols], chunksize=4):
            out.extend(res)
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- CLI
def _engine_trades(stamp: str) -> pd.DataFrame:
    f = sorted((REPO / "drive" / "honest_bt" / stamp / "pit" / "WPBR").glob("WPBR_Closed_*.csv"))[-1]
    e = pd.read_csv(f, low_memory=False, usecols=["SYMBOL", "DATE_OPENED", "ENTRY_PRICE", "DATE_CLOSED",
                                                  "EXIT_PRICE", "EXIT_TYPE", "PNL_PCT"])
    e["opened"] = pd.to_datetime(e.DATE_OPENED.astype(str).str[:8])
    e["gross"] = e.PNL_PCT.astype(str).str.rstrip("%").astype(float)
    return e.rename(columns={"SYMBOL": "symbol"})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["validate", "run"])
    ap.add_argument("--stamp", default="20261112")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--symbols", default="", help="comma list or @file")
    ap.add_argument("--pivot-tf", default="W", choices=["W", "D"])
    ap.add_argument("--retest-tf", default="D", choices=["D", "60", "30"])
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--placebo", default="")
    ap.add_argument("--overhead-mode", default="engine", choices=["engine", "confirmed", "causal"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    P = Params(s=a.scale, overhead_mode=a.overhead_mode, placebo=a.placebo)

    if a.symbols.startswith("@"):
        syms = [s.strip() for s in Path(a.symbols[1:]).read_text().split() if s.strip()]
    elif a.symbols:
        syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    else:
        syms = sorted(p.stem for p in PIT_DAILY.glob("*.csv") if p.stem != "SPY" and not p.stem.startswith("_"))
    if a.limit:
        syms = syms[: a.limit]

    if a.mode == "validate":
        mine = run_many(syms, "W", "D", P, a.workers)
        eng = _engine_trades(a.stamp)
        eng = eng[eng.symbol.isin(syms)]
        key = lambda df: set(zip(df.symbol, pd.to_datetime(df.opened).dt.normalize()))  # noqa: E731
        km, ke = key(mine), key(eng)
        both = km & ke
        print(f"[validate] {len(syms)} symbols  engine {len(ke)}  mine {len(km)}  matched {len(both)} "
              f"({len(both) / max(1, len(ke)):.1%} of engine)")
        m = mine.assign(day=pd.to_datetime(mine.opened).dt.normalize()).merge(
            eng.assign(day=eng.opened), on=["symbol", "day"], suffixes=("_m", "_e"))
        if len(m):
            same = (m.gross_m.round(2) - m.gross_e.round(2)).abs() <= 0.02
            print(f"[validate] matched trades with same P&L: {same.mean():.1%}; "
                  f"avg gross mine {mine.gross.mean():.2f} engine {eng.gross.mean():.2f}")
        if a.out:
            Path(a.out).mkdir(parents=True, exist_ok=True)
            mine.to_csv(Path(a.out) / "mine.csv", index=False)
            pd.DataFrame(sorted(ke - km), columns=["symbol", "opened"]).to_csv(Path(a.out) / "engine_only.csv", index=False)
            pd.DataFrame(sorted(km - ke), columns=["symbol", "opened"]).to_csv(Path(a.out) / "mine_only.csv", index=False)
        return 0

    df = run_many(syms, a.pivot_tf, a.retest_tf, P, a.workers)
    out = Path(a.out or REPO / "drive" / "honest_bt" / "mtf" / f"{a.pivot_tf}_{a.retest_tf}")
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "trades.csv", index=False)
    print(f"[mtf] {a.pivot_tf}->{a.retest_tf} s={a.scale} placebo={a.placebo or '-'}: {len(df)} trades, "
          f"{df.symbol.nunique() if len(df) else 0} symbols -> {out / 'trades.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
