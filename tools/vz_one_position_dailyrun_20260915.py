#!/usr/bin/env python3
"""Lock VZ one-position-per-symbol as DailyRun + re-freeze reconcile golden.

Writes drive/paul_experiments/vz_one_position_dailyrun_20260915/
(BASELINE.md + compare.html). Updates reconcile_gate_config.json to the new
house pin / LatestRun book. Does not mutate rsi_universe.csv.
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import shutil
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
DRIVE = REPO / "drive"
STAMP = "vz_one_position_dailyrun_20260915"
OUT = DRIVE / "paul_experiments" / STAMP
CFG_PATH = DRIVE / "paul_experiments" / "reconcile_gate_config.json"
WRITEUP = REPO / "tools" / "_gen_system_writeups.py"
BEFORE_CLOSED = DRIVE / "VZ_Closed_260915143939.csv"
IS_CUT = date(2024, 1, 1)
VZ_CASH = 45_000.0
VZ_INIT = 500_000.0

_CF = DRIVE / "paul_experiments"
if str(_CF) not in sys.path:
    sys.path.insert(0, str(_CF))
from compare_format import (  # noqa: E402
    format_money,
    overlay_ann_ror_max_dd,
    resolve_overlay_sharpe,
)

ASK = (
    "ok. let's lock in removing the more than one trade at a time code as the "
    "DailyRun. make sure the latest is what we check against when looking for "
    "regressions."
)

LAYMAN = (
    "Volatility Zone (VZ) must not buy a name we already hold. That is now the "
    "live DailyRun rule, not a research overlay. After we rerun house VZ, "
    "VZ_LatestRun_Closed.csv is the book we compare to when checking for regressions."
)

_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  var MONTHS = {
    january:1, february:2, march:3, april:4, may:5, june:6,
    july:7, august:8, september:9, october:10, november:11, december:12
  };
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "month") {
      var key = s.toLowerCase().split(/\\s/)[0];
      return MONTHS[key] || 0;
    }
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      var mdy = s.match(/(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/);
      if (mdy) return parseInt(mdy[3] + mdy[1].padStart(2, "0") + mdy[2].padStart(2, "0"), 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
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
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def _esc(s: Any) -> str:
    return html_mod.escape("" if s is None else str(s))


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _read_pin(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    return (raw.splitlines()[0] if raw else "").strip()


def _parse_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    s = s.replace("/", "-")
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt != "%Y%m%d" else s[:8], fmt).date()
        except ValueError:
            continue
    if s.isdigit() and len(s) == 8:
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _f(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.lower() in ("nan", "none", "nat", "—", "-"):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    if not math.isfinite(x):
        return None
    return x


def load_closed(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(rows):
        opened = _parse_date(raw.get("DATE_OPENED") or raw.get("DATE OPENED"))
        if opened is None:
            continue
        pct = _f(raw.get("PNL_PCT") or raw.get("PNL %"))
        dol = _f(raw.get("PNL_DOLLARS") or raw.get("PNL $"))
        if dol is None and pct is not None:
            dol = pct / 100.0 * VZ_CASH
        out.append(
            {
                "i": i,
                "symbol": str(raw.get("SYMBOL") or "").strip().upper(),
                "opened": opened,
                "closed": _parse_date(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED")),
                "entry": _f(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE")),
                "stop": _f(raw.get("STOP_PRICE") or raw.get("STOP PRICE")),
                "target": _f(raw.get("TARGET_PRICE") or raw.get("TARGET PRICE")),
                "exit": _f(raw.get("EXIT_PRICE") or raw.get("EXIT PRICE")),
                "exit_type": str(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip().upper(),
                "days": _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD")),
                "pnl": pct,
                "pnl_d": dol,
                "n_sig": raw.get("N_SIGNALS_THAT_DAY") or "",
                "multi": raw.get("MULTI_SIGNAL_DAY") or "",
                "zone_id": str(raw.get("ZONE_ID") or "").strip(),
            }
        )
    return out


def gold_20200506(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["symbol"] == "GOLD" and r["opened"] == date(2020, 5, 6)]


def slice_is(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["opened"] < IS_CUT]


def slice_oos(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["opened"] >= IS_CUT]


def win_rate(rows: list[dict[str, Any]]) -> Optional[float]:
    pcts = [r["pnl"] for r in rows if r["pnl"] is not None]
    if not pcts:
        return None
    return 100.0 * sum(1 for p in pcts if p > 0) / len(pcts)


def avg_pct(rows: list[dict[str, Any]]) -> Optional[float]:
    pcts = [r["pnl"] for r in rows if r["pnl"] is not None]
    if not pcts:
        return None
    return sum(pcts) / len(pcts)


def avg_days(rows: list[dict[str, Any]]) -> Optional[float]:
    days = [r["days"] for r in rows if r["days"] is not None]
    if not days:
        return None
    return sum(days) / len(days)


def profit_factor(rows: list[dict[str, Any]]) -> Optional[float]:
    wins = sum(r["pnl_d"] or 0.0 for r in rows if (r["pnl_d"] or 0) > 0)
    loss = abs(sum(r["pnl_d"] or 0.0 for r in rows if (r["pnl_d"] or 0) < 0))
    if loss <= 0:
        return None if wins <= 0 else float("inf")
    return wins / loss


def avg_pnl_wo_max(rows: list[dict[str, Any]]) -> Optional[float]:
    pcts = [r["pnl"] for r in rows if r["pnl"] is not None]
    if len(pcts) < 2:
        return avg_pct(rows)
    mx = max(pcts)
    rest = [p for p in pcts if p != mx]
    if len(rest) == len(pcts):
        rest = pcts[:-1]
    return sum(rest) / len(rest) if rest else None


def exit_mix(rows: list[dict[str, Any]]) -> Counter:
    c: Counter = Counter()
    for r in rows:
        et = r["exit_type"] or "UNKNOWN"
        if et in ("STOP", "STOP_LOSS"):
            et = "STOP_LOSS"
        elif et in ("TIME", "TIME_STOP"):
            et = "TIME"
        c[et] += 1
    return c


def pack_metrics(
    rows: list[dict[str, Any]],
    *,
    equity_curve: Optional[Path] = None,
    start: Optional[date] = None,
    end_excl: Optional[date] = None,
) -> dict[str, Any]:
    ov = overlay_ann_ror_max_dd(
        rows,
        cash=VZ_CASH,
        initial_account=VZ_INIT,
        equity_curve_path=equity_curve,
        start_date=start,
        end_date_exclusive=end_excl,
    )
    sh, sh_src = resolve_overlay_sharpe(
        rows,
        cash=VZ_CASH,
        initial_account=VZ_INIT,
        equity_curve_path=equity_curve,
        start_date=start,
        end_date_exclusive=end_excl,
    )

    def _finite_or_none(v: Any) -> Optional[float]:
        x = _f(v)
        if x is None or (isinstance(x, float) and not math.isfinite(x)):
            return None
        return x

    n = len(rows)
    wr = win_rate(rows)
    ap = avg_pct(rows)
    pf = profit_factor(rows)
    mix = exit_mix(rows)
    return {
        "n": n,
        "wins": sum(1 for r in rows if (r["pnl"] or 0) > 0),
        "losses": sum(1 for r in rows if (r["pnl"] or 0) <= 0),
        "win_pct": wr,
        "avg_pct": ap,
        "avg_wo_max": avg_pnl_wo_max(rows),
        "avg_days": avg_days(rows),
        "pf": None if pf is not None and not math.isfinite(pf) else pf,
        "ann_ror": _finite_or_none(ov.get("ann_ror", ov.get("Ann_ROR"))),
        "max_dd": _finite_or_none(ov.get("max_dd", ov.get("Max_DD"))),
        "calmar": _finite_or_none(ov.get("calmar")),
        "sharpe": _finite_or_none(sh if sh is not None else ov.get("sharpe", ov.get("Sharpe"))),
        "sharpe_src": sh_src or ov.get("sharpe_source") or ov.get("Sharpe_source") or "",
        "exit_mix": mix,
        "gold_n": len(gold_20200506(rows)),
        "multi_yes": sum(1 for r in rows if str(r.get("multi") or "").upper() == "YES"),
    }


def _fmt_n(v: Any) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"


def _fmt_pct(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{float(v):.{digits}f}%"


def _fmt_num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and not math.isfinite(v):
        return "—"
    return f"{float(v):.{digits}f}"


def _fmt_delta(v: Any, *, pct: bool = False, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    sign = "+" if v > 0 else ""
    if pct:
        return f"{sign}{v:.{digits}f}%"
    if abs(v - round(v)) < 1e-9:
        return f"{sign}{int(round(v))}"
    return f"{sign}{v:.{digits}f}"


def freeze_golden(pin: str) -> Path:
    dest = DRIVE / "paul_experiments" / f"vz_baseline_{pin}" / "engine_closed"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in DRIVE.glob(f"VZ_*_{pin}.*"):
        shutil.copy2(src, dest / src.name)
        copied += 1
    latest = DRIVE / "VZ_LatestRun_Closed.csv"
    closed = dest / f"VZ_Closed_{pin}.csv"
    if not closed.is_file():
        raise FileNotFoundError(f"golden Closed missing after copy: {closed}")
    n_closed = sum(1 for _ in closed.open(encoding="utf-8-sig")) - 1
    readme = f"""# VZ reconcile baseline freeze — stamp `{pin}`

