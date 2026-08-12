import json
from pathlib import Path

p = Path(r"C:\Users\songg\Downloads\stockresearch\_tmp_rs_sameday_cluster_trades.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("source", d["source"])
print("missing_ind", d["missing_ind_diff"])
for day in d["days"]:
    s = day["summary"]
    prior = "N/A" if s["avg_prior_hold"] is None else f"{s['avg_prior_hold']:.1f}"
    print()
    print(
        f"== {day['date']} N={s['n']} WR={s['wr']:.1f}% "
        f"avgPNL%={s['avg_pnl_pct']:+.2f} avgIND={s['avg_ind_diff']:.1f} "
        f"avgPriorHold={prior} sum$={s['sum_pnl_dollars']:,.0f}"
    )
    print(f"{'SYM':6} {'DH':>4} {'PNL%':>8} {'PNL$':>10} {'EXIT':12} {'IND':>4} {'SCORE':>7} {'PRIOR':>7}")
    for t in day["trades"]:
        pr = "N/A" if t["prior_avg_days"] is None else f"{t['prior_avg_days']:.1f}"
        score = "—" if t["ind_score"] is None else f"{t['ind_score']:.2f}"
        print(
            f"{t['symbol']:6} {t['days_held']:4.0f} {t['pnl_pct']:+8.2f} "
            f"{t['pnl_dollars']:10.0f} {t['exit_type']:12} {t['ind_diff']:4.0f} "
            f"{score:>7} {pr:>7}"
        )
