#!/usr/bin/env python3
"""Deep-dive WPBR retest discrepancies for NVDA + AMZN (stamp 260722105625).

Does NOT modify engine. Writes analysis dumps to stdout.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO))

from stock_analysis.wpbr_zones import (  # noqa: E402
    compute_wpbr_touch_stream,
    find_wpbr_retest_and_signal,
    RETEST_MODE_STOP_LOOKING,
    RETEST_MODE_KEEP_LOOKING,
)

STAMP = "260722105625"
ART = REPO / "drive/wpbr_sheet_reconcile/_markten_retest_2016"


def parse_sheet_date(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    s = str(s).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    return pd.Timestamp(s).normalize()


def load_sheet_zones(sym: str) -> pd.DataFrame:
    p = REPO / f"drive/wpbr_sheet_reconcile/{sym}/sheet_zones.csv"
    if not p.exists():
        p = REPO / f"drive/wpbr_sheet_reconcile/{sym}/zones.tsv"
        df = pd.read_csv(p, sep="\t")
    else:
        df = pd.read_csv(p)
    # normalize colnames
    cols = {c: c.strip() for c in df.columns}
    df = df.rename(columns=cols)
    out = pd.DataFrame(
        {
            "pivot": df["Pivot Date"].map(parse_sheet_date),
            "zone_lower": pd.to_numeric(df["Zone Lower"], errors="coerce"),
            "zone_upper": pd.to_numeric(df["Zone Upper"], errors="coerce"),
            "bo": df["Breakout Date"].map(parse_sheet_date),
            "conf": df["Conf Week Date"].map(parse_sheet_date),
            "next": df["Next week start date"].map(parse_sheet_date),
            "retest": df["Daily Retest Date"].map(parse_sheet_date),
            "rocket": df["Rocket Buy Date"].map(parse_sheet_date),
        }
    )
    return out.dropna(subset=["pivot"]).reset_index(drop=True)


def load_sheet_ohlc(sym: str) -> pd.DataFrame:
    for name in ("sheet_ohlc.csv", "sheet_ohlc.tsv", "ohlc.tsv"):
        p = REPO / f"drive/wpbr_sheet_reconcile/{sym}/{name}"
        if p.exists():
            sep = "\t" if p.suffix == ".tsv" else ","
            df = pd.read_csv(p, sep=sep)
            # find date col
            dcol = [c for c in df.columns if c.lower().startswith("date")][0]
            df[dcol] = pd.to_datetime(df[dcol])
            df = df.set_index(dcol).sort_index()
            # normalize OHLC names
            rename = {}
            for c in df.columns:
                cl = c.strip().lower()
                if cl == "open":
                    rename[c] = "Open"
                elif cl == "high":
                    rename[c] = "High"
                elif cl == "low":
                    rename[c] = "Low"
                elif cl == "close":
                    rename[c] = "Close"
                elif cl == "volume":
                    rename[c] = "Volume"
            df = df.rename(columns=rename)
            return df[["Open", "High", "Low", "Close"]].astype(float)
    raise FileNotFoundError(sym)


def load_engine_ohlc(sym: str) -> pd.DataFrame:
    df = pd.read_csv(REPO / f"data/newdata/data/{sym}.csv", index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).normalize()
    cols = ["Open", "High", "Low", "Close"]
    if "Volume" in df.columns:
        cols = cols + ["Volume"]
    return df[cols].astype(float)


def load_engine_zones_csv(sym: str) -> pd.DataFrame:
    p = ART / f"WPBR_ZONES_{sym}_{STAMP}.csv"
    ez = pd.read_csv(p)
    ez["PIVOT_MONDAY"] = pd.to_datetime(ez["PIVOT_MONDAY"]).dt.normalize()
    # map RETEST_BAR index to date via engine OHLC
    ohlc = load_engine_ohlc(sym)
    dates = ohlc.index

    def bar_to_date(b):
        try:
            bi = int(b)
        except Exception:
            return None
        if bi < 0 or bi >= len(dates):
            return None
        return dates[bi]

    ez["retest_date"] = ez["RETEST_BAR"].map(bar_to_date)
    ez["signal_date"] = ez["ENTRY_SIGNAL_BAR"].map(bar_to_date)
    ez["fill_date"] = ez["ENTRY_FILL_BAR"].map(bar_to_date)
    # next week start = Monday after conf week; CONF_MONDAY is already Monday of conf week
    # engine CSV may not have NEXT; compute as CONF_MONDAY + 7 days
    ez["CONF_MONDAY"] = pd.to_datetime(ez["CONF_MONDAY"], errors="coerce").dt.normalize()
    ez["BREAKOUT_MONDAY"] = pd.to_datetime(ez["BREAKOUT_MONDAY"], errors="coerce").dt.normalize()
    ez["next_week_start"] = ez["CONF_MONDAY"] + pd.Timedelta(days=7)
    return ez


def live_engine_zones(sym: str, retest_mode: str = RETEST_MODE_STOP_LOOKING) -> list[dict]:
    df = load_engine_ohlc(sym)
    out = compute_wpbr_touch_stream(df, retest_mode=retest_mode)
    return out["wpbr_zone_events"]


def dstr(ts):
    if ts is None or (isinstance(ts, float) and np.isnan(ts)):
        return None
    try:
        if pd.isna(ts):
            return None
    except Exception:
        pass
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def compare_all_retests(sym: str):
    sheet = load_sheet_zones(sym)
    ez = load_engine_zones_csv(sym)
    # also live
    live = live_engine_zones(sym, RETEST_MODE_STOP_LOOKING)
    live_by_pivot = {}
    for z in live:
        pm = z.get("pivot_monday") or z.get("PIVOT_MONDAY")
        # events use various keys
        keys = list(z.keys())
        pm = z.get("pivot_monday")
        if pm is None:
            # try date fields
            for k in ("pivot_monday", "pivot_week_monday", "pivot_date"):
                if k in z:
                    pm = z[k]
                    break
        if pm is None and "wpbr_zone_id" in z:
            # zone id starts with week end date often
            pass
        live_by_pivot[dstr(pm)] = z

    # Inspect first live event keys
    if live:
        print(f"\n[{sym}] live event keys sample: {sorted(live[0].keys())}")
        print(f"  sample0: pivot_monday={live[0].get('pivot_monday')} zl={live[0].get('zone_lower')} zh={live[0].get('zone_upper')} retest={live[0].get('retest_date')}")

    mismatches = []
    matches = 0
    blank_matches = 0
    for _, row in sheet.iterrows():
        piv = dstr(row["pivot"])
        s_rt = dstr(row["retest"])
        # engine csv match
        m = ez[ez["PIVOT_MONDAY"] == pd.Timestamp(piv)]
        if m.empty:
            mismatches.append((piv, s_rt, None, "NO_ENGINE_PIVOT", row))
            continue
        er = m.iloc[0]
        e_rt = dstr(er["retest_date"])
        if s_rt == e_rt:
            if s_rt is None:
                blank_matches += 1
            else:
                matches += 1
        else:
            mismatches.append(
                (
                    piv,
                    s_rt,
                    e_rt,
                    "DATE_DIFF",
                    row,
                    er,
                )
            )
    print(f"\n=== {sym} RETEST SCAN (sheet vs engine CSV stamp) ===")
    print(f"  sheet zones={len(sheet)} date_match={matches} blank_match={blank_matches} mismatches={len(mismatches)}")
    for mm in mismatches:
        print(f"  MISMATCH pivot={mm[0]} sheet_rt={mm[1]} eng_rt={mm[2]} kind={mm[3]}")
        if len(mm) > 4 and hasattr(mm[4], "zone_lower"):
            r = mm[4]
            print(f"    sheet zl/zh={r['zone_lower']}/{r['zone_upper']} next={dstr(r['next'])} bo={dstr(r['bo'])} conf={dstr(r['conf'])}")
        if len(mm) > 5:
            er = mm[5]
            print(f"    eng   zl/zh={er['ZONE_LOW']}/{er['ZONE_HIGH']} center={er['ZONE_CENTER']} next={dstr(er['next_week_start'])} conf={dstr(er['CONF_MONDAY'])} bo={dstr(er['BREAKOUT_MONDAY'])}")
            print(f"    eng   zone_id={er['WPBR_ZONE_ID']} RETEST_BAR={er['RETEST_BAR']}")
    return mismatches, sheet, ez, live


def walk_days(
    sym: str,
    *,
    scan_start: str,
    until: str,
    zone_lower: float,
    zone_upper: float,
    label: str,
    use_sheet_ohlc: bool = False,
    also_rounded_close: bool = True,
):
    ohlc = load_sheet_ohlc(sym) if use_sheet_ohlc else load_engine_ohlc(sym)
    src = "SHEET" if use_sheet_ohlc else "ENGINE"
    win = ohlc.loc[pd.Timestamp(scan_start) : pd.Timestamp(until)]
    print(f"\n--- {sym} day-walk [{label}] src={src} zl={zone_lower!r} zh={zone_upper!r} ---")
    print(f"  {'date':10} {'Low':>10} {'Close':>10} {'C_r2':>8}  L<=zh  C>zh  C<zl  abandon  retest?")
    first_abandon = None
    first_retest = None
    for d, r in win.iterrows():
        L, C = float(r.Low), float(r.Close)
        Cr2 = round(C, 2)
        low_in = L <= zone_upper + 1e-9
        close_ab = C > zone_upper + 1e-9
        close_ab_r2 = Cr2 > zone_upper + 1e-9
        abandon = C < zone_lower - 1e-9
        abandon_r2 = Cr2 < zone_lower - 1e-9
        is_retest = low_in and close_ab
        is_retest_r2 = (L <= zone_upper + 1e-9) and close_ab_r2
        if abandon and first_abandon is None:
            first_abandon = dstr(d)
        if is_retest and first_retest is None and (first_abandon is None or dstr(d) < first_abandon):
            first_retest = dstr(d)
        mark = ""
        if abandon:
            mark += " ABANDON"
        if is_retest:
            mark += " RETEST"
        if also_rounded_close and (close_ab != close_ab_r2 or abandon != abandon_r2):
            mark += f" [r2: C>zh={close_ab_r2} C<zl={abandon_r2}]"
        # boundary detail
        side_up = "C>zh" if C > zone_upper else ("C==zh" if abs(C - zone_upper) < 1e-12 else "C<=zh")
        side_lo = "C<zl" if C < zone_lower else ("C==zl" if abs(C - zone_lower) < 1e-12 else "C>=zl")
        print(
            f"  {dstr(d)} {L:10.6f} {C:10.6f} {Cr2:8.2f}  "
            f"{str(low_in):5} {str(close_ab):5} {str(abandon):5}  "
            f"{side_up}/{side_lo}{mark}"
        )
    print(f"  => first_abandon={first_abandon} first_retest(engine-rule)={first_retest}")
    return first_abandon, first_retest


def ohlc_diff(sym: str, start: str, end: str):
    e = load_engine_ohlc(sym)
    s = load_sheet_ohlc(sym)
    # align
    common = e.index.intersection(s.index)
    common = common[(common >= pd.Timestamp(start)) & (common <= pd.Timestamp(end))]
    diffs = []
    for d in common:
        er, sr = e.loc[d], s.loc[d]
        for col in ("Open", "High", "Low", "Close"):
            ev, sv = float(er[col]), float(sr[col])
            # sheet often 2dp
            if abs(ev - sv) > 1e-9 and abs(round(ev, 2) - sv) > 1e-9:
                diffs.append((dstr(d), col, ev, sv, abs(ev - sv)))
            elif abs(ev - sv) > 1e-9:
                # only precision
                diffs.append((dstr(d), col, ev, sv, abs(ev - sv), "precision"))
    print(f"\n--- {sym} OHLC sheet vs engine {start}..{end} ---")
    print(f"  bars={len(common)} diffs_any={len(diffs)}")
    # show non-precision first
    hard = [x for x in diffs if len(x) == 5]
    soft = [x for x in diffs if len(x) == 6]
    print(f"  hard (beyond round2)={len(hard)} soft(precision-only)={len(soft)}")
    for x in hard[:40]:
        print(f"  HARD {x}")
    for x in soft[:20]:
        print(f"  soft {x}")
    if len(hard) > 40:
        print(f"  ... {len(hard)-40} more hard")
    return hard, soft


def zone_lineage(sym: str, pivot: str):
    sheet = load_sheet_zones(sym)
    ez = load_engine_zones_csv(sym)
    live = live_engine_zones(sym)
    srow = sheet[sheet["pivot"] == pd.Timestamp(pivot)]
    erow = ez[ez["PIVOT_MONDAY"] == pd.Timestamp(pivot)]
    print(f"\n======== {sym} ZONE LINEAGE pivot={pivot} ========")
    if srow.empty:
        print("  SHEET: missing")
    else:
        r = srow.iloc[0]
        print(
            f"  SHEET: zl={r.zone_lower!r} zh={r.zone_upper!r} "
            f"bo={dstr(r.bo)} conf={dstr(r.conf)} next={dstr(r.next)} "
            f"retest={dstr(r.retest)} rocket={dstr(r.rocket)}"
        )
        # unrounded from center if we can infer
        # sheet zone often ROUND(pivot*(1±0.015),2)
    if erow.empty:
        print("  ENG CSV: missing")
        er = None
    else:
        er = erow.iloc[0]
        print(
            f"  ENG CSV: zl={er.ZONE_LOW!r} zh={er.ZONE_HIGH!r} center={er.ZONE_CENTER!r} "
            f"bo={dstr(er.BREAKOUT_MONDAY)} conf={dstr(er.CONF_MONDAY)} next={dstr(er.next_week_start)} "
            f"retest={dstr(er.retest_date)} sig={dstr(er.signal_date)} "
            f"RETEST_BAR={er.RETEST_BAR} zone_id={er.WPBR_ZONE_ID}"
        )
        # raw vs rounded
        center = float(er.ZONE_CENTER)
        raw_zl = center * (1 - 0.015)
        raw_zh = center * (1 + 0.015)
        print(
            f"  ROUND check: center={center} raw_zl={raw_zl:.10f} raw_zh={raw_zh:.10f} "
            f"round2=({round(raw_zl,2)}, {round(raw_zh,2)}) "
            f"csv=({er.ZONE_LOW}, {er.ZONE_HIGH})"
        )

    # live match
    for z in live:
        if dstr(z.get("pivot_monday")) == pivot:
            print(
                f"  LIVE stop_looking: zl={z.get('zone_lower')!r} zh={z.get('zone_upper')!r} "
                f"center={z.get('zone_center')!r} next={dstr(z.get('next_week_start'))} "
                f"retest={dstr(z.get('retest_date'))} "
                f"retest_bar={z.get('retest_bar')} scan_start={z.get('scan_start_bar')}"
            )
            # also keep_looking
            break
    live_kl = live_engine_zones(sym, RETEST_MODE_KEEP_LOOKING)
    for z in live_kl:
        if dstr(z.get("pivot_monday")) == pivot:
            print(
                f"  LIVE keep_looking: retest={dstr(z.get('retest_date'))} "
                f"zl={z.get('zone_lower')!r} zh={z.get('zone_upper')!r}"
            )
            break
    return srow.iloc[0] if not srow.empty else None, er


def deep_nvda():
    print("\n" + "#" * 72)
    print("# NVDA DEEP DIVE — pivot 2017-06-05")
    print("#" * 72)
    srow, er = zone_lineage("NVDA", "2017-06-05")
    # Also check weekly pivot high from engine OHLC for that week
    eohlc = load_engine_ohlc("NVDA")
    # pivot week ending ~2017-06-09 (Friday) for Monday 2017-06-05
    week = eohlc.loc["2017-06-05":"2017-06-09"]
    print(f"\n  Pivot week daily Highs:\n{week[['High','Low','Close']]}")
    print(f"  weekly High max={week['High'].max()} -> band upper raw={week['High'].max()*1.015:.10f} round2={round(week['High'].max()*1.015,2)}")
    print(f"  weekly High max lower raw={week['High'].max()*0.985:.10f} round2={round(week['High'].max()*0.985,2)}")

    # Sheet weekly helper if available
    wp = REPO / "drive/wpbr_sheet_reconcile/NVDA/sheet_weekly.csv"
    if wp.exists():
        w = pd.read_csv(wp)
        # find pivot row
        for _, row in w.iterrows():
            try:
                d = parse_sheet_date(row.get("Date") or row.get("Week") or row.iloc[0])
            except Exception:
                continue
            if dstr(d) == "2017-06-05":
                print(f"  SHEET weekly row 2017-06-05: {dict(row)}")
                break

    zl_s, zh_s = float(srow.zone_lower), float(srow.zone_upper)
    zl_e, zh_e = float(er.ZONE_LOW), float(er.ZONE_HIGH)
    next_s = dstr(srow["next"])
    # Critical window around sheet retest
    walk_days("NVDA", scan_start="2017-09-18", until="2017-10-02", zone_lower=zl_s, zone_upper=zh_s, label="SHEET bounds", use_sheet_ohlc=True)
    walk_days("NVDA", scan_start="2017-09-18", until="2017-10-02", zone_lower=zl_s, zone_upper=zh_s, label="SHEET bounds on ENGINE ohlc", use_sheet_ohlc=False)
    walk_days("NVDA", scan_start="2017-09-18", until="2017-10-02", zone_lower=zl_e, zone_upper=zh_e, label="ENGINE bounds", use_sheet_ohlc=False)
    walk_days("NVDA", scan_start="2017-09-18", until="2017-10-02", zone_lower=zl_e, zone_upper=zh_e, label="ENGINE bounds on SHEET ohlc", use_sheet_ohlc=True)

    # Full scan from next_week_start with engine find_ function
    ohlc = eohlc
    n = len(ohlc)
    lo = ohlc["Low"].to_numpy()
    cl = ohlc["Close"].to_numpy()
    op = ohlc["Open"].to_numpy()
    scan = ohlc.index.get_indexer([pd.Timestamp(next_s)], method="bfill")[0]
    print(f"\n  next_week_start={next_s} scan_bar={scan} date={dstr(ohlc.index[scan])}")
    for mode in (RETEST_MODE_STOP_LOOKING, RETEST_MODE_KEEP_LOOKING):
        for zl, zh, tag in ((zl_s, zh_s, "sheet_bounds"), (zl_e, zh_e, "eng_bounds")):
            rb, sb, fb = find_wpbr_retest_and_signal(
                lo, cl, op, scan_start=scan, zone_lower=zl, zone_upper=zh,
                max_days_after_retest=2, n=n, retest_mode=mode,
            )
            print(f"  find({mode},{tag} zl={zl} zh={zh}): retest={dstr(ohlc.index[rb]) if rb is not None else None} sig={dstr(ohlc.index[sb]) if sb is not None else None}")

    # Exact 9/25 close comparison
    for src, df in (("ENGINE", eohlc), ("SHEET", load_sheet_ohlc("NVDA"))):
        r = df.loc[pd.Timestamp("2017-09-25")]
        C = float(r.Close)
        print(f"  {src} 2017-09-25 Close={C!r} round2={round(C,2)} vs zh_s={zh_s} zh_e={zh_e}")
        print(f"    C>zh_s: {C > zh_s}  C>zh_e: {C > zh_e}  round2>zh_s: {round(C,2)>zh_s} round2>zh_e: {round(C,2)>zh_e}")
        print(f"    Low={float(r.Low)!r} Low<=zh_s={float(r.Low)<=zh_s} Low<=zh_e={float(r.Low)<=zh_e}")

    ohlc_diff("NVDA", "2017-09-18", "2017-10-02")


def deep_amzn():
    print("\n" + "#" * 72)
    print("# AMZN DEEP DIVE — pivot 2024-12-16")
    print("#" * 72)
    srow, er = zone_lineage("AMZN", "2024-12-16")
    eohlc = load_engine_ohlc("AMZN")
    week = eohlc.loc["2024-12-16":"2024-12-20"]
    print(f"\n  Pivot week daily:\n{week[['High','Low','Close']]}")
    print(f"  weekly High max={week['High'].max()} raw_zh={week['High'].max()*1.015:.10f} r2={round(week['High'].max()*1.015,2)}")
    print(f"  raw_zl={week['High'].max()*0.985:.10f} r2={round(week['High'].max()*0.985,2)}")

    zl_s, zh_s = float(srow.zone_lower), float(srow.zone_upper)
    zl_e, zh_e = float(er.ZONE_LOW), float(er.ZONE_HIGH)
    next_s = dstr(srow["next"])
    sheet_rt = dstr(srow["retest"])
    print(f"\n  sheet retest={sheet_rt} next={next_s}")

    # Walk from next to sheet retest (+ a bit) — this may be LONG. Summarize abandon first.
    # First find abandon with both bound sets on both OHLC sources
    for use_sheet in (False, True):
        src = "SHEET" if use_sheet else "ENGINE"
        ohlc = load_sheet_ohlc("AMZN") if use_sheet else eohlc
        for zl, zh, tag in ((zl_s, zh_s, "sheet_bounds"), (zl_e, zh_e, "eng_bounds")):
            win = ohlc.loc[pd.Timestamp(next_s) : pd.Timestamp(sheet_rt) + pd.Timedelta(days=5)]
            first_ab = None
            first_rt = None
            ab_rows = []
            rt_rows = []
            for d, r in win.iterrows():
                L, C = float(r.Low), float(r.Close)
                if C < zl - 1e-9 and first_ab is None:
                    first_ab = dstr(d)
                    ab_rows.append((dstr(d), L, C, round(C, 2)))
                if L <= zh + 1e-9 and C > zh + 1e-9:
                    if first_rt is None:
                        first_rt = dstr(d)
                    rt_rows.append((dstr(d), L, C, round(C, 2)))
            print(f"\n  SUMMARY {src}/{tag}: first_abandon={first_ab} first_retest={first_rt} n_retest_cands={len(rt_rows)}")
            if first_ab:
                # show context around abandon
                ad = pd.Timestamp(first_ab)
                ctx = ohlc.loc[ad - pd.Timedelta(days=10) : ad + pd.Timedelta(days=10)]
                print(f"    abandon context ({tag} zl={zl} zh={zh}):")
                for d, r in ctx.iterrows():
                    L, C = float(r.Low), float(r.Close)
                    flags = []
                    if C < zl - 1e-9:
                        flags.append("ABANDON")
                    if L <= zh + 1e-9 and C > zh + 1e-9:
                        flags.append("RETEST")
                    print(f"      {dstr(d)} L={L:.4f} C={C:.6f} Cr2={round(C,2):.2f} C-zl={C-zl:+.6f} {' '.join(flags)}")
            # show last few days before sheet retest and sheet retest day
            if sheet_rt:
                srt = pd.Timestamp(sheet_rt)
                ctx2 = ohlc.loc[srt - pd.Timedelta(days=14) : srt + pd.Timedelta(days=3)]
                print(f"    around sheet retest {sheet_rt}:")
                for d, r in ctx2.iterrows():
                    L, C = float(r.Low), float(r.Close)
                    flags = []
                    if C < zl - 1e-9:
                        flags.append("ABANDON")
                    if L <= zh + 1e-9 and C > zh + 1e-9:
                        flags.append("RETEST")
                    print(f"      {dstr(d)} L={L:.4f} C={C:.6f} Cr2={round(C,2):.2f} L-zh={L-zh:+.4f} C-zh={C-zh:+.6f} {' '.join(flags)}")

    # find_wpbr with both modes
    n = len(eohlc)
    lo = eohlc["Low"].to_numpy()
    cl = eohlc["Close"].to_numpy()
    op = eohlc["Open"].to_numpy()
    scan = eohlc.index.get_indexer([pd.Timestamp(next_s)], method="bfill")[0]
    print(f"\n  next_week_start={next_s} scan_bar={scan} date={dstr(eohlc.index[scan])}")
    for mode in (RETEST_MODE_STOP_LOOKING, RETEST_MODE_KEEP_LOOKING):
        for zl, zh, tag in ((zl_s, zh_s, "sheet_bounds"), (zl_e, zh_e, "eng_bounds")):
            rb, sb, fb = find_wpbr_retest_and_signal(
                lo, cl, op, scan_start=scan, zone_lower=zl, zone_upper=zh,
                max_days_after_retest=2, n=n, retest_mode=mode,
            )
            print(f"  find({mode},{tag}): retest={dstr(eohlc.index[rb]) if rb is not None else None}")

    # Also try with ROUND(2) on OHLC close for abandon/retest (sheet-like)
    print("\n  Simulated sheet-like ROUND(Close,2) scan on ENGINE ohlc with sheet bounds:")
    win = eohlc.loc[pd.Timestamp(next_s) :]
    first_ab = first_rt = None
    for d, r in win.iterrows():
        L, C = float(r.Low), round(float(r.Close), 2)
        if C < zl_s - 1e-9:
            first_ab = dstr(d)
            print(f"    ABANDON at {first_ab} L={L} C_r2={C} zl={zl_s}")
            break
        if L <= zh_s + 1e-9 and C > zh_s + 1e-9:
            first_rt = dstr(d)
            print(f"    RETEST at {first_rt} L={L} C_r2={C} zh={zh_s}")
            break
    print(f"    => first_ab={first_ab} first_rt={first_rt}")

    # Same with sheet OHLC (already 2dp typically)
    print("\n  Sheet OHLC scan with sheet bounds (exact sheet data):")
    sohlc = load_sheet_ohlc("AMZN")
    win = sohlc.loc[pd.Timestamp(next_s) :]
    first_ab = first_rt = None
    for d, r in win.iterrows():
        L, C = float(r.Low), float(r.Close)
        if C < zl_s - 1e-9:
            if first_ab is None:
                first_ab = dstr(d)
                print(f"    ABANDON at {first_ab} L={L} C={C} zl={zl_s} (C-zl={C-zl_s})")
                # continue to also find if sheet somehow still has retest? shouldn't under stop_looking
                break
        if L <= zh_s + 1e-9 and C > zh_s + 1e-9:
            if first_rt is None:
                first_rt = dstr(d)
                print(f"    RETEST at {first_rt} L={L} C={C} zh={zh_s}")
                break
    print(f"    => first_ab={first_ab} first_rt={first_rt} sheet_claimed_rt={sheet_rt}")

    # If abandon fires before sheet retest on sheet OHLC, sheet formula quirk
    # Dump sheet formula behavior: maybe sheet uses ROUND on zone_lower for abandon differently
    # or uses Low < lower vs Close < lower
    print("\n  ALT abandon rules on SHEET ohlc / sheet bounds:")
    for rule_name, pred in [
        ("Close < zl", lambda L, C: C < zl_s - 1e-9),
        ("Close <= zl", lambda L, C: C <= zl_s + 1e-9),
        ("Close < round(zl,2)", lambda L, C: C < round(zl_s, 2) - 1e-9),
        ("Low < zl", lambda L, C: L < zl_s - 1e-9),
        ("Close < zl (r2 close)", lambda L, C: round(C, 2) < zl_s - 1e-9),
    ]:
        first_ab = first_rt = None
        for d, r in sohlc.loc[pd.Timestamp(next_s) :].iterrows():
            L, C = float(r.Low), float(r.Close)
            if pred(L, C):
                first_ab = dstr(d)
                break
            if L <= zh_s + 1e-9 and C > zh_s + 1e-9:
                first_rt = dstr(d)
                break
        print(f"    rule={rule_name!r:30} first_ab={first_ab} first_rt={first_rt}")

    # OHLC drift full window next -> sheet retest
    ohlc_diff("AMZN", next_s, sheet_rt)

    # Specifically check sheet retest day and abandon day candidates
    for day in [sheet_rt]:
        if not day:
            continue
        for src, df in (("ENGINE", eohlc), ("SHEET", sohlc)):
            if pd.Timestamp(day) not in df.index:
                print(f"  {src} missing {day}")
                continue
            r = df.loc[pd.Timestamp(day)]
            print(f"  {src} {day} O={r.Open} H={r.High} L={r.Low} C={r.Close}")


def main():
    for sym in ("NVDA", "AMZN"):
        compare_all_retests(sym)
    deep_nvda()
    deep_amzn()


if __name__ == "__main__":
    main()