Frozen **engine Closed** for the DailyRun reconcile gate after locking
**one open position per symbol** as the live Volatility Zone (VZ) rule.

**Do not invent trades** — this folder is a copy of a real `drive/VZ_*_{pin}.*`
house run (`run_vz.bat` defaults after the one-position DailyRun lock).

LatestRun alias `drive/VZ_LatestRun_Closed.csv` is the same book (regression
side of the gate). Future DailyRun VZ must match this identity; new forward
fills after the freeze cutoff are allowed.

## Stamp / date

| Item | Value |
|---|---|
| Engine stamp | **`{pin}`** (one-position DailyRun lock 2026-09-15) |
| Golden Closed | `engine_closed/VZ_Closed_{pin}.csv` (**{n_closed}** trades) |
| LatestRun | `drive/VZ_LatestRun_Closed.csv` (same book at lock-in) |
| Universe | Paul78.142 — [`drive/universes/VZ_universe.csv`](../../universes/VZ_universe.csv) |
| Gate config | `../reconcile_gate_config.json` → system **`VZ`** |
| Runner | `run_vz.bat` → `rocket_tbn -v vz_mode=true` |
| Adopt stamp | [`../vz_one_position_dailyrun_20260915/`](../vz_one_position_dailyrun_20260915/) |
| Prior golden | `260907175402` (ATR% at trigger adopt; pyramid / overlapping fills) |

