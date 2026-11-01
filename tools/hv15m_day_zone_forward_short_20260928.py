#!/usr/bin/env python3
"""Short-side mirror of the 15-minute high-volume day-zone forward study.

Research scan only. Does not wire DailyRun and does not claim gold.
Does not touch the long stamp or the live clean-break watch page.

Each long entry rule is inverted: the short signal is the break the other way,
using the same zone construction, carry lengths, and bar exclusions. The fill
is the next 15-minute open. Short profit is (entry - exit) / entry.

Later long-book freezes (age 4-8, morning 09:30-11:00, 20% under the prior
252-day high, 1/2/3/4% stops, same-day cover on the last 15-minute bar) are
extra arms on the short clean break. They do not replace the original grid.
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
sys.path.insert(0, str(ROOT / "tools"))

import hv15m_clean_break_n20_signal_ledger_20260927 as led  # noqa: E402
import hv15m_day_zone_forward_20260925 as base  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_day_zone_forward_short_20260928"
CACHE = STAMP / "cache_15m.parquet"
SIGNALS_CSV = STAMP / "signals.csv"
ONE_MIN = base.ONE_MIN
LONG_SIGNALS = base.SIGNALS_CSV

NS = base.NS
H26 = base.H26
H52 = base.H52
NEAR_PCT = base.NEAR_PCT
FAR_PCT = base.FAR_PCT
MIN_SESSIONS = base.MIN_SESSIONS
MIN_BARS_SESSION = base.MIN_BARS_SESSION
ZONE_R_MIN = base.ZONE_R_MIN
ZONE_R_MAX = base.ZONE_R_MAX
SPRING_BARS = base.SPRING_BARS
ANN_ROR_DAYS = base.ANN_ROR_DAYS
HOLDING_TRADING_DAYS = base.HOLDING_TRADING_DAYS

AGES = (4, 5, 6, 7, 8)
MORNING_TIMES = ("09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00")
STOPS = (0.01, 0.02, 0.03, 0.04)
LATER_N = 20
LATER_RULE = "ex_last_bar"
PCT_FLOOR = 0.20

ORIGINAL_REQUEST = (
    "can we run a full analysis on hv15m starting from scratch to see if there is any "
    "value to any of the systems we explored to selling short? I would like you to "
    "generate the same report you did for longs here: "
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "hv15m_day_zone_forward_20260925/compare.html"
)

PATTERN_ORDER = (
    "reject_lowest",
    "reject_highest",
    "resistance_shelf",
    "spring_highest",
    "clean_break_lowest",
    "floor_stack",
    "baseline_1030",
)

PATTERN_LABEL = {
    "reject_lowest": "Reject lowest zone",
    "reject_highest": "Reject highest zone",
    "resistance_shelf": "Resistance shelf",
    "spring_highest": "Spring off highest zone",
    "clean_break_lowest": "Clean break down of lowest zone",
    "floor_stack": "Floor stack (short into zones below)",
    "baseline_1030": "Baseline: short at 10:30 ET",
}

MIRROR_OF = {
    "reject_lowest": "Reclaim highest zone",
    "reject_highest": "Bounce off lowest zone",
    "resistance_shelf": "Support shelf",
    "spring_highest": "Spring off lowest zone",
    "clean_break_lowest": "Clean break of highest zone",
    "floor_stack": "Ceiling stack (long into zones above)",
    "baseline_1030": "Baseline: buy at 10:30 ET",
}

ORIGIN = "Original day-zone report"
LATER_ORIGIN = "Later study"

ZONE_RULE_LABEL = base.ZONE_RULE_LABEL

HEADWIND = "floor_stack"


def _bkt_label(bucket: int) -> str:
    return base._bkt_label(bucket)


def build_15m(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if CACHE.exists():
        print(f"reading cache {CACHE}", flush=True)
        return pd.read_parquet(CACHE)
    print("resampling 1-minute to 15-minute RTH bars into the short stamp...", flush=True)
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


def _path_short(high, low, close, i0: int, entry: float, stop: float | None, horizon: int):
    """Short path. Profit is a lower price. Adverse stop is above the fill.

    The window includes the fill bar, matching the long study. A same-bar stop
    and target counts as a loss.
    """
    end = i0 + horizon
    if end > len(close) or not np.isfinite(entry) or entry <= 0:
        return None
    h = high[i0:end]
    l = low[i0:end]
    c_end = float(close[end - 1])
    fwd = (entry - c_end) / entry
    path_high = float(np.max(h))
    up = entry * 1.01
    dn = entry * 0.99
    sym_r = None
    sym_win = 0
    for k in range(horizon):
        hit_stop = h[k] >= up
        hit_tgt = l[k] <= dn
        if hit_stop:
            sym_r = -1.0
            sym_win = 0
            break
        if hit_tgt:
            sym_r = 1.0
            sym_win = 1
            break
    if sym_r is None:
        sym_r = (entry - c_end) / (entry * 0.01)
        sym_win = 0
    zone_r = None
    zone_win = 0
    if stop is not None and np.isfinite(stop) and stop > entry:
        risk = stop - entry
        rp = risk / entry
        if ZONE_R_MIN <= rp <= ZONE_R_MAX:
            tgt = entry - risk
            for k in range(horizon):
                hit_stop = h[k] >= stop
                hit_tgt = l[k] <= tgt
                if hit_stop:
                    zone_r = -1.0
                    zone_win = 0
                    break
                if hit_tgt:
                    zone_r = 1.0
                    zone_win = 1
                    break
            if zone_r is None:
                zone_r = (entry - c_end) / risk
                zone_win = 0
    return fwd, sym_r, sym_win, zone_r, zone_win, path_high


def scan_symbol(sym: str, g: pd.DataFrame, rows_out: list, *, zone_rule: str, emit_baseline: bool) -> None:
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
    for s, d in enumerate(good_days):
        m = (day == d) & (sess == s)
        if not np.any(m):
            continue
        idx = np.flatnonzero(m)
        if zone_rule == "ex_last_bar":
            idx = idx[bucket[idx] < 25]
            if len(idx) == 0:
                continue
        vols = v[idx]
        bk = bucket[idx]
        best = idx[int(np.lexsort((bk, -vols))[0])]
        chosen_bkt = int(bucket[best])
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

    eod_of_day: dict = {}
    for j in range(n):
        if int(bucket[j]) == 25:
            eod_of_day[day[j]] = j
    eod_i = np.full(n, -1, dtype=np.int32)
    for j in range(n):
        k = eod_of_day.get(day[j], -1)
        if k >= j:
            eod_i[j] = k

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

    def _emit(pattern, N, j, stop, zone_lo, zone_hi, entry_is_signal_bar=False, rule=None, zone_meta=None):
        entry_i = j if entry_is_signal_bar else j + 1
        if entry_i < 0 or entry_i + H26 > n:
            return
        entry = float(o[entry_i])
        if not np.isfinite(entry) or entry <= 0:
            return
        got = _path_short(h, l, c, entry_i, entry, stop, H26)
        if got is None:
            return
        fwd26, sym_r, sym_win, zone_r, zone_win, path_high = got
        fwd52 = np.nan
        if entry_i + H52 <= n:
            got52 = _path_short(h, l, c, entry_i, entry, None, H52)
            if got52 is not None:
                fwd52 = got52[0]
        k_eod = int(eod_i[entry_i])
        if k_eod >= 0 and np.isfinite(c[k_eod]):
            day_ret = (entry - float(c[k_eod])) / entry
        else:
            day_ret = np.nan
        meta = zone_meta or {}
        rows_out.append(
            {
                "symbol": sym,
                "pattern": pattern,
                "N": int(N),
                "day": pd.Timestamp(day[entry_i]).date().isoformat(),
                "entry": entry,
                "fwd26": fwd26,
                "fwd52": fwd52,
                "sym_r": sym_r,
                "sym_win": sym_win,
                "zone_r": zone_r if zone_r is not None else np.nan,
                "zone_win": zone_win if zone_r is not None else np.nan,
                "stop": stop if stop is not None else np.nan,
                "zone_lo": zone_lo,
                "zone_hi": zone_hi,
                "zone_rule": rule if rule is not None else zone_rule,
                "zone_age": meta.get("zone_age", np.nan),
                "signal_close": meta.get("signal_close", np.nan),
                "signal_day": meta.get("signal_day", pd.Timestamp(day[j]).date().isoformat()),
                "signal_time_et": meta.get("signal_time_et", ""),
                "zone_date": meta.get("zone_date", ""),
                "path_high": path_high,
                "day_ret": day_ret,
                "side": "short",
            }
        )

    for N in NS:
        bounced = np.zeros(S, dtype=np.int8)
        clean_done = np.zeros(S, dtype=np.int8)
        spring_done = np.zeros(S, dtype=np.int8)
        shelf_done = np.zeros(S, dtype=np.int8)
        floor_done = np.zeros(S, dtype=np.int8)
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
            s0 = max(0, s - N)
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

            if n_act == 0 or lo_z < 0 or hi_z < 0:
                setup_z = -1
                spring_z = -1
                continue

            # Mirror of reclaim-highest: break under the lowest zone, come back
            # into the band, then close back under the band. A close above the
            # band's high cancels. If this zone stops being the lowest, cancel.
            if setup_z >= 0:
                alive = bool(valid_zone[setup_z]) and 0 <= (s - setup_z) <= N
                if setup_z == s and b <= int(z_bkt[setup_z]):
                    alive = False
                if (not alive) or lo_z != setup_z:
                    setup_z = -1
                    touched = False
                else:
                    zl = float(z_lo[setup_z])
                    zh = float(z_hi[setup_z])
                    if c[j] > zh:
                        setup_z = -1
                        touched = False
                    else:
                        if l[j] <= zh and h[j] >= zl and j > setup_j:
                            touched = True
                        if touched and c[j] < zl and j > setup_j:
                            _emit(
                                "reject_lowest", N, j, zh, zl, zh,
                                zone_meta=_zmeta(setup_z, j, s),
                            )
                            setup_z = -1
                            touched = False
            if setup_z < 0 and lo_z >= 0 and j > 0:
                zl = float(z_lo[lo_z])
                if c[j] < zl and c[j - 1] >= zl and int(sess[j - 1]) >= 0:
                    setup_z = lo_z
                    setup_j = j
                    touched = False

            # Mirror of clean-break-highest: the whole bar is under the lowest
            # zone (high and close both below the zone low) and the prior close
            # was not. First time per zone. Stop sits at the zone high.
            if lo_z >= 0 and clean_done[lo_z] == 0 and j > 0 and int(sess[j - 1]) >= 0:
                zl = float(z_lo[lo_z])
                zh = float(z_hi[lo_z])
                if h[j] < zl and c[j] < zl and c[j - 1] >= zl:
                    _emit(
                        "clean_break_lowest", N, j, zh, zl, zh,
                        zone_meta=_zmeta(lo_z, j, s),
                    )
                    clean_done[lo_z] = 1

            # Mirror of bounce-off-lowest: a red bar wicks into the highest zone
            # (high inside the band) and closes under it. Needs a different,
            # lower zone too. First time per zone.
            if hi_z >= 0 and hi_z != lo_z and n_act >= 2 and bounced[hi_z] == 0:
                zl = float(z_lo[hi_z])
                zh = float(z_hi[hi_z])
                if zl <= h[j] <= zh and c[j] < zl and c[j] < o[j]:
                    _emit(
                        "reject_highest", N, j, zh, zl, zh,
                        zone_meta=_zmeta(hi_z, j, s),
                    )
                    bounced[hi_z] = 1

            # Mirror of spring-off-lowest: close above the highest zone, then
            # within 8 bars a red bar closes back under that zone's low.
            if spring_z >= 0:
                alive = bool(valid_zone[spring_z]) and 0 <= (s - spring_z) <= N and spring_done[spring_z] == 0
                if spring_z == s and b <= int(z_bkt[spring_z]):
                    alive = False
                if not alive or (j - spring_j) > SPRING_BARS:
                    spring_z = -1
                else:
                    zl = float(z_lo[spring_z])
                    zh = float(z_hi[spring_z])
                    if j > spring_j and c[j] < zl and c[j] < o[j]:
                        _emit(
                            "spring_highest", N, j, zh, zl, zh,
                            zone_meta=_zmeta(spring_z, j, s),
                        )
                        spring_done[spring_z] = 1
                        spring_z = -1
                    elif j > spring_j and c[j] < zl:
                        spring_z = -1
            if spring_z < 0 and hi_z >= 0 and spring_done[hi_z] == 0:
                if c[j] > float(z_hi[hi_z]):
                    spring_z = hi_z
                    spring_j = j

            # Mirror of support shelf: first red bar of the session with at
            # least three zones just overhead and none just underneath.
            if (
                shelf_done[s] == 0
                and c[j] < o[j]
                and n_above_near >= 3
                and n_below == 0
                and nearest_below >= FAR_PCT
                and resist_z >= 0
            ):
                zl = float(z_lo[resist_z])
                zh = float(z_hi[resist_z])
                stop = zh if zh > px else None
                _emit(
                    "resistance_shelf", N, j, stop, zl, zh,
                    zone_meta=_zmeta(resist_z, j, s),
                )
                shelf_done[s] = 1

            # Mirror of the ceiling-stack long. This is a headwind check:
            # shorting into a stack of zones underneath, not a short idea.
            if (
                floor_done[s] == 0
                and c[j] < o[j]
                and n_below >= 3
                and n_above_near == 0
                and nearest_above >= FAR_PCT
                and support_z >= 0
            ):
                zl = float(z_lo[support_z])
                zh = float(z_hi[support_z])
                stop = zh if zh > px else None
                _emit(
                    "floor_stack", N, j, stop, zl, zh,
                    zone_meta=_zmeta(support_z, j, s),
                )
                floor_done[s] = 1

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
                    "baseline_1030", 0, j, None, float("nan"), float("nan"),
                    entry_is_signal_bar=True, rule="baseline",
                )


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


def _stat_row(pattern: str, N: int, zone_rule: str, g: pd.DataFrame, half_cut: str, window: str) -> dict:
    label = PATTERN_LABEL.get(pattern, pattern)
    rule_label = ZONE_RULE_LABEL.get(zone_rule, zone_rule)
    empty = {
        "pattern": pattern,
        "label": label,
        "zone_rule": zone_rule,
        "zone_rule_label": rule_label,
        "mirror_of": MIRROR_OF.get(pattern, ""),
        "origin": ORIGIN,
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
    }
    n = int(len(g))
    if n == 0:
        return empty
    fwd = g["fwd26"].to_numpy(dtype=float)
    order = np.argsort(fwd)
    ex = fwd[order[:-1]] if n > 1 else fwd
    by_day = g.groupby("day")["fwd26"].mean()
    zw = g["zone_r"].dropna()
    avg52 = g["fwd52"].dropna()
    return {
        **empty,
        "signals": n,
        "symbols": int(g["symbol"].nunique()),
        "days": int(g["day"].nunique()),
        "win_pct": float((fwd > 0).mean()),
        "avg26": float(fwd.mean()),
        "med26": float(np.median(fwd)),
        "avg26_exmax": float(ex.mean()),
        "day_avg": float(by_day.mean()),
        "day_med": float(by_day.median()),
        "sym_win_pct": float(g["sym_win"].mean()),
        "sym_exp": float(g["sym_r"].mean()),
        "zone_n": int(len(zw)),
        "zone_win_pct": float((g.loc[zw.index, "zone_win"] == 1).mean()) if len(zw) else None,
        "zone_exp": float(zw.mean()) if len(zw) else None,
        "avg52": float(avg52.mean()) if len(avg52) else None,
    }


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


def _base(stats: list[dict], window: str) -> dict | None:
    for s in stats:
        if s["pattern"] == "baseline_1030" and s["window"] == window:
            return s
    return None


def _pair(stats, s, window):
    for x in stats:
        if (
            x["pattern"] == s["pattern"]
            and x["N"] == s["N"]
            and x["window"] == window
            and x.get("zone_rule") == s.get("zone_rule")
        ):
            return x
    return None


def judge(stats: list[dict]) -> dict:
    """Same quality bar as the long page, against shorting at 10:30.

    The later half can veto a story that fades. It is not used to pick a winner.
    """
    base_full = _base(stats, "full")
    late_base = _base(stats, "late")
    early_base = _base(stats, "early")
    verdicts = []
    for s in stats:
        if s["window"] != "full" or s["pattern"] == "baseline_1030":
            continue
        late = _pair(stats, s, "late")
        early = _pair(stats, s, "early")
        reasons = []
        ok = True
        if base_full is None or s["signals"] < 100 or s["days"] < 12:
            ok = False
            reasons.append("too few signals or days")
        else:
            if s["day_avg"] is None or s["day_avg"] <= base_full["day_avg"] + 0.001:
                ok = False
                reasons.append("day-averaged return does not beat shorting at 10:30 by at least 0.10 percentage points")
            if s["med26"] is None or base_full["med26"] is None or s["med26"] <= base_full["med26"]:
                ok = False
                reasons.append("median trade is not above the 10:30 short baseline median")
            if s["sym_exp"] is None or base_full["sym_exp"] is None or s["sym_exp"] <= base_full["sym_exp"]:
                ok = False
                reasons.append("1% path expectancy is not above the baseline")
            if s["avg26_exmax"] is None or base_full["avg26"] is None or s["avg26_exmax"] <= base_full["avg26"]:
                ok = False
                reasons.append("average without the best trade does not clear the baseline average")
            if s["day_med"] is None or base_full["day_med"] is None or s["day_med"] <= base_full["day_med"]:
                ok = False
                reasons.append("the typical day does not beat shorting at 10:30")
        late_ok = True
        if late and late["signals"] >= 40 and late_base and late["avg26"] is not None:
            if late.get("med26") is None or late["med26"] <= 0:
                late_ok = False
                reasons.append("later half median trade was not a short profit")
            if late.get("sym_exp") is None or late_base.get("sym_exp") is None or late["sym_exp"] <= late_base["sym_exp"]:
                late_ok = False
                reasons.append("later half 1% expectancy did not beat the later baseline")
            if late["avg26"] < 0 and late["avg26"] < (late_base["avg26"] or 0):
                late_ok = False
                reasons.append("later half was negative and worse than the later baseline")
            if late["day_avg"] is not None and late_base["day_avg"] is not None:
                if late["day_avg"] + 0.0005 < late_base["day_avg"]:
                    late_ok = False
                    reasons.append("later half lost the edge versus shorting at 10:30")
        if not late_ok:
            ok = False
        kind = "candidate" if ok and s["pattern"] != HEADWIND else "not_proposed"
        if s["pattern"] == HEADWIND:
            kind = "headwind_check"
        if s["signals"] < 30:
            kind = "empty_or_thin"
        verdicts.append(
            {
                **s,
                "propose": bool(ok and s["pattern"] != HEADWIND),
                "kind": kind,
                "reasons": reasons,
                "late_signals": late["signals"] if late else 0,
                "late_avg26": late["avg26"] if late else None,
                "late_med26": late["med26"] if late else None,
                "late_day_avg": late["day_avg"] if late else None,
                "early_avg26": early["avg26"] if early else None,
                "early_signals": early["signals"] if early else 0,
                "excess_day_avg": (
                    (s["day_avg"] - base_full["day_avg"])
                    if base_full and s["day_avg"] is not None and base_full["day_avg"] is not None
                    else None
                ),
            }
        )
    proposed = [v for v in verdicts if v["propose"]]
    best = None
    if proposed:
        top = max(proposed, key=lambda v: (v["excess_day_avg"] or -1e9, v["sym_exp"] or -1e9))
        best = {
            "pattern": top["pattern"],
            "label": top["label"],
            "zone_rule": top.get("zone_rule"),
            "N": top["N"],
            "excess_day_avg": top["excess_day_avg"],
            "note": "in-sample selection on this short window; not adopted",
        }
    return {
        "verdicts": verdicts,
        "proposed": proposed,
        "best": best,
        "baseline": base_full,
        "late_baseline": late_base,
        "early_baseline": early_base,
    }


def attach_252(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        out = df.copy()
        out["pct_below_252d_high_at_signal_close"] = []
        return out
    symbols = sorted(df["symbol"].astype(str).str.upper().unique())
    daily = led.load_daily(symbols)
    pcts = []
    for rec in df.itertuples(index=False):
        pack = daily.get(str(rec.symbol).upper())
        close = float(rec.signal_close) if rec.signal_close == rec.signal_close else float("nan")
        if not pack or not rec.signal_day:
            pcts.append(np.nan)
            continue
        i = led._prior_index(pack["day"], rec.signal_day)
        hi, _hi_date, n = led._window_high(pack["day"], pack["high"], i + 1, led.YEAR_BARS, None)
        if n < led.MIN_YEAR_BARS:
            hi = float("nan")
        pcts.append(led._pct_below(hi, close))
    out = df.copy()
    out["pct_below_252d_high_at_signal_close"] = pcts
    return out


def _book_stats(g: pd.DataFrame, ret: np.ndarray, half_cut: str) -> dict:
    n = int(len(g))
    if n == 0 or len(ret) != n:
        return {
            "n": 0, "win": None, "avg": None, "med": None, "day_avg": None,
            "early_n": 0, "early_avg": None, "late_n": 0, "late_avg": None,
        }
    days = g["day"].to_numpy()
    by = pd.Series(ret, index=g.index).groupby(g["day"]).mean()
    early = ret[days < half_cut]
    late = ret[days >= half_cut]
    return {
        "n": n,
        "win": float((ret > 0).mean()),
        "avg": float(np.mean(ret)),
        "med": float(np.median(ret)),
        "day_avg": float(by.mean()) if len(by) else None,
        "early_n": int(len(early)),
        "early_avg": float(np.mean(early)) if len(early) else None,
        "late_n": int(len(late)),
        "late_avg": float(np.mean(late)) if len(late) else None,
    }


def _stopped(g: pd.DataFrame, stop: float) -> np.ndarray:
    entry = g["entry"].to_numpy(dtype=float)
    path_high = g["path_high"].to_numpy(dtype=float)
    fwd = g["fwd26"].to_numpy(dtype=float)
    hit = path_high >= entry * (1.0 + stop) - 1e-9
    return np.where(hit, -stop, fwd)


def later_frames(sig: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, pd.DataFrame]]]:
    book = sig[
        (sig["pattern"] == "clean_break_lowest")
        & (sig["zone_rule"] == LATER_RULE)
        & (sig["N"] == LATER_N)
    ].copy()
    book = attach_252(book)
    age = book["zone_age"].isin(AGES)
    morning = book["signal_time_et"].astype(str).isin(MORNING_TIMES)
    pct = book["pct_below_252d_high_at_signal_close"] >= PCT_FLOOR
    book["in_age"] = age
    book["in_morning"] = morning
    book["in_pct20"] = pct
    book["in_freeze"] = age & morning & pct
    arms = [
        ("Unfiltered clean break down (exclude 15:45, carry 20)", book),
        ("Zone age 4 to 8 only", book[age]),
        ("Trigger 09:30 through 11:00 only", book[morning]),
        ("At least 20% below the prior 252-day high only", book[pct]),
        ("Age 4 to 8 and morning 09:30-11:00", book[age & morning]),
        ("Combined freeze: age 4-8, morning, and 20% or more below", book[age & morning & pct]),
    ]
    return book, arms


def sanity_check(sig: pd.DataFrame) -> dict:
    """Short 10:30 return should negate the long 10:30 return on shared fills."""
    out = {"checked": False}
    if not LONG_SIGNALS.exists() or sig.empty:
        out["note"] = "long signals file missing or short book empty"
        return out
    use = ["pattern", "symbol", "day", "entry", "fwd26"]
    long = pd.read_csv(LONG_SIGNALS, usecols=use)
    long = long[long["pattern"] == "baseline_1030"]
    short = sig[sig["pattern"] == "baseline_1030"][use].copy()
    long["day"] = long["day"].astype(str).str.slice(0, 10)
    short["day"] = short["day"].astype(str).str.slice(0, 10)
    m = short.merge(long, on=["symbol", "day"], suffixes=("_s", "_l"))
    if m.empty:
        out["note"] = "no shared 10:30 rows with the long signals file"
        return out
    gap = (m["fwd26_s"] + m["fwd26_l"]).abs()
    entry_gap = (m["entry_s"] - m["entry_l"]).abs()
    out.update(
        {
            "checked": True,
            "shared_rows": int(len(m)),
            "short_only_rows": int(len(short) - len(m)),
            "max_abs_entry_gap": float(entry_gap.max()),
            "max_abs_return_sum": float(gap.max()),
            "median_abs_return_sum": float(gap.median()),
        }
    )
    return out


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def _td(val: str) -> str:
    return f"<td>{val}</td>"


SORT_JS = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+ppR]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var body = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    body.sort(function (a, b) {
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
    body.forEach(function (r) { tbody.appendChild(r); });
    pinned.forEach(function (r) { tbody.appendChild(r); });
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


def _arm_row(label: str, st: dict, origin: str) -> str:
    return (
        "<tr>"
        + _td(html.escape(origin))
        + _td(html.escape(label))
        + _td(str(st["n"]))
        + _td(_pct(st["win"]))
        + _td(_pct(st["avg"]))
        + _td(_ann(st["avg"]))
        + _td(_pct(st["med"]))
        + _td(_pct(st["day_avg"]))
        + _td(str(st["early_n"]))
        + _td(_pct(st["early_avg"]))
        + _td(str(st["late_n"]))
        + _td(_pct(st["late_avg"]))
        + "</tr>"
    )


def write_reports(
    info: dict,
    n_files: int,
    hv: pd.DataFrame,
    stats: list[dict],
    judged: dict,
    half_cut: str,
    book: pd.DataFrame,
    arms: list[tuple[str, pd.DataFrame]],
    sanity: dict,
) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    base_full = judged["baseline"] or {}
    date_min = info.get("date_min", "")
    date_max = info.get("date_max", "")

    rule_order = {"baseline": 0, "as_asked": 1, "ex_last_bar": 2, "mid_session": 3, "close_only": 4}

    def sort_key(s):
        try:
            pi = PATTERN_ORDER.index(s["pattern"])
        except ValueError:
            pi = 99
        return (rule_order.get(s.get("zone_rule"), 9), pi, s["N"])

    full = sorted([s for s in stats if s["window"] == "full"], key=sort_key)

    body = []
    for s in full:
        nshow = "—" if s["pattern"] == "baseline_1030" else str(s["N"])
        body.append(
            "<tr>"
            + _td(html.escape(s["label"]))
            + _td(html.escape(MIRROR_OF.get(s["pattern"], "")))
            + _td(html.escape(s.get("zone_rule_label") or ""))
            + _td(nshow)
            + _td(str(s["signals"]))
            + _td(str(s["symbols"]))
            + _td(str(s["days"]))
            + _td(_pct(s["win_pct"]))
            + _td(_pct(s["avg26"]))
            + _td(_ann(s["avg26"]))
            + _td(_pct(s["med26"]))
            + _td(_pct(s["avg26_exmax"]))
            + _td(_pct(s["day_avg"]))
            + _td(_pct(s["day_med"]))
            + _td(_pct(s["avg52"]))
            + "</tr>"
        )

    rbody = []
    for s in full:
        nshow = "—" if s["pattern"] == "baseline_1030" else str(s["N"])
        rbody.append(
            "<tr>"
            + _td(html.escape(s["label"]))
            + _td(html.escape(s.get("zone_rule_label") or ""))
            + _td(nshow)
            + _td(str(s["signals"]))
            + _td(_pct(s["sym_win_pct"]))
            + _td(_r(s["sym_exp"]))
            + _td(str(s["zone_n"]))
            + _td(_pct(s["zone_win_pct"]))
            + _td(_r(s["zone_exp"]))
            + "</tr>"
        )

    hbody = []
    for s in full:
        if s["pattern"] == "baseline_1030":
            early = next((x for x in stats if x["pattern"] == "baseline_1030" and x["window"] == "early"), None)
            late = next((x for x in stats if x["pattern"] == "baseline_1030" and x["window"] == "late"), None)
        else:
            early = _pair(stats, s, "early")
            late = _pair(stats, s, "late")
        nshow = "—" if s["pattern"] == "baseline_1030" else str(s["N"])
        hbody.append(
            "<tr>"
            + _td(html.escape(s["label"]))
            + _td(html.escape(s.get("zone_rule_label") or ""))
            + _td(nshow)
            + _td(str(early["signals"] if early else 0))
            + _td(_pct(early["avg26"] if early else None))
            + _td(_ann(early["avg26"] if early else None))
            + _td(_pct(early["day_avg"] if early else None))
            + _td(str(late["signals"] if late else 0))
            + _td(_pct(late["avg26"] if late else None))
            + _td(_ann(late["avg26"] if late else None))
            + _td(_pct(late["day_avg"] if late else None))
            + "</tr>"
        )

    mid_rows = []
    for pattern in PATTERN_ORDER:
        if pattern == "baseline_1030":
            continue
        for n in NS:
            def pick(rule, p=pattern, nn=n):
                for s in full:
                    if s["pattern"] == p and s["N"] == nn and s["zone_rule"] == rule:
                        return s
                return None
            mid = pick("mid_session")
            asked = pick("as_asked")
            close = pick("close_only")
            delta = None
            if mid and asked and mid["avg26"] is not None and asked["avg26"] is not None:
                delta = mid["avg26"] - asked["avg26"]
            mid_rows.append(
                "<tr>"
                + _td(html.escape(PATTERN_LABEL[pattern]))
                + _td(str(n))
                + _td(str(mid["signals"] if mid else 0))
                + _td(_pct(mid["avg26"] if mid else None))
                + _td(_ann(mid["avg26"] if mid else None))
                + _td(_pct(asked["avg26"] if asked else None))
                + _td(_pct(close["avg26"] if close else None))
                + _td(_pct(delta))
                + "</tr>"
            )

    later_rows = []
    later_stats = []
    for label, frame in arms:
        st = _book_stats(frame, frame["fwd26"].to_numpy(dtype=float) if len(frame) else np.array([]), half_cut)
        later_stats.append((label, st))
        later_rows.append(_arm_row(label + " — next session", st, LATER_ORIGIN))
        day_frame = frame[frame["day_ret"].notna()] if len(frame) else frame
        st_day = _book_stats(day_frame, day_frame["day_ret"].to_numpy(dtype=float) if len(day_frame) else np.array([]), half_cut)
        later_stats.append((label + " day trade", st_day))
        later_rows.append(_arm_row(label + " — cover at 15:45 close", st_day, LATER_ORIGIN))

    stop_rows = []
    stop_stats = []
    stop_books = [
        ("Unfiltered clean break down", arms[0][1] if arms else book.iloc[0:0]),
        ("Combined freeze", arms[-1][1] if arms else book.iloc[0:0]),
    ]
    for book_name, frame in stop_books:
        for stop in STOPS:
            if len(frame) == 0:
                ret = np.array([])
            else:
                ret = _stopped(frame, stop)
            st = _book_stats(frame, ret, half_cut)
            hit = None
            if len(frame):
                entry = frame["entry"].to_numpy(dtype=float)
                path_high = frame["path_high"].to_numpy(dtype=float)
                hit = int((path_high >= entry * (1.0 + stop) - 1e-9).sum())
            stop_stats.append((book_name, stop, st, hit))
            stop_rows.append(
                "<tr>"
                + _td(html.escape(book_name))
                + _td(_pct(stop, 0))
                + _td(str(st["n"]))
                + _td(str(hit if hit is not None else 0))
                + _td(_pct(st["win"]))
                + _td(_pct(st["avg"]))
                + _td(_ann(st["avg"]))
                + _td(_pct(st["med"]))
                + _td(_pct(st["day_avg"]))
                + _td(_pct(st["early_avg"]))
                + _td(_pct(st["late_avg"]))
                + "</tr>"
            )

    hv_body = []
    if hv is not None and not hv.empty:
        for rec in hv.itertuples(index=False):
            hv_body.append(
                "<tr>"
                + _td(html.escape(str(rec.time_et)))
                + _td(str(int(rec.sessions)))
                + _td(_pct(float(rec.pct)))
                + "</tr>"
            )

    proposed = judged["proposed"]
    if not proposed:
        verdict_plain = (
            "HOLD. No short idea beat simply shorting at 10:30 Eastern Time on the quality checks "
            "this page uses (day-averaged return, the typical day, the median trade, the average with "
            "the best trade removed, and the 1% path), with the later half of this window still in "
            "agreement. There is no short edge in the original zone shapes, and the later filters "
            "(age, morning, distance under the yearly high, tighter stops, same-day cover) are not "
            "adopted either. A row that looks better after you have already seen this table would be "
            "in-sample selection. It is not a system."
        )
        verdict_kind = "HOLD / no short edge"
    else:
        names = ", ".join(
            f"{p['label']} ({p.get('zone_rule_label') or ''}, carry {p['N']})"
            for p in proposed
        )
        verdict_plain = (
            "HOLD for trading. A few short rows cleared the same research bar the long page used versus "
            f"shorting at 10:30: {names}. Naming the best one after reading this table is in-sample "
            "selection on a short 2026 window. It is not gold, not DailyRun, and not a reason to pick "
            "a carry length or a filter. The later half is a short-sample check, reported only, and was "
            "not used to choose a winner."
        )
        verdict_kind = "HOLD — research bar touched, nothing adopted"

    b_avg = base_full.get("avg26")
    b_med = base_full.get("med26")
    b_n = base_full.get("signals")
    b_win = base_full.get("win_pct")
    early_b = judged.get("early_baseline") or {}
    late_b = judged.get("late_baseline") or {}

    # Later-filter quality versus the unfiltered short and versus 10:30.
    later_notes = []
    unfiltered = later_stats[0][1] if later_stats else None
    combined = None
    for label, st in later_stats:
        if label.startswith("Combined freeze") and "day trade" not in label:
            combined = st
    if unfiltered and combined and base_full:
        beat_base = (
            combined["day_avg"] is not None
            and base_full.get("day_avg") is not None
            and combined["day_avg"] > base_full["day_avg"] + 0.001
            and combined["med"] is not None
            and base_full.get("med26") is not None
            and combined["med"] > base_full["med26"]
            and combined["avg"] is not None
            and combined["avg"] > 0
        )
        beat_raw = (
            combined["avg"] is not None
            and unfiltered["avg"] is not None
            and combined["avg"] > unfiltered["avg"]
        )
        later_notes.append(
            "Unfiltered short clean break (exclude the 15:45 bar, carry 20): "
            f"N={unfiltered['n']}, win {_pct(unfiltered['win'])}, average {_pct(unfiltered['avg'])}, "
            f"median {_pct(unfiltered['med'])}."
        )
        later_notes.append(
            "Combined later freeze on that same short (zone age 4 to 8, trigger from 09:30 through 11:00 "
            "including 11:00, close at least 20% under the prior 252-trading-day high): "
            f"N={combined['n']}, win {_pct(combined['win'])}, average {_pct(combined['avg'])}, "
            f"median {_pct(combined['med'])}."
        )
        if not beat_base or not beat_raw or combined["n"] < 30:
            later_notes.append(
                "That freeze does not clear a higher bar than the unfiltered short and the 10:30 short "
                "together. It is not a winner. The gates were already chosen on the long book, so any "
                "prettier row here is in-sample selection."
            )
        else:
            later_notes.append(
                "The combined freeze’s average and median are above the unfiltered short and above "
                "shorting at 10:30 on this sample. That comparison was made after seeing the table, and "
                "the gates were chosen on the long book first. Label: in-sample selection. Not adopted. "
                "Not gold. Not DailyRun."
            )

    showed = []
    showed.append(
        f"<li>Short at 10:30 Eastern Time, no zone: {b_n} signals, win {_pct(b_win)}, "
        f"average next-session short return {_pct(b_avg)} (AnnRoR {_ann(b_avg)}), median {_pct(b_med)}. "
        f"Before {html.escape(half_cut)}: average {_pct(early_b.get('avg26'))} on {early_b.get('signals', 0)} signals. "
        f"On or after {html.escape(half_cut)}: average {_pct(late_b.get('avg26'))} on {late_b.get('signals', 0)} signals.</li>"
    )
    showed.append(
        "<li>The long page’s 10:30 buy, on its published window 2026-07-23 through 2026-09-24, averaged "
        "about 0.00% over the next session (32,842 signals). That figure is cited from the long report. "
        "It was not recomputed here. A short of that same clock print is the baseline on this page.</li>"
    )
    for line in later_notes:
        showed.append(f"<li>{html.escape(line)}</li>")
    if sanity.get("checked"):
        showed.append(
            "<li>Check against the long baseline fills that share a symbol and day: "
            f"{sanity['shared_rows']} rows. The largest gap between the short return and the negative of "
            f"the long return was {sanity['max_abs_return_sum']:.2e}. "
            f"Largest entry-price gap was {sanity['max_abs_entry_gap']:.2e}. "
            f"Short-only baseline rows (days the long file does not have): {sanity['short_only_rows']}.</li>"
        )
    else:
        showed.append(
            f"<li>Long-baseline cross-check: {html.escape(str(sanity.get('note', 'not run')))}.</li>"
        )

    open_share = float("nan")
    close_share = float("nan")
    if hv is not None and not hv.empty:
        total = float(hv["sessions"].sum())
        if total > 0:
            def _share(label):
                hit = hv[hv["time_et"] == label]
                return float(hit["sessions"].sum()) / total if len(hit) else 0.0
            open_share = _share("09:30")
            close_share = _share("15:45")

    glossary = "".join(
        f"<li><strong>{html.escape(PATTERN_LABEL[p])}</strong> — short mirror of the long pattern "
        f"“{html.escape(MIRROR_OF[p])}”. From the original day-zone report.</li>"
        for p in PATTERN_ORDER
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>15-minute high-volume day zone — short side</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1180px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.callout.hold {{ border-left-color: #b45309; background: #fffbeb; }}
.note {{ color: #334155; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 8px 8px; }}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
table.mid th:nth-child(3), table.mid td:nth-child(3) {{ text-align: right; }}
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
<h1>15-minute high-volume day zone — selling short</h1>
<p class="note">Research scan only. Not gold. Not wired into DailyRun. Not the daily Volume Zone (VZ) system. Bars: {html.escape(str(date_min))} through {html.escape(str(date_max))}. Liquid symbols: {info.get('symbols_liquid', '—')}. Verdict: {html.escape(verdict_kind)}.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ORIGINAL_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>We rebuilt the 15-minute high-volume study from the 1-minute bars and asked whether any of those buy ideas are worth selling short instead. A short makes money when the price falls. The fair comparison is simply shorting at 10:30 Eastern Time with no zone at all, because a falling market can look like a short edge on a sample this short.</p>
<p>Each day we draw a band from the low to the high of that day’s busiest 15-minute candle (the highest-volume 15-minute bar, Regular Trading Hours only). We keep the band for 5, 8, 10, or 20 trading days. Where the long study bought a move above the top band, this study sells a move below the bottom band, and the other shapes are flipped the same way. The fill is the next 15-minute bar’s open. Profit is the entry price minus the later price, divided by the entry price.</p>
<p>Annualized rate of return (AnnRoR) beside an average is that one-session average multiplied by 252. It scales the one-day move. It is not compound growth and not a yearly portfolio return. A large AnnRoR does not change the verdict.</p>
<p>The original day-zone report supplies the pattern grid. Later studies add extra arms on one short only: a clean break down, with the 15:45 bar left out of the zone, carried 20 trading days, then filtered by zone age, a morning trigger, and distance under the prior 252-day high, plus 1%, 2%, 3%, and 4% stops and a same-day cover. Those extras are labeled “Later study”. They do not replace the grid. A 3% stop was a research exit on the long filter. It was not DailyRun and not gold. The short stops are research only too.</p>
</div>

<div class="callout hold">
<h2 style="margin-top:0">Verdict</h2>
<p>{html.escape(verdict_plain)}</p>
</div>

<h2>What showed up</h2>
<ul>
{''.join(showed)}
</ul>
<p class="note">Click column headers to sort. A short profit means the later price was below the fill. Returns are from the fill to the close 26 fifteen-minute bars later (about one regular session) unless a column says 52 bars or a same-day cover. “Day-avg” is the average of each calendar day’s average return, so one market day weighs once. The 1% path counts a same-bar stop and target as a loss. Zone-edge R uses a stop at the zone high (above the fill) and drops trades whose risk is under 0.10% or over 8% of price. The house in-sample / out-of-sample split at 2024-01-01 cannot be used: this 15-minute store begins on {html.escape(str(date_min))}.</p>

<h2>Which arm came from where</h2>
<ul>
{glossary}
<li><strong>Later filters, stops, and the same-day cover</strong> — extra arms on the short clean break only. Zone source “exclude the 15:45 close bar”, carry 20. From the later highest-volume 15-minute studies (age and distance under the 252-day high, the morning window, the 1/2/3/4% stop grid, and the last-15-minute day trade). Not a silent replacement of the grid above.</li>
</ul>

<h2>Pattern results (full window)</h2>
<table class="sortable">
<caption>Short mirror of each long pattern, by zone source and carry length. Research scan, not a sleeve compare. Click column headers to sort.</caption>
<thead><tr>
{_th("Pattern", "text")}
{_th("Long pattern it mirrors", "text")}
{_th("Zone source", "text")}
{_th("Carry N (trading days)", "num")}
{_th("Signals", "num")}
{_th("Symbols", "num")}
{_th("Days", "num")}
{_th("Win % (price fell)", "num")}
{_th("Avg 26-bar", "num")}
{_th("AnnRoR", "num")}
{_th("Median 26-bar", "num")}
{_th("Avg ex-best", "num")}
{_th("Day-avg", "num")}
{_th("Day-median", "num")}
{_th("Avg 52-bar", "num")}
</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>

<h2>1% path and zone-edge R</h2>
<p class="note">On the long page this block was “+1% before −1%”: did price rise 1% before it fell 1%. For a short, the mirror is “−1% before +1%”: did price fall 1% (a profit) before it rose 1% (the stop). If both happen on the same bar, it counts as a loss. If neither happens, the result is the ending short move divided by 1%. Zone-edge R puts the stop at the zone high and a target one times that risk below the fill.</p>
<table class="sortable">
<caption>Minus 1% before plus 1% is comparable across patterns and the baseline. Zone-edge R is only for signals with a usable stop above the fill. Click column headers to sort.</caption>
<thead><tr>
{_th("Pattern", "text")}
{_th("Zone source", "text")}
{_th("Carry N", "num")}
{_th("Signals", "num")}
{_th("−1% before +1% win %", "num")}
{_th("1% expectancy (R)", "num")}
{_th("Zone-edge n", "num")}
{_th("Zone-edge win %", "num")}
{_th("Zone-edge expectancy (R)", "num")}
</tr></thead>
<tbody>
{''.join(rbody)}
</tbody>
</table>

<h2>Follow-up: mid-session zones</h2>
<div class="callout">
<h2 style="margin-top:0">What you asked (follow-up on the long page)</h2>
<p>The long study also asked whether zones that were not the last bar of the day and not the first bar behaved differently. This section repeats that check on the short mirrors. Mid-session means the day’s true busiest 15-minute candle is kept only when it is not the 09:30 bar and not the 15:45 bar. Close-only keeps the zone only when the 15:45 bar really is the busiest.</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>“Mid minus full” is the mid-session average short return minus the original full-set average, over the same 26 bars. A positive number means the mid-session zones were better shorts. It is a sensitivity, not a new system.</p>
</div>
<table class="sortable mid">
<caption>Mid-session zones versus the full set and versus close-only zones. Research scan, not a sleeve compare. Click column headers to sort.</caption>
<thead><tr>
{_th("Pattern", "text")}
{_th("Carry N", "num")}
{_th("Mid signals", "num")}
{_th("Mid avg", "num")}
{_th("Mid AnnRoR", "num")}
{_th("Full-set avg", "num")}
{_th("Close-only avg", "num")}
{_th("Mid minus full", "num")}
</tr></thead>
<tbody>
{''.join(mid_rows)}
</tbody>
</table>

<h2>Early window vs later window</h2>
<p class="note">This is a short-sample check inside this tape only: entry before {html.escape(half_cut)} versus on or after {html.escape(half_cut)}. It is the midpoint of the calendar dates in the liquid set, the same method the long page used (that page’s cut was 2026-08-24). It is not the house in-sample / out-of-sample cut at 2024-01-01. The store has no bars before {html.escape(str(date_min))}. The later half is report-only. It is not a reason to pick a winner. On the long page a fading later half could only veto a story. It was not used to retune.</p>
<table class="sortable">
<caption>Same short patterns, split by entry date. Click column headers to sort.</caption>
<thead><tr>
{_th("Pattern", "text")}
{_th("Zone source", "text")}
{_th("Carry N", "num")}
{_th("Early signals", "num")}
{_th("Early avg", "num")}
{_th("Early AnnRoR", "num")}
{_th("Early day-avg", "num")}
{_th("Late signals", "num")}
{_th("Late avg", "num")}
{_th("Late AnnRoR", "num")}
{_th("Late day-avg", "num")}
</tr></thead>
<tbody>
{''.join(hbody)}
</tbody>
</table>

<h2>Later studies, on the short clean break</h2>
<p>These arms use one book: clean break down of the lowest zone, zone taken from the busiest 15-minute candle that starts before 15:45, carried 20 trading days. That matches the freeze the later long studies used, flipped to a short. Age is how many trading sessions have passed since the zone was born (4, 5, 6, 7, or 8). Morning means the signal candle starts at 09:30, 09:45, 10:00, 10:15, 10:30, 10:45, or 11:00 Eastern. The 11:00 candle counts. Distance under the prior 252-day high is (highest daily high of the 252 trading days strictly before the signal date, minus the signal candle’s close) divided by that high. At least 20% below means that result is 0.20 or larger. A missing yearly high does not pass. The same-day cover sells the short at the close of the entry day’s last 15-minute bar (15:45–16:00). If the signal itself is the 15:45 bar, the short starts at the next morning’s open and covers that same day’s 15:45 close.</p>
<table class="sortable">
<caption>Later filters and the same-day cover. Next session is the close 26 bars after the fill. Click column headers to sort.</caption>
<thead><tr>
{_th("From", "text")}
{_th("Arm", "text")}
{_th("N", "num")}
{_th("Win %", "num")}
{_th("Avg", "num")}
{_th("AnnRoR", "num")}
{_th("Median", "num")}
{_th("Day-avg", "num")}
{_th("Early N", "num")}
{_th("Early avg", "num")}
{_th("Late N", "num")}
{_th("Late avg", "num")}
</tr></thead>
<tbody>
{''.join(later_rows)}
</tbody>
</table>

<h2>Stops of 1%, 2%, 3%, and 4% above the fill</h2>
<p class="note">A long stop of X% below the entry becomes a short stop of X% above the entry. If any high in the 26-bar window reaches the fill times (1+X), the short is closed at exactly that loss. Otherwise the result stays the next-session short return. This is the same extreme-in-the-window treatment the long stop grid used, pointed the other way. The 3% row is a research exit, not DailyRun and not gold.</p>
<table class="sortable">
<caption>Stop grid on the unfiltered short clean break and on the combined later freeze. Click column headers to sort.</caption>
<thead><tr>
{_th("Book", "text")}
{_th("Stop", "num")}
{_th("N", "num")}
{_th("Stopped", "num")}
{_th("Win %", "num")}
{_th("Avg with stop", "num")}
{_th("AnnRoR with stop", "num")}
{_th("Median with stop", "num")}
{_th("Day-avg", "num")}
{_th("Early avg", "num")}
{_th("Late avg", "num")}
</tr></thead>
<tbody>
{''.join(stop_rows)}
</tbody>
</table>

<h2>When the highest-volume candle prints</h2>
<p>Share of liquid complete sessions whose busiest 15-minute candle is the 15:45 bar: {_pct(close_share)}. The 09:30 bar is {_pct(open_share)}. Closing auctions pile volume into that final candle, so the zone as asked is often the close. The primary grid still uses that candle, because the long study did. A labeled pass drops the 15:45 bar when choosing the zone.</p>
<table class="sortable">
<caption>Liquid complete sessions. Clock time is the start of the 15-minute bar, US/Eastern. Click column headers to sort.</caption>
<thead><tr>
{_th("Time ET", "text")}
{_th("Sessions", "num")}
{_th("Share", "num")}
</tr></thead>
<tbody>
{''.join(hv_body)}
</tbody>
</table>

<h2>Definitions</h2>
<ul>
<li><strong>Bars.</strong> Regular Trading Hours, 09:30–16:00 US/Eastern. Fifteen-minute candles are resampled from the stored 1-minute bars. The 09:30 bar covers 09:30–09:44. A 15-minute bar needs at least 10 one-minute prints.</li>
<li><strong>Zone.</strong> One band per symbol per session: low to high of the highest-volume 15-minute candle. A volume tie keeps the earlier bar. A band thinner than 0.05% of its midpoint is skipped. The band is known only after that candle closes. It stays active through N later trading sessions. N is 5, 8, 10, and 20, a sensitivity grid, not four systems.</li>
<li><strong>Zone sources.</strong> As asked (the 15:45 bar may be the zone). Exclude the 15:45 close bar (use the busiest earlier candle). Mid-session only (drop the day if the true busiest bar is 09:30 or 15:45). Close bar only (keep the day only when 15:45 is the busiest).</li>
<li><strong>Short return.</strong> (entry − exit) / entry. Entry is the next 15-minute open after the signal bar. The baseline shorts the open of the 10:30 bar itself. The 26-bar window starts on the fill bar and ends at the close of the 26th bar. The 52-bar window is the same idea when those bars exist. Signals without 26 bars ahead are dropped, same as the long study.</li>
<li><strong>Stops.</strong> The symmetric 1% path stops the short if price trades 1% above the fill before it trades 1% below. The zone-edge stop is the zone high. The 1/2/3/4% grid exits at exactly +X% above the fill when the window’s high reaches that price. Same-bar stop and target is a loss on the path scores.</li>
<li><strong>Universe.</strong> At least {MIN_SESSIONS} sessions with at least {MIN_BARS_SESSION} valid 15-minute bars, median session dollar volume at least $1,000,000, median close at least $5. Same gates as the long study.</li>
<li><strong>Not claimed.</strong> Not gold. Not DailyRun. No portfolio, no position cap, no fees, no slippage beyond the next open. AnnRoR is not an equity-curve annualized rate of return. No Simple Moving Average is used. In-sample / out-of-sample at 2024-01-01 is impossible on this store.</li>
</ul>
<p class="note">Volume Zone (VZ) in this note means the existing daily high-volume zone system. This page does not rerun it. Average True Range is not used. Long trade signs were not reused. Each short was recomputed from the 15-minute bars.</p>
</body>
<!--SORT-->
</html>
"""
    page = page.replace("<!--SORT-->", SORT_JS)
    (STAMP / "compare.html").write_text(page, encoding="utf-8")

    # Headline numbers for the stamp notes.
    lines = []
    for s in full:
        nshow = "—" if s["pattern"] == "baseline_1030" else str(s["N"])
        lines.append(
            f"- {s['label']} [{s.get('zone_rule_label')}] N={nshow}: "
            f"signals={s['signals']}; win={_pct(s['win_pct'])}; avg={_pct(s['avg26'])}; "
            f"median={_pct(s['med26'])}; day-avg={_pct(s['day_avg'])}; "
            f"AnnRoR={_ann(s['avg26'])}; early={_pct(s.get('avg26') and None)}; "
            f"kind note in compare.html."
        )
    # Fix early/late into the baseline notes properly below.
    result_lines = []
    for s in full:
        early = _pair(stats, s, "early") if s["pattern"] != "baseline_1030" else next(
            (x for x in stats if x["pattern"] == "baseline_1030" and x["window"] == "early"), None
        )
        late = _pair(stats, s, "late") if s["pattern"] != "baseline_1030" else next(
            (x for x in stats if x["pattern"] == "baseline_1030" and x["window"] == "late"), None
        )
        # baseline early/late doesn't carry zone_rule pairing via _pair if window filter... 
        if s["pattern"] == "baseline_1030":
            early = next((x for x in stats if x["pattern"] == "baseline_1030" and x["window"] == "early"), None)
            late = next((x for x in stats if x["pattern"] == "baseline_1030" and x["window"] == "late"), None)
        nshow = "—" if s["pattern"] == "baseline_1030" else str(s["N"])
        result_lines.append(
            f"- {s['label']} [{s.get('zone_rule_label')}] N={nshow}: "
            f"N={s['signals']}; win={_pct(s['win_pct'])}; avg={_pct(s['avg26'])}; "
            f"median={_pct(s['med26'])}; day-avg={_pct(s['day_avg'])}; AnnRoR={_ann(s['avg26'])}; "
            f"early avg={_pct(early['avg26'] if early else None)} on {early['signals'] if early else 0}; "
            f"late avg={_pct(late['avg26'] if late else None)} on {late['signals'] if late else 0}."
        )

    later_md = []
    for label, st in later_stats:
        later_md.append(
            f"- {label}: N={st['n']}; win={_pct(st['win'])}; avg={_pct(st['avg'])}; "
            f"median={_pct(st['med'])}; AnnRoR={_ann(st['avg'])}; "
            f"early={_pct(st['early_avg'])} (n={st['early_n']}); late={_pct(st['late_avg'])} (n={st['late_n']})."
        )
    stop_md = []
    for book_name, stop, st, hit in stop_stats:
        stop_md.append(
            f"- {book_name}, stop {_pct(stop, 0)}: N={st['n']}; stopped={hit}; "
            f"win={_pct(st['win'])}; avg={_pct(st['avg'])}; median={_pct(st['med'])}; AnnRoR={_ann(st['avg'])}."
        )

    proposed_md = "None. No short pattern cleared the bar versus shorting at 10:30."
    if proposed:
        proposed_md = "\n".join(
            f"- {p['label']} [{p.get('zone_rule_label')}] N={p['N']} cleared the research bar on this sample. "
            "In-sample selection. Not adopted."
            for p in proposed
        )

    baseline_md = f"""# 15-minute high-volume day zone — short side

Study id: `hv15m_day_zone_forward_short_20260928`

This is a from-scratch short mirror of `hv15m_day_zone_forward_20260925`. It is not gold. It is not wired into DailyRun. It does not change the long stamp or the live watch page.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

Each long buy shape from the highest-volume 15-minute day-zone study is flipped into a short. A short makes money if price falls. Bands are built the same way, from the busiest 15-minute candle of each day, and carried for 5, 8, 10, or 20 trading days. The fill is the next 15-minute open. The score is (entry − later price) / entry. The fair comparison is shorting at 10:30 Eastern Time with no band. Later long-book filters are extra arms, labeled as later studies, not a replacement of that grid. Annualized rate of return (AnnRoR) is the one-session average times 252. It is not a yearly portfolio return.

## Short definition

- Same 15-minute zones as the long study, resampled here from `data/intraday/1m`. Regular Trading Hours, 09:30–16:00 US/Eastern. One zone per session: high and low of the highest-volume 15-minute candle. Ties keep the earlier bar. The zone is usable only after that candle closes, through N trading sessions (5, 8, 10, 20).
- Date span of the 15-minute bars actually built: **{date_min} through {date_max}** ({info.get('sessions_calendar')} calendar dates before the liquid filter). No longer history was invented. The 1-minute store does not go back to 2024.
- **Reject lowest zone** mirrors reclaim of the highest zone. A bar closes under the lowest active zone when the prior close had not. A later bar touches that zone, then closes back under the zone low. A close above the zone high cancels. If the zone stops being the lowest, cancel. Short the next open. Stop for the zone-edge test: the zone high.
- **Reject highest zone** mirrors bounce off the lowest zone. A red 15-minute candle wicks into the highest zone (its high is inside the band) and closes under that zone. At least one other, lower zone is active. First time per zone. Stop: zone high.
- **Resistance shelf** mirrors the support shelf. First red bar of the session with at least three active zones within 1.5% overhead, none within 1.5% underneath, and the nearest zone below at least 3% away or absent. Stop: high of the nearest zone overhead, when that high is above the close.
- **Spring off highest zone** mirrors spring off the lowest zone. Price closes above the highest zone, then within the next 8 completed 15-minute bars a red bar closes back under that zone’s low. One attempt per zone. Stop: zone high.
- **Clean break down of the lowest zone** mirrors clean break of the highest zone. The whole bar is under the lowest zone (high and close both below the zone low) and the prior close was not. First time per zone. This is the short “sell the break” without waiting for a bounce. Stop: zone high.
- **Floor stack** mirrors the ceiling-stack check. It is a headwind check, not a short idea: a red bar with at least three zones within 1.5% underneath and none just overhead. Shorting into support is recorded so we can see the headwind. A stop at the support zone’s high is kept only when that high is above the close, which it usually is not.
- **Baseline:** short the open of the 10:30 Eastern Time 15-minute bar. No zone.
- Return: (entry − exit) / entry. Next-session exit is the close 26 fifteen-minute bars after the fill bar, including the fill bar. Two-session score uses 52 bars when they exist. Same windows as the long page.
- A long stop of X% below entry is a short stop of X% above entry. The 1% path and the zone-edge path match the long page, inverted. The 1%, 2%, 3%, and 4% grid is the later stop study, inverted: exit exactly at entry × (1+X) if any high in the 26-bar window reaches that price.
- Long trade signs were not reused. Signals were scanned from these bars.

## Later arms (additional, not a replacement)

Frozen the way the later long studies froze them, then pointed short:

- Book: clean break down of the lowest zone. Zone source: exclude the 15:45 bar. Carry: 20 trading days.
- Zone age 4, 5, 6, 7, or 8 sessions.
- Signal candle starts from 09:30 through 11:00 Eastern, 11:00 included.
- Signal close at least 20% under the high of the prior 252 trading days. Days strictly before the signal date. Missing history does not pass.
- Stops at 1%, 2%, 3%, and 4% above the fill, on the unfiltered book and on the combined freeze. The 3% stop is research only. It was not DailyRun and not gold on the long filter, and it is not here.
- Day trade: cover at the close of the entry day’s 15:45 bar. If the signal is the 15:45 bar, the short opens the next session and covers that day’s 15:45 close.

## In-sample / out-of-sample

The house split (entry before 2024-01-01 versus on or after) does not apply. Every bar in this store is from 2026, starting {date_min}. A 2024 cut would be false. Caution split inside this window only: entry before {half_cut} versus on or after {half_cut}. That date is the midpoint of the calendar dates in the liquid set. The long page’s midpoint was 2026-08-24. This split is a short-sample check. It is report-only. It is not used to pick a winner. Do not retune knobs because the later half looks better or worse.

## Universe

- 1-minute files on disk: {n_files} under `data/intraday/1m/`.
- Symbols with at least one 15-minute bar: {info.get('symbols_with_15m')}.
- Liquid set: **{info.get('symbols_liquid')}** symbols. At least {MIN_SESSIONS} complete sessions, at least {MIN_BARS_SESSION} bars in a session, median session dollar volume at least $1,000,000, median close at least $5.
- 15-minute rows in the liquid set: {info.get('rows_liquid')}.
- Busiest candle is the 15:45 bar in {_pct(close_share)} of liquid complete sessions. The 09:30 bar is {_pct(open_share)}.

## Quality bar

Judge quality over trade count. A pattern is only a research candidate if its day-averaged short return beats shorting at 10:30 by at least 0.10 percentage points, the median trade and the typical day beat that baseline, the average without the single best trade beats the baseline average, and the 1% path expectancy beats the baseline. The later half can veto a fade. Floor stack is a headwind check, not a candidate. Clearing that bar still does not make gold or DailyRun. If a best row is named after seeing the table, that naming is in-sample selection and is not adopted.

## Verdict

{verdict_plain}

## Proposed systems

{proposed_md}

## Cross-check

{json.dumps(sanity, indent=2)}

## Pattern results

{chr(10).join(result_lines)}

## Later arms

{chr(10).join(later_md)}

## Stop grid

{chr(10).join(stop_md)}

Research only. Not gold. Not wired into DailyRun.
"""
    (STAMP / "BASELINE.md").write_text(baseline_md, encoding="utf-8")

    summary = f"""# Short-side highest-volume 15-minute scan

{verdict_kind}

Window {date_min} through {date_max}. Liquid symbols {info.get('symbols_liquid')}. Half-sample cut {half_cut} (report only).

10:30 short: N={b_n}, win {_pct(b_win)}, avg {_pct(b_avg)}, median {_pct(b_med)}, AnnRoR {_ann(b_avg)}.

{chr(10).join(later_notes)}

Full grid, sortable tables, and definitions: compare.html. Not gold. Not DailyRun.
"""
    (STAMP / "SUMMARY.md").write_text(summary, encoding="utf-8")

    meta = {
        "info": info,
        "n_files": n_files,
        "half_cut": half_cut,
        "open_share_0930": open_share,
        "close_bar_1545_share": close_share,
        "verdict": verdict_kind,
        "proposed": [
            {"pattern": p["pattern"], "zone_rule": p.get("zone_rule"), "N": p["N"]}
            for p in proposed
        ],
        "best": judged.get("best"),
        "sanity": sanity,
        "baseline": {
            "n": b_n,
            "win": b_win,
            "avg": b_avg,
            "median": b_med,
        },
        "later": [
            {"label": label, **{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in st.items()}}
            for label, st in later_stats
        ],
    }
    (STAMP / "scan_meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"wrote {STAMP / 'compare.html'}", flush=True)


def _jsonable(info: dict) -> dict:
    out = {}
    for k, v in info.items():
        if isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating,)):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    reports_only = "--reports-only" in sys.argv and SIGNALS_CSV.exists()
    if reports_only:
        print(f"reports only from {SIGNALS_CSV}", flush=True)
        sig = pd.read_csv(SIGNALS_CSV)
        meta_path = STAMP / "scan_meta.json"
        prior = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        info = prior.get("info") or {}
        half_cut = prior.get("half_cut") or "2026-08-24"
        n_files = int(prior.get("n_files") or 0)
        hv = pd.read_csv(STAMP / "hv_time_of_day.csv") if (STAMP / "hv_time_of_day.csv").exists() else pd.DataFrame()
        sanity = prior.get("sanity") or {"checked": False, "note": "reports-only"}
    else:
        if not ONE_MIN.exists():
            print("missing data/intraday/1m", file=sys.stderr)
            return 2
        n_files = len(list(ONE_MIN.glob("*.parquet")))
        con = duckdb.connect()
        con.execute("SET threads=4")
        bars = build_15m(con)
        liquid, info = base.select_universe(bars)
        info = _jsonable(info)
        days_sorted = sorted(pd.to_datetime(liquid["day"]).dt.date.unique())
        half_cut = days_sorted[len(days_sorted) // 2].isoformat() if days_sorted else "2026-08-24"
        print(f"half cut (short-sample check only) {half_cut} n_days {len(days_sorted)}", flush=True)
        print("high-volume candle clock...", flush=True)
        hv = base.hv_time_table(liquid)
        hv.to_csv(STAMP / "hv_time_of_day.csv", index=False)
        print(f"scanning {liquid['symbol'].nunique()} symbols...", flush=True)
        rows: list[dict] = []
        n_sym = 0
        for sym, g in liquid.groupby("symbol", sort=False):
            scan_symbol(str(sym), g, rows, zone_rule="as_asked", emit_baseline=True)
            scan_symbol(str(sym), g, rows, zone_rule="ex_last_bar", emit_baseline=False)
            scan_symbol(str(sym), g, rows, zone_rule="mid_session", emit_baseline=False)
            scan_symbol(str(sym), g, rows, zone_rule="close_only", emit_baseline=False)
            n_sym += 1
            if n_sym % 50 == 0:
                print(f"  {n_sym} symbols, signals {len(rows):,}", flush=True)
        print(f"signals collected {len(rows):,}", flush=True)
        sig = pd.DataFrame(rows)
        if sig.empty:
            print("no signals", file=sys.stderr)
            return 2
        sig.to_csv(SIGNALS_CSV, index=False)
        print("baseline cross-check...", flush=True)
        sanity = sanity_check(sig)
        print(json.dumps(sanity), flush=True)

    sig["day"] = sig["day"].astype(str).str.slice(0, 10)
    stats = summarize(sig, half_cut)
    judged = judge(stats)
    print("attaching 252-day highs on the later-study book...", flush=True)
    book, arms = later_frames(sig)
    keep_cols = [
        "symbol", "day", "entry", "fwd26", "fwd52", "day_ret", "path_high",
        "zone_age", "signal_close", "signal_day", "signal_time_et", "zone_date",
        "zone_lo", "zone_hi", "pct_below_252d_high_at_signal_close",
        "in_age", "in_morning", "in_pct20", "in_freeze", "sym_r", "sym_win",
    ]
    book[[c for c in keep_cols if c in book.columns]].to_csv(
        STAMP / "clean_break_down_n20.csv", index=False
    )
    write_reports(info, n_files, hv, stats, judged, half_cut, book, arms, sanity)
    print("--- digest ---", flush=True)
    for s in stats:
        if s["window"] != "full":
            continue
        if s["zone_rule"] not in ("baseline", "as_asked", "ex_last_bar"):
            continue
        if s["pattern"] != "baseline_1030" and s["N"] not in (10, 20):
            continue
        print(
            f"{s.get('zone_rule','?'):12} {s['pattern']:22} N={s['N']:<3} n={s['signals']:<7} "
            f"win={_pct(s['win_pct']):8} avg={_pct(s['avg26']):8} med={_pct(s['med26']):8}",
            flush=True,
        )
    print("verdict proposed", [(v["pattern"], v.get("zone_rule"), v["N"]) for v in judged["proposed"]], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
