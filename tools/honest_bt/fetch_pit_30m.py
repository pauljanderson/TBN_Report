#!/usr/bin/env python3
"""Survivor-free 30-minute RTH bars from Alpaca for the multi-timeframe WPBR test.

Symbols: every name that was ever in the honest PIT universe
(drive/honest_bt/<stamp>/membership_pit.csv), delisted ones included.
Bars: 30Min, split-adjusted, SIP feed, regular hours only (09:30-16:00 ET; the 13
half-hour bars of a normal session). Pre/post-market prints are dropped on write.

Output (data/ is gitignored):
  data/pit_30m/{SYM}.parquet   columns: ts (bar start, ET, tz-naive), date, open, high, low, close, volume
  data/pit_30m/_manifest.csv   symbol, bars, first, last

Each symbol is fetched only for its PIT member months (first member month minus 1 month to last
member month plus 6 months, so trades opened late can still exit), with parallel requests held
under Alpaca's free-plan limit (200 requests/min).

Resumable: symbols that already have a parquet are skipped (use --force to refetch).

Run:  python tools/honest_bt/fetch_pit_30m.py --stamp 20261112 [--limit 20]
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "tools"))
from fetch_alpaca_1m import load_keys  # noqa: E402

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
OUT_DIR = REPO / "data" / "pit_30m"
NY = "America/New_York"


class RateLimit:
    """At most `per_min` request starts per rolling minute, shared by all threads."""

    def __init__(self, per_min: int):
        self.gap = 60.0 / per_min
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_t)
            self.next_t = t + self.gap
        if t > now:
            time.sleep(t - now)


LIMIT = RateLimit(190)


def fetch_batch(symbols: list[str], headers: dict, start: str, end: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    token = None
    while True:
        params = {"symbols": ",".join(symbols), "timeframe": "30Min", "start": start, "end": end,
                  "adjustment": "split", "feed": "sip", "limit": 10000, "sort": "asc"}
        if token:
            params["page_token"] = token
        for attempt in range(8):
            LIMIT.wait()
            try:
                r = requests.get(BARS_URL, params=params, headers=headers, timeout=120)
            except requests.RequestException:
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(min(60, 3 * (attempt + 1)))
                continue
            if r.status_code >= 500:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            break
        else:
            raise RuntimeError(f"Alpaca kept failing for batch starting {symbols[0]}")
        j = r.json()
        for sym, bars in (j.get("bars") or {}).items():
            out.setdefault(sym, []).extend(bars)
        token = j.get("next_page_token")
        if not token:
            return out


def to_rth_frame(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    ts = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY).dt.tz_localize(None)
    out = pd.DataFrame({"ts": ts, "open": df["o"], "high": df["h"], "low": df["l"],
                        "close": df["c"], "volume": df["v"]})
    tod = out.ts.dt.hour * 60 + out.ts.dt.minute
    out = out[(tod >= 9 * 60 + 30) & (tod < 16 * 60)]
    out = out.drop_duplicates("ts", keep="last").sort_values("ts", ignore_index=True)
    out.insert(1, "date", out.ts.dt.normalize())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stamp", default="20261112")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None, help="default: now minus 30 minutes")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="fixed random sample of N universe symbols (written to _sample.txt)")
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--symbols", default="", help="comma list instead of the PIT universe")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args(argv)

    end = a.end or (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    windows: dict[str, tuple[str, str]] = {}
    if a.symbols:
        syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    else:
        mem = pd.read_csv(REPO / "drive" / "honest_bt" / a.stamp / "membership_pit.csv")
        mem["m"] = pd.PeriodIndex(mem.month.astype(str), freq="M")
        g = mem.groupby("symbol").m.agg(["min", "max"])
        for sym, r in g.iterrows():
            lo = max(pd.Timestamp(a.start), (r["min"] - 1).to_timestamp())
            hi = min(pd.Timestamp(end).tz_localize(None), (r["max"] + 7).to_timestamp())
            if lo >= hi:  # member only before --start: no bars needed
                windows[sym] = ("", "")
                continue
            windows[sym] = (lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%dT%H:%M:%SZ"))
        syms = sorted(windows)
    if a.sample and not a.symbols:
        import random
        syms = sorted(random.Random(a.seed).sample(syms, min(a.sample, len(syms))))
        (out / "_sample.txt").write_text("\n".join(syms) + "\n")
    if a.limit:
        syms = syms[: a.limit]
    todo = [s for s in syms if a.force or not (out / f"{s}.parquet").exists()]
    key, sec = load_keys()
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    print(f"[30m] {len(syms)} symbols, {len(todo)} to fetch, {a.start}..{end} -> {out}", flush=True)

    def one(sym: str) -> int:
        st, en = windows.get(sym, (a.start, end))
        b = fetch_batch([sym], headers, st, en).get(sym) if st else None
        df = to_rth_frame(b) if b else pd.DataFrame(columns=["ts", "date", "open", "high", "low", "close", "volume"])
        tmp = out / f"{sym}.parquet.tmp"
        df.to_parquet(tmp, index=False)
        tmp.replace(out / f"{sym}.parquet")
        return len(df)

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, s): s for s in todo}
        for f in as_completed(futs):
            f.result()
            done += 1
            if done % 25 == 0 or done == len(todo):
                el = time.time() - t0
                print(f"[30m] {done}/{len(todo)}  {el:.0f}s  eta {el / done * (len(todo) - done) / 60:.0f} min", flush=True)

    rows = []
    for p in sorted(out.glob("*.parquet")):
        d = pd.read_parquet(p, columns=["ts"])
        rows.append({"symbol": p.stem, "bars": len(d),
                     "first": str(d.ts.min()) if len(d) else "", "last": str(d.ts.max()) if len(d) else ""})
    pd.DataFrame(rows).to_csv(out / "_manifest.csv", index=False)
    print(f"[30m] done: {sum(r['bars'] > 0 for r in rows)} symbols with bars", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
