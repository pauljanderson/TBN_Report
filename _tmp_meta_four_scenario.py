#!/usr/bin/env python3
"""META four-scenario paste blocks (engine-only; not sheet-reconciled)."""
from __future__ import annotations

import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "drive"
OUT = DRIVE / "brt_sheet_reconcile"
PY = sys.executable
DATA = ROOT / "data" / "newdata" / "data"
PER_SYMBOL = ROOT / "stock_analysis" / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
POSITION = 50000.0  # $50k -> 21% win = $10,500

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
    "max_market_cap=0",
]

SCENARIOS = [
    ("default", "Default", "breakout_zone_pick=max, stop_loss_based=trigger_low", []),
    ("min_zone", "Min zone", "breakout_zone_pick=min, stop_loss_based=trigger_low", ["breakout_zone_pick=min"]),
    (
        "entry_open_stop",
        "Entry open stop",
        "breakout_zone_pick=max, stop_loss_based=entry_open",
        ["stop_loss_based=entry_open"],
    ),
    (
        "zone_bottom",
        "Zone bottom",
        "breakout_zone_pick=max, stop_loss_based=zone_low (alias zone_bottom)",
        ["stop_loss_based=zone_low"],
    ),
]


def pf(v: object, default: float = 0.0) -> float:
    if v is None:
        return default
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s:
        return default
    if s.endswith("%"):
        try:
            return float(s[:-1].strip())
        except ValueError:
            return default
    try:
        return float(s)
    except ValueError:
        return default


def newest_closed_after(t0: float) -> Path | None:
    best = None
    best_m = t0
    for p in DRIVE.glob("BRT_Closed_*.csv"):
        if "_RL_" in p.name:
            continue
        m = p.stat().st_mtime
        if m >= t0 and (best is None or m > best_m):
            best, best_m = p, m
    return best


def run_scenario(extra: list[str]) -> Path:
    cmd = [
        PY,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        str(DATA),
        "-o",
        str(DRIVE),
        "-w",
        "8",
        "--no-regression",
        "--aggressive",
        "-s",
        "META",
    ]
    if PER_SYMBOL.exists():
        cmd += ["--per-symbol-settings", str(PER_SYMBOL)]
    for v in BASE_V + extra:
        cmd += ["-v", v]
    print(f"\n=== Running META: {extra or '(default)'} ===", flush=True)
    t0 = time.time() - 1.0
    rc = subprocess.run(cmd, cwd=str(ROOT))
    if rc.returncode != 0:
        raise SystemExit(f"BRT failed rc={rc.returncode}")
    closed = newest_closed_after(t0)
    if closed is None:
        raise SystemExit("No Closed CSV after run")
    print(f"  -> {closed.name} ({time.time() - t0:.1f}s)", flush=True)
    return closed


def engine_stats(path: Path) -> dict:
    rows = [
        r
        for r in csv.DictReader(path.open(encoding="utf-8-sig"))
        if (r.get("SYMBOL") or "").strip().upper() == "META"
    ]
    pnls = [pf(r.get("PNL_PCT")) for r in rows]
    days = [pf(r.get("DAYS_HELD")) for r in rows]
    days = [d for d in days if d > 0]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    n = len(pnls)
    wlr = (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else 0.0
    total = sum(POSITION * (p / 100.0) for p in pnls)
    return {
        "total_trades": n,
        "win_rate_pct": 100.0 * len(wins) / n if n else 0.0,
        "avg_profit_pct": sum(pnls) / n if n else 0.0,
        "win_loss_ratio": wlr,
        "avg_days": sum(days) / len(days) if days else 0.0,
        "total_profit": total,
        "source": path.name,
    }


def fmt_block(name: str, s: dict) -> str:
    return "\n".join(
        [
            name,
            f"Total Trades\t{s['total_trades']}",
            f"Win Rate\t{s['win_rate_pct']:.1f}%",
            f"Average Profit %\t{s['avg_profit_pct']:.1f}%",
            f"Win/Loss Ratio\t{s['win_loss_ratio']:.2f}",
            f"Average Days in Trade\t{s['avg_days']:.1f}",
            f"Total Profit\t${s['total_profit']:,.2f}",
        ]
    )


def main() -> None:
    reuse: dict[str, str] = {}
    for a in sys.argv[1:]:
        if a.startswith("--reuse-stamps="):
            for part in a.split("=", 1)[1].split(","):
                if "=" in part:
                    k, st = part.split("=", 1)
                    reuse[k.strip()] = st.strip()

    stamps: dict[str, Path] = {}
    configs: dict[str, str] = {}
    for key, label, cfg, extra in SCENARIOS:
        configs[key] = cfg
        if key in reuse:
            p = DRIVE / f"BRT_Closed_{reuse[key]}.csv"
            if not p.exists():
                raise SystemExit(f"missing {p}")
            stamps[key] = p
            print(f"reuse {key}: {p.name}", flush=True)
        else:
            stamps[key] = run_scenario(extra)

    results: dict[str, dict] = {}
    for key, label, _cfg, _extra in SCENARIOS:
        results[label] = engine_stats(stamps[key])

    OUT.mkdir(parents=True, exist_ok=True)
    lines = [
        "# META Four-Scenario BRT Portfolio Stats ($10.5k scale)",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Closed META trades only. **Not sheet-reconciled** (no META_* sheet OHLC/zones/BOs/trades artifacts).",
        "All four scenarios from fresh META-only engine runs.",
        "**Scale:** $50,000 position per trade -> 21% target win = $10,500.",
        "Total Profit = sum(50000 x PNL_PCT/100). Avg days = engine DAYS_HELD (no sheet calendar-day ledger).",
        "",
        "Metrics: Win Rate = share PNL_PCT>0; Average Profit % = mean PNL_PCT;",
        "Win/Loss Ratio = mean winning % / |mean losing %|; Average Days = mean DAYS_HELD(>0).",
        "",
        f"- Stamps: default=`{stamps['default'].stem}`, min=`{stamps['min_zone'].stem}`, "
        f"entry_open=`{stamps['entry_open_stop'].stem}`, zone_bottom=`{stamps['zone_bottom'].stem}`",
        "",
    ]
    for key, label, cfg, _extra in SCENARIOS:
        s = results[label]
        lines += [
            f"## {label}",
            "",
            f"- Config: `{cfg}`",
            f"- Source: `{s['source']}` (engine; $50k / $10.5k-21% win scale)",
            "",
            "```",
            f"Total Trades\t{s['total_trades']}",
            f"Win Rate\t{s['win_rate_pct']:.1f}%",
            f"Average Profit %\t{s['avg_profit_pct']:.1f}%",
            f"Win/Loss Ratio\t{s['win_loss_ratio']:.2f}",
            f"Average Days in Trade\t{s['avg_days']:.1f}",
            f"Total Profit\t${s['total_profit']:,.2f}",
            "```",
            "",
        ]

    out_md = OUT / "META_four_scenario_stats.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print("\n=== PASTE ===\n", flush=True)
    print(
        "Closed META trades only. NOT sheet-reconciled. "
        "All four from META-only engine; Total Profit = $50k x PNL%/100 ($10.5k per 21% win). "
        "Avg days = engine DAYS_HELD."
    )
    print()
    for _key, label, _cfg, _extra in SCENARIOS:
        print(fmt_block(label, results[label]))
        print()
    print(f"Wrote {out_md}", flush=True)


if __name__ == "__main__":
    main()
