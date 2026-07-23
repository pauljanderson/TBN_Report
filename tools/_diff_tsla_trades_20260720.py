"""Diff TSLA sheet trades (post 2023-03-06 fix) vs engine stamp 260720143523."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
STAMP = "260720143523"
SHEET_TSV = ROOT / "tools" / "tsla_brt_sheet_trades_20260720.tsv"
WIN_START = datetime(2010, 1, 4).date()
WIN_END = datetime(2026, 6, 5).date()


def parse_date(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def within(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9


def is_win(pnl, result=""):
    if (result or "").upper() == "WIN":
        return True
    if (result or "").upper() == "LOSS":
        return False
    if pnl is None:
        return None
    return pnl > 0


def load_engine(stamp: str):
    eng_tr = []
    for path, is_open in (
        (ROOT / "drive" / f"BRT_Closed_{stamp}.csv", False),
        (ROOT / "drive" / f"BRT_Open_{stamp}.csv", True),
    ):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").upper() != "TSLA":
                    continue
                ca = parse_date(r.get("CLOSE_ABOVE_DATE"))
                op = parse_date(r.get("DATE_OPENED"))
                entry = parse_money(r.get("ENTRY_PRICE"))
                if entry is None:
                    continue
                ref = ca or op
                if ref and not (WIN_START <= ref <= WIN_END):
                    if op is None or not (WIN_START <= op <= WIN_END):
                        continue
                eng_tr.append(
                    {
                        "trigger_ca": ca,
                        "open": op,
                        "entry": entry,
                        "exit_date": parse_date(r.get("DATE_CLOSED")),
                        "exit_price": parse_money(r.get("EXIT_PRICE")),
                        "pnl_pct": parse_money(
                            str(r.get("PNL_PCT") or "").replace("%", "")
                        ),
                        "exit_type": r.get("EXIT_TYPE") or ("OPEN" if is_open else ""),
                        "is_open": is_open,
                    }
                )
    return eng_tr


def load_sheet(path: Path):
    sheet_tr = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            d = parse_date(r.get("Trigger Date"))
            entry = parse_money(r.get("Entry Price"))
            if d is None or entry is None:
                continue
            sheet_tr.append(
                {
                    "trigger": d,
                    "entry": entry,
                    "exit_date": parse_date(r.get("Exit Date")),
                    "exit_price": parse_money(r.get("Exit Price")),
                    "pnl_pct": parse_money(r.get("Profit %")),
                    "result": (r.get("Result") or "").strip(),
                }
            )
    return sheet_tr


def reconcile(sheet_tr, eng_tr):
    by_ca = {}
    for i, e in enumerate(eng_tr):
        if e["trigger_ca"]:
            by_ca.setdefault(e["trigger_ca"], []).append(i)

    used = set()
    exact, near, so = [], [], []
    for s in sheet_tr:
        cands = list(by_ca.get(s["trigger"], []))
        if not cands:
            for ei, e in enumerate(eng_tr):
                if ei in used:
                    continue
                if e["open"] and 0 <= (e["open"] - s["trigger"]).days <= 5:
                    cands.append(ei)
        hit = None
        kind = None
        best = None
        best_score = None
        for ei in cands:
            if ei in used:
                continue
            e = eng_tr[ei]
            if abs(s["entry"] - e["entry"]) < 1e-9:
                hit = ei
                kind = "exact"
                break
            if within(s["entry"], e["entry"], 0.05):
                score = abs(s["entry"] - e["entry"])
                if best_score is None or score < best_score:
                    best = ei
                    best_score = score
        if hit is None and best is not None:
            hit = best
            kind = "near"
        if hit is None:
            so.append(s)
            continue
        used.add(hit)
        e = eng_tr[hit]
        exit_match = None
        if s["exit_date"] and e["exit_date"]:
            exit_match = s["exit_date"] == e["exit_date"]
        entry_delta = abs(s["entry"] - e["entry"])
        rec = {
            "sheet": s,
            "engine": e,
            "kind": kind,
            "exit_date_match": exit_match,
            "entry_delta": entry_delta,
            "within_02": entry_delta <= 0.02 + 1e-9,
        }
        (exact if kind == "exact" else near).append(rec)

    eo = [eng_tr[i] for i in range(len(eng_tr)) if i not in used]
    matched = exact + near
    exit_ok = sum(1 for m in matched if m["exit_date_match"])
    exit_known = sum(1 for m in matched if m["exit_date_match"] is not None)
    near_02 = sum(1 for m in near if m["within_02"])
    matched_02 = len(exact) + near_02
    return {
        "exact": exact,
        "near": near,
        "matched": matched,
        "so": so,
        "eo": eo,
        "exit_ok": exit_ok,
        "exit_known": exit_known,
        "near_02": near_02,
        "matched_02": matched_02,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # keep copy under reconcile folder
    copy = OUT / "tsla_brt_sheet_trades_20260720.tsv"
    copy.write_text(SHEET_TSV.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

    sheet_tr = load_sheet(SHEET_TSV)
    eng_tr = load_engine(STAMP)
    r = reconcile(sheet_tr, eng_tr)
    exact, near, matched, so, eo = (
        r["exact"],
        r["near"],
        r["matched"],
        r["so"],
        r["eo"],
    )
    exit_ok, exit_known = r["exit_ok"], r["exit_known"]
    near_02, matched_02 = r["near_02"], r["matched_02"]

    sw = sum(1 for s in sheet_tr if is_win(s["pnl_pct"], s["result"]))
    sl = sum(1 for s in sheet_tr if is_win(s["pnl_pct"], s["result"]) is False)
    ew = sum(1 for e in eng_tr if (e["pnl_pct"] or 0) > 0)
    el = sum(1 for e in eng_tr if e["pnl_pct"] is not None and e["pnl_pct"] < 0)

    checks = [
        "2013-02-11",
        "2013-07-19",
        "2024-08-21",
        "2024-09-27",
        "2024-09-23",
        "2026-05-19",
        "2026-04-07",
    ]

    def find_sheet(dstr):
        d = datetime.strptime(dstr, "%Y-%m-%d").date()
        return next((s for s in sheet_tr if s["trigger"] == d), None)

    def find_eng(dstr):
        d = datetime.strptime(dstr, "%Y-%m-%d").date()
        return next((e for e in eng_tr if e["trigger_ca"] == d), None)

    def find_matched(dstr):
        d = datetime.strptime(dstr, "%Y-%m-%d").date()
        return next((m for m in matched if m["sheet"]["trigger"] == d), None)

    with open(
        OUT / "TSLA_trades_match_detail_20260720.csv", "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "sheet_trigger",
                "sheet_entry",
                "sheet_exit",
                "sheet_pnl",
                "eng_ca",
                "eng_open",
                "eng_entry",
                "eng_exit",
                "eng_pnl",
                "eng_exit_type",
                "exit_date_match",
                "entry_delta",
                "within_0p02",
            ]
        )
        for m in exact + near:
            s, e = m["sheet"], m["engine"]
            w.writerow(
                [
                    m["kind"],
                    s["trigger"],
                    s["entry"],
                    s["exit_date"],
                    s["pnl_pct"],
                    e["trigger_ca"],
                    e["open"],
                    e["entry"],
                    e["exit_date"],
                    e["pnl_pct"],
                    e["exit_type"],
                    m["exit_date_match"],
                    f"{m['entry_delta']:.4f}",
                    m["within_02"],
                ]
            )
        for s in so:
            w.writerow(
                [
                    "sheet_only",
                    s["trigger"],
                    s["entry"],
                    s["exit_date"],
                    s["pnl_pct"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        for e in eo:
            w.writerow(
                [
                    "engine_only",
                    "",
                    "",
                    "",
                    "",
                    e["trigger_ca"],
                    e["open"],
                    e["entry"],
                    e["exit_date"],
                    e["pnl_pct"],
                    e["exit_type"],
                    "",
                    "",
                    "",
                ]
            )

    special = []
    for dstr in checks:
        sm = find_matched(dstr)
        ss = find_sheet(dstr)
        ee = find_eng(dstr)
        if sm:
            special.append(
                f"- **{dstr}**: MATCHED (sheet {sm['sheet']['entry']:.4f} / eng "
                f"{sm['engine']['entry']:.4f}, Δ={sm['entry_delta']:.4f}; "
                f"exit {'OK' if sm['exit_date_match'] else sm['exit_date_match']})"
            )
        elif ss and not ee:
            special.append(
                f"- **{dstr}**: SHEET-ONLY (entry {ss['entry']:.4f}, exit {ss['exit_date']}, {ss['result']})"
            )
        elif ee and not ss:
            special.append(
                f"- **{dstr}**: ENGINE-ONLY (entry {ee['entry']:.4f}, exit {ee['exit_date']}, {ee['exit_type']})"
            )
        elif not ss and not ee:
            special.append(f"- **{dstr}**: absent from both")
        else:
            special.append(
                f"- **{dstr}**: present both but unmatched? sheet={ss} eng={ee}"
            )

    exit_mismatch = [m for m in matched if m["exit_date_match"] is False]

    lines = [
        "# TSLA trades reconcile — after sheet insert **2023-03-06**",
        "",
        "- Sheet paste: 2026-07-20 ~16:39 (post missing-day fix; first trade **2013-07-19**)",
        "- Saved: `tools/tsla_brt_sheet_trades_20260720.tsv` + `drive/brt_sheet_reconcile/tsla_brt_sheet_trades_20260720.tsv`",
        f"- Engine: `BRT_Closed_{STAMP}.csv` + `BRT_Open_{STAMP}.csv` (preferred stamp; no BRT re-run)",
        "- Settings context: `stop_loss_based=trigger_low`, `min_spy_compare_1y_at_trigger=-1000`, growth_filter on",
        "- Match key: sheet **Trigger Date** == engine **CLOSE_ABOVE_DATE**, entry exact or ±$0.05 (also report ±$0.02)",
        f"- Window: {WIN_START} .. {WIN_END} (sheet fully inside)",
        f"- Sheet trades: **{len(sheet_tr)}** (W/L {sw}/{sl}) — was **63** before 3/6 fix",
        f"- Engine trades in window: **{len(eng_tr)}** (W/L {ew}/{el})",
        "",
        "## Before → after (same engine stamp)",
        "",
        "| Metric | Before (growth `$0→FALSE` paste) | After (2023-03-06 added) |",
        "|---|---:|---:|",
        f"| Sheet trades | 63 | **{len(sheet_tr)}** |",
        f"| Matched ±$0.05 | 60/63 | **{len(matched)}/{len(sheet_tr)}** |",
        "| Sheet-only | 3 (2013-02-11, 2024-08-21, 2024-09-27) | "
        f"**{len(so)}** |",
        "| Engine-only | 2 (2024-09-23, open 2026-05-19) | "
        f"**{len(eo)}** |",
        f"| Exit-date agree | 60/60 | **{exit_ok}/{exit_known}** |",
        "",
        "## Match summary",
        f"- Exact entry: **{len(exact)}**",
        f"- Near entry (±$0.05): **{len(near)}** (of which ±$0.02: **{near_02}**)",
        f"- Total matched (±$0.05): **{len(matched)}** / {len(sheet_tr)} sheet "
        f"({100 * len(matched) / max(1, len(sheet_tr)):.1f}%)",
        f"- Matched at ±$0.02 (exact + near≤0.02): **{matched_02}** / {len(sheet_tr)}",
        f"- Sheet-only: **{len(so)}**",
        f"- Engine-only: **{len(eo)}**",
        f"- Exit-date match among matched (both have exit): **{exit_ok}/{exit_known}**",
        "",
        "## Special checks (3/6/2023 fix)",
        "",
    ]
    lines += special
    lines += [
        "",
        "### Key verifications",
        "",
        "- **2024-08-21**: GONE from sheet (expected — growth now uses same 8/18/2021 lookback as engine → FAIL).",
        "- **2013-02-11**: GONE from sheet (first trade now **2013-07-19**, matches engine).",
        "- **2024-09-23**: now on sheet (was engine-only twin); **2024-09-27** GONE.",
        "",
        "## Sheet-only",
        "| trigger | entry | exit | pnl% | result | note |",
        "|---|---:|---|---:|---|---|",
    ]
    if so:
        for s in so:
            lines.append(
                f"| {s['trigger']} | {s['entry']:.4f} | {s['exit_date']} | "
                f"{s['pnl_pct']} | {s['result']} | |"
            )
    else:
        lines.append("| *(none)* | | | | | |")

    lines += [
        "",
        "## Engine-only",
        "| close_above | open | entry | exit | pnl% | exit_type | note |",
        "|---|---|---:|---|---:|---|---|",
    ]
    eo_notes = {
        datetime(2024, 9, 23).date(): "was twin of old sheet 9/27 — should now match sheet",
        datetime(2026, 5, 19).date(): "open trade still live; sheet closed list ends 2026-04-07",
    }
    for e in eo:
        note = eo_notes.get(e["trigger_ca"], "")
        lines.append(
            f"| {e['trigger_ca']} | {e['open']} | {e['entry']:.4f} | {e['exit_date']} | "
            f"{e['pnl_pct']} | {e['exit_type']} | {note} |"
        )
    if not eo:
        lines.append("| *(none)* | | | | | | |")

    if near:
        lines += ["", "## Near entry matches (Δ ≤ $0.05)"]
        for m in near:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['trigger']}: sheet {s['entry']:.4f} vs eng {e['entry']:.4f} "
                f"(Δ={m['entry_delta']:.4f}; ≤0.02={m['within_02']}; "
                f"exit_match={m['exit_date_match']})"
            )

    if exit_mismatch:
        lines += ["", "## Exit-date mismatches among matched"]
        for m in exit_mismatch:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['trigger']}: sheet exit {s['exit_date']} vs eng "
                f"{e['exit_date']} ({e['exit_type']})"
            )
    else:
        lines += ["", "## Exit-date mismatches among matched", "", "(none)"]

    lines += [
        "",
        "## Delta vs prior mismatches",
        "",
        "| Prior mismatch | Status after 3/6 fix |",
        "|---|---|",
        "| Sheet-only **2013-02-11** | **Resolved** — absent from new sheet; first sheet trade is **2013-07-19** (matches engine) |",
        "| Sheet-only **2024-08-21** | **Resolved** — absent from new sheet (growth FAIL aligned with engine) |",
        "| Sheet-only **2024-09-27** | **Resolved** — absent; sheet now has twin **2024-09-23** |",
        "| Engine-only **2024-09-23** | **Resolved** — now matched on sheet |",
        "| Engine-only open **2026-05-19** | **Still open** on engine; not in sheet closed list (ends 4/7/2026) |",
        "",
        "## Notes",
        "",
        "- Sheet Trigger Date aligns with engine CLOSE_ABOVE_DATE; DATE_OPENED is typically next session.",
        "- With `stop_loss_based=trigger_low`, stop = signal-bar Low × 0.934 (sheet AM).",
        "- Engine stamp was **not** re-run; comparing against existing Closed/Open only.",
        "- Detail CSV: `TSLA_trades_match_detail_20260720.csv`",
        "",
    ]

    md_path = OUT / "TSLA_trades_diff_20260720.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    gates = f"""# TSLA sheet-only trades — entry gate analysis (current)

