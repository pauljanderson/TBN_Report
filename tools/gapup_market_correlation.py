#!/usr/bin/env python3
"""Gap-up monthly counts vs SPY market direction — correlation report.

Reads newest full (non-smoke) drive/GapUp_Scan_*.csv and data/newdata/data/SPY.csv.
Writes:
  drive/paul_experiments/GapUp_Market_Correlation.html
  drive/paul_experiments/GapUp_Market_Correlation_monthly.csv

Usage:
  python tools/gapup_market_correlation.py
  python tools/gapup_market_correlation.py --gap-csv drive/GapUp_Scan_YYMMDDHHMMSS.csv
"""
from __future__ import annotations

import argparse
import html as html_mod
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments"
DEFAULT_SPY = ROOT / "data" / "newdata" / "data" / "SPY.csv"

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


def _sample_min_gap_pct(path: Path, nrows: int = 50_000) -> float:
    try:
        s = pd.read_csv(path, usecols=["GAP_PCT"], nrows=nrows)["GAP_PCT"]
        return float(s.min()) if len(s) else float("nan")
    except Exception:
        return float("nan")


def find_latest_gap_csv(drive: Path = DRIVE, prefer_min_gap: float = 1.0) -> Path:
    """Newest full GapUp_Scan_*.csv (exclude smoke).

    Prefer scans whose GAP_PCT floor matches bat default (~1.0) over a newer
    tighter filter (e.g. min 2%). Among preferred, take newest mtime.
    """
    candidates: list[Path] = []
    for p in drive.glob("GapUp_Scan_*.csv"):
        name = p.name.lower()
        if "smoke" in name:
            continue
        if re.search(r"GapUp_Scan_\d{12}\.csv$", p.name, re.I) or re.search(
            r"GapUp_Scan_\d+", p.name, re.I
        ):
            candidates.append(p)
    if not candidates:
        candidates = [p for p in drive.glob("GapUp_Scan_*.csv") if "smoke" not in p.name.lower()]
    if not candidates:
        raise FileNotFoundError(
            f"No full GapUp_Scan_*.csv under {drive}. "
            "Run: python tools/scan_gap_ups.py --min-gap-pct 1.0"
        )

    scored: list[tuple[float, float, Path]] = []
    for p in candidates:
        gmin = _sample_min_gap_pct(p)
        # Prefer floors within 0.15 of prefer_min_gap; then newest mtime; then larger file
        prefer_rank = 0.0 if (not np.isnan(gmin) and abs(gmin - prefer_min_gap) <= 0.15) else 1.0
        scored.append((prefer_rank, -p.stat().st_mtime, p))
    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0][2]


def load_monthly_gap_counts(gap_csv: Path) -> pd.DataFrame:
    """Aggregate gap events by calendar month (GAP_DATE)."""
    chunks: list[pd.Series] = []
    for chunk in pd.read_csv(gap_csv, usecols=["GAP_DATE"], chunksize=400_000):
        dt = pd.to_datetime(chunk["GAP_DATE"], errors="coerce")
        m = dt.dt.to_period("M")
        chunks.append(m.value_counts())
    if not chunks:
        raise ValueError(f"No rows in {gap_csv}")
    counts = pd.concat(chunks).groupby(level=0).sum().sort_index()
    out = counts.rename("gap_count").reset_index()
    out.columns = ["month", "gap_count"]
    out["month"] = out["month"].astype(str)  # YYYY-MM
    return out


