#!/usr/bin/env python3
"""MR AB #4 — BRT z-score EXIT AB (research-only).

Control: BRT DailyRun freeze with `zscore_exit_enabled=false` (prod default).
Candidate: same freeze + `zscore_exit_enabled=true` with frozen N=40, k=2.0
(engine defaults — one enable knob; N/k frozen, not a grid).

Labeled EXIT AB. Universe: drive/universes/BRT_universe.csv.

Usage:
  python tools/mr_brt_zscore_exit_ab.py
  python tools/mr_brt_zscore_exit_ab.py --skip-existing
  python tools/mr_brt_zscore_exit_ab.py --summarize-only
  python tools/mr_brt_zscore_exit_ab.py --workers 12
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mr_ab_common import (  # noqa: E402
    BRT_CASH,
    PARENT_OUT,
    PARENT_STAMP,
    load_trades,
    overall_verdict,
    pack_overlay_arm,
    write_stamp_html,
    write_summary_md,
)
from rl_univ_compare_lists import _find_latest, _resolve_python  # noqa: E402

CHILD = "04_brt_zscore_exit"
OUT = PARENT_OUT / CHILD
UNIV = ROOT / "drive" / "universes" / "BRT_universe.csv"
DATA = ROOT / "data" / "newdata" / "data"
PER_SYMBOL = ROOT / "stock_analysis" / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

# Frozen N,k (engine defaults) — enable flag is the one knob
Z_N = 40
Z_K = 2.0

BRT_COMMON_V = [
    "stop_pct=0.934",
    "target_pct=1.21",
    "too_high_multiplier=0",
    "band_pct=0.0154",
    "strong_pre_pivot_pct=0.1",
    "strong_post_pivot_pct=0.1",
    "strong_pre_pivot_bars=7",
    "strong_post_pivot_bars=7",
    "breakout_bars=100",
    "tight_range_threshold_pct=0.35",
    "tight_range_lookback=105",
    "sheet_breakout_scan_start_row_delta=2",
    "brt_sheet_touch=true",
    "min_spy_compare_1y_at_trigger=-1000",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=true",
    "brt_zones=true",
    "yh_zones=false",
    "min_pivot_run_h_before_entry=0",
    "min_beta_at_trigger=0",
    "max_market_cap=0",
    "min_market_cap=0",
]

ARMS = [
    {
        "id": "control",
        "label": "control (zscore_exit OFF)",
        "extra": ["zscore_exit_enabled=false"],
    },
    {
        "id": "zscore_on",
        "label": f"zscore_exit ON (N={Z_N}, k={Z_K})",
        "extra": [
            "zscore_exit_enabled=true",
            f"zscore_exit_lookback={Z_N}",
            f"zscore_exit_k={Z_K}",
        ],
    },
]


def load_univ_symbols() -> list[str]:
    out: list[str] = []
    for line in UNIV.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip().upper()
        if not s or s.startswith("#") or s == "SYMBOL":
            continue
        out.append(s.split(",")[0].strip().upper())
    return out


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = [
        py,
        str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(DATA),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--no-regression",
        "--aggressive",
        "--print-zones",
        "--use-duckdb",
    ]
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for v in BRT_COMMON_V + extra_v:
        cmd.extend(["-v", v])
    cmd.extend(["-s", symbols])
    return cmd


def run_arm(arm: dict[str, Any], symbols: str, workers: int, skip_existing: bool) -> dict[str, Any]:
    outdir = OUT / "runs" / arm["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    existing = _find_latest(outdir, "BRT_Closed_*.csv")
    if skip_existing and existing and existing.stat().st_size > 0:
        print(f"[skip] {arm['id']} reuse {existing.name}")
        return {"arm": arm, "ok": True, "closed": existing, "outdir": outdir}

    py = _resolve_python()
    cmd = build_cmd(py, outdir, workers, symbols, arm["extra"])
    log = outdir / "run.log"
    print(f"[run] {arm['id']} -> {outdir}")
    t0 = time.time()
    with log.open("w", encoding="utf-8") as lf:
        lf.write(" ".join(cmd) + "\n\n")
        lf.flush()
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT)
    elapsed = time.time() - t0
    closed = _find_latest(outdir, "BRT_Closed_*.csv")
    ok = proc.returncode == 0 and closed is not None and closed.stat().st_size > 0
    print(f"[{'ok' if ok else 'FAIL'}] {arm['id']} rc={proc.returncode} {elapsed:.0f}s closed={closed}")
    return {"arm": arm, "ok": ok, "closed": closed, "outdir": outdir, "rc": proc.returncode}


def summarize(runs: list[dict[str, Any]]) -> int:
    packed: list[dict[str, Any]] = []
    for r in runs:
        if not r.get("ok") or not r.get("closed"):
            print(f"WARN: missing Closed for {r['arm']['id']}")
            continue
        trades = load_trades(r["closed"])
        # BRT dollars may already be in Closed; load_trades fills from % if needed
        p = pack_overlay_arm(r["arm"]["id"], r["arm"]["label"], trades, BRT_CASH)
        p["cash"] = BRT_CASH
        p["closed"] = r["closed"]
        packed.append(p)
    if len(packed) < 2:
        raise SystemExit("Need control + candidate Closed to summarize")

    control = next(p for p in packed if p["id"] == "control")
    verdicts: dict[str, tuple[str, str, str, str]] = {}
    for p in packed:
        if p["id"] == "control":
            continue
        verdicts[p["id"]] = overall_verdict(p, control)

    baseline = f"""# BASELINE — `{PARENT_STAMP}/{CHILD}`

