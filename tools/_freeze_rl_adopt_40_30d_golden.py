#!/usr/bin/env python3
"""One-shot: point RL reconcile golden at adopt stamp 260831213302."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = "260831213302"
CFG = ROOT / "drive" / "paul_experiments" / "reconcile_gate_config.json"
BASE = ROOT / "drive" / "paul_experiments" / f"rl_baseline_{STAMP}"
CLOSED = BASE / "engine_closed" / f"RL_Closed_{STAMP}.csv"

assert CLOSED.is_file(), CLOSED

readme = f"""# RL reconcile baseline freeze — stamp `{STAMP}`

Frozen **engine Closed** for the DailyRun reconcile gate after house adopt **+40%/30d**.

## Stamp / settings

| Item | Value |
|---|---|
| Engine stamp | **`{STAMP}`** (adopt exit 40_30d + cut OFF 2026-08-31) |
| Golden Closed | `engine_closed/RL_Closed_{STAMP}.csv` (**674** closed) |
| Runner | `run_rl.bat` after house `rl_exit_percent=0.40` / `rl_exit_days=30` / `rl_cut_the_losers=1000` |
| Gate config | `../reconcile_gate_config.json` → system **`RL`** |
| Prior | `260827175608` (dip=1.055; exit 0.29/10000; cut default 0.25) |
| Adopt note | `../rl_adopt_exit_40_30d_20260831/` |

## Why freeze

House timed exit changed to **+40% then 30d** and cut OFF — Paul override after AB IS LEAN KEEP / OOS DISMISS vs 40d@29%. Engine↔engine golden so DailyRun reconcile catches historical trade rewrites.

## Layout

```
rl_baseline_{STAMP}/
  README.md
  engine_closed/
    RL_Closed_{STAMP}.csv   <- gate golden
```
"""
(BASE / "README.md").write_text(readme, encoding="utf-8")

c = json.loads(CFG.read_text(encoding="utf-8"))
for s in c["systems"]:
    if s["id"] == "RL":
        s["baseline"] = {
            "mode": "single_file",
            "path": f"drive/paul_experiments/rl_baseline_{STAMP}/engine_closed/RL_Closed_{STAMP}.csv",
        }
        s["freeze_note"] = (
            f"RL 59-name production universe engine Closed stamp {STAMP} (674 trades). "
            "House adopt rl_exit_percent=0.40 / rl_exit_days=30 / rl_cut_the_losers=1000 "
            "(Paul override; prior AB 40_30d IS LEAN KEEP / OOS DISMISS vs 40d@29%). "
            f"Prior golden 260827175608. See rl_baseline_{STAMP}/README.md and "
            "rl_adopt_exit_40_30d_20260831/."
        )
        break
note = c.get("notes", "")
if STAMP not in note:
    c["notes"] = (
        note.rstrip()
        + f" RL re-frozen {STAMP} after house adopt exit +40%/30d + cut OFF Paul override "
        "(prior 260827175608)."
    )
CFG.write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
print(f"RL golden -> {STAMP}")
