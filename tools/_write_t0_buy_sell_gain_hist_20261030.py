"""Hist T0 buy then sell-at-G on Kalshi yes_ask in-play paths.

Report only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not leftover-GTC A.
Does not DailyRun. Does not retune live B/C/D/E. Does not rewrite dashboard.html.
Does not start a leftover T0 candle pull. Does not pick G from OOS.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras  # noqa: E402
from nfl_t0_type_a_collect import line_won  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP  # noqa: E402
from t0_fav_lt90_baseline_20261024 import fmt_pct  # noqa: E402
import _write_sport_league_t0_decile_20261027 as decile_w  # noqa: E402
import _write_t0_buy_sell_gain_decile_sport_bet_20261030 as live_w  # noqa: E402
import _pull_kalshi_inplay_path_20261030 as pull  # noqa: E402

ET = ZoneInfo("America/New_York")
STAMP_SUB = STAMP / "t0_buy_sell_gain_hist_20261030"
PAGE = STAMP / "t0_buy_sell_gain_hist_20261030.html"
JSON_OUT = STAMP_SUB / "summary.json"
BASELINE = STAMP_SUB / "BASELINE.md"
LIVE_PAGE = STAMP / "t0_buy_sell_gain_decile_sport_bet_20261030.html"
PARENT_HTML = STAMP / "sport_league_t0_decile_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_buy_sell_gain_hist_20261030.html"
)
LIVE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_buy_sell_gain_decile_sport_bet_20261030.html"
)
DECILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/sport_league_t0_decile_20261027.html"
)
HIST_DIR = LOCAL_STAMP / "hist"
BOOKS = HIST_DIR / "books_kalshi.json"
SLICE_READY = 1500
GAIN_CENTS = live_w.GAIN_CENTS
HEADLINE_G = live_w.HEADLINE_G

ASKED = (
    "Paul (Fri 30 Oct 2026): i feel like this did NOT do a full analysis "
    f"{LIVE_URL} "
    "why? the max # Ns there are for a sport/bet type / decile combo is 60 "
    "on this report it's 5425 "
    f"{DECILE_URL} "
    "Original: thanks. let's see if we can bank on movement. theory: bets closer "
    "to 50c at the start move more. create a decile report by sports and bet types "
    "and show if we buy at the decile would we make money if we sold at gains on "
    "1c, 5c, 10c, etc."
)
PLAIN = (
    "The 5,425 report is: at kickoff we buy the Kalshi Yes ask, then wait until "
    "the game is won or lost. That does not need odds during the game. Selling at "
    "+1 / +5 / +10 cents does — we have to see whether the Yes ask actually got "
    "there after kickoff. Kalshi history on disk only kept one close around "
    "kickoff (about a 46-minute window, one bar saved). Polymarket history is one "
    "last-trade, not an ask. So the gain page could only use October 2026 games "
    "we watched live. Biggest live cell: 60 tennis moneyline 40–49. The 5,425 cell "
    "is Kalshi history tennis moneyline 90–99 (all tennis tours pooled) on the "
    "27 Oct sport/league page. We are now pulling 1-minute Kalshi Yes-ask paths "
    "through each game, tennis first. This page is that hist pull + sell-at-gain "
    "once paths exist. It is not the live-tape 60-row book. Live B/C/D/E bands "
    "were not changed."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def why_callout(status: dict, *, live_max_n: int = 60, live_page: bool = False) -> str:
    combo = status.get("combo_5425") or pull.COMBO_5425["label"]
    n_t = status.get("n_target") or 0
    n_t5 = status.get("n_target_5425") or 0
    n_u = status.get("n_usable") or 0
    n_u5 = status.get("n_usable_5425") or 0
    n_ut = status.get("n_usable_tennis") or 0
    running = "yes" if status.get("running") else "no"
    pid = status.get("pid") or "—"
    cmd = status.get("cmd") or "python -u tools/_pull_kalshi_inplay_path_20261030.py"
    combo_done = bool(n_t5) and int(n_u5) >= int(n_t5)
    tennis_slice = int(n_ut) >= SLICE_READY
    if live_page:
        verdict = (
            f"This page is live-tape only (max combo N={live_max_n} tennis moneyline 40–49). "
            "It is not the 5,425 hist book. Through-game Kalshi yes_ask paths are on the sibling hist page."
        )
    elif combo_done:
        verdict = (
            "Kalshi yes_ask in-play coverage for tennis moneyline 90–99 is on disk. "
            "Sell-at-gain below is hist path, not the October live tape."
        )
    elif tennis_slice:
        verdict = (
            f"A tennis in-play slice is on disk (usable {n_ut}). "
            f"The 5,425 combo is not done yet ({n_u5}/{n_t5 or '—'} mid-price 90–99). "
            "Do not read the live-tape 60-row book as the 5,425 hist book."
        )
    else:
        verdict = (
            "This is not yet a full hist gain study. Paths are still being fetched. "
            "Do not read the live-tape 60-row book as the 5,425 hist book."
        )
    return f"""<div class="callout warn" id="why-60-vs-5425">
