"""Re-reconcile TSLA sheet matured zones after 2023-03-06 calendar fix."""
from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT_DIR = ROOT / "drive" / "brt_sheet_reconcile"
TOOLS = ROOT / "tools"
ENGINE = ROOT / "drive" / "BRT_ZONES_TSLA_260720143523.csv"
PRIOR_ENGINE = ROOT / "drive" / "BRT_ZONES_TSLA_260720082240.csv"
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


def load_engine(path: Path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
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


def extract_paste() -> str:
    lines = TRANSCRIPT.read_text(encoding="utf-8").splitlines()
    # 2026-07-20 16:39 parent message with zones+BOs+trades (1-indexed line 725)
    obj = json.loads(lines[724])
    text = "".join(
        c.get("text", "")
        for c in obj["message"]["content"]
        if isinstance(c, dict) and c.get("type") == "text"
    )
    idx = text.find("Matured touch price")
    if idx < 0:
        raise SystemExit("Matured touch price header not found")
    end = text.find("Breakout Date")
    if end < 0:
        end = len(text)
    return text[idx:end].rstrip() + "\n"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)

    paste = extract_paste()
    tsv_path = TOOLS / "tsla_brt_sheet_zones_20260720.tsv"
    tsv_path.write_text(paste, encoding="utf-8")
    (TOOLS / "tsla_brt_sheet_zones.txt").write_text(paste, encoding="utf-8")
    print("wrote", tsv_path, "chars", len(paste))

    raw_rows = []
    for ln in paste.splitlines()[1:]:
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        t, lo, hi = parse_money(parts[0]), parse_money(parts[1]), parse_money(parts[2])
        if t is None or lo is None or hi is None:
            continue
        raw_rows.append((t, lo, hi))
    unique_sheet = list(OrderedDict.fromkeys(raw_rows).keys())
    print("sheet raw", len(raw_rows), "unique", len(unique_sheet))

    prior_path = OUT_DIR / "TSLA_sheet_zones.csv"
    prior_set = set()
    if prior_path.exists():
        with open(prior_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                prior_set.add(
                    (
                        parse_money(row["touch"]),
                        parse_money(row["lower"]),
                        parse_money(row["upper"]),
                    )
                )
    sheet_set = set(unique_sheet)
    added = sheet_set - prior_set
    removed = prior_set - sheet_set
    print("vs prior sheet csv: added", len(added), "removed", len(removed))

    with open(prior_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["touch", "lower", "upper"])
        for t, lo, hi in unique_sheet:
            w.writerow([f"{t:.4f}", f"{lo:.4f}", f"{hi:.4f}"])

    eng_win, unique_eng = load_engine(ENGINE)
    _, prior_unique_eng = load_engine(PRIOR_ENGINE)
    eng_set = set(unique_eng.keys())
    prior_eng_set = set(prior_unique_eng.keys())
    eng_delta_add = eng_set - prior_eng_set
    eng_delta_rem = prior_eng_set - eng_set
    print("engine unique", len(unique_eng), "vs 082240 +", len(eng_delta_add), "-", len(eng_delta_rem))

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

    cent_matches = []
    for s, e in tol_matches:
        if (
            abs(s[0] - e[0]) < 1e-9
            and abs(s[1] - e[1]) <= 0.011 + 1e-9
            and abs(s[2] - e[2]) <= 0.011 + 1e-9
            and (abs(s[1] - e[1]) > 1e-9 or abs(s[2] - e[2]) > 1e-9)
        ):
            cent_matches.append((s, e))

    tol_total = len(exact) + len(tol_matches)

    detail_path = OUT_DIR / "TSLA_zones_match_detail_20260720.csv"
    with open(detail_path, "w", newline="", encoding="utf-8") as f:
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
        cent_set = set(cent_matches)
        for s, e in sorted(tol_matches, key=lambda x: x[0][0]):
            ed = unique_eng[e]
            note = "within 0.02; +/-1c twin" if (s, e) in cent_set else "within 0.02"
            w.writerow(
                ["tol_0.02", s[0], s[1], s[2], ed["date"], e[0], e[1], e[2], note]
            )
        for s in sorted(so_rem):
            w.writerow(["sheet_only", s[0], s[1], s[2], "", "", "", "", ""])
        for e in sorted(eo_rem):
            ed = unique_eng[e]
            w.writerow(["engine_only", "", "", "", ed["date"], e[0], e[1], e[2], ""])

    unchanged = (
        not added
        and not removed
        and not eng_delta_add
        and not eng_delta_rem
        and len(unique_sheet) == 139
        and len(unique_eng) == 139
        and tol_total == 139
        and not so_rem
        and not eo_rem
    )

    lines = []
    lines.append(
        "# TSLA zone reconcile (sheet paste 2026-07-20 16:39, after 2023-03-06 calendar fix)"
    )
    lines.append("")
    lines.append(f"- Engine: `{ENGINE.name}` (newest; post-SPY/-1000 stamp)")
    lines.append(f"- Sheet paste: `tools/tsla_brt_sheet_zones_20260720.tsv`")
    lines.append(f"- Window: {WIN_START} .. {WIN_END}")
    lines.append(f"- Sheet raw rows: {len(raw_rows)}; unique: **{len(unique_sheet)}**")
    lines.append(
        f"- Engine rows in window: {len(eng_win)}; unique: **{len(unique_eng)}**"
    )
    lines.append("")
    lines.append("## vs prior 139/139 (±$0.02) at 09:57")
    lines.append(
        "- Prior report: `TSLA_zones_diff.md` vs `BRT_ZONES_TSLA_260720082240.csv` "
        "→ unique 139/139, exact 135, tol±$0.02 139, unmatched 0/0"
    )
    if added or removed:
        lines.append(
            f"- Sheet set vs prior `TSLA_sheet_zones.csv`: added **{len(added)}**, "
            f"removed **{len(removed)}** — added {sorted(added)}; removed {sorted(removed)}"
        )
    else:
        lines.append(
            "- Sheet set vs prior `TSLA_sheet_zones.csv`: added **0**, removed **0** "
            "(identical unique set)"
        )
    if eng_delta_add or eng_delta_rem:
        lines.append(
            f"- Engine set vs `260720082240`: added **{len(eng_delta_add)}**, "
            f"removed **{len(eng_delta_rem)}**"
        )
    else:
        lines.append(
            "- Engine set vs `260720082240`: added **0**, removed **0** "
            "(identical unique set)"
        )
    if unchanged:
        lines.append(
            f"- **2023-03-06 fix changed zone parity?** **NO** — still "
            f"**{len(unique_sheet)}/{len(unique_eng)}** unique and "
            f"**{tol_total}/{len(unique_sheet)}** at ±$0.02 "
            f"(exact {len(exact)}; ±1¢ twins {len(cent_matches)})"
        )
    else:
        lines.append(
            f"- **2023-03-06 fix changed zone parity?** **YES** — "
            f"unique sheet {len(unique_sheet)} vs eng {len(unique_eng)}; "
            f"tol matches {tol_total}; unmatched sheet {len(so_rem)} / eng {len(eo_rem)}"
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
        lines.append("- Near-miss pairs (±1¢ AC/AD twins unless noted):")
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
    if sheet_only:
        lines.append("## Sheet-only list (exact; includes ±1¢ twins)")
        lines.append("| touch | lower | upper |")
        lines.append("|------:|------:|------:|")
        for t, lo, hi in sorted(sheet_only):
            lines.append(f"| {t:.4f} | {lo:.4f} | {hi:.4f} |")
        lines.append("")
    if eng_only:
        lines.append("## Engine-only list (exact; includes ±1¢ twins)")
        lines.append("| date | touch | lower | upper |")
        lines.append("|------|------:|------:|------:|")
        for ekey in sorted(eng_only, key=lambda x: (unique_eng[x]["date"], x[0])):
            ed = unique_eng[ekey]
            lines.append(
                f"| {ed['date']} | {ekey[0]:.4f} | {ekey[1]:.4f} | {ekey[2]:.4f} |"
            )
        lines.append("")

    report = OUT_DIR / "TSLA_zones_diff_20260720.md"
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
        "cent_twins",
        len(cent_matches),
        "unmatched_sheet",
        len(so_rem),
        "unmatched_eng",
        len(eo_rem),
        "unchanged_vs_139",
        unchanged,
    )


if __name__ == "__main__":
    main()
