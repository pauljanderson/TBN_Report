#!/usr/bin/env python3
"""
Run four BRT scenarios (default / min zone / entry_open stop / zone_low stop)
with the same baseline flags as run_brt.bat, then aggregate Closed trade stats.

Outputs:
  drive/brt_sheet_reconcile/BRT_four_scenario_stats.md
  drive/brt_sheet_reconcile/BRT_four_scenario_stats.csv
"""
from __future__ import annotations

import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "brt_sheet_reconcile"
PY = sys.executable

# Same universe as run_brt.bat default BRT_SYMBOLS
BRT_SYMBOLS = (
    "AAPL,ABBV,ACN,ADBE,ADI,AMAT,AMD,AMZN,AU,AVGO,BABA,BAC,CDNS,CI,CRM,CRWD,"
    "GOOG,GOOGL,HD,JPM,KR,LYV,META,MPC,MSFT,MU,NEM,NFLX,NVDA,ORCL,PFE,PG,PPTA,"
    "SHOP,TMUS,TSLA,TSM,UNH,V,WFC,WMT,XOM"
)
PER_SYMBOL = ROOT / "stock_analysis" / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

# Shared -v flags from run_brt.bat (excluding scenario-specific overrides)
BASE_V = [
    "stop_pct=0.934",
    "target_pct=1.21",
    "too_high_multiplier=0",
    "band_pct=0.0154",
    "strong_pre_pivot_pct=0.081",
    "strong_post_pivot_pct=0.108",
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
]

SCENARIOS: list[tuple[str, str, list[str]]] = [
    # (key, label, extra -v)
    ("default", "Default (zone pick max, stop=trigger_low)", []),
    ("min_zone", "Min zone (breakout_zone_pick=min)", ["breakout_zone_pick=min"]),
    ("entry_open_stop", "Entry open stop (stop_loss_based=entry_open)", ["stop_loss_based=entry_open"]),
    ("zone_bottom_stop", "Zone bottom stop (stop_loss_based=zone_low)", ["stop_loss_based=zone_low"]),
]


def _newest_closed_after(t0: float) -> Path | None:
    best: Path | None = None
    best_mtime = t0
    for p in DRIVE.glob("BRT_Closed_*.csv"):
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m >= t0 and (best is None or m > best_mtime):
            best = p
            best_mtime = m
    return best


def _run_scenario(extra_v: list[str]) -> Path:
    cmd = [
        PY,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o",
        str(DRIVE),
        "-w",
        "16",
        "--no-regression",
        "--aggressive",
        "-s",
        BRT_SYMBOLS,
    ]
    if PER_SYMBOL.exists():
        cmd += ["--per-symbol-settings", str(PER_SYMBOL)]
    for v in BASE_V + extra_v:
        cmd += ["-v", v]

    print(f"\n=== Running: {' '.join(extra_v) if extra_v else '(defaults)'} ===", flush=True)
    t0 = time.time()
    # Touch a marker so we can detect files written after this run starts
    marker = t0 - 1.0
    rc = subprocess.run(cmd, cwd=str(ROOT))
    if rc.returncode != 0:
        raise SystemExit(f"BRT run failed with exit code {rc.returncode}")
    closed = _newest_closed_after(marker)
    if closed is None:
        raise SystemExit("No BRT_Closed_*.csv found after run")
    print(f"  -> {closed.name} ({time.time() - t0:.1f}s)", flush=True)
    return closed


def _parse_float(val: object, default: float = 0.0) -> float:
    """Parse CSV numeric cells that may include commas, $, or a trailing %."""
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    s = s.replace(",", "").replace("$", "")
    pct = s.endswith("%")
    if pct:
        s = s[:-1].strip()
    try:
        return float(s)
    except ValueError:
        return default


def _aggregate(closed_path: Path) -> dict[str, float | int | str]:
    rows: list[dict[str, str]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    n = len(rows)
    if n == 0:
        return {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "avg_profit_pct": 0.0,
            "win_loss_ratio": 0.0,
            "avg_days": 0.0,
            "total_profit": 0.0,
            "wins": 0,
            "losses": 0,
            "symbols": 0,
        }

    pnls = [_parse_float(r.get("PNL_PCT")) for r in rows]
    dollars = [_parse_float(r.get("PNL_DOLLARS")) for r in rows]
    days = [
        d
        for r in rows
        for d in [_parse_float(r.get("DAYS_HELD"))]
        if d > 0
    ]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    win_dollars = [d for p, d in zip(pnls, dollars) if p > 0]
    loss_dollars = [abs(d) for p, d in zip(pnls, dollars) if p < 0]
    avg_win = sum(win_dollars) / len(win_dollars) if win_dollars else 0.0
    avg_loss = sum(loss_dollars) / len(loss_dollars) if loss_dollars else 0.0
    wlr = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 0.0)
    symbols = {str(r.get("SYMBOL") or "").strip().upper() for r in rows if r.get("SYMBOL")}
    return {
        "total_trades": n,
        "win_rate_pct": 100.0 * wins / n,
        "avg_profit_pct": sum(pnls) / n,
        "win_loss_ratio": wlr,
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "total_profit": sum(dollars),
        "wins": wins,
        "losses": losses,
        "symbols": len(symbols),
    }


