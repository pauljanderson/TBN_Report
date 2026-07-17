"""One-off: run NVDA BRT under a few configs; compare to STONK_DATA sheet trades."""
from __future__ import annotations

from pathlib import Path

from rocket_brt_og import (
    BRTConfig,
    load_csv,
    compute_pivots,
    compute_market_structure,
    compute_touch_stream,
    run_brt_backtest,
    _load_benchmark_local,
)


def fmt_iso(s: str) -> str:
    if not s or len(s) < 8:
        return s or ""
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def run_nvda(cfg: BRTConfig, label: str) -> None:
    data_dir = Path(r"C:\Users\songg\Downloads\stockresearch\data\newdata\data")
    sym = "NVDA"
    df = load_csv(str(data_dir / f"{sym}.csv"))
    benchmark_df = _load_benchmark_local(data_dir)
    ph, pl, php, plp = compute_pivots(
        df,
        cfg.pivot_k,
        cfg.pivot_d,
        cfg.pivot_disp,
        cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, ph, pl, php, plp)
    l3 = compute_touch_stream(
        df,
        ph,
        pl,
        php,
        plp,
        cfg.band_pct,
        cfg.lookback_long,
        cfg.touch_threshold,
        cfg.lookback_short,
        strong_pivots_enabled=cfg.strong_pivots_enabled,
        strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
        strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
        strong_post_pivot_bars=cfg.strong_post_pivot_bars,
        strong_post_pivot_pct=cfg.strong_post_pivot_pct,
        strong_pivot_mode=cfg.strong_pivot_mode,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    closed, _op, *_ = run_brt_backtest(sym, df, cfg, php, plp, struct, l3, benchmark_df=benchmark_df)
    print(f"\n=== {label} ===")
    print(
        f"touch_threshold={cfg.touch_threshold} strong_pivots_enabled={cfg.strong_pivots_enabled} "
        f"strong_pivot_mode={cfg.strong_pivot_mode!r} pre={cfg.strong_pre_pivot_bars}/{cfg.strong_pre_pivot_pct} "
        f"post={cfg.strong_post_pivot_bars}/{cfg.strong_post_pivot_pct}"
    )
    print(f"Closed trades: {len(closed)}")
    hdr = f"{'Entry':<12} {'Entry$':>8} {'Exit':<12} {'Exit$':>8} {'PnL%':>8} {'Days':>5} {'Type':<12} {'PnL$':>12}"
    print(hdr)
    for t in closed:
        ed = fmt_iso(t.date_opened)
        xd = fmt_iso(t.date_closed)
        print(
            f"{ed:<12} {t.entry_price:8.2f} {xd:<12} {t.exit_price:8.2f} "
            f"{t.pnl_pct:7.2f}% {t.days_held:5d} {t.exit_type:<12} {t.pnl_dollars:12.2f}"
        )


def main() -> None:
    # A) Code defaults (touch_threshold=2 per sheet, strong pre / sheet AE)
    run_nvda(BRTConfig(), "A: BRTConfig() defaults (touch=2, strong pre)")
    # B–D: optional higher-touch stress tests (not sheet default)
    run_nvda(
        BRTConfig(touch_threshold=6, strong_pivots_enabled=True, strong_pivot_mode="pre"),
        "B: touch_threshold=6 + strong pre",
    )
    run_nvda(
        BRTConfig(touch_threshold=6, strong_pivots_enabled=False),
        "C: touch_threshold=6, strong_pivots_enabled=False",
    )
    run_nvda(
        BRTConfig(
            touch_threshold=6,
            strong_pivots_enabled=True,
            strong_pivot_mode="post",
        ),
        "D: touch_threshold=6 + strong_pivot_mode=post (lookahead follow-through)",
    )


if __name__ == "__main__":
    main()
