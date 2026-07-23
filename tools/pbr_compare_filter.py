"""Backward-compat shim for tools.pbr_compare_filter → wpbr_compare_filter."""
from __future__ import annotations

from wpbr_compare_filter import *  # noqa: F403
from wpbr_compare_filter import SHEET_COMPARE_MIN_DATE, filter_wpbr_output_for_compare  # noqa: F401

filter_pbr_output_for_compare = filter_wpbr_output_for_compare
