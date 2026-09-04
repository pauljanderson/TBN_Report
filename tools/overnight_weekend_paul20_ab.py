#!/usr/bin/env python3
"""Overnight / weekend session-timing A/B on PaulTwenty (research only).

Daily OHLC only (no intraday). Reconstructs adjusted open from Adj Close so
close→open gaps are not wrecked by splits.

Primary one-knob (Part A): equal-weight close-to-close (control) vs overnight
close→open only (candidate). Intraday open→close is a foil, not for KEEP.

Secondary (Part B, separate hypothesis): weekend gap (Fri close→Mon open) arms.

Usage:
  python tools/overnight_weekend_paul20_ab.py
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    sharpe_from_equity_values,
)

try:
    from compare_format import calmar_ratio  # noqa: E402
except Exception:  # pragma: no cover
    calmar_ratio = None  # type: ignore

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "overnight_weekend_paul20_20260830"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
IS_CUT = date(2024, 1, 1)
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
# Round-trip cost charged when an arm is "in market" that day (bps of notional).
# Primary freeze is 0; HTML also prints a 5 bps sensitivity row set.
COST_BPS_PRIMARY = 0.0
COST_BPS_SENS = 5.0
MIN_PRICE = 5.0
START_FLOOR = date(2010, 1, 1)

SORT_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\d{4})-(\d{2})-(\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      var aMissing = (typeof av === "number" && !Number.isFinite(av)) || av === "";
      var bMissing = (typeof bv === "number" && !Number.isFinite(bv)) || bv === "";
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table) {
    var ths = table.querySelectorAll("thead th.sortable-th");
    ths.forEach(function (th, idx) {
      th.addEventListener("click", function () {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      });
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); th.click(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def load_universe(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.append(s.split(",")[0].strip())
    return out


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower().strip(): c for c in df.columns}
    need = ("date", "open", "high", "low", "close", "volume")
    if not all(k in cols for k in need):
        return None
    adj_col = cols.get("adj close") or cols.get("adj_close")
    close = df[cols["close"]].astype(float)
    adj = df[adj_col].astype(float) if adj_col else close.copy()
    # Avoid div0 / bad rows
    ratio = np.where(close.to_numpy() > 0, adj.to_numpy() / close.to_numpy(), np.nan)
    open_raw = df[cols["open"]].astype(float).to_numpy()
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]]).dt.date,
            "Open": open_raw,
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": close,
            "AdjClose": adj,
            "AdjOpen": open_raw * ratio,
            "Volume": df[cols["volume"]].astype(float),
        }
    )
    out = out.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
    out = out[out["Date"] >= START_FLOOR].reset_index(drop=True)
    return out


def session_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per-bar session returns (long-only decompositions)."""
    out = df.copy()
    ao = out["AdjOpen"].to_numpy(dtype=float)
    ac = out["AdjClose"].to_numpy(dtype=float)
    prev_ac = np.roll(ac, 1)
    prev_ac[0] = np.nan
    # Prior session close for Fri-up check on Monday
    prev2_ac = np.roll(ac, 2)
    prev2_ac[:2] = np.nan

    ctc = ac / prev_ac - 1.0
    overnight = ao / prev_ac - 1.0
    intraday = np.where(ao > 0, ac / ao - 1.0, np.nan)

    # Sanity: drop absurd gaps (likely bad adj / halt) > 40%
    for arr in (ctc, overnight, intraday):
        bad = np.abs(arr) > 0.40
        arr[bad] = np.nan

    dates = pd.to_datetime(out["Date"])
    dow = dates.dt.weekday.to_numpy()  # Mon=0
    is_mon = dow == 0
    # Friday up: Friday close > Thursday close → on Monday, prev_ac > prev2_ac
    fri_up = prev_ac > prev2_ac

    out["ret_ctc"] = ctc
    out["ret_overnight"] = overnight
    out["ret_intraday"] = intraday
    out["is_monday"] = is_mon
    out["weekend_gap"] = np.where(is_mon, overnight, np.nan)
    out["weekend_if_up"] = np.where(is_mon & fri_up, overnight, np.where(is_mon, 0.0, np.nan))
    # Weekday CTC excluding weekend gap: Monday uses intraday only; else CTC
    out["ret_no_weekend"] = np.where(is_mon, intraday, ctc)
    out["px_ok"] = (out["Close"] >= MIN_PRICE) & np.isfinite(out["AdjClose"])
    return out


