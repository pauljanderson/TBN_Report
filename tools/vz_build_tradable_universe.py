#!/usr/bin/env python3
"""Build VZ tradable universe from OHLC traits (no VZ PnL / Paul).

Freeze (v1):
  - local CSV under data/newdata/data
  - first bar on or before 2010-01-04
  - as-of 2023-12-29 (last session on/before that date):
      Close >= $5
      20-session ADV$ = mean(Close * Volume) >= $2,000,000
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "newdata" / "data"
OUT = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
REJECT = ROOT / "drive" / "paul_experiments" / "vz_tradable_2010_adv2m_20260818" / "universe_rejects.csv"

FIRST_BAR_MAX = date(2010, 1, 4)
ASOF = date(2023, 12, 29)
MIN_CLOSE = 5.0
MIN_ADV = 2_000_000.0
ADV_BARS = 20


def _parse_d(s: str) -> date | None:
    s = str(s or "").strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _f(v: object) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def screen_csv(path: Path) -> tuple[bool, dict[str, object]]:
    sym = path.stem.upper()
    first: date | None = None
    asof_i = -1
    dates: list[date] = []
    closes: list[float] = []
    vols: list[float] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            d = _parse_d(row.get("Date") or row.get("DATE") or "")
            if d is None:
                continue
            if first is None:
                first = d
            dates.append(d)
            closes.append(_f(row.get("Close") or row.get("CLOSE")))
            vols.append(_f(row.get("Volume") or row.get("VOLUME")))
            if d <= ASOF:
                asof_i = len(dates) - 1
    rec: dict[str, object] = {
        "SYMBOL": sym,
        "first_bar": first.isoformat() if first else "",
        "asof_date": dates[asof_i].isoformat() if asof_i >= 0 else "",
        "asof_close": closes[asof_i] if asof_i >= 0 else "",
        "adv20_usd": "",
        "pass": "N",
        "reason": "",
    }
    if first is None:
        rec["reason"] = "empty"
        return False, rec
    if first > FIRST_BAR_MAX:
        rec["reason"] = f"first_bar>{FIRST_BAR_MAX.isoformat()}"
        return False, rec
    if asof_i < 0:
        rec["reason"] = "no bars on/before as-of"
        return False, rec
    px = closes[asof_i]
    rec["asof_close"] = round(px, 4)
    if px < MIN_CLOSE:
        rec["reason"] = f"close<{MIN_CLOSE}"
        return False, rec
    start = asof_i - ADV_BARS + 1
    if start < 0:
        rec["reason"] = f"adv_bars<{ADV_BARS}"
        return False, rec
    doll = [closes[i] * vols[i] for i in range(start, asof_i + 1)]
    adv = sum(doll) / len(doll)
    rec["adv20_usd"] = round(adv, 2)
    if adv < MIN_ADV:
        rec["reason"] = f"adv20<{MIN_ADV:.0f}"
        return False, rec
    rec["pass"] = "Y"
    rec["reason"] = "pass"
    return True, rec


def main() -> int:
    files = sorted(DATA.glob("*.csv"))
    kept: list[str] = []
    rows: list[dict[str, object]] = []
    for p in files:
        ok, rec = screen_csv(p)
        rows.append(rec)
        if ok:
            kept.append(str(rec["SYMBOL"]))
    REJECT.parent.mkdir(parents=True, exist_ok=True)
    with REJECT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["SYMBOL", "first_bar", "asof_date", "asof_close", "adv20_usd", "pass", "reason"],
        )
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: str(r["SYMBOL"])))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        f.write("# VZ tradable universe v1 — RESEARCH (not gold / not DailyRun)\n")
        f.write("# Traits only (no VZ PnL / Paul / FIT). Frozen as-of 2023-12-29.\n")
        f.write("# first_bar <= 2010-01-04; Close >= 5; 20d ADV$ >= 2000000 (Close*Volume mean)\n")
        f.write("SYMBOL\n")
        for s in kept:
            f.write(f"{s}\n")
    n_pass = len(kept)
    n_fail = len(rows) - n_pass
    print(f"scanned={len(rows)} pass={n_pass} fail={n_fail}")
    print(f"universe={OUT}")
    print(f"rejects={REJECT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
