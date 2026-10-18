"""Rocket Launcher look-left entry filter. Research only. Does not change DailyRun.

Frozen before the historical ranking (Monday 2026-09-28 charts + Magic Touch zones):
  skip a buy only when BOTH are true at the fill:
  1) an uncleared Magic Touch pivot-high shelf has its lower edge within 15% above
     the entry (or the entry is already inside that band);
  2) the entry is more than 45% above the lowest low of the 63 sessions ending on
     the signal bar (the day before the fill).
"""
from __future__ import annotations

import csv
import html
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from rocket_post_analysis import (  # noqa: E402
    apply_paul_scores_to_summary_rows,
    assess_symbol_fit,
)
from rocket_tbn import compute_sheet_brt_touch_stream  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "rl_lookleft_resistance_20260930"
CLOSED = ROOT / "drive" / "RL_Closed_260930184039.csv"
SUMMARY = ROOT / "drive" / "RL_Summary_260930184039.csv"
OPEN = ROOT / "drive" / "RL_Open_260930184039.csv"
DATA = ROOT / "data" / "newdata" / "data"
MTS_DOCU = STAMP / "mts_docu" / "MTS_Closed_260930234707.csv"

# Frozen knobs. Do not retune after seeing the book.
OVERHEAD_PCT = 0.15
BOUNCE_PCT = 0.45
BOUNCE_BARS = 63
BAND_PCT = 0.018
CASH = 47_500.0
INIT = 500_000.0
IS_CUT = date(2024, 1, 1)

USER_QUOTE = (
    "on monday we had a few RL signals in the trigger file. here is the feedback from the PO. "
    "if we were to build his analysis into the RL system, what would it look like, and show me a "
    "comparison of what the results are today and what they would be with his changes?\n"
    "PO: Look left on all of those for resistance\n"
    "ME: all right. something for you to build into the system, then!\n"
    "PO: Yup.  3 of those are software that WAS beaten down sector, but has a nice bounce recently, "
    "but a lot of them have already made a big move.  Look at the MTS trades in Docu at that level I drew"
)


def ymd(raw: str) -> date | None:
    s = str(raw or "").strip().replace("-", "")[:8]
    if len(s) < 8 or not s.isdigit():
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def num(raw) -> float:
    s = str(raw or "").replace("%", "").replace(",", "").replace("+", "").strip()
    if not s or s in {"nan", "None", "—"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def load_industry() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    if not SUMMARY.exists():
        return out
    with SUMMARY.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sym = (row.get("SYMBOL") or "").strip().upper()
            if sym:
                out[sym] = (row.get("SECTOR") or "", row.get("INDUSTRY") or "")
    return out


def load_closed(industry: dict[str, tuple[str, str]]) -> list[dict]:
    rows = []
    with CLOSED.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            pnl = num(row.get("PNL %"))
            days = num(row.get("DAYS HELD"))
            opened = ymd(row.get("DATE OPENED") or "")
            closed = ymd(row.get("DATE CLOSED") or "")
            if opened is None or not math.isfinite(pnl):
                continue
            sym = (row.get("SYMBOL") or "").strip().upper()
            sec, ind = industry.get(sym, ("", ""))
            rows.append(
                {
                    "symbol": sym,
                    "opened": opened,
                    "closed": closed or opened,
                    "entry": num(row.get("ENTRY PRICE")),
                    "pnl": pnl,
                    "days": days if math.isfinite(days) else 0.0,
                    "exit_type": (row.get("EXIT TYPE") or "").strip() or "(blank)",
                    "sector": sec,
                    "industry": ind or "(unknown)",
                }
            )
    return rows


def build_shelves(sym: str) -> dict | None:
    path = DATA / f"{sym}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["Date"])
    if df.empty:
        return None
    df = df.sort_values("Date")
    stream = compute_sheet_brt_touch_stream(
        df.set_index("Date"),
        band_pct=BAND_PCT,
        pivot_local_window=4,
        post_pivot_bars=7,
        pivot_future_move_pct=0.06,
        pre_pivot_bars=7,
        pre_pivot_pct=0.12,
        touch_pullback_pct=0.06,
        touch_pullback_bars=7,
        maturity_lag=7,
        include_pivot_low_touches=True,
        zone_bounds_round_decimals=-1,
        lookback_long=503,
        lookback_short=199,
        touch_threshold=2,
    )
    dates = [d.date() for d in df["Date"]]
    closes = df["Close"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    origin = stream["zone_touch_origin"].to_numpy()
    shelves = []
    for ev in stream["brt_matured_zone_events"]:
        p = int(ev["pivot_bar"])
        if int(origin[p]) != 1:
            continue
        m = int(ev["maturity_bar"])
        hi = float(ev["zone_upper"])
        lo = float(ev["zone_lower"])
        tail = closes[m:]
        hits = np.where(tail > hi)[0]
        first_clear = int(m + hits[0]) if len(hits) else None
        shelves.append(
            {
                "touch": float(ev["touch_price"]),
                "lo": lo,
                "hi": hi,
                "maturity": m,
                "pivot": p,
                "pivot_date": dates[p].isoformat(),
                "first_clear": first_clear,
            }
        )
    return {"dates": dates, "lows": lows, "shelves": shelves}


def lookup_bar(pack: dict, when: date) -> int | None:
    dates = pack["dates"]
    # last bar strictly before the fill (the signal day)
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] < when:
            lo = mid + 1
        else:
            hi = mid
    sig = lo - 1
    return sig if sig >= 0 else None


def judge(pack: dict | None, entry: float, opened: date) -> dict:
    blank = {
        "skip": False,
        "bounce_pct": float("nan"),
        "overhead_pct": float("nan"),
        "touch": float("nan"),
        "shelf_lo": float("nan"),
        "shelf_hi": float("nan"),
        "pivot_date": "",
        "reason": "no price file; filter does not fire",
        "data_ok": False,
    }
    if pack is None or not (entry > 0):
        return blank
    sig = lookup_bar(pack, opened)
    if sig is None:
        blank["reason"] = "no signal bar before the fill"
        return blank
    blank["data_ok"] = True
    bounce = float("nan")
    big = False
    if sig + 1 >= BOUNCE_BARS:
        window = pack["lows"][sig - BOUNCE_BARS + 1 : sig + 1]
        low = float(np.min(window))
        if low > 0:
            bounce = entry / low - 1.0
            big = bounce > BOUNCE_PCT
    best = None
    best_dist = None
    for sh in pack["shelves"]:
        if sh["maturity"] > sig:
            continue
        fc = sh["first_clear"]
        if fc is not None and fc <= sig:
            continue
        if not (sh["hi"] > entry):
            continue
        dist = (sh["lo"] - entry) / entry
        if dist > OVERHEAD_PCT:
            continue
        if best is None or dist < best_dist:
            best = sh
            best_dist = dist
    overhead = best is not None
    skip = bool(overhead and big)
    if skip:
        why = (
            f"skip: shelf {best['touch']:.2f} ({best['lo']:.2f}–{best['hi']:.2f}, "
            f"pivot {best['pivot_date']}) is {best_dist * 100:.1f}% above the buy, "
            f"and price is already {bounce * 100:.1f}% off the {BOUNCE_BARS}-session low"
        )
    elif overhead and not big:
        why = (
            f"keep: shelf {best['touch']:.2f} is {best_dist * 100:.1f}% overhead, "
            f"but the bounce off the {BOUNCE_BARS}-session low is "
            f"{bounce * 100:.1f}% (needs more than {BOUNCE_PCT * 100:.0f}%)"
        )
    elif big and not overhead:
        why = (
            f"keep: bounce {bounce * 100:.1f}% off the {BOUNCE_BARS}-session low, "
            f"but no uncleared pivot-high shelf within {OVERHEAD_PCT * 100:.0f}%"
        )
    else:
        btxt = "n/a" if not math.isfinite(bounce) else f"{bounce * 100:.1f}%"
        why = f"keep: bounce {btxt}, no nearby uncleared pivot-high shelf"
    return {
        "skip": skip,
        "bounce_pct": bounce * 100 if math.isfinite(bounce) else float("nan"),
        "overhead_pct": best_dist * 100 if best is not None else float("nan"),
        "touch": best["touch"] if best else float("nan"),
        "shelf_lo": best["lo"] if best else float("nan"),
        "shelf_hi": best["hi"] if best else float("nan"),
        "pivot_date": best["pivot_date"] if best else "",
        "reason": why,
        "data_ok": True,
    }


def annotate(trades: list[dict]) -> None:
    symbols = sorted({t["symbol"] for t in trades})
    packs: dict[str, dict | None] = {}
    for i, sym in enumerate(symbols, 1):
        packs[sym] = build_shelves(sym)
        if i % 200 == 0:
            print(f"zones {i}/{len(symbols)}", flush=True)
    print(f"zones {len(symbols)}/{len(symbols)}", flush=True)
    missing = 0
    for t in trades:
        j = judge(packs.get(t["symbol"]), t["entry"], t["opened"])
        t.update(j)
        t["pnl_d"] = t["pnl"] / 100.0 * CASH
        if not j["data_ok"]:
            missing += 1
    print("missing price", missing, flush=True)


def _pctile(vals: list[float], q: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(math.ceil(q * len(s))) - 1))
    return s[i]