def build_panel(syms: list[str]) -> tuple[pd.DataFrame, list[str], list[str]]:
    frames = []
    loaded, missing = [], []
    for sym in syms:
        df = load_ohlc(sym)
        if df is None or len(df) < 60:
            missing.append(sym)
            continue
        s = session_frame(df)
        s["symbol"] = sym
        frames.append(s)
        loaded.append(sym)
    if not frames:
        raise SystemExit("No PaulTwenty symbols loaded")
    panel = pd.concat(frames, ignore_index=True)
    return panel, loaded, missing


def arm_daily_returns(
    panel: pd.DataFrame,
    arm: str,
    *,
    cost_bps: float,
) -> pd.DataFrame:
    """Equal-weight cross-section mean of arm returns per calendar day."""
    col_map = {
        "ctc": "ret_ctc",
        "overnight": "ret_overnight",
        "intraday": "ret_intraday",
        "weekend_only": "weekend_gap",
        "weekend_if_up": "weekend_if_up",
        "no_weekend": "ret_no_weekend",
    }
    col = col_map[arm]
    sub = panel.loc[panel["px_ok"], ["Date", "symbol", col]].copy()
    sub = sub.rename(columns={col: "ret"})
    # Arms that are "out of market" most days: weekend_* use 0 on non-event days
    if arm == "weekend_only":
        # Only Mondays contribute; other weekdays flat 0 (cash)
        # Build full calendar from panel dates
        all_days = sorted(panel["Date"].unique())
        mon = sub[sub["ret"].notna()].groupby("Date")["ret"].mean()
        rets = pd.Series(0.0, index=pd.Index(all_days, name="Date"), dtype=float)
        rets.loc[mon.index] = mon
        invested = rets.index.isin(mon.index)
    elif arm == "weekend_if_up":
        # Mondays always "decision"; return may be 0 if Fri not up
        all_days = sorted(panel["Date"].unique())
        # weekend_if_up is NaN non-Monday; 0 or overnight on Monday
        mon = sub[sub["ret"].notna()].groupby("Date")["ret"].mean()
        rets = pd.Series(0.0, index=pd.Index(all_days, name="Date"), dtype=float)
        rets.loc[mon.index] = mon
        invested = rets.index.isin(mon.index)
    else:
        g = sub[sub["ret"].notna()].groupby("Date")["ret"].agg(["mean", "count"])
        g = g[g["count"] >= 1]
        rets = g["mean"]
        invested = np.ones(len(rets), dtype=bool)

    cost = (cost_bps / 10000.0) if cost_bps else 0.0
    # Charge cost on invested days (proxy for being in the session sleeve)
    net = rets.copy()
    if cost and arm in ("ctc", "overnight", "intraday", "no_weekend"):
        net = net - cost
    elif cost and arm in ("weekend_only", "weekend_if_up"):
        net = net.where(~invested, net - cost)

    out = pd.DataFrame({"Date": net.index, "ret": net.to_numpy(dtype=float)})
    out["arm"] = arm
    out["n_names"] = (
        sub[sub["ret"].notna()].groupby("Date")["symbol"].nunique().reindex(net.index).fillna(0).astype(int).to_numpy()
        if arm not in ("weekend_only", "weekend_if_up")
        else sub[sub["ret"].notna()].groupby("Date")["symbol"].nunique().reindex(net.index).fillna(0).astype(int).to_numpy()
    )
    return out.sort_values("Date").reset_index(drop=True)