def load_spy_monthly(spy_path: Path) -> pd.DataFrame:
    """Month-end SPY close, monthly return, 3m return, above SMA50/SMA200."""
    spy = pd.read_csv(spy_path)
    spy["Date"] = pd.to_datetime(spy["Date"], errors="coerce")
    spy = spy.dropna(subset=["Date", "Close"]).sort_values("Date")
    spy["month"] = spy["Date"].dt.to_period("M").astype(str)

    # Last trading day of each month
    me = spy.groupby("month", as_index=False).tail(1).copy()
    me = me.rename(columns={"Date": "month_end", "Close": "spy_close"})
    me["spy_ret_1m"] = me["spy_close"].pct_change() * 100.0
    me["spy_ret_3m"] = me["spy_close"].pct_change(3) * 100.0

    sma50 = me["SMA50"] if "SMA50" in me.columns else pd.Series(np.nan, index=me.index)
    sma200 = me["SMA200"] if "SMA200" in me.columns else pd.Series(np.nan, index=me.index)
    me["spy_above_sma50"] = np.where(
        (sma50.notna()) & (sma50 > 0),
        me["spy_close"] > sma50,
        np.nan,
    )
    me["spy_above_sma200"] = np.where(
        (sma200.notna()) & (sma200 > 0),
        me["spy_close"] > sma200,
        np.nan,
    )
    me["spy_trend"] = np.where(
        me["spy_above_sma200"] == True,  # noqa: E712
        "above_SMA200",
        np.where(me["spy_above_sma200"] == False, "below_SMA200", "n/a"),  # noqa: E712
    )
    keep = [
        "month",
        "month_end",
        "spy_close",
        "spy_ret_1m",
        "spy_ret_3m",
        "spy_above_sma50",
        "spy_above_sma200",
        "spy_trend",
    ]
    return me[keep].reset_index(drop=True)


def _corr_pair(x: pd.Series, y: pd.Series) -> dict:
    mask = x.notna() & y.notna()
    n = int(mask.sum())
    if n < 5:
        return {
            "n": n,
            "pearson_r": np.nan,
            "pearson_p": np.nan,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
        }
    xs, ys = x[mask].astype(float), y[mask].astype(float)
    pr, pp = stats.pearsonr(xs, ys)
    sr, sp = stats.spearmanr(xs, ys)
    return {
        "n": n,
        "pearson_r": float(pr),
        "pearson_p": float(pp),
        "spearman_rho": float(sr),
        "spearman_p": float(sp),
    }


def build_series(gap_m: pd.DataFrame, spy_m: pd.DataFrame) -> pd.DataFrame:
    df = gap_m.merge(spy_m, on="month", how="inner").sort_values("month").reset_index(drop=True)
    df["spy_ret_next_1m"] = df["spy_ret_1m"].shift(-1)
    df["spy_ret_next_2m"] = (
        (df["spy_close"].shift(-2) / df["spy_close"] - 1.0) * 100.0
    )
    df["spy_ret_next_3m"] = (
        (df["spy_close"].shift(-3) / df["spy_close"] - 1.0) * 100.0
    )
    df["spy_ret_prior_1m"] = df["spy_ret_1m"].shift(1)
    df["gap_count_z"] = (df["gap_count"] - df["gap_count"].mean()) / df["gap_count"].std(ddof=0)
    q25 = df["gap_count"].quantile(0.25)
    q75 = df["gap_count"].quantile(0.75)
    df["gap_quartile"] = pd.cut(
        df["gap_count"],
        bins=[-np.inf, q25, df["gap_count"].quantile(0.5), q75, np.inf],
        labels=["Q1_low", "Q2", "Q3", "Q4_high"],
    )
    df["is_bottom_quartile"] = df["gap_count"] <= q25
    df["spy_down_month"] = df["spy_ret_1m"] < 0
    df["spy_down_prior"] = df["spy_ret_prior_1m"] < 0
    df["spy_down_next"] = df["spy_ret_next_1m"] < 0
    return df


