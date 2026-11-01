"""Same tennis T0-dog + GTC-fav book, sliced by 10¢ dog decile.

Report only. Same freeze as tennis_dog_t0_gtc_fav_d_sweep_20261030.
Does not retune live B D=0.25 / C_HI=1.05 / E. Does not start a second B.
Does not DailyRun. Does not rewrite dashboard.html. Does not print secrets.
Does not touch leftover Kalshi hist pulls or other running jobs.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from dense_inplay_yes_dip_20261021 import iso_now  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
SWEEP_PY = ROOT / "tools" / "_write_tennis_dog_t0_gtc_fav_d_sweep_20261030.py"
PAGE = STAMP / "tennis_dog_t0_gtc_fav_d_by_decile_20261030.html"
PRIOR = STAMP / "tennis_dog_t0_gtc_fav_d_sweep_20261030.html"
STAMP_SUB = STAMP / "tennis_dog_t0_gtc_fav_d_sweep_20261030"
JSON_OUT = STAMP_SUB / "by_decile.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tennis_dog_t0_gtc_fav_d_by_decile_20261030.html"
)
PRIOR_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tennis_dog_t0_gtc_fav_d_sweep_20261030.html"
)
LIVE_D = 0.25
MATRIX_D = (0.01, 0.05, 0.10, 0.15, 0.25, 0.30, 0.40)
HOUSE_BANDS = ("0-9", "10-19", "20-29", "30-39", "40-49")

ASKED = (
    "Paul follow-up (Fri 30 Oct 2026): OK. what if we measure this by decile bought. "
    "does it make a difference?"
)
PLAIN = (
    "Same test as the tennis underdog-at-start page: buy the cheaper player at first "
    "serve, leave a resting buy on the favorite if they get cheap enough that both "
    "tickets cost less than a dollar by D cents. This page only asks whether the "
    "cheap player’s starting price band — 0–9 cents, 10–19, 20–29, 30–39, 40–49 — "
    "changes the result. Those bands are 10-cent buckets on the cheaper Yes ask "
    "before the shop’s fee (the price you see), same labels as the sport/league "
    "decile sheet. After-fee cash still sets the GTC and the P&L. Quality means "
    "average dollars per match, not how many matches sit in the bucket. Live "
    "Tennis crossover still uses a 25-cent extra-pair dip; we do not change that "
    "from this table."
)


def load_sweep():
    spec = importlib.util.spec_from_file_location("dog_t0_gtc_sweep", SWEEP_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def decile_of(px) -> str | None:
    """T0 Yes in [0.00, 0.10) = 0-9, …, [0.90, 1.00] = 90-99. House labels."""
    if px is None:
        return None
    try:
        p = float(px)
    except (TypeError, ValueError):
        return None
    if p < 0 or p > 1:
        return None
    if p >= 0.90 - 1e-12:
        return "90-99"
    band = int(p * 10.0 + 1e-12)
    lo = band * 10
    return f"{lo}-{lo + 9}"


def band_sort_key(label: str) -> tuple[int, str]:
    try:
        return (int(str(label).split("-", 1)[0]), label)
    except (TypeError, ValueError):
        return (999, label)


def extra_score(sweep, books: list[dict], d: float) -> dict:
    """score_arm plus PF / avg win / avg loss / max DD on the trade list."""
    rec = sweep.score_arm(books, d)
    pnls = []
    for book in books:
        got = (book.get("dips") or {}).get(d) or {}
        if got.get("pnl") is None:
            continue
        pnls.append(float(got["pnl"]))
    wins = [x for x in pnls if x > 1e-12]
    losses = [x for x in pnls if x < -1e-12]
    rec["avg_win"] = (sum(wins) / len(wins)) if wins else None
    rec["avg_loss"] = (sum(losses) / len(losses)) if losses else None
    if losses:
        rec["pf"] = (sum(wins) / abs(sum(losses))) if wins else 0.0
    elif wins:
        rec["pf"] = None
    else:
        rec["pf"] = None
    peak = 0.0
    cum = 0.0
    dd = 0.0
    for x in pnls:
        cum += x
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    rec["max_dd"] = dd if pnls else None
    rec["ann_ror"] = None
    rec["ann_ror_note"] = "n/a — same-day tennis; no days held"
    rec["is_n"] = 0
    rec["oos_n"] = rec["n"]
    return rec


def long_row(sweep, score: dict, band: str) -> dict:
    return {
        "band": band,
        "d": f"{score['d_cents']}¢",
        "n": score["n"],
        "hit": sweep._pct(score["n_hit"], score["n"]),
        "n_lock": score["n_lock"],
        "n_dog": score["n_dog_only"],
        "total": sweep._money(score["total_pnl"]),
        "avg": sweep._money(score["avg_pnl"]),
        "wr": sweep._pct(score["wins"], score["n"]) if score["n"] else "—",
        "pf": f"{score['pf']:.2f}" if score.get("pf") is not None else "—",
        "avg_win": sweep._money(score.get("avg_win")),
        "avg_loss": sweep._money(score.get("avg_loss")),
        "max_dd": sweep._money(score.get("max_dd")),
        "ann": score.get("ann_ror_note") or "n/a — same-day tennis; no days held",
        "note": score.get("note") or "",
        "d_sort": score["d_cents"],
    }


def matrix_cell(score: dict) -> str:
    if not score.get("n"):
        return "—"
    avg = score.get("avg_pnl")
    n = score.get("n")
    if avg is None:
        return f"— (N={n})"
    return f"{avg:+.3f} (N={n})"


def verdict_text(d25: list[dict]) -> tuple[str, str, str, str]:
    """yes/no + why, best band, worst band at D=25 (quality = avg P&L)."""
    ranked = [r for r in d25 if r.get("avg_pnl") is not None and r.get("n")]
    if len(ranked) < 2:
        return "no", "Not enough decile cells with an average to compare.", "", ""
    best = max(ranked, key=lambda r: (r["avg_pnl"], r.get("n") or 0))
    worst = min(ranked, key=lambda r: (r["avg_pnl"], -(r.get("n") or 0)))
    spread = float(best["avg_pnl"]) - float(worst["avg_pnl"])
    ten = next((r for r in ranked if r["band"] == "10-19"), None)
    forty = next((r for r in ranked if r["band"] == "40-49"), None)
    bits = []
    if ten and forty and ten.get("avg_pnl") is not None and forty.get("avg_pnl") is not None:
        bits.append(
            f"At D=25¢, 10–19 avg {ten['avg_pnl']:+.3f} (N={ten['n']}) vs "
            f"40–49 avg {forty['avg_pnl']:+.3f} (N={forty['n']})."
        )
    bits.append(
        f"Best {best['band']} {best['avg_pnl']:+.3f} (N={best['n']}); "
        f"worst {worst['band']} {worst['avg_pnl']:+.3f} (N={worst['n']}); "
        f"spread {spread:+.3f}."
    )
    # Quality difference: more than 2¢ of avg P&L, and not a 1-row toy.
    material = spread >= 0.02 and min(best.get("n") or 0, worst.get("n") or 0) >= 20
    signs = {1 if r["avg_pnl"] > 1e-12 else (-1 if r["avg_pnl"] < -1e-12 else 0) for r in ranked}
    if material or len(signs) > 1:
        yn = "yes"
        why = (
            "Decile changes average dollars, not just head-count. "
            + " ".join(bits)
            + " Still HOLD 25¢ on B — do not pick a live D or a live dog band from this OOS table."
        )
    else:
        yn = "no"
        why = (
            "Deciles do not move average P&L enough to matter (spread under 2¢ on "
            "buckets with N≥20, same sign). "
            + " ".join(bits)
            + " HOLD 25¢ on B."
        )
    any_green = [r for r in ranked if (r.get("avg_pnl") or 0) > 1e-12]
    if any_green:
        why += (
            " A green cell here is still October 2026 out-of-sample (no IS row) — "
            "HOLD, do not retune live E or B."
        )
    return yn, why, best["band"], worst["band"]


def link_prior_page() -> None:
    if not PRIOR.is_file():
        return
    text = PRIOR.read_text(encoding="utf-8")
    needle = PAGE.name
    if needle in text:
        return
    snippet = (
        f'<p class="note">Follow-up: same book sliced by 10¢ dog decile (0–9 … 40–49) is '
        f'<a href="{needle}">{needle}</a>.</p>\n'
    )
    mark = '<h2>1. Primary book'
    if mark in text:
        text = text.replace(mark, snippet + mark, 1)
    else:
        text = text.replace("</h1>", "</h1>\n" + snippet, 1)
    PRIOR.write_text(text, encoding="utf-8")


def build_html(sweep, payload: dict) -> str:
    kn = payload["knobs"]
    d25 = payload["d25"]
    yn = payload["yn"]
    why = payload["why"]
    best = payload["best"]
    worst = payload["worst"]
    freeze_rows = [
        {"k": "Book", "v": "Same primary as tennis_dog_t0_gtc_fav_d_sweep_20261030: tennis T0 dog < 50¢, skip-if-B off, SIZE=1, no time exit."},
        {"k": "Decile", "v": "House 10¢ bands on the T0 cheaper Yes ASK before fee: [0.00,0.10)=0–9, [0.10,0.20)=10–19, … [0.40,0.50)=40–49. After-fee cash is for GTC/P&L only."},
        {"k": "Formula", "v": sweep.formula_text()},
        {"k": "IS / OOS", "v": "No IS (entry_date < 2024-01-01 N=0). Whole October 2026 tape is OOS. Ann ROR omitted — same-day tennis, no days held."},
        {"k": "Live B / E", "v": f"D={kn.get('b_d')} C_HI={kn.get('b_c_hi')} E=({kn.get('e_dog_lo')},{kn.get('e_dog_hi')}). Unchanged={kn.get('unchanged')}."},
        {"k": "Live D", "v": "Do not pick a live D or a live dog band from this table. HOLD 25¢ on B."},
    ]
    long_headers = [
        ("Decile", "text"), ("D", "text"), ("N", "num"), ("Dip-hit %", "num"),
        ("Lock N", "num"), ("Dog-only N", "num"), ("With-fee total P&L", "num"),
        ("Avg with-fee P&L", "num"), ("Win %", "num"), ("Profit factor", "num"),
        ("Avg win", "num"), ("Avg loss", "num"), ("Max DD $", "num"),
        ("Ann ROR", "text"), ("Note", "text"),
    ]
    long_fields = [
        "band", "d", "n", "hit", "n_lock", "n_dog", "total", "avg", "wr",
        "pf", "avg_win", "avg_loss", "max_dd", "ann", "note",
    ]
    d25_headers = [
        ("Decile", "text"), ("N", "num"), ("Dip-hit %", "num"), ("Lock N", "num"),
        ("Dog-only N", "num"), ("With-fee total P&L", "num"), ("Avg with-fee P&L", "num"),
        ("Win %", "num"), ("Profit factor", "num"), ("Avg win", "num"),
        ("Avg loss", "num"), ("Max DD $", "num"), ("Note", "text"),
    ]
    d25_fields = [
        "band", "n", "hit", "n_lock", "n_dog", "total", "avg", "wr",
        "pf", "avg_win", "avg_loss", "max_dd", "note",
    ]
    matrix_headers = [("Decile", "text")] + [(f"D={int(d*100)}¢ avg (N)", "num") for d in MATRIX_D]
    matrix_fields = ["band"] + [f"c{int(d*100)}" for d in MATRIX_D]
    kpi = [
        ("Does decile matter?", yn.upper()),
        ("Best at D=25¢", best or "—"),
        ("Worst at D=25¢", worst or "—"),
        ("N primary", str(payload.get("n_primary") or 0)),
        ("Live B/E unchanged", "yes" if kn.get("unchanged") else "CHECK"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-label">{esc(a)}</div>'
        f'<div class="kpi-value">{esc(b)}</div></div>'
        for a, b in kpi
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis T0 dog + GTC fav — by decile 2026-10-30</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.hl {{ background: #fef9c3; border: 1px solid #eab308; padding: 10px 12px; margin: 0 0 1rem; }}
.ok {{ background: #ecfdf5; border: 1px solid #34d399; padding: 10px 12px; margin: 0 0 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
.kpi-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 1rem; }}
.kpi {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 10px 12px; min-width: 9rem; }}
.kpi-label {{ font-size: 0.78rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.03em; }}
.kpi-value {{ font-size: 1.25rem; font-weight: 650; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Tennis T0 dog + GTC favorite — by decile bought</h1>
<p class="tiny">Written {esc(payload.get("written_at"))}. Click column headers to sort.
Parent sweep: <a href="{esc(PRIOR.name)}">{esc(PRIOR.name)}</a>. Path: {esc(FILE_URL)}</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<strong>Does decile matter?</strong> {esc(yn.upper())}. {esc(why)}
</div>

<div class="ok">
<strong>Live B and E were left unchanged.</strong>
B D stays {esc(kn.get("b_d"))} (HOLD 25¢). C_HI stays {esc(kn.get("b_c_hi"))}.
E stays exclusive ({esc(kn.get("e_dog_lo"))}, {esc(kn.get("e_dog_hi"))}).
Did not start a second B. Did not DailyRun. Did not rewrite dashboard.html.
Do not pick a live D from this table. If a bucket looks green, it is still OOS — HOLD, not retune.
</div>

<div class="kpi-row">{kpi_html}</div>

<p class="note">Decile is the T0 cheaper named Yes <strong>ask before fee</strong>
(house <code>decile_of</code>: 0–9 = [0.00, 0.10), 10–19 = [0.10, 0.20), …).
After-fee cash still builds the GTC and the with-fee P&amp;L.
{esc(payload.get("fee_shift_note") or "")}
Parent N={esc(payload.get("n_primary"))} settled venue books. Skip-if-B off.
Annualized rate of return (Ann ROR) is omitted: same-day tennis, no days held.
In-sample (entry before 2024-01-01) N=0; this tape is all out-of-sample.</p>

<h2>1. Matrix — avg with-fee P&amp;L (N) by decile × D</h2>
<p class="note">Cell is average dollars per match at that D, with the bucket’s N in parentheses.
Paul’s D list is the columns. Nearby cents (2, 3, 4, 20, 35) are in the long table below.</p>
{sweep.table(matrix_headers, payload["matrix_rows"], matrix_fields)}

<h2>2. D=25¢ by decile (headline next to live B, not a retune)</h2>
{sweep.table(d25_headers, payload["d25_rows"], d25_fields)}

<h2>3. Every decile × D</h2>
<p class="note">Canonical extras that apply on this same-day book: profit factor, average win,
average loss, max drawdown on the listed sequence. Ann ROR is n/a. Total P&amp;L stays
because this experiment asked for with-fee total and average.</p>
{sweep.table(long_headers, payload["long_rows"], long_fields)}

<h2>4. Freeze</h2>
{sweep.table([("Knob", "text"), ("Freeze", "text")], freeze_rows, ["k", "v"])}

<p class="tiny">Sources: <code>tools/_write_tennis_dog_t0_gtc_fav_d_by_decile_20261030.py</code>
reusing <code>load_primary_books</code> from the 30 Oct D-sweep.
Parent: <a href="{esc(PRIOR_URL)}">{esc(PRIOR_URL)}</a>.
Did not print secrets. Did not commit.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def main() -> int:
    sweep = load_sweep()
    sweep.self_check()
    knobs = sweep.live_knobs()
    print(f"live knobs {knobs}", flush=True)
    books, meta = sweep.load_primary_books()
    primary = sweep.slice_books(books, "primary")
    for book in primary:
        book["decile"] = decile_of(book.get("dog_px"))
        book["decile_after_fee"] = decile_of(book.get("dog_cash"))
    n_shift = sum(
        1 for b in primary
        if b.get("decile") and b.get("decile_after_fee") and b["decile"] != b["decile_after_fee"]
    )
    fee_shift_note = (
        f"{n_shift} of {len(primary)} books would change bucket if we had used after-fee "
        f"cash instead of the ask. This page stays on the ask."
    )
    bags: dict[str, list] = defaultdict(list)
    for book in primary:
        bags[book.get("decile") or "unknown"].append(book)
    bands = [b for b in HOUSE_BANDS if b in bags]
    extra = sorted((b for b in bags if b not in HOUSE_BANDS), key=band_sort_key)
    ordered = bands + extra

    long_rows = []
    cells = {}
    d25_scores = []
    for band in ordered:
        group = bags[band]
        for d in sweep.D_CENTS:
            sc = extra_score(sweep, group, d)
            sc["band"] = band
            cells[(band, d)] = sc
            long_rows.append(long_row(sweep, sc, band))
        d25_scores.append({**cells[(band, LIVE_D)], "band": band})

    d25_rows = []
    for sc in d25_scores:
        row = long_row(sweep, sc, sc["band"])
        d25_rows.append(row)

    matrix_rows = []
    for band in ordered:
        row = {"band": band}
        for d in MATRIX_D:
            row[f"c{int(d*100)}"] = matrix_cell(cells[(band, d)])
        matrix_rows.append(row)

    yn, why, best, worst = verdict_text(d25_scores)
    payload = {
        "written_at": iso_now(),
        "knobs": knobs,
        "n_primary": len(primary),
        "n_dog_books": meta.get("n_dog_books"),
        "fee_shift_note": fee_shift_note,
        "n_fee_shift": n_shift,
        "yn": yn,
        "why": why,
        "best": best,
        "worst": worst,
        "d25": d25_scores,
        "d25_rows": d25_rows,
        "matrix_rows": matrix_rows,
        "long_rows": long_rows,
        "bands": ordered,
        "band_n": {b: len(bags[b]) for b in ordered},
    }
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    html = build_html(sweep, payload)
    if "dashboard.html" in PAGE.name:
        raise SystemExit("refusing to write dashboard.html")
    PAGE.write_text(html, encoding="utf-8")
    slim = {
        "written_at": payload["written_at"],
        "decile_on": "t0_dog_yes_ask_before_fee",
        "n_primary": len(primary),
        "n_fee_shift": n_shift,
        "yn": yn,
        "why": why,
        "best_d25": best,
        "worst_d25": worst,
        "knobs": knobs,
        "live_b_e_unchanged": knobs["unchanged"],
        "hold_b_d": 0.25,
        "d25": [
            {
                "band": s["band"],
                "n": s["n"],
                "hit_pct": s.get("hit_pct"),
                "n_lock": s.get("n_lock"),
                "n_dog_only": s.get("n_dog_only"),
                "total_pnl": s.get("total_pnl"),
                "avg_pnl": s.get("avg_pnl"),
                "win_pct": s.get("win_pct"),
                "pf": s.get("pf"),
            }
            for s in d25_scores
        ],
        "matrix": {
            band: {
                f"d{int(d*100)}": {
                    "n": cells[(band, d)]["n"],
                    "avg_pnl": cells[(band, d)]["avg_pnl"],
                    "hit_pct": cells[(band, d)]["hit_pct"],
                }
                for d in MATRIX_D
            }
            for band in ordered
        },
        "page": str(PAGE),
        "parent": str(PRIOR),
    }
    JSON_OUT.write_text(json.dumps(slim, indent=2, default=str) + "\n", encoding="utf-8")
    link_prior_page()
    print(f"wrote {PAGE}", flush=True)
    print(f"DECILE matter={yn} best={best} worst={worst} N={len(primary)}", flush=True)
    print(why, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
