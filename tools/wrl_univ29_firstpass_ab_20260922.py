#!/usr/bin/env python3
"""WRL first-pass A/B on the frozen 29-name sleeve — 2026-09-22.

Weekly Range / Swing (WRL). Reuses ``tools/wrl_firstpass_ab_20260922.py``
(same four one-knob arms). Post-runs the parent EXIT_swing IS book
(entry_date < 2024-01-01). Research only — not gold, not DailyRun.

Universe is frozen exactly (no add/drop). Names were picked after the
full-universe IS table — in-sample selection. OOS is report-only.
"""
from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import os
import subprocess
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

PARENT_STAMP = REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922"
STAMP_DIR = REPO / "drive" / "paul_experiments" / "wrl_univ29_firstpass_ab_20260922"
POST_DIR = STAMP_DIR / "post_run_is"
UNIVERSE_CSV = PARENT_STAMP / "universe29.csv"
DATA_DIR = REPO / "data" / "newdata" / "data"
IS_CUT = date(2024, 1, 1)
IS_CLOSED_TS = "260922IS29"

ORIGINAL_REQUEST = (
    "let's run the IS through post run analysis, wire up same AB tests and execute please"
)

UNIVERSE_29: tuple[str, ...] = (
    "GEHC",
    "FTRE",
    "UBER",
    "NE",
    "FANG",
    "CARR",
    "IBP",
    "TDG",
    "DELL",
    "HWM",
    "PANW",
    "STZ",
    "LNC",
    "HCA",
    "GDDY",
    "EXLS",
    "CWK",
    "CRM",
    "PVH",
    "SHC",
    "SPG",
    "DRI",
    "FNF",
    "FN",
    "ADBE",
    "CCL",
    "UNH",
    "HGV",
    "MAR",
)
assert len(UNIVERSE_29) == 29

LAYMAN = (
    "Weekly Range / Swing (WRL) waits for a daily close in last week's lower pocket, "
    "then buys the next session if price trades back up through that week's low. "
    "Paul already froze these 29 names as the first sleeve and adopted the swing-high "
    "exit (sell the whole position at the swing high). This job does two things: "
    "(1) run the house after-action report on the in-sample trades only — the years "
    "before 2024 — so we see the same ImproveHints patterns on this sleeve, not the "
    "6 Sep full-universe firehose; (2) re-run the same four first-pass A/B tests "
    "(one setting each) on these 29 names. In-sample quality decides; out-of-sample "
    "is shown but we do not retune from it. Names were picked after seeing the "
    "full-universe in-sample table — that is selection bias, labeled as such."
)

FREEZE = (
    "`wrl_mode=true`, control `wrl_target_mode=scale` / `wrl_scale_frac=0.50`, "
    "`stop_pct=1.0` (multiplier on swing low), `wrl_min_zone_pct=0`, "
    "`wrl_time_stop_bars=0`, `symbol_reentry_cooldown_days=0`, "
    "host `$500k × 2.0 × 0.6` like `run_wrl.bat`. "
    "Parent sleeve adopted `wrl_target_mode=swing` "
    "(`drive/paul_experiments/wrl_exitswing_univ29_20260922/`, HOLD). "
    "Cooldown is still unread in the engine (`cooldown_until` never set) — "
    "EXIT_cd5 is labeled null if the book matches control; we do not invent wiring."
)


