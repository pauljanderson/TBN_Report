#!/usr/bin/env python3
"""Start-date sensitivity on the locked live-style wallet (research only).

Paul: rerun official sizing from bad / random starts to see timing luck.
Stamp: drive/paul_experiments/live_style_startdates_20260918/

Reuses tools/risk2500_five_sys_20260917.py run_wallet with the locked
17.5% live-style lids. $7,500/mo wires OFF — those are 2026 cash-flow,
not sizing. HOLD. Not gold. Not DailyRun. Do not retune lids on the
worst start.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import random
import sys
from copy import copy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402

_FSPEC = importlib.util.spec_from_file_location(
    "risk2500_five_sys_20260917",
    REPO / "tools" / "risk2500_five_sys_20260917.py",
)
f = importlib.util.module_from_spec(_FSPEC)
assert _FSPEC.loader is not None
sys.modules["risk2500_five_sys_20260917"] = f
_FSPEC.loader.exec_module(f)

STAMP = "live_style_startdates_20260918"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
ACCOUNT = f.ACCOUNT
ASOF_ASKED = date(2026, 9, 18)
RNG_SEED = 20260918
RANDOM_LO = date(2010, 1, 4)
RANDOM_HI = date(2025, 1, 1)
REQUIRED_ASKED = [
    date(2025, 3, 1),
    date(2022, 6, 1),
    date(2021, 7, 1),
    date(2021, 1, 1),
    date(2020, 9, 1),
    date(2015, 9, 1),
]
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
R_ONE = 0.01
MAX_RISK = 50_000.0
ADV_FRAC = 0.01
NAME_CAP = 0.175
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
ET = f.ET
SPY_PATH = f.SPY_PATH
DD_DEF = (
    "Max drawdown % = peak-to-trough of that start’s Closed-only wallet equity "
    "(cash + open cost) after each event day, plus month-end mark-to-close of "
    "opens. Same proxy as the official live-style wallet. Not a full daily mark."
)

ORIGINAL_REQUEST = (
    "can you rerun our new sizing system using some bad start dates to see "
    "what it comes out to if my timing is bad by implementing it today. can "
    "you use 2025-03-01, 2022-06-01, 2021-07-01, 2021-01-01, 2020-09-01, "
    "2015-09-01 and 5 other random dates to start the system. I'd like to "
    "see how much each makes and would like to know the annuallized ROR "
    "since they will each be different time lengths"
)
PLAIN_ENGLISH = (
    "Same official live-style recipe — five sleeves StockBee (SB), Relative "
    "Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket "
    "Launcher (RL); Indicators (IND) out. Start $250,000 on each date. "
    "Each month risk the smaller of 1% of the account and $50,000. RSI "
    "dollars in = that risk ÷ 0.0651 (In-Sample average-loser freeze). "
    "Other systems: shares = risk ÷ (entry − stop). Shares ≤ 1% of 20-session "
    "average daily volume (ADV20). One ticker ≤ 17.5% of the account right "
    "then. Open stock cost ≤ 2× the account; pay 10.5% a year on borrowed "
    "money. When a new signal has no buying power, sell the most profitable "
    "open name (same as the official wallet). We do NOT pull $7,500 a month "
    "here — that wire is Paul’s 2026 living cash-flow, not the sizing rule. "
    "Six dates Paul named plus five dates drawn with seed 20260918 before "
    "any results were seen. Weekend / holiday starts move to the next regular "
    "trading session. Annualized rate of return (Ann ROR) is the compound "
    "growth rate that turns $250,000 into the ending pile over that many "
    "years: (end ÷ start)^(1 ÷ years) − 1. We also show buy-and-hold SPY "
    "(S&P 500 tracker, dividends reinvested) from the same start. Do not "
    "pick the best start as the ‘real’ number — that would be cherry-picking. "
    "HOLD research. Not gold. Not DailyRun."
)


def _load_spy() -> pd.DataFrame:
    if not SPY_PATH.is_file():
        raise SystemExit(f"missing {SPY_PATH}")
    df = pd.read_csv(SPY_PATH)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["Adj Close"] = pd.to_numeric(df["Adj Close"], errors="coerce")
    df = df.dropna(subset=["Close", "Adj Close"])
    df["d"] = df["Date"].dt.date
    return df.reset_index(drop=True)


def _sessions(df: pd.DataFrame) -> list[date]:
    return [d for d in df["d"].tolist() if d is not None]


def next_rth(asked: date, sessions: list[date]) -> date:
    for s in sessions:
        if s >= asked:
            return s
    raise SystemExit(f"no regular trading session on/after {asked.isoformat()}")


def last_bar_on_or_before(asked: date, sessions: list[date]) -> date:
    prior = [s for s in sessions if s <= asked]
    if not prior:
        raise SystemExit(f"no on-disk bar on/before {asked.isoformat()}")
    return prior[-1]


def years_span(start: date, end: date) -> float:
    return max((end - start).days / 365.25, 1e-9)


def ann_ror(end_eq: float, start_eq: float, years: float) -> Optional[float]:
    if start_eq <= 0 or years <= 0:
        return None
    if end_eq <= 0:
        return -1.0
    return (end_eq / start_eq) ** (1.0 / years) - 1.0


def _fmt_pct(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{100.0 * float(v):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct_pts(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _num(st: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        v = st.get(key)
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _maybe(st: dict[str, Any], key: str) -> Optional[float]:
    try:
        v = st.get(key)
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def freeze_random_starts(
    *,
    sessions: list[date],
    blocked: set[date],
    seed: int = RNG_SEED,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Draw n calendar dates, snap to next RTH, reject overlap. No PnL look."""
    rng = random.Random(seed)
    span = (RANDOM_HI - RANDOM_LO).days
    out: list[dict[str, Any]] = []
    used = set(blocked)
    tries = 0
    while len(out) < n:
        tries += 1
        if tries > 20_000:
            raise SystemExit("could not freeze 5 non-overlapping random starts")
        asked_d = RANDOM_LO + timedelta(days=int(rng.randint(0, span)))
        rth = next_rth(asked_d, sessions)
        if rth in used:
            continue
        used.add(rth)
        used.add(asked_d)
        out.append(
            {
                "kind": "random",
                "asked": asked_d.isoformat(),
                "start": rth.isoformat(),
                "snapped": rth != asked_d,
            }
        )
    return out


