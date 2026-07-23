# -*- coding: utf-8 -*-
"""AMD sheet vs engine diagnosis for stamp 260722151857 stop=0.91"""
from __future__ import annotations
import csv, json, re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
AMD = ROOT / "drive/wpbr_sheet_reconcile/AMD"
ENG = ROOT / "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_2016_20260722151842"
STAMP = "260722151857"
PAYLOAD = ROOT / "drive/wpbr_sheet_reconcile/_variantC_SC_stop91_2016_reconcile_payload.json"
INV = ROOT / "drive/wpbr_sheet_reconcile/MARKTEN_SC_FULL_MISMATCH_INVENTORY.md"

STACKED = dict(trades=26, win_pct=65.4, avg_profit=10.0, wl_ratio=1.72, avg_days=36.3, pnl=372938.74)

def parse_date(s):
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip().strip('"')
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19] if " " in s and fmt.startswith("%Y-%m-%d %") else s, fmt).date()
        except Exception:
            continue
    # excel serial?
    try:
        n = float(s)
        if 20000 < n < 60000:
            from datetime import date, timedelta
            return (date(1899, 12, 30) + timedelta(days=int(n)))
    except Exception:
        pass
    return None

def parse_money(s):
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip().replace("$", "").replace(",", "").replace("%", "").replace("(", "-").replace(")", "")
    try:
        return float(s)
    except Exception:
        return None

def parse_pct(s):
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except Exception:
        return None

