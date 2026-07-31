from pathlib import Path
p = Path(r"C:\Users\songg\Downloads\stockresearch\stock_analysis\rocket_brt.py")
text = p.read_text(encoding="utf-8")
helper = """def _atr_pct_at_trigger_gate_blocks(
    cfg: BRTConfig,
    atr_14_arr: np.ndarray,
    close_arr: np.ndarray,
    signal_t: int,
) -> bool:
    \"\"\"True when ATR_PCT_AT_TRIGGER fails min/max (0 = off). Trigger bar only.\"\"\"
    min_trig = _cfg_min_atr_pct_trigger(cfg)
    max_trig = _cfg_max_atr_pct_trigger(cfg)
    if min_trig <= 0.0 and max_trig <= 0.0:
        return False
    _, atr_pct = _atr_14_and_pct_at_bar(atr_14_arr, close_arr, int(signal_t))
    if min_trig > 0.0 and (
        atr_pct is None or not np.isfinite(float(atr_pct)) or float(atr_pct) < min_trig
    ):
        return True
    if max_trig > 0.0 and (
        atr_pct is None or not np.isfinite(float(atr_pct)) or float(atr_pct) > max_trig
    ):
        return True
    return False


"""
needle = "def _upper_wick_atr_min_at_trigger_gate_blocks("
if "_atr_pct_at_trigger_gate_blocks" not in text:
    text = text.replace(needle, helper + needle, 1)
old_atr = """    min_trig = _cfg_min_atr_pct_trigger(cfg)
    max_trig = _cfg_max_atr_pct_trigger(cfg)
    if min_trig > 0.0 or max_trig > 0.0:
        _, atr_pct_trig = _atr_14_and_pct_at_bar(atr_14_arr, close_arr, signal_t)
        if min_trig > 0.0:
            if atr_pct_trig is None or not np.isfinite(float(atr_pct_trig)) or float(atr_pct_trig) < min_trig:
                return True
        if max_trig > 0.0:
            if atr_pct_trig is None or not np.isfinite(float(atr_pct_trig)) or float(atr_pct_trig) > max_trig:
                return True"""
new_atr = """    if _atr_pct_at_trigger_gate_blocks(cfg, atr_14_arr, close_arr, signal_t):
        return True"""
if old_atr in text:
    text = text.replace(old_atr, new_atr, 1)
gate_needle = """            if _upper_wick_atr_min_at_trigger_gate_blocks(
                cfg, high_arr, open_arr, close_arr, atr_14_arr, t
            ):
                continue
            if _mandatory_ind_states_gate_blocks(cfg, _sym_indicator_pre_rs, t, _cfg_entry_side_rs):"""
gate_repl = """            if _upper_wick_atr_min_at_trigger_gate_blocks(
                cfg, high_arr, open_arr, close_arr, atr_14_arr, t
            ):
                continue
            if _atr_pct_at_trigger_gate_blocks(cfg, atr_14_arr, close_arr, t):
                continue
            if _mandatory_ind_states_gate_blocks(cfg, _sym_indicator_pre_rs, t, _cfg_entry_side_rs):"""
if gate_repl not in text and gate_needle in text:
    text = text.replace(gate_needle, gate_repl, 1)
p.write_text(text, encoding="utf-8")
print("patched ok")
