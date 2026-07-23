#!/usr/bin/env python3
"""Compute NVDA four-scenario stats from closed CSVs + sheet ledger."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "drive"
OUT = DRIVE / "brt_sheet_reconcile"
SHEET_TRADES = OUT / "NVDA_sheet_trades.csv"
SCALE = 10_500 / 15_000  # sheet $10.5k win vs engine $15k default


def parse_float(val: object, default: float = 0.0) -> float:
    if val is None:
        return default
    s = str(val).strip().replace(",", "").replace("$", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        return float(s)
    except ValueError:
        return default


def sheet_stats() -> dict:
    rows = list(csv.DictReader(SHEET_TRADES.open(encoding="utf-8")))
    pnls = [parse_float(r["Profit %"]) for r in rows]
    dollars = [parse_float(r["Profit per trade"]) for r in rows]
    days = [parse_float(r["Days In Trade"]) for r in rows if parse_float(r["Days In Trade"]) > 0]
    wins = sum(1 for p in pnls if p > 0)
    n = len(rows)
    win_d = [d for p, d in zip(pnls, dollars) if p > 0]
    loss_d = [abs(d) for p, d in zip(pnls, dollars) if p < 0]
    aw = sum(win_d) / len(win_d) if win_d else 0.0
    al = sum(loss_d) / len(loss_d) if loss_d else 0.0
    wlr = (aw / al) if al > 0 else aw
    return {
        "total_trades": n,
        "win_rate_pct": 100.0 * wins / n,
        "avg_profit_pct": sum(pnls) / n,
        "win_loss_ratio": wlr,
        "avg_days": sum(days) / len(days) if days else 0.0,
        "total_profit": sum(dollars),
        "source": "sheet ledger (NVDA_sheet_trades.csv)",
    }


def engine_stats(closed_path: Path, scale: float = SCALE) -> dict:
    rows = [
        r
        for r in csv.DictReader(closed_path.open(encoding="utf-8-sig"))
        if (r.get("SYMBOL") or "").strip().upper() == "NVDA"
    ]
    n = len(rows)
    if n == 0:
        return {"total_trades": 0}
    pnls = [parse_float(r.get("PNL_PCT")) for r in rows]
    dollars = [parse_float(r.get("PNL_DOLLARS")) * scale for r in rows]
    days = [
        d
        for r in rows
        for d in [parse_float(r.get("DAYS_HELD"))]
        if d > 0
    ]
    wins = sum(1 for p in pnls if p > 0)
    win_d = [d for p, d in zip(pnls, dollars) if p > 0]
    loss_d = [abs(d) for p, d in zip(pnls, dollars) if p < 0]
    aw = sum(win_d) / len(win_d) if win_d else 0.0
    al = sum(loss_d) / len(loss_d) if loss_d else 0.0
    wlr = (aw / al) if al > 0 else aw
    return {
        "total_trades": n,
        "win_rate_pct": 100.0 * wins / n,
        "avg_profit_pct": sum(pnls) / n,
        "win_loss_ratio": wlr,
        "avg_days": sum(days) / len(days) if days else 0.0,
        "total_profit": sum(dollars),
        "source": f"{closed_path.name} (engine; $ scaled ×{scale:.4f})",
    }


def fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def fmt_pct(x: float) -> str:
    return f"{x:.1f}%"


def block(name: str, s: dict) -> list[str]:
    return [
        name,
        f"Total Trades\t{s['total_trades']}",
        f"Win Rate\t{fmt_pct(s['win_rate_pct'])}",
        f"Average Profit %\t{fmt_pct(s['avg_profit_pct'])}",
        f"Win/Loss Ratio\t{s['win_loss_ratio']:.2f}",
        f"Average Days in Trade\t{s['avg_days']:.1f}",
        f"Total Profit\t{fmt_money(s['total_profit'])}",
        "",
    ]


def main() -> None:
    # Candidate stamps — newest first
    candidates = sorted(DRIVE.glob("BRT_Closed_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    print("=== All closed files NVDA trade counts ===")
    for p in candidates[:25]:
        st = engine_stats(p, scale=1.0)
        print(f"  {p.stem.replace('BRT_Closed_', '')}: {st.get('total_trades', 0)} trades")

    default_sheet = sheet_stats()
    default_eng = engine_stats(DRIVE / "BRT_Closed_260720194240.csv")

    print("\n=== Default: sheet vs engine 260720194240 ===")
    print(f"  sheet: {default_sheet['total_trades']} trades, {default_sheet['win_rate_pct']:.1f}% WR")
    print(f"  engine: {default_eng['total_trades']} trades, {default_eng['win_rate_pct']:.1f}% WR")

    # Map four scenarios — try known pre-L stamps and recent 1857xx batch
    scenario_stamps = {
        "default": ("260720194240", default_sheet),
        "min_zone": None,
        "entry_open_stop": None,
        "zone_bottom_stop": None,
    }

    # Heuristic: find 3 other distinct NVDA trade-count profiles among recent full-universe runs
    # Known four-scenario stamps from NFLX run (pre-L): 165440, 165458, 165516
    known = {
        "min_zone": "260720165440",
        "entry_open_stop": "260720165458",
        "zone_bottom_stop": "260720165516",
    }
    for key, stamp in known.items():
        p = DRIVE / f"BRT_Closed_{stamp}.csv"
        if p.exists():
            scenario_stamps[key] = (stamp, engine_stats(p))

    print("\n=== Paste blocks ===")
    note = (
        "Closed NVDA trades only. Default = sheet ledger (matches sheet % metrics). "
        "Non-default from engine Closed CSVs; Total Profit scaled ×(10.5k/15k) to sheet $10.5k/21% win notional. "
        "Avg days: sheet = trigger→exit calendar days; engine = DAYS_HELD (near but not identical)."
    )
    lines = [note, ""]
    lines.extend(block("Default", default_sheet))
    for label, key in [
        ("Min zone", "min_zone"),
        ("Entry open stop", "entry_open_stop"),
        ("Zone bottom", "zone_bottom_stop"),
    ]:
        entry = scenario_stamps.get(key)
        if entry and entry[1]:
            lines.extend(block(label, entry[1]))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