def positions_stats(trades: list[dict]) -> tuple[float, float, float]:
    events: dict[date, int] = defaultdict(int)
    if not trades:
        return float("nan"), float("nan"), float("nan")
    start = min(t["opened"] for t in trades)
    end = max(t["closed"] for t in trades)
    for t in trades:
        events[t["opened"]] += 1
        nxt = t["closed"] + timedelta(days=1)
        events[nxt] -= 1
    days = (end - start).days + 1
    if days <= 0:
        return float("nan"), float("nan"), float("nan")
    cur = 0
    # walk calendar via change-points only, carrying the count across gaps
    keys = sorted(events)
    samples = []
    prev = start
    cur = 0
    # apply changes up to each day
    idx = 0
    for n in range(days):
        d = start + timedelta(days=n)
        while idx < len(keys) and keys[idx] <= d:
            cur += events[keys[idx]]
            idx += 1
        samples.append(cur)
    samples.sort()
    return (
        sum(samples) / len(samples),
        samples[len(samples) // 2],
        float(samples[-1]),
    )


def losing_streak(trades: list[dict]) -> int:
    ordered = sorted(trades, key=lambda t: (t["closed"], t["opened"], t["symbol"]))
    best = cur = 0
    for t in ordered:
        if t["pnl"] < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def symbol_scores(trades: list[dict]) -> dict[str, float]:
    by: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by[t["symbol"]].append(t)
    rows = []
    fieldnames = [
        "SYMBOL",
        "TRADES",
        "WINS",
        "LOSSES",
        "PCT_WINS",
        "TOTAL_PNL",
        "SHEET_PNL",
        "AVG_PNL_PCT",
        "AVG_PNL_PCT_WO_MAX",
        "AVG_TRADES_PER_YEAR",
        "AVG_DAYS_HELD",
        "OUTLIER_PCT_OF_WINS",
        "PROFIT_FACTOR",
        "MAX_WIN_PCT",
    ]
    fits = []
    robust = []
    pf_s = []
    wo = []
    out_l = []
    tpy_l = []
    maxw = []
    for sym, group in by.items():
        pnls = [g["pnl"] for g in group]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        avg = sum(pnls) / len(pnls)
        mx = max(pnls) if pnls else 0.0
        wo_avg = avg
        if len(pnls) >= 2 and mx > 0:
            rest = [p for p in pnls if p != mx or pnls.count(mx) > 1]
            # drop one max
            dropped = False
            kept = []
            for p in pnls:
                if not dropped and p == mx:
                    dropped = True
                    continue
                kept.append(p)
            wo_avg = sum(kept) / len(kept) if kept else avg
        span_days = (max(g["closed"] for g in group) - min(g["opened"] for g in group)).days
        years = max(span_days / 365.25, 1.0)
        tpy = len(group) / years
        sheet = sum(g["pnl_d"] for g in group)
        outlier = (100.0 * max(wins) / sum(wins)) if wins and sum(wins) > 0 else 0.0
        gp = sum(wins)
        gl = abs(sum(losses))
        pf = (gp / gl) if gl > 0 else (gp if gp > 0 else 0.0)
        closed_rows = [{"PNL %": p} for p in pnls]
        fit = assess_symbol_fit(
            trades=len(group),
            wins=len(wins),
            losses=len(losses),
            pct_wins=100.0 * len(wins) / len(group),
            avg_pnl_pct=avg,
            sheet_pnl=sheet,
            avg_tpy=tpy,
            closed_rows=closed_rows,
        )
        fits.append(fit.score)
        robust.append(fit.score_robust)
        pf_s.append(pf)
        wo.append(wo_avg)
        out_l.append(outlier)
        tpy_l.append(tpy)
        maxw.append(max(wins) if wins else 0.0)
        rows.append(
            {
                "SYMBOL": sym,
                "TRADES": len(group),
                "WINS": len(wins),
                "LOSSES": len(losses),
                "PCT_WINS": 100.0 * len(wins) / len(group),
                "TOTAL_PNL": sheet,
                "SHEET_PNL": sheet,
                "AVG_PNL_PCT": avg,
                "AVG_PNL_PCT_WO_MAX": wo_avg,
                "AVG_TRADES_PER_YEAR": tpy,
                "AVG_DAYS_HELD": sum(g["days"] for g in group) / len(group),
                "OUTLIER_PCT_OF_WINS": outlier,
                "PROFIT_FACTOR": pf,
                "MAX_WIN_PCT": max(wins) if wins else 0.0,
            }
        )
    apply_paul_scores_to_summary_rows(rows, fieldnames)
    pauls = [num(r.get("PAUL_SCORE")) for r in rows]
    pauls = [p for p in pauls if math.isfinite(p)]

    def mean(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    return {
        "paul_sum": sum(pauls) if pauls else float("nan"),
        "paul_mean": mean(pauls),
        "fit_sum": sum(fits) if fits else float("nan"),
        "fit_mean": mean(fits),
        "robust_sum": sum(robust) if robust else float("nan"),
        "robust_mean": mean(robust),
        "mean_pf": mean(pf_s),
        "mean_wo": mean(wo),
        "mean_outlier": mean(out_l),
        "mean_tpy": mean(tpy_l),
        "mean_max_win": mean(maxw),
        "n_symbols": len(rows),
    }


def book_metrics(trades: list[dict]) -> dict:
    n = len(trades)
    empty = {"n": 0}
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    dollars = [t["pnl_d"] for t in trades]
    days = [t["days"] for t in trades if t["days"] > 0]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_d = [t["pnl_d"] for t in trades if t["pnl"] > 0]
    loss_d = [t["pnl_d"] for t in trades if t["pnl"] < 0]
    mapped = [
        {
            "pnl": t["pnl"],
            "pnl_d": t["pnl_d"],
            "days": t["days"],
            "closed": t["closed"],
            "opened": t["opened"],
        }
        for t in trades
    ]
    ov = overlay_ann_ror_max_dd(mapped, cash=CASH, initial_account=INIT)
    mx = max(pnls)
    wo = pnls
    if n >= 2 and mx > 0:
        dropped = False
        kept = []
        for p in pnls:
            if not dropped and p == mx:
                dropped = True
                continue
            kept.append(p)
        wo = kept
    gp = sum(win_d)
    gl = abs(sum(loss_d))
    pf = gp / gl if gl > 0 else (gp if gp > 0 else 0.0)
    total = sum(dollars)
    by_sym: dict[str, float] = defaultdict(float)
    by_ind: dict[str, float] = defaultdict(float)
    exits: dict[str, int] = defaultdict(int)
    for t in trades:
        by_sym[t["symbol"]] += t["pnl_d"]
        by_ind[t["industry"]] += t["pnl_d"]
        exits[t["exit_type"]] += 1
    max_sym = max(by_sym.values()) if by_sym else 0.0
    max_trade = max(dollars) if dollars else 0.0
    max_ind = max(by_ind.values(), key=abs) if by_ind else 0.0
    ordered_d = sorted(dollars)
    top10 = sum(ordered_d[-10:]) if ordered_d else 0.0
    bot10 = sum(ordered_d[:10]) if ordered_d else 0.0
    avg_pos, med_pos, max_pos = positions_stats(trades)
    scores = symbol_scores(trades)
    ces = [t["pnl"] / t["days"] for t in trades if t["days"] > 0]
    ann = ov["ann_ror"]
    dd = ov["max_dd"]
    calmar = ov["calmar"]
    return {
        "n": n,
        "symbols": len(by_sym),
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg": sum(pnls) / n,
        "wo_max": sum(wo) / len(wo) if wo else float("nan"),
        "exp_d": total / n,
        "exp_pct": sum(pnls) / n,
        "avg_win": sum(wins) / len(wins) if wins else float("nan"),
        "avg_loss": sum(losses) / len(losses) if losses else float("nan"),
        "wl_n": (len(wins) / len(losses)) if losses else float("nan"),
        "wl_d": (abs(sum(wins) / len(wins)) / abs(sum(losses) / len(losses)))
        if wins and losses
        else float("nan"),
        "pf": pf,
        "ann": ann,
        "dd": dd,
        "calmar": calmar,
        "sharpe": ov["sharpe"],
        "sharpe_src": ov.get("sharpe_source") or "",
        "cap_days": sum(days),
        "ppc": (total / sum(days)) if days else float("nan"),
        "avg_days": sum(days) / len(days) if days else float("nan"),
        "med_days": statistics.median(days) if days else float("nan"),
        "p90_days": _pctile(days, 0.9),
        "streak": losing_streak(trades),
        "avg_pos": avg_pos,
        "med_pos": med_pos,
        "max_pos": max_pos,
        "pct_sym": (max_sym / total * 100) if total else float("nan"),
        "pct_trade": (max_trade / total * 100) if total else float("nan"),
        "pct_ind": (abs(max_ind) / abs(total) * 100) if total else float("nan"),
        "pct_top10": (top10 / total * 100) if total else float("nan"),
        "pct_bot10": (bot10 / total * 100) if total else float("nan"),
        "ces_avg": sum(ces) / len(ces) if ces else float("nan"),
        "ces_med": statistics.median(ces) if ces else float("nan"),
        "exits": dict(exits),
        "total_d": total,
        **{f"s_{k}": v for k, v in scores.items()},
    }


def fnum(x, d=2, suffix=""):
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x:.{d}f}{suffix}"


def fdelta(x, d=2, suffix=""):
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.{d}f}{suffix}"


