# One-shot migration: remove 8-rung ladder from rocket_MTS.py, align pre-loop with rocket_brt.py (BH/BI, full-history DI/DP/DW).
from __future__ import annotations

from pathlib import Path

PATH = Path("stock_analysis/rocket_MTS.py")
text = PATH.read_text(encoding="utf-8")
lines = text.splitlines()

HELPERS = '''

def _precompute_mat_bh_bi_stream(
    zl_full_arr: np.ndarray,
    zh_full_arr: np.ndarray,
    lag: int,
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Sheet BH/BI: INDEX(AG/AH, ROW()-lag) to zone lower/upper from bar (i - lag)."""
    mat_bh = np.full(n, np.nan, dtype=np.float64)
    mat_bi = np.full(n, np.nan, dtype=np.float64)
    lag = max(0, int(lag))
    for i in range(n):
        j = i - lag
        if j >= 0:
            mat_bh[i] = float(zl_full_arr[j])
            mat_bi[i] = float(zh_full_arr[j])
    return mat_bh, mat_bi


def _precompute_di_all_zones_breakout(
    high_arr: np.ndarray,
    mat_bh: np.ndarray,
    mat_bi: np.ndarray,
    n: int,
    max_hist: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Sheet DI (all zones): among historical matured bounds rows j before i, require prior high below BI[j]
    and current high at or above BI[j]; take the minimum qualifying BI.
    """
    di_ok = np.zeros(n, dtype=np.bool_)
    sel_j = np.full(n, -1, dtype=np.int32)
    mh = max(0, int(max_hist))
    high_64 = np.asarray(high_arr, dtype=np.float64)
    for i in range(1, n):
        hp = float(high_64[i - 1])
        hc = float(high_64[i])
        j0 = 0 if mh <= 0 else max(0, i - mh)
        best_zu = None
        best_j = -1
        for j in range(j0, i):
            zl = float(mat_bh[j])
            zu = float(mat_bi[j])
            if not (np.isfinite(zl) and np.isfinite(zu)):
                continue
            if hp < zu and hc >= zu:
                if best_zu is None or zu < best_zu:
                    best_zu = zu
                    best_j = j
        if best_j >= 0:
            di_ok[i] = True
            sel_j[i] = best_j
    return di_ok, sel_j


def _precompute_dw_dates_from_di_breakouts(
    low_arr: np.ndarray,
    high_arr: np.ndarray,
    mat_bh: np.ndarray,
    mat_bi: np.ndarray,
    di_ok: np.ndarray,
    selected_j: np.ndarray,
    index_iso: list[str],
    n: int,
) -> Set[str]:
    """Simulated DW retest dates after DI breakouts (BH/BI overlap)."""
    dates_in_dw: Set[str] = set()
    pending: list[tuple[int, int]] = []
    low_64 = np.asarray(low_arr, dtype=np.float64)
    high_64 = np.asarray(high_arr, dtype=np.float64)
    for i in range(1, n):
        new_pending: list[tuple[int, int]] = []
        for b, j_star in pending:
            if i <= b:
                new_pending.append((b, j_star))
                continue
            zl = float(mat_bh[j_star])
            zu = float(mat_bi[j_star])
            if not (np.isfinite(zl) and np.isfinite(zu)):
                new_pending.append((b, j_star))
                continue
            lo = float(low_64[i])
            hi = float(high_64[i])
            if (lo <= zu) and (hi >= zl):
                if i < len(index_iso):
                    dates_in_dw.add(index_iso[i])
            else:
                new_pending.append((b, j_star))
        pending = new_pending
        sj = int(selected_j[i])
        if bool(di_ok[i]) and sj >= 0:
            if (not bool(di_ok[i - 1])) or int(selected_j[i - 1]) != sj:
                pending.append((i, sj))
    return dates_in_dw

'''

