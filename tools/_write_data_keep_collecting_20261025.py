"""Keep-collecting tape note. Does not place orders. Does not restart B or E."""
from __future__ import annotations

import html
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "data_keep_collecting_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/data_keep_collecting_20261025.html"
)
LOCAL = "local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw"

ASKED = (
    "Thanks for the report. Keep storing whatever data we can so we can "
    "continue to refine strategies on real-world data."
)
PLAIN = (
    "The live collector is still writing price ticks and order logs on this PC "
    "so later we can replay what the books looked like. Ticks stay local "
    "(thousands of files, not synced to Drive). Drive only gets this short HTML "
    "stamp. We added a few cheap extra fields on the existing orders log: both "
    "Yes prices plus all-in cost at every T0 send or skip, and both Yes prices "
    "at every 50-cross attempt (so a Patel 80¢ / 81¢ can be rebuilt). Lock dual "
    "REST size and system E posts were already on that log. Strategy knobs are "
    "unchanged. We did not start a second Tennis crossover, did not sell, and "
    "did not turn E off."
)

TOKENS = (
    "t0_allin_c_over_105",
    "cross_fav_not_below_dog",
    "poly_size_lt_qty_skip",
    "hard_miss_abort",
    "poly_fok_partial_unexpected",
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total:
        cells = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def mtime(path: Path) -> str:
    if not path.exists():
        return "missing"
    stamp = datetime.fromtimestamp(path.stat().st_mtime, ET)
    size = path.stat().st_size
    if size >= 1_000_000:
        human = f"{size / 1_000_000:.1f} MB"
    elif size >= 1000:
        human = f"{size / 1000:.1f} KB"
    else:
        human = f"{size} B"
    return f"{stamp.strftime('%Y-%m-%d %H:%M:%S ET')} · {human}"


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def last_jsonl_row(path: Path, tail: int = 12000) -> dict:
    if not path.exists():
        return {}
    data = path.read_bytes()
    chunk = data[-tail:].decode("utf-8", errors="replace")
    for line in reversed(chunk.strip().splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            return row
    return {}


def count_tokens(path: Path, tokens: tuple[str, ...], tail: int | None = None) -> Counter:
    hits: Counter = Counter()
    if not path.exists():
        return hits
    data = path.read_bytes()
    if tail is not None and len(data) > tail:
        data = data[-tail:]
    text = data.decode("utf-8", errors="replace")
    for token in tokens:
        hits[token] = text.count(token)
    return hits


def snapshot() -> dict:
    pollers = read_json(RAW / "live_pollers_status.json")
    b_pid = read_json(RAW / "strategy_b.pid")
    e_pid = read_json(RAW / "tennis_t0_dog.pid")
    sup_pid = read_json(RAW / "live_supervisor.pid")
    e_watch = read_json(RAW / "tennis_t0_dog_watch.json")
    b_watch = read_json(RAW / "strategy_b_watch.json")
    shards = sorted((RAW / "price_memory").rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    tennis_today = RAW / "price_memory" / datetime.now(ET).strftime("%Y-%m-%d") / "tennis.jsonl"
    tick = last_jsonl_row(tennis_today if tennis_today.exists() else (shards[0] if shards else Path()))
    orders_events: Counter = Counter()
    sent_quote = 0
    sent_n = 0
    systems: Counter = Counter()
    token_orders: Counter = Counter()
    if (RAW / "orders.jsonl").exists():
        with (RAW / "orders.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                ev = str(row.get("event") or "")
                orders_events[ev] += 1
                blob = json.dumps(row)
                for token in TOKENS:
                    if token in blob:
                        token_orders[token] += 1
                if ev == "sent":
                    sent_n += 1
                    if row.get("quote_size") not in (None, ""):
                        sent_quote += 1
                    systems[str(row.get("system") or "(empty)")] += 1
    b_log = count_tokens(RAW / "strategy_b.log", TOKENS)
    sup_log = count_tokens(RAW / "live_supervisor.log", TOKENS, tail=2_000_000)
    return {
        "now": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET"),
        "supervisor_pid": sup_pid.get("pid") or pollers.get("supervisor_pid") or "",
        "supervisor_started": sup_pid.get("started_at") or "",
        "poller_count": pollers.get("live_count") or len(pollers.get("games") or []),
        "pollers_updated": pollers.get("updated_at") or "",
        "b_pid": b_pid.get("pid") or b_watch.get("pid") or "",
        "b_started": b_pid.get("started_at") or "",
        "e_pid": e_pid.get("pid") or e_watch.get("pid") or "",
        "e_started": e_pid.get("started_at") or "",
        "e_open": e_watch.get("currently_open"),
        "e_last_send": e_watch.get("last_send") or "",
        "tick_at": tick.get("seen_at") or "",
        "tick_game": tick.get("game") or "",
        "tick_venue": tick.get("venue") or "",
        "tick_side": tick.get("side") or "",
        "shard_n": len(shards),
        "newest_shard": str(shards[0].relative_to(RAW / "price_memory")) if shards else "",
        "orders_events": dict(orders_events),
        "sent_quote": sent_quote,
        "sent_n": sent_n,
        "systems": dict(systems),
        "token_orders": dict(token_orders),
        "b_log": dict(b_log),
        "sup_log": dict(sup_log),
        "files": [
            ("price_memory shards (local ticks)", RAW / "price_memory" / datetime.now(ET).strftime("%Y-%m-%d") / "tennis.jsonl"),
            ("live_checks.jsonl", RAW / "live_checks.jsonl"),
            ("orders.jsonl", RAW / "orders.jsonl"),
            ("order_io.jsonl", RAW / "order_io.jsonl"),
            ("considerations.json", RAW / "considerations.json"),
            ("call_metrics.jsonl", RAW / "call_metrics.jsonl"),
            ("live_moves.jsonl", RAW / "live_moves.jsonl"),
            ("cfb_game_results.jsonl (settlements)", RAW / "cfb_game_results.jsonl"),
            ("odds_cross_settlements_20261020.json", RAW / "odds_cross_settlements_20261020.json"),
            ("strategy_b.log", RAW / "strategy_b.log"),
            ("strategy_b_watch.json", RAW / "strategy_b_watch.json"),
            ("tennis_t0_dog.log", RAW / "tennis_t0_dog.log"),
            ("tennis_t0_dog_watch.json", RAW / "tennis_t0_dog_watch.json"),
            ("live_pollers_status.json", RAW / "live_pollers_status.json"),
            ("lock_last_skip.json", RAW / "lock_last_skip.json"),
        ],
    }


def main() -> None:
    snap = snapshot()
    files = table(
        [("File", "text"), ("Last write", "text")],
        [[esc(label), esc(mtime(path))] for label, path in snap["files"]],
    )
    skip_rows = []
    for token in TOKENS:
        skip_rows.append(
            [
                esc(token),
                str(snap["token_orders"].get(token, 0)),
                str(snap["b_log"].get(token, 0)),
                str(snap["sup_log"].get(token, 0)),
            ]
        )
    skips = table(
        [
            ("Token", "text"),
            ("orders.jsonl", "num"),
            ("strategy_b.log", "num"),
            ("supervisor.log tail", "num"),
        ],
        skip_rows,
    )
    events = table(
        [("orders.jsonl event", "text"), ("Count", "num")],
        [[esc(name), str(n)] for name, n in sorted(snap["orders_events"].items())],
    )
    new_fields = table(
        [("Gap", "text"), ("What we did", "text")],
        [
            [
                "T0 send/skip: both Yes asks + all-in C",
                "New <code>event=t0</code> rows on <code>orders.jsonl</code> (yes_a, yes_b, all_in_c). "
                "Was only a text line in strategy_b.log / skip_reason on the watch file.",
            ],
            [
                "50-cross attempt: both Yes asks",
                "New <code>event=cross</code> rows (dog_yes, fav_yes). Patel 80/81 reconstructable. "
                "Once per distinct ask pair on skip; always on send.",
            ],
            [
                "REST ask size on lock duals",
                "Already there. Sent rows copy <code>quote_size</code> "
                f"({snap['sent_quote']} of {snap['sent_n']} sent). "
                "hard_miss_abort has hard_size / easy_size. Not duplicated.",
            ],
            [
                "E sends when E exists",
                "Already there. POSTs go through orders.jsonl sent with "
                "<code>system=tennis_t0_dog</code>. Zero E posts so far. Poly size skips now also "
                "append <code>event=e</code>. Did not start a second E.",
            ],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Keep collecting tape — 25 Oct 2026</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.callout h2 {{ margin: 0 0 6px; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Keep collecting the live tape</h1>
<p class="note">Written {esc(snap['now'])}. Times America/New_York. Research-candidate live. Not gold. Not DailyRun. No sells. No second Strategy B. E left running. Knobs unchanged (C_HI 1.05, FOK, hard-first, 50-cross fav-below-dog, leftover no deadline). No secrets.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout ok">
<h2>Collection still on</h2>
<ul>
<li><strong>Yes.</strong> Last tennis tick {esc(snap['tick_at'] or '—')} · {esc(snap['tick_game'] or '—')} · {esc(snap['tick_venue'] or '—')} {esc(snap['tick_side'] or '')}.</li>
<li>Supervisor PID {esc(snap['supervisor_pid'])} (started {esc(snap['supervisor_started'])}). Live pollers {esc(snap['poller_count'])}. Status {esc(snap['pollers_updated'])}.</li>
<li>Tennis crossover B PID {esc(snap['b_pid'])} (started {esc(snap['b_started'])}). One process. Not restarted this job.</li>
<li>System E (Tennis T0 dog) PID {esc(snap['e_pid'])} (started {esc(snap['e_started'])}). Open {esc(snap['e_open'])}. Last send {esc(snap['e_last_send'] or 'none')}. Not turned off. Not duplicated.</li>
<li>Ticks stay under <code>{esc(LOCAL)}/price_memory/YYYY-MM-DD/{{sport}}.jsonl</code> ({esc(snap['shard_n'])} shards; newest {esc(snap['newest_shard'])}). Not copied to Drive.</li>
</ul>
</div>

<h2>Where it lives</h2>
{SWIPE_NOTE_HTML}
<p class="note">Click column headers to sort. Local path only. Drive HTML stamps only.</p>
{files}

<h2>Skip tokens</h2>
{SWIPE_NOTE_HTML}
{skips}
<p class="note"><code>poly_fok_partial_unexpected</code> is wired (record_send_skip) and has not fired. New <code>event=t0</code> / <code>event=cross</code> rows start after the next B restart; this job did not restart B.</p>

<h2>New fields (cheap, existing jsonl)</h2>
{SWIPE_NOTE_HTML}
{new_fields}

<h2>orders.jsonl event mix</h2>
{SWIPE_NOTE_HTML}
{events}

<h2>What we did not do</h2>
<ul>
<li>Did not change C_HI 1.05, FOK, hard-first, 50-cross fav-below-dog, leftover no deadline.</li>
<li>Did not start a second <code>live_strategy_b.py</code>. Did not sell. Did not turn E off or start a second E.</li>
<li>Did not sync tick files to Drive.</li>
</ul>

<p class="note">Sources: local raw under <code>{esc(LOCAL)}</code>. Code: <code>tools/live_strategy_b.py</code> tape_t0 / tape_cross, <code>tools/live_lock_orders.py</code> record_research_row, <code>tools/live_t0_yes.py</code> E skip tape. Tests in <code>tools/test_live_strategy_b.py</code>. Live B PID {esc(snap['b_pid'])}. E PID {esc(snap['e_pid'])}. File URL {esc(FILE_URL)}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(PAGE)


if __name__ == "__main__":
    main()
