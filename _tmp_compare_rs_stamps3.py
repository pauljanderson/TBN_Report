import csv
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")

# list fat gap dirs
ab = ROOT / "drive/paul_experiments/rs_fat_gap_ab"
print("AB dirs:")
for p in sorted(ab.iterdir()):
    if p.is_dir():
        audits = list(p.glob("RS_Audit_Report_*.csv"))
        stamps = [a.stem.replace("RS_Audit_Report_", "") for a in audits]
        print(f"  {p.name}: {stamps}")

# pipeline / profile for 212031
for pat in ["BRT_Pipeline_Timings_20260731_212031*", "BRT_Profile_Symbols_260731212031*", "RS_ImproveHints_260731212031*"]:
    hits = list((ROOT / "drive").glob(pat))
    print(pat, "->", [h.name for h in hits])

# fat GAP_DOWN: exit worse than -12% stop (gap past stop)
def gap_fat(stamp):
    with open(ROOT / f"drive/RS_Closed_{stamp}.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    def fnum(x):
        try:
            return float(str(x).replace("%", "").replace(",", ""))
        except Exception:
            return None
    gd = [r for r in rows if r.get("EXIT_TYPE") == "GAP_DOWN"]
    pcts = [fnum(r["PNL_PCT"]) for r in gd]
    pcts = [p for p in pcts if p is not None]
    pnls = [fnum(r["PNL_DOLLARS"]) for r in gd]
    pnls = [p for p in pnls if p is not None]
    # fat = gap down worse than nominal -12% stop
    fat = [p for p in pcts if p < -12.01]
    mild = [p for p in pcts if p >= -12.01]
    print(f"\n{stamp} GAP_DOWN n={len(gd)} pnl={sum(pnls):,.0f} avg_pct={sum(pcts)/len(pcts):.2f}")
    print(f"  worse-than-stop (fat): {len(fat)} avg={sum(fat)/len(fat) if fat else 0:.2f} min={min(fat) if fat else 0:.2f}")
    print(f"  at/near-stop: {len(mild)}")
    # rate
    print(f"  GAP_DOWN rate: {100*len(gd)/len(rows):.1f}%  fat rate: {100*len(fat)/len(rows):.1f}%")

gap_fat("260731212031")
gap_fat("260731204706")

# Confirm identical levers except max_atr
cand_audit = list(csv.DictReader(open(ROOT / "drive/RS_Audit_Report_260731212031.csv", encoding="utf-8")))[0]
ctrl_audit = list(csv.DictReader(open(ROOT / "drive/RS_Audit_Report_260731204706.csv", encoding="utf-8")))[0]
focus = [
    "stop_pct","target_pct","atr_days","atr_stop","atr_target","max_atr_pct_at_trigger",
    "rs_spy_int_tc_not_weak","sell_breakdown","too_high_multiplier","growth_filter_enabled",
    "block_entries_when_spy_int_weak","exit_when_spy_int_turns_weak","rs_require_tc_strong",
    "rs_max_pct_below_52w_high","min_spy_compare_1y_at_trigger","stop_order_gap_fill_at_open",
]
print("\nKey levers:")
for k in focus:
    print(f"  {k}: cand={cand_audit.get(k)} ctrl={ctrl_audit.get(k)} {'DIFF' if str(cand_audit.get(k))!=str(ctrl_audit.get(k)) else ''}")
