#!/usr/bin/env python3
"""
All-systems historical convergence (LatestRun Closed books).

For each hub system H, compute hold-range overlaps with every other discovered
peer system, using the same second-signal rules and capital/metrics as
tools/sb_system_convergence.py.

Does NOT overwrite SB_System_Convergence_* outputs — writes:
  drive/paul_experiments/All_Systems_Convergence_<prefix>.html
  drive/paul_experiments/All_Systems_Convergence_<prefix>.csv
  drive/paul_experiments/All_Systems_Convergence_<prefix>.md
  drive/paul_experiments/All_Systems_Convergence_SecondSignal_Agg[_<prefix>].csv

Usage:
  python tools/all_systems_convergence.py
  python tools/all_systems_convergence.py --no-standalone
  python tools/all_systems_convergence.py --out-prefix OverlapUniverse --closed-map map.json
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))

from sb_system_convergence import (  # noqa: E402
    DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MARGIN_UTILIZATION,
    PREFERRED_PEERS,
    SKIP_IF_WPBR,
    SYSTEM_LABELS,
    SecondSignalTrade,
    SourceFile,
    Trade,
    _SORTABLE_TABLE_SCRIPT,
    _AGG_COLS,
    _fmt_pct,
    _fmt_price,
    _pnl_class,
    _resolve_drive,
    _sortable_th,
    aggregate_second_signal,
    build_second_signal,
    dedupe_second_signal,
    discover_latest_closed,
    find_overlap_pairs,
    load_closed_map,
    load_trades,
    overlap_pair_to_row,
)


HUB_ORDER = ("SB",) + PREFERRED_PEERS


@dataclass
class HubResult:
    hub: str
    hub_n: int
    peers: list[str]
    detail: list[dict]
    summary: list[dict]
    agg_rows: list[dict]
    ss_raw_n: int
    ss_deduped_n: int
    all_peers_metrics: dict
    standalone_metrics: Optional[dict]


def hub_peer_order(hub: str, available: list[str]) -> list[str]:
    """Peers for hub: preferred order (incl. SB), then extras; skip hub / PBR-if-WPBR."""
    pool = [s for s in available if s != hub]
    if "WPBR" in available:
        pool = [s for s in pool if s not in SKIP_IF_WPBR]
    preferred = [s for s in HUB_ORDER if s in pool]
    extras = sorted(s for s in pool if s not in preferred)
    return preferred + extras


def select_hubs(discovered: dict[str, SourceFile]) -> list[str]:
    """Hubs = SB + preferred peers present on disk (skip incidental books / PBR when WPBR)."""
    hubs = [s for s in HUB_ORDER if s in discovered]
    if "WPBR" in discovered:
        hubs = [s for s in hubs if s not in SKIP_IF_WPBR]
    return hubs


def overlap_pair_to_hub_row(a: Trade, b: Trade) -> dict:
    """Detail row with hub/peer naming (a=hub, b=peer)."""
    base = overlap_pair_to_row(a, b)
    return {
        "hub": a.system,
        "peer": b.system,
        "symbol": base["symbol"],
        "side_hub": base["side_a"],
        "side_peer": base["side_b"],
        "hub_buy_date": base["sb_buy_date"],
        "hub_entry_price": base["sb_entry_price"],
        "hub_exit_date": base["sb_exit_date"],
        "hub_exit_price": base["sb_exit_price"],
        "hub_pnl_pct": base["sb_pnl_pct"],
        "peer_buy_date": base["b_buy_date"],
        "peer_entry_price": base["b_entry_price"],
        "peer_exit_date": base["b_exit_date"],
        "peer_exit_price": base["b_exit_price"],
        "peer_pnl_pct": base["b_pnl_pct"],
        "hold_overlap_days": base["hold_overlap_days"],
        "entry_date_delta_days": base["entry_date_delta_days"],
        "same_day_entry": base["same_day_entry"],
    }


def summarize_hub(rows: list[dict], hub: str, peers: list[str]) -> list[dict]:
    out = []
    for peer in peers:
        subset = [r for r in rows if r["peer"] == peer]
        out.append(
            {
                "pair": f"{hub} x {peer}",
                "peer": peer,
                "n_overlapping_trades": len(subset),
                "n_unique_symbols": len({r["symbol"] for r in subset}),
                "n_same_day_entry": sum(1 for r in subset if r["same_day_entry"]),
            }
        )
    return out


def trade_to_standalone_ss(t: Trade) -> Optional[SecondSignalTrade]:
    """Map a hub closed trade to SecondSignalTrade for standalone metrics."""
    ep = t.entry_price
    xp = t.exit_price
    if ep is None or ep <= 0:
        return None
    side = (t.side or "LONG").upper()
    if t.pnl_pct is not None:
        pnl_pct = float(t.pnl_pct)
    elif xp is not None and xp > 0:
        if side.startswith("S"):
            pnl_pct = (ep - xp) / ep * 100.0
        else:
            pnl_pct = (xp - ep) / ep * 100.0
    else:
        return None
    if xp is None or xp <= 0:
        # Reconstruct exit price from pnl so aggregate path stays consistent.
        if side.startswith("S"):
            xp = ep * (1.0 - pnl_pct / 100.0)
        else:
            xp = ep * (1.0 + pnl_pct / 100.0)
        if xp <= 0:
            return None
    days = (t.exit_date - t.entry_date).days
    if days < 0:
        return None
    days_held = max(days, 1)
    return SecondSignalTrade(
        symbol=t.symbol,
        peer="STANDALONE",
        side=side,
        entry_date=t.entry_date,
        entry_price=float(ep),
        entry_system=t.system,
        exit_date=t.exit_date,
        exit_price=float(xp),
        exit_system=t.system,
        days_held=days_held,
        pnl_pct=pnl_pct,
        sb_buy_date=t.entry_date,
        peer_buy_date=t.entry_date,
        same_day_entry=True,
    )


def compute_hub(
    hub: str,
    hub_trades: list[Trade],
    peer_trades: dict[str, list[Trade]],
    peers: list[str],
    *,
    include_standalone: bool,
) -> HubResult:
    all_detail: list[dict] = []
    all_ss: list[SecondSignalTrade] = []
    ss_by_peer: dict[str, list[SecondSignalTrade]] = {p: [] for p in peers}

    for peer in peers:
        trades = peer_trades.get(peer, [])
        pairs = find_overlap_pairs(hub_trades, trades)
        rows = [overlap_pair_to_hub_row(a, b) for a, b in pairs]
        rows.sort(key=lambda r: (r["peer"], r["symbol"], r["hub_buy_date"], r["peer_buy_date"]))
        peer_ss: list[SecondSignalTrade] = []
        for a, b in pairs:
            ss = build_second_signal(a, b)
            if ss is not None:
                peer_ss.append(ss)
        all_detail.extend(rows)
        all_ss.extend(peer_ss)
        ss_by_peer[peer] = peer_ss

    summary = summarize_hub(all_detail, hub, peers)

    agg_rows: list[dict] = []
    standalone_metrics: Optional[dict] = None
    if include_standalone:
        raw_sa = [x for t in hub_trades if (x := trade_to_standalone_ss(t)) is not None]
        ded_sa = dedupe_second_signal(raw_sa)
        standalone_metrics = aggregate_second_signal(ded_sa, bucket=f"{hub} STANDALONE")
        standalone_metrics["n_before_dedupe_note"] = f"{len(raw_sa)}->{len(ded_sa)}"
        standalone_metrics["hub"] = hub
        agg_rows.append(standalone_metrics)

    for peer in peers:
        raw = ss_by_peer.get(peer, [])
        ded = dedupe_second_signal(raw)
        m = aggregate_second_signal(ded, bucket=f"{hub} x {peer}")
        m["n_before_dedupe_note"] = f"{len(raw)}->{len(ded)}"
        m["hub"] = hub
        agg_rows.append(m)

    all_deduped = dedupe_second_signal(all_ss)
    all_metrics = aggregate_second_signal(all_deduped, bucket=f"{hub} ALL PEERS (deduped)")
    all_metrics["n_before_dedupe_note"] = f"{len(all_ss)}->{len(all_deduped)}"
    all_metrics["hub"] = hub
    agg_rows.append(all_metrics)

    return HubResult(
        hub=hub,
        hub_n=len(hub_trades),
        peers=peers,
        detail=all_detail,
        summary=summary,
        agg_rows=agg_rows,
        ss_raw_n=len(all_ss),
        ss_deduped_n=len(all_deduped),
        all_peers_metrics=all_metrics,
        standalone_metrics=standalone_metrics,
    )


def _metric_snapshot(row: Optional[dict]) -> dict:
    """Pull the verdict metric columns from an aggregate row."""
    if not row:
        return {
            "total_trades": 0,
            "Total_PNL": 0.0,
            "Ann_ROR": 0.0,
            "win_rate_pct": 0.0,
            "Drawdown": 0.0,
            "avg_profit_pct": 0.0,
            "profit_factor": 0.0,
        }
    return {
        "total_trades": int(row.get("total_trades") or 0),
        "Total_PNL": float(row.get("Total_PNL") or 0.0),
        "Ann_ROR": float(row.get("Ann_ROR") or 0.0),
        "win_rate_pct": float(row.get("win_rate_pct") or 0.0),
        "Drawdown": float(row.get("Drawdown") or 0.0),
        "avg_profit_pct": float(row.get("avg_profit_pct") or 0.0),
        "profit_factor": float(row.get("profit_factor") or 0.0),
    }


def build_alone_vs_overlap_verdicts(hub_results: list[HubResult]) -> list[dict]:
    """
    Per hub: compare standalone vs best H×peer second-signal vs H×ALL PEERS.

    Winner primary key = Total_PNL. Labels: ALONE | OVERLAP(<peer>) | ALL_PEERS.
    Secondary note when ALONE has lower drawdown than the PnL winner but loses on PnL.
    """
    out: list[dict] = []
    for hr in hub_results:
        alone_row = hr.standalone_metrics
        if alone_row is None:
            for r in hr.agg_rows:
                if "STANDALONE" in str(r.get("bucket", "")):
                    alone_row = r
                    break
        alone = _metric_snapshot(alone_row)

        peer_rows: list[tuple[str, dict]] = []
        for r in hr.agg_rows:
            bkt = str(r.get("bucket", ""))
            if "STANDALONE" in bkt or "ALL PEERS" in bkt:
                continue
            # Expect "HUB x PEER"
            peer = bkt.split(" x ", 1)[-1].strip() if " x " in bkt else bkt
            if int(r.get("total_trades") or 0) <= 0:
                continue
            peer_rows.append((peer, r))

        best_peer = ""
        best_peer_row: Optional[dict] = None
        if peer_rows:
            best_peer, best_peer_row = max(
                peer_rows,
                key=lambda t: (float(t[1].get("Total_PNL") or 0.0), -float(t[1].get("Drawdown") or 0.0)),
            )
        best = _metric_snapshot(best_peer_row)
        allp = _metric_snapshot(hr.all_peers_metrics)

        candidates: list[tuple[str, float, float]] = [
            ("ALL_PEERS", allp["Total_PNL"], allp["Drawdown"]),
        ]
        if alone_row is not None:
            candidates.append(("ALONE", alone["Total_PNL"], alone["Drawdown"]))
        if best_peer:
            candidates.append((f"OVERLAP({best_peer})", best["Total_PNL"], best["Drawdown"]))

        winner_label, winner_pnl, winner_dd = max(candidates, key=lambda c: (c[1], -c[2]))

        note = ""
        if winner_label != "ALONE" and alone_row is not None:
            if alone["Drawdown"] < winner_dd:
                note = (
                    f"ALONE wins Drawdown ({alone['Drawdown']:.2f}% vs "
                    f"{winner_dd:.2f}%) but loses Total_PNL"
                )

        out.append(
            {
                "hub": hr.hub,
                "alone": alone,
                "best_peer": best_peer,
                "best": best,
                "all_peers": allp,
                "winner": winner_label,
                "winner_pnl": winner_pnl,
                "note": note,
                "better_alone": winner_label == "ALONE",
            }
        )
    return out


def verdict_summary_counts(verdicts: list[dict]) -> dict:
    n_alone = sum(1 for v in verdicts if v.get("better_alone"))
    n_overlap = len(verdicts) - n_alone
    return {
        "n_hubs": len(verdicts),
        "n_better_alone": n_alone,
        "n_better_overlap": n_overlap,
    }


def _agg_row_html(r: dict, *, pin_total: bool = True) -> str:
    cells = []
    bucket = str(r.get("bucket", ""))
    is_total = pin_total and ("ALL PEERS" in bucket or bucket.endswith("STANDALONE"))
    # Pin only ALL PEERS as total-row; standalone sorts with body but bolded.
    pin = pin_total and "ALL PEERS" in bucket
    for _lab, _typ, key in _AGG_COLS:
        v = r.get(key)
        if key in ("win_rate_pct", "avg_profit_pct", "Ann_ROR", "Drawdown"):
            cls = _pnl_class(v if key != "Drawdown" else (-v if isinstance(v, (int, float)) else None))
            if key == "Drawdown":
                cells.append(f"<td>{v:.2f}%</td>" if isinstance(v, (int, float)) else f"<td>{v}</td>")
            elif key == "win_rate_pct":
                cells.append(f"<td>{v:.2f}%</td>" if isinstance(v, (int, float)) else f"<td>{v}</td>")
            else:
                cells.append(
                    f'<td class="{cls}">{v:+.2f}%</td>'
                    if isinstance(v, (int, float))
                    else f"<td>{v}</td>"
                )
        elif key == "Total_PNL":
            cells.append(
                f'<td class="{_pnl_class(v)}">{v:,.2f}</td>'
                if isinstance(v, (int, float))
                else f"<td>{v}</td>"
            )
        elif key == "brt_cash":
            cells.append(f"<td>{v:,.2f}</td>" if isinstance(v, (int, float)) else f"<td>{v}</td>")
        elif key == "bucket":
            if is_total:
                cells.append(f"<td><strong>{html_mod.escape(bucket)}</strong></td>")
            else:
                cells.append(f"<td>{html_mod.escape(bucket)}</td>")
        else:
            cells.append(f"<td>{html_mod.escape(str(v))}</td>")
    row_cls = ' class="total-row"' if pin else ""
    return f"<tr{row_cls}>" + "".join(cells) + "</tr>"


def render_html(
    *,
    hub_results: list[HubResult],
    sources: list[SourceFile],
    missing: list[str],
    gen_ts: str,
    include_standalone: bool,
    verdicts: Optional[list[dict]] = None,
    out_prefix: str = "LatestRun",
) -> str:
    deployable = DEFAULT_INITIAL_CAPITAL * DEFAULT_AGGRESSIVE_MAX_MULTIPLE * DEFAULT_MARGIN_UTILIZATION

    # Top-line: each hub ALL PEERS
    top_head = "".join(
        [
            _sortable_th("Hub", "text"),
            _sortable_th("Label", "text"),
            _sortable_th("Trades", "num"),
            _sortable_th("Win rate %", "num"),
            _sortable_th("Ann_ROR", "num"),
            _sortable_th("Total_PNL", "num"),
            _sortable_th("Avg %", "num"),
            _sortable_th("Drawdown %", "num"),
            _sortable_th("PF", "num"),
            _sortable_th("Max_Pos", "num"),
        ]
    )
    top_body = ""
    for hr in hub_results:
        m = hr.all_peers_metrics
        label = SYSTEM_LABELS.get(hr.hub, hr.hub)
        wr = m.get("win_rate_pct", 0)
        ann = m.get("Ann_ROR", 0)
        pnl = m.get("Total_PNL", 0)
        avg = m.get("avg_profit_pct", 0)
        top_body += (
            "<tr>"
            f"<td><a href=\"#hub-{html_mod.escape(hr.hub.lower())}\">{html_mod.escape(hr.hub)}</a></td>"
            f"<td>{html_mod.escape(label)}</td>"
            f"<td>{m.get('total_trades', 0)}</td>"
            f"<td>{wr:.2f}%</td>"
            f'<td class="{_pnl_class(ann)}">{ann:+.2f}%</td>'
            f'<td class="{_pnl_class(pnl)}">{pnl:,.2f}</td>'
            f'<td class="{_pnl_class(avg)}">{avg:+.2f}%</td>'
            f"<td>{m.get('Drawdown', 0):.2f}%</td>"
            f"<td>{m.get('profit_factor', 0)}</td>"
            f"<td>{m.get('Max_Positions', 0)}</td>"
            "</tr>"
        )

    toc = "".join(
        f'<li><a href="#hub-{html_mod.escape(hr.hub.lower())}">'
        f'{html_mod.escape(hr.hub)} — {html_mod.escape(SYSTEM_LABELS.get(hr.hub, hr.hub))}</a>'
        f' ({hr.ss_deduped_n} ALL PEERS trades)</li>'
        for hr in hub_results
    )
    toc += '<li><a href="#alone-vs-overlap">Alone vs overlap — what\'s better?</a></li>'

    sections = []
    for hr in hub_results:
        label = SYSTEM_LABELS.get(hr.hub, hr.hub)
        sum_head = "".join(
            [
                _sortable_th("Pair", "text"),
                _sortable_th("# Overlapping trades", "num"),
                _sortable_th("# Unique symbols", "num"),
                _sortable_th("# Same-day entry", "num"),
            ]
        )
        sum_body = ""
        tot_ov = tot_sd = 0
        all_syms: set[str] = set()
        for s in hr.summary:
            tot_ov += s["n_overlapping_trades"]
            tot_sd += s["n_same_day_entry"]
            sum_body += (
                "<tr>"
                f"<td>{html_mod.escape(s['pair'])}</td>"
                f"<td>{s['n_overlapping_trades']}</td>"
                f"<td>{s['n_unique_symbols']}</td>"
                f"<td>{s['n_same_day_entry']}</td>"
                "</tr>"
            )
        for r in hr.detail:
            all_syms.add(r["symbol"])
        sum_foot = (
            f'<tr class="total-row"><td><strong>All {html_mod.escape(hr.hub)} x peers (rows)</strong></td>'
            f"<td><strong>{tot_ov}</strong></td>"
            f"<td><strong>{len(all_syms)}</strong> <span class=\"small\">(unique across pairs)</span></td>"
            f"<td><strong>{tot_sd}</strong></td></tr>"
        )

        agg_head = "".join(_sortable_th(lab, typ) for lab, typ, _ in _AGG_COLS)
        # Standalone first (if present), then peers, then ALL PEERS last (pinned).
        peer_aggs = [r for r in hr.agg_rows if "ALL PEERS" not in str(r.get("bucket", "")) and "STANDALONE" not in str(r.get("bucket", ""))]
        sa_aggs = [r for r in hr.agg_rows if "STANDALONE" in str(r.get("bucket", ""))]
        all_aggs = [r for r in hr.agg_rows if "ALL PEERS" in str(r.get("bucket", ""))]
        ordered_aggs = sa_aggs + peer_aggs + all_aggs
        agg_body = "".join(_agg_row_html(r) for r in ordered_aggs)

        det_cols = [
            ("Hub", "text", "hub"),
            ("Peer", "text", "peer"),
            ("Symbol", "text", "symbol"),
            ("Hub buy date", "date", "hub_buy_date"),
            ("Hub entry $", "num", "hub_entry_price"),
            ("Hub exit date", "date", "hub_exit_date"),
            ("Hub exit $", "num", "hub_exit_price"),
            ("Hub PNL%", "num", "hub_pnl_pct"),
            ("Peer buy date", "date", "peer_buy_date"),
            ("Peer entry $", "num", "peer_entry_price"),
            ("Peer exit date", "date", "peer_exit_date"),
            ("Peer exit $", "num", "peer_exit_price"),
            ("Peer PNL%", "num", "peer_pnl_pct"),
            ("Hold overlap days", "num", "hold_overlap_days"),
            ("Entry delta days", "num", "entry_date_delta_days"),
            ("Same-day entry", "text", "same_day_entry"),
        ]
        det_head = "".join(_sortable_th(lab, typ) for lab, typ, _ in det_cols)
        det_body = ""
        # Cap detail HTML per hub for page weight; full detail is in CSV.
        detail_show = hr.detail
        detail_note = ""
        max_detail_html = 5000
        if len(detail_show) > max_detail_html:
            detail_show = detail_show[:max_detail_html]
            detail_note = (
                f'<p class="small">Showing first {max_detail_html} of {len(hr.detail)} detail rows; '
                f"full set in <code>All_Systems_Convergence_{html_mod.escape(out_prefix)}.csv</code>.</p>"
            )
        for r in detail_show:
            cells = []
            for _lab, _typ, key in det_cols:
                v = r[key]
                if key.endswith("_price"):
                    cells.append(f"<td>{_fmt_price(v)}</td>")
                elif key.endswith("pnl_pct"):
                    cells.append(f'<td class="{_pnl_class(v)}">{_fmt_pct(v)}</td>')
                elif key == "same_day_entry":
                    cells.append(f"<td>{'Y' if v else ''}</td>")
                else:
                    cells.append(f"<td>{html_mod.escape(str(v) if v is not None else '-')}</td>")
            det_body += "<tr>" + "".join(cells) + "</tr>"

        sa_note = ""
        if include_standalone:
            sa_note = (
                f" Optional <code>{html_mod.escape(hr.hub)} STANDALONE</code> row = hub Closed book alone "
                f"(no peer confirmation), same capital/metrics formulas."
            )

        sections.append(
            f"""
