#!/usr/bin/env python3
"""NFLX orphan causal diagnostics: OHLC, zone attach, engine state, cross-ticker paste check."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream, find_wpbr_retest_and_signal  # noqa: E402

DATA = REPO / "data" / "newdata" / "data" / "NFLX.csv"
ZONES = REPO / "drive" / "wpbr_sheet_reconcile" / "NFLX" / "zones.tsv"
TRADES = REPO / "drive" / "wpbr_sheet_reconcile" / "NFLX" / "trades.tsv"
STAMP = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_2016_20260722134127"
CLOSED = STAMP / "WPBR_Closed_260722134152.csv"
BO = STAMP / "WPBR_breakout_and_retest_260722134152.csv"
ORPHANS = [
    ("2022-05-13", 17.72, "2022-07-20", 21.62),
    ("2023-10-16", 35.62, "2023-11-03", 43.46),
]
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]


def nd(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def nf(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def window(df, center, before=15, after=10):
    i = df.index.get_indexer([pd.Timestamp(center)], method="nearest")[0]
    a = max(0, i - before)
    b = min(len(df), i + after + 1)
    sub = df.iloc[a:b][["Open", "High", "Low", "Close"]].copy()
    sub.index = sub.index.strftime("%Y-%m-%d")
    return sub


def load_sheet_zones():
    z = pd.read_csv(ZONES, sep="\t", dtype=str)
    rows = []
    for _, r in z.iterrows():
        rows.append(
            {
                "pivot": nd(r.get("Pivot Date")),
                "zlow": nf(r.get("Zone Lower")),
                "zhigh": nf(r.get("Zone Upper")),
                "bo": nd(r.get("Breakout Date")),
                "conf": nd(r.get("Conf Week Date")),
                "next": nd(r.get("Next week start date")),
                "retest": nd(r.get("Daily Retest Date")),
                "retest_row": str(r.get("Daily Retest Row", "")).strip(),
                "rocket": nd(r.get("Rocket Buy Date")),
                "rocket_row": str(r.get("Rocket Buy Row", "")).strip(),
            }
        )
    return rows


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
    zones = load_sheet_zones()
    print("=== OHLC verification (orphan entry/exit days) ===")
    for entry, ep, exit_, xp in ORPHANS:
        for d, expect in ((entry, ep), (exit_, xp)):
            row = df.loc[pd.Timestamp(d)]
            print(
                f"{d}: O={row.Open:.4f} H={row.High:.4f} L={row.Low:.4f} C={row.Close:.4f} "
                f"| sheet_px={expect} open_2dp={round(float(row.Open), 2)} match_open={abs(float(row.Open)-expect)<0.015}"
            )
        print("--- window around entry ---")
        print(window(df, entry).to_string())
        print()

    print("=== Cross-ticker paste check (same Entry Date elsewhere?) ===")
    base = REPO / "drive" / "wpbr_sheet_reconcile"
    for entry, ep, *_ in ORPHANS:
        hits = []
        for sym in MARKTEN:
            p = base / sym / "trades.tsv"
            if not p.is_file():
                p = base / sym / "sheet_trades.tsv"
            if not p.is_file():
                continue
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
                c = line.split("\t")
                if not c:
                    continue
                if nd(c[0]) == entry:
                    hits.append((sym, c[1] if len(c) > 1 else "", line[:80]))
        print(f"{entry} @ {ep}: hits={hits or '(only NFLX / none)'}")

    print("\n=== Sheet zones: blank-rocket rows with retest near orphans ===")
    for entry, ep, *_ in ORPHANS:
        et = pd.Timestamp(entry)
        print(f"\n-- orphan {entry} @ {ep} --")
        ranked = []
        for z in zones:
            # price distance to mid / band membership
            if z["zlow"] is None or z["zhigh"] is None:
                continue
            mid = 0.5 * (z["zlow"] + z["zhigh"])
            in_band = z["zlow"] - 0.05 <= ep <= z["zhigh"] + 0.05
            above = ep > z["zhigh"]
            dist = abs(ep - mid)
            # temporal: retest/rocket/bo near entry
            dates = [d for d in (z["retest"], z["rocket"], z["bo"], z["conf"]) if d]
            nearest = None
            if dates:
                nearest = min(dates, key=lambda d: abs((pd.Timestamp(d) - et).days))
                ndays = abs((pd.Timestamp(nearest) - et).days)
            else:
                ndays = 9999
            ranked.append((dist, ndays, in_band, above, z))
        ranked.sort(key=lambda x: (0 if x[2] else 1, x[0], x[1]))
        for dist, ndays, in_band, above, z in ranked[:8]:
            print(
                f"  piv={z['pivot']} zl={z['zlow']:.2f}-{z['zhigh']:.2f} "
                f"bo={z['bo']} retest={z['retest']} rocket={z['rocket']} "
                f"| distMid={dist:.2f} nearDays={ndays} inBand={in_band} aboveZh={above and not in_band}"
            )

    print("\n=== Engine closed NFLX occupancy around orphans ===")
    if CLOSED.is_file():
        cl = pd.read_csv(CLOSED, dtype=str)
        cl = cl[cl["SYMBOL"].str.upper() == "NFLX"]
        for _, r in cl.iterrows():
            o = nd(r.get("DATE_OPENED"))
            c = nd(r.get("DATE_CLOSED"))
            if not o:
                continue
            # show trades overlapping/near orphans
            for entry, *_ in ORPHANS:
                if abs((pd.Timestamp(o) - pd.Timestamp(entry)).days) <= 120 or (
                    c and pd.Timestamp(o) <= pd.Timestamp(entry) <= pd.Timestamp(c)
                ):
                    print(
                        f"  {o} -> {c} @ {r.get('ENTRY_PRICE')} exit={r.get('EXIT_PRICE')} "
                        f"{r.get('EXIT_TYPE')} pnl={r.get('PNL_PCT')} zone={r.get('WPBR_ZONE_ID','')}"
                    )
                    break
    else:
        print(f"MISSING {CLOSED}")

    print("\n=== Engine breakout/retest rows near orphan windows ===")
    if BO.is_file():
        bo = pd.read_csv(BO, dtype=str)
        if "SYMBOL" in bo.columns:
            bo = bo[bo["SYMBOL"].str.upper() == "NFLX"]
        for entry, ep, *_ in ORPHANS:
            et = pd.Timestamp(entry)
            print(f"\n-- around {entry} --")
            shown = 0
            for _, r in bo.iterrows():
                # try common date cols
                dates = []
                for k in r.index:
                    if "DATE" in k.upper() or k.upper() in {"RETEST", "SIGNAL", "TRIGGER"}:
                        d = nd(r.get(k))
                        if d:
                            dates.append((k, d))
                if not dates:
                    continue
                if any(abs((pd.Timestamp(d) - et).days) <= 45 for _, d in dates):
                    zl = r.get("ZONE_LOW") or r.get("ZONE_LOWER") or r.get("zone_low")
                    zh = r.get("ZONE_HIGH") or r.get("ZONE_UPPER") or r.get("zone_high")
                    print(
                        f"  cols_sample: "
                        + " | ".join(f"{k}={r.get(k)}" for k in list(r.index)[:12])
                    )
                    print(f"    zl/zh={zl}/{zh} dates={dates[:6]}")
                    shown += 1
                    if shown >= 12:
                        break
            if shown == 0:
                print("  (no nearby rows; dumping header)")
                print("  ", list(bo.columns)[:30])
    else:
        print(f"MISSING {BO}")

    print("\n=== Live WPBR: any opportunity fill on orphan dates? ===")
    out = compute_wpbr_touch_stream(
        df,
        band_pct=0.015,
        strong_pre_pivot_bars=3,
        strong_pre_pivot_pct=0.10,
        strong_post_pivot_bars=3,
        strong_post_pivot_pct=0.10,
        strong_pivot_mode="either",
        breakout_confirmation=0.03,
        max_days_after_retest=2,
        retest_mode="stop_looking",
        zone_price_round_decimals=2,
    )
    idx = df.index
    orphan_fills = {o[0] for o in ORPHANS}
    for opp in out.get("wpbr_entry_opportunities") or []:
        fb = opp.get("entry_fill_bar")
        sb = opp.get("entry_signal_bar")
        rb = opp.get("retest_bar")
        if fb is None or fb < 0:
            continue
        fd = pd.Timestamp(idx[int(fb)]).strftime("%Y-%m-%d")
        sd = pd.Timestamp(idx[int(sb)]).strftime("%Y-%m-%d") if sb is not None and sb >= 0 else None
        rd = pd.Timestamp(idx[int(rb)]).strftime("%Y-%m-%d") if rb is not None and rb >= 0 else None
        if fd in orphan_fills or (sd and abs((pd.Timestamp(sd) - pd.Timestamp(list(orphan_fills)[0])).days) < 5):
            print(f"  FILL {fd} signal={sd} retest={rd} zl={opp['zone_lower']:.2f}-{opp['zone_upper']:.2f} id={opp.get('wpbr_zone_id')}")
    # explicit check
    for entry, ep, *_ in ORPHANS:
        hits = []
        for opp in out.get("wpbr_entry_opportunities") or []:
            fb = opp.get("entry_fill_bar")
            if fb is None or fb < 0:
                continue
            fd = pd.Timestamp(idx[int(fb)]).strftime("%Y-%m-%d")
            if fd == entry:
                hits.append(opp)
        print(f"orphan {entry}: live fill opportunities = {len(hits)}")

    print("\n=== Hypothetical: if sheet ignored max_days_after_retest / used retest as signal ===")
    # For blank-rocket zones with retest before orphan, check if fill@orphan open could attach
    for entry, ep, *_ in ORPHANS:
        et = pd.Timestamp(entry)
        print(f"\n-- {entry} --")
        for z in zones:
            if not z["retest"] or z["rocket"]:
                continue
            rt = pd.Timestamp(z["retest"])
            if rt > et:
                continue
            lag = (et - rt).days
            if lag > 60:
                continue
            # would open on entry day be a WPBR-style fill after a green day?
            # check prior session green close > zh
            i = df.index.get_loc(pd.Timestamp(entry))
            if i <= 0:
                continue
            prev = df.iloc[i - 1]
            green = float(prev.Close) > float(prev.Open)
            above = float(prev.Close) > float(z["zhigh"])
            print(
                f"  blank-rocket piv={z['pivot']} {z['zlow']:.2f}-{z['zhigh']:.2f} "
                f"retest={z['retest']} lagCal={lag}d | prev={prev.name.date()} "
                f"O={prev.Open:.2f} C={prev.Close:.2f} green={green} C>zh={above}"
            )

    print("\n=== Same-day re-entry / prior exit adjacency ===")
    sheet_t = pd.read_csv(TRADES, sep="\t", dtype=str)
    rows = []
    for _, r in sheet_t.iterrows():
        rows.append(
            {
                "entry": nd(r.get("Entry Date")),
                "exit": nd(r.get("Exit Date")),
                "ep": nf(r.get("Entry Price")),
                "xp": nf(r.get("Exit Price")),
                "pnl": str(r.get("Profit %", "")),
            }
        )
    for i, t in enumerate(rows):
        if t["entry"] in orphan_fills:
            prev = rows[i - 1] if i else None
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            print(f"orphan {t}: prev={prev} next={nxt}")
            if prev and prev["exit"]:
                gap = (pd.Timestamp(t["entry"]) - pd.Timestamp(prev["exit"])).days
                print(f"  calendar gap from prior sheet exit: {gap}d")

    print("\n=== Rocket→fill lag for ALL matched sheet trades (baseline pattern) ===")
    rockets = [(z["rocket"], z) for z in zones if z["rocket"]]
    for t in rows:
        best = None
        for rk, z in rockets:
            lag = (pd.Timestamp(t["entry"]) - pd.Timestamp(rk)).days
            if 0 <= lag <= 5:
                if best is None or lag < best[0]:
                    best = (lag, rk, z)
        if best:
            print(
                f"  {t['entry']} @ {t['ep']} <- rocket {best[1]} (lag {best[0]}d) "
                f"zone {best[2]['zlow']:.2f}-{best[2]['zhigh']:.2f} piv={best[2]['pivot']}"
            )
        else:
            print(f"  {t['entry']} @ {t['ep']} <- NO rocket within 0..5d  *** ORPHAN PATTERN ***")


if __name__ == "__main__":
    main()
