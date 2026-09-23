#!/usr/bin/env python3
"""Launch isolated RSI CONTROL vs min_dist52=7.18 candidate (research -o, no house pin steal)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAMP = "rsi_mindist52_718_20260916"
OUT = REPO / "drive" / "paul_experiments" / STAMP
UNIV = REPO / "drive" / "universes" / "rsi_universe.csv"

sys.path.insert(0, str(REPO))
from tools.load_universe_csv import load_tickers  # noqa: E402


def _cmd(out_dir: Path, extra_v: list[str], *, atr: str = "5") -> list[str]:
    tickers = load_tickers(UNIV)
    if not isinstance(tickers, list) or len(tickers) < 120:
        raise SystemExit(f"expected ~149 house tickers, got {tickers!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    return [
        sys.executable,
        str(REPO / "stock_analysis" / "rocket_tbn.py"),
        str(REPO / "data" / "newdata" / "data"),
        "-o",
        str(out_dir),
        "-w",
        "12",
        "--no-regression",
        "--aggressive",
        "--initial-capital",
        "500000",
        "--aggressive-max-multiple",
        "2.0",
        "--margin-utilization",
        "0.6",
        "-v",
        "rsi_mode=true",
        "-v",
        "vz_mode=false",
        "-v",
        "wrl_mode=false",
        "-v",
        "brt_zones=false",
        "-v",
        "yh_zones=false",
        "-v",
        "wpbr_zones=false",
        "-v",
        "rl_mode=false",
        "-v",
        "relative_strength_enabled=false",
        "-v",
        "rs_mode=false",
        "-v",
        "mvcp_mode=false",
        "-v",
        "sb_mode=false",
        "-v",
        "qull_mode=false",
        "-v",
        "indicator_buy=off",
        "-v",
        "rsi_ob=70",
        "-v",
        "rsi_os=30",
        "-v",
        "rsi_exit=70",
        "-v",
        "rsi_max_trigger=60",
        "-v",
        f"rsi_min_atr_pct={atr}",
        "-v",
        "rsi_time_stop_days=20",
        "-v",
        "rsi_entry_on=next_open",
        "-v",
        "rsi_sheet_notional=10000",
        *extra_v,
        "-s",
        ",".join(tickers),
    ]


def main() -> int:
    arm = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if arm == "control":
        cmd = _cmd(OUT / "control", [])
    elif arm == "candidate":
        cmd = _cmd(
            OUT / "candidate",
            ["-v", "rsi_min_dist_to_52w_high_pct_at_trigger=7.18"],
        )
    elif arm in ("atr0_nodist", "atr0-nodist", "atr0"):
        cmd = _cmd(OUT / "ATR0_NO_DIST", [], atr="0")
    elif arm in ("atr4_nodist", "atr4-nodist", "atr4"):
        cmd = _cmd(OUT / "ATR4_NO_DIST", [], atr="4")
    elif arm in ("atr3_nodist", "atr3-nodist", "atr3"):
        cmd = _cmd(OUT / "ATR3_NO_DIST", [], atr="3")
    else:
        print(
            "usage: rsi_mindist52_718_run_ab_20260916.py "
            "control|candidate|atr0_nodist|atr4_nodist|atr3_nodist",
            file=sys.stderr,
        )
        return 2
    print("[rsi mindist] " + " ".join(cmd[:12]) + " ...", flush=True)
    return subprocess.call(cmd, cwd=str(REPO))


if __name__ == "__main__":
    raise SystemExit(main())
