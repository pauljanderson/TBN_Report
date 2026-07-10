#!/usr/bin/env python3
"""Compare two active-zone TSV exports (old 10-rung vs new unlimited).

Usage:
  python tools/compare_zone_exports.py old.tsv new.tsv

Each line: lower<TAB>upper<TAB>avail_row<TAB>zone_id  (blank = inactive)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def parse_row(line: str) -> tuple[Optional[float], Optional[float], Optional[int], Optional[int]]:
    parts = line.rstrip("\n").split("\t")
    parts += [""] * (4 - len(parts))

    def money(s: str) -> Optional[float]:
        s = s.strip().replace("$", "").replace(",", "")
        if not s:
            return None
        return float(s)

    lo, hi, avail, zid = parts[:4]
    return (
        money(lo),
        money(hi),
        int(avail) if avail.strip().isdigit() else None,
        int(zid) if zid.strip().isdigit() else None,
    )


def key(lo, hi, avail) -> Optional[tuple]:
    if lo is None:
        return None
    return (round(lo, 2), round(hi, 2), avail)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    old_path, new_path = Path(sys.argv[1]), Path(sys.argv[2])
    old_lines = old_path.read_text(encoding="utf-8").splitlines()
    new_lines = new_path.read_text(encoding="utf-8").splitlines()
    n = min(len(old_lines), len(new_lines))

    same_all = dn_only = resurfaced = different_zone = old_blank_new_active = 0
    dn_gt10 = 0
    examples: list[str] = []

    for i in range(n):
        o = parse_row(old_lines[i])
        nw = parse_row(new_lines[i])
        ok, nk = key(*o[:3]), key(*nw[:3])

        if ok is None and nk is None:
            same_all += 1
            continue
        if ok == nk and o[3] == nw[3]:
            same_all += 1
            continue
        if ok == nk and o[3] != nw[3]:
            dn_only += 1
            if nw[3] and nw[3] > 10:
                dn_gt10 += 1
            if len(examples) < 8:
                examples.append(
                    f"  bar {i+1}: same zone {ok} DN {o[3]} -> {nw[3]}"
                )
            continue
        if ok is None and nk is not None:
            old_blank_new_active += 1
            resurfaced += 1
            if len(examples) < 12:
                examples.append(f"  bar {i+1}: old blank -> new {nk} DN={nw[3]}")
            continue
        if ok is not None and nk is not None and ok != nk:
            different_zone += 1
            if len(examples) < 16:
                examples.append(f"  bar {i+1}: old {ok} DN={o[3]} -> new {nk} DN={nw[3]}")
            continue
        if ok is not None and nk is None:
            if len(examples) < 18:
                examples.append(f"  bar {i+1}: old {ok} -> new blank")

    print(f"Bars compared: {n}")
    print(f"Identical (DK/DL/DM/DN):     {same_all}")
    print(f"Same zone, DN only changed:  {dn_only}  (of which DN>10: {dn_gt10})")
    print(f"Old blank, new active:       {old_blank_new_active}  (resurfaced / bumped-back zones)")
    print(f"Different active zone:       {different_zone}")
    if examples:
        print("\nExamples:")
        print("\n".join(examples))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
