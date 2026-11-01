"""Rewrite F HTML from saved JSON. Does not rescore. Does not start F."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import _write_system_f_tennis_spread_20261030 as w  # noqa: E402

NOTE = (
    "n/a — no IS (all T0 ≥ 2024-01-01; this tape starts Apr 2025)"
)


def main() -> int:
    blob = json.loads(w.JSON_OUT.read_text(encoding="utf-8"))
    meta = blob.get("live_meta") or {}
    n_lines = meta.get("n_lines") or 0
    blob["tape_20_49"]["note"] = (
        f"Kitchen tennis ticks Oct 21–30 2026 are moneyline only "
        f"({n_lines} lines, 0 spread Yes). price_last_games tennis files have "
        "no spread market_type. N=0 is labeled, not mixed with hist."
    )
    blob["tape_10_49"]["note"] = "Not the freeze. Same empty live-spread tape as the 20–49 row."
    for key in ("hist_20_49", "hist_10_49", "tape_20_49", "tape_10_49"):
        blob[key]["is_note"] = NOTE
        q = blob[key].get("quality") or {}
        if q:
            q["is_note"] = NOTE
    w.JSON_OUT.write_text(json.dumps(blob, indent=2, default=str) + "\n", encoding="utf-8")
    path = w.write_html(blob, blob.get("written") or "")
    w.link_recs_page()
    print("rewrote", path)
    print("f_running", blob.get("f_running"), "pids", blob.get("f_pids"))
    print("hist20", blob["hist_20_49"]["n"], blob["hist_20_49"]["avg"])
    print("tape20", blob["tape_20_49"]["n"], blob["tape_20_49"]["avg"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