def money_or(x):
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return format_money(x)


def money_d(x):
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return format_money_delta(x)


METRIC_ROWS = [
    ("Universe size", "symbols", "num", False),
    ("Total trades", "n", "num", False),
    ("Wins", "wins", "num", False),
    ("Losses", "losses", "num", False),
    ("Win %", "wr", "pct", False),
    ("Avg PnL %", "avg", "pct", False),
    ("Book AVG_PNL_PCT_WO_MAX", "wo_max", "pct", False),
    ("Expectancy $", "exp_d", "money", False),
    ("Expectancy %", "exp_pct", "pct", False),
    ("Avg win %", "avg_win", "pct", False),
    ("Avg loss %", "avg_loss", "pct", False),
    ("Win/Loss ratio (count)", "wl_n", "num", False),
    ("Win/Loss ratio $", "wl_d", "num", False),
    ("Profit factor", "pf", "num", False),
    ("Ann ROR %", "ann", "pct", False),
    ("Max DD %", "dd", "pct", True),
    ("Calmar", "calmar", "num", False),
    ("Sharpe", "sharpe", "num", False),
    ("Profit per capital day", "ppc", "money", False),
    ("Capital days", "cap_days", "num", True),
    ("Avg days held", "avg_days", "num", True),
    ("Median days held", "med_days", "num", False),
    ("P90 days held", "p90_days", "num", False),
    ("Losing streak", "streak", "num", True),
    ("Avg positions", "avg_pos", "num", False),
    ("Median positions", "med_pos", "num", False),
    ("Max positions", "max_pos", "num", False),
    ("Pct PnL max symbol", "pct_sym", "pct", True),
    ("Pct PnL max trade", "pct_trade", "pct", True),
    ("Pct PnL max industry", "pct_ind", "pct", True),
    ("Pct PnL top10", "pct_top10", "pct", False),
    ("Pct PnL bottom10", "pct_bot10", "pct", False),
    ("CES avg", "ces_avg", "num", False),
    ("CES median", "ces_med", "num", False),
    ("Σ Paul Score", "s_paul_sum", "num", False),
    ("Mean Paul Score", "s_paul_mean", "num", False),
    ("Σ FIT Score", "s_fit_sum", "num", False),
    ("Mean FIT Score", "s_fit_mean", "num", False),
    ("Σ FIT Score Robust", "s_robust_sum", "num", False),
    ("Mean FIT Score Robust", "s_robust_mean", "num", False),
    ("Mean AVG_PNL_PCT_WO_MAX", "s_mean_wo", "pct", False),
    ("Mean OUTLIER_PCT_OF_WINS", "s_mean_outlier", "pct", True),
    ("Mean AVG_TRADES_PER_YEAR", "s_mean_tpy", "num", False),
    ("Mean MAX_WIN_PCT", "s_mean_max_win", "pct", False),
    ("Mean profit factor (per symbol)", "s_mean_pf", "num", False),
]


