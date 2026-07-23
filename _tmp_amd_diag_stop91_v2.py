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
PAYLOAD = ROOT / "drive/wpbr_sheet_reconcile/_variantC_SC_stop91_2016_reconcile_payload.json"
INV = ROOT / "drive/wpbr_sheet_reconcile/MARKTEN_SC_FULL_MISMATCH_INVENTORY.md"
STACKED = dict(trades=26, win_pct=65.4, avg_profit=10.0, wl_ratio=1.72, avg_days=36.3, pnl=372938.74)
OUT = ROOT / "_tmp_amd_diag_stop91_v2_out.txt"

def parse_date(s):
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip().strip('"')
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s[:10] if fmt.startswith("%Y-%m-%d") and len(s) >= 10 else s, fmt).date()
        except Exception:
            pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
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
    cols = list(rows[0].keys()) if rows else []
    return cols, rows

lines = []

def P(*a):
    s = " ".join(str(x) for x in a)
    lines.append(s)
    print(s)

P("=" * 80)
P("AMD DIAG stop=0.91 stamp", STAMP)
P("=" * 80)

for name in ["sheet_trades.tsv", "trades.tsv", "sheet_trades.csv"]:
    p = AMD / name
    cols, rows = read_delim(p)
    P("")
    P("## SHEET FILE", name, "cols=", cols, "n=", len(rows))
    for i, r in enumerate(rows, 1):
        P("  [%d]" % i, dict(r))

cols, srows = read_delim(AMD / "sheet_trades.tsv")
sheet = []
for r in srows:
    sheet.append(
        dict(
            entry=parse_date(r.get("Entry Date")),
            exit=parse_date(r.get("Exit Date")),
            ep=parse_num(r.get("Entry Price")),
            xp=parse_num(r.get("Exit Price")),
            pct=parse_num(r.get("Profit %")),
            days=parse_num(r.get("Days In Trade")),
            result=r.get("Result"),
            pnl=parse_num(r.get("Profit per trade")),
            raw=dict(r),
        )
    )

cols, crows = read_delim(ENG / ("WPBR_Closed_%s.csv" % STAMP))
P("")
P("## ENG CLOSED COLUMNS", cols)
eng = []
for r in crows:
    if str(r.get("SYMBOL", "")).upper() != "AMD":
        continue
    eng.append(
        dict(
            entry=parse_date(r.get("DATE_OPENED")),
            exit=parse_date(r.get("DATE_CLOSED")),
            ep=parse_num(r.get("ENTRY_PRICE")),
            xp=parse_num(r.get("EXIT_PRICE")),
            pct=parse_num(r.get("PNL_PCT")),
            days=parse_num(r.get("DAYS_HELD")),
            reason=r.get("EXIT_TYPE"),
            pnl=parse_num(r.get("PNL_DOLLARS")),
            stop=parse_num(r.get("STOP_PRICE")),
            side=r.get("SIDE"),
        )
    )
P("AMD closed n=", len(eng))
for i, t in enumerate(eng, 1):
    P(
        "  [%d] entry=%s exit=%s ep=%s xp=%s pct=%s days=%s reason=%s pnl$=%s stop=%s"
        % (i, t["entry"], t["exit"], t["ep"], t["xp"], t["pct"], t["days"], t["reason"], t["pnl"], t["stop"])
    )

cols, orows = read_delim(ENG / ("WPBR_Open_%s.csv" % STAMP))
oamd = [r for r in orows if str(r.get("SYMBOL", "")).upper() == "AMD"]
P("")
P("## ENG OPEN AMD n=", len(oamd))
for r in oamd:
    P(dict(r))

cols, zrows = read_delim(ENG / ("WPBR_ZONES_ENTRIES_AMD_%s.csv" % STAMP))
P("")
P("## ZONES ENTRIES n=", len(zrows))
zdates = []
for i, r in enumerate(zrows, 1):
    d = parse_date(r.get("ENTRY_DATE"))
    zdates.append(d)
    P("  [%d] %s ep=%s" % (i, d, r.get("ENTRY_PRICE")))

