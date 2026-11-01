"""Lock gap (A): first-fill then second-miss rate before vs after thin-first.

Does not send, flatten, leftover-GTC, retune, or start a second B.
Does not print secrets. Does not commit.
"""
from __future__ import annotations

import html as html_lib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_gap_thin_first_oneleg_20261029.html"
EXTRACT = RAW / "lock_gap_thin_first_oneleg_20261029.json"

ASKED = (
    "what percent of lock gap trades hit the first order succesfully but failed "
    "on the second order PRIOR to us prioritizing the thin side first? what percent "
    "of lock gap trades hit the first order succesfully but failed on the second "
    "order AFTER prioritizing the thin side first?"
)
PLAIN = (
    "A lock gap (System A) tries to buy both sides of the same result in two shops "
    "so one side pays $1 and we keep the leftover after fees. We send one immediate-"
    "or-cancel (IOC: fill now or cancel) then the other. The percent here is not "
    "among every look: it is only among attempts that filled the first ticket. Of "
    "those, how often did the second ticket miss? Empty IOC (neither filled) is "
    "shown but is not in that percent. Before thin-first, both tickets left at the "
    "same instant; first vs second is which shop’s HTTP left first. After thin-first, "
    "first is the thinner displayed book (hard) and second is the thicker book (easy)."
)

B_STEPS = {"b-t0", "b-cross", "b-leftover-yes", "b-fav"}
C_STEPS = {"c-t0"}
D_STEPS = {"d-t0"}
E_STEPS = {"e-t0"}
FLAT_STEPS = {"flatten", "extra-flatten"}
LEFTOVER_STEPS = {"watch", "recovery"}
# Original dual-IOC legs of a lock pair (not flatten, not leftover hedge).
DUAL_STEPS = {"", "hard", "easy", "websocket", "book", "midway", "simultaneous"}
NON_LOCK_PREFIX = ("tennis-b", "cfb-favorite", "spread-t0", "tennis-t0-dog", "tennis_t0")
FOUR = Decimal("0.0001")
# Code freeze HTML was Written 20:05 ET. First restart-lock after that is the deploy.
CODE_WIRED = datetime(2026, 10, 24, 20, 5, 0, tzinfo=ET)
DOCUMENTED_RESTART = datetime(2026, 10, 24, 20, 6, 16, tzinfo=ET)
# Oct 26 latency tweak: Drive HTML no longer rebuilds between hard IOC and easy IOC.
HTML_LATENCY_TWEAK = datetime(2026, 10, 26, 0, 0, tzinfo=ET)


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    text = "" if value is None else str(value)
    extra = ' class="num"' if kind == "num" else ""
    return f"<td{extra}>{esc(text)}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(
            td(cell, headers[i][1] if i < len(headers) else "text")
            for i, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    if total is not None:
        cells = "".join(
            td(cell, headers[i][1] if i < len(headers) else "text")
            for i, cell in enumerate(total)
        )
        body.append(f'<tr class="total-row">{cells}</tr>')
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def money4(value) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    return format(number.quantize(FOUR, rounding=ROUND_HALF_UP), "f")


def pct(numer: int, denom: int) -> str:
    if denom <= 0:
        return "—"
    return f"{(100 * Decimal(numer) / Decimal(denom)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def parse_dt(raw) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        stamp = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def fmt_ts(stamp: datetime | None) -> str:
    if stamp is None:
        return "—"
    return stamp.strftime("%Y-%m-%d %H:%M:%S ET")


def dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def is_b_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or row.get("source") or "").strip().lower().replace(" ", "_")
    if system in {"b", "strategy_b", "strategy-b", "tennis_crossover", "tennis-crossover"}:
        return True
    return bool(row.get("_strategy_b")) or key.startswith("tennis-b") or step.startswith("b-") or step in B_STEPS


def is_c_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "cfb_favorite" or key.startswith("cfb-favorite") or step in C_STEPS or step.startswith("c-")


def is_d_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "spread_t0" or key.startswith("spread-t0") or step in D_STEPS or step.startswith("d-")


