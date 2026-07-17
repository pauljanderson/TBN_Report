#!/usr/bin/env python3
"""
Analyze RL_Closed and DB_Closed (timestamp 260223121017):
1. RL-only PnL if we sold everything when # DB > # RL (prorated PnL for force-closed trades).
2. Compare to actual combined RL+DB.
3. DB-only when DB > RL at entry: only count DB trades entered on days when DB count > RL count.

Writes: Drive/RL_DB_analysis_result_<ts>.txt
"""
import os
import sys

TS = "260223121017"
_script_dir = os.path.dirname(os.path.abspath(__file__))
DRIVE = os.path.normpath(os.path.join(_script_dir, "..", "Drive"))
RL_CASH = 47500
DB_CASH = 47500
OUT_PATH = os.path.join(DRIVE, f"RL_DB_analysis_result_{TS}.txt")

import pandas as pd

def parse_yyyymmdd(s):
    if pd.isna(s): return None
    s = str(int(float(s))).strip()
    if len(s) != 8: return None
    return pd.Timestamp(s[:4] + "-" + s[4:6] + "-" + s[6:8])

def clean_pct(val):
    if pd.isna(val): return 0.0
    if isinstance(val, str):
        val = val.replace("%", "").replace(",", "").strip()
    try:
        x = float(val)
        return x / 100.0 if abs(x) > 1.5 else x  # e.g. -9.31 -> -0.0931 if already decimal
    except Exception:
        return 0.0

