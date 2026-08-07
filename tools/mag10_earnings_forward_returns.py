#!/usr/bin/env python3
"""Mag10 post-earnings forward returns vs earnings surprise.

Universe (YH Mag10): AAPL, AMD, AMZN, AU, GOOGL, META, MSFT, NFLX, NVDA, TSLA

Event day assumption
--------------------
Use ``earnings_date`` from ``drive/fundamentals_cache.duckdb`` (``yf_earnings_dates``)
as the event calendar day. Align to the OHLC bar on that date; if that session is
missing, use the **next** available bar. Forward returns are measured from:

- **Close path:** close on the event bar
- **Next-open path (optional):** open of the session **after** the event bar

Horizons: 5 / 10 / 15 / 20 trading days to the close of that later bar.

  RET_C_Nd = (Close[event+N] - Close[event]) / Close[event] * 100
  RET_O_Nd = (Close[event+N] - Open[event+1]) / Open[event+1] * 100

Only historical announcements with a known/reported date are included
(``earnings_date <= as_of`` and at least one of eps_reported / surprise_pct, or
past date with OHLC). Future dated rows are excluded.

``surprise_pct`` is treated as a fraction (0.05 = +5%). Values with |s| > 2 are
assumed to be percent-points and divided by 100 (Yahoo mix).

Outputs
-------
  drive/paul_experiments/Mag10_Earnings_Forward_Returns.html
  drive/paul_experiments/Mag10_Earnings_Forward_Returns.csv
  drive/paul_experiments/Mag10_Earnings_Forward_Returns_summary.csv

Usage
-----
  python tools/mag10_earnings_forward_returns.py
  python tools/mag10_earnings_forward_returns.py --as-of 2026-08-07
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analysis.fundamentals_yfinance import (  # noqa: E402
    DEFAULT_FUNDAMENTALS_DB,
    resolve_fundamentals_db,
)

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments"
DEFAULT_DATA_DIR = ROOT / "data" / "newdata" / "data"
DEFAULT_DB = DEFAULT_FUNDAMENTALS_DB

MAG10 = ("AAPL", "AMD", "AMZN", "AU", "GOOGL", "META", "MSFT", "NFLX", "NVDA", "TSLA")
HORIZONS = (5, 10, 15, 20)

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim().replace(/[$,%]/g,"").replace(/,/g,"");
    if(type==="num"){var n=parseFloat(t); return isNaN(n)?null:n;}
    if(type==="date"||type==="month"){return t;}
    return t.toLowerCase();
  }
  function bind(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th, colIdx){
      th.addEventListener("click", function(){
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        ths.forEach(function(x){
          x.classList.remove("sort-asc","sort-desc");
          x.setAttribute("aria-sort","none");
        });
        th.classList.add(asc?"sort-asc":"sort-desc");
        th.setAttribute("aria-sort", asc?"ascending":"descending");
        var tbody=table.tBodies[0]; if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll("tr")).filter(function(r){
          return !r.classList.contains("total-row");
        });
        rows.sort(function(a,b){
          var av=parseCell(a.children[colIdx], type), bv=parseCell(b.children[colIdx], type);
          if(av==null&&bv==null) return 0;
          if(av==null) return 1; if(bv==null) return -1;
          if(av<bv) return asc?-1:1; if(av>bv) return asc?1:-1; return 0;
        });
        rows.forEach(function(r){tbody.appendChild(r);});
      });
      th.addEventListener("keydown", function(e){
        if(e.key==="Enter"||e.key===" "){e.preventDefault(); th.click();}
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _fmt(x, kind: str = "num", digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "—"
    if kind == "int":
        return f"{int(x):,}"
    if kind == "pct":
        return f"{float(x):.{digits}f}%"
    if kind == "r":
        return f"{float(x):.{digits}f}"
    if kind == "p":
        return f"{float(x):.{digits}g}"
    return f"{float(x):.{digits}f}"


def normalize_surprise_pct(s: Optional[float]) -> Optional[float]:
    """Fraction form; |s|>2 treated as Yahoo percent-points."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    v = float(s)
    if abs(v) > 2.0:
        v = v / 100.0
    return v


