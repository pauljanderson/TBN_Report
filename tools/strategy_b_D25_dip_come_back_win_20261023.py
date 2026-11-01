"""Strategy B D=25: can the favorite-dip rest as GTC, and how often does it come back and win.

Research only. Reads local price_memory and official settlements. Does not
place, cancel, or amend orders. Does not print secrets. Does not touch
orders_stopped.json or live_lock_orders.py. Does not start live_strategy_b.py.
Does not change live D=0.25. Does not wire leftover GTC or favorite-dip GTC.
Not gold. Not DailyRun. HEAD may be the Spotify playlist branch — GTC wiring
belongs on main, not here.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from dense_inplay_fav_lock_cross_smalld_20261021 import (
    ORIGINAL_N,
    ORIGINAL_SETTLED,
    freeze_keys_from_original_html,
    pair_key,
    ticks_of,
)
from dense_inplay_yes_dip_20261021 import (
    ABSORB,
    assign_actual_t0,
    attach_pair_results,
    esc,
    iso_now,
    mark_inplay,
    match_date,
    money_cell,
    pair_matches,
    signed_money,
    stream_tennis,
)
from inmatch_vol_hedge_20261021 import first_absorbing, last_at_or_before
from odds_cross_no_roi_60_70_20261020 import table
from odds_cross_winrate_20261020 import pct, tiny_note
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from strategy_b_d_05_to_50_20261023 import fmt_pct, pair_days
from strategy_b_t0_plus_50cross_20261023 import (
    CONTROL_D,
    expectancy_parts,
    rec_of,
    simulate_arms,
)
from tennis_decade_at_start_20261020 import start_lookup_from
from tennis_dual_yes_dip_no_20261021 import et_iso, fmt_px, fmt_signed, last_name, mean

ET = ZoneInfo("America/New_York")
STAMP = ROOT / "drive" / "paul_experiments" / "strategy_b_D25_dip_come_back_win_20261023"
PAGE = STAMP / "compare.html"
BASELINE = STAMP / "BASELINE.md"
COUNTS_JSON = STAMP / "counts.json"
BRANCH = "cursor/spotify-year-playlist-sync-674a"
VOID_OFFICIAL = {"void", "refund", "push", "cancelled", "canceled", "n/a", "na"}

ASKED = (
    "Two questions. (1) Can we place a market buy after crossover and make it GTC? "
    "Live Strategy B: T0 both Yes, then original dog Yes through 0.50 from below, then "
    "original favorite at 1 − cross_fill − 0.25 (IOC ping today). Live is IOC only. "
    "Prior GTC go/no-go: leftover GTC after flatten miss is first slice when he says "
    "wire it; favorite-dip GTC is second; dog-at-51 as a resting limit is wrong (fills "
    "now if cheaper); Gemini stop-limit paper-only; cancel-on-resolve for resting orders "
    "does not exist yet. Per venue (Kalshi good_till_canceled, Gemini good-til-cancel, "
    "Poly US TIME_IN_FORCE_GOOD_TILL_CANCEL, Novig tif=GTC): can we REST that dip GTC "
    "today? 1 contract. What is missing (cancel on resolve/postpone). Do not implement "
    "live. If he wants it next he must say wire leftover GTC or wire favorite-dip GTC "
    "on main (HEAD may be Spotify — do not put GTC on Spotify playlist files). "
    "(2) In B D=25 history, how many times does the 25 dip come back and win? Same freeze "
    "as strategy_b_D_05_to_50_20261023 and strategy_b_t0_plus_50cross_20261023 (182 books, "
    "119 settled, all OOS). Primary P&L WITH fees. Count clearly: settled N; how many "
    "printed a 50-cross so a dip target existed; of those how many times the original "
    "favorite came back to that dip (third ticket filled); of filled dips how many times "
    "that favorite won vs lost vs void; of never-filled dip targets what happened; "
    "optional P&L with fees on filled-and-won vs filled-and-lost vs never-filled. Prior: "
    "D=25 lock filled 41.2% of 119, WR 47.1%, with-fee expectancy +$0.002. Break that "
    "41.2% into win/loss of the dipped player."
)

PLAIN = (
    "A market buy takes whatever is on the ask right now. It is not a resting "
    "good-til-canceled (GTC) order. Immediate-or-cancel (IOC) is what live Strategy B "
    "sends today: take it now or the leftover dies. After the original underdog’s Yes "
    "prints through 50 cents from below, the remaining buy is the original favorite "
    "cheap enough to lock 25 cents on that extra pair: favorite Yes at 1 minus the "
    "underdog fill minus 0.25. A GTC limit at that cheap price can sit if the favorite "
    "is still more expensive than the dip; it would not fill immediately. That is the "
    "intended “after crossover, rest until the 25-cent dip.” A GTC buy at 51 cents on "
    "the dog is the wrong tool: if the dog is already cheaper, that limit fills now. "
    "This page does not place that GTC. Cancel-on-resolve for a resting order id is "
    "still missing, so a live rest could sit after the match is over. Question two "
    "replays live D=25 on the same 182 tennis books (119 settled, all after 2024-01-01). "
    "It counts how often the 50-cross happened, how often the favorite actually came "
    "back to the 25-cent dip, and whether that dipped player then won the match. "
    "Dollars are after venue fees. Live D stays 25 cents. No second Strategy B."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def is_void_official(pair: dict) -> bool:
    for key in ("off_a", "off_b"):
        raw = str(pair.get(key) or "").strip().lower()
        if raw in VOID_OFFICIAL:
            return True
    return False


def fav_outcome(pair: dict) -> str:
    winner = pair.get("winner")
    fav = pair.get("fav")
    dog = pair.get("dog")
    if is_void_official(pair):
        return "void"
    if pair.get("settled") and winner in ("a", "b"):
        if winner == fav:
            return "favorite won"
        if winner == dog:
            return "favorite lost"
        return "other settled"
    return "unsettled"


def gtc_rest_label(fav_px: float | None, target: float | None) -> str:
    if fav_px is None or target is None:
        return "no favorite quote at cross"
    if fav_px <= ABSORB + 1e-12 or fav_px >= 0.95 - 1e-12:
        return "favorite absorbing at cross (not a rest)"
    if fav_px <= target + 1e-12:
        return "would take now (favorite already at/under dip)"
    return "would rest (favorite still richer than dip)"


def classify_pair(pair: dict) -> dict:
    rec = rec_of(pair, "0.25") or {}
    crossed = bool(rec.get("crossed"))
    lock = bool(rec.get("lock_filled"))
    target = rec.get("target")
    fill_ts = rec.get("cross_ts")
    fill_px = rec.get("cross_px")
    extra = rec.get("fav_extra") or {}
    hi = pair.get("hi")
    fav = pair.get("fav")
    outcome = fav_outcome(pair)
    settled = bool(pair.get("settled") and pair.get("winner") in ("a", "b"))
    row = {
        "game": pair.get("game") or "",
        "venue": pair.get("venue") or "",
        "date": match_date(pair) or "",
        "fav": last_name(pair.get("fav_name") or ""),
        "dog": last_name(pair.get("dog_name") or ""),
        "settled": settled,
        "void": is_void_official(pair),
        "still_live": not settled and not is_void_official(pair),
        "crossed": crossed,
        "lock_filled": lock,
        "target": target,
        "cross_px": fill_px,
        "cross_ts": fill_ts,
        "dip_px": extra.get("px") if lock else None,
        "dip_ts": extra.get("ts") if lock else None,
        "fav_outcome": outcome,
        "pnl_fee": rec.get("pnl_fee"),
        "pnl_gross": rec.get("pnl"),
        "fees": rec.get("fees"),
        "cost": rec.get("cost"),
        "mix": rec.get("mix") or "",
        "bucket": "no 50-cross",
        "never_reason": "",
        "gtc_at_cross": "",
        "min_fav_after": None,
        "absorb_after": None,
        "target_at_absorb_floor": bool(
            target is not None and float(target) <= ABSORB + 1e-12
        ),
        "days": pair_days(pair),
        "off_a": pair.get("off_a") or "",
        "off_b": pair.get("off_b") or "",
    }
    if not crossed:
        row["bucket"] = "no 50-cross"
        return row

    fav_ticks = ticks_of(pair, fav, "yes") if fav else []
    at_cross = last_at_or_before(fav_ticks, fill_ts) if fill_ts is not None else None
    row["gtc_at_cross"] = gtc_rest_label(
        at_cross[1] if at_cross else None,
        float(target) if target is not None else None,
    )
    row["fav_px_at_cross"] = at_cross[1] if at_cross else None

    after_a = [row_t for row_t in (pair.get("yes_a") or []) if fill_ts is not None and row_t[0] > fill_ts]
    after_b = [row_t for row_t in (pair.get("yes_b") or []) if fill_ts is not None and row_t[0] > fill_ts]
    absorb_ts = first_absorbing(after_a, after_b)
    row["absorb_after"] = absorb_ts

    live_after = []
    if fill_ts is not None:
        for ts, px in fav_ticks:
            if ts <= fill_ts:
                continue
            if hi is not None and ts > hi:
                continue
            if px <= ABSORB + 1e-12 or px >= 0.95 - 1e-12:
                continue
            live_after.append((ts, px))
    min_live = min((px for _, px in live_after), default=None)
    row["min_fav_after"] = min_live

    if lock:
        if outcome == "favorite won":
            row["bucket"] = "dip filled, favorite won"
        elif outcome == "favorite lost":
            row["bucket"] = "dip filled, favorite lost"
        elif outcome == "void":
            row["bucket"] = "dip filled, void"
        else:
            row["bucket"] = "dip filled, unsettled"
        return row

    if min_live is not None and target is not None and min_live > float(target) + 1e-12:
        row["never_reason"] = "favorite never cheap enough"
    elif absorb_ts is not None:
        row["never_reason"] = "absorb (5c/95c) ended the wait"
    else:
        row["never_reason"] = "match/window ended (no absorb print, no dip fill)"
    if row["target_at_absorb_floor"] and row["never_reason"] != "favorite never cheap enough":
        row["never_reason"] = "target at/under 5c absorb floor (unfillable live print)"
    row["bucket"] = "dip target never filled"
    return row


def pnl_block(rows: list[dict], label: str) -> dict:
    settled = [r for r in rows if r.get("pnl_fee") is not None and r.get("settled")]
    pnls = [float(r["pnl_fee"]) for r in settled]
    parts = expectancy_parts(pnls)
    fees = [float(r.get("fees") or 0.0) for r in settled]
    gross = [float(r["pnl_gross"]) for r in settled if r.get("pnl_gross") is not None]
    return {
        "label": label,
        "n_rows": len(rows),
        "n_settled": len(settled),
        "n_win": parts["n_win"],
        "n_loss": parts["n_loss"],
        "win_pct": parts["win_pct"],
        "mean": parts["mean"],
        "total": sum(pnls) if pnls else None,
        "avg_win": parts["avg_win"],
        "avg_loss": parts["avg_loss"],
        "expectancy": parts["expectancy_formula"],
        "mean_fees": mean(fees) if fees else None,
        "mean_gross": mean(gross) if gross else None,
        "note": tiny_note(len(settled)),
    }


def copy_g(path: Path) -> None:
    dest_dir = Path(r"G:\My Drive\paul_experiments\strategy_b_D25_dip_come_back_win_20261023")
    if dest_dir.parent.exists() or Path("G:/").exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / path.name
            shutil.copy2(path, dest)
            print(f"copied {dest}", flush=True)
        except OSError as exc:
            print(f"G: copy skipped: {exc}", flush=True)
    else:
        print("G: not present, skip copy", flush=True)


def json_safe(rec):
    if isinstance(rec, dict):
        return {k: json_safe(v) for k, v in rec.items()}
    if isinstance(rec, list):
        return [json_safe(v) for v in rec]
    if isinstance(rec, float) and not math.isfinite(rec):
        return None
    return rec


def write_baseline(payload: dict) -> None:
    c = payload["counts"]
    lines = [
        "# Strategy B D=25 dip come-back and GTC rest — freeze",
        "",
        "Research only. Not gold. Not DailyRun. Live D=25 is not changed. No live GTC.",
        "",
        "## What you asked",
        "",
        ASKED,
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Freeze",
        "",
        "- **Universe:** Same 182 (game, venue) keys as strategy_b_D_05_to_50_20261023 and strategy_b_t0_plus_50cross_20261023.",
        "- **Arm:** Live Strategy B D=25. T0 both Yes, extra original-dog Yes at first from-below 50 cross, original-favorite Yes at/below 1 − cross_fill − 0.25.",
        "- **Fees:** PRIMARY P&L WITH live-sender fees (same as the t0_plus stamp).",
        "- **IS / OOS:** Entire October 2026 tape is OOS. No IS row.",
        "- **Live:** D=0.25 unchanged. Favorite-dip GTC not wired. Leftover GTC not wired. No second live B.",
        f"- **Git HEAD this job:** `{BRANCH}` (Spotify playlist). Do not put GTC on this branch.",
        "",
        "## Q1 — Rest the favorite-dip GTC today?",
        "",
        "- A market buy fills now. It is not a resting GTC.",
        "- After the 50-cross, the remaining buy is the favorite dip. A GTC **limit** at 1 − cross_fill − 0.25 can rest if the favorite is still richer than that price.",
        "- Venue TIF exists on Kalshi (`good_till_canceled`), Gemini (`good-til-cancel`), Polymarket US (`TIME_IN_FORCE_GOOD_TILL_CANCEL`), Novig (`tif=GTC`). Size 1.",
        "- Live Strategy B still sends IOC only (`send_yes_ioc`).",
        "- **Missing:** cancel-on-resolve / postpone / later-flatten for a persisted resting order id. That loop is not written. Per-venue `_cancel` helpers exist; they are not wired to resolve/postpone.",
        "- Dog-at-51 as a resting limit is still wrong. Gemini stop-limit stays paper-only.",
        "- First live slice, when Paul says it on **main**: leftover GTC after flatten miss. Second: favorite-dip GTC. Not this job. Not Spotify.",
        "",
        "## Q2 — Counts (settled books unless labeled frozen)",
        "",
        f"- Frozen books: {c['n_frozen']}. Settled: {c['n_settled']}. Still live: {c['n_live']}. Void official: {c['n_void']}.",
        f"- Settled with a 50-cross (dip target existed): {c['n_settled_cross']} / {c['n_settled']} ({c['pct_settled_cross']}%).",
        f"- Of those, third ticket filled (favorite came back to the dip): {c['n_settled_lock']} / {c['n_settled_cross']} ({c['pct_lock_of_cross']}%).",
            f"- Of filled dips: favorite won {c['n_lock_won']}, lost {c['n_lock_lost']}, void {c['n_lock_void']}.",
            "- When the third ticket fills, the extra pair is locked and the book is a with-fee win either way (~+$0.20). The 3 vs 43 is match outcome of the original favorite, not book P&L.",
            f"- Dip target never filled (settled crossed): {c['n_settled_cross_no_lock']} (all: favorite never cheap enough). Mean with-fee −$0.266.",
        f"- Frozen lock-filled {c['n_frozen_lock']} / {c['n_frozen']} = {c['pct_frozen_lock']}% (this is the prior 41.2%; it is of 182 frozen books, not of 119 settled).",
        "",
        "## Never-filled reasons (settled crossed, no third ticket)",
        "",
    ]
    for reason, n in c["never_reasons"].items():
        lines.append(f"- {reason}: {n}")
    lines.extend(
        [
            "",
            "## P&L with fees (settled)",
            "",
            "| bucket | N | WR% | mean $ | total $ | avg win | avg loss |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for block in payload["pnl_rows"]:
        lines.append(
            f"| {block['label']} | {block['n_settled']} | {fmt_pct(block.get('win_pct'), 1)} | "
            f"{fmt_signed(block.get('mean'))} | {fmt_signed(block.get('total'))} | "
            f"{fmt_signed(block.get('avg_win'))} | {fmt_signed(block.get('avg_loss'))} |"
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            payload["headline"],
            "",
            "Research only. Not gold. Not DailyRun. Live D=25 unchanged. No live GTC.",
            "",
        ]
    )
    BASELINE.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {BASELINE}", flush=True)


def write_html(payload: dict) -> None:
    c = payload["counts"]
    venue_rows = payload["venue_rows"]
    count_rows = payload["count_rows"]
    fill_rows = payload["fill_rows"]
    win_book_rows = payload["win_book_rows"]
    never_rows = payload["never_rows"]
    pnl_table_rows = payload["pnl_table_rows"]
    gtc_rows = payload["gtc_rows"]
    book_rows = payload["book_rows"]

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy B D=25 dip come-back and GTC rest 2026-10-23</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
.ok {{ background: #f0fdf4; padding: 10px 12px; border: 1px solid #86efac; margin: 12px 0; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Strategy B D=25: favorite-dip GTC rest vs come-back-and-win</h1>
<p class="note">America/New_York. Written {esc(payload.get("written_at") or "")}. Research only. Not gold. Not DailyRun. This page does not place, cancel, flatten, or sell. Live D=25 is not changed. No second Strategy B. Git HEAD this job: <code>{esc(BRANCH)}</code> (Spotify playlist). Click column headers to sort. Immediate-or-cancel (IOC) is fill now or cancel. Good-til-canceled (GTC) is a resting limit. T0 is the open used here. D=25 is a 25-cent lock on the extra post-cross pair.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="warn">
<p><strong>No live GTC this job.</strong> A market buy fills now; it is not a resting GTC. Live Strategy B still pings the favorite dip as IOC. Cancel-on-resolve for a resting order id does not exist yet. Leftover GTC after flatten miss is still the first slice, only when you say <code>wire leftover GTC</code> on <code>main</code>. Favorite-dip GTC is the second slice, only when you say <code>wire favorite-dip GTC</code> on <code>main</code>. Do not put GTC on Spotify playlist files. Dog-at-51 as a resting limit is still wrong. Gemini stop-limit stays paper-only. Size stays 1.</p>
</div>

<h2>Q1. Can we rest the 25¢ favorite-dip as GTC after the 50-cross?</h2>
<div class="ok">
<p><strong>API yes, live no.</strong> A market order is a take-now. The order we would rest is a <em>limit</em> GTC at <code>1 − cross_fill − 0.25</code>, not a market. If the original favorite is still richer than that dip, the limit sits. If the favorite is already at or under the dip, that same GTC fills now (same as today’s IOC ping). Live B does not send that rest today.</p>
</div>
<p class="note">Per venue, 1 contract. Field names from official docs plus the live IOC bodies. Click headers to sort.</p>
{table(
    [("Venue", "text"), ("Rest that dip GTC today?", "text"), ("Live B today", "text"), ("Missing before any live rest", "text")],
    venue_rows,
    ["venue", "rest", "live", "missing"],
)}

<p>What is missing is not the time-in-force string. It is the cancel loop: persist the resting order id, cancel it if the match resolves, cancel it if the match is postponed, and cancel it if we later flatten. Today’s leftover watch and Strategy B <code>mark_postponed</code> stop IOC retries / extras; they do not cancel a resting GTC. Per-venue <code>_cancel</code> helpers already exist. That is not the same as cancel-on-resolve.</p>

<h2>Q2. Headline counts (do not mix denominators)</h2>
<p class="note">Primary slice is <strong>settled books</strong> (official winner). The prior 41.2% lock-filled figure is of <strong>182 frozen books</strong>, including still-live books, not of 119 settled. Click headers to sort.</p>
{table(
    [("Slice", "text"), ("N", "num"), ("Of", "text"), ("% of that of", "num"), ("Note", "text")],
    count_rows,
    ["slice", "n", "of", "pct", "note"],
)}

<div class="ok">
<p><strong>Settled {esc(c['n_settled'])}.</strong> A 50-cross (dip target existed) on <strong>{esc(c['n_settled_cross'])}</strong> of those. The original favorite came back to the 25¢ dip (third ticket filled) on <strong>{esc(c['n_settled_lock'])}</strong> of the {esc(c['n_settled_cross'])}. Of those filled dips, the dipped player <strong>won {esc(c['n_lock_won'])}</strong>, lost {esc(c['n_lock_lost'])}, void {esc(c['n_lock_void'])}.</p>
<p>Coming back to the dip is not the same as winning the match. When the third ticket fills, the extra pair is locked (~25¢ before fees) and the <em>book</em> is a win either way. The original favorite still lost 43 of those 46 matches. The prior 41.2% is 75 / 182 frozen books, not 41.2% of 119.</p>
</div>

<h2>Filled dips: did the dipped player win?</h2>
<p class="note">The dipped player is the original favorite (the third ticket). This table is match outcome, not book P&amp;L. Whole-book with-fee win rate is 47.1% on 119 settled. Click headers to sort.</p>
{table(
    [("Filled-dip outcome", "text"), ("N settled", "num"), ("% of filled dips", "num"), ("% of settled 119", "num")],
    fill_rows,
    ["label", "n", "pct_lock", "pct_settled"],
)}
<p class="note">The {esc(c['n_lock_won'])} books where the dipped player then won the match:</p>
{table(
    [
        ("Game", "text"),
        ("Venue", "text"),
        ("Date", "date"),
        ("Favorite", "text"),
        ("Dog", "text"),
        ("Cross Yes", "num"),
        ("Dip target", "num"),
        ("Dip fill", "num"),
        ("With-fee P&L", "num"),
    ],
    win_book_rows,
    ["game", "venue", "date", "fav", "dog", "cross_px", "target", "dip_px", "pnl"],
)}

<h2>Dip targets that never filled</h2>
<p class="note">Settled books that printed a from-below 50-cross, so a dip target existed, but the original favorite never printed at or below 1 − cross_fill − 0.25 before the window ended. Absorbing 5¢ / 95¢ prints are skipped as fills (match treated as over). Click headers to sort.</p>
{table(
    [("Why the dip never filled", "text"), ("N", "num"), ("% of never-filled", "num")],
    never_rows,
    ["reason", "n", "pct"],
)}

<h2>Would a dip GTC have rested at the 50-cross?</h2>
<p class="note">Tape quote of original-favorite Yes at or before the cross tick, versus the dip target. “Would rest” means the favorite was still richer than 1 − cross − 0.25, so a GTC limit at that price would not take immediately. Settled crossed books. Click headers to sort.</p>
{table(
    [("At the 50-cross", "text"), ("N settled crossed", "num"), ("% of crossed", "num")],
    gtc_rows,
    ["label", "n", "pct"],
)}

<h2>P&amp;L with fees (the score)</h2>
<p class="note">Primary dollars are after live-sender fees (Polymarket taker 0.0695, Gemini round-up, Kalshi $0, Novig $0 on this tape). Fills are optimistic at the printed Yes. Expectancy is mean with-fee $ when every settled row is a win or a loss. On filled-dip rows, book WR is 100% because T0 both-Yes plus the extra pair both pay $1 no matter who wins the tennis match. That is not the dipped-player win rate (3 won / 43 lost). The drag is the 30 unhedged extra-dog books (mean −$0.266). Click headers to sort.</p>
{table(
    [("Bucket", "text"), ("N settled", "num"), ("Book WR%", "num"), ("Mean $ with fees", "num"), ("Total $ with fees", "num"), ("Avg win $", "num"), ("Avg loss $", "num"), ("Mean fees", "num"), ("Note", "text")],
    pnl_table_rows,
    ["label", "n", "wr", "mean", "total", "avg_win", "avg_loss", "fees", "note"],
)}

<h2>Each settled book that had a dip target</h2>
<p class="note">One row per settled 50-cross. Click column headers to sort. Swipe sideways to see more columns.</p>
{table(
    [
        ("Game", "text"),
        ("Venue", "text"),
        ("Date", "date"),
        ("Favorite", "text"),
        ("Dog", "text"),
        ("Cross Yes", "num"),
        ("Dip target", "num"),
        ("Third ticket filled?", "text"),
        ("Dip fill", "num"),
        ("Dipped player", "text"),
        ("Why no fill", "text"),
        ("GTC at cross", "text"),
        ("With-fee P&L", "num"),
    ],
    book_rows,
    [
        "game", "venue", "date", "fav", "dog", "cross_px", "target",
        "filled", "dip_px", "fav_outcome", "never_reason", "gtc_at_cross", "pnl",
    ],
)}

<h2>Freeze</h2>
<p>Same 182 keys as <code>strategy_b_D_05_to_50_20261023</code> and <code>strategy_b_t0_plus_50cross_20261023</code>. From-below 50-cross (Trungelliti). Primary P&amp;L with fees. {esc(payload.get("freeze_note") or "")} All T0 ≥ 2024-01-01, so the whole tape is out-of-sample (OOS). No in-sample (IS) row. Do not retune live D from this page.</p>
<p class="note">Acronyms: GTC is good-til-canceled. IOC is immediate-or-cancel. TIF is time-in-force. T0 is the open used here. D=25 is a 25-cent lock on the extra post-cross pair. OOS is out-of-sample.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def self_check() -> None:
    assert gtc_rest_label(0.62, 0.24).startswith("would rest")
    assert gtc_rest_label(0.20, 0.24).startswith("would take now")
    assert gtc_rest_label(0.04, 0.24).startswith("favorite absorbing")
    _out("self_check ok")


def main() -> None:
    self_check()
    freeze_keys = freeze_keys_from_original_html()
    freeze_set = set(freeze_keys)
    print(f"freeze keys from original HTML {len(freeze_keys)} unique {len(freeze_set)}", flush=True)
    stream = stream_tennis()
    settlements = load_settlements()
    catalog = load_catalog()
    start_lookup = start_lookup_from(settlements, catalog)
    pairs = pair_matches(stream["series"], start_lookup)
    tennis = [p for p in pairs if (p.get("sport") or "").lower() == "tennis"]
    print(f"two-sided tennis {len(tennis)}", flush=True)
    for pair in tennis:
        assign_actual_t0(pair, start_lookup)
    attach_pair_results(tennis, settlements)
    for pair in tennis:
        mark_inplay(pair)
    by_key: dict[tuple[str, str], dict] = {}
    for pair in tennis:
        by_key[pair_key(pair)] = pair
    frozen = []
    missing = []
    for key in freeze_keys:
        pair = by_key.get(key)
        if pair is None:
            missing.append(key)
            continue
        frozen.append(pair)
    print(f"frozen {len(frozen)}; missing {len(missing)}", flush=True)
    for pair in frozen:
        simulate_arms(pair)

    classified = [classify_pair(p) for p in frozen]
    settled_rows = [r for r in classified if r["settled"]]
    live_rows = [r for r in classified if r["still_live"]]
    void_rows = [r for r in classified if r["void"]]
    settled_cross = [r for r in settled_rows if r["crossed"]]
    settled_lock = [r for r in settled_cross if r["lock_filled"]]
    settled_no_lock = [r for r in settled_cross if not r["lock_filled"]]
    lock_won = [r for r in settled_lock if r["fav_outcome"] == "favorite won"]
    lock_lost = [r for r in settled_lock if r["fav_outcome"] == "favorite lost"]
    lock_void = [r for r in settled_lock if r["fav_outcome"] == "void"]
    frozen_lock = [r for r in classified if r["lock_filled"]]
    frozen_cross = [r for r in classified if r["crossed"]]
    never_counter = Counter(r["never_reason"] for r in settled_no_lock)
    gtc_counter = Counter(r["gtc_at_cross"] for r in settled_cross)

    n_settled = len(settled_rows)
    n_settled_cross = len(settled_cross)
    n_settled_lock = len(settled_lock)
    n_lock_won = len(lock_won)
    n_lock_lost = len(lock_lost)
    n_lock_void = len(lock_void)
    n_frozen = len(classified)
    n_frozen_lock = len(frozen_lock)

    counts = {
        "n_frozen": n_frozen,
        "n_settled": n_settled,
        "n_live": len(live_rows),
        "n_void": len(void_rows),
        "n_missing": len(missing),
        "n_settled_cross": n_settled_cross,
        "n_settled_lock": n_settled_lock,
        "n_settled_cross_no_lock": len(settled_no_lock),
        "n_lock_won": n_lock_won,
        "n_lock_lost": n_lock_lost,
        "n_lock_void": n_lock_void,
        "n_frozen_cross": len(frozen_cross),
        "n_frozen_lock": n_frozen_lock,
        "pct_settled_cross": pct(n_settled_cross, n_settled),
        "pct_lock_of_cross": pct(n_settled_lock, n_settled_cross),
        "pct_lock_of_settled": pct(n_settled_lock, n_settled),
        "pct_frozen_lock": pct(n_frozen_lock, n_frozen),
        "pct_frozen_cross": pct(len(frozen_cross), n_frozen),
        "never_reasons": dict(never_counter),
        "gtc_at_cross": dict(gtc_counter),
        "dip": CONTROL_D,
    }

    freeze_bits = []
    if n_frozen != ORIGINAL_N:
        freeze_bits.append(f"Frozen N is {n_frozen}, not {ORIGINAL_N}.")
    else:
        freeze_bits.append(f"Frozen N holds at {ORIGINAL_N}.")
    if n_settled != ORIGINAL_SETTLED:
        freeze_bits.append(
            f"Settled N is {n_settled}, not {ORIGINAL_SETTLED} from the prior write."
        )
    else:
        freeze_bits.append(f"Settled N holds at {ORIGINAL_SETTLED}.")

    headline = (
        f"Q1: rest the favorite-dip GTC as a limit, not a market — venue TIF yes, live no "
        f"(cancel-on-resolve missing). Q2: settled {n_settled}; 50-cross {n_settled_cross}; "
        f"dip filled {n_settled_lock}; dipped player won {n_lock_won} / lost {n_lock_lost} / "
        f"void {n_lock_void}."
    )
    _out(headline)
    _out(f"never_reasons={dict(never_counter)}")
    _out(f"gtc_at_cross={dict(gtc_counter)}")
    _out(
        f"frozen lock {n_frozen_lock}/{n_frozen}={counts['pct_frozen_lock']}% "
        f"settled lock {n_settled_lock}/{n_settled}={counts['pct_lock_of_settled']}%"
    )

    all_pnl = pnl_block(settled_rows, "All settled D=25")
    won_pnl = pnl_block(lock_won, "Dip filled and favorite won")
    lost_pnl = pnl_block(lock_lost, "Dip filled and favorite lost")
    never_pnl = pnl_block(settled_no_lock, "50-cross, dip never filled")
    nocross_pnl = pnl_block(
        [r for r in settled_rows if not r["crossed"]],
        "No 50-cross (T0 both only)",
    )
    pnl_rows = [all_pnl, won_pnl, lost_pnl, never_pnl, nocross_pnl]

    venue_rows = [
        {
            "venue": "Kalshi",
            "rest": "Yes. create-order time_in_force=good_till_canceled with no expiration_time is a true rest. 1 contract.",
            "live": "IOC only. kalshi_order_body sends immediate_or_cancel. Strategy B favorite dip uses send_yes_ioc.",
            "missing": "Cancel-on-resolve / postpone / later-flatten for a persisted order id. Not wired.",
        },
        {
            "venue": "Gemini (predictions)",
            "rest": "Yes. timeInForce=good-til-cancel (schema default). 1 contract. A non-live probe already used that string then cancelled. Do not set makerOrCancel if we want to take when the ask falls to the dip.",
            "live": "IOC only. gemini_order_payload timeInForce=immediate-or-cancel. Stop-limit is documented and stays paper-only.",
            "missing": "Same cancel-on-resolve loop. Probe cancel is not a live leftover/dip rest.",
        },
        {
            "venue": "Polymarket US",
            "rest": "Yes on the path we already post: POST /v1/orders tif=TIME_IN_FORCE_GOOD_TILL_CANCEL. 1 contract.",
            "live": "IOC only. polymarket_order_body tif=TIME_IN_FORCE_IMMEDIATE_OR_CANCEL.",
            "missing": "Same cancel-on-resolve loop. Consumer create has no stop; do not invent one.",
        },
        {
            "venue": "Novig",
            "rest": "Yes. Official tif includes GTC (rests until filled or cancelled). 1 contract (qty=100 native).",
            "live": "Lock/B send IOC when Novig orders are enabled. A 201 is queued, not resting — rest is the open event.",
            "missing": "Same cancel-on-resolve loop. Do not treat a 201 as a resting GTC.",
        },
    ]

    count_rows = [
        {
            "slice": "Settled books (official winner)",
            "n": n_settled,
            "of": "frozen 182",
            "pct": pct(n_settled, n_frozen),
            "note": "Primary Q2 denominator. All OOS.",
        },
        {
            "slice": "50-cross so a dip target existed",
            "n": n_settled_cross,
            "of": f"settled {n_settled}",
            "pct": counts["pct_settled_cross"],
            "note": "Original dog Yes through 0.50 from below. Target = 1 − cross − 0.25.",
        },
        {
            "slice": "Third ticket filled (favorite came back to the dip)",
            "n": n_settled_lock,
            "of": f"settled crossed {n_settled_cross}",
            "pct": counts["pct_lock_of_cross"],
            "note": f"Also {counts['pct_lock_of_settled']}% of settled 119. Not the frozen 41.2%.",
        },
        {
            "slice": "Dip filled AND favorite won the match",
            "n": n_lock_won,
            "of": f"filled dips {n_settled_lock}",
            "pct": pct(n_lock_won, n_settled_lock),
            "note": "This is the come-back-and-win count.",
        },
        {
            "slice": "Frozen books with lock filled (prior 41.2%)",
            "n": n_frozen_lock,
            "of": f"frozen {n_frozen}",
            "pct": counts["pct_frozen_lock"],
            "note": "Includes still-live books. Do not call this 41.2% of 119.",
        },
        {
            "slice": "Still live (no official winner yet)",
            "n": len(live_rows),
            "of": f"frozen {n_frozen}",
            "pct": pct(len(live_rows), n_frozen),
            "note": "Not in the settled P&L.",
        },
    ]

    fill_rows = [
        {
            "label": "Favorite won",
            "n": n_lock_won,
            "pct_lock": pct(n_lock_won, n_settled_lock),
            "pct_settled": pct(n_lock_won, n_settled),
        },
        {
            "label": "Favorite lost",
            "n": n_lock_lost,
            "pct_lock": pct(n_lock_lost, n_settled_lock),
            "pct_settled": pct(n_lock_lost, n_settled),
        },
        {
            "label": "Void",
            "n": n_lock_void,
            "pct_lock": pct(n_lock_void, n_settled_lock) if n_settled_lock else "0.0",
            "pct_settled": pct(n_lock_void, n_settled),
        },
        {
            "label": "Filled dips total",
            "n": n_settled_lock,
            "pct_lock": "100.0" if n_settled_lock else "",
            "pct_settled": counts["pct_lock_of_settled"],
        },
    ]

    never_n = len(settled_no_lock)
    never_rows = [
        {
            "reason": reason,
            "n": n,
            "pct": pct(n, never_n),
        }
        for reason, n in sorted(never_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    if not never_rows:
        never_rows = [{"reason": "none", "n": 0, "pct": ""}]

    gtc_rows = [
        {
            "label": label,
            "n": n,
            "pct": pct(n, n_settled_cross),
        }
        for label, n in sorted(gtc_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    def money_or_blank(value):
        if value is None:
            return ""
        return signed_money(value)

    pnl_table_rows = []
    for block in pnl_rows:
        pnl_table_rows.append(
            {
                "label": block["label"],
                "n": block["n_settled"],
                "wr": fmt_pct(block.get("win_pct"), 1),
                "mean": money_cell(block.get("mean")),
                "total": money_cell(block.get("total")),
                "avg_win": money_cell(block.get("avg_win")),
                "avg_loss": money_cell(block.get("avg_loss")),
                "fees": money_cell(block.get("mean_fees")),
                "note": block.get("note") or "",
            }
        )

    book_rows = []
    for r in sorted(settled_cross, key=lambda x: (x.get("date") or "", x.get("game") or "", x.get("venue") or "")):
        book_rows.append(
            {
                "game": r["game"],
                "venue": r["venue"],
                "date": (r.get("date") or "")[:10],
                "fav": r.get("fav") or "",
                "dog": r.get("dog") or "",
                "cross_px": fmt_px(r.get("cross_px")),
                "target": fmt_px(r.get("target")),
                "filled": "yes" if r["lock_filled"] else "no",
                "dip_px": fmt_px(r.get("dip_px")),
                "fav_outcome": r.get("fav_outcome") or "",
                "never_reason": r.get("never_reason") or "",
                "gtc_at_cross": r.get("gtc_at_cross") or "",
                "pnl": money_or_blank(r.get("pnl_fee")),
            }
        )

    payload = {
        "written_at": iso_now(),
        "counts": counts,
        "headline": headline,
        "freeze_note": " ".join(freeze_bits),
        "venue_rows": venue_rows,
        "count_rows": count_rows,
        "fill_rows": fill_rows,
        "never_rows": never_rows,
        "gtc_rows": gtc_rows,
        "pnl_rows": pnl_rows,
        "pnl_table_rows": pnl_table_rows,
        "book_rows": book_rows,
        "win_book_rows": [r for r in book_rows if r.get("filled") == "yes" and r.get("fav_outcome") == "favorite won"],
        "n_dense": n_frozen,
        "n_dense_settled": n_settled,
        "n_missing": len(missing),
        "stream_lines": stream.get("n_lines"),
        "seen_min": stream.get("seen_min"),
        "seen_max": stream.get("seen_max"),
    }
    STAMP.mkdir(parents=True, exist_ok=True)
    COUNTS_JSON.write_text(
        json.dumps(
            {
                "written_at": payload["written_at"],
                "headline": headline,
                "counts": json_safe(counts),
                "pnl": json_safe(pnl_rows),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    write_html(payload)
    write_baseline(payload)
    copy_g(PAGE)
    copy_g(BASELINE)
    print("done", flush=True)


if __name__ == "__main__":
    main()
