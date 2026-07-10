#!/usr/bin/env python3
"""Trace why sheet skips 2022-05-19 trigger vs engine 2022-05-20 entry."""
from __future__ import annotations

import glob
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def parse_mdy(s: str) -> str:
    s = str(s).strip()
    if not s or s == "nan":
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    if "/" in s:
        m, d, y = s.split("/")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return ""


def latest_run_id() -> str:
    runs = sorted(
        glob.glob(str(ROOT / "drive" / "YH_Closed_*.csv")),
        key=lambda p: Path(p).stat().st_mtime,
        reverse=True,
    )
    return Path(runs[0]).stem.replace("YH_Closed_", "")


def main() -> None:
    run_id = latest_run_id()
    print(f"Run: {run_id}\n")

    meta = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"]).sort_values("Date")
    iso = [d.strftime("%Y-%m-%d") for d in meta["Date"]]
    op = meta["Open"].to_numpy(float)
    cl = meta["Close"].to_numpy(float)
    hi = meta["High"].to_numpy(float)
    lo = meta["Low"].to_numpy(float)

    rt = pd.read_csv(ROOT / f"drive/YH_breakout_and_retest_{run_id}.csv")
    rt = rt[rt["SYMBOL"] == "TSLA"]
    rets = {parse_mdy(s) for s in rt["Retest Date"] if parse_mdy(str(s))}
    gb = 756

    def gates(d: str) -> dict:
        i = iso.index(d)
        j = i - 1
        g = {
            "AG": cl[i] > op[i],
            "AV": i >= gb and cl[i] >= cl[i - gb],
            "BO": d in rets,
            "H7leE7": j >= 0 and cl[j] <= op[j],
            "H8gtE8": cl[i] > op[i],
        }
        g["rtg"] = g["H7leE7"] and g["H8gtE8"]
        g["AH"] = all(g[k] for k in ("AG", "AV", "BO", "rtg"))
        return g

    eng = pd.read_csv(ROOT / f"drive/YH_Closed_{run_id}.csv")
    eng = eng[eng["SYMBOL"] == "TSLA"].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    eng["cad"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce")

    def in_trade(d: str) -> str | None:
        ts = pd.Timestamp(d)
        for _, r in eng.iterrows():
            if r.open_d <= ts <= r.close_d:
                cad = r.cad.date() if pd.notna(r.cad) else "?"
                return f"open {r.open_d.date()} CAD {cad} -> {r.close_d.date()} {r.EXIT_TYPE}"
        return None

    print("=== Sheet AH gates (AG & AV & BO & red-to-green) ===")
    for d in ["2022-05-16", "2022-05-17", "2022-05-18", "2022-05-19", "2022-05-20"]:
        i = iso.index(d)
        j = i - 1
        g = gates(d)
        print(f"\n{d}  O={op[i]:.2f} H={hi[i]:.2f} L={lo[i]:.2f} C={cl[i]:.2f}")
        print(f"  prior {iso[j]} O={op[j]:.2f} C={cl[j]:.2f}")
        print(f"  AH={g['AH']}  AG={g['AG']}  AV={g['AV']}  BO={g['BO']}  rtg={g['rtg']}")
        it = in_trade(d)
        if it:
            print(f"  ENGINE IN_TRADE: {it}")

    print("\n=== Retest ledger rows (May 2022) ===")
    for _, r in rt.iterrows():
        rd = parse_mdy(r["Retest Date"])
        if rd and "2022-05" <= rd <= "2022-05-25":
            print(
                f"  BO {parse_mdy(r['Breakout Date'])}  retest {rd}  "
                f"zone [{r['Zone Lower']}, {r['Zone Upper']}]"
            )

    print("\n=== Engine trades May 2022 ===")
    w = eng[(eng["open_d"] >= "2022-05-01") & (eng["open_d"] <= "2022-06-01")]
    for _, r in w.sort_values("open_d").iterrows():
        cad = r.cad.date() if pd.notna(r.cad) else "?"
        print(
            f"  CAD {cad}  open {r.open_d.date()}  ${float(r.ENTRY_PRICE):.2f}  "
            f"-> {r.close_d.date()}  {r.EXIT_TYPE}  {r.PNL_PCT}"
        )

    # Too-fast retest (BQ): overlap on Main Row + 1 after breakout
    print("\n=== Too-fast retest (BQ) check for 5/19 BO rows ===")
    for _, r in rt.iterrows():
        bo = parse_mdy(r["Breakout Date"])
        rd = parse_mdy(r["Retest Date"])
        if rd != "2022-05-19":
            continue
        if bo not in iso:
            continue
        bi = iso.index(bo)
        bl = bi + 2  # excel row if data from row 2
        scan = bl + 2  # C19 delay
        bq_row = bl + 1
        if bq_row - 2 < 0 or bq_row - 2 >= len(iso):
            continue
        bx = bq_row - 2
        zl = float(str(r["Zone Lower"]).replace("$", "").replace(",", ""))
        zu = float(str(r["Zone Upper"]).replace("$", ""))
        overlap = lo[bx] <= zu and hi[bx] >= zl
        print(
            f"  BO {bo} retest {rd} zone [{zl},{zu}]  "
            f"BQ bar {iso[bx]} overlap={overlap} (H={hi[bx]:.2f} L={lo[bx]:.2f})"
        )


if __name__ == "__main__":
    main()