def _load_firstpass():
    path = REPO / "tools" / "wrl_firstpass_ab_20260922.py"
    spec = importlib.util.spec_from_file_location("wrl_firstpass_ab_20260922", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STAMP_DIR = STAMP_DIR
    return mod


def _load_universe() -> list[str]:
    src = UNIVERSE_CSV if UNIVERSE_CSV.is_file() else None
    out: list[str] = []
    if src:
        for line in src.read_text(encoding="utf-8").splitlines():
            t = line.strip().upper()
            if t and not t.startswith("#") and t != "SYMBOL":
                out.append(t)
    if out != list(UNIVERSE_29):
        # Frozen list wins. File is a convenience copy.
        return list(UNIVERSE_29)
    return out


def _parse_ymd(val: Any) -> Optional[date]:
    s = str(val or "").strip().replace("-", "")
    if len(s) < 8 or not s[:8].isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _latest(folder: Path, pattern: str) -> Optional[Path]:
    files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _write_universe_csv(path: Path) -> None:
    path.write_text("\n".join(UNIVERSE_29) + "\n", encoding="utf-8")


def slice_is_closed() -> Path:
    """Write IS-only Closed from parent EXIT_swing book (entry < 2024-01-01)."""
    POST_DIR.mkdir(parents=True, exist_ok=True)
    src = _latest(PARENT_STAMP / "EXIT_swing", "WRL_Closed_*.csv")
    if src is None:
        overlay = PARENT_STAMP / "WRL_Closed_overlay.csv"
        if not overlay.is_file():
            raise FileNotFoundError("parent EXIT_swing Closed / overlay missing")
        src = overlay
    dest = POST_DIR / f"WRL_Closed_{IS_CLOSED_TS}.csv"
    kept = 0
    skipped_oos = 0
    with src.open(newline="", encoding="utf-8-sig", errors="replace") as fin:
        reader = csv.DictReader(fin)
        fieldnames = [c for c in (reader.fieldnames or []) if c and c.upper() != "ARM"]
        if not fieldnames:
            raise RuntimeError(f"no columns in {src}")
        rows_out: list[dict[str, Any]] = []
        for row in reader:
            if src.name.startswith("WRL_Closed_overlay") and str(row.get("ARM") or "") != "EXIT_swing":
                continue
            opened = _parse_ymd(row.get("DATE_OPENED"))
            if opened is None:
                continue
            if opened >= IS_CUT:
                skipped_oos += 1
                continue
            rows_out.append({k: row.get(k, "") for k in fieldnames})
            kept += 1
    with dest.open("w", newline="", encoding="utf-8") as fout:
        w = csv.DictWriter(fout, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_out)
    (POST_DIR / "last_run_ts.txt").write_text(IS_CLOSED_TS + "\n", encoding="utf-8")
    (POST_DIR / "SOURCE.txt").write_text(
        f"source={src}\nfilter=DATE_OPENED < 2024-01-01\n"
        f"n_is={kept}\nn_oos_dropped={skipped_oos}\n"
        f"parent=wrl_exitswing_univ29_20260922/EXIT_swing\n",
        encoding="utf-8",
    )
    print(f"[WRL-29-1P] IS Closed {kept} rows (dropped {skipped_oos} OOS) -> {dest}", flush=True)
    return dest


def run_post_run(closed: Path) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        str(REPO / "stock_analysis" / "post_run_analysis.py"),
        "--system",
        "WRL",
        "--closed",
        str(closed),
        "--output-dir",
        str(POST_DIR),
        "--data-dir",
        str(DATA_DIR),
        "--no-charts",
        "--refresh-cheap",
    ]
    print("[WRL-29-1P] post_run:", " ".join(cmd), flush=True)
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), check=False, capture_output=False)
        if proc.returncode != 0:
            return False, f"post_run_analysis exited {proc.returncode}"
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"post_run_analysis failed: {exc}"


def _hint_rows() -> list[dict[str, str]]:
    p = _latest(POST_DIR, "WRL_ImproveHints_*.csv")
    if not p:
        return []
    with p.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


def _hint_read_sentences(hints: list[dict[str, str]]) -> str:
    if not hints:
        return (
            "ImproveHints did not write a CSV — see post_run_is/ for assessments "
            "or the failure note."
        )
    top = hints[:5]
    bits = []
    for h in top:
        hid = (h.get("HYPOTHESIS_ID") or h.get("CATEGORY") or "").strip()
        sug = (h.get("SUGGESTION") or h.get("EVIDENCE") or "").strip()
        n = (h.get("TRADE_COUNT") or "").strip()
        pct = (h.get("PCT_OF_TRADES") or "").strip()
        extra = f" ({n} trades, {pct}% of book)" if n else ""
        bits.append(f"{hid}{extra}: {sug}" if hid else sug)
    return " ".join(x.rstrip(".") + "." for x in bits if x)


def _trade_keys(rows: list[dict[str, Any]]) -> set[tuple[str, Any, Any]]:
    return {(str(r.get("symbol") or ""), r.get("opened"), r.get("closed")) for r in rows}


