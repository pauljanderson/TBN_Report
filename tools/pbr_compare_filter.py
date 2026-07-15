"""Filter PBR engine output for spreadsheet parity (not applied in live engine)."""
from __future__ import annotations

from typing import Any

import pandas as pd

# Spreadsheet backtests start 2016-01-01; pre-2016 engine zones are ignored in compare only.
SHEET_COMPARE_MIN_DATE = "2016-01-01"


def _on_or_after(ts: pd.Timestamp, cutoff: pd.Timestamp) -> bool:
    return pd.Timestamp(ts).normalize() >= cutoff


def filter_pbr_output_for_compare(
    out: dict[str, Any],
    df: pd.DataFrame,
    *,
    min_date: str = SHEET_COMPARE_MIN_DATE,
) -> dict[str, Any]:
    """Drop zones and entry bars before ``min_date`` (spreadsheet window)."""
    cutoff = pd.Timestamp(min_date).normalize()
    filtered = dict(out)

    events: list[dict] = []
    for ev in out.get("pbr_zone_events") or []:
        pm = ev.get("pivot_monday") or ""
        if pm and not _on_or_after(pm, cutoff):
            continue
        events.append(ev)
    filtered["pbr_zone_events"] = events

    if "pbr_audit" in out:
        filtered["pbr_audit"] = [
            ev for ev in out.get("pbr_audit") or []
            if (ev.get("pivot_monday") or "") and _on_or_after(ev["pivot_monday"], cutoff)
        ]

    signals = [
        int(b)
        for b in out.get("pbr_entry_signal_bars") or out.get("pbr_entry_bars") or []
        if 0 <= int(b) < len(df) and _on_or_after(df.index[int(b)], cutoff)
    ]
    fills = [
        int(b)
        for b in out.get("pbr_entry_fill_bars") or []
        if 0 <= int(b) < len(df) and _on_or_after(df.index[int(b)], cutoff)
    ]
    filtered["pbr_entry_signal_bars"] = signals
    filtered["pbr_entry_fill_bars"] = fills
    filtered["pbr_entry_bars"] = signals
    return filtered
