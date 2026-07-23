"""One-shot: NVDA sheet vs engine stamp 260722165827 (startfloor halfup). Do not commit."""
from __future__ import annotations

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
STAMP_NOTE = "startfloor halfup MarkTen run"

SYM = "NVDA"
FOCUS_FILL = "2017-09-28"
FOCUS_PIVOT = "2017-06-05"
FOCUS_SIGNAL = "2017-09-27"


def fp(x):
    if pd.isna(x):
        return None
    t = str(x).replace("%", "").replace(",", "").replace("$", "").strip()
    try:
        return float(t)
    except Exception:
        return None


def stacked_nvda_closed() -> dict:
    p = R.STAMP_DIR / f"WPBR_Closed_{R.STAMP}.csv"
    df = pd.read_csv(p)
    print("Closed CSV columns (first 20):", list(df.columns)[:20])
    print(
        "key cols present:",
        {
            c: (c in df.columns)
            for c in [
                "SYMBOL",
                "PNL_PCT",
                "PNL_DOLLARS",
                "DAYS_HELD",
                "EXIT_TYPE",
                "DATE_OPENED",
                "DATE_CLOSED",
            ]
        },
    )
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
        "entries": [
            R.parse_entry(x) for x in s["DATE_OPENED"]
        ],
    }


