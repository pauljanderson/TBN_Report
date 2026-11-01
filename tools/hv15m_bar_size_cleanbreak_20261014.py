#!/usr/bin/env python3
"""Same clean-break rule on 15-minute, 10-minute, 5-minute, and 1-minute bars.

The zone stays the highest-volume 15-minute candle before 15:45, carried 20
sessions. Only the signal bar's length changes. Research only. Not gold.
Not DailyRun. Does not change the live watch.
"""
from __future__ import annotations

import html
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
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

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_bar_size_cleanbreak_20261014"
BARS_15 = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_stop_grid_20260927" / "live_15m.parquet"
ONE_MIN = ROOT / "data" / "intraday" / "1m"
N_CARRY = 20
AGES = {4, 5, 6, 7, 8}
PCT_FLOOR = 0.20
SLOT = 10_000.0
IS_CUT = date(2024, 1, 1)
OPEN_MINUTE = 9 * 60 + 30
MORNING_LAST = 11 * 60  # 11:00 bar start is still in

ARMS = (
    {"key": "15m", "label": "15-minute", "minutes": 15, "min_prints": 10, "hold": 26},
    {"key": "10m", "label": "10-minute", "minutes": 10, "min_prints": 7, "hold": 39},
    {"key": "5m", "label": "5-minute", "minutes": 5, "min_prints": 4, "hold": 78},
    {"key": "1m", "label": "1-minute", "minutes": 1, "min_prints": 1, "hold": 390},
)

ASK = (
    "OK. let's stick to the control, but I feel like most gaps up are green bars, no? "
    "are we simply looking for a gap up high enough that it opens over the trigger? "
    "and is it better for us to look for 15-minute bars above the trigger, 10m, 5m, or 1m. "
    "can you run all of these tests through"
)


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


def _highest(z_hi, valid, z_bkt, done, s: int, b15: int) -> int:
    n = len(valid)
    s0 = max(0, s - N_CARRY)
    hi_z = -1
    best = -1e300
    for zs in range(s0, s + 1):
        if zs >= n or not valid[zs] or done[zs]:
            continue
        if (s - zs) > N_CARRY:
            continue
        if zs == s and b15 <= int(z_bkt[zs]):
            continue
        zh = float(z_hi[zs])
        if zh > best or (zh == best and zs > hi_z):
            best = zh
            hi_z = zs
    return hi_z


def _zones(g: pd.DataFrame):
    g = g.sort_values(["day", "bucket"])
    day = pd.to_datetime(g["day"]).dt.date.to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    low = g["low"].to_numpy(dtype=np.float64)
    high = g["high"].to_numpy(dtype=np.float64)
    vol = g["volume"].to_numpy(dtype=np.float64)
    n = len(day)
    if n < 30:
        return None
    uniq = list(pd.unique(day))
    counts: dict = {}
    for d in day:
        counts[d] = counts.get(d, 0) + 1
    good_days = [d for d in uniq if counts[d] >= base.MIN_BARS_SESSION]
    if len(good_days) < 8:
        return None
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    z_lo, z_hi, z_bkt, valid = _elect(day, bucket, low, high, vol, sess, good_days)
    if not np.any(valid):
        return None
    return {
        "good_days": good_days,
        "day_to_s": day_to_s,
        "z_lo": z_lo,
        "z_hi": z_hi,
        "z_bkt": z_bkt,
        "valid": valid,
    }


def _pct_ok(pack, on_day, price: float) -> bool:
    if pack is None or not np.isfinite(price):
        return False
    ix = led._prior_index(pack["day"], on_day)
    hi, _hi_date, n_used = led._window_high(pack["day"], pack["high"], ix + 1, led.YEAR_BARS, None)
    if n_used < led.MIN_YEAR_BARS:
        return False
    pct = led._pct_below(hi, price)
    return bool(np.isfinite(pct) and pct >= PCT_FLOOR)


