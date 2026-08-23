"""House Calmar / Sharpe helpers (Report-aligned, descriptive only).

Calmar uses book Ann ROR % and Max DD % (same fields as Report).
Sharpe uses consecutive equity levels (daily EquityCurve when available), rf=0,
annualized with sqrt(252). Not a forecast or institutional composite score.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional, Sequence


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        x = float(value)
        return x if math.isfinite(x) else None
    s = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.upper() in {"N/A", "NA", "—", "-", "NONE"}:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def calmar_ratio(
    ann_ror_pct: Any,
    max_dd_pct: Any,
    *,
    eps: float = 1e-9,
) -> Optional[float]:
    """Calmar = Ann ROR % / |Max DD %|.

    Ann ROR is the Report book formula (percent points, e.g. 45.0 for 45%).
    Max DD is Report Max_DD (percent points, e.g. 12.5 for 12.5%).
    Returns None when Max DD is missing or |Max DD| <= eps (avoid blow-ups).
    """
    ann = _as_float(ann_ror_pct)
    dd = _as_float(max_dd_pct)
    if ann is None or dd is None:
        return None
    abs_dd = abs(dd)
    if abs_dd <= eps:
        return None
    return ann / abs_dd


def sharpe_from_equity_values(
    equity_values: Sequence[Any] | Iterable[Any],
    *,
    periods_per_year: float = 252.0,
    rf: float = 0.0,
    min_obs: int = 2,
) -> Optional[float]:
    """Sharpe from consecutive equity levels (rf=0 by default).

    ``r_t = E_t / E_{t-1} - 1`` on positive finite levels, then
    ``mean(r - rf) / std(r, ddof=1) * sqrt(periods_per_year)``.

    Intended for **daily** EquityCurve rows (same series as Max_DD / passive
    regular). Do not use sqrt(252) on sparse exit-date-only curves without
    documenting the frequency mismatch.
    """
    vals: list[float] = []
    for v in equity_values:
        x = _as_float(v)
        if x is None or x <= 0:
            continue
        vals.append(x)
    if len(vals) < min_obs + 1:
        return None
    rets: list[float] = []
    for i in range(1, len(vals)):
        prev = vals[i - 1]
        if prev <= 0:
            continue
        rets.append(vals[i] / prev - 1.0)
    if len(rets) < min_obs:
        return None
    n = len(rets)
    mu = sum(rets) / n
    var = sum((r - mu) ** 2 for r in rets) / (n - 1)
    if var <= 0:
        return None
    sig = math.sqrt(var)
    if sig <= 0 or periods_per_year <= 0:
        return None
    return ((mu - float(rf)) / sig) * math.sqrt(float(periods_per_year))


def format_calmar(ann_ror_pct: Any, max_dd_pct: Any, *, digits: int = 2) -> Any:
    """Report cell: rounded float or ``N/A``."""
    c = calmar_ratio(ann_ror_pct, max_dd_pct)
    if c is None:
        return "N/A"
    return round(c, digits)


def format_sharpe(equity_values: Sequence[Any] | Iterable[Any] | None, *, digits: int = 2) -> Any:
    """Report / EquityMeta cell: rounded float or ``N/A``."""
    if equity_values is None:
        return "N/A"
    s = sharpe_from_equity_values(equity_values)
    if s is None:
        return "N/A"
    return round(s, digits)