def spy_from_start(
    df: pd.DataFrame,
    start: date,
    through: date,
) -> dict[str, Any]:
    chunk = df[(df["d"] >= start) & (df["d"] <= through)]
    if chunk.empty:
        raise SystemExit(f"no SPY bars {start} → {through}")
    first = chunk.iloc[0]
    last = chunk.iloc[-1]
    adj0 = float(first["Adj Close"])
    adj1 = float(last["Adj Close"])
    px0 = float(first["Close"])
    px1 = float(last["Close"])
    eq = (ACCOUNT * chunk["Adj Close"] / adj0).astype(float).tolist()
    years = years_span(start, through)
    tr_end = ACCOUNT * (adj1 / adj0)
    price_end = ACCOUNT * (px1 / px0)
    return {
        "start_date": first["d"].isoformat(),
        "end_date": last["d"].isoformat(),
        "adj0": adj0,
        "adj1": adj1,
        "px0": px0,
        "px1": px1,
        "tr_end": tr_end,
        "price_end": price_end,
        "tr_mult": adj1 / adj0,
        "price_mult": px1 / px0,
        "made": tr_end - ACCOUNT,
        "years": years,
        "ann_ror": ann_ror(tr_end, ACCOUNT, years),
        "max_dd_pct": f._max_dd_pct(eq),
        "series": "SPY Adj Close total return (dividends reinvested)",
    }


