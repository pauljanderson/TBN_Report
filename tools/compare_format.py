"""Minimal helpers used by prediction-market HTML writers.

The full house compare_format (ann_ror_from_closed for BRT sleeves) is not in
this workspace. Prediction tickets are 1-contract holds measured in hours, so
annualized ROR is omitted upstream; these stubs keep imports green.
"""
from __future__ import annotations

from decimal import Decimal


def format_money(value) -> str:
    try:
        number = Decimal(str(value))
    except Exception:
        return "$0.00"
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):.2f}"


def ann_ror_from_closed(*_args, **_kwargs):
    """Not computed for 1-contract prediction tickets in this workspace."""
    return None