def cell(m, key, kind):
    if not m or key not in m:
        return "—"
    v = m[key]
    if kind == "pct":
        return fnum(v, 2, "%")
    if kind == "money":
        return money_or(v)
    if kind == "num" and key in {"n", "wins", "losses", "symbols", "streak", "cap_days"}:
        return fnum(v, 0)
    return fnum(v, 2)


def dcell(a, b, key, kind, lower_better=False):
    if not a or not b or key not in a or key not in b:
        return "—"
    x, y = a[key], b[key]
    if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
        return "—"
    if not (math.isfinite(x) and math.isfinite(y)):
        return "—"
    d = y - x
    if kind == "money":
        return money_d(d)
    if kind == "pct":
        return fdelta(d, 2, " pp" if key in {"wr"} else "")
    return fdelta(d, 2)


def metric_table(title, control, cand) -> str:
    rows = []
    for label, key, kind, _lower in METRIC_ROWS:
        rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{cell(control, key, kind)}</td>"
            f"<td>{cell(cand, key, kind)}</td>"
            f"<td>{dcell(control, cand, key, kind)}</td>"
            "</tr>"
        )
    body = "\n".join(rows)
    return f"""
<h2>{html.escape(title)}</h2>
<div class="table-wrap"><table class="sortable">
<caption>Click column headers to sort. Candidate minus control. Annualized rate of return uses one $47,500 slot per trade. Maximum drawdown is lower when the number is smaller.</caption>
<thead><tr>
<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Metric<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Today's Rocket Launcher<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Look-left filter<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Delta<span class="sort-ind"></span></th>
</tr></thead>
<tbody>
{body}
</tbody></table></div>
"""


def exit_table(control, cand) -> str:
    keys = sorted(set(control.get("exits", {})) | set(cand.get("exits", {})))
    rows = []
    nc = max(control.get("n") or 1, 1)
    nk = max(cand.get("n") or 1, 1)
    for k in keys:
        c = control.get("exits", {}).get(k, 0)
        d = cand.get("exits", {}).get(k, 0)
        rows.append(
            "<tr>"
            f"<td>{html.escape(k)}</td>"
            f"<td>{c}</td><td>{c / nc * 100:.1f}%</td>"
            f"<td>{d}</td><td>{d / nk * 100:.1f}%</td>"
            f"<td>{d - c:+d}</td>"
            "</tr>"
        )
    body = "\n".join(rows)
    return f"""
<h2>Exit mix</h2>
<div class="table-wrap"><table class="sortable">
<caption>Click column headers to sort. Same exit on both arms: sell 80% at +20%, leftover stop at the buy, leftover target +40%.</caption>
<thead><tr>
<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Exit<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Control n<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Control %<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Filter n<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Filter %<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Delta n<span class="sort-ind"></span></th>
</tr></thead>
<tbody>
{body}
</tbody></table></div>
"""


