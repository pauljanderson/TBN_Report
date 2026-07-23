#!/usr/bin/env python3
"""AMD four-scenario paste blocks: sheet Default + post-L engine others."""
from __future__ import annotations

import csv
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "drive"
OUT = DRIVE / "brt_sheet_reconcile"
SHEET = OUT / "AMD_sheet_trades.csv"
PY = sys.executable
DATA = ROOT / "data" / "newdata" / "data"
PER_SYMBOL = ROOT / "stock_analysis" / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

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
    ("default", "Default", []),
    ("min_zone", "Min zone", ["breakout_zone_pick=min"]),
    ("entry_open_stop", "Entry open stop", ["stop_loss_based=entry_open"]),
    ("zone_bottom", "Zone bottom", ["stop_loss_based=zone_low"]),
]


def pf(v: object, default: float | None = 0.0) -> float | None:
    if v is None:
        return default
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s or "DIV" in s.upper() or "N/A" in s.upper():
        return None if default is None else default
    if s.endswith("%"):
        try:
            return float(s[:-1].strip())
        except ValueError:
            return default
    try:
        return float(s)
    except ValueError:
        return default


def parse_pct_points(s: object) -> float | None:
    """Profit % as percent points (21.0 for 21%)."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "")
    if not t or "DIV" in t.upper():
        return None
    if t.endswith("%"):
        return float(t[:-1].strip())
    # $0.21 style fraction, or -$0.0835
    neg = t.startswith("-")
    t2 = t[1:] if neg else t
    if t2.startswith("$"):
        v = float(t2[1:]) * 100.0
        return -v if neg else v
    v = float(t.replace("$", ""))
    if abs(v) <= 1.5:
        return v * 100.0
    return v


def newest_closed_after(t0: float) -> Path | None:
    best = None
    best_m = t0
    for p in DRIVE.glob("BRT_Closed_*.csv"):
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
        "AMD",
    ]
    if PER_SYMBOL.exists():
        cmd += ["--per-symbol-settings", str(PER_SYMBOL)]
    for v in BASE_V + extra:
        cmd += ["-v", v]
    print(f"\n=== Running AMD: {extra or '(default)'} ===", flush=True)
    t0 = time.time() - 1.0
    rc = subprocess.run(cmd, cwd=str(ROOT))
    if rc.returncode != 0:
        raise SystemExit(f"BRT failed rc={rc.returncode}")
    closed = newest_closed_after(t0)
    if closed is None:
        raise SystemExit("No Closed CSV after run")
    print(f"  -> {closed.name} ({time.time() - t0:.1f}s)", flush=True)
    return closed


def sheet_default() -> dict:
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8-sig")))
    valid = []
    for r in rows:
        pct = parse_pct_points(r.get("Profit %"))
        if pct is None:
            continue
        dollars = pf(r.get("Profit per trade"), default=None)
        if dollars is None:
            # fill blank WIN at 21%
            if abs(pct - 21.0) < 0.05:
                dollars = 10500.0
            else:
                continue
        days = pf(r.get("Days In Trade")) or 0.0
        valid.append((pct, dollars, days))
    pnls = [p for p, _, _ in valid]
    dollars = [d for _, d, _ in valid]
    days = [dy for _, _, dy in valid if dy > 0]
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    wd = [d for p, d in zip(pnls, dollars) if p > 0]
    ld = [abs(d) for p, d in zip(pnls, dollars) if p < 0]
    aw, al = (sum(wd) / len(wd) if wd else 0.0), (sum(ld) / len(ld) if ld else 0.0)
    # Prefer %-based W/L to match prior AMD/NVDA pasteables when documented as 2.22
    ww = [p for p in pnls if p > 0]
    ll = [abs(p) for p in pnls if p < 0]
    wlr_pct = (sum(ww) / len(ww)) / (sum(ll) / len(ll)) if ww and ll else 0.0
    wlr_dol = aw / al if al > 0 else aw
    return {
        "total_trades": n,
        "win_rate_pct": 100.0 * wins / n,
        "avg_profit_pct": sum(pnls) / n,
        "win_loss_ratio": wlr_pct,  # matches prior AMD paste (2.22)
        "win_loss_ratio_dol": wlr_dol,
        "avg_days": sum(days) / len(days) if days else 0.0,
        "total_profit": sum(dollars),
        "source": "sheet",
    }


def engine_stats(path: Path, scale: float) -> dict:
    rows = [
        r
        for r in csv.DictReader(path.open(encoding="utf-8-sig"))
        if (r.get("SYMBOL") or "").strip().upper() == "AMD"
    ]
    if not rows:
        # try checkpoint? return empty
        return {"total_trades": 0, "source": path.name}
    pnls = [pf(r.get("PNL_PCT")) or 0.0 for r in rows]
    # PNL_PCT may already be percent points like -7.37 or with %
    raw_dollars = [pf(r.get("PNL_DOLLARS")) or 0.0 for r in rows]
    dollars = [d * scale for d in raw_dollars]
    days = [pf(r.get("DAYS_HELD")) or 0.0 for r in rows]
    days = [d for d in days if d > 0]
    wins = sum(1 for p in pnls if p > 0)
    n = len(rows)
    ww = [p for p in pnls if p > 0]
    ll = [abs(p) for p in pnls if p < 0]
    wlr_pct = (sum(ww) / len(ww)) / (sum(ll) / len(ll)) if ww and ll else 0.0
    wd = [d for p, d in zip(pnls, dollars) if p > 0]
    ld = [abs(d) for p, d in zip(pnls, dollars) if p < 0]
    aw, al = (sum(wd) / len(wd) if wd else 0.0), (sum(ld) / len(ld) if ld else 0.0)
    win_raw = [d for p, d in zip(pnls, raw_dollars) if p > 0]
    typical_win = sum(win_raw) / len(win_raw) if win_raw else 0.0
    return {
        "total_trades": n,
        "win_rate_pct": 100.0 * wins / n,
        "avg_profit_pct": sum(pnls) / n,
        "win_loss_ratio": wlr_pct,
        "win_loss_ratio_dol": aw / al if al > 0 else aw,
        "avg_days": sum(days) / len(days) if days else 0.0,
        "total_profit": sum(dollars),
        "typical_win_raw": typical_win,
        "raw_total": sum(raw_dollars),
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

    sheet = sheet_default()
    print("SHEET DEFAULT:", sheet, flush=True)

    stamps: dict[str, Path] = {}
    for key, _label, extra in SCENARIOS:
        if key in reuse:
            p = DRIVE / f"BRT_Closed_{reuse[key]}.csv"
            if not p.exists():
                raise SystemExit(f"missing {p}")
            stamps[key] = p
            print(f"reuse {key}: {p.name}", flush=True)
        else:
            stamps[key] = run_scenario(extra)

    # Determine scale from default engine win size vs sheet $10.5k
    dflt = engine_stats(stamps["default"], 1.0)
    typ = dflt.get("typical_win_raw") or 0.0
    if typ > 0:
        scale = 10500.0 / typ
    else:
        scale = 10500.0 / 15000.0
    print(f"scale={scale:.6f} (typical eng win ${typ:.2f})", flush=True)

    results = {
        "Default": sheet,  # sheet ledger for Default
        "Min zone": engine_stats(stamps["min_zone"], scale),
        "Entry open stop": engine_stats(stamps["entry_open_stop"], scale),
        "Zone bottom": engine_stats(stamps["zone_bottom"], scale),
    }
    # Also report engine default for sanity
    eng_def = engine_stats(stamps["default"], scale)
    print("ENGINE DEFAULT (scaled):", eng_def, flush=True)

    md = [
        "# AMD Four-Scenario BRT Portfolio Stats",
        "",
        "Closed AMD trades only.",
        "",
        "- **Default** = sheet ledger (`AMD_sheet_trades.csv`); matches reconciled Default % metrics.",
        f"- Non-default from post-L AMD-only engine runs; Total Profit scaled ×({scale:.6f}) to sheet $10.5k/21% win notional.",
        "- Avg days: sheet = trigger→exit calendar days; engine = DAYS_HELD.",
        "",
        f"- default stamp: `{stamps['default'].name}`",
        f"- min_zone stamp: `{stamps['min_zone'].name}`",
        f"- entry_open stamp: `{stamps['entry_open_stop'].name}`",
        f"- zone_bottom stamp: `{stamps['zone_bottom'].name}`",
        "",
    ]
    for name, s in results.items():
        md.append(f"## {name}")
        md.append("")
        md.append("```")
        md.append(fmt_block(name, s).split("\n", 1)[1] if False else fmt_block(name, s).replace(name + "\n", ""))
        # simpler:
        md[-1] = "\n".join(
            [
                f"Total Trades\t{s['total_trades']}",
                f"Win Rate\t{s['win_rate_pct']:.1f}%",
                f"Average Profit %\t{s['avg_profit_pct']:.1f}%",
                f"Win/Loss Ratio\t{s['win_loss_ratio']:.2f}",
                f"Average Days in Trade\t{s['avg_days']:.1f}",
                f"Total Profit\t${s['total_profit']:,.2f}",
            ]
        )
        md.append("```")
        md.append("")

    out_md = OUT / "AMD_four_scenario_stats.md"
    # rewrite cleanly
    lines = [
        "# AMD Four-Scenario BRT Portfolio Stats",
        "",
        "Closed AMD trades only.",
        "",
        "- **Default** uses the sheet closed ledger (`AMD_sheet_trades.csv`) — matches reconciled engine Default % metrics.",
        f"- Non-default scenarios from post-L AMD-only engine runs; **Total Profit** scaled ×({scale:.6f}) onto sheet $10.5k / 21% win notional.",
        "- Avg days: sheet = trigger→exit calendar days; engine = `DAYS_HELD` (near but not identical).",
        "",
        f"- Stamps: default=`{stamps['default'].stem}`, min=`{stamps['min_zone'].stem}`, "
        f"entry_open=`{stamps['entry_open_stop'].stem}`, zone_bottom=`{stamps['zone_bottom'].stem}`",
        "",
    ]
    for name, s in results.items():
        lines += [
            f"## {name}",
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
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print("\n=== PASTE ===\n", flush=True)
    note = (
        "Closed AMD trades only. Default = sheet ledger (matches sheet % metrics). "
        "Non-default from post-L AMD-only engine runs; Total Profit scaled to sheet $10.5k/21% win notional. "
        "Avg days: sheet = trigger-to-exit calendar days; engine = DAYS_HELD (near but not identical)."
    )
    print(note)
    print()
    for name, s in results.items():
        print(fmt_block(name, s))
        print()
    print(f"Wrote {out_md}", flush=True)


if __name__ == "__main__":
    main()
