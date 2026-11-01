#!/usr/bin/env python3
"""Scan: already broke, first from-above retest still waiting, can it tag tomorrow?

Research watchlist only. Not gold. Not DailyRun. No new entries wired.

Reuses:
  A) VZ 4h 3-month high-vol freeze from vz4h_3m_highvol_20260916
  B) HTF 4h/2h swing-high + 1m/2m retest band from intraday_htf_retest_20260916

As-of last available bar (shop date 2026-09-16). Tomorrow = next RTH 2026-09-17.
Does not invent live quotes.

Usage:
  python tools/retest_tomorrow_scan_20260916.py
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "tools"))

from intraday_1m import DEFAULT_1M_DIR, ET, read_1m  # noqa: E402
from intraday_htf_retest_20260916 import (  # noqa: E402
    HTF_MINUTES,
    PIVOT_K,
    RETEST_ATR_MULT,
    RETEST_HTF_BARS,
    SORT_CSS,
    SORT_JS,
    _as_arrays,
    find_htf_breaks,
    first_retest_idx,
    resample_from_rth_open,
    rth_filter,
    sortable_th,
    wilder_atr,
)
from vol_zone_break_retest import (  # noqa: E402
    atr14,
    build_zones,
    detect_breaks,
    detect_touches,
    generate_signals,
)
from vz4h_3m_highvol_20260916 import (  # noqa: E402
    BAR_MINUTES,
    LOOKBACK_4H,
    PARAMS,
    RETEST_EPS,
    RETEST_WINDOW_4H,
    current_maxvol_idx,
    fetch_1h,
    fmt_day,
    fmt_ts,
    frozen_universe,
    to_vz_frame,
)

STAMP_NAME = "retest_tomorrow_scan_20260916"
STAMP = ROOT / "drive" / "paul_experiments" / STAMP_NAME
CHART_DIR = STAMP / "charts"
DAILY_DIR = ROOT / "data" / "newdata" / "data"

AS_OF = date(2026, 9, 16)
TOMORROW = date(2026, 9, 17)

# --- Rank rule (frozen here BEFORE any write-up sort) ---
# Highest potential = closest to the zone while still valid
# (broken, first from-above retest not filled, not already failed through).
# Sort keys, in order:
#   1. dist_hi_atr  = max(0, last_close − zone_hi) / daily ATR14   (smaller better)
#      If last close is inside [zone_lo, zone_hi], this is 0 (hovering / already at the shelf).
#   2. sessions_since_break  (smaller = fresher; "break not ancient")
#   3. symbol A–Z
# No ML. No composite mystery score. Reachable buckets are labels, not a second sort.
ANCIENT_SESSIONS = 21  # label only; does not drop a row
JUST_THROUGH_ATR = 0.25  # last close below zone_lo but within this × daily ATR → "just through"
ADR_LOOKBACK = 14
HTF_LIST_SCAN = ("4h", "2h")
N_CHARTS = 8

ORIGINAL_REQUEST = (
    "can you show me what stocks have the highest potential of hitting a retest "
    "tomorrow after a previous break today or earlier?"
)

PLAIN_ENGLISH = (
    "We are not hunting new breakouts. We want names that already punched through a "
    "shelf — either a Volume Zone (VZ) high-volume 4-hour High–Low band, or a High Time "
    "Frame (HTF) swing high — and have not yet come back to tap that shelf from above. "
    "Tomorrow means the next Regular Trading Hours (RTH) session, 2026-09-17. "
    "Highest potential just means: still valid, and close enough that one typical day "
    "(Average Daily Range / Average True Range) could reach the shelf. No fancy score."
)


def _finite(x: Any) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def reachable_bucket(dist_hi_adr: float) -> str:
    if not _finite(dist_hi_adr):
        return "n/a"
    if dist_hi_adr <= 0.5:
        return "0.5x"
    if dist_hi_adr <= 1.0:
        return "1.0x"
    if dist_hi_adr <= 1.5:
        return "1.5x"
    return ">1.5x"


def last_vs_zone(close: float, lo: float, hi: float, atr_d: float) -> str:
    if close >= lo and close <= hi:
        return "inside"
    if close > hi:
        return "above"
    pad = JUST_THROUGH_ATR * atr_d if _finite(atr_d) and atr_d > 0 else 0.0
    if close >= lo - pad:
        return "just_through"
    return "through"


def load_daily(symbol: str) -> pd.DataFrame:
    path = DAILY_DIR / f"{symbol}.csv"
    if not path.is_file():
        return pd.DataFrame()
    df = pd.read_csv(path)
    cols = {c: str(c).strip() for c in df.columns}
    df = df.rename(columns=cols)
    if "Date" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Date"})
    df["Date"] = pd.to_datetime(df["Date"], utc=False)
    if getattr(df["Date"].dt, "tz", None) is not None:
        df["Date"] = df["Date"].dt.tz_localize(None)
    df = df.loc[df["Date"].dt.date <= AS_OF].copy()
    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("Date").reset_index(drop=True)


def daily_ranges(daily: pd.DataFrame) -> tuple[float, float, str]:
    if daily is None or daily.empty:
        return float("nan"), float("nan"), ""
    last_day = pd.Timestamp(daily["Date"].iloc[-1]).date().isoformat()
    atr = atr14(daily)
    atr_d = float(atr[-1]) if len(atr) and np.isfinite(atr[-1]) else float("nan")
    tail = daily.tail(ADR_LOOKBACK)
    adr = float((tail["High"] - tail["Low"]).mean()) if len(tail) else float("nan")
    return atr_d, adr, last_day


def session_dates(ts_series: pd.Series) -> list[date]:
    t = pd.to_datetime(ts_series)
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_convert(ET)
    return sorted({d.date() for d in t})


def sessions_between(sess: list[date], start: date, end: date) -> int:
    return sum(1 for d in sess if start < d <= end)


def dist_pack(
    close: float, lo: float, hi: float, atr_d: float, adr: float, atr_4h: float
) -> dict[str, Any]:
    mid = (lo + hi) / 2.0
    # Distance to the shelf we still have to travel downward (0 if already at/through top).
    travel_hi = max(0.0, close - hi)
    out = {
        "zone_mid": mid,
        "dist_hi_pct": (close - hi) / close * 100.0 if close else float("nan"),
        "dist_mid_pct": (close - mid) / close * 100.0 if close else float("nan"),
        "dist_lo_pct": (close - lo) / close * 100.0 if close else float("nan"),
        "dist_hi": travel_hi,
        "dist_hi_atr": travel_hi / atr_d if _finite(atr_d) and atr_d > 0 else float("nan"),
        "dist_mid_atr": max(0.0, close - mid) / atr_d if _finite(atr_d) and atr_d > 0 else float("nan"),
        "dist_lo_atr": max(0.0, close - lo) / atr_d if _finite(atr_d) and atr_d > 0 else float("nan"),
        "dist_hi_adr": travel_hi / adr if _finite(adr) and adr > 0 else float("nan"),
        "dist_hi_4h_atr": travel_hi / atr_4h if _finite(atr_4h) and atr_4h > 0 else float("nan"),
    }
    out["reachable"] = reachable_bucket(out["dist_hi_adr"])
    out["reachable_1session"] = bool(_finite(out["dist_hi_adr"]) and out["dist_hi_adr"] <= 1.0)
    return out


def rank_key(row: dict[str, Any]) -> tuple[float, int, str]:
    """Frozen rank. Do not change after inspecting the table."""
    dist = float(row.get("dist_hi_atr", float("nan")))
    if not _finite(dist):
        dist = 1e9
    age = int(row.get("sessions_since_break") or 9999)
    return (dist, age, str(row.get("symbol", "")))


def load_4h(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = fetch_1h(symbol)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    rth = rth_filter(raw)
    if rth.empty:
        return pd.DataFrame(), pd.DataFrame()
    t = pd.to_datetime(rth["ts"], utc=True).dt.tz_convert(ET)
    rth = rth.loc[t.dt.date <= AS_OF].copy()
    if rth.empty:
        return pd.DataFrame(), pd.DataFrame()
    htf = resample_from_rth_open(rth, BAR_MINUTES)
    return rth, htf if htf is not None else pd.DataFrame()


def last_bar_notes(htf: pd.DataFrame, lo: float, hi: float) -> dict[str, Any]:
    if htf is None or len(htf) < 1:
        return {
            "last_4h_ts": "",
            "last_4h_close": float("nan"),
            "last_4h_low": float("nan"),
            "last_4h_vol": float("nan"),
            "dipping": False,
            "vol_vs_med20": float("nan"),
        }
    last = htf.iloc[-1]
    prev_c = float(htf["close"].iloc[-2]) if len(htf) >= 2 else float("nan")
    last_c = float(last["close"])
    last_l = float(last["low"])
    last_v = float(last["volume"]) if "volume" in htf.columns else float("nan")
    med = float(htf["volume"].tail(20).median()) if "volume" in htf.columns else float("nan")
    dipping = False
    if _finite(prev_c) and last_c < prev_c:
        dipping = True
    if last_l <= hi and last_c > hi:
        dipping = True
    vol_vs = last_v / med if _finite(last_v) and _finite(med) and med > 0 else float("nan")
    return {
        "last_4h_ts": fmt_ts(last["ts"]),
        "last_4h_close": last_c,
        "last_4h_low": last_l,
        "last_4h_vol": last_v,
        "dipping": dipping,
        "vol_vs_med20": vol_vs,
    }


def scan_vz(symbol: str, htf: pd.DataFrame, daily: pd.DataFrame) -> list[dict[str, Any]]:
    if htf is None or len(htf) < LOOKBACK_4H + 8:
        return []
    df = to_vz_frame(htf)
    atr_4h_arr = atr14(df)
    atr_4h = float(atr_4h_arr[-1]) if len(atr_4h_arr) and np.isfinite(atr_4h_arr[-1]) else float("nan")
    atr_d, adr, daily_last = daily_ranges(daily)
    last_c = float(df["Close"].iloc[-1])
    last_ts = pd.Timestamp(df["Date"].iloc[-1])
    sess = [pd.Timestamp(x).date() for x in df["Date"]]
    sess_uniq = sorted(set(sess))
    current_idx = current_maxvol_idx(df)
    zones = [z for z in build_zones(df, LOOKBACK_4H) if z.kind == "HL"]
    rows: list[dict[str, Any]] = []
    for z in zones:
        touches = detect_touches(df, z, PARAMS.approach_lookback, eps_pct=PARAMS.retest_eps_pct)
        breaks = detect_breaks(
            df, z, atr_4h_arr, PARAMS.break_pct, PARAMS.break_atr, PARAMS.break_window
        )
        ups = [b for b in breaks if b.direction == "up"]
        if not ups:
            continue
        br = ups[0]
        sigs = generate_signals(df, z, touches, breaks, PARAMS, "vz4h_3m")
        band_lo = z.lo * (1.0 - RETEST_EPS)
        band_hi = z.hi * (1.0 + RETEST_EPS)
        first_tag = None
        for t in touches:
            if t.bar_idx <= br.bar_idx:
                continue
            if t.approach != "from_above":
                continue
            if t.low <= band_hi and t.high >= band_lo:
                first_tag = t
                break
        window_end = min(len(df) - 1, br.bar_idx + RETEST_WINDOW_4H)
        in_window = (len(df) - 1) <= window_end
        bars_since = int(len(df) - 1 - br.bar_idx)
        br_day = pd.Timestamp(br.date).date()
        sess_since = sessions_between(sess_uniq, br_day, last_ts.date())
        notes = last_bar_notes(htf, float(z.lo), float(z.hi))
        vs = last_vs_zone(last_c, float(z.lo), float(z.hi), atr_d)
        d = dist_pack(last_c, float(z.lo), float(z.hi), atr_d, adr, atr_4h)
        tagged = first_tag is not None
        signaled = bool(sigs)
        waiting = (not tagged) and vs in ("above", "inside")
        just_through = (not tagged) and vs == "just_through"
        second = tagged and vs in ("above", "inside") and bool(d["reachable_1session"])
        status = "waiting"
        if tagged and signaled:
            status = "already_retested"
        elif tagged:
            status = "tagged_no_signal"
        elif just_through:
            status = "just_through"
        elif vs == "through":
            status = "failed_through"
        elif not in_window and waiting:
            status = "window_expired"
        elif waiting:
            status = "waiting"
        else:
            status = vs
        note_bits = []
        if int(z.max_vol_idx) == int(current_idx):
            note_bits.append("current 3-month max-vol shelf")
        if notes["dipping"]:
            note_bits.append("last 4h dipping toward the band")
        if _finite(notes["vol_vs_med20"]):
            note_bits.append(f"last 4h vol {notes['vol_vs_med20']:.2f}× 20-bar median")
        if br_day == AS_OF:
            note_bits.append("broke today")
        elif sess_since <= 1:
            note_bits.append("broke this session or prior")
        if sess_since > ANCIENT_SESSIONS:
            note_bits.append(f"ancient break ({sess_since} sessions)")
        if not in_window:
            note_bits.append(f"outside parent {RETEST_WINDOW_4H}-bar retest window")
        if tagged:
            note_bits.append(f"first from-above tag {fmt_ts(first_tag.date)}")
        row = {
            "setup": "VZ 4h",
            "symbol": symbol,
            "htf": "4h",
            "zone_id": z.zone_id,
            "zone_lo": float(z.lo),
            "zone_hi": float(z.hi),
            "level": float(z.hi),
            "zone_ts": fmt_ts(z.max_vol_date),
            "break_ts": fmt_ts(br.date),
            "break_day": br_day.isoformat(),
            "retest_ts": fmt_ts(first_tag.date) if first_tag is not None else "",
            "signal_ts": fmt_ts(sigs[0].signal_date) if sigs else "",
            "last_close": last_c,
            "last_bar": fmt_ts(last_ts),
            "daily_last": daily_last,
            "atr14": atr_d,
            "adr14": adr,
            "atr_4h": atr_4h,
            "last_vs_zone": vs,
            "status": status,
            "waiting": waiting and in_window,
            "waiting_expired": waiting and (not in_window),
            "just_through": just_through,
            "second_touch": second,
            "in_window": in_window,
            "bars_since_break": bars_since,
            "sessions_since_break": sess_since,
            "is_current_3m": int(z.max_vol_idx) == int(current_idx),
            "parent_window_open": in_window,
            "notes": "; ".join(note_bits),
            **notes,
            **d,
        }
        rows.append(row)
    return rows


def _ltf_arrays_from_1h(rth_1h: pd.DataFrame, minutes: int) -> Optional[dict[str, Any]]:
    if rth_1h is None or rth_1h.empty:
        return None
    frame = resample_from_rth_open(rth_1h, minutes)
    if frame is None or frame.empty:
        return None
    return _as_arrays(frame)


def scan_htf(
    symbol: str,
    rth_1h: pd.DataFrame,
    htf_name: str,
    daily: pd.DataFrame,
    df1: Optional[pd.DataFrame],
) -> list[dict[str, Any]]:
    mins = HTF_MINUTES[htf_name]
    htf = resample_from_rth_open(rth_1h, mins)
    if htf is None or htf.empty or len(htf) < 2 * PIVOT_K[htf_name] + 1:
        return []
    breaks = find_htf_breaks(htf, htf_name)
    if not breaks:
        return []
    atr_d, adr, daily_last = daily_ranges(daily)
    last_c = float(htf["close"].iloc[-1])
    last_ts = pd.Timestamp(htf["ts"].iloc[-1])
    sess_uniq = session_dates(htf["ts"])
    atr_htf_arr = wilder_atr(
        htf["high"].to_numpy(dtype=float),
        htf["low"].to_numpy(dtype=float),
        htf["close"].to_numpy(dtype=float),
    )
    atr_htf = float(atr_htf_arr[-1]) if len(atr_htf_arr) and np.isfinite(atr_htf_arr[-1]) else float("nan")

    ltf_1m = None
    if df1 is not None and not df1.empty:
        work = df1.copy()
        if "end_ts" not in work.columns:
            work["end_ts"] = work["ts"] + pd.Timedelta(minutes=1)
        ltf_1m = _as_arrays(work)
    ltf_1h = _as_arrays(rth_1h.assign(end_ts=rth_1h["ts"] + pd.Timedelta(hours=1))) if not rth_1h.empty else None
    ltf_2m = None
    if df1 is not None and not df1.empty:
        f2 = resample_from_rth_open(df1, 2)
        if f2 is not None and not f2.empty:
            ltf_2m = _as_arrays(f2)

    rows: list[dict[str, Any]] = []
    for br in breaks:
        level = float(br["level"])
        band = RETEST_ATR_MULT * float(br["htf_atr"])
        lo = level - band
        hi = level + band
        start_ts = br["break_end_ts"]
        end_scan = pd.Timestamp(htf["end_ts"].iloc[-1])
        if end_scan.tzinfo is None:
            end_scan = end_scan.tz_localize(ET)
        window_end = pd.Timestamp(br["window_end_ts"])
        if window_end.tzinfo is None:
            window_end = window_end.tz_localize(ET)
        parent_open = end_scan <= window_end

        retest_src = ""
        retest_ts = ""
        ri = None
        if ltf_1m is not None:
            tape_start = pd.Timestamp(ltf_1m["ts"][0])
            if tape_start.tzinfo is None:
                tape_start = tape_start.tz_localize(ET)
            br_end = pd.Timestamp(start_ts)
            if br_end.tzinfo is None:
                br_end = br_end.tz_localize(ET)
            if br_end >= tape_start:
                ri = first_retest_idx(
                    ltf_1m, start_ts=start_ts, end_ts=end_scan, level=level, band=band
                )
                if ri is not None:
                    retest_src = "1m"
                    retest_ts = fmt_ts(ltf_1m["ts"][ri])
            else:
                # Break is older than the 1m store — 1h proxy for "already tagged?"
                if ltf_1h is not None:
                    ri_h = first_retest_idx(
                        ltf_1h, start_ts=start_ts, end_ts=end_scan, level=level, band=band
                    )
                    if ri_h is not None:
                        retest_src = "1h_proxy"
                        retest_ts = fmt_ts(ltf_1h["ts"][ri_h])
                        ri = ri_h
        elif ltf_1h is not None:
            ri = first_retest_idx(
                ltf_1h, start_ts=start_ts, end_ts=end_scan, level=level, band=band
            )
            if ri is not None:
                retest_src = "1h_proxy"
                retest_ts = fmt_ts(ltf_1h["ts"][ri])

        if ri is None and ltf_2m is not None and retest_src == "":
            ri2 = first_retest_idx(
                ltf_2m, start_ts=start_ts, end_ts=end_scan, level=level, band=band
            )
            if ri2 is not None:
                retest_src = "2m"
                retest_ts = fmt_ts(ltf_2m["ts"][ri2])
                ri = ri2

        tagged = ri is not None
        notes_bar = last_bar_notes(htf, lo, hi)
        vs = last_vs_zone(last_c, lo, hi, atr_d)
        d = dist_pack(last_c, lo, hi, atr_d, adr, atr_htf)
        br_ts = pd.Timestamp(br["break_end_ts"])
        if br_ts.tzinfo is not None:
            br_day = br_ts.tz_convert(ET).date()
        else:
            br_day = br_ts.date()
        sess_since = sessions_between(sess_uniq, br_day, last_ts.date() if last_ts.tzinfo is None else last_ts.tz_convert(ET).date())
        last_day = last_ts.date() if last_ts.tzinfo is None else last_ts.tz_convert(ET).date()
        waiting = (not tagged) and vs in ("above", "inside")
        just_through = (not tagged) and vs == "just_through"
        second = tagged and vs in ("above", "inside") and bool(d["reachable_1session"])
        if tagged:
            status = "already_retested"
        elif just_through:
            status = "just_through"
        elif vs == "through":
            status = "failed_through"
        elif waiting and not parent_open:
            status = "window_expired"
        elif waiting:
            status = "waiting"
        else:
            status = vs
        note_bits = [
            f"HTF {htf_name} swing high {level:.2f} ± {RETEST_ATR_MULT:.2f}× HTF ATR ({band:.2f})"
        ]
        if notes_bar["dipping"]:
            note_bits.append(f"last {htf_name} dipping toward the band")
        if br_day == AS_OF:
            note_bits.append("broke today")
        if sess_since > ANCIENT_SESSIONS:
            note_bits.append(f"ancient break ({sess_since} sessions)")
        if not parent_open:
            note_bits.append(
                f"outside parent {RETEST_HTF_BARS[htf_name]}-bar HTF retest window"
            )
        if tagged:
            note_bits.append(f"first retest already printed on {retest_src} at {retest_ts}")
        elif retest_src == "" and (df1 is None or df1.empty):
            note_bits.append("no 1m tape; waiting judged on 1h proxy")
        elif not tagged and ltf_1m is None:
            note_bits.append("1m missing for this name; 1h proxy has not tagged")
        row = {
            "setup": f"HTF {htf_name}",
            "symbol": symbol,
            "htf": htf_name,
            "zone_id": f"SWING_{htf_name}_{br_day.isoformat()}",
            "zone_lo": lo,
            "zone_hi": hi,
            "level": level,
            "zone_ts": fmt_ts(htf["ts"].iloc[int(br["pivot_i"])]),
            "break_ts": fmt_ts(br["break_end_ts"]),
            "break_day": br_day.isoformat(),
            "retest_ts": retest_ts,
            "signal_ts": retest_ts,
            "last_close": last_c,
            "last_bar": fmt_ts(last_ts),
            "daily_last": daily_last,
            "atr14": atr_d,
            "adr14": adr,
            "atr_4h": atr_htf,
            "last_vs_zone": vs,
            "status": status,
            "waiting": waiting and parent_open,
            "waiting_expired": waiting and (not parent_open),
            "just_through": just_through,
            "second_touch": second,
            "in_window": parent_open,
            "bars_since_break": int(len(htf) - 1 - int(br["break_i"])),
            "sessions_since_break": sess_since,
            "is_current_3m": False,
            "parent_window_open": parent_open,
            "retest_src": retest_src,
            "notes": "; ".join(note_bits),
            **notes_bar,
            **d,
        }
        rows.append(row)
    return rows


def pick_best_waiting(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per symbol: the highest-potential still-waiting setup (in-window first)."""
    waiting = [r for r in rows if r.get("waiting")]
    if not waiting:
        waiting = [r for r in rows if r.get("waiting_expired")]
    best: dict[str, dict[str, Any]] = {}
    for r in waiting:
        prev = best.get(r["symbol"])
        if prev is None or rank_key(r) < rank_key(prev):
            best[r["symbol"]] = r
    return sorted(best.values(), key=rank_key)