<section id="hub-{html_mod.escape(hr.hub.lower())}">
<h2>{html_mod.escape(hr.hub)} — {html_mod.escape(label)}</h2>
<p class="sub">Hub closed trades loaded: {hr.hub_n}. Overlap detail rows: {len(hr.detail)}.
  Second-signal raw: {hr.ss_raw_n}; ALL PEERS deduped: {hr.ss_deduped_n}.{sa_note}</p>

<h3>Summary by pair</h3>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{sum_head}</tr></thead>
  <tbody>{sum_body}{sum_foot}</tbody>
</table>
</div>

<h3>Second-signal aggregates</h3>
<p class="small">Click column headers to sort. ALL PEERS (deduped) row is pinned as total.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{agg_head}</tr></thead>
  <tbody>{agg_body if agg_body else '<tr><td colspan="13">No second-signal trades.</td></tr>'}</tbody>
</table>
</div>

<h3>Overlap detail</h3>
{detail_note}
<p class="small">One row per {html_mod.escape(hr.hub)} × peer trade pair with intersecting hold ranges. Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{det_head}</tr></thead>
  <tbody>{det_body if det_body else '<tr><td colspan="16">No overlapping trades.</td></tr>'}</tbody>
</table>
</div>
</section>
"""
        )

    src_li = ""
    for s in sources:
        twin = s.stamp_twin or "(none)"
        lbl = SYSTEM_LABELS.get(s.system, s.system)
        src_li += (
            f"<li><strong>{html_mod.escape(s.system)}</strong> "
            f"({html_mod.escape(lbl)}): "
            f"<code>{html_mod.escape(s.path.name)}</code> — {s.n_rows} rows; "
            f"stamp twin <code>{html_mod.escape(twin)}</code>"
            f"{(' — ' + html_mod.escape(s.note)) if s.note else ''}</li>"
        )
    miss_html = ""
    if missing:
        miss_html = (
            "<p class=\"small\">Skipped / not found on disk: "
            + ", ".join(html_mod.escape(m) for m in missing)
            + "</p>"
        )

    hub_sections = "\n".join(sections)

    if verdicts is None:
        verdicts = build_alone_vs_overlap_verdicts(hub_results)
    vcounts = verdict_summary_counts(verdicts)
    verdict_head = "".join(
        [
            _sortable_th("Hub", "text"),
            _sortable_th("Alone Total_PNL", "num"),
            _sortable_th("Alone Ann_ROR", "num"),
            _sortable_th("Alone WR%", "num"),
            _sortable_th("Alone DD%", "num"),
            _sortable_th("Alone Avg%", "num"),
            _sortable_th("Alone PF", "num"),
            _sortable_th("Best overlap", "text"),
            _sortable_th("Overlap Total_PNL", "num"),
            _sortable_th("Overlap Ann_ROR", "num"),
            _sortable_th("Overlap WR%", "num"),
            _sortable_th("Overlap DD%", "num"),
            _sortable_th("Overlap Avg%", "num"),
            _sortable_th("Overlap PF", "num"),
            _sortable_th("ALL_PEERS Total_PNL", "num"),
            _sortable_th("ALL Ann_ROR", "num"),
            _sortable_th("ALL WR%", "num"),
            _sortable_th("ALL DD%", "num"),
            _sortable_th("ALL Avg%", "num"),
            _sortable_th("ALL PF", "num"),
            _sortable_th("Winner", "text"),
            _sortable_th("Secondary note", "text"),
        ]
    )
    verdict_body = ""
    for v in verdicts:
        a, b, p = v["alone"], v["best"], v["all_peers"]
        best_lab = f"OVERLAP({v['best_peer']})" if v["best_peer"] else "—"
        winner = str(v["winner"])
        win_cls = "pos" if winner == "ALONE" else ("neg" if winner == "ALL_PEERS" else "")
        verdict_body += (
            "<tr>"
            f"<td><strong>{html_mod.escape(v['hub'])}</strong></td>"
            f'<td class="{_pnl_class(a["Total_PNL"])}">{a["Total_PNL"]:,.2f}</td>'
            f'<td class="{_pnl_class(a["Ann_ROR"])}">{a["Ann_ROR"]:+.2f}%</td>'
            f'<td>{a["win_rate_pct"]:.2f}%</td>'
            f'<td>{a["Drawdown"]:.2f}%</td>'
            f'<td class="{_pnl_class(a["avg_profit_pct"])}">{a["avg_profit_pct"]:+.2f}%</td>'
            f'<td>{a["profit_factor"]}</td>'
            f"<td>{html_mod.escape(best_lab)}</td>"
            f'<td class="{_pnl_class(b["Total_PNL"])}">{b["Total_PNL"]:,.2f}</td>'
            f'<td class="{_pnl_class(b["Ann_ROR"])}">{b["Ann_ROR"]:+.2f}%</td>'
            f'<td>{b["win_rate_pct"]:.2f}%</td>'
            f'<td>{b["Drawdown"]:.2f}%</td>'
            f'<td class="{_pnl_class(b["avg_profit_pct"])}">{b["avg_profit_pct"]:+.2f}%</td>'
            f'<td>{b["profit_factor"]}</td>'
            f'<td class="{_pnl_class(p["Total_PNL"])}">{p["Total_PNL"]:,.2f}</td>'
            f'<td class="{_pnl_class(p["Ann_ROR"])}">{p["Ann_ROR"]:+.2f}%</td>'
            f'<td>{p["win_rate_pct"]:.2f}%</td>'
            f'<td>{p["Drawdown"]:.2f}%</td>'
            f'<td class="{_pnl_class(p["avg_profit_pct"])}">{p["avg_profit_pct"]:+.2f}%</td>'
            f'<td>{p["profit_factor"]}</td>'
            f'<td class="{win_cls}"><strong>{html_mod.escape(winner)}</strong></td>'
            f"<td class=\"small\">{html_mod.escape(v.get('note') or '')}</td>"
            "</tr>"
        )
    verdict_section = f"""