def is_e_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "tennis_t0_dog" or key.startswith("tennis-t0-dog") or step in E_STEPS or step.startswith("e-")


def is_lock_row(row: dict) -> bool:
    if is_b_row(row) or is_c_row(row) or is_d_row(row) or is_e_row(row):
        return False
    key = str(row.get("bet_key") or "")
    if key.startswith(NON_LOCK_PREFIX):
        return False
    return True


def dual_step(row: dict) -> bool:
    step = str(row.get("step") or "").strip().lower()
    if step in FLAT_STEPS or step in LEFTOVER_STEPS:
        return False
    if step.startswith(("b-", "c-", "d-", "e-")):
        return False
    return step in DUAL_STEPS


def venue_true_fill(sent: dict) -> bool:
    """Venue-confirm qty >= 1. HTTP 200/201 alone is not a fill."""
    if sent.get("confirm_known") is True:
        qty = dec(sent.get("confirm_qty"))
        return qty is not None and qty >= 1
    tape = dec(sent.get("tape_qty"))
    if tape is not None:
        return tape >= 1
    return False


def load_settled() -> dict:
    path = RAW / "settled_pnl.json"
    if not path.exists():
        return {}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(blob, dict) and isinstance(blob.get("orders"), dict):
        blob = blob["orders"]
    if not isinstance(blob, dict):
        return {}
    return {str(key): dict(row) for key, row in blob.items() if isinstance(row, dict)}


def git_log_hard_first() -> list[str]:
    lines = []
    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                "--all",
                "--date=iso-local",
                "--pretty=format:%ci %h %s",
                "-S",
                "_pick_hard_leg",
                "--",
                "tools/live_lock_orders.py",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return [f"git log failed: {type(exc).__name__}"]
    text = (proc.stdout or "").strip()
    if not text:
        lines.append(
            "Git has no commit that introduces _pick_hard_leg (live_*.py dump is 2026-10-18; "
            "later freezes are tape / HTML Written lines)."
        )
        return lines
    lines.extend(text.splitlines()[:8])
    return lines


def scan_supervisor_starts() -> list[datetime]:
    found: list[datetime] = []
    for name in ("live_supervisor.log", "live_supervisor.console.log"):
        path = RAW / name
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if "supervisor start" not in line:
                        continue
                    stamp = parse_dt(line.split(" ", 1)[0])
                    if stamp and stamp.date().isoformat() == "2026-10-24" and stamp.hour >= 19:
                        found.append(stamp)
        except OSError:
            continue
    return sorted(found)


def first_log_hard_first() -> datetime | None:
    paths = [
        RAW / "overnight_scan.log",
        RAW / "overnight_scan.console.log",
        RAW / "live_supervisor.log",
        RAW / "live_supervisor.console.log",
    ]
    first = None
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if "order hard-first send" not in line:
                        continue
                    stamp = parse_dt(line.split(" ", 1)[0])
                    if stamp and (first is None or stamp < first):
                        first = stamp
        except OSError:
            continue
    return first


def _has_step(events: list[dict], step: str) -> bool:
    want = step.lower()
    return any(
        row.get("event") == "sent" and str(row.get("step") or "").lower() == want
        for row in events
    )


def _waiting_for_easy(cluster: dict) -> bool:
    events = cluster.get("events") or []
    if not _has_step(events, "hard"):
        return False
    if _has_step(events, "easy"):
        return False
    terminals = {row.get("event") for row in events}
    if terminals & {"hard_miss_abort", "both_unfilled", "one_leg", "flatten_filled"}:
        return False
    return True