def read_delim(path: Path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    # detect delimiter
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    cols = list(rows[0].keys()) if rows else (first.split(delim) if first else [])
    return cols, rows, delim

def norm_col(c):
    return re.sub(r"\s+", " ", (c or "").strip().lower())

def pick(row, *cands):
    m = {norm_col(k): k for k in row.keys()}
    for c in cands:
        k = m.get(norm_col(c))
        if k is not None and row.get(k) not in (None, ""):
            return row[k]
    # fuzzy contains
    for c in cands:
        for nk, k in m.items():
            if c.lower() in nk and row.get(k) not in (None, ""):
                return row[k]
    return None

print("=" * 80)
print("AMD DIAGNOSIS stamp", STAMP, "stop=0.91")
print("=" * 80)

# --- 1. Sheet trades ---
print("\n### 1. SHEET TRADES ###")
for name in ["sheet_trades.tsv", "trades.tsv", "sheet_trades.csv"]:
    p = AMD / name
    print(f"\n-- {name} exists={p.exists()} size={p.stat().st_size if p.exists() else 'N/A'}")
    if not p.exists():
        continue
    cols, rows, delim = read_delim(p)
    print("COLUMNS:", cols)
    print(f"ROW COUNT: {len(rows)}")
    for i, r in enumerate(rows, 1):
        print(f"  [{i}] {dict(r)}")

# Use sheet_trades.tsv as primary
cols_s, sheet_rows, _ = read_delim(AMD / "sheet_trades.tsv")
sheet_trades = []
for r in sheet_rows:
    ed = parse_date(pick(r, "Entry Date", "entry_date", "Entry"))
    xd = parse_date(pick(r, "Exit Date", "exit_date", "Exit"))
    ep = parse_money(pick(r, "Entry Price", "entry_price"))
    xp = parse_money(pick(r, "Exit Price", "exit_price"))
    pct = parse_pct(pick(r, "Profit %", "Profit%", "result%", "pnl%"))
    days = parse_money(pick(r, "Days In Trade", "Days", "days"))
    result = pick(r, "Result", "result")
    pnl = parse_money(pick(r, "Profit per trade", "PnL", "$PnL"))
    # rocket / SC markers in any field
    blob = " | ".join(str(v) for v in r.values())
    markers = []
    if re.search(r"\brocket\b", blob, re.I):
        markers.append("rocket")
    if re.search(r"\bSC\b|second.?chance|blank", blob, re.I):
        markers.append("SC/blank?")
    # blank entry markers
    for k, v in r.items():
        if v is None or str(v).strip() == "":
            markers.append(f"blank:{k}")
    sheet_trades.append(dict(entry=ed, exit=xd, entry_px=ep, exit_px=xp, pct=pct, days=days, result=result, pnl=pnl, markers=markers, raw=dict(r)))

print("\n### Sheet trade markers (rocket/SC/blank) ###")
for i, t in enumerate(sheet_trades, 1):
    print(f"  [{i}] entry={t['entry']} markers={t['markers']}")

# --- 2. Engine closed ---
print("\n### 2. ENGINE CLOSED AMD ###")
closed_path = ENG / f"WPBR_Closed_{STAMP}.csv"
cols_c, closed_all, _ = read_delim(closed_path)
print("CLOSED COLUMNS:", cols_c)
# find symbol col
sym_keys = []
for c in cols_c:
    if "symbol" in norm_col(c) or norm_col(c) in ("ticker", "sym"):
        sym_keys.append(c)
print("Symbol-like cols:", sym_keys)

def is_amd(row):
    for c in row:
        v = str(row[c]).strip().upper()
        if v == "AMD":
            return True
    # also Symbol column specifically
    s = pick(row, "Symbol", "Ticker", "symbol")
    return str(s or "").strip().upper() == "AMD"

eng_closed = []
for r in closed_all:
    if not is_amd(r):
        continue
    ed = parse_date(pick(r, "Entry Date", "entry_date", "EntryDate", "Date In", "Buy Date"))
    xd = parse_date(pick(r, "Exit Date", "exit_date", "ExitDate", "Date Out", "Sell Date"))
    ep = parse_money(pick(r, "Entry Price", "entry_price", "Buy Price", "EntryPx"))
    xp = parse_money(pick(r, "Exit Price", "exit_price", "Sell Price", "ExitPx"))
    pct = parse_pct(pick(r, "Profit %", "Profit%", "Return %", "PnL %", "Result %", "pct"))
    days = parse_money(pick(r, "Days In Trade", "Days", "Holding Days", "days_held"))
    reason = pick(r, "Exit Reason", "Reason", "Exit Type", "ExitType", "Type", "exit_reason", "Comment")
    result = pick(r, "Result", "Win/Loss", "Outcome")
    pnl = parse_money(pick(r, "Profit", "PnL", "$PnL", "Profit $", "Dollar PnL", "P/L"))
    eng_closed.append(dict(entry=ed, exit=xd, entry_px=ep, exit_px=xp, pct=pct, days=days, reason=reason, result=result, pnl=pnl, raw=dict(r)))

print(f"AMD closed count: {len(eng_closed)}")
print("KEY FIELDS:")
for i, t in enumerate(eng_closed, 1):
    print(f"  [{i}] entry={t['entry']} exit={t['exit']} ep={t['entry_px']} xp={t['exit_px']} pct={t['pct']} days={t['days']} result={t['result']} reason={t['reason']} pnl={t['pnl']}")

print("\nFULL RAW AMD CLOSED ROWS:")
for i, t in enumerate(eng_closed, 1):
    print(f"  [{i}] {t['raw']}")

# --- 3. Open ---
print("\n### 3. ENGINE OPEN AMD ###")
open_path = ENG / f"WPBR_Open_{STAMP}.csv"
if open_path.exists():
    cols_o, open_all, _ = read_delim(open_path)
    print("OPEN COLUMNS:", cols_o)
    eng_open = [r for r in open_all if is_amd(r)]
    print(f"AMD open count: {len(eng_open)}")
    for i, r in enumerate(eng_open, 1):
        print(f"  [{i}] {dict(r)}")
else:
    print("Open file missing")
    eng_open = []

# --- 4. Zones entries ---
print("\n### 4. WPBR_ZONES_ENTRIES_AMD ###")
ze = ENG / f"WPBR_ZONES_ENTRIES_AMD_{STAMP}.csv"
cols_z, zrows, _ = read_delim(ze)
print("COLUMNS:", cols_z)
print(f"ROW COUNT: {len(zrows)}")
entry_dates_zones = []
for i, r in enumerate(zrows, 1):
    ed = parse_date(pick(r, "Entry Date", "entry_date", "Date", "Trigger Date", "Breakout Date"))
    entry_dates_zones.append(ed)
    print(f"  [{i}] entry_date={ed} raw={dict(r)}")

# --- 5. Diff ---
print("\n### 5. ENTRY DATE DIFFS ###")
sheet_by = {}
for t in sheet_trades:
    sheet_by.setdefault(t["entry"], []).append(t)
eng_by = {}
for t in eng_closed:
    eng_by.setdefault(t["entry"], []).append(t)

sheet_dates = set(sheet_by.keys()) - {None}
eng_dates = set(eng_by.keys()) - {None}
sheet_only = sorted(sheet_dates - eng_dates)
eng_only = sorted(eng_dates - sheet_dates)
matched = sorted(sheet_dates & eng_dates)

print(f"Sheet entries ({len(sheet_dates)}): {sorted(sheet_dates)}")
print(f"Eng closed entries ({len(eng_dates)}): {sorted(eng_dates)}")
print(f"Sheet-only ({len(sheet_only)}): {sheet_only}")
print(f"Eng-only ({len(eng_only)}): {eng_only}")
print(f"Matched ({len(matched)}): {matched}")

# zones vs sheet/eng
zone_dates = set(d for d in entry_dates_zones if d)
print(f"Zones entry dates ({len(zone_dates)}): {sorted(zone_dates)}")
print(f"Zones-only vs sheet: {sorted(zone_dates - sheet_dates)}")
print(f"Sheet-only vs zones: {sorted(sheet_dates - zone_dates)}")
print(f"Zones-only vs eng closed: {sorted(zone_dates - eng_dates)}")
print(f"Eng-only vs zones: {sorted(eng_dates - zone_dates)}")

print("\n### PER-MATCHED FIELD DIFFS ###")
issues = []

def near(a, b, tol=0.02):
    if a is None or b is None:
        return a == b
    return abs(float(a) - float(b)) <= tol

for d in matched:
    st = sheet_by[d][0]
    et = eng_by[d][0]
    diffs = []
    if st["exit"] != et["exit"]:
        diffs.append(f"exit_date sheet={st['exit']} eng={et['exit']}")
    if not near(st["entry_px"], et["entry_px"], 0.05):
        diffs.append(f"entry_px sheet={st['entry_px']} eng={et['entry_px']}")
    if not near(st["exit_px"], et["exit_px"], 0.05):
        diffs.append(f"exit_px sheet={st['exit_px']} eng={et['exit_px']}")
    if not near(st["pct"], et["pct"], 0.15):
        diffs.append(f"pct sheet={st['pct']} eng={et['pct']}")
    if st["days"] is not None and et["days"] is not None and abs(st["days"] - et["days"]) > 1:
        diffs.append(f"days sheet={st['days']} eng={et['days']}")
    cls = "MATCH_OK" if not diffs else "FIELD_MISMATCH"
    print(f"  {d}: {cls}")
    for x in diffs:
        print(f"    - {x}")
    issues.append(dict(kind=cls, entry=d, diffs=diffs, sheet=st, eng=et))

for d in sheet_only:
    issues.append(dict(kind="SHEET_ONLY_ENTRY", entry=d, sheet=sheet_by[d][0], eng=None))
    print(f"  SHEET_ONLY: {d} -> {sheet_by[d][0]}")
for d in eng_only:
    issues.append(dict(kind="ENG_ONLY_ENTRY", entry=d, sheet=None, eng=eng_by[d][0]))
    print(f"  ENG_ONLY: {d} -> entry_px={eng_by[d][0]['entry_px']} exit={eng_by[d][0]['exit']} pct={eng_by[d][0]['pct']} reason={eng_by[d][0]['reason']}")

# open AMD
if eng_open:
    for r in eng_open:
        ed = parse_date(pick(r, "Entry Date", "entry_date", "EntryDate"))
        issues.append(dict(kind="ENG_OPEN", entry=ed, raw=dict(r)))

# --- 6. Engine summary ---
print("\n### 6. ENGINE SUMMARY vs STACKED ###")
n = len(eng_closed)
pcts = [t["pct"] for t in eng_closed if t["pct"] is not None]
wins = [p for p in pcts if p > 0]
losses = [p for p in pcts if p <= 0]
win_pct = (100.0 * len(wins) / n) if n else None
avg_profit = (sum(pcts) / len(pcts)) if pcts else None
avg_win = (sum(wins) / len(wins)) if wins else None
avg_loss = (sum(losses) / len(losses)) if losses else None
wl = (avg_win / abs(avg_loss)) if avg_win is not None and avg_loss not in (None, 0) else None
days_list = [t["days"] for t in eng_closed if t["days"] is not None]
avg_days = (sum(days_list) / len(days_list)) if days_list else None
pnls = [t["pnl"] for t in eng_closed if t["pnl"] is not None]
dollar = sum(pnls) if pnls else None

print(f"eng: trades={n} win%={win_pct} avg_profit%={avg_profit} wl={wl} avg_days={avg_days} $PnL={dollar}")
print(f"stacked target: {STACKED}")
print(f"pnls_available={len(pnls)}/{n} pcts_available={len(pcts)}/{n}")

# Sheet summary if available
spcts = [t["pct"] for t in sheet_trades if t["pct"] is not None]
sw = [p for p in spcts if p > 0]
sl = [p for p in spcts if p <= 0]
sn = len(sheet_trades)
print(f"sheet: trades={sn} win%={(100*len(sw)/sn) if sn else None} avg_profit%={(sum(spcts)/len(spcts)) if spcts else None} "
      f"wl={( (sum(sw)/len(sw)) / abs(sum(sl)/len(sl)) ) if sw and sl else None} "
      f"avg_days={(sum(t['days'] for t in sheet_trades if t['days'] is not None)/sum(1 for t in sheet_trades if t['days'] is not None)) if any(t['days'] is not None for t in sheet_trades) else None} "
      f"$PnL={sum(t['pnl'] for t in sheet_trades if t['pnl'] is not None) if any(t['pnl'] is not None for t in sheet_trades) else None}")

# Check stacked stats file
stats_path = ENG / "_markten_stacked_stats.txt"
if stats_path.exists():
    print("\n--- stacked stats file ---")
    print(stats_path.read_text(encoding="utf-8", errors="replace")[:3000])

# --- 7. Payload ---
print("\n### 7. RECONCILE PAYLOAD AMD ###")
payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
# find AMD section
def find_amd(obj, path="$"):
    hits = []
    if isinstance(obj, dict):
        # if looks like symbol keyed
        for k, v in obj.items():
            if str(k).upper() == "AMD":
                hits.append((f"{path}.{k}", v))
            hits.extend(find_amd(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, dict) and str(v.get("symbol") or v.get("Symbol") or v.get("ticker") or "").upper() == "AMD":
                hits.append((f"{path}[{i}]", v))
            hits.extend(find_amd(v, f"{path}[{i}]"))
    return hits

hits = find_amd(payload)
print(f"AMD hits in payload: {len(hits)}")
# Prefer top-level or compact summaries
shown = set()
for path, v in hits:
    key = path.split(".")[-1] if isinstance(path, str) else path
    # print orphans/rocket/ser focused
    if isinstance(v, dict):
        keys_lower = {k.lower(): k for k in v.keys()}
        interesting = {}
        for needle in ["orphan", "rocket", "ser", "sheet", "engine", "mismatch", "status", "trades", "entries", "closed", "open", "summary", "stats", "count"]:
            for lk, k in keys_lower.items():
                if needle in lk:
                    interesting[k] = v[k]
        print(f"\nPATH: {path}")
        if interesting:
            print(json.dumps(interesting, indent=2, default=str)[:8000])
        else:
            # print full if small
            s = json.dumps(v, indent=2, default=str)
            print(s[:6000] if len(s) > 6000 else s)
    else:
        print(f"PATH: {path} => {v}")

# Also print top-level keys
print("\nPayload top-level keys:", list(payload.keys()) if isinstance(payload, dict) else type(payload))

# --- 8. Inventory ---
print("\n### 8. MARKTEN_SC_FULL_MISMATCH_INVENTORY AMD ###")
inv_text = INV.read_text(encoding="utf-8", errors="replace")
# extract AMD section
m = re.search(r"(?im)^#+\s*AMD\b.*?(?=^#+\s*[A-Z]{2,5}\b|\Z)", inv_text, re.S)
if not m:
    m = re.search(r"(?im)^##?\s*AMD\s*$.*?(?=^##?\s+[A-Z]|\Z)", inv_text, re.S)
if m:
    print(m.group(0)[:8000])
else:
    # line-based
    lines = inv_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"(?i)^#+\s*AMD\b|^AMD\b", line.strip()):
            start = i
            break
    if start is not None:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if re.match(r"(?i)^#+\s*[A-Z]{1,5}\b", lines[j].strip()) and not re.match(r"(?i)^#+\s*AMD\b", lines[j].strip()):
                end = j
                break
        print("\n".join(lines[start:end])[:8000])
    else:
        print("AMD section not found; searching mentions...")
        for i, line in enumerate(lines):
            if "AMD" in line:
                print(f"L{i}: {line}")

# --- 9. raw paste ---
print("\n### 9. _raw_user_paste.txt summary 6-value block? ###")
paste = (AMD / "_raw_user_paste.txt").read_text(encoding="utf-8", errors="replace")
print(f"paste length={len(paste)}")
# look for patterns like 26, 65.4%, etc or 6 numbers in a row
print("--- first 120 lines ---")
for i, line in enumerate(paste.splitlines()[:120], 1):
    print(f"{i:3}| {line}")
print("--- searching numeric summary patterns ---")
# 6-value block: trades, win%, avg, ratio, days, $
patterns = [
    r"26\b",
    r"65\.4",
    r"10\.0",
    r"1\.72",
    r"36\.3",
    r"372,?938",
    r"\b\d+\s+\d+\.?\d*%\s+\d+\.?\d*%\s+\d+\.?\d*\s+\d+\.?\d*\s+\$?[\d,]+",
]
for pat in patterns:
    ms = list(re.finditer(pat, paste))
    print(f"  pattern {pat!r}: {len(ms)} hits")
    for mm in ms[:5]:
        start = max(0, mm.start() - 40)
        end = min(len(paste), mm.end() + 40)
        print(f"    ...{paste[start:end].replace(chr(10),' / ')}...")

# try detect a header row of summary metrics
for line in paste.splitlines():
    if re.search(r"(?i)win\s*%|avg\s*profit|win.?loss|avg\s*days|trades", line) and re.search(r"\d", line):
        print("SUMMARY-ISH LINE:", line)

# --- 10. rocket blank / SC ---
print("\n### 10. ROCKET BLANK / SC MARKERS IN SHEET ###")
print("Checking sheet_trades columns for extra marker columns / blank cells...")
for i, r in enumerate(sheet_rows, 1):
    blanks = [k for k, v in r.items() if v is None or str(v).strip() == ""]
    print(f"  row{i} blanks={blanks} values={list(r.values())}")

# Also check status md
print("\n### STATUS MD ###")
print((AMD / "AMD_wpbr_reconcile_status.md").read_text(encoding="utf-8", errors="replace"))

# --- Verdict ---
print("\n### VERDICT / CLASSIFICATION SUMMARY ###")
print(f"Sheet closed trades: {len(sheet_trades)}")
print(f"Eng closed trades: {len(eng_closed)}")
print(f"Matched by entry date: {len(matched)}")
print(f"Sheet-only: {len(sheet_only)} Eng-only: {len(eng_only)}")
field_mm = [i for i in issues if i["kind"] == "FIELD_MISMATCH"]
print(f"Field mismatches on matched: {len(field_mm)}")
print(f"Hypothesis ser 20/20 sheet in engine but eng has 26 closed (6 eng-only): sheet={len(sheet_trades)} eng={len(eng_closed)} eng_only={len(eng_only)} sheet_only={len(sheet_only)}")
print(f"  => sheet entries all in eng? {len(sheet_only)==0 and len(sheet_trades)>0}")
print(f"  => eng has {len(eng_only)} extra closed beyond sheet")
print(f"  => 20/20 + 6 eng-only? sheet_n==20? {len(sheet_trades)==20}; eng==26? {len(eng_closed)==26}; eng_only==6? {len(eng_only)==6}")

print("\nISSUE LIST:")
for iss in issues:
    print(f"  - {iss['kind']}: entry={iss.get('entry')} diffs={iss.get('diffs')}")

print("\nDONE.")