## Why this stamp

Paul asked to lock in “do not buy a name we already hold” as DailyRun, and to
make LatestRun the book we check against for regressions. GOLD 2020-05-06 is
**one** Closed row. Older N=2708 / two-row GOLD books are not the baseline.

## Levers (house freeze)

| Lever | Value |
|---|---|
| Universe | Paul78.142 (142) |
| zone_kinds | HL only |
| first_retest_only | true |
| min_touches | ≥1 |
| retest_eps_pct | 0.005 |
| lookback / retest_window | 126 / 63 |
| entry_on | next_open |
| exit | `EXIT_atr4_s025_r15_ts20` |
| stop_atr | 0.25 |
| target_r | 1.5 |
| exit_bars | 20 |
| min_atr_pct_at_trigger | 4.0 |
| min_atr_pct_at_entry | 0 (off) |
| require_hvn_overlap | false |
| trade_side | long |
| cooldown_after_target_days | 10 |
| One position per symbol | **on** (always; no flag) |

## Layout

```
vz_baseline_{pin}/
  README.md
  engine_closed/
    VZ_Closed_{pin}.csv
    …
```

Source originals remain under `drive/VZ_*_{pin}.*`. Copied files: {copied}.
LatestRun exists: {latest.is_file()}.
"""
    (dest.parent / "README.md").write_text(readme, encoding="utf-8")
    print(f"[freeze] {dest} copied={copied} closed_n={n_closed}", flush=True)
    return closed


def update_reconcile_config(pin: str, n_closed: int) -> None:
    c = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    for s in c["systems"]:
        if s["id"] == "VZ":
            s["latest_alias"] = "VZ_LatestRun_Closed.csv"
            s["closed_prefix"] = "VZ_Closed"
            s["baseline"] = {
                "mode": "single_file",
                "path": (
                    f"drive/paul_experiments/vz_baseline_{pin}/"
                    f"engine_closed/VZ_Closed_{pin}.csv"
                ),
            }
            s["freeze_note"] = (
                f"Paul78.142 + EXIT_atr4_s025_r15_ts20 / stop 0.25 / ts20 / cd10; "
                f"atr4 = 4% ATR floor at trigger close (entry gate off); "
                f"one position per symbol DailyRun lock 2026-09-15; "
                f"golden {pin} (N={n_closed}); latest = VZ_LatestRun_Closed.csv. "
                f"Prior golden 260907175402 was the pyramid book."
            )
            break
    note = c.get("notes", "")
    marker = f"VZ re-frozen {pin}"
    if marker not in note:
        c["notes"] = (
            note.rstrip()
            + f" {marker} after one-position DailyRun lock "
            f"(prior 260907175402 pyramid / overlapping fills)."
        )
    CFG_PATH.write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
    print(f"[cfg] VZ golden -> {pin} (n={n_closed}) latest=VZ_LatestRun_Closed.csv", flush=True)


def update_writeup_golden(pin: str) -> None:
    if not WRITEUP.is_file():
        return
    text = WRITEUP.read_text(encoding="utf-8")
    new_cell = (
        f'"<code>drive/paul_experiments/vz_baseline_{pin}/</code> '
        f'(one-position DailyRun lock <code>vz_one_position_dailyrun_20260915</code>; '
        f'latest = <code>VZ_LatestRun_Closed.csv</code>; '
        f'prior trigger-gate <code>vz_baseline_260907175402</code>)"'
    )
    if f"vz_baseline_{pin}" in text:
        print(f"[writeup] already points at {pin}", flush=True)
        return
    old = (
        '"<code>drive/paul_experiments/vz_baseline_260907175402/</code> '
        "(trigger-gate adopt <code>vz_atr_trigger_adopt_20260907</code>; "
        'prior PO s025 <code>vz_baseline_260907093231</code>)"'
    )
    if old in text:
        WRITEUP.write_text(text.replace(old, new_cell), encoding="utf-8")
        print(f"[writeup] reconcile freeze -> {pin}", flush=True)
        return
    print("[writeup] old freeze cell not found — skipped", flush=True)


def write_baseline_md(
    path: Path,
    *,
    pin: str,
    before: dict[str, Any],
    after: dict[str, Any],
    before_is: dict[str, Any],
    after_is: dict[str, Any],
    before_oos: dict[str, Any],
    after_oos: dict[str, Any],
    gold_after: list[dict[str, Any]],
) -> None:
    gold_line = (
        "; ".join(
            f"stop={g['stop']} target={g['target']} pnl={g['pnl']}% "
            f"n_sig={g['n_sig']} multi={g['multi']} zone={g['zone_id']}"
            for g in gold_after
        )
        or "none"
    )
    path.write_text(
        f"""# VZ one-position DailyRun lock — `{STAMP}`

