"""Reconcile AAPL sheet matured zones vs engine BRT_ZONES."""
from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT_DIR = ROOT / "drive" / "brt_sheet_reconcile"
TOOLS = ROOT / "tools"
ENGINE = ROOT / "drive" / "BRT_ZONES_AAPL_260720143523.csv"
WIN_START, WIN_END = "2010-01-04", "2026-06-05"
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)


def parse_money(s):
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    return round(float(s), 4)


def within(a, b, tol=0.02):
    return abs(a - b) <= tol + 1e-9


def near_match(s, candidates, tol=0.02):
    st, slo, shi = s
    same_touch = [c for c in candidates if within(st, c[0], tol)]
    pool = same_touch if same_touch else list(candidates)
    best = None
    best_score = None
    for c in pool:
        ct, clo, chi = c
        if within(st, ct, tol) and within(slo, clo, tol) and within(shi, chi, tol):
            score = (abs(st - ct), abs(slo - clo) + abs(shi - chi))
            if best_score is None or score < best_score:
                best = c
                best_score = score
    return best


def fmt(z):
    return f"${z[0]:.2f}/${z[1]:.2f}/${z[2]:.2f}"


def fmt4(z):
    return f"{z[0]:.4f}/{z[1]:.4f}/{z[2]:.4f}"


def extract_paste() -> str:
    lines = TRANSCRIPT.read_text(encoding="utf-8").splitlines()
    # 2026-07-20 16:45 AAPL paste (0-indexed line 728)
    obj = json.loads(lines[728])
    text = "".join(
        c.get("text", "")
        for c in obj["message"]["content"]
        if isinstance(c, dict) and c.get("type") == "text"
    )
    idx = text.find("Matured touch price")
    if idx < 0:
        raise SystemExit("Matured touch price header not found")
    end = -1
    for marker in ("Breakout Date", "Breakout date", "Breakouts", "Trade Date"):
        end = text.find(marker, idx + 1)
        if end > 0:
            break
    if end < 0:
        end = text.find("</user_query>", idx + 1)
    if end < 0:
        end = len(text)
    return text[idx:end].rstrip() + "\n"


