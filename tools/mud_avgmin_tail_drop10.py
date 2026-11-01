#!/usr/bin/env python3
"""Why filtered-long Ann ROR >> shorts; drop top 10% trades and rescore."""
from __future__ import annotations

import html as html_mod
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
for _p in (_PE, _REPO / "tools", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    max_dd_pct_from_closed_pnl_by_date,
)
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = _PE / "mud_avg_min_filter_ab_20261005"
IS_CUT = date(2024, 1, 1)
ASK = (
    "how is the Ann ROR so much larger for the longs than it is for the shorts "
    "when the avg. per trade is 1/3. is there a heavy right tail. what if we "
    "take out the top 10% trades for each?"
)
PLAIN = (
    "Annualized rate of return (Ann ROR) is not the same as average percent "
    "per trade. It also depends on how much cash sits in each trade and how "
    "many calendar days the average trade is held. We checked whether a few "
    "huge winners drive the long sleeve, then rescored both sleeves after "
    "dropping the best 10% of trades."
)


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _dated(df: pd.DataFrame) -> list[tuple[Any, float]]:
    tmp = pd.DataFrame(
        {
            "c": pd.to_datetime(df["DATE_CLOSED"], errors="coerce"),
            "d": pd.to_numeric(df["PNL_DOLLARS"], errors="coerce"),
        }
    ).dropna()
    if tmp.empty:
        return []
    g = tmp.groupby(tmp["c"].dt.date)["d"].sum()
    return [(d, float(v)) for d, v in g.items() if math.isfinite(v)]


def _slice_ann(df: pd.DataFrame) -> Optional[float]:
    if len(df) == 0:
        return None
    pnl_d = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    days = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    cash = float(pd.to_numeric(df["ENTRY_NOTIONAL"], errors="coerce").mean())
    days_ok = days[days > 0]
    avg_days = float(days_ok.mean()) if len(days_ok) else 0.0
    if not cash or avg_days <= 0:
        return None
    return ann_ror_from_closed(
        total_pnl=float(pnl_d.sum()),
        n_trades=len(df),
        avg_days_held=avg_days,
        brt_cash=cash,
    )


def book_row(name: str, df: pd.DataFrame) -> dict[str, Any]:
    pnl = pd.to_numeric(df["PNL_PCT"], errors="coerce")
    pnl_d = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    days = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    cash_s = pd.to_numeric(df["ENTRY_NOTIONAL"], errors="coerce")
    n = len(df)
    cash = float(cash_s.mean()) if cash_s.notna().any() else None
    days_ok = days[days > 0]
    avg_days = float(days_ok.mean()) if len(days_ok) else None
    total = float(pnl_d.sum()) if pnl_d.notna().any() else 0.0
    turn = (total / (cash * n)) if cash and n else None
    ann = (
        ann_ror_from_closed(
            total_pnl=total, n_trades=n, avg_days_held=avg_days, brt_cash=cash
        )
        if cash and avg_days and n
        else None
    )
    opened = pd.to_datetime(df["DATE_OPENED"], errors="coerce")
    mdd = max_dd_pct_from_closed_pnl_by_date(
        _dated(df), initial_account=DEFAULT_INITIAL_ACCOUNT
    )
    top_cut = float(pnl.quantile(0.9)) if n else None
    top_mask = pnl >= top_cut if top_cut is not None else pd.Series(False, index=df.index)
    top_share = (
        float(pnl_d[top_mask].sum() / total * 100) if total and top_mask.any() else None
    )
    return {
        "name": name,
        "n": n,
        "win_pct": float((pnl > 0).mean() * 100) if n else None,
        "avg_pct": float(pnl.mean()) if n else None,
        "med_pct": float(pnl.median()) if n else None,
        "p90": float(pnl.quantile(0.9)) if n else None,
        "p95": float(pnl.quantile(0.95)) if n else None,
        "p99": float(pnl.quantile(0.99)) if n else None,
        "max_pct": float(pnl.max()) if n else None,
        "skew_pct": float(pnl.skew()) if n > 2 else None,
        "avg_d": float(pnl_d.mean()) if n else None,
        "med_d": float(pnl_d.median()) if n else None,
        "max_d": float(pnl_d.max()) if n else None,
        "skew_d": float(pnl_d.skew()) if n > 2 else None,
        "cash": cash,
        "avg_days": avg_days,
        "total_pnl": total,
        "turn": turn,
        "ann": ann,
        "ann_is": _slice_ann(df[opened < pd.Timestamp(IS_CUT)]),
        "ann_oos": _slice_ann(df[opened >= pd.Timestamp(IS_CUT)]),
        "max_dd": mdd,
        "top10_pct_share_of_dollars": top_share,
        "avg_pct_wo_max": float(pnl.drop(pnl.idxmax()).mean()) if n > 1 else None,
    }


def drop_top10(df: pd.DataFrame, col: str = "PNL_PCT") -> tuple[pd.DataFrame, float]:
    s = pd.to_numeric(df[col], errors="coerce")
    thr = float(s.quantile(0.9))
    return df.loc[s < thr].copy(), thr


