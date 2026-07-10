#!/usr/bin/env python3
"""
Cross-system convergence report: symbols appearing on 2+ of IND / BRT / RL / YH
watchlist and scanner outputs from the latest run of each engine.

Writes:
  Drive/System_Convergence_<stamp>.csv
  Drive/System_Convergence_<stamp>.html
  Drive/System_Convergence_Latest.csv / .html
"""
from __future__ import annotations

import argparse
import html
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from generate_investment_report import _html_table, _latest_run_timestamp

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "Drive"
ET = ZoneInfo("America/New_York")

SYSTEMS = ("IND", "BRT", "RL", "YH")
LIST_KINDS = ("Watchlist", "Scanner")


@dataclass
class ListHit:
    system: str
    kind: str
    path: Path
    run_ts: Optional[str]
    row: dict


@dataclass
class SymbolConvergence:
    symbol: str
    hits: list[ListHit] = field(default_factory=list)

    @property
    def systems(self) -> set[str]:
        return {h.system for h in self.hits}

    @property
    def lists(self) -> list[str]:
        return [f"{h.system}_{h.kind}" for h in self.hits]

    @property
    def n_systems(self) -> int:
        return len(self.systems)

    @property
    def n_lists(self) -> int:
        return len(self.hits)


def _resolve_drive(drive: Path) -> Path:
    d = drive.resolve()
    if d.is_dir():
        return d
    alt = ROOT / "drive"
    if alt.is_dir():
        return alt.resolve()
    raise FileNotFoundError(f"Drive folder not found: {drive}")


def _first_numeric(row: dict, cols: list[str]) -> Optional[float]:
    for c in cols:
        if c not in row:
            continue
        v = row.get(c)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        s = str(v).strip()
        if not s or s.lower() in {"nan", "none"}:
            continue
        try:
            return float(str(v).replace(",", "").replace("%", ""))
        except ValueError:
            continue
    return None


