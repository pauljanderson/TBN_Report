#!/usr/bin/env python3
"""Clean-break carry length and exit check, 2026-09-26.

Follow-up to hv15m_day_zone_forward_20260925. One pattern only:
clean break of the highest high-volume 15-minute zone, zone source
"exclude the 15:45 close bar".

Two frozen questions, same tape, research only (not gold, not DailyRun):

1. Carry length, exit frozen as the original one-session close.
   N = 20 (the prior longest), 30, 40, and every prior session in this tape.
2. Exit rules. Lookback frozen at N=20. The same exit list is also
   scored at the full tape carry as a side look, not as a second pick.

The house in-sample / out-of-sample cut at 2024-01-01 does not apply.
Every bar in the 1-minute store is from 2026. A caution split is the
midpoint of this window only, report-only.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import hv15m_day_zone_forward_20260925 as base  # noqa: E402

sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import ann_ror_from_closed  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_clean_break_nmax_exit_20260926"
H1 = 26
H2 = 52
H5 = 130
N_ALL = 999
NS = (20, 30, 40, N_ALL)
ZONE_R_MIN = base.ZONE_R_MIN
ZONE_R_MAX = base.ZONE_R_MAX

ORIGINAL_REQUEST = (
    "i like this one and id like to explore further hv15m_day_zone_forward_20260925 "
    "Clean break of highest zone, Exclude 15:45 close bar. it looks like the best one "
    "was where we used the past 20 days. can we expand that to the max and see if "
    "results get better? also what is the exit on this? can we test different exits."
)

EXIT_SPEC = (
    # id, label, kind, horizon, target_R (None = time or stop-only)
    ("hold_1s", "Hold one session (original score)", "time", H1, None),
    ("hold_eod", "Sell that day's close", "eod", None, None),
    ("hold_2s", "Hold two sessions", "time", H2, None),
    ("hold_5s", "Hold five sessions", "time", H5, None),
    ("zone1r_1s", "Zone-low stop, 1R target, else one session", "bracket", H1, 1.0),
    ("zone2r_2s", "Zone-low stop, 2R target, else two sessions", "bracket", H2, 2.0),
    ("zone_stop_2s", "Zone-low stop, else hold two sessions", "stop_only", H2, None),
    ("pct1_2_2s", "1% stop, 2% target, else two sessions", "pct", H2, 2.0),
)


def _n_label(n: int) -> str:
    if int(n) >= N_ALL:
        return "999"
    return str(int(n))


def _carry_note(n: int) -> str:
    if int(n) >= N_ALL:
        return "every prior session on this tape"
    return f"{int(n)} trading days"


def _zones_ex_last(day, sess, bucket, low, high, vol, n, good_days) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    s_count = len(good_days)
    z_lo = np.full(s_count, np.nan)
    z_hi = np.full(s_count, np.nan)
    z_bkt = np.full(s_count, -1, dtype=np.int16)
    for s, d in enumerate(good_days):
        idx = np.flatnonzero((day == d) & (sess == s))
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


def _prior_best(z_hi: np.ndarray, valid: np.ndarray, n_carry: int) -> tuple[np.ndarray, np.ndarray]:
    s_count = len(z_hi)
    idx = np.full(s_count, -1, dtype=np.int32)
    best = np.full(s_count, -1e300)
    for s in range(s_count):
        s0 = s - n_carry
        if s0 < 0:
            s0 = 0
        bhi = -1e300
        bi = -1
        for zs in range(s0, s):
            if not valid[zs] or (s - zs) > n_carry:
                continue
            zh = float(z_hi[zs])
            if zh > bhi or (zh == bhi and zs > bi):
                bhi = zh
                bi = zs
        idx[s] = bi
        if bi >= 0:
            best[s] = bhi
    return idx, best


def _last_bar_of_day(day: np.ndarray) -> np.ndarray:
    n = len(day)
    last = np.empty(n, dtype=np.int32)
    i = n - 1
    while i >= 0:
        d = day[i]
        j = i
        while j >= 0 and day[j] == d:
            j -= 1
        start = j + 1
        last[start : i + 1] = i
        i = j
    return last


def _time_exit(close, entry_i: int, entry: float, horizon: int):
    end = entry_i + horizon
    if end > len(close):
        return None
    px = float(close[end - 1])
    if not np.isfinite(px):
        return None
    ret = px / entry - 1.0
    return {
        "ret": ret,
        "r": np.nan,
        "win": int(ret > 0),
        "exit_i": end - 1,
        "outcome": "time",
    }


def _eod_exit(close, day_last, entry_i: int, entry: float):
    k = int(day_last[entry_i])
    if k < entry_i:
        return None
    px = float(close[k])
    if not np.isfinite(px):
        return None
    ret = px / entry - 1.0
    return {"ret": ret, "r": np.nan, "win": int(ret > 0), "exit_i": k, "outcome": "time"}


def _bracket(high, low, close, entry_i, entry, stop, target, horizon, risk, stop_only: bool):
    """Stop is checked before the target on each bar. Same bar counts as a stop."""
    if entry_i + horizon > len(close):
        return None
    for k in range(horizon):
        i = entry_i + k
        if float(low[i]) <= stop:
            ret = stop / entry - 1.0
            return {"ret": ret, "r": -1.0, "win": 0, "exit_i": i, "outcome": "stop"}
        if (not stop_only) and float(high[i]) >= target:
            r_mult = (target - entry) / risk
            ret = target / entry - 1.0
            return {"ret": ret, "r": float(r_mult), "win": 1, "exit_i": i, "outcome": "target"}
    px = float(close[entry_i + horizon - 1])
    r_mult = (px - entry) / risk
    ret = px / entry - 1.0
    return {
        "ret": ret,
        "r": float(r_mult),
        "win": int(ret > 0) if stop_only else 0,
        "exit_i": entry_i + horizon - 1,
        "outcome": "time",
    }


def _score_exit(kind, horizon, target_r, o, h, l, c, day_last, entry_i, entry, zone_lo):
    if kind == "time":
        return _time_exit(c, entry_i, entry, int(horizon))
    if kind == "eod":
        return _eod_exit(c, day_last, entry_i, entry)
    stop = float(zone_lo)
    if kind == "pct":
        stop = entry * 0.99
        risk = entry - stop
        target = entry * 1.02
        return _bracket(h, l, c, entry_i, entry, stop, target, int(horizon), risk, False)
    if not np.isfinite(stop) or not (entry > stop):
        return None
    risk = entry - stop
    rp = risk / entry
    if not (ZONE_R_MIN <= rp <= ZONE_R_MAX):
        return None
    if kind == "stop_only":
        return _bracket(h, l, c, entry_i, entry, stop, entry, int(horizon), risk, True)
    target = entry + float(target_r) * risk
    return _bracket(h, l, c, entry_i, entry, stop, target, int(horizon), risk, False)


def _scan_symbol(sym: str, g: pd.DataFrame) -> list[dict]:
    g = g.sort_values(["day", "bucket"])
    day = g["day"].to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    o = g["open"].to_numpy(dtype=np.float64)
    h = g["high"].to_numpy(dtype=np.float64)
    l = g["low"].to_numpy(dtype=np.float64)
    c = g["close"].to_numpy(dtype=np.float64)
    v = g["volume"].to_numpy(dtype=np.float64)
    n = len(c)
    if n < H1 + 5:
        return []
    uniq = pd.unique(day)
    counts = pd.Series(day).value_counts()
    good_days = [d for d in uniq if int(counts.get(d, 0)) >= base.MIN_BARS_SESSION]
    if len(good_days) < base.MIN_SESSIONS:
        return []
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    z_lo, z_hi, z_bkt, valid = _zones_ex_last(day, sess, bucket, l, h, v, n, good_days)
    day_last = _last_bar_of_day(day)
    raw: list[dict] = []

    for n_carry in NS:
        prior_i, prior_hi = _prior_best(z_hi, valid, n_carry)
        clean_done = np.zeros(len(good_days), dtype=np.int8)
        for j in range(1, n - 1):
            s = int(sess[j])
            if s < 0 or int(sess[j - 1]) < 0:
                continue
            hi_z = int(prior_i[s])
            best_hi = float(prior_hi[s]) if hi_z >= 0 else -1e300
            if valid[s] and int(bucket[j]) > int(z_bkt[s]):
                zh_today = float(z_hi[s])
                if zh_today > best_hi or (zh_today == best_hi and s > hi_z):
                    hi_z = s
                    best_hi = zh_today
            if hi_z < 0 or clean_done[hi_z]:
                continue
            zh = float(z_hi[hi_z])
            if not (l[j] > zh and c[j] > zh and c[j - 1] <= zh):
                continue
            entry_i = j + 1
            entry = float(o[entry_i])
            if not np.isfinite(entry) or entry <= 0:
                continue
            clean_done[hi_z] = 1
            raw.append(
                {
                    "symbol": sym,
                    "side": "signal",
                    "N": int(n_carry),
                    "entry_i": entry_i,
                    "entry": entry,
                    "zone_lo": float(z_lo[hi_z]),
                    "day": pd.Timestamp(day[entry_i]).date().isoformat(),
                }
            )

    seen = set()
    for j in range(n):
        if int(bucket[j]) != 4 or int(sess[j]) < 0:
            continue
        d = day[j]
        if d in seen:
            continue
        seen.add(d)
        entry = float(o[j])
        if not np.isfinite(entry) or entry <= 0:
            continue
        raw.append(
            {
                "symbol": sym,
                "side": "baseline",
                "N": 0,
                "entry_i": j,
                "entry": entry,
                "zone_lo": np.nan,
                "day": pd.Timestamp(d).date().isoformat(),
            }
        )

    rows: list[dict] = []
    for sig in raw:
        for exit_id, _label, kind, horizon, target_r in EXIT_SPEC:
            if sig["side"] == "baseline" and kind in ("bracket", "stop_only"):
                continue
            got = _score_exit(
                kind, horizon, target_r, o, h, l, c, day_last,
                sig["entry_i"], sig["entry"], sig["zone_lo"],
            )
            if got is None:
                continue
            exit_day = pd.Timestamp(day[got["exit_i"]]).date()
            entry_day = pd.Timestamp(sig["day"]).date()
            rows.append(
                {
                    "symbol": sig["symbol"],
                    "side": sig["side"],
                    "N": sig["N"],
                    "exit": exit_id,
                    "day": sig["day"],
                    "entry_i": sig["entry_i"],
                    "ret": got["ret"],
                    "r": got["r"],
                    "win": got["win"],
                    "exit_i": got["exit_i"],
                    "outcome": got["outcome"],
                    "days_held": int((exit_day - entry_day).days),
                }
            )
    return rows


def _one_book(df: pd.DataFrame) -> pd.DataFrame:
    """One open trade per symbol, per carry, per exit. Next entry only after the prior exit bar."""
    if df.empty:
        return df
    keep_idx = []
    grouped = df.sort_values(["entry_i"]).groupby(["symbol", "side", "N", "exit"], sort=False)
    for _key, g in grouped:
        busy_until = -1
        for i, rec in g.iterrows():
            if int(rec["entry_i"]) <= busy_until:
                continue
            keep_idx.append(i)
            busy_until = int(rec["exit_i"])
    out = df.loc[keep_idx].copy()
    return out


def _stat_block(g: pd.DataFrame) -> dict:
    n = int(len(g))
    if n == 0:
        return {
            "signals": 0,
            "symbols": 0,
            "days": 0,
            "win_pct": np.nan,
            "avg": np.nan,
            "med": np.nan,
            "avg_exmax": np.nan,
            "day_avg": np.nan,
            "day_med": np.nan,
            "pf": np.nan,
            "exp_r": np.nan,
            "r_n": 0,
            "stop_pct": np.nan,
            "target_pct": np.nan,
            "time_pct": np.nan,
            "avg_days_held": np.nan,
            "ann_ror": np.nan,
        }
    ret = g["ret"].to_numpy(dtype=float)
    order = np.argsort(ret)
    ex = ret[order[:-1]] if n > 1 else ret
    by_day = g.groupby("day")["ret"].mean()
    wins = ret[ret > 0].sum()
    losses = ret[ret < 0].sum()
    pf = float(wins / abs(losses)) if losses < 0 else np.nan
    rr = g["r"].dropna()
    oc = g["outcome"]
    held = g["days_held"].to_numpy(dtype=float)
    held_pos = held[held > 0]
    avg_days = float(held_pos.mean()) if len(held_pos) else 0.0
    ann = ann_ror_from_closed(
        total_pnl=float(ret.sum()),
        n_trades=n,
        avg_days_held=avg_days,
        brt_cash=1.0,
    )
    return {
        "signals": n,
        "symbols": int(g["symbol"].nunique()),
        "days": int(g["day"].nunique()),
        "win_pct": float((ret > 0).mean()),
        "avg": float(ret.mean()),
        "med": float(np.median(ret)),
        "avg_exmax": float(ex.mean()),
        "day_avg": float(by_day.mean()),
        "day_med": float(by_day.median()),
        "pf": pf,
        "exp_r": float(rr.mean()) if len(rr) else np.nan,
        "r_n": int(len(rr)),
        "stop_pct": float((oc == "stop").mean()),
        "target_pct": float((oc == "target").mean()),
        "time_pct": float((oc == "time").mean()),
        "avg_days_held": avg_days if avg_days > 0 else np.nan,
        "ann_ror": float(ann) if ann is not None else np.nan,
    }


def _summarize(df: pd.DataFrame, half_cut: str) -> list[dict]:
    rows = []
    if df.empty:
        return rows
    for (side, n_carry, exit_id), g in df.groupby(["side", "N", "exit"], sort=False):
        slices = {
            "full": g,
            "early": g[g["day"] < half_cut],
            "late": g[g["day"] >= half_cut],
        }
        for window, sub in slices.items():
            rec = _stat_block(sub)
            rec.update(
                {
                    "side": side,
                    "N": int(n_carry),
                    "n_label": _n_label(int(n_carry)) if side == "signal" else "—",
                    "exit": exit_id,
                    "window": window,
                }
            )
            rows.append(rec)
    return rows


def _pick(rows: list[dict], side: str, n_carry: int, exit_id: str, window: str) -> dict | None:
    for r in rows:
        if r["side"] == side and r["N"] == n_carry and r["exit"] == exit_id and r["window"] == window:
            return r
    return None


def _pct(x, digits=2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann(x) -> str:
    """Book Ann ROR is already in percent (the helper multiplies by 100)."""
    if x is None or not np.isfinite(x):
        return "—"
    return f"{float(x):.1f}%"


def _num(x, digits=2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{float(x):.{digits}f}"


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def _td(val: str) -> str:
    return f"<td>{html.escape(val)}</td>"


EXIT_LABEL = {e[0]: e[1] for e in EXIT_SPEC}


def _row_cells(r: dict, extra: list[str]) -> str:
    return "<tr>" + "".join(_td(x) for x in extra) + "".join(
        _td(v)
        for v in (
            str(r["signals"]),
            str(r["symbols"]),
            str(r["days"]),
            _pct(r["win_pct"]),
            _pct(r["avg"]),
            _pct(r["med"]),
            _pct(r["avg_exmax"]),
            _pct(r["day_avg"]),
            _pct(r["day_med"]),
            _num(r["pf"]),
            _ann(r.get("ann_ror")),
            _num(r["exp_r"], 3),
            _pct(r["stop_pct"], 1),
            _pct(r["target_pct"], 1),
            _pct(r["time_pct"], 1),
        )
    ) + "</tr>"


def _metric_headers() -> str:
    return "".join(
        _th(lab, typ)
        for lab, typ in (
            ("Signals", "num"),
            ("Symbols", "num"),
            ("Days", "num"),
            ("Win %", "num"),
            ("Avg return", "num"),
            ("Median", "num"),
            ("Avg ex-best", "num"),
            ("Day-avg", "num"),
            ("Day-median", "num"),
            ("Profit factor", "num"),
            ("Ann ROR %", "num"),
            ("Expectancy (R)", "num"),
            ("Stopped", "num"),
            ("Hit target", "num"),
            ("Held to time", "num"),
        )
    )


def _verdict(rows: list[dict]) -> tuple[str, str]:
    """Quality check of longer carries vs N=20 on the original one-session exit."""
    control = _pick(rows, "signal", 20, "hold_1s", "full")
    late_c = _pick(rows, "signal", 20, "hold_1s", "late")
    bits = []
    better = []
    worse_or_flat = []
    for n_carry in NS:
        if n_carry == 20:
            continue
        cur = _pick(rows, "signal", n_carry, "hold_1s", "full")
        late = _pick(rows, "signal", n_carry, "hold_1s", "late")
        if control is None or cur is None or cur["signals"] == 0:
            continue
        avg_up = cur["avg"] > control["avg"] + 0.0005
        med_ok = cur["med"] >= control["med"] - 1e-6
        day_ok = np.isfinite(cur["day_avg"]) and np.isfinite(control["day_avg"]) and cur["day_avg"] >= control["day_avg"] - 0.0002
        day_med_ok = np.isfinite(cur["day_med"]) and cur["day_med"] >= 0
        late_med_ok = late is not None and np.isfinite(late["med"]) and late["med"] > 0 and late["signals"] >= 40
        line = (
            f"{_carry_note(n_carry)}: {cur['signals']} signals, average {_pct(cur['avg'])}, "
            f"median {_pct(cur['med'])}, day-average {_pct(cur['day_avg'])}, "
            f"typical day {_pct(cur['day_med'])}, later-half median {_pct(late['med'] if late else None)} "
            f"({late['signals'] if late else 0} later signals)."
        )
        bits.append(line)
        if avg_up and med_ok and day_ok and day_med_ok and late_med_ok:
            better.append(_carry_note(n_carry))
        else:
            worse_or_flat.append(_carry_note(n_carry))
    if better and not worse_or_flat:
        call = (
            "Longer than 20 trading days improved the average, the median, the typical day, "
            "and the later half on this tape. That is still one short window. It is not adopted."
        )
    elif better:
        call = (
            "A longer carry beat 20 days on the checklist in some rows and missed it in others. "
            "Nothing is adopted."
        )
    else:
        call = (
            "Stretching the zone past 20 trading days did not clear a stricter check than "
            "the pooled average. The first study already showed the average rising with a longer "
            "carry while the typical day and the later half did not. This pass does not treat a "
            "higher average alone as better. No longer carry is adopted."
        )
    if control and late_c:
        call += (
            f" Control (20 days, hold one session): average {_pct(control['avg'])}, "
            f"median {_pct(control['med'])}, day-average {_pct(control['day_avg'])}, "
            f"typical day {_pct(control['day_med'])}, later-half median {_pct(late_c['med'])} "
            f"on {late_c['signals']} signals."
        )
    detail = " ".join(bits)
    return call, detail


def _exit_blurb(rows: list[dict], n_carry: int) -> str:
    base_row = _pick(rows, "baseline", 0, "hold_1s", "full")
    parts = []
    for exit_id, label, _k, _h, _t in EXIT_SPEC:
        sig = _pick(rows, "signal", n_carry, exit_id, "full")
        late = _pick(rows, "signal", n_carry, exit_id, "late")
        drift = _pick(rows, "baseline", 0, exit_id, "full")
        if sig is None or sig["signals"] == 0:
            parts.append(f"{label}: no trades with a usable risk or enough bars.")
            continue
        extra = ""
        if drift is not None and drift["signals"] and np.isfinite(sig["avg"]) and np.isfinite(drift["avg"]):
            extra = f" The same exit on a 10:30 buy averaged {_pct(drift['avg'])}."
        elif exit_id.startswith("zone"):
            extra = " The 10:30 baseline has no zone, so this R result stands on its own."
        late_bit = ""
        if late is not None:
            late_bit = f" Later half: median {_pct(late['med'])} on {late['signals']} signals."
        parts.append(
            f"{label}: {sig['signals']} signals, average {_pct(sig['avg'])}, median {_pct(sig['med'])}, "
            f"win rate {_pct(sig['win_pct'])}, day-average {_pct(sig['day_avg'])}."
            + late_bit
            + extra
        )
    _ = base_row
    return " ".join(parts)


def write_reports(info: dict, half_cut: str, all_rows: list[dict], one_rows: list[dict], n20_check: dict) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    call, detail = _verdict(all_rows)
    exit20 = _exit_blurb(all_rows, 20)
    exit_all = _exit_blurb(all_rows, N_ALL)

    def table_for(rows: list[dict], side: str, exit_id: str | None, n_list: tuple[int, ...] | None, caption: str) -> str:
        head_extra = []
        if n_list is not None:
            head_extra.append(_th("Carry days", "num"))
        if exit_id is None:
            head_extra.append(_th("Exit", "text"))
        if side == "both":
            head_extra.append(_th("Book", "text"))
        body = []
        use = [r for r in rows if r["window"] == "full"]
        if side != "both":
            use = [r for r in use if r["side"] == side]
        if exit_id is not None:
            use = [r for r in use if r["exit"] == exit_id]
        if n_list is not None:
            use = [r for r in use if r["N"] in n_list or (side == "baseline")]
        use.sort(key=lambda r: (0 if r["side"] == "signal" else 1, r["N"], r["exit"]))
        for r in use:
            extra = []
            if n_list is not None:
                extra.append(r["n_label"] if r["side"] == "signal" else "—")
            if exit_id is None:
                extra.append(EXIT_LABEL.get(r["exit"], r["exit"]))
            if side == "both":
                extra.append("Clean break" if r["side"] == "signal" else "Buy at 10:30")
            body.append(_row_cells(r, extra))
        return (
            f'<table class="sortable"><caption>{html.escape(caption)}</caption><thead><tr>'
            + "".join(head_extra)
            + _metric_headers()
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table>"
        )

    def half_table(rows: list[dict], exit_id: str) -> str:
        body = []
        for n_carry in NS:
            for window, label in (("early", f"Before {half_cut}"), ("late", f"On or after {half_cut}")):
                r = _pick(rows, "signal", n_carry, exit_id, window)
                if r is None:
                    continue
                body.append(
                    _row_cells(r, [_n_label(n_carry), label])
                )
        b_early = _pick(rows, "baseline", 0, exit_id, "early")
        b_late = _pick(rows, "baseline", 0, exit_id, "late")
        if b_early:
            body.append(_row_cells(b_early, ["—", f"10:30 before {half_cut}"]))
        if b_late:
            body.append(_row_cells(b_late, ["—", f"10:30 on or after {half_cut}"]))
        return (
            '<table class="sortable"><caption>Caution split on the same exit. Not used to pick a winner.</caption><thead><tr>'
            + _th("Carry days", "num")
            + _th("Window", "text")
            + _metric_headers()
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table>"
        )

    match = (
        f"This script’s 20-day, one-session score has {n20_check['signals']} signals and an average of "
        f"{_pct(n20_check['avg'])}. The prior page’s clean-break, exclude-15:45, N=20 row was 979 signals "
        f"and an average of 0.61%. "
        + (
            "Those match, so the longer carries are the same buy with a longer memory."
            if n20_check.get("match")
            else "Those do not match. Read the longer-carry table as a new count, and do not treat it as a strict extension until the difference is explained."
        )
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Clean break — longer carry and exits, 20260926</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px auto; max-width: 1180px; color: #1a1a1a; line-height: 1.45; }}
h1 {{ font-size: 1.6rem; }}
h2 {{ font-size: 1.2rem; margin-top: 1.6rem; }}
.callout {{ background: #f4f7fb; border: 1px solid #d5deea; padding: 12px 16px; margin: 12px 0; }}
.plain {{ background: #f8f6f1; }}
.note {{ color: #444; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 6px 8px; }}
th:first-child, td:first-child {{ text-align: left; }}
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
<h1>Clean break of the highest zone — longer memory, and other ways to sell</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Not the daily Volume Zone (VZ) system. Same 15-minute tape as <code>hv15m_day_zone_forward_20260925</code>: {html.escape(info["date_min"])} to {html.escape(info["date_max"])}, {info["symbols_liquid"]} liquid symbols. Click column headers to sort.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ORIGINAL_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>We kept the buy you liked. Each day we draw a band from the low to the high of that day’s busiest 15-minute candle, skipping the last candle of the day (the one that starts at 15:45), because the closing auction often makes that candle the busiest. A buy is the first time a later 15-minute candle sits entirely above the highest band that is still “alive.” We buy the next 15-minute bar’s open.</p>
<p>Last time the longest memory was 20 trading days, and that row had the highest average trade. This tape only runs from late July 2026 through 24 September 2026, about nine weeks, so the longest memory we can test is “every earlier day in that window.” We try 30 days, 40 days, and that full window, and we ask whether the trade actually gets better, not only whether the average of all trades rises.</p>
<p>The original score was not a stop. It was “hold about one regular session, then look at the price.” Below we say that plainly, then we try several other sell rules on the 20-day memory. The full-window memory gets the same sell rules as a side look. We do not pick a favorite from that side look.</p>
</div>

<h2>What the exit was</h2>
<p>On the first page, the main number is the change from the buy price to the close <strong>26 fifteen-minute bars later</strong> (one regular session, including the bar you bought). There is no stop in that number. Two side checks sat next to it, still inside that same session: whether price traded 1% higher before it traded 1% lower, and whether price reached a profit equal to the distance down to the zone’s low before it traded through that low. If the stop and the target hit on the same bar, it counts as a loss. If the distance from the buy to the zone’s low is under 0.10% of price or over 8%, that R (risk multiple) check is left out as too tight or too wide.</p>
<p class="note">{html.escape(match)}</p>

<h2>Does a longer memory help?</h2>
<p>{html.escape(call)}</p>
<p>{html.escape(detail)}</p>
<p class="note">Carry 999 means every prior session on this tape (the 1-minute store starts {html.escape(info["date_min"])}). Exit is frozen as the original one-session close. Overlapping buys are all counted, same as the first page. That is a signal score, not one account’s profit, drawdown, or Calmar ratio (return divided by the worst decline).</p>
<p class="note">Ann ROR % is the book formula: take one plus the average trade, raise it to 365 divided by the average calendar days held, then subtract one. Calendar days are the exit date minus the entry date. A trade that opens and closes on the same date has a hold of zero and is left out of that day average, the same way the book code skips a zero-day hold. If every trade in a row is same-day, the cell is blank, because the formula would divide by zero. The average trade stands in for total profit divided by stake times number of trades, which is the same figure when every trade uses the same stake. This annualizes that average trade. It is not the growth of one account, because many of these buys are open at the same time.</p>
{table_for(all_rows, "both", "hold_1s", NS, "Carry length, original one-session exit. 10:30 row is the no-zone drift under that same hold.")}
{half_table(all_rows, "hold_1s")}

<h2>Other ways to sell (20-day zones)</h2>
<p>Lookback stays at 20 trading days, the row you asked to extend. Each row is a different sell rule on that same buy. A time rule’s expectancy column is blank because there is no risk distance. A zone stop uses the zone’s low. Profit factor is gross winning dollars divided by gross losing dollars on the percent result. Day-average is the average of each calendar day’s average return, so one strong market day weighs once.</p>
<p>{html.escape(exit20)}</p>
{table_for([r for r in all_rows if r["side"] == "signal" and r["N"] == 20], "signal", None, None, "Exits on the 20-day clean break. Every signal, even when several are open in the same symbol.")}
{table_for([r for r in all_rows if r["side"] == "baseline" and r["exit"] in ("hold_1s", "hold_eod", "hold_2s", "hold_5s", "pct1_2_2s")], "baseline", None, None, "Same sell rules on a 10:30 buy with no zone, where that rule does not need a zone.")}

<h2>Same exits if the zone never expires</h2>
<p class="note">Side look only. The carry was not frozen before seeing these numbers. Do not treat a winner here as chosen. Later-half numbers are printed in the table via the day columns on the full set; the caution split for the one-session exit is above.</p>
<p>{html.escape(exit_all)}</p>
{table_for([r for r in all_rows if r["side"] == "signal" and r["N"] == N_ALL], "signal", None, None, "Exits when every prior zone in this tape is still eligible. Same buy. Not a second freeze.")}

<h2>One trade at a time per symbol</h2>
<p>The tables above count every signal, so a five-session hold can stack many buys in one name. This table keeps a symbol out of a new trade until the prior one has been sold. It is still not a sized portfolio.</p>
{table_for([r for r in one_rows if not (r["side"] == "signal" and r["N"] not in (20, N_ALL))], "both", None, (20, N_ALL), "One open trade per symbol. Carry 20 and carry 999, plus the 10:30 baseline on the time rules and the 1% / 2% rule.")}

<h2>Freeze</h2>
<ul>
<li>Buy: clean break of the highest active zone (the whole bar is above the zone high, the prior close was not, first time for that zone). Fill is the next 15-minute open.</li>
<li>Zone source: highest-volume 15-minute bar that starts before 15:45. Ties go to the earlier bar.</li>
<li>Control carry: 20 trading days after the birth session, matching the prior page. Tested carries: 30, 40, and 999 (every prior session).</li>
<li>Control exit: close of the 26th 15-minute bar starting at the fill. Other exits are listed in the table and are not a menu to mix.</li>
<li>Universe and dates: liquid names from the parent study, {html.escape(info["date_min"])} through {html.escape(info["date_max"])}.</li>
<li>Caution split: entry before {html.escape(half_cut)} versus on or after. Report only. The 2024-01-01 in-sample / out-of-sample split cannot be built from this store.</li>
<li>Selection: the clean-break and the exclude-15:45 zone were already the preferred look on this same tape. This page does not adopt a longer carry or a new exit.</li>
<li>Ann ROR %: book formula, one plus the average trade, raised to 365 divided by average calendar days held, minus one. Same-calendar-day holds are left out of the day average. The cell is blank when every trade in the row is same-day.</li>
</ul>
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

    baseline_md = f"""# Clean break — longer carry and exits

