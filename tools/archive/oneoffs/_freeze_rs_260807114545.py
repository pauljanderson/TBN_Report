"""One-shot: freeze RS stamp 260807114545 as new reconcile golden."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

STAMP = "260807114545"
OLD = "260801111512"
ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DST = DRIVE / "paul_experiments" / f"rs_baseline_{STAMP}"
ENG = DST / "engine_closed"


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
    syms = sorted({r["SYMBOL"] for r in closed})
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
| Engine stamp | **`{STAMP}`** (2026-08-07 ~11:45 local) |
| Golden Closed | `engine_closed/RS_Closed_{STAMP}.csv` (**{len(closed)}** trades, **{len(syms)}** symbols) |
| Also frozen | Audit, Report, Summary, Open, Watchlist, EquityCurve (+ Aggressive/Regular/Meta) |
| Closed date span | opened `{min(opens)}` → `{max(opens)}`; closed through `{max(closes)}` |
| Gate config | `../reconcile_gate_config.json` → system **`RS`** |
| Prior freeze | `{OLD}` (`time_stop_days=0`) — superseded by this TIME=252 production adopt |

## Levers (from this stamp's Audit + Closed STOP/TARGET ratios)

| Lever | Value on `{STAMP}` | Notes |
|---|---|---|
| `rs_mode` | `true` | |
| `rs_require_tc_strong` | `true` | |
| `rs_spy_int_tc_not_weak` | **`true`** | matches `run_rs.bat` |
| `symbol_reentry_cooldown_days` | **`60`** | matches `run_rs.bat` |
| `stop_pct` / `stop_pct_is_multiplier` | **`0.88` / `true`** | Closed STOP÷ENTRY ≈ **0.88** |
| `target_pct` | **`1.25`** | Closed TARGET÷ENTRY ≈ **1.25** |
| `time_stop_days` | **`252`** | adopted from `rs_noft_time_ab` arm `15_time_252` (env `RS_TIME_STOP`; set `0` to disable) |
| `no_ft_days` | `0` | off |
| `sell_breakdown` | `off` | |
| `rs_max_pct_below_52w_high` | `0` | |
| `growth_filter_enabled` | `false` | |
| `min_spy_compare_1y_at_trigger` | `0` | |
| `too_high_multiplier` | `0` | |
| `atr_days` | `0` | |

### Aligned with production `run_rs.bat`

Production `run_rs.bat` defaults: **`stop_pct=0.88`**, **`target_pct=1.25`**, **`time_stop_days=252`** (via `RS_TIME_STOP`). A/B evidence: control Total_PNL ~$1.756M → TIME=252 ~$1.918M (**+$161k**); Max_DD 9.98 → 10.88 (slight DD↑). Research stamp **`260801104344`** used 0.934/1.21 — historical only.

## Symbol universe (54 — matches `run_rs.bat` / `drive/universes/RS_universe.csv`)

```
{','.join(syms)}
```

## Audit headline metrics (stamp)

| Metric | Value |
|---|---|
| Total_Trades | {a('Total_Trades') or len(closed)} |
| Total_PNL | {a('Total_PNL')} |
| Profit_Factor | {a('Profit_Factor')} |
| Ann_ROR | {a('Ann_ROR')} |
| Max_DD | {a('Max_DD')} |

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

Compares frozen Closed vs latest `RS_LatestRun_Closed.csv` (or newest `RS_Closed_*.csv`) for the 54 symbols above.

- Identity: `SYMBOL + DATE_OPENED + DATE_CLOSED`
- Fail: missing / changed entry·exit / PnL_PCT / EXIT_TYPE beyond soft tol
- Allow: `new_only` (forward fills after freeze cutoff)

See `../yh_baseline_20260731/RECONCILE_GATE.md`.
"""
    (DST / "README.md").write_text(readme, encoding="utf-8")
    print("wrote", DST / "README.md")

    cfg_path = DRIVE / "paul_experiments" / "reconcile_gate_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for sys in cfg["systems"]:
        if sys["id"] != "RS":
            continue
        sys["baseline"] = {
            "mode": "single_file",
            "path": f"drive/paul_experiments/rs_baseline_{STAMP}/engine_closed/RS_Closed_{STAMP}.csv",
        }
        sys["freeze_note"] = (
            f"RS FIT-54 engine Closed stamp {STAMP} ({len(closed)} trades). "
            f"Levers: spy_int + cd=60; stop 0.88 / target 1.25; time_stop_days=252 "
            f"(replaces {OLD} with time_stop=0). Matches run_rs.bat. "
            f"See rs_baseline_{STAMP}/README.md."
        )
        print("updated RS baseline path ->", sys["baseline"]["path"])
    # Keep notes accurate without rewriting other systems
    note = cfg.get("notes") or ""
    if STAMP not in note:
        cfg["notes"] = (
            note.rstrip()
            + f" RS re-frozen {STAMP} for time_stop_days=252 (prior {OLD})."
        )
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("updated", cfg_path)

    print("AUDIT_KEYS", sorted(audit.keys())[:40])
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
    ):
        print(k, a(k))


if __name__ == "__main__":
    main()
