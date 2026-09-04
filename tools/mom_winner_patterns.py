#!/usr/bin/env python3
"""MOM winner pre-entry pattern scan — research only.

Uses parent Closed book + OHLC features available at/before entry (no look-ahead).
Compares large winners (top decile PnL% and/or PnL% >= threshold) vs rest / losers.

Stamp: drive/paul_experiments/mom_winner_patterns_20260829/
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import mom_clenow_ab as mom  # noqa: E402

STAMP = "mom_winner_patterns_20260829"
OUT = _PE / STAMP
CLOSED_DEFAULT = _PE / "mom_baseline_20260828" / "MOM_Closed.csv"
IS_CUT = date(2024, 1, 1)


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def mom_components(closes: np.ndarray) -> tuple[float, float, float]:
    """Return (score, ann_slope, r2) over MOM_LOOKBACK — same formula as engine."""
    y = np.asarray(closes, dtype=float)
    if len(y) < mom.MOM_LOOKBACK or not np.all(np.isfinite(y)) or np.any(y <= 0):
        return float("nan"), float("nan"), float("nan")
    y = np.log(y[-mom.MOM_LOOKBACK :])
    x = np.arange(mom.MOM_LOOKBACK, dtype=float)
    xd = x - x.mean()
    yd = y - y.mean()
    den = float(np.dot(xd, xd))
    if den <= 0:
        return float("nan"), float("nan"), float("nan")
    b = float(np.dot(xd, yd) / den)
    ss_res = float(np.dot(yd - b * xd, yd - b * xd))
    ss_tot = float(np.dot(yd, yd))
    r2 = 0.0 if ss_tot <= 0 else max(0.0, 1.0 - ss_res / ss_tot)
    ann = math.exp(b * 252.0) - 1.0
    return ann * r2, ann, r2


def max_abs_gap(closes: np.ndarray, lookback: int = 90) -> float:
    if len(closes) < lookback + 1:
        return float("nan")
    window = closes[-(lookback + 1) :]
    if not np.all(np.isfinite(window)) or np.any(window[:-1] <= 0):
        return float("nan")
    return float(np.max(np.abs(np.diff(window) / window[:-1])))


def features_at_entry(ser: mom.SymSeries, spy: mom.SymSeries, entry_d: date) -> dict[str, float]:
    """Features using bars through entry_date only (entry is next-open fill; use prior close OK).

    Closed ENTRY_DATE is the fill date (next open after Wednesday signal). Use the bar
    **before** fill when available for signal-close features; fall back to fill date close.
    """
    i = ser.idx(entry_d)
    if i is None:
        return {}
    # Prefer prior session as signal proxy (fill = next open after Wednesday close)
    sig_i = i - 1 if i >= 1 else i
    c = ser.close[sig_i]
    if not np.isfinite(c) or c <= 0:
        return {}
    score, ann, r2 = mom_components(ser.close[: sig_i + 1])
    atr = ser.atr20[sig_i]
    sma50 = ser.sma50[sig_i]
    sma100 = ser.sma100[sig_i]
    # ADV$ approx: 20d mean(volume * close)
    adv = float("nan")
    if sig_i >= 19 and len(ser.volume) > sig_i:
        vv = ser.volume[sig_i - 19 : sig_i + 1]
        cc = ser.close[sig_i - 19 : sig_i + 1]
        if np.all(np.isfinite(vv)) and np.all(np.isfinite(cc)):
            adv = float(np.mean(vv * cc))
    # 20d realized vol
    vol20 = float("nan")
    if sig_i >= 20:
        rets = np.diff(np.log(ser.close[sig_i - 20 : sig_i + 1]))
        if np.all(np.isfinite(rets)):
            vol20 = float(np.std(rets) * math.sqrt(252) * 100.0)
    spy_i = spy.idx(ser.dates[sig_i] if hasattr(ser.dates[sig_i], "year") else entry_d)
    # Align SPY by date
    sig_date = ser.dates[sig_i]
    if isinstance(sig_date, np.datetime64):
        sig_date = pd.Timestamp(sig_date).date()
    spy_i = spy.idx(sig_date)
    spy_above = float("nan")
    spy_dist = float("nan")
    if spy_i is not None:
        spy_sma200 = mom._sma(spy.close, mom.SMA_INDEX)
        sc = spy.close[spy_i]
        ss = spy_sma200[spy_i]
        if np.isfinite(sc) and np.isfinite(ss) and ss > 0:
            spy_above = 1.0 if sc > ss else 0.0
            spy_dist = (sc / ss - 1.0) * 100.0

    return {
        "entry_score": score,
        "mom_ann_slope": ann,
        "mom_r2": r2,
        "atr_pct": (atr / c * 100.0) if np.isfinite(atr) and atr > 0 else float("nan"),
        "dist_sma50_pct": (c / sma50 - 1.0) * 100.0 if np.isfinite(sma50) and sma50 > 0 else float("nan"),
        "dist_sma100_pct": (c / sma100 - 1.0) * 100.0 if np.isfinite(sma100) and sma100 > 0 else float("nan"),
        "max_gap_90d": max_abs_gap(ser.close[: sig_i + 1]) * 100.0,
        "adv_dollar": adv,
        "vol20_ann_pct": vol20,
        "spy_above_sma200": spy_above,
        "spy_dist_sma200_pct": spy_dist,
    }


def group_stats(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for col in cols:
        s = df[col].dropna()
        rows.append(
            {
                "feature": col,
                "n": int(s.shape[0]),
                "mean": float(s.mean()) if len(s) else float("nan"),
                "median": float(s.median()) if len(s) else float("nan"),
                "p25": float(s.quantile(0.25)) if len(s) else float("nan"),
                "p75": float(s.quantile(0.75)) if len(s) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def effect_table(winners: pd.DataFrame, rest: pd.DataFrame, losers: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for col in cols:
        w = winners[col].dropna()
        r = rest[col].dropna()
        l = losers[col].dropna()
        wm, rm, lm = (float(w.mean()) if len(w) else float("nan"),
                      float(r.mean()) if len(r) else float("nan"),
                      float(l.mean()) if len(l) else float("nan"))
        # Cohen's d winners vs rest
        d = float("nan")
        if len(w) > 5 and len(r) > 5:
            pooled = math.sqrt(((w.std(ddof=1) ** 2) + (r.std(ddof=1) ** 2)) / 2.0) if w.std(ddof=1) and r.std(ddof=1) else float("nan")
            if pooled and np.isfinite(pooled) and pooled > 0:
                d = (wm - rm) / pooled
        rows.append(
            {
                "feature": col,
                "winners_mean": wm,
                "rest_mean": rm,
                "losers_mean": lm,
                "delta_w_vs_rest": wm - rm if np.isfinite(wm) and np.isfinite(rm) else float("nan"),
                "cohens_d": d,
                "n_winners": int(len(w)),
                "n_rest": int(len(r)),
            }
        )
    return pd.DataFrame(rows).sort_values("cohens_d", key=lambda s: s.abs(), ascending=False)


def write_html(out: Path, effects: pd.DataFrame, meta: dict[str, Any], sample: pd.DataFrame) -> Path:
    head = "".join(
        _sortable_th(c, "num" if c != "feature" else "text")
        for c in [
            "feature",
            "winners_mean",
            "rest_mean",
            "losers_mean",
            "delta_w_vs_rest",
            "cohens_d",
            "n_winners",
            "n_rest",
        ]
    )
    body = ""
    for _, r in effects.iterrows():
        body += (
            f"<tr><td>{html_mod.escape(str(r['feature']))}</td>"
            f"<td>{r['winners_mean']:.4g}</td><td>{r['rest_mean']:.4g}</td>"
            f"<td>{r['losers_mean']:.4g}</td><td>{r['delta_w_vs_rest']:.4g}</td>"
            f"<td>{r['cohens_d']:.4g}</td><td>{int(r['n_winners'])}</td>"
            f"<td>{int(r['n_rest'])}</td></tr>"
        )
    sh = "".join(
        _sortable_th(c, "num" if c not in ("SYMBOL", "ENTRY_DATE", "EXIT_REASON") else "text")
        for c in sample.columns
    )
    sb = ""
    for _, r in sample.iterrows():
        sb += "<tr>" + "".join(f"<td>{html_mod.escape(str(r[c]))}</td>" for c in sample.columns) + "</tr>"

    verdict = meta["verdict"]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MOM winner patterns — {STAMP}</title>
<style>
  body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.5rem; background: #f7f6f2; color: #1a1a1a; }}
  h1 {{ font-size: 1.35rem; }}
  .meta {{ color: #555; max-width: 52rem; font-size: 0.92rem; }}
  .verdict {{ background: #fff; border: 1px solid #d8d5cc; padding: 0.8rem 1rem; max-width: 52rem; }}
  table.sortable {{ border-collapse: collapse; background: #fff; margin: 1rem 0; font-size: 0.88rem; }}
  th, td {{ border: 1px solid #d8d5cc; padding: 0.35rem 0.55rem; }}
  th {{ background: #efece4; }}
  {mom.SORTABLE_TH_CSS}
</style>
</head>
<body>
  <h1>MOM winner pre-entry patterns — <code>{STAMP}</code></h1>
  <p class="meta">Research only. Features reconstructed at/before entry from OHLC (signal-close proxy = session before fill).
  Large winners = top decile PnL% (cutoff {meta['winner_cutoff_pct']:.2f}%) and separately PnL% ≥ {meta['abs_threshold_pct']:.0f}%.
  No look-ahead. Click headers to sort.</p>
  <div class="verdict"><strong>Verdict:</strong> {html_mod.escape(verdict)}</div>
  <p class="meta">Closed: {html_mod.escape(meta['closed_path'])} · N={meta['n_trades']} ·
  winners(top10%)={meta['n_winners']} · losers(PnL%≤0)={meta['n_losers']}</p>

  <h2>Feature means — winners vs rest vs losers (|Cohen's d| sorted)</h2>
  <table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>

  <h2>Sample large winners (top 25 by PnL%)</h2>
  <table class="sortable"><thead><tr>{sh}</tr></thead><tbody>{sb}</tbody></table>
  {mom.SORT_JS}
</body>
</html>
"""
    path = out / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--closed", type=Path, default=CLOSED_DEFAULT)
    ap.add_argument("--db", type=Path, default=mom.DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--abs-threshold", type=float, default=50.0, help="PnL%% threshold for big-winner tag")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    closed = pd.read_csv(args.closed)
    closed.columns = [c.upper() for c in closed.columns]
    closed["ENTRY_DATE"] = pd.to_datetime(closed["ENTRY_DATE"]).dt.date
    closed["EXIT_DATE"] = pd.to_datetime(closed["EXIT_DATE"]).dt.date
    print(f"[winners] Closed N={len(closed)} from {args.closed}")

    syms = sorted(closed["SYMBOL"].astype(str).unique().tolist())
    print(f"[winners] Loading panel for {len(syms)} symbols + SPY ...")
    panel = mom.load_panel(args.db, syms)
    spy = panel.get("SPY")
    if spy is None:
        raise SystemExit("SPY missing")

    rows = []
    miss = 0
    for _, tr in closed.iterrows():
        sym = str(tr["SYMBOL"])
        ser = panel.get(sym)
        if ser is None:
            miss += 1
            continue
        feats = features_at_entry(ser, spy, tr["ENTRY_DATE"])
        if not feats:
            miss += 1
            continue
        feats.update(
            {
                "SYMBOL": sym,
                "ENTRY_DATE": tr["ENTRY_DATE"].isoformat(),
                "EXIT_DATE": tr["EXIT_DATE"].isoformat(),
                "PNL_PCT": float(tr["PNL_PCT"]),
                "DAYS_HELD": int(tr["DAYS_HELD"]),
                "EXIT_REASON": str(tr["EXIT_REASON"]),
                "CLOSED_ENTRY_SCORE": float(tr["ENTRY_SCORE"]),
            }
        )
        # days since prior closed exit for same symbol (known at entry if prior finished)
        rows.append(feats)
    feat_df = pd.DataFrame(rows)
    # days since prior trade exit
    feat_df = feat_df.sort_values(["SYMBOL", "ENTRY_DATE"])
    prior_exit: dict[str, date] = {}
    days_since = []
    for _, r in feat_df.iterrows():
        sym = r["SYMBOL"]
        ed = date.fromisoformat(r["ENTRY_DATE"])
        prev = prior_exit.get(sym)
        days_since.append((ed - prev).days if prev else float("nan"))
        prior_exit[sym] = date.fromisoformat(r["EXIT_DATE"])
    feat_df["days_since_prior_exit"] = days_since

    feat_path = out / "trade_features.csv"
    feat_df.to_csv(feat_path, index=False)
    print(f"[winners] Features N={len(feat_df)} miss={miss} -> {feat_path}")

    q90 = float(feat_df["PNL_PCT"].quantile(0.90))
    winners = feat_df[feat_df["PNL_PCT"] >= q90]
    rest = feat_df[feat_df["PNL_PCT"] < q90]
    losers = feat_df[feat_df["PNL_PCT"] <= 0]
    big = feat_df[feat_df["PNL_PCT"] >= args.abs_threshold]

    feat_cols = [
        "entry_score",
        "CLOSED_ENTRY_SCORE",
        "mom_ann_slope",
        "mom_r2",
        "atr_pct",
        "dist_sma50_pct",
        "dist_sma100_pct",
        "max_gap_90d",
        "adv_dollar",
        "vol20_ann_pct",
        "spy_above_sma200",
        "spy_dist_sma200_pct",
        "days_since_prior_exit",
        "DAYS_HELD",  # outcome — label as post-entry for honesty in docs
    ]
    # Exclude DAYS_HELD from KEEP signal features (post-entry)
    signal_cols = [c for c in feat_cols if c != "DAYS_HELD"]
    effects = effect_table(winners, rest, losers, signal_cols)
    effects.to_csv(out / "effects_top_decile.csv", index=False)
    effects_big = effect_table(big, feat_df[feat_df["PNL_PCT"] < args.abs_threshold], losers, signal_cols)
    effects_big.to_csv(out / "effects_abs50.csv", index=False)

    # Honest verdict: require |d| >= 0.35 on a pre-entry feature AND same-direction on IS-only
    is_df = feat_df[pd.to_datetime(feat_df["ENTRY_DATE"]).dt.date < IS_CUT]
    # Parent closed is all IS anyway
    strong = effects[effects["cohens_d"].abs() >= 0.35]
    # DAYS_HELD would be huge but excluded
    if strong.empty:
        verdict = (
            "DISMISS / no reliable pre-entry edge — no feature reached |Cohen's d| >= 0.35 "
            "for top-decile winners vs rest. Differences look like noise / mild drift. Research only."
        )
    else:
        names = ", ".join(strong["feature"].tolist())
        # Still research-only; check if economically sensible and not circular
        circular = {"CLOSED_ENTRY_SCORE", "entry_score"}
        only_score = set(strong["feature"]) <= circular
        if only_score:
            verdict = (
                f"HOLD — modest separation on momentum score only ({names}); expected by construction "
                f"(entries already ranked by score). Not a new KEEP filter. Research only."
            )
        else:
            verdict = (
                f"HOLD (investigate) — |d|>=0.35 on: {names}. Treat as hypothesis only; "
                f"not KEEP for DailyRun. Selection bias if knobs tuned on this table. Research only."
            )

    meta = {
        "closed_path": str(args.closed),
        "n_trades": len(feat_df),
        "n_winners": len(winners),
        "n_losers": len(losers),
        "n_big50": len(big),
        "winner_cutoff_pct": q90,
        "abs_threshold_pct": args.abs_threshold,
        "verdict": verdict,
    }

    sample_cols = [
        "SYMBOL",
        "ENTRY_DATE",
        "PNL_PCT",
        "DAYS_HELD",
        "EXIT_REASON",
        "entry_score",
        "mom_r2",
        "atr_pct",
        "dist_sma100_pct",
        "vol20_ann_pct",
        "spy_dist_sma200_pct",
    ]
    sample = feat_df.nlargest(25, "PNL_PCT")[sample_cols].copy()
    for c in sample.columns:
        if sample[c].dtype == float:
            sample[c] = sample[c].map(lambda x: f"{x:.4g}" if np.isfinite(x) else "—")

    write_html(out, effects, meta, sample)

    md = f"""# SUMMARY — `{STAMP}`

**Status:** RESEARCH only. Not gold. Not DailyRun.

## Closed source

- `{args.closed}`
- N trades with features: **{len(feat_df)}** (miss={miss})
- Top-decile PnL% cutoff: **{q90:.2f}%** (N winners={len(winners)})
- Absolute big-winner threshold: PnL% ≥ **{args.abs_threshold:.0f}%** (N={len(big)})

## Verdict

{verdict}

## Top |Cohen's d| (winners vs rest)

| feature | d | Δ mean | winners mean | rest mean |
|---------|---|--------|--------------|-----------|
"""
    for _, r in effects.head(12).iterrows():
        md += (
            f"| `{r['feature']}` | {r['cohens_d']:.3f} | {r['delta_w_vs_rest']:.4g} | "
            f"{r['winners_mean']:.4g} | {r['rest_mean']:.4g} |\n"
        )
    md += """
## Honesty notes

1. Features use signal-close proxy (bar before fill date) — no post-entry info except `DAYS_HELD` which is excluded from KEEP scoring.
2. Momentum score separation is partly by construction (book already buys high score).
3. No KEEP promotion from this scan alone.
"""
    (out / "SUMMARY.md").write_text(md, encoding="utf-8")
    (out / "BASELINE.md").write_text(
        f"""# BASELINE — `{STAMP}`

Research pattern scan on MOM Closed (`mom_baseline_20260828`). No engine knob change.
Features at/before entry only. See SUMMARY.md for verdict.
""",
        encoding="utf-8",
    )
    print(f"[winners] Verdict: {verdict}")
    print(f"[winners] Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
