"""
Load per-symbol optimized BRT/RL parameters and apply them to backtests and getTarget.

Settings JSON shape (from per_symbol_optimizer.py):
  { "AAPL": { "system": "BRT", "stop_pct": 0.934, ... }, ... }
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any, Mapping, Optional, TypeVar

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent

DEFAULT_SETTINGS_LATEST = SCRIPT_DIR / "Per_Symbol_Optimized_Settings_Latest.json"
DEFAULT_SETTINGS_APPROVED = SCRIPT_DIR / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

T = TypeVar("T")

META_KEYS = frozenset({"system"})

# Legacy stop_anchor ↔ stop_loss_based (keep both keys consistent when applying overrides)
_STOP_LOSS_BASED_ALIASES = {
    "trigger_low": "trigger_low",
    "signal_low": "trigger_low",
    "entry_open": "entry_open",
    "entry": "entry_open",
    "zone_low": "zone_low",
    "zone_bottom": "zone_low",
}
_STOP_LOSS_BASED_TO_ANCHOR = {
    "trigger_low": "signal_low",
    "entry_open": "entry",
    "zone_low": "zone_low",
}


def _sync_stop_loss_override_keys(overrides: dict[str, Any]) -> dict[str, Any]:
    """Map legacy stop_anchor into stop_loss_based; keep both fields aligned."""
    if "stop_loss_based" not in overrides and "stop_anchor" not in overrides:
        return overrides
    out = dict(overrides)
    raw = out.get("stop_loss_based", out.get("stop_anchor", "trigger_low"))
    s = str(raw or "trigger_low").strip().lower()
    slb = _STOP_LOSS_BASED_ALIASES.get(s, s if s in _STOP_LOSS_BASED_TO_ANCHOR else "trigger_low")
    out["stop_loss_based"] = slb
    out["stop_anchor"] = _STOP_LOSS_BASED_TO_ANCHOR[slb]
    return out


# BRT keys stored in optimized JSON -> PercentProfile field names (getTarget)
_BRT_PERCENT_MAP = {
    "target_pct": "target_pct",
    "stop_pct": "stop_pct",
}

# RL keys -> RlProfile field names (getTarget)
_RL_PROFILE_KEYS = frozenset(
    {
        "rl_target_pct",
        "rl_stop_pct",
        "rl_trail_profit",
        "rl_trail_stop",
        "rl_trail_profit2",
        "rl_trail_stop2",
    }
)


def resolve_settings_path(arg: str | None = None) -> Path | None:
    """Resolve settings file: explicit arg > env PER_SYMBOL_SETTINGS > Latest symlink/file."""
    for candidate in (
        (arg or "").strip(),
        (os.environ.get("PER_SYMBOL_SETTINGS") or "").strip(),
    ):
        if candidate:
            p = Path(candidate)
            if not p.is_absolute():
                p = SCRIPT_DIR.parent / p
            if p.is_file():
                return p.resolve()
            # Also try under stock_analysis/
            p2 = SCRIPT_DIR / candidate
            if p2.is_file():
                return p2.resolve()
    if DEFAULT_SETTINGS_APPROVED.is_file():
        return DEFAULT_SETTINGS_APPROVED.resolve()
    if DEFAULT_SETTINGS_LATEST.is_file():
        return DEFAULT_SETTINGS_LATEST.resolve()
    # Newest timestamped approved file, then any settings file
    approved = sorted(
        p for p in SCRIPT_DIR.glob("Per_Symbol_Optimized_Settings_Approved_*.json")
        if "Latest" not in p.name
    )
    if approved:
        return approved[-1].resolve()
    candidates = sorted(
        p for p in SCRIPT_DIR.glob("Per_Symbol_Optimized_Settings_*.json")
        if "Latest" not in p.name and "Approved" not in p.name
    )
    for p in reversed(candidates):
        return p.resolve()
    return None


def load_per_symbol_settings(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    resolved = Path(path).resolve() if path else resolve_settings_path()
    if resolved is None or not resolved.is_file():
        return {}
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected object at root of {resolved}")
    out: dict[str, dict[str, Any]] = {}
    for sym, entry in data.items():
        if not isinstance(entry, dict):
            continue
        out[str(sym).strip().upper()] = dict(entry)
    return out


def overrides_for_symbol(
    settings: Mapping[str, Mapping[str, Any]],
    symbol: str,
    system: str,
    *,
    valid_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Return param overrides for symbol when JSON system matches requested system."""
    entry = settings.get(str(symbol).strip().upper())
    if not entry:
        return {}
    entry_system = str(entry.get("system", "")).strip().upper()
    if entry_system and entry_system != str(system).strip().upper():
        return {}
    overrides = {k: v for k, v in entry.items() if k not in META_KEYS}
    if valid_fields is not None:
        # Allow legacy stop_anchor in JSON even if only stop_loss_based is listed, and vice versa.
        _stop_fields = {"stop_loss_based", "stop_anchor"}
        overrides = {
            k: v
            for k, v in overrides.items()
            if k in valid_fields or (k in _stop_fields and (_stop_fields & valid_fields))
        }
    return _sync_stop_loss_override_keys(overrides)


