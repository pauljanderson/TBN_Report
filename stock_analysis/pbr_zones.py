"""Backward-compat shim: old ``pbr_zones`` module name → ``wpbr_zones``."""
from __future__ import annotations

try:
    from wpbr_zones import *  # noqa: F403
    from wpbr_zones import (  # noqa: F401
        WPBR_STRENGTH_FIELDS,
        compute_wpbr_touch_stream,
        find_wpbr_retest_and_signal,
        make_wpbr_zone_id,
        wpbr_strength_from_event,
    )
except ImportError:
    from stock_analysis.wpbr_zones import *  # noqa: F403
    from stock_analysis.wpbr_zones import (  # noqa: F401
        WPBR_STRENGTH_FIELDS,
        compute_wpbr_touch_stream,
        find_wpbr_retest_and_signal,
        make_wpbr_zone_id,
        wpbr_strength_from_event,
    )

# Legacy aliases (pre-WPBR rename)
PBR_STRENGTH_FIELDS = WPBR_STRENGTH_FIELDS
compute_pbr_touch_stream = compute_wpbr_touch_stream
find_pbr_retest_and_signal = find_wpbr_retest_and_signal
make_pbr_zone_id = make_wpbr_zone_id
pbr_strength_from_event = wpbr_strength_from_event