def cluster_lock_attempts(orders: list[dict]) -> list[dict]:
    """One lock attempt per bet_key. Other games' claims must not split hard/easy."""
    open_by: dict[str, dict] = {}
    clusters: list[dict] = []

    def flush(key: str) -> None:
        item = open_by.pop(key, None)
        if item:
            clusters.append(item)

    keep_events = {
        "sent",
        "filled",
        "one_leg",
        "both_unfilled",
        "hard_miss_abort",
        "flatten_filled",
        "flatten_miss",
        "skip",
        "orders_off",
    }

    for row in orders:
        if not is_lock_row(row):
            continue
        event = str(row.get("event") or "")
        key = str(row.get("bet_key") or "")
        if not key:
            continue
        current = open_by.get(key)
        if event == "claim":
            if current is None:
                open_by[key] = {"claim": row, "events": []}
            elif _waiting_for_easy(current):
                continue
            elif any(item.get("event") == "sent" for item in current.get("events") or []):
                flush(key)
                open_by[key] = {"claim": row, "events": []}
            else:
                current["claim"] = row
            continue
        if event not in keep_events:
            continue
        if current is None:
            if event in {"sent", "hard_miss_abort", "filled", "one_leg", "both_unfilled"}:
                open_by[key] = {
                    "claim": {
                        "bet_key": key,
                        "game": row.get("game") or "",
                        "sport": row.get("sport") or "",
                    },
                    "events": [row],
                }
            continue
        current["events"].append(row)
        if event in {"hard_miss_abort", "both_unfilled", "one_leg"}:
            flush(key)
    for key in list(open_by):
        flush(key)
    return clusters


def attempt_time(claim: dict, duals: list[dict], events: list[dict]) -> datetime | None:
    stamps = []
    for sent in duals:
        stamps.append(parse_dt(sent.get("sent_at") or sent.get("quote_seen_at")))
    stamps.append(parse_dt(claim.get("compared_at") or claim.get("at")))
    for row in events:
        stamps.append(parse_dt(row.get("at") or row.get("sent_at") or row.get("compared_at")))
    stamps = [item for item in stamps if item is not None]
    return min(stamps) if stamps else None


