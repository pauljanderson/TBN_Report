"""Trigger zone must stay on-screen even when a newer 126d winner exists."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from vol_zone_break_retest import Zone  # noqa: E402
from vz_chart_zones import (  # noqa: E402
    VzTriggerSpec,
    find_zone_by_id,
    parse_zone_id,
    reconstruct_zone,
    resolve_trigger_zone,
    resolve_vz_chart_pack,
    visible_window_start,
    zones_same,
)


def _zone(zone_id: str, idx: int, day: str, lo: float, hi: float, last_winner: int) -> Zone:
    ts = pd.Timestamp(day)
    return Zone(
        zone_id=zone_id,
        kind="HL",
        max_vol_idx=idx,
        max_vol_date=ts,
        volume=1000,
        lo=lo,
        hi=hi,
        created_on_idx=idx,
        created_on=ts,
        last_winner_idx=last_winner,
        last_winner_date=ts,
    )


def test_parse_zone_id() -> None:
    assert parse_zone_id("HL_2025-03-15") == ("HL", date(2025, 3, 15))
    assert parse_zone_id("OC_2024-12-01") == ("OC", date(2024, 12, 1))
    assert parse_zone_id("") is None
    assert parse_zone_id("BRT_ZONE") is None


def test_find_older_trigger_not_latest() -> None:
    older = _zone("HL_2025-03-15", 10, "2025-03-15", 10.0, 12.0, last_winner=40)
    newer = _zone("HL_2026-08-01", 80, "2026-08-01", 20.0, 24.0, last_winner=100)
    hit = find_zone_by_id([older, newer], "HL_2025-03-15")
    assert hit is older
    assert not zones_same(older, newer)


def test_visible_window_extends_left_for_old_trigger() -> None:
    end = pd.Timestamp("2026-09-18")
    trigger = _zone("HL_2025-12-01", 1, "2025-12-01", 5.0, 6.0, last_winner=20)
    start = visible_window_start(end, months=6, trigger=trigger, pad_days=7)
    assert start <= pd.Timestamp("2025-11-24")
    default = visible_window_start(end, months=6, trigger=None)
    assert default > start


def test_reconstruct_zone_from_ohlc() -> None:
    dates = pd.date_range("2025-03-10", periods=10, freq="B")
    close = np.linspace(10.0, 11.0, len(dates))
    df = pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 1.0,
            "Low": close - 0.5,
            "Close": close,
            "Volume": np.full(len(dates), 1000.0),
        }
    )
    spec = VzTriggerSpec(symbol="TEST", zone_id="HL_2025-03-17", kind="HL")
    z = reconstruct_zone(df, spec)
    assert z is not None
    assert z.zone_id == "HL_2025-03-17"
    row = df.loc[pd.to_datetime(df["Date"]).dt.normalize() == pd.Timestamp("2025-03-17")].iloc[0]
    assert abs(z.lo - float(row["Low"])) < 1e-9
    assert abs(z.hi - float(row["High"])) < 1e-9


def test_resolve_trigger_prefers_spec_over_current() -> None:
    dates = pd.bdate_range("2024-01-02", periods=200)
    vol = np.full(len(dates), 100.0)
    vol[20] = 5000.0  # older max-vol day
    vol[180] = 9000.0  # newer max-vol day
    close = np.linspace(10.0, 20.0, len(dates))
    df = pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 0.4,
            "Low": close - 0.4,
            "Close": close,
            "Volume": vol,
        }
    )
    older_day = pd.Timestamp(dates[20]).date().isoformat()
    newer_day = pd.Timestamp(dates[180]).date().isoformat()
    spec = VzTriggerSpec(symbol="TEST", zone_id=f"HL_{older_day}", kind="HL")
    pack = resolve_vz_chart_pack(df, lookback=126, trigger_spec=spec)
    assert pack.trigger_hl is not None
    assert pack.current_hl is not None
    assert pd.Timestamp(pack.trigger_hl.max_vol_date).date().isoformat() == older_day
    assert pd.Timestamp(pack.current_hl.max_vol_date).date().isoformat() == newer_day
    assert pack.trigger_is_current is False
    hl, _oc = resolve_trigger_zone(df, pack.all_zones, spec)
    assert hl is not None
    assert hl.zone_id == f"HL_{older_day}"


if __name__ == "__main__":
    test_parse_zone_id()
    test_find_older_trigger_not_latest()
    test_visible_window_extends_left_for_old_trigger()
    test_reconstruct_zone_from_ohlc()
    test_resolve_trigger_prefers_spec_over_current()
    print("ok")
