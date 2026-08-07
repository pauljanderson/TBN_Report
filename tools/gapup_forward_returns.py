#!/usr/bin/env python3
"""Gap-up size vs forward returns — bucketed ROR / correlation report.

Reads newest full drive/GapUp_Scan_*.csv that has RET_C_* / RET_O_* columns
(prefer ~≥1% floor used by market-correlation scan).

Writes:
  drive/paul_experiments/GapUp_Forward_Returns.html
  drive/paul_experiments/GapUp_Forward_Returns_summary.csv

Annualization (documented in HTML):
  mean simple return r (decimal) over N trading days:
    Ann = (1 + r)^(252/N) - 1
  Same formula applied to median return for Ann_med.

Usage:
  python tools/gapup_forward_returns.py
  python tools/gapup_forward_returns.py --gap-csv drive/GapUp_Scan_YYMMDDHHMMSS.csv
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments"

HORIZONS = (5, 10, 15, 20)
TRADING_DAYS_YEAR = 252

# Discrete buckets (left-inclusive, right-exclusive except last)
BUCKET_EDGES = [
    (1.0, 2.0, "[1–2%)"),
    (2.0, 3.0, "[2–3%)"),
    (3.0, 5.0, "[3–5%)"),
    (5.0, 10.0, "[5–10%)"),
    (10.0, np.inf, "≥10%"),
]
CUM_THRESHOLDS = (1.0, 2.0, 3.0, 5.0, 10.0)

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


def _has_fwd_rets(path: Path) -> bool:
    try:
        cols = set(pd.read_csv(path, nrows=0).columns)
        return any(c.startswith("RET_C_") for c in cols) and any(
            c.startswith("RET_O_") for c in cols
        )
    except Exception:
        return False


def find_latest_gap_csv_with_fwd(
    drive: Path = DRIVE, prefer_min_gap: float = 1.0
) -> Path:
    """Newest full GapUp_Scan_*.csv with forward RET_* cols (prefer ~≥1% floor)."""
    candidates: list[Path] = []
    for p in drive.glob("GapUp_Scan_*.csv"):
        name = p.name.lower()
        if "smoke" in name:
            continue
        if not _has_fwd_rets(p):
            continue
        candidates.append(p)
    if not candidates:
        raise FileNotFoundError(
            f"No full GapUp_Scan_*.csv with RET_C_*/RET_O_* under {drive}. "
            "Run: python tools/scan_gap_ups.py --min-gap-pct 1.0 --horizons 5,10,15,20"
        )

    scored: list[tuple[float, float, Path]] = []
    for p in candidates:
        gmin = _sample_min_gap_pct(p)
        prefer_rank = 0.0 if (not np.isnan(gmin) and abs(gmin - prefer_min_gap) <= 0.15) else 1.0
        scored.append((prefer_rank, -p.stat().st_mtime, p))
    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0][2]


def annualize(mean_pct: float, n_days: int) -> float:
    """Annualize mean simple return in percent over N trading days."""
    if n_days <= 0 or mean_pct is None or (isinstance(mean_pct, float) and np.isnan(mean_pct)):
        return float("nan")
    r = mean_pct / 100.0
    if r <= -1.0:
        return float("nan")
    return (float((1.0 + r) ** (TRADING_DAYS_YEAR / n_days)) - 1.0) * 100.0


def _bucket_label(gap: float) -> str:
    for lo, hi, lab in BUCKET_EDGES:
        if lo <= gap < hi:
            return lab
    return "≥10%"


def load_gap_fwd(gap_csv: Path) -> pd.DataFrame:
    need = ["SYMBOL", "GAP_DATE", "GAP_PCT"]
    ret_cols = [f"RET_C_{n}D" for n in HORIZONS] + [f"RET_O_{n}D" for n in HORIZONS]
    header = list(pd.read_csv(gap_csv, nrows=0).columns)
    usecols = [c for c in need + ret_cols if c in header]
    missing = [c for c in ret_cols if c not in header]
    if missing:
        raise ValueError(f"{gap_csv.name} missing forward columns: {missing}")
    df = pd.read_csv(gap_csv, usecols=usecols)
    df["GAP_PCT"] = pd.to_numeric(df["GAP_PCT"], errors="coerce")
    for c in ret_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["GAP_PCT"])
    df["bucket"] = df["GAP_PCT"].map(_bucket_label)
    # Preserve bucket order
    order = [lab for _, _, lab in BUCKET_EDGES]
    df["bucket"] = pd.Categorical(df["bucket"], categories=order, ordered=True)
    return df


def _cell_stats(s: pd.Series, n_days: int) -> dict:
    s = s.dropna()
    n = int(len(s))
    if n == 0:
        return {
            "n": 0,
            "mean_pct": np.nan,
            "median_pct": np.nan,
            "std_pct": np.nan,
            "win_rate": np.nan,
            "ann_mean_pct": np.nan,
            "ann_median_pct": np.nan,
            "ann_over_std": np.nan,
        }
    mean_pct = float(s.mean())
    med_pct = float(s.median())
    std_pct = float(s.std(ddof=1)) if n > 1 else float("nan")
    win = float((s > 0).mean() * 100.0)
    ann_m = annualize(mean_pct, n_days)
    ann_med = annualize(med_pct, n_days)
    # Risk-aware: ann mean / std of holding-period returns (not ann std)
    ann_over_std = (
        ann_m / std_pct if (std_pct and not np.isnan(std_pct) and std_pct > 1e-12) else np.nan
    )
    return {
        "n": n,
        "mean_pct": mean_pct,
        "median_pct": med_pct,
        "std_pct": std_pct,
        "win_rate": win,
        "ann_mean_pct": ann_m,
        "ann_median_pct": ann_med,
        "ann_over_std": ann_over_std,
    }


def _pearson(x: pd.Series, y: pd.Series) -> dict:
    m = pd.concat([x, y], axis=1).dropna()
    if len(m) < 3:
        return {"n": int(len(m)), "r": np.nan, "p": np.nan}
    r, p = stats.pearsonr(m.iloc[:, 0], m.iloc[:, 1])
    return {"n": int(len(m)), "r": float(r), "p": float(p)}


def build_summary(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Return (bucket_summary, cum_summary, corr_summary, meta)."""
    rows: list[dict] = []
    scopes = [("bucket", lab) for _, _, lab in BUCKET_EDGES]
    scopes.append(("all", "All ≥1%"))

    for scope_kind, scope_lab in scopes:
        if scope_kind == "all":
            sub = df
        else:
            sub = df[df["bucket"] == scope_lab]
        for side, prefix in (("close", "RET_C"), ("open", "RET_O")):
            for n in HORIZONS:
                col = f"{prefix}_{n}D"
                st = _cell_stats(sub[col], n)
                rows.append(
                    {
                        "scope": scope_lab,
                        "scope_kind": scope_kind,
                        "side": side,
                        "horizon_d": n,
                        "ret_col": col,
                        **st,
                    }
                )

    # Cumulative thresholds
    cum_rows: list[dict] = []
    for thr in CUM_THRESHOLDS:
        sub = df[df["GAP_PCT"] >= thr]
        for side, prefix in (("close", "RET_C"), ("open", "RET_O")):
            for n in HORIZONS:
                col = f"{prefix}_{n}D"
                st = _cell_stats(sub[col], n)
                cum_rows.append(
                    {
                        "scope": f"≥{thr:g}%",
                        "scope_kind": "cumulative",
                        "threshold": thr,
                        "side": side,
                        "horizon_d": n,
                        "ret_col": col,
                        **st,
                    }
                )

    bucket_df = pd.DataFrame(rows)
    cum_df = pd.DataFrame(cum_rows)

    # Correlations: overall + within bucket
    corr_rows: list[dict] = []
    for side, prefix in (("close", "RET_C"), ("open", "RET_O")):
        for n in HORIZONS:
            col = f"{prefix}_{n}D"
            ov = _pearson(df["GAP_PCT"], df[col])
            corr_rows.append(
                {
                    "scope": "All ≥1%",
                    "side": side,
                    "horizon_d": n,
                    "ret_col": col,
                    **ov,
                }
            )
            for _, _, lab in BUCKET_EDGES:
                sub = df[df["bucket"] == lab]
                c = _pearson(sub["GAP_PCT"], sub[col])
                corr_rows.append(
                    {
                        "scope": lab,
                        "side": side,
                        "horizon_d": n,
                        "ret_col": col,
                        **c,
                    }
                )
    corr_df = pd.DataFrame(corr_rows)

    # Best cells (close side primary for trading-from-close narrative)
    close_b = bucket_df[(bucket_df["side"] == "close") & (bucket_df["scope_kind"] == "bucket")]
    best_ann = close_b.loc[close_b["ann_mean_pct"].idxmax()] if len(close_b) else None
    # Risk-aware among cells with n>=200
    ra = close_b[close_b["n"] >= 200].copy()
    best_ra = ra.loc[ra["ann_over_std"].idxmax()] if len(ra) and ra["ann_over_std"].notna().any() else None
    best_win = close_b.loc[close_b["win_rate"].idxmax()] if len(close_b) else None

    # Overall correlations strength
    overall_corr = corr_df[corr_df["scope"] == "All ≥1%"].copy()
    strongest = (
        overall_corr.loc[overall_corr["r"].abs().idxmax()]
        if len(overall_corr) and overall_corr["r"].notna().any()
        else None
    )

    meta = {
        "n_events": int(len(df)),
        "date_min": str(pd.to_datetime(df["GAP_DATE"], errors="coerce").min().date())
        if "GAP_DATE" in df.columns
        else "",
        "date_max": str(pd.to_datetime(df["GAP_DATE"], errors="coerce").max().date())
        if "GAP_DATE" in df.columns
        else "",
        "gap_min": float(df["GAP_PCT"].min()),
        "gap_max": float(df["GAP_PCT"].max()),
        "best_ann": best_ann.to_dict() if best_ann is not None else {},
        "best_ra": best_ra.to_dict() if best_ra is not None else {},
        "best_win": best_win.to_dict() if best_win is not None else {},
        "strongest_corr": strongest.to_dict() if strongest is not None else {},
    }
    return bucket_df, cum_df, corr_df, meta