def _fmt_num(v: Optional[float], nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return f"{v:,.{nd}f}"


def _fmt_text(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return s


def _load_list_csv(drive: Path, system: str, kind: str) -> tuple[Optional[Path], pd.DataFrame, Optional[str]]:
    latest = drive / f"{system}_LatestRun_{kind}.csv"
    run_ts = _latest_run_timestamp(system, drive)
    if latest.is_file():
        df = pd.read_csv(latest)
        return latest, df, run_ts
    if run_ts:
        path = drive / f"{system}_{kind}_{run_ts}.csv"
        if path.is_file():
            return path, pd.read_csv(path), run_ts
    return None, pd.DataFrame(), run_ts


def _collect_hits(drive: Path) -> tuple[dict[str, SymbolConvergence], dict[str, dict]]:
    """Return symbol map and metadata about source files."""
    meta: dict[str, dict] = {}
    by_symbol: dict[str, SymbolConvergence] = {}

    for system in SYSTEMS:
        for kind in LIST_KINDS:
            key = f"{system}_{kind}"
            path, df, run_ts = _load_list_csv(drive, system, kind)
            meta[key] = {
                "path": path,
                "run_ts": run_ts,
                "rows": len(df),
                "symbols": 0,
            }
            if path is None or df.empty or "SYMBOL" not in df.columns:
                continue
            seen: set[str] = set()
            for _, row in df.iterrows():
                sym = str(row.get("SYMBOL", "")).strip().upper()
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                hit = ListHit(
                    system=system,
                    kind=kind,
                    path=path,
                    run_ts=run_ts,
                    row=row.to_dict(),
                )
                if sym not in by_symbol:
                    by_symbol[sym] = SymbolConvergence(symbol=sym)
                by_symbol[sym].hits.append(hit)
            meta[key]["symbols"] = len(seen)

    return by_symbol, meta


def _system_detail(conv: SymbolConvergence, system: str, field_name: str, cols: list[str]) -> str:
    parts: list[str] = []
    for h in conv.hits:
        if h.system != system:
            continue
        val = _fmt_text(h.row.get(field_name)) if field_name in h.row else ""
        if not val:
            val = _fmt_num(_first_numeric(h.row, cols))
        if val:
            tag = "S" if h.kind == "Scanner" else "W"
            parts.append(f"{tag}:{val}")
    return " · ".join(parts)


def _build_row(conv: SymbolConvergence) -> dict:
    price_cols = ["CLOSE", "LAST_CLOSE", "TRIGGER_CLOSE", "CURRENT_PRICE"]
    stop_cols = ["STOP_LOSS", "StopLoss"]
    target_cols = ["TARGET", "Target"]

    prices = [
        _first_numeric(h.row, price_cols)
        for h in conv.hits
        if _first_numeric(h.row, price_cols) is not None
    ]
    stops = [
        _first_numeric(h.row, stop_cols)
        for h in conv.hits
        if _first_numeric(h.row, stop_cols) is not None
    ]
    targets = [
        _first_numeric(h.row, target_cols)
        for h in conv.hits
        if _first_numeric(h.row, target_cols) is not None
    ]

    current = prices[0] if prices else None
    stop = stops[0] if stops else None
    target = targets[0] if targets else None

    upside = ""
    if current and target and current > 0:
        upside = f"{(target / current - 1) * 100:+.1f}%"
    risk = ""
    if current and stop and current > 0:
        risk = f"{(stop / current - 1) * 100:+.1f}%"

    return {
        "SYMBOL": conv.symbol,
        "SYSTEMS": ", ".join(sorted(conv.systems)),
        "N_SYSTEMS": conv.n_systems,
        "LISTS": ", ".join(conv.lists),
        "N_LISTS": conv.n_lists,
        "CURRENT_PRICE": _fmt_num(current),
        "TARGET": _fmt_num(target),
        "STOP": _fmt_num(stop),
        "UPSIDE_TO_TARGET": upside,
        "RISK_TO_STOP": risk,
        "IND_SCORE": _system_detail(conv, "IND", "IND_SCORE", []),
        "IND_DIFF": _system_detail(conv, "IND", "IND_DIFF", []),
        "IND_STATUS": _system_detail(conv, "IND", "STATUS", []),
        "BRT_STATUS": _system_detail(conv, "BRT", "STATUS", []),
        "BRT_ZONE": _system_detail(conv, "BRT", "ZONE_CENTER", []),
        "YH_STATUS": _system_detail(conv, "YH", "STATUS", []),
        "YH_ZONE": _system_detail(conv, "YH", "ZONE_CENTER", []),
        "RL_SCORE": _system_detail(conv, "RL", "SETUP_SCORE", []),
        "RL_TIER": _system_detail(conv, "RL", "WATCH_TIER", []),
        "ENTRY_BAND": _system_detail(conv, "IND", "ENTRY_OPEN_BAND", ["MAX_ENTRY_OPEN", "MIN_ENTRY_OPEN"])
        or _system_detail(conv, "BRT", "ENTRY_OPEN_BAND", ["MAX_ENTRY_OPEN", "MIN_ENTRY_OPEN"]),
        "RL_TOO_HIGH": _system_detail(conv, "RL", "TOO_HIGH_LINE", []),
        "RL_ENTRY_OK": _system_detail(conv, "RL", "ENTRY_ALLOWED", []),
    }


def build_convergence_df(
    by_symbol: dict[str, SymbolConvergence],
    *,
    min_systems: int = 2,
    include_same_system: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cross_rows: list[dict] = []
    same_sys_rows: list[dict] = []

    for conv in by_symbol.values():
        if conv.n_lists < 2:
            continue
        row = _build_row(conv)
        if conv.n_systems >= min_systems:
            cross_rows.append(row)
        elif include_same_system and conv.n_lists >= 2:
            same_sys_rows.append(row)

    cross = pd.DataFrame(cross_rows)
    same = pd.DataFrame(same_sys_rows)
    if not cross.empty:
        cross = cross.sort_values(
            ["N_SYSTEMS", "N_LISTS", "SYMBOL"], ascending=[False, False, True]
        ).reset_index(drop=True)
    if not same.empty:
        same = same.sort_values(["N_LISTS", "SYMBOL"], ascending=[False, True]).reset_index(
            drop=True
        )
    return cross, same


def _meta_lines(meta: dict[str, dict]) -> list[str]:
    lines = []
    for key in sorted(meta.keys()):
        m = meta[key]
        path = m["path"]
        name = path.name if path else "(missing)"
        ts = m["run_ts"] or "?"
        lines.append(f"{key}: {name} · run {ts} · {m['symbols']} symbols")
    return lines


def _df_to_table_rows(df: pd.DataFrame, cols: list[str]) -> list[list[str]]:
    if df.empty:
        return []
    return [[str(row.get(c, "")) for c in cols] for _, row in df.iterrows()]


def build_html(
    cross: pd.DataFrame,
    same: pd.DataFrame,
    meta: dict[str, dict],
    *,
    generated: datetime,
) -> str:
    cross_cols = [
        "SYMBOL",
        "SYSTEMS",
        "N_SYSTEMS",
        "LISTS",
        "CURRENT_PRICE",
        "TARGET",
        "STOP",
        "UPSIDE_TO_TARGET",
        "RISK_TO_STOP",
        "IND_SCORE",
        "IND_DIFF",
        "RL_SCORE",
        "RL_TIER",
        "BRT_ZONE",
        "YH_ZONE",
        "ENTRY_BAND",
        "IND_STATUS",
        "BRT_STATUS",
        "YH_STATUS",
    ]
    same_cols = [
        "SYMBOL",
        "SYSTEMS",
        "LISTS",
        "CURRENT_PRICE",
        "TARGET",
        "STOP",
        "ENTRY_BAND",
        "IND_STATUS",
        "BRT_STATUS",
        "YH_STATUS",
        "RL_TIER",
    ]

    cross_rows = _df_to_table_rows(cross, cross_cols)
    same_rows = _df_to_table_rows(same, same_cols)
    three_way = 0
    if not cross.empty:
        three_way = int((cross["N_SYSTEMS"] >= 4).sum())

    meta_html = "".join(f"<li>{html.escape(line)}</li>" for line in _meta_lines(meta))
    gen_s = generated.strftime("%Y-%m-%d %H:%M ET")

    cross_table = (
        _html_table(cross_cols, cross_rows, ["text"] * len(cross_cols))
        if cross_rows
        else "<p>No cross-system overlaps (symbol on 2+ of IND/BRT/RL/YH).</p>"
    )
    same_table = (
        _html_table(same_cols, same_rows, ["text"] * len(same_cols))
        if same_rows
        else "<p>No same-system watchlist+scanner overlaps.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System Convergence Report</title>
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin:24px; color:#0f172a; max-width:1200px; }}
h1 {{ font-size:1.5rem; margin:0 0 8px; }}
.sub {{ color:#64748b; margin-bottom:20px; font-size:0.95rem; line-height:1.45; }}
.cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }}
.card {{ flex:1 1 180px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px; }}
.card h3 {{ margin:0 0 6px; font-size:13px; color:#475569; }}
.metric {{ font-size:1.5rem; font-weight:700; }}
.small {{ font-size:12px; color:#64748b; }}
section {{ margin-top:28px; }}
.table-wrap {{ overflow-x:auto; margin:12px 0; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; min-width:720px; }}
th, td {{ border:1px solid #e2e8f0; padding:8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
ul.sources {{ font-size:12px; color:#475569; line-height:1.5; }}
</style></head><body>
<h1>IND / BRT / RL / YH — Watchlist &amp; Scanner Convergence</h1>
<p class="sub">Generated {html.escape(gen_s)} · Symbols listed when they appear on <strong>2+ lists</strong> across the latest IND, BRT, RL, and YH watchlist/scanner outputs.</p>
<div class="cards">
  <div class="card"><h3>Cross-system overlaps</h3><div class="metric">{len(cross)}</div><div class="small">2+ engines (IND/BRT/RL/YH)</div></div>
  <div class="card"><h3>4-engine overlaps</h3><div class="metric">{three_way}</div><div class="small">On all four systems</div></div>
  <div class="card"><h3>Same-system only</h3><div class="metric">{len(same)}</div><div class="small">Watchlist + scanner, one engine</div></div>
</div>
<section>
<h2>Sources</h2>
<ul class="sources">{meta_html}</ul>
</section>
<section>
<h2>Cross-system convergence</h2>
<p class="small">Example: symbol on both IND Watchlist and BRT Watchlist. W=watchlist, S=scanner in per-system detail columns.</p>
<div class="table-wrap">{cross_table}</div>
</section>
<section>
<h2>Same-system watchlist + scanner</h2>
<p class="small">Symbol on both watchlist and scanner for a single engine (e.g. BRT_Watchlist + BRT_Scanner).</p>
<div class="table-wrap">{same_table}</div>
</section>
<p class="small"><a href="investment.html">Investment report</a> · <a href="index.html">Scanner open report</a></p>
</body></html>"""


def build_report(
    drive_dir: Path,
    *,
    output_path: Optional[Path] = None,
    min_systems: int = 2,
) -> tuple[Path, Path, pd.DataFrame, pd.DataFrame]:
    drive = _resolve_drive(drive_dir)
    by_symbol, meta = _collect_hits(drive)
    cross, same = build_convergence_df(by_symbol, min_systems=min_systems)

    now = datetime.now(tz=ET)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    out_csv = output_path or (drive / f"System_Convergence_{stamp}.csv")
    out_html = out_csv.with_suffix(".html")
    if output_path and output_path.suffix.lower() == ".csv":
        out_html = output_path.with_suffix(".html")

    # Primary CSV = cross-system; append same-system rows with a section marker file or second sheet
    # Write cross-system as main CSV; same-system to companion if non-empty.
    cross.to_csv(out_csv, index=False)
    if not same.empty:
        same_path = out_csv.with_name(out_csv.stem + "_SameSystem" + out_csv.suffix)
        same.to_csv(same_path, index=False)

    html_text = build_html(cross, same, meta, generated=now)
    out_html.write_text(html_text, encoding="utf-8")

    latest_csv = drive / "System_Convergence_Latest.csv"
    latest_html = drive / "System_Convergence_Latest.html"
    shutil.copy2(out_csv, latest_csv)
    shutil.copy2(out_html, latest_html)

    return out_csv, out_html, cross, same


def main() -> int:
    p = argparse.ArgumentParser(description="IND/BRT/RL/YH watchlist & scanner convergence report")
    p.add_argument("--drive", type=Path, default=DRIVE)
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument(
        "--min-systems",
        type=int,
        default=2,
        help="Minimum distinct systems for primary table (default 2)",
    )
    args = p.parse_args()

    out_csv, out_html, cross, same = build_report(
        args.drive, output_path=args.output, min_systems=args.min_systems
    )
    print(f"Wrote {out_csv} ({len(cross)} cross-system rows)")
    if not same.empty:
        print(f"Wrote {out_csv.with_name(out_csv.stem + '_SameSystem' + out_csv.suffix)} ({len(same)} same-system rows)")
    print(f"Wrote {out_html}")
    print(f"Latest copies: System_Convergence_Latest.csv / .html")
    if not cross.empty:
        top = cross.iloc[0]
        print(
            f"Top overlap: {top['SYMBOL']} on {top['SYSTEMS']} "
            f"({top['LISTS']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
