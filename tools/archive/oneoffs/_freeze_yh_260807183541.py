"""One-shot: freeze YH stamp 260807183541 as Mag9 golden (TSLA removed)."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

STAMP = "260807183541"
OLD = "260801110845"
ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DST = DRIVE / "paul_experiments" / f"yh_baseline_{STAMP}"
ENG = DST / "engine_closed"
UNIV = DRIVE / "universes" / "YH_universe.csv"


def _load_universe() -> list[str]:
    syms: list[str] = []
    with UNIV.open(encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            s = line.strip().split(",")[0].strip().upper()
            if not s or s.startswith("#") or s.lower() in ("symbol", "ticker"):
                continue
            if s not in syms:
                syms.append(s)
    return syms


def main() -> None:
    ENG.mkdir(parents=True, exist_ok=True)
    patterns = [
        f"YH_Closed_{STAMP}.csv",
        f"YH_Audit_Report_{STAMP}.csv",
        f"YH_Report_{STAMP}.csv",
        f"YH_Summary_{STAMP}.csv",
        f"YH_Open_{STAMP}.csv",
        f"YH_Watchlist_{STAMP}.csv",
        f"YH_EquityCurve_{STAMP}.csv",
        f"YH_EquityCurve_Aggressive_{STAMP}.csv",
        f"YH_EquityCurve_Regular_{STAMP}.csv",
        f"YH_EquityMeta_{STAMP}.csv",
    ]
    for name in patterns:
        src = DRIVE / name
        if not src.exists():
            print("MISSING", name)
            continue
        shutil.copy2(src, ENG / name)
        print("copied", name, src.stat().st_size)

    closed = list(csv.DictReader((ENG / f"YH_Closed_{STAMP}.csv").open(encoding="utf-8-sig")))
    syms_closed = sorted({r["SYMBOL"].strip().upper() for r in closed})
    univ = _load_universe()
    opens = [r["DATE_OPENED"] for r in closed if r.get("DATE_OPENED")]
    closes = [r["DATE_CLOSED"] for r in closed if r.get("DATE_CLOSED")]
    if "TSLA" in univ or "TSLA" in syms_closed:
        raise SystemExit("refusing freeze: TSLA still present (Mag9 should exclude TSLA)")

    audit_path = ENG / f"YH_Audit_Report_{STAMP}.csv"
    audit: dict[str, str] = {}
    if audit_path.is_file():
        audit = list(csv.DictReader(audit_path.open(encoding="utf-8-sig")))[0]

    def a(*keys: str) -> str:
        for k in keys:
            if k in audit and audit[k] not in (None, ""):
                return str(audit[k])
        lower = {kk.lower(): vv for kk, vv in audit.items()}
        for k in keys:
            if k.lower() in lower and lower[k.lower()] not in (None, ""):
                return str(lower[k.lower()])
        return ""

    # Keep LatestRun alias aligned with this freeze stamp (DailyRun already did).
    shutil.copy2(DRIVE / f"YH_Closed_{STAMP}.csv", DRIVE / "YH_LatestRun_Closed.csv")
    print("wrote YH_LatestRun_Closed.csv")

    readme = f"""# YH reconcile baseline freeze — stamp `{STAMP}`

Frozen **engine Closed** for the DailyRun reconcile gate (`tools/reconcile_gate.py`).

**Do not invent trades** — this folder is a copy of a real `drive/YH_*_{STAMP}.*` run.

## Stamp / date

| Item | Value |
|---|---|
| Engine stamp | **`{STAMP}`** (DailyRun 2026-08-07 ~18:35 local) |
| Golden Closed | `engine_closed/YH_Closed_{STAMP}.csv` (**{len(closed)}** trades, **{len(syms_closed)}** symbols) |
| Also frozen | Audit, Report, Summary, Open, Watchlist, EquityCurve (+ Aggressive/Regular/Meta) |
| Closed date span | opened `{min(opens) if opens else "?"}` → `{max(opens) if opens else "?"}`; closed through `{max(closes) if closes else "?"}` |
| Universe | **Mag9** (TSLA removed) — matches `drive/universes/YH_universe.csv` / `run_yh.bat` |
| Gate config | `../reconcile_gate_config.json` → system **`YH`** |
| Prior freeze | `{OLD}` Mag10 (441 trades incl. TSLA) — superseded because production dropped TSLA |

## Why re-freeze

Production YH universe is Mag9 without **TSLA**. Gate vs `{OLD}` failed with `TSLA base=64 latest=0` (missing baseline). New golden is the Mag9 Closed ledger from DailyRun stamp `{STAMP}`.

## Symbol universe ({len(univ)})

```
{','.join(univ)}
```

Closed symbols ({len(syms_closed)}): `{','.join(syms_closed)}`

## Audit headline metrics (stamp)

| Metric | Value |
|---|---|
| Total_Trades | {a('Total_Trades') or len(closed)} |
| Total_PNL | {a('Total_PNL')} |
| Profit_Factor | {a('Profit_Factor')} |
| Ann_ROR | {a('Ann_ROR')} |
| Max_DD | {a('Max_DD')} |
| Pct_Wins | {a('Pct_Wins')} |
| Avg_Days_Held | {a('Avg_Days_Held')} |

## Layout

```
yh_baseline_{STAMP}/
  README.md
  engine_closed/
    YH_Closed_{STAMP}.csv          <- gate golden
    YH_Audit_Report_{STAMP}.csv
    ...
```

Source originals remain under `drive/YH_*_{STAMP}.*`.

## Gate behavior

Compares frozen Closed vs latest `YH_LatestRun_Closed.csv` (or newest `YH_Closed_*.csv`) for the Mag9 symbols above.

- Identity: `SYMBOL + DATE_OPENED + DATE_CLOSED`
- Fail: missing / changed entry·exit / PnL_PCT / EXIT_TYPE beyond soft tol
- Allow: `new_only` (forward fills after freeze cutoff)

See `../yh_baseline_20260731/RECONCILE_GATE.md`.

## Freeze history

| Stamp | Universe | Notes |
|---|---|---|
| `20260731` / multi | Mag7+ slices | early multi-stamp archive |
| `{OLD}` | Mag10 (incl. TSLA) | longer OHLC / AMD restore |
| **`{STAMP}`** | **Mag9 (no TSLA)** | production `YH_universe.csv` |
"""
    (DST / "README.md").write_text(readme, encoding="utf-8")
    print("wrote", DST / "README.md")

    cfg_path = DRIVE / "paul_experiments" / "reconcile_gate_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for sys in cfg["systems"]:
        if sys["id"] != "YH":
            continue
        sys["symbols"] = list(univ)
        sys["baseline"] = {
            "mode": "single_file",
            "path": f"drive/paul_experiments/yh_baseline_{STAMP}/engine_closed/YH_Closed_{STAMP}.csv",
        }
        sys["freeze_note"] = (
            f"YH Mag9 (no TSLA) engine Closed stamp {STAMP} ({len(closed)} trades). "
            f"Replaces {OLD} Mag10 freeze after TSLA removed from YH_universe.csv. "
            f"See yh_baseline_{STAMP}/README.md."
        )
        print("updated YH baseline path ->", sys["baseline"]["path"])
        print("updated YH symbols ->", sys["symbols"])
    note = cfg.get("notes") or ""
    marker = f"YH re-frozen {STAMP}"
    if marker not in note:
        cfg["notes"] = (
            note.rstrip()
            + f" {marker} Mag9 no-TSLA (prior {OLD} Mag10)."
        )
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("updated", cfg_path)


if __name__ == "__main__":
    main()
