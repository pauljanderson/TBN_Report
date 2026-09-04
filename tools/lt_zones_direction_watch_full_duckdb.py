#!/usr/bin/env python3
"""Full-universe LT zones direction scores from DuckDB OHLCV (research).

Scores every distinct symbol in ``data/ohlcv.duckdb`` (table ``prices``) using
``tools/lt_zones_direction_watch.score_symbol``. Skips/flags missing daily,
short history, empty zones, etc. via a ``status`` column.

Research only — NOT financial advice, NOT KEEP, NOT DailyRun.

Example:
  python tools/lt_zones_direction_watch_full_duckdb.py
  python tools/lt_zones_direction_watch_full_duckdb.py --limit 50
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
_SA = _REPO / "stock_analysis"
for _p in (_SA, _REPO, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from intraday_1m import DEFAULT_1M_DIR  # noqa: E402
import lt_zones_daily_to_15m as lt  # noqa: E402
import lt_zones_direction_watch as watch  # noqa: E402

DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"
DEFAULT_STAMP = _REPO / "drive" / "paul_experiments" / "lt_zones_direction_watch_20260824"
DEFAULT_DAILY = _REPO / "data" / "newdata" / "data"
SCORE_COLS = [
    "symbol",
    "status",
    "status_detail",
    "has_daily_csv",
    "has_1m",
    "n_daily_bars",
    "universe",
    "price",
    "price_src",
    "price_ts",
    "daily_last",
    "day_ret_pct",
    "day_loc",
    "prior_loc",
    "yr_pos",
    "dist_yl_pct",
    "dist_yh_pct",
    "yl",
    "yh",
    "poc",
    "near_support",
    "near_resist",
    "d_sup_pct",
    "d_res_pct",
    "up_score",
    "down_score",
    "net_score",
    "lean",
    "confidence",
    "reasons_up",
    "reasons_down",
    "n_zones",
]


def list_duckdb_symbols(db_path: Path, table: str = "prices") -> list[str]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            f"SELECT DISTINCT symbol FROM {table} WHERE symbol IS NOT NULL ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    return [str(r[0]).strip().upper() for r in rows if str(r[0]).strip()]


def _diagnose_skip(
    symbol: str,
    *,
    data_dir: Path,
    in_dir: Path,
) -> dict:
    csv_path = data_dir / f"{symbol}.csv"
    has_csv = csv_path.is_file()
    has_1m = (in_dir / f"{symbol}.parquet").is_file()
    base = {
        "symbol": symbol,
        "universe": "DUCKDB",
        "has_daily_csv": has_csv,
        "has_1m": has_1m,
        "n_daily_bars": 0,
    }
    if not has_csv:
        return {
            **base,
            "status": "skipped_missing_daily",
            "status_detail": f"no {csv_path.name}",
        }
    try:
        daily = lt._load_daily(symbol, data_dir)
    except Exception as e:
        return {
            **base,
            "status": "skipped_daily_load_error",
            "status_detail": str(e)[:200],
        }
    n = len(daily)
    base["n_daily_bars"] = n
    if n < 60:
        return {
            **base,
            "status": "skipped_short_history",
            "status_detail": f"n_daily={n} < 60",
        }
    try:
        zones = lt.compute_lt_zones(daily, symbol, include_lvn=False, max_swing=6)
    except Exception as e:
        return {
            **base,
            "status": "skipped_zone_error",
            "status_detail": str(e)[:200],
        }
    if not zones:
        return {
            **base,
            "status": "skipped_no_zones",
            "status_detail": "compute_lt_zones returned empty",
        }
    return {
        **base,
        "status": "skipped_score_none",
        "status_detail": "score_symbol returned None after zones ok",
    }


def score_one(
    symbol: str,
    *,
    data_dir: Path,
    in_dir: Path,
    near_pct: float,
) -> dict:
    has_csv = (data_dir / f"{symbol}.csv").is_file()
    has_1m = (in_dir / f"{symbol}.parquet").is_file()
    if not has_csv:
        return _diagnose_skip(symbol, data_dir=data_dir, in_dir=in_dir)

    try:
        row = watch.score_symbol(
            symbol,
            data_dir=data_dir,
            in_dir=in_dir,
            near_pct=near_pct,
            univ_tags=["DUCKDB"],
        )
    except Exception as e:
        out = _diagnose_skip(symbol, data_dir=data_dir, in_dir=in_dir)
        out["status"] = "skipped_exception"
        out["status_detail"] = str(e)[:200]
        return out

    if row is None:
        return _diagnose_skip(symbol, data_dir=data_dir, in_dir=in_dir)

    # Count bars for scored rows
    n_bars = 0
    try:
        n_bars = len(lt._load_daily(symbol, data_dir))
    except Exception:
        n_bars = 0

    status = "scored"
    detail = ""
    if not has_1m:
        status = "scored_daily_only"
        detail = "no 1m parquet; price from daily_close fallback"

    return {
        **row,
        "status": status,
        "status_detail": detail,
        "has_daily_csv": has_csv,
        "has_1m": has_1m,
        "n_daily_bars": n_bars,
    }


def write_readme(path: Path, meta: dict) -> None:
    skip_lines = "\n".join(
        f"| `{k}` | {v} |" for k, v in sorted(meta["status_counts"].items()) if k != "scored"
    )
    if not skip_lines.strip():
        skip_lines = "| — | 0 |"
    path.write_text(
        f"""# Full DuckDB direction scores — research note

