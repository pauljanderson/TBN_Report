#!/usr/bin/env python3
"""Report-only dump of Trading Central-style IND outlooks (no gates).

Loads OHLCV + warm ``.indcache.pkl`` / ``build_entry_indicator_precompute`` for a
symbol list and prints or writes CSV of as-of TC sums/outlooks plus legacy
``IND_DIFF`` / ``IND_SCORE`` for comparison.

Expected columns from the indicator engine (report-only; not used for entry):
  IND_TC_SHORT_SUM, IND_TC_SHORT_OUTLOOK,
  IND_TC_INT_SUM,   IND_TC_INT_OUTLOOK,
  IND_TC_LONG_SUM,  IND_TC_LONG_OUTLOOK
Optional counts: IND_TC_SHORT_N, IND_TC_INT_N, IND_TC_LONG_N.

Bucket assumptions (engine-owned; mirrored here for readers):
  Short ≤3d→±3, 4–8→±2, 9–30→±1; Intermediate ≤10→±3, 11–30→±2, 31–90→±1;
  Long ≤30→±3, 31–90→±2, 91–252→±1. Outlook = Strong / Neutral / Weak by sum sign.

Fails clearly if TC fields are not yet present on the public IND snapshot API.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_SA = _REPO / "stock_analysis"
for p in (_REPO, _SA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from brt_entry_indicators import (  # noqa: E402
    build_entry_indicator_precompute,
    ind_score_at_bar,
    resolve_indicator_cache_dir,
    snapshot_for_entry,
)
from rocket_brt import load_csv  # noqa: E402

try:
    from brt_entry_indicators import IND_TC_EXPORT_COLS as _IND_TC_EXPORT_COLS  # noqa: E402
except ImportError:  # core / audit wiring not merged yet
    _IND_TC_EXPORT_COLS = (
        "IND_TC_SHORT_SUM",
        "IND_TC_SHORT_OUTLOOK",
        "IND_TC_INT_SUM",
        "IND_TC_INT_OUTLOOK",
        "IND_TC_LONG_SUM",
        "IND_TC_LONG_OUTLOOK",
        "IND_TC_SHORT_N",
        "IND_TC_INT_N",
        "IND_TC_LONG_N",
    )

# MarkTen (same set as MARKTEN_WPBR; ordered for readable dumps)
DEFAULT_SYMBOLS = [
    "AAPL",
    "AMD",
    "AMZN",
    "AU",
    "META",
    "MSFT",
    "NVDA",
    "NFLX",
    "GOOGL",
    "TSLA",
]

TC_CORE_COLS = [
    "IND_TC_SHORT_SUM",
    "IND_TC_SHORT_OUTLOOK",
    "IND_TC_INT_SUM",
    "IND_TC_INT_OUTLOOK",
    "IND_TC_LONG_SUM",
    "IND_TC_LONG_OUTLOOK",
]
TC_OPT_N_COLS = [c for c in _IND_TC_EXPORT_COLS if c.endswith("_N")]
# Keep export order from engine when available; ensure core cols always listed.
TC_ALL_COLS = list(dict.fromkeys(list(TC_CORE_COLS) + list(TC_OPT_N_COLS)))
LEGACY_COLS = ["IND_DIFF", "IND_SCORE"]


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in str(raw).split(",") if s.strip()]


def _parse_as_of(raw: Optional[str]) -> Optional[int]:
    if raw is None or str(raw).strip() == "":
        return None
    digits = "".join(ch for ch in str(raw).strip() if ch.isdigit())
    if len(digits) < 8:
        raise SystemExit(f"Invalid --as-of {raw!r}; expected YYYYMMDD or YYYY-MM-DD")
    return int(digits[:8])


def _ymd8(v: Any) -> int:
    s = "".join(ch for ch in str(v).strip() if ch.isdigit())[:8]
    return int(s) if len(s) == 8 else 0


def _resolve_bar_index(dates: Any, as_of: Optional[int]) -> int:
    """Last bar on/before as_of, or last bar if as_of is None."""
    n = len(dates)
    if n == 0:
        return -1
    if as_of is None:
        return n - 1
    # dates are int YYYYMMDD
    lo, hi = 0, n - 1
    best = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        d = int(dates[mid])
        if d <= as_of:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _discover_tc_extractor() -> Optional[Callable[..., dict[str, Any]]]:
    """Prefer a dedicated public helper if the core worker exported one."""
    bei = importlib.import_module("brt_entry_indicators")
    for name in (
        "ind_tc_at_bar",
        "tc_outlook_at_bar",
        "compute_ind_tc_at_bar",
        "snapshot_tc_outlook",
        "tc_fields_at_bar",
    ):
        fn = getattr(bei, name, None)
        if callable(fn):
            return fn  # type: ignore[return-value]
    return None


def _row_from_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in TC_ALL_COLS + LEGACY_COLS:
        if c in snap and snap.get(c) not in (None, ""):
            out[c] = snap[c]
    return out


def _row_from_extractor(
    fn: Callable[..., dict[str, Any]],
    pre: Any,
    bar_i: int,
) -> dict[str, Any]:
    try:
        raw = fn(pre, bar_i)
    except TypeError:
        raw = fn(pre, bar_i, "LONG")
    if not isinstance(raw, dict):
        return {}
    return _row_from_snapshot(raw)


def _tc_present(row: dict[str, Any]) -> bool:
    return all(c in row for c in TC_CORE_COLS)


def _legacy_from_apis(pre: Any, bar_i: int) -> dict[str, Any]:
    """Fill IND_DIFF / IND_SCORE from existing public APIs when snapshot omits them."""
    out: dict[str, Any] = {}
    snap = snapshot_for_entry(pre, bar_i, "LONG")
    if "IND_DIFF" in snap:
        out["IND_DIFF"] = snap["IND_DIFF"]
    if "IND_SCORE" in snap and snap.get("IND_SCORE") not in (None, ""):
        out["IND_SCORE"] = snap["IND_SCORE"]
    else:
        sc = ind_score_at_bar(pre, bar_i)
        if sc is not None:
            out["IND_SCORE"] = f"{float(sc):.2f}"
    return out


def _extract_bar_row(pre: Any, bar_i: int, extractor: Optional[Callable[..., dict[str, Any]]]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    if extractor is not None:
        row.update(_row_from_extractor(extractor, pre, bar_i))
    if not _tc_present(row):
        snap = snapshot_for_entry(pre, bar_i, "LONG")
        row.update(_row_from_snapshot(snap))
    # Always enrich legacy if missing
    if "IND_DIFF" not in row or "IND_SCORE" not in row:
        leg = _legacy_from_apis(pre, bar_i)
        for k, v in leg.items():
            row.setdefault(k, v)
    return row


def _load_pre(symbol: str, data_dir: Path, cache_dir: Path) -> Any:
    csv_path = data_dir / f"{symbol}.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"missing OHLCV: {csv_path}")
    df = load_csv(str(csv_path))
    pre = build_entry_indicator_precompute(
        df, symbol=symbol, cache_dir=cache_dir, use_cache=True
    )
    if pre is None:
        raise RuntimeError(f"precompute unavailable for {symbol} (need ≥220 bars + Volume)")
    return pre


def collect_rows(
    symbols: list[str],
    *,
    data_dir: Path,
    cache_dir: Path,
    as_of: Optional[int],
    history_bars: int,
) -> tuple[pd.DataFrame, list[str]]:
    """Return (dataframe, missing_tc_symbols)."""
    extractor = _discover_tc_extractor()
    rows: list[dict[str, Any]] = []
    missing_tc: list[str] = []
    hist_n = max(1, int(history_bars))

    for sym in symbols:
        try:
            pre = _load_pre(sym, data_dir, cache_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"[tc-outlook] {sym}: SKIP ({exc})", file=sys.stderr)
            continue

        dates = pre.dates
        end_i = _resolve_bar_index(dates, as_of)
        if end_i < 0:
            print(f"[tc-outlook] {sym}: SKIP (no bar on/before as-of)", file=sys.stderr)
            continue

        start_i = max(0, end_i - hist_n + 1)
        sample = _extract_bar_row(pre, end_i, extractor)
        if not _tc_present(sample):
            missing_tc.append(sym)
            # Still emit legacy-only rows so callers see IND_DIFF/SCORE while waiting on core.
            for i in range(start_i, end_i + 1):
                leg = _legacy_from_apis(pre, i)
                rows.append(
                    {
                        "as_of": int(dates[i]),
                        "symbol": sym,
                        **{c: "" for c in TC_ALL_COLS},
                        **leg,
                        "tc_available": 0,
                    }
                )
            continue

        for i in range(start_i, end_i + 1):
            bar = _extract_bar_row(pre, i, extractor)
            rows.append(
                {
                    "as_of": int(dates[i]),
                    "symbol": sym,
                    **{c: bar.get(c, "") for c in TC_ALL_COLS},
                    "IND_DIFF": bar.get("IND_DIFF", ""),
                    "IND_SCORE": bar.get("IND_SCORE", ""),
                    "tc_available": 1,
                }
            )

    cols = ["as_of", "symbol"] + TC_ALL_COLS + LEGACY_COLS + ["tc_available"]
    df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
    return df, missing_tc


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Dump Trading Central-style IND outlooks (report-only, no gates)"
    )
    ap.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols (default: MarkTen)",
    )
    ap.add_argument(
        "--as-of",
        default=None,
        help="As-of date YYYYMMDD or YYYY-MM-DD (default: last available bar)",
    )
    ap.add_argument(
        "--history-bars",
        type=int,
        default=1,
        help="Bars per symbol ending at as-of (default 1 = snapshot only)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional CSV output path (prints to stdout if omitted)",
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=_REPO / "data" / "newdata" / "data",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Indicator cache dir (default: <data-dir>/.brt_indicator_cache)",
    )
    args = ap.parse_args()

    symbols = _parse_symbols(args.symbols)
    as_of = _parse_as_of(args.as_of)
    data_dir = Path(args.data_dir)
    cache_dir = (
        Path(args.cache_dir)
        if args.cache_dir
        else resolve_indicator_cache_dir(data_dir=data_dir, repo_root=_REPO)
    )

    print(f"[tc-outlook] data={data_dir}", flush=True)
    print(f"[tc-outlook] cache={cache_dir}", flush=True)
    print(
        f"[tc-outlook] symbols={len(symbols)} as_of={as_of or 'latest'} "
        f"history_bars={args.history_bars}",
        flush=True,
    )

    df, missing_tc = collect_rows(
        symbols,
        data_dir=data_dir,
        cache_dir=cache_dir,
        as_of=as_of,
        history_bars=int(args.history_bars),
    )

    if df.empty:
        print("[tc-outlook] no rows produced", file=sys.stderr)
        return 1

    # Prefer latest bar per symbol for console summary when history > 1
    if int(args.history_bars) > 1:
        latest = df.sort_values(["symbol", "as_of"]).groupby("symbol", as_index=False).tail(1)
    else:
        latest = df

    # Console: compact latest view
    show = [
        "as_of",
        "symbol",
        "IND_TC_SHORT_OUTLOOK",
        "IND_TC_SHORT_SUM",
        "IND_TC_INT_OUTLOOK",
        "IND_TC_INT_SUM",
        "IND_TC_LONG_OUTLOOK",
        "IND_TC_LONG_SUM",
        "IND_DIFF",
        "IND_SCORE",
        "tc_available",
    ]
    print(latest[show].to_string(index=False), flush=True)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"[tc-outlook] wrote {out} ({len(df)} rows)", flush=True)

    if missing_tc:
        cols = ", ".join(TC_CORE_COLS)
        print(
            "\n[tc-outlook] ERROR: Trading Central IND columns missing from indicator engine "
            f"for: {', '.join(missing_tc)}\n"
            f"  Expected on snapshot / public API: {cols}\n"
            "  (+ optional IND_TC_*_N). Core scoring in brt_entry_indicators is not available "
            "yet; re-run after IND_TC_* fields land on snapshot_for_entry (or a helper like "
            "ind_tc_at_bar).",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