def load_ohlc(path: Path) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(
            path,
            usecols=lambda c: str(c).strip().lower()
            in {"date", "open", "high", "low", "close", "volume"},
            low_memory=False,
        )
    except Exception:
        return None
    if df.empty:
        return None
    lower = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for want in ("Date", "Open", "High", "Low", "Close", "Volume"):
        src = lower.get(want.lower())
        if src is not None:
            rename[src] = want
    df = df.rename(columns=rename)
    if any(c not in df.columns for c in ("Date", "Open", "Close")):
        return None
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Date"]).sort_values("Date", ignore_index=True)
    for c in ("Open", "Close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Open", "Close"])
    return df if len(df) else None


def load_mag10_earnings(db_path: Path, symbols: Sequence[str], as_of: date) -> pd.DataFrame:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        placeholders = ",".join(["?"] * len(symbols))
        df = con.execute(
            f"""
            SELECT symbol, earnings_date, eps_estimate, eps_reported, surprise_pct, fetched_at
            FROM yf_earnings_dates
            WHERE symbol IN ({placeholders})
            ORDER BY symbol, earnings_date
            """,
            list(symbols),
        ).fetchdf()
    finally:
        con.close()

    if df.empty:
        return df
    df["earnings_date"] = pd.to_datetime(df["earnings_date"], errors="coerce").dt.date
    df["surprise_pct_raw"] = pd.to_numeric(df["surprise_pct"], errors="coerce")
    df["surprise_pct"] = df["surprise_pct_raw"].map(normalize_surprise_pct)
    df["eps_estimate"] = pd.to_numeric(df["eps_estimate"], errors="coerce")
    df["eps_reported"] = pd.to_numeric(df["eps_reported"], errors="coerce")

    # Historical / known: on or before as_of, and not a blank future placeholder
    rows = []
    for r in df.itertuples(index=False):
        ed = r.earnings_date
        if ed is None or (isinstance(ed, float) and np.isnan(ed)):
            continue
        if ed > as_of:
            continue
        has_report = (
            (r.eps_reported is not None and not (isinstance(r.eps_reported, float) and np.isnan(r.eps_reported)))
            or (r.surprise_pct is not None and not (isinstance(r.surprise_pct, float) and np.isnan(r.surprise_pct)))
            or ed < as_of  # past calendar date even if surprise missing
        )
        if not has_report:
            continue
        rows.append(r)
    out = pd.DataFrame(rows)
    return out


def event_bar_index(dates: np.ndarray, event: date) -> Optional[int]:
    """Index of event day bar, or next session if missing."""
    ed = np.datetime64(event, "D")
    # dates are datetime64[ns] normalized
    d64 = dates.astype("datetime64[D]")
    pos = int(np.searchsorted(d64, ed, side="left"))
    if pos >= len(d64):
        return None
    return pos