**Stamp:** `lt_zones_direction_watch_20260824`  
**As-of:** {meta['asof']}  
**Status:** research heuristic only — **not** financial advice, **not** KEEP, **not** DailyRun.

## DuckDB source

| Item | Value |
|------|-------|
| Path | `{meta['db_path']}` |
| Table | `{meta['db_table']}` |
| Schema | `symbol, date, open, high, low, close, volume, source_file, loaded_at` |
| N unique symbols (universe) | **{meta['n_universe']}** |
| N attempted | **{meta['n_attempted']}** |
| N scored (status starts with `scored`) | **{meta['n_scored']}** |
| N skipped / flagged | **{meta['n_skipped']}** |
| Daily CSV dir | `{meta['data_dir']}` |
| 1m parquet dir | `{meta['in_dir']}` |
| Near threshold | {meta['near_pct'] * 100:.1f}% |
| Scorer | `tools/lt_zones_direction_watch.score_symbol` |

Other DuckDB files in repo (not used as this universe): `drive/brt_profile.duckdb` (pipeline timings), `drive/fundamentals_cache.duckdb` (yfinance fundamentals), plus many run-local `brt_profile.duckdb` under experiment folders.

## Status counts

| status | N |
|--------|---|
{chr(10).join(f'| `{k}` | {v} |' for k, v in sorted(meta['status_counts'].items()))}

### Skipped / why

{skip_lines}

## Outputs

- `direction_scores_full_duckdb.csv` — full book (scored + skipped rows)
- `direction_scores_full_duckdb.html` — thin sortable index of scored rows
- This note: `README_FULL_DUCKDB.md`

## Decision