## What you asked

{ASK}

## In plain English

{LAYMAN}

## Status

**DailyRun lock** (operational). Not walk-forward gold. Research extras on the
old pyramid book were better quality (higher Avg%) — we still lock one position
because two lots on a name we already hold is not how Paul trades.

## Freeze (unchanged except one-position)

| Lever | Value |
|---|---|
| Universe | Paul78.142 (`drive/universes/VZ_universe.csv`) |
| exit | `EXIT_atr4_s025_r15_ts20` |
| lookback / retest_window | 126 / 63 |
| entry_on | next_open |
| stop_atr / target_r / exit_bars | 0.25 / 1.5 / 20 |
| min_atr_pct_at_trigger | 4.0 (entry gate off) |
| cooldown_after_target_days | 10 |
| One position per symbol | **on** (`enrich_trade_rows`; no flag) |

## Pins

| Item | Value |
|---|---|
| Before (pyramid) | `VZ_Closed_260915143939.csv` (N={before['n']}) |
| New house pin | **`{pin}`** |
| LatestRun | `drive/VZ_LatestRun_Closed.csv` (N={after['n']}) |
| Reconcile golden | `drive/paul_experiments/vz_baseline_{pin}/` |
| GOLD 20200506 after | {after['gold_n']} row — {gold_line} |

