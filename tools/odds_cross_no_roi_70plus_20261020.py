"""No-bet ROI the first time a moneyline Yes is listed at 70% or above.

Research only. Reuses the odds-cross decade tape and official settlements.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not restart jobs.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from odds_cross_no_roi_60_70_20261020 import (
    SLICE_FIELDS,
    SLICE_HEADERS,
    annotate_crosses,
    as_float,
    backfill_starts,
    copy_g,
    esc,
    fmt_px,
    fmt_signed_pct,
    kalshi_fee,
    pct,
    summarize,
    summary_row,
    table,
    trade_from,
)
from odds_cross_winrate_20261020 import (
    PAGE as PARENT_PAGE,
    SETTLE_CACHE,
    STAMP,
    attach_results,
    build_index,
    load_decade_cache,
    load_stream_cache,
)
from prediction_paths import RAW_DIR as RAW
PAGE = STAMP / "odds_cross_no_roi_70plus_20261020.html"
JSON_OUT = RAW / "odds_cross_no_roi_70plus_20261020.json"
CSV_OUT = RAW / "odds_cross_no_roi_70plus_20261020.csv"
ET = ZoneInfo("America/New_York")

ASKED = (
    "thanks. for any of the moneyline bets any event that is 70 or greater seems to have a "
    "fairly significant chance of losing. what if we took a no bet for any event listed at 70 "
    "or above. what would our return be?"
)
PLAIN = (
    "A prediction-market Yes price is a dollar from 0 to 1, also read as an implied chance: "
    "0.70 means the venue is pricing that named side at 70 percent. This page is moneyline "
    "only (who wins the game). The first time a side’s Yes price is listed at 70 percent or "
    "higher (greater than or equal to 0.70, inclusive), we buy No on that same side. No costs "
    "one dollar minus that Yes price. If the named side loses, No pays a dollar. If the named "
    "side wins, No pays nothing and the stake is gone. Each No gets the same one-dollar stake. "
    "Return on investment (ROI) is the average of those trade-by-trade returns. Official win or "
    "loss comes from venue settlement (Kalshi result, Gemini resolution). Games still open are "
    "pending and are left out. This is not the decade-band Yes win-rate table: that table says "
    "how often the favorite won, not what a No bet returned. Research only. Not gold. Not "
    "DailyRun. Not a trading rule."
)

THRESHOLD = 0.70
HIGH_BANDS = ("70–79", "80–89", "90–99")
WINDOW_LO = 15.0
WINDOW_HI = 60.0


def first_hit_per_key(rows: list[dict], *, moneyline_only: bool) -> list[dict]:
    """Keep the first qualifying tick per (game, side, venue) key, stream order."""
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if moneyline_only and row.get("market_type") != "moneyline":
            continue
        key = row.get("key") or ""
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def moneyline_high_prints(rows: list[dict], bands: tuple[str, ...] | None = None) -> list[dict]:
    out = []
    for row in rows:
        if row.get("market_type") != "moneyline":
            continue
        if bands is not None and (row.get("band") or "") not in bands:
            continue
        px = as_float(row.get("first_above"))
        if px is None or px < THRESHOLD or px >= 1.0:
            continue
        out.append(row)
    return out


def in_window(row: dict) -> bool:
    minutes = row.get("minutes_num")
    return minutes is not None and WINDOW_LO <= minutes <= WINDOW_HI


def trades_of(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        trade = trade_from(row)
        if trade:
            out.append(trade)
    return out


def load_attached() -> tuple[list[dict], list[dict], dict]:
    stream = load_stream_cache()
    if stream is None:
        raise FileNotFoundError("odds_cross_full_20261020.json missing; parent study cache required")
    decade = load_decade_cache()
    if decade is None:
        raise FileNotFoundError("odds_cross_decade_20261020.json missing; parent decade cache required")
    if not SETTLE_CACHE.is_file():
        raise FileNotFoundError(SETTLE_CACHE)
    first_in_band = list(decade["first_in_band"])
    opener = list(decade["opener"])
    settlements = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
    index = build_index(settlements)
    attach_results(first_in_band, stream["last_map"], settlements, index)
    attach_results(opener, stream["last_map"], settlements, index)
    for rows in (first_in_band, opener):
        for row in rows:
            row["start_source"] = "feed" if row.get("game_start") else ""
        backfill_starts(rows, settlements)
        annotate_crosses(rows)
    meta = {
        "seen_min": stream.get("seen_min") or "",
        "seen_max": stream.get("seen_max") or "",
        "n_yes": stream.get("n_yes"),
        "n_keys": stream.get("n_keys"),
        "n_lines": stream.get("n_lines"),
        "settle_total": len(settlements),
        "kalshi": sum(1 for r in settlements if r.get("venue") == "Kalshi"),
        "gemini": sum(1 for r in settlements if r.get("venue") == "Gemini"),
    }
    return first_in_band, opener, meta


def patch_parent() -> None:
    text = PARENT_PAGE.read_text(encoding="utf-8")
    href = "odds_cross_no_roi_70plus_20261020.html"
    if href in text:
        print("parent already linked; skip patch", flush=True)
        return
    follow_ask = (
        f'<p>Follow-up: for any of the moneyline bets any event that is 70 or greater seems to '
        f'have a fairly significant chance of losing. what if we took a no bet for any event '
        f'listed at 70 or above. what would our return be? See <a href="{href}">No at 70%+</a>.</p>'
    )
    decade_p = (
        "ok. so can we also make the bands 30-39, 40-49, etc. and show the win % based on that</p>"
    )
    if decade_p in text:
        text = text.replace(decade_p, decade_p + "\n" + follow_ask, 1)
    else:
        print("parent What-you-asked decade line not found; skip ask append", flush=True)
    follow_hl = (
        f'<p>Follow-up: buying No the first time a moneyline Yes is listed at 70 or above. '
        f'<a href="{href}">No-bet ROI at 70%+</a> (event-level ROI, not the decade Yes win % table).</p>'
    )
    hl_end = (
        "Decade bands (new, not hysteresis): moneyline win % by first print in 30–39, 40–49, … "
        "is in <a href=\"#decade-bands\">the decade tables</a>. Research only. Not gold. No KEEP.</p>"
    )
    if hl_end in text:
        text = text.replace(hl_end, hl_end + "\n" + follow_hl, 1)
    else:
        print("parent headline box not found; skip one-line add", flush=True)
    PARENT_PAGE.write_text(text, encoding="utf-8")
    print(f"patched {PARENT_PAGE}", flush=True)


def write_html(
    main: dict,
    companions: list[dict],
    primary_partition: list[dict],
    trades: list[dict],
    counts: dict,
    meta: dict,
    now: str,
) -> None:
    settled = [t for t in trades if t.get("official") in ("win", "loss") and t.get("roi") is not None]
    detail = []
    for row in sorted(settled, key=lambda r: r.get("cross_time") or "", reverse=True):
        detail.append({
            "sport": row["sport"],
            "game": row["game"],
            "side": row["side"],
            "venue": row["venue"],
            "band": row.get("band") or "",
            "cross_time": row["cross_time"],
            "game_start": row["game_start"],
            "minutes": row["minutes_into_game"],
            "yes_px": fmt_px(row["yes_price_at_cross"]),
            "no_cost": fmt_px(row["no_cost"]),
            "official": row["official"],
            "no_result": row["no_result"],
            "roi_pct": fmt_signed_pct(row["roi"]),
            "pnl": f"{row['pnl_1_stake']:+.4f}" if row.get("pnl_1_stake") is not None else "",
            "source": row["official_source"],
            "start_source": row["start_source"],
        })
    n = main["n"]
    headline_roi = fmt_signed_pct(main["avg_roi"])
    headline_med = fmt_signed_pct(main.get("median_roi"))
    no_wr = pct(main["no_wins"], n)
    yes_wr = pct(main["yes_wins"], n)
    mean_cost = f"{main['mean_no_cost']:.4f}" if main["mean_no_cost"] is not None else "n/a"
    total_pnl = f"{main['total_pnl_1_stake']:+.2f}" if main["total_pnl_1_stake"] is not None else "n/a"
    unique_games = main.get("unique_games") or 0
    cheap = [t for t in settled if (t.get("no_cost") or 1) < 0.10]
    cheap_wins = [t for t in cheap if t.get("no_result") == "win"]
    cheap_sum = sum(t["roi"] for t in cheap_wins) if cheap_wins else 0.0
    rest = [t for t in settled if (t.get("no_cost") or 0) >= 0.10]
    rest_mean = (sum(t["roi"] for t in rest) / len(rest)) if rest else None
    skew_note = (
        f"Cheap Nos dominate the mean: {len(cheap)} of {n} settled trades cost under 10 cents; "
        f"the {len(cheap_wins)} that won contribute {fmt_signed_pct(cheap_sum / n if n else None)} "
        f"percentage points of the {headline_roi}% average (they are {cheap_sum:+.1f} on the $1-stake sum). "
        f"On the {len(rest)} trades with No cost of 0.10 or more, average ROI is {fmt_signed_pct(rest_mean)}% "
        f"and the median is still a full loss. Soccer moneyline here includes three-way books "
        f"(home / away / Tie), so both named teams can lose on a draw."
    )
    fee_line = "Fees are not subtracted in the primary table. "
    if main["avg_roi_kalshi_fee_all"] is not None and n:
        fee_line += (
            f"Sensitivity: if every No paid the Kalshi sports formula "
            f"0.07 × price × (1 − price) rounded to $0.0001, average ROI would be "
            f"{fmt_signed_pct(main['avg_roi_kalshi_fee_all'])}% on the same {n} trades."
        )
    else:
        fee_line += "Kalshi-style fee sensitivity could not be computed on this slice."

    arith = (
        "Threshold is inclusive: first Yes print with price ≥ 0.70. One row per (game, side, venue) "
        "at that first 70+ print. No cost = 1 − yes_price_at_that_print. Equal stake $1 on each No: "
        "if the named side loses, No pays $1 and ROI = (1 / no_cost) − 1; if the named side wins, "
        "No pays $0 and ROI = −1. Average ROI is the mean of those per-trade ROIs. Median ROI is "
        "the middle trade. Total dollars with $1 No each is the sum of those ROIs (same as N × "
        "average ROI)."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>No-bet ROI the first time a moneyline is 70 or above</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Buying No the first time a moneyline is listed at 70% or above</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Slice of <a href="odds_cross_winrate_20261020.html">odds-cross win rates</a>. Same official-settlement tape (about 17–20 Oct 2026, Kalshi / Gemini).</p>
<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Definition</h2>
<ul>
<li><strong>Event:</strong> moneyline (who wins). First time the named side’s Yes price is <em>greater than or equal to 0.70</em> (inclusive). One row per (game, side, venue) at that first 70+ print. Later ticks on the same contract are ignored.</li>
<li><strong>Bet:</strong> buy No on that same side at that print. No cost = 1 − yes_price_at_that_print.</li>
<li><strong>Payoff and ROI:</strong> {esc(arith)}</li>
<li><strong>Settlements:</strong> official Kalshi <code>result</code> / Gemini <code>resolutionSide</code> only, same matcher as the parent study. Pending markets are labeled and excluded from ROI. A last print at 99 cents is not used as a result.</li>
<li><strong>Fees:</strong> primary table without fees.</li>
</ul>
<p class="note">Acronyms: ROI is return on investment. ATP is Association of Tennis Professionals. NHL is National Hockey League. NFL is National Football League. MLB is Major League Baseball. NBA is National Basketball Association. WTA is Women’s Tennis Association.</p>
<p class="note"><strong>Not the decade Yes win % table.</strong> The parent 70–79 / 80–89 / 90–99 rows are how often the named side later settled Yes. That is not ROI. This page rebuilds each trade’s No cost from the Yes price at the first 70+ print, then scores official win/loss. Cheap Nos (a 0.95 Yes is a 5-cent No) can return many times the stake if they hit, so the mean can look better than the typical trade. Read the median.</p>

<div class="hl">
<p><strong>Headline, moneyline first Yes ≥ 0.70, official settlements, No bet, no fees:</strong>
N = {n} settled rows ({unique_games} unique games), No win rate {esc(no_wr)}% ({main['no_wins']} No wins / {n} settled), Yes-side win rate {esc(yes_wr)}%,
average ROI {esc(headline_roi)}%, median ROI {esc(headline_med)}%, mean No cost {esc(mean_cost)},
total $ if $1 No each {esc(total_pnl)}. {esc(main['note'] or '')}</p>
<p>Average ROI is the equal-stake mean. Same game can appear once per venue, so N is not unique matches. {esc(skew_note)} Research only. Not gold.</p>
</div>

<h2>Sample and honesty</h2>
<p>Live tape is about 17–20 Oct 2026 (first Yes quote {esc(meta.get('seen_min') or '')}, last {esc(meta.get('seen_max') or '')}). There is no in-sample / out-of-sample split to report: almost every first print is after 2024-01-01, and the tape does not go back years. If N is small, do not read this as a trading rule. Nothing here is KEEP, gold, or DailyRun.</p>
<p>Moneyline (game, side, venue) contracts that ever printed Yes ≥ 0.70: {counts['n_first70']}. Settled: {counts['n_first70_settled']}. Pending (excluded from ROI): {counts['n_first70_pending']}. Official settlements in the parent cache: Kalshi {meta.get('kalshi', 0):,}; Gemini {meta.get('gemini', 0):,}; unique after merge {meta.get('settle_total', 0):,}.</p>
<p>Known start and first 70+ print inside [15, 60] minutes inclusive: {counts['n_window']} ({counts['n_window_settled']} settled, {counts['n_window_pending']} pending). Unknown start is excluded from that companion, not dumped into the window. Tennis often has no commence time in the feed; some starts are occurrence-datetime backfill, same as the parent study.</p>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>

<h2>Arithmetic (quoted)</h2>
<p>{esc(arith)} Example: first 70+ Yes print is 0.72, so No costs 0.28. If that side loses, ROI = (1 / 0.28) − 1 = +257.1%. If that side wins, ROI = −100%. Average ROI is the equal-weight mean of those percents, not a dollar-weighted pool.</p>

<h2>Primary slice: first moneyline Yes ≥ 0.70, buy No</h2>
{table(SLICE_HEADERS, [summary_row(main)], SLICE_FIELDS)}

<h2>Companion: opener already ≥ 0.70</h2>
<p class="note">First Yes print of the whole series (not a later climb). If the opener is already 70 or above, that print is the No. A side that opens at 0.55 and later prints 0.72 is in the primary table, not here.</p>
{table(SLICE_HEADERS, [summary_row(s) for s in companions[:1]], SLICE_FIELDS)}

<h2>Companion: first-in-band 70–79 vs 80–89 vs 90–99</h2>
<p class="note">No at the first Yes print that actually sits inside that decade (70–79 is 0.70 ≤ price &lt; 0.80, and so on). A side can appear in more than one row if it later prints in a higher decade. That is not the same as the primary “first ever 70+” row: a jump from 0.65 to 0.85 is primary 80–89 and does not appear in 70–79.</p>
{table(SLICE_HEADERS, [summary_row(s) for s in companions[1:4]], SLICE_FIELDS)}

<h2>Companion: first 70+ print 15–60 minutes after start</h2>
<p class="note">Same primary event (first Yes ≥ 0.70), but only when listed start is known and (print time − start) is in [15, 60] minutes inclusive. Small N is expected. Unknown start is excluded.</p>
{table(SLICE_HEADERS, [summary_row(s) for s in companions[4:]], SLICE_FIELDS)}

<h2>Where the first 70+ print landed</h2>
<p class="note">Partition of the primary slice by the decade of that first ≥ 0.70 print. Each (game, side, venue) is in exactly one row here.</p>
{table(SLICE_HEADERS, [summary_row(s) for s in primary_partition], SLICE_FIELDS)}

<h2>Primary slice by sport</h2>
{table(
    [
        ("Sport", "text"), ("Settled N", "num"), ("No wins", "num"), ("Yes-side wins", "num"),
        ("No win %", "num"), ("Yes-side win %", "num"), ("Avg ROI %", "num"),
        ("Mean No cost", "num"), ("Total $ ($1 No each)", "num"), ("Note", "text"),
    ],
    main["by_sport"],
    ["sport", "n", "no_wins", "yes_wins", "no_win_pct", "yes_win_pct",
     "avg_roi_pct", "mean_no_cost", "total_pnl_1_stake", "note"],
)}

<h2>Primary slice by venue</h2>
<p class="note">Novig is a quote venue. Official result is the same game/side on Kalshi or Gemini when that match exists.</p>
{table(
    [
        ("Venue", "text"), ("Settled N", "num"), ("No wins", "num"), ("Yes-side wins", "num"),
        ("No win %", "num"), ("Yes-side win %", "num"), ("Avg ROI %", "num"),
        ("Mean No cost", "num"), ("Total $ ($1 No each)", "num"), ("Note", "text"),
    ],
    main["by_venue"],
    ["venue", "n", "no_wins", "yes_wins", "no_win_pct", "yes_win_pct",
     "avg_roi_pct", "mean_no_cost", "total_pnl_1_stake", "note"],
)}

<h2>Fees</h2>
<p>{esc(fee_line)}</p>

<h2>Event rows (primary slice, settled only)</h2>
<p class="note">One row per (game, side, venue) at the first Yes ≥ 0.70. Official win means the named side won (No lost). Official loss means the named side lost (No won).</p>
{table(
    [
        ("Sport", "text"), ("Game", "text"), ("Side", "text"), ("Venue", "text"),
        ("First 70+ decade", "text"), ("Print time", "date"), ("Game start", "date"),
        ("Minutes in", "num"), ("Yes at first 70+", "num"), ("No cost", "num"),
        ("Official (Yes side)", "text"), ("No result", "text"), ("ROI %", "num"),
        ("$ PnL ($1 No)", "num"), ("Official source", "text"), ("Start source", "text"),
    ],
    detail,
    [
        "sport", "game", "side", "venue", "band", "cross_time", "game_start",
        "minutes", "yes_px", "no_cost", "official", "no_result", "roi_pct",
        "pnl", "source", "start_source",
    ],
)}

<p class="note">Rows saved as <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/odds_cross_no_roi_70plus_20261020.csv</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def slim(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("by_sport", "by_venue")}


def main() -> None:
    now = datetime.now(ET).isoformat()
    first_in_band, opener, meta = load_attached()

    high = moneyline_high_prints(first_in_band, HIGH_BANDS)
    primary_rows = first_hit_per_key(high, moneyline_only=True)
    for row in primary_rows:
        row["defn"] = "first_70plus"

    opener_high = first_hit_per_key(moneyline_high_prints(opener, HIGH_BANDS), moneyline_only=True)
    for row in opener_high:
        row["defn"] = "opener_70plus"

    band_rows = {
        band: moneyline_high_prints(first_in_band, (band,))
        for band in HIGH_BANDS
    }
    window_rows = [r for r in primary_rows if in_window(r)]

    primary_trades = trades_of(primary_rows)
    main_sum = summarize(primary_trades, "First moneyline Yes ≥ 0.70, buy No")

    companions = [
        summarize(trades_of(opener_high), "Opener already ≥ 0.70, buy No"),
        summarize(trades_of(band_rows["70–79"]), "First-in-band 70–79, buy No"),
        summarize(trades_of(band_rows["80–89"]), "First-in-band 80–89, buy No"),
        summarize(trades_of(band_rows["90–99"]), "First-in-band 90–99, buy No"),
        summarize(trades_of(window_rows), "First Yes ≥ 0.70, 15–60m after start"),
    ]
    primary_partition = [
        summarize(
            trades_of([r for r in primary_rows if r.get("band") == band]),
            f"First 70+ print landed in {band}",
        )
        for band in HIGH_BANDS
    ]

    counts = {
        "n_first70": len(primary_rows),
        "n_first70_settled": sum(1 for r in primary_rows if r.get("official") in ("win", "loss")),
        "n_first70_pending": sum(1 for r in primary_rows if r.get("official") == "pending"),
        "n_window": len(window_rows),
        "n_window_settled": sum(1 for r in window_rows if r.get("official") in ("win", "loss")),
        "n_window_pending": sum(1 for r in window_rows if r.get("official") == "pending"),
        "n_opener": len(opener_high),
        "n_band_70": len(band_rows["70–79"]),
        "n_band_80": len(band_rows["80–89"]),
        "n_band_90": len(band_rows["90–99"]),
    }

    payload = {
        "written_at": now,
        "asked": ASKED,
        "threshold": "yes_price >= 0.70 inclusive",
        "window_minutes": [WINDOW_LO, WINDOW_HI],
        "arithmetic": (
            "no_cost = 1 - yes_price_at_first_70plus; "
            "if side loses (No wins): ROI = (1 / no_cost) - 1; "
            "if side wins (No loses): ROI = -1; "
            "average ROI = mean of per-trade ROIs with $1 No stake"
        ),
        "counts": counts,
        "meta": meta,
        "primary": slim(main_sum),
        "companions": [slim(s) for s in companions],
        "primary_partition": [slim(s) for s in primary_partition],
        "by_sport": main_sum["by_sport"],
        "by_venue": main_sum["by_venue"],
        "trades": primary_trades,
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {JSON_OUT}", flush=True)

    if primary_trades:
        fieldnames = list(primary_trades[0].keys())
        with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(primary_trades)
        print(f"wrote {CSV_OUT}", flush=True)

    write_html(main_sum, companions, primary_partition, primary_trades, counts, meta, now)
    patch_parent()
    copy_g(PAGE)
    copy_g(PARENT_PAGE)

    print(
        f"PRIMARY N={main_sum['n']} no_wr={main_sum['no_win_rate']} "
        f"avg_roi={main_sum['avg_roi']} median_roi={main_sum.get('median_roi')} "
        f"mean_no_cost={main_sum['mean_no_cost']} unique_games={main_sum.get('unique_games')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