def monday_rows() -> list[dict]:
    """The four Monday signals that filled Tuesday 2026-09-29."""
    wanted = {
        "DOCU": "Software. Photo title reads DOCU / DocuSign, last about 65.97.",
        "ZETA": "Software. Photo title reads Zeta Global, last about 28.",
        "PAYC": "Software. Photo last price matches Monday's 220.58 scanner close.",
        "SSRM": "Miner, not software. Chart title on the remaining photos was not reliable.",
    }
    opens = {}
    with OPEN.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sym = (row.get("SYMBOL") or "").strip().upper()
            if sym in wanted:
                opens[sym] = row
    # judge needs shelves; caller fills
    return [
        {
            "symbol": sym,
            "note": wanted[sym],
            "entry": num(opens[sym].get("ENTRY PRICE")) if sym in opens else float("nan"),
            "opened": ymd(opens[sym].get("DATE OPENED")) if sym in opens else date(2026, 9, 29),
            "open_pnl": opens[sym].get("PNL %") if sym in opens else "",
        }
        for sym in ("DOCU", "PAYC", "ZETA", "SSRM")
    ]


def mts_docu_html() -> str:
    if not MTS_DOCU.exists():
        return "<p>DOCU Magic Touch file was not found.</p>"
    rows = []
    with MTS_DOCU.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('DATE_OPENED','')))}</td>"
            f"<td>{html.escape(str(row.get('ENTRY_PRICE','')))}</td>"
            f"<td>{html.escape(str(row.get('ZONE_CENTER','')))}</td>"
            f"<td>{html.escape(str(row.get('ENTRY_PIVOT_TYPE','')))}</td>"
            f"<td>{html.escape(str(row.get('MATURITY_DATE','')))}</td>"
            f"<td>{html.escape(str(row.get('DATE_CLOSED','')))}</td>"
            f"<td>{html.escape(str(row.get('EXIT_PRICE','')))}</td>"
            f"<td>{html.escape(str(row.get('EXIT_TYPE','')))}</td>"
            f"<td>{html.escape(str(row.get('PNL_PCT','')))}</td>"
            "</tr>"
        )
    return (
        "<div class='table-wrap'><table class='sortable'>"
        "<caption>Click column headers to sort. DOCU is not in the daily Magic Touch universe, "
        "so these four fills are a one-name rerun of the same Magic Touch rules. "
        "The level the note points at is the December 2025 buy near 66 against a pivot-high zone near 70.71.</caption>"
        "<thead><tr>"
        + "".join(
            f'<th class="sortable-th" data-sort="{k}" tabindex="0" role="columnheader" aria-sort="none">{lab}<span class="sort-ind"></span></th>'
            for lab, k in (
                ("Opened", "date"),
                ("Entry", "num"),
                ("Zone center", "num"),
                ("Pivot", "text"),
                ("Matured", "date"),
                ("Closed", "date"),
                ("Exit", "num"),
                ("Exit type", "text"),
                ("PnL %", "num"),
            )
        )
        + "</tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table></div>"
    )


def monday_html(items: list[dict]) -> str:
    body = []
    for t in items:
        taken = "Yes — filled 2026-09-29" 
        filt = "No — skip" if t.get("skip") else "Yes — keep"
        body.append(
            "<tr>"
            f"<td>{html.escape(t['symbol'])}</td>"
            f"<td>{t['entry']:.2f}</td>"
            f"<td>{html.escape(taken)}</td>"
            f"<td>{html.escape(filt)}</td>"
            f"<td>{fnum(t.get('touch'), 2)}</td>"
            f"<td>{fnum(t.get('shelf_lo'), 2)}</td>"
            f"<td>{fnum(t.get('shelf_hi'), 2)}</td>"
            f"<td>{fnum(t.get('overhead_pct'), 1, '%')}</td>"
            f"<td>{fnum(t.get('bounce_pct'), 1, '%')}</td>"
            f"<td>{html.escape(t.get('reason') or '')}</td>"
            f"<td>{html.escape(t.get('note') or '')}</td>"
            "</tr>"
        )
    return (
        "<div class='table-wrap'><table class='sortable'>"
        "<caption>Click column headers to sort. Monday 2026-09-28 Rocket Launcher scanner: DOCU, PAYC, SSRM, ZETA. "
        "All four filled the next morning. The filter uses that fill price.</caption>"
        "<thead><tr>"
        + "".join(
            f'<th class="sortable-th" data-sort="{k}" tabindex="0" role="columnheader" aria-sort="none">{html.escape(lab)}<span class="sort-ind"></span></th>'
            for lab, k in (
                ("Symbol", "text"),
                ("Fill 2026-09-29", "num"),
                ("Today's Rocket Launcher", "text"),
                ("Look-left filter", "text"),
                ("Shelf", "num"),
                ("Shelf low", "num"),
                ("Shelf high", "num"),
                ("Overhead", "num"),
                ("Bounce off 63-session low", "num"),
                ("Why", "text"),
                ("Photo", "text"),
            )
        )
        + "</tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table></div>"
    )


SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text" || type === "date") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "").replace(/pp/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      var an = Number.isFinite(av) ? av : (dir > 0 ? Infinity : -Infinity);
      var bn = Number.isFinite(bv) ? bv : (dir > 0 ? Infinity : -Infinity);
      return dir * (an - bn);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def verdict_text(isc, isk, oosc, oosk) -> tuple[str, str]:
    """Return (verdict, paragraph). IS quality first. OOS softens -> HOLD."""
    def better_quality(a, b):
        # b is candidate. Quality: higher avg, wr, pf, ann, and not a worse drawdown, N not cut in half.
        if a["n"] <= 0 or b["n"] <= 0:
            return "unclear"
        n_ok = b["n"] >= 0.5 * a["n"]
        avg_up = b["avg"] > a["avg"] + 0.15
        wr_up = b["wr"] > a["wr"] + 0.5
        pf_up = b["pf"] > a["pf"] + 0.05
        ann_up = math.isfinite(b["ann"]) and math.isfinite(a["ann"]) and b["ann"] > a["ann"] + 0.5
        dd_ok = (not math.isfinite(b["dd"])) or (not math.isfinite(a["dd"])) or b["dd"] <= a["dd"] + 1.0
        ups = sum([avg_up, wr_up, pf_up, ann_up])
        worse = (
            b["avg"] < a["avg"] - 0.15
            and b["pf"] < a["pf"] - 0.05
            and (not math.isfinite(b["ann"]) or not math.isfinite(a["ann"]) or b["ann"] < a["ann"] - 0.5)
        )
        if worse or not n_ok and b["avg"] <= a["avg"]:
            return "worse"
        if ups >= 3 and dd_ok and n_ok:
            return "better"
        return "flat"

    is_q = better_quality(isc, isk)
    oos_soft = False
    if oosc.get("n") and oosk.get("n") and math.isfinite(oosc.get("ann", float("nan"))) and math.isfinite(oosk.get("ann", float("nan"))):
        oos_soft = oosk["ann"] + 0.5 < oosc["ann"] or (
            oosk["avg"] + 0.15 < oosc["avg"] and oosk["wr"] + 0.5 < oosc["wr"]
        )
    if is_q == "worse":
        v = "DISMISS"
        why = "In-sample quality is worse under the frozen skip rule."
    elif is_q == "better" and oos_soft:
        v = "HOLD"
        why = "In-sample quality is better, and out-of-sample softens. Out-of-sample is report-only. Do not retune."
    elif is_q == "better":
        v = "KEEP"
        why = "In-sample quality improves without cutting the book in half, and out-of-sample does not soften. Research only."
    else:
        v = "HOLD"
        why = "In-sample quality is flat. Not enough to keep the skip rule."
    return v, why


