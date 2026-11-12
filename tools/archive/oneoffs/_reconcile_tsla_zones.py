"""One-shot TSLA sheet vs engine zone reconcile."""
from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
ENGINE = ROOT / "drive" / "BRT_ZONES_TSLA_260720082240.csv"
OUT_DIR = ROOT / "drive" / "brt_sheet_reconcile"
TOOLS = ROOT / "tools"
WIN_START, WIN_END = "2010-01-04", "2026-06-05"


def parse_money(s):
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    return round(float(s), 4)


def extract_paste() -> str:
    latest = None
    with open(TRANSCRIPT, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("role") != "user":
                continue
            content = obj.get("message", {}).get("content", [])
            texts = []
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        texts.append(c.get("text", ""))
            elif isinstance(content, str):
                texts.append(content)
            for text in texts:
                if (
                    "here are the updated sheet zones for TSLA" in text
                    and "Matured touch price" in text
                ):
                    latest = text
    if not latest:
        raise SystemExit("paste not found in transcript")
    idx = latest.find("Matured touch price")
    paste = latest[idx:]
    if "</user_query>" in paste:
        paste = paste[: paste.find("</user_query>")]
    return paste


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


def is_ac_ad_twin(s, e):
    st, slo, shi = s
    et, elo, ehi = e
    if abs(st - et) > 1e-9:
        return False
    return (
        abs(slo - elo) <= 0.011 + 1e-9
        and abs(shi - ehi) <= 0.011 + 1e-9
        and (abs(slo - elo) > 1e-9 or abs(shi - ehi) > 1e-9)
    )


def fmt(z):
    return f"${z[0]:.2f}/${z[1]:.2f}/${z[2]:.2f}"


def fmt4(z):
    return f"{z[0]:.4f}/{z[1]:.4f}/{z[2]:.4f}"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)

    paste = extract_paste()
    raw_path = TOOLS / "tsla_brt_sheet_zones.txt"
    raw_path.write_text(paste, encoding="utf-8")
    print("raw paste chars", len(paste))

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

    sheet_csv = OUT_DIR / "TSLA_sheet_zones.csv"
    with open(sheet_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["touch", "lower", "upper"])
        for t, lo, hi in unique_sheet:
            w.writerow([f"{t:.4f}", f"{lo:.4f}", f"{hi:.4f}"])

    engine_rows = []
    with open(ENGINE, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            date = row.get("DATE") or row.get("MATURITY_DATE") or ""
            t = parse_money(row.get("TOUCH_PRICE") or row.get("ZONE_CENTER"))
            lo = parse_money(row.get("ZONE_LOW"))
            hi = parse_money(row.get("ZONE_HIGH"))
            if t is None:
                continue
            engine_rows.append({"date": date, "touch": t, "lower": lo, "upper": hi})

    eng_win = [
        e
        for e in engine_rows
        if (not e["date"]) or (WIN_START <= e["date"] <= WIN_END)
    ]
    unique_eng: OrderedDict = OrderedDict()
    for e in eng_win:
        key = (e["touch"], e["lower"], e["upper"])
        if key not in unique_eng:
            unique_eng[key] = e
    print("engine raw in window", len(eng_win), "unique", len(unique_eng))

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

    ac_ad = []
    used_e = set()
    used_s = set()
    for s in sorted(so_rem):
        for e in sorted(eo_rem):
            if e in used_e:
                continue
            if is_ac_ad_twin(s, e):
                ac_ad.append((s, e))
                used_s.add(s)
                used_e.add(e)
                break

    EARLY_CUTOFF_TOUCH = 10.0
    early_sheet = [s for s in so_rem if s not in used_s and s[0] < EARLY_CUTOFF_TOUCH]
    early_eng = [e for e in eo_rem if e not in used_e and e[0] < EARLY_CUTOFF_TOUCH]
    other_sheet = [s for s in so_rem if s not in used_s and s not in early_sheet]
    other_eng = [e for e in eo_rem if e not in used_e and e not in early_eng]

    prior_sheet_gaps = {
        (1.42, 1.40, 1.44),
        (2.23, 2.20, 2.26),
        (2.09, 2.06, 2.12),
        (2.40, 2.36, 2.44),
    }
    prior_eng_gaps = {
        (2.43, 2.39, 2.47),
        (2.00, 1.97, 2.03),
        (1.97, 1.94, 2.00),
        (2.13, 2.10, 2.16),
        (2.10, 2.07, 2.13),
    }

    closed_notes = []
    for g in sorted(prior_sheet_gaps):
        if g in sheet_set:
            closed_notes.append(f"Sheet still has prior gap zone {fmt4(g)}")
        else:
            closed_notes.append(f"Sheet no longer has prior gap {fmt4(g)}")
    for g in sorted(prior_eng_gaps):
        in_s = g in sheet_set
        in_e = g in eng_set
        closed_notes.append(
            f"Prior eng-gap {fmt4(g)}: sheet={in_s} engine={in_e} exact_match={g in exact}"
        )

    flags = {
        "1.42_sheet": (1.42, 1.40, 1.44) in sheet_set,
        "2.23_sheet": (2.23, 2.20, 2.26) in sheet_set,
        "2.43_sheet": (2.43, 2.39, 2.47) in sheet_set,
        "2.00_sheet": (2.00, 1.97, 2.03) in sheet_set,
        "1.97_sheet": (1.97, 1.94, 2.00) in sheet_set,
        "2.13_sheet": (2.13, 2.10, 2.16) in sheet_set,
        "2.10_sheet": (2.10, 2.07, 2.13) in sheet_set,
        "239.28_sheet": any(abs(t - 239.28) < 1e-6 for t, _, _ in sheet_set),
        "239.28_engine": any(abs(t - 239.28) < 1e-6 for t, _, _ in eng_set),
    }

    detail_path = OUT_DIR / "TSLA_zones_match_detail.csv"
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
        for s, e in sorted(tol_matches, key=lambda x: x[0][0]):
            ed = unique_eng[e]
            w.writerow(
                [
                    "tol_0.02",
                    s[0],
                    s[1],
                    s[2],
                    ed["date"],
                    e[0],
                    e[1],
                    e[2],
                    "within 0.02",
                ]
            )
        for s, e in ac_ad:
            ed = unique_eng[e]
            w.writerow(
                [
                    "ac_ad_twin",
                    s[0],
                    s[1],
                    s[2],
                    ed["date"],
                    e[0],
                    e[1],
                    e[2],
                    "same touch bounds +/-1c",
                ]
            )
        for s in sorted(so_rem - used_s):
            note = "early_gf_yahoo" if s in early_sheet else "other"
            w.writerow(["sheet_only", s[0], s[1], s[2], "", "", "", "", note])
        for e in sorted(eo_rem - used_e):
            ed = unique_eng[e]
            note = "early_gf_yahoo" if e in early_eng else "other"
            w.writerow(
                ["engine_only", "", "", "", ed["date"], e[0], e[1], e[2], note]
            )

    tol_total = len(exact) + len(tol_matches)

    lines = []
    lines.append("# TSLA zone reconcile (updated sheet paste 2026-07-20 09:57)")
    lines.append("")
    lines.append(f"- Engine: `{ENGINE.name}`")
    lines.append(f"- Window: {WIN_START} .. {WIN_END}")
    lines.append(f"- Sheet raw rows: {len(raw_rows)}; unique: **{len(unique_sheet)}**")
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
    yes_exact = "YES" if not sheet_only and not eng_only else "NO"
    lines.append(f"- 100% exact: **{yes_exact}**")
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
    yes_tol = "YES" if not so_rem and not eo_rem else "NO"
    lines.append(f"- 100% tolerant: **{yes_tol}**")
    lines.append("")
    lines.append("## Mismatch classification")
    lines.append(f"- +/-1c AC/AD twins: **{len(ac_ad)}**")
    for s, e in ac_ad:
        lines.append(f"  - sheet {fmt4(s)} <-> eng {fmt4(e)}")
    lines.append(
        f"- Early GF/Yahoo drift sheet-only: **{len(early_sheet)}** — "
        + (", ".join(fmt(z) for z in sorted(early_sheet)) if early_sheet else "(none)")
    )
    lines.append(
        f"- Early GF/Yahoo drift engine-only: **{len(early_eng)}** — "
        + (", ".join(fmt(z) for z in sorted(early_eng)) if early_eng else "(none)")
    )
    lines.append(
        f"- Other sheet-only: **{len(other_sheet)}** — "
        + (", ".join(fmt(z) for z in sorted(other_sheet)) if other_sheet else "(none)")
    )
    lines.append(
        f"- Other engine-only: **{len(other_eng)}** — "
        + (", ".join(fmt(z) for z in sorted(other_eng)) if other_eng else "(none)")
    )
    lines.append("")
    lines.append(
        "## Early gap closure (vs prior 1.42/2.23 vs 2.00/1.97/2.13)"
    )
    for n in closed_notes:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("## Key flags")
    for k, v in flags.items():
        lines.append(f"- {k}: {'YES' if v else 'NO'}")
    lines.append("")
    lines.append("## Sheet-only list (touch/lo/hi)")
    if sheet_only:
        lines.append("| touch | lower | upper |")
        lines.append("|------:|------:|------:|")
        for t, lo, hi in sorted(sheet_only):
            lines.append(f"| {t:.4f} | {lo:.4f} | {hi:.4f} |")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Engine-only list (date / touch/lo/hi)")
    if eng_only:
        lines.append("| date | touch | lower | upper |")
        lines.append("|------|------:|------:|------:|")
        for ekey in sorted(eng_only, key=lambda x: (unique_eng[x]["date"], x[0])):
            ed = unique_eng[ekey]
            lines.append(
                f"| {ed['date']} | {ekey[0]:.4f} | {ekey[1]:.4f} | {ekey[2]:.4f} |"
            )
    else:
        lines.append("(none)")
    lines.append("")

    report = OUT_DIR / "TSLA_zones_diff.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("Wrote", report)
    print(
        "EXACT",
        len(exact),
        "TOL",
        tol_total,
        "SO",
        len(sheet_only),
        "EO",
        len(eng_only),
    )
    print("SO_list", sorted(sheet_only))
    print("EO_list", sorted(eng_only))
    print("FLAGS", flags)


if __name__ == "__main__":
    main()
