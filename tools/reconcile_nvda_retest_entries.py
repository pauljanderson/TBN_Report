#!/usr/bin/env python3
"""NVDA trade mismatches: map to engine retest rows on trigger day (COUNTIF BO)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.compare_nvda_sheet import load_sheet, next_td, norm_exit  # noqa: E402


def _parse_mdy(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    dt = pd.to_datetime(s, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


def _money(s) -> float:
    import re
    return float(re.sub(r"[^0-9.\-]", "", str(s)))


def _closed_path(run_id: str) -> Path:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_Closed_{run_id}.csv"
        if p.exists():
            return p
    return ROOT / "Drive" / f"YH_Closed_{run_id}.csv"


def load_engine_retest(run_id: str) -> pd.DataFrame:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_breakout_and_retest_{run_id}.csv"
        if p.exists():
            rt = pd.read_csv(p)
            break
    else:
        p = ROOT / "Drive" / f"YH_breakout_and_retest_{run_id}.csv"
        rt = pd.read_csv(p)
    rt = rt[rt["SYMBOL"].fillna("").astype(str).str.upper() == "NVDA"].copy()
    rt["bo_iso"] = rt["Breakout Date"].map(_parse_mdy)
    rt["rt_iso"] = rt["Retest Date"].map(_parse_mdy)
    rt["zl"] = rt["Zone Lower"].map(_money)
    rt["zu"] = rt["Zone Upper"].map(_money)
    return rt


def fmt_rows(df: pd.DataFrame, n: int = 5) -> str:
    if df.empty:
        return "  (none)"
    lines = []
    for _, r in df.head(n).iterrows():
        lines.append(
            f"  BO {r['Breakout Date']} MR{int(r['Main Row'])} "
            f"Z${r['zl']:.2f}-${r['zu']:.2f} scan={int(r['Scan Start Row'])} "
            f"rr={r['retest Row']} RT={r['Retest Date']}"
        )
    if len(df) > n:
        lines.append(f"  ... +{len(df) - n} more")
    return "\n".join(lines)


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260620101456"
    rt = load_engine_retest(run_id)

    eng = pd.read_csv(_closed_path(run_id))
    eng = eng[eng["SYMBOL"] == "NVDA"].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["purch_key"] = eng["open_d"].dt.strftime("%Y-%m-%d")
    eng["cad_key"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")

    meta = pd.read_csv(ROOT / "data" / "newdata" / "data" / "NVDA.csv", parse_dates=["Date"])
    iso = [d.strftime("%Y-%m-%d") for d in meta.sort_values("Date")["Date"]]

    sheet = load_sheet()
    sheet["purch_d"] = sheet["trigger_d"].map(lambda d: next_td(iso, d) if d in iso else "")

    matched_purch: set[str] = set()
    buckets: dict[str, list] = {"exact": [], "sheet_only": [], "eng_only": [], "exit_mismatch": []}

    print(f"Run {run_id}  engine retest rows={len(rt)}  unique RT dates={rt['rt_iso'].nunique()}")
    print("=" * 90)

    for _, s in sheet.iterrows():
        er = eng[eng["purch_key"] == s["purch_d"]]
        e = er.iloc[0] if len(er) else None
        trig = s["trigger_d"]
        rt_trig = rt[rt["rt_iso"] == trig]
        if e is not None:
            matched_purch.add(s["purch_d"])
            ep = abs(float(e.ENTRY_PRICE) - s["entry_px"])
            xp = abs(float(e.EXIT_PRICE) - s["exit_px"])
            ed = abs((pd.to_datetime(str(e.DATE_CLOSED), format="%Y%m%d") - pd.Timestamp(s["exit_d"])).days)
            if ep < 0.03 and xp < 0.08 and ed <= 2:
                buckets["exact"].append((s, e, rt_trig))
                continue
            buckets["exit_mismatch"].append((s, e, rt_trig))
        else:
            buckets["sheet_only"].append((s, None, rt_trig))

    for _, e in eng[~eng["purch_key"].isin(matched_purch)].iterrows():
        trig = e["cad_key"]
        rt_trig = rt[rt["rt_iso"] == trig] if trig else rt.iloc[0:0]
        buckets["eng_only"].append((None, e, rt_trig))

    print(f"exact={len(buckets['exact'])}  sheet_only={len(buckets['sheet_only'])}  "
          f"eng_only={len(buckets['eng_only'])}  exit_mismatch={len(buckets['exit_mismatch'])}")

    def show(title: str, items: list, limit: int = 12) -> None:
        if not items:
            return
        print(f"\n--- {title} ({len(items)}) ---")
        for item in items[:limit]:
            s, e, rt_trig = item
            if s is not None:
                print(
                    f"\nSheet trig {s['trigger_d']} -> purch {s['purch_d']} "
                    f"${s['entry_px']:.2f} exit {s['exit_d']} ${s['exit_px']:.2f}"
                )
            if e is not None:
                print(
                    f"Engine purch {e['purch_key']} ${float(e.ENTRY_PRICE):.2f} "
                    f"exit {str(e.DATE_CLOSED)} ${float(e.EXIT_PRICE):.2f} {e.EXIT_TYPE} "
                    f"CAD={e['cad_key']} BO={e.get('BREAKOUT_DATE','')}"
                )
            trig_iso = s["trigger_d"] if s is not None else str(e["cad_key"])
            print(f"Engine retest rows with RT={trig_iso} (COUNTIF on trigger D): {len(rt_trig)}")
            print(fmt_rows(rt_trig))

    show("EXIT MISMATCH (same entry, different exit)", buckets["exit_mismatch"], 5)
    show("SHEET ONLY (no engine purchase on trigger+1)", buckets["sheet_only"], 14)
    show("ENGINE ONLY (no sheet trade on purchase day)", buckets["eng_only"], 14)

    # Ledger parity quick stats
    print("\n" + "=" * 90)
    print("Ledger key parity (engine export vs itself sanity — use sheet TSV for full diff)")
    print(f"  NVDA breakout rows in engine export: {len(rt)}")
    print(f"  Rows with retest date populated: {rt['rt_iso'].notna().sum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
