#!/usr/bin/env python3
"""Analysis-only: compare WPBR _round_bounds variants (runtime monkeypatch)."""
from __future__ import annotations

import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(ROOT))

import stock_analysis.wpbr_zones as wz

SYMS = ["META", "NVDA", "AMZN", "NFLX"]
START = "2016-01-01"
BAND = 0.015
DEC = 2
CLOSED = ROOT / "drive/wpbr_sheet_reconcile/_markten_retest_2016/WPBR_Closed_260722105625.csv"
OUT_MD = ROOT / "drive/wpbr_sheet_reconcile/PIVOT_ROUND_ANALYSIS.md"
OHLC_DIR = ROOT / "data/newdata/data"
JSON_PATH = ROOT / "drive/wpbr_sheet_reconcile/_tmp_pivot_round_analysis.json"

FOCUS = {
    "NVDA": {"label": "2017-06-05", "want_dates": {"2017-06-05", "2017-06-09", "2017-06-11"}},
    "AMZN": {"label": "2024-12-16", "want_dates": {"2024-12-16", "2024-12-20", "2024-12-22"}},
}


def load_ohlc(sym: str) -> pd.DataFrame:
    p = OHLC_DIR / f"{sym}.csv"
    df = pd.read_csv(p)
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("date") or cols.get("datetime") or list(df.columns)[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    for want, dest in (("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close"), ("volume", "Volume")):
        if dest not in df.columns:
            src = cols.get(want)
            if src is not None:
                df[dest] = df[src]
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    df = df.loc[df.index >= START, ["Open", "High", "Low", "Close", "Volume"]].copy()
    for c in ("Open", "High", "Low", "Close", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def bounds_A(price: float, band_pct: float, dec: int):
    tp = float(price)
    zl = round(tp * (1.0 - band_pct), dec)
    zh = round(tp * (1.0 + band_pct), dec)
    return tp, zl, zh


def bounds_B(price: float, band_pct: float, dec: int):
    tp = round(float(price), dec)
    zl = round(tp * (1.0 - band_pct), dec)
    zh = round(tp * (1.0 + band_pct), dec)
    return tp, zl, zh


def bounds_C(price: float, band_pct: float, dec: int):
    quant = Decimal(10) ** (-int(dec))
    tp = Decimal(str(float(price))).quantize(quant, rounding=ROUND_HALF_UP)
    db = Decimal(str(band_pct))
    zl = (tp * (Decimal(1) - db)).quantize(quant, rounding=ROUND_HALF_UP)
    zh = (tp * (Decimal(1) + db)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(tp), float(zl), float(zh)


def bounds_D(price: float, band_pct: float, dec: int):
    tp = float(price)
    quant = Decimal(10) ** (-int(dec))
    dtp = Decimal(str(tp))
    db = Decimal(str(band_pct))
    zl = (dtp * (Decimal(1) - db)).quantize(quant, rounding=ROUND_HALF_UP)
    zh = (dtp * (Decimal(1) + db)).quantize(quant, rounding=ROUND_HALF_UP)
    return tp, float(zl), float(zh)


VARIANTS = {
    "A": ("current float-round band only", bounds_A),
    "B": ("round(pivot,2) then float-round band", bounds_B),
    "C": ("HALF_UP round(pivot,2) then HALF_UP band", bounds_C),
    "D": ("HALF_UP band only (no pivot round)", bounds_D),
}


def run_stream(df: pd.DataFrame, bounds_fn):
    orig = wz._round_bounds
    wz._round_bounds = bounds_fn
    try:
        return wz.compute_wpbr_touch_stream(
            df,
            band_pct=BAND,
            strong_pre_pivot_bars=3,
            strong_pre_pivot_pct=0.1,
            strong_post_pivot_bars=3,
            strong_post_pivot_pct=0.1,
            strong_pivot_mode="either",
            breakout_confirmation=0.03,
            max_days_after_retest=2,
            retest_mode="stop_looking",
            zone_price_round_decimals=DEC,
        )
    finally:
        wz._round_bounds = orig


def retest_date(df: pd.DataFrame, ev: dict):
    rb = ev.get("retest_bar", -1)
    if rb is None or int(rb) < 0:
        return None
    return pd.Timestamp(df.index[int(rb)]).strftime("%Y-%m-%d")


def signal_date(df: pd.DataFrame, ev: dict):
    for k in ("entry_signal_bar", "signal_bar"):
        sb = ev.get(k, -1)
        if sb is not None and int(sb) >= 0:
            return pd.Timestamp(df.index[int(sb)]).strftime("%Y-%m-%d")
    return None


def fill_date(df: pd.DataFrame, ev: dict):
    for k in ("entry_fill_bar", "fill_bar"):
        fb = ev.get(k, -1)
        if fb is not None and int(fb) >= 0:
            return pd.Timestamp(df.index[int(fb)]).strftime("%Y-%m-%d")
    return None


def index_events(events):
    out = {}
    for ev in events:
        k = str(ev.get("pivot_week_end") or ev.get("pivot_monday") or "")
        out[k] = ev
    return out


def compare_pair(df, a_evs, b_evs, label_a, label_b):
    ia, ib = index_events(a_evs), index_events(b_evs)
    keys = sorted(set(ia) | set(ib))
    bound_diff = retest_diff = signal_diff = fill_diff = only_a = only_b = 0
    details_bound, details_retest = [], []
    for k in keys:
        ea, eb = ia.get(k), ib.get(k)
        if ea is None:
            only_b += 1
            continue
        if eb is None:
            only_a += 1
            continue
        zl_a, zh_a = float(ea["zone_lower"]), float(ea["zone_upper"])
        zl_b, zh_b = float(eb["zone_lower"]), float(eb["zone_upper"])
        if zl_a != zl_b or zh_a != zh_b:
            bound_diff += 1
            if len(details_bound) < 8:
                details_bound.append({
                    "id": k,
                    "pivot_week_end": ea.get("pivot_week_end"),
                    f"zl_{label_a}": zl_a, f"zh_{label_a}": zh_a,
                    f"zl_{label_b}": zl_b, f"zh_{label_b}": zh_b,
                    f"tp_{label_a}": ea.get("pivot_high"), f"tp_{label_b}": eb.get("pivot_high"),
                })
        ra, rb = retest_date(df, ea), retest_date(df, eb)
        if ra != rb:
            retest_diff += 1
            if len(details_retest) < 12:
                details_retest.append({
                    "id": k,
                    "pivot_week_end": ea.get("pivot_week_end"),
                    f"retest_{label_a}": ra, f"retest_{label_b}": rb,
                    f"zh_{label_a}": zh_a, f"zh_{label_b}": zh_b,
                })
        if signal_date(df, ea) != signal_date(df, eb):
            signal_diff += 1
        if fill_date(df, ea) != fill_date(df, eb):
            fill_diff += 1
    return {
        "zones_a": len(ia), "zones_b": len(ib),
        "bound_diff": bound_diff, "retest_diff": retest_diff,
        "signal_diff": signal_diff, "fill_diff": fill_diff,
        "only_a": only_a, "only_b": only_b,
        "bound_examples": details_bound, "retest_examples": details_retest,
    }


def find_focus(df, events, want_dates):
    hits = []
    for ev in events:
        candidates = {str(ev.get("pivot_week_end") or ""), str(ev.get("pivot_monday") or "")}
        if candidates & want_dates:
            hits.append({
                "pivot_week_end": ev.get("pivot_week_end"),
                "pivot_monday": ev.get("pivot_monday"),
                "pivot_high_stored": ev.get("pivot_high"),
                "zl": ev.get("zone_lower"),
                "zh": ev.get("zone_upper"),
                "retest_date": retest_date(df, ev),
                "signal_date": signal_date(df, ev),
                "fill_date": fill_date(df, ev),
                "wpbr_zone_id": ev.get("wpbr_zone_id"),
            })
    return hits


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    paths = {s: str((OHLC_DIR / f"{s}.csv").resolve()) for s in SYMS}
    closed_exists = CLOSED.exists()
    closed_counts, closed_entry_dates = {}, {}
    if closed_exists:
        cdf = pd.read_csv(CLOSED)
        for s in SYMS:
            sub = cdf[cdf["SYMBOL"].astype(str).str.upper() == s]
            closed_counts[s] = int(len(sub))
            closed_entry_dates[s] = sorted(sub["DATE_OPENED"].astype(str).tolist())

    results, focus_out = {}, {}
    for sym in SYMS:
        df = load_ohlc(sym)
        print(f"=== {sym} bars={len(df)} {df.index.min().date()}..{df.index.max().date()} ===")
        streams = {}
        for vid, (desc, fn) in VARIANTS.items():
            streams[vid] = run_stream(df, fn)
            print(f"  {vid}: zones={len(streams[vid]['wpbr_zone_events'])} entries={len(streams[vid]['wpbr_entry_opportunities'])}")
        a_ev = streams["A"]["wpbr_zone_events"]
        results[sym] = {
            "bars": len(df),
            "ohlc_path": paths[sym],
            "total_zones": {vid: len(streams[vid]["wpbr_zone_events"]) for vid in VARIANTS},
            "total_entry_opps": {vid: len(streams[vid]["wpbr_entry_opportunities"]) for vid in VARIANTS},
            "A_vs_B": compare_pair(df, a_ev, streams["B"]["wpbr_zone_events"], "A", "B"),
            "A_vs_C": compare_pair(df, a_ev, streams["C"]["wpbr_zone_events"], "A", "C"),
            "A_vs_D": compare_pair(df, a_ev, streams["D"]["wpbr_zone_events"], "A", "D"),
            "B_vs_C": compare_pair(df, streams["B"]["wpbr_zone_events"], streams["C"]["wpbr_zone_events"], "B", "C"),
        }
        if sym in FOCUS:
            fo = {vid: find_focus(df, streams[vid]["wpbr_zone_events"], FOCUS[sym]["want_dates"]) for vid in VARIANTS}
            focus_out[sym] = fo
            print(f"  FOCUS {FOCUS[sym]['label']}:")
            for vid, hits in fo.items():
                for h in hits:
                    print(f"    {vid}: zl={h['zl']} zh={h['zh']} retest={h['retest_date']} tp={h['pivot_high_stored']} id={h['wpbr_zone_id']}")

    sanity = {}
    for name, piv in (("NVDA_raw_pivot", 4.2125), ("AMZN_raw_pivot", 233.0)):
        sanity[name] = piv
        sanity[name + "_bounds"] = {
            vid: {"tp": fn(piv, BAND, DEC)[0], "zl": fn(piv, BAND, DEC)[1], "zh": fn(piv, BAND, DEC)[2]}
            for vid, (_, fn) in VARIANTS.items()
        }

    summary_rows = []
    for sym in SYMS:
        r = results[sym]
        summary_rows.append({
            "symbol": sym,
            "zones_A": r["total_zones"]["A"],
            "A_vs_B_bound": r["A_vs_B"]["bound_diff"],
            "A_vs_B_retest": r["A_vs_B"]["retest_diff"],
            "A_vs_B_signal": r["A_vs_B"]["signal_diff"],
            "A_vs_B_fill": r["A_vs_B"]["fill_diff"],
            "A_vs_C_bound": r["A_vs_C"]["bound_diff"],
            "A_vs_C_retest": r["A_vs_C"]["retest_diff"],
            "A_vs_C_signal": r["A_vs_C"]["signal_diff"],
            "A_vs_C_fill": r["A_vs_C"]["fill_diff"],
            "A_vs_D_bound": r["A_vs_D"]["bound_diff"],
            "A_vs_D_retest": r["A_vs_D"]["retest_diff"],
            "closed_trades": closed_counts.get(sym),
        })

    def focus_zh_retest(sym, vid):
        hits = focus_out.get(sym, {}).get(vid, [])
        if not hits:
            return None, None
        h = hits[0]
        return h.get("zh"), h.get("retest_date")

    nvda_sheet_zh, nvda_sheet_retest = 4.27, "2017-09-25"
    amzn_sheet_zh, amzn_sheet_retest = 236.50, "2025-11-13"
    verdicts = {}
    for vid in ("A", "B", "C", "D"):
        nzh, nr = focus_zh_retest("NVDA", vid)
        azh, ar = focus_zh_retest("AMZN", vid)
        nvda_ok = (nzh == nvda_sheet_zh) and (nr == nvda_sheet_retest)
        amzn_ok = (azh == amzn_sheet_zh) and (ar == amzn_sheet_retest)
        verdicts[vid] = {
            "NVDA_zh": nzh, "NVDA_retest": nr,
            "NVDA_zh_match_sheet": nzh == nvda_sheet_zh,
            "NVDA_retest_match_sheet": nr == nvda_sheet_retest,
            "NVDA_case_fixed": nvda_ok,
            "AMZN_zh": azh, "AMZN_retest": ar,
            "AMZN_zh_match_sheet": azh == amzn_sheet_zh,
            "AMZN_retest_match_sheet": ar == amzn_sheet_retest,
            "AMZN_case_fixed": amzn_ok,
            "both_fixed": nvda_ok and amzn_ok,
        }

    payload = {
        "stamp_context": "260722105625",
        "params": {"band_pct": BAND, "retest_mode": "stop_looking", "start_date": START,
                   "strong": "3/0.1/either", "breakout_confirmation": 0.03,
                   "max_days_after_retest": 2, "zone_price_round_decimals": DEC},
        "ohlc_paths": paths,
        "closed_csv": str(CLOSED.resolve()) if closed_exists else None,
        "closed_counts": closed_counts,
        "closed_entry_dates": closed_entry_dates,
        "summary_rows": summary_rows,
        "focus": focus_out,
        "sanity_bounds": sanity,
        "verdicts": verdicts,
        "per_symbol": {
            s: {
                "total_zones": results[s]["total_zones"],
                "A_vs_B": {k: results[s]["A_vs_B"][k] for k in ("bound_diff", "retest_diff", "signal_diff", "fill_diff", "only_a", "only_b", "retest_examples", "bound_examples")},
                "A_vs_C": {k: results[s]["A_vs_C"][k] for k in ("bound_diff", "retest_diff", "signal_diff", "fill_diff", "only_a", "only_b", "retest_examples", "bound_examples")},
                "A_vs_D": {k: results[s]["A_vs_D"][k] for k in ("bound_diff", "retest_diff", "signal_diff", "fill_diff", "only_a", "only_b", "retest_examples")},
                "B_vs_C": {k: results[s]["B_vs_C"][k] for k in ("bound_diff", "retest_diff", "signal_diff", "fill_diff")},
            }
            for s in SYMS
        },
    }
    JSON_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print("JSON", JSON_PATH)

    lines = []
    L = lines.append
    L("# WPBR pivot-round band analysis")
    L("")
    L("Analysis-only simulation (runtime monkeypatch of `stock_analysis.wpbr_zones._round_bounds`).")
    L("No permanent engine patches. Stamp context: `260722105625`, `band_pct=0.015`, `retest_mode=stop_looking`, `start_date=2016-01-01`.")
    L("")
    L("## Paths used")
    L("")
    for s in SYMS:
        L(f"- OHLC `{s}`: `{paths[s]}`")
    L(f"- Closed CSV: `{CLOSED.resolve()}` (exists={closed_exists})")
    L(f"- Engine: `{wz.__file__}`")
    L(f"- JSON dump: `{JSON_PATH.resolve()}`")
    L("")
    L("## Closed CSV trade counts (context)")
    L("")
    if closed_exists:
        for s in SYMS:
            L(f"- **{s}**: {closed_counts[s]} closed trades; DATE_OPENED={closed_entry_dates[s]}")
    else:
        L("- Closed CSV not found")
    L("")
    L("## Bound construction variants")
    L("")
    L("| ID | Construction |")
    L("|----|--------------|")
    L("| A | Current: `tp=float(price)`; `zl/zh=round(tp*(1?band),2)` (Python bankers round) |")
    L("| B | `tp=round(price,2)` then float `round` band |")
    L("| C | Decimal HALF_UP `round(pivot,2)` then HALF_UP band (Sheets-like) |")
    L("| D | HALF_UP band only; no pivot round (tp raw float) |")
    L("")
    L("Monkeypatch site: `compute_wpbr_touch_stream` calls `_round_bounds(pivot_high, band_pct, dec)` at zone creation (`wpbr_zones.py`).")
    L("")
    L("## Sanity math (raw pivots)")
    L("")
    L("Sheet targets: NVDA zh=**4.27** (from 4.2125); AMZN zh=**236.50** (from 233).")
    L("")
    for name, piv in (("NVDA", 4.2125), ("AMZN", 233.0)):
        L(f"### {name} pivot={piv}")
        L("")
        L("| Variant | tp | zl | zh |")
        L("|---------|----|----|----|")
        for vid, (_, fn) in VARIANTS.items():
            tp, zl, zh = fn(piv, BAND, DEC)
            L(f"| {vid} | {tp} | {zl} | {zh} |")
        L("")
    L("## Focus cases (engine stream)")
    L("")
    L("Sheet expectations: NVDA 2017-06-05 zone ? zh 4.27, retest **2017-09-25**; AMZN 2024-12-16 zone ? zh 236.50, retest **2025-11-13**.")
    L("")
    for sym in ("NVDA", "AMZN"):
        L(f"### {sym} ({FOCUS[sym]['label']})")
        L("")
        L("| Variant | zl | zh | retest | signal | fill | zone_id |")
        L("|---------|----|----|--------|--------|------|---------|")
        for vid in VARIANTS:
            hits = focus_out.get(sym, {}).get(vid, [])
            if not hits:
                L(f"| {vid} | ? | ? | ? | ? | ? | NOT FOUND |")
            else:
                h = hits[0]
                L(f"| {vid} | {h['zl']} | {h['zh']} | {h['retest_date']} | {h['signal_date']} | {h['fill_date']} | `{h['wpbr_zone_id']}` |")
        L("")
        for vid in VARIANTS:
            L(f"- {vid} vs sheet: zh_match={verdicts[vid][f'{sym}_zh_match_sheet']}, retest_match={verdicts[vid][f'{sym}_retest_match_sheet']}")
        L("")
    L("## Quantified side effects (zones vs variant A)")
    L("")
    L("| Symbol | zones(A) | A?B bounds | A?B retest | A?B signal | A?B fill | A?C bounds | A?C retest | A?C signal | A?C fill | A?D bounds | A?D retest | Closed trades |")
    L("|--------|----------|------------|------------|------------|----------|------------|------------|------------|----------|------------|------------|---------------|")
    for row in summary_rows:
        L(
            f"| {row['symbol']} | {row['zones_A']} | {row['A_vs_B_bound']} | {row['A_vs_B_retest']} | {row['A_vs_B_signal']} | {row['A_vs_B_fill']} | "
            f"{row['A_vs_C_bound']} | {row['A_vs_C_retest']} | {row['A_vs_C_signal']} | {row['A_vs_C_fill']} | "
            f"{row['A_vs_D_bound']} | {row['A_vs_D_retest']} | {row['closed_trades']} |"
        )
    L("")
    L("### B vs C differences (bankers vs HALF_UP after pivot round)")
    L("")
    L("| Symbol | B?C bounds | B?C retest | B?C signal | B?C fill |")
    L("|--------|------------|------------|------------|----------|")
    for s in SYMS:
        bc = results[s]["B_vs_C"]
        L(f"| {s} | {bc['bound_diff']} | {bc['retest_diff']} | {bc['signal_diff']} | {bc['fill_diff']} |")
    L("")
    L("### Retest-date change examples (A?C, up to 12/symbol)")
    L("")
    for s in SYMS:
        ex = results[s]["A_vs_C"]["retest_examples"]
        L(f"**{s}** ({results[s]['A_vs_C']['retest_diff']} total retest diffs):")
        if not ex:
            L("- (none)")
        else:
            for e in ex:
                L(f"- `{e.get('pivot_week_end')}` zh A={e.get('zh_A')}?C={e.get('zh_C')}; retest A={e.get('retest_A')}?C={e.get('retest_C')}")
        L("")
    L("## Answers")
    L("")
    L("### 1. Can we ROUND pivot in engine before band? Where?")
    L("")
    L("**Yes.** Single choke point: `stock_analysis.wpbr_zones._round_bounds`, called from `compute_wpbr_touch_stream` when each weekly pivot-high zone is created (`touch, zl, zh = _round_bounds(pivot_high, ...)`).")
    L("`pbr_zones.py` is a shim to `wpbr_zones`, so WPBR/PBR share this path.")
    L("")
    L("### 2. Does it fix both NVDA+AMZN?")
    L("")
    for vid, desc in (("A", "current"), ("B", "round(pivot)+float band"), ("C", "HALF_UP pivot+band"), ("D", "HALF_UP band only")):
        v = verdicts[vid]
        both = "yes" if v["both_fixed"] else ("partial" if (v["NVDA_case_fixed"] or v["AMZN_case_fixed"]) else "no")
        L(
            f"- **{vid} ({desc})**: both={both}; "
            f"NVDA zh={v['NVDA_zh']} retest={v['NVDA_retest']} fixed={v['NVDA_case_fixed']}; "
            f"AMZN zh={v['AMZN_zh']} retest={v['AMZN_retest']} fixed={v['AMZN_case_fixed']}"
        )
    L("")
    L("### 3. Isolation: WPBR-only vs shared with BRT")
    L("")
    L("- **WPBR/PBR**: `_round_bounds` in `wpbr_zones.py` (this analysis). Changing it does **not** automatically change BRT.")
    L("- **BRT**: uses `rocket_brt._sheet_tp_band_bounds` (already Decimal **HALF_UP** on `tp*(1?band)` ? separate from WPBR).")
    L("- Therefore pivot-round-before-band is a **WPBR-local** decision unless deliberately mirrored into BRT.")
    L("")
    L("### 4. Quantified side effects")
    L("")
    tot_b_bounds = sum(r["A_vs_B_bound"] for r in summary_rows)
    tot_b_ret = sum(r["A_vs_B_retest"] for r in summary_rows)
    tot_c_bounds = sum(r["A_vs_C_bound"] for r in summary_rows)
    tot_c_ret = sum(r["A_vs_C_retest"] for r in summary_rows)
    tot_d_bounds = sum(r["A_vs_D_bound"] for r in summary_rows)
    tot_d_ret = sum(r["A_vs_D_retest"] for r in summary_rows)
    L(f"- Across META/NVDA/AMZN/NFLX: A?B bound changes **{tot_b_bounds}**, retest date changes **{tot_b_ret}**.")
    L(f"- Across same: A?C bound changes **{tot_c_bounds}**, retest date changes **{tot_c_ret}**.")
    L(f"- Across same: A?D bound changes **{tot_d_bounds}**, retest date changes **{tot_d_ret}**.")
    L("- See table above for per-symbol signal/fill bar diffs (proxy for trade entry shifts).")
    L("")
    L("### 5. Recommended approach + pitfalls")
    L("")
    if verdicts["C"]["both_fixed"]:
        L("- **Recommend C** (HALF_UP round pivot to 2dp, then HALF_UP ?1.5% band) to match Google Sheets `ROUND` for both NVDA and AMZN focus cases.")
    elif verdicts["B"]["both_fixed"]:
        L("- **Recommend B** ? both focus cases fixed with float round(pivot)+band.")
    else:
        L("- Prefer the variant that matches Sheets ROUND for both zh and retest; see focus table / verdicts.")
    L("- **Pitfall ? bankers rounding**: Python `round` is HALF_EVEN. `x.xx5` can diverge from Sheets `ROUND` (HALF_UP). B can fix NVDA (4.2125?4.21?zh 4.27) while AMZN needs HALF_UP on `233*1.015=236.495?236.50`.")
    L("- **Pitfall ? D alone**: HALF_UP band without pivot round fixes AMZN zh but leaves NVDA at zh 4.28.")
    L("- **Pitfall ? B alone**: float pivot round helps NVDA but AMZN zh may stay 236.49 under bankers round of 236.495.")
    L("- Changing `_round_bounds` shifts zone IDs (`make_wpbr_zone_id` embeds zl/zh), retest/signal/fill bars, and Closed trade sets ? re-stamp reconcile after any production change.")
    L("- Do **not** assume BRT needs the same pivot-pre-round; it already HALF_UPs band bounds separately.")
    L("")
    L("## Verdict snapshot")
    L("")
    L(f"- Fix both NVDA+AMZN focus (zh+retest): A={verdicts['A']['both_fixed']}, B={verdicts['B']['both_fixed']}, C={verdicts['C']['both_fixed']}, D={verdicts['D']['both_fixed']}")
    L("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("MD", OUT_MD)
    print("VERDICTS", json.dumps(verdicts, indent=2))


if __name__ == "__main__":
    main()