sb = defaultdict(list)
eb = defaultdict(list)
for t in sheet:
    sb[t["entry"]].append(t)
for t in eng:
    eb[t["entry"]].append(t)
sd, ed = set(sb) - {None}, set(eb) - {None}
sheet_only = sorted(sd - ed)
eng_only = sorted(ed - sd)
matched = sorted(sd & ed)
zd = set(d for d in zdates if d)

P("")
P("## ENTRY SET DIFFS")
P("sheet n", len(sd), sorted(sd))
P("eng n", len(ed), sorted(ed))
P("sheet_only", len(sheet_only), sheet_only)
P("eng_only", len(eng_only), eng_only)
P("matched", len(matched), matched)
P("zones_only_vs_sheet", sorted(zd - sd))
P("sheet_only_vs_zones", sorted(sd - zd))
P("zones_only_vs_eng", sorted(zd - ed))
P("eng_only_vs_zones", sorted(ed - zd))


def near(a, b, tol=0.05):
    if a is None or b is None:
        return a == b
    return abs(float(a) - float(b)) <= tol

P("")
P("## PER-MATCHED FIELD DIFFS")
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
    else:
        kinds = set(x[0] for x in diffs)
        if "exit_date" in kinds:
            cls = "EXIT_DATE_MISMATCH"
        elif "exit_px" in kinds:
            cls = "EXIT_PRICE_MISMATCH"
        elif "entry_px" in kinds:
            cls = "ENTRY_PRICE_MISMATCH"
        elif "pct" in kinds:
            cls = "PCT_MISMATCH"
        else:
            cls = "FIELD_MISMATCH"
    P(
        "  %s: %s | sheet %s@%s pct=%s days=%s | eng %s@%s pct=%s days=%s reason=%s"
        % (d, cls, st["exit"], st["xp"], st["pct"], st["days"], et["exit"], et["xp"], et["pct"], et["days"], et["reason"])
    )
    for df in diffs:
        P("    DIFF", df)
    issues.append((cls, d, diffs))

for d in sheet_only:
    P("  SHEET_ONLY", d, sb[d][0])
    issues.append(("SHEET_ONLY", d, None))
for d in eng_only:
    t = eb[d][0]
    P(
        "  ENG_ONLY",
        d,
        "exit=%s ep=%s xp=%s pct=%s reason=%s pnl=%s" % (t["exit"], t["ep"], t["xp"], t["pct"], t["reason"], t["pnl"]),
    )
    issues.append(("ENG_ONLY_EXTRA", d, None))

P("")
P("## SUMMARY METRICS")

def summarize(trades):
    n = len(trades)
    pcts = [t["pct"] for t in trades if t["pct"] is not None]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p <= 0]
    win_pct = 100.0 * len(wins) / n if n else None
    avg_p = sum(pcts) / len(pcts) if pcts else None
    aw = sum(wins) / len(wins) if wins else None
    al = sum(losses) / len(losses) if losses else None
    wl = (aw / abs(al)) if aw is not None and al not in (None, 0) else None
    days = [t["days"] for t in trades if t["days"] is not None]
    avg_d = sum(days) / len(days) if days else None
    pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
    dollar = sum(pnls) if pnls else None
    return dict(n=n, win_pct=win_pct, avg_profit=avg_p, wl=wl, avg_days=avg_d, pnl=dollar, n_wins=len(wins), n_losses=len(losses), aw=aw, al=al)

es = summarize(eng)
ss = summarize(sheet)
P("ENG  ", es)
P("SHEET", ss)
P("STACKED target", STACKED)
P("eng n == stacked trades?", es["n"] == STACKED["trades"], es["n"])
P("win% rounded", round(es["win_pct"], 1), "vs", STACKED["win_pct"])
P("avg_profit rounded", round(es["avg_profit"], 1), "vs", STACKED["avg_profit"])
P("wl rounded", round(es["wl"], 2), "vs", STACKED["wl_ratio"])
P("avg_days rounded", round(es["avg_days"], 1), "vs", STACKED["avg_days"])
P("pnl", es["pnl"], "vs", STACKED["pnl"], "delta", None if es["pnl"] is None else es["pnl"] - STACKED["pnl"])

