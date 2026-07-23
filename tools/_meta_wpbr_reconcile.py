#!/usr/bin/env python3
"""META WPBR sheet vs engine reconcile (closed trades + raw signal fills)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd
from wpbr_compare_filter import filter_wpbr_output_for_compare
from wpbr_sheet_ground_truth import load_wpbr_ground_truth
from wpbr_zones import compute_wpbr_touch_stream

MIN_DATE = "2016-01-01"
# retest_mode default is now stop_looking (sheet parity); pass explicitly for clarity.
RETEST_MODE = "stop_looking"
DATA = REPO / "data" / "newdata" / "data" / "META.csv"
BASE = REPO / "drive" / "wpbr_sheet_reconcile" / "META"
TRADES = BASE / "trades.tsv"
ZONES = BASE / "zones.tsv"
# New MarkTen (incl META) run with retest_mode=stop_looking (start_date=2016-01-01).
ENG = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_retest_2016" / "WPBR_Closed_260722105625.csv"
ENG_SYMBOL = "META"


def _ymd(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y%m%d")


def _load_sheet_zone_retests() -> list[tuple[str, pd.Timestamp, pd.Timestamp | None]]:
    """(pivot_monday YYYY-MM-DD, next_week_start, sheet Daily Retest Date|None) per zone."""
    z = pd.read_csv(ZONES, sep="\t")
    for c in ("Zone Lower", "Zone Upper"):
        z[c] = z[c].astype(str).str.replace("$", "", regex=False).astype(float)
    for c in ("Pivot Date", "Next week start date", "Daily Retest Date"):
        z[c] = pd.to_datetime(z[c], errors="coerce")
    rows = []
    for _, r in z.iterrows():
        if pd.isna(r["Pivot Date"]):
            continue
        rt = r["Daily Retest Date"]
        rows.append((r["Pivot Date"].strftime("%Y-%m-%d"), r["Next week start date"],
                     None if pd.isna(rt) else rt.normalize()))
    return rows


def _engine_zone_retests(df: pd.DataFrame) -> dict[str, pd.Timestamp | None]:
    out = compute_wpbr_touch_stream(
        df, band_pct=0.015, strong_pre_pivot_bars=3, strong_pre_pivot_pct=0.10,
        strong_post_pivot_bars=3, strong_post_pivot_pct=0.10, strong_pivot_mode="either",
        breakout_confirmation=0.03, max_days_after_retest=2, retest_mode=RETEST_MODE,
        zone_price_round_decimals=2,
    )
    res: dict[str, pd.Timestamp | None] = {}
    for ev in out["wpbr_zone_events"]:
        rb = int(ev.get("retest_bar", -1))
        key = pd.Timestamp(ev["pivot_monday"]).strftime("%Y-%m-%d")
        res[key] = pd.Timestamp(df.index[rb]).normalize() if rb >= 0 else None
    return res


def _retest_parity(df: pd.DataFrame) -> None:
    sheet = _load_sheet_zone_retests()
    eng = _engine_zone_retests(df)
    match = blank_match = eng_only = sheet_only = diff = 0
    misses = []
    for piv, _bk, s_rt in sheet:
        e_rt = eng.get(piv, "MISSING")
        if e_rt == "MISSING":
            misses.append((piv, "no engine zone", None if s_rt is None else s_rt.date()))
            continue
        if s_rt is None and e_rt is None:
            blank_match += 1
        elif s_rt is None and e_rt is not None:
            eng_only += 1
            misses.append((piv, f"eng={e_rt.date()}", "sheet=BLANK"))
        elif s_rt is not None and e_rt is None:
            sheet_only += 1
            misses.append((piv, "eng=BLANK", f"sheet={s_rt.date()}"))
        elif s_rt.normalize() == e_rt.normalize():
            match += 1
        else:
            diff += 1
            misses.append((piv, f"eng={e_rt.date()}", f"sheet={s_rt.date()}"))
    total = len(sheet)
    print(f"\n=== RETEST parity (retest_mode={RETEST_MODE}) vs sheet zones.tsv ===")
    print(f"  date_match={match} blank_match={blank_match} eng_only(sheet_blank)={eng_only} "
          f"sheet_only(eng_blank)={sheet_only} date_diff={diff}  "
          f"PARITY={match + blank_match}/{total}")
    for k, a, b in misses:
        print(f"    pivot={k}: {a} | {b}")


def main() -> int:
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    gt = load_wpbr_ground_truth(TRADES)["META"]

    out = filter_wpbr_output_for_compare(
        compute_wpbr_touch_stream(
            df, band_pct=0.015, strong_pre_pivot_bars=3, strong_pre_pivot_pct=0.10,
            strong_post_pivot_bars=3, strong_post_pivot_pct=0.10, strong_pivot_mode="either",
            breakout_confirmation=0.03, max_days_after_retest=2, retest_mode=RETEST_MODE,
            zone_price_round_decimals=2,
        ),
        df, min_date=MIN_DATE,
    )
    raw_fills = sorted(_ymd(df.index[b]) for b in out.get("wpbr_entry_fill_bars") or [])

    eng = pd.read_csv(ENG, dtype=str)
    eng = eng[eng["SYMBOL"] == ENG_SYMBOL].reset_index(drop=True)
    eng_trades = [
        (r["DATE_OPENED"], float(r["ENTRY_PRICE"]), r["DATE_CLOSED"], float(r["EXIT_PRICE"]),
         r["PNL_PCT"], r["EXIT_TYPE"])
        for _, r in eng.iterrows()
    ]
    eng_entries = {t[0] for t in eng_trades}

    print("=== SHEET closed trades vs ENGINE (serialized) ===")
    print(f"{'sheet_entry':>10} {'px':>8} {'sheet_exit':>10} {'pnl%':>8} {'res':>5} | "
          f"{'in_raw_sig':>10} {'in_eng_trade':>12}")
    entry_sig_hits = 0
    eng_trade_hits = 0
    for t in gt.trades:
        in_raw = "YES" if t.entry_date in raw_fills else "no"
        in_eng = "YES" if t.entry_date in eng_entries else "no"
        if t.entry_date in raw_fills:
            entry_sig_hits += 1
        if t.entry_date in eng_entries:
            eng_trade_hits += 1
        pnl = ((t.exit_price / t.entry_price) - 1) * 100
        print(f"{t.entry_date:>10} {t.entry_price:>8.2f} {t.exit_date:>10} {pnl:>7.2f}% "
              f"{t.result:>5} | {in_raw:>10} {in_eng:>12}")

    print(f"\nSheet trades: {len(gt.trades)}")
    print(f"Sheet entries present as engine RAW WPBR signals: {entry_sig_hits}/{len(gt.trades)}")
    print(f"Sheet entries present as engine SERIALIZED trades: {eng_trade_hits}/{len(gt.trades)}")

    print("\n=== ENGINE serialized closed trades (start 2016-01-01) ===")
    sheet_entries = {t.entry_date for t in gt.trades}
    for do, ep, dc, xp, pnl, xt in eng_trades:
        flag = "MATCH-SHEET" if do in sheet_entries else "engine-only"
        print(f"  {do} {ep:>8.2f} -> {dc} {xp:>8.2f} {pnl:>8} {xt:<10} [{flag}]")

    print("\n=== ENGINE RAW WPBR signal fills (>=2016, from live compute) ===")
    print("  " + " ".join(raw_fills))
    sheet_only = [t.entry_date for t in gt.trades if t.entry_date not in raw_fills]
    print(f"\nSheet entries NOT in engine raw signals: {sheet_only}")

    _retest_parity(df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
