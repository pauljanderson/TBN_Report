#!/usr/bin/env python3
"""Adopt a production change: the only sanctioned way to move governance/production_lock.json.

  python tools/adopt.py --check
      show what changed since the lock (nothing = governed)

  python tools/adopt.py --system RSI --change "roll 8 -> 6" --evidence drive/honest_bt/20261201
      record the change and re-lock. Refused unless:
        * the honest harness PIT verdict for that system is PASS
          (drive/honest_bt/<stamp>/scorecard.json from score.py), and
        * the quarterly budget allows it (1 per system, 3 total)

  ... --override "why this cannot wait"
      bypass the verdict/budget, on the record (shows in ADOPTIONS.csv)

A plain refactor that does not change behaviour (comments, CRLF) does not drift:
fingerprints ignore line endings and trailing whitespace. For a deliberate
no-behaviour edit (e.g. adding a comment line) use --change "no-op: ..." --override "no behaviour change".
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools" / "honest_bt"))
import governance as gov  # noqa: E402


def honest_verdict(evidence: Path, system: str) -> tuple[str, int]:
    card = evidence / "scorecard.json" if evidence.is_dir() else evidence
    if not card.is_file():
        return "MISSING", 0
    data = json.loads(card.read_text(encoding="utf-8"))
    rec = data.get("systems", {}).get(system, {})
    pit = rec.get("pit") or {}
    return str(pit.get("verdict", "MISSING")), int(rec.get("trials", 0) or 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--system", help="system code(s) changed, e.g. RSI or RSI+VZ (SIZING / DAILYRUN allowed)")
    ap.add_argument("--change", help="one line: what changed")
    ap.add_argument("--evidence", help="drive/honest_bt/<stamp> (or its scorecard.json)")
    ap.add_argument("--override", default="", help="reason to bypass verdict/budget (recorded)")
    ap.add_argument("--init", action="store_true", help="write the first lock (only if none exists)")
    a = ap.parse_args(argv)

    if a.init:
        if gov.LOCK_PATH.exists():
            print("lock already exists; use --check / --system")
            return 1
        fp = gov.fingerprint()
        gov.write_lock(fp, note="initial lock 2026-11-12 (post-review baseline)")
        gov.append_ledger({"date": str(date.today()), "system": "ALL", "change": "initial production lock",
                           "evidence": "drive/honest_bt/20261112", "honest_verdict": "n/a",
                           "override_reason": "baseline", "lock_digest": gov.lock_digest(fp)})
        print(f"wrote {gov.LOCK_PATH} ({len(fp)} knobs, digest {gov.lock_digest(fp)})")
        return 0

    changed = gov.drift()
    if a.check or not a.system:
        if not changed:
            print("governed: production matches governance/production_lock.json")
            return 0
        print("UNADOPTED production changes (new buys are halted until adopted):")
        for k in changed:
            print(f"  {k}")
        print(f"systems: {'+'.join(gov.systems_for(changed))}\n"
              "adopt with: python tools/adopt.py --system <SYS> --change \"...\" --evidence drive/honest_bt/<stamp>")
        return 1 if a.check else 0

    systems = [s.strip().upper() for s in a.system.split("+") if s.strip()]
    touched = gov.systems_for(changed)
    if not changed:
        print("nothing changed since the lock; nothing to adopt")
        return 1
    missing = [s for s in touched if s not in systems]
    if missing:
        print(f"REFUSED: changes also touch {missing}; list every system changed (--system {'+'.join(touched)})")
        return 1
    if not a.change:
        print("REFUSED: --change is required")
        return 1

    problems: list[str] = []
    verdicts, trials = [], 0
    for s in systems:
        if s in ("SIZING", "DAILYRUN"):
            continue
        v, t = honest_verdict(REPO / (a.evidence or "missing"), s)
        verdicts.append(f"{s}={v}")
        trials = max(trials, t)
        if v != "PASS":
            problems.append(f"{s} honest PIT verdict is {v} (needs PASS)")
    problems += gov.budget_problems(systems, date.today())
    if problems and not a.override:
        print("REFUSED:\n  " + "\n  ".join(problems) + "\n(--override \"reason\" records a bypass)")
        return 1

    fp = gov.fingerprint()
    gov.write_lock(fp, note=a.change)
    gov.append_ledger({"date": str(date.today()), "system": "+".join(systems), "change": a.change,
                       "evidence": a.evidence or "", "honest_verdict": " ".join(verdicts) or "n/a",
                       "trials": trials, "override_reason": a.override, "lock_digest": gov.lock_digest(fp)})
    print(f"adopted {'+'.join(systems)}: {a.change} (lock {gov.lock_digest(fp)})"
          + (f"\n  OVERRIDE: {a.override}; bypassed: {problems}" if problems else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
