"""Cluster Alves-Zarate T0 asks and Zarate>50 episodes. Read-only."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PATH = RAW / "price_memory" / "2026-10-23" / "tennis.jsonl"
T0 = datetime(2026, 10, 23, 11, 0, tzinfo=ET)
LO = datetime(2026, 10, 23, 10, 50, tzinfo=ET)
HI = datetime(2026, 10, 23, 11, 10, tzinfo=ET)
OUT = RAW / "alves_zarate_ticks_20261023.json"


def parse(text):
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        return dt.astimezone(ET)
    except Exception:
        return None


def dec(value):
    try:
        return Decimal(str(value))
    except Exception:
        return None


def main() -> int:
    t0_near = []
    first_during = None
    first_during_zarate = None
    zarate = []
    alves = []
    n = 0
    with PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if "Zarate" not in line and "Meligeni" not in line:
                continue
            rec = json.loads(line)
            if rec.get("game") != "Meligeni Alves vs Zarate":
                continue
            n += 1
            seen = parse(rec.get("seen_at"))
            if seen is None:
                continue
            pay = str(rec.get("pay") or "").lower()
            if pay != "yes":
                continue
            side = str(rec.get("side") or "")
            venue = str(rec.get("venue") or "")
            px = dec(rec.get("price"))
            phase = rec.get("phase")
            row = {
                "seen": seen.isoformat(timespec="milliseconds"),
                "venue": venue,
                "side": side,
                "price": str(px) if px is not None else "",
                "phase": phase,
            }
            if first_during is None and phase == "during":
                first_during = row
            if "zarate" in side.lower():
                zarate.append((seen, venue, side, px, phase))
                if first_during_zarate is None and phase == "during":
                    first_during_zarate = row
            elif "alves" in side.lower() or "meligeni" in side.lower():
                alves.append((seen, venue, side, px, phase))
            if LO <= seen <= HI:
                t0_near.append(row)

    last_before = {}
    for seen, venue, side, px, phase in alves + zarate:
        key = f"{venue}|{side}"
        if seen <= T0:
            prev = last_before.get(key)
            if prev is None or seen >= parse(prev["seen"]):
                last_before[key] = {
                    "seen": seen.isoformat(timespec="milliseconds"),
                    "venue": venue,
                    "side": side,
                    "price": str(px) if px is not None else "",
                    "phase": phase,
                }

    episodes = {}
    for venue in sorted({row[1] for row in zarate}):
        ticks = [(s, p, ph) for s, v, _side, p, ph in zarate if v == venue]
        ticks.sort()
        out = []
        cur = None
        last_px = None
        for seen, px, phase in ticks:
            if px is None:
                continue
            over = px > Decimal("0.50")
            if over:
                if cur is None:
                    cur = {
                        "start": seen.isoformat(timespec="milliseconds"),
                        "end": seen.isoformat(timespec="milliseconds"),
                        "peak": str(px),
                        "peak_at": seen.isoformat(timespec="milliseconds"),
                        "n": 1,
                        "from_below": last_px is None or last_px <= Decimal("0.50"),
                        "prev": str(last_px) if last_px is not None else "",
                        "phase0": phase,
                        "min_over": str(px),
                    }
                else:
                    cur["end"] = seen.isoformat(timespec="milliseconds")
                    cur["n"] += 1
                    if px > Decimal(cur["peak"]):
                        cur["peak"] = str(px)
                        cur["peak_at"] = seen.isoformat(timespec="milliseconds")
                    if px < Decimal(cur["min_over"]):
                        cur["min_over"] = str(px)
            elif cur is not None:
                start = parse(cur["start"])
                end = parse(cur["end"])
                cur["dur_sec"] = round((end - start).total_seconds(), 3)
                out.append(cur)
                cur = None
            last_px = px
        if cur is not None:
            start = parse(cur["start"])
            end = parse(cur["end"])
            cur["dur_sec"] = round((end - start).total_seconds(), 3)
            out.append(cur)
        episodes[venue] = out

    payload = {
        "yes_change_ticks": n,
        "zarate_yes_n": len(zarate),
        "alves_yes_n": len(alves),
        "first_during": first_during,
        "first_during_zarate": first_during_zarate,
        "t0_window_ticks": t0_near,
        "last_yes_at_or_before_t0": last_before,
        "episodes_over_50": episodes,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
    print("first_during", first_during)
    print("t0 last <=11:00")
    for key, row in sorted(last_before.items()):
        print(" ", key, row["seen"][11:19], row["price"], row["phase"])
    print("t0 window ticks", len(t0_near))
    for venue, rows in episodes.items():
        print(venue, "episodes", len(rows))
        for i, row in enumerate(rows, 1):
            print(
                f"  {i} {row['start'][11:19]}->{row['end'][11:19]} "
                f"dur={row['dur_sec']}s n={row['n']} peak={row['peak']} "
                f"from_below={row['from_below']} prev={row['prev']} {row['phase0']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
