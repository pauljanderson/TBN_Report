from pathlib import Path
Path(r"tools/_googl_gatebleed_verify.py").write_text("""#!/usr/bin/env python3
from __future__ import annotations
import io, sys
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
import pandas as pd
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))
import rocket_brt as rb
from wpbr_zones import compute_wpbr_touch_stream
DATA = REPO / "data" / "newdata" / "data" / "GOOGL.csv"
SPY = REPO / "data" / "newdata" / "data" / "SPY.csv"
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "GOOGL"
ENG_CLOSED = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_retest_2016" / "WPBR_Closed_260722105625.csv"
MIN_DATE = "2016-01-01"
KW = dict(band_pct=0.015, strong_pre_pivot_bars=3, strong_pre_pivot_pct=0.10, strong_post_pivot_bars=3, strong_post_pivot_pct=0.10, strong_pivot_mode="either", breakout_confirmation=0.03, max_days_after_retest=2, retest_mode="stop_looking", zone_price_round_decimals=2)

def nd(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return None

def make_cfg():
    base = asdict(rb.BRTConfig())
    base.update(dict(wpbr_zones=True, brt_zones=False, yh_zones=False, vec_zones=False, band_pct=0.015, strong_pre_pivot_bars=3, strong_pre_pivot_pct=0.10, strong_post_pivot_bars=3, strong_post_pivot_pct=0.10, strong_pivot_mode="either", wpbr_breakout_confirmation=0.03, wpbr_max_days_after_retest=2, wpbr_retest_mode="stop_looking", wpbr_second_chance_after_win=False, growth_filter_enabled=False, min_spy_compare_1y_at_trigger=-1000.0, ind_score_weights_path="", too_high_multiplier=0.0, target_pct=1.22, stop_pct=0.89, stop_pct_is_multiplier=True, entry_start_date="2016-01-01", use_indicators=False, indicator_buy="off", zone_price_round_decimals=2))
    return rb.BRTConfig(**base)

def bar_date(idx, b):
    try:
        bi = int(b)
    except Exception:
        return None
    if bi < 0 or bi >= len(idx):
        return None
    return idx[bi].strftime("%Y-%m-%d")

def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
    idx = df.index
    sheet = pd.read_csv(OUT / "trades.tsv", sep="\t", dtype=str)
    sheet_entries = [nd(r.get("Entry Date")) for _, r in sheet.iterrows()]
    sheet_entries = [e for e in sheet_entries if e]
    stream = compute_wpbr_touch_stream(df, **KW)
    raw = []
    for opp in stream.get("wpbr_entry_opportunities") or []:
        fd = bar_date(idx, opp.get("entry_fill_bar"))
        if fd and fd >= MIN_DATE:
            raw.append(fd)
    closed_old = pd.read_csv(ENG_CLOSED, dtype=str)
    closed_old = closed_old[closed_old["SYMBOL"] == "GOOGL"]
    old_entries = [nd(x) for x in closed_old["DATE_OPENED"].tolist() if nd(x)]
    cfg = make_cfg()
    ph, pl, php, plp = rb.compute_pivots(df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m, realtime_filter_enabled=cfg.realtime_filter_enabled)
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    bench = pd.read_csv(SPY, index_col=0, parse_dates=True).sort_index() if SPY.exists() else None
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = rb.run_brt_backtest("GOOGL", df, cfg, php, plp, struct, l3, benchmark_df=bench)
    live_rows = []
    for tr in out[0]:
        e = nd(getattr(tr, "date_opened", None))
        if not e:
            continue
        live_rows.append(dict(entry=e, exit=nd(getattr(tr, "date_closed", None)), ep=getattr(tr, "entry_price", None), xp=getattr(tr, "exit_price", None), xt=getattr(tr, "exit_type", ""), pnl=getattr(tr, "pnl_pct", None)))
    live_entries = [r["entry"] for r in live_rows]
    def hits(entries):
        return sum(1 for e in sheet_entries if e in set(entries))
    lines = []
    def P(s=""):
        lines.append(s); print(s)
    P("=== GOOGL gate-bleed verify ===")
    P("Sheet trades: %d -> %s" % (len(sheet_entries), sheet_entries))
    P("Raw WPBR fills: %d" % len(raw))
    P("Sheet in RAW: %d / %d" % (hits(raw), len(sheet_entries)))
    P("Old stamp serialized: %d -> %s" % (len(old_entries), old_entries))
    P("Sheet in OLD serialized: %d / %d" % (hits(old_entries), len(sheet_entries)))
    P("Live gatebleed serialized: %d" % len(live_entries))
    for r in live_rows:
        tag = "MATCH-SHEET" if r["entry"] in sheet_entries else "engine-only"
        P("  %s -> %s %s ep=%s [%s]" % (r["entry"], r["exit"], r["xt"], r["ep"], tag))
    P("Sheet in LIVE serialized: %d / %d" % (hits(live_entries), len(sheet_entries)))
    P("Sheet NOT in raw: %s" % [e for e in sheet_entries if e not in set(raw)])
    P("Sheet NOT in live: %s" % [e for e in sheet_entries if e not in set(live_entries)])
    (OUT / "_gatebleed_verify_out.txt").write_text("\\n".join(lines) + "\\n", encoding="utf-8")
    rows = ["DATE_OPENED,DATE_CLOSED,ENTRY_PRICE,EXIT_PRICE,EXIT_TYPE,PNL_PCT"]
    for r in live_rows:
        rows.append("%s,%s,%s,%s,%s,%s" % (r["entry"], r["exit"], r["ep"], r["xp"], r["xt"], r["pnl"]))
    (OUT / "engine_gatebleed_closed.csv").write_text("\\n".join(rows) + "\\n", encoding="utf-8")
    print("Wrote outputs under GOOGL/")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
""", encoding="utf-8")
print("wrote verify script")
