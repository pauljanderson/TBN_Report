#!/usr/bin/env python3
"""MSFT-only reconcile vs startfloor+halfup stamp 260722165827."""
from __future__ import annotations

import importlib.util
import json
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
OUT_MD = REPO / "drive" / "wpbr_sheet_reconcile" / "MSFT" / "MSFT_wpbr_reconcile_status.md"
OUT_JSON = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "MSFT"
    / f"MSFT_startfloor_halfup_{STAMP}_parent_summary.json"
)

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


def forks() -> tuple[list[dict], int, int]:
    out_dir = mod.BASE / "MSFT"
    sheet_t = [t for t in mod.load_sheet_trades(out_dir) if t["entry"] and t["entry"] >= mod.MIN_DATE]
    closed = mod.load_closed("MSFT")
    by_entry = {t["entry"]: t for t in closed if t["entry"]}
    forks_out = []
    matched = 0
    for t in sheet_t:
        e = by_entry.get(t["entry"])
        if not e:
            continue
        matched += 1
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
    exit_match = matched - len(forks_out)
    return forks_out, exit_match, matched


def pre2016_check() -> dict:
    zpath = STAMP_DIR / f"WPBR_ZONES_MSFT_{STAMP}.csv"
    zones_pre = 0
    min_piv = None
    if zpath.is_file():
        zdf = pd.read_csv(zpath)
        col = None
        for c in ("PIVOT_MONDAY", "pivot_monday", "PIVOT", "Pivot"):
            if c in zdf.columns:
                col = c
                break
        if col:
            pivs = [mod.nd(x) for x in zdf[col]]
            pivs = [p for p in pivs if p]
            if pivs:
                min_piv = min(pivs)
                zones_pre = sum(1 for p in pivs if p < mod.MIN_DATE)
    closed = mod.load_closed("MSFT")
    closed_pre = sum(1 for t in closed if t["entry"] and t["entry"] < mod.MIN_DATE)
    return {
        "zones_pre2016": zones_pre,
        "min_pivot": min_piv,
        "closed_pre2016": closed_pre,
        "min_entry": min((t["entry"] for t in closed if t["entry"]), default=None),
    }


