#!/usr/bin/env python3
"""Full MarkTen SC mismatch inventory + NFLX Aug-exit bar walk."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))

STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_SC_2016_20260722145207"
STAMP = "260722145252"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]


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


def load_sheet_trades(sym_dir: Path) -> list[dict]:
    for name in ("trades.tsv", "sheet_trades.tsv", "sheet_trades.csv"):
        p = sym_dir / name
        if p.is_file():
            break
    else:
        return []
    rows = []
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p)
        for _, r in df.iterrows():
            ed = nd(r.get("Entry Date"))
            if not ed:
                continue
            rows.append(
                {
                    "entry": ed,
                    "entry_px": nf(r.get("Entry Price")),
                    "exit": nd(r.get("Exit Date")),
                    "exit_px": nf(r.get("Exit Price")),
                    "result": str(r.get("Result", "")).strip().upper() or None,
                    "pnl_pct": nf(r.get("Profit %")),
                }
            )
        return rows
    for line in read_text_any(p).splitlines()[1:]:
        if not line.strip():
            continue
        c = line.split("\t") + [""] * 12
        ed = nd(c[0])
        if not ed:
            continue
        rows.append(
            {
                "entry": ed,
                "entry_px": nf(c[1]),
                "exit": nd(c[2]),
                "exit_px": nf(c[3]),
                "result": str(c[6]).strip().upper() or None,
                "pnl_pct": nf(c[4]),
            }
        )
    return rows


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


def eng_date(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(int(float(v))) if str(v).replace(".", "").isdigit() else str(v)
    s = s.replace("-", "").replace("/", "")[:8]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return nd(v)


def load_engine_closed() -> pd.DataFrame:
    df = pd.read_csv(STAMP_DIR / f"WPBR_Closed_{STAMP}.csv")
    df["entry"] = df["DATE_OPENED"].map(eng_date)
    df["exit"] = df["DATE_CLOSED"].map(eng_date)
    return df


def load_engine_bo() -> pd.DataFrame:
    p = STAMP_DIR / f"WPBR_breakout_and_retest_{STAMP}.csv"
    if not p.is_file():
        return pd.DataFrame()
    return pd.read_csv(p)


def px_close(a, b, tol=0.02):
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def nearest_session_delta(d1: str | None, d2: str | None) -> int | None:
    if not d1 or not d2:
        return None
    return (pd.Timestamp(d1) - pd.Timestamp(d2)).days


def classify_pair(s: dict, e: dict) -> list[dict]:
    """Return mismatch records for a matched entry-date pair (may be empty if perfect)."""
    out = []
    se, ee = s["entry"], e["entry"]
    sx, ex = s.get("exit"), e.get("exit")
    sp, ep = s.get("entry_px"), float(e["ENTRY_PRICE"])
    sxp, exp = s.get("exit_px"), float(e["EXIT_PRICE"])
    if se != ee:
        # shouldn't happen if keyed by entry
        out.append(("entry_date", se, ee))
    if not px_close(sp, ep):
        out.append(
            {
                "type": "entry_price_mismatch",
                "sheet": f"{se} @{sp}",
                "engine": f"{ee} @{ep:.2f}",
                "detail": f"delta={abs(sp-ep):.4f}" if sp is not None else "sheet_px_missing",
            }
        )
    if sx != ex:
        delta = nearest_session_delta(sx, ex)
        out.append(
            {
                "type": "exit_date_mismatch",
                "sheet": f"{sx} @{sxp} {s.get('result')}",
                "engine": f"{ex} @{exp:.2f} {e.get('EXIT_TYPE')}",
                "detail": f"calendar_delta_days={delta}; stop={e.get('STOP_PRICE')}",
            }
        )
    elif not px_close(sxp, exp):
        out.append(
            {
                "type": "exit_price_mismatch",
                "sheet": f"{sx} @{sxp}",
                "engine": f"{ex} @{exp:.2f} {e.get('EXIT_TYPE')}",
                "detail": f"delta={abs(sxp-exp):.4f}" if sxp is not None else "sheet_px_missing",
            }
        )
    # result vs exit type sanity (WIN should be TARGET/GAP_UP etc.)
    sr = (s.get("result") or "").upper()
    et = str(e.get("EXIT_TYPE") or "").upper()
    if sr == "WIN" and ("STOP" in et or "GAP_DOWN" in et):
        out.append(
            {
                "type": "result_type_conflict",
                "sheet": f"{sr} {s.get('pnl_pct')}",
                "engine": et,
                "detail": "",
            }
        )
    if sr == "LOSS" and ("TARGET" in et or "GAP_UP" in et):
        out.append(
            {
                "type": "result_type_conflict",
                "sheet": f"{sr} {s.get('pnl_pct')}",
                "engine": et,
                "detail": "",
            }
        )
    return out


def invent_for_symbol(sym: str, eng: pd.DataFrame, bo: pd.DataFrame) -> dict:
    sym_dir = BASE / sym
    sheet_tr = load_sheet_trades(sym_dir)
    sheet_z = load_sheet_zones(sym_dir)
    e_sym = eng[eng["SYMBOL"].astype(str).str.upper() == sym].copy()
    e_by_entry = {r["entry"]: r for _, r in e_sym.iterrows() if r["entry"]}
    s_by_entry = {t["entry"]: t for t in sheet_tr if t["entry"]}

    sheet_only = sorted(set(s_by_entry) - set(e_by_entry))
    eng_only = sorted(set(e_by_entry) - set(s_by_entry))
    matched = sorted(set(s_by_entry) & set(e_by_entry))

    mismatches = []
    for d in sheet_only:
        t = s_by_entry[d]
        mismatches.append(
            {
                "ticker": sym,
                "type": "sheet_only_trade",
                "sheet": f"{t['entry']} @{t['entry_px']} -> {t['exit']} @{t['exit_px']} {t['result']}",
                "engine": "—",
                "cause": "orphan / SC timing / cascade",
                "severity": "blocks_identity",
            }
        )
    for d in eng_only:
        r = e_by_entry[d]
        mismatches.append(
            {
                "ticker": sym,
                "type": "engine_only_trade",
                "sheet": "—",
                "engine": f"{r['entry']} @{float(r['ENTRY_PRICE']):.2f} -> {r['exit']} @{float(r['EXIT_PRICE']):.2f} {r['EXIT_TYPE']}",
                "cause": "eng-only / cascade from prior exit fork",
                "severity": "blocks_identity",
            }
        )

    # Off-by-one entry pairing: sheet date D vs eng D±1 not already matched
    for d in list(sheet_only):
        for delta in (-1, 1, -3, 3, -4, 4):  # include weekend-ish
            cand = (pd.Timestamp(d) + pd.Timedelta(days=delta)).strftime("%Y-%m-%d")
            if cand in eng_only:
                t = s_by_entry[d]
                r = e_by_entry[cand]
                # replace the two orphan rows with a paired timing mismatch if prices close
                mismatches = [
                    m
                    for m in mismatches
                    if not (
                        (m["type"] == "sheet_only_trade" and m["sheet"].startswith(d))
                        or (m["type"] == "engine_only_trade" and m["engine"].startswith(cand))
                    )
                ]
                mismatches.append(
                    {
                        "ticker": sym,
                        "type": "entry_date_off_by_session",
                        "sheet": f"{t['entry']} @{t['entry_px']} -> {t['exit']} @{t['exit_px']} {t['result']}",
                        "engine": f"{r['entry']} @{float(r['ENTRY_PRICE']):.2f} -> {r['exit']} @{float(r['EXIT_PRICE']):.2f} {r['EXIT_TYPE']}",
                        "cause": "prior exit timing / fill lag",
                        "severity": "blocks_identity",
                    }
                )
                sheet_only = [x for x in sheet_only if x != d]
                eng_only = [x for x in eng_only if x != cand]
                break

    perfect = 0
    for d in matched:
        pair_issues = classify_pair(s_by_entry[d], e_by_entry[d].to_dict())
        if not pair_issues:
            perfect += 1
            continue
        for iss in pair_issues:
            if isinstance(iss, tuple):
                continue
            sev = "blocks_identity" if iss["type"].startswith("exit_date") or iss["type"].startswith("entry") else "cosmetic"
            if iss["type"] == "exit_date_mismatch":
                sev = "blocks_identity"
            if iss["type"] == "exit_price_mismatch":
                # cents vs material
                try:
                    dlt = abs(float(s_by_entry[d]["exit_px"]) - float(e_by_entry[d]["EXIT_PRICE"]))
                    sev = "cosmetic" if dlt < 0.05 else "blocks_identity"
                except Exception:
                    sev = "cosmetic"
            mismatches.append(
                {
                    "ticker": sym,
                    "type": iss["type"],
                    "sheet": iss["sheet"],
                    "engine": iss["engine"],
                    "cause": iss.get("detail") or iss["type"],
                    "severity": sev,
                }
            )

    # Zone / retest / rocket diffs
    zone_diffs = []
    if not bo.empty and "SYMBOL" in bo.columns:
        b_sym = bo[bo["SYMBOL"].astype(str).str.upper() == sym]
    else:
        b_sym = pd.DataFrame()

    # Use payload if present for structured zone compare later; quick rocket set compare
    sheet_rockets = {z["rocket"] for z in sheet_z if z.get("rocket")}
    eng_rockets = set()
    if not b_sym.empty:
        for col in ("ROCKET_BUY_DATE", "SIGNAL_DATE", "ROCKET_DATE", "DATE_ROCKET"):
            if col in b_sym.columns:
                for v in b_sym[col]:
                    d = eng_date(v) or nd(v)
                    if d:
                        eng_rockets.add(d)
                break
        # also try WPBR signal columns
        for col in b_sym.columns:
            if "ROCKET" in col.upper() or col.upper() in {"SIGNAL_DATE", "BUY_SIGNAL_DATE"}:
                for v in b_sym[col]:
                    d = eng_date(v) or nd(v)
                    if d:
                        eng_rockets.add(d)

    return {
        "ticker": sym,
        "sheet_n": len(sheet_tr),
        "eng_n": len(e_sym),
        "perfect_matches": perfect,
        "matched_entries": len(matched),
        "mismatches": mismatches,
        "sheet_rockets_n": len(sheet_rockets),
        "zone_diffs": zone_diffs,
    }


def walk_nflx_aug_exit():
    """Bar-by-bar for Aug 2023 NFLX trade around 10/12-10/13."""
    # Load OHLC
    ohlc_path = DATA / "NFLX.csv"
    if not ohlc_path.is_file():
        alts = list((REPO / "data").rglob("NFLX.csv"))
        ohlc_path = alts[0] if alts else None
    if ohlc_path is None:
        return {"error": "no NFLX OHLC"}

    df = pd.read_csv(ohlc_path)
    # normalize columns
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("date") or cols.get("datetime") or list(df.columns)[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    for need in ("open", "high", "low", "close"):
        if need not in {c.lower() for c in df.columns}:
            # try Title case
            pass
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if cl in ("open", "high", "low", "close", "volume", "adj close", "adj_close"):
            rename[c] = cl.replace(" ", "_")
    df = df.rename(columns=rename)

    entry = 40.22
    stop_entry = round(entry * 0.89, 2)  # if stop based on entry
    # Engine closed row
    eng = load_engine_closed()
    row = eng[(eng.SYMBOL == "NFLX") & (eng.entry == "2023-08-21")].iloc[0]
    eng_stop = float(row["STOP_PRICE"])
    eng_tgt = float(row["TARGET_PRICE"])
    eng_exit = float(row["EXIT_PRICE"])
    eng_exit_type = row["EXIT_TYPE"]

    # Sheet
    sheet = {
        "entry": "2023-08-21",
        "entry_px": 40.22,
        "exit": "2023-10-12",
        "exit_px": 36.24,
        "result": "LOSS",
        "pnl_pct": -9.91,
    }

    # Walk bars from entry next day through 10/16
    start = pd.Timestamp("2023-08-21")
    end = pd.Timestamp("2023-10-17")
    window = df.loc[start:end]

    # Also get signal day for stop_loss_based=trigger_low
    # From zone rocket: need signal date for Aug trade
    # Engine zone 2022-04-01|39.06|40.24 — find BO/retest from closed or bo file
    bo = load_engine_bo()
    sig_info = {}
    if not bo.empty:
        b = bo[bo["SYMBOL"].astype(str).str.upper() == "NFLX"]
        # find zone matching
        for _, r in b.iterrows():
            zl = nf(r.get("ZONE_LOW") or r.get("LOWER") or r.get("ZONE_LOWER"))
            zh = nf(r.get("ZONE_HIGH") or r.get("UPPER") or r.get("ZONE_UPPER"))
            # loose match
            pass

    bars = []
    first_stop_touch = None
    first_gap_down = None
    first_target = None
    sheet_exit_bar = None
    for dt, r in window.iterrows():
        o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        d = dt.strftime("%Y-%m-%d")
        gap_down = o <= eng_stop
        stop_hit = l <= eng_stop
        target_hit = h >= eng_tgt
        # sheet exit price check
        close_match_sheet = abs(c - 36.24) < 0.05
        open_match_sheet = abs(o - 36.24) < 0.05
        # what if sheet stop is different?
        entry_stop = entry * 0.89
        stop_hit_entry = l <= entry_stop
        gap_entry = o <= entry_stop
        # what price is 36.24 relative to?
        bars.append(
            {
                "date": d,
                "O": round(o, 3),
                "H": round(h, 3),
                "L": round(l, 3),
                "C": round(c, 3),
                "gap_down_eng_stop": gap_down,
                "stop_hit_eng_stop": stop_hit,
                "target_hit": target_hit,
                "stop_hit_entry_x089": stop_hit_entry,
                "gap_entry_x089": gap_entry,
                "C_vs_sheet_exit": round(c - 36.24, 3),
                "O_vs_sheet_exit": round(o - 36.24, 3),
                "L_vs_eng_stop": round(l - eng_stop, 3),
                "L_vs_entry089": round(l - entry_stop, 3),
            }
        )
        if stop_hit and first_stop_touch is None and d > "2023-08-21":
            first_stop_touch = d
        if gap_down and first_gap_down is None and d > "2023-08-21":
            first_gap_down = d
        if target_hit and first_target is None and d > "2023-08-21":
            first_target = d
        if d == "2023-10-12":
            sheet_exit_bar = bars[-1]

    # Focus last 10 bars before eng exit
    focus = [b for b in bars if b["date"] >= "2023-10-01"]

    # Hypothesis: sheet exits at CLOSE when Low touches stop? or different stop?
    # 36.24 / 40.22 = ?
    ratio = 36.24 / 40.22
    # Is 36.24 a rounded close?
    # Check if sheet uses stop = zone_low * 0.89
    zone_low = 39.05  # sheet
    zone_low_eng = 39.06
    zl_stop = zone_low * 0.89
    zl_stop_eng = zone_low_eng * 0.89

    # Find any bar where close ~= 36.24
    close_eq = [b for b in bars if abs(b["C"] - 36.24) < 0.05]
    # Find first day Low <= eng_stop
    stop_days = [b for b in focus if b["stop_hit_eng_stop"] or b["stop_hit_entry_x089"]]

    return {
        "sheet": sheet,
        "engine": {
            "entry": "2023-08-21",
            "entry_px": float(row["ENTRY_PRICE"]),
            "exit": row["exit"],
            "exit_px": eng_exit,
            "exit_type": eng_exit_type,
            "stop": eng_stop,
            "target": eng_tgt,
            "zone": row.get("WPBR_ZONE_ID"),
            "pnl": row.get("PNL_PCT"),
        },
        "stop_calcs": {
            "entry_x_0.89": round(entry * 0.89, 4),
            "sheet_zone_low_39.05_x_0.89": round(zl_stop, 4),
            "eng_zone_low_39.06_x_0.89": round(zl_stop_eng, 4),
            "eng_STOP_PRICE": eng_stop,
            "sheet_exit_over_entry": round(ratio, 6),
            "sheet_exit_vs_entry089": round(36.24 - entry * 0.89, 4),
        },
        "first_stop_touch": first_stop_touch,
        "first_gap_down": first_gap_down,
        "first_target": first_target,
        "sheet_exit_bar": sheet_exit_bar,
        "focus_bars": focus,
        "stop_touch_focus": stop_days,
        "close_near_3624": close_eq,
        "ohlc_path": str(ohlc_path),
    }


def main():
    eng = load_engine_closed()
    bo = load_engine_bo()
    print("BO columns:", list(bo.columns)[:40] if not bo.empty else "empty")

    results = []
    all_mm = []
    for sym in MARKTEN:
        r = invent_for_symbol(sym, eng, bo)
        results.append(r)
        all_mm.extend(r["mismatches"])
        print(f"\n=== {sym} sheet={r['sheet_n']} eng={r['eng_n']} perfect={r['perfect_matches']} mm={len(r['mismatches'])} ===")
        for m in r["mismatches"]:
            print(f"  [{m['severity']}] {m['type']}: sheet={m['sheet']} | eng={m['engine']} | {m['cause']}")

    print("\n\n========== NFLX AUG EXIT WALK ==========")
    walk = walk_nflx_aug_exit()
    print(json.dumps({k: v for k, v in walk.items() if k != "focus_bars"}, indent=2, default=str))
    print("\nFOCUS BARS:")
    for b in walk.get("focus_bars", []):
        flags = []
        if b["gap_down_eng_stop"]:
            flags.append("GAP_DOWN")
        if b["stop_hit_eng_stop"]:
            flags.append("STOP_HIT")
        if b["target_hit"]:
            flags.append("TARGET")
        if b["stop_hit_entry_x089"]:
            flags.append("L<=entry*0.89")
        print(f"  {b['date']} O={b['O']} H={b['H']} L={b['L']} C={b['C']} {' '.join(flags)} L-stop={b['L_vs_eng_stop']}")

    out = {
        "per_symbol": [
            {
                "ticker": r["ticker"],
                "sheet_n": r["sheet_n"],
                "eng_n": r["eng_n"],
                "perfect_matches": r["perfect_matches"],
                "mismatch_count": len(r["mismatches"]),
                "mismatches": r["mismatches"],
            }
            for r in results
        ],
        "all_mismatches": all_mm,
        "nflx_aug_walk": walk,
    }
    out_path = REPO / "drive" / "wpbr_sheet_reconcile" / "_tmp_markten_mismatch_inv.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
