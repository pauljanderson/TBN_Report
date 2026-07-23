#!/usr/bin/env python3
"""MarkTen board-wide trade↔BO parent linkage reconcile (additive to exit match).

Uses existing sheet dumps under drive/brt_sheet_reconcile/ plus engine Closed /
breakout CSVs. Parallelized per symbol.

Writes:
  - {SYM}_bo_parent_trades_match_detail.csv
  - {SYM}_bo_parent_reconcile_summary.md
  - MARKTEN_bo_parent_issues_summary.md
"""
from __future__ import annotations

import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
DRIVE = ROOT / "drive"
sys.path.insert(0, str(OUT))

from bo_parent_check import (  # noqa: E402
    DEFAULT_STOP_PCT,
    annotate_trade_match,
    index_sheet_bos_by_retest,
    parse_date,
    parse_money,
    within,
)

MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
ZONE_LOW_STAMP = "260721155448"
ENTRY_TOL = 0.05
EXIT_PX_TOL = 0.05

# Prefer documented deep-reconcile stamps (trigger_low / sheet-match) when present.
DEEP_STAMPS = {
    "AAPL": "260720143523",
    "AMZN": "260720185855",
    "GOOGL": "260720143523",
    "META": "260721152701",
    "MSFT": "260720143523",
    "NVDA": "260720194240",
    "TSLA": "260720111055",
    "AU": "260720215017",
    "AMD": "260720165857",
    "NFLX": "260720183518",
}


def load_sheet_trades(sym: str, prefer_zone_low: bool) -> tuple[list[dict], str]:
    zl = OUT / f"{sym}_zone_low_sheet_trades.csv"
    st = OUT / f"{sym}_sheet_trades.csv"
    tsv = OUT / f"{sym.lower()}_brt_sheet_trades.tsv"
    # TSLA extras
    tsv_auth = OUT / "tsla_brt_sheet_trades_authoritative_paste.tsv"
    paths: list[Path] = []
    if prefer_zone_low and zl.exists():
        paths = [zl]
    else:
        for p in (st, tsv, tsv_auth if sym == "TSLA" else None, zl):
            if p and p.exists():
                paths.append(p)
                break
    if not paths:
        return [], "missing"
    path = paths[0]
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        header = sample.splitlines()[0] if sample else ""
        # Sniff: prefer tab when header is TSV even if extension is .csv
        delim = "\t" if "\t" in header else ","
        reader = csv.DictReader(f, delimiter=delim)
        for r in reader:
            keys = {k.lower().strip(): k for k in r.keys() if k}
            def g(*names):
                for n in names:
                    k = keys.get(n.lower())
                    if k is not None and str(r.get(k) or "").strip():
                        return r[k]
                return None

            trig = parse_date(g("Trigger Date", "trigger", "trigger date"))
            entry = parse_money(g("Entry Price", "entry", "entry price"))
            if trig is None or entry is None:
                continue
            rows.append(
                {
                    "trigger": trig,
                    "entry": entry,
                    "exit_date": parse_date(g("Exit Date", "exit", "exit date")),
                    "exit_price": parse_money(g("Exit Price", "exit price", "exit_px")),
                    "pnl_pct": parse_money(g("Profit %", "pnl%", "pnl_pct", "Profit %")),
                    "result": (g("Result", "result") or "").strip(),
                }
            )
    return rows, path.name


def load_sheet_bos(sym: str, prefer_zone_low: bool = False) -> tuple[list[dict], str]:
    candidates = [
        OUT / f"{sym}_zone_low_sheet_breakouts.csv" if prefer_zone_low else None,
        OUT / f"{sym}_sheet_breakouts.csv",
        OUT / "TSLA_sheet_breakout_retest.csv" if sym == "TSLA" else None,
        OUT / f"{sym}_breakout_match_detail.csv",
    ]
    for path in candidates:
        if path is None or not path.exists():
            continue
        rows = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            # reconstructed from match detail
            if "sheet_bo_date" in fields:
                for r in reader:
                    if (r.get("status") or "").startswith("sheet_only") or not (r.get("sheet_bo_date") or "").strip():
                        # still include sheet_only rows for parent join
                        pass
                    rows.append(
                        {
                            "Breakout Date": r.get("sheet_bo_date"),
                            "Zone Lower": r.get("sheet_lo"),
                            "Zone Upper": r.get("sheet_hi"),
                            "Retest Date": r.get("sheet_retest"),
                        }
                    )
                # also include sheet_only from same file if present with sheet cols
                return rows, path.name
            for r in reader:
                rows.append(dict(r))
        return rows, path.name
    return [], "missing"


