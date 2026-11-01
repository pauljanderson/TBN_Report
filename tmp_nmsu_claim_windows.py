"""Reconstruct 30-60s after each of 4 stuck NMSU/SHSU claims. No secrets. No orders."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import RAW  # noqa: E402

ET = ZoneInfo("America/New_York")

KEYS = [
    "college football\tnmsushsu\t2026-10-21\tspread\tcode:SHSU\t2.5\tgemini\tkalshi",
    "college football\tnmsushsu\t2026-10-21\tspread\tcode:SHSU\t2.5\tkalshi\tnovig",
    "college football\tnmsushsu\t2026-10-21\ttotal\tover\t33.5\tkalshi\tnovig",
    "college football\tnmsushsu\t2026-10-21\tspread\tcode:NMSU\t5.5\tkalshi\tnovig",
]

LABELS = {
    KEYS[0]: "1 SHSU 2.5 Gemini/Kalshi claimed ~20:35:50 ET",
    KEYS[1]: "2 SHSU 2.5 Kalshi/Novig claimed ~20:24:51 ET",
    KEYS[2]: "3 Over 33.5 Kalshi/Novig claimed ~21:01:59 ET",
    KEYS[3]: "4 NMSU 5.5 Kalshi/Novig claimed ~21:25:02 ET",
}

SAFE_ORDER = (
    "event",
    "at",
    "compared_at",
    "ts",
    "sent_at",
    "t",
    "venue",
    "other_venue",
    "side",
    "outcome",
    "http_status",
    "other_http",
    "status",
    "note",
    "other_note",
    "reason",
    "pid",
    "fill_count",
    "fill_qty",
    "filled_qty",
    "game",
    "market_type",
    "number",
    "step",
    "net",
    "trigger_venue",
    "trigger_side",
    "trigger_price",
    "trigger_seen_at",
    "trigger_source",
)

SAFE_IO = (
    "event",
    "at",
    "ts",
    "sent_at",
    "venue",
    "side",
    "outcome",
    "http_status",
    "status",
    "fill_count",
    "fill_qty",
    "filled_qty",
    "note",
    "step",
    "tif",
    "game",
    "bet_key",
)

LOG_KEEP = re.compile(
    r"order skip|book recheck|duplicate|balance|over cap|spawn|restart|killed|"
    r"nmsu|shsu|sam houston|new mexico|novig|max_open|claim|simultaneous|"
    r"send gate|funds|poller|SIG|exit|died|dead|pid |child|start |stop |"
    r"one.leg|both unfilled|placing|orders stopped",
    re.I,
)

SECRETISH = re.compile(r"(token|secret|key|password|authorization|bearer|api[_-]?key)", re.I)


def parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        return dt.astimezone(ET)
    except Exception:
        return None


def row_time(row: dict) -> datetime | None:
    for k in ("at", "compared_at", "ts", "sent_at", "t", "trigger_seen_at"):
        dt = parse_dt(row.get(k))
        if dt is not None:
            return dt
    return None


def safe_row(row: dict, keys) -> dict:
    out = {}
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            s = str(v)
            if SECRETISH.search(k) or SECRETISH.search(s):
                continue
            if len(s) > 240:
                s = s[:240] + "..."
            out[k] = s
    return out


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        print("MISSING", path)
        return rows
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def io_mentions_key(row: dict, key: str) -> bool:
    if str(row.get("bet_key") or "") == key:
        return True
    blob = json.dumps(row, default=str).lower()
    # never dump the blob; just match distinctive fragments
    parts = key.lower().split("\t")
    if "nmsushsu" not in blob:
        return False
    if parts[-1] not in blob or parts[-2] not in blob:
        return False
    if parts[4] not in blob:  # number
        return False
    if parts[3] not in blob:  # side/code
        return False
    return True


def main() -> None:
    print("RAW", RAW)
    print("orders exists", (RAW / "orders.jsonl").exists(), "size", (RAW / "orders.jsonl").stat().st_size if (RAW / "orders.jsonl").exists() else 0)
    print("order_io exists", (RAW / "order_io.jsonl").exists(), "size", (RAW / "order_io.jsonl").stat().st_size if (RAW / "order_io.jsonl").exists() else 0)
    print("supervisor exists", (RAW / "live_supervisor.log").exists(), "size", (RAW / "live_supervisor.log").stat().st_size if (RAW / "live_supervisor.log").exists() else 0)

    orders = load_jsonl(RAW / "orders.jsonl")
    ios = load_jsonl(RAW / "order_io.jsonl") if (RAW / "order_io.jsonl").exists() else []
    print("orders rows", len(orders), "io rows", len(ios))

    by_key: dict[str, list[tuple[int, dict]]] = {k: [] for k in KEYS}
    nmsu_other = []
    for i, row in enumerate(orders):
        key = str(row.get("bet_key") or "")
        if key in by_key:
            by_key[key].append((i, row))
        elif "nmsushsu" in key.lower():
            nmsu_other.append((i, row.get("event"), key, row_time(row), row.get("reason") or row.get("note")))

    print("\n=== ALL NMSU/SHSU OTHER KEYS (event counts only) ===")
    other_keys = {}
    for _, ev, key, _, _ in nmsu_other:
        other_keys.setdefault(key, []).append(ev)
    for key, evs in other_keys.items():
        from collections import Counter
        print(" OTHER", repr(key), dict(Counter(evs)))

    claim_windows = []
    print("\n=== PER-KEY ORDERS TAPE ===")
    for key in KEYS:
        print("\n----", LABELS[key], "----")
        print("KEY", repr(key))
        rows = by_key[key]
        print("n_rows", len(rows))
        claims = []
        for i, row in rows:
            ev = str(row.get("event") or "")
            dt = row_time(row)
            print(" ", i, ev, dt.isoformat() if dt else "NO_TIME", safe_row(row, SAFE_ORDER))
            if ev == "claim":
                claims.append((i, dt, row))
        if not claims:
            print("  NO CLAIM ROWS")
            continue
        last_claim_i, last_claim_dt, last_claim = claims[-1]
        print(" last_claim idx", last_claim_i, "time", last_claim_dt.isoformat() if last_claim_dt else None, "pid", last_claim.get("pid"))
        # next 60s of ANY orders rows after this claim index, plus same-key later rows
        window_end = last_claim_dt + timedelta(seconds=90) if last_claim_dt else None
        print("  --- next ~90s ANY rows after claim index ---")
        n_shown = 0
        for j in range(last_claim_i + 1, min(last_claim_i + 80, len(orders))):
            row = orders[j]
            dt = row_time(row)
            if window_end and dt and dt > window_end:
                break
            ev = str(row.get("event") or "")
            bk = str(row.get("bet_key") or "")
            interesting = ev in {"claim", "skip", "preflight_skip", "both_unfilled", "sent", "filled", "one_leg"} or bk == key
            if not interesting:
                continue
            print(
                "   AFTER",
                j,
                ev,
                dt.isoformat() if dt else "NO_TIME",
                "same_key" if bk == key else "other_key=" + bk[:80],
                safe_row(row, ("reason", "note", "game", "venue", "pid", "http_status")),
            )
            n_shown += 1
        print("  after-window interesting rows", n_shown)
        later_same = [(i, r) for i, r in rows if i > last_claim_i]
        print("  later same-key rows after last claim", len(later_same))
        claim_windows.append((key, last_claim_dt, last_claim.get("pid")))

    print("\n=== ORDER_IO FOR THE 4 KEYS ===")
    nmsu_io = 0
    for row in ios:
        blob_ok = "nmsushsu" in json.dumps({"bet_key": row.get("bet_key"), "game": row.get("game")}, default=str).lower()
        game = str(row.get("game") or "").lower()
        if blob_ok or "nmsu" in game or "sam houston" in game or "shsu" in game:
            nmsu_io += 1
            print(" IO_NMSUISH", safe_row(row, SAFE_IO))
    print("nmsu-ish io rows", nmsu_io)
    for key in KEYS:
        hits = [r for r in ios if io_mentions_key(r, key)]
        print(" IO_FOR_KEY", LABELS[key], "n", len(hits))
        for r in hits:
            print("  ", safe_row(r, SAFE_IO))

    print("\n=== SUPERVISOR WINDOWS ===")
    logp = RAW / "live_supervisor.log"
    if not logp.exists():
        print("NO SUPERVISOR LOG")
        return
    # Parse lines as "ISO msg"
    windows = []
    for key, dt, pid in claim_windows:
        if dt is None:
            continue
        windows.append((key, dt - timedelta(seconds=5), dt + timedelta(seconds=90), pid))

    # also hardcoded claim times in case tape times differ
    hardcoded = [
        datetime(2026, 10, 21, 20, 24, 51, tzinfo=ET),
        datetime(2026, 10, 21, 20, 35, 50, tzinfo=ET),
        datetime(2026, 10, 21, 21, 1, 59, tzinfo=ET),
        datetime(2026, 10, 21, 21, 25, 2, tzinfo=ET),
        datetime(2026, 10, 21, 21, 2, 0, tzinfo=ET),
        datetime(2026, 10, 21, 21, 26, 0, tzinfo=ET),
    ]

    def in_any_window(dt: datetime) -> bool:
        for _, start, end, _ in windows:
            if start <= dt <= end:
                return True
        for t0 in hardcoded:
            if t0 - timedelta(seconds=20) <= dt <= t0 + timedelta(seconds=90):
                return True
        return False

    print("windows from tape claims:")
    for key, start, end, pid in windows:
        print(" ", LABELS[key], start.isoformat(), "->", end.isoformat(), "pid", pid)

    n_kept = 0
    with logp.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            # first token iso
            parts = line.split(" ", 1)
            dt = parse_dt(parts[0]) if parts else None
            keep = False
            if dt and in_any_window(dt) and LOG_KEEP.search(line):
                keep = True
            elif dt and in_any_window(dt) and any(x in line.lower() for x in ("kill", "exit", "spawn", "restart", "poller", "nmsu", "shsu", "novig", "sam houston")):
                keep = True
            if keep:
                # strip possible secrets
                if SECRETISH.search(line):
                    line = line[:80] + " [redacted]"
                print(line[:400])
                n_kept += 1
    print("supervisor matching lines", n_kept)

    print("\n=== SUPERVISOR RESTART/KILL AROUND 21:02 and 21:26 regardless of keywords ===")
    bands = [
        (datetime(2026, 10, 21, 21, 1, 30, tzinfo=ET), datetime(2026, 10, 21, 21, 4, 0, tzinfo=ET)),
        (datetime(2026, 10, 21, 21, 24, 30, tzinfo=ET), datetime(2026, 10, 21, 21, 28, 0, tzinfo=ET)),
        (datetime(2026, 10, 21, 20, 24, 30, tzinfo=ET), datetime(2026, 10, 21, 20, 26, 30, tzinfo=ET)),
        (datetime(2026, 10, 21, 20, 35, 30, tzinfo=ET), datetime(2026, 10, 21, 20, 37, 30, tzinfo=ET)),
    ]
    with logp.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            parts = line.split(" ", 1)
            dt = parse_dt(parts[0]) if parts else None
            if dt is None:
                continue
            if any(a <= dt <= b for a, b in bands):
                low = line.lower()
                if any(w in low for w in ("spawn", "restart", "kill", "died", "exit", "start ", "stop", "pid", "poller", "order skip", "claim", "nmsu", "shsu", "novig", "funds", "balance", "duplicate", "send gate", "over cap", "simultaneous", "book")):
                    if SECRETISH.search(line):
                        line = line[:80] + " [redacted]"
                    print(line[:400])


if __name__ == "__main__":
    main()
