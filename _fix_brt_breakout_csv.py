"""Repair rocket_brt.py: replace corrupted write_brt_breakout_and_retest body and restore run_brt_backtest def."""
from pathlib import Path

p = Path(__file__).resolve().parent / "stock_analysis" / "rocket_brt.py"
text = p.read_text(encoding="utf-8")
start = text.find('        retest_row = "" if rb is None else str(int(rb) + int(r.get("_first_row", 2)))')
if start == -1:
    raise SystemExit("start marker not found")
doc = '    """\n    One trade at a time. Entry at next day open. Stop/Target from spec.'
end = text.find(doc, start)
if end == -1:
    raise SystemExit("doc marker not found")
replacement = '''        fr = int(r.get("excel_first_row", 2))
        retest_row_str = "" if rb is None else str(int(rb) + fr)
        riso = str(r.get("retest_iso") or "")
        retest_date_str = _iso_yyyymmdd_to_mdy(riso) if riso else ""
        out_rows.append(
            [
                str(r["SYMBOL"]),
                _iso_yyyymmdd_to_mdy(str(r.get("breakout_iso") or "")),
                zone_lo,
                zone_hi,
                str(int(r["main_row"])),
                str(int(r["scan_start_row"])),
                retest_row_str,
                retest_date_str,
            ]
        )
    outp = Path(path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with open(outp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(out_rows)


def run_brt_backtest(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    ph_price: pd.Series,
    pl_price: pd.Series,
    struct: dict,
    level3: dict,
    zone_entries_debug: Optional[list] = None,
    benchmark_df: Optional[pd.DataFrame] = None,
    profile_beta_times: Optional[list] = None,
    reference_stats: Optional[dict[str, tuple[float, float]]] = None,
    profile_block_reasons: Optional[dict[str, int]] = None,
    profile_backtest_sections: Optional[dict[str, float]] = None,
    cprofile_magic_touch: Optional[cProfile.Profile] = None,
    cprofile_pending_sheet_prep: Optional[cProfile.Profile] = None,
    breakout_retest_rows_out: Optional[list] = None,
) -> tuple[list[BRTTrade], Optional[BRTTrade], list[dict], list[dict]]:
'''
new_text = text[:start] + replacement + text[end:]
p.write_text(new_text, encoding="utf-8")
print("patched", p, "removed", end - start, "chars")
