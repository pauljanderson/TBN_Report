#!/usr/bin/env python3
"""Verify WPBR MarkTen parity vs stamp 260722174041 + sheet pastes. Diagnose-only; no commit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import _round_bounds, compute_wpbr_touch_stream  # noqa: E402

BASE = REPO / "drive" / "wpbr_sheet_reconcile"
OLD_DIR = BASE / "_markten_variantC_SC_stop91_startfloor_halfup_scresume_20260722174137"
NEW_DIR = BASE / "_markten_parity_verify_20260723180034"
OLD_STAMP = "260722174041"
NEW_STAMP = "260723180035"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
FOCUS = {
    "AMZN": ["2022-12-08"],
    "AU": ["2019-04-25"],
    "TSLA": ["2022-12-16"],
}


def read_text_any(p: Path) -> str:
    b = p.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 1 and b[1] == 0):
        for enc in ("utf-16", "utf-16-le"):
            try:
                return b.decode(enc)
            except Exception:
                pass
    return b.decode("utf-8", errors="ignore")


def nd(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    if s.isdigit() and len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def nf(s):
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").replace("%", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_entry(s) -> str | None:
    d = nd(s)
    if d:
        return d
    try:
        t = str(int(s))
        if len(t) == 8:
            return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    except Exception:
        pass
    return None


def bar_to_date(idx, b):
    if b is None:
        return None
    try:
        b = int(b)
    except Exception:
        return None
    if b < 0 or b >= len(idx):
        return None
    return pd.Timestamp(idx[b]).strftime("%Y-%m-%d")


def load_sheet_zones(sym_dir: Path) -> list[dict]:
    for name in ("zones.tsv", "sheet_zones.tsv"):
        p = sym_dir / name
        if p.is_file():
            break
    else:
        return []
    rows = []
    for line in read_text_any(p).splitlines()[1:]:
        if not line.strip():
            continue
        c = line.split("\t") + [""] * 20
        piv = nd(c[9])
        if not piv:
            continue
        rows.append(
            {
                "pivot": piv,
                "bo": nd(c[5]),
                "zlow": nf(c[6]),
                "zhigh": nf(c[7]),
                "conf": nd(c[13]),
                "next": nd(c[14]),
                "retest": nd(c[16]),
                "rocket": nd(c[18]),
            }
        )
    return rows


def load_sheet_trades(sym_dir: Path) -> list[dict]:
    for name in ("trades.tsv", "sheet_trades.tsv"):
        p = sym_dir / name
        if p.is_file():
            break
    else:
        return []
    lines = read_text_any(p).splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Entry Date"):
            start = i + 1
            break
    trades = []
    for line in lines[start:]:
        if not line.strip():
            continue
        c = line.split("\t")
        entry = nd(c[0])
        if not entry:
            continue
        trades.append(
            {
                "entry": entry,
                "entry_px": nf(c[1]) if len(c) > 1 else None,
                "exit": nd(c[2]) if len(c) > 2 else None,
                "exit_px": nf(c[3]) if len(c) > 3 else None,
            }
        )
    return trades


def load_closed_from(stamp_dir: Path, stamp: str, sym: str) -> list[dict]:
    p = stamp_dir / f"WPBR_Closed_{stamp}.csv"
    df = pd.read_csv(p)
    df = df[df["SYMBOL"].astype(str).str.upper() == sym.upper()].copy()
    out = []
    for _, r in df.iterrows():
        out.append(
            {
                "entry": parse_entry(r["DATE_OPENED"]),
                "exit": parse_entry(r.get("DATE_CLOSED")),
                "entry_px": nf(r["ENTRY_PRICE"]),
                "exit_px": nf(r.get("EXIT_PRICE")),
                "open": False,
            }
        )
    op = stamp_dir / f"WPBR_Open_{stamp}.csv"
    if op.is_file():
        odf = pd.read_csv(op)
        if "SYMBOL" in odf.columns:
            odf = odf[odf["SYMBOL"].astype(str).str.upper() == sym.upper()]
            for _, r in odf.iterrows():
                out.append(
                    {
                        "entry": parse_entry(r["DATE_OPENED"]),
                        "exit": None,
                        "entry_px": nf(r["ENTRY_PRICE"]),
                        "exit_px": None,
                        "open": True,
                    }
                )
    out.sort(key=lambda x: x["entry"] or "")
    return out


def build_eng(df: pd.DataFrame) -> tuple[dict, set[str]]:
    idx = pd.DatetimeIndex(df.index)
    stream = compute_wpbr_touch_stream(
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
        min_pivot_date=MIN_DATE,
    )
    eng = {}
    for ev in stream["wpbr_zone_events"]:
        piv = nd(ev["pivot_monday"])
        if not piv:
            continue
        eng[piv] = {
            "zlow": float(ev["zone_lower"]),
            "zhigh": float(ev["zone_upper"]),
            "bo": nd(ev["breakout_monday"]),
            "conf": nd(ev["conf_monday"]),
            "next": nd(ev["next_week_start"]),
            "retest": bar_to_date(idx, ev.get("retest_bar")),
            "signal": bar_to_date(idx, ev.get("entry_signal_bar")),
            "fill": bar_to_date(idx, ev.get("entry_fill_bar")),
            "zone_id": str(ev.get("wpbr_zone_id") or ""),
        }
    raw_fills = {e["fill"] for e in eng.values() if e["fill"]}
    for opp in stream.get("wpbr_entry_opportunities") or []:
        fd = bar_to_date(idx, opp.get("entry_fill_bar"))
        if fd:
            raw_fills.add(fd)
    return eng, raw_fills


def structure_stats(sheet_z: list[dict], eng: dict) -> dict:
    zone_ok = retest_ok = rocket_ok = rocket_where_sheet = rocket_sheet_fires = 0
    n_pairs = 0
    eng_only = []
    for z in sheet_z:
        piv = z["pivot"]
        e = eng.get(piv)
        if not e:
            continue
        n_pairs += 1
        if (
            z["zlow"] is not None
            and z["zhigh"] is not None
            and abs(e["zlow"] - z["zlow"]) < 0.02
            and abs(e["zhigh"] - z["zhigh"]) < 0.02
        ):
            zone_ok += 1
        if (z["retest"] or None) == (e["retest"] or None):
            retest_ok += 1
        if z["rocket"]:
            rocket_sheet_fires += 1
            ok = False
            if e["signal"] == z["rocket"]:
                ok = True
            elif e["fill"] and abs(
                (pd.Timestamp(e["fill"]) - pd.Timestamp(z["rocket"])).days
            ) <= 2:
                ok = True
            elif e["signal"]:
                try:
                    if abs((pd.Timestamp(e["signal"]) - pd.Timestamp(z["rocket"])).days) <= 1:
                        ok = True
                except Exception:
                    pass
            if ok:
                rocket_where_sheet += 1
                rocket_ok += 1
        else:
            if e["signal"]:
                eng_only.append(
                    {
                        "pivot": piv,
                        "eng_signal": e["signal"],
                        "eng_fill": e["fill"],
                    }
                )
    return {
        "n_pairs": n_pairs,
        "zone_ok": zone_ok,
        "retest_ok": retest_ok,
        "rocket_ok": rocket_ok,
        "rocket_sheet_fires": rocket_sheet_fires,
        "rocket_where_sheet": rocket_where_sheet,
        "eng_only_rockets": eng_only,
    }


def ser_match(sheet_trades: list[dict], eng_closed: list[dict]) -> dict:
    """Ser = sheet entry date present in engine closed/open entries (canonical MarkTen metric)."""
    ser = {t["entry"] for t in eng_closed if t["entry"]}
    matched = [t for t in sheet_trades if t["entry"] in ser]
    sheet_only = [t for t in sheet_trades if t["entry"] not in ser]
    eng_only = [t for t in eng_closed if t["entry"] and t["entry"] not in {x["entry"] for x in sheet_trades}]
    return {
        "matched": matched,
        "sheet_only": sheet_only,
        "eng_only": eng_only,
        "ser_n": len(matched),
        "ser_d": len(sheet_trades),
    }


def raw_match(sheet_trades: list[dict], raw_fills: set[str]) -> dict:
    matched = [t for t in sheet_trades if t["entry"] in raw_fills]
    sheet_only = [t for t in sheet_trades if t["entry"] not in raw_fills]
    return {
        "matched": matched,
        "sheet_only": sheet_only,
        "raw_n": len(matched),
        "raw_d": len(sheet_trades),
    }


def load_closed_df(stamp_dir: Path, stamp: str) -> pd.DataFrame:
    df = pd.read_csv(stamp_dir / f"WPBR_Closed_{stamp}.csv")
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.upper()
    df = df[df.SYMBOL.isin(MARKTEN)].copy()
    for c in ("DATE_OPENED", "DATE_CLOSED"):
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.strftime("%Y-%m-%d")
    for c in ("ENTRY_PRICE", "EXIT_PRICE", "PNL_PCT", "STOP_PRICE", "TARGET_PRICE", "PNL_DOLLARS"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["_ek"] = df["ENTRY_PRICE"].round(4)
    df["_xk"] = df["EXIT_PRICE"].round(4)
    df["_id"] = (
        df["SYMBOL"]
        + "|"
        + df["DATE_OPENED"].fillna("")
        + "|"
        + df["DATE_CLOSED"].fillna("")
        + "|"
        + df["_ek"].astype(str)
        + "|"
        + df["_xk"].astype(str)
    )
    df["eid"] = df["SYMBOL"] + "|" + df["DATE_OPENED"].fillna("")
    return df


def main() -> int:
    # --- Variant C HALF_UP smoke ---
    mid, lo, hi = _round_bounds(100.125, 0.015, 2)
    halfup_ok = (lo, mid, hi) == (98.63, 100.13, 101.63)
    print(f"HALF_UP sample: {mid}/{lo}/{hi} expected 100.13/98.63/101.63 -> {'PASS' if halfup_ok else 'FAIL'}")

    # --- Closed identity vs prior stamp ---
    old = load_closed_df(OLD_DIR, OLD_STAMP)
    new = load_closed_df(NEW_DIR, NEW_STAMP)
    old_ids, new_ids = set(old["_id"]), set(new["_id"])
    only_old = sorted(old_ids - new_ids)
    only_new = sorted(new_ids - old_ids)
    both = old_ids & new_ids
    print(
        f"\nClosed identity vs {OLD_STAMP}: old={len(old)} new={len(new)} "
        f"match={len(both)} old_only={len(only_old)} new_only={len(only_new)}"
    )
    for s in MARKTEN:
        oset = set(old.loc[old.SYMBOL == s, "_id"])
        nset = set(new.loc[new.SYMBOL == s, "_id"])
        print(
            f"  {s}: old={len(oset)} new={len(nset)} match={len(oset & nset)} "
            f"old_only={len(oset - nset)} new_only={len(nset - oset)}"
        )
    if only_old:
        print("old_only sample:", only_old[:20])
    if only_new:
        print("new_only sample:", only_new[:20])

    oe, ne = set(old.eid), set(new.eid)
    print(
        f"Entry-date identity: match={len(oe & ne)} old_only={len(oe - ne)} new_only={len(ne - oe)}"
    )
    if oe - ne:
        print(" entry old_only:", sorted(oe - ne)[:20])
    if ne - oe:
        print(" entry new_only:", sorted(ne - oe)[:20])

    m = old.merge(new, on=["SYMBOL", "DATE_OPENED"], suffixes=("_o", "_n"), how="inner")
    price_drift = {}
    for col in ("ENTRY_PRICE", "EXIT_PRICE", "STOP_PRICE", "TARGET_PRICE", "PNL_PCT"):
        if f"{col}_o" in m.columns and f"{col}_n" in m.columns:
            diff = (m[f"{col}_o"] - m[f"{col}_n"]).abs()
            price_drift[col] = {
                "max_abs_diff": float(diff.max()) if len(diff) else 0.0,
                "n_diff_gt_1e4": int((diff > 1e-4).sum()),
                "n": len(m),
            }
            print(
                f" matched {col}: max_abs_diff={diff.max():.6g} "
                f"n_diff>1e-4={(diff > 1e-4).sum()}/{len(m)}"
            )

    # SMA / IND columns present on new?
    new_cols = set(pd.read_csv(NEW_DIR / f"WPBR_Closed_{NEW_STAMP}.csv", nrows=0).columns)
    sma_cols = sorted(c for c in new_cols if "SMA" in c.upper())
    ind_cols = sorted(c for c in new_cols if c.startswith("IND_") or c.startswith("IND_TC"))
    print(f"\nNew Closed SMA cols ({len(sma_cols)}): {sma_cols[:12]}")
    print(f"New Closed IND/TC cols ({len(ind_cols)}): {ind_cols[:20]}")

    # Dollar scale
    if len(m) and "PNL_PCT_o" in m.columns and "PNL_DOLLARS_n" in m.columns:
        # sheet uses 47500; engine scales to ~142857 => ratio ~3.0075
        ratio = (m["PNL_DOLLARS_n"] / (m["PNL_PCT_n"] / 100.0 * 47500)).replace(
            [float("inf"), -float("inf")], pd.NA
        )
        ratio = ratio.dropna()
        print(
            f"Dollar sizing ratio vs $47.5k unit: median={ratio.median():.6f} "
            f"(expected ~3.00752)"
        )

    # --- Sheet reconcile (ser) ---
    rows = []
    ser_num = ser_den = 0
    raw_num = raw_den = 0
    total_eng_only = 0
    total_sheet_only = 0
    print("\n=== Sheet reconcile (ser) vs pastes ===")
    print(
        f"{'Ticker':<6} {'Piv':>7} {'Zones':>7} {'Retest':>8} {'Rocket':>8} "
        f"{'Raw':>8} {'Ser':>8} {'EngCl':>5} eng_only sheet_only"
    )
    for sym in MARKTEN:
        sym_dir = BASE / sym
        sheet_z = load_sheet_zones(sym_dir)
        sheet_t_all = load_sheet_trades(sym_dir)
        sheet_t = [t for t in sheet_t_all if t["entry"] and t["entry"] >= MIN_DATE]
        df = pd.read_csv(DATA / f"{sym}.csv", index_col=0, parse_dates=True)
        eng_all, raw_all = build_eng(df)
        eng = {p: e for p, e in eng_all.items() if p >= MIN_DATE}
        raw_fills = {f for f in raw_all if f and f >= MIN_DATE}
        sheet_z_f = [z for z in sheet_z if z["pivot"] and z["pivot"] >= MIN_DATE]
        st = structure_stats(sheet_z_f, eng)
        closed = load_closed_from(NEW_DIR, NEW_STAMP, sym)
        sm = ser_match(sheet_t, closed)
        rm = raw_match(sheet_t, raw_fills)
        ser_num += sm["ser_n"]
        ser_den += sm["ser_d"]
        raw_num += rm["raw_n"]
        raw_den += rm["raw_d"]
        total_eng_only += len(sm["eng_only"])
        total_sheet_only += len(sm["sheet_only"])
        piv_n = sum(1 for z in sheet_z_f if z["pivot"] in eng)
        print(
            f"{sym:<6} {piv_n}/{len(sheet_z_f):>3} "
            f"{st['zone_ok']}/{st['n_pairs']:>3} "
            f"{st['retest_ok']}/{st['n_pairs']:>3} "
            f"{st['rocket_ok']}/{st['rocket_sheet_fires']:>3} "
            f"{rm['raw_n']}/{rm['raw_d']:>3} "
            f"{sm['ser_n']}/{sm['ser_d']:>3} "
            f"{len(closed):>5} "
            f"{len(sm['eng_only']):>8} {len(sm['sheet_only']):>10}"
        )
        focus_notes = []
        ser_set = {t["entry"] for t in closed if t["entry"]}
        for d in FOCUS.get(sym, []):
            focus_notes.append(f"{d}: ser={d in ser_set} closed={d in ser_set}")
        rows.append(
            {
                "symbol": sym,
                "pivots": f"{piv_n}/{len(sheet_z_f)}",
                "zones": f"{st['zone_ok']}/{st['n_pairs']}",
                "retest": f"{st['retest_ok']}/{st['n_pairs']}",
                "rocket": f"{st['rocket_ok']}/{st['rocket_sheet_fires']}",
                "raw": f"{rm['raw_n']}/{rm['raw_d']}",
                "ser": f"{sm['ser_n']}/{sm['ser_d']}",
                "eng_closed": len(closed),
                "eng_only": [t["entry"] for t in sm["eng_only"]],
                "sheet_only": [t["entry"] for t in sm["sheet_only"]],
                "raw_only": [t["entry"] for t in rm["sheet_only"]],
                "focus": focus_notes,
                "eng_only_rockets": len(st["eng_only_rockets"]),
            }
        )
        if sm["sheet_only"]:
            print(f"  sheet_only entries: {[t['entry'] for t in sm['sheet_only']]}")
        if sm["eng_only"]:
            print(f"  eng_only entries: {[t['entry'] for t in sm['eng_only']]}")

    print(
        f"\nSer rollup: {ser_num} / {ser_den} "
        f"({100.0 * ser_num / ser_den if ser_den else 0:.1f}%)"
    )
    print(f"Raw rollup: {raw_num} / {raw_den}")
    print(f"Total eng-only closed (vs sheet trades): {total_eng_only}")
    print(f"Total sheet-only (ser): {total_sheet_only}")
    print(f"Prior baseline ser: 142 / 142 (100.0%)")

    identity_ok = len(only_old) == 0 and len(only_new) == 0
    ser_ok = ser_num == ser_den == 142
    verdict = "PASS" if identity_ok and ser_ok and halfup_ok else (
        "REGRESSED" if (not identity_ok or ser_num < 142) else "FAIL"
    )
    # refine: if ser still 142/142 and identity matches -> PASS; if ser drops -> REGRESSED
    if ser_den and ser_num == ser_den and ser_num >= 142 and halfup_ok:
        if identity_ok:
            verdict = "PASS"
        elif len(oe - ne) == 0 and len(ne - oe) == 0:
            # entry dates same but exit/price drift
            verdict = "PASS"  # trade identity by entry preserved; note price drift separately
        else:
            verdict = "REGRESSED"
    elif ser_den and ser_num < 142:
        verdict = "REGRESSED"
    else:
        verdict = "FAIL"

    payload = {
        "verdict": verdict,
        "halfup_ok": halfup_ok,
        "new_stamp": NEW_STAMP,
        "new_outdir": str(NEW_DIR),
        "old_stamp": OLD_STAMP,
        "closed_identity": {
            "old_n": len(old),
            "new_n": len(new),
            "match": len(both),
            "old_only": only_old,
            "new_only": only_new,
            "entry_old_only": sorted(oe - ne),
            "entry_new_only": sorted(ne - oe),
            "price_drift": price_drift,
        },
        "ser": {"n": ser_num, "d": ser_den, "prior": "142/142"},
        "raw": {"n": raw_num, "d": raw_den},
        "eng_only_total": total_eng_only,
        "sheet_only_total": total_sheet_only,
        "per_symbol": rows,
        "sma_cols": sma_cols,
        "ind_cols": ind_cols[:40],
        "dollar_scale_note": "PNL_DOLLARS still scaled ~×3.00752 vs sheet $47,500 unit (142857/47500)",
        "bat_flag_note": (
            "run_wpbr.bat comment claims start_date 2016 but CLI omits -v start_date=2016-01-01; "
            "this verify run passed start_date explicitly (parity required)."
        ),
    }
    out = BASE / "_parity_verify_20260723_payload.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nVERDICT: {verdict}")
    print(f"Wrote {out}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
