"""AAPL-only reconcile vs HALF_UP retest + startfloor stamp 260722165827. Do not commit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "tools"))
import _variantC_SC_stop91_2016_wpbr_reconcile as R

R.STAMP_DIR = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
)
R.STAMP = "260722165827"

SYM = "AAPL"
ENG_DIR = (
    "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_20260722165815/"
)


def fp(x):
    if pd.isna(x):
        return None
    t = str(x).replace("%", "").replace(",", "").replace("$", "").strip()
    try:
        return float(t)
    except Exception:
        return None


def stacked_closed() -> dict:
    p = R.STAMP_DIR / f"WPBR_Closed_{R.STAMP}.csv"
    df = pd.read_csv(p)
    s = df[df["SYMBOL"].astype(str).str.upper() == SYM].copy()
    n = len(s)
    pcts = [fp(x) for x in s["PNL_PCT"]]
    pcts = [v for v in pcts if v is not None]
    wins = [v for v in pcts if v > 0]
    losses = [v for v in pcts if v < 0]
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
    days = [fp(x) for x in s["DAYS_HELD"]]
    days = [v for v in days if v is not None]
    avgd = sum(days) / len(days) if days else float("nan")
    dol = 0.0
    for x in s["PNL_DOLLARS"]:
        v = fp(x)
        if v is not None:
            dol += v
    return {
        "n": n,
        "win_pct": wr,
        "avg_profit_pct": avg,
        "wl_ratio": wl,
        "avg_days": avgd,
        "pnl_dollars": dol,
    }


def exit_forks(r: dict) -> tuple[list[dict], int, int]:
    sheet_t = R.load_sheet_trades(R.BASE / SYM)
    sheet_t = [t for t in sheet_t if t["entry"] and t["entry"] >= R.MIN_DATE]
    cdf = pd.read_csv(R.STAMP_DIR / f"WPBR_Closed_{R.STAMP}.csv")
    aapl = cdf[cdf["SYMBOL"].astype(str).str.upper() == SYM].copy()
    eng_by = {R.parse_entry(row.DATE_OPENED): row for _, row in aapl.iterrows()}
    forks: list[dict] = []
    matched = 0
    exit_ok = 0
    for t in sheet_t:
        row = eng_by.get(t["entry"])
        if row is None:
            continue
        matched += 1
        ex = R.parse_entry(row.DATE_CLOSED)
        xp = float(row.EXIT_PRICE)
        exit_d_ok = t["exit"] == ex
        exit_p_ok = t["exit_px"] is not None and abs(t["exit_px"] - xp) <= 0.02
        if exit_d_ok and exit_p_ok:
            exit_ok += 1
        else:
            forks.append(
                {
                    "entry": t["entry"],
                    "sheet_exit": t["exit"],
                    "eng_exit": ex,
                    "sheet_px": t["exit_px"],
                    "eng_px": xp,
                }
            )
    return forks, exit_ok, matched


def confirm_halfup_log() -> dict:
    eng = R.confirm_engine()
    log = R.STAMP_DIR / "_run_log.txt"
    log_txt = R.read_text_any(log) if log.is_file() else ""
    low = log_txt.lower()
    eng["startfloor_in_log"] = (
        "floors pivots at start" in low
        or "startfloor" in low
        or "min_pivot" in low
        or "pivot" in low and "2016-01-01" in log_txt
    )
    eng["stop91_in_log"] = "0.91" in log_txt or "stop_pct=0.91" in low
    eng["half_up_retest_in_log"] = (
        "half_up" in low
        or "half-up" in low
        or "ROUND_HALF_UP" in log_txt
        or "retest" in low and "half" in low
    )
    eng["log_snip"] = [
        ln.strip()
        for ln in log_txt.splitlines()
        if any(
            k in ln.lower()
            for k in (
                "second_chance",
                "stop_pct",
                "start",
                "floor",
                "half",
                "retest",
                "variant",
                "round",
            )
        )
    ][:40]
    return eng


def write_status(r: dict, eng: dict, stacked: dict, forks: list, exit_ok: int, matched: int) -> Path:
    fair = r["fair"]
    out = R.BASE / SYM / f"{SYM}_wpbr_reconcile_status.md"
    wl = stacked["wl_ratio"]
    wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"

    open_n = 0
    op = R.STAMP_DIR / f"WPBR_Open_{R.STAMP}.csv"
    if op.is_file():
        odf = pd.read_csv(op)
        if "SYMBOL" in odf.columns:
            open_n = int((odf["SYMBOL"].astype(str).str.upper() == SYM).sum())

    # pre-2016 check on zones/closed
    pre2016_notes = []
    zpath = R.STAMP_DIR / f"WPBR_ZONES_{SYM}_{R.STAMP}.csv"
    pre_z = 0
    min_piv = None
    if zpath.is_file():
        zdf = pd.read_csv(zpath)
        piv_col = next(
            (c for c in zdf.columns if "PIVOT" in c.upper() and "MONDAY" in c.upper()),
            None,
        )
        if piv_col is None:
            piv_col = next((c for c in zdf.columns if "PIVOT" in c.upper()), None)
        if piv_col:
            pivs = [R.nd(x) for x in zdf[piv_col]]
            pivs = [p for p in pivs if p]
            pre_z = sum(1 for p in pivs if p < "2016-01-01")
            min_piv = min(pivs) if pivs else None
            pre2016_notes.append(
                f"`WPBR_ZONES_{SYM}_{R.STAMP}.csv` ({len(pivs)} rows) | **{pre_z}** | min pivot `{min_piv}`"
            )

    cdf = pd.read_csv(R.STAMP_DIR / f"WPBR_Closed_{R.STAMP}.csv")
    aapl = cdf[cdf["SYMBOL"].astype(str).str.upper() == SYM]
    opens = [R.parse_entry(x) for x in aapl["DATE_OPENED"]]
    opens = [o for o in opens if o]
    pre_c = sum(1 for o in opens if o < "2016-01-01")
    min_open = min(opens) if opens else None

    lines: list[str] = []
    lines.append(
        f"# {SYM} WPBR reconcile — variant C + SC-on + startfloor + HALF_UP retest (`{R.STAMP}`)"
    )
    lines.append("")
    lines.append(f"**Engine:** `{ENG_DIR}` (`{R.STAMP}`)")
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (log: **{eng['sc_in_run_log']}**)"
    )
    lines.append(
        "**Settings:** stop_pct=0.91 + start_date=2016-01-01 + **startfloor** + "
        "**HALF_UP retest** (stamp halfup outdir)."
    )
    lines.append("**Paste:** breakouts/retests/rockets + trades only (OHLC/weekly unchanged).")
    lines.append("")
    lines.append("## Structure / serialization")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Pivots | {fair['pivots_match']} |")
    lines.append(f"| Zones | {fair['zones_ok']} |")
    lines.append(f"| Retest | {fair['retest_ok']} |")
    lines.append(f"| Rocket (sheet fires) | {fair['rocket_where_sheet_fires']} |")
    lines.append(f"| Raw | **{r['raw']}** |")
    lines.append(f"| Ser | **{r['ser']}** |")
    lines.append(f"| Eng closed (+open) | {r['closed_n']} ({open_n} open) |")
    lines.append(f"| Sheet trades ≥2016 | {r['n_sheet_trades']} |")
    lines.append(f"| Exit match (entry-matched) | **{exit_ok}/{matched}** |")
    lines.append(f"| Exit forks | **{len(forks)}** |")
    lines.append("")
    if r["raw_orphans"]:
        lines.append(f"**Raw orphans:** {', '.join(r['raw_orphans'])}")
    else:
        lines.append("**Raw orphans:** —")
    lines.append("")
    if r["ser_orphans"]:
        lines.append(f"**Ser orphans:** {', '.join(r['ser_orphans'])}")
    else:
        lines.append("**Ser orphans:** —")
    lines.append("")
    if forks:
        lines.append(f"**Exit forks ({len(forks)}):**")
        for f in forks:
            lines.append(
                f"- entry `{f['entry']}` sheet exit `{f['sheet_exit']}` @{f['sheet_px']} "
                f"vs eng `{f['eng_exit']}` @{f['eng_px']}"
            )
    else:
        lines.append(
            "**Exit forks:** none (all entry-matched trades agree on exit date/px within tol)."
        )
    lines.append("")
    if fair["retest_mismatches"]:
        lines.append(f"**Retest mismatches ({len(fair['retest_mismatches'])}):**")
        for m in fair["retest_mismatches"][:20]:
            lines.append(
                f"- pivot `{m['pivot']}` sheet `{m['sheet_retest']}` vs eng `{m['eng_retest']}`"
            )
        lines.append("")
    if fair["n_eng_only"]:
        lines.append(f"**Eng-only rockets:** {fair['n_eng_only']}")
        for er in fair["eng_only"][:20]:
            lines.append(
                f"- pivot `{er['pivot']}` signal `{er['eng_signal']}` fill `{er['eng_fill']}`"
            )
        lines.append("")

    lines.append("## Stacked results (engine closed)")
    lines.append("")
    lines.append("Order: trades → win% → avg% → W/L → avg days → $PnL")
    lines.append("")
    lines.append("```")
    lines.append(SYM)
    lines.append(str(stacked["n"]))
    lines.append(f"{stacked['win_pct']:.1f}%")
    lines.append(f"{stacked['avg_profit_pct']:.1f}%")
    lines.append(wl_s)
    lines.append(f"{stacked['avg_days']:.1f}")
    lines.append(f"${stacked['pnl_dollars']:,.2f}")
    lines.append("```")
    lines.append("")

    lines.append("## Pre-2016 pivots (startfloor)")
    lines.append("")
    lines.append("| Artifact | Pre-2016 | Notes |")
    lines.append("|---|---:|---|")
    for note in pre2016_notes:
        parts = note.split(" | ")
        if len(parts) == 3:
            lines.append(f"| {parts[0]} | {parts[1]} | {parts[2]} |")
    lines.append(
        f"| Closed {SYM} entries | **{pre_c}** | min open `{min_open}` |"
    )
    lines.append("")
    verdict = "PASS" if pre_z == 0 and pre_c == 0 else "FAIL"
    lines.append(
        f"- **Verdict: {verdict}** — startfloor stamp `{R.STAMP}` pre-2016 zone/trade check."
    )
    lines.append("")

    lines.append("## Remaining mismatches")
    lines.append("")
    remain = []
    if r["raw_orphans"]:
        remain.append(
            f"- raw orphan(s): `{', '.join(r['raw_orphans'])}` "
            "(present in ser / closed+open — SC or occupancy path; not in primary zone-stream raw fills)"
        )
    if r["ser_orphans"]:
        remain.append(f"- ser orphan(s): `{', '.join(r['ser_orphans'])}`")
    if forks:
        remain.append(f"- exit fork(s): {len(forks)}")
        for f in forks:
            remain.append(
                f"  - `{f['entry']}` sheet `{f['sheet_exit']}` vs eng `{f['eng_exit']}`"
            )
    if fair["retest_mismatches"]:
        remain.append(f"- retest mismatch(es): {len(fair['retest_mismatches'])}")
    if fair["n_eng_only"]:
        remain.append(
            f"- {fair['n_eng_only']} eng-only rocket(s) (sheet blank rocket on those pivots; not trade orphans)"
        )
    if not remain:
        remain.append("- none")
    lines.extend(remain)
    lines.append("")
    lines.append(
        f"*Reconciled vs HALF_UP retest + startfloor stamp `{R.STAMP}` "
        f"(`_tmp_aapl_halfup_startfloor_reconcile.py`).*"
    )
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    print("STAMP_DIR:", R.STAMP_DIR)
    print("exists:", R.STAMP_DIR.is_dir())
    print("Closed:", (R.STAMP_DIR / f"WPBR_Closed_{R.STAMP}.csv").is_file())

    r = R.analyze(SYM)
    eng = confirm_halfup_log()
    stacked = stacked_closed()
    forks, exit_ok, matched = exit_forks(r)
    status_path = write_status(r, eng, stacked, forks, exit_ok, matched)

    wl = stacked["wl_ratio"]
    wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"
    fair = r["fair"]

    parent = {
        "symbol": SYM,
        "stamp": R.STAMP,
        "ser": r["ser"],
        "raw": r["raw"],
        "raw_orphans": r["raw_orphans"],
        "ser_orphans": r["ser_orphans"],
        "exit_forks": forks,
        "exit_match": f"{exit_ok}/{matched}",
        "stacked": stacked,
        "pivots": fair["pivots_match"],
        "zones": fair["zones_ok"],
        "retest": fair["retest_ok"],
        "rocket": fair["rocket_where_sheet_fires"],
        "eng_only_rockets": fair["n_eng_only"],
        "retest_mismatches": fair["retest_mismatches"],
        "status": str(status_path),
        "sc_in_run_log": eng["sc_in_run_log"],
        "log_snip": eng.get("log_snip"),
    }
    parent_path = R.BASE / SYM / f"{SYM}_halfup_startfloor_{R.STAMP}_parent_summary.json"
    parent_path.write_text(json.dumps(parent, indent=2, default=str), encoding="utf-8")

    print("=" * 72)
    print("PARENT SUMMARY")
    print("=" * 72)
    print(f"ser: {r['ser']}  raw: {r['raw']}")
    print(f"raw orphans: {r['raw_orphans'] or '(none)'}")
    print(f"ser orphans: {r['ser_orphans'] or '(none)'}")
    print(f"exit forks: {len(forks)}  exit_match: {exit_ok}/{matched}")
    for f in forks:
        print(f"  - {f}")
    print(f"pivots/zones/retest/rocket: {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} / {fair['rocket_where_sheet_fires']}")
    print(f"eng-only rockets: {fair['n_eng_only']}")
    if fair["retest_mismatches"]:
        print(f"retest mismatches: {len(fair['retest_mismatches'])}")
        for m in fair["retest_mismatches"][:10]:
            print(f"  - {m}")
    print("6-value stacked:")
    print(SYM)
    print(stacked["n"])
    print(f"{stacked['win_pct']:.1f}%")
    print(f"{stacked['avg_profit_pct']:.1f}%")
    print(wl_s)
    print(f"{stacked['avg_days']:.1f}")
    print(f"${stacked['pnl_dollars']:,.2f}")
    print(f"wrote: {status_path}")
    print(f"parent: {parent_path}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
