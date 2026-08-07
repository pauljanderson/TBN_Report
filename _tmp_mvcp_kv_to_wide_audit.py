"""One-shot: rewrite legacy key/value MVCP_Audit_Report_*.csv -> shared 408-col wide schema.

Reads stamp Audit (key/value) + optional Closed for trade counts; backs up as
*.keyvalue.bak.csv; writes via brt_audit_columns.write_wide_audit_csv.
Does not re-run the backtest.
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "stock_analysis"))

from brt_audit_columns import empty_audit_row, write_wide_audit_csv  # noqa: E402
from rocket_minervini_vcp import MvcpConfig  # noqa: E402
from dataclasses import fields  # noqa: E402

DRIVE = ROOT / "drive"

# key/value metric aliases -> shared wide column names (match write_mvcp_outputs)
_KV_TO_WIDE = {
    "n_closed": "Total_Trades",
    "wins": "Wins",
    "losses": "Losses",
    "pct_wins": "Pct_Wins",
    "avg_pnl_pct": "Avg_PNL_Pct",
    "total_pnl_audit_1m_scale": "Total_PNL",
    "max_dd_pct": "Max_DD",
    "Max_Positions": "Max_Positions",
    "Aggressive_Total_PNL": "Aggressive_Total_PNL",
    "Aggressive_Max_DD": "Aggressive_Max_DD",
    "initial_capital": "initial_capital",
    "aggressive": "aggressive",
    "aggressive_max_multiple": "aggressive_max_multiple",
    "margin_utilization": "margin_utilization",
    "max_positions": "max_positions",
    "aggressive_margin_interest": "aggressive_margin_interest",
    "aggressive_avg_positions": "aggressive_avg_positions",
    "aggressive_sizing_equity_cap": "aggressive_sizing_equity_cap",
}


def _read_kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            k, v = row[0].strip(), row[1]
            if k.lower() in ("key", "metric"):
                continue
            out[k] = v  # last wins for duplicate keys
    return out


def _is_kv(path: Path) -> bool:
    with path.open(encoding="utf-8") as f:
        h = (f.readline() or "").strip().lower()
    return h.startswith("key,") or h.startswith("key,value")


def _strip_pct(s: str) -> str:
    s = (s or "").strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    return s


def convert_stamp(stamp: str, *, update_latest: bool = False) -> Path:
    audit = DRIVE / f"MVCP_Audit_Report_{stamp}.csv"
    if not audit.exists():
        raise FileNotFoundError(audit)
    if not _is_kv(audit):
        print(f"[skip] {audit.name} already wide")
        return audit

    bak = DRIVE / f"MVCP_Audit_Report_{stamp}.keyvalue.bak.csv"
    if not bak.exists():
        shutil.copy2(audit, bak)
        print(f"[bak] {bak.name}")

    kv = _read_kv(bak if bak.exists() else audit)
    row = empty_audit_row()

    link = f"https://drive.google.com/drive/search?q={stamp}"
    row["Timestamp_Drive"] = kv.get("Timestamp_Drive") or f'=hyperlink("{link}","{stamp}")'
    row["mvcp_mode"] = "true"
    row["sb_mode"] = "false"
    row["rs_mode"] = "false"
    row["rl_mode"] = "false"
    row["mts_mode"] = "false"

    cfg_names = {f.name for f in fields(MvcpConfig)}
    for name in cfg_names:
        if name in kv and name in row:
            val = kv[name]
            if name == "mvcp_mode":
                val = "true"
            row[name] = val

    for src, dst in _KV_TO_WIDE.items():
        if src in kv and dst in row and not str(row.get(dst, "")).strip():
            row[dst] = kv[src]

    # Prefer audit-scale cash / PNL (same as write_mvcp_outputs host_meta)
    if "audit_brt_cash_1m" in kv:
        row["brt_cash"] = kv["audit_brt_cash_1m"]
    elif "brt_cash" in kv:
        row["brt_cash"] = kv["brt_cash"]

    if "total_pnl_audit_1m_scale" in kv:
        row["Total_PNL"] = kv["total_pnl_audit_1m_scale"]
    elif "total_pnl_dollars" in kv and not str(row.get("Total_PNL", "")).strip():
        row["Total_PNL"] = kv["total_pnl_dollars"]

    row["Max_DD"] = _strip_pct(str(row.get("Max_DD", "") or kv.get("max_dd_pct", "")))

    # Pct_Losses / BE
    try:
        n_tr = int(float(str(row.get("Total_Trades") or "0").strip() or "0"))
    except ValueError:
        n_tr = 0
    try:
        wins = int(float(str(row.get("Wins") or "0").strip() or "0"))
    except ValueError:
        wins = 0
    try:
        losses = int(float(str(row.get("Losses") or "0").strip() or "0"))
    except ValueError:
        losses = max(n_tr - wins, 0)
    if n_tr and not str(row.get("Pct_Losses", "")).strip():
        row["Pct_Losses"] = f"{(100.0 * losses / n_tr):.2f}"
    if not str(row.get("BE", "")).strip():
        row["BE"] = "0"

    write_wide_audit_csv(audit, row)
    print(f"[wide] {audit.name} cols=408 Total_Trades={row.get('Total_Trades')} Total_PNL={row.get('Total_PNL')}")

    if update_latest:
        latest = DRIVE / "MVCP_LatestRun_Audit_Report.csv"
        shutil.copy2(audit, latest)
        print(f"[latest] {latest.name}")
    return audit


def main() -> None:
    stamps = sys.argv[1:] or ["260801215052", "260801214825"]
    for i, s in enumerate(stamps):
        convert_stamp(s, update_latest=(s == "260801215052" or (i == 0 and len(stamps) == 1)))


if __name__ == "__main__":
    main()