def compute_event_returns(
    earnings: pd.DataFrame,
    data_dir: Path,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    records: list[dict] = []
    by_sym = {s: g for s, g in earnings.groupby("symbol", sort=False)}
    for sym in sorted(by_sym.keys()):
        path = data_dir / f"{sym}.csv"
        ohlc = load_ohlc(path) if path.exists() else None
        if ohlc is None:
            for r in by_sym[sym].itertuples(index=False):
                rec = {
                    "symbol": sym,
                    "earnings_date": r.earnings_date,
                    "event_bar_date": None,
                    "used_next_bar": None,
                    "eps_estimate": r.eps_estimate,
                    "eps_reported": r.eps_reported,
                    "surprise_pct": r.surprise_pct,
                    "surprise_pct_raw": r.surprise_pct_raw,
                    "event_close": np.nan,
                    "next_open": np.nan,
                    "ohlc_missing": True,
                }
                for n in horizons:
                    rec[f"RET_C_{n}D"] = np.nan
                    rec[f"RET_O_{n}D"] = np.nan
                records.append(rec)
            continue

        dates = ohlc["Date"].to_numpy()
        opens = ohlc["Open"].to_numpy(dtype=np.float64)
        closes = ohlc["Close"].to_numpy(dtype=np.float64)

        for r in by_sym[sym].itertuples(index=False):
            i = event_bar_index(dates, r.earnings_date)
            rec = {
                "symbol": sym,
                "earnings_date": r.earnings_date,
                "event_bar_date": None,
                "used_next_bar": None,
                "eps_estimate": r.eps_estimate,
                "eps_reported": r.eps_reported,
                "surprise_pct": r.surprise_pct,
                "surprise_pct_raw": r.surprise_pct_raw,
                "event_close": np.nan,
                "next_open": np.nan,
                "ohlc_missing": False,
            }
            if i is None:
                rec["ohlc_missing"] = True
                for n in horizons:
                    rec[f"RET_C_{n}D"] = np.nan
                    rec[f"RET_O_{n}D"] = np.nan
                records.append(rec)
                continue

            event_bar = pd.Timestamp(dates[i]).date()
            used_next = event_bar != r.earnings_date
            rec["event_bar_date"] = event_bar
            rec["used_next_bar"] = used_next
            c0 = float(closes[i])
            rec["event_close"] = c0
            if i + 1 < len(opens):
                rec["next_open"] = float(opens[i + 1])

            for n in horizons:
                j = i + int(n)
                if j >= len(closes) or not np.isfinite(c0) or c0 == 0:
                    rec[f"RET_C_{n}D"] = np.nan
                else:
                    rec[f"RET_C_{n}D"] = (float(closes[j]) - c0) / c0 * 100.0

                # Next-session open baseline: need open[i+1] and close[i+N]
                if i + 1 >= len(opens) or j >= len(closes):
                    rec[f"RET_O_{n}D"] = np.nan
                else:
                    o1 = float(opens[i + 1])
                    if not np.isfinite(o1) or o1 == 0:
                        rec[f"RET_O_{n}D"] = np.nan
                    else:
                        rec[f"RET_O_{n}D"] = (float(closes[j]) - o1) / o1 * 100.0

            # Drop events that cannot fill any horizon (too recent / short history)
            if all(np.isnan(rec.get(f"RET_C_{n}D", np.nan)) for n in horizons):
                # still keep if we want coverage audit — skip incomplete for main stats
                pass
            records.append(rec)

    return pd.DataFrame.from_records(records)


def _ret_stats(s: pd.Series) -> dict:
    s = pd.to_numeric(s, errors="coerce").dropna()
    n = int(len(s))
    if n == 0:
        return {
            "n": 0,
            "mean_pct": np.nan,
            "median_pct": np.nan,
            "std_pct": np.nan,
            "pct_positive": np.nan,
        }
    return {
        "n": n,
        "mean_pct": float(s.mean()),
        "median_pct": float(s.median()),
        "std_pct": float(s.std(ddof=1)) if n > 1 else np.nan,
        "pct_positive": float((s > 0).mean() * 100.0),
    }


def summarize_returns(events: pd.DataFrame, horizons: Sequence[int] = HORIZONS) -> pd.DataFrame:
    rows: list[dict] = []
    scopes = [("ALL", events)] + [
        (sym, events[events["symbol"] == sym]) for sym in MAG10 if (events["symbol"] == sym).any()
    ]
    for scope, sub in scopes:
        for side, prefix in (("close", "RET_C"), ("next_open", "RET_O")):
            for n in horizons:
                col = f"{prefix}_{n}D"
                if col not in sub.columns:
                    continue
                st = _ret_stats(sub[col])
                rows.append(
                    {
                        "scope": scope,
                        "side": side,
                        "horizon_d": int(n),
                        "ret_col": col,
                        **st,
                    }
                )
    return pd.DataFrame(rows)


def correlate_surprise(
    events: pd.DataFrame, horizons: Sequence[int] = HORIZONS
) -> pd.DataFrame:
    rows: list[dict] = []
    usable = events.dropna(subset=["surprise_pct"]).copy()
    scopes = [("ALL", usable)] + [
        (sym, usable[usable["symbol"] == sym]) for sym in MAG10 if (usable["symbol"] == sym).any()
    ]
    for scope, sub in scopes:
        for side, prefix in (("close", "RET_C"), ("next_open", "RET_O")):
            for n in horizons:
                col = f"{prefix}_{n}D"
                if col not in sub.columns:
                    continue
                pair = sub[["surprise_pct", col]].dropna()
                n_obs = int(len(pair))
                if n_obs < 5:
                    rows.append(
                        {
                            "scope": scope,
                            "side": side,
                            "horizon_d": int(n),
                            "ret_col": col,
                            "n": n_obs,
                            "pearson_r": np.nan,
                            "pearson_p": np.nan,
                            "spearman_rho": np.nan,
                            "spearman_p": np.nan,
                        }
                    )
                    continue
                x = pair["surprise_pct"].to_numpy(dtype=float)
                y = pair[col].to_numpy(dtype=float)
                pr, pp = stats.pearsonr(x, y)
                sr, sp = stats.spearmanr(x, y)
                rows.append(
                    {
                        "scope": scope,
                        "side": side,
                        "horizon_d": int(n),
                        "ret_col": col,
                        "n": n_obs,
                        "pearson_r": float(pr),
                        "pearson_p": float(pp),
                        "spearman_rho": float(sr),
                        "spearman_p": float(sp),
                    }
                )
    return pd.DataFrame(rows)


def _verdict(corr: pd.DataFrame, summary: pd.DataFrame) -> tuple[str, list[str]]:
    bullets: list[str] = []
    all_c = corr[(corr["scope"] == "ALL") & (corr["side"] == "close")].copy()
    if all_c.empty or all_c["pearson_r"].isna().all():
        return (
            "Insufficient Mag10 surprise×return pairs for a correlation verdict.",
            ["Check fundamentals cache coverage and OHLC history."],
        )

    max_abs_r = float(all_c["pearson_r"].abs().max())
    best = all_c.loc[all_c["pearson_r"].abs().idxmax()]
    bullets.append(
        f"Strongest ALL Mag10 close-path Pearson |r|: {best['ret_col']} "
        f"r={best['pearson_r']:.3f} (p={best['pearson_p']:.3g}, n={int(best['n'])})."
    )
    max_abs_rho = float(all_c["spearman_rho"].abs().max()) if all_c["spearman_rho"].notna().any() else float("nan")
    if not np.isnan(max_abs_rho):
        best_s = all_c.loc[all_c["spearman_rho"].abs().idxmax()]
        bullets.append(
            f"Strongest Spearman |ρ|: {best_s['ret_col']} ρ={best_s['spearman_rho']:.3f} "
            f"(p={best_s['spearman_p']:.3g})."
        )

    all_sum = summary[(summary["scope"] == "ALL") & (summary["side"] == "close")]
    for _, row in all_sum.sort_values("horizon_d").iterrows():
        bullets.append(
            f"{int(row['horizon_d'])}d close: mean={row['mean_pct']:.2f}%, "
            f"median={row['median_pct']:.2f}%, %pos={row['pct_positive']:.1f}% (n={int(row['n'])})."
        )

    if max_abs_r < 0.10:
        headline = (
            f"No useful linear link: Mag10 surprise_pct vs forward returns max |r|~{max_abs_r:.3f} "
            f"(effectively near zero). Surprise does not reliably predict 5-20d post-earnings drift here."
        )
    elif max_abs_r < 0.25:
        headline = (
            f"Only a weak surprise vs forward-return link (max |r|~{max_abs_r:.3f}). "
            f"Not actionable as a standalone Mag10 edge."
        )
    else:
        headline = (
            f"Moderate surprise vs forward-return association (max |r|~{max_abs_r:.3f}) - "
            f"worth a closer look, but still noisy at Mag10 sample size."
        )
    bullets.append(
        "Caveat: earnings often after close; using earnings_date close (or next bar) mixes "
        "same-day reaction with post-print drift. Next-open path better isolates post-print."
    )
    return headline, bullets


def _table_from_df(df: pd.DataFrame, cols: list[tuple[str, str, str]], fmt_map: dict) -> str:
    """cols: (key, label, sort_type)."""
    esc = html_mod.escape
    ths = "".join(_sortable_th(lab, st) for _, lab, st in cols)
    body = []
    for _, row in df.iterrows():
        tds = []
        for key, _, _ in cols:
            v = row.get(key)
            kind = fmt_map.get(key, "num")
            if kind == "text":
                tds.append(f"<td>{esc(str(v) if v is not None else '—')}</td>")
            elif kind == "date":
                tds.append(f"<td>{esc(str(v) if v is not None and str(v) != 'NaT' else '—')}</td>")
            elif kind == "bool":
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    tds.append("<td>—</td>")
                else:
                    tds.append(f"<td>{'Y' if bool(v) else 'N'}</td>")
            else:
                tds.append(f"<td>{_fmt(v, kind)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        f'<table class="sortable"><thead><tr>{ths}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def write_html(
    *,
    events: pd.DataFrame,
    summary: pd.DataFrame,
    corr: pd.DataFrame,
    coverage: pd.DataFrame,
    meta: dict,
    out_html: Path,
) -> None:
    headline, bullets = _verdict(corr, summary)
    esc = html_mod.escape
    bullet_li = "".join(f"<li>{esc(b)}</li>" for b in bullets)

    sum_close = summary[summary["side"] == "close"].sort_values(["scope", "horizon_d"])
    sum_open = summary[summary["side"] == "next_open"].sort_values(["scope", "horizon_d"])
    corr_close = corr[corr["side"] == "close"].sort_values(["scope", "horizon_d"])
    corr_open = corr[corr["side"] == "next_open"].sort_values(["scope", "horizon_d"])

    sum_cols = [
        ("scope", "Scope", "text"),
        ("horizon_d", "Horizon (d)", "num"),
        ("n", "N", "num"),
        ("mean_pct", "Mean RET %", "num"),
        ("median_pct", "Median RET %", "num"),
        ("std_pct", "Std %", "num"),
        ("pct_positive", "% Positive", "num"),
    ]
    sum_fmt = {
        "scope": "text",
        "horizon_d": "int",
        "n": "int",
        "mean_pct": "pct",
        "median_pct": "pct",
        "std_pct": "pct",
        "pct_positive": "pct",
    }
    corr_cols = [
        ("scope", "Scope", "text"),
        ("horizon_d", "Horizon (d)", "num"),
        ("n", "N", "num"),
        ("pearson_r", "Pearson r", "num"),
        ("pearson_p", "Pearson p", "num"),
        ("spearman_rho", "Spearman ρ", "num"),
        ("spearman_p", "Spearman p", "num"),
    ]
    corr_fmt = {
        "scope": "text",
        "horizon_d": "int",
        "n": "int",
        "pearson_r": "r",
        "pearson_p": "p",
        "spearman_rho": "r",
        "spearman_p": "p",
    }
    cov_cols = [
        ("symbol", "Symbol", "text"),
        ("n_cache_past", "Past dates in cache", "num"),
        ("n_events", "Events used", "num"),
        ("n_with_surprise", "With surprise", "num"),
        ("n_with_ret_c_5", "With RET_C_5D", "num"),
        ("min_earnings", "Min earnings", "date"),
        ("max_earnings", "Max earnings", "date"),
    ]
    cov_fmt = {
        "symbol": "text",
        "n_cache_past": "int",
        "n_events": "int",
        "n_with_surprise": "int",
        "n_with_ret_c_5": "int",
        "min_earnings": "date",
        "max_earnings": "date",
    }

    # Event detail (compact)
    detail = events.copy()
    detail_cols = [
        ("symbol", "Symbol", "text"),
        ("earnings_date", "Earnings date", "date"),
        ("event_bar_date", "Event bar", "date"),
        ("used_next_bar", "Next bar?", "text"),
        ("surprise_pct", "Surprise (frac)", "num"),
        ("eps_reported", "EPS reported", "num"),
        ("eps_estimate", "EPS est", "num"),
        ("event_close", "Event close", "num"),
        ("next_open", "Next open", "num"),
    ]
    for n in HORIZONS:
        detail_cols.append((f"RET_C_{n}D", f"RET_C_{n}D %", "num"))
    for n in HORIZONS:
        detail_cols.append((f"RET_O_{n}D", f"RET_O_{n}D %", "num"))
    detail_fmt = {k: "num" for k, _, _ in detail_cols}
    detail_fmt.update(
        {
            "symbol": "text",
            "earnings_date": "date",
            "event_bar_date": "date",
            "used_next_bar": "bool",
            "surprise_pct": "r",
        }
    )
    # Sort detail newest first
    if "earnings_date" in detail.columns:
        detail = detail.sort_values(["earnings_date", "symbol"], ascending=[False, True])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mag10 Earnings Forward Returns</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1600px; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
.sub {{ color:#64748b; margin-bottom:16px; line-height:1.5; font-size:0.95rem; }}
.caption {{ font-size:12px; color:#64748b; margin:6px 0 10px; }}
.verdict {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:14px 16px; margin:12px 0 20px; }}
.verdict strong {{ display:block; margin-bottom:8px; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:6px 8px; text-align:left; white-space:nowrap; }}
th {{ background:#f1f5f9; }}
{SORTABLE_TH_CSS}
code {{ font-size:11px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
ul {{ line-height:1.55; }}
</style></head><body>
<h1>Mag10 post-earnings forward returns</h1>
<p class="sub">
  YH Mag10: {esc(", ".join(MAG10))}.<br>
  Generated {esc(meta.get("generated", ""))}.
  As-of {esc(str(meta.get("as_of")))}.
  DB <code>{esc(str(meta.get("db")))}</code>.
  OHLC <code>{esc(str(meta.get("data_dir")))}</code>.
  Events used: {esc(str(meta.get("n_events")))}
  (with surprise: {esc(str(meta.get("n_with_surprise")))}).
</p>

<div class="verdict">
  <strong>Verdict</strong>
  {esc(headline)}
  <ul>{bullet_li}</ul>
</div>

<div class="verdict">
  <strong>Assumptions</strong>
  <ul>
    <li>Event day = <code>earnings_date</code>; if that close is missing, use the next OHLC bar.</li>
    <li><code>RET_C_Nd</code> from event-bar close; <code>RET_O_Nd</code> from open of the next session after the event bar — both to close N trading days later.</li>
    <li>Horizons: 5, 10, 15, 20 trading days. Future earnings dates excluded.</li>
    <li><code>surprise_pct</code> as fraction (0.05 = +5%); |raw| &gt; 2 divided by 100.</li>
  </ul>
</div>

<h2>1. Coverage by symbol</h2>
<p class="caption">Click column headers to sort.</p>
<div class="table-wrap">{_table_from_df(coverage, cov_cols, cov_fmt)}</div>

<h2>2. Mean / median / % positive — from event close</h2>
<p class="caption">Click column headers to sort. Scope ALL = pooled Mag10.</p>
<div class="table-wrap">{_table_from_df(sum_close, sum_cols, sum_fmt)}</div>

<h2>3. Mean / median / % positive — from next-session open</h2>
<p class="caption">Click column headers to sort.</p>
<div class="table-wrap">{_table_from_df(sum_open, sum_cols, sum_fmt)}</div>

<h2>4. Correlation: surprise_pct vs forward RET (close path)</h2>
<p class="caption">Click column headers to sort. Non-null surprise only.</p>
<div class="table-wrap">{_table_from_df(corr_close, corr_cols, corr_fmt)}</div>

<h2>5. Correlation: surprise_pct vs forward RET (next-open path)</h2>
<p class="caption">Click column headers to sort.</p>
<div class="table-wrap">{_table_from_df(corr_open, corr_cols, corr_fmt)}</div>

<h2>6. Event detail</h2>
<p class="caption">Click column headers to sort. Returns in percent.</p>
<div class="table-wrap">{_table_from_df(detail, detail_cols, detail_fmt)}</div>

{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")


def build_coverage(events: pd.DataFrame, earnings_raw_counts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym in MAG10:
        sub = events[events["symbol"] == sym] if len(events) else events
        past_n = 0
        if len(earnings_raw_counts) and (earnings_raw_counts["symbol"] == sym).any():
            past_n = int(earnings_raw_counts.loc[earnings_raw_counts["symbol"] == sym, "n_past"].iloc[0])
        rows.append(
            {
                "symbol": sym,
                "n_cache_past": past_n,
                "n_events": int(len(sub)),
                "n_with_surprise": int(sub["surprise_pct"].notna().sum()) if len(sub) else 0,
                "n_with_ret_c_5": int(sub["RET_C_5D"].notna().sum()) if len(sub) and "RET_C_5D" in sub.columns else 0,
                "min_earnings": sub["earnings_date"].min() if len(sub) else None,
                "max_earnings": sub["earnings_date"].max() if len(sub) else None,
            }
        )
    return pd.DataFrame(rows)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="fundamentals DuckDB path")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    as_of = date.today()
    if args.as_of:
        as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    db = resolve_fundamentals_db(args.db)
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    import duckdb

    con = duckdb.connect(str(db), read_only=True)
    try:
        placeholders = ",".join(["?"] * len(MAG10))
        raw_counts = con.execute(
            f"""
            SELECT symbol,
                   COUNT(*) FILTER (WHERE earnings_date <= ?) AS n_past
            FROM yf_earnings_dates
            WHERE symbol IN ({placeholders})
            GROUP BY symbol
            """,
            [as_of, *MAG10],
        ).fetchdf()
    finally:
        con.close()

    earnings = load_mag10_earnings(db, MAG10, as_of)
    events = compute_event_returns(earnings, data_dir, HORIZONS)
    # Prefer events that have at least one close return (drop pure placeholders)
    if len(events) and "RET_C_5D" in events.columns:
        has_any = events[[f"RET_C_{n}D" for n in HORIZONS]].notna().any(axis=1)
        # Keep rows even without returns for coverage, but summary uses available NaNs
        _ = has_any

    summary = summarize_returns(events, HORIZONS)
    corr = correlate_surprise(events, HORIZONS)
    coverage = build_coverage(events, raw_counts)

    csv_path = out_dir / "Mag10_Earnings_Forward_Returns.csv"
    sum_path = out_dir / "Mag10_Earnings_Forward_Returns_summary.csv"
    corr_path = out_dir / "Mag10_Earnings_Forward_Returns_corr.csv"
    html_path = out_dir / "Mag10_Earnings_Forward_Returns.html"

    events.to_csv(csv_path, index=False)
    summary.to_csv(sum_path, index=False)
    corr.to_csv(corr_path, index=False)

    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "as_of": as_of,
        "db": db,
        "data_dir": data_dir,
        "n_events": int(len(events)),
        "n_with_surprise": int(events["surprise_pct"].notna().sum()) if len(events) else 0,
    }
    write_html(
        events=events,
        summary=summary,
        corr=corr,
        coverage=coverage,
        meta=meta,
        out_html=html_path,
    )

    headline, _ = _verdict(corr, summary)
    print(f"Wrote {html_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {sum_path}")
    print(f"Wrote {corr_path}")
    print(f"Events={meta['n_events']} with_surprise={meta['n_with_surprise']}")
    print(f"VERDICT: {headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
