from pathlib import Path
p = Path(r"C:\Users\songg\Downloads\stockresearch\tools\run_rs_atr_pct_filter_opt.py")
t = p.read_text(encoding="utf-8")
old = '''def _score(row: dict) -> float:
    """Rank by PF then PNL; require enough trades."""
    trades = float(row.get("trades") or 0)
    pf = float(row.get("pf") or 0)
    pnl = float(row.get("pnl") or 0)
    if trades < 50:
        return -1e18
    return pf * 1e9 + pnl'''
new = '''def _score(row: dict) -> float:
    """Rank arms: PF primary, PNL secondary, lower MaxDD tertiary."""
    trades = float(row.get("trades") or 0)
    pf = float(row.get("pf") or 0)
    pnl = float(row.get("pnl") or 0)
    maxdd = abs(float(row.get("maxdd") or 0))
    if trades < 50:
        return -1e18
    return pf * 1e12 + pnl * 1e3 - maxdd * 1e6'''
if old not in t:
    raise SystemExit("score block not found")
t = t.replace(old, new, 1)
marker = '            "## Recommendations",'
insert = '''            "",
            "**Scoring:** composite = PF (primary) + PNL/1000 - MaxDD penalty. "
            "Production guard: beat baseline PF with PNL >= 85% baseline and MaxDD <= 115% baseline.",
            "",
            "## Recommendations",'''
if "Scoring:** composite" not in t and marker in t:
    t = t.replace(marker, insert, 1)
# Expand recommendations dict with baseline metrics for parent agent
old_recs = '''    recs = {
        "best_min": ba["label"] if ba else "n/a",
        "best_max": bb["label"] if bb else "n/a",
        "best_both": bc["label"] if bc else "n/a",
        "verdict": verdict,
        "notes": notes,
    }'''
new_recs = '''    def _fmt(r: Optional[dict]) -> str:
        if not r:
            return "n/a"
        return (
            f"{r['label']}: trades={r.get('trades')} WR={float(r.get('wr') or 0):.1f}% "
            f"PF={float(r.get('pf') or 0):.3f} PNL={float(r.get('pnl') or 0):.0f} "
            f"MaxDD={float(r.get('maxdd') or 0):.2f} exp={float(r.get('expectancy') or 0):.4f}"
        )

    baseline_line = _fmt(baseline)
    notes = (
        f"baseline [{baseline_line}]; "
        f"best_min [{_fmt(ba)}]; best_max [{_fmt(bb)}]; best_both [{_fmt(bc)}]. "
        f"Arms with identical trade counts to baseline before fix are invalid; post-fix counts must differ when min/max > 0."
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
    }'''
if old_recs in t:
    # remove duplicate notes assignment before recs - find and replace block from notes = to recs
    start = t.index("    notes = (")
    end = t.index("    recs = {")
    # keep verdict block, replace notes+recs
    verdict_start = t.rfind("    verdict = ", 0, end)
    before = t[:verdict_start]
    after = t[t.index("    write_results_md", end):]
    mid = '''    def _fmt(r: Optional[dict]) -> str:
        if not r:
            return "n/a"
        return (
            f"{r['label']}: trades={r.get('trades')} WR={float(r.get('wr') or 0):.1f}% "
            f"PF={float(r.get('pf') or 0):.3f} PNL={float(r.get('pnl') or 0):.0f} "
            f"MaxDD={float(r.get('maxdd') or 0):.2f} exp={float(r.get('expectancy') or 0):.4f}"
        )

'''
    # extract verdict section
    verdict_end = t.index("\n    notes = (", verdict_start)
    verdict_block = t[verdict_start:verdict_end]
    mid += verdict_block + "\n\n"
    mid += '''    baseline_line = _fmt(baseline)
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
    t = before + mid + after
else:
    print("recs block patch skipped")
p.write_text(t, encoding="utf-8")
print("opt script updated")
