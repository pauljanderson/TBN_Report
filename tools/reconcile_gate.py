#!/usr/bin/env python3
"""DailyRun reconciliation gate: frozen engine Closed vs latest Closed.

Compares per-system MagN baselines (config) to the newest Closed CSV under drive/.
Fails (exit 1) when historical baseline trades are missing, deleted, or materially
changed. Allows new trades after the freeze cutoff (forward fills).

Usage:
  python tools/reconcile_gate.py
  python tools/reconcile_gate.py --config drive/paul_experiments/reconcile_gate_config.json
  set SKIP_RECONCILE_GATE=1  (or RECONCILE_GATE=0) to skip from the bat wrapper
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "drive" / "paul_experiments" / "reconcile_gate_config.json"

DATE_RE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})")


def _norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().upper()).replace(" ", "_")


def _parse_date(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    # Excel serials / floats like 20190321.0
    if re.fullmatch(r"\d+(\.0+)?", s):
        s = s.split(".", 1)[0]
    m = DATE_RE.match(s.replace("/", "-"))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    s = s.replace("%", "").replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _load_closed_csv(path: Path) -> list[dict[str, Any]]:
    import csv

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        rows: list[dict[str, Any]] = []
        for raw in reader:
            row = {_norm_header(k): (v if v is not None else "") for k, v in raw.items() if k is not None}
            sym = str(row.get("SYMBOL", "")).strip().upper()
            if not sym:
                continue
            opened = _parse_date(row.get("DATE_OPENED") or row.get("DATE OPENED"))
            closed = _parse_date(row.get("DATE_CLOSED") or row.get("DATE CLOSED"))
            rows.append(
                {
                    "SYMBOL": sym,
                    "DATE_OPENED": opened,
                    "DATE_CLOSED": closed,
                    "ENTRY_PRICE": _parse_float(row.get("ENTRY_PRICE") or row.get("ENTRY PRICE")),
                    "EXIT_PRICE": _parse_float(row.get("EXIT_PRICE") or row.get("EXIT PRICE")),
                    "PNL_PCT": _parse_float(row.get("PNL_PCT") or row.get("PNL %") or row.get("PNL_PCT")),
                    "EXIT_TYPE": str(row.get("EXIT_TYPE") or row.get("EXIT TYPE") or "").strip().upper(),
                }
            )
        return rows


def _trade_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        row["SYMBOL"],
        row["DATE_OPENED"] or "",
        row["DATE_CLOSED"] or "",
    )


def _find_latest_closed(drive: Path, prefix: str, alias: str | None) -> Path | None:
    if alias:
        alias_path = drive / alias
        if alias_path.is_file():
            return alias_path
    pat = re.compile(rf"^{re.escape(prefix)}_(\d{{12}})\.csv$", re.I)
    best: tuple[str, Path] | None = None
    for p in drive.glob(f"{prefix}_*.csv"):
        m = pat.match(p.name)
        if not m:
            continue
        stamp = m.group(1)
        if best is None or stamp > best[0]:
            best = (stamp, p)
    return best[1] if best else None


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    return p


def _load_baseline(spec: dict[str, Any], symbols: list[str]) -> list[dict[str, Any]]:
    mode = (spec.get("mode") or "none").lower()
    if mode in ("none", ""):
        return []
    want = {s.upper() for s in symbols}
    rows: list[dict[str, Any]] = []
    if mode == "single_file":
        path = _resolve(spec["path"])
        if not path.is_file():
            raise FileNotFoundError(f"baseline missing: {path}")
        rows = [r for r in _load_closed_csv(path) if r["SYMBOL"] in want]
    elif mode == "per_symbol_files":
        files = spec.get("files") or {}
        for sym in symbols:
            rel = files.get(sym) or files.get(sym.upper())
            if not rel:
                raise FileNotFoundError(f"no baseline file mapped for {sym}")
            path = _resolve(rel)
            if not path.is_file():
                raise FileNotFoundError(f"baseline missing for {sym}: {path}")
            part = [r for r in _load_closed_csv(path) if r["SYMBOL"] == sym.upper()]
            rows.extend(part)
    else:
        raise ValueError(f"unknown baseline mode: {mode}")
    return rows


@dataclass
class SymResult:
    symbol: str
    baseline_n: int = 0
    latest_n: int = 0
    matched: int = 0
    missing_count: int = 0
    changed_count: int = 0
    new_only_count: int = 0
    missing: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    new_only: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # New-only trades (forward fills or extra history) are allowed; fail only on
        # missing/changed baseline identity (regressions / deletions).
        return self.missing_count == 0 and self.changed_count == 0


@dataclass
class SystemResult:
    system_id: str
    status: str  # PASS | FAIL | SKIP | ERROR
    detail: str = ""
    baseline_path_note: str = ""
    latest_path: str = ""
    freeze_cutoff: str = ""
    symbols: list[SymResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("PASS", "SKIP")


def _compare_system(
    system: dict[str, Any],
    drive: Path,
    *,
    price_tol: float,
    pnl_tol: float,
    max_examples: int = 8,
) -> SystemResult:
    sid = system["id"]
    if not system.get("enabled", True):
        reason = system.get("skip_reason") or "disabled in config"
        return SystemResult(sid, "SKIP", detail=reason)

    symbols = [s.upper() for s in (system.get("symbols") or [])]
    if not symbols:
        return SystemResult(sid, "SKIP", detail="no symbols configured")

    try:
        baseline = _load_baseline(system.get("baseline") or {}, symbols)
    except (OSError, ValueError) as e:
        return SystemResult(sid, "ERROR", detail=str(e))

    if not baseline:
        return SystemResult(sid, "ERROR", detail="baseline loaded 0 trades")

    latest_path = _find_latest_closed(
        drive,
        system.get("closed_prefix") or f"{sid}_Closed",
        system.get("latest_alias"),
    )
    if latest_path is None:
        return SystemResult(sid, "ERROR", detail="no latest Closed CSV found under drive/")

    want = set(symbols)
    latest_all = [r for r in _load_closed_csv(latest_path) if r["SYMBOL"] in want]
    freeze_dates = [r["DATE_CLOSED"] or r["DATE_OPENED"] for r in baseline if (r["DATE_CLOSED"] or r["DATE_OPENED"])]
    freeze_cutoff = max(freeze_dates) if freeze_dates else ""

    base_by_sym: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    latest_by_sym: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    for r in baseline:
        base_by_sym.setdefault(r["SYMBOL"], []).append(r)
    for r in latest_all:
        latest_by_sym.setdefault(r["SYMBOL"], []).append(r)

    sym_results: list[SymResult] = []
    for sym in symbols:
        sr = SymResult(symbol=sym)
        b_rows = base_by_sym.get(sym, [])
        l_rows = latest_by_sym.get(sym, [])
        sr.baseline_n = len(b_rows)
        sr.latest_n = len(l_rows)

        b_map: dict[tuple[str, str, str], dict[str, Any]] = {}
        for r in b_rows:
            k = _trade_key(r)
            # keep first; duplicates rare
            b_map.setdefault(k, r)
        l_map: dict[tuple[str, str, str], dict[str, Any]] = {}
        for r in l_rows:
            k = _trade_key(r)
            l_map.setdefault(k, r)

        for k, br in b_map.items():
            lr = l_map.get(k)
            if lr is None:
                if len(sr.missing) < max_examples:
                    sr.missing.append(f"{k[1]}->{k[2]}")
                elif len(sr.missing) == max_examples:
                    sr.missing.append("...")
                continue
            diffs: list[str] = []
            for col, tol in (("ENTRY_PRICE", price_tol), ("EXIT_PRICE", price_tol)):
                bv, lv = br.get(col), lr.get(col)
                if bv is None or lv is None:
                    if bv != lv:
                        diffs.append(f"{col} {bv} vs {lv}")
                elif round(abs(float(bv) - float(lv)), 4) > tol:
                    diffs.append(f"{col} {bv} vs {lv}")
            bv, lv = br.get("PNL_PCT"), lr.get("PNL_PCT")
            if bv is not None and lv is not None and round(abs(float(bv) - float(lv)), 4) > pnl_tol:
                diffs.append(f"PNL_PCT {bv} vs {lv}")
            bet, let_ = br.get("EXIT_TYPE") or "", lr.get("EXIT_TYPE") or ""
            if bet and let_ and bet != let_:
                diffs.append(f"EXIT_TYPE {bet} vs {let_}")
            if diffs:
                if len(sr.changed) < max_examples:
                    sr.changed.append(f"{k[1]}->{k[2]} ({'; '.join(diffs)})")
                elif len(sr.changed) == max_examples:
                    sr.changed.append("...")
            else:
                sr.matched += 1

        for k, lr in l_map.items():
            if k in b_map:
                continue
            opened = lr["DATE_OPENED"] or ""
            closed = lr["DATE_CLOSED"] or ""
            sr.new_only_count += 1
            if len(sr.new_only) < max_examples:
                tag = "fwd" if (freeze_cutoff and ((opened and opened > freeze_cutoff) or (closed and closed > freeze_cutoff))) else "extra"
                sr.new_only.append(f"{opened}->{closed}({tag})")
            elif len(sr.new_only) == max_examples:
                sr.new_only.append("...")

        sr.missing_count = sum(1 for k in b_map if k not in l_map)
        chg_n = 0
        for k, br in b_map.items():
            lr = l_map.get(k)
            if lr is None:
                continue
            bad = False
            for col, tol in (("ENTRY_PRICE", price_tol), ("EXIT_PRICE", price_tol)):
                bv, lv = br.get(col), lr.get(col)
                if bv is not None and lv is not None and round(abs(float(bv) - float(lv)), 4) > tol:
                    bad = True
            if br.get("PNL_PCT") is not None and lr.get("PNL_PCT") is not None:
                if round(abs(float(br["PNL_PCT"]) - float(lr["PNL_PCT"])), 4) > pnl_tol:
                    bad = True
            if (br.get("EXIT_TYPE") or "") and (lr.get("EXIT_TYPE") or "") and br["EXIT_TYPE"] != lr["EXIT_TYPE"]:
                bad = True
            if bad:
                chg_n += 1
        sr.changed_count = chg_n
        sym_results.append(sr)

    failed = [s for s in sym_results if not s.ok]
    status = "PASS" if not failed else "FAIL"
    note = system.get("freeze_note") or ""
    return SystemResult(
        system_id=sid,
        status=status,
        detail=note,
        baseline_path_note=note,
        latest_path=str(latest_path),
        freeze_cutoff=freeze_cutoff,
        symbols=sym_results,
    )


def _print_report(results: list[SystemResult], price_tol: float) -> None:
    print("=" * 72)
    print("RECONCILE GATE — frozen engine Closed vs latest DailyRun Closed")
    print(f"price_tol=+/- ${price_tol:.2f}  (identity: SYMBOL + DATE_OPENED + DATE_CLOSED)")
    print("=" * 72)
    for res in results:
        print()
        print(f"[{res.system_id}] {res.status}")
        if res.status == "SKIP":
            print(f"  {res.detail}")
            continue
        if res.status == "ERROR":
            print(f"  ERROR: {res.detail}")
            continue
        print(f"  latest: {res.latest_path}")
        print(f"  freeze_cutoff (max baseline DATE_CLOSED): {res.freeze_cutoff}")
        if res.detail:
            print(f"  note: {res.detail}")
        for sr in res.symbols:
            flag = "OK" if sr.ok else "FAIL"
            print(
                f"  {sr.symbol:5s} {flag:4s}  base={sr.baseline_n:3d} latest={sr.latest_n:3d} "
                f"match={sr.matched:3d} miss={sr.missing_count:3d} changed={sr.changed_count:3d} "
                f"new_only={sr.new_only_count:3d}"
            )
            if sr.missing:
                print(f"         missing baseline: {', '.join(sr.missing)}")
            if sr.changed:
                print(f"         changed: {', '.join(sr.changed)}")
            if sr.new_only:
                print(f"         new_only (allowed): {', '.join(sr.new_only)}")
    print()
    print("=" * 72)
    fails = [r for r in results if r.status in ("FAIL", "ERROR")]
    skips = [r for r in results if r.status == "SKIP"]
    passes = [r for r in results if r.status == "PASS"]
    print(
        f"SUMMARY: PASS={len(passes)} FAIL={len(fails)} SKIP={len(skips)} "
        f"-> {'PASS' if not fails else 'FAIL'}"
    )
    for r in skips:
        print(f"  SKIP {r.system_id}: {r.detail}")
    for r in fails:
        bad_syms = [s.symbol for s in r.symbols if not s.ok] if r.symbols else []
        extra = f" ({', '.join(bad_syms)})" if bad_syms else ""
        print(f"  FAIL {r.system_id}{extra}" + (f": {r.detail}" if r.status == "ERROR" else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile gate: frozen vs latest Closed trades")
    ap.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to reconcile_gate_config.json",
    )
    ap.add_argument(
        "--drive",
        default=str(ROOT / "drive"),
        help="Output directory with Closed CSVs",
    )
    ap.add_argument(
        "--system",
        action="append",
        default=[],
        help="Only run these system ids (repeatable). Default: all in config.",
    )
    args = ap.parse_args(argv)

    # Honor skip env (bat also short-circuits, but keep script usable)
    skip = os.environ.get("SKIP_RECONCILE_GATE", "").strip().lower() in ("1", "true", "yes", "y")
    gate_env = os.environ.get("RECONCILE_GATE", "").strip().lower()
    if skip or gate_env in ("0", "false", "off", "no"):
        print("RECONCILE GATE SKIPPED (SKIP_RECONCILE_GATE / RECONCILE_GATE=0)")
        return 0

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    if not cfg_path.is_file():
        print(f"ERROR: config not found: {cfg_path}", file=sys.stderr)
        return 2

    with cfg_path.open(encoding="utf-8") as f:
        cfg = json.load(f)

    price_tol = float(cfg.get("price_tol", 0.05))
    pnl_tol = float(cfg.get("pnl_tol", 0.05))
    drive = Path(args.drive)
    if not drive.is_absolute():
        drive = ROOT / drive

    systems = cfg.get("systems") or []
    if args.system:
        want = {s.upper() for s in args.system}
        systems = [s for s in systems if str(s.get("id", "")).upper() in want]
        if not systems:
            print(f"ERROR: no systems matched --system {args.system}", file=sys.stderr)
            return 2

    results = [
        _compare_system(s, drive, price_tol=price_tol, pnl_tol=pnl_tol) for s in systems
    ]
    _print_report(results, price_tol)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