def classify_attempt(cluster: dict, cutover: datetime) -> dict | None:
    claim = cluster.get("claim") or {}
    events = cluster.get("events") or []
    duals = [
        row
        for row in events
        if row.get("event") == "sent" and dual_step(row)
    ]
    hard_abort = [row for row in events if row.get("event") == "hard_miss_abort"]
    if not duals and not hard_abort:
        return None

    filled_events = {
        (str(row.get("venue") or "").lower(), str(row.get("instrument") or ""))
        for row in events
        if row.get("event") == "filled"
    }

    def leg_filled(sent: dict) -> bool:
        if venue_true_fill(sent):
            return True
        key = (str(sent.get("venue") or "").lower(), str(sent.get("instrument") or ""))
        if key in filled_events and key[0]:
            return True
        return False

    by_leg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sent in duals:
        key = (str(sent.get("venue") or "").lower(), str(sent.get("instrument") or ""))
        by_leg[key].append(sent)

    legs = []
    for key, sents in by_leg.items():
        sents_sorted = sorted(
            sents,
            key=lambda row: (
                parse_dt(row.get("sent_at")) or datetime.max.replace(tzinfo=ET),
                int(row.get("attempt") or 1),
            ),
        )
        first_sent = sents_sorted[0]
        steps = {str(item.get("step") or "").lower() for item in sents_sorted}
        filled = any(leg_filled(item) for item in sents_sorted)
        legs.append(
            {
                "venue": key[0],
                "instrument": key[1],
                "sent": first_sent,
                "sents": sents_sorted,
                "steps": steps,
                "filled": filled,
                "sent_at": parse_dt(first_sent.get("sent_at"))
                or parse_dt(first_sent.get("quote_seen_at")),
                "order_id": str(first_sent.get("order_id") or ""),
                "quote_size": first_sent.get("quote_size"),
                "limit": first_sent.get("limit_price"),
            }
        )

    steps_all = set()
    for leg in legs:
        steps_all |= set(leg["steps"])
    thin_first = "hard" in steps_all or "easy" in steps_all or bool(hard_abort)

    if thin_first:
        hard = next((leg for leg in legs if "hard" in leg["steps"]), None)
        easy = next((leg for leg in legs if "easy" in leg["steps"]), None)
        first = hard
        second = easy
        if first is None and legs:
            legs_sorted = sorted(
                legs,
                key=lambda leg: leg["sent_at"] or datetime.max.replace(tzinfo=ET),
            )
            first = legs_sorted[0]
            second = legs_sorted[1] if len(legs_sorted) > 1 else None
    else:
        legs_sorted = sorted(
            legs,
            key=lambda leg: leg["sent_at"] or datetime.max.replace(tzinfo=ET),
        )
        first = legs_sorted[0] if legs_sorted else None
        second = legs_sorted[1] if len(legs_sorted) > 1 else None

    first_filled = bool(first and first["filled"])
    second_posted = second is not None
    second_filled = bool(second and second["filled"])
    flatten_ok = any(row.get("event") == "flatten_filled" for row in events)
    flatten_miss = any(row.get("event") == "flatten_miss" for row in events)
    one_leg = any(row.get("event") == "one_leg" for row in events)
    both_unfilled = any(row.get("event") == "both_unfilled" for row in events)

    if first_filled and second_filled:
        outcome = "both_fill"
    elif first_filled and not second_filled:
        outcome = "first_fill_second_miss"
    elif not first_filled and second_filled:
        outcome = "first_miss_second_fill"
    else:
        outcome = "empty_ioc"

    send_at = attempt_time(claim, duals, events)
    period = "after" if send_at and send_at >= cutover else "before"
    if send_at is None:
        period = "after" if thin_first else "before"

    second_how = ""
    if outcome == "first_fill_second_miss":
        if second_posted:
            second_how = "second posted, venue miss"
        else:
            second_how = "second never posted"
        if flatten_ok:
            second_how += "; flattened"
        elif flatten_miss or one_leg:
            second_how += "; leftover"

    return {
        "game": str(claim.get("game") or (first or {}).get("sent", {}).get("game") or ""),
        "sport": str(claim.get("sport") or ""),
        "market": str(claim.get("market_type") or ""),
        "bet_key": str(claim.get("bet_key") or ""),
        "send_at": send_at,
        "period": period,
        "thin_first": thin_first,
        "outcome": outcome,
        "first_filled": first_filled,
        "second_posted": second_posted,
        "second_filled": second_filled,
        "second_how": second_how,
        "flatten_ok": flatten_ok,
        "flatten_miss": flatten_miss,
        "one_leg": one_leg,
        "both_unfilled": both_unfilled,
        "hard_abort": bool(hard_abort),
        "n_dual_http": len(duals),
        "n_legs": len(legs),
        "first_venue": (first or {}).get("venue") or "",
        "second_venue": (second or {}).get("venue") or "",
        "first_size": (first or {}).get("quote_size") or "",
        "second_size": (second or {}).get("quote_size") or "",
        "first_oid": (first or {}).get("order_id") or "",
        "second_oid": (second or {}).get("order_id") or "",
        "order_ids": [leg["order_id"] for leg in legs if leg.get("order_id")],
        "flatten_oids": [
            str(row.get("order_id") or "")
            for row in events
            if row.get("event") == "sent" and str(row.get("step") or "").lower() in FLAT_STEPS
            and str(row.get("order_id") or "")
        ],
        "watch_oids": [
            str(row.get("order_id") or "")
            for row in events
            if row.get("event") == "sent" and str(row.get("step") or "").lower() in LEFTOVER_STEPS
            and str(row.get("order_id") or "")
        ],
    }


def attach_pnl(attempts: list[dict], settled: dict) -> None:
    for att in attempts:
        ids = [oid for oid in (att.get("order_ids") or []) + (att.get("flatten_oids") or []) if oid]
        pnls = []
        n_settled = 0
        n_open = 0
        for oid in ids:
            row = settled.get(oid) or {}
            status = str(row.get("status") or "").lower()
            pnl = dec(row.get("pnl"))
            if status in {"win", "lose", "void"} or pnl is not None:
                n_settled += 1
                if pnl is not None and status != "void":
                    pnls.append(pnl)
                elif status == "void":
                    pnls.append(Decimal("0"))
            else:
                n_open += 1
        att["pnl_sum"] = sum(pnls, Decimal("0")) if pnls else None
        att["pnl_n"] = len(pnls)
        att["pnl_open"] = n_open
        att["pnl_settled"] = n_settled


