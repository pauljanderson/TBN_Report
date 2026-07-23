#!/usr/bin/env python3
"""NFLX-only reconcile vs startfloor halfup stamp 260722165827."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
STAMP_DIR = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
)
STAMP = "260722165827"
OUT_MD = REPO / "drive" / "wpbr_sheet_reconcile" / "NFLX" / "NFLX_wpbr_reconcile_status.md"
STACK_TXT = STAMP_DIR / "_nflx_stacked_stats.txt"

sys.path.insert(0, str(REPO / "tools"))
spec = importlib.util.spec_from_file_location(
    "vc_reconcile",
    REPO / "tools" / "_variantC_SC_stop91_2016_wpbr_reconcile.py",
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

mod.STAMP_DIR = STAMP_DIR
mod.STAMP = STAMP


def stacked_six(sym: str) -> dict:
    df = pd.read_csv(STAMP_DIR / f"WPBR_Closed_{STAMP}.csv")
    df = df[df["SYMBOL"].astype(str).str.upper() == sym.upper()].copy()
    n = len(df)
    if n == 0:
        return {
            "trades": 0,
            "win_pct": None,
            "avg_profit_pct": None,
            "win_loss": None,
            "avg_days": None,
            "pnl": 0.0,
        }

    def pct(x):
        if isinstance(x, str):
            return float(x.replace("%", "").replace(",", "").strip())
        return float(x)

    pnls = df["PNL_PCT"].map(pct)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    win_pct = 100.0 * len(wins) / n
    avg_profit = float(pnls.mean())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss_abs = float((-losses).mean()) if len(losses) else 0.0
    win_loss = (avg_win / avg_loss_abs) if avg_loss_abs else None
    avg_days = float(pd.to_numeric(df["DAYS_HELD"], errors="coerce").mean())
    pnl = float(pd.to_numeric(df["PNL_DOLLARS"], errors="coerce").sum())
    return {
        "trades": n,
        "win_pct": win_pct,
        "avg_profit_pct": avg_profit,
        "win_loss": win_loss,
        "avg_days": avg_days,
        "pnl": pnl,
    }


def forks(r: dict) -> list[dict]:
    """Entry-date matches with exit/entry_px forks vs sheet trades."""
    out_dir = mod.BASE / "NFLX"
    sheet_t = [t for t in mod.load_sheet_trades(out_dir) if t["entry"] and t["entry"] >= mod.MIN_DATE]
    closed = mod.load_closed("NFLX")
    by_entry = {t["entry"]: t for t in closed if t["entry"]}
    forks_out = []
    for t in sheet_t:
        e = by_entry.get(t["entry"])
        if not e:
            continue
        notes = []
        if t["exit"] and e["exit"] and t["exit"] != e["exit"]:
            notes.append(f"exit {t['exit']} vs {e['exit']}")
        if (
            t["entry_px"] is not None
            and e["entry_px"] is not None
            and abs(t["entry_px"] - e["entry_px"]) > 0.02
        ):
            notes.append(f"entry_px {t['entry_px']} vs {e['entry_px']}")
        if notes:
            forks_out.append({"entry": t["entry"], "notes": notes})
    return forks_out


def write_status(r: dict, eng: dict, six: dict, fork_rows: list[dict], nflx: dict) -> None:
    fair = r["fair"]
    lines: list[str] = []
    lines.append(f"# NFLX WPBR reconcile — variant C + SC-on + startfloor halfup (`{STAMP}`)")
    lines.append("")
    lines.append(
        f"**Engine:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_20260722165815/` "
        f"(`{STAMP}`)"
    )
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (log: **{eng['sc_in_run_log']}**)"
    )
    lines.append(
        "**Settings:** stop_pct=0.91, start_date=2016-01-01, **min_pivot_date / startfloor**, "
        "**HALF_UP** pivot then band (pre-2016 pivots skipped)."
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
    lines.append(f"| Sheet trades ≥2016 | {r['n_sheet_trades']} |")
    lines.append("")
    if r["raw_orphans"]:
        lines.append(f"**Raw orphans:** {', '.join(r['raw_orphans'])}")
        lines.append("")
    else:
        lines.append("**Raw orphans:** —")
        lines.append("")
    if r["ser_orphans"]:
        lines.append(f"**Ser orphans:** {', '.join(r['ser_orphans'])}")
        lines.append("")
    else:
        lines.append("**Ser orphans:** —")
        lines.append("")
    if fork_rows:
        lines.append(f"**Exit/entry forks ({len(fork_rows)}):**")
        for f in fork_rows:
            lines.append(f"- `{f['entry']}`: {'; '.join(f['notes'])}")
        lines.append("")
    else:
        lines.append("**Exit/entry forks:** —")
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
        lines.append("**Eng-only rockets (paired blank sheet):** 0")
        lines.append("")

    lines.append("## NFLX SC focus")
    lines.append("")
    lines.append(f"- **2022-05-13:** {nflx['may13_status']}")
    lines.append(f"- **2023-10-16 vs 2023-10-17:** {nflx['oct16_vs_17_status']}")
    for d, info in nflx["dates"].items():
        lines.append(
            f"  - `{d}`: sheet={info['in_sheet']} raw={info['in_raw']} ser={info['in_ser']}"
        )
    lines.append("")

    lines.append("## Engine stacked (6-value)")
    lines.append("")
    lines.append("Order: trades → win% → avg profit% → win/loss → avg days → $PnL")
    lines.append("")
    lines.append("```")
    lines.append("NFLX")
    lines.append(str(six["trades"]))
    lines.append(f"{six['win_pct']:.1f}%")
    lines.append(f"{six['avg_profit_pct']:.1f}%")
    wl = six["win_loss"]
    lines.append(f"{wl:.2f}" if wl is not None else "n/a")
    lines.append(f"{six['avg_days']:.1f}")
    lines.append(f"${six['pnl']:,.2f}")
    lines.append("```")
    lines.append("")

    eng_only = sorted(set(r["eng_entries"]) - set(r["sheet_entries"]))
    sheet_only_ser = r["ser_orphans"]
    lines.append("## Remaining mismatches")
    lines.append("")
    lines.append(f"- Ser orphans: `{', '.join(sheet_only_ser) or '—'}`")
    lines.append(f"- Eng-only entries (not on sheet): `{', '.join(eng_only) or '—'}`")
    lines.append(f"- Raw orphans (SC lifecycle expected): `{', '.join(r['raw_orphans']) or '—'}`")
    lines.append(f"- Exit/entry forks: `{len(fork_rows)}`")
    lines.append("")
    lines.append(
        f"*Generated by `tools/_tmp_nflx_startfloor_reconcile.py` vs stamp `{STAMP}`.*"
    )
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    eng = mod.confirm_engine()
    print("engine:", eng)
    r = mod.analyze("NFLX")
    fair = r["fair"]
    print(
        f"piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} "
        f"rocket {fair['rocket_where_sheet_fires']} raw {r['raw']} ser {r['ser']} "
        f"closed={r['closed_n']} raw_orphans={r['raw_orphans']} ser_orphans={r['ser_orphans']}"
    )
    print("sheet_entries:", r["sheet_entries"])
    print("eng_entries:", r["eng_entries"])
    nflx = mod.nflx_focus(r)
    print("NFLX focus:", nflx)
    six = stacked_six("NFLX")
    print("stacked:", six)
    fork_rows = forks(r)
    print("forks:", fork_rows)
    write_status(r, eng, six, fork_rows, nflx)
    print(f"wrote {OUT_MD}")

    wl = six["win_loss"]
    stack_lines = [
        "NFLX",
        str(six["trades"]),
        f"{six['win_pct']:.1f}%",
        f"{six['avg_profit_pct']:.1f}%",
        f"{wl:.2f}" if wl is not None else "n/a",
        f"{six['avg_days']:.1f}",
        f"${six['pnl']:,.2f}",
        "",
    ]
    STACK_TXT.write_text("\n".join(stack_lines), encoding="utf-8")
    print(f"wrote {STACK_TXT}")

    # Parent summary block
    print("\n=== PARENT SUMMARY ===")
    print(f"NFLX startfloor halfup `{STAMP}`: ser **{r['ser']}**, raw **{r['raw']}**, closed={r['closed_n']}")
    print(f"  orphans raw={r['raw_orphans'] or '—'} ser={r['ser_orphans'] or '—'}")
    print(f"  forks={len(fork_rows)} eng_only_rockets={fair['n_eng_only']}")
    print(
        f"  stacked: {six['trades']} | {six['win_pct']:.1f}% | {six['avg_profit_pct']:.1f}% | "
        f"{(f'{wl:.2f}' if wl is not None else 'n/a')} | {six['avg_days']:.1f}d | ${six['pnl']:,.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
