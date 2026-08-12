#!/usr/bin/env python3
"""SPY SHORT TC Weak lag-1 A/B for BRT, WPBR, YH, MTS, RL, RS.

Arms (GRID_PLAN / exit-only preference):
  baseline       — production defaults, no SPY weak filter
  no_entry_weak  — spy_tc_weak_horizon=short, spy_int_tc_lag=1,
                   block_entries_when_spy_int_weak=true
  exit_on_weak   — spy_tc_weak_horizon=short, spy_int_tc_lag=1,
                   exit_when_spy_int_turns_weak=true  (exit-only; no block)

Out: drive/davey_experiments/spy_tc_weak_system_ab/short/
     partial_all_short.csv + <SYSTEM>/{baseline,no_entry_weak,exit_on_weak}/
"""
from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_ROWS_LOCK = threading.Lock()

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
OUT_ROOT = REPO / "drive" / "davey_experiments" / "spy_tc_weak_system_ab" / "short"
DATA_DIR = REPO / "data" / "newdata" / "data"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
IND_WEIGHTS = SA / "ind_score_weights_260609152353.json"
YH_SYMBOLS_FILE = (
    REPO / "drive" / "davey_experiments" / "spy_int_weak_system_ab" / "YH" / "YH_SYMBOLS.txt"
)

HORIZON = "short"
ARM_ORDER = ["baseline", "no_entry_weak", "exit_on_weak"]

SHORT_ARMS: list[tuple[str, list[str]]] = [
    ("baseline", []),
    (
        "no_entry_weak",
        [
            "spy_tc_weak_horizon=short",
            "spy_int_tc_lag=1",
            "block_entries_when_spy_int_weak=true",
            "exit_when_spy_int_turns_weak=false",
        ],
    ),
    (
        # GRID_PLAN: exit-only (entries still allowed while Weak).
        "exit_on_weak",
        [
            "spy_tc_weak_horizon=short",
            "spy_int_tc_lag=1",
            "exit_when_spy_int_turns_weak=true",
        ],
    ),
]


def _py() -> str:
    env = os.environ.get("PY", "").strip()
    if env and Path(env).is_file():
        return env
    for c in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python311/python.exe",
    ):
        if c.is_file():
            return str(c)
    return sys.executable


def _safe_num(x: Any) -> float:
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _parse_bat_symbols(bat_name: str, var_name: str) -> str:
    env = os.environ.get(var_name, "").strip()
    if env:
        return env
    bat = (REPO / bat_name).read_text(encoding="utf-8", errors="replace")
    m = re.search(rf'set "{var_name}=([^"]+)"', bat)
    if not m:
        raise RuntimeError(f"Could not parse {var_name} from {bat_name}")
    return m.group(1).strip()


def _yh_symbols() -> str:
    env = os.environ.get("YH_SYMBOLS", "").strip()
    if env:
        return env
    if YH_SYMBOLS_FILE.is_file():
        return YH_SYMBOLS_FILE.read_text(encoding="utf-8").strip()
    return _parse_bat_symbols("run_yh.bat", "YH_SYMBOLS")


BRT_SYMBOLS = (
    "AAPL,ABBV,ACN,ADBE,ADI,AMAT,AMD,AMZN,AU,AVGO,BABA,BAC,CDNS,CI,CRM,CRWD,"
    "GOOG,GOOGL,HD,JPM,KR,LYV,META,MPC,MSFT,MU,NEM,NFLX,NVDA,ORCL,PFE,PG,"
    "PPTA,SHOP,TMUS,TSLA,TSM,UNH,V,WFC,WMT,XOM"
)
WPBR_SYMBOLS = "AAPL,AMD,AMZN,AU,META,MSFT,NVDA,NFLX,GOOGL,TSLA"
MTS_SYMBOLS = (
    "AAON,ABCB,ABG,ACA,ACU,ALG,AMD,AMN,APP,ARES,,AU,BBW,BELFA,BWLP,CF,CHCI,"
    "CIEN,CLS,CMC,COHR,COKE,CRS,CRWD,CSTM,CVCO,DDS,DECK,DKL,DKS,DXCM,DY,ENVA,ESP,"
    "EVR,FEIM,FN,FRD,FTAI,HWKN,IBP,IESC,IR,JOE,LMAT,LOGI,LRCX,LUGDF,LULU,MATX,MOD,"
    "MPWR,MTSI,MTZ,MYRG,NEO,NGL,NTAP,NVDA,NVMI,NXPI,OR,PFSI,PLUS,POOL,POWL,PTC,QXO,"
    "RMBS,SANM,SCCO,SGI,SHOP,SIMO,SKYW,TATT,TBBK,TER,TOELY,TPH,TRT,TWLO,UHS,URI,"
    "UTI,VSEC,WDAY,WOR,XPO"
)