def load_engine(path: Path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date = row.get("DATE") or row.get("MATURITY_DATE") or ""
            t = parse_money(row.get("TOUCH_PRICE") or row.get("ZONE_CENTER"))
            lo = parse_money(row.get("ZONE_LOW"))
            hi = parse_money(row.get("ZONE_HIGH"))
            if t is None or lo is None or hi is None:
                continue
            if date and not (WIN_START <= date <= WIN_END):
                continue
            rows.append({"date": date, "touch": t, "lower": lo, "upper": hi})
    unique: OrderedDict = OrderedDict()
    for e in rows:
        key = (e["touch"], e["lower"], e["upper"])
        if key not in unique:
            unique[key] = e
    return rows, unique


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)

    paste = extract_paste()
    tsv_path = TOOLS / "aapl_brt_sheet_zones.tsv"
    tsv_path.write_text(paste, encoding="utf-8")
    (TOOLS / "aapl_brt_sheet_zones.txt").write_text(paste, encoding="utf-8")
    print("wrote", tsv_path, "chars", len(paste), "lines", paste.count("\n"))

    raw_rows = []
    blank_rows = 0
    for ln in paste.splitlines()[1:]:
        parts = ln.split("\t")
        if len(parts) < 3:
            if not ln.strip():
                blank_rows += 1
            continue
        t, lo, hi = parse_money(parts[0]), parse_money(parts[1]), parse_money(parts[2])
        if t is None or lo is None or hi is None:
            blank_rows += 1
            continue
        raw_rows.append((t, lo, hi))
    unique_sheet = list(OrderedDict.fromkeys(raw_rows).keys())
    print(
        "sheet raw",
        len(raw_rows),
        "unique",
        len(unique_sheet),
        "blank_rows",
        blank_rows,
    )

    with open(OUT_DIR / "AAPL_sheet_zones.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["touch", "lower", "upper"])
        for t, lo, hi in unique_sheet:
            w.writerow([f"{t:.4f}", f"{lo:.4f}", f"{hi:.4f}"])

    eng_win, unique_eng = load_engine(ENGINE)
    print("engine unique", len(unique_eng), "rows", len(eng_win))

    sheet_set = set(unique_sheet)
    eng_set = set(unique_eng.keys())
    exact = sheet_set & eng_set
    sheet_only = sheet_set - eng_set
    eng_only = eng_set - sheet_set

    tol_matches = []
    so_rem = set(sheet_only)
    eo_rem = set(eng_only)
    for s in sorted(so_rem, key=lambda x: x[0]):
        if s not in so_rem:
            continue
        m = near_match(s, eo_rem, 0.02)
        if m:
            tol_matches.append((s, m))
            so_rem.remove(s)
            eo_rem.remove(m)
    tol_total = len(exact) + len(tol_matches)

    with open(OUT_DIR / "AAPL_zones_match_detail.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "sheet_touch",
                "sheet_lower",
                "sheet_upper",
                "eng_date",
                "eng_touch",
                "eng_lower",
                "eng_upper",
                "note",
            ]
        )
        for k in sorted(exact, key=lambda x: x[0]):
            e = unique_eng[k]
            w.writerow(
                ["exact", k[0], k[1], k[2], e["date"], e["touch"], e["lower"], e["upper"], ""]
            )
        for s, e in sorted(tol_matches, key=lambda x: x[0][0]):
            ed = unique_eng[e]
            w.writerow(
                ["tol_0.02", s[0], s[1], s[2], ed["date"], e[0], e[1], e[2], "within 0.02"]
            )
        for s in sorted(so_rem):
            w.writerow(["sheet_only", s[0], s[1], s[2], "", "", "", "", ""])
        for e in sorted(eo_rem):
            ed = unique_eng[e]
            w.writerow(["engine_only", "", "", "", ed["date"], e[0], e[1], e[2], ""])

    lines = []
    lines.append("# AAPL zone reconcile (sheet paste 2026-07-20 16:45)")
    lines.append("")
    lines.append(f"- Engine: `{ENGINE.name}` (newest; no re-run)")
    lines.append("- Sheet paste: `tools/aapl_brt_sheet_zones.tsv`")
    lines.append(f"- Window: {WIN_START} .. {WIN_END}")
    lines.append(
        f"- Sheet raw non-blank rows: {len(raw_rows)}; unique: **{len(unique_sheet)}**"
    )
    lines.append(
        f"- Engine rows in window: {len(eng_win)}; unique: **{len(unique_eng)}**"
    )
    lines.append("")
    lines.append("## Exact (tol=$0.00)")
    lines.append(f"- Matches: **{len(exact)}**")
    lines.append(
        f"- Sheet-only ({len(sheet_only)}): "
        + (", ".join(fmt(z) for z in sorted(sheet_only)) if sheet_only else "(none)")
    )
    lines.append(
        f"- Engine-only ({len(eng_only)}): "
        + (", ".join(fmt(z) for z in sorted(eng_only)) if eng_only else "(none)")
    )
    lines.append(
        f"- 100% exact: **{'YES' if not sheet_only and not eng_only else 'NO'}**"
    )
    lines.append("")
    lines.append("## Tolerant (±$0.02)")
    lines.append(
        f"- Matches: **{tol_total}** (exact {len(exact)} + near {len(tol_matches)})"
    )
    lines.append(
        f"- Sheet-only remaining ({len(so_rem)}): "
        + (", ".join(fmt(z) for z in sorted(so_rem)) if so_rem else "(none)")
    )
    lines.append(
        f"- Engine-only remaining ({len(eo_rem)}): "
        + (", ".join(fmt(z) for z in sorted(eo_rem)) if eo_rem else "(none)")
    )
    if tol_matches:
        lines.append("- Near-miss pairs:")
        for s, e in sorted(tol_matches, key=lambda x: x[0][0]):
            lines.append(
                f"  - sheet {fmt4(s)} <-> eng {fmt4(e)} (date {unique_eng[e]['date']})"
            )
    lines.append(
        f"- 100% tolerant: **{'YES' if not so_rem and not eo_rem else 'NO'}**"
    )
    lines.append("")
    lines.append("## Unmatched both ways")
    lines.append(f"- Sheet unmatched after ±$0.02: **{len(so_rem)}**")
    lines.append(f"- Engine unmatched after ±$0.02: **{len(eo_rem)}**")
    lines.append("")
    if exact:
        lines.append("## Matched zones (sheet = engine exact)")
        lines.append("| touch | lower | upper | eng_date |")
        lines.append("|------:|------:|------:|----------|")
        for k in sorted(exact, key=lambda x: (unique_eng[x]["date"], x[0])):
            ed = unique_eng[k]
            lines.append(
                f"| {k[0]:.4f} | {k[1]:.4f} | {k[2]:.4f} | {ed['date']} |"
            )
        lines.append("")
    if sheet_only:
        lines.append("## Sheet-only list")
        lines.append("| touch | lower | upper |")
        lines.append("|------:|------:|------:|")
        for t, lo, hi in sorted(sheet_only):
            lines.append(f"| {t:.4f} | {lo:.4f} | {hi:.4f} |")
        lines.append("")
    if eng_only:
        lines.append("## Engine-only list")
        lines.append("| date | touch | lower | upper |")
        lines.append("|------|------:|------:|------:|")
        for ekey in sorted(eng_only, key=lambda x: (unique_eng[x]["date"], x[0])):
            ed = unique_eng[ekey]
            lines.append(
                f"| {ed['date']} | {ekey[0]:.4f} | {ekey[1]:.4f} | {ekey[2]:.4f} |"
            )
        lines.append("")

    report = OUT_DIR / "AAPL_zones_diff.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("Wrote", report)
    print(
        "SUMMARY",
        "unique_sheet",
        len(unique_sheet),
        "unique_eng",
        len(unique_eng),
        "exact",
        len(exact),
        "tol",
        tol_total,
        "unmatched_sheet",
        len(so_rem),
        "unmatched_eng",
        len(eo_rem),
    )


if __name__ == "__main__":
    main()