BH_BI_PRELOOP = r'''
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

# --- 1) Remove ladder builders + reports; insert BH/DI/DW helpers before _fmt_par ---
out_lines = lines[:1160] + lines[1400:1416] + HELPERS.splitlines() + lines[1626:]

s = "\n".join(out_lines)

# --- 2) Remove _brt_active_zone_dn_bar ---
start = s.find("\ndef _brt_active_zone_dn_bar(")
if start != -1:
    end = s.find("\ndef _brt_make_entry_gate_query_fns(", start)
    if end != -1:
        s = s[:start] + "\n" + s[end + 1 :]

# --- 3) Remove _sheet_ladder_aq_ak_and_gate_fns ---
start = s.find("\ndef _sheet_ladder_aq_ak_and_gate_fns(")
if start != -1:
    end = s.find("\ndef run_brt_backtest(", start)
    if end != -1:
        s = s[:start] + "\n" + s[end + 1 :]

# --- 4) run_brt_backtest: strip sheet_ladder_trace parameter ---
s = s.replace(
    "    sheet_ladder_trace: Optional[dict[str, Any]] = None,\n",
    "",
)

start = s.find("    c14_lag = int(getattr(cfg, \"sheet_maturity_lag_bars\", 7))")
end = s.find("    for i in range(n - 1):", s.find("_acc_bt(\"bt_init\", time.perf_counter() - _t_init)"))
if start == -1 or end == -1:
    raise SystemExit("could not locate pre-loop ladder block for replacement")
s = s[:start] + BH_BI_PRELOOP.lstrip("\n\r") + "\n\n" + s[end:]

# --- 5) main: ladder CLI / sink / mismatch / parity ---
s = s.replace(
    """    if _NUMBA_LADDER_AVAILABLE and _use_numba_sheet_ladder():
        print("[MTS] Numba ladder JIT: on (compiled code cached on disk; not invalidated by BRT --set params)")
    elif _NUMBA_LADDER_AVAILABLE:
        print("[MTS] Numba ladder JIT: off (MTS_DISABLE_NUMBA_LADDER is set)")

""",
    "",
)

s = s.replace(
    """    ap.add_argument("--emit-sheet-parity", action="store_true",
                    help="With -s SYMBOL: write MTS_SheetParity_<sym>_<ts>.csv (DE/DF/DG per bar + blank columns to paste sheet values)")
    ap.add_argument("--sheet-ladder-active-zone", action="store_true",
                    help="Use Excel zone-ladder DE/DF/DG for row_local active zone (pair with -v entry_eval_mode=row_local)")
    ap.add_argument("--sheet-maturity-lag", type=int, default=None,
                    help="Sheet C14: lag in bars for CE/CF inputs to the ladder (default: config sheet_maturity_lag_bars)")
    ap.add_argument("--sheet-zone-ladder-rungs", type=int, default=None,
                    help="Sheet ladder depth: >0 fixed rungs, 0 => use lookback_long (extended memory)")
    ap.add_argument("--ladder-mismatch-report", action="store_true",
                    help="With -s SYMBOL: count trades whose maturity zone is not on any of 8 sheet rungs at signal bar; write MTS_LadderMismatch_<sym>_<ts>.csv")
""",
    """    ap.add_argument("--sheet-maturity-lag", type=int, default=None,
                    help="Sheet lag in bars for BH/BI/CE/CF INDEX (C10/C14 style); default: config sheet_maturity_lag_bars")
""",
)

s = s.replace(
    """    if getattr(args, "sheet_ladder_active_zone", False):
        cfg_kw["use_sheet_ladder_active_zone"] = True
    if getattr(args, "sheet_maturity_lag", None) is not None:
        cfg_kw["sheet_maturity_lag_bars"] = int(args.sheet_maturity_lag)
    if getattr(args, "sheet_zone_ladder_rungs", None) is not None:
        cfg_kw["sheet_zone_ladder_rungs"] = int(args.sheet_zone_ladder_rungs)
""",
    """    if getattr(args, "sheet_maturity_lag", None) is not None:
        cfg_kw["sheet_maturity_lag_bars"] = int(args.sheet_maturity_lag)
""",
)

s = s.replace(
    """    if cfg.use_sheet_ladder_active_zone and str(cfg.entry_eval_mode).strip().lower() != "row_local":
        print(
            "[MTS] Note: use_sheet_ladder_active_zone is designed for entry_eval_mode=row_local "
            f"(current: {cfg.entry_eval_mode}).",
            file=sys.stderr,
        )

""",
    "",
)

s = s.replace(
    """    sheet_ladder_sink: Optional[dict[str, Any]] = None
    if getattr(args, "emit_sheet_parity", False) or cfg.use_sheet_ladder_active_zone:
        sheet_ladder_sink = {}

""",
    "",
)

s = s.replace(
    """                        profile_backtest_sections=bt_sections if args.profile else None,
                        sheet_ladder_trace=sheet_ladder_sink,
                        cprofile_magic_touch=""",
    """                        profile_backtest_sections=bt_sections if args.profile else None,
                        cprofile_magic_touch=""",
)

s = s.replace(
    """                        profile_backtest_sections=bt_sections if args.profile else None,
                        sheet_ladder_trace=sheet_ladder_sink,
                        cprofile_magic_touch=""",
    """                        profile_backtest_sections=bt_sections if args.profile else None,
                        cprofile_magic_touch=""",
)

# Remove ladder mismatch block (best-effort: from if getattr ladder_mismatch through print report)
import re

s = re.sub(
    r"\n            if getattr\(args, \"ladder_mismatch_report\", False\).*?f\"at signal bar \(close_above_date\)\. Report: \{lp\}\"\s*\n\s*\)\s*\n",
    "\n",
    s,
    count=1,
    flags=re.DOTALL,
)

s = re.sub(
    r"\n            if \(\s*\n\s*getattr\(args, \"emit_sheet_parity\", False\)\s*\n\s*and args\.symbol\s*\n\s*and sym == args\.symbol\.upper\(\)\s*\n\s*and sheet_ladder_sink\s*\n\s*\):\s*\n\s*sp_path = output_dir / f\"MTS_SheetParity_\{sym\}_\{ts\}\.csv\"\s*\n\s*write_sheet_parity_csv\(sp_path, sym, df, sheet_ladder_sink\.get\(\"index_iso\", \[\]\), sheet_ladder_sink\)\s*\n\s*print\(f\"\[MTS\] Sheet parity trace: \{sp_path\}\"\)\s*\n\s*\n",
    "\n",
    s,
    count=1,
)

PATH.write_text(s, encoding="utf-8")
print("finalize_mts_bh_bi: wrote", PATH)

# Note: do not use .strip() on BH_BI_PRELOOP — it removes leading indent from the first line (lag_c14 = ...).