Study id: `hv15m_clean_break_nmax_exit_20260926`

Parent: `hv15m_day_zone_forward_20260925`. Research only. Not gold. Not DailyRun. Not the daily Volume Zone (VZ) system.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

The buy is unchanged: first 15-minute bar that sits entirely above the highest still-active high-volume zone, ignoring the 15:45 close bar when the zone is chosen, fill at the next open. Last time 20 trading days was the longest memory and had the highest average. This tape is only about nine weeks (from {info["date_min"]} to {info["date_max"]}), so the longest memory is every earlier session. We test 30, 40, and that full window with the original one-session score, then we try other sell rules on the 20-day memory.

## What the exit was

The original main score holds for 26 fifteen-minute bars (one regular session) and uses that bar’s close. It has no stop. Side checks, still inside one session: +1% before −1%, and a zone-low stop with a 1R target (same-bar stop and target counts as a loss; risk under 0.10% or over 8% of price is dropped).

## Freeze

- Pattern: clean break of the highest zone. Zone source: exclude 15:45.
- Control carry: 20. Tested: 30, 40, 999 (every prior session on this tape).
- Control exit: 26-bar close. Other exits are a separate question, scored at N=20. N=999 exits are a side look, not a pick.
- Caution split: entry before {half_cut} vs on or after. Report only. No 2024-01-01 split exists in this store.
- Selection: this pattern and zone source were already the preferred look on the same tape. No carry and no exit is adopted from this page.
- Ann ROR % uses the book formula on the average trade and calendar days held (exit date minus entry date). Same-day holds are left out of the day average. It is not one account’s compounded return.