def write_status(r: dict, eng: dict, stacked: dict, eng_only_928: bool) -> Path:
    fair = r["fair"]
    out = R.BASE / SYM / f"{SYM}_wpbr_reconcile_status.md"
    lines: list[str] = []
    lines.append(f"# {SYM} WPBR reconcile — variant C + SC-on + startfloor (`{R.STAMP}`)")
    lines.append("")
    stamp_dir_rel = (
        "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_20260722165815/"
    )
    lines.append(f"**Engine:** `{stamp_dir_rel}` (`{R.STAMP}`)")
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (log: **{eng['sc_in_run_log']}**)"
    )
    lines.append(
        f"**Note:** {STAMP_NOTE} (stamp `{R.STAMP}`; HALF_UP={eng.get('has_HALF_UP')})."
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
    lines.append(f"| Eng closed (+open) | {r['closed_n']} |")
    lines.append(f"| Sheet trades >=2016 | {r['n_sheet_trades']} |")
    lines.append("")
    lines.append(
        f"**Raw orphans:** {', '.join(r['raw_orphans']) if r['raw_orphans'] else 'none'}"
    )
    lines.append("")
    lines.append(
        f"**Ser orphans:** {', '.join(r['ser_orphans']) if r['ser_orphans'] else 'none'}"
    )
    lines.append("")
    sheet_set = set(r["sheet_entries"])
    eng_set = set(r["eng_entries"])
    sheet_only = sorted(sheet_set - eng_set)
    eng_only_fills = sorted(eng_set - sheet_set)
    lines.append(
        f"**Sheet-only entries:** {', '.join(sheet_only) if sheet_only else 'none'}"
    )
    lines.append("")
    lines.append(
        f"**Eng-only entries:** {', '.join(eng_only_fills) if eng_only_fills else 'none'}"
    )
    lines.append("")
    lines.append(
        f"**Trade forks:** "
        f"{'none (matched entries agree on exit/prices within tolerance).' if not fair['retest_mismatches'] else 'see retest mismatches'}"
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
        for er in fair["eng_only"][:15]:
            lines.append(
                f"- pivot `{er['pivot']}` signal `{er['eng_signal']}` fill `{er['eng_fill']}`"
            )
        lines.append("")
    else:
        lines.append("**Eng-only rockets:** none")
        lines.append("")
    lines.append(
        f"**Eng-only fill `{FOCUS_FILL}` (pivot `{FOCUS_PIVOT}` / signal `{FOCUS_SIGNAL}`):** "
        f"{'STILL PRESENT' if eng_only_928 else 'ABSENT'}"
    )
    lines.append("")
    wl = stacked["wl_ratio"]
    wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"
    lines.append("**6-value stacked (NVDA closed only, WPBR_Closed):**")
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
    lines.append(
        f"*Generated by `tools/_tmp_nvda_startfloor_reconcile.py` "
        f"(reuse `tools/_variantC_SC_stop91_2016_wpbr_reconcile.py`) vs startfloor stamp `{R.STAMP}`.*"
    )
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    print("STAMP_DIR:", R.STAMP_DIR)
    print("STAMP:", R.STAMP)
    print("exists Closed:", (R.STAMP_DIR / f"WPBR_Closed_{R.STAMP}.csv").is_file())
    print("exists Open:", (R.STAMP_DIR / f"WPBR_Open_{R.STAMP}.csv").is_file())

    r = R.analyze(SYM)
    eng = R.confirm_engine()
    stacked = stacked_nvda_closed()

    fair = r["fair"]
    eng_only_928 = any(
        (er.get("eng_fill") == FOCUS_FILL)
        or (
            er.get("pivot") == FOCUS_PIVOT
            and er.get("eng_signal") == FOCUS_SIGNAL
            and er.get("eng_fill") == FOCUS_FILL
        )
        for er in fair.get("eng_only") or []
    )
    # also check closed ser / raw
    in_ser = FOCUS_FILL in set(r["eng_entries"])
    in_raw = FOCUS_FILL in set(r["raw_fills"])
    in_sheet = FOCUS_FILL in set(r["sheet_entries"])

    status_path = write_status(r, eng, stacked, eng_only_928)
    status_txt = status_path.read_text(encoding="utf-8")

    wl = stacked["wl_ratio"]
    wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"

    print()
    print("=" * 72)
    print("PARENT SUMMARY")
    print("=" * 72)
    print(f"stamp: {R.STAMP} (startfloor)")
    print(f"ser: {r['ser']}  raw: {r['raw']}")
    print(f"raw orphans: {r['raw_orphans'] or '(none)'}")
    print(f"ser orphans: {r['ser_orphans'] or '(none)'}")
    print(f"eng closed (+open): {r['closed_n']}  sheet trades>=2016: {r['n_sheet_trades']}")
    print(f"pivots/zones/retest/rocket: {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} / {fair['rocket_where_sheet_fires']}")
    print(f"eng-only rockets (n={fair['n_eng_only']}):")
    for er in fair.get("eng_only") or []:
        print(f"  - pivot {er['pivot']} signal {er['eng_signal']} fill {er['eng_fill']}")
    if fair.get("retest_mismatches"):
        print(f"retest mismatches: {len(fair['retest_mismatches'])} (exit forks not separately tracked)")
        for m in fair["retest_mismatches"][:10]:
            print(f"  - pivot {m['pivot']} sheet {m['sheet_retest']} vs eng {m['eng_retest']}")
    else:
        print("retest mismatches / obvious exit forks: none from structure_stats")
    # sheet vs eng entry set forks
    sheet_set = set(r["sheet_entries"])
    eng_set = set(r["eng_entries"])
    sheet_only = sorted(sheet_set - eng_set)
    eng_only_fills = sorted(eng_set - sheet_set)
    print(f"sheet-only entries (not in eng ser): {sheet_only or '(none)'}")
    print(f"eng-only entries (not in sheet): {eng_only_fills or '(none)'}")
    print(
        f"6-value stacked NVDA closed: n={stacked['n']}  win%={stacked['win_pct']:.1f}%  "
        f"avg%={stacked['avg_profit_pct']:.1f}%  W/L={wl_s}  avg_days={stacked['avg_days']:.1f}  "
        f"$PnL=${stacked['pnl_dollars']:,.2f}"
    )
    print(
        f"eng-only fill {FOCUS_FILL} (pivot {FOCUS_PIVOT} signal {FOCUS_SIGNAL}): "
        f"{'STILL PRESENT' if eng_only_928 else 'ABSENT'} "
        f"(in_sheet={in_sheet} in_raw={in_raw} in_ser={in_ser})"
    )
    print(f"engine confirm: sc_in_run_log={eng['sc_in_run_log']} HALF_UP={eng['has_HALF_UP']} variantC_doc={eng['doc_variant_C']}")
    print(f"wrote status: {status_path}")
    print("=" * 72)
    print()
    print("--- FULL STATUS MD ---")
    print(status_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
