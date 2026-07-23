#!/usr/bin/env python3
"""AMD WPBR gate-bleed verify: stamp closed vs live post-fix serialization.

Compares sheet-matching serialized fills under:
  A) MarkTen stamp 260722105625 (pre gate-bleed fix closed trades)
  B) Live run_brt_backtest with current rocket_brt.py (WPBR skips all BRT gates)

Outputs under drive/wpbr_sheet_reconcile/AMD/_gatebleed_amd/
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

import rocket_brt as rb  # noqa: E402
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

SYMBOL = "AMD"
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "AMD" / "_gatebleed_amd"
OUT.mkdir(parents=True, exist_ok=True)
DATA = REPO / "data" / "newdata" / "data" / "AMD.csv"
SPY = REPO / "data" / "newdata" / "data" / "SPY.csv"
TRADES = REPO / "drive" / "wpbr_sheet_reconcile" / "AMD" / "trades.tsv"
ENG_CLOSED = (
    REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_retest_2016"
    / "WPBR_Closed_260722105625.csv"
)
STAMP = "260722105625"
MIN_DATE = "2016-01-01"

WPBR_STREAM_KW = dict(
    band_pct=0.015,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_pivot_mode="either",
    breakout_confirmation=0.03,
    max_days_after_retest=2,
    retest_mode="stop_looking",
    zone_price_round_decimals=2,
)


def nd(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return None


def make_cfg() -> rb.BRTConfig:
    base = asdict(rb.BRTConfig())
    base.update(
        {
            "wpbr_zones": True,
            "brt_zones": False,
            "yh_zones": False,
            "vec_zones": False,
            "band_pct": 0.015,
            "strong_pre_pivot_bars": 3,
            "strong_pre_pivot_pct": 0.10,
            "strong_post_pivot_bars": 3,
            "strong_post_pivot_pct": 0.10,
            "strong_pivot_mode": "either",
            "wpbr_breakout_confirmation": 0.03,
            "wpbr_max_days_after_retest": 2,
            "wpbr_retest_mode": "stop_looking",
            "wpbr_second_chance_after_win": False,
            "growth_filter_enabled": False,
            "min_spy_compare_1y_at_trigger": -1000.0,
            "ind_score_weights_path": "",
            "too_high_multiplier": 0.0,
            "target_pct": 1.22,
            "stop_pct": 0.89,
            "stop_pct_is_multiplier": True,
            "entry_start_date": "2016-01-01",
            "use_indicators": False,
            "indicator_buy": "off",
            "zone_price_round_decimals": 2,
        }
    )
    return rb.BRTConfig(**base)


def run_backtest(df: pd.DataFrame, cfg: rb.BRTConfig):
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    bench = None
    if SPY.exists():
        bench = pd.read_csv(SPY, index_col=0, parse_dates=True).sort_index()
    block_reasons: dict[str, int] = {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = rb.run_brt_backtest(
            SYMBOL, df, cfg, php, plp, struct, l3,
            benchmark_df=bench, profile_block_reasons=block_reasons,
        )
    closed = out[0]
    return closed, buf.getvalue(), block_reasons


def closed_rows(closed):
    rows = []
    for t in closed:
        rows.append({
            "entry": nd(getattr(t, "date_opened", "")),
            "exit": nd(getattr(t, "date_closed", "")),
            "entry_px": float(getattr(t, "entry_price", 0.0) or 0.0),
            "exit_px": float(getattr(t, "exit_price", 0.0) or 0.0),
            "exit_type": str(getattr(t, "exit_type", "") or ""),
            "pnl_pct": float(getattr(t, "pnl_pct", 0.0) or 0.0),
        })
    rows.sort(key=lambda r: r["entry"] or "")
    return rows


def main() -> int:
    df = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
    idx = df.index

    # sheet trades
    st = pd.read_csv(TRADES, sep="\t", dtype=str)
    sheet = []
    for _, r in st.iterrows():
        e = nd(r.get("Entry Date"))
        if e:
            sheet.append(e)
    sheet_set = set(sheet)

    # raw fills (live zones)
    stream = compute_wpbr_touch_stream(df, **WPBR_STREAM_KW)
    raw_fills = sorted(
        pd.Timestamp(idx[b]).strftime("%Y-%m-%d")
        for b in (stream.get("wpbr_entry_fill_bars") or [])
        if int(b) >= 0
    )
    raw_set = {d for d in raw_fills if d >= MIN_DATE}

    # stamp closed
    stamp = pd.read_csv(ENG_CLOSED, dtype=str)
    stamp = stamp[stamp["SYMBOL"] == SYMBOL]
    stamp_entries = []
    for _, r in stamp.iterrows():
        e = nd(r["DATE_OPENED"])
        if e:
            stamp_entries.append(e)
    stamp_set = set(stamp_entries)

    # live post-fix
    cfg = make_cfg()
    closed, stdout, blocks = run_backtest(df, cfg)
    live_rows = closed_rows(closed)
    live_entries = [r["entry"] for r in live_rows if r["entry"]]
    live_set = set(live_entries)

    stamp_raw = sum(1 for d in sheet if d in raw_set)
    stamp_ser = sum(1 for d in sheet if d in stamp_set)
    live_ser = sum(1 for d in sheet if d in live_set)

    lines = []
    def P(s=""):
        lines.append(s)
        print(s)

    P(f"# AMD WPBR gate-bleed verify ({STAMP} vs live post-fix)")
    P("")
    P(f"Sheet trades: {len(sheet)}")
    P(f"Raw WPBR fills (>=2016, live zones): {len(raw_set)}")
    P(f"Stamp serialized AMD: {len(stamp_entries)}")
    P(f"Live serialized AMD (post gate-bleed fix): {len(live_entries)}")
    P("")
    P("| Metric | Stamp (pre-fix closed) | Live (post-fix) |")
    P("|---|---|---|")
    P(f"| Sheet ∩ raw fills | {stamp_raw}/{len(sheet)} | {stamp_raw}/{len(sheet)} |")
    P(f"| Sheet ∩ serialized | **{stamp_ser}/{len(sheet)}** | **{live_ser}/{len(sheet)}** |")
    P("")
    P("### Sheet trade × raw × stamp-ser × live-ser")
    P("")
    P("| Entry | Raw | Stamp ser | Live ser |")
    P("|---|---|---|---|")
    for d in sheet:
        P(
            f"| {d} | "
            f"{'YES' if d in raw_set else 'no'} | "
            f"{'YES' if d in stamp_set else 'no'} | "
            f"{'YES' if d in live_set else 'no'} |"
        )
    P("")
    P("### Live serialized trades")
    for r in live_rows:
        tag = "MATCH-SHEET" if r["entry"] in sheet_set else "engine-only"
        P(f"- `{r['entry']}` {r['entry_px']:.2f} → `{r['exit']}` {r['exit_px']:.2f} "
          f"{r['pnl_pct']:.2f}% {r['exit_type']} [{tag}]")
    P("")
    P("### Stamp serialized trades")
    for d in stamp_entries:
        tag = "MATCH-SHEET" if d in sheet_set else "engine-only"
        P(f"- `{d}` [{tag}]")
    P("")
    P(f"Block reasons (live): {dict(sorted(blocks.items(), key=lambda x: -x[1])[:20])}")
    P("")
    gained = sorted(sheet_set & live_set - stamp_set)
    lost = sorted(sheet_set & stamp_set - live_set)
    P(f"Sheet fills newly serialized after fix: {gained}")
    P(f"Sheet fills lost vs stamp: {lost}")
    P(f"Cascade leftovers (sheet∩raw but not live-ser): "
      f"{sorted(sheet_set & raw_set - live_set)}")

    report = "\n".join(lines) + "\n"
    (OUT / "gatebleed_verify.md").write_text(report, encoding="utf-8")
    (OUT / "live_closed.csv").write_text(
        "entry,exit,entry_px,exit_px,pnl_pct,exit_type\n"
        + "\n".join(
            f"{r['entry']},{r['exit']},{r['entry_px']},{r['exit_px']},{r['pnl_pct']},{r['exit_type']}"
            for r in live_rows
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "stdout_tail.txt").write_text(stdout[-8000:], encoding="utf-8")
    print(f"\nWrote {OUT / 'gatebleed_verify.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
