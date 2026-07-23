"""Backward-compat shim for tools.pbr_sheet_ground_truth → wpbr_sheet_ground_truth."""
from __future__ import annotations

from wpbr_sheet_ground_truth import *  # noqa: F403
from wpbr_sheet_ground_truth import (  # noqa: F401
    load_wpbr_ground_truth,
    parse_wpbr_paste,
)

load_pbr_ground_truth = load_wpbr_ground_truth
parse_pbr_paste = parse_wpbr_paste