def load_engine_trades(sym: str, stamp: str) -> list[dict]:
    rows = []
    for path, is_open in (
        (DRIVE / f"BRT_Closed_{stamp}.csv", False),
        (DRIVE / f"BRT_Open_{stamp}.csv", True),
    ):
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").strip().upper() != sym:
                    continue
                ca = parse_date(r.get("CLOSE_ABOVE_DATE"))
                op = parse_date(r.get("DATE_OPENED"))
                entry = parse_money(r.get("ENTRY_PRICE"))
                if entry is None:
                    continue
                rows.append(
                    {
                        "trigger_ca": ca,
                        "open": op,
                        "entry": entry,
                        "exit_date": parse_date(r.get("DATE_CLOSED")),
                        "exit_price": parse_money(r.get("EXIT_PRICE")),
                        "exit_type": (r.get("EXIT_TYPE") or ("OPEN" if is_open else "")).strip(),
                        "pnl_pct": parse_money(str(r.get("PNL_PCT") or "").replace("%", "")),
                        "stop": parse_money(r.get("STOP_PRICE")),
                        "target": parse_money(r.get("TARGET_PRICE")),
                        "breakout": parse_date(r.get("BREAKOUT_DATE")),
                        "zone_center": parse_money(r.get("ZONE_CENTER")),
                        "is_open": is_open,
                    }
                )
    return rows


def load_engine_bos(sym: str, stamp: str) -> list[dict]:
    path = DRIVE / f"BRT_breakout_and_retest_{stamp}.csv"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("SYMBOL") or "").strip().upper() != sym:
                continue
            out.append(dict(r))
    return out


def trigger_ok(sheet_trig, eng, tol_days=1):
    cands = []
    if eng.get("trigger_ca") is not None:
        cands.append(("ca", abs((eng["trigger_ca"] - sheet_trig).days)))
    if eng.get("open") is not None:
        cands.append(("open", abs((eng["open"] - sheet_trig).days)))
    if not cands:
        return False, None, None
    best = min(cands, key=lambda x: x[1])
    return best[1] <= tol_days, best[0], best[1]


def parse_layer_counts(sym: str) -> dict:
    """Pull zone/BO/trade counts from existing reconcile summary if present."""
    out = {"zones": None, "breakouts": None, "trades": None}
    for name in (f"{sym}_zone_low_reconcile_summary.md", f"{sym}_reconcile_summary.md"):
        path = OUT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # Match table rows like: | Zones ... | n | n | **m** | so | eo |
        for layer, key in (("Zones", "zones"), ("Breakouts", "breakouts"), ("Trades", "trades")):
            m = re.search(
                rf"\|\s*{layer}[^\|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*\*??\*?(\d+)\*?\*?\s*\|\s*(\d+)\s*\|\s*(\d+)",
                text,
                re.I,
            )
            if m:
                out[key] = {
                    "sheet": int(m.group(1)),
                    "engine": int(m.group(2)),
                    "matched": int(m.group(3)),
                    "sheet_only": int(m.group(4)),
                    "eng_only": int(m.group(5)),
                    "source": name,
                }
    return out


def match_trades(sheet, eng):
    used = set()
    matched = []
    sheet_only = []
    for s in sheet:
        hit = None
        kind = None
        best = None
        best_score = None
        for ei, e in enumerate(eng):
            if ei in used:
                continue
            tok, _, _ = trigger_ok(s["trigger"], e)
            if not tok:
                continue
            if abs(s["entry"] - e["entry"]) < 1e-9:
                hit, kind = ei, "exact"
                break
            if within(s["entry"], e["entry"], ENTRY_TOL):
                score = abs(s["entry"] - e["entry"])
                if best_score is None or score < best_score:
                    best, best_score = ei, score
        if hit is None and best is not None:
            hit, kind = best, "near"
        if hit is None:
            sheet_only.append(s)
            continue
        used.add(hit)
        e = eng[hit]
        ed = s["exit_date"] == e["exit_date"] if s["exit_date"] and e["exit_date"] else None
        ep = (
            within(s["exit_price"], e["exit_price"], EXIT_PX_TOL)
            if s["exit_price"] is not None and e["exit_price"] is not None
            else None
        )
        matched.append({"sheet": s, "engine": e, "kind": kind, "exit_date_match": ed, "exit_px_match": ep})
    eng_only = [eng[i] for i in range(len(eng)) if i not in used]
    return matched, sheet_only, eng_only


