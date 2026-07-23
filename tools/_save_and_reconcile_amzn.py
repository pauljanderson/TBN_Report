#!/usr/bin/env python3
"""Save AMZN breakout/trade paste and reconcile vs variant C 2016 stamp."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
sys.path.insert(0, str(REPO / "tools"))
from _variantC_2016_wpbr_reconcile import (  # noqa: E402
    BASE,
    DATA,
    MARKTEN,
    STAMP,
    analyze,
    build_eng,
    confirm_variant_c,
    has_paste,
    load_sheet_zones,
)

DONE = {"AU", "NVDA", "NFLX", "AMZN"}


def find_amzn_line() -> int:
    hits = []
    with TRANSCRIPT.open(encoding="utf-8", errors="ignore") as fh:
        for i, line in enumerate(fh, 1):
            if "29.69" in line and "28.81" in line and "AMZN" in line:
                hits.append(i)
            elif "236.50" in line and "229.51" in line and "AMZN" in line:
                hits.append(i)
    # prefer latest user line that is breakout-only (not huge OHLC paste)
    for line_no in reversed(hits):
        body = extract_user_body(line_no)
        if body is None:
            continue
        if "Break out upper" in body and "Entry Date" in body and "29.69" in body:
            # skip full OHLC dumps
            if body.lstrip().startswith("AMZN") and "Date\tOpen\tHigh" not in body[:200]:
                return line_no
            if "Break out upper" in body[:500]:
                return line_no
    if hits:
        return hits[-1]
    raise SystemExit("AMZN paste not found")


def extract_user_body(line_no: int) -> str | None:
    with TRANSCRIPT.open(encoding="utf-8", errors="ignore") as fh:
        for i, line in enumerate(fh, 1):
            if i != line_no:
                continue
            obj = json.loads(line)
            if obj.get("role") != "user":
                return None
            c = obj["message"]["content"]
            if isinstance(c, list):
                text = "".join(
                    x.get("text", "") if isinstance(x, dict) else str(x) for x in c
                )
            else:
                text = c
            m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", text, re.S)
            return (m.group(1) if m else text).strip()
    return None


def save_zones_trades(sym: str, body: str) -> None:
    b = body.find("Break out upper")
    if b < 0:
        raise SystemExit(f"{sym}: no Break out upper")
    body = body[b:]
    ei = body.find("Entry Date")
    if ei < 0:
        raise SystemExit(f"{sym}: no Entry Date")
    zones = body[:ei].rstrip() + "\n"
    trades = body[ei:].rstrip() + "\n"
    out = BASE / sym
    out.mkdir(parents=True, exist_ok=True)
    (out / "_raw_user_paste.txt").write_text(body, encoding="utf-8")
    (out / "zones.tsv").write_text(zones, encoding="utf-8")
    (out / "sheet_zones.tsv").write_text(zones, encoding="utf-8")
    (out / "trades.tsv").write_text(trades, encoding="utf-8")
    (out / "sheet_trades.tsv").write_text(trades, encoding="utf-8")
    zr = len([ln for ln in zones.splitlines()[1:] if ln.strip()])
    tr = len([ln for ln in trades.splitlines()[1:] if ln.strip()])
    print(f"saved {sym}: zones={zr} trades={tr}")


def amzn_focus_notes() -> list[str]:
    import pandas as pd

    notes = []
    df = pd.read_csv(DATA / "AMZN.csv", index_col=0, parse_dates=True)
    eng_all, _ = build_eng(df)
    sheet_z = load_sheet_zones(BASE / "AMZN")
    target = None
    for z in sheet_z:
        if z.get("zhigh") == 236.5 or (
            z.get("zhigh") is not None and abs(float(z["zhigh"]) - 236.5) < 1e-9
        ):
            target = z
            break
        if (z.get("pivot") or "").startswith("2024-12"):
            target = z
            break
    if not target:
        notes.append("Could not locate ~2024-12-16 / zh=236.50 pivot in sheet paste")
        return notes
    e = eng_all.get(target["pivot"])
    notes.append(
        f"Sheet focus pivot `{target['pivot']}`: z=({target['zlow']},{target['zhigh']}) "
        f"retest `{target['retest']}` rocket `{target['rocket']}`"
    )
    if e:
        zh_ok = abs(e["zhigh"] - 236.5) <= 0.02
        rt_ok = e["retest"] == "2025-11-13"
        notes.append(
            f"Engine under C: z=({e['zlow']},{e['zhigh']}) retest `{e['retest']}` "
            f"signal `{e['signal']}` — zh==236.50 {'YES' if zh_ok else 'NO'}, "
            f"retest==2025-11-13 {'YES' if rt_ok else 'NO'}"
        )
        notes.append(
            f"Sheet vs eng: zh sheet={target['zhigh']} eng={e['zhigh']}; "
            f"retest sheet={target['retest']} eng={e['retest']}"
        )
    else:
        notes.append(f"Engine missing pivot `{target['pivot']}`")
    return notes


def write_ticker_status(sym: str, r: dict, vc: dict, extra_notes: list[str] | None = None) -> Path:
    fair = r["fair"]
    lines: list[str] = []
    lines.append(f"# {sym} WPBR Sheet <-> Engine Reconcile (variant C, start_date=2016-01-01)")
    lines.append("")
    lines.append(
        f"**Engine stamp:** `{STAMP}` — "
        f"`drive/wpbr_sheet_reconcile/_markten_variantC_2016_20260722134127/`"
    )
    lines.append(
        "**Settings:** variant C `_round_bounds` (HALF_UP pivot then band), "
        "`retest_mode=stop_looking`, `start_date=2016-01-01`, `target_pct=1.22`, `stop_pct=0.89`."
    )
    lines.append(
        "**Paste:** breakout/retest/rocket + trades only (OHLC/weekly skipped). "
        "Sheet 2019 rocket gate removed."
    )
    lines.append("")
    lines.append("## Variant C")
    lines.append("")
    s = vc["sample_100_125_band_1_5pct"]
    e = vc["expected"]
    lines.append(
        f"- Confirmed HALF_UP pivot then band; sample tp/zl/zh={s['tp']}/{s['zl']}/{s['zh']} "
        f"(expected {e['tp']}/{e['zl']}/{e['zh']}) -> **{'PASS' if s == e else 'FAIL'}**"
    )
    lines.append("")
    lines.append("## Structure (>=2016 pivots)")
    lines.append("")
    lines.append("| Check | Result |")
    lines.append("|---|---|")
    lines.append(
        f"| Sheet zones (>=2016 / all) | **{r['n_sheet_zones_ge2016']}** / {r['n_sheet_zones_all']} |"
    )
    lines.append(f"| Pivots match | **{fair['pivots_match']}** |")
    lines.append(f"| Zones (bounds+BO) | **{fair['zones_ok']}** |")
    lines.append(f"| Retest | **{fair['retest_ok']}** |")
    lines.append(f"| Rocket where sheet fires | **{fair['rocket_where_sheet_fires']}** |")
    lines.append(f"| Rocket pairs (incl blanks) | **{fair['rocket_ok_pairs']}** |")
    lines.append(
        f"| Eng-only rockets (sheet blank) | **{fair['n_eng_only_rockets']}** "
        f"(sig <2019: {fair['n_eng_only_pre2019_signal']}) |"
    )
    lines.append("")
    if r["retest_mismatches"]:
        lines.append("### Retest mismatches")
        lines.append("")
        for m in r["retest_mismatches"]:
            lines.append(
                f"- pivot `{m['pivot']}` sheet `{m['sheet_retest']}` vs eng `{m['eng_retest']}` "
                f"z=({m['zlow']},{m['zhigh']})"
            )
        lines.append("")
    if fair["eng_only_rockets"]:
        lines.append("### Eng-only rockets (sheet blank)")
        lines.append("")
        for er in fair["eng_only_rockets"][:20]:
            lines.append(
                f"- pivot `{er['pivot']}` signal `{er['eng_signal']}` fill `{er['eng_fill']}`"
            )
        lines.append("")
    lines.append("## Trades (>=2016)")
    lines.append("")
    lines.append("| Metric | Result |")
    lines.append("|---|---|")
    lines.append(
        f"| Sheet trades (>=2016 / all) | **{r['n_sheet_trades_ge2016']}** / {r['n_sheet_trades_all']} |"
    )
    lines.append(f"| Raw fills | **{r['raw']}** |")
    lines.append(f"| Serialized (this stamp) | **{r['ser']}** |")
    lines.append(
        f"| Engine closed+open | **{r['closed_n']}** "
        f"(2016-18: {r['closed_2016_2018_n']}; pre-2016: {r['closed_pre2016_n']}) |"
    )
    lines.append("")
    if r["orphans"]:
        lines.append(f"**Orphans (sheet not in eng raw):** {len(r['orphans'])}")
        for o in r["orphans"]:
            lines.append(f"- `{o}`")
        lines.append("")
    lines.append("| Entry | Raw | Ser |")
    lines.append("|---|---|---|")
    for t in r["trade_rows"]:
        lines.append(
            f"| `{t['entry']}` | {'YES' if t['raw'] else 'no'} | {'YES' if t['ser'] else 'no'} |"
        )
    lines.append("")
    if extra_notes:
        lines.append("## Focus / notes")
        lines.append("")
        for n in extra_notes:
            lines.append(f"- {n}")
        lines.append("")
    outp = BASE / sym / f"{sym}_wpbr_reconcile_status.md"
    outp.write_text("\n".join(lines), encoding="utf-8")
    (BASE / sym / "_reconcile_summary.json").write_text(
        json.dumps(
            {
                "stamp": STAMP,
                "raw": r["raw"],
                "ser": r["ser"],
                "pivots": fair["pivots_match"],
                "zones": fair["zones_ok"],
                "retest": fair["retest_ok"],
                "rocket_where_sheet": fair["rocket_where_sheet_fires"],
                "eng_only": fair["n_eng_only_rockets"],
                "closed_n": r["closed_n"],
                "orphans": r["orphans"],
                "retest_mismatches": r["retest_mismatches"],
                "trade_rows": r["trade_rows"],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"wrote {outp}")
    return outp


def load_prior_summary(sym: str) -> dict | None:
    p = BASE / sym / "_reconcile_summary.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def update_markten_status(results: dict[str, dict], vc: dict, focus_notes: list[str]) -> Path:
    out = BASE / "VARIANT_C_2016_MARKTEN_STATUS.md"
    lines: list[str] = []
    lines.append("# WPBR MarkTen — variant C + start_date=2016-01-01")
    lines.append("")
    lines.append(
        "**Engine outdir:** `drive/wpbr_sheet_reconcile/_markten_variantC_2016_20260722134127/`"
    )
    lines.append(f"**Stamp:** `{STAMP}`")
    lines.append(
        "**Settings:** variant C `_round_bounds` (HALF_UP pivot then band), "
        "`retest_mode=stop_looking` (default), `start_date=2016-01-01`, "
        "`target_pct=1.22`, `stop_pct=0.89`, WPBR-only zones, growth off."
    )
    lines.append("")
    lines.append("## Variant C confirmation")
    lines.append("")
    s = vc["sample_100_125_band_1_5pct"]
    e = vc["expected"]
    lines.append(
        f"- `_round_bounds` Decimal HALF_UP: **{vc['has_HALF_UP']}** "
        f"(doc variant C: **{vc['doc_says_variant_C']}**)"
    )
    lines.append(
        f"- Sample `_round_bounds(100.125, 0.015, 2)` -> "
        f"{s['tp']}/{s['zl']}/{s['zh']} (expected {e['tp']}/{e['zl']}/{e['zh']}) -> "
        f"**{'PASS' if s == e else 'FAIL'}**"
    )
    lines.append("")
    lines.append("## Paste policy")
    lines.append("")
    lines.append(
        "User skips OHLC/weekly repastes (unchanged). Only breakout/retest/rocket + trades "
        "are refreshed. Sheet **1/1/2019 rocket gate removed**."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Reconciled vs this stamp (fresh pastes)")
    lines.append("")
    lines.append(
        "| Ticker | Pivots | Zones | Retest | Rocket (sheet fires) | Raw | Ser | Eng closed | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---:|---|")
    for sym in ("AU", "NVDA", "NFLX", "AMZN"):
        r = results[sym]
        if "fair" in r:
            fair = r["fair"]
            note = []
            if fair["retest_mismatches"]:
                note.append(f"{len(fair['retest_mismatches'])} retest miss")
            if r["orphans"]:
                note.append(f"{len(r['orphans'])} orphan(s)")
            if fair["n_eng_only_rockets"]:
                note.append(f"{fair['n_eng_only_rockets']} eng-only rocket(s)")
            lines.append(
                f"| {sym} | {fair['pivots_match']} | {fair['zones_ok']} | {fair['retest_ok']} | "
                f"{fair['rocket_where_sheet_fires']} | **{r['raw']}** | **{r['ser']}** | "
                f"{r['closed_n']} | {'; '.join(note) or 'OK'} |"
            )
        else:
            note_bits = []
            if r.get("orphans"):
                note_bits.append(f"{len(r['orphans'])} orphan(s)")
            if r.get("eng_only"):
                note_bits.append(f"{r['eng_only']} eng-only rocket(s)")
            lines.append(
                f"| {sym} | {r.get('pivots','?')} | {r.get('zones','?')} | {r.get('retest','?')} | "
                f"{r.get('rocket_where_sheet','?')} | **{r.get('raw','?')}** | "
                f"**{r.get('ser','?')}** | {r.get('closed_n','?')} | "
                f"{'; '.join(note_bits) or 'OK'} |"
            )
    lines.append("")
    lines.append("### NVDA focus (pivot ~2017-06-05)")
    lines.append("")
    lines.append("- zh **4.27**, retest **2017-09-25** under variant C (confirmed prior).")
    lines.append("")
    lines.append("### AMZN focus (pivot ~2024-12-16)")
    lines.append("")
    for n in focus_notes:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Paste checklist")
    lines.append("")
    lines.append("| Ticker | Status |")
    lines.append("|---|---|")
    remaining = []
    for s in MARKTEN:
        if s in DONE:
            lines.append(f"| {s} | **DONE** (breakout+trades reconciled vs `{STAMP}`) |")
        else:
            remaining.append(s)
            old = has_paste(s)
            lines.append(
                f"| {s} | **NEED breakout+trade repaste** "
                f"({'old paste present — replace' if old else 'no paste'}) |"
            )
    lines.append("")
    lines.append(f"**Remaining:** {', '.join(remaining)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Resume protocol")
    lines.append("")
    lines.append(
        f"On each new breakout+trade paste: save under `drive/wpbr_sheet_reconcile/<TICKER>/`, "
        f"reconcile that symbol only vs stamp `{STAMP}` "
        f"(`_markten_variantC_2016_20260722134127`), update this doc."
    )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(
        f"- Engine: `drive/wpbr_sheet_reconcile/_markten_variantC_2016_20260722134127/` (`{STAMP}`)"
    )
    lines.append("- Status: `drive/wpbr_sheet_reconcile/VARIANT_C_2016_MARKTEN_STATUS.md`")
    for s in ("AU", "NVDA", "NFLX", "AMZN"):
        lines.append(f"- {s}: `drive/wpbr_sheet_reconcile/{s}/{s}_wpbr_reconcile_status.md`")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return out


def main() -> int:
    # Confirm NFLX already done
    nflx_ok = (BASE / "NFLX" / "NFLX_wpbr_reconcile_status.md").is_file()
    print(f"NFLX already done: {nflx_ok}")

    line_no = find_amzn_line()
    print(f"AMZN transcript line: {line_no}")
    body = extract_user_body(line_no)
    if not body or "Break out upper" not in body:
        raise SystemExit("AMZN paste body invalid")
    save_zones_trades("AMZN", body)

    vc = confirm_variant_c()
    print("=== reconcile AMZN ===")
    r = analyze("AMZN")
    fair = r["fair"]
    print(
        f"  piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} "
        f"rocket {fair['rocket_where_sheet_fires']} raw {r['raw']} ser {r['ser']} "
        f"closed={r['closed_n']} eng_only={fair['n_eng_only_rockets']} orphans={r['orphans']}"
    )
    focus = amzn_focus_notes()
    for n in focus:
        print("  FOCUS:", n.encode("ascii", "replace").decode())

    write_ticker_status("AMZN", r, vc, extra_notes=focus)

    results = {
        "AU": load_prior_summary("AU") or {},
        "NVDA": load_prior_summary("NVDA") or {},
        "NFLX": load_prior_summary("NFLX") or {},
        "AMZN": r,
    }
    update_markten_status(results, vc, focus)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
