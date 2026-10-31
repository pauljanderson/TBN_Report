"""Write Paul's layman field-guide for the two live prediction-market strategies.

Reads send-line and caps from live_lock_orders / live_strategy_b so the HTML
cannot drift. Does not place, cancel, or amend orders. Does not commit.
Research only. Not gold. Not DailyRun. 1 contract. Immediate-or-cancel only.
"""
from __future__ import annotations

import html as html_lib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

import live_lock_orders  # noqa: E402
import live_strategy_b  # noqa: E402
import novig_live  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

PAGE = STAMP / "strategies_layman.html"
G_DIR = Path(r"G:\My Drive\paul_experiments\prediction_market_arb_exhaustive_20261017")

ASKED = (
    "document each of these strategies we are currently using in clear layman's terms, "
    "with a preface of how the prediction markets work, and how each of our strategies work."
)
PLAIN = (
    "This is a field guide to the live bots that can send money today. All buy "
    "one-dollar Yes/No contracts as Immediate or Cancel "
    "(fill now or cancel — nothing sits on the book). The gap lock bot buys Yes "
    "on one sportsbook and No on another when the two prices plus fees still cost "
    "less than a dollar, so one side must pay $1 and we keep the gap. Tennis crossover "
    "(the code file is still live_strategy_b.py) is tennis-only: at the trusted start it buys both players, then later tries "
    "to lock in 25 cents on an extra pair after the underdog prints above 50 cents. "
    "College football favorite buys the T0 favorite's Yes on college football moneyline when that ask is between 50 and 90 cents. "
    "T0 spreads buys one qualifying spread per game in that same band. "
    "None of these is gold. None is DailyRun. A leftover Good Til Canceled (GTC) rest "
    "was asked about separately and is not live."
)


