#!/usr/bin/env python3
"""Compact BRT BO/retest parity summary (date+zone authoritative)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from compare_breakout_retest import _load_engine_csv, _engine_path, _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER, DEFAULT_SYMBOLS  # noqa: E402


def _summarize(sym: str, run_id: str, *, zd: int = 2, fuzz: float = 0.02) -> dict:
    lp = BRT_SHEET_BREAKOUT_LEDGER.get(sym)
    if lp is None or not lp.is_file():
        return {"sym": sym, "status": "no_ledger"}
    sh = _load_sheet_tsv(lp, sym)
    ep = _engine_path(run_id, brt=True)
    if not ep.is_file():
        return {"sym": sym, "status": "no_engine", "sheet_n": len(sh)}
    en = _load_engine_csv(ep, sym)
    pm = {(r.breakout_iso, round(r.zl, zd), round(r.zu, zd)): r for r in en}
    dz_m = dz_rt = fuzz_extra = fuzz_rt = 0
    sheet_only: list[str] = []
    rt_mismatch: list[str] = []
    for s in sh:
        k = (s.breakout_iso, round(s.zl, zd), round(s.zu, zd))
        e = pm.get(k)
        if e is not None:
            dz_m += 1
            if (s.retest_iso or "") == (e.retest_iso or ""):
                dz_rt += 1
            elif s.retest_iso or e.retest_iso:
                rt_mismatch.append(
                    f"{s.breakout_mdy} Z{s.zu:.2f} sheet={s.retest_iso or '-'} eng={e.retest_iso or '-'}"
                )
            continue
        e2 = next(
            (
                r
                for r in en
                if r.breakout_iso == s.breakout_iso
                and abs(r.zl - s.zl) <= fuzz
                and abs(r.zu - s.zu) <= fuzz
            ),
            None,
        )
        if e2 is not None:
            fuzz_extra += 1
            if (s.retest_iso or "") == (e2.retest_iso or ""):
                fuzz_rt += 1
            elif s.retest_iso or e2.retest_iso:
                rt_mismatch.append(
                    f"{s.breakout_mdy} Z{s.zu:.2f}~ sheet={s.retest_iso or '-'} eng={e2.retest_iso or '-'}"
                )
        else:
            sheet_only.append(f"{s.breakout_mdy} ${s.zl:.2f}/${s.zu:.2f}")
    eng_only = []
    matched_keys = {
        (s.breakout_iso, round(s.zl, zd), round(s.zu, zd))
        for s in sh
        if (s.breakout_iso, round(s.zl, zd), round(s.zu, zd)) in pm
    }
    for e in en:
        k = (e.breakout_iso, round(e.zl, zd), round(e.zu, zd))
        if k in pm and k in matched_keys:
            continue
        if k in matched_keys:
            continue
        if any(
            s.breakout_iso == e.breakout_iso
            and abs(s.zl - e.zl) <= fuzz
            and abs(s.zu - e.zu) <= fuzz
            for s in sh
        ):
            continue
        eng_only.append(f"{e.breakout_mdy} ${e.zl:.2f}/${e.zu:.2f}")
    return {
        "sym": sym,
        "status": "ok",
        "sheet_n": len(sh),
        "eng_n": len(en),
        "dz_match": dz_m,
        "dz_rt": dz_rt,
        "fuzz_extra": fuzz_extra,
        "fuzz_rt": fuzz_rt,
        "sheet_only": sheet_only,
        "eng_only": eng_only,
        "rt_mismatch": rt_mismatch,
    }


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260626133218"
    syms = [s.upper() for s in sys.argv[2:]] if len(sys.argv) > 2 else DEFAULT_SYMBOLS
    hdr = f"{'SYM':6} {'sheet':>5} {'eng':>5} {'dz':>8} {'rt@dz':>8} {'+fuzz':>6} {'rt tot':>8}"
    print(f"Run: {run_id}")
    print(hdr)
    print("-" * len(hdr))
    tot_s = tot_dz = tot_rt = 0
    for sym in syms:
        r = _summarize(sym, run_id)
        if r.get("status") != "ok":
            print(f"{sym:6} {r.get('status')}")
            continue
        sn = r["sheet_n"]
        dz = r["dz_match"]
        rt = r["dz_rt"] + r["fuzz_rt"]
        tot_s += sn
        tot_dz += dz + r["fuzz_extra"]
        tot_rt += rt
        print(
            f"{sym:6} {sn:5} {r['eng_n']:5} "
            f"{dz:3}/{sn:<4} {r['dz_rt']:3}/{dz:<4} "
            f"{r['fuzz_extra']:6} {rt:3}/{sn:<4}"
        )
        if r["sheet_only"][:3]:
            print(f"       sheet-only sample: {', '.join(r['sheet_only'][:3])}")
        if r["rt_mismatch"][:2]:
            print(f"       rt mismatch: {r['rt_mismatch'][0]}")
    print("-" * len(hdr))
    print(f"{'TOTAL':6} {tot_s:5}       {tot_dz:3}/{tot_s:<4}         {tot_rt:3}/{tot_s:<4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
