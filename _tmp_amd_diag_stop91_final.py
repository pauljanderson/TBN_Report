# -*- coding: utf-8 -*-
import csv, json, re, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
AMD = ROOT / "drive/wpbr_sheet_reconcile/AMD"
ENG = ROOT / "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_2016_20260722151842"
STAMP = "260722151857"
OUT = ROOT / "_tmp_amd_diag_stop91_final.txt"

def parse_date(s):
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip().strip('"')
    if re.fullmatch(r"\d{8}", s):
        return datetime.strptime(s, "%Y%m%d").date()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" and "-" in s else s, fmt).date()
        except Exception:
            pass
    return None

def parse_num(s):
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip().replace("$", "").replace(",", "").replace("%", "").replace("(", "-").replace(")", "")
    try:
        return float(s)
    except Exception:
        return None

def read_delim(path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    first = text.splitlines()[0]
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    return list(rows[0].keys()) if rows else [], rows

lines = []
def P(*a):
    s = " ".join(str(x) for x in a)
    lines.append(s)
    print(s)

_, srows = read_delim(AMD / "sheet_trades.tsv")
sheet = []
for r in srows:
    sheet.append(dict(
        entry=parse_date(r.get("Entry Date")),
        exit=parse_date(r.get("Exit Date")),
        ep=parse_num(r.get("Entry Price")),
        xp=parse_num(r.get("Exit Price")),
        pct=parse_num(r.get("Profit %")),
        days=parse_num(r.get("Days In Trade")),
        result=r.get("Result"),
        pnl=parse_num(r.get("Profit per trade")),
    ))

_, crows = read_delim(ENG / ("WPBR_Closed_%s.csv" % STAMP))
eng = []
for r in crows:
    if str(r.get("SYMBOL", "")).upper() != "AMD":
        continue
    eng.append(dict(
        entry=parse_date(r.get("DATE_OPENED")),
        exit=parse_date(r.get("DATE_CLOSED")),
        ep=parse_num(r.get("ENTRY_PRICE")),
        xp=parse_num(r.get("EXIT_PRICE")),
        pct=parse_num(r.get("PNL_PCT")),
        days=parse_num(r.get("DAYS_HELD")),
        reason=r.get("EXIT_TYPE"),
        pnl=parse_num(r.get("PNL_DOLLARS")),
        stop=parse_num(r.get("STOP_PRICE")),
    ))

_, zrows = read_delim(ENG / ("WPBR_ZONES_ENTRIES_AMD_%s.csv" % STAMP))
zdates = [parse_date(r.get("ENTRY_DATE")) for r in zrows]

P("=" * 80)
P("AMD FINAL DIFF stop91", STAMP)
P("=" * 80)
P("SHEET n=", len(sheet))
for i, t in enumerate(sheet, 1):
    P("  S%02d %s -> %s  ep=%.2f xp=%.2f pct=%.2f days=%s %s pnl=%.2f" % (
        i, t["entry"], t["exit"], t["ep"], t["xp"], t["pct"], int(t["days"]), t["result"], t["pnl"]))

P("")
P("ENG CLOSED n=", len(eng))
for i, t in enumerate(eng, 1):
    P("  E%02d %s -> %s  ep=%s xp=%s pct=%s days=%s reason=%s pnl=%.2f stop=%s" % (
        i, t["entry"], t["exit"], t["ep"], t["xp"], t["pct"], t["days"], t["reason"], t["pnl"], t["stop"]))

P("")
P("ZONES ENTRY DATES n=", len(zdates))
for d in zdates:
    P(" ", d)

sb = defaultdict(list); eb = defaultdict(list)
for t in sheet: sb[t["entry"]].append(t)
for t in eng: eb[t["entry"]].append(t)
sd, ed = set(sb) - {None}, set(eb) - {None}
sheet_only = sorted(sd - ed)
eng_only = sorted(ed - sd)
matched = sorted(sd & ed)
zd = set(d for d in zdates if d)

P("")
P("SET DIFFS")
P("sheet_only", sheet_only)
P("eng_only", eng_only)
P("matched", matched)
P("zones_only_vs_sheet", sorted(zd - sd))
P("sheet subset of eng?", sd <= ed)
P("eng_only == zones_only_vs_sheet?", eng_only == sorted(zd - sd))

def near(a, b, tol=0.05):
    if a is None or b is None:
        return a == b
    return abs(float(a) - float(b)) <= tol

P("")
P("PER-MATCHED")
issues = []
for d in matched:
    st, et = sb[d][0], eb[d][0]
    diffs = []
    if st["exit"] != et["exit"]:
        diffs.append(("exit_date", str(st["exit"]), str(et["exit"])))
    if not near(st["ep"], et["ep"], 0.05):
        diffs.append(("entry_px", st["ep"], et["ep"]))
    if not near(st["xp"], et["xp"], 0.05):
        diffs.append(("exit_px", st["xp"], et["xp"]))
    if not near(st["pct"], et["pct"], 0.15):
        diffs.append(("pct", st["pct"], et["pct"]))
    if st["days"] is not None and et["days"] is not None and abs(st["days"] - et["days"]) > 1:
        diffs.append(("days", st["days"], et["days"]))
    if not diffs:
        cls = "MATCH_OK"
    elif any(x[0] == "exit_date" for x in diffs):
        cls = "EXIT_DATE_MISMATCH"
    elif any(x[0] == "exit_px" for x in diffs):
        cls = "EXIT_PRICE_MISMATCH"
    else:
        cls = "FIELD_MISMATCH"
    P("  %s %s | S %s@%s pct=%s | E %s@%s pct=%s %s" % (
        d, cls, st["exit"], st["xp"], st["pct"], et["exit"], et["xp"], et["pct"], et["reason"]))
    for df in diffs:
        P("    ", df)
    issues.append((cls, d, diffs, st, et))

for d in eng_only:
    t = eb[d][0]
    P("  ENG_ONLY %s -> %s ep=%s xp=%s pct=%s %s pnl=%.2f" % (d, t["exit"], t["ep"], t["xp"], t["pct"], t["reason"], t["pnl"]))
    issues.append(("ENG_ONLY_NOT_IN_SHEET", d, None, None, t))

# compare to stop0.89 inventory claims for matched exits
P("")
P("STOP0.91 vs INVENTORY(0.89) NOTES")
P("Under stop=0.91, check whether previously flagged exit_date mismatches still exist:")
inv_flagged_entries = {
    "2017-02-21": "exit_price same-day mismatch at 0.89",
    "2020-12-11": "exit_date mismatch at 0.89",
    "2022-01-25": "exit_date mismatch at 0.89",
    "2023-08-15": "exit_date mismatch at 0.89",
    "2024-03-18": "exit_date mismatch at 0.89",
    "2024-04-08": "entry_date_off_by_session at 0.89",
    "2024-10-14": "exit_date mismatch at 0.89",
    "2024-12-12": "exit_date mismatch at 0.89",
    "2025-10-24": "exit_date mismatch at 0.89",
}
for k, note in inv_flagged_entries.items():
    d = datetime.strptime(k, "%Y-%m-%d").date()
    if d in matched:
        st, et = sb[d][0], eb[d][0]
        ok = st["exit"] == et["exit"] and near(st["xp"], et["xp"], 0.05) and near(st["pct"], et["pct"], 0.15)
        P("  %s was (%s) => now %s | S %s@%s | E %s@%s pct S/E %s/%s" % (
            d, note, "RESOLVED_MATCH" if ok else "STILL_DIFF", st["exit"], st["xp"], et["exit"], et["xp"], st["pct"], et["pct"]))
    elif d in eng_only:
        P("  %s eng-only now" % d)
    else:
        P("  %s not in eng matched set" % d)

# summary already known
pcts = [t["pct"] for t in eng]
wins = [p for p in pcts if p > 0]
losses = [p for p in pcts if p <= 0]
P("")
P("ENG SUMMARY", len(eng), "win%%=%.1f avg=%.1f wl=%.2f days=%.1f pnl=%.2f" % (
    100*len(wins)/len(eng), sum(pcts)/len(pcts),
    (sum(wins)/len(wins))/abs(sum(losses)/len(losses)),
    sum(t["days"] for t in eng)/len(eng), sum(t["pnl"] for t in eng)))
P("SHEET SUMMARY", len(sheet), "win%%=%.1f avg=%.2f wl=%.2f days=%.1f pnl=%.2f" % (
    100*sum(1 for t in sheet if t["pct"]>0)/len(sheet),
    sum(t["pct"] for t in sheet)/len(sheet),
    (sum(t["pct"] for t in sheet if t["pct"]>0)/sum(1 for t in sheet if t["pct"]>0)) /
    abs(sum(t["pct"] for t in sheet if t["pct"]<=0)/sum(1 for t in sheet if t["pct"]<=0)),
    sum(t["days"] for t in sheet)/len(sheet), sum(t["pnl"] for t in sheet)))

cls_counts = {}
for iss in issues:
    cls_counts[iss[0]] = cls_counts.get(iss[0], 0) + 1
P("")
P("CLASS COUNTS", cls_counts)
P("VERDICT ser 20/20 + 6 eng-only:", len(sheet_only)==0, len(eng_only)==6, "sheet", len(sheet), "eng", len(eng))
P("MATCH_OK count", cls_counts.get("MATCH_OK", 0), "of", len(matched))

OUT.write_text("\n".join(lines), encoding="utf-8")
P("Wrote", OUT)
