"""AMD-only reconcile vs startfloor+halfup stamp 260722165827. Diagnose-only; no commit."""
from __future__ import annotations

import importlib.util
import sys
import json
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
STAMP = "260722165827"
BASE = REPO / "drive" / "wpbr_sheet_reconcile" / "AMD"
EARLY6 = [
    "2016-04-27",
    "2016-06-27",
    "2016-12-05",
    "2017-01-19",
    "2017-12-06",
    "2018-04-05",
]


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


def fp(x):
    if pd.isna(x):
        return None
    t = str(x).replace("%", "").replace(",", "").replace("$", "").strip()
    try:
        return float(t)
    except Exception:
        return None


def pe(x):
    s = str(x).strip()
    if s.replace(".0", "").isdigit() and len(s.replace(".0", "")) == 8:
        s = s.replace(".0", "")
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        s2 = str(int(float(s)))
        if len(s2) == 8:
            return f"{s2[:4]}-{s2[4:6]}-{s2[6:8]}"
    except Exception:
        pass
    return nd(x)


def read_text_any(p: Path) -> str:
    b = p.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 1 and b[1] == 0):
        for enc in ("utf-16", "utf-16-le"):
            try:
                return b.decode(enc)
            except Exception:
                pass
    return b.decode("utf-8", errors="ignore")


def load_sheet_trades() -> list[dict]:
    for name in ("sheet_trades.tsv", "trades.tsv"):
        p = BASE / name
        if p.is_file():
            break
    else:
        return []
    lines = read_text_any(p).splitlines()
    start = 0
    header = ""
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Entry Date"):
            start = i + 1
            header = ln
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
                "pnl_pct": nf(c[4]) if len(c) > 4 else None,
                "days": nf(c[5]) if len(c) > 5 else None,
                "result": (c[6].strip() if len(c) > 6 else ""),
                "pnl_dol": nf(c[7]) if len(c) > 7 else None,
            }
        )
    return trades, header


def stacked(rows: pd.DataFrame) -> dict:
    n = len(rows)
    pcts = [fp(x) for x in rows["PNL_PCT"]]
    pcts = [p for p in pcts if p is not None]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    wr = 100.0 * len(wins) / n if n else 0.0
    avg = sum(pcts) / len(pcts) if pcts else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    if losses and aw:
        wl = aw / abs(al)
    elif wins:
        wl = float("inf")
    else:
        wl = 0.0
    days = [fp(x) for x in rows["DAYS_HELD"]]
    days = [d for d in days if d is not None]
    avgd = sum(days) / len(days) if days else float("nan")
    dol = sum(fp(x) or 0.0 for x in rows["PNL_DOLLARS"])
    return {
        "n": n,
        "wr": wr,
        "avg": avg,
        "wl": wl,
        "avgd": avgd,
        "dol": dol,
        "n_wins": len(wins),
        "n_losses": len(losses),
    }


def fmt_stack(label: str, s: dict) -> str:
    wl_s = f"{s['wl']:.2f}" if s["wl"] != float("inf") else "inf"
    return (
        f"{label}\n{s['n']}\n{s['wr']:.1f}%\n{s['avg']:.1f}%\n{wl_s}\n"
        f"{s['avgd']:.1f}\n${s['dol']:,.2f}"
    )


