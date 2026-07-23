"""
Set up IND ATR_RATIO / VOL_SURGE / DIAMOND weight experiment files.

Creates:
  experiments/ind_weights_C0.json          (control copy of active defaults)
  experiments/ind_weights_W1.json
  experiments/ind_weights_W2.json
  experiments/ind_weights_A1_ATR.json
  experiments/ind_weights_A2_VOL.json
  experiments/ind_weights_A3_DIAMOND.json
  experiments/mandatory_ATR_VOL.json
  experiments/mandatory_ATR_DIAMOND.json
  experiments/mandatory_VOL_DIAMOND.json
  experiments/ind_weight_exp_manifest.json
"""
from __future__ import annotations

import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYS_ANALYSIS = REPO / "stock_analysis"
sys.path.insert(0, str(SYS_ANALYSIS))

from brt_entry_indicators import resolve_default_ind_score_weights_path  # noqa: E402

EXP_DIR = REPO / "experiments"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _with_weights(base: dict, overrides: dict[str, float], description: str) -> dict:
    out = deepcopy(base)
    w = out.setdefault("weights", {})
    for k, v in overrides.items():
        w[k] = float(v)
    out["description"] = description
    out["experiment_overrides"] = overrides
    return out


def main() -> int:
    src = resolve_default_ind_score_weights_path()
    if src is None or not Path(src).is_file():
        print("ERROR: could not resolve default ind_score_weights path", file=sys.stderr)
        return 1
    src = Path(src)
    base = _load(src)
    w0 = base.get("weights", {})
    print(f"control_source={src}")
    print(
        "control_weights: "
        f"ATR_RATIO={w0.get('ATR_RATIO')} "
        f"VOL_SURGE={w0.get('VOL_SURGE')} "
        f"DIAMOND={w0.get('DIAMOND')}"
    )

    EXP_DIR.mkdir(parents=True, exist_ok=True)
    control_path = EXP_DIR / "ind_weights_C0.json"
    shutil.copy2(src, control_path)
    # Annotate without changing weight values
    c0 = _load(control_path)
    c0["description"] = (
        f"Experiment control copy of {src.name} "
        f"(ATR/VOL/DIAMOND unchanged: "
        f"{w0.get('ATR_RATIO')}/{w0.get('VOL_SURGE')}/{w0.get('DIAMOND')})"
    )
    c0["control_source"] = str(src)
    _dump(control_path, c0)

    variants = {
        "ind_weights_W1.json": (
            {"ATR_RATIO": 0.50, "VOL_SURGE": 0.25, "DIAMOND": 0.50},
            "W1 conservative: ATR=0.50 VOL=0.25 DIAMOND=0.50",
        ),
        "ind_weights_W2.json": (
            {"ATR_RATIO": 1.25, "VOL_SURGE": 0.75, "DIAMOND": 1.50},
            "W2 moderate: ATR=1.25 VOL=0.75 DIAMOND=1.50",
        ),
        "ind_weights_A1_ATR.json": (
            {"ATR_RATIO": 1.25},
            "A1 ablation: ATR_RATIO=1.25 only",
        ),
        "ind_weights_A2_VOL.json": (
            {"VOL_SURGE": 0.75},
            "A2 ablation: VOL_SURGE=0.75 only",
        ),
        "ind_weights_A3_DIAMOND.json": (
            {"DIAMOND": 1.50},
            "A3 ablation: DIAMOND=1.50 only",
        ),
    }
    for name, (ovr, desc) in variants.items():
        _dump(EXP_DIR / name, _with_weights(base, ovr, desc))

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
    }
    for name, payload in pairs.items():
        _dump(EXP_DIR / name, payload)

    # Core matrix (priority set from experiment design)
    candidates = [
        {
            "id": "C0",
            "label": "production control",
            "weights": "ind_weights_C0.json",
            "min_ind_score": -2,
            "mandatory": None,
        },
        {
            "id": "C1",
            "label": "gate-only (current weights)",
            "weights": "ind_weights_C0.json",
            "min_ind_score": 0.5,
            "mandatory": None,
        },
        {
            "id": "W1_T05",
            "label": "W1 @ min_ind_score=0.5",
            "weights": "ind_weights_W1.json",
            "min_ind_score": 0.5,
            "mandatory": None,
        },
        {
            "id": "W1_T10",
            "label": "W1 @ min_ind_score=1.0",
            "weights": "ind_weights_W1.json",
            "min_ind_score": 1.0,
            "mandatory": None,
        },
        {
            "id": "W2_T05",
            "label": "W2 @ min_ind_score=0.5",
            "weights": "ind_weights_W2.json",
            "min_ind_score": 0.5,
            "mandatory": None,
        },
        {
            "id": "W2_T10",
            "label": "W2 @ min_ind_score=1.0",
            "weights": "ind_weights_W2.json",
            "min_ind_score": 1.0,
            "mandatory": None,
        },
        {
            "id": "W2_T15",
            "label": "W2 @ min_ind_score=1.5",
            "weights": "ind_weights_W2.json",
            "min_ind_score": 1.5,
            "mandatory": None,
        },
        {
            "id": "A1_ATR_T10",
            "label": "A1 ATR ablation @ 1.0",
            "weights": "ind_weights_A1_ATR.json",
            "min_ind_score": 1.0,
            "mandatory": None,
        },
        {
            "id": "A2_VOL_T10",
            "label": "A2 VOL ablation @ 1.0",
            "weights": "ind_weights_A2_VOL.json",
            "min_ind_score": 1.0,
            "mandatory": None,
        },
        {
            "id": "A3_DIAMOND_T10",
            "label": "A3 DIAMOND ablation @ 1.0",
            "weights": "ind_weights_A3_DIAMOND.json",
            "min_ind_score": 1.0,
            "mandatory": None,
        },
        {
            "id": "P_ATR_VOL",
            "label": "pair gate ATR+VOL (score off)",
            "weights": "ind_weights_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_ATR_VOL.json",
        },
        {
            "id": "P_ATR_DIAMOND",
            "label": "pair gate ATR+DIAMOND (score off)",
            "weights": "ind_weights_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_ATR_DIAMOND.json",
        },
        {
            "id": "P_VOL_DIAMOND",
            "label": "pair gate VOL+DIAMOND (score off)",
            "weights": "ind_weights_C0.json",
            "min_ind_score": -2,
            "mandatory": "mandatory_VOL_DIAMOND.json",
        },
    ]

    manifest = {
        "control_source": str(src),
        "control_atr_vol_diamond": {
            "ATR_RATIO": w0.get("ATR_RATIO"),
            "VOL_SURGE": w0.get("VOL_SURGE"),
            "DIAMOND": w0.get("DIAMOND"),
        },
        "experiments_dir": str(EXP_DIR),
        "output_root": str(REPO / "drive" / "ind_weight_exp"),
        "concurrency": 3,
        "workers_per_job": 10,
        "concurrency_note": (
            "Up to 3 concurrent IND backtests, each with -w 10 (~30 symbol workers total). "
            "Override via run_ind_weight_experiments.py --jobs/--workers."
        ),
        "candidates": candidates,
    }
    _dump(EXP_DIR / "ind_weight_exp_manifest.json", manifest)
    print(f"wrote {len(candidates)} candidates -> {EXP_DIR / 'ind_weight_exp_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
