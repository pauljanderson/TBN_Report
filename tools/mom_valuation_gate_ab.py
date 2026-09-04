#!/usr/bin/env python3
"""MOM ∩ Valuation gate AB on frozen mom_baseline_20260828 (research-only).

Closest in-repo operationalization of ValMom Everywhere’s combine-negatively-
correlated-styles insight: keep MOM baseline trades only when the house fund
scorecard Valuation pillar passes one pre-declared threshold.

Control: full ``mom_baseline_20260828`` Closed book.
Candidate: Valuation ≥ 60 (pre-declared; same thr as MR RL dual-book).

Scores: prefer PIT ``scores_as_of(entry_date)`` when history exists; else
snapshot industry stamp. PIT history currently starts ~2026-08-31 while this
MOM Closed ends 2023-12-28 → expect CONTAMINATED / snapshot ceiling.

Usage:
  python tools/mom_valuation_gate_ab.py
  python tools/mom_valuation_gate_ab.py --threshold 60
  python tools/mom_valuation_gate_ab.py --stamp mom_valuation_gate_customuniv_20260904 \\
      --universe drive/paul_experiments/mom_valuation_gate_customuniv_20260904/universe.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mr_ab_common import (  # noqa: E402
    SCORES_FALLBACK,
    SCORES_INDUSTRY,
    esc,
    md_split_line,
    overall_verdict,
    pack_overlay_arm,
    write_stamp_html,
)
from rl_univ_compare_lists import (  # noqa: E402
    _f,
    _parse_d,
    _row_get,
)

STAMP_DEFAULT = "mom_valuation_gate_20260904"
MOM_BASELINE = ROOT / "drive" / "paul_experiments" / "mom_baseline_20260828"
MOM_CLOSED = MOM_BASELINE / "MOM_Closed.csv"
SCORECARD_DB = ROOT / "drive" / "fund_scorecard_cache.duckdb"
MOM_CASH = 500_000.0  # mom_baseline_20260828 EquityMeta seed
THR_DEFAULT = 60.0  # PRE-DECLARED — do not retune after seeing results


def load_universe(path: Path) -> set[str]:
    """Load symbol list from CSV (column symbol/SYMBOL or first column)."""
    syms: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            fields = [c.strip() for c in reader.fieldnames]
            lower = {c.lower(): c for c in fields}
            key = lower.get("symbol") or fields[0]
            for raw in reader:
                s = str(raw.get(key) or "").strip().upper()
                if s:
                    syms.add(s)
        else:
            f.seek(0)
            for line in f:
                s = line.strip().upper()
                if s and s != "SYMBOL":
                    syms.add(s.split(",")[0].strip())
    return syms


def load_mom_trades(closed_path: Path) -> list[dict[str, Any]]:
    """Load MOM Closed (ENTRY_DATE / EXIT_DATE / PNL_PCT columns)."""
    rows: list[dict[str, Any]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(
                _row_get(raw, "ENTRY_DATE", "ENTRY DATE", "DATE OPENED", "DATE_OPENED")
            )
            closed = _parse_d(
                _row_get(raw, "EXIT_DATE", "EXIT DATE", "DATE CLOSED", "DATE_CLOSED")
            )
            if opened is None:
                continue
            pnl = _f(_row_get(raw, "PNL_PCT", "PNL %"))
            days = _f(_row_get(raw, "DAYS_HELD", "DAYS HELD"))
            pnl_d = _f(_row_get(raw, "PNL_DOLLARS"))
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = MOM_CASH * pnl / 100.0
            rows.append(
                {
                    "sym": _row_get(raw, "SYMBOL").upper(),
                    "opened": opened,
                    "closed": closed,
                    "pnl": pnl,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exit": _row_get(raw, "EXIT_REASON", "EXIT TYPE", "EXIT_TYPE") or "?",
                    "max_gain": _f(_row_get(raw, "MAX GAIN", "MAX_GAIN")),
                    "mae": _f(_row_get(raw, "MAE")),
                    "hist_high": _f(_row_get(raw, "HIST_HIGH_PCT")),
                    "entry": _f(_row_get(raw, "ENTRY_PX", "ENTRY PRICE", "ENTRY_PRICE")),
                }
            )
    return rows


def load_snapshot_scores(path: Path) -> dict[str, float]:
    import pandas as pd

    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    out: dict[str, float] = {}
    for _, r in df.iterrows():
        sym = str(r["symbol"]).upper()
        try:
            v = float(r["score_valuation"])
        except (TypeError, ValueError, KeyError):
            continue
        if math.isfinite(v):
            out[sym] = v
    return out


def pit_coverage() -> dict[str, Any]:
    if not SCORECARD_DB.is_file():
        return {
            "available": False,
            "scores_as_of_min": None,
            "scores_as_of_max": None,
            "scores_distinct_days": 0,
            "scores_history_n": 0,
        }
    from fund_scorecard_v1 import history_coverage

    cov = history_coverage(SCORECARD_DB)
    return {
        "available": int(cov.get("scores_history_n") or 0) > 0,
        "scores_as_of_min": cov.get("scores_as_of_min"),
        "scores_as_of_max": cov.get("scores_as_of_max"),
        "scores_distinct_days": cov.get("scores_distinct_days"),
        "scores_history_n": cov.get("scores_history_n"),
    }


def valuation_for_trade(
    sym: str,
    entry: date,
    snapshot: dict[str, float],
    *,
    use_pit: bool,
    pit_min: Optional[date] = None,
) -> tuple[Optional[float], str]:
    """Return (score, source) where source is pit|snapshot|missing."""
    # Skip empty PIT queries when entry is before any history (typical for MOM 2010–2023).
    if use_pit and SCORECARD_DB.is_file() and (pit_min is None or entry >= pit_min):
        try:
            from fund_scorecard_v1 import scores_as_of

            row = scores_as_of(SCORECARD_DB, sym, entry)
            if row is not None:
                raw = row.get("score_valuation")
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    v = float("nan")
                if math.isfinite(v):
                    return v, "pit"
        except Exception:  # noqa: BLE001 — fall through to snapshot
            pass
    if sym in snapshot:
        return snapshot[sym], "snapshot"
    return None, "missing"


def gate_trades(
    trades: list[dict[str, Any]],
    snapshot: dict[str, float],
    thr: float,
    *,
    use_pit: bool,
    pit_min: Optional[date] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    n_pass = n_fail = n_miss = 0
    n_pit = n_snap = 0
    for t in trades:
        score, src = valuation_for_trade(
            t["sym"], t["opened"], snapshot, use_pit=use_pit, pit_min=pit_min
        )
        if score is None:
            n_miss += 1
            continue
        if src == "pit":
            n_pit += 1
        else:
            n_snap += 1
        if score >= thr:
            kept.append(t)
            n_pass += 1
        else:
            n_fail += 1
    cov = {
        "n_pass_trades": n_pass,
        "n_fail_score": n_fail,
        "n_missing": n_miss,
        "n_pit_hits": n_pit,
        "n_snapshot_hits": n_snap,
        "n_keep_sym": len({t["sym"] for t in kept}),
    }
    return kept, cov


def write_summary(
    out: Path,
    *,
    stamp: str,
    thr: float,
    arms: list[dict[str, Any]],
    verdicts: dict[str, tuple[str, str, str, str]],
    pit_label: str,
    cov: dict[str, Any],
    scores_path: Path,
    pit_meta: dict[str, Any],
    univ_note: str,
) -> Path:
    ctrl = next(a for a in arms if a["id"] == "control")
    cand = next(a for a in arms if a["id"] != "control")
    tag, is_v, oos_v, note = verdicts[cand["id"]]
    lines = [
        f"# SUMMARY — `{stamp}`",
        "",
        "**Hypothesis:** MOM ∩ Valuation (fund scorecard) improves quality vs full MOM "
        "baseline by intersecting momentum with a cheapness gate (ValMom Everywhere-style).",
        f"**Single knob:** keep MOM trades with **score_valuation ≥ {thr:.0f}**.",
        f"**Control:** frozen `mom_baseline_20260828` Closed filtered to custom universe "
        f"(N={len(ctrl['trades'])}; {univ_note}).",
        f"**Scores:** `{scores_path.as_posix()}` + PIT DB `{SCORECARD_DB.as_posix()}`.",
        f"**PIT / contamination label:** **{pit_label}**",
        "**Status:** RESEARCH-ONLY — not gold / not DailyRun / no commit.",
        "",
        "## Coverage",
        "",
        f"- universe: {univ_note}",
        f"- trades pass ≥{thr:.0f}: {cov['n_pass_trades']}",
        f"- fail score: {cov['n_fail_score']}; missing: {cov['n_missing']}",
        f"- PIT score hits: {cov['n_pit_hits']}; snapshot hits: {cov['n_snapshot_hits']}",
        f"- keep symbols: {cov['n_keep_sym']}",
        f"- PIT history: as_of {pit_meta.get('scores_as_of_min')}→{pit_meta.get('scores_as_of_max')} "
        f"({pit_meta.get('scores_distinct_days')} days, n={pit_meta.get('scores_history_n')})",
        "",
        "## IS / OOS quality",
        "",
        f"- **control IS:** {md_split_line(ctrl['m_is'])}",
        f"- **control OOS:** {md_split_line(ctrl['m_oos'])}",
        f"- **{cand['id']} IS:** {md_split_line(cand['m_is'])} → {is_v}",
        f"- **{cand['id']} OOS:** {md_split_line(cand['m_oos'])} → {oos_v}",
        f"- **Overall (research):** **{tag}** — {note}",
        "",
        "## Blockers",
        "",
        "- MOM Closed ends **2023-12-28** → trade-level OOS (entry ≥ 2024-01-01) **N=0** on this freeze.",
        "- PIT Valuation history starts **~2026-08-31** → no overlap with MOM entries; snapshot ceiling.",
        "- Not DailyRun-wired. No OOS retune.",
        "",
        "## Paths",
        "",
        f"- HTML: `drive/paul_experiments/{stamp}/compare.html`",
        f"- BASELINE: `drive/paul_experiments/{stamp}/BASELINE.md`",
        "",
    ]
    path = out / "SUMMARY.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--threshold",
        type=float,
        default=THR_DEFAULT,
        help=f"Pre-declared Valuation gate (default {THR_DEFAULT:.0f}; do not retune)",
    )
    ap.add_argument("--closed", type=Path, default=MOM_CLOSED)
    ap.add_argument(
        "--scores",
        type=Path,
        default=None,
        help="Snapshot scores.csv (default: industry stamp, else fallback)",
    )
    ap.add_argument(
        "--stamp",
        type=str,
        default=STAMP_DEFAULT,
        help=f"Output stamp folder name under drive/paul_experiments/ (default {STAMP_DEFAULT})",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: drive/paul_experiments/<stamp>)",
    )
    ap.add_argument(
        "--universe",
        type=Path,
        default=None,
        help="Optional CSV of symbols; filter MOM Closed to this list for control vs gate",
    )
    args = ap.parse_args(argv)
    thr = float(args.threshold)
    stamp = str(args.stamp).strip() or STAMP_DEFAULT
    out = args.out if args.out is not None else (ROOT / "drive" / "paul_experiments" / stamp)

    if not args.closed.is_file():
        raise SystemExit(f"Missing MOM Closed: {args.closed}")

    scores_path = args.scores
    if scores_path is None:
        scores_path = SCORES_INDUSTRY if SCORES_INDUSTRY.is_file() else SCORES_FALLBACK
    if not scores_path.is_file():
        raise SystemExit(f"Missing fund scorecard scores.csv: {scores_path}")

    out.mkdir(parents=True, exist_ok=True)

    # --- Pre-declare threshold in BASELINE before packing results ---
    pit_meta = pit_coverage()
    use_pit = bool(pit_meta.get("available"))

    snapshot = load_snapshot_scores(scores_path)
    all_trades = load_mom_trades(args.closed)
    if not all_trades:
        raise SystemExit("No trades loaded from MOM Closed")

    univ: Optional[set[str]] = None
    univ_n_list = 0
    if args.universe is not None:
        if not args.universe.is_file():
            raise SystemExit(f"Missing universe CSV: {args.universe}")
        univ = load_universe(args.universe)
        univ_n_list = len(univ)
        before = len(all_trades)
        all_trades = [t for t in all_trades if t["sym"] in univ]
        print(
            f"[mom_val_gate] universe filter: list={univ_n_list} "
            f"trades {before} -> {len(all_trades)} "
            f"syms_with_trades={len({t['sym'] for t in all_trades})}"
        )
        if not all_trades:
            raise SystemExit("No MOM Closed trades overlap custom universe")

    univ_syms_traded = len({t["sym"] for t in all_trades})
    if univ is not None:
        univ_note = (
            f"custom univ list N={univ_n_list}; "
            f"syms with MOM Closed trades={univ_syms_traded}; "
            f"`{args.universe.as_posix()}`"
        )
        univ_label = (
            f"custom list N={univ_n_list} "
            f"(syms w/ trades={univ_syms_traded}; filter mom_baseline Closed)"
        )
        ctrl_label = "control (MOM baseline ∩ custom univ)"
    else:
        univ_note = f"full mom_baseline Closed (syms traded={univ_syms_traded})"
        univ_label = "ALL_ohlc / MOM_universe N≈1118 (see parent BASELINE)"
        ctrl_label = "control (full MOM baseline)"

    entry_min = min(t["opened"] for t in all_trades)
    entry_max = max(t["opened"] for t in all_trades)

    pit_min: Optional[date] = None
    if pit_meta.get("scores_as_of_min"):
        try:
            pit_min = date.fromisoformat(str(pit_meta["scores_as_of_min"])[:10])
        except ValueError:
            pit_min = None

    kept, cov = gate_trades(
        all_trades, snapshot, thr, use_pit=use_pit, pit_min=pit_min
    )

    # Contamination label (honest): no PIT overlap with trade history → CONTAMINATED
    if cov["n_pit_hits"] == 0:
        pit_label = "CONTAMINATED / SNAPSHOT CEILING (no PIT overlap with MOM entry dates)"
    elif cov["n_snapshot_hits"] > 0:
        pit_label = (
            f"MIXED PIT+SNAPSHOT (pit={cov['n_pit_hits']}, "
            f"snapshot={cov['n_snapshot_hits']}) — treat as contaminated ceiling"
        )
    else:
        pit_label = "PIT-CLEAN (all gated trades used scores_as_of ≤ entry)"

    baseline = f"""# BASELINE — `{stamp}`