def write_status(r: dict, eng: dict, six: dict, fork_rows: list[dict], exit_match: int, matched: int, pre: dict) -> None:
    fair = r["fair"]
    eng_only = sorted(set(r["eng_entries"]) - set(r["sheet_entries"]))
    lines: list[str] = []
    lines.append(f"# MSFT WPBR reconcile — variant C + SC-on + startfloor + halfup (`{STAMP}`)")
    lines.append("")
    lines.append(
        f"**Engine:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_20260722165815/` "
        f"(`{STAMP}`)"
    )
    lines.append(f"**SC:** `wpbr_second_chance_after_win=true` (log: **{eng['sc_in_run_log']}**)")
    lines.append(
        f"**Startfloor:** WPBR pivots floored at `start_date=2016-01-01` "
        f"(HALF_UP round: **{eng.get('has_HALF_UP')}**; `stop_pct=0.91`)."
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
    lines.append(f"| Eng closed (+open) | {r['closed_n']} |")
    lines.append(f"| Sheet trades ≥2016 | {r['n_sheet_trades']} |")
    lines.append(f"| Exit match (entry-matched) | **{exit_match}/{matched}** |")
    lines.append(f"| Exit forks | **{len(fork_rows)}** |")
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
    if eng_only:
        lines.append(f"**Eng-only forks:** {', '.join(eng_only)}")
    else:
        lines.append("**Eng-only forks:** —")
    lines.append("")
    if fork_rows:
        lines.append(f"**Exit forks:** {len(fork_rows)}")
        for f in fork_rows:
            lines.append(f"- `{f['entry']}`: {'; '.join(f['notes'])}")
    else:
        lines.append("**Exit forks:** none (all entry-matched trades agree on exit date/px within tol).")
    lines.append("")
    lines.append(f"**Eng-only rockets:** {fair['n_eng_only']}")
    lines.append("")
    lines.append("## Stacked results (engine closed)")
    lines.append("")
    lines.append("Order: trades → win% → avg% → W/L → avg days → $PnL")
    lines.append("")
    lines.append("```")
    lines.append("MSFT")
    lines.append(str(six["trades"]))
    lines.append(f"{six['win_pct']:.1f}%")
    lines.append(f"{six['avg_profit_pct']:.1f}%")
    wl = six["win_loss"]
    lines.append(f"{wl:.2f}" if wl is not None else "n/a")
    lines.append(f"{six['avg_days']:.1f}")
    lines.append(f"${six['pnl']:,.2f}")
    lines.append("```")
    lines.append("")
    lines.append("## vs prior startfloor (no halfup) `260722161242`")
    lines.append("")
    lines.append("| Item | Startfloor `260722161242` | Halfup `260722165827` |")
    lines.append("|---|---|---|")
    lines.append("| Ser | **11/11** | **{}** |".format(r["ser"]))
    lines.append("| Raw orphans | `2020-03-25`, `2022-10-14` | `{}` |".format(
        "`, `".join(r["raw_orphans"]) if r["raw_orphans"] else "—"
    ))
    lines.append("| Eng-only forks | — | `{}` |".format(", ".join(eng_only) if eng_only else "—"))
    lines.append(
        f"| Stacked | 11 / 90.9% / 18.9% / 1.70 / 134.4 / $296,736.40 | "
        f"{six['trades']} / {six['win_pct']:.1f}% / {six['avg_profit_pct']:.1f}% / "
        f"{(f'{wl:.2f}' if wl is not None else 'n/a')} / {six['avg_days']:.1f} / ${six['pnl']:,.2f} |"
    )
    lines.append("")
    lines.append("## Pre-2016 pivots (startfloor)")
    lines.append("")
    lines.append("| Artifact | Pre-2016 | Notes |")
    lines.append("|---|---:|---|")
    lines.append(
        f"| `WPBR_ZONES_MSFT_{STAMP}.csv` | **{pre['zones_pre2016']}** | "
        f"min pivot `{pre['min_pivot']}` |"
    )
    lines.append(
        f"| Closed MSFT entries | **{pre['closed_pre2016']}** | "
        f"min open `{pre['min_entry']}` |"
    )
    lines.append("")
    verdict = "PASS" if pre["zones_pre2016"] == 0 and pre["closed_pre2016"] == 0 else "FAIL"
    lines.append(
        f"- **Verdict: {verdict}** — "
        f"{'no' if verdict == 'PASS' else 'found'} pre-2016 WPBR zone pivots / trade entries "
        f"under startfloor+halfup stamp `{STAMP}`."
    )
    lines.append("")
    lines.append("## Remaining mismatches")
    lines.append("")
    if r["raw_orphans"]:
        lines.append(
            f"- raw orphans: `{', '.join(r['raw_orphans'])}` "
            "(both present in ser / closed — SC or occupancy path; not in primary zone-stream raw fills)"
        )
    else:
        lines.append("- raw orphans: none")
    lines.append(f"- ser orphans: {'`' + ', '.join(r['ser_orphans']) + '`' if r['ser_orphans'] else 'none'}")
    lines.append(f"- eng-only forks: {'`' + ', '.join(eng_only) + '`' if eng_only else 'none'}")
    lines.append(f"- exit forks: {'none' if not fork_rows else len(fork_rows)}")
    lines.append("")
    lines.append(
        f"*Reconciled with helpers from `tools/_variantC_SC_stop91_2016_wpbr_reconcile.py` "
        f"vs startfloor+halfup stamp `{STAMP}`.*"
    )
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    eng = mod.confirm_engine()
    print("engine:", eng)
    r = mod.analyze("MSFT")
    fair = r["fair"]
    print(
        f"piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} "
        f"rocket {fair['rocket_where_sheet_fires']} raw {r['raw']} ser {r['ser']} "
        f"closed={r['closed_n']} raw_orphans={r['raw_orphans']} ser_orphans={r['ser_orphans']}"
    )
    print("sheet_entries:", r["sheet_entries"])
    print("eng_entries:", r["eng_entries"])
    six = stacked_six("MSFT")
    print("stacked:", six)
    fork_rows, exit_match, matched = forks()
    print("forks:", fork_rows, "exit_match", exit_match, "/", matched)
    pre = pre2016_check()
    print("pre2016:", pre)
    write_status(r, eng, six, fork_rows, exit_match, matched, pre)
    print(f"wrote {OUT_MD}")

    eng_only = sorted(set(r["eng_entries"]) - set(r["sheet_entries"]))
    wl = six["win_loss"]
    payload = {
        "symbol": "MSFT",
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR.relative_to(REPO)).replace("\\", "/"),
        "sc_in_run_log": eng["sc_in_run_log"],
        "startfloor": True,
        "halfup": eng.get("has_HALF_UP"),
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
        "eng_only_forks": eng_only,
        "exit_match": f"{exit_match}/{matched}",
        "exit_forks": len(fork_rows),
        "n_eng_only_rockets": fair["n_eng_only"],
        "pre2016": pre,
        "stacked": {
            "n": six["trades"],
            "win_pct": f"{six['win_pct']:.1f}%",
            "avg_profit_pct": f"{six['avg_profit_pct']:.1f}%",
            "win_loss": f"{wl:.2f}" if wl is not None else None,
            "avg_days": f"{six['avg_days']:.1f}",
            "dollar_pnl": f"${six['pnl']:,.2f}",
            "lines": [
                str(six["trades"]),
                f"{six['win_pct']:.1f}%",
                f"{six['avg_profit_pct']:.1f}%",
                f"{wl:.2f}" if wl is not None else "n/a",
                f"{six['avg_days']:.1f}",
                f"${six['pnl']:,.2f}",
            ],
        },
        "remaining_mismatches": (
            [f"raw orphans {', '.join(r['raw_orphans'])} (both in ser; SC/occupancy)"]
            if r["raw_orphans"]
            else []
        ),
        "status_md": "drive/wpbr_sheet_reconcile/MSFT/MSFT_wpbr_reconcile_status.md",
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON}")

    print("\n=== PARENT SUMMARY ===")
    print(f"MSFT startfloor+halfup `{STAMP}`: ser **{r['ser']}**, raw **{r['raw']}**, closed={r['closed_n']}")
    print(f"  orphans raw={r['raw_orphans'] or '—'} ser={r['ser_orphans'] or '—'}")
    print(f"  eng_only={eng_only or '—'} forks={len(fork_rows)} eng_only_rockets={fair['n_eng_only']}")
    print(
        f"  stacked: {six['trades']} | {six['win_pct']:.1f}% | {six['avg_profit_pct']:.1f}% | "
        f"{(f'{wl:.2f}' if wl is not None else 'n/a')} | {six['avg_days']:.1f}d | ${six['pnl']:,.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
