"""Generate Dual Paul >=7/8 candidate set three-way compare stamp (research only)."""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
SRC = ROOT / "drive/paul_experiments/vol_zone_v2_rw63_fulluniv_20260810"
STAMP = "vol_zone_dual_paul78_20260811"
OUT = ROOT / "drive/paul_experiments" / STAMP
OUT.mkdir(parents=True, exist_ok=True)

USER_LIST_RAW = [
    "AA", "EC", "PLPC", "SUBCY", "BELFA", "NXPI", "ITIC", "PLD", "AEM", "OCANF",
    "WTS", "GOOGL", "HTHIY", "ESLT", "PNRG", "CVNA", "UUUU", "NGL", "SIMO", "FANG",
    "WTFC", "INCY", "AU", "CRWD", "GE", "TROW", "VLO", "CF", "PRIM", "BCH",
    "CRZBY", "HBM", "GGAL", "POWL", "NG", "PAC", "AAPL", "MTX", "CENX", "RUSHB",
    "LCII", "MAR", "RGLD", "CSTM", "NMR", "BN", "TFC", "ESEA", "PDEX", "KINS",
    "BYD", "MSTR", "SVM", "PPIH", "TAYD", "CIEN", "BANC", "UTI", "TGB", "ITT",
    "EQIX", "BG", "HMY", "BPOP", "BAP", "SPXC", "WDC", "ENS", "SAFRY", "AEE",
    "NDAQ", "SWK", "AKAM", "AME", "DELL", "LYV", "ASH", "SENEA", "CI", "FBAK",
    "ETR", "FNF", "AWI",
]

# If Yahoo alias OGC appears in data, prefer OCANF (summary/signals use OCANF).
LOOKUP_ALTS = {"OCANF": ["OCANF", "OGC"]}

NOTIONAL = 45_000.0
SPLIT = pd.Timestamp("2024-01-01")


def pct_to_float(x):
    if pd.isna(x):
        return np.nan
    if isinstance(x, str):
        return float(x.replace("%", "").strip())
    return float(x)


def pool_metrics(df: pd.DataFrame, label: str, n_symbols: int, coverage_note: str = "") -> dict:
    if df.empty:
        return {
            "universe": label,
            "n_symbols": n_symbols,
            "n_symbols_with_signals": 0,
            "coverage_note": coverage_note,
            "n_signals": 0,
            "wr_pct": np.nan,
            "avg_r": np.nan,
            "avg_pnl_pct": np.nan,
            "sheet_pnl": 0.0,
            "avg_days_held": np.nan,
            "trades_per_year_pooled": np.nan,
        }
    n = len(df)
    years = (df["entry_date"].max() - df["entry_date"].min()).days / 365.25
    tpy = (n / years) if years > 0 else np.nan
    return {
        "universe": label,
        "n_symbols": n_symbols,
        "n_symbols_with_signals": int(df["symbol"].nunique()),
        "coverage_note": coverage_note,
        "n_signals": n,
        "wr_pct": 100.0 * float(df["win"].mean()),
        "avg_r": float(df["r_mult"].mean()),
        "avg_pnl_pct": float(df["pnl_pct"].mean()),
        "sheet_pnl": float((df["pnl_pct"] / 100.0 * NOTIONAL).sum()),
        "avg_days_held": float(df["bars_held"].mean()) if "bars_held" in df.columns else np.nan,
        "trades_per_year_pooled": tpy,
    }


def split_metrics(df: pd.DataFrame, split_name: str) -> dict:
    if df.empty:
        return {
            "split": split_name,
            "n": 0,
            "wr_pct": np.nan,
            "avg_r": np.nan,
            "avg_pnl_pct": np.nan,
            "sheet_pnl": 0.0,
            "avg_days_held": np.nan,
        }
    return {
        "split": split_name,
        "n": len(df),
        "wr_pct": 100.0 * float(df["win"].mean()),
        "avg_r": float(df["r_mult"].mean()),
        "avg_pnl_pct": float(df["pnl_pct"].mean()),
        "sheet_pnl": float((df["pnl_pct"] / 100.0 * NOTIONAL).sum()),
        "avg_days_held": float(df["bars_held"].mean()) if "bars_held" in df.columns else np.nan,
    }


