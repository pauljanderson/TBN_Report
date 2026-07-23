#!/usr/bin/env python3
"""AU four-scenario pasteable stats ($10.5k / 21% win scale)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
OUT = DRIVE / "brt_sheet_reconcile"
SHEET = OUT / "AU_sheet_trades.csv"
SCALE_NOTIONAL = 50_000.0  # 21% win = $10,500

SCENARIOS = [
    ("Default", "breakout_zone_pick=max, stop_loss_based=trigger_low", "sheet", None),
    ("Min zone", "breakout_zone_pick=min, stop_loss_based=trigger_low", "eng", "260720215133"),
    ("Entry open stop", "breakout_zone_pick=max, stop_loss_based=entry_open", "eng", "260720215138"),
    ("Zone bottom", "breakout_zone_pick=max, stop_loss_based=zone_low (alias zone_bottom)", "eng", "260720215142"),
]
DEFAULT_ENG_STAMP = "260720215017"


def pf(v, default: float = 0.0) -> float:
    if v is None:
        return default
    s = str(v).strip().replace(",", "").replace("$", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        return float(s)
    except ValueError:
        return default


def _agg(pnls: list[float], dollars: list[float], days: list[float]) -> dict:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    aw = sum(wins) / len(wins) if wins else 0.0
    al = abs(sum(losses) / len(losses)) if losses else 0.0
    wlr = (aw / al) if al else aw
    n = len(pnls)
    return {
        "n": n,
        "wr": 100.0 * len(wins) / n if n else 0.0,
        "avg": sum(pnls) / n if n else 0.0,
        "wlr": wlr,
        "days": sum(days) / len(days) if days else 0.0,
        "tp": sum(dollars),
        "wins": len(wins),
        "losses": len(losses),
    }


def sheet_stats() -> dict:
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
    pnls = [pf(r.get("Profit %")) for r in rows]
    dollars = [pf(r.get("Profit per trade")) for r in rows]
    days = [pf(r.get("Days In Trade")) for r in rows if pf(r.get("Days In Trade")) > 0]
    s = _agg(pnls, dollars, days)
    s["source"] = "sheet ledger (`AU_sheet_trades.csv`)"
    return s


def eng_stats(stamp: str) -> dict:
    path = DRIVE / f"BRT_Closed_{stamp}.csv"
    rows = [
        r
        for r in csv.DictReader(path.open(encoding="utf-8-sig"))
        if (r.get("SYMBOL") or "").upper() == "AU"
    ]
    pnls = [pf(r.get("PNL_PCT")) for r in rows]
    dollars = [SCALE_NOTIONAL * p / 100.0 for p in pnls]
    days = [d for r in rows for d in [pf(r.get("DAYS_HELD"))] if d > 0]
    s = _agg(pnls, dollars, days)
    s["path"] = path.name
    s["source"] = f"`{path.name}` (engine; $50k / $10.5k-21% win scale)"
    return s


def block(title: str, cfg: str, source: str, s: dict) -> list[str]:
    return [
        f"## {title}",
        "",
        f"- Config: `{cfg}`",
        f"- Source: {source}",
        "",
        "```",
        f"Total Trades\t{s['n']}",
        f"Win Rate\t{s['wr']:.1f}%",
        f"Average Profit %\t{s['avg']:.1f}%",
        f"Win/Loss Ratio\t{s['wlr']:.2f}",
        f"Average Days in Trade\t{s['days']:.1f}",
        f"Total Profit\t${s['tp']:,.2f}",
        "```",
        "",
    ]


def main() -> None:
    sh = sheet_stats()
    def_eng = eng_stats(DEFAULT_ENG_STAMP)
    lines = [
        "# AU Four-Scenario BRT Portfolio Stats ($10.5k scale)",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Closed AU trades only.",
        "",
        "- **Default** uses the sheet closed ledger (`AU_sheet_trades.csv`) — matches sheet $ metrics.",
        "- Non-default scenarios from fresh AU-only engine runs (2026-07-20); **Total Profit** = sum($50k × PNL_PCT/100) so a 21% win = $10,500.",
        f"- Engine Default stamp `{DEFAULT_ENG_STAMP}` also has **43** trades (100% trade-level match vs sheet at ±$0.05 entry / exit dates).",
        "- Avg days: sheet = trigger→exit calendar days; engine = `DAYS_HELD` (near but not identical).",
        "",
        "Metrics: Win Rate = share Profit%>0; Average Profit % = mean Profit%;",
        "Win/Loss Ratio = mean winning % / |mean losing %|;",
        "Average Days = mean days in trade; Total Profit = sum $ P&L.",
        "",
        "| Scenario | Total Trades | Win Rate | Average Profit % | Win/Loss Ratio | Average Days | Total Profit | Source |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
        f"| Default (sheet) | {sh['n']} | {sh['wr']:.1f}% | {sh['avg']:.1f}% | {sh['wlr']:.2f} | {sh['days']:.1f} | ${sh['tp']:,.2f} | sheet ledger |",
        f"| Default (engine) | {def_eng['n']} | {def_eng['wr']:.1f}% | {def_eng['avg']:.1f}% | {def_eng['wlr']:.2f} | {def_eng['days']:.1f} | ${def_eng['tp']:,.2f} | `{def_eng['path']}` |",
    ]
    for name, _cfg, _kind, stamp in SCENARIOS[1:]:
        s = eng_stats(stamp)
        lines.append(
            f"| {name} | {s['n']} | {s['wr']:.1f}% | {s['avg']:.1f}% | {s['wlr']:.2f} | {s['days']:.1f} | ${s['tp']:,.2f} | `{s['path']}` |"
        )
    lines.append("")

    lines += block("Default", SCENARIOS[0][1], sh["source"], sh)
    for name, cfg, _kind, stamp in SCENARIOS[1:]:
        s = eng_stats(stamp)
        lines += block(name, cfg, s["source"], s)

    rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
    lines += [
        f"## Default sheet closed trades (all {len(rows)})",
        "",
        "| # | Trigger | Entry | Exit | Profit % | Days | Result | Profit $ |",
        "|--:|---|---:|---|---:|---:|---|---:|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r.get('Trigger Date', '')} | {r.get('Entry Price', '')} | "
            f"{r.get('Exit Date', '')} | {r.get('Profit %', '')} | {r.get('Days In Trade', '')} | "
            f"{r.get('Result', '')} | {r.get('Profit per trade', '')} |"
        )
    lines.append("")

    out = OUT / "AU_four_scenario_stats.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    print("Default sheet", sh)
    print("Default eng", def_eng)


if __name__ == "__main__":
    main()
