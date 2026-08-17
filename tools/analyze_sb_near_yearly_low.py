#!/usr/bin/env python3
"""Exploratory: SB closed trades vs proximity to 252-day (52w) low at entry.

Usage:
  python tools/analyze_sb_near_yearly_low.py
  python tools/analyze_sb_near_yearly_low.py --closed drive/SB_LatestRun_Closed.csv
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLOSED = ROOT / "drive" / "SB_LatestRun_Closed.csv"
DEFAULT_OHLC_DIR = ROOT / "data" / "newdata" / "data"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "sb_near_yearly_low_explore"
LOOKBACK = 252
THRESHOLDS = (5.0, 10.0, 15.0)
IS_CUTOFF = "2024-01-01"

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""

SORTABLE_TABLE_SCRIPT = """
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
        ths.forEach(function(x){x.classList.remove("sort-asc","sort-desc"); x.setAttribute("aria-sort","none");});
        th.classList.add(asc?"sort-asc":"sort-desc");
        th.setAttribute("aria-sort", asc?"ascending":"descending");
        var tbody=table.tBodies[0]; if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll("tr")).filter(function(r){return !r.classList.contains("total-row");});
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
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _parse_pct(val: Any) -> Optional[float]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip().replace("%", "").replace(",", "")
    if not s or s.upper() in {"N/A", "NA", "NONE", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(val: Any) -> Optional[pd.Timestamp]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return pd.Timestamp(datetime.strptime(s[:10].replace("-", "") if fmt == "%Y%m%d" else s[:10], fmt))
        except ValueError:
            continue
    try:
        return pd.Timestamp(s)
    except Exception:
        return None


def _atr14(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(h)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = h[0] - l[0]
    if n > 1:
        hl = h[1:] - l[1:]
        h_pc = np.abs(h[1:] - c[:-1])
        l_pc = np.abs(l[1:] - c[:-1])
        tr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr = np.full(n, np.nan, dtype=np.float64)
    if n >= period:
        atr[period - 1 :] = np.convolve(tr, np.ones(period) / period, mode="valid")
    return atr


@dataclass
class OhlcCache:
    dates: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    atr: np.ndarray
    low_252: np.ndarray


_OHLC_CACHE: dict[str, OhlcCache] = {}


def load_ohlc(symbol: str, ohlc_dir: Path) -> Optional[OhlcCache]:
    sym = symbol.upper()
    if sym in _OHLC_CACHE:
        return _OHLC_CACHE[sym]
    path = ohlc_dir / f"{sym}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    cols = {c.lower().replace(" ", "_"): c for c in df.columns}
    date_col = cols.get("date")
    if not date_col:
        return None
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)
    h = df[cols.get("high", "High")].astype(float).to_numpy()
    l = df[cols.get("low", "Low")].astype(float).to_numpy()
    c = df[cols.get("close", "Close")].astype(float).to_numpy()
    dates = df[date_col].to_numpy(dtype="datetime64[ns]")
    low_252 = pd.Series(l).rolling(LOOKBACK, min_periods=LOOKBACK).min().to_numpy()
    atr = _atr14(h, l, c)
    cache = OhlcCache(dates=dates, h=h, l=l, c=c, atr=atr, low_252=low_252)
    _OHLC_CACHE[sym] = cache
    return cache


def bar_index_on_or_before(dates: np.ndarray, dt: pd.Timestamp) -> Optional[int]:
    if dates.size == 0:
        return None
    target = np.datetime64(dt.normalize())
    idx = np.searchsorted(dates, target, side="right") - 1
    if idx < 0:
        return None
    return int(idx)


def yearly_low_metrics(
    symbol: str,
    entry_dt: pd.Timestamp,
    entry_price: float,
    ohlc_dir: Path,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "low_52w": None,
        "dist_to_52w_low_pct": None,
        "dist_to_52w_low_atr": None,
        "pct_above_52w_low": None,
        "warmup_ok": False,
        "ohlc_found": False,
    }
    bars = load_ohlc(symbol, ohlc_dir)
    if bars is None:
        return out
    out["ohlc_found"] = True
    i = bar_index_on_or_before(bars.dates, entry_dt)
    if i is None:
        return out
    low52 = float(bars.low_252[i])
    if not np.isfinite(low52) or low52 <= 0:
        return out
    out["warmup_ok"] = True
    out["low_52w"] = low52
    if entry_price > 0:
        dist_pct = (entry_price - low52) / low52 * 100.0
        out["dist_to_52w_low_pct"] = dist_pct
        out["pct_above_52w_low"] = dist_pct
        atr = float(bars.atr[i]) if i < len(bars.atr) else float("nan")
        if np.isfinite(atr) and atr > 0:
            out["dist_to_52w_low_atr"] = (entry_price - low52) / atr
    return out


def group_stats(df: pd.DataFrame, label: str) -> dict[str, Any]:
    n = len(df)
    if n == 0:
        return {"label": label, "N": 0}
    wins = (df["pnl_pct"] > 0).sum()
    wr = 100.0 * wins / n
    avg_pnl = df["pnl_pct"].mean()
    med_pnl = df["pnl_pct"].median()
    avg_ann = df["ann_ror_pct"].dropna().mean() if df["ann_ror_pct"].notna().any() else None
    med_ann = df["ann_ror_pct"].dropna().median() if df["ann_ror_pct"].notna().any() else None
    avg_days = df["days_held"].mean()
    expectancy = avg_pnl  # per-trade avg PnL% proxy
    return {
        "label": label,
        "N": n,
        "WR_pct": round(wr, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
        "med_pnl_pct": round(med_pnl, 2),
        "avg_ann_ror_pct": round(avg_ann, 1) if avg_ann is not None and np.isfinite(avg_ann) else None,
        "med_ann_ror_pct": round(med_ann, 1) if med_ann is not None and np.isfinite(med_ann) else None,
        "avg_days_held": round(avg_days, 1),
        "expectancy_pct": round(expectancy, 2),
    }


def pearson(x: pd.Series, y: pd.Series) -> Optional[float]:
    pair = pd.concat([x, y], axis=1).dropna()
    if len(pair) < 10:
        return None
    r = pair.iloc[:, 0].corr(pair.iloc[:, 1])
    return round(float(r), 3) if np.isfinite(r) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--closed", default=str(DEFAULT_CLOSED))
    ap.add_argument("--ohlc-dir", default=str(DEFAULT_OHLC_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    closed_path = Path(args.closed)
    ohlc_dir = Path(args.ohlc_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not closed_path.is_file():
        print(f"Missing closed CSV: {closed_path}", file=sys.stderr)
        return 1

    rows: list[dict[str, Any]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            sym = (raw.get("SYMBOL") or "").strip().upper()
            entry_dt = _parse_date(raw.get("DATE_OPENED") or raw.get("DATE OPENED"))
            entry_px = _parse_pct(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE")) or 0.0
            if not sym or entry_dt is None or entry_px <= 0:
                continue
            pnl = _parse_pct(raw.get("PNL_PCT") or raw.get("PNL %"))
            ann = _parse_pct(raw.get("ANN_ROR_PCT") or raw.get("ANN ROR PCT"))
            days = _parse_pct(raw.get("DAYS_HELD") or raw.get("DAYS HELD"))
            ym = yearly_low_metrics(sym, entry_dt, entry_px, ohlc_dir)
            dist = ym["dist_to_52w_low_pct"]
            row = {
                "symbol": sym,
                "date_opened": entry_dt.strftime("%Y-%m-%d"),
                "entry_price": entry_px,
                "pnl_pct": pnl,
                "ann_ror_pct": ann,
                "days_held": days,
                "exit_type": (raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip(),
                "dist_to_52w_high_pct": _parse_pct(raw.get("DIST_TO_52W_HIGH_PCT")),
                "high_52w_at_entry": _parse_pct(raw.get("HIGH_52W_AT_ENTRY")),
                "signal_low": _parse_pct(raw.get("SIGNAL_LOW")),
                "risk_pct": _parse_pct(raw.get("RISK_PCT")),
                "is_oos": entry_dt >= pd.Timestamp(IS_CUTOFF),
                **ym,
            }
            for thr in THRESHOLDS:
                row[f"near_{int(thr)}pct"] = dist is not None and dist <= thr
            rows.append(row)

    df = pd.DataFrame(rows)
    df_ok = df[df["warmup_ok"]].copy()
    n_total = len(df)
    n_ok = len(df_ok)
    n_missing = n_total - n_ok

    # Correlations: closer to low = smaller dist_to_52w_low_pct
    corr_pnl = pearson(df_ok["dist_to_52w_low_pct"], df_ok["pnl_pct"])
    corr_ann = pearson(df_ok["dist_to_52w_low_pct"], df_ok["ann_ror_pct"])
    corr_atr_pnl = pearson(df_ok["dist_to_52w_low_atr"], df_ok["pnl_pct"])

    # Group stats by threshold
    group_rows: list[dict[str, Any]] = []
    for thr in THRESHOLDS:
        col = f"near_{int(thr)}pct"
        near = df_ok[df_ok[col]]
        rest = df_ok[~df_ok[col]]
        gs_near = group_stats(near, f"within {thr:.0f}% of 252d low")
        gs_rest = group_stats(rest, f"> {thr:.0f}% above 252d low")
        gs_near["threshold_pct"] = thr
        gs_rest["threshold_pct"] = thr
        group_rows.extend([gs_near, gs_rest])

    # IS / OOS for 10% threshold (middle)
    is_df = df_ok[~df_ok["is_oos"]]
    oos_df = df_ok[df_ok["is_oos"]]
    split_rows = []
    for split_name, split_df in [("IS (<2024)", is_df), ("OOS (>=2024)", oos_df)]:
        for thr in THRESHOLDS:
            col = f"near_{int(thr)}pct"
            split_rows.append({**group_stats(split_df[split_df[col]], f"{split_name} near {int(thr)}%"), "split": split_name, "threshold": thr})
            split_rows.append({**group_stats(split_df[~split_df[col]], f"{split_name} rest"), "split": split_name, "threshold": thr})

    # CSGP historical SB trades
    csgp_hist = df_ok[df_ok["symbol"] == "CSGP"].sort_values("date_opened")
    # CSGP hypothetical 2026-08-17 entry
    csgp_probe = yearly_low_metrics("CSGP", pd.Timestamp("2026-08-17"), 31.26, ohlc_dir)
    csgp_probe["symbol"] = "CSGP"
    csgp_probe["date_opened"] = "2026-08-17"
    csgp_probe["entry_price"] = 31.26
    csgp_probe["note"] = "Hypothetical open (getTarget 2026-08-17); not in Closed book yet"
    csgp_probe["signal_low_user"] = 31.86

    # Console output
    print(f"SB closed: {closed_path.name}")
    print(f"Trades loaded: {n_total}; with 252d warmup: {n_ok}; missing OHLC/warmup: {n_missing}")
    print(f"\nCorrelation (dist_to_52w_low_pct vs outcomes; negative => closer to low associates with higher PnL):")
    print(f"  vs PNL_PCT:     r = {corr_pnl}")
    print(f"  vs ANN_ROR_PCT: r = {corr_ann}")
    print(f"  vs PNL (ATR dist): r = {corr_atr_pnl}")
    print("\nGrouped stats (full book, warmup OK):")
    hdr = f"{'group':32} {'N':>5} {'WR%':>6} {'avgPnL%':>8} {'medPnL%':>8} {'avgAnnROR':>10} {'avgDays':>8}"
    print(hdr)
    print("-" * len(hdr))
    for thr in THRESHOLDS:
        for label_suffix, mask in [("near", True), ("rest", False)]:
            col = f"near_{int(thr)}pct"
            sub = df_ok[df_ok[col]] if mask else df_ok[~df_ok[col]]
            gs = group_stats(sub, "")
            tag = f"{'within' if mask else '>'} {thr:.0f}% 252d low"
            ann_s = f"{gs['avg_ann_ror_pct']:>10.1f}" if gs.get("avg_ann_ror_pct") is not None else f"{'n/a':>10}"
            print(
                f"{tag:32} {gs['N']:5d} {gs['WR_pct']:6.1f} {gs['avg_pnl_pct']:8.2f} "
                f"{gs['med_pnl_pct']:8.2f} {ann_s} {gs['avg_days_held']:8.1f}"
            )

    print(f"\nCSGP SB historical trades in closed book: {len(csgp_hist)}")
    if len(csgp_hist):
        print(csgp_hist[["date_opened", "entry_price", "pnl_pct", "dist_to_52w_low_pct", "dist_to_52w_high_pct"]].to_string(index=False))
    print("\nCSGP 2026-08-17 probe @ $31.26:")
    print(json.dumps(csgp_probe, indent=2, default=str))

    # Write CSV detail
    detail_csv = out_dir / "sb_near_yearly_low_trades.csv"
    df.to_csv(detail_csv, index=False)

    group_csv = out_dir / "sb_near_yearly_low_groups.csv"
    pd.DataFrame(group_rows).to_csv(group_csv, index=False)

    # HTML report
    html_path = out_dir / "sb_near_yearly_low_report.html"
    gen_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    group_table_rows = ""
    for thr in THRESHOLDS:
        for mask, tag in [(True, f"Within {int(thr)}% of 252d low"), (False, f"> {int(thr)}% above 252d low")]:
            col = f"near_{int(thr)}pct"
            sub = df_ok[df_ok[col]] if mask else df_ok[~df_ok[col]]
            gs = group_stats(sub, tag)
            ann = gs.get("avg_ann_ror_pct")
            group_table_rows += (
                f"<tr><td>{html.escape(tag)}</td>"
                f"<td>{gs['N']}</td>"
                f"<td>{gs['WR_pct']:.1f}</td>"
                f"<td>{gs['avg_pnl_pct']:.2f}</td>"
                f"<td>{gs['med_pnl_pct']:.2f}</td>"
                f"<td>{ann if ann is not None else 'n/a'}</td>"
                f"<td>{gs['avg_days_held']:.1f}</td></tr>\n"
            )

    csgp_rows = ""
    for _, r in csgp_hist.iterrows():
        csgp_rows += (
            f"<tr><td>{r['date_opened']}</td><td>{r['entry_price']:.2f}</td>"
            f"<td>{r['pnl_pct']:.2f}</td><td>{r['dist_to_52w_low_pct']:.2f}</td>"
            f"<td>{r.get('dist_to_52w_high_pct') or 'n/a'}</td><td>{r['exit_type']}</td></tr>\n"
        )
    if not csgp_rows:
        csgp_rows = "<tr><td colspan='6'>No CSGP rows in current Closed export (check universe stamp).</td></tr>"

    probe_dist = csgp_probe.get("dist_to_52w_low_pct")
    probe_low = csgp_probe.get("low_52w")
    near_flags = ", ".join(
        f"{int(t)}%: {'YES' if probe_dist is not None and probe_dist <= t else 'no'}"
        for t in THRESHOLDS
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>SB near 252d low explore</title>
<style>
body{{font-family:system-ui,sans-serif;margin:1.5rem;max-width:1100px;line-height:1.45}}
table.sortable{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:14px}}
td,th{{border:1px solid #ccc;padding:6px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS}
.note{{color:#444;font-size:0.95rem}}
</style></head><body>
<h1>SB: entry proximity to 252-day low (exploratory)</h1>
<p class="note">Generated {html.escape(gen_ts)}. Source: {html.escape(str(closed_path))}. OHLC: {html.escape(str(ohlc_dir))}. Research only — not gold promotion.</p>
<h2>Methodology</h2>
<ul>
<li>252 trading-day rolling minimum low through entry date (prior bars incl. entry day).</li>
<li><code>dist_to_52w_low_pct</code> = (entry − low_252) / low_252 × 100. Smaller = closer to yearly low.</li>
<li>Near-low flags: dist ≤ 5%, 10%, 15%. Also report ATR-normalized distance.</li>
<li>IS/OOS split: entry &lt; 2024-01-01 vs ≥ 2024-01-01.</li>
<li>Closed book already has <code>DIST_TO_52W_HIGH_PCT</code> (distance below 52w high) — complementary, not identical.</li>
</ul>
<p>Trades: {n_total} total; {n_ok} with 252d warmup; {n_missing} excluded (missing OHLC or &lt;252 bars).</p>
<h2>Correlations</h2>
<p>dist_to_52w_low_pct vs PNL_PCT: <strong>r = {corr_pnl}</strong> (negative ⇒ closer to low ↔ higher PnL)<br>
dist_to_52w_low_pct vs ANN_ROR_PCT: <strong>r = {corr_ann}</strong><br>
dist_to_52w_low_atr vs PNL_PCT: <strong>r = {corr_atr_pnl}</strong></p>
<h2>Grouped outcomes (click headers to sort)</h2>
<p class="note">Click column headers to sort.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Group", "text")}{sortable_th("N", "num")}{sortable_th("WR%", "num")}{sortable_th("Avg PnL%", "num")}{sortable_th("Med PnL%", "num")}{sortable_th("Avg Ann ROR%", "num")}{sortable_th("Avg days", "num")}
</tr></thead>
<tbody>
{group_table_rows}
</tbody></table>
<h2>CSGP</h2>
<h3>Historical SB closed trades</h3>
<table class="sortable"><thead><tr>
{sortable_th("Entry", "date")}{sortable_th("Entry $", "num")}{sortable_th("PnL%", "num")}{sortable_th("Dist 252d low %", "num")}{sortable_th("Dist 52w high %", "num")}{sortable_th("Exit", "text")}
</tr></thead><tbody>{csgp_rows}</tbody></table>
<h3>2026-08-17 probe (getTarget example)</h3>
<ul>
<li>Entry $31.26; user signal low $31.86</li>
<li>252d low at entry: {probe_low if probe_low is not None else 'n/a'}</li>
<li>Dist to 252d low: {f"{probe_dist:.2f}%" if probe_dist is not None else 'n/a'}</li>
<li>Near-low flags: {near_flags}</li>
</ul>
<h2>Caveats</h2>
<ul>
<li>Exploratory — threshold choice is not pre-registered; report multiple cutoffs.</li>
<li>Selection bias if tuning threshold on same book.</li>
<li>OOS N may be small for near-low buckets.</li>
<li>CSGP 2026 entry is illustrative; not a closed trade outcome.</li>
<li>SB DNA tracks 52w <em>high</em> distance at trigger, not low — this analysis adds low-side lens.</li>
</ul>
<p>Optional formal test: stamp <code>sb_near_yearly_low_ab</code> with frozen entry gate on max dist-to-52w-low.</p>
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>"""
    html_path.write_text(html_body, encoding="utf-8")

    print(f"\nWrote: {detail_csv}")
    print(f"Wrote: {group_csv}")
    print(f"Wrote: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