BRT_BASE_V = [
    "stop_pct=0.934",
    "target_pct=1.21",
    "too_high_multiplier=0",
    "band_pct=0.0154",
    "strong_pre_pivot_pct=0.081",
    "strong_post_pivot_pct=0.108",
    "strong_pre_pivot_bars=7",
    "strong_post_pivot_bars=7",
    "breakout_bars=100",
    "tight_range_threshold_pct=0.35",
    "tight_range_lookback=105",
    "sheet_breakout_scan_start_row_delta=2",
    "brt_sheet_touch=true",
    "min_spy_compare_1y_at_trigger=-1000",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=true",
    "brt_zones=true",
    "yh_zones=false",
    "min_pivot_run_h_before_entry=0",
    "min_beta_at_trigger=0",
]
WPBR_BASE_V = [
    "wpbr_zones=true",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "band_pct=0.015",
    "strong_pre_pivot_bars=3",
    "strong_pre_pivot_pct=0.10",
    "strong_post_pivot_bars=3",
    "strong_post_pivot_pct=0.10",
    "strong_pivot_mode=either",
    "wpbr_breakout_confirmation=0.03",
    "wpbr_max_days_after_retest=2",
    "wpbr_second_chance_after_win=true",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=-1000",
    "ind_score_weights_path=",
    "too_high_multiplier=0",
    "target_pct=1.22",
    "stop_pct=0.91",
    "start_date=2016-01-01",
    "sheet_no_entry_same_bar_after_exit=false",
    "use_indicators=true",
]
YH_BASE_V = [
    "yh_zones=true",
    "brt_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "band_pct=0.0099",
    "yh_move_away_pct=0.031",
    "yh_lookback=252",
    "yh_memory_mode=sheet",
    "strong_pre_pivot_bars=7",
    "strong_pre_pivot_pct=0.12",
    "strong_post_pivot_bars=7",
    "strong_post_pivot_pct=0.109",
    "strong_pivot_mode=both",
    "target_pct=1.27",
    "stop_pct=0.923",
    "stop_pct_is_multiplier=true",
    "too_high_multiplier=1.04",
    "min_spy_compare_1y_at_trigger=97.5",
    "max_spy_compare_1y_at_trigger=0",
    "min_atr_pct_at_trigger=0",
    "max_atr_pct_at_trigger=0",
    "growth_filter_enabled=true",
    "growth_bars=756",
    "use_indicators=false",
    "indicator_buy=off",
    f"ind_score_weights_path={IND_WEIGHTS.as_posix()}",
    "min_ind_score=0",
    "indicator_diff=10",
    "symbol_reentry_cooldown_days=20",
]
MTS_BASE_V = [
    "band_pct=0.018",
    "touch_threshold=2",
    "strong_post_pivot_bars=7",
    "strong_post_pivot_pct=0.06",
    "strong_pre_pivot_bars=7",
    "strong_pre_pivot_pct=0.12",
    "target_pct=1.22",
    "stop_pct=0.934",
    "stop_pct_is_multiplier=true",
    "stop_loss_based=trigger_low",
    "min_upper_wick_atr_at_trigger=0.25",
    "min_dist_to_52w_high_pct_at_trigger=25",
]
RL_BASE_V = [
    "rl_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "indicator_buy=off",
]
RS_BASE_V = [
    "rs_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "target_pct=1.25",
    "stop_pct=0.88",
    "stop_pct_is_multiplier=true",
    "use_indicators=true",
    "indicator_buy=off",
    "rs_require_tc_strong=true",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=0",
    "too_high_multiplier=0",
    "rs_max_pct_below_52w_high=0",
    "rs_spy_int_tc_not_weak=false",
]

