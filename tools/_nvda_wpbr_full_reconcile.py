#!/usr/bin/env python3
"""NVDA WPBR FULL reconcile: weekly pivots + zones + retests + rockets + trades.

Engine truth = live compute_wpbr_touch_stream(retest_mode=stop_looking) on NVDA.csv
(identical settings to MarkTen stamp 260722105625) + serialized WPBR_Closed from
that same MarkTen run. Sheet = user paste under drive/wpbr_sheet_reconcile/NVDA/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "NVDA"
DATA = REPO / "data" / "newdata" / "data" / "NVDA.csv"
ZONES = OUT / "sheet_zones.tsv"
WEEKLY = OUT / "sheet_weekly.tsv"
TRADES = OUT / "sheet_trades.tsv"
ENG_CLOSED = (REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_retest_2016"
              / "WPBR_Closed_260722105625.csv")
RETEST_MODE = "stop_looking"
MIN_DATE = "2016-01-01"

df = pd.read_csv(DATA, index_col=0, parse_dates=True)
idx = df.index


def bar_to_date(b):
    if b is None or int(b) < 0:
        return None
    try:
        return pd.Timestamp(idx[int(b)]).strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return f"bar{b}?"


def nd(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return s


def nf(s):
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


# ---------- ENGINE (live stop_looking) ----------
res = compute_wpbr_touch_stream(
    df, band_pct=0.015, strong_pre_pivot_bars=3, strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3, strong_post_pivot_pct=0.10, strong_pivot_mode="either",
    breakout_confirmation=0.03, max_days_after_retest=2, retest_mode=RETEST_MODE,
    zone_price_round_decimals=2,
)
eng = {}
for ev in res["wpbr_zone_events"]:
    piv = nd(ev["pivot_monday"])
    eng[piv] = {
        "zlow": float(ev["zone_lower"]), "zhigh": float(ev["zone_upper"]),
        "bo": nd(ev["breakout_monday"]),
        "conf": nd(ev["conf_monday"]),
        "next": nd(ev["next_week_start"]),
        "retest": bar_to_date(ev["retest_bar"]),
        "signal": bar_to_date(ev["entry_signal_bar"]),
        "fill": bar_to_date(ev["entry_fill_bar"]),
    }
# engine raw fills >= MIN_DATE
eng_fill_dates = {v["fill"] for v in eng.values()
                  if v["fill"] and v["fill"] >= MIN_DATE}

# ---------- SHEET zones ----------
zrows = ZONES.read_text(encoding="utf-8").splitlines()
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
        "create_bo": c[4].strip(),
    }

# ---------- SHEET weekly qualified pivots ----------
wrows = WEEKLY.read_text(encoding="utf-8").splitlines()
whead = wrows[0].split("\t")
wcol = {h: i for i, h in enumerate(whead)}
weekly_piv = {}
n_weekly = n_qual = 0
for line in wrows[1:]:
    if not line.strip():
        continue
    c = line.split("\t") + [""] * len(whead)
    n_weekly += 1
    if c[wcol["Qualified Pivot"]].strip().upper() == "TRUE":
        n_qual += 1
        d = nd(c[wcol["Weekly Date"]])
        weekly_piv[d] = {
            "swing_px": nf(c[wcol["Swing High price"]]),
            "zone_upper": nf(c[wcol["Pivot Zone upper helper"]]),
        }

out = []
def P(s=""):
    out.append(s)
    print(s)

P("=== NVDA WPBR FULL RECONCILE (sheet vs engine stop_looking; MarkTen 260722105625) ===")
P(f"NVDA price bars={len(df)} ({idx.min().date()}..{idx.max().date()})")
P(f"Sheet: weekly={n_weekly} rows, zones={len(sheet_z)}, trades=11")
P(f"Engine zones (all history)={len(eng)}; retest_mode={RETEST_MODE}")
P("")

# ===== 1. WEEKLY PIVOTS =====
P("=== 1) WEEKLY QUALIFIED PIVOTS (sheet) vs ENGINE zone pivots ===")
P(f"Sheet Qualified Pivot=TRUE rows: {n_qual}")
wp_match = wp_zone = 0
wp_missing = []
for d in sorted(weekly_piv):
    e = eng.get(d)
    wp = weekly_piv[d]
    if e:
        wp_match += 1
        zu_ok = wp["zone_upper"] is not None and abs(wp["zone_upper"] - e["zhigh"]) <= 0.02
        wp_zone += 1 if zu_ok else 0
        tag = "ZONE-OK" if zu_ok else f"ZONE-DIFF s={wp['zone_upper']} e={e['zhigh']}"
    else:
        wp_missing.append(d)
        tag = "ENGINE-MISSING"
    if tag != "ZONE-OK":
        P(f"  {d}  zoneUpper s={wp['zone_upper']} -> {tag}")
P(f"Weekly pivots present as engine zone pivots: {wp_match}/{n_qual}")
P(f"Weekly zone-upper matches engine (+-0.02):   {wp_zone}/{n_qual}")
if wp_missing:
    P(f"Qualified pivots with NO engine zone: {wp_missing}")
P("")

# ===== 2. ZONE TABLE =====
P("=== 2) ZONE TABLE (sheet) vs ENGINE (matched by pivot date) ===")
stats = {k: [0, 0] for k in ["zone", "bo", "conf", "next", "retest", "rocket"]}
zone_missing = []
P(f"{'pivot':>10} {'zone':>5}{'bo':>4}{'conf':>5}{'next':>5}{'retest':>7}{'rocket':>7}  detail")
for p in sorted(sheet_z):
    s = sheet_z[p]
    e = eng.get(p)
    if not e:
        zone_missing.append(p)
        P(f"{p:>10}  ENGINE-MISSING (sheet zlow/zhigh={s['zlow']}/{s['zhigh']})")
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
        stats[k][0] += 1 if ok else 0
        if not ok:
            if k == "rocket":
                det.append(f"rocket[s={s['rocket']} e_sig={e['signal']} e_fill={e['fill']}]")
            elif k == "retest":
                det.append(f"retest[s={s['retest']} e={e['retest']}]")
            elif k == "zone":
                det.append(f"zone[s={s['zlow']}/{s['zhigh']} e={e['zlow']}/{e['zhigh']}]")
            else:
                det.append(f"{k}[s={s[k]} e={e[k]}]")
    fmt = lambda ok: " OK " if ok else " XX "
    if det:
        P(f"{p:>10} {fmt(chk['zone'])}{fmt(chk['bo'])}{fmt(chk['conf'])}{fmt(chk['next'])}"
          f"{fmt(chk['retest'])}{fmt(chk['rocket'])}  {'; '.join(det)}")
P("")
P("--- ZONE MATCH STATS (matched pivot pairs) ---")
for k, (n, d) in stats.items():
    P(f"  {k:>7}: {n}/{d} ({100*n/d:.0f}%)" if d else f"  {k:>7}: 0/0")
if zone_missing:
    P(f"Sheet zones with NO engine zone: {zone_missing}")
P("")

# ===== 3. RETEST parity summary =====
r_match = r_blank = r_engonly = r_sheetonly = r_diff = 0
for p in sheet_z:
    if p not in eng:
        continue
    s_rt, e_rt = sheet_z[p]["retest"], eng[p]["retest"]
    if s_rt is None and e_rt is None:
        r_blank += 1
    elif s_rt is None:
        r_engonly += 1
    elif e_rt is None:
        r_sheetonly += 1
    elif s_rt == e_rt:
        r_match += 1
    else:
        r_diff += 1
matched = sum(1 for p in sheet_z if p in eng)
P("=== 3) RETEST PARITY ===")
P(f"  date_match={r_match} blank_match={r_blank} eng_only(sheet_blank)={r_engonly} "
  f"sheet_only(eng_blank)={r_sheetonly} diff={r_diff}  "
  f"PARITY={r_match + r_blank}/{matched}")
P("")

# ===== 4. TRADE CASCADE =====
P("=== 4) CLOSED TRADES: sheet vs engine ===")
tlines = TRADES.read_text(encoding="utf-8").splitlines()
sheet_trades = []
for line in tlines[1:]:
    if not line.strip():
        continue
    c = line.split("\t")
    if len(c) < 7:
        continue
    e = nd(c[0])
    if not e:
        continue
    sheet_trades.append({"entry": e, "entry_px": nf(c[1]), "exit": nd(c[2]),
                         "exit_px": nf(c[3]), "pnl": c[4], "res": c[6]})

eng_closed = pd.read_csv(ENG_CLOSED, dtype=str)
eng_closed = eng_closed[eng_closed["SYMBOL"] == "NVDA"].reset_index(drop=True)
eng_entry_dates = {nd(x) for x in eng_closed["DATE_OPENED"]}

P("Engine serialized NVDA closed trades (portfolio one-slot; start 2016-01-01):")
sheet_entry_set = {t["entry"] for t in sheet_trades}
for _, r in eng_closed.iterrows():
    do = nd(r["DATE_OPENED"])
    tag = "MATCH-SHEET" if do in sheet_entry_set else "engine-only"
    P(f"  {do} {float(r['ENTRY_PRICE']):>9.2f} -> {nd(r['DATE_CLOSED'])} "
      f"{float(r['EXIT_PRICE']):>9.2f} {r.get('PNL_PCT','?'):>8} "
      f"{r.get('EXIT_TYPE',''):<10} [{tag}]")
P("")
sig_hits = sum(1 for t in sheet_trades if t["entry"] in eng_fill_dates)
ser_hits = sum(1 for t in sheet_trades if t["entry"] in eng_entry_dates)
P("Sheet entry -> engine RAW WPBR signal fill / engine SERIALIZED trade:")
for t in sheet_trades:
    P(f"  {t['entry']} px={t['entry_px']:>8.2f} {t['res']:>4}  "
      f"raw_signal={'YES' if t['entry'] in eng_fill_dates else 'no ':>3}  "
      f"serialized={'YES' if t['entry'] in eng_entry_dates else 'no'}")
P("")
P(f"Sheet trades: {len(sheet_trades)}")
P(f"Sheet entries that ARE engine raw WPBR signals: {sig_hits}/{len(sheet_trades)}")
P(f"Sheet entries that ARE engine serialized trades: {ser_hits}/{len(sheet_trades)}")
sheet_only = [t["entry"] for t in sheet_trades if t["entry"] not in eng_fill_dates]
P(f"Sheet entries NOT in engine raw signals: {sheet_only}")
P("")
P("Engine raw WPBR signal fills (>=2016): " + " ".join(sorted(eng_fill_dates)))

(OUT / "_full_reconcile_out.txt").write_text("\n".join(out), encoding="utf-8")
