from pathlib import Path

p = Path("stock_analysis/rocket_MTS.py")
text = p.read_text(encoding="utf-8")
start = text.index("def _compute_sheet_ladder_de_df_dg_all_modes(")
end = text.index("\ndef _fmt_par(x: Any)", start)

insert = r'''
def _trade_ymd_to_bar_index(index_iso: list[str], date_s: str) -> Optional[int]:
    """Match BRTTrade date strings (YYYY-MM-DD or YYYYMMDD) to index_iso bar position."""
    if not date_s or not str(date_s).strip():
        return None
    s = str(date_s).strip()
    if len(s) >= 10 and s[4] == "-":
        ymd = s[:10].replace("-", "")
    else:
        ymd = "".join(ch for ch in s if ch.isdigit())[:8]
    if len(ymd) != 8:
        return None
    for i, iso in enumerate(index_iso):
        if len(iso) >= 8 and iso[:8] == ymd:
            return i
    return None


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
    Sheet DI (all zones): among historical matured bounds rows j less than i, require prior high below BI[j]
    and current high at or above BI[j]; take the minimum qualifying BI (sheet FILTER plus MIN).
    """
    di_ok = np.zeros(n, dtype=np.bool_)
    sel_j = np.full(n, -1, dtype=np.int32)
    mh = max(0, int(max_hist))
    high_64 = np.asarray(high_arr, dtype=np.float64)
    for i in range(1, n):
        hp = float(high_64[i - 1])
        hc = float(high_64[i])
        j0 = 0
        if mh > 0:
            j0 = max(0, i - mh)
        best_zu: Optional[float] = None
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
    """
    Minimal DW simulation: after a DI breakout at bar b on zone row j_star, first later bar whose
    range overlaps [BH[j_star], BI[j_star]] records a retest date (that bar date in column DW).
    """
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

new_text = text[:start] + insert + text[end:]
p.write_text(new_text, encoding="utf-8")
print("patched", start, end)
