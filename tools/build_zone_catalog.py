#!/usr/bin/env python3
"""Build a durable shared zone catalog from BRT / YH / WPBR / MTS DNA.

Phase A of the zones-as-target/stop experiment: persist every matured zone
(price band + mature date + source system) so other systems' trades can be
replayed against that inventory. This is *not* a product "zone exit" mode —
it is a research artifact.

Usage (repo root)::

  python tools/build_zone_catalog.py
  python tools/build_zone_catalog.py --symbols AAPL,AMD,NVDA --jobs 4
  python tools/build_zone_catalog.py --from-closed RS,RL,SB --include-markten

Writes under ``drive/paul_experiments/zone_catalog/``.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
DRIVE = REPO / "drive"
OUT_ROOT = DRIVE / "paul_experiments" / "zone_catalog"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]

sys.path.insert(0, str(SA))
sys.path.insert(0, str(REPO))

from ohlcv_store import load_symbol_df  # noqa: E402
import rocket_tbn as rt  # noqa: E402

# Production-typical DNA per source (mirrors run_zone_exits_ab / run_*.bat).
SOURCE_CFG: dict[str, dict[str, Any]] = {
    "BRT": {
        "brt_zones": True,
        "yh_zones": False,
        "wpbr_zones": False,
        "vec_zones": False,
        "brt_sheet_touch": True,
        "band_pct": 0.0154,
        "strong_pre_pivot_pct": 0.081,
        "strong_post_pivot_pct": 0.108,
        "strong_pre_pivot_bars": 7,
        "strong_post_pivot_bars": 7,
        "strong_pivot_mode": "either",
        "breakout_bars": 100,
        "tight_range_threshold_pct": 0.35,
        "tight_range_lookback": 105,
    },
    "YH": {
        "yh_zones": True,
        "brt_zones": False,
        "wpbr_zones": False,
        "vec_zones": False,
        "rl_mode": False,
        "band_pct": 0.015,
        "yh_move_away_pct": 0.03,
        "yh_lookback": 252,
        "yh_memory_mode": "sheet",
        "strong_pre_pivot_bars": 7,
        "strong_pre_pivot_pct": 0.12,
        "strong_post_pivot_bars": 7,
        "strong_post_pivot_pct": 0.109,
        "strong_pivot_mode": "off",
    },
    "WPBR": {
        "wpbr_zones": True,
        "brt_zones": False,
        "yh_zones": False,
        "vec_zones": False,
        "band_pct": 0.015,
        "strong_pre_pivot_bars": 3,
        "strong_pre_pivot_pct": 0.10,
        "strong_post_pivot_bars": 3,
        "strong_post_pivot_pct": 0.10,
        "strong_pivot_mode": "either",
        "wpbr_breakout_confirmation": 0.03,
        "wpbr_max_days_after_retest": 2,
    },
    "MTS": {
        # mts_sheet_parity_overrides() + production bat knobs
        "band_pct": 0.018,
        "touch_threshold": 2,
        "strong_post_pivot_bars": 7,
        "strong_post_pivot_pct": 0.06,
        "strong_pre_pivot_bars": 7,
        "strong_pre_pivot_pct": 0.12,
    },
}

CATALOG_FIELDS = [
    "symbol",
    "source_system",
    "zone_low",
    "zone_high",
    "zone_center",
    "mature_date",
    "as_of_date",
    "band_pct",
    "bar_index",
    "zone_id",
]


def _cfg_for_source(source: str) -> rt.BRTConfig:
    fields = {f.name for f in dataclasses.fields(rt.BRTConfig)}
    kw: dict[str, Any] = {}
    if source == "MTS":
        ov = {k: v for k, v in rt.mts_sheet_parity_overrides().items() if k in fields}
        kw.update(ov)
    kw.update({k: v for k, v in SOURCE_CFG[source].items() if k in fields})
    return rt.BRTConfig(**kw)


def _iso(ts) -> str:
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]


def _events_from_level3(
    source: str, level3: dict, df, *, band_pct: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    band = float(band_pct) if band_pct and band_pct > 0 else 0.015

    def add(ev: dict, *, bar_key: str, zid: str = "") -> None:
        try:
            zc = float(ev.get("zone_center", ev.get("touch_price", 0.0)) or 0.0)
            zl = float(ev.get("zone_lower", ev.get("zone_lower_f", float("nan"))))
            zh = float(ev.get("zone_upper", ev.get("zone_upper_f", float("nan"))))
        except (TypeError, ValueError):
            return
        if not (zc > 0):
            return
        bi = int(ev.get(bar_key, ev.get("activation_bar", ev.get("maturity_bar", -1))))
        if bi < 0 or bi >= len(df):
            return
        if not (zl == zl and zh == zh and zl > 0 and zh > 0):  # NaN check
            zl = zc * (1.0 - band)
            zh = zc * (1.0 + band)
        md = _iso(df.index[bi])
        rows.append(
            {
                "zone_low": round(zl, 6),
                "zone_high": round(zh, 6),
                "zone_center": round(zc, 6),
                "mature_date": md,
                "as_of_date": md,
                "bar_index": bi,
                "zone_id": zid or str(ev.get("wpbr_zone_id", "") or ""),
            }
        )

    if source in ("BRT", "MTS"):
        for ev in level3.get("brt_matured_zone_events") or []:
            add(ev, bar_key="maturity_bar")
    elif source == "YH":
        for ev in level3.get("yh_zone_events") or []:
            add(ev, bar_key="activation_bar")
    elif source == "WPBR":
        for ev in level3.get("wpbr_zone_events") or []:
            add(
                ev,
                bar_key="activation_bar",
                zid=str(ev.get("wpbr_zone_id", "") or ""),
            )
    return rows


def extract_zones_for_symbol(symbol: str, sources: list[str]) -> list[dict[str, Any]]:
    sym = symbol.upper().strip()
    df = load_symbol_df(sym)
    if df is None or df.empty or len(df) < 50:
        return []
    cfg0 = rt.BRTConfig()
    ph, pl, php, plp = rt.compute_pivots(
        df,
        int(cfg0.pivot_k),
        int(cfg0.pivot_d),
        float(cfg0.pivot_disp),
        int(cfg0.pivot_m),
    )
    out: list[dict[str, Any]] = []
    for source in sources:
        cfg = _cfg_for_source(source)
        band = float(getattr(cfg, "band_pct", 0.015) or 0.015)
        try:
            # WPBR may print debug lines when a symbol is set; keep debug_symbol=None.
            level3 = rt.build_level3_for_cfg(df, cfg, ph, pl, php, plp, debug_symbol=None)
        except Exception as exc:
            print(f"[zone_catalog] {sym}/{source} failed: {exc}", file=sys.stderr)
            continue
        for ev in _events_from_level3(source, level3, df, band_pct=band):
            out.append(
                {
                    "symbol": sym,
                    "source_system": source,
                    "band_pct": band,
                    **ev,
                }
            )
    return out


def symbols_from_closed(systems: list[str]) -> list[str]:
    syms: set[str] = set()
    for sysn in systems:
        path = DRIVE / f"{sysn.upper()}_LatestRun_Closed.csv"
        if not path.is_file():
            print(f"[zone_catalog] missing Closed: {path}", file=sys.stderr)
            continue
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue
        sc = next((c for c in rows[0] if c.upper() in ("SYMBOL", "TICKER")), None)
        if not sc:
            continue
        for r in rows:
            s = (r.get(sc) or "").upper().strip()
            if s:
                syms.add(s)
    return sorted(syms)


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = (
            r["symbol"],
            r["source_system"],
            round(float(r["zone_center"]), 4),
            r["mature_date"],
            round(float(r["zone_low"]), 4),
            round(float(r["zone_high"]), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def write_catalog(rows: list[dict[str, Any]], out_dir: Path, stamp: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"zone_catalog_{stamp}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CATALOG_FIELDS})
    latest = out_dir / "zone_catalog_latest.csv"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def write_meta(
    *,
    out_dir: Path,
    stamp: str,
    catalog_path: Path,
    rows: list[dict[str, Any]],
    symbols: list[str],
    sources: list[str],
    elapsed_s: float,
) -> Path:
    by_src: dict[str, int] = {}
    by_sym: dict[str, int] = {}
    for r in rows:
        by_src[r["source_system"]] = by_src.get(r["source_system"], 0) + 1
        by_sym[r["symbol"]] = by_sym.get(r["symbol"], 0) + 1
    meta = {
        "stamp": stamp,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "catalog_csv": str(catalog_path.relative_to(REPO)).replace("\\", "/"),
        "n_rows": len(rows),
        "n_symbols": len(symbols),
        "symbols": symbols,
        "sources": sources,
        "rows_by_source": by_src,
        "elapsed_s": round(elapsed_s, 1),
        "scope_note": (
            "MarkTen minimum plus any --from-closed / --symbols expansion. "
            "Zones are DNA from BRT/YH/WPBR/MTS only; VEC not included unless "
            "added as a source. Catalog is a research artifact for replaying "
            "other systems' entries with zone levels as target/stop."
        ),
    }
    path = out_dir / f"zone_catalog_{stamp}_meta.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (out_dir / "zone_catalog_latest_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="", help="Comma symbols (overrides universe)")
    ap.add_argument(
        "--from-closed",
        default="",
        help="Comma systems whose LatestRun Closed symbols are included (e.g. RS,RL,SB)",
    )
    ap.add_argument(
        "--include-markten",
        action="store_true",
        help="Always include MarkTen 10 (default when no symbols/from-closed)",
    )
    ap.add_argument("--markten-only", action="store_true", help="MarkTen symbols only")
    ap.add_argument(
        "--sources",
        default="BRT,YH,WPBR,MTS",
        help="Comma source systems for zone DNA",
    )
    ap.add_argument("--jobs", type=int, default=4, help="Parallel symbol workers")
    ap.add_argument("--out", default="", help="Output dir (default zone_catalog/)")
    args = ap.parse_args()

    sources = [s.strip().upper() for s in args.sources.split(",") if s.strip()]
    for s in sources:
        if s not in SOURCE_CFG:
            raise SystemExit(f"Unknown source {s}; choose from {list(SOURCE_CFG)}")

    symbols: list[str] = []
    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.markten_only:
        symbols = list(MARKTEN)
    else:
        if args.from_closed.strip():
            systems = [s.strip().upper() for s in args.from_closed.split(",") if s.strip()]
            symbols = symbols_from_closed(systems)
        if args.include_markten or (not args.from_closed.strip() and not args.symbols.strip()):
            symbols = sorted(set(symbols) | set(MARKTEN))
        if not symbols:
            symbols = list(MARKTEN)

    out_dir = Path(args.out) if args.out else OUT_ROOT
    stamp = datetime.now().strftime("%y%m%d%H%M%S")
    print(f"[zone_catalog] symbols={len(symbols)} sources={sources} jobs={args.jobs}")
    t0 = time.time()
    all_rows: list[dict[str, Any]] = []
    jobs = max(1, int(args.jobs))

    if jobs == 1:
        for i, sym in enumerate(symbols, 1):
            rows = extract_zones_for_symbol(sym, sources)
            all_rows.extend(rows)
            if i % 10 == 0 or i == len(symbols):
                print(f"  [{i}/{len(symbols)}] {sym} +{len(rows)} (total {len(all_rows)})")
    else:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(extract_zones_for_symbol, sym, sources): sym for sym in symbols}
            done = 0
            for fut in as_completed(futs):
                sym = futs[fut]
                done += 1
                try:
                    rows = fut.result()
                except Exception as exc:
                    print(f"[zone_catalog] {sym} worker error: {exc}", file=sys.stderr)
                    rows = []
                all_rows.extend(rows)
                if done % 10 == 0 or done == len(symbols):
                    print(f"  [{done}/{len(symbols)}] last={sym} total_rows={len(all_rows)}")

    all_rows = dedupe(all_rows)
    all_rows.sort(key=lambda r: (r["symbol"], r["mature_date"], r["source_system"], r["zone_center"]))
    elapsed = time.time() - t0
    catalog_path = write_catalog(all_rows, out_dir, stamp)
    meta_path = write_meta(
        out_dir=out_dir,
        stamp=stamp,
        catalog_path=catalog_path,
        rows=all_rows,
        symbols=symbols,
        sources=sources,
        elapsed_s=elapsed,
    )
    by_src: dict[str, int] = {}
    for r in all_rows:
        by_src[r["source_system"]] = by_src.get(r["source_system"], 0) + 1
    print(f"[zone_catalog] wrote {catalog_path} rows={len(all_rows)} by_source={by_src}")
    print(f"[zone_catalog] meta {meta_path} elapsed={elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