IS = entry &lt; 2024-01-01; OOS = entry ≥ 2024-01-01 (report-only). Do not retune OOS.

## Before vs after (full / IS / OOS)

| Book | N | Avg% | WR% | Ann ROR | Max DD | GOLD 20200506 |
|---|---:|---:|---:|---:|---:|---:|
| Pyramid full | {before['n']} | {before['avg_pct']} | {before['win_pct']} | {before['ann_ror']} | {before['max_dd']} | {before['gold_n']} |
| House full | {after['n']} | {after['avg_pct']} | {after['win_pct']} | {after['ann_ror']} | {after['max_dd']} | {after['gold_n']} |
| Pyramid IS | {before_is['n']} | {before_is['avg_pct']} | {before_is['win_pct']} | {before_is['ann_ror']} | {before_is['max_dd']} | |
| House IS | {after_is['n']} | {after_is['avg_pct']} | {after_is['win_pct']} | {after_is['ann_ror']} | {after_is['max_dd']} | |
| Pyramid OOS | {before_oos['n']} | {before_oos['avg_pct']} | {before_oos['win_pct']} | {before_oos['ann_ror']} | {before_oos['max_dd']} | |
| House OOS | {after_oos['n']} | {after_oos['avg_pct']} | {after_oos['win_pct']} | {after_oos['ann_ror']} | {after_oos['max_dd']} | |