def reconcile_one(sym: str, mode: str) -> dict:
    """mode: zone_low | deep"""
    prefer_zl = mode == "zone_low"
    stamp = ZONE_LOW_STAMP if mode == "zone_low" else DEEP_STAMPS.get(sym, ZONE_LOW_STAMP)
    check_stop = mode == "zone_low"

    sheet, sheet_src = load_sheet_trades(sym, prefer_zone_low=prefer_zl)
    if mode == "zone_low" and sheet_src == "missing":
        return {"sym": sym, "mode": mode, "skipped": True, "reason": "no zone_low sheet trades"}
    if not sheet:
        # deep mode: try any trades
        sheet, sheet_src = load_sheet_trades(sym, prefer_zone_low=False)
    bos, bo_src = load_sheet_bos(sym, prefer_zone_low=prefer_zl)
    eng = load_engine_trades(sym, stamp)
    if not eng and mode == "deep":
        # fallback to zone_low stamp closed if deep stamp missing
        stamp = ZONE_LOW_STAMP
        eng = load_engine_trades(sym, stamp)
    eng_bos = load_engine_bos(sym, stamp)
    bos_idx = index_sheet_bos_by_retest(bos)

    matched, sheet_only, eng_only = match_trades(sheet, eng)

    annotated = []
    for m in matched:
        s, e = m["sheet"], m["engine"]
        ann = annotate_trade_match(
            sheet_trigger=s["trigger"],
            eng_breakout_date=e.get("breakout"),
            eng_stop=e.get("stop"),
            eng_ca=e.get("trigger_ca") or e.get("open"),
            sheet_bos_by_retest=bos_idx,
            eng_bos=eng_bos,
            exit_date_match=m["exit_date_match"],
            exit_px_match=m["exit_px_match"],
            stop_pct=DEFAULT_STOP_PCT,
            check_stop=check_stop,
        )
        annotated.append({**m, "ann": ann})

    # counts
    counts = {
        "bo_parent_mismatch": sum(1 for a in annotated if "BO_PARENT_MISMATCH" in a["ann"]["status_flags"]),
        "zone_mismatch": sum(1 for a in annotated if "ZONE_MISMATCH" in a["ann"]["status_flags"]),
        "exit_fork": sum(1 for a in annotated if a["ann"]["exit_status"] == "EXIT_FORK"),
        "full": sum(1 for a in annotated if a["ann"]["exit_status"] == "FULL" and a["ann"]["bo_parent_status"] == "OK"),
        "ambiguous": sum(1 for a in annotated if a["ann"]["bo_parent_status"] == "AMBIGUOUS"),
        "missing_sheet_bo": sum(1 for a in annotated if a["ann"]["bo_parent_status"] == "MISSING_SHEET_BO"),
        "sheet_only": len(sheet_only),
        "eng_only": len(eng_only),
        "matched": len(matched),
        "sheet_n": len(sheet),
        "eng_n": len(eng),
    }

    # detail csv
    detail_path = OUT / f"{sym}_bo_parent_trades_match_detail.csv"
    if mode == "zone_low":
        detail_path = OUT / f"{sym}_zone_low_bo_parent_trades_match_detail.csv"
    with detail_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "exit_status",
                "bo_parent_status",
                "status_flags",
                "match_kind",
                "sheet_trigger",
                "sheet_entry",
                "sheet_exit",
                "sheet_exit_px",
                "eng_ca",
                "eng_entry",
                "eng_exit",
                "eng_exit_px",
                "eng_exit_type",
                "eng_stop",
                "bo_select_note",
                "n_sheet_bo_cands",
                "sheet_parent_bo_date",
                "sheet_parent_zone_lower",
                "eng_breakout_date",
                "eng_zone_lower",
                "bo_date_match",
                "zone_lower_match",
                "stop_match",
                "implied_sheet_stop",
            ]
        )
        for a in annotated:
            s, e, ann = a["sheet"], a["engine"], a["ann"]
            w.writerow(
                [
                    ann["exit_status"],
                    ann["bo_parent_status"],
                    ann["status_flags"],
                    a["kind"],
                    s["trigger"],
                    f"{s['entry']:.4f}",
                    s["exit_date"],
                    f"{s['exit_price']:.4f}" if s["exit_price"] is not None else "",
                    e["trigger_ca"],
                    f"{e['entry']:.4f}",
                    e["exit_date"],
                    f"{e['exit_price']:.4f}" if e["exit_price"] is not None else "",
                    e["exit_type"],
                    f"{e['stop']:.4f}" if e["stop"] is not None else "",
                    ann["bo_select_note"],
                    ann["n_sheet_bo_cands"],
                    ann["sheet_parent_bo_date"],
                    f"{ann['sheet_parent_zone_lower']:.4f}" if ann["sheet_parent_zone_lower"] is not None else "",
                    ann["eng_breakout_date"],
                    f"{ann['eng_zone_lower']:.4f}" if ann["eng_zone_lower"] is not None else "",
                    ann["bo_date_match"],
                    ann["zone_lower_match"],
                    ann["stop_match"],
                    f"{ann['implied_sheet_stop']:.4f}" if ann["implied_sheet_stop"] is not None else "",
                ]
            )
        for s in sheet_only:
            w.writerow(["SHEET_ONLY", "", "SHEET_ONLY", "", s["trigger"], f"{s['entry']:.4f}", s["exit_date"], "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
        for e in eng_only:
            w.writerow(
                [
                    "ENG_ONLY",
                    "",
                    "ENG_ONLY",
                    "",
                    "",
                    "",
                    "",
                    "",
                    e["trigger_ca"],
                    f"{e['entry']:.4f}",
                    e["exit_date"],
                    f"{e['exit_price']:.4f}" if e["exit_price"] is not None else "",
                    e["exit_type"],
                    f"{e['stop']:.4f}" if e["stop"] is not None else "",
                    "",
                    "",
                    "",
                    "",
                    e.get("breakout"),
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )

    layers = parse_layer_counts(sym)
    issues = []
    for a in annotated:
        ann = a["ann"]
        if ann["bo_parent_status"] in ("OK",) and ann["exit_status"] == "FULL":
            continue
        if ann["exit_status"] == "FULL" and ann["bo_parent_status"] == "OK":
            continue
        interesting = ann["exit_status"] != "FULL" or ann["bo_parent_status"] not in ("OK", "MISSING_SHEET_BO")
        # always keep BO mismatches and exit forks
        if (
            "BO_PARENT_MISMATCH" in ann["status_flags"]
            or "ZONE_MISMATCH" in ann["status_flags"]
            or ann["exit_status"] == "EXIT_FORK"
            or ann["bo_parent_status"] == "AMBIGUOUS"
        ):
            s, e = a["sheet"], a["engine"]
            issues.append(
                {
                    "trigger": str(s["trigger"]),
                    "entry": s["entry"],
                    "flags": ann["status_flags"],
                    "sheet_bo": str(ann["sheet_parent_bo_date"]),
                    "sheet_lo": ann["sheet_parent_zone_lower"],
                    "eng_bo": str(ann["eng_breakout_date"]),
                    "eng_lo": ann["eng_zone_lower"],
                    "sheet_exit": str(s["exit_date"]),
                    "eng_exit": str(e["exit_date"]),
                }
            )

    # summary md
    sum_path = OUT / (f"{sym}_zone_low_bo_parent_reconcile_summary.md" if mode == "zone_low" else f"{sym}_bo_parent_reconcile_summary.md")
    lines = [
        f"# {sym} trade↔BO parent reconcile ({mode})",
        "",
        f"- Sheet trades: `{sheet_src}` (n={len(sheet)})",
        f"- Sheet BOs: `{bo_src}` (n={len(bos)})",
        f"- Engine stamp: **{stamp}** (closed+open; BO table if present)",
        f"- stop check: {'yes (zone_low stop_pct=' + str(DEFAULT_STOP_PCT) + ')' if check_stop else 'no (deep/trigger_low — zone from eng BO table)'}",
        "- Match key: trigger ±1d of CA/open, entry ±$0.05; **then** BO parent via Retest Date == Trigger Date",
        "- Multi-BO policy: prefer BO matching engine BREAKOUT_DATE; else AMBIGUOUS",
        "",
        "## Counts",
        "",
        f"| matched | sheet-only | eng-only | FULL+BO_OK | EXIT_FORK | BO_PARENT_MISMATCH | ZONE_MISMATCH | AMBIGUOUS | MISSING_SHEET_BO |",
        f"|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {counts['matched']} | {counts['sheet_only']} | {counts['eng_only']} | {counts['full']} | {counts['exit_fork']} | {counts['bo_parent_mismatch']} | {counts['zone_mismatch']} | {counts['ambiguous']} | {counts['missing_sheet_bo']} |",
        "",
    ]
    if layers.get("zones") or layers.get("breakouts"):
        lines += ["## Prior layer counts (from existing summaries)", ""]
        for k in ("zones", "breakouts", "trades"):
            v = layers.get(k)
            if v:
                lines.append(
                    f"- {k}: sheet {v['sheet']} / eng {v['engine']} / matched {v['matched']} / so {v['sheet_only']} / eo {v['eng_only']} (`{v['source']}`)"
                )
        lines.append("")

    if issues:
        lines += [
            "## Issue trades",
            "",
            "| trigger | entry | flags | sheet BO | sheet lo | eng BO | eng lo | sheet exit | eng exit |",
            "|---|---:|---|---|---:|---|---:|---|---|",
        ]
        for it in issues:
            slo = f"{it['sheet_lo']:.4f}" if it["sheet_lo"] is not None else ""
            elo = f"{it['eng_lo']:.4f}" if it["eng_lo"] is not None else ""
            lines.append(
                f"| {it['trigger']} | {it['entry']:.2f} | `{it['flags']}` | {it['sheet_bo']} | {slo} | {it['eng_bo']} | {elo} | {it['sheet_exit']} | {it['eng_exit']} |"
            )
        lines.append("")
    else:
        lines += ["## Issue trades", "", "(none)", ""]

    # canonical META highlight
    if sym == "META":
        jul = next((a for a in annotated if str(a["sheet"]["trigger"]) == "2023-07-11"), None)
        lines += ["## Canonical check: META 2023-07-11", ""]
        if jul:
            ann = jul["ann"]
            lines += [
                f"- status_flags: `{ann['status_flags']}`",
                f"- sheet parent BO: {ann['sheet_parent_bo_date']} zone_lower={ann['sheet_parent_zone_lower']}",
                f"- eng BREAKOUT_DATE: {ann['eng_breakout_date']} zone_lower={ann['eng_zone_lower']}",
                f"- BO_PARENT_MISMATCH lit: **{'YES' if 'BO_PARENT_MISMATCH' in ann['status_flags'] else 'NO'}**",
                "",
            ]
        else:
            lines += ["- 2023-07-11 matched trade **not found** in this mode", ""]

    lines += [
        "## Artifacts",
        "",
        f"- `{detail_path.name}`",
        f"- `{sum_path.name}`",
        "",
    ]
    sum_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "sym": sym,
        "mode": mode,
        "skipped": False,
        "stamp": stamp,
        "sheet_src": sheet_src,
        "bo_src": bo_src,
        "counts": counts,
        "issues": issues,
        "layers": layers,
        "detail": str(detail_path),
        "summary": str(sum_path),
        "meta_711_flags": next(
            (a["ann"]["status_flags"] for a in annotated if str(a["sheet"]["trigger"]) == "2023-07-11"),
            None,
        )
        if sym == "META"
        else None,
    }


def run_symbol(sym: str) -> list[dict]:
    results = []
    # Always run deep linkage against prior sheet dumps when trades+BOs exist
    results.append(reconcile_one(sym, "deep"))
    # Zone_low when sheet zone_low trades exist
    zl = OUT / f"{sym}_zone_low_sheet_trades.csv"
    if zl.exists():
        results.append(reconcile_one(sym, "zone_low"))
    return results


def main() -> None:
    all_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(10, len(MARKTEN))) as ex:
        futs = {ex.submit(run_symbol, s): s for s in MARKTEN}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                res = fut.result()
                all_results.extend(res)
                print(f"OK {sym}: {len(res)} mode(s)")
            except Exception as e:
                print(f"FAIL {sym}: {e}")
                all_results.append({"sym": sym, "mode": "error", "skipped": True, "reason": str(e)})

    # board summary
    lines = [
        "# MarkTen trade↔BO parent issues summary",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Helper: `drive/brt_sheet_reconcile/bo_parent_check.py`",
        f"- Zone_low stamp: `{ZONE_LOW_STAMP}`; deep stamps: per-symbol (see details)",
        "- Additive flags: `EXIT_FORK` preserved; `BO_PARENT_MISMATCH` / `ZONE_MISMATCH` added",
        "",
        "## Board table",
        "",
        "| Symbol | Mode | Matched | Sheet-only | Eng-only | EXIT_FORK | BO_PARENT_MISMATCH | ZONE_MISMATCH | AMBIGUOUS | Notes |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    all_results.sort(key=lambda r: (r.get("sym") or "", r.get("mode") or ""))
    for r in all_results:
        if r.get("skipped"):
            lines.append(f"| {r.get('sym')} | {r.get('mode')} | — | — | — | — | — | — | — | skipped: {r.get('reason')} |")
            continue
        c = r["counts"]
        note = ""
        if r["sym"] == "META" and r.get("meta_711_flags"):
            note = f"META 7/11 → `{r['meta_711_flags']}`"
        elif c["bo_parent_mismatch"]:
            note = f"{c['bo_parent_mismatch']} BO parent mismatch(es)"
        lines.append(
            f"| {r['sym']} | {r['mode']} | {c['matched']} | {c['sheet_only']} | {c['eng_only']} | "
            f"{c['exit_fork']} | {c['bo_parent_mismatch']} | {c['zone_mismatch']} | {c['ambiguous']} | {note} |"
        )

    # META canonical
    meta_zl = next((r for r in all_results if r.get("sym") == "META" and r.get("mode") == "zone_low" and not r.get("skipped")), None)
    lines += ["", "## Canonical: META 2023-07-11 (zone_low)", ""]
    if meta_zl and meta_zl.get("meta_711_flags"):
        lit = "BO_PARENT_MISMATCH" in meta_zl["meta_711_flags"]
        lines += [
            f"- Flags: `{meta_zl['meta_711_flags']}`",
            f"- BO_PARENT_MISMATCH lit: **{'YES' if lit else 'NO'}**",
            "- Expected: sheet parent BO `2022-01-31` zone `$299.98` vs eng BO `2023-07-05` zone `~$282.37`",
            "",
        ]
    else:
        lines += ["- zone_low META result missing", ""]

    # themes
    lines += ["## Board-wide themes", ""]
    bpm = [(r["sym"], r["mode"], r["counts"]["bo_parent_mismatch"]) for r in all_results if not r.get("skipped") and r["counts"]["bo_parent_mismatch"]]
    znm = [(r["sym"], r["mode"], r["counts"]["zone_mismatch"]) for r in all_results if not r.get("skipped") and r["counts"]["zone_mismatch"]]
    exf = [(r["sym"], r["mode"], r["counts"]["exit_fork"]) for r in all_results if not r.get("skipped") and r["counts"]["exit_fork"]]
    if bpm:
        lines.append("- **BO_PARENT_MISMATCH** (same CA/entry, different parent BO date) seen in: " + ", ".join(f"{s}/{m}×{n}" for s, m, n in bpm))
    else:
        lines.append("- No BO_PARENT_MISMATCH outside empty runs.")
    if znm:
        lines.append("- **ZONE_MISMATCH** (parent zone_lower ±$0.02 fail): " + ", ".join(f"{s}/{m}×{n}" for s, m, n in znm))
    if exf:
        lines.append("- **EXIT_FORK** still present (unchanged layer): " + ", ".join(f"{s}/{m}×{n}" for s, m, n in exf))
    lines += [
        "",
        "- Gap class: trade match on trigger+entry alone can hide sheet vs engine picking **different BO/zone parents** that share a retest/CA date (META 7/11 is the prototype).",
        "- Where sheet BO dumps are missing (e.g. AAPL reconstructed from breakout_match_detail), MISSING_SHEET_BO may inflate until a full BO paste is available.",
        "",
        "## Artifact paths",
        "",
    ]
    for r in all_results:
        if r.get("summary"):
            lines.append(f"- `{Path(r['summary']).name}` / `{Path(r['detail']).name}`")
    lines.append("- `MARKTEN_bo_parent_issues_summary.md` (this file)")
    lines.append("")

    out = OUT / "MARKTEN_bo_parent_issues_summary.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")

    # console META confirm
    if meta_zl:
        print("META 7/11 flags:", meta_zl.get("meta_711_flags"))


if __name__ == "__main__":
    main()
