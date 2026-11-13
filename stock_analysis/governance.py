"""Production-change governance: every live knob is locked; changes go through adopt.

Why: ~1,000 experiment folders and dozens of A/B launchers fed straight into
production. Each adoption looked good in-sample and decayed after its freeze
(see drive/honest_bt/). The fix is not "never change" but "change rarely,
on honest evidence, and on the record".

  governance/production_lock.json  fingerprint of every production knob (tracked in git)
  governance/ADOPTIONS.csv         one row per adopted change (tracked in git)
  tools/adopt.py                   the only sanctioned way to change the lock

Enforcement: investment-report allotment calls `drift()`. Any unadopted change
halts NEW buys (stops/targets for open lots still publish — DailyRun keeps running).

Fingerprints normalise line endings and trailing whitespace, so CRLF churn
from the Windows checkout never trips the lock.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

REPO = Path(__file__).resolve().parents[1]
GOV_DIR = REPO / "governance"
LOCK_PATH = GOV_DIR / "production_lock.json"
LEDGER_PATH = GOV_DIR / "ADOPTIONS.csv"
LEDGER_COLS = ["date", "system", "change", "evidence", "honest_verdict", "trials", "override_reason", "lock_digest"]

MAX_PER_SYSTEM_PER_QUARTER = 1
MAX_TOTAL_PER_QUARTER = 3

# Production launchers (DailyRun + every wired sleeve) and the universes they read.
LAUNCHERS = {
    "DAILYRUN": ["DailyRun.bat"],
    "BRT": ["run_brt.bat"], "YH": ["run_yh.bat"], "MTS": ["run_mts.bat"], "WPBR": ["run_wpbr.bat"],
    "RS": ["run_rs.bat"], "SB": ["run_sb.bat", "run_stockbee_burst.bat"], "VZ": ["run_vz.bat"],
    "RSI": ["run_rsi.bat"], "WRL": ["run_wrl.bat"], "RL": ["run_rl.bat", "run_audit.bat", "run_audit.ps1"],
}
UNIVERSES = {
    "BRT": "drive/universes/BRT_universe.csv", "YH": "drive/universes/YH_universe.csv",
    "MTS": "drive/universes/MTS_universe.csv", "WPBR": "drive/universes/WPBR_universe.csv",
    "RS": "drive/universes/RS_universe.csv", "SB": "drive/universes/SB_universe.csv",
    "VZ": "drive/universes/VZ_universe.csv", "RSI": "drive/universes/rsi_universe.csv",
    "WRL": "drive/universes/WRL_universe.csv", "RL": "drive/universes/RL_universe.csv",
}
EXTRA_FILES = {"BRT": ["stock_analysis/Per_Symbol_Optimized_Settings_Approved_Latest.json"]}


def _norm_digest(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    text = path.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _sizing_knobs() -> dict:
    import importlib
    import sys
    sys.path.insert(0, str(REPO / "stock_analysis"))
    lss = importlib.import_module("live_style_sizing")
    pr = importlib.import_module("portfolio_risk")
    names = ["RISK_FRAC", "MAX_RISK_DOLLAR", "ADV_FRAC", "ADV_WINDOW", "NAME_CAP_FRAC",
             "MAX_NOTIONAL_PER_TRADE", "MAX_OPEN_NAMES", "MAX_GROSS_LONG_FRAC", "LIVE_RISK_MULT",
             "TESTED_MIN_HISTORY_BARS", "TESTED_MIN_PRICE", "TESTED_MIN_DOLLAR_VOL", "TESTED_WINDOW"]
    out = {n: getattr(lss, n) for n in names if hasattr(lss, n)}
    out["RiskLimits"] = asdict(pr.RiskLimits())
    return out


def fingerprint(repo: Path = REPO, *, sizing: Optional[dict] = None) -> dict:
    """{key: digest} for every production knob. Missing files are recorded as None."""
    fp: dict[str, Optional[str]] = {}
    for sys_code, files in LAUNCHERS.items():
        for f in files:
            fp[f"{sys_code}:{f}"] = _norm_digest(repo / f)
    for sys_code, f in UNIVERSES.items():
        fp[f"{sys_code}:{f}"] = _norm_digest(repo / f)
    for sys_code, files in EXTRA_FILES.items():
        for f in files:
            fp[f"{sys_code}:{f}"] = _norm_digest(repo / f)
    knobs = sizing if sizing is not None else _sizing_knobs()
    fp["SIZING:knobs"] = hashlib.sha256(json.dumps(knobs, sort_keys=True).encode()).hexdigest()[:16]
    return fp


def lock_digest(fp: dict) -> str:
    return hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()[:12]


def load_lock(path: Path = LOCK_PATH) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("fingerprint", {})


def write_lock(fp: dict, path: Path = LOCK_PATH, *, note: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"written": str(date.today()), "note": note, "digest": lock_digest(fp), "fingerprint": fp}
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def drift(repo: Path = REPO, lock_path: Path = LOCK_PATH, *, sizing: Optional[dict] = None) -> list[str]:
    """Keys whose fingerprint differs from the lock. Empty = governed. No lock = everything drifts."""
    locked = load_lock(lock_path)
    now = fingerprint(repo, sizing=sizing)
    if not locked:
        return ["no governance/production_lock.json"]
    return sorted(k for k in set(locked) | set(now) if locked.get(k) != now.get(k))


def systems_for(keys: Iterable[str]) -> list[str]:
    return sorted({k.split(":", 1)[0] for k in keys})


def _quarter(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def ledger(path: Path = LEDGER_PATH) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def budget_problems(systems: list[str], today: date, path: Path = LEDGER_PATH) -> list[str]:
    """Reasons this adoption would exceed the quarterly change budget."""
    q = _quarter(today)
    rows = [r for r in ledger(path) if r.get("date") and _quarter(date.fromisoformat(r["date"])) == q
            and r.get("system") != "ALL"]  # overrides count too; only the baseline row is exempt
    probs = []
    if len(rows) + 1 > MAX_TOTAL_PER_QUARTER:
        probs.append(f"{len(rows)} adoptions already this quarter (max {MAX_TOTAL_PER_QUARTER})")
    for s in systems:
        n = sum(1 for r in rows if s in r.get("system", "").split("+"))
        if n + 1 > MAX_PER_SYSTEM_PER_QUARTER:
            probs.append(f"{s} already changed this quarter (max {MAX_PER_SYSTEM_PER_QUARTER}/system)")
    return probs


def append_ledger(row: dict, path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LEDGER_COLS})