def write_csv(trades: list[dict]) -> None:
    path = STAMP / "trades.csv"
    fields = [
        "symbol",
        "entry_date",
        "exit_date",
        "entry_price",
        "pnl_pct",
        "slot_pnl",
        "days_held",
        "exit_type",
        "industry",
        "skip",
        "bounce_pct",
        "overhead_pct",
        "shelf_touch",
        "shelf_lo",
        "shelf_hi",
        "shelf_pivot",
        "reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow(
                {
                    "symbol": t["symbol"],
                    "entry_date": t["opened"].isoformat(),
                    "exit_date": t["closed"].isoformat(),
                    "entry_price": f"{t['entry']:.4f}",
                    "pnl_pct": f"{t['pnl']:.4f}",
                    "slot_pnl": f"{t['pnl_d']:.2f}",
                    "days_held": f"{t['days']:.0f}",
                    "exit_type": t["exit_type"],
                    "industry": t["industry"],
                    "skip": int(bool(t["skip"])),
                    "bounce_pct": "" if not math.isfinite(t["bounce_pct"]) else f"{t['bounce_pct']:.2f}",
                    "overhead_pct": "" if not math.isfinite(t["overhead_pct"]) else f"{t['overhead_pct']:.2f}",
                    "shelf_touch": "" if not math.isfinite(t["touch"]) else f"{t['touch']:.4f}",
                    "shelf_lo": "" if not math.isfinite(t["shelf_lo"]) else f"{t['shelf_lo']:.4f}",
                    "shelf_hi": "" if not math.isfinite(t["shelf_hi"]) else f"{t['shelf_hi']:.4f}",
                    "shelf_pivot": t.get("pivot_date") or "",
                    "reason": t.get("reason") or "",
                }
            )


