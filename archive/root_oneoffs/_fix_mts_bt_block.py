from pathlib import Path

path = Path("stock_analysis/rocket_MTS.py")
text = path.read_text(encoding="utf-8")

# 1) Remove sheet_ladder_trace parameter from run_brt_backtest
text = text.replace(
    "    profile_backtest_sections: Optional[dict[str, float]] = None,\n"
    "    sheet_ladder_trace: Optional[dict[str, Any]] = None,\n"
    "    cprofile_magic_touch: Optional[cProfile.Profile] = None,",
    "    profile_backtest_sections: Optional[dict[str, float]] = None,\n"
    "    cprofile_magic_touch: Optional[cProfile.Profile] = None,",
)

# 2) Strong pivot arrays after close_arr
needle = '    close_arr = df["Close"].to_numpy(dtype=np.float64)\n    try:'
if needle not in text:
    raise SystemExit("close_arr needle missing")
text = text.replace(
    needle,
    '    close_arr = df["Close"].to_numpy(dtype=np.float64)\n'
    "    _hl_dec_bt = int(getattr(cfg, \"zone_price_round_decimals\", 2))\n"
    "    if _hl_dec_bt >= 0:\n"
    "        strong_hi_arr = np.round(high_arr, _hl_dec_bt)\n"
    "        strong_lo_arr = np.round(low_arr, _hl_dec_bt)\n"
    "    else:\n"
    "        strong_hi_arr = high_arr\n"
    "        strong_lo_arr = low_arr\n"
    "    try:",
)

# 3) Replace post-bt_init ladder block through prefetch
start = text.index('    _acc_bt("bt_init", time.perf_counter() - _t_init)\n\n    c14_lag = int(getattr(cfg, "sheet_maturity_lag_bars", 7))')
end = text.index("\n    for i in range(n - 1):", start)