def _fmt(v, kind: str = "num", digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if kind == "int":
        return f"{int(round(v)):,}"
    if kind == "pct":
        return f"{v:.{digits}f}%"
    if kind == "r":
        return f"{v:.{digits}f}"
    if kind == "p":
        if v < 0.0001:
            return "<0.0001"
        return f"{v:.{digits}f}"
    return f"{v:.{digits}f}"


def _sig(p: float) -> str:
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "n/a"
    if p < 0.001:
        return "p<0.001"
    if p < 0.01:
        return "p<0.01"
    if p < 0.05:
        return "p<0.05"
    return f"p={p:.2f} (n.s.)"


def _verdict(meta: dict, corr_df: pd.DataFrame) -> tuple[str, list[str]]:
    bullets: list[str] = []
    ba = meta.get("best_ann") or {}
    bra = meta.get("best_ra") or {}
    bw = meta.get("best_win") or {}
    sc = meta.get("strongest_corr") or {}

    if ba:
        bullets.append(
            f"Best mean Ann_ROR (close, discrete buckets): {ba.get('scope')} × {ba.get('horizon_d')}d "
            f"— Ann_mean={_fmt(ba.get('ann_mean_pct'), 'pct')} "
            f"(mean hold {_fmt(ba.get('mean_pct'), 'pct')}, win {_fmt(ba.get('win_rate'), 'num', 1)}%, "
            f"n={_fmt(ba.get('n'), 'int')})."
        )
    if bra:
        bullets.append(
            f"Best risk-aware Ann/std (close, n≥200): {bra.get('scope')} × {bra.get('horizon_d')}d "
            f"— Ann/std={_fmt(bra.get('ann_over_std'), 'num', 2)}, "
            f"Ann={_fmt(bra.get('ann_mean_pct'), 'pct')}, win {_fmt(bra.get('win_rate'), 'num', 1)}%."
        )
    if bw:
        bullets.append(
            f"Highest win rate (close buckets): {bw.get('scope')} × {bw.get('horizon_d')}d "
            f"= {_fmt(bw.get('win_rate'), 'num', 1)}% (mean {_fmt(bw.get('mean_pct'), 'pct')})."
        )

    # Overall corr magnitude
    ov = corr_df[corr_df["scope"] == "All ≥1%"]
    max_abs = float(ov["r"].abs().max()) if len(ov) and ov["r"].notna().any() else float("nan")
    if sc:
        bullets.append(
            f"Strongest overall Pearson |r|: GAP_PCT vs {sc.get('ret_col')} "
            f"r={_fmt(sc.get('r'), 'r', 3)} ({_sig(sc.get('p'))}, n={_fmt(sc.get('n'), 'int')})."
        )

    # Honest read
    if not np.isnan(max_abs) and max_abs < 0.05:
        corr_note = (
            "Gap size vs forward return correlation is effectively near zero (|r|<0.05) — "
            "bigger gaps do not reliably mean bigger forward moves."
        )
    elif not np.isnan(max_abs) and max_abs < 0.15:
        corr_note = (
            f"Gap size vs forward return shows only a weak linear link (max |r|≈{max_abs:.3f})."
        )
    else:
        corr_note = (
            f"Moderate linear association between gap size and forward return (max |r|≈{max_abs:.3f})."
        )

    if ba:
        headline = (
            f"Top Ann_ROR cell: {ba.get('scope')} @ {ba.get('horizon_d')}d close → "
            f"{_fmt(ba.get('ann_mean_pct'), 'pct')} annualized. {corr_note}"
        )
    else:
        headline = corr_note

    # Edge noise caveat
    bullets.append(
        "Caveat: annualizing short-horizon means amplifies noise; extreme ≥10% gaps are sparse "
        "and fat-tailed (penny/news names). Prefer win rate + Ann/std alongside raw Ann."
    )
    return headline, bullets


def write_html(
    gap_csv: Path,
    bucket_df: pd.DataFrame,
    cum_df: pd.DataFrame,
    corr_df: pd.DataFrame,
    meta: dict,
    out_html: Path,
) -> None:
    headline, bullets = _verdict(meta, corr_df)
    esc = html_mod.escape
    bullet_li = "".join(f"<li>{esc(b)}</li>" for b in bullets)

    # Close-side discrete buckets table (primary)
    close_b = bucket_df[
        (bucket_df["side"] == "close") & (bucket_df["scope_kind"].isin(["bucket", "all"]))
    ].copy()
    close_b = close_b.sort_values(["scope", "horizon_d"])

    open_b = bucket_df[
        (bucket_df["side"] == "open") & (bucket_df["scope_kind"].isin(["bucket", "all"]))
    ].copy()
    open_b = open_b.sort_values(["scope", "horizon_d"])

    cum_close = cum_df[cum_df["side"] == "close"].sort_values(["threshold", "horizon_d"])
    corr_show = corr_df.sort_values(["scope", "side", "horizon_d"])

    # Heat-style mini: pivot Ann for close buckets
    heat = close_b[close_b["scope_kind"] == "bucket"].pivot_table(
        index="scope", columns="horizon_d", values="ann_mean_pct", aggfunc="first"
    )
    heat_html = ""
    if len(heat):
        ths = _sortable_th("Bucket", "text") + "".join(
            _sortable_th(f"Ann {c}d", "num") for c in heat.columns
        )
        body = ""
        for idx, row in heat.iterrows():
            body += "<tr><td>" + esc(str(idx)) + "</td>"
            for c in heat.columns:
                body += f"<td>{_fmt(row[c], 'pct')}</td>"
            body += "</tr>"
        heat_html = f"""
<h2>2. Ann_ROR heat (close, discrete buckets)</h2>
<p class="caption">Click headers to sort. Values = annualized mean simple return.</p>
<table class="sortable"><thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table>
"""

    def detail_table(df: pd.DataFrame, title: str, caption: str) -> str:
        heads = "".join(
            [
                _sortable_th("Bucket / scope", "text"),
                _sortable_th("Horizon (d)", "num"),
                _sortable_th("N", "num"),
                _sortable_th("Mean %", "num"),
                _sortable_th("Median %", "num"),
                _sortable_th("Std %", "num"),
                _sortable_th("Win %", "num"),
                _sortable_th("Ann mean %", "num"),
                _sortable_th("Ann median %", "num"),
                _sortable_th("Ann/std", "num"),
            ]
        )
        # Fix digits for horizon as int-like
        rows = []
        for _, r in df.iterrows():
            rows.append(
                "<tr>"
                f"<td>{esc(str(r['scope']))}</td>"
                f"<td>{int(r['horizon_d'])}</td>"
                f"<td>{_fmt(r['n'], 'int')}</td>"
                f"<td>{_fmt(r['mean_pct'], 'pct')}</td>"
                f"<td>{_fmt(r['median_pct'], 'pct')}</td>"
                f"<td>{_fmt(r['std_pct'], 'pct')}</td>"
                f"<td>{_fmt(r['win_rate'], 'num', 1)}</td>"
                f"<td>{_fmt(r['ann_mean_pct'], 'pct')}</td>"
                f"<td>{_fmt(r['ann_median_pct'], 'pct')}</td>"
                f"<td>{_fmt(r['ann_over_std'], 'num', 2)}</td>"
                "</tr>"
            )
        return f"""
<h2>{esc(title)}</h2>
<p class="caption">{esc(caption)}</p>
<table class="sortable"><thead><tr>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody></table>
"""

    corr_heads = "".join(
        [
            _sortable_th("Scope", "text"),
            _sortable_th("Side", "text"),
            _sortable_th("Horizon (d)", "num"),
            _sortable_th("RET col", "text"),
            _sortable_th("N", "num"),
            _sortable_th("Pearson r", "num"),
            _sortable_th("p", "num"),
        ]
    )
    corr_body = ""
    for _, r in corr_show.iterrows():
        corr_body += (
            "<tr>"
            f"<td>{esc(str(r['scope']))}</td>"
            f"<td>{esc(str(r['side']))}</td>"
            f"<td>{int(r['horizon_d'])}</td>"
            f"<td>{esc(str(r['ret_col']))}</td>"
            f"<td>{_fmt(r['n'], 'int')}</td>"
            f"<td>{_fmt(r['r'], 'r', 3)}</td>"
            f"<td>{_fmt(r['p'], 'p', 4)}</td>"
            "</tr>"
        )

    try:
        gap_disp = str(gap_csv.relative_to(ROOT))
    except ValueError:
        gap_disp = str(gap_csv)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Gap-Up Forward Returns by Size &amp; Horizon</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#0f172a;background:#f8fafc;line-height:1.45;max-width:1200px}}
h1{{font-size:1.45rem;margin:0 0 .4rem}}
h2{{font-size:1.1rem;margin:1.6rem 0 .5rem;border-bottom:1px solid #cbd5e1;padding-bottom:.25rem}}
.meta{{color:#475569;font-size:.92rem;margin:.4rem 0 1rem}}
.verdict{{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;padding:.9rem 1.1rem;margin:1rem 0}}
.verdict ul{{margin:.4rem 0 0;padding-left:1.2rem}}
.method{{background:#f1f5f9;border:1px solid #cbd5e1;border-radius:8px;padding:.8rem 1rem;font-size:.92rem}}
.caption{{color:#64748b;font-size:.88rem;margin:.2rem 0 .6rem}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:.88rem;margin-bottom:1rem}}
th,td{{border:1px solid #e2e8f0;padding:.35rem .55rem;text-align:left}}
th{{background:#f1f5f9}}
{SORTABLE_TH_CSS}
code{{font-size:.85em}}
</style>
</head>
<body>
<h1>Gap-Up Forward Returns by Size &amp; Horizon</h1>
<p class="meta">
Source: <code>{esc(gap_disp)}</code><br/>
Events: <strong>{meta['n_events']:,}</strong>
· GAP_DATE {esc(meta.get('date_min',''))} → {esc(meta.get('date_max',''))}
· GAP_PCT [{_fmt(meta.get('gap_min'), 'num', 2)}, {_fmt(meta.get('gap_max'), 'num', 1)}]<br/>
Returns: <code>RET_C_Nd</code> = % from gap <em>close</em>; <code>RET_O_Nd</code> = % from gap <em>open</em>
(N trading days later).
</p>

<div class="verdict">
<strong>Verdict.</strong> {esc(headline)}
<ul>{bullet_li}</ul>
</div>

<div class="method">
<strong>Method — annualized rate of return.</strong>
Holding-period mean simple return <em>r</em> (decimal) over <em>N</em> trading days is compounded to
a 252-trading-day year:
<code>Ann = (1 + r)^(252/N) − 1</code>
(with <em>r</em> = mean_pct/100). Median-based Ann uses the same formula on the median.
<strong>Ann/std</strong> = Ann_mean / std of the N-day % returns (risk-aware ranking; not Sharpe).
Discrete buckets: [1–2%), [2–3%), [3–5%), [5–10%), ≥10%. Cumulative: ≥1%, ≥2%, ≥3%, ≥5%, ≥10%.
</div>

{heat_html}

{detail_table(close_b, "3. Close-side detail (buckets + All)", "Click column headers to sort. Primary path: buy gap close → exit after N days.")}
{detail_table(open_b, "4. Open-side detail (buckets + All)", "Click column headers to sort. Path: buy gap open → exit after N days (includes gap-day open→close in the return).")}
{detail_table(cum_close, "5. Cumulative thresholds (close)", "Click headers to sort. ≥k% includes all gaps at or above threshold.")}

<h2>6. Correlation: GAP_PCT vs forward return</h2>
<p class="caption">Pearson overall and within buckets. |r| near 0 ⇒ bigger gap ≠ bigger forward move linearly.</p>
<table class="sortable">
<thead><tr>{corr_heads}</tr></thead>
<tbody>{corr_body}</tbody>
</table>

<p class="meta">CSV summary twin: <code>GapUp_Forward_Returns_summary.csv</code>.
Does not overwrite GapUp_Market_Correlation.html.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")


def write_summary_csv(
    bucket_df: pd.DataFrame,
    cum_df: pd.DataFrame,
    corr_df: pd.DataFrame,
    out_csv: Path,
) -> None:
    base_cols = [
        "table",
        "scope",
        "scope_kind",
        "threshold",
        "side",
        "horizon_d",
        "ret_col",
        "n",
        "mean_pct",
        "median_pct",
        "std_pct",
        "win_rate",
        "ann_mean_pct",
        "ann_median_pct",
        "ann_over_std",
        "pearson_r",
        "pearson_p",
    ]

    def _prep(frame: pd.DataFrame, table: str, scope_kind_default: str) -> pd.DataFrame:
        p = frame.copy()
        p["table"] = table
        if "scope_kind" not in p.columns:
            p["scope_kind"] = scope_kind_default
        if "threshold" not in p.columns:
            p["threshold"] = np.nan
        if "pearson_r" not in p.columns:
            p["pearson_r"] = np.nan
            p["pearson_p"] = np.nan
        for col in base_cols:
            if col not in p.columns:
                p[col] = np.nan
        return p[base_cols]

    b = _prep(bucket_df, "bucket_or_all", "bucket")
    c = _prep(cum_df, "cumulative", "cumulative")
    corr = corr_df.rename(columns={"r": "pearson_r", "p": "pearson_p"})
    corr2 = _prep(corr, "correlation", "corr")
    out = pd.concat([b, c, corr2], ignore_index=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gap-csv", type=Path, default=None, help="GapUp scan CSV with RET_* cols")
    ap.add_argument(
        "--out-html",
        type=Path,
        default=OUT_DIR / "GapUp_Forward_Returns.html",
    )
    ap.add_argument(
        "--out-csv",
        type=Path,
        default=OUT_DIR / "GapUp_Forward_Returns_summary.csv",
    )
    args = ap.parse_args(argv)

    gap_csv = args.gap_csv.resolve() if args.gap_csv else find_latest_gap_csv_with_fwd()
    if not gap_csv.is_file():
        print(f"ERROR: gap CSV not found: {gap_csv}", file=sys.stderr)
        return 1

    print(f"[gap-fwd] gap_csv={gap_csv.name}")
    df = load_gap_fwd(gap_csv)
    print(f"[gap-fwd] events={len(df):,} gap_min={df['GAP_PCT'].min():.3f}")
    bucket_df, cum_df, corr_df, meta = build_summary(df)
    write_summary_csv(bucket_df, cum_df, corr_df, args.out_csv.resolve())
    write_html(gap_csv, bucket_df, cum_df, corr_df, meta, args.out_html.resolve())

    headline, bullets = _verdict(meta, corr_df)
    print(f"[gap-fwd] wrote {args.out_html}")
    print(f"[gap-fwd] wrote {args.out_csv}")
    print("--- VERDICT ---")

    def _ascii(s: str) -> str:
        return (
            s.replace("≥", ">=")
            .replace("–", "-")
            .replace("→", "->")
            .replace("−", "-")
            .replace("×", "x")
            .replace("≈", "~")
            .replace("≠", "!=")
        )

    print(_ascii(headline))
    for b in bullets:
        print(f"  - {_ascii(b)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
