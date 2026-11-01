#!/usr/bin/env python3
"""Cap-band transfer of spx_trend_ab_20260916.

Same equal-weight top-5, 126-trading-day book and the same frozen trend
overlays, restricted each January to one market-cap bucket.

Research only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)
from run_spx_diversification import (  # noqa: E402
    INITIAL_CAPITAL,
    load_price_panels,
    metrics_from_equity,
    run_one_backtest,
)
from run_spx_trend_ab import (  # noqa: E402
    ARMS,
    COST_BPS,
    IS_CUT,
    TrendBook,
    _fmt,
    _fmt_money,
    judge_book,
    make_filter,
    result_payload,
)
from trendline_slopes_paultwenty import (  # noqa: E402
    MONTH_FREQ,
    PIVOT_K,
    WEEK_FREQ,
    confirmed_pivots_daily,
    confirmed_pivots_htf,
)

STAMP = REPO / "drive" / "paul_experiments" / "spx_trend_capband_ab_20261009"
DB_PATH = REPO / "data" / "ohlcv.duckdb"
YF_CACHE = REPO / "yfinance_cache.json"
PARENT = "spx_trend_ab_20260916"
X = 5
N = 126

ORIGINAL_REQUEST = (
    "lets build on this spx_trend_ab_20260916 how would this strategy work "
    "for mega caps, large, mid, small and micro cap stocks"
)

LAYMAN = (
    "The earlier test owns the five biggest Standard & Poor's 500 (S&P 500) "
    "stocks with equal dollars, refreshes the list each January, and checks "
    "the weights about twice a year. Drawing a support line under the weekly "
    "chart and skipping or selling when that line is falling, broken, or the "
    "price is stretched did not beat just holding the five. This test asks "
    "the same question one company-size at a time. Each January we estimate "
    "market cap by scaling today's size by how much the price has changed, "
    "keep only the stocks in one bucket, and buy the five largest still in "
    "that bucket. Mega-cap is $200 billion and up. Large-cap is $10 billion "
    "up to $200 billion. Mid-cap is $2 billion up to $10 billion. Small-cap "
    "is $300 million up to $2 billion. Micro-cap is $50 million up to "
    "$300 million (a floor so the tiniest shells are left out). If a bucket "
    "has fewer than five names, the book holds however many qualify. The "
    "practice years are before 2024. From 2024 on is the exam, and we do not "
    "change the rules to fit the exam. Research only."
)

# Inclusive low, exclusive high. None = no cap.
BANDS: list[dict[str, Any]] = [
    {"id": "mega", "label": "Mega-cap", "lo": 200e9, "hi": None, "plain": "$200 billion and up"},
    {"id": "large", "label": "Large-cap", "lo": 10e9, "hi": 200e9, "plain": "$10 billion up to $200 billion"},
    {"id": "mid", "label": "Mid-cap", "lo": 2e9, "hi": 10e9, "plain": "$2 billion up to $10 billion"},
    {"id": "small", "label": "Small-cap", "lo": 300e6, "hi": 2e9, "plain": "$300 million up to $2 billion"},
    {"id": "micro", "label": "Micro-cap", "lo": 50e6, "hi": 300e6, "plain": "$50 million up to $300 million"},
]

# Same-company share classes. Keep the larger cached cap.
DUAL_GROUPS = [
    ("GOOG", "GOOGL"),
    ("BRK-A", "BRK-B"),
    ("BRK.A", "BRK.B"),
    ("BF-A", "BF-B"),
    ("BF.A", "BF.B"),
    ("FOX", "FOXA"),
    ("NWS", "NWSA"),
    ("UA", "UAA"),
    ("HEI", "HEI.A"),
    ("LEN", "LEN.B"),
]


def _esc(s: Any) -> str:
    return html_mod.escape("" if s is None else str(s))


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{_esc(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _band_plain(band: dict[str, Any]) -> str:
    return str(band["plain"])


def load_mcap() -> tuple[dict[str, float], str]:
    cache = json.loads(YF_CACHE.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    asof = ""
    for sym, entry in cache.items():
        if not isinstance(entry, dict):
            continue
        mc = entry.get("market_cap")
        if mc is None or float(mc) <= 0:
            continue
        out[str(sym).upper()] = float(mc)
        asof = asof or str(entry.get("as_of_date") or "")
    return out, asof


def drop_dual_class(mcap: dict[str, float]) -> list[str]:
    dropped: list[str] = []
    for group in DUAL_GROUPS:
        present = [s for s in group if s in mcap]
        if len(present) < 2:
            continue
        keep = max(present, key=lambda s: mcap[s])
        for s in present:
            if s != keep:
                mcap.pop(s, None)
                dropped.append(f"{s} (kept {keep})")
    return dropped


def fill_trend(book: TrendBook, symbols: list[str]) -> None:
    if not symbols:
        return
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            """
            SELECT symbol, date AS Date, open AS Open, high AS High, low AS Low, close AS Close
            FROM prices
            WHERE symbol IN (SELECT * FROM UNNEST(?::VARCHAR[]))
            ORDER BY symbol, date
            """,
            [symbols],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        book.missing.extend(symbols)
        return
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    have = set(df["symbol"].astype(str))
    for sym in symbols:
        if sym not in have:
            book.missing.append(sym)
    n = 0
    for sym, g in df.groupby("symbol", sort=False):
        g = g.drop(columns=["symbol"]).drop_duplicates("Date").sort_values("Date").reset_index(drop=True)
        if len(g) < 30:
            book.missing.append(str(sym))
            continue
        dates = list(g["Date"])
        book.pack[str(sym)] = {
            "dates": dates,
            "close": [float(x) for x in g["Close"]],
            "date_set": set(dates),
            "piv_d": confirmed_pivots_daily(g, PIVOT_K["daily"]),
            "piv_w": confirmed_pivots_htf(g, WEEK_FREQ, PIVOT_K["weekly"]),
            "piv_m": confirmed_pivots_htf(g, MONTH_FREQ, PIVOT_K["monthly"]),
        }
        n += 1
        if n % 40 == 0:
            print(f"  trendlines {n}", flush=True)
    print(f"  trendlines ready {n}, missing {len(book.missing)}", flush=True)


def january_counts(
    closes: pd.DataFrame,
    mcap: dict[str, float],
) -> list[dict[str, Any]]:
    syms = [c for c in closes.columns if c != "SPY" and c in mcap]
    panel = closes[syms]
    ref = np.array(
        [
            float(panel[s].dropna().iloc[-1]) if panel[s].notna().any() else np.nan
            for s in syms
        ],
        dtype=float,
    )
    vec = np.array([mcap[s] for s in syms], dtype=float)
    rows = []
    cal = panel.index
    for year in sorted(set(cal.year)):
        idx = np.where(cal.year == year)[0]
        if len(idx) == 0 or int(idx[0]) < 60:
            continue
        i = int(idx[0])
        px = panel.iloc[i].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            approx = vec * (px / ref)
        approx[~np.isfinite(approx) | (px <= 0)] = np.nan
        rec: dict[str, Any] = {"date": str(cal[i].date()), "year": int(year)}
        for band in BANDS:
            m = np.isfinite(approx) & (approx >= float(band["lo"]))
            if band["hi"] is not None:
                m = m & (approx < float(band["hi"]))
            rec[band["id"]] = int(m.sum())
        rows.append(rec)
    return rows


def _slice(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return payload["slices"].get(key) or {}


def _calmar(sl: dict[str, Any]) -> float | None:
    if not sl.get("ok"):
        return None
    dd = float(sl.get("max_dd") or 0)
    if dd <= 1e-9:
        return None
    return float(sl["cagr"]) / dd


def run_band(
    band: dict[str, Any],
    *,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    mcap: dict[str, float],
    trend: TrendBook | None,
    arms: list[dict[str, str]],
) -> list[dict[str, Any]]:
    calendar = closes.index
    syms = [c for c in closes.columns if c != "SPY" and c in mcap]
    rows = []
    for arm in arms:
        # Control must be allowed to sell a year with nobody left in the bucket.
        allow_empty = True
        fn = None
        if arm["id"] != "control":
            if trend is None:
                raise RuntimeError("trend book required for overlays")
            fn = make_filter(arm["id"], trend, syms, calendar)
        print(f"  {band['id']} {arm['id']}", flush=True)
        t0 = time.time()
        r = run_one_backtest(
            X=X,
            N=N,
            cost_bps=COST_BPS,
            opens=opens,
            closes=closes,
            mcap_now=mcap,
            capital0=INITIAL_CAPITAL,
            collect_extras=True,
            filter_members=fn,
            allow_empty=allow_empty,
            mcap_lo=float(band["lo"]),
            mcap_hi=None if band["hi"] is None else float(band["hi"]),
            allow_partial_book=True,
        )
        print(f"    {time.time() - t0:.1f}s ok={r.ok} cagr={r.cagr:.2f}" if r.ok else f"    FAIL {r.error}", flush=True)
        rows.append(result_payload(r, arm["id"], band["id"]))
    return rows


def _names(events: list[dict[str, Any]], which: str) -> str:
    recon = [e for e in events if e.get("kind") == "recon" and e.get("members")]
    if not recon:
        recon = [e for e in events if e.get("members")]
    if not recon:
        return "—"
    ev = recon[0] if which == "first" else recon[-1]
    return ", ".join(ev.get("members") or []) or "—"


def _ever(events: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for ev in events:
        for s in ev.get("members") or []:
            names.add(str(s))
    return sorted(names)


def spy_slices(spy: pd.Series, start: str, end: str) -> dict[str, dict[str, Any]]:
    window = spy.loc[(spy.index >= pd.Timestamp(start)) & (spy.index <= pd.Timestamp(end))].dropna()
    if len(window) < 5:
        empty = metrics_from_equity([], [])
        return {"IS": empty, "OOS": empty, "FULL": empty}
    equity = (INITIAL_CAPITAL * (window / float(window.iloc[0]))).astype(float)
    dates = [str(pd.Timestamp(d).date()) for d in equity.index]
    vals = [float(v) for v in equity.to_numpy()]
    return {
        "IS": metrics_from_equity(dates, vals, end=IS_CUT),
        "OOS": metrics_from_equity(dates, vals, start=IS_CUT),
        "FULL": metrics_from_equity(dates, vals),
    }


def write_reports(
    *,
    by_band: dict[str, list[dict[str, Any]]],
    counts: list[dict[str, Any]],
    dropped: list[str],
    cache_asof: str,
    n_universe: int,
    spy_stats: dict[str, dict[str, Any]],
    trend_missing: list[str],
) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    flat_rows: list[dict[str, Any]] = []
    verdicts: dict[tuple[str, str], tuple[str, str]] = {}
    for band in BANDS:
        rows = by_band[band["id"]]
        control = next(r for r in rows if r["arm"] == "control")
        for row in rows:
            v, why = judge_book(control, row)
            verdicts[(band["id"], row["arm"])] = (v, why)
            rec = {
                "band": band["id"],
                "arm": row["arm"],
                "ok": row["ok"],
                "verdict": v,
                "why": why,
                "start": row["start"],
                "end": row["end"],
                "final_equity": row["final_equity"],
                "avg_held": row["avg_held"],
                "min_held": row["min_held"],
                "first_roster": _names(row.get("membership") or [], "first"),
                "last_roster": _names(row.get("membership") or [], "last"),
                "n_ever": len(_ever(row.get("membership") or [])),
            }
            for sl in ("IS", "OOS", "FULL"):
                s = _slice(row, sl)
                rec[f"{sl}_cagr"] = s.get("cagr")
                rec[f"{sl}_max_dd"] = s.get("max_dd")
                rec[f"{sl}_sharpe"] = s.get("sharpe")
                rec[f"{sl}_calmar"] = _calmar(s)
                rec[f"{sl}_ok"] = s.get("ok")
            flat_rows.append(rec)
    pd.DataFrame(flat_rows).to_csv(STAMP / "compare.csv", index=False)
    pd.DataFrame(counts).to_csv(STAMP / "january_eligible.csv", index=False)

    # Lead answer from unmodified books (FULL descriptive, IS is the judge window).
    ctrl = {b["id"]: next(r for r in by_band[b["id"]] if r["arm"] == "control") for b in BANDS}
    bits = []
    for b in BANDS:
        sl = _slice(ctrl[b["id"]], "FULL")
        bits.append(f"{b['label']} {_fmt(sl.get('cagr'))}%")
    is_bits = []
    for b in BANDS:
        sl = _slice(ctrl[b["id"]], "IS")
        is_bits.append(
            f"{b['label']} CAGR {_fmt(sl.get('cagr'))}% / max drawdown {_fmt(sl.get('max_dd'))}% / Sharpe {_fmt(sl.get('sharpe'))}"
        )
    spy_full = spy_stats["FULL"]
    small_drop = next(r for r in by_band["small"] if r["arm"] == "drop_w_break")
    sd_is, sc_is = _slice(small_drop, "IS"), _slice(ctrl["small"], "IS")
    answer = (
        "The same five-name timer book is not one result across sizes. Each book owns "
        "the five largest names still inside that bucket, and a name is sold at the next "
        "January once its scaled market cap grows into the next bucket. "
        f"Full-period compound annual growth rate (CAGR): {', '.join(bits)}. "
        f"The S&P 500 exchange-traded fund (SPY) buy-and-hold was CAGR {_fmt(spy_full.get('cagr'))}% "
        f"with max drawdown {_fmt(spy_full.get('max_dd'))}%. "
        f"In-sample, before 2024: {'; '.join(is_bits)}. "
        "Mega-cap has no ceiling, so it keeps the names that get huge. That book is the "
        "parent idea, and the trend rules still do not beat just holding it. "
        "Large-cap is the weak bucket, and it sits below SPY: winners such as AAPL and "
        "GOOGL were in the 2011 large-cap five and later left when they crossed $200 billion. "
        "Mid-cap had the best in-sample balance (higher CAGR and Sharpe, a smaller drawdown "
        "than mega). Its 2024+ path cooled, which is report-only. "
        "Small-cap has the highest full-period CAGR and a drawdown around 50%. The very high "
        "2024+ CAGR is a short window on this survivor list. "
        "Micro-cap had the weakest practice period (low CAGR, drawdown above 50%, weak Sharpe). "
        "Its hot 2024+ path gets the same short-window caution."
    )

    def cell(v: Any, nd: int = 2) -> str:
        return _fmt(v, nd)

    def dlt(a: Any, b: Any) -> str:
        try:
            av, bv = float(a), float(b)
        except (TypeError, ValueError):
            return "—"
        if not (np.isfinite(av) and np.isfinite(bv)):
            return "—"
        return f"{av - bv:+.2f}"

    head_ctrl = "".join(
        sortable_th(h, t)
        for h, t in (
            ("Bucket", "text"),
            ("Size rule", "text"),
            ("Start", "date"),
            ("End", "date"),
            ("Avg names held", "num"),
            ("Full CAGR %", "num"),
            ("Full max DD %", "num"),
            ("Full Sharpe", "num"),
            ("Full Calmar", "num"),
            ("IS CAGR %", "num"),
            ("IS max DD %", "num"),
            ("IS Sharpe", "num"),
            ("OOS CAGR %", "num"),
            ("OOS max DD %", "num"),
            ("OOS Sharpe", "num"),
            ("Ending equity", "num"),
            ("First January roster", "text"),
            ("Latest January roster", "text"),
        )
    )
    body_ctrl = []
    for b in BANDS:
        row = ctrl[b["id"]]
        full, is_, oos = _slice(row, "FULL"), _slice(row, "IS"), _slice(row, "OOS")
        body_ctrl.append(
            "<tr>"
            + "".join(
                f"<td>{x}</td>"
                for x in (
                    _esc(b["label"]),
                    _esc(_band_plain(b)),
                    _esc(row["start"]),
                    _esc(row["end"]),
                    cell(row["avg_held"]),
                    cell(full.get("cagr")),
                    cell(full.get("max_dd")),
                    cell(full.get("sharpe")),
                    cell(_calmar(full)),
                    cell(is_.get("cagr")),
                    cell(is_.get("max_dd")),
                    cell(is_.get("sharpe")),
                    cell(oos.get("cagr")),
                    cell(oos.get("max_dd")),
                    cell(oos.get("sharpe")),
                    _fmt_money(row["final_equity"]),
                    _esc(_names(row.get("membership") or [], "first")),
                    _esc(_names(row.get("membership") or [], "last")),
                )
            )
            + "</tr>"
        )
    sf, si, so = spy_stats["FULL"], spy_stats["IS"], spy_stats["OOS"]
    body_ctrl.append(
        '<tr class="total-row">'
        + "".join(
            f"<td>{x}</td>"
            for x in (
                "SPY buy-and-hold",
                "Whole market fund, no 10 bps cost",
                _esc(sf.get("start")),
                _esc(sf.get("end")),
                "1",
                cell(sf.get("cagr")),
                cell(sf.get("max_dd")),
                cell(sf.get("sharpe")),
                cell(_calmar(sf)),
                cell(si.get("cagr")),
                cell(si.get("max_dd")),
                cell(si.get("sharpe")),
                cell(so.get("cagr")),
                cell(so.get("max_dd")),
                cell(so.get("sharpe")),
                _fmt_money(sf.get("final_equity")),
                "SPY",
                "SPY",
            )
        )
        + "</tr>"
    )

    head_arm = "".join(
        sortable_th(h, t)
        for h, t in (
            ("Bucket", "text"),
            ("Arm", "text"),
            ("Kind", "text"),
            ("Verdict", "text"),
            ("IS CAGR %", "num"),
            ("Δ IS CAGR", "num"),
            ("IS max DD %", "num"),
            ("Δ IS max DD", "num"),
            ("IS Sharpe", "num"),
            ("Δ IS Sharpe", "num"),
            ("OOS CAGR %", "num"),
            ("Δ OOS CAGR", "num"),
            ("OOS max DD %", "num"),
            ("Δ OOS max DD", "num"),
            ("OOS Sharpe", "num"),
            ("Δ OOS Sharpe", "num"),
            ("Full CAGR %", "num"),
            ("Avg names held", "num"),
        )
    )
    arm_meta = {a["id"]: a for a in ARMS}
    body_arm = []
    for b in BANDS:
        rows = by_band[b["id"]]
        control = next(r for r in rows if r["arm"] == "control")
        for row in rows:
            v, _why = verdicts[(b["id"], row["arm"])]
            is_, oos, full = _slice(row, "IS"), _slice(row, "OOS"), _slice(row, "FULL")
            cis, coos = _slice(control, "IS"), _slice(control, "OOS")
            body_arm.append(
                "<tr>"
                + "".join(
                    f"<td>{x}</td>"
                    for x in (
                        _esc(b["label"]),
                        _esc(row["arm"]),
                        _esc(arm_meta[row["arm"]]["kind"]),
                        _esc(v),
                        cell(is_.get("cagr")),
                        dlt(is_.get("cagr"), cis.get("cagr")),
                        cell(is_.get("max_dd")),
                        dlt(is_.get("max_dd"), cis.get("max_dd")),
                        cell(is_.get("sharpe")),
                        dlt(is_.get("sharpe"), cis.get("sharpe")),
                        cell(oos.get("cagr")),
                        dlt(oos.get("cagr"), coos.get("cagr")),
                        cell(oos.get("max_dd")),
                        dlt(oos.get("max_dd"), coos.get("max_dd")),
                        cell(oos.get("sharpe")),
                        dlt(oos.get("sharpe"), coos.get("sharpe")),
                        cell(full.get("cagr")),
                        cell(row["avg_held"]),
                    )
                )
                + "</tr>"
            )

    head_n = "".join(
        sortable_th(h, t)
        for h, t in (
            ("January", "date"),
            ("Mega", "num"),
            ("Large", "num"),
            ("Mid", "num"),
            ("Small", "num"),
            ("Micro", "num"),
        )
    )
    body_n = []
    for rec in counts:
        body_n.append(
            "<tr>"
            + "".join(
                f"<td>{x}</td>"
                for x in (
                    _esc(rec["date"]),
                    str(rec["mega"]),
                    str(rec["large"]),
                    str(rec["mid"]),
                    str(rec["small"]),
                    str(rec["micro"]),
                )
            )
            + "</tr>"
        )

    why_lines = []
    for b in BANDS:
        for row in by_band[b["id"]]:
            if row["arm"] == "control":
                continue
            v, why = verdicts[(b["id"], row["arm"])]
            why_lines.append(f"<li><strong>{_esc(b['label'])} / {_esc(row['arm'])}</strong> — {_esc(v)}. {_esc(why)}</li>")

    arm_lines = "".join(
        f"<li><strong>{_esc(a['id'])}</strong> ({_esc(a['kind'])}). {_esc(a['one_liner'])}</li>"
        for a in ARMS
    )
    ever_lines = []
    for b in BANDS:
        row = ctrl[b["id"]]
        names = _ever(row.get("membership") or [])
        ever_lines.append(
            f"<li><strong>{_esc(b['label'])}</strong> ({len(names)} names ever held): {_esc(', '.join(names))}</li>"
        )

    keeps = [
        f"{b['label']} / {row['arm']}"
        for b in BANDS
        for row in by_band[b["id"]]
        if verdicts[(b["id"], row["arm"])][0] == "KEEP"
    ]
    keep_txt = (
        "No overlay earned KEEP inside its bucket."
        if not keeps
        else (
            "Mechanical KEEP only: "
            + "; ".join(keeps)
            + f". Small-cap sell-if-through-weekly-support lifted in-sample CAGR from "
            f"{_fmt(sc_is.get('cagr'))}% to {_fmt(sd_is.get('cagr'))}% and Sharpe from "
            f"{_fmt(sc_is.get('sharpe'))} to {_fmt(sd_is.get('sharpe'))}, with max drawdown "
            f"unchanged near {_fmt(sd_is.get('max_dd'))}%. That is one of 30 overlay tests "
            f"(six rules times five buckets). The edge is small. Not gold. Not DailyRun."
        )
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Cap buckets for the S&amp;P X trend book — spx_trend_capband_ab_20261009</title>
<style>
{SORTABLE_TH_CSS}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.15rem; margin: 1.5rem 0 .4rem; }}
.meta, .caveat {{ color: #475569; max-width: 52rem; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .8rem 1rem; margin: .8rem 0; max-width: 52rem; }}
code {{ background: #e2e8f0; padding: 0 .2rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Same five-name book, five company-size buckets</h1>
<p class="meta">Research only. Not gold. Not DailyRun. Builds on <code>{PARENT}</code>. Stamp <code>spx_trend_capband_ab_20261009</code>.</p>

<h2>What you asked</h2>
<blockquote>{_esc(ORIGINAL_REQUEST)}</blockquote>

<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>

<div class="callout"><strong>What the numbers say.</strong> {_esc(answer)} { _esc(keep_txt) }</div>

<p class="meta">Click column headers to sort. {_esc("Compound annual growth rate (CAGR)")} is the equity-path growth rate from this engine. The closed-trade annualized rate of return formula does not apply: this is a continuous equal-weight account, not a list of separate closed trades. In-sample (IS) is equity dates before 2024-01-01. Out-of-sample (OOS) is 2024-01-01 onward and is report-only. Max drawdown (max DD) is the worst peak-to-trough drop. Sharpe uses daily equity returns, no risk-free rate. Calmar is CAGR divided by max DD.</p>
{SWIPE_NOTE_HTML}

<h2>Unmodified book by company size</h2>
<p class="meta">Each row owns the five largest names inside that bucket (fewer when the bucket has fewer than five). Control has no trend rule. SPY is a buy-and-hold comparison, close to close, with no trading cost.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{head_ctrl}</tr></thead>
<tbody>
{''.join(body_ctrl)}
</tbody>
</table>
</div>

<h2>Trend rules inside each bucket</h2>
<p class="meta">Deltas are versus that bucket's own unmodified book. A lower max DD is better, so a negative max-DD delta is a smaller drop. Verdicts use the same IS quality rule as the parent stamp. OOS does not pick the winner.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{head_arm}</tr></thead>
<tbody>
{''.join(body_arm)}
</tbody>
</table>
</div>

<h2>Why each overlay landed where it did</h2>
<ul>
{''.join(why_lines)}
</ul>

<h2>How many names were in each bucket each January</h2>
<p class="meta">Count of stocks in this {n_universe}-name store whose price-scaled market cap sat in the bucket on the first trading day of the year. The book buys five of them, not the whole bucket.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{head_n}</tr></thead>
<tbody>
{''.join(body_n)}
</tbody>
</table>
</div>

<h2>Names the unmodified book actually held</h2>
<ul>
{''.join(ever_lines)}
</ul>

<h2>Frozen rules</h2>
<ul>
<li>Parent engine <code>tools/run_spx_diversification.py</code>, primary book from <code>{PARENT}</code>: X=5, rebalance every 126 trading days, membership refresh on the first trading day of the year.</li>
<li>Capital {_fmt_money(INITIAL_CAPITAL)}. Costs 10 bps per side on traded dollars. Fills at the next open after the signal close.</li>
<li>Market cap at a past date ≈ today's Yahoo cap × that day's close / the latest close. Cache date { _esc(cache_asof or "unknown") }. No fresh Yahoo pull for this run.</li>
<li>Buckets: {"; ".join(_esc(b["label"] + " " + b["plain"]) for b in BANDS)}. A name can move buckets as its scaled cap changes. It leaves at the next January refresh.</li>
<li>No substitute outside the bucket. A skipped trend slot stays cash. If January has fewer than five names, hold those names equal-weight. If January has none, go to cash.</li>
<li>Dual-class drop: {_esc(", ".join(dropped) if dropped else "none")}.</li>
<li>Trend lines match the parent: confirmed swing lows, daily k=5, weekly Friday k=3, monthly k=2, scored on the signal-day close. Missing line is not treated as broken or stretched, except the arm that requires an up-sloping weekly line.</li>
<li>One rule per arm. Do not retune 2%, 10%, or 60% on 2024+.</li>
</ul>
<ul>
{arm_lines}
</ul>

<h2>Caveats</h2>
<ul class="caveat">
<li>This store is about {n_universe} names with prices and a cached market cap, not every listed micro-cap. Dead companies are missing, so smaller buckets are the survivors in this file.</li>
<li>Scaled market cap assumes the share count never changed. Buybacks and new shares make the old size approximate.</li>
<li>Mega-cap had only a couple of names in 2011–2012 in this store, so that book starts with fewer than five holdings.</li>
<li>Ten basis points per side is optimistic for micro-caps. That cost was not raised, because cost is not the knob under test.</li>
<li>The trend menu was chosen on the big-stock book. Using it here is a transfer test across 30 overlay runs. One mechanical KEEP with a small in-sample edge is not a promotion.</li>
<li>Dividends are not reinvested.</li>
<li>Trend symbols missing from the price file: {_esc(", ".join(trend_missing) if trend_missing else "none")}.</li>
</ul>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    (STAMP / "compare.html").write_text(html, encoding="utf-8")

    base = [
        "# BASELINE — spx_trend_capband_ab_20261009",
        "",
        "**Status:** Research. **Not gold. Not DailyRun.** OOS report-only. Builds on `spx_trend_ab_20260916` (primary X=5, D=126 only; the X=10 D=21 check book was not re-run).",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## What the numbers say",
        "",
        answer,
        "",
        keep_txt,
        "",
        "## Freeze",
        "",
        "- Engine: equal-weight top 5 inside the bucket, annual membership, intra-year every 126 trading days.",
        f"- Capital: ${INITIAL_CAPITAL:,.0f}. Costs: 10 bps/side. Next-open fills.",
        "- Scaled market cap = Yahoo-now × close_t / close_now. Cache as-of " + (cache_asof or "unknown") + ".",
        "- Mega ≥ $200B; large $10B–$200B; mid $2B–$10B; small $300M–$2B; micro $50M–$300M.",
        "- Partial book when the bucket has 1–4 names. Cash when it has zero.",
        "- IS equity date < 2024-01-01. OOS ≥ 2024-01-01, report-only.",
        "- Closed-trade Ann ROR does not apply (continuous book). CAGR is the equity-path compound annual growth rate.",
        "- Dual-class dropped: " + (", ".join(dropped) if dropped else "none") + ".",
        f"- Universe with a market cap: {n_universe}.",
        "",
        "## Unmodified book",
        "",
    ]
    for b in BANDS:
        row = ctrl[b["id"]]
        full, is_, oos = _slice(row, "FULL"), _slice(row, "IS"), _slice(row, "OOS")
        base.append(
            f"- **{b['label']}** ({b['plain']}): FULL CAGR {_fmt(full.get('cagr'))}% "
            f"MaxDD {_fmt(full.get('max_dd'))}% Sharpe {_fmt(full.get('sharpe'))} · "
            f"IS CAGR {_fmt(is_.get('cagr'))}% MaxDD {_fmt(is_.get('max_dd'))}% Sharpe {_fmt(is_.get('sharpe'))} · "
            f"OOS CAGR {_fmt(oos.get('cagr'))}% MaxDD {_fmt(oos.get('max_dd'))}% Sharpe {_fmt(oos.get('sharpe'))} · "
            f"avg held {_fmt(row['avg_held'])} · first {_names(row.get('membership') or [], 'first')} · "
            f"latest {_names(row.get('membership') or [], 'last')}"
        )
    base.append(
        f"- **SPY** buy-and-hold: FULL CAGR {_fmt(spy_full.get('cagr'))}% "
        f"MaxDD {_fmt(spy_full.get('max_dd'))}% Sharpe {_fmt(spy_full.get('sharpe'))}"
    )
    base += ["", "## Overlay verdicts", ""]
    for b in BANDS:
        for row in by_band[b["id"]]:
            v, why = verdicts[(b["id"], row["arm"])]
            base.append(f"- **{b['label']} / {row['arm']}** {v}: {why}")
    base += [
        "",
        "## Honesty",
        "",
        "- Parent stamp verdict on the S&P top-5 book was HOLD. These buckets do not reopen that threshold search.",
        "- Choosing a favorite bucket after seeing this table would be in-sample selection. No bucket is wired to DailyRun.",
        "",
    ]
    (STAMP / "BASELINE.md").write_text("\n".join(base) + "\n", encoding="utf-8")
    summary = {
        "stamp": "spx_trend_capband_ab_20261009",
        "parent": PARENT,
        "answer": answer,
        "keep": keeps,
        "cache_asof": cache_asof,
        "n_universe": n_universe,
        "dropped_dual": dropped,
        "rows": flat_rows,
    }
    (STAMP / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(answer, flush=True)
    print(keep_txt, flush=True)


def main() -> None:
    t0 = time.time()
    mcap, cache_asof = load_mcap()
    dropped = drop_dual_class(mcap)
    print(f"[capband] mcap {len(mcap)} cache {cache_asof} dropped {dropped}", flush=True)
    print("[capband] loading prices...", flush=True)
    opens, closes, spy = load_price_panels(sorted(mcap), start="2010-01-01")
    # Restrict mcap to names that actually loaded.
    have = {c for c in closes.columns if c != "SPY"}
    mcap = {s: v for s, v in mcap.items() if s in have}
    print(f"[capband] panel {len(closes)} days × {len(mcap)} names", flush=True)
    counts = january_counts(closes, mcap)
    print("[capband] control pass...", flush=True)
    by_band: dict[str, list[dict[str, Any]]] = {}
    ever: set[str] = set()
    for band in BANDS:
        rows = run_band(band, opens=opens, closes=closes, mcap=mcap, trend=None, arms=[ARMS[0]])
        by_band[band["id"]] = rows
        ever.update(_ever(rows[0].get("membership") or []))
    print(f"[capband] trend symbols {len(ever)}", flush=True)
    trend = TrendBook([])
    fill_trend(trend, sorted(ever))
    print("[capband] overlay pass...", flush=True)
    for band in BANDS:
        overlays = run_band(
            band,
            opens=opens,
            closes=closes,
            mcap=mcap,
            trend=trend,
            arms=[a for a in ARMS if a["id"] != "control"],
        )
        by_band[band["id"]].extend(overlays)
    start = min(r["start"] for rows in by_band.values() for r in rows if r.get("start"))
    end = max(r["end"] for rows in by_band.values() for r in rows if r.get("end"))
    spy_stats = spy_slices(spy, start, end)
    write_reports(
        by_band=by_band,
        counts=counts,
        dropped=dropped,
        cache_asof=cache_asof,
        n_universe=len(mcap),
        spy_stats=spy_stats,
        trend_missing=list(trend.missing),
    )
    print(f"[capband] done in {time.time() - t0:.1f}s -> {STAMP}", flush=True)


if __name__ == "__main__":
    main()
