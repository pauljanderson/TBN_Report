"""Measure TARGET->next IN gaps for NTRA ladder vs post_target_quick_stop fails."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PATH = Path(r"drive/RL_Closed_260730094107.csv")


def col(r, *names):
    upper = {k.upper().replace("_", " "): v for k, v in r.items()}
    for n in names:
        key = n.upper().replace("_", " ")
        if key in upper and upper[key] not in (None, ""):
            return upper[key]
    return ""


def ymd(s: str) -> str:
    s = str(s).strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def parse(s: str):
    s = ymd(s)
    return datetime.strptime(s, "%Y%m%d") if s else None


def gap_days(a, b):
    da, db = parse(a), parse(b)
    return (db - da).days if da and db else None


def main() -> None:
    with PATH.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print("n_rows", len(rows))
    print("cols", list(rows[0].keys())[:25])

    by: dict[str, list] = defaultdict(list)
    for r in rows:
        sym = str(col(r, "SYMBOL")).strip().upper()
        if sym:
            by[sym].append(r)
    for sym in by:
        by[sym].sort(
            key=lambda r: (
                ymd(col(r, "DATE OPENED", "DATE_OPENED")),
                ymd(col(r, "DATE CLOSED", "DATE_CLOSED")),
            )
        )

    def dump_symbol(sym: str, year_min: str = "", year_max: str = "") -> None:
        print(f"\n=== {sym} trades ===")
        trades = by.get(sym, [])
        for i, r in enumerate(trades):
            do = col(r, "DATE OPENED", "DATE_OPENED")
            dc = col(r, "DATE CLOSED", "DATE_CLOSED")
            y = ymd(do)
            if year_min and y < year_min:
                continue
            if year_max and y > year_max:
                continue
            et = str(col(r, "EXIT TYPE", "EXIT_TYPE")).upper()
            print(
                f"  {do}->{dc} {et} held={col(r, 'DAYS HELD', 'DAYS_HELD')} "
                f"pnl={col(r, 'PNL %', 'PNL_PCT')}"
            )
            if i + 1 < len(trades):
                # find next among full list by object identity after filter skip
                pass
        # gaps for all TARGET exits
        for i, r in enumerate(trades):
            et = str(col(r, "EXIT TYPE", "EXIT_TYPE")).upper()
            if "TARGET" not in et:
                continue
            dc = col(r, "DATE CLOSED", "DATE_CLOSED")
            if year_min and ymd(dc) < year_min:
                continue
            if year_max and ymd(dc) > year_max:
                continue
            if i + 1 < len(trades):
                nxt = trades[i + 1]
                g = gap_days(dc, col(nxt, "DATE OPENED", "DATE_OPENED"))
                print(
                    f"  TARGET_out={dc} -> IN={col(nxt, 'DATE OPENED', 'DATE_OPENED')} "
                    f"gap={g}d next_exit={col(nxt, 'EXIT TYPE', 'EXIT_TYPE')} "
                    f"held={col(nxt, 'DAYS HELD', 'DAYS_HELD')}"
                )

    dump_symbol("NTRA")
    print("\n--- NTRA 2019 window focus ---")
    dump_symbol("NTRA", "20180701", "20201231")
    print("\n--- AU 2024+ ---")
    dump_symbol("AU", "20240101")

    # All TARGET -> next IN gaps (any next exit)
    ladder_like = []
    for sym, trades in by.items():
        for i, r in enumerate(trades):
            et = str(col(r, "EXIT TYPE", "EXIT_TYPE")).upper()
            if "TARGET" not in et:
                continue
            if i + 1 >= len(trades):
                continue
            nxt = trades[i + 1]
            g = gap_days(col(r, "DATE CLOSED", "DATE_CLOSED"), col(nxt, "DATE OPENED", "DATE_OPENED"))
            if g is None:
                continue
            nxt_et = str(col(nxt, "EXIT TYPE", "EXIT_TYPE")).upper()
            nxt_days = int(float(col(nxt, "DAYS HELD", "DAYS_HELD") or 0))
            ladder_like.append((sym, g, nxt_et, nxt_days, col(r, "DATE CLOSED", "DATE_CLOSED"), col(nxt, "DATE OPENED", "DATE_OPENED")))

    fails = [x for x in ladder_like if "STOP" in x[2] and x[3] <= 10]
    successes_next = [x for x in ladder_like if "TARGET" in x[2] or ("STOP" not in x[2])]
    # NTRA/AU TARGET->any re-entry
    preserve = [x for x in ladder_like if x[0] in ("NTRA", "AU")]

    def stats(xs, label):
        gs = sorted(x[1] for x in xs)
        if not gs:
            print(f"{label}: empty")
            return
        def pct(p):
            return gs[min(len(gs) - 1, int(len(gs) * p))]
        print(
            f"{label}: n={len(gs)} min={gs[0]} p10={pct(0.1)} p25={pct(0.25)} "
            f"med={pct(0.5)} p75={pct(0.75)} p90={pct(0.9)} max={gs[-1]}"
        )

    print("\n=== gap stats TARGET_out -> next_IN (calendar days) ===")
    stats(fails, "post_target_quick_stop fails")
    stats([x for x in ladder_like if "TARGET" in x[2]], "TARGET then next also TARGET")
    stats(preserve, "NTRA+AU all TARGET->next IN")
    stats([x for x in preserve if x[0] == "NTRA"], "NTRA only")
    stats([x for x in preserve if x[0] == "AU"], "AU only")

    print("\n=== fail pairs detail (sorted by gap) ===")
    for x in sorted(fails, key=lambda t: (t[1], t[0])):
        print(f"  {x[0]} gap={x[1]}d TARGET_out={x[4]} IN={x[5]} next={x[2]} held={x[3]}d")

    print("\n=== NTRA TARGET->next IN all ===")
    for x in [t for t in ladder_like if t[0] == "NTRA"]:
        print(f"  gap={x[1]}d TARGET_out={x[4]} IN={x[5]} next={x[2]} held={x[3]}d")

    print("\n=== AU TARGET->next IN all ===")
    for x in [t for t in ladder_like if t[0] == "AU"]:
        print(f"  gap={x[1]}d TARGET_out={x[4]} IN={x[5]} next={x[2]} held={x[3]}d")

    # Separability: what cooldown would kill how many fails vs NTRA/AU
    print("\n=== cooldown separability (block if gap < CD) ===")
    ntra_gaps = [x[1] for x in ladder_like if x[0] == "NTRA"]
    au_gaps = [x[1] for x in ladder_like if x[0] == "AU"]
    fail_gaps = [x[1] for x in fails]
    for cd in [3, 5, 7, 10, 14, 21, 28, 35, 42, 60]:
        kill_fail = sum(1 for g in fail_gaps if g < cd)
        kill_ntra = sum(1 for g in ntra_gaps if g < cd)
        kill_au = sum(1 for g in au_gaps if g < cd)
        print(
            f"  CD={cd:2d}d  kills_fails={kill_fail}/{len(fail_gaps)} "
            f"kills_NTRA_reentries={kill_ntra}/{len(ntra_gaps)} "
            f"kills_AU_reentries={kill_au}/{len(au_gaps)}"
        )

    # Also measure extension / cut_the_losers proxy if columns exist
    sample_cols = [c for c in rows[0].keys() if any(k in c.upper() for k in ("CUT", "SLOPE", "SMA", "DIP", "HI", "PEAK", "ATR"))]
    print("\nrelevant closed cols:", sample_cols)


if __name__ == "__main__":
    main()