def equity_metrics(daily: pd.DataFrame, *, label: str, split: str) -> dict[str, Any]:
    d = daily.copy()
    if split == "IS":
        d = d[d["Date"] < IS_CUT]
    elif split == "OOS":
        d = d[d["Date"] >= IS_CUT]
    d = d[np.isfinite(d["ret"])].sort_values("Date")
    n = len(d)
    if n < 5:
        return {
            "arm": label,
            "split": split,
            "n_days": n,
            "ann_ror": float("nan"),
            "max_dd": float("nan"),
            "calmar": float("nan"),
            "sharpe": float("nan"),
            "avg_ret_bps": float("nan"),
            "win_pct": float("nan"),
            "final_equity": float("nan"),
            "total_ret_pct": float("nan"),
            "avg_names": float("nan"),
        }
    rets = d["ret"].to_numpy(dtype=float)
    eq = INIT_ACCT * np.cumprod(1.0 + rets)
    # prepend start
    eq_full = np.concatenate([[INIT_ACCT], eq])
    peak = np.maximum.accumulate(eq_full)
    dd = (peak - eq_full) / np.where(peak > 0, peak, np.nan)
    max_dd = float(np.nanmax(dd) * 100.0)
    years = n / 252.0
    final = float(eq[-1])
    total_ret = final / INIT_ACCT - 1.0
    ann = (1.0 + total_ret) ** (1.0 / years) - 1.0 if years > 0 and (1.0 + total_ret) > 0 else float("nan")
    sharpe = None
    if sharpe_from_equity_values is not None:
        sharpe = sharpe_from_equity_values(eq_full.tolist())
    if sharpe is None or (isinstance(sharpe, float) and not math.isfinite(sharpe)):
        mu, sd = float(np.mean(rets)), float(np.std(rets, ddof=1))
        sharpe = (mu / sd * math.sqrt(252.0)) if sd > 1e-12 else float("nan")
    cal = None
    if calmar_ratio is not None and math.isfinite(ann) and math.isfinite(max_dd) and max_dd > 1e-9:
        cal = calmar_ratio(ann * 100.0, max_dd)
    elif math.isfinite(ann) and max_dd > 1e-9:
        cal = (ann * 100.0) / max_dd
    win_pct = float(np.mean(rets > 0) * 100.0)
    return {
        "arm": label,
        "split": split,
        "n_days": int(n),
        "ann_ror": float(ann * 100.0) if math.isfinite(ann) else float("nan"),
        "max_dd": max_dd,
        "calmar": float(cal) if cal is not None and math.isfinite(cal) else float("nan"),
        "sharpe": float(sharpe) if sharpe is not None and math.isfinite(float(sharpe)) else float("nan"),
        "avg_ret_bps": float(np.mean(rets) * 10000.0),
        "win_pct": win_pct,
        "final_equity": final,
        "total_ret_pct": float(total_ret * 100.0),
        "avg_names": float(d["n_names"].mean()) if "n_names" in d.columns else float("nan"),
    }


def per_symbol_stats(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym, g in panel.groupby("symbol"):
        g = g[g["px_ok"]].copy()
        is_mask = g["Date"] < IS_CUT
        for split, mask in (("FULL", slice(None)), ("IS", is_mask), ("OOS", ~is_mask)):
            if isinstance(mask, slice):
                s = g
            else:
                s = g.loc[mask]
            if len(s) < 20:
                continue
            on = s["ret_overnight"].dropna()
            intra = s["ret_intraday"].dropna()
            ctc = s["ret_ctc"].dropna()
            wg = s["weekend_gap"].dropna()
            rows.append(
                {
                    "symbol": sym,
                    "split": split,
                    "n": len(s),
                    "mean_overnight_bps": float(on.mean() * 10000) if len(on) else float("nan"),
                    "mean_intraday_bps": float(intra.mean() * 10000) if len(intra) else float("nan"),
                    "mean_ctc_bps": float(ctc.mean() * 10000) if len(ctc) else float("nan"),
                    "mean_weekend_gap_bps": float(wg.mean() * 10000) if len(wg) else float("nan"),
                    "overnight_minus_intraday_bps": (
                        float(on.mean() * 10000 - intra.mean() * 10000)
                        if len(on) and len(intra)
                        else float("nan")
                    ),
                }
            )
    return pd.DataFrame(rows)


def fmt_num(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):.{nd}f}"


