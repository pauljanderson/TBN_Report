#!/usr/bin/env python3
"""Compare sheet-vs-engine zone gaps: prior deep stamp vs new stamp."""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "drive" / "brt_sheet_reconcile"
DRIVE = ROOT / "drive"
TOOLS = ROOT / "tools"
WIN_START, WIN_END = date(2010, 1, 4), date(2026, 6, 5)
PRIOR = {
    "AAPL": "260720143523",
    "AMZN": "260720185855",
    "GOOGL": "260720143523",
    "META": "260721152701",
    "MSFT": "260720143523",
    "NVDA": "260720194240",
    "TSLA": "260720111055",
    "AU": "260720215017",
    "AMD": "260720165857",
    "NFLX": "260720183518",
}
STAMP = "260722175102"


def parse_date(s):
    if s is None:
        return None
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        n = int(s)
        if 19000101 <= n <= 21001231:
            try:
                return datetime.strptime(str(n), "%Y%m%d").date()
            except ValueError:
                return None
    s = str(s).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    if s.endswith(".0"):
        s = s[:-2]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(s):
    if s is None:
        return None
    try:
        return round(float(str(s).strip().replace("$", "").replace(",", "")), 4)
    except ValueError:
        return None


def uniq(rows):
    seen = set()
    out = []
    for r in rows:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out


def load_sheet_zones(sym):
    for p in (OUT / f"{sym}_sheet_zones.csv", TOOLS / f"{sym.lower()}_brt_sheet_zones.tsv"):
        if not p.is_file():
            continue
        rows = []
        text = p.read_text(encoding="utf-8-sig")
        first = text.splitlines()[0]
        delim = "\t" if "\t" in first else ","
        for r in csv.DictReader(text.splitlines(), delimiter=delim):
            km = {k.lower(): k for k in r}

            def g(*ns):
                for n in ns:
                    if n in km:
                        return r[km[n]]
                    for lk, ok in km.items():
                        if n in lk:
                            return r[ok]
                return None

            c = parse_money(g("touch", "center"))
            lo = parse_money(g("lower"))
            hi = parse_money(g("upper"))
            if None in (c, lo, hi):
                continue
            rows.append((round(c, 2), round(lo, 2), round(hi, 2)))
        return uniq(rows)
    return []


def load_eng(sym, stamp):
    p = DRIVE / f"BRT_ZONES_{sym}_{stamp}.csv"
    if not p.is_file():
        return []
    rows = []
    with p.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            mat = str(r.get("MATURED_NOW", "")).strip()
            if mat and mat not in ("1", "1.0", "True", "true"):
                continue
            d = parse_date(r.get("MATURITY_DATE") or r.get("DATE"))
            if d and not (WIN_START <= d <= WIN_END):
                continue
            c = parse_money(r.get("ZONE_CENTER"))
            lo = parse_money(r.get("ZONE_LOW"))
            hi = parse_money(r.get("ZONE_HIGH"))
            if None in (c, lo, hi):
                continue
            rows.append((round(c, 2), round(lo, 2), round(hi, 2)))
    return uniq(rows)


def match(sheet, eng, tol=0.02):
    rem = list(eng)
    m = 0
    so = []
    for s in sheet:
        bi = None
        for i, e in enumerate(rem):
            if max(abs(s[0] - e[0]), abs(s[1] - e[1]), abs(s[2] - e[2])) <= tol + 1e-9:
                bi = i
                break
        if bi is None:
            so.append(s)
        else:
            m += 1
            rem.pop(bi)
    return m, len(sheet), so, rem


def main():
    print("SYM    prior_match  new_match   gap_same")
    for sym in PRIOR:
        sh = load_sheet_zones(sym)
        pm, ps, p_so, p_eo = match(sh, load_eng(sym, PRIOR[sym]))
        nm, ns, n_so, n_eo = match(sh, load_eng(sym, STAMP))
        same = pm == nm and p_so == n_so and p_eo == n_eo
        print(
            f"{sym:6} {pm}/{ps:<3}        {nm}/{ns:<3}       {same}  "
            f"prior_so={p_so[:3]} new_so={n_so[:3]} prior_eo={len(p_eo)} new_eo={len(n_eo)}"
        )


if __name__ == "__main__":
    main()
