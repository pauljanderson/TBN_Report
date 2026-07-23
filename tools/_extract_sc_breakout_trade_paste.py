#!/usr/bin/env python3
"""Find and extract latest AAPL/META WPBR breakout+trade pastes from transcript."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
BASE = REPO / "drive" / "wpbr_sheet_reconcile"

MARKERS = {
    "AAPL": [
        "28.52\t28.52\t27.68",
        "28.52\\t28.52\\t27.68",
        "9/13/2016\t$26.88",
        "9/13/2016\\t$26.88",
    ],
    "META": [
        "119.35\t119.35\t115.82",
        "119.35\\t119.35\\t115.82",
        "8/2/2016\t$124.06",
        "8/2/2016\\t$124.06",
    ],
    "MSFT": [
        "57.62\t57.62\t55.92",
        "57.62\\t57.62\\t55.92",
        "11/16/2016\t$58.94",
        "11/16/2016\\t$58.94",
    ],
}


def user_text(ln: str) -> str | None:
    if '"role":"user"' not in ln:
        return None
    try:
        obj = json.loads(ln)
    except Exception:
        return None
    parts = []
    for b in obj.get("message", {}).get("content", []) or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text") or "")
    text = "".join(parts)
    if "<user_query>" in text:
        text = text[text.find("<user_query>") + len("<user_query>") :]
    if "</user_query>" in text:
        text = text[: text.find("</user_query>")]
    return text.strip()


def find_prefix(rows: list[str], prefix: str, start: int = 0) -> int | None:
    for j in range(start, len(rows)):
        if rows[j].strip().startswith(prefix):
            return j
    return None


def section(rows: list[str], a: int, b: int) -> list[str]:
    out = list(rows[a:b])
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def to_csv(tsv_rows: list[str]) -> str:
    out = []
    for r in tsv_rows:
        cells = r.split("\t")
        clean = [c.strip().replace("$", "").replace(",", "") for c in cells]
        out.append(",".join(clean))
    return "\n".join(out)


def extract_sym(sym: str, prefer_pre2019: bool = False) -> None:
    lines = TRANSCRIPT.read_text(encoding="utf-8", errors="ignore").splitlines()
    markers = MARKERS[sym]
    candidates: list[tuple[int, str, bool]] = []
    for i, ln in enumerate(lines):
        if '"role":"user"' not in ln:
            continue
        if "Break out upper" not in ln or "Entry Date" not in ln:
            continue
        if not any(m in ln for m in markers):
            continue
        text = user_text(ln)
        if not text:
            continue
        pre = ("9/13/2016" in text) or ("6/21/2018" in text) or ("8/2/2016" in text)
        candidates.append((i, text, pre))

    assert candidates, f"no {sym} paste found"
    if prefer_pre2019:
        pre_cands = [c for c in candidates if c[2]]
        chosen = pre_cands[-1] if pre_cands else candidates[-1]
    else:
        chosen = candidates[-1]
    i, text, pre = chosen
    print(f"{sym}: using line {i} of {len(candidates)} candidates pre2019_trades={pre}")

    for prefix in (f"{sym}\n", f"{sym}\r\n"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break

    out = BASE / sym
    out.mkdir(parents=True, exist_ok=True)
    (out / "_raw_user_paste.txt").write_text(text, encoding="utf-8")

    rows = text.splitlines()
    i_zones = find_prefix(rows, "Break out upper")
    i_trades = find_prefix(rows, "Entry Date")
    assert i_zones is not None and i_trades is not None, f"{sym} missing sections"
    zones = section(rows, i_zones, i_trades)
    trades = section(rows, i_trades, len(rows))

    (out / "zones.tsv").write_text("\n".join(zones), encoding="utf-8")
    (out / "trades.tsv").write_text("\n".join(trades), encoding="utf-8")
    (out / "sheet_zones.tsv").write_text("\n".join(zones), encoding="utf-8")
    (out / "sheet_trades.tsv").write_text("\n".join(trades), encoding="utf-8")
    (out / "sheet_zones.csv").write_text(to_csv(zones), encoding="utf-8")
    (out / "sheet_trades.csv").write_text(to_csv(trades), encoding="utf-8")

    print(f"  zones={len(zones)} trades={len(trades)}")
    print("  trades head:")
    for l in trades[:6]:
        print("   ", l[:120])
    print("  trades tail:")
    for l in trades[-3:]:
        print("   ", l[:120])


def main() -> int:
    syms = sys.argv[1:] or ["AAPL", "META"]
    for sym in syms:
        extract_sym(sym, prefer_pre2019=(sym == "AAPL"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
