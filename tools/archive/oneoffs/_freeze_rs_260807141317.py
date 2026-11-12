"""One-shot: freeze RS stamp 260807141317 as new reconcile golden (65 expand)."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

STAMP = "260807141317"
OLD = "260807114545"
ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DST = DRIVE / "paul_experiments" / f"rs_baseline_{STAMP}"
ENG = DST / "engine_closed"
UNIV = DRIVE / "universes" / "RS_universe.csv"


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
        f"RS_Closed_{STAMP}.csv",
        f"RS_Audit_Report_{STAMP}.csv",
        f"RS_Report_{STAMP}.csv",
        f"RS_Summary_{STAMP}.csv",
        f"RS_Open_{STAMP}.csv",
        f"RS_Watchlist_{STAMP}.csv",
        f"RS_EquityCurve_{STAMP}.csv",
        f"RS_EquityCurve_Aggressive_{STAMP}.csv",
        f"RS_EquityCurve_Regular_{STAMP}.csv",
        f"RS_EquityMeta_{STAMP}.csv",
    ]
    for name in patterns:
        src = DRIVE / name
        if not src.exists():
            print("MISSING", name)
            continue
        shutil.copy2(src, ENG / name)
        print("copied", name, src.stat().st_size)

    audit = list(csv.DictReader((ENG / f"RS_Audit_Report_{STAMP}.csv").open(encoding="utf-8")))[0]
    closed = list(csv.DictReader((ENG / f"RS_Closed_{STAMP}.csv").open(encoding="utf-8")))
    syms_closed = sorted({r["SYMBOL"] for r in closed})
    univ = _load_universe()
    opens = [r["DATE_OPENED"] for r in closed if r.get("DATE_OPENED")]
    closes = [r["DATE_CLOSED"] for r in closed if r.get("DATE_CLOSED")]

    def a(*keys: str) -> str:
        for k in keys:
            if k in audit and audit[k] not in (None, ""):
                return str(audit[k])
        lower = {kk.lower(): vv for kk, vv in audit.items()}
        for k in keys:
            if k.lower() in lower and lower[k.lower()] not in (None, ""):
                return str(lower[k.lower()])
        return ""

    shutil.copy2(DRIVE / f"RS_Closed_{STAMP}.csv", DRIVE / "RS_LatestRun_Closed.csv")
    print("wrote RS_LatestRun_Closed.csv")

    readme = f"""# RS reconcile baseline freeze — stamp `{STAMP}`

Frozen **engine Closed** for the DailyRun reconcile gate (`tools/reconcile_gate.py`). Same idea as YH Mag7+ / BRT Mag10 / WPBR Mag9 baselines: fail when historical Closed trades go missing or materially change.

**Do not invent trades** — this folder is a copy of a real `drive/RS_*_{STAMP}.*` run.

## Stamp / date

| Item | Value |
|---|---|
| Engine stamp | **`{STAMP}`** (2026-08-07 ~14:13 local) |
| Golden Closed | `engine_closed/RS_Closed_{STAMP}.csv` (**{len(closed)}** trades, **{len(syms_closed)}** symbols) |
| Also frozen | Audit, Report, Summary, Open, Watchlist, EquityCurve (+ Aggressive/Regular/Meta) |
| Closed date span | opened `{min(opens) if opens else "?"}` → `{max(opens) if opens else "?"}`; closed through `{max(closes) if closes else "?"}` |
| Gate config | `../reconcile_gate_config.json` → system **`RS`** |
| Prior freeze | `{OLD}` (FIT-54, stop 0.88 / target 1.25 / time_stop=252) — superseded by this **65 expanded universe** + **stop 0.85** production |

## Levers (from this stamp's Audit + Closed STOP/TARGET ratios)

