#!/usr/bin/env python3
"""Ingest multi-symbol sheet paste (BRT + zones) into per-symbol ledger files."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
SYMBOLS = {"AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "NFLX"}
BRT_HDR = "Breakout Date\tZone Lower\tZone Upper"
ZONE_HDR = "Matured touch price"


def _strip_user_query(text: str) -> str:
    t = text.strip()
    if t.startswith("<user_query>"):
        t = t[len("<user_query>") :].strip()
    if t.endswith("</user_query>"):
        t = t[: -len("</user_query>")].strip()
    return t


def _is_brt_row(line: str) -> bool:
    parts = line.split("\t")
    if len(parts) < 6:
        return False
    return bool(re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", parts[0].strip()))


def _parse_price(s: str) -> float | None:
    t = re.sub(r"[^0-9.\-]", "", (s or "").strip())
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _is_zone_row(line: str) -> tuple[float, float, float] | None:
    parts = [p.strip() for p in line.split("\t") if p.strip()]
    if len(parts) != 3:
        return None
    vals = [_parse_price(p) for p in parts]
    if any(v is None for v in vals):
        return None
    return float(vals[0]), float(vals[1]), float(vals[2])  # type: ignore[arg-type]


def parse_multisymbol_paste(text: str) -> dict[str, dict[str, list]]:
    text = _strip_user_query(text)
    out: dict[str, dict[str, list]] = {}
    sym: str | None = None
    mode: str | None = None  # brt | zones
    brt_hdr: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in SYMBOLS:
            sym = stripped
            mode = None
            brt_hdr = None
            out.setdefault(sym, {"brt_lines": [], "zone_rows": []})
            continue
        if sym is None:
            continue
        if stripped.startswith(BRT_HDR) or stripped.replace(" ", "").startswith("BreakoutDate"):
            mode = "brt"
            # Normalize header: drop leading empty tab columns from sheet paste
            parts = line.split("\t")
            while parts and not parts[0].strip():
                parts = parts[1:]
            if parts and parts[0].strip() == "Breakout Date":
                brt_hdr = "Breakout Date\t" + "\t".join(parts[1:])
            else:
                brt_hdr = line
            out[sym]["brt_lines"] = [brt_hdr]
            continue
        if stripped.startswith(ZONE_HDR) or stripped.lower() == "zones":
            if stripped.startswith(ZONE_HDR):
                mode = "zones"
            continue
        if "all zones will be from" in stripped.lower():
            mode = "zones"
            continue
        if mode == "brt" and _is_brt_row(line):
            out[sym]["brt_lines"].append(line)
            continue
        if mode == "zones":
            z = _is_zone_row(line)
            if z is not None:
                out[sym]["zone_rows"].append(z)
    return out


def write_ledgers(parsed: dict[str, dict[str, list]], *, brt_tab: bool = False) -> None:
    brt_map: dict[str, Path] = {}
    zone_map: dict[str, Path] = {}
    brt_suffix = "_brt" if brt_tab else ""
    for sym, data in parsed.items():
        sym_l = sym.lower()
        brt_path = TOOLS / f"{sym_l}{brt_suffix}_sheet_breakout_retest.tsv"
        zone_path = TOOLS / f"{sym_l}{brt_suffix}_sheet_zones.txt"
        brt_lines: list[str] = data.get("brt_lines") or []
        zone_rows: list[tuple[float, float, float]] = data.get("zone_rows") or []
        if len(brt_lines) > 1:
            brt_path.write_text("\n".join(brt_lines) + "\n", encoding="utf-8")
            brt_map[sym] = brt_path
            print(f"{sym}: {len(brt_lines)-1} breakout rows -> {brt_path.name}")
        else:
            print(f"{sym}: no breakout rows")
        if zone_rows:
            zone_path.write_text(
                "\n".join(f"{c}\t{lo}\t{hi}" for c, lo, hi in zone_rows) + "\n",
                encoding="utf-8",
            )
            zone_map[sym] = zone_path
            print(f"{sym}: {len(zone_rows)} zones -> {zone_path.name}")
        else:
            print(f"{sym}: no zone rows")

    if brt_tab:
        _update_brt_breakout_registry(brt_map)
        _update_brt_zone_registry(zone_map)
    else:
        _update_breakout_registry(brt_map)
        _update_zone_registry(zone_map)


def _update_brt_breakout_registry(mapping: dict[str, Path]) -> None:
    path = TOOLS / "brt_sheet_breakout_ledgers.py"
    entries = []
    for sym in sorted(mapping):
        fname = mapping[sym].name
        entries.append(f'    "{sym}": TOOLS / "{fname}",')
    block = "BRT_SHEET_BREAKOUT_LEDGER: dict[str, Path] = {\n" + "\n".join(entries) + "\n}"
    src = path.read_text(encoding="utf-8")
    start = src.index("BRT_SHEET_BREAKOUT_LEDGER:")
    end = src.index("\n}", start) + 2
    path.write_text(src[:start] + block + src[end:], encoding="utf-8")
    print(f"Updated {path.name} ({len(mapping)} symbols)")


def _update_brt_zone_registry(mapping: dict[str, Path]) -> None:
    path = TOOLS / "brt_sheet_zone_ledgers.py"
    entries = []
    for sym in sorted(mapping):
        fname = mapping[sym].name
        entries.append(f'    "{sym}": TOOLS / "{fname}",')
    block = "BRT_SHEET_ZONE_LEDGER: dict[str, Path] = {\n" + "\n".join(entries) + "\n}"
    src = path.read_text(encoding="utf-8")
    start = src.index("BRT_SHEET_ZONE_LEDGER:")
    end = src.index("\n}", start) + 2
    path.write_text(src[:start] + block + src[end:], encoding="utf-8")
    print(f"Updated {path.name} ({len(mapping)} symbols)")


def _update_breakout_registry(mapping: dict[str, Path]) -> None:
    path = TOOLS / "sheet_breakout_ledgers.py"
    entries = []
    for sym in sorted(mapping):
        fname = mapping[sym].name
        entries.append(f'    "{sym}": TOOLS / "{fname}",')
    block = "SHEET_BREAKOUT_LEDGER: dict[str, Path] = {\n" + "\n".join(entries) + "\n}"
    src = path.read_text(encoding="utf-8")
    start = src.index("SHEET_BREAKOUT_LEDGER:")
    end = src.index("\n}", start) + 2
    path.write_text(src[:start] + block + src[end:], encoding="utf-8")
    print(f"Updated {path.name} ({len(mapping)} symbols)")


def _update_zone_registry(mapping: dict[str, Path]) -> None:
    path = TOOLS / "sheet_zone_ledgers.py"
    entries = []
    for sym in sorted(mapping):
        fname = mapping[sym].name
        entries.append(f'    "{sym}": TOOLS / "{fname}",')
    block = "SHEET_ZONE_LEDGER: dict[str, Path] = {\n" + "\n".join(entries) + "\n}"
    src = path.read_text(encoding="utf-8")
    start = src.index("SHEET_ZONE_LEDGER:")
    end = src.index("\n}", start) + 2
    path.write_text(src[:start] + block + src[end:], encoding="utf-8")
    print(f"Updated {path.name} ({len(mapping)} symbols)")


def _load_from_transcript() -> str | None:
    candidates = [
        Path(r"C:\Users\songg\.cursor\projects\1779571378307\agent-transcripts\112ffbb0-4126-4ba3-a226-b15b0081690a\112ffbb0-4126-4ba3-a226-b15b0081690a.jsonl"),
    ]
    best: str | None = None
    marker_ok = lambda ln: (
        "AAPL" in ln and "Breakout Date" in ln and "MSFT" in ln and ZONE_HDR in ln
    )
    for p in candidates:
        if not p.is_file():
            continue
        # Read from end in chunks — latest MAG7 paste is near EOF.
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 8_000_000)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            if '"role":"user"' not in line or not marker_ok(line):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            txt = obj["message"]["content"][0]["text"]
            if best is None or len(txt) > len(best):
                best = txt
        if best:
            break
    return best


def main() -> None:
    brt_tab = "--brt" in sys.argv
    argv = [a for a in sys.argv[1:] if a != "--brt"]
    if argv:
        paste_path = Path(argv[0])
        text = paste_path.read_text(encoding="utf-8-sig")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        found = _load_from_transcript()
        if found is None:
            paste = TOOLS / "mag7_sheet_paste.txt"
            if paste.is_file():
                text = paste.read_text(encoding="utf-8-sig")
            else:
                print("Usage: ingest_mag7_sheet_paste.py [paste.txt]  (or pipe stdin)", file=sys.stderr)
                sys.exit(1)
        else:
            text = found
            print("Loaded paste from transcript")

    parsed = parse_multisymbol_paste(text)
    if not parsed:
        print("No symbols parsed", file=sys.stderr)
        sys.exit(1)
    write_ledgers(parsed, brt_tab=brt_tab)


if __name__ == "__main__":
    main()
