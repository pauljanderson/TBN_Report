#!/usr/bin/env python3
"""VZ research: breakout amount and time-to-retest vs PnL / Ann ROR.

Uses the same rw126 DualPaul78 closed-trade stamp as the OC-overlap study
(prior to the rw63 trade-count cut). Amount = how far price went above the
zone before the retest; time = bars from upside break to fill.

  python tools/vz_breakout_amt_time.py
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from vol_zone_break_retest import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_OUT_DIR,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    _fmt_num,
    _fmt_pct,
    bucket_bars_after_break,
    bucket_break_dist,
    load_ohlcv,
    sortable_th,
    split_is_oos,
    summarize_signal_dicts,
)
from vz_oc_overlap_vol_strength import (  # noqa: E402
    corr_with_p,
    quartile_table,
    within_symbol_spearman,
)

STAMP_DEFAULT = "vz_breakout_amt_time_20260813"
TRADES_DEFAULT = (
    REPO / "drive" / "paul_experiments" / "vz_oc_vol_strength_20260813" / "trades_oc_vol_strength.csv"
)

FEATURES = [
    ("bars_after_break", "Bars from upside break to fill (time)"),
    ("break_dist_pct", "Break-bar close vs zone.hi (amount)"),
    ("break_atr_mult", "Break-bar distance in ATR14 (amount)"),
    ("ext_pct", "Max high break→signal vs zone.hi (run-up amount)"),
    ("ext_atr", "Max high break→signal in ATR14 (run-up amount)"),
]


def _bucket_metrics(df: pd.DataFrame, key: str, order: list[str] | None = None) -> pd.DataFrame:
    rows = []
    for k, g in df.groupby(key, observed=True):
        m = summarize_signal_dicts(g.to_dict("records"))
        rows.append(
            {
                "bucket": str(k),
                "n": int(len(g)),
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "median_pnl_pct": m["median_pnl_pct"],
                "avg_r": m["avg_r"],
                "avg_days": m["avg_days_held"],
                "ann_ror": m["ann_ror"],
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    if order:
        out["_ord"] = out["bucket"].map({b: i for i, b in enumerate(order)})
        out = out.sort_values(["_ord", "bucket"]).drop(columns=["_ord"])
    return out


def enrich_extension(df: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """Max high from break through signal vs zone.hi (known by signal close)."""
    out = df.copy()
    out["ext_pct"] = np.nan
    out["ext_atr"] = np.nan
    out["break_idx"] = np.nan
    for sym, g in out.groupby("symbol"):
        path = data_dir / f"{sym}.csv"
        if not path.is_file():
            continue
        ohlc = load_ohlcv(path)
        dates = pd.to_datetime(ohlc["Date"]).dt.normalize()
        by_date = {pd.Timestamp(d): i for i, d in enumerate(dates)}
        highs = ohlc["High"].to_numpy(dtype=np.float64)
        for idx, row in g.iterrows():
            bd = pd.Timestamp(row["break_date"]).normalize()
            if bd not in by_date:
                continue
            br_i = by_date[bd]
            sig_i = int(row["signal_idx"]) if pd.notna(row.get("signal_idx")) else -1
            if sig_i < 0 or sig_i >= len(highs):
                # next_open: entry = signal+1, bars_after_break = entry - break
                sig_i = br_i + max(int(row["bars_after_break"]) - 1, 0)
                sig_i = min(sig_i, len(highs) - 1)
            hi = float(row.get("zone_hi") or 0.0)
            if hi <= 0:
                continue
            sl = highs[br_i : sig_i + 1]
            if len(sl) == 0:
                continue
            mx = float(np.nanmax(sl))
            out.at[idx, "break_idx"] = br_i
            out.at[idx, "ext_pct"] = (mx - hi) / hi
            atr = float(row.get("break_atr_mult") or 0.0)
            # reconstruct ATR from break distance when possible
            dist = float(row.get("break_dist_pct") or 0.0)
            if atr > 0 and dist > 0:
                # break_atr = (close-hi)/ATR  and break_dist = (close-hi)/hi
                # ATR = hi * dist / atr_mult
                atr_px = hi * dist / atr
                out.at[idx, "ext_atr"] = (mx - hi) / atr_px if atr_px > 0 else np.nan
            else:
                out.at[idx, "ext_atr"] = np.nan
    return out


def write_scatter(df: pd.DataFrame, feat: str, path: Path, title: str) -> None:
    d = df.dropna(subset=[feat, "pnl_pct"])
    if d.empty:
        return
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.scatter(d[feat], d["pnl_pct"], s=10, alpha=0.28, c="#2a4a5c", edgecolors="none")
    ax.axhline(0.0, color="#999", lw=0.8)
    ax.set_xlabel(feat)
    ax.set_ylabel("pnl_pct")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _q_html(df: pd.DataFrame, caption: str) -> str:
    if df is None or df.empty:
        return f"<p class='muted'>{html_mod.escape(caption)}: empty.</p>"
    body = []
    name_col = "quartile" if "quartile" in df.columns else "bucket"
    for _, r in df.iterrows():
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r[name_col]))}</td>"
            f"<td>{int(r['n'])}</td>"
            f"<td>{_fmt_pct(float(r['win_rate']))}%</td>"
            f"<td>{_fmt_num(float(r['avg_pnl_pct']))}</td>"
            f"<td>{_fmt_num(float(r['median_pnl_pct']))}</td>"
            f"<td>{_fmt_num(float(r['avg_r']))}</td>"
            f"<td>{_fmt_num(float(r['avg_days']), 1)}</td>"
            f"<td>{_fmt_num(float(r['ann_ror']))}</td>"
            "</tr>"
        )
    heads = "".join(
        [
            sortable_th("Bucket", "text"),
            sortable_th("N", "num"),
            sortable_th("Win%", "num"),
            sortable_th("Avg PnL%", "num"),
            sortable_th("Med PnL%", "num"),
            sortable_th("Avg R", "num"),
            sortable_th("Avg days", "num"),
            sortable_th("Book Ann ROR%", "num"),
        ]
    )
    return (
        f"<div class='table-wrap'><table class='sortable'><caption>{html_mod.escape(caption)}</caption>"
        f"<thead><tr>{heads}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _corr_html(rows: list[dict]) -> str:
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['feature'])}</td>"
            f"<td>{html_mod.escape(r['label'])}</td>"
            f"<td>{html_mod.escape(r['vs'])}</td>"
            f"<td>{r['spearman']:+.3f}</td>"
            f"<td>{r['pearson']:+.3f}</td>"
            f"<td>{r['p_spearman']:.4f}</td>"
            f"<td>{r['n']}</td>"
            "</tr>"
        )
    heads = "".join(
        [
            sortable_th("Feature", "text"),
            sortable_th("Meaning", "text"),
            sortable_th("vs", "text"),
            sortable_th("Spearman", "num"),
            sortable_th("Pearson", "num"),
            sortable_th("p (Spearman)", "num"),
            sortable_th("N", "num"),
        ]
    )
    return (
        "<div class='table-wrap'><table class='sortable'><thead><tr>"
        + heads
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _two_by_two(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["bars_after_break", "ext_pct"]).copy()
    if d.empty:
        return pd.DataFrame()
    t_med = float(d["bars_after_break"].median())
    a_med = float(d["ext_pct"].median())
    d["time"] = np.where(d["bars_after_break"] <= t_med, "early", "late")
    d["amt"] = np.where(d["ext_pct"] <= a_med, "small", "large")
    d["cell"] = d["time"] + " / " + d["amt"]
    order = ["early / small", "early / large", "late / small", "late / large"]
    return _bucket_metrics(d, "cell", order)


def _verdict(corr_rows: list[dict], time_b: pd.DataFrame, amt_b: pd.DataFrame, oos_time: pd.DataFrame) -> str:
    def sp(feat: str, vs: str) -> float:
        hit = next((r for r in corr_rows if r["feature"] == feat and r["vs"] == vs), None)
        return float(hit["spearman"]) if hit else float("nan")

    rt = sp("bars_after_break", "pnl_pct")
    ra = sp("ext_pct", "pnl_pct")
    rd = sp("break_dist_pct", "pnl_pct")
    return (
        f"**No continuous ranking signal** (Spearman vs PnL: time {rt:+.3f}, "
        f"run-up {ra:+.3f}, break-bar {rd:+.3f}). "
        "Late retests (64–126d) are a weaker *group* — that is the rw63 cut already made. "
        "Tiny break-bar clears (<0.25%) look worse on means than ≥3% clears, but |r|≲0.04 "
        "so it is not a ranking filter. Do not add a new amount or time knob without a "
        "dedicated one-knob AB; time is already truncated by rw63."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="VZ breakout amount / time-to-retest vs PnL")
    ap.add_argument("--trades", default=str(TRADES_DEFAULT))
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    args = ap.parse_args()

    trades_path = Path(args.trades)
    if not trades_path.is_file():
        print(f"missing trades CSV: {trades_path}", flush=True)
        return 1
    df = pd.read_csv(trades_path)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["break_date"] = pd.to_datetime(df["break_date"])
    print(f"[VZ-amt] loaded {len(df)} closed trades from {trades_path.name}", flush=True)
    df = enrich_extension(df, Path(args.data_dir))
    print(
        f"[VZ-amt] ext_pct coverage {df['ext_pct'].notna().mean()*100:.0f}%  "
        f"median bars={df['bars_after_break'].median():.0f}  "
        f"median break_dist={df['break_dist_pct'].median()*100:.2f}%  "
        f"median ext={df['ext_pct'].median()*100:.2f}%",
        flush=True,
    )

    corr_rows: list[dict] = []
    for feat, label in FEATURES:
        if feat not in df.columns:
            continue
        for vs in ("pnl_pct", "ann_ror_pct", "r_mult"):
            rs, ps, n = corr_with_p(df[feat], df[vs], "spearman")
            rp, _, _ = corr_with_p(df[feat], df[vs], "pearson")
            corr_rows.append(
                {
                    "feature": feat,
                    "label": label,
                    "vs": vs,
                    "spearman": rs if np.isfinite(rs) else 0.0,
                    "pearson": rp if np.isfinite(rp) else 0.0,
                    "p_spearman": ps if np.isfinite(ps) else 1.0,
                    "n": n,
                }
            )

    recs = df.to_dict("records")
    is_rows, oos_rows = split_is_oos(recs)
    is_df = pd.DataFrame(is_rows)
    oos_df = pd.DataFrame(oos_rows)
    full_m = summarize_signal_dicts(recs)

    time_order = ["1-5", "6-21", "22-63", "64-126", "127+"]
    dist_order = ["<0.25%", "0.25-1%", "1-3%", ">=3%"]
    df["time_bucket"] = df["bars_after_break"].map(lambda x: bucket_bars_after_break(int(x)))
    df["dist_bucket"] = df["break_dist_pct"].map(lambda x: bucket_break_dist(float(x)))
    is_df["time_bucket"] = is_df["bars_after_break"].map(lambda x: bucket_bars_after_break(int(x)))
    oos_df["time_bucket"] = oos_df["bars_after_break"].map(lambda x: bucket_bars_after_break(int(x)))
    is_df["dist_bucket"] = is_df["break_dist_pct"].map(lambda x: bucket_break_dist(float(x)))
    oos_df["dist_bucket"] = oos_df["break_dist_pct"].map(lambda x: bucket_break_dist(float(x)))

    time_full = _bucket_metrics(df, "time_bucket", time_order)
    time_is = _bucket_metrics(is_df, "time_bucket", time_order)
    time_oos = _bucket_metrics(oos_df, "time_bucket", time_order)
    dist_full = _bucket_metrics(df, "dist_bucket", dist_order)
    dist_is = _bucket_metrics(is_df, "dist_bucket", dist_order)
    dist_oos = _bucket_metrics(oos_df, "dist_bucket", dist_order)
    q_time = quartile_table(df, "bars_after_break")
    q_dist = quartile_table(df, "break_dist_pct")
    q_ext = quartile_table(df, "ext_pct")
    q_ext_oos = quartile_table(oos_df, "ext_pct")
    two = _two_by_two(df)
    two_oos = _two_by_two(oos_df)

    w_time, w_n, _ = within_symbol_spearman(df, "bars_after_break", "pnl_pct")
    w_ext, _, _ = within_symbol_spearman(df, "ext_pct", "pnl_pct")
    w_dist, _, _ = within_symbol_spearman(df, "break_dist_pct", "pnl_pct")

    out_dir = Path(args.out_dir) / args.stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(corr_rows).to_csv(out_dir / "correlations.csv", index=False)
    df.to_csv(out_dir / "trades_amt_time.csv", index=False)
    time_full.to_csv(out_dir / "time_buckets.csv", index=False)
    dist_full.to_csv(out_dir / "amount_buckets.csv", index=False)
    write_scatter(df, "bars_after_break", out_dir / "scatter_time.png", "Bars after break vs PnL%")
    write_scatter(df, "ext_pct", out_dir / "scatter_ext.png", "Breakout run-up vs PnL%")
    write_scatter(df, "break_dist_pct", out_dir / "scatter_break_dist.png", "Break-bar distance vs PnL%")

    verdict = _verdict(corr_rows, time_full, dist_full, time_oos)
    print(verdict, flush=True)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VZ breakout amount / time — {html_mod.escape(args.stamp)}</title>
<style>
  body {{ font-family: Segoe UI, Helvetica, sans-serif; margin: 24px; color: #1c1b19; background: #f7f6f2; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 8px; }}
  h2 {{ font-size: 1.05rem; margin: 22px 0 8px; border-bottom: 1px solid #d4d0c4; padding-bottom: 4px; }}
  .muted {{ color: #5a574f; }}
  .callout {{ background: #e8eef2; border-left: 4px solid #2a4a5c; padding: 10px 12px; margin: 12px 0; }}
  .callout.warn {{ background: #f7efe0; border-left-color: #8a5a12; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }}
  th, td {{ border: 1px solid #d4d0c4; padding: 6px 8px; text-align: left; }}
  thead th {{ background: #f0eee6; }}
  {SORTABLE_TH_CSS}
  img {{ max-width: 48%; border: 1px solid #d4d0c4; background: #fff; }}
  code {{ background: #f0eee6; padding: 0.05em 0.3em; }}
</style></head><body>
<h1>VZ — breakout amount and time-to-retest</h1>
<p class="muted">Research only · {html_mod.escape(args.stamp)} · same rw126 DualPaul78 closed set (N={full_m['n_signals']})</p>
<div class="callout warn">
Prior to the rw63 trade-count cut. Amount = how far price went above the zone before the retest.
Time = bars from upside break close to fill (<code>bars_after_break</code>, includes T+1 next-open).
</div>
<p>{html_mod.escape(verdict)}</p>
<h2>1. Correlations</h2>
{_corr_html(corr_rows)}
<p class="muted">Within-symbol mean Spearman vs PnL (symbols ≥8 trades, n={w_n}):
time {w_time:+.3f} · run-up {w_ext:+.3f} · break-bar {w_dist:+.3f}.</p>
<h2>2. Time buckets (engine slices)</h2>
{_q_html(time_full, "FULL — bars after break")}
{_q_html(time_is, "IS — bars after break")}
{_q_html(time_oos, "OOS — bars after break")}
{_q_html(q_time, "FULL quartiles of bars_after_break")}
<h2>3. Amount — break-bar close vs zone.hi</h2>
{_q_html(dist_full, "FULL — break distance")}
{_q_html(dist_is, "IS — break distance")}
{_q_html(dist_oos, "OOS — break distance")}
{_q_html(q_dist, "FULL quartiles of break_dist_pct")}
<h2>4. Amount — max high from break through signal</h2>
{_q_html(q_ext, "FULL quartiles of ext_pct")}
{_q_html(q_ext_oos, "OOS quartiles of ext_pct")}
<h2>5. Joint (median split): early/late × small/large run-up</h2>
{_q_html(two, "FULL 2×2")}
{_q_html(two_oos, "OOS 2×2")}
<h2>6. Scatters</h2>
<p><img src="scatter_time.png" alt="time"/> <img src="scatter_ext.png" alt="run-up"/></p>
<footer class="muted">Twin Beacon Networks · VZ research · {html_mod.escape(args.stamp)}</footer>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    (out_dir / "VZ_Breakout_Amt_Time.html").write_text(html, encoding="utf-8")

    def md_table(frame: pd.DataFrame, name_col: str) -> list[str]:
        if frame is None or frame.empty:
            return ["_(empty)_", ""]
        lines = [
            f"| {name_col} | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for _, r in frame.iterrows():
            lines.append(
                f"| {r[name_col]} | {int(r['n'])} | {_fmt_pct(float(r['win_rate']))}% | "
                f"{_fmt_num(float(r['avg_pnl_pct']))} | {_fmt_num(float(r['median_pnl_pct']))} | "
                f"{_fmt_num(float(r['ann_ror']))} |"
            )
        lines.append("")
        return lines

    def sp_line(feat: str, vs: str) -> str:
        hit = next((r for r in corr_rows if r["feature"] == feat and r["vs"] == vs), None)
        if not hit:
            return "—"
        return f"{hit['spearman']:+.3f} (p={hit['p_spearman']:.3f}, N={hit['n']})"

    md_lines = [
        "# VZ breakout amount and time-to-retest vs PnL / Ann ROR",
        "",
        "Research only. Same rw126 DualPaul78 closed trades as the OC-overlap study "
        f"(N={full_m['n_signals']}, prior to the rw63 cut).",
        "",
        "## Verdict",
        "",
        verdict,
        "",
        "## What was measured",
        "",
        "- **Time:** `bars_after_break` — trading bars from upside break close to fill (next-open, so includes T+1).",
        "- **Amount (break bar):** `break_dist_pct` / `break_atr_mult` — how far the break close cleared `zone.hi`.",
        "- **Amount (run-up):** `ext_pct` — max high from the break bar through the signal bar, vs `zone.hi`. Known by signal close; no look-ahead.",
        "",
        "## Spearman",
        "",
        "| Feature | vs PnL% | vs trade Ann ROR | vs R |",
        "|---|---|---|---|",
        f"| bars_after_break (time) | {sp_line('bars_after_break','pnl_pct')} | {sp_line('bars_after_break','ann_ror_pct')} | {sp_line('bars_after_break','r_mult')} |",
        f"| break_dist_pct (amount) | {sp_line('break_dist_pct','pnl_pct')} | {sp_line('break_dist_pct','ann_ror_pct')} | {sp_line('break_dist_pct','r_mult')} |",
        f"| break_atr_mult | {sp_line('break_atr_mult','pnl_pct')} | {sp_line('break_atr_mult','ann_ror_pct')} | {sp_line('break_atr_mult','r_mult')} |",
        f"| ext_pct (run-up) | {sp_line('ext_pct','pnl_pct')} | {sp_line('ext_pct','ann_ror_pct')} | {sp_line('ext_pct','r_mult')} |",
        f"| ext_atr | {sp_line('ext_atr','pnl_pct')} | {sp_line('ext_atr','ann_ror_pct')} | {sp_line('ext_atr','r_mult')} |",
        "",
        f"Within-symbol mean Spearman vs PnL: time {w_time:+.3f} · run-up {w_ext:+.3f} · break-bar {w_dist:+.3f}.",
        "",
        "## Time buckets",
        "",
        "### FULL",
        "",
        *md_table(time_full, "bucket"),
        "### OOS",
        "",
        *md_table(time_oos, "bucket"),
        "## Amount buckets (break-bar close vs zone.hi)",
        "",
        "### FULL",
        "",
        *md_table(dist_full, "bucket"),
        "### OOS",
        "",
        *md_table(dist_oos, "bucket"),
        "## Run-up quartiles (`ext_pct`)",
        "",
        "### FULL",
        "",
        *md_table(q_ext, "quartile"),
        "### OOS",
        "",
        *md_table(q_ext_oos, "quartile"),
        "## Joint median split (time × run-up)",
        "",
        *md_table(two, "bucket"),
        "### OOS 2×2",
        "",
        *md_table(two_oos, "bucket"),
        "## Reproduce",
        "",
        "```",
        "python tools/vz_breakout_amt_time.py",
        "```",
        "",
    ]
    md = "\n".join(md_lines)
    (out_dir / "README.md").write_text(md, encoding="utf-8")
    docs = REPO / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "vz_breakout_amt_time.md").write_text(md, encoding="utf-8")
    (docs / "vz_breakout_amt_time.html").write_text(html, encoding="utf-8")
    pd.DataFrame(corr_rows).to_csv(docs / "vz_breakout_amt_time_correlations.csv", index=False)
    print(f"[VZ-amt] wrote {out_dir} and docs/research/vz_breakout_amt_time.md", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
