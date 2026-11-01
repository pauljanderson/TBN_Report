#!/usr/bin/env python3
"""Live watch for the clean-break filter behind the 1%–4% stop grid.

Same buy as hv15m_cleanbreak_stop_grid_20260927:

- Zone: highest-volume 15-minute candle before 15:45, remembered 20 sessions.
  The zone stays a 15-minute zone. It is not re-elected from 10-minute volume.
- Clean break: the first later 10-minute bar that sits entirely above the
  highest still-active zone, when the prior 10-minute close was not already
  above it.
- Filter: zone age 4 to 8 sessions, trigger from 09:30 through 11:00 Eastern,
  and the close at least 20% under the prior 252-trading-day high.
- Stops drawn once the next 10-minute open is known: 1%, 2%, 3%, and 4%
  under that open. A low at or below the stop fills at exactly that loss.

Each run refreshes 1-minute bars for names that can still trigger and writes
1-minute charts into the page. The printed price, the distance to the zone
high, and the percent under the prior 252-day high always come from the
latest 1-minute print. A phone notification is sent only when a new signal
bar closes. The batch file posts that alert; this script writes the message
when it is started with --no-notify.

Research watch. Not gold. Not DailyRun.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))

import hv15m_clean_break_n20_signal_ledger_20260927 as led  # noqa: E402
import hv15m_day_zone_forward_20260925 as base  # noqa: E402
from intraday_1m import upsert_symbol_1m  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_stop_grid_20260927"
ONE_MIN = ROOT / "data" / "intraday" / "1m"
CACHE = STAMP / "live_15m.parquet"
CHARTS = STAMP / "live_charts"
FIRED = STAMP / "live_fired.json"
ALERT = STAMP / "live_buy_alert.txt"
PAGE = STAMP / "live.html"
CSV_PATH = STAMP / "live_watch.csv"
ET = "America/New_York"

N_CARRY = 20
AGES = {4, 5, 6, 7, 8}
SIGNAL_MINUTES = 10
SIGNAL_MIN_PRINTS = 7
# A 10-minute bar can be a buy with 7 one-minute prints. Thin means fewer than 9.
SIGNAL_THIN_PRINTS = 9
MORNING = {
    "09:30", "09:40", "09:50",
    "10:00", "10:10", "10:20", "10:30", "10:40", "10:50",
    "11:00",
}
PCT_FLOOR = 0.20
STOPS = (0.01, 0.02, 0.03, 0.04)
CHART_BAND = 0.015
FETCH_BAND = 0.08
LOOKBACK_DAYS = 5
# Each slot is when a 10-minute signal bar has finished. 09:40 is the 09:30
# bar. 11:10 is the 11:00 bar. Weekdays only. Not the old 15-minute clocks.
SLOTS = (
    (9, 40),
    (9, 50),
    (10, 0),
    (10, 10),
    (10, 20),
    (10, 30),
    (10, 40),
    (10, 50),
    (11, 0),
    (11, 10),
)

ASK = (
    "It does not seem to update price and distance to trigger / under the "
    "252-day high each time the file is updated. On my desktop the charts load "
    "fine, but on my iPad and phone they do not. Can you add to the batch file "
    "an ntfy if any symbol ever is triggered to buy?\n\n"
    "let's change the rule to the 10m candle. no need to keep running this on "
    "loop for every 15 minutes until 11AM since it is unlikely the previous "
    "candle will close below the trigger and the next will open above the "
    "trigger and not go lower, correct?\n\n"
    "ok. so let's not rule out rerunning this every 10 minutes to see if any "
    "trades get activated before 11:10AM"
)


def now_et() -> pd.Timestamp:
    return pd.Timestamp.now(tz=ET)


def next_weekday(d: date) -> date:
    out = d
    while out.weekday() >= 5:
        out += timedelta(days=1)
    return out


def watch_day(now: pd.Timestamp) -> tuple[date, str]:
    """Session this run is aiming at, and whether the cash session is open."""
    d = now.date()
    minutes = int(now.hour) * 60 + int(now.minute)
    if d.weekday() >= 5:
        return next_weekday(d + timedelta(days=1)), "preview"
    if minutes < 9 * 60 + 30:
        return d, "preopen"
    if minutes >= 16 * 60:
        return d, "after"
    return d, "rth"


def bkt_label(bucket: int, minutes: int = 15) -> str:
    mins = 9 * 60 + 30 + int(bucket) * int(minutes)
    return f"{mins // 60:02d}:{mins % 60:02d}"


def signal_b15(bucket10: int) -> int:
    """15-minute bucket that contains the start of a 10-minute bar."""
    return (int(bucket10) * SIGNAL_MINUTES) // 15


def bar_end(day: date, bucket: int, minutes: int = SIGNAL_MINUTES) -> pd.Timestamp:
    start = 9 * 60 + 30 + int(bucket) * int(minutes)
    end = start + int(minutes)
    return pd.Timestamp(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=end // 60,
        minute=end % 60,
        tz=ET,
    )


def px(x: float) -> str:
    if not np.isfinite(x):
        return "—"
    ax = abs(float(x))
    if ax >= 1000:
        return f"{x:,.2f}"
    if ax >= 1:
        return f"{x:.2f}"
    return f"{x:.4f}"


def pct_txt(x: float) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):.2f}%"


def pct_words(x: float) -> str:
    """Percent text without a percent sign, safe to pass through a batch file."""
    if x is None or not np.isfinite(x):
        return "unknown"
    return f"{100.0 * float(x):.2f} percent"


def live_1m_quote(symbol: str, watch: date) -> tuple[float, pd.Timestamp] | None:
    """Latest regular-hours 1-minute close. Prefer today's session."""
    src = ONE_MIN / f"{symbol}.parquet"
    if not src.is_file():
        return None
    try:
        m = pd.read_parquet(src, columns=["ts", "close"])
    except Exception as exc:  # noqa: BLE001 — a locked file should not drop the name
        print(f"  {symbol} live quote skipped: {exc}", flush=True)
        return None
    if m.empty or "ts" not in m.columns:
        return None
    ts = pd.to_datetime(m["ts"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(ET)
    else:
        ts = ts.dt.tz_convert(ET)
    close = pd.to_numeric(m["close"], errors="coerce")
    mins = ts.dt.hour * 60 + ts.dt.minute
    keep = close.notna() & (mins >= 570) & (mins < 960)
    if not bool(keep.any()):
        return None
    ts = ts[keep]
    close = close[keep]
    today = ts.dt.date == watch
    if bool(today.any()):
        ts = ts[today]
        close = close[today]
    i = int(ts.argmax())
    px_ = float(close.iloc[i])
    if not np.isfinite(px_):
        return None
    return px_, ts.iloc[i]


def _apply_live_quote(row: dict, watch: date) -> dict | None:
    """Replace the displayed price, distance, and 252-day percent from the latest print.

    A buy still uses the finished 10-minute bar. Names that have not signaled
    and are no longer 20% under the prior 252-day high on the live print drop off.
    """
    quote = live_1m_quote(str(row["symbol"]), watch)
    if quote is None:
        row["print_day"] = row["quote_day"]
        row["print_clock"] = row["clock"]
        return row
    px_, ts = quote
    zh = float(row["zone_hi"])
    row["last"] = float(px_)
    row["distance"] = (zh - float(px_)) / zh if zh > 0 else float("nan")
    row["pct_below"] = led._pct_below(float(row["high_252"]), float(px_))
    row["print_day"] = ts.date().isoformat()
    row["print_clock"] = ts.strftime("%H:%M")
    if row["tier"] != "signal":
        if not np.isfinite(row["pct_below"]) or float(row["pct_below"]) < PCT_FLOOR:
            return None
    return row


def build_bars(files: list[Path] | None, minutes: int, min_prints: int) -> pd.DataFrame:
    if files is not None:
        existing = [p for p in files if p.is_file()]
        if not existing:
            return pd.DataFrame()
        src = "read_parquet([" + ", ".join("'" + p.as_posix() + "'" for p in existing) + "])"
    else:
        glob = (ONE_MIN / "*.parquet").as_posix()
        src = f"read_parquet('{glob}')"
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            WITH src AS (
                SELECT
                    upper(symbol) AS symbol,
                    timezone('America/New_York', ts) AS ts_et,
                    open, high, low, close, volume
                FROM {src}
                WHERE volume IS NOT NULL AND volume > 0
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
            ),
            f AS (
                SELECT
                    symbol,
                    CAST(ts_et AS DATE) AS day,
                    (hour(ts_et) * 60 + minute(ts_et)) AS mins,
                    ts_et, open, high, low, close, volume
                FROM src
            )
            SELECT
                symbol,
                day,
                ((mins - 570) // {int(minutes)})::INTEGER AS bucket,
                arg_min(open, ts_et) AS open,
                max(high) AS high,
                min(low) AS low,
                arg_max(close, ts_et) AS close,
                sum(volume) AS volume,
                count(*)::INTEGER AS n_min
            FROM f
            WHERE mins >= 570 AND mins < 960
            GROUP BY symbol, day, bucket
            HAVING count(*) >= {int(min_prints)}
               AND max(high) > min(low)
               AND sum(volume) > 0
            ORDER BY symbol, day, bucket
            """
        ).fetchdf()
    finally:
        con.close()


def build_15m(files: list[Path] | None) -> pd.DataFrame:
    """15-minute bars used only to elect the high-volume zone."""
    return build_bars(files, 15, 10)


def build_10m(files: list[Path] | None) -> pd.DataFrame:
    """10-minute signal bars. A bar needs at least 7 one-minute prints."""
    return build_bars(files, SIGNAL_MINUTES, SIGNAL_MIN_PRINTS)


def cache_behind_1m(bars: pd.DataFrame) -> bool:
    """True when the saved 15-minute book is older than the 1-minute store.

    The morning loop only refreshes names already on the list. If the age
    filter keeps nobody, that refresh never runs and the book stays stuck.
    SPY is the sentinel: a full rebuild is due when its 15-minute day lags
    the 1-minute file.
    """
    if bars is None or len(bars) == 0:
        return True
    spy = ONE_MIN / "SPY.parquet"
    if not spy.is_file():
        return False
    live = pd.read_parquet(spy, columns=["ts"])
    if live.empty or "ts" not in live.columns:
        return False
    ts = pd.to_datetime(live["ts"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(ET)
    else:
        ts = ts.dt.tz_convert(ET)
    mins = ts.dt.hour * 60 + ts.dt.minute
    ts = ts[(mins >= 570) & (mins < 960)]
    if ts.empty:
        return False
    live_day = ts.max().date()
    sub = bars[bars["symbol"].astype(str) == "SPY"]
    if sub.empty:
        return True
    cached_day = pd.to_datetime(sub["day"]).max().date()
    return cached_day < live_day


def load_bars(refresh: list[str] | None) -> pd.DataFrame:
    """Full liquid 15-minute book, with an incremental refresh for some symbols."""
    STAMP.mkdir(parents=True, exist_ok=True)
    if refresh:
        files = [ONE_MIN / f"{s}.parquet" for s in refresh]
        fresh = build_15m(files)
        if CACHE.is_file():
            old = pd.read_parquet(CACHE)
            if len(fresh):
                old = old[~old["symbol"].isin(set(fresh["symbol"]))]
                df = pd.concat([old, fresh], ignore_index=True)
            else:
                df = old
        else:
            df = fresh
        if len(df):
            df.to_parquet(CACHE, index=False)
        return df

    print("resampling 1-minute bars to 15-minute regular-hours bars...", flush=True)
    raw = build_15m(None)
    print(f"15m rows {len(raw):,} symbols {raw['symbol'].nunique():,}", flush=True)
    liquid, info = base.select_universe(raw)
    liquid.to_parquet(CACHE, index=False)
    (STAMP / "live_universe.json").write_text(json.dumps(info, default=str), encoding="utf-8")
    return liquid


def _elect(days, bucket, low, high, vol, sess, good_days):
    s_count = len(good_days)
    z_lo = np.full(s_count, np.nan)
    z_hi = np.full(s_count, np.nan)
    z_bkt = np.full(s_count, -1, dtype=np.int16)
    for s, d in enumerate(good_days):
        idx = np.flatnonzero((days == d) & (sess == s))
        idx = idx[bucket[idx] < 25]
        if len(idx) == 0:
            continue
        vols = vol[idx]
        bk = bucket[idx]
        best = idx[int(np.lexsort((bk, -vols))[0])]
        lo = float(low[best])
        hi = float(high[best])
        mid = 0.5 * (lo + hi)
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo or mid <= 0:
            continue
        if (hi - lo) / mid < 0.0005:
            continue
        z_lo[s] = lo
        z_hi[s] = hi
        z_bkt[s] = int(bucket[best])
    valid = np.isfinite(z_lo) & np.isfinite(z_hi) & (z_bkt >= 0)
    return z_lo, z_hi, z_bkt, valid


def _highest(z_hi, valid, z_bkt, done, s: int, b: int) -> int:
    n = len(valid)
    s0 = s - N_CARRY
    if s0 < 0:
        s0 = 0
    hi_z = -1
    best = -1e300
    for zs in range(s0, s + 1):
        if zs < 0 or zs >= n or not valid[zs] or done[zs]:
            continue
        if (s - zs) > N_CARRY:
            continue
        if zs == s and b <= int(z_bkt[zs]):
            continue
        zh = float(z_hi[zs])
        if zh > best or (zh == best and zs > hi_z):
            best = zh
            hi_z = zs
    return hi_z


def _pct252(pack: dict | None, on_day: date, price: float) -> tuple[float, float, str]:
    if not pack or not np.isfinite(price):
        return float("nan"), float("nan"), ""
    i = led._prior_index(pack["day"], on_day)
    hi, hi_date, n_used = led._window_high(pack["day"], pack["high"], i + 1, led.YEAR_BARS, None)
    if n_used < led.MIN_YEAR_BARS:
        return float("nan"), float("nan"), ""
    return led._pct_below(hi, price), hi, hi_date


def _session_index(days, good_days, watch: date):
    day_to_s = {d: i for i, d in enumerate(good_days)}
    virtual = sum(1 for d in good_days if d < watch)
    sess = np.empty(len(days), dtype=np.int16)
    for i, d in enumerate(days):
        if d in day_to_s:
            sess[i] = day_to_s[d]
        elif d == watch:
            sess[i] = virtual
        else:
            sess[i] = -1
    return sess


def classify_symbol(
    sym: str,
    g15: pd.DataFrame,
    g10: pd.DataFrame,
    watch: date,
    now: pd.Timestamp,
    pack,
) -> dict | None:
    """Zone from 15-minute bars. Signal from 10-minute bars."""
    g15 = g15.sort_values(["day", "bucket"])
    days15 = pd.to_datetime(g15["day"]).dt.date.to_numpy()
    bucket15 = g15["bucket"].to_numpy(dtype=np.int16)
    low15 = g15["low"].to_numpy(dtype=np.float64)
    high15 = g15["high"].to_numpy(dtype=np.float64)
    vol15 = g15["volume"].to_numpy(dtype=np.float64)
    if len(days15) < 30 or g10 is None or len(g10) < 2:
        return None
    uniq = list(pd.unique(days15))
    counts: dict = {}
    for d in days15:
        counts[d] = counts.get(d, 0) + 1
    good_days = [d for d in uniq if counts[d] >= base.MIN_BARS_SESSION]
    if len(good_days) < 8:
        return None
    sess15 = _session_index(days15, good_days, watch)
    z_lo, z_hi, z_bkt, valid = _elect(days15, bucket15, low15, high15, vol15, sess15, good_days)
    if not np.any(valid):
        return None

    g = g10.sort_values(["day", "bucket"])
    days = pd.to_datetime(g["day"]).dt.date.to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    opens = g["open"].to_numpy(dtype=np.float64)
    low = g["low"].to_numpy(dtype=np.float64)
    close = g["close"].to_numpy(dtype=np.float64)
    n_min = g["n_min"].to_numpy(dtype=np.int16)
    n = len(close)
    sess = _session_index(days, good_days, watch)

    order = [i for i in range(n) if sess[i] >= 0]
    if len(order) < 2:
        return None
    closed_idx = []
    forming_idx = None
    for i in order:
        end = bar_end(days[i], int(bucket[i]), SIGNAL_MINUTES)
        if end <= now and int(n_min[i]) >= SIGNAL_MIN_PRINTS:
            closed_idx.append(i)
        elif days[i] == watch:
            forming_idx = i

    done = np.zeros(len(good_days), dtype=np.int8)
    signals = []
    for k, i in enumerate(closed_idx):
        if k == 0:
            continue
        prev_i = closed_idx[k - 1]
        s = int(sess[i])
        b = int(bucket[i])
        hi_z = _highest(z_hi, valid, z_bkt, done, s, signal_b15(b))
        if hi_z < 0:
            continue
        zh = float(z_hi[hi_z])
        if low[i] > zh and close[i] > zh and close[prev_i] <= zh:
            done[hi_z] = 1
            age = s - hi_z
            clock = bkt_label(b, SIGNAL_MINUTES)
            nxt = closed_idx[k + 1] if k + 1 < len(closed_idx) else forming_idx
            entry = float(opens[nxt]) if nxt is not None else float("nan")
            signals.append(
                {
                    "day": days[i],
                    "clock": clock,
                    "bucket": b,
                    "close": float(close[i]),
                    "low": float(low[i]),
                    "zone": hi_z,
                    "age": int(age),
                    "n_min": int(n_min[i]),
                    "entry": entry,
                }
            )

    today_signals = [
        s
        for s in signals
        if s["day"] == watch and s["age"] in AGES and s["clock"] in MORNING
    ]
    quote_i = forming_idx if forming_idx is not None else (closed_idx[-1] if closed_idx else None)
    if quote_i is None:
        return None
    quote_s = int(sess[quote_i])
    quote_b = int(bucket[quote_i])
    hi_z = _highest(z_hi, valid, z_bkt, done, quote_s, signal_b15(quote_b))
    last_px = float(close[quote_i])
    pct, hi252, hi_date = _pct252(pack, watch, last_px)

    chosen = None
    if today_signals:
        chosen = today_signals[-1]
        pct_sig, hi252, hi_date = _pct252(pack, watch, float(chosen["close"]))
        if not np.isfinite(pct_sig) or pct_sig < PCT_FLOOR:
            chosen = None
        else:
            pct = pct_sig

    if chosen is None:
        if hi_z < 0:
            return None
        age = quote_s - hi_z
        if age not in AGES:
            return None
        if not np.isfinite(pct) or pct < PCT_FLOOR:
            return None
        zh = float(z_hi[hi_z])
        if zh <= 0:
            return None
        distance = (zh - last_px) / zh
        zone_i = hi_z
        if distance <= CHART_BAND:
            tier = "near"
        elif distance <= FETCH_BAND:
            tier = "fetch"
        else:
            tier = "arm"
        entry = float("nan")
        clock = bkt_label(quote_b, SIGNAL_MINUTES)
        quote_day = days[quote_i].isoformat()
        sig_close = float("nan")
        thin = False
    else:
        zone_i = int(chosen["zone"])
        zh = float(z_hi[zone_i])
        distance = (zh - float(chosen["close"])) / zh if zh > 0 else float("nan")
        tier = "signal"
        age = int(chosen["age"])
        entry = float(chosen["entry"])
        clock = chosen["clock"]
        quote_day = chosen["day"].isoformat()
        sig_close = float(chosen["close"])
        thin = int(chosen["n_min"]) < SIGNAL_THIN_PRINTS
        last_px = float(chosen["close"])

    born = good_days[zone_i]
    row = {
        "symbol": sym,
        "tier": tier,
        "last": last_px,
        "zone_hi": zh,
        "zone_lo": float(z_lo[zone_i]),
        "zone_day": born.isoformat() if hasattr(born, "isoformat") else str(born),
        "zone_clock": bkt_label(int(z_bkt[zone_i])),
        "age": int(age),
        "distance": float(distance),
        "pct_below": float(pct),
        "high_252": float(hi252) if np.isfinite(hi252) else float("nan"),
        "high_252_date": hi_date,
        "clock": clock,
        "quote_day": quote_day,
        "entry": float(entry),
        "signal_close": float(sig_close) if tier == "signal" else float("nan"),
        "thin": bool(thin) if tier == "signal" else False,
        "forming": forming_idx is not None and tier != "signal",
    }
    return _apply_live_quote(row, watch)


def scan(
    bars15: pd.DataFrame,
    bars10: pd.DataFrame,
    watch: date,
    now: pd.Timestamp,
    symbols: list[str] | None,
) -> list[dict]:
    if symbols:
        keep = set(symbols)
        bars15 = bars15[bars15["symbol"].isin(keep)]
        bars10 = bars10[bars10["symbol"].isin(keep)] if len(bars10) else bars10
    names = sorted(bars15["symbol"].astype(str).unique())
    print(f"daily 252-day highs for {len(names)} symbols...", flush=True)
    daily = led.load_daily(names)
    g15 = {sym: g for sym, g in bars15.groupby(bars15["symbol"].astype(str), sort=False)}
    g10 = {sym: g for sym, g in bars10.groupby(bars10["symbol"].astype(str), sort=False)} if len(bars10) else {}
    rows = []
    for i, sym in enumerate(names, 1):
        ten = g10.get(sym)
        if ten is None:
            continue
        row = classify_symbol(sym, g15[sym], ten, watch, now, daily.get(sym))
        if row is not None:
            rows.append(row)
        if i % 200 == 0 or i == len(names):
            print(f"  classified {i}/{len(names)} kept {len(rows)}", flush=True)
    return rows


def refresh_1m(symbols: list[str], sleep_s: float) -> None:
    if not symbols:
        print("no symbols to refresh", flush=True)
        return
    print(f"fetching 1-minute bars for {len(symbols)} symbols...", flush=True)
    for i, sym in enumerate(symbols, 1):
        try:
            upsert_symbol_1m(
                sym,
                out_dir=ONE_MIN,
                lookback_days=LOOKBACK_DAYS,
                sleep_s=sleep_s,
                retries=2,
            )
        except Exception as exc:  # noqa: BLE001 — one bad ticker should not stop the watch
            print(f"  {sym} fetch failed: {exc}", flush=True)
        if i % 25 == 0 or i == len(symbols):
            print(f"  fetched {i}/{len(symbols)}", flush=True)


def _load_fired() -> set[str]:
    if not FIRED.is_file():
        return set()
    try:
        raw = json.loads(FIRED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(raw, list):
        return set(str(x) for x in raw)
    return set()


def _save_fired(keys: set[str]) -> None:
    FIRED.write_text(json.dumps(sorted(keys)), encoding="utf-8")


def signal_key(row: dict, watch: date) -> str:
    return f"{row['symbol']}|{watch.isoformat()}|{row['clock']}"


def plot_1m(row: dict, watch: date, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    src = ONE_MIN / f"{row['symbol']}.parquet"
    if not src.is_file():
        return
    m = pd.read_parquet(src)
    if m.empty or "ts" not in m.columns:
        return
    ts = pd.to_datetime(m["ts"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(ET)
    else:
        ts = ts.dt.tz_convert(ET)
    m = m.copy()
    m["ts"] = ts
    m["day"] = ts.dt.date
    mins = ts.dt.hour * 60 + ts.dt.minute
    m = m[(mins >= 570) & (mins < 960)]
    days = sorted(m["day"].unique())
    show = [d for d in days if d <= watch][-2:]
    m = m[m["day"].isin(show)].sort_values("ts")
    if m.empty:
        return
    o = m["open"].to_numpy(dtype=float)
    h = m["high"].to_numpy(dtype=float)
    low = m["low"].to_numpy(dtype=float)
    c = m["close"].to_numpy(dtype=float)
    days_arr = m["day"].to_numpy()
    n = len(c)
    x = np.arange(n)
    fig, ax = plt.subplots(figsize=(12, 5.2), dpi=100)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    for i in range(n):
        up = c[i] >= o[i]
        color = "#1b7f4e" if up else "#c0392b"
        ax.plot([x[i], x[i]], [low[i], h[i]], color=color, linewidth=0.5, solid_capstyle="butt")
        body_lo = min(o[i], c[i])
        body_hi = max(o[i], c[i])
        if body_hi <= body_lo:
            body_hi = body_lo + max(abs(c[i]) * 1e-4, 1e-4)
        ax.add_patch(
            Rectangle((x[i] - 0.35, body_lo), 0.7, body_hi - body_lo, facecolor=color, edgecolor=color, linewidth=0.3)
        )
    day_starts = [0]
    for i in range(1, n):
        if days_arr[i] != days_arr[i - 1]:
            day_starts.append(i)
            ax.axvline(i - 0.5, color="#d0d5dd", linewidth=0.6)
    tick_idx = list(range(0, n, 30))
    ax.set_xticks(tick_idx)
    labels = []
    for i in tick_idx:
        t = m["ts"].iloc[i]
        labels.append(t.strftime("%m-%d %H:%M"))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    zh = float(row["zone_hi"])
    ax.axhline(zh, color="#1a5276", linewidth=1.3, label="trigger, zone high")
    ax.axhline(float(row["zone_lo"]), color="#94a3b8", linewidth=0.8, linestyle=":")
    entry = float(row["entry"])
    if np.isfinite(entry):
        ax.axhline(entry, color="#6c3483", linewidth=1.0, linestyle="--")
        colors = ("#b91c1c", "#c2410c", "#a16207", "#3f6212")
        for stop, color in zip(STOPS, colors):
            ax.axhline(entry * (1.0 - stop), color=color, linewidth=0.9, linestyle="--", alpha=0.9)
    highs = [float(np.nanmax(h)), zh]
    lows = [float(np.nanmin(low)), float(row["zone_lo"])]
    if np.isfinite(entry):
        highs.append(entry)
        lows.append(entry * 0.96)
    pad = (max(highs) - min(lows)) * 0.08
    if pad <= 0:
        pad = 0.05
    ax.set_ylim(min(lows) - pad, max(highs) + pad)
    ax.set_xlim(-1, n)
    title = f"{row['symbol']}  1-minute   trigger {px(zh)}   zone age {row['age']}"
    if row["tier"] == "signal":
        title += f"   SIGNAL {row['clock']}"
    else:
        title += f"   {pct_txt(row['distance'])} under the trigger"
    ax.set_title(title, loc="left", fontsize=12)
    note = "Blue line is the zone high the 10-minute bar has to clear. Gray dotted line is the zone low."
    if np.isfinite(entry):
        note += " Purple dashed line is the buy, the next 10-minute open. The other dashed lines are 1%, 2%, 3%, and 4% under that buy."
    fig.text(0.01, 0.01, note, fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


SORT_JS = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+pp]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      var aMiss = typeof av === "number" && !Number.isFinite(av);
      var bMiss = typeof bv === "number" && !Number.isFinite(bv);
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      if (typeof av === "string" || typeof bv === "string") return dir * String(av).localeCompare(String(bv));
      return dir * (av - bv);
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var headers = table.querySelectorAll("th.sortable-th");
    headers.forEach(function (th, col) {
      function activate(ev) {
        if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.type === "keydown") ev.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        headers.forEach(function (h) { h.classList.remove("sort-asc", "sort-desc"); h.setAttribute("aria-sort", "none"); });
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, type, dir);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", activate);
    });
  });
})();
</script>
"""


def _chart_img(symbol: str, path: Path) -> str:
    """Inline the chart so a phone can show it from one local file."""
    safe = html.escape(symbol)
    if not path.is_file() or path.stat().st_size < 32:
        return f"<p id='chart-{safe}'>Chart was not written for {safe}.</p>"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    alt = html.escape(f"{symbol} 1-minute chart")
    return (
        f"<img class='chart' id='chart-{safe}' alt='{alt}' "
        f"src='data:image/png;base64,{encoded}'/>"
    )


def write_page(rows: list[dict], watch: date, mode: str, now: pd.Timestamp, fetched: int) -> list[dict]:
    show = list(rows)
    show.sort(key=lambda r: (0 if r["tier"] == "signal" else 1, r["distance"], r["symbol"]))
    CHARTS.mkdir(parents=True, exist_ok=True)
    keep = set()
    for r in show:
        dest = CHARTS / f"{r['symbol']}.png"
        plot_1m(r, watch, dest)
        keep.add(dest.name)
        print(f"chart {r['symbol']} ({r['tier']})", flush=True)
    for old in CHARTS.glob("*.png"):
        if old.name not in keep:
            old.unlink()

    body = []
    charts = []
    for r in show:
        if r["tier"] == "signal" and r["thin"]:
            status = "Signal, thin bar"
        elif r["tier"] == "signal":
            status = "Signal"
        elif r["distance"] <= CHART_BAND:
            status = "Close to the trigger"
        else:
            status = "May trigger"
        entry = px(r["entry"]) if r["tier"] == "signal" else "—"
        printed = f"{r.get('print_day') or r['quote_day']} {r.get('print_clock') or r['clock']}"
        body.append(
            "<tr>"
            f"<td><a href='#chart-{html.escape(r['symbol'])}'>{html.escape(r['symbol'])}</a></td>"
            f"<td>{html.escape(status)}</td>"
            f"<td>{html.escape(printed)}</td>"
            f"<td>{px(r['last'])}</td>"
            f"<td>{px(r['zone_hi'])}</td>"
            f"<td>{pct_txt(r['distance'])}</td>"
            f"<td>{r['age']}</td>"
            f"<td>{html.escape(r['zone_day'])} {html.escape(r['zone_clock'])}</td>"
            f"<td>{pct_txt(r['pct_below'])}</td>"
            f"<td>{entry}</td>"
            f"<td><a href='#chart-{html.escape(r['symbol'])}'>chart</a></td>"
            "</tr>"
        )
        stop_line = ""
        if r["tier"] == "signal" and np.isfinite(r["entry"]):
            bits = ", ".join(f"{int(s * 100)}% at {px(r['entry'] * (1.0 - s))}" for s in STOPS)
            stop_line = f" Buy is the next 10-minute open, {px(r['entry'])}. Stops: {bits}."
        elif r["tier"] == "signal":
            stop_line = " The buy is the next 10-minute open, which is not in the tape yet. The stop is 1%, 2%, 3%, or 4% under that open."
        printed = f"{r.get('print_day') or r['quote_day']} {r.get('print_clock') or r['clock']}"
        signal_note = ""
        if r["tier"] == "signal":
            signal_note = (
                f" The buy signal is the {html.escape(r['clock'])} 10-minute bar"
                f" (close {px(r['signal_close'])})."
            )
        charts.append(
            f"<h3 id='{html.escape(r['symbol'])}'>{html.escape(r['symbol'])} — {html.escape(status)}</h3>"
            f"<p>Last price {px(r['last'])} at {html.escape(printed)} Eastern. "
            f"Zone high {px(r['zone_hi'])}. "
            f"Distance to the trigger {pct_txt(r['distance'])}. "
            f"Zone born {html.escape(r['zone_day'])} at {html.escape(r['zone_clock'])}, "
            f"age {r['age']} sessions. "
            f"{pct_txt(r['pct_below'])} under the prior 252-day high"
            f"{(' (' + html.escape(r['high_252_date']) + ')') if r['high_252_date'] else ''}."
            f"{signal_note}{stop_line}</p>"
            f"<div class='chart-wrap'>{_chart_img(r['symbol'], CHARTS / (r['symbol'] + '.png'))}</div>"
        )
    body_html = "\n".join(body) if body else "<tr><td colspan='11'>No name passes the filter on this pass.</td></tr>"
    chart_html = "\n".join(charts) if charts else "<p>No 1-minute charts this pass.</p>"
    n_sig = sum(1 for r in show if r["tier"] == "signal")
    n_near = sum(1 for r in show if r["tier"] != "signal" and r["distance"] <= CHART_BAND)
    n_watch = len(show) - n_sig - n_near
    mode_txt = {
        "rth": "Regular hours are open. A signal counts when the 10-minute bar has finished.",
        "preopen": "Before the 9:30 open. Charts use the last stored prices. Nothing can signal until the 9:30 bar closes at 9:40.",
        "preview": "The cash session is not open (weekend or the next session has not started). This is the list that would be watched at the next open. Nothing is signaled.",
        "after": "After 4:00pm Eastern. A manual run still classifies any finished 10-minute bar from 9:30 through 11:00.",
    }[mode]
    header = "".join(
        [
            _th("Symbol", "text"),
            _th("Status", "text"),
            _th("Last print (Eastern Time)", "text"),
            _th("Price", "num"),
            _th("Zone high", "num"),
            _th("Distance to trigger", "num"),
            _th("Zone age", "num"),
            _th("Zone born", "text"),
            _th("Under 252-day high", "num"),
            _th("Buy (next open)", "num"),
            _th("Chart", "text"),
        ]
    )
    ask_html = "".join(
        "<p>" + html.escape(part.strip()) + "</p>"
        for part in ASK.split("\n\n")
        if part.strip()
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="refresh" content="60"/>
<title>Clean break live watch</title>
<style>
html {{ overflow-x: hidden; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif; margin: 16px auto; max-width: 1200px; padding: 0 12px 48px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
.table-scroll {{ width: 100%; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 12px 0 28px; }}
table.sortable {{ border-collapse: collapse; width: 100%; min-width: 760px; margin: 0; font-size: 0.92rem; }}
th, td {{ border-bottom: 1px solid #e2e8f0; padding: 6px 8px; text-align: right; white-space: nowrap; }}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
caption {{ caption-side: top; text-align: left; font-weight: 600; margin-bottom: 6px; white-space: normal; }}
.chart-wrap {{ width: 100%; max-width: 100%; overflow: hidden; margin: 0 0 28px; }}
img.chart {{ display: block; width: 100%; max-width: 100%; height: auto; border: 1px solid #e2e8f0; background: #fff; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #475569; font-size: 0.92rem; }}
th.sortable-th {{ cursor: pointer; user-select: none; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
@media (max-width: 700px) {{
  body {{ margin: 8px auto; padding: 0 8px 32px; }}
  h1 {{ font-size: 1.2rem; }}
  table.sortable {{ font-size: 0.8rem; }}
}}
</style>
</head>
<body>
<h1>Clean break live watch — names that may trigger</h1>
<p class="note">Research watch only. Not gold. Not wired into the daily batch (DailyRun). As of {html.escape(now.strftime("%Y-%m-%d %H:%M"))} Eastern Time. Watching session {watch.isoformat()}. {n_sig} signal{"s" if n_sig != 1 else ""}, {n_near} within 1.5% of the trigger, {n_watch} further under but still in the filter. Refreshed 1-minute data for {fetched} symbols. Price, distance to the trigger, and percent under the prior 252-day high are the latest 1-minute print. This tab reloads about once a minute. Click a symbol to jump to its chart. Click column headers to sort. On a phone, swipe the table sideways. The chart is below the table and fits the screen.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
{ask_html}
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>This is the live version of the clean-break study that compared 1%, 2%, 3%, and 4% stops. The zone is still the highest-volume 15-minute candle from the last 20 sessions, the one before 15:45. A buy is the first 10-minute bar that closes entirely above that zone, and only when the 10-minute bar before it closed at or under the zone. The zone’s age has to be 4 to 8 sessions, the bar has to start from 9:30 through 11:00 Eastern, and the price has to be at least 20% under the high of the prior 252 trading days. The buy price is the next 10-minute open. The stop choices are 1%, 2%, 3%, and 4% under that open.</p>
<p>The price, the distance to the trigger, and the percent under the prior 252-day high are recalculated from the latest 1-minute print every time this file is rewritten. A buy still waits for a finished 10-minute bar. Each chart is stored inside this page, so a phone or iPad does not have to open a separate picture file.</p>
<p>The morning loop checks every 10 minutes from 9:40 through 11:10 Eastern Time. 9:40 is when the 9:30 10-minute bar has finished. 11:10 is when the 11:00 bar has finished. Each pass pulls fresh 1-minute prices and draws a 1-minute chart for every name that still passes the filter, closest to the trigger first. A later clean break is uncommon, but a few winners have shown up after the open, so the loop stays up through 11:10. A phone alert goes out only when a symbol is actually triggered to buy. The same symbol and the same signal bar are not alerted again on later refreshes.</p>
<p>{html.escape(mode_txt)} A 10-minute bar is used for a buy only after its clock has finished and at least 7 one-minute prints are stored. “Thin bar” means fewer than 9 of those prints made it in.</p>
</div>
<h2>Who is on the list</h2>
<div class="table-scroll">
<table class="sortable">
<caption>Every name that still passes the filter. Signals first, then closest to the zone high. Click column headers to sort.</caption>
<thead><tr>{header}</tr></thead>
<tbody>
{body_html}
</tbody>
</table>
</div>
<h2>1-minute charts</h2>
{chart_html}
<h2>How this run is scheduled</h2>
<ul>
<li>Double-click <code>run_hv15m_cleanbreak_watch.bat</code> for one pass right now.</li>
<li>For the morning, run <code>run_hv15m_cleanbreak_watch.bat loop</code> and leave the window open. On a weekday it waits until 9:40 Eastern Time if you start it earlier, then runs every 10 minutes through 11:10, and exits. The clocks are 9:40, 9:50, 10:00, 10:10, 10:20, 10:30, 10:40, 10:50, 11:00, and 11:10.</li>
<li>Each pass refreshes 1-minute data for every name that still passes the filter, so an overnight gap is included.</li>
<li>If a symbol is triggered to buy, the batch file sends one phone notification titled “Clean break buy”. A later refresh does not send that same buy again.</li>
</ul>
</body>
{SORT_JS}
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    out = pd.DataFrame(show)
    if len(out):
        out.to_csv(CSV_PATH, index=False)
    elif CSV_PATH.is_file():
        CSV_PATH.unlink()
    print(f"wrote {PAGE} signals={n_sig} close={n_near} watching={n_watch}", flush=True)
    return [r for r in show if r["tier"] == "signal"]


def buy_alert_line(rows: list[dict], watch: date) -> str:
    """One line, no percent signs, so a batch file can pass it through safely."""
    bits = []
    shown = rows[:12]
    for r in shown:
        if np.isfinite(r["entry"]):
            buy = f" Buy at {px(r['entry'])}."
        else:
            buy = " The next 10-minute open is not in the tape yet."
        bits.append(
            f"BUY {r['symbol']} {watch.isoformat()} {r['clock']} Eastern."
            f" Last {px(r['last'])}. Trigger {px(r['zone_hi'])}."
            f" Under the prior 252-day high {pct_words(r['pct_below'])}."
            f"{buy} Stops are 1, 2, 3, or 4 percent under that open."
        )
    text = " ; ".join(bits)
    if len(rows) > 12:
        text += f" And {len(rows) - 12} more."
    return text


def _desktop_cue() -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass
    try:
        import os

        os.startfile(PAGE)  # type: ignore[attr-defined]
    except Exception:
        pass


def publish_buy_alert(rows: list[dict], watch: date, notify_phone: bool) -> None:
    """Remember the signal, and optionally post the phone alert from Python.

    The batch file posts the same text when this script is started with
    --no-notify, so a morning loop does not alert twice.
    """
    message = buy_alert_line(rows, watch)
    if not notify_phone and ALERT.is_file():
        old = ALERT.read_text(encoding="utf-8").strip()
        if old and old not in message and message not in old:
            message = old + " ; " + message
    ALERT.write_text(message + "\n", encoding="utf-8")
    _desktop_cue()
    if not notify_phone:
        print(f"buy alert queued for the batch: {message}", flush=True)
        return
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    subprocess.run(
        [sys.executable, str(ntfy), "--path", str(PAGE), "-t", "Clean break buy", "-m", message],
        cwd=str(ROOT),
    )
    try:
        ALERT.unlink()
    except OSError:
        pass


def signal_bars_for(symbols: list[str]) -> pd.DataFrame:
    files = [ONE_MIN / f"{s}.parquet" for s in symbols]
    print(f"resampling {len(files)} symbols to 10-minute signal bars...", flush=True)
    return build_10m(files)


def run_once(fetch: bool, sleep_s: float, only: list[str] | None, notify_phone: bool = True) -> int:
    now = now_et()
    watch, mode = watch_day(now)
    print(f"watch {watch.isoformat()} ({mode}) at {now.strftime('%H:%M')} Eastern", flush=True)
    tape_before = None
    if CACHE.is_file() and not only:
        bars = pd.read_parquet(CACHE)
        if cache_behind_1m(bars):
            print("15-minute cache is behind the 1-minute store; rebuilding...", flush=True)
            bars = load_bars(None)
        tape_before = pd.to_datetime(bars["day"]).max().date() if len(bars) else None
    else:
        bars = load_bars(None)
        if len(bars):
            tape_before = pd.to_datetime(bars["day"]).max().date()
    if bars is None or len(bars) == 0:
        print("no 15-minute bars", flush=True)
        return 1
    names = sorted(bars["symbol"].astype(str).unique())
    if only:
        keep = set(only)
        names = [s for s in names if s in keep]
        bars = bars[bars["symbol"].astype(str).isin(keep)]
    bars10 = signal_bars_for(names)
    rows = scan(bars, bars10, watch, now, only)
    fetch_names = sorted({r["symbol"] for r in rows})
    if tape_before is None or tape_before < watch:
        print(f"session catch-up: {len(fetch_names)} names still in the filter", flush=True)
    else:
        print(f"refreshing {len(fetch_names)} names still in the filter", flush=True)
    if only:
        fetch_names = [s for s in fetch_names if s in set(only)]
    fetched = 0
    if fetch and fetch_names:
        refresh_1m(fetch_names, sleep_s)
        fetched = len(fetch_names)
        bars = load_bars(fetch_names)
        fresh10 = signal_bars_for(fetch_names)
        if len(bars10) and len(fresh10):
            bars10 = bars10[~bars10["symbol"].astype(str).isin(set(fresh10["symbol"].astype(str)))]
            bars10 = pd.concat([bars10, fresh10], ignore_index=True)
        elif len(fresh10):
            bars10 = fresh10
        now = now_et()
        watch, mode = watch_day(now)
        rows = scan(bars, bars10, watch, now, only)
    elif not fetch:
        print("fetch skipped", flush=True)
    signals = write_page(rows, watch, mode, now, fetched)
    fired = _load_fired()
    fresh = []
    for r in signals:
        key = signal_key(r, watch)
        if key not in fired:
            fresh.append(r)
            fired.add(key)
    if fresh:
        _save_fired(fired)
        print("NEW SIGNAL " + ", ".join(r["symbol"] for r in fresh), flush=True)
        publish_buy_alert(fresh, watch, notify_phone)
        return 2
    print("no new signal", flush=True)
    return 0


def _slot_minutes(hm: tuple[int, int]) -> int:
    return hm[0] * 60 + hm[1]


def next_slot_after(now: pd.Timestamp) -> pd.Timestamp | None:
    """Next weekday clock strictly after now, inside the watch list. None if today’s are done."""
    d = now.date()
    if d.weekday() >= 5:
        d = next_weekday(d + timedelta(days=1))
        h, m = SLOTS[0]
        return pd.Timestamp(year=d.year, month=d.month, day=d.day, hour=h, minute=m, tz=ET)
    cur = int(now.hour) * 60 + int(now.minute)
    for h, m in SLOTS:
        if _slot_minutes((h, m)) > cur:
            return pd.Timestamp(year=d.year, month=d.month, day=d.day, hour=h, minute=m, tz=ET)
    return None


def sleep_until(target: pd.Timestamp) -> None:
    while True:
        now = now_et()
        left = (target - now).total_seconds()
        if left <= 0:
            return
        print(f"next run {target.strftime('%H:%M')} Eastern ({int(left // 60)} min)", flush=True)
        time.sleep(min(left, 60))


def sleep_until_next_slot() -> int:
    """Sleep until the next watch slot today. Exit 1 when this morning is done."""
    now = now_et()
    nxt = next_slot_after(now)
    if nxt is None or (nxt - now).total_seconds() > 12 * 3600:
        print("morning window finished", flush=True)
        return 1
    sleep_until(nxt)
    return 0


def loop(fetch: bool, sleep_s: float, only: list[str] | None, notify_phone: bool = True) -> int:
    first = True
    while True:
        now = now_et()
        minutes = int(now.hour) * 60 + int(now.minute)
        start = _slot_minutes(SLOTS[0])
        end = _slot_minutes(SLOTS[-1])
        if now.date().weekday() < 5 and start <= minutes <= end:
            nxt = next_slot_after(now)
            run_once(fetch, sleep_s, only, notify_phone)
            first = False
            if nxt is None:
                print("morning window finished", flush=True)
                return 0
            sleep_until(nxt)
            continue
        nxt = next_slot_after(now)
        if nxt is None:
            if first:
                run_once(fetch, sleep_s, only, notify_phone)
            print("morning window finished", flush=True)
            return 0
        if (nxt - now).total_seconds() > 12 * 3600 and not first:
            print("morning window finished", flush=True)
            return 0
        sleep_until(nxt)


def main() -> int:
    ap = argparse.ArgumentParser(description="Live 1-minute watch for the clean-break stop-grid filter")
    ap.add_argument("--loop", action="store_true", help="On a weekday, wait until 9:40 Eastern if needed, then run every 10 minutes through 11:10")
    ap.add_argument("--sleep-until-next", action="store_true", help="Wait until the next 10-minute slot through 11:10 Eastern, then exit")
    ap.add_argument("--due-now", action="store_true", help="Exit 0 when the current Eastern minute is a watch slot")
    ap.add_argument("--no-notify", action="store_true", help="Write the buy alert for the batch file instead of posting it here")
    ap.add_argument("--no-fetch", action="store_true", help="Use the 1-minute files already on disk")
    ap.add_argument("--sleep", type=float, default=0.35, help="Seconds between Yahoo requests")
    ap.add_argument("--symbols", default="", help="Optional comma-separated symbols, for a small test")
    args = ap.parse_args()
    only = [p.strip().upper() for p in args.symbols.replace(";", ",").split(",") if p.strip()] or None
    phone = not args.no_notify
    try:
        if args.due_now:
            now = now_et()
            cur = int(now.hour) * 60 + int(now.minute)
            due = now.date().weekday() < 5 and any(_slot_minutes(hm) == cur for hm in SLOTS)
            print("slot due" if due else "not a slot minute", flush=True)
            return 0 if due else 1
        if args.sleep_until_next:
            return sleep_until_next_slot()
        if args.loop:
            return loop(not args.no_fetch, float(args.sleep), only, phone)
        return run_once(not args.no_fetch, float(args.sleep), only, phone)
    except KeyboardInterrupt:
        print("Stopped.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
