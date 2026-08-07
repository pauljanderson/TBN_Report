#!/usr/bin/env python3
"""Scan stock CSVs for gap-up events (open vs prior close).

Default data dir matches rocket_tbn: data/newdata/data (excludes SPY).

Gap definition (default):
  Open[t] > Close[t-1]
  GAP_PCT = (GAP_O - PREV_C) / PREV_C * 100

Forward performance (trading days after gap day; blank if not enough bars):
  RET_C_ND = (Close[t+N] - GAP_C) / GAP_C * 100
  RET_O_ND = (Close[t+N] - GAP_O) / GAP_O * 100
  Default horizons N = 5, 10, 15, 20

Optional filters:
  --min-gap-pct              minimum GAP_PCT (default 0)
  --min-gap-vs-prev-high     require open > prev high by at least this %%
                             (omit flag = no filter; 0 = open > prev high)
  --horizons                 comma list of forward trading-day horizons
  --symbols                  comma list subset
  --start-date / --end-date  inclusive YYYY-MM-DD window on GAP_DATE
  --out                      CSV path (HTML twin written beside it)

Usage:
  python tools/scan_gap_ups.py
  python tools/scan_gap_ups.py --symbols AAPL,NVDA,TSLA --min-gap-pct 1.0
  python tools/scan_gap_ups.py --start-date 2024-01-01 --end-date 2024-12-31
  python tools/scan_gap_ups.py --min-gap-vs-prev-high 0 --out drive/GapUp_Scan.csv
  python tools/scan_gap_ups.py --horizons 5,10,15,20 --symbols AAPL

Outputs:
  drive/GapUp_Scan_<stamp>.csv
  drive/GapUp_Scan_<stamp>.html  (sortable table)
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "newdata" / "data"
DEFAULT_HORIZONS = (5, 10, 15, 20)

_BASE_COLUMNS = [
    "SYMBOL",
    "GAP_DATE",
    "PREV_DATE",
    "PREV_O",
    "PREV_H",
    "PREV_L",
    "PREV_C",
    "GAP_O",
    "GAP_H",
    "GAP_L",
    "GAP_C",
    "GAP_PCT",
    "FROM_OPEN_HIGH_PCT",
    "FROM_OPEN_LOW_PCT",
    "FROM_OPEN_CLOSE_PCT",
    "GAP_VS_PREV_HIGH_PCT",
    "VOLUME",
]


def _fwd_ret_columns(horizons: Sequence[int]) -> list[str]:
    """RET_C_* then RET_O_* for each horizon (stable column order)."""
    cols: list[str] = []
    for n in horizons:
        cols.append(f"RET_C_{n}D")
    for n in horizons:
        cols.append(f"RET_O_{n}D")
    return cols


def _columns_for(horizons: Sequence[int]) -> list[str]:
    return list(_BASE_COLUMNS) + _fwd_ret_columns(horizons)


# Default column list (used when horizons = DEFAULT_HORIZONS)
COLUMNS = _columns_for(DEFAULT_HORIZONS)

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

# Column -> data-sort type for HTML
_COL_SORT_BASE = {
    "SYMBOL": "text",
    "GAP_DATE": "date",
    "PREV_DATE": "date",
    "PREV_O": "num",
    "PREV_H": "num",
    "PREV_L": "num",
    "PREV_C": "num",
    "GAP_O": "num",
    "GAP_H": "num",
    "GAP_L": "num",
    "GAP_C": "num",
    "GAP_PCT": "num",
    "FROM_OPEN_HIGH_PCT": "num",
    "FROM_OPEN_LOW_PCT": "num",
    "FROM_OPEN_CLOSE_PCT": "num",
    "GAP_VS_PREV_HIGH_PCT": "num",
    "VOLUME": "num",
}


def _col_sort_map(horizons: Sequence[int]) -> dict[str, str]:
    m = dict(_COL_SORT_BASE)
    for col in _fwd_ret_columns(horizons):
        m[col] = "num"
    return m


# Default sort map (horizons = DEFAULT_HORIZONS)
_COL_SORT = _col_sort_map(DEFAULT_HORIZONS)


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _stamp() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S")


def _parse_symbols(raw: Optional[str]) -> Optional[set[str]]:
    if not raw or not str(raw).strip():
        return None
    return {s.strip().upper() for s in str(raw).split(",") if s.strip()}


def _parse_horizons(raw: Optional[str]) -> tuple[int, ...]:
    """Parse comma-separated positive ints; default DEFAULT_HORIZONS if empty."""
    if not raw or not str(raw).strip():
        return tuple(DEFAULT_HORIZONS)
    out: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        n = int(part)
        if n <= 0:
            raise ValueError(f"horizon must be positive, got {n}")
        if n not in out:
            out.append(n)
    if not out:
        return tuple(DEFAULT_HORIZONS)
    return tuple(out)


def _list_csv_paths(data_dir: Path, symbols: Optional[set[str]]) -> list[Path]:
    paths = sorted(data_dir.glob("*.csv"))
    out: list[Path] = []
    for p in paths:
        sym = p.stem.upper()
        if sym == "SPY":
            continue
        if symbols is not None and sym not in symbols:
            continue
        out.append(p)
    return out


def _scan_symbol(
    path: Path,
    *,
    min_gap_pct: float,
    min_gap_vs_prev_high: Optional[float],
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """Vectorized gap-up scan for one symbol CSV. Returns empty frame if none."""
    cols = _columns_for(horizons)
    try:
        df = pd.read_csv(path, usecols=lambda c: c in {
            "Date", "Open", "High", "Low", "Close", "Volume",
            "date", "open", "high", "low", "close", "volume",
        }, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=cols)

    if df.empty or len(df) < 2:
        return pd.DataFrame(columns=cols)

    lower_map = {str(c).strip().lower(): c for c in df.columns}
    colmap = {}
    for want in ("Date", "Open", "High", "Low", "Close", "Volume"):
        src = lower_map.get(want.lower())
        if src is not None:
            colmap[src] = want
    df = df.rename(columns=colmap)

    need = ["Date", "Open", "High", "Low", "Close"]
    if any(c not in df.columns for c in need):
        return pd.DataFrame(columns=cols)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date", ignore_index=True)
    for c in ("Open", "High", "Low", "Close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    has_vol = "Volume" in df.columns
    if has_vol:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")

    if len(df) < 2:
        return pd.DataFrame(columns=cols)

    o = df["Open"].to_numpy(dtype=np.float64)
    h = df["High"].to_numpy(dtype=np.float64)
    l = df["Low"].to_numpy(dtype=np.float64)
    c = df["Close"].to_numpy(dtype=np.float64)
    dates = df["Date"].to_numpy()
    vol = df["Volume"].to_numpy(dtype=np.float64) if has_vol else None
    n_bars = len(c)

    # t vs t-1
    prev_c = c[:-1]
    gap_o = o[1:]
    valid = (
        np.isfinite(prev_c)
        & np.isfinite(gap_o)
        & (prev_c > 0)
        & (gap_o > 0)
        & (gap_o > prev_c)  # gap up
    )
    gap_pct = np.where(valid, (gap_o - prev_c) / prev_c * 100.0, np.nan)
    if min_gap_pct > 0:
        valid = valid & (gap_pct >= min_gap_pct)
    else:
        # still require finite gap_pct
        valid = valid & np.isfinite(gap_pct)

    prev_h = h[:-1]
    gap_vs_prev_high = np.where(
        np.isfinite(prev_h) & (prev_h > 0) & np.isfinite(gap_o),
        (gap_o - prev_h) / prev_h * 100.0,
        np.nan,
    )
    if min_gap_vs_prev_high is not None:
        # open > prev high by at least threshold (0 => any true gap above prior high)
        valid = valid & np.isfinite(gap_vs_prev_high) & (gap_vs_prev_high > min_gap_vs_prev_high)

    if start is not None or end is not None:
        gap_dates = pd.to_datetime(dates[1:])
        if start is not None:
            valid = valid & (gap_dates >= start)
        if end is not None:
            valid = valid & (gap_dates <= end)

    idx = np.nonzero(valid)[0]
    if idx.size == 0:
        return pd.DataFrame(columns=cols)

    # idx is index into the t-1 / t parallel arrays (length n-1)
    # gap day in original series is at position gap_day_i = idx + 1
    gap_o_v = gap_o[idx]
    gap_h_v = h[1:][idx]
    gap_l_v = l[1:][idx]
    gap_c_v = c[1:][idx]
    # Avoid div0 (already filtered gap_o > 0)
    from_hi = (gap_h_v - gap_o_v) / gap_o_v * 100.0
    from_lo = (gap_l_v - gap_o_v) / gap_o_v * 100.0
    from_cl = (gap_c_v - gap_o_v) / gap_o_v * 100.0

    gap_dates_str = pd.to_datetime(dates[1:][idx]).strftime("%Y-%m-%d")
    prev_dates_str = pd.to_datetime(dates[:-1][idx]).strftime("%Y-%m-%d")

    out = {
        "SYMBOL": path.stem.upper(),
        "GAP_DATE": gap_dates_str,
        "PREV_DATE": prev_dates_str,
        "PREV_O": o[:-1][idx],
        "PREV_H": prev_h[idx],
        "PREV_L": l[:-1][idx],
        "PREV_C": prev_c[idx],
        "GAP_O": gap_o_v,
        "GAP_H": gap_h_v,
        "GAP_L": gap_l_v,
        "GAP_C": gap_c_v,
        "GAP_PCT": gap_pct[idx],
        "FROM_OPEN_HIGH_PCT": from_hi,
        "FROM_OPEN_LOW_PCT": from_lo,
        "FROM_OPEN_CLOSE_PCT": from_cl,
        "GAP_VS_PREV_HIGH_PCT": gap_vs_prev_high[idx],
        "VOLUME": vol[1:][idx] if vol is not None else np.full(idx.size, np.nan),
    }

    # Forward closes: Close[gap_day + N]; blank/NaN if not enough future bars
    gap_day_i = idx + 1
    for n in horizons:
        fwd_i = gap_day_i + n
        ok = fwd_i < n_bars
        fwd_c = np.full(idx.size, np.nan, dtype=np.float64)
        if np.any(ok):
            fwd_c[ok] = c[fwd_i[ok]]
        ret_c = np.where(
            np.isfinite(fwd_c) & np.isfinite(gap_c_v) & (gap_c_v > 0),
            (fwd_c - gap_c_v) / gap_c_v * 100.0,
            np.nan,
        )
        ret_o = np.where(
            np.isfinite(fwd_c) & np.isfinite(gap_o_v) & (gap_o_v > 0),
            (fwd_c - gap_o_v) / gap_o_v * 100.0,
            np.nan,
        )
        out[f"RET_C_{n}D"] = ret_c
        out[f"RET_O_{n}D"] = ret_o

    return pd.DataFrame(out)[cols]


def scan_all(
    data_dir: Path,
    *,
    symbols: Optional[set[str]] = None,
    min_gap_pct: float = 0.0,
    min_gap_vs_prev_high: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    cols = _columns_for(horizons)
    paths = _list_csv_paths(data_dir, symbols)
    start = pd.Timestamp(start_date) if start_date else None
    end = pd.Timestamp(end_date) if end_date else None
    frames: list[pd.DataFrame] = []
    n = len(paths)
    for i, p in enumerate(paths, 1):
        if i == 1 or i == n or i % 100 == 0:
            print(f"  [{i}/{n}] {p.stem}", flush=True)
        part = _scan_symbol(
            p,
            min_gap_pct=min_gap_pct,
            min_gap_vs_prev_high=min_gap_vs_prev_high,
            start=start,
            end=end,
            horizons=horizons,
        )
        if not part.empty:
            frames.append(part)
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["GAP_DATE", "SYMBOL", "GAP_PCT"], ascending=[True, True, False], ignore_index=True)


def _fmt_cell(col: str, val) -> str:
    if val is None or (isinstance(val, float) and not np.isfinite(val)) or pd.isna(val):
        return ""
    if col == "VOLUME":
        try:
            return f"{int(round(float(val))):,}"
        except (TypeError, ValueError):
            return ""
    if col in (
        "PREV_O", "PREV_H", "PREV_L", "PREV_C",
        "GAP_O", "GAP_H", "GAP_L", "GAP_C",
    ):
        return f"{float(val):.4f}"
    if (
        col.endswith("_PCT")
        or col.startswith("RET_C_")
        or col.startswith("RET_O_")
        or col in (
            "GAP_PCT", "FROM_OPEN_HIGH_PCT", "FROM_OPEN_LOW_PCT",
            "FROM_OPEN_CLOSE_PCT", "GAP_VS_PREV_HIGH_PCT",
        )
    ):
        return f"{float(val):.4f}"
    return html_mod.escape(str(val))


def write_html(
    df: pd.DataFrame,
    path: Path,
    *,
    title: str,
    meta_lines: Iterable[str],
    columns: Optional[Sequence[str]] = None,
    col_sort: Optional[dict[str, str]] = None,
) -> None:
    cols = list(columns) if columns is not None else list(COLUMNS)
    sort_map = col_sort if col_sort is not None else _COL_SORT
    head = "".join(_sortable_th(c, sort_map.get(c, "text")) for c in cols)
    # Cap HTML body for browser sanity; full data always in CSV
    max_rows = 50_000
    view = df.head(max_rows) if len(df) > max_rows else df
    body_parts: list[str] = []
    for row in view.itertuples(index=False):
        cells = "".join(f"<td>{_fmt_cell(cols[i], row[i])}</td>" for i in range(len(cols)))
        body_parts.append(f"<tr>{cells}</tr>")
    body = "\n".join(body_parts)
    meta = "<br>\n".join(html_mod.escape(x) for x in meta_lines)
    note = ""
    if len(df) > max_rows:
        note = (
            f"<p><em>HTML shows first {max_rows:,} of {len(df):,} rows; "
            f"full set in CSV twin.</em></p>"
        )
    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html_mod.escape(title)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.25rem;color:#0f172a;background:#f8fafc}}
h1{{font-size:1.35rem;margin:0 0 .5rem}}
.meta{{color:#475569;font-size:.9rem;margin-bottom:1rem;line-height:1.45}}
table.sortable{{border-collapse:collapse;width:100%;font-size:.8rem;background:#fff}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:.28rem .4rem;text-align:right}}
table.sortable th{{background:#f1f5f9;text-align:left;position:sticky;top:0;z-index:1}}
table.sortable td:nth-child(1),table.sortable td:nth-child(2),table.sortable td:nth-child(3){{text-align:left}}
{SORTABLE_TH_CSS}
.caption{{color:#64748b;font-size:.85rem;margin:.4rem 0 1rem}}
</style></head><body>
<h1>{html_mod.escape(title)}</h1>
<div class="meta">{meta}</div>
<p class="caption">Click column headers to sort. Gap up = Open[t] &gt; Close[t-1].
RET_C_ND = %% from gap close; RET_O_ND = %% from gap open (N trading days later).</p>
{note}
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{body}
</tbody>
</table>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Scan stock CSVs for gap-up events (Open[t] > Close[t-1]).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/scan_gap_ups.py --symbols AAPL,NVDA --min-gap-pct 1
  python tools/scan_gap_ups.py --min-gap-vs-prev-high 0 --start-date 2023-01-01
  python tools/scan_gap_ups.py --data-dir data/newdata/data --out drive/GapUp_Scan.csv
  python tools/scan_gap_ups.py --horizons 5,10,15,20 --symbols AAPL
        """.strip(),
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="OHLCV CSV directory (default: data/newdata/data)",
    )
    ap.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbol subset (default: all CSVs except SPY)",
    )
    ap.add_argument(
        "--min-gap-pct",
        type=float,
        default=0.0,
        help="Minimum GAP_PCT = (open-prev_close)/prev_close*100 (default: 0)",
    )
    ap.add_argument(
        "--min-gap-vs-prev-high",
        type=float,
        default=None,
        help=(
            "Optional: require GAP_VS_PREV_HIGH_PCT > this value "
            "(0 = open must be strictly above prior high). Omit = no filter."
        ),
    )
    ap.add_argument("--start-date", default="", help="Inclusive GAP_DATE start YYYY-MM-DD")
    ap.add_argument("--end-date", default="", help="Inclusive GAP_DATE end YYYY-MM-DD")
    ap.add_argument(
        "--horizons",
        default="5,10,15,20",
        help=(
            "Comma-separated forward trading-day horizons for RET_C_ND / RET_O_ND "
            "(default: 5,10,15,20)"
        ),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV path (default: drive/GapUp_Scan_<stamp>.csv); HTML twin beside it",
    )
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    data_dir: Path = args.data_dir
    if not data_dir.is_absolute():
        data_dir = (ROOT / data_dir).resolve()
    if not data_dir.is_dir():
        print(f"ERROR: data dir not found: {data_dir}", file=sys.stderr)
        return 1

    try:
        horizons = _parse_horizons(args.horizons)
    except ValueError as e:
        print(f"ERROR: invalid --horizons: {e}", file=sys.stderr)
        return 1

    cols = _columns_for(horizons)
    sort_map = _col_sort_map(horizons)

    symbols = _parse_symbols(args.symbols)
    stamp = _stamp()
    out_csv: Path = args.out if args.out else (ROOT / "drive" / f"GapUp_Scan_{stamp}.csv")
    if not out_csv.is_absolute():
        out_csv = (ROOT / out_csv).resolve()
    out_html = out_csv.with_suffix(".html")

    print(f"Scanning {data_dir}")
    print(f"  min_gap_pct={args.min_gap_pct}  min_gap_vs_prev_high={args.min_gap_vs_prev_high}")
    print(f"  horizons={','.join(str(h) for h in horizons)}")
    if symbols:
        print(f"  symbols={sorted(symbols)}")
    if args.start_date or args.end_date:
        print(f"  dates={args.start_date or '...'} .. {args.end_date or '...'}")

    df = scan_all(
        data_dir,
        symbols=symbols,
        min_gap_pct=float(args.min_gap_pct),
        min_gap_vs_prev_high=args.min_gap_vs_prev_high,
        start_date=args.start_date or None,
        end_date=args.end_date or None,
        horizons=horizons,
    )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    meta = [
        f"Rows: {len(df):,}",
        f"Symbols scanned filter: {', '.join(sorted(symbols)) if symbols else 'ALL (excl. SPY)'}",
        f"min_gap_pct={args.min_gap_pct}",
        f"min_gap_vs_prev_high={args.min_gap_vs_prev_high}",
        f"horizons={','.join(str(h) for h in horizons)}",
        f"start_date={args.start_date or '(none)'}  end_date={args.end_date or '(none)'}",
        f"data_dir={data_dir}",
        f"csv={out_csv}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
    ]
    write_html(
        df, out_html, title="Gap-Up Scan", meta_lines=meta,
        columns=cols, col_sort=sort_map,
    )

    print(f"Wrote {len(df):,} rows -> {out_csv}")
    print(f"HTML twin -> {out_html}")
    if not df.empty:
        show_cols = [
            "SYMBOL", "GAP_DATE", "GAP_O", "GAP_C", "GAP_PCT",
            *[f"RET_C_{n}D" for n in horizons],
            *[f"RET_O_{n}D" for n in horizons],
        ]
        sample = df.sort_values("GAP_PCT", ascending=False).head(3)
        print("\nTop 3 by GAP_PCT (with forward rets):")
        with pd.option_context("display.max_columns", 30, "display.width", 200):
            print(sample[show_cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
