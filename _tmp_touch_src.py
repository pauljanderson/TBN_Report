def compute_wpbr_touch_stream(
    df: pd.DataFrame,
    *,
    band_pct: float = 0.015,
    strong_pre_pivot_bars: int = 3,
    strong_pre_pivot_pct: float = 0.10,
    strong_post_pivot_bars: int = 3,
    strong_post_pivot_pct: float = 0.10,
    strong_pivot_mode: str = "either",
    breakout_confirmation: float = 0.03,
    max_days_after_retest: int = 2,
    retest_mode: str = RETEST_MODE_STOP_LOOKING,
    zone_price_round_decimals: int = 2,
    debug_symbol: Optional[str] = None,
) -> dict[str, Any]:
    """
    Weekly pivot-high zones; two-stage weekly breakout (close > upper, then high > upper*(1+conf));
    daily retest/entry begins the Monday after the confirmation week.

    Emits the first retest/signal opportunity per zone. The backtest enforces zone lifecycle
    when ``wpbr_second_chance_after_win`` is enabled:
      - 1st purchase closes with pnl_pct > 0 → allow one more purchase (resume scan after exit)
      - 1st purchase closes flat/loss → retire zone
      - 2nd purchase → retire zone immediately (no further entries)
    When that flag is False (default), the zone is retired after the first purchase.

    Each zone event includes strength metrics (``WPBR_STRENGTH_FIELDS``): pivot quality,
    POC/prior-extreme confluence, breakout/confirmation power, retest quality, and
    ``wpbr_zone_strength`` composite (0–1, audit/research).

    Spreadsheet mapping:
      Breakout Date  -> Monday of first weekly close > zone_upper
      Conf Date      -> Monday of first weekly high > zone_upper*(1+confirmation)
      Next week start -> Monday after confirmation week
      Rocket Buy Date -> signal day (green close); fill = next session open
    """
    n = len(df)
    daily_index = pd.DatetimeIndex(df.index)
    hi = np.asarray(df["High"].values, dtype=np.float64)
    lo = np.asarray(df["Low"].values, dtype=np.float64)
    op = np.asarray(df["Open"].values, dtype=np.float64)
    cl = np.asarray(df["Close"].values, dtype=np.float64)
    vol = (
        np.asarray(df["Volume"].values, dtype=np.float64)
        if "Volume" in df.columns
        else np.zeros(n, dtype=np.float64)
    )

    weekly = aggregate_weekly(df)
    if weekly.empty:
        empty = np.full(n, np.nan)
        return {
            "touch_price": pd.Series(empty, index=df.index),
            "zone_center": pd.Series(empty, index=df.index),
            "zone_low": pd.Series(empty, index=df.index),
            "zone_high": pd.Series(empty, index=df.index),
            "touch_count_long": pd.Series(0, index=df.index),
            "touch_count_short": pd.Series(0, index=df.index),
            "tradeable_key_level": pd.Series(False, index=df.index),
            "matured_now": pd.Series(False, index=df.index),
            "short_candidate": pd.Series(False, index=df.index),
            "zone_touch_origin": pd.Series(0, index=df.index),
            "yh_zone_events": [],
            "wpbr_zone_events": [],
            "wpbr_entry_opportunities": [],
            "wpbr_entry_signal_bars": [],
            "wpbr_entry_fill_bars": [],
            "wpbr_audit": [],
        }

    wh = weekly["High"].to_numpy(dtype=np.float64)
    wl = weekly["Low"].to_numpy(dtype=np.float64)
    wc = weekly["Close"].to_numpy(dtype=np.float64)
    wv = (
        weekly["Volume"].to_numpy(dtype=np.float64)
        if "Volume" in weekly.columns
        else np.zeros(len(weekly), dtype=np.float64)
    )
    w_index = pd.DatetimeIndex(weekly.index)

    pivots = _weekly_pivot_indices(
        wh,
        wl,
        pre_bars=int(strong_pre_pivot_bars),
        post_bars=int(strong_post_pivot_bars),
        pre_pct=float(strong_pre_pivot_pct),
        post_pct=float(strong_post_pivot_pct),
        pivot_mode=strong_pivot_mode,
    )

    dec = max(0, int(zone_price_round_decimals))
    bo_conf = max(0.0, float(breakout_confirmation))
    max_entry_days = max(0, int(max_days_after_retest))
    retest_mode_norm = normalize_retest_mode(retest_mode)

    tp_arr = np.full(n, np.nan)
    zc_arr = np.full(n, np.nan)
    zl_arr = np.full(n, np.nan)
    zh_arr = np.full(n, np.nan)
    origin_arr = np.zeros(n, dtype=np.int8)
    matured_arr = np.zeros(n, dtype=bool)

    zone_events: list[dict] = []
    yh_events: list[dict] = []
    audit: list[dict] = []
    entry_signal_bars: list[int] = []
    entry_fill_bars: list[int] = []
    entry_opportunities: list[dict] = []

    dates_norm = daily_index.normalize()

    for wi in pivots:
        pivot_high = float(wh[wi])
        touch, zl, zh = _round_bounds(pivot_high, band_pct, dec)
        pivot_week_end = w_index[wi].strftime("%Y-%m-%d")
        zone_id = make_wpbr_zone_id(pivot_week_end, zl, zh)
        pivot_monday = _week_monday(w_index[wi])
        pivot_daily_start = int(
            np.searchsorted(dates_norm.to_numpy(), pivot_monday.to_numpy(), side="left")
        )
        if pivot_daily_start >= n:
            continue

        bo_week, conf_week = _find_weekly_breakout_and_confirm(
            wc, wh, start_week=wi, zone_upper=zh, confirm_pct=bo_conf,
        )

        bo_monday: pd.Timestamp | None = None
        conf_monday: pd.Timestamp | None = None
        next_week_start: pd.Timestamp | None = None
        bo_daily_end: int | None = None
        conf_daily_end: int | None = None
        scan_start_bar: int | None = None

        if bo_week is not None:
            bo_monday = _week_monday(w_index[bo_week])
            bo_daily_end = int(
                np.searchsorted(dates_norm.to_numpy(), _to_date(w_index[bo_week]).to_numpy(), side="right")
            ) - 1
            bo_daily_end = max(0, min(n - 1, bo_daily_end))
        if conf_week is not None:
            conf_monday = _week_monday(w_index[conf_week])
            next_week_start = _next_week_start_after_conf(w_index[conf_week])
            conf_daily_end = int(
                np.searchsorted(dates_norm.to_numpy(), _to_date(w_index[conf_week]).to_numpy(), side="right")
            ) - 1
            conf_daily_end = max(0, min(n - 1, conf_daily_end))

        # Zone cloud from pivot week forward (active even before confirmation)
        for di in range(pivot_daily_start, n):
            tp_arr[di] = touch
            zc_arr[di] = touch
            zl_arr[di] = zl
            zh_arr[di] = zh
            origin_arr[di] = 5
        if pivot_daily_start < n:
            matured_arr[pivot_daily_start] = True

        retest_bar: int | None = None
        entry_signal_bar: int | None = None
        entry_fill_bar: int | None = None

        if conf_week is not None and next_week_start is not None:
            scan_start_bar = _first_daily_bar_on_or_after(next_week_start, daily_index)
            if scan_start_bar is not None:
                retest_bar, entry_signal_bar, entry_fill_bar = find_wpbr_retest_and_signal(
                    lo,
                    cl,
                    op,
                    scan_start=scan_start_bar,
                    zone_lower=zl,
                    zone_upper=zh,
                    max_days_after_retest=max_entry_days,
                    n=n,
                    retest_mode=retest_mode_norm,
                )
                if entry_signal_bar is not None and entry_fill_bar is not None:
                    entry_signal_bars.append(entry_signal_bar)
                    entry_fill_bars.append(entry_fill_bar)
                    entry_opportunities.append(
                        {
                            "wpbr_zone_id": zone_id,
                            "zone_lower": zl,
                            "zone_upper": zh,
                            "zone_center": touch,
                            "retest_bar": retest_bar,
                            "entry_signal_bar": entry_signal_bar,
                            "entry_fill_bar": entry_fill_bar,
                            "opportunity_index": 0,
                            "scan_start_bar": scan_start_bar,
                        }
                    )

        pivot_daily_end = int(
            np.searchsorted(dates_norm.to_numpy(), _to_date(w_index[wi]).to_numpy(), side="right")
        ) - 1
        pivot_daily_end = max(0, min(n - 1, pivot_daily_end))

        strength: dict[str, float] = {}
        strength.update(
            _pivot_strength_detail(
                wh,
                wl,
                wi,
                pre_bars=int(strong_pre_pivot_bars),
                post_bars=int(strong_post_pivot_bars),
            )
        )
        strength.update(_wpbr_poc_confluence(hi, lo, cl, vol, pivot_daily_end, touch))
        strength.update(_wpbr_prior_extreme_confluence(wh, wi, touch, prior_weeks=_WPBR_PRIOR_WEEKS))
        strength.update(
            _wpbr_breakout_strength(
                wc,
                wh,
                wv,
                pivot_week=wi,
                bo_week=bo_week,
                conf_week=conf_week,
                zone_upper=zh,
                confirm_pct=bo_conf,
            )
        )
        strength.update(
            _wpbr_retest_strength(
                lo,
                cl,
                op,
                retest_bar=retest_bar,
                signal_bar=entry_signal_bar,
                conf_bar=conf_daily_end,
                zone_lower=zl,
                zone_upper=zh,
                daily_index=daily_index,
            )
        )
        strength["wpbr_zone_strength"] = _compute_wpbr_zone_strength(strength)

        ev = {
            "wpbr_zone_id": zone_id,
            "pivot_week_end": pivot_week_end,
            "pivot_monday": pivot_monday.strftime("%Y-%m-%d"),
            "pivot_high": touch,
            "zone_lower": zl,
            "zone_upper": zh,
            "breakout_week_end": w_index[bo_week].strftime("%Y-%m-%d") if bo_week is not None else "",
            "breakout_monday": bo_monday.strftime("%Y-%m-%d") if bo_monday is not None else "",
            "breakout_bar": bo_daily_end if bo_daily_end is not None else -1,
            "conf_week_end": w_index[conf_week].strftime("%Y-%m-%d") if conf_week is not None else "",
            "conf_monday": conf_monday.strftime("%Y-%m-%d") if conf_monday is not None else "",
            "conf_bar": conf_daily_end if conf_daily_end is not None else -1,
            "next_week_start": next_week_start.strftime("%Y-%m-%d") if next_week_start is not None else "",
            "scan_start_bar": scan_start_bar if scan_start_bar is not None else -1,
            "retest_bar": retest_bar if retest_bar is not None else -1,
            "entry_signal_bar": entry_signal_bar if entry_signal_bar is not None else -1,
            "entry_fill_bar": entry_fill_bar if entry_fill_bar is not None else -1,
            "yh_bar": pivot_daily_start,
            "activation_bar": pivot_daily_start,
            "touch_price": touch,
            "zone_center": touch,
            "zone_lower_f": zl,
            "zone_upper_f": zh,
            "activation_price": touch,
            "origin": 5,
            "max_days_after_retest": max_entry_days,
            **strength,
        }
        if entry_opportunities and entry_opportunities[-1].get("wpbr_zone_id") == zone_id:
            entry_opportunities[-1].update(strength)
        zone_events.append(ev)
        yh_events.append(
            {
                "yh_bar": pivot_daily_start,
                "activation_bar": pivot_daily_start,
                "touch_price": touch,
                "zone_center": touch,
                "zone_lower": zl,
                "zone_upper": zh,
                "activation_price": touch,
                "origin": 5,
                "breakout_bar": bo_daily_end if bo_daily_end is not None else -1,
                "conf_bar": conf_daily_end if conf_daily_end is not None else -1,
                "retest_bar": retest_bar if retest_bar is not None else -1,
                "wpbr_zone_id": zone_id,
            }
        )
        audit.append(ev)

        if debug_symbol:
            print(
                f"[WPBR] {debug_symbol} id={zone_id} pivot={pivot_monday.date()} z=({zl},{zh}) "
                f"bo={bo_monday.date() if bo_monday else None} "
                f"conf={conf_monday.date() if conf_monday else None} "
                f"next={next_week_start.date() if next_week_start else None} "
                f"retest={retest_bar} signal={entry_signal_bar} fill={entry_fill_bar}"
            )

    tkl = matured_arr.copy()
    return {
        "touch_price": pd.Series(tp_arr, index=df.index),
        "zone_center": pd.Series(zc_arr, index=df.index),
        "zone_low": pd.Series(zl_arr, index=df.index),
        "zone_high": pd.Series(zh_arr, index=df.index),
        "touch_count_long": pd.Series(np.where(np.isfinite(zc_arr), 1, 0), index=df.index),
        "touch_count_short": pd.Series(0, index=df.index),
        "tradeable_key_level": pd.Series(tkl, index=df.index),
        "matured_now": pd.Series(matured_arr, index=df.index),
        "short_candidate": pd.Series(False, index=df.index),
        "zone_touch_origin": pd.Series(origin_arr, index=df.index),
        "yh_zone_events": yh_events,
        "wpbr_zone_events": zone_events,
        "wpbr_entry_opportunities": entry_opportunities,
        "wpbr_entry_signal_bars": sorted(set(entry_signal_bars)),
        "wpbr_entry_fill_bars": sorted(set(entry_fill_bars)),
        "wpbr_entry_bars": sorted(set(entry_signal_bars)),
        "wpbr_audit": audit,
    }
