#!/usr/bin/env python3
"""Clean-break control vs a buy on the first bar whose low is above the zone.

Control is the live watch rule: the whole 15-minute bar is above the highest
active zone, the prior close was not, and it is the first time for that zone.
The candidate drops only the prior-close test. The first bar whose low is
above the zone high is the buy, even if an earlier bar already closed above.

Both arms keep the rest of the freeze: zone age 4 to 8, trigger from 09:30
through 11:00 Eastern, and the signal close at least 20% under the prior
252-trading-day high. That yearly-high test is the rule that blocks a name
that has already run up, including an opening gap. There is no separate
percent cap on the overnight gap.

Research only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import hv15m_clean_break_n20_signal_ledger_20260927 as led  # noqa: E402
import hv15m_day_zone_forward_20260925 as base  # noqa: E402
import report_page_extras as extras  # noqa: E402
from compare_format import DEFAULT_INITIAL_ACCOUNT, overlay_ann_ror_max_dd  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_low_above_ignore_prior_close_20261014"
BARS = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_stop_grid_20260927" / "live_15m.parquet"
N_CARRY = 20
AGES = {4, 5, 6, 7, 8}
MORNING_MAX_BUCKET = 6  # 09:30 through 11:00
PCT_FLOOR = 0.20
H26 = 26
STOPS = (0.01, 0.02, 0.03, 0.04)
SLOT = 10_000.0
IS_CUT = date(2024, 1, 1)

ASK = (
    "can you show me a report using this rule as control and a new rule that allows "
    "a buy on any bar whose low is above the trigger regardless of previous candle close. "
    "keep whatever rule is in place for not allowing a buy at the open if it gapes up too much"
)


def _bkt_label(bucket: int) -> str:
    mins = 9 * 60 + 30 + int(bucket) * 15
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _elect(day, bucket, low, high, vol, sess, good_days):
    s_count = len(good_days)
    z_lo = np.full(s_count, np.nan)
    z_hi = np.full(s_count, np.nan)
    z_bkt = np.full(s_count, -1, dtype=np.int16)
    for s, d in enumerate(good_days):
        idx = np.flatnonzero((day == d) & (sess == s))
        idx = idx[bucket[idx] < 25]
        if len(idx) == 0:
            continue
        best = idx[int(np.lexsort((bucket[idx], -vol[idx]))[0])]
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
    s0 = max(0, s - N_CARRY)
    hi_z = -1
    best = -1e300
    for zs in range(s0, s + 1):
        if zs >= n or not valid[zs] or done[zs]:
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


def _path(opens, low, close, days, entry_i: int) -> dict | None:
    end = entry_i + H26
    if end > len(close):
        return None
    entry = float(opens[entry_i])
    if not np.isfinite(entry) or entry <= 0:
        return None
    hold_l = low[entry_i:end]
    hold_c = close[entry_i:end]
    sold = float(hold_c[-1])
    if not np.isfinite(sold):
        return None
    fwd = sold / entry - 1.0
    entry_day = days[entry_i]
    exit_day = days[end - 1]
    held = max(1, (pd.Timestamp(exit_day) - pd.Timestamp(entry_day)).days)
    path_exit = pd.Timestamp(exit_day).date().isoformat()
    stop_exit: dict[float, str] = {}
    stops = {}
    stop_days = {}
    for stop in STOPS:
        level = entry * (1.0 - stop)
        hit_at = None
        for k, lo in enumerate(hold_l):
            if float(lo) <= level + 1e-9:
                hit_at = k
                break
        if hit_at is None:
            stops[stop] = fwd
            stop_days[stop] = held
            stop_exit[stop] = path_exit
        else:
            stops[stop] = -stop
            sd = days[entry_i + hit_at]
            stop_days[stop] = max(1, (pd.Timestamp(sd) - pd.Timestamp(entry_day)).days)
            stop_exit[stop] = pd.Timestamp(sd).date().isoformat()
    return {
        "entry": entry,
        "entry_date": pd.Timestamp(entry_day).date().isoformat(),
        "exit_date": pd.Timestamp(exit_day).date().isoformat(),
        "fwd": fwd,
        "days": held,
        "stops": stops,
        "stop_days": stop_days,
        "stop_exit": stop_exit,
    }


def scan_symbol(sym: str, g: pd.DataFrame, pack: dict | None) -> list[dict]:
    g = g.sort_values(["day", "bucket"])
    day = pd.to_datetime(g["day"]).dt.date.to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    opens = g["open"].to_numpy(dtype=np.float64)
    high = g["high"].to_numpy(dtype=np.float64)
    low = g["low"].to_numpy(dtype=np.float64)
    close = g["close"].to_numpy(dtype=np.float64)
    vol = g["volume"].to_numpy(dtype=np.float64)
    n = len(close)
    if n < 30:
        return []
    uniq = list(pd.unique(day))
    counts: dict = {}
    for d in day:
        counts[d] = counts.get(d, 0) + 1
    good_days = [d for d in uniq if counts[d] >= base.MIN_BARS_SESSION]
    if len(good_days) < 8:
        return []
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    z_lo, z_hi, z_bkt, valid = _elect(day, bucket, low, high, vol, sess, good_days)
    if not np.any(valid):
        return []
    done_c = np.zeros(len(good_days), dtype=np.int8)
    done_a = np.zeros(len(good_days), dtype=np.int8)
    order = [i for i in range(n) if sess[i] >= 0]
    rows: list[dict] = []
    for k, i in enumerate(order):
        if k == 0:
            continue
        prev = order[k - 1]
        s = int(sess[i])
        b = int(bucket[i])
        for arm, done in (("control", done_c), ("low_above", done_a)):
            hi_z = _highest(z_hi, valid, z_bkt, done, s, b)
            if hi_z < 0:
                continue
            zh = float(z_hi[hi_z])
            prior_under = float(close[prev]) <= zh
            if arm == "control":
                hit = float(low[i]) > zh and float(close[i]) > zh and prior_under
            else:
                # A 9:30 bar that is already above the zone is an overnight gap.
                # Keep the control rule there: buy it only when yesterday's close
                # was still at or under the zone. Do not use up the zone if that
                # open is rejected, so a later bar can still qualify.
                if b == 0 and not prior_under:
                    continue
                hit = float(low[i]) > zh
            if not hit:
                continue
            done[hi_z] = 1
            age = s - hi_z
            if age not in AGES or b > MORNING_MAX_BUCKET:
                continue
            path = _path(opens, low, close, day, i + 1)
            if path is None:
                continue
            sig_close = float(close[i])
            pct, hi252, hi_date = (float("nan"), float("nan"), "")
            if pack is not None:
                ix = led._prior_index(pack["day"], day[i])
                hi252, hi_date, n_used = led._window_high(
                    pack["day"], pack["high"], ix + 1, led.YEAR_BARS, None
                )
                if n_used < led.MIN_YEAR_BARS:
                    hi252, hi_date = float("nan"), ""
                pct = led._pct_below(hi252, sig_close)
            if not np.isfinite(pct) or pct < PCT_FLOOR:
                continue
            born = good_days[hi_z]
            rows.append(
                {
                    "arm": arm,
                    "symbol": sym,
                    "signal_date": pd.Timestamp(day[i]).date().isoformat(),
                    "signal_time": _bkt_label(b),
                    "zone_date": pd.Timestamp(born).date().isoformat(),
                    "zone_time": _bkt_label(int(z_bkt[hi_z])),
                    "zone_age": int(age),
                    "zone_hi": zh,
                    "zone_lo": float(z_lo[hi_z]),
                    "signal_low": float(low[i]),
                    "signal_close": sig_close,
                    "prior_close": float(close[prev]),
                    "prior_was_under": bool(prior_under),
                    "pct_below": float(pct),
                    "high_252": float(hi252) if np.isfinite(hi252) else float("nan"),
                    "high_252_date": hi_date,
                    **path,
                }
            )
    return rows


def load_rows() -> pd.DataFrame:
    print("reading 15-minute cache...", flush=True)
    bars = pd.read_parquet(BARS)
    names = sorted(bars["symbol"].astype(str).unique())
    print(f"daily 252-day highs for {len(names)} symbols...", flush=True)
    daily = led.load_daily(names)
    grouped = {sym: g for sym, g in bars.groupby(bars["symbol"].astype(str), sort=False)}
    rows: list[dict] = []
    for i, sym in enumerate(names, 1):
        rows.extend(scan_symbol(sym, grouped[sym], daily.get(sym)))
        if i % 200 == 0 or i == len(names):
            print(f"  scanned {i}/{len(names)} signals {len(rows)}", flush=True)
    return pd.DataFrame(rows)


def _book_metrics(g: pd.DataFrame, ret_col: str, days_col: str, exit_col: str = "exit_date") -> dict:
    n = int(len(g))
    if n == 0:
        return {"n": 0}
    r = g[ret_col].to_numpy(dtype=float)
    wins = r[r > 0]
    losses = r[r < 0]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else float("nan")
    wo = np.sort(r)[:-1] if n > 1 else r
    trades = []
    for rec in g.itertuples(index=False):
        pct = float(getattr(rec, ret_col))
        trades.append(
            {
                "opened": getattr(rec, "entry_date"),
                "closed": getattr(rec, exit_col),
                "days": float(getattr(rec, days_col)),
                "pnl_d": pct * SLOT,
                "pnl": pct * 100.0,
            }
        )
    if days_col != "days":
        # Stop exits close on the stop day stored beside the return.
        pass
    ov_full = overlay_ann_ror_max_dd(trades, cash=SLOT, initial_account=DEFAULT_INITIAL_ACCOUNT)
    is_rows = [t for t, opened in zip(trades, g["entry_date"]) if date.fromisoformat(str(opened)) < IS_CUT]
    oos_rows = [t for t, opened in zip(trades, g["entry_date"]) if date.fromisoformat(str(opened)) >= IS_CUT]
    ov_is = overlay_ann_ror_max_dd(is_rows, cash=SLOT, initial_account=DEFAULT_INITIAL_ACCOUNT)
    ov_oos = overlay_ann_ror_max_dd(oos_rows, cash=SLOT, initial_account=DEFAULT_INITIAL_ACCOUNT)
    return {
        "n": n,
        "symbols": int(g["symbol"].nunique()),
        "win": float((r > 0).mean()),
        "avg": float(r.mean()),
        "med": float(np.median(r)),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "pf": pf,
        "expect": float(r.mean()),
        "wo_max": float(wo.mean()) if len(wo) else float("nan"),
        "avg_days": float(g[days_col].mean()),
        "full": ov_full,
        "is": ov_is,
        "oos": ov_oos,
        "n_is": len(is_rows),
        "n_oos": len(oos_rows),
    }


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _num(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{float(x):.{digits}f}"


def _delta_pct(a, b) -> str:
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
        return "—"
    return f"{100.0 * (float(b) - float(a)):+.2f} pp"


def _delta_num(a, b, digits=2) -> str:
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
        return "—"
    return f"{float(b) - float(a):+.{digits}f}"


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _table(headers, rows) -> str:
    head = "".join(_th(h, k) for h, k in headers)
    body = []
    for row in rows:
        tds = []
        for text, num in row:
            style = ' style="text-align:right"' if num else ""
            tds.append(f"<td{style}>{html.escape(text)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        extras.SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _metric_rows(control: dict, cand: dict) -> list:
    def ann(book, key):
        ov = book.get(key) or {}
        v = ov.get("ann_ror")
        return v

    def dd(book, key):
        ov = book.get(key) or {}
        return ov.get("max_dd")

    def sh(book, key):
        ov = book.get(key) or {}
        return ov.get("sharpe")

    rows_spec = [
        ("Trades", control["n"], cand["n"], "num", False),
        ("Symbols", control["symbols"], cand["symbols"], "num", False),
        ("Win %", control["win"], cand["win"], "pct", True),
        ("Avg return", control["avg"], cand["avg"], "pct", True),
        ("Median return", control["med"], cand["med"], "pct", True),
        ("Avg win", control["avg_win"], cand["avg_win"], "pct", True),
        ("Avg loss", control["avg_loss"], cand["avg_loss"], "pct", True),
        ("Profit factor", control["pf"], cand["pf"], "num", False),
        ("Avg return without the best trade", control["wo_max"], cand["wo_max"], "pct", True),
        ("Avg days held", control["avg_days"], cand["avg_days"], "num", False),
        ("Annualized rate of return, full book", ann(control, "full"), ann(cand, "full"), "ann", False),
        ("Annualized rate of return, in-sample", ann(control, "is"), ann(cand, "is"), "ann", False),
        ("Annualized rate of return, out-of-sample", ann(control, "oos"), ann(cand, "oos"), "ann", False),
        ("Max drawdown, full book", dd(control, "full"), dd(cand, "full"), "dd", False),
        ("Max drawdown, in-sample", dd(control, "is"), dd(cand, "is"), "dd", False),
        ("Max drawdown, out-of-sample", dd(control, "oos"), dd(cand, "oos"), "dd", False),
        ("Sharpe, full book", sh(control, "full"), sh(cand, "full"), "num", False),
        ("Sharpe, out-of-sample", sh(control, "oos"), sh(cand, "oos"), "num", False),
        ("Calmar, full book", (control.get("full") or {}).get("calmar"), (cand.get("full") or {}).get("calmar"), "num", False),
    ]
    out = []
    for label, a, b, kind, is_frac in rows_spec:
        if kind == "pct":
            fa, fb, dlt = _pct(a), _pct(b), _delta_pct(a, b)
        elif kind == "ann":
            fa = _num(a) + "%" if a is not None and np.isfinite(a) else "—"
            fb = _num(b) + "%" if b is not None and np.isfinite(b) else "—"
            dlt = _delta_num(a, b) + " pp" if a is not None and b is not None and np.isfinite(a) and np.isfinite(b) else "—"
        elif kind == "dd":
            fa = _num(a) + "%" if a is not None and np.isfinite(a) else "—"
            fb = _num(b) + "%" if b is not None and np.isfinite(b) else "—"
            dlt = _delta_num(a, b) + " pp" if a is not None and b is not None and np.isfinite(a) and np.isfinite(b) else "—"
        else:
            if label in {"Trades", "Symbols"}:
                fa, fb = str(int(a)), str(int(b))
                dlt = f"{int(b) - int(a):+d}"
            else:
                fa, fb = _num(a), _num(b)
                dlt = _delta_num(a, b)
        out.append([(label, False), (fa, True), (fb, True), (dlt, True)])
    return out


def _attach_stop_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for stop in STOPS:
        key = f"{int(stop * 100)}pct"
        out[f"ret_{key}"] = [float(rec[stop]) for rec in out["stops"]]
        out[f"days_{key}"] = [int(rec[stop]) for rec in out["stop_days"]]
        out[f"exit_{key}"] = [rec[stop] for rec in out["stop_exit"]]
    return out


def render(df: pd.DataFrame) -> str:
    control = df[df["arm"] == "control"].copy()
    cand = df[df["arm"] == "low_above"].copy()
    c_key = set(zip(control["symbol"], control["signal_date"], control["signal_time"]))
    a_key = set(zip(cand["symbol"], cand["signal_date"], cand["signal_time"]))
    only = cand[~cand.apply(lambda r: (r["symbol"], r["signal_date"], r["signal_time"]) in c_key, axis=1)].copy()
    shared = len(c_key & a_key)
    mc = _book_metrics(control, "fwd", "days")
    ma = _book_metrics(cand, "fwd", "days")

    stop_rows = []
    for stop in STOPS:
        key = f"{int(stop * 100)}pct"
        sc = _book_metrics(control, f"ret_{key}", f"days_{key}", f"exit_{key}")
        sa = _book_metrics(cand, f"ret_{key}", f"days_{key}", f"exit_{key}")
        stop_rows.append(
            [
                (f"{int(stop * 100)}% stop", False),
                (str(sc["n"]), True),
                (_pct(sc["avg"]), True),
                (_pct(sc["win"]), True),
                (_num(sc["full"].get("ann_ror")) + "%" if np.isfinite(sc["full"].get("ann_ror", np.nan)) else "—", True),
                (_num(sc["full"].get("max_dd")) + "%" if np.isfinite(sc["full"].get("max_dd", np.nan)) else "—", True),
                (str(sa["n"]), True),
                (_pct(sa["avg"]), True),
                (_pct(sa["win"]), True),
                (_num(sa["full"].get("ann_ror")) + "%" if np.isfinite(sa["full"].get("ann_ror", np.nan)) else "—", True),
                (_num(sa["full"].get("max_dd")) + "%" if np.isfinite(sa["full"].get("max_dd", np.nan)) else "—", True),
            ]
        )

    extra_rows = []
    show = only.sort_values(["signal_date", "symbol"])
    for rec in show.itertuples(index=False):
        extra_rows.append(
            [
                (rec.symbol, False),
                (rec.signal_date, False),
                (rec.signal_time, False),
                (str(int(rec.zone_age)), True),
                (f"{rec.zone_hi:.2f}", True),
                (f"{rec.signal_low:.2f}", True),
                (f"{rec.prior_close:.2f}", True),
                ("yes" if rec.prior_was_under else "no", False),
                (f"{rec.entry:.2f}", True),
                (_pct(rec.fwd), True),
                (_pct(rec.pct_below), True),
            ]
        )

    date_min = str(df["entry_date"].min()) if len(df) else "—"
    date_max = str(df["entry_date"].max()) if len(df) else "—"
    verdict = (
        f"The candidate adds {len(only)} closed trades the control does not take. "
        f"Shared signals: {shared}. Control average return {_pct(mc.get('avg'))} on {mc.get('n')} trades. "
        f"Candidate average return {_pct(ma.get('avg'))} on {ma.get('n')} trades."
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{extras.CACHE_META}
<title>Clean break vs low-above trigger</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif; margin: 16px auto; max-width: 1100px; padding: 0 12px 48px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #475569; font-size: 0.92rem; }}
{extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Clean break vs a later bar whose low clears the zone</h1>
<p class="note">Research only. Not gold. Not DailyRun. Built {html.escape(now)}. Closed trades from {html.escape(date_min)} through {html.escape(date_max)}. Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ASK)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>The control is the rule on the live clean-break watch. A buy is the first 15-minute bar that sits entirely above the highest busy-candle zone, and only when the bar before it closed at or under that zone. The buy price is the next 15-minute open. The sale in the main table is the close 26 fifteen-minute bars later, about one session. The zone has to be 4 to 8 sessions old, the bar has to start between 9:30 and 11:00 Eastern, and the close has to be at least 20% under the high of the prior 252 trading days.</p>
<p>The new rule keeps every one of those filters. The only change is for bars after the open. The first bar from 9:45 through 11:00 whose low is above the zone is a buy, even if an earlier bar already closed above it. That is the BBWI case: the first bar closed above the zone but dipped back under it, and the next bar stayed above.</p>
<p>The open bar is unchanged. A 9:30 bar is a buy only when the whole bar is above the zone and the prior close was still at or under it. If the stock is already above the zone at the open, that bar is not a buy. The 20% test under the prior 252-day high also stays on every bar, including the open. This system does not have a separate percent cap on the size of an overnight gap.</p>
<p>{html.escape(verdict)} In-sample here means an entry before 2024-01-01. This 15-minute tape starts in July 2026, so that slice has no trades. Out-of-sample is the whole book. Annualized rate of return uses the house formula on a ${SLOT:,.0f} slot per trade. These holds last about one day, so that annualized figure is very large. The average return is the easier comparison. Max drawdown replays the dollar results on a ${DEFAULT_INITIAL_ACCOUNT:,.0f} account. Each trade’s dollar result is its percent return times ${SLOT:,.0f}. Sharpe is blank because the exit-date series is too short for that calculation.</p>
</div>
<h2>Same exit, no stop</h2>
<p class="note">Sale is the close 26 fifteen-minute bars after the fill. A lower max drawdown is the better direction. In-sample annualized rate of return and max drawdown are blank because no entry is before 2024-01-01.</p>
{_table(
    [("Metric", "text"), ("Control", "num"), ("Low above the zone", "num"), ("Change", "num")],
    _metric_rows(mc, ma),
)}
<h2>Same trades with a stop under the fill</h2>
<p class="note">If any of the 26 bars trades at or below the stop, the result is exactly that loss. The open is not given a worse gap fill. Annualized rate of return and max drawdown are the full book.</p>
{_table(
    [
        ("Stop", "text"),
        ("Control trades", "num"),
        ("Control avg", "num"),
        ("Control win %", "num"),
        ("Control Ann ROR", "num"),
        ("Control max DD", "num"),
        ("New trades", "num"),
        ("New avg", "num"),
        ("New win %", "num"),
        ("New Ann ROR", "num"),
        ("New max DD", "num"),
    ],
    stop_rows,
)}
<h2>Trades the new rule adds</h2>
<p class="note">{len(only)} closed trades are in the new rule and not in the control. “Prior close under the zone” is no when the bar before the signal already finished above the trigger. That is the piece the control rejects.</p>
{_table(
    [
        ("Symbol", "text"),
        ("Signal date", "date"),
        ("Signal time", "text"),
        ("Zone age", "num"),
        ("Zone high", "num"),
        ("Signal low", "num"),
        ("Prior close", "num"),
        ("Prior close under zone", "text"),
        ("Buy", "num"),
        ("26-bar return", "num"),
        ("Under 252-day high", "num"),
    ],
    extra_rows,
) if extra_rows else "<p>No extra closed trades.</p>"}
<h2>Freeze</h2>
<ul>
<li>Zone: highest-volume 15-minute candle before 15:45, carried 20 sessions. A band thinner than 0.05% of its midpoint is skipped.</li>
<li>Age 4 to 8 sessions after the zone’s own day. Trigger bar starts at 09:30, 09:45, 10:00, 10:15, 10:30, 10:45, or 11:00 Eastern.</li>
<li>Signal close at least 20% under the highest daily high of the prior 252 trading days, through the day before the signal.</li>
<li>Fill: next 15-minute open. A trade is counted only when 26 bars after that open are in the tape.</li>
<li>Tape: the live-watch 15-minute cache, liquid names, {html.escape(date_min)} through {html.escape(date_max)} entries.</li>
</ul>
</body>
{extras.SORTABLE_TABLE_SCRIPT}
</html>
"""
    return body


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    df = load_rows()
    df = _attach_stop_columns(df)
    keep = [c for c in df.columns if c not in {"stops", "stop_days", "stop_exit"}]
    df[keep].to_csv(STAMP / "signals.csv", index=False)
    page = STAMP / "compare.html"
    page.write_text(render(df), encoding="utf-8")
    control_n = int((df["arm"] == "control").sum()) if len(df) else 0
    cand_n = int((df["arm"] == "low_above").sum()) if len(df) else 0
    (STAMP / "BASELINE.md").write_text(
        "\n".join(
            [
                "# Clean break vs low-above, ignore prior close",
                "",
                "Research only. Not gold. Not DailyRun.",
                "",
                "One change: after the open, the candidate buys the first bar from 9:45 through 11:00 whose low is above the highest active zone, even if the prior close was already above. The 9:30 bar still uses the control rule: the whole bar must be above the zone and the prior close must still be at or under it. The control requires that prior-close test on every bar.",
                "",
                "Kept on both arms: age 4–8, trigger 09:30–11:00 Eastern, signal close at least 20% under the prior 252-day high, next 15-minute open, 26-bar close. The 9:30 bar is still bought only when yesterday closed at or under the zone. The 20% test also blocks a name already too close to the yearly high. There is no separate overnight-gap percent cap.",
                "",
                f"Tape: `{BARS.relative_to(ROOT).as_posix()}`. Slot cash ${SLOT:,.0f}. Drawdown account ${DEFAULT_INITIAL_ACCOUNT:,.0f}.",
                "",
                f"Closed trades: control {control_n}, candidate {cand_n}.",
                "",
                "In-sample (`entry_date < 2024-01-01`) has no trades. The 15-minute store starts in July 2026. Out-of-sample is the full book. OOS was not used to pick the rule.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"wrote {page} control={control_n} candidate={cand_n}", flush=True)


if __name__ == "__main__":
    main()
