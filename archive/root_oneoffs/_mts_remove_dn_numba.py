from pathlib import Path

p = Path("stock_analysis/rocket_MTS.py")
text = p.read_text(encoding="utf-8")

s = text.index("def _brt_active_zone_dn_bar(")
e = text.index("\ndef _brt_make_entry_gate_query_fns(", s)
text = text[:s] + text[e + 1 :]

s = text.index("# Optional Numba JIT for sheet AQ/AK precompute")
e = text.index("\ndef run_brt_backtest(", s)
text = text[:s] + "\n\n" + text[e + 1 :]

p.write_text(text, encoding="utf-8")
print("removed dn_bar and numba aq stack")