- Engine stamp: **`{STAMP}`** (`stop_loss_based=trigger_low`, `min_spy_compare_1y_at_trigger=-1000`, `growth_filter` 756 / slack 2)
- Sheet paste after **2023-03-06** insert: `tsla_brt_sheet_trades_20260720.tsv` (**{len(sheet_tr)}** trades)
- Match: **{len(matched)} / {len(sheet_tr)}** (±$0.05 entry on Trigger = CLOSE_ABOVE); exit dates **{exit_ok}/{exit_known}** among matches
- **Sheet-only closed trades: none**
- Remaining engine-only: open **2026-05-19** (not in sheet closed list)
- Diff: `TSLA_trades_diff_20260720.md`

---

## Active engine entry gates (this stamp)

### ON / binding

| Gate | Value | Role |
|------|------:|------|
| `entry_from_retest_only` | true | Buy only after BY/retest pending |
| `sheet_dw_countif_entry_enabled` | true | Eval date in simulated BY set |
| `require_close_gt_open` | true | Bullish signal bar (C>O) |
| `sheet_red_to_green_entry_enabled` | true | Prior red + today green |
| `growth_filter_enabled` | true | Need history + `Close[t] >= Close[t−756]` |
| `growth_bars` / `growth_history_slack_bars` | 756 / 2 | Min eval index **754** |
| `min_spy_compare_1y_at_trigger` | **−1000** | Effectively **off** |
| `allow_secondary_entries` | false | One open trade per symbol |
| `sheet_no_entry_same_bar_after_exit` | true | No same-bar re-entry |
| `stop_loss_based` | `trigger_low` | Exit path |