def _fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def _fmt_num(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    stamps: dict[str, str] = {}

    # Optional resume: --reuse-stamps key=stamp,... (skip re-running those scenarios)
    reuse: dict[str, str] = {}
    for a in sys.argv[1:]:
        if a.startswith("--reuse-stamps="):
            for part in a.split("=", 1)[1].split(","):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                k, stamp = part.split("=", 1)
                reuse[k.strip()] = stamp.strip()

    for key, label, extra in SCENARIOS:
        if key in reuse:
            closed = DRIVE / f"BRT_Closed_{reuse[key]}.csv"
            if not closed.exists():
                raise SystemExit(f"Reuse stamp missing: {closed}")
            print(f"\n=== Reusing {key}: {closed.name} ===", flush=True)
        else:
            closed = _run_scenario(extra)
        stamp = closed.stem.replace("BRT_Closed_", "")
        stamps[key] = stamp
        m = _aggregate(closed)
        results.append(
            {
                "scenario_key": key,
                "scenario": label,
                "stamp": stamp,
                "closed_file": closed.name,
                **m,
            }
        )

    # Markdown table
    md_lines = [
        "# BRT Four-Scenario Stats",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Universe",
        "",
        f"- Symbols: `{BRT_SYMBOLS}` (same default list as `run_brt.bat`).",
        f"- Per-symbol settings: `{PER_SYMBOL.name}` (if present).",
        "- Baseline flags match `run_brt.bat` (SPY gate `min_spy_compare_1y_at_trigger=-1000`, growth filter, sheet touch, etc.).",
        "- Default scenario: `breakout_zone_pick=max` (implicit), `stop_loss_based=trigger_low` (implicit).",
        "",
        "## Config notes",
        "",
        "| Scenario | Key override |",
        "|---|---|",
        "| Default | *(none — production defaults)* |",
        "| Min zone | `-v breakout_zone_pick=min` |",
        "| Entry open stop | `-v stop_loss_based=entry_open` |",
        "| Zone bottom stop | `-v stop_loss_based=zone_low` (alias: `zone_bottom`) |",
        "",
        "New stop base: `stop_loss_based=zone_low` -> stop = **zone lower bound x stop_pct** "
        "(same multiplier semantics as `trigger_low`). Default behavior unchanged.",
        "",
        "## Metrics",
        "",
        "- **Win Rate**: share of closed trades with PNL_PCT > 0.",
        "- **Average Profit %**: mean of PNL_PCT.",
        "- **Win/Loss Ratio**: mean winning $ / mean |losing $| (dollar magnitude).",
        "- **Average Days in Trade**: mean DAYS_HELD (>0).",
        "- **Total Profit**: sum of PNL_DOLLARS.",
        "",
        "| Scenario | Total Trades | Win Rate | Average Profit % | Win/Loss Ratio | Average Days in Trade | Total Profit | Stamp |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        md_lines.append(
            "| {scenario} | {total_trades} | {win_rate} | {avg_profit} | {wlr} | {avg_days} | {total_profit} | `{stamp}` |".format(
                scenario=r["scenario"],
                total_trades=r["total_trades"],
                win_rate=_fmt_pct(float(r["win_rate_pct"])),
                avg_profit=_fmt_pct(float(r["avg_profit_pct"])),
                wlr=_fmt_num(float(r["win_loss_ratio"])),
                avg_days=_fmt_num(float(r["avg_days"]), 1),
                total_profit=_fmt_num(float(r["total_profit"])),
                stamp=r["stamp"],
            )
        )
    md_lines.extend(
        [
            "",
            "## Run stamps",
            "",
        ]
    )
    for key, stamp in stamps.items():
        md_lines.append(f"- **{key}**: `BRT_Closed_{stamp}.csv`")
    md_lines.append("")

    md_path = OUT_DIR / "BRT_four_scenario_stats.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    csv_path = OUT_DIR / "BRT_four_scenario_stats.csv"
    fieldnames = [
        "scenario_key",
        "scenario",
        "stamp",
        "closed_file",
        "total_trades",
        "win_rate_pct",
        "avg_profit_pct",
        "win_loss_ratio",
        "avg_days",
        "total_profit",
        "wins",
        "losses",
        "symbols",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)

    print(f"\nWrote {md_path}")
    print(f"Wrote {csv_path}")
    print("\n".join(md_lines))


if __name__ == "__main__":
    main()
