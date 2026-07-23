#!/usr/bin/env python3
"""Forward-return association of IND indicator states vs subsequent price rises.

Uses warm ``.indcache.pkl`` + OHLCV CSVs. Matches IND fill convention:
  - Signal / state evaluated at trigger bar ``t`` close (cache state)
  - Synthetic entry at ``Open[t+1]``
  - Forward return: ``Close[t+h] / Open[t+1] - 1`` for horizons h

Also reports per-symbol (symbol × signal) and (symbol × BULL+BULL pair) lifts
vs each symbol's own baseline, with early/late half consistency flags.

Does **not** apply IND_DIFF / min_ind_score / ATR gates — raw association
(in-sample, multiple-testing caveats apply).
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_SA = _REPO / "stock_analysis"
for p in (_REPO, _SA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from brt_entry_indicators import (  # noqa: E402
    INDICATOR_IDS,
    _Precomputed,
    _load_disk_cache_payload,
)
from rocket_brt import load_csv  # noqa: E402


class _Acc:
    __slots__ = ("n", "sum_ret", "wins")

    def __init__(self) -> None:
        self.n = 0
        self.sum_ret = 0.0
        self.wins = 0

    def add_many(self, rets: np.ndarray) -> None:
        if rets.size == 0:
            return
        self.n += int(rets.size)
        self.sum_ret += float(np.sum(rets))
        self.wins += int(np.sum(rets > 0.0))

    def avg(self) -> float | None:
        return (self.sum_ret / self.n) if self.n else None

    def hit(self) -> float | None:
        return (self.wins / self.n) if self.n else None


def _acc_row(
    *,
    avg: float | None,
    hit: float | None,
    n: int,
    base_avg_pct: float,
    base_hit_pct: float,
) -> dict:
    avg_pct = None if avg is None else 100.0 * avg
    hit_pct = None if hit is None else 100.0 * hit
    return {
        "n": n,
        "avg_ret_pct": None if avg_pct is None else round(avg_pct, 4),
        "lift_vs_base_pp": None if avg_pct is None else round(avg_pct - base_avg_pct, 4),
        "hit_rate_pct": None if hit_pct is None else round(hit_pct, 2),
        "hit_lift_pp": None if hit_pct is None else round(hit_pct - base_hit_pct, 2),
    }


def _align_ohlcv(df: pd.DataFrame, dates: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (open, close) aligned to cache dates (YYYYMMDD), or None if poorly aligned."""
    if df is None or df.empty or "Open" not in df.columns or "Close" not in df.columns:
        return None
    idx_dates = np.array([int(pd.Timestamp(x).strftime("%Y%m%d")) for x in df.index], dtype=np.int64)
    s_open = pd.Series(df["Open"].to_numpy(dtype=np.float64), index=idx_dates)
    s_close = pd.Series(df["Close"].to_numpy(dtype=np.float64), index=idx_dates)
    s_open = s_open[~s_open.index.duplicated(keep="last")]
    s_close = s_close[~s_close.index.duplicated(keep="last")]
    op = s_open.reindex(dates).to_numpy(dtype=np.float64)
    cl = s_close.reindex(dates).to_numpy(dtype=np.float64)
    miss = int(np.isnan(op).sum())
    if miss > max(5, len(dates) // 20):
        return None
    return op, cl


def _fwd_returns_vec(op: np.ndarray, cl: np.ndarray, horizon: int) -> np.ndarray:
    n = len(op)
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= horizon:
        return out
    valid_n = n - horizon
    e = op[1 : valid_n + 1]
    x = cl[horizon : valid_n + horizon]
    ok = np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0)
    tmp = np.full(valid_n, np.nan, dtype=np.float64)
    tmp[ok] = x[ok] / e[ok] - 1.0
    out[:valid_n] = tmp
    return out


