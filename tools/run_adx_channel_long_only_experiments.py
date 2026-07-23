"""Long-only ADX channel-breakout experiment vs real baselines (non-production).

Pre-registered entry: Wilder ADX(15)<20, 10-bar channel stop (next bar only).
Universe: production BRT liquid whitelist from run_brt.bat (not full DuckDB).
Costs: 10 bps/side + $2 round-trip on all strategy runs; 20 bps stress on selected.
OOS folds vs SPY buy-and-hold and production BRT on the same universe/period.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from davey_experiment_common import DATA_DIR, Arm, REPO, run_jobs, score, write_csv

ROOT = REPO / "drive" / "davey_experiments" / "adx_channel_long_only"
INITIAL_CAPITAL = 500_000.0

# Investable liquid list — same symbols as run_brt.bat (≈42 names). Documented in comparison.md.
BRT_LIQUID_SYMBOLS = (
    "AAPL,ABBV,ACN,ADBE,ADI,AMAT,AMD,AMZN,AU,AVGO,BABA,BAC,CDNS,CI,CRM,CRWD,"
    "GOOG,GOOGL,HD,JPM,KR,LYV,META,MPC,MSFT,MU,NEM,NFLX,NVDA,ORCL,PFE,PG,PPTA,"
    "SHOP,TMUS,TSLA,TSM,UNH,V,WFC,WMT,XOM"
)

ADX_COMMON = (
    "entry_mode=adx_channel",
    "adx_period=15",
    "adx_max=20",
    "channel_length=10",
    "pending_stop_bars=1",
    "stop_order_gap_fill_at_open=true",
    "transaction_type=long",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "wpbr_zones=false",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=-1000",
    "too_high_multiplier=0",
    "too_low_multiplier=0",
    "stop_pct=0",
    "target_pct=0",
    "liquidate_at_end=true",
    "max_market_cap=0",
    "min_market_cap=0",
    # Explicit cost model (charged on every ADX arm unless overridden).
    "slippage_bps=10",
    "commission_per_trade=2",
    f"initial_capital={INITIAL_CAPITAL:g}",
)

# Small exit grid around prior L_S2_T3; entry fixed.
ARMS = (
    Arm("L_S15_T3", "Long ATR stop 1.5 / target 3", ("atr_stop=1.5", "atr_target=3", "target_enabled=true")),
    Arm("L_S2_T25", "Long ATR stop 2 / target 2.5", ("atr_stop=2", "atr_target=2.5", "target_enabled=true")),
    Arm("L_S2_T3", "Long ATR stop 2 / target 3", ("atr_stop=2", "atr_target=3", "target_enabled=true")),
    Arm("L_S2_T35", "Long ATR stop 2 / target 3.5", ("atr_stop=2", "atr_target=3.5", "target_enabled=true")),
    Arm("L_S25_T3", "Long ATR stop 2.5 / target 3", ("atr_stop=2.5", "atr_target=3", "target_enabled=true")),
)

# Production BRT long baseline on the same universe (from run_brt.bat; not wired to DailyRun).
BRT_COMMON = (
    "entry_mode=zones",
    "brt_zones=true",
    "yh_zones=false",
    "wpbr_zones=false",
    "vec_zones=false",
    "transaction_type=long",
    "stop_pct=0.934",
    "target_pct=1.21",
    "target_enabled=true",
    "too_high_multiplier=0",
    "band_pct=0.0154",
    "strong_pre_pivot_pct=0.081",
    "strong_post_pivot_pct=0.108",
    "strong_pre_pivot_bars=7",
    "strong_post_pivot_bars=7",
    "breakout_bars=100",
    "tight_range_threshold_pct=0.35",
    "tight_range_lookback=105",
    "sheet_breakout_scan_start_row_delta=2",
    "brt_sheet_touch=true",
    "min_spy_compare_1y_at_trigger=-12",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=true",
    "min_pivot_run_h_before_entry=0",
    "min_beta_at_trigger=0",
    "liquidate_at_end=true",
    "slippage_bps=10",
    "commission_per_trade=2",
    f"initial_capital={INITIAL_CAPITAL:g}",
)

BRT_BASELINE = Arm("BRT_PROD", "Production BRT long (same universe + costs)", ())

OOS_FOLDS = (
    ("oos_2021_2022", "2021-01-01", "2022-12-31"),
    ("oos_2023_2024", "2023-01-01", "2024-12-31"),
    ("oos_2025_2026", "2025-01-01", "2026-12-31"),
)

FEASIBILITY_SYMBOLS = "SPY,AAPL,MSFT,AMZN,NVDA,META,JPM,XOM"


def load_brt_symbols() -> str:
    bat = (REPO / "run_brt.bat").read_text(encoding="utf-8", errors="replace")
    match = re.search(r'set "BRT_SYMBOLS=([^"]+)"', bat)
    if match:
        return match.group(1)
    return BRT_LIQUID_SYMBOLS


def _load_ohlc(symbol: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    close_col = "Close" if "Close" in df.columns else "Adj Close"
    if close_col not in df.columns:
        return None
    out = df[[close_col]].rename(columns={close_col: "Close"}).dropna()
    return out if not out.empty else None


def _slice_period(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)]


def _max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity / peak - 1.0) * 100.0
    return float(-dd.min()) if len(dd) else 0.0


def _ann_ror(total_return: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = max((end - start).days / 365.25, 1e-9)
    if total_return <= -1.0:
        return -100.0
    return ((1.0 + total_return) ** (1.0 / years) - 1.0) * 100.0


def buy_and_hold_metrics(
    *,
    label: str,
    arm_id: str,
    phase: str,
    start: str,
    end: str,
    closes: pd.Series,
    capital: float = INITIAL_CAPITAL,
) -> dict:
    """Passive buy-and-hold from first to last close in [start, end]."""
    window = closes.loc[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    if len(window) < 2:
        return {
            "id": arm_id,
            "label": label,
            "phase": phase,
            "start": start,
            "end": end,
            "ok": False,
            "metrics": {},
            "error": "insufficient price history",
        }
    entry = float(window.iloc[0])
    exit_px = float(window.iloc[-1])
    rets = window.pct_change().fillna(0.0)
    equity = capital * (1.0 + rets).cumprod()
    total_ret = exit_px / entry - 1.0
    pnl = capital * total_ret
    start_ts, end_ts = window.index[0], window.index[-1]
    metrics = {
        "Total_Trades": 1,
        "Total_PNL": pnl,
        "Profit_Factor": 0.0,
        "Max_DD": _max_drawdown_pct(equity),
        "Profit_Per_Capital_Day": pnl / max((end_ts - start_ts).days, 1),
        "Ann_ROR": _ann_ror(total_ret, start_ts, end_ts),
        "Avg_Days_Held": float((end_ts - start_ts).days),
        "Median_Days_Held": float((end_ts - start_ts).days),
        "P90_Days": float((end_ts - start_ts).days),
        "Expectancy": pnl,
        "Losing_Streak": 0,
        "Pct_PNL_Max_Symbol": 100.0,
        "Aggressive_Total_PNL": pnl,
        "Aggressive_Max_DD": _max_drawdown_pct(equity),
    }
    return {
        "id": arm_id,
        "label": label,
        "phase": phase,
        "start": start,
        "end": end,
        "ok": True,
        "metrics": metrics,
        "outdir": "",
    }


def equal_weight_bh_metrics(
    symbols: str,
    *,
    phase: str,
    start: str,
    end: str,
    capital: float = INITIAL_CAPITAL,
) -> dict:
    """Equal-weight buy-and-hold of symbols with overlapping history in the window."""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    frames: list[pd.Series] = []
    for sym in syms:
        df = _load_ohlc(sym)
        if df is None:
            continue
        window = _slice_period(df, start, end)["Close"]
        if len(window) >= 2:
            frames.append(window.rename(sym))
    if not frames:
        return {
            "id": "EW_BH",
            "label": "Equal-weight buy-and-hold of universe",
            "phase": phase,
            "start": start,
            "end": end,
            "ok": False,
            "metrics": {},
            "error": "no overlapping symbols",
        }
    panel = pd.concat(frames, axis=1).dropna(how="any")
    if len(panel) < 2:
        # fall back to forward-fill within window after requiring first/last presence
        panel = pd.concat(frames, axis=1).sort_index().ffill().bfill().dropna(how="any")
    if len(panel) < 2:
        return {
            "id": "EW_BH",
            "label": "Equal-weight buy-and-hold of universe",
            "phase": phase,
            "start": start,
            "end": end,
            "ok": False,
            "metrics": {},
            "error": "insufficient overlap",
        }
    norm = panel / panel.iloc[0]
    ew = norm.mean(axis=1)
    equity = capital * ew
    total_ret = float(ew.iloc[-1] - 1.0)
    pnl = capital * total_ret
    start_ts, end_ts = ew.index[0], ew.index[-1]
    metrics = {
        "Total_Trades": len(panel.columns),
        "Total_PNL": pnl,
        "Profit_Factor": 0.0,
        "Max_DD": _max_drawdown_pct(equity),
        "Profit_Per_Capital_Day": pnl / max((end_ts - start_ts).days, 1),
        "Ann_ROR": _ann_ror(total_ret, start_ts, end_ts),
        "Avg_Days_Held": float((end_ts - start_ts).days),
        "Median_Days_Held": float((end_ts - start_ts).days),
        "P90_Days": float((end_ts - start_ts).days),
        "Expectancy": pnl / max(len(panel.columns), 1),
        "Losing_Streak": 0,
        "Pct_PNL_Max_Symbol": 100.0 / max(len(panel.columns), 1),
        "Aggressive_Total_PNL": pnl,
        "Aggressive_Max_DD": _max_drawdown_pct(equity),
    }
    return {
        "id": "EW_BH",
        "label": f"Equal-weight BH ({len(panel.columns)} names with overlap)",
        "phase": phase,
        "start": start,
        "end": end,
        "ok": True,
        "metrics": metrics,
        "outdir": "",
    }


def spec(
    arm: Arm,
    phase: str,
    workers: int,
    symbols: str,
    *,
    common: tuple[str, ...] = ADX_COMMON,
    prefix: str = "ADX",
    start: str = "",
    end: str = "",
    skip: bool = False,
) -> dict:
    return {
        "root": ROOT,
        "prefix": prefix,
        "common_values": common,
        "arm": arm,
        "phase": phase,
        "workers": workers,
        "symbols": symbols,
        "start": start,
        "end": end,
        "skip_existing": skip,
    }


def _m(result: dict | None, key: str, default: float = 0.0) -> float:
    if not result:
        return default
    return float((result.get("metrics") or {}).get(key, default) or default)


def write_report(results: list[dict], selected: Arm, symbols: str) -> None:
    write_csv(ROOT / "comparison.csv", results)
    by = {(r["phase"], r["id"]): r for r in results}

    fold_rows: list[str] = []
    beats_spy = beats_brt = beats_ew = valid = 0
    sel_pnl = spy_pnl = brt_pnl = ew_pnl = 0.0
    for fold, start, end in OOS_FOLDS:
        choice = by.get((fold, selected.id))
        spy = by.get((fold, "SPY_BH"))
        brt = by.get((fold, "BRT_PROD"))
        ew = by.get((fold, "EW_BH"))
        if not choice or not choice.get("ok"):
            continue
        valid += 1
        cm = choice["metrics"]
        sel_pnl += float(cm.get("Total_PNL", 0) or 0)
        if spy and spy.get("ok"):
            spy_pnl += _m(spy, "Total_PNL")
            if _m(choice, "Ann_ROR") > _m(spy, "Ann_ROR") and _m(choice, "Total_PNL") > _m(spy, "Total_PNL"):
                beats_spy += 1
        if brt and brt.get("ok"):
            brt_pnl += _m(brt, "Total_PNL")
            if (
                _m(choice, "Profit_Factor") > _m(brt, "Profit_Factor")
                and _m(choice, "Profit_Per_Capital_Day") > _m(brt, "Profit_Per_Capital_Day")
            ):
                beats_brt += 1
        if ew and ew.get("ok"):
            ew_pnl += _m(ew, "Total_PNL")
            if _m(choice, "Ann_ROR") > _m(ew, "Ann_ROR") and _m(choice, "Total_PNL") > _m(ew, "Total_PNL"):
                beats_ew += 1
        fold_rows.append(
            f"| {fold} | {_m(choice,'Total_PNL'):.0f} / {_m(choice,'Ann_ROR'):.1f} / "
            f"{_m(choice,'Profit_Factor'):.2f} / {_m(choice,'Max_DD'):.1f} | "
            f"{_m(spy,'Total_PNL'):.0f} / {_m(spy,'Ann_ROR'):.1f} / {_m(spy,'Max_DD'):.1f} | "
            f"{_m(ew,'Total_PNL'):.0f} / {_m(ew,'Ann_ROR'):.1f} / {_m(ew,'Max_DD'):.1f} | "
            f"{_m(brt,'Total_PNL'):.0f} / {_m(brt,'Ann_ROR'):.1f} / "
            f"{_m(brt,'Profit_Factor'):.2f} / {_m(brt,'Max_DD'):.1f} |"
        )

    cost10 = by.get(("costs_2021_2026", selected.id + "_COST10"))
    cost20 = by.get(("costs_2021_2026", selected.id + "_COST20"))
    cost10_ok = bool(cost10 and cost10.get("ok") and _m(cost10, "Total_PNL") > 0)
    cost20_ok = bool(cost20 and cost20.get("ok") and _m(cost20, "Total_PNL") > 0)

    # Conservative gate vs real baselines (not both-sides ADX).
    robust = (
        valid >= 2
        and beats_spy >= 2
        and beats_brt >= 2
        and sel_pnl > spy_pnl
        and cost10_ok
    )
    promising = (
        valid >= 2
        and (beats_spy + beats_brt) >= 3
        and sel_pnl > 0
        and cost10_ok
        and not robust
    )
    if robust:
        verdict = "ADOPT (experiment-only; still not DailyRun)"
    elif promising:
        verdict = "CONTINUE"
    else:
        verdict = "REJECT"

    n_sym = len([s for s in symbols.split(",") if s.strip()])
    lines = [
        "# Long-only ADX channel-breakout vs real baselines",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Protocol (pre-registered)",
        "",
        "- **Entry (fixed):** Wilder ADX(15) < 20 on a completed bar → next-bar stop at 10-bar channel.",
        "- **Sides:** long-only only.",
        f"- **Universe:** production BRT liquid whitelist from `run_brt.bat` (**{n_sym} names**). "
        "Not the full DuckDB dump. Names: `" + symbols + "`.",
        "- **Liquidity note:** ADX entry path does not apply `min_avg_volume_10d_at_entry` / market-cap "
        "gates; investability is enforced by the curated liquid list instead.",
        f"- **Capital:** initial_capital={INITIAL_CAPITAL:,.0f} (engine default sleeve scaling unchanged).",
        "- **Cost model (all ADX + BRT strategy runs):** `slippage_bps=10` per side + "
        "`commission_per_trade=2` round-trip. Selected arm also stressed at **20 bps/side + $2**.",
        "- **IS selection:** exit grid scored on entries through 2020 only; then frozen for OOS.",
        "- **OOS folds:** 2021–22 / 2023–24 / 2025–26.",
        "- **Baselines (same periods/capital):** SPY buy-and-hold; equal-weight BH of the universe; "
        "production BRT long on the same symbols with the same 10 bps + $2 costs.",
        "- **Production:** not wired into DailyRun / run_brt.bat.",
        "",
        f"**IS-selected arm:** `{selected.id}` — {selected.label}",
        f"**OOS verdict:** **{verdict}**",
        "",
        f"- Beats SPY (AnnROR **and** PNL): **{beats_spy}/{valid}** folds "
        f"(agg PNL {sel_pnl:,.0f} vs SPY {spy_pnl:,.0f}).",
        f"- Beats BRT (PF **and** PPCD): **{beats_brt}/{valid}** folds "
        f"(agg PNL vs BRT {brt_pnl:,.0f}).",
        f"- Beats equal-weight BH (AnnROR **and** PNL): **{beats_ew}/{valid}** folds "
        f"(EW agg PNL {ew_pnl:,.0f}).",
        f"- Cost10 PNL positive: {cost10_ok} ({_m(cost10,'Total_PNL'):,.0f}); "
        f"Cost20 stress positive: {cost20_ok} ({_m(cost20,'Total_PNL'):,.0f}).",
        "",
        "### OOS fold scoreboard (selected vs baselines)",
        "",
        "| fold | ADX PNL / AnnROR / PF / DD | SPY PNL / AnnROR / DD | EW PNL / AnnROR / DD | BRT PNL / AnnROR / PF / DD |",
        "|---|---:|---:|---:|---:|",
        *fold_rows,
        "",
        "### Full results table",
        "",
        "| phase | arm | trades | PNL | PF | DD | PPCD | AnnROR | avg/med/P90 hold | exp | streak | max symbol% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in sorted(results, key=lambda r: (r["phase"], r["id"])):
        if result["phase"] == "feasibility":
            continue
        m = result.get("metrics") or {}
        lines.append(
            f"| {result['phase']} | {result['id']} | {int(m.get('Total_Trades', 0) or 0)} | "
            f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} | "
            f"{float(m.get('Max_DD', 0) or 0):.1f} | {float(m.get('Profit_Per_Capital_Day', 0) or 0):.3f} | "
            f"{float(m.get('Ann_ROR', 0) or 0):.1f} | {float(m.get('Avg_Days_Held', 0) or 0):.0f}/"
            f"{float(m.get('Median_Days_Held', 0) or 0):.0f}/{float(m.get('P90_Days', 0) or 0):.0f} | "
            f"{float(m.get('Expectancy', 0) or 0):.0f} | {int(m.get('Losing_Streak', 0) or 0)} | "
            f"{float(m.get('Pct_PNL_Max_Symbol', 0) or 0):.1f} |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- Prior full-universe long-only edge was partly vs a weak both-sides ADX reference; this run "
        "re-tests against SPY / EW / BRT on a tighter universe with explicit costs.",
        "- Survivorship: BRT whitelist is today's liquid names (no delisting simulation).",
        "- Costs ignore market impact, borrow, and gap illiquidity; 20 bps is a coarse stress only.",
        "- Ann_ROR / Total_PNL for active systems use engine report conventions (sleeve scaling); "
        "passive BH uses flat $500k equity — compare directionally, not dollar-for-dollar as identical.",
        "- Still a research experiment; ADOPT does not mean wire into DailyRun.",
    ]
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--symbols", default="", help="Override universe (default: run_brt.bat list)")
    args = parser.parse_args()
    symbols = args.symbols or load_brt_symbols()
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "universe.txt").write_text(symbols.replace(",", "\n") + "\n", encoding="utf-8")

    results: list[dict] = []

    # Feasibility smoke on a tiny subset.
    results += run_jobs(
        [spec(a, "feasibility", args.workers, FEASIBILITY_SYMBOLS, skip=args.skip_existing) for a in ARMS[:2]],
        args.jobs,
    )

    # Full-period long-only grid + IS selection window.
    results += run_jobs(
        [spec(a, "full", args.workers, symbols, skip=args.skip_existing) for a in ARMS],
        args.jobs,
    )
    is_results = run_jobs(
        [spec(a, "is_to_2020", args.workers, symbols, end="2020-12-31", skip=args.skip_existing) for a in ARMS],
        args.jobs,
    )
    results += is_results
    eligible = [
        r
        for r in is_results
        if r.get("ok") and float((r.get("metrics") or {}).get("Total_Trades", 0) or 0) > 0
    ]
    if not eligible:
        write_csv(ROOT / "comparison.csv", results)
        (ROOT / "comparison.md").write_text(
            "# Long-only ADX channel-breakout vs real baselines\n\n"
            "No successful in-sample arm completed. See run logs under `runs/`.\n",
            encoding="utf-8",
        )
        print(f"[write] {ROOT / 'comparison.md'} (no eligible IS arms)")
        return 1

    selected_result = max(eligible, key=lambda r: score(r.get("metrics") or {}))
    selected = next(a for a in ARMS if a.id == selected_result["id"])
    print(f"[select] IS winner={selected.id} score={score(selected_result.get('metrics') or {}):.3f}", flush=True)

    # OOS: selected ADX + BRT baseline per fold; SPY/EW computed offline.
    oos_specs: list[dict] = []
    for fold, start, end in OOS_FOLDS:
        oos_specs.append(
            spec(selected, fold, args.workers, symbols, start=start, end=end, skip=args.skip_existing)
        )
        oos_specs.append(
            spec(
                BRT_BASELINE,
                fold,
                args.workers,
                symbols,
                common=BRT_COMMON,
                prefix="BRT",
                start=start,
                end=end,
                skip=args.skip_existing,
            )
        )
    results += run_jobs(oos_specs, args.jobs)

    spy_df = _load_ohlc("SPY")
    if spy_df is None:
        print("[warn] SPY.csv missing; SPY_BH baselines will fail", flush=True)
        spy_close = pd.Series(dtype=float)
    else:
        spy_close = spy_df["Close"]

    for fold, start, end in OOS_FOLDS:
        results.append(
            buy_and_hold_metrics(
                label="SPY buy-and-hold",
                arm_id="SPY_BH",
                phase=fold,
                start=start,
                end=end,
                closes=spy_close,
            )
        )
        results.append(equal_weight_bh_metrics(symbols, phase=fold, start=start, end=end))

    # Aggregate 2021–2026 cost stresses for selected arm.
    cost10 = Arm(
        selected.id + "_COST10",
        selected.label + " + 10bps/side + $2",
        selected.values + ("slippage_bps=10", "commission_per_trade=2"),
    )
    cost20 = Arm(
        selected.id + "_COST20",
        selected.label + " + 20bps/side + $2 stress",
        selected.values + ("slippage_bps=20", "commission_per_trade=2"),
    )
    # COST10 is already in ADX_COMMON; still run labeled arms for clear reporting.
    adx_nocost_common = tuple(v for v in ADX_COMMON if not v.startswith("slippage_bps=") and not v.startswith("commission_per_trade="))
    results += run_jobs(
        [
            spec(
                cost10,
                "costs_2021_2026",
                args.workers,
                symbols,
                common=adx_nocost_common,
                start="2021-01-01",
                end="2026-12-31",
                skip=args.skip_existing,
            ),
            spec(
                cost20,
                "costs_2021_2026",
                args.workers,
                symbols,
                common=adx_nocost_common,
                start="2021-01-01",
                end="2026-12-31",
                skip=args.skip_existing,
            ),
        ],
        args.jobs,
    )

    # Also record full-period SPY/EW for context.
    results.append(
        buy_and_hold_metrics(
            label="SPY buy-and-hold",
            arm_id="SPY_BH",
            phase="full",
            start="2000-01-01",
            end="2026-12-31",
            closes=spy_close,
        )
    )
    results.append(equal_weight_bh_metrics(symbols, phase="full", start="2000-01-01", end="2026-12-31"))

    write_report(results, selected, symbols)
    print(f"[write] {ROOT / 'comparison.md'}")
    engine_ok = all(r.get("ok") for r in results if r.get("outdir"))
    return 0 if engine_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