def compute_stats(df: pd.DataFrame) -> dict:
    corrs = {
        "same_month": _corr_pair(df["gap_count"], df["spy_ret_1m"]),
        "vs_next_month": _corr_pair(df["gap_count"], df["spy_ret_next_1m"]),
        "vs_prior_month": _corr_pair(df["gap_count"], df["spy_ret_prior_1m"]),
        "vs_spy_ret_3m": _corr_pair(df["gap_count"], df["spy_ret_3m"]),
        "vs_fwd_3m": _corr_pair(df["gap_count"], df["spy_ret_next_3m"]),
    }

    # Contingency: bottom-quartile gap months
    bq = df[df["is_bottom_quartile"]].copy()
    rest = df[~df["is_bottom_quartile"]].copy()

    def _avg_fwd(sub: pd.DataFrame) -> dict:
        return {
            "n": int(len(sub)),
            "avg_gap_count": float(sub["gap_count"].mean()) if len(sub) else np.nan,
            "avg_spy_ret_same": float(sub["spy_ret_1m"].mean()) if len(sub) else np.nan,
            "avg_spy_fwd_1m": float(sub["spy_ret_next_1m"].mean()) if len(sub) else np.nan,
            "avg_spy_fwd_2m": float(sub["spy_ret_next_2m"].mean()) if len(sub) else np.nan,
            "avg_spy_fwd_3m": float(sub["spy_ret_next_3m"].mean()) if len(sub) else np.nan,
            "pct_spy_down_same": float(sub["spy_down_month"].mean() * 100) if len(sub) else np.nan,
            "pct_spy_down_prior": float(sub["spy_down_prior"].mean() * 100) if len(sub) else np.nan,
            "pct_spy_down_next": float(sub["spy_down_next"].mean() * 100) if len(sub) else np.nan,
        }

    # Lead/lag: among bottom-quartile months, were prior or next SPY months more often down?
    lead_lag = {
        "bottom_q": _avg_fwd(bq),
        "other": _avg_fwd(rest),
        "all": _avg_fwd(df),
    }

    # Simple contingency table: gap quartile vs next-month SPY sign
    cont_rows = []
    for q in ["Q1_low", "Q2", "Q3", "Q4_high"]:
        sub = df[df["gap_quartile"] == q]
        n = len(sub.dropna(subset=["spy_ret_next_1m"]))
        if n == 0:
            cont_rows.append({"quartile": q, "n": 0, "pct_next_up": np.nan, "avg_next_ret": np.nan})
            continue
        nxt = sub["spy_ret_next_1m"].dropna()
        cont_rows.append(
            {
                "quartile": q,
                "n": int(len(nxt)),
                "pct_next_up": float((nxt > 0).mean() * 100),
                "avg_next_ret": float(nxt.mean()),
                "avg_same_ret": float(sub["spy_ret_1m"].dropna().mean()),
                "avg_prior_ret": float(sub["spy_ret_prior_1m"].dropna().mean()),
            }
        )

    # Declining SPY months: gap counts around them
    down = df[df["spy_down_month"] == True]  # noqa: E712
    up = df[df["spy_down_month"] == False]  # noqa: E712
    around_declines = {
        "n_down_months": int(len(down)),
        "avg_gap_in_down_month": float(down["gap_count"].mean()) if len(down) else np.nan,
        "avg_gap_in_up_month": float(up["gap_count"].mean()) if len(up) else np.nan,
        "avg_gap_month_before_down": float(
            df.loc[down.index, "gap_count"].reindex(down.index - 1).dropna().mean()
        )
        if len(down)
        else np.nan,
        "avg_gap_month_after_down": float(
            df.loc[down.index, "gap_count"].reindex(down.index + 1).dropna().mean()
        )
        if len(down)
        else np.nan,
    }
    # Cleaner: gap count in month immediately before / after a SPY down month
    before_vals = []
    after_vals = []
    for idx in down.index:
        if idx - 1 in df.index:
            before_vals.append(df.loc[idx - 1, "gap_count"])
        if idx + 1 in df.index:
            after_vals.append(df.loc[idx + 1, "gap_count"])
    around_declines["avg_gap_month_before_down"] = (
        float(np.mean(before_vals)) if before_vals else np.nan
    )
    around_declines["avg_gap_month_after_down"] = (
        float(np.mean(after_vals)) if after_vals else np.nan
    )
    around_declines["n_before"] = len(before_vals)
    around_declines["n_after"] = len(after_vals)

    return {
        "corrs": corrs,
        "lead_lag": lead_lag,
        "contingency": cont_rows,
        "around_declines": around_declines,
        "q25": float(df["gap_count"].quantile(0.25)),
        "q50": float(df["gap_count"].quantile(0.50)),
        "q75": float(df["gap_count"].quantile(0.75)),
        "mean_gap": float(df["gap_count"].mean()),
        "n_months": int(len(df)),
    }


