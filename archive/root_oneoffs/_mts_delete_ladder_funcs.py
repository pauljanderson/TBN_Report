from pathlib import Path

p = Path("stock_analysis/rocket_MTS.py")
text = p.read_text(encoding="utf-8")

# 1) Remove ladder + parity CSV + dn_bar between helpers
s1 = text.index("def _compute_sheet_ladder_de_df_dg_all_modes(")
e1 = text.index("\ndef _fmt_par(x: Any)", s1)
text = text[:s1] + text[e1:]

# 2) Remove _brt_active_zone_dn_bar
s2 = text.index("def _brt_active_zone_dn_bar(")
# end at next def at column 0 after this function
rest = text[s2 + 1 :]
next_def = rest.find("\ndef _brt_make_entry_gate_query_fns(")
if next_def == -1:
    raise SystemExit("anchor2")
text = text[:s2] + rest[next_def + 1 :]

# 3) Remove Numba AQ/AK through _sheet_ladder_aq_ak_and_gate_fns (keep _SheetLadderGateFns alias)
s3 = text.index("# Optional Numba JIT for sheet AQ/AK precompute")
e3 = text.index("\ndef run_brt_backtest(", s3)
text = text[:s3] + "\n\n" + text[e3 + 1 :]

p.write_text(text, encoding="utf-8")
print("deleted ladder helpers")