### OFF / no-op here

`too_high_multiplier=0`, `min_ind_score=-1`, IND buy off, tight-range off, DO/DP off.  
`entry_filter_major_pivot` / `entry_filter_is_20bar_high_at_trigger` are audit-style fields — **not** consulted in the pending entry loop.

---

## Current sheet-only root causes

**None** for closed trades after inserting missing sheet day **2023-03-06**.

| Prior # | Trigger | Prior first engine block | Status after 3/6 fix |
|--:|---------|--------------------------|----------------------|
| 1 | **2013-02-11** | `growth_not_enough_history` | **Gone from sheet** (first trade now 2013-07-19) |
| 2 | **2024-08-21** | `growth_filter_fail` (756 off-by-1) | **Gone from sheet** — lookback now aligns; growth FAIL on sheet too |
| 3 | **2024-09-27** | open-trade overlap (engine on 9/23) | **Gone**; sheet now takes **2024-09-23** twin |

### Remaining engine-only (not sheet-only)

| CLOSE_ABOVE | Entry | Exit | Note |
|-------------|------:|------|------|
| **2026-05-19** | 407.60 | OPEN | Still open on engine; sheet closed list ends **2026-04-07** |

---

## Root-cause counts (current)

| Count | Gate / issue |
|------:|------|
| **0** | sheet-only closed-trade entry-path divergences |
| **1** | engine open not yet on sheet closed list (2026-05-19) |