def _half_masks(n_valid: int) -> tuple[np.ndarray, np.ndarray]:
    mid = n_valid // 2
    early = np.zeros(n_valid, dtype=bool)
    late = np.zeros(n_valid, dtype=bool)
    early[:mid] = True
    late[mid:] = True
    return early, late


def analyze(
    data_dir: Path,
    cache_dir: Path,
    *,
    horizons: list[int],
    max_symbols: int | None,
    min_n: int,
    min_n_sym: int,
    min_n_half: int,
    warmup: int,
    max_pair_for_sym: int,
) -> dict[str, pd.DataFrame]:
    caches = sorted(cache_dir.glob("*.indcache.pkl"))
    if max_symbols and max_symbols > 0:
        caches = caches[:max_symbols]

    ids = list(INDICATOR_IDS)
    id_index = {iid: i for i, iid in enumerate(ids)}
    n_ind = len(ids)
    pairs = list(combinations(ids, 2))

    baseline: dict[int, _Acc] = {h: _Acc() for h in horizons}
    single: dict[tuple[str, str, int], _Acc] = {
        (iid, st, h): _Acc() for iid in ids for st in ("BULL", "BEAR", "NEUTRAL") for h in horizons
    }
    fresh: dict[tuple[str, int], _Acc] = {(iid, h): _Acc() for iid in ids for h in horizons}
    pair_acc: dict[tuple[str, str, int], _Acc] = {
        (a, b, h): _Acc() for a, b in pairs for h in horizons
    }

    diff_edges_inner = [-10, 0, 5, 7, 10, 15, 20]
    diff_labels = [
        "diff<=-10",
        "-10<diff<=0",
        "0<diff<=5",
        "5<diff<=7",
        "7<diff<=10",
        "10<diff<=15",
        "15<diff<=20",
        "diff>20",
    ]
    diff_acc: dict[tuple[str, int], _Acc] = {
        (lab, h): _Acc() for lab in diff_labels for h in horizons
    }

    sym_base: dict[tuple[str, int], _Acc] = {}
    sym_base_e: dict[tuple[str, int], _Acc] = {}
    sym_base_l: dict[tuple[str, int], _Acc] = {}
    sym_bull: dict[tuple[str, str, int], _Acc] = {}
    sym_bull_e: dict[tuple[str, str, int], _Acc] = {}
    sym_bull_l: dict[tuple[str, str, int], _Acc] = {}
    sym_pair: dict[tuple[str, str, str, int], _Acc] = {}
    sym_pair_e: dict[tuple[str, str, str, int], _Acc] = {}
    sym_pair_l: dict[tuple[str, str, str, int], _Acc] = {}

    sym_payloads: list[tuple[str, np.ndarray, dict[int, np.ndarray], np.ndarray]] = []

    sym_ok = 0
    sym_skip = 0
    bars_used = 0
    t0 = time.time()

    for ci, cpath in enumerate(caches):
        sym = cpath.stem.replace(".indcache", "").upper()
        if sym in ("SPY", "XSPY"):
            continue
        payload = _load_disk_cache_payload(cache_dir, sym)
        if payload is None:
            try:
                with open(cpath, "rb") as f:
                    payload = pickle.load(f)
            except Exception:
                sym_skip += 1
                continue
        pre = payload.get("pre") if isinstance(payload, dict) else None
        if not isinstance(pre, _Precomputed):
            sym_skip += 1
            continue
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            sym_skip += 1
            continue
        try:
            df = load_csv(str(csv_path))
        except Exception:
            sym_skip += 1
            continue
        aligned = _align_ohlcv(df, pre.dates)
        if aligned is None:
            sym_skip += 1
            continue
        op, cl = aligned
        n = len(pre.dates)
        if n < warmup + max(horizons) + 5:
            sym_skip += 1
            continue

        st_mat = np.zeros((n_ind, n), dtype=np.int8)
        for iid, ii in id_index.items():
            arr = pre.states.get(iid)
            if arr is not None and len(arr) == n:
                st_mat[ii] = arr

        diff = pre.diff_long
        if diff is None or len(diff) != n:
            bull = (st_mat > 0).sum(axis=0).astype(np.int16)
            bear = (st_mat < 0).sum(axis=0).astype(np.int16)
            diff = (bull - bear).astype(np.int16)

        fwd = {h: _fwd_returns_vec(op, cl, h) for h in horizons}
        valid = np.ones(n, dtype=bool)
        valid[:warmup] = False
        for h in horizons:
            valid &= np.isfinite(fwd[h])
        if not valid.any():
            sym_skip += 1
            continue

        sym_ok += 1
        n_valid = int(valid.sum())
        bars_used += n_valid
        early_m, late_m = _half_masks(n_valid)
        idx = np.flatnonzero(valid)
        st_v = st_mat[:, valid]

        sym_payloads.append((sym, st_v, {h: fwd[h][valid].copy() for h in horizons}, early_m.copy()))

        for h in horizons:
            rets = fwd[h][valid]
            baseline[h].add_many(rets)

            sb = sym_base.setdefault((sym, h), _Acc())
            sbe = sym_base_e.setdefault((sym, h), _Acc())
            sbl = sym_base_l.setdefault((sym, h), _Acc())
            sb.add_many(rets)
            sbe.add_many(rets[early_m])
            sbl.add_many(rets[late_m])

            d = diff[valid].astype(np.float64)
            bins = np.digitize(d, diff_edges_inner, right=True)
            for bi, lab in enumerate(diff_labels):
                m = bins == bi
                if m.any():
                    diff_acc[(lab, h)].add_many(rets[m])

            for ii, iid in enumerate(ids):
                s = st_v[ii]
                for code, name in ((1, "BULL"), (-1, "BEAR"), (0, "NEUTRAL")):
                    m = s == code
                    if m.any():
                        single[(iid, name, h)].add_many(rets[m])

                raw = st_mat[ii]
                if idx.size and idx[0] > 0:
                    fresh_m = (raw[idx] == 1) & (raw[idx - 1] != 1)
                    if fresh_m.any():
                        fresh[(iid, h)].add_many(rets[fresh_m])

                m_bull = s == 1
                if m_bull.any():
                    key = (sym, iid, h)
                    sym_bull.setdefault(key, _Acc()).add_many(rets[m_bull])
                    sym_bull_e.setdefault(key, _Acc()).add_many(rets[m_bull & early_m])
                    sym_bull_l.setdefault(key, _Acc()).add_many(rets[m_bull & late_m])

        # Global pairs once per symbol (same BULL mask for all horizons)
        bull = st_v == 1
        rets_by_h = {h: fwd[h][valid] for h in horizons}
        for a, b in pairs:
            ia, ib = id_index[a], id_index[b]
            m = bull[ia] & bull[ib]
            if not m.any():
                continue
            for h in horizons:
                pair_acc[(a, b, h)].add_many(rets_by_h[h][m])

        if (ci + 1) % 50 == 0:
            print(
                f"[ind-fwd] pass1 {ci+1}/{len(caches)} ok={sym_ok} skip={sym_skip} "
                f"bars={bars_used:,} {time.time()-t0:.0f}s",
                flush=True,
            )

    base_rows = []
    for h in horizons:
        a = baseline[h]
        base_rows.append(
            {
                "horizon": h,
                "n": a.n,
                "avg_ret_pct": None if a.avg() is None else round(100.0 * a.avg(), 4),
                "hit_rate_pct": None if a.hit() is None else round(100.0 * a.hit(), 2),
            }
        )
    base_df = pd.DataFrame(base_rows)
    base_map = {int(r["horizon"]): float(r["avg_ret_pct"] or 0) for _, r in base_df.iterrows()}
    hit_map = {int(r["horizon"]): float(r["hit_rate_pct"] or 0) for _, r in base_df.iterrows()}

    single_rows = []
    for (iid, st, h), a in single.items():
        if a.n < min_n:
            continue
        single_rows.append(
            {
                "indicator": iid,
                "state": st,
                "horizon": h,
                **_acc_row(
                    avg=a.avg(),
                    hit=a.hit(),
                    n=a.n,
                    base_avg_pct=base_map[h],
                    base_hit_pct=hit_map[h],
                ),
            }
        )
    single_df = pd.DataFrame(single_rows)

    fresh_rows = []
    for (iid, h), a in fresh.items():
        if a.n < min_n:
            continue
        fresh_rows.append(
            {
                "indicator": iid,
                "state": "FRESH_BULL",
                "horizon": h,
                **_acc_row(
                    avg=a.avg(),
                    hit=a.hit(),
                    n=a.n,
                    base_avg_pct=base_map[h],
                    base_hit_pct=hit_map[h],
                ),
            }
        )
    fresh_df = pd.DataFrame(fresh_rows)

    pair_rows = []
    for (a, b, h), acc in pair_acc.items():
        if acc.n < min_n:
            continue
        pair_rows.append(
            {
                "signal_a": a,
                "signal_b": b,
                "combo": f"{a}=BULL & {b}=BULL",
                "horizon": h,
                **_acc_row(
                    avg=acc.avg(),
                    hit=acc.hit(),
                    n=acc.n,
                    base_avg_pct=base_map[h],
                    base_hit_pct=hit_map[h],
                ),
            }
        )
    pair_df = pd.DataFrame(pair_rows)

    diff_rows = []
    for (lab, h), a in diff_acc.items():
        if a.n < min_n:
            continue
        diff_rows.append(
            {
                "bucket": lab,
                "horizon": h,
                **_acc_row(
                    avg=a.avg(),
                    hit=a.hit(),
                    n=a.n,
                    base_avg_pct=base_map[h],
                    base_hit_pct=hit_map[h],
                ),
            }
        )
    diff_df = pd.DataFrame(diff_rows)

    pair_rank_h = 5 if 5 in horizons else horizons[0]
    if not pair_df.empty:
        top_pairs_df = (
            pair_df[pair_df["horizon"] == pair_rank_h]
            .sort_values("lift_vs_base_pp", ascending=False)
            .head(max_pair_for_sym)
        )
        top_pair_keys = [(str(r.signal_a), str(r.signal_b)) for r in top_pairs_df.itertuples()]
    else:
        top_pair_keys = pairs[:max_pair_for_sym]

    print(
        f"[ind-fwd] pass2 per-symbol pairs for {len(top_pair_keys)} global top combos…",
        flush=True,
    )
    for sym, st_v, fwd_map, early_m in sym_payloads:
        late_m = ~early_m
        for a, b in top_pair_keys:
            ia, ib = id_index[a], id_index[b]
            m = (st_v[ia] == 1) & (st_v[ib] == 1)
            if not m.any():
                continue
            for h in horizons:
                rets = fwd_map[h]
                key = (sym, a, b, h)
                sym_pair.setdefault(key, _Acc()).add_many(rets[m])
                sym_pair_e.setdefault(key, _Acc()).add_many(rets[m & early_m])
                sym_pair_l.setdefault(key, _Acc()).add_many(rets[m & late_m])

    sym_rows = []
    for (sym, iid, h), a in sym_bull.items():
        if a.n < min_n_sym:
            continue
        sb = sym_base.get((sym, h))
        if sb is None or sb.n == 0:
            continue
        base_avg = 100.0 * (sb.avg() or 0.0)
        base_hit = 100.0 * (sb.hit() or 0.0)
        ae = sym_bull_e.get((sym, iid, h), _Acc())
        al = sym_bull_l.get((sym, iid, h), _Acc())
        sbe = sym_base_e.get((sym, h), _Acc())
        sbl = sym_base_l.get((sym, h), _Acc())
        lift_e = None
        lift_l = None
        if ae.n >= min_n_half and sbe.n >= min_n_half and ae.avg() is not None and sbe.avg() is not None:
            lift_e = 100.0 * ae.avg() - 100.0 * sbe.avg()
        if al.n >= min_n_half and sbl.n >= min_n_half and al.avg() is not None and sbl.avg() is not None:
            lift_l = 100.0 * al.avg() - 100.0 * sbl.avg()
        consistent_pos = bool(lift_e is not None and lift_l is not None and lift_e > 0 and lift_l > 0)
        consistent_neg = bool(lift_e is not None and lift_l is not None and lift_e < 0 and lift_l < 0)
        sym_rows.append(
            {
                "symbol": sym,
                "indicator": iid,
                "state": "BULL",
                "horizon": h,
                "sym_base_avg_pct": round(base_avg, 4),
                "sym_base_hit_pct": round(base_hit, 2),
                "n_early": ae.n,
                "n_late": al.n,
                "lift_early_pp": None if lift_e is None else round(lift_e, 4),
                "lift_late_pp": None if lift_l is None else round(lift_l, 4),
                "consistent_positive": consistent_pos,
                "consistent_negative": consistent_neg,
                **_acc_row(
                    avg=a.avg(),
                    hit=a.hit(),
                    n=a.n,
                    base_avg_pct=base_avg,
                    base_hit_pct=base_hit,
                ),
            }
        )
    sym_single_df = pd.DataFrame(sym_rows)

    sym_pair_rows = []
    for (sym, a, b, h), acc in sym_pair.items():
        if acc.n < min_n_sym:
            continue
        sb = sym_base.get((sym, h))
        if sb is None or sb.n == 0:
            continue
        base_avg = 100.0 * (sb.avg() or 0.0)
        base_hit = 100.0 * (sb.hit() or 0.0)
        ae = sym_pair_e.get((sym, a, b, h), _Acc())
        al = sym_pair_l.get((sym, a, b, h), _Acc())
        sbe = sym_base_e.get((sym, h), _Acc())
        sbl = sym_base_l.get((sym, h), _Acc())
        lift_e = lift_l = None
        if ae.n >= min_n_half and sbe.n >= min_n_half and ae.avg() is not None and sbe.avg() is not None:
            lift_e = 100.0 * ae.avg() - 100.0 * sbe.avg()
        if al.n >= min_n_half and sbl.n >= min_n_half and al.avg() is not None and sbl.avg() is not None:
            lift_l = 100.0 * al.avg() - 100.0 * sbl.avg()
        consistent_pos = bool(lift_e is not None and lift_l is not None and lift_e > 0 and lift_l > 0)
        consistent_neg = bool(lift_e is not None and lift_l is not None and lift_e < 0 and lift_l < 0)
        sym_pair_rows.append(
            {
                "symbol": sym,
                "signal_a": a,
                "signal_b": b,
                "combo": f"{a}=BULL & {b}=BULL",
                "horizon": h,
                "sym_base_avg_pct": round(base_avg, 4),
                "sym_base_hit_pct": round(base_hit, 2),
                "n_early": ae.n,
                "n_late": al.n,
                "lift_early_pp": None if lift_e is None else round(lift_e, 4),
                "lift_late_pp": None if lift_l is None else round(lift_l, 4),
                "consistent_positive": consistent_pos,
                "consistent_negative": consistent_neg,
                **_acc_row(
                    avg=acc.avg(),
                    hit=acc.hit(),
                    n=acc.n,
                    base_avg_pct=base_avg,
                    base_hit_pct=base_hit,
                ),
            }
        )
    sym_pair_df = pd.DataFrame(sym_pair_rows)

    meta = {
        "symbols_ok": sym_ok,
        "symbols_skip": sym_skip,
        "bars_used": bars_used,
        "elapsed_s": round(time.time() - t0, 1),
        "n_indicators": n_ind,
        "n_caches": len(caches),
        "min_n_global": min_n,
        "min_n_symbol": min_n_sym,
        "min_n_half": min_n_half,
        "n_top_pairs_for_symbol": len(top_pair_keys),
    }

    return {
        "meta": pd.DataFrame([meta]),
        "baseline": base_df,
        "single": single_df,
        "fresh_bull": fresh_df,
        "pairs": pair_df,
        "diff_buckets": diff_df,
        "symbol_single": sym_single_df,
        "symbol_pairs": sym_pair_df,
    }


