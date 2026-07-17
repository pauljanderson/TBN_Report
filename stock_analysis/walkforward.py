"""Rolling walk-forward fold definitions and param aggregation for per-symbol optimizer."""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class WalkForwardFold:
    name: str
    train_start: str
    train_end: str
    val_start: str
    val_end: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def norm_date_str(d: str | Any) -> str:
    """Normalize trade/bar dates to YYYY-MM-DD for window comparisons."""
    s = str(d or "").strip().replace("/", "-")
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        d8 = digits[:8]
        return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"
    return s[:10]


def build_rolling_folds(
    first_date: pd.Timestamp,
    last_date: pd.Timestamp,
    *,
    train_years: int = 3,
    test_years: int = 1,
    step_years: int = 1,
    wf_start: str | None = None,
    wf_end: str | None = None,
) -> list[WalkForwardFold]:
    """
    Rolling walk-forward: train on train_years, validate on test_years, advance step_years.

    First validation year begins train_years after wf_start (or first_date).
    """
    start = pd.Timestamp(wf_start) if wf_start else pd.Timestamp(first_date)
    end = pd.Timestamp(wf_end) if wf_end else pd.Timestamp(last_date)
    if start < pd.Timestamp(first_date):
        start = pd.Timestamp(first_date)
    if end > pd.Timestamp(last_date):
        end = pd.Timestamp(last_date)
    if end <= start:
        return []

    folds: list[WalkForwardFold] = []
    val_start = start + pd.DateOffset(years=int(train_years))
    idx = 0
    while val_start <= end:
        val_end = val_start + pd.DateOffset(years=int(test_years)) - pd.Timedelta(days=1)
        if val_end > end:
            val_end = end
        train_start = val_start - pd.DateOffset(years=int(train_years))
        train_end = val_start - pd.Timedelta(days=1)
        if train_start < start:
            train_start = start
        if train_end < train_start:
            break
        if val_end < val_start:
            break
        folds.append(
            WalkForwardFold(
                name=f"fold{idx}_{train_start.year}_{val_start.year}",
                train_start=train_start.strftime("%Y-%m-%d"),
                train_end=train_end.strftime("%Y-%m-%d"),
                val_start=val_start.strftime("%Y-%m-%d"),
                val_end=val_end.strftime("%Y-%m-%d"),
            )
        )
        val_start = val_start + pd.DateOffset(years=int(step_years))
        idx += 1
    return folds


def _is_boolish(values: list[Any]) -> bool:
    return all(isinstance(v, bool) for v in values)


def _is_intish(values: list[Any]) -> bool:
    return all(isinstance(v, bool) or (isinstance(v, int) and not isinstance(v, bool)) for v in values)


def median_params_across_folds(
    fold_param_dicts: list[dict[str, Any]],
    baseline: dict[str, Any],
    tunable_keys: list[str],
) -> dict[str, Any]:
    """
    Merge per-fold optimized params: median for numeric, mode for discrete/bool.
    Keys not present in any fold fall back to baseline.
    """
    out = dict(baseline)
    for key in tunable_keys:
        vals = [d[key] for d in fold_param_dicts if key in d]
        if not vals:
            continue
        if _is_boolish(vals):
            out[key] = max(set(vals), key=vals.count)
        elif _is_intish(vals):
            out[key] = int(round(statistics.median([float(v) for v in vals])))
        else:
            try:
                med = float(statistics.median([float(v) for v in vals]))
                out[key] = round(med, 6) if abs(med) < 100 else round(med, 4)
            except (TypeError, ValueError):
                out[key] = max(set(vals), key=vals.count)
    return out


def median_oos_score(scores: list[float]) -> float:
    vals = [float(s) for s in scores if s is not None]
    return float(statistics.median(vals)) if vals else 0.0