def summarize(attempts: list[dict]) -> dict:
    n = len(attempts)
    empty = sum(1 for a in attempts if a["outcome"] == "empty_ioc")
    both = sum(1 for a in attempts if a["outcome"] == "both_fill")
    first_miss_second = sum(1 for a in attempts if a["outcome"] == "first_miss_second_fill")
    first_fill = sum(1 for a in attempts if a["first_filled"])
    second_miss = sum(1 for a in attempts if a["outcome"] == "first_fill_second_miss")
    second_posted_miss = sum(
        1
        for a in attempts
        if a["outcome"] == "first_fill_second_miss" and a["second_posted"]
    )
    second_unsent = sum(
        1
        for a in attempts
        if a["outcome"] == "first_fill_second_miss" and not a["second_posted"]
    )
    flat_ok = sum(1 for a in attempts if a["outcome"] == "first_fill_second_miss" and a["flatten_ok"])
    leftover = sum(
        1
        for a in attempts
        if a["outcome"] == "first_fill_second_miss" and (a["flatten_miss"] or a["one_leg"]) and not a["flatten_ok"]
    )
    pnls = [
        a["pnl_sum"]
        for a in attempts
        if a["outcome"] == "first_fill_second_miss" and a.get("pnl_sum") is not None
    ]
    avg = (sum(pnls, Decimal("0")) / Decimal(len(pnls))) if pnls else None
    any_fill = first_fill + first_miss_second
    one_sided = second_miss + first_miss_second
    return {
        "n_attempts": n,
        "empty_ioc": empty,
        "both_fill": both,
        "first_miss_second_fill": first_miss_second,
        "n_first_fill": first_fill,
        "n_second_miss": second_miss,
        "rate": pct(second_miss, first_fill),
        "any_fill": any_fill,
        "one_sided": one_sided,
        "one_sided_rate": pct(one_sided, any_fill),
        "second_posted_miss": second_posted_miss,
        "second_unsent": second_unsent,
        "flatten_ok": flat_ok,
        "leftover": leftover,
        "avg_pnl": avg,
        "n_pnl": len(pnls),
    }


def find_cutover(orders: list[dict]) -> dict:
    first_hard_sent = None
    first_hard_abort = None
    first_hard_game = ""
    for row in orders:
        if not is_lock_row(row):
            continue
        event = str(row.get("event") or "")
        step = str(row.get("step") or "").lower()
        if event == "sent" and step == "hard":
            stamp = parse_dt(row.get("sent_at") or row.get("quote_seen_at"))
            if stamp and (first_hard_sent is None or stamp < first_hard_sent):
                first_hard_sent = stamp
                first_hard_game = str(row.get("game") or row.get("bet_key") or "")
        if event == "hard_miss_abort":
            stamp = parse_dt(row.get("at") or row.get("sent_at") or row.get("compared_at"))
            if stamp and (first_hard_abort is None or stamp < first_hard_abort):
                first_hard_abort = stamp
    if first_hard_abort is None and first_hard_sent is not None:
        first_hard_abort = first_hard_sent
    log_line = first_log_hard_first()
    restarts = scan_supervisor_starts()
    git_lines = git_log_hard_first()
    after_wire = [stamp for stamp in restarts if stamp >= CODE_WIRED]
    if after_wire:
        cutover = min(after_wire)
        source = (
            f"live_supervisor.log supervisor start {fmt_ts(cutover)} — first restart after "
            f"hard-first HTML Written 20:05 ET (restart-lock). Matches lock_quiet_since_20261021.html."
        )
    else:
        cutover = DOCUMENTED_RESTART
        source = (
            "Supervisor restart 2026-10-24 20:06:16 ET from lock_quiet_since_20261021.html "
            "(hard-first wired that evening; restart-lock). Current supervisor log did not "
            "keep that line."
        )
    return {
        "cutover": cutover,
        "source": source,
        "first_hard_sent": first_hard_sent,
        "first_hard_game": first_hard_game,
        "first_hard_abort": first_hard_abort,
        "first_log_line": log_line,
        "restarts": restarts,
        "git": git_lines,
        "html_written": CODE_WIRED,
    }


