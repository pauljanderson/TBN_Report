#!/usr/bin/env python3
"""Parse STONK_DATA MTS tab paste (CE triplets + trade rows) into ground-truth files."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
CE_DIR = _REPO / "sheet_ce_ground_truth"
EXPORT = Path(__file__).with_name("multisym_sheet_export.txt")

# zone-lower column in triplet rows: $touch\t$lower\t$upper
_TRIPLET = re.compile(
    r"^\$?([\d.]+)\s+\$?([\d.]+)\s+\$?([\d.]+)\s*$"
)
# trade row after "Trigger Date" header
_TRADE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4})\s+\$?([\d.]+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+\$?([\d.]+)\s+(-?[\d.]+)%\s+(\d+)\s+(WIN|LOSS)\s",
    re.I,
)


def r2(x: float) -> str:
    v = float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return f"{v:.2f}"


@dataclass
class ParsedSym:
    symbol: str
    ce_raw: list[float]
    trades: list[tuple]


def parse_export(text: str) -> dict[str, ParsedSym]:
    out: dict[str, ParsedSym] = {}
    sym: str | None = None
    ce: list[float] = []
    trades: list[tuple] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # symbol header (bare ticker)
        if re.fullmatch(r"[A-Z]{1,5}", line) and line not in ("WIN", "LOSS"):
            if sym and (ce or trades):
                out[sym] = ParsedSym(sym, ce, trades)
            sym = line
            ce, trades = [], []
            continue
        if sym is None:
            continue
        if line.startswith("Matured touch") or line.startswith("Trigger Date"):
            continue
        m = _TRIPLET.match(line.replace("\t", " ").replace("  ", " "))
        if m:
            ce.append(float(m.group(2)))
            continue
        # normalize tabs for trade rows
        tline = re.sub(r"\s+", "\t", line.strip())
        parts = tline.split("\t")
        if len(parts) >= 7 and "/" in parts[0]:
            try:
                d0 = parts[0]
                ep = float(parts[1].replace("$", ""))
                d1 = parts[2]
                xp = float(parts[3].replace("$", ""))
                pnl = float(parts[4].replace("%", ""))
                days = int(parts[5])
                res = parts[6].upper()
                trades.append((d0, ep, d1, xp, pnl, days, res))
            except (ValueError, IndexError):
                pass

    if sym and (ce or trades):
        out[sym] = ParsedSym(sym, ce, trades)
    return out


def mdy(s: str) -> date:
    mo, da, yr = s.split("/")
    return date(int(yr), int(mo), int(da))


def write_ce(sym: str, raw: list[float]) -> list[str]:
    rounded = [r2(x) for x in raw]
    path = CE_DIR / f"{sym}_ce.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rounded) + "\n")
    return rounded


def emit_trades_py(trades_map: dict[str, ParsedSym]) -> str:
    lines = ["REFERENCE: dict[str, list[SheetRow]] = {"]
    for sym in sorted(trades_map):
        ps = trades_map[sym]
        if not ps.trades:
            continue
        lines.append(f'    "{sym}": [')
        for d0, ep, d1, xp, pnl, days, res in ps.trades:
            ed = mdy(d0)
            xd = mdy(d1)
            lines.append(
                f"        SheetRow(date({ed.year}, {ed.month}, {ed.day}), {ep:.2f}, "
                f"date({xd.year}, {xd.month}, {xd.day}), {xp:.2f}, {pnl:.2f}, {days}, {res!r}),"
            )
        lines.append("    ],")
    lines.append("}")
    return "\n".join(lines)


def main() -> int:
    src = EXPORT if EXPORT.exists() else None
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
    if src is None or not src.exists():
        print(f"Usage: {Path(__file__).name} [export.txt]", file=sys.stderr)
        print(f"Expected default: {EXPORT}", file=sys.stderr)
        return 1

    parsed = parse_export(src.read_text(encoding="utf-8", errors="replace"))
    print(f"Parsed {len(parsed)} symbols from {src}")
    for sym, ps in sorted(parsed.items()):
        ce = write_ce(sym, ps.ce_raw)
        print(f"  {sym}: {len(ce)} CE, {len(ps.trades)} trades")
        if ps.trades:
            for t in ps.trades:
                print(f"    trade {t[0]} ${t[1]:.2f} -> {t[2]} ${t[3]:.2f} {t[4]:+.2f}%")

    out_py = _REPO / "tools" / "_multisym_trades_reference_snippet.py"
    trade_syms = {k: v for k, v in parsed.items() if v.trades}
    out_py.write_text(emit_trades_py(trade_syms) + "\n")
    print(f"\nWrote trade snippet -> {out_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