def delta(a: float, b: float) -> float:
    if not (math.isfinite(a) and math.isfinite(b)):
        return float("nan")
    return a - b


def verdict_part_a(is_rows: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """KEEP/HOLD/DISMISS on IS quality: overnight vs ctc. OOS not used for pick."""
    c = is_rows.get("ctc")
    o = is_rows.get("overnight")
    if not c or not o:
        return "HOLD", "Missing IS metrics."
    # Quality: prefer higher Sharpe + Calmar, not worse Max DD by a lot, Ann ROR not collapsed
    sharpe_lift = delta(o["sharpe"], c["sharpe"])
    cal_lift = delta(o["calmar"], c["calmar"])
    ann_lift = delta(o["ann_ror"], c["ann_ror"])
    dd_delta = delta(o["max_dd"], c["max_dd"])  # lower better; positive = worse DD

    notes = (
        f"IS overnight vs ctc: ΔSharpe={fmt_num(sharpe_lift, 2)}, "
        f"ΔCalmar={fmt_num(cal_lift, 2)}, ΔAnnROR={fmt_num(ann_lift, 1)}pp, "
        f"ΔMaxDD={fmt_num(dd_delta, 1)}pp (positive ΔMaxDD = worse)."
    )
    # Simple rule: need Sharpe and Calmar both up, Max DD not worse by >2pp, Ann ROR not down >3pp
    if (
        math.isfinite(sharpe_lift)
        and math.isfinite(cal_lift)
        and sharpe_lift > 0.05
        and cal_lift > 0.05
        and (not math.isfinite(dd_delta) or dd_delta <= 2.0)
        and (not math.isfinite(ann_lift) or ann_lift >= -3.0)
    ):
        return "LEAN KEEP", notes + " Quality lift on IS without large DD/ROR damage — research-only; OOS report-only."
    if (
        math.isfinite(sharpe_lift)
        and math.isfinite(cal_lift)
        and sharpe_lift < -0.05
        and cal_lift < -0.05
    ):
        return "DISMISS", notes + " Overnight worse on both Sharpe and Calmar in IS."
    return "HOLD", notes + " Mixed / flat — do not adopt; do not retune on OOS."


def write_baseline(loaded: list[str], missing: list[str]) -> None:
    text = f"""# BASELINE — {STAMP}

## Status
Research only — not gold / not DailyRun.

## Universe
PaulTwenty (`drive/universes/PaulTwenty_universe.csv`)
Loaded ({len(loaded)}): {", ".join(loaded)}
Missing ({len(missing)}): {", ".join(missing) if missing else "—"}

## Identity (frozen)
- Long-only equal-weight daily portfolio of names with valid bars that day
- Prices: Adj Close + Adj Open (= Open × AdjClose/Close) from `data/newdata/data/{{SYM}}.csv`
- Start floor: {START_FLOOR.isoformat()}
- Min price: ${MIN_PRICE:g} (raw Close)
- Absurd session |ret| > 40% → dropped as bad bar
- Initial account (equity / Max DD): ${INIT_ACCT:,.0f}
- Primary costs: {COST_BPS_PRIMARY:g} bps per invested day (sensitivity also at {COST_BPS_SENS:g} bps)
- IS / OOS: entry/return date `< {IS_CUT.isoformat()}` vs `>= {IS_CUT.isoformat()}`

## Part A — primary one-knob (session timing)
- **Control:** `ctc` — equal-weight close→close
- **Candidate:** `overnight` — equal-weight close→open only (flat conceptually in cash during the cash session)
- **Foil (not for KEEP):** `intraday` — equal-weight open→close

Hypothesis: on PaulTwenty mega-caps, the equity premium accrues overnight; overnight-only improves risk-adjusted quality vs full-day CTC.

## Part B — secondary hypothesis (weekend)
- `no_weekend` — CTC but Mondays use open→close only (skip Fri→Mon gap)
- `weekend_only` — only Fri close→Mon open; cash other days
- `weekend_if_up` — Monday overnight only if Friday close > Thursday close (Simons-lore-ish weekend continuation filter)

Part B is a **separate** hypothesis. Do not pick Part B from Part A results.

## Selection bias
Part A foil `intraday` is context. KEEP/LEAN KEEP/DISMISS for Part A uses **IS only**. OOS is report-only — no retune.

## Not claimed
Medallion / Renaissance replication. Daily bars cannot test Friday AM→PM microstructure.
"""
    (OUT_DIR / "BASELINE.md").write_text(text, encoding="utf-8")


def write_html(
    *,
    loaded: list[str],
    missing: list[str],
    metrics: list[dict[str, Any]],
    sym_stats: pd.DataFrame,
    verdict: str,
    verdict_notes: str,
    cost_bps: float,
) -> Path:
    by = {(m["arm"], m["split"]): m for m in metrics}

    def row_cells(arm: str, split: str, ctrl: str | None = None) -> str:
        m = by.get((arm, split), {})
        cells = [
            arm,
            split,
            str(m.get("n_days", "—")),
            fmt_num(m.get("ann_ror"), 1),
            fmt_num(m.get("max_dd"), 1),
            fmt_num(m.get("calmar"), 2),
            fmt_num(m.get("sharpe"), 2),
            fmt_num(m.get("avg_ret_bps"), 2),
            fmt_num(m.get("win_pct"), 1),
            fmt_num(m.get("total_ret_pct"), 1),
            format_money(m.get("final_equity")),
            fmt_num(m.get("avg_names"), 1),
        ]
        if ctrl:
            c = by.get((ctrl, split), {})
            cells.extend(
                [
                    fmt_num(delta(m.get("ann_ror", float("nan")), c.get("ann_ror", float("nan"))), 1),
                    fmt_num(delta(m.get("max_dd", float("nan")), c.get("max_dd", float("nan"))), 1),
                    fmt_num(delta(m.get("calmar", float("nan")), c.get("calmar", float("nan"))), 2),
                    fmt_num(delta(m.get("sharpe", float("nan")), c.get("sharpe", float("nan"))), 2),
                ]
            )
        else:
            cells.extend(["—", "—", "—", "—"])
        return "<tr>" + "".join(f"<td>{html_mod.escape(str(x))}</td>" for x in cells) + "</tr>"

    part_a_arms = ["ctc", "overnight", "intraday"]
    part_b_arms = ["no_weekend", "weekend_only", "weekend_if_up"]
    splits = ["FULL", "IS", "OOS"]

    def table_for(arms: list[str], ctrl: str) -> str:
        head = (
            "<table class=\"sortable\"><thead><tr>"
            + sortable_th("Arm", "text")
            + sortable_th("Split", "text")
            + sortable_th("N days", "num")
            + sortable_th("Ann ROR %", "num")
            + sortable_th("Max DD %", "num")
            + sortable_th("Calmar", "num")
            + sortable_th("Sharpe", "num")
            + sortable_th("Avg ret bps", "num")
            + sortable_th("Win % days", "num")
            + sortable_th("Total ret %", "num")
            + sortable_th("Final equity", "num")
            + sortable_th("Avg names", "num")
            + sortable_th("ΔAnn ROR vs ctrl", "num")
            + sortable_th("ΔMax DD vs ctrl", "num")
            + sortable_th("ΔCalmar vs ctrl", "num")
            + sortable_th("ΔSharpe vs ctrl", "num")
            + "</tr></thead><tbody>"
        )
        body = []
        for split in splits:
            for arm in arms:
                body.append(row_cells(arm, split, ctrl if arm != ctrl else None))
        return head + "".join(body) + "</tbody></table>"

    # Symbol table IS only for readability
    sym_is = sym_stats[sym_stats["split"] == "IS"].sort_values("overnight_minus_intraday_bps", ascending=False)
    sym_rows = []
    for _, r in sym_is.iterrows():
        sym_rows.append(
            "<tr>"
            + "".join(
                f"<td>{html_mod.escape(fmt_num(r[c], 2) if c != 'symbol' and c != 'split' and c != 'n' else str(int(r[c]) if c == 'n' else r[c]))}</td>"
                for c in [
                    "symbol",
                    "n",
                    "mean_overnight_bps",
                    "mean_intraday_bps",
                    "mean_ctc_bps",
                    "mean_weekend_gap_bps",
                    "overnight_minus_intraday_bps",
                ]
            )
            + "</tr>"
        )

    badge = html_mod.escape(verdict)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Overnight / weekend PaulTwenty A/B — {html_mod.escape(STAMP)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.35rem;margin:0 0 .4rem}}