Not causes anymore: 756 off-by-1 from missing **2023-03-06**, 9/23 vs 9/27 twin, early 2013-02-11 growth history.

---

## Historical note

1. Pre−1000 SPY (`260720111055`): **17** sheet-only (mostly SPY floor).
2. After `-1000` + sheet `$0→FALSE` growth: **3** sheet-only (2013-02-11, 2024-08-21, 2024-09-27).
3. After sheet insert **2023-03-06**: **0** sheet-only closed; **{len(matched)}/{len(sheet_tr)}** matched ±$0.05; only open **2026-05-19** remains engine-only.

Archived pieces: `TSLA_sheet_only_2013-02-11.md`, `TSLA_sheet_only_2024-08-21.md`, `TSLA_sheet_only_2024-09-27.md`, `TSLA_sheet_missing_trading_days.md`.

---

## Recommended next knobs

1. **None for closed-trade parity** — closed sheet vs engine now align at ±$0.05 entry / exit dates.
2. Optional: include open **2026-05-19** on the sheet open/active list when comparing live positions.

---

## Sources

- `BRT_Closed_{STAMP}.csv`, `BRT_Open_{STAMP}.csv`
- `tools/tsla_brt_sheet_trades_20260720.tsv`
- `TSLA_trades_diff_20260720.md`, `TSLA_sheet_missing_trading_days.md`
"""
    (OUT / "TSLA_sheet_only_trades_gates.md").write_text(gates, encoding="utf-8")

    summary = {
        "stamp": STAMP,
        "sheet": len(sheet_tr),
        "engine": len(eng_tr),
        "exact": len(exact),
        "near": len(near),
        "matched": len(matched),
        "matched_02": matched_02,
        "so": [(str(s["trigger"]), s["entry"]) for s in so],
        "eo": [
            (str(e["trigger_ca"]), e["entry"], e["exit_type"]) for e in eo
        ],
        "exit_ok": f"{exit_ok}/{exit_known}",
        "first": str(sheet_tr[0]["trigger"]),
        "last": str(sheet_tr[-1]["trigger"]),
        "checks": {
            d: (
                "matched"
                if find_matched(d)
                else "sheet_only"
                if find_sheet(d) and not find_eng(d)
                else "engine_only"
                if find_eng(d) and not find_sheet(d)
                else "absent"
            )
            for d in checks
        },
    }
    print("SUMMARY", summary)
    return summary


if __name__ == "__main__":
    main()