**Status:** RESEARCH EXIT AB — not gold / not DailyRun.

## Hypothesis

Enabling the host detrended log-price residual z-score exit (already coded, default off)
improves BRT exit quality vs production stop+target alone.

## Single knob (EXIT-labeled)

| Knob | Control | Candidate |
|------|---------|-----------|
| `zscore_exit_enabled` | **false** | **true** |
| `zscore_exit_lookback` | n/a | **{Z_N}** (frozen) |
| `zscore_exit_k` | n/a | **{Z_K}** (frozen) |

N and k are frozen at engine defaults — **not** a grid. The hypothesis is enable vs off.

## Frozen BRT DailyRun identity (`run_brt.bat`)

All common `-v` from `run_brt.bat` (stop 0.934, target 1.21, band 0.0154, growth on,
sheet touch, red-to-green, zones on, market-cap bounds 0, …). Universe: `BRT_universe.csv`.

Cash model $47,500. Split: IS entry < 2024-01-01; OOS report-only.

## Closed stamps

"""
    for p in packed:
        baseline += f"- `{p['id']}`: `{p.get('closed')}`\n"
    baseline += "\n## Verdict\n\nSee `SUMMARY.md` / `compare.html`.\n"
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    write_stamp_html(
        OUT,
        title="MR AB #4 — BRT z-score EXIT (enabled vs off)",
        meta=f"Stamp <code>{PARENT_STAMP}/{CHILD}</code> · EXIT AB · research-only",
        warn=(
            "<strong>EXIT-labeled AB.</strong> One knob: enable zscore_exit "
            f"(N={Z_N}, k={Z_K} frozen). OOS report-only — do not retune. Not DailyRun."
        ),
        baseline_md_link="BASELINE.md",
        arms=packed,
        control=control,
        verdicts=verdicts,
    )
    write_summary_md(
        OUT,
        stamp=f"{PARENT_STAMP}/{CHILD}",
        hypothesis="Enable zscore_exit on BRT improves exit quality vs prod off.",
        knob=f"zscore_exit_enabled true vs false (N={Z_N}, k={Z_K} frozen)",
        control_id="BRT DailyRun freeze, zscore_exit OFF",
        arms=packed,
        verdicts=verdicts,
    )
    for aid, (tag, *_rest) in verdicts.items():
        print(f"[mr_brt_z] {aid} overall={tag}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=int(os.environ.get("BRT_WORKERS", "12")))
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--summarize-only", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    syms = load_univ_symbols()
    if not syms:
        raise SystemExit(f"Empty BRT universe: {UNIV}")
    symbols = ",".join(syms)
    print(f"[mr_brt_z] universe N={len(syms)}")

    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in ARMS:
            outdir = OUT / "runs" / arm["id"]
            closed = _find_latest(outdir, "BRT_Closed_*.csv")
            runs.append({"arm": arm, "ok": closed is not None, "closed": closed, "outdir": outdir})
    else:
        for arm in ARMS:
            runs.append(run_arm(arm, symbols, args.workers, args.skip_existing))

    return summarize(runs)


if __name__ == "__main__":
    raise SystemExit(main())
