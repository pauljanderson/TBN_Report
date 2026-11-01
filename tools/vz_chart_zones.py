"""Shared Volume Zone (VZ) chart overlays — always include the trigger box.

House VZ signals use a specific High–Low (HL) zone (``ZONE_ID`` like
``HL_2025-03-15``). That zone can be older than the current 126-bar rolling
max-volume winner. DailyRun / trendline / ToS charts used to draw only the
latest winner, so the box that actually triggered the trade/watchlist row
disappeared.

Display-only. Does not change ``rocket_vz`` entry logic, gold, or DailyRun
wiring. The chart must match the engine's ``ZONE_ID`` when a live Open /
Watchlist row exists.

Usage:
    from vz_chart_zones import (
        LOOKBACK_DAYS,
        load_vz_trigger_specs,
        resolve_vz_chart_pack,
        visible_window_start,
    )
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"

from vol_zone_break_retest import Zone, build_zones  # noqa: E402

LOOKBACK_DAYS = 126
CHART_MONTHS = 6
TRIGGER_PAD_DAYS = 7
_HL_ZONE_ID_RE = re.compile(r"^(HL|OC)_(\d{4}-\d{2}-\d{2})$", re.I)


@dataclass(frozen=True)
class VzTriggerSpec:
    """Engine row that names the High–Low box a VZ signal is based on."""

    symbol: str
    zone_id: str
    kind: str = "HL"
    lo: float | None = None
    hi: float | None = None
    source: str = ""  # watchlist | open
    signal_date: str = ""
    break_date: str = ""


@dataclass
class VzChartPack:
    """Zones to draw on a symbol chart.

    ``trigger_hl`` is the box the scanner/engine is using (Open / Watchlist
    ``ZONE_ID``). ``current_hl`` is the latest rolling 126d winner. They may
    be the same object. Always draw the trigger when present; current is
    optional context when it is a newer unused box.
    """

    all_zones: list[Zone] = field(default_factory=list)
    current_hl: Zone | None = None
    current_oc: Zone | None = None
    trigger_hl: Zone | None = None
    trigger_oc: Zone | None = None
    trigger_spec: VzTriggerSpec | None = None
    trigger_is_current: bool = False
    nearest_above: Zone | None = None
    nearest_below: Zone | None = None

    def as_legacy_current(self) -> dict[str, Zone | None]:
        """Back-compat ``{\"HL\": ..., \"OC\": ...}`` — trigger preferred."""
        hl = self.trigger_hl or self.current_hl
        oc = self.trigger_oc or self.current_oc
        return {"HL": hl, "OC": oc}


def parse_zone_id(zone_id: Any) -> tuple[str, date] | None:
    """``HL_2025-03-15`` / ``OC_2025-03-15`` → (kind, date)."""
    s = str(zone_id or "").strip()
    m = _HL_ZONE_ID_RE.match(s)
    if not m:
        return None
    kind = m.group(1).upper()
    return kind, date.fromisoformat(m.group(2))


def zones_same(a: Zone | None, b: Zone | None) -> bool:
    if a is None or b is None:
        return False
    if a.zone_id and b.zone_id and a.zone_id == b.zone_id:
        return True
    try:
        return (
            str(a.kind).upper() == str(b.kind).upper()
            and pd.Timestamp(a.max_vol_date).date() == pd.Timestamp(b.max_vol_date).date()
        )
    except Exception:
        return False


def nearest_hl_zones(zones: Iterable[Zone], price: float) -> tuple[Zone | None, Zone | None]:
    """Nearest mature VZ HL zone above/below *price*."""
    hl = [z for z in zones if z.kind == "HL"]
    above = [z for z in hl if z.lo > price]
    below = [z for z in hl if z.hi < price]
    nearest_above = min(above, key=lambda z: z.lo - price) if above else None
    nearest_below = max(below, key=lambda z: z.hi) if below else None
    return nearest_above, nearest_below


def current_vz_zones(df: pd.DataFrame, lookback: int = LOOKBACK_DAYS) -> dict[str, Zone | None]:
    """Latest rolling-winner HL (and matching OC). Not the trigger unless they match."""
    out: dict[str, Zone | None] = {"HL": None, "OC": None}
    if df is None or len(df) <= lookback:
        return out
    zones = build_zones(df, lookback)
    last_i = len(df) - 1
    active = [z for z in zones if z.last_winner_idx == last_i]
    if not active:
        by_kind: dict[str, list[Zone]] = {"HL": [], "OC": []}
        for z in zones:
            by_kind.setdefault(z.kind, []).append(z)
        for k in ("HL", "OC"):
            if by_kind[k]:
                out[k] = by_kind[k][-1]
        return out
    for z in active:
        out[z.kind] = z
    return out


def find_zone_by_id(zones: Iterable[Zone], zone_id: str) -> Zone | None:
    parsed = parse_zone_id(zone_id)
    want = str(zone_id or "").strip()
    if not want:
        return None
    for z in zones:
        if str(z.zone_id) == want:
            return z
    if parsed is None:
        return None
    kind, day = parsed
    for z in zones:
        if str(z.kind).upper() != kind:
            continue
        try:
            if pd.Timestamp(z.max_vol_date).date() == day:
                return z
        except Exception:
            continue
    return None


def reconstruct_zone(
    df: pd.DataFrame,
    spec: VzTriggerSpec,
) -> Zone | None:
    """Build a Zone from OHLC at ``ZONE_ID`` date when ``build_zones`` missed it."""
    parsed = parse_zone_id(spec.zone_id)
    if parsed is None or df is None or df.empty or "Date" not in df.columns:
        return None
    kind, day = parsed
    dates = pd.to_datetime(df["Date"]).dt.normalize()
    hits = df.loc[dates == pd.Timestamp(day)]
    if hits.empty:
        return None
    row = hits.iloc[-1]
    idx = int(hits.index[-1])
    lo = spec.lo
    hi = spec.hi
    if lo is None or hi is None or (hi < lo):
        if kind == "OC":
            lo = float(min(row["Open"], row["Close"]))
            hi = float(max(row["Open"], row["Close"]))
        else:
            lo = float(row["Low"])
            hi = float(row["High"])
    vol = row["Volume"] if "Volume" in row.index else 0
    try:
        vol_i = int(float(vol or 0))
    except (TypeError, ValueError):
        vol_i = 0
    ts = pd.Timestamp(day)
    return Zone(
        zone_id=spec.zone_id if spec.zone_id else f"{kind}_{day.isoformat()}",
        kind=kind,  # type: ignore[arg-type]
        max_vol_idx=idx,
        max_vol_date=ts,
        volume=vol_i,
        lo=float(lo),
        hi=float(hi),
        created_on_idx=idx,
        created_on=ts,
        last_winner_idx=idx,
        last_winner_date=ts,
    )


def resolve_trigger_zone(
    df: pd.DataFrame,
    zones: list[Zone],
    spec: VzTriggerSpec | None,
) -> tuple[Zone | None, Zone | None]:
    """Return (HL, OC) for the engine trigger. Reconstruct HL if needed."""
    if spec is None:
        return None, None
    parsed = parse_zone_id(spec.zone_id)
    kind = (spec.kind or (parsed[0] if parsed else "HL")).upper()
    found = find_zone_by_id(zones, spec.zone_id) if spec.zone_id else None
    if found is None:
        found = reconstruct_zone(df, spec)
    if found is None:
        return None, None
    hl = found if str(found.kind).upper() == "HL" else None
    oc = found if str(found.kind).upper() == "OC" else None
    if parsed is not None:
        other_kind = "OC" if kind == "HL" else "HL"
        other_id = f"{other_kind}_{parsed[1].isoformat()}"
        other = find_zone_by_id(zones, other_id)
        if other is None:
            other_spec = VzTriggerSpec(
                symbol=spec.symbol,
                zone_id=other_id,
                kind=other_kind,
                source=spec.source,
            )
            other = reconstruct_zone(df, other_spec)
        if other is not None:
            if str(other.kind).upper() == "HL":
                hl = hl or other
            else:
                oc = oc or other
    if hl is None and found is not None:
        hl = found
    return hl, oc


def visible_window_start(
    end_ts: pd.Timestamp,
    *,
    months: int = CHART_MONTHS,
    trigger: Zone | None = None,
    pad_days: int = TRIGGER_PAD_DAYS,
) -> pd.Timestamp:
    """Default last-N-months start, extended left so the trigger write day is on-screen."""
    end = pd.Timestamp(end_ts).normalize()
    start = (end - pd.DateOffset(months=int(months))).normalize()
    if trigger is None:
        return start
    try:
        z_day = pd.Timestamp(trigger.max_vol_date).normalize()
    except Exception:
        return start
    need = z_day - pd.Timedelta(days=int(pad_days))
    if need < start:
        return need
    return start


def _fnum(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(",", "")
    if not s or s in ("—", "-", "nan", "None"):
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def _row_spec(row: dict[str, Any], *, source: str) -> VzTriggerSpec | None:
    cols = {str(k).strip().upper(): k for k in row.keys()}

    def _get(*names: str) -> Any:
        for n in names:
            k = cols.get(n)
            if k is not None:
                return row.get(k)
        return None

    sym = str(_get("SYMBOL") or "").strip().upper()
    zid = str(_get("ZONE_ID", "ZONE ID") or "").strip()
    if not sym or not parse_zone_id(zid):
        return None
    parsed = parse_zone_id(zid)
    kind = str(_get("ZONE_KIND", "ZONE KIND") or "").strip().upper()
    if not kind and parsed:
        kind = parsed[0]
    return VzTriggerSpec(
        symbol=sym,
        zone_id=zid,
        kind=kind or "HL",
        lo=_fnum(_get("ZONE_LO", "ZONE LO", "ZONE_LOW", "ZONE LOW")),
        hi=_fnum(_get("ZONE_HI", "ZONE HI", "ZONE_HIGH", "ZONE HIGH", "ZONE_UPPER")),
        source=source,
        signal_date=str(_get("SIGNAL_DATE", "ASOF_DATE", "DATE_OPENED", "DATE OPENED") or ""),
        break_date=str(_get("BREAK_DATE", "BREAKOUT_DATE") or ""),
    )


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        df = pd.read_csv(path)
    except Exception:
        return []
    if df.empty:
        return []
    return [row.to_dict() for _, row in df.iterrows()]


def _open_csv_candidates(drive: Path, run_ts: str | None) -> list[Path]:
    out: list[Path] = []
    if run_ts:
        out.append(drive / f"VZ_Open_{run_ts}.csv")
    out.append(drive / "VZ_LatestRun_Open.csv")
    return out


def load_vz_trigger_specs(drive: Path | None = None) -> dict[str, VzTriggerSpec]:
    """Map SYMBOL → engine trigger (Watchlist first, then Open).

    VZ Watchlist is written from live Open lots and always carries ``ZONE_ID``.
    TBN Open CSV may omit ``ZONE_ID``; we still try it. House-pinned stamp via
    ``trendlines_opens_universe.vz_core_run_timestamp``.
    """
    drive = drive or (_REPO / "drive")
    specs: dict[str, VzTriggerSpec] = {}
    run_ts: str | None = None
    try:
        from trendlines_opens_universe import resolve_watchlist_csv, vz_core_run_timestamp

        run_ts = vz_core_run_timestamp(drive)
        watch_path, _ = resolve_watchlist_csv("VZ", drive)
    except Exception:
        watch_path = None
        if (drive / "VZ_LatestRun_Watchlist.csv").is_file():
            watch_path = drive / "VZ_LatestRun_Watchlist.csv"

    if watch_path is not None:
        for row in _read_csv_rows(watch_path):
            spec = _row_spec(row, source="watchlist")
            if spec is not None:
                specs[spec.symbol] = spec

    for path in _open_csv_candidates(drive, run_ts):
        if not path.is_file():
            continue
        for row in _read_csv_rows(path):
            spec = _row_spec(row, source="open")
            if spec is None:
                continue
            # Open wins when both exist (same ZONE_ID usually); keep first Open.
            prev = specs.get(spec.symbol)
            if prev is None or prev.source == "watchlist":
                specs[spec.symbol] = spec
        break
    return specs


def resolve_vz_chart_pack(
    df: pd.DataFrame,
    *,
    lookback: int = LOOKBACK_DAYS,
    trigger_spec: VzTriggerSpec | None = None,
    last_close: float | None = None,
) -> VzChartPack:
    """Current winner + engine trigger + nearest HL guides."""
    pack = VzChartPack()
    if df is None or df.empty or len(df) <= lookback:
        return pack
    try:
        zones = build_zones(df, lookback)
    except ValueError:
        return pack
    pack.all_zones = zones
    cur = current_vz_zones(df, lookback)
    pack.current_hl = cur.get("HL")
    pack.current_oc = cur.get("OC")
    trig_hl, trig_oc = resolve_trigger_zone(df, zones, trigger_spec)
    pack.trigger_spec = trigger_spec
    pack.trigger_hl = trig_hl
    pack.trigger_oc = trig_oc
    pack.trigger_is_current = zones_same(trig_hl, pack.current_hl) if trig_hl else False
    # General symbol chart with no live VZ row: the "trigger" is the current
    # winner the scanner would write next — already in current_hl.
    px = last_close
    if px is None and "Close" in df.columns and len(df):
        try:
            px = float(df["Close"].iloc[-1])
        except (TypeError, ValueError):
            px = None
    if px is not None:
        pack.nearest_above, pack.nearest_below = nearest_hl_zones(zones, float(px))
    return pack


def trigger_label(z: Zone | None, *, is_current: bool = False) -> str:
    if z is None:
        return "—"
    day = pd.Timestamp(z.max_vol_date).date()
    tag = "trigger (current winner)" if is_current else "trigger"
    return f"{tag} {day} {z.lo:.2f}–{z.hi:.2f}"


def latest_unused_label(z: Zone | None) -> str:
    if z is None:
        return "—"
    day = pd.Timestamp(z.max_vol_date).date()
    return f"latest unused {day} {z.lo:.2f}–{z.hi:.2f}"