h2{{font-size:1.1rem;margin:1.6rem 0 .5rem}}
.meta{{color:#475569;font-size:.92rem;max-width:1000px}}
.badge{{display:inline-block;background:#fef3c7;color:#92400e;padding:.15rem .5rem;border-radius:4px;font-size:.8rem;font-weight:600}}
.verdict{{background:#ecfeff;border:1px solid #a5f3fc;padding:.85rem 1rem;border-radius:6px;max-width:1000px;margin:.8rem 0}}
.note{{background:#fff7ed;border:1px solid #fed7aa;padding:.75rem 1rem;border-radius:6px;max-width:1000px;margin:.8rem 0}}
table{{border-collapse:collapse;background:#fff;margin:.6rem 0 1rem;font-size:.84rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
th,td{{border:1px solid #e2e8f0;padding:.35rem .5rem;text-align:right}}
th{{background:#f1f5f9;text-align:left}}
td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){{text-align:left}}
{SORT_CSS}
</style>
</head>
<body>
<p class="badge">Research only — not gold / not DailyRun · Part A verdict: {badge}</p>
<h1>Overnight / weekend session timing — PaulTwenty</h1>
<p class="meta">Stamp <code>{html_mod.escape(STAMP)}</code> · Universe PaulTwenty N={len(loaded)}
({html_mod.escape(", ".join(loaded))})
· Costs {cost_bps:g} bps/invested-day · IS &lt; {IS_CUT.isoformat()} · OOS ≥ {IS_CUT.isoformat()}
· Init {format_money(INIT_ACCT)} · Click column headers to sort.</p>

<div class="verdict"><strong>Part A verdict (IS only): {html_mod.escape(verdict)}</strong><br/>
{html_mod.escape(verdict_notes)}<br/>
OOS is report-only — do not retune. Not a Renaissance / Medallion clone; daily bars only.</div>

<div class="note"><strong>Freeze:</strong> equal-weight long-only; Adj Open/Close; primary knob =
<code>overnight</code> vs control <code>ctc</code>. <code>intraday</code> is a foil.
Part B weekend arms are a <em>separate</em> hypothesis. Missing symbols: {html_mod.escape(", ".join(missing) if missing else "none")}.</div>

<h2>Part A — session timing (control <code>ctc</code>)</h2>
<p class="meta">Canonical-ish book metrics on daily equal-weight equity curve (Ann ROR, Max DD, Calmar, Sharpe). Absolute + Δ vs control.</p>
{table_for(part_a_arms, "ctc")}

<h2>Part B — weekend hypothesis (control <code>no_weekend</code>)</h2>
<p class="meta">Separate hypothesis. <code>weekend_only</code> / <code>weekend_if_up</code> are sparse (mostly cash). Compare quality carefully — low time-in-market inflates some ratios.</p>
{table_for(part_b_arms, "no_weekend")}

<h2>Per-symbol IS mean session returns (bps/day)</h2>
<p class="meta">Descriptive. Positive overnight−intraday = classic overnight-premium shape on that name.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("N bars", "num")}
{sortable_th("Mean overnight bps", "num")}
{sortable_th("Mean intraday bps", "num")}
{sortable_th("Mean CTC bps", "num")}
{sortable_th("Mean weekend gap bps", "num")}
{sortable_th("Overnight − intraday bps", "num")}
</tr></thead>
<tbody>
{''.join(sym_rows)}
</tbody>
</table>

<h2>How to read</h2>
<ul>
<li><strong>ctc</strong> — always exposed close-to-close (buy-and-hold EW).</li>
<li><strong>overnight</strong> — only close→next open; captures the academic overnight equity premium sleeve.</li>
<li><strong>intraday</strong> — only open→close (foil).</li>
<li><strong>weekend_only</strong> — Fri close→Mon open only (Simons-lore weekend hold, unconditional).</li>
<li><strong>weekend_if_up</strong> — that gap only if Friday finished up vs Thursday.</li>
<li>Daily data cannot test Friday morning→afternoon microstructure from Zuckerman.</li>
</ul>

<p class="meta">Re-run: <code>python tools/overnight_weekend_paul20_ab.py</code></p>
{SORT_JS}
</body>
</html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=Path, default=PAULTWENTY)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--cost-bps", type=float, default=COST_BPS_PRIMARY)
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    # Rebind module OUT_DIR used by writers
    globals()["OUT_DIR"] = out_dir

    univ = load_universe(args.universe)
    panel, loaded, missing = build_panel(univ)
    write_baseline(loaded, missing)

    arms = ["ctc", "overnight", "intraday", "no_weekend", "weekend_only", "weekend_if_up"]
    metrics: list[dict[str, Any]] = []
    daily_by_arm: dict[str, pd.DataFrame] = {}
    for arm in arms:
        daily = arm_daily_returns(panel, arm, cost_bps=args.cost_bps)
        daily_by_arm[arm] = daily
        daily.to_csv(OUT_DIR / f"daily_{arm}.csv", index=False)
        for split in ("FULL", "IS", "OOS"):
            metrics.append(equity_metrics(daily, label=arm, split=split))

    metrics_df = pd.DataFrame(metrics)
    metrics_df.to_csv(OUT_DIR / "metrics.csv", index=False)

    sym_stats = per_symbol_stats(panel)
    sym_stats.to_csv(OUT_DIR / "symbol_session_stats.csv", index=False)

    is_map = {m["arm"]: m for m in metrics if m["split"] == "IS"}
    verdict, notes = verdict_part_a(is_map)

    html_path = write_html(
        loaded=loaded,
        missing=missing,
        metrics=metrics,
        sym_stats=sym_stats,
        verdict=verdict,
        verdict_notes=notes,
        cost_bps=args.cost_bps,
    )

    # Short SUMMARY
    summary = [
        f"# {STAMP}",
        "",
        f"**Part A verdict (IS):** {verdict}",
        "",
        notes,
        "",
        f"HTML: `{html_path.as_posix()}`",
        f"Loaded: {', '.join(loaded)}",
        f"Costs: {args.cost_bps:g} bps/invested-day",
        "",
        "OOS report-only. Research only.",
    ]
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    print(f"[OW] stamp={STAMP} loaded={len(loaded)} missing={missing}")
    print(f"[OW] Part A verdict={verdict}")
    for arm in ("ctc", "overnight", "intraday"):
        m = is_map[arm]
        print(
            f"[OW] IS {arm}: AnnROR={m['ann_ror']:.1f}% MaxDD={m['max_dd']:.1f}% "
            f"Calmar={m['calmar']:.2f} Sharpe={m['sharpe']:.2f}"
        )
    print(f"[OW] wrote {html_path}")


if __name__ == "__main__":
    main()