def main():
    lines = []
    def out(s=""):
        lines.append(s)
        print(s)

    rl_path = os.path.join(DRIVE, f"RL_Closed_{TS}.csv")
    db_path = os.path.join(DRIVE, f"DB_Closed_{TS}.csv")
    if not os.path.isfile(rl_path) or not os.path.isfile(db_path):
        out("Missing RL_Closed or DB_Closed for timestamp " + TS)
        return

    rl = pd.read_csv(rl_path)
    db = pd.read_csv(db_path)
    rl.columns = [c.strip() for c in rl.columns]
    db.columns = [c.strip() for c in db.columns]

    # Parse dates and PnL
    rl["entry_dt"] = rl["DATE OPENED"].apply(parse_yyyymmdd)
    rl["exit_dt"] = rl["DATE CLOSED"].apply(parse_yyyymmdd)
    db["entry_dt"] = db["DATE OPENED"].apply(parse_yyyymmdd)
    db["exit_dt"] = db["DATE CLOSED"].apply(parse_yyyymmdd)

    # PNL % column: sometimes "9.37%" or -9.53; dollar PnL = (pct/100)*CASH (if pct in -100..100) or pct*CASH (if already decimal)
    def rl_pnl_dollars(row):
        pct = row.get("PNL %")
        if pd.isna(pct): return 0.0
        if isinstance(pct, str): pct = pct.replace("%", "").replace(",", "").strip()
        try: x = float(pct)
        except Exception: return 0.0
        if abs(x) <= 1.5: x = x  # already decimal
        else: x = x / 100.0
        return x * RL_CASH
    def db_pnl_dollars(row):
        pct = row.get("PNL %")
        if pd.isna(pct): return 0.0
        if isinstance(pct, str): pct = pct.replace("%", "").replace(",", "").strip()
        try: x = float(pct)
        except Exception: return 0.0
        if abs(x) <= 1.5: x = x
        else: x = x / 100.0
        return x * DB_CASH

    rl["pnl_dollars"] = rl.apply(rl_pnl_dollars, axis=1)
    db["pnl_dollars"] = db.apply(db_pnl_dollars, axis=1)
    rl["days_held"] = rl["DAYS HELD"].fillna(0).astype(float)
    db["days_held"] = db["DAYS HELD"].fillna(0).astype(float)

    rl = rl.dropna(subset=["entry_dt", "exit_dt"])
    db = db.dropna(subset=["entry_dt", "exit_dt"])

    # All trading dates (calendar days between min and max)
    all_dates = set()
    for _, row in rl.iterrows():
        d = row["entry_dt"]
        while d <= row["exit_dt"]:
            all_dates.add(d.normalize())
            d += pd.Timedelta(days=1)
    for _, row in db.iterrows():
        d = row["entry_dt"]
        while d <= row["exit_dt"]:
            all_dates.add(d.normalize())
            d += pd.Timedelta(days=1)
    all_dates = sorted(all_dates)

    # Per-date open counts (inclusive of entry and exit day)
    def rl_open_on(d):
        return ((rl["entry_dt"] <= d) & (rl["exit_dt"] >= d)).sum()
    def db_open_on(d):
        return ((db["entry_dt"] <= d) & (db["exit_dt"] >= d)).sum()

    # First date when DB > RL
    first_db_gt_rl = None
    for d in all_dates:
        if db_open_on(d) > rl_open_on(d):
            first_db_gt_rl = d
            break

    # --- Baseline totals ---
    total_rl_pnl = rl["pnl_dollars"].sum()
    total_db_pnl = db["pnl_dollars"].sum()
    combined_pnl = total_rl_pnl + total_db_pnl

    out("=" * 60)
    out("BASELINE (actual backtest)")
    out("=" * 60)
    out(f"RL total PnL:     ${total_rl_pnl:,.2f}  ({len(rl)} trades)")
    out(f"DB total PnL:     ${total_db_pnl:,.2f}  ({len(db)} trades)")
    out(f"Combined PnL:     ${combined_pnl:,.2f}")
    out()

    # --- Scenario A: RL-only, sell everything when # DB > # RL ---
    # For EACH RL trade: if at any time during [entry, exit] we have DB > RL, we force-close that trade
    # on the first such date (realize prorated PnL). Otherwise we keep full PnL. Sum over ALL RL trades.
    scenario_a_pnl = 0.0
    n_force_any = 0
    n_full_keep = 0
    for _, row in rl.iterrows():
        entry_d = row["entry_dt"]
        exit_d = row["exit_dt"]
        # First date during this trade's life when DB > RL
        first_cross = None
        d = entry_d
        while d <= exit_d:
            if db_open_on(d) > rl_open_on(d):
                first_cross = d
                break
            d += pd.Timedelta(days=1)
        if first_cross is None:
            scenario_a_pnl += row["pnl_dollars"]
            n_full_keep += 1
        else:
            days_to_cross = (first_cross - entry_d).days
            days_held = row["days_held"] if row["days_held"] and row["days_held"] > 0 else 1
            ratio = min(1.0, max(0.0, days_to_cross / days_held))
            scenario_a_pnl += row["pnl_dollars"] * ratio
            n_force_any += 1
    out("Scenario A: RL-only, sell everything when # DB > # RL (each trade closed on first day DB>RL during its life)")
    out(f"  RL trades never force-closed (full PnL): {n_full_keep}")
    out(f"  RL trades force-closed at least once (prorated PnL): {n_force_any}")
    out(f"  Scenario A total RL PnL: ${scenario_a_pnl:,.2f}")
    out()

    # --- Scenario B: Only take DB trades when DB > RL at entry ---
    # On entry day d, we only count this DB trade if (including it) DB count > RL count, i.e. db_open_on(d) > rl_open_on(d).
    def db_entered_when_db_gt_rl(row):
        d = row["entry_dt"]
        return db_open_on(d) > rl_open_on(d)
    db["entered_when_db_gt_rl"] = db.apply(db_entered_when_db_gt_rl, axis=1)
    scenario_b_db = db[db["entered_when_db_gt_rl"]]
    scenario_b_pnl = scenario_b_db["pnl_dollars"].sum()

    out("Scenario B: Only take Dive Bomber trades when there were MORE DB than RL (on entry day)")
    out(f"  DB trades that entered on a day when DB count > RL count: {len(scenario_b_db)} of {len(db)}")
    out(f"  Their total PnL: ${scenario_b_pnl:,.2f}")
    if len(scenario_b_db):
        wins = (scenario_b_db["pnl_dollars"] > 0).sum()
        losses = (scenario_b_db["pnl_dollars"] < 0).sum()
        bes = (scenario_b_db["pnl_dollars"] == 0).sum()
        out(f"  Wins / Losses / BEs: {wins} / {losses} / {bes}")
    out()

    # --- Scenario C: Only open RL when RL > DB at entry (don't close early, just skip new entries when DB >= RL) ---
    def rl_entered_when_rl_gt_db(row):
        d = row["entry_dt"]
        return rl_open_on(d) > db_open_on(d)
    rl["entered_when_rl_gt_db"] = rl.apply(rl_entered_when_rl_gt_db, axis=1)
    scenario_c_rl = rl[rl["entered_when_rl_gt_db"]]
    scenario_c_pnl = scenario_c_rl["pnl_dollars"].sum()

    out("Scenario C: Only open RL when RL trades > DB trades (on entry day); hold to normal exit, no early close")
    out(f"  RL trades that entered on a day when RL count > DB count: {len(scenario_c_rl)} of {len(rl)}")
    out(f"  Their total PnL: ${scenario_c_pnl:,.2f}")
    if len(scenario_c_rl):
        wins_c = (scenario_c_rl["pnl_dollars"] > 0).sum()
        losses_c = (scenario_c_rl["pnl_dollars"] < 0).sum()
        bes_c = (scenario_c_rl["pnl_dollars"] == 0).sum()
        out(f"  Wins / Losses / BEs: {wins_c} / {losses_c} / {bes_c}")
    out()

    # --- Summary ---
    out("=" * 60)
    out("SUMMARY")
    out("=" * 60)
    out(f"Actual combined (RL+DB):     ${combined_pnl:,.2f}")
    out(f"RL-only (no early exit):     ${total_rl_pnl:,.2f}")
    out(f"RL-only, exit when DB>RL:   ${scenario_a_pnl:,.2f}  (prorated)")
    out(f"RL-only, only open when RL>DB: ${scenario_c_pnl:,.2f}")
    out(f"DB-only (all):               ${total_db_pnl:,.2f}")
    out(f"DB-only when DB>RL at entry: ${scenario_b_pnl:,.2f}")
    out()
    if first_db_gt_rl is not None:
        diff = scenario_a_pnl - total_rl_pnl
        out(f"Exiting RL when DB>RL would have {'reduced' if diff < 0 else 'increased'} RL PnL by ${abs(diff):,.2f} (vs holding RL to actual exit).")
    if scenario_b_pnl != total_db_pnl:
        out(f"Filtering DB to 'only when DB>RL' would have yielded ${scenario_b_pnl - total_db_pnl:+,.2f} vs taking all DB trades.")

    try:
        with open(OUT_PATH, "w") as f:
            f.write("\n".join(lines))
        sys.stderr.write(f"[OK] Results written to {OUT_PATH}\n")
    except Exception as e:
        sys.stderr.write(f"[WARN] Could not write result file: {e}\n")

if __name__ == "__main__":
    main()
