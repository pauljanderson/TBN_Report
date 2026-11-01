"""One-shot status dump. Does not sell. Does not spawn."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import prediction_job_control as jc
import prediction_systems as ps
from prediction_paths import RAW

jobs = jc.classify(jc._ps_rows())
cfgs = ps.load_config()
out = {
    "systems": {
        sid: {
            "letter": ps.LETTER[sid],
            "on": bool(cfgs[sid].on),
            "max_open": cfgs[sid].max_open,
            "stake": str(cfgs[sid].stake_usd),
            "net_max": str(cfgs[sid].net_max) if cfgs[sid].net_max is not None else None,
        }
        for sid in ps.SYSTEM_IDS
    },
    "pids": {
        key: [row.get("pid") for row in (jobs.get(key) or [])]
        for key in (
            "supervisor",
            "scan",
            "strategy_b",
            "cfb_favorite",
            "spread_t0",
            "tennis_t0_dog",
        )
    },
    "poller_n": len(jobs.get("children") or []),
    "latch": (RAW / "orders_stopped.json").exists(),
}
print(json.dumps(out, indent=2))
