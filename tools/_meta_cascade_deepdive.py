#!/usr/bin/env python3
"""META WPBR cascade deep-dive: sheet closed vs engine RAW vs SERIALIZED (stamp 105625)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))

OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "META"
DATA = REPO / "data" / "newdata" / "data" / "META.csv"
ZONES = OUT / "zones.tsv"
TRADES = OUT / "trades.tsv"
ENG_CLOSED = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_retest_2016"
    / "WPBR_Closed_260722105625.csv"
)
REPORT = OUT / "META_cascade_deepdive.md"

from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402


def read_text_any(p: Path) -> str:
    b = p.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 1 and b[1] == 0):
        for enc in ("utf-16", "utf-16-le"):
            try:
                return b.decode(enc)
            except Exception:
                pass
    return b.decode("utf-8", errors="ignore")


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


df = pd.read_csv(DATA, index_col=0, parse_dates=True)
idx = pd.DatetimeIndex(df.index)
# Align to engine start_date=2016-01-01 for serialization window labeling
start = pd.Timestamp("2016-01-01")

stream = compute_wpbr_touch_stream(
    df,
    breakout_confirmation=0.03,
    max_days_after_retest=2,
    retest_mode="stop_looking",
)
opps = list(stream.get("wpbr_entry_opportunities") or [])
events = {str(e.get("wpbr_zone_id", "")): e for e in (stream.get("wpbr_zone_events") or [])}

raw_fills = []
for opp in opps:
    fb = opp.get("entry_fill_bar")
    sb = opp.get("entry_signal_bar")
    rb = opp.get("retest_bar")
    if fb is None:
        continue
    fb = int(fb)
    if fb < 0 or fb >= len(idx):
        continue
    fill_d = idx[fb].strftime("%Y-%m-%d")
    if pd.Timestamp(fill_d) < start:
        continue
    signal_d = idx[int(sb)].strftime("%Y-%m-%d") if sb is not None else None
    retest_d = idx[int(rb)].strftime("%Y-%m-%d") if rb is not None else None
    zid = str(opp.get("wpbr_zone_id", "") or "")
    ev = events.get(zid) or {}
    pivot_d = None
    # zone_id format: YYYY-MM-DD|zlow|zhigh — pivot week end often in event
    pivot_week = ev.get("pivot_week_end") or ev.get("pivot_date") or (zid.split("|")[0] if "|" in zid else None)
    if pivot_week:
        pivot_d = nd(pivot_week)
    raw_fills.append(
        {
            "fill": fill_d,
            "signal": signal_d,
            "retest": retest_d,
            "zone_id": zid,
            "pivot": pivot_d,
            "zlow": float(opp.get("zone_lower", float("nan"))),
            "zhigh": float(opp.get("zone_upper", float("nan"))),
            "fill_bar": fb,
            "signal_bar": int(sb) if sb is not None else None,
        }
    )
raw_fills.sort(key=lambda x: x["fill"])
raw_by_fill = {r["fill"]: r for r in raw_fills}

# Sheet zones
zrows = read_text_any(ZONES).splitlines()
sheet_z = []
for line in zrows[1:]:
    if not line.strip():
        continue
    c = line.split("\t") + [""] * 19
    sheet_z.append(
        {
            "pivot": nd(c[9]),
            "bo": nd(c[5]),
            "zlow": nf(c[6]),
            "zhigh": nf(c[7]),
            "conf": nd(c[13]),
            "next": nd(c[14]),
            "retest": nd(c[16]),
            "rocket": nd(c[18]),
        }
    )

# Sheet trades
tlines = read_text_any(TRADES).splitlines()
sheet_trades = []
for line in tlines[2:]:
    if not line.strip():
        continue
    c = line.split("\t")
    sheet_trades.append(
        {
            "entry": nd(c[0]),
            "entry_px": nf(c[1]),
            "exit": nd(c[2]),
            "exit_px": nf(c[3]),
            "pnl": c[4].strip() if len(c) > 4 else "",
            "days": c[5].strip() if len(c) > 5 else "",
            "res": c[6].strip() if len(c) > 6 else "",
        }
    )

# Engine serialized META
eng = pd.read_csv(ENG_CLOSED, dtype=str)
eng = eng[eng["SYMBOL"].str.upper() == "META"].copy()
eng_trades = []
for _, r in eng.iterrows():
    eng_trades.append(
        {
            "entry": nd(r["DATE_OPENED"]),
            "entry_px": nf(r["ENTRY_PRICE"]),
            "exit": nd(r["DATE_CLOSED"]),
            "exit_px": nf(r["EXIT_PRICE"]),
            "pnl": str(r.get("PNL_PCT", "")),
            "exit_type": str(r.get("EXIT_TYPE", "")),
            "zone_id": str(r.get("WPBR_ZONE_ID", "")),
            "maturity": nd(r.get("MATURITY_DATE")),
        }
    )

# Map sheet rocket -> fill (T+1 trading day)
trading_days = [d.strftime("%Y-%m-%d") for d in idx]
td_set = set(trading_days)
td_index = {d: i for i, d in enumerate(trading_days)}


def next_trading_day(d: str) -> str | None:
    if d not in td_index:
        # try nearest
        ts = pd.Timestamp(d)
        for i, x in enumerate(idx):
            if x.normalize() >= ts.normalize():
                # if exact bar is signal day, fill is next
                if x.normalize() == ts.normalize() and i + 1 < len(idx):
                    return idx[i + 1].strftime("%Y-%m-%d")
                return x.strftime("%Y-%m-%d")
        return None
    i = td_index[d]
    if i + 1 < len(trading_days):
        return trading_days[i + 1]
    return None


def find_sheet_zone_for_entry(entry: str):
    """Match sheet entry to zone via rocket+1 == entry, else retest+1, else rocket==entry-ish."""
    for z in sheet_z:
        rocket = z["rocket"]
        if not rocket:
            continue
        fill = next_trading_day(rocket)
        if fill == entry:
            return z, "rocket+1"
    for z in sheet_z:
        if z["rocket"] == entry:
            return z, "rocket_same_day"
    return None, None


# Link sheet trades to raw
sheet_rows = []
for t in sheet_trades:
    z, how = find_sheet_zone_for_entry(t["entry"])
    raw = raw_by_fill.get(t["entry"])
    # also try match by zone upper/pivot if fill date differs slightly
    if raw is None and z and z.get("pivot"):
        for r in raw_fills:
            if r["pivot"] and r["pivot"][:10] == z["pivot"][:10]:
                raw = r
                break
            if abs(r["zhigh"] - (z["zhigh"] or 0)) < 0.03 and r["signal"] == z.get("rocket"):
                raw = r
                break
    sheet_rows.append({"trade": t, "zone": z, "link_how": how, "raw": raw})


def overlapping_engine(entry: str):
    """Which engine serialized trade occupies the slot on entry date."""
    hits = []
    for e in eng_trades:
        if e["entry"] <= entry <= e["exit"]:
            hits.append(e)
        elif e["entry"] < entry and e["exit"] >= entry:
            hits.append(e)
    # also: free after exit — check if entry falls strictly after prior exit
    return hits


def free_after(e):
    # first trading day after exit
    return next_trading_day(e["exit"]) if e.get("exit") else None


# Blocked-by matrix: for each sheet raw-matched entry not serialized, which engine trade blocked it
blocked_matrix = []
for row in sheet_rows:
    t = row["trade"]
    entry = t["entry"]
    ser = any(e["entry"] == entry for e in eng_trades)
    raw_ok = row["raw"] is not None or (row["zone"] and row["zone"].get("rocket"))
    # Prefer engine raw fill presence
    raw_ok = entry in raw_by_fill or (row["raw"] is not None and row["raw"]["fill"] == entry)
    if entry not in raw_by_fill:
        # check if any raw fill matches
        raw_ok = False
        for r in raw_fills:
            if r["fill"] == entry:
                raw_ok = True
                break
    else:
        raw_ok = True

    occ = overlapping_engine(entry)
    # If entry equals an engine entry, it's a match not blocked
    if ser:
        blocker = None
        reason = "SERIALIZED_MATCH"
        free = None
    elif not raw_ok:
        blocker = None
        reason = "NOT_ENGINE_RAW"
        free = None
        occ = []
    elif occ:
        # pick the occupying trade (should be one)
        blocker = occ[0]
        reason = "BLOCKED_BY_OPEN_POSITION"
        free = free_after(blocker)
        # refine: free means first day AFTER exit when new entry allowed
        # engine fills at open of fill bar; typically free starting the day after exit
        # if exit and new signal same day — check code (usually no same-bar reentry)
    else:
        blocker = None
        reason = "FREE_BUT_NOT_TAKEN"  # unexpected
        free = entry

    blocked_matrix.append(
        {
            "entry": entry,
            "exit": t["exit"],
            "pnl": t["pnl"],
            "raw": raw_ok,
            "serialized": ser,
            "reason": reason,
            "blocker": blocker,
            "free_after": free,
            "zone": row["zone"],
            "raw_opp": raw_by_fill.get(entry) or row["raw"],
            "link_how": row["link_how"],
        }
    )

# Engine-only trades: which sheet signals they preempted
eng_only_preempt = []
for e in eng_trades:
    sheet_match = any(t["entry"] == e["entry"] for t in sheet_trades)
    preempted = []
    for bm in blocked_matrix:
        if bm["reason"] != "BLOCKED_BY_OPEN_POSITION":
            continue
        b = bm["blocker"]
        if b and b["entry"] == e["entry"]:
            preempted.append(bm["entry"])
    eng_only_preempt.append(
        {
            "eng": e,
            "sheet_match": sheet_match,
            "preempted_sheet_entries": preempted,
        }
    )

# Count top blockers
from collections import Counter

blocker_counts = Counter()
for bm in blocked_matrix:
    if bm["blocker"]:
        blocker_counts[bm["blocker"]["entry"]] += 1

# Option A simulation: serialize using ONLY sheet-armed fill dates (the 9 raw-matched
# sheet entries), one position at a time with sheet's own exit dates.
# This answers: if engine only considered "armed setups that earned sheet fills"...
option_a_candidates = [bm for bm in blocked_matrix if bm["raw"]]
option_a_candidates.sort(key=lambda x: x["entry"])

# Also: engine raw fills serialized greedily earliest-first (reproduces eng) — already have eng_trades

# Option A = take sheet entry dates in order, holding until sheet exit (sheet ownership path)
opt_a_fills = []
slot_free = "1900-01-01"
for bm in option_a_candidates:
    if bm["entry"] >= slot_free:
        opt_a_fills.append(bm["entry"])
        # free day after sheet exit
        slot_free = next_trading_day(bm["exit"]) or bm["exit"]
        # actually free starting day AFTER exit for next entry
        if bm["exit"] in td_index:
            # next trading day after exit
            slot_free = next_trading_day(bm["exit"]) or "9999-12-31"
        else:
            slot_free = bm["exit"]

# Alternate Option A: serialize ALL engine raw fills earliest-first but SKIP fills that
# are not "sheet-armed" (no sheet rocket). i.e. only take raw fills that match a sheet rocket+1.
sheet_armed_fills = set()
for z in sheet_z:
    if z["rocket"]:
        f = next_trading_day(z["rocket"])
        if f:
            sheet_armed_fills.add(f)

opt_a2 = []
slot_exit = "1900-01-01"
# Need exit modeling: use engine exit rules on those fills — approximate by taking
# from eng_trades if present, else from sheet if present, else unknown hold.
# Simpler product question: which of the 9 would survive if engine refused early
# engine-only fills and only armed sheet setups were eligible?

eligible = [r for r in raw_fills if r["fill"] in sheet_armed_fills or r["fill"] in {t["entry"] for t in sheet_trades if t["entry"] in raw_by_fill}]
# Use sheet exits when known for hold duration; else skip unknown
exit_map = {t["entry"]: t["exit"] for t in sheet_trades}
# For engine-only early fills that aren't sheet-armed, exclude them
slot_free = "1900-01-01"
opt_a2_taken = []
for r in sorted(raw_fills, key=lambda x: x["fill"]):
    if r["fill"] not in sheet_armed_fills and r["fill"] not in exit_map:
        continue  # not sheet-armed
    if r["fill"] < slot_free:
        continue
    # need an exit — prefer sheet exit, else we can't sim well without running BT
    ex = exit_map.get(r["fill"])
    if not ex:
        # sheet-armed but not a sheet trade (suppressed by sheet occupancy) — still an armed setup;
        # without exit model, mark as would-take-unknown-exit
        opt_a2_taken.append({"fill": r["fill"], "exit": "?", "note": "armed_not_in_sheet_trades"})
        # can't continue cascade without exit — stop conservative
        break
    opt_a2_taken.append({"fill": r["fill"], "exit": ex, "note": "sheet_trade"})
    slot_free = next_trading_day(ex) or ex

# Dig 2021-12-07
outlier = "2021-12-07"
outlier_info = {"date": outlier}
# OHLC that day
if outlier in td_index:
    i = td_index[outlier]
    row = df.iloc[i]
    outlier_info["ohlc"] = {
        "O": float(row["Open"]),
        "H": float(row["High"]),
        "L": float(row["Low"]),
        "C": float(row["Close"]),
    }
    # prior day
    if i > 0:
        p = df.iloc[i - 1]
        outlier_info["prior"] = {
            "date": idx[i - 1].strftime("%Y-%m-%d"),
            "O": float(p["Open"]),
            "H": float(p["High"]),
            "L": float(p["Low"]),
            "C": float(p["Close"]),
        }
outlier_info["sheet_entry_px"] = next((t["entry_px"] for t in sheet_trades if t["entry"] == outlier), None)
# Does entry px match open?
if outlier_info.get("ohlc") and outlier_info.get("sheet_entry_px"):
    outlier_info["matches_open"] = abs(outlier_info["ohlc"]["O"] - outlier_info["sheet_entry_px"]) < 0.02
    outlier_info["matches_close"] = abs(outlier_info["ohlc"]["C"] - outlier_info["sheet_entry_px"]) < 0.02
# Any zone with rocket near that date?
near_rockets = []
for z in sheet_z:
    if not z["rocket"]:
        continue
    if abs((pd.Timestamp(z["rocket"]) - pd.Timestamp(outlier)).days) <= 14:
        near_rockets.append(z)
outlier_info["near_rockets"] = near_rockets
# Engine raw near that date
near_raw = [r for r in raw_fills if abs((pd.Timestamp(r["fill"]) - pd.Timestamp(outlier)).days) <= 30]
outlier_info["near_raw"] = near_raw
# Sheet zone rocket 1/24/2022 fill would be 1/25 — engine took 1/25/2022
# Check if 12/7 could be a mis-pasted fill from some other signal
# Scan all sheet rockets: any fill near 12/7?
rocket_fills = []
for z in sheet_z:
    if z["rocket"]:
        f = next_trading_day(z["rocket"])
        rocket_fills.append((z["pivot"], z["rocket"], f, z["zhigh"]))
outlier_info["all_rocket_fills_2021"] = [x for x in rocket_fills if x[1] and x[1].startswith("2021")]

# Sheet occupancy around 12/7: prior trade 4/21→7/23 WIN, next would start...
outlier_info["prior_sheet_trade"] = next((t for t in sheet_trades if t["exit"] and t["exit"] < outlier), None)
# last sheet trade before
prior_trades = [t for t in sheet_trades if t["entry"] < outlier]
outlier_info["last_sheet_before"] = prior_trades[-1] if prior_trades else None
# sheet free after 7/23/2021
# zones with rocket between 7/23 and 12/7?
armed_between = []
for z in sheet_z:
    if not z["rocket"]:
        continue
    if "2021-07-23" < z["rocket"] < outlier:
        armed_between.append(z)
outlier_info["rockets_while_free_before_outlier"] = armed_between

# Print dump for report assembly
print("RAW fills count (from 2016):", len(raw_fills))
print("Sheet trades:", len(sheet_trades))
print("Eng serialized:", len(eng_trades))
print("Raw matched sheet:", sum(1 for bm in blocked_matrix if bm["raw"]))
print("Ser matched sheet:", sum(1 for bm in blocked_matrix if bm["serialized"]))
print("\n=== BLOCKED MATRIX ===")
for bm in blocked_matrix:
    b = bm["blocker"]
    print(
        f"{bm['entry']} raw={bm['raw']} ser={bm['serialized']} {bm['reason']}"
        + (f" blocker={b['entry']}->{b['exit']} free~{bm['free_after']}" if b else "")
    )
print("\n=== ENGINE TRADES / PREEMPT ===")
for ep in eng_only_preempt:
    e = ep["eng"]
    print(
        f"{e['entry']}->{e['exit']} {e['exit_type']} match={ep['sheet_match']} "
        f"preempts={ep['preempted_sheet_entries']}"
    )
print("\nTop blockers:", blocker_counts.most_common())
print("\nOption A (sheet-armed serialize):", opt_a_fills)
print("Option A2 taken:", opt_a2_taken)
print("\n=== OUTLIER 2021-12-07 ===")
import pprint

pprint.pprint(outlier_info)

# Persist structured for markdown writer
import json

payload = {
    "raw_fills": raw_fills,
    "sheet_trades": sheet_trades,
    "eng_trades": eng_trades,
    "blocked_matrix": [
        {
            **{k: v for k, v in bm.items() if k not in ("blocker", "zone", "raw_opp")},
            "blocker_entry": bm["blocker"]["entry"] if bm["blocker"] else None,
            "blocker_exit": bm["blocker"]["exit"] if bm["blocker"] else None,
            "blocker_pnl": bm["blocker"]["pnl"] if bm["blocker"] else None,
            "blocker_type": bm["blocker"]["exit_type"] if bm["blocker"] else None,
            "blocker_zone": bm["blocker"]["zone_id"] if bm["blocker"] else None,
            "pivot": (bm["zone"] or {}).get("pivot") if bm["zone"] else None,
            "rocket": (bm["zone"] or {}).get("rocket") if bm["zone"] else None,
            "retest": (bm["zone"] or {}).get("retest") if bm["zone"] else None,
            "zhigh": (bm["zone"] or {}).get("zhigh") if bm["zone"] else None,
            "eng_signal": (bm["raw_opp"] or {}).get("signal") if bm["raw_opp"] else None,
            "eng_retest": (bm["raw_opp"] or {}).get("retest") if bm["raw_opp"] else None,
            "eng_zone_id": (bm["raw_opp"] or {}).get("zone_id") if bm["raw_opp"] else None,
        }
        for bm in blocked_matrix
    ],
    "eng_preempt": [
        {
            "entry": ep["eng"]["entry"],
            "exit": ep["eng"]["exit"],
            "exit_type": ep["eng"]["exit_type"],
            "pnl": ep["eng"]["pnl"],
            "zone_id": ep["eng"]["zone_id"],
            "sheet_match": ep["sheet_match"],
            "preempted": ep["preempted_sheet_entries"],
        }
        for ep in eng_only_preempt
    ],
    "blocker_counts": blocker_counts.most_common(),
    "option_a_fills": opt_a_fills,
    "option_a2_taken": opt_a2_taken,
    "outlier": {
        "date": outlier,
        "ohlc": outlier_info.get("ohlc"),
        "prior": outlier_info.get("prior"),
        "sheet_entry_px": outlier_info.get("sheet_entry_px"),
        "matches_open": outlier_info.get("matches_open"),
        "matches_close": outlier_info.get("matches_close"),
        "near_rockets": [
            {k: z[k] for k in ("pivot", "rocket", "retest", "zhigh", "bo", "conf")}
            for z in near_rockets
        ],
        "near_raw": near_raw,
        "rockets_2021": outlier_info["all_rocket_fills_2021"],
        "last_sheet_before": outlier_info.get("last_sheet_before"),
        "rockets_while_free": [
            {k: z[k] for k in ("pivot", "rocket", "retest", "zhigh")}
            for z in armed_between
        ],
    },
    "sheet_armed_fills": sorted(sheet_armed_fills),
}
(OUT / "_cascade_payload.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
print("\nWrote", OUT / "_cascade_payload.json")