## Check against the parent

{match}

## Longer carry

{call}

{detail}

## Exits at 20 days

{exit20}
"""
    (STAMP / "BASELINE.md").write_text(baseline_md, encoding="utf-8")
    print(f"wrote {STAMP / 'compare.html'}", flush=True)


def main() -> int:
    con = __import__("duckdb").connect()
    bars = base.build_15m(con)
    liquid, info = base.select_universe(bars)
    days_sorted = sorted(pd.to_datetime(liquid["day"]).dt.date.unique())
    half_cut = days_sorted[len(days_sorted) // 2].isoformat() if days_sorted else "2026-08-24"
    print(f"half cut {half_cut} days {len(days_sorted)} symbols {info['symbols_liquid']}", flush=True)
    rows: list[dict] = []
    n_sym = 0
    for sym, g in liquid.groupby("symbol", sort=False):
        rows.extend(_scan_symbol(str(sym), g))
        n_sym += 1
        if n_sym % 100 == 0:
            print(f"  {n_sym} symbols, rows {len(rows):,}", flush=True)
    print(f"rows {len(rows):,}", flush=True)
    df = pd.DataFrame(rows)
    STAMP.mkdir(parents=True, exist_ok=True)
    df.drop(columns=[], errors="ignore").to_csv(STAMP / "outcomes.csv", index=False)
    all_stats = _summarize(df, half_cut)
    one = _one_book(df)
    one_stats = _summarize(one, half_cut)
    n20 = _pick(all_stats, "signal", 20, "hold_1s", "full") or {"signals": 0, "avg": float("nan")}
    n20_check = {
        "signals": int(n20["signals"]),
        "avg": float(n20["avg"]) if n20["signals"] else float("nan"),
        "match": int(n20["signals"]) == 979 and abs(float(n20["avg"]) - 0.00612) < 0.0004,
    }
    print("N20 check", n20_check, flush=True)
    write_reports(info, half_cut, all_stats, one_stats, n20_check)
    (STAMP / "scan_meta.json").write_text(
        json.dumps({"info": info, "half_cut": half_cut, "n20_check": n20_check}, indent=2, default=str),
        encoding="utf-8",
    )
    print("--- hold_1s by N ---", flush=True)
    for n_carry in NS:
        r = _pick(all_stats, "signal", n_carry, "hold_1s", "full")
        late = _pick(all_stats, "signal", n_carry, "hold_1s", "late")
        if r:
            print(
                f"N={n_carry} n={r['signals']} avg={_pct(r['avg'])} med={_pct(r['med'])} "
                f"day={_pct(r['day_avg'])} daymed={_pct(r['day_med'])} "
                f"ann={_ann(r.get('ann_ror'))} days={_num(r.get('avg_days_held'), 2)} "
                f"late_n={late['signals'] if late else 0} late_med={_pct(late['med'] if late else None)}",
                flush=True,
            )
    print("--- exits N=20 ---", flush=True)
    for exit_id, label, *_rest in EXIT_SPEC:
        r = _pick(all_stats, "signal", 20, exit_id, "full")
        if r:
            print(
                f"{exit_id:12} n={r['signals']:<5} avg={_pct(r['avg']):8} med={_pct(r['med']):8} "
                f"win={_pct(r['win_pct']):7} ann={_ann(r.get('ann_ror')):8} "
                f"days={_num(r.get('avg_days_held'), 2):6} expR={_num(r['exp_r'], 3):8} pf={_num(r['pf'])}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
