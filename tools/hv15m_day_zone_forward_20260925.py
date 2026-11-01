#!/usr/bin/env python3
"""15-minute high-volume day zone, carried forward N sessions.

Research scan only. Does not wire DailyRun and does not claim gold.
Not the daily Volume Zone (VZ) engine in rocket_vz.py.

Each Regular Trading Hours session, the single highest-volume 15-minute
candle (resampled from 1-minute) becomes a high-low price zone. The zone
stays usable after that candle closes, through N later trading sessions.
N is a sensitivity grid: 5, 8, 10, 20.

Usage (repo root):
  python tools/hv15m_day_zone_forward_20260925.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_day_zone_forward_20260925"
CACHE = STAMP / "cache_15m.parquet"
SIGNALS_CSV = STAMP / "signals.csv"

ONE_MIN = ROOT / "data" / "intraday" / "1m"
NS = (5, 8, 10, 20)
H26 = 26  # one Regular Trading Hours session of 15-minute bars
H52 = 52
NEAR_PCT = 0.015
FAR_PCT = 0.030
MIN_SESSIONS = 25
MIN_BARS_SESSION = 20
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 1_000_000.0
ZONE_R_MIN = 0.001
ZONE_R_MAX = 0.08
SPRING_BARS = 8

ORIGINAL_REQUEST = (
    "try a new system. draw a zone on the highest volume 15 minute candle of each day. "
    "carry it forward n days (5,8,10,20) analyze for any distinct patterns that arise and "
    "propose potential systems. i.e. buy when a stock goes above the highest zone and then "
    "comes back and touches the zone and then moves higher; buy when a candle bounces off "
    "the lowest zone and moves higher. buy when a candle has many close zones below and "
    "none above or some above but far away, etc."
)

PATTERN_ORDER = (
    "reclaim_highest",
    "bounce_lowest",
    "support_shelf",
    "spring_lowest",
    "clean_break_highest",
    "ceiling_stack",
    "baseline_1030",
)

PATTERN_LABEL = {
    "reclaim_highest": "Reclaim highest zone",
    "bounce_lowest": "Bounce off lowest zone",
    "support_shelf": "Support shelf",
    "spring_lowest": "Spring off lowest zone",
    "clean_break_highest": "Clean break of highest zone",
    "ceiling_stack": "Ceiling stack (long into zones above)",
    "baseline_1030": "Baseline: buy at 10:30 ET",
}

FOLLOWUP_REQUEST = (
    "thanks. are there any patterns or noticeable difference for the zones that were "
    "NOT end of day or beginning of day?"
)

ZONE_RULE_LABEL = {
    "as_asked": "As asked (close bar allowed)",
    "ex_last_bar": "Exclude 15:45 close bar",
    "mid_session": "Mid-session only (not 09:30, not 15:45)",
    "close_only": "Close bar only (15:45)",
    "baseline": "No zone",
}


def _bkt_label(bucket: int) -> str:
    mins = 9 * 60 + 30 + int(bucket) * 15
    return f"{mins // 60:02d}:{mins % 60:02d}"


def build_15m(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if CACHE.exists():
        print(f"reading cache {CACHE}", flush=True)
        return pd.read_parquet(CACHE)
    print("resampling 1-minute to 15-minute RTH bars...", flush=True)
    glob = (ONE_MIN / "*.parquet").as_posix()
    df = con.execute(
        f"""
        WITH src AS (
            SELECT
                upper(symbol) AS symbol,
                timezone('America/New_York', ts) AS ts_et,
                open, high, low, close, volume
            FROM read_parquet('{glob}')
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
            ((mins - 570) // 15)::INTEGER AS bucket,
            arg_min(open, ts_et) AS open,
            max(high) AS high,
            min(low) AS low,
            arg_max(close, ts_et) AS close,
            sum(volume) AS volume,
            count(*)::INTEGER AS n_min
        FROM f
        WHERE mins >= 570 AND mins < 960
        GROUP BY symbol, day, bucket
        HAVING count(*) >= 10
           AND max(high) > min(low)
           AND sum(volume) > 0
        ORDER BY symbol, day, bucket
        """
    ).fetchdf()
    STAMP.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE, index=False)
    print(f"15m rows {len(df):,} symbols {df['symbol'].nunique():,}", flush=True)
    return df


def select_universe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.copy()
    df["dollar"] = df["volume"].astype(float) * df["close"].astype(float)
    sess = (
        df.groupby(["symbol", "day"], sort=False)
        .agg(nbar=("bucket", "size"), dvol=("dollar", "sum"), med_c=("close", "median"))
        .reset_index()
    )
    complete = sess[sess["nbar"] >= MIN_BARS_SESSION]
    by = complete.groupby("symbol", sort=False).agg(
        n_sess=("day", "nunique"),
        med_dvol=("dvol", "median"),
        med_px=("med_c", "median"),
    )
    keep = by[
        (by["n_sess"] >= MIN_SESSIONS)
        & (by["med_dvol"] >= MIN_DOLLAR_VOL)
        & (by["med_px"] >= MIN_PRICE)
    ]
    info = {
        "symbols_with_15m": int(df["symbol"].nunique()),
        "symbols_liquid": int(len(keep)),
        "min_sessions": MIN_SESSIONS,
        "min_bars_session": MIN_BARS_SESSION,
        "min_price": MIN_PRICE,
        "min_median_session_dollar_vol": MIN_DOLLAR_VOL,
        "date_min": str(pd.to_datetime(df["day"]).min().date()),
        "date_max": str(pd.to_datetime(df["day"]).max().date()),
        "sessions_calendar": int(df["day"].nunique()),
    }
    out = df[df["symbol"].isin(keep.index)].copy()
    info["rows_liquid"] = int(len(out))
    print(
        f"universe {info['symbols_liquid']} / {info['symbols_with_15m']} symbols "
        f"{info['date_min']} .. {info['date_max']}",
        flush=True,
    )
    return out, info


def _empty_bucket() -> dict:
    return {
        "fwd26": [],
        "fwd52": [],
        "sym_r": [],
        "sym_win": [],
        "zone_r": [],
        "zone_win": [],
        "days": [],
        "syms": [],
    }


def _push(bucket: dict, rec: dict) -> None:
    bucket["fwd26"].append(rec["fwd26"])
    bucket["fwd52"].append(rec["fwd52"])
    bucket["sym_r"].append(rec["sym_r"])
    bucket["sym_win"].append(rec["sym_win"])
    bucket["days"].append(rec["day"])
    bucket["syms"].append(rec["sym"])
    if rec["zone_r"] is not None:
        bucket["zone_r"].append(rec["zone_r"])
        bucket["zone_win"].append(rec["zone_win"])


def _path(high, low, close, i0: int, entry: float, stop: float | None, horizon: int):
    end = i0 + horizon
    if end > len(close) or not np.isfinite(entry) or entry <= 0:
        return None
    h = high[i0:end]
    l = low[i0:end]
    c_end = float(close[end - 1])
    fwd = c_end / entry - 1.0
    up = entry * 1.01
    dn = entry * 0.99
    sym_r = None
    sym_win = 0
    for k in range(horizon):
        hit_dn = l[k] <= dn
        hit_up = h[k] >= up
        if hit_dn:
            sym_r = -1.0
            sym_win = 0
            break
        if hit_up:
            sym_r = 1.0
            sym_win = 1
            break
    if sym_r is None:
        sym_r = (c_end - entry) / (entry * 0.01)
        sym_win = 0
    zone_r = None
    zone_win = 0
    if stop is not None and np.isfinite(stop) and entry > stop:
        risk = entry - stop
        rp = risk / entry
        if ZONE_R_MIN <= rp <= ZONE_R_MAX:
            tgt = entry + risk
            zone_r = None
            for k in range(horizon):
                hit_dn = l[k] <= stop
                hit_up = h[k] >= tgt
                if hit_dn:
                    zone_r = -1.0
                    zone_win = 0
                    break
                if hit_up:
                    zone_r = 1.0
                    zone_win = 1
                    break
            if zone_r is None:
                zone_r = (c_end - entry) / risk
                zone_win = 0
    return fwd, sym_r, sym_win, zone_r, zone_win


def scan_symbol(
    sym: str,
    g: pd.DataFrame,
    rows_out: list,
    *,
    zone_rule: str = "as_asked",
    emit_baseline: bool = True,
) -> None:
    g = g.sort_values(["day", "bucket"])
    day = g["day"].to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    o = g["open"].to_numpy(dtype=np.float64)
    h = g["high"].to_numpy(dtype=np.float64)
    l = g["low"].to_numpy(dtype=np.float64)
    c = g["close"].to_numpy(dtype=np.float64)
    v = g["volume"].to_numpy(dtype=np.float64)
    n = len(c)
    if n < H26 + 5:
        return

    # Session index on days that have a full 15-minute session.
    uniq_days = pd.unique(day)
    counts = pd.Series(day).value_counts()
    good_days = [d for d in uniq_days if int(counts.get(d, 0)) >= MIN_BARS_SESSION]
    if len(good_days) < MIN_SESSIONS:
        return
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    S = len(good_days)

    z_lo = np.full(S, np.nan)
    z_hi = np.full(S, np.nan)
    z_bkt = np.full(S, -1, dtype=np.int16)
    # Highest-volume bar per complete session.
    for s, d in enumerate(good_days):
        m = (day == d) & (sess == s)
        if not np.any(m):
            continue
        idx = np.flatnonzero(m)
        # The 15:45 bar (bucket 25) often holds the closing auction. as_asked
        # keeps it. ex_last_bar elects the busiest candle that starts before 15:45
        # (a substitute). mid_session and close_only do not substitute: they keep
        # the day's true highest-volume bar only when it falls in the allowed clock.
        if zone_rule == "ex_last_bar":
            idx = idx[bucket[idx] < 25]
            if len(idx) == 0:
                continue
        # Max volume, earliest bucket on a tie.
        vols = v[idx]
        bk = bucket[idx]
        best = idx[int(np.lexsort((bk, -vols))[0])]
        chosen_bkt = int(bucket[best])
        # Edge bars are only 09:30 (bucket 0) and 15:45 (bucket 25).
        # 09:45 and 15:30 stay in the mid-session set.
        if zone_rule == "mid_session" and chosen_bkt in (0, 25):
            continue
        if zone_rule == "close_only" and chosen_bkt != 25:
            continue
        lo = float(l[best])
        hi = float(h[best])
        mid = 0.5 * (lo + hi)
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo or mid <= 0:
            continue
        if (hi - lo) / mid < 0.0005:
            continue
        z_lo[s] = lo
        z_hi[s] = hi
        z_bkt[s] = int(bucket[best])

    valid_zone = np.isfinite(z_lo) & np.isfinite(z_hi) & (z_bkt >= 0)

    def _zmeta(zs: int, j: int, s_now: int) -> dict:
        birth = ""
        age = np.nan
        if 0 <= zs < len(good_days):
            birth = pd.Timestamp(good_days[zs]).date().isoformat()
            age = int(s_now - zs)
        return {
            "zone_age": age,
            "signal_close": float(c[j]),
            "signal_day": pd.Timestamp(day[j]).date().isoformat(),
            "signal_time_et": _bkt_label(int(bucket[j])),
            "zone_date": birth,
        }

    for N in NS:
        bounced = np.zeros(S, dtype=np.int8)
        clean_done = np.zeros(S, dtype=np.int8)
        spring_done = np.zeros(S, dtype=np.int8)
        shelf_done = np.zeros(S, dtype=np.int8)
        ceiling_done = np.zeros(S, dtype=np.int8)
        setup_z = -1
        setup_j = -1
        touched = False
        spring_z = -1
        spring_j = -1

        for j in range(n):
            s = int(sess[j])
            if s < 0:
                setup_z = -1
                spring_z = -1
                continue
            b = int(bucket[j])
            s0 = s - N
            if s0 < 0:
                s0 = 0
            hi_z = -1
            lo_z = -1
            best_hi = -1e300
            best_lo = 1e300
            n_act = 0
            n_below = 0
            n_above_near = 0
            nearest_below = 1e9
            nearest_above = 1e9
            support_z = -1
            support_hi = -1e300
            resist_z = -1
            resist_lo = 1e300
            px = c[j]
            if not np.isfinite(px) or px <= 0:
                continue
            for zs in range(s0, s + 1):
                if not valid_zone[zs]:
                    continue
                if (s - zs) > N:
                    continue
                if zs == s and b <= int(z_bkt[zs]):
                    continue
                n_act += 1
                zl = float(z_lo[zs])
                zh = float(z_hi[zs])
                if zh > best_hi or (zh == best_hi and zs > hi_z):
                    best_hi = zh
                    hi_z = zs
                if zl < best_lo or (zl == best_lo and zs > lo_z):
                    best_lo = zl
                    lo_z = zs
                if zh <= px:
                    dist = (px - zh) / px
                    if dist < nearest_below:
                        nearest_below = dist
                    if dist <= NEAR_PCT:
                        n_below += 1
                        if zh > support_hi:
                            support_hi = zh
                            support_z = zs
                elif zl >= px:
                    dist = (zl - px) / px
                    if dist < nearest_above:
                        nearest_above = dist
                    if dist <= NEAR_PCT:
                        n_above_near += 1
                        if zl < resist_lo:
                            resist_lo = zl
                            resist_z = zs

            if n_act == 0 or hi_z < 0:
                setup_z = -1
                spring_z = -1
                continue

            # --- reclaim of the zone that was highest when price closed above it
            if setup_z >= 0:
                alive = valid_zone[setup_z] and 0 <= (s - setup_z) <= N
                if setup_z == s and b <= int(z_bkt[setup_z]):
                    alive = False
                if (not alive) or hi_z != setup_z:
                    setup_z = -1
                    touched = False
                else:
                    zl = float(z_lo[setup_z])
                    zh = float(z_hi[setup_z])
                    if c[j] < zl:
                        setup_z = -1
                        touched = False
                    else:
                        if l[j] <= zh and h[j] >= zl and j > setup_j:
                            touched = True
                        if touched and c[j] > zh and j > setup_j:
                            _emit(
                                rows_out, sym, "reclaim_highest", N, j, g, o, h, l, c, day,
                                stop=zl, zone_lo=zl, zone_hi=zh, zone_rule=zone_rule,
                                zone_meta=_zmeta(setup_z, j, s),
                            )
                            setup_z = -1
                            touched = False
            if setup_z < 0 and hi_z >= 0 and j > 0:
                zh = float(z_hi[hi_z])
                if c[j] > zh and c[j - 1] <= zh and int(sess[j - 1]) >= 0:
                    setup_z = hi_z
                    setup_j = j
                    touched = False

            # --- clean break: whole bar above the highest zone, first time for that zone
            if hi_z >= 0 and clean_done[hi_z] == 0 and j > 0 and int(sess[j - 1]) >= 0:
                zh = float(z_hi[hi_z])
                zl = float(z_lo[hi_z])
                if l[j] > zh and c[j] > zh and c[j - 1] <= zh:
                    _emit(
                        rows_out, sym, "clean_break_highest", N, j, g, o, h, l, c, day,
                        stop=zl, zone_lo=zl, zone_hi=zh, zone_rule=zone_rule,
                        zone_meta=_zmeta(hi_z, j, s),
                    )
                    clean_done[hi_z] = 1

            # --- bounce off the lowest zone (needs a different, higher zone too)
            if lo_z >= 0 and hi_z != lo_z and n_act >= 2 and bounced[lo_z] == 0:
                zl = float(z_lo[lo_z])
                zh = float(z_hi[lo_z])
                if zl <= l[j] <= zh and c[j] > zh and c[j] > o[j]:
                    _emit(
                        rows_out, sym, "bounce_lowest", N, j, g, o, h, l, c, day,
                        stop=zl, zone_lo=zl, zone_hi=zh, zone_rule=zone_rule,
                        zone_meta=_zmeta(lo_z, j, s),
                    )
                    bounced[lo_z] = 1

            # --- spring: close under the lowest zone, then reclaim within 8 bars
            if spring_z >= 0:
                alive = valid_zone[spring_z] and 0 <= (s - spring_z) <= N and spring_done[spring_z] == 0
                if spring_z == s and b <= int(z_bkt[spring_z]):
                    alive = False
                if not alive or (j - spring_j) > SPRING_BARS:
                    spring_z = -1
                else:
                    zl = float(z_lo[spring_z])
                    zh = float(z_hi[spring_z])
                    if j > spring_j and c[j] > zh and c[j] > o[j]:
                        _emit(
                            rows_out, sym, "spring_lowest", N, j, g, o, h, l, c, day,
                            stop=zl, zone_lo=zl, zone_hi=zh, zone_rule=zone_rule,
                            zone_meta=_zmeta(spring_z, j, s),
                        )
                        spring_done[spring_z] = 1
                        spring_z = -1
                    elif j > spring_j and c[j] > zh:
                        spring_z = -1
            if spring_z < 0 and lo_z >= 0 and spring_done[lo_z] == 0:
                if c[j] < float(z_lo[lo_z]):
                    spring_z = lo_z
                    spring_j = j

            # --- shelf / ceiling, first green bar of the session that qualifies
            if shelf_done[s] == 0 and c[j] > o[j] and n_below >= 3 and n_above_near == 0 and nearest_above >= FAR_PCT and support_z >= 0:
                zl = float(z_lo[support_z])
                zh = float(z_hi[support_z])
                _emit(
                    rows_out, sym, "support_shelf", N, j, g, o, h, l, c, day,
                    stop=zl, zone_lo=zl, zone_hi=zh, zone_rule=zone_rule,
                    zone_meta=_zmeta(support_z, j, s),
                )
                shelf_done[s] = 1
            if ceiling_done[s] == 0 and c[j] > o[j] and n_above_near >= 3 and n_below == 0 and nearest_below >= FAR_PCT:
                stop = float(z_lo[resist_z]) if resist_z >= 0 else None
                zlo = float(z_lo[resist_z]) if resist_z >= 0 else float("nan")
                zhi = float(z_hi[resist_z]) if resist_z >= 0 else float("nan")
                # For a long into overhead zones the nearby zone is above, so a stop
                # at that zone's low is usually above the close and is rejected later
                # (entry > stop). Pass the zone low only when it sits under price.
                if stop is not None and not (stop < px):
                    stop = None
                _emit(
                    rows_out, sym, "ceiling_stack", N, j, g, o, h, l, c, day,
                    stop=stop, zone_lo=zlo, zone_hi=zhi, zone_rule=zone_rule,
                    zone_meta=_zmeta(resist_z, j, s) if resist_z >= 0 else _zmeta(-1, j, s),
                )
                ceiling_done[s] = 1

        # baseline once per N loop would duplicate. Do it only on first N, and only
        # on the as-asked pass so the two zone rules share one drift benchmark.
        if emit_baseline and N == NS[0]:
            seen_day = set()
            for j in range(n):
                if int(bucket[j]) != 4:
                    continue
                d = day[j]
                if d in seen_day or int(sess[j]) < 0:
                    continue
                seen_day.add(d)
                _emit(
                    rows_out, sym, "baseline_1030", 0, j, g, o, h, l, c, day,
                    stop=None, zone_lo=float("nan"), zone_hi=float("nan"),
                    entry_is_signal_bar=True, zone_rule="baseline",
                )


def _emit(rows_out, sym, pattern, N, j, g, o, h, l, c, day, stop, zone_lo, zone_hi, entry_is_signal_bar=False, zone_rule="as_asked", zone_meta=None):
    n = len(c)
    entry_i = j if entry_is_signal_bar else j + 1
    if entry_i < 0 or entry_i + H26 > n:
        return
    entry = float(o[entry_i])
    if not np.isfinite(entry) or entry <= 0:
        return
    # Baseline is already "this bar". Patterns fill the next open, so the
    # 26-bar path starts at the fill bar. Baseline path starts at the 10:30 bar.
    got26 = _path(h, l, c, entry_i, entry, stop, H26)
    if got26 is None:
        return
    fwd26, sym_r, sym_win, zone_r, zone_win = got26
    fwd52 = None
    if entry_i + H52 <= n:
        got52 = _path(h, l, c, entry_i, entry, None, H52)
        if got52 is not None:
            fwd52 = got52[0]
    d = pd.Timestamp(day[entry_i]).date().isoformat()
    rows_out.append(
        {
            "symbol": sym,
            "pattern": pattern,
            "N": int(N),
            "day": d,
            "entry": entry,
            "fwd26": fwd26,
            "fwd52": fwd52 if fwd52 is not None else np.nan,
            "sym_r": sym_r,
            "sym_win": sym_win,
            "zone_r": zone_r if zone_r is not None else np.nan,
            "zone_win": zone_win if zone_r is not None else np.nan,
            "stop": stop if stop is not None else np.nan,
            "zone_lo": zone_lo,
            "zone_hi": zone_hi,
            "zone_rule": zone_rule,
            "zone_age": (zone_meta or {}).get("zone_age", np.nan),
            "signal_close": (zone_meta or {}).get("signal_close", np.nan),
            "signal_day": (zone_meta or {}).get("signal_day", d),
            "signal_time_et": (zone_meta or {}).get("signal_time_et", ""),
            "zone_date": (zone_meta or {}).get("zone_date", ""),
        }
    )


def hv_time_table(df: pd.DataFrame) -> pd.DataFrame:
    """Where in the session the highest-volume 15-minute candle sits."""
    rows = []
    # Only complete sessions in the liquid frame (caller already filtered symbols).
    for (sym, day), g in df.groupby(["symbol", "day"], sort=False):
        if len(g) < MIN_BARS_SESSION:
            continue
        g = g.sort_values("bucket")
        i = int(np.lexsort((g["bucket"].to_numpy(), -g["volume"].to_numpy(dtype=float)))[0])
        rows.append(int(g["bucket"].iloc[i]))
    if not rows:
        return pd.DataFrame(columns=["time_et", "sessions", "pct"])
    bc = pd.Series(rows).value_counts().sort_index()
    total = int(bc.sum())
    out = pd.DataFrame(
        {
            "time_et": [_bkt_label(int(i)) for i in bc.index],
            "sessions": bc.to_numpy(dtype=int),
            "pct": bc.to_numpy(dtype=float) / total,
        }
    )
    return out


def summarize(sig: pd.DataFrame, half_cut: str) -> list[dict]:
    stats = []
    if sig.empty:
        return stats
    for (pattern, N, zone_rule), g in sig.groupby(["pattern", "N", "zone_rule"], sort=False):
        stats.append(_stat_row(str(pattern), int(N), str(zone_rule), g, half_cut, "full"))
        early = g[g["day"] < half_cut]
        late = g[g["day"] >= half_cut]
        stats.append(_stat_row(str(pattern), int(N), str(zone_rule), early, half_cut, "early"))
        stats.append(_stat_row(str(pattern), int(N), str(zone_rule), late, half_cut, "late"))
    return stats


def _stat_row(pattern: str, N: int, zone_rule: str, g: pd.DataFrame, half_cut: str, window: str) -> dict:
    n = int(len(g))
    if n == 0:
        return {
            "pattern": pattern,
            "label": PATTERN_LABEL.get(pattern, pattern),
            "zone_rule": zone_rule,
            "zone_rule_label": ZONE_RULE_LABEL.get(zone_rule, zone_rule),
            "N": N,
            "window": window,
            "half_cut": half_cut,
            "signals": 0,
            "symbols": 0,
            "days": 0,
            "win_pct": None,
            "avg26": None,
            "med26": None,
            "avg26_exmax": None,
            "day_avg": None,
            "day_med": None,
            "sym_win_pct": None,
            "sym_exp": None,
            "zone_n": 0,
            "zone_win_pct": None,
            "zone_exp": None,
            "avg52": None,
            "per_symbol_day": None,
        }
    fwd = g["fwd26"].to_numpy(dtype=float)
    order = np.argsort(fwd)
    ex = fwd[order[:-1]] if n > 1 else fwd
    by_day = g.groupby("day")["fwd26"].mean()
    sym = g["sym_r"].to_numpy(dtype=float)
    zw = g["zone_r"].dropna()
    avg52 = g["fwd52"].dropna()
    n_sym = int(g["symbol"].nunique())
    n_days = int(g["day"].nunique())
    return {
        "pattern": pattern,
        "label": PATTERN_LABEL.get(pattern, pattern),
        "zone_rule": zone_rule,
        "zone_rule_label": ZONE_RULE_LABEL.get(zone_rule, zone_rule),
        "N": N,
        "window": window,
        "half_cut": half_cut,
        "signals": n,
        "symbols": n_sym,
        "days": n_days,
        "win_pct": float((fwd > 0).mean()),
        "avg26": float(fwd.mean()),
        "med26": float(np.median(fwd)),
        "avg26_exmax": float(ex.mean()),
        "day_avg": float(by_day.mean()),
        "day_med": float(by_day.median()),
        "sym_win_pct": float(g["sym_win"].mean()),
        "sym_exp": float(np.mean(sym)),
        "zone_n": int(len(zw)),
        "zone_win_pct": float((g.loc[zw.index, "zone_win"] == 1).mean()) if len(zw) else None,
        "zone_exp": float(zw.mean()) if len(zw) else None,
        "avg52": float(avg52.mean()) if len(avg52) else None,
        "per_symbol_day": None,
    }


def _base(stats: list[dict], window: str) -> dict | None:
    for s in stats:
        if s["pattern"] == "baseline_1030" and s["window"] == window:
            return s
    return None


def _judge(stats: list[dict]) -> dict:
    """Full-window quality vs the 10:30 baseline. Late half can veto a proposal."""
    base = _base(stats, "full")
    late_base = _base(stats, "late")
    early_base = _base(stats, "early")
    verdicts = []
    for s in stats:
        if s["window"] != "full" or s["pattern"] == "baseline_1030":
            continue
        late = next(
            (
                x for x in stats
                if x["pattern"] == s["pattern"] and x["N"] == s["N"] and x["window"] == "late"
                and x.get("zone_rule") == s.get("zone_rule")
            ),
            None,
        )
        early = next(
            (
                x for x in stats
                if x["pattern"] == s["pattern"] and x["N"] == s["N"] and x["window"] == "early"
                and x.get("zone_rule") == s.get("zone_rule")
            ),
            None,
        )
        reasons = []
        ok = True
        if base is None or s["signals"] < 100 or s["days"] < 12:
            ok = False
            reasons.append("too few signals or days")
        else:
            if s["day_avg"] is None or s["day_avg"] <= base["day_avg"] + 0.001:
                ok = False
                reasons.append("day-averaged return does not beat buying at 10:30 by at least 0.10 percentage points")
            if s["med26"] is None or base["med26"] is None or s["med26"] <= base["med26"]:
                ok = False
                reasons.append("median trade is not above the 10:30 baseline median")
            if s["sym_exp"] is None or base["sym_exp"] is None or s["sym_exp"] <= base["sym_exp"]:
                ok = False
                reasons.append("+1% path expectancy is not above the baseline")
            if s["avg26_exmax"] is None or base["avg26"] is None or s["avg26_exmax"] <= base["avg26"]:
                ok = False
                reasons.append("average without the best trade does not clear the baseline average")
            # Day-average can be pulled up by a few huge days. The typical day has to clear too.
            if s["day_med"] is None or base["day_med"] is None or s["day_med"] <= base["day_med"]:
                ok = False
                reasons.append("the typical day (median of daily average returns) does not beat buying at 10:30")
        late_ok = True
        if late and late["signals"] >= 40 and late_base and late["avg26"] is not None:
            # The later half has to still look like a buy on the typical trade, not only
            # on a day-average that a few big days can inflate.
            if late.get("med26") is None or late["med26"] <= 0:
                late_ok = False
                reasons.append("later half median trade was not positive")
            if late.get("sym_exp") is None or late_base.get("sym_exp") is None or late["sym_exp"] <= late_base["sym_exp"]:
                late_ok = False
                reasons.append("later half +1% expectancy did not beat the later baseline")
            if late["avg26"] < 0 and late["avg26"] < (late_base["avg26"] or 0):
                late_ok = False
                reasons.append("later half of the window was negative and worse than the later baseline")
            if late["day_avg"] is not None and late_base["day_avg"] is not None:
                if late["day_avg"] + 0.0005 < late_base["day_avg"]:
                    late_ok = False
                    reasons.append("later half lost the edge versus buying at 10:30")
        if not late_ok:
            ok = False
        # Ceiling is a headwind check, not a buy candidate, even if numbers are positive.
        kind = "candidate" if ok and s["pattern"] != "ceiling_stack" else "not_proposed"
        if s["pattern"] == "ceiling_stack":
            kind = "headwind_check"
        if s["signals"] < 30:
            kind = "empty_or_thin"
        verdicts.append(
            {
                **s,
                "propose": bool(ok and s["pattern"] != "ceiling_stack"),
                "kind": kind,
                "reasons": reasons,
                "late_signals": late["signals"] if late else 0,
                "late_avg26": late["avg26"] if late else None,
                "late_med26": late["med26"] if late else None,
                "late_day_avg": late["day_avg"] if late else None,
                "early_avg26": early["avg26"] if early else None,
                "early_signals": early["signals"] if early else 0,
                "excess_day_avg": (s["day_avg"] - base["day_avg"]) if base and s["day_avg"] is not None and base["day_avg"] is not None else None,
            }
        )
    proposed = [v for v in verdicts if v["propose"]]
    # Best N is a research label on this window only, among proposed rows for the same pattern.
    best_note = None
    if proposed:
        top = max(proposed, key=lambda v: (v["excess_day_avg"] or -1e9, v["sym_exp"] or -1e9))
        best_note =             {
                "pattern": top["pattern"],
                "label": top["label"],
                "zone_rule": top.get("zone_rule"),
                "N": top["N"],
                "excess_day_avg": top["excess_day_avg"],
            }
    return {
        "verdicts": verdicts,
        "proposed": proposed,
        "best": best_note,
        "baseline": base,
        "late_baseline": late_base,
        "early_baseline": early_base,
    }


# Next-session score is about one trading day. Annualized rate of return (AnnRoR)
# is that simple return times 252 / holding days. Not compound growth, and not a
# portfolio equity-curve Ann ROR.
HOLDING_TRADING_DAYS = 1
ANN_ROR_DAYS = 252


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return _pct(float(x) * (ANN_ROR_DAYS / HOLDING_TRADING_DAYS), digits)


def _num(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{float(x):.{digits}f}"


def _r(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{float(x):.3f}"


def _proposals_html(judge: dict, info: dict, hv: pd.DataFrame) -> str:
    base = judge["baseline"]
    bits = []
    open_pct = 0.0
    if not hv.empty:
        # first two buckets = first 30 minutes
        # hv pct column is a fraction
        pass
    proposed = judge["proposed"]
    if not proposed:
        bits.append(
            "<p><strong>No buy system is proposed from this window.</strong> "
            "Signals were scored against buying the same stocks at 10:30 Eastern Time with no zone. "
            "A pattern had to beat that drift on win-rate path, median trade, and day-averaged return, "
            "and the later half of the window could not contradict it. None cleared that bar, "
            "or the ones that looked fine on the whole window faded in the later weeks. "
            "That is a finding: on about nine weeks of 15-minute data these zone stories are not distinct yet.</p>"
        )
    else:
        # Group by pattern, mention N values that passed.
        by_p: dict[str, list] = {}
        for v in proposed:
            by_p.setdefault(v["pattern"], []).append(v)
        for pattern, rows in by_p.items():
            rows = sorted(rows, key=lambda r: r["N"])
            best = max(rows, key=lambda r: r["excess_day_avg"] or -1e9)
            n_list = ", ".join(str(r["N"]) for r in rows)
            bits.append(
                "<p><strong>{label}.</strong> Carry lengths that cleared the research bar on this window: "
                "{ns} trading days (best excess versus the 10:30 baseline was N={best_n}, "
                "day-averaged return {day} versus baseline {bday}, "
                "{n} signals, {syms} symbols, {days} days, "
                "average next-session return {avg}, median {med}, "
                "+1% before −1% win rate {sw}, expectancy {se} R). "
                "Read that N only as which setting looked strongest on this short sample. "
                "It is not a tuned freeze, and a longer history can change it. "
                "Not gold and not wired into DailyRun.</p>".format(
                    label=html.escape(rows[0]["label"]),
                    ns=html.escape(n_list),
                    best_n=best["N"],
                    day=_pct(best["day_avg"]),
                    bday=_pct(base["day_avg"] if base else None),
                    n=best["signals"],
                    syms=best["symbols"],
                    days=best["days"],
                    avg=_pct(best["avg26"]),
                    med=_pct(best["med26"]),
                    sw=_pct(best["sym_win_pct"]),
                    se=_r(best["sym_exp"]),
                )
            )
    # Headwind note for ceiling if it is worse than baseline.
    ceilings = [
        v for v in judge["verdicts"]
        if v["pattern"] == "ceiling_stack" and v["signals"] >= 100 and v["excess_day_avg"] is not None
    ]
    if ceilings:
        worst = min(ceilings, key=lambda v: v["excess_day_avg"])
        if worst["excess_day_avg"] < -0.001:
            bits.append(
                "<p><strong>Ceiling stack is a headwind, not a buy.</strong> "
                "When several high-volume zones sat just overhead and none sat just under price, "
                "the next session did worse than the 10:30 baseline "
                "(N={n}, excess day-averaged return {ex}). "
                "That supports waiting when supply is stacked overhead. It is not a short system and not a buy.</p>".format(
                    n=worst["N"],
                    ex=_pct(worst["excess_day_avg"]),
                )
            )
        elif all(v["excess_day_avg"] > -0.001 for v in ceilings):
            bits.append(
                "<p><strong>Ceiling stack was not a distinct headwind on this window.</strong> "
                "Buying into several nearby zones overhead did not lag the 10:30 baseline by a clear margin. "
                "Treat the idea as unproven, not as a system.</p>"
            )
    return "\n".join(bits)


def _open_share(hv: pd.DataFrame) -> tuple[float, float, float]:
    if hv.empty:
        return 0.0, 0.0, 0.0
    p0 = float(hv.loc[hv["time_et"] == "09:30", "pct"].sum())
    p1 = float(hv.loc[hv["time_et"].isin(["09:30", "09:45"]), "pct"].sum())
    pclose = float(hv.loc[hv["time_et"] == "15:45", "pct"].sum())
    return p0, p1, pclose


def _pick(stats: list[dict], pattern: str, N: int, zone_rule: str, window: str) -> dict | None:
    for s in stats:
        if (
            s["pattern"] == pattern
            and int(s["N"]) == int(N)
            and s.get("zone_rule") == zone_rule
            and s["window"] == window
        ):
            return s
    return None


def _family_blurb(stats: list[dict], pattern: str, zone_rule: str) -> str:
    """One plain sentence at carry = 10 days, plus whether 5/8/20 agree on the average's sign."""
    row = _pick(stats, pattern, 10, zone_rule, "full")
    early = _pick(stats, pattern, 10, zone_rule, "early")
    late = _pick(stats, pattern, 10, zone_rule, "late")
    if row is None or row["signals"] == 0:
        return f"{PATTERN_LABEL.get(pattern, pattern)} ({ZONE_RULE_LABEL.get(zone_rule, zone_rule)}, 10 trading days): no signals."
    signs = []
    for n in NS:
        r = _pick(stats, pattern, n, zone_rule, "full")
        if r and r["avg26"] is not None:
            signs.append(r["avg26"])
    if signs and all(x > 0.0005 for x in signs):
        agree = "The full-window average stayed positive at every carry length (5, 8, 10, and 20)."
    elif signs and all(x < -0.0005 for x in signs):
        agree = "The full-window average stayed negative at every carry length (5, 8, 10, and 20)."
    else:
        agree = "The full-window average’s sign was not the same at every carry length, so N is not a stable winner."
    full_plus = row.get("avg26") is not None and row["avg26"] > 0.0005
    if full_plus and late and late.get("avg26") is not None and late["avg26"] < -0.0005:
        agree += " The later half’s average was negative, so that plus sign is not a holdout."
    elif full_plus and late and late.get("med26") is not None and late["med26"] <= 0:
        agree += " The later half’s typical trade was not a winner."
    return (
        f"{PATTERN_LABEL.get(pattern, pattern)}, {ZONE_RULE_LABEL.get(zone_rule, zone_rule)}, "
        f"carried 10 trading days: {row['signals']} signals, average next-session return {_pct(row['avg26'])}, "
        f"median {_pct(row['med26'])}, day-averaged return {_pct(row['day_avg'])}, "
        f"+1% expectancy {_r(row['sym_exp'])} R. "
        f"Before {row['half_cut']}: average {_pct(early['avg26'] if early else None)}, median {_pct(early['med26'] if early else None)} "
        f"on {early['signals'] if early else 0} signals. "
        f"On or after {row['half_cut']}: average {_pct(late['avg26'] if late else None)}, median {_pct(late['med26'] if late else None)} "
        f"on {late['signals'] if late else 0} signals. "
        f"{agree}"
    )


def _mid_followup(stats: list[dict], hv: pd.DataFrame, half_cut: str) -> tuple[str, str]:
    """Compare zones born in the middle of the session with the full set and the close-only set."""
    if hv.empty:
        mid_share = open_share = close_share = edge_near = 0.0
    else:
        mid_share = float(hv.loc[~hv["time_et"].isin(["09:30", "15:45"]), "pct"].sum())
        open_share = float(hv.loc[hv["time_et"] == "09:30", "pct"].sum())
        close_share = float(hv.loc[hv["time_et"] == "15:45", "pct"].sum())
        edge_near = float(hv.loc[hv["time_et"].isin(["09:45", "15:30"]), "pct"].sum())
    base_e = _pick(stats, "baseline_1030", 0, "baseline", "early")
    base_l = _pick(stats, "baseline_1030", 0, "baseline", "late")
    base_f = _pick(stats, "baseline_1030", 0, "baseline", "full")

    rows_html = []
    notes = []
    notes_vs_close: list[tuple[float, str]] = []
    both_halves = []
    for pattern in PATTERN_ORDER:
        if pattern == "baseline_1030":
            continue
        for n in NS:
            mid = _pick(stats, pattern, n, "mid_session", "full")
            full = _pick(stats, pattern, n, "as_asked", "full")
            close = _pick(stats, pattern, n, "close_only", "full")
            mid_e = _pick(stats, pattern, n, "mid_session", "early")
            mid_l = _pick(stats, pattern, n, "mid_session", "late")
            if mid is None:
                continue
            delta = None
            if mid.get("avg26") is not None and full and full.get("avg26") is not None:
                delta = mid["avg26"] - full["avg26"]
            close_delta = None
            if mid.get("avg26") is not None and close and close.get("avg26") is not None:
                close_delta = mid["avg26"] - close["avg26"]
            thin = mid["signals"] < 80
            noticeable = (not thin) and delta is not None and abs(delta) >= 0.0015
            if (not thin) and close_delta is not None and abs(close_delta) >= 0.0015:
                direction = "higher" if close_delta > 0 else "lower"
                notes_vs_close.append(
                    (
                        abs(close_delta),
                        f"{PATTERN_LABEL[pattern]} at N={n} is {direction} than close-only zones by {_pct(abs(close_delta))} "
                        f"({_pct(mid['avg26'])} vs {_pct(close['avg26'])}; later half {_pct(mid_l['avg26'] if mid_l else None)} "
                        f"on {mid_l['signals'] if mid_l else 0} signals)",
                    )
                )
            if noticeable:
                direction = "higher" if delta > 0 else "lower"
                notes.append(
                    f"{PATTERN_LABEL[pattern]} at N={n}: mid-session average is {direction} than the full set "
                    f"by {_pct(abs(delta))} ({_pct(mid['avg26'])} vs {_pct(full['avg26'])}, "
                    f"{mid['signals']} mid-session signals, win rate {_pct(mid['win_pct'])}). "
                    f"Before {half_cut}: {_pct(mid_e['avg26'] if mid_e else None)} on {mid_e['signals'] if mid_e else 0} signals. "
                    f"On or after {half_cut}: {_pct(mid_l['avg26'] if mid_l else None)} "
                    f"(median {_pct(mid_l['med26'] if mid_l else None)}) on {mid_l['signals'] if mid_l else 0} signals."
                )
            beats_both = False
            if (
                mid_e and mid_l and base_e and base_l
                and mid_e["signals"] >= 40 and mid_l["signals"] >= 40
                and mid_e.get("avg26") is not None and mid_l.get("avg26") is not None
                and base_e.get("avg26") is not None and base_l.get("avg26") is not None
                and mid_e["avg26"] > base_e["avg26"] and mid_l["avg26"] > base_l["avg26"]
                and mid_l.get("med26") is not None and mid_l["med26"] > 0
            ):
                beats_both = True
                both_halves.append(f"{PATTERN_LABEL[pattern]} N={n}")
            rows_html.append(
                "<tr>"
                f"<td>{html.escape(PATTERN_LABEL[pattern])}</td>"
                f"<td>{n}</td>"
                f"<td>{mid['signals']}</td>"
                f"<td>{_pct(mid['win_pct'])}</td>"
                f"<td>{_pct(mid['avg26'])}</td>"
                f"<td>{_ann(mid['avg26'])}</td>"
                f"<td>{_pct(mid['med26'])}</td>"
                f"<td>{mid_e['signals'] if mid_e else 0}</td>"
                f"<td>{_pct(mid_e['avg26'] if mid_e else None)}</td>"
                f"<td>{_ann(mid_e['avg26'] if mid_e else None)}</td>"
                f"<td>{mid_l['signals'] if mid_l else 0}</td>"
                f"<td>{_pct(mid_l['avg26'] if mid_l else None)}</td>"
                f"<td>{_ann(mid_l['avg26'] if mid_l else None)}</td>"
                f"<td>{_pct(mid_l['med26'] if mid_l else None)}</td>"
                f"<td>{_pct(full['avg26'] if full else None)}</td>"
                f"<td>{_ann(full['avg26'] if full else None)}</td>"
                f"<td>{_pct(delta)}</td>"
                f"<td>{close['signals'] if close else 0}</td>"
                f"<td>{_pct(close['avg26'] if close else None)}</td>"
                f"<td>{_ann(close['avg26'] if close else None)}</td>"
                f"<td>{'thin' if thin else ('yes' if noticeable else 'no')}</td>"
                "</tr>"
            )

    if not notes:
        diff_sentence = (
            "Versus the original full set (which is mostly closing candles), nothing in the mid-session slice "
            "moves the average next-session return by 0.15 percentage points or more, with at least 80 signals. "
            "Reclaim, bounce, shelf, clean break, and the ceiling check stay in the same neighborhood as the full set."
        )
    else:
        diff_sentence = (
            "Versus the original full set, the gaps of at least 0.15 percentage points are these. "
            + " ".join(notes)
        )
    if notes_vs_close:
        top_close = [text for _, text in sorted(notes_vs_close, key=lambda x: -x[0])[:6]]
        diff_sentence += (
            f" Versus zones born only on the 15:45 close, {len(notes_vs_close)} cells differ by at least "
            f"0.15 percentage points. The largest are: " + "; ".join(top_close) + "."
        )
    else:
        diff_sentence += " Versus close-only zones, no pattern clears that same 0.15 percentage point gap."

    if both_halves:
        adopt = (
            "These mid-session cells beat a 10:30 buy in both halves of this window, with a positive later-half median: "
            + "; ".join(both_halves)
            + ". That is still this nine-week sample only. It is not wired into DailyRun and it is not gold."
        )
    else:
        adopt = (
            "No mid-session pattern beat a 10:30 buy in both halves of this window with a positive later-half typical trade. "
            "No system is justified from this slice."
        )

    def th(label: str, typ: str) -> str:
        return (
            f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
            f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
        )

    base_line = (
        f"The no-zone 10:30 buy on this same tape averaged {_pct(base_f['avg26'] if base_f else None)} overall, "
        f"{_pct(base_e['avg26'] if base_e else None)} before {half_cut}, and "
        f"{_pct(base_l['avg26'] if base_l else None)} on or after {half_cut}."
    )
    intro = (
        f"A zone is included here only when that day’s single busiest 15-minute candle was neither the 09:30 bar "
        f"nor the 15:45 bar. Days whose busiest candle is the open or the close contribute no zone. "
        f"We do not substitute a quieter bar. The 09:45 bar and the 15:30 bar are still mid-session "
        f"(together about {_pct(edge_near)} of sessions). "
        f"Share of liquid complete sessions: mid-session {_pct(mid_share)}, 09:30 open {_pct(open_share)}, "
        f"15:45 close {_pct(close_share)}. "
        f"The close-only column is the opposite slice: a zone only when the busiest candle is 15:45."
    )
    html_block = f"""
<h2>Follow-up: mid-session zones</h2>
<div class="callout">
<h2 style="margin-top:0">What you asked (follow-up)</h2>
<p>{html.escape(FOLLOWUP_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>The first pass often drew the band from the last 15 minutes, because that candle usually has the most shares. This follow-up keeps a band only when the busiest candle of the day was somewhere in the middle: not the 09:30 open and not the 15:45 close. The 09:45 and 15:30 candles still count. If the day’s busiest candle was the open or the close, that day has no band at all — we do not quietly swap in the next-busiest candle. Volume Zone (VZ) still means the separate daily system; this slice does not rerun it.</p>
<p>{html.escape(intro)}</p>
</div>
<p>{html.escape(base_line)} {html.escape(diff_sentence)}</p>
<p><strong>{html.escape(adopt)}</strong></p>
<p class="note">Click column headers to sort. “Mid minus full” is the mid-session average minus the original full-set average, in the same 26-bar window. Positive means the mid-session zones returned more. The later half is entries on or after {html.escape(half_cut)}.</p>
<table class="sortable">
<caption>Mid-session zones versus the full set and versus close-only zones. Research scan, not a sleeve compare.</caption>
<thead><tr>
{th("Pattern", "text")}
{th("Carry N", "num")}
{th("Mid signals", "num")}
{th("Mid win %", "num")}
{th("Mid avg", "num")}
{th("Mid AnnRoR", "num")}
{th("Mid median", "num")}
{th("Early n", "num")}
{th("Early avg", "num")}
{th("Early AnnRoR", "num")}
{th("Late n", "num")}
{th("Late avg", "num")}
{th("Late AnnRoR", "num")}
{th("Late median", "num")}
{th("Full-set avg", "num")}
{th("Full-set AnnRoR", "num")}
{th("Mid minus full", "num")}
{th("Close-only n", "num")}
{th("Close-only avg", "num")}
{th("Close-only AnnRoR", "num")}
{th("Noticeable gap", "text")}
</tr></thead>
<tbody>
{"".join(rows_html)}
</tbody>
</table>
"""
    md = f"""## Follow-up: mid-session zones

> {FOLLOWUP_REQUEST}

A zone counts only when the day’s busiest 15-minute candle is neither 09:30 nor 15:45. The 09:45 and 15:30 bars still count. Days whose busiest candle is the open or the close get no zone (we do not substitute). Session share: mid-session {_pct(mid_share)}, 09:30 {_pct(open_share)}, 15:45 {_pct(close_share)}.

{base_line}

{diff_sentence}

{adopt}
"""
    return html_block, md


def write_reports(info: dict, cov_files: dict, hv: pd.DataFrame, stats: list[dict], judge: dict, half_cut: str) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    p0, p30, pclose = _open_share(hv)
    base = judge["baseline"]
    proposals_md = []
    proposed = judge["proposed"]
    if not proposed:
        proposals_md.append(
            "No buy system cleared the bar. Each pattern had to beat buying at 10:30 Eastern Time "
            "on the day-averaged return (by at least 0.10 percentage points), the median trade, "
            "and the +1% before −1% expectancy, and the later half of this window could not contradict it. "
            "On this nine-week sample the zone stories are not distinct enough to propose."
        )
        proposals_md.append(
            "What the patterns actually did is listed under each family below. "
            "A positive full-window average that flips negative in the later half is not a system."
        )
    else:
        by_p: dict[str, list] = {}
        for v in proposed:
            by_p.setdefault(v["pattern"], []).append(v)
        for rows in by_p.values():
            best = max(rows, key=lambda r: r["excess_day_avg"] or -1e9)
            ns = ", ".join(str(r["N"]) for r in sorted(rows, key=lambda r: r["N"]))
            proposals_md.append(
                f"{best['label']}: carry lengths {ns} trading days cleared the research bar. "
                f"The strongest excess versus the 10:30 baseline on this window was N={best['N']} "
                f"(day-averaged return {_pct(best['day_avg'])} vs baseline {_pct(base['day_avg'] if base else None)}, "
                f"{best['signals']} signals, median {_pct(best['med26'])}, "
                f"+1% win rate {_pct(best['sym_win_pct'])}, expectancy {_r(best['sym_exp'])} R). "
                f"That N is a research label on a short sample, not a freeze. Not gold. Not DailyRun."
            )

    early_b = judge.get("early_baseline") or {}
    late_b = judge.get("late_baseline") or {}
    eb = early_b.get("avg26")
    lb = late_b.get("avg26")
    if eb is not None and lb is not None and eb > 0.0005 and lb < -0.0005:
        regime = "The first half of this window was an up market and the second half was a down market."
    elif eb is not None and lb is not None and eb < -0.0005 and lb > 0.0005:
        regime = "The first half of this window was a down market and the second half was an up market."
    else:
        regime = "The two halves of this window did not show a simple up-then-down split."
    proposals_md.append(
        f"Market drift on this tape, with no zone: before {half_cut} the 10:30 buy averaged "
        f"{_pct(eb)} ({early_b.get('signals', 0)} signals); "
        f"on or after {half_cut} it averaged {_pct(lb)} "
        f"({late_b.get('signals', 0)} signals). {regime} "
        f"Any zone idea has to beat that drift, including in the later half."
    )
    proposals_md.append(
        f"The busiest 15-minute candle was the 15:45 bar (the last bar of the regular session) "
        f"{_pct(pclose)} of the time. The 09:30 bar was only {_pct(p0)}. "
        f"Closing auctions and last-minute prints pile volume into that final candle, so the zone "
        f"as asked is often the closing range, carried forward. A second pass drops that 15:45 bar "
        f"when choosing the zone and uses the busiest earlier candle instead. Both passes are in the tables."
    )
    for pattern in (
        "reclaim_highest",
        "bounce_lowest",
        "support_shelf",
        "spring_lowest",
        "clean_break_highest",
        "ceiling_stack",
    ):
        proposals_md.append(_family_blurb(stats, pattern, "as_asked"))
        proposals_md.append(_family_blurb(stats, pattern, "ex_last_bar"))

    if not proposed:
        looks = [
            v for v in judge["verdicts"]
            if v["pattern"] == "clean_break_highest"
            and v.get("zone_rule") == "ex_last_bar"
            and v["signals"] >= 100
            and v.get("avg26") is not None
        ]
        if looks:
            top = max(looks, key=lambda v: v["avg26"])
            proposals_md.append(
                "The closest look was a clean break above the highest zone after ignoring the 15:45 close candle. "
                f"At N={top['N']} the pooled average next-session return was {_pct(top['avg26'])} "
                f"(median {_pct(top['med26'])}, {top['signals']} signals), which is above the flat 10:30 baseline. "
                f"The later half’s median trade was {_pct(top.get('late_med26'))}. "
                "A longer carry made the pooled average a bit larger, but that is the up-market half keeping old zones alive, "
                "not a reason to pick an N. No best carry length is adopted."
            )

    # Empty / thin patterns
    thin_lines = []
    full_rows = [s for s in stats if s["window"] == "full" and s["pattern"] != "baseline_1030"]
    for s in full_rows:
        if s["signals"] < 30:
            thin_lines.append(f"- {s['label']} at N={s['N']}: {s['signals']} signals (thin or empty).")

    real_notes = []
    for v in judge["verdicts"]:
        if v["signals"] < 30:
            tag = "thin/empty"
        elif v["propose"]:
            tag = "proposed (research)"
        elif v["kind"] == "headwind_check":
            tag = "headwind check"
        else:
            tag = "seen, not proposed"
        real_notes.append(
            f"- {v['label']} [{v.get('zone_rule_label', v.get('zone_rule'))}] N={v['N']}: {tag}; "
            f"signals={v['signals']}; avg={_pct(v['avg26'])}; day-avg={_pct(v['day_avg'])}; "
            f"excess vs 10:30={_pct(v['excess_day_avg'])}; "
            f"early avg={_pct(v.get('early_avg26'))}; late avg={_pct(v.get('late_avg26'))}."
        )

    baseline_md = f"""# 15-minute high-volume day zone — research baseline

Study id: `hv15m_day_zone_forward_20260925`

This is a **new 15-minute study**. It is not a rerun of the daily Volume Zone (VZ) system (`rocket_vz.py` / `run_vz.bat`), and it is not wired into DailyRun. It is not gold.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

Each day we find the single 15-minute candle with the most shares traded, and we draw a price band from that candle’s low to that candle’s high. We keep that band on the chart for several more trading days (5, 8, 10, or 20) and ask whether later price action around those bands has a repeatable shape worth buying. “Moves higher” is measured the same way for every idea: from the next 15-minute bar’s open, what happened over the next session, and whether price hit +1% before it hit −1%. The comparison is simply buying at 10:30 Eastern Time with no zone at all, so a rising market does not get mistaken for a zone edge.

## Zone definition

- Bars: Regular Trading Hours only, 09:30–16:00 US/Eastern. 15-minute candles are resampled from the stored 1-minute bars, left-labeled and anchored at 09:30 (the 09:30 bar covers 09:30–09:44).
- One zone per symbol per trading session: the highest-volume 15-minute bar. If two bars tie on volume, the earlier bar wins.
- Zone edges: **high and low of that candle** (not open-close). A bar whose high-to-low range is under 0.05% of its midpoint is skipped.
- Primary rule (`as_asked`): any Regular Trading Hours 15-minute bar may be the zone, including 15:45.
- Sensitivity (`ex_last_bar`): the 15:45 bar cannot be elected. The zone is the highest-volume bar that starts at 15:30 or earlier. Signals can still occur on the 15:45 bar; only the zone source changes.
- The zone is known only after that candle closes. It can be used on later 15-minute bars the same day, and it stays active through **N trading sessions after the birth session** (weekends are not counted). N is tested at 5, 8, 10, and 20. N is a sensitivity grid of one idea, not four different systems.
- Highest active zone: the active zone with the highest high (most recent wins a tie). Lowest active zone: the active zone with the lowest low (most recent wins a tie).

## Patterns (one family each)

1. **Reclaim highest zone.** A bar closes above the highest active zone, and the prior bar had not. A *later* bar comes back and touches that zone (its range overlaps the band) and then closes back above the zone’s high. If price closes under the zone’s low first, the idea is cancelled. If that zone stops being the highest active zone, the idea is cancelled. Buy the next 15-minute open. Zone-edge stop for the optional R test: the zone’s low.
2. **Bounce off the lowest zone.** At least two zones are active and the lowest one is not the same as the highest. A green 15-minute candle wicks into the lowest zone (low inside the band) and closes above it. Only the first such bounce per zone. Buy the next open. Stop: zone low.
3. **Support shelf.** At least three active zones sit just under price (each zone’s high is within 1.5% below the close) and none sit just overhead (no zone low within 1.5% above the close). Any zone above that is at least 3% away, or there is no zone above. The first green 15-minute bar of that session which meets the test. One signal per symbol per session. Stop: low of the nearest zone underneath.
4. **Spring off the lowest zone** (extra pattern). Price closes under the lowest zone, then within the next 8 completed 15-minute bars a green bar closes back above that zone’s high. One attempt per zone. Stop: zone low.
5. **Clean break of the highest zone** (extra pattern). The whole bar is above the highest zone (low and close both above the zone high) and the prior close was not. First time per zone. This is “buy the break” without waiting for a pullback, so it can be compared with the reclaim. Stop: zone low.
6. **Ceiling stack** (extra check, not a buy idea). The mirror of the shelf: at least three zones within 1.5% overhead, none within 1.5% underneath, nearest support at least 3% below or absent. We record what a long entry would have done, to see whether overhead zones are a headwind.

**Baseline:** buy at the open of the 10:30 Eastern Time 15-minute bar, same forward window, no zone. Same liquid names.

## How a trade is scored

- Fill: next 15-minute bar’s open after the signal bar closes (the baseline fills at the 10:30 open itself).
- Primary window: the next **26** 15-minute bars (one regular session) from the fill bar, including that bar. We also record 52 bars (about two sessions) when those bars exist.
- Forward return: fill to the close of the last bar in the window.
- Comparable path: did price trade +1% above the fill before it traded −1% below the fill? If both happen on the same bar, it counts as a loss. If neither happens by the end of the window, the result is the ending move divided by 1% (so a +0.4% drift is +0.4 R, not a win).
- Optional zone-edge path: same idea with the stop at the zone low and a target one times that risk above the fill. Trades are left out of this column when that risk is under 0.10% or over 8% of price (too tight to be real, or a very wide bar). Same-bar stop and target counts as a loss.
- Quality: win rate, average and median return, average with the single best trade removed, and the average of each day’s average return (so one market day cannot pretend to be many independent wins). Signal count is reported beside quality.
- House in-sample / out-of-sample split (entry before 2024-01-01 versus on or after) **does not apply**. Every bar in this store is from 2026. Inventing a 2010 or 2024 split would be false. A caution split inside this window only: entry date before {half_cut} versus on or after {half_cut}. The later half can veto a proposal. It is not used to pick the winner.

## Universe and dates

- 1-minute files on disk: {cov_files.get("n_files", "—")} under `data/intraday/1m/` (Yahoo 1-minute, accumulated locally; not a multi-year archive).
- Symbols with at least one 15-minute bar: {info["symbols_with_15m"]}.
- Liquid set used for signals: **{info["symbols_liquid"]}** symbols. Rules: at least {MIN_SESSIONS} sessions that each have at least {MIN_BARS_SESSION} valid 15-minute bars, median session dollar volume (volume times close, summed) at least ${MIN_DOLLAR_VOL:,.0f}, median close at least ${MIN_PRICE:.0f}.
- Date span of the 15-minute bars: **{info["date_min"]} through {info["date_max"]}** ({info["sessions_calendar"]} calendar dates present in the 1-minute store before the liquid filter).
- 15-minute rows in the liquid set: {info["rows_liquid"]:,}.

## What the highest-volume candle actually is

Share of liquid complete sessions whose high-volume candle is the **15:45 bar** (last 15 minutes, 15:45–16:00): **{_pct(pclose)}**. The 09:30 bar is only **{_pct(p0)}**. The first 30 minutes (09:30 or 09:45) are **{_pct(p30)}**. Closing auctions and the last-minute print in the Yahoo 1-minute bars pile volume into that final candle, so “the highest-volume candle of the day” is often the close, not a midday event. The primary scan uses that candle anyway, because that is the request. A labeled sensitivity drops the 15:45 bar and elects the highest-volume candle among earlier bars. Both are reported. The sensitivity is not a retune and is not adopted.

## What we did not claim

- Not gold. Not a DailyRun system. Not a portfolio backtest (no one-position rule, no sizing, no equity-curve annualized rate of return, no max drawdown book). The tables now include a simple annualized rate of return (AnnRoR): the next-session average multiplied by 252. That is the same one-day move scaled up. It is not compound growth and not a yearly portfolio return. Canonical sleeve metrics are therefore not used; this is a pattern scan.
- No slippage model beyond “next bar’s open,” no fees, no partial fills.
- N is not adopted. If one N looks best below, that is a label on this sample only.
- Daily Volume Zone (VZ) touch rules were not reused as the engine. Touch here means the 15-minute bar’s range overlaps the band.

## Pattern results (see compare.html for the sortable table)

Baseline 10:30, full window: signals {base["signals"] if base else "—"}, average 26-bar return {_pct(base["avg26"] if base else None)}, day-averaged return {_pct(base["day_avg"] if base else None)}, +1% expectancy {_r(base["sym_exp"] if base else None)} R.

{chr(10).join(real_notes)}

### Thin or empty

{chr(10).join(thin_lines) if thin_lines else "- None of the six pattern families were empty at every N."}

## Proposed systems

{chr(10).join(f"{i}. {p}" for i, p in enumerate(proposals_md, 1))}
"""
    (STAMP / "BASELINE.md").write_text(baseline_md, encoding="utf-8")

    summary = f"""# Summary — 15-minute high-volume day zone

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

We marked a price band from the low to the high of each day’s busiest 15-minute candle, kept that band for 5, 8, 10, or 20 trading days, and looked for repeatable buy shapes. The fair comparison is “just buy at 10:30,” because this whole sample is one short stretch of 2026 and the market’s own drift can look like an edge. Annualized rate of return (AnnRoR) on the tables is the next-session average multiplied by 252. It scales that one-day move. It is not a yearly portfolio return, and it does not change the verdict.

## Coverage

- {info["symbols_liquid"]} liquid symbols out of {info["symbols_with_15m"]} with 15-minute bars, from {info["date_min"]} to {info["date_max"]}.
- 1-minute files on disk: {cov_files.get("n_files", "—")}. This is not years of intraday history.
- Highest-volume candle at 15:45 (last bar): {_pct(pclose)}. At 09:30: {_pct(p0)}. First 30 minutes: {_pct(p30)}.
- House 2024 in-sample / out-of-sample split: not available. Caution split date inside this window: {half_cut}.

## Best N

"""
    if judge["best"]:
        b = judge["best"]
        summary += (
            f"On this window only, the strongest research label was **{b['label']}** at **N={b['N']}** "
            f"(day-averaged return excess versus the 10:30 baseline {_pct(b['excess_day_avg'])}). "
            "That is not a freeze and not an adoption. Do not retune a story on this sample.\n"
        )
    else:
        summary += (
            "No carry length earned a “best N” label, because no pattern beat the 10:30 baseline "
            "under the rules in BASELINE.md. Do not pick a favorite N from a flat or losing grid.\n"
        )

    summary += "\n## Proposed systems\n\n"
    summary += "\n\n".join(proposals_md)
    summary += (
        "\n\nResearch only. Not gold. Not wired into DailyRun. "
        "Full definitions and the sortable numbers are in BASELINE.md and compare.html.\n"
    )
    mid_html, mid_md = _mid_followup(stats, hv, half_cut)
    summary = summary + "\n" + mid_md
    (STAMP / "SUMMARY.md").write_text(summary, encoding="utf-8")

    def th(label: str, typ: str) -> str:
        return (
            f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
            f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
        )

    def td(val: str, cls: str = "") -> str:
        attr = f' class="{cls}"' if cls else ""
        return f"<td{attr}>{val}</td>"

    full = [s for s in stats if s["window"] == "full"]
    # stable order
    rule_order = {"baseline": 0, "as_asked": 1, "ex_last_bar": 2, "mid_session": 3, "close_only": 4}

    def sort_key(s):
        try:
            pi = PATTERN_ORDER.index(s["pattern"])
        except ValueError:
            pi = 99
        return (rule_order.get(s.get("zone_rule"), 9), pi, s["N"])

    full = sorted(full, key=sort_key)

    body = []
    for s in full:
        nshow = "—" if s["pattern"] == "baseline_1030" else str(s["N"])
        body.append(
            "<tr>"
            + td(html.escape(s["label"]))
            + td(html.escape(s.get("zone_rule_label") or ""))
            + td(nshow)
            + td(str(s["signals"]))
            + td(str(s["symbols"]))
            + td(str(s["days"]))
            + td(_pct(s["win_pct"]))
            + td(_pct(s["avg26"]))
            + td(_ann(s["avg26"]))
            + td(_pct(s["med26"]))
            + td(_pct(s["avg26_exmax"]))
            + td(_pct(s["day_avg"]))
            + td(_pct(s["day_med"]))
            + td(_pct(s["avg52"]))
            + "</tr>"
        )

    rbody = []
    for s in full:
        nshow = "—" if s["pattern"] == "baseline_1030" else str(s["N"])
        rbody.append(
            "<tr>"
            + td(html.escape(s["label"]))
            + td(html.escape(s.get("zone_rule_label") or ""))
            + td(nshow)
            + td(str(s["signals"]))
            + td(_pct(s["sym_win_pct"]))
            + td(_r(s["sym_exp"]))
            + td(str(s["zone_n"]))
            + td(_pct(s["zone_win_pct"]))
            + td(_r(s["zone_exp"]))
            + "</tr>"
        )

    hbody = []
    seen = {}
    for s in stats:
        seen.setdefault((s["pattern"], s["N"], s.get("zone_rule")), {})[s["window"]] = s
    def half_key(k):
        try:
            pi = PATTERN_ORDER.index(k[0])
        except ValueError:
            pi = 99
        return (rule_order.get(k[2], 9), pi, k[1])
    for key in sorted(seen, key=half_key):
        parts = seen[key]
        f, e, l = parts.get("full"), parts.get("early"), parts.get("late")
        if not f:
            continue
        nshow = "—" if f["pattern"] == "baseline_1030" else str(f["N"])
        hbody.append(
            "<tr>"
            + td(html.escape(f["label"]))
            + td(html.escape(f.get("zone_rule_label") or ""))
            + td(nshow)
            + td(str(e["signals"] if e else 0))
            + td(_pct(e["avg26"] if e else None))
            + td(_ann(e["avg26"] if e else None))
            + td(_pct(e["day_avg"] if e else None))
            + td(str(l["signals"] if l else 0))
            + td(_pct(l["avg26"] if l else None))
            + td(_ann(l["avg26"] if l else None))
            + td(_pct(l["day_avg"] if l else None))
            + "</tr>"
        )

    hv_body = []
    for _, r in hv.iterrows():
        hv_body.append(
            "<tr>"
            + td(html.escape(str(r["time_et"])))
            + td(str(int(r["sessions"])))
            + td(_pct(float(r["pct"])))
            + "</tr>"
        )

    prop_html = "\n".join(f"<p>{html.escape(p)}</p>" for p in proposals_md)
    open_sentence = (
        f"On the liquid names, the busiest 15-minute candle was the 15:45 bar "
        f"{_pct(pclose)} of the time. The 09:30 bar was {_pct(p0)}, "
        f"and the first 30 minutes together were {_pct(p30)}."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>15-minute high-volume day zone — research scan</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1180px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #334155; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 8px 8px; }}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin-bottom: 6px; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
code {{ background: #f1f5f9; padding: 0 4px; }}
</style>
</head>
<body>
<h1>15-minute high-volume day zone</h1>
<p class="note">Research scan only. Not gold. Not wired into DailyRun. Not the daily Volume Zone (VZ) system. Window: {html.escape(info["date_min"])} to {html.escape(info["date_max"])}. Liquid symbols: {info["symbols_liquid"]}.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ORIGINAL_REQUEST)}</p>
<p><strong>Follow-up:</strong> {html.escape(FOLLOWUP_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>Each day we draw a band from the low to the high of that day’s busiest 15-minute candle, keep the band for 5, 8, 10, or 20 trading days, and look for buys: a break above the top band that comes back and holds, a bounce off the bottom band, or a stack of bands just under the price with little overhead. We judge those ideas by how the price behaved over the next session, and we compare them with simply buying at 10:30 with no band at all. This history is only about nine weeks in 2026, so nothing here is a finished system.</p>
<p>{html.escape(open_sentence)}</p>
<p>Annualized rate of return (AnnRoR) was added beside every average next-session return. It is that one-day average multiplied by 252. It is a simple scaling of the same one-day move, not compound growth and not a yearly portfolio return. A large AnnRoR does not change the verdict.</p>
</div>

<h2>What showed up</h2>
{prop_html}
<p class="note">Click column headers to sort. Returns are from the fill to the close 26 fifteen-minute bars later (about one regular session) unless a column says 52 bars. “Day-avg” is the average of each calendar day’s average return, so a single strong market day weighs once. The +1% path counts a same-bar stop as a loss. Zone-edge R uses a stop at the zone low and drops trades whose risk is under 0.10% or over 8% of price.</p>
{mid_html}

<h2>Pattern results (full window)</h2>
<table class="sortable">
<caption>Pattern versus carry length. Research scan, not a sleeve compare.</caption>
<thead><tr>
{th("Pattern", "text")}
{th("Zone source", "text")}
{th("Carry N (trading days)", "num")}
{th("Signals", "num")}
{th("Symbols", "num")}
{th("Days", "num")}
{th("Win % (close up)", "num")}
{th("Avg 26-bar", "num")}
{th("AnnRoR", "num")}
{th("Median 26-bar", "num")}
{th("Avg ex-best", "num")}
{th("Day-avg", "num")}
{th("Day-median", "num")}
{th("Avg 52-bar", "num")}
</tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>

<h2>+1% path and zone-edge R</h2>
<table class="sortable">
<caption>+1% before −1% is comparable across patterns and the baseline. Zone-edge R is only for signals with a usable zone stop.</caption>
<thead><tr>
{th("Pattern", "text")}
{th("Zone source", "text")}
{th("Carry N", "num")}
{th("Signals", "num")}
{th("+1% before −1% win %", "num")}
{th("+1% expectancy (R)", "num")}
{th("Zone-edge n", "num")}
{th("Zone-edge win %", "num")}
{th("Zone-edge expectancy (R)", "num")}
</tr></thead>
<tbody>
{"".join(rbody)}
</tbody>
</table>

<h2>Early window vs later window</h2>
<p class="note">Caution split inside this sample only: entry before {html.escape(half_cut)} versus on or after {html.escape(half_cut)}. This is not the house in-sample / out-of-sample cut at 2024-01-01. The store has no bars before 2026-07-23. The later half was not used to pick a winner; it can only veto a story that fades.</p>
<table class="sortable">
<caption>Same patterns, split by entry date.</caption>
<thead><tr>
{th("Pattern", "text")}
{th("Zone source", "text")}
{th("Carry N", "num")}
{th("Early signals", "num")}
{th("Early avg", "num")}
{th("Early AnnRoR", "num")}
{th("Early day-avg", "num")}
{th("Late signals", "num")}
{th("Late avg", "num")}
{th("Late AnnRoR", "num")}
{th("Late day-avg", "num")}
</tr></thead>
<tbody>
{"".join(hbody)}
</tbody>
</table>

<h2>When the highest-volume candle prints</h2>
<table class="sortable">
<caption>Liquid complete sessions. Clock time is the start of the 15-minute bar, US/Eastern.</caption>
<thead><tr>
{th("Time ET", "text")}
{th("Sessions", "num")}
{th("Share", "num")}
</tr></thead>
<tbody>
{"".join(hv_body)}
</tbody>
</table>

<h2>Definitions (short)</h2>
<ul>
<li><strong>Zone:</strong> high and low of the single highest-volume 15-minute candle that session. Carried N trading days after the birth session, plus the rest of the birth session after the candle closes. “As asked” may pick the 15:45 close bar. “Exclude 15:45 close bar” picks the busiest earlier candle instead.</li>
<li><strong>Reclaim:</strong> close above the highest zone, then a later touch, then a close back above the zone.</li>
<li><strong>Bounce:</strong> green candle wicks into the lowest zone and closes above it, with some other zone higher.</li>
<li><strong>Support shelf:</strong> three or more zones within 1.5% under the close, none within 1.5% above, nearest overhead at least 3% away or none.</li>
<li><strong>Spring:</strong> close under the lowest zone, then a green close back above it within 8 bars.</li>
<li><strong>Clean break:</strong> an entire bar above the highest zone, no pullback required.</li>
<li><strong>Ceiling stack:</strong> three or more zones within 1.5% overhead and none just below. Logged to see if buying into that ceiling lags.</li>
<li><strong>Baseline:</strong> buy the 10:30 bar, same names, no zone.</li>
</ul>
<p class="note">Volume Zone (VZ) in this note means the existing daily high-volume zone system. This page does not rerun it. Average True Range is not used.</p>
</body>
<script>
(function () {{
  function parseSortValue(text, type) {{
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+R]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }}
  function sortTable(table, col, type, dir) {{
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) {{ return r.classList.contains("total-row"); }});
    var movable = rows.filter(function (r) {{ return !r.classList.contains("total-row"); }});
    movable.sort(function (a, b) {{
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      var aMiss = typeof av === "number" && !Number.isFinite(av);
      var bMiss = typeof bv === "number" && !Number.isFinite(bv);
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      if (typeof av === "string" || typeof bv === "string") {{
        return dir * String(av).localeCompare(String(bv));
      }}
      return dir * (av - bv);
    }});
    movable.concat(pinned).forEach(function (r) {{ tbody.appendChild(r); }});
  }}
  document.querySelectorAll("table.sortable").forEach(function (table) {{
    var headers = table.querySelectorAll("th.sortable-th");
    headers.forEach(function (th, col) {{
      function activate(ev) {{
        if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.type === "keydown") ev.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        headers.forEach(function (h) {{
          h.classList.remove("sort-asc", "sort-desc");
          h.setAttribute("aria-sort", "none");
        }});
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, type, dir);
      }}
      th.addEventListener("click", activate);
      th.addEventListener("keydown", activate);
    }});
  }});
}})();
</script>
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")
    meta = {
        "info": info,
        "cov_files": cov_files,
        "half_cut": half_cut,
        "open_share_0930": p0,
        "open_share_first_30m": p30,
        "close_bar_1545_share": pclose,
        "best": judge["best"],
        "proposed": [
            {"pattern": v["pattern"], "N": v["N"], "signals": v["signals"], "excess_day_avg": v["excess_day_avg"]}
            for v in judge["proposed"]
        ],
    }
    (STAMP / "scan_meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"wrote {STAMP / 'compare.html'}", flush=True)


def main() -> int:
    if not ONE_MIN.exists():
        print("missing data/intraday/1m", file=sys.stderr)
        return 2
    n_files = len(list(ONE_MIN.glob("*.parquet")))
    STAMP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    bars = build_15m(con)
    liquid, info = select_universe(bars)
    days_sorted = sorted(pd.to_datetime(liquid["day"]).dt.date.unique())
    half_cut = days_sorted[len(days_sorted) // 2].isoformat() if days_sorted else "2026-08-24"
    print(f"half cut (caution only) {half_cut} n_days {len(days_sorted)}", flush=True)

    reports_only = "--reports-only" in sys.argv and SIGNALS_CSV.exists()
    print("high-volume candle clock...", flush=True)
    hv = hv_time_table(liquid)
    hv.to_csv(STAMP / "hv_time_of_day.csv", index=False)

    mid_only = "--mid-only" in sys.argv and SIGNALS_CSV.exists()
    if reports_only:
        print(f"reports only from {SIGNALS_CSV}", flush=True)
        sig = pd.read_csv(SIGNALS_CSV)
    elif mid_only:
        print("scanning mid-session and close-only zones...", flush=True)
        prior = pd.read_csv(SIGNALS_CSV)
        prior = prior[~prior["zone_rule"].isin(["mid_session", "close_only"])]
        rows = []
        n_sym = 0
        for sym, g in liquid.groupby("symbol", sort=False):
            scan_symbol(str(sym), g, rows, zone_rule="mid_session", emit_baseline=False)
            scan_symbol(str(sym), g, rows, zone_rule="close_only", emit_baseline=False)
            n_sym += 1
            if n_sym % 100 == 0:
                print(f"  {n_sym} symbols, new signals {len(rows):,}", flush=True)
        print(f"new signals {len(rows):,}", flush=True)
        extra = pd.DataFrame(rows)
        sig = pd.concat([prior, extra], ignore_index=True) if not extra.empty else prior
        sig.to_csv(SIGNALS_CSV, index=False)
    else:
        print(f"scanning {liquid['symbol'].nunique()} symbols...", flush=True)
        rows: list[dict] = []
        n_sym = 0
        for sym, g in liquid.groupby("symbol", sort=False):
            scan_symbol(str(sym), g, rows, zone_rule="as_asked", emit_baseline=True)
            scan_symbol(str(sym), g, rows, zone_rule="ex_last_bar", emit_baseline=False)
            scan_symbol(str(sym), g, rows, zone_rule="mid_session", emit_baseline=False)
            scan_symbol(str(sym), g, rows, zone_rule="close_only", emit_baseline=False)
            n_sym += 1
            if n_sym % 100 == 0:
                print(f"  {n_sym} symbols, signals {len(rows):,}", flush=True)
        print(f"signals collected {len(rows):,}", flush=True)
        sig = pd.DataFrame(rows)
        if not sig.empty:
            sig.to_csv(SIGNALS_CSV, index=False)
    stats = summarize(sig, half_cut)
    judge = _judge(stats)
    write_reports(info, {"n_files": n_files}, hv, stats, judge, half_cut)
    # Console digest for the operator.
    print("--- digest ---", flush=True)
    for s in stats:
        if s["window"] != "full":
            continue
        print(
            f"{s.get('zone_rule','?'):12} {s['pattern']:24} N={s['N']:<3} n={s['signals']:<7} "
            f"avg={_pct(s['avg26']):8} day={_pct(s['day_avg']):8} "
            f"med={_pct(s['med26']):8} exp={_r(s['sym_exp'])}",
            flush=True,
        )
    print("proposed", [(v["pattern"], v.get("zone_rule"), v["N"]) for v in judge["proposed"]], flush=True)
    print("best", judge["best"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