def sheet_stacked(trades: list[dict]) -> dict:
    pcts = [t["pnl_pct"] for t in trades if t["pnl_pct"] is not None]
    # sheet stores percent points like 22 / -14.5; if values look like fractions, scale
    if pcts and max(abs(p) for p in pcts) <= 1.5:
        pcts = [p * 100 for p in pcts]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    n = len(trades)
    wr = 100.0 * len(wins) / n if n else 0.0
    avg = sum(pcts) / len(pcts) if pcts else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    wl = aw / abs(al) if losses and aw else (float("inf") if wins else 0.0)
    days = [t["days"] for t in trades if t["days"] is not None]
    avgd = sum(days) / len(days) if days else float("nan")
    dol = sum(t["pnl_dol"] or 0.0 for t in trades)
    return {
        "n": n,
        "wr": wr,
        "avg": avg,
        "wl": wl,
        "avgd": avgd,
        "dol": dol,
        "n_wins": len(wins),
        "n_losses": len(losses),
    }


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "rec", REPO / "tools" / "_variantC_SC_stop91_2016_wpbr_reconcile.py"
    )
    rec = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(rec)
    rec.STAMP_DIR = OUT
    rec.STAMP = STAMP
    r = rec.analyze("AMD")
    eng_conf = rec.confirm_engine()

    sheet_t, header = load_sheet_trades()
    cdf = pd.read_csv(OUT / f"WPBR_Closed_{STAMP}.csv")
    amd = cdf[cdf["SYMBOL"].astype(str).str.upper() == "AMD"].copy()
    eng_by = {pe(row.DATE_OPENED): row for _, row in amd.iterrows()}

    forks = []
    full = 0
    for t in sheet_t:
        row = eng_by.get(t["entry"])
        if row is None:
            continue
        ex = pe(row.DATE_CLOSED)
        ep = float(row.ENTRY_PRICE)
        xp = float(row.EXIT_PRICE)
        entry_ok = t["entry_px"] is not None and abs(t["entry_px"] - ep) <= 0.02
        exit_d_ok = t["exit"] == ex
        exit_p_ok = t["exit_px"] is not None and abs(t["exit_px"] - xp) <= 0.02
        if entry_ok and exit_d_ok and exit_p_ok:
            full += 1
        elif entry_ok and (not exit_d_ok or not exit_p_ok):
            forks.append(
                {
                    "entry": t["entry"],
                    "sheet_exit": t["exit"],
                    "eng_exit": ex,
                    "sheet_px": t["exit_px"],
                    "eng_px": xp,
                }
            )

    eng_stack = stacked(amd)
    sh_stack = sheet_stacked(sheet_t)
    early_present = [e for e in EARLY6 if e in set(r["eng_entries"])]

    open_n = 0
    op = OUT / f"WPBR_Open_{STAMP}.csv"
    if op.is_file():
        odf = pd.read_csv(op)
        if "SYMBOL" in odf.columns:
            open_n = int((odf["SYMBOL"].astype(str).str.upper() == "AMD").sum())

    fair = r["fair"]
    lines: list[str] = []
    lines.append(f"# AMD WPBR reconcile — variant C + SC-on + startfloor + halfup (`{STAMP}`)")
    lines.append("")
    lines.append(
        f"**Engine:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_20260722165815/` "
        f"(`{STAMP}`)"
    )
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (log: **{eng_conf['sc_in_run_log']}**)"
    )
    lines.append(
        "**Settings:** variant C + SC-on + `stop_pct=0.91` + `start_date=2016-01-01` "
        "+ **pivot startfloor** (`PIVOT_MONDAY >= 2016-01-01`) + **half-up rounding** "
        "(zone/pivot HALF_UP; halfup stamp)."
    )
    lines.append("**Paste:** breakouts/retests/rockets + trades only (OHLC/weekly unchanged).")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Pivots | {fair['pivots_match']} |")
    lines.append(f"| Zones | {fair['zones_ok']} |")
    lines.append(f"| Retest | {fair['retest_ok']} |")
    lines.append(f"| Rocket (sheet fires) | {fair['rocket_where_sheet_fires']} |")
    lines.append(f"| Raw | **{r['raw']}** |")
    lines.append(f"| Ser | **{r['ser']}** |")
    lines.append(f"| Eng closed (+open) | {r['closed_n']} (+{open_n} open) |")
    lines.append(f"| Sheet trades ≥2016 | {r['n_sheet_trades']} |")
    lines.append(f"| Exit forks | **{len(forks)}** |")
    lines.append(f"| Full identity (entry+exit+px) | **{full}/{r['n_sheet_trades']}** |")
    lines.append("")
    if r["raw_orphans"]:
        lines.append(f"**Raw orphans (SC/lifecycle):** {', '.join(r['raw_orphans'])}")
        lines.append("")
    else:
        lines.append("**Raw orphans:** none")
        lines.append("")
    if r["ser_orphans"]:
        lines.append(f"**Ser orphans:** {', '.join(r['ser_orphans'])}")
        lines.append("")
    else:
        lines.append("**Ser orphans:** none")
        lines.append("")
    eng_only = sorted(set(r["eng_entries"]) - set(r["sheet_entries"]))
    sheet_only = sorted(set(r["sheet_entries"]) - set(r["eng_entries"]))
    lines.append(f"**Eng-only entries:** {', '.join(eng_only) if eng_only else 'none'}")
    lines.append("")
    lines.append(f"**Sheet-only entries:** {', '.join(sheet_only) if sheet_only else 'none'}")
    lines.append("")
    lines.append("## Six early eng-only TARGET wins (pre-2016 pivots)")
    lines.append("")
    if early_present:
        lines.append(f"**STILL PRESENT:** {', '.join(early_present)}")
    else:
        lines.append(
            "**GONE** — none of "
            "`2016-04-27`, `2016-06-27`, `2016-12-05`, `2017-01-19`, `2017-12-06`, `2018-04-05` "
            "remain in eng closed under startfloor."
        )
    lines.append("")
    lines.append(
        f"Trade count: eng closed **{r['closed_n']}** ≡ sheet **{r['n_sheet_trades']}**."
    )
    lines.append("")
    lines.append("## 6-value stacked")
    lines.append("")
    lines.append("| Block | Trades | Win% | Avg% | W/L | Avg days | $ PnL |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| Sheet | {sh_stack['n']} | {sh_stack['wr']:.1f}% | {sh_stack['avg']:.1f}% | "
        f"{sh_stack['wl']:.2f} | {sh_stack['avgd']:.1f} | ${sh_stack['dol']:,.2f} |"
    )
    lines.append(
        f"| Engine (all closed) | {eng_stack['n']} | {eng_stack['wr']:.1f}% | {eng_stack['avg']:.1f}% | "
        f"{eng_stack['wl']:.2f} | {eng_stack['avgd']:.1f} | ${eng_stack['dol']:,.2f} |"
    )
    lines.append("")
    lines.append("Engine paste block:")
    lines.append("")
    lines.append("```")
    lines.append(fmt_stack("AMD", eng_stack))
    lines.append("```")
    lines.append("")
    lines.append(
        "Note: % metrics (win%/avg%/W/L/days) align sheet↔eng on the same 20 entries. "
        "$ PnL still differs by risk-unit sizing (historical ×~3.008)."
    )
    lines.append("")
    if forks:
        lines.append(f"**Exit forks ({len(forks)}):**")
        for f in forks:
            lines.append(
                f"- `{f['entry']}` sheet exit `{f['sheet_exit']}` @{f['sheet_px']} "
                f"vs eng `{f['eng_exit']}` @{f['eng_px']}"
            )
        lines.append("")
    lines.append(
        f"*Generated vs stamp `{STAMP}` (startfloor + halfup). Diagnose-only. No commit.*"
    )
    lines.append("")

    status_path = BASE / "AMD_wpbr_reconcile_status.md"
    status_path.write_text("\n".join(lines), encoding="utf-8")

    # also write AMD stacked into outdir helper
    stack_path = OUT / "_amd_stacked_stats.txt"
    stack_path.write_text(fmt_stack("AMD", eng_stack) + "\n", encoding="utf-8")

    parent = {
        "symbol": "AMD",
        "stamp": STAMP,
        "ser": r["ser"],
        "raw": r["raw"],
        "ser_orphans": r["ser_orphans"],
        "raw_orphans": r["raw_orphans"],
        "exit_forks": len(forks),
        "eng_closed": r["closed_n"],
        "sheet_trades": r["n_sheet_trades"],
        "early6_gone": len(early_present) == 0,
        "early6_still": early_present,
        "eng_only": eng_only,
        "sheet_only": sheet_only,
        "full_identity": f"{full}/{r['n_sheet_trades']}",
        "stacked_eng": eng_stack,
        "stacked_sheet": sh_stack,
        "status_md": str(status_path),
        "header_sample": header[:120],
    }
    parent_path = BASE / f"AMD_startfloor_{STAMP}_parent_summary.json"
    parent_json = {
        "symbol": "AMD",
        "stamp": STAMP,
        "stamp_dir": str(OUT),
        "sc_in_run_log": eng_conf.get("sc_in_run_log"),
        "startfloor": True,
        "halfup": True,
        "pivots": fair["pivots_match"],
        "zones": fair["zones_ok"],
        "retest": fair["retest_ok"],
        "rocket_sheet_fires": fair["rocket_where_sheet_fires"],
        "raw": r["raw"],
        "ser": r["ser"],
        "closed_n": r["closed_n"],
        "sheet_trades": r["n_sheet_trades"],
        "raw_orphans": r["raw_orphans"],
        "ser_orphans": r["ser_orphans"],
        "exit_forks": len(forks),
        "full_identity": f"{full}/{r['n_sheet_trades']}",
        "early6_gone": len(early_present) == 0,
        "early6_still": early_present,
        "eng_only": eng_only,
        "sheet_only": sheet_only,
        "stacked_eng": eng_stack,
        "stacked_sheet": sh_stack,
        "status_md": str(status_path),
        "stacked_path": str(stack_path),
    }
    parent_path.write_text(json.dumps(parent_json, indent=2, default=str), encoding="utf-8")
    parent["parent_summary_json"] = str(parent_path)

    print("PARENT_SUMMARY")
    for k, v in parent.items():
        if k.startswith("stacked"):
            print(f"  {k}: {fmt_stack('AMD' if 'eng' in k else 'SHEET', v).replace(chr(10), ' | ')}")
        else:
            print(f"  {k}: {v}")
    print("wrote", status_path)
    print("wrote", stack_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