**Status:** RESEARCH-ONLY — not gold / not DailyRun / no commit.

## Hypothesis

ValMom Everywhere (Asness / Moskowitz / Pedersen): value and momentum are negatively
correlated styles; combining them stabilizes. Closest house hook = **MOM baseline ∩
fund scorecard Valuation pillar**.

## Pre-declared single knob (chosen before results)

| Knob | Control | Candidate |
|------|---------|-----------|
| Valuation gate | none (MOM Closed ∩ univ) | keep trades with **score_valuation ≥ {thr:.0f}** |

Threshold **{thr:.0f}** matches prior MR RL Valuation dual-book (`mr_rl_valuation_dualbook_ab.py`)
and fund-score pillar arms — consistency, not a post-hoc pick.

## Frozen control identity

| Knob | Value |
|------|-------|
| Parent freeze | `mom_baseline_20260828` |
| Closed | `{args.closed.as_posix()}` |
| Universe | {univ_label} |
| Buy / sell | Clenow weekly rank; SMA100 exit; no hard stop (parent freeze) |
| Capital | ${MOM_CASH:,.0f} |
| Split | IS entry < 2024-01-01; OOS entry ≥ 2024-01-01 **report-only** |

## PIT vs snapshot (method honesty)

| Item | Value |
|------|-------|
| Snapshot scores | `{scores_path.as_posix()}` |
| PIT DB | `{SCORECARD_DB.as_posix()}` |
| PIT as_of range | {pit_meta.get("scores_as_of_min")} → {pit_meta.get("scores_as_of_max")} ({pit_meta.get("scores_distinct_days")} days) |
| MOM entry range | {entry_min.isoformat()} → {entry_max.isoformat()} |
| **Label** | **{pit_label}** |

