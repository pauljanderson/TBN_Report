#!/usr/bin/env python3
import csv
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
DRIVE = ROOT / "drive"
SHEET = ROOT / "drive" / "brt_sheet_reconcile" / "NVDA_sheet_trades.csv"
SCALE = 10_500 / 15_000


def pf(v):
    s = str(v).replace(",", "").replace("$", "").replace("%", "").strip()
    return float(s) if s else 0.0


def aggregate(rows, dollars):
    pnls = [pf(r.get("Profit %") or r.get("PNL_PCT")) for r in rows]
    days = [
        pf(r.get("Days In Trade") or r.get("DAYS_HELD"))
        for r in rows
        if pf(r.get("Days In Trade") or r.get("DAYS_HELD")) > 0
    ]
    wins = sum(1 for p in pnls if p > 0)
    n = len(rows)
    wd = [d for p, d in zip(pnls, dollars) if p > 0]
    ld = [abs(d) for p, d in zip(pnls, dollars) if p < 0]
    aw = sum(wd) / len(wd) if wd else 0.0
    al = sum(ld) / len(ld) if ld else 0.0
    wlr = aw / al if al > 0 else aw
    return {
        "total_trades": n,
        "win_rate_pct": 100.0 * wins / n,
        "avg_profit_pct": sum(pnls) / n,
        "win_loss_ratio": wlr,
        "avg_days": sum(days) / len(days) if days else 0.0,
        "total_profit": sum(dollars),
    }


def sheet_default():
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
    dollars = [pf(r["Profit per trade"]) for r in rows]
    return aggregate(rows, dollars)


def engine(stamp: str):
    path = DRIVE / f"BRT_Closed_{stamp}.csv"
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8-sig")) if r["SYMBOL"] == "NVDA"]
    dollars = [pf(r["PNL_DOLLARS"]) * SCALE for r in rows]
    return aggregate(rows, dollars)


def fmt_pct(x):
    return f"{x:.1f}%"


def fmt_money(x):
    return f"${x:,.2f}"


def block(name, s):
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


def main():
    note = (
        "Closed NVDA trades only. Default = sheet ledger (matches sheet % metrics). "
        "Non-default from post-L NVDA-only engine runs; Total Profit scaled x(10.5k/15k) to sheet $10.5k/21% win notional. "
        "Avg days: sheet = trigger-to-exit calendar days; engine = DAYS_HELD (near but not identical)."
    )
    lines = [note, ""]
    lines.extend(block("Default", sheet_default()))
    lines.extend(block("Min zone", engine("260720203024")))
    lines.extend(block("Entry open stop", engine("260720203039")))
    lines.extend(block("Zone bottom", engine("260720203043")))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