<h2>Why max N is {esc(live_max_n)} here vs 5,425 on the sport/league page</h2>
<p><strong>{esc(verdict)}</strong></p>
<ul>
<li>The <strong>5,425</strong> cell is <strong>{esc(combo)}</strong> on
<a href="sport_league_t0_decile_20261027.html">sport_league_t0_decile_20261027.html</a>
— Kalshi history <strong>T0 Yes-ask → settle</strong> (who won). No in-play path needed.</li>
<li>The gain page needs a path after kickoff to know if +1 / +5 / +10¢ hit.
Kalshi hist stored <strong>0 in-play paths</strong> (T0 window ~46 min, one close kept).
Polymarket hist stored <strong>0 paths</strong> (one last-trade, not an ask).</li>
<li>The live gain book is October 2026 four-platform Yes-ask tape only.
Max sport / bet type / decile combo N = <strong>{esc(live_max_n)}</strong>
(tennis moneyline 40–49).</li>
<li>After leftover ITF/Challenger candles, disk tennis moneyline 90–99 is larger
than 5,425. The 27 Oct HTML still shows 5,425 on that frozen hist table.</li>
</ul>
<p class="note">In-play pull (Kalshi 1-min yes_ask through the game, tennis first):
running={esc(running)}, pid={esc(pid)}, usable paths {esc(n_u)} / target sides {esc(n_t)};
5425-combo usable {esc(n_u5)} / {esc(n_t5)}; tennis usable {esc(n_ut)}.
<code>{esc(cmd)}</code>. Polymarket through-game last-trade is feasible on the CLOB
and is <strong>not ask</strong> — not mixed, not started. HOLD live knobs. Did not pick G.</p>
</div>"""


def load_path_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    folder = pull.INPLAY
    if not folder.is_dir():
        return out
    for path in folder.glob("*.jsonl"):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    rec = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or not rec.get("ticker"):
                    continue
                out[str(rec["ticker"])] = rec
    return out


def hist_compact(book: dict, path_rec: dict) -> dict | None:
    if book.get("void"):
        return None
    won = book.get("fav_won")
    if won is None:
        won = line_won(book)
    if won is None:
        return None
    px = book.get("t0_fav")
    if px is None:
        px = book.get("t0_a")
    if px is None:
        return None
    t0_ts = book.get("t0_ts")
    if t0_ts is None:
        return None
    ticks = []
    for row in path_rec.get("path") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ts, p = row[0], row[1]
        try:
            ts_i = int(ts)
            price = float(p)
        except (TypeError, ValueError):
            continue
        if ts_i <= int(t0_ts):
            continue
        if 0.0 < price < 1.0:
            ticks.append((ts_i, price))
    ticks.sort(key=lambda r: r[0])
    if len(ticks) < pull.MIN_POST:
        return None
    opened = datetime.fromtimestamp(int(t0_ts), ET)
    end_ts = book.get("end_ts") or t0_ts
    if ticks:
        end_ts = max(int(end_ts), ticks[-1][0])
    closed = datetime.fromtimestamp(int(end_ts), ET)
    return {
        "sport": str(book.get("sport") or "unknown"),
        "league": decile_w.league_of_side(book),
        "kind": str(book.get("kind") or "moneyline"),
        "number": str(book.get("number") or ""),
        "venue": "kalshi",
        "game": str(book.get("game") or ""),
        "game_n": str(book.get("game_n") or book.get("game") or ""),
        "letter": str(book.get("_side_letter") or book.get("ticker") or ""),
        "name": str(book.get("fav_name") or ""),
        "t0_px": float(px),
        "t0_ts": int(t0_ts),
        "end_ts": int(end_ts),
        "won": bool(won),
        "entry_date": opened.date().isoformat(),
        "ticks": ticks,
        "days": max(0.0, (int(end_ts) - int(t0_ts)) / 86400.0),
        "opened": opened,
        "closed": closed,
        "decile": live_w.decile_of(px),
        "dist50": live_w.dist50_band(px),
        "move": live_w.move_stats(float(px), ticks),
        "n_venues": 1,
        "source": "kalshi_hist_yes_ask_path",
        "ticker": str(book.get("ticker") or ""),
    }


def build_hist_sides(books: list[dict], path_map: dict[str, dict]) -> list[dict]:
    out = []
    for book in books:
        ticker = str(book.get("ticker") or "")
        rec = path_map.get(ticker)
        if not rec:
            continue
        row = hist_compact(book, rec)
        if row and row.get("decile") and row.get("ticks"):
            out.append(row)
    return out


def status_table(status: dict) -> str:
    rows = [
        {"k": "5425 combo (27 Oct HTML)", "v": status.get("combo_5425") or pull.COMBO_5425["label"]},
        {"k": "Pull running", "v": "yes" if status.get("running") else "no"},
        {"k": "PID", "v": status.get("pid") or "—"},
        {"k": "Command", "v": status.get("cmd") or ""},
        {"k": "Target sides (unique Kalshi tickers)", "v": status.get("n_target") or 0},
        {"k": "Fetched (jsonl rows)", "v": status.get("n_done") or 0},
        {"k": "Usable in-play paths", "v": status.get("n_usable") or 0},
        {"k": "Target tennis ML 90-99", "v": status.get("n_target_5425") or 0},
        {"k": "Usable tennis ML 90-99", "v": status.get("n_usable_5425") or 0},
        {"k": "Usable tennis (any decile)", "v": status.get("n_usable_tennis") or 0},
        {"k": "Current series", "v": status.get("current_series") or "—"},
        {"k": "Poly last-trade through-game", "v": status.get("poly_note") or "not started, not mixed"},
    ]
    return live_w.table(
        [("Item", "text"), ("Value", "text")],
        rows,
        ["k", "v"],
    )


def score_block(sides: list[dict]) -> dict:
    identities = {
        "named_yes": live_w.pick_named_yes(sides),
        "cheaper_yes": live_w.pick_cheaper(sides),
        "nearest_50": live_w.pick_nearest_50(sides),
    }
    cheap = identities["cheaper_yes"]
    named = identities["named_yes"]
    html = {
        "cheap_matrix": live_w.matrix_html(
            live_w.matrix_rows(cheap, ("0-9", "10-19", "20-29", "30-39", "40-49")),
            "cheaper",
        ),
        "cheap_long": live_w.long_html(live_w.long_rows(cheap, include_league=False), include_league=False),
        "cheap_sport": live_w.sport_kind_html(cheap),
        "cheap_detail": live_w.long_html(live_w.long_rows(cheap, include_league=True), include_league=True),
        "named_matrix": live_w.matrix_html(live_w.matrix_rows(named, live_w.DECADES), "named"),
        "named_sport": live_w.sport_kind_html(named),
        "isoos": live_w.isoos_html(cheap),
        "canonical": live_w.canonical_html(live_w.path_sides(cheap)),
    }
    dist_table, dist_svg, _ = live_w.dist_html(named)
    html["dist_table"] = dist_table
    html["dist_svg"] = dist_svg
    html["near_far"] = live_w.near_far_html(identities)
    named_path = live_w.path_sides(named)
    near_mv = live_w.move_summary(live_w.group_key_sides(named_path, dist="0-9"))
    far_mv = live_w.move_summary(live_w.group_key_sides(named_path, dist="40-50"))
    verdict, detail = live_w.theory_yes_no(near_mv, far_mv)
    return {
        "html": html,
        "n_named": len(named),
        "n_cheaper": len(cheap),
        "n_named_path": len(named_path),
        "n_cheaper_path": len(live_w.path_sides(cheap)),
        "theory": {"verdict": verdict, "detail": detail, "g_line": live_w.g_line(identities)},
        "near_move": near_mv,
        "far_move": far_mv,
    }


def freeze_md(now: str, status: dict, scored: dict | None) -> str:
    lines = [
        "# T0 buy then sell at +G — Kalshi hist in-play paths",
        "",
        f"Written {now}. Report only. Live B/C/D/E knobs were not patched.",
        "",
        "## What you asked",
        "",
        ASKED,
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Why 60 vs 5425",
        "",
        "- 5425 = tennis ALL Moneyline 90-99 on sport_league_t0_decile Kalshi hist "
        "(T0 Yes-ask → settle). No in-play needed.",
        "- Gain study needs a post-kickoff Yes-ask path. Kalshi hist stored 0 paths "
        "(T0 window ~46 min, one close). Poly hist stored 0 paths (one last-trade).",
        "- Live gain page max combo N=60 (tennis moneyline 40-49, Oct 2026 tape).",
        "",
        "## Freeze",
        "",
        "- **Universe:** Kalshi hist `books_kalshi.json` joined to through-game "
        "1-min yes_ask.close paths (`hist/kalshi/inplay/`). Same named-Yes T0 identity "
        "as sport_league_t0_decile.",
        "- **Entry:** 1 contract at T0 Yes ask (before-fee decile; with-fee P&L).",
        "- **Exit:** sell at first in-play Yes-ask print ≥ entry + G. Fill at the gain "
        "price, or at the open if the path opens through it. Miss = hold to settle.",
        "- **G:** 1, 5, 10, 15, 20, 25 cents (same headline as live gain; 2/3/4 not retuned).",
        "- **Fees:** Kalshi 0.07×p×(1−p) both legs. Do not mix sportsbooks. "
        "Do not call Poly last-trade an ask.",
        "- **Path:** Kalshi yes_ask.close 1-min through the game. Labeled "
        "`kalshi_hist_yes_ask_path`. Not live ticks. Not Poly last-trade.",
        f"- **Pull:** pid={status.get('pid')} running={status.get('running')} "
        f"usable={status.get('n_usable')}/{status.get('n_target')} "
        f"combo5425 usable={status.get('n_usable_5425')}/{status.get('n_target_5425')}.",
        "- **IS / OOS:** entry_date < 2024-01-01 vs ≥ 2024-01-01. Kalshi sports hist "
        "is after 2024 — expect IS N=0. Never retune on OOS. HOLD G.",
        "- **Selection:** do not pick a live band or G from this table.",
        "",
        "## Do not",
        "",
        "- Do not pick G or a live band from this page.",
        "- Do not DailyRun. Do not leftover-GTC A. Do not start a second B.",
        "",
    ]
    if scored:
        lines.extend([
            "## Theory headline (hist paths on disk)",
            "",
            f"- Near-50 move more? **{scored.get('theory', {}).get('verdict')}**. "
            f"{scored.get('theory', {}).get('detail')}",
            "",
        ])
    return "\n".join(lines)


def write_html(now: str, status: dict, scored: dict | None) -> str:
    kn = live_w.live_knobs()
    why = why_callout(status)
    score_html = ""
    if scored:
        thry = scored.get("theory") or {}
        h = scored["html"]
        score_html = f"""