NEW = r'''    _acc_bt("bt_init", time.perf_counter() - _t_init)

    lag_c14 = max(0, _effective_sheet_maturity_lag_bars(cfg))

    beta_by_bar_arr: Optional[np.ndarray] = None
    if benchmark_df is not None:
        _t_beta = time.perf_counter()
        beta_by_bar_arr = _precompute_beta_by_bar_index(df, benchmark_df, _BETA_ROLLING_WINDOW)
        _acc_bt("bt_beta_precompute", time.perf_counter() - _t_beta)

    # DO parity helper: pre-only strong pivot touch event on bar t (N/S with AD/AE-style pre check).
    do_touch_arr = np.zeros(n, dtype=bool)
    # AF/CD parity helper: confirmed strong touch price stream (pre AND post), then lagged by C14.
    confirmed_touch_arr = np.full(n, np.nan, dtype=np.float64)
    cd_touch_arr = np.full(n, np.nan, dtype=np.float64)
    pre_bars = int(getattr(cfg, "strong_pre_pivot_bars", 0))
    pre_pct = float(getattr(cfg, "strong_pre_pivot_pct", 0.0))
    post_bars = int(getattr(cfg, "strong_post_pivot_bars", 0))
    post_pct = float(getattr(cfg, "strong_post_pivot_pct", 0.0))
    _t_scd = time.perf_counter()
    if pre_bars > 0 and pre_pct > 0:
        for t in range(n):
            if ph_arr[t] > 0.0:
                do_touch_arr[t] = _strong_pivot_bar_ok(
                    t, "PH", strong_hi_arr, strong_lo_arr, n,
                    pre_bars=pre_bars,
                    pre_pct=pre_pct,
                    post_bars=0,
                    post_pct=0.0,
                    mode="pre",
                )
                # Confirmed touch (AF-style): require pre AND post.
                if post_bars > 0 and post_pct > 0:
                    if _strong_pivot_bar_ok(
                        t, "PH", strong_hi_arr, strong_lo_arr, n,
                        pre_bars=pre_bars,
                        pre_pct=pre_pct,
                        post_bars=post_bars,
                        post_pct=post_pct,
                        mode="both",
                    ):
                        confirmed_touch_arr[t] = float(ph_arr[t])
            elif pl_arr[t] > 0.0:
                do_touch_arr[t] = _strong_pivot_bar_ok(
                    t, "PL", strong_hi_arr, strong_lo_arr, n,
                    pre_bars=pre_bars,
                    pre_pct=pre_pct,
                    post_bars=0,
                    post_pct=0.0,
                    mode="pre",
                )
                if post_bars > 0 and post_pct > 0:
                    if _strong_pivot_bar_ok(
                        t, "PL", strong_hi_arr, strong_lo_arr, n,
                        pre_bars=pre_bars,
                        pre_pct=pre_pct,
                        post_bars=post_bars,
                        post_pct=post_pct,
                        mode="both",
                    ):
                        confirmed_touch_arr[t] = float(pl_arr[t])
    if lag_c14 > 0:
        for i_cd in range(lag_c14, n):
            cd_touch_arr[i_cd] = confirmed_touch_arr[i_cd - lag_c14]
    else:
        cd_touch_arr[:] = confirmed_touch_arr
    _acc_bt("bt_strong_pivot_cd_stream", time.perf_counter() - _t_scd)

    # Matured BH/BI streams + ladder-free DI / simulated DW dates (sheet_column_reference).
    mat_bh_arr, mat_bi_arr = _precompute_mat_bh_bi_stream(zl_full_arr, zh_full_arr, lag_c14, n)
    di_max_hist = int(getattr(cfg, "sheet_di_max_history_bars", 0) or 0)
    di_ok_arr, di_sel_j_arr = _precompute_di_all_zones_breakout(
        high_arr, mat_bh_arr, mat_bi_arr, n, max_hist=di_max_hist
    )
    dw_dates_set = _precompute_dw_dates_from_di_breakouts(
        low_arr, high_arr, mat_bh_arr, mat_bi_arr, di_ok_arr, di_sel_j_arr, index_iso, n
    )

    # DP parity helper: current low inside any matured BH/BI band in [i-window .. i-lag].
    def _dp_inside_any_zone(i_bar: int) -> bool:
        if i_bar < 0:
            return False
        lag = max(0, _effective_sheet_maturity_lag_bars(cfg))
        c10 = int(getattr(cfg, "dp_window_bars", 0))
        if c10 <= 0:
            c10 = int(getattr(cfg, "lookback_long", 504))
        start = max(0, i_bar - c10)
        end = i_bar - lag
        if end < 0 or end < start:
            return False
        px = float(low_arr[i_bar])
        for k in range(start, end + 1):
            zl_k = float(mat_bh_arr[k]) if k < len(mat_bh_arr) and np.isfinite(mat_bh_arr[k]) else float("nan")
            zu_k = float(mat_bi_arr[k]) if k < len(mat_bi_arr) and np.isfinite(mat_bi_arr[k]) else float("nan")
            if np.isfinite(zl_k) and np.isfinite(zu_k) and zl_k <= px <= zu_k:
                return True
        return False

    # Consolidation Blocker (CB) state (per symbol)
    inside_required_high = 3
    inside_required_low = 3
    max_high_since_entry: float = 0.0  # for ATR_Increment trailing stop
    box_ceiling: Optional[float] = None
    box_floor: Optional[float] = None
    inside_high_count = 0
    inside_low_count = 0
    cb_active = False
    last_pivot_high: Optional[float] = None
    last_pivot_low: Optional[float] = None

    # Sheet magic touch (AR/AW): hoist bounds helper + window once — was ~90% of bt_loop_bar_total (per-bar def + Python AR loops).
    # _smt_prev_bar carries f(i-1); each bar calls _smt_bounds_fn(i) at most once (magic block or finally on early continue).
    zone_cmp_round_bt = int(getattr(cfg, "zone_compare_round_decimals", -1))
    _smt_bounds_fn: Optional[Callable[[int], tuple[bool, float, float, int]]] = None
    _smt_win_magic = 0
    if bool(getattr(cfg, "sheet_magic_touch_enabled", False)):
        _smt_win_magic = int(getattr(cfg, "sheet_magic_touch_window_bars", 0))
        if _smt_win_magic <= 0:
            _smt_win_magic = int(getattr(cfg, "lookback_long", 504))

        def _smt_bounds_fn(idx: int) -> tuple[bool, float, float, int]:
            if idx < 0 or idx >= n:
                return (False, float("nan"), float("nan"), -1)
            zl_v = float(mat_bh_arr[idx])
            zh_v = float(mat_bi_arr[idx])
            ok_v = np.isfinite(zl_v) and np.isfinite(zh_v) and zl_v > 0.0 and zh_v > 0.0
            if not ok_v:
                return (False, float("nan"), float("nan"), -1)
            return (True, zl_v, zh_v, idx)

    # Carries _smt_bounds_fn(i-1) across bars for zone-change vs prior row (sheet AW).
    _smt_prev_bar: tuple[bool, float, float, int] = (False, float("nan"), float("nan"), -1)

'''

text = text[:start] + NEW + text[end:]

path.write_text(text, encoding="utf-8")
print("replaced run_brt_backtest init block", start, end)