- Prefer `scores_as_of(entry)` when a history row exists with `as_of ≤ entry`.
- Missing Valuation → **fail** gate (cannot pass ≥ {thr:.0f}).
- Snapshot applied to historical entries = **look-ahead / contaminated research ceiling**.
- Max research claim under contamination: **LEAN KEEP**; prefer HOLD if quality flat/mixed.
- OOS report-only; **no retune**; no DailyRun wire.

## Coverage (filled after run)

- {univ_note}
- traded N: {len(all_trades)}
- pass ≥{thr:.0f}: {cov["n_pass_trades"]}
- fail score: {cov["n_fail_score"]}; missing: {cov["n_missing"]}
- PIT hits: {cov["n_pit_hits"]}; snapshot hits: {cov["n_snapshot_hits"]}

## Verdict

See `SUMMARY.md` / `compare.html`.
"""
    (out / "BASELINE.md").write_text(baseline, encoding="utf-8")

    control = pack_overlay_arm("control", ctrl_label, all_trades, MOM_CASH)
    control["cash"] = MOM_CASH
    cand = pack_overlay_arm(
        "valuation_ge_60" if thr == 60.0 else f"valuation_ge_{thr:.0f}",
        f"MOM ∩ Valuation ≥ {thr:.0f}",
        kept,
        MOM_CASH,
        extra=cov,
    )

    tag, is_v, oos_v, note = overall_verdict(cand, control)
    # Contamination ceiling: never claim full KEEP
    if tag == "KEEP":
        tag = "LEAN KEEP"
        note += " (contamination ceiling — snapshot scores)"
    # Empty OOS on this freeze → do not let empty-OOS soft-dismiss dominate; label HOLD caution
    if control["m_oos"]["n"] == 0 and cand["m_oos"]["n"] == 0:
        note += (
            "; OOS N=0 on mom_baseline_20260828 Closed (ends 2023-12-28) — "
            "OOS report unavailable; IS-only research verdict"
        )
        if tag in ("KEEP", "LEAN KEEP"):
            # Still allow LEAN KEEP on IS but flag hold-bias for promotion
            note += " (promotion blocked until OOS book exists)"
    verdicts = {cand["id"]: (tag, is_v, oos_v, note)}
    arms = [control, cand]

    title_univ = "custom univ" if univ is not None else "mom_baseline_20260828"
    write_stamp_html(
        out,
        title=f"MOM ∩ Valuation gate AB — {title_univ}",
        meta=(
            f"Stamp <code>{esc(stamp)}</code> · threshold ≥{thr:.0f} pre-declared · "
            f"research-only · {esc(pit_label)}"
        ),
        warn=(
            f"<strong>{esc(pit_label)}</strong> Valuation scores are a point-in-time "
            "stamp for nearly all MOM entries (PIT history starts ~2026-08-31; MOM Closed "
            "ends 2023-12-28). Treat as research upper-bound. OOS trade-level N=0 on this "
            "freeze. Not DailyRun."
        ),
        baseline_md_link="BASELINE.md",
        arms=arms,
        control=control,
        verdicts=verdicts,
        extra_html=(
            f'<div class="info">Universe: {esc(univ_note)}. '
            f"Gate pass trades={len(kept)} / {len(all_trades)}; "
            f"syms={cov['n_keep_sym']}; PIT hits={cov['n_pit_hits']}; "
            f"snapshot hits={cov['n_snapshot_hits']}; missing={cov['n_missing']}. "
            f"Scores: <code>{esc(scores_path.as_posix())}</code>. "
            f"Cash model ${MOM_CASH:,.0f}.</div>"
        ),
    )
    write_summary(
        out,
        stamp=stamp,
        thr=thr,
        arms=arms,
        verdicts=verdicts,
        pit_label=pit_label,
        cov=cov,
        scores_path=scores_path,
        pit_meta=pit_meta,
        univ_note=univ_note,
    )

    # Optional Closed CSVs for inspection
    def _write_closed(path: Path, trades: list[dict[str, Any]]) -> None:
        cols = [
            "SYMBOL",
            "ENTRY_DATE",
            "EXIT_DATE",
            "PNL_PCT",
            "PNL_DOLLARS",
            "DAYS_HELD",
            "EXIT_REASON",
        ]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for t in trades:
                w.writerow(
                    {
                        "SYMBOL": t["sym"],
                        "ENTRY_DATE": t["opened"].isoformat(),
                        "EXIT_DATE": t["closed"].isoformat() if t["closed"] else "",
                        "PNL_PCT": t["pnl"],
                        "PNL_DOLLARS": t["pnl_d"],
                        "DAYS_HELD": t["days"],
                        "EXIT_REASON": t["exit"],
                    }
                )

    _write_closed(out / "MOM_Closed_control_univ.csv", all_trades)
    _write_closed(out / "MOM_Closed_valuation_ge_60.csv", kept)

    print(
        f"[mom_val_gate] done -> {out} overall={tag} IS={is_v} OOS={oos_v} "
        f"pass={len(kept)}/{len(all_trades)} univ_syms={univ_syms_traded}/{univ_n_list or univ_syms_traded} "
        f"pit={cov['n_pit_hits']} snap={cov['n_snapshot_hits']} label={pit_label}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
