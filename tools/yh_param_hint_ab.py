#!/usr/bin/env python3
"""YH ImprovePriority param-hint A/B (band / target / stop).

Hypothesis-test style: one knob per arm, control vs ≤1 suggested alternative
from ImproveHints / ImprovePriority (docs/HYPOTHESIS_TEST.md).

Reads ``drive/{prefix}_ImproveHints_<stamp>.csv`` (or latest), picks the top
``band_pct`` / ``target_pct`` / ``stop_pct`` rows, maps direction → one alt
value against frozen ``run_yh.bat`` baselines, runs control + each one-knob arm
via ``rocket_tbn.py``, writes comparison under
``drive/paul_experiments/yh_param_hint_ab/``.

Usage (repo root)::

  python tools/yh_param_hint_ab.py --stamp 260807080037
  python tools/yh_param_hint_ab.py --stamp 260807080037 --reuse-control
  python tools/yh_param_hint_ab.py --dry-run --stamp 260807080037
  run_yh_param_hint_ab.bat
  run_yh_param_hint_ab.bat 260807080037
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
DATA_DIR = REPO / "data" / "newdata" / "data"
DRIVE = REPO / "drive"
DEFAULT_OUT = DRIVE / "paul_experiments" / "yh_param_hint_ab"

# Frozen production baselines matching run_yh.bat (do not edit run_yh.bat here).
YH_BASELINE: dict[str, float] = {
    "band_pct": 0.015,
    "target_pct": 1.21,
    "stop_pct": 0.934,
}

# One modest step per direction (not a grid). stop_pct is multiplier:
# lower = wider (expand). Values align with prior YH low-diff experiment deltas.
YH_ALT: dict[tuple[str, str], float] = {
    ("stop_pct", "expand"): 0.923,
    ("stop_pct", "loosen"): 0.923,
    ("stop_pct", "widen"): 0.923,
    ("stop_pct", "contract"): 0.945,
    ("stop_pct", "tighten"): 0.945,
    ("target_pct", "expand"): 1.27,
    ("target_pct", "contract"): 1.15,
    ("band_pct", "tighten"): 0.010,
    ("band_pct", "loosen"): 0.020,
    ("band_pct", "expand"): 0.020,
}

YH_COMMON_V = [
    "yh_zones=true",
    "brt_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "band_pct=0.015",
    "yh_move_away_pct=0.03",
    "yh_lookback=252",
    "yh_memory_mode=sheet",
    "strong_pre_pivot_bars=7",
    "strong_pre_pivot_pct=0.12",
    "strong_post_pivot_bars=7",
    "strong_post_pivot_pct=0.109",
    "strong_pivot_mode=off",
    "target_pct=1.21",
    "stop_pct=0.934",
    "stop_pct_is_multiplier=true",
    "stop_compare_round_decimals=-1",
    "too_high_multiplier=0",
    "max_spy_compare_1y_at_trigger=0",
    "min_spy_compare_1y_at_trigger=0",
    "min_atr_pct_at_trigger=0",
    "max_atr_pct_at_trigger=0",
    "max_market_cap=0",
    "min_market_cap=0",
    "growth_filter_enabled=true",
    "growth_bars=756",
    "use_indicators=false",
    "indicator_buy=off",
    'ind_score_weights_path=""',
    "min_ind_score=0",
]

PARAM_KEYS = ("stop_pct", "target_pct", "band_pct")

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


@dataclass
class HintArm:
    arm_id: str
    hypothesis_id: str
    param: str
    direction: str
    confidence: str
    baseline: float
    alt_value: Optional[float]
    suggestion: str
    is_control: bool = False

    @property
    def knob_v(self) -> Optional[str]:
        if self.is_control or self.alt_value is None:
            return None
        return f"{self.param}={self.alt_value}"


def _resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
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


def _latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def find_hints_csv(stamp: str, prefix: str = "YH") -> Path:
    p = DRIVE / f"{prefix}_ImproveHints_{stamp}.csv"
    if p.is_file():
        return p
    cands = sorted(DRIVE.glob(f"{prefix}_ImproveHints_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not cands:
        raise SystemExit(f"No {prefix}_ImproveHints_*.csv under {DRIVE}")
    return cands[0]


def resolve_stamp(explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()
    for name in ("YH_last_run_ts.txt", "last_run_ts.txt"):
        p = DRIVE / name
        if p.is_file():
            ts = p.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0].strip()
            if ts:
                return ts
    hints = _latest(DRIVE, "YH_ImproveHints_*.csv")
    if hints:
        m = re.search(r"_(\d{12})\.csv$", hints.name)
        if m:
            return m.group(1)
    raise SystemExit("Could not resolve YH stamp (pass --stamp)")


def load_param_hints(hints_csv: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with hints_csv.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            cat = str(r.get("CATEGORY", "")).strip().lower()
            param = str(r.get("PARAM", "")).strip().lower()
            if cat != "param":
                continue
            if param not in PARAM_KEYS:
                continue
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
    # Prefer ImproveHints PRIORITY order; keep first occurrence per param.
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in rows:
        p = str(r.get("PARAM", "")).strip().lower()
        if p in seen:
            continue
        seen.add(p)
        out.append(r)
    return out


def alt_value_for(param: str, direction: str) -> Optional[float]:
    d = (direction or "").strip().lower()
    if d in ("", "hold", "mixed", "adopt"):
        return None
    return YH_ALT.get((param, d))


def build_arms(hints: list[dict[str, str]]) -> list[HintArm]:
    arms: list[HintArm] = [
        HintArm(
            arm_id="00_control",
            hypothesis_id="baseline_run_yh",
            param="(all)",
            direction="hold",
            confidence="n/a",
            baseline=0.0,
            alt_value=None,
            suggestion="Frozen run_yh.bat baselines (band/target/stop).",
            is_control=True,
        )
    ]
    idx = 1
    for h in hints:
        param = str(h.get("PARAM", "")).strip().lower()
        direction = str(h.get("DIRECTION", "")).strip().lower()
        alt = alt_value_for(param, direction)
        hid = str(h.get("HYPOTHESIS_ID", "")).strip() or f"{param}_{direction}"
        base = YH_BASELINE.get(param, 0.0)
        if alt is None:
            # Still surface the card; no runnable alt (hold / unknown).
            arm_id = f"{idx:02d}_{param}_{direction or 'na'}_skip"
            arms.append(
                HintArm(
                    arm_id=arm_id,
                    hypothesis_id=hid,
                    param=param,
                    direction=direction,
                    confidence=str(h.get("CONFIDENCE", "")).strip(),
                    baseline=base,
                    alt_value=None,
                    suggestion=str(h.get("SUGGESTION", "")).strip(),
                )
            )
        else:
            short = direction.replace(" ", "_")[:12]
            arm_id = f"{idx:02d}_{param}_{short}"
            arms.append(
                HintArm(
                    arm_id=arm_id,
                    hypothesis_id=hid,
                    param=param,
                    direction=direction,
                    confidence=str(h.get("CONFIDENCE", "")).strip(),
                    baseline=base,
                    alt_value=alt,
                    suggestion=str(h.get("SUGGESTION", "")).strip(),
                )
            )
        idx += 1
    return arms


def symbols_from_closed(stamp: str, prefix: str = "YH") -> str:
    closed = DRIVE / f"{prefix}_Closed_{stamp}.csv"
    if not closed.is_file():
        # Mag9+AU production list incl. TSLA (stamp 260807080037)
        return "AAPL,AMD,AMZN,AU,GOOGL,META,MSFT,NFLX,NVDA,TSLA"
    syms: list[str] = []
    seen: set[str] = set()
    with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            s = str(r.get("SYMBOL", "")).strip().upper()
            if s and s not in seen:
                seen.add(s)
                syms.append(s)
    return ",".join(syms) if syms else "AAPL,AMD,AMZN,AU,GOOGL,META,MSFT,NFLX,NVDA,TSLA"


def extract_metrics(outdir: Path, prefix: str = "YH") -> Optional[dict[str, Any]]:
    report = _latest(outdir, f"{prefix}_Audit_Report_*.csv") or _latest(outdir, f"{prefix}_Report_*.csv")
    if report is None:
        return None
    with report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    wins = int(_safe_num(row.get("Wins")))
    losses = int(_safe_num(row.get("Losses")))
    bes = int(_safe_num(row.get("BEs", row.get("BE", 0))))
    trades = int(_safe_num(row.get("Total_Trades")))
    if trades <= 0:
        trades = wins + losses + bes
    wr = _safe_num(row.get("Pct_Wins"))
    if wr == 0.0 and trades:
        wr = 100.0 * wins / trades
    stamp = ""
    m = re.search(r"_(\d{12})\.csv$", report.name)
    if m:
        stamp = m.group(1)
    return {
        "ok": True,
        "stamp": stamp,
        "report": report.name,
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "avg_pnl_pct": _safe_num(row.get("Avg_PNL_Pct")),
        "ann_ror": _safe_num(row.get("Ann_ROR")),
        "pnl": _safe_num(row.get("Total_PNL")),
        "max_dd": _safe_num(row.get("Max_DD")),
        "pf": _safe_num(row.get("Profit_Factor")),
        "agg_pnl": _safe_num(row.get("Aggressive_Total_PNL")),
        "agg_dd": _safe_num(row.get("Aggressive_Max_DD")),
    }


def copy_stamp_artifacts(src_dir: Path, dest: Path, stamp: str, prefix: str = "YH") -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in src_dir.glob(f"{prefix}_*_{stamp}.*"):
        if p.is_file():
            shutil.copy2(p, dest / p.name)
            n += 1
    chart = src_dir / f"{prefix}_Charts_{stamp}"
    if chart.is_dir():
        # Skip bulky charts for AB mirrors unless already small.
        pass
    return n


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, override_v: Optional[str]) -> list[str]:
    vs = list(YH_COMMON_V)
    if override_v:
        key = override_v.split("=", 1)[0]
        vs = [v for v in vs if not v.startswith(key + "=")]
        vs.append(override_v)
    cmd = [
        py,
        str(SA / "rocket_tbn.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    for v in vs:
        cmd.extend(["-v", v])
    cmd.extend(["-s", symbols])
    return cmd


def run_arm(
    *,
    py: str,
    arm: HintArm,
    out_root: Path,
    drive_out: Path,
    workers: int,
    symbols: str,
    reuse_control_stamp: str = "",
) -> dict[str, Any]:
    arm_dir = out_root / arm.arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "arm": arm.arm_id,
        "hypothesis_id": arm.hypothesis_id,
        "param": arm.param,
        "direction": arm.direction,
        "confidence": arm.confidence,
        "baseline": arm.baseline,
        "alt_value": arm.alt_value,
        "knob": arm.knob_v or "(none)",
        "suggestion": arm.suggestion,
        "skipped_no_alt": arm.alt_value is None and not arm.is_control,
    }

    if result["skipped_no_alt"]:
        result["ok"] = False
        result["note"] = "direction has no mapped alt (hold/mixed) — not run"
        return result

    if arm.is_control and reuse_control_stamp:
        n = copy_stamp_artifacts(DRIVE, arm_dir, reuse_control_stamp)
        metrics = extract_metrics(arm_dir) or extract_metrics(DRIVE)
        # Prefer drive metrics if copy incomplete
        if metrics is None:
            metrics = extract_metrics(DRIVE)
            if metrics and metrics.get("stamp") == reuse_control_stamp:
                copy_stamp_artifacts(DRIVE, arm_dir, reuse_control_stamp)
        result["ok"] = bool(metrics)
        result["metrics"] = metrics or {}
        result["stamp"] = reuse_control_stamp
        result["elapsed_s"] = 0.0
        result["note"] = f"reused drive stamp {reuse_control_stamp} ({n} files)"
        (arm_dir / "STAMP.txt").write_text(
            f"stamp={reuse_control_stamp}\narm={arm.arm_id}\nextra=(reuse)\nsymbols={symbols}\n",
            encoding="utf-8",
        )
        return result

    # Run into drive/, then mirror stamp into arm folder (same pattern as SB AB bats).
    cmd = build_cmd(py, drive_out, workers, symbols, arm.knob_v)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.time() - t0
    stamp = ""
    ts_file = drive_out / "YH_last_run_ts.txt"
    if ts_file.is_file():
        stamp = ts_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0].strip()
    if not stamp:
        aud = _latest(drive_out, "YH_Audit_Report_*.csv") or _latest(drive_out, "YH_Report_*.csv")
        if aud:
            m = re.search(r"_(\d{12})\.csv$", aud.name)
            if m:
                stamp = m.group(1)
    n_copy = copy_stamp_artifacts(drive_out, arm_dir, stamp) if stamp else 0
    metrics = extract_metrics(arm_dir) if stamp else None
    result["ok"] = proc.returncode == 0 and metrics is not None
    result["exit_code"] = proc.returncode
    result["elapsed_s"] = elapsed
    result["stamp"] = stamp
    result["metrics"] = metrics or {}
    result["note"] = f"copied {n_copy} files" if n_copy else "no mirror"
    (arm_dir / "STAMP.txt").write_text(
        f"stamp={stamp}\narm={arm.arm_id}\nextra={arm.knob_v or ''}\nsymbols={symbols}\n",
        encoding="utf-8",
    )
    if not result["ok"]:
        result["error"] = f"exit={proc.returncode}; see {log_path}"
    return result


def write_comparison(out_root: Path, rows: list[dict[str, Any]], *, stamp_src: str, symbols: str) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    ctrl = next((r for r in rows if r.get("arm") == "00_control"), None)
    cm = (ctrl or {}).get("metrics") or {}

    def delta(r: dict[str, Any], key: str) -> Optional[float]:
        m = r.get("metrics") or {}
        if not ctrl or not cm or not m:
            return None
        if key not in m or key not in cm:
            return None
        return float(m[key]) - float(cm[key])

    # Console
    hdr = (
        f"{'arm':28} {'knob':22} {'trades':>7} {'WR%':>6} {'avg%':>7} "
        f"{'Ann_ROR':>8} {'Total_PNL':>12} {'Max_DD':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        m = r.get("metrics") or {}
        if r.get("skipped_no_alt"):
            print(f"{r['arm']:28} {'(skip)':22}  —")
            continue
        print(
            f"{r['arm']:28} {str(r.get('knob','')):22} "
            f"{int(m.get('trades', 0)):7d} {float(m.get('wr', 0)):6.1f} "
            f"{float(m.get('avg_pnl_pct', 0)):7.2f} {float(m.get('ann_ror', 0)):8.2f} "
            f"{float(m.get('pnl', 0)):12.0f} {float(m.get('max_dd', 0)):7.2f}"
        )

    # Markdown
    md = [
        "# YH param-hint A/B (band / target / stop)",
        "",
        f"Source ImproveHints stamp: `{stamp_src}`. Universe: `{symbols}`.",
        "One knob per arm vs frozen `run_yh.bat` control. Not an optimization grid "
        "(see `docs/HYPOTHESIS_TEST.md`).",
        "",
        "## Arms",
        "",
        "| Arm | Hypothesis | Param | Direction | Knob | Confidence |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| `{r['arm']}` | `{r.get('hypothesis_id','')}` | `{r.get('param','')}` | "
            f"{r.get('direction','')} | `{r.get('knob','')}` | {r.get('confidence','')} |"
        )
    md.extend(
        [
            "",
            "## Results",
            "",
            "Click column headers to sort (HTML). Deltas vs `00_control`.",
            "",
            "| Arm | Stamp | Trades | WR% | Avg% | Ann_ROR | Total_PNL | Max_DD | "
            "Δ Trades | Δ WR | Δ Ann_ROR | Δ PnL | Δ DD |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in rows:
        m = r.get("metrics") or {}
        if r.get("skipped_no_alt") or not m:
            md.append(f"| `{r['arm']}` | — | — | — | — | — | — | — | — | — | — | — | — |")
            continue
        d_tr = delta(r, "trades")
        d_wr = delta(r, "wr")
        d_ror = delta(r, "ann_ror")
        d_pnl = delta(r, "pnl")
        d_dd = delta(r, "max_dd")
        md.append(
            f"| `{r['arm']}` | `{m.get('stamp','')}` | {int(m.get('trades',0))} | "
            f"{float(m.get('wr',0)):.1f} | {float(m.get('avg_pnl_pct',0)):.2f} | "
            f"{float(m.get('ann_ror',0)):.2f} | {float(m.get('pnl',0)):.0f} | "
            f"{float(m.get('max_dd',0)):.2f} | "
            f"{'' if d_tr is None else f'{d_tr:+.0f}'} | "
            f"{'' if d_wr is None else f'{d_wr:+.1f}'} | "
            f"{'' if d_ror is None else f'{d_ror:+.2f}'} | "
            f"{'' if d_pnl is None else f'{d_pnl:+.0f}'} | "
            f"{'' if d_dd is None else f'{d_dd:+.2f}'} |"
        )
    md.extend(
        [
            "",
            "## Re-run",
            "",
            "```bat",
            f"run_yh_param_hint_ab.bat {stamp_src}",
            "python tools\\yh_param_hint_ab.py --stamp " + stamp_src + " --reuse-control",
            "```",
            "",
        ]
    )
    (out_root / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # HTML
    body = []
    for r in rows:
        m = r.get("metrics") or {}
        if r.get("skipped_no_alt") or not m:
            body.append(
                "<tr>"
                f"<td>{html.escape(r['arm'])}</td>"
                f"<td>{html.escape(str(r.get('hypothesis_id','')))}</td>"
                f"<td>{html.escape(str(r.get('knob','')))}</td>"
                "<td colspan='10' class='muted'>skipped / no metrics</td>"
                "</tr>"
            )
            continue
        d_tr = delta(r, "trades")
        d_wr = delta(r, "wr")
        d_ror = delta(r, "ann_ror")
        d_pnl = delta(r, "pnl")
        d_dd = delta(r, "max_dd")

        def fmt(v: Optional[float], nd: int = 1) -> str:
            return "—" if v is None else f"{v:+.{nd}f}"

        body.append(
            "<tr>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td>{html.escape(str(r.get('hypothesis_id','')))}</td>"
            f"<td><code>{html.escape(str(r.get('knob','')))}</code></td>"
            f"<td>{html.escape(str(m.get('stamp','')))}</td>"
            f"<td>{int(m.get('trades',0))}</td>"
            f"<td>{float(m.get('wr',0)):.1f}</td>"
            f"<td>{float(m.get('avg_pnl_pct',0)):.2f}</td>"
            f"<td>{float(m.get('ann_ror',0)):.2f}</td>"
            f"<td>{float(m.get('pnl',0)):.0f}</td>"
            f"<td>{float(m.get('max_dd',0)):.2f}</td>"
            f"<td>{fmt(d_tr, 0)}</td>"
            f"<td>{fmt(d_wr, 1)}</td>"
            f"<td>{fmt(d_ror, 2)}</td>"
            f"<td>{fmt(d_pnl, 0)}</td>"
            f"<td>{fmt(d_dd, 2)}</td>"
            "</tr>"
        )

    thead = (
        "<tr>"
        + sortable_th("Arm", "text")
        + sortable_th("Hypothesis", "text")
        + sortable_th("Knob", "text")
        + sortable_th("Stamp", "text")
        + sortable_th("Trades", "num")
        + sortable_th("WR%", "num")
        + sortable_th("Avg%", "num")
        + sortable_th("Ann_ROR", "num")
        + sortable_th("Total_PNL", "num")
        + sortable_th("Max_DD", "num")
        + sortable_th("Δ Trades", "num")
        + sortable_th("Δ WR", "num")
        + sortable_th("Δ Ann_ROR", "num")
        + sortable_th("Δ PnL", "num")
        + sortable_th("Δ DD", "num")
        + "</tr>"
    )
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>YH param-hint A/B — {html.escape(stamp_src)}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1400px; margin:0 auto; }}
  h1 {{ font-size:1.5rem; }}
  .muted {{ color:#5c5c56; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:6px 8px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  code {{ font-size:12px; }}
  {SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>YH param-hint A/B — source stamp {html.escape(stamp_src)}</h1>
  <p class="muted">Control vs one suggested direction per ImproveHints band/target/stop card.
  One knob frozen otherwise. Click column headers to sort. Judge trade quality / DD —
  not max PnL (<code>docs/HYPOTHESIS_TEST.md</code>).</p>
  <p class="muted">Universe: <code>{html.escape(symbols)}</code>. Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M"))}.</p>
  <table class="sortable"><thead>{thead}</thead><tbody>
  {''.join(body)}
  </tbody></table>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html_path = out_root / "comparison.html"
    html_path.write_text(doc, encoding="utf-8")

    # Machine-readable metrics
    flat_path = out_root / "comparison.csv"
    with flat_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "arm",
                "hypothesis_id",
                "param",
                "direction",
                "knob",
                "stamp",
                "trades",
                "wr",
                "avg_pnl_pct",
                "ann_ror",
                "total_pnl",
                "max_dd",
                "note",
            ],
        )
        w.writeheader()
        for r in rows:
            m = r.get("metrics") or {}
            w.writerow(
                {
                    "arm": r.get("arm"),
                    "hypothesis_id": r.get("hypothesis_id"),
                    "param": r.get("param"),
                    "direction": r.get("direction"),
                    "knob": r.get("knob"),
                    "stamp": m.get("stamp", r.get("stamp", "")),
                    "trades": m.get("trades", ""),
                    "wr": m.get("wr", ""),
                    "avg_pnl_pct": m.get("avg_pnl_pct", ""),
                    "ann_ror": m.get("ann_ror", ""),
                    "total_pnl": m.get("pnl", ""),
                    "max_dd": m.get("max_dd", ""),
                    "note": r.get("note", ""),
                }
            )
    return html_path


def patch_improve_priority(
    stamp: str,
    out_root: Path,
    arms: list[HintArm],
    *,
    prefix: str = "YH",
) -> Optional[Path]:
    """Append / refresh an A/B strip at top of ImprovePriority HTML if present."""
    prio = DRIVE / f"{prefix}_ImprovePriority_{stamp}.html"
    if not prio.is_file():
        return None
    text = prio.read_text(encoding="utf-8", errors="replace")
    rel = os.path.relpath(out_root / "comparison.html", DRIVE).replace("\\", "/")
    bat = f"run_yh_param_hint_ab.bat {stamp}"
    rows = []
    for a in arms:
        if a.is_control:
            continue
        knob = a.knob_v or "(no mapped alt — skip)"
        rows.append(
            f"<tr><td>{html.escape(a.hypothesis_id)}</td>"
            f"<td><code>{html.escape(a.param)}</code></td>"
            f"<td>{html.escape(a.direction)}</td>"
            f"<td><code>{html.escape(knob)}</code></td>"
            f"<td><code>{html.escape(bat)}</code></td></tr>"
        )
    block = f"""
  <div class="ab-strip" style="background:#eef3f8;border:1px solid #c5d0dc;padding:12px 14px;margin:12px 0 8px;border-radius:4px;">
    <strong>Parameter A/B (hypothesis test)</strong>
    <span class="muted"> — one knob, control vs suggested direction.
    Results: <a href="{html.escape(rel)}">comparison.html</a>
    · re-run <code>{html.escape(bat)}</code></span>
    <table class="sortable" style="margin-top:8px"><thead><tr>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Hypothesis<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Param<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Direction<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Alt knob<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Run AB<span class="sort-ind"></span></th>
    </tr></thead><tbody>
    {''.join(rows)}
    </tbody></table>
  </div>