def write_page() -> Path:
    now = datetime.now(ET)
    orders = load_jsonl(RAW / "orders.jsonl")
    cut = find_cutover(orders)
    cutover = cut["cutover"]
    clusters = cluster_lock_attempts(orders)
    attempts = []
    for cluster in clusters:
        att = classify_attempt(cluster, cutover)
        if att:
            attempts.append(att)
    attach_pnl(attempts, load_settled())
    before = [a for a in attempts if a["period"] == "before"]
    after = [a for a in attempts if a["period"] == "after"]
    # Robustness: observed rule vs clock, in case an old helper kept simultaneous.
    after_not_thin = [a for a in after if not a["thin_first"]]
    before_thin = [a for a in before if a["thin_first"]]
    sb = summarize(before)
    sa = summarize(after)

    miss_rows_before = [
        a for a in before if a["outcome"] == "first_fill_second_miss"
    ]
    miss_rows_after = [
        a for a in after if a["outcome"] == "first_fill_second_miss"
    ]

    def miss_table(rows: list[dict]) -> str:
        body = []
        for a in rows:
            body.append(
                [
                    a["send_at"].strftime("%Y-%m-%d %H:%M:%S") if a["send_at"] else "",
                    a["sport"],
                    a["game"],
                    a["market"],
                    a["first_venue"],
                    a["second_venue"] or "—",
                    a["first_size"] or "—",
                    a["second_size"] or "—",
                    a["second_how"],
                    "yes" if a["flatten_ok"] else ("leftover" if a["one_leg"] or a["flatten_miss"] else "—"),
                    money4(a.get("pnl_sum")) if a.get("pnl_sum") is not None else "—",
                    "thin-first" if a["thin_first"] else "simultaneous",
                ]
            )
        return table(
            [
                ("Send ET", "date"),
                ("Sport", "text"),
                ("Game", "text"),
                ("Market", "text"),
                ("First venue", "text"),
                ("Second venue", "text"),
                ("First size", "num"),
                ("Second size", "num"),
                ("Second miss how", "text"),
                ("Flatten / leftover", "text"),
                ("With-fee P&L $", "num"),
                ("Send rule", "text"),
            ],
            body,
        )

    def headline(label: str, s: dict) -> str:
        return (
            f"<p><strong>{esc(label)}:</strong> {esc(s['rate'])} "
            f"({esc(s['n_second_miss'])} second-misses / {esc(s['n_first_fill'])} first-fills). "
            f"Empty IOC {esc(s['empty_ioc'])} of {esc(s['n_attempts'])} dual attempts "
            f"(not in the percent). Both-fill {esc(s['both_fill'])}. "
            f"Among any dual fill: one-sided {esc(s['one_sided_rate'])} "
            f"({esc(s['one_sided'])}/{esc(s['any_fill'])}). "
            f"With-fee avg P&amp;L on settled second-misses: "
            f"{esc(money4(s['avg_pnl']))} (N={esc(s['n_pnl'])}). "
            f"Of the second-misses, {esc(s['second_posted_miss'])} posted the second IOC and missed; "
            f"{esc(s['second_unsent'])} never posted the second (gap closed / flatten / abort easy).</p>"
        )

    caveat = ""
    if sa["n_first_fill"] < 30:
        caveat = (
            f"<p class=\"banner\"><strong>Small after sample.</strong> Only "
            f"{esc(sa['n_first_fill'])} first-fills after thin-first. Treat the after percent as "
            f"directional, not a horse-race.</p>"
        )

    mix_note = ""
    if after_not_thin or before_thin:
        mix_note = (
            f"<p class=\"note\">Clock vs observed rule: {esc(len(after_not_thin))} after-cutover "
            f"attempts still look simultaneous (no hard/easy step); {esc(len(before_thin))} "
            f"before-cutover attempts already look thin-first. Split is by send time vs cutover "
            f"as asked; those mix rows stay in their clock bucket.</p>"
        )

    git_html = "<br>".join(esc(line) for line in (cut["git"] or ["(none)"]))
    restart_html = ", ".join(esc(fmt_ts(item)) for item in cut["restarts"]) or "none in current live_supervisor.log after 19:00 ET 24 Oct (log may have rotated; stamp HTML still cites 20:06:16)."

    summary_rows = [
        [
            "Before thin-first",
            sb["n_attempts"],
            sb["empty_ioc"],
            sb["both_fill"],
            sb["first_miss_second_fill"],
            sb["n_first_fill"],
            sb["n_second_miss"],
            sb["rate"],
            sb["one_sided_rate"],
            sb["second_posted_miss"],
            sb["second_unsent"],
            sb["flatten_ok"],
            sb["leftover"],
            money4(sb["avg_pnl"]),
            sb["n_pnl"],
        ],
        [
            "After thin-first",
            sa["n_attempts"],
            sa["empty_ioc"],
            sa["both_fill"],
            sa["first_miss_second_fill"],
            sa["n_first_fill"],
            sa["n_second_miss"],
            sa["rate"],
            sa["one_sided_rate"],
            sa["second_posted_miss"],
            sa["second_unsent"],
            sa["flatten_ok"],
            sa["leftover"],
            money4(sa["avg_pnl"]),
            sa["n_pnl"],
        ],
    ]

    payload = {
        "written_at": now.isoformat(timespec="seconds"),
        "cutover": cutover.isoformat(timespec="seconds"),
        "before": sb,
        "after": sa,
        "n_attempts": len(attempts),
        "first_hard_sent": cut["first_hard_sent"].isoformat() if cut["first_hard_sent"] else None,
    }
    try:
        EXTRACT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        pass

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Lock gap thin-first one-leg rates — 29 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.hl {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Lock gap: first fill, second miss — before vs after thin-first</h1>
<p class="tiny">Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. America/New_York. Venue-true fills (confirm qty ≥ 1). Did not send, flatten, leftover-GTC, retune, or start a second B.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<h2>Headline</h2>
{headline("Before thin-first", sb)}
{headline("After thin-first", sa)}
<p>Cutover: <strong>{esc(fmt_ts(cutover))}</strong>. Split by first dual-IOC send time vs that clock.</p>
</div>
{caveat}

<h2>Cutover</h2>
<p>Thin / low displayed size first, thick / high displayed size second is sequential hard-first in
<code>tools/live_lock_orders.py</code> (<code>_pick_hard_leg</code>: smaller REST ask size, then historical miss-venue rank, then pricier cash). Simultaneous both-at-once was the default before that.</p>
{table(
    [("Fact", "text"), ("When ET", "date"), ("Source", "text")],
    [
        ["Code freeze HTML (wired)", fmt_ts(cut["html_written"]), "lock_hard_leg_first_20261024.html Written 20:05 ET"],
        ["Live-process start / deploy (cutover used here)", fmt_ts(cutover), cut["source"]],
        ["Supervisor starts 24 Oct after 19:00 in current log", restart_html, "live_supervisor.log"],
        ["First live step=hard IOC", fmt_ts(cut["first_hard_sent"]), "Kachmazov vs Kim Polymarket hard miss (orders.jsonl)"],
        ["First hard_miss_abort", fmt_ts(cut["first_hard_abort"]), "orders.jsonl"],
        ["First overnight_scan “order hard-first send” line", fmt_ts(cut["first_log_line"]), "overnight_scan.log (catalog/NFL; tennis helpers log elsewhere)"],
        ["Later tweak (not a new thin-first rule)", "2026-10-26", "Drive HTML no longer rebuilds between hard IOC and easy IOC (Bobichon ~2 min delay). Order of legs unchanged."],
    ],
)}
<p class="note">Git: {git_html}</p>
<p class="note">If the rule changed more than once: first live thin-first is this 24 Oct restart. The 26 Oct change is a send-path latency fix, not a new size-order rule. Size remains the primary hard-leg signal.</p>
{mix_note}

<h2>Rates (denominator = first fills)</h2>
<p class="note">Click column headers to sort. Empty IOC is not in the percent. First-miss then second-fill can only happen on simultaneous duals (before); after thin-first a hard miss does not send easy, so that path is empty IOC.</p>
{table(
    [
        ("Period", "text"),
        ("Dual attempts", "num"),
        ("Empty IOC", "num"),
        ("Both fill", "num"),
        ("First miss, second fill", "num"),
        ("N first-fills", "num"),
        ("N second-misses", "num"),
        ("% second-miss | first fill", "num"),
        ("% one-sided | any fill", "num"),
        ("Second posted and missed", "num"),
        ("Second never posted", "num"),
        ("Then flattened", "num"),
        ("Then leftover", "num"),
        ("With-fee avg P&L $", "num"),
        ("N with P&L", "num"),
    ],
    summary_rows,
)}

<h2>How we counted</h2>
<ol>
<li>Lock gap (A) only. Tennis crossover / CFB favorite / T0 spreads / tennis T0 dog rows are out.</li>
<li>One attempt = one claim that posted at least one dual IOC (or a <code>hard_miss_abort</code>).</li>
<li>Dual IOC legs are <code>hard</code> / <code>easy</code> after thin-first, and <code>websocket</code> / <code>book</code> / <code>midway</code> / <code>simultaneous</code> before. Flatten, leftover watch, and recovery are not the second lock order.</li>
<li>Fill truth is venue confirm qty ≥ 1 (Kalshi 201 with fill_count 0 is a miss. Polymarket HTTP 200 is not a fill by itself).</li>
<li>Before: first vs second is send time of each shop’s first dual HTTP. After: first = hard (thin), second = easy (thick).</li>
<li>Second miss = first filled and the other shop did not venue-fill on that dual (posted miss, or never posted because the gap closed and we flattened).</li>
<li>With-fee P&amp;L is from <code>settled_pnl.json</code> on the filled dual / flatten order ids. Open leftovers are omitted from the average.</li>
</ol>

<h2>Before: first-fill then second-miss</h2>
<p class="note">{esc(len(miss_rows_before))} rows. Click column headers to sort.</p>
{miss_table(miss_rows_before)}

<h2>After: first-fill then second-miss</h2>
<p class="note">{esc(len(miss_rows_after))} rows. Click column headers to sort.</p>
{miss_table(miss_rows_after)}

<h2>After: both dual IOCs filled</h2>
<p class="note">{esc(sa['both_fill'])} true locks on the original dual (leftover-watch completions are not in this table). Click column headers to sort.</p>
{table(
    [
        ("Send ET", "date"),
        ("Sport", "text"),
        ("Game", "text"),
        ("Market", "text"),
        ("First / thin", "text"),
        ("Second / thick", "text"),
        ("First size", "num"),
        ("Second size", "num"),
        ("Send rule", "text"),
    ],
    [
        [
            a["send_at"].strftime("%Y-%m-%d %H:%M:%S") if a["send_at"] else "",
            a["sport"],
            a["game"],
            a["market"],
            a["first_venue"],
            a["second_venue"] or "—",
            a["first_size"] or "—",
            a["second_size"] or "—",
            "thin-first" if a["thin_first"] else "simultaneous",
        ]
        for a in after
        if a["outcome"] == "both_fill"
    ],
)}

<p class="tiny">Data: local <code>orders.jsonl</code> (venue confirm on each sent row), <code>settled_pnl.json</code>,
<code>lock_hard_leg_first_20261024.html</code>, <code>lock_quiet_since_20261021.html</code>.
Manual: <code>python tools/_write_lock_gap_thin_first_oneleg_20261029.py</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    print(
        f"before {sb['rate']} {sb['n_second_miss']}/{sb['n_first_fill']} "
        f"after {sa['rate']} {sa['n_second_miss']}/{sa['n_first_fill']} "
        f"cutover {fmt_ts(cutover)} page {PAGE}",
        flush=True,
    )
    return PAGE


if __name__ == "__main__":
    write_page()
