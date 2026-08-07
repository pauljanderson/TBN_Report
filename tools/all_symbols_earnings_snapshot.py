#!/usr/bin/env python3
"""Full-universe symbol info + latest earnings snapshot from fundamentals cache.

Dumps every symbol in ``yf_symbol_info`` (prefer cache; no batch Yahoo fetch by
default). Joins latest quarterly EPS row and latest/next earnings dates.

Outputs
-------
  drive/paul_experiments/All_Symbols_Earnings_Snapshot.html
  drive/paul_experiments/All_Symbols_Earnings_Snapshot.csv

Usage
-----
  python tools/all_symbols_earnings_snapshot.py
  python tools/all_symbols_earnings_snapshot.py --as-of 2026-08-07
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analysis.fundamentals_yfinance import ensure_schema  # noqa: E402

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments"
DEFAULT_DATA_DIR = ROOT / "data" / "newdata" / "data"

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

COLUMNS = [
    "symbol",
    "market_cap",
    "float_shares",
    "inst_pct",
    "roe",
    "shares_short",
    "shares_short_prior_month",
    "date_short_interest",
    "shares_short_previous_month_date",
    "short_ratio",
    "short_percent_of_float",
    "shares_percent_shares_out",
    "sector",
    "industry",
    "as_of",
    "fetched_at",
    "latest_period_end",
    "eps_actual",
    "eps_estimate_q",
    "surprise_pct_q",
    "latest_earnings_date",
    "latest_eps_estimate",
    "latest_eps_reported",
    "latest_surprise_pct",
    "next_earnings_date",
    "has_ohlc_csv",
]


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _fmt_cell(v: Any, kind: str) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    if isinstance(v, (pd.Timestamp, datetime, date)):
        if pd.isna(v):
            return "—"
        if isinstance(v, datetime):
            return html_mod.escape(v.strftime("%Y-%m-%d %H:%M"))
        return html_mod.escape(str(v)[:10])
    if kind == "text":
        return html_mod.escape(str(v))
    if kind == "bool":
        return "Y" if bool(v) else "N"
    if kind == "mcap":
        x = float(v)
        if abs(x) >= 1e12:
            return f"{x/1e12:.2f}T"
        if abs(x) >= 1e9:
            return f"{x/1e9:.2f}B"
        if abs(x) >= 1e6:
            return f"{x/1e6:.1f}M"
        return f"{x:,.0f}"
    if kind == "shares":
        x = float(v)
        if abs(x) >= 1e9:
            return f"{x/1e9:.2f}B"
        if abs(x) >= 1e6:
            return f"{x/1e6:.1f}M"
        return f"{x:,.0f}"
    if kind == "pct_frac":
        return f"{float(v)*100:.2f}%"
    if kind == "roe":
        # ROE often already fraction
        x = float(v)
        if abs(x) <= 5:
            return f"{x*100:.1f}%"
        return f"{x:.2f}"
    if kind == "num":
        return f"{float(v):.4g}"
    return html_mod.escape(str(v))


def _parse_sector_industry(raw_json: Any) -> tuple[Optional[str], Optional[str]]:
    if raw_json is None or (isinstance(raw_json, float) and np.isnan(raw_json)):
        return None, None
    try:
        raw = json.loads(raw_json) if isinstance(raw_json, str) else (raw_json or {})
    except Exception:
        return None, None
    if not isinstance(raw, dict):
        return None, None
    sector = raw.get("sector")
    industry = raw.get("industry")
    return (
        str(sector) if sector else None,
        str(industry) if industry else None,
    )


def normalize_surprise(s: Any) -> Optional[float]:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    v = float(s)
    if abs(v) > 2.0:
        v = v / 100.0
    return v


def build_snapshot(
    db_path: Path,
    *,
    as_of: date,
    data_dir: Path,
) -> tuple[pd.DataFrame, dict]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        info = con.execute(
            """
            SELECT symbol, as_of, market_cap, float_shares, inst_pct, roe,
                   shares_short, shares_short_prior_month, date_short_interest,
                   shares_short_previous_month_date, short_ratio,
                   short_percent_of_float, shares_percent_shares_out,
                   raw_json, fetched_at
            FROM yf_symbol_info
            ORDER BY symbol
            """
        ).fetchdf()

        # Latest quarterly by period_end
        q_latest = con.execute(
            """
            SELECT q.symbol, q.period_end, q.eps_actual, q.eps_estimate, q.surprise_pct
            FROM yf_earnings_quarterly q
            INNER JOIN (
              SELECT symbol, MAX(period_end) AS period_end
              FROM yf_earnings_quarterly
              GROUP BY symbol
            ) m USING (symbol, period_end)
            """
        ).fetchdf()

        # Latest past / on-as_of earnings date
        e_latest = con.execute(
            """
            SELECT e.symbol, e.earnings_date, e.eps_estimate, e.eps_reported, e.surprise_pct
            FROM yf_earnings_dates e
            INNER JOIN (
              SELECT symbol, MAX(earnings_date) AS earnings_date
              FROM yf_earnings_dates
              WHERE earnings_date <= ?
              GROUP BY symbol
            ) m USING (symbol, earnings_date)
            """,
            [as_of],
        ).fetchdf()

        # Next future earnings date
        e_next = con.execute(
            """
            SELECT e.symbol, e.earnings_date AS next_earnings_date
            FROM yf_earnings_dates e
            INNER JOIN (
              SELECT symbol, MIN(earnings_date) AS earnings_date
              FROM yf_earnings_dates
              WHERE earnings_date > ?
              GROUP BY symbol
            ) m USING (symbol, earnings_date)
            """,
            [as_of],
        ).fetchdf()

        n_info = int(con.execute("SELECT COUNT(*) FROM yf_symbol_info").fetchone()[0])
        n_ed_sym = int(
            con.execute("SELECT COUNT(DISTINCT symbol) FROM yf_earnings_dates").fetchone()[0]
        )
        n_q_sym = int(
            con.execute("SELECT COUNT(DISTINCT symbol) FROM yf_earnings_quarterly").fetchone()[0]
        )
    finally:
        con.close()

    ohlc_syms: set[str] = set()
    if data_dir.exists():
        ohlc_syms = {p.stem.upper() for p in data_dir.glob("*.csv")}

    sectors = []
    industries = []
    for raw in info["raw_json"]:
        s, i = _parse_sector_industry(raw)
        sectors.append(s)
        industries.append(i)
    info = info.drop(columns=["raw_json"])
    info["sector"] = sectors
    info["industry"] = industries
    info["has_ohlc_csv"] = info["symbol"].map(lambda s: str(s).upper() in ohlc_syms)

    if len(q_latest):
        q_latest = q_latest.rename(
            columns={
                "period_end": "latest_period_end",
                "eps_estimate": "eps_estimate_q",
                "surprise_pct": "surprise_pct_q",
            }
        )
        q_latest["surprise_pct_q"] = q_latest["surprise_pct_q"].map(normalize_surprise)
        info = info.merge(q_latest, on="symbol", how="left")
    else:
        info["latest_period_end"] = pd.NaT
        info["eps_actual"] = np.nan
        info["eps_estimate_q"] = np.nan
        info["surprise_pct_q"] = np.nan

    if len(e_latest):
        e_latest = e_latest.rename(
            columns={
                "earnings_date": "latest_earnings_date",
                "eps_estimate": "latest_eps_estimate",
                "eps_reported": "latest_eps_reported",
                "surprise_pct": "latest_surprise_pct",
            }
        )
        e_latest["latest_surprise_pct"] = e_latest["latest_surprise_pct"].map(normalize_surprise)
        info = info.merge(e_latest, on="symbol", how="left")
    else:
        info["latest_earnings_date"] = pd.NaT
        info["latest_eps_estimate"] = np.nan
        info["latest_eps_reported"] = np.nan
        info["latest_surprise_pct"] = np.nan

    if len(e_next):
        info = info.merge(e_next, on="symbol", how="left")
    else:
        info["next_earnings_date"] = pd.NaT

    # Column order
    for c in COLUMNS:
        if c not in info.columns:
            info[c] = np.nan
    snap = info[COLUMNS].sort_values("symbol").reset_index(drop=True)

    meta = {
        "n_symbol_info": n_info,
        "n_earnings_dates_symbols": n_ed_sym,
        "n_quarterly_symbols": n_q_sym,
        "n_ohlc_csvs": len(ohlc_syms),
        "n_rows": int(len(snap)),
        "n_with_latest_earnings": int(snap["latest_earnings_date"].notna().sum()),
        "n_with_next_earnings": int(snap["next_earnings_date"].notna().sum()),
        "n_with_quarterly": int(snap["latest_period_end"].notna().sum()),
        "n_with_ohlc": int(snap["has_ohlc_csv"].sum()),
        "n_with_shares_short": int(snap["shares_short"].notna().sum()),
        "n_with_short_percent_of_float": int(snap["short_percent_of_float"].notna().sum()),
        "n_with_short_ratio": int(snap["short_ratio"].notna().sum()),
        "n_with_date_short_interest": int(snap["date_short_interest"].notna().sum()),
        "as_of": as_of,
        "db": db_path,
        "data_dir": data_dir,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return snap, meta


def write_html(snap: pd.DataFrame, meta: dict, out_html: Path) -> None:
    esc = html_mod.escape
    col_meta = [
        ("symbol", "Symbol", "text", "text"),
        ("market_cap", "Market cap", "num", "mcap"),
        ("float_shares", "Float shares", "num", "shares"),
        ("inst_pct", "Inst %", "num", "pct_frac"),
        ("roe", "ROE", "num", "roe"),
        ("shares_short", "Shares short", "num", "shares"),
        ("shares_short_prior_month", "Shares short prior mo", "num", "shares"),
        ("date_short_interest", "Short settle date", "date", "date"),
        ("shares_short_previous_month_date", "Prior short settle", "date", "date"),
        ("short_ratio", "Days to cover", "num", "num"),
        ("short_percent_of_float", "Short % float", "num", "pct_frac"),
        ("shares_percent_shares_out", "Short % shares out", "num", "pct_frac"),
        ("sector", "Sector", "text", "text"),
        ("industry", "Industry", "text", "text"),
        ("as_of", "As of", "date", "date"),
        ("fetched_at", "Fetched at", "date", "date"),
        ("latest_period_end", "Latest period end", "date", "date"),
        ("eps_actual", "EPS actual (q)", "num", "num"),
        ("eps_estimate_q", "EPS est (q)", "num", "num"),
        ("surprise_pct_q", "Surprise (q)", "num", "pct_frac"),
        ("latest_earnings_date", "Latest earnings date", "date", "date"),
        ("latest_eps_estimate", "EPS est (date)", "num", "num"),
        ("latest_eps_reported", "EPS reported", "num", "num"),
        ("latest_surprise_pct", "Surprise (date)", "num", "pct_frac"),
        ("next_earnings_date", "Next earnings date", "date", "date"),
        ("has_ohlc_csv", "Has OHLC CSV", "text", "bool"),
    ]

    ths = "".join(_sortable_th(lab, st) for _, lab, st, _ in col_meta)
    body_rows = []
    for _, row in snap.iterrows():
        tds = []
        for key, _, _, kind in col_meta:
            tds.append(f"<td>{_fmt_cell(row.get(key), kind)}</td>")
        body_rows.append("<tr>" + "".join(tds) + "</tr>")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>All Symbols Earnings Snapshot</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1800px; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
.sub {{ color:#64748b; margin-bottom:16px; line-height:1.5; font-size:0.95rem; }}
.caption {{ font-size:12px; color:#64748b; margin:6px 0 10px; }}
.note {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin:12px 0 20px; font-size:0.92rem; line-height:1.5; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:11px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:5px 7px; text-align:left; white-space:nowrap; }}
th {{ background:#f1f5f9; position:sticky; top:0; }}
{SORTABLE_TH_CSS}
code {{ font-size:11px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
</style></head><body>
<h1>All symbols — fundamentals + latest earnings snapshot</h1>
<p class="sub">
  Generated {esc(meta["generated"])}. As-of {esc(str(meta["as_of"]))}.
  Cache <code>{esc(str(meta["db"]))}</code>.
  OHLC dir <code>{esc(str(meta["data_dir"]))}</code>.
</p>
<div class="note">
  <strong>Coverage (cache only — no batch Yahoo refresh):</strong>
  symbol_info rows = {meta["n_symbol_info"]};
  distinct symbols with earnings_dates = {meta["n_earnings_dates_symbols"]};
  with quarterly = {meta["n_quarterly_symbols"]};
  snapshot rows = {meta["n_rows"]};
  with latest earnings_date ≤ as-of = {meta["n_with_latest_earnings"]};
  with next earnings_date = {meta["n_with_next_earnings"]};
  with latest quarterly = {meta["n_with_quarterly"]};
  with matching OHLC CSV = {meta["n_with_ohlc"]}
  (data dir has {meta["n_ohlc_csvs"]} CSVs).<br>
  Short interest (Yahoo columns on <code>yf_symbol_info</code>):
  shares_short = {meta["n_with_shares_short"]};
  short_percent_of_float = {meta["n_with_short_percent_of_float"]};
  short_ratio (days to cover) = {meta["n_with_short_ratio"]};
  date_short_interest = {meta["n_with_date_short_interest"]}
  of {meta["n_rows"]} rows.
  Pre-migration cache rows stay null until TTL refresh; this report does not
  batch-fetch Yahoo.<br>
  Snapshot only (no full quarterly history in HTML). Surprise shown as percent
  (fraction × 100); |raw|&gt;2 treated as percent-points / 100.
</div>
<p class="caption">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
</div>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    as_of = date.today()
    if args.as_of:
        as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    db = ensure_schema(args.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    snap, meta = build_snapshot(db, as_of=as_of, data_dir=Path(args.data_dir))

    csv_path = out_dir / "All_Symbols_Earnings_Snapshot.csv"
    html_path = out_dir / "All_Symbols_Earnings_Snapshot.html"
    snap.to_csv(csv_path, index=False)
    write_html(snap, meta, html_path)

    print(f"Wrote {html_path}")
    print(f"Wrote {csv_path}")
    print(
        f"rows={meta['n_rows']} latest_earn={meta['n_with_latest_earnings']} "
        f"next={meta['n_with_next_earnings']} quarterly={meta['n_with_quarterly']} "
        f"ohlc={meta['n_with_ohlc']}"
    )
    print(
        f"short_interest: shares_short={meta['n_with_shares_short']} "
        f"short_percent_of_float={meta['n_with_short_percent_of_float']} "
        f"short_ratio={meta['n_with_short_ratio']} "
        f"date_short_interest={meta['n_with_date_short_interest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
