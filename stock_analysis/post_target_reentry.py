"""Post-TARGET re-entry window helpers shared by RL, RS/IND scan, and zone (YH/BRT/WPBR) paths.

Config fields (on BRTConfig / RLConfig):
  rl_post_target_reentry_bars / mode / stop_pct / min_stack / under_sma20

Modes are mutually exclusive when bars > 0 and the prior exit was TARGET:
  stop_loss      — allow; optional tighter stop via rl_post_target_stop_pct
  min_stack      — block unless (SMA20/SMA50 − 1) ≥ min_stack
  under_sma_limit — block if close < SMA20 × (1 − under_sma20)
  none           — block all re-entries in the window
"""
from __future__ import annotations

from typing import Any

import numpy as np

POST_TARGET_MODES = frozenset({"stop_loss", "min_stack", "under_sma_limit", "none"})

def post_target_reentry_mode(cfg: Any) -> str:
    """Normalized post-TARGET re-entry mode (default stop_loss)."""
    raw = str(getattr(cfg, "rl_post_target_reentry_mode", "stop_loss") or "stop_loss").strip().lower()
    if raw in ("", "off"):
        return "stop_loss"
    if raw in POST_TARGET_MODES:
        return raw
    return "stop_loss"


def in_post_target_window(
    cfg: Any,
    *,
    last_exit_idx: int,
    last_exit_was_target: bool,
    entry_idx: int,
) -> bool:
    """True when bars>0 and prior TARGET exit is within reentry_bars of fill index."""
    bars = int(getattr(cfg, "rl_post_target_reentry_bars", 0) or 0)
    return (
        bars > 0
        and last_exit_was_target
        and last_exit_idx >= 0
        and (entry_idx - last_exit_idx) <= bars
    )


def post_target_blocks_entry(
    cfg: Any,
    *,
    last_exit_idx: int,
    last_exit_was_target: bool,
    entry_idx: int,
    close: float,
    sma20: float,
    sma50: float,
) -> bool:
    """True when post-TARGET policy should block this re-entry.

    Quality checks (min_stack / under_sma_limit) use trigger/signal bar close & SMAs.
    Modes are mutually exclusive; ``stop_loss`` never blocks here.
    """
    if not in_post_target_window(
        cfg,
        last_exit_idx=last_exit_idx,
        last_exit_was_target=last_exit_was_target,
        entry_idx=entry_idx,
    ):
        return False
    mode = post_target_reentry_mode(cfg)
    if mode == "stop_loss":
        return False
    if mode == "none":
        return True
    if mode == "min_stack":
        min_stack = float(getattr(cfg, "rl_post_target_min_stack", 0.05) or 0.0)
        if not (np.isfinite(sma20) and np.isfinite(sma50) and sma50 > 0):
            return True
        return (float(sma20) / float(sma50) - 1.0) < min_stack
    if mode == "under_sma_limit":
        limit = float(getattr(cfg, "rl_post_target_under_sma20", 0.03) or 0.0)
        if not (np.isfinite(sma20) and np.isfinite(close) and sma20 > 0):
            return True
        # Reject if close is deeper under SMA20 than limit:
        # close < SMA20 × (1 − limit) ⇔ (SMA20 − close) / SMA20 > limit
        return float(close) < float(sma20) * (1.0 - limit)
    return False


def post_target_effective_stop_pct(
    cfg: Any,
    *,
    baseline_stop_pct: float,
    last_exit_idx: int,
    last_exit_was_target: bool,
    entry_idx: int,
) -> float:
    """Stop multiplier for entry; may tighten after a TARGET within the window.

    When ``rl_post_target_reentry_bars`` > 0, mode is ``stop_loss``, and
    ``rl_post_target_stop_pct`` > 0, use the post-TARGET stop. Otherwise return
    ``baseline_stop_pct`` (RL: ``rl_stop_pct``; RS: ``stop_pct``).
    """
    post_pct = float(getattr(cfg, "rl_post_target_stop_pct", 0.0) or 0.0)
    if (
        post_pct > 0
        and post_target_reentry_mode(cfg) == "stop_loss"
        and in_post_target_window(
            cfg,
            last_exit_idx=last_exit_idx,
            last_exit_was_target=last_exit_was_target,
            entry_idx=entry_idx,
        )
    ):
        return post_pct
    return float(baseline_stop_pct)


def exit_type_is_target(exit_type: Any) -> bool:
    """True when EXIT_TYPE is a TARGET-family win (matches ImproveHints / PTQS spirit)."""
    et = str(exit_type or "").strip().upper()
    return "TARGET" in et
