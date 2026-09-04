#!/usr/bin/env python3
"""DailyRun hook: refresh house fund scorecard + retain dated PIT snapshots.

Refresh policy
--------------
- Yahoo ``Ticker.info`` multiples: fetch symbols that are **missing** or older
  than TTL (default **7 days**; env ``FUND_SCORECARD_TTL_DAYS`` /
  ``YF_FUND_TTL_DAYS``; CLI ``--ttl-days``).
- ``FORCE_FUND_SCORECARD=1`` / ``--force-refresh``: ignore TTL (full Yahoo pass).
- ``SKIP_FUND_SCORECARD=1``: DailyRun bat skips this tool entirely.
- ``NO_YFINANCE=1``: no network; still re-score from cache and write today's
  history rows when possible.
- Same calendar day + no stale symbols + prior success stamp → **skip**
  (cheap). ``--force-snapshot`` always re-scores and rewrites today's history.

History (PIT path going forward)
--------------------------------
DuckDB ``drive/fund_scorecard_cache.duckdb``:

- ``yf_scorecard_metrics`` — latest overwrite-by-symbol (live cache)
- ``yf_scorecard_metrics_history`` — ``(symbol, as_of)`` raw Yahoo multiples
- ``yf_scorecard_scores_history`` — ``(symbol, as_of)`` pillar scores + key metrics

Join future trades with ``as_of <= entry_date`` (see
``fund_scorecard_v1.scores_as_of``). **No backfill** of past dates — PIT only
becomes usable after DailyRun has accumulated history from today forward.

Also writes ``drive/fund_scorecard_latest/scores.csv`` (live consumer path)
and ``drive/fund_scorecard_last_ok.json``.

Not gold. Does not promote contaminated Closed overlays.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from stock_analysis.fundamentals_yfinance import (  # noqa: E402
    resolve_fundamentals_db,
    yfinance_disabled,
)

from fund_scorecard_v1 import (  # noqa: E402
    DEFAULT_LATEST_DIR,
    DEFAULT_SCORECARD_DB,
    LAST_OK_STAMP,
    UNIVERSE_ADV2M,
    UNIVERSE_ALL,
    _fresh,
    _load_scorecard_cache,
    _load_universe,
    build_metric_frame,
    history_coverage,
    persist_scores_history,
    refresh_scorecard_metrics,
    score_pillars,
    scorecard_ttl_days,
    snapshot_metrics_history_from_latest,
    _connect,
    ensure_scorecard_schema,
)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


def _load_last_ok() -> Optional[dict[str, Any]]:
    if not LAST_OK_STAMP.is_file():
        return None
    try:
        return json.loads(LAST_OK_STAMP.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_last_ok(payload: dict[str, Any]) -> None:
    LAST_OK_STAMP.parent.mkdir(parents=True, exist_ok=True)
    LAST_OK_STAMP.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _stale_or_missing(
    symbols: list[str],
    scorecard_db: Path,
    *,
    ttl: int,
    force: bool,
) -> list[str]:
    ensure_scorecard_schema(scorecard_db)
    con = _connect(scorecard_db, read_only=True)
    try:
        cached = _load_scorecard_cache(con, symbols)
    finally:
        con.close()
    if force:
        return list(symbols)
    return [
        s
        for s in symbols
        if s not in cached or not _fresh(cached[s].get("fetched_at"), ttl=ttl)
    ]


def _today_scores_exist(scorecard_db: Path, as_of) -> bool:
    ensure_scorecard_schema(scorecard_db)
    con = _connect(scorecard_db, read_only=True)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM yf_scorecard_scores_history WHERE as_of = ?",
            [as_of],
        ).fetchone()[0]
        return int(n) > 0
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="DailyRun fund scorecard refresh + PIT history snapshot"
    )
    ap.add_argument(
        "--universe",
        type=Path,
        default=UNIVERSE_ALL,
        help=f"Symbol list (default: {UNIVERSE_ALL.name})",
    )
    ap.add_argument("--db", type=Path, default=None, help="Fundamentals DuckDB (read-only)")
    ap.add_argument(
        "--scorecard-db",
        type=Path,
        default=DEFAULT_SCORECARD_DB,
        help="Scorecard DuckDB (latest + history)",
    )
    ap.add_argument(
        "--latest-dir",
        type=Path,
        default=DEFAULT_LATEST_DIR,
        help="Live scores.csv output directory",
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ttl-days", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore Yahoo TTL (also FORCE_FUND_SCORECARD=1)",
    )
    ap.add_argument(
        "--force-snapshot",
        action="store_true",
        help="Re-score and rewrite today's history even if already done",
    )
    ap.add_argument("--cache-only", action="store_true", help="No Yahoo network fetch")
    ap.add_argument("--min-industry-n", type=int, default=6)
    ap.add_argument("--min-sector-n", type=int, default=8)
    ap.add_argument(
        "--status-html",
        type=Path,
        default=None,
        help="Optional status HTML under drive/paul_experiments/...",
    )
    ap.add_argument("--skip-ntfy", action="store_true")
    args = ap.parse_args(argv)

    ttl = int(args.ttl_days) if args.ttl_days is not None else scorecard_ttl_days()
    force = bool(args.force_refresh) or _env_truthy("FORCE_FUND_SCORECARD")
    cache_only = bool(args.cache_only) or yfinance_disabled()
    as_of_day = datetime.utcnow().date()

    univ_path = args.universe if args.universe.is_absolute() else _REPO / args.universe
    if not univ_path.exists():
        if UNIVERSE_ADV2M.exists():
            print(f"[fund-sc-daily] universe missing {univ_path}; fallback {UNIVERSE_ADV2M}")
            univ_path = UNIVERSE_ADV2M
        else:
            print(f"ERROR: universe not found: {univ_path}", file=sys.stderr)
            return 2

    symbols = _load_universe(univ_path)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]

    sc_db = args.scorecard_db if args.scorecard_db.is_absolute() else _REPO / args.scorecard_db
    latest_dir = args.latest_dir if args.latest_dir.is_absolute() else _REPO / args.latest_dir
    db_path = resolve_fundamentals_db(args.db)

    need = _stale_or_missing(symbols, sc_db, ttl=ttl, force=force)
    today_ok = _today_scores_exist(sc_db, as_of_day)
    last = _load_last_ok()
    last_as_of = str((last or {}).get("as_of") or "")

    print(
        f"[fund-sc-daily] universe={univ_path.name} N={len(symbols)} "
        f"ttl_days={ttl} force={force} cache_only={cache_only}"
    )
    print(
        f"[fund-sc-daily] stale_or_missing={len(need)} "
        f"today_scores_exist={today_ok} last_ok_as_of={last_as_of or 'none'}"
    )

    scores_csv = latest_dir / "scores.csv"
    skip_ok = (
        not args.force_snapshot
        and not force
        and not need
        and today_ok
        and last_as_of == as_of_day.isoformat()
        and bool((last or {}).get("ok", False))
        and scores_csv.is_file()
    )
    if skip_ok:
        cov = history_coverage(sc_db)
        print(
            f"[fund-sc-daily] SKIP — today's PIT snapshot already written "
            f"and no symbols past TTL ({cov})"
        )
        return 0
    if (
        not args.force_snapshot
        and not force
        and not need
        and today_ok
        and last_as_of == as_of_day.isoformat()
        and bool((last or {}).get("ok", False))
        and not scores_csv.is_file()
    ):
        print(
            f"[fund-sc-daily] today snapshot OK in DB but missing {scores_csv} — re-exporting"
        )

    scorecard = refresh_scorecard_metrics(
        symbols,
        sc_db,
        force=force,
        cache_only=cache_only,
        ttl=ttl,
        workers=args.workers,
    )
    raw = build_metric_frame(symbols, db_path, scorecard)
    scored = score_pillars(
        raw,
        min_industry_n=args.min_industry_n,
        min_sector_n=args.min_sector_n,
    )
    scored_n = int((scored["n_pillars"] >= 1).sum())

    # Always retain today's dated rows (even when Yahoo TTL skipped all fetches)
    snapshot_metrics_history_from_latest(sc_db, symbols, as_of=as_of_day)
    hist_n = persist_scores_history(sc_db, scored, as_of=as_of_day)

    latest_dir.mkdir(parents=True, exist_ok=True)
    _LATEST_CSV_COLS = [
        "symbol",
        "sector",
        "industry",
        "is_financial",
        "peer_mode",
        "score_valuation",
        "score_quality",
        "score_growth_stability",
        "score_financial_health",
        "score_composite",
        "score_valuation_sector",
        "score_quality_sector",
        "score_growth_stability_sector",
        "score_financial_health_sector",
        "score_composite_sector",
        "n_pillars",
        "pe",
        "pe_source",
        "pb",
        "ps",
        "ev_ebitda",
        "roe",
        "roa",
        "profit_margin",
        "operating_margin",
        "fcf_conversion",
        "eps_growth_vol",
        "debt_to_equity",
        "current_ratio",
        "interest_coverage",
        "earnings_growth",
        "revenue_growth",
        "has_scorecard_row",
        "has_fund_info",
    ]
    export_cols = [c for c in _LATEST_CSV_COLS if c in scored.columns]
    export = scored[export_cols].sort_values("score_composite", ascending=False)
    export.to_csv(scores_csv, index=False)
    meta_path = latest_dir / "meta.json"
    cov = history_coverage(sc_db)
    meta = {
        "ok": True,
        "as_of": as_of_day.isoformat(),
        "ok_at": datetime.utcnow().isoformat() + "Z",
        "universe": univ_path.as_posix(),
        "univ_n": len(symbols),
        "scored_n": scored_n,
        "yahoo_fetched_or_attempted": len(need) if not cache_only else 0,
        "stale_or_missing_at_start": len(need),
        "ttl_days": ttl,
        "force": force,
        "cache_only": cache_only,
        "scores_history_rows_written": hist_n,
        "scores_csv": scores_csv.as_posix(),
        "scorecard_db": sc_db.as_posix(),
        "coverage": cov,
        "policy": (
            "Yahoo refresh if missing/stale beyond TTL (default 7d); "
            "always write (symbol, as_of=today) metrics+scores history on run"
        ),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    _write_last_ok(meta)

    print(
        f"[fund-sc-daily] scored={scored_n}/{len(symbols)} "
        f"history_rows={hist_n} as_of={as_of_day} -> {scores_csv}"
    )
    print(f"[fund-sc-daily] coverage={cov}")

    status_html = args.status_html
    if status_html is None:
        # default small status page next to the PIT stamp if present
        stamp = _REPO / "drive" / "paul_experiments" / "fund_scorecard_pit_dailyrun_20260831"
        if stamp.is_dir():
            status_html = stamp / "status.html"
    if status_html is not None:
        status_html = status_html if status_html.is_absolute() else _REPO / status_html
        status_html.parent.mkdir(parents=True, exist_ok=True)
        _write_status_html(status_html, meta)
        if not args.skip_ntfy:
            import subprocess

            subprocess.run(
                [
                    sys.executable,
                    str(_REPO / "tools" / "ntfy_job_done.py"),
                    "--path",
                    str(status_html),
                    "-t",
                    "Fund scorecard DailyRun refresh",
                    "-m",
                    (
                        f"as_of={as_of_day} scored={scored_n}/{len(symbols)} "
                        f"stale={len(need)} hist_days={cov.get('scores_distinct_days')}"
                    ),
                ],
                check=False,
            )

    return 0


def _write_status_html(path: Path, meta: dict[str, Any]) -> None:
    cov = meta.get("coverage") or {}
    rows = [
        ("as_of", meta.get("as_of")),
        ("scored", f"{meta.get('scored_n')}/{meta.get('univ_n')}"),
        ("TTL days", meta.get("ttl_days")),
        ("stale/missing at start", meta.get("stale_or_missing_at_start")),
        ("force", meta.get("force")),
        ("cache_only", meta.get("cache_only")),
        ("scores history rows", cov.get("scores_history_n")),
        ("metrics history rows", cov.get("metrics_history_n")),
        ("distinct as_of days", cov.get("scores_distinct_days")),
        ("as_of min→max", f"{cov.get('scores_as_of_min')} → {cov.get('scores_as_of_max')}"),
        ("latest CSV", meta.get("scores_csv")),
        ("scorecard DB", meta.get("scorecard_db")),
    ]
    body = "\n".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows
    )
    path.write_text(
        f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Fund scorecard DailyRun status</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;max-width:52rem;}}
table{{border-collapse:collapse;width:100%;}}
th,td{{border:1px solid #ccc;padding:.4rem .6rem;text-align:left;}}
th{{background:#f4f4f4;width:40%;}}
.note{{color:#444;font-size:.95rem;}}
</style></head><body>
<h1>Fund scorecard DailyRun refresh</h1>
<p class="note"><strong>Research retention path.</strong> Not gold. Yahoo TTL smart
refresh + dated PIT history. Existing Closed overlays remain look-ahead contaminated
until enough <code>as_of</code> history exists for entry-date joins.</p>
<table>{body}</table>
<p class="note">Policy: {meta.get('policy')}</p>
<p class="note">Generated {meta.get('ok_at')}</p>
</body></html>
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
