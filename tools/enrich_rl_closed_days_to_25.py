#!/usr/bin/env python3
"""Enrich an existing RL_Closed CSV with DAYS_TO_25 / 25_TO_CLOSE and post-25/20/exit path metrics.

Matches house milestone rules in rocket_rl.py / portfolio_audit.awk:
  - Reach 25% = first bar where High >= entry_price * 1.25 (inclusive of entry/exit dates)
  - Reach 20% = first bar where High >= entry_price * 1.20
  - DAYS_TO_25 = days_diff(entry, touch) + 1  (same inclusive calendar span as DAYS HELD)
  - 25_TO_CLOSE = hold_days - DAYS_TO_25 if hit else 0  (= calendar days from touch→exit; 0 if same day)
  - Never hit → DAYS_TO_25 / 25_TO_CLOSE = 0 (house convention)

Post-milestone path columns (clock starts on touch bar = day 0; X = trading bars later):
  - PNL_XD_AFTER_25 / AFTER_20 = (close_at_touch+X − entry) / entry × 100
    If trade closed before touch+X, use exit price. Insufficient bars → blank.
  - MAX_GAIN_XD_AFTER_25 / AFTER_20 = (max High from touch..touch+X − entry) / entry
    Uses market highs for the full window (not capped at exit). Insufficient bars → blank.
  - Never hit threshold → all post-* columns = 0 (match DAYS_TO_* house convention)

Post-exit path columns (clock starts on exit bar = day 0; vs EXIT PRICE — left on table):
  - PNL_XD_AFTER_EXIT = (close_at_exit+X − exit) / exit × 100
  - MAX_GAIN_XD_AFTER_EXIT = (max High exit..exit+X − exit) / exit  (MAX GAIN units)
  - Insufficient bars → blank. (AFTER_25/20 unchanged: still vs entry.)

Usage:
  python tools/enrich_rl_closed_days_to_25.py path/to/RL_Closed_*.csv
  python tools/enrich_rl_closed_days_to_25.py path/to/RL_Closed_*.csv --html path/to/report.html
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "newdata" / "data"
IS_CUTOFF = "20240101"

PNL_AFTER_25_DAYS = (30, 45, 60, 90, 120)
MAX_GAIN_AFTER_25_DAYS = (30, 45, 60, 90, 120)
PNL_AFTER_20_DAYS = (30, 45, 60, 90, 120)
MAX_GAIN_AFTER_20_DAYS = (30, 45, 60, 90, 120)
PNL_AFTER_EXIT_DAYS = (30, 60, 90, 120)
MAX_GAIN_AFTER_EXIT_DAYS = (30, 60, 90, 120)

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
try:
    from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
except ImportError:
    SORTABLE_TH_CSS = ""
    SORTABLE_TABLE_SCRIPT = ""

    def sortable_th(label: str, sort: str = "text") -> str:  # type: ignore
        return f"<th>{html_mod.escape(label)}</th>"


def days_diff(d1: str, d2: str) -> int:
    """Match rocket_rl / AWK days_diff (local midnight calendar days)."""

    def _epoch(d: str) -> int:
        t = time.struct_time((int(d[:4]), int(d[4:6]), int(d[6:8]), 0, 0, 0, 0, 0, -1))
        return int(time.mktime(t))

    return int((_epoch(d2) - _epoch(d1)) / 86400)


def _iso(d: Any) -> str:
    s = str(d).strip().replace("-", "").replace("/", "")[:8]
    if len(s) == 8 and s.isdigit():
        return s
    raise ValueError(f"bad date: {d!r}")


def _load_ohlc(sym: str, cache: dict[str, pd.DataFrame | None]) -> pd.DataFrame | None:
    if sym in cache:
        return cache[sym]
    path = DATA_DIR / f"{sym}.csv"
    if not path.is_file():
        matches = list(DATA_DIR.glob(f"{sym}.csv")) + list(DATA_DIR.glob(f"{sym.lower()}.csv"))
        path = matches[0] if matches else path
    if not path.is_file():
        cache[sym] = None
        return None
    df = pd.read_csv(path)
    df["DateIso"] = df["Date"].astype(str).str.replace("-", "", regex=False).str[:8]
    df["High"] = df["High"].astype(float)
    df["Close"] = df["Close"].astype(float)
    cache[sym] = df
    return df


def first_touch_idx(
    df: pd.DataFrame, entry_iso: str, exit_iso: str, entry_px: float, mult: float
) -> int | None:
    """Return 0-based index of first High >= entry*mult within [entry, exit], else None."""
    thr = entry_px * mult
    sub = df[(df["DateIso"] >= entry_iso) & (df["DateIso"] <= exit_iso)]
    if sub.empty:
        return None
    hit = sub[sub["High"] >= thr]
    if hit.empty:
        return None
    return int(hit.index[0])


def compute_post_path(
    ohlc: pd.DataFrame,
    touch_i: int | None,
    exit_iso: str,
    entry_px: float,
    exit_px: float,
    *,
    pnl_days: tuple[int, ...],
    max_gain_days: tuple[int, ...],
    suffix: str,
) -> dict[str, float | None]:
    """Post-milestone path metrics. None = insufficient bars (blank); never-hit → 0.0."""
    out: dict[str, float | None] = {}
    for d in pnl_days:
        out[f"PNL_{d}D_AFTER_{suffix}"] = 0.0
    for d in max_gain_days:
        out[f"MAX_GAIN_{d}D_AFTER_{suffix}"] = 0.0
    if touch_i is None:
        return out

    n = len(ohlc)
    exit_rows = ohlc.index[ohlc["DateIso"] == exit_iso].tolist()
    exit_i = int(exit_rows[0]) if exit_rows else touch_i

    highs = ohlc["High"].to_numpy()
    closes = ohlc["Close"].to_numpy()

    for d in pnl_days:
        tgt = touch_i + d
        if tgt >= n:
            out[f"PNL_{d}D_AFTER_{suffix}"] = None
            continue
        px = exit_px if exit_i < tgt else float(closes[tgt])
        out[f"PNL_{d}D_AFTER_{suffix}"] = (px - entry_px) / entry_px * 100.0 if entry_px > 0 else 0.0

    for d in max_gain_days:
        tgt = touch_i + d
        if tgt >= n:
            out[f"MAX_GAIN_{d}D_AFTER_{suffix}"] = None
            continue
        mx = float(highs[touch_i : tgt + 1].max())
        out[f"MAX_GAIN_{d}D_AFTER_{suffix}"] = (mx - entry_px) / entry_px if entry_px > 0 else 0.0

    return out


def compute_post_exit_path(
    ohlc: pd.DataFrame,
    exit_iso: str,
    exit_px: float,
    *,
    pnl_days: tuple[int, ...] = PNL_AFTER_EXIT_DAYS,
    max_gain_days: tuple[int, ...] = MAX_GAIN_AFTER_EXIT_DAYS,
) -> dict[str, float | None]:
    """Post-exit path vs EXIT PRICE. None = insufficient bars (blank)."""
    out: dict[str, float | None] = {}
    for d in pnl_days:
        out[f"PNL_{d}D_AFTER_EXIT"] = None
    for d in max_gain_days:
        out[f"MAX_GAIN_{d}D_AFTER_EXIT"] = None

    exit_rows = ohlc.index[ohlc["DateIso"] == exit_iso].tolist()
    if not exit_rows or exit_px <= 0:
        return out
    exit_i = int(exit_rows[0])
    n = len(ohlc)
    highs = ohlc["High"].to_numpy()
    closes = ohlc["Close"].to_numpy()

    for d in pnl_days:
        tgt = exit_i + d
        if tgt >= n:
            continue
        px = float(closes[tgt])
        out[f"PNL_{d}D_AFTER_EXIT"] = (px - exit_px) / exit_px * 100.0

    for d in max_gain_days:
        tgt = exit_i + d
        if tgt >= n:
            continue
        mx = float(highs[exit_i : tgt + 1].max())
        out[f"MAX_GAIN_{d}D_AFTER_EXIT"] = (mx - exit_px) / exit_px

    return out


def _insert_cols_after(df: pd.DataFrame, after: str, pairs: list[tuple[str, list[Any]]]) -> pd.DataFrame:
    """Insert or overwrite named columns; place new ones after `after` if missing."""
    out = df.copy()
    for name, vals in pairs:
        out[name] = vals
    cols = [c for c in out.columns if c not in {n for n, _ in pairs}]
    if after in cols:
        i = cols.index(after) + 1
    else:
        i = len(cols)
    for name, _ in pairs:
        cols.insert(i, name)
        i += 1
    return out[cols]


def _post_col_names() -> list[str]:
    names: list[str] = []
    for d in PNL_AFTER_25_DAYS:
        names.append(f"PNL_{d}D_AFTER_25")
    for d in MAX_GAIN_AFTER_25_DAYS:
        names.append(f"MAX_GAIN_{d}D_AFTER_25")
    for d in PNL_AFTER_20_DAYS:
        names.append(f"PNL_{d}D_AFTER_20")
    for d in MAX_GAIN_AFTER_20_DAYS:
        names.append(f"MAX_GAIN_{d}D_AFTER_20")
    for d in PNL_AFTER_EXIT_DAYS:
        names.append(f"PNL_{d}D_AFTER_EXIT")
    for d in MAX_GAIN_AFTER_EXIT_DAYS:
        names.append(f"MAX_GAIN_{d}D_AFTER_EXIT")
    return names


def _exit_col_names() -> list[str]:
    names: list[str] = []
    for d in PNL_AFTER_EXIT_DAYS:
        names.append(f"PNL_{d}D_AFTER_EXIT")
    for d in MAX_GAIN_AFTER_EXIT_DAYS:
        names.append(f"MAX_GAIN_{d}D_AFTER_EXIT")
    return names


def enrich(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache: dict[str, pd.DataFrame | None] = {}
    days_to: list[int] = []
    days_after: list[int] = []
    post_cols: dict[str, list[Any]] = {k: [] for k in _post_col_names()}
    missing_ohlc = 0
    exit_blank_n = 0

    for _, row in df.iterrows():
        sym = str(row["SYMBOL"]).strip().upper()
        entry_iso = _iso(row["DATE OPENED"])
        exit_iso = _iso(row["DATE CLOSED"])
        entry_px = float(row["ENTRY PRICE"])
        exit_px = float(row["EXIT PRICE"])
        hold = int(float(row["DAYS HELD"]))
        ohlc = _load_ohlc(sym, cache)
        if ohlc is None:
            missing_ohlc += 1
            days_to.append(0)
            days_after.append(0)
            for k in post_cols:
                # AFTER_EXIT → blank when no OHLC; milestone post-* → 0 (house never-hit)
                post_cols[k].append(None if k.endswith("_AFTER_EXIT") else 0.0)
            exit_blank_n += 1
            continue

        touch25 = first_touch_idx(ohlc, entry_iso, exit_iso, entry_px, 1.25)
        touch20 = first_touch_idx(ohlc, entry_iso, exit_iso, entry_px, 1.20)
        if touch25 is None:
            days_to.append(0)
            days_after.append(0)
        else:
            touch_iso = str(ohlc.loc[touch25, "DateIso"])
            d25 = days_diff(entry_iso, touch_iso) + 1
            days_to.append(d25)
            days_after.append(max(0, hold - d25) if d25 > 0 else 0)

        post = {}
        post.update(
            compute_post_path(
                ohlc,
                touch25,
                exit_iso,
                entry_px,
                exit_px,
                pnl_days=PNL_AFTER_25_DAYS,
                max_gain_days=MAX_GAIN_AFTER_25_DAYS,
                suffix="25",
            )
        )
        post.update(
            compute_post_path(
                ohlc,
                touch20,
                exit_iso,
                entry_px,
                exit_px,
                pnl_days=PNL_AFTER_20_DAYS,
                max_gain_days=MAX_GAIN_AFTER_20_DAYS,
                suffix="20",
            )
        )
        post.update(compute_post_exit_path(ohlc, exit_iso, exit_px))
        if post.get("PNL_30D_AFTER_EXIT") is None:
            exit_blank_n += 1
        for k in post_cols:
            post_cols[k].append(post[k])

    out = df.copy()
    if "DAYS_TO_25" in out.columns:
        out["DAYS_TO_25"] = days_to
        out["25_TO_CLOSE"] = days_after
    else:
        cols = list(out.columns)
        i20 = cols.index("DAYS_TO_20") + 1 if "DAYS_TO_20" in cols else len(cols)
        out.insert(i20, "DAYS_TO_25", days_to)
        out["25_TO_CLOSE"] = days_after
        cols = [c for c in out.columns if c != "25_TO_CLOSE"]
        i20c = cols.index("20_TO_CLOSE") + 1 if "20_TO_CLOSE" in cols else len(cols)
        cols.insert(i20c, "25_TO_CLOSE")
        out = out[cols]

    after_anchor = "60_TO_CLOSE" if "60_TO_CLOSE" in out.columns else "25_TO_CLOSE"
    # Place AFTER_25/20 first (existing), then AFTER_EXIT after last AFTER_20 max-gain col
    milestone_names = [k for k in _post_col_names() if not k.endswith("_AFTER_EXIT")]
    exit_names = _exit_col_names()
    pairs = [(k, post_cols[k]) for k in milestone_names]
    out = _insert_cols_after(out, after_anchor, pairs)
    exit_anchor = (
        "MAX_GAIN_120D_AFTER_20"
        if "MAX_GAIN_120D_AFTER_20" in out.columns
        else milestone_names[-1] if milestone_names else after_anchor
    )
    out = _insert_cols_after(out, exit_anchor, [(k, post_cols[k]) for k in exit_names])

    meta = {
        "n": len(out),
        "missing_ohlc": missing_ohlc,
        "exit_blank_n_30": exit_blank_n,
        "hit_n": sum(1 for x in days_to if x > 0),
        "hit20_n": 0,
    }
    if "DAYS_TO_20" in out.columns:
        meta["hit20_n"] = int((out["DAYS_TO_20"].astype(float) > 0).sum())
    return out, meta


def _median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def _finite_nums(series: pd.Series) -> list[float]:
    out: list[float] = []
    for v in series.tolist():
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        s = str(v).strip()
        if s == "" or s.lower() in {"nan", "none", "na"}:
            continue
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def _post_medians(hit_df: pd.DataFrame, suffix: str, days: tuple[int, ...]) -> dict[str, float | None]:
    post: dict[str, float | None] = {}
    for d in days:
        pnl_col = f"PNL_{d}D_AFTER_{suffix}"
        mx_col = f"MAX_GAIN_{d}D_AFTER_{suffix}"
        pnl_vals = _finite_nums(hit_df[pnl_col]) if pnl_col in hit_df.columns else []
        mx_vals = _finite_nums(hit_df[mx_col]) if mx_col in hit_df.columns else []
        post[f"med_pnl_{suffix}_{d}"] = _median(pnl_vals)
        post[f"med_max_{suffix}_{d}"] = _median(mx_vals)
        post[f"n_pnl_{suffix}_{d}"] = len(pnl_vals)
        post[f"n_max_{suffix}_{d}"] = len(mx_vals)
    return post


def _exit_medians(df: pd.DataFrame) -> dict[str, float | None]:
    """Medians over all trades with non-blank post-exit values (full book opportunity cost)."""
    return _post_medians(df, "EXIT", PNL_AFTER_EXIT_DAYS)


def split_stats(df: pd.DataFrame, label: str) -> dict[str, Any]:
    d25 = [int(x) for x in df["DAYS_TO_25"].tolist()]
    after = [int(x) for x in df["25_TO_CLOSE"].tolist()]
    hit_mask = [x > 0 for x in d25]
    hit_n = sum(hit_mask)
    n = len(df)
    to_hit = [d25[i] for i, h in enumerate(hit_mask) if h]
    after_hit = [after[i] for i, h in enumerate(hit_mask) if h]
    p25 = p75 = None
    if len(to_hit) >= 4:
        qs = statistics.quantiles(to_hit, n=4)
        p25, p75 = float(qs[0]), float(qs[2])
    else:
        p25 = p75 = _median(to_hit)

    hit25_df = df.iloc[[i for i, h in enumerate(hit_mask) if h]]
    if "DAYS_TO_20" in df.columns:
        hit20_mask = [float(x) > 0 for x in df["DAYS_TO_20"].tolist()]
    else:
        hit20_mask = []
        for _, row in df.iterrows():
            mx = row.get("MAX_GAIN_30D_AFTER_20", 0)
            try:
                hit20_mask.append(float(mx) > 0 if mx is not None and str(mx).strip() != "" else False)
            except (TypeError, ValueError):
                hit20_mask.append(False)
    hit20_n = sum(hit20_mask)
    hit20_df = df.iloc[[i for i, h in enumerate(hit20_mask) if h]]

    post = {}
    post.update(_post_medians(hit25_df, "25", (30, 45, 60, 90, 120)))
    post.update(_post_medians(hit20_df, "20", (30, 45, 60, 90, 120)))
    post.update(_exit_medians(df))

    return {
        "label": label,
        "n": n,
        "hit_n": hit_n,
        "hit20_n": hit20_n,
        "hit_pct": (100.0 * hit_n / n) if n else 0.0,
        "hit20_pct": (100.0 * hit20_n / n) if n else 0.0,
        "med_days_to_25": _median(to_hit),
        "med_days_after": _median(after_hit),
        "p25_to": p25,
        "p75_to": p75,
        **post,
    }


def write_html(path: Path, closed_path: Path, rows: list[dict[str, Any]], notes: str) -> None:
    def fmt_med(v: float | None, places: int = 1) -> str:
        return "—" if v is None else f"{v:.{places}f}"

    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(r['label'])}</td>"
            f"<td>{r['n']}</td>"
            f"<td>{r['hit_n']}</td>"
            f"<td>{r['hit_pct']:.1f}%</td>"
            f"<td>{r.get('hit20_n', 0)}</td>"
            f"<td>{r.get('hit20_pct', 0):.1f}%</td>"
            f"<td>{fmt_med(r['med_days_to_25'])}</td>"
            f"<td>{fmt_med(r['med_days_after'])}</td>"
            f"<td>{fmt_med(r.get('p25_to'))}</td>"
            f"<td>{fmt_med(r.get('p75_to'))}</td>"
            "</tr>"
        )

    def post_table(suffix: str, hit_key: str, days: tuple[int, ...], title: str, blurb: str) -> str:
        post_rows = []
        for r in rows:
            cells = [
                f"<td>{html_mod.escape(r['label'])}</td>",
                f"<td>{r.get(hit_key, r['n'])}</td>",
            ]
            for d in days:
                cells.append(f"<td>{fmt_med(r.get(f'med_pnl_{suffix}_{d}'), 2)}</td>")
                cells.append(f"<td>{fmt_med(r.get(f'med_max_{suffix}_{d}'), 2)}</td>")
                cells.append(f"<td>{r.get(f'n_pnl_{suffix}_{d}', 0)}</td>")
            post_rows.append("<tr>" + "".join(cells) + "</tr>")
        ths = [
            sortable_th("Book", "text"),
            sortable_th("N" if suffix == "EXIT" else f"Hit {suffix}% N", "num"),
        ]
        for d in days:
            ths.append(sortable_th(f"Med PNL {d}d", "num"))
            ths.append(sortable_th(f"Med MaxGain {d}d", "num"))
            ths.append(sortable_th(f"N PNL {d}d", "num"))
        return f"""<h2>{html_mod.escape(title)}</h2>