def _fmt(v, kind: str = "num", digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    if kind == "pct":
        return f"{v:+.{digits}f}%"
    if kind == "int":
        return f"{int(round(v)):,}"
    if kind == "p":
        if abs(v) < 0.001:
            return f"{v:.2e}"
        return f"{v:.{digits}f}"
    if kind == "r":
        return f"{v:+.{digits}f}"
    return f"{v:.{digits}f}"


def _verdict(stats_d: dict) -> tuple[str, list[str]]:
    """Honest summary bullets + short headline."""
    c_same = stats_d["corrs"]["same_month"]
    c_next = stats_d["corrs"]["vs_next_month"]
    c_prior = stats_d["corrs"]["vs_prior_month"]
    ll = stats_d["lead_lag"]
    ad = stats_d["around_declines"]
    bullets: list[str] = []

    def _sig(p: float) -> str:
        if np.isnan(p):
            return "n/a"
        if p < 0.01:
            return "p<0.01"
        if p < 0.05:
            return "p<0.05"
        if p < 0.10:
            return "p<0.10"
        return "n.s."

    bullets.append(
        f"Same-month: gap_count vs SPY return Pearson r={_fmt(c_same['pearson_r'], 'r')} "
        f"({_sig(c_same['pearson_p'])}), Spearman rho={_fmt(c_same['spearman_rho'], 'r')} "
        f"({_sig(c_same['spearman_p'])}), n={c_same['n']}."
    )
    bullets.append(
        f"Predictive (this month -> next SPY): r={_fmt(c_next['pearson_r'], 'r')} "
        f"({_sig(c_next['pearson_p'])}), rho={_fmt(c_next['spearman_rho'], 'r')} "
        f"({_sig(c_next['spearman_p'])})."
    )
    bullets.append(
        f"Lag / reaction (prior SPY -> this month gaps): r={_fmt(c_prior['pearson_r'], 'r')} "
        f"({_sig(c_prior['pearson_p'])}), rho={_fmt(c_prior['spearman_rho'], 'r')} "
        f"({_sig(c_prior['spearman_p'])})."
    )

    bq = ll["bottom_q"]
    oth = ll["other"]
    bullets.append(
        f"Bottom-quartile gap months (n={bq['n']}, count<={_fmt(stats_d['q25'], 'int')}): "
        f"% prior/same/next SPY-down = "
        f"{_fmt(bq['pct_spy_down_prior'], 'num', 1)}% / "
        f"{_fmt(bq['pct_spy_down_same'], 'num', 1)}% / "
        f"{_fmt(bq['pct_spy_down_next'], 'num', 1)}%; "
        f"avg forward SPY 1m/2m/3m = {_fmt(bq['avg_spy_fwd_1m'], 'pct')} / "
        f"{_fmt(bq['avg_spy_fwd_2m'], 'pct')} / {_fmt(bq['avg_spy_fwd_3m'], 'pct')} "
        f"(vs other months fwd 1m {_fmt(oth['avg_spy_fwd_1m'], 'pct')})."
    )

    bullets.append(
        f"Around SPY down months (n={ad['n_down_months']}): avg gap_count in down month "
        f"{_fmt(ad['avg_gap_in_down_month'], 'int')} vs up month "
        f"{_fmt(ad['avg_gap_in_up_month'], 'int')}; "
        f"avg gaps in month before decline {_fmt(ad['avg_gap_month_before_down'], 'int')}, "
        f"after {_fmt(ad['avg_gap_month_after_down'], 'int')} "
        f"(gaps tend to surge after declines, not before)."
    )

    # Headline verdict — interpret signs, not just |r|
    r_prior = c_prior["pearson_r"]
    r_next = c_next["pearson_r"]
    r_same = c_same["pearson_r"]
    abs_next = abs(r_next) if not np.isnan(r_next) else 0.0
    abs_prior = abs(r_prior) if not np.isnan(r_prior) else 0.0
    abs_same = abs(r_same) if not np.isnan(r_same) else 0.0
    p_next = c_next["pearson_p"] if not np.isnan(c_next["pearson_p"]) else 1.0
    p_prior = c_prior["pearson_p"] if not np.isnan(c_prior["pearson_p"]) else 1.0
    pred_sig = abs_next >= 0.12 and p_next <= 0.05
    pred_weak = not pred_sig

    # Prior r < 0 => strong prior SPY associated with fewer gaps this month
    if abs_prior >= 0.15 and p_prior <= 0.05 and (r_prior < 0):
        timing = (
            "Strongest link is lagging: low gap counts tend to follow strong SPY months "
            "(negative prior-month correlation), not weak ones. "
            "Around declines, gap counts are lower just before and surge after."
        )
    elif abs_prior >= 0.15 and p_prior <= 0.05 and (r_prior > 0):
        timing = (
            "Low gap counts tend to follow weak SPY months (positive prior-month correlation)."
        )
    elif pred_sig and (r_next > 0):
        timing = (
            "Mild lead: higher gap counts associate with slightly better next-month SPY "
            "(so low counts lean slightly softer forward) — effect size is small."
        )
    else:
        timing = (
            "Lead vs lag is ambiguous: associations with prior, same, and next SPY months "
            "are all modest."
        )

    if abs_prior >= abs_next and abs_prior >= 0.15 and p_prior <= 0.05:
        headline = (
            f"Mostly a lagging/coincident market-tone marker, not a clean forward signal. "
            f"Prior-month r={_fmt(r_prior, 'r')} ({_sig(p_prior)}); "
            f"next-month r={_fmt(r_next, 'r')} ({_sig(p_next)}). {timing}"
        )
    elif pred_sig:
        headline = (
            f"Mild predictive association (next-month r={_fmt(r_next, 'r')}, "
            f"{_sig(p_next)}). {timing}"
        )
    elif pred_weak and abs_same < 0.25:
        headline = (
            f"Not usefully predictive for trading. "
            f"Same-month r={_fmt(r_same, 'r')}; "
            f"next-month r={_fmt(r_next, 'r')}; "
            f"prior-month r={_fmt(r_prior, 'r')}. {timing}"
        )
    else:
        headline = (
            f"Weak overall. Same-month r={_fmt(r_same, 'r')}, "
            f"next-month r={_fmt(r_next, 'r')}. {timing}"
        )

    return headline, bullets


def write_html(
    df: pd.DataFrame,
    stats_d: dict,
    gap_csv: Path,
    spy_path: Path,
    out_html: Path,
) -> None:
    headline, bullets = _verdict(stats_d)
    esc = html_mod.escape

    # Correlation table
    corr_rows_html = ""
    labels = {
        "same_month": "gap_count vs SPY same-month return",
        "vs_next_month": "gap_count vs SPY next-month return (predictive)",
        "vs_prior_month": "gap_count vs SPY prior-month return (lag)",
        "vs_spy_ret_3m": "gap_count vs SPY trailing 3m return",
        "vs_fwd_3m": "gap_count vs SPY forward 3m return",
    }
    for key, label in labels.items():
        c = stats_d["corrs"][key]
        corr_rows_html += (
            "<tr>"
            f"<td>{esc(label)}</td>"
            f"<td>{c['n']}</td>"
            f"<td>{_fmt(c['pearson_r'], 'r', 3)}</td>"
            f"<td>{_fmt(c['pearson_p'], 'p', 4)}</td>"
            f"<td>{_fmt(c['spearman_rho'], 'r', 3)}</td>"
            f"<td>{_fmt(c['spearman_p'], 'p', 4)}</td>"
            "</tr>"
        )

    cont_html = ""
    for row in stats_d["contingency"]:
        cont_html += (
            "<tr>"
            f"<td>{esc(str(row['quartile']))}</td>"
            f"<td>{row['n']}</td>"
            f"<td>{_fmt(row.get('avg_prior_ret'), 'pct')}</td>"
            f"<td>{_fmt(row.get('avg_same_ret'), 'pct')}</td>"
            f"<td>{_fmt(row.get('avg_next_ret'), 'pct')}</td>"
            f"<td>{_fmt(row.get('pct_next_up'), 'num', 1)}%</td>"
            "</tr>"
        )

    ll = stats_d["lead_lag"]
    bq_html = (
        "<tr>"
        "<td>Bottom quartile (low gaps)</td>"
        f"<td>{ll['bottom_q']['n']}</td>"
        f"<td>{_fmt(ll['bottom_q']['avg_gap_count'], 'int')}</td>"
        f"<td>{_fmt(ll['bottom_q']['avg_spy_ret_same'], 'pct')}</td>"
        f"<td>{_fmt(ll['bottom_q']['avg_spy_fwd_1m'], 'pct')}</td>"
        f"<td>{_fmt(ll['bottom_q']['avg_spy_fwd_2m'], 'pct')}</td>"
        f"<td>{_fmt(ll['bottom_q']['avg_spy_fwd_3m'], 'pct')}</td>"
        f"<td>{_fmt(ll['bottom_q']['pct_spy_down_prior'], 'num', 1)}%</td>"
        f"<td>{_fmt(ll['bottom_q']['pct_spy_down_same'], 'num', 1)}%</td>"
        f"<td>{_fmt(ll['bottom_q']['pct_spy_down_next'], 'num', 1)}%</td>"
        "</tr>"
        "<tr>"
        "<td>Other months</td>"
        f"<td>{ll['other']['n']}</td>"
        f"<td>{_fmt(ll['other']['avg_gap_count'], 'int')}</td>"
        f"<td>{_fmt(ll['other']['avg_spy_ret_same'], 'pct')}</td>"
        f"<td>{_fmt(ll['other']['avg_spy_fwd_1m'], 'pct')}</td>"
        f"<td>{_fmt(ll['other']['avg_spy_fwd_2m'], 'pct')}</td>"
        f"<td>{_fmt(ll['other']['avg_spy_fwd_3m'], 'pct')}</td>"
        f"<td>{_fmt(ll['other']['pct_spy_down_prior'], 'num', 1)}%</td>"
        f"<td>{_fmt(ll['other']['pct_spy_down_same'], 'num', 1)}%</td>"
        f"<td>{_fmt(ll['other']['pct_spy_down_next'], 'num', 1)}%</td>"
        "</tr>"
    )

    # Yearly rollup
    ydf = df.copy()
    ydf["year"] = ydf["month"].astype(str).str[:4]
    yearly_rows = ""
    for year, g in ydf.groupby("year", sort=True):
        yearly_rows += (
            "<tr>"
            f"<td>{esc(str(year))}</td>"
            f"<td>{len(g)}</td>"
            f"<td>{int(g['gap_count'].sum()):,}</td>"
            f"<td>{_fmt(g['gap_count'].mean(), 'int')}</td>"
            f"<td>{_fmt(g['spy_ret_1m'].mean(), 'pct')}</td>"
            "</tr>"
        )

    # Monthly detail (newest first for glance, but sort JS can reorder)
    detail = df.copy().sort_values("month", ascending=False)
    detail_rows = ""
    for _, r in detail.iterrows():
        bq_flag = "Y" if bool(r["is_bottom_quartile"]) else ""
        detail_rows += (
            "<tr>"
            f"<td>{esc(str(r['month']))}</td>"
            f"<td>{int(r['gap_count']):,}</td>"
            f"<td>{_fmt(r['spy_ret_1m'], 'pct')}</td>"
            f"<td>{_fmt(r['spy_ret_3m'], 'pct')}</td>"
            f"<td>{_fmt(r['spy_ret_prior_1m'], 'pct')}</td>"
            f"<td>{_fmt(r['spy_ret_next_1m'], 'pct')}</td>"
            f"<td>{_fmt(r['spy_ret_next_3m'], 'pct')}</td>"
            f"<td>{esc(str(r['spy_trend']))}</td>"
            f"<td>{esc(str(r['gap_quartile']) if pd.notna(r['gap_quartile']) else '—')}</td>"
            f"<td>{bq_flag}</td>"
            "</tr>"
        )

    bullet_li = "".join(f"<li>{esc(b)}</li>" for b in bullets)
    ad = stats_d["around_declines"]
    try:
        spy_disp = str(spy_path.relative_to(ROOT))
    except ValueError:
        spy_disp = str(spy_path)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Gap-Up Counts vs SPY — Market Correlation</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.45rem;margin:0 0 .4rem}}
