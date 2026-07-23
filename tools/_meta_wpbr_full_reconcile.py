#!/usr/bin/env python3
"""META WPBR FULL reconcile: weekly pivots + zones + trades  (sheet vs engine 260722094929)."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "META"
DATA = REPO / "data" / "newdata" / "data" / "META.csv"
LOG = OUT / "engine_2016_run.log"
ZONES = OUT / "zones.tsv"
WEEKLY = OUT / "sheet_weekly.tsv"
TRADES = OUT / "trades.tsv"
ENG_CLOSED = OUT / "engine_2016" / "WPBR_Closed_260722094929.csv"

df = pd.read_csv(DATA, index_col=0, parse_dates=True)
idx = df.index


def read_text_any(p: Path) -> str:
    b = p.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 1 and b[1] == 0):
        for enc in ("utf-16", "utf-16-le"):
            try:
                return b.decode(enc)
            except Exception:
                pass
    return b.decode("utf-8", errors="ignore")


def bar_to_date(b):
    if b is None or b == "None":
        return None
    try:
        return pd.Timestamp(idx[int(b)]).strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return f"bar{b}?"


def nd(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!"}:
        return None
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return s


def nf(s):
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


# ---------- engine zones from log ----------
pat = re.compile(
    r"pivot=(\S+) z=\(([\d.]+),([\d.]+)\) bo=(\S+) conf=(\S+) next=(\S+) "
    r"retest=(\S+) signal=(\S+) fill=(\S+)"
)
eng = {}
for line in read_text_any(LOG).splitlines():
    if "META id=" not in line:
        continue
    m = pat.search(line)
    if not m:
        continue
    piv, zl, zh, bo, conf, nxt, rt, sig, fill = m.groups()
    eng[nd(piv)] = {
        "zlow": float(zl), "zhigh": float(zh),
        "bo": nd(bo) if bo != "None" else None,
        "conf": nd(conf) if conf != "None" else None,
        "next": nd(nxt) if nxt != "None" else None,
        "retest": bar_to_date(rt) if rt != "None" else None,
        "signal": bar_to_date(sig) if sig != "None" else None,
        "fill": bar_to_date(fill) if fill != "None" else None,
    }

# ---------- sheet zones ----------
zrows = read_text_any(ZONES).splitlines()
sheet_z = {}
for line in zrows[1:]:
    if not line.strip():
        continue
    c = line.split("\t") + [""] * 19
    piv = nd(c[9])
    if not piv:
        continue
    sheet_z[piv] = {
        "bo": nd(c[5]), "zlow": nf(c[6]), "zhigh": nf(c[7]),
        "conf": nd(c[13]), "next": nd(c[14]),
        "retest": nd(c[16]), "rocket": nd(c[18]),
    }

# ---------- sheet weekly qualified pivots ----------
wrows = read_text_any(WEEKLY).splitlines()
whead = wrows[0].split("\t")
col = {h: i for i, h in enumerate(whead)}
weekly_piv = {}  # date -> {swing_high_px, zone_upper}
n_weekly = 0
n_qual = 0
for line in wrows[1:]:
    if not line.strip():
        continue
    c = line.split("\t") + [""] * len(whead)
    n_weekly += 1
    qp = c[col["Qualified Pivot"]].strip().upper()
    if qp == "TRUE":
        n_qual += 1
        d = nd(c[col["Weekly Date"]])
        weekly_piv[d] = {
            "swing_px": nf(c[col["Swing High price"]]),
            "zone_upper": nf(c[col["Pivot Zone upper helper"]]),
            "strength": c[col["Pivot Strength%"]].strip(),
            "bo_row": c[col["Breakout Row Helper"]].strip(),
        }

out = []
def P(s=""):
    out.append(s)

P("=== META WPBR FULL RECONCILE (sheet vs engine stamp 260722094929) ===")
P(f"Data recovered from user paste: OHLC={len(df)} daily bars, "
  f"weekly={n_weekly} rows, zones={len(sheet_z)}, trades(sheet)=10")
P("")

# ===== 1. WEEKLY PIVOT DIFF =====
P("=== 1) WEEKLY QUALIFIED PIVOTS (sheet) vs ENGINE zones ===")
P(f"Sheet Qualified Pivot=TRUE rows: {n_qual}")
wp_match_piv = 0
wp_match_zone = 0
wp_missing = []
for d in sorted(weekly_piv):
    e = eng.get(d)
    wp = weekly_piv[d]
    if e:
        wp_match_piv += 1
        zu_ok = wp["zone_upper"] is not None and abs(wp["zone_upper"] - e["zhigh"]) <= 0.02
        if zu_ok:
            wp_match_zone += 1
        tag = "ZONE-OK" if zu_ok else f"ZONE-DIFF s={wp['zone_upper']} e={e['zhigh']}"
    else:
        wp_missing.append(d)
        tag = "ENGINE-MISSING"
    P(f"  {d}  swingpx={wp['swing_px']}  zoneUpper={wp['zone_upper']}  -> {tag}")
P("")
P(f"Weekly pivots present as engine zone pivots: {wp_match_piv}/{n_qual}")
P(f"Weekly zone-upper matches engine zhigh (+-0.02): {wp_match_zone}/{n_qual}")
if wp_missing:
    P(f"Weekly qualified pivots with NO engine zone: {wp_missing}")
P("")

# ===== 2. ZONE-LEVEL DIFF =====
P("=== 2) ZONE TABLE (sheet) vs ENGINE (matched by pivot date) ===")
stats = {k: [0, 0] for k in ["zone", "bo", "conf", "next", "retest", "rocket"]}
zone_missing = []
P(f"{'pivot':>10} {'zone':>5}{'bo':>4}{'conf':>5}{'next':>5}{'retest':>7}{'rocket':>7}  detail")
for p in sorted(sheet_z):
    s = sheet_z[p]
    e = eng.get(p)
    if not e:
        zone_missing.append(p)
        P(f"{p:>10}  ENGINE-MISSING")
        continue
    chk = {
        "zone": (s["zlow"] is not None and abs(s["zlow"]-e["zlow"]) <= 0.02
                 and abs(s["zhigh"]-e["zhigh"]) <= 0.02),
        "bo": (s["bo"] or None) == (e["bo"] or None),
        "conf": (s["conf"] or None) == (e["conf"] or None),
        "next": (s["next"] or None) == (e["next"] or None),
        "retest": (s["retest"] or None) == (e["retest"] or None),
        "rocket": (s["rocket"] or None) == (e["signal"] or None),
    }
    det = []
    for k, ok in chk.items():
        stats[k][1] += 1
        if ok:
            stats[k][0] += 1
        elif k == "rocket":
            det.append(f"rocket[s={s['rocket']} e_signal={e['signal']} e_fill={e['fill']}]")
        elif k == "retest":
            det.append(f"retest[s={s['retest']} e={e['retest']}]")
        elif k == "zone":
            det.append(f"zone[s={s['zlow']}/{s['zhigh']} e={e['zlow']}/{e['zhigh']}]")
        else:
            det.append(f"{k}[s={s[k]} e={e[k]}]")
    f = lambda ok: " OK " if ok else " XX "
    P(f"{p:>10} {f(chk['zone'])}{f(chk['bo'])}{f(chk['conf'])}{f(chk['next'])}"
      f"{f(chk['retest'])}{f(chk['rocket'])}  {'; '.join(det)}")
P("")
P("--- ZONE MATCH STATS (matched pivot pairs) ---")
for k, (n, d) in stats.items():
    P(f"  {k:>7}: {n}/{d} ({100*n/d:.0f}%)" if d else f"  {k:>7}: 0/0")
if zone_missing:
    P(f"Sheet zones with no engine zone: {zone_missing}")
P("")

# ===== 3. TRADE CASCADE =====
P("=== 3) CLOSED TRADES: sheet vs engine serialized (one position at a time) ===")
tlines = read_text_any(TRADES).splitlines()
sheet_trades = []
for line in tlines[2:]:
    if not line.strip():
        continue
    c = line.split("\t")
    sheet_trades.append({
        "entry": nd(c[0]), "entry_px": nf(c[1]), "exit": nd(c[2]),
        "exit_px": nf(c[3]), "pnl": c[4], "res": c[6],
    })

eng_closed = pd.read_csv(ENG_CLOSED, dtype=str)
eng_entry_dates = {nd(x) for x in eng_closed["DATE_OPENED"]}
# raw engine signals (fill dates) across all zones
eng_fill_dates = {v["fill"] for v in eng.values() if v["fill"]}

P("Engine serialized closed trades (start 2016-01-01):")
for _, r in eng_closed.iterrows():
    do = nd(r["DATE_OPENED"])
    tag = "MATCH-SHEET" if do in {t['entry'] for t in sheet_trades} else "engine-only"
    P(f"  {do}  {r['ENTRY_PRICE']:>8} -> {nd(r['DATE_CLOSED'])} {r['EXIT_PRICE']:>8} "
      f"{r.get('PNL_PCT','?'):>8} {r.get('EXIT_TYPE',''):<10} [{tag}]")
P("")
sig_hits = sum(1 for t in sheet_trades if t["entry"] in eng_fill_dates)
ser_hits = sum(1 for t in sheet_trades if t["entry"] in eng_entry_dates)
P("Sheet trade entry -> in engine RAW WPBR signal fills / in engine SERIALIZED trades:")
for t in sheet_trades:
    P(f"  {t['entry']}  raw_signal={'YES' if t['entry'] in eng_fill_dates else 'no ':>3}  "
      f"serialized={'YES' if t['entry'] in eng_entry_dates else 'no'}")
P("")
P(f"Sheet trades: {len(sheet_trades)}")
P(f"Sheet entries that ARE valid engine WPBR raw signals: {sig_hits}/{len(sheet_trades)}")
P(f"Sheet entries that ARE engine serialized trades:      {ser_hits}/{len(sheet_trades)}")
sheet_only = [t["entry"] for t in sheet_trades if t["entry"] not in eng_fill_dates]
P(f"Sheet entries NOT in engine raw signals: {sheet_only}")

report = "\n".join(out)
print(report)
(OUT / "_full_reconcile_out.txt").write_text(report, encoding="utf-8")