def _write_failure_html(path: Path, title: str, detail: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>{html.escape(title)}</title>
<style>body{{font-family:Segoe UI,sans-serif;max-width:820px;margin:32px auto;padding:0 16px;}}
.callout{{background:#fdecea;border-left:4px solid #9b2226;padding:12px 14px;}}</style></head>
<body>
<h1>{html.escape(title)}</h1>
<div class="callout"><strong>What you asked</strong>
<p>{html.escape(ORIGINAL_REQUEST)}</p></div>
<div class="callout"><strong>In plain English</strong>
<p>{html.escape(LAYMAN)}</p></div>
<p>This research stamp failed partway. Weekly Range / Swing (WRL) first-pass on the
frozen 29-name sleeve did not finish cleanly.</p>
<pre>{html.escape(detail)}</pre>
<p class="muted">Research only. Not gold. Not DailyRun.</p>
</body></html>
"""
    path.write_text(page, encoding="utf-8")
    return path


def write_reports(
    fp: Any,
    symbols: list[str],
    frames: dict[str, pd.DataFrame],
    *,
    missing: list[str],
    post_ok: bool,
    post_note: str,
    hints: list[dict[str, str]],
    cd_null: bool,
    cd_note: str,
) -> list[Path]:
    n_univ = len(frames)
    full_books: dict[str, dict[str, Any]] = {}
    is_books: dict[str, dict[str, Any]] = {}
    oos_books: dict[str, dict[str, Any]] = {}
    sums: dict[str, dict[str, Any]] = {}
    audits: dict[str, dict[str, Any]] = {}
    notes: dict[str, str] = {}

    for arm, *_rest in fp.ARMS:
        d = STAMP_DIR / arm
        rows = fp._closed_rows(d)
        cash = fp.SHEET_CASH
        aud = fp._audit_row(d)
        audits[arm] = aud
        c_aud = fp.parse_number(aud.get("brt_cash") or aud.get("sheet_brt_cash"))
        if c_aud and c_aud > 0:
            cash = float(c_aud)
        eq = fp._latest(d, "WRL_EquityCurve_*.csv")
        if eq and ("_Aggressive_" in eq.name or "_Regular_" in eq.name):
            eq = None
            for p in sorted(d.glob("WRL_EquityCurve_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
                if "_Aggressive_" not in p.name and "_Regular_" not in p.name:
                    eq = p
                    break
        full_books[arm] = fp._book_from_rows(rows, cash=cash, n_univ=n_univ, equity_curve=eq)
        is_books[arm] = fp._book_from_rows(
            fp._slice_rows(rows, "IS"),
            cash=cash,
            n_univ=n_univ,
            equity_curve=eq,
            end_date_exclusive=IS_CUT,
        )
        oos_books[arm] = fp._book_from_rows(
            fp._slice_rows(rows, "OOS"),
            cash=cash,
            n_univ=n_univ,
            equity_curve=eq,
            start_date=IS_CUT,
        )
        sums[arm] = fp._summary_aggs(d)
        notes[arm] = full_books[arm].get("note") or ""

    verdicts: dict[str, tuple[str, str]] = {}
    for arm, *_r in fp.ARMS:
        if arm == fp.CONTROL:
            continue
        if arm == "EXIT_cd5" and cd_null:
            verdicts[arm] = (
                "HOLD",
                "Null test: rocket_wrl never assigns cooldown_until, so the 5-day "
                "cooldown knob does not fire. Book matches control. Do not treat "
                "this as evidence against the post-TARGET quick-stop hint, and do "
                "not invent cooldown wiring from this stamp.",
            )
            continue
        verdicts[arm] = fp._quality_verdict(
            is_books[fp.CONTROL],
            is_books[arm],
            oos_ctrl=oos_books[fp.CONTROL],
            oos_cand=oos_books[arm],
        )

    labs = {arm: v[0] for arm, v in verdicts.items()}
    if any(v == "LEAN KEEP" for v in labs.values()):
        keepers = [a for a, v in labs.items() if v == "LEAN KEEP"]
        overall = "HOLD"
        overall_why = (
            f"IS lean-keep on {', '.join(keepers)} is research-only. "
            "Do not adopt into run_wrl.bat or DailyRun from this IS horse-race. "
            "Names were picked after the full-universe IS table — in-sample selection. "
            "Next: walk-forward or a second universe before gold."
        )
    elif any(v == "DISMISS" for v in labs.values()) and not any(v == "LEAN KEEP" for v in labs.values()):
        overall = "HOLD"
        overall_why = (
            "No arm cleared KEEP on IS quality vs control. "
            "Keep the house freeze on this sleeve; parent EXIT_swing remains HOLD. "
            "Names were picked after the full-universe IS table — in-sample selection."
        )
    else:
        overall = "HOLD"
        overall_why = (
            "HOLD — do not adopt any arm into run_wrl.bat. "
            "Judge IS quality; OOS is report-only (do not retune). "
            "Parent EXIT_swing on this 29-name sleeve was already HOLD. "
            "Names were picked after the full-universe IS table — in-sample selection. "
            "Research candidate only — not gold / not DailyRun."
        )

    _write_baseline(verdicts, overall, overall_why, is_books, oos_books, cd_null, cd_note, missing)
    _write_hypothesis(verdicts, overall, overall_why, is_books, oos_books, cd_null)

    v_html = []
    for arm, (lab, why) in verdicts.items():
        cls = "ok" if "KEEP" in lab else ("bad" if lab == "DISMISS" else "warn")
        v_html.append(
            f"<div class='callout {cls}'><strong>{html.escape(arm)} — {html.escape(lab)}.</strong> "
            f"{html.escape(why)}</div>"
        )
    ocls = "warn" if overall == "HOLD" else ("bad" if overall == "DISMISS" else "ok")

    hint_html = html.escape(_hint_read_sentences(hints))
    post_links = []
    for pat, label in (
        ("WRL_SymbolAssessments_*.html", "SymbolAssessments"),
        ("WRL_ImprovePriority_*.html", "ImprovePriority"),
        ("WRL_ImproveHints_*.html", "ImproveHints"),
    ):
        p = _latest(POST_DIR, pat)
        if p:
            rel = p.relative_to(STAMP_DIR).as_posix()
            post_links.append(f"<li><a href='{html.escape(rel)}'>{html.escape(label)}</a> — <code>{html.escape(rel)}</code></li>")
    post_ul = "<ul>" + "".join(post_links) + "</ul>" if post_links else "<p class='muted'>No post-run HTML yet.</p>"
    post_cls = "ok" if post_ok else "bad"
    post_status = "Post-run finished on the EXIT_swing IS sleeve." if post_ok else f"Post-run issue: {post_note}"

    def _card(arm: str, book: dict[str, Any]) -> str:
        return (
            f"<div class='card'><div class='k'>{html.escape(arm)} IS</div>"
            f"<div class='v'>N={book['n']}</div>"
            f"<div class='muted'>WR {book['wr']:.1f}% · Avg {book['avg_pnl_pct']:+.2f}% · "
            f"PF {book['pf']:.2f} · DD {book['max_dd']:.2f}%</div></div>"
        )

    miss_html = (
        f"<p class='muted'>Listed in the freeze but no/short local OHLC: {html.escape(', '.join(missing))} "
        "(not dropped from <code>universe29.csv</code>).</p>"
        if missing
        else ""
    )
    used = [s for s in UNIVERSE_29 if s in frames]
    cd_cls = "warn"
    empty_book = {"n": 0, "wr": 0.0, "avg_pnl_pct": 0.0, "pf": 0.0, "max_dd": 0.0}
    empty_sums = {a: {} for a in is_books}
    empty_oos = {a: {} for a in oos_books}
    empty_notes: dict[str, str] = {}
    hint_rows_html = []
    for h in hints[:8]:
        hint_rows_html.append(
            "<tr>"
            f"<td>{html.escape(h.get('PRIORITY') or '')}</td>"
            f"<td>{html.escape(h.get('HYPOTHESIS_ID') or h.get('CATEGORY') or '')}</td>"
            f"<td class='num'>{html.escape(h.get('TRADE_COUNT') or '')}</td>"
            f"<td class='num'>{html.escape(h.get('PCT_OF_TRADES') or '')}</td>"
            f"<td>{html.escape((h.get('SUGGESTION') or '')[:220])}</td>"
            "</tr>"
        )
    hints_table = ""
    if hint_rows_html:
        hints_table = f"""
<div class="table-wrap"><table class="sortable">
<caption>Top ImproveHints on the EXIT_swing IS sleeve — click headers to sort</caption>
<thead><tr>
{fp.sortable_th("P","num")}{fp.sortable_th("Hint","text")}{fp.sortable_th("Trades","num")}{fp.sortable_th("% book","num")}{fp.sortable_th("Suggestion","text")}
</tr></thead>
<tbody>{''.join(hint_rows_html)}</tbody>
</table></div>
"""

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WRL univ29 first-pass A/B — 2026-09-22</title>
<style>
  :root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
    --card:#fff; --accent:#2a4a5c; --ok:#2d6a4f; --ok-bg:#e8f2ec;
    --warn:#8a5a12; --warn-bg:#f7efe0; --bad:#9b2226; --bad-bg:#fdecea; --fill:#f0eee6; }}
  body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",Georgia,serif; font-size:15px;
    line-height:1.55; color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:1.55rem; margin:0 0 8px; }}
  h2 {{ font-size:1.12rem; margin:26px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:1.0rem; margin:18px 0 8px; }}
  .lede, .muted {{ color:var(--muted); }}
  .badge {{ display:inline-block; font-size:0.75rem; font-weight:700; padding:2px 8px; background:var(--bad-bg); color:var(--bad); }}
  .callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:12px 0; }}
  .callout.ok {{ background:var(--ok-bg); border-left-color:var(--ok); }}
  .callout.warn {{ background:var(--warn-bg); border-left-color:var(--warn); }}
  .callout.bad {{ background:var(--bad-bg); border-left-color:var(--bad); }}
  .cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:12px 0 8px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; min-width:160px; flex:1 1 160px; }}
  .card .k {{ font-size:0.75rem; color:var(--muted); font-weight:700; }}
  .card .v {{ font-size:1.15rem; font-weight:700; }}
  .table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
  thead th {{ background:var(--fill); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
  code {{ background:var(--fill); padding:0.08em 0.3em; }}
  {fp.SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <p class="muted">WRL — Weekly Range / Swing · research stamp 2026-09-22 · parent
  <code>wrl_exitswing_univ29_20260922</code> · first-pass reuse
  <code>wrl_firstpass_ab_20260922</code></p>
  <h1>WRL first-pass A/B · 29-name sleeve</h1>
  <div class="badge">Research candidate — not gold — not DailyRun</div>
  <p class="lede">Frozen 29 names · one knob at a time · IS quality · OOS report-only · in-sample selection labeled.</p>

  <div class="callout">
    <strong>What you asked</strong>
    <p>{html.escape(ORIGINAL_REQUEST)}</p>
  </div>
  <div class="callout">
    <strong>In plain English</strong>
    <p>{html.escape(LAYMAN)}</p>
  </div>

  <div class="callout warn"><strong>In-sample selection.</strong> These 29 names were picked
  after the full-universe IS table in <code>wrl_exitswing_is_universe_20260922</code>.
  A good sleeve here is not confirmation. Next promotion step is walk-forward or a
  <em>second</em> universe — not another IS pick from the same table. OOS is report-only;
  do not retune on OOS.</div>

  <h2>Post-run on EXIT_swing IS (entry &lt; 2024-01-01)</h2>
  <div class="callout {post_cls}"><strong>{html.escape(post_status)}</strong>
  <p>Outputs live under <code>post_run_is/</code> with stamp <code>{IS_CLOSED_TS}</code>
  so they do not overwrite the 6 Sep 2026 full-universe assessments.</p>
  <p>{hint_html}</p></div>
  {post_ul}
  {hints_table}

  <h2>Freeze</h2>
  <p>{html.escape(FREEZE)}</p>
  <p>Universe (Paul's order, 29, no add/drop): <code>{html.escape(','.join(used))}</code>
  ({n_univ} with OHLC). See <code>universe29.csv</code>.</p>
  {miss_html}
  <p class="muted">IS = <code>entry_date &lt; 2024-01-01</code>. OOS report-only. Same exit when testing entries and vice versa. Not the Mag10 kitchen sink.</p>

  <h2>Arms (one knob)</h2>
  <div class="table-wrap"><table class="sortable">
  <caption>Click column headers to sort</caption>
  <thead><tr>
    {fp.sortable_th("Arm","text")}{fp.sortable_th("Kind","text")}{fp.sortable_th("One knob","text")}{fp.sortable_th("Why","text")}
  </tr></thead>
  <tbody>
    <tr><td><code>00_control</code></td><td>CONTROL</td><td><code>wrl_target_mode=scale</code></td><td>Pinned old house (scale 50/50) — not the 2026-09-22 swing default</td></tr>
    <tr><td><code>ENTRY_minzone01</code></td><td>ENTRY</td><td><code>wrl_min_zone_pct=0.01</code></td>
      <td>Demand zone ≥ 1% wide. Same exit as control.</td></tr>
    <tr><td><code>EXIT_swing</code></td><td>EXIT</td><td><code>wrl_target_mode=swing</code></td>
      <td>Full size out at swing high. Parent adopted freeze on this sleeve (HOLD).</td></tr>
    <tr><td><code>EXIT_cd5</code></td><td>EXIT</td><td><code>symbol_reentry_cooldown_days=5</code></td>
      <td>5-day cooldown after a close — <strong>null if engine still never sets cooldown_until</strong></td></tr>
  </tbody></table></div>

  <h2>IS headlines (decide here)</h2>
    <div class="cards">
    {_card(fp.CONTROL, is_books[fp.CONTROL])}
    {_card("ENTRY_minzone01", is_books.get("ENTRY_minzone01") or empty_book)}
    {_card("EXIT_swing", is_books.get("EXIT_swing") or empty_book)}
    {_card("EXIT_cd5", is_books.get("EXIT_cd5") or empty_book)}
  </div>

  <h2>Verdict</h2>
  <div class="callout {ocls}"><strong>Overall: {html.escape(overall)}.</strong> {html.escape(overall_why)}</div>
  {''.join(v_html)}
  <div class="callout {cd_cls}"><strong>EXIT_cd5 cooldown — {"still a null test" if cd_null else "not null"}.</strong>
  {html.escape(cd_note)}</div>
  <p class="muted">KEEP / LEAN KEEP only if IS quality improves vs control without collapsing N.
  Flat → HOLD. Worse → DISMISS. OOS softens → HOLD, do not retune. Not Total PnL.</p>

  <h2>FULL book</h2>
  {fp._table_compare("FULL (all entries)", full_books, sums, audits, notes)}

  <h2>In-sample (entry &lt; 2024-01-01) — decide here</h2>
  {fp._table_compare("IS", is_books, empty_sums, empty_sums, empty_notes)}

  <h2>Out-of-sample (entry ≥ 2024-01-01) — report only</h2>
  {fp._table_compare("OOS", oos_books, empty_oos, empty_oos, empty_notes)}

  {fp._exit_table(full_books)}

  <h2>Promotion</h2>
  <p>Research candidate / research sleeve only. Not gold. Not DailyRun. No
  <code>run_wrl.bat</code> change. Parent EXIT_swing on this universe is already HOLD.
  Next bar: walk-forward or a second universe, plus product-owner sign-off and reconcile
  freeze, before any DailyRun wire.</p>

  <p class="muted">Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M"))} ·
  <code>tools/wrl_univ29_firstpass_ab_20260922.py</code> reuses
  <code>tools/wrl_firstpass_ab_20260922.py</code> · research ≠ gold ≠ DailyRun</p>
</div>
{fp.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    compare = STAMP_DIR / "compare.html"
    compare.write_text(html_page, encoding="utf-8")
    (STAMP_DIR / "OVERALL.txt").write_text(f"{overall}\n{overall_why}\n", encoding="utf-8")
    print(f"[WRL-29-1P] wrote {compare}", flush=True)
    print(f"[WRL-29-1P] overall {overall}: {overall_why}", flush=True)
    return [compare, STAMP_DIR / "BASELINE.md", STAMP_DIR / "HYPOTHESIS.md"]


def _write_baseline(
    verdicts: dict[str, tuple[str, str]],
    overall: str,
    overall_why: str,
    is_books: dict[str, dict[str, Any]],
    oos_books: dict[str, dict[str, Any]],
    cd_null: bool,
    cd_note: str,
    missing: list[str],
) -> None:
    lines = [
        "# WRL first-pass A/B on univ29 — 2026-09-22",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Selection bias (label honesty)",
        "",
        "Paul chose these 29 names **after** seeing the full-universe IS symbol table in "
        "`drive/paul_experiments/wrl_exitswing_is_universe_20260922`. That is "
        "**in-sample selection**, even though this page also prints OOS. Do not treat a "
        "good IS sleeve as confirmation. Do not retune on OOS.",
        "",
        "## Delta from prior",
        "",
        "- **Parent sleeve:** `drive/paul_experiments/wrl_exitswing_univ29_20260922/` "
        "(EXIT_swing adopted; HOLD; IS N=1760 WR 43.6% Avg +2.53 PF 2.41).",
        "- **First-pass suite reused:** `drive/paul_experiments/wrl_firstpass_ab_20260922/` "
        "and `tools/wrl_firstpass_ab_20260922.py` (control / min-zone / swing / cd5).",
        "- **This stamp:** same four one-knob arms, universe forced to the frozen 29. "
        "Plus post-run on the EXIT_swing IS book only (`post_run_is/`, stamp "
        f"`{IS_CLOSED_TS}`) — not an overwrite of 6 Sep full-universe assessments.",
        "- **Not run:** Mag10 kitchen sink (`tools/run_wrl.ab` / nine-arm Total PnL).",
        "- **Cooldown:** labeled null if still unread; no `cooldown_until` wiring invented.",
        "",
        "## Freeze (everything else locked)",
        "",
        FREEZE,
        "",
        "Universe = first universe, 29 names, Paul's order (see `universe29.csv`): "
        + ", ".join(UNIVERSE_29)
        + ". Count = 29. Do not add/drop.",
        "",
        "IS = `entry_date < 2024-01-01`. OOS = `entry_date >= 2024-01-01`. "
        "Report both N and quality. IS is the decision lens. Do not retune on OOS.",
        "",
    ]
    if missing:
        lines.extend(
            [
                f"Listed but no/short local OHLC (kept in universe file): {', '.join(missing)}.",
                "",
            ]
        )
    lines.extend(["## Arms (one knob each)", ""])
    lines.append("- `00_control` [CONTROL]: scale 50/50, stop swing low, min-zone off, cooldown off")
    lines.append("- `ENTRY_minzone01` [ENTRY]: `wrl_min_zone_pct=0.01` (same exit as control)")
    lines.append("- `EXIT_swing` [EXIT]: `wrl_target_mode=swing` (same entry as control)")
    lines.append("- `EXIT_cd5` [EXIT]: `symbol_reentry_cooldown_days=5` (null if engine never sets cooldown_until)")
    lines.extend(["", "## IS headlines (decide here)", ""])
    for arm in ("00_control", "ENTRY_minzone01", "EXIT_swing", "EXIT_cd5"):
        b = is_books.get(arm) or {}
        if not b:
            continue
        lines.append(
            f"- {arm} IS: N={b['n']} · WR={b['wr']:.1f}% · Avg PnL%={b['avg_pnl_pct']:+.2f} · "
            f"PF={b['pf']:.2f} · Max DD={b['max_dd']:.2f}%"
        )
    lines.extend(["", "## OOS headlines (report only)", ""])
    for arm in ("00_control", "ENTRY_minzone01", "EXIT_swing", "EXIT_cd5"):
        b = oos_books.get(arm) or {}
        if not b:
            continue
        lines.append(
            f"- {arm} OOS: N={b['n']} · WR={b['wr']:.1f}% · Avg PnL%={b['avg_pnl_pct']:+.2f} · "
            f"PF={b['pf']:.2f} · Max DD={b['max_dd']:.2f}%"
        )
    lines.extend(["", "## Verdicts (IS quality; OOS report-only)", ""])
    for arm, (lab, why) in verdicts.items():
        lines.append(f"- **{arm} — {lab}:** {why}")
    lines.extend(
        [
            "",
            f"**Overall: {overall}.** {overall_why}",
            "",
            "## Cooldown",
            "",
            f"{'Still a null test. ' if cd_null else 'Not null. '}{cd_note}",
            "",
            "## Promotion",
            "",
            "Research candidate only. Not gold. Not DailyRun. No `run_wrl.bat` change.",
            "",
        ]
    )
    (STAMP_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_hypothesis(
    verdicts: dict[str, tuple[str, str]],
    overall: str,
    overall_why: str,
    is_books: dict[str, dict[str, Any]],
    oos_books: dict[str, dict[str, Any]],
    cd_null: bool,
) -> None:
    def _h(book: dict[str, Any]) -> str:
        if not book:
            return "n/a"
        return (
            f"N={book['n']}, WR={book['wr']:.1f}%, Avg%={book['avg_pnl_pct']:+.2f}, "
            f"PF={book['pf']:.2f}, MaxDD={book['max_dd']:.2f}%"
        )

    vline = "; ".join(f"{a}={lab}" for a, (lab, _w) in verdicts.items())
    (STAMP_DIR / "HYPOTHESIS.md").write_text(
        "\n".join(
            [
                "# Hypothesis test — WRL univ29 first-pass 20260922",
                "",
                "| Field | Fill |",
                "|---|---|",
                "| System / prefix | WRL — Weekly Range / Swing |",
                "| Baseline stamp | parent `wrl_exitswing_univ29_20260922` (EXIT_swing HOLD) + house first-pass `wrl_firstpass_ab_20260922` |",
                "| Universe | First universe — 29 names Paul listed (see `universe29.csv`). In-sample selection after full-univ IS table. Frozen exactly — no add/drop. |",
                "| Evidence | Parent sleeve EXIT_swing IS N=1760 WR 43.6% Avg +2.53 PF 2.41 HOLD. First-pass ImproveHints 260906140457: small_target_wins, band_tighten_weak_fill, post_target_quick_stop. This stamp re-runs post_run on the 29-name EXIT_swing IS book. |",
                "| Hypotheses | Same three one-knob first-pass arms: EXIT swing target; ENTRY 1% min zone; EXIT 5-day cooldown (null if unread). |",
                f"| Frozen settings | {FREEZE} |",
                "| Alternatives | control + 1 value each (3 arms). Not Mag10 kitchen sink. |",
                f"| Decision | {overall} — {overall_why} Per-arm: {vline} |",
                f"| IS 00_control | {_h(is_books.get('00_control') or {})} |",
                f"| IS ENTRY_minzone01 | {_h(is_books.get('ENTRY_minzone01') or {})} |",
                f"| IS EXIT_swing | {_h(is_books.get('EXIT_swing') or {})} |",
                f"| IS EXIT_cd5 | {_h(is_books.get('EXIT_cd5') or {})} |",
                f"| OOS 00_control (report only) | {_h(oos_books.get('00_control') or {})} |",
                f"| OOS ENTRY_minzone01 (report only) | {_h(oos_books.get('ENTRY_minzone01') or {})} |",
                f"| OOS EXIT_swing (report only) | {_h(oos_books.get('EXIT_swing') or {})} |",
                f"| OOS EXIT_cd5 (report only) | {_h(oos_books.get('EXIT_cd5') or {})} |",
                f"| EXIT_cd5 null? | {'yes — cooldown_until never set' if cd_null else 'no — books differ'} |",
                "| PO sign-off | no |",
                "| Reconcile freeze | no — research only |",
                "",
                "OOS is report-only. Do not retune on OOS. Selection bias: names picked after seeing the parent IS table.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="WRL univ29 first-pass A/B + IS post-run 20260922")
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--skip-post-run", action="store_true")
    ap.add_argument("--skip-ab", action="store_true")
    args = ap.parse_args()

    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    _write_universe_csv(STAMP_DIR / "universe29.csv")

    post_ok = True
    post_note = "skipped"
    hints: list[dict[str, str]] = []
    try:
        closed_is = slice_is_closed()
        if not args.skip_post_run:
            post_ok, post_note = run_post_run(closed_is)
        else:
            post_ok, post_note = True, "skipped by flag"
        hints = _hint_rows()
    except Exception as exc:  # noqa: BLE001
        post_ok = False
        post_note = f"{exc}\n{traceback.format_exc()}"
        print(f"[WRL-29-1P] post-run path failed: {exc}", flush=True)
        _write_failure_html(STAMP_DIR / "post_run_failure.html", "WRL univ29 post-run failed", post_note)

    fp = _load_firstpass()
    symbols = _load_universe()
    frames: dict[str, Any] = {}
    missing: list[str] = []
    for sym in symbols:
        df = fp._load_symbol(sym, DATA_DIR)
        if df is None:
            print(f"[WRL-29-1P] skip {sym}: no OHLC", flush=True)
            missing.append(sym)
            continue
        frames[sym] = df
    if not frames:
        _write_failure_html(
            STAMP_DIR / "compare.html",
            "WRL univ29 first-pass failed",
            "No symbol OHLC for the frozen 29.",
        )
        return 1

    kept = [s for s in symbols if s in frames]
    print(f"[WRL-29-1P] {len(frames)} symbols, {args.workers} workers -> {STAMP_DIR}", flush=True)

    try:
        if not args.skip_ab and not args.summarize_only:
            for arm, overrides, _n, _k in fp.ARMS:
                fp._run_arm(arm, overrides, kept, frames, int(args.workers))
        elif args.summarize_only or args.skip_ab:
            print("[WRL-29-1P] skipping AB engine (summarize-only / skip-ab)", flush=True)

        ctrl_rows = fp._closed_rows(STAMP_DIR / "00_control")
        cd_rows = fp._closed_rows(STAMP_DIR / "EXIT_cd5")
        cd_null = False
        if ctrl_rows and cd_rows:
            same_n = len(ctrl_rows) == len(cd_rows)
            same_keys = _trade_keys(ctrl_rows) == _trade_keys(cd_rows)
            cd_null = same_n and same_keys
            cd_note = (
                f"Control N={len(ctrl_rows)}, EXIT_cd5 N={len(cd_rows)}. "
                + (
                    "Identical trade keys — engine still never assigns cooldown_until. Labeled null; no wiring added."
                    if cd_null
                    else "Books differ — cooldown is no longer a null test; judge as a real one-knob EXIT arm."
                )
            )
        else:
            cd_note = "Could not compare Closed books for cooldown null check."
            cd_null = True

        write_reports(
            fp,
            kept,
            frames,
            missing=missing,
            post_ok=post_ok,
            post_note=post_note,
            hints=hints,
            cd_null=cd_null,
            cd_note=cd_note,
        )
    except Exception as exc:  # noqa: BLE001
        detail = f"{exc}\n{traceback.format_exc()}"
        print(f"[WRL-29-1P] AB/report failed: {exc}", flush=True)
        _write_failure_html(STAMP_DIR / "compare.html", "WRL univ29 first-pass failed", detail)
        return 1

    if not post_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