def scan_arm(sym: str, g: pd.DataFrame, zones: dict, pack, minutes: int, hold: int, diag: bool) -> tuple[list[dict], dict]:
    g = g.sort_values(["day", "bucket"])
    day = pd.to_datetime(g["day"]).dt.date.to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    opens = g["open"].to_numpy(dtype=np.float64)
    low = g["low"].to_numpy(dtype=np.float64)
    close = g["close"].to_numpy(dtype=np.float64)
    n = len(close)
    day_to_s = zones["day_to_s"]
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    minute = OPEN_MINUTE + bucket.astype(np.int32) * int(minutes)
    b15 = ((minute - OPEN_MINUTE) // 15).astype(np.int16)
    order = [i for i in range(n) if sess[i] >= 0]
    z_hi = zones["z_hi"]
    z_lo = zones["z_lo"]
    z_bkt = zones["z_bkt"]
    valid = zones["valid"]
    good_days = zones["good_days"]
    done = np.zeros(len(good_days), dtype=np.int8)
    rows: list[dict] = []
    stats = {
        "dropped": 0,
        "rejected_open_above": 0,
        "rejected_open_above_0930": 0,
    }
    cached_hi = -2
    cached_s = -2
    cached_b15 = -2
    for k, i in enumerate(order):
        if k == 0:
            continue
        prev = order[k - 1]
        s = int(sess[i])
        bb = int(b15[i])
        if cached_s != s or cached_b15 != bb or cached_hi < -1:
            cached_hi = _highest(z_hi, valid, z_bkt, done, s, bb)
            cached_s = s
            cached_b15 = bb
        hi_z = cached_hi
        if hi_z < 0:
            continue
        zh = float(z_hi[hi_z])
        prior = float(close[prev])
        prior_under = prior <= zh
        whole = float(low[i]) > zh and float(close[i]) > zh
        opened_over = float(opens[i]) > zh
        if whole and prior_under:
            done[hi_z] = 1
            cached_hi = -2
            age = s - hi_z
            start = int(minute[i])
            morning = OPEN_MINUTE <= start <= MORNING_LAST
            if age not in AGES or not morning:
                continue
            if not _pct_ok(pack, day[i], float(close[i])):
                continue
            entry_i = i + 1
            if entry_i + hold > n:
                stats["dropped"] += 1
                continue
            exit_i = entry_i + hold - 1
            entry = float(opens[entry_i])
            sold = float(close[exit_i])
            if not np.isfinite(entry) or entry <= 0 or not np.isfinite(sold):
                stats["dropped"] += 1
                continue
            entry_day = pd.Timestamp(day[entry_i]).date()
            exit_day = pd.Timestamp(day[exit_i]).date()
            rows.append(
                {
                    "symbol": sym,
                    "signal_date": pd.Timestamp(day[i]).date().isoformat(),
                    "entry_date": entry_day.isoformat(),
                    "exit_date": exit_day.isoformat(),
                    "signal_minute": start,
                    "is_0930": start == OPEN_MINUTE,
                    "signal_open": float(opens[i]),
                    "signal_close": float(close[i]),
                    "zone_hi": zh,
                    "prior_close": prior,
                    "entry": entry,
                    "fwd": sold / entry - 1.0,
                    "days": max(1, (exit_day - entry_day).days),
                }
            )
        elif diag and prior_under and opened_over and not whole:
            age = s - hi_z
            start = int(minute[i])
            if age in AGES and OPEN_MINUTE <= start <= MORNING_LAST and _pct_ok(pack, day[i], float(close[i])):
                stats["rejected_open_above"] += 1
                if start == OPEN_MINUTE:
                    stats["rejected_open_above_0930"] += 1
    return rows, stats


def build_tf(symbols: list[str], minutes: int, min_prints: int) -> pd.DataFrame:
    glob = (ONE_MIN / "*.parquet").as_posix()
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE syms(symbol VARCHAR)")
        con.executemany("INSERT INTO syms VALUES (?)", [(s,) for s in symbols])
        hi_test = "max(high) >= min(low)" if minutes == 1 else "max(high) > min(low)"
        return con.execute(
            f"""
            WITH src AS (
                SELECT upper(symbol) AS symbol,
                       timezone('America/New_York', ts) AS ts_et,
                       open, high, low, close, volume
                FROM read_parquet('{glob}')
                WHERE upper(symbol) IN (SELECT symbol FROM syms)
                  AND volume IS NOT NULL AND volume > 0
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
            ),
            f AS (
                SELECT symbol,
                       CAST(ts_et AS DATE) AS day,
                       (hour(ts_et) * 60 + minute(ts_et)) AS mins,
                       ts_et, open, high, low, close, volume
                FROM src
            )
            SELECT symbol, day,
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
               AND {hi_test}
               AND sum(volume) > 0
            ORDER BY symbol, day, bucket
            """
        ).fetchdf()
    finally:
        con.close()


def _book_metrics(g: pd.DataFrame) -> dict:
    n = int(len(g))
    empty_ov = {
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "capital_days": 0.0,
        "note": "no trades",
    }
    if n == 0:
        return {
            "n": 0,
            "symbols": 0,
            "wins": 0,
            "losses": 0,
            "win": float("nan"),
            "avg": float("nan"),
            "med": float("nan"),
            "avg_win": float("nan"),
            "avg_loss": float("nan"),
            "pf": float("nan"),
            "wo_max": float("nan"),
            "avg_days": float("nan"),
            "n_0930": 0,
            "n_later": 0,
            "green": 0,
            "red": 0,
            "flat": 0,
            "full": empty_ov,
            "is": empty_ov,
            "oos": empty_ov,
            "n_is": 0,
            "n_oos": 0,
        }
    r = g["fwd"].to_numpy(dtype=float)
    wins = r[r > 0]
    losses = r[r < 0]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    wo = np.sort(r)[:-1] if n > 1 else r
    so = g["signal_open"].to_numpy(dtype=float)
    sc = g["signal_close"].to_numpy(dtype=float)
    trades = [
        {
            "opened": rec.entry_date,
            "closed": rec.exit_date,
            "days": float(rec.days),
            "pnl_d": float(rec.fwd) * SLOT,
            "pnl": float(rec.fwd) * 100.0,
        }
        for rec in g.itertuples(index=False)
    ]
    is_rows = [t for t in trades if date.fromisoformat(str(t["opened"])) < IS_CUT]
    oos_rows = [t for t in trades if date.fromisoformat(str(t["opened"])) >= IS_CUT]
    return {
        "n": n,
        "symbols": int(g["symbol"].nunique()),
        "wins": int((r > 0).sum()),
        "losses": int((r < 0).sum()),
        "win": float((r > 0).mean()),
        "avg": float(r.mean()),
        "med": float(np.median(r)),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "pf": (gross_win / gross_loss) if gross_loss > 0 else float("nan"),
        "wo_max": float(wo.mean()) if len(wo) else float("nan"),
        "avg_days": float(g["days"].mean()),
        "n_0930": int(g["is_0930"].sum()),
        "n_later": int((~g["is_0930"]).sum()),
        "green": int((sc > so).sum()),
        "red": int((sc < so).sum()),
        "flat": int((sc == so).sum()),
        "full": overlay_ann_ror_max_dd(trades, cash=SLOT, initial_account=DEFAULT_INITIAL_ACCOUNT),
        "is": overlay_ann_ror_max_dd(is_rows, cash=SLOT, initial_account=DEFAULT_INITIAL_ACCOUNT),
        "oos": overlay_ann_ror_max_dd(oos_rows, cash=SLOT, initial_account=DEFAULT_INITIAL_ACCOUNT),
        "n_is": len(is_rows),
        "n_oos": len(oos_rows),
    }


def _pct(x, digits=2) -> str:
    if x is None or not isinstance(x, (int, float)) or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _num(x, digits=2) -> str:
    if x is None or not isinstance(x, (int, float)) or not np.isfinite(x):
        return "—"
    return f"{float(x):.{digits}f}"


def _ann(ov) -> str:
    v = (ov or {}).get("ann_ror")
    if v is None or not np.isfinite(v):
        return "—"
    return f"{float(v):.2f}%"


def _dd(ov) -> str:
    v = (ov or {}).get("max_dd")
    if v is None or not np.isfinite(v):
        return "—"
    return f"{float(v):.2f}%"


def _delta_pp(a, b) -> str:
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
        return "—"
    return f"{100.0 * (float(b) - float(a)):+.2f} pp"


def _delta_ann(a, b) -> str:
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
        return "—"
    return f"{float(b) - float(a):+.2f} pp"


def _delta_int(a, b) -> str:
    return f"{int(b) - int(a):+d}"


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
            tds.append(f"<td{style}>{html.escape(str(text))}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        extras.SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _fmt_cell(kind: str, v) -> str:
    if kind == "int":
        return str(int(v))
    if kind == "pct":
        return _pct(v)
    if kind == "num":
        return _num(v)
    if kind == "ann":
        return _ann(v)
    if kind == "dd":
        return _dd(v)
    return str(v)


def _compare_rows(books: list[dict]) -> list:
    """books aligned with ARMS. Deltas are versus the 15-minute control."""
    c = books[0]
    specs = [
        ("Trades", "n", "int"),
        ("Symbols", "symbols", "int"),
        ("Wins", "wins", "int"),
        ("Losses", "losses", "int"),
        ("Win %", "win", "pct"),
        ("Avg return", "avg", "pct"),
        ("Median return", "med", "pct"),
        ("Avg win", "avg_win", "pct"),
        ("Avg loss", "avg_loss", "pct"),
        ("Profit factor", "pf", "num"),
        ("Avg return without the best trade", "wo_max", "pct"),
        ("Avg days held", "avg_days", "num"),
        ("9:30 gap signals", "n_0930", "int"),
        ("Later morning signals", "n_later", "int"),
        ("Green signal bars", "green", "int"),
        ("Red signal bars", "red", "int"),
        ("Flat signal bars", "flat", "int"),
        ("Annualized rate of return, full book", "full", "ann"),
        ("Annualized rate of return, in-sample", "is", "ann"),
        ("Annualized rate of return, out-of-sample", "oos", "ann"),
        ("Max drawdown, full book", "full", "dd"),
        ("Max drawdown, in-sample", "is", "dd"),
        ("Max drawdown, out-of-sample", "oos", "dd"),
        ("Calmar, full book", "full", "cal"),
        ("Sharpe, full book", "full", "sh"),
    ]
    out = []
    for label, key, kind in specs:
        cells = [(label, False)]
        raw = []
        for b in books:
            if kind == "ann":
                raw.append((b.get(key) or {}).get("ann_ror"))
                cells.append((_ann(b.get(key)), True))
            elif kind == "dd":
                raw.append((b.get(key) or {}).get("max_dd"))
                cells.append((_dd(b.get(key)), True))
            elif kind == "cal":
                raw.append((b.get(key) or {}).get("calmar"))
                cells.append((_num(raw[-1]), True))
            elif kind == "sh":
                raw.append((b.get(key) or {}).get("sharpe"))
                cells.append((_num(raw[-1]), True))
            else:
                raw.append(b.get(key))
                cells.append((_fmt_cell(kind, b.get(key)), True))
        base = raw[0]
        for v in raw[1:]:
            if kind == "int":
                cells.append((_delta_int(base, v), True))
            elif kind in {"pct"}:
                cells.append((_delta_pp(base, v), True))
            elif kind in {"ann", "dd", "cal", "sh", "num"}:
                cells.append((_delta_ann(base, v) if kind != "num" else (
                    "—" if base is None or v is None or not np.isfinite(base) or not np.isfinite(v) else f"{float(v) - float(base):+.2f}"
                ), True))
            else:
                cells.append(("—", True))
        out.append(cells)
    return out


def render(books: list[dict], dropped: dict, diag: dict, date_min: str, date_max: str) -> str:
    c = books[0]
    gap_n = c["n_0930"]
    later_n = c["n_later"]
    # All closed control signals open above the zone, because the low is above it.
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    headers = [("Metric", "text"), ("15-minute control", "num")]
    for arm in ARMS[1:]:
        headers.append((arm["label"], "num"))
        headers.append((f"Change, {arm['label']}", "num"))
    gap_rows = []
    for arm, b, drop in zip(ARMS, books, [dropped[a["key"]] for a in ARMS]):
        gap_rows.append([
            (arm["label"], False),
            (str(b["n"]), True),
            (str(b["n_0930"]), True),
            (str(b["n_later"]), True),
            (str(b["green"]), True),
            (str(b["red"]), True),
            (str(b["flat"]), True),
            (_pct(b["win"]), True),
            (_pct(b["avg"]), True),
            (_pct(b["med"]), True),
            (_num(b["pf"]), True),
            (_ann(b["full"]), True),
            (str(drop), True),
        ])
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{extras.CACHE_META}
<title>Clean break bar length</title>
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
<h1>Clean break on 15-minute, 10-minute, 5-minute, and 1-minute bars</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Built {html.escape(now)}. Closed entries {html.escape(date_min)} through {html.escape(date_max)}. This is one horse race on a short tape, so the winner is in-sample selection. Out-of-sample is report-only and was not used to pick a bar length. Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ASK)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>We are keeping the control. A buy is still the first bar that finishes entirely above the high-volume 15-minute zone: the low and the close both stay above that high, and the bar before it closed at or under that high. The zone itself stays a 15-minute zone in every test. We only change how long the signal bar is: 15 minutes, 10 minutes, 5 minutes, or 1 minute. The buy is the next bar's open on that same clock. The sale is one regular session later, 390 minutes: 26 bars of 15 minutes, 39 bars of 10 minutes, 78 bars of 5 minutes, or 390 one-minute bars.</p>
<p>We are not simply looking for a gap that opens over the trigger. Opening above the zone is not enough. If the bar trades back to the trigger or through it, it is not a buy. If the bar rallies through the trigger but its low is still under the zone, it is not a buy. On the 15-minute control, {diag['rejected_open_above']} morning bars in the age window opened above the zone with the prior close still at or under it, passed the 20% test under the prior 252-day high, and were still rejected because the low or the close came back. {diag['rejected_open_above_0930']} of those rejected bars were the 9:30 bar.</p>
<p>Of the {c['n']} closed 15-minute control trades, {gap_n} are the 9:30 bar (an overnight gap that stayed entirely above the zone) and {later_n} are later morning bars. Every one of those trades opened above the zone, because the low itself was above the zone. {c['green']} of them closed green (close above the open), {c['red']} closed red, and {c['flat']} were flat. The 9:30 gaps alone were {diag['gap_green']} green, {diag['gap_red']} red, and {diag['gap_flat']} flat.</p>
<p>The zone has to be 4 to 8 sessions old. The signal bar has to start from 9:30 through 11:00 Eastern. The signal close has to be at least 20% under the highest daily high of the prior 252 trading days. That 20% test is the existing block for a name that has already run up too far, including at the open. There is no extra percent cap on the overnight gap. A 9:30 bar is a buy only when the whole bar stays above the zone and the prior session closed at or under the zone.</p>
<p>In-sample means an entry before 2024-01-01. This tape starts in July 2026, so that slice has no trades. Out-of-sample is the whole book. Annualized rate of return is the house formula on a ${SLOT:,.0f} slot per trade. These holds last about a day, so that annualized figure is very large. The average return is the easier comparison. Max drawdown replays those dollars on a ${DEFAULT_INITIAL_ACCOUNT:,.0f} account. Sharpe is blank when the exit-date series is too short for that calculation.</p>
</div>
<h2>Control gaps</h2>
<p class="note">Closed 15-minute trades only. A green bar closed above its open. A red bar closed below its open.</p>
{_table(
    [("Group", "text"), ("Trades", "num"), ("Green", "num"), ("Red", "num"), ("Flat", "num")],
    [
        [("9:30 overnight gaps", False), (str(gap_n), True), (str(diag["gap_green"]), True), (str(diag["gap_red"]), True), (str(diag["gap_flat"]), True)],
        [("Later morning bars", False), (str(later_n), True), (str(diag["later_green"]), True), (str(diag["later_red"]), True), (str(diag["later_flat"]), True)],
        [("All control trades", False), (str(c["n"]), True), (str(c["green"]), True), (str(c["red"]), True), (str(c["flat"]), True)],
    ],
)}
<h2>Bar length</h2>
<p class="note">Change is the other bar length minus the 15-minute control. A lower max drawdown is the better direction. In-sample annualized rate of return and max drawdown are blank because no entry is before 2024-01-01. Green, red, and flat describe the signal bar, not the trade result.</p>
{_table(headers, _compare_rows(books))}
<h2>Short version of the same four arms</h2>
<p class="note">Dropped means a signal passed the rule but the tape ended before the 390-minute hold finished, so it is not in the closed counts above.</p>
{_table(
    [
        ("Bar", "text"),
        ("Trades", "num"),
        ("9:30 gaps", "num"),
        ("Later bars", "num"),
        ("Green", "num"),
        ("Red", "num"),
        ("Flat", "num"),
        ("Win %", "num"),
        ("Avg return", "num"),
        ("Median return", "num"),
        ("Profit factor", "num"),
        ("Ann ROR", "num"),
        ("Dropped", "num"),
    ],
    gap_rows,
)}
<h2>Freeze</h2>
<ul>
<li>Zone: highest-volume 15-minute candle before 15:45, carried 20 sessions. The same zone is used on every bar length. A band thinner than 0.05% of its midpoint is skipped.</li>
<li>Clean break: the whole signal bar is above the zone high, and the previous bar's close is still at or under that high. First time for that zone.</li>
<li>Age 4 to 8 sessions. Signal bar starts from 09:30 through 11:00 Eastern, including 11:00.</li>
<li>Signal close at least 20% under the prior 252-trading-day high.</li>
<li>Fill: next bar's open on that same bar length. Hold: 26 bars of 15 minutes, 39 of 10 minutes, 78 of 5 minutes, 390 of 1 minute.</li>
<li>A 15-minute bar needs at least 10 one-minute prints. A 10-minute bar needs 7. A 5-minute bar needs 4. A 1-minute bar is the print itself. Bars with no volume are skipped.</li>
<li>15-minute bars are the live-watch cache. The shorter bars are built from the stored 1-minute files, regular hours 9:30 to 16:00 Eastern, left-labeled and anchored at 9:30.</li>
</ul>
</body>
{extras.SORTABLE_TABLE_SCRIPT}
</html>
"""
    return body


def load_daily(symbols: list[str]) -> dict:
    try:
        return led.load_daily(symbols)
    except Exception as exc:
        print(f"price database is busy ({exc}); reading daily highs from the CSV warehouse", flush=True)
    glob = (ROOT / "data" / "newdata" / "data" / "*.csv").as_posix()
    con = duckdb.connect()
    try:
        df = con.execute(
            f"""
            SELECT upper(regexp_extract(filename, '([^/\\\\]+)\\.csv$', 1)) AS symbol,
                   CAST(Date AS DATE) AS day,
                   High AS high
            FROM read_csv('{glob}', filename=true, header=true, union_by_name=true,
                          columns={{'Date': 'DATE', 'High': 'DOUBLE'}})
            WHERE CAST(Date AS DATE) >= DATE '2025-01-01'
              AND upper(regexp_extract(filename, '([^/\\\\]+)\\.csv$', 1)) IN (SELECT * FROM UNNEST(?))
            """,
            [symbols],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        return {}
    df["day"] = pd.to_datetime(df["day"]).dt.date
    out = {}
    for sym, g in df.groupby("symbol", sort=False):
        g = g.sort_values("day")
        days = [d.date() if isinstance(d, pd.Timestamp) else d for d in g["day"].tolist()]
        out[str(sym)] = {"day": days, "high": g["high"].to_numpy(dtype=np.float64)}
    return out


def _color_split(g: pd.DataFrame) -> tuple[int, int, int]:
    if g.empty:
        return 0, 0, 0
    so = g["signal_open"].to_numpy(dtype=float)
    sc = g["signal_close"].to_numpy(dtype=float)
    green = int((sc > so).sum())
    red = int((sc < so).sum())
    flat = int(np.isclose(sc, so).sum())
    return green, red, flat


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    print("reading 15-minute cache...", flush=True)
    bars15 = pd.read_parquet(BARS_15)
    names = sorted(bars15["symbol"].astype(str).unique())
    print(f"daily highs for {len(names)} symbols...", flush=True)
    daily = load_daily(names)
    grouped15 = {sym: g for sym, g in bars15.groupby(bars15["symbol"].astype(str), sort=False)}
    zone_map = {}
    for sym, g in grouped15.items():
        z = _zones(g)
        if z is not None:
            zone_map[sym] = z
    print(f"zones for {len(zone_map)} symbols", flush=True)

    frames: dict[str, pd.DataFrame] = {}
    dropped = {}
    diag_15 = {
        "rejected_open_above": 0,
        "rejected_open_above_0930": 0,
        "gap_green": 0,
        "gap_red": 0,
        "gap_flat": 0,
        "later_green": 0,
        "later_red": 0,
        "later_flat": 0,
    }
    all_rows = []
    for arm in ARMS:
        key = arm["key"]
        print(f"building {key}...", flush=True)
        if key == "15m":
            raw = bars15
        else:
            raw = build_tf(names, arm["minutes"], arm["min_prints"])
            print(f"  {key} rows {len(raw):,}", flush=True)
        grouped = {sym: g for sym, g in raw.groupby(raw["symbol"].astype(str), sort=False)}
        rows = []
        drop_n = 0
        rej = 0
        rej_open = 0
        for i, sym in enumerate(names, 1):
            z = zone_map.get(sym)
            g = grouped.get(sym)
            if z is None or g is None or g.empty:
                continue
            got, st = scan_arm(
                sym, g, z, daily.get(sym), arm["minutes"], arm["hold"], diag=(key == "15m")
            )
            for rec in got:
                rec["arm"] = key
            rows.extend(got)
            drop_n += st["dropped"]
            rej += st["rejected_open_above"]
            rej_open += st["rejected_open_above_0930"]
            if i % 400 == 0 or i == len(names):
                print(f"  {key} {i}/{len(names)} signals {len(rows)} dropped {drop_n}", flush=True)
        frames[key] = pd.DataFrame(rows)
        dropped[key] = drop_n
        all_rows.extend(rows)
        if key == "15m":
            diag_15["rejected_open_above"] = rej
            diag_15["rejected_open_above_0930"] = rej_open
            g15 = frames["15m"]
            if len(g15):
                diag_15["gap_green"], diag_15["gap_red"], diag_15["gap_flat"] = _color_split(g15[g15["is_0930"]])
                diag_15["later_green"], diag_15["later_red"], diag_15["later_flat"] = _color_split(g15[~g15["is_0930"]])

    books = []
    for arm in ARMS:
        g = frames[arm["key"]]
        books.append(_book_metrics(g if len(g) else pd.DataFrame(columns=["fwd", "symbol", "signal_open", "signal_close", "is_0930", "entry_date", "exit_date", "days"])))
        print(
            f"{arm['key']} n={books[-1]['n']} win={books[-1]['win']} avg={books[-1]['avg']} "
            f"0930={books[-1]['n_0930']} dropped={dropped[arm['key']]}",
            flush=True,
        )

    out = pd.DataFrame(all_rows)
    if len(out):
        out.to_csv(STAMP / "signals.csv", index=False)
    dates = out["entry_date"] if len(out) else pd.Series(dtype=str)
    date_min = str(dates.min()) if len(dates) else "—"
    date_max = str(dates.max()) if len(dates) else "—"
    page = STAMP / "compare.html"
    page.write_text(render(books, dropped, diag_15, date_min, date_max), encoding="utf-8")
    (STAMP / "BASELINE.md").write_text(
        "\n".join(
            [
                "# Clean break bar length",
                "",
                "Research only. Not gold. Not DailyRun. The live watch is unchanged.",
                "",
                "Control is the 15-minute clean break. One question: does the same rule improve on a 10-minute, 5-minute, or 1-minute signal bar.",
                "",
                "Zone stays the highest-volume 15-minute candle before 15:45, carried 20 sessions, on every arm.",
                "Clean break: low and close both above the zone high, previous bar close still at or under the zone high, first time for that zone.",
                "Age 4 to 8. Signal start 09:30 through 11:00 Eastern. Signal close at least 20% under the prior 252-day high.",
                "The 9:30 bar is a buy only when the whole bar stays above the zone and the prior session closed at or under it. No extra overnight-gap percent cap.",
                "Fill is the next bar open on that timeframe. Hold is 390 minutes: 26 x 15-minute, 39 x 10-minute, 78 x 5-minute, 390 x 1-minute.",
                "Minimum prints: 15-minute >= 10, 10-minute >= 7, 5-minute >= 4, 1-minute is the print. No-volume bars skipped.",
                "",
                f"Tape: 15-minute cache `{BARS_15.relative_to(ROOT).as_posix()}`. Shorter bars from `data/intraday/1m`. Slot ${SLOT:,.0f}. Drawdown account ${DEFAULT_INITIAL_ACCOUNT:,.0f}.",
                "",
                "In-sample (`entry_date < 2024-01-01`) has no trades. The store starts in July 2026. Out-of-sample is the full book and was not used to choose a bar length. This horse race is in-sample selection on a short tape.",
                "",
                "Dropped (signal passed, hold not finished): "
                + ", ".join(f"{a['key']}={dropped[a['key']]}" for a in ARMS)
                + ".",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"wrote {page}", flush=True)


if __name__ == "__main__":
    main()