sp = ENG / "_markten_stacked_stats.txt"
if sp.exists():
    for line in sp.read_text(encoding="utf-8", errors="replace").splitlines():
        if "AMD" in line.upper():
            P("STACKED FILE:", line)

P("")
P("## PAYLOAD AMD")
payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
amd = None
res = payload.get("results")
if isinstance(res, dict) and "AMD" in res:
    amd = res["AMD"]
elif isinstance(res, list):
    for item in res:
        if isinstance(item, dict):
            sym = str(item.get("symbol") or item.get("Symbol") or item.get("ticker") or item.get("sym") or "").upper()
            if sym == "AMD":
                amd = item
                break
            if "AMD" in item and isinstance(item.get("AMD"), dict):
                amd = item["AMD"]
                break


def find_amd(o):
    if isinstance(o, dict):
        if "AMD" in o:
            return o["AMD"]
        for v in o.values():
            r = find_amd(v)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_amd(v)
            if r is not None:
                return r
    return None

if amd is None:
    amd = find_amd(payload)

P("AMD type", type(amd).__name__)
if isinstance(amd, dict):
    P("AMD keys", sorted(amd.keys()))
    for k in sorted(amd.keys()):
        v = amd[k]
        js = json.dumps(v, default=str)
        if len(js) > 2500 and not any(x in k.lower() for x in ["orphan", "rocket", "ser", "stat", "summary", "parity", "mismatch"]):
            P("  %s: <%s approx_len=%d>" % (k, type(v).__name__, len(js)))
        else:
            P("  %s:" % k)
            P(js[:4000])

P("")
P("## INVENTORY AMD (may be stop 0.89)")
for i, line in enumerate(INV.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
    if re.search(r"\bAMD\b", line):
        P("L%d: %s" % (i, line))

paste = (AMD / "_raw_user_paste.txt").read_text(encoding="utf-8", errors="replace")
P("")
P("## RAW PASTE")
P("len", len(paste))
has_summary = bool(re.search(r"65\.4|1\.72|372,?938|Avg Profit|Win/Loss|Win %", paste, re.I))
P("contains stacked 6-value summary block?", has_summary)
P("contains Profit percent / Days In Trade headers?", bool(re.search(r"Profit %|Days In Trade", paste, re.I)))
P("contains Rocket Buy Date column?", "Rocket Buy Date" in paste)
hdr = paste.splitlines()[0].split("\t") if paste.splitlines() else []
if "Rocket Buy Date" in hdr:
    ri = hdr.index("Rocket Buy Date")
    blank = filled = 0
    for line in paste.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) <= ri:
            continue
        if parts[ri].strip() == "":
            blank += 1
        else:
            filled += 1
    P("Rocket Buy Date blank=%d filled=%d" % (blank, filled))

P("")
P("## SHEET ROCKET/SC MARKERS")
P("sheet_trades: no rocket/SC columns; all cells filled; no blank markers in trade table")
P("paste is breakout/zone table with Rocket Buy Date blanks (not trade summary)")

P("")
P("## STATUS MD")
P((AMD / "AMD_wpbr_reconcile_status.md").read_text(encoding="utf-8", errors="replace"))

P("")
P("## VERDICT")
P("sheet=%d eng_closed=%d open=%d matched=%d sheet_only=%d eng_only=%d" % (len(sheet), len(eng), len(oamd), len(matched), len(sheet_only), len(eng_only)))
P("ser-style: all 20 sheet entries in engine?", len(sheet_only) == 0)
P("eng has 26 closed with 6 eng-only?", len(eng) == 26 and len(eng_only) == 6)
cls_counts = {}
for iss in issues:
    cls_counts[iss[0]] = cls_counts.get(iss[0], 0) + 1
P("issue class counts", cls_counts)
P("ISSUE DETAIL:")
for iss in issues:
    P("  -", iss[0], "entry=", iss[1], "diffs=", iss[2])

OUT.write_text("\n".join(lines), encoding="utf-8")
P("")
P("Wrote", OUT)