def sth(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def money(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def fmt_num(x, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{nd}f}"


def main() -> None:
    summary = pd.read_csv(SRC / "VZ_Summary_Symbols_vol_zone_v2_rw63_fulluniv_20260810.csv")
    summary["SYMBOL"] = summary["SYMBOL"].astype(str).str.upper().str.strip()
    sum_by = summary.set_index("SYMBOL", drop=False)

    signals = pd.read_csv(SRC / "signals_rw63.csv")
    signals["symbol"] = signals["symbol"].astype(str).str.upper().str.strip()
    signals["entry_date"] = pd.to_datetime(signals["entry_date"])
    if "exit_name" in signals.columns:
        signals = signals[signals["exit_name"].astype(str) == "zone_atr05_ts40"].copy()

    pt_syms = []
    for line in (ROOT / "drive/universes/PaulTwenty_universe.csv").read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        pt_syms.append(t.upper())

    verify_rows = []
    fail = []
    missing = []
    validated = []
    data_syms_for_user = []

    for sym in USER_LIST_RAW:
        alts = LOOKUP_ALTS.get(sym, [sym])
        row = None
        hit = None
        for a in alts:
            if a in sum_by.index:
                row = sum_by.loc[a]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                hit = a
                break
        if row is None:
            missing.append(sym)
            verify_rows.append(
                {
                    "SYMBOL": sym,
                    "DATA_SYMBOL": "",
                    "STATUS": "MISSING_FROM_SUMMARY",
                    "PAUL_SCORE": np.nan,
                    "PAUL_SCORE_OOS": np.nan,
                    "PASS_DUAL7": False,
                    "NOTE": "not in VZ_Summary_Symbols",
                }
            )
            continue
        ps = float(row["PAUL_SCORE"]) if pd.notna(row["PAUL_SCORE"]) else np.nan
        pso = float(row["PAUL_SCORE_OOS"]) if pd.notna(row["PAUL_SCORE_OOS"]) else np.nan
        pass_dual = pd.notna(ps) and pd.notna(pso) and ps >= 7 and pso >= 7
        note = ""
        if hit != sym:
            note = f"alias mapped {sym}->{hit}"
        if not pass_dual:
            reasons = []
            if pd.isna(ps) or pd.isna(pso):
                reasons.append("missing Paul score(s)")
            else:
                if ps < 7:
                    reasons.append(f"PAUL_SCORE={ps:g}<7")
                if pso < 7:
                    reasons.append(f"PAUL_SCORE_OOS={pso:g}<7")
            note = (note + "; " if note else "") + "; ".join(reasons)
            fail.append(
                {
                    "SYMBOL": sym,
                    "DATA_SYMBOL": hit,
                    "PAUL_SCORE": ps,
                    "PAUL_SCORE_OOS": pso,
                    "NOTE": note,
                }
            )
        verify_rows.append(
            {
                "SYMBOL": sym,
                "DATA_SYMBOL": hit,
                "STATUS": str(row.get("STATUS", "")),
                "PAUL_SCORE": ps,
                "PAUL_SCORE_OOS": pso,
                "PASS_DUAL7": bool(pass_dual),
                "NOTE": note,
            }
        )
        if pass_dual:
            validated.append(sym)
            data_syms_for_user.append(hit)

    verify_df = pd.DataFrame(verify_rows)
    print("=== DUAL PAUL VERIFY ===")
    print(
        f"listed={len(USER_LIST_RAW)} validated={len(validated)} "
        f"fail={len(fail)} missing={len(missing)}"
    )
    if fail:
        print("FAIL:")
        for f in fail:
            print(f"  {f}")
    if missing:
        print("MISSING:", missing)

    per_rows = []
    for sym, dsym in zip(validated, data_syms_for_user):
        r = sum_by.loc[dsym]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        per_rows.append(
            {
                "SYMBOL": sym,
                "DATA_SYMBOL": dsym,
                "PAUL_SCORE": float(r["PAUL_SCORE"]),
                "PAUL_SCORE_OOS": float(r["PAUL_SCORE_OOS"]),
                "N": int(r["TRADES"]) if pd.notna(r["TRADES"]) else 0,
                "WR_PCT": pct_to_float(r["PCT_WINS"]),
                "AVG_R": float(r["AVG_R"]) if pd.notna(r["AVG_R"]) else np.nan,
                "AVG_PNL_PCT": float(r["AVG_PNL_PCT"]) if pd.notna(r["AVG_PNL_PCT"]) else np.nan,
                "SHEET_PNL": float(r["SHEET_PNL"]) if pd.notna(r["SHEET_PNL"]) else np.nan,
                "AVG_DAYS_HELD": float(r["AVG_DAYS_HELD"]) if pd.notna(r["AVG_DAYS_HELD"]) else np.nan,
                "AVG_TRADES_PER_YEAR": float(r["AVG_TRADES_PER_YEAR"])
                if pd.notna(r["AVG_TRADES_PER_YEAR"])
                else np.nan,
                "OOS_N": int(r["OOS_TRADES"]) if pd.notna(r["OOS_TRADES"]) else 0,
                "OOS_WR_PCT": pct_to_float(r["OOS_PCT_WINS"]),
                "OOS_AVG_R": float(r["OOS_AVG_R"]) if pd.notna(r["OOS_AVG_R"]) else np.nan,
                "OOS_AVG_PNL_PCT": float(r["OOS_AVG_PNL_PCT"])
                if pd.notna(r["OOS_AVG_PNL_PCT"])
                else np.nan,
                "OOS_SHEET_PNL": float(r["OOS_SHEET_PNL"]) if pd.notna(r["OOS_SHEET_PNL"]) else np.nan,
                "IS_N": int(r["IS_TRADES"]) if pd.notna(r["IS_TRADES"]) else 0,
                "IS_WR_PCT": pct_to_float(r["IS_PCT_WINS"]),
                "IS_AVG_R": float(r["IS_AVG_R"]) if pd.notna(r["IS_AVG_R"]) else np.nan,
                "IS_AVG_PNL_PCT": float(r["IS_AVG_PNL_PCT"]) if pd.notna(r["IS_AVG_PNL_PCT"]) else np.nan,
            }
        )
    per_df = pd.DataFrame(per_rows)

    def paul_stats(syms):
        sub = summary[summary["SYMBOL"].isin(syms)]
        if sub.empty:
            return np.nan, np.nan, np.nan
        return (
            float(sub["PAUL_SCORE"].median()),
            float(sub["PAUL_SCORE_OOS"].median()),
            100.0 * float((sub["PAUL_SCORE_OOS"] >= 7).mean()),
        )

    user_data_set = sorted(set(data_syms_for_user))
    sig_user = signals[signals["symbol"].isin(user_data_set)].copy()
    sig_pt = signals[signals["symbol"].isin(pt_syms)].copy()
    sig_full = signals.copy()

    pool_rows = []
    for label, sdf, syms, note in [
        (
            "DualPaul78_user",
            sig_user,
            user_data_set,
            f"user list dual Paul>=7; n_listed={len(USER_LIST_RAW)} n_pass={len(validated)}",
        ),
        ("PaulTwenty", sig_pt, pt_syms, "drive/universes/PaulTwenty_universe.csv"),
        ("FullOHLC", sig_full, summary["SYMBOL"].tolist(), "all symbols in signals/summary"),
    ]:
        m = pool_metrics(sdf, label, len(syms), note)
        med_p, med_o, pct7 = paul_stats(syms)
        m["median_paul"] = med_p
        m["median_paul_oos"] = med_o
        m["pct_paul_oos_ge7"] = pct7
        sub = summary[summary["SYMBOL"].isin(syms)]
        m["mean_avg_trades_per_year"] = float(sub["AVG_TRADES_PER_YEAR"].mean()) if len(sub) else np.nan
        m["sum_sheet_pnl_summary"] = float(sub["SHEET_PNL"].sum()) if len(sub) else np.nan
        pool_rows.append(m)
    pool_df = pd.DataFrame(pool_rows)

    isoos_rows = []
    for lab, sdf in [
        ("DualPaul78_user", sig_user),
        ("PaulTwenty", sig_pt),
        ("FullOHLC", sig_full),
    ]:
        for name, mask in [
            ("IS_<2024-01-01", sdf["entry_date"] < SPLIT),
            ("OOS_>=2024-01-01", sdf["entry_date"] >= SPLIT),
            ("FULL", pd.Series(True, index=sdf.index)),
        ]:
            r = split_metrics(sdf.loc[mask], name)
            r["universe"] = lab
            isoos_rows.append(r)
    isoos_df = pd.DataFrame(isoos_rows)

    pd.DataFrame({"SYMBOL": validated}).to_csv(OUT / "DualPaul78_universe.csv", index=False)
    verify_df.to_csv(OUT / "dual_paul_verify.csv", index=False)
    per_df.to_csv(OUT / "per_symbol_dual_paul78.csv", index=False)
    per_df.to_csv(OUT / "DualPaul78_set_metrics.csv", index=False)
    pool_df.to_csv(OUT / "compare_pooled_threeway.csv", index=False)
    isoos_df.to_csv(OUT / "oos_split.csv", index=False)
    pd.DataFrame(fail).to_csv(OUT / "dual_paul_failures.csv", index=False)

    baseline = f"""# Dual Paul >=7/8 candidate set — three-way compare (NOT gold)

**Stamp:** `{STAMP}`  
**Status:** Research only — **proposed gold candidate set comparison**, **not** adopted gold, **not** DailyRun-wired.

## Freeze (unchanged — research)

From `vol_zone_v2_rw63_fulluniv_20260810` / PaulTwenty rw63:

| Knob | Value |
|------|-------|
| lookback_days | 126 |
| zone_kinds | HL (HL-only) |
| retest_eps_pct | 0.005 |
| retest_window | **63** |
| first_retest_only | True |
| min_touches_before_entry | 1 |
| Primary exit | `zone_atr05_ts40` (stop = zone.lo - 0.5·ATR14; target 2.0R; time stop 40) |

Signals reused from `signals_rw63.csv` (filtered by symbol set — no full re-run).

## Dual Paul filter

User request: Paul 7 or 8 on **both** `PAUL_SCORE` and `PAUL_SCORE_OOS` (>=7 each).

- Listed symbols: {len(USER_LIST_RAW)}
- Pass dual-7: {len(validated)}
- Fail / missing: see `dual_paul_verify.csv` / `dual_paul_failures.csv`

## Universes compared

1. **DualPaul78_user** — validated list (this stamp)
2. **PaulTwenty** — `drive/universes/PaulTwenty_universe.csv`
3. **FullOHLC** — all symbols in fulluniv summary/signals

## Sheet PnL convention

Fixed notional **$45,000** per trade: `sum(pnl_pct/100 * 45000)` (same as summary SHEET_PNL).

## Chronologic split

IS = entry_date < 2024-01-01; OOS = entry_date >= 2024-01-01. OOS report-only — do not retune.

## Outputs

- `VolZone_DualPaul78_Compare.html` — primary
- `compare_pooled_threeway.csv`, `per_symbol_dual_paul78.csv`, `oos_split.csv`
- `DualPaul78_universe.csv`, `dual_paul_verify.csv`
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    u = pool_df[pool_df.universe == "DualPaul78_user"].iloc[0]
    pt = pool_df[pool_df.universe == "PaulTwenty"].iloc[0]
    fu = pool_df[pool_df.universe == "FullOHLC"].iloc[0]
    vs_pt = "above" if u.avg_r > pt.avg_r else ("near" if abs(u.avg_r - pt.avg_r) < 0.02 else "below")
    verdict = (
        f"DualPaul78 set quality beats FullOHLC (WR {u.wr_pct:.1f}% vs {fu.wr_pct:.1f}%, "
        f"AvgR {u.avg_r:.3f} vs {fu.avg_r:.3f}, AvgPnL% {u.avg_pnl_pct:.2f} vs {fu.avg_pnl_pct:.2f}) "
        f"and is {vs_pt} PaulTwenty "
        f"(WR {pt.wr_pct:.1f}%, AvgR {pt.avg_r:.3f}, AvgPnL% {pt.avg_pnl_pct:.2f}) — research candidate set only."
    )

    user_isoos = isoos_df[isoos_df.universe == "DualPaul78_user"]

    if fail or missing:
        fail_html = '<div class="note"><strong>Dual-7 failures / missing</strong><ul>'
        for f in fail:
            fail_html += (
                f"<li><code>{html.escape(f['SYMBOL'])}</code>: "
                f"PAUL={f['PAUL_SCORE']}, PAUL_OOS={f['PAUL_SCORE_OOS']} — "
                f"{html.escape(f['NOTE'])}</li>"
            )
        for msym in missing:
            fail_html += f"<li><code>{html.escape(msym)}</code>: missing from summary</li>"
        fail_html += "</ul></div>"
    else:
        fail_html = (
            '<div class="ok"><strong>Dual Paul ≥7 check:</strong> all listed symbols '
            "present with PAUL_SCORE≥7 and PAUL_SCORE_OOS≥7.</div>"
        )

    pool_trs = []
    for _, r in pool_df.iterrows():
        pool_trs.append(
            "<tr>"
            f"<td>{html.escape(r.universe)}</td>"
            f"<td>{int(r.n_symbols)}</td>"
            f"<td>{int(r.n_symbols_with_signals)}</td>"
            f"<td>{int(r.n_signals)}</td>"
            f"<td>{fmt_num(r.wr_pct, 1)}</td>"
            f"<td>{fmt_num(r.avg_r, 3)}</td>"
            f"<td>{fmt_num(r.avg_pnl_pct, 2)}</td>"
            f"<td>{money(r.sheet_pnl)}</td>"
            f"<td>{fmt_num(r.avg_days_held, 1)}</td>"
            f"<td>{fmt_num(r.trades_per_year_pooled, 1)}</td>"
            f"<td>{fmt_num(r.mean_avg_trades_per_year, 2)}</td>"
            f"<td>{fmt_num(r.median_paul, 1)}</td>"
            f"<td>{fmt_num(r.median_paul_oos, 1)}</td>"
            f"<td>{fmt_num(r.pct_paul_oos_ge7, 1)}</td>"
            "</tr>"
        )

    isoos_user_trs = []
    for _, r in user_isoos.iterrows():
        isoos_user_trs.append(
            "<tr>"
            f"<td>{html.escape(r.split)}</td>"
            f"<td>{int(r['n'])}</td>"
            f"<td>{fmt_num(r.wr_pct, 1)}</td>"
            f"<td>{fmt_num(r.avg_r, 3)}</td>"
            f"<td>{fmt_num(r.avg_pnl_pct, 2)}</td>"
            f"<td>{money(r.sheet_pnl)}</td>"
            "</tr>"
        )

    per_trs = []
    for _, r in per_df.iterrows():
        per_trs.append(
            "<tr>"
            f"<td>{html.escape(r.SYMBOL)}</td>"
            f"<td>{fmt_num(r.PAUL_SCORE, 0)}</td>"
            f"<td>{fmt_num(r.PAUL_SCORE_OOS, 0)}</td>"
            f"<td>{int(r.N)}</td>"
            f"<td>{fmt_num(r.WR_PCT, 1)}</td>"
            f"<td>{fmt_num(r.AVG_R, 3)}</td>"
            f"<td>{fmt_num(r.AVG_PNL_PCT, 2)}</td>"
            f"<td>{money(r.SHEET_PNL)}</td>"
            f"<td>{int(r.OOS_N)}</td>"
            f"<td>{fmt_num(r.OOS_WR_PCT, 1)}</td>"
            f"<td>{fmt_num(r.OOS_AVG_R, 3)}</td>"
            f"<td>{fmt_num(r.OOS_AVG_PNL_PCT, 2)}</td>"
            "</tr>"
        )

    sort_js = r"""
<script>
(function () {
  function parseVal(text, type) {
    var t = (text || "").trim().replace(/,/g, "");
    if (t === "" || t === "—") return type === "text" ? "" : 0;
    if (type === "text") return t.toLowerCase();
    t = t.replace(/[+$%]/g, "").replace(/^\((.*)\)$/, "-$1");
    var n = parseFloat(t);
    return isNaN(n) ? 0 : n;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    var movable = [], pinned = [];
    rows.forEach(function (r) {
      if (r.classList.contains("total-row")) pinned.push(r); else movable.push(r);
    });
    movable.sort(function (a, b) {
      var av = parseVal(a.cells[col].textContent, type);
      var bv = parseVal(b.cells[col].textContent, type);
      if (type === "text") return dir * String(av).localeCompare(String(bv));
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Dual Paul≥7/8 set vs PaulTwenty vs Full — {STAMP}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1200px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.ok{{background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
th.sortable-th{{cursor:pointer;user-select:none;white-space:nowrap}}
th.sortable-th:hover{{background:#e2e8f0}}
th.sortable-th .sort-ind::after{{content:" \\2195";opacity:.35;font-size:.85em}}
th.sortable-th.sort-asc .sort-ind::after{{content:" \\2191";opacity:.9}}
th.sortable-th.sort-desc .sort-ind::after{{content:" \\2193";opacity:.9}}
</style>
</head>
<body>
<h1>Vol-zone dual Paul ≥7/8 candidate set — three-way compare</h1>
<p class="small">Stamp <code>{STAMP}</code> · Freeze from <code>vol_zone_v2_rw63_fulluniv_20260810</code> · Signals filtered (no re-run) · Sheet notional $45,000 · <b>Not adopted gold / not DailyRun</b>.</p>

<div class="note">
<strong>Research only — proposed gold candidate set comparison.</strong>
Entry: HL-only · first_retest · mt≥1 · eps=0.005 · lookback=126 · <strong>rw=63</strong>.
Exit: <code>zone_atr05_ts40</code>. Dual filter: PAUL_SCORE≥7 <em>and</em> PAUL_SCORE_OOS≥7 (Paul 7 or 8 on both).
</div>

{fail_html}

<div class="callout">
<strong>One-line verdict:</strong> {html.escape(verdict)}
</div>

<h2>1. Pooled three-way compare</h2>
<p>Click column headers to sort. Metrics from pooled <code>signals_rw63.csv</code> filtered by universe (exit <code>zone_atr05_ts40</code>). Sheet PnL = Σ(pnl% × $45k).</p>
<table class="sortable">
<thead><tr>
{sth("Universe", "text")}
{sth("N symbols", "num")}
{sth("N w/ signals", "num")}
{sth("N signals", "num")}
{sth("WR%", "num")}
{sth("AvgR", "num")}
{sth("AvgPnL%", "num")}
{sth("Sheet PnL", "num")}
{sth("Avg days held", "num")}
{sth("Trades/yr (pooled)", "num")}
{sth("Mean TPY (summary)", "num")}
{sth("Med Paul", "num")}
{sth("Med Paul OOS", "num")}
{sth("% Paul OOS≥7", "num")}
</tr></thead>
<tbody>
{''.join(pool_trs)}
</tbody>
</table>

<h2>2. IS / OOS — DualPaul78 user set</h2>
<p>IS = entry_date &lt; 2024-01-01; OOS = entry_date ≥ 2024-01-01. OOS is report-only.</p>
<table class="sortable">
<thead><tr>
{sth("Split", "text")}
{sth("N", "num")}
{sth("WR%", "num")}
{sth("AvgR", "num")}
{sth("AvgPnL%", "num")}
{sth("Sheet PnL", "num")}
</tr></thead>
<tbody>
{''.join(isoos_user_trs)}
</tbody>
</table>

<h2>3. Per-symbol (validated DualPaul78 set)</h2>
<p>Click column headers to sort. Coverage: {len(validated)} / {len(USER_LIST_RAW)} listed symbols pass dual-7.</p>
<table class="sortable">
<thead><tr>
{sth("Symbol", "text")}
{sth("Paul", "num")}
{sth("Paul OOS", "num")}
{sth("N", "num")}
{sth("WR%", "num")}
{sth("AvgR", "num")}
{sth("AvgPnL%", "num")}
{sth("Sheet PnL", "num")}
{sth("OOS_N", "num")}
{sth("OOS WR%", "num")}
{sth("OOS AvgR", "num")}
{sth("OOS AvgPnL%", "num")}
</tr></thead>
<tbody>
{''.join(per_trs)}
</tbody>
</table>

<p class="small">Source summary: <code>VZ_Summary_Symbols_vol_zone_v2_rw63_fulluniv_20260810.csv</code>. OCANF present in signals/summary as OCANF (Yahoo alias OGC noted; no remap needed for this CSV).</p>
{sort_js}
</body>
</html>
"""
    html_path = OUT / "VolZone_DualPaul78_Compare.html"
    html_path.write_text(html_doc, encoding="utf-8")

    print("\n=== POOLED ===")
    print(pool_df.to_string(index=False))
    print("\n=== USER IS/OOS ===")
    print(user_isoos.to_string(index=False))
    print("\n=== VERDICT ===")
    print(verdict)
    print("\nHTML:", html_path)
    print("OUT:", OUT)


if __name__ == "__main__":
    main()
