#!/usr/bin/env python3
"""StockBee Market Monitor (MM) breadth series for SB ``burst_mm_gate``.

Builds a lag-safe daily series of ±4% breadth over a 10-session window:

  up4[D] / down4[D]  — liquid names up/down ≥4% on completed day D
  mm_ratio[D]        — sum(up4[D-9..D]) / max(sum(down4[D-9..D]), 1)

Gate usage (in ``rocket_stockbee_burst``): allow signal on T iff
``mm_ratio[T-1] >= burst_mm_min_ratio`` (do not use same-bar mm_ratio[T]).

Spec: ``drive/.../stockbee_momentum_burst/SB_NEXT_BUILDS.md`` priority 1.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

try:
    from ohlcv_store import list_csv_symbols as _list_csv_symbols
except ImportError:
    try:
        from stock_analysis.ohlcv_store import list_csv_symbols as _list_csv_symbols  # type: ignore
    except ImportError:
        _list_csv_symbols = None  # type: ignore

# Obvious ETFs / indices to skip when listing “common stocks” from the CSV store.
_DEFAULT_ETF_EXCLUDE = frozenset(
    {
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "MDY",
        "IJR",
        "IWF",
        "IWD",
        "VTI",
        "VOO",
        "IVV",
        "RSP",
        "XLF",
        "XLK",
        "XLE",
        "XLV",
        "XLI",
        "XLY",
        "XLP",
        "XLU",
        "XLB",
        "XLRE",
        "XLC",
        "HYG",
        "LQD",
        "TLT",
        "GLD",
        "SLV",
        "USO",
        "UNG",
        "TQQQ",
        "SQQQ",
        "SPXU",
        "SPXL",
        "UVXY",
        "VIXY",
    }
)


@dataclass
class MMBuildConfig:
    """Liquidity / membership knobs for MM daily counts (not the SB entry gate)."""

    mm_min_shares: float = 1000.0
    mm_min_adv_usd: float = 250_000.0  # 0 = disable dollar-volume filter
    mm_min_price: float = 5.0
    mm_move_pct: float = 0.04
    mm_lookback: int = 10
    exclude_symbols: frozenset[str] = _DEFAULT_ETF_EXCLUDE


def _ymd(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d)[:10].replace("-", "")
    return s


def list_mm_symbols(data_dir: Path, exclude: Optional[Iterable[str]] = None) -> list[str]:
    ex = {str(x).strip().upper() for x in (exclude or _DEFAULT_ETF_EXCLUDE) if str(x).strip()}
    if _list_csv_symbols is not None:
        syms = [s.upper() for s in _list_csv_symbols(data_dir, include_spy=False)]
    else:
        syms = sorted(
            p.stem.upper()
            for p in Path(data_dir).glob("*.csv")
            if p.is_file() and p.stem.upper() != "SPY"
        )
    return [s for s in syms if s not in ex]


def _load_ohlcv_light(path: Path) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(path, usecols=lambda c: str(c).strip().lower() in ("date", "close", "volume"))
    except Exception:
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            return None
    cols = {str(c).strip().lower(): c for c in df.columns}
    if "date" not in cols or "close" not in cols:
        return None
    date_c, close_c = cols["date"], cols["close"]
    vol_c = cols.get("volume")
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[date_c], errors="coerce"),
            "Close": pd.to_numeric(df[close_c], errors="coerce"),
            "Volume": pd.to_numeric(df[vol_c], errors="coerce") if vol_c else 0.0,
        }
    )
    out = out.dropna(subset=["Date", "Close"]).sort_values("Date")
    if out.empty:
        return None
    return out.reset_index(drop=True)


def build_mm_frame(data_dir: Path, cfg: Optional[MMBuildConfig] = None) -> pd.DataFrame:
    """Scan CSV universe → daily up4/down4 + 10d mm_ratio (indexed by calendar date)."""
    cfg = cfg or MMBuildConfig()
    data_dir = Path(data_dir)
    symbols = list_mm_symbols(data_dir, cfg.exclude_symbols)
    if not symbols:
        return pd.DataFrame(
            columns=["Date", "up4", "down4", "ups_10", "downs_10", "mm_ratio", "n_eligible"]
        )

    # Accumulate per-day counts without materializing a full panel.
    up_counts: dict[pd.Timestamp, int] = {}
    down_counts: dict[pd.Timestamp, int] = {}
    elig_counts: dict[pd.Timestamp, int] = {}
    move = float(cfg.mm_move_pct)
    min_sh = float(cfg.mm_min_shares or 0.0)
    min_usd = float(cfg.mm_min_adv_usd or 0.0)
    min_px = float(cfg.mm_min_price or 0.0)

    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.is_file():
            # list_csv_symbols may return names without requiring path casing match
            matches = list(data_dir.glob(f"{sym}.csv")) + list(data_dir.glob(f"{sym.lower()}.csv"))
            if not matches:
                continue
            path = matches[0]
        df = _load_ohlcv_light(path)
        if df is None or len(df) < 2:
            continue
        c = df["Close"].to_numpy(dtype=np.float64)
        v = df["Volume"].to_numpy(dtype=np.float64)
        dates = df["Date"].to_numpy()
        for i in range(1, len(df)):
            c0, c1 = float(c[i - 1]), float(c[i])
            if not (np.isfinite(c0) and np.isfinite(c1) and c0 > 0 and c1 > 0):
                continue
            vol = float(v[i]) if np.isfinite(v[i]) else 0.0
            if min_px > 0 and c1 < min_px:
                continue
            if min_sh > 0 and vol < min_sh:
                continue
            # Telechart-style: volume up vs prior day
            vol_prev = float(v[i - 1]) if np.isfinite(v[i - 1]) else 0.0
            if vol <= vol_prev:
                continue
            if min_usd > 0 and (c1 * vol) < min_usd:
                continue
            d = pd.Timestamp(dates[i]).normalize()
            elig_counts[d] = elig_counts.get(d, 0) + 1
            ret = c1 / c0 - 1.0
            if ret >= move:
                up_counts[d] = up_counts.get(d, 0) + 1
            elif ret <= -move:
                down_counts[d] = down_counts.get(d, 0) + 1

    all_dates = sorted(set(up_counts) | set(down_counts) | set(elig_counts))
    if not all_dates:
        return pd.DataFrame(
            columns=["Date", "up4", "down4", "ups_10", "downs_10", "mm_ratio", "n_eligible"]
        )

    up4 = np.array([int(up_counts.get(d, 0)) for d in all_dates], dtype=np.int64)
    down4 = np.array([int(down_counts.get(d, 0)) for d in all_dates], dtype=np.int64)
    elig = np.array([int(elig_counts.get(d, 0)) for d in all_dates], dtype=np.int64)
    lb = max(1, int(cfg.mm_lookback))
    # Rolling sum over trading days present in the series (not calendar days).
    ups_10 = np.convolve(up4, np.ones(lb, dtype=np.float64), mode="full")[: len(up4)]
    downs_10 = np.convolve(down4, np.ones(lb, dtype=np.float64), mode="full")[: len(down4)]
    # Incomplete window at start: still define ratio (blog uses 10 completed sessions;
    # early history is thinner — documented limitation).
    mm_ratio = ups_10 / np.maximum(downs_10, 1.0)

    out = pd.DataFrame(
        {
            "Date": all_dates,
            "up4": up4,
            "down4": down4,
            "ups_10": ups_10.astype(np.int64),
            "downs_10": downs_10.astype(np.int64),
            "mm_ratio": mm_ratio,
            "n_eligible": elig,
        }
    )
    return out


def mm_ratio_lookup(frame: pd.DataFrame) -> dict[str, float]:
    """Map YYYYMMDD → mm_ratio for lag-1 gate lookups."""
    out: dict[str, float] = {}
    if frame is None or frame.empty:
        return out
    for _, row in frame.iterrows():
        key = _ymd(row["Date"])
        try:
            out[key] = float(row["mm_ratio"])
        except (TypeError, ValueError):
            continue
    return out


def save_mm_frame(frame: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def load_mm_frame(path: Path) -> Optional[pd.DataFrame]:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if "Date" not in df.columns or "mm_ratio" not in df.columns:
        return None
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    return df


def build_or_load_mm_series(
    data_dir: Path,
    *,
    cfg: Optional[MMBuildConfig] = None,
    cache_path: Optional[Path] = None,
    force_rebuild: bool = False,
) -> tuple[pd.DataFrame, dict[str, float], Path]:
    """Return (frame, ymd→ratio, path_used). Rebuilds when cache missing or force_rebuild."""
    cfg = cfg or MMBuildConfig()
    cache_path = Path(cache_path) if cache_path else Path("drive") / "SB_MM_Series_latest.csv"
    if not force_rebuild:
        cached = load_mm_frame(cache_path)
        if cached is not None and not cached.empty:
            return cached, mm_ratio_lookup(cached), cache_path
    frame = build_mm_frame(data_dir, cfg)
    save_mm_frame(frame, cache_path)
    return frame, mm_ratio_lookup(frame), cache_path


def mm_cfg_from_burst(cfg: Any) -> MMBuildConfig:
    """Map BurstConfig / BRTConfig fields onto MMBuildConfig."""
    return MMBuildConfig(
        mm_min_shares=float(getattr(cfg, "mm_min_shares", 1000.0) or 1000.0),
        mm_min_adv_usd=float(getattr(cfg, "mm_min_adv_usd", 250_000.0) or 0.0),
        mm_min_price=float(getattr(cfg, "mm_min_price", 5.0) or 5.0),
        mm_move_pct=float(getattr(cfg, "mm_move_pct", 0.04) or 0.04),
        mm_lookback=int(getattr(cfg, "mm_lookback", 10) or 10),
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Build StockBee Market Monitor series")
    ap.add_argument("data_dir", nargs="?", default="data/newdata/data")
    ap.add_argument("-o", "--output", default="drive/SB_MM_Series_latest.csv")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    frame, lookup, path = build_or_load_mm_series(
        Path(args.data_dir),
        cache_path=Path(args.output),
        force_rebuild=bool(args.force),
    )
    print(f"[MM] wrote {path} rows={len(frame)} dates_with_ratio={len(lookup)}")
    if not frame.empty:
        print(frame.tail(5).to_string(index=False))
