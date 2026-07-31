from pathlib import Path
p = Path(r"C:\Users\songg\Downloads\stockresearch\tools\run_rs_atr_pct_filter_opt.py")
t = p.read_text(encoding="utf-8")
start = t.index("    def _beats_baseline(cand: Optional[dict]) -> bool:")
end = t.index("    write_results_md(OUT_ROOT, rows, recs)")
block = '''    def _beats_baseline(cand: Optional[dict]) -> bool:
        if not cand or not baseline:
            return False
        # Prefer higher PF with MaxDD not much worse and PNL not collapsing
        b_pf = float(baseline.get("pf") or 0)
        b_pnl = float(baseline.get("pnl") or 0)
        b_dd = abs(float(baseline.get("maxdd") or 0))
        c_pf = float(cand.get("pf") or 0)
        c_pnl = float(cand.get("pnl") or 0)
        c_dd = abs(float(cand.get("maxdd") or 0))
        if c_pf <= b_pf:
            return False
        if b_pnl > 0 and c_pnl < 0.85 * b_pnl:
            return False
        if b_dd > 0 and c_dd > 1.15 * b_dd:
            return False
        return True

    def _fmt(r: Optional[dict]) -> str:
        if not r:
            return "n/a"
        return (
            f"{r['label']}: trades={r.get('trades')} WR={float(r.get('wr') or 0):.1f}% "
            f"PF={float(r.get('pf') or 0):.3f} PNL={float(r.get('pnl') or 0):.0f} "
            f"MaxDD={float(r.get('maxdd') or 0):.2f} exp={float(r.get('expectancy') or 0):.4f}"
        )

    verdict = "no help - keep ATR filters off (baseline)"
    if _beats_baseline(bb) and (not ba or _score(bb) >= _score(ba or {})):
        if bc and _beats_baseline(bc) and _score(bc) > _score(bb):
            verdict = f"help - prefer both: {bc['label']}"
        else:
            verdict = f"help - prefer max-only: {bb['label']}"
    elif _beats_baseline(ba):
        if bc and _beats_baseline(bc) and _score(bc) > _score(ba):
            verdict = f"help - prefer both: {bc['label']}"
        else:
            verdict = f"help - prefer min-only: {ba['label']}"
    elif bc and _beats_baseline(bc):
        verdict = f"help - prefer both: {bc['label']}"
    elif bb and baseline and float(bb.get("pf") or 0) > float(baseline.get("pf") or 0):
        verdict = (
            f"marginal - max-only {bb['label']} raises PF but fails PNL/MaxDD guard; "
            "prefer neither for production"
        )

    baseline_line = _fmt(baseline)
    notes = (
        f"baseline [{baseline_line}]; "
        f"best_min [{_fmt(ba)}]; best_max [{_fmt(bb)}]; best_both [{_fmt(bc)}]. "
        "Post-fix: filtered arms must show lower trade count than baseline when min/max > 0."
    )
    recs = {
        "best_min": ba["label"] if ba else "n/a",
        "best_max": bb["label"] if bb else "n/a",
        "best_both": bc["label"] if bc else "n/a",
        "verdict": verdict,
        "notes": notes,
        "baseline_detail": baseline_line,
        "best_min_detail": _fmt(ba),
        "best_max_detail": _fmt(bb),
        "best_both_detail": _fmt(bc),
    }
'''
t = t[:start] + block + t[end:]
p.write_text(t, encoding="utf-8")
print("fixed main tail")
