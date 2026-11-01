"""WPBR incremental / resume-from-last-run helpers.

Warm start (when fingerprint matches): seed per-symbol backtest state and
advance the bar loop from the prior last bar instead of replaying full history.

Cold start / fingerprint mismatch / force-full: full rebuild (current behavior).

Default OFF until parity proven. Enable with::

    -v wpbr_incremental=true
    # or
    set WPBR_INCREMENTAL=1

Force full rebuild while keeping the flag on::

    -v wpbr_incremental_force_full=true
    # or
    set WPBR_INCREMENTAL_FORCE_FULL=1

State lives under ``<output_dir>/WPBR_incr_state/`` (override with
``wpbr_incremental_state_dir`` / ``WPBR_INCREMENTAL_STATE_DIR``).
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STATE_VERSION = 1
META_NAME = "meta.json"
SYMBOLS_DIR = "by_symbol"

# Freeze knobs that change trade identity for WPBR DailyRun / research.
# Universe size is tracked separately via symbol list hash.
FINGERPRINT_CFG_KEYS: tuple[str, ...] = (
    "wpbr_zones",
    "brt_zones",
    "yh_zones",
    "vec_zones",
    "band_pct",
    "strong_pre_pivot_bars",
    "strong_pre_pivot_pct",
    "strong_post_pivot_bars",
    "strong_post_pivot_pct",
    "strong_pivot_mode",
    "wpbr_breakout_confirmation",
    "wpbr_max_days_after_retest",
    "wpbr_retest_mode",
    "wpbr_second_chance_after_win",
    "wpbr_merge_overlapping_zones",
    "wpbr_overhead_band_pct",
    "wpbr_dynamic_overhead",
    "wpbr_dyn_oh_target_frac",
    "wpbr_dyn_oh_stop_frac",
    "growth_filter_enabled",
    "growth_bars",
    "growth_history_slack_bars",
    "min_history_bars",
    "growth_filter_strict_gt",
    "growth_min_pct",
    "target_pct",
    "stop_pct",
    "stop_pct_is_multiplier",
    "stop_loss_based",
    "sheet_no_entry_same_bar_after_exit",
    "entry_start_date",
    "entry_end_date",
    "too_high_multiplier",
    "min_spy_compare_1y_at_trigger",
    "max_market_cap",
    "min_market_cap",
    "use_indicators",
    "indicator_buy",
    "transaction_type",
    "entry_type",
)

CODE_FILES: tuple[str, ...] = (
    "stock_analysis/rocket_tbn.py",
    "stock_analysis/wpbr_zones.py",
    "stock_analysis/wpbr_incremental.py",
)


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    s = str(val or "").strip().lower()
    return s in {"1", "true", "yes", "on"}


def incremental_flag_enabled(cfg_value: Any = None) -> bool:
    """True when cfg asks for incremental or ``WPBR_INCREMENTAL`` is truthy."""
    if cfg_value is not None and str(cfg_value).strip() != "":
        return _truthy(cfg_value)
    env = os.environ.get("WPBR_INCREMENTAL", "").strip().lower()
    return env in {"1", "true", "yes", "on"}


def force_full_enabled(cfg_value: Any = None) -> bool:
    if cfg_value is not None and str(cfg_value).strip() != "":
        return _truthy(cfg_value)
    env = os.environ.get("WPBR_INCREMENTAL_FORCE_FULL", "").strip().lower()
    return env in {"1", "true", "yes", "on"}


def resolve_state_dir(
    state_dir: str | Path | None = None,
    *,
    output_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> Path:
    raw = (str(state_dir).strip() if state_dir else "") or os.environ.get(
        "WPBR_INCREMENTAL_STATE_DIR", ""
    ).strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute() and repo_root is not None:
            p = Path(repo_root) / p
        return p.resolve()
    if output_dir is not None:
        return (Path(output_dir) / "WPBR_incr_state").resolve()
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
    return (root / "drive" / "WPBR_incr_state").resolve()


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return "missing"
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _cfg_snapshot(cfg: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in FINGERPRINT_CFG_KEYS:
        v = getattr(cfg, k, None)
        if is_dataclass(v):
            out[k] = asdict(v)
        else:
            out[k] = v
    return out


def code_digests(repo_root: str | Path | None = None) -> dict[str, str]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
    return {rel: _file_digest(root / rel) for rel in CODE_FILES}


def symbols_digest(symbols: list[str] | tuple[str, ...] | None) -> str:
    syms = sorted({str(s).strip().upper() for s in (symbols or []) if str(s).strip()})
    payload = ",".join(syms).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


def compute_fingerprint(
    cfg: Any,
    *,
    symbols: list[str] | tuple[str, ...] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Stable fingerprint of freeze knobs + code digests + universe set."""
    snap = _cfg_snapshot(cfg)
    codes = code_digests(repo_root)
    sym_hash = symbols_digest(symbols)
    blob = json.dumps(
        {"cfg": snap, "code": codes, "symbols": sym_hash},
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    digest = hashlib.blake2b(blob, digest_size=16).hexdigest()
    return {
        "version": STATE_VERSION,
        "digest": digest,
        "cfg": snap,
        "code": codes,
        "symbols_digest": sym_hash,
    }


def load_meta(state_dir: Path) -> Optional[dict[str, Any]]:
    path = state_dir / META_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_meta(state_dir: Path, meta: dict[str, Any]) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / META_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def symbol_state_path(state_dir: Path, symbol: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(symbol).strip().upper()) or "UNKNOWN"
    return state_dir / SYMBOLS_DIR / f"{safe}.pkl"


def save_symbol_state(state_dir: Path, symbol: str, payload: dict[str, Any]) -> Path:
    path = symbol_state_path(state_dir, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
    return path


def load_symbol_state(state_dir: Path, symbol: str) -> Optional[dict[str, Any]]:
    path = symbol_state_path(state_dir, symbol)
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
    except (OSError, pickle.UnpicklingError, EOFError):
        return None
    return data if isinstance(data, dict) else None


def clear_state_dir(state_dir: Path) -> None:
    """Remove symbol pkls + meta (cold rebuild)."""
    if not state_dir.exists():
        return
    sym_dir = state_dir / SYMBOLS_DIR
    if sym_dir.is_dir():
        for p in sym_dir.glob("*.pkl"):
            try:
                p.unlink()
            except OSError:
                pass
    meta = state_dir / META_NAME
    if meta.is_file():
        try:
            meta.unlink()
        except OSError:
            pass


def decide_mode(
    cfg: Any,
    *,
    symbols: list[str] | tuple[str, ...] | None,
    output_dir: str | Path,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return mode decision for WPBR incremental.

    Keys: enabled, mode ('full'|'warm'|'noop'), reason, state_dir, fingerprint, prior_meta
    """
    enabled = incremental_flag_enabled(getattr(cfg, "wpbr_incremental", None))
    state_dir = resolve_state_dir(
        getattr(cfg, "wpbr_incremental_state_dir", "") or "",
        output_dir=output_dir,
        repo_root=repo_root,
    )
    fp = compute_fingerprint(cfg, symbols=symbols, repo_root=repo_root)
    out: dict[str, Any] = {
        "enabled": enabled,
        "mode": "full",
        "reason": "incremental_off",
        "state_dir": str(state_dir),
        "fingerprint": fp,
        "prior_meta": None,
    }
    if not enabled:
        return out
    if force_full_enabled(getattr(cfg, "wpbr_incremental_force_full", None)):
        out["reason"] = "force_full"
        return out
    prior = load_meta(state_dir)
    out["prior_meta"] = prior
    if not prior:
        out["reason"] = "no_prior_state"
        return out
    if int(prior.get("version", 0) or 0) != STATE_VERSION:
        out["reason"] = "state_version_mismatch"
        return out
    prior_fp = str(prior.get("fingerprint_digest", "") or "")
    if prior_fp != str(fp.get("digest", "")):
        out["reason"] = "fingerprint_mismatch"
        return out
    out["mode"] = "warm"
    out["reason"] = "fingerprint_match"
    return out


def build_end_state(
    *,
    closed: list[Any],
    open_trade: Any,
    extra_open_trades: list[Any],
    wpbr_zone_state: dict[str, Any],
    pending_maturities: list[dict],
    max_high_since_entry: float,
    last_exit_yyyymmdd: str,
    last_exit_idx: int,
    last_exit_was_target: bool,
    pending_ind_diff_exit: bool,
    n_bars: int,
    last_bar_ymd: str,
    index_iso: list[str],
) -> dict[str, Any]:
    """Snapshot end-of-run state for one symbol (pickled per symbol)."""
    return {
        "version": STATE_VERSION,
        "closed": list(closed or []),
        "open_trade": open_trade,
        "extra_open_trades": list(extra_open_trades or []),
        "wpbr_zone_state": dict(wpbr_zone_state or {}),
        "pending_maturities": list(pending_maturities or []),
        "max_high_since_entry": float(max_high_since_entry or 0.0),
        "last_exit_yyyymmdd": str(last_exit_yyyymmdd or ""),
        "last_exit_idx": int(last_exit_idx),
        "last_exit_was_target": bool(last_exit_was_target),
        "pending_ind_diff_exit": bool(pending_ind_diff_exit),
        "n_bars": int(n_bars),
        "last_bar_ymd": str(last_bar_ymd or ""),
        # Resume starts at prior last bar index (was only used as next_op before).
        "next_bar": max(0, int(n_bars) - 1) if int(n_bars) > 0 else 0,
        "index_tail": list(index_iso[-5:]) if index_iso else [],
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def resolve_resume_start(
    seed: dict[str, Any],
    index_iso: list[str],
) -> tuple[int, str]:
    """Map a saved seed onto current index; return (loop_start_i, reason).

    Returns loop_start >= n-1 when there is nothing new to process (caller may
    still rebuild scanner/watchlist from seeded open/pending).
    """
    n = len(index_iso)
    if n <= 1:
        return 0, "too_short"
    prior_n = int(seed.get("n_bars", 0) or 0)
    prior_last = str(seed.get("last_bar_ymd", "") or "").strip()
    if prior_n <= 0 or not prior_last:
        return 0, "seed_incomplete_full"
    # Align: prior last bar should still sit at index prior_n-1 with same ymd.
    if prior_n > n:
        return 0, "history_shrunk_full"
    idx = prior_n - 1
    if idx < 0 or idx >= n:
        return 0, "index_oob_full"
    cur = str(index_iso[idx]).strip().replace("-", "")[:8]
    want = prior_last.strip().replace("-", "")[:8]
    if cur != want:
        # Data revised or calendar shifted — full rebuild for this symbol.
        return 0, "last_bar_mismatch_full"
    # Prefix check: if earlier bars revised, refuse warm.
    prior_tail = seed.get("index_tail") or []
    if prior_tail:
        # Compare overlapping tail dates.
        start = max(0, prior_n - len(prior_tail))
        for j, ymd in enumerate(prior_tail):
            bi = start + j
            if bi >= prior_n or bi >= n:
                break
            a = str(index_iso[bi]).strip().replace("-", "")[:8]
            b = str(ymd).strip().replace("-", "")[:8]
            if a != b:
                return 0, "prefix_mismatch_full"
    next_bar = int(seed.get("next_bar", idx) or idx)
    next_bar = max(0, min(next_bar, n - 1))
    if next_bar >= n - 1 and n == prior_n:
        return next_bar, "no_new_bars"
    return next_bar, "warm"