<section id="alone-vs-overlap">
<h2>Alone vs overlap — what's better?</h2>
<div class="def">
  Per hub, compare <strong>STANDALONE</strong> (hub Closed book alone) vs the
  <strong>best single-peer</strong> second-signal bucket (max <code>Total_PNL</code>)
  vs <strong>ALL PEERS (deduped)</strong>.<br>
  <strong>Winner</strong> primary key = <code>Total_PNL</code>
  (<code>ALONE</code> | <code>OVERLAP(&lt;peer&gt;)</code> | <code>ALL_PEERS</code>).
  Tie-break: lower Drawdown.<br>
  Secondary note when ALONE has a better (lower) Drawdown than the PnL winner but loses on dollars.
</div>
<p class="sub">
  Summary: <strong>{vcounts['n_better_alone']}</strong> hub(s) better alone;
  <strong>{vcounts['n_better_overlap']}</strong> hub(s) better with some overlap
  (best peer or ALL PEERS) — of {vcounts['n_hubs']} hubs.
</p>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{verdict_head}</tr></thead>
  <tbody>{verdict_body if verdict_body else '<tr><td colspan="22">No verdict rows.</td></tr>'}</tbody>
</table>
</div>
</section>
"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>All Systems Convergence - {html_mod.escape(out_prefix)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1400px; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.2rem; margin-top:36px; border-top:2px solid #e2e8f0; padding-top:16px; }}
h3 {{ font-size:1.05rem; margin-top:20px; }}
.sub {{ color:#64748b; margin-bottom:16px; line-height:1.5; font-size:0.95rem; }}
.small {{ font-size:12px; color:#64748b; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
code {{ font-size:11px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
ul.sources, ul.toc {{ font-size:12px; color:#475569; line-height:1.7; }}
.def {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin:12px 0 20px; font-size:0.92rem; line-height:1.5; }}
</style></head><body>
<h1>All Systems Convergence - {html_mod.escape(out_prefix)}</h1>
<p class="sub">
  For each hub system, historical hold-period overlap with all other peer systems,
  using each system's Closed book (LatestRun / stamp twin / closed-map) on disk.
  Same second-signal rules and capital assumptions as
  <code>SB_System_Convergence_{html_mod.escape(out_prefix)}</code>.
  Generated {html_mod.escape(gen_ts)}.
</p>

<div class="def">
  <strong>Overlap:</strong> same <em>SYMBOL</em>, intersecting
  <code>DATE_OPENED..DATE_CLOSED</code> (inclusive).<br>
  <strong>Second-signal:</strong> entry = later buy (same-day tie-break: prefer peer);
  exit = earlier exit among sides still open on/after second entry.
  Dedupe by <code>(symbol, second_entry_date)</code> within each bucket and for ALL PEERS.<br>
  <strong>Capital:</strong> initial_capital={DEFAULT_INITIAL_CAPITAL:,.0f},
  max_multiple={DEFAULT_AGGRESSIVE_MAX_MULTIPLE}, margin_util={DEFAULT_MARGIN_UTILIZATION}
  (deployable {deployable:,.0f}).
  Metrics match <code>rocket_tbn.compute_metrics</code> / <code>tbn_host_sizing</code>.
</div>

<section>
<h2>Top-line: each hub × ALL PEERS (deduped)</h2>
<p class="small">Click column headers to sort. Hub links jump to that section.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{top_head}</tr></thead>
  <tbody>{top_body}</tbody>
</table>
</div>
</section>

<section>
<h2>Contents</h2>
<ul class="toc">{toc}</ul>
{miss_html}
</section>

{hub_sections}

{verdict_section}

<section>
<h2>Data sources</h2>
<ul class="sources">{src_li}</ul>
</section>
{_SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def render_md(
    *,
    hub_results: list[HubResult],
    sources: list[SourceFile],
    missing: list[str],
    gen_ts: str,
    include_standalone: bool,
    verdicts: Optional[list[dict]] = None,
    out_prefix: str = "LatestRun",
) -> str:
    deployable = DEFAULT_INITIAL_CAPITAL * DEFAULT_AGGRESSIVE_MAX_MULTIPLE * DEFAULT_MARGIN_UTILIZATION
    lines = [
        f"# All Systems Convergence - {out_prefix}",
        "",
        f"Generated: {gen_ts}",
        "",
        "For each hub system H, overlap with all other peers using the same rules as",
        f"`SB_System_Convergence_{out_prefix}` (intersecting hold ranges; second-signal",
        "entry/exit; dedupe; capital 500k×2×0.6).",
        "",
        "## Top-line: hub × ALL PEERS (deduped)",
        "",
        "| Hub | Trades | Win% | Ann_ROR | Total_PNL | Avg% | DD% | PF | Max_Pos |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for hr in hub_results:
        m = hr.all_peers_metrics
        lines.append(
            f"| {hr.hub} | {m.get('total_trades', 0)} | {m.get('win_rate_pct', 0)} | "
            f"{m.get('Ann_ROR', 0)} | {m.get('Total_PNL', 0)} | {m.get('avg_profit_pct', 0)} | "
            f"{m.get('Drawdown', 0)} | {m.get('profit_factor', 0)} | {m.get('Max_Positions', 0)} |"
        )

    lines += [
        "",
        "### Capital / metrics",
        "",
        f"- `initial_capital`={DEFAULT_INITIAL_CAPITAL:,.0f}, "
        f"`aggressive_max_multiple`={DEFAULT_AGGRESSIVE_MAX_MULTIPLE}, "
        f"`margin_utilization`={DEFAULT_MARGIN_UTILIZATION}",
        f"  -> deployable **{deployable:,.0f}**",
        "- Same formulas as `tools/sb_system_convergence.py` / `rocket_tbn.compute_metrics`",
        "",
    ]
    if include_standalone:
        lines += [
            "Standalone row (optional): hub Closed book alone, no peer confirmation.",
            "",
        ]

    for hr in hub_results:
        label = SYSTEM_LABELS.get(hr.hub, hr.hub)
        lines += [
            f"## {hr.hub} — {label}",
            "",
            f"Hub trades: **{hr.hub_n}**. Detail rows: **{len(hr.detail)}**. "
            f"Second-signal raw: {hr.ss_raw_n}; ALL PEERS deduped: {hr.ss_deduped_n}.",
            "",
            "### Summary counts",
            "",
            "| Pair | # Overlaps | # Symbols | # Same-day |",
            "|---|---:|---:|---:|",
        ]
        for s in hr.summary:
            lines.append(
                f"| {s['pair']} | {s['n_overlapping_trades']} | "
                f"{s['n_unique_symbols']} | {s['n_same_day_entry']} |"
            )
        lines += [
            "",
            "### Second-signal aggregates",
            "",
            "| Bucket | Trades | Win% | Avg% | Ann_ROR | Avg days | Total_PNL | DD% | PF | Lose streak | p90 | brt_cash | Max_Pos |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in hr.agg_rows:
            lines.append(
                f"| {r['bucket']} | {r['total_trades']} | {r['win_rate_pct']} | "
                f"{r['avg_profit_pct']} | {r['Ann_ROR']} | {r['avg_days_in_trade']} | "
                f"{r['Total_PNL']} | {r['Drawdown']} | {r['profit_factor']} | "
                f"{r['losing_streak']} | {r['p90_days']} | {r['brt_cash']} | {r['Max_Positions']} |"
            )
        lines.append("")

    if verdicts is None:
        verdicts = build_alone_vs_overlap_verdicts(hub_results)
    vcounts = verdict_summary_counts(verdicts)
    lines += [
        "## Alone vs overlap — what's better?",
        "",
        "Per hub: **STANDALONE** vs best single-peer second-signal (max `Total_PNL`) "
        "vs **ALL PEERS (deduped)**. Winner primary key = `Total_PNL` "
        "(`ALONE` | `OVERLAP(<peer>)` | `ALL_PEERS`); tie-break lower Drawdown.",
        "",
        f"Summary: **{vcounts['n_better_alone']}** hub(s) better alone; "
        f"**{vcounts['n_better_overlap']}** hub(s) better with some overlap "
        f"(of {vcounts['n_hubs']} hubs).",
        "",
        "| Hub | Alone_PNL | Alone_Ann_ROR | Alone_WR% | Alone_DD% | Alone_Avg% | Alone_PF | Best overlap | Overlap_PNL | Overlap_Ann_ROR | Overlap_WR% | Overlap_DD% | Overlap_Avg% | Overlap_PF | ALL_PNL | ALL_Ann_ROR | ALL_WR% | ALL_DD% | ALL_Avg% | ALL_PF | Winner | Secondary note |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for v in verdicts:
        a, b, p = v["alone"], v["best"], v["all_peers"]
        best_lab = f"OVERLAP({v['best_peer']})" if v["best_peer"] else "—"
        lines.append(
            f"| {v['hub']} | {a['Total_PNL']} | {a['Ann_ROR']} | {a['win_rate_pct']} | "
            f"{a['Drawdown']} | {a['avg_profit_pct']} | {a['profit_factor']} | "
            f"{best_lab} | {b['Total_PNL']} | {b['Ann_ROR']} | {b['win_rate_pct']} | "
            f"{b['Drawdown']} | {b['avg_profit_pct']} | {b['profit_factor']} | "
            f"{p['Total_PNL']} | {p['Ann_ROR']} | {p['win_rate_pct']} | "
            f"{p['Drawdown']} | {p['avg_profit_pct']} | {p['profit_factor']} | "
            f"{v['winner']} | {v.get('note') or ''} |"
        )
    lines.append("")

    lines += [
        "## Closed files used",
        "",
        "| System | Closed file | Rows | Stamp twin |",
        "|---|---|---:|---|",
    ]
    for src in sources:
        twin = src.stamp_twin or "(none)"
        lines.append(f"| {src.system} | `{src.path.name}` | {src.n_rows} | `{twin}` |")
    if missing:
        lines += ["", "## Skipped / missing", "", ", ".join(f"`{m}`" for m in missing)]
    if out_prefix == "LatestRun":
        agg_name = "All_Systems_Convergence_SecondSignal_Agg.csv"
    else:
        agg_name = f"All_Systems_Convergence_SecondSignal_Agg_{out_prefix}.csv"
    lines += [
        "",
        "## Outputs",
        "",
        f"- `All_Systems_Convergence_{out_prefix}.html`",
        f"- `All_Systems_Convergence_{out_prefix}.csv` (overlap detail, all hubs)",
        f"- `{agg_name}`",
        f"- `All_Systems_Convergence_{out_prefix}.md` (this note)",
        "",
        "Re-run: `python tools/all_systems_convergence.py`",
        "",
        "Note: does not modify `SB_System_Convergence_*`. Legacy `PBR` skipped when WPBR present.",
        "",
    ]
    return "\n".join(lines)


def all_second_signal_agg_name(out_prefix: str) -> str:
    if out_prefix == "LatestRun":
        return "All_Systems_Convergence_SecondSignal_Agg.csv"
    return f"All_Systems_Convergence_SecondSignal_Agg_{out_prefix}.csv"


def main() -> int:
    ap = argparse.ArgumentParser(description="All hubs × peers LatestRun closed-trade convergence")
    ap.add_argument("--drive", type=Path, default=ROOT / "drive", help="drive/ folder")
    ap.add_argument("--out-dir", type=Path, default=None, help="output directory")
    ap.add_argument(
        "--no-standalone",
        action="store_true",
        help="omit hub STANDALONE aggregate rows",
    )
    ap.add_argument(
        "--hubs",
        default="",
        help="comma-separated hub subset (default: all preferred hubs found)",
    )
    ap.add_argument(
        "--out-prefix",
        default="LatestRun",
        help="output filename suffix (default LatestRun)",
    )
    ap.add_argument(
        "--closed-map",
        type=Path,
        default=None,
        help="explicit system→Closed path/stamp map (JSON/text)",
    )
    args = ap.parse_args()
    include_standalone = not args.no_standalone
    out_prefix = str(args.out_prefix or "LatestRun").strip() or "LatestRun"

    drive = _resolve_drive(args.drive)
    out_dir = (args.out_dir or (drive / "paul_experiments")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.closed_map:
        discovered = load_closed_map(args.closed_map, drive)
    else:
        discovered = discover_latest_closed(drive)
    hubs = select_hubs(discovered)
    if args.hubs.strip():
        want = [h.strip().upper() for h in args.hubs.split(",") if h.strip()]
        hubs = [h for h in want if h in discovered]
        missing_want = [h for h in want if h not in discovered]
    else:
        missing_want = []

    expected = list(HUB_ORDER)
    missing = [s for s in expected if s not in discovered] + missing_want
    if "WPBR" in discovered and "PBR" in missing:
        missing = [m for m in missing if m != "PBR"]

    print(f"Drive: {drive}")
    print(f"Out:   {out_dir}")
    print(f"Prefix:{out_prefix}")
    print(f"Hubs:  {', '.join(hubs)}")
    if missing:
        print(f"Missing expected: {', '.join(missing)}")

    # Load all hub/peer trade books once
    trades_by_sys: dict[str, list[Trade]] = {}
    used_sources: list[SourceFile] = []
    for sys_name in sorted(set(hubs) | set(discovered.keys())):
        if sys_name not in hubs and sys_name not in HUB_ORDER:
            continue
        if "WPBR" in discovered and sys_name in SKIP_IF_WPBR:
            continue
        src = discovered.get(sys_name)
        if src is None:
            continue
        try:
            trades_by_sys[sys_name] = load_trades(src)
            used_sources.append(src)
            print(f"  Loaded {sys_name}: {len(trades_by_sys[sys_name])} trades ({src.note})")
        except Exception as e:
            print(f"  SKIP {sys_name}: {e}")
            missing.append(f"{sys_name} (load error)")

    used_sources.sort(key=lambda s: (HUB_ORDER.index(s.system) if s.system in HUB_ORDER else 99, s.system))

    hub_results: list[HubResult] = []
    for hub in hubs:
        if hub not in trades_by_sys:
            print(f"  SKIP hub {hub}: no trades loaded")
            continue
        peers = hub_peer_order(hub, list(trades_by_sys.keys()))
        print(f"\n=== Hub {hub} vs {', '.join(peers)} ===")
        hr = compute_hub(
            hub,
            trades_by_sys[hub],
            trades_by_sys,
            peers,
            include_standalone=include_standalone,
        )
        hub_results.append(hr)
        m = hr.all_peers_metrics
        print(
            f"  ALL PEERS: trades={m['total_trades']} WR={m['win_rate_pct']}% "
            f"Ann_ROR={m['Ann_ROR']}% Total_PNL={m['Total_PNL']}"
        )
        for s in hr.summary:
            if s["n_overlapping_trades"]:
                print(
                    f"    {s['pair']}: {s['n_overlapping_trades']} overlaps, "
                    f"{s['n_unique_symbols']} syms"
                )

    gen_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    csv_path = out_dir / f"All_Systems_Convergence_{out_prefix}.csv"
    agg_csv_path = out_dir / all_second_signal_agg_name(out_prefix)
    html_path = out_dir / f"All_Systems_Convergence_{out_prefix}.html"
    md_path = out_dir / f"All_Systems_Convergence_{out_prefix}.md"

    all_detail: list[dict] = []
    all_agg: list[dict] = []
    for hr in hub_results:
        all_detail.extend(hr.detail)
        all_agg.extend(hr.agg_rows)

    detail_df = pd.DataFrame(all_detail)
    if detail_df.empty:
        detail_df = pd.DataFrame(
            columns=[
                "hub", "peer", "symbol", "side_hub", "side_peer",
                "hub_buy_date", "hub_entry_price", "hub_exit_date", "hub_exit_price", "hub_pnl_pct",
                "peer_buy_date", "peer_entry_price", "peer_exit_date", "peer_exit_price", "peer_pnl_pct",
                "hold_overlap_days", "entry_date_delta_days", "same_day_entry",
            ]
        )
    detail_df.to_csv(csv_path, index=False)

    agg_df = pd.DataFrame(all_agg)
    agg_cols = [
        "hub", "bucket", "total_trades", "wins", "losses", "bes", "win_rate_pct", "avg_profit_pct",
        "Ann_ROR", "avg_days_in_trade", "Total_PNL", "Drawdown", "profit_factor",
        "losing_streak", "p90_days", "brt_cash", "Max_Positions", "n_before_dedupe_note",
    ]
    for c in agg_cols:
        if c not in agg_df.columns:
            agg_df[c] = None
    if not agg_df.empty:
        agg_df[agg_cols].to_csv(agg_csv_path, index=False)
    else:
        pd.DataFrame(columns=agg_cols).to_csv(agg_csv_path, index=False)

    verdicts = build_alone_vs_overlap_verdicts(hub_results)
    vcounts = verdict_summary_counts(verdicts)

    html_path.write_text(
        render_html(
            hub_results=hub_results,
            sources=used_sources,
            missing=missing,
            gen_ts=gen_ts,
            include_standalone=include_standalone,
            verdicts=verdicts,
            out_prefix=out_prefix,
        ),
        encoding="utf-8",
    )
    md_path.write_text(
        render_md(
            hub_results=hub_results,
            sources=used_sources,
            missing=missing,
            gen_ts=gen_ts,
            include_standalone=include_standalone,
            verdicts=verdicts,
            out_prefix=out_prefix,
        ),
        encoding="utf-8",
    )

    print()
    print("=== Top-line ALL PEERS (deduped) ===")
    print(f"{'Hub':<6} {'Trades':>7} {'WR%':>8} {'Ann_ROR':>10} {'Total_PNL':>14}")
    for hr in hub_results:
        m = hr.all_peers_metrics
        print(
            f"{hr.hub:<6} {m['total_trades']:>7} {m['win_rate_pct']:>7.2f}% "
            f"{m['Ann_ROR']:>9.2f}% {m['Total_PNL']:>14,.2f}"
        )
    print()
    print("=== Alone vs overlap winners (Total_PNL) ===")
    print(
        f"Better alone: {vcounts['n_better_alone']}; "
        f"better with overlap: {vcounts['n_better_overlap']} "
        f"(of {vcounts['n_hubs']} hubs)"
    )
    print(f"{'Hub':<6} {'Winner':<18} {'Alone_PNL':>12} {'BestOverlap':>14} {'ALL_PNL':>12}")
    for v in verdicts:
        best_lab = f"OVERLAP({v['best_peer']})" if v["best_peer"] else "—"
        print(
            f"{v['hub']:<6} {v['winner']:<18} {v['alone']['Total_PNL']:>12,.2f} "
            f"{best_lab:>14} {v['all_peers']['Total_PNL']:>12,.2f}"
            + (f"  [{v['note']}]" if v.get("note") else "")
        )
    print()
    print(f"Wrote:\n  {csv_path}\n  {agg_csv_path}\n  {html_path}\n  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
