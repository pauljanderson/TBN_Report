#!/usr/bin/env python3
"""Full MarkTen SC mismatch inventory (identity-grade). Writes JSON + prints summary."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))

STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_SC_2016_20260722145207"
STAMP = "260722145252"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
MIN_DATE = "2016-01-01"


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


def eng_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s.replace(".", "", 1).isdigit():
        s = str(int(float(s)))
    s = s.replace("-", "").replace("/", "")
    if len(s) >= 8 and s[:8].isdigit():
        s = s[:8]
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return nd(v)


def load_sheet_trades(sym_dir: Path) -> list[dict]:
    for name in ("trades.tsv", "sheet_trades.tsv", "sheet_trades.csv"):
        p = sym_dir / name
        if p.is_file():
            break
    else:
        return []
    trades = []
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p)
        for _, r in df.iterrows():
            entry = nd(r.get("Entry Date") or r.get("Trigger Date"))
            if not entry or entry < MIN_DATE:
                continue
            trades.append(
                {
                    "entry": entry,
                    "entry_px": nf(r.get("Entry Price")),
                    "exit": nd(r.get("Exit Date")),
                    "exit_px": nf(r.get("Exit Price")),
                    "result": str(r.get("Result") or "").strip().upper() or None,
                    "pnl_pct": nf(r.get("Profit %")),
                }
            )
        return trades
    lines = read_text_any(p).splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if "Entry Date" in ln or "Trigger Date" in ln:
            start = i + 1
            break
    for line in lines[start:]:
        if not line.strip():
            continue
        c = line.split("\t") + [""] * 10
        entry = nd(c[0])
        if not entry or entry < MIN_DATE:
            continue
        trades.append(
            {
                "entry": entry,
                "entry_px": nf(c[1]),
                "exit": nd(c[2]),
                "exit_px": nf(c[3]),
                "result": str(c[6]).strip().upper() or None,
                "pnl_pct": nf(c[4]),
            }
        )
    return trades


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
        if not piv or piv < MIN_DATE:
            continue
        rows.append(
            {
                "pivot": piv,
                "retest": nd(c[16]),
                "rocket": nd(c[18]),
                "zlow": nf(c[6]),
                "zhigh": nf(c[7]),
            }
        )
    return rows


def load_engine():
    closed = pd.read_csv(STAMP_DIR / f"WPBR_Closed_{STAMP}.csv")
    closed["entry"] = closed["DATE_OPENED"].map(eng_date)
    closed["exit"] = closed["DATE_CLOSED"].map(eng_date)
    open_p = STAMP_DIR / f"WPBR_Open_{STAMP}.csv"
    opens = []
    if open_p.is_file():
        odf = pd.read_csv(open_p)
        if len(odf) and "SYMBOL" in odf.columns:
            odf["entry"] = odf["DATE_OPENED"].map(eng_date)
            odf["exit"] = None
            opens.append(odf)
    return closed, opens[0] if opens else pd.DataFrame()


def px_eq(a, b, tol=0.03):
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def session_neighbors(d: str, n: int = 5) -> list[str]:
    """Calendar offsets that often equal +/-1 trading session."""
    out = []
    t = pd.Timestamp(d)
    for delta in range(-n, n + 1):
        if delta == 0:
            continue
        out.append((t + pd.Timedelta(days=delta)).strftime("%Y-%m-%d"))
    return out


def suspect_cause(mtype: str, sheet_t: dict | None, eng_r: dict | None) -> str:
    if mtype == "entry_date_off_by_session":
        return "fill lag from prior-trade exit fork (occupancy)"
    if mtype == "exit_date_mismatch" and sheet_t and eng_r:
        sx, ex = sheet_t.get("exit"), eng_r.get("exit")
        sxp, exp = sheet_t.get("exit_px"), float(eng_r.get("EXIT_PRICE") or 0)
        stop = float(eng_r.get("STOP_PRICE") or 0)
        et = str(eng_r.get("EXIT_TYPE") or "")
        if sx and ex and sx < ex and "STOP" in et.upper():
            if sxp and stop and sxp > stop + 0.05:
                return "sheet exits earlier at higher price than eng trigger_low*0.89 stop (NFLX-class exit fork)"
            return "sheet exits earlier than eng STOP day"
        if sx and ex and sx > ex:
            return "engine exits earlier than sheet"
        if "GAP" in et.upper():
            return "gap vs intraday stop/close rule fork"
        return "exit date fork"
    if mtype == "exit_price_mismatch":
        return "exit price cents / stop vs close / gap open"
    if mtype == "sheet_only_trade":
        return "sheet-only (SC timing / occupancy / no eng fill)"
    if mtype == "engine_only_trade":
        return "engine-only (eng rocket without sheet trade, or paste window)"
    if mtype == "entry_price_mismatch":
        return "entry open rounding / OHLC source"
    return mtype


def invent(sym: str, closed: pd.DataFrame, opens: pd.DataFrame) -> dict:
    sheet = load_sheet_trades(BASE / sym)
    zones = load_sheet_zones(BASE / sym)
    e_sym = closed[closed["SYMBOL"].astype(str).str.upper() == sym].copy()
    if not opens.empty and "SYMBOL" in opens.columns:
        o_sym = opens[opens["SYMBOL"].astype(str).str.upper() == sym]
    else:
        o_sym = pd.DataFrame()

    e_by = {}
    for _, r in e_sym.iterrows():
        if r["entry"]:
            e_by[r["entry"]] = r.to_dict()
    for _, r in o_sym.iterrows():
        if r.get("entry") and r["entry"] not in e_by:
            d = r.to_dict()
            d["EXIT_PRICE"] = None
            d["EXIT_TYPE"] = "OPEN"
            d["exit"] = None
            e_by[r["entry"]] = d

    s_by = {t["entry"]: t for t in sheet}
    sheet_entries = set(s_by)
    eng_entries = set(e_by)

    # Pair off-by-session first
    paired_sheet = set()
    paired_eng = set()
    mismatches = []
    near_pairs = []

    for d in sorted(sheet_entries - eng_entries):
        for cand in session_neighbors(d, 4):
            if cand in eng_entries - sheet_entries and cand not in paired_eng:
                near_pairs.append((d, cand))
                paired_sheet.add(d)
                paired_eng.add(cand)
                break

    for sd, ed in near_pairs:
        st, er = s_by[sd], e_by[ed]
        mismatches.append(
            {
                "ticker": sym,
                "type": "entry_date_off_by_session",
                "sheet": f"{st['entry']} @{st['entry_px']} -> {st['exit']} @{st['exit_px']} {st.get('result')}",
                "engine": f"{er['entry']} @{float(er['ENTRY_PRICE']):.2f} -> {er.get('exit')} @{er.get('EXIT_PRICE')} {er.get('EXIT_TYPE')}",
                "cause": suspect_cause("entry_date_off_by_session", st, er),
                "severity": "blocks_identity",
            }
        )
        # also note exit fork inside the pair
        if st.get("exit") and er.get("exit") and st["exit"] != er["exit"]:
            mismatches.append(
                {
                    "ticker": sym,
                    "type": "exit_date_mismatch_on_near_pair",
                    "sheet": f"exit {st['exit']} @{st['exit_px']}",
                    "engine": f"exit {er['exit']} @{er.get('EXIT_PRICE')} {er.get('EXIT_TYPE')}",
                    "cause": "paired entry off-by-session; exits also differ",
                    "severity": "blocks_identity",
                }
            )

    for d in sorted(sheet_entries - eng_entries - paired_sheet):
        st = s_by[d]
        mismatches.append(
            {
                "ticker": sym,
                "type": "sheet_only_trade",
                "sheet": f"{st['entry']} @{st['entry_px']} -> {st['exit']} @{st['exit_px']} {st.get('result')}",
                "engine": "-",
                "cause": suspect_cause("sheet_only_trade", st, None),
                "severity": "blocks_identity",
            }
        )

    for d in sorted(eng_entries - sheet_entries - paired_eng):
        er = e_by[d]
        ep = er.get("ENTRY_PRICE")
        xp = er.get("EXIT_PRICE")
        mismatches.append(
            {
                "ticker": sym,
                "type": "engine_only_trade",
                "sheet": "-",
                "engine": f"{er['entry']} @{float(ep):.2f} -> {er.get('exit')} @{xp} {er.get('EXIT_TYPE')}",
                "cause": suspect_cause("engine_only_trade", None, er),
                "severity": "blocks_identity",
            }
        )

    perfect = 0
    matched = sorted(sheet_entries & eng_entries)
    for d in matched:
        st, er = s_by[d], e_by[d]
        issues = []
        if not px_eq(st["entry_px"], er["ENTRY_PRICE"]):
            issues.append(
                (
                    "entry_price_mismatch",
                    f"{st['entry']} @{st['entry_px']}",
                    f"{er['entry']} @{float(er['ENTRY_PRICE']):.2f}",
                    "cosmetic" if st["entry_px"] is not None and abs(st["entry_px"] - float(er["ENTRY_PRICE"])) < 0.05 else "blocks_identity",
                )
            )
        if st.get("exit") and er.get("exit") and st["exit"] != er["exit"]:
            issues.append(
                (
                    "exit_date_mismatch",
                    f"{st['exit']} @{st['exit_px']} {st.get('result')}",
                    f"{er['exit']} @{er.get('EXIT_PRICE')} {er.get('EXIT_TYPE')} stop={er.get('STOP_PRICE')}",
                    "blocks_identity",
                )
            )
        elif st.get("exit_px") is not None and er.get("EXIT_PRICE") is not None:
            if not px_eq(st["exit_px"], er["EXIT_PRICE"]):
                dlt = abs(float(st["exit_px"]) - float(er["EXIT_PRICE"]))
                issues.append(
                    (
                        "exit_price_mismatch",
                        f"{st['exit']} @{st['exit_px']}",
                        f"{er['exit']} @{float(er['EXIT_PRICE']):.2f} {er.get('EXIT_TYPE')}",
                        "cosmetic" if dlt < 0.05 else "blocks_identity",
                    )
                )
        if not issues:
            perfect += 1
        for typ, sh, en, sev in issues:
            mismatches.append(
                {
                    "ticker": sym,
                    "type": typ,
                    "sheet": sh,
                    "engine": en,
                    "cause": suspect_cause(typ, st, er),
                    "severity": sev,
                }
            )

    # Zone rocket date diffs (structure should already be 1:1 per status; flag if any)
    rocket_diffs = []
    # status claims perfect structure; skip heavy recompute unless needed

    return {
        "ticker": sym,
        "sheet_n": len(sheet),
        "eng_n": len(e_by),
        "perfect": perfect,
        "matched": len(matched),
        "mismatches": mismatches,
        "sheet_entries": sorted(sheet_entries),
        "eng_entries": sorted(eng_entries),
        "zones_n": len(zones),
        "rockets_sheet": sum(1 for z in zones if z.get("rocket")),
    }


def analyze_loss_exit_pattern(closed: pd.DataFrame) -> list[dict]:
    """For matched sheet/eng LOSS-ish trades, classify sheet-early vs eng-early."""
    rows = []
    for sym in MARKTEN:
        sheet = {t["entry"]: t for t in load_sheet_trades(BASE / sym)}
        e_sym = closed[closed["SYMBOL"].astype(str).str.upper() == sym]
        for _, er in e_sym.iterrows():
            d = er["entry"]
            if d not in sheet:
                continue
            st = sheet[d]
            if not st.get("exit") or not er.get("exit"):
                continue
            if st["exit"] == er["exit"]:
                continue
            et = str(er.get("EXIT_TYPE") or "")
            rows.append(
                {
                    "ticker": sym,
                    "entry": d,
                    "sheet_exit": st["exit"],
                    "sheet_exit_px": st["exit_px"],
                    "eng_exit": er["exit"],
                    "eng_exit_px": float(er["EXIT_PRICE"]) if er.get("EXIT_PRICE") is not None else None,
                    "eng_stop": float(er["STOP_PRICE"]) if er.get("STOP_PRICE") is not None else None,
                    "eng_type": et,
                    "sheet_earlier": st["exit"] < er["exit"],
                    "sheet_px_above_stop": (
                        st["exit_px"] is not None
                        and er.get("STOP_PRICE") is not None
                        and float(st["exit_px"]) > float(er["STOP_PRICE"]) + 0.05
                    ),
                }
            )
    return rows


def main():
    closed, opens = load_engine()
    results = []
    all_mm = []
    for sym in MARKTEN:
        r = invent(sym, closed, opens)
        results.append(r)
        all_mm.extend(r["mismatches"])

    loss_forks = analyze_loss_exit_pattern(closed)

    # Root cause clusters
    cause_counts = Counter(m["cause"] for m in all_mm)
    type_counts = Counter(m["type"] for m in all_mm)
    sev_counts = Counter(m["severity"] for m in all_mm)

    # NFLX focus
    nflx_mm = [m for m in all_mm if m["ticker"] == "NFLX"]

    out = {
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "per_symbol": [
            {
                "ticker": r["ticker"],
                "sheet_n": r["sheet_n"],
                "eng_n": r["eng_n"],
                "perfect": r["perfect"],
                "matched": r["matched"],
                "mismatch_n": len(r["mismatches"]),
                "mismatches": r["mismatches"],
            }
            for r in results
        ],
        "all_mismatches": all_mm,
        "type_counts": dict(type_counts),
        "cause_counts": dict(cause_counts),
        "severity_counts": dict(sev_counts),
        "loss_exit_forks": loss_forks,
        "nflx_mismatches": nflx_mm,
    }
    outp = BASE / "_tmp_markten_mismatch_inv.json"
    outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    print(f"Wrote {outp}")
    print("TYPE COUNTS", dict(type_counts))
    print("CAUSE COUNTS", dict(cause_counts))
    print("SEV", dict(sev_counts))
    print(f"\nLoss/exit date forks: {len(loss_forks)}")
    sheet_early = [x for x in loss_forks if x["sheet_earlier"]]
    eng_early = [x for x in loss_forks if not x["sheet_earlier"]]
    print(f"  sheet earlier: {len(sheet_early)}; eng earlier: {len(eng_early)}")
    print(f"  sheet_px_above_eng_stop: {sum(1 for x in sheet_early if x['sheet_px_above_stop'])}")
    for x in loss_forks:
        print(
            f"  {x['ticker']} {x['entry']}: sheet {x['sheet_exit']}@{x['sheet_exit_px']} vs eng {x['eng_exit']}@{x['eng_exit_px']} {x['eng_type']} stop={x['eng_stop']} sheet_earlier={x['sheet_earlier']} px>stop={x['sheet_px_above_stop']}"
        )

    print("\n=== PER SYMBOL ===")
    for r in results:
        print(f"\n{r['ticker']}: sheet={r['sheet_n']} eng={r['eng_n']} perfect={r['perfect']} mm={len(r['mismatches'])}")
        for m in r["mismatches"]:
            print(f"  [{m['severity']}] {m['type']}: S={m['sheet']} | E={m['engine']} | {m['cause']}")


if __name__ == "__main__":
    main()