def apply_to_dataclass(cfg: T, overrides: Mapping[str, Any]) -> T:
    """Apply overrides to a dataclass instance (unknown keys ignored)."""
    if not overrides:
        return cfg
    field_names = {f.name for f in fields(cfg)}  # type: ignore[arg-type]
    kw = _sync_stop_loss_override_keys({k: v for k, v in overrides.items() if k in field_names or k in ("stop_anchor", "stop_loss_based")})
    kw = {k: v for k, v in kw.items() if k in field_names}
    if not kw:
        return cfg
    return replace(cfg, **kw)  # type: ignore[return-value]


def cfg_dict_with_overrides(
    base_cfg: Any,
    symbol: str,
    settings: Mapping[str, Mapping[str, Any]],
    system: str,
    *,
    field_names: set[str],
) -> dict[str, Any]:
    d = {f: getattr(base_cfg, f) for f in field_names}
    overrides = overrides_for_symbol(settings, symbol, system, valid_fields=field_names)
    d.update(overrides)
    return _sync_stop_loss_override_keys(d)


def apply_rl_profile_overrides(profile: Any, overrides: Mapping[str, Any]) -> Any:
    kw = {k: v for k, v in overrides.items() if k in _RL_PROFILE_KEYS}
    return apply_to_dataclass(profile, kw)


def apply_brt_percent_overrides(profile: Any, overrides: Mapping[str, Any]) -> Any:
    kw = {}
    for src, dst in _BRT_PERCENT_MAP.items():
        if src in overrides:
            kw[dst] = overrides[src]
    return apply_to_dataclass(profile, kw)


def summarize_param_value_counts(
    settings: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Count how often each optimized param value appears across all symbols."""
    counters: dict[str, Counter] = {}
    for sym, entry in settings.items():
        sys_name = str(entry.get("system", "")).strip().upper()
        for k, v in entry.items():
            if k in META_KEYS:
                continue
            param_key = f"{sys_name}.{k}" if sys_name else k
            counters.setdefault(param_key, Counter())[v] += 1
    rows: list[dict[str, Any]] = []
    for param in sorted(counters):
        for value, count in counters[param].most_common():
            rows.append({"param": param, "value": value, "count": count})
    return rows


def write_param_summary_csv(
    settings: Mapping[str, Mapping[str, Any]],
    out_path: Path,
) -> Path:
    import pandas as pd

    rows = summarize_param_value_counts(settings)
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def print_param_summary(settings: Mapping[str, Mapping[str, Any]]) -> None:
    rows = summarize_param_value_counts(settings)
    if not rows:
        print("[per-symbol] No optimized settings to summarize.")
        return
    print("\n" + "=" * 60)
    print("[per-symbol] Optimized parameter value counts (all symbols)")
    print("=" * 60)
    current_param = None
    for row in rows:
        param = row["param"]
        if param != current_param:
            current_param = param
            print(f"\n{param}:")
        print(f"  {row['value']!r}: {row['count']}")
