#!/usr/bin/env python3
"""META WPBR zone-level reconcile: sheet zones paste vs engine WPBR zones.

Sheet zones : drive/wpbr_sheet_reconcile/META/zones.tsv (recovered from user paste)
Engine zones: parsed from engine_2016_run.log [WPBR] lines (stamp 260722094929)
Bar indices (retest/signal/fill) converted to dates via META.csv index.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "META"
DATA = REPO / "data" / "newdata" / "data" / "META.csv"
LOG = OUT / "engine_2016_run.log"
ZONES = OUT / "zones.tsv"

df = pd.read_csv(DATA, index_col=0, parse_dates=True)
idx = df.index


def bar_to_date(b):
    if b is None or b == "None":
        return None
    try:
        return pd.Timestamp(idx[int(b)]).strftime("%-m/%-d/%Y")
    except (ValueError, IndexError):
        try:
            return pd.Timestamp(idx[int(b)]).strftime("%m/%d/%Y").lstrip("0").replace("/0", "/")
        except Exception:
            return f"bar{b}?"


def norm_date(s):
    if not s or str(s).strip() in {"", "#N/A", "None"}:
        return None
    try:
        return pd.Timestamp(str(s).strip()).strftime("%Y-%m-%d")
    except Exception:
        return str(s).strip()


# --- parse engine log ---
pat = re.compile(
    r"pivot=(\S+) z=\(([\d.]+),([\d.]+)\) bo=(\S+) conf=(\S+) next=(\S+) "
    r"retest=(\S+) signal=(\S+) fill=(\S+)"
)
eng = {}
for line in LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
    if "[WPBR] META id=" not in line:
        continue
    m = pat.search(line)
    if not m:
        continue
    piv, zl, zh, bo, conf, nxt, rt, sig, fill = m.groups()
    eng[norm_date(piv)] = {
        "pivot": piv,
        "zlow": float(zl),
        "zhigh": float(zh),
        "bo": None if bo == "None" else norm_date(bo),
        "conf": None if conf == "None" else norm_date(conf),
        "next": None if nxt == "None" else norm_date(nxt),
        "retest": None if rt == "None" else norm_date(bar_to_date(rt)),
        "signal": None if sig == "None" else norm_date(bar_to_date(sig)),
        "fill": None if fill == "None" else norm_date(bar_to_date(fill)),
    }

# --- parse sheet zones ---
rows = ZONES.read_text(encoding="utf-8").splitlines()
sheet = {}
for line in rows[1:]:
    if not line.strip():
        continue
    c = line.split("\t")
    if len(c) < 19:
        c = c + [""] * (19 - len(c))
    piv = norm_date(c[9])
    if piv is None:
        continue
    sheet[piv] = {
        "bo": norm_date(c[5]),
        "zlow": float(str(c[6]).replace("$", "").strip()),
        "zhigh": float(str(c[7]).replace("$", "").strip()),
        "conf": norm_date(c[13]),
        "next": norm_date(c[14]),
        "retest": norm_date(c[16]),
        "rocket": norm_date(c[18]),
    }

# --- diff ---
all_pivots = sorted(set(sheet) | set(eng))
sheet_pivots = sorted(sheet)

def eq(a, b):
    return (a or None) == (b or None)

stats = {k: [0, 0] for k in ["zone", "bo", "conf", "next", "retest", "rocket"]}
lines_out = []
lines_out.append("=== META WPBR ZONE-LEVEL RECONCILE (sheet vs engine, pivot>=2016) ===")
lines_out.append(f"Sheet zones: {len(sheet)}  |  Engine zones(>=2016): {sum(1 for p in eng if p>='2016')}")
lines_out.append("")
hdr = f"{'pivot':>10} {'zone':>6} {'bo':>5} {'conf':>5} {'next':>5} {'retest':>7} {'rocket':>7}  mismatches"
lines_out.append(hdr)

only_sheet = []
only_eng = []
mismatch_detail = []
for p in sheet_pivots:
    s = sheet[p]
    e = eng.get(p)
    if e is None:
        only_sheet.append(p)
        lines_out.append(f"{p:>10}  ENGINE-MISSING")
        continue
    zmatch = abs(s["zlow"] - e["zlow"]) <= 0.02 and abs(s["zhigh"] - e["zhigh"]) <= 0.02
    checks = {
        "zone": zmatch,
        "bo": eq(s["bo"], e["bo"]),
        "conf": eq(s["conf"], e["conf"]),
        "next": eq(s["next"], e["next"]),
        "retest": eq(s["retest"], e["retest"]),
        "rocket": eq(s["rocket"], e["fill"]),
    }
    mm = []
    for k, ok in checks.items():
        stats[k][1] += 1
        if ok:
            stats[k][0] += 1
        else:
            if k == "zone":
                mm.append(f"zone[s={s['zlow']}/{s['zhigh']} e={e['zlow']}/{e['zhigh']}]")
            elif k == "rocket":
                mm.append(f"rocket[s={s['rocket']} e_fill={e['fill']}]")
            else:
                mm.append(f"{k}[s={s[k]} e={e[k]}]")
    flag = lambda ok: "OK" if ok else "XX"
    lines_out.append(
        f"{p:>10} {flag(checks['zone']):>6} {flag(checks['bo']):>5} "
        f"{flag(checks['conf']):>5} {flag(checks['next']):>5} "
        f"{flag(checks['retest']):>7} {flag(checks['rocket']):>7}  {'; '.join(mm)}"
    )
    if mm:
        mismatch_detail.append((p, mm))

for p in sorted(eng):
    if p >= "2016" and p not in sheet:
        only_eng.append(p)

lines_out.append("")
lines_out.append("=== MATCH STATS (matched pivot pairs) ===")
for k, (n, d) in stats.items():
    pct = (100.0 * n / d) if d else 0.0
    lines_out.append(f"  {k:>7}: {n}/{d}  ({pct:.0f}%)")

lines_out.append("")
lines_out.append(f"Pivots only in SHEET (no engine zone): {only_sheet}")
lines_out.append(f"Pivots only in ENGINE (>=2016, not in sheet): {only_eng}")

report = "\n".join(lines_out)
print(report)
(OUT / "_zone_diff_out.txt").write_text(report, encoding="utf-8")