def plot_snapshot(row: dict[str, Any], htf: pd.DataFrame, out_path: Path) -> None:
    if htf is None or htf.empty:
        return
    n = min(80, len(htf))
    sl = htf.tail(n).reset_index(drop=True)
    idx = np.arange(len(sl))
    o = sl["open"].to_numpy(dtype=float)
    h = sl["high"].to_numpy(dtype=float)
    l = sl["low"].to_numpy(dtype=float)
    c = sl["close"].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(11.2, 4.6))
    up = c >= o
    ax.vlines(idx, l, h, color="#64748b", lw=0.6, zorder=2)
    body_lo = np.minimum(o, c)
    body_hi = np.maximum(o, c)
    if np.any(up):
        ax.vlines(idx[up], body_lo[up], body_hi[up], color="#2ca02c", lw=2.1, zorder=3)
    if np.any(~up):
        ax.vlines(idx[~up], body_lo[~up], body_hi[~up], color="#d62728", lw=2.1, zorder=3)
    lo, hi = float(row["zone_lo"]), float(row["zone_hi"])
    ax.add_patch(
        Rectangle(
            (-0.5, lo),
            len(sl),
            max(hi - lo, 1e-6),
            facecolor="#9467bd",
            edgecolor="none",
            alpha=0.18,
            zorder=1,
        )
    )
    ax.axhline(hi, color="#7c3aed", lw=1.0, ls="--", label="zone / band top")
    ax.axhline(lo, color="#7c3aed", lw=0.8, ls=":", label="zone / band bottom")
    ax.axhline(float(row["level"]), color="#ea580c", lw=1.0, alpha=0.85, label="level")
    ax.scatter([len(sl) - 1], [float(row["last_close"])], color="#0f172a", s=28, zorder=4)
    ax.set_title(
        f"{row['symbol']}  {row['setup']}  last {row['last_close']:.2f}  "
        f"dist {row['dist_hi_atr']:.2f}×ATR  {row['reachable']} ADR  "
        f"break {row['break_day']}"
    )
    ax.grid(True, alpha=0.18)
    dates = pd.to_datetime(sl["ts"])
    tick_n = max(6, min(10, len(sl) // 10 or 6))
    tick_pos = np.linspace(0, max(len(sl) - 1, 0), tick_n, dtype=int)
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(
        [dates.iloc[i].strftime("%m-%d %H:%M") for i in tick_pos], rotation=30, ha="right"
    )
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fmt_num(x: Any, nd: int = 2) -> str:
    if not _finite(x):
        return "—"
    return f"{float(x):,.{nd}f}"


def fmt_px(x: Any) -> str:
    return fmt_num(x, 2)


def write_baseline(universe: list[str], coverage: list[dict[str, Any]]) -> None:
    cov_lines = [
        "| Symbol | 4h bars | last 4h | daily last | 1m bars | 1m last |",
        "|--------|--------:|---------|------------|--------:|---------|",
    ]
    for c in coverage:
        cov_lines.append(
            f"| {c['symbol']} | {c.get('n_4h', '—')} | {c.get('last_4h', '—')} | "
            f"{c.get('daily_last', '—')} | {c.get('n_1m', '—')} | {c.get('last_1m', '—')} |"
        )
    text = f"""# BASELINE — retest-tomorrow scan — `{STAMP_NAME}`

**Research scan only. Not gold. Not DailyRun. No new entries wired.**

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

Volume Zone (**VZ**) = house max-volume High–Low shelf, then a from-above retest buy.
High Time Frame (**HTF**) here is the 4-hour / 2-hour bar the swing high is drawn on
(parent expansion: High Time Frame, not High Tight Flag).
Average True Range (**ATR**) = Wilder 14 typical-bar range.
Average Daily Range (**ADR**) = mean(High−Low) over the last {ADR_LOOKBACK} daily bars.
Regular Trading Hours (**RTH**) = 09:30–16:00 ET.

## As-of / tomorrow

| Item | Value |
|------|--------|
| Shop as-of | **{AS_OF.isoformat()}** (last completed / latest on-disk bar; no live quotes) |
| Tomorrow | next RTH session **{TOMORROW.isoformat()}** |
| Daily source | `data/newdata/data/{{SYM}}.csv` clipped to as-of |
| 4h / 2h source | Yahoo 1h (`vz4h_3m_highvol_20260916/cache_1h/`), RTH-filtered, `resample_from_rth_open` |
| 1m source | `data/intraday/1m/` (Jul–Sep 2026). Used only to ask: did a 1-minute retest already print? |

## Universe (frozen)

PaulTwenty + UNH (same list as the VZ 4h / HTF 4h stamps):

{', '.join(universe)}

{len(universe)} names. Mega-caps already in local data. No extra names added after seeing the table.

## Setup A — VZ 4h 3-month high-vol (do not mix with B)

Parent: `vz4h_3m_highvol_20260916` / house `build_zones`.

| Knob | Freeze |
|------|--------|
| Lookback | **{LOOKBACK_4H}** 4h bars (~3 calendar months) |
| Zone | max-volume 4h bar **High–Low** (HL). No ATR pad. |
| Break | 4h close > zone.hi |
| First retest | house `generate_signals` + visual from-above High–Low intersect (eps={RETEST_EPS}) |
| Retest window | **{RETEST_WINDOW_4H}** 4h bars after the break |
| Waiting | broke up, **no** post-break from-above tag yet, last close still above zone_lo (or inside) |
| Just through | last close below zone_lo but within {JUST_THROUGH_ATR}× daily ATR — labeled, not in the main rank |

All persistent HL winners are scanned. Current 3-month max-vol shelf is flagged. Main table = still inside the 63-bar window.

## Setup B — HTF 4h (and 2h) broken swing high (do not mix with A)

Parent: `intraday_htf_retest_20260916`.

| Knob | Freeze |
|------|--------|
| Pivot | shop fractal, k={dict(PIVOT_K)} |
| Break | HTF close above the confirmed swing high |
| Retest band | level ± **{RETEST_ATR_MULT} × HTF ATR** |
| Parent window | {dict(RETEST_HTF_BARS)} HTF bars after the break |
| LTF retest | 1m bar intersects the band (2m if 1m quiet). Breaks older than the 1m store use a **1h proxy**, labeled. |
| Waiting | HTF high broken, first LTF/proxy retest **not** printed, last close still above the band floor |

Prefer **waiting for first retest**. Already-used first retests are not in the main rank.

## Rank rule (frozen before sorting the write-up)

Highest potential = closest to the zone while still valid. **No ML.**

1. `dist_hi_atr` = `max(0, last_close − zone_hi) / daily ATR14` (smaller better). Inside the zone ⇒ 0.
2. `sessions_since_break` (smaller = fresher; breaks older than {ANCIENT_SESSIONS} sessions are labeled **ancient**, not dropped).
3. symbol A–Z.

**Reachable in 1 session?** `dist_to_zone_hi <= 1.0 × ADR14`. Buckets: 0.5× / 1.0× / 1.5× / >1.5×. These are labels, not a second sort.

Shortlist lead = waiting (in-window) rows, already sorted by the rank above, that are also in the 0.5× or 1.0× ADR bucket.

## Window-expired, first retest never printed (labeled, not mixed)

Parent HTF window is only **3** 4h bars / **4** 2h bars (~1–2 sessions). A Monday break can be “still never tagged” on Wednesday and already be outside that window. Those rows are **not** mixed into the in-window shortlist. They get their own table when:

- first from-above / 1m retest has **not** printed
- last close still above or inside the band
- `sessions_since_break <= 10` (recent only; older expired waits are noise)

Same rank keys. Honest for “break earlier, retest tomorrow.” Not a DailyRun signal — the parent freeze would have already given up.

## Second-touch bucket

Shown only when the first retest already printed **and** last close is still above/inside **and** `dist_hi_adr <= 1.0` **and** `sessions_since_break <= {ANCIENT_SESSIONS}` (drop ancient levels that price happens to be near). VZ second-touch is current-3m shelves only. Labeled separately. Not mixed into “waiting for tomorrow.”

## What this is not

- Not a book. Canonical compare metrics (Ann ROR, Max DD, FIT, …) do not apply.
- Not gold. Not DailyRun. No entry wired.
- Selection of *which* waiting name is “highest potential” is the frozen rank above, not an OOS retune.

## Coverage

{chr(10).join(cov_lines)}
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    (STAMP / "BASELINE.md").write_text(text, encoding="utf-8")


def write_hypothesis() -> None:
    text = f"""# HYPOTHESIS — `{STAMP_NAME}`

**Research scan only. Not a KEEP / gold / DailyRun claim.**

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Hypothesis

If a name has already left a VZ 4h high-volume High–Low shelf or an HTF 4h/2h swing
high to the upside, and the first from-above retest has not printed, then the names
**closest** to that shelf (in daily ATR units) are the ones most likely to tag it
in the next Regular Trading Hours (RTH) session — provided one typical Average Daily
Range (ADR) can cover the remaining distance.

This is a **distance / freshness scan**, not an expectancy test. We are not claiming
the retest bounce works. We are ranking who can still *reach* the retest tomorrow.

## One question, two freezes (not mixed)

- **A:** VZ 4h 3-month high-vol (`vz4h_3m_highvol_20260916`).
- **B:** HTF 4h / 2h swing-high break + 1m band (`intraday_htf_retest_20260916`).

Same universe. Same as-of. Separate tables.

## Falsify / HOLD

- Nobody is close: every broken name has already run >1.5× ADR away.
- The 2026-09-16 session already completed the first from-above tag on the names
  that looked close — then “tomorrow” is a second touch, not a first.
- 1m tape is too short to know whether an older HTF break already retested
  (we then use a labeled 1h proxy).

No DailyRun wire. No knob shopping after the table.
"""
    (STAMP / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def _lead_items(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    close = [
        r
        for r in rows
        if r.get("reachable") in ("0.5x", "1.0x")
        and (r.get("waiting") or r.get("waiting_expired"))
    ]
    return close[:limit]


def _row_tr(r: dict[str, Any], chart_rel: str = "") -> str:
    zone = f"{fmt_px(r['zone_lo'])}–{fmt_px(r['zone_hi'])}"
    chart = f"<a href=\"{html_mod.escape(chart_rel)}\">PNG</a>" if chart_rel else "—"
    return (
        "<tr>"
        f"<td>{html_mod.escape(r['symbol'])}</td>"
        f"<td>{html_mod.escape(r['setup'])}</td>"
        f"<td>{html_mod.escape(r.get('zone_id', ''))}<br><span class='dim'>{zone}</span></td>"
        f"<td>{html_mod.escape(r['break_ts'])}</td>"
        f"<td>{r.get('sessions_since_break', '—')}</td>"
        f"<td>{fmt_num(r.get('dist_hi_pct'))}</td>"
        f"<td>{fmt_num(r.get('dist_hi_atr'))}</td>"
        f"<td>{fmt_num(r.get('dist_hi_adr'))}</td>"
        f"<td>{html_mod.escape(str(r.get('reachable', '—')))}</td>"
        f"<td>{fmt_px(r.get('last_close'))}</td>"
        f"<td>{html_mod.escape(str(r.get('last_vs_zone', '')))}</td>"
        f"<td>{'YES' if r.get('parent_window_open') else 'no'}</td>"
        f"<td>{html_mod.escape(r.get('notes', ''))}</td>"
        f"<td>{chart}</td>"
        "</tr>"
    )


def _table(rows: list[dict[str, Any]], charts: dict[str, str], empty: str) -> str:
    if not rows:
        return f"<p class='note'>{html_mod.escape(empty)}</p>"
    body = "".join(
        _row_tr(r, charts.get(f"{r['symbol']}|{r['setup']}", "")) for r in rows
    )
    heads = "".join(
        [
            sortable_th("symbol", "text"),
            sortable_th("setup", "text"),
            sortable_th("zone / level", "text"),
            sortable_th("break time", "date"),
            sortable_th("sessions since break", "num"),
            sortable_th("dist to top %", "num"),
            sortable_th("dist / ATR14", "num"),
            sortable_th("dist / ADR14", "num"),
            sortable_th("reachable bucket", "text"),
            sortable_th("last close", "num"),
            sortable_th("last vs zone", "text"),
            sortable_th("parent window open", "text"),
            sortable_th("notes", "text"),
            sortable_th("chart", "text"),
        ]
    )
    return (
        "<table class=\"sortable\">"
        "<caption>Click column headers to sort.</caption>"
        f"<thead><tr>{heads}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def write_html(
    *,
    universe: list[str],
    coverage: list[dict[str, Any]],
    vz_wait: list[dict[str, Any]],
    htf4_wait: list[dict[str, Any]],
    htf2_wait: list[dict[str, Any]],
    expired_recent: list[dict[str, Any]],
    vz_second: list[dict[str, Any]],
    htf_second: list[dict[str, Any]],
    vz_all: list[dict[str, Any]],
    htf_all: list[dict[str, Any]],
    charts: dict[str, str],
    asof_bar: str,
) -> Path:
    lead_a = _lead_items(vz_wait)
    lead_b = _lead_items(htf4_wait) + _lead_items(htf2_wait)
    lead_exp = _lead_items(expired_recent)
    tagged_today_vz = [
        r
        for r in vz_all
        if r.get("retest_ts") and str(r.get("retest_ts", "")).startswith(AS_OF.isoformat())
    ]
    tagged_today_htf = [
        r
        for r in htf_all
        if r.get("retest_ts") and str(r.get("retest_ts", "")).startswith(AS_OF.isoformat())
    ]

    def bullets(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "<li>Nobody in-window and inside 1.0× ADR. See the full table.</li>"
        bits = []
        for r in rows[:8]:
            bits.append(
                f"<li><strong>{html_mod.escape(r['symbol'])}</strong> "
                f"({html_mod.escape(r['setup'])}) — "
                f"{fmt_num(r['dist_hi_atr'])}× daily ATR / {html_mod.escape(r['reachable'])} ADR "
                f"to the top, broke {html_mod.escape(r['break_day'])}, "
                f"last close {fmt_px(r['last_close'])} vs "
                f"{fmt_px(r['zone_lo'])}–{fmt_px(r['zone_hi'])}. "
                f"{html_mod.escape(r.get('notes', ''))}</li>"
            )
        return "".join(bits)

    blunt_html = []
    if not lead_a and not lead_b:
        blunt_html.append(
            "Blunt: <strong>no in-window first-retest wait is inside 1.0× ADR</strong> "
            "after the 2026-09-16 close. The parent HTF window is only 3 four-hour bars, "
            "so same-session fills ate almost every fresh 4h/2h break."
        )
    if lead_exp:
        blunt_html.append(
            "The only <em>close</em> name that still has not printed a first from-above "
            "tag is in the <strong>window-expired</strong> bucket (parent freeze already "
            "gave up). That is the honest “broke earlier, could tag tomorrow” row."
        )
    if tagged_today_vz or tagged_today_htf:
        names = sorted({r["symbol"] for r in tagged_today_vz + tagged_today_htf})
        blunt_html.append(
            "The 2026-09-16 session already printed a first from-above tag on: "
            + ", ".join(html_mod.escape(n) for n in names)
            + ". Those are not “waiting for tomorrow” unless you want a second touch."
        )
    ran = [r for r in (vz_wait + htf4_wait) if r.get("reachable") == ">1.5x"]
    if ran:
        blunt_html.append(
            f"{len(ran)} in-window VZ wait"
            + ("s have" if len(ran) != 1 else " has")
            + " already run more than 1.5× ADR away — not a tomorrow tag unless the day is huge."
        )

    cov_body = []
    for c in coverage:
        cov_body.append(
            "<tr>"
            f"<td>{html_mod.escape(c['symbol'])}</td>"
            f"<td>{c.get('n_4h', '—')}</td>"
            f"<td>{html_mod.escape(str(c.get('last_4h', '—')))}</td>"
            f"<td>{html_mod.escape(str(c.get('daily_last', '—')))}</td>"
            f"<td>{c.get('n_1m', '—')}</td>"
            f"<td>{html_mod.escape(str(c.get('last_1m', '—')))}</td>"
            f"<td>{html_mod.escape(str(c.get('note', '')))}</td>"
            "</tr>"
        )

    gallery = []
    for key, rel in charts.items():
        gallery.append(
            f"<figure class='card'><figcaption>{html_mod.escape(key)}</figcaption>"
            f"<a href='{html_mod.escape(rel)}'><img src='{html_mod.escape(rel)}' "
            f"alt='{html_mod.escape(key)}'/></a></figure>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Retest tomorrow scan — {STAMP_NAME}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.45rem;margin:0 0 8px}}
h2{{font-size:1.15rem;margin:28px 0 10px}}
.ask,.plain,.lead{{max-width:1100px;padding:12px 14px;border-radius:8px;margin:12px 0}}
.ask{{background:#fff7ed;border:1px solid #fdba74}}
.plain{{background:#ecfeff;border:1px solid #67e8f9}}
.lead{{background:#f0fdf4;border:1px solid #86efac}}
.badge{{display:inline-block;background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:.85rem;font-weight:600}}
.meta,.note,.dim{{font-size:.92rem;color:#475569}}
.dim{{font-size:.8rem}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.stat{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;min-width:150px}}
.stat h3{{margin:0 0 6px;font-size:12px;color:#64748b}}
.stat .n{{font-size:1.25rem;font-weight:700}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0 16px;font-size:.85rem}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:8px 10px;text-align:left;vertical-align:top}}
table.sortable th{{background:#f1f5f9}}
.gallery{{display:grid;grid-template-columns:1fr;gap:18px;margin:18px 0}}
figure.card{{margin:0;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:10px}}
figure.card img{{width:100%;height:auto;border:1px solid #e2e8f0}}
{SORT_CSS}
</style>
</head>
<body>
<p class="badge">Research scan only · not gold · not DailyRun · no new entries</p>
<h1>Who can still tag a first retest tomorrow?</h1>
<p class="meta">Stamp <code>{STAMP_NAME}</code> · as-of <strong>{AS_OF.isoformat()}</strong>
(last on-disk bar {html_mod.escape(asof_bar)}) · tomorrow = RTH <strong>{TOMORROW.isoformat()}</strong>
· universe PaulTwenty + UNH ({len(universe)} names).
Click column headers to sort.</p>

<div class="ask">
<strong>What you asked</strong>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
</div>
<div class="plain">
<strong>In plain English</strong>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>Volume Zone (<strong>VZ</strong>) = high-volume High–Low shelf on 4-hour Regular Trading Hours
(<strong>RTH</strong>) bars. High Time Frame (<strong>HTF</strong>) = 4-hour / 2-hour swing high
(not High Tight Flag). Average True Range (<strong>ATR</strong>) = Wilder 14 typical range.
Average Daily Range (<strong>ADR</strong>) = mean daily High−Low over 14 sessions.
A name is “waiting” only if it already broke up and has <em>not</em> completed the first
from-above retest.</p>
</div>

<div class="lead">
<strong>Shortlist (frozen rank: smaller dist/ATR, then fresher break)</strong>
<p>Reachable = remaining distance to the zone top ≤ 1.0 × ADR. In-window only.</p>
<p><strong>A — VZ 4h</strong></p>
<ul>{bullets(lead_a)}</ul>
<p><strong>B — HTF 4h / 2h (in-window)</strong></p>
<ul>{bullets(lead_b)}</ul>
<p><strong>Window expired, first tag still missing (recent, labeled)</strong></p>
<ul>{bullets(lead_exp)}</ul>
<p>{' '.join(blunt_html) if blunt_html else 'See tables for everyone else.'}</p>
</div>

<div class="cards">
<div class="stat"><h3>VZ waiting (in window)</h3><div class="n">{len(vz_wait)}</div></div>
<div class="stat"><h3>HTF 4h waiting (in window)</h3><div class="n">{len(htf4_wait)}</div></div>
<div class="stat"><h3>HTF 2h waiting (in window)</h3><div class="n">{len(htf2_wait)}</div></div>
<div class="stat"><h3>Expired, never tagged (≤10 sess)</h3><div class="n">{len(expired_recent)}</div></div>
<div class="stat"><h3>Tagged on {AS_OF.isoformat()}</h3><div class="n">{len(tagged_today_vz)+len(tagged_today_htf)}</div></div>
<div class="stat"><h3>Cheap second-touch</h3><div class="n">{len(vz_second)+len(htf_second)}</div></div>
</div>

<h2>Rank rule (frozen before this table was sorted)</h2>
<p class="note">1) <code>max(0, last_close − zone_hi) / daily ATR14</code> ascending.
Inside the zone counts as 0. 2) Sessions since the break, ascending (older than
{ANCIENT_SESSIONS} sessions is labeled ancient, not dropped). 3) Symbol.
Reachable buckets (0.5× / 1.0× / 1.5× ADR) are labels only. Highest potential =
closest while still valid. Not a machine-learning score. Setups A and B are
<strong>not</strong> mixed in one ranking.</p>

<h2>A — VZ 4h 3-month high-vol, waiting on first from-above retest</h2>
<p class="note">Parent freeze <code>vz4h_3m_highvol_20260916</code>. Zone = 126-bar
max-volume 4h High–Low. Break = 4h close above the high. Waiting = no from-above
tag yet, still inside the 63-bar retest window, last close above or inside the zone.
One row per name (closest waiting shelf).</p>
{_table(vz_wait, charts, "No VZ 4h name is in-window and still waiting. They already tagged, failed through, or the window expired.")}

<h2>B — HTF 4h broken swing high, waiting on first 1m/2m retest</h2>
<p class="note">Parent freeze <code>intraday_htf_retest_20260916</code>. Level =
confirmed 4h swing high. Band = level ± 0.15 × HTF ATR. Waiting = that band has not
been tagged on 1m (or 1h proxy if the break is older than the 1m store), last close
still above the band floor, still inside the parent 3-bar window. One row per name.</p>
{_table(htf4_wait, charts, "No HTF 4h name is in the parent 3-bar window and still waiting. Same-session fills are common on this tape — check the tagged-today note and the second-touch bucket.")}

<h2>B2 — HTF 2h (optional, same geometry)</h2>
<p class="note">Same parent band (level ± 0.15 × 2h ATR) and first-retest rule.
Parent window is 4 bars of 2h. Not mixed into the 4h rank.</p>
{_table(htf2_wait, charts, "No HTF 2h name is in-window and still waiting.")}

<h2>Window expired — first retest still missing (recent only)</h2>
<p class="note">Broke, never tagged from above, last close still above/inside, but the
parent retest window has already closed. Kept only if the break is ≤10 sessions old.
<strong>Not</strong> mixed into the in-window shortlist. Same rank (dist/ATR, then age).
This is the “Monday break, Wednesday still has not come back” bucket.</p>
{_table(expired_recent, charts, "No recent expired-but-never-tagged names.")}

<h2>Already tagged — cheap second-touch only</h2>
<p class="note">These already used the first from-above retest. Shown only if last
close is still above/inside and remaining distance to the top is ≤ 1.0 × ADR.
<strong>Not</strong> “waiting for tomorrow.” Labeled so they are not confused with
a first touch.</p>
{_table(sorted(vz_second + htf_second, key=rank_key), charts, "No cheap second-touch names.")}

<h2>4h snapshots (top waiting / closest)</h2>
<p class="note">Purple band = zone or HTF retest band. Orange line = raw level.
Last close is the black dot. Pictures only.</p>
<div class="gallery">
{''.join(gallery) if gallery else '<p class="note">No charts (nobody close enough to snapshot).</p>'}
</div>

<h2>Coverage</h2>
<p class="note">Yahoo 1h → RTH 4h (same cache as the VZ 4h stamp). Daily ATR/ADR
from <code>data/newdata/data</code>. 1m store is short (Jul–Sep 2026). Click headers to sort.</p>
<table class="sortable">
<caption>Data coverage. Click column headers to sort.</caption>
<thead><tr>
{sortable_th("symbol", "text")}
{sortable_th("4h bars", "num")}
{sortable_th("last 4h", "date")}
{sortable_th("daily last", "date")}
{sortable_th("1m bars", "num")}
{sortable_th("1m last", "date")}
{sortable_th("note", "text")}
</tr></thead>
<tbody>
{''.join(cov_body)}
</tbody>
</table>

<p class="note">Parents:
<a href="../vz4h_3m_highvol_20260916/compare.html">vz4h_3m_highvol_20260916</a> ·
<a href="../intraday_htf_retest_20260916/charts_4h_1m_chandelier3.html">HTF 4h×1m gallery</a>.</p>
{SORT_JS}
</body>
</html>
"""
    path = STAMP / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    universe = frozen_universe()
    # Freeze rank rule on disk BEFORE sorting any write-up.
    write_baseline(universe, [])
    write_hypothesis()

    coverage: list[dict[str, Any]] = []
    vz_all: list[dict[str, Any]] = []
    htf_all: list[dict[str, Any]] = []
    htf_frames: dict[str, pd.DataFrame] = {}
    asof_bar = ""

    for i, sym in enumerate(universe, 1):
        print(f"[{i}/{len(universe)}] {sym}", flush=True)
        daily = load_daily(sym)
        rth_1h, htf4 = load_4h(sym)
        df1 = pd.DataFrame()
        try:
            raw1 = read_1m(sym, DEFAULT_1M_DIR)
            df1 = rth_filter(raw1)
            if not df1.empty:
                t1 = pd.to_datetime(df1["ts"], utc=True).dt.tz_convert(ET)
                df1 = df1.loc[t1.dt.date <= AS_OF].copy()
        except Exception as exc:  # noqa: BLE001
            print(f"  1m skip {sym}: {exc}", flush=True)

        cov = {
            "symbol": sym,
            "n_4h": int(len(htf4)) if htf4 is not None else 0,
            "last_4h": fmt_ts(htf4["ts"].iloc[-1]) if htf4 is not None and not htf4.empty else "",
            "daily_last": "",
            "n_1m": int(len(df1)),
            "last_1m": fmt_ts(df1["ts"].iloc[-1]) if not df1.empty else "",
            "note": "",
        }
        if not daily.empty:
            cov["daily_last"] = pd.Timestamp(daily["Date"].iloc[-1]).date().isoformat()
        if htf4 is None or htf4.empty:
            cov["note"] = "no 4h from 1h"
            coverage.append(cov)
            continue
        if not asof_bar:
            asof_bar = cov["last_4h"]
        htf_frames[sym] = htf4
        vz_all.extend(scan_vz(sym, htf4, daily))
        for htf_name in HTF_LIST_SCAN:
            htf_all.extend(scan_htf(sym, rth_1h, htf_name, daily, df1 if not df1.empty else None))
        coverage.append(cov)

    write_baseline(universe, coverage)

    vz_wait = pick_best_waiting([r for r in vz_all if r["setup"] == "VZ 4h"])
    # pick_best_waiting already prefers in-window; force in-window list
    vz_wait = [r for r in vz_wait if r.get("waiting")]
    vz_wait = sorted(vz_wait, key=rank_key)
    htf4_wait = pick_best_waiting([r for r in htf_all if r["htf"] == "4h" and r.get("waiting")])
    htf4_wait = sorted(htf4_wait, key=rank_key)
    htf2_wait = pick_best_waiting([r for r in htf_all if r["htf"] == "2h" and r.get("waiting")])
    htf2_wait = sorted(htf2_wait, key=rank_key)

    expired_pool = [
        r
        for r in (vz_all + htf_all)
        if r.get("waiting_expired") and int(r.get("sessions_since_break") or 999) <= 10
    ]
    expired_recent = sorted(expired_pool, key=rank_key)
    # one expired row per symbol+setup
    seen_e: set[tuple[str, str]] = set()
    expired_u: list[dict[str, Any]] = []
    for r in expired_recent:
        key = (r["symbol"], r["setup"])
        if key in seen_e:
            continue
        seen_e.add(key)
        expired_u.append(r)
    expired_recent = expired_u

    vz_second = sorted(
        [
            r
            for r in vz_all
            if r.get("second_touch")
            and r.get("is_current_3m")
            and int(r.get("sessions_since_break") or 999) <= ANCIENT_SESSIONS
        ],
        key=rank_key,
    )
    seen = set()
    vz_second_u = []
    for r in vz_second:
        if r["symbol"] in seen:
            continue
        seen.add(r["symbol"])
        vz_second_u.append(r)
    htf_second = []
    seen_h: set[tuple[str, str]] = set()
    for r in sorted(
        [
            x
            for x in htf_all
            if x.get("second_touch")
            and int(x.get("sessions_since_break") or 999) <= ANCIENT_SESSIONS
        ],
        key=rank_key,
    ):
        key = (r["symbol"], r["htf"])
        if key in seen_h:
            continue
        seen_h.add(key)
        htf_second.append(r)

    chart_src: list[dict[str, Any]] = []
    for bucket in (expired_recent, vz_wait, htf4_wait, vz_second_u, htf_second):
        for r in bucket:
            if r not in chart_src:
                chart_src.append(r)
            if len(chart_src) >= N_CHARTS:
                break
        if len(chart_src) >= N_CHARTS:
            break

    charts: dict[str, str] = {}
    for n, r in enumerate(chart_src[:N_CHARTS], 1):
        htf = htf_frames.get(r["symbol"])
        rel = f"charts/{n:02d}_{r['symbol']}_{r['setup'].replace(' ', '_')}.png"
        if htf is not None:
            plot_snapshot(r, htf, STAMP / rel)
            charts[f"{r['symbol']}|{r['setup']}"] = rel

    html_path = write_html(
        universe=universe,
        coverage=coverage,
        vz_wait=vz_wait,
        htf4_wait=htf4_wait,
        htf2_wait=htf2_wait,
        expired_recent=expired_recent,
        vz_second=vz_second_u,
        htf_second=htf_second,
        vz_all=vz_all,
        htf_all=htf_all,
        charts=charts,
        asof_bar=asof_bar or AS_OF.isoformat(),
    )

    def slim(r: dict[str, Any]) -> dict[str, Any]:
        skip = {"last_4h_vol"}
        return {k: v for k, v in r.items() if k not in skip and not isinstance(v, (np.ndarray, pd.Series))}

    payload = {
        "as_of": AS_OF.isoformat(),
        "tomorrow": TOMORROW.isoformat(),
        "universe": universe,
        "rank_rule": [
            "dist_hi_atr = max(0, last_close-zone_hi)/daily_ATR14",
            "sessions_since_break",
            "symbol",
        ],
        "vz_waiting": [slim(r) for r in vz_wait],
        "htf4_waiting": [slim(r) for r in htf4_wait],
        "htf2_waiting": [slim(r) for r in htf2_wait],
        "expired_recent": [slim(r) for r in expired_recent],
        "vz_second": [slim(r) for r in vz_second_u],
        "htf_second": [slim(r) for r in htf_second],
    }
    (STAMP / "summary.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(vz_all).to_csv(STAMP / "vz_all.csv", index=False)
    pd.DataFrame(htf_all).to_csv(STAMP / "htf_all.csv", index=False)
    print(f"wrote {html_path}", flush=True)
    print(
        f"VZ waiting {len(vz_wait)}  HTF4 waiting {len(htf4_wait)}  "
        f"HTF2 waiting {len(htf2_wait)}  expired-recent {len(expired_recent)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