def fmt(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return str(v)


def main() -> int:
    longs = pd.read_csv(STAMP / "MUD_Closed_longs_avgmin_261005223347.csv", low_memory=False)
    shorts = pd.read_csv(STAMP / "MUD_Closed_shorts_avgmin_261005223347.csv", low_memory=False)

    rows: list[dict[str, Any]] = []
    detail: dict[str, dict[str, Any]] = {}
    for label, df in (("Longs", longs), ("Shorts", shorts)):
        full = book_row(f"{label} (filtered)", df)
        rows.append(full)
        detail[label] = full
        kept, thr = drop_top10(df, "PNL_PCT")
        rows.append(book_row(f"{label} drop top 10% by PnL%", kept))
        kept_d, thr_d = drop_top10(df, "PNL_DOLLARS")
        rows.append(book_row(f"{label} drop top 10% by PnL$", kept_d))
        print(f"{label}: top10% PnL% cut={thr:.4f}  top10% $ cut={thr_d:.2f}", flush=True)

    # Console explanation
    L, S = detail["Longs"], detail["Shorts"]
    print("\n=== Why Ann ROR can diverge from Avg PnL% ===", flush=True)
    print(
        f"Longs:  Avg%={L['avg_pct']:.4f}  cash=${L['cash']:,.0f}  days={L['avg_days']:.3f}  "
        f"turn={L['turn']:.6f}  AnnROR={L['ann']:.2f}%  "
        f"top10% $ share={L['top10_pct_share_of_dollars']:.1f}%  skew%={L['skew_pct']:.2f}  max%={L['max_pct']:.2f}",
        flush=True,
    )
    print(
        f"Shorts: Avg%={S['avg_pct']:.4f}  cash=${S['cash']:,.0f}  days={S['avg_days']:.3f}  "
        f"turn={S['turn']:.6f}  AnnROR={S['ann']:.2f}%  "
        f"top10% $ share={S['top10_pct_share_of_dollars']:.1f}%  skew%={S['skew_pct']:.2f}  max%={S['max_pct']:.2f}",
        flush=True,
    )
    print(
        "House Ann ROR ~ ((1 + total_pnl/(cash*n)) ** (365/avg_days) - 1) * 100. "
        "Ann ROR uses dollar PnL and slot cash, not average percent alone.",
        flush=True,
    )

    print("\n=== Rescore table ===", flush=True)
    hdr = (
        f"{'Arm':36s} {'N':>7} {'WR%':>6} {'Avg%':>8} {'Med%':>8} {'P99%':>8} "
        f"{'Cash':>10} {'Days':>6} {'AnnROR':>9} {'IS':>9} {'OOS':>9}"
    )
    print(hdr, flush=True)
    for r in rows:
        print(
            f"{r['name']:36s} {r['n']:7,} {r['win_pct']:6.2f} {r['avg_pct']:8.4f} "
            f"{r['med_pct']:8.4f} {r['p99']:8.2f} {r['cash']:10,.0f} {r['avg_days']:6.2f} "
            f"{r['ann']:8.2f}% {r['ann_is']:8.2f}% {r['ann_oos']:8.2f}%",
            flush=True,
        )

    # Write CSV + HTML into same stamp
    out_csv = STAMP / "tail_drop_top10.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)

    # Dollar-consistent avg % (sum $ / sum notional) vs headline mean of PNL_PCT
    def _dollar_avg_pct(df: pd.DataFrame) -> float:
        d = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
        ntl = pd.to_numeric(df["ENTRY_NOTIONAL"], errors="coerce")
        return float(d.sum() / ntl.sum() * 100.0)

    L_davg = _dollar_avg_pct(longs)
    S_davg = _dollar_avg_pct(shorts)
    cash_ratio = (S["cash"] / L["cash"]) if L["cash"] else float("nan")
    days_ratio = (S["avg_days"] / L["avg_days"]) if L["avg_days"] else float("nan")
    avg_ratio = (S["avg_pct"] / L["avg_pct"]) if L["avg_pct"] else float("nan")
    turn_ratio = (L["turn"] / S["turn"]) if S["turn"] else float("nan")
    print(
        f"Dollar-weighted avg% (sum$/sum notional): longs={L_davg:.4f}% shorts={S_davg:.4f}%",
        flush=True,
    )
    print(
        f"Mean PNL_PCT / dollar-weighted: longs={L['avg_pct']/L_davg:.2f}x "
        f"shorts={S['avg_pct']/S_davg:.2f}x  (>>1 means tiny names inflate mean %)",
        flush=True,
    )

    # Biggest winners
    for label, df in (("Longs", longs), ("Shorts", shorts)):
        pnl = pd.to_numeric(df["PNL_PCT"], errors="coerce")
        top = df.loc[pnl.nlargest(5).index, ["SYMBOL", "DATE_OPENED", "PNL_PCT", "PNL_DOLLARS", "ENTRY_NOTIONAL", "ENTRY_PRICE"]]
        print(f"\nTop 5 {label} by PNL_PCT:", flush=True)
        print(top.to_string(index=False), flush=True)

    ths = "".join(
        [
            _th("Arm", "text"),
            _th("N", "num"),
            _th("Win %", "num"),
            _th("Avg PnL %", "num"),
            _th("Median %", "num"),
            _th("P90 %", "num"),
            _th("P99 %", "num"),
            _th("Max %", "num"),
            _th("Skew %", "num"),
            _th("Top10% $ share", "num"),
            _th("Mean slot $", "num"),
            _th("Avg days", "num"),
            _th("Ann ROR %", "num"),
            _th("Ann ROR IS %", "num"),
            _th("Ann ROR OOS %", "num"),
            _th("Max DD %", "num"),
        ]
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['name'])}</td>"
            f"<td>{r['n']:,}</td>"
            f"<td>{fmt(r['win_pct'])}</td>"
            f"<td>{fmt(r['avg_pct'], 4)}</td>"
            f"<td>{fmt(r['med_pct'], 4)}</td>"
            f"<td>{fmt(r['p90'], 4)}</td>"
            f"<td>{fmt(r['p99'], 2)}</td>"
            f"<td>{fmt(r['max_pct'], 2)}</td>"
            f"<td>{fmt(r['skew_pct'], 2)}</td>"
            f"<td>{fmt(r['top10_pct_share_of_dollars'], 1)}%</td>"
            f"<td>${fmt(r['cash'], 0)}</td>"
            f"<td>{fmt(r['avg_days'], 3)}</td>"
            f"<td>{fmt(r['ann'], 2)}</td>"
            f"<td>{fmt(r['ann_is'], 2)}</td>"
            f"<td>{fmt(r['ann_oos'], 2)}</td>"
            f"<td>{fmt(r['max_dd'], 2)}</td>"
            "</tr>"
        )

    why = (
        f"Headline mean PnL% on filtered shorts is about {avg_ratio:.2f}x the longs "
        f"({S['avg_pct']:.4f}% vs {L['avg_pct']:.4f}%), but that mean is "
        f"<strong>trade-count weighted</strong> and gets inflated by tiny-notional "
        f"blowups (short max {S['max_pct']:.0f}%, skew {S['skew_pct']:.1f}). "
        f"Dollar-weighted avg% is longs <strong>{L_davg:.4f}%</strong> vs shorts "
        f"<strong>{S_davg:.4f}%</strong>. Ann ROR uses "
        f"<code>total_pnl / (mean_slot_cash × n)</code> (turn: longs {L['turn']:.4f} vs "
        f"shorts {S['turn']:.4f}, ~{turn_ratio:.1f}x), then annualizes with "
        f"<code>365 / avg_days</code>. Slot cash and days are similar "
        f"(shorts cash {cash_ratio:.2f}x, days {days_ratio:.2f}x); the Ann ROR gap "
        f"is mostly the dollar edge per slot, not a mystery hold-time effect."
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD filtered sleeves — Ann ROR vs tail</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.2rem;line-height:1.45;color:#222;max-width:1100px}}
.callout{{background:#f4f7fb;border-left:4px solid #2a6;padding:.8rem 1rem;margin:1rem 0}}
code{{font-family:ui-monospace,Consolas,monospace;font-size:.92em}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>MUD filtered longs vs shorts — Ann ROR gap and drop-top-10%</h1>
<div class="callout"><h2>What you asked</h2><p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2><p>{html_mod.escape(PLAIN)}</p></div>
<h2>Why Ann ROR ≠ Avg PnL%</h2>
<p>{why}</p>
<ul>
<li>Longs: Avg PnL% {L['avg_pct']:.4f}, median {L['med_pct']:.4f}, skew {L['skew_pct']:.2f},
max {L['max_pct']:.2f}%, top 10% by PnL% own {L['top10_pct_share_of_dollars']:.1f}% of sleeve dollars,
slot ${L['cash']:,.0f}, avg days {L['avg_days']:.3f}, Ann ROR {L['ann']:.2f}%.</li>
<li>Shorts: Avg PnL% {S['avg_pct']:.4f}, median {S['med_pct']:.4f}, skew {S['skew_pct']:.2f},
max {S['max_pct']:.2f}%, top 10% by PnL% own {S['top10_pct_share_of_dollars']:.1f}% of sleeve dollars,
slot ${S['cash']:,.0f}, avg days {S['avg_days']:.3f}, Ann ROR {S['ann']:.2f}%.</li>
</ul>
<p>Yes — both sleeves have a right tail (positive skew, fat P99/max). Dropping the top 10%
by PnL% (and separately by dollars) shows how much of the edge survives without those winners.
Still research-only; the avg-min filter itself was selected after the correlation look.</p>
<p>Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>{ths}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table></div>
<p>CSV: <code>tail_drop_top10.csv</code>. Parent AB: <code>compare.html</code>.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = STAMP / "tail_drop_top10.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_csv}", flush=True)
    print(f"Wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