def write_frozen_starts(rows: list[dict[str, Any]], through: date) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "stamp": STAMP,
        "rng_seed": RNG_SEED,
        "random_window": [RANDOM_LO.isoformat(), RANDOM_HI.isoformat()],
        "asof_asked": ASOF_ASKED.isoformat(),
        "asof_bar": through.isoformat(),
        "withdrawals": 0.0,
        "withdraw_note": (
            "$7,500/mo wires excluded — personal 2026 cash-flow, not sizing."
        ),
        "starts_frozen_before_results": True,
        "starts": rows,
    }
    (OUT_DIR / "starts.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "## What you asked",
        "",
        ORIGINAL_REQUEST,
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "## Frozen starts (written BEFORE any wallet run)",
        "",
        f"- RNG seed: **{RNG_SEED}**",
        f"- Random window: {RANDOM_LO.isoformat()} through {RANDOM_HI.isoformat()} "
        "(uniform calendar days, then next regular trading session)",
        f"- As-of asked: {ASOF_ASKED.isoformat()}; last on-disk bar: {through.isoformat()}",
        "- $7,500/mo withdrawals: **OFF**",
        "",
        "### Required (Paul)",
        "",
    ]
    for row in rows:
        if row["kind"] != "required":
            continue
        snap = " (next RTH)" if row.get("snapped") else ""
        lines.append(f"- asked {row['asked']} → start {row['start']}{snap}")
    lines.extend(["", "### Random (seed 20260918 — listed before equity table)", "",])
    for row in rows:
        if row["kind"] != "random":
            continue
        snap = " (next RTH)" if row.get("snapped") else ""
        lines.append(f"- asked {row['asked']} → start {row['start']}{snap}")
    lines.extend(
        [
            "",
            "## Equity / Ann ROR",
            "",
            "_Wallet results are appended after the runs. Do not pick KEEP from the best start._",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _run_one(
    static: list[Any],
    *,
    start: date,
    through: date,
    label: str,
) -> dict[str, Any]:
    book = [copy(t) for t in static if t.opened >= start]
    prev_start = f.START
    f.START = start
    try:
        arm = f._run_arm(
            book,
            rank=FIVE_RANK,
            rotate="winner",
            withdraw=False,
            label=label,
            risk_frac=R_ONE,
            through=through,
            name_cap_frac=NAME_CAP,
            max_risk_dollar=MAX_RISK,
            adv_frac=ADV_FRAC,
        )
    finally:
        f.START = prev_start
    return arm


def _pack_row(
    spec: dict[str, Any],
    arm: dict[str, Any],
    spy: dict[str, Any],
    through: date,
) -> dict[str, Any]:
    led = arm["led"]
    st = arm["stats_full"]
    start = date.fromisoformat(spec["start"])
    years = years_span(start, through)
    end_eq = float(led.end_equity)
    wallet_ann = ann_ror(end_eq, ACCOUNT, years)
    max_dd = float(led.max_dd_pct)
    calmar = None
    if wallet_ann is not None and max_dd and abs(max_dd) > 1e-12:
        calmar = (100.0 * wallet_ann) / abs(max_dd)
    n_fill = int(led.n_full) + int(led.n_scaled)
    exits = st.get("exits") or {}
    return {
        "kind": spec["kind"],
        "asked": spec["asked"],
        "start": spec["start"],
        "snapped": bool(spec.get("snapped")),
        "through": through.isoformat(),
        "years": years,
        "end": end_eq,
        "made": end_eq - ACCOUNT,
        "ann_ror": wallet_ann,
        "max_dd_pct": max_dd,
        "max_dd_peak": float(led.max_dd_peak),
        "max_dd_trough": float(led.max_dd_trough),
        "calmar": calmar,
        "spy_end": float(spy["tr_end"]),
        "spy_made": float(spy["made"]),
        "spy_ann_ror": spy["ann_ror"],
        "spy_max_dd_pct": float(spy["max_dd_pct"]),
        "spy_tr_mult": float(spy["tr_mult"]),
        "interest": float(led.interest),
        "withdrawals": float(led.withdrawals),
        "identity": float(led.identity_err),
        "n_rotate": int(led.n_rotate),
        "n_name_capped": int(led.n_name_capped),
        "n_skip_name": int(led.n_skip_name),
        "n_skip_bp": int(led.n_skip_bp),
        "n_full": int(led.n_full),
        "n_scaled": int(led.n_scaled),
        "n_fill": n_fill,
        "n_risk_1pct_bound": int(led.n_risk_1pct_bound),
        "n_risk_50k_bound": int(led.n_risk_50k_bound),
        "n_adv_clipped": int(led.n_adv_clipped),
        "n_skip_adv": int(led.n_skip_adv),
        "n": _num(st, "n"),
        "win_pct": _maybe(st, "win_pct"),
        "avg_pnl_pct": _maybe(st, "avg_pnl_pct"),
        "avg_wo_max": _maybe(st, "avg_wo_max"),
        "pf": _maybe(st, "pf"),
        "expectancy_pct": _maybe(st, "expectancy_pct"),
        "avg_win_pct": _maybe(st, "avg_win_pct"),
        "avg_loss_pct": _maybe(st, "avg_loss_pct"),
        "book_ann_ror": _maybe(st, "ann_ror"),
        "book_max_dd": _maybe(st, "max_dd"),
        "book_calmar": _maybe(st, "calmar"),
        "sharpe": _maybe(st, "sharpe"),
        "profit_per_cap_day": _maybe(st, "profit_per_cap_day"),
        "capital_days": _num(st, "capital_days"),
        "avg_days": _maybe(st, "avg_days"),
        "median_days": _maybe(st, "median_days"),
        "p90_days": _maybe(st, "p90_days"),
        "losing_streak": _maybe(st, "losing_streak"),
        "exits": {str(k): int(v) for k, v in exits.items()},
        "n_is": _num(arm.get("stats_is") or {}, "n"),
        "n_oos": _num(arm.get("stats_oos") or {}, "n"),
        "wr_is": _maybe(arm.get("stats_is") or {}, "win_pct"),
        "wr_oos": _maybe(arm.get("stats_oos") or {}, "win_pct"),
        "avg_is": _maybe(arm.get("stats_is") or {}, "avg_pnl_pct"),
        "avg_oos": _maybe(arm.get("stats_oos") or {}, "avg_pnl_pct"),
    }


def _ask_block() -> str:
    return f"""
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>"""


def _sortable_head(pairs: list[tuple[str, str]]) -> str:
    return "".join(f.r._sortable_th(h, t) for h, t in pairs)


def _lead_table(rows: list[dict[str, Any]]) -> str:
    head = _sortable_head(
        [
            ("Kind", "text"),
            ("Asked", "date"),
            ("Start (RTH)", "date"),
            ("Years", "num"),
            ("End $", "num"),
            ("$ made", "num"),
            ("Ann ROR %", "num"),
            ("SPY Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("SPY Max DD %", "num"),
            ("SPY end $", "num"),
        ]
    )
    body = ""
    for r in rows:
        snap = " *" if r.get("snapped") else ""
        body += (
            "<tr>"
            f"<td>{html_mod.escape(r['kind'])}</td>"
            f"<td>{html_mod.escape(r['asked'])}</td>"
            f"<td>{html_mod.escape(r['start'])}{snap}</td>"
            f"<td>{r['years']:.3f}</td>"
            f"<td>{format_money(r['end'])}</td>"
            f"<td>{format_money(r['made'])}</td>"
            f"<td>{_fmt_pct(r['ann_ror'])}</td>"
            f"<td>{_fmt_pct(r['spy_ann_ror'])}</td>"
            f"<td>{_fmt_pct_pts(r['max_dd_pct'])}</td>"
            f"<td>{_fmt_pct_pts(r['spy_max_dd_pct'])}</td>"
            f"<td>{format_money(r['spy_end'])}</td>"
            "</tr>"
        )
    return (
        '<p class="small">Click column headers to sort. * = asked date was not a '
        "regular trading session; book starts on the next session. Ann ROR = "
        "(end ÷ $250,000)^(1 ÷ years) − 1 on the wallet pile. SPY is $250,000 "
        "buy-and-hold total return from the same start. $ made = end − $250,000. "
        "Do not rank KEEP by the best start.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _book_table(rows: list[dict[str, Any]]) -> str:
    head = _sortable_head(
        [
            ("Start (RTH)", "date"),
            ("Kind", "text"),
            ("N closed", "num"),
            ("Win %", "num"),
            ("Avg %", "num"),
            ("AVG% w/o max", "num"),
            ("PF", "num"),
            ("Expectancy %", "num"),
            ("Avg win %", "num"),
            ("Avg loss %", "num"),
            ("Wallet Ann ROR %", "num"),
            ("Wallet Max DD %", "num"),
            ("Calmar (wallet)", "num"),
            ("Book Ann ROR %", "num"),
            ("Sharpe", "num"),
            ("Profit / cap day", "num"),
            ("Capital days", "num"),
            ("Avg days held", "num"),
            ("Median days", "num"),
            ("P90 days", "num"),
            ("Losing streak", "num"),
            ("Fills", "num"),
            ("Rotates", "num"),
            ("BP-skip", "num"),
            ("Name-capped", "num"),
            ("Interest $", "num"),
            ("IS N", "num"),
            ("OOS N", "num"),
            ("IS Win %", "num"),
            ("OOS Win %", "num"),
            ("IS Avg %", "num"),
            ("OOS Avg %", "num"),
        ]
    )
    body = ""
    for r in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(r['start'])}</td>"
            f"<td>{html_mod.escape(r['kind'])}</td>"
            f"<td>{int(r['n'])}</td>"
            f"<td>{_fmt_pct_pts(r['win_pct'])}</td>"
            f"<td>{_fmt_pct_pts(r['avg_pnl_pct'])}</td>"
            f"<td>{_fmt_pct_pts(r['avg_wo_max'])}</td>"
            f"<td>{_fmt_num(r['pf'])}</td>"
            f"<td>{_fmt_pct_pts(r['expectancy_pct'])}</td>"
            f"<td>{_fmt_pct_pts(r['avg_win_pct'])}</td>"
            f"<td>{_fmt_pct_pts(r['avg_loss_pct'])}</td>"
            f"<td>{_fmt_pct(r['ann_ror'])}</td>"
            f"<td>{_fmt_pct_pts(r['max_dd_pct'])}</td>"
            f"<td>{_fmt_num(r['calmar'])}</td>"
            f"<td>{_fmt_pct_pts(r['book_ann_ror'])}</td>"
            f"<td>{_fmt_num(r['sharpe'])}</td>"
            f"<td>{format_money(r['profit_per_cap_day']) if r['profit_per_cap_day'] is not None else '—'}</td>"
            f"<td>{r['capital_days']:.1f}</td>"
            f"<td>{_fmt_num(r['avg_days'], 1)}</td>"
            f"<td>{_fmt_num(r['median_days'], 1)}</td>"
            f"<td>{_fmt_num(r['p90_days'], 1)}</td>"
            f"<td>{'—' if r['losing_streak'] is None else str(int(r['losing_streak']))}</td>"
            f"<td>{int(r['n_fill'])}</td>"
            f"<td>{int(r['n_rotate'])}</td>"
            f"<td>{int(r['n_skip_bp'])}</td>"
            f"<td>{int(r['n_name_capped'])}</td>"
            f"<td>{format_money(r['interest'])}</td>"
            f"<td>{int(r['n_is'])}</td>"
            f"<td>{int(r['n_oos'])}</td>"
            f"<td>{_fmt_pct_pts(r['wr_is'])}</td>"
            f"<td>{_fmt_pct_pts(r['wr_oos'])}</td>"
            f"<td>{_fmt_pct_pts(r['avg_is'])}</td>"
            f"<td>{_fmt_pct_pts(r['avg_oos'])}</td>"
            "</tr>"
        )
    return (
        '<p class="small">Click headers to sort. Wallet Ann ROR is the pile CAGR '
        "Paul asked for. Book Ann ROR is the overlay trade-level formula (capital-turn). "
        "IS = entry before 2024-01-01; OOS report-only — do not retune lids. "
        "Sheet / Total PnL $ omitted (wallet $ made is on the lead table).</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _exit_table(rows: list[dict[str, Any]]) -> str:
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.get("exits") or {}:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    keys.sort()
    pairs = [("Start (RTH)", "date"), ("N closed", "num")]
    pairs.extend((k, "num") for k in keys)
    head = _sortable_head(pairs)
    body = ""
    for r in rows:
        body += f"<tr><td>{html_mod.escape(r['start'])}</td><td>{int(r['n'])}</td>"
        for k in keys:
            body += f"<td>{int((r.get('exits') or {}).get(k, 0))}</td>"
        body += "</tr>"
    return (
        '<p class="small">Click headers to sort. Exit mix from sized closed overlay rows.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _freeze_table() -> str:
    rows = [
        ("Systems", "SB, RSI, VZ, MTS, RL (IND out)"),
        ("Start equity", format_money(ACCOUNT)),
        ("Monthly risk", "min(1% beginning-of-month equity, $50,000)"),
        ("ADV lid", "shares ≤ 1% ADV20"),
        ("Name cap", "notional ≤ 17.5% of current equity"),
        ("RSI slot", "invested = risk / 0.0651 (IS avg-loss freeze)"),
        ("Leverage", f"open ≤ {LEVERAGE:.0f}× equity"),
        ("Margin interest", f"{MARGIN_RATE:.1%} annual on debit"),
        ("No buying power", "sell most-profitable open name (official wallet)"),
        ("$7,500/mo wires", "OFF — 2026 personal cash-flow, not sizing"),
        ("Wallet", "tools/risk2500_five_sys_20260917.py run_wallet"),
        ("Official freeze stamp", "risk_1pct_50k_adv_17name_20260917"),
    ]
    body = "".join(
        f"<tr><td>{html_mod.escape(a)}</td><td>{html_mod.escape(b)}</td></tr>"
        for a, b in rows
    )
    head = _sortable_head([("Knob", "text"), ("Freeze", "text")])
    return (
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _range_note(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    scored = [r for r in rows if r.get("ann_ror") is not None]
    if not scored:
        return "No scored starts.", {}
    rors = [float(r["ann_ror"]) for r in scored]
    worst = min(scored, key=lambda r: float(r["ann_ror"]))
    best = max(scored, key=lambda r: float(r["ann_ror"]))
    worst_end = min(scored, key=lambda r: float(r["end"]))
    extras = {
        "ann_ror_min": min(rors),
        "ann_ror_max": max(rors),
        "worst_start": worst["start"],
        "worst_asked": worst["asked"],
        "worst_kind": worst["kind"],
        "worst_ann": worst["ann_ror"],
        "worst_end": worst["end"],
        "worst_made": worst["made"],
        "worst_dd": worst["max_dd_pct"],
        "best_start": best["start"],
        "best_asked": best["asked"],
        "best_kind": best["kind"],
        "best_ann": best["ann_ror"],
        "best_end": best["end"],
        "worst_end_start": worst_end["start"],
        "n_starts": len(scored),
    }
    text = (
        f"HOLD — start-date sensitivity, not a knob race. Ann ROR range "
        f"{_fmt_pct(min(rors))} to {_fmt_pct(max(rors))} across {len(scored)} starts. "
        f"Worst Ann ROR (not a pick): {worst['start']} ({worst['kind']}, asked "
        f"{worst['asked']}) {_fmt_pct(worst['ann_ror'])}, end {format_money(worst['end'])}, "
        f"$ made {format_money(worst['made'])}, Max DD {_fmt_pct_pts(worst['max_dd_pct'])}. "
        f"Best Ann ROR (not a pick): {best['start']} ({best['kind']}) {_fmt_pct(best['ann_ror'])}, "
        f"end {format_money(best['end'])}. Do not retune lids on the worst date. "
        f"Not gold. Not DailyRun."
    )
    return text, extras


def build_compare(
    *,
    rows: list[dict[str, Any]],
    verdict: str,
    extras: dict[str, Any],
    through: date,
    generated: datetime,
    sources: list[str],
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    randoms = [r for r in rows if r["kind"] == "random"]
    rand_lis = "".join(
        f"<li>asked {html_mod.escape(r['asked'])} → RTH {html_mod.escape(r['start'])}"
        f"{' (snapped)' if r.get('snapped') else ''}</li>"
        for r in randoms
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live-style start-date sensitivity — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Live-style start-date sensitivity</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Official live-style lids. As-of last on-disk bar
{through.isoformat()} (asked {ASOF_ASKED.isoformat()}).
<strong>HOLD. Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
{_ask_block()}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Headline</h2>
<p>Eleven $250,000 books, same sizing recipe, different start dates. Ann ROR
range <strong>{_fmt_pct(extras.get('ann_ror_min'))}</strong> to
<strong>{_fmt_pct(extras.get('ann_ror_max'))}</strong>.
Worst start (label only, not a pick): <strong>{html_mod.escape(str(extras.get('worst_start')))}</strong>
at {_fmt_pct(extras.get('worst_ann'))}.
Best start (label only, not a pick): <strong>{html_mod.escape(str(extras.get('best_start')))}</strong>
at {_fmt_pct(extras.get('best_ann'))}.</p>
</section>
<section>
<h2>Frozen random starts (seed {RNG_SEED}) — listed before results were used</h2>
<p class="small">Uniform calendar draw {RANDOM_LO.isoformat()} through
{RANDOM_HI.isoformat()}, then next regular trading session. Rejected if it
landed on a required date. Frozen to <code>starts.json</code> before wallets ran.</p>
<ul>{rand_lis}</ul>
</section>
<section>
<h2>Lead — wallet pile by start</h2>
{_lead_table(rows)}
</section>
<section>
<h2>Locked freeze (same on every book)</h2>
{_freeze_table()}
</section>
<section>
<h2>Book quality (canonical set, one row per start)</h2>
{_book_table(rows)}
</section>
<section>
<h2>Exit mix</h2>
{_exit_table(rows)}
</section>
<section>
<h2>How to read this</h2>
<ul>
<li>Do <strong>not</strong> treat the best start as the official live-style number.</li>
<li>Do <strong>not</strong> retune the $50k / ADV / 17.5% lids because one start looks ugly.</li>
<li>$7,500/mo wires are off. The official 2010 compound page still includes them for Paul’s 2026 cash-flow story.</li>
<li>Later-year paper dollars can still be capacity fiction (tight stops + 1% of a growing pile + 2×). Read Max DD and vs SPY, not only the ending pile.</li>
<li>OOS (entry ≥ 2024-01-01) is report-only.</li>
</ul>
</section>
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Official freeze: <code>risk_1pct_50k_adv_17name_20260917</code>.
Not gold. Not DailyRun.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def write_baseline_final(
    *,
    rows: list[dict[str, Any]],
    verdict: str,
    extras: dict[str, Any],
    through: date,
    sources: list[str],
) -> None:
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "## What you asked",
        "",
        ORIGINAL_REQUEST,
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "## Tag: HOLD",
        "",
        verdict,
        "",
        "## Frozen starts (written BEFORE any wallet run)",
        "",
        f"- RNG seed: **{RNG_SEED}** (`random.Random({RNG_SEED})`)",
        f"- Random window: {RANDOM_LO.isoformat()} through {RANDOM_HI.isoformat()} "
        "(uniform calendar days → next regular trading session)",
        f"- As-of asked: {ASOF_ASKED.isoformat()}; last on-disk bar: {through.isoformat()}",
        "- Start equity: $250,000 on the start date; signals with entry ≥ start only",
        "",
        "### Required (Paul)",
        "",
    ]
    for r in rows:
        if r["kind"] != "required":
            continue
        snap = " (next RTH)" if r.get("snapped") else ""
        lines.append(f"- asked {r['asked']} → start {r['start']}{snap}")
    lines.extend(
        [
            "",
            "### Random (seed 20260918 — listed before the equity table)",
            "",
        ]
    )
    for r in rows:
        if r["kind"] != "random":
            continue
        snap = " (next RTH)" if r.get("snapped") else ""
        lines.append(f"- asked {r['asked']} → start {r['start']}{snap}")
    lines.extend(
        [
            "",
            "## Locked live-style freeze (every book)",
            "",
            "- 5-sys: SB, RSI, VZ, MTS, RL (IND out)",
            f"- Account ${ACCOUNT:,.0f} on the start date",
            "- **$7,500/mo withdrawals: OFF** — personal 2026 cash-flow, not sizing",
            f"- Margin {MARGIN_RATE:.1%}; leverage {LEVERAGE:.0f}×; sell-winner when no BP",
            "- risk = min(1% beginning-of-month equity, $50,000)",
            "- shares ≤ 1% ADV20",
            "- notional ≤ 17.5% of current equity",
            "- RSI size = risk / 0.0651 (IS avg-loss freeze)",
            "",
            "## Equity / Ann ROR",
            "",
            "Ann ROR = (end / 250000) ** (1 / years) − 1. Years = (as-of − start) / 365.25.",
            "Do not rank KEEP by the best start (selection).",
            "",
            f"- Ann ROR range: {_fmt_pct(extras.get('ann_ror_min'))} to {_fmt_pct(extras.get('ann_ror_max'))}",
            f"- Worst Ann ROR (not a pick): {extras.get('worst_start')} "
            f"({extras.get('worst_kind')}) {_fmt_pct(extras.get('worst_ann'))} "
            f"end {format_money(float(extras.get('worst_end') or 0))} "
            f"Max DD {_fmt_pct_pts(extras.get('worst_dd'))}",
            f"- Best Ann ROR (not a pick): {extras.get('best_start')} "
            f"({extras.get('best_kind')}) {_fmt_pct(extras.get('best_ann'))}",
            "",
            "| Kind | Asked | Start | Years | End $ | $ made | Ann ROR | SPY Ann ROR | Max DD |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in rows:
        lines.append(
            f"| {r['kind']} | {r['asked']} | {r['start']} | {r['years']:.3f} | "
            f"{format_money(r['end'])} | {format_money(r['made'])} | "
            f"{_fmt_pct(r['ann_ror'])} | {_fmt_pct(r['spy_ann_ror'])} | "
            f"{_fmt_pct_pts(r['max_dd_pct'])} |"
        )
    lines.extend(["", "## Sources", ""])
    for s in sources:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("Research only. Not gold. Not DailyRun. No lid retune on the worst start.")
    lines.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def write_hypothesis(verdict: str) -> None:
    text = f"""# HYPOTHESIS — {STAMP}

## Question
If the official live-style sizing book is turned on on a “bad” (or random) calendar
day instead of 2010-01-04, how much does the $250,000 pile make through the
as-of bar, and what is the annualized rate of return (Ann ROR) given the
different lengths?

## One change
Start date of the official wallet. Lids frozen.

## Freeze
- 5-sys: SB, RSI, VZ, MTS, RL (IND out)
- $250,000 on the start date; entries ≥ start only
- risk = min(1% BOM equity, $50k)
- shares ≤ 1% ADV20
- notional ≤ 17.5% current equity
- RSI invested = risk / 0.0651 (IS avg-loss freeze)
- open ≤ 2×; 10.5% margin interest; sell-winner when no buying power
- **$7,500/mo withdrawals OFF** (2026 personal cash-flow, not sizing)

## Random protocol
Seed **{RNG_SEED}**. Five dates drawn uniformly from {RANDOM_LO.isoformat()}
through {RANDOM_HI.isoformat()} **before** any wallet result. Next regular
trading session if the draw is not a session. No overlap with the six required
dates. Listed in BASELINE before the equity table.

## Metric
Wallet Ann ROR = (end / 250000)^(1 / years) − 1, years = (as-of − start) / 365.25.
Compare each start to SPY $250k buy-and-hold total return from the same start.

## Tag
HOLD

## Verdict
{verdict}

## Promotion
HOLD research. Not gold. Not DailyRun. Do not retune lids on the worst start.
Do not treat the best start as the official number (selection).
"""
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return str(obj)


def run() -> int:
    spy_df = _load_spy()
    sessions = _sessions(spy_df)
    through = last_bar_on_or_before(ASOF_ASKED, sessions)
    print(f"[asof] asked={ASOF_ASKED.isoformat()} last_bar={through.isoformat()}", flush=True)

    required: list[dict[str, Any]] = []
    blocked: set[date] = set()
    for asked in REQUIRED_ASKED:
        rth = next_rth(asked, sessions)
        required.append(
            {
                "kind": "required",
                "asked": asked.isoformat(),
                "start": rth.isoformat(),
                "snapped": rth != asked,
            }
        )
        blocked.add(asked)
        blocked.add(rth)

    randoms = freeze_random_starts(sessions=sessions, blocked=blocked, seed=RNG_SEED, n=5)
    specs = required + randoms
    write_frozen_starts(specs, through)
    print("[freeze] starts written before wallets:", flush=True)
    for row in specs:
        print(
            f"  {row['kind']:8} asked={row['asked']} start={row['start']}"
            f"{' SNAP' if row.get('snapped') else ''}",
            flush=True,
        )

    static = f.load_static(FIVE)
    print(f"[load] 5-sys overlay n={len(static)}", flush=True)

    rows: list[dict[str, Any]] = []
    for spec in specs:
        start = date.fromisoformat(spec["start"])
        label = f"{spec['kind']}_{spec['start']}"
        print(f"[book] {label} n_src>={sum(1 for t in static if t.opened >= start)}", flush=True)
        arm = _run_one(static, start=start, through=through, label=label)
        spy = spy_from_start(spy_df, start, through)
        pack = _pack_row(spec, arm, spy, through)
        rows.append(pack)
        print(
            f"  end={pack['end']:.2f} made={pack['made']:.2f} years={pack['years']:.3f} "
            f"ann={_fmt_pct(pack['ann_ror'])} spy_ann={_fmt_pct(pack['spy_ann_ror'])} "
            f"dd={_fmt_pct_pts(pack['max_dd_pct'])} wd={pack['withdrawals']:.2f} "
            f"ident={pack['identity']:.6f}",
            flush=True,
        )

    verdict, extras = _range_note(rows)
    sources = [
        "overlays: risk2500_monthly_20260917 (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {SPY_PATH.as_posix()} Adj Close total return",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "LOCKED live-style freeze: risk=min(1% BOM, $50k) AND shares≤1% ADV20 "
        "AND notional≤17.5% current equity",
        "official stamp: risk_1pct_50k_adv_17name_20260917",
        "rotate=winner; withdraw=False ($7,500/mo OFF)",
        f"RNG seed {RNG_SEED}; randoms frozen in starts.json before results",
        DD_DEF,
    ]
    generated = datetime.now(tz=ET)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = build_compare(
        rows=rows,
        verdict=verdict,
        extras=extras,
        through=through,
        generated=generated,
        sources=sources,
    )
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    write_baseline_final(
        rows=rows,
        verdict=verdict,
        extras=extras,
        through=through,
        sources=sources,
    )
    write_hypothesis(verdict)
    summary = {
        "stamp": STAMP,
        "tag": "HOLD",
        "asof_asked": ASOF_ASKED.isoformat(),
        "asof_bar": through.isoformat(),
        "rng_seed": RNG_SEED,
        "withdrawals": 0.0,
        "verdict": verdict,
        "extras": extras,
        "rows": rows,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(_jsonable(summary), indent=2), encoding="utf-8"
    )
    print(verdict, flush=True)
    print(f"[write] {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
