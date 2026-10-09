#!/usr/bin/env python3
"""VZ research: OC-overlap volume as zone strength vs PnL / Ann ROR.

Uses the freeze *prior* to the last adopted trade-count cut (rw63):
  RESEARCH_CANDIDATE_V2 = HL-only, first_retest, mt>=1, retest_window=126
  + house fill next_open + primary exit zone_atr05_ts40

Strength (as-of signal bar, no look-ahead):
  A day counts when Open or Close sits inside the zone [lo, hi].
  Volume on those days (after the zone is known, through the signal bar)
  is the strength measure. Relative volume (vs 20d SMA) is the
  cross-symbol primary metric.

Research only — not gold / not DailyRun.

  python tools/vz_oc_overlap_vol_strength.py
  python tools/vz_oc_overlap_vol_strength.py --stamp vz_oc_vol_strength_YYYYMMDD
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from vol_zone_break_retest import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_OUT_DIR,
    OOS_SPLIT_DATE,
    PRIMARY_EXIT,
    RESEARCH_CANDIDATE_V2,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SysParams,
    Zone,
    _closed_signal_rows,
    _fmt_num,
    _fmt_pct,
    ann_ror_from_signal_rows,
    atr14,
    build_zones,
    enrich_signal_rows,
    load_ohlcv,
    run_symbol_with_params,
    sortable_th,
    split_is_oos,
    summarize_signal_dicts,
)

STAMP_DEFAULT = "vz_oc_vol_strength_20260813"
RVOL_WIN = 20

# DualPaul78 research default (drive/universes/VZ_universe.csv is gitignored).
DUAL_PAUL78 = [
    "AA", "EC", "PLPC", "SUBCY", "BELFA", "NXPI", "ITIC", "PLD", "AEM", "OCANF",
    "WTS", "GOOGL", "HTHIY", "ESLT", "PNRG", "CVNA", "UUUU", "NGL", "SIMO", "FANG",
    "WTFC", "INCY", "AU", "CRWD", "GE", "TROW", "VLO", "CF", "PRIM", "BCH",
    "CRZBY", "HBM", "GGAL", "POWL", "NG", "PAC", "AAPL", "MTX", "CENX", "RUSHB",
    "LCII", "MAR", "RGLD", "CSTM", "NMR", "BN", "TFC", "ESEA", "PDEX", "KINS",
    "BYD", "MSTR", "SVM", "PPIH", "TAYD", "CIEN", "BANC", "UTI", "TGB", "ITT",
    "EQIX", "BG", "HMY", "BPOP", "BAP", "SPXC", "WDC", "ENS", "SAFRY", "AEE",
    "NDAQ", "SWK", "AKAM", "AME", "DELL", "LYV", "ASH", "SENEA", "CI", "FBAK",
    "ETR", "FNF", "AWI",
]
YF_ALTS = {"OCANF": ["OCANF", "OGC"]}

# Primary strength features (as-of signal; causal).
STRENGTH_FEATURES = [
    ("oc_rvol_mean", "Mean relative vol on OC-overlap days (primary)"),
    ("oc_rvol_sum", "Sum of relative vol on OC-overlap days"),
    ("oc_rvol_max", "Max relative vol on OC-overlap days"),
    ("oc_overlap_n", "Count of OC-overlap days"),
    ("log_oc_vol_sum", "log1p sum of raw overlap volume"),
    ("origin_rvol", "Origin max-vol day relative volume"),
    ("touch_strength", "Existing visit/hold strength score"),
    ("touch_count_all", "Existing pre-entry visit count"),
]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _rank_avg(s: pd.Series) -> pd.Series:
    return s.rank(method="average")


def corr_with_p(x: pd.Series, y: pd.Series, method: str = "spearman") -> tuple[float, float, int]:
    """Return (r, two-sided p via normal approx, n). Spearman via ranks (no scipy)."""
    d = pd.concat([x, y], axis=1).dropna()
    n = int(len(d))
    if n < 8:
        return float("nan"), float("nan"), n
    a = d.iloc[:, 0]
    b = d.iloc[:, 1]
    if method == "spearman":
        a = _rank_avg(a)
        b = _rank_avg(b)
    r = float(a.corr(b, method="pearson"))
    if not np.isfinite(r) or abs(r) >= 0.999999:
        return r, float("nan"), n
    t = r * math.sqrt((n - 2) / (1.0 - r * r))
    p = 2.0 * (1.0 - _norm_cdf(abs(t)))
    return r, p, n


def oc_overlap_mask(opens: np.ndarray, closes: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """True when Open or Close sits inside [lo, hi] (inclusive)."""
    o_in = (opens >= lo) & (opens <= hi)
    c_in = (closes >= lo) & (closes <= hi)
    return o_in | c_in


def rvol20(vol: np.ndarray, win: int = RVOL_WIN) -> np.ndarray:
    s = pd.Series(vol)
    base = s.rolling(win, min_periods=max(5, win // 2)).mean().to_numpy(dtype=np.float64)
    out = np.full_like(vol, np.nan, dtype=np.float64)
    ok = np.isfinite(base) & (base > 0)
    out[ok] = vol[ok] / base[ok]
    return out


def zone_oc_strength(
    df: pd.DataFrame,
    zone: Zone,
    asof_idx: int,
    rvol: np.ndarray,
) -> dict[str, float]:
    """OC-overlap volume stats using bars (created_on, asof] — no look-ahead."""
    opens = df["Open"].to_numpy(dtype=np.float64)
    closes = df["Close"].to_numpy(dtype=np.float64)
    vols = df["Volume"].to_numpy(dtype=np.float64)
    start = int(zone.created_on_idx) + 1
    end = int(asof_idx)
    empty = {
        "oc_overlap_n": 0.0,
        "oc_vol_sum": 0.0,
        "oc_vol_mean": float("nan"),
        "oc_rvol_mean": float("nan"),
        "oc_rvol_sum": 0.0,
        "oc_rvol_max": float("nan"),
        "log_oc_vol_sum": 0.0,
        "origin_vol": float(zone.volume),
        "origin_rvol": float("nan"),
    }
    oi = int(zone.max_vol_idx)
    if 0 <= oi < len(rvol) and np.isfinite(rvol[oi]):
        empty["origin_rvol"] = float(rvol[oi])
    if start > end or start >= len(df):
        return empty
    end = min(end, len(df) - 1)
    sl = slice(start, end + 1)
    hit = oc_overlap_mask(opens[sl], closes[sl], float(zone.lo), float(zone.hi))
    n = int(hit.sum())
    empty["oc_overlap_n"] = float(n)
    if n <= 0:
        return empty
    v = vols[sl][hit]
    rv = rvol[sl][hit]
    empty["oc_vol_sum"] = float(np.nansum(v))
    empty["oc_vol_mean"] = float(np.nanmean(v))
    empty["log_oc_vol_sum"] = float(np.log1p(empty["oc_vol_sum"]))
    rv_ok = rv[np.isfinite(rv)]
    if len(rv_ok):
        empty["oc_rvol_mean"] = float(np.mean(rv_ok))
        empty["oc_rvol_sum"] = float(np.sum(rv_ok))
        empty["oc_rvol_max"] = float(np.max(rv_ok))
    return empty


def ensure_ohlcv(symbols: list[str], data_dir: Path) -> tuple[list[str], list[str]]:
    """Download missing DualPaul78 CSVs via yfinance into house OHLCV shape."""
    data_dir.mkdir(parents=True, exist_ok=True)
    need: list[str] = []
    have: list[str] = []
    for s in symbols:
        p = data_dir / f"{s}.csv"
        if p.is_file() and p.stat().st_size > 200:
            have.append(s)
        else:
            need.append(s)
    if not need:
        return have, []
    print(f"[VZ-ocvol] downloading {len(need)} missing symbols via yfinance", flush=True)
    import yfinance as yf

    failed: list[str] = []
    # Batch download, then fill gaps one-by-one.
    yf_tickers: list[str] = []
    wanted_by_yf: dict[str, str] = {}
    for s in need:
        alts = YF_ALTS.get(s, [s])
        yf_tickers.append(alts[0])
        wanted_by_yf[alts[0]] = s
    raw = yf.download(
        yf_tickers,
        start="2005-01-01",
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    saved = 0
    for yf_sym, house_sym in wanted_by_yf.items():
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if yf_sym not in raw.columns.get_level_values(0) and yf_sym not in raw.columns.get_level_values(1):
                    failed.append(house_sym)
                    continue
                # yfinance layout varies: (Ticker, Price) or (Price, Ticker)
                lvl0 = set(raw.columns.get_level_values(0))
                if yf_sym in lvl0:
                    sub = raw[yf_sym].copy()
                else:
                    sub = raw.xs(yf_sym, axis=1, level=1).copy()
            else:
                sub = raw.copy()
            sub = sub.rename(columns=str.title)
            need_cols = {"Open", "High", "Low", "Close", "Volume"}
            if not need_cols.issubset(set(sub.columns)):
                failed.append(house_sym)
                continue
            sub = sub.dropna(subset=["Open", "High", "Low", "Close"])
            if len(sub) < 200:
                failed.append(house_sym)
                continue
            out = sub.reset_index()
            date_col = "Date" if "Date" in out.columns else out.columns[0]
            out = out.rename(columns={date_col: "Date"})
            out["Date"] = pd.to_datetime(out["Date"]).dt.tz_localize(None)
            out = out[["Date", "Open", "High", "Low", "Close", "Volume"]]
            out.to_csv(data_dir / f"{house_sym}.csv", index=False)
            saved += 1
            have.append(house_sym)
        except Exception:
            failed.append(house_sym)
    print(f"[VZ-ocvol] saved {saved} CSVs; failed {len(failed)}", flush=True)
    # One-by-one retry for failures / alts
    still: list[str] = []
    for s in failed:
        ok = False
        for alt in YF_ALTS.get(s, [s]):
            try:
                t = yf.Ticker(alt)
                hist = t.history(start="2005-01-01", auto_adjust=True)
                if hist is None or hist.empty or len(hist) < 200:
                    continue
                hist = hist.rename(columns=str.title).reset_index()
                date_col = "Date" if "Date" in hist.columns else hist.columns[0]
                hist = hist.rename(columns={date_col: "Date"})
                hist["Date"] = pd.to_datetime(hist["Date"]).dt.tz_localize(None)
                hist = hist[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(hist) < 200:
                    continue
                hist.to_csv(data_dir / f"{s}.csv", index=False)
                have.append(s)
                ok = True
                break
            except Exception:
                continue
        if not ok:
            still.append(s)
    if still:
        print(f"[VZ-ocvol] still missing: {', '.join(still)}", flush=True)
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in have:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq, still


def _worker(args: tuple[str, str, dict]) -> dict:
    """Picklable one-symbol worker."""
    sym, data_dir, pdict = args
    params = SysParams(**pdict)
    return process_symbol(sym, Path(data_dir), params)


def process_symbol(sym: str, data_dir: Path, params: SysParams) -> dict:
    csv_path = data_dir / f"{sym}.csv"
    if not csv_path.is_file():
        return {"symbol": sym, "status": "missing", "rows": [], "note": "no csv"}
    try:
        df = load_ohlcv(csv_path)
        if len(df) <= params.lookback_days + 20:
            return {"symbol": sym, "status": "short", "rows": [], "note": f"n={len(df)}"}
        atr = atr14(df)
        zones = build_zones(df, params.lookback_days)
        zone_by_id = {z.zone_id: z for z in zones}
        sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, params)
        rows = enrich_signal_rows(sym, df, sigs, params, atr=atr, exit_spec=PRIMARY_EXIT)
        rvol = rvol20(df["Volume"].to_numpy(dtype=np.float64))
        nan_stats = {
            "oc_overlap_n": 0.0,
            "oc_vol_sum": 0.0,
            "oc_vol_mean": float("nan"),
            "oc_rvol_mean": float("nan"),
            "oc_rvol_sum": 0.0,
            "oc_rvol_max": float("nan"),
            "log_oc_vol_sum": 0.0,
            "origin_vol": float("nan"),
            "origin_rvol": float("nan"),
        }
        for row, sig in zip(rows, sigs):
            z = zone_by_id.get(sig.zone_id)
            asof = int(sig.signal_idx) if int(getattr(sig, "signal_idx", -1)) >= 0 else int(sig.entry_idx)
            stats = zone_oc_strength(df, z, asof, rvol) if z is not None else dict(nan_stats)
            row.update(stats)
            row["touch_strength"] = float(row.get("strength") or 0.0)
            days = max(int(row.get("bars_held") or 0), 1)
            row["ann_ror_pct"] = float(row["pnl_pct"]) * (365.25 / float(days))
            row["signal_idx"] = asof
            row["zone_lo"] = float(z.lo) if z is not None else row.get("zone_lo")
            row["zone_hi"] = float(z.hi) if z is not None else float("nan")
            row["origin_vol"] = float(z.volume) if z is not None else float("nan")
        return {"symbol": sym, "status": "ok", "rows": rows, "note": "", "n_zones": len(zones)}
    except Exception as e:
        return {"symbol": sym, "status": "error", "rows": [], "note": str(e)[:200]}


def quartile_table(df: pd.DataFrame, feat: str) -> pd.DataFrame:
    d = df.dropna(subset=[feat]).copy()
    if d.empty:
        return pd.DataFrame()
    try:
        d["q"] = pd.qcut(d[feat], 4, labels=["Q1 low", "Q2", "Q3", "Q4 high"], duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    rows = []
    for q, g in d.groupby("q", observed=True):
        recs = g.to_dict("records")
        m = summarize_signal_dicts(recs)
        rows.append(
            {
                "quartile": str(q),
                "n": int(len(g)),
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "median_pnl_pct": m["median_pnl_pct"],
                "avg_r": m["avg_r"],
                "avg_days": m["avg_days_held"],
                "ann_ror": m["ann_ror"],
                "avg_ann_ror_trade": float(g["ann_ror_pct"].mean()),
                "median_ann_ror_trade": float(g["ann_ror_pct"].median()),
                "mean_feat": float(g[feat].mean()),
            }
        )
    return pd.DataFrame(rows)


def within_symbol_spearman(df: pd.DataFrame, feat: str, y: str, min_n: int = 8) -> tuple[float, int, int]:
    """Mean per-symbol Spearman; returns (mean_r, n_symbols, n_trades_used)."""
    rs = []
    n_used = 0
    for _, g in df.groupby("symbol"):
        if len(g) < min_n:
            continue
        r, _, n = corr_with_p(g[feat], g[y], "spearman")
        if np.isfinite(r):
            rs.append(r)
            n_used += n
    if not rs:
        return float("nan"), 0, 0
    return float(np.mean(rs)), int(len(rs)), int(n_used)


def _metrics_row_html(label: str, m: dict) -> str:
    return (
        f"<tr><td>{html_mod.escape(label)}</td>"
        f"<td>{m['n_signals']}</td>"
        f"<td>{_fmt_pct(m['win_rate'])}%</td>"
        f"<td>{_fmt_num(m['avg_pnl_pct'])}</td>"
        f"<td>{_fmt_num(m['avg_r'])}</td>"
        f"<td>{_fmt_num(m.get('median_pnl_pct', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('avg_days_held', 0.0), 1)}</td>"
        f"<td>{_fmt_num(m.get('ann_ror', 0.0))}</td></tr>"
    )


def write_scatter(df: pd.DataFrame, feat: str, y: str, path: Path, title: str) -> None:
    d = df.dropna(subset=[feat, y])
    if d.empty:
        return
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.scatter(d[feat], d[y], s=12, alpha=0.35, c="#2a4a5c", edgecolors="none")
    ax.set_xlabel(feat)
    ax.set_ylabel(y)
    ax.set_title(title)
    ax.axhline(0.0, color="#999", lw=0.8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def write_html(
    *,
    out_path: Path,
    stamp: str,
    params: SysParams,
    n_symbols: int,
    skipped: list[str],
    full_m: dict,
    is_m: dict,
    oos_m: dict,
    corr_rows: list[dict],
    q_primary: pd.DataFrame,
    q_is: pd.DataFrame,
    q_oos: pd.DataFrame,
    q_origin: pd.DataFrame,
    q_touch: pd.DataFrame,
    within: dict,
    png_rel: str,
) -> None:
    def q_table(df: pd.DataFrame, caption: str) -> str:
        if df is None or df.empty:
            return f"<p class='muted'>{html_mod.escape(caption)}: not enough distinct values to quartile.</p>"
        body = []
        for _, r in df.iterrows():
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(str(r['quartile']))}</td>"
                f"<td>{int(r['n'])}</td>"
                f"<td>{_fmt_pct(float(r['win_rate']))}%</td>"
                f"<td>{_fmt_num(float(r['avg_pnl_pct']))}</td>"
                f"<td>{_fmt_num(float(r['median_pnl_pct']))}</td>"
                f"<td>{_fmt_num(float(r['avg_r']))}</td>"
                f"<td>{_fmt_num(float(r['avg_days']), 1)}</td>"
                f"<td>{_fmt_num(float(r['ann_ror']))}</td>"
                f"<td>{_fmt_num(float(r['avg_ann_ror_trade']))}</td>"
                f"<td>{_fmt_num(float(r['mean_feat']), 3)}</td>"
                "</tr>"
            )
        heads = "".join(
            [
                sortable_th("Quartile", "text"),
                sortable_th("N", "num"),
                sortable_th("Win%", "num"),
                sortable_th("Avg PnL%", "num"),
                sortable_th("Med PnL%", "num"),
                sortable_th("Avg R", "num"),
                sortable_th("Avg days", "num"),
                sortable_th("Book Ann ROR%", "num"),
                sortable_th("Avg trade Ann ROR%", "num"),
                sortable_th("Mean feature", "num"),
            ]
        )
        return (
            f"<div class='table-wrap'><table class='sortable'><caption>{html_mod.escape(caption)}</caption>"
            f"<thead><tr>{heads}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )

    corr_body = []
    for r in corr_rows:
        corr_body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['feature'])}</td>"
            f"<td>{html_mod.escape(r['label'])}</td>"
            f"<td>{html_mod.escape(r['vs'])}</td>"
            f"<td>{r['spearman']:+.3f}</td>"
            f"<td>{r['pearson']:+.3f}</td>"
            f"<td>{r['p_spearman']:.4f}</td>"
            f"<td>{r['n']}</td>"
            "</tr>"
        )
    skip_txt = ", ".join(skipped) if skipped else "none"
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>VZ OC-overlap volume strength — {html_mod.escape(stamp)}</title>
<style>
  body {{ font-family: Segoe UI, Helvetica, sans-serif; margin: 24px; color: #1c1b19; background: #f7f6f2; }}
  h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
  h2 {{ font-size: 1.08rem; margin: 22px 0 8px; border-bottom: 1px solid #d4d0c4; padding-bottom: 4px; }}
  .muted {{ color: #5a574f; }}
  .callout {{ background: #e8eef2; border-left: 4px solid #2a4a5c; padding: 10px 12px; margin: 12px 0; }}
  .callout.warn {{ background: #f7efe0; border-left-color: #8a5a12; }}
  .callout.ok {{ background: #e8f2ec; border-left-color: #2d6a4f; }}
  .callout.bad {{ background: #fdecea; border-left-color: #9b2226; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }}
  th, td {{ border: 1px solid #d4d0c4; padding: 6px 8px; text-align: left; }}
  thead th {{ background: #f0eee6; }}
  {SORTABLE_TH_CSS}
  img {{ max-width: 100%; border: 1px solid #d4d0c4; background: #fff; }}
  code {{ background: #f0eee6; padding: 0.05em 0.3em; }}
</style></head><body>
<h1>VZ — OC-overlap volume as zone strength</h1>
<p class="muted">Research only · stamp <code>{html_mod.escape(stamp)}</code> · DualPaul78 ({n_symbols} symbols with data)</p>
<div class="callout warn">
<strong>Prior to the last trade-count cut.</strong>
Adopted freeze is <code>RESEARCH_CANDIDATE_V2_RW63</code> (retest_window=63).
This stamp uses <code>RESEARCH_CANDIDATE_V2</code> with <strong>retest_window=126</strong>
(same HL / first_retest / mt≥1 gates) so more late retests remain in the sample.
House fill <code>entry_on=next_open</code>, exit <code>zone_atr05_ts40</code>.
Not gold. Do not retune on OOS.
</div>
<h2>1. Hypothesis</h2>
<p>
Zone strength = volume on any day, after the zone is known and through the signal bar,
where <strong>Open or Close sits inside the zone band</strong> [lo, hi].
Relative volume (day volume / 20-day SMA) is the primary cross-symbol metric —
raw share volume is not comparable across names.
</p>
<p>Question: does that strength correlate with trade PnL% or book Ann ROR?</p>
<div class="callout">
<strong>Causal window:</strong> bars <code>(zone.created_on_idx, signal_idx]</code>.
Origin max-vol day is reported separately and is <em>not</em> mixed into the overlap sum
(that day already defined the zone).
</div>
<h2>2. Freeze / coverage</h2>
<ul>
<li>lookback={params.lookback_days} · retest_window=<strong>{params.retest_window}</strong> · eps={params.retest_eps_pct}</li>
<li>first_retest_only={params.first_retest_only} · min_touches≥{params.min_touches_before_entry} · kinds={'+'.join(params.zone_kinds)}</li>
<li>entry_on={params.entry_on} · exit={PRIMARY_EXIT.name}</li>
<li>IS = entry &lt; 2024-01-01 · OOS = 2024+</li>
<li>Skipped / missing: {html_mod.escape(skip_txt)}</li>
</ul>
<div class="table-wrap"><table class="sortable">
<caption>Pooled closed trades (still_open dropped)</caption>
<thead><tr>
{sortable_th("Split", "text")}{sortable_th("N", "num")}{sortable_th("Win%", "num")}
{sortable_th("Avg PnL%", "num")}{sortable_th("Avg R", "num")}{sortable_th("Med PnL%", "num")}
{sortable_th("Avg days", "num")}{sortable_th("Book Ann ROR%", "num")}
</tr></thead>
<tbody>
{_metrics_row_html("FULL rw126", full_m)}
{_metrics_row_html("IS", is_m)}
{_metrics_row_html("OOS", oos_m)}
</tbody></table></div>

<h2>3. Correlation (closed trades)</h2>
<p>Spearman is the headline (volume features are skewed). p-values use a normal approximation of the t statistic — directional, not a multiple-test correction.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>
{sortable_th("Feature", "text")}{sortable_th("Meaning", "text")}{sortable_th("vs", "text")}
{sortable_th("Spearman", "num")}{sortable_th("Pearson", "num")}{sortable_th("p (Spearman)", "num")}
{sortable_th("N", "num")}
</tr></thead>
<tbody>{''.join(corr_body)}</tbody></table></div>
<p class="muted">Within-symbol mean Spearman (symbols with ≥8 closed trades):
oc_rvol_mean vs pnl_pct = <strong>{within.get('pnl', float('nan')):+.3f}</strong>
({within.get('pnl_n_sym', 0)} symbols) ·
vs trade Ann ROR = <strong>{within.get('ann', float('nan')):+.3f}</strong>.</p>

<h2>4. Quartiles — primary feature <code>oc_rvol_mean</code></h2>
<p>Book Ann ROR is the house formula on the quartile subset (not the mean of per-trade Ann ROR).
A monotone Q1→Q4 lift in Avg PnL% / book Ann ROR would support a strength filter.</p>
{q_table(q_primary, "FULL — mean relative volume on OC-overlap days")}
{q_table(q_is, "IS — oc_rvol_mean")}
{q_table(q_oos, "OOS — oc_rvol_mean")}

<h2>5. Contrast: origin-day rvol and existing touch strength</h2>
{q_table(q_origin, "FULL — origin max-vol day relative volume")}
{q_table(q_touch, "FULL — existing visit/hold strength score")}

<h2>6. Scatter (primary)</h2>
<p><img src="{html_mod.escape(png_rel)}" alt="oc_rvol_mean vs pnl_pct"/></p>

<h2>7. How to read this</h2>
<ul>
<li><strong>Useful filter:</strong> Spearman |r| ≳ 0.15 with a monotone quartile lift in PnL and book Ann ROR, holding on OOS.</li>
<li><strong>Weak / none:</strong> |r| ≲ 0.10 and Q4 not clearly better than Q1 — overlap volume is not a ranking signal on this freeze.</li>
<li>Per-trade Ann ROR is noisy (short winners inflate it). Prefer book Ann ROR by quartile.</li>
</ul>
<footer class="muted">Twin Beacon Networks · VZ research · {html_mod.escape(stamp)}</footer>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.write_text(html, encoding="utf-8")


def write_md(
    path: Path,
    *,
    stamp: str,
    n_full: int,
    full_m: dict,
    corr_rows: list[dict],
    q_primary: pd.DataFrame,
    verdict: str,
) -> None:
    lines = [
        f"# VZ OC-overlap volume strength — {stamp}",
        "",
        "Research only. Freeze = RESEARCH_CANDIDATE_V2 (rw126) — prior to the rw63 trade-count cut.",
        "",
        f"- Closed trades: **{n_full}**",
        f"- WR {_fmt_pct(full_m['win_rate'])}% · avg PnL {_fmt_num(full_m['avg_pnl_pct'])}% · "
        f"book Ann ROR {_fmt_num(full_m.get('ann_ror', 0.0))}%",
        "",
        "## Verdict",
        "",
        verdict,
        "",
        "## Headline correlations (Spearman vs PnL%)",
        "",
        "| Feature | r | p | N |",
        "|---|---:|---:|---:|",
    ]
    for r in corr_rows:
        if r["vs"] != "pnl_pct":
            continue
        lines.append(f"| {r['feature']} | {r['spearman']:+.3f} | {r['p_spearman']:.4f} | {r['n']} |")
    lines += ["", "## Quartiles of oc_rvol_mean", ""]
    if q_primary is not None and not q_primary.empty:
        lines.append("| Q | N | Win% | Avg PnL% | Book Ann ROR% |")
        lines.append("|---|---:|---:|---:|---:|")
        for _, row in q_primary.iterrows():
            lines.append(
                f"| {row['quartile']} | {int(row['n'])} | {_fmt_pct(float(row['win_rate']))}% | "
                f"{_fmt_num(float(row['avg_pnl_pct']))} | {_fmt_num(float(row['ann_ror']))} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _verdict(corr_rows: list[dict], q: pd.DataFrame) -> str:
    prim = next((r for r in corr_rows if r["feature"] == "oc_rvol_mean" and r["vs"] == "pnl_pct"), None)
    ann = next((r for r in corr_rows if r["feature"] == "oc_rvol_mean" and r["vs"] == "ann_ror_pct"), None)
    r = float(prim["spearman"]) if prim else float("nan")
    ra = float(ann["spearman"]) if ann else float("nan")
    monotone = False
    q4_better = False
    if q is not None and len(q) >= 2:
        pnls = q["avg_pnl_pct"].to_numpy(dtype=float)
        anns = q["ann_ror"].to_numpy(dtype=float)
        monotone = bool(np.all(np.diff(pnls) >= -1e-9) or np.all(np.diff(pnls) <= 1e-9))
        q4_better = bool(pnls[-1] > pnls[0] and anns[-1] > anns[0])
    if not np.isfinite(r):
        return "Not enough data to judge correlation."
    if abs(r) >= 0.15 and q4_better:
        return (
            f"**Yes — modest/useful association.** Spearman(oc_rvol_mean, PnL%) = {r:+.3f}; "
            f"vs per-trade Ann ROR {ra:+.3f}. Q4 beats Q1 on both avg PnL and book Ann ROR. "
            "Worth a one-knob filter AB (not an automatic adopt)."
        )
    if abs(r) >= 0.08 and q4_better:
        return (
            f"**Weak association.** Spearman(oc_rvol_mean, PnL%) = {r:+.3f}; "
            f"vs per-trade Ann ROR {ra:+.3f}. Quartiles lean the right way but the rank "
            "correlation is small — a filter would cut trades for a thin quality lift."
        )
    extra = " Quartiles are not monotone." if not monotone else ""
    return (
        f"**No meaningful correlation for a filter.** Spearman(oc_rvol_mean, PnL%) = {r:+.3f}; "
        f"vs per-trade Ann ROR {ra:+.3f}. Overlap-day volume does not rank VZ trades "
        f"on this rw126 freeze.{extra}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="VZ OC-overlap volume strength vs PnL / Ann ROR")
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--symbols", default="")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir) / args.stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or list(DUAL_PAUL78)
    skipped: list[str] = []
    if not args.skip_download:
        symbols, skipped = ensure_ohlcv(symbols, data_dir)
    else:
        symbols = [s for s in symbols if (data_dir / f"{s}.csv").is_file()]

    params = replace(RESEARCH_CANDIDATE_V2, entry_on="next_open")
    print(
        f"[VZ-ocvol] freeze=rw{params.retest_window} (prior to rw63) "
        f"symbols={len(symbols)} stamp={args.stamp}",
        flush=True,
    )
    t0 = time.time()
    all_rows: list[dict] = []
    per_status: list[dict] = []
    pdict = asdict(params)
    n_w = max(1, int(args.workers))
    if n_w == 1 or len(symbols) == 1:
        iterator = (
            (i, process_symbol(sym, data_dir, params))
            for i, sym in enumerate(symbols, 1)
        )
        for i, res in iterator:
            per_status.append(
                {"symbol": res["symbol"], "status": res["status"], "note": res.get("note", ""), "n": len(res["rows"])}
            )
            all_rows.extend(res["rows"])
            print(
                f"  [{i}/{len(symbols)}] {res['symbol']} {res['status']} n={len(res['rows'])}",
                flush=True,
            )
            if res["status"] != "ok":
                skipped.append(f"{res['symbol']}:{res['status']}")
    else:
        print(f"[VZ-ocvol] {n_w} workers", flush=True)
        jobs = [(sym, str(data_dir), pdict) for sym in symbols]
        done = 0
        with ProcessPoolExecutor(max_workers=n_w) as ex:
            futs = {ex.submit(_worker, job): job[0] for job in jobs}
            for fut in as_completed(futs):
                done += 1
                try:
                    res = fut.result()
                except Exception as e:
                    sym = futs[fut]
                    res = {"symbol": sym, "status": "error", "rows": [], "note": str(e)[:200]}
                per_status.append(
                    {
                        "symbol": res["symbol"],
                        "status": res["status"],
                        "note": res.get("note", ""),
                        "n": len(res["rows"]),
                    }
                )
                all_rows.extend(res["rows"])
                print(
                    f"  [{done}/{len(symbols)}] {res['symbol']} {res['status']} n={len(res['rows'])}",
                    flush=True,
                )
                if res["status"] != "ok":
                    skipped.append(f"{res['symbol']}:{res['status']}")

    closed = _closed_signal_rows(all_rows)
    df = pd.DataFrame(closed)
    if df.empty:
        print("[VZ-ocvol] no closed trades", flush=True)
        return 1
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    is_rows, oos_rows = split_is_oos(closed)
    full_m = summarize_signal_dicts(closed)
    is_m = summarize_signal_dicts(is_rows)
    oos_m = summarize_signal_dicts(oos_rows)

    corr_rows: list[dict] = []
    for feat, label in STRENGTH_FEATURES:
        if feat not in df.columns:
            continue
        for vs in ("pnl_pct", "ann_ror_pct", "r_mult"):
            rs, ps, n = corr_with_p(df[feat], df[vs], "spearman")
            rp, _, _ = corr_with_p(df[feat], df[vs], "pearson")
            corr_rows.append(
                {
                    "feature": feat,
                    "label": label,
                    "vs": vs,
                    "spearman": rs if np.isfinite(rs) else 0.0,
                    "pearson": rp if np.isfinite(rp) else 0.0,
                    "p_spearman": ps if np.isfinite(ps) else 1.0,
                    "n": n,
                }
            )

    q_primary = quartile_table(df, "oc_rvol_mean")
    q_is = quartile_table(pd.DataFrame(is_rows), "oc_rvol_mean") if is_rows else pd.DataFrame()
    q_oos = quartile_table(pd.DataFrame(oos_rows), "oc_rvol_mean") if oos_rows else pd.DataFrame()
    q_origin = quartile_table(df, "origin_rvol")
    q_touch = quartile_table(df, "touch_strength")

    w_pnl, w_n, _ = within_symbol_spearman(df, "oc_rvol_mean", "pnl_pct")
    w_ann, _, _ = within_symbol_spearman(df, "oc_rvol_mean", "ann_ror_pct")
    within = {"pnl": w_pnl, "ann": w_ann, "pnl_n_sym": w_n}

    png_name = "scatter_oc_rvol_mean_vs_pnl.png"
    write_scatter(
        df,
        "oc_rvol_mean",
        "pnl_pct",
        out_dir / png_name,
        "OC-overlap mean rvol vs PnL% (rw126, DualPaul78)",
    )

    df.to_csv(out_dir / "trades_oc_vol_strength.csv", index=False)
    pd.DataFrame(corr_rows).to_csv(out_dir / "correlations.csv", index=False)
    if not q_primary.empty:
        q_primary.to_csv(out_dir / "quartiles_oc_rvol_mean.csv", index=False)
    pd.DataFrame(per_status).to_csv(out_dir / "per_symbol_status.csv", index=False)

    verdict = _verdict(corr_rows, q_primary)
    write_html(
        out_path=out_dir / "VZ_OC_Overlap_Vol_Strength.html",
        stamp=args.stamp,
        params=params,
        n_symbols=len(symbols),
        skipped=skipped,
        full_m=full_m,
        is_m=is_m,
        oos_m=oos_m,
        corr_rows=corr_rows,
        q_primary=q_primary,
        q_is=q_is,
        q_oos=q_oos,
        q_origin=q_origin,
        q_touch=q_touch,
        within=within,
        png_rel=png_name,
    )
    write_md(
        out_dir / "README.md",
        stamp=args.stamp,
        n_full=int(full_m["n_signals"]),
        full_m=full_m,
        corr_rows=corr_rows,
        q_primary=q_primary,
        verdict=verdict,
    )
    # Copy a compact verdict into docs so the PR can show numbers (drive/ is gitignored).
    docs_dir = REPO / "docs" / "research"
    docs_dir.mkdir(parents=True, exist_ok=True)
    write_md(
        docs_dir / "vz_oc_overlap_vol_strength.md",
        stamp=args.stamp,
        n_full=int(full_m["n_signals"]),
        full_m=full_m,
        corr_rows=corr_rows,
        q_primary=q_primary,
        verdict=verdict + (
            f"\n\nTrade count context: rw126 (this stamp, prior to last cut) closed N={full_m['n_signals']}. "
            "Current adopted freeze uses retest_window=63."
        ),
    )

    elapsed = time.time() - t0
    print(verdict, flush=True)
    print(
        f"[VZ-ocvol] done in {elapsed:.0f}s  N={full_m['n_signals']}  "
        f"WR={full_m['win_rate']*100:.1f}%  AnnROR={full_m.get('ann_ror', 0):.2f}%  "
        f"out={out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
