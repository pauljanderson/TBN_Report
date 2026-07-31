from pathlib import Path
p = Path(r"C:\Users\songg\Downloads\stockresearch\tools\run_rs_atr_pct_filter_opt.py")
t = p.read_text(encoding="utf-8")
old = '''            f"- **Verdict:** {recommendations.get('verdict')}",
            "",
            f"Rationale: {recommendations.get('notes', '')}",'''
new = '''            f"- **Verdict:** {recommendations.get('verdict')}",
            "",
            f"- **Baseline:** {recommendations.get('baseline_detail', 'n/a')}",
            f"- **Best min-only (scored):** {recommendations.get('best_min_detail', 'n/a')}",
            f"- **Best max-only (scored):** {recommendations.get('best_max_detail', 'n/a')}",
            f"- **Best both (scored):** {recommendations.get('best_both_detail', 'n/a')}",
            "",
            f"Rationale: {recommendations.get('notes', '')}",'''
if old in t:
    t = t.replace(old, new, 1)
    p.write_text(t, encoding="utf-8")
    print("md section updated")
else:
    print("md marker missing")
