"""Shared TBN host sizing / aggressive helpers (YH/BRT/RS/SB/MVCP).

Production dollar-scale (Closed / Summary PNL_DOLLARS) matches rocket_tbn
``_apply_report_dollar_scale_to_trades``:

  deployable D = initial_capital × aggressive_max_multiple × margin_utilization
  capacity_brt_cash = D / max(Max_Positions, 1)   # Closed host scale
  effective_brt_cash = D / max(1.5 × Avg_Positions, 5)
  sheet_brt_cash = 47_500                          # engine / Google-sheet default

Defaults: initial_capital=500_000, max_multiple=2.0, margin_utilization=0.6
→ D = 600_000; capacity = 600_000 / Max_Positions.

Audit/Report *legacy* ``brt_cash`` / ``Total_PNL`` stay on the 1_000_000 / Max_Positions
display path (util ignored) for reconcile freezes — see ``audit_display_brt_cash``.
Closed CSV stays on the capacity (600k) path. New Audit columns expose capacity /
effective / sheet cash + PnL companions without renaming legacy fields.

Effective fallback when Avg_Positions is missing/0: use Median_Positions if >0;
else effective_brt_cash = capacity_brt_cash.

``max_positions``: override when >0; else peak concurrent closed trades (min 1).
Pass via ``-v max_positions=N`` on rocket_tbn, or ``--max-positions`` on SB.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

DEFAULT_INITIAL_CAPITAL = 500_000.0
DEFAULT_AGGRESSIVE_MAX_MULTIPLE = 2.0
DEFAULT_MARGIN_UTILIZATION = 0.6
# Audit/Report display convention: (500k × 2) / max_positions
AUDIT_DEPLOYABLE_NOTIONAL = DEFAULT_INITIAL_CAPITAL * DEFAULT_AGGRESSIVE_MAX_MULTIPLE  # 1_000_000
# Canonical Google-sheet / engine per-trade notional (BRTConfig.brt_cash default).
# Distinct from rocket_tbn.SHEET_INVESTMENT (45_000) used only by Summary SHEET_PNL scaling.
SHEET_BRT_CASH = 47_500.0
EFFECTIVE_AVG_POSITIONS_MULT = 1.5
EFFECTIVE_MIN_SLOT_DIVISOR = 5.0


@dataclass
class HostSizingConfig:
    """Duck-typed subset of BRTConfig used for dollar-scale + aggressive equity."""

    brt_cash: float = SHEET_BRT_CASH
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION
    max_positions: int = 0
    aggressive: bool = False
    aggressive_margin_interest: float = 0.10
    aggressive_avg_positions: float = 0.0
    aggressive_sizing_equity_cap: float = 10.0
    aggressive_sell: str = "false"
    equity_fast_aggressive: bool = False
    compute_equity_metrics: bool = True


def effective_margin_utilization(margin_utilization: float = DEFAULT_MARGIN_UTILIZATION) -> float:
    util = float(margin_utilization or 0.0)
    return max(0.0, min(util, 1.0))


def aggressive_sim_margin_utilization(aggressive: bool, margin_utilization: float = DEFAULT_MARGIN_UTILIZATION) -> float:
    """Aggressive overlay uses full buying power (1.0); passive path keeps configured util."""
    if aggressive:
        return 1.0
    return effective_margin_utilization(margin_utilization)


def margin_deployable_capital(
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION,
) -> float:
    """Passive deployable budget for Closed dollar-scale: init × leverage × util."""
    init = float(initial_capital) if initial_capital and initial_capital > 0 else AUDIT_DEPLOYABLE_NOTIONAL
    mult = float(aggressive_max_multiple) if aggressive_max_multiple and aggressive_max_multiple > 0 else DEFAULT_AGGRESSIVE_MAX_MULTIPLE
    return init * mult * effective_margin_utilization(margin_utilization)


def report_adjusted_brt_cash(
    max_positions: int,
    *,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION,
) -> float:
    """Per-slot notional for Closed/Summary: deployable / max(max_positions, 1)."""
    mp = max(int(max_positions or 0), 1)
    return margin_deployable_capital(initial_capital, aggressive_max_multiple, margin_utilization) / mp


def capacity_brt_cash(
    max_positions: int,
    *,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION,
) -> float:
    """Alias of ``report_adjusted_brt_cash`` — Closed host scale (D / Max_Positions)."""
    return report_adjusted_brt_cash(
        max_positions,
        initial_capital=initial_capital,
        aggressive_max_multiple=aggressive_max_multiple,
        margin_utilization=margin_utilization,
    )


def effective_brt_cash(
    avg_positions: float,
    *,
    max_positions: int = 0,
    median_positions: float = 0.0,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION,
) -> float:
    """D / max(1.5 × Avg_Positions, 5).

    Fallback when Avg_Positions missing/≤0: Median_Positions if >0; else capacity
    (D / Max_Positions).
    """
    deployable = margin_deployable_capital(initial_capital, aggressive_max_multiple, margin_utilization)
    avg = float(avg_positions or 0.0)
    if avg <= 0.0:
        avg = float(median_positions or 0.0)
    if avg <= 0.0:
        return capacity_brt_cash(
            max_positions,
            initial_capital=initial_capital,
            aggressive_max_multiple=aggressive_max_multiple,
            margin_utilization=margin_utilization,
        )
    denom = max(EFFECTIVE_AVG_POSITIONS_MULT * avg, EFFECTIVE_MIN_SLOT_DIVISOR)
    return deployable / denom


def audit_display_brt_cash(max_positions: int) -> float:
    """Audit/Report labeled brt_cash: 1_000_000 / max_positions."""
    mp = max(int(max_positions or 0), 1)
    return AUDIT_DEPLOYABLE_NOTIONAL / mp


def _safe_float(x: Any, default: float = 0.0) -> float:
    if x is None:
        return default
    if isinstance(x, (int, float)):
        try:
            v = float(x)
        except (TypeError, ValueError):
            return default
        return default if v != v else v  # NaN → default
    s = str(x).replace(",", "").replace("%", "").strip()
    if not s:
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def compute_triple_cash_audit_fields(
    *,
    max_positions: int,
    avg_positions: float = 0.0,
    median_positions: float = 0.0,
    capacity_total_pnl: float | None = None,
    sum_pnl_pct: float | None = None,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION,
    sheet_brt_cash: float = SHEET_BRT_CASH,
) -> dict[str, float]:
    """Capacity / effective / sheet cash + PnL companions for Audit/Report rows.

    PnL companions use the same %% sum × cash scale: prefer ``capacity_total_pnl``
    (Closed/host Total_PNL before Audit 1M display rescale); else
    ``(sum_pnl_pct / 100) × capacity_brt_cash``.
    """
    cap = capacity_brt_cash(
        max_positions,
        initial_capital=initial_capital,
        aggressive_max_multiple=aggressive_max_multiple,
        margin_utilization=margin_utilization,
    )
    eff = effective_brt_cash(
        avg_positions,
        max_positions=max_positions,
        median_positions=median_positions,
        initial_capital=initial_capital,
        aggressive_max_multiple=aggressive_max_multiple,
        margin_utilization=margin_utilization,
    )
    sheet = float(sheet_brt_cash) if sheet_brt_cash and float(sheet_brt_cash) > 0 else SHEET_BRT_CASH
    if capacity_total_pnl is not None:
        cap_pnl = float(capacity_total_pnl)
    elif sum_pnl_pct is not None:
        cap_pnl = (float(sum_pnl_pct) / 100.0) * cap
    else:
        cap_pnl = 0.0
    scale_eff = (eff / cap) if cap > 0 else 0.0
    scale_sheet = (sheet / cap) if cap > 0 else 0.0
    return {
        "capacity_brt_cash": round(cap, 6),
        "effective_brt_cash": round(eff, 6),
        "sheet_brt_cash": round(sheet, 6),
        "capacity_Total_PNL": round(cap_pnl, 4),
        "effective_Total_PNL": round(cap_pnl * scale_eff, 4),
        "sheet_PnL": round(cap_pnl * scale_sheet, 4),
    }


def apply_triple_cash_to_audit_row(
    row: dict[str, Any],
    cfg: Any = None,
    *,
    capacity_total_pnl: float | None = None,
) -> dict[str, Any]:
    """Mutate Audit/Report ``row`` with triple-cash fields; blank when Max_Positions N/A.

    Call **after** Max_Positions / Avg_Positions / Median_Positions are on the row,
    and pass ``capacity_total_pnl`` from metrics before any 1M display rescale of Total_PNL.
    Legacy ``brt_cash`` / ``Total_PNL`` are left unchanged.
    """
    max_pos = int(_safe_float(row.get("Max_Positions"), 0))
    blank_keys = (
        "capacity_brt_cash",
        "effective_brt_cash",
        "sheet_brt_cash",
        "capacity_Total_PNL",
        "effective_Total_PNL",
        "sheet_PnL",
    )
    if max_pos <= 0:
        for k in blank_keys:
            row.setdefault(k, "")
        return row

    init = DEFAULT_INITIAL_CAPITAL
    mult = DEFAULT_AGGRESSIVE_MAX_MULTIPLE
    util = DEFAULT_MARGIN_UTILIZATION
    if cfg is not None:
        init = float(getattr(cfg, "initial_capital", init) or init)
        mult = float(getattr(cfg, "aggressive_max_multiple", mult) or mult)
        util = float(getattr(cfg, "margin_utilization", util) or util)

    fields = compute_triple_cash_audit_fields(
        max_positions=max_pos,
        avg_positions=_safe_float(row.get("Avg_Positions"), 0.0),
        median_positions=_safe_float(row.get("Median_Positions"), 0.0),
        capacity_total_pnl=capacity_total_pnl if capacity_total_pnl is not None else 0.0,
        initial_capital=init,
        aggressive_max_multiple=mult,
        margin_utilization=util,
    )
    row.update(fields)
    return row


def _parse_trade_date(s: Any) -> Optional[pd.Timestamp]:
    if s is None:
        return None
    text = str(s).strip()
    if len(text) < 8:
        return None
    try:
        if "-" in text:
            return pd.Timestamp(text[:10])
        return pd.Timestamp(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
    except Exception:
        return None


def _trade_attr(t: Any, *names: str) -> Any:
    if isinstance(t, dict):
        for n in names:
            if n in t:
                return t[n]
        return None
    for n in names:
        if hasattr(t, n):
            return getattr(t, n)
    return None


def max_concurrent_positions(closed: list[Any]) -> int:
    """Peak overlapping positions from closed trades (open through close day)."""
    if not closed:
        return 0
    events: list[tuple[pd.Timestamp, int]] = []
    for t in closed:
        dopen = _parse_trade_date(_trade_attr(t, "date_opened", "DATE_OPENED"))
        dclose = _parse_trade_date(_trade_attr(t, "date_closed", "DATE_CLOSED"))
        if dopen is None or dclose is None:
            continue
        events.append((dopen, 1))
        events.append((dclose, -1))
    if not events:
        return 0
    events.sort(key=lambda x: (x[0], -x[1]))
    cur, mx = 0, 0
    for _, delta in events:
        cur += delta
        mx = max(mx, cur)
    return mx


def resolve_max_positions(closed: list[Any], max_positions: int = 0) -> int:
    override = int(max_positions or 0)
    if override > 0:
        return override
    return max(max_concurrent_positions(closed), 1)


def apply_host_dollar_scale(
    closed: list[Any],
    open_trades: list[Any] | None,
    cfg: Any,
) -> tuple[float, float, int]:
    """Scale trade pnl_dollars to host per-slot notional; set cfg.brt_cash.

    Returns (adjusted_brt_cash, scale_applied, max_positions_used).
    """
    open_trades = open_trades or []
    max_pos = resolve_max_positions(closed, int(getattr(cfg, "max_positions", 0) or 0))
    adjusted = report_adjusted_brt_cash(
        max_pos,
        initial_capital=float(getattr(cfg, "initial_capital", DEFAULT_INITIAL_CAPITAL) or DEFAULT_INITIAL_CAPITAL),
        aggressive_max_multiple=float(
            getattr(cfg, "aggressive_max_multiple", DEFAULT_AGGRESSIVE_MAX_MULTIPLE) or DEFAULT_AGGRESSIVE_MAX_MULTIPLE
        ),
        margin_utilization=float(
            getattr(cfg, "margin_utilization", DEFAULT_MARGIN_UTILIZATION) or DEFAULT_MARGIN_UTILIZATION
        ),
    )
    orig = float(getattr(cfg, "brt_cash", 0) or 0)
    if orig <= 0:
        orig = float(getattr(cfg, "cash", 0) or 0)
    if orig <= 0:
        orig = adjusted
    scale = adjusted / orig if orig > 0 else 1.0
    if abs(scale - 1.0) >= 1e-12:
        for t in closed:
            if isinstance(t, dict):
                t["pnl_dollars"] = float(t.get("pnl_dollars", 0) or 0) * scale
            else:
                t.pnl_dollars = float(getattr(t, "pnl_dollars", 0) or 0) * scale
        for t in open_trades:
            if isinstance(t, dict):
                if "pnl_dollars" in t:
                    t["pnl_dollars"] = float(t.get("pnl_dollars", 0) or 0) * scale
            elif hasattr(t, "pnl_dollars"):
                t.pnl_dollars = float(getattr(t, "pnl_dollars", 0) or 0) * scale
    if hasattr(cfg, "brt_cash"):
        cfg.brt_cash = adjusted
    if hasattr(cfg, "cash"):
        cfg.cash = adjusted
    return adjusted, (scale if abs(scale - 1.0) >= 1e-12 else 1.0), max_pos


def write_aggressive_equity_curve(
    output_dir: Path | str,
    ts: str,
    equity: dict[str, Any],
    file_prefix: str,
) -> Optional[Path]:
    """Write P_EquityCurve_Aggressive_<ts>.csv (+ Regular when present)."""
    if not equity.get("_aggressive"):
        return None
    dates = equity.get("equity_dates")
    values = equity.get("equity_values")
    pos = equity.get("equity_positions")
    if not dates or not values or len(dates) != len(values):
        return None
    outp = Path(output_dir)
    init_sz = float(equity.get("_initial_account_size", 0) or 0)
    df_data: dict[str, Any] = {"Date": pd.to_datetime(dates), "Equity": values}
    if pos and len(pos) == len(values):
        df_data["Positions"] = pos
    if init_sz > 0:
        df_data["Equity_Pct_of_Initial"] = [(float(v) / init_sz - 1.0) * 100.0 for v in values]
    path = outp / f"{file_prefix}_EquityCurve_Aggressive_{ts}.csv"
    pd.DataFrame(df_data).to_csv(path, index=False)
    reg = equity.get("equity_values_regular")
    if reg and len(reg) == len(values):
        passive_df: dict[str, Any] = {"Date": pd.to_datetime(dates), "Equity": reg}
        if pos and len(pos) == len(values):
            passive_df["Positions"] = pos
        pd.DataFrame(passive_df).to_csv(outp / f"{file_prefix}_EquityCurve_Regular_{ts}.csv", index=False)
    return path


def compute_and_write_host_equity(
    *,
    output_dir: Path | str,
    ts: str,
    file_prefix: str,
    closed: list[Any],
    open_trades: list[Any],
    tickers: dict[str, pd.DataFrame],
    cfg: Any,
) -> dict[str, Any]:
    """Run BRT_DrawdownCalc.compute_equity_metrics and write EquityCurve(+Aggressive).

    Returns equity dict (may be empty on failure / skip).
    """
    if not closed or not tickers:
        return {}
    if not bool(getattr(cfg, "compute_equity_metrics", True)):
        return {}
    try:
        from BRT_DrawdownCalc import compute_equity_metrics
    except ImportError:
        try:
            from stock_analysis.BRT_DrawdownCalc import compute_equity_metrics  # type: ignore
        except ImportError:
            print(f"[{file_prefix}] compute_equity_metrics unavailable — skip host equity", flush=True)
            return {}

    cash = float(getattr(cfg, "brt_cash", 0) or getattr(cfg, "cash", 0) or 0)
    if cash <= 0:
        cash = report_adjusted_brt_cash(
            resolve_max_positions(closed, int(getattr(cfg, "max_positions", 0) or 0)),
            initial_capital=float(getattr(cfg, "initial_capital", DEFAULT_INITIAL_CAPITAL) or DEFAULT_INITIAL_CAPITAL),
            aggressive_max_multiple=float(
                getattr(cfg, "aggressive_max_multiple", DEFAULT_AGGRESSIVE_MAX_MULTIPLE) or DEFAULT_AGGRESSIVE_MAX_MULTIPLE
            ),
            margin_utilization=float(
                getattr(cfg, "margin_utilization", DEFAULT_MARGIN_UTILIZATION) or DEFAULT_MARGIN_UTILIZATION
            ),
        )
    aggressive = bool(getattr(cfg, "aggressive", False))
    try:
        equity = compute_equity_metrics(
            closed,
            open_trades or [],
            tickers,
            cash,
            initial_capital=float(getattr(cfg, "initial_capital", DEFAULT_INITIAL_CAPITAL) or DEFAULT_INITIAL_CAPITAL),
            aggressive=aggressive,
            aggressive_margin_interest=float(getattr(cfg, "aggressive_margin_interest", 0.10) or 0.10),
            aggressive_max_multiple=float(
                getattr(cfg, "aggressive_max_multiple", DEFAULT_AGGRESSIVE_MAX_MULTIPLE) or DEFAULT_AGGRESSIVE_MAX_MULTIPLE
            ),
            aggressive_avg_positions=(
                float(getattr(cfg, "aggressive_avg_positions", 0) or 0) or None
            ),
            aggressive_sizing_equity_cap=float(getattr(cfg, "aggressive_sizing_equity_cap", 10.0) or 10.0),
            margin_utilization=aggressive_sim_margin_utilization(
                aggressive,
                float(getattr(cfg, "margin_utilization", DEFAULT_MARGIN_UTILIZATION) or DEFAULT_MARGIN_UTILIZATION),
            ),
            aggressive_sell=str(getattr(cfg, "aggressive_sell", "false") or "false"),
            skip_passive_mtm_for_aggressive=bool(
                getattr(cfg, "equity_fast_aggressive", False) and aggressive
            ),
        )
    except Exception as e:
        print(f"[{file_prefix}] Host equity failed: {e}", flush=True)
        return {}

    outp = Path(output_dir)
    dates = equity.get("equity_dates")
    values = equity.get("equity_values")
    if dates and values and len(dates) == len(values):
        df_data: dict[str, Any] = {"Date": pd.to_datetime(dates), "Equity": values}
        pos = equity.get("equity_positions")
        if pos and len(pos) == len(values):
            df_data["Positions"] = pos
        reg = equity.get("equity_values_regular")
        if reg and len(reg) == len(values):
            df_data["Equity_Regular"] = reg
        pd.DataFrame(df_data).to_csv(outp / f"{file_prefix}_EquityCurve_{ts}.csv", index=False)
        raw = float(equity.get("_max_port_dd_raw", 0) or 0)
        init_sz = float(equity.get("_initial_account_size", 0) or 0)
        meta_row: dict[str, Any] = {
            "Initial_Account_Size": init_sz,
            "Max_Drawdown_fraction": raw,
            "Max_Drawdown_pct": equity.get("Max_Drawdown", ""),
            "Max_Days_Underwater": int(equity.get("Max_Days_Underwater", 0) or 0),
            "Pct_Days_Underwater": equity.get("Pct_Days_Underwater", ""),
            "Aggressive": bool(equity.get("_aggressive")),
            "Curve_Kind": "host_ohlc_mtm",
        }
        if equity.get("_aggressive"):
            meta_row["Aggressive_Max_Drawdown_fraction"] = float(equity.get("_aggressive_max_dd_raw", 0) or 0)
            meta_row["Aggressive_Max_Drawdown_pct"] = equity.get("Aggressive_Max_Drawdown", "")
            meta_row["Aggressive_Total_PNL"] = equity.get("_equity_total_pnl", "")
        pd.DataFrame([meta_row]).to_csv(outp / f"{file_prefix}_EquityMeta_{ts}.csv", index=False)
        print(
            f"[FILE] {file_prefix}_EquityCurve_{ts}.csv / EquityMeta (host OHLC MTM)",
            flush=True,
        )
    agg_path = write_aggressive_equity_curve(outp, ts, equity, file_prefix)
    if agg_path is not None:
        print(f"[FILE] Aggressive equity curve: {agg_path}", flush=True)
    return equity