def _esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{_esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def _table(headers: list[tuple[str, str]], rows: list[list[str]], *, total: bool = False) -> str:
    head = "".join(_th(label, kind) for label, kind in headers)
    body = []
    for i, cells in enumerate(rows):
        cls = ' class="total-row"' if total and i == len(rows) - 1 else ""
        tds = "".join(f"<td>{_esc(cell)}</td>" for cell in cells)
        body.append(f"<tr{cls}>{tds}</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _copy_g(path: Path) -> None:
    if not (G_DIR.parent.exists() or Path("G:/").exists()):
        return
    try:
        G_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, G_DIR / path.name)
    except OSError:
        return


def write_page() -> Path:
    send_line = live_lock_orders.send_line()
    net_max = format(live_lock_orders.NET_MAX, "f")
    assert send_line == net_max
    max_open_locks = int(live_lock_orders.MAX_OPEN_LOCKS)
    lock_tick = int(live_lock_orders.WATCH_TICK_SEC)
    lock_size = format(live_lock_orders.SIZE, "f")
    max_open_b = int(live_strategy_b.MAX_OPEN_B_MATCHES)
    d = format(live_strategy_b.D, "f")
    c_lo = format(live_strategy_b.C_LO, "f")
    c_hi = format(live_strategy_b.C_HI, "f")
    yes_lo = format(live_strategy_b.YES_LO, "f")
    yes_hi = format(live_strategy_b.YES_HI, "f")
    b_tick = int(live_strategy_b.TICK_SEC)
    cross = format(live_strategy_b.CROSS, "f")
    novig_flag = bool(novig_live.NOVIG_ORDERS_ENABLED)
    novig_orders = (
        "quoted, and sent only when Novig orders are live "
        f"(switch on={novig_flag}; still needs a trading key)"
        if novig_flag
        else "quoted only (orders switch is off)"
    )

    freeze = _table(
        [("Knob", "text"), ("Live value", "text"), ("Where", "text")],
        [
            ["Size", f"{lock_size} contract", "both bots"],
            ["Time in force", "Immediate or Cancel (IOC) — fill now or cancel; nothing rests", "both bots"],
            ["Send line (NET_MAX)", send_line, "live_lock_orders.send_line()"],
            ["Max open lock-bot pairs", str(max_open_locks), "MAX_OPEN_LOCKS"],
            ["Lock leftover watch tick", f"{lock_tick} second", "WATCH_TICK_SEC"],
            ["Tennis crossover max open matches", str(max_open_b), "MAX_OPEN_B_MATCHES / systems.json"],
            ["Tennis crossover lock profit D", d, "D on the extra pair after the 50c cross, not a 25c dip of the dog"],
            ["Tennis crossover combined Yes C", f"[{c_lo}, {c_hi}]", "C_LO / C_HI inclusive"],
            ["Tennis crossover each Yes", f"({yes_lo}, {yes_hi})", "YES_LO / YES_HI exclusive"],
            ["Tennis crossover dog cross", f"strictly above {cross}", "CROSS"],
            ["Tennis crossover tick", f"{b_tick} second", "TICK_SEC"],
            ["Novig on lock bot", novig_orders, "novig_live.NOVIG_ORDERS_ENABLED + trading key"],
            ["Novig on Strategy B", "may send when Novig orders are live (1 contract IOC + fills confirm)", "VENUE_ORDER includes Novig"],
            ["Good Til Canceled (GTC)", "not live", "asked separately; leftover / B dip GTC is not wired"],
        ],
    )

    compare = _table(
        [
            ("Topic", "text"),
            ("Gap lock bot", "text"),
            ("Tennis crossover (B)", "text"),
        ],
        [
            ["Code", "live_lock_orders.py", "live_strategy_b.py"],
            ["Sport", "Any live game we poll (same settlement on two venues)", "Tennis moneyline only"],
            [
                "What we buy",
                "Yes on one venue + No on the other (or opponent Yes on a 2-player tennis moneyline)",
                "Both players' Yes at start, then extra dog Yes after 50c, then favorite Yes at the 25c-lock dip",
            ],
            [
                "When we send",
                f"After-fee Yes+No at or under {send_line} and under $1",
                f"Trusted start T0, combined C in [{c_lo}, {c_hi}], each Yes in ({yes_lo}, {yes_hi})",
            ],
            ["Size / time in force", f"{lock_size} contract, Immediate or Cancel", f"{lock_size} contract, Immediate or Cancel"],
            ["Max open", f"{max_open_locks} live lock-bot pairs", f"{max_open_b} open tennis matches"],
            ["Novig", "Only if Novig orders are live", "May send when Novig orders are live"],
            [
                "If one leg fills",
                "Flatten (buy the opposite on the same venue). Flatten miss → leftover watch for a true hedge only",
                "Flatten that Yes (buy No on the same venue). Flatten miss → leftover-watch only the missed player's Yes",
            ],
            ["If neither fills", "No latch. Try later.", "Retry T0 a few times, then abandon. Latch untouched."],
            [
                "Is a filled pair a lock?",
                "Yes, if Yes+No same settlement (or dual-Yes on opposite tennis names) both filled under $1 after fees",
                "T0 dual-Yes is B's pair, not a Kalshi/Gemini lock. The extra post-cross pair is the 25-cent lock",
            ],
        ],
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prediction-market strategies — what is live today</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ margin: 0; padding: 16px 16px 48px; font: 16px/1.45 system-ui, Segoe UI, sans-serif; color: #0f172a; background: #fff; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
h3 {{ font-size: 1rem; margin: 1rem 0 0.35rem; }}
p {{ margin: 0.4rem 0 0.7rem; }}
ul, ol {{ margin: 0.3rem 0 0.8rem; padding-left: 1.3rem; }}
li {{ margin: 0.25rem 0; }}
.callout {{ border-left: 4px solid #1d4ed8; background: #f8fafc; padding: 10px 12px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.notyet {{ background: #f1f5f9; border: 1px solid #94a3b8; padding: 10px 12px; margin: 0.8rem 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
.ex {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px 12px; margin: 0.5rem 0 0.9rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Prediction-market strategies — what is live today</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. Size is <strong>1 contract</strong>. Every live send is <strong>Immediate or Cancel (IOC)</strong>: fill now or cancel. Nothing rests on the book. Written 2026-10-22 from the live constants in <code>live_lock_orders.py</code> and <code>live_strategy_b.py</code>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{_esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{_esc(PLAIN)}</p>
</div>
<p class="note">All-game T0 stats (every tracked game, not only ones we bet): <a href="t0_all_games_stats.html">t0_all_games_stats.html</a>. Rebuilds about every 2 hours while prediction jobs are running.</p>

<h2>How these markets work</h2>
<p>A contract is a Yes/No bet that pays <strong>$1 if that outcome happens</strong> and <strong>$0 if it does not</strong>.</p>
<ul>
<li><strong>Buying Yes at 40 cents</strong> means you pay 40c now. If Yes wins you get $1 (profit 60c). If No wins, you lose the 40c.</li>
<li><strong>Buying No</strong> is the other side of the same question. On Kalshi, buying No is sent as a Yes-ask at 1 minus the No price you want to pay. On Polymarket US, buying No is a short (<code>BUY_SHORT</code>) whose cash cost is 1 minus the Yes price.</li>
<li>The same game can be listed on more than one venue. We use <strong>Kalshi</strong>, <strong>Gemini</strong>, <strong>Polymarket US</strong>, and <strong>Novig</strong>.</li>
</ul>

<h3>What a lock is</h3>
<p>A <strong>true lock</strong> (full system) is Yes on one venue plus No on the other for the <strong>same settlement</strong>, both filled, combined after-fee cost under $1. Then one side wins $1 and you keep the gap as profit.</p>
<div class="ex">
<p><strong>Example.</strong> Pay 40 cents for Yes and 50 cents for No. Combined cost 90 cents. Someone is paid $1. The 10-cent gap is locked profit — before fees. Live we also require after-fee cost at or under the send line (<strong>{_esc(send_line)}</strong>) and still under $1.</p>
</div>
<p>On a 2-player tennis moneyline, <strong>opponent Yes</strong> (Player B wins) is the economic twin of No on Player A. That can complete a lock. <strong>Opponent No of a dog we already hold Yes is not a hedge</strong> — that is the Goffin / Onclin mistake: two tickets that both pay only if the same player wins.</p>

<h3>Fees and the send line</h3>
<ul>
<li><strong>Kalshi:</strong> no taker fee in our compare (unless a fill response itself reports a fee).</li>
<li><strong>Gemini, Polymarket US, Novig:</strong> documented taker fees. We add those before we decide the pair is cheap enough.</li>
<li><strong>Send cap:</strong> after-fee cost must be at or under <code>NET_MAX</code> = <strong>{_esc(send_line)}</strong> (from <code>live_lock_orders.send_line()</code> today) <em>and</em> the two prices must still sum under $1.</li>
<li>We send <strong>1 contract</strong>, Immediate or Cancel.</li>
</ul>

<h2>Live knobs (from code, not memory)</h2>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{freeze}

<h2>Strategy 1 — gap lock bot</h2>
<p class="tiny">Code: <code>tools/live_lock_orders.py</code>. Watches live games. Cap {_esc(str(max_open_locks))} open lock-bot pairs. Tick {_esc(str(lock_tick))}s.</p>
<ol>
<li>Watch live games. When Yes + No after fees is at or under the send line ({_esc(send_line)}) <em>and</em> under $1, post <strong>both legs at once</strong> as Immediate or Cancel.</li>
<li>Recheck the live book on each venue right before either send goes out. If either book is empty, has no takeable size of 1, or would put after-fee net above {_esc(send_line)}, send <strong>neither</strong> leg.</li>
<li>Before the send, <strong>claim</strong> the pair so two pollers cannot buy the same ticket twice. An already-claimed or already-filled pair is skipped as a <strong>duplicate</strong>.</li>
<li><strong>Both fill</strong> as a true lock → keep them, keep looking (until {_esc(str(max_open_locks))} live holdings).</li>
<li><strong>One fills</strong> → <strong>flatten</strong>: buy the opposite on the <em>same</em> venue / same instrument so we are not directional. If flatten also misses, leftover watch may buy only a <strong>true hedge</strong> of the filled player (the missed intended instrument, same-player No on another venue, or opponent Yes that completes a dual-Yes lock). Never opponent-No when we already hold dog Yes.</li>
<li><strong>Neither fills</strong> → no latch. Try later.</li>
<li>A venue “accepted” reply with <strong>fill 0</strong> is not a fill. Immediate or Cancel cancelled empty. We do not treat that as filled.</li>
<li><strong>Novig</strong> is quoted always; Novig orders go out only if Novig orders are live (switch plus a trading key). Today: {_esc(novig_orders)}.</li>
<li>If Strategy B already has that <strong>same tennis match</strong> open, the lock bot skips it so the two bots do not double-buy.</li>
</ol>
<p class="note">A leftover watch is one Immediate or Cancel, 1 contract, cheapest qualifying true hedge, first time the rechecked ask is in cap. A fill (including a partial) or a zero-fill miss both mark that leftover attempt done — we do not fire another Immediate or Cancel for the same leftover ticket. New pairs stay blocked while that leftover is open.</p>

<p class="note">On/off, stake, and max open: <code>python tools/prediction_job_control.py systems</code> or <code>run_prediction_systems.bat</code>. See <a href="systems_abcd_cli_20261024.html">systems_abcd_cli_20261024.html</a> and <a href="job_status.html">job_status.html</a>.</p>

<h2>Strategy 2 — Tennis crossover (Strategy B, D=25)</h2>
<p class="tiny">Code: <code>tools/live_strategy_b.py</code> (module name unchanged). Tennis only. Max {_esc(str(max_open_b))} open matches. Tick {_esc(str(b_tick))}s. D={_esc(d)} lock profit on the extra pair.</p>
<ol>
<li>Tennis moneyline only. At a <strong>trusted start (T0)</strong> — a clocked Kalshi/Gemini occurrence, or a listed time with seconds=00, inside a 5-minute window, not already in-play — buy <strong>both Yes</strong> if combined C is in [{_esc(c_lo)}, {_esc(c_hi)}] and each Yes is in ({_esc(yes_lo)}, {_esc(yes_hi)}).</li>
<li>Both-or-nothing at T0: recheck both books before either send. If only one fills, flatten that Yes (buy No on the same venue). Do not hold a cheap directional dog. If flatten also misses, leftover-watch <em>only</em> the missed player's Yes — never opponent No.</li>
<li>Then wait until the <strong>dog Yes goes strictly above {_esc(cross)}</strong> (50 cents).</li>
<li>Buy extra of that dog, then buy the original <strong>favorite at a dip</strong> so leftover lock profit is 25 cents: favorite target ≈ 1 − dog_fill − {_esc(d)}. <strong>Not</strong> a 25-cent dip of the dog. Example: extra dog fills at 52 cents → favorite target is 1 − 0.52 − 0.25 = 23 cents.</li>
<li>May send Novig when Novig orders are live (switch plus a trading key), same 1-contract Immediate or Cancel path as Kalshi / Gemini / Polymarket US, with a fills confirm after the send. Independent of the lock-bot latch file.</li>
<li><strong>Postponed / delayed / suspended:</strong> holdings stay. Extras, the 50-cent cross, and the favorite dip stop. We do not sell.</li>
</ol>
<p class="note"><strong>Dual-Yes at T0 is Tennis crossover's pair, not a Kalshi/Gemini lock.</strong> Combined C can be a bit over $1 ({_esc(c_hi)} max). That is both sides at the start, then a hunt for the 25-cent extra lock. Extra unmatched dog Yes (Shigeta extra, Takagi unpaired dog) is leftover risk, not a lock.</p>

<h2>Strategy 3 — College football favorite (C)</h2>
<p class="tiny">Code: <code>tools/live_cfb_favorite.py</code>. College football moneyline only. T0 favorite Yes in (0.50, 0.90), cheapest venue. Hold to settlement. Default stake $1, max 2 open games. Not gold. Not DailyRun.</p>
<ol>
<li>At a trusted start, look at college football moneyline on Kalshi, Gemini, Polymarket US, and Novig.</li>
<li>The favorite is the team with the higher Yes ask on a primary read, then we shop that same team. If venues disagree, the team whose Yes is above 50 cents with the higher median wins; a 50-50 is skipped.</li>
<li>Buy one Immediate or Cancel on the cheapest Yes ask if it is in (0.50, 0.90). Recheck that venue's book before send. Confirm fill. Hold to the end. No 50-cent cross. No 0.984 lock cap.</li>
<li>One shot per game at T0. After the window, do not chase.</li>
</ol>

<h2>Strategy 4 — T0 spreads (D)</h2>
<p class="tiny">Code: <code>tools/live_spread_t0.py</code>. Any sport with spread markets. One qualifying spread per game. Totals stay out. Default stake $1, max 2 open games.</p>
<ol>
<li>At trusted T0, if a spread's Yes favorite is in (0.50, 0.90), buy that side on the cheapest venue for that line.</li>
<li>Default is <strong>one spread ticket per game</strong> — the qualifying line closest to 50 cents — so eight lines on one kickoff cannot blow max=2. A later <code>--d-all-lines</code> switch is possible; it is off.</li>
<li>Totals / over-under are not D. Hold to settlement. Same send rules as C.</li>
</ol>

<h2>Lock bot vs Tennis crossover, side by side</h2>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{compare}

<h2>What is not a strategy here</h2>
<ul>
<li><strong>Stock research / DailyRun / partial exit p80_be_40.</strong> Different book, different engine. Not these bots.</li>
<li><strong>Catalog scan.</strong> Quotes only. It never sends. A cheap-looking catalog row is an alert, not an order.</li>
<li><strong>Proposed Good Til Canceled leftover / B dip GTC.</strong> Asked about separately. <strong>Not live.</strong></li>
</ul>
<div class="notyet">
<p><strong>Not live yet.</strong> Good Til Canceled (GTC) leftover, and a GTC rest for the Strategy B favorite dip, were asked about in a separate thread. Today every live send is still Immediate or Cancel. This page does not invent GTC as a working strategy.</p>
</div>

<h2>Words used on this page</h2>
<ul>
<li><strong>Immediate or Cancel (IOC):</strong> fill what you can right now; cancel the rest. Nothing rests on the book.</li>
<li><strong>Good Til Canceled (GTC):</strong> an order that would sit until filled or canceled. Not used live today.</li>
<li><strong>T0:</strong> trusted match start, not a random feed update.</li>
<li><strong>Dog / favorite:</strong> the cheaper Yes vs the more expensive Yes at T0.</li>
<li><strong>Flatten:</strong> buy the other side of the same ticket on the same venue so a one-leg fill is not a naked bet.</li>
<li><strong>Send line / NET_MAX:</strong> live after-fee cap, {_esc(send_line)} today.</li>
</ul>
<p class="note">Research only. Not gold. Not DailyRun. 1 contract. Immediate or Cancel. Constants read from source on write; if a knob changes, regenerate this page.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    path = write_page()
    _copy_g(path)
    print(path)
    print("send_line", live_lock_orders.send_line())
    print("MAX_OPEN_LOCKS", live_lock_orders.MAX_OPEN_LOCKS)
    print("MAX_OPEN_B_MATCHES", live_strategy_b.MAX_OPEN_B_MATCHES)
    print("D", live_strategy_b.D)
    print("C", live_strategy_b.C_LO, live_strategy_b.C_HI)
    print("TICK", live_lock_orders.WATCH_TICK_SEC, live_strategy_b.TICK_SEC)


if __name__ == "__main__":
    main()