Selection: operational lock (one position), not a quality KEEP. Overlay on the
old book was 2708→2172 / Avg% 5.18→4.27; engine house rerun is N={after['n']}.
""",
        encoding="utf-8",
    )


def write_html(
    path: Path,
    *,
    pin: str,
    before: dict[str, Any],
    after: dict[str, Any],
    before_is: dict[str, Any],
    after_is: dict[str, Any],
    before_oos: dict[str, Any],
    after_oos: dict[str, Any],
    gold_before: list[dict[str, Any]],
    gold_after: list[dict[str, Any]],
) -> None:
    def row(label: str, scope: str, a: dict[str, Any], b: dict[str, Any]) -> str:
        dn = (b["n"] - a["n"]) if a["n"] is not None and b["n"] is not None else None
        davg = (
            (b["avg_pct"] - a["avg_pct"])
            if a["avg_pct"] is not None and b["avg_pct"] is not None
            else None
        )
        dwr = (
            (b["win_pct"] - a["win_pct"])
            if a["win_pct"] is not None and b["win_pct"] is not None
            else None
        )
        dror = (
            (b["ann_ror"] - a["ann_ror"])
            if a["ann_ror"] is not None and b["ann_ror"] is not None
            else None
        )
        ddd = (
            (b["max_dd"] - a["max_dd"])
            if a["max_dd"] is not None and b["max_dd"] is not None
            else None
        )
        return (
            "<tr>"
            f"<td>{_esc(label)}</td><td>{_esc(scope)}</td>"
            f"<td>{_fmt_n(a['n'])}</td><td>{_fmt_n(b['n'])}</td><td>{_fmt_delta(dn)}</td>"
            f"<td>{_fmt_pct(a['avg_pct'])}</td><td>{_fmt_pct(b['avg_pct'])}</td>"
            f"<td>{_fmt_delta(davg, pct=True)}</td>"
            f"<td>{_fmt_pct(a['win_pct'])}</td><td>{_fmt_pct(b['win_pct'])}</td>"
            f"<td>{_fmt_delta(dwr, pct=True)}</td>"
            f"<td>{_fmt_pct(a['ann_ror'])}</td><td>{_fmt_pct(b['ann_ror'])}</td>"
            f"<td>{_fmt_delta(dror, pct=True)}</td>"
            f"<td>{_fmt_pct(a['max_dd'])}</td><td>{_fmt_pct(b['max_dd'])}</td>"
            f"<td>{_fmt_delta(ddd, pct=True)}</td>"
            f"<td>{_fmt_num(a['pf'])}</td><td>{_fmt_num(b['pf'])}</td>"
            f"<td>{_fmt_num(a['avg_days'])}</td><td>{_fmt_num(b['avg_days'])}</td>"
            f"<td>{_fmt_pct(a['avg_wo_max'])}</td><td>{_fmt_pct(b['avg_wo_max'])}</td>"
            f"<td>{_fmt_num(a['sharpe'])}</td><td>{_fmt_num(b['sharpe'])}</td>"
            f"<td>{_fmt_num(a['calmar'])}</td>"
            f"<td>{_fmt_num(b['calmar'])}</td>"
            f"<td>{a['gold_n']}</td><td>{b['gold_n']}</td>"
            "</tr>"
        )

    head = "".join(
        _sortable_th(lab, typ)
        for lab, typ in (
            ("Book", "text"),
            ("Scope", "text"),
            ("N before", "num"),
            ("N after", "num"),
            ("Δ N", "num"),
            ("Avg% before", "num"),
            ("Avg% after", "num"),
            ("Δ Avg%", "num"),
            ("WR% before", "num"),
            ("WR% after", "num"),
            ("Δ WR%", "num"),
            ("Ann ROR before", "num"),
            ("Ann ROR after", "num"),
            ("Δ Ann ROR", "num"),
            ("Max DD before", "num"),
            ("Max DD after", "num"),
            ("Δ Max DD", "num"),
            ("PF before", "num"),
            ("PF after", "num"),
            ("Days before", "num"),
            ("Days after", "num"),
            ("Avg% w/o max before", "num"),
            ("Avg% w/o max after", "num"),
            ("Sharpe before", "num"),
            ("Sharpe after", "num"),
            ("Calmar before", "num"),
            ("Calmar after", "num"),
            ("GOLD 20200506 before", "num"),
            ("GOLD 20200506 after", "num"),
        )
    )
    body = (
        row("Pyramid → house engine", "Full book", before, after)
        + row("Pyramid → house engine", "IS (entry < 2024-01-01)", before_is, after_is)
        + row("Pyramid → house engine", "OOS (entry ≥ 2024-01-01, report-only)", before_oos, after_oos)
    )

    def gold_rows(rows: list[dict[str, Any]], book: str) -> str:
        if not rows:
            return f"<tr><td>{_esc(book)}</td><td colspan='8'>none</td></tr>"
        html = ""
        for g in rows:
            html += (
                "<tr>"
                f"<td>{_esc(book)}</td>"
                f"<td>{g['opened'].isoformat()}</td>"
                f"<td>{_fmt_num(g['entry'])}</td>"
                f"<td>{_fmt_num(g['stop'])}</td>"
                f"<td>{_fmt_num(g['target'])}</td>"
                f"<td>{_fmt_pct(g['pnl'])}</td>"
                f"<td>{_esc(g['n_sig'] or '—')}</td>"
                f"<td>{_esc(g['multi'] or '—')}</td>"
                f"<td>{_esc(g['zone_id'] or '—')}</td>"
                "</tr>"
            )
        return html

    ghead = "".join(
        _sortable_th(lab, typ)
        for lab, typ in (
            ("Book", "text"),
            ("Opened", "date"),
            ("Entry", "num"),
            ("Stop", "num"),
            ("Target", "num"),
            ("PnL %", "num"),
            ("N_SIGNALS_THAT_DAY", "num"),
            ("MULTI_SIGNAL_DAY", "text"),
            ("ZONE_ID", "text"),
        )
    )

    mix_keys = sorted(set(before["exit_mix"]) | set(after["exit_mix"]))
    mix_head = "".join(
        _sortable_th(lab, typ)
        for lab, typ in (("Exit", "text"), ("Before N", "num"), ("After N", "num"), ("Δ N", "num"))
    )
    mix_body = ""
    for k in mix_keys:
        bn = before["exit_mix"].get(k, 0)
        an = after["exit_mix"].get(k, 0)
        mix_body += (
            f"<tr><td>{_esc(k)}</td><td>{bn}</td><td>{an}</td>"
            f"<td>{_fmt_delta(an - bn)}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP}</title>
<style>
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; touch-action: manipulation; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 88rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 88rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
.lock {{ background: #ecfdf5; border: 1px solid #6ee7b7; }}
.caveat {{ color: #9a3412; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }}
table.sortable th {{ background: #f1f5f9; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; white-space: pre-wrap; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #dcfce7; }}
</style></head><body>
<h1>VZ one position per symbol — now DailyRun</h1>
<p class="badge">DailyRun lock · not walk-forward gold · LatestRun is the regression baseline</p>
<p class="meta">Stamp <code>{_esc(STAMP)}</code> · house pin <code>{_esc(pin)}</code> · {datetime.now().strftime("%Y-%m-%d")} · Click column headers to sort</p>

<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{_esc(ASK)}</blockquote>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>

<div class="insight lock">
<h2 style="margin-top:0;border:0">What is locked</h2>
<p>Volatility Zone (VZ) <code>enrich_trade_rows</code> skips a later signal while that
symbol is still held (including same-day two-zone pile-ups). Always on — no
<code>run_vz.bat</code> / DailyRun flag re-enables pyramids.
<code>N_SIGNALS_THAT_DAY</code> / <code>MULTI_SIGNAL_DAY</code> stay on the Closed
row so a two-zone day still reports N=2 on the kept lot.</p>
<p class="meta">House rerun pin <code>{_esc(pin)}</code> wrote
<code>drive/VZ_LatestRun_Closed.csv</code> (N={after['n']}). GOLD 2020-05-06 is
<strong>{after['gold_n']}</strong> row (was {before['gold_n']} on the pyramid book).
Reconcile golden is <code>drive/paul_experiments/vz_baseline_{_esc(pin)}/</code>;
the latest side of the gate is <code>VZ_LatestRun_Closed.csv</code>.</p>
</div>

<h2>Before vs after</h2>
<p class="meta">Before = pyramid house Closed <code>VZ_Closed_260915143939.csv</code>
(N=2708). After = new house engine book / LatestRun. In-sample (IS) = entry &lt;
2024-01-01; out-of-sample (OOS) = entry ≥ 2024-01-01 is report-only. Sheet
{format_money(VZ_CASH)} · overlay Max DD / Sharpe seed {format_money(VZ_INIT)}.
Dollar Total / Sheet PnL omitted from the compare table (canonical rule).
Click headers to sort.</p>
<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
<p class="caveat meta">Research note: extras on the old pyramid book were
<strong>better quality</strong> (higher Avg%). Operational lock is still one
position — do not keep the pyramid bug. Not a quality KEEP / not walk-forward gold.</p>

<h2>GOLD 2020-05-06</h2>
<p class="meta">The two-zone same-day pile-up that started this thread. After lock, one row.</p>
<table class="sortable"><thead><tr>{ghead}</tr></thead><tbody>
{gold_rows(gold_before, "pyramid 260915143939")}
{gold_rows(gold_after, "house " + pin)}
</tbody></table>

<h2>Exit mix (full book)</h2>
<table class="sortable"><thead><tr>{mix_head}</tr></thead><tbody>{mix_body}</tbody></table>

<h2>Regression / DailyRun wiring</h2>
<ul class="meta">
<li><code>run_vz.bat</code> / <code>DailyRun.bat</code> rem: one position per symbol; no pyramid flag.</li>
<li><code>rocket_vz.write_outputs</code>: only a house-universe run updates
<code>VZ_LatestRun_*</code> and <code>VZ_house_last_run_ts.txt</code>.</li>
<li><code>Copy-LatestRunOutputs.ps1</code>: prefers the house pin so ALL / research cannot steal LatestRun.</li>
<li><code>tools/reconcile_gate.py</code> + <code>run_reconcile_gate.bat</code>: VZ
<code>latest_alias=VZ_LatestRun_Closed.csv</code>; golden = this pin (not 2708 / not
<code>260907175402</code> pyramid doubles).</li>
<li>Unit test: <code>tools/test_vz_one_position.py</code>.</li>
</ul>

{_SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    pin = _read_pin(DRIVE / "VZ_house_last_run_ts.txt")
    if not pin:
        raise SystemExit("VZ_house_last_run_ts.txt missing")
    after_path = DRIVE / f"VZ_Closed_{pin}.csv"
    latest = DRIVE / "VZ_LatestRun_Closed.csv"
    if not after_path.is_file():
        raise SystemExit(f"missing house Closed {after_path}")
    if not latest.is_file():
        raise SystemExit("missing VZ_LatestRun_Closed.csv")
    if not BEFORE_CLOSED.is_file():
        raise SystemExit(f"missing before book {BEFORE_CLOSED}")

    before_rows = load_closed(BEFORE_CLOSED)
    after_rows = load_closed(after_path)
    latest_rows = load_closed(latest)
    if len(after_rows) != len(latest_rows):
        raise SystemExit(
            f"LatestRun N={len(latest_rows)} != house pin N={len(after_rows)}"
        )
    gold_a = gold_20200506(after_rows)
    if len(gold_a) != 1:
        raise SystemExit(f"GOLD 20200506 must be 1 row, got {len(gold_a)}")

    eq_after = DRIVE / f"VZ_EquityCurve_{pin}.csv"
    if not eq_after.is_file():
        eq_after = DRIVE / "VZ_LatestRun_EquityCurve.csv"
    eq_before = None

    before = pack_metrics(before_rows, equity_curve=eq_before)
    after = pack_metrics(after_rows, equity_curve=eq_after if eq_after.is_file() else None)
    before_is = pack_metrics(slice_is(before_rows))
    after_is = pack_metrics(slice_is(after_rows))
    before_oos = pack_metrics(slice_oos(before_rows))
    after_oos = pack_metrics(slice_oos(after_rows))

    OUT.mkdir(parents=True, exist_ok=True)
    write_baseline_md(
        OUT / "BASELINE.md",
        pin=pin,
        before=before,
        after=after,
        before_is=before_is,
        after_is=after_is,
        before_oos=before_oos,
        after_oos=after_oos,
        gold_after=gold_a,
    )
    write_html(
        OUT / "compare.html",
        pin=pin,
        before=before,
        after=after,
        before_is=before_is,
        after_is=after_is,
        before_oos=before_oos,
        after_oos=after_oos,
        gold_before=gold_20200506(before_rows),
        gold_after=gold_a,
    )

    golden = freeze_golden(pin)
    n_closed = sum(1 for _ in golden.open(encoding="utf-8-sig")) - 1
    update_reconcile_config(pin, n_closed)
    update_writeup_golden(pin)

    print(
        f"[done] pin={pin} latest_n={len(after_rows)} gold={len(gold_a)} "
        f"html={OUT / 'compare.html'}",
        flush=True,
    )


if __name__ == "__main__":
    main()