<div class="callout"><h2>Does near-50 move more? (hist paths on disk only)</h2>
<p><strong>{esc((thry.get('verdict') or '').upper())}</strong> — {esc(thry.get('detail'))}</p>
<p class="note">{esc(thry.get('g_line') or '')}</p>
<p class="note">HOLD live B/C/D/E. Did not pick a G from this table.</p>
</div>
<h2>Distance-to-50 — theory test (named Yes, Kalshi hist path)</h2>
<p class="note">Click column headers to sort. Same freeze as the live gain page, Kalshi yes_ask path only.</p>
{h['dist_table']}
{h['dist_svg']}
<h2>Near-50 vs far-from-50 — G=1 / 5 / 10</h2>
{h['near_far']}
<h2>Canonical book metrics — cheaper Yes, hist path</h2>
<p class="note">Hold-to-settle vs sell-at-G. Do not judge on max single-trade PnL.
Annualized rate of return uses the house formula; same-day holds are omitted.</p>
{h['canonical']}
<h2>Cheaper Yes — G × decile</h2>
{h['cheap_matrix']}
{h['cheap_long']}
<h2>Cheaper Yes — sport × bet type × G=1/5/10</h2>
{h['cheap_sport']}
<h2>Cheaper Yes — sport × league × bet type × decile × G</h2>
<p class="note">Full grain. This is the hist analog of the 60-vs-5425 table.</p>
{h['cheap_detail']}
<h2>Named Yes both sides</h2>
{h['named_matrix']}
{h['named_sport']}
<h2>IS / OOS</h2>
<p class="note">If OOS softens versus IS, HOLD — do not retune OOS. Did not pick G from OOS.</p>
{h['isoos']}
"""
    else:
        score_html = (
            "<h2>Sell-at-gain numbers</h2>"
            "<p class=\"note\">Not scored yet — usable Kalshi in-play paths are still "
            "below a meaningful slice. The live-tape page is Oct 2026 only "
            "(max combo N=60). Do not treat that as the 5,425 hist book.</p>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>T0 buy then sell at +G — Kalshi hist in-play</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout.warn {{ background: #fff7ed; border-color: #fdba74; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
.chart {{ max-width: 720px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>T0 buy then sell at +G — Kalshi hist in-play</h1>
<p class="note">Written {esc(now)}. Live B D stays {esc(kn.get('b_d'))} (HOLD 25¢).
C 51–89, D spreads, and E 11–49 were not retuned. Did not pick a G from this table.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{PLAIN}</p></div>
{why}
<div class="callout"><h2>Two gain pages, not blended</h2>
<p><a href="t0_buy_sell_gain_decile_sport_bet_20261030.html">Live-tape gain page</a>
(Oct 2026 Yes-ask ticks, max combo N=60).
This page is Kalshi hist yes_ask paths. Parent hold-to-settle:
<a href="sport_league_t0_decile_20261027.html">sport / league / T0 decile</a>
(5425 = tennis moneyline 90–99).</p>
</div>
<h2>In-play pull status</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
{status_table(status)}
{score_html}
<p class="tiny">Generator: <code>tools/_write_t0_buy_sell_gain_hist_20261030.py</code>.
Pull: <code>tools/_pull_kalshi_inplay_path_20261030.py</code>.
Same freeze as <a href="t0_buy_sell_gain_decile_sport_bet_20261030.html">live gain</a>.
File URL {esc(FILE_URL)}.
Did not sell, start a second B, leftover-GTC A, DailyRun, or retune live B D=0.25 / C 51–89 / D spreads / E 11–49.
Did not rewrite dashboard.html.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return str(PAGE)


def annotate_live_gain_page(status: dict) -> None:
    if not LIVE_PAGE.is_file():
        return
    text = LIVE_PAGE.read_text(encoding="utf-8")
    why = why_callout(status, live_page=True)
    if 'id="why-60-vs-5425"' in text:
        text = _replace_callout(text, why)
    else:
        needle = '<div class="callout"><h2>In plain English</h2>'
        end = text.find("</div>", text.find(needle)) if needle in text else -1
        if end > 0:
            insert_at = end + len("</div>")
            text = text[:insert_at] + "\n" + why + text[insert_at:]
    sib = (
        ' · <a href="t0_buy_sell_gain_hist_20261030.html">'
        "Kalshi hist in-play gain (30 Oct)</a>"
    )
    if "t0_buy_sell_gain_hist_20261030.html" not in text:
        old = (
            'Related: <a href="sport_league_t0_decile_20261027.html">'
            "sport / league / T0 decile (hold-to-settle)</a>."
        )
        if old in text:
            text = text.replace(
                old,
                old[:-1] + sib + ".",
                1,
            )
    if "id=\"why-60-vs-5425\"" in text or 'id="why-60-vs-5425"' in text:
        if ".callout.warn" not in text:
            text = text.replace(
                ".callout h2 { margin: 0 0 6px; font-size: 1rem; }",
                ".callout.warn { background: #fff7ed; border-color: #fdba74; }\n"
                ".callout h2 { margin: 0 0 6px; font-size: 1rem; }",
                1,
            )
    LIVE_PAGE.write_text(text, encoding="utf-8")


def _replace_callout(text: str, why: str) -> str:
    start = text.find('id="why-60-vs-5425"')
    if start < 0:
        return text
    div = text.rfind("<div", 0, start)
    if div < 0:
        return text
    depth = 0
    i = div
    while i < len(text):
        if text.startswith("<div", i):
            depth += 1
            i += 4
            continue
        if text.startswith("</div>", i):
            depth -= 1
            i += 6
            if depth == 0:
                return text[:div] + why + text[i:]
            continue
        i += 1
    return text


def patch_parent_html() -> None:
    if not PARENT_HTML.is_file():
        return
    text = PARENT_HTML.read_text(encoding="utf-8")
    if "t0_buy_sell_gain_hist_20261030.html" in text:
        return
    needle = "t0_buy_sell_gain_decile_sport_bet_20261030.html"
    idx = text.find(needle)
    if idx < 0:
        return
    close = text.find("</a>", idx)
    if close < 0:
        return
    insert = (
        ' · <a href="t0_buy_sell_gain_hist_20261030.html">'
        "Kalshi hist in-play gain (30 Oct)</a>"
    )
    PARENT_HTML.write_text(text[: close + 4] + insert + text[close + 4 :], encoding="utf-8")


def annotate_live_writer() -> None:
    path = ROOT / "tools" / "_write_t0_buy_sell_gain_decile_sport_bet_20261030.py"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if "why-60-vs-5425" in text:
        return
    # Link sibling from the related paragraph on future regenerations.
    old = (
        '<p>Related: <a href="sport_league_t0_decile_20261027.html">'
        "sport / league / T0 decile (hold-to-settle)</a>.</p>"
    )
    new = (
        '<p>Related: <a href="sport_league_t0_decile_20261027.html">'
        "sport / league / T0 decile (hold-to-settle)</a>"
        ' · <a href="t0_buy_sell_gain_hist_20261030.html">'
        "Kalshi hist in-play gain (30 Oct)</a>.</p>"
    )
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


def slice_ready(status: dict) -> bool:
    n_u5 = int(status.get("n_usable_5425") or 0)
    n_ut = int(status.get("n_usable_tennis") or 0)
    n_t5 = int(status.get("n_target_5425") or 0)
    if n_u5 >= SLICE_READY:
        return True
    if n_ut >= SLICE_READY:
        return True
    if n_t5 and n_u5 >= n_t5 and n_t5 >= 500:
        return True
    return False


def main() -> int:
    STAMP_SUB.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    status = pull.census_inplay()
    if not status.get("n_target"):
        # Fill targets from books if the pull has not written them yet.
        try:
            work = pull.load_work()
            status["n_target"] = len(work)
            status["n_target_5425"] = sum(1 for b in work if pull.is_combo_5425(b))
        except Exception as exc:
            _out(f"worklist preview failed: {type(exc).__name__}: {exc}")
    status.setdefault("combo_5425", pull.COMBO_5425["label"])
    status.setdefault("cmd", "python -u tools/_pull_kalshi_inplay_path_20261030.py")
    scored = None
    n_usable = int(status.get("n_usable") or 0)
    if n_usable >= 50:
        _out(f"loading books + {n_usable} in-play paths")
        books = decile_w.load_json_list(BOOKS)
        path_map = load_path_map()
        sides = build_hist_sides(books, path_map)
        _out(f"hist sides with path {len(sides)}")
        if sides:
            scored = score_block(sides)
            if not slice_ready(status):
                note = (
                    (scored.get("theory") or {}).get("detail") or ""
                ) + " Partial pull — not the full 5425 hist book yet."
                scored.setdefault("theory", {})
                scored["theory"]["detail"] = note
    path = write_html(now, status, scored)
    BASELINE.write_text(freeze_md(now, status, scored), encoding="utf-8")
    dump = {
        "written_at": now,
        "combo_5425": pull.COMBO_5425["label"],
        "live_max_combo_n": 60,
        "live_max_combo": "tennis ALL Moneyline 40-49",
        "status": status,
        "scored": bool(scored),
        "slice_ready": slice_ready(status),
        "n_named": (scored or {}).get("n_named"),
        "n_cheaper": (scored or {}).get("n_cheaper"),
        "n_named_path": (scored or {}).get("n_named_path"),
        "theory": (scored or {}).get("theory"),
        "live_knobs": live_w.live_knobs(),
    }
    JSON_OUT.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
    annotate_live_gain_page(status)
    annotate_live_writer()
    patch_parent_html()
    _out(f"wrote {path} usable={status.get('n_usable')} scored={bool(scored)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
