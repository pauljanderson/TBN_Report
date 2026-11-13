#!/usr/bin/env python3
"""Survivor-free daily OHLCV from Alpaca for the honest backtest harness.

Why: data/newdata/data/ is today's ~1,100 survivors projected back to 2010.
Names that went bust, got bought, or were delisted are missing, which
inflates every long-only backtest. Alpaca lists both active and inactive
(delisted) US equities and serves their daily bars from 2016.

What this writes (data/ is gitignored):
  data/pit_daily/{SYM}.csv        same columns as data/newdata/data (engines read it as-is)
  data/pit_daily/_manifest.csv    symbol, status (active/inactive), first, last, bars, ever_eligible
  data/pit_daily/SPY.csv          copied from the canonical warehouse (benchmark)

Only symbols that were ever liquid enough to matter (see pit_universe.py
ELIGIBLE_*) get a CSV, so the engines scan thousands, not 16k.

Run:  python tools/honest_bt/fetch_pit_daily.py            (full fetch, ~20-40 min)
      python tools/honest_bt/fetch_pit_daily.py --limit 300 (smoke test)
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(HERE))
from fetch_alpaca_1m import load_keys  # noqa: E402
from pit_universe import ever_eligible  # noqa: E402

ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"}
SYM_RE = re.compile(r"^[A-Z]{1,5}$")
# Funds/ETFs/derivative listings: the systems trade operating companies.
NOT_COMMON = re.compile(
    r"\b(ETF|ETN|Fund|Index|iShares|SPDR|ProShares|Direxion|Invesco|Vanguard|WisdomTree|"
    r"Warrant|Warrants|Right|Rights|Unit|Units|Preferred|Notes?|Debentures?|Bull|Bear|2X|3X|Leveraged|Inverse)\b",
    re.I,
)
OUT_DIR = REPO / "data" / "pit_daily"
CANON = REPO / "data" / "newdata" / "data"
SMA_PERIODS = (20, 30, 50, 100, 200)


def list_assets(headers: dict) -> pd.DataFrame:
    rows = []
    for status in ("active", "inactive"):
        r = requests.get(ASSETS_URL, params={"status": status, "asset_class": "us_equity"}, headers=headers, timeout=120)
        r.raise_for_status()
        for a in r.json():
            if a.get("exchange") not in EXCHANGES:
                continue
            sym = str(a.get("symbol") or "")
            if not SYM_RE.match(sym):
                continue
            if NOT_COMMON.search(str(a.get("name") or "")):
                continue
            rows.append({"symbol": sym, "status": status, "name": a.get("name", "")})
    df = pd.DataFrame(rows).drop_duplicates("symbol", keep="first")
    return df.sort_values("symbol", ignore_index=True)


def fetch_batch(symbols: list[str], headers: dict, start: str, end: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    token = None
    while True:
        params = {
            "symbols": ",".join(symbols), "timeframe": "1Day", "start": start, "end": end,
            "adjustment": "split", "feed": "sip", "limit": 10000,
        }
        if token:
            params["page_token"] = token
        for attempt in range(6):
            r = requests.get(BARS_URL, params=params, headers=headers, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
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


def to_engine_frame(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["Date"] = pd.to_datetime(df["t"]).dt.tz_convert("America/New_York").dt.date
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].drop_duplicates("Date", keep="last")
    df = df.sort_values("Date").set_index("Date")
    df.insert(4, "Adj Close", df["Close"])  # split-adjusted only; dividends ignored (as canonical engines)
    for p in SMA_PERIODS:  # same rule as pygetallMore: rolling mean, 0 until enough bars
        df[f"SMA{p}"] = df["Close"].rolling(window=p, min_periods=p).mean().fillna(0)
    return df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None, help="default: now minus 30 minutes")
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--limit", type=int, default=0, help="only the first N symbols (smoke test)")
    ap.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args(argv)

    # Free SIP refuses anything inside the last 15 minutes; a bare date reads as end-of-day.
    end = a.end or (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    key, sec = load_keys()
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}

    assets = list_assets(headers)
    if a.limit:
        assets = assets.head(a.limit)
    print(f"[pit] {len(assets)} symbols ({(assets.status == 'inactive').sum()} inactive) {a.start}..{end}", flush=True)

    manifest = []
    syms = assets.symbol.tolist()
    status = dict(zip(assets.symbol, assets.status))
    t0 = time.time()
    for i in range(0, len(syms), a.batch):
        chunk = syms[i : i + a.batch]
        bars = fetch_batch(chunk, headers, a.start, end)
        for sym in chunk:
            b = bars.get(sym)
            if not b:
                manifest.append({"symbol": sym, "status": status[sym], "first": "", "last": "", "bars": 0, "ever_eligible": False})
                continue
            df = to_engine_frame(b)
            ok = ever_eligible(df)
            if ok:
                df.to_csv(out / f"{sym}.csv", float_format="%.4f")
            manifest.append({"symbol": sym, "status": status[sym], "first": str(df.index[0]), "last": str(df.index[-1]),
                             "bars": len(df), "ever_eligible": bool(ok)})
        done = min(i + a.batch, len(syms))
        print(f"[pit] {done}/{len(syms)}  eligible so far {sum(m['ever_eligible'] for m in manifest)}  {time.time() - t0:.0f}s", flush=True)

    pd.DataFrame(manifest).to_csv(out / "_manifest.csv", index=False)
    if (CANON / "SPY.csv").exists():
        shutil.copy2(CANON / "SPY.csv", out / "SPY.csv")
    m = pd.DataFrame(manifest)
    print(f"[pit] done: {m.ever_eligible.sum()} CSVs written ({(m.ever_eligible & (m.status == 'inactive')).sum()} delisted) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