**Research-only.** No adoption / no DailyRun wire.
""",
        encoding="utf-8",
    )


def write_html(path: Path, df: pd.DataFrame, meta: dict) -> None:
    scored = df[df["status"].astype(str).str.startswith("scored")].copy()
    scored = scored.sort_values("net_score", ascending=False)
    cols = [
        ("symbol", "Symbol", "text"),
        ("status", "Status", "text"),
        ("net_score", "Net", "num"),
        ("up_score", "Up", "num"),
        ("down_score", "Down", "num"),
        ("lean", "Lean", "text"),
        ("confidence", "Conf", "text"),
        ("price", "Price", "num"),
        ("day_ret_pct", "Day%", "num"),
        ("yr_pos", "YrPos", "num"),
        ("near_support", "Near support", "text"),
        ("near_resist", "Near resist", "text"),
        ("poc", "POC", "num"),
        ("has_1m", "Has1m", "text"),
        ("price_src", "PxSrc", "text"),
    ]
    head = "".join(watch._sortable_th(lab, st) for _, lab, st in cols)

    def _cell(v, numeric: bool) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        if numeric:
            try:
                return f"{float(v):.4g}"
            except (TypeError, ValueError):
                return html_mod.escape(str(v))
        return html_mod.escape(str(v))

    body_rows = []
    for r in scored.itertuples(index=False):
        d = r._asdict() if hasattr(r, "_asdict") else dict(zip(scored.columns, r))
        tds = []
        for c, _, st in cols:
            num = st == "num"
            cls = ' class="num"' if num else ""
            tds.append(f"<td{cls}>{_cell(d.get(c), num)}</td>")
        body_rows.append("<tr>" + "".join(tds) + "</tr>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Direction scores — full DuckDB</title>
<style>
  :root {{ --bg:#f7f5f0; --ink:#1c1b19; --muted:#5c584f; --line:#d9d4c8; }}
  body {{ font-family: "Segoe UI", system-ui, sans-serif; margin:0; background:var(--bg); color:var(--ink); }}
  main {{ max-width: 1280px; margin: 0 auto; padding: 1.25rem 1rem 3rem; }}
  h1 {{ font-size: 1.35rem; margin: 0 0 0.35rem; }}
  .sub {{ color: var(--muted); font-size: 0.95rem; }}
  .disclaimer {{ background:#fff3e0; border:1px solid #ffcc80; padding:0.75rem 1rem; border-radius:6px; margin:1rem 0; }}
  table.sortable {{ width:100%; border-collapse:collapse; background:#fff; font-size:0.82rem; }}
  table.sortable th, table.sortable td {{ border-bottom:1px solid var(--line); padding:0.35rem 0.4rem; text-align:left; }}
  table.sortable th {{ background:#efece4; position:sticky; top:0; z-index:1; }}
  td.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
  {watch.SORTABLE_TH_CSS}
</style>
</head>
<body>
<main>
<h1>LT zones direction scores — full DuckDB universe</h1>
<p class="sub">As-of {html_mod.escape(meta['asof'])} · universe {meta['n_universe']} · scored {meta['n_scored']} · skipped {meta['n_skipped']} · CSV <a href="direction_scores_full_duckdb.csv">direction_scores_full_duckdb.csv</a> · Click column headers to sort</p>
<div class="disclaimer"><strong>Research only — not financial advice.</strong> Same heuristic as BRT∪RL watch; expanded to all symbols in <code>data/ohlcv.duckdb</code>.</div>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{chr(10).join(body_rows)}
</tbody>
</table>
</main>
{watch._SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Full DuckDB LT direction scores (research)")
    ap.add_argument("--db-path", default=str(DEFAULT_DB))
    ap.add_argument("--db-table", default="prices")
    ap.add_argument("--out-dir", default=str(DEFAULT_STAMP))
    ap.add_argument("--data-dir", default=str(DEFAULT_DAILY))
    ap.add_argument("--in-dir", default=str(DEFAULT_1M_DIR))
    ap.add_argument("--near-pct", type=float, default=watch.NEAR_PCT_DEFAULT)
    ap.add_argument("--limit", type=int, default=0, help="Optional cap for smoke tests")
    args = ap.parse_args()

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)
    data_dir = Path(args.data_dir)
    in_dir = Path(args.in_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.is_file():
        print(f"DuckDB not found: {db_path}", file=sys.stderr)
        return 2

    symbols = list_duckdb_symbols(db_path, args.db_table)
    n_universe = len(symbols)
    if args.limit and args.limit > 0:
        symbols = symbols[: int(args.limit)]

    print(
        f"Scoring {len(symbols)}/{n_universe} DuckDB symbols from {db_path} "
        f"(near_pct={args.near_pct})...",
        flush=True,
    )

    rows: list[dict] = []
    for i, s in enumerate(symbols):
        rows.append(
            score_one(
                s,
                data_dir=data_dir,
                in_dir=in_dir,
                near_pct=float(args.near_pct),
            )
        )
        if (i + 1) % 50 == 0 or (i + 1) == len(symbols):
            print(f"  … {i + 1}/{len(symbols)}", flush=True)

    df = pd.DataFrame(rows)
    for c in SCORE_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[SCORE_COLS]
    # Scored first by net, then skips
    scored_mask = df["status"].astype(str).str.startswith("scored")
    df_scored = df[scored_mask].sort_values("net_score", ascending=False)
    df_skip = df[~scored_mask].sort_values("symbol")
    df_out = pd.concat([df_scored, df_skip], ignore_index=True)

    csv_path = out_dir / "direction_scores_full_duckdb.csv"
    html_path = out_dir / "direction_scores_full_duckdb.html"
    readme_path = out_dir / "README_FULL_DUCKDB.md"

    status_counts = Counter(df_out["status"].astype(str).tolist())
    n_scored = int(scored_mask.sum())
    n_skipped = int((~scored_mask).sum())
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meta = {
        "asof": asof,
        "db_path": db_path.as_posix(),
        "db_table": args.db_table,
        "data_dir": data_dir.as_posix(),
        "in_dir": in_dir.as_posix(),
        "near_pct": float(args.near_pct),
        "n_universe": n_universe,
        "n_attempted": len(symbols),
        "n_scored": n_scored,
        "n_skipped": n_skipped,
        "status_counts": dict(status_counts),
    }

    df_out.to_csv(csv_path, index=False)
    write_html(html_path, df_out, meta)
    write_readme(readme_path, meta)

    print(f"Wrote {csv_path}", flush=True)
    print(f"Wrote {html_path}", flush=True)
    print(f"Wrote {readme_path}", flush=True)
    print(f"Universe={n_universe} attempted={len(symbols)} scored={n_scored} skipped={n_skipped}", flush=True)
    print(f"Status counts: {dict(status_counts)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