def _top_table(
    df: pd.DataFrame,
    horizon: int,
    n: int,
    sort_col: str = "lift_vs_base_pp",
    ascending: bool = False,
    extra_filter=None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    sub = df[df["horizon"] == horizon].copy()
    if extra_filter is not None:
        sub = extra_filter(sub)
    if sub.empty:
        return sub
    return sub.sort_values(sort_col, ascending=ascending).head(n)


def _md_rows_signal(top: pd.DataFrame, label_col: str) -> list[str]:
    lines = [
        "| Signal | N | Avg ret % | Lift pp | Hit % | Hit lift pp |",
        "|--------|--:|----------:|--------:|------:|------------:|",
    ]
    for _, r in top.iterrows():
        lines.append(
            f"| {r[label_col]} | {int(r['n']):,} | {float(r['avg_ret_pct']):+.4f} | "
            f"{float(r['lift_vs_base_pp']):+.4f} | {float(r['hit_rate_pct']):.2f} | "
            f"{float(r['hit_lift_pp']):+.2f} |"
        )
    return lines


def write_summary_md(
    out_dir: Path,
    results: dict[str, pd.DataFrame],
    *,
    horizons: list[int],
    top_n: int,
) -> Path:
    meta = results["meta"].iloc[0].to_dict()
    base = results["baseline"]
    lines = [
        "# IND signal vs forward return",
        "",
        "## Methodology",
        "",
        "- Universe: warm `.indcache.pkl` + matching OHLCV CSV under `data/newdata/data`.",
        f"- Symbols used: **{int(meta['symbols_ok']):,}** (skipped {int(meta['symbols_skip']):,}); "
        f"bar-events: **{int(meta['bars_used']):,}**.",
        "- Signal at trigger bar close; entry at next open; return = Close[t+h]/Open[t+1]-1.",
        f"- Horizons (trading bars): {horizons}.",
        "- States: BULL(+1) / BEAR(-1) / NEUTRAL(0). Fresh BULL = becomes BULL today.",
        "- Pairs: co-occurring BULL & BULL. Per-symbol pairs limited to top global combos.",
        "- Per-symbol lift vs **that symbol's own** baseline; consistency = positive (or negative) "
        "lift in both chronological halves.",
        "- No IND_DIFF / score / ATR / capital gates — unconditional association.",
        "",
        "## Baseline (all valid bars)",
        "",
        "| Horizon | N | Avg ret % | Hit rate % |",
        "|--------:|--:|----------:|-----------:|",
    ]
    for _, r in base.iterrows():
        lines.append(
            f"| {int(r['horizon'])}d | {int(r['n']):,} | {float(r['avg_ret_pct']):+.4f} | "
            f"{float(r['hit_rate_pct']):.2f} |"
        )

    for h in horizons:
        lines += ["", f"## Top individual BULL states — {h}d (global)", ""]
        sub = results["single"]
        if not sub.empty:
            sub = sub[(sub["horizon"] == h) & (sub["state"] == "BULL")]
        top = _top_table(sub, h, top_n)
        if not top.empty:
            top = top.assign(label=top["indicator"].astype(str) + "=BULL")
            lines += _md_rows_signal(top, "label")
        else:
            lines.append("_(no rows)_")

        lines += ["", f"## Top FRESH_BULL transitions — {h}d (global)", ""]
        fr = results["fresh_bull"]
        topf = _top_table(fr, h, top_n)
        if not topf.empty:
            topf = topf.assign(label=topf["indicator"].astype(str) + " FRESH_BULL")
            lines += _md_rows_signal(topf, "label")
        else:
            lines.append("_(no rows)_")

        lines += ["", f"## Top BULL+BULL pairs — {h}d (global)", ""]
        topp = _top_table(results["pairs"], h, top_n)
        if not topp.empty:
            lines += _md_rows_signal(topp, "combo")
        else:
            lines.append("_(no rows)_")

        lines += ["", f"## IND_DIFF (long-aligned) buckets — {h}d", ""]
        db = results["diff_buckets"]
        if not db.empty:
            sub = db[db["horizon"] == h].sort_values("lift_vs_base_pp", ascending=False)
            lines.append("| Bucket | N | Avg ret % | Lift pp | Hit % |")
            lines.append("|--------|--:|----------:|--------:|------:|")
            for _, r in sub.iterrows():
                lines.append(
                    f"| {r['bucket']} | {int(r['n']):,} | {float(r['avg_ret_pct']):+.4f} | "
                    f"{float(r['lift_vs_base_pp']):+.4f} | {float(r['hit_rate_pct']):.2f} |"
                )

        ss = results.get("symbol_single", pd.DataFrame())
        lines += [
            "",
            f"## Top consistent symbol × BULL signal — {h}d",
            "",
            "Lift vs symbol's own baseline; requires positive lift in early **and** late halves.",
            "",
            "| Symbol | Signal | N | Avg ret % | Lift pp | Hit % | Early lift | Late lift |",
            "|--------|--------|--:|----------:|--------:|------:|-----------:|----------:|",
        ]
        if not ss.empty:
            top_ss = _top_table(
                ss,
                h,
                top_n,
                extra_filter=lambda d: d[d["consistent_positive"] == True],  # noqa: E712
            )
            for _, r in top_ss.iterrows():
                lines.append(
                    f"| {r['symbol']} | {r['indicator']}=BULL | {int(r['n']):,} | "
                    f"{float(r['avg_ret_pct']):+.4f} | {float(r['lift_vs_base_pp']):+.4f} | "
                    f"{float(r['hit_rate_pct']):.2f} | {float(r['lift_early_pp']):+.4f} | "
                    f"{float(r['lift_late_pp']):+.4f} |"
                )
            if top_ss.empty:
                lines.append("| _(none)_ | | | | | | | |")

            lines += [
                "",
                f"## Weak/negative consistent symbol × BULL — {h}d",
                "",
                "| Symbol | Signal | N | Avg ret % | Lift pp | Hit % | Early lift | Late lift |",
                "|--------|--------|--:|----------:|--------:|------:|-----------:|----------:|",
            ]
            bot = _top_table(
                ss,
                h,
                top_n,
                ascending=True,
                extra_filter=lambda d: d[d["consistent_negative"] == True],  # noqa: E712
            )
            for _, r in bot.iterrows():
                lines.append(
                    f"| {r['symbol']} | {r['indicator']}=BULL | {int(r['n']):,} | "
                    f"{float(r['avg_ret_pct']):+.4f} | {float(r['lift_vs_base_pp']):+.4f} | "
                    f"{float(r['hit_rate_pct']):.2f} | {float(r['lift_early_pp']):+.4f} | "
                    f"{float(r['lift_late_pp']):+.4f} |"
                )
            if bot.empty:
                lines.append("| _(none)_ | | | | | | | |")

        sp = results.get("symbol_pairs", pd.DataFrame())
        lines += [
            "",
            f"## Top consistent symbol × combo — {h}d",
            "",
            "| Symbol | Combo | N | Avg ret % | Lift pp | Hit % | Early | Late |",
            "|--------|-------|--:|----------:|--------:|------:|------:|-----:|",
        ]
        if not sp.empty:
            top_sp = _top_table(
                sp,
                h,
                top_n,
                extra_filter=lambda d: d[d["consistent_positive"] == True],  # noqa: E712
            )
            for _, r in top_sp.iterrows():
                lines.append(
                    f"| {r['symbol']} | {r['combo']} | {int(r['n']):,} | "
                    f"{float(r['avg_ret_pct']):+.4f} | {float(r['lift_vs_base_pp']):+.4f} | "
                    f"{float(r['hit_rate_pct']):.2f} | {float(r['lift_early_pp']):+.4f} | "
                    f"{float(r['lift_late_pp']):+.4f} |"
                )
            if top_sp.empty:
                lines.append("| _(none)_ | | | | | | | |")

    lines += [
        "",
        "## Caveats",
        "",
        "- In-sample over full history; half-split is a weak consistency check, not true OOS.",
        "- Multiple testing is severe: ~47 indicators × ~1k symbols × horizons × pairs — "
        "top ranks are inflated by selection.",
        "- Persistent trend states (price vs SMA) largely label 'already in uptrend'.",
        "- No costs, gaps, or capital constraints; many lifts are small vs noise.",
        "- Per-symbol combos only scored for top global pairs (see meta `n_top_pairs_for_symbol`).",
        "- Closed-trade PnL reports are selection-biased (only gated IND entries).",
        "",
        "## Actionability",
        "",
        "- Prefer signals with large **n**, positive lift vs baseline, and "
        "`consistent_positive` across halves.",
        "- Global lifts that are tiny (<< 0.1 pp/day) are usually not strong enough to "
        "reweight IND scoring without OOS confirmation.",
        "- Symbol-specific edges may feed watchlists / overrides, not universal weights.",
        "",
    ]
    path = out_dir / "IND_Signal_Forward_Returns_Summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="IND indicator state vs forward returns")
    ap.add_argument("--data-dir", type=Path, default=_REPO / "data" / "newdata" / "data")
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--horizons", default="1,5,20")
    ap.add_argument("--max-symbols", type=int, default=0)
    ap.add_argument("--min-n", type=int, default=500, help="Min n for global tables")
    ap.add_argument("--min-n-sym", type=int, default=40, help="Min n for symbol×signal")
    ap.add_argument("--min-n-half", type=int, default=15, help="Min n per half for consistency")
    ap.add_argument("--max-pair-for-sym", type=int, default=25, help="Top global pairs for per-symbol")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--warmup", type=int, default=220)
    ap.add_argument("-o", "--out-dir", type=Path, default=_REPO / "drive")
    args = ap.parse_args()

    data_dir = args.data_dir
    cache_dir = args.cache_dir or (data_dir / ".brt_indicator_cache")
    horizons = [int(x) for x in str(args.horizons).split(",") if x.strip()]
    max_sym = args.max_symbols if args.max_symbols > 0 else None

    if not cache_dir.is_dir():
        print(f"Missing cache dir: {cache_dir}", file=sys.stderr)
        return 1

    print(f"[ind-fwd] data={data_dir}")
    print(f"[ind-fwd] cache={cache_dir}")
    print(
        f"[ind-fwd] horizons={horizons} max_symbols={max_sym or 'all'} "
        f"min_n={args.min_n} min_n_sym={args.min_n_sym}",
        flush=True,
    )

    results = analyze(
        data_dir,
        cache_dir,
        horizons=horizons,
        max_symbols=max_sym,
        min_n=args.min_n,
        min_n_sym=args.min_n_sym,
        min_n_half=args.min_n_half,
        warmup=args.warmup,
        max_pair_for_sym=args.max_pair_for_sym,
    )

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%y%m%d%H%M%S")
    for name, df in results.items():
        p = out_dir / f"IND_Signal_Fwd_{name}_{stamp}.csv"
        df.to_csv(p, index=False)
        print(f"Wrote {p} ({len(df)} rows)")
        df.to_csv(out_dir / f"IND_Signal_Fwd_{name}_Latest.csv", index=False)

    md = write_summary_md(out_dir, results, horizons=horizons, top_n=args.top)
    print(f"Wrote {md}")
    print(results["meta"].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
