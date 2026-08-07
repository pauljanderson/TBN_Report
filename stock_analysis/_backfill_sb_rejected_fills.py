#!/usr/bin/env python3
"""Backfill SB_RejectedFills + Audit counters for an existing gold stamp (no full re-run)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_stockbee_burst import (  # noqa: E402
    BurstConfig,
    REJECTED_FILL_FIELDS,
    _write_csv,
    rejected_fill_to_dict,
    run_backtest,
    write_rejected_fills_html,
)

STAMP = "260802090646"
DRIVE = ROOT / "drive"
DATA = ROOT / "data" / "newdata" / "data"
GOLD = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "tbn_new_systems"
    / "stockbee_momentum_burst"
    / "GOLD_UNIVERSE.csv"
)


def _load_gold_symbols() -> list[str]:
    text = GOLD.read_text(encoding="utf-8").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    syms: list[str] = []
    for ln in lines:
        parts = [x.strip().upper() for x in ln.split(",") if x.strip()]
        if parts and parts[0] == "SYMBOL":
            parts = parts[1:]
        syms.extend(parts)
    seen: set[str] = set()
    out: list[str] = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _patch_audit(path: Path, counters: dict[str, int]) -> None:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if len(rows) < 2:
        raise SystemExit(f"Audit too short: {path}")
    headers = rows[0]
    values = rows[1]
    # pad if needed
    while len(values) < len(headers):
        values.append("")
    # ensure new columns exist (append if missing — matches live schema)
    for col in (
        "sb_signals_total",
        "sb_rejected_fills_total",
        "sb_rejected_too_low",
        "sb_rejected_too_high",
    ):
        if col not in headers:
            headers.append(col)
            values.append("")
    idx = {h: i for i, h in enumerate(headers)}
    for col, val in counters.items():
        values[idx[col]] = str(val)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerow(values)


def main() -> int:
    symbols = _load_gold_symbols()
    if not symbols:
        # fall back to Report symbol list
        rep = DRIVE / f"SB_Report_{STAMP}.txt"
        text = rep.read_text(encoding="utf-8")
        for ln in text.splitlines():
            if ln.startswith("symbols_run="):
                raw = ln.split("=", 1)[1].strip()
                symbols = [x.strip(" []'\"") for x in raw.split(",") if x.strip(" []'\"")]
                break
    if not symbols:
        raise SystemExit("no symbols")
    print(f"[backfill] stamp={STAMP} symbols={len(symbols)}", flush=True)
    cfg = BurstConfig(
        burst_min_pct=0.04,
        burst_vol_gt_prior=True,
        burst_range_lookback=5,
        burst_dcr_min=0.70,
        burst_max_prior_up_days=1,
        burst_fill="next_open",
        burst_max_risk_pct=0.08,
        target_pct=1.10,
        burst_time_stop_days=5,
        burst_no_ft_days=3,
        burst_mm_gate=False,
        burst_min_price=5.0,
        host_dollar_scale=True,
    )
    _closed, _opens, _watches, rejected, meta, _tickers = run_backtest(symbols, DATA, cfg)
    print(
        f"[backfill] signals={meta['n_signals']} rejected={meta['n_rejected_risk']} "
        f"too_low={meta['n_rejected_too_low']} too_high={meta['n_rejected_too_high']} "
        f"closed={meta['n_closed']}",
        flush=True,
    )
    # Sanity vs gold report rejected_risk=625
    expected_rej = 625
    if meta["n_rejected_risk"] != expected_rej:
        print(
            f"[backfill] WARNING: rejected_risk={meta['n_rejected_risk']} != gold Report {expected_rej}",
            flush=True,
        )

    rows = [rejected_fill_to_dict(r) for r in rejected]
    csv_path = DRIVE / f"SB_RejectedFills_{STAMP}.csv"
    html_path = DRIVE / f"SB_RejectedFills_{STAMP}.html"
    _write_csv(csv_path, REJECTED_FILL_FIELDS, rows)
    n_other = sum(1 for r in rejected if r.reject_reason not in ("TOO_LOW", "TOO_HIGH"))
    write_rejected_fills_html(
        html_path,
        rows,
        stamp=STAMP,
        n_too_low=int(meta["n_rejected_too_low"]),
        n_too_high=int(meta["n_rejected_too_high"]),
        n_other=n_other,
    )
    # LatestRun mirrors
    (DRIVE / "SB_LatestRun_RejectedFills.csv").write_bytes(csv_path.read_bytes())
    (DRIVE / "SB_LatestRun_RejectedFills.html").write_bytes(html_path.read_bytes())

    counters = {
        "sb_signals_total": int(meta["n_signals"]),
        "sb_rejected_fills_total": int(meta["n_rejected_risk"]),
        "sb_rejected_too_low": int(meta["n_rejected_too_low"]),
        "sb_rejected_too_high": int(meta["n_rejected_too_high"]),
    }
    audit = DRIVE / f"SB_Audit_Report_{STAMP}.csv"
    if audit.exists():
        _patch_audit(audit, counters)
        latest_audit = DRIVE / "SB_LatestRun_Audit_Report.csv"
        if latest_audit.exists():
            # only overwrite LatestRun audit if it matches this stamp (best-effort)
            try:
                ts_file = (DRIVE / "SB_last_run_ts.txt").read_text(encoding="utf-8").strip()
            except OSError:
                ts_file = ""
            if ts_file == STAMP or not ts_file:
                latest_audit.write_bytes(audit.read_bytes())
        print(f"[backfill] patched Audit: {audit}", flush=True)
    print(f"[backfill] wrote {csv_path} ({len(rows)} rows)", flush=True)
    print(f"[backfill] wrote {html_path}", flush=True)
    print(f"[backfill] counters={counters}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