"""
    marker_start = "<!-- YH_PARAM_HINT_AB_START -->"
    marker_end = "<!-- YH_PARAM_HINT_AB_END -->"
    wrapped = f"{marker_start}\n{block}\n{marker_end}"
    if marker_start in text and marker_end in text:
        pre, rest = text.split(marker_start, 1)
        _, post = rest.split(marker_end, 1)
        text = pre + wrapped + post
    else:
        # Insert after opening wrap + h1 block: before first <h2>
        m = re.search(r"(<h2>)", text)
        if m:
            i = m.start()
            text = text[:i] + wrapped + "\n" + text[i:]
        else:
            text = text.replace("<div class=\"wrap\">", "<div class=\"wrap\">\n" + wrapped, 1)
    prio.write_text(text, encoding="utf-8")
    return prio


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", "-t", default="", help="ImproveHints / baseline stamp")
    ap.add_argument("--hints", default="", help="Explicit ImproveHints CSV path")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="A/B output root")
    ap.add_argument("--workers", "-w", type=int, default=16)
    ap.add_argument("--symbols", "-s", default="", help="Override universe")
    ap.add_argument(
        "--reuse-control",
        action="store_true",
        help="Copy existing stamp artifacts into 00_control (skip re-run)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print arms only")
    ap.add_argument("--smoke", action="store_true", help="Control only")
    ap.add_argument(
        "--params",
        default="stop_pct,target_pct,band_pct",
        help="Comma list of params to AB (default: all three)",
    )
    args = ap.parse_args(argv)

    stamp = resolve_stamp(args.stamp)
    hints_csv = Path(args.hints) if args.hints else find_hints_csv(stamp)
    if not hints_csv.is_absolute():
        hints_csv = REPO / hints_csv
    # If hints path stamp differs, prefer filename stamp for reuse.
    m = re.search(r"_(\d{12})\.csv$", hints_csv.name)
    if m and not args.stamp:
        stamp = m.group(1)

    hints = load_param_hints(hints_csv)
    want = {p.strip().lower() for p in args.params.split(",") if p.strip()}
    hints = [h for h in hints if str(h.get("PARAM", "")).strip().lower() in want]
    if not hints:
        raise SystemExit(f"No param hints for {want} in {hints_csv}")

    arms = build_arms(hints)
    symbols = args.symbols.strip() or symbols_from_closed(stamp)
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = REPO / out_root

    print(f"[YH param AB] hints={hints_csv.name} stamp={stamp}")
    print(f"[YH param AB] symbols={symbols}")
    print(f"[YH param AB] out={out_root}")
    for a in arms:
        print(
            f"  {a.arm_id}: {a.hypothesis_id}  "
            f"{a.param} {a.direction} -> {a.knob_v or '(skip/control)'}"
        )

    if args.dry_run:
        return 0

    py = _resolve_python()
    out_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    run_list = arms
    if args.smoke:
        run_list = [a for a in arms if a.is_control]

    for a in run_list:
        print(f"\n=== {a.arm_id} ===")
        if a.is_control and args.reuse_control:
            r = run_arm(
                py=py,
                arm=a,
                out_root=out_root,
                drive_out=DRIVE,
                workers=args.workers,
                symbols=symbols,
                reuse_control_stamp=stamp,
            )
        else:
            r = run_arm(
                py=py,
                arm=a,
                out_root=out_root,
                drive_out=DRIVE,
                workers=args.workers,
                symbols=symbols,
                reuse_control_stamp="",
            )
        results.append(r)
        print(f"  ok={r.get('ok')} stamp={r.get('stamp','')} note={r.get('note','')}")

    # If smoke, still write what we have
    html_path = write_comparison(out_root, results, stamp_src=stamp, symbols=symbols)
    patch_improve_priority(stamp, out_root, arms)
    print(f"\n[YH param AB] Wrote {html_path}")
    print(f"[YH param AB] README {out_root / 'README.md'}")
    return 0 if all(r.get("ok") or r.get("skipped_no_alt") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