<p class="muted">{html_mod.escape(blurb)} Click headers to sort.</p>
<table class="sortable">
<thead><tr>
{''.join(ths)}
</tr></thead>
<tbody>
{''.join(post_rows)}
</tbody></table>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>RL Closed post-25 / post-20 / post-exit — th113_vol</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;max-width:1400px;color:#1a1a1a}}
h1{{font-size:1.25rem}} h2{{font-size:1.1rem;margin-top:1.75rem}}
.muted{{color:#555;font-size:0.9rem}}
table.sortable{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:0.85rem}}
th,td{{border:1px solid #ccc;padding:0.35rem 0.45rem;text-align:left}}
th{{background:#f3f3f3}}
{SORTABLE_TH_CSS}
code{{font-size:0.85em}}
pre{{background:#f7f7f7;padding:0.75rem;overflow:auto;font-size:0.85rem}}
</style></head><body>
<h1>RL Closed — days to / after 25% + post-25 / post-20 / post-exit path</h1>
<p class="muted">Source: <code>{html_mod.escape(str(closed_path))}</code>. Research-only. Click column headers to sort.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Book", "text")}
{sortable_th("N", "num")}
{sortable_th("Hit 25% N", "num")}
{sortable_th("Hit 25%", "num")}
{sortable_th("Hit 20% N", "num")}
{sortable_th("Hit 20%", "num")}
{sortable_th("Med days to 25%", "num")}
{sortable_th("Med days after→close", "num")}
{sortable_th("P25 days to 25%", "num")}
{sortable_th("P75 days to 25%", "num")}
</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody></table>
{post_table("25", "hit_n", (30, 45, 60, 90, 120),
            "Post-25% path (hitters only; medians)",
            "Among trades that hit 25% High. Blank horizons excluded from medians. Vs ENTRY.")}
{post_table("20", "hit20_n", (30, 45, 60, 90, 120),
            "Post-20% path (hitters only; medians)",
            "Among trades that hit 20% High. Blank horizons excluded from medians. Vs ENTRY.")}
{post_table("EXIT", "n", (30, 60, 90, 120),
            "Post-exit path (all trades; medians) — vs EXIT PRICE",
            "Opportunity cost after flat. Clock = exit bar day 0. Blank horizons excluded. Vs EXIT (not entry).")}
<h2>Definitions (freeze)</h2>
<pre>{html_mod.escape(notes)}</pre>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


NOTES = """Column names (house style, aligned with DAYS_TO_10..60):
  DAYS_TO_25   — calendar days from DATE OPENED to first High >= entry*1.25, inclusive
                 (= days_diff(entry, touch) + 1). Same convention as DAYS HELD / DAYS_TO_20.
  25_TO_CLOSE  — hold_days - DAYS_TO_25 when hit; else 0.
                 Equals calendar days from first 25% touch date to DATE CLOSED (not +1).
                 Same-day touch+exit → 0.

Reach rule: High (not Close) on any bar with entry_iso <= bar <= exit_iso.
Never reached 25%: DAYS_TO_25 / 25_TO_CLOSE = 0 (house milestone convention; not blank).

Post-25 path (clock starts on touch bar = trading-day 0; vs ENTRY):
  PNL_30D/45D/60D/90D/120D_AFTER_25
    — (close at touch+X − entry) / entry × 100 (price PnL%, not cash book PNL %).
    — If trade already closed before touch+X, use EXIT PRICE.
    — Not enough bars after touch → blank/NA.
  MAX_GAIN_30D/45D/60D/90D/120D_AFTER_25
    — max High from touch through touch+X, as (maxH−entry)/entry (same units as MAX GAIN).
    — Market highs for the full window (not capped at exit).
    — Not enough bars after touch → blank/NA.
  Never hit 25%: all post-25 columns = 0 (match DAYS_TO_25 convention).

Post-20 path (same rules; touch = first High >= entry*1.20; vs ENTRY):
  PNL_30D/45D/60D/90D/120D_AFTER_20
  MAX_GAIN_30D/45D/60D/90D/120D_AFTER_20
  Never hit 20%: all post-20 columns = 0.

Post-exit path (clock starts on exit bar = trading-day 0; vs EXIT PRICE — left on table):
  PNL_30D/60D/90D/120D_AFTER_EXIT
    — (close at exit+X − exit) / exit × 100.
    — Already flat: no exit-price cap; market close at exit+X.
  MAX_GAIN_30D/60D/90D/120D_AFTER_EXIT
    — (max High from exit through exit+X − exit) / exit (MAX GAIN units).
  Not enough bars after exit → blank/NA.
  Note: AFTER_EXIT is intentionally vs EXIT (opportunity cost). AFTER_25/AFTER_20 stay vs ENTRY.

Future RL Closed: rocket_rl.py emits these columns on new runs; stamp files OHLC-enriched.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("closed_csv", type=Path)
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--notes", type=Path, default=None)
    args = ap.parse_args()
    closed = args.closed_csv
    if not closed.is_file():
        print(f"missing: {closed}", file=sys.stderr)
        return 1

    df = pd.read_csv(closed)
    out, meta = enrich(df)
    out.to_csv(closed, index=False)
    print(
        f"wrote {closed}  N={meta['n']} hit25={meta['hit_n']} "
        f"hit20={meta.get('hit20_n')} missing_ohlc={meta['missing_ohlc']} "
        f"exit_blank_30~{meta.get('exit_blank_n_30')}"
    )

    entry = out["DATE OPENED"].astype(str).str.replace("-", "", regex=False).str[:8]
    full = split_stats(out, "Full book")
    is_df = out[entry < IS_CUTOFF]
    oos_df = out[entry >= IS_CUTOFF]
    rows = [full, split_stats(is_df, "IS (entry < 2024-01-01)"), split_stats(oos_df, "OOS (entry >= 2024-01-01)")]

    notes_path = args.notes or closed.with_name("DAYS_TO_25_NOTES.md")
    notes_path.write_text(
        "# DAYS_TO_25 / 25_TO_CLOSE / post-25 + post-20 + post-exit path\n\n```\n" + NOTES + "\n```\n",
        encoding="utf-8",
    )
    print(f"wrote {notes_path}")

    html_path = args.html or closed.with_name("th113_vol_days_to_25_summary.html")
    write_html(html_path, closed, rows, NOTES)
    print(f"wrote {html_path}")

    for r in rows:
        print(
            f"{r['label']}: N={r['n']} hit25={r['hit_n']} ({r['hit_pct']:.1f}%) "
            f"hit20={r.get('hit20_n')} ({r.get('hit20_pct', 0):.1f}%) "
            f"med_to={r['med_days_to_25']} med_after={r['med_days_after']} | "
            f"med_pnl25_30/60={r.get('med_pnl_25_30')}/{r.get('med_pnl_25_60')} | "
            f"med_pnlEXIT_30/60/90/120={r.get('med_pnl_EXIT_30')}/{r.get('med_pnl_EXIT_60')}/"
            f"{r.get('med_pnl_EXIT_90')}/{r.get('med_pnl_EXIT_120')} "
            f"med_maxEXIT_30/60={r.get('med_max_EXIT_30')}/{r.get('med_max_EXIT_60')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