REPORT_GLOBS: dict[str, tuple[str, ...]] = {
    "BRT": ("BRT_Report_*.csv", "BRT_Audit_Report_*.csv"),
    "WPBR": (
        "WPBR_Report_*.csv",
        "WPBR_Summary_*.csv",
        "BRT_Report_*.csv",
        "BRT_Audit_Report_*.csv",
    ),
    "YH": ("YH_Report_*.csv", "YH_Audit_Report_*.csv"),
    "MTS": ("MTS_Report_*.csv", "BRT_Report_*.csv", "BRT_Audit_Report_*.csv"),
    "RL": ("RL_Report_*.csv", "RL_Audit_Report_*.csv"),
    "RS": ("RS_Report_*.csv", "RS_Audit_Report_*.csv", "BRT_Report_*.csv"),
}


def extract_metrics(system: str, outdir: Path) -> Optional[dict]:
    report = None
    for pat in REPORT_GLOBS[system]:
        report = _find_latest(outdir, pat)
        if report is not None:
            break
    if report is None:
        return None
    with open(report, newline="", encoding="utf-8", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    wins = int(_safe_num(row.get("Wins", 0)))
    losses = int(_safe_num(row.get("Losses", 0)))
    bes = int(_safe_num(row.get("BE", row.get("BEs", 0))))
    total_trades = int(_safe_num(row.get("Total_Trades", 0)))
    if total_trades <= 0:
        total_trades = wins + losses + bes
    wr = (100.0 * wins / total_trades) if total_trades else 0.0
    if "Pct_Wins" in row and row.get("Pct_Wins") not in (None, ""):
        wr = _safe_num(row.get("Pct_Wins"))
    return {
        "report": str(report.name),
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "be": bes,
        "wr": wr,
        "pf": _safe_num(row.get("Profit_Factor", 0)),
        "pnl": _safe_num(row.get("Total_PNL", 0)),
        "maxdd": _safe_num(row.get("Max_DD", 0)),
        "expectancy": _safe_num(row.get("Expectancy", row.get("Expectancy_Pct", 0))),
        "ann_ror": _safe_num(row.get("Ann_ROR", 0)),
    }


def build_cmd(system: str, outdir: Path, workers: int, extra_v: list[str]) -> list[str]:
    py = _py()
    cmd = [py, str(SA / "rocket_brt.py"), str(DATA_DIR), "-o", str(outdir), "-w", str(workers)]
    if system == "BRT":
        cmd += ["--no-regression", "--aggressive", "--print-zones", "-s", BRT_SYMBOLS]
        if PER_SYMBOL.is_file():
            cmd += ["--per-symbol-settings", str(PER_SYMBOL)]
        vs = BRT_BASE_V
    elif system == "WPBR":
        cmd += [
            "--aggressive",
            "--use-duckdb",
            "--no-regression",
            "--print-zones",
            "-s",
            WPBR_SYMBOLS,
        ]
        vs = WPBR_BASE_V
    elif system == "YH":
        cmd += ["--aggressive", "--use-duckdb", "--no-regression", "-s", _yh_symbols()]
        vs = YH_BASE_V
    elif system == "MTS":
        cmd += [
            "--no-regression",
            "--mts-sheet-parity",
            "--symbol-reentry-cooldown-days",
            "20",
            "-s",
            MTS_SYMBOLS,
        ]
        vs = MTS_BASE_V
    elif system == "RL":
        cmd += [
            "--no-regression",
            "-s",
            _parse_bat_symbols("run_rl.bat", "RL_SYMBOLS"),
        ]
        if PER_SYMBOL.is_file():
            cmd += ["--per-symbol-settings", str(PER_SYMBOL)]
        vs = RL_BASE_V
    elif system == "RS":
        cmd += [
            "--no-regression",
            "--aggressive",
            "--relative-strength",
            "-s",
            _parse_bat_symbols("run_rs.bat", "RS_SYMBOLS"),
        ]
        vs = RS_BASE_V
    else:
        raise ValueError(system)
    for v in vs + extra_v:
        cmd.extend(["-v", v])
    return cmd


def default_workers(system: str) -> int:
    env_key = f"{system}_WORKERS"
    if os.environ.get(env_key, "").strip():
        return int(os.environ[env_key])
    return {"BRT": 16, "WPBR": 10, "YH": 24, "MTS": 24, "RL": 5, "RS": 11}[system]


def write_partial_all(rows: list[dict]) -> Path:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUT_ROOT / "partial_all_short.csv"
    fields = [
        "horizon",
        "system",
        "arm",
        "trades",
        "wr",
        "pf",
        "pnl",
        "maxdd",
        "expectancy",
        "ann_ror",
        "wins",
        "losses",
        "be",
        "exit_code",
        "elapsed_s",
        "report",
        "extra_v",
        "note",
    ]
    ordered = sorted(
        rows,
        key=lambda r: (
            ["BRT", "WPBR", "YH", "MTS", "RL", "RS"].index(r["system"])
            if r["system"] in ("BRT", "WPBR", "YH", "MTS", "RL", "RS")
            else 99,
            ARM_ORDER.index(r["arm"]) if r["arm"] in ARM_ORDER else 99,
        ),
    )
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in ordered:
            w.writerow(r)
    print(f"[partial_all] wrote {path} ({len(ordered)} rows)", flush=True)
    return path


def write_system_partial(system: str, rows: list[dict]) -> None:
    sys_dir = OUT_ROOT / system
    sys_dir.mkdir(parents=True, exist_ok=True)
    path = sys_dir / f"partial_{system}.csv"
    fields = [
        "system",
        "arm",
        "trades",
        "wr",
        "pf",
        "pnl",
        "maxdd",
        "expectancy",
        "ann_ror",
        "wins",
        "losses",
        "exit_code",
        "elapsed_s",
        "report",
        "extra_v",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    md = [
        f"# {system} — SPY SHORT TC Weak lag-1 A/B",
        "",
        "Horizon=`short` → SPY `IND_TC_SHORT_OUTLOOK`. Lag-1 on trigger bar; exit-only arm does not block.",
        "",
        "| Arm | Trades | WR% | PF | PNL | MaxDD | Expectancy |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md.append(
            f"| {r.get('arm')} | {r.get('trades', '')} | {float(r.get('wr') or 0):.2f} | "
            f"{float(r.get('pf') or 0):.2f} | {float(r.get('pnl') or 0):,.2f} | "
            f"{float(r.get('maxdd') or 0):.2f} | {float(r.get('expectancy') or 0):,.2f} |"
        )
    md.append("")
    (sys_dir / "RESULTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def run_arm(system: str, label: str, extra_v: list[str], workers: int) -> dict:
    outdir = OUT_ROOT / system / label
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = build_cmd(system, outdir, workers, extra_v)
    log_path = outdir / "run.log"
    print(f"[{system}/{label}] START w={workers}", flush=True)
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - t0
    metrics = extract_metrics(system, outdir) or {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "be": 0,
        "wr": 0.0,
        "pf": 0.0,
        "pnl": 0.0,
        "maxdd": 0.0,
        "expectancy": 0.0,
        "ann_ror": 0.0,
        "report": "",
    }
    row = {
        "horizon": HORIZON,
        "system": system,
        "arm": label,
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        "extra_v": ";".join(extra_v),
        "note": "" if proc.returncode == 0 else f"rc={proc.returncode} see {log_path.name}",
        **metrics,
    }
    print(
        f"[{system}/{label}] DONE rc={proc.returncode} {elapsed:.0f}s "
        f"trades={row.get('trades')} WR={row.get('wr')} PF={row.get('pf')} "
        f"PNL={row.get('pnl')} MaxDD={row.get('maxdd')}",
        flush=True,
    )
    return row


def run_system(system: str, all_rows: list[dict]) -> list[dict]:
    workers = default_workers(system)
    only = os.environ.get(f"{system}_ARM", os.environ.get("ARM", "")).strip()
    sys_rows: list[dict] = []
    for label, extra in SHORT_ARMS:
        if only and label != only:
            continue
        row = run_arm(system, label, extra, workers)
        sys_rows.append(row)
        with _ROWS_LOCK:
            all_rows.append(row)
            write_system_partial(system, sys_rows)
            write_partial_all(all_rows)
    return sys_rows


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    systems_env = os.environ.get("SYSTEMS", "BRT,WPBR,YH,MTS,RL,RS").strip()
    systems = [s.strip().upper() for s in systems_env.split(",") if s.strip()]
    # Default: 2 systems concurrently (YH/MTS are heavy); override with SYSTEM_JOBS.
    jobs = int(os.environ.get("SYSTEM_JOBS", "2"))
    (OUT_ROOT / "NOTES.md").write_text(
        "\n".join(
            [
                "# SPY SHORT TC Weak lag-1 system A/B",
                "",
                f"- Started: {datetime.now().isoformat(timespec='seconds')}",
                "- Flags: `spy_tc_weak_horizon=short`, `spy_int_tc_lag=1`,",
                "  `block_entries_when_spy_int_weak`, `exit_when_spy_int_turns_weak`.",
                "- Arms: baseline / no_entry_weak / exit_on_weak (exit-only).",
                "- Production defaults from run_brt/wpbr/yh/mts/rl/rs.bat.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"systems={systems} parallel_jobs={jobs} out={OUT_ROOT}", flush=True)
    all_rows: list[dict] = []
    # Prefer lighter systems first so partial CSV fills sooner.
    order = [s for s in ("RL", "WPBR", "RS", "BRT", "MTS", "YH") if s in systems]
    for s in systems:
        if s not in order:
            order.append(s)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {ex.submit(run_system, s, all_rows): s for s in order}
        failed = False
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                fut.result()
            except Exception as e:
                failed = True
                print(f"[ERROR] {s}: {e}", flush=True)
                with _ROWS_LOCK:
                    all_rows.append(
                        {
                            "horizon": HORIZON,
                            "system": s,
                            "arm": "ERROR",
                            "trades": 0,
                            "wr": 0,
                            "pf": 0,
                            "pnl": 0,
                            "maxdd": 0,
                            "expectancy": 0,
                            "ann_ror": 0,
                            "wins": 0,
                            "losses": 0,
                            "be": 0,
                            "exit_code": 1,
                            "elapsed_s": 0,
                            "report": "",
                            "extra_v": "",
                            "note": str(e),
                        }
                    )
                    write_partial_all(all_rows)

    write_partial_all(all_rows)
    # Combined RESULTS.md
    lines = [
        "# SPY SHORT TC Weak lag-1 — all systems",
        "",
        "| System | Arm | Trades | WR% | PF | PNL | MaxDD | Expectancy |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(
        all_rows,
        key=lambda x: (
            order.index(x["system"]) if x["system"] in order else 99,
            ARM_ORDER.index(x["arm"]) if x["arm"] in ARM_ORDER else 99,
        ),
    ):
        lines.append(
            f"| {r.get('system')} | {r.get('arm')} | {r.get('trades', '')} | "
            f"{float(r.get('wr') or 0):.2f} | {float(r.get('pf') or 0):.2f} | "
            f"{float(r.get('pnl') or 0):,.2f} | {float(r.get('maxdd') or 0):.2f} | "
            f"{float(r.get('expectancy') or 0):,.2f} |"
        )
    lines.append("")
    (OUT_ROOT / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((OUT_ROOT / "RESULTS.md").read_text(encoding="utf-8"))
    ok = (not failed) and all(int(r.get("exit_code", 1)) == 0 for r in all_rows if r.get("arm") != "ERROR")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
