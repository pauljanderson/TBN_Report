"""TSLA stop91 sheet vs engine trade diff (stamp 260722151857)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
STAMP = "260722151857"
OUTDIR = ROOT / "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_2016_20260722151842"
SHEET = ROOT / "drive/wpbr_sheet_reconcile/TSLA/sheet_trades.tsv"
ENG = OUTDIR / f"WPBR_Closed_{STAMP}.csv"
OPENP = OUTDIR / f"WPBR_Open_{STAMP}.csv"
ZONES = ROOT / "drive/wpbr_sheet_reconcile/TSLA/sheet_zones.tsv"


def pd(s):
    s = str(s or "").strip()
    if not s:
        return None
    for f in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def pm(s):
    s = str(s or "").strip().replace("$", "").replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def load_sheet():
    st = []
    with SHEET.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            ed = pd(row.get("Entry Date"))
            if not ed or ed.year < 2016:
                continue
            st.append(
                dict(
                    entry=ed,
                    entry_px=pm(row.get("Entry Price")),
                    exit=pd(row.get("Exit Date")),
                    exit_px=pm(row.get("Exit Price")),
                    pnl_pct=pm(row.get("Profit %")),
                    days=pm(row.get("Days In Trade")),
                    result=(row.get("Result") or "").strip(),
                    pnl_dol=pm(row.get("Profit per trade")),
                )
            )
    return st


def load_eng():
    et = []
    for path, is_open in ((ENG, False), (OPENP, True)):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("SYMBOL") or "").upper() != "TSLA":
                    continue
                ed = pd(row.get("DATE_OPENED"))
                if not ed or ed.year < 2016:
                    continue
                et.append(
                    dict(
                        entry=ed,
                        entry_px=pm(row.get("ENTRY_PRICE")),
                        exit=pd(row.get("DATE_CLOSED")),
                        exit_px=pm(row.get("EXIT_PRICE")),
                        pnl_pct=pm(row.get("PNL_PCT")),
                        days=pm(row.get("DAYS_HELD")),
                        exit_type=(row.get("EXIT_TYPE") or "").strip(),
                        pnl_dol=pm(row.get("PNL_DOLLARS")),
                        open=is_open,
                        ca=pd(row.get("CLOSE_ABOVE_DATE")),
                        stop=pm(row.get("STOP_PRICE")),
                        target=pm(row.get("TARGET_PRICE")),
                    )
                )
    return et


def six(trades, use_result=True):
    n = len(trades)
    if n == 0:
        return None
    if use_result:
        wins = [
            t
            for t in trades
            if (t.get("result") or "").upper() == "WIN"
            or (
                (t.get("result") or "").upper() != "LOSS"
                and (t.get("pnl_pct") or 0) > 0
            )
        ]
    else:
        wins = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
    losses = [t for t in trades if t not in wins]
    winpct = 100 * len(wins) / n
    avg = sum(t["pnl_pct"] or 0 for t in trades) / n
    aw = sum(t["pnl_pct"] or 0 for t in wins) / len(wins) if wins else 0.0
    al = abs(sum(t["pnl_pct"] or 0 for t in losses) / len(losses)) if losses else 0.0
    wl = aw / al if al else None
    ad = sum(t["days"] or 0 for t in trades) / n
    dol = sum(t["pnl_dol"] or 0 for t in trades)
    return n, winpct, avg, wl, ad, dol


def main():
    st = load_sheet()
    et = load_eng()
    sm = {t["entry"]: t for t in st}
    em = {t["entry"]: t for t in et}
    s_only = sorted(set(sm) - set(em))
    e_only = sorted(set(em) - set(sm))
    both = sorted(set(sm) & set(em))

    print(f"SHEET {len(st)} ENG {len(et)} OPEN {sum(1 for t in et if t['open'])}")
    print("SHEET_ONLY", [d.isoformat() for d in s_only])
    print("ENG_ONLY", [d.isoformat() for d in e_only])
    print("MATCHED", len(both))

    mism = []
    soft = []
    for d in both:
        a, b = sm[d], em[d]
        hard = []
        soft_i = []
        if a["exit"] != b["exit"]:
            hard.append(f"exit_date sheet={a['exit']} eng={b['exit']}")
        if a["entry_px"] is not None and b["entry_px"] is not None:
            if abs(a["entry_px"] - b["entry_px"]) > 0.06:
                hard.append(f"entry_px sheet={a['entry_px']} eng={b['entry_px']}")
            elif abs(a["entry_px"] - b["entry_px"]) > 0.005:
                soft_i.append(f"entry_px¢ sheet={a['entry_px']} eng={b['entry_px']}")
        if a["exit_px"] is not None and b["exit_px"] is not None:
            if abs(a["exit_px"] - b["exit_px"]) > 0.06:
                hard.append(f"exit_px sheet={a['exit_px']} eng={b['exit_px']}")
            elif abs(a["exit_px"] - b["exit_px"]) > 0.005:
                soft_i.append(f"exit_px¢ sheet={a['exit_px']} eng={b['exit_px']}")
        if a["pnl_pct"] is not None and b["pnl_pct"] is not None:
            if abs(a["pnl_pct"] - b["pnl_pct"]) > 0.15:
                hard.append(f"pnl_pct sheet={a['pnl_pct']} eng={b['pnl_pct']}")
            elif abs(a["pnl_pct"] - b["pnl_pct"]) > 0.02:
                soft_i.append(f"pnl_pct soft sheet={a['pnl_pct']} eng={b['pnl_pct']}")
        if a["days"] is not None and b["days"] is not None and abs(a["days"] - b["days"]) >= 1:
            soft_i.append(f"days sheet={a['days']} eng={b['days']}")
        if a["pnl_dol"] is not None and b["pnl_dol"] is not None:
            ratio = b["pnl_dol"] / a["pnl_dol"] if a["pnl_dol"] else None
            soft_i.append(f"$ ratio eng/sheet={ratio:.4f}" if ratio else "$ ratio n/a")
        if hard:
            mism.append((d, hard, soft_i, a, b))
        elif soft_i:
            soft.append((d, soft_i, a, b))

    print("HARD_MISMATCHES", len(mism))
    for d, hard, soft_i, a, b in mism:
        print(
            d,
            "|",
            "; ".join(hard),
            "|",
            "; ".join(soft_i),
            "|",
            b.get("exit_type"),
            "stop",
            b.get("stop"),
            "target",
            b.get("target"),
        )
    print("SOFT_ONLY", len(soft))
    for d, soft_i, a, b in soft:
        print(d, "|", "; ".join(soft_i), "|", b.get("exit_type"))

    print("--- SHEET_ONLY detail ---")
    for d in s_only:
        t = sm[d]
        print(t)

    print("--- ENG_ONLY detail ---")
    for d in e_only:
        t = em[d]
        print(t)

    print("--- ALL SHEET ---")
    for t in st:
        print(
            t["entry"],
            t["entry_px"],
            "->",
            t["exit"],
            t["exit_px"],
            t["result"],
            t["pnl_pct"],
            t["days"],
            t["pnl_dol"],
        )
    print("--- ALL ENG ---")
    for t in et:
        print(
            t["entry"],
            t["entry_px"],
            "->",
            t["exit"],
            t["exit_px"],
            t["exit_type"],
            t["pnl_pct"],
            t["days"],
            t["pnl_dol"],
            "OPEN" if t["open"] else "",
        )

    matched_eng = [em[d] for d in both]
    matched_sheet = [sm[d] for d in both]
    # attach result from sheet onto matched eng for fair 6val
    for s, e in zip(matched_sheet, matched_eng):
        e = dict(e)
        e["result"] = "WIN" if (e["pnl_pct"] or 0) > 0 else "LOSS"

    print("--- SHEET 6VAL ---")
    print(six(st, True))
    print("--- ENG ALL 6VAL ---")
    closed = [t for t in et if not t["open"]]
    print(six(closed, False))
    print("--- ENG MATCHED-TO-SHEET 6VAL ---")
    me = []
    for d in both:
        e = dict(em[d])
        e["result"] = "WIN" if (e["pnl_pct"] or 0) > 0 else "LOSS"
        me.append(e)
    print(six(me, True))
    print("--- SHEET MATCHED 6VAL ---")
    print(six(matched_sheet, True))

    # dollar ratios on matched
    ratios = []
    for d in both:
        a, b = sm[d], em[d]
        if a["pnl_dol"] and b["pnl_dol"]:
            ratios.append(b["pnl_dol"] / a["pnl_dol"])
    if ratios:
        print("DOLLAR RATIOS", [round(r, 4) for r in ratios])
        print("MEAN RATIO", round(sum(ratios) / len(ratios), 4))

    # zone rocket blanks near eng-only
    if ZONES.exists():
        print("--- ZONES near eng-only ---")
        with ZONES.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        print("zone cols", rows[0].keys() if rows else None)
        for d in e_only:
            print("ENG_ONLY", d)
            for r in rows:
                # try common date cols
                for k, v in r.items():
                    dv = pd(v)
                    if dv and abs((dv - d).days) <= 10:
                        print(" ", {kk: r[kk] for kk in list(r)[:12]})
                        break


if __name__ == "__main__":
    main()
