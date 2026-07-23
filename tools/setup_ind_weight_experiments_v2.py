#!/usr/bin/env python3
"""Set up fair IND ATR/VOL/DIAMOND weight experiment v2.

Fixes v1 failure mode: production weights are ~-0.5, so min_ind_score>0 yields 0 trades.

Method (explicit):
  POSITIVE-BASE weights — all non-target indicator weights set to 0.0; target
  signals (ATR_RATIO / VOL_SURGE / DIAMOND) get positive weights. Thresholds are
  calibrated to empirical quantiles of IND_SCORE under each weight file on
  C0-accepted IND closed triggers (retain ~90/75/50/25% of candidates with
  score computed under that file).

Also reports score distribution under production weights for documentation.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SYS_ANALYSIS = REPO / "stock_analysis"
sys.path.insert(0, str(SYS_ANALYSIS))

from brt_entry_indicators import (  # noqa: E402
    INDICATOR_IDS,
    resolve_default_ind_score_weights_path,
)

EXP_DIR = REPO / "experiments"
OUT_ROOT = REPO / "drive" / "ind_weight_exp_v2"
RETAIN_TARGETS = (0.90, 0.75, 0.50, 0.25)  # fraction of scored triggers retained


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _positive_base(overrides: dict[str, float], description: str) -> dict:
    """All weights 0 except explicit positive overrides."""
    weights = {iid: 0.0 for iid in INDICATOR_IDS}
    for k, v in overrides.items():
        weights[k] = float(v)
    return {
        "description": description,
        "method": "positive_base_zero_elsewhere",
        "experiment_overrides": overrides,
        "weights": weights,
    }


def _score_from_closed(df: pd.DataFrame, weights: dict[str, float]) -> np.ndarray:
    scores = np.zeros(len(df), dtype=np.float64)
    for iid in INDICATOR_IDS:
        col = f"IND_{iid}"
        if col not in df.columns:
            continue
        bull = df[col].astype(str).str.upper().eq("BULL").to_numpy()
        scores += bull.astype(np.float64) * float(weights.get(iid, 0.0))
    return scores


def _find_c0_closed() -> Path:
    c0 = REPO / "drive" / "ind_weight_exp" / "C0"
    if c0.is_dir():
        files = sorted(c0.glob("IND_Closed_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    latest = REPO / "drive" / "IND_LatestRun_Closed.csv"
    if latest.is_file():
        return latest
    raise FileNotFoundError("No IND Closed CSV found for score calibration")


def _quantile_threshold(scores: np.ndarray, retain_frac: float) -> float:
    """Threshold such that ~retain_frac of scores are >= threshold."""
    if scores.size == 0:
        return -1e9
    # retain 90% => threshold at 10th percentile
    q = 100.0 * (1.0 - retain_frac)
    return float(np.percentile(scores, q))


def main() -> int:
    src = resolve_default_ind_score_weights_path()
    if src is None or not Path(src).is_file():
        print("ERROR: could not resolve default ind_score_weights path", file=sys.stderr)
        return 1
    src = Path(src)
    prod = _load(src)
    prod_w = {k: float(v) for k, v in prod.get("weights", {}).items()}

    closed_path = _find_c0_closed()
    closed = pd.read_csv(closed_path, low_memory=False)
    print(f"calibration_closed={closed_path} n={len(closed)}")
    print(f"control_source={src}")

    # Score distributions
    prod_scores = _score_from_closed(closed, prod_w)
    dist = {
        "n": int(len(prod_scores)),
        "production_weights": {
            "min": float(np.min(prod_scores)),
            "p10": float(np.percentile(prod_scores, 10)),
            "p25": float(np.percentile(prod_scores, 25)),
            "p50": float(np.percentile(prod_scores, 50)),
            "p75": float(np.percentile(prod_scores, 75)),
            "p90": float(np.percentile(prod_scores, 90)),
            "max": float(np.max(prod_scores)),
            "frac_gt_0": float(np.mean(prod_scores > 0)),
            "frac_gt_0_5": float(np.mean(prod_scores > 0.5)),
            "frac_gt_1": float(np.mean(prod_scores > 1.0)),
        },
    }

    EXP_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Production control copy
    c0 = deepcopy(prod)
    c0["description"] = f"v2 C0 production control copy of {src.name}"
    c0["control_source"] = str(src)
    c0["method"] = "production_correlation_weights"
    _dump(EXP_DIR / "ind_weights_v2_C0.json", c0)

    # Positive-base variants
    variants = {
        "ind_weights_v2_W1.json": (
            {"ATR_RATIO": 0.50, "VOL_SURGE": 0.25, "DIAMOND": 0.50},
            "v2 W1 positive-base: ATR=0.50 VOL=0.25 DIAMOND=0.50 (others 0)",
        ),
        "ind_weights_v2_W2.json": (
            {"ATR_RATIO": 1.25, "VOL_SURGE": 0.75, "DIAMOND": 1.50},
            "v2 W2 positive-base: ATR=1.25 VOL=0.75 DIAMOND=1.50 (others 0)",
        ),
        "ind_weights_v2_A1_ATR.json": (
            {"ATR_RATIO": 1.25},
            "v2 A1 positive-base ATR_RATIO=1.25 only",
        ),
        "ind_weights_v2_A2_VOL.json": (
            {"VOL_SURGE": 0.75},
            "v2 A2 positive-base VOL_SURGE=0.75 only",
        ),
        "ind_weights_v2_A3_DIAMOND.json": (
            {"DIAMOND": 1.50},
            "v2 A3 positive-base DIAMOND=1.50 only",
        ),
        "ind_weights_v2_ADD.json": (
            {"ATR_RATIO": 1.0, "VOL_SURGE": 1.0, "DIAMOND": 1.0},
            "v2 ADD equal positive-base ATR=VOL=DIAMOND=1.0",
        ),
    }
    variant_scores: dict[str, np.ndarray] = {}
    for name, (ovr, desc) in variants.items():
        payload = _positive_base(ovr, desc)
        _dump(EXP_DIR / name, payload)
        sc = _score_from_closed(closed, payload["weights"])
        variant_scores[name] = sc
        dist[name] = {
            "overrides": ovr,
            "min": float(np.min(sc)),
            "p10": float(np.percentile(sc, 10)),
            "p25": float(np.percentile(sc, 25)),
            "p50": float(np.percentile(sc, 50)),
            "p75": float(np.percentile(sc, 75)),
            "p90": float(np.percentile(sc, 90)),
            "max": float(np.max(sc)),
            "frac_gt_0": float(np.mean(sc > 0)),
            "mean": float(np.mean(sc)),
        }

    # Pair mandatory files (reuse if present, else write)
    pairs = {
        "mandatory_ATR_VOL.json": {
            "description": "Pair gate: require ATR_RATIO and VOL_SURGE BULL at trigger",
            "rules": {"ATR_RATIO": "BULL", "VOL_SURGE": "BULL"},
        },
        "mandatory_ATR_DIAMOND.json": {
            "description": "Pair gate: require ATR_RATIO and DIAMOND BULL at trigger",
            "rules": {"ATR_RATIO": "BULL", "DIAMOND": "BULL"},
        },
        "mandatory_VOL_DIAMOND.json": {
            "description": "Pair gate: require VOL_SURGE and DIAMOND BULL at trigger",
            "rules": {"VOL_SURGE": "BULL", "DIAMOND": "BULL"},
        },
        "mandatory_ATR_only.json": {
            "description": "Single gate: require ATR_RATIO BULL",
            "rules": {"ATR_RATIO": "BULL"},
        },
        "mandatory_VOL_only.json": {
            "description": "Single gate: require VOL_SURGE BULL",
            "rules": {"VOL_SURGE": "BULL"},
        },
        "mandatory_DIAMOND_only.json": {
            "description": "Single gate: require DIAMOND BULL",
            "rules": {"DIAMOND": "BULL"},
        },
    }
    for name, payload in pairs.items():
        _dump(EXP_DIR / name, payload)

    def thr(weight_file: str, retain: float) -> float:
        """Engine activates min_ind_score only when value > 0; bump 0 -> epsilon."""
        sc = variant_scores[weight_file]
        t = _quantile_threshold(sc, retain)
        # Discrete positive-base scores often have mass at 0; epsilon means "any target BULL".
        if t <= 0:
            return 1e-6
        return round(float(t), 4)

    # C1: positive-base W1 requiring any target BULL (engine cannot gate on negative prod scores)
    c1_thr = 1e-6

    candidates = [
        {
            "id": "C0",
            "label": "production control (score gate off)",
            "weights": "ind_weights_v2_C0.json",
            "min_ind_score": -2,
            "mandatory": None,
            "retain_target": None,
        },
        {
            "id": "C1",
            "label": (
                "W1 positive-base any-target BULL (min_ind_score=1e-6); "
                "prod weights cannot activate score gate (all scores < 0; engine requires thr>0)"
            ),
            "weights": "ind_weights_v2_W1.json",
            "min_ind_score": c1_thr,
            "mandatory": None,
            "retain_target": 0.72,
        },
        # W1 ladder
        {
            "id": "W1_ANY",
            "label": "W1 positive-base any target BULL (eps)",
            "weights": "ind_weights_v2_W1.json",
            "min_ind_score": thr("ind_weights_v2_W1.json", 0.90),
            "mandatory": None,
            "retain_target": 0.90,
        },
        {
            "id": "W1_R50",
            "label": "W1 positive-base retain~50% (score>=0.5)",
            "weights": "ind_weights_v2_W1.json",
            "min_ind_score": thr("ind_weights_v2_W1.json", 0.50),
            "mandatory": None,
            "retain_target": 0.50,
        },
        {
            "id": "W1_R25",
            "label": "W1 positive-base retain~25% / high score",
            "weights": "ind_weights_v2_W1.json",
            "min_ind_score": thr("ind_weights_v2_W1.json", 0.25),
            "mandatory": None,
            "retain_target": 0.25,
        },
        # W2 ladder
        {
            "id": "W2_ANY",
            "label": "W2 positive-base any target BULL (eps)",
            "weights": "ind_weights_v2_W2.json",
            "min_ind_score": thr("ind_weights_v2_W2.json", 0.90),
            "mandatory": None,
            "retain_target": 0.90,
        },
        {
            "id": "W2_R50",
            "label": "W2 positive-base retain~50%",
            "weights": "ind_weights_v2_W2.json",
            "min_ind_score": thr("ind_weights_v2_W2.json", 0.50),
            "mandatory": None,
            "retain_target": 0.50,
        },
        {
            "id": "W2_R25",
            "label": "W2 positive-base retain~25%",
            "weights": "ind_weights_v2_W2.json",
            "min_ind_score": thr("ind_weights_v2_W2.json", 0.25),
            "mandatory": None,
            "retain_target": 0.25,
        },
        # Ablations: require the single target BULL (score >= weight)
        {
            "id": "A1_ATR",
            "label": "A1 ATR-only BULL required (score>=1.25)",
            "weights": "ind_weights_v2_A1_ATR.json",
            "min_ind_score": 1.25,
            "mandatory": None,
            "retain_target": None,
        },
        {
            "id": "A2_VOL",
            "label": "A2 VOL-only BULL required (score>=0.75)",
            "weights": "ind_weights_v2_A2_VOL.json",
            "min_ind_score": 0.75,
            "mandatory": None,
            "retain_target": None,
        },
        {
            "id": "A3_DIAMOND",
            "label": "A3 DIAMOND-only BULL required (score>=1.50)",
            "weights": "ind_weights_v2_A3_DIAMOND.json",
            "min_ind_score": 1.50,
            "mandatory": None,
            "retain_target": None,
        },
        {
            "id": "ADD_R50",
            "label": "equal additive retain~50%",
            "weights": "ind_weights_v2_ADD.json",
            "min_ind_score": thr("ind_weights_v2_ADD.json", 0.50),
            "mandatory": None,
            "retain_target": 0.50,
        },
        {
            "id": "ADD_ANY",
            "label": "equal additive any target BULL",
            "weights": "ind_weights_v2_ADD.json",
            "min_ind_score": 1e-6,
            "mandatory": None,
            "retain_target": 0.90,
        },
        # Pair-aware (score off, production DIFF gate still applies via COMMON_V)
        {
            "id": "P_ATR_VOL",
            "label": "pair gate ATR+VOL BULL (score off)",
            "weights": "ind_weights_v2_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_ATR_VOL.json",
            "retain_target": None,
        },
        {
            "id": "P_ATR_DIAMOND",
            "label": "pair gate ATR+DIAMOND BULL (score off)",
            "weights": "ind_weights_v2_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_ATR_DIAMOND.json",
            "retain_target": None,
        },
        {
            "id": "P_VOL_DIAMOND",
            "label": "pair gate VOL+DIAMOND BULL (score off)",
            "weights": "ind_weights_v2_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_VOL_DIAMOND.json",
            "retain_target": None,
        },
        # Soft single signal gates (score off)
        {
            "id": "G_ATR",
            "label": "mandatory ATR_RATIO BULL only",
            "weights": "ind_weights_v2_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_ATR_only.json",
            "retain_target": None,
        },
        {
            "id": "G_VOL",
            "label": "mandatory VOL_SURGE BULL only",
            "weights": "ind_weights_v2_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_VOL_only.json",
            "retain_target": None,
        },
        {
            "id": "G_DIAMOND",
            "label": "mandatory DIAMOND BULL only",
            "weights": "ind_weights_v2_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_DIAMOND_only.json",
            "retain_target": None,
        },
    ]

    # Annotate calibrated thresholds onto candidates for transparency
    for c in candidates:
        wf = c["weights"]
        if c.get("retain_target") and wf in variant_scores:
            sc = variant_scores[wf]
            c["calibrated_on_n"] = int(len(sc))
            c["score_p50_under_weights"] = float(np.percentile(sc, 50))
        elif c["id"] == "C1":
            c["calibrated_on_n"] = int(len(prod_scores))
            c["score_p50_under_weights"] = float(np.percentile(prod_scores, 50))

    manifest = {
        "method": (
            "positive_base_zero_elsewhere + empirical quantile thresholds on C0-accepted "
            "IND closed triggers; C0/C1 use production correlation weights"
        ),
        "control_source": str(src),
        "calibration_closed": str(closed_path),
        "score_distributions": dist,
        "experiments_dir": str(EXP_DIR),
        "output_root": str(OUT_ROOT),
        "concurrency": 3,
        "workers_per_job": 10,
        "hard_gates": {"min_trades": 350, "max_dd_pct": 22.0},
        "candidates": candidates,
    }
    _dump(EXP_DIR / "ind_weight_exp_v2_manifest.json", manifest)
    _dump(OUT_ROOT / "score_calibration.json", dist)

    # Human-readable calibration note
    cal_md = [
        "# IND Weight Exp v2 — Score Calibration",
        "",
        f"Calibration trades: `{closed_path}` (n={len(closed)})",
        f"Production weights: `{src.name}`",
        "",
        "## Method",
        "",
        "1. **Positive-base** treatment weights: all indicators 0 except ATR_RATIO / "
        "VOL_SURGE / DIAMOND (as specified).",
        "2. Compute IND_SCORE on each C0-accepted closed trigger under that weight file.",
        "3. Set `min_ind_score` to the empirical quantile that retains ~90/75/50% of those scores.",
        "4. **C0**: production weights, `min_ind_score=-2` (off).",
        f"5. **C1**: W1 positive-base with `min_ind_score={c1_thr}` (any ATR/VOL/DIAMOND BULL).",
        "6. Engine rule: `min_ind_score` filter is **active only when thr > 0**; "
        "thresholds of 0 are replaced with `1e-6`. Production correlation scores are "
        "entirely negative, so they cannot activate this gate.",
        "",
        "## Production score distribution (why v1 failed)",
        "",
        f"- min/p50/max = {dist['production_weights']['min']:.3f} / "
        f"{dist['production_weights']['p50']:.3f} / {dist['production_weights']['max']:.3f}",
        f"- fraction score > 0: {100*dist['production_weights']['frac_gt_0']:.1f}%",
        f"- fraction score > 0.5: {100*dist['production_weights']['frac_gt_0_5']:.1f}%",
        f"- fraction score > 1.0: {100*dist['production_weights']['frac_gt_1']:.1f}%",
        "",
        "## Candidate thresholds",
        "",
        "| id | weights | min_ind_score | retain_target |",
        "|----|---------|--------------:|--------------:|",
    ]
    for c in candidates:
        cal_md.append(
            f"| {c['id']} | {c['weights']} | {c['min_ind_score']} | {c.get('retain_target')} |"
        )
    (OUT_ROOT / "score_calibration.md").write_text("\n".join(cal_md) + "\n", encoding="utf-8")

    print(f"wrote {len(candidates)} candidates -> {EXP_DIR / 'ind_weight_exp_v2_manifest.json'}")
    print(f"calibration -> {OUT_ROOT / 'score_calibration.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