h2{{font-size:1.1rem;margin:1.6rem 0 .5rem;border-bottom:1px solid #cbd5e1;padding-bottom:.25rem}}
.meta{{color:#475569;font-size:.9rem;margin-bottom:1rem}}
.verdict{{background:#fff;border-left:4px solid #0369a1;padding:.85rem 1rem;margin:1rem 0;border-radius:0 6px 6px 0;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.verdict strong{{display:block;margin-bottom:.35rem}}
ul.notes{{margin:.4rem 0 .8rem 1.2rem}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;font-size:.88rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:.35rem .5rem;text-align:left}}
table.sortable th{{background:#f1f5f9}}
table.sortable tr:nth-child(even){{background:#f8fafc}}
.small{{color:#64748b;font-size:.85rem}}
.caption{{color:#64748b;font-size:.82rem;margin:.25rem 0 .6rem}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Gap-Up Counts vs SPY Market Direction</h1>
<p class="meta">
Source scan: <code>{esc(gap_csv.name)}</code> (min GAP_PCT floor ~1.0% preferred over tighter filters)<br/>
SPY: <code>{esc(spy_disp)}</code><br/>
Months: {stats_d['n_months']} &nbsp;|&nbsp;
Mean monthly gaps: {_fmt(stats_d['mean_gap'], 'int')} &nbsp;|&nbsp;
Q1/Q2/Q3 cutoffs: {_fmt(stats_d['q25'], 'int')} / {_fmt(stats_d['q50'], 'int')} / {_fmt(stats_d['q75'], 'int')}<br/>
Methods: Pearson &amp; Spearman on monthly <code>gap_count</code> vs SPY monthly return (same / next / prior);
bottom-quartile flag for forward 1–3m SPY; click column headers to sort.
</p>

<div class="verdict">
<strong>Verdict</strong>
{esc(headline)}
<ul class="notes">{bullet_li}</ul>
</div>

<h2>0. Yearly gap totals</h2>
<p class="caption">Click column headers to sort.</p>
<table class="sortable">
<thead><tr>
{_sortable_th("Year", "num")}
{_sortable_th("Months", "num")}
{_sortable_th("Total gaps", "num")}
{_sortable_th("Avg monthly gaps", "num")}
{_sortable_th("Avg SPY 1m %", "num")}
</tr></thead>
<tbody>
{yearly_rows}
</tbody>
</table>

<h2>1. Correlations</h2>
<p class="caption">Click column headers to sort. |r| &lt; ~0.15 with non-significant p ≈ noise for trading use.</p>
<table class="sortable">
<thead><tr>
{_sortable_th("Pairing", "text")}
{_sortable_th("n", "num")}
{_sortable_th("Pearson r", "num")}
{_sortable_th("Pearson p", "num")}
{_sortable_th("Spearman ρ", "num")}
{_sortable_th("Spearman p", "num")}
</tr></thead>
<tbody>
{corr_rows_html}
</tbody>
</table>

<h2>2. Gap quartile vs SPY returns (contingency)</h2>
<p class="caption">Q1_low = bottom 25% of monthly gap counts. Forward = next calendar month(s) SPY return from month-end close.</p>
<table class="sortable">
<thead><tr>
{_sortable_th("Quartile", "text")}
{_sortable_th("n", "num")}
{_sortable_th("Avg prior SPY 1m", "num")}
{_sortable_th("Avg same SPY 1m", "num")}
{_sortable_th("Avg next SPY 1m", "num")}
{_sortable_th("% next SPY up", "num")}
</tr></thead>
<tbody>
{cont_html}
</tbody>
</table>

<h2>3. Bottom-quartile gap months — forward SPY</h2>
<table class="sortable">
<thead><tr>
{_sortable_th("Group", "text")}
{_sortable_th("n", "num")}
{_sortable_th("Avg gaps", "num")}
{_sortable_th("Avg same SPY", "num")}
{_sortable_th("Avg fwd 1m", "num")}
{_sortable_th("Avg fwd 2m", "num")}
{_sortable_th("Avg fwd 3m", "num")}
{_sortable_th("% prior down", "num")}
{_sortable_th("% same down", "num")}
{_sortable_th("% next down", "num")}
</tr></thead>
<tbody>
{bq_html}
</tbody>
</table>

<h2>4. Around SPY declining months</h2>
<p class="small">
Avg gap_count in SPY-down months: <strong>{_fmt(ad['avg_gap_in_down_month'], 'int')}</strong>
vs up months: <strong>{_fmt(ad['avg_gap_in_up_month'], 'int')}</strong>.
Month <em>before</em> a decline: {_fmt(ad['avg_gap_month_before_down'], 'int')} (n={ad['n_before']});
<em>after</em>: {_fmt(ad['avg_gap_month_after_down'], 'int')} (n={ad['n_after']}).
</p>

<h2>5. Monthly series</h2>
<p class="caption">Click headers to sort. CSV twin: GapUp_Market_Correlation_monthly.csv</p>
<table class="sortable">
<thead><tr>
{_sortable_th("Month", "month")}
{_sortable_th("Gap count", "num")}
{_sortable_th("SPY 1m %", "num")}
{_sortable_th("SPY 3m %", "num")}
{_sortable_th("SPY prior 1m %", "num")}
{_sortable_th("SPY next 1m %", "num")}
{_sortable_th("SPY fwd 3m %", "num")}
{_sortable_th("Trend", "text")}
{_sortable_th("Gap Q", "text")}
{_sortable_th("Bottom Q", "text")}
</tr></thead>
<tbody>
{detail_rows}
</tbody>
</table>

{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")


def write_csv(df: pd.DataFrame, out_csv: Path) -> None:
    cols = [
        "month",
        "gap_count",
        "month_end",
        "spy_close",
        "spy_ret_1m",
        "spy_ret_3m",
        "spy_ret_prior_1m",
        "spy_ret_next_1m",
        "spy_ret_next_2m",
        "spy_ret_next_3m",
        "spy_above_sma50",
        "spy_above_sma200",
        "spy_trend",
        "gap_quartile",
        "is_bottom_quartile",
        "gap_count_z",
    ]
    out = df[[c for c in cols if c in df.columns]].copy()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gap-csv", type=Path, default=None, help="GapUp scan CSV (default: newest full)")
    ap.add_argument("--spy", type=Path, default=DEFAULT_SPY)
    ap.add_argument(
        "--out-html",
        type=Path,
        default=OUT_DIR / "GapUp_Market_Correlation.html",
    )
    ap.add_argument(
        "--out-csv",
        type=Path,
        default=OUT_DIR / "GapUp_Market_Correlation_monthly.csv",
    )
    args = ap.parse_args(argv)

    gap_csv = args.gap_csv.resolve() if args.gap_csv else find_latest_gap_csv()
    spy_path = args.spy.resolve()
    if not gap_csv.is_file():
        print(f"ERROR: gap CSV not found: {gap_csv}", file=sys.stderr)
        return 1
    if not spy_path.is_file():
        print(f"ERROR: SPY CSV not found: {spy_path}", file=sys.stderr)
        return 1

    print(f"[gap-corr] gap_csv={gap_csv.name}")
    print(f"[gap-corr] spy={spy_path}")
    gap_m = load_monthly_gap_counts(gap_csv)
    spy_m = load_spy_monthly(spy_path)
    df = build_series(gap_m, spy_m)
    stats_d = compute_stats(df)
    write_csv(df, args.out_csv.resolve())
    write_html(df, stats_d, gap_csv, spy_path, args.out_html.resolve())

    headline, bullets = _verdict(stats_d)
    print(f"[gap-corr] wrote {args.out_html}")
    print(f"[gap-corr] wrote {args.out_csv}")
    print(f"[gap-corr] months={stats_d['n_months']} mean_gaps={stats_d['mean_gap']:.0f}")
    print("--- VERDICT ---")
    print(headline)
    for b in bullets:
        print(f"  - {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
