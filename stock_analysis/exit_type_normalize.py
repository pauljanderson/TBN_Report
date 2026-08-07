"""Shared EXIT_TYPE normalization / equivalence helpers.

Canonical core labels (BRT/PVH):
  GAP_DOWN  — open gaps through stop (fill @open)
  GAP_UP    — open gaps through target (fill @open)
  STOP_LOSS — intraday stop touch (fill @stop)
  TARGET    — intraday target touch
  TIME / NO_FT — clock / failure-to-launch

Report aliases only (do not rewrite historical Closed CSVs):
  STOP → STOP_LOSS, GAP_STOP → GAP_DOWN, TIME_STOP → TIME

GAP_DOWN stays distinct from the STOP family for fat-gap analytics.
"""
from __future__ import annotations

from typing import Optional

# String renames for report / gate display (engine emits should prefer canonical).
_EXIT_TYPE_ALIASES = {
    "STOP": "STOP_LOSS",
    "GAP_STOP": "GAP_DOWN",
    "TIME_STOP": "TIME",
}


def normalize_exit_type(exit_type: str | None) -> str:
    """Map legacy aliases to canonical EXIT_TYPE strings (uppercased)."""
    e = (exit_type or "").strip().upper()
    if not e:
        return ""
    return _EXIT_TYPE_ALIASES.get(e, e)


def exit_types_equivalent(
    a: str | None,
    b: str | None,
    *,
    exit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> bool:
    """True when two EXIT_TYPE labels match after alias normalize.

    Also accepts GAP_DOWN ↔ STOP_LOSS when the fill looks like a gap-through-stop
    (exit_price <= stop_price). Used by reconcile gates so re-labeling gaps does
    not fail historical freezes that still say STOP_LOSS.
    """
    na, nb = normalize_exit_type(a), normalize_exit_type(b)
    if not na or not nb:
        return not na and not nb
    if na == nb:
        return True
    pair = {na, nb}
    if pair == {"GAP_DOWN", "STOP_LOSS"}:
        if (
            exit_price is not None
            and stop_price is not None
            and float(exit_price) <= float(stop_price) + 1e-9
        ):
            return True
        # Label-only drift with matching economics already checked elsewhere:
        # treat as equivalent when stop_price unavailable.
        if stop_price is None:
            return True
    return False


def exit_family(exit_type: str | None) -> str:
    """Coarse family for tweak hints. GAP_DOWN/GAP_UP stay their own families
    so fat-gap stats are not folded into STOP.
    """
    e = normalize_exit_type(exit_type)
    if "TARGET" in e and "GAP" not in e:
        return "TARGET"
    if e == "GAP_DOWN" or e.startswith("GAP_DOWN"):
        return "GAP_DOWN"
    if e == "GAP_UP" or e.startswith("GAP_UP"):
        return "GAP_UP"
    if "STOP" in e:
        return "STOP"
    if "TRAIL" in e:
        return "TRAIL"
    if "TIME" in e or "NO_FT" in e:
        return "TIME"
    return e or "OTHER"