| Lever | Value on `{STAMP}` | Notes |
|---|---|---|
| `rs_mode` | `true` | |
| `rs_require_tc_strong` | `true` | |
| `rs_spy_int_tc_not_weak` | **`true`** | matches `run_rs.bat` |
| `symbol_reentry_cooldown_days` | **`60`** | matches `run_rs.bat` |
| `stop_pct` / `stop_pct_is_multiplier` | **`0.85` / `true`** | Closed STOP÷ENTRY ≈ **0.85** (adopted from prior post-252 A/B widen) |
| `target_pct` | **`1.25`** | Closed TARGET÷ENTRY ≈ **1.25** |
| `time_stop_days` | **`252`** | production (env `RS_TIME_STOP`; set `0` to disable) |
| `no_ft_days` | `0` | off |
| `sell_breakdown` | `off` | |
| `rs_max_pct_below_52w_high` | `0` | |
| `growth_filter_enabled` | `false` | |
| `min_spy_compare_1y_at_trigger` | `0` | |
| `too_high_multiplier` | `0` | |
| `atr_days` | `0` | |

### Aligned with production `run_rs.bat`

Production `run_rs.bat` defaults: **`stop_pct=0.85`**, **`target_pct=1.25`**, **`time_stop_days=252`** (via `RS_TIME_STOP`). Universe: **`drive/universes/RS_universe.csv`** (65 expanded FIT names; synced from `RS_universe_expand.csv`).

## Symbol universe ({len(univ)} — matches `run_rs.bat` / `drive/universes/RS_universe.csv`)

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
rs_baseline_{STAMP}/
  README.md
  engine_closed/
    RS_Closed_{STAMP}.csv          <- gate golden
    RS_Audit_Report_{STAMP}.csv
    ...
```

Source originals remain under `drive/RS_*_{STAMP}.*`.

## Gate behavior

Compares frozen Closed vs latest `RS_LatestRun_Closed.csv` (or newest `RS_Closed_*.csv`) for the {len(univ)} symbols above.

- Identity: `SYMBOL + DATE_OPENED + DATE_CLOSED`
- Fail: missing / changed entry·exit / PnL_PCT / EXIT_TYPE beyond soft tol
- Allow: `new_only` (forward fills after freeze cutoff)

See `../yh_baseline_20260731/RECONCILE_GATE.md`.

## Freeze history

| Stamp | Universe | stop / target / time | Notes |
|---|---|---|---|
| `260801111512` | 54 | 0.88 / 1.25 / 0 | prior no-TIME |
| `{OLD}` | 54 | 0.88 / 1.25 / 252 | TIME=252 adopt |
| **`{STAMP}`** | **65** | **0.85 / 1.25 / 252** | expanded FIT + stop widen |
"""
    (DST / "README.md").write_text(readme, encoding="utf-8")
    print("wrote", DST / "README.md")

    cfg_path = DRIVE / "paul_experiments" / "reconcile_gate_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for sys in cfg["systems"]:
        if sys["id"] != "RS":
            continue
        sys["symbols"] = list(univ)
        sys["baseline"] = {
            "mode": "single_file",
            "path": f"drive/paul_experiments/rs_baseline_{STAMP}/engine_closed/RS_Closed_{STAMP}.csv",
        }
        sys["freeze_note"] = (
            f"RS expanded-65 engine Closed stamp {STAMP} ({len(closed)} trades). "
            f"Levers: spy_int + cd=60; stop 0.85 / target 1.25; time_stop_days=252 "
            f"(replaces {OLD} FIT-54 stop 0.88). Matches run_rs.bat / RS_universe.csv. "
            f"See rs_baseline_{STAMP}/README.md."
        )
        print("updated RS baseline path ->", sys["baseline"]["path"])
        print("updated RS symbols ->", len(sys["symbols"]))
    note = cfg.get("notes") or ""
    marker = f"RS re-frozen {STAMP}"
    if marker not in note:
        cfg["notes"] = (
            note.rstrip()
            + f" {marker} for expanded-65 universe + stop 0.85 (prior {OLD} FIT-54 stop 0.88)."
        )
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("updated", cfg_path)

    for k in (
        "Total_Trades",
        "Total_PNL",
        "Profit_Factor",
        "Ann_ROR",
        "Max_DD",
        "Pct_Wins",
        "Avg_Days_Held",
        "Losing_Streak",
        "P90_Days",
        "brt_cash",
        "Max_Positions",
        "stop_pct",
        "target_pct",
        "time_stop_days",
    ):
        print(k, a(k))


if __name__ == "__main__":
    main()