def write_outputs(trades, monday, full_c, full_k, is_c, is_k, oos_c, oos_k, verdict, why):
    n_skip = sum(1 for t in trades if t["skip"])
    quote = "<br>\n".join(html.escape(USER_QUOTE).split("\n"))
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Rocket Launcher look-left — 2026-09-30</title>
<style>
  :root {{
    --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
    --card:#fff; --accent:#2a4a5c; --accent-soft:#e8eef2; --fill:#f0eee6;
    --ok:#2d6a4f; --ok-bg:#e8f2ec; --warn:#8a5a12; --warn-bg:#f7efe0; --bad:#9b2226; --bad-bg:#fdecea;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",Georgia,serif; font-size:15px; line-height:1.55; color:var(--ink);
    background:radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%), var(--bg); }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:32px 22px 64px; }}
  h1 {{ font-size:1.6rem; margin:0 0 8px; }}
  h2 {{ font-size:1.12rem; margin:26px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }}
  .lede {{ color:var(--muted); max-width:78ch; }}
  .callout {{ background:var(--accent-soft); border-left:4px solid var(--accent); padding:12px 14px; margin:14px 0; }}
  .callout.warn {{ background:var(--warn-bg); border-left-color:var(--warn); }}
  .badge {{ display:inline-block; font-weight:700; padding:2px 8px; background:var(--warn-bg); color:var(--warn); }}
  code {{ font-family:Consolas,monospace; font-size:0.88em; background:var(--fill); padding:0.05em 0.3em; }}
  .table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ border:1px solid var(--line); padding:7px 8px; text-align:left; vertical-align:top; }}
  thead th {{ background:var(--fill); }}
  th.sortable-th {{ cursor:pointer; user-select:none; }}
  th.sortable-th:hover {{ background:#e8e4d8; }}
  .sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#9a9588; font-size:10px; }}
  th.sort-asc .sort-ind::after {{ content:"▲"; color:var(--ink); }}
  th.sort-desc .sort-ind::after {{ content:"▼"; color:var(--ink); }}
  caption {{ text-align:left; font-size:0.82rem; color:var(--muted); margin:0 0 6px; caption-side:top; }}
  footer {{ margin-top:28px; font-size:0.8rem; color:var(--muted); border-top:1px solid var(--line); padding-top:12px; }}
</style>
</head>
<body>
<div class="wrap">
<p class="badge">Research only · not gold · not DailyRun</p>
<h1>Rocket Launcher: look left for resistance</h1>
<p class="lede">Control is today's production Rocket Launcher book (stamp 260930184039). The candidate drops buys that are already extended into an uncleared Magic Touch (MTS) pivot-high shelf. The exit does not change.</p>

<div class="callout">
<strong>What you asked</strong>
<p>{quote}</p>
</div>
<div class="callout">
<strong>In plain English</strong>
<p>Rocket Launcher buys a dip in an uptrend. The note says also look left. If there is a ceiling of prior trading just overhead, or the stock has already bounced a long way into that ceiling, skip it. The comparison is today's Rocket Launcher versus the same buys with that skip rule.</p>
<p>Magic Touch (MTS) is the system that already draws those ceilings and floors from pivot highs and pivot lows. A pivot-high zone is the red supply band. Annualized rate of return (Ann ROR) is how fast the slot compounds from the average trade and how long trades are held. In-sample (IS) is a buy before 2024-01-01. Out-of-sample (OOS) is a buy on or after that date. OOS is report-only.</p>
</div>

<h2>Verdict: {html.escape(verdict)}</h2>
<p>{html.escape(why)} The rule was frozen from Monday's four signals and the Magic Touch zone math before this table was ranked. Dropped {n_skip} of {len(trades)} closed trades. Not gold. Not wired into DailyRun.</p>

<h2>The frozen rule</h2>
<p>Skip the buy only when both are true, measured at the next-morning fill:</p>
<ol>
<li><strong>Overhead shelf.</strong> A Magic Touch pivot-high zone (local high in a 4-bar window, then a drop of at least 6% within 7 bars, into a high that rose at least 12% over the prior 7 bars, then a pullback of at least 6% over the next 7 bars). The band is that high plus or minus 1.8%. The zone is usable 7 bars after the pivot. It is still supply if no later close through the signal day has closed above the top of the band. It is nearby when the bottom of the band is at most 15% above the fill, or the fill is already inside the band.</li>
<li><strong>Already a big move.</strong> The fill is more than 45% above the lowest low of the 63 sessions ending on the signal day.</li>
</ol>
<p>Knobs: <code>overhead_pct=0.15</code>, <code>bounce_pct=0.45</code>, <code>bounce_bars=63</code>, Magic Touch <code>band_pct=0.018</code>, pivot window 4, pre 7 bars / 12%, post 7 bars / 6%, maturity lag 7. One combined candidate. No second variant.</p>

<h2>Monday 2026-09-28 signals</h2>
<p>Scanner file <code>drive/RL_Scanner_260928184043.csv</code> (same four names all day): DOCU, PAYC, SSRM, ZETA. Tuesday's open book <code>RL_Open_260930184039.csv</code> shows all four filled on 2026-09-29. Three are software (DocuSign, Paycom, Zeta Global). SSR Mining is the one that is not. The filter drops the three software names and keeps SSRM.</p>
{monday_html(monday)}

<h2>Charts</h2>
<ul>
<li>One photo's title is readable as <strong>DOCU</strong> (DocuSign), last about 65.97. Price is well off a spike. The red ceiling just overhead lines up with the Magic Touch pivot-high near 70–71.</li>
<li>One photo's title is readable as <strong>ZETA</strong> (Zeta Global), last about 28, with price bouncing up toward a red band.</li>
<li>One photo's last price reads about 220.58, which is Paycom's (PAYC) Monday scanner close. Red band overhead, green band below, price bouncing.</li>
<li>The other two titles were not reliable on the monitor photos. The only remaining Monday Rocket Launcher signal is SSRM. One photo shows a failed red shelf and price back on a green band; another is a long chart pressing up into a red line.</li>
</ul>

<h2>Magic Touch trades in DOCU</h2>
<p>DOCU is not in the daily Magic Touch universe, so the production closed file has no DOCU rows. A one-name rerun of the production Magic Touch rules produced four trades. The one at the level on the chart is the 2025-12-08 buy at 66.09 against a pivot-high zone centered at 70.71. It stopped out at 59.22 (−10.39%). Tuesday's Rocket Launcher buy is 66.27, the same neighborhood, and that shelf family is still uncleared (nearest live pivot-high 70.40 from 2026-09-04, band 69.13–71.67). An October 2025 Magic Touch buy at 70.16 used a pivot-low zone at 67.30 and also stopped out.</p>
{mts_docu_html()}

<h2>How the book is scored</h2>
<p>Control file <code>drive/RL_Closed_260930184039.csv</code>. Entries stay production: <code>rl_too_high=0</code>, <code>rl_dip_pct=1.055</code>, <code>rl_cut_the_losers=1000</code>, ATR off, slope 0. Exit stays <code>rl_scale_ladder=0.20:0.80:0</code>, leftover stop at the buy, leftover target +40%, no time exit, no Simple Moving Average (SMA) target. Each closed trade is one $47,500 slot. Slot dollars are the closed percent times $47,500. Annualized rate of return is <code>((1 + total slot dollars / (47500 × trades)) ^ (365 / average days held) − 1)</code>. Maximum drawdown and Sharpe use exit-date equity on a $500,000 account (Sharpe is the exit-date series, not a daily √252 curve). The published DailyRun report on this same file prints annualized rate of return 21.77%, profit factor 1.60, and maximum drawdown 10.7%. That ledger is the engine's sized dollars divided by a different cash figure ($4,237), so it is not the equal-slot number. Both arms here use the equal-slot math, so the difference is the skip rule. Days underwater and the aggressive account path are not rebuilt. Paul Score and FIT Score are recomputed on each arm's own symbols at the same slot.</p>

{metric_table("Full book", full_c, full_k)}
{metric_table("In-sample (entry before 2024-01-01)", is_c, is_k)}
{metric_table("Out-of-sample (entry on or after 2024-01-01) — report only", oos_c, oos_k)}
{exit_table(full_c, full_k)}

<h2>Limitation</h2>
<p>This is a filter on trades Rocket Launcher already took. Rocket Launcher holds one position per symbol at a time. Skipping a trade would have freed that symbol for a later dip that never appears in this book. Those extra trades are not added back. Industry labels come from the DailyRun summary file. Symbols with no price file are kept.</p>
<footer>Stamp rl_lookleft_resistance_20260930 · research candidate · not gold · not DailyRun</footer>
</div>
{SORT_JS}
</body></html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")

    def line(label, a, b, key, kind="num"):
        return f"| {label} | {cell(a, key, kind)} | {cell(b, key, kind)} | {dcell(a, b, key, kind)} |"

    md = f"""# Rocket Launcher look-left — 2026-09-30

## What you asked

{USER_QUOTE}

## In plain English

Rocket Launcher buys a dip in an uptrend. The note says also look left. If there is a ceiling of prior trading just overhead, or the stock has already bounced a long way into that ceiling, skip it. The comparison is today's Rocket Launcher versus the same buys with that skip rule.

Magic Touch (MTS) already draws those ceilings from pivot highs. Annualized rate of return (Ann ROR) compounds the average slot by how long trades are held. In-sample (IS) is a buy before 2024-01-01. Out-of-sample (OOS) is a buy on or after that date, report only.

## Verdict

**{verdict}.** {why}

Research only. Not gold. Not DailyRun. The exit was not changed. The filter was not wired into `run_rl.bat` or the trigger file.

## Freeze (set before the book was ranked)

| Knob | Value |
|---|---|
| Control entries | `rl_too_high=0`, `rl_dip_pct=1.055`, `rl_cut_the_losers=1000`, ATR off, slope 0 |
| Exit (unchanged) | `rl_scale_ladder=0.20:0.80:0`, leftover stop at the entry, `rl_entry_target_pct=0.40`, `rl_sma_target_off=1`, no time exit |
| Control file | `drive/RL_Closed_260930184039.csv` (DailyRun stamp 260930184039) |
| Universe | Full `data/newdata/data` names that are in that closed file |
| Slot | $47,500 (`rl_cash`) |
| Overhead | Uncleared Magic Touch pivot-high band (band ±1.8%, pivot window 4, pre 7/12%, post 7/6%, mature +7). Lower edge within 15% above the fill, or the fill inside the band. No close above the band top through the signal day. |
| Big move | Fill more than 45% above the lowest low of the 63 sessions ending on the signal day |
| Combined | Skip only when overhead AND the big move are both true |
| IS / OOS | entry before / on-or-after 2024-01-01 |
| Selection | 15%, 45%, and 63 were frozen to match Monday's four charts (three software names extended into a nearby shelf; SSRM's bounce stayed under 45%). They were not chosen by searching this book's profit. |

Magic Touch zone identity matches `run_mts.bat` / `compute_sheet_brt_touch_stream` (pivot-high origin). DOCU is outside the daily Magic Touch universe. A one-name rerun is in `mts_docu/`. The December 2025 DOCU trade bought 66.09 against pivot-high zone center 70.71 and stopped out. Tuesday's Rocket Launcher fill is 66.27 with the live shelf at 70.40 (band 69.13–71.67).

## Monday signals

| Symbol | Fill | Today's Rocket Launcher | Filter |
|---|---|---|---|
"""
    for t in monday:
        md += f"| {t['symbol']} | {t['entry']:.2f} | took it 2026-09-29 | {'skip' if t.get('skip') else 'keep'} |\n"
    md += f"""
## Compare (equal slot)

Published DailyRun ledger on the same closed file (not used for the delta): annualized rate of return 21.77%, profit factor 1.60, maximum drawdown 10.7%, average 2.76%, win rate 42.26%, trades 3888. That ledger divides sized dollars by cash $4,237. The table below uses percent × $47,500 on both arms.

### Full

| Metric | Control | Look-left | Delta |
|---|---:|---:|---:|
{line("Trades", full_c, full_k, "n")}
{line("Win %", full_c, full_k, "wr", "pct")}
{line("Avg PnL %", full_c, full_k, "avg", "pct")}
{line("Profit factor", full_c, full_k, "pf")}
{line("Ann ROR %", full_c, full_k, "ann", "pct")}
{line("Max DD %", full_c, full_k, "dd", "pct")}

### In-sample

| Metric | Control | Look-left | Delta |
|---|---:|---:|---:|
{line("Trades", is_c, is_k, "n")}
{line("Win %", is_c, is_k, "wr", "pct")}
{line("Avg PnL %", is_c, is_k, "avg", "pct")}
{line("Profit factor", is_c, is_k, "pf")}
{line("Ann ROR %", is_c, is_k, "ann", "pct")}
{line("Max DD %", is_c, is_k, "dd", "pct")}

### Out-of-sample (report only)

| Metric | Control | Look-left | Delta |
|---|---:|---:|---:|
{line("Trades", oos_c, oos_k, "n")}
{line("Win %", oos_c, oos_k, "wr", "pct")}
{line("Avg PnL %", oos_c, oos_k, "avg", "pct")}
{line("Profit factor", oos_c, oos_k, "pf")}
{line("Ann ROR %", oos_c, oos_k, "ann", "pct")}
{line("Max DD %", oos_c, oos_k, "dd", "pct")}

## Limitation

Skipping a trade does not free the symbol for a later Rocket Launcher dip that the frozen book never took. One position per symbol at a time means those later trades are missing from both arms.
"""
    (STAMP / "BASELINE.md").write_text(md, encoding="utf-8")


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    industry = load_industry()
    trades = load_closed(industry)
    print("trades", len(trades), flush=True)
    annotate(trades)
    kept = [t for t in trades if not t["skip"]]
    print("kept", len(kept), "skipped", len(trades) - len(kept), flush=True)
    is_all = [t for t in trades if t["opened"] < IS_CUT]
    oos_all = [t for t in trades if t["opened"] >= IS_CUT]
    is_k = [t for t in kept if t["opened"] < IS_CUT]
    oos_k = [t for t in kept if t["opened"] >= IS_CUT]
    print("scoring full control", flush=True)
    full_c = book_metrics(trades)
    print("scoring full candidate", flush=True)
    full_k = book_metrics(kept)
    print("scoring IS/OOS", flush=True)
    is_c = book_metrics(is_all)
    is_km = book_metrics(is_k)
    oos_c = book_metrics(oos_all)
    oos_km = book_metrics(oos_k)
    monday = monday_rows()
    # shelves already computed inside annotate via per-trade judge; redo monday with cache by calling judge on packs rebuilt... 
    # Reuse by judging from a fresh shelf build for the four names only.
    for t in monday:
        pack = build_shelves(t["symbol"])
        j = judge(pack, t["entry"], t["opened"])
        t.update(j)
        print("MON", t["symbol"], "skip", t["skip"], t["reason"], flush=True)
    v, why = verdict_text(is_c, is_km, oos_c, oos_km)
    print("VERDICT", v, why, flush=True)
    for name, m in (
        ("FULL C", full_c),
        ("FULL K", full_k),
        ("IS C", is_c),
        ("IS K", is_km),
        ("OOS C", oos_c),
        ("OOS K", oos_km),
    ):
        print(
            name,
            "n", m.get("n"),
            "wr", round(m.get("wr", float("nan")), 2),
            "avg", round(m.get("avg", float("nan")), 2),
            "ann", round(m.get("ann", float("nan")), 2) if math.isfinite(m.get("ann", float("nan"))) else None,
            "dd", round(m.get("dd", float("nan")), 2) if math.isfinite(m.get("dd", float("nan"))) else None,
            "pf", round(m.get("pf", float("nan")), 2),
            flush=True,
        )
    write_csv(trades)
    write_outputs(trades, monday, full_c, full_k, is_c, is_km, oos_c, oos_km, v, why)
    print("wrote", STAMP, flush=True)


if __name__ == "__main__":
    main()
